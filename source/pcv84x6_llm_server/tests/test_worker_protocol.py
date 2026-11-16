"""End-to-end test of the worker's JSON-lines protocol over a real socket."""

import asyncio
import json

import pytest

from app.engine import worker


async def start_worker(port, model_id="test-model", context_length=4096):
    proc = await asyncio.create_subprocess_exec(
        "python3", "-m", "app.engine.worker",
        "--model-id", model_id,
        "--port", str(port),
        "--backend", "mock",
        "--max-concurrent", "4",
        "--context-length", str(context_length),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Wait for the ready banner before connecting.
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=20)
    evt = json.loads(line)
    assert evt["event"] == "ready"
    return proc


async def rpc(reader, writer, obj):
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=20)
    return json.loads(line)


@pytest.mark.asyncio
async def test_health_and_generate_stream():
    port = 18931
    proc = await start_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        h = await rpc(reader, writer, {"op": "health"})
        assert h["ok"] is True and h["model"] == "test-model"

        writer.write((json.dumps({
            "op": "generate", "req_id": "r1",
            "prompt": "hello board", "params": {"max_tokens": 3},
        }) + "\n").encode())
        await writer.drain()

        ops = []
        while True:
            msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=20))
            ops.append(msg["op"])
            if msg["op"] in ("done", "error"):
                final = msg
                break
        assert ops[0] == "meta"
        assert "delta" in ops
        assert final["op"] == "done"
        assert final["prompt_tokens"] > 0
        assert final["completion_tokens"] >= 1
        assert final["first_token_latency_s"] is not None
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_two_requests_interleave_on_one_connection():
    port = 18932
    proc = await start_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        for rid in ("a", "b"):
            writer.write((json.dumps({
                "op": "generate", "req_id": rid,
                "prompt": f"prompt {rid}", "params": {"max_tokens": 3},
            }) + "\n").encode())
        await writer.drain()
        seen = {}
        while len(seen) < 2 or not all(v for v in seen.values()):
            msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=20))
            if msg["op"] == "done":
                seen[msg["req_id"]] = True
        assert set(seen) == {"a", "b"}
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_context_overflow_is_reported_not_crashed():
    port = 18933
    proc = await start_worker(port, context_length=64)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        h = await rpc(reader, writer, {"op": "health"})
        limit = h["context_length"]
        # Mock encoding is ~4 chars/token, so this is comfortably over the limit.
        writer.write((json.dumps({
            "op": "generate", "req_id": "big",
            "prompt": "x" * (limit * 8), "params": {"max_tokens": 1},
        }) + "\n").encode())
        await writer.drain()
        msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=30))
        assert msg["op"] == "error"
        assert "context limit" in msg["message"]
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


async def test_large_request_line_is_accepted():
    """A base64 photo makes one protocol line far larger than 64 KiB."""
    port = 18934
    proc = await start_worker(port, context_length=4096)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port, limit=1 << 26)
        await rpc(reader, writer, {"op": "health"})
        writer.write((json.dumps({
            "op": "generate", "req_id": "big-line",
            "prompt": "hi " + "x" * 300_000, "params": {"max_tokens": 1},
        }) + "\n").encode())
        await writer.drain()
        msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=30))
        # Whatever the verdict (too long for the context here), the worker must
        # answer instead of dropping the connection.
        assert msg["req_id"] == "big-line"
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_health_reports_the_worker_own_readiness_not_a_constant():
    """`loaded` in the health reply is a state, not a literal (MYS-2496).

    The manager treats one answered health probe as the readiness handshake, so
    the reply must actually mean "the engine is up". A worker that never set its
    readiness flag is the case a hard-coded ``"loaded": true`` would have
    vouched for; ``serve`` is driven directly here because a real worker only
    serves after it is ready, which is exactly the point.
    """
    from app.engine.mock import MockBackend
    from app.engine.prefix_cache import PrefixCache
    from app.engine.scheduler import Scheduler

    backend = MockBackend("m", context_length=512)
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=1))
    await sched.start()

    async def one(ready):
        server = await asyncio.start_server(
            lambda r, w: worker.serve(r, w, sched, backend, "m", ready),
            host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b'{"op":"health"}\n')
            await writer.drain()
            reply = json.loads(await asyncio.wait_for(reader.readline(), timeout=10))
            writer.close()
            return reply
        finally:
            server.close()
            await server.wait_closed()

    try:
        not_ready = await one(asyncio.Event())        # never set
        assert not_ready["ok"] is True
        assert not_ready["loaded"] is False, (
            "a worker that is not ready must not vouch for itself")

        flag = asyncio.Event()
        flag.set()
        ready = await one(flag)
        assert ready["loaded"] is True
        # The capabilities travel with the readiness claim.
        assert ready["model"] == "m"
        assert ready["context_length"] == 512
    finally:
        await sched.stop()


# ---------------------------------------------------------------------------
# the streaming transcription op
# ---------------------------------------------------------------------------
def _wav(seconds: float, rate: int = 16000) -> bytes:
    import io
    import math as _math
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * _math.sin(2 * _math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))))
    return buf.getvalue()


async def start_asr_worker(port, **env):
    """The mock ASR worker: decodes and segments for real, invents the words."""
    import os

    proc = await asyncio.create_subprocess_exec(
        "python3", "-m", "app.engine.worker",
        "--model-id", "asr-mock",
        "--port", str(port),
        "--backend", "mock",
        "--kind", "asr",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env},
    )
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=20)
    evt = json.loads(line)
    assert evt["event"] == "ready"
    return proc


async def _drain(reader, stop_ops=("done", "error", "transcript"), timeout=60):
    """Every frame up to and including a terminal one."""
    frames = []
    while True:
        msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=timeout))
        frames.append(msg)
        if msg["op"] in stop_ops:
            return frames


@pytest.mark.asyncio
async def test_transcribe_stream_frames_meta_segment_done():
    import base64

    port = 18941
    proc = await start_asr_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await rpc(reader, writer, {"op": "health"})
        writer.write((json.dumps({
            "op": "transcribe_stream", "req_id": "s1",
            "audio_b64": base64.b64encode(_wav(75.0)).decode(),
            "filename": "a.wav",
        }) + "\n").encode())
        await writer.drain()
        frames = await _drain(reader)

        assert [f["op"] for f in frames] == ["meta", "segment", "segment",
                                             "segment", "done"]
        meta = frames[0]
        assert meta["segments_total"] == 3
        assert meta["segment_seconds"] == 30
        assert meta["duration"] == pytest.approx(75.0, abs=0.05)
        assert meta["language"] is None
        # Segment ids are the position, so a client can render them out of order
        # if it ever has to.
        assert [f["id"] for f in frames[1:-1]] == [0, 1, 2]
        assert all(f["text"] for f in frames[1:-1])
        done = frames[-1]
        assert done["text"] == " ".join(f["text"] for f in frames[1:-1])
        assert done["infer_seconds"] > 0
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_transcribe_stream_agrees_with_transcribe_on_the_same_bytes():
    """Both ops over one connection and one file: same text, same segments."""
    import base64

    port = 18942
    proc = await start_asr_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await rpc(reader, writer, {"op": "health"})
        payload = base64.b64encode(_wav(45.0)).decode()
        for rid, op in (("plain", "transcribe"), ("stream", "transcribe_stream")):
            writer.write((json.dumps({
                "op": op, "req_id": rid, "audio_b64": payload,
                "filename": "a.wav",
            }) + "\n").encode())
            await writer.drain()
            frames = await _drain(reader)
            if op == "transcribe":
                plain = frames[-1]
            else:
                streamed = frames
        assert plain["op"] == "transcript"
        assert streamed[-1]["op"] == "done"
        assert streamed[-1]["text"] == plain["text"]
        assert [(s["start"], s["end"], s["text"]) for s in plain["segments"]] == [
            (s["start"], s["end"], s["text"]) for s in streamed[1:-1]]
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_transcribe_stream_refuses_undecodable_audio_as_an_error_frame():
    """The refusal arrives before ``meta``, which is what lets the API use 415."""
    import base64

    port = 18943
    proc = await start_asr_worker(port, CV84X6_FFMPEG="/nonexistent/ffmpeg")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await rpc(reader, writer, {"op": "health"})
        writer.write((json.dumps({
            "op": "transcribe_stream", "req_id": "bad",
            "audio_b64": base64.b64encode(b"ID3 not really an mp3").decode(),
            "filename": "a.mp3",
        }) + "\n").encode())
        await writer.drain()
        frames = await _drain(reader)
        assert [f["op"] for f in frames] == ["error"], "no meta before a refusal"
        assert frames[0]["kind"] == "unsupported_audio"
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_transcribe_stream_is_refused_by_a_non_asr_worker():
    port = 18944
    proc = await start_worker(port, model_id="chatty")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await rpc(reader, writer, {"op": "health"})
        reply = await rpc(reader, writer, {
            "op": "transcribe_stream", "req_id": "nope", "audio_b64": "AAAA"})
        assert reply["op"] == "error"
        assert "不支持" in reply["message"]
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_the_mock_segment_delay_knob_makes_the_stream_pausable():
    """``CV84X6_MOCK_ASR_SEGMENT_MS`` is what the console developer uses.

    Two segments of a 45 s file must take at least the configured 200 ms: that
    is the whole point of the knob, and a value that silently did nothing would
    leave them unable to see the progress or to hang up mid-stream.
    """
    import base64
    import time as _time

    port = 18945
    proc = await start_asr_worker(port, CV84X6_MOCK_ASR_SEGMENT_MS="200")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await rpc(reader, writer, {"op": "health"})
        began = _time.monotonic()
        writer.write((json.dumps({
            "op": "transcribe_stream", "req_id": "slow",
            "audio_b64": base64.b64encode(_wav(45.0)).decode(),
        }) + "\n").encode())
        await writer.drain()
        frames = await _drain(reader)
        elapsed = _time.monotonic() - began
        assert frames[0]["segments_total"] == 2
        assert elapsed >= 0.4, f"the configured pause did not happen ({elapsed:.2f}s)"
        writer.close()
    finally:
        proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_a_backend_oserror_becomes_an_error_frame_not_a_silent_close():
    """A backend I/O failure must be *reported*, not mistaken for a hang-up.

    The handler used to catch ``OSError`` alongside ``ConnectionError`` around
    the whole loop and re-raise, on the theory that either meant "the peer is
    gone". Only a failing socket write means that; an OSError raised by the
    backend (ENOSPC writing the ffmpeg temp file, EACCES starting the binary)
    meant the frame was dropped and the API waited out ``TRANSCRIBE_TIMEOUT_S``
    before answering 503.

    Driven against ``handle_transcribe_stream`` directly with a backend that
    raises, so the assertion is about the handler's classification rather than
    about how to make a real ffmpeg fail on the test machine.
    """
    import base64

    from app.engine import worker as worker_module

    class FailingBackend:
        kind = "asr"

        async def iter_transcribe(self, audio, **kwargs):
            raise OSError(28, "No space left on device")
            yield  # pragma: no cover - makes this an async generator

    written: list[dict] = []

    async def write(obj):
        written.append(obj)

    await worker_module.handle_transcribe_stream(
        FailingBackend(),
        {"req_id": "oserr", "audio_b64": base64.b64encode(b"x").decode()},
        write)

    assert [w["op"] for w in written] == ["error"], (
        "the failure was swallowed instead of reported")
    assert written[0]["kind"] == "server"
    assert "No space left" in written[0]["message"]


@pytest.mark.asyncio
async def test_a_transcribe_stream_refusal_before_meta_is_one_error_frame():
    """Every pre-stream refusal is exactly one ``error`` frame and no ``meta``.

    The endpoint depends on this: it pulls the first frame to decide the HTTP
    status, so a backend that emitted ``meta`` first would force a 200 for a
    request it went on to refuse.
    """
    import base64

    from app.engine import worker as worker_module

    class RefusingBackend:
        kind = "asr"

        async def iter_transcribe(self, audio, **kwargs):
            from app.engine.aux_backend import AuxRequestError
            raise AuxRequestError("音频时长 1801.0 秒超过上限 30 分钟")
            yield  # pragma: no cover

    written: list[dict] = []

    async def write(obj):
        written.append(obj)

    await worker_module.handle_transcribe_stream(
        RefusingBackend(),
        {"req_id": "refused", "audio_b64": base64.b64encode(b"x").decode()},
        write)

    assert [w["op"] for w in written] == ["error"]
    assert written[0]["kind"] == "invalid_request"
