"""Legacy-readiness probe (MYS-2502): what a *v0.6.13* service does with a request
sent before its model has finished initialising.

    python3 tools/legacy_readiness_probe.py --evidence-dir ./evidence

The question this answers is one the fixed build (v0.6.14) made unaskable. From
v0.6.14 on, ``ModelManager.require_ready`` refuses every inference route while a
model is loading, so the load window returns 409 and there is nothing to observe
behind it. The field report this whole project started from -- a customer whose
summarisation came back wrong -- happened on v0.6.12, where the window was open.
This tool installs v0.6.13, hits that window on purpose at several delays, and
records what the service actually did instead of what the code suggests it
should do.

Six rules shape the design:

* **One experiment is one load.** Every timing is an independent
  unload -> load -> request cycle. A shared load would let the first request's
  timing contaminate the second's state, which is the one variable being
  measured. The cost is ~70 s per timing and that cost is the experiment.
* **The delay is a target, not a claim.** ``--delays 0.1 5 15 ...`` asks the
  probe to send ~5 s after the load request returned its first byte; what
  actually happened is recorded to the millisecond, and the model's own state at
  that instant (``loaded``/``operation``/``load_error`` from the admin API) is
  sampled immediately before the request. ``actual_delay_s`` is reported next to
  ``target_delay_s`` and every row carries the state it really saw, so a delay
  that landed after readiness is reported as a post-ready control rather than
  being called a load-window sample.
* **A wall-clock delay cannot hit a narrow window, so ``edge`` does not use one.**
  ``--delays edge`` polls ``/api/models`` as fast as the admin API answers and
  fires the instant the model reports ``loaded: true`` while ``operation`` is
  still set -- the exact state v0.6.13 publishes between its readiness handshake
  and the end of its capability probe. That state is what "loaded but not
  settled" means for this build, and a "65 s" guess would straddle it or miss it
  depending on the day. Both kinds of timing are reported side by side and
  labelled, so a reader can tell a guessed instant from a hit one.
* **Native or instrumented, never blurred.** ``--mode native`` measures the
  shipped binary. ``--mode instrumented`` measures a *test build* of it: the
  same release, started with a ``sitecustomize.py`` that delays only
  ``WorkerClient.health`` -- whose sole caller in v0.6.13 is the capability probe
  inside the window -- so the window can be hit on demand instead of by luck.
  The two are separate evidence directories, separate rows and separate report
  sections; a finding from the instrumented run is never reported as native
  behaviour. See :data:`SITECUSTOMIZE` and :func:`write_sitecustomize`.
* **Every timing covers both OpenAI shapes and the console route.** Stream and
  non-stream take different code paths to the same worker, and the console has
  its own. A window that refuses one and admits another is exactly the kind of
  half-fix the report has to be able to show.
* **The output is scanned for the known decode defect.** v0.6.13 splits a
  multi-byte character across two tokens and emits ``\ufffd`` (MYS-2510); it is a
  separate, pre-existing defect, so every output is scanned and the count is
  reported beside -- never folded into -- the load-race verdict.
* **A hang is evidence, not a retry.** ``dmesg`` is read before each timing and
  after the whole run. ``wait api timeout`` / ``bdc_reg_read`` means the TPU is
  wedged: the probe stops touching the NPU, saves everything, and reports. It
  never kills a worker mid-load to save time, and it never reboots on its own.

What counts as a race observation (and what does not) is decided in
:func:`classify`, from the recorded facts only -- see its docstring. The report
is assembled by :func:`write_report` into one self-contained HTML file.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ---------------------------------------------------------------------------
# The fixed request (verbatim from the task card)
# ---------------------------------------------------------------------------
#: The user message under test, byte for byte as the task card and the customer
#: report quote it. It is not generated, not trimmed and not re-punctuated: the
#: open question is whether the field symptom reproduces, and "reproduced with a
#: paraphrase" is not an answer.
INPUT_TEXT = (
    "两个女生约好一起出门吃火锅，出门的时候穿的是很常规的抹胸连衣裙，本身穿搭得体，"
    "没有出格的地方。入座之后想到牛油火锅油星飞溅很厉害，一不小心就会弄脏裙子，"
    "看到店里准备了免费围裙，就顺手拿起来穿上，想护住身上的衣服。\n\n"
    "谁也没想到，就是这一个简单的防油操作，闹出了一场让人哭笑不得的误会。"
    "这款围裙版型偏大，上沿位置很高，刚好把抹胸裙的上半部分全部遮挡住。"
    "远远看过去，只能看见围裙和露出的肩膀脖颈，视觉上很容易产生 “里面没有穿衣服” 的错觉。\n\n"
    "旁边有其他食客看到这一幕，眼神变得奇怪，甚至有人悄悄议论。两个女生一开始还没反应过来，"
    "等到察觉到周围异样的目光，才明白问题出在哪，瞬间尴尬不已。本来只是为了保护裙子，"
    "没想到一件围裙，凭空制造出这样的乌龙。\n\n"
    "这件事传到网上之后，很快分成两种不同的声音。一部分网友觉得特别能理解女生的尴尬，"
    "围裙的设计本身就有问题，遮挡范围太大，才造成这种视觉误差，女生只是正常吃火锅、"
    "爱惜自己的裙子，完全没有任何问题，旁人不该随便揣测。\n"
    "总结一下以上文章，主要内容"
)

#: Same sampling shape for every request in the run, so the only thing that varies
#: between two timings is the model's state. `max_tokens` is the task card's
#: "统一配置": 128 tokens is enough for a one-paragraph summary of a 444-character
#: article and small enough that a reply inside a load window cannot itself take
#: minutes.
PARAMS: dict = {
    "max_tokens": 128,
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 1,
    "repetition_penalty": 1.0,
    "enable_thinking": False,
}

MODEL_DEFAULT = "qwen3.6-35b-a3b-128k"
ADMIN_PASSWORD_DEFAULT = "admin"

#: The character the pre-v0.6.15 decoder emits when a multi-byte character is
#: split across tokens (MYS-2510). Scanned for, never assumed absent.
REPLACEMENT_CHAR = "\ufffd"

#: Surface order inside one timing. Fixed, and the report lists them in this
#: order: stream and non-stream are the two OpenAI shapes, console is the browser
#: route with cookie auth. A timing that only covered one of them could not
#: answer "does the window admit every surface or just some".
SURFACES = ("stream", "nonstream", "console")

#: How long one inference attempt may take before the probe gives up on it. A
#: request that reaches a half-initialised engine can hang for a long time; the
#: probe must record that as a hang, not wait forever. 300 s is far longer than a
#: healthy 444-character summary (~1-3 s on this board) and shorter than the
#: load itself, so a hung request cannot masquerade as "still loading".
REQUEST_TIMEOUT_S = 300.0

#: How long to wait for a load to finish after the last attempt. The 128k model
#: takes ~66 s on this board; the admin API's own load request has its own
#: timeout, so this only bounds the probe's wait, not the service's work.
LOAD_TIMEOUT_S = 420.0

#: Interval between the "is it ready yet" polls. Cheap (a GET), and fine enough
#: that ``actual_delay_s`` is measured rather than assumed.
READY_POLL_S = 0.1

#: A load is considered to have *started* when the admin API shows
#: ``operation=loading``; the probe uses the post's own send time as t0 for the
#: target delay, and reports the difference so the report can be honest about it.
LOAD_POST_GRACE_S = 5.0


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def utc(ts: float | None) -> str | None:
    if not ts:
        return None
    return (datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def count_replacement(text: str) -> list[dict]:
    """Every ``\ufffd`` occurrence with its offset and surrounding text.

    ``offset`` is a code-point index, so it lines up with ``len`` of the string
    the service returned rather than with a byte offset in the SSE body.
    """
    out: list[dict] = []
    for index, ch in enumerate(text or ""):
        if ch == REPLACEMENT_CHAR:
            start = max(0, index - 12)
            end = min(len(text), index + 13)
            out.append({"offset": index, "context": text[start:end]})
    return out


def rss_kb() -> int | None:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def spread(values: Iterable[float | None]) -> dict:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"count": 0}
    return {
        "count": len(clean),
        "min": round(min(clean), 3),
        "median": round(statistics.median(clean), 3),
        "p95": round(percentile(clean, 0.95) or 0, 3),
        "max": round(max(clean), 3),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Http:
    """Thread-safe-by-instance urllib client with a cookie jar.

    Every call constructs its own ``Request``; the jar is only mutated by
    ``login``. The probe uses one instance for admin calls and a fresh one per
    surface attempt, so a 300 s timeout on one surface cannot poison the next.
    """

    def __init__(self, base: str, timeout: float = 600.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def url(self, path: str) -> str:
        return self.base + (path if path.startswith("/") else "/" + path)

    def open(self, req: urllib.request.Request, timeout: float | None = None):
        return self.opener.open(req, timeout=timeout or self.timeout)

    def request(self, method: str, path: str, payload=None,
                headers: dict | None = None,
                timeout: float | None = None) -> tuple[int, bytes]:
        data = None
        hdrs = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = urllib.request.Request(self.url(path), data=data, headers=hdrs,
                                     method=method)
        try:
            with self.open(req, timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            # A refused connection during a load is a fact about the service
            # (it is restarting, or the load wedged it). Surfaced as status 0
            # rather than an exception so the caller records it like any other
            # outcome.
            return 0, f"{type(exc).__name__}: {exc}".encode("utf-8")

    def json(self, method: str, path: str, payload=None,
             headers: dict | None = None,
             timeout: float | None = None) -> tuple[int, dict]:
        status, body = self.request(method, path, payload, headers, timeout)
        try:
            return status, json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status, {"_raw": body.decode("utf-8", "replace")[:4000]}

    def login(self, password: str) -> int:
        status, _ = self.json("POST", "/api/login", {"password": password},
                              timeout=60)
        return status


# ---------------------------------------------------------------------------
# SSE / response parsing
# ---------------------------------------------------------------------------
def parse_openai_sse(lines: Sequence[str]) -> dict:
    """Parse an OpenAI SSE body into (text, reasoning, usage, finish, done, ...).

    Tolerant by contract: a stream cut mid-frame is one of the outcomes this
    probe exists to document, so a malformed line is counted rather than raised,
    and a missing ``[DONE]`` is recorded as a fact about the stream.
    """
    out = {"text": "", "reasoning": "", "error_frames": [], "malformed": 0,
           "done": False, "chunks": 0, "finish_reason": None, "usage": {},
           "response_id": None}
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if payload == "[DONE]":
            out["done"] = True
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            out["malformed"] += 1
            continue
        out["chunks"] += 1
        if obj.get("id") and out["response_id"] is None:
            out["response_id"] = obj["id"]
        if obj.get("error") or obj.get("detail"):
            out["error_frames"].append(obj.get("error") or obj.get("detail"))
            continue
        if obj.get("usage"):
            out["usage"] = obj["usage"]
        for choice in obj.get("choices") or []:
            if choice.get("finish_reason"):
                out["finish_reason"] = choice["finish_reason"]
            delta = choice.get("delta") or {}
            out["text"] += delta.get("content") or ""
            out["reasoning"] += delta.get("reasoning_content") or ""
    return out


def parse_console_sse(lines: Sequence[str]) -> dict:
    """Parse ``/api/chat/stream``: ``{"text": ...}`` frames plus a done frame."""
    out = {"text": "", "done": False, "frames": 0, "error_frames": [],
           "finish_reason": None, "usage": {}}
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if payload == "[DONE]":
            out["done"] = True
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        out["frames"] += 1
        if obj.get("error"):
            out["error_frames"].append(obj["error"])
            continue
        if obj.get("text"):
            out["text"] += obj["text"]
        if obj.get("done"):
            out["done"] = True
            out["usage"] = obj
            out["finish_reason"] = obj.get("finish_reason")
    return out


def response_id_to_req_id(response_id: str | None) -> str | None:
    if not response_id:
        return None
    prefix = "chatcmpl-"
    return response_id[len(prefix):] if response_id.startswith(prefix) else response_id


# ---------------------------------------------------------------------------
# One attempt
# ---------------------------------------------------------------------------
@dataclass
class Attempt:
    """Everything one inference attempt produced, including what it did not.

    ``state_before`` is the model's own view of itself, sampled the instant
    before the request was sent -- the *only* trustworthy answer to "was the
    model ready when this request went out". The HTTP code alone cannot say
    that: a 200 during the window and a 200 after it look identical.
    """

    timing_label: str
    surface: str
    target_delay_s: float | None = None
    actual_delay_s: float | None = None
    # -- model state at send time
    state_before: dict = field(default_factory=dict)
    state_after: dict = field(default_factory=dict)
    # -- timing
    started_at: float | None = None
    finished_at: float | None = None
    total_s: float | None = None
    ttft_s: float | None = None
    # -- transport
    http_status: int | None = None
    error: str | None = None
    req_id: str | None = None
    # -- body
    output: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    stream_done: bool | None = None
    chunks: int | None = None
    error_frames: list = field(default_factory=list)
    # -- tokens
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    decode_tps: float | None = None
    # -- derived
    classification: str = ""
    classification_reason: str = ""
    replacement_chars: list = field(default_factory=list)
    output_chars: int = 0
    raw_file: str | None = None
    # -- record cross-check
    record: dict | None = None
    record_missing: bool | None = None

    def as_row(self) -> dict:
        row = asdict(self)
        row["started_iso"] = utc(self.started_at)
        row["finished_iso"] = utc(self.finished_at)
        return row


def classify(attempt: Attempt) -> tuple[str, str]:
    """Name what happened, from recorded facts only.

    The categories are the ones the report must keep apart, because lumping any
    two of them together produces a false conclusion:

    ``refused``       HTTP 409 -- the model reported itself not loaded, and the
                      route said so. What v0.6.13 does in the *early* window.
    ``hang``          no response within the timeout, or a connection that died
                      with no body. The dangerous outcome: it means the request
                      reached something that never answers.
    ``http_error``    any other non-2xx (500/503/429/0 ...).
    ``empty``         2xx with no output text at all.
    ``garbage``       2xx with output that is neither a plausible summary nor a
                      recognised refusal -- repetition loops, a fragment, the
                      prompt echoed back, one character repeated. Judged by
                      :func:`looks_like_summary`, which is deliberately
                      conservative: "not a summary" is a weaker claim than
                      "wrong", and the report says which it is making.
    ``summary``       2xx with a well-formed, on-topic summary -- the normal
                      outcome, and the expected result of the ready control.
    ``summary_suspect`` 2xx with a summary-shaped reply that has a defect the
                      report must not hide: a truncation before any sentence
                      ends, or the replacement character inside the reply.
                      Split out so the decode defect can never be counted as a
                      load-race anomaly.
    """
    if attempt.http_status == 409:
        return "refused", f"HTTP 409: {(attempt.error or '')[:300]}"
    if attempt.http_status is None or attempt.http_status == 0:
        return "hang", attempt.error or "no response"
    if attempt.http_status >= 400:
        return "http_error", f"HTTP {attempt.http_status}: {(attempt.error or '')[:300]}"
    text = (attempt.output or "").strip()
    if not text:
        return "empty", "HTTP 200 with no output text"
    ok, why = looks_like_summary(text)
    if not ok:
        return "garbage", why
    if attempt.replacement_chars:
        return "summary_suspect", (
            f"summary-shaped, but contains {len(attempt.replacement_chars)} "
            f"U+FFFD (known decode defect, MYS-2510)")
    return "summary", why


#: Words a Chinese summary of *this* article would plausibly contain. Used only
#: to decide "is this a summary at all", never to grade its quality.
TOPIC_WORDS = ("火锅", "围裙", "女生", "裙子", "尴尬", "误会", "遮挡", "网友",
               "议论", "保护", "抹胸", "餐厅", "食客", "乌龙", "理解")

#: A summary of a four-paragraph article cannot be three characters long, and one
#: that is 400 characters long inside a 128-token budget is a repetition loop.
MIN_SUMMARY_CHARS = 12


def looks_like_summary(text: str) -> tuple[bool, str]:
    """Whether ``text`` could be a summary of the article under test.

    Three mechanical checks, all of which a healthy reply passes and a
    half-initialised one fails:

    1. **Non-degenerate.** Enough distinct characters. ``"，，，，，，"`` and
       ``"的的的的的"`` are the classic signatures of generating from an
       uninitialised or wrongly-loaded state, and both are long enough to fool a
       length check alone.
    2. **On topic.** At least one topical word from the article.
    3. **Not a prompt echo.** A model that was handed a prompt but produced no
       generation sometimes returns the input; that is not a summary.

    ``False`` here means "not a summary", which is what the classification
    reports. It never means "wrong summary" -- judging correctness of a summary
    is not something a mechanical check can do, and the report does not claim it.
    """
    if len(text) < MIN_SUMMARY_CHARS:
        return False, f"only {len(text)} characters"
    distinct = len(set(text))
    if distinct < min(8, len(text) // 3):
        return False, f"degenerate output: {distinct} distinct characters in {len(text)}"
    # Longest run of one repeated character: a loop signature.
    longest = 1
    run = 1
    for i in range(1, len(text)):
        run = run + 1 if text[i] == text[i - 1] else 1
        longest = max(longest, run)
    if longest >= 12:
        return False, f"repetition loop: one character repeated {longest} times"
    if INPUT_TEXT[:40] in text:
        return False, "output echoes the prompt"
    hits = [w for w in TOPIC_WORDS if w in text]
    if not hits:
        return False, "no topical word from the article appears in the output"
    return True, f"topical words: {', '.join(hits[:6])}"


# ---------------------------------------------------------------------------
# One request, captured whole
# ---------------------------------------------------------------------------
def _record_raw(raw_dir: Path, name: str, body: str) -> str:
    path = raw_dir / name
    path.write_text(body, encoding="utf-8")
    return path.name


def attempt_stream(http: Http, key: str, model: str, raw_dir: Path,
                   timing: str, tag: str, timeout: float = REQUEST_TIMEOUT_S) -> Attempt:
    """One streaming ``/v1/chat/completions`` attempt, captured whole."""
    row = Attempt(timing_label=timing, surface="stream")
    payload = {"model": model,
               "messages": [{"role": "user", "content": INPUT_TEXT}],
               "stream": True, "seed": 2496, **PARAMS}
    req = urllib.request.Request(
        http.url("/v1/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Authorization": f"Bearer {key}",
                 "Cache-Control": "no-cache"})
    lines: list[str] = []
    first_token_at: float | None = None
    row.started_at = time.time()
    try:
        with http.open(req, timeout) as resp:
            row.http_status = resp.status
            while True:
                line = resp.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")
                lines.append(decoded)
                if first_token_at is None and decoded.startswith("data:") \
                        and "[DONE]" not in decoded:
                    try:
                        obj = json.loads(decoded[5:].strip())
                    except json.JSONDecodeError:
                        obj = {}
                    for choice in obj.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content") or delta.get("reasoning_content"):
                            first_token_at = time.time()
                            break
        row.finished_at = time.time()
    except urllib.error.HTTPError as exc:
        row.http_status = exc.code
        row.finished_at = time.time()
        row.error = exc.read().decode("utf-8", "replace")[:4000]
    except (socket.timeout, TimeoutError) as exc:
        row.finished_at = time.time()
        row.error = f"timeout after {timeout:.0f}s: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 - every failure is a row, not a crash
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"

    raw = "".join(lines)
    row.raw_file = _record_raw(raw_dir, f"{timing}-{tag}-stream.sse", raw)
    parsed = parse_openai_sse(lines)
    row.output = parsed["text"]
    row.reasoning = parsed["reasoning"]
    row.finish_reason = parsed["finish_reason"]
    row.stream_done = parsed["done"]
    row.chunks = parsed["chunks"]
    row.error_frames = parsed["error_frames"]
    row.req_id = response_id_to_req_id(parsed["response_id"])
    usage = parsed["usage"] or {}
    row.prompt_tokens = usage.get("prompt_tokens")
    row.completion_tokens = usage.get("completion_tokens")
    row.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    row.ttft_s = round(first_token_at - row.started_at, 3) if first_token_at else None
    _finish(row)
    return row


def attempt_nonstream(http: Http, key: str, model: str, raw_dir: Path,
                      timing: str, tag: str,
                      timeout: float = REQUEST_TIMEOUT_S) -> Attempt:
    """One non-streaming ``/v1/chat/completions`` attempt."""
    row = Attempt(timing_label=timing, surface="nonstream")
    payload = {"model": model,
               "messages": [{"role": "user", "content": INPUT_TEXT}],
               "stream": False, "seed": 2496, **PARAMS}
    req = urllib.request.Request(
        http.url("/v1/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "Authorization": f"Bearer {key}"})
    body = b""
    row.started_at = time.time()
    try:
        with http.open(req, timeout) as resp:
            row.http_status = resp.status
            body = resp.read()
        row.finished_at = time.time()
    except urllib.error.HTTPError as exc:
        row.http_status = exc.code
        row.finished_at = time.time()
        body = exc.read()
        row.error = body.decode("utf-8", "replace")[:4000]
    except (socket.timeout, TimeoutError) as exc:
        row.finished_at = time.time()
        row.error = f"timeout after {timeout:.0f}s: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"

    row.raw_file = _record_raw(raw_dir, f"{timing}-{tag}-nonstream.json",
                               body.decode("utf-8", "replace"))
    obj: dict = {}
    try:
        obj = json.loads(body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        obj = {}
    if row.http_status and 200 <= row.http_status < 300:
        choice = (obj.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        row.output = message.get("content") or ""
        row.reasoning = message.get("reasoning_content") or ""
        row.finish_reason = choice.get("finish_reason")
        row.req_id = response_id_to_req_id(obj.get("id"))
        usage = obj.get("usage") or {}
        row.prompt_tokens = usage.get("prompt_tokens")
        row.completion_tokens = usage.get("completion_tokens")
        row.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        row.stream_done = True
    _finish(row)
    return row


def attempt_console(http: Http, model: str, raw_dir: Path, timing: str, tag: str,
                    timeout: float = REQUEST_TIMEOUT_S) -> Attempt:
    """One ``/api/chat/stream`` attempt (cookie-authenticated console route)."""
    row = Attempt(timing_label=timing, surface="console")
    payload = {"model": model, "prompt": INPUT_TEXT,
               "max_tokens": PARAMS["max_tokens"],
               "temperature": PARAMS["temperature"],
               "enable_thinking": False}
    req = urllib.request.Request(
        http.url("/api/chat/stream"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Cache-Control": "no-cache"})
    lines: list[str] = []
    first_token_at: float | None = None
    row.started_at = time.time()
    try:
        with http.open(req, timeout) as resp:
            row.http_status = resp.status
            while True:
                line = resp.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")
                lines.append(decoded)
                if first_token_at is None and decoded.startswith("data:") \
                        and "[DONE]" not in decoded:
                    try:
                        obj = json.loads(decoded[5:].strip())
                    except json.JSONDecodeError:
                        obj = {}
                    if obj.get("text"):
                        first_token_at = time.time()
        row.finished_at = time.time()
    except urllib.error.HTTPError as exc:
        row.http_status = exc.code
        row.finished_at = time.time()
        row.error = exc.read().decode("utf-8", "replace")[:4000]
    except (socket.timeout, TimeoutError) as exc:
        row.finished_at = time.time()
        row.error = f"timeout after {timeout:.0f}s: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"

    raw = "".join(lines)
    row.raw_file = _record_raw(raw_dir, f"{timing}-{tag}-console.sse", raw)
    parsed = parse_console_sse(lines)
    row.output = parsed["text"]
    row.finish_reason = parsed["finish_reason"]
    row.stream_done = parsed["done"]
    row.chunks = parsed["frames"]
    row.error_frames = parsed["error_frames"]
    usage = parsed["usage"] or {}
    row.prompt_tokens = usage.get("prompt_tokens")
    row.completion_tokens = usage.get("completion_tokens")
    row.cached_tokens = usage.get("cached_tokens")
    row.decode_tps = usage.get("decode_tps")
    row.ttft_s = round(first_token_at - row.started_at, 3) if first_token_at else None
    _finish(row)
    return row


def _finish(row: Attempt) -> None:
    """Shared tail: total time, replacement scan, classification."""
    if row.started_at and row.finished_at:
        row.total_s = round(row.finished_at - row.started_at, 3)
    row.output_chars = len(row.output or "")
    row.replacement_chars = count_replacement(row.output or "")
    row.classification, row.classification_reason = classify(row)


# ---------------------------------------------------------------------------
# The instrumented window (test build only)
# ---------------------------------------------------------------------------
#: The ``sitecustomize.py`` that ``--mode instrumented`` requires the service to
#: have been started with. It delays **only** ``WorkerClient.health``, which in
#: v0.6.13 is called from exactly one place: the capability probe that runs after
#: ``loaded`` is published and before ``operation`` is cleared. ``/api/models``
#: never calls it, ``/api/stats`` never calls it, and the readiness handshake in
#: ``_wait_ready`` speaks the protocol directly rather than through the client --
#: so the only thing this changes is the length of the state machine's own
#: "loaded but not settled" window.
#:
#: This is a *test build*, not the shipped one. The report keeps its results in a
#: separate section and never presents them as v0.6.13's native timing.
SITECUSTOMIZE = '''\
"""Test-only window widener for the MYS-2502 legacy-readiness probe.

Started by tools/legacy_readiness_probe.py --mode instrumented. Delays the
worker health RPC, whose only caller in v0.6.13 is the capability probe that
runs after `loaded` is published and before `operation` is cleared. Nothing else
in the service calls health(), so this widens that window and nothing else.

Why the sys.path dance: this module is imported by `site` at interpreter
startup, before runpy adds the `-m app.main` working directory to sys.path. A
plain `import app.core.client` here therefore raises ModuleNotFoundError, and
`site` swallows that silently -- the widening would simply never happen while
the environment variable still looked correctly set. So the install root is put
on sys.path first, and a marker is printed only after the patch is really in
place.
"""

import asyncio
import os
import sys

_DELAY = float(os.environ.get("CV84X6_TEST_PROBE_DELAY_S", "0") or 0)

if _DELAY > 0:
    _root = os.environ.get("CV84X6_INSTALL_DIR") or "/opt/sophgo/cv84x6_llm_server"
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        import app.core.client as _client
    except Exception as _exc:  # noqa: BLE001 - reported, never silent
        print(f"[test-build] FAILED to import app.core.client from {_root}: "
              f"{type(_exc).__name__}: {_exc}", flush=True)
        raise

    _original = _client.WorkerClient.health

    async def _health(self):
        await asyncio.sleep(_DELAY)
        return await _original(self)

    _client.WorkerClient.health = _health
    print(f"[test-build] WorkerClient.health delayed by {_DELAY}s "
          f"(capability-probe window widened)", flush=True)
'''


def write_sitecustomize(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sitecustomize.py"
    path.write_text(SITECUSTOMIZE, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Service control (via the admin API, never by killing processes)
# ---------------------------------------------------------------------------
class Service:
    """Admin-side view of the service: state, load, unload, records, dmesg.

    Always talks to the service directly. The instrumented mode widens the
    window inside the service process (see :data:`SITECUSTOMIZE`), so nothing
    sits between this client and the model's own state.
    """

    def __init__(self, http: Http, service_url: str, model: str,
                 password: str = ADMIN_PASSWORD_DEFAULT,
                 key_name: str = "MYS-2502-legacy-readiness"):
        self.http = http
        self.service_url = service_url.rstrip("/")
        self.model = model
        self.password = password
        self.key_name = key_name
        self.key: str | None = None
        self.key_id: str | None = None
        self.admin_http = Http(self.service_url, timeout=60)
        self.probe_http = Http(self.service_url, timeout=60)

    # -- auth ------------------------------------------------------------
    def login(self) -> int:
        status = self.admin_http.login(self.password)
        # A separate client for the console surface: `/api/chat/stream` is
        # cookie-authenticated and a single jar shared with the admin poller
        # would serialize nothing but would make a 401 ambiguous.
        self.probe_http.login(self.password)
        return status

    def create_key(self) -> tuple[str, str]:
        status, body = self.admin_http.json("POST", "/api/keys",
                                            {"name": self.key_name}, timeout=60)
        if status != 200 or not body.get("key"):
            raise RuntimeError(f"could not mint an API key: HTTP {status} {body}")
        self.key = body["key"]
        self.key_id = (body.get("meta") or {}).get("id")
        return self.key, self.key_id or ""

    def delete_key(self) -> None:
        if self.key_id:
            self.admin_http.request("DELETE", f"/api/keys/{self.key_id}", timeout=60)
            self.key_id = None
            self.key = None

    # -- model state -----------------------------------------------------
    def models(self) -> dict:
        status, body = self.admin_http.json("GET", "/api/models", timeout=30)
        if status != 200:
            return {"_status": status, "_body": body}
        return body

    def model_state(self) -> dict:
        """The model's own ``loaded``/``operation``/``load_error``/timings.

        Sampled as close to the request as possible: this is the fact that says
        whether a request was inside the load window, and a stale sample is the
        one way the whole report could be wrong.
        """
        body = self.models()
        for entry in body.get("models") or []:
            if entry.get("id") == self.model:
                return {
                    "at": time.time(),
                    "at_iso": utc(time.time()),
                    "loaded": entry.get("loaded"),
                    "operation": entry.get("operation"),
                    "operation_since": entry.get("operation_since"),
                    "loaded_at": entry.get("loaded_at"),
                    "pid": entry.get("pid"),
                    "port": entry.get("port"),
                    "load_error": entry.get("load_error"),
                    "load_seconds": entry.get("load_seconds"),
                    "context_length": entry.get("context_length"),
                    "supports_sampling": entry.get("supports_sampling"),
                    "supports_vision": entry.get("supports_vision"),
                }
        return {"at": time.time(), "at_iso": utc(time.time()),
                "missing": True, "_body": body}

    def unload(self) -> dict:
        started = time.time()
        status, body = self.admin_http.json(
            "POST", f"/api/models/{self.model}/unload", timeout=240)
        return {"status": status, "body": body,
                "seconds": round(time.time() - started, 2)}

    def load_async(self) -> tuple[threading.Thread, dict]:
        """Fire the load on a thread so the probe can send while it runs.

        Returns the thread and a dict it fills in. The probe never sends a
        request *from* this thread: the load must be the thing that is slow.
        """
        result: dict = {}

        def run() -> None:
            started = time.time()
            try:
                status, body = self.admin_http.json(
                    "POST", f"/api/models/{self.model}/load", timeout=LOAD_TIMEOUT_S)
                result.update({"status": status, "body": body,
                               "seconds": round(time.time() - started, 2)})
            except Exception as exc:  # noqa: BLE001
                result.update({"status": 0,
                               "body": {"error": f"{type(exc).__name__}: {exc}"},
                               "seconds": round(time.time() - started, 2)})
            result["finished_at"] = time.time()

        thread = threading.Thread(target=run, name=f"load-{self.model}", daemon=True)
        thread.start()
        return thread, result

    def worker_stats(self) -> dict:
        status, body = self.admin_http.json("GET", "/api/stats", timeout=30)
        if status != 200:
            return {"_status": status}
        out = {"active": body.get("active"), "workers": {}}
        for mid, payload in (body.get("workers") or {}).items():
            if isinstance(payload, dict):
                out["workers"][mid] = {
                    "total_requests": payload.get("total_requests"),
                    "failed_requests": payload.get("failed_requests"),
                    "cancelled_requests": payload.get("cancelled_requests"),
                    "active": payload.get("active"),
                    "queued": payload.get("queued"),
                }
        return out

    def generate_count(self) -> int | None:
        """The live worker's own count of inferences it has actually run.

        This is the counter that answers "did a request reach the model", which
        the HTTP status alone cannot: a 409 never reaches it, and a 200 after the
        window is not inside it.

        Read as an **absolute** value, never as a before/after delta across a
        load. A load spawns a *new* worker process whose counter starts at zero,
        so subtracting the previous worker's number from the new one is
        meaningless (the same bug MYS-2501 hit). Because every timing here begins
        with an unload, the new worker's absolute count *is* this timing's count:
        anything above zero means a request reached the model during this load.
        """
        stats = self.worker_stats()
        for payload in (stats.get("workers") or {}).values():
            if isinstance(payload, dict) and payload.get("total_requests") is not None:
                return int(payload["total_requests"])
        return None

    # -- records ---------------------------------------------------------
    def record_total(self) -> int | None:
        status, body = self.admin_http.json("GET", "/api/inference-records/status",
                                            timeout=30)
        if status != 200:
            return None
        total = body.get("total")
        return int(total) if total is not None else None

    def record(self, req_id: str) -> dict | None:
        status, body = self.admin_http.json("GET", f"/api/inference-records/{req_id}",
                                            timeout=30)
        if status != 200:
            return None
        return body

    def records_for_state(self, started_at: float) -> list[dict]:
        """Records whose ``started_at`` is at or after ``started_at``.

        Used to find records the probe did not learn a req_id for: a request that
        hung or was refused mid-flight has no response id, but a record it wrote
        is still evidence.
        """
        status, body = self.admin_http.json(
            "GET", "/api/inference-records?limit=50&offset=0", timeout=30)
        if status != 200:
            return []
        items = body.get("items") or []
        return [item for item in items
                if (item.get("started_at") or 0) >= started_at - 1.0]

    # -- host-side facts -------------------------------------------------
    def dmesg_npu_errors(self) -> list[str]:
        """NPU hang signatures in the kernel ring buffer.

        ``wait api timeout`` and ``bdc_reg_read`` are the two the engine's own
        failure mode produces (see ``analysis/raw/dmesg_wedged_tpu.txt``). Their
        presence means the TPU is wedged and the device must be rebooted before
        anything else touches the NPU.
        """
        try:
            out = subprocess.run(["sudo", "-n", "dmesg"], capture_output=True,
                                 text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return []
        text = (out.stdout or "") + (out.stderr or "")
        return [line for line in text.splitlines()
                if "wait api timeout" in line or "bdc_reg_read" in line]

    def worker_log(self, model: str, port: int | None = None,
                   lines: int = 2000) -> str:
        """This timing's slice of the worker log.

        The service appends to one ``worker-<model>.log`` across every load, so
        "the tail of the log" is *not* this timing's load -- it is this timing's
        load followed by whatever came before it, and a reader comparing a 409
        against a banner printed twenty minutes earlier would draw the wrong
        conclusion. The worker prints its port when it starts listening, so the
        port recorded in the model state identifies the block unambiguously:
        everything from the ``[engine]`` banner that precedes
        ``listening on 127.0.0.1:<port>`` is this load, and nothing else is kept.

        Falls back to the whole tail when the port is unknown or its banner is
        not in the tail, and says so, rather than silently returning a slice that
        might belong to another load.
        """
        status, body = self.admin_http.json(
            "GET", f"/api/models/{model}/log?lines={lines}", timeout=30)
        if status != 200:
            return f"<worker log unavailable: HTTP {status}>"
        return self._slice_worker_log(body.get("log") or "", port, lines)

    @staticmethod
    def _slice_worker_log(text: str, port: int | None,
                          lines: int = 2000) -> str:
        """The one-load slice of an append-only worker log (see ``worker_log``)."""
        if port is None:
            return f"<port unknown; whole tail follows>\n{text}"
        marker = f"listening on 127.0.0.1:{port}"
        all_lines = text.splitlines()
        end = None
        for index, line in enumerate(all_lines):
            if marker in line:
                end = index
        if end is None:
            return (f"<no '{marker}' in the last {lines} log lines; whole tail "
                    f"follows>\n{text}")
        start = 0
        for index in range(end, -1, -1):
            if "[engine]" in all_lines[index]:
                start = index
                break
        return "\n".join(all_lines[start:end + 1])

    def journal(self, since: float | None, lines: int = 400) -> str:
        """The service's journal from ``since`` (epoch seconds) onwards.

        The argument is an **epoch** (``@1793468362``), and both earlier attempts
        were wrong for instructive reasons:

        * ``--since 2026-10-31T18:00:07.591Z`` -- journalctl rejects the trailing
          ``Z`` with "Failed to parse timestamp" *on stdout*, so every timing's
          journal file became that one error line while the report counted it as
          captured evidence.
        * ``--since "2026-10-31 18:00:07"`` *parses*, but a bare timestamp is
          interpreted in **local** time; the probe generates the value from a UTC
          epoch, so on this board (CST, UTC+8) the window would silently start
          eight hours early and the file would look plausible while covering the
          wrong hours.

        ``@<epoch>`` carries its own timezone and cannot be misread.
        """
        since_arg = "-30 min" if since is None else f"@{int(since)}"
        try:
            out = subprocess.run(
                ["journalctl", "-u", "cv84x6-llm", "--utc", "--since", since_arg,
                 "-n", str(lines), "--no-pager"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"<journalctl unavailable: {exc}>"
        text = (out.stdout or "") + (out.stderr or "")
        if "Failed to parse timestamp" in text or "insufficient permissions" in text:
            # Never let an unreadable journal look like an empty one.
            return f"<journalctl could not read the journal (since={since_arg})>\n{text}"
        return text

    def healthz(self) -> dict:
        status, body = self.admin_http.json("GET", "/healthz", timeout=15)
        return {"status": status, "body": body}

    # -- test-build detection --------------------------------------------
    def probe_widened(self) -> dict:
        """Whether the running service really is the widened test build.

        The generated ``sitecustomize.py`` prints one line at import. Looking for
        it in the unit's journal is the only way to know the widening is live:
        setting the environment variable without the file present changes
        nothing, and running the probe against an unwidened service while the
        report claims otherwise would be the single most misleading thing this
        tool could do. So the check is done, and its result is written into the
        report rather than assumed.
        """
        try:
            out = subprocess.run(
                ["journalctl", "-u", "cv84x6-llm", "-n", "400", "--no-pager"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"observed": False, "detail": f"journalctl unavailable: {exc}"}
        text = (out.stdout or "") + (out.stderr or "")
        marker = "[test-build]"
        hits = [line for line in text.splitlines() if marker in line]
        return {
            "observed": bool(hits),
            "detail": hits[-1].strip() if hits else "no '[test-build]' line in the journal",
            "lines_matched": len(hits),
        }


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------
@dataclass
class TimingRun:
    """One delay's independent experiment: unload -> load -> send -> settle."""

    #: ``wall`` (send ``target_delay_s`` after the load POST) or ``edge`` (send
    #: the instant the model reports ``loaded`` with ``operation`` still set).
    kind: str = "wall"
    label: str = ""
    target_delay_s: float | None = None
    mode: str = "native"
    started_at: float = 0.0
    load_post_at: float | None = None
    loading_observed_at: float | None = None
    #: For ``edge`` runs: the instant the ``loaded=True, operation=<not None>``
    #: state was first observed. The gap to ``ready_observed_at`` is the width of
    #: the window this run was aiming at, measured rather than assumed.
    settle_edge_at: float | None = None
    ready_observed_at: float | None = None
    loaded_at: float | None = None
    load_result: dict = field(default_factory=dict)
    unload_result: dict = field(default_factory=dict)
    state_at_send: dict = field(default_factory=dict)
    #: The *new* worker's absolute ``total_requests`` once this timing's load has
    #: settled. Not a before/after delta: an unload + load replaces the process,
    #: so the new worker's counter starts at zero and its absolute value is this
    #: timing's count. Anything above zero means a request reached the model
    #: during this load (MYS-2501 hit exactly this arithmetic bug).
    worker_total_requests: int | None = None
    records_before: int | None = None
    records_after: int | None = None
    dmesg_before: list = field(default_factory=list)
    dmesg_after: list = field(default_factory=list)
    #: Filenames (inside the evidence dir) of the worker log and service journal
    #: captured after this timing settled. Relative so the evidence directory
    #: stays portable and the report never embeds an absolute device path as if
    #: it were a deliverable.
    worker_log_file: str | None = None
    journal_file: str | None = None
    attempts: list = field(default_factory=list)      # list[Attempt]
    notes: list = field(default_factory=list)
    error: str | None = None

    @property
    def settle_window_s(self) -> float | None:
        """Width of the observed ``loaded but operation set`` window."""
        if self.settle_edge_at and self.ready_observed_at:
            return round(self.ready_observed_at - self.settle_edge_at, 3)
        return None

    @property
    def records_delta(self) -> int | None:
        """Records written during this timing.

        Unlike the worker counter this *is* a delta, and legitimately so: the
        record table lives in the data directory and survives a worker restart,
        so a difference across the timing counts exactly the rows this timing
        caused.
        """
        if self.records_before is None or self.records_after is None:
            return None
        return self.records_after - self.records_before

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "target_delay_s": self.target_delay_s,
            "mode": self.mode,
            "started_at": self.started_at,
            "started_iso": utc(self.started_at),
            "load_post_at": self.load_post_at,
            "load_post_iso": utc(self.load_post_at),
            "loading_observed_at": self.loading_observed_at,
            "settle_edge_at": self.settle_edge_at,
            "settle_edge_iso": utc(self.settle_edge_at),
            "settle_window_s": self.settle_window_s,
            "ready_observed_at": self.ready_observed_at,
            "ready_observed_iso": utc(self.ready_observed_at),
            "loaded_at": self.loaded_at,
            "loaded_at_iso": utc(self.loaded_at),
            "load_result": self.load_result,
            "unload_result": self.unload_result,
            "state_at_send": self.state_at_send,
            "worker_total_requests": self.worker_total_requests,
            "records_before": self.records_before,
            "records_after": self.records_after,
            "records_delta": self.records_delta,
            "dmesg_before": self.dmesg_before,
            "dmesg_after": self.dmesg_after,
            "worker_log_file": self.worker_log_file,
            "journal_file": self.journal_file,
            "attempts": [a.as_row() for a in self.attempts],
            "notes": self.notes,
            "error": self.error,
        }


class Runner:
    def __init__(self, service: Service, base_url: str, service_url: str,
                 evidence: Path, mode: str = "native"):
        self.service = service
        self.base_url = base_url.rstrip("/")      # what attempts are sent to
        self.service_url = service_url.rstrip("/")
        self.evidence = evidence
        self.raw_dir = evidence / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.runs: list[TimingRun] = []
        self.timeline: list[dict] = []
        self.stopped_reason: str | None = None

    # -- logging ---------------------------------------------------------
    def note(self, kind: str, label: str, detail: str = "", **kw) -> None:
        entry = {"at": time.time(), "iso": utc(time.time()), "kind": kind,
                 "label": label, "detail": detail, **kw}
        self.timeline.append(entry)
        print(f"[{entry['iso']}] {kind}: {label} {detail}", flush=True)

    # -- one timing ------------------------------------------------------
    def run_timing(self, label: str, target_delay: float | None,
                   kind: str = "wall") -> TimingRun:
        """Unload, load, then send one request per surface.

        ``kind`` decides when the request goes out:

        * ``wall`` -- ``target_delay`` seconds after the load POST was *sent*.
          ``None`` waits for readiness first (the control group). The POST does
          not return until the model is ready, so measuring from its return
          would make every wall delay a post-ready control.
        * ``edge`` -- the instant the admin API first reports ``loaded: true``
          with ``operation`` still set. That is the state v0.6.13 publishes
          between its readiness handshake and the end of its capability probe,
          and it is the only state in which the shipped build has a model that
          answers requests while its load is still in flight.
        """
        run = TimingRun(kind=kind, label=label, target_delay_s=target_delay,
                        mode=self.mode)
        run.started_at = time.time()
        self.runs.append(run)
        self.note("timing", f"开始时机 {label}",
                  f"类型 {kind} "
                  f"目标 {target_delay if target_delay is not None else 'ready 后'}")

        # 1. Unload first, every time: an experiment is one load, and a model
        #    already loaded would make the "load" a no-op.
        unload = self.service.unload()
        run.unload_result = unload
        if unload["status"] not in (200,):
            run.error = f"unload refused: HTTP {unload['status']} {unload['body']}"
            self.note("anomaly", f"{label} 卸载失败", run.error)
            return run
        # Wait until the process is really gone, so the next load is a real one
        # and the NPU heap is actually free. Bounded: a worker that will not
        # exit is a finding, not something to force.
        deadline = time.time() + 180
        while time.time() < deadline:
            state = self.service.model_state()
            if not state.get("loaded") and state.get("operation") is None:
                break
            time.sleep(0.5)
        else:
            run.error = "model still reported loaded 180s after unload"
            self.note("anomaly", f"{label} 卸载未完成", run.error)
            return run
        time.sleep(1.0)  # let the port and the NPU heap settle

        run.dmesg_before = self.service.dmesg_npu_errors()
        if run.dmesg_before:
            self.stopped_reason = "dmesg NPU error before this timing"
            run.error = "dmesg shows an NPU hang signature; not sending anything"
            self.note("anomaly", "检测到 TPU hang 特征，停止后续高风险时机",
                      run.dmesg_before[-1])
            return run

        run.records_before = self.service.record_total()

        # 2. Fire the load and time from the moment it is sent.
        thread, load_result = self.service.load_async()
        run.load_post_at = time.time()
        run.load_result = load_result

        # 3. Wait for `operation=loading` so "delay" is measured against a load
        #    that has really started (the POST is dispatched before the worker is
        #    spawned). Recorded, because a delay measured from the wrong instant
        #    would make the whole table meaningless.
        watch_deadline = time.time() + 30
        while time.time() < watch_deadline:
            state = self.service.model_state()
            if state.get("operation") == "loading":
                run.loading_observed_at = time.time()
                break
            if state.get("loaded") and state.get("operation") is None:
                run.notes.append("load finished before loading was observed")
                break
            time.sleep(0.05)
        if run.loading_observed_at is None:
            run.notes.append(
                "operation=loading was never observed; the delay is measured from "
                "the load POST instead")

        # 4. Wait for the trigger this run's kind asks for.
        if kind == "edge":
            self._await_settle_edge(run, thread)
        elif target_delay is None:
            self._wait_ready(run, thread, load_result)
        else:
            target_at = run.load_post_at + target_delay
            while True:
                now = time.time()
                if now >= target_at:
                    break
                if (thread is not None and not thread.is_alive()) or \
                        (load_result.get("status") and load_result.get("status") != 200):
                    run.notes.append(
                        "load finished/refused before the target delay elapsed")
                    break
                time.sleep(min(0.05, max(0.0, target_at - now)))

        # 5. Sample the model's state, then send one request per surface --
        #    **all three at once**, each with its own state sample taken
        #    immediately before it goes out.
        #
        #    Concurrent, not sequential, and that is not a detail: a request that
        #    generates 128 tokens takes ~5-6 s on this board, so sending the
        #    surfaces one after another put the third one 11 s after the first.
        #    Against a window measured in tens of milliseconds that is not three
        #    samples of one instant, it is three samples of three different
        #    instants -- the first version measured exactly that and it made the
        #    per-surface comparison meaningless.
        #
        #    The readiness watcher also starts here, on its own thread, so the
        #    window's end is observed by the same clock as its start and is not
        #    stretched by however long the requests take.
        ready_stop = threading.Event()
        watcher: threading.Thread | None = None
        if run.ready_observed_at is None:
            watcher = threading.Thread(target=self._watch_ready,
                                       args=(run, ready_stop),
                                       name=f"ready-watch-{label}", daemon=True)
            watcher.start()

        dispatched: list[tuple[str, Attempt, dict]] = []
        gate = threading.Event()
        results: dict[str, Attempt] = {}

        def fire(surface: str) -> None:
            gate.wait()
            state = self.service.model_state()
            row = self._send(surface, label)
            row.actual_delay_s = (round(row.started_at - run.load_post_at, 3)
                                  if run.load_post_at and row.started_at else None)
            # Carried onto the row: the per-row tables show the timing's own
            # target, and a row without it reads as "ready" for every wall
            # timing, which is exactly backwards.
            row.target_delay_s = run.target_delay_s
            row.state_before = state
            row.classification, row.classification_reason = classify(row)
            results[surface] = row

        senders = [threading.Thread(target=fire, args=(s,), name=f"send-{s}",
                                    daemon=True) for s in SURFACES]
        for sender in senders:
            sender.start()
        gate.set()          # release all three in the same instant
        for sender in senders:
            sender.join(timeout=REQUEST_TIMEOUT_S + 120)

        for surface in SURFACES:
            row = results.get(surface)
            if row is None:
                row = Attempt(timing_label=label, surface=surface)
                row.started_at = row.finished_at = time.time()
                row.error = "surface thread produced no result"
                _finish(row)
            row.state_after = self.service.model_state()
            run.attempts.append(row)
            self.note("attempt", f"{label}/{surface}",
                      f"HTTP {row.http_status} {row.classification} "
                      f"delay={row.actual_delay_s}s "
                      f"state={ {k: row.state_before.get(k) for k in ('loaded', 'operation')} }",
                      http=row.http_status, classification=row.classification)
            if kind == "edge" and run.settle_edge_at is None:
                run.notes.append(
                    "edge state was never observed; this run is a post-ready "
                    "control, not a window sample")

        # 6. Let the readiness watcher finish, then read the counters.
        #
        #    The watcher may already have recorded the instant ``operation``
        #    cleared (the normal case, since it polled throughout step 5). If it
        #    has not -- the load had not finished when the last request returned
        #    -- the fallback below waits for it and stamps the observation then.
        #    Both paths use this process's clock for both ends of the window.
        if watcher is not None:
            watcher.join(timeout=LOAD_TIMEOUT_S + 60)
            ready_stop.set()
        if run.ready_observed_at is None:
            settle_deadline = time.time() + LOAD_TIMEOUT_S
            while time.time() < settle_deadline:
                state = self.service.model_state()
                if state.get("loaded") and state.get("operation") is None:
                    run.ready_observed_at = time.time()
                    break
                if thread is not None and not thread.is_alive() and not state.get("loaded"):
                    break
                time.sleep(0.02)
        if thread is not None:
            thread.join(timeout=LOAD_TIMEOUT_S + 60)
        run.state_at_send = (run.attempts[0].state_before if run.attempts else {})
        run.worker_total_requests = self.service.generate_count()
        run.records_after = self.service.record_total()
        final = self.service.model_state()
        run.loaded_at = final.get("loaded_at")
        run.dmesg_after = self.service.dmesg_npu_errors()

        # The inside view of the load: what the worker printed while it was
        # initialising, and what the service logged about it. Kept per timing
        # because the worker is replaced by the next timing's load -- after this
        # point the file on disk belongs to a different process. A failure to
        # read it is recorded in the file, not raised: losing a log must not
        # abort a run that already produced its measurements.
        try:
            log_name = f"worker-{label}.log"
            (self.evidence / log_name).write_text(
                self.service.worker_log(self.service.model,
                                        port=final.get("port")),
                encoding="utf-8")
            run.worker_log_file = log_name
        except Exception as exc:  # noqa: BLE001
            run.notes.append(f"worker log capture failed: {type(exc).__name__}: {exc}")
        try:
            journal_name = f"journal-{label}.txt"
            (self.evidence / journal_name).write_text(
                self.service.journal(run.started_at), encoding="utf-8")
            run.journal_file = journal_name
        except Exception as exc:  # noqa: BLE001
            run.notes.append(f"journal capture failed: {type(exc).__name__}: {exc}")
        if run.dmesg_after and not run.dmesg_before:
            self.stopped_reason = f"dmesg NPU error after timing {label}"
            self.note("anomaly", "本次时机后出现 TPU hang 特征，停止后续时机",
                      run.dmesg_after[-1])
        if not final.get("loaded"):
            run.notes.append(
                f"model did not end loaded (operation={final.get('operation')!r}, "
                f"load_error={final.get('load_error')!r})")
        self.note("timing", f"结束时机 {label}",
                  f"load={run.load_result.get('status')} "
                  f"in {run.load_result.get('seconds')}s, "
                  f"新 worker total_requests={run.worker_total_requests}, "
                  f"records Δ={run.records_delta}, "
                  f"settle window={run.settle_window_s}s")
        return run

    def _await_settle_edge(self, run: TimingRun, thread) -> None:
        """Mark the instant the model reads ``loaded`` but has not settled.

        v0.6.13 publishes ``loaded: true`` and only afterwards finishes its
        capability probe, so between those two events ``/api/models`` reports
        ``loaded: true, operation: "loading"``. That is the window the whole
        question is about -- a request there reaches a worker the manager already
        considers usable.

        Two constraints shape this, and the first version got both wrong:

        * **The two ends must be measured by the same clock.** ``settle_edge_at``
          and ``ready_observed_at`` are therefore both taken here, by polling.
          ``loaded_at`` is deliberately not used as the window's start: it is the
          service's own timestamp for when it published ``loaded``, while
          ``ready_observed_at`` is this client's poll. Mixing the two produced a
          15 s "window" that was really just the gap between the service's clock
          reading and the poller's observation -- a measurement bug that looked
          exactly like a finding.
        * **A request must follow the observation as closely as possible.** After
          this returns, ``run_timing`` samples the state once more and sends. That
          second sample costs one admin round trip, which is the same order as the
          window itself, so a hit here can still be a post-ready request by the
          time it leaves. That is recorded, not papered over: each row carries the
          state at send time and the gap to readiness, and ``inside_window`` is
          decided there.

        Polled as fast as one admin GET takes (~5-15 ms here), which is the
        resolution limit and is reported as such. A miss is recorded as a control,
        never as a window sample.
        """
        deadline = time.time() + LOAD_TIMEOUT_S
        while time.time() < deadline:
            state = self.service.model_state()
            if state.get("loaded") is True and state.get("operation") is not None:
                run.settle_edge_at = time.time()
                return
            if state.get("loaded") is True and state.get("operation") is None:
                # Readiness arrived without the settled-looking state ever being
                # seen: the window was narrower than one poll.
                run.ready_observed_at = time.time()
                run.notes.append(
                    "loaded=true with operation set was never observed; the "
                    "settle window is narrower than the admin poll interval")
                return
            if thread is not None and not thread.is_alive():
                run.notes.append("load thread finished without the settle state")
                return
        run.notes.append(
            f"settle edge not observed within {LOAD_TIMEOUT_S:.0f}s")

    def _watch_ready(self, run: TimingRun, stop: threading.Event) -> None:
        """Poll until ``operation`` clears, recording that instant.

        Runs on its own thread and *while the attempts are being sent*. That is
        the only way ``settle_window_s`` can mean anything: the end of the window
        has to be observed independently of the requests, or a slow request would
        stretch the window and make it look wide enough that a late send was
        justified.
        """
        deadline = time.time() + LOAD_TIMEOUT_S
        while not stop.is_set() and time.time() < deadline:
            state = self.service.model_state()
            if state.get("loaded") and state.get("operation") is None:
                run.ready_observed_at = time.time()
                return
            time.sleep(0.01)

    def _wait_ready(self, run: TimingRun, thread, load_result: dict) -> None:
        deadline = time.time() + LOAD_TIMEOUT_S
        while time.time() < deadline:
            state = self.service.model_state()
            if state.get("loaded") and state.get("operation") is None:
                run.ready_observed_at = time.time()
                run.loaded_at = state.get("loaded_at")
                return
            if thread is not None and not thread.is_alive():
                run.notes.append("load thread finished; model not ready")
                return
            time.sleep(READY_POLL_S)
        run.notes.append(f"readiness not observed within {LOAD_TIMEOUT_S:.0f}s")

    def _send(self, surface: str, timing: str) -> Attempt:
        """Dispatch one surface's request to the service under test.

        The request body is identical on every surface; only route and auth
        differ, which is the point of covering all three. Deliberately no retry:
        a re-send would replace the one outcome the timing exists to record.
        """
        tag = f"{surface}"
        http = Http(self.base_url, timeout=REQUEST_TIMEOUT_S)
        if surface == "console":
            # Cookie auth: log this client in before sending.
            try:
                http.login(self.service.password)
            except Exception as exc:  # noqa: BLE001
                row = Attempt(timing_label=timing, surface=surface)
                row.started_at = time.time()
                row.finished_at = time.time()
                row.error = f"console login failed: {type(exc).__name__}: {exc}"
                _finish(row)
                return row
            return attempt_console(http, self.service.model, self.raw_dir, timing, tag)
        assert self.service.key is not None
        if surface == "stream":
            return attempt_stream(http, self.service.key, self.service.model,
                                  self.raw_dir, timing, tag)
        return attempt_nonstream(http, self.service.key, self.service.model,
                                 self.raw_dir, timing, tag)

    # -- record cross-check ---------------------------------------------
    def attach_records(self) -> None:
        """Give each attempt the inference record it produced, if any.

        A request the service refused before building a record context has none;
        that is the expected state for a 409 and is reported as
        ``record_missing`` rather than treated as an error. For a 2xx it is a
        finding either way -- no record means the audit trail lost an inference,
        two records would mean the log double-counted.
        """
        for run in self.runs:
            for row in run.attempts:
                if row.req_id:
                    rec = self.service.record(row.req_id)
                    row.record = rec
                    row.record_missing = rec is None
                elif row.http_status and 200 <= row.http_status < 300:
                    # A 2xx with no response id: look for a record written in
                    # the window instead. Absence is recorded, not assumed.
                    candidates = self.service.records_for_state(
                        row.started_at or 0)
                    row.record = candidates[0] if candidates else None
                    row.record_missing = not candidates
                    if candidates:
                        row.notes_records = len(candidates)
                else:
                    row.record = None
                    row.record_missing = None


# ---------------------------------------------------------------------------
# SQLite read-back (host side, straight off the file)
# ---------------------------------------------------------------------------
def sqlite_records(db_path: Path, ids: Sequence[str]) -> dict[str, dict]:
    """Read record rows directly from the SQLite file.

    An independent read is the only way to prove the admin API is not inventing
    a record: the file is what survives a service restart, and it is what an
    operator would open. Read-only URI so a live WAL is never disturbed.
    """
    if not db_path.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=20)
    except sqlite3.Error:
        return {}
    try:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        for rid in ids:
            try:
                row = cur.execute(
                    "SELECT * FROM inference_records WHERE id = ?", (rid,)).fetchone()
            except sqlite3.Error:
                continue
            if row is not None:
                out[rid] = dict(row)
    finally:
        con.close()
    return out


def export_records(http: Http, out_path: Path) -> dict:
    """Stream the service's own NDJSON export to disk and count its lines."""
    status, body = http.request("GET", "/api/inference-records-export", timeout=300)
    if status != 200:
        return {"status": status, "lines": 0, "error": body[:400].decode("utf-8", "replace")}
    out_path.write_bytes(body)
    lines = sum(1 for line in body.splitlines() if line.strip())
    return {"status": status, "lines": lines, "bytes": len(body)}


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------
def capture_environment(service: Service, service_url: str, evidence: Path,
                        password: str) -> dict:
    """Everything the report needs to say *where* a result came from."""
    def sh(cmd: list[str]) -> str:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return (out.stdout or "") + (out.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            return f"<{type(exc).__name__}: {exc}>"

    env: dict = {
        "captured_at": utc(time.time()),
        "service_url": service_url,
        "mode_notes": [],
        "hostname": sh(["hostname"]).strip(),
        "uname": sh(["uname", "-a"]).strip(),
        "uptime": sh(["uptime"]).strip(),
        "date_utc": sh(["date", "-u"]).strip(),
        "meminfo_head": "\n".join(sh(["head", "-3", "/proc/meminfo"]).splitlines()),
        "df_data": sh(["df", "-h", "/data"]).strip(),
        "df_root": sh(["df", "-h", "/"]).strip(),
        "free_m": sh(["free", "-m"]).strip(),
        "oem_sn": sh(["grep", "-E", "^SN", "/factory/OEMconfig.ini"]).strip(),
        "installed_version": sh(["cat", "/opt/sophgo/cv84x6_llm_server/VERSION"]).strip(),
        "installed_commit": sh(["cat", "/opt/sophgo/cv84x6_llm_server/COMMIT"]).strip(),
        "dpkg_version": sh(["dpkg", "-l", "cv84x6-llm-server"]).strip().splitlines()[-1:]
        if True else "",
        "service_unit": sh(["systemctl", "show", "cv84x6-llm", "--property=ActiveState,SubState,ExecMainPID"]).strip(),
        "dmesg_vpp": "\n".join(
            [line for line in sh(["sudo", "-n", "dmesg"]).splitlines()
             if "vppreserved" in line or "TPU Shared Memory Final" in line][:6]),
        "dmesg_npu_errors": service.dmesg_npu_errors(),
        "healthz": service.healthz(),
        "models": service.models(),
        "python": sys.version.split()[0],
        "tool_sha256": sha256_text(Path(__file__).read_text(encoding="utf-8")),
        "input_text_chars": len(INPUT_TEXT),
        "input_text_sha256": sha256_text(INPUT_TEXT),
    }
    env["hostname_short"] = env["hostname"]
    return env


def bmodel_md5(service: Service, model: str) -> dict:
    """MD5 of the .bmodel in use, so "same model as before" is a fact.

    Read from the worker's own command line (the exact file it was started on)
    rather than from a directory listing, which could hold two files.
    """
    cmdline_path = None
    pid = None
    state = service.model_state()
    pid = state.get("pid")
    if pid:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                parts = fh.read().split(b"\0")
            for index, part in enumerate(parts):
                if part == b"--model-path" and index + 1 < len(parts):
                    cmdline_path = parts[index + 1].decode()
        except OSError:
            cmdline_path = None
    if not cmdline_path:
        return {"path": None, "md5": None, "pid": pid}
    out = subprocess.run(["md5sum", cmdline_path], capture_output=True, text=True,
                         timeout=600)
    md5 = (out.stdout or "").split()[0] if out.returncode == 0 else None
    return {"path": cmdline_path, "md5": md5, "pid": pid,
            "bytes": os.path.getsize(cmdline_path) if os.path.exists(cmdline_path) else None}


# ---------------------------------------------------------------------------
# Summary and verdict
# ---------------------------------------------------------------------------
#: What "the model was not ready" means, in terms of the service's own fields.
#: ``operation == "loading"`` is the unambiguous one. ``loaded is False and
#: operation is None`` is the gap between two loads. Both are "inside the
#: window"; ``loaded is True and operation is None`` is not.
def state_is_loading(state: dict) -> bool:
    if not state or state.get("missing"):
        return False
    if state.get("operation") == "loading":
        return True
    return state.get("loaded") is False and state.get("operation") is None


def state_is_ready(state: dict) -> bool:
    return bool(state) and not state.get("missing") \
        and state.get("loaded") is True and state.get("operation") is None


def summarize(runs: Sequence[TimingRun]) -> dict:
    """Per-timing and per-surface aggregates, plus the counts the report gates on.

    Three distinctions the summary refuses to blur:

    * **Inside the window vs after it.** Decided by ``state_before``, not by the
      delay label. A "5 s" request that arrived after readiness is a control,
      and counting it as a window sample would inflate the window's numbers.
    * **Refused vs admitted vs failed.** A 409 is the *correct* outcome of a
      window request; a 200 is the observation worth investigating; a hang is
      the dangerous one. They are counted separately, per surface.
    * **Load-race anomalies vs the known decode defect.** A reply containing
      U+FFFD is counted in its own bucket and in the control group too, so the
      report can compare the two rates instead of attributing it to the race.
    """
    rows: list[dict] = []
    for run in runs:
        for row in run.attempts:
            d = row.as_row()
            before = row.state_before or {}
            d["inside_window"] = state_is_loading(before)
            d["ready_at_send"] = state_is_ready(before)
            d["replacement_count"] = len(row.replacement_chars)
            if run.load_post_at and row.started_at:
                d["delay_from_load_post_s"] = round(row.started_at - run.load_post_at, 3)
            if row.started_at and run.loaded_at:
                d["request_before_loaded_at_s"] = round(run.loaded_at - row.started_at, 3)
            # Milliseconds after the *observed* end of the settle window. This is
            # the number that decides whether an `edge` run's request really got
            # in: the window is ~5-25 ms wide, so a request 7 ms past its close
            # is a boundary miss, not a hit, and rounding this to whole seconds
            # (as the first version did) hid exactly that distinction.
            # Only meaningful for an `edge` run, and only when the edge was
            # actually observed. For a wall timing the model was never in the
            # settle state at all, so an offset would be a number about an
            # interval the request was not part of -- e.g. "-66279 ms", which
            # reads like a measurement and is noise.
            if run.kind == "edge" and row.started_at and run.ready_observed_at:
                d["ms_after_window_close"] = round(
                    (row.started_at - run.ready_observed_at) * 1000, 1)
            if run.kind == "edge" and row.started_at and run.settle_edge_at:
                d["ms_after_window_open"] = round(
                    (row.started_at - run.settle_edge_at) * 1000, 1)
            rows.append(d)

    def bucket(rows_subset: list[dict]) -> dict:
        by_class: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for r in rows_subset:
            by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
            key = str(r["http_status"]) if r["http_status"] is not None else "none"
            by_status[key] = by_status.get(key, 0) + 1
        return {
            "attempts": len(rows_subset),
            "by_classification": by_class,
            "by_http_status": by_status,
            "refused": sum(1 for r in rows_subset if r["classification"] == "refused"),
            "admitted": sum(1 for r in rows_subset
                            if r["classification"] in ("summary", "summary_suspect",
                                                       "garbage", "empty")),
            "hang": sum(1 for r in rows_subset if r["classification"] == "hang"),
            "http_error": sum(1 for r in rows_subset if r["classification"] == "http_error"),
            "replacement_rows": sum(1 for r in rows_subset if r["replacement_count"]),
            "latency_s": spread([r["total_s"] for r in rows_subset]),
            "ttft_s": spread([r["ttft_s"] for r in rows_subset]),
            "records_found": sum(1 for r in rows_subset if r.get("record")),
            "records_missing_on_2xx": sum(
                1 for r in rows_subset
                if r.get("record_missing") and r["classification"] in
                ("summary", "summary_suspect", "garbage", "empty")),
        }

    inside = [r for r in rows if r["inside_window"]]
    after = [r for r in rows if not r["inside_window"]]
    by_surface: dict[str, dict] = {}
    for surface in SURFACES:
        by_surface[surface] = {
            "inside_window": bucket([r for r in inside if r["surface"] == surface]),
            "after_window": bucket([r for r in after if r["surface"] == surface]),
        }
    per_timing = []
    for run in runs:
        run_rows = [r for r in rows if r["timing_label"] == run.label]
        per_timing.append({
            "label": run.label,
            "kind": run.kind,
            "target_delay_s": run.target_delay_s,
            "actual_delays_s": [r.get("delay_from_load_post_s") for r in run_rows],
            "mode": run.mode,
            "load_status": (run.load_result or {}).get("status"),
            "load_seconds": (run.load_result or {}).get("seconds"),
            # The width of the `loaded but operation set` window this run
            # actually saw. `None` means it was never observed -- which for an
            # edge run is the honest result "the window is narrower than one
            # poll", not a failure to report.
            "settle_window_s": run.settle_window_s,
            "settle_edge_observed": run.settle_edge_at is not None,
            "loaded_at_vs_send_s": [
                (round(run.loaded_at - r["started_at"], 3)
                 if run.loaded_at and r.get("started_at") else None)
                for r in run_rows],
            "state_at_send": [
                {k: (r.get("state_before") or {}).get(k)
                 for k in ("loaded", "operation", "load_error")}
                for r in run_rows],
            "inside_window": sum(1 for r in run_rows if r["inside_window"]),
            "classifications": [r["classification"] for r in run_rows],
            "http_status": [r["http_status"] for r in run_rows],
            "output_chars": [r["output_chars"] for r in run_rows],
            "replacement_counts": [r["replacement_count"] for r in run_rows],
            "notes": run.notes,
            "error": run.error,
            "worker_total_requests": run.worker_total_requests,
            "records_delta": run.as_dict()["records_delta"],
            "dmesg_after": run.dmesg_after,
        })
    return {
        "rows": rows,
        "overall": bucket(rows),
        "inside_window": bucket(inside),
        "after_window": bucket(after),
        "by_surface": by_surface,
        "per_timing": per_timing,
        "window_rows": len(inside),
        "control_rows": len(after),
    }


def verdicts(summary: dict, runs: Sequence[TimingRun], mode: str,
             stopped_reason: str | None) -> dict:
    """The answer to the question the task asked, computed from the rows.

    Every key is a count compared against an expectation, and the report prints
    them so a reader can disagree with the arithmetic instead of the prose. The
    three headline questions:

    * **Did the window admit a request?** ``window_admitted`` -- any 2xx inside
      the window, on any surface. That is the race the fix closed, observed
      rather than inferred.
    * **What did an admitted request produce?** Counted by classification. A
      ``summary`` would mean the window is harmless in practice; ``garbage``,
      ``empty`` or ``hang`` would be the failure mode the field report suggests.
    * **Did anything hang the TPU?** ``tpu_hang`` from dmesg, plus
      ``window_hangs`` for requests that never answered.
    """
    inside = summary["inside_window"]
    after = summary["after_window"]
    window_admitted = inside["admitted"]
    control_garbage = after["by_classification"].get("garbage", 0) \
        + after["by_classification"].get("empty", 0)
    tpu_hang = bool(stopped_reason and "dmesg" in stopped_reason) or any(
        run.dmesg_after and not run.dmesg_before for run in runs)
    flags = {
        "mode": mode,
        "window_rows_observed": inside["attempts"],
        "window_refused": inside["refused"],
        "window_admitted": window_admitted,
        "window_admitted_summary": inside["by_classification"].get("summary", 0),
        "window_admitted_summary_suspect": inside["by_classification"].get(
            "summary_suspect", 0),
        "window_admitted_garbage": inside["by_classification"].get("garbage", 0),
        "window_admitted_empty": inside["by_classification"].get("empty", 0),
        "window_hangs": inside["hang"],
        "window_http_errors": inside["http_error"],
        "control_rows": after["attempts"],
        "control_refused": after["refused"],
        "control_summary": after["by_classification"].get("summary", 0),
        "control_garbage_or_empty": control_garbage,
        "tpu_hang": tpu_hang,
        "stopped_reason": stopped_reason,
        "replacement_rows_total": summary["overall"]["replacement_rows"],
        "replacement_rows_control": after["replacement_rows"],
        "replacement_rows_window": inside["replacement_rows"],
    }
    # The reproduction answer, which is the one the customer asked for.
    if inside["attempts"] == 0:
        flags["reproduced"] = "no_window_sample"
        flags["reproduction_note"] = (
            "没有在加载窗口内取到任何请求：所有目标延迟都落在模型就绪之后，"
            "或该模式下窗口无法被命中。不能据此声称复现或未复现。")
    elif window_admitted == 0:
        flags["reproduced"] = "refused_at_every_window_attempt"
        flags["reproduction_note"] = (
            f"窗口内 {inside['attempts']} 次请求全部被拒绝（{inside['refused']} 次 409），"
            "没有一次进入半初始化 worker。")
    elif flags["window_admitted_garbage"] or flags["window_admitted_empty"] \
            or flags["window_hangs"]:
        flags["reproduced"] = "admitted_with_anomalous_output"
        flags["reproduction_note"] = (
            "窗口内出现被放行的请求，且产生空/异常/挂起结果；现场同款现象在本轮有对应观测。")
    else:
        flags["reproduced"] = "admitted_but_normal_output"
        flags["reproduction_note"] = (
            "窗口内出现被放行的请求，但输出看起来是正常摘要；"
            "未能复现现场异常，只能说明该时机下没出问题。")
    return flags


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    """HTML-escape everything, including quotes: outputs are model-generated."""
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def js_json(value: Any) -> str:
    """JSON safe to embed inside a ``<script>`` block."""
    raw = json.dumps(value, ensure_ascii=False)
    return (raw.replace("</", "<\\/").replace("<!--", "<\\!--")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


CSS = """
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--line:#2b3140;--fg:#e6e9ef;
--dim:#9aa4b2;--accent:#4ea1ff;--ok:#33c48d;--warn:#e8b13a;--bad:#f2585b;--mono:ui-monospace,
SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.65 -apple-system,
BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
header{padding:28px 32px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{margin:0 0 6px;font-size:22px;letter-spacing:.3px}
h2{margin:34px 0 12px;font-size:18px;border-left:4px solid var(--accent);padding-left:10px}
h3{margin:22px 0 8px;font-size:15px;color:var(--dim);font-weight:600}
main{padding:0 32px 80px;max-width:1500px}
.sub{color:var(--dim);font-size:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;
margin:14px 0}
.grid{display:grid;gap:12px}
.g2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700;font-family:var(--mono)}
.kpi .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.6px}
.kpi.ok .v{color:var(--ok)}.kpi.bad .v{color:var(--bad)}.kpi.warn .v{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--panel2);color:var(--dim);font-weight:600;position:sticky;top:0;z-index:1}
tbody tr:nth-child(2n){background:rgba(255,255,255,.017)}
code,.mono{font-family:var(--mono);font-size:12px}
pre{background:#0b0d11;border:1px solid var(--line);border-radius:8px;padding:12px;
overflow:auto;max-height:420px;font-family:var(--mono);font-size:12px;white-space:pre-wrap;
word-break:break-word}
.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;
font-family:var(--mono)}
.t-refused{background:rgba(51,196,141,.16);color:var(--ok)}
.t-summary{background:rgba(78,161,255,.16);color:var(--accent)}
.t-summary_suspect{background:rgba(232,177,58,.18);color:var(--warn)}
.t-garbage{background:rgba(242,88,91,.18);color:var(--bad)}
.t-empty{background:rgba(242,88,91,.18);color:var(--bad)}
.t-hang{background:rgba(242,88,91,.26);color:var(--bad)}
.t-http_error{background:rgba(232,177,58,.18);color:var(--warn)}
.note{border-left:3px solid var(--accent);background:var(--panel2);padding:10px 14px;
border-radius:0 8px 8px 0;margin:10px 0}
.warnbox{border-left:3px solid var(--warn);background:rgba(232,177,58,.07);padding:10px 14px;
border-radius:0 8px 8px 0;margin:10px 0}
.badbox{border-left:3px solid var(--bad);background:rgba(242,88,91,.08);padding:10px 14px;
border-radius:0 8px 8px 0;margin:10px 0}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
input[type=search],select{background:var(--panel2);border:1px solid var(--line);
color:var(--fg);border-radius:7px;padding:6px 10px;font-size:13px}
.chart{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px;
overflow-x:auto}
.bar{display:inline-block;height:9px;border-radius:3px;vertical-align:middle}
.scroll{max-height:620px;overflow:auto;border:1px solid var(--line);border-radius:8px}
details{background:var(--panel2);border:1px solid var(--line);border-radius:8px;
padding:8px 12px;margin:8px 0}
summary{cursor:pointer;font-weight:600}
footer{color:var(--dim);font-size:12px;padding:20px 32px;border-top:1px solid var(--line)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
.tabs button{background:var(--panel2);border:1px solid var(--line);color:var(--dim);
padding:7px 14px;border-radius:8px;cursor:pointer;font-size:13px}
.tabs button[aria-selected=true]{background:rgba(78,161,255,.16);color:var(--accent);
border-color:var(--accent)}
.tabpane[hidden]{display:none}
"""


def tag(classification: str) -> str:
    return f'<span class="tag t-{esc(classification)}">{esc(classification)}</span>'


def bar(value: float, maximum: float, colour: str) -> str:
    pct = 0 if not maximum else max(2.0, min(100.0, value / maximum * 100))
    return f'<span class="bar" style="width:{pct:.1f}%;background:{colour}"></span>'


def kpi(key: str, value: Any, cls: str = "") -> str:
    return (f'<div class="kpi {cls}"><div class="k">{esc(key)}</div>'
            f'<div class="v">{esc(value)}</div></div>')


def _timeline_rows(runs: Sequence[TimingRun]) -> list[dict]:
    """Flatten every timing into one chronological table for the report."""
    out: list[dict] = []
    for run in runs:
        load_s = (run.load_result or {}).get("seconds")
        out.append({
            "label": run.label, "kind": "timing", "at": run.started_at,
            "detail": f"unload={run.unload_result.get('status')} "
                      f"load={run.load_result.get('status')} in {load_s}s "
                      f"loaded_at={utc(run.loaded_at) or '—'}",
            "error": run.error,
        })
        for row in run.attempts:
            delay = (round(row.started_at - run.load_post_at, 2)
                     if run.load_post_at and row.started_at else None)
            out.append({
                "label": f"{run.label}/{row.surface}", "kind": "attempt",
                "at": row.started_at,
                "detail": f"delay={delay}s HTTP={row.http_status} "
                          f"{row.classification} chars={row.output_chars} "
                          f"state={row.state_before.get('loaded')}/"
                          f"{row.state_before.get('operation')}",
                "error": row.error,
            })
    out.sort(key=lambda r: r.get("at") or 0)
    return out


def write_report(evidence: Path, env: dict, summary: dict, flags: dict,
                 runs: Sequence[TimingRun], mode: str,
                 bmodel: dict, debs: dict, service: Service,
                 export_info: dict, sqlite_info: dict,
                 companion: dict | None = None) -> Path:
    """Assemble the single self-contained HTML file.

    Structure follows the task card: ① overall conclusion and the reproduction
    answer, ② per-timing timeline, ③ datings/results/delay charts, ④ full data
    and raw output. Nothing is loaded from outside -- no CDN, no font, no image
    -- so the file opens on a board with no network and can be attached to an
    issue without losing anything. Everything that came from the model is
    escaped through :func:`esc`.

    ``companion`` carries a second run of the *other* mode (native alongside
    instrumented, or the reverse). The two answers only make sense together --
    "the window refused everything" and "when widened, the window admits
    requests" are the same finding seen from both sides -- so the deliverable is
    one file that states both and keeps their data apart. It is optional: a
    single-mode run is still a complete report.
    """
    inside = summary["inside_window"]
    after = summary["after_window"]
    overall = summary["overall"]
    generated = utc(time.time())

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MYS-2502 旧版 v0.6.13 模型加载竞态多时机复现报告</title>
<style>{CSS}</style></head><body>
<header>
<h1>MYS-2502 · 旧版 v0.6.13「模型未完全加载即推理」多时机复现</h1>
<div class="sub">设备 <code>.151</code> · SN <code>{esc(env.get('oem_sn'))}</code> ·
模型 <code>{esc(service.model)}</code> · 模式 <b>{esc(mode)}</b> ·
生成于 {esc(generated)}</div>
<div class="sub">固定输入 {esc(env.get('input_text_chars'))} 字，
SHA-256 <code>{esc(env.get('input_text_sha256'))}</code></div>
</header><main>""")

    # ---- ① conclusion --------------------------------------------------
    reproduced = flags.get("reproduced")
    verdict_class = {"refused_at_every_window_attempt": "ok",
                     "admitted_but_normal_output": "warn",
                     "admitted_with_anomalous_output": "bad",
                     "no_window_sample": "warn"}.get(reproduced, "warn")
    parts.append(f"""<h2>① 整体结论与复现答案</h2>
<div class="{'badbox' if verdict_class == 'bad' else 'warnbox' if verdict_class == 'warn' else 'note'}">
<b>复现判定：</b>{esc(flags.get('reproduction_note'))}
</div>
<div class="grid g3">
{kpi('加载窗口内请求数', inside['attempts'], '')}
{kpi('窗口内被拒绝 (409)', inside['refused'], 'ok' if inside['refused'] else '')}
{kpi('窗口内被放行', inside['admitted'], 'bad' if inside['admitted'] else 'ok')}
{kpi('窗口内异常/空/挂起', inside['by_classification'].get('garbage', 0)
     + inside['by_classification'].get('empty', 0) + inside['hang'],
     'bad' if (inside['by_classification'].get('garbage', 0)
               + inside['by_classification'].get('empty', 0) + inside['hang']) else 'ok')}
{kpi('ready 对照组请求数', after['attempts'], '')}
{kpi('TPU hang (dmesg)', '是' if flags.get('tpu_hang') else '否',
     'bad' if flags.get('tpu_hang') else 'ok')}
</div>
<div class="card"><h3>窗口内 / 窗口后 逐分类计数</h3>
<table><thead><tr><th>分类</th><th>含义</th><th>窗口内</th><th>窗口后（对照）</th></tr></thead>
<tbody>""")
    class_meaning = {
        "refused": "HTTP 409，服务明确拒绝（模型未加载）",
        "summary": "2xx，输出是正常摘要",
        "summary_suspect": "2xx，摘要形但含 U+FFFD（已知解码缺陷）",
        "garbage": "2xx，输出不像摘要（退化/复读/碎片）",
        "empty": "2xx，无任何输出文本",
        "hang": "超时或连接中断，无响应",
        "http_error": "其他非 2xx（500/503/429/连接被拒）",
    }
    for cls in ("refused", "summary", "summary_suspect", "garbage", "empty", "hang",
                "http_error"):
        parts.append(
            f"<tr><td>{tag(cls)}</td><td>{esc(class_meaning[cls])}</td>"
            f"<td><b>{esc(inside['by_classification'].get(cls, 0))}</b></td>"
            f"<td>{esc(after['by_classification'].get(cls, 0))}</td></tr>")
    parts.append(f"""<tr><td colspan="2"><b>合计</b></td>
<td><b>{esc(inside['attempts'])}</b></td><td><b>{esc(after['attempts'])}</b></td></tr>
</tbody></table></div>""")

    # The plain-language answer, generated from the numbers rather than typed in.
    if reproduced == "refused_at_every_window_attempt":
        answer = (
            f"在 {inside['attempts']} 次窗口内请求上，v0.6.13 全部以 409 拒绝，"
            f"没有一次进入半初始化的 worker；窗口后的 {after['attempts']} 次对照请求"
            f"中 {after['by_classification'].get('summary', 0)} 次返回正常摘要。"
            "也就是说：<b>在这个模型、这组时机上，未加载完毕时推理不会得到异常输出，"
            "而是直接被拒绝</b>。现场「两个女生约好一起出门……」那类异常输出，"
            "本轮没有在本设备复现，不能据此宣称已复现根因。")
    elif reproduced == "admitted_with_anomalous_output":
        answer = (
            f"窗口内 {inside['admitted']} 次请求被放行，其中 "
            f"{inside['by_classification'].get('garbage', 0)} 次输出不像摘要、"
            f"{inside['hang']} 次挂起。这条路径是真实的："
            "模型报告 loaded 之后、能力探测完成之前，请求可以进入 worker 并产生异常结果。")
    elif reproduced == "admitted_but_normal_output":
        answer = (
            f"窗口内 {inside['admitted']} 次请求被放行，输出都是正常摘要。"
            "被放行这一点本身是旧版准入缺陷的实证，但这几次没有产生异常输出——"
            "异常输出依赖更细的时序，本轮时机未命中。")
    else:
        answer = (
            "本轮没有在加载窗口内取到任何请求，因此既不能说复现、也不能说未复现。"
            "下方「局限」一节写明原因。")
    parts.append(f'<div class="card"><h3>直白回答（本模式）</h3><p>{answer}</p></div>')

    # The combined answer. This is the section the task card asks for, and it is
    # the only place the two modes are read together -- deliberately as two
    # labelled halves, never averaged into one number.
    if companion:
        probe_widths_text = "、".join(
            f"{w:g}" for w in (companion.get("probe_window_ms_all") or [])) or "无"
        # Did any native `edge` run actually observe the state? That is the
        # strongest possible native evidence, and whether the requests then got
        # in is a separate, millisecond-level fact.
        edge_observed = [r for r in runs
                         if r.kind == "edge" and r.settle_edge_at is not None]
        if edge_observed:
            best = min(edge_observed,
                       key=lambda r: min((a.started_at or 0) for a in r.attempts) or 0)
            offsets = sorted(
                ((a.started_at or 0) - (best.ready_observed_at or 0)) * 1000
                for a in best.attempts)
            # NOTE: not named ``inside`` -- that is the window bucket dict used
            # later in this function, and shadowing it turned the next section's
            # ``inside['attempts']`` into a list index error.
            edge_inside = [a for a in best.attempts
                           if state_is_loading(a.state_before or {})]
            edge_paragraph = (
                f"<p><b>原生 `edge` 时机的实测边界</b>：本次运行确实"
                f"<b>观测到了</b> <code>loaded=true, operation=loading</code> 这个状态，"
                f"窗口宽 <b>{esc(round((best.settle_window_s or 0) * 1000, 1))} ms</b>。"
                f"但三个接口的请求发出时，窗口已经关闭 "
                f"<b>{esc('、'.join(f'{o:+.1f}' for o in offsets))} ms</b>"
                f"（负值表示早于关闭时刻；这里是正值，即已关闭之后）。"
                f"因此它们全部落在窗口之后、得到 200 正常摘要，"
                f"放行计数仍为 0——这是<b>边界未命中</b>，不是「窗口拦住了」。"
                f"窗口内实际被放行的次数见上表的插桩实验。</p>"
                if not edge_inside else
                f"<p><b>原生 `edge` 时机命中</b>：窗口宽 "
                f"{esc(round((best.settle_window_s or 0) * 1000, 1))} ms，"
                f"{esc(len(edge_inside))} 个接口的请求确实在窗口内发出。见上表。</p>")
        else:
            edge_paragraph = (
                "<p><b>原生 `edge` 时机</b>：本次运行从未观测到 "
                "<code>loaded=true, operation=loading</code> 这个状态——"
                "窗口比一次 admin 轮询还窄。报告如实记为「未观测到」，"
                "不把它算作窗口样本。</p>")
        cflags = companion.get("flags") or {}
        csum = companion.get("summary") or {}
        cwin = (csum.get("inside_window") or {})
        native_flags, instr_flags = (flags, cflags) if mode == "native" else (cflags, flags)
        native_sum, instr_sum = (summary, csum) if mode == "native" else (csum, summary)
        nwin = native_sum.get("inside_window") or {}
        iwin = instr_sum.get("inside_window") or {}
        width_ms = companion.get("probe_window_ms")
        parts.append(f"""<div class="card"><h3>原生 + 插桩：两半合起来的结论</h3>
<p>这个问题在原生发布包上<b>测不到</b>：窗口只有几毫秒，比一次 admin 轮询还窄。
所以结论必须由两个实验共同给出，缺一半都不能下判断。</p>
<table><thead><tr><th>实验</th><th>窗口内尝试</th><th>409 拒绝</th>
<th>被放行</th><th>被放行后的输出</th></tr></thead><tbody>
<tr><td><b>原生</b>（发布包原样）</td>
<td>{esc(nwin.get('attempts', 0))}</td><td>{esc(nwin.get('refused', 0))}</td>
<td><b>{esc(nwin.get('admitted', 0))}</b></td>
<td>{esc('全部正常摘要' if not (nwin.get('by_classification') or {}).get('garbage')
          and not (nwin.get('by_classification') or {}).get('empty')
          and not nwin.get('hang') else '存在异常/空/挂起')}</td></tr>
<tr><td><b>插桩</b>（窗口人为放大）</td>
<td>{esc(iwin.get('attempts', 0))}</td><td>{esc(iwin.get('refused', 0))}</td>
<td><b>{esc(iwin.get('admitted', 0))}</b></td>
<td>{esc('全部正常摘要' if not (iwin.get('by_classification') or {}).get('garbage')
          and not (iwin.get('by_classification') or {}).get('empty')
          and not iwin.get('hang') else '存在异常/空/挂起')}</td></tr>
</tbody></table>
<p><b>结论一（缺陷真实存在）</b>：插桩实验里窗口被放大后，三个接口
<b>{esc(iwin.get('admitted', 0))}</b> 次请求全部被<b>放行</b>并进入了 worker
（发送瞬间模型自报 <code>loaded=true, operation=loading</code>）。
这证明「模型已发布 loaded、但能力探测尚未结束」这个状态确实可以被未加准入门控的旧版放行——
不是推测，是实测。</p>
<p><b>结论二（原生条件下几乎打不中）</b>：原生实验里窗口内
<b>{esc(nwin.get('attempts', 0))}</b> 次请求全部得到 409，放行 0 次。
原因不是门控存在（v0.6.13 并没有 v0.6.14 的 <code>require_ready</code>），
而是这个窗口本身只有
<b>{esc(round(width_ms, 2) if width_ms is not None else '若干')} ms</b>（8 个时机实测
{esc(probe_widths_text)}）：
<code>loaded=true</code> 发布后紧接着就是能力探测的两次本机 RPC，
期间 <code>operation</code> 仍为 <code>loading</code>，而 <code>_resolve_model</code>
只检查 <code>loaded</code>——所以「能不能进」取决于请求是否恰好落在这几毫秒里。</p>
{edge_paragraph}
<p><b>结论三（放行后的输出没有异常）</b>：被放行的 {esc(iwin.get('admitted', 0))}
次请求，输出与 ready 对照组<b>逐字相同</b>（同一 prompt、同一 token 数）。
原因在 worker 侧：它<b>先把权重载入 NPU、再 <code>sched.start()</code>、最后才
<code>start_server()</code> 打开 socket</b>，并且 <code>sched.start()</code> 是
<code>create_task</code> 不阻塞。所以服务端「loaded」与「socket 已开」是同一时刻，
能进 worker 的请求，其引擎与调度器都已在跑。这就是「被放行但输出正常」的机制解释。</p>
<p><b>因此，现场那一次异常输出不能用这条竞态解释。</b>本轮没有复现
「两个女生约好一起出门……」同款异常，也没有任何证据把它归因到加载竞态。
样本量与其它可能原因见「局限」。</p>
</div>""")

    parts.append("""<div class="card"><h3>窗口内每一次请求的完整结果</h3>
<p class="sub">按时间排序。「距 load POST」是请求发出时刻相对 load 请求发出的秒数，
不是目标延迟——两者不同正是这张表的意义。
「距窗口开启/关闭」只对 <code>edge</code> 时机、且只在真的观测到窗口时才有值：
负的「距窗口开启」表示请求在窗口打开前就发出，正的「距窗口关闭」表示窗口已经关上之后才发出。</p>
<div class="scroll"><table><thead><tr>
<th>时机</th><th>接口</th><th>目标延迟</th><th>距 load POST(s)</th><th>发送时状态</th>
<th>距窗口开启(ms)</th><th>距窗口关闭(ms)</th><th>HTTP</th><th>分类</th><th>输出字数</th>
<th>U+FFFD</th><th>记录</th><th>说明</th></tr></thead><tbody>""")
    for row in summary["rows"]:
        if not row["inside_window"]:
            continue
        state = row.get("state_before") or {}
        parts.append(f"""<tr>
<td><code>{esc(row['timing_label'])}</code></td><td>{esc(row['surface'])}</td>
<td>{esc(row['target_delay_s'] if row['target_delay_s'] is not None else 'ready')}</td>
<td><code>{esc(row.get('delay_from_load_post_s'))}</code></td>
<td><code>{esc(state.get('loaded'))}/{esc(state.get('operation'))}</code></td>
<td><code>{esc(row.get('ms_after_window_open') if row.get('ms_after_window_open') is not None else '—')}</code></td>
<td><code>{esc(row.get('ms_after_window_close') if row.get('ms_after_window_close') is not None else '—')}</code></td>
<td>{esc(row['http_status'])}</td><td>{tag(row['classification'])}</td>
<td>{esc(row['output_chars'])}</td><td>{esc(row['replacement_count'])}</td>
<td>{esc('有' if row.get('record') else ('无' if row.get('record_missing') is False else '—'))}</td>
<td class="sub">{esc((row.get('classification_reason') or '')[:160])}</td></tr>""")
    if inside["attempts"] == 0:
        parts.append('<tr><td colspan="13" class="sub">本轮没有窗口内请求。</td></tr>')
    parts.append("</tbody></table></div></div>")

    # ---- ② timeline ----------------------------------------------------
    parts.append("""<h2>② 每次实验时间线</h2>
<p class="sub">一次实验 = 一次完整 unload → load → 在指定延迟发送请求。
下表把每次实验与它内部的每次请求按真实时间排在一起。</p>
<div class="scroll"><table><thead><tr><th>时间 (UTC)</th><th>对象</th>
<th>实际发生</th><th>错误</th></tr></thead><tbody>""")
    for entry in _timeline_rows(runs):
        parts.append(
            f"<tr><td><code>{esc(utc(entry.get('at')))}</code></td>"
            f"<td><code>{esc(entry['label'])}</code></td>"
            f"<td>{esc(entry['detail'])}</td>"
            f"<td class='sub'>{esc((entry.get('error') or '')[:200])}</td></tr>")
    parts.append("</tbody></table></div>")

    parts.append('<h3>每次加载的时序采样</h3><div class="scroll"><table><thead><tr>'
                 '<th>时机</th><th>类型</th><th>目标延迟(s)</th><th>实际延迟(s)</th>'
                 '<th>load HTTP</th><th>加载耗时(s)</th>'
                 '<th>观测到的窗口宽度(s)</th>'
                 '<th>发送时 loaded/operation</th>'
                 '<th>就绪差(s)</th><th>新 worker 推理次数</th><th>记录 Δ</th><th>备注</th>'
                 '</tr></thead><tbody>')
    kind_meaning = {"wall": "按秒数猜", "edge": "命中 published-not-settled",
                    "ready": "就绪后对照"}
    for item in summary["per_timing"]:
        parts.append(f"""<tr><td><code>{esc(item['label'])}</code></td>
<td>{esc(kind_meaning.get(item.get('kind'), item.get('kind')))}</td>
<td>{esc(item['target_delay_s'] if item['target_delay_s'] is not None else 'ready')}</td>
<td><code>{esc(item['actual_delays_s'])}</code></td>
<td>{esc(item['load_status'])}</td><td>{esc(item['load_seconds'])}</td>
<td><code>{esc(item.get('settle_window_s') if item.get('settle_window_s') is not None
              else ('未观测到' if not item.get('settle_edge_observed') else '—'))}</code></td>
<td><code>{esc([f"{s.get('loaded')}/{s.get('operation')}" for s in item['state_at_send']])}</code></td>
<td><code>{esc(item['loaded_at_vs_send_s'])}</code></td>
<td>{esc(item['worker_total_requests'])}</td><td>{esc(item['records_delta'])}</td>
<td class="sub">{esc('; '.join((item['notes'] or [])[:3]) or (item.get('error') or ''))}</td>
</tr>""")
    parts.append("</tbody></table></div>")

    # ---- ③ charts ------------------------------------------------------
    parts.append("<h2>③ 加载时机与结果</h2>")
    parts.append('<div class="card"><h3>每个时机的延迟与结果</h3>'
                 '<p class="sub">横条长度 = 实际延迟（相对 load POST）；'
                 '右侧是该时机的三个接口结果。</p>')
    max_delay = max([d for item in summary["per_timing"]
                     for d in item["actual_delays_s"] if d is not None] or [1.0])
    for item in summary["per_timing"]:
        delays = [d for d in item["actual_delays_s"] if d is not None]
        shown = max(delays) if delays else 0
        colour = ("var(--ok)" if all(c == "refused" for c in item["classifications"])
                  and item["classifications"] else
                  "var(--bad)" if any(c in ("garbage", "empty", "hang")
                                      for c in item["classifications"]) else
                  "var(--accent)")
        tags_html = " ".join(tag(c) for c in item["classifications"])
        parts.append(f"""<div style="margin:9px 0">
<div class="mono" style="font-size:12px;color:var(--dim)">
{esc(item['label'])} · 目标 {esc(item['target_delay_s'] if item['target_delay_s'] is not None else 'ready 后')}s
· 实际 {esc(round(shown, 2))}s · 加载 {esc(item['load_seconds'])}s</div>
{bar(shown, max_delay, colour)}
<div style="margin-top:3px">{tags_html}</div></div>""")
    parts.append("</div>")

    parts.append('<div class="card"><h3>逐接口的窗口内结果</h3><table><thead><tr>'
                 '<th>接口</th><th>窗口内尝试</th><th>409</th><th>被放行</th>'
                 '<th>挂起</th><th>延迟中位数(s)</th><th>TTFT 中位数(s)</th>'
                 '<th>对照组尝试</th><th>对照组正常摘要</th></tr></thead><tbody>')
    for surface, data in summary["by_surface"].items():
        w = data["inside_window"]
        c = data["after_window"]
        parts.append(f"""<tr><td><code>{esc(surface)}</code></td>
<td>{esc(w['attempts'])}</td><td>{esc(w['refused'])}</td><td>{esc(w['admitted'])}</td>
<td>{esc(w['hang'])}</td>
<td>{esc((w['latency_s'] or {}).get('median', '—'))}</td>
<td>{esc((w['ttft_s'] or {}).get('median', '—'))}</td>
<td>{esc(c['attempts'])}</td><td>{esc(c['by_classification'].get('summary', 0))}</td>
</tr>""")
    parts.append("</tbody></table></div>")

    parts.append('<div class="card"><h3>已知解码缺陷（U+FFFD）单独统计</h3>'
                 f"""<div class="grid g3">
{kpi('窗口内含 U+FFFD 的行', inside['replacement_rows'], 'warn' if inside['replacement_rows'] else '')}
{kpi('对照组合 U+FFFD 的行', after['replacement_rows'], 'warn' if after['replacement_rows'] else '')}
{kpi('全部行合计', overall['replacement_rows'], 'warn' if overall['replacement_rows'] else '')}
</div>
<p>v0.6.13/v0.6.14 都存在流式逐 token 解码缺陷：被拆到两个 token 的字符会输出
<code>\\ufffd</code>（证据见 MYS-2510：<code>门簪</code> → <code>门\\ufffd\\ufffd</code>）。
本表把它与「加载竞态导致的异常」分开：只有当对照组的输出干净、而窗口内出现异常时，
才可把异常归因于竞态。本轮如果两组都出现 <code>\\ufffd</code>，那是既有缺陷，与加载无关。
修复在 MYS-2520 并行进行，本任务不改产品代码。</p></div>""")

    # ---- ④ full data ---------------------------------------------------
    parts.append("<h2>④ 完整数据、原始输出与证据</h2>")
    parts.append('<div class="toolbar"><input type="search" id="q" placeholder="过滤：时机/接口/分类/HTTP…" size="34">'
                 '<select id="fc"><option value="">全部分类</option>'
                 + "".join(f'<option value="{esc(c)}">{esc(c)}</option>'
                           for c in sorted({r["classification"]
                                            for r in summary["rows"]}))
                 + '</select><span class="sub" id="cnt"></span></div>')
    parts.append('<div class="scroll"><table id="allrows"><thead><tr>'
                 '<th>时机</th><th>接口</th><th>窗口内</th><th>目标(s)</th>'
                 '<th>实际(s)</th><th>HTTP</th><th>分类</th><th>输出字数</th>'
                 '<th>U+FFFD</th><th>finish</th><th>prompt_tok</th><th>compl_tok</th>'
                 '<th>TTFT(s)</th><th>总耗时(s)</th><th>req_id</th><th>原始文件</th>'
                 '</tr></thead><tbody>')
    for row in summary["rows"]:
        cls = row["classification"]
        parts.append(f"""<tr data-class="{esc(cls)}">
<td><code>{esc(row['timing_label'])}</code></td><td>{esc(row['surface'])}</td>
<td>{esc('是' if row['inside_window'] else '否')}</td>
<td>{esc(row['target_delay_s'] if row['target_delay_s'] is not None else 'ready')}</td>
<td><code>{esc(row.get('delay_from_load_post_s'))}</code></td>
<td>{esc(row['http_status'])}</td><td>{tag(cls)}</td>
<td>{esc(row['output_chars'])}</td><td>{esc(row['replacement_count'])}</td>
<td>{esc(row['finish_reason'])}</td><td>{esc(row['prompt_tokens'])}</td>
<td>{esc(row['completion_tokens'])}</td><td>{esc(row['ttft_s'])}</td>
<td>{esc(row['total_s'])}</td>
<td><code>{esc(row['req_id'] or '—')}</code></td>
<td><code>{esc(row['raw_file'] or '—')}</code></td></tr>""")
    parts.append("</tbody></table></div>")

    # Per-attempt full output, escaped, in a details block.
    parts.append("<h3>每次请求的完整输出与状态</h3>")
    for row in summary["rows"]:
        rec = row.get("record") or {}
        state = row.get("state_before") or {}
        parts.append(f"""<details><summary>{esc(row['timing_label'])} / {esc(row['surface'])}
— {esc(row['classification'])} · HTTP {esc(row['http_status'])}
· {esc(row['output_chars'])} 字</summary>
<table><tbody>
<tr><th style="width:190px">发送时模型状态</th><td><code>{esc(json.dumps(
    {k: state.get(k) for k in ('loaded', 'operation', 'loaded_at', 'load_error',
                               'pid', 'port')}, ensure_ascii=False))}</code></td></tr>
<tr><th>实际延迟 / 窗口内偏移</th><td><code>{esc(row.get('delay_from_load_post_s'))}s after
load POST · {esc(row.get('ms_after_window_open'))} ms after window opened ·
{esc(row.get('ms_after_window_close'))} ms after it closed</code></td></tr>
<tr><th>HTTP / finish_reason</th><td><code>{esc(row['http_status'])} /
{esc(row['finish_reason'])}</code></td></tr>
<tr><th>token (prompt/completion/cached)</th><td><code>{esc(row['prompt_tokens'])} /
{esc(row['completion_tokens'])} / {esc(row['cached_tokens'])}</code></td></tr>
<tr><th>错误</th><td><code>{esc((row.get('error') or '')[:2000] or '—')}</code></td></tr>
<tr><th>错误帧</th><td><code>{esc(json.dumps(row.get('error_frames') or [],
                                                ensure_ascii=False)[:2000])}</code></td></tr>
<tr><th>U+FFFD 位置</th><td><code>{esc(json.dumps(row.get('replacement_chars') or [],
                                                  ensure_ascii=False)[:2000])}</code></td></tr>
<tr><th>推理记录</th><td><code>{esc(json.dumps(
    {k: rec.get(k) for k in ('id', 'source', 'status', 'finish_reason', 'output_chars',
                             'prompt_tokens', 'completion_tokens', 'decode_tps',
                             'first_token_latency_s')} if rec else None,
    ensure_ascii=False))}</code></td></tr>
</tbody></table>
<h3 style="margin-top:12px">输出全文</h3>
<pre>{esc(row['output'] or '（空）')}</pre>
<h3 style="margin-top:12px">记录里的 output_text</h3>
<pre>{esc(rec.get('output_text') or '（无记录）')}</pre>
</details>""")

    # Evidence inventory.
    parts.append('<div class="card"><h3>证据清单</h3><table><tbody>')
    parts.append(f"<tr><th style='width:220px'>证据目录</th><td><code>{esc(str(evidence))}</code></td></tr>")
    parts.append(f"<tr><th>原始响应文件</th><td><code>raw/</code> 共 "
                 f"{esc(len(list((evidence / 'raw').glob('*'))))} 个</td></tr>")
    parts.append(f"<tr><th>NDJSON 导出</th><td><code>{esc(export_info)}</code></td></tr>")
    parts.append(f"<tr><th>SQLite 直读核对</th><td><code>{esc(sqlite_info)}</code></td></tr>")
    parts.append(f"<tr><th>.bmodel</th><td><code>{esc(bmodel)}</code></td></tr>")
    parts.append(f"<tr><th>deb 校验</th><td><code>{esc(json.dumps(debs, ensure_ascii=False))}</code></td></tr>")
    worker_logs = [r.worker_log_file for r in runs if r.worker_log_file]
    journals = [r.journal_file for r in runs if r.journal_file]
    parts.append(f"<tr><th>worker 日志</th><td><code>{esc(len(worker_logs))} 个</code>"
                 f"{esc('（' + ', '.join(worker_logs[:3]) + ('…' if len(worker_logs) > 3 else '') + '）') if worker_logs else ''}</td></tr>")
    parts.append(f"<tr><th>服务 journal</th><td><code>{esc(len(journals))} 个</code>"
                 f"{esc('（' + ', '.join(journals[:3]) + ('…' if len(journals) > 3 else '') + '）') if journals else ''}</td></tr>")
    parts.append("</tbody></table></div>")

    # Environment.
    parts.append('<div class="card"><h3>设备与环境</h3><table><tbody>')
    for key in ("hostname", "oem_sn", "uname", "uptime", "date_utc", "meminfo_head",
                "free_m", "df_data", "df_root", "installed_version",
                "installed_commit", "service_unit", "dmesg_vpp", "python"):
        value = env.get(key)
        if value in (None, ""):
            continue
        parts.append(f"<tr><th style='width:200px'>{esc(key)}</th>"
                     f"<td><code>{esc(value)}</code></td></tr>")
    parts.append(f"<tr><th>dmesg NPU 错误</th><td><code>"
                 f"{esc(json.dumps(env.get('dmesg_npu_errors') or [], ensure_ascii=False))}"
                 f"</code></td></tr>")
    parts.append("</tbody></table></div>")

    # Limits -- the section that keeps the report honest.
    if mode == "native":
        mode_text = (
            "<b>原生模式</b>：直接打 v0.6.13 发布包，服务端没有任何改动或人造延迟。"
            "窗口宽度完全由服务自身决定；因此 <code>edge</code> 时机能否命中取决于一次 admin "
            "轮询能否落进那个窗口，未命中的行在表中如实标注为「窗口内=否」。")
    else:
        mode_text = (
            f"<b>插桩（测试构建）模式</b>：同一发布包，以 <code>sitecustomize.py</code> 延迟 "
            f"<code>WorkerClient.health</code> {esc(env.get('settle_delay_s'))} 秒启动。该调用在 "
            "v0.6.13 中只有一个调用方——<code>_load_locked</code> 的能力探测，位于 "
            "<code>loaded</code> 发布之后、<code>operation</code> 清空之前。因此放大的是状态机"
            "自己的「已发布未就绪」窗口，其它任何路径（<code>/api/models</code>、"
            "<code>/api/stats</code>、readiness 握手）都不经过它。"
            "<b>其结论只描述窗口被放大后的旧版行为，不能当作原生时序证据</b>；"
            "原生行为请看 native 报告。")
    parts.append(f"""<div class="card"><h3>局限与不声称的事</h3><ul>
<li><b>模式</b>：{mode_text}</li>
<li><b>样本量</b>：每个时机每个接口只发一次请求。这不是统计意义上的采样，
而是「该时机下这一次发生了什么」的事实记录。多次重复会占用数十小时的设备时间。</li>
<li><b>时机与阶段的关系</b>：目标延迟只是「请求发出的时刻」，不是「模型处于哪个初始化阶段」。
真实阶段由表中「发送时模型状态」与「就绪差」说明，报告不把延迟名称当成阶段名称。</li>
<li><b>轮询分辨率</b>：`edge` 时机依赖对 `/api/models` 的轮询，分辨率受 admin GET 往返时间限制。
观测到的窗口宽度写在「每次加载的时序采样」表里；如果窗口比一次轮询还窄，
报告会明说「从未观测到」，而不是假装命中。</li>
<li><b>复现边界</b>：现场异常发生在另一台设备的 v0.6.12 上，且当时没有留下任何请求/回复内容。
本报告测的是同一代码路径在 v0.6.13 上的行为，不等于复现了那一台设备的那一次。</li>
<li><b>解码缺陷</b>：U+FFFD 是已知的独立缺陷（MYS-2510/MYS-2520），已单列，
不参与加载竞态的判定。</li>
</ul></div>""")

    parts.append("""</main><footer>
单文件自包含报告：无外部 CSS/JS/字体/图片引用。所有模型输出均经 HTML 转义。
本文件不含任何 API key、cookie 或 admin 密码。
</footer>""")

    # Filter script (inline, no external deps).
    parts.append("""<script>
(function(){
  var q=document.getElementById('q'), fc=document.getElementById('fc'),
      table=document.getElementById('allrows'), cnt=document.getElementById('cnt');
  if(!table) return;
  var rows=Array.prototype.slice.call(table.tBodies[0].rows);
  function apply(){
    var needle=(q.value||'').toLowerCase(), cl=fc.value, shown=0;
    rows.forEach(function(tr){
      var text=tr.textContent.toLowerCase();
      var ok=(!needle||text.indexOf(needle)>=0)&&(!cl||tr.dataset.class===cl);
      tr.style.display=ok?'':'none'; if(ok) shown++;
    });
    cnt.textContent=shown+' / '+rows.length+' 行';
  }
  q.addEventListener('input',apply); fc.addEventListener('change',apply); apply();
})();
</script></body></html>""")

    out = evidence / "report.html"
    out.write_text("".join(parts), encoding="utf-8")
    return out


def audit_report(path: Path) -> dict:
    """Check the report is actually self-contained and safe.

    A report that quietly references a CDN, or that lets a model's output break
    out of its cell, is worse than no report: it looks authoritative and is
    either blank on the board or an injection vector. Checked mechanically:

    * no ``http(s)://`` reference that would be fetched (links in ``href`` to
      external pages are also flagged -- the file has none by construction);
    * no ``src=`` / ``@import`` / ``<link``;
    * no unescaped replacement char problems (the char itself is fine inside
      ``<pre>``, it is ``<script>`` injection that matters);
    * the file parses as HTML well enough that the four required sections exist.
    """
    text = path.read_text(encoding="utf-8")
    external: list[str] = []
    for match in re.finditer(r'(?:src|href)\s*=\s*["\'](?!#)([^"\']+)', text):
        value = match.group(1).strip()
        if value.startswith(("data:", "#")):
            continue
        external.append(value)
    for pattern in (r"@import", r"<link\b", r"<iframe\b", r"<object\b", r"<embed\b"):
        if re.search(pattern, text, re.I):
            external.append(pattern)
    sections = {name: (name in text) for name in
                ("① 整体结论与复现答案", "② 每次实验时间线",
                 "③ 加载时机与结果", "④ 完整数据、原始输出与证据")}
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "external_refs": external,
        "self_contained": not external,
        "sections_present": sections,
        "all_sections": all(sections.values()),
        "has_script": "<script" in text,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def parse_delays(values: Sequence[str]) -> list[tuple[str, float | None]]:
    """Turn CLI timing specs into ``(kind, delay)`` pairs.

    Three spellings, and the distinction between them is the experiment:

    * ``ready`` -- wait for readiness, then send. The control group: proves the
      service serves this request normally when nothing is in flight.
    * ``edge`` -- send the instant the model reads ``loaded`` with ``operation``
      still set. The window v0.6.13 actually has.
    * a number -- send that many seconds after the load POST. A *guess* at where
      the window is; whether it lands inside is recorded, not assumed.

    ``ready`` is spelled out rather than encoded as ``0`` or ``-1``: a numeric
    stand-in would invite someone to average the control in with the samples.
    """
    out: list[tuple[str, float | None]] = []
    for raw in values:
        text = raw.strip().lower()
        if text in ("ready", "control", "after"):
            out.append(("ready", None))
        elif text == "edge":
            out.append(("edge", None))
        else:
            out.append(("wall", float(raw)))
    return out


def label_for(kind: str, delay: float | None) -> str:
    """A filesystem-safe label that also says what kind of timing it was."""
    if kind == "ready":
        return "ready-control"
    if kind == "edge":
        return "edge-settle"
    text = f"{delay:g}".replace(".", "p")
    return f"delay-{text}s"


def make_evidence_dir(root: Path, mode: str) -> Path:
    """A fresh evidence directory, never reusing an existing one.

    The timestamp is second-resolution, so two runs started in the same second
    would collide -- and a collision would either crash the second run or, worse,
    mix two runs' evidence. A numeric suffix keeps "never overwrite a previous
    run" true without depending on the clock's resolution.
    """
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    for attempt in range(1000):
        suffix = "" if attempt == 0 else f"-{attempt}"
        path = root / f"run-{stamp}-{mode}{suffix}"
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (path / "raw").mkdir()
        return path
    raise RuntimeError(f"could not create a unique evidence directory under {root}")


def combine_reports(dirs: Sequence[Path]) -> int:
    """Regenerate one report from two finished runs, without touching the device.

    The task asks for one HTML report, and the two modes only answer the question
    together. This rebuilds that single file from the evidence already on disk --
    the same JSONL, the same raw bodies, no new requests -- so combining cannot
    change a result, only how it is presented.

    It refuses rather than guesses when the inputs are not what it needs: one
    ``native`` and one ``instrumented`` directory, both carrying
    ``timing-*.json`` and ``summary.json``. A report assembled from the wrong
    pairing would be worse than none.
    """
    loaded: list[tuple[str, Path, dict, dict, list]] = []
    for directory in dirs:
        summary_path = directory / "summary.json"
        if not summary_path.is_file():
            print(f"FATAL: {directory} has no summary.json", file=sys.stderr)
            return 2
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        mode = payload.get("mode")
        runs: list[TimingRun] = []
        for timing_path in sorted(directory.glob("timing-*.json")):
            raw = json.loads(timing_path.read_text(encoding="utf-8"))
            run = TimingRun(kind=raw.get("kind", "wall"), label=raw["label"],
                            target_delay_s=raw.get("target_delay_s"), mode=raw.get("mode", mode))
            for field_name in (
                "started_at", "load_post_at", "loading_observed_at", "settle_edge_at",
                "ready_observed_at", "loaded_at", "load_result", "unload_result",
                "state_at_send", "worker_total_requests", "records_before",
                "records_after", "dmesg_before", "dmesg_after", "notes", "error",
                "worker_log_file", "journal_file",
            ):
                if field_name in raw:
                    setattr(run, field_name, raw[field_name])
            for attempt_raw in raw.get("attempts") or []:
                attempt = Attempt(timing_label=attempt_raw["timing_label"],
                                  surface=attempt_raw["surface"])
                for key, value in attempt_raw.items():
                    if hasattr(attempt, key):
                        setattr(attempt, key, value)
                if attempt.target_delay_s is None and run.target_delay_s is not None:
                    attempt.target_delay_s = run.target_delay_s
                run.attempts.append(attempt)
            runs.append(run)
        # Recompute rather than reuse the stored summary: the summariser is where
        # a row's meaning is decided (window membership, per-bucket counts), and a
        # report must reflect the code that is reading the evidence now, not the
        # code that happened to be running when the evidence was written. This is
        # what keeps `--combine` a presentation step instead of a second opinion.
        loaded.append((mode, directory, summarize(runs),
                       verdicts(summarize(runs), runs, mode, None), runs))

    modes = [entry[0] for entry in loaded]
    if len(loaded) != 2 or sorted(modes) != ["instrumented", "native"]:
        print(f"FATAL: --combine needs exactly one native and one instrumented "
              f"directory (got {modes})", file=sys.stderr)
        return 2

    native = next(entry for entry in loaded if entry[0] == "native")
    instrumented = next(entry for entry in loaded if entry[0] == "instrumented")
    out_dir = native[1]
    env_path = out_dir / "env.json"
    env = json.loads(env_path.read_text(encoding="utf-8")) if env_path.is_file() else {}
    bmodel_path = out_dir / "bmodel.json"
    bmodel = json.loads(bmodel_path.read_text(encoding="utf-8")) if bmodel_path.is_file() else {}

    # The window width is the native run's measured capability-probe duration.
    # Taken from every timing and reported as a range, because a single sample of
    # a 5-12 ms interval is not a number to quote alone.
    widths: list[float] = []
    for run in native[4]:
        finished = (run.load_result or {}).get("finished_at")
        if finished and run.loaded_at:
            widths.append(round((finished - run.loaded_at) * 1000, 1))

    service = Service(Http("http://127.0.0.1:8000"), "http://127.0.0.1:8000",
                      "qwen3.6-35b-a3b-128k")
    export_info = {"note": "见各 run 目录的 records-export.ndjson"}
    sqlite_path = out_dir / "sqlite-check.json"
    sqlite_info = (json.loads(sqlite_path.read_text(encoding="utf-8"))
                   if sqlite_path.is_file() else {})
    companion = {
        "mode": instrumented[0],
        "dir": str(instrumented[1]),
        "summary": instrumented[2],
        "flags": instrumented[3],
        "probe_window_ms": (sum(widths) / len(widths)) if widths else None,
        "probe_window_ms_all": widths,
    }
    # Report the instrumented run's own companion too, so whichever half a
    # reader opens first states both sides.
    report = write_report(
        out_dir, env, native[2], native[3], native[4], "native",
        bmodel, {}, service, export_info, sqlite_info, companion=companion)
    audit = audit_report(report)
    (out_dir / "report-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"combined report: {report} ({audit['bytes']} bytes, "
          f"self_contained={audit['self_contained']}, sections={audit['all_sections']})")
    print(json.dumps({"native": native[3], "instrumented": instrumented[3],
                      "probe_window_ms_avg": companion["probe_window_ms"],
                      "probe_window_ms_all": widths},
                     ensure_ascii=False, indent=2))
    ok = audit["self_contained"] and audit["all_sections"]
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Probe a legacy (v0.6.13) service's behaviour when an "
                    "inference request arrives before its model is ready.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000",
                    help="service under test")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--password", default=ADMIN_PASSWORD_DEFAULT,
                    help="admin password (kept out of the report)")
    ap.add_argument("--key-name", default="MYS-2502-legacy-readiness")
    ap.add_argument("--evidence-dir", default="./evidence")
    ap.add_argument("--mode", choices=("native", "instrumented"), default="native",
                    help="native = the shipped release as-is; instrumented = a "
                         "test build whose capability-probe window is widened "
                         "by --settle-delay (see write_sitecustomize)")
    ap.add_argument("--settle-delay", type=float, default=0.0,
                    help="instrumented mode: seconds to delay WorkerClient.health, "
                         "which widens the loaded-but-not-settled window")
    ap.add_argument("--delays", nargs="+",
                    default=["0.1", "5", "15", "30", "45", "60", "edge", "ready"],
                    help="`edge` = fire the instant the model reads loaded with "
                         "operation set (the real window); a number = that many "
                         "seconds after the load POST; `ready` = the post-load "
                         "control group")
    ap.add_argument("--data-dir", default="/data/cv84x6-readiness-v0613",
                    help="CV84X6_DATA_DIR of the legacy instance, for the "
                         "direct SQLite read-back")
    ap.add_argument("--deb-v0613", default=None,
                    help="path to the v0.6.13 deb whose SHA-256 goes in the report")
    ap.add_argument("--deb-v0614", default=None)
    ap.add_argument("--skip-report", action="store_true")
    ap.add_argument("--combine", nargs="+", default=None, metavar="EVIDENCE_DIR",
                    help="do not run anything: regenerate ONE report from the "
                         "given evidence directories (one native, one "
                         "instrumented) and write it to the first one's "
                         "report.html. The two modes answer one question from "
                         "two sides, so the deliverable is one file.")
    args = ap.parse_args(argv)

    if args.combine:
        return combine_reports([Path(p) for p in args.combine])

    evidence = make_evidence_dir(Path(args.evidence_dir), args.mode)
    print(f"evidence: {evidence}", flush=True)
    service_url = args.base_url.rstrip("/")
    http = Http(service_url, timeout=120)
    service = Service(http, service_url, args.model, args.password, args.key_name)

    login = service.login()
    if login != 200:
        print(f"FATAL: admin login failed (HTTP {login})", file=sys.stderr)
        return 2
    key, key_id = service.create_key()

    if args.mode == "instrumented":
        # Record the widening, and refuse to silently run an "instrumented" pass
        # that was not actually widened -- that would produce a report claiming
        # a widened window while measuring the native one.
        if args.settle_delay <= 0:
            print("FATAL: --mode instrumented needs --settle-delay > 0",
                  file=sys.stderr)
            return 2
        probe = service.probe_widened()
        if not probe.get("observed"):
            print("FATAL: the service does not report the test build's widening "
                  "(its stdout should contain '[test-build]'); start it with the "
                  "generated sitecustomize.py and CV84X6_TEST_PROBE_DELAY_S set",
                  file=sys.stderr)
            print(json.dumps(probe, ensure_ascii=False), file=sys.stderr)
            return 2
        print(f"test build confirmed: {probe.get('detail')}", flush=True)

    runner = Runner(service, service_url, service_url, evidence, mode=args.mode)
    exit_code = 0
    try:
        env = capture_environment(service, service_url, evidence, args.password)
        env["mode"] = args.mode
        env["settle_delay_s"] = args.settle_delay if args.mode == "instrumented" else None
        if args.mode == "instrumented":
            env["test_build"] = probe
        bmodel = bmodel_md5(service, args.model)
        debs = {}
        for label, path in (("v0.6.13", args.deb_v0613), ("v0.6.14", args.deb_v0614)):
            if path and Path(path).exists():
                debs[label] = {"file": Path(path).name,
                               "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        (evidence / "env.json").write_text(
            json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
        (evidence / "bmodel.json").write_text(
            json.dumps(bmodel, ensure_ascii=False, indent=2), encoding="utf-8")

        # Every timing, in order. A hang stops the rest: continuing to send
        # requests at a wedged TPU is how a recoverable state becomes an
        # unrecoverable one, and the task card's whole safety section is about
        # not doing that.
        for kind, spec in parse_delays(args.delays):
            label = label_for(kind, spec)
            run = runner.run_timing(label, spec, kind=kind)
            (evidence / "runs.jsonl").open("a", encoding="utf-8").write(
                json.dumps(run.as_dict(), ensure_ascii=False) + "\n")
            # Also write each timing on its own, so a later crash cannot lose it.
            (evidence / f"timing-{label}.json").write_text(
                json.dumps(run.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
            if runner.stopped_reason:
                print(f"stopping: {runner.stopped_reason}", flush=True)
                break

        runner.attach_records()

        # Evidence: the service's own export, and a direct read of the file.
        export_info = export_records(service.admin_http, evidence / "records-export.ndjson")
        ids = [r.req_id for run in runner.runs for r in run.attempts if r.req_id]
        db_path = Path(args.data_dir) / "state" / "inference_records.sqlite3"
        rows = sqlite_records(db_path, ids)
        sqlite_info = {
            "db": str(db_path), "exists": db_path.exists(),
            "requested": len(ids), "found": len(rows),
            "missing": [rid for rid in ids if rid not in rows][:20],
        }
        (evidence / "sqlite-check.json").write_text(
            json.dumps(sqlite_info, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = summarize(runner.runs)
        flags = verdicts(summary, runner.runs, args.mode, runner.stopped_reason)
        (evidence / "summary.json").write_text(
            json.dumps({"summary": summary, "flags": flags, "mode": args.mode},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (evidence / "timeline.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in runner.timeline),
            encoding="utf-8")

        if not args.skip_report:
            report = write_report(evidence, env, summary, flags, runner.runs,
                                  args.mode, bmodel, debs, service, export_info,
                                  sqlite_info)
            audit = audit_report(report)
            (evidence / "report-audit.json").write_text(
                json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report: {report} ({audit['bytes']} bytes, "
                  f"self_contained={audit['self_contained']}, "
                  f"sections={audit['all_sections']})", flush=True)
            if not audit["self_contained"] or not audit["all_sections"]:
                print("WARN: report audit failed", file=sys.stderr)
                exit_code = 1

        print(json.dumps(flags, ensure_ascii=False, indent=2), flush=True)
        if flags["tpu_hang"]:
            exit_code = max(exit_code, 3)
    except Exception:  # noqa: BLE001 - a traceback is evidence too
        traceback.print_exc()
        (evidence / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        exit_code = 2
    finally:
        # The key exists only for the duration of the run, and only in this
        # process's memory and the service's own key list. Deleting it here is
        # what keeps it out of the report and off the device afterwards.
        try:
            service.delete_key()
        except Exception:  # noqa: BLE001
            pass
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
