"""``POST /v1/audio/transcriptions`` end-to-end over the mock backend.

Drives real worker subprocesses (the mock engine), so everything between the
multipart body and the recorded row is exercised: the upload parser and its
size cap, the admission gate, the kind check, the language validation, the
segmentation of long audio, the five response formats and the one record each
request leaves behind.

The mock decodes the audio for real -- ``asr_audio.decode_audio``, the same
front end the board runs -- and invents only the words. So the *durations*, the
*segment boundaries*, the 415 for an undecodable container and the 400 for
audio that is too long are all facts about real code, not about the fake.
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

#: 1 s of 16 kHz mono 16-bit PCM is 32 000 bytes; the mock's segmentation is
#: driven by the real MAX_INPUT_LENGTH/13, which is 38 s at this build.
SAMPLE_RATE = 16000
#: One prompt holds floor((512 - 15 - 8) / 13) = 37 s, and the segment cap is
#: 30 s, so a segment is 30 s of audio.
SEGMENT_SECONDS = 30


def make_model(root: Path, name: str, bmodel: str, context: str = "seq1024"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


#: The file names the catalogue's downloads land as -- the same strings the kind
#: detector reads, so these tests cover the naming contract too.
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
            # 8-bit PCM is unsigned, centred on 128.
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


def _transcribe(client, headers, *, audio: bytes, filename="a.wav", **fields):
    data = {"model": fields.pop("model", "asr-model")}
    data.update({k: v for k, v in fields.items() if v is not None})
    return client.post("/v1/audio/transcriptions", headers=headers, data=data,
                       files={"file": (filename, audio, "application/octet-stream")})


def _records(client) -> list[dict]:
    """Every transcription record, in full.

    The list route carries summaries only (no output text, no messages), so the
    detail route is what the record assertions read -- that is the shape an
    operator sees when they open a row.
    """
    r = client.get("/api/inference-records", params={"limit": 200})
    assert r.status_code == 200, r.text
    ids = [item["id"] for item in r.json()["items"]
           if item["source"] == "/v1/audio/transcriptions"]
    out = []
    for record_id in ids:
        detail = client.get(f"/api/inference-records/{record_id}")
        assert detail.status_code == 200, detail.text
        out.append(detail.json())
    return out


# ---------------------------------------------------------------------------
# the one happy path, in each format
# ---------------------------------------------------------------------------
def test_json_is_the_default_and_returns_only_text(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"text"}
    assert body["text"].startswith("segment 0:")
    # Deterministic for the same bytes, which is what makes the rest checkable.
    again = _transcribe(client, h, audio=wav_bytes(2.0))
    assert again.json()["text"] == body["text"]


def test_text_format_is_a_plain_body_with_no_json(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), response_format="text")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("segment 0:")
    with pytest.raises(json.JSONDecodeError):
        json.loads(r.text)


def test_verbose_json_carries_the_openai_fields(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), response_format="verbose_json")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task"] == "transcribe"
    assert body["duration"] == pytest.approx(2.0, abs=0.01)
    assert body["text"].startswith("segment 0:")
    assert body["language"] is None  # nothing forced, and the mock detects nothing
    seg = body["segments"][0]
    # The keys an OpenAI client actually reads. A missing one is an AttributeError
    # in the SDK, not a silently ignored field.
    for key in ("id", "start", "end", "text", "seek", "tokens", "temperature",
                "avg_logprob", "compression_ratio", "no_speech_prob"):
        assert key in seg, key
    assert seg["start"] == 0.0
    assert seg["end"] == pytest.approx(2.0, abs=0.01)
    assert body["usage"]["total_tokens"] > 0


def test_srt_has_numbered_cues_with_comma_timestamps(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), response_format="srt")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-subrip")
    lines = r.text.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,000"
    assert lines[2].startswith("segment 0:")
    # Cues are separated by a blank line and the body ends with one; SubRip
    # parsers key on both, so neither may be dropped.
    assert r.text.endswith("\n")


def test_srt_separates_two_cues_with_a_blank_line(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0 * SEGMENT_SECONDS),
                    response_format="srt")
    assert r.status_code == 200, r.text
    assert "\n\n2\n" in r.text


def test_vtt_has_the_required_header_and_dot_timestamps(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), response_format="vtt")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/vtt")
    lines = r.text.splitlines()
    assert lines[0] == "WEBVTT"
    assert lines[2] == "00:00:00.000 --> 00:00:02.000"
    assert lines[3].startswith("segment 0:")


def test_an_unknown_response_format_is_refused(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(1.0), response_format="yaml")
    assert r.status_code == 400, r.text
    assert "response_format" in r.json()["detail"]


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------
def test_a_chat_model_is_a_400_naming_the_right_endpoint(client):
    h = _login_and_load(client, "chat-model")
    r = _transcribe(client, h, audio=wav_bytes(1.0), model="chat-model")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "chat" in detail and "/v1/chat/completions" in detail


def test_an_asr_model_at_the_chat_endpoint_is_a_400(client):
    """The mismatch has to be refused in both directions, or the kind check is half a check."""
    h = _login_and_load(client, "asr-model")
    r = client.post("/v1/chat/completions", headers=h,
                    json={"model": "asr-model",
                          "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400, r.text
    assert "/v1/audio/transcriptions" in r.json()["detail"]


def test_a_multipart_body_without_a_file_is_a_400(client):
    h = _login_and_load(client, "asr-model")
    r = client.post(
        "/v1/audio/transcriptions", headers=h,
        files={"model": (None, "asr-model")})
    assert r.status_code == 400, r.text
    assert "file" in r.json()["detail"]


def test_a_urlencoded_body_is_refused_as_not_multipart(client):
    """Some clients post the simple form instead of multipart; say so plainly."""
    h = _login_and_load(client, "asr-model")
    r = client.post("/v1/audio/transcriptions", headers=h,
                    data={"model": "asr-model"})
    assert r.status_code == 400, r.text
    assert "multipart" in r.json()["detail"]


def test_a_missing_or_empty_model_is_a_400(client):
    h = _login_and_load(client, "asr-model")
    r = client.post("/v1/audio/transcriptions", headers=h,
                    files={"file": ("a.wav", wav_bytes(1.0), "audio/wav")},
                    data={})
    assert r.status_code == 400, r.text
    assert "model" in r.json()["detail"]


def test_a_non_multipart_body_is_a_400_not_a_500(client):
    h = _login_and_load(client, "asr-model")
    r = client.post("/v1/audio/transcriptions", headers={**h, "Content-Type": "application/json"},
                    content=b'{"model": "asr-model"}')
    assert r.status_code == 400, r.text
    assert "multipart" in r.json()["detail"]


def test_a_not_wav_body_without_ffmpeg_is_415(client, monkeypatch):
    """415 is the code for "the audio's format", not for "your request".

    ``find_ffmpeg`` returning None is the substrate-without-ffmpeg case; the
    board has one, which is why the same code path is what the real device
    exercises for mp3.
    """
    from app.engine import asr_audio

    monkeypatch.setattr(asr_audio, "find_ffmpeg", lambda: None)
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=b"ID3\x04\x00\x00\x00\x00\x00\x00rawmp3",
                    filename="a.mp3")
    assert r.status_code == 415, r.text
    assert "ffmpeg" in r.json()["detail"]


def test_a_broken_wav_is_415(client):
    h = _login_and_load(client, "asr-model")
    # A RIFF/WAVE header with no fmt or data chunk: decodable by nothing.
    r = _transcribe(client, h, audio=b"RIFF" + b"\x00" * 4 + b"WAVE" + b"junk"
                    + struct.pack("<I", 4) + b"xxxx")
    assert r.status_code == 415, r.text


def test_an_unknown_language_is_a_400_listing_the_names(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(1.0), language="klingon")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "Chinese" in detail and "English" in detail


def test_audio_longer_than_the_cap_is_a_400(client):
    """30 minutes is the ceiling; the check is on the decoded duration, not the size."""
    h = _login_and_load(client, "asr-model")
    # 31 minutes of 16 kHz 8-bit mono is 28 MB: inside the 50 MB upload cap, so
    # this really reaches the duration check rather than the size check.
    r = _transcribe(client, h, audio=wav_bytes(31 * 60, bits=8))
    assert r.status_code == 400, r.text
    assert "超过上限" in r.json()["detail"]


def test_a_bad_temperature_is_a_400(client):
    """Accepted and ignored, but not silently: nonsense is still nonsense."""
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(1.0), temperature="hot")
    assert r.status_code == 400, r.text
    assert "temperature" in r.json()["detail"]


def test_temperature_in_range_is_accepted_and_the_transcript_is_identical(client):
    h = _login_and_load(client, "asr-model")
    audio = wav_bytes(1.0)
    cold = _transcribe(client, h, audio=audio, temperature="0")
    warm = _transcribe(client, h, audio=audio, temperature="0.9")
    assert cold.status_code == warm.status_code == 200, (cold.text, warm.text)
    # Greedy decoding: the accepted value must not change the answer.
    assert cold.json()["text"] == warm.json()["text"]


def test_a_50mb_upload_is_refused_before_it_is_read(client):
    """The cap is on the body, not on the decoded audio: an explicit 400 beats an OOM."""
    h = _login_and_load(client, "asr-model")
    from app.api import audio_upload

    old = audio_upload.MAX_UPLOAD_BYTES
    audio_upload.MAX_UPLOAD_BYTES = 64 * 1024
    try:
        huge = b"\x00" * (256 * 1024)
        r = client.post("/v1/audio/transcriptions", headers=h,
                        data={"model": "asr-model"},
                        files={"file": ("big.wav", huge, "audio/wav")})
    finally:
        audio_upload.MAX_UPLOAD_BYTES = old
    assert r.status_code == 400, r.text
    assert "上限" in r.json()["detail"]


def test_a_second_file_part_is_refused(client):
    h = _login_and_load(client, "asr-model")
    r = client.post(
        "/v1/audio/transcriptions", headers=h,
        data={"model": "asr-model"},
        files=[("file", ("a.wav", wav_bytes(1.0), "audio/wav")),
               ("file", ("b.wav", wav_bytes(1.0), "audio/wav"))])
    assert r.status_code == 400, r.text


def test_an_unloaded_model_is_loaded_on_demand(client):
    """The admission gate is shared, so on-demand loading is shared too.

    Since MYS-2657 an auxiliary model that is on disk but unloaded is brought up
    rather than refused -- otherwise an auto-unload would turn the next request
    into a 409 nobody asked for. The 409 path is now the operator's switch:
    ``test_auto_load_disabled_answers_409`` in ``tests/test_aux_idle.py``.
    """
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    client.post("/api/settings", json={"aux_auto_load": True})  # off by default since v0.6.28
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    r = client.post("/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {raw}"},
                    data={"model": "asr-model"},
                    files={"file": ("a.wav", wav_bytes(1.0), "audio/wav")})
    assert r.status_code == 200, r.text
    assert r.json()["text"]


# ---------------------------------------------------------------------------
# long audio: segmentation and timestamps
# ---------------------------------------------------------------------------
def test_audio_past_one_prompt_is_cut_into_contiguous_segments(client):
    """90 s of audio at 38 s per prompt is three segments, back to back.

    The timestamps are the point: a client that stitches subtitles needs each
    cue to start where the previous one ended, and needs the last one to end at
    the file's real duration.
    """
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(90.0), response_format="verbose_json")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration"] == pytest.approx(90.0, abs=0.05)
    segments = body["segments"]
    assert len(segments) == math.ceil(90 / SEGMENT_SECONDS) == 3
    for i, seg in enumerate(segments):
        assert seg["id"] == i
        # Contiguous: each cue starts exactly where the previous one ended.
        if i:
            assert seg["start"] == pytest.approx(segments[i - 1]["end"], abs=1e-6)
        assert seg["end"] - seg["start"] == pytest.approx(
            min(SEGMENT_SECONDS, 90 - i * SEGMENT_SECONDS), abs=0.02)
    assert segments[0]["start"] == 0.0
    assert segments[-1]["end"] == pytest.approx(90.0, abs=0.05)
    # The joined text is every segment's text in order, so nothing is dropped.
    assert body["text"] == " ".join(s["text"] for s in segments)


def test_a_tail_shorter_than_one_second_still_gets_a_segment(client):
    """60.4 s is three prompts: the 0.4 s tail must not vanish.

    The reference truncates to whole seconds and loses it; padding the waveform
    is what keeps the last word of a clip.
    """
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(60.4), response_format="verbose_json")
    assert r.status_code == 200, r.text
    segments = r.json()["segments"]
    assert len(segments) == 3
    assert segments[2]["start"] == pytest.approx(60.0, abs=0.02)
    assert segments[2]["end"] == pytest.approx(60.4, abs=0.05)


def test_srt_timestamps_follow_the_segments(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(80.0), response_format="srt")
    assert r.status_code == 200, r.text
    cues = [line for line in r.text.splitlines() if "-->" in line]
    assert len(cues) == 3  # 30 + 30 + 20
    assert cues[0] == "00:00:00,000 --> 00:00:30,000"
    assert cues[1] == "00:00:30,000 --> 00:01:00,000"
    assert cues[2].startswith("00:01:00,000 --> 00:01:20,000")


def test_a_forced_language_is_reported_back(client):
    """A forced language is what the model was told to use, so it is what the reply says."""
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), language="zh",
                    response_format="verbose_json")
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "Chinese"


def test_an_iso_code_and_the_canonical_name_agree(client):
    h = _login_and_load(client, "asr-model")
    audio = wav_bytes(2.0)
    by_code = _transcribe(client, h, audio=audio, language="en",
                          response_format="verbose_json").json()
    by_name = _transcribe(client, h, audio=audio, language="English",
                          response_format="verbose_json").json()
    assert by_code["language"] == by_name["language"] == "English"
    assert by_code["text"] == by_name["text"]


# ---------------------------------------------------------------------------
# the inference record
# ---------------------------------------------------------------------------
def test_one_record_per_request_with_the_source_and_the_transcript(client):
    h = _login_and_load(client, "asr-model")
    r = _transcribe(client, h, audio=wav_bytes(2.0), language="en", prompt="a glossary")
    assert r.status_code == 200, r.text
    text = r.json()["text"]

    rows = [x for x in _records(client) if x["source"] == "/v1/audio/transcriptions"]
    assert len(rows) >= 1
    row = rows[0]
    assert row["model"] == "asr-model"
    assert row["status"] == "ok"
    assert row["output_text"] == text
    assert row["prompt_tokens"] > 0
    assert row["completion_tokens"] > 0

    # The stored messages describe the upload -- filename, format, duration --
    # and never the audio itself.
    messages = row["messages"]
    assert isinstance(messages, list) and len(messages) == 1
    described = json.loads(messages[0]["content"])
    assert described["filename"] == "a.wav"
    assert described["format"] == "wav"
    assert described["language"] == "en"
    assert described["prompt"] == "a glossary"
    assert described["bytes"] > 0
    assert "duration" in row["params"]
    assert row["params"]["response_format"] == "json"

    # No audio anywhere in the row, by any of the columns that could carry it.
    blob = json.dumps(row, ensure_ascii=False)
    assert "audio_b64" not in blob
    assert "UklGR" not in blob  # "RIFF" in base64


def test_a_415_leaves_an_error_record(client, monkeypatch):
    from app.engine import asr_audio

    monkeypatch.setattr(asr_audio, "find_ffmpeg", lambda: None)
    h = _login_and_load(client, "asr-model")
    before = len([x for x in _records(client)
                  if x["source"] == "/v1/audio/transcriptions"])
    r = _transcribe(client, h, audio=b"not audio at all", filename="x.mp3")
    assert r.status_code == 415, r.text
    rows = [x for x in _records(client) if x["source"] == "/v1/audio/transcriptions"]
    assert len(rows) == before + 1
    assert rows[0]["status"] == "error"
    assert rows[0]["error_type"]


def test_a_validation_error_writes_no_record(client):
    """A 400 before the model ran is not an inference, so it gets no row."""
    h = _login_and_load(client, "asr-model")
    before = len(_records(client))
    r = _transcribe(client, h, audio=wav_bytes(1.0), language="klingon")
    assert r.status_code == 400
    assert len(_records(client)) == before


# ---------------------------------------------------------------------------
# the model list
# ---------------------------------------------------------------------------
def test_v1_models_lists_the_asr_model_with_its_kind(client):
    h = _login_and_load(client, "asr-model", "chat-model")
    body = client.get("/v1/models", headers=h).json()
    kinds = {m["id"]: m["kind"] for m in body["data"]}
    assert kinds["asr-model"] == "asr"
    assert kinds["chat-model"] == "chat"
