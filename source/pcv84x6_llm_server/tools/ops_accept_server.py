"""Acceptance harness: run the real service with a DELIBERATELY slow load.

The point is a model load that really takes seconds, so a browser can be
reloaded in the middle of one and the backend's `operation` observed from a
fresh page -- which is the exact scenario the console used to get wrong.

The delay is injected by wrapping `ModelManager._wait_ready`; the worker itself
is the normal mock backend, so everything else (spawning, the RPC client, the
operation bookkeeping) is the real code path.

    python3 tools/ops_accept_server.py [--port 18200] [--delay 8] [--root DIR]

Then, in another shell:

    python3 tools/ops_refresh_browser_check.py http://127.0.0.1:18200
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import uvicorn  # noqa: E402

from app.core.models import ModelManager  # noqa: E402
from app.main import create_app  # noqa: E402


def make_app(root: Path, delay: float, port: int):
    models = root / "models"
    # One model directory with a fake .bmodel: enough for discovery and for a
    # mock worker to start, small enough to commit to a temp tree.
    model = models / "qwen-demo"
    (model / "config").mkdir(parents=True, exist_ok=True)
    (model / "qwen-demo-seq32768-4core.bmodel").write_bytes(b"\\0" * 4096)
    (model / "config" / "config.json").write_text("{}")
    (model / "config" / "tokenizer.json").write_text("{}")

    original = ModelManager._wait_ready

    async def slow_wait(self, port_, timeout, proc):
        ok = await original(self, port_, timeout, proc)
        if ok:
            await asyncio.sleep(delay)  # the load stays "loading" this much longer
        return ok

    ModelManager._wait_ready = slow_wait
    return create_app(
        data_dir=root / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=BASE / "web" / "dist",
        context_length_override=32768,
        data_root=root / "runtime",
        service_port=port,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=18200)
    p.add_argument("--delay", type=float, default=8.0,
                   help="extra seconds a load stays in the loading state")
    p.add_argument("--root", default=None,
                   help="scratch directory (default: a temp dir)")
    args = p.parse_args()

    root = Path(args.root) if args.root else Path(
        __import__("tempfile").mkdtemp(prefix="ops-accept-"))
    root.mkdir(parents=True, exist_ok=True)
    app = make_app(root, args.delay, args.port)
    print(f"serving on http://127.0.0.1:{args.port}  root={root}  "
          f"load delay={args.delay}s", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
