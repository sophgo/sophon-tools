"""Streaming decode must assemble characters that span tokens (MYS-2496).

The production tokenizer is byte-level BPE. A CJK character's three UTF-8 bytes
are spread across token boundaries, so ``门簪`` is the three ids
``[96141, 97618, 103]`` -- the first carrying all of ``门`` plus the first two
thirds of ``簪``. Decoding one id at a time and calling ``.decode("utf-8",
"replace")`` on each fragment commits the two incomplete tails to U+FFFD, and
U+FFFD cannot be un-replaced: the customer's ``门簪`` came back as ``门��``.

So the scheduler now takes raw bytes from the session and joins them through an
incremental UTF-8 decoder, which holds an incomplete tail until the bytes that
finish it arrive. These tests drive the real ``Scheduler`` with a session that
returns exactly the byte fragments the real tokenizer would produce, then check
the same thing against the real tokenizer.

The last case is the honest edge: a generation that stops in the middle of a
character cannot be repaired by joining, because the rest of the character was
never generated. One U+FFFD is then the truthful answer, and it must still be
streamed rather than silently dropped.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.engine.base import EngineBackend, GenerateParams, Session
from app.engine.scheduler import Scheduler

ROOT = Path(__file__).resolve().parent.parent
STUB_SRC = ROOT / "tests" / "native_stub.c"

DEFAULT_TOKENIZER_JSON = Path(
    "/home/zzt/workspace/cv84x6-refs/models/Qwen3_5/config/tokenizer.json"
)


def _tokenizer_json() -> Path | None:
    explicit = os.environ.get("CV84X6_TOKENIZER_JSON")
    if explicit:
        return Path(explicit) if Path(explicit).exists() else None
    if DEFAULT_TOKENIZER_JSON.exists():
        return DEFAULT_TOKENIZER_JSON
    return None


def params(**kw) -> GenerateParams:
    base = dict(max_tokens=64, temperature=0.0, top_p=1.0, top_k=1)
    base.update(kw)
    return GenerateParams(**base)


# ---------------------------------------------------------------------------
# a backend whose tokens carry preset byte fragments
# ---------------------------------------------------------------------------
# A stream is a list of byte fragments, one per generated token. Token id i+1
# carries ``stream[i]``, so a test states the exact bytes the scheduler sees and
# the scheduler builds its own ids the way a real session would. Id 0 is the
# stop token, which has no bytes because the stop check runs before decoding.
STOP_ID = 0


class ByteSession(Session):
    """A session that emits preset bytes, one token per step.

    ``decode_bytes`` is the whole point: it hands back the token's bytes without
    any UTF-8 validation, which is what the real tokenizer wrapper now does.
    """

    def __init__(self, backend: "ByteBackend") -> None:
        self._backend = backend
        self._tokens: list[int] = []
        self._pos = 0

    @property
    def token_len(self) -> int:
        return len(self._tokens)

    async def feed_prompt(self, tokens) -> None:
        self._tokens.extend(tokens)

    async def step(self) -> int:
        i = self._pos
        self._pos += 1
        hook = self._backend.on_step
        if hook is not None:
            hook(i)
        if i < len(self._backend.stream):
            token = i + 1
            self._tokens.append(token)
            return token
        # Ran out of preset tokens without a stop: the stream ends here, which
        # the tests using it arrange to be a max_tokens stop.
        return STOP_ID

    def decode(self, tokens) -> str:
        return self.decode_bytes(tokens).decode("utf-8", "replace")

    def decode_bytes(self, tokens) -> bytes:
        out = b""
        for t in tokens:
            if t == STOP_ID:
                continue
            out += self._backend.stream[t - 1]
        return out

    def is_stop_token(self, token: int) -> bool:
        return token == STOP_ID

    async def snapshot(self, token_len: int) -> object:
        return None

    async def restore(self, snap: object) -> None:
        return None

    async def close(self) -> None:
        return None


class ByteBackend(EngineBackend):
    def __init__(self, stream: list[bytes], context_length: int = 4096) -> None:
        self.stream = stream
        self._ctx = context_length
        # Called with the step index before each step returns; lets a test
        # cancel at a chosen point in the stream.
        self.on_step = None

    @property
    def model_id(self) -> str:
        return "bytes"

    @property
    def context_length(self) -> int:
        return self._ctx

    @property
    def supports_vision(self) -> bool:
        return False

    async def encode(self, text: str, images=None) -> list[int]:
        return [STOP_ID]

    async def new_session(self) -> Session:
        return ByteSession(self)

    async def close(self) -> None:
        return None


async def run_stream(stream: list[bytes], max_tokens: int = 64):
    """Drive one request through the real scheduler; return (req, chunks)."""
    backend = ByteBackend(stream)
    sched = Scheduler(backend, max_concurrent=1)
    await sched.start()
    chunks: list[str] = []

    async def sink(text: str) -> None:
        chunks.append(text)

    try:
        req = await sched.generate("utf8", [STOP_ID], params(max_tokens=max_tokens), sink)
    finally:
        await sched.stop()
    return req, chunks


# ---------------------------------------------------------------------------
# the character that started this
# ---------------------------------------------------------------------------
# 门簪 as the real tokenizer splits it. The first token ends with two of the
# three bytes of 簪; decoding it alone is unrescuable.
MEN_ZAN = [b"\xe9\x97\xa8", b"\xe7\xb0", b"\xaa"]


@pytest.mark.asyncio
async def test_a_character_split_across_three_tokens_streams_whole():
    req, chunks = await run_stream(MEN_ZAN)

    assert "".join(chunks) == "门簪"
    assert all("\ufffd" not in c for c in chunks), chunks
    # The first token's text is 门 alone: its trailing two bytes belong to the
    # next character and must not have been flushed as a replacement.
    assert chunks[0] == "门"
    assert req.finish_reason == "stop"
    assert len(req.generated) == 3, "three generated tokens before the stop"
    assert "".join(req.text_parts) == "门簪"


@pytest.mark.asyncio
async def test_a_four_byte_emoji_split_one_byte_per_token_streams_whole():
    emoji = "😀".encode("utf-8")
    assert len(emoji) == 4
    req, chunks = await run_stream([bytes([b]) for b in emoji])

    assert "".join(chunks) == "😀"
    assert all("\ufffd" not in c for c in chunks), chunks
    # Nothing is emitted until the fourth byte completes the scalar value.
    assert chunks == ["😀"]
    assert req.finish_reason == "stop"


@pytest.mark.asyncio
async def test_whole_characters_and_split_ones_interleave_correctly():
    """琴轸好: 琴 whole, 轸 split over two tokens, 好 whole."""
    stream = [b"\xe7\x90\xb4", b"\xe8\xbd", b"\xb8", b"\xe5\xa5\xbd"]
    req, chunks = await run_stream(stream)

    assert "".join(chunks) == "琴轸好"
    assert all("\ufffd" not in c for c in chunks), chunks
    assert chunks == ["琴", "轸", "好"]
    assert req.finish_reason == "stop"


@pytest.mark.asyncio
async def test_truncating_mid_character_ends_with_exactly_one_replacement():
    """max_tokens cut inside 簪: the bytes that would finish it never exist.

    Joining cannot invent them, so one U+FFFD is the honest text -- and it has
    to reach the client, not be dropped as "incomplete".
    """
    req, chunks = await run_stream(MEN_ZAN[:2], max_tokens=2)

    assert req.finish_reason == "length"
    text = "".join(chunks)
    assert text == "门\ufffd", repr(text)
    assert text.count("\ufffd") == 1
    # The tail went through the sink, so the SSE stream ends with it too.
    assert chunks[-1] == "\ufffd"
    assert "".join(req.text_parts) == text


@pytest.mark.asyncio
async def test_cancelling_mid_character_drops_the_tail_without_raising():
    """A cancel inside 簪 closes cleanly and never writes to the dead sink.

    The scheduler decodes the first token (``门``) and holds the next two bytes,
    then the request is cancelled from inside ``step`` -- exactly the state a
    disconnect leaves. Nothing pending may be flushed to a sink that is gone,
    and the request must still finish as ``cancelled``.
    """
    stream = MEN_ZAN + MEN_ZAN * 8
    backend = ByteBackend(stream)
    sched = Scheduler(backend, max_concurrent=1)
    chunks: list[str] = []
    cancelled_at: list[int] = []

    def cancel_after_one_character(i: int) -> None:
        # Step 1 produced 门; step 2's two bytes are still pending.
        if i == 1:
            cancelled_at.append(i)
            sched.cancel("cancel")

    backend.on_step = cancel_after_one_character

    async def sink(text: str) -> None:
        chunks.append(text)
        assert not cancelled_at, "the sink was called after the cancel"

    await sched.start()
    try:
        req = await sched.generate("cancel", [STOP_ID], params(max_tokens=1000), sink)
    finally:
        await sched.stop()

    assert cancelled_at, "the cancel never fired, so nothing was cancelled mid-character"
    assert req.finish_reason == "cancelled"
    assert req.state == "done"
    # Exactly what the client was sent: 门, then nothing. No U+FFFD tail: the
    # client is gone, and a cancel is not a text event.
    assert chunks == ["门"]
    # The record still shows the truth -- the answer was cut mid-character, and
    # one U+FFFD says so rather than implying a clean 门.
    assert "".join(req.text_parts) == "门\ufffd"


@pytest.mark.asyncio
async def test_a_whole_character_stream_is_unchanged_by_the_decoder():
    """Regression guard: text that never splits must come out token for token."""
    stream = ["两个".encode(), "女生".encode(), "约".encode()]
    req, chunks = await run_stream(stream)

    assert "".join(chunks) == "两个女生约"
    assert chunks == ["两个", "女生", "约"]
    assert req.finish_reason == "stop"


# ---------------------------------------------------------------------------
# the real tokenizer, and proof the test above covers the real defect
# ---------------------------------------------------------------------------
def _byte_level_inverse() -> dict[str, int]:
    """GPT-2's byte<->code-point table inverted: code point -> raw byte.

    The tokenizer's vocabulary stores each raw byte as a printable stand-in
    (space is ``Ġ`` etc.), so recovering a token's bytes means mapping every
    character back. This is the same map native/src/tokenizer.cpp applies.
    """
    printable = (list(range(ord("!"), ord("~") + 1))
                 + list(range(ord("¡"), ord("¬") + 1))
                 + list(range(ord("®"), ord("ÿ") + 1)))
    codes = printable[:]
    n = 0
    for b in range(256):
        if b not in printable:
            printable.append(b)
            codes.append(256 + n)
            n += 1
    return {chr(c): b for b, c in zip(printable, codes)}


def _token_bytes(tokenizer, token_id: int) -> bytes:
    """The raw bytes one token contributes, byte-level BPE undone."""
    inv = _byte_level_inverse()
    raw = bytearray()
    for ch in tokenizer.id_to_token(token_id) or "":
        b = inv.get(ch)
        if b is None:
            raw += ch.encode("utf-8")  # an added token's literal text
        else:
            raw.append(b)
    return bytes(raw)


WORDS = ["门簪", "琴轸", "秤砣", "妆奁", "😀👍", "两个女生约好一起出门吃火锅"]


def test_the_real_tokenizer_reproduces_the_field_failure():
    """The bug, on the shipped vocabulary: per-token decode mangles these words.

    This is what makes the tests above evidence rather than invention -- the
    fragments they feed are the fragments this tokenizer really produces.
    """
    tokenizers = pytest.importorskip("tokenizers")
    path = _tokenizer_json()
    if path is None:
        pytest.skip("no tokenizer.json available (set CV84X6_TOKENIZER_JSON)")
    tok = tokenizers.Tokenizer.from_file(str(path))

    broken = {}
    for word in WORDS:
        ids = tok.encode(word, add_special_tokens=False).ids
        old = "".join(tok.decode([i]) for i in ids)
        if "\ufffd" in old:
            broken[word] = old
    # The four rare two-character words are the ones the field log caught as
    # `门��`/`琴��`/`秤��`/`妆��`; the emoji pair splits the same way.
    for word in ("门簪", "琴轸", "秤砣", "妆奁", "😀👍"):
        assert word in broken, f"{word} no longer splits across tokens: {broken}"
    # A run of ordinary characters does not split, so it must not be "broken":
    # the failure is specific to characters the BPE merges did not cover.
    assert "两个女生约好一起出门吃火锅" not in broken


def test_incremental_decode_over_real_token_bytes_restores_every_word():
    """Feed the real tokenizer's bytes through the scheduler's decoder."""
    tokenizers = pytest.importorskip("tokenizers")
    path = _tokenizer_json()
    if path is None:
        pytest.skip("no tokenizer.json available (set CV84X6_TOKENIZER_JSON)")
    tok = tokenizers.Tokenizer.from_file(str(path))

    for word in WORDS:
        ids = tok.encode(word, add_special_tokens=False).ids
        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        joined = "".join(dec.decode(_token_bytes(tok, i)) for i in ids)
        joined += dec.decode(b"", final=True)
        assert joined == word, (word, ids, joined)
        assert "\ufffd" not in joined


# ---------------------------------------------------------------------------
# the ctypes layer: the C ABI must hand back bytes, not a validated string
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def stub_lib(tmp_path_factory) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler to build the engine stub")
    out = tmp_path_factory.mktemp("utf8stub") / "libcv84x6_llm.so"
    proc = subprocess.run(
        [cc, "-shared", "-fPIC", "-O1", str(STUB_SRC), "-o", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"the engine stub does not build here: {proc.stderr[:400]}")
    return out


@pytest.fixture()
def native_backend(tmp_path, stub_lib):
    from app.engine.native import NativeBackend

    tok = tmp_path / "tokenizer.json"
    tok.write_text("{}", encoding="utf-8")
    be = NativeBackend("model.bmodel", str(tok), "stub", lib_path=str(stub_lib))
    yield be
    be._handle = None  # the stub owns no engine state; skip llm_engine_free
    be._tok.close()


def test_the_engine_library_returns_the_partial_bytes(native_backend):
    """A token holding half a character must cross the ABI as those bytes.

    The stub decodes one id per byte, so a 3-byte character is three ids. That
    is the shape of the real defect: if this layer converted to str, the first
    id alone would already be U+FFFD and nothing downstream could recover it.
    """
    raw = "门簪".encode("utf-8")
    ids = [1000 + b for b in raw]

    assert native_backend.tokenizer_decode_bytes(ids) == raw
    # The per-id fragments are exactly the unusable halves.
    assert native_backend.tokenizer_decode_bytes(ids[:1]) == raw[:1]
    assert native_backend.tokenizer_decode_bytes(ids[1:2]) == raw[1:2]
    # And the str door still replaces them -- unchanged behaviour, which is why
    # the scheduler must not use it per token.
    assert native_backend.tokenizer_decode(ids[:1]) == "\ufffd"


@pytest.mark.asyncio
async def test_a_native_session_decodes_through_the_byte_path(native_backend):
    """NativeSession.decode_bytes is what the scheduler actually calls."""
    from app.engine.native import NativeSession

    raw = "琴轸".encode("utf-8")
    ids = [1000 + b for b in raw]
    session = NativeSession(native_backend, 1)

    assert session.decode_bytes(ids) == raw
    # Default Session.decode_bytes would round-trip through str and lose the
    # fragments; the override is what makes the stream correct.
    assert session.decode_bytes(ids[1:2]) == raw[1:2]


# ---------------------------------------------------------------------------
# through the HTTP surface: the customer's view
# ---------------------------------------------------------------------------
class _SchedulerClient:
    """A worker client that runs the real scheduler over ``ByteBackend``.

    The API layer talks to a worker over the ``generate`` event stream, so
    putting a real ``Scheduler`` behind that boundary exercises the whole path
    -- scheduler decode, worker events, SSE assembly, the inference record --
    with the API code left exactly as it ships.
    """

    def __init__(self, stream: list[bytes]) -> None:
        self.stream = stream
        self.port = 0
        self._live: list[Scheduler] = []

    async def generate(self, req_id, prompt, params, images=None):
        # A scheduler per request: the shim is driven from whatever loop the
        # app runs on, so nothing is created before this coroutine starts.
        sched = Scheduler(ByteBackend(list(self.stream)), max_concurrent=1)
        await sched.start()
        self._live.append(sched)
        queue: asyncio.Queue = asyncio.Queue()

        async def sink(text: str) -> None:
            await queue.put({"op": "delta", "req_id": req_id, "text": text})

        gen_params = GenerateParams(max_tokens=params.get("max_tokens") or 512,
                                    stop=list(params.get("stop") or []))
        try:
            req = sched.enqueue(req_id, [STOP_ID], gen_params, sink)
            yield {"op": "meta", "req_id": req_id,
                   "prompt_tokens": req.prompt_len, "cached_tokens": 0}
            waiter = asyncio.create_task(sched.wait(req))
            while True:
                get = asyncio.create_task(queue.get())
                await asyncio.wait({get, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if get.done():
                    yield get.result()
                    continue
                # The request finished. Its last sink call completed before the
                # done event was set, so everything left in the queue is ours.
                get.cancel()
                while not queue.empty():
                    yield queue.get_nowait()
                break
        finally:
            await sched.stop()
            self._live.remove(sched)
        yield {"op": "done", "req_id": req_id, "finish_reason": req.finish_reason,
               "prompt_tokens": req.prompt_len, "completion_tokens": len(req.generated),
               "cached_tokens": 0, "first_token_latency_s": 0.01, "decode_tps": 100.0}

    async def cancel(self, req_id):
        for sched in self._live:
            sched.cancel(req_id)

    async def close(self):
        return None


@pytest.fixture()
def utf8_api(tmp_path):
    """(TestClient, headers, app) whose model streams 门簪 as three fragments."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models"
    d = models / "test-model"
    (d / "config").mkdir(parents=True)
    (d / "test-model-int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        app.state.models.get("test-model").loaded = True
        app.state.clients["test-model"] = _SchedulerClient(MEN_ZAN)
        key = c.post("/api/keys", json={"name": "pytest"}).json()["key"]
        yield c, {"Authorization": f"Bearer {key}"}, app


def test_non_stream_content_is_the_whole_character(utf8_api):
    client, headers, _ = utf8_api
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "说一个生僻词"}],
        "max_tokens": 8,
    })

    assert r.status_code == 200, r.text
    content = r.json()["choices"][0]["message"]["content"]
    assert content == "门簪", repr(content)
    assert "\ufffd" not in content


def test_stream_sse_concatenates_to_the_whole_character(utf8_api):
    client, headers, _ = utf8_api
    with client.stream("POST", "/v1/chat/completions", headers=headers, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "说一个生僻词"}],
        "max_tokens": 8,
    }) as r:
        assert r.status_code == 200
        sse = "".join(r.iter_text())

    chunks = [json.loads(line[len("data: "):])
              for line in sse.splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    # The usage chunk carries no choices, so it contributes no content.
    deltas = [c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"]]
    assert "".join(deltas) == "门簪", repr(deltas)
    assert "\ufffd" not in sse


def test_the_inference_record_holds_the_whole_character(utf8_api):
    """The record is the evidence an operator reads after a complaint."""
    client, headers, _ = utf8_api
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "说一个生僻词"}],
        "max_tokens": 8,
    })
    assert r.status_code == 200, r.text

    items = client.get("/api/inference-records", params={"limit": 10}).json()["items"]
    assert len(items) == 1, items
    row = client.get(f"/api/inference-records/{items[0]['id']}").json()
    assert row["output_text"] == "门簪", repr(row["output_text"])
    # The detail view carries the raw output's length, not its text, so two
    # characters (not four replacement characters plus noise) is the check.
    assert row["raw_output_chars"] == 2
    assert row["completion_tokens"] == 3


def test_the_console_playground_shows_the_whole_character(utf8_api):
    """/api/chat is the other path into the same model."""
    client, headers, _ = utf8_api
    r = client.post("/api/chat", json={
        "model": "test-model", "prompt": "说一个生僻词",
        "max_tokens": 8, "temperature": 0.0,
    })

    assert r.status_code == 200, r.text
    assert r.json()["text"] == "门簪", repr(r.json()["text"])
