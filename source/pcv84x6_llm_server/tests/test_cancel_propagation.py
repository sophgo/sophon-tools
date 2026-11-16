"""Client hang-up must free the model, not leave it decoding into the void.

On this chip a leaked generation keeps a session's KV alive and burns NPU time,
so this is a correctness property, not a nicety.
"""

import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_worker_drops_session_on_disconnect():
    """Closing the socket must leave the worker with zero active requests."""
    port = 18944
    # A per-token delay keeps the request in flight long enough to hang up on it
    # mid-stream. Without it the mock finishes before we can disconnect, and the
    # test would pass without ever exercising cancellation.
    proc = await asyncio.create_subprocess_exec(
        "python3", "-m", "app.engine.worker",
        "--model-id", "m", "--port", str(port), "--backend", "mock",
        "--context-length", "4096", "--max-concurrent", "4",
        "--decode-delay-ms", "20",
        # Never emit the stop token, so the only way this request can end is the
        # cancellation we are testing -- otherwise the mock finishes on its own
        # and the assertion passes for the wrong reason.
        "--mock-min-tokens", "1000000000",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.stdout.readline(), timeout=20)

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write((json.dumps({
            "op": "generate", "req_id": "long",
            "prompt": "a prompt", "params": {"max_tokens": 100000},
        }) + "\n").encode())
        await writer.drain()

        # Confirm it is genuinely mid-flight before hanging up, otherwise this
        # test can pass for the wrong reason.
        first = json.loads(await asyncio.wait_for(reader.readline(), timeout=10))
        assert first["req_id"] == "long"

        writer.close()
        await writer.wait_closed()

        # A fresh connection must report nothing active: the worker cancelled the
        # orphaned request when the first connection hit EOF.
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        stats = {}
        for _ in range(100):
            w2.write(b'{"op":"stats"}\n')
            await w2.drain()
            stats = json.loads(await asyncio.wait_for(r2.readline(), timeout=10))
            if stats.get("active", 0) == 0:
                break
            await asyncio.sleep(0.05)
        w2.close()
        assert stats["active"] == 0, f"orphaned request still running: {stats}"
        assert stats.get("cancelled_requests", 0) >= 1, stats
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
