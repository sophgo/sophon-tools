"""Extended stability suite: 2100 requests plus a readiness probe, one HTML report.

MYS-2501 asks for a much larger run than `board_stability_suite.py` was built
for, on a bigger model and a tighter memory layout:

  * **2000 core requests.** 1000 with no context (one independent request each)
    and 1000 with context, organised as **100 sessions x 10 turns** rather than
    1000 turns of one conversation -- 1000 turns with the whole history resent
    would reach 128k of prompt tokens and measure prefill limits, not stability.
  * **100 concurrent requests.** 2 lanes x 50 rounds, kept separate from the
    core totals, because "two lanes are fine" and "two thousand requests are
    fine" are different claims.
  * **A readiness probe.** Stop and reload the model, hammer every inference
    surface during the load window, and prove that every request is refused
    (409), that no request reaches the worker, and that no record is written --
    then that one short request succeeds afterwards with exactly one record.

The 12 length tiers are 2..1200 code points; each core group sends every tier a
declared number of times (84 for the four shortest, 83 for the rest, so the
totals are exactly 1000).

Design rules, all inherited from the MYS-2498 suite and still enforced here:

* **Standard library only.** The board runs CPython 3.10 with no httpx.
* **Every prompt is exactly its declared length**, generated from a fixed seed,
  and carries a task whose answer is computed from the text the model saw.
* **Nothing is retried.** A failure is written to JSONL as a failure and the run
  carries on; the evidence directory is new every time.
* **The service's own records are the second opinion.** Every request is
  cross-checked against `/api/inference-records/{id}` and a direct read-only
  SQLite query, so "exactly one record per inference" is a counted fact.

What this module adds on top:

* A **timeline** (`timeline.jsonl`) of phases and anomalies with timestamps, which
  is what the HTML report's second tab renders.
* A **self-contained HTML report** -- no CDN, no external font, no build step.
  Charts are inline SVG drawn from the run's own numbers, the request table is
  filterable/sortable/paginated in plain JS, and every model output is escaped
  before it reaches the DOM (:func:`html_escape` and `textContent` assignment).
* A **sampler** thread that records device and worker counters every few seconds
  for the whole run, so the report can show memory/NPU alongside the requests.

The tool is a superset of, not a replacement for, `board_stability_suite.py`:
the MYS-2498 matrix still runs there unchanged, and this one imports its prompt
generator, SSE parser, record verifier and statistics rather than copying them.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import statistics
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import board_stability_suite as base  # noqa: E402

# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

#: Length tiers in Unicode code points, extended from MYS-2498's 2..800.
TIERS: list[int] = [2, 10, 30, 60, 100, 200, 300, 400, 600, 800, 1000, 1200]

#: How many requests each core group sends at each tier. The four shortest tiers
#: get one extra each so the 12-tier total is exactly 1000 rather than 996.
REQUESTS_PER_TIER_SHORT = 84
REQUESTS_PER_TIER_LONG = 83
SHORT_TIER_COUNT = 4

#: Sessions x turns for the context group. 100 x 10 = 1000 requests, and the
#: longest context any single request carries is one session's nine earlier
#: exchanges -- a few thousand prompt tokens, not 128k.
CONTEXT_SESSIONS = 100
CONTEXT_TURNS = 10

#: Concurrency bolt-on, counted apart from the core 2000.
CONCURRENCY_LANES = 2
CONCURRENCY_ROUNDS = 50

#: Tiers the concurrency group uses, one per lane, alternating by round. Short
#: enough that 100 requests finish in reasonable time and long enough that a
#: cross-talk bug cannot hide in a one-token reply.
CONCURRENCY_TIERS: tuple[int, ...] = (60, 300)

#: Same fixed system message as MYS-2498: both core groups see the same prefix,
#: so the only difference between them is the history.
SYSTEM_PROMPT = base.SYSTEM_PROMPT

#: Identical sampling shape for every request in the run. On this board the
#: bmodel's lm_head fuses argmax, so `supports_sampling` is false and these do
#: not change the output (see the MYS-2498 suite's note); they are sent so every
#: request has one recorded shape and the run stays meaningful on a model whose
#: sampling is real.
PARAMS: dict = dict(base.PARAMS)

#: Readiness probe: requests fired while the model is loading. The probe keeps
#: firing for the whole load window rather than sleeping, because "how many
#: attempts were refused" is itself evidence that the window was really hit.
READINESS_INTERVAL_S = 0.25
READINESS_MAX_ATTEMPTS = 600

#: The probe's request is a fixed, tiny prompt at its own tier.
#:
#: A 30-character prompt is the shortest that still carries a word list, and its
#: template has room for a *two*-character round number and nothing more: "第9轮。"
#: plus the ask, the "材料：" label and a material list. Numbering the probe's
#: rounds 900+ (as this suite's other groups do) makes the head grow past the
#: budget and `build_prompt` correctly refuses with "leaves no room for a material
#: list". The probe therefore uses ONE constant prompt, sent unchanged on every
#: attempt -- which is also the right experimental design: the only thing that
#: varies between attempts is the model's state, not the input.
READINESS_TIER = 30
READINESS_ROUND = 1

KEY_NAME_DEFAULT = "MYS-2501-stability"


def tier_plan() -> list[tuple[int, int]]:
    """``(length, count)`` per tier -- the exact matrix, in tier order.

    The counts are derived, not typed: 12 tiers, 1000 requests, 84 for the first
    four and 83 for the remaining eight. The sum is asserted by the unit tests,
    which is what keeps "1000 次" from becoming a rounded claim.
    """
    out: list[tuple[int, int]] = []
    for index, length in enumerate(TIERS):
        out.append((length,
                    REQUESTS_PER_TIER_SHORT if index < SHORT_TIER_COUNT
                    else REQUESTS_PER_TIER_LONG))
    return out


def core_total() -> int:
    return sum(count for _length, count in tier_plan())


def noctx_cycle(turns: int | None = None) -> list[int]:
    """The ten tiers one context session walks, and one no-context cycle.

    A function rather than a constant so the matrix is read when a run starts
    instead of when the module is imported. That is what lets the tests shrink
    the matrix (``monkeypatch.setattr(ext, "TIERS", ...)``) and still exercise the
    real ``main`` -- and it keeps :func:`context_session_plan` honest if the tier
    list ever changes length at run time.

    Repeating this cycle is what makes the two core groups' *new input* identical
    turn by turn: request ``cycle*len(cycle) + turn`` of the no-context group
    sends exactly the text that turn of every context session sends, so the only
    difference between the groups is the history.
    """
    return list(TIERS[:(CONTEXT_TURNS if turns is None else turns)])


def nocxt_plan(mode: str = "cycle") -> list[int]:
    """The tier of each no-context request, in send order.

    The counts are fixed by the task card -- 84 requests at each of the four
    shortest tiers, 83 at each of the other eight, 1000 in total -- and "连续循环"
    (continuous cycling) is how they are produced:

    ``"cycle"`` (the default, and what the run uses)
        Cycle the 12 tiers in order. 83 full cycles give every tier 83 requests
        (996); the 84th request at each of the four shortest tiers makes up the
        remaining four. The first cycle is also the ten-tier ladder a context
        session walks, so the no-context group's first ten requests are
        byte-identical in input to any session's ten turns (see
        :func:`context_session_plan`).

    ``"tiered"``
        All 83/84 requests of one tier together, then the next. Same set of
        requests, different order; useful when watching one tier's behaviour.

    Both orders send exactly the tier plan; only the sequence differs.
    """
    if mode == "tiered":
        plan: list[int] = []
        for length, count in tier_plan():
            plan.extend([length] * count)
        return plan
    if mode != "cycle":
        raise ValueError(f"unknown nocxt order {mode!r}")
    plan: list[int] = []
    full_cycles, remainder = divmod(core_total(), len(TIERS))
    for _ in range(full_cycles):
        plan.extend(TIERS)
    # The remainder goes to the shortest tiers, which is where the extra request
    # in the 84/83 split lives.
    plan.extend(TIERS[:remainder])
    return plan


def context_session_plan(sessions: int | None = None,
                         turns: int | None = None) -> list[list[int]]:
    """The tier each turn of each session uses.

    Every session walks :func:`noctx_cycle` -- the same ten lengths, in the same
    order, as one no-context cycle. The two long tiers (1000, 1200) are exercised
    by the no-context group only: a session long enough to reach them would make
    every later turn a 100k-token prefill, which measures the prefill path rather
    than stability.
    """
    sessions = CONTEXT_SESSIONS if sessions is None else sessions
    turns = CONTEXT_TURNS if turns is None else turns
    ladder = noctx_cycle(turns)
    if len(ladder) != turns:
        raise ValueError(f"{turns} turns need {turns} tiers, have {len(ladder)}")
    return [list(ladder) for _ in range(sessions)]


def tier_counts(plan: Sequence[int]) -> dict[int, int]:
    """``{tier: count}`` for a send-order plan -- what the report checks against."""
    counts: dict[int, int] = {}
    for length in plan:
        counts[length] = counts.get(length, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
def html_escape(value) -> str:
    """Escape a value for HTML text and attribute context.

    ``quote=True`` covers attributes, and the single quote is escaped too so the
    same function is safe inside a JS string literal in an attribute. Model
    output is attacker-influenced text on a page an operator opens: it must never
    be able to introduce an element, and it never can through this.
    """
    return html.escape("" if value is None else str(value), quote=True)


def js_json(value) -> str:
    """JSON for embedding inside a ``<script>`` block.

    ``</script>`` inside a string would end the block early, so ``<`` is escaped
    to its JSON unicode form -- valid JSON, inert HTML. This is the only correct
    way to ship server data into inline JS; ``json.dumps`` alone is not.
    """
    return (json.dumps(value, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def percentile(values: Iterable[float], q: float) -> float | None:
    """The ``q``-th percentile (0..1) by linear interpolation.

    Deliberately the same definition ``numpy.percentile`` uses by default, so a
    reader can check a p95 by hand or in another tool and get the same number.
    Returns ``None`` for an empty sample rather than 0, so "not measured" never
    reads as "instant".
    """
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * q
    low = int(pos)
    high = min(low + 1, len(clean) - 1)
    frac = pos - low
    return clean[low] + (clean[high] - clean[low]) * frac


def spread(values: Iterable[float]) -> dict:
    """min / median / p95 / max over the non-``None`` values.

    The MYS-2498 suite reported min/median/max; MYS-2501 asks for p95 as well,
    because with 1000 samples the far end of a latency distribution is where a
    queueing problem shows up and the maximum alone cannot say whether it was one
    outlier or a systematically long tail.
    """
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"n": 0, "min": None, "median": None, "p95": None, "max": None}
    return {
        "n": len(clean),
        "min": round(min(clean), 4),
        "median": round(statistics.median(clean), 4),
        "p95": round(percentile(clean, 0.95), 4),
        "max": round(max(clean), 4),
    }


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
@dataclass
class TimelineEntry:
    """One phase boundary or anomaly, as the report's timeline tab shows it."""

    at: float
    kind: str            # "phase" | "anomaly" | "note"
    label: str
    detail: str = ""
    group: str | None = None
    count: int | None = None

    def as_dict(self) -> dict:
        return {
            "at": self.at,
            "iso": datetime.fromtimestamp(self.at, tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "group": self.group,
            "count": self.count,
        }


class Timeline:
    """Append-only, thread-safe list of phases and anomalies.

    Written to ``timeline.jsonl`` line by line as it happens, for the same reason
    the round rows are: a run that dies mid-flight must still leave a record of
    where it got to.
    """

    def __init__(self, path: Path | None = None):
        self.entries: list[TimelineEntry] = []
        self._lock = threading.Lock()
        self._fh = path.open("w", encoding="utf-8") if path else None

    def add(self, kind: str, label: str, detail: str = "", *,
            group: str | None = None, count: int | None = None,
            at: float | None = None) -> TimelineEntry:
        entry = TimelineEntry(at=at if at is not None else time.time(),
                              kind=kind, label=label, detail=detail,
                              group=group, count=count)
        with self._lock:
            self.entries.append(entry)
            if self._fh is not None:
                self._fh.write(json.dumps(entry.as_dict(), ensure_ascii=False) + "\n")
                self._fh.flush()
        return entry

    def anomaly(self, label: str, detail: str = "", **kw) -> TimelineEntry:
        return self.add("anomaly", label, detail, **kw)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


# ---------------------------------------------------------------------------
# Device sampler
# ---------------------------------------------------------------------------
class Sampler:
    """Device and worker counters every ``interval`` seconds, in a thread.

    Why a thread rather than a poll between requests: the interesting moments are
    *inside* a phase (the NPU heap climbing through a long prefill, the queue
    depth during the concurrency run), and sampling only between requests would
    systematically miss them. It only ever issues reads, so it cannot perturb
    what it measures beyond the HTTP cost of two admin GETs.

    A sample failure is recorded as a gap, not raised: a service that stops
    answering `/api/stats` during a load is exactly what the readiness phase
    expects, and the report should show "no sample" rather than a crash.
    """

    def __init__(self, http: base.Http, interval: float = 5.0):
        self.http = http
        self.interval = interval
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.errors = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 10)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.interval)

    def sample_once(self) -> dict | None:
        """One sample; returns it, or ``None`` when the service did not answer."""
        at = time.time()
        try:
            status, stats = self.http.json("GET", "/api/stats", timeout=20)
        except (OSError, ValueError):
            status, stats = 0, {}
        if status != 200:
            with self._lock:
                self.errors += 1
                self.samples.append({"at": at, "ok": False, "http": status})
            return None
        device = stats.get("device") or {}
        memory = device.get("memory") or {}
        npu = device.get("npu") or {}
        smi = npu.get("smi") or {}
        workers = stats.get("workers") or {}
        worker_row = {}
        for model_id, payload in workers.items():
            if isinstance(payload, dict):
                worker_row = {
                    "model": model_id,
                    "active": payload.get("active"),
                    "queued": payload.get("queued"),
                    "total_requests": payload.get("total_requests"),
                    "failed_requests": payload.get("failed_requests"),
                    "cancelled_requests": payload.get("cancelled_requests"),
                    "rejected_requests": payload.get("rejected_requests"),
                    "memory_waits": payload.get("memory_waits"),
                    "cache_entries": (payload.get("cache") or {}).get("entries"),
                    "cache_bytes": (payload.get("cache") or {}).get("bytes"),
                    "prompt_tokens": payload.get("prompt_tokens"),
                    "completion_tokens": payload.get("completion_tokens"),
                }
                break
        usage = stats.get("usage") or {}
        sample = {
            "at": at,
            "ok": True,
            "http": status,
            "cpu_percent": device.get("cpu_percent"),
            "load_average": device.get("load_average"),
            "mem_total": memory.get("total_bytes"),
            "mem_available": memory.get("available_bytes"),
            "mem_used": memory.get("used_bytes"),
            "tpu_util": smi.get("tpu_util_percent"),
            "npu_mem_used": smi.get("mem_used_bytes"),
            "npu_mem_total": smi.get("mem_total_bytes"),
            "temperatures": device.get("temperatures"),
            "service_requests": usage.get("requests"),
            "service_prompt_tokens": usage.get("prompt_tokens"),
            "worker": worker_row,
        }
        with self._lock:
            self.samples.append(sample)
        return sample

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.samples)


# ---------------------------------------------------------------------------
# Rounds: the shared row, plus the extra columns this matrix needs
# ---------------------------------------------------------------------------
@dataclass
class Round(base.Round):
    """A ``base.Round`` with the extra coordinates MYS-2501 reports on.

    ``session`` and ``turn`` distinguish the 100 sessions of the context group
    from a single 1000-turn conversation; keeping them explicit is what makes
    the report unable to blur the two. ``attempt`` is the readiness probe's
    counter, and ``expected_status`` is the HTTP code the phase requires (409
    during a load, 200 after it) so the verdict can compare rather than assume.
    """

    session: int | None = None
    turn: int | None = None
    lane: int | None = None
    attempt: int | None = None
    expected_status: int | None = None
    status_ok: bool | None = None
    latency_s: float | None = None
    request_kind: str = "stream"     # "stream" | "nonstream" | "console"

    def as_row(self) -> dict:
        row = super().as_row()
        row["status_ok"] = self.status_ok
        row["request_kind"] = self.request_kind
        return row


def new_round(group: str, prompt: base.Prompt, messages: list[dict], **kw) -> Round:
    row = Round(group=group, round_index=prompt.round_index, tier=prompt.length,
                input_text=prompt.text, input_chars=base.chars(prompt.text),
                input_sha256=base.sha256(prompt.text),
                context_messages=len(messages),
                expected_count=prompt.expected_count,
                expected_recall=prompt.expected_recall, marker=prompt.marker)
    for key, value in kw.items():
        setattr(row, key, value)
    return row


# ---------------------------------------------------------------------------
# HTTP surfaces
# ---------------------------------------------------------------------------
def chat_stream(http: base.Http, key: str, model: str, prompt: base.Prompt,
                group: str, messages: list[dict], raw_dir: Path,
                timeout: float = 1800.0, raw_token: str | None = None,
                **kw) -> Round:
    """One streaming ``/v1/chat/completions`` request, captured whole.

    Delegates to the MYS-2498 implementation and upgrades the row, so the SSE
    parsing, TTFT measurement and grading stay in exactly one place. A failure
    is a row with ``error`` set, never an exception.

    ``raw_token`` renames the raw body file after capture. It exists because the
    base suite names raw files ``<group>-<round>.sse``, and the context group
    here reuses round numbers 1..10 across 100 sessions -- without a token, every
    session's turn 3 would overwrite the previous session's turn 3 and the raw
    evidence for 900 of the 1000 context requests would be lost.
    """
    row = base.chat_once(http, key, model, prompt, group, messages, raw_dir, timeout)
    if raw_token:
        produced = raw_dir / f"{group}-{prompt.round_index}.sse"
        if produced.is_file():
            produced.replace(raw_dir / f"{group}-{raw_token}.sse")
    out = Round(**{f: getattr(row, f) for f in base.Round.__dataclass_fields__})
    for k, v in kw.items():
        setattr(out, k, v)
    out.expected_status = out.expected_status or 200
    out.status_ok = out.http_status == out.expected_status
    out.latency_s = out.total_s
    return out


def chat_nonstream(http: base.Http, key: str, model: str, prompt: base.Prompt,
                   group: str, messages: list[dict], raw_dir: Path,
                   timeout: float = 600.0, **kw) -> Round:
    """One non-streaming completion: the other half of the OpenAI surface.

    The load-window probe has to cover both shapes because they take different
    paths through the route (the streaming one wraps a generator in a
    ``StreamingResponse``, so its refusal can arrive as a 409 *before* any bytes
    are sent -- but that ordering is a property of the code, not a guarantee,
    which is exactly why it is measured).
    """
    row = new_round(group, prompt, messages, request_kind="nonstream", **kw)
    payload = {"model": model, "messages": messages, "stream": False,
               "seed": base.SEED, **PARAMS}
    req = urllib.request.Request(
        http.url("/v1/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "Authorization": f"Bearer {key}"})
    body: bytes = b""
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
        if exc.code >= 400:
            row.error = f"HTTP {exc.code}: {body.decode('utf-8', 'replace')[:2000]}"
    except Exception as exc:  # noqa: BLE001 - every failure is a row
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"
    raw_path = raw_dir / f"{group}-{prompt.round_index}-{row.request_kind}.json"
    raw_path.write_bytes(body or b"")
    obj: dict = {}
    try:
        obj = json.loads(body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        obj = {}
    if row.http_status and row.http_status < 400:
        choice = (obj.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        row.output = message.get("content") or ""
        row.req_id = base.request_id_of(obj.get("id"))
        row.finish_reason = choice.get("finish_reason")
        prompt_tokens, completion_tokens, cached = base.usage_tokens(
            obj.get("usage") or {})
        row.prompt_tokens = prompt_tokens or None
        row.completion_tokens = completion_tokens or None
        row.cached_tokens = cached if obj.get("usage") else None
        row.stream_done = True
        if not row.output and row.error is None:
            row.error = "empty output"
        graded = base.grade(prompt, row.output, group)
        row.count_ok = graded["count_ok"]
        row.recall_ok = graded["recall_ok"]
        row.marker_ok = graded["marker_ok"]
    if row.finished_at and row.started_at:
        row.total_s = round(row.finished_at - row.started_at, 6)
        row.latency_s = row.total_s
    row.expected_status = row.expected_status or 200
    row.status_ok = row.http_status == row.expected_status
    return row


def chat_console(http: base.Http, model: str, prompt: base.Prompt, group: str,
                 raw_dir: Path, timeout: float = 600.0, **kw) -> Round:
    """``/api/chat/stream``: the console's own SSE route, authenticated by cookie.

    A third inference surface, and the one an operator would actually use when
    the OpenAI path looks fine but the UI does not. Its response shape is
    ``{"text": ...}`` rather than an OpenAI ``choices`` array, so it gets its own
    parser instead of being forced through ``parse_sse``.
    """
    row = new_round(group, prompt, [{"role": "user", "content": prompt.text}],
                    request_kind="console", **kw)
    payload = {"model": model, "prompt": prompt.text, "max_tokens": 64,
               "temperature": 0.0, "enable_thinking": False}
    req = urllib.request.Request(
        http.url("/api/chat/stream"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Cache-Control": "no-cache"})
    row.started_at = time.time()
    collected: list[str] = []
    first_token_at: float | None = None
    try:
        with http.open(req, timeout) as resp:
            row.http_status = resp.status
            while True:
                line = resp.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")
                collected.append(decoded)
                if first_token_at is None and decoded.startswith("data:") \
                        and "[DONE]" not in decoded:
                    try:
                        obj = json.loads(decoded[5:].strip())
                    except (json.JSONDecodeError, ValueError):
                        obj = {}
                    if obj.get("text"):
                        first_token_at = time.time()
        row.finished_at = time.time()
    except urllib.error.HTTPError as exc:
        row.http_status = exc.code
        row.finished_at = time.time()
        row.error = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:2000]}"
    except Exception as exc:  # noqa: BLE001
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"
    raw = "".join(collected)
    (raw_dir / f"{group}-{prompt.round_index}-console.sse").write_text(raw, encoding="utf-8")
    text = ""
    done = False
    usage: dict = {}
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload_line = line[5:].strip()
        if payload_line == "[DONE]":
            done = True
            continue
        try:
            obj = json.loads(payload_line)
        except json.JSONDecodeError:
            continue
        if obj.get("text"):
            text += obj["text"]
        if obj.get("done"):
            done = True
            usage = obj
    row.output = text
    row.stream_done = done
    row.finish_reason = usage.get("finish_reason")
    row.prompt_tokens = usage.get("prompt_tokens") or None
    row.completion_tokens = usage.get("completion_tokens") or None
    row.cached_tokens = usage.get("cached_tokens")
    row.server_ttft_s = usage.get("first_token_latency_s")
    row.decode_tps = usage.get("decode_tps")
    if row.error is None and row.http_status and row.http_status < 400:
        if not text:
            row.error = "empty output"
        elif not done:
            row.error = "stream ended without [DONE]"
        graded = base.grade(prompt, text, group)
        row.count_ok = graded["count_ok"]
        row.recall_ok = graded["recall_ok"]
        row.marker_ok = graded["marker_ok"]
    if row.finished_at and row.started_at:
        row.total_s = round(row.finished_at - row.started_at, 6)
        row.latency_s = row.total_s
        if first_token_at:
            row.ttft_s = round(first_token_at - row.started_at, 6)
    row.expected_status = row.expected_status or 200
    row.status_ok = row.http_status == row.expected_status
    return row


# ---------------------------------------------------------------------------
# The core groups
# ---------------------------------------------------------------------------
def concurrency_marker(lane: int, round_index: int, lanes: int) -> str:
    """A unique, letters-only marker for one concurrent request.

    Two constraints, both load-bearing:

    * **Letters only.** The reply is graded by pulling integers out of it, so a
      digit in the marker would look like a second, conflicting count and turn a
      correct answer into a failure.
    * **Unique across the whole run, not just within a round.** Cross-talk is
      detected by looking for *another* request's marker in a reply, so a marker
      reused by a later round would make that later round's reply look like
      cross-talk from an earlier one. Base-26 over the request's global index
      gives 676 distinct three-letter-suffixed markers, which covers the 100
      requests of this matrix (and up to 26 lanes x 676 rounds) with room to
      spare.

    The lane letter comes first so a human reading the evidence can see which
    lane a marker belongs to at a glance.
    """
    if lane < 1 or lanes > 26:
        raise ValueError(f"lane {lane} of {lanes} cannot be encoded in letters")
    index = (round_index - 1) * lanes + (lane - 1)
    high, low = divmod(index, 26)
    return f"KX{chr(65 + lane - 1)}{chr(65 + high)}{chr(65 + low)}"


class Runner:
    """Drives one run: writes rows as they happen, keeps the timeline.

    Extracted from ``main`` so the phases are callable (and testable) one at a
    time; the module-level ``main`` is then only argument parsing and wiring.
    """

    def __init__(self, http: base.Http, key: str, model: str, evidence: Path,
                 raw_dir: Path, timeline: Timeline, timeout: float = 1800.0):
        self.http = http
        self.key = key
        self.model = model
        self.evidence = evidence
        self.raw_dir = raw_dir
        self.timeline = timeline
        self.timeout = timeout
        self.rounds: list[Round] = []
        self.readiness: dict = {}
        self.jsonl = (evidence / "rounds.jsonl").open("w", encoding="utf-8")
        self._lock = threading.Lock()

    # -- row plumbing ----------------------------------------------------
    def record(self, row: Round) -> Round:
        with self._lock:
            self.rounds.append(row)
            self.jsonl.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
            self.jsonl.flush()
        mark = ""
        if row.count_ok is not None:
            mark += "计数✓" if row.count_ok else "计数✗"
        if row.recall_ok is not None:
            mark += "回忆✓" if row.recall_ok else "回忆✗"
        if not row.status_ok:
            mark += f"状态✗({row.http_status})"
        tail = (row.output or "").strip().replace("\n", " ")[:24]
        where = ""
        if row.session is not None:
            where = f"s{row.session:>3}t{row.turn:<2}"
        elif row.lane is not None:
            where = f"L{row.lane}r{row.round_index:<3}"
        elif row.attempt is not None:
            where = f"a{row.attempt:<3}"
        print(f"  {row.group:<14} {where:<8} {row.input_chars:>4}字 "
              f"HTTP {row.http_status if row.http_status is not None else '-'} "
              f"{(row.total_s if row.total_s is not None else 0):>7.2f}s "
              f"pt={row.prompt_tokens or '-'} ct={row.completion_tokens or '-'} "
              f"{mark} out={tail!r}"
              + (f" ERR {row.error[:60]}" if row.error else ""), flush=True)
        return row

    def close(self) -> None:
        self.jsonl.close()

    # -- phases ----------------------------------------------------------
    def run_nocxt(self, plan: Sequence[int] | None = None,
                  tiers: Sequence[int] | None = None) -> None:
        """1000 independent requests: system + one user message, nothing else.

        Ordered by the tier plan -- 84 requests at each of the four shortest
        tiers, 83 at each of the other eight -- so the run is reproducible
        request by request rather than "1000 random lengths". Each request uses
        its own round index, which is what makes its prompt text and its expected
        answer distinct from every other request's.
        """
        order = list(nocxt_plan() if plan is None else plan)
        tiers = list(TIERS if tiers is None else tiers)
        self.timeline.add("phase", "开始无上下文组",
                          f"计划 {len(order)} 次独立请求（按 "
                          f"{len(noctx_cycle())} 档循环）", group="nocxt")
        index = 0
        for length in order:
            index += 1
            turn = (index - 1) % len(tiers) + 1
            cycle = (index - 1) // len(tiers)
            prompt = base.build_prompt(length, turn, lengths=tiers,
                                       recall_target="previous",
                                       variant=cycle + 1,
                                       allow_recall=turn <= CONTEXT_TURNS)
            messages = base.context_messages(SYSTEM_PROMPT, [], prompt.text)
            row = chat_stream(self.http, self.key, self.model, prompt, "nocxt",
                              messages, self.raw_dir, self.timeout,
                              raw_token=f"n{index:04d}", session=None,
                              turn=turn)
            self.record(row)
            if not row.status_ok or row.error:
                self.timeline.anomaly(
                    "无上下文请求异常",
                    f"第 {index} 次（{length} 字）："
                    f"HTTP {row.http_status} {row.error or ''}".strip(),
                    group="nocxt")
        self.timeline.add("phase", "无上下文组结束", f"共 {index} 次", group="nocxt",
                          count=index)

    def run_cxt(self, plan: Sequence[Sequence[int]] | None = None) -> None:
        """1000 requests in 100 independent sessions of 10 turns each.

        Each session resends its whole history on every turn, exactly as the
        MYS-2498 context group did -- so the history is really used, not
        referenced. Sessions are independent: session 7's history has nothing to
        do with session 6's, which is what keeps 1000 requests from becoming one
        100k-token prefill (see the module docstring).

        From the 60-character tier on, each turn plants a numbered fact; from the
        300 tier on it also asks for the *previous* turn's keyword. Asking about
        the previous turn rather than a random earlier one makes round 10's
        question the same shape as round 5's, so "recall rate" is one number
        about one kind of question instead of an average over different ones.
        """
        plan = list(context_session_plan() if plan is None else plan)
        self.timeline.add("phase", "开始带上下文组",
                          f"{len(plan)} 个独立会话 × 每会话 "
                          f"{len(plan[0]) if plan else 0} 轮",
                          group="cxt")
        for session_index, ladder in enumerate(plan, start=1):
            history: list[dict] = []
            for turn, length in enumerate(ladder, start=1):
                prompt = base.build_prompt(length, turn, lengths=ladder,
                                           recall_target="previous",
                                           variant=session_index)
                messages = base.context_messages(SYSTEM_PROMPT, history, prompt.text)
                row = chat_stream(self.http, self.key, self.model, prompt, "cxt",
                                  messages, self.raw_dir, self.timeout,
                                  raw_token=f"s{session_index:03d}t{turn:02d}",
                                  session=session_index, turn=turn)
                self.record(row)
                # The assistant turn enters the history exactly as received.
                history = base.append_turn(history, prompt.text, row.output)
                if not row.status_ok or row.error:
                    self.timeline.anomaly(
                        "带上下文请求异常",
                        f"会话 {session_index} 第 {turn} 轮（{length} 字）："
                        f"HTTP {row.http_status} {row.error or ''}".strip(),
                        group="cxt")
        self.timeline.add("phase", "带上下文组结束",
                          f"{len(plan)} 会话 × {len(plan[0]) if plan else 0} 轮",
                          group="cxt",
                          count=sum(len(ladder) for ladder in plan))

    def run_concurrency(self, lanes: int | None = None,
                        rounds: int | None = None,
                        tiers: Sequence[int] | None = None) -> None:
        """2 lanes x 50 rounds: one request per lane, fired together.

        Two lanes, not three: the service is configured with
        ``max_concurrent_per_model=2``, and the point is to keep both slots busy
        and see whether they stay isolated, not to measure what happens past the
        configured limit. Every request carries a unique letter marker it must
        echo, and a reply carrying another lane's marker is cross-talk.

        Rounds are sequential: round N+1 starts only when both of round N's
        requests have finished, so the batch boundaries are real and a slow
        request shows up as a slow *round* rather than as an untracked overlap.
        """
        lanes = CONCURRENCY_LANES if lanes is None else lanes
        rounds = CONCURRENCY_ROUNDS if rounds is None else rounds
        tiers = list(CONCURRENCY_TIERS if tiers is None else tiers)
        if lanes > 26:
            raise ValueError(f"at most 26 lanes; got {lanes}")
        self.timeline.add("phase", "开始并发组",
                          f"{lanes} 路 × {rounds} 轮", group="conc")
        for round_index in range(1, rounds + 1):
            prompts: list[tuple[int, base.Prompt]] = []
            for lane in range(1, lanes + 1):
                length = tiers[(round_index + lane) % len(tiers)]
                marker = concurrency_marker(lane, round_index, lanes)
                prompts.append((lane, base.build_prompt(
                    length, 1000 + round_index * 10 + lane, lengths=TIERS,
                    marker=marker, variant=lane)))
            started = time.time()
            results: list[Round] = []
            lock = threading.Lock()

            def work(lane: int, prompt: base.Prompt) -> None:
                client = base.Http(self.http.base, timeout=self.timeout)
                try:
                    row = chat_stream(client, self.key, self.model, prompt, "conc",
                                      [{"role": "user", "content": prompt.text}],
                                      self.raw_dir, self.timeout,
                                      raw_token=f"r{round_index:03d}L{lane}",
                                      lane=lane, session=None, turn=None)
                except Exception as exc:  # noqa: BLE001 - a thread must not die silently
                    row = new_round("conc", prompt,
                                    [{"role": "user", "content": prompt.text}], lane=lane)
                    row.error = f"{type(exc).__name__}: {exc}"
                with lock:
                    results.append(row)

            threads = [threading.Thread(target=work, args=(lane, prompt))
                       for lane, prompt in prompts]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            elapsed = time.time() - started
            markers = {p.marker: lane for lane, p in prompts}
            for row in results:
                foreign = [m for m, lane in markers.items()
                           if m != row.marker and m in (row.output or "")]
                row.cross_talk = bool(foreign)
                if foreign:
                    row.error = row.error or f"cross-talk: reply carried {','.join(foreign)}"
            for row in results:
                self.record(row)
            if any(r.cross_talk for r in results):
                self.timeline.anomaly("并发串话", f"第 {round_index} 轮", group="conc")
            if any(not r.status_ok or r.error for r in results):
                self.timeline.anomaly(
                    "并发请求异常",
                    f"第 {round_index} 轮，{elapsed:.1f}s：" +
                    "; ".join(f"HTTP {r.http_status} {r.error or ''}".strip()
                              for r in results if not r.status_ok or r.error),
                    group="conc")
        self.timeline.add("phase", "并发组结束", f"{lanes * rounds} 次",
                          group="conc", count=lanes * rounds)

    # -- readiness -------------------------------------------------------
    def run_readiness(self, password: str, model: str,
                      load_timeout: float = 900.0) -> dict:
        """Stop, reload, and hammer every inference surface while it loads.

        The claim being tested is narrow and checkable: **from the moment the
        load starts until the model is ready, every inference request is refused
        with 409, none of them reaches the worker, and none of them writes a
        record.** So the probe does three things at once during the window:

          * polls ``GET /api/models`` for this model's ``loaded``/``operation``;
          * fires ``/v1/chat/completions`` stream and non-stream, and
            ``/api/chat/stream``, as fast as the interval allows;
          * records the worker's ``generate`` counter and the record count
            before and after, so "did any request get in" is answered by the
            worker and the database rather than by the HTTP status alone.

        SIGTERM only. ``kill -9`` on a process holding the NPU heap is what
        wedges the board, and the whole point of this phase is to observe the
        *normal* load path -- injecting a fake loading state would measure the
        fake.
        """
        info: dict = {"started_at": time.time(), "attempts": 0, "by_surface": {},
                      "windows": [], "stopped": False, "loaded": False,
                      "refused": 0, "admitted": 0, "other": 0, "ready_at": None}
        self.timeline.add("phase", "开始 readiness 专项",
                          "正常停止 / 重新加载 128k 模型，加载窗口内持续探测",
                          group="readiness")

        # The record database outlives a reload; the worker process does not. So
        # the record count is compared before/after (a delta), while the worker's
        # own generate counter is read *absolutely* once the new worker is ready:
        # a fresh worker starts at zero, so "0" after the window is exactly the
        # statement "no inference reached it", and subtracting the old worker's
        # count would produce a meaningless negative number.
        before_records = self._record_total()
        info["generate_before_unload"] = self._worker_generate_count()
        info["records_before"] = before_records

        # 1. Normal unload, then load, over the admin API. An unload rather than
        #    a bare load is what makes the window long enough to hit reliably.
        status, _ = self.http.json("POST", f"/api/models/{model}/unload",
                                   timeout=180)
        info["unload_status"] = status
        if status != 200:
            info["error"] = f"unload refused: HTTP {status}"
            self.timeline.anomaly("readiness 卸载失败", info["error"], group="readiness")
            return info

        # 2. Fire the load and probe while it runs. The load request itself is
        #    issued from a thread so the probe can run in this one.
        load_result: dict = {}

        def load() -> None:
            started = time.time()
            try:
                code, body = self.http.json("POST", f"/api/models/{model}/load",
                                            timeout=load_timeout)
            except Exception as exc:  # noqa: BLE001
                code, body = 0, {"error": f"{type(exc).__name__}: {exc}"}
            load_result.update({"status": code, "s": round(time.time() - started, 2),
                                "body": body if code != 200 else None})

        load_thread = threading.Thread(target=load, name="model-load", daemon=True)
        load_thread.start()

        # 3. Probe the three surfaces until the model reports ready.
        #
        #    A separate client so a probe timeout cannot poison the shared
        #    session -- but it must *authenticate* first. `/api/chat/stream` is
        #    cookie-authenticated, and an un-logged-in client would answer 401
        #    for every attempt: the phase would then report "nothing admitted"
        #    while having measured nothing at all on that surface. (Caught by the
        #    live test, which asserted the console bucket must be all-409.)
        probe_client = base.Http(self.http.base, timeout=120)
        probe_login = probe_client.login(password)
        if probe_login != 200:
            info["error"] = (f"readiness 探测客户端登录失败（HTTP {probe_login}）；"
                             "console 接口无法有效验证")
            self.timeline.anomaly("readiness 探测登录失败",
                                  f"HTTP {probe_login}", group="readiness")
            return info
        attempt = 0
        observed_loading = False
        while attempt < READINESS_MAX_ATTEMPTS:
            attempt += 1
            checked_at = time.time()
            loaded, operation = self._model_state(model)
            snapshot = {"at": time.time(), "attempt": attempt, "loaded": loaded,
                        "operation": operation}
            if operation == "loading" or (loaded is False and operation is not None):
                observed_loading = True
            if loaded and operation is None:
                info["windows"].append({**snapshot, "phase": "ready"})
                info["load_ready_after_s"] = round(
                    time.time() - info["started_at"], 2)
                # The instant this probe *observed* readiness, used to decide
                # whether a non-409 response was really inside the window. The
                # model's own ``loaded_at`` is preferred when the admin API
                # reports it (it is the exact instant), with this observation as
                # the fallback.
                info["ready_observed_at"] = checked_at
                break
            # One fixed prompt for the whole window: the variable under test is
            # the model's state, not the input. (The three surfaces still differ
            # in route and authentication, which is the point of covering all
            # three.)
            prompt = base.build_prompt(READINESS_TIER, READINESS_ROUND,
                                       lengths=TIERS)
            messages = base.context_messages(SYSTEM_PROMPT, [], prompt.text)
            for surface, call in (
                ("stream", lambda: chat_stream(
                    probe_client, self.key, self.model, prompt, "readiness-stream",
                    messages, self.raw_dir, 120, attempt=attempt, expected_status=409)),
                ("nonstream", lambda: chat_nonstream(
                    probe_client, self.key, self.model, prompt, "readiness-nonstream",
                    messages, self.raw_dir, 120, attempt=attempt, expected_status=409)),
                ("console", lambda: chat_console(
                    probe_client, self.model, prompt, "readiness-console",
                    self.raw_dir, 120, attempt=attempt, expected_status=409)),
            ):
                # Re-check readiness immediately before each surface. One poll
                # per iteration lets the model finish loading between the poll
                # and the third request, which produces a 200 that belongs to the
                # window's other side -- and every such straddle has to be
                # explained away afterwards. Polling first makes the boundary
                # tight: a request is only fired while readiness was just
                # re-confirmed false. The extra GETs are ~10 ms each against a
                # 66-second load.
                if surface != "stream":
                    still_loaded, still_operation = self._model_state(model)
                    if still_loaded and still_operation is None:
                        info.setdefault("ready_observed_at", time.time())
                        info.setdefault("boundary_hit_on", surface)
                        break
                try:
                    row = call()
                except Exception as exc:  # noqa: BLE001
                    row = new_round(f"readiness-{surface}", prompt, messages,
                                    attempt=attempt, expected_status=409)
                    row.error = f"{type(exc).__name__}: {exc}"
                    row.status_ok = False
                self.record(row)
                bucket = info["by_surface"].setdefault(
                    surface, {"attempts": 0, "refused": 0, "admitted": 0,
                              "other": 0, "records": 0, "after_ready": 0})
                bucket["attempts"] += 1
                info["attempts"] += 1
                if row.http_status == 409:
                    bucket["refused"] += 1
                    info["refused"] += 1
                elif row.http_status == 200:
                    bucket["admitted"] += 1
                    info["admitted"] += 1
                else:
                    bucket["other"] += 1
                    info["other"] += 1
                if row.req_id:
                    bucket["records"] += 1
                if row.http_status is not None and row.http_status != 409 \
                        and row.http_status < 500:
                    entry = {"surface": surface, "attempt": attempt,
                             "http": row.http_status, "error": row.error,
                             "started_at": row.started_at}
                    info.setdefault("unexpected", []).append(entry)
                    # A refusal is the rollout of a 409; anything else inside the
                    # window is a defect. Note it now, and decide whether it was
                    # inside the window at the end (see ``ready_at`` below) --
                    # the surface order means the model can finish loading
                    # between this iteration's readiness poll and its last
                    # request, which is not the service admitting anything early.
                    self.timeline.anomaly(
                        "加载窗口内出现非 409 响应",
                        f"{surface} attempt {attempt}: HTTP {row.http_status}",
                        group="readiness")
            info["windows"].append({**snapshot})
            if not load_thread.is_alive() and attempt > 4 and not loaded:
                # The load finished but the model does not read as loaded: a
                # failed load, which is itself a result worth reporting rather
                # than something to poll through.
                pass
            time.sleep(READINESS_INTERVAL_S)
        else:
            info["error"] = (f"模型在 {READINESS_MAX_ATTEMPTS} 次探测内未就绪；"
                            "未做任何强杀，需人工检查")

        load_thread.join(timeout=load_timeout + 30)
        info["load"] = load_result
        info["probe_login_status"] = probe_login
        info["observed_loading"] = observed_loading
        info["loaded_after"] = self._model_state(model)[0]
        info["loaded"] = bool(info["loaded_after"])
        info["attempts_during_loading"] = info["attempts"]
        info["generate_after_load_raw"] = self._worker_generate_count()
        info["records_after_loading_raw"] = self._record_total()

        # The counters are process- and table-wide, so they also include any
        # request the probe fired in an iteration whose *poll* still said
        # "loading" but which the model served once it became ready. Those are
        # legitimate post-ready successes -- the probe cannot observe readiness
        # inside an iteration -- so they are subtracted here by timestamp, and
        # listed, rather than being allowed to fail the gate. The subtraction is
        # reported so it is visible rather than hidden arithmetic.
        probe_rows = [r for r in self.rounds
                      if r.group.startswith("readiness")
                      and r.group != "readiness-after" and r.http_status == 200]
        post_ready = []
        for row in probe_rows:
            ready_hint = info.get("ready_observed_at")
            if row.started_at is not None and ready_hint is not None \
                    and row.started_at >= ready_hint:
                post_ready.append(row)
        info["post_ready_requests"] = [
            {"group": r.group, "attempt": r.attempt, "http": r.http_status,
             "req_id": r.req_id, "started_at": r.started_at} for r in post_ready]
        post_ready_records = sum(1 for r in post_ready if r.req_id)
        info["post_ready_records"] = post_ready_records

        generate_raw = info["generate_after_load_raw"]
        info["generate_after_load"] = (
            None if generate_raw is None else max(generate_raw - len(post_ready), 0))
        records_raw = info["records_after_loading_raw"]
        info["records_delta_loading_raw"] = (
            None if info["records_before"] is None or records_raw is None
            else records_raw - info["records_before"])
        info["records_delta_loading"] = (
            None if info["records_delta_loading_raw"] is None
            else max(info["records_delta_loading_raw"] - post_ready_records, 0))
        if post_ready:
            self.timeline.add(
                "note", "就绪瞬间被服务的探测请求",
                f"{len(post_ready)} 个请求在模型就绪后才被服务（其中 "
                f"{post_ready_records} 个落了记录）；已按时间戳从窗口计数中扣除，"
                "不视为加载期间放行", group="readiness", count=len(post_ready))

        # Which non-409 responses were genuinely inside the loading window?
        #
        # The probe polls readiness once per iteration and then fires three
        # requests. A 60-second load can finish between that poll and the third
        # request, so a 200 can legitimately belong to *after* the window. The
        # model's own ``loaded_at`` (or, failing that, the instant this probe
        # observed readiness) is what decides -- by timestamp, not by "which
        # request number was it".
        ready_at = self._model_loaded_at(model) or info.get("ready_observed_at")
        info["ready_at"] = ready_at
        inside: list[dict] = []
        outside: list[dict] = []
        for entry in info.get("unexpected") or []:
            started = entry.get("started_at")
            if ready_at is None or started is None:
                # Without a timestamp the only safe reading is "inside": an
                # unexplained 200 during this phase must not be waved away.
                inside.append(entry)
            elif started < ready_at:
                inside.append(entry)
            else:
                outside.append(entry)
        info["unexpected_inside_window"] = inside
        info["unexpected_after_ready"] = outside
        info["unexpected"] = inside
        info["admitted_inside_window"] = len(inside)
        if outside:
            self.timeline.add(
                "note", "加载完成瞬间的成功响应",
                f"{len(outside)} 个请求在模型就绪后才发出（就绪时刻 "
                f"{datetime.fromtimestamp(ready_at, tz=timezone.utc).isoformat(timespec='milliseconds') if ready_at else '未知'}），"
                "属于窗口之后的正常成功，不计入放行", group="readiness",
                count=len(outside))

        if info["generate_after_load"] not in (0, None):
            self.timeline.anomaly(
                "加载窗口内有请求进入 worker",
                f"新 worker 就绪时 generate 计数为 {info['generate_after_load']}"
                "（应为 0）", group="readiness")
        if info["records_delta_loading"] not in (0, None):
            self.timeline.anomaly(
                "加载窗口内写入了推理记录",
                f"记录总数增加 {info['records_delta_loading']}", group="readiness")
        if not observed_loading:
            self.timeline.anomaly(
                "未观察到 loading 状态",
                "探测期间 /api/models 从未报告 operation=loading；"
                "加载过快或状态未发布，readiness 结论不成立", group="readiness")

        # 4. Once ready: one short request must succeed and write exactly one
        #    record. The other half of the contract -- refusal during, service
        #    after -- and the half a green 409 count alone would not prove.
        prompt = base.build_prompt(READINESS_TIER, READINESS_ROUND, lengths=TIERS)
        messages = base.context_messages(SYSTEM_PROMPT, [], prompt.text)
        generate_before = self._worker_generate_count()
        records_before = self._record_total()
        row = chat_stream(self.http, self.key, self.model, prompt, "readiness-after",
                          messages, self.raw_dir, 300, attempt=0, expected_status=200)
        self.record(row)
        info["after"] = {
            "http": row.http_status, "req_id": row.req_id,
            "output_chars": len(row.output or ""), "error": row.error,
            "generate_before": generate_before,
            "generate_after": self._worker_generate_count(),
            "records_before": records_before,
            "records_after": self._record_total(),
        }
        after = info["after"]
        after["generate_delta"] = (
            None if after["generate_before"] is None or after["generate_after"] is None
            else after["generate_after"] - after["generate_before"])
        after["records_delta"] = (
            None if after["records_before"] is None or after["records_after"] is None
            else after["records_after"] - after["records_before"])
        info["stopped"] = True
        info["finished_at"] = time.time()
        self.timeline.add("phase", "readiness 专项结束",
                          f"加载窗口内 {info['attempts']} 次探测，加载完成后短请求 "
                          f"HTTP {row.http_status}", group="readiness",
                          count=info["attempts"])
        return info

    # -- service-side counters ------------------------------------------
    def _model_state(self, model: str) -> tuple[bool | None, str | None]:
        """``(loaded, operation)`` for one model, from the admin listing."""
        try:
            status, body = self.http.json("GET", "/api/models", timeout=30)
        except (OSError, ValueError):
            return None, None
        if status != 200:
            return None, None
        for entry in body.get("models") or []:
            if entry.get("id") == model:
                return bool(entry.get("loaded")), entry.get("operation")
        return None, None

    def _model_loaded_at(self, model: str) -> float | None:
        """The exact instant the service published ``loaded`` for ``model``.

        Preferred over the probe's own observation because it is the service's
        statement, not the client's sample: it is what distinguishes "the gate let
        a request through" from "the load finished while the probe was between
        requests".
        """
        try:
            status, body = self.http.json("GET", "/api/models", timeout=30)
        except (OSError, ValueError):
            return None
        if status != 200:
            return None
        for entry in body.get("models") or []:
            if entry.get("id") == model:
                value = entry.get("loaded_at")
                return float(value) if isinstance(value, (int, float)) else None
        return None

    def _worker_generate_count(self) -> int | None:
        """The worker's own ``total_requests`` -- inferences it actually ran.

        Read from ``/api/stats`` -> ``workers``, which the worker fills from live
        scheduler state. This is the counter that answers "did a request reach
        the model"; the HTTP status alone answers only "was the client told no".
        """
        try:
            status, body = self.http.json("GET", "/api/stats", timeout=30)
        except (OSError, ValueError):
            return None
        if status != 200:
            return None
        for payload in (body.get("workers") or {}).values():
            if isinstance(payload, dict) and "total_requests" in payload:
                return int(payload["total_requests"])
        return None

    def _record_total(self) -> int | None:
        try:
            status, body = self.http.json("GET", "/api/inference-records/status",
                                          timeout=30)
        except (OSError, ValueError):
            return None
        if status != 200:
            return None
        total = body.get("total")
        return int(total) if total is not None else None


# ---------------------------------------------------------------------------
# Summary and verdict
# ---------------------------------------------------------------------------
#: The groups whose requests are the core 2000. The concurrency and readiness
#: groups are reported on their own terms and never folded into these.
CORE_GROUPS = ("nocxt", "cxt")

#: The surfaces the load-window probe hits, in the order the report lists them.
READINESS_SURFACES = ("stream", "nonstream", "console")

#: Group names the readiness phase uses. ``readiness-after`` is the post-load
#: request, which is part of the same phase and is re-run with it.
READINESS_GROUPS = ("readiness-stream", "readiness-nonstream", "readiness-console",
                    "readiness-after")


def summarize(rounds: Sequence[Round], readiness: dict | None = None) -> dict:
    """Per-group rates, spreads and answer accuracy, plus run-wide totals.

    Three things this computes that a naive summariser would get wrong:

    * **Success means "the status the phase required", not "HTTP 200".** A
      readiness attempt that was correctly refused with 409 is a success, and
      counting it as a failure would make a working gate look broken. That is
      why ``status_ok`` is per-row and set by the phase, not inferred here.
    * **The context group's prompt tokens are reported separately**, because
      they are larger by construction and averaging them with the no-context
      group would produce a number that describes neither.
    * **Recall and count accuracy are counted per graded row**, in the same
      group they came from, so "the history was used" cannot be inflated by the
      independent group's trivially answerable questions.
    """
    out: dict = {"groups": {}, "by_tier": {}, "totals": {}}
    groups = sorted({r.group for r in rounds})
    for group in groups:
        rows = [r for r in rounds if r.group == group]
        # ``status_ok`` alone, not ``and not error``: a 409 refusal during a load
        # carries the service's explanation in ``error`` and is still the correct
        # outcome for its phase. The per-group error breakdown below is what keeps
        # those visible.
        answered = [r for r in rows if r.status_ok]
        counts = [r.count_ok for r in rows if r.count_ok is not None]
        recalls = [r.recall_ok for r in rows if r.recall_ok is not None]
        markers = [r.marker_ok for r in rows if r.marker_ok is not None]
        errors: dict[str, int] = {}
        for r in rows:
            if r.error:
                head = r.error.split(":")[0][:60]
                errors[head] = errors.get(head, 0) + 1
        statuses: dict[str, int] = {}
        for r in rows:
            key = str(r.http_status) if r.http_status is not None else "no-status"
            statuses[key] = statuses.get(key, 0) + 1
        out["groups"][group] = {
            "requests": len(rows),
            "ok": len(answered),
            "status_matched": sum(1 for r in rows if r.status_ok),
            "success_rate": round(len(answered) / len(rows), 4) if rows else None,
            "http_status_counts": statuses,
            "empty_outputs": sum(1 for r in rows if not r.output and r.status_ok),
            "error_types": errors,
            "ttft_s": spread([r.ttft_s for r in rows if r.status_ok]),
            "server_ttft_s": spread([r.server_ttft_s for r in rows if r.status_ok]),
            "total_s": spread([r.total_s for r in rows if r.status_ok]),
            "decode_tps": spread([r.decode_tps for r in rows if r.status_ok]),
            "prompt_tokens": spread([r.prompt_tokens for r in rows if r.status_ok]),
            "completion_tokens": spread([r.completion_tokens for r in rows if r.status_ok]),
            "cached_tokens": spread([r.cached_tokens for r in rows if r.status_ok]),
            "count_checked": len(counts),
            "count_ok": sum(1 for c in counts if c),
            "recall_checked": len(recalls),
            "recall_ok": sum(1 for r in recalls if r),
            "marker_checked": len(markers),
            "marker_ok": sum(1 for r in markers if r),
            "cross_talk": sum(1 for r in rows if r.cross_talk),
            "sessions": len({r.session for r in rows if r.session is not None}),
        }

    # Per tier, per core group: the distribution the charts are drawn from.
    for group in CORE_GROUPS:
        rows = [r for r in rounds if r.group == group]
        per_tier: dict[int, dict] = {}
        for tier in TIERS:
            tier_rows = [r for r in rows if r.tier == tier]
            if not tier_rows:
                continue
            graded = [r for r in tier_rows if r.count_ok is not None]
            per_tier[tier] = {
                "requests": len(tier_rows),
                "ok": sum(1 for r in tier_rows if r.status_ok),
                "ttft_s": spread([r.ttft_s for r in tier_rows if r.status_ok]),
                "total_s": spread([r.total_s for r in tier_rows if r.status_ok]),
                "decode_tps": spread([r.decode_tps for r in tier_rows if r.status_ok]),
                "prompt_tokens": spread([r.prompt_tokens for r in tier_rows if r.status_ok]),
                "completion_tokens": spread([r.completion_tokens
                                             for r in tier_rows if r.status_ok]),
                "count_checked": len(graded),
                "count_ok": sum(1 for r in graded if r.count_ok),
                "recall_checked": sum(1 for r in tier_rows if r.recall_ok is not None),
                "recall_ok": sum(1 for r in tier_rows if r.recall_ok),
            }
        out["by_tier"][group] = {str(k): v for k, v in sorted(per_tier.items())}

    core = [r for r in rounds if r.group in CORE_GROUPS]
    out["totals"] = {
        "requests": len(rounds),
        "core_requests": len(core),
        "core_ok": sum(1 for r in core if r.status_ok),
        "concurrency_requests": sum(1 for r in rounds if r.group == "conc"),
        "concurrency_ok": sum(1 for r in rounds
                              if r.group == "conc" and r.status_ok),
        "readiness_attempts": sum(1 for r in rounds if r.group.startswith("readiness")),
        "http_5xx": sum(1 for r in rounds if (r.http_status or 0) >= 500),
        "http_4xx": sum(1 for r in rounds if r.http_status and 400 <= r.http_status < 500),
        "connection_errors": sum(1 for r in rounds if r.http_status is None and r.error),
        "empty_outputs": sum(1 for r in rounds
                             if not r.output and r.status_ok and r.group in CORE_GROUPS),
        "cross_talk": sum(1 for r in rounds if r.cross_talk),
    }
    if readiness is not None:
        out["readiness"] = readiness
    return out


def verdict(summary: dict, records: dict, db: dict | None,
            readiness: dict | None) -> dict:
    """The acceptance gate, computed rather than asserted in prose.

    Every criterion in the task card is a count compared against an expected
    value, so the gate is arithmetic. ``passed`` is the conjunction, and the
    individual keys are printed in the report so a failure names itself.

    Answer correctness enters as a **rate that is reported, not a threshold that
    gates**: the task defines acceptance as stability (2000/2000 clean, no 5xx,
    no cross-talk, records consistent, readiness enforced) and a "95% correct"
    bar would be an acceptance criterion nobody set. It is not a floor of zero
    either -- a run where the model answered nothing correctly has not shown a
    working service, and the MYS-2498 run's recall bug is exactly what a
    zero-floor gate would have shipped.
    """
    groups = summary["groups"]
    core = {g: groups.get(g) for g in CORE_GROUPS}
    conc = groups.get("conc") or {}
    readiness = readiness or {}

    core_requests = sum((v or {}).get("requests", 0) for v in core.values())
    core_ok = sum((v or {}).get("ok", 0) for v in core.values())
    planned_per_group = core_total()
    counts = {
        "records_missing": len(records.get("missing") or []),
        "records_missing_from_export": len(records.get("missing_from_export") or []),
        "records_duplicated": len(records.get("duplicates") or []),
        "records_output_mismatch": len(records.get("output_mismatch") or []),
        "records_metrics_mismatch": len(records.get("metrics_mismatch") or []),
        "records_context_mismatch": len(records.get("context_mismatch") or []),
        "records_input_mismatch": len(records.get("input_mismatch") or []),
        "records_not_ok": len(records.get("not_ok_rows") or []),
        "records_source_mismatch": len(records.get("source_mismatch") or []),
        "secret_leaks": len(records.get("secret_leaks") or []),
        "http_5xx": summary["totals"]["http_5xx"],
        "core_errors": core_requests - core_ok,
        "empty_outputs": summary["totals"]["empty_outputs"],
        "cross_talk": summary["totals"]["cross_talk"],
        "concurrency_errors": summary["totals"]["concurrency_requests"]
        - summary["totals"]["concurrency_ok"],
    }
    # Readiness: every attempt during the window must have been refused, and the
    # post-load request must have been served. A missing or unmeasured phase is a
    # failure, not a skip -- "we did not check" is not "it works".
    by_surface = readiness.get("by_surface") or {}
    readiness_refused = sum(v.get("refused", 0) for v in by_surface.values())
    # "Admitted" means admitted *during the load*. A response that started after
    # the model's own ``loaded_at`` is a success that belongs to the window's
    # other side, and counting it as a violation would fail a gate that did its
    # job -- the task card's criterion is "模型准备好前所有请求只能拒绝", which a
    # post-ready success does not contradict.
    readiness_admitted = readiness.get("admitted_inside_window")
    if readiness_admitted is None:
        readiness_admitted = sum(v.get("admitted", 0) for v in by_surface.values())
    readiness_other = len(readiness.get("unexpected_inside_window") or []) \
        if "unexpected_inside_window" in readiness \
        else sum(v.get("other", 0) for v in by_surface.values())
    readiness_records = sum(v.get("records", 0) for v in by_surface.values())
    after = readiness.get("after") or {}
    flags = {
        "core_all_ok": core_ok == 2 * planned_per_group and core_requests == 2 * planned_per_group,
        "concurrency_all_ok": (
            conc.get("requests") == CONCURRENCY_LANES * CONCURRENCY_ROUNDS
            and conc.get("ok") == CONCURRENCY_LANES * CONCURRENCY_ROUNDS),
        "readiness_observed_loading": bool(readiness.get("observed_loading")),
        "readiness_no_admitted": readiness_admitted == 0 and readiness_other == 0,
        "readiness_no_worker_generate": readiness.get("generate_after_load") == 0,
        "readiness_no_records": (readiness.get("records_delta_loading") == 0
                                 and readiness_records == 0),
        "readiness_serves_after": (after.get("http") == 200
                                   and after.get("records_delta") == 1
                                   and bool(after.get("req_id"))),
        "some_answer_correct": (sum(v.get("count_ok", 0) for v in core.values() if v) >= 1),
        "some_recall_correct": (
            True if not any((v or {}).get("recall_checked") for v in core.values())
            else sum(v.get("recall_ok", 0) for v in core.values() if v) >= 1),
    }
    if db is not None:
        counts["sqlite_missing"] = len(db.get("missing") or [])
        counts["sqlite_output_mismatch"] = len(db.get("output_mismatch") or [])
        flags["sqlite_readable"] = bool(db.get("readable"))
    gate: dict = {**flags, **counts}
    gate["core_graded_requests"] = core_requests
    gate["core_ok_requests"] = core_ok
    gate["count_graded"] = sum(v.get("count_checked", 0) for v in core.values() if v)
    gate["count_correct"] = sum(v.get("count_ok", 0) for v in core.values() if v)
    gate["count_accuracy"] = (round(gate["count_correct"] / gate["count_graded"], 4)
                              if gate["count_graded"] else None)
    gate["recall_graded"] = sum(v.get("recall_checked", 0) for v in core.values() if v)
    gate["recall_correct"] = sum(v.get("recall_ok", 0) for v in core.values() if v)
    gate["recall_accuracy"] = (round(gate["recall_correct"] / gate["recall_graded"], 4)
                               if gate["recall_graded"] else None)
    gate["readiness_attempts"] = readiness.get("attempts", 0)
    gate["readiness_refused"] = readiness_refused
    gate["readiness_admitted"] = readiness_admitted
    gate["readiness_other_status"] = readiness_other
    gate["passed"] = all(v == 0 for v in counts.values()) and all(flags.values())
    return gate


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
#: Chart geometry, in SVG user units. One place so every chart lines up.
CHART = {"w": 880, "h": 260, "left": 62, "right": 18, "top": 18, "bottom": 46}


def _fmt(value, digits: int = 3) -> str:
    """A number for display: three decimals at most, trailing zeros dropped."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _spread_cell(d: dict) -> str:
    """min / median / p95 / max as one cell; ``-`` when nothing was measured."""
    if not d or not d.get("n"):
        return "-"
    return (f"{_fmt(d['min'])} / {_fmt(d['median'])} / "
            f"{_fmt(d['p95'])} / {_fmt(d['max'])}")


def _axis_scale(values: Sequence[float]) -> tuple[float, float]:
    """``(lo, hi)`` for a y-axis, padded and never degenerate."""
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0, 1.0
    lo, hi = min(clean), max(clean)
    if lo == hi:
        pad = abs(lo) * 0.05 or 1.0
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def _tick_values(lo: float, hi: float, count: int = 5) -> list[float]:
    """``count`` evenly spaced ticks across ``[lo, hi]``, rounded for display."""
    if hi <= lo:
        return [lo]
    step = (hi - lo) / (count - 1)
    return [lo + step * i for i in range(count)]


def svg_line_chart(series: Sequence[dict], *, title: str, y_label: str,
                   x_labels: Sequence[str], width: int | None = None,
                   height: int | None = None) -> str:
    """A multi-series line chart drawn from the run's numbers, as inline SVG.

    No chart library: the report must open on a board with no network, so the
    SVG is generated here. Each series is ``{"name": ..., "values": [...],
    "colour": "#rrggbb"}`` with ``None`` allowed for "not measured" (the line
    simply breaks there rather than pretending zero).

    Only numbers reach the SVG -- series names and labels go through
    :func:`html_escape` -- so a model's output can never become markup here.
    """
    w = width or CHART["w"]
    h = height or CHART["h"]
    left, right, top, bottom = CHART["left"], CHART["right"], CHART["top"], CHART["bottom"]
    plot_w = w - left - right
    plot_h = h - top - bottom
    all_values = [v for s in series for v in s["values"] if v is not None]
    lo, hi = _axis_scale(all_values)
    n = max(len(x_labels), 1)
    step_x = plot_w / max(n - 1, 1)

    def x_at(i: int) -> float:
        return left + step_x * i

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts: list[str] = [
        f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{html_escape(title)}" preserveAspectRatio="xMidYMid meet">',
        f'<text class="chart-title" x="{left}" y="13">{html_escape(title)}</text>',
    ]
    for tick in _tick_values(lo, hi):
        y = y_at(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" '
                     f'x2="{w - right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{html_escape(_fmt(tick))}</text>')
    for i, label in enumerate(x_labels):
        parts.append(f'<text class="tick" x="{x_at(i):.1f}" y="{h - bottom + 18}" '
                     f'text-anchor="middle">{html_escape(label)}</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top + plot_h}" '
                 f'x2="{w - right}" y2="{top + plot_h}"/>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top}" '
                 f'x2="{left}" y2="{top + plot_h}"/>')
    parts.append(f'<text class="axis-label" transform="translate(14,{top + plot_h / 2:.1f}) '
                 f'rotate(-90)" text-anchor="middle">{html_escape(y_label)}</text>')
    for s in series:
        colour = s.get("colour") or "#2f6fed"
        path: list[str] = []
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            path.append(f"{'M' if not path else 'L'}{x_at(i):.1f},{y_at(float(v)):.1f}")
        if path:
            parts.append(f'<path class="series" d="{" ".join(path)}" '
                         f'stroke="{html_escape(colour)}"/>')
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            parts.append(f'<circle class="point" cx="{x_at(i):.1f}" '
                         f'cy="{y_at(float(v)):.1f}" r="2.5" '
                         f'fill="{html_escape(colour)}">'
                         f'<title>{html_escape(s["name"])} · {html_escape(x_labels[i] if i < len(x_labels) else i)}'
                         f' · {html_escape(_fmt(v))}</title></circle>')
    # Legend along the bottom, right-aligned so it never overlaps the first tick.
    legend_x = w - right
    for s in reversed(list(series)):
        label = html_escape(s["name"])
        legend_x -= 12 + 7 * len(s["name"]) + 16
        parts.append(f'<rect x="{legend_x:.0f}" y="{h - 12}" width="10" height="3" '
                     f'fill="{html_escape(s.get("colour") or "#2f6fed")}"/>')
        parts.append(f'<text class="legend" x="{legend_x + 14:.0f}" y="{h - 7}">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_bar_chart(labels: Sequence[str], values: Sequence[float | None], *,
                  title: str, y_label: str, colour: str = "#2f6fed",
                  second: Sequence[float | None] | None = None,
                  second_name: str = "", first_name: str = "") -> str:
    """A grouped bar chart: one or two series over categorical labels.

    Used for the per-tier answer-accuracy panel, where the interesting
    comparison is "graded vs correct" per tier -- a table of 12 rows is harder
    to scan than 12 pairs of bars.
    """
    w, h = CHART["w"], CHART["h"]
    left, right, top, bottom = CHART["left"], CHART["right"], CHART["top"], CHART["bottom"]
    plot_w = w - left - right
    plot_h = h - top - bottom
    everything = [v for v in list(values) + list(second or []) if v is not None]
    lo, hi = 0.0, max(everything) if everything else 1.0
    hi = hi * 1.12 or 1.0
    n = max(len(labels), 1)
    slot = plot_w / n

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts: list[str] = [
        f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{html_escape(title)}" preserveAspectRatio="xMidYMid meet">',
        f'<text class="chart-title" x="{left}" y="13">{html_escape(title)}</text>',
    ]
    for tick in _tick_values(lo, hi):
        y = y_at(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" '
                     f'x2="{w - right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{html_escape(_fmt(tick))}</text>')
    parts.append(f'<text class="axis-label" transform="translate(14,{top + plot_h / 2:.1f}) '
                 f'rotate(-90)" text-anchor="middle">{html_escape(y_label)}</text>')
    bar_w = slot * (0.34 if second is not None else 0.6)
    for i, label in enumerate(labels):
        centre = left + slot * (i + 0.5)
        if second is not None:
            pairs = [(values[i] if i < len(values) else None, -bar_w * 0.55, colour),
                     (second[i] if i < len(second) else None, bar_w * 0.05, "#9aa8c7")]
        else:
            pairs = [(values[i] if i < len(values) else None, -bar_w / 2, colour)]
        for value, offset, fill in pairs:
            if value is None:
                continue
            y = y_at(float(value))
            parts.append(f'<rect x="{centre + offset:.1f}" y="{y:.1f}" '
                         f'width="{bar_w:.1f}" height="{max(top + plot_h - y, 0):.1f}" '
                         f'fill="{html_escape(fill)}"><title>'
                         f'{html_escape(label)} · {html_escape(_fmt(value))}</title></rect>')
        parts.append(f'<text class="tick" x="{centre:.1f}" y="{h - bottom + 18}" '
                     f'text-anchor="middle">{html_escape(label)}</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top + plot_h}" '
                 f'x2="{w - right}" y2="{top + plot_h}"/>')
    if second is not None and (first_name or second_name):
        parts.append(f'<rect x="{w - right - 150}" y="{h - 12}" width="10" height="3" '
                     f'fill="{html_escape(colour)}"/>')
        parts.append(f'<text class="legend" x="{w - right - 134}" y="{h - 7}">'
                     f'{html_escape(first_name)}</text>')
        parts.append(f'<rect x="{w - right - 62}" y="{h - 12}" width="10" height="3" '
                     f'fill="#9aa8c7"/>')
        parts.append(f'<text class="legend" x="{w - right - 46}" y="{h - 7}">'
                     f'{html_escape(second_name)}</text>')
    parts.append("</svg>")
    return "".join(parts)


#: The report's CSS. Inline, no @import, no webfont: the file has to render the
#: same on a board with no network as on a laptop.
STYLE = """
:root{
  --bg:#f6f7fb; --panel:#ffffff; --ink:#141a26; --muted:#5b6577; --line:#dfe3ec;
  --accent:#2f6fed; --ok:#1a7f4b; --warn:#a85b00; --bad:#b00020; --chip:#eef2fb;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC",
  "Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif;}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:18px 26px}
h1{margin:0 0 4px;font-size:20px;font-weight:650;letter-spacing:.2px}
h2{font-size:16px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:14px;margin:18px 0 8px;color:var(--muted);font-weight:600}
.sub{color:var(--muted);font-size:12.5px}
main{max-width:1180px;margin:0 auto;padding:0 26px 60px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin:18px 0}
nav{display:flex;gap:6px;flex-wrap:wrap;background:var(--panel);padding:10px 26px 0;
  border-bottom:1px solid var(--line)}
nav button{border:1px solid transparent;border-bottom:none;background:transparent;
  padding:8px 14px;border-radius:8px 8px 0 0;cursor:pointer;color:var(--muted);
  font:inherit;font-weight:550}
nav button[aria-selected="true"]{background:var(--bg);color:var(--ink);
  border-color:var(--line);margin-bottom:-1px}
.panel[hidden]{display:none}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);
  vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:none;
  position:sticky;top:0;background:var(--panel);z-index:1}
tbody tr:hover{background:#f9fafd}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12.5px}
.scroll{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:8px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.chip{background:var(--chip);border-radius:999px;padding:3px 11px;font-size:12.5px}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
.kpi div{background:#fbfcfe;border:1px solid var(--line);border-radius:9px;padding:12px 14px}
.kpi .v{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}
.kpi .k{color:var(--muted);font-size:12px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.chart{width:100%;height:auto;display:block;margin:6px 0 2px}
.chart .grid{stroke:#eef1f7;stroke-width:1}
.chart .axis{stroke:#c6cddb;stroke-width:1}
.chart .series{fill:none;stroke-width:2}
.chart .point{stroke:#fff;stroke-width:1}
.chart text{font-size:10.5px;fill:var(--muted)}
.chart-title{font-size:12px;fill:var(--ink);font-weight:600}
.chart .legend{font-size:10.5px}
.chart .axis-label{font-size:10.5px}
pre{background:#0f1420;color:#e7ecf5;padding:12px 14px;border-radius:8px;
  overflow:auto;font-size:12.5px;line-height:1.5;max-height:420px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
input[type=search],select{font:inherit;padding:6px 9px;border:1px solid var(--line);
  border-radius:7px;background:#fff;min-width:120px}
button.pg{font:inherit;padding:5px 11px;border:1px solid var(--line);border-radius:7px;
  background:#fff;cursor:pointer}
button.pg[disabled]{opacity:.45;cursor:default}
.out{white-space:pre-wrap;word-break:break-word;max-height:220px;overflow:auto;
  background:#fbfcfe;border:1px solid var(--line);border-radius:7px;padding:8px 10px;
  font-size:12.5px}
.tag{display:inline-block;padding:1px 7px;border-radius:5px;font-size:11.5px;
  background:var(--chip);color:var(--muted)}
.tag.ok{background:#e6f5ec;color:var(--ok)}
.tag.bad{background:#fdeaee;color:var(--bad)}
footer{color:var(--muted);font-size:12px;padding:20px 26px}
"""


#: Column definitions for the searchable request table. Kept as data rather than
#: hand-written ``<td>`` soup so the JS header, the sort keys and the row builder
#: cannot disagree -- a mismatch there is the classic "sort by a column that is
#: actually the neighbouring one" bug.
TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("group", "组"),
    ("session", "会话"),
    ("turn", "轮"),
    ("lane", "路"),
    ("tier", "字数"),
    ("http", "HTTP"),
    ("status_ok", "状态符合"),
    ("total_s", "总耗时(s)"),
    ("ttft_s", "首 token(s)"),
    ("prompt_tokens", "prompt"),
    ("completion_tokens", "completion"),
    ("cached_tokens", "cached"),
    ("decode_tps", "decode_tps"),
    ("finish_reason", "finish_reason"),
    ("count_ok", "计数"),
    ("recall_ok", "回忆"),
    ("marker_ok", "标记"),
    ("error", "错误"),
    ("input", "输入"),
    ("output", "输出"),
)


def _flag_cell(value) -> str:
    """``✓`` / ``✗`` / ``-`` for a tri-state grade, as a JS-side literal.

    Returned as a small string for the JSON payload rather than HTML: the table
    is built in the browser (so filtering and pagination work on 2100+ rows
    without shipping 2100 ``<tr>`` elements), which means the server's job is to
    hand over data, not markup. All of it is inserted with ``textContent``.
    """
    if value is None:
        return "-"
    return "✓" if value else "✗"


def table_rows(rounds: Sequence[Round]) -> list[list]:
    """The JSON rows the request table renders, in column order.

    Model output is truncated here, not in the browser: 2100 rows of full
    completions would be a multi-megabyte page, and the full text is what
    ``evidence.json`` and ``rounds.jsonl`` are for. The truncation is visible
    (an ellipsis) so a reader is never misled into thinking a reply was short.
    """
    rows: list[list] = []

    def clip(text, limit=240):
        text = text or ""
        return text if len(text) <= limit else text[:limit] + "…"

    for r in rounds:
        rows.append([
            r.group,
            "" if r.session is None else r.session,
            "" if r.turn is None else r.turn,
            "" if r.lane is None else r.lane,
            r.tier,
            "" if r.http_status is None else r.http_status,
            _flag_cell(r.status_ok),
            None if r.total_s is None else round(r.total_s, 3),
            None if r.ttft_s is None else round(r.ttft_s, 3),
            r.prompt_tokens,
            r.completion_tokens,
            r.cached_tokens,
            None if r.decode_tps is None else round(float(r.decode_tps), 2),
            r.finish_reason or "",
            _flag_cell(r.count_ok),
            _flag_cell(r.recall_ok),
            _flag_cell(r.marker_ok),
            clip(r.error, 300),
            clip(r.input_text, 240),
            clip(r.output, 240),
        ])
    return rows


#: The browser half of the request table. Filtering, sorting and pagination all
#: run over the JSON payload; every value goes in with ``textContent`` (never
#: ``innerHTML``), which is the reason a model reply containing ``<script>``
#: cannot execute.
TABLE_JS = """
(function(){
  const T = window.__ROWS__;
  const COLS = window.__COLS__;
  const q = document.getElementById('t-q');
  const groupSel = document.getElementById('t-group');
  const statusSel = document.getElementById('t-status');
  const pageSizeSel = document.getElementById('t-size');
  const body = document.getElementById('t-body');
  const info = document.getElementById('t-info');
  const prev = document.getElementById('t-prev');
  const next = document.getElementById('t-next');
  let page = 0, sortKey = -1, sortDir = 1, filtered = T;

  function matches(row){
    const needle = (q.value || '').trim().toLowerCase();
    if (needle){
      let hit = false;
      for (let i = 0; i < row.length; i++){
        if (String(row[i] === null ? '' : row[i]).toLowerCase().indexOf(needle) >= 0){ hit = true; break; }
      }
      if (!hit) return false;
    }
    const g = groupSel.value;
    if (g && row[0] !== g) return false;
    const s = statusSel.value;
    if (s === 'bad' && row[6] !== '✗') return false;
    if (s === 'ok' && row[6] !== '✓') return false;
    if (s === 'count-bad' && row[14] !== '✗') return false;
    if (s === 'recall-bad' && row[15] !== '✗') return false;
    if (s === 'any-bad' && row[6] !== '✗' && row[14] !== '✗' && row[15] !== '✗' && row[16] !== '✗') return false;
    return true;
  }
  function cmp(a, b){
    const x = a[sortKey], y = b[sortKey];
    const nx = (x === '' || x === null || x === undefined) ? null : Number(x);
    const ny = (y === '' || y === null || y === undefined) ? null : Number(y);
    if (nx !== null && ny !== null && !isNaN(nx) && !isNaN(ny)) return (nx - ny) * sortDir;
    const sx = String(x === null || x === undefined ? '' : x);
    const sy = String(y === null || y === undefined ? '' : y);
    return sx.localeCompare(sy) * sortDir;
  }
  function render(){
    const size = Number(pageSizeSel.value);
    const maxPage = Math.max(Math.ceil(filtered.length / size) - 1, 0);
    if (page > maxPage) page = maxPage;
    const slice = filtered.slice(page * size, page * size + size);
    body.textContent = '';
    const frag = document.createDocumentFragment();
    for (const row of slice){
      const tr = document.createElement('tr');
      for (let i = 0; i < row.length; i++){
        const td = document.createElement('td');
        const v = row[i];
        if (i === 7 || i === 8 || i === 9 || i === 10 || i === 11 || i === 12){
          td.className = 'num';
        }
        if (i === 18 || i === 19){
          const div = document.createElement('div');
          div.className = 'out';
          div.textContent = v === null || v === undefined ? '' : String(v);
          td.appendChild(div);
        } else if (i === 17 && v){
          td.textContent = String(v);
          td.className = 'mono';
        } else {
          td.textContent = v === null || v === undefined ? '' : String(v);
        }
        tr.appendChild(td);
      }
      frag.appendChild(tr);
    }
    body.appendChild(frag);
    info.textContent = '共 ' + filtered.length + ' 行 / 第 ' + (page + 1) +
      ' 页，共 ' + (maxPage + 1) + ' 页';
    prev.disabled = page <= 0;
    next.disabled = page >= maxPage;
  }
  function apply(){
    filtered = T.filter(matches);
    if (sortKey >= 0) filtered = filtered.slice().sort(cmp);
    page = 0;
    render();
  }
  q.addEventListener('input', apply);
  groupSel.addEventListener('change', apply);
  statusSel.addEventListener('change', apply);
  pageSizeSel.addEventListener('change', apply);
  prev.addEventListener('click', function(){ page = Math.max(page - 1, 0); render(); });
  next.addEventListener('click', function(){ page += 1; render(); });
  document.querySelectorAll('th[data-col]').forEach(function(th){
    th.addEventListener('click', function(){
      const idx = Number(th.getAttribute('data-col'));
      if (sortKey === idx){ sortDir = -sortDir; } else { sortKey = idx; sortDir = 1; }
      filtered = filtered.slice().sort(cmp);
      render();
    });
  });
  apply();
})();
"""


def build_html(evidence: Path, env: dict, summary: dict, records: dict, db: dict,
               readiness: dict, gate: dict, manifest: dict, rounds: Sequence[Round],
               timeline: Sequence[TimelineEntry], samples: Sequence[dict],
               device_label: str, resume: dict | None = None) -> Path:
    """The single-file report: conclusions, timeline, charts, request table.

    Self-contained by construction -- the CSS and JS are string constants in this
    module, the charts are inline SVG built from the run's numbers, and there is
    not one ``http://`` reference in the output. That is checkable, and the unit
    tests check it (:func:`tests.test_extended_stability_suite`).
    """
    svc = env.get("service") or {}
    rec_log = env.get("record_log") or {}
    groups = summary["groups"]
    totals = summary["totals"]
    planned = core_total()

    def kpi(value, label, cls="") -> str:
        return (f'<div><div class="v {cls}">{html_escape(_fmt(value))}</div>'
                f'<div class="k">{html_escape(label)}</div></div>')

    parts: list[str] = []
    add = parts.append
    add('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">')
    add('<meta name="viewport" content="width=device-width,initial-scale=1">')
    add(f'<title>CV84X6 扩大稳定性测试报告 · {html_escape(device_label)}</title>')
    add(f"<style>{STYLE}</style></head><body>")

    verdict_text = "通过" if gate.get("passed") else "未通过"
    verdict_cls = "ok" if gate.get("passed") else "bad"
    add('<header>')
    add('<h1>CV84X6 128k 模型扩大稳定性测试报告</h1>')
    add(f'<div class="sub">设备 {html_escape(device_label)}　·　模型 '
        f'<code>{html_escape(manifest.get("model"))}</code>　·　版本 '
        f'<code>{html_escape((svc.get("version_pkg") or "").strip())}</code>　·　'
        f'生成 {html_escape(env.get("captured_iso"))}　·　'
        f'结论 <strong class="{verdict_cls}">{verdict_text}</strong></div>')
    add('</header>')

    add('<nav role="tablist">')
    for i, (tab_id, label) in enumerate((("p-summary", "整体结论"),
                                         ("p-timeline", "测试时间线"),
                                         ("p-perf", "性能图表"),
                                         ("p-data", "测试数据详情"))):
        selected = "true" if i == 0 else "false"
        add(f'<button role="tab" id="tab-{tab_id}" aria-controls="{tab_id}" '
            f'aria-selected="{selected}">{label}</button>')
    add('</nav><main>')

    # ------------------------------------------------------------------
    # 1. Overall conclusions
    # ------------------------------------------------------------------
    add('<div class="panel" id="p-summary" role="tabpanel">')
    add('<section>')
    add('<h2>1 · 整体结论</h2>')
    add('<div class="kpi">')
    add(kpi(f'{totals["core_ok"]}/{planned * 2}', "核心请求正常结束（无上下文 + 带上下文）",
            "ok" if gate.get("core_all_ok") else "bad"))
    add(kpi(f'{totals["concurrency_ok"]}/{CONCURRENCY_LANES * CONCURRENCY_ROUNDS}',
            f'并发 {CONCURRENCY_LANES} 路 × {CONCURRENCY_ROUNDS} 轮',
            "ok" if gate.get("concurrency_all_ok") else "bad"))
    add(kpi(gate.get("readiness_refused"), "加载窗口内被拒（409）次数",
            "ok" if gate.get("readiness_no_admitted") else "bad"))
    add(kpi(f'{gate.get("count_correct")}/{gate.get("count_graded")}', "计数正确"))
    add(kpi(f'{gate.get("recall_correct")}/{gate.get("recall_graded") or 0}', "上下文回忆正确"))
    add(kpi(totals["http_5xx"], "5xx", "" if not totals["http_5xx"] else "bad"))
    add(kpi(totals["empty_outputs"], "空回复", "" if not totals["empty_outputs"] else "bad"))
    add(kpi(totals["cross_talk"], "并发串话", "" if not totals["cross_talk"] else "bad"))
    add('</div>')

    add('<h3>判定</h3>')
    add('<div class="chips">')
    flags = {k: v for k, v in gate.items()
             if isinstance(v, bool)}
    counts = {k: v for k, v in gate.items()
              if isinstance(v, int) and not isinstance(v, bool)}
    for name, value in flags.items():
        add(f'<span class="chip {"ok" if value else "bad"}">'
            f'{html_escape(name)}: {_fmt(value)}</span>')
    add('</div>')

    add('<h3>关键结论</h3><ul>')
    add(f'<li><strong>核心 {planned * 2} 次</strong>：无上下文 {planned} 次、带上下文 '
        f'{planned} 次（<strong>{CONTEXT_SESSIONS} 个独立会话 × 每会话 {CONTEXT_TURNS} 轮</strong>，'
        f'不是 {planned} 轮同一会话），正常结束 '
        f'{totals["core_ok"]}/{planned * 2}；HTTP 5xx {totals["http_5xx"]} 次、'
        f'4xx {totals["http_4xx"]} 次、连接异常 {totals["connection_errors"]} 次、'
        f'空回复 {totals["empty_outputs"]} 次。</li>')
    add(f'<li><strong>并发 {CONCURRENCY_LANES} 路 × {CONCURRENCY_ROUNDS} 轮</strong>'
        f'（{CONCURRENCY_LANES * CONCURRENCY_ROUNDS} 次，独立统计，不并入核心数字）：成功 '
        f'{totals["concurrency_ok"]}/{CONCURRENCY_LANES * CONCURRENCY_ROUNDS}，'
        f'串话 {totals["cross_talk"]} 次，标记回显 '
        f'{(groups.get("conc") or {}).get("marker_ok", 0)}/'
        f'{(groups.get("conc") or {}).get("marker_checked", 0)}。</li>')
    add(f'<li><strong>readiness 专项</strong>：加载窗口内共 '
        f'{gate.get("readiness_attempts")} 次推理请求，被拒 409 '
        f'{gate.get("readiness_refused")} 次、加载期间被放行 {gate.get("readiness_admitted")} 次、'
        f'其他状态 {gate.get("readiness_other_status")} 次；新 worker 就绪时 generate 计数 '
        f'<code>{_fmt(readiness.get("generate_after_load"))}</code>（应为 0）、推理记录变化 '
        f'<code>{_fmt(readiness.get("records_delta_loading"))}</code>；'
        f'加载完成后短请求 HTTP '
        f'<code>{_fmt((readiness.get("after") or {}).get("http"))}</code>，'
        f'新增记录 <code>{_fmt((readiness.get("after") or {}).get("records_delta"))}</code> 条。</li>')
    if resume:
        add(f'<li><strong>证据构成</strong>：本轮沿用 '
            f'<code>{html_escape(resume.get("source_name"))}</code> 的 '
            f'{_fmt(resume.get("adopted_rows"))} 条请求行（组：'
            f'{html_escape("、".join(resume.get("adopted_groups") or []))}），'
            '本轮只运行缺失阶段；两者合并成同一份报告，源目录未被修改。'
            '合并后的请求时间戳保留各自真实发生时间。</li>')
    add(f'<li><strong>推理记录一致性</strong>：逐条核对 {records.get("checked", 0)} 条；'
        f'缺失 {len(records.get("missing") or [])}、导出中缺失 '
        f'{len(records.get("missing_from_export") or [])}、重复 '
        f'{len(records.get("duplicates") or [])}、输出不一致 '
        f'{len(records.get("output_mismatch") or [])}、token 不一致 '
        f'{len(records.get("metrics_mismatch") or [])}、上下文条数不一致 '
        f'{len(records.get("context_mismatch") or [])}，记录内出现原始 API key '
        f'{len(records.get("secret_leaks") or [])} 次；直接只读 SQLite 命中 '
        f'{_fmt(db.get("found"))}/{_fmt(db.get("expected"))}。</li>')
    add(f'<li><strong>正确性</strong>：计数正确 {gate.get("count_correct")}/'
        f'{gate.get("count_graded")}（准确率 {_fmt(gate.get("count_accuracy"))}），'
        f'上下文回忆正确 {gate.get("recall_correct")}/{gate.get("recall_graded") or 0}'
        f'（准确率 {_fmt(gate.get("recall_accuracy"))}）。'
        '正确率单独列示、不参与稳定性判定：任务卡的验收口径是稳定性'
        '（正常结束、无 5xx、无串话、记录一致、readiness 生效），'
        '计一个「95% 正确」的门槛并非任务要求。'
        '缓存命中数（cached）只说明前缀复用，<strong>不作为语义正确的证据</strong>。</li>')
    add('</ul>')

    if readiness:
        add('<h3>readiness 明细</h3>')
        add('<table><thead><tr><th>接口</th><th class="num">尝试</th>'
            '<th class="num">409 拒绝</th><th class="num">被放行</th>'
            '<th class="num">其他状态</th><th class="num">携带 req_id</th></tr></thead><tbody>')
        for surface in READINESS_SURFACES:
            b = (readiness.get("by_surface") or {}).get(surface) or {}
            add(f'<tr><td><code>{html_escape(surface)}</code></td>'
                f'<td class="num">{_fmt(b.get("attempts"))}</td>'
                f'<td class="num">{_fmt(b.get("refused"))}</td>'
                f'<td class="num {"bad" if b.get("admitted") else ""}">'
                f'{_fmt(b.get("admitted"))}</td>'
                f'<td class="num {"bad" if b.get("other") else ""}">'
                f'{_fmt(b.get("other"))}</td>'
                f'<td class="num">{_fmt(b.get("records"))}</td></tr>')
        add(f'<tr><td colspan="6" class="sub">观测到 <code>operation=loading</code>：'
            f'{_fmt(readiness.get("observed_loading"))}；load 请求 HTTP '
            f'<code>{_fmt((readiness.get("load") or {}).get("status"))}</code>，'
            f'耗时 {_fmt((readiness.get("load") or {}).get("s"))}s；'
            f'卸载请求 HTTP <code>{_fmt(readiness.get("unload_status"))}</code>。'
            '加载窗口内的探测按 409 期望值判定：409 是正确结果，不是失败。</td></tr>')
        add('</tbody></table>')
    add('</section>')

    # -- environment ---------------------------------------------------
    add('<section>')
    add('<h2>环境、版本与测试矩阵</h2>')
    add('<table><tbody>')
    rows_env = [
        ("设备", device_label),
        ("服务版本", f'deb <code>{html_escape((svc.get("version_pkg") or "").strip())}</code>，'
                     f'`VERSION` 文件 <code>{html_escape(svc.get("version_file"))}</code>，'
                     f'/healthz <code>{html_escape((env.get("healthz") or {}).get("version"))}</code>'),
        ("服务状态", f'<code>{html_escape(svc.get("active"))}</code>，MainPID '
                     f'<code>{html_escape(svc.get("main_pid"))}</code>，启动于 '
                     f'<code>{html_escape(svc.get("started"))}</code>'),
        ("内核", f'<code>{html_escape((env.get("kernel") or "").strip())}</code>'),
        ("libsophon", f'<code>{html_escape((env.get("sdk_version") or "").strip() or (env.get("libsophon") or "").strip())}</code>'),
        ("数据目录", f'<code>{html_escape(env.get("data_dir"))}</code>'),
        ("记录库", f'<code>{html_escape(rec_log.get("path"))}</code>，开始前 '
                   f'{_fmt(rec_log.get("total"))} 条 / {_fmt(rec_log.get("bytes"))} 字节，'
                   f'保留 {_fmt(rec_log.get("retention_count"))} 条 / '
                   f'{_fmt(rec_log.get("retention_days"))} 天'),
    ]
    for m in env.get("models") or []:
        if m.get("id"):
            rows_env.append(("模型", f'<code>{html_escape(m.get("id"))}</code>，'
                                    f'context_length <code>{_fmt(m.get("context_length"))}</code>，'
                                    f'supports_sampling <code>{_fmt(m.get("supports_sampling"))}</code>，'
                                    f'supports_vision <code>{_fmt(m.get("supports_vision"))}</code>，'
                                    f'加载耗时 {_fmt(m.get("load_seconds"))}s'))
    for d in env.get("model_dirs") or []:
        rows_env.append(("权重", f'<code>{html_escape(d.get("bmodel"))}</code>'
                                f'（{_fmt(d.get("bytes"))} 字节）'))
    for key, value in rows_env:
        add(f'<tr><th style="width:150px">{html_escape(key)}</th><td>{value}</td></tr>')
    add('</tbody></table>')

    settings = env.get("settings") or {}
    if settings:
        add('<h3>关键设置</h3><div class="chips">')
        for key in ("max_concurrent_per_model", "max_queue", "prefix_cache_entries",
                    "prefix_cache_ttl_min", "prefill_exact_tail",
                    "inference_logging_enabled", "inference_log_retention_count",
                    "inference_log_retention_days", "require_api_key"):
            if key in settings:
                add(f'<span class="chip"><code>{html_escape(key)}</code> = '
                    f'{html_escape(settings[key])}</span>')
        add('</div>')

    add('<h3>测试矩阵</h3>')
    add('<table><thead><tr><th>组</th><th>构成</th><th class="num">计划</th>'
        '<th class="num">实发</th><th>说明</th></tr></thead><tbody>')
    add(f'<tr><td>无上下文 nocxt</td><td>每次独立 messages（system + 当前 user）</td>'
        f'<td class="num">{planned}</td>'
        f'<td class="num">{(groups.get("nocxt") or {}).get("requests", 0)}</td>'
        f'<td>长度档 {", ".join(str(t) for t in TIERS)}；前 {SHORT_TIER_COUNT} 档各 '
        f'{REQUESTS_PER_TIER_SHORT} 次、其余各 {REQUESTS_PER_TIER_LONG} 次</td></tr>')
    add(f'<tr><td>带上下文 cxt</td>'
        f'<td>{CONTEXT_SESSIONS} 会话 × {CONTEXT_TURNS} 轮</td>'
        f'<td class="num">{planned}</td>'
        f'<td class="num">{(groups.get("cxt") or {}).get("requests", 0)}</td>'
        f'<td>每轮重发该会话全部历史；每会话长度档 '
        f'{", ".join(str(t) for t in TIERS[:CONTEXT_TURNS])}；'
        f'≥{base.FACT_TIER} 字轮次植入编号事实，≥{base.RECALL_TIER} 字轮次追问前一轮关键词</td></tr>')
    add(f'<tr><td>并发 conc</td><td>{CONCURRENCY_LANES} 路 × {CONCURRENCY_ROUNDS} 轮</td>'
        f'<td class="num">{CONCURRENCY_LANES * CONCURRENCY_ROUNDS}</td>'
        f'<td class="num">{(groups.get("conc") or {}).get("requests", 0)}</td>'
        f'<td>每路唯一字母标记，检查标记回显与记录隔离；服务 '
        f'<code>max_concurrent_per_model={(settings.get("max_concurrent_per_model"))}</code></td></tr>')
    if readiness:
        add(f'<tr><td>readiness</td><td>加载窗口内反复探测三个接口</td>'
            f'<td class="num">—</td>'
            f'<td class="num">{gate.get("readiness_attempts")}</td>'
            f'<td>期望全部 409、worker generate 0、记录 0；加载完成后短请求 200 且恰 1 条记录</td></tr>')
    add('</tbody></table>')

    add('<h3>参数</h3>')
    add(f'<p class="sub">seed=<code>{html_escape(manifest.get("seed"))}</code>，'
        f'固定采样参数 <code>{html_escape(json.dumps(manifest.get("params"), ensure_ascii=False))}</code>，'
        f'system prompt「{html_escape(manifest.get("system"))}」。'
        '长度档为整个 user message 的 Unicode 码点数，由固定 seed 确定性生成，'
        '正文与 SHA-256 见 <code>manifest.json</code>。</p>')
    sampling = {m.get("id"): m.get("supports_sampling") for m in env.get("models") or []}
    if any(value is False for value in sampling.values()):
        add('<p class="sub">本板 bmodel 的 <code>supports_sampling</code> 为 '
            '<code>false</code>：<code>lm_head</code> 只输出 int32、argmax 融在图里，'
            '<code>temperature</code>/<code>top_p</code>/<code>top_k</code> 不生效，解码本身即确定。'
            '参数仍按固定值发送并记录，用于保证每次请求形状一致。</p>')
    add('</section>')
    add('</div>')  # p-summary

    # ------------------------------------------------------------------
    # 2. Timeline
    # ------------------------------------------------------------------
    add('<div class="panel" id="p-timeline" role="tabpanel" hidden>')
    add('<section>')
    add('<h2>2 · 测试时间线</h2>')
    add(f'<p class="sub">共 {len(timeline)} 条记录，按时间升序；'
        '「异常」为请求失败、串话或 readiness 违约，如实保留、不重跑覆盖。'
        '时间均为 UTC。</p>')
    add('<table><thead><tr><th style="width:210px">时间（UTC）</th>'
        '<th style="width:74px">类型</th><th style="width:180px">阶段/事件</th>'
        '<th class="num" style="width:70px">计数</th><th>详情</th></tr></thead><tbody>')
    for entry in timeline:
        iso = datetime.fromtimestamp(entry.at, tz=timezone.utc) \
            .isoformat(timespec="seconds").replace("+00:00", "Z")
        cls = {"anomaly": "bad", "phase": "ok"}.get(entry.kind, "")
        add(f'<tr><td class="mono">{html_escape(iso)}</td>'
            f'<td><span class="tag {cls}">{html_escape(entry.kind)}</span></td>'
            f'<td>{html_escape(entry.label)}</td>'
            f'<td class="num">{_fmt(entry.count)}</td>'
            f'<td>{html_escape(entry.detail)}</td></tr>')
    if not timeline:
        add('<tr><td colspan="5">无记录</td></tr>')
    add('</tbody></table>')

    if samples:
        add('<h3>设备与 worker 采样</h3>')
        add(f'<p class="sub">每 {_fmt(sampler_interval(samples))} 秒一次，共 {len(samples)} 条；'
            '采样线程只发两个只读 GET，不参与请求计时。</p>')
        add('<div class="scroll" style="max-height:360px"><table><thead><tr>'
            '<th>时间（UTC）</th><th class="num">CPU%</th><th class="num">可用内存(MiB)</th>'
            '<th class="num">TPU%</th><th class="num">NPU 已用(MiB)</th>'
            '<th class="num">active</th><th class="num">queued</th>'
            '<th class="num">worker 请求</th><th class="num">失败</th>'
            '<th class="num">拒绝</th><th class="num">缓存条目</th></tr></thead><tbody>')
        for s in samples:
            if not s.get("ok"):
                continue
            w = s.get("worker") or {}
            iso = datetime.fromtimestamp(s["at"], tz=timezone.utc) \
                .isoformat(timespec="seconds").replace("+00:00", "Z")
            mib = lambda v: "-" if v is None else f"{float(v) / 1048576:.0f}"
            add(f'<tr><td class="mono">{html_escape(iso)}</td>'
                f'<td class="num">{_fmt(s.get("cpu_percent"))}</td>'
                f'<td class="num">{mib(s.get("mem_available"))}</td>'
                f'<td class="num">{_fmt(s.get("tpu_util"))}</td>'
                f'<td class="num">{mib(s.get("npu_mem_used"))}</td>'
                f'<td class="num">{_fmt(w.get("active"))}</td>'
                f'<td class="num">{_fmt(w.get("queued"))}</td>'
                f'<td class="num">{_fmt(w.get("total_requests"))}</td>'
                f'<td class="num">{_fmt(w.get("failed_requests"))}</td>'
                f'<td class="num">{_fmt(w.get("rejected_requests"))}</td>'
                f'<td class="num">{_fmt(w.get("cache_entries"))}</td></tr>')
        add('</tbody></table></div>')
    add('</section>')
    add('</div>')  # p-timeline

    # ------------------------------------------------------------------
    # 3. Performance charts
    # ------------------------------------------------------------------
    add('<div class="panel" id="p-perf" role="tabpanel" hidden>')
    add('<section>')
    add('<h2>3 · 性能图表</h2>')
    add('<p class="sub">全部按组、按长度档统计，取 min / median / p95 / max。'
        '两组不构成性能 A/B：带上下文组每轮重发全部历史，prompt token 必然更大，'
        '两组之间的时延差异不代表模型或服务更慢。</p>')

    tier_labels = [str(t) for t in TIERS]
    by_tier = summary.get("by_tier") or {}

    def tier_series(group: str, metric: str) -> list:
        """One per-tier row per tier, in tier order, for ``group``.

        Missing tiers become ``{}`` so ``pick`` yields ``None`` and the chart
        breaks its line -- a tier that was never measured must not be drawn at
        zero. This is a plain lookup, not a metric extraction: callers index the
        row they need, which keeps ``count_ok`` (an int) and ``ttft_s`` (a dict)
        from being conflated.
        """
        d = by_tier.get(group) or {}
        return [d.get(str(t)) or {} for t in TIERS]

    def pick(rows: list, key: str) -> list:
        return [r.get(key) for r in rows]

    add('<h3>首 token 延迟 TTFT（秒）</h3>')
    add(svg_line_chart(
        [{"name": "无上下文 median", "colour": "#2f6fed",
          "values": pick(tier_series("nocxt", "ttft_s"), "median")},
         {"name": "无上下文 p95", "colour": "#8ab0f8",
          "values": pick(tier_series("nocxt", "ttft_s"), "p95")},
         {"name": "带上下文 median", "colour": "#d9822b",
          "values": pick(tier_series("cxt", "ttft_s"), "median")},
         {"name": "带上下文 p95", "colour": "#f0b878",
          "values": pick(tier_series("cxt", "ttft_s"), "p95")}],
        title="首 token 延迟 · 按长度档", y_label="秒", x_labels=tier_labels))

    add('<h3>decode 吞吐（token/s）</h3>')
    add(svg_line_chart(
        [{"name": "无上下文 median", "colour": "#2f6fed",
          "values": pick(tier_series("nocxt", "decode_tps"), "median")},
         {"name": "无上下文 min", "colour": "#8ab0f8",
          "values": pick(tier_series("nocxt", "decode_tps"), "min")},
         {"name": "带上下文 median", "colour": "#d9822b",
          "values": pick(tier_series("cxt", "decode_tps"), "median")},
         {"name": "带上下文 min", "colour": "#f0b878",
          "values": pick(tier_series("cxt", "decode_tps"), "min")}],
        title="decode 吞吐 · 按长度档", y_label="token/s", x_labels=tier_labels))

    add('<h3>总耗时（秒）</h3>')
    add(svg_line_chart(
        [{"name": "无上下文 median", "colour": "#2f6fed",
          "values": pick(tier_series("nocxt", "total_s"), "median")},
         {"name": "无上下文 p95", "colour": "#8ab0f8",
          "values": pick(tier_series("nocxt", "total_s"), "p95")},
         {"name": "带上下文 median", "colour": "#d9822b",
          "values": pick(tier_series("cxt", "total_s"), "median")},
         {"name": "带上下文 p95", "colour": "#f0b878",
          "values": pick(tier_series("cxt", "total_s"), "p95")}],
        title="单请求总耗时 · 按长度档", y_label="秒", x_labels=tier_labels))

    add('<h3>prompt token（中位数）</h3>')
    add(svg_line_chart(
        [{"name": "无上下文", "colour": "#2f6fed",
          "values": pick(tier_series("nocxt", "prompt_tokens"), "median")},
         {"name": "带上下文", "colour": "#d9822b",
          "values": pick(tier_series("cxt", "prompt_tokens"), "median")}],
        title="prompt token 中位数 · 按长度档", y_label="token", x_labels=tier_labels))

    add('<h3>每档判分（已判 / 正确）</h3>')
    for group, group_label in (("nocxt", "无上下文组"), ("cxt", "带上下文组")):
        tier_rows = tier_series(group, "count_ok")
        add(svg_bar_chart(
            tier_labels,
            [r.get("count_checked") for r in tier_rows],
            title=f"{group_label} · 每档正确次数（蓝）与已判次数（灰）",
            y_label="次",
            second=[r.get("count_ok") for r in tier_rows],
            first_name="已判", second_name="正确"))

    add('<h3>分布表（min / median / p95 / max）</h3>')
    add('<div class="scroll"><table><thead><tr><th>组</th><th class="num">请求</th>'
        '<th class="num">成功</th><th class="num">首 token(s)</th>'
        '<th class="num">总耗时(s)</th><th class="num">decode_tps</th>'
        '<th class="num">prompt</th><th class="num">completion</th>'
        '<th class="num">cached</th></tr></thead><tbody>')
    for group in sorted(groups):
        g = groups[group]
        add(f'<tr><td><code>{html_escape(group)}</code></td>'
            f'<td class="num">{g["requests"]}</td><td class="num">{g["ok"]}</td>'
            f'<td class="num">{_spread_cell(g["ttft_s"])}</td>'
            f'<td class="num">{_spread_cell(g["total_s"])}</td>'
            f'<td class="num">{_spread_cell(g["decode_tps"])}</td>'
            f'<td class="num">{_spread_cell(g["prompt_tokens"])}</td>'
            f'<td class="num">{_spread_cell(g["completion_tokens"])}</td>'
            f'<td class="num">{_spread_cell(g["cached_tokens"])}</td></tr>')
    add('</tbody></table></div>')

    add('<h3>错误分类</h3><table><thead><tr><th>组</th><th>错误类型</th>'
        '<th class="num">次数</th></tr></thead><tbody>')
    printed = False
    for group in sorted(groups):
        for kind, count in (groups[group].get("error_types") or {}).items():
            printed = True
            add(f'<tr><td><code>{html_escape(group)}</code></td>'
                f'<td class="mono">{html_escape(kind)}</td>'
                f'<td class="num">{count}</td></tr>')
    if not printed:
        add('<tr><td colspan="3">无错误</td></tr>')
    add('</tbody></table>')

    add('<h3>HTTP 状态分布</h3><table><thead><tr><th>组</th><th>状态</th>'
        '<th class="num">次数</th></tr></thead><tbody>')
    for group in sorted(groups):
        for status, count in sorted((groups[group].get("http_status_counts") or {}).items()):
            add(f'<tr><td><code>{html_escape(group)}</code></td>'
                f'<td class="mono">{html_escape(status)}</td>'
                f'<td class="num">{count}</td></tr>')
    add('</tbody></table>')
    add('</section>')
    add('</div>')  # p-perf

    # ------------------------------------------------------------------
    # 4. Request table
    # ------------------------------------------------------------------
    rows = table_rows(rounds)
    group_options = sorted({r.group for r in rounds})
    add('<div class="panel" id="p-data" role="tabpanel" hidden>')
    add('<section>')
    add('<h2>4 · 测试数据详情</h2>')
    add(f'<p class="sub">共 {len(rows)} 条请求记录，可搜索、筛选、排序、分页。'
        '输入/输出在此截断显示（各 240 字符），完整原文见证据目录的 '
        '<code>rounds.jsonl</code>、<code>manifest.json</code> 与 <code>raw/</code>。'
        '所有单元格以 <code>textContent</code> 注入，模型输出中的 HTML 不会被解析。</p>')
    add('<div class="controls">')
    add('<input type="search" id="t-q" placeholder="搜索全部字段（组/错误/输入/输出…）" '
        'style="min-width:280px">')
    add('<select id="t-group"><option value="">全部组</option>')
    for g in group_options:
        add(f'<option value="{html_escape(g)}">{html_escape(g)}</option>')
    add('</select>')
    add('<select id="t-status">'
        '<option value="">全部状态</option>'
        '<option value="bad">仅状态不符</option>'
        '<option value="ok">仅状态符合</option>'
        '<option value="count-bad">仅计数错</option>'
        '<option value="recall-bad">仅回忆错</option>'
        '<option value="any-bad">任一判分错</option>'
        '</select>')
    add('<select id="t-size"><option value="50">50 行/页</option>'
        '<option value="100" selected>100 行/页</option>'
        '<option value="200">200 行/页</option>'
        '<option value="500">500 行/页</option></select>')
    add('<button class="pg" id="t-prev">上一页</button>')
    add('<button class="pg" id="t-next">下一页</button>')
    add('<span class="sub" id="t-info"></span>')
    add('</div>')
    add('<div class="scroll" style="max-height:640px"><table><thead><tr>')
    for index, (key, label) in enumerate(TABLE_COLUMNS):
        add(f'<th data-col="{index}" style="cursor:pointer" title="点击排序">'
            f'{html_escape(label)}</th>')
    add('</tr></thead><tbody id="t-body"></tbody></table></div>')
    add('</section>')
    add('</div>')  # p-data

    add('</main>')
    add(f'<footer>由 <code>tools/extended_stability_suite.py</code> 生成；'
        f'证据目录 <code>{html_escape(evidence.name)}/</code>。'
        '报告不依赖任何外部资源（无 CDN、无外链字体），离线可开。</footer>')

    add('<script>')
    add(f'window.__ROWS__ = {js_json(rows)};')
    add(f'window.__COLS__ = {js_json([label for _k, label in TABLE_COLUMNS])};')
    add("""
(function(){
  const tabs = document.querySelectorAll('nav button[role=tab]');
  tabs.forEach(function(btn){
    btn.addEventListener('click', function(){
      tabs.forEach(function(other){
        var on = other === btn;
        other.setAttribute('aria-selected', on ? 'true' : 'false');
        var panel = document.getElementById(other.getAttribute('aria-controls'));
        if (panel) panel.hidden = !on;
      });
    });
  });
})();
""")
    add(TABLE_JS)
    add('</script>')
    add('</body></html>')

    path = evidence / "report.html"
    path.write_text("".join(parts), encoding="utf-8")
    return path


def sampler_interval(samples: Sequence[dict]) -> float | None:
    """The median gap between samples, for the report's description."""
    stamps = [s["at"] for s in samples if s.get("at")]
    if len(stamps) < 2:
        return None
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    return round(statistics.median(gaps), 2)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_manifest(model: str, seed: int) -> dict:
    """Every prompt this run will send, verbatim, with its length and hash.

    Two thousand no-context prompts plus 100 sessions is a lot of JSON
    (~2 MB), and that is the point: the manifest is what makes "the 1200 tier
    really was 1200 characters" checkable after the fact without trusting the
    report. It is written once, before the first request.
    """
    entries: dict = {"seed": seed, "model": model, "tiers": TIERS,
                     "params": PARAMS, "system": SYSTEM_PROMPT,
                     "matrix": {
                         "requests_per_tier_short": REQUESTS_PER_TIER_SHORT,
                         "requests_per_tier_long": REQUESTS_PER_TIER_LONG,
                         "short_tier_count": SHORT_TIER_COUNT,
                         "core_total_per_group": core_total(),
                         "context_sessions": CONTEXT_SESSIONS,
                         "context_turns": CONTEXT_TURNS,
                         "concurrency_lanes": CONCURRENCY_LANES,
                         "concurrency_rounds": CONCURRENCY_ROUNDS,
                         "concurrency_tiers": list(CONCURRENCY_TIERS),
                     },
                     "generated_iso": datetime.now(timezone.utc)
                     .isoformat(timespec="seconds"),
                     "nocxt": [], "cxt": [], "concurrency": []}
    for index, length in enumerate(nocxt_plan(), start=1):
        # ``turn`` is the position inside the 12-tier cycle, and it is what the
        # prompt's round index uses. Using the request number instead (1..1000)
        # would make every prompt unique, which sounds harmless but is not: the
        # no-context group's whole point is to resend the *same* inputs in a
        # loop, and a unique-every-time prompt would never reuse a prefix. With
        # the cycle position, requests 1..10 of every cycle are byte-identical
        # to the ten turns of every context session, which is what "两组使用相同
        # 新输入" has to mean to be checkable.
        turn = (index - 1) % len(TIERS) + 1
        cycle = (index - 1) // len(TIERS)
        entries["nocxt"].append({**base.build_prompt(
            length, turn, seed=seed, lengths=TIERS, recall_target="previous",
            variant=cycle + 1,
            # Only the first CONTEXT_TURNS positions of a cycle mirror a real
            # conversation; the two longer tiers have no counterpart and are
            # sent with no history, so a recall clause there is unanswerable.
            allow_recall=turn <= CONTEXT_TURNS).manifest(),
            "request": index, "cycle": cycle + 1})
    for session_index, ladder in enumerate(context_session_plan(), start=1):
        turns = []
        for turn, length in enumerate(ladder, start=1):
            prompt = base.build_prompt(length, turn, seed=seed, lengths=ladder,
                                       recall_target="previous",
                                       variant=session_index)
            turns.append({**prompt.manifest(), "session": session_index, "turn": turn})
        entries["cxt"].append(turns)
    for round_index in range(1, CONCURRENCY_ROUNDS + 1):
        for lane in range(1, CONCURRENCY_LANES + 1):
            length = CONCURRENCY_TIERS[(round_index + lane) % len(CONCURRENCY_TIERS)]
            marker = concurrency_marker(lane, round_index, CONCURRENCY_LANES)
            prompt = base.build_prompt(length, 1000 + round_index * 10 + lane,
                                       seed=seed, lengths=TIERS, marker=marker,
                                       variant=lane)
            entries["concurrency"].append({**prompt.manifest(),
                                           "round": round_index, "lane": lane})
    return entries


def make_run_dir(base_dir: Path) -> Path:
    """A fresh ``run-*`` directory; reusing one is refused, not merged."""
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
        run = base_dir / f"run-{stamp}{suffix}"
        try:
            run.mkdir()
        except FileExistsError:
            continue
        (run / "raw").mkdir()
        return run
    raise SystemExit(f"cannot find a free run directory under {base_dir}")


#: Files a resumed run copies from its source so the new report's evidence
#: directory is self-contained. ``rounds.jsonl`` is rebuilt from the adopted rows
#: (with the resume recorded), not copied.
RESUME_FILES = ("manifest.json", "env.json")

#: Directories copied wholesale. ``raw`` is the per-request SSE/JSON bodies; the
#: report links nothing into it, but an operator explaining a failure needs it
#: beside the report rather than in a sibling directory.
RESUME_DIRS = ("raw",)


def adopt_previous_run(source: Path, evidence: Path,
                       skip_groups: Iterable[str] = ()) -> tuple[list[Round], dict]:
    """Take the request rows (and raw bodies) of an earlier run into a new one.

    Why this exists rather than "just re-run everything": the phases cost very
    different amounts. The 2000 core requests take about two and a half hours on
    this board; the readiness probe takes the length of one model load. If the
    probe has a harness bug -- and on the first MYS-2501 run it did -- redoing the
    core groups to get a report would burn hours and, worse, replace real evidence
    with a second sample. The task card forbids the second half of that ("不能以
    重跑覆盖错误"), and the first half is simply waste.

    Every adopted row keeps its original timestamps, so the merged timeline stays
    truthful about when each request actually happened. The new run's own rows are
    appended after, and the report's timeframe spans both.

    The source directory is read only; nothing in it is modified. The copy is
    line-by-line so a truncated source (a run killed mid-write) yields the rows it
    did have instead of failing.

    ``skip_groups`` names phases this run is about to redo, and their old rows are
    *not* adopted. Merging them would put two readiness probes in one report
    while the summary described only one of them -- a reader counting rows would
    get a different answer from the headline. Evidence for a phase that is being
    re-run stays in the old directory, where it still is.
    """
    if not source.is_dir():
        raise SystemExit(f"--resume-from {source} is not a directory")
    rounds_path = source / "rounds.jsonl"
    if not rounds_path.is_file():
        raise SystemExit(f"--resume-from {source} has no rounds.jsonl")
    rows: list[Round] = []
    skipped: list[str] = []
    replaced = 0
    skip = set(skip_groups)
    for line in rounds_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            skipped.append(line[:80])
            continue
        row = _round_from_row(payload)
        if row is None:
            skipped.append(line[:80])
            continue
        if row.group in skip:
            replaced += 1
            continue
        rows.append(row)
    note: dict = {
        "source": str(source),
        "source_name": source.name,
        "adopted_rows": len(rows),
        "adopted_groups": sorted({r.group for r in rows}),
        "skipped_lines": skipped[:20],
        "skipped_count": len(skipped),
        "not_adopted_rerun_groups": sorted(skip),
        "not_adopted_rows": replaced,
    }
    for name in RESUME_FILES:
        origin = source / name
        if origin.is_file() and not (evidence / name).exists():
            (evidence / name).write_bytes(origin.read_bytes())
    for name in RESUME_DIRS:
        origin = source / name
        if not origin.is_dir():
            continue
        target = evidence / name
        target.mkdir(exist_ok=True)
        copied = 0
        for item in origin.iterdir():
            if not item.is_file():
                continue
            destination = target / item.name
            # Never overwrite this run's own capture: it names files by request,
            # and a clash would mean the two runs disagreed about a request id.
            if destination.exists():
                continue
            destination.write_bytes(item.read_bytes())
            copied += 1
        note[f"{name}_copied"] = copied
    # The source's own manifest is the authority on what those rows actually
    # sent. It is kept in the note (not written into this run's directory, which
    # gets a freshly built one) and used to restore ``input_text`` below.
    note["manifest"] = None
    try:
        source_manifest = json.loads(
            (source / "manifest.json").read_text(encoding="utf-8"))
        note["manifest"] = source_manifest
        note["manifest_seed"] = source_manifest.get("seed")
        note["manifest_model"] = source_manifest.get("model")
    except (OSError, json.JSONDecodeError):
        pass
    return rows, note


def backfill_inputs(rows: Sequence[Round], manifest: dict) -> dict:
    """Restore ``input_text`` on rows that came from a JSONL.

    The JSONL deliberately omits the full prompt (the manifest carries every text
    once, rather than repeating it in 2100 rows), so a row read back from disk has
    only ``input_chars`` and ``input_sha256``. Two things depend on the text
    itself:

    * the record cross-check, which compares the record's last user message with
      what the client sent -- without it every adopted row reports an input
      mismatch, which is what happened on the first resume (2100 false
      mismatches);
    * the report's input column, which would otherwise be blank for exactly the
      rows an operator most wants to inspect.

    The manifest is the authoritative source, and the row's own
    ``input_sha256`` is the check that the text found there really is the text
    that was sent: a mismatch leaves the row unbackfilled and is counted, never
    silently accepted. Rows from this run already have their text and are left
    alone.
    """
    index: dict[tuple, str] = {}
    #: Every text in the manifest, keyed by its SHA-256. Built from *all* entries,
    #: not from ``index``: the no-context group sends 1000 requests that cycle
    #: through 12 ladder positions, so its structural key collapses to 12 entries
    #: and only the last cycle would survive. The hash does not collapse -- it is
    #: what distinguishes one cycle's 300-character prompt from another's.
    by_hash: dict[str, str] = {}

    def remember(key: tuple, text: str) -> None:
        index[key] = text
        if text:
            by_hash[base.sha256(text)] = text

    for entry in manifest.get("nocxt") or []:
        # Structural key: the *prompt* round index (``round``), because that is
        # what a row stores. It is deliberately last-writer-wins and only ever a
        # hint -- the hash is what decides.
        remember(("nocxt", int(entry.get("round") or 0)), entry.get("text") or "")
    for session in manifest.get("cxt") or []:
        for entry in session:
            remember(("cxt", int(entry.get("session") or 0),
                      int(entry.get("turn") or 0)), entry.get("text") or "")
    for entry in manifest.get("concurrency") or []:
        remember(("conc", int(entry.get("round") or 0), int(entry.get("lane") or 0)),
                 entry.get("text") or "")

    filled = 0
    mismatched: list[dict] = []
    missing = 0
    # Prompt round indices repeat across sessions, cycles and rounds, so a
    # ``(group, round)`` key is not unique for anything but an in-cycle position.
    # The SHA-256 is: it is what the row recorded about the text it actually
    # sent. Everything below therefore looks up by hash first and only uses a
    # structural key as a starting candidate -- a structural hit is still hashed
    # before it is accepted.
    for row in rows:
        if row.input_text:
            continue
        # Hash first. It is the only lookup that is unique across a run: the
        # structural keys repeat (12 no-context ladder positions for 1000
        # requests, 10 turns per session for 100 sessions), so trusting one first
        # returns a text from some other cycle -- which then fails the hash check
        # and is reported as a mismatch even though the right text is present.
        text: str | None = by_hash.get(row.input_sha256 or "")
        if text is None and row.group == "cxt" and row.session and row.turn:
            text = index.get(("cxt", int(row.session), int(row.turn)))
        if text is None and row.group == "nocxt" and row.round_index:
            text = index.get(("nocxt", int(row.round_index)))
        if text is None:
            # A refusal during a load never reaches the model, so it has no prompt
            # in the manifest and none is needed -- counting it as "missing" would
            # turn the correct outcome into a reported defect.
            if row.group.startswith("readiness"):
                continue
            missing += 1
            continue
        if row.input_sha256 and base.sha256(text) != row.input_sha256:
            mismatched.append({"group": row.group, "round": row.round_index,
                               "session": row.session, "turn": row.turn})
            continue
        row.input_text = text
        row.input_chars = base.chars(text)
        filled += 1
    return {"filled": filled, "missing": missing, "hash_mismatch": mismatched[:20],
            "hash_mismatch_count": len(mismatched)}


def _find_by_hash(index: dict, digest: str | None) -> str | None:
    """The manifest text whose SHA-256 matches, if exactly one does."""
    if not digest:
        return None
    hits = [text for text in index.values() if base.sha256(text) == digest]
    return hits[0] if len(hits) == 1 else None


def _round_from_row(payload: dict) -> Round | None:
    """Rebuild a :class:`Round` from one JSONL line, or ``None`` if unusable.

    Only the dataclass fields are taken, and unknown keys are ignored: a row from
    an older build that lacks a column must still load (with that column null),
    while a row that is not an object at all is refused rather than guessed at.
    ``input_text`` was dropped on the way out (the manifest carries every text),
    so a resumed row's input comparison is limited to ``input_chars`` and
    ``input_sha256`` -- which is what the record check uses anyway.
    """
    if not isinstance(payload, dict) or "group" not in payload:
        return None
    row = Round(group=str(payload["group"]),
                round_index=int(payload.get("round_index") or 0),
                tier=int(payload.get("tier") or 0))
    for name in Round.__dataclass_fields__:
        if name in ("group", "round_index", "tier") or name not in payload:
            continue
        setattr(row, name, payload[name])
    return row


def create_key(http: base.Http, name: str) -> tuple[str, str]:
    """Mint this run's API key. The raw value stays in memory and in env only."""
    status, body = http.json("POST", "/api/keys", {"name": name}, timeout=60)
    if status != 200 or not body.get("key"):
        raise SystemExit(f"key creation failed: HTTP {status} {body}")
    return body["key"], body["meta"]["id"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extended stability suite (MYS-2501): 2000 core requests, "
                    "100 concurrent, a readiness probe, one self-contained HTML report.")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--password",
                    default=os.environ.get("CV84X6_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--evidence-dir", default="./stability-evidence")
    ap.add_argument("--data-dir", default="/data/cv84x6_llm_server")
    ap.add_argument("--device-label", default="172.26.166.96:10151 (.151)")
    ap.add_argument("--model", default=None, help="model id (default: the loaded one)")
    ap.add_argument("--api-key", default=None,
                    help="reuse this key instead of minting one (never written to evidence)")
    ap.add_argument("--key-name", default=KEY_NAME_DEFAULT)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--seed", type=int, default=base.SEED)
    ap.add_argument("--sample-interval", type=float, default=5.0)
    ap.add_argument("--skip-core", action="store_true",
                    help="skip the core and concurrency groups")
    ap.add_argument("--resume-from", default=None, metavar="RUN_DIR",
                    help="adopt the request rows and evidence files from an earlier "
                         "run directory and only run the phases still missing. The "
                         "report then covers both, and the source directory is left "
                         "untouched.")
    ap.add_argument("--readiness", action="store_true",
                    help="run the stop/reload readiness probe after the core groups")
    ap.add_argument("--load-timeout", type=float, default=900.0)
    args = ap.parse_args(argv)

    evidence = make_run_dir(Path(args.evidence_dir))
    raw_dir = evidence / "raw"
    print(f"evidence: {evidence}", flush=True)

    adopted: list[Round] = []
    resume_note: dict = {}
    if args.resume_from:
        # Only the readiness phase is ever re-run, so only its old rows are
        # dropped; the core and concurrency rows are the whole reason to resume.
        rerun = list(READINESS_GROUPS) if args.readiness else []
        adopted, resume_note = adopt_previous_run(Path(args.resume_from), evidence,
                                                  skip_groups=rerun)
        print(f"resumed: adopted {len(adopted)} request rows from "
              f"{Path(args.resume_from).name}", flush=True)

    http = base.Http(args.base, timeout=max(args.timeout, 120.0))
    if http.login(args.password) != 200:
        raise SystemExit("console login failed")

    model = args.model or base.pick_model(http)
    print(f"model: {model}", flush=True)

    key = args.api_key
    key_id: str | None = None
    if not key:
        key, key_id = create_key(http, args.key_name)
        print(f"api key: minted {args.key_name}", flush=True)
    else:
        print("api key: reused from --api-key", flush=True)

    timeline = Timeline(evidence / "timeline.jsonl")
    sampler = Sampler(http, args.sample_interval)
    env: dict = {}

    runner = Runner(http, key, model, evidence, raw_dir, timeline, args.timeout)
    runner.rounds = list(adopted)
    if adopted:
        timeline.add("phase", "沿用上一轮请求证据",
                     f"从 {Path(args.resume_from).name} 接管 {len(adopted)} 条请求行；"
                     "本轮只运行缺失的阶段", count=len(adopted))
    sampler.start()
    exit_code = 1
    try:
        env = base.capture_environment(http, Path(args.data_dir))
        (evidence / "env.json").write_text(
            json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")
        # A resumed run renders the report from rows whose prompt text was not in
        # the JSONL. Rebuilding the manifest (same seed and model ⇒ same prompts)
        # and backfilling from it is what keeps the record check meaningful;
        # ``backfill`` verifies each restore against the row's own SHA-256.
        manifest = build_manifest(model, args.seed)
        if resume_note:
            manifest_for_rows = resume_note.get("manifest") or manifest
            backfilled = backfill_inputs(runner.rounds, manifest_for_rows)
            resume_note["inputs"] = backfilled
            if backfilled["filled"] or backfilled["missing"] or \
                    backfilled["hash_mismatch_count"]:
                timeline.add(
                    "note", "补全沿用行的 prompt 原文",
                    f"命中 manifest {backfilled['filled']} 条，"
                    f"缺失 {backfilled['missing']} 条，"
                    f"hash 不符 {backfilled['hash_mismatch_count']} 条",
                    count=backfilled["filled"])
            if backfilled["hash_mismatch_count"]:
                timeline.anomaly(
                    "沿用行与 manifest 原文不一致",
                    f"{backfilled['hash_mismatch_count']} 条行的 SHA-256 与 manifest 不匹配"
                    "（已跳过，不猜）")
        (evidence / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        timeline.add("phase", "环境采集完成",
                     f"模型 {model}，版本 "
                     f"{(env.get('service') or {}).get('version_pkg')}")

        have_core = any(r.group in CORE_GROUPS for r in runner.rounds)
        have_conc = any(r.group == "conc" for r in runner.rounds)
        if not args.skip_core and not have_core:
            runner.run_nocxt()
            runner.run_cxt()
        if not args.skip_core and not have_conc:
            runner.run_concurrency()
        readiness_info: dict = {}
        if args.readiness:
            readiness_info = runner.run_readiness(args.password, model,
                                                  args.load_timeout)
        runner.close()
        timeline.add("phase", "请求阶段结束", f"共 {len(runner.rounds)} 条记录")
    except BaseException:
        traceback.print_exc()
        timeline.anomaly("运行中断", traceback.format_exc()[-1200:])
        try:
            runner.close()
        except Exception:  # noqa: BLE001
            pass
        readiness_info = locals().get("readiness_info") or {}
    finally:
        sampler.stop()

    summary: dict = {"groups": {}, "by_tier": {}, "totals": {}}
    records: dict = {}
    db: dict = {"readable": False, "found": 0, "expected": 0, "missing": [],
                "output_mismatch": [], "exists": False, "bytes": None,
                "error": "not checked"}
    gate: dict = {"passed": False}
    rounds = runner.rounds
    try:
        # Verification only makes sense for requests the service actually ran; a
        # 409 refusal correctly has no record, so readiness rows are excluded
        # from the record cross-check and judged by the readiness criteria.
        checkable = [r for r in rounds if r.group in (*CORE_GROUPS, "conc", "readiness-after")]
        details, no_ids = base.fetch_records(http, checkable)
        counts, export_lines = base.export_records(
            http, evidence / "records-export.ndjson")
        records = base.verify_records(checkable, details, counts, key)
        records["no_record_ids"] = no_ids
        records["export_lines"] = export_lines
        db = base.sqlite_check(base.record_log_path(env, args.data_dir), checkable)
        summary = summarize(rounds, readiness_info or None)
        gate = verdict(summary, records, db, readiness_info or None)
        # The JSONL was written row by row during the run; rewrite it now that
        # verification adopted the server-side numbers.
        tmp = (evidence / "rounds.jsonl").with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rounds:
                fh.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
        os.replace(tmp, evidence / "rounds.jsonl")
    except Exception:  # noqa: BLE001 - a broken verification still leaves a report
        traceback.print_exc()
        records.setdefault("verification_error", traceback.format_exc()[-2000:])
        summary = summarize(rounds, readiness_info or None) if rounds else summary
        timeline.anomaly("记录核对失败", traceback.format_exc()[-600:])

    timeline.close()
    samples = sampler.snapshot()
    if samples:
        (evidence / "samples.json").write_text(
            json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    dmesg = base.run_cmd(["sudo", "-n", "dmesg"], timeout=90)
    (evidence / "dmesg.txt").write_text(dmesg, encoding="utf-8")
    window = min((r.started_at for r in rounds if r.started_at), default=time.time())
    (evidence / "journal-test.txt").write_text(
        base.run_cmd(["sudo", "-n", "journalctl", "-u", "cv84x6-llm",
                      "--since", f"@{int(window) - 60}", "--no-pager"], timeout=240),
        encoding="utf-8")
    (evidence / "records-check.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (evidence / "sqlite-check.json").write_text(
        json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    summary["verdict"] = gate
    summary["timeline"] = [e.as_dict() for e in timeline.entries]
    if resume_note:
        summary["resumed_from"] = {k: v for k, v in resume_note.items()
                                   if k != "manifest"}
    (evidence / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (evidence / "evidence.json").write_text(
        json.dumps({"env": env, "records": records, "sqlite": db, "gate": gate,
                    "resumed_from": ({k: v for k, v in resume_note.items()
                                      if k != "manifest"} if resume_note else None)},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    report = build_html(evidence, env, summary, records, db, readiness_info or {},
                        gate, {"model": model, "seed": args.seed, "params": PARAMS,
                               "system": SYSTEM_PROMPT},
                        rounds, timeline.entries, samples, args.device_label,
                        resume_note or None)

    if key_id:
        status, _ = http.json("DELETE", f"/api/keys/{key_id}", timeout=30)
        print(f"cleanup: removed key {args.key_name} (HTTP {status})", flush=True)

    print(f"report: {report}", flush=True)
    print(f"verdict: {'PASS' if gate.get('passed') else 'FAIL'}", flush=True)
    for name, value in gate.items():
        print(f"  {name}: {value}", flush=True)
    npu_errors = [ln for ln in dmesg.splitlines()
                  if "wait api timeout" in ln or "bdc_reg_read" in ln]
    if npu_errors:
        print("NPU error signature in dmesg -- stop and report, do not retry:", flush=True)
        for line in npu_errors[-3:]:
            print("  " + line, flush=True)
    exit_code = 0 if gate.get("passed") else 1
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - a traceback is evidence too
        traceback.print_exc()
        sys.exit(2)
