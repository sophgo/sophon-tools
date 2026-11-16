"""The ASR worker's request machinery, without an NPU.

``tests/test_transcriptions_api.py`` drives the mock backend through HTTP; this
file goes one level down to the parts only the *real* backend has, with the
engine replaced by a scripted stand-in. Three things live only here:

* the **decode loop** -- greedy, stopping on ``<|im_end|>``, bounded by what the
  KV cache leaves after the prompt;
* the **reference's output rule** -- the ``language <Name><asr_text>`` preamble
  is stripped, and a partial UTF-8 character is dropped rather than turned into
  U+FFFD;
* the **segment geometry** -- how many seconds one prompt holds, derived from
  MAX_INPUT_LENGTH and the 13-tokens-per-second ratio rather than hard-coded.

The prompt construction and the mel front end are pinned against HuggingFace in
``tests/test_asr_preprocess.py``; this file assumes them and tests what stage 2
added on top.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from app.engine import asr_audio, aux_backend
from app.engine.asr_prompt import AsrTokenizer, build_prompt
from app.engine.aux_backend import (
    MAX_AUDIO_SECONDS,
    RESERVED_OUTPUT_TOKENS,
    SEGMENT_CAP_SECONDS,
    AuxRequestError,
)

ROOT = Path(__file__).resolve().parent.parent
TOKENIZER = ROOT / "model-config" / "qwen3_asr" / "tokenizer.json"

pytestmark = pytest.mark.skipif(
    not TOKENIZER.exists(), reason="the ASR tokenizer config is not in this checkout")


# ---------------------------------------------------------------------------
# a scripted engine
# ---------------------------------------------------------------------------
class ScriptedEngine:
    """Stands in for ``aux_native.AsrEngine``: fixes the geometry, replays tokens.

    ``script`` is what generation produces, in order. The prefill returns its
    first element and each ``forward_next`` the next, which is exactly the real
    engine's contract (both return a token), so the backend's loop runs
    unmodified.
    """

    def __init__(self, script=(), seq_len=1024, max_input_length=512,
                 audio_length=100, tokens_per_chunk=13, hidden_size=1024):
        self._script = list(script)
        self._pos = 0
        self.seq_len = seq_len
        self.max_input_length = max_input_length
        self.audio_length = audio_length
        self.tokens_per_chunk = tokens_per_chunk
        self.hidden_size = hidden_size
        self.calls: list[tuple] = []
        self.closed = False

    # the parts of the real engine the backend touches
    def clear(self):
        self.calls.append(("clear",))

    def forward_audio(self, feats, offsets):
        self.calls.append(("audio", feats.shape, list(offsets), feats.copy()))

    def forward_first(self, tokens):
        self.calls.append(("first", list(tokens)))
        self._pos = 1
        return self._script[0] if self._script else IM_END

    def forward_next(self):
        self.calls.append(("next",))
        if self._pos >= len(self._script):
            return IM_END
        token = self._script[self._pos]
        self._pos += 1
        return token

    def close(self):
        self.closed = True

    @property
    def im_end(self):
        return IM_END


TOK = AsrTokenizer.from_file(TOKENIZER)
IM_END = TOK.im_end


def make_backend(script=(), **overrides) -> aux_backend.AsrBackend:
    """A real ``AsrBackend`` around a scripted engine."""
    backend = aux_backend.AsrBackend.__new__(aux_backend.AsrBackend)
    backend._model_id = "asr-test"
    backend._config_dir = str(TOKENIZER.parent)
    backend._tok = TOK
    engine = ScriptedEngine(script, **overrides)
    backend._engine = engine
    backend._gate = aux_backend._Serialised(4)
    backend.seq_len = engine.seq_len
    backend.max_input_length = engine.max_input_length
    backend.audio_length = engine.audio_length
    backend.tokens_per_chunk = engine.tokens_per_chunk
    backend.hidden = engine.hidden_size
    return backend


def wav(seconds: float, rate: int = 16000, bits: int = 16) -> bytes:
    frames = int(round(seconds * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        if bits == 8:
            w.writeframes(bytes(128 + int(60 * math.sin(i / 10.0)) for i in range(frames)))
        else:
            w.writeframes(b"".join(
                struct.pack("<h", int(9000 * math.sin(i / 10.0))) for i in range(frames)))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# segment geometry
# ---------------------------------------------------------------------------
def test_a_segment_is_capped_by_the_prompt_window_and_by_the_hard_cap():
    """512 tokens, a 15-token skeleton and 13 tokens/s gives 37 s; the cap is 30.

    Both numbers matter: the arithmetic one is what the graph can physically
    hold, the cap is what one NPU call should be allowed to take.
    """
    backend = make_backend()
    skeleton = len(build_prompt(TOK, 1, None, "")[0]) - 1
    arithmetic = (512 - skeleton - RESERVED_OUTPUT_TOKENS) // 13
    assert backend.segment_seconds(None) == min(arithmetic, SEGMENT_CAP_SECONDS)


def test_the_window_actually_fits_a_segment_end_to_end():
    """The prompt for one full segment must fit MAX_INPUT_LENGTH.

    A one-token error here is a hard engine failure on real hardware -- the
    graph has no slack -- so the boundary is asserted rather than assumed.
    """
    backend = make_backend()
    for language in (None, "Chinese", "English"):
        seconds = backend.segment_seconds(language)
        frames = seconds * 16000
        from app.engine.asr_prompt import audio_token_count

        n_tokens = audio_token_count(frames // 160, 100, 13)
        ids, _ = build_prompt(TOK, n_tokens, language, "")
        assert len(ids) <= backend.max_input_length, (language, seconds, len(ids))
        # And one second more would not fit, or the cap is not the binding
        # constraint and this test is not testing what it says.
        if seconds < SEGMENT_CAP_SECONDS:
            more = audio_token_count((frames + 16000) // 160, 100, 13)
            assert len(build_prompt(TOK, more, language, "")[0]) > backend.max_input_length


def test_a_context_shortens_the_segment():
    """The context is real prompt tokens, so it has to be paid for in audio."""
    backend = make_backend(max_input_length=200)  # tight enough for context to bite
    plain = backend.segment_seconds(None, "")
    with_context = backend.segment_seconds(None, "会" * 120)
    assert with_context < plain


def test_a_context_that_leaves_no_room_is_refused():
    backend = make_backend()
    with pytest.raises(AuxRequestError, match="放不下"):
        backend.segment_seconds(None, "这是一段很长的上下文" * 200)


def test_the_stub_geometry_would_give_a_longer_segment_than_the_cap():
    """If the cap ever stops binding, this is the test that notices.

    A 1024-token window would allow 76 s; the point of the cap is that 30 s wins.
    """
    backend = make_backend(max_input_length=1024)
    assert backend.segment_seconds(None) == SEGMENT_CAP_SECONDS


# ---------------------------------------------------------------------------
# the decode loop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_request_clears_the_history_first():
    """The engine keeps no context between requests: one client's transcript
    must not depend on another's."""
    backend = make_backend(script=[IM_END])
    await backend.transcribe(wav(1.0))
    kinds = [call[0] for call in backend._engine.calls]
    assert kinds[0] == "clear"
    assert kinds.count("clear") == 1


@pytest.mark.asyncio
async def test_generation_stops_on_the_stop_token_and_counts_what_it_emitted():
    script = [200, 201, 202, IM_END]
    backend = make_backend(script=script)
    result = await backend.transcribe(wav(1.0))
    # 200 came from forward_first itself, then one forward_next per further token
    # including the stop token that ends the loop.
    nexts = [c for c in backend._engine.calls if c[0] == "next"]
    assert len(nexts) == 3
    assert result.completion_tokens == 3


@pytest.mark.asyncio
async def test_generation_is_bounded_by_the_kv_cache():
    """A model that never emits the stop token must still return.

    Without the bound, one bad generation holds the NPU until the request times
    out; with it, the transcript is short and the request completes.
    """
    script = [300] * 5000  # never the stop token
    backend = make_backend(script=script, seq_len=200)
    result = await backend.transcribe(wav(1.0))
    prompt_len = next(len(c[1]) for c in backend._engine.calls if c[0] == "first")
    assert prompt_len < 200, "the prompt must fit, or this tests the wrong bound"
    assert result.completion_tokens == 200 - prompt_len - 1


@pytest.mark.asyncio
async def test_a_prompt_that_fills_the_cache_still_terminates():
    """Degenerate case: the window is zero. It must return, not spin."""
    backend = make_backend(script=[300] * 10, seq_len=1)
    result = await backend.transcribe(wav(0.5))
    assert result.completion_tokens == 0


# ---------------------------------------------------------------------------
# the reference's output rule
# ---------------------------------------------------------------------------
def _tokens(text: str) -> list[int]:
    """Generated ids for ``text``, the way the model would emit them."""
    return TOK.encode(text)


def test_the_language_preamble_is_stripped_from_the_transcript():
    """``language Chinese<asr_text>今天天气不错`` -> ``今天天气不错``.

    The reference pipeline clears its buffer at ``<asr_text>``; everything before
    it is the model restating the instruction, and a client asking for a
    transcript does not want it.
    """
    tokens = _tokens("language Chinese<asr_text>今天天气不错")
    assert aux_backend._parse_generated(TOK, tokens) == "今天天气不错"


def test_a_transcript_with_no_preamble_is_returned_as_is():
    tokens = _tokens("今天天气不错")
    assert aux_backend._parse_generated(TOK, tokens) == "今天天气不错"


def test_an_empty_generation_is_an_empty_transcript():
    assert aux_backend._parse_generated(TOK, []) == ""


def test_a_truncated_preamble_does_not_become_the_transcript():
    """``language Chinese`` with no marker: the preamble is not the answer."""
    tokens = _tokens("language Chinese")
    assert aux_backend._parse_generated(TOK, tokens) == ""


def test_the_detected_language_is_read_from_the_preamble():
    tokens = _tokens("language Chinese<asr_text>你好")
    assert aux_backend._detected_language(TOK, tokens) == "Chinese"


def test_no_preamble_means_no_detected_language():
    assert aux_backend._detected_language(TOK, _tokens("你好")) is None


# ---------------------------------------------------------------------------
# the mel front end as this stage uses it
# ---------------------------------------------------------------------------
def test_padding_happens_in_the_waveform_not_in_the_features():
    """A feature-domain zero is not silence, so the pad has to be audio.

    ``log_mel`` of a zero waveform is about -1.5 (the floor after the ``-8``
    clamp), not 0. Padding features with zeros would therefore hand the tower a
    full-scale step at the chunk boundary -- loud, not quiet -- which is why the
    last window is padded before the mel front end, not after.
    """
    waveform = np.zeros(16000, dtype=np.float32)
    feats = asr_audio.log_mel(waveform)
    assert feats.max() < 0.0
    assert not np.allclose(feats, 0.0)
    # What "silence" actually looks like, so the test pins the value the code
    # comments rely on rather than only "not zero".
    assert float(np.median(feats)) == pytest.approx(-1.5, abs=0.2)


@pytest.mark.asyncio
async def test_the_last_window_is_padded_to_a_whole_second():
    """0.4 s of tail becomes one 1 s tower chunk, not a ragged one.

    Every chunk handed to the engine is 100 frames -- the two stride-2
    convolutions cannot take a partial one -- and the tail must not be dropped.
    """
    backend = make_backend(script=[IM_END], seq_len=4096)
    audio = wav(30.4)
    result = await backend.transcribe(audio)
    chunks = [call for call in backend._engine.calls if call[0] == "audio"]
    assert len(chunks) == 2
    for _, shape, _, _ in chunks:
        assert shape[1] == 128 and shape[2] == 100
    # 30 whole chunks for the full window, then one for the 0.4 s tail padded
    # up to a second -- not a ragged chunk, and not a dropped tail.
    assert [c[1][0] for c in chunks] == [30, 1]
    # The tail really is in there: two segments, the second one 0.4 s long.
    assert len(result.segments) == 2
    assert result.segments[1].end == pytest.approx(30.4, abs=0.02)


@pytest.mark.asyncio
async def test_segments_are_contiguous_and_cover_the_file():
    backend = make_backend(script=[IM_END], seq_len=4096)
    result = await backend.transcribe(wav(75.5))
    assert [s.start for s in result.segments] == pytest.approx(
        [0.0, 30.0, 60.0], abs=0.02)
    assert [s.end for s in result.segments] == pytest.approx(
        [30.0, 60.0, 75.5], abs=0.02)
    assert result.segmented is True
    assert result.duration == pytest.approx(75.5, abs=0.02)


@pytest.mark.asyncio
async def test_audio_under_the_cap_is_one_segment():
    backend = make_backend(script=[IM_END])
    result = await backend.transcribe(wav(5.0))
    assert len(result.segments) == 1
    assert result.segmented is False


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audio_past_the_thirty_minute_cap_is_refused(monkeypatch):
    backend = make_backend(script=[IM_END])
    monkeypatch.setattr(aux_backend, "MAX_AUDIO_SECONDS", 2)
    with pytest.raises(AuxRequestError, match="超过上限"):
        await backend.transcribe(wav(3.0))


@pytest.mark.asyncio
async def test_the_cap_is_thirty_minutes():
    assert MAX_AUDIO_SECONDS == 30 * 60


@pytest.mark.asyncio
async def test_an_unknown_language_is_refused_before_any_npu_work():
    backend = make_backend(script=[IM_END])
    with pytest.raises(ValueError, match="不支持的语言"):
        await backend.transcribe(wav(1.0), language="klingon")
    assert backend._engine.calls == []


@pytest.mark.asyncio
async def test_an_undecodable_container_raises_unsupported_audio(monkeypatch):
    backend = make_backend(script=[IM_END])
    monkeypatch.setattr(asr_audio, "find_ffmpeg", lambda: None)
    with pytest.raises(asr_audio.UnsupportedAudio):
        await backend.transcribe(b"not audio", filename="x.mp3")
    assert backend._engine.calls == []


@pytest.mark.asyncio
async def test_audio_shorter_than_a_tenth_of_a_second_is_refused():
    """20 ms is a WAV header and nothing else; transcribing the room tone is not useful."""
    backend = make_backend(script=[IM_END])
    with pytest.raises(AuxRequestError, match="太短"):
        await backend.transcribe(wav(0.05))


# ---------------------------------------------------------------------------
# ffmpeg lookup (design item 7)
# ---------------------------------------------------------------------------
def test_ffmpeg_is_found_under_opt_sophon_when_it_is_not_on_path(monkeypatch, tmp_path):
    """The board's ffmpeg is not on PATH; the SDK keeps it under /opt/sophon."""
    sdk = tmp_path / "sophon"
    exe = sdk / "sophon-ffmpeg-latest" / "bin" / "ffmpeg"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.delenv("CV84X6_FFMPEG", raising=False)
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: None)
    assert asr_audio.find_ffmpeg(sdk_root=sdk) == str(exe)


def test_the_environment_variable_wins(monkeypatch, tmp_path):
    exe = tmp_path / "my-ffmpeg"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("CV84X6_FFMPEG", str(exe))
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert asr_audio.find_ffmpeg() == str(exe)


def test_an_unusable_environment_override_does_not_silently_fall_back(monkeypatch, tmp_path):
    """An operator who set CV84X6_FFMPEG meant *that* binary.

    Falling back to whatever PATH finds would hide a typo, and the transcode
    would then run a different ffmpeg than the one they chose.
    """
    monkeypatch.setenv("CV84X6_FFMPEG", str(tmp_path / "missing"))
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert asr_audio.find_ffmpeg() is None


def test_path_is_preferred_over_the_sdk_copy(monkeypatch, tmp_path):
    monkeypatch.delenv("CV84X6_FFMPEG", raising=False)
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert asr_audio.find_ffmpeg() == "/usr/bin/ffmpeg"


def test_the_highest_sdk_version_wins(monkeypatch, tmp_path):
    """``sophon-ffmpeg_2.10.0`` must beat ``sophon-ffmpeg_2.9.0``.

    String order gets that backwards, which is why the versions are compared as
    numbers.
    """
    sdk = tmp_path / "sophon"
    old = sdk / "sophon-ffmpeg_2.9.0" / "bin" / "ffmpeg"
    new = sdk / "sophon-ffmpeg_2.10.0" / "bin" / "ffmpeg"
    for exe in (old, new):
        exe.parent.mkdir(parents=True)
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    monkeypatch.delenv("CV84X6_FFMPEG", raising=False)
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: None)
    assert asr_audio.find_ffmpeg(sdk_root=sdk) == str(new)


def test_no_ffmpeg_anywhere_returns_none(monkeypatch, tmp_path):
    sdk = tmp_path / "sophon"
    sdk.mkdir()
    monkeypatch.delenv("CV84X6_FFMPEG", raising=False)
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: None)
    assert asr_audio.find_ffmpeg(sdk_root=sdk) is None


def test_a_versioned_sdk_with_no_latest_symlink_is_still_found(monkeypatch, tmp_path):
    sdk = tmp_path / "sophon"
    exe = sdk / "sophon-ffmpeg_2.3.0" / "bin" / "ffmpeg"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.delenv("CV84X6_FFMPEG", raising=False)
    monkeypatch.setattr(asr_audio.shutil, "which", lambda name: None)
    assert asr_audio.find_ffmpeg(sdk_root=sdk) == str(exe)


# ---------------------------------------------------------------------------
# the reported language, across segments
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_forced_language_wins_over_what_a_segment_claims():
    """The caller said which language to use, so that is the answer.

    The reference does the same thing: ``parse_asr_output`` returns
    ``user_language`` verbatim when the language was forced, without reading the
    preamble at all.
    """
    backend = make_backend(script=_tokens("language English<asr_text>hello"),
                           seq_len=4096)
    result = await backend.transcribe(wav(1.0), language="zh")
    assert result.language == "Chinese"


@pytest.mark.asyncio
async def test_the_language_is_merged_across_segments_not_taken_from_the_first():
    """A file that switches language must say so.

    Reading only ``segments[0]`` labels the whole file by its first 30 s, which
    for a multilingual recording is wrong for most of it. The reference merges
    per-chunk languages in order (``merge_languages``).
    """
    backend = make_backend(script=_tokens("language Chinese<asr_text>你好"),
                           seq_len=4096)
    # Two prompts: 60 s of audio at a 30 s cap.
    result = await backend.transcribe(wav(60.0))
    assert len(result.segments) == 2
    # Both segments stated Chinese, so the merge does not repeat it.
    assert result.language == "Chinese"


@pytest.mark.asyncio
async def test_no_stated_language_and_no_forced_one_is_none():
    """Not a guess: if neither the caller nor the model said, the field is null."""
    backend = make_backend(script=_tokens("你好"))
    result = await backend.transcribe(wav(1.0))
    assert result.language is None


def test_merge_drops_consecutive_duplicates_but_keeps_a_switch():
    """The reference's ``merge_languages``: order kept, consecutive dupes gone."""
    tok = TOK

    def seg(text):
        return aux_backend._RawSegment(start=0.0, end=1.0, text="", tokens=tok.encode(text),
                                       prompt_tokens=0, completion_tokens=0)

    segments = [seg("language Chinese<asr_text>a"),
                seg("language Chinese<asr_text>b"),
                seg("language English<asr_text>c"),
                seg("language Chinese<asr_text>d")]
    assert aux_backend._transcript_language(tok, segments, None) == "Chinese,English,Chinese"


# ---------------------------------------------------------------------------
# the protocol line bound
# ---------------------------------------------------------------------------
def test_the_asr_line_limit_holds_a_maximum_size_upload():
    """A 50 MiB upload is 66.7 MiB of base64 in one JSON line.

    The chat path's 64 MiB bound is smaller than that, so an ASR worker using it
    would drop a *legal* request inside asyncio's reader, with an error nobody in
    this codebase raises. The limit is derived from the endpoint's own cap so
    raising the cap cannot leave the transport behind.
    """
    import base64
    import json

    from app.api.audio_upload import MAX_UPLOAD_BYTES
    from app.core.client import _line_limit
    from app.engine.worker import STREAM_LIMIT, stream_limit_for

    payload = base64.b64encode(b"\0" * MAX_UPLOAD_BYTES).decode("ascii")
    line = json.dumps({"op": "transcribe", "req_id": "x", "audio_b64": payload})
    needed = len(line.encode()) + 1  # the newline the protocol appends

    # The bound the worker really starts its server with, not just the helper:
    # the bug this replaces was that ASR was handed the chat path's bound.
    assert stream_limit_for("asr") > needed, "the worker would reject a legal upload"
    assert _line_limit() > needed, "the client would reject its own request"
    # The chat and text-aux bounds are deliberately unchanged: their largest
    # request is images, not a file.
    assert STREAM_LIMIT == 64 * 1024 * 1024
    assert stream_limit_for("chat") == stream_limit_for("rerank") == STREAM_LIMIT


async def test_decoding_does_not_block_the_worker_event_loop(monkeypatch):
    """ffmpeg / resampling run in a thread: health and stats keep answering meanwhile."""
    import asyncio
    import time as _time

    from app.engine import asr_audio

    real = asr_audio.decode_audio

    def slow_decode(data, filename=None):
        _time.sleep(0.5)
        return real(data, filename)

    monkeypatch.setattr(asr_audio, "decode_audio", slow_decode)
    backend = make_backend()
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        await backend.transcribe(wav(2.0))
    finally:
        task.cancel()
    assert ticks >= 5, f"event loop stalled during decode (ticks={ticks})"


def test_ffmpeg_that_hangs_is_given_up_as_unsupported(monkeypatch, tmp_path):
    import subprocess

    from app.engine import asr_audio

    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CV84X6_FFMPEG", str(fake))

    def hang(cmd, **kwargs):
        assert kwargs.get("timeout") == asr_audio.FFMPEG_TIMEOUT_S
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(asr_audio.subprocess, "run", hang)
    with pytest.raises(asr_audio.UnsupportedAudio, match="超过"):
        asr_audio.decode_audio(b"ID3 not really mp3", filename="clip.mp3")


# ---------------------------------------------------------------------------
# the streaming generator (the one both paths are built on)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_iter_transcribe_yields_meta_before_the_first_segment():
    """``meta`` is on the wire while the engine is still idle.

    This is the property the endpoint exists for: the console learns the
    duration and the segment count before a single NPU call has run, so it can
    draw a progress bar instead of a spinner.
    """
    backend = make_backend(script=[IM_END], seq_len=4096)
    stream = backend.iter_transcribe(wav(75.5))
    meta = await stream.__anext__()
    assert meta["type"] == "meta"
    assert meta["segments_total"] == 3
    assert meta["duration"] == pytest.approx(75.5, abs=0.02)
    assert meta["segment_seconds"] == SEGMENT_CAP_SECONDS
    # Nothing has touched the engine yet.
    assert [c for c in backend._engine.calls if c[0] != "clear"] == []
    await stream.aclose()


@pytest.mark.asyncio
async def test_iter_transcribe_and_transcribe_agree_segment_for_segment():
    """One producer: the stream's segments are the plain reply's, exactly."""
    script = _tokens("language Chinese<asr_text>这段话是测试")
    backend = make_backend(script=script, seq_len=4096)
    audio = wav(65.0)

    frames = [f async for f in backend.iter_transcribe(audio)]
    result = await backend.transcribe(audio)

    assert [f["type"] for f in frames] == ["meta", "segment", "segment", "segment", "done"]
    streamed = frames[1:-1]
    assert len(streamed) == len(result.segments)
    for got, want in zip(streamed, result.segments):
        assert got["text"] == want.text
        assert got["start"] == pytest.approx(want.start, abs=1e-9)
        assert got["end"] == pytest.approx(want.end, abs=1e-9)
    assert frames[-1]["text"] == result.text
    assert frames[-1]["language"] == result.language
    assert frames[-1]["prompt_tokens"] == result.prompt_tokens
    assert frames[-1]["completion_tokens"] == result.completion_tokens


@pytest.mark.asyncio
async def test_a_cancelled_stream_does_not_advance_to_the_next_segment():
    """The disconnect contract, one level below the API.

    Closing the generator between segments must end the loop -- no further
    ``clear``/``first`` cycle -- because that is what makes "cancelling stops the
    NPU after the segment in flight" true rather than wishful.
    """
    backend = make_backend(script=[IM_END], seq_len=4096)
    stream = backend.iter_transcribe(wav(95.0))   # four 30 s segments
    await stream.__anext__()                       # meta
    first = await stream.__anext__()
    assert first["id"] == 0
    prompts_before = sum(1 for c in backend._engine.calls if c[0] == "first")
    assert prompts_before == 1

    await stream.aclose()

    prompts_after = sum(1 for c in backend._engine.calls if c[0] == "first")
    assert prompts_after == prompts_before, "a segment ran after the stream closed"


@pytest.mark.asyncio
async def test_a_cancel_during_a_segment_lets_that_segment_finish():
    """Cancellation must not release the engine lock under a live NPU call.

    ``asyncio.to_thread`` cannot stop a thread, so cancelling the await would
    let the next request enter the engine while this one is still inside it.
    The segment in flight therefore runs to completion and the *next* one never
    starts -- which is the documented behaviour, asserted rather than assumed.

    The lock is observed directly: it must still be held by the cancelled
    request until its NPU call is really over, and free immediately after.
    """
    import asyncio as _asyncio
    import time as _time

    entered = _asyncio.Event()
    finished: list[int] = []

    backend = make_backend(script=[IM_END], seq_len=4096)
    real_run = backend._run_prompt

    def slow_run(feats, language, context):
        # A synchronous sleep: this is what an uninterruptible NPU call looks
        # like from the event loop's point of view.
        entered.set()
        _time.sleep(0.3)
        finished.append(1)
        return real_run(feats, language, context)

    backend._run_prompt = slow_run
    stream = backend.iter_transcribe(wav(95.0))   # four 30 s segments
    await stream.__anext__()                       # meta
    task = _asyncio.create_task(stream.__anext__())
    await entered.wait()
    task.cancel()
    # Still inside the NPU call: the lock must not be available.
    assert backend._gate._lock.locked(), "the engine was handed over mid-call"
    await _asyncio.sleep(0.5)

    assert finished, "the NPU call was abandoned instead of allowed to finish"
    assert task.done() and task.cancelled()
    assert len(finished) == 1, "a second segment ran after the cancel"
    assert not backend._gate._lock.locked(), "the lock leaked"
    await stream.aclose()
