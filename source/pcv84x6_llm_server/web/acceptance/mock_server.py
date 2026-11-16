#!/usr/bin/env python3
"""Run the console against the mock backend, with data worth looking at.

Purpose: the UI branch must be verifiable without an NPU (and without touching
10.42). This starts the real FastAPI app -- same routes, same auth, same SSE --
with the deterministic mock engine and seeds a little history so the charts and
tables are not empty.

Usage:
    python3 web/acceptance/mock_server.py --port 8765
    # then: http://127.0.0.1:8765 with password admin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MODELS = [
    ("qwen3.6-35b-a3b-32k", "Qwen3.6-35B-A3B 32k（视觉）", "seq32768", True),
    ("qwen3.6-35b-a3b-128k", "Qwen3.6-35B-A3B 128k", "seq131072", False),
]

#: One model of every auxiliary kind (MYS-2599), so each model-page tab and each
#: playground panel has something to show. The kind is read off the bmodel file
#: name, so these are the names the catalogue downloads land as; the mock
#: engine serves all four. OCR is a directory of four networks.
AUX_MODELS = {
    "qwen3-embedding-0.6b": ["qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static.bmodel"],
    "bge-reranker-v2-m3": ["bge-reranker-v2-m3_bf16_seq2048_cv84x6_4core_static.bmodel"],
    "qwen3-asr-0.6b": ["qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static.bmodel"],
    "ppocrv6-medium": [
        "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel",
    ],
}


def seed(root: Path) -> None:
    """Create model directories and a usage history the console can render."""
    models = root / "models"
    for mid, _title, ctx, vision in MODELS:
        d = models / mid / "config"
        d.mkdir(parents=True, exist_ok=True)
        (models / mid / f"{mid}-int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * (1 << 20))
        (d / "config.json").write_text(json.dumps({"vision": vision, "context": ctx}))
    for mid, files in AUX_MODELS.items():
        d = models / mid
        (d / "config").mkdir(parents=True, exist_ok=True)
        (d / "config" / "config.json").write_text("{}")
        for f in files:
            (d / f).write_bytes(b"\x00" * (1 << 16))

    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    now = time.time()
    # A plausible decode curve: ~28 tok/s, dipping when the prompt got longer.
    history = [[round(now - (60 - i) * 45, 1), round(26 + 4 * ((i * 7) % 11) / 10, 2)]
               for i in range(60)]
    (state / "state.json").write_text(json.dumps({
        "usage": {
            "prompt_tokens": 18432,
            "completion_tokens": 9021,
            "cached_tokens": 6400,
            "requests": 37,
            "tps_history": history,
            "cache_hit_rate": 0.31,
        }
    }))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "cv84x6-ui-acceptance"))
    ap.add_argument("--decode-delay-ms", type=float, default=45.0,
                    help="per-token delay, so streaming and the speed chart are observable")
    args = ap.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    seed(root)

    os.environ["CV84X6_BACKEND"] = "mock"
    from app.main import create_app

    app = create_app(
        data_root=root,
        backend_kind="mock",
        web_dir=ROOT / "web" / "dist",
        decode_delay_ms=args.decode_delay_ms,
        context_length_override=32768,
        service_port=args.port,
    )

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
