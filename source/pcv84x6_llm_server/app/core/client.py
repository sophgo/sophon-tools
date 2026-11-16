"""Thin async client for talking to a worker's JSON-lines socket."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import AsyncIterator

#: How long one auxiliary call may take. A batch is one forward per item on a
#: single NPU, and the API caps batches at 64 texts / 256 documents, so this is
#: a bound on "the NPU is wedged", not on normal work: a single forward is
#: ~20-100 ms on CV84X6, and 256 of them is well inside a minute.
EMBED_TIMEOUT_S = 300.0
RERANK_TIMEOUT_S = 600.0
#: A transcription is bounded by the audio, not by the batch: the NPU runs at
#: roughly 1x real time and the API caps audio at 30 minutes, so 45 leaves room
#: for a slow board without inventing a second, tighter limit.
TRANSCRIBE_TIMEOUT_S = 2700.0
#: One OCR request is one det pass plus one rec pass per detected line. A dense
#: A4 page is ~100 lines at ~30 ms each, so 10 s of rec on top of a 50 ms det;
#: 300 s is a bound on "the NPU is wedged", not on normal work.
OCR_TIMEOUT_S = 300.0

#: The largest single protocol line this client will read. Chat requests carry
#: base64 images; a transcription carries a whole audio file, which the endpoint
#: allows up to 50 MiB -- 66.7 MiB once base64-encoded. Kept in step with the
#: worker's own bound (_asr_stream_limit) by deriving it from the same constant:
#: a reply smaller than the request can never exceed it.
LINE_LIMIT = 64 * 1024 * 1024


def _line_limit() -> int:
    """The read bound for the worker socket, sized for the largest request."""
    from ..api.audio_upload import MAX_UPLOAD_BYTES

    return max(LINE_LIMIT, (MAX_UPLOAD_BYTES * 4 // 3) + (1024 * 1024))


class WorkerError(RuntimeError):
    """A worker reported failure. ``kind`` is "invalid_request" when the request
    itself was refused (over-long prompt, unreadable image) -- a client error --
    and "server" otherwise.

    This class means **the worker answered**. When the failure is local --
    the connection could not be opened, the write failed, or the socket hit EOF
    while a reply was outstanding -- the request may still have been executed,
    and :class:`WorkerTransportError` says so. Callers that cannot act on that
    difference keep catching ``WorkerError`` and behave as before.
    """

    def __init__(self, message: str, kind: str = "server") -> None:
        super().__init__(message)
        self.kind = kind


class WorkerTransportError(WorkerError):
    """The round trip failed *locally*: the outcome on the worker is unknown.

    Raised by every path that cannot prove whether the worker saw the request
    (MYS-2801). Until this existed, ``_send`` converted a dead connection and
    ``_call`` converted an EOF into the same ``WorkerError`` a refusal uses, so
    ``PUT /api/models/{id}/settings`` reported "409, nothing changed" for a
    ``configure`` the worker had already applied.

    ``stage`` names where it broke, for logs and tests -- never for branching on
    a message string: ``"connect"`` (nothing was written), ``"write"`` (the
    request may be partly on the wire) and ``"read"`` (it was written and the
    reply never arrived).
    """

    transport = True

    def __init__(self, message: str, stage: str = "read") -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class _ConnectionLost:
    """Queued into every pending reply when the read loop sees EOF.

    A sentinel rather than an ``{"op": "error"}`` frame: a dict would be
    indistinguishable from the worker's own error reply, which is precisely the
    confusion this class exists to end.
    """

    message: str


@dataclass
class StreamDone:
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    first_token_latency_s: float | None
    decode_tps: float | None


#: RPC ops that are inference work (as opposed to health/stats/configure
#: control traffic): they mark the model as in use for the idle sweep.
_WORK_OPS = frozenset({"embed", "rerank", "ocr", "transcribe",
                       "detect_page", "ocr_page"})


class WorkerClient:
    """One connection to one worker, multiplexing several requests.

    A connection stays open for many requests; each request is a stream of
    events tagged with its ``req_id``, so the caller filters its own events.

    A client is single-use per worker generation: once ``close`` has run it
    refuses to reconnect. That is not tidiness. An unload closes the socket
    *before* it signals the worker, because the worker's shutdown waits for its
    connection handlers and a live one costs the 120 s grace that ends in a
    SIGKILL of a live NPU process -- and a console poll that still held this
    object would otherwise silently open a **new** connection right after the
    close, putting that handler back and turning a 0.6 s unload into a kill.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._queues: dict[str, asyncio.Queue] = {}
        self._pump: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        #: Inference calls in flight through this client (embed, rerank, ocr,
        #: transcribe, streamed transcriptions) -- counted on the API side, so a
        #: request already sent but not yet admitted by the worker still counts.
        #: The idle sweep reads it next to the worker's own figure.
        self.active = 0
        #: Called at the start and end of every inference call; the manager
        #: binds it to ``touch`` so a long job (a library build, a 300-page OCR)
        #: keeps its model "in use" between batches instead of only at the
        #: first one.
        self.on_activity = None

    def _work_started(self) -> None:
        self.active += 1
        self._notify_activity()

    def _work_finished(self) -> None:
        self.active = max(0, self.active - 1)
        self._notify_activity()

    def _notify_activity(self) -> None:
        hook = self.on_activity
        if hook is not None:
            with contextlib.suppress(Exception):
                hook()

    async def connect(self) -> None:
        async with self._lock:
            if self._closed:
                raise WorkerError(
                    "模型进程的连接已关闭；请在「模型」页重新加载该模型")
            if self._writer is not None and not self._writer.is_closing():
                return
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", self.port, limit=_line_limit())
            # ``close`` does not take this lock (it is called from the unload,
            # which must not queue behind an in-flight request), so it can run
            # *while* the line above is awaiting. Re-check after the await: a
            # connection opened into that window belongs to nobody, and leaving
            # it open is the exact failure the close exists to prevent -- the
            # worker's shutdown then waits on this handler for the full 120 s
            # grace and ends in a SIGKILL of a live NPU process.
            if self._closed:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                raise WorkerError(
                    "模型进程的连接已关闭；请在「模型」页重新加载该模型")
            self._reader, self._writer = reader, writer
            self._pump = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = msg.get("req_id")
                q = self._queues.get(rid) if rid else None
                if q is not None:
                    await q.put(msg)
        finally:
            # Wake every waiter so nobody hangs on a dead worker. The sentinel,
            # not an error frame: EOF says nothing about whether the worker
            # executed the request, and ``_call`` must be able to tell that from
            # a refusal (MYS-2801).
            lost = _ConnectionLost(
                "模型进程连接已断开；请在「模型」页重新加载该模型")
            for q in list(self._queues.values()):
                await q.put(lost)

    async def _send(self, obj: dict) -> None:
        stage = "connect"
        try:
            await self.connect()
            assert self._writer is not None
            stage = "write"
            self._writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            # The worker process died (OOM, killed, crashed on load). Convert to
            # a domain error so the API returns a clear message instead of an
            # unhandled ConnectionRefusedError, and drop the stale socket.
            await self._reset()
            raise WorkerTransportError(
                f"模型进程无响应（{type(exc).__name__}）；请在「模型」页卸载后重新加载",
                stage=stage) from exc

    async def _reset(self) -> None:
        self._writer = None
        self._reader = None
        if self._pump is not None:
            task, self._pump = self._pump, None
            task.cancel()

    async def health(self) -> dict:
        return await self._call("health")

    async def configure(self, **settings) -> dict:
        """Push console settings to the running worker; returns what applied."""
        return await self._call("configure", **settings)

    async def stats(self) -> dict:
        return await self._call("stats")

    async def embed(self, req_id: str, texts: list[str],
                    dimensions: int | None = None) -> dict:
        """One ``embed`` round trip: ``{op: embeddings, vectors, tokens}``.

        Unlike ``generate`` this is a single request/response, not a stream --
        an embedding call has no partial results to report -- so it rides the
        same path as ``health``/``stats``, keyed by its own unique id so two
        concurrent callers cannot cross their replies.

        The reply can be large (64 texts x 1024 floats is ~500 KB of JSON), so
        the timeout is generous compared with ``_call``'s 10 s: a 64-text batch
        on the board is 64 sequential forwards.
        """
        return await self._call("embed", _timeout=EMBED_TIMEOUT_S,
                                _req_prefix=req_id, texts=texts,
                                dimensions=dimensions)

    async def rerank(self, req_id: str, query: str, documents: list[str]) -> dict:
        """One ``rerank`` round trip: ``{op: scores, logits, tokens}``."""
        return await self._call("rerank", _timeout=RERANK_TIMEOUT_S,
                                _req_prefix=req_id, query=query,
                                documents=documents)

    async def embed_multimodal(self, req_id: str, items: list[dict],
                               dimensions: int | None = None,
                               instruction: str | None = None) -> dict:
        return await self._call("embed", _timeout=EMBED_TIMEOUT_S,
                                _req_prefix=req_id, inputs=items,
                                dimensions=dimensions, instruction=instruction)

    async def transcribe(self, req_id: str, audio_b64: str,
                         filename: str | None = None, language: str | None = None,
                         prompt: str = "") -> dict:
        """One ``transcribe`` round trip: ``{op: transcript, text, segments, ...}``.

        ``audio_b64`` is the uploaded file's bytes. They go over the socket
        rather than through a shared path because the worker owns the ffmpeg and
        the mel front end: the API process never decodes audio, so there is no
        second copy of that logic to keep in step.

        The timeout is the transcription's own: 30 minutes of audio at roughly
        1x real time is half an hour of NPU time, and a client that asked for it
        should not be cut off by a bound meant for a wedged NPU.
        """
        fields = {"audio_b64": audio_b64, "filename": filename, "prompt": prompt}
        if language is not None:
            fields["language"] = language
        return await self._call("transcribe", _timeout=TRANSCRIBE_TIMEOUT_S,
                                _req_prefix=req_id, **fields)

    async def stream_transcribe(self, req_id: str, audio_b64: str,
                                filename: str | None = None,
                                language: str | None = None,
                                prompt: str = "") -> AsyncIterator[dict]:
        """Yield ``meta``/``segment``/``done`` events for one transcription.

        The segment-level sibling of ``transcribe``: same request fields, same
        worker, but the reply arrives a frame at a time so the console can show
        progress. The *final* text is the ``done`` frame's ``text``, and it is
        the same string ``transcribe`` would have returned -- one joiner in the
        worker produces both.

        An ``error`` frame is raised as :class:`WorkerError` with its ``kind``,
        exactly as the single-shot call's error reply is, so the API's status
        mapping is the same code for both. That matters most for the frame that
        arrives *before* ``meta``: a 415 for undecodable audio has to become an
        HTTP status, not the first event of a 200 stream.

        Closing this generator early (the caller's disconnect) does **not**
        cancel the worker's segment in flight: ``cancel`` is a separate call, so
        the caller decides whether "stop" means "stop after this segment" (send
        it) or "I am only done reading" (do not). The endpoint always sends it.
        """
        q: asyncio.Queue = asyncio.Queue()
        self._queues[req_id] = q
        fields = {"audio_b64": audio_b64, "filename": filename, "prompt": prompt}
        if language is not None:
            fields["language"] = language
        self._work_started()
        try:
            await self._send({"op": "transcribe_stream", "req_id": req_id, **fields})
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=TRANSCRIBE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    # The worker is wedged, not merely slow: tell it to stop so
                    # it does not keep a queue slot (and the NPU) for a request
                    # nobody is waiting for any more. Best effort -- the socket
                    # may be the thing that is wedged.
                    with contextlib.suppress(Exception):
                        await self.cancel(req_id)
                    raise WorkerError(
                        "转写超时（worker 超过 "
                        f"{TRANSCRIBE_TIMEOUT_S / 60:.0f} 分钟没有回应）") from None
                if isinstance(msg, _ConnectionLost):
                    raise WorkerTransportError(msg.message, stage="read")
                if msg.get("op") == "error":
                    raise WorkerError(msg.get("message", "worker error"),
                                      kind=msg.get("kind", "server"))
                yield msg
                if msg.get("op") == "done":
                    return
        finally:
            self._queues.pop(req_id, None)
            self._work_finished()

    async def ocr(self, req_id: str, image_b64: str, mode: str = "lines") -> dict:
        """One ``ocr`` round trip: ``{op: ocr_result, text, lines, det_ms, ...}``.

        ``image_b64`` is the image's bytes. They go over the socket rather than
        through a shared path for the same reason the audio does: the worker
        owns the OpenCV and the transform parameters, so the API process never
        decodes an image and there is no second implementation to keep in step.

        ``mode`` travels as a separate field rather than being folded into the
        image: the worker validates it (it is the thing that owns the mode's
        meaning), and "layout" with no image is a different 400 from "not a
        supported mode". Omitted from the frame when it is the default, so a
        lines-mode request is byte-identical to what this service sent before
        layout mode existed.
        """
        fields = {"image_b64": image_b64}
        if mode != "lines":
            fields["mode"] = mode
        return await self._call("ocr", _timeout=OCR_TIMEOUT_S,
                                _req_prefix=req_id, **fields)

    async def detect_page(self, req_id: str, image_b64: str) -> dict:
        """``op: detect_page``: the layout half of ``mode: "vl"``.

        Returns ``{width, height, layout_ms, regions}``. The image goes over the
        socket for the same reason an ``ocr`` request's does: the worker owns
        OpenCV and the model's transform, so the management plane never decodes
        an image.
        """
        timeout = self.page_timeout_s()
        return await self._call("detect_page", _timeout=timeout,
                                _req_prefix=req_id, image_b64=image_b64)

    async def ocr_page(self, req_id: str, image_b64: str,
                       regions: list[dict]) -> dict:
        """``op: ocr_page``: the recognition half of ``mode: "vl"``.

        ``regions`` are the detector's output, unchanged. One region is one VLM
        request, so the timeout has to cover a whole page rather than one
        answer -- see :meth:`page_timeout_s`.
        """
        timeout = self.page_timeout_s(regions=len(regions))
        return await self._call("ocr_page", _timeout=timeout,
                                _req_prefix=req_id, image_b64=image_b64,
                                regions=regions)

    @staticmethod
    def page_timeout_s(regions: int = 1) -> float:
        """How long a whole-page call may take, from the page's own work.

        Not a constant: ``vl`` mode runs one VLM answer per region, and a table
        answer is up to 4096 tokens at the board's measured 13.6 ms -- about a
        minute. A 12-region page is therefore minutes, not seconds, and the
        single-region ``OCR_TIMEOUT_S`` would abandon a page that is working.

        The bound is computed by the page module itself
        (``ocr_vl_page.page_timeout_s``), so "the worker is wedged" means the
        same thing on both sides of the socket.
        """
        from ..engine.ocr_vl_page import page_timeout_s

        return page_timeout_s(int(regions))

    async def _call(self, op: str, _timeout: float = 10.0,
                    _req_prefix: str | None = None, **fields) -> dict:
        """One request/response round trip, keyed by a unique id.

        A fixed key (e.g. the literal "__stats__") would collide when two
        callers ask concurrently -- the second would overwrite the first's queue
        and the first would wait forever.
        """
        rid = (f"__{_req_prefix}__" if _req_prefix
               else f"__{op}_{secrets.token_hex(4)}__")
        q: asyncio.Queue = asyncio.Queue()
        self._queues[rid] = q
        work = op in _WORK_OPS
        if work:
            self._work_started()
        try:
            await self._send({"op": op, "req_id": rid, **fields})
            reply = await asyncio.wait_for(q.get(), timeout=_timeout)
        finally:
            self._queues.pop(rid, None)
            if work:
                self._work_finished()
        # The read loop reports a dead worker by queueing a sentinel. Returning
        # that as if it were a successful reply would hand callers a dict with no
        # expected fields, which fails later and far from the cause -- and
        # reading it as the worker's own refusal would be a lie about what is
        # known (MYS-2801).
        if isinstance(reply, _ConnectionLost):
            raise WorkerTransportError(reply.message, stage="read")
        if reply.get("op") == "error":
            raise WorkerError(reply.get("message", "worker error"),
                              kind=reply.get("kind", "server"))
        return reply

    async def generate(
        self, req_id: str, prompt: str, params: dict, images: list[str] | None = None
    ) -> AsyncIterator[dict]:
        """Yield ``meta``/``delta``/``done`` events for one request."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues[req_id] = q
        try:
            await self._send({
                "op": "generate", "req_id": req_id, "prompt": prompt,
                "params": params, "images": images or [],
            })
            while True:
                msg = await q.get()
                if isinstance(msg, _ConnectionLost):
                    raise WorkerTransportError(msg.message, stage="read")
                if msg.get("op") == "error":
                    raise WorkerError(msg.get("message", "worker error"),
                                      kind=msg.get("kind", "server"))
                yield msg
                if msg.get("op") == "done":
                    return
        finally:
            self._queues.pop(req_id, None)

    async def cancel(self, req_id: str) -> None:
        try:
            await self._send({"op": "cancel", "req_id": req_id})
        except Exception:
            pass

    async def close(self) -> None:
        # Permanent: see the class docstring. Set before the socket work so a
        # concurrent ``connect`` cannot slip a reconnect in behind the close.
        self._closed = True
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except (asyncio.CancelledError, Exception):
                pass
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
