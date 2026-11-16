#!/usr/bin/env python3
"""Board half of the MYS-2681 alignment: raw token ids out of the **product**
engine (``cv_vl_*``), on the product's own pixels and prompt.

The prototype (``vl_native``) and the resident engine are two transcriptions of
the same arithmetic. On ``mixed_spec`` they part company at position 14 -- a
0.22-logit near-tie -- so an alignment measured on the prototype would blame the
preprocessing change for something the product does not do. What matters is the
shipped engine, so this drives it directly: the same ``preprocess_image``, the
same ``render_prompt``, the same tokenizer the worker uses, and it records the
raw ids (never text, which decode->encode cannot round-trip).

One element per process, and the element's model must be *unloaded* from the
service first: two VL engines on one NPU is not a comparison, it is two programs
sharing a device. On 10155 the service's own copy has to be unloaded with
``POST /api/models/<id>/unload`` before this runs.

    python3 tools/ocr/board_engine_tokens.py --work DIR --only cn_notice \
        --bmodel /data/vl.bmodel --lib PREFIX/lib/libcv84x6_llm.so --out out/
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from pathlib import Path


async def run(args) -> int:
    sys.path.insert(0, "/opt/sophon/sophon-opencv_2.3.0/opencv-python")
    sys.path.insert(0, args.install_dir)
    from app.engine import paddle_vl as vl

    backend = vl.PaddleVlBackend(
        model_path=args.bmodel,
        tokenizer_path=args.install_dir + "/model-config/paddleocr_vl_1_5/tokenizer.json",
        model_id="vl-2681", lib_path=args.lib)
    out = {}
    try:
        dirs = sorted(p for p in args.work.iterdir() if p.is_dir())
        if args.only:
            dirs = [p for p in dirs if p.name == args.only]
        for d in dirs:
            prep = json.loads((d / "prep.json").read_text(encoding="utf-8"))
            blob = (d / "crop.png").read_bytes()
            prompt, images = vl.render_prompt([{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64,"
                                      + base64.b64encode(blob).decode()}},
                {"type": "text", "text": prep["prompt"]},
            ]}])
            encoded = await backend.encode(prompt, [base64.b64decode(images[0])])
            session = await backend.new_session_for(encoded)
            await session.feed_prompt([])
            ids: list[int] = []
            for _ in range(args.max_new):
                tok = await session.step()
                if session.is_stop_token(tok):
                    break
                ids.append(tok)
            out[d.name] = {"tokens": ids,
                           "text": backend.tokenizer_decode(ids),
                           "grid": list(encoded.image["grid"]),
                           "prompt_tokens": len(encoded)}
            print(f"{d.name}: {len(ids)} tokens "
                  f"{backend.tokenizer_decode(ids)[:50]!r}", flush=True)
    finally:
        backend.close()
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)   # the engine's KV is process-wide; exit without a slow teardown
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path,
                    help="one dir per element: crop.png + prep.json, as vl_align prep writes")
    ap.add_argument("--only", default=None,
                    help="one element name; one process per element, the way "
                         "MYS-2660 launched the prototype")
    ap.add_argument("--install-dir", default="/data/mys2681/side")
    ap.add_argument("--bmodel", required=True)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-new", type=int, default=512)
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
