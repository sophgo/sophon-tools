# Qwen3-ASR on CV84X6

Two things live here: how the bmodel is compiled, and how the golden data the
numpy front end is tested against is produced. The front end itself is
`app/engine/asr_audio.py` and `app/engine/asr_prompt.py`.

Reference implementation: `sophgo/LLM-TPU`, `models/Qwen3_ASR/`.

## Compiling the bmodel

Official CV84X6 builds do not exist for this model — LLM-TPU publishes bm1684x
(1 device) and bm1688 versions only — so they are compiled here with the
tpuc22 container's tpu-mlir 1.30.2, which already ships `Qwen3AsrConverter` and
accepts `-c bm1684x2`.

```bash
# 1. weights, on the host (ModelScope is reachable, Docker Hub is not reliable)
modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir Qwen3-ASR-1.7B
modelscope download --model Qwen/Qwen3-ASR-0.6B --local_dir Qwen3-ASR-0.6B

# 2. compile (both sizes, same flags)
tools/asr/build_bmodel.sh /workspace/asr/weights/Qwen3-ASR-0.6B /workspace/asr/out/qwen3_asr_06b
tools/asr/build_bmodel.sh /workspace/asr/weights/Qwen3-ASR-1.7B /workspace/asr/out/qwen3_asr_17b
```

`build_bmodel.sh` runs the equivalent of

```bash
llm_convert.py -m <weights> -s 1024 --max_input_length 512 --quantize bf16 \
               -c bm1684x2 --out_dir <out> --qwen_asr
```

through `asr_convert.py`, a shim that exists for one reason: the container's
`Qwen3AsrConverter.__init__` takes `(args, config)` while its `llm_convert.py`
calls the converter with `loader=`. `LlmConverter` already builds a
`SafetensorsModelHandle` itself when `loader is None`, so dropping the keyword
changes nothing for a safetensors checkpoint. The shim patches that class in
memory instead of editing the container's site-packages, because the 35B builds
share the same environment.

The container also needs a venv with `transformers==4.57.6` and `qwen_asr` (the
converter registers the model type), because the base image's transformers does
not know `qwen3_asr`:

```bash
docker exec tpuc22 python3 -m venv --system-site-packages /workspace/asr-venv
docker exec tpuc22 /workspace/asr-venv/bin/pip install -r tools/asr/requirements-build.txt
```

`nagisa` (a qwen_asr dependency, only used by the forced aligner) needs dyNET,
which has no wheel. A stub on `PYTHONPATH` is enough; conversion never touches
alignment. See `/workspace/asr/stub/nagisa/__init__.py` in the build tree.

### What the flags mean for the runtime

| Field | Value | Where it comes from |
|---|---|---|
| `SEQLEN` | 1024 | `-s`; the KV cache length, so the decode budget after the prompt |
| `MAX_INPUT_LENGTH` | 512 | `--max_input_length`; the prefill width, and the largest prompt |
| `AUDIO_LENGTH` | 100 | `audio` net input `[1, 1, 128, 100]` — mel frames per tower call |
| audio tokens per call | 13 | `audio` net output `[1, 13, hidden]` |

A full run took 39 s (0.6B) / 78 s (1.7B) from first sub-model to the combined
bmodel, on a 20-way parallel deploy; MLIR export and weight loading run before
that and dominate wall-clock on a cold container.

`AUDIO_LENGTH = 100` is `n_window * 2` from the model config: 100 mel frames at
a 10 ms hop is 1 s, and 13 tokens per second is the constant the reference
pipeline hard-codes as `audio_tokens_per_chunk`.

A 512-token prefill therefore covers roughly **38 s of audio**: about 15 tokens
of chat scaffolding plus 13 per second. `SEQLEN` 1024 leaves the rest for the
transcript. Longer clips have to be split by the caller and the results joined —
`app/engine/asr_prompt.py` exposes the arithmetic (`audio_token_count`) so the
caller can decide where to cut.

### Building the runtime venv offline

The build container has no reliable PyPI path; wheels were staged by hand:

```bash
pip download --no-deps -d wheels transformers==4.57.6 huggingface-hub==0.36.0 \
    qwen-asr nagisa soynlp requests urllib3 certifi charset-normalizer idna \
    filelock pyyaml regex tqdm packaging typing-extensions fsspec safetensors \
    librosa soundfile soxr audioread pooch joblib scikit-learn threadpoolctl \
    decorator lazy-loader msgpack numba llvmlite cffi pycparser
docker cp wheels tpuc22:/workspace/asr/wheels
docker exec tpuc22 /workspace/asr-venv/bin/pip install --no-index \
    --find-links /workspace/asr/wheels --ignore-installed --no-deps <packages>
```

`--ignore-installed` is required: with `--system-site-packages`, pip treats the
image's `transformers 5.6.2` as satisfying the requirement and installs nothing.

## Golden data

`tools/asr/make_golden.py` regenerates `tests/data/asr/` from the reference
stack. It needs an x86 box with torch, not the board:

```bash
python3 -m venv /tmp/asr-golden
/tmp/asr-golden/bin/pip install torch==2.4.1 transformers==4.57.6 qwen_asr librosa numpy
/tmp/asr-golden/bin/python tools/asr/make_golden.py \
    --llm-tpu /path/to/LLM-TPU --out tests/data/asr
```

It writes three files, 1.9 MiB total (the budget is 3):

| File | Contents |
|---|---|
| `features.npz` | log-mel features for 8 clips, and the waveforms behind them |
| `prompts.json` | `input_ids` and the audio BOS offset, 24 combinations |
| `meta.json` | per-case frame counts, durations, the quantisation scale |

### Measured agreement

Against `WhisperFeatureExtractor`, `log_mel` on the same 16 kHz waveform:

| Clip | Max abs error |
|---|---|
| `asr_zh.wav` (4.2 s) | < 1e-4 |
| `asr_en.wav` (15.1 s) | < 1e-4 |
| sine 3 s / 17 s | < 1e-4 |

Against `librosa.resample` (soxr), compared through the mel front end — the
waveforms themselves differ by design, both are valid reconstructions:

| Input rate | Mean abs log-mel error |
|---|---|
| 8 kHz | 0.0055 |
| 22.05 kHz | 0.0016 |
| 44.1 kHz | 0.0017 |
| 48 kHz | 0.0017 |

The task allows 0.02; the test asserts 0.01 so a regression trips early. 8 kHz
is the worst case because upsampling leaves the images above 4 kHz to the
interpolator's rolloff, which soxr and this Kaiser window place slightly
differently.

Against `Qwen3ASRProcessor`, `build_prompt` returns identical `input_ids` and
the same audio BOS offset for all 24 audio × language × context combinations.

### Two storage details that are not obvious

**Features are int16, quantised before storage** (`FEATURE_SCALE = 8192`), which
puts the quantisation step at 1.2e-4 — under the 1e-4 *test* tolerance only
because the test compares against the same quantised values. Storing float32
would be 4x the size for a budget of 3 MiB.

**The waveform is stored int16 and the features are extracted from the
round-tripped float**, not from the original. A 3e-5 step in a near-silent
frame moves `log10` by 3e-2, so extracting from the original would encode a
precision the stored array cannot carry and the test would measure int16
quantisation instead of the front end.

## Board verification

`.151`, `bmrt_test --bmodel <0.6B> --loopnum 1`: all 60 networks loaded and
ran, no architecture mismatch. The audio network takes `[1, 1, 128, 100]` f32
and returns `[1, 13, 1024]` bf16 in 5.8 ms; one decoder block takes 2.5 ms.
