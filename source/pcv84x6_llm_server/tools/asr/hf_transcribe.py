#!/usr/bin/env python3
"""Reference transcriptions from the `qwen_asr` package, as the oracle.

The board's engine is a port of LLM-TPU's ``chat.cpp``, whose pipeline.py drives
it through ``transformers`` + ``qwen_asr``. This script runs that same stack on
CPU, so "the bmodel transcribes correctly" has something independent to mean:
the same file, the same language argument, the same parse rule, compared on the
text.

The reference truncates each file to whole seconds and chunks anything longer
than its own ``MAX_ASR_INPUT_SECONDS``; both are the reference's behaviour, not
this service's, so the comparison is only meaningful per chunk. This script
prints what the reference produced for the *whole* file, plus the per-chunk
split, and leaves the comparison to the caller.

    /home/zzt/workspace/asr-golden-venv/bin/python tools/asr/hf_transcribe.py \\
        --weights /mnt/sda2/cv84x6_llm_server/build_asr/weights/Qwen3-ASR-1.7B \\
        --audio a.wav [b.wav ...] [--language Chinese]

One JSON object per file on stdout, in the order given.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _whole_seconds(path: str) -> float:
    """The duration the reference transcribes: the file's, truncated to seconds."""
    import librosa

    y, _ = librosa.load(path, sr=16000, mono=True)
    return float(int(y.size) // 16000)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", required=True, help="HF weights dir (Qwen3-ASR-*)")
    p.add_argument("--language", default=None,
                   help="forced language name (Chinese / English / ...)")
    p.add_argument("--audio", nargs="+", required=True)
    p.add_argument("--max-new-tokens", type=int, default=440)
    args = p.parse_args()

    import torch
    from qwen_asr import Qwen3ASRModel

    started = time.time()
    model = Qwen3ASRModel.from_pretrained(
        args.weights,
        # CPU float32: this is the oracle, not a performance run. bf16 on a
        # machine without bf16 kernels is slower, not more accurate.
        dtype=torch.float32,
        device_map="cpu",
        max_new_tokens=args.max_new_tokens,
        max_inference_batch_size=1,
    )
    load_seconds = round(time.time() - started, 2)

    for path in args.audio:
        t0 = time.time()
        results = model.transcribe(path, language=args.language)
        result = results[0]
        print(json.dumps({
            "audio": Path(path).name,
            # The reference truncates to whole seconds, which is the length it
            # actually transcribed.
            "duration": _whole_seconds(path),
            "language": result.language,
            "text": result.text,
            "load_seconds": load_seconds,
            "seconds": round(time.time() - t0, 2),
        }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
