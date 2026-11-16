"""Rapid waves of concurrent requests against one real worker.

    python3 tools/decode_quantum_smoke.py --python /usr/bin/python3.10 \
        --model ... --tokenizer ... --lib ... --waves 10 --sessions 3

Why: the decode quantum changes how often sessions swap in and out of the TPU,
so the thing to rule out is not a single correct answer but churn -- many
sessions created, used and closed back to back, with a short generation each.
Every wave fires `--sessions` requests at once, which the worker admits
concurrently; the quantum then rotates between them. A wave is checked for:
every request finishing, the right token count, the same output across lanes
of the same prompt, and the worker still reporting zero active requests.
Then a fresh wave starts, which is the "register a session, use it, drop it"
cycle that a multi-agent workload produces.

Exits non-zero on the first inconsistency and prints the worker's stats at the
end so a leak (active sessions, failed requests) is visible.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = ("Summarise, in about 150 words and in full sentences, how a small "
          "archive keeps its catalogue consistent with the scans it stores.")


class Client:
    def __init__(self, port: int) -> None:
        self.port = port
        self.queues: dict[str, asyncio.Queue] = {}

    async def __aenter__(self) -> "Client":
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", self.port, limit=64 * 1024 * 1024)
        self.pump = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc) -> None:
        self.pump.cancel()
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    def q(self, rid: str) -> asyncio.Queue:
        return self.queues.setdefault(rid, asyncio.Queue())

    async def _read(self) -> None:
        while True:
            line = await self.reader.readline()
            if not line:
                for q in self.queues.values():
                    await q.put({"op": "eof"})
                return
            msg = json.loads(line)
            rid = msg.get("req_id")
            if rid:
                await self.q(rid).put(msg)

    async def send(self, obj: dict) -> None:
        self.writer.write((json.dumps(obj) + "\n").encode())
        await self.writer.drain()

    async def rpc(self, op: str, **fields) -> dict:
        rid = f"__{op}__"
        await self.send({"op": op, "req_id": rid, **fields})
        return await asyncio.wait_for(self.q(rid).get(), timeout=60)

    async def one(self, rid: str, max_tokens: int) -> dict:
        await self.send({"op": "generate", "req_id": rid, "prompt": PROMPT,
                         "params": {"max_tokens": max_tokens}})
        chunks: list[str] = []
        while True:
            msg = await asyncio.wait_for(self.q(rid).get(), timeout=900)
            if msg.get("op") == "eof":
                return {"error": "worker closed the connection", "chunks": chunks}
            if msg.get("op") == "delta":
                chunks.append(msg["text"])
            elif msg.get("op") in ("done", "error"):
                return {"done": msg, "chunks": chunks}


async def main_async(args) -> int:
    argv = [
        args.python, "-m", "app.engine.worker",
        "--model-id", args.model_id, "--port", str(args.port),
        "--backend", "native", "--model-path", args.model,
        "--tokenizer-path", args.tokenizer, "--native-lib", args.lib,
        "--max-concurrent", str(args.sessions),
        "--no-prefix-cache",
        "--decode-quantum", str(args.quantum),
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=HERE)
    failures: list[str] = []
    try:
        banner = await asyncio.wait_for(proc.stdout.readline(), timeout=900)
        if b'"ready"' not in banner:
            err = (await proc.stderr.read()).decode()[-800:]
            raise SystemExit(f"worker did not start: {banner!r} {err}")
        async with Client(args.port) as c:
            await c.one("__warmup__", 8)
            reference: list[str] | None = None
            for wave in range(1, args.waves + 1):
                runs = await asyncio.gather(*(
                    c.one(f"w{wave}-s{i}", args.decode) for i in range(args.sessions)))
                for i, r in enumerate(runs):
                    done = r.get("done") or {}
                    if done.get("op") != "done":
                        failures.append(f"wave {wave} lane {i}: {done.get('message', r)}")
                        continue
                    got = done.get("completion_tokens", 0)
                    if got < args.decode // 2:
                        failures.append(f"wave {wave} lane {i}: only {got} tokens "
                                        f"({done.get('finish_reason')})")
                    if reference is None:
                        reference = r["chunks"]
                    elif r["chunks"] != reference:
                        failures.append(f"wave {wave} lane {i}: output differs from "
                                        f"the first wave")
                stats = await c.rpc("stats")
                if stats.get("active"):
                    failures.append(f"wave {wave}: {stats['active']} session(s) still "
                                    f"active after the wave finished")
                if stats.get("failed_requests"):
                    failures.append(f"wave {wave}: {stats['failed_requests']} failed request(s)")
                print(f"  wave {wave:2d}/{args.waves}: {args.sessions} session(s), "
                      f"{sum(len(r['chunks']) for r in runs)} tokens, "
                      f"active={stats.get('active')} "
                      f"queued={stats.get('queued')} "
                      f"cancelled={stats.get('cancelled_requests')}", flush=True)
            stats = await c.rpc("stats")
            print(f"\nfinal: requests={stats.get('total_requests')} "
                  f"failed={stats.get('failed_requests')} "
                  f"cancelled={stats.get('cancelled_requests')} "
                  f"active={stats.get('active')} quantum={stats.get('decode_quantum')}",
                  flush=True)
            await c.send({"op": "shutdown"})
    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    if failures:
        print("\nFAIL", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print("\nPASS", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--model", required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--lib", required=True)
    p.add_argument("--model-id", default="qwen3.6-35b-a3b-128k")
    p.add_argument("--port", type=int, default=19101)
    p.add_argument("--quantum", type=int, default=8)
    p.add_argument("--sessions", type=int, default=3)
    p.add_argument("--waves", type=int, default=10)
    p.add_argument("--decode", type=int, default=24)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
