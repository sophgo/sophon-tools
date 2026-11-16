"""Audio decoding and log-mel features for Qwen3-ASR, in numpy only.

The board ships no torch, no librosa and no soundfile, so the whole front end of
the ASR pipeline lives here: container decode, resampling to 16 kHz, and the
`WhisperFeatureExtractor` mel front end of ``model-config/qwen3_asr``.

The features have to match what HuggingFace produces for this model, because the
bmodel was compiled against features the reference pipeline generated -- see
``tools/asr/make_golden.py`` and ``tests/test_asr_preprocess.py``.

Two entry points matter to the rest of the service:

``decode_audio``  bytes -> 16 kHz mono float32 waveform in [-1, 1]
``log_mel``       16 kHz waveform -> ``[128, frames]`` float32, valid frames only
"""

from __future__ import annotations

import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

#: Everything downstream (mel filters, the audio tower) is built for this rate.
SAMPLE_RATE = 16000

#: Qwen3-ASR's preprocessor_config.json, mirrored here so the module has no
#: config file to read at import time. ``tests/test_asr_preprocess.py`` asserts
#: these still equal the values in model-config/qwen3_asr/preprocessor_config.json.
N_FFT = 400
HOP_LENGTH = 160
FEATURE_SIZE = 128
CHUNK_LENGTH_S = 30
#: 30 s of 16 kHz audio; the extractor truncates and pads to exactly this.
N_SAMPLES = CHUNK_LENGTH_S * SAMPLE_RATE
#: The extractor's own floor for the mel power, applied before ``log10``.
MEL_FLOOR = 1e-10

_WAV_RIFF = b"RIFF"
_WAV_WAVE = b"WAVE"
# WAVE_FORMAT_* tags we can decode without an external tool.
_FMT_PCM = 0x0001
_FMT_IEEE_FLOAT = 0x0003
_FMT_EXTENSIBLE = 0xFFFE


class UnsupportedAudio(ValueError):
    """The bytes are not audio we can decode on this device."""


# --------------------------------------------------------------------------
# WAV
# --------------------------------------------------------------------------


def _parse_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Decode a RIFF/WAVE blob to ``(float32 [frames, channels], sample_rate)``.

    Handles 8/16/24/32-bit integer PCM and 32-bit IEEE float, in plain or
    WAVE_FORMAT_EXTENSIBLE headers. Deliberately hand-rolled: the board has no
    ``soundfile`` and ``wave`` refuses WAVE_FORMAT_EXTENSIBLE and 24-bit float
    files that clients do send.
    """
    if len(data) < 12 or data[:4] != _WAV_RIFF or data[8:12] != _WAV_WAVE:
        raise UnsupportedAudio("不是 RIFF/WAVE 文件")

    fmt: tuple[int, int, int, int] | None = None  # (format, channels, rate, bits)
    payload: bytes | None = None

    pos = 12
    while pos + 8 <= len(data):
        ckid = data[pos:pos + 4]
        (cksize,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + cksize]
        if ckid == b"fmt ":
            if cksize < 16:
                raise UnsupportedAudio("WAV fmt 块长度异常")
            tag, channels, rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == _FMT_EXTENSIBLE:
                # The real format lives in the first two bytes of the GUID.
                if cksize < 40:
                    raise UnsupportedAudio("WAVE_FORMAT_EXTENSIBLE 头不完整")
                (tag,) = struct.unpack("<H", body[24:26])
            fmt = (tag, channels, rate, bits)
        elif ckid == b"data":
            payload = body
        pos += 8 + cksize + (cksize & 1)  # chunks are word aligned

    if fmt is None:
        raise UnsupportedAudio("WAV 缺少 fmt 块")
    if payload is None:
        raise UnsupportedAudio("WAV 缺少 data 块")

    tag, channels, rate, bits = fmt
    if channels < 1 or channels > 8:
        raise UnsupportedAudio(f"不支持的声道数 {channels}（支持 1–8）")
    if rate <= 0:
        raise UnsupportedAudio(f"不支持的采样率 {rate}")

    if tag == _FMT_PCM:
        if bits == 8:
            raw = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)
            samples = (raw - 128.0) / 128.0
        elif bits == 16:
            samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        elif bits == 24:
            b = np.frombuffer(payload, dtype=np.uint8)
            b = b[: len(b) - len(b) % 3].reshape(-1, 3).astype(np.int32)
            # Sign-extend the 3-byte little-endian word into 32 bits.
            ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
            samples = ints.astype(np.float32) / 8388608.0
        elif bits == 32:
            samples = np.frombuffer(payload, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            raise UnsupportedAudio(f"不支持的 PCM 位深 {bits}（支持 8/16/24/32）")
    elif tag == _FMT_IEEE_FLOAT:
        if bits == 32:
            samples = np.frombuffer(payload, dtype="<f4").astype(np.float32)
        elif bits == 64:
            samples = np.frombuffer(payload, dtype="<f8").astype(np.float32)
        else:
            raise UnsupportedAudio(f"不支持的浮点位深 {bits}（支持 32/64）")
    else:
        raise UnsupportedAudio(f"不支持的 WAV 编码 0x{tag:04x}（支持 PCM / IEEE float）")

    usable = samples.size - samples.size % channels
    if usable == 0:
        raise UnsupportedAudio("音频为空")
    frames = samples[:usable].reshape(-1, channels)
    return frames, rate


#: Where the Sophon SDK installs its ffmpeg. Not on PATH on the target devices;
#: ``sophon-ffmpeg-latest`` is a symlink to the newest versioned directory.
SDK_ROOT = Path("/opt/sophon")


def find_ffmpeg(sdk_root: Path | None = None) -> str | None:
    """Locate an ffmpeg to transcode non-WAV input, or None when there is none.

    The target devices ship ffmpeg from the Sophon SDK, under ``/opt/sophon``
    and *not* on ``PATH``. Looking only at ``shutil.which`` therefore reported
    "no ffmpeg" on boards that have one, so the order is:

    1. ``$CV84X6_FFMPEG`` -- an operator's explicit choice, used as given (an
       override that does not exist is an error, not a reason to fall back: a
       typo must not silently run a different binary);
    2. ``PATH`` -- a distribution install, the x86 dev case;
    3. ``<sdk_root>/sophon-ffmpeg-latest/bin/ffmpeg`` -- the SDK's own link;
    4. ``<sdk_root>/sophon-ffmpeg_*/bin/ffmpeg`` -- highest version wins, for an
       image that ships a version but no ``-latest`` symlink.

    Nothing here installs anything: no apt, no pip, no download. A device
    without ffmpeg really does only get WAV, and says so.

    ``sdk_root`` is a parameter so the search itself is testable on a machine
    that has no ``/opt/sophon``.
    """
    override = os.environ.get("CV84X6_FFMPEG")
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    root = SDK_ROOT if sdk_root is None else Path(sdk_root)
    latest = root / "sophon-ffmpeg-latest" / "bin" / "ffmpeg"
    if latest.is_file() and os.access(latest, os.X_OK):
        return str(latest)
    candidates = []
    for path in root.glob("sophon-ffmpeg_*/bin/ffmpeg"):
        if not (path.is_file() and os.access(path, os.X_OK)):
            continue
        # Sort on the version's numeric parts: plain string order puts _2.10.0
        # before _2.9.0, which would pick the older SDK.
        version = path.parent.parent.name.split("_", 1)[-1]
        key = tuple(int(p) if p.isdigit() else -1 for p in re.split(r"[._-]", version))
        candidates.append((key, str(path)))
    if not candidates:
        return None
    return max(candidates)[1]


#: Upper bound on one ffmpeg transcode. A 50 MB upload (the API's limit) of the
#: slowest container decodes in well under a minute on the board; past this the
#: input is treated as undecodable rather than left to hold the worker.
FFMPEG_TIMEOUT_S = 120


def _decode_with_ffmpeg(data: bytes, filename: str | None) -> tuple[np.ndarray, int]:
    """Transcode any container ffmpeg knows to 16 kHz mono f32le."""
    exe = find_ffmpeg()
    if exe is None:
        raise UnsupportedAudio(
            "仅支持 WAV；本机未找到 ffmpeg（查找顺序：环境变量 CV84X6_FFMPEG、PATH、"
            "/opt/sophon/sophon-ffmpeg-latest、/opt/sophon/sophon-ffmpeg_*），"
            "因此无法解码该格式"
        )
    suffix = Path(filename).suffix if filename else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix) as src:
        src.write(data)
        src.flush()
        try:
            proc = subprocess.run(
                [exe, "-nostdin", "-v", "error", "-i", src.name,
                 "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
                capture_output=True,
                check=False,
                timeout=FFMPEG_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise UnsupportedAudio(f"ffmpeg 解码超过 {FFMPEG_TIMEOUT_S} 秒，放弃该音频") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise UnsupportedAudio("ffmpeg 无法解码该音频" + (f"：{detail[-1]}" if detail else ""))
    samples = np.frombuffer(proc.stdout, dtype="<f4")
    if samples.size == 0:
        raise UnsupportedAudio("音频为空")
    return samples.reshape(-1, 1), SAMPLE_RATE


def decode_audio(data: bytes, filename: str | None = None) -> tuple[np.ndarray, float]:
    """Decode ``data`` to a 16 kHz mono float32 waveform plus its original duration.

    WAV is decoded here; anything else goes through ffmpeg when it is installed
    and raises :class:`UnsupportedAudio` with an actionable message when it is not.
    """
    if not data:
        raise UnsupportedAudio("音频为空")

    if data[:4] == _WAV_RIFF and data[8:12] == _WAV_WAVE:
        frames, rate = _parse_wav(data)
    else:
        frames, rate = _decode_with_ffmpeg(data, filename)

    if frames.shape[0] == 0:
        raise UnsupportedAudio("音频为空")

    duration = frames.shape[0] / float(rate)
    # Averaging channels is what the reference loader does (librosa mono=True).
    mono = frames.mean(axis=1) if frames.shape[1] > 1 else frames[:, 0]
    mono = np.clip(mono.astype(np.float32), -1.0, 1.0)
    return resample(mono, rate, SAMPLE_RATE), duration


# --------------------------------------------------------------------------
# Resampling
# --------------------------------------------------------------------------


def _kaiser(x: np.ndarray, beta: float) -> np.ndarray:
    """Kaiser window evaluated at continuous positions ``x`` in [-1, 1]."""
    inside = np.clip(1.0 - x * x, 0.0, None)
    return np.i0(beta * np.sqrt(inside)) / np.i0(beta)


#: Zeros of the sinc on each side at the original rate. The filter half-width
#: grows as ``_ZEROS / cutoff``, so downsampling gets a proportionally longer
#: kernel. 32 zeros is a 68-tap filter at 48 kHz; going wider buys accuracy the
#: log-mel front end cannot see, at a linear cost in CPU.
_ZEROS = 32
_BETA = 10.0
#: The kernel is cut this much below Nyquist. soxr (what ``librosa.resample``
#: uses by default) rolls off slightly too; matching it halves the log-mel
#: difference at 8 kHz, where the images above 4 kHz would otherwise land in
#: bands the mel bank weights heavily.
_ROLLOFF = 0.95
#: Output samples per block, so the gather stays cache-sized or smaller.
_BLOCK = 65536

#: (sr_in, sr_out) -> (phase table [up, taps], half width, up, down)
_resample_tables: dict[tuple[int, int], tuple[np.ndarray, int, int, int]] = {}


def _phase_table(sr_in: int, sr_out: int) -> tuple[np.ndarray, int, int, int]:
    """Precompute one FIR per polyphase branch.

    For a rational ratio ``up/down`` in lowest terms, output sample ``n`` sits at
    input position ``n*down/up``, so the interpolation kernel only ever depends
    on ``phase = (n*down) % up``. There are at most ``up`` distinct kernels, and
    building them once turns the per-sample work into a table lookup plus a dot
    product -- which is what makes this fast enough to run on the board.
    """
    key = (sr_in, sr_out)
    cached = _resample_tables.get(key)
    if cached is not None:
        return cached

    g = math.gcd(sr_in, sr_out)
    up = sr_out // g
    down = sr_in // g
    cutoff = min(1.0, sr_out / sr_in) * _ROLLOFF
    half = int(math.ceil(_ZEROS / cutoff))
    # Kernel taps relative to the input sample at floor(t_n): one per input
    # sample the window covers, -half+1 .. half.
    offsets = np.arange(-half + 1, half + 1, dtype=np.float64)

    # One row per phase. ``u`` is the signed distance from tap ``offset`` to the
    # output instant, in input-sample units, so the kernel is evaluated at
    # cutoff*u -- the sinc's zero crossings then land every 1/cutoff samples.
    frac = (np.arange(up, dtype=np.float64) / up)[:, None]
    u = frac - offsets[None, :]
    table = cutoff * np.sinc(cutoff * u) * _kaiser(u / half, _BETA)
    # Normalise each branch to unit DC gain: the truncation loses a little area,
    # and an unnormalised filter would leave a faint level error in the mel bins.
    table /= table.sum(axis=1, keepdims=True)

    entry = (table.astype(np.float64), half, up, down)
    _resample_tables[key] = entry
    return entry


def resample(x: np.ndarray, sr_in: int, sr_out: int = SAMPLE_RATE) -> np.ndarray:
    """Band-limited resampling by a rational factor, numpy only.

    Windowed-sinc polyphase interpolation: the signal is reconstructed at the
    output instants with a Kaiser-windowed sinc whose cutoff follows
    ``min(1, sr_out/sr_in)``, which is the anti-aliasing low-pass when
    downsampling. Matches ``librosa.resample`` closely enough for the log-mel
    front end (see ``tools/asr/make_golden.py`` for the measured error); no
    scipy, no soxr, no C extension.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    sr_in = int(sr_in)
    sr_out = int(sr_out)
    if sr_in <= 0 or sr_out <= 0:
        raise ValueError(f"采样率必须为正：{sr_in} -> {sr_out}")
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32)

    table, half, up, down = _phase_table(sr_in, sr_out)
    n_out = int(math.ceil(x.size * up / down))

    # Zero padding keeps the kernel fed past both ends. The right pad has to
    # cover the longest kernel, which is ``2*half`` wide, not just ``half``:
    # the last output sample's kernel reaches ``half`` past its input sample.
    padded = np.pad(x, (half, 2 * half), mode="constant")

    positions = np.arange(n_out, dtype=np.int64) * down
    # ``positions // up`` is the input sample the kernel is centred near; the
    # leading pad shifts it into ``padded`` coordinates.
    base = positions // up + half
    phase = (positions % up).astype(np.int64)
    # Same tap layout the table was built with: -half+1 .. half.
    offsets = np.arange(-half + 1, half + 1, dtype=np.int64)

    out = np.empty(n_out, dtype=np.float64)
    for start in range(0, n_out, _BLOCK):
        stop = min(start + _BLOCK, n_out)
        idx = base[start:stop, None] + offsets[None, :]
        out[start:stop] = np.einsum("ij,ij->i", padded[idx], table[phase[start:stop]])
    return out.astype(np.float32)


# --------------------------------------------------------------------------
# Log-mel
# --------------------------------------------------------------------------


def _hertz_to_mel(freq):
    """Slaney's mel scale, as ``transformers.audio_utils.hertz_to_mel``."""
    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = 27.0 / math.log(6.4)
    freq = np.asarray(freq, dtype=np.float64)
    mels = 3.0 * freq / 200.0
    log_region = freq >= min_log_hertz
    return np.where(log_region, min_log_mel + np.log(np.maximum(freq, 1e-12) / min_log_hertz) * logstep, mels)


def _mel_to_hertz(mels):
    """Inverse of :func:`_hertz_to_mel`."""
    min_log_hertz, min_log_mel = 1000.0, 15.0
    logstep = math.log(6.4) / 27.0
    mels = np.asarray(mels, dtype=np.float64)
    freqs = 200.0 * mels / 3.0
    log_region = mels >= min_log_mel
    return np.where(log_region, min_log_hertz * np.exp(logstep * (mels - min_log_mel)), freqs)


def mel_filter_bank(
    num_frequency_bins: int = N_FFT // 2 + 1,
    num_mel_filters: int = FEATURE_SIZE,
    min_frequency: float = 0.0,
    max_frequency: float = SAMPLE_RATE / 2,
    sampling_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Slaney-normalised triangular mel bank, ``[num_frequency_bins, num_mel_filters]``.

    Bit-for-bit the construction in ``transformers.audio_utils.mel_filter_bank``
    with ``norm="slaney"`` and ``mel_scale="slaney"``, which is what
    WhisperFeatureExtractor uses. ``sampling_rate`` only sets the default
    ``max_frequency``; the bins themselves are evenly spaced to Nyquist.
    """
    mel_min = _hertz_to_mel(min_frequency)
    mel_max = _hertz_to_mel(max_frequency)
    mel_freqs = np.linspace(mel_min, mel_max, num_mel_filters + 2)
    filter_freqs = _mel_to_hertz(mel_freqs)
    fft_freqs = np.linspace(0, sampling_rate // 2, num_frequency_bins)

    filter_diff = np.diff(filter_freqs)
    slopes = filter_freqs[None, :] - fft_freqs[:, None]
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    filters = np.maximum(0.0, np.minimum(down_slopes, up_slopes))

    enorm = 2.0 / (filter_freqs[2:num_mel_filters + 2] - filter_freqs[:num_mel_filters])
    return filters * enorm[None, :]


def _hann_periodic(n: int) -> np.ndarray:
    """``torch.hann_window(n)``: periodic, so ``n+1`` points minus the last."""
    return np.hanning(n + 1)[:n]


def log_mel(audio: np.ndarray) -> np.ndarray:
    """Whisper-style log-mel features for 16 kHz mono audio, valid frames only.

    ``[128, frames]`` float32 with ``frames == ceil(len(audio)/160)``, i.e. the
    ``input_features[:, :, :feature_attention_mask.sum()]`` slice the reference
    pipeline feeds the audio tower. Audio longer than 30 s is truncated, exactly
    as ``WhisperFeatureExtractor`` does -- callers chunk first.

    The chain matches HuggingFace step for step: reflect-pad by ``n_fft//2``,
    periodic Hann, rfft, power, Slaney mel, ``log10`` floored at 1e-10, drop the
    trailing frame, clip to ``max-8``, then ``(x + 4) / 4``.
    """
    audio = np.asarray(audio, dtype=np.float32).ravel()
    if audio.size == 0:
        raise UnsupportedAudio("音频为空")

    frames_out = int(math.ceil(audio.size / HOP_LENGTH))
    # The extractor pads/truncates to a full 30 s before it starts, and the
    # trailing all-zero frames only ever feed the frames we then drop.
    full = np.zeros(N_SAMPLES, dtype=np.float64)
    keep = min(audio.size, N_SAMPLES)
    full[:keep] = audio[:keep]
    frames_out = min(frames_out, N_SAMPLES // HOP_LENGTH)

    pad = N_FFT // 2
    # np.pad(..., mode="reflect") needs len > pad; 480000 samples always are.
    padded = np.pad(full, (pad, pad), mode="reflect")

    # 1 + (480000 - 400)//160 + 1 window starts, minus the frame HF drops.
    n_frames = 1 + (padded.size - N_FFT) // HOP_LENGTH
    window = _hann_periodic(N_FFT)
    index = np.arange(N_FFT)[None, :] + HOP_LENGTH * np.arange(n_frames)[:, None]
    # complex64 is what HF's spectrogram buffer holds, so keep the same rounding.
    spec = np.fft.rfft(padded[index] * window[None, :], axis=1).astype(np.complex64)
    power = np.abs(spec, dtype=np.float64) ** 2.0
    power = power[:-1]  # HF drops the last frame

    mel = power @ mel_filter_bank()
    log_spec = np.log10(np.maximum(mel, MEL_FLOOR)).T  # [128, frames]
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec[:, :frames_out].astype(np.float32)
