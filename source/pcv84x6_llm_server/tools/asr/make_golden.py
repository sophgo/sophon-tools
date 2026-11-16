#!/usr/bin/env python3
"""Generate the ASR preprocess golden set in tests/data/asr/.

Everything here comes from the reference stack (torch + transformers +
qwen_asr + librosa), so the numpy-only front end in ``app/engine/asr_*.py`` has
something independent to be compared against. Run it on an x86 box; the board
never needs this file.

    python3 -m venv /tmp/asr-golden
    /tmp/asr-golden/bin/pip install torch==2.4.1 transformers==4.57.6 \\
        qwen_asr librosa numpy
    /tmp/asr-golden/bin/python tools/asr/make_golden.py \\
        --llm-tpu /home/zzt/workspace/LLM-TPU --out tests/data/asr

``--llm-tpu`` is a checkout of sophgo/LLM-TPU; the two WAVs and the model config
both come from ``models/Qwen3_ASR/``.

Storage: the mel features are quantised to int16 against a per-array scale and
stored in one compressed npz, because float32 would be several megabytes for a
budget of three. ``tests/test_asr_preprocess.py`` uses :func:`load_features` to
undo that, and the quantisation step is far below the 1e-4 tolerance it asserts
(see ``FEATURE_SCALE``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

#: Log-mel values this model produces sit in roughly [-0.4, 1.6]; a scale of
#: 2**13 gives a quantisation step of 1.2e-4 in absolute terms, i.e. well under
#: the 1e-4 *feature* tolerance once the step is halved by rounding.
FEATURE_SCALE = 8192.0

#: The synthetic clips, as (duration seconds, seed). Whole seconds, per the
#: task: the reference pipeline truncates to whole seconds and the golden must
#: not paper over that.
SINE_CASES = ((3.0, 11), (17.0, 12))

#: Input rates for the resampling comparison. Each clip is generated at that
#: rate, resampled by librosa, and the librosa-side features are stored.
RESAMPLE_RATES = (8000, 22050, 44100, 48000)
RESAMPLE_SECONDS = 2.0
RESAMPLE_SEED = 7


def quantise(feats: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(feats, dtype=np.float32) * FEATURE_SCALE).astype(np.int16)


def quantise_wave(wave: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Store a waveform as int16 and return ``(stored, round_tripped_float)``.

    The features are extracted from the *round-tripped* float, not the original:
    otherwise the golden would encode a precision the stored array cannot carry,
    and the test would be measuring int16 error rather than the front end. In
    near-silent frames a 3e-5 waveform step moves ``log10`` by 3e-2, which would
    swamp the 1e-4 tolerance for reasons that have nothing to do with the code
    under test.
    """
    peak = float(np.max(np.abs(wave))) or 1.0
    norm = max(1.0, peak)
    stored = np.round(np.asarray(wave, dtype=np.float32) / norm * 32767.0).astype(np.int16)
    return stored, stored.astype(np.float32) / 32767.0 * norm


def synth(duration: float, seed: int, sr: int = 16000) -> np.ndarray:
    """A deterministic clip: two tones plus a little noise, whole seconds long."""
    t = np.arange(int(round(duration * sr))) / sr
    rng = np.random.default_rng(seed)
    return (
        0.5 * np.sin(2 * np.pi * 220.0 * t)
        + 0.3 * np.sin(2 * np.pi * 1310.0 * t)
        + 0.05 * rng.standard_normal(t.size)
    ).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-tpu", required=True, type=Path,
                    help="checkout of sophgo/LLM-TPU")
    ap.add_argument("--out", required=True, type=Path,
                    help="destination, normally tests/data/asr")
    args = ap.parse_args()

    import librosa
    from transformers.models.whisper.feature_extraction_whisper import WhisperFeatureExtractor

    proc = None
    try:  # only needed for the prompt golden, which needs the model's processor
        import qwen_asr  # noqa: F401  # registers Qwen3ASRProcessor
        from transformers import AutoProcessor

        proc = AutoProcessor.from_pretrained(str(args.llm_tpu / "models/Qwen3_ASR/config"),
                                             fix_mistral_regex=True)
    except Exception as exc:  # pragma: no cover - the mel half is still useful
        print(f"warning: no processor, skipping prompt golden: {exc}", file=sys.stderr)

    fe = WhisperFeatureExtractor(
        feature_size=128, sampling_rate=16000, hop_length=160, chunk_length=30,
        n_fft=400, dither=0.0, return_attention_mask=True, padding_value=0.0,
    )

    def features(wave: np.ndarray) -> np.ndarray:
        """HF features for one 16 kHz clip, valid frames only."""
        out = fe(wave, sampling_rate=16000, return_tensors="np", padding="max_length",
                 truncation=True, max_length=480000, return_attention_mask=True)
        n = int(out["attention_mask"].sum())
        return out["input_features"][0][:, :n]

    args.out.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    meta: dict[str, dict] = {}

    # --- the two reference clips -------------------------------------------
    for name in ("asr_zh", "asr_en"):
        src = args.llm_tpu / "models/Qwen3_ASR/python_demo" / f"{name}.wav"
        raw = src.read_bytes()
        # librosa is the reference loader (pipeline.py uses it), so the golden
        # starts from exactly what the reference would see.
        y, sr = librosa.load(str(src), sr=16000, mono=True)
        y = np.asarray(y, dtype=np.float32)
        stored, y = quantise_wave(y)  # extract from what the test can reconstruct
        feat = features(y)
        arrays[f"{name}_features"] = quantise(feat)
        arrays[f"{name}_wave"] = stored
        meta[name] = {
            "source": str(src.name),
            "source_bytes": len(raw),
            "source_sr": int(librosa.get_samplerate(str(src))),
            "wave_scale": float(max(1.0, float(np.max(np.abs(y))))),
            "duration_s": round(float(y.size) / 16000.0, 6),
            "frames": int(feat.shape[1]),
            "max_abs": round(float(np.abs(feat).max()), 6),
        }
        print(f"{name}: {feat.shape} from {len(raw)} source bytes", flush=True)

    # --- synthetic whole-second clips --------------------------------------
    for duration, seed in SINE_CASES:
        y = synth(duration, seed)
        feat = features(y)
        key = f"sine{int(duration)}s"
        arrays[f"{key}_features"] = quantise(feat)
        meta[key] = {"duration_s": duration, "seed": seed, "frames": int(feat.shape[1])}
        print(f"{key}: {feat.shape}", flush=True)

    # --- resampling: librosa's output features, our resampler's job to match -
    for sr_in in RESAMPLE_RATES:
        n = int(round(RESAMPLE_SECONDS * sr_in))
        y = synth(RESAMPLE_SECONDS, RESAMPLE_SEED, sr=sr_in)[:n]
        stored, y = quantise_wave(y)
        # librosa resamples the *stored* waveform too, so both sides start from
        # the same numbers the test will feed its own resampler.
        y16 = librosa.resample(y, orig_sr=sr_in, target_sr=16000)
        feat = features(y16)
        arrays[f"resample_{sr_in}_features"] = quantise(feat)
        arrays[f"resample_{sr_in}_wave"] = stored
        meta[f"resample_{sr_in}"] = {
            "sr_in": sr_in, "seconds": RESAMPLE_SECONDS, "seed": RESAMPLE_SEED,
            "in_samples": int(y.size), "out_samples": int(y16.size),
            "frames": int(feat.shape[1]),
        }
        print(f"resample {sr_in} Hz: {y.size} -> {y16.size}", flush=True)

    # --- prompts: the processor's input_ids for every case the test uses ----
    if proc is not None:
        tok = proc.tokenizer
        audio_bos = tok.convert_tokens_to_ids(proc.audio_bos_token)
        prompts = {}
        for name in ("asr_zh", "asr_en", *[f"sine{int(d)}s" for d, _ in SINE_CASES]):
            if name in ("asr_zh", "asr_en"):
                y, _ = librosa.load(str(args.llm_tpu / "models/Qwen3_ASR/python_demo" / f"{name}.wav"),
                                    sr=16000, mono=True)
            else:
                duration, seed = next(c for c in SINE_CASES if f"sine{int(c[0])}s" == name)
                y = synth(duration, seed)
            # pipeline.py truncates the waveform to whole seconds first; the
            # prompt golden is only meaningful for inputs where that is a no-op.
            y = np.asarray(y[: (y.size // 16000) * 16000], dtype=np.float32)
            for language in (None, "Chinese", "English"):
                for context in ("", "这是一段会议录音"):
                    messages = [
                        {"role": "system", "content": context},
                        {"role": "user", "content": [{"type": "audio", "audio": ""}]},
                    ]
                    text = proc.apply_chat_template(messages, tokenize=False,
                                                    add_generation_prompt=True)
                    if language is not None:
                        text = text + f"language {language}<asr_text>"
                    out = proc(text=text, audio=[y], return_tensors="np", padding=True)
                    ids = out["input_ids"][0].tolist()
                    key = f"{name}|{language}|{context}"
                    prompts[key] = {
                        "n_audio_tokens": int(np.sum(out["input_ids"][0] ==
                                                     tok.convert_tokens_to_ids(proc.audio_token))),
                        "input_ids": ids,
                        "start_offset": int(np.where(np.asarray(ids) == audio_bos)[0][0]),
                    }
        (args.out / "prompts.json").write_text(
            json.dumps(prompts, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"prompts: {len(prompts)} cases", flush=True)

    np.savez_compressed(args.out / "features.npz", **arrays)
    (args.out / "meta.json").write_text(
        json.dumps({"feature_scale": FEATURE_SCALE, "cases": meta},
                   ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    total = sum(p.stat().st_size for p in args.out.iterdir())
    print(f"\nwrote {args.out}: {total/1024/1024:.2f} MiB")
    for p in sorted(args.out.iterdir()):
        print(f"  {p.name}: {p.stat().st_size/1024:.0f} KiB")
    return 0


def load_features(npz_path: Path, scale: float) -> dict[str, np.ndarray]:
    """Inverse of :func:`quantise`, for the tests."""
    with np.load(npz_path) as z:
        return {k: z[k].astype(np.float32) / scale for k in z.files}


if __name__ == "__main__":
    raise SystemExit(main())
