"""``POST /api/apps/asr/transcriptions/stream`` -- the segment-level SSE endpoint.

What is pinned here is the contract the console's demo page is written against:

* the **frame sequence and its fields** -- ``meta`` first (with the segment count
  and the duration, before any segment text exists), then one ``segment`` per
  stretch in order, then ``done``;
* **agreement with the plain endpoint** -- the segments of a streamed request
  are the segments of its ``verbose_json`` reply, word for word, and ``done.text``
  is that reply's ``text``. This is the assertion the task calls out, and it is
  checked against a real ``/v1/audio/transcriptions`` call over the same bytes,
  not against a second rendering of the same fake;
* **refusals are status codes** -- a format, size, duration, readiness or kind
  problem gets the same code the plain endpoint gives, *before* the stream
  starts, never as the first event of a 200;
* **a disconnect stops between segments** -- no segment after the one that was
  running starts, and the record says ``cancelled`` with the count it reached.

The mock decodes and segments the audio for real (see ``MockAsrBackend``), so
the durations, the boundaries and the 415 are facts about real code.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SAMPLE_RATE = 16000
#: One prompt holds 37 s at this build and the segment cap is 30 s, so a segment
#: is 30 s of audio -- the same number the plain endpoint's tests use.
SEGMENT_SECONDS = 30

STREAM_PATH = "/api/apps/asr/transcriptions/stream"
PLAIN_PATH = "/api/test/audio/transcriptions"
V1_PATH = "/v1/audio/transcriptions"


def make_model(root: Path, name: str, bmodel: str, context: str = "seq1024"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


ASR_BMODEL = "qwen3-asr-0.6b_bf16"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"


def wav_bytes(seconds: float, rate: int = SAMPLE_RATE, freq: float = 440.0,
              bits: int = 16) -> bytes:
    """A mono PCM WAV of ``seconds`` of a sine, as a client would upload."""
    frames = int(round(seconds * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        if bits == 8:
            samples = bytes(
                128 + int(100 * math.sin(2 * math.pi * freq * i / rate))
                for i in range(frames))
        else:
            samples = b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
                for i in range(frames))
        w.writeframes(samples)
    return buf.getvalue()


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "asr-model", ASR_BMODEL)
    make_model(models, "chat-model", CHAT_BMODEL, context="seq2048")
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _login_and_load(client, *model_ids) -> dict:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def _stream(client, *, audio: bytes, filename: str = "a.wav", **fields):
    data = {"model": fields.pop("model", "asr-model")}
    data.update({k: v for k, v in fields.items() if v is not None})
    return client.post(STREAM_PATH, data=data,
                       files={"file": (filename, audio, "application/octet-stream")})


def _plain(client, headers, *, audio: bytes, filename: str = "a.wav", **fields):
    data = {"model": fields.pop("model", "asr-model")}
    data.update({k: v for k, v in fields.items() if v is not None})
    return client.post(V1_PATH, headers=headers, data=data,
                       files={"file": (filename, audio, "application/octet-stream")})


def _frames(response) -> list[dict]:
    """The SSE body's frames, parsed, with the envelope checked."""
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = []
    for chunk in response.text.split("\n\n"):
        if not chunk.strip():
            continue
        assert chunk.startswith("data: "), chunk
        frames.append(json.loads(chunk[len("data: "):]))
    return frames


def _records(client, source=STREAM_PATH) -> list[dict]:
    r = client.get("/api/inference-records", params={"limit": 200})
    assert r.status_code == 200, r.text
    ids = [item["id"] for item in r.json()["items"] if item["source"] == source]
    out = []
    for record_id in ids:
        detail = client.get(f"/api/inference-records/{record_id}")
        assert detail.status_code == 200, detail.text
        out.append(detail.json())
    return out


# ---------------------------------------------------------------------------
# the frame sequence
# ---------------------------------------------------------------------------
def test_frames_are_meta_then_segments_then_done(client):
    _login_and_load(client, "asr-model")
    r = _stream(client, audio=wav_bytes(75.0))
    assert r.status_code == 200, r.text
    frames = _frames(r)

    assert [f["type"] for f in frames] == ["meta", "segment", "segment", "segment", "done"]

    meta, segments, done = frames[0], frames[1:-1], frames[-1]
    assert set(meta) == {"type", "duration", "segments_total", "segment_seconds", "language"}
    assert meta["duration"] == pytest.approx(75.0, abs=0.05)
    assert meta["segments_total"] == len(segments) == math.ceil(75 / SEGMENT_SECONDS)
    assert meta["segment_seconds"] == SEGMENT_SECONDS
    assert meta["language"] is None

    for i, seg in enumerate(segments):
        # The fields the task fixes, and nothing else: a UI that renders these
        # must not have to guess at a shape that changes with the backend.
        assert set(seg) == {"type", "id", "start", "end", "text", "infer_ms"}
        assert seg["id"] == i
        if i:
            assert seg["start"] == pytest.approx(segments[i - 1]["end"], abs=1e-6)
    assert segments[0]["start"] == 0.0
    assert segments[-1]["end"] == pytest.approx(75.0, abs=0.05)
    assert all(seg["text"] for seg in segments)
    assert all(seg["infer_ms"] > 0 for seg in segments)

    assert set(done) == {"type", "text", "language", "duration", "usage", "infer_seconds"}
    assert done["duration"] == pytest.approx(75.0, abs=0.05)
    assert done["text"] == " ".join(seg["text"] for seg in segments)
    assert done["usage"]["total_tokens"] == (
        done["usage"]["prompt_tokens"] + done["usage"]["completion_tokens"])
    assert done["usage"]["completion_tokens"] > 0


def test_a_short_file_is_one_segment(client):
    _login_and_load(client, "asr-model")
    frames = _frames(_stream(client, audio=wav_bytes(2.0)))
    assert [f["type"] for f in frames] == ["meta", "segment", "done"]
    assert frames[0]["segments_total"] == 1
    assert frames[1]["end"] == pytest.approx(2.0, abs=0.05)


def test_the_request_must_carry_an_admin_session(client):
    """No cookie, no stream -- the same gate the other console routes use."""
    r = client.post(STREAM_PATH, data={"model": "asr-model"},
                    files={"file": ("a.wav", wav_bytes(1.0), "audio/wav")})
    assert r.status_code == 401, r.text


def test_a_forced_language_survives_into_meta_and_done(client):
    _login_and_load(client, "asr-model")
    frames = _frames(_stream(client, audio=wav_bytes(2.0), language="zh"))
    assert frames[0]["language"] == "Chinese"
    assert frames[-1]["language"] == "Chinese"


# ---------------------------------------------------------------------------
# streaming and non-streaming must not disagree
# ---------------------------------------------------------------------------
def test_the_streamed_segments_are_the_verbose_json_segments(client):
    """The task's acceptance criterion: same audio, same words, same times.

    Compared against a real ``/v1/audio/transcriptions`` ``verbose_json`` reply
    over the same bytes, so this is a statement about the two endpoints rather
    than about two renderings of one fake.
    """
    headers = _login_and_load(client, "asr-model")
    audio = wav_bytes(75.0)

    frames = _frames(_stream(client, audio=audio))
    plain = _plain(client, headers, audio=audio, response_format="verbose_json")
    assert plain.status_code == 200, plain.text
    body = plain.json()

    streamed = [f for f in frames if f["type"] == "segment"]
    assert len(streamed) == len(body["segments"])
    for got, want in zip(streamed, body["segments"]):
        assert got["id"] == want["id"]
        assert got["text"] == want["text"]
        # Exact, not approximate: both sides round to three decimals, so the
        # two must agree in the last digit as well as in the value. An
        # `approx` here would hide exactly the rounding drift this replaced.
        assert got["start"] == want["start"]
        assert got["end"] == want["end"]

    assert frames[-1]["text"] == body["text"]
    assert frames[-1]["duration"] == body["duration"]
    assert frames[-1]["language"] == body["language"]
    assert frames[-1]["usage"]["prompt_tokens"] == body["usage"]["prompt_tokens"]
    assert frames[-1]["usage"]["completion_tokens"] == body["usage"]["completion_tokens"]


def test_a_context_changes_both_paths_the_same_way(client):
    """A prompt shortens the segment, so it is where the two could drift apart."""
    headers = _login_and_load(client, "asr-model")
    audio = wav_bytes(45.0)
    prompt = "这是一段会议录音" * 20

    frames = _frames(_stream(client, audio=audio, prompt=prompt))
    plain = _plain(client, headers, audio=audio, prompt=prompt,
                   response_format="verbose_json").json()
    assert frames[0]["segment_seconds"] < SEGMENT_SECONDS, "the prompt did not bite"
    assert (frames[0]["segments_total"]
            == len(plain["segments"]) == len([f for f in frames if f["type"] == "segment"]))
    assert frames[-1]["text"] == plain["text"]


# ---------------------------------------------------------------------------
# refusals happen before the stream starts
# ---------------------------------------------------------------------------
def test_an_unloaded_model_is_loaded_on_demand(client):
    """The admission gate is shared, so on-demand loading is shared too.

    MYS-2657: an auxiliary model that is on disk but unloaded is brought up for
    the stream rather than refused, because an auto-unload must not turn the next
    request into a 409. It still happens *before* the first frame -- a load that
    failed would be a status code, never the first event of a 200.
    """
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    client.post("/api/settings", json={"aux_auto_load": True})  # off by default since v0.6.28
    r = _stream(client, audio=wav_bytes(1.0))
    assert r.status_code == 200, r.text


def test_a_chat_model_is_a_400_naming_the_right_endpoint(client):
    _login_and_load(client, "chat-model")
    r = _stream(client, audio=wav_bytes(1.0), model="chat-model")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "chat" in detail and "/v1/chat/completions" in detail


def test_an_unknown_model_is_404(client):
    _login_and_load(client, "asr-model")
    r = _stream(client, audio=wav_bytes(1.0), model="nope")
    assert r.status_code == 404, r.text


def test_an_undecodable_container_is_415_not_a_failed_stream(client, monkeypatch):
    """415 is the code the plain endpoint gives, so the stream must give it too.

    The status matters: a console that got 200 and then an ``error`` frame could
    not tell "your file is not audio" from "the model broke mid-file".
    """
    from app.engine import asr_audio

    monkeypatch.setattr(asr_audio, "find_ffmpeg", lambda: None)
    _login_and_load(client, "asr-model")
    r = _stream(client, audio=b"ID3\x04\x00\x00\x00\x00\x00\x00rawmp3",
                filename="a.mp3")
    assert r.status_code == 415, r.text
    assert "ffmpeg" in r.json()["detail"]


def test_audio_longer_than_the_cap_is_a_400(client):
    _login_and_load(client, "asr-model")
    r = _stream(client, audio=wav_bytes(31 * 60, bits=8))
    assert r.status_code == 400, r.text
    assert "超过上限" in r.json()["detail"]


def test_an_unknown_language_is_a_400_listing_the_names(client):
    _login_and_load(client, "asr-model")
    r = _stream(client, audio=wav_bytes(1.0), language="klingon")
    assert r.status_code == 400, r.text
    assert "Chinese" in r.json()["detail"]


def test_a_missing_model_or_file_is_a_400(client):
    _login_and_load(client, "asr-model")
    no_model = client.post(STREAM_PATH,
                           files={"file": ("a.wav", wav_bytes(1.0), "audio/wav")})
    assert no_model.status_code == 400 and "model" in no_model.json()["detail"]
    # A field-only multipart body, the way the plain endpoint's test sends it:
    # an urlencoded body is refused earlier, as "not multipart".
    no_file = client.post(STREAM_PATH, files={"model": (None, "asr-model")})
    assert no_file.status_code == 400 and "file" in no_file.json()["detail"]


def test_a_non_multipart_body_is_a_400(client):
    _login_and_load(client, "asr-model")
    r = client.post(STREAM_PATH, headers={"Content-Type": "application/json"},
                    content=b'{"model": "asr-model"}')
    assert r.status_code == 400, r.text
    assert "multipart" in r.json()["detail"]


def test_an_oversized_upload_is_refused_before_it_is_read(client):
    """The same bounded reader and the same 400 the plain endpoint gives."""
    from app.api import audio_upload

    _login_and_load(client, "asr-model")
    old = audio_upload.MAX_UPLOAD_BYTES
    audio_upload.MAX_UPLOAD_BYTES = 64 * 1024
    try:
        r = _stream(client, audio=b"\x00" * (256 * 1024))
    finally:
        audio_upload.MAX_UPLOAD_BYTES = old
    assert r.status_code == 400, r.text
    assert "上限" in r.json()["detail"]


def test_a_validation_failure_writes_no_record(client):
    """Nothing reached the NPU, so there is no inference to record."""
    _login_and_load(client, "asr-model")
    before = len(_records(client))
    assert _stream(client, audio=wav_bytes(1.0), language="klingon").status_code == 400
    assert len(_records(client)) == before


def test_the_plain_endpoint_is_unchanged_by_the_new_route(client):
    """``/v1/audio/transcriptions`` still answers as it did, next to the stream."""
    headers = _login_and_load(client, "asr-model")
    audio = wav_bytes(2.0)
    assert _frames(_stream(client, audio=audio))[-1]["type"] == "done"
    plain = _plain(client, headers, audio=audio)
    assert plain.status_code == 200
    assert set(plain.json()) == {"text"}


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------
def test_a_worker_failure_after_the_stream_starts_sends_an_error_frame(client):
    """The one case that cannot be a status code: the engine broke mid-file.

    The status is already 200 and segments have been sent, so the contract is a
    terminal ``error`` frame (with a Chinese ``detail``) and a closed connection
    -- the client must not be left waiting for a ``done`` that will never come.
    """
    _login_and_load(client, "asr-model")

    import asyncio

    from app.api import asr_stream_api
    from app.core.client import WorkerError

    class BreakingClient:
        """Streams one good segment, then dies the way a dead worker does."""

        def __init__(self):
            self.cancelled: list[str] = []

        async def stream_transcribe(self, req_id, audio_b64, **kwargs):
            yield {"op": "meta", "duration": 90.0, "segments_total": 3,
                   "segment_seconds": 30, "language": None}
            yield {"op": "segment", "id": 0, "start": 0.0, "end": 30.0,
                   "text": "第一段", "infer_ms": 1200.0}
            raise WorkerError("模型进程无响应（ConnectionResetError）；请在「模型」页卸载后重新加载")

        async def cancel(self, req_id):
            self.cancelled.append(req_id)

    async def scenario():
        fake = BreakingClient()
        frames = fake.stream_transcribe("rid", "")
        job = asr_stream_api._Transcription(fake, "rid", ctx=None, store=None)
        relay = asr_stream_api._relay(job, frames, await frames.__anext__())
        return [json.loads(chunk[len("data: "):]) async for chunk in relay]

    frames = asyncio.run(scenario())
    assert [f["type"] for f in frames] == ["meta", "segment", "error"]
    assert "模型进程无响应" in frames[-1]["detail"]


def test_a_disconnect_stops_before_the_next_segment(client):
    """The contract the demo's "stop" button relies on.

    Driven at the relay level: a ``TestClient`` cannot hang up mid-body, so what
    is exercised here is the thing that decides the behaviour -- the response
    generator is closed while segments are still available, and the assertions
    are that no *further* segment is produced, that the worker is told to
    cancel, and that the record says ``cancelled`` with the count it reached.

    The frames come from a real ``MockAsrBackend`` (so the segmentation and the
    text are the ones the endpoint really produces) with a per-segment delay, so
    closing mid-stream finds the generator with segments left to yield.
    """
    _login_and_load(client, "asr-model")

    import asyncio

    from app.api import asr_stream_api
    from app.engine.mock import MockAsrBackend

    backend = MockAsrBackend("asr-model", segment_delay_ms=20)

    class FakeClient:
        """Just enough of ``WorkerClient`` for the relay: frames and cancel."""

        def __init__(self):
            self.cancelled: list[str] = []

        async def stream_transcribe(self, req_id, audio_b64, **kwargs):
            async for frame in backend.iter_transcribe(wav_bytes(120.0)):
                kind = frame.pop("type")
                yield {"op": "done" if kind == "done" else kind, **frame}

        async def cancel(self, req_id):
            self.cancelled.append(req_id)

    fake = FakeClient()

    async def scenario():
        frames = fake.stream_transcribe("rid", "")
        job = asr_stream_api._Transcription(fake, "rid", ctx=None, store=None)
        relay = asr_stream_api._relay(job, frames, await frames.__anext__())
        seen = []
        async for chunk in relay:
            seen.append(json.loads(chunk[len("data: "):]))
            if len([f for f in seen if f["type"] == "segment"]) >= 2:
                # The client hung up here: Starlette closes the generator.
                break
        await relay.aclose()
        return seen, job

    seen, job = asyncio.run(scenario())
    assert seen[0]["type"] == "meta"
    segments = [f for f in seen if f["type"] == "segment"]
    # 120 s of audio is four 30 s segments; stopping after two means the other
    # two were never produced, and no `done` was ever sent.
    assert len(segments) == 2
    assert job.segments_total == 4
    assert job.segments_done == 2
    assert not [f for f in seen if f["type"] == "done"]
    # And the worker was actually told to stop rather than left running.
    assert fake.cancelled == ["rid"]
    assert job.recorded is False, "no ctx means nothing to record, but it was attempted"


def test_a_cancelled_stream_records_the_segments_it_did_finish(client):
    """The row a cancelled stream leaves says *how far it got*, and with what.

    A cancelled record with an empty ``output_text`` would be indistinguishable
    from one that never started; what an operator needs is "3 of 8 segments, and
    here is what those three said".
    """
    _login_and_load(client, "asr-model")

    import asyncio

    from app.api import asr_stream_api
    from app.core.inference_log import build_context

    store = client.app.state.inference_log
    ctx = build_context(store, req_id="cancel-rid", source=STREAM_PATH,
                        model="asr-model", params={"language": None},
                        messages=[{"role": "user", "content": "{}"}])

    class FakeClient:
        async def stream_transcribe(self, req_id, audio_b64, **kwargs):
            yield {"op": "meta", "duration": 90.0, "segments_total": 3,
                   "segment_seconds": 30, "language": None}
            yield {"op": "segment", "id": 0, "start": 0.0, "end": 30.0,
                   "text": "第一段文字", "infer_ms": 1100.0}
            yield {"op": "segment", "id": 1, "start": 30.0, "end": 60.0,
                   "text": "第二段文字", "infer_ms": 1200.0}
            # The client hung up here; the generator is closed, so nothing more
            # is produced.

        async def cancel(self, req_id):
            pass

    async def scenario():
        fake = FakeClient()
        frames = fake.stream_transcribe("cancel-rid", "")
        job = asr_stream_api._Transcription(fake, "cancel-rid", ctx=ctx, store=store)
        relay = asr_stream_api._relay(job, frames, await frames.__anext__())
        seen = []
        async for chunk in relay:
            seen.append(json.loads(chunk[len("data: "):]))
            if len([f for f in seen if f["type"] == "segment"]) >= 2:
                break
        await relay.aclose()
        return seen

    asyncio.run(scenario())

    rows = [r for r in _records(client) if r["id"] == "cancel-rid"]
    assert len(rows) == 1, "exactly one record per inference"
    row = rows[0]
    assert row["status"] == "cancelled"
    assert row["params"]["segments"] == 2
    assert row["params"]["segments_total"] == 3
    # The text the client actually received, not an empty row.
    assert row["output_text"] == "第一段文字 第二段文字"



# ---------------------------------------------------------------------------
# review round 1: the defects found on PR #76
# ---------------------------------------------------------------------------
def test_a_full_queue_is_429_with_retry_after_not_a_200_stream(client):
    """The queue bound must be answered *before* the response is committed.

    A worker at ``max_queue`` has to refuse the request outright. When the slot
    was acquired around the segment loop instead, ``meta`` was already on the
    wire by the time ``AuxBusy`` was raised, so the endpoint could only answer
    200 and then an ``error`` frame -- and a client switching between the two
    transcription endpoints would have to handle a different status for the same
    condition. The plain endpoint gives 429 + ``Retry-After``; so must this one.

    ``max_queue=0`` makes "the queue is full" the very first admission, so the
    test needs no concurrency to set it up.
    """
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    client.app.state.models.max_queue = 0
    assert client.post("/api/models/asr-model/load").status_code == 200

    streamed = _stream(client, audio=wav_bytes(1.0))
    assert streamed.status_code == 429, streamed.text
    assert streamed.headers.get("retry-after") == "5"
    assert "队列已满" in streamed.json()["detail"]

    # The plain endpoint is the reference behaviour this one has to match.
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    plain = _plain(client, {"Authorization": f"Bearer {raw}"}, audio=wav_bytes(1.0))
    assert plain.status_code == 429, plain.text
    assert plain.headers.get("retry-after") == "5"


def test_a_backend_oserror_is_reported_not_mistaken_for_a_disconnect(client):
    """An ENOSPC/EACCES inside the backend must surface, not vanish.

    ``OSError`` used to be caught together with ``ConnectionError`` around the
    whole frame loop, so a backend I/O failure looked exactly like a client
    hang-up: nothing was sent and the API waited out ``TRANSCRIBE_TIMEOUT_S``
    before answering 503. The two are now separated by *where* they are raised --
    only a failing socket write means the peer left.

    The worker-side assertion lives in ``tests/test_worker_protocol.py`` (it
    needs a fault inside the worker process); what is pinned here is that the
    API turns such a report into a status code instead of hanging, and that a
    backend ``OSError`` is classified as a *server* failure rather than a bad
    request.
    """
    from app.engine.worker import _transcribe_error

    reported = _transcribe_error(OSError(28, "No space left on device"))
    assert reported["kind"] == "server"
    assert "No space left" in reported["message"]
    assert "OSError" in reported["message"]

    # And the API's mapping of that kind is 503, not 400/415.
    from app.api.openai_api import _worker_error_to_http
    from app.core.client import WorkerError

    http = _worker_error_to_http(WorkerError(reported["message"],
                                             kind=reported["kind"]))
    assert http.status_code == 503


def test_a_stream_cancelled_while_queued_runs_no_segment(client):
    """B waiting for the engine lock must leave without transcribing anything.

    Two requests share one NPU. B queues behind A and is disconnected there. If
    the uncancellable work were created before the lock was acquired -- as it
    first was -- B would still run one whole segment when its turn came up: a
    violation of "a disconnect stops before the next segment", and NPU time
    spent for nobody. Only *waiting* is interruptible; once a segment has the
    engine it is still allowed to finish.

    Driven at ``_run_uninterruptible`` itself, because that is where the lock
    ordering lives and where the two other backends' paths converge.
    """
    import asyncio
    import threading

    from app.engine.aux_backend import _Serialised, _run_uninterruptible

    gate = _Serialised(4)
    ran: list[str] = []
    holding = threading.Event()

    def slow(tag):
        # A synchronous sleep: what an uninterruptible NPU call looks like from
        # the event loop's point of view.
        holding.set()
        import time as _time
        _time.sleep(0.3)
        ran.append(tag)
        return tag

    async def scenario():
        # A takes the engine and keeps it for a while.
        task_a = asyncio.create_task(_run_uninterruptible(gate, slow, "A"))
        await asyncio.get_running_loop().run_in_executor(None, holding.wait)

        # B queues behind A, then the client hangs up.
        task_b = asyncio.create_task(_run_uninterruptible(gate, slow, "B"))
        await asyncio.sleep(0.05)
        assert gate.lock.locked(), "the test needs B to really be waiting"
        task_b.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_b

        assert await task_a == "A"
        return ran

    ran = asyncio.run(scenario())
    assert ran == ["A"], f"a request cancelled while queued still ran a segment: {ran}"


def test_a_cancelled_running_segment_still_finishes_and_releases_the_lock():
    """The other half of the contract: running work is not abandoned.

    ``asyncio.to_thread`` cannot stop a thread, so releasing the lock on cancel
    would let the next request enter the engine underneath a live NPU call.
    """
    import asyncio
    import threading

    from app.engine.aux_backend import _Serialised, _run_uninterruptible

    gate = _Serialised(4)
    ran: list[str] = []
    holding = threading.Event()

    def slow(tag):
        holding.set()
        import time as _time
        _time.sleep(0.3)
        ran.append(tag)
        return tag

    async def scenario():
        task = asyncio.create_task(_run_uninterruptible(gate, slow, "A"))
        await asyncio.get_running_loop().run_in_executor(None, holding.wait)
        # Now the segment is inside the engine, not merely queued.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not gate.lock.locked(), "the engine lock leaked"
        return ran

    ran = asyncio.run(scenario())
    assert ran == ["A"], "the in-flight segment was abandoned"


def test_the_cancel_notification_cannot_swallow_the_record(client):
    """A hanging ``cancel`` must not cost the cancelled request its row.

    After a disconnect Starlette keeps cancelling the request's scope, so the
    ``await`` that notifies the worker can be cancelled in turn. Written the
    other way round -- cancel first, record second -- that leaves a request that
    really ran with no row at all, which is the one thing the inference log
    exists to prevent.
    """
    _login_and_load(client, "asr-model")

    import asyncio

    from app.api import asr_stream_api
    from app.core.inference_log import build_context

    store = client.app.state.inference_log
    ctx = build_context(store, req_id="swallow-rid", source=STREAM_PATH,
                        model="asr-model", params={"language": None},
                        messages=[{"role": "user", "content": "{}"}])

    class StallingClient:
        """Streams one segment, then a ``cancel`` that never returns."""

        async def stream_transcribe(self, req_id, audio_b64, **kwargs):
            yield {"op": "meta", "duration": 60.0, "segments_total": 2,
                   "segment_seconds": 30, "language": None}
            yield {"op": "segment", "id": 0, "start": 0.0, "end": 30.0,
                   "text": "已经转好的一段", "infer_ms": 900.0}
            await asyncio.sleep(3600)

        async def cancel(self, req_id):
            await asyncio.sleep(3600)

    async def scenario():
        fake = StallingClient()
        frames = fake.stream_transcribe("swallow-rid", "")
        job = asr_stream_api._Transcription(fake, "swallow-rid", ctx=ctx, store=store)
        relay = asr_stream_api._relay(job, frames, await frames.__anext__())
        seen = []
        async for chunk in relay:
            seen.append(json.loads(chunk[len("data: "):]))
            if seen[-1]["type"] == "segment":
                break
        # The client hangs up: close the response body from the outside, which
        # is what Starlette does, then cancel the scope the way it does.
        closing = asyncio.ensure_future(relay.aclose())
        await asyncio.sleep(0.05)
        closing.cancel()
        with contextlib.suppress(BaseException):
            await closing
        return seen

    seen = asyncio.run(scenario())
    assert [f["type"] for f in seen] == ["meta", "segment"]

    rows = [r for r in _records(client) if r["id"] == "swallow-rid"]
    assert len(rows) == 1, "the cancelled request lost its record"
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["output_text"] == "已经转好的一段"
