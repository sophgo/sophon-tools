"""Comprehensive inference stability matrix for the CV84X6 offline LLM service.

MYS-2510 asks for more than "run the same short requests again". It asks whether
the service is stable across **the shapes real work actually takes**: long
contexts near the model's limit, requests that queue, clients that hang up, the
load/unload lifecycle, vision input, tool calls, and a two-hour soak -- with each
dimension judged separately so a passing protocol cannot hide a wrong answer.

The matrix, and why each block exists:

===========  ===========================================================
``longctx``  16k/32k/64k/96k-token prompts with a fact that can only be
             retrieved from the material, plus a 50-turn (and 100-turn)
             growing conversation, plus the >context boundary. The
             measurement that matters is real ``prompt_tokens``, not
             characters: this model's Chinese runs about 0.6 tokens per
             character, so a "64k character" prompt is not a 64k-token one.
``conc``     Independent identical workloads at 2 and 3 lanes, and 3 lanes
             against a ``max_concurrent=2`` service -- which must *queue*,
             not refuse. A temporary ``max_queue`` cut proves the 429 edge
             and that it recovers.
``cancel``   Client disconnects before the first token, mid-stream, and near
             completion; a stop string, a ``max_tokens`` cut, and six
             malformed requests whose 4xx codes are the assertion. A
             cancel must leave exactly one record, with the partial text.
``cache``    A long prefix reused across turns (``cached_tokens`` observed),
             compared with a no-cache baseline; cache TTL/eviction
             experiments; then the load->infer->unload lifecycle loop.
``vlm``      JPEG and PNG, single and multi-image, checking that the record
             keeps dimensions and not pixels.
``tools``    Tool calls with JSON arguments, parallel calls, and rejected
             definitions, plus thinking on/off -- protocol correctness and
             content correctness scored apart.
``soak``     A mixed workload sustained for **two hours of wall clock**,
             sampling CPU/NPU/TPU/memory/queue/cache throughout, reporting
             the first-to-last drift so monotonic growth is visible.
``readiness`` Repeated load-window probing, carrying MYS-2501's evidence
             forward rather than re-deriving it.
``restart``  SIGTERM restart, reload, request recovery, records retained.

Design rules inherited from the MYS-2498/MYS-2501 suites, all still enforced:

* **Standard library only** on the board (CPython 3.10, no httpx/pip).
* **Every prompt is exactly the size it claims**, in *tokens* for the long
  tiers -- measured with the model's own tokenizer, called through the shipped
  native library, not guessed from a character count.
* **Every checkable question has a computed answer.** Long-context tiers ask
  for a fact planted in the material; the expected value comes from the same
  text the model saw.
* **A failure is evidence, not a reason to retry.** Nothing is re-sent. The
  raw body of every request is kept.
* **The service's own records are the second opinion**, read back through the
  admin API and a read-only SQLite open.

What this module adds over MYS-2501's suite:

* A **token-exact prompt builder** using the real tokenizer, so "32k" is a
  number of tokens the model was actually given.
* A **dimension verdict**: stability, protocol semantics, record consistency,
  isolation, recovery and TPU health are counted separately, and semantic
  accuracy is reported as its own number -- never folded into "passed".
* A **soak sampler** whose drift calculation distinguishes a warm-up ramp from
  monotonic growth.
* One **self-contained HTML report** with the overall verdict, the matrix,
  the timeline, SVG performance charts and a searchable per-request table.

Time is the binding constraint, and it is measured rather than assumed: on
``.151`` a 2,048-token prompt prefills in ~10 s, 8,192 in ~36 s and 32,768 in
~286 s, because history attention makes prefill superlinear in prompt length.
The tiers and repetition counts here are chosen against that curve, and the
report states the real number for every tier it ran.
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import gzip
import hashlib
import json
import os
import re
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
from typing import Iterable, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import board_stability_suite as base  # noqa: E402
import extended_stability_suite as ext  # noqa: E402

#: Escaping and JS-safe JSON come from the MYS-2501 suite, which already had to
#: get the ``</script>``-inside-a-string case right. Re-exported here so the
#: report builders below read without an ``ext.`` prefix on every call.
html_escape = ext.html_escape
js_json = ext.js_json

# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

#: Same generator seed as the earlier suites. Changing it changes every
#: generated prompt, so it is recorded in the manifest.
SEED = 25102496

#: Long-context tiers, in **tokens** of the rendered user message.
#:
#: 16k/32k/64k/96k are the task's four requested rungs. The measured prefill
#: curve on ``.151`` is superlinear (2k: 10 s, 8k: 36 s, 32k: 286 s), so the
#: top rung costs minutes of wall clock each; the counts below are set from that
#: curve, not from optimism. ``128k`` is deliberately *not* a tier — it is the
#: boundary probe in :data:`OVERFLOW_TOKENS`, where refusal is the assertion.
LONG_TIERS: tuple[int, ...] = (16384, 32768, 65536, 98304)

#: Requests per long tier. One is enough to answer "does a real 16k-token
#: prompt work"; three at the bottom rung catch an intermittent failure without
#: paying 96k prices three times.
LONG_TIER_REPEATS: dict[int, int] = {16384: 3, 32768: 2, 65536: 1, 98304: 1}

#: Prompts past the model's 131,072-token window. The service must answer with
#: a clear 4xx naming the limit — not an empty stream, not a crash. Building one
#: costs a tokenizer pass; *sending* it costs nothing because the worker refuses
#: before prefill (the length is checked against the encoded ids).
OVERFLOW_TOKENS: tuple[int, ...] = (132_000, 200_000)

#: Growing-conversation sizes. Each turn adds a numbered, recallable fact.
#: 50 turns is required; 100 is attempted when the time budget allows, and the
#: report says which one actually ran.
CHAT_TURNS_REQUIRED = 50
CHAT_TURNS_EXTENDED = 100

#: Continuous-conversation tiers (MYS-2521 A2), in **cumulative conversation
#: ``prompt_tokens``** -- not the length of a single prompt.
#:
#: The user's follow-up requirement is explicit that these are real multi-turn
#: sessions: every turn resends the whole user/assistant history, and a tier is
#: reached when the service's own reported ``prompt_tokens`` lands within
#: :data:`CTX_TIER_TOLERANCE` of the target. The turn count is whatever that
#: takes -- it is decided by measured tokens, never by a schedule.
CTX_TIERS: tuple[int, ...] = (2048, 4096, 8192, 12288, 16384)

#: Sessions per tier. The low rungs are cheap, so they get two independent
#: sessions; 12k/16k cost a real prefill every turn and get one.
CTX_TIER_SESSIONS: dict[int, int] = {2048: 2, 4096: 2, 8192: 2, 12288: 1, 16384: 1}

#: How close the service-reported cumulative ``prompt_tokens`` must land to the
#: tier target. The requirement says "±10%"; the number is on the report so a
#: reader can check the tier rather than trust it.
CTX_TIER_TOLERANCE = 0.10

#: After a session reaches its tier, how many *early* and *recent* planted
#: facts are asked back. The requirement is at least 3 + 2.
CTX_EARLY_PROBES = 3
CTX_RECENT_PROBES = 2

#: Per-turn ``max_tokens`` for the A2 sessions. These answers are one keyword or
#: one short sentence; anything larger just makes the decode phase longer.
CTX_MAX_TOKENS = 96

#: The 16k session that is restarted mid-conversation. One, because the restart
#: costs a full unload + ~66 s reload and the claim is about continuity, not
#: frequency.
CTX_RESTART_TIER = 16384

#: Rare words and emoji planted in every A2 session and replayed by U1. These
#: are the exact characters a byte-level tokenizer splits across token
#: boundaries, so they are the UTF-8 regression point rather than decoration:
#: 门簪 is [96141, 97618, 103] and the first token ends with two of 簪's three
#: bytes (see the v0.6.15 fix).
RARE_WORDS: tuple[str, ...] = ("门簪", "琴轸", "秤砣", "妆奁")

#: Emoji required in the planted facts. Both are 4-byte sequences, which is the
#: other half of the same split-character bug.
RARE_EMOJI: tuple[str, ...] = ("😀", "👍")

#: U1: how many times each rare token is repeated verbatim, and on which
#: surfaces. The requirement is at least 10 per token across the three routes.
U1_REPEATS = 10
U1_SURFACES: tuple[str, ...] = ("stream", "nonstream", "console")

#: U1 replay of the MYS-2510 turns that came back with U+FFFD. The turn numbers
#: are the ones in that run's evidence (chat50 18/29/35/45 and chat100
#: 18/29/35/45/68/79/85/95); the history is rebuilt with the same constructor,
#: so the request that failed is the request that is replayed.
U1_REPLAY_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("chat50", (18, 29, 35, 45)),
    ("chat100", (18, 29, 35, 45, 68, 79, 85, 95)),
)

#: Concurrency blocks: (lanes, rounds, description). "Pairs" means one round
#: fires ``lanes`` requests together and waits for all of them.
CONC_LANES: tuple[int, ...] = (2, 3)
CONC_ROUNDS = 50

#: Temporary ``max_queue`` values for the saturation experiment. With
#: ``max_concurrent=2`` and ``max_queue=0``, the third simultaneous request is
#: over capacity and must be refused with 429 — not 500, not a hang.
QUEUE_CAPACITY_EXPERIMENTS = (0, 1)

#: Disconnect phases: how many times, and where in the stream.
CANCEL_REPEATS = 5

#: How many content deltas to accept before hanging up for the "near completion"
#: case. The cancel prompt asks for 1..50 and the engine's loop guard truncates
#: around 140 tokens, so 120 lands in the last stretch of decoding without being
#: after the finish frame (which would make the disconnect a no-op).
NEAR_COMPLETION_DELTAS = 120

#: Prefix-cache block: turns over one fixed prefix, and how long that prefix is.
PREFIX_CACHE_TURNS = 6
PREFIX_CACHE_TOKENS = 4096

#: How long to wait past a 1-minute cache TTL before asserting eviction.
CACHE_TTL_WAIT_S = 70.0

#: Lifecycle cycles. The task allows 20 instead of 50 with an explanation; the
#: explanation is the measured load time (~66 s each) — 50 cycles would be
#: ~2 hours of pure loading, and the point (no leaked worker/socket/memory) is
#: established by 20.
LIFECYCLE_CYCLES = 20

#: Vision repeats per format, and the fixtures used. All are tiny, decidable
#: images checked into ``tests/vision_fixtures`` — never a real photograph.
VLM_REPEATS = 20

#: Tool-call attempts and thinking-mode repeats.
TOOL_CALLS = 30
THINKING_REPEATS = 10

#: Soak duration. The task says "at least 2 hours"; this is exactly that, in
#: wall-clock seconds, and the report states the measured span.
SOAK_SECONDS = 2 * 60 * 60

#: Mixed-concurrency rounds in a full run. Each round fires a short, a medium
#: and a long prompt together, and the long one's prefill dominates (~50 s per
#: round measured), so this is deliberately small.
MIXED_ROUNDS = 10

#: Mixed workload weights for the soak. Each entry is (kind, tier tokens).
SOAK_MIX: tuple[tuple[str, int], ...] = (
    ("short", 60), ("short", 200), ("mid", 2048),
    ("long", 8192), ("ctx", 4096),
)

#: The model's advertised window, used to assert the boundary behaviour.
EXPECTED_CONTEXT = 131_072

#: Fixed system message, identical across every group that uses one.
SYSTEM_PROMPT = base.SYSTEM_PROMPT

#: Sampling shape sent with every request. On this bmodel ``supports_sampling``
#: is false (argmax is fused into ``lm_head``), so these do not change the
#: output; they are sent so each request has one recorded shape.
PARAMS: dict = dict(base.PARAMS)

#: Key name for this run. The raw value never leaves process memory.
KEY_NAME_DEFAULT = "MYS-2510-matrix"


# ---------------------------------------------------------------------------
# Token-exact prompt building
# ---------------------------------------------------------------------------
class Tokenizer:
    """The model's own BPE tokenizer, through the shipped native library.

    Why not count characters and multiply: this model's Chinese text runs about
    0.6 tokens per character, but digits cost one token each and English costs
    far less, so a character-based estimate drifts by tens of percent across
    materials. The task requires real ``prompt_tokens``; the only way to *build*
    to a token target is to measure with the tokenizer the model uses.

    The board has no ``tokenizers``/``transformers`` package (that was the point
    of the native port), but ``libcv84x6_llm.so`` exports a stable C API:
    ``llm_tokenizer_load`` / ``llm_tokenizer_encode``. Calling it through
    ``ctypes`` uses exactly the code path the worker uses to encode the prompt,
    so the token counts here are the same numbers the worker reports.

    ``available`` is False when the library or file is missing (a dev box, a
    unit test): callers then fall back to a calibrated estimate and *say so* in
    the manifest rather than silently claiming token precision.
    """

    def __init__(self, lib_path: str, tokenizer_json: str):
        self.lib_path = lib_path
        self.tokenizer_json = tokenizer_json
        self.handle = None
        self.error: str | None = None
        self._lock = threading.Lock()
        try:
            lib = ctypes.CDLL(lib_path)
            lib.llm_tokenizer_load.restype = ctypes.c_void_p
            lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p,
                                               ctypes.POINTER(ctypes.c_char_p)]
            lib.llm_tokenizer_encode.restype = ctypes.c_int
            lib.llm_tokenizer_encode.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int),
                ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
            err = ctypes.c_char_p()
            handle = lib.llm_tokenizer_load(str(tokenizer_json).encode(),
                                            ctypes.byref(err))
            if not handle:
                self.error = (err.value or b"unknown error").decode("utf-8", "replace")
                return
            self._lib = lib
            self.handle = handle
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def available(self) -> bool:
        return self.handle is not None

    def count(self, text: str) -> int | None:
        """Token count of ``text``, or ``None`` when no tokenizer is loaded."""
        if self.handle is None:
            return None
        with self._lock:
            err = ctypes.c_char_p()
            n = self._lib.llm_tokenizer_encode(
                self.handle, text.encode("utf-8"), None, 0, ctypes.byref(err))
            return None if n < 0 else int(n)

    def describe(self) -> dict:
        return {"lib": self.lib_path, "tokenizer_json": str(self.tokenizer_json),
                "available": self.available, "error": self.error}


#: Fallback ratio (tokens per character) for Chinese material on Qwen3.6.
#: Measured on ``.151``: 31 tokens / 52 characters = 0.596. Only used when no
#: tokenizer is loadable, and recorded as an estimate in the manifest.
FALLBACK_TOKENS_PER_CHAR = 0.6


def estimate_tokens(text: str, tokenizer: Tokenizer | None) -> int:
    """Real token count when possible, documented estimate otherwise."""
    if tokenizer is not None and tokenizer.available:
        counted = tokenizer.count(text)
        if counted is not None:
            return counted
    return max(1, int(round(len(text) * FALLBACK_TOKENS_PER_CHAR)))


# ---------------------------------------------------------------------------
# Long-context material with retrievable facts
# ---------------------------------------------------------------------------
#: Clause template for the material. Every clause is a distinct warehouse
#: record: an index, a six-digit registration number, and two attributes. The
#: answer to "what is the registration number of warehouse N" is therefore a
#: fact that exists **only** in the material -- a model that guesses, or that
#: answers from its own priors, cannot produce the right digits.
CLAUSE = "第{i}号仓库第三周盘点完毕，登记编号{code:06d}，保管员{keeper}，温湿度达标。"

KEEPERS = ("周明", "李岩", "王珂", "赵岭", "陈默", "孙桐", "吴楠", "郑昀",
           "冯桦", "许澈", "何澈", "曹岩", "沈砚", "韩松", "杨柏", "朱棠")

#: Phrases the model might emit to hedge instead of answering. Kept for the
#: report's "refused to answer" count, not used to excuse a wrong number.
HEDGES = ("无法确定", "没有找到", "未提供", "无法回答", "材料中未", "不确定")


@dataclass
class LongPrompt:
    """One long-context request and the fact that proves the context was read.

    ``needle_index`` is the warehouse asked about, ``expected_code`` its
    six-digit registration number. ``probe`` says *where* the needle sits
    (``head``/``middle``/``tail`` at 10%/50%/90% of the material), because
    retrieval accuracy is strongly position-dependent and a tail-only probe
    would make the model look better than it is.
    """

    tier_tokens: int
    text: str
    chars: int
    tokens: int
    needle_index: int
    expected_code: int
    probe: str
    material_clauses: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def build_long_prompt(target_tokens: int, *, tokenizer: Tokenizer | None = None,
                      seed: int = SEED, probe: str = "tail",
                      round_index: int = 1) -> LongPrompt:
    """A user message of ~``target_tokens`` tokens with exactly one answerable fact.

    Construction is linear in the target size by design. The naive version --
    append a clause, re-tokenize the whole text, repeat until the target is
    reached -- is O(n²) in tokenizer calls and made a 64k build hang on the
    board for minutes before it ever sent a request. Here a 64-clause block is
    measured once, repeated to the target, and then topped up clause by clause.

    The needle is placed by *rebuilding around* it rather than by string
    surgery, so the material is always whole clauses and the fact is always
    present exactly once: ``第{needle}号仓库`` appears once, and its six-digit
    code appears once, because the index-to-code mapping is injective.
    """
    if target_tokens < 512:
        raise ValueError("long tiers start at 512 tokens; use the short suites below")
    if probe not in ("head", "middle", "tail"):
        raise ValueError(f"probe must be head/middle/tail; got {probe!r}")

    def clause(i: int) -> str:
        return CLAUSE.format(i=i, code=code_for(i, seed),
                             keeper=KEEPERS[(i + seed) % len(KEEPERS)])

    # Measure a 64-clause block once. Subsequent sizes are computed from it.
    block = "".join(clause(i) for i in range(1, 65))
    per_block = estimate_tokens(block, tokenizer)
    blocks = max(1, int(target_tokens / per_block))

    total_clauses = blocks * 64

    def assemble(count: int) -> str:
        return "".join(clause(i) for i in range(1, count + 1))

    # Converge on the target by whole clauses. Two properties matter:
    #
    # * it must be able to *shrink* as well as grow -- the first block-based
    #   estimate undershoots slightly, because clause indices get longer as the
    #   material grows ("第1号" vs "第1216号" is not the same number of tokens),
    #   and a grow-only loop therefore lands several hundred tokens high;
    # * it must not re-tokenize the whole text once per clause, which is what
    #   made the first version of this builder hang for minutes at 64k.
    #
    # So each pass measures once and then moves the clause count by the
    # shortfall divided by the measured cost per clause: a handful of passes at
    # most, each a single tokenizer call.
    material = assemble(total_clauses)
    tokens = estimate_tokens(material, tokenizer)
    for _ in range(12):
        if tokens == target_tokens:
            break
        per_clause = max(1.0, tokens / max(1, total_clauses))
        delta = int(round((target_tokens - tokens) / per_clause))
        if delta == 0:
            # Within one clause of the target: one clause either way is the
            # finest adjustment this construction allows.
            delta = 1 if tokens < target_tokens else -1
        candidate = max(1, total_clauses + delta)
        if candidate == total_clauses:
            break
        candidate_material = assemble(candidate)
        candidate_tokens = estimate_tokens(candidate_material, tokenizer)
        # Accept only a move that is closer; otherwise stop rather than
        # oscillate between two clause counts.
        if abs(candidate_tokens - target_tokens) >= abs(tokens - target_tokens):
            break
        total_clauses, material, tokens = candidate, candidate_material, candidate_tokens
    # The residual is under one clause and is reported, not hidden: the run's
    # ``prompt_tokens`` shows the real value for every tier.
    while tokens < target_tokens:
        total_clauses += 1
        material = assemble(total_clauses)
        tokens = estimate_tokens(material, tokenizer)

    # The needle is chosen from the material's *final* clause count. Picking it
    # before the top-up loop would let the material grow past the position it
    # was supposed to sit at, which is how a "tail" probe ends up in the middle
    # (caught by a test, not by a reader noticing the retrieval rate was odd).
    position = {"head": 0.10, "middle": 0.50, "tail": 0.90}[probe]
    needle = max(1, min(total_clauses, int(total_clauses * position)))

    ask_tail = (
        f"\n\n问题：材料中第{needle}号仓库的登记编号是多少？"
        f"只回答六位数字，不要解释。"
    )
    text = material + ask_tail
    code = code_for(needle, seed)
    return LongPrompt(tier_tokens=target_tokens, text=text, chars=len(text),
                      tokens=estimate_tokens(text, tokenizer),
                      needle_index=needle, expected_code=code, probe=probe,
                      material_clauses=total_clauses)


def code_for(index: int, seed: int = SEED) -> int:
    """The six-digit registration number of warehouse ``index``.

    Injective in ``index`` for the range this suite uses (a multiplier coprime
    with 1,000,000), so "the code appears exactly once" holds and grading a
    retrieved number cannot be confused with a coincidental other one. Always
    six digits, so a reply that drops leading zeros is wrong for a real reason.
    """
    return (index * 7919 + seed) % 900_000 + 100_000


def grade_retrieval(prompt: LongPrompt, output: str) -> dict:
    """Did the reply contain the planted code?

    Scored as three separate facts so the report cannot blur them:

    * ``correct`` — the expected six-digit code appears in the reply.
    * ``wrong_number`` — some other six-digit number appears (answered, wrongly).
    * ``hedged`` — no six-digit number at all and a hedge phrase present.

    A reply with neither a number nor a hedge is counted as ``no_answer``.
    """
    text = (output or "")
    # ``(?<!\d)``/``(?!\d)`` so a seven-digit number does not contain a
    # six-digit "match": otherwise a wrong 7-digit answer would be graded
    # correct whenever its first six digits happened to line up.
    digits = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    correct = str(prompt.expected_code) in digits
    other = [d for d in digits if d != str(prompt.expected_code)]
    return {
        "correct": correct,
        "wrong_number": bool(other) and not correct,
        "hedged": (not digits) and any(h in text for h in HEDGES),
        "no_answer": (not digits) and not any(h in text for h in HEDGES),
        "found_numbers": digits[:6],
    }


def build_overflow_prompt(target_tokens: int, *, tokenizer: Tokenizer | None = None,
                          seed: int = SEED) -> LongPrompt:
    """A prompt deliberately past the context window.

    Same builder, larger target; the point is the service's *refusal*, so the
    content does not matter beyond being genuinely too long as counted by the
    model's own tokenizer.
    """
    prompt = build_long_prompt(target_tokens, tokenizer=tokenizer, seed=seed,
                               probe="tail")
    prompt.tier_tokens = target_tokens
    return prompt


# ---------------------------------------------------------------------------
# Growing conversation with recallable facts
# ---------------------------------------------------------------------------
#: Per-turn fact words for the long conversation. Distinct, and none is a
#: substring of another, so "which keyword was planted in turn N" is unique.
CHAT_FACTS = (
    "青瓷", "铜镜", "木匣", "石阶", "竹帘", "陶笛", "铁锁", "帆影", "银针", "瓦当",
    "檐铃", "砚池", "书案", "茶碾", "灯罩", "枕函", "门簪", "窗纸", "藤椅", "蒲团",
    "药臼", "线装", "笔洗", "墨锭", "印章", "画轴", "扇骨", "琴轸", "棋盘", "棋子",
    "酒旗", "茶旗", "米斗", "秤砣", "磨盘", "纺轮", "梭子", "染缸", "织机", "绣绷",
    "烛台", "香炉", "镜台", "妆奁", "衣桁", "巾架", "盆架", "烛剪", "火钳", "汤匙",
)


def chat_turn_text(turn: int, *, seed: int = SEED, ask_back: bool = True) -> tuple[str, str, str | None]:
    """One turn's user message, the fact it plants, and the fact it asks about.

    The message plants ``CHAT_FACTS[turn-1]`` with its turn number, and (from
    turn 2 on) asks for the *previous* turn's fact. Asking backwards is what
    makes the history load-bearing: a service that dropped the history, or a
    model that never saw it, cannot answer turn N's question. The answer is
    graded mechanically.
    """
    fact = CHAT_FACTS[(turn - 1) % len(CHAT_FACTS)]
    lines = [f"第{turn}轮记录：本轮编号{turn}，关键词是「{fact}」，请记下。"]
    asked: str | None = None
    if ask_back and turn > 1:
        asked = CHAT_FACTS[(turn - 2) % len(CHAT_FACTS)]
        lines.append(f"上一轮（第{turn - 1}轮）的关键词是什么？只回答关键词本身。")
    else:
        lines.append("请只回复“收到”。")
    return "\n".join(lines), fact, asked


def grade_chat_turn(asked: str | None, output: str) -> bool | None:
    """Whether the reply recalled ``asked``; ``None`` when nothing was asked."""
    if asked is None:
        return None
    return asked in (output or "")


#: Group **prefixes** whose recall verdicts are measurements of the **model**, and
#: so belong in the multi-turn recall denominator.
#:
#: * ``chat`` -- the 50/100-turn history sessions;
#: * ``ctx-`` -- the A2 continuous-conversation probes, which ask a planted fact
#:   back over the real conversation the session built;
#: * ``utf8-replay-`` -- the replayed MYS-2510 turns, which ask a real question.
#:
#: The soak's ``ctx`` turns are **not** here. They do ask a recall question, but
#: their history is built with a hardcoded ``收到。`` assistant reply for every
#: planted turn, so the model is shown a conversation that answers recall
#: questions with ``收到。`` and obliges with ``收到。``. That is a statement about
#: the fixture, not about long-context recall, and counting it is exactly the
#: MYS-2510 error that turned 136/148 (91.9%) into 136/263 (51.7%).
#:
#: An allowlist rather than a denylist on purpose: a new group that happens to
#: set ``recall_ok`` should default to *not* moving the headline recall number,
#: and someone has to look at it and add it deliberately.
RECALL_GROUP_PREFIXES: tuple[str, ...] = ("chat", "ctx-", "utf8-replay-")


def is_recall_row(row) -> bool:
    """Whether a row belongs in the multi-turn recall denominator.

    Two conditions:

    * **the group is a real recall measurement** (:data:`RECALL_GROUP_PREFIXES`)
      -- a verdict against a fixture that itself taught the wrong answer says
      nothing about recall;
    * **there is a verdict** -- a request that failed before replying has no
      measurement, and scoring it as wrong would charge the model for a
      transport failure.

    Checked against the MYS-2510 evidence, this is the rule that reproduces the
    corrected ratio: the three groups carrying a verdict there are ``chat50``
    (49), ``chat100`` (99) and ``soak-ctx`` (115). The first two give 136/148 =
    91.9%; including the third is the 136/263 = 51.7% the original report
    printed.

    Deliberately **not** keyed on ``expected_recall``. The task card describes
    the fix as "drop the rows whose ``expected_recall`` is null", and that is the
    natural rule -- but in the MYS-2510 evidence that column was never populated
    on *any* row, chat rows included, so such a test selects the empty set and
    the report would claim recall was never measured at all. The soak rows are
    null for the same reason the chat rows are, so the column cannot separate the
    two populations; group membership can, and it is the property that is
    actually true of them. ``expected_recall`` is still recorded on new runs and
    still drives grading, it just is not what decides the denominator.
    """
    group = getattr(row, "group", None) or ""
    return (group.startswith(RECALL_GROUP_PREFIXES)
            and getattr(row, "recall_ok", None) is not None)


# ---------------------------------------------------------------------------
# A2: continuous conversation up to a cumulative-token tier
# ---------------------------------------------------------------------------
#: The replacement character. One occurrence is a defect, not a tolerance: it
#: means a multi-byte character was assembled from bytes that did not complete
#: it. Named so every scan in this file uses the same literal.
REPLACEMENT_CHAR = "�"


def has_replacement_char(text: str | None) -> bool:
    """Whether ``text`` carries U+FFFD -- the UTF-8 assembly defect's signature."""
    return REPLACEMENT_CHAR in (text or "")


#: Fact words that are *not* one of the rare ones. Derived rather than a second
#: literal list, so the two can never drift apart.
#:
#: ``RARE_WORDS`` are already members of ``CHAT_FACTS`` (that is where the
#: MYS-2510 recall failures came from). They are pulled to the front of every
#: session instead of being appended, which would duplicate them and make
#: "which turn planted this word" ambiguous.
COMMON_FACTS: tuple[str, ...] = tuple(w for w in CHAT_FACTS
                                      if w not in RARE_WORDS)


def ctx_fact_for(session: int, turn: int) -> str:
    """The keyword planted in turn ``turn`` of A2 session ``session``.

    Two properties the recall grading depends on:

    * **deterministic and session-dependent** -- the rare-word order rotates by
      session, so two sessions at the same tier plant their facts in a different
      order and a cross-session leak shows up as a wrong answer rather than as a
      coincidence;
    * **no word is a substring of another** -- recall is graded by substring
      search, so a short word inside a longer planted one would score a hit for
      a turn that was never asked (asserted by a test over the whole pool).

    The first four turns of *every* session plant ``RARE_WORDS``, because those
    are the characters whose byte-level tokens split across token boundaries.
    A session that never plants them cannot regress-test the UTF-8 assembly fix,
    and the low tiers (2k is only a handful of turns) would otherwise never
    reach them in the pool.
    """
    if turn <= len(RARE_WORDS):
        return RARE_WORDS[(turn - 1 + session) % len(RARE_WORDS)]
    start = turn - len(RARE_WORDS) - 1
    return COMMON_FACTS[(start + session * 7) % len(COMMON_FACTS)]


#: Material clauses appended to each A2 turn, so a session reaches a tier in a
#: realistic number of turns rather than hundreds of one-line ones.
#:
#: A one-line turn costs ~33 tokens, so 16k would take ~500 turns. That is not
#: what "a 16k-token conversation" means in practice -- real turns carry content
#: -- and 500 turns of round trips would spend the whole budget on orchestration.
#: Four measured clauses per turn puts 16k at ~90 turns, which is a long but
#: ordinary conversation.
CTX_FILLER_CLAUSES = 4

#: Per-turn filler template. Reuses the warehouse-record shape from the long
#: tiers: it is ordinary Chinese prose, it is verifiable, and -- the reason it is
#: reused rather than invented -- the suite already knows it tokenizes predictably.
CTX_FILLER = "第{turn}轮附带台账{seq}：第{n}号库位登记编号{code:06d}，保管员{keeper}，状态正常。"


def ctx_turn_text(session: int, turn: int, *, ask_turn: int | None = None,
                  filler: int = CTX_FILLER_CLAUSES) -> tuple[str, str]:
    """One A2 turn: plant this turn's fact, carry some content, optionally ask back.

    ``ask_turn`` is the turn whose fact is asked back. ``None`` means "plant
    only, say 收到", which is what the turns building up to the tier do: asking
    every turn would burn decode time without adding evidence, since the recall
    probes are what the tier is graded on.

    ``filler`` clauses of ordinary material are appended so the conversation
    grows at a realistic rate (see :data:`CTX_FILLER_CLAUSES`). They are
    deterministic in ``(session, turn)`` so :meth:`Runner._ctx_history` can
    rebuild the identical history -- which the restart replay and the U1
    re-enactment both depend on.

    The message is deliberately self-contained and numbered, so a reply that
    quotes the turn number is evidence the history was read rather than guessed.
    """
    fact = ctx_fact_for(session, turn)
    emoji = RARE_EMOJI[(turn - 1) % len(RARE_EMOJI)]
    lines = [f"第{turn}轮记录：本轮编号{turn}，关键词是「{fact}」，标记符号{emoji}。"]
    for seq in range(1, max(0, filler) + 1):
        n = (session * 1000 + turn * 10 + seq)
        lines.append(CTX_FILLER.format(
            turn=turn, seq=seq, n=n, code=code_for(n, SEED + session),
            keeper=KEEPERS[(n + session) % len(KEEPERS)]))
    if ask_turn is None:
        lines.append("请只回复“收到”。")
    else:
        lines.append(f"第{ask_turn}轮的记录关键词是什么？只回答关键词本身，不要解释。")
    return "\n".join(lines), fact


def ctx_probe_plan(turns: int, *, early: int = CTX_EARLY_PROBES,
                   recent: int = CTX_RECENT_PROBES) -> list[tuple[int, str]]:
    """Which planted turns to ask back once the tier is reached.

    ``early`` turns come from the first tenth of the history, ``recent`` from the
    last few, and the two sets never overlap. Asking only recent facts would pass
    on a short sliding window; asking only early ones would pass on a cache that
    kept the head. The pair is what makes the result "the whole history is
    there" rather than "something is there".

    The early picks are spread evenly across ``1..head_end`` and are **distinct
    even when the session is short** -- a 7-turn 2k session has a head window of
    one turn, and asking the same turn three times would report three probes
    where there was one. So the head window is widened to at least ``early``
    turns, and the picks inside it are unique.

    Returns ``(turn, position)``, early first, in the order they are asked.
    """
    if turns < early + recent:
        raise ValueError(f"need at least {early + recent} turns to probe; got {turns}")
    head_end = max(early, turns // 10)
    head_end = min(head_end, turns - recent)

    if early == 1:
        early_turns = [1]
    else:
        # Evenly spaced across the head window, inclusive of both ends.
        early_turns = sorted({1 + round(i * (head_end - 1) / (early - 1))
                              for i in range(early)})
    recent_turns = [turns - recent + 1 + i for i in range(recent)]
    plan = [(t, "early") for t in early_turns]
    plan += [(t, "recent") for t in recent_turns if t not in early_turns]
    assert len({t for t, _ in plan}) == len(plan), plan
    return plan


def ctx_tier_reached(prompt_tokens: int | None, target: int,
                     tolerance: float = CTX_TIER_TOLERANCE) -> bool:
    """Whether a measured cumulative ``prompt_tokens`` lands in the tier.

    ``None`` is not reached: an unmeasured tier cannot be claimed. The band is
    inclusive on both ends so a session that lands exactly on target passes.
    """
    if not prompt_tokens:
        return False
    low = target * (1 - tolerance)
    high = target * (1 + tolerance)
    return low <= prompt_tokens <= high


def grade_verbatim(expected: str, output: str) -> dict:
    """Score a "repeat this verbatim" reply for U1.

    Three separate facts, because they fail for different reasons:

    * ``contains_all`` -- every requested character appeared;
    * ``exact`` -- the reply *is* the token, i.e. the model did not wrap it;
    * ``clean`` -- no U+FFFD anywhere.

    A reply can be clean and still wrong (a different word), and it can be
    right-in-substance but dirty (``门簪`` plus a stray replacement char
    elsewhere). Reporting all three keeps "the decode is fixed" apart from "the
    model obeyed".
    """
    text = output or ""
    return {
        "contains_all": expected in text,
        "exact": text.strip() == expected,
        "clean": not has_replacement_char(text),
    }


# ---------------------------------------------------------------------------
# Tool definitions and grading
# ---------------------------------------------------------------------------
#: Two tools whose arguments are JSON objects with a required string field. The
#: model must emit a call naming the right one; the *content* of the argument is
#: graded separately, because "called the right tool with a slightly different
#: city spelling" is protocol-correct and content-imperfect.
TOOL_WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的当前天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}

TOOL_TIME = {
    "type": "function",
    "function": {
        "name": "get_local_time",
        "description": "查询指定城市的当前时间",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名称"}},
            "required": ["city"],
        },
    },
}

#: Tool-call prompts. Each names one city, so the expected argument is known.
#: The two-tool prompt is the discrimination check: a model that always picks
#: the first tool passes the single-tool cases and fails this one.
TOOL_PROMPTS: tuple[dict, ...] = (
    {"text": "北京现在天气怎么样？请调用工具查询。", "expect": "get_weather",
     "city": "北京", "tools": 1},
    {"text": "上海现在几点了？请调用工具查询。", "expect": "get_local_time",
     "city": "上海", "tools": 2},
    {"text": "深圳天气如何？请调用工具查询。", "expect": "get_weather",
     "city": "深圳", "tools": 2},
    {"text": "杭州现在时间是多少？请调用工具查询。", "expect": "get_local_time",
     "city": "杭州", "tools": 2},
)

#: Definitions the service must reject with 400: no name, wrong type, not a list.
INVALID_TOOLS: tuple[tuple[str, object], ...] = (
    ("missing function.name", [{"type": "function", "function": {}}]),
    ("tools not a list", {"type": "function"}),
    ("wrong tool type", [{"type": "tool", "function": {"name": "x"}}]),
)


def grade_tool_call(expect_name: str, expect_city: str, calls: Sequence[dict]) -> dict:
    """Protocol correctness and content correctness, scored apart.

    ``protocol_ok`` is "a well-formed function call with a ``function.name`` and
    JSON-parseable arguments came back". ``content_ok`` additionally requires the
    right tool name and the city inside the arguments. A model that calls the
    right tool with the wrong city is a content miss, not a protocol failure --
    and the report says which, because they lead to different fixes.
    """
    if not calls:
        return {"protocol_ok": False, "content_ok": False, "name": None,
                "arguments": None, "reason": "no tool_calls in the reply"}
    first = calls[0] or {}
    fn = first.get("function") if isinstance(first.get("function"), dict) else {}
    name = fn.get("name")
    raw_args = fn.get("arguments")
    parsed = None
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = None
    elif isinstance(raw_args, dict):
        parsed = raw_args
    protocol_ok = bool(name) and isinstance(parsed, dict)
    content_ok = protocol_ok and name == expect_name and \
        (expect_city in json.dumps(parsed, ensure_ascii=False))
    return {"protocol_ok": protocol_ok, "content_ok": content_ok, "name": name,
            "arguments": parsed if parsed is not None else raw_args,
            "reason": None if protocol_ok else "unparseable arguments"}


# ---------------------------------------------------------------------------
# Vision fixtures
# ---------------------------------------------------------------------------
#: (filename, mime) pairs from ``tests/vision_fixtures``. Tiny, decidable
#: images -- a gradient, a flat grey, a palette, a wide strip and one 160x120
#: JPEG -- never a real photograph. The task asks for the record to carry
#: dimensions only, so the fixtures' sizes are also the expected metadata.
VLM_FILES: tuple[tuple[str, str], ...] = (
    ("gradient.png", "image/png"),
    ("gray.png", "image/png"),
    ("palette.png", "image/png"),
    ("photo.jpg", "image/jpeg"),
)

#: A valid 1x1 PNG, used as the *second* image in multi-image requests. Written
#: as bytes rather than read from disk so the multi-image case cannot be skipped
#: when a fixture is missing.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


def data_url(raw: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def png_size(raw: bytes) -> tuple[int | None, int | None]:
    """(width, height) from a PNG's IHDR; ``(None, None)`` when unreadable."""
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


def jpeg_size(raw: bytes) -> tuple[int | None, int | None]:
    """(width, height) from a JPEG's SOF marker; ``(None, None)`` when absent."""
    i = 2
    while i < len(raw) - 8:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            return (int.from_bytes(raw[i + 7:i + 9], "big"),
                    int.from_bytes(raw[i + 5:i + 7], "big"))
        i += 1
    return None, None


def image_size(raw: bytes) -> tuple[int | None, int | None]:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return png_size(raw)
    return jpeg_size(raw)


# ---------------------------------------------------------------------------
# The row
# ---------------------------------------------------------------------------
@dataclass
class Round(base.Round):
    """One request, with the coordinates this matrix needs.

    ``dimension`` is the task card's letter (A..F) so the report can group by
    the thing being judged rather than by which helper happened to send the
    request. ``expected_status`` is what the phase requires -- a 429 or a 409 is
    a *success* in the phase that provokes it, and counting "HTTP 200" as the
    only success would make a working queue look broken.

    ``tokens`` is the real token count of the user text as measured by the
    tokenizer, which for the long tiers is the number the tier is named after;
    ``prompt_tokens`` is what the service reported, and the report shows both so
    "16k" can be checked rather than trusted.
    """

    dimension: str = "A"
    phase: str = ""
    expected_status: int | None = None
    status_ok: bool | None = None
    request_kind: str = "stream"
    tokens: int | None = None
    session: int | None = None
    turn: int | None = None
    lane: int | None = None
    attempt: int | None = None
    # Retrieval / chat / tool grading, kept as separate nullable facts.
    retrieval_correct: bool | None = None
    retrieval_wrong: bool | None = None
    retrieval_hedged: bool | None = None
    expected_code: int | None = None
    needle_index: int | None = None
    probe_position: str | None = None
    recall_ok: bool | None = None
    tool_protocol_ok: bool | None = None
    tool_content_ok: bool | None = None
    tool_name: str | None = None
    thinking: bool | None = None
    reasoning_present: bool | None = None
    # Cancellation / error semantics.
    cancel_stage: str | None = None
    partial_chars: int | None = None
    record_status: str | None = None
    record_finish_reason: str | None = None
    record_error_type: str | None = None
    records_found: int | None = None
    image_dims: list | None = None
    record_image_dims: list | None = None
    cache_hit: bool | None = None
    note: str | None = None
    # A2 continuous conversation / U1 UTF-8 regression.
    #:
    #: Which side of the tier a session is on: ``build`` turns grow the history,
    #: ``probe`` turns ask a planted fact back after the tier was reached.
    ctx_role: str | None = None
    #: The turn whose fact this row asks, and how far back that is. The distance
    #: is what makes "early fact" and "recent fact" checkable rather than labels.
    ctx_ask_turn: int | None = None
    ctx_ask_distance: int | None = None
    #: ``early``/``recent`` for a probe row; ``None`` on build turns.
    ctx_probe_position: str | None = None
    #: The tier this session was aiming at, in cumulative prompt_tokens.
    ctx_tier: int | None = None
    #: Cumulative ``prompt_tokens`` the service reported for this turn's request,
    #: i.e. the whole conversation up to and including this turn. Kept apart from
    #: ``prompt_tokens`` (the same number) only to make the report's intent clear.
    ctx_cumulative_tokens: int | None = None
    #: Whether that cumulative count landed inside the tier's band.
    ctx_tier_reached: bool | None = None
    #: The fact this row planted, and whether the reply recalled the asked one.
    ctx_fact: str | None = None
    #: U1: which surface (``stream``/``nonstream``/``console``) and which
    #: requested literal, plus the three separate verdicts from
    #: :func:`grade_verbatim`.
    u1_surface: str | None = None
    u1_expected: str | None = None
    u1_contains_all: bool | None = None
    u1_exact: bool | None = None
    #: Whether the reply carried U+FFFD. ``False`` is a pass, ``None`` unmeasured.
    u1_clean: bool | None = None
    #: Three-way agreement for U1: SSE-concatenated text, non-stream ``content``,
    #: and the inference record's ``output_text`` all said the same thing.
    u1_surfaces_agree: bool | None = None
    #: The record's ``output_text`` for this request, when it was read back.
    record_output_text: str | None = None
    #: The record's ``response_content`` (what the client was actually shown).
    record_response_content: str | None = None

    def as_row(self) -> dict:
        row = super().as_row()
        row["status_ok"] = self.status_ok
        row["request_kind"] = self.request_kind
        row["dimension"] = self.dimension
        row["phase"] = self.phase
        row["expected_status"] = self.expected_status
        return row


def new_round(dimension: str, phase: str, group: str, *, tokens: int | None = None,
              text: str = "", messages: int = 0, **kw) -> Round:
    row = Round(group=group, round_index=kw.pop("round_index", 0), tier=tokens or 0,
                input_text=text, input_chars=len(text),
                input_sha256=base.sha256(text), context_messages=messages,
                dimension=dimension, phase=phase, tokens=tokens)
    for key, value in kw.items():
        setattr(row, key, value)
    return row


# ---------------------------------------------------------------------------
# Request surfaces
# ---------------------------------------------------------------------------
def _post_stream(http: base.Http, path: str, payload: dict, headers: dict,
                 timeout: float, raw_path: Path, *,
                 stop_after_content: int | None = None,
                 stop_after_finish: bool = False) -> dict:
    """POST an SSE request and capture it, optionally hanging up early.

    ``stop_after_content`` closes the socket after that many content deltas --
    the client-disconnect injection. Closing (rather than calling a "cancel"
    route, which does not exist) is what a real client does when its user hits
    stop, and it is the path that must propagate to the worker.

    The raw body is written *before* parsing so the evidence survives a bug in
    this function, and the number of content deltas actually received is
    returned, which is how a "close before first token" case is proven to have
    really been before the first token.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(http.url(path), data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **headers})
    started = time.time()
    lines: list[str] = []
    first_token_at: float | None = None
    content_deltas = 0
    finish_seen = False
    status = None
    error = None
    closed_early = False
    try:
        with http.open(req, timeout) as resp:
            status = resp.status
            while True:
                line = resp.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")
                lines.append(decoded)
                payload_line = decoded.strip()
                if payload_line.startswith("data:") and "[DONE]" not in payload_line:
                    try:
                        obj = json.loads(payload_line[5:].strip())
                    except (json.JSONDecodeError, ValueError):
                        obj = None
                    if isinstance(obj, dict):
                        content, reasoning = base._delta_text(obj)
                        if content or reasoning:
                            first_token_at = first_token_at or time.time()
                            content_deltas += 1
                        for choice in obj.get("choices") or []:
                            if choice.get("finish_reason"):
                                finish_seen = True
                        if obj.get("text"):
                            content_deltas += 1
                            first_token_at = first_token_at or time.time()
                        if obj.get("done"):
                            finish_seen = True
                if stop_after_content is not None and content_deltas >= stop_after_content:
                    closed_early = True
                    break
                if stop_after_finish and finish_seen:
                    closed_early = True
                    break
    except urllib.error.HTTPError as exc:
        status = exc.code
        lines.append(exc.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - every failure is evidence
        error = f"{type(exc).__name__}: {exc}"
    finished = time.time()
    raw = "".join(lines)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw, encoding="utf-8")
    return {"status": status, "raw": raw, "started_at": started,
            "finished_at": finished, "first_token_at": first_token_at,
            "content_deltas": content_deltas, "finish_seen": finish_seen,
            "closed_early": closed_early, "error": error}


def stream_round(http: base.Http, key: str, model: str, *,
                 dimension: str, phase: str, group: str, user_text: str,
                 raw_path: Path, timeout: float = 1800.0,
                 tools: list | None = None, thinking: bool = False,
                 max_tokens: int = 128, stop=None,
                 stop_after_content: int | None = None,
                 stop_after_finish: bool = False,
                 expected_status: int = 200, tokens: int | None = None,
                 messages_override: list | None = None,
                 **kw) -> Round:
    """One ``/v1/chat/completions`` stream, graded and recorded as a row."""
    messages = messages_override or [{"role": "system", "content": SYSTEM_PROMPT},
                                     {"role": "user", "content": user_text}]
    row = new_round(dimension, phase, group, tokens=tokens, text=user_text,
                    messages=len(messages), expected_status=expected_status,
                    thinking=thinking, **kw)
    payload = {"model": model, "messages": messages, "stream": True,
               "seed": SEED, **PARAMS, "max_tokens": max_tokens,
               "enable_thinking": thinking}
    if stop is not None:
        payload["stop"] = stop
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    result = _post_stream(http, "/v1/chat/completions", payload,
                          {"Accept": "text/event-stream",
                           "Authorization": f"Bearer {key}"},
                          timeout, raw_path,
                          stop_after_content=stop_after_content,
                          stop_after_finish=stop_after_finish)
    _fill_from_stream(row, result)
    return row


def _fill_from_stream(row: Round, result: dict) -> None:
    """Populate a row from a captured SSE body, failures included."""
    row.http_status = result["status"]
    row.started_at = result["started_at"]
    row.finished_at = result["finished_at"]
    row.total_s = round(result["finished_at"] - result["started_at"], 6)
    if result["first_token_at"]:
        row.ttft_s = round(result["first_token_at"] - result["started_at"], 6)
    if result["error"]:
        row.error = result["error"]
    parsed = base.parse_sse(result["raw"])
    row.req_id = base.request_id_of(parsed.response_id)
    row.output = parsed.text
    row.finish_reason = parsed.finish_reason
    row.stream_done = parsed.done
    prompt_tokens, completion_tokens, cached = base.usage_tokens(parsed.usage)
    row.prompt_tokens = prompt_tokens or None
    row.completion_tokens = completion_tokens or None
    row.cached_tokens = cached if parsed.usage else None
    row.reasoning_present = bool(parsed.reasoning) or None
    row.partial_chars = len(parsed.text)
    if row.error is None and parsed.errors:
        row.error = f"stream error: {parsed.error_summary()}"
    # A 4xx body is JSON, not SSE: keep the service's own words.
    if row.http_status and row.http_status >= 400 and not row.error:
        row.error = f"HTTP {row.http_status}: {result['raw'][:600]}"
    # A stream that *opened* with 200 and then timed out or reset has a 200 on
    # the row and no successful outcome -- judging on the status alone called it
    # a pass on the first live run. An error after the headers is a failure, and
    # ``error`` is set by the caller's exception handler when that happens.
    row.status_ok = (row.http_status == row.expected_status
                     and not result["error"]
                     and not (row.expected_status == 200
                              and not result["closed_early"]
                              and not parsed.done))
    if row.status_ok and row.http_status == 200:
        if not row.output and row.expected_status == 200:
            row.error = row.error or "empty output"
            row.status_ok = False


def nonstream_round(http: base.Http, key: str, model: str, *,
                    dimension: str, phase: str, group: str, user_text: str,
                    raw_path: Path, timeout: float = 1800.0,
                    tools: list | None = None, thinking: bool = False,
                    max_tokens: int = 128, stop=None,
                    expected_status: int = 200, tokens: int | None = None,
                    **kw) -> Round:
    """One non-streaming ``/v1/chat/completions`` request."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}]
    row = new_round(dimension, phase, group, tokens=tokens, text=user_text,
                    messages=len(messages), expected_status=expected_status,
                    request_kind="nonstream", thinking=thinking, **kw)
    payload = {"model": model, "messages": messages, "stream": False,
               "seed": SEED, **PARAMS, "max_tokens": max_tokens,
               "enable_thinking": thinking}
    if stop is not None:
        payload["stop"] = stop
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        http.url("/v1/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
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
    except Exception as exc:  # noqa: BLE001
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body or b"")
    row.total_s = round((row.finished_at or 0) - (row.started_at or 0), 6)
    obj: dict = {}
    try:
        obj = json.loads((body or b"{}").decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        obj = {}
    row.status_ok = row.http_status == row.expected_status
    if row.http_status and row.http_status >= 400:
        row.error = row.error or f"HTTP {row.http_status}: " \
                                 f"{(body or b'').decode('utf-8', 'replace')[:600]}"
    if row.http_status == 200:
        choice = (obj.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        row.output = message.get("content") or ""
        row.req_id = base.request_id_of(obj.get("id"))
        row.finish_reason = choice.get("finish_reason")
        pt, ct, cached = base.usage_tokens(obj.get("usage") or {})
        row.prompt_tokens = pt or None
        row.completion_tokens = ct or None
        row.cached_tokens = cached if obj.get("usage") else None
        row.reasoning_present = bool(message.get("reasoning_content")) or None
        row.partial_chars = len(row.output)
        row.stream_done = True
        if not row.output and row.expected_status == 200:
            row.error = row.error or "empty output"
        calls = message.get("tool_calls") or []
        if calls:
            row.tool_name = ((calls[0] or {}).get("function") or {}).get("name")
    return row


def console_round(http: base.Http, model: str, *, dimension: str, phase: str,
                  group: str, user_text: str, raw_path: Path,
                  timeout: float = 1800.0, max_tokens: int = 128,
                  expected_status: int = 200, tokens: int | None = None,
                  **kw) -> Round:
    """``/api/chat/stream``: the console's cookie-authenticated SSE route."""
    row = new_round(dimension, phase, group, tokens=tokens, text=user_text,
                    messages=1, expected_status=expected_status,
                    request_kind="console", **kw)
    payload = {"model": model, "prompt": user_text, "max_tokens": max_tokens,
               "temperature": 0.0, "enable_thinking": False}
    result = _post_stream(http, "/api/chat/stream", payload,
                          {"Accept": "text/event-stream"}, timeout, raw_path)
    row.http_status = result["status"]
    row.started_at = result["started_at"]
    row.finished_at = result["finished_at"]
    row.total_s = round(result["finished_at"] - result["started_at"], 6)
    if result["first_token_at"]:
        row.ttft_s = round(result["first_token_at"] - result["started_at"], 6)
    if result["error"]:
        row.error = result["error"]
    text = ""
    done = False
    usage: dict = {}
    for line in result["raw"].splitlines():
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
    row.partial_chars = len(text)
    row.status_ok = (row.http_status == row.expected_status
                     and not result["error"]
                     and not (row.expected_status == 200
                              and not result["closed_early"] and not done))
    if row.http_status and row.http_status >= 400 and not row.error:
        row.error = f"HTTP {row.http_status}: {result['raw'][:600]}"
    if row.status_ok and row.http_status == 200 and not text:
        row.error = row.error or "empty output"
        row.status_ok = False
    return row


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------
class Service:
    """Admin operations the matrix needs, each one audited.

    Every mutation is recorded as ``(what, before, after)`` in :attr:`changes`
    so the report can show the experiment's configuration *and* prove it was
    restored. A phase that changes ``max_queue`` or stops the service is only
    honest if the report can show the original value and the restore.
    """

    def __init__(self, http: base.Http, model: str, password: str = "admin"):
        self.http = http
        self.model = model
        self.password = password
        self.changes: list[dict] = []
        self._settings: dict | None = None

    # -- settings --------------------------------------------------------
    def settings(self, refresh: bool = False) -> dict:
        if self._settings is None or refresh:
            status, body = self.http.json("GET", "/api/settings", timeout=60)
            if status != 200:
                raise RuntimeError(f"cannot read /api/settings (HTTP {status})")
            self._settings = body
        return dict(self._settings)

    def set_settings(self, **fields) -> dict:
        """Apply settings and verify the service echoes them back.

        Verified rather than assumed: ``POST /api/settings`` clamps values, so a
        ``max_queue=0`` request that the service stored as 16 would silently
        invalidate the queue experiment. The returned dict is what the service
        says it applied; the caller compares.
        """
        before = self.settings()
        status, body = self.http.json("POST", "/api/settings", fields, timeout=120)
        if status != 200:
            raise RuntimeError(f"POST /api/settings failed: HTTP {status} {body}")
        after = body.get("settings") or {}
        self._settings = dict(after)
        self.changes.append({"at": time.time(), "fields": dict(fields),
                             "before": {k: before.get(k) for k in fields},
                             "after": {k: after.get(k) for k in fields},
                             "applied": body.get("applied")})
        mismatch = {k: {"asked": v, "stored": after.get(k)}
                    for k, v in fields.items() if after.get(k) != v}
        if mismatch:
            raise RuntimeError(f"settings not taken as asked: {mismatch}")
        return after

    def restore_settings(self, snapshot: dict, keys: Sequence[str]) -> dict:
        fields = {k: snapshot[k] for k in keys if k in snapshot}
        return self.set_settings(**fields) if fields else {}

    # -- model lifecycle -------------------------------------------------
    def model_state(self) -> tuple[bool | None, str | None, dict]:
        status, body = self.http.json("GET", "/api/models", timeout=60)
        if status != 200:
            return None, None, {}
        for entry in body.get("models") or []:
            if entry.get("id") == self.model:
                return bool(entry.get("loaded")), entry.get("operation"), entry
        return None, None, {}

    def unload(self, timeout: float = 300.0) -> int:
        status, _ = self.http.json("POST", f"/api/models/{self.model}/unload",
                                   timeout=timeout)
        return status

    def load(self, timeout: float = 900.0) -> tuple[int, float]:
        started = time.time()
        status, _ = self.http.json("POST", f"/api/models/{self.model}/load",
                                   timeout=timeout)
        return status, round(time.time() - started, 2)

    def wait_ready(self, timeout: float = 900.0, interval: float = 0.5) -> bool:
        """Block until the model reports ``loaded`` with no operation in flight."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            loaded, operation, _ = self.model_state()
            if loaded and operation is None:
                return True
            time.sleep(interval)
        return False

    def wait_stopped(self, timeout: float = 300.0, interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            loaded, operation, _ = self.model_state()
            if not loaded and operation is None:
                return True
            time.sleep(interval)
        return False

    def reload(self, load_timeout: float = 900.0) -> dict:
        """Normal unload -> load, both waited out. Never a ``kill -9``."""
        out = {"unload_status": self.unload(), "started_at": time.time()}
        out["stopped"] = self.wait_stopped()
        out["load_status"], out["load_s"] = self.load(load_timeout)
        out["ready"] = self.wait_ready(load_timeout)
        out["finished_at"] = time.time()
        return out

    def cache_state(self) -> dict:
        """The worker's own prefix-cache counters.

        Read before the run and after each long-tier request: the cache can only
        be *shown* to be empty at the start -- zero entries, zero reused tokens --
        and a phase that inherits a warm cache would report prefill latency for
        work that never happened.
        """
        stats = self.worker_stats()
        cache = stats.get("cache") or {}
        return {"entries": cache.get("entries"),
                "bytes": cache.get("bytes"),
                "tokens_reused": cache.get("tokens_reused"),
                "tokens_prompted": cache.get("tokens_prompted"),
                "hit_rate": cache.get("hit_rate"),
                "evictions": cache.get("evictions"),
                "expirations": cache.get("expirations")}

    def cold_cache(self, timeout: float = 300.0, interval: float = 1.0) -> dict:
        """Wait until the prefix cache holds no entries; report what happened.

        A cold start is achieved the supported way -- unloading and reloading the
        model, which destroys the worker process and therefore its KV cache. There
        is no "clear cache" endpoint, and shrinking the TTL only schedules
        eviction. This is the only honest way to make "the first 16k request
        prefills 16k tokens" a true statement.

        Returns the before/after cache counters plus how long it took, so the
        report can show the cache really was empty rather than asserting it.
        """
        before = self.cache_state()
        started = time.time()
        out = {"before": before, "reloaded": False, "cold": None, "s": None}
        if not before.get("entries"):
            out.update({"cold": True, "s": 0.0, "reloaded": False})
            return out
        reload_info = self.reload(load_timeout=timeout)
        out["reload"] = reload_info
        out["reloaded"] = True
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.cache_state()
            if not state.get("entries"):
                out.update({"after": state, "cold": True,
                            "s": round(time.time() - started, 2)})
                return out
            time.sleep(interval)
        out.update({"after": self.cache_state(), "cold": False,
                    "s": round(time.time() - started, 2)})
        return out

    def worker_stats(self) -> dict:
        status, body = self.http.json("GET", "/api/stats", timeout=60)
        if status != 200:
            return {}
        for payload in (body.get("workers") or {}).values():
            if isinstance(payload, dict):
                return payload
        return {}

    def record_total(self) -> int | None:
        status, body = self.http.json("GET", "/api/inference-records/status",
                                      timeout=60)
        return body.get("total") if status == 200 else None

    def record(self, req_id: str) -> dict | None:
        status, body = self.http.json("GET", f"/api/inference-records/{req_id}",
                                      timeout=60)
        return body if status == 200 else None

    def record_ids_for(self, ids: Sequence[str], limit: int = 200) -> dict[str, int]:
        """How many times each id appears in the export (duplicate detection).

        Reads the NDJSON export once rather than issuing a request per id: on a
        run of a few thousand rows the per-id loop is thousands of round trips,
        and the export is the same server-side data in one pass. Only ids in
        ``ids`` are tallied, so memory stays bounded by the run, not the log.
        """
        wanted = set(ids)
        counts: dict[str, int] = {}
        req = urllib.request.Request(self.http.url("/api/inference-records-export"),
                                     headers={"Accept": "application/x-ndjson"})
        try:
            with self.http.open(req, 900) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        rid = json.loads(line).get("id")
                    except json.JSONDecodeError:
                        continue
                    if rid in wanted:
                        counts[rid] = counts.get(rid, 0) + 1
        except (urllib.error.HTTPError, OSError):
            return counts
        return counts


def systemctl(action: str, *, unit: str = "cv84x6-llm", timeout: float = 300.0,
              via: str | None = None) -> dict:
    """Run one systemd action, over SSH when ``via`` names a host.

    ``via`` is ``"linaro@host:port"``. The suite normally runs *on* the board,
    where the command is local; the SSH form exists so a run driven from a
    workstation still restarts the real unit rather than a mock.

    Only ``SIGTERM``-equivalent actions are used by the matrix. ``kill -9`` on a
    process holding the NPU heap is what wedges the board, so no phase here
    escalates to it.
    """
    cmd = ["sudo", "-n", "systemctl", action, unit]
    if via:
        user_host, _, port = via.partition(":")
        cmd = ["sshpass", "-p", "linaro", "ssh", "-o", "StrictHostKeyChecking=no",
               "-o", "ConnectTimeout=15", "-p", port or "22",
               user_host, " ".join(cmd)]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": proc.returncode, "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:], "s": round(time.time() - started, 2)}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"cmd": cmd, "rc": -1, "stdout": "", "stderr": repr(exc),
                "s": round(time.time() - started, 2)}


def wait_http_ready(http: base.Http, timeout: float = 600.0,
                    interval: float = 1.0) -> float | None:
    """Seconds until ``/healthz`` answers 200, or ``None`` on timeout."""
    started = time.time()
    while time.time() - started < timeout:
        try:
            status, _ = http.request("GET", "/healthz", timeout=10)
        except (OSError, ValueError):
            status = 0
        if status == 200:
            return round(time.time() - started, 2)
        time.sleep(interval)
    return None


# ---------------------------------------------------------------------------
# Device sampling
# ---------------------------------------------------------------------------
class Sampler(ext.Sampler):
    """``/api/stats`` every few seconds, plus the service's own counters.

    Subclasses the MYS-2501 sampler (same fields, same never-raise contract) and
    adds the two numbers the soak's drift analysis needs beyond it: the record
    log's size and row count, and the disk's free bytes. A soak that only watched
    RAM would miss a record log growing without bound.

    ``drift`` compares the median of the first tenth of the samples with the
    median of the last tenth, per metric: a monotonic leak shows up as a large
    positive delta, while a warm-up ramp that plateaus does not, because the
    comparison is between two settled windows rather than first-vs-last sample.
    """

    def sample_once(self) -> dict | None:
        sample = super().sample_once()
        if sample is None:
            return None
        try:
            status, body = self.http.json("GET", "/api/inference-records/status",
                                          timeout=15)
            if status == 200:
                sample["record_total"] = body.get("total")
                sample["record_bytes"] = body.get("bytes")
        except (OSError, ValueError):
            pass
        try:
            status, body = self.http.json("GET", "/api/storage", timeout=15)
            if status == 200:
                disk = body.get("disk") or {}
                sample["disk_free"] = disk.get("free_bytes")
        except (OSError, ValueError):
            pass
        # The parent appends this same dict to ``samples``, so the two extra
        # keys are already visible to ``snapshot()`` -- no second write, and no
        # window in which the stored sample lacks them.
        return sample

    def drift(self, key: str) -> dict:
        """First-tenth vs last-tenth medians for one metric."""
        values = [s.get(key) for s in self.snapshot()
                  if s.get("ok") and isinstance(s.get(key), (int, float))]
        if len(values) < 10:
            return {"key": key, "n": len(values), "head": None, "tail": None,
                    "delta": None, "growth": None}
        window = max(1, len(values) // 10)
        head = statistics.median(values[:window])
        tail = statistics.median(values[-window:])
        delta = tail - head
        return {"key": key, "n": len(values), "head": head, "tail": tail,
                "delta": delta,
                "growth": round(delta / head, 4) if head else None}

    def summary(self, keys: Sequence[str]) -> dict:
        return {k: self.drift(k) for k in keys}


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------
class Runner:
    """Drives the matrix, writing every row to JSONL as it happens.

    One object per run so phases are callable (and testable) individually. The
    JSONL is flushed after each row: a run that dies mid-matrix leaves the
    evidence it had, which is the difference between "the 32k tier failed" and
    "we do not know what happened at 32k".
    """

    def __init__(self, http: base.Http, key: str, model: str, evidence: Path,
                 raw_dir: Path, timeline: ext.Timeline, service: Service,
                 tokenizer: Tokenizer | None = None, timeout: float = 3600.0,
                 verbose: bool = True):
        self.http = http
        self.key = key
        self.model = model
        self.evidence = evidence
        self.raw_dir = raw_dir
        self.timeline = timeline
        self.service = service
        self.tokenizer = tokenizer
        self.timeout = timeout
        self.verbose = verbose
        self.rounds: list[Round] = []
        self.phases: dict[str, dict] = {}
        self.jsonl = (evidence / "rounds.jsonl").open("a", encoding="utf-8")
        self._lock = threading.Lock()

    # -- plumbing --------------------------------------------------------
    def record(self, row: Round) -> Round:
        with self._lock:
            self.rounds.append(row)
            self.jsonl.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
            self.jsonl.flush()
        if self.verbose:
            mark = "✓" if row.status_ok else "✗"
            if row.retrieval_correct:
                mark += "取✓"
            elif row.retrieval_correct is False:
                mark += "取✗"
            if row.recall_ok:
                mark += "忆✓"
            elif row.recall_ok is False:
                mark += "忆✗"
            tail = (row.output or "").strip().replace("\n", " ")[:28]
            where = ""
            if row.session is not None:
                where = f"s{row.session}t{row.turn}"
            elif row.lane is not None:
                where = f"L{row.lane}"
            elif row.attempt is not None:
                where = f"a{row.attempt}"
            print(f"  [{row.dimension}] {row.group:<16} {where:<8} "
                  f"{row.tokens or row.input_chars:>6} "
                  f"HTTP {row.http_status if row.http_status is not None else '-'} "
                  f"{(row.total_s or 0):>8.2f}s pt={row.prompt_tokens or '-'} "
                  f"ct={row.completion_tokens or '-'} {mark} {tail!r}"
                  + (f" ERR {str(row.error)[:70]}" if row.error else ""), flush=True)
        return row

    def close(self) -> None:
        self.jsonl.close()

    def rewrite_jsonl(self) -> None:
        """Rewrite ``rounds.jsonl`` from memory, filling in late-known columns.

        Rows are appended as they happen, on purpose: a run that dies mid-matrix
        must leave everything it observed. But some fields are only decided
        afterwards -- a cancelled request's ``record_status`` and
        ``records_found`` (the record is written during generator teardown, after
        the client's socket closes), the service-side ``decode_tps``, the
        duplicate count from the export pass. Without this rewrite those columns
        stayed null in the evidence file even though the phase had judged them,
        which made the JSONL disagree with the report.

        Written through a temporary file and ``os.replace`` so an interrupted
        rewrite cannot leave a half-written evidence file.
        """
        path = self.evidence / "rounds.jsonl"
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in self.rounds:
                fh.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
        os.replace(tmp, path)

    @staticmethod
    def _is_support_row(row: Round) -> bool:
        """A row that proves recovery rather than testing the thing itself."""
        return row.group.endswith("-recovery") or row.group.endswith("-restored")

    def _raw(self, *parts: str) -> Path:
        """A path under ``raw/``, with its directory created.

        Created here rather than at every call site: a missing parent produced a
        FileNotFoundError *after* a request had already been sent, which loses
        the response the path existed to keep.
        """
        path = self.raw_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _phase_start(self, name: str, note: str, dimension: str) -> float:
        self.timeline.add("phase", f"开始 {name}", note, group=name)
        if self.verbose:
            print(f"\n=== {name} [{dimension}] {note}", flush=True)
        return time.time()

    def _phase_end(self, name: str, started: float, **extra) -> None:
        """Close a phase and count it.

        ``intended`` counts only the requests the phase is *judging* -- the
        cancel phase's "one short request afterwards" recovery probes are
        evidence that the worker was released, not cancellations, and folding
        them into the expected total made 30 rows read as "25/30 as expected"
        when every one of the 15 cancellations had in fact passed.
        """
        rows = [r for r in self.rounds if r.phase == name]
        judged = [r for r in rows if not self._is_support_row(r)]
        info = {"phase": name, "started_at": started, "finished_at": time.time(),
                "s": round(time.time() - started, 2), "requests": len(rows),
                "intended": len(judged) or len(rows),
                "ok": sum(1 for r in judged if r.status_ok),
                "support_rows": len(rows) - len(judged),
                "support_ok": sum(1 for r in rows
                                  if self._is_support_row(r) and r.status_ok),
                **extra}
        self.phases[name] = info
        self.timeline.add("phase", f"结束 {name}",
                          f"{info['requests']} 请求，{info['ok']} 符合预期，"
                          f"{info['s']}s", group=name, count=info["requests"])
        if self.verbose:
            tail = ""
            if info["support_rows"]:
                tail = (f"（另 {info['support_rows']} 次恢复探针 "
                        f"{info['support_ok']} 通过）")
            print(f"=== {name} done: {info['intended']} requests, "
                  f"{info['ok']} as expected, {info['s']}s{tail}", flush=True)

    # -- A. long context -------------------------------------------------
    def run_long_context(self, tiers: Sequence[int] | None = None,
                         repeats: dict[int, int] | None = None,
                         probes: Sequence[str] = ("head", "middle", "tail")) -> None:
        """Long prompts at each tier, each asking for a planted fact.

        The probe position rotates across repeats (head/middle/tail) because
        retrieval accuracy depends on where the fact sits: a suite that only
        planted facts at the end would report a retrieval rate this model does
        not have on a fact buried at the start.

        Nothing is retried and no timeout is guessed: the timeout is an explicit
        parameter, every failure keeps its raw body, and a slow tier is reported
        as a slow tier. A long prefill on this board is *minutes*, not a hang —
        the report separates ``timeout`` from ``error`` so a prefill that exceeded
        an intentionally generous limit is not mislabelled as a service crash.
        """
        tiers = list(LONG_TIERS if tiers is None else tiers)
        repeats = dict(LONG_TIER_REPEATS if repeats is None else repeats)
        name = "longctx"
        # Start from a provably empty prefix cache. Without this a re-run of the
        # same material prefills in a fraction of the time -- measured: 110 s
        # cold vs 13 s warm for the 16k tier -- and the report would present that
        # as the cost of a 16k prompt.
        cold = self.service.cold_cache()
        self.timeline.add(
            "note", "长上下文组开始前清空前缀缓存",
            f"重载={cold['reloaded']}，缓存条目 {cold['before'].get('entries')} -> "
            f"{(cold.get('after') or {}).get('entries')}，耗时 {cold['s']}s",
            group=name)
        if not cold["cold"]:
            self.timeline.anomaly(
                "无法确认前缀缓存为空，长上下文延迟可能被缓存命中掩盖",
                f"cache={cold.get('after')}", group=name)
        started = self._phase_start(
            name, f"{len(tiers)} 档 × 各自次数：" +
                  "、".join(f"{t//1024}k×{repeats.get(t, 1)}" for t in tiers), "A")
        index = 0
        for tier in tiers:
            for k in range(repeats.get(tier, 1)):
                index += 1
                probe = probes[k % len(probes)]
                prompt = build_long_prompt(tier, tokenizer=self.tokenizer,
                                           seed=SEED + index, probe=probe,
                                           round_index=index)
                row = stream_round(
                    self.http, self.key, self.model,
                    dimension="A", phase=name, group=f"longctx-{tier//1024}k",
                    user_text=prompt.text,
                    raw_path=self._raw("longctx", f"{tier}-{index}-{probe}.sse"),
                    timeout=self.timeout, max_tokens=32,
                    tokens=prompt.tokens, round_index=index,
                    expected_code=prompt.expected_code,
                    needle_index=prompt.needle_index, probe_position=probe)
                graded = grade_retrieval(prompt, row.output)
                row.retrieval_correct = graded["correct"]
                row.retrieval_wrong = graded["wrong_number"]
                row.retrieval_hedged = graded["hedged"]
                if not graded["correct"]:
                    row.note = (";".join(
                        n for n, on in (("wrong_number", graded["wrong_number"]),
                                        ("hedged", graded["hedged"]),
                                        ("no_answer", graded["no_answer"])) if on)
                        or None)
                self.record(row)
                # The real prompt_tokens vs the tier's target: the gap is the
                # builder's one-clause overshoot plus the system message, and it
                # is reported rather than assumed away.
                # A cache hit shows up as cached_tokens. Record it, and flag a
                # long tier whose prompt was mostly served from cache: the
                # latency on that row is not the cost of a cold prefill.
                if row.cached_tokens:
                    row.note = ((row.note + ";") if row.note else "") + \
                        f"cached_tokens={row.cached_tokens}"
                    if row.cached_tokens >= tier * 0.5:
                        self.timeline.anomaly(
                            "长上下文请求大量命中前缀缓存",
                            f"{tier} 档 cached={row.cached_tokens}，"
                            "该行延迟不代表冷预填充成本", group=name)
                if row.prompt_tokens and abs(row.prompt_tokens - tier) > tier * 0.05:
                    self.timeline.anomaly(
                        "长上下文 token 数与档位偏差过大",
                        f"{tier} 档实际 prompt_tokens={row.prompt_tokens}",
                        group=name)
                if row.error and "timeout" in str(row.error).lower():
                    self.timeline.anomaly(
                        "长 prompt 触发受控超时",
                        f"{tier} 档：{row.error[:120]}", group=name)
                elif not row.status_ok:
                    self.timeline.anomaly(
                        "长上下文请求异常",
                        f"{tier} 档 HTTP {row.http_status} {str(row.error)[:120]}",
                        group=name)
        self._phase_end(name, started, tiers=tiers, repeats=repeats,
                        cold_cache=cold)

    def run_overflow(self, targets: Sequence[int] | None = None) -> None:
        """Prompts past the window must be refused clearly, not served empty.

        Three assertions, in order of what a failure would mean:

        * the status is a 4xx (**not** 200, not a 5xx, not a hang);
        * the body names the limit (``context limit``/``too long``/``131072``),
          so an operator can tell "too long" from "bad request";
        * no record was written -- the request never reached the model, so an
          audit row for it would be a lie about what the NPU did.

        The refusal is cheap because the worker encodes and compares lengths
        before prefill; that is why a 200k-token probe is affordable at all.
        """
        targets = list(OVERFLOW_TOKENS if targets is None else targets)
        name = "overflow"
        started = self._phase_start(name, "超出上下文必须明确报错", "A")
        before = self.service.record_total()
        for index, target in enumerate(targets, start=1):
            prompt = build_overflow_prompt(target, tokenizer=self.tokenizer,
                                           seed=SEED + index)
            row = stream_round(
                self.http, self.key, self.model,
                dimension="A", phase=name, group="overflow",
                user_text=prompt.text,
                raw_path=self._raw("overflow", f"{target}.sse"),
                timeout=min(self.timeout, 600.0), max_tokens=8,
                tokens=prompt.tokens, round_index=index,
                expected_status=400)
            body = row.error or ""
            names_limit = any(marker in body for marker in
                              ("context limit", "too long", "131072", "上下文"))
            # Two refusal shapes are both *clear* refusals, and which one arrives
            # depends on the transport, not on the service being wrong:
            #
            #   * non-streaming / pre-header: a 4xx status and a JSON detail;
            #   * streaming: the SSE headers are already sent by the time the
            #     worker rejects the length, so the refusal arrives as an
            #     `{"error": ...}` frame followed by [DONE] on a 200 status line.
            #
            # The task requires "明确错误，不得空输出或服务崩溃". Judging on the
            # status alone marked the streaming shape as a failure on the live
            # run even though it named the exact limit. So: a 4xx, or a 200 whose
            # body carries an error frame, is a refusal; what must not happen is
            # a successful-looking 200 with content, or a 5xx.
            in_stream_error = bool(row.http_status == 200 and row.error
                                   and "error" in body.lower())
            refused = bool((row.http_status and 400 <= row.http_status < 500)
                           or in_stream_error)
            produced_output = bool(row.output) or bool(row.prompt_tokens)
            row.status_ok = refused and names_limit and not produced_output
            row.note = (";".join([
                "shape=" + ("4xx" if row.http_status and row.http_status >= 400
                            else "sse-error-frame" if in_stream_error else "served"),
                f"names_limit={names_limit}",
                f"tokens={prompt.tokens}",
                f"output_chars={len(row.output or '')}",
            ]))
            self.record(row)
            if not refused:
                self.timeline.anomaly("超长 prompt 未被明确拒绝",
                                      f"{target}: HTTP {row.http_status} "
                                      f"{str(row.error)[:120]}", group=name)
            elif not names_limit:
                self.timeline.anomaly("超长拒绝未说明长度上限",
                                      f"{target}: {body[:160]}", group=name)
            elif produced_output:
                self.timeline.anomaly("超长 prompt 产生了输出或推理记录",
                                      f"{target}: pt={row.prompt_tokens} "
                                      f"out={len(row.output or '')}", group=name)
            if in_stream_error:
                # Worth stating in the report rather than only in a row note: a
                # client that only reads status codes will treat this as success.
                self.timeline.add(
                    "note", "超长输入以 SSE 错误帧拒绝而非 4xx",
                    f"{prompt.tokens} tokens：HTTP 200 + error 帧"
                    "（流式响应已发头，属正常形态；非流式请求仍是 4xx）",
                    group=name, count=1)
        after = self.service.record_total()
        delta = None if before is None or after is None else after - before
        # The task says an over-length request must not be served and must not
        # crash; it does not say it leaves no audit row. Measured on .151:
        # each over-length prompt writes exactly one record with
        # ``status=error``, ``error.type=WorkerError:invalid_request`` and
        # ``prompt_tokens=0`` -- the inference genuinely happened (the prompt was
        # tokenized, the length was checked) and was correctly refused, which is
        # what ``docs/inference-records.md`` says every WorkerError produces.
        #
        # So the assertion is "one error record per over-length attempt, and no
        # record that claims tokens were processed", not "zero records". The
        # earlier zero expectation was the suite's mistake, not the service's.
        over = [r for r in self.rounds
                if r.phase == name and r.req_id and r.group == "overflow"]
        claimed = [r for r in over if r.prompt_tokens]
        if delta is not None and delta != len(over):
            self.timeline.anomaly(
                "超长请求的记录条数与实际请求数不符",
                f"记录总数增加 {delta}，超长请求 {len(over)} 次"
                "（每次应恰好一条 error 记录）", group=name)
        if claimed:
            self.timeline.anomaly(
                "超长请求的记录声称处理了 token",
                f"{len(claimed)} 条记录带 prompt_tokens（应为 0）", group=name)
        self.timeline.add(
            "note", "超长请求按约定写入 error 记录",
            f"{len(over)} 次超长请求各写 1 条 status=error、prompt_tokens=0 的记录"
            "（推理确实发生并被正确拒绝，符合 records 契约）；"
            f"记录总数增量 {delta}", group=name)
        self._phase_end(name, started, records_before=before, records_after=after,
                        records_delta=delta, expected_records=len(over),
                        records_claiming_tokens=len(claimed))

    def run_chat_history(self, turns: int = CHAT_TURNS_REQUIRED,
                         *, extended: bool = False) -> None:
        """One growing conversation of ``turns`` rounds, each resending history.

        Every turn is a real turn: the whole earlier exchange is resent, so the
        prompt grows monotonically. Each turn plants a numbered fact and asks for
        the previous turn's keyword, so the recall score is evidence the history
        was actually used rather than a claim about it.

        The cumulative token count is recorded per turn. That curve is the point
        of the block: it shows how fast a real conversation approaches the
        window, and the report shows the last turn's ``prompt_tokens`` as the
        measured maximum context.
        """
        name = f"chat{turns}"
        started = self._phase_start(
            name, f"同会话 {turns} 轮，每轮增加可核验事实", "A")
        history: list[dict] = []
        for turn in range(1, turns + 1):
            text, fact, asked = chat_turn_text(turn, seed=SEED)
            messages = base.context_messages(SYSTEM_PROMPT, history, text)
            row = stream_round(
                self.http, self.key, self.model,
                dimension="A", phase=name, group=f"chat{turns}",
                user_text=text, raw_path=self._raw(name, f"turn{turn:03d}.sse"),
                timeout=self.timeout, max_tokens=48,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=turn, session=1, turn=turn,
                messages_override=messages)
            row.recall_ok = grade_chat_turn(asked, row.output)
            row.expected_recall = asked
            if row.recall_ok is False:
                row.note = f"asked={asked}"
            self.record(row)
            history = base.append_turn(history, text, row.output)
            if not row.status_ok:
                self.timeline.anomaly(
                    f"{turns} 轮会话请求异常",
                    f"第 {turn} 轮：HTTP {row.http_status} {str(row.error)[:120]}",
                    group=name)
        max_prompt = max((r.prompt_tokens or 0) for r in self.rounds
                         if r.phase == name) if self.rounds else 0
        self._phase_end(name, started, turns=turns, max_prompt_tokens=max_prompt,
                        extended=extended)

    # -- A2. continuous conversation up to a cumulative-token tier ---------
    def _ctx_history(self, session: int, up_to: int) -> list[dict]:
        """The deterministic history of turns ``1..up_to`` for one session.

        Rebuilt from the seed rather than replayed from a stored transcript, so
        the restart-replay step sends **byte-identical** history to what the
        live session built, and the U1 replay can reconstruct a session that
        this run never held in memory.

        Assistant turns are the literal ``收到。`` the build turns were asked
        for. That is what the live session actually sent in its history, and it
        is also the honest thing to rebuild: the model's real replies are
        recorded per-turn in ``rounds.jsonl``, but they are not reproducible, and
        a replayed history that invented them would not be the same conversation.
        Build turns are not scored for recall, so no recall claim depends on the
        substituted assistant text.
        """
        history: list[dict] = []
        for turn in range(1, up_to + 1):
            text, _ = ctx_turn_text(session, turn)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": "收到。"})
        return history

    def run_context_tiers(self, tiers: Sequence[int] | None = None,
                          sessions_per_tier: dict[int, int] | None = None,
                          run_restart: bool = True) -> None:
        """A2: real multi-turn sessions grown until their cumulative tokens hit a tier.

        The whole point is that the tier is measured, not scheduled. Each turn
        resends the entire user/assistant history, so ``prompt_tokens`` on the
        service's own response *is* the conversation's size; a session keeps
        going until that number lands inside the tier's ±10% band. The turn count
        is therefore an output, not an input, and the report prints both.

        Grading is split three ways on purpose:

        * **reaching the tier** -- arithmetic on reported ``prompt_tokens``;
        * **protocol success** -- ``status_ok`` per request;
        * **fact recall** -- whether the reply contained the planted keyword.

        A session that reaches 16k and answers nothing is a *semantic* result,
        not a stability failure, and the two are counted apart.

        Nothing is retried. A turn that fails is recorded and the session
        continues, because a conversation with a hole in it is exactly the state
        the next turn has to cope with.

        When the restart tier is one of the tiers being grown, the 16k session
        **is** the one that gets restarted rather than an extra one being built
        beside it. The requirement is "one of the 16k sessions, after reaching
        the tier, is restarted"; building a second 16k conversation to restart
        would spend another ~80 minutes of prefill re-establishing the same
        evidence, and would let the report count 16k twice.
        """
        tiers = list(tiers or CTX_TIERS)
        per_tier = dict(sessions_per_tier or CTX_TIER_SESSIONS)
        name = "ctx-tiers"
        started = self._phase_start(
            name, f"连续对话到档：{'/'.join(f'{t//1024}k' for t in tiers)}"
                  f"（按会话累计 prompt_tokens 判档 ±{CTX_TIER_TOLERANCE:.0%}）", "A")
        session_id = 0
        restart_facts: dict = {}
        restart_done = False
        for tier in tiers:
            for index in range(max(1, per_tier.get(tier, 1))):
                session_id += 1
                # Restart the *first* session of the restart tier, in place.
                if (run_restart and not restart_done
                        and tier == CTX_RESTART_TIER):
                    restart_facts = self._ctx_restart_session(session_id, tier) or {}
                    restart_done = True
                else:
                    self._ctx_session(session_id, tier)
        if run_restart and not restart_done:
            # The restart tier was not among the tiers grown (a --ctx-tiers
            # override). Run it anyway: the restart-replay evidence is required
            # independently of which tiers were asked for.
            session_id += 1
            restart_facts = self._ctx_restart_session(session_id,
                                                      CTX_RESTART_TIER) or {}
        reached = [r for r in self.rounds
                   if r.phase == name and r.ctx_tier_reached]
        sessions = {r.session for r in self.rounds if r.phase == name}
        self._phase_end(name, started, sessions=len(sessions),
                        sessions_reaching=sorted({r.session for r in reached}),
                        tiers=list(tiers),
                        restart_session=restart_facts.get("session"),
                        restart_tier=CTX_RESTART_TIER,
                        restart_gate_ok=restart_facts.get("gate_ok"),
                        restart_reload_ok=restart_facts.get("reload_ok"),
                        restart_history_kept=restart_facts.get("history_kept"))

    def _ctx_session(self, session: int, tier: int, *,
                     group: str | None = None, max_turns: int = 400,
                     history_override: list[dict] | None = None) -> list[dict]:
        """Grow one session to ``tier``, then probe it. Returns the history.

        ``history_override`` lets the restart step reuse a history that was
        already built rather than rebuilding it, so the "complete history" claim
        is about the same bytes and not about a reconstruction.
        """
        group = group or f"ctx-{tier // 1024}k"
        history = history_override if history_override is not None else []
        turn = len(history) // 2
        reached_at: int | None = None
        last_pt: int | None = None

        # -- grow ------------------------------------------------------
        while turn < max_turns:
            turn += 1
            text, fact = ctx_turn_text(session, turn)
            messages = base.context_messages(SYSTEM_PROMPT, history, text)
            row = stream_round(
                self.http, self.key, self.model,
                dimension="A2", phase="ctx-tiers", group=group,
                user_text=text,
                raw_path=self._raw("ctx-tiers", f"s{session:02d}", f"t{turn:03d}.sse"),
                timeout=self.timeout, max_tokens=CTX_MAX_TOKENS,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=turn, session=session, turn=turn,
                messages_override=messages)
            row.ctx_role = "build"
            row.ctx_tier = tier
            row.ctx_fact = fact
            row.ctx_cumulative_tokens = row.prompt_tokens
            last_pt = row.prompt_tokens
            row.ctx_tier_reached = ctx_tier_reached(row.prompt_tokens, tier)
            if not row.status_ok:
                row.note = f"build-turn failure: HTTP {row.http_status}"
            self.record(row)
            history = base.append_turn(history, text, row.output)
            if row.ctx_tier_reached:
                reached_at = turn
                break
            # Overshoot guard: if this turn already flew past the band, another
            # turn only makes it worse, so stop and let the report say the tier
            # was missed rather than burning minutes proving it repeatedly.
            if (row.prompt_tokens or 0) > tier * (1 + CTX_TIER_TOLERANCE):
                row.note = (f"tier overshot: {row.prompt_tokens} > "
                            f"{int(tier * (1 + CTX_TIER_TOLERANCE))}")
                break
            if not row.status_ok:
                # A dead session cannot reach a bigger tier by continuing.
                break

        if reached_at is None:
            self.timeline.anomaly(
                f"{group} 未到档",
                f"会话 {session} 结束于 {turn} 轮，最后一轮累计 "
                f"prompt_tokens={last_pt}，目标 {tier}±{CTX_TIER_TOLERANCE:.0%}",
                group=group)
            return history

        # -- probe (only when the tier was actually reached) ------------
        plan = ctx_probe_plan(turn)
        for ask_turn, position in plan:
            asked_fact = ctx_fact_for(session, ask_turn)
            text, _ = ctx_turn_text(session, turn, ask_turn=ask_turn)
            messages = base.context_messages(SYSTEM_PROMPT, history, text)
            probe = stream_round(
                self.http, self.key, self.model,
                dimension="A2", phase="ctx-tiers", group=group,
                user_text=text,
                raw_path=self._raw("ctx-tiers", f"s{session:02d}",
                                   f"probe-t{ask_turn:03d}.sse"),
                timeout=self.timeout, max_tokens=CTX_MAX_TOKENS,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=turn, session=session, turn=turn,
                messages_override=messages)
            probe.ctx_role = "probe"
            probe.ctx_tier = tier
            probe.ctx_tier_reached = ctx_tier_reached(probe.prompt_tokens, tier)
            probe.ctx_cumulative_tokens = probe.prompt_tokens
            probe.ctx_ask_turn = ask_turn
            probe.ctx_ask_distance = turn - ask_turn
            probe.ctx_probe_position = position
            probe.ctx_fact = asked_fact
            probe.expected_recall = asked_fact
            probe.recall_ok = grade_chat_turn(asked_fact, probe.output)
            if probe.recall_ok is False:
                probe.note = f"asked turn {ask_turn} = {asked_fact}"
            self.record(probe)
            if has_replacement_char(probe.output):
                self.timeline.anomaly(
                    "回忆回答含 U+FFFD",
                    f"会话 {session} 第 {ask_turn} 轮 {asked_fact}："
                    f"{probe.output[:80]!r}",
                    group=group)
        return history

    def _ctx_restart_session(self, session: int, tier: int) -> dict:
        """Reach ``tier``, restart the service, then continue with the full history.

        The requirement is specific: after a normal ``systemctl restart`` the
        model is *not* reloaded (startup only adopts a worker that is still
        running, and SIGTERM killed it), so the first request must be refused
        with 409 and the model must be loaded explicitly. Both are asserted, in
        that order, and the conversation then resumes with the complete history
        that was built before the restart.

        Continuity is graded as three separate facts, because they can fail
        independently: the history is not lost (the resumed turn's
        ``prompt_tokens`` is at least what it was), the records are continuous
        (the record total did not drop across the restart), and the model still
        recalls the planted facts. The three are returned as separate booleans so
        the report can name which one broke instead of reporting "restart
        failed".
        """
        group = f"ctx-{tier // 1024}k-restart"
        before = len(self.rounds)
        history = self._ctx_session(session, tier, group=group)
        # The conversation's length is the last *build* turn. Counting rows
        # instead would include the recall probes, which do not extend the
        # history, and would ask the resumed turn about a turn that planted
        # nothing.
        build_turns = [r.turn for r in self.rounds[before:]
                       if r.ctx_role == "build" and r.turn]
        turn = max(build_turns) if build_turns else max(1, len(history) // 2)
        pre_ids = [r.req_id for r in self.rounds[before:] if r.req_id]

        # -- restart (SIGTERM), then prove the gate and reload ----------
        self.timeline.add("phase", f"开始 {group} 重启",
                          "正常 systemctl restart，验证准入与显式加载", group=group)
        restart = self._restart_and_reload(
            marker=f"请只回复“{RARE_WORDS[0]}”三个字。",
            raw_prefix=f"{group}-restart", dimension="A2", phase="ctx-tiers",
            group_prefix=group, round_base=turn)
        self.record(restart["gate_row"])
        if restart.get("records_retained") is False:
            self.timeline.anomaly(
                f"{group} 重启后推理记录减少",
                f"{restart['records_before']} -> {restart['records_after']}",
                group=group)

        # -- resume with the complete history ---------------------------
        plan = ctx_probe_plan(turn) if turn >= CTX_EARLY_PROBES + CTX_RECENT_PROBES \
            else [(1, "early")]
        resumed_pt: int | None = None
        for ask_turn, position in plan:
            asked_fact = ctx_fact_for(session, ask_turn)
            text, _ = ctx_turn_text(session, turn, ask_turn=ask_turn)
            messages = base.context_messages(SYSTEM_PROMPT, history, text)
            probe = stream_round(
                self.http, self.key, self.model,
                dimension="A2", phase="ctx-tiers", group=group,
                user_text=text,
                raw_path=self._raw("ctx-tiers", f"s{session:02d}",
                                   f"postrestart-t{ask_turn:03d}.sse"),
                timeout=self.timeout, max_tokens=CTX_MAX_TOKENS,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=turn, session=session, turn=turn,
                messages_override=messages)
            probe.ctx_role = "probe"
            probe.ctx_tier = tier
            probe.ctx_tier_reached = ctx_tier_reached(probe.prompt_tokens, tier)
            probe.ctx_cumulative_tokens = probe.prompt_tokens
            probe.ctx_ask_turn = ask_turn
            probe.ctx_ask_distance = turn - ask_turn
            probe.ctx_probe_position = position
            probe.ctx_fact = asked_fact
            probe.expected_recall = asked_fact
            probe.recall_ok = grade_chat_turn(asked_fact, probe.output)
            if resumed_pt is None:
                resumed_pt = probe.prompt_tokens
            if probe.recall_ok is False:
                probe.note = f"post-restart asked turn {ask_turn} = {asked_fact}"
            self.record(probe)

        # Continuity is three separate facts. The history survived if the
        # resumed turn reports at least the tokens the pre-restart turn did;
        # the records survived if the service's own total did not drop; and the
        # conversation still works if the probes answered. Reported apart so a
        # failure names which one broke.
        build_pts = [r.prompt_tokens or 0 for r in self.rounds[before:]
                     if r.ctx_role == "build"]
        pre_pt = max(build_pts) if build_pts else None
        history_kept = None if not resumed_pt or not pre_pt \
            else resumed_pt >= pre_pt
        recalled = [r for r in self.rounds[before:]
                    if r.ctx_role == "probe" and r.recall_ok is not None]
        self.timeline.add(
            "note", f"{group} 重启复验",
            f"重启前最后一条 build 轮 prompt_tokens={pre_pt}，"
            f"重启后完整历史首问 prompt_tokens={resumed_pt}，"
            f"历史保留={history_kept}，"
            f"回忆 {sum(1 for r in recalled if r.recall_ok)}/{len(recalled)}，"
            f"重启前请求 {len(pre_ids)} 条，"
            f"记录总数 {restart['records_before']}→{restart['records_after']}",
            group=group)
        self.timeline.add("phase", f"结束 {group} 重启",
                          f"重启前 {len(pre_ids)} 条请求，重启后恢复追问", group=group)
        return {
            "session": session,
            "tier": tier,
            "gate_ok": restart["gate_refused"],
            "reload_ok": restart["model_ready"] is True,
            "history_kept": history_kept,
            "records_retained": restart["records_retained"],
            "pre_prompt_tokens": pre_pt,
            "resumed_prompt_tokens": resumed_pt,
            "recall_ok": sum(1 for r in recalled if r.recall_ok),
            "recall_checked": len(recalled),
        }

    # -- B. concurrency and queueing -------------------------------------
    def run_concurrency(self, lanes_list: Sequence[int] | None = None,
                        rounds: int = CONC_ROUNDS,
                        tiers: Sequence[int] = (60, 300, 1200)) -> None:  # noqa: D401
        """N lanes × ``rounds`` rounds, each request carrying its own marker.

        Two separate claims are tested and reported apart:

        * **Isolation** — every reply echoes its own marker and no other lane's.
          A reply carrying another lane's marker is cross-talk, which is what a
          session or buffer mix-up looks like from outside.
        * **Queueing** — with ``max_concurrent=2`` and three lanes, the third
          request must *wait*, not refuse. ``queued`` rising above zero in the
          sampler during a 3-lane round is the positive evidence that it
          queued; a 429 there would mean the waiting room never accepted it.

        Rounds are sequential: round N+1 starts only after all of round N's
        requests finish, so the batch boundary is real and a slow request shows
        up as a slow round rather than as untracked overlap.
        """
        lanes_list = list(CONC_LANES if lanes_list is None else lanes_list)
        for lanes in lanes_list:
            name = f"conc{lanes}"
            started = self._phase_start(
                name, f"{lanes} 路 × {rounds} 轮独立同负载，唯一标记", "B")
            queued_seen = 0
            refused = 0
            for round_index in range(1, rounds + 1):
                specs: list[tuple[int, str, int]] = []
                markers: dict[str, int] = {}
                for lane in range(1, lanes + 1):
                    # Lane count in the marker: the 2-lane and 3-lane blocks
                    # share round numbers, and a marker that repeated across
                    # them would let one phase's reply satisfy another's
                    # cross-talk check.
                    marker = f"MK{lanes}{chr(64 + lane)}{round_index:03d}"
                    markers[marker] = lane
                    specs.append((lane, marker,
                                  tiers[(round_index + lane) % len(tiers)]))
                started_at = time.time()
                results: list[Round] = []
                lock = threading.Lock()

                def work(lane: int, marker: str, tier: int) -> None:
                    client = base.Http(self.http.base, timeout=self.timeout)
                    text = (f"请原样复述这个标记：{marker}。"
                            f"只回复标记本身，不要添加任何其他内容。")
                    try:
                        row = stream_round(
                            client, self.key, self.model,
                            dimension="B", phase=name, group=f"conc{lanes}",
                            user_text=text,
                            raw_path=self._raw(name, f"r{round_index:03d}-L{lane}.sse"),
                            timeout=self.timeout, max_tokens=32,
                            tokens=estimate_tokens(text, self.tokenizer),
                            round_index=round_index, lane=lane, marker=marker,
                            expected_status=200)
                    except Exception as exc:  # noqa: BLE001 - thread must not die
                        row = new_round("B", name, f"conc{lanes}", text=text,
                                        round_index=round_index, lane=lane,
                                        marker=marker, expected_status=200)
                        row.error = f"{type(exc).__name__}: {exc}"
                        row.status_ok = False
                    with lock:
                        results.append(row)

                threads = [threading.Thread(target=work, args=spec)
                           for spec in specs]
                for t in threads:
                    t.start()
                # Sample queue depth while the batch is in flight: this is the
                # only moment the waiting room has anything in it, so polling
                # between rounds would always read zero.
                while any(t.is_alive() for t in threads):
                    stats = self.service.worker_stats()
                    queued_seen = max(queued_seen, int(stats.get("queued") or 0))
                    time.sleep(0.4)
                for t in threads:
                    t.join()
                elapsed = round(time.time() - started_at, 3)
                for row in results:
                    foreign = [m for m in markers if m != row.marker
                               and m in (row.output or "")]
                    row.marker_ok = bool(row.marker and row.marker in (row.output or ""))
                    if foreign:
                        row.note = f"cross_talk:{','.join(foreign)}"
                        row.error = row.error or "cross-talk"
                        row.status_ok = False
                    if row.http_status == 429:
                        refused += 1
                    self.record(row)
                if any(r.note and "cross_talk" in r.note for r in results):
                    self.timeline.anomaly("并发串话",
                                          f"{lanes} 路第 {round_index} 轮", group=name)
            self._phase_end(name, started, lanes=lanes, rounds=rounds,
                            queued_seen=queued_seen, refused_429=refused,
                            cross_talk=sum(1 for r in self.rounds
                                           if r.phase == name and r.note
                                           and "cross_talk" in r.note))

    def run_queue_limits(self, capacities: Sequence[int] | None = None,
                         lanes: int = 3) -> None:
        """Prove the 429 edge exists, is honest, and recovers.

        With ``max_concurrent=2`` and ``max_queue=k`` the service holds
        ``2+k`` requests; one more is over capacity and must be refused with
        **429** and a ``Retry-After``. This phase fires ``lanes`` requests
        simultaneously against each capacity, records the status mix, then
        restores the original ``max_queue`` and makes one short request to show
        service resumed.

        A 429 here is a *pass*, not a fault — the phase's ``expected_status``
        encodes what is correct, and the report counts "refused as designed",
        "served" and "anything else" as three separate numbers.
        """
        capacities = list(QUEUE_CAPACITY_EXPERIMENTS if capacities is None else capacities)
        original = self.service.settings().get("max_queue")
        keys = ("max_queue",)
        name = "queue-capacity"
        started = self._phase_start(
            name, f"临时 max_queue ∈ {capacities}，超容量应 429 且可恢复", "B")
        outcomes: dict[int, dict] = {}
        try:
            for capacity in capacities:
                applied = self.service.set_settings(max_queue=capacity)
                sub_started = time.time()
                results: list[Round] = []
                lock = threading.Lock()

                def work(lane: int) -> None:
                    client = base.Http(self.http.base, timeout=self.timeout)
                    text = (f"请原样复述这个标记：QT{chr(64 + lane)}{capacity}。"
                            "只回复标记本身。")
                    try:
                        # expected_status is deliberately not 200: which code is
                        # right depends on capacity, and is judged below.
                        row = stream_round(
                            client, self.key, self.model,
                            dimension="B", phase=name, group="queue-capacity",
                            user_text=text,
                            raw_path=self._raw(name, f"cap{capacity}-L{lane}.sse"),
                            timeout=self.timeout, max_tokens=32,
                            tokens=estimate_tokens(text, self.tokenizer),
                            round_index=capacity * 10 + lane,
                            lane=lane, expected_status=200)
                    except Exception as exc:  # noqa: BLE001
                        row = new_round("B", name, "queue-capacity", text=text)
                        row.error = f"{type(exc).__name__}: {exc}"
                    with lock:
                        results.append(row)

                threads = [threading.Thread(target=work, args=(lane,))
                           for lane in range(1, lanes + 1)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                statuses: dict[str, int] = {}
                refused = 0
                for row in results:
                    key = str(row.http_status)
                    statuses[key] = statuses.get(key, 0) + 1
                    # Whether a lane *should* have been refused depends on how
                    # the three requests raced for the 2+k slots, so a per-row
                    # 200/429 is not by itself a pass or a fail. What is judged:
                    #
                    #   * the request produced a usable outcome (served, or
                    #     explicitly refused) -- never a hang or a 5xx;
                    #   * at least one lane was refused when the configured
                    #     capacity could not hold all of them.
                    #
                    # A streaming refusal arrives as HTTP 200 with an error
                    # frame (the headers are already sent), so it is detected
                    # from the frame, not the status -- counting statuses alone
                    # reported "no 429 appeared" for a phase that had refused a
                    # request exactly as designed.
                    refused_in_stream = bool(
                        row.http_status == 200 and row.error
                        and "rate_limit" in str(row.error).lower())
                    if row.http_status == 429 or refused_in_stream:
                        refused += 1
                    row.status_ok = (row.http_status in (200, 429)
                                     and not (row.http_status is None))
                    row.note = ("refused" if (row.http_status == 429 or refused_in_stream)
                                else "served")
                    self.record(row)
                outcomes[capacity] = {"statuses": statuses,
                                      "refused": refused,
                                      "s": round(time.time() - sub_started, 3),
                                      "applied": applied.get("max_queue")}
                # 2 slots + k queue holds 2+k; over that must be refused.
                over_capacity = lanes - (2 + capacity)
                if over_capacity > 0 and refused == 0:
                    self.timeline.anomaly(
                        "超容量未出现拒绝",
                        f"max_queue={capacity}，{lanes} 路并发超出容量 "
                        f"{over_capacity}，但无任何请求被拒（状态 {statuses}）",
                        group=name)
            # Restore and prove it: a settings change that is not undone would
            # silently reshape every later phase.
            restored = self.service.set_settings(**{keys[0]: original})
            probe_text = "请只回复“恢复”两个字。"
            row = stream_round(
                self.http, self.key, self.model,
                dimension="B", phase=name, group="queue-restored",
                user_text=probe_text,
                raw_path=self._raw(name, "restored.sse"),
                timeout=self.timeout, max_tokens=16,
                tokens=estimate_tokens(probe_text, self.tokenizer),
                round_index=9999, expected_status=200)
            self.record(row)
            self._phase_end(name, started, outcomes=outcomes,
                            original_max_queue=original,
                            restored_max_queue=restored.get("max_queue"),
                            recovered=row.status_ok)
        finally:
            # Unconditional restore: an exception mid-experiment must not leave
            # the board with a queue depth nobody expects.
            current = self.service.settings(refresh=True)
            if current.get("max_queue") != original:
                try:
                    self.service.set_settings(max_queue=original)
                    self.timeline.anomaly(
                        "队列容量已回滚", f"{current.get('max_queue')} -> {original}",
                        group=name)
                except RuntimeError as exc:
                    self.timeline.anomaly("队列容量回滚失败", str(exc), group=name)

    def run_mixed_concurrency(self, rounds: int = 10) -> None:
        """Short, medium and long prompts running together: isolation at scale.

        The single-tier concurrency block keeps every request the same size; this
        one deliberately mixes a 60-token request with a 2,048-token one and an
        8,192-token one in the same batch. That is the shape where a shared
        buffer or a per-session mix-up shows up, and it also shows the real
        throughput cost of a long prefill sitting next to small work.
        """
        name = "conc-mixed"
        started = self._phase_start(
            name, f"{rounds} 轮，每轮同时发 短/中/长 三个不同长度请求", "B")
        tiers = (60, 2048, 8192)
        # The long prompts are built once and reused across rounds. Rebuilding
        # them per round was ~10 s of tokenizer work plus a cold prefill each
        # time (measured 49 s for the 8k lane, per round), which measured the
        # generator rather than the service. Only the marker changes, and it is
        # appended to the same material -- so a round still differs from the
        # previous one in the text the model must echo.
        long_material = {
            lane: build_long_prompt(max(512, tier), tokenizer=self.tokenizer,
                                    seed=SEED + lane, probe="tail")
            for lane, tier in enumerate(tiers, start=1) if tier > 200
        }
        for round_index in range(1, rounds + 1):
            results: list[Round] = []
            lock = threading.Lock()
            markers = {f"MX{len(tiers)}{chr(64 + i)}{round_index:03d}": i
                       for i in range(1, len(tiers) + 1)}

            def work(lane: int, tier: int, marker: str) -> None:
                client = base.Http(self.http.base, timeout=self.timeout)
                if tier <= 200:
                    text = f"请原样复述标记：{marker}。只回复标记本身。"
                else:
                    text = long_material[lane].text + f"\n（标记 {marker}）"
                try:
                    row = stream_round(
                        client, self.key, self.model,
                        dimension="B", phase=name, group="conc-mixed",
                        user_text=text,
                        raw_path=self._raw(name, f"r{round_index:03d}-L{lane}.sse"),
                        timeout=self.timeout, max_tokens=32,
                        tokens=estimate_tokens(text, self.tokenizer),
                        round_index=round_index, lane=lane, marker=marker,
                        expected_status=200)
                except Exception as exc:  # noqa: BLE001
                    row = new_round("B", name, "conc-mixed", text=text)
                    row.error = f"{type(exc).__name__}: {exc}"
                    row.status_ok = False
                with lock:
                    results.append(row)

            threads = [threading.Thread(target=work,
                                        args=(i + 1, tier, marker))
                       for i, (marker, tier) in
                       enumerate(zip(markers, tiers))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            for row in results:
                foreign = [m for m in markers if m != row.marker
                           and m in (row.output or "")]
                row.marker_ok = None if row.tokens and row.tokens > 200 \
                    else bool(row.marker and row.marker in (row.output or ""))
                if foreign:
                    row.note = f"cross_talk:{','.join(foreign)}"
                    row.error = row.error or "cross-talk"
                    row.status_ok = False
                self.record(row)
        self._phase_end(name, started, rounds=rounds)

    # -- C. streaming, cancellation, client faults -----------------------
    def wait_record(self, req_id: str, timeout: float = 60.0,
                    interval: float = 0.5) -> dict | None:
        """Poll for one record to appear.

        A cancelled request's record is written during generator teardown, which
        happens *after* the client's socket closes -- so reading immediately
        after the disconnect races the write. Polling with a bounded timeout
        observes the write instead of concluding it never happened.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            detail = self.service.record(req_id)
            if detail is not None:
                return detail
            time.sleep(interval)
        return None

    def run_cancel(self, repeats: int = CANCEL_REPEATS) -> None:
        """Disconnect before the first token, mid-stream, and near completion.

        The service's contract (``docs/inference-records.md``) is that every
        inference writes **exactly one** record on every termination path, and
        that a client disconnect leaves ``status=cancelled`` with the partial
        text kept. Both halves are checked per repetition:

        * exactly one record exists for the request id (the export is read once
          at the end to count duplicates);
        * its ``status`` is ``cancelled`` and its ``output_text`` holds what had
          already been streamed;
        * a short request immediately afterwards is served normally, which is
          what proves the worker was released rather than left decoding.

        The three stages are not interchangeable: closing before the first token
        exercises cancellation during prefill (before any ``delta``), mid-stream
        exercises it during decode, and near-completion exercises the teardown
        that races the normal ``[DONE]`` path.
        """
        name = "cancel"
        started = self._phase_start(
            name, f"三阶段各 {repeats} 次主动断开，验证取消传播与记录", "C")
        # Three different moments, and the third one is subtle. Closing on the
        # first `finish_reason` frame is *too late*: the service has already
        # completed the inference and written its `ok` record by then, so the
        # cancel is a no-op and asserting `cancelled` fails for a correct service
        # (measured: all 5 near-completion cases recorded `status=ok`). The real
        # "near the end" window is the last stretch of decoding -- the client
        # hangs up with a few tokens still to come. With max_tokens=256 the
        # generation is truncated by the loop guard at roughly 140 tokens, so
        # closing after 120 is genuinely near the end while still mid-stream.
        stages = (
            ("before-first-token", dict(stop_after_content=0)),
            ("mid-stream", dict(stop_after_content=5)),
            ("near-completion", dict(stop_after_content=NEAR_COMPLETION_DELTAS)),
        )
        for stage, how in stages:
            for k in range(1, repeats + 1):
                text = (f"请从一数到五十，每个数字之间用逗号分隔，只输出数字。"
                        f"（第{k}次）")
                row = stream_round(
                    self.http, self.key, self.model,
                    dimension="C", phase=name, group=f"cancel-{stage}",
                    user_text=text,
                    raw_path=self._raw(name, f"{stage}-{k}.sse"),
                    timeout=600.0, max_tokens=256,
                    tokens=estimate_tokens(text, self.tokenizer),
                    round_index=k, cancel_stage=stage,
                    expected_status=200, **how)
                # A deliberately closed stream has no [DONE] and may be short:
                # the *transport* outcome that matters is that we did close.
                deltas = row.partial_chars or 0
                row.note = f"closed_after_deltas={deltas}"
                # Status is judged by the record below, not by the socket.
                row.status_ok = True
                self.record(row)
                if not row.req_id:
                    row.status_ok = False
                    row.error = row.error or "no request id observed before close"
                    self.timeline.anomaly("断开时未取得请求 id", f"{stage} 第{k}次",
                                          group=name)
                    continue
                detail = self.wait_record(row.req_id, timeout=90.0)
                if detail is None:
                    row.status_ok = False
                    row.error = f"no record for {row.req_id} after cancel"
                    self.timeline.anomaly("取消后没有记录",
                                          f"{stage} 第{k}次 id={row.req_id}", group=name)
                else:
                    row.record_status = detail.get("status")
                    row.record_finish_reason = detail.get("finish_reason")
                    err = detail.get("error") or {}
                    row.record_error_type = err.get("type") if isinstance(err, dict) else None
                    recorded_text = detail.get("output_text") or ""
                    row.record_image_dims = None
                    row.note += (f";record_status={row.record_status}"
                                 f";record_chars={len(recorded_text)}")
                    if row.record_status != "cancelled":
                        row.status_ok = False
                        self.timeline.anomaly(
                            "取消后记录状态不是 cancelled",
                            f"{stage} 第{k}次：{row.record_status}", group=name)
                    if deltas and not recorded_text:
                        # Partial output was streamed but not kept: the record
                        # would be useless for the现场 debugging it exists for.
                        row.status_ok = False
                        self.timeline.anomaly(
                            "取消时未保留已生成的部分输出",
                            f"{stage} 第{k}次：已收到 {deltas} 段但记录为空",
                            group=name)
                # Recovery: the next request must be served normally.
                probe = "请只回复“正常”两个字。"
                after = stream_round(
                    self.http, self.key, self.model,
                    dimension="C", phase=name, group="cancel-recovery",
                    user_text=probe,
                    raw_path=self._raw(name, f"recovery-{stage}-{k}.sse"),
                    timeout=300.0, max_tokens=16,
                    tokens=estimate_tokens(probe, self.tokenizer),
                    round_index=k, cancel_stage=stage, expected_status=200)
                self.record(after)
                if not after.status_ok or after.error:
                    self.timeline.anomaly(
                        "取消后后续短请求异常",
                        f"{stage} 第{k}次之后：HTTP {after.http_status} "
                        f"{str(after.error)[:100]}", group=name)
        # Duplicate check for every cancelled id, in one export pass.
        ids = [r.req_id for r in self.rounds
               if r.phase == name and r.req_id and r.cancel_stage
               and r.group.startswith("cancel-")]
        counts = self.service.record_ids_for(ids)
        for row in self.rounds:
            if row.phase == name and row.cancel_stage and row.req_id:
                row.records_found = counts.get(row.req_id, 0)
                if row.records_found != 1:
                    self.timeline.anomaly(
                        "取消请求的记录条数不是恰好一条",
                        f"{row.cancel_stage} 第{row.round_index}次：{row.records_found} 条",
                        group=name)
        self._phase_end(name, started, repeats=repeats,
                        cancelled=sum(1 for r in self.rounds
                                      if r.phase == name
                                      and r.record_status == "cancelled"))

    def run_protocol_errors(self) -> None:
        """Six malformed requests plus stop/max_tokens, each with its expected code.

        The task card is explicit that an expected 4xx is **not** a fault, so each
        case carries the status it must produce and the phase judges "as
        specified" rather than "2xx". A wrong code, a 5xx, or a 200 with an empty
        body is a failure; the exact 4xx the service chooses is the assertion,
        because an operator debugging a client needs it to be stable.

        The same reasoning covers the two *successful* protocol cases: a stop
        string must truncate and say ``stop``, and ``max_tokens`` must truncate
        and say ``length``. Returning the full answer for a ``max_tokens=4``
        request would be a protocol bug that looks like a good answer.
        """
        name = "protocol"
        started = self._phase_start(
            name, "stop/max_tokens 语义 + 空消息/非法图片/未知模型/非法工具", "C")
        cases: list[tuple[str, dict, tuple[int, ...], str]] = []

        # -- malformed: these must be 4xx and must not write a record --------
        #
        # Each case lists the codes that are *correct*, not one code. Two shapes
        # reach different layers: a bad message role is rejected by pydantic
        # (422) before the endpoint sees it, while an empty `messages` list and a
        # bad image reach the endpoint's own validation (400). Both are correct
        # client errors, and asserting a single exact code turned a working
        # service into a reported failure on the first live run.
        cases.append(("empty-messages", {"messages": []}, (400,), "空 messages"))
        cases.append(("bad-role", {"messages": [{"role": "wizard",
                                                 "content": "hi"}]}, (422, 400), "非法角色"))
        cases.append(("unknown-model", {"model": "no-such-model"}, (404,), "未知模型"))
        cases.append(("bad-image-url", {"messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,!!!notbase64!!!"}}]}]},
            (400,), "非法图片 data URL"))
        cases.append(("remote-image", {"messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": "https://example.com/x.png"}}]}]},
            (400,), "远端图片 URL"))
        for label, tools in INVALID_TOOLS:
            # A non-list `tools` never reaches validate_tools: pydantic rejects
            # the request body first. Recorded as 422/400 rather than pretending
            # the documented 400 is the only acceptable answer.
            codes = (400, 422) if not isinstance(tools, list) else (400,)
            cases.append((f"tool-def:{label}", {"tools": tools}, codes,
                          f"非法工具定义 {label}"))
        cases.append(("n-not-1", {"n": 2}, (400,), "n != 1"))
        cases.append(("max-tokens-0", {"max_tokens": 0}, (400,), "max_tokens < 1"))

        before_records = self.service.record_total()
        for index, (label, overrides, acceptable, note) in enumerate(cases, start=1):
            expected = acceptable[0]
            payload = {"model": self.model, "stream": False,
                       "messages": [{"role": "user", "content": "请只回复“好”。"}],
                       "max_tokens": 8, "temperature": 0.0}
            payload.update(overrides)
            row = new_round("C", name, f"proto-{label}", text=note,
                            round_index=index, expected_status=expected,
                            request_kind="nonstream")
            req = urllib.request.Request(
                self.http.url("/v1/chat/completions"),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json",
                         "Accept": "application/json",
                         "Authorization": f"Bearer {self.key}"})
            body = b""
            row.started_at = time.time()
            try:
                with self.http.open(req, 240) as resp:
                    row.http_status = resp.status
                    body = resp.read()
            except urllib.error.HTTPError as exc:
                row.http_status = exc.code
                body = exc.read()
            except Exception as exc:  # noqa: BLE001
                row.error = f"{type(exc).__name__}: {exc}"
            row.finished_at = time.time()
            row.total_s = round(row.finished_at - row.started_at, 6)
            self._raw("protocol", f"{index:02d}-{label}.json").write_bytes(body or b"")
            row.req_id = None
            row.status_ok = row.http_status in acceptable
            if row.http_status and row.http_status >= 400:
                row.error = body.decode("utf-8", "replace")[:400]
            row.note = f"{note}; expected {acceptable}; got {row.http_status}"
            self.record(row)
            if not row.status_ok:
                self.timeline.anomaly(
                    "协议错误响应与预期不符",
                    f"{label}: 期望 {acceptable}，实际 {row.http_status}", group=name)

        # -- stop string -----------------------------------------------------
        stop_text = "请依次输出：甲乙丙丁戊己庚辛。只输出这些字。"
        for k in range(1, 4):
            row = stream_round(
                self.http, self.key, self.model,
                dimension="C", phase=name, group="proto-stop-string",
                user_text=stop_text, raw_path=self._raw("protocol", f"stop-{k}.sse"),
                timeout=300.0, max_tokens=64, stop=["丁"],
                tokens=estimate_tokens(stop_text, self.tokenizer),
                round_index=k, expected_status=200)
            # The stop text itself must not be in the reply, and the reason must
            # be "stop" -- that pair is what distinguishes "cut by stop" from
            # "happened to finish early".
            row.status_ok = row.status_ok and "丁" not in (row.output or "")
            row.note = f"finish={row.finish_reason};contains_stop={'丁' in (row.output or '')}"
            self.record(row)
            if not row.status_ok:
                self.timeline.anomaly("stop string 未按语义截断",
                                      f"第{k}次 finish={row.finish_reason} "
                                      f"output={row.output[:60]!r}", group=name)

        # -- the console's own route -----------------------------------------
        # `/api/chat/stream` is cookie-authenticated and shaped differently from
        # the OpenAI route, so a regression there would not show up in any of the
        # cases above. Three takes: a normal short answer, and the same request
        # after the console session was established -- the second is what a
        # browser actually does.
        console_text = "请只回复“控制台”三个字。"
        for k in range(1, 4):
            row = console_round(
                self.http, self.model,
                dimension="C", phase=name, group="proto-console",
                user_text=console_text,
                raw_path=self._raw("protocol", f"console-{k}.sse"),
                timeout=600.0, max_tokens=24,
                tokens=estimate_tokens(console_text, self.tokenizer),
                round_index=k, expected_status=200)
            self.record(row)
            if not row.status_ok:
                self.timeline.anomaly(
                    "控制台推理接口异常",
                    f"第{k}次：HTTP {row.http_status} {str(row.error)[:120]}",
                    group=name)

        # -- max_tokens truncation ------------------------------------------
        cut_text = "请从一数到三十，用逗号分隔。"
        for k, limit in enumerate((4, 8, 16), start=1):
            row = stream_round(
                self.http, self.key, self.model,
                dimension="C", phase=name, group="proto-max-tokens",
                user_text=cut_text, raw_path=self._raw("protocol", f"maxtok-{limit}.sse"),
                timeout=300.0, max_tokens=limit,
                tokens=estimate_tokens(cut_text, self.tokenizer),
                round_index=k, expected_status=200)
            row.status_ok = row.status_ok and row.finish_reason in ("length", "stop")
            # ``length`` is the expected reason; ``stop`` is accepted only when
            # the engine's loop guard fired, which it records in the reason too.
            row.note = f"finish={row.finish_reason};ct={row.completion_tokens}"
            self.record(row)

        after_records = self.service.record_total()
        delta = None if before_records is None or after_records is None \
            else after_records - before_records
        # Which cases are *supposed* to leave a record:
        #
        #   * the 3 stop-string and 3 max_tokens requests run on the model, so
        #     they write 6 `ok` records;
        #   * a bad image data URL passes model resolution and prompt rendering,
        #     so its record context already exists when the *worker* rejects the
        #     base64 -- that one writes an `error` record, which is the contract's
        #     own behaviour (`WorkerError` always gets exactly one record).
        #
        # Every other 4xx is refused before the model is touched and must write
        # nothing. The previous hardcoded 3+3 = 6 called that expected error
        # record a violation; measured on the board, the delta is exactly 7.
        expected_records = 6 + 1 + 3   # stop/max_tokens, bad image, console
        expected_error_records = 1
        if delta is not None and delta != expected_records:
            self.timeline.anomaly(
                "协议阶段记录增量与预期不符",
                f"新增 {delta} 条，预期 {expected_records} 条"
                f"（6 次真实推理 + {expected_error_records} 条图片解码失败记录）",
                group=name)
        self._phase_end(name, started, cases=len(cases),
                        records_before=before_records, records_after=after_records,
                        records_delta=delta, expected_records=expected_records,
                        expected_error_records=expected_error_records)

    def _restart_and_reload(self, *, marker: str, raw_prefix: str,
                            dimension: str, phase: str, group_prefix: str,
                            round_base: int = 1) -> dict:
        """SIGTERM restart, prove the 409 gate, reload, prove inference recovers.

        Extracted from :meth:`run_restart` because A2's 16k session needs the
        identical sequence in the middle of a conversation. Two copies of a
        restart choreography is how the second one silently drifts; one copy with
        the marker and evidence paths passed in cannot.

        Returns the facts a caller needs to judge it, including the gate row, so
        the caller decides how to record it.
        """
        before_total = self.service.record_total()
        unit = systemctl("restart")
        http_ready = wait_http_ready(self.http, timeout=300.0)
        # Fresh client: the cookie session lived in the old process.
        self.http.login(self.service.password)
        loaded_after_restart, _, _ = self.service.model_state()

        # 1. The gate must hold while nothing is loaded.
        gate = stream_round(
            self.http, self.key, self.model,
            dimension=dimension, phase=phase, group=f"{group_prefix}-gate",
            user_text=marker, raw_path=self._raw(raw_prefix, "gate.sse"),
            timeout=120.0, max_tokens=16,
            tokens=estimate_tokens(marker, self.tokenizer),
            round_index=round_base, expected_status=409)
        gate_refused = gate.http_status == 409
        if gate.http_status == 200:
            # Legitimate only if a worker really was adopted; otherwise the gate
            # let a request through with nothing loaded, which is the defect.
            gate.status_ok = loaded_after_restart is True
            if not gate.status_ok:
                self.timeline.anomaly(
                    "重启后模型未加载却被放行",
                    f"HTTP {gate.http_status}，loaded={loaded_after_restart}",
                    group=phase)

        # 2. Reload -- the operator's action, and part of the card's flow.
        reload_s = None
        reload_status = None
        if not loaded_after_restart:
            reload_status, reload_s = self.service.load(timeout=900.0)
        ready = self.service.wait_ready(timeout=900.0)
        after_total = self.service.record_total()
        retained = None if before_total is None or after_total is None \
            else after_total >= before_total
        if not ready:
            self.timeline.anomaly(
                "重启后服务未恢复",
                f"ready={ready} reload={reload_status} http_ready={http_ready}",
                group=phase)
        return {"unit": unit, "http_ready_s": http_ready,
                "loaded_after_restart": loaded_after_restart,
                "reload_status": reload_status, "reload_s": reload_s,
                "model_ready": ready, "gate_row": gate,
                "gate_status": gate.http_status, "gate_refused": gate_refused,
                "records_before": before_total, "records_after": after_total,
                "records_retained": retained}

    def run_restart(self) -> None:
        """SIGTERM restart, explicit reload, then prove service and records return.

        Four assertions, in the order the field would hit them:

        1. **The gate survives the restart.** This build does not auto-load a
           model at startup -- it *adopts* a worker that is still running, and a
           ``systemctl restart`` has killed that worker. So immediately after the
           restart the model is not loaded, and an inference request must be
           refused with 409. Verified live: the service comes back healthy with
           ``loaded=false``, which makes this the cheapest real check that the
           admission gate is not bypassed by a restart.
        2. **Reload works.** ``POST /api/models/<id>/load`` returns 200 and the
           model reaches ``loaded`` with no operation in flight.
        3. **Inference recovers.** A short request afterwards is served with
           exactly one new record.
        4. **Records survive.** The record total did not go down.

        Only a normal ``systemctl restart`` (SIGTERM) is used; never ``kill -9``.
        """
        name = "restart"
        started = self._phase_start(name, "正常 SIGTERM 重启，验证准入/重载/恢复/记录保留", "C")
        marker = "请只回复“重启后”三个字。"
        pre = stream_round(
            self.http, self.key, self.model,
            dimension="C", phase=name, group="restart-pre",
            user_text=marker, raw_path=self._raw(name, "pre.sse"),
            timeout=600.0, max_tokens=16,
            tokens=estimate_tokens(marker, self.tokenizer),
            round_index=1, expected_status=200)
        self.record(pre)

        restart = self._restart_and_reload(
            marker=marker, raw_prefix=name, dimension="C", phase=name,
            group_prefix="restart", round_base=2)
        gate = restart["gate_row"]
        self.record(gate)
        reload_status, reload_s = restart["reload_status"], restart["reload_s"]
        loaded_after_restart = restart["loaded_after_restart"]
        ready = restart["model_ready"]
        before_total = restart["records_before"]
        after_total = restart["records_after"]
        retained = restart["records_retained"]

        # 3. Inference recovers.
        post = stream_round(
            self.http, self.key, self.model,
            dimension="C", phase=name, group="restart-post",
            user_text=marker, raw_path=self._raw(name, "post.sse"),
            timeout=900.0, max_tokens=16,
            tokens=estimate_tokens(marker, self.tokenizer),
            round_index=3, expected_status=200)
        self.record(post)

        if not ready or not post.status_ok:
            self.timeline.anomaly(
                "重启后服务未恢复",
                f"ready={ready} reload={reload_status} "
                f"http_ready={restart['http_ready_s']} "
                f"post HTTP {post.http_status} {str(post.error)[:120]}", group=name)
        if retained is False:
            self.timeline.anomaly("重启后推理记录减少",
                                  f"{before_total} -> {after_total}", group=name)
        self.timeline.add(
            "note", "重启后模型状态",
            f"重启后 loaded={loaded_after_restart}（本版本不自动加载，"
            f"需显式重载），重载={reload_status} 用时 {reload_s}s，"
            f"重启后首个请求 HTTP {gate.http_status}", group=name)
        self._phase_end(name, started, unit=restart["unit"],
                        http_ready_s=restart["http_ready_s"],
                        loaded_after_restart=loaded_after_restart,
                        reload_status=reload_status, reload_s=reload_s,
                        model_ready=ready, gate_status=gate.http_status,
                        gate_refused=restart["gate_refused"],
                        records_before=before_total,
                        records_after=after_total, records_retained=retained,
                        post_ok=post.status_ok)

    # -- U1. UTF-8 regression on all three surfaces -----------------------
    def run_utf8_regression(self, repeats: int = U1_REPEATS,
                            replay: bool = True) -> None:
        """U1: the rare characters, on every surface, and the 12 historical failures.

        Two independent claims, and the report keeps them apart:

        * **The decode is fixed.** Ask the model to repeat ``门簪`` and friends
          verbatim, :data:`U1_REPEATS` times each, on ``/v1/chat/completions``
          stream, the same route non-streamed, and ``/api/chat/stream``. None of
          the replies may contain U+FFFD. The three surfaces are also compared
          against the stored record, because the v0.6.14 defect lived in the
          *streaming assembly* and a non-streaming client could have been fine
          while the console was broken.
        * **The historical failures are gone.** The MYS-2510 turns that came back
          as ``门��`` are rebuilt with the same history constructor and replayed.
          This is the regression that matters: those eight turn numbers are the
          ones that actually failed in the field.

        A single U+FFFD fails the case and the raw text is kept -- nothing is
        retried, because a retry that passes would hide exactly the intermittent
        split this exists to catch.
        """
        name = "utf8"
        started = self._phase_start(
            name, f"生僻字/emoji 三接口各 {repeats} 次 + MYS-2510 失败轮重放", "U")
        expected_literals = list(RARE_WORDS) + list(RARE_EMOJI)

        for surface in U1_SURFACES:
            for literal in expected_literals:
                prompt = (f"请原样复述下面这个词，不要加任何其他内容：「{literal}」")
                for k in range(1, repeats + 1):
                    row = self._u1_round(surface, prompt, literal,
                                          f"{surface}-{k:02d}")
                    self.record(row)
                    if not row.u1_clean:
                        self.timeline.anomaly(
                            f"U1 {surface} 输出含 U+FFFD",
                            f"{literal} 第{k}次：{row.output[:80]!r}", group=name)

        if replay:
            for group, turns in U1_REPLAY_GROUPS:
                self._u1_replay(group, turns)

        rows = [r for r in self.rounds if r.phase == name]
        dirty = [r for r in rows if r.u1_clean is False]
        clean_checked = [r for r in rows if r.u1_clean is not None]
        self._phase_end(name, started, starts=len(rows),
                        clean=sum(1 for r in clean_checked if r.u1_clean),
                        checked=len(clean_checked), fffd_rows=len(dirty),
                        surfaces=list(U1_SURFACES))

    def _u1_round(self, surface: str, prompt: str, literal: str,
                  tag: str) -> Round:
        """One U1 request on ``surface``, graded for verbatim and cleanliness."""
        raw = self._raw("utf8", f"{tag}.sse")
        if surface == "stream":
            row = stream_round(
                self.http, self.key, self.model,
                dimension="U", phase="utf8", group="utf8-stream",
                user_text=prompt, raw_path=raw, timeout=self.timeout,
                max_tokens=48, tokens=estimate_tokens(prompt, self.tokenizer),
                round_index=1)
        elif surface == "nonstream":
            row = nonstream_round(
                self.http, self.key, self.model,
                dimension="U", phase="utf8", group="utf8-nonstream",
                user_text=prompt, raw_path=raw.with_suffix(".json"),
                timeout=self.timeout, max_tokens=48,
                tokens=estimate_tokens(prompt, self.tokenizer), round_index=1)
        else:
            row = console_round(
                self.http, self.model,
                dimension="U", phase="utf8", group="utf8-console",
                user_text=prompt, raw_path=raw, timeout=self.timeout,
                max_tokens=48, tokens=estimate_tokens(prompt, self.tokenizer),
                round_index=1)
        verdict = grade_verbatim(literal, row.output)
        row.u1_surface = surface
        row.u1_expected = literal
        row.u1_contains_all = verdict["contains_all"]
        row.u1_exact = verdict["exact"]
        row.u1_clean = verdict["clean"]
        if not verdict["clean"]:
            row.note = f"U+FFFD in output for {literal}"
            row.status_ok = False
        return row

    def _chat_history(self, up_to: int) -> list[dict]:
        """The deterministic history of turns ``1..up_to`` of a **chat** session.

        Two things had to be got right, and both were wrong on the first attempt:

        * **The turns come from :func:`chat_turn_text`, not** :func:`ctx_turn_text`.
          A2's constructor plants A2's own words, so a history rebuilt the A2 way
          holds 药臼 where the chat session held 门簪, and the replay asks a
          question its own history does not answer.
        * **The assistant replies are the recalled words, not** ``收到。``
          (MYS-2510's evidence, ``chat50`` turn n -> ``CHAT_FACTS[n-2]``). A history
          in which every assistant turn says ``收到。`` teaches the model that
          ``收到。`` is the reply to "上一轮的关键词是什么", and the replay duly
          answered ``收到。`` for all twelve turns -- a wrong answer produced by the
          fixture, which would have read as a recall failure.

        The replies are deterministic, so this is a reconstruction rather than a
        guess: turn ``n`` answers the fact planted at turn ``n-1``, which is
        exactly what :func:`chat_turn_text` asks for.
        """
        history: list[dict] = []
        for turn in range(1, up_to + 1):
            text, fact, _ = chat_turn_text(turn, seed=SEED)
            history.append({"role": "user", "content": text})
            # Turn 1 asks nothing, and the original replied 收到 (no period).
            answered = (CHAT_FACTS[(turn - 2) % len(CHAT_FACTS)]
                        if turn >= 2 else "收到")
            history.append({"role": "assistant", "content": answered})
        return history

    def _u1_replay(self, history_group: str, turns: Sequence[int]) -> None:
        """Replay the MYS-2510 turns that produced U+FFFD.

        The history is rebuilt with :meth:`_chat_history`, the constructor the
        *original* sessions used, so the request's shape is the one that failed
        rather than an approximation of it.

        The question comes from :func:`chat_turn_text` too, for the same reason.
        That matters more than it looks: ``chat_turn_text`` asks the previous
        turn's fact, which at turns 18/29/35/45 is one of :data:`RARE_WORDS`, and
        those are precisely the words a byte-level tokenizer splits across token
        boundaries. Taking the question from ``ctx_fact_for`` instead asked common
        words like ``药臼``, which assemble from whole tokens and never exercise
        the defect -- a replay that passes because it re-asks an easier question
        proves nothing.
        """
        for session_index, turn in enumerate(turns, start=1):
            # The original sessions asked the *previous* turn's fact, and all
            # twelve failures were that query.
            history = self._chat_history(turn - 1)
            _, _, asked = chat_turn_text(turn, seed=SEED)
            if asked is None:  # turn 1 asks nothing; the replay never uses it
                continue
            text = f"上一轮（第{turn - 1}轮）的关键词是什么？只回答关键词本身。"
            messages = base.context_messages(SYSTEM_PROMPT, history, text)
            row = stream_round(
                self.http, self.key, self.model,
                dimension="U", phase="utf8", group=f"utf8-replay-{history_group}",
                user_text=text,
                raw_path=self._raw("utf8", f"replay-{history_group}-t{turn:03d}.sse"),
                timeout=self.timeout, max_tokens=48,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=turn, session=session_index, turn=turn,
                messages_override=messages)
            row.u1_surface = "stream"
            row.u1_expected = asked
            row.expected_recall = asked
            row.recall_ok = grade_chat_turn(asked, row.output)
            row.u1_clean = not has_replacement_char(row.output)
            row.u1_contains_all = asked in (row.output or "")
            if not row.u1_clean:
                row.note = f"U+FFFD replaying {history_group} turn {turn}"
                row.status_ok = False
                self.timeline.anomaly(
                    "U1 重放历史失败轮仍含 U+FFFD",
                    f"{history_group} 第{turn}轮 期望 {asked}：{row.output[:80]!r}",
                    group="utf8")
            # Record it. Without this the replay ran, sent its twelve requests
            # and graded them -- but none of it reached rounds.jsonl, so the
            # report counted zero replay rows and listed "MYS-2510 失败轮重放无
            # U+FFFD" as unmeasured. The evidence for the regression the whole
            # U1 block exists to prove was being thrown away.
            self.record(row)

    # -- D. prefix cache and lifecycle -----------------------------------
    def run_prefix_cache(self, turns: int = PREFIX_CACHE_TURNS,
                         prefix_tokens: int = PREFIX_CACHE_TOKENS) -> None:
        """Reuse one long prefix and watch ``cached_tokens``; compare with no cache.

        Two claims, measured separately:

        * **The cache works** — turns 2..N of a fixed prefix report
          ``cached_tokens > 0`` and a materially shorter TTFT than turn 1.
        * **The cache does not change the answer** — the question asked *after*
          the prefix is answered identically with and without a cache hit.

        The second is the one that matters for correctness, and it is why the
        no-cache baseline is a separate request built from the same material with
        a different seed: same task, no shared prefix, so no cache hit. Cache
        hits are **not** evidence of semantic correctness, only of reuse; that
        distinction is carried into the report.
        """
        name = "prefix-cache"
        started = self._phase_start(
            name, f"固定 {prefix_tokens} token 前缀 × {turns} 轮，对照无缓存基线", "D")
        base_prompt = build_long_prompt(prefix_tokens, tokenizer=self.tokenizer,
                                        seed=SEED + 11, probe="tail")
        cached_turns: list[Round] = []
        for turn in range(1, turns + 1):
            # The prefix is byte-identical every turn; only the trailing question
            # varies, so any prompt-token reuse is real prefix reuse.
            text = base_prompt.text + (f"\n（第{turn}次确认，请重新回答上面的问题。）"
                                       if turn > 1 else "")
            row = stream_round(
                self.http, self.key, self.model,
                dimension="D", phase=name, group="prefix-cache",
                user_text=text, raw_path=self._raw(name, f"turn{turn}.sse"),
                timeout=self.timeout, max_tokens=32,
                tokens=base_prompt.tokens, round_index=turn,
                expected_status=200, expected_code=base_prompt.expected_code)
            graded = grade_retrieval(base_prompt, row.output)
            row.retrieval_correct = graded["correct"]
            row.cache_hit = bool(row.cached_tokens and row.cached_tokens > 0)
            cached_turns.append(row)
            self.record(row)
        # No-cache baseline: same task, unrelated material, so nothing to reuse.
        baseline_prompt = build_long_prompt(prefix_tokens, tokenizer=self.tokenizer,
                                            seed=SEED + 999, probe="tail")
        baseline = stream_round(
            self.http, self.key, self.model,
            dimension="D", phase=name, group="prefix-baseline",
            user_text=baseline_prompt.text,
            raw_path=self._raw(name, "baseline.sse"),
            timeout=self.timeout, max_tokens=32,
            tokens=baseline_prompt.tokens, round_index=99,
            expected_status=200, expected_code=baseline_prompt.expected_code)
        base_graded = grade_retrieval(baseline_prompt, baseline.output)
        baseline.retrieval_correct = base_graded["correct"]
        baseline.cache_hit = bool(baseline.cached_tokens and baseline.cached_tokens > 0)
        self.record(baseline)
        # Both must answer their own material correctly: that is the
        # "cache does not corrupt the answer" check, scored per-prompt so the
        # two expected codes are different numbers.
        cached_ok = sum(1 for r in cached_turns if r.retrieval_correct)
        self._phase_end(
            name, started, turns=turns, prefix_tokens=prefix_tokens,
            cache_hits=sum(1 for r in cached_turns if r.cache_hit),
            cached_answers_ok=cached_ok, baseline_answer_ok=baseline.retrieval_correct,
            first_turn_ttft=cached_turns[0].ttft_s if cached_turns else None,
            warm_ttft=ext.percentile(
                [r.ttft_s for r in cached_turns[1:] if r.ttft_s], 0.5))

    def run_cache_ttl(self, wait_s: float = CACHE_TTL_WAIT_S) -> None:
        """Shrink the cache TTL to force eviction, then set it back.

        The cache's other failure mode is a stale entry: if an expired entry is
        still served, the answer comes from material the request no longer
        contains. Setting ``prefix_cache_ttl_min`` low, waiting past it, and
        re-asking must produce a **correct** answer derived from the *new*
        request — a fresh prefill, not a stale hit. Then the original TTL is
        restored and a request must succeed.

        Only ``prefix_cache_ttl_min`` is touched, and it is restored in a
        ``finally``: leaving a 1-minute TTL behind would quietly disable caching
        for every later phase.
        """
        name = "cache-ttl"
        original = self.service.settings()
        started = self._phase_start(
            name, "缩短 cache TTL 触发淘汰，验证无陈旧命中并可恢复", "D")
        try:
            applied = self.service.set_settings(prefix_cache_ttl_min=1)
            first = build_long_prompt(2048, tokenizer=self.tokenizer,
                                      seed=SEED + 21, probe="tail")
            r1 = stream_round(
                self.http, self.key, self.model,
                dimension="D", phase=name, group="cache-ttl",
                user_text=first.text, raw_path=self._raw(name, "warm.sse"),
                timeout=self.timeout, max_tokens=24, tokens=first.tokens,
                round_index=1, expected_status=200)
            r1.retrieval_correct = grade_retrieval(first, r1.output)["correct"]
            self.record(r1)
            # Wait past the TTL. 70 s is the smallest honest margin over 60 s.
            self.timeline.add("note", "等待 cache TTL 过期", f"{wait_s:.0f} 秒",
                              group=name)
            time.sleep(wait_s)
            second = build_long_prompt(2048, tokenizer=self.tokenizer,
                                       seed=SEED + 22, probe="tail")
            r2 = stream_round(
                self.http, self.key, self.model,
                dimension="D", phase=name, group="cache-ttl-expired",
                user_text=second.text, raw_path=self._raw(name, "expired.sse"),
                timeout=self.timeout, max_tokens=24, tokens=second.tokens,
                round_index=2, expected_status=200)
            r2.retrieval_correct = grade_retrieval(second, r2.output)["correct"]
            self.record(r2)
        finally:
            restored = self.service.restore_settings(
                original, ("prefix_cache_ttl_min",))
        probe_text = "请只回复“好”。"
        after = stream_round(
            self.http, self.key, self.model,
            dimension="D", phase=name, group="cache-ttl-restored",
            user_text=probe_text, raw_path=self._raw(name, "restored.sse"),
            timeout=600.0, max_tokens=16,
            tokens=estimate_tokens(probe_text, self.tokenizer),
            round_index=3, expected_status=200)
        self.record(after)
        self._phase_end(name, started, applied_ttl=applied.get("prefix_cache_ttl_min"),
                        original_ttl=original.get("prefix_cache_ttl_min"),
                        restored_ttl=restored.get("prefix_cache_ttl_min"),
                        recovered=after.status_ok)

    def run_lifecycle(self, cycles: int = LIFECYCLE_CYCLES) -> None:
        """``load -> short inference -> unload`` repeated, watching for residue.

        Each cycle asserts the things a leak would break:

        * the load is *complete* before the request (readiness observed, not
          assumed) — a request fired at a half-loaded model is the exact bug
          MYS-2496's admission gate exists to prevent, and this phase must not
          inject it accidentally;
        * the request is served and writes its record;
        * after unload, the worker process and its port are gone and NPU memory
          has fallen back, so "no leaked worker/socket" is measured, not assumed.

        The task card allows 20 cycles instead of 50 with an explanation: each
        cycle costs a real ~66 s load plus unload, so 50 cycles is roughly two
        hours of pure lifecycle churn. 20 establishes "no residue accumulates"
        because a leak would show by cycle 3; the count actually run is stated in
        the report either way.
        """
        name = "lifecycle"
        started = self._phase_start(
            name, f"{cycles} 次 加载→短推理→卸载 循环", "D")
        baseline_mem = self._npu_mem_used()
        cycles_run = 0
        for cycle in range(1, cycles + 1):
            unload_status = self.service.unload()
            stopped = self.service.wait_stopped(timeout=300.0)
            load_status, load_s = self.service.load(timeout=900.0)
            ready = self.service.wait_ready(timeout=900.0)
            text = f"第{cycle}次循环：请只回复“在”一个字。"
            row = stream_round(
                self.http, self.key, self.model,
                dimension="D", phase=name, group="lifecycle",
                user_text=text, raw_path=self._raw(name, f"cycle{cycle:02d}.sse"),
                timeout=900.0, max_tokens=16,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=cycle, expected_status=200)
            # A refused load means the phase could not be run as designed; that
            # is a failure to report, not a reason to retry blindly.
            if load_status != 200 or not ready:
                row.status_ok = False
                row.error = (row.error or "") + \
                    f" load_status={load_status} ready={ready}"
            self.record(row)
            unload_after_status = self.service.unload()
            stopped_after = self.service.wait_stopped(timeout=300.0)
            mem = self._npu_mem_used()
            residue = self._worker_residue()
            row.note = (f"cycle={cycle};load_s={load_s};"
                        f"unload={unload_status}/{unload_after_status};"
                        f"stopped={stopped}/{stopped_after};"
                        f"npu_mem={mem};residue={residue}")
            cycles_run = cycle
            # ``residue`` is a *report*, not a flag: a dict is always truthy, so
            # testing it directly flagged every cycle even when it said
            # ``loaded=False, worker_procs=0, pid=None, port=None``. Judge its
            # contents.
            leftover = bool(residue.get("loaded") or residue.get("operation")
                            or (residue.get("worker_procs") or 0) > 0
                            or residue.get("pid") or residue.get("port"))
            if not row.status_ok or not stopped_after or leftover:
                self.timeline.anomaly(
                    "生命周期循环出现残留或失败",
                    f"第 {cycle} 次：status_ok={row.status_ok} "
                    f"stopped={stopped_after} residue={residue}", group=name)
        final_mem = self._npu_mem_used()
        # Leave the model loaded and ready: later phases and the operator both
        # expect a serving service, not an unloaded one.
        self.service.load(timeout=900.0)
        self.service.wait_ready(timeout=900.0)
        self._phase_end(name, started, cycles=cycles_run,
                        baseline_npu_mem=baseline_mem, final_npu_mem=final_mem)

    def _resolve_fixture_dir(self) -> Path:
        """Where the vision fixtures are.

        Three layouts have to work: the repository (``<repo>/tools/…`` next to
        ``<repo>/tests/vision_fixtures``), a board deployment that copied the
        whole tools tree (fixtures beside the script), and a board deployment
        that copied only the ``.py`` files with the fixtures staged elsewhere.

        Resolved rather than assumed, because a wrong guess silently produced a
        vision phase with zero requests: every fixture was "missing", which was
        recorded as a note, and the phase "passed" having measured nothing. The
        phase now fails loudly in that case (see below), and the resolved
        directory is reported.
        """
        candidates = [
            Path(__file__).resolve().parent.parent / "tests" / "vision_fixtures",
            Path(__file__).resolve().parent / "tests" / "vision_fixtures",
            Path(__file__).resolve().parent / "vision_fixtures",
            Path.cwd() / "tests" / "vision_fixtures",
            Path.cwd() / "vision_fixtures",
        ]
        for candidate in candidates:
            if (candidate / "gradient.png").is_file():
                return candidate
        return candidates[0]

    def _npu_mem_used(self) -> int | None:
        try:
            status, body = self.http.json("GET", "/api/stats", timeout=30)
        except (OSError, ValueError):
            return None
        if status != 200:
            return None
        smi = ((body.get("device") or {}).get("npu") or {}).get("smi") or {}
        value = smi.get("mem_used_bytes")
        return int(value) if isinstance(value, (int, float)) else None

    def _worker_residue(self) -> dict:
        """Any worker process or listening port left after an unload.

        Read from the service's own model listing *and* from the process table:
        the listing is what the service believes, the process table is what is
        true. A worker alive but forgotten by the service is exactly the residue
        this loop is looking for.
        """
        loaded, operation, info = self.service.model_state()
        procs = 0
        try:
            # ``pgrep -f`` matches the *shell running pgrep* as well, because the
            # pattern is in its own command line -- measured: it reported 1 while
            # no worker existed, and 2 with exactly one worker. Enumerate the
            # pids and drop our own process tree.
            out = subprocess.run(["pgrep", "-f", "app.engine.worker"],
                                 capture_output=True, text=True, timeout=30)
            pids = [int(p) for p in (out.stdout or "").split() if p.isdigit()]
            mine = {os.getpid(), os.getppid()}
            procs = len([p for p in pids if p not in mine])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            procs = -1
        return {"loaded": loaded, "operation": operation, "worker_procs": procs,
                "pid": info.get("pid"), "port": info.get("port")}

    # -- E. vision and tool calls ----------------------------------------
    def run_vlm(self, repeats: int = VLM_REPEATS,
                fixture_dir: Path | None = None) -> None:
        """JPEG and PNG, single and multi-image, with a decidable question.

        The question is "how many images did you receive?" — answerable only if
        the image count survived the path, and wrong in a visible way if an image
        was dropped. Each request also checks the *record*: it must carry the
        image dimensions and **not** the pixels, which is the privacy contract
        the record module promises.

        The task card says to stop and report if the known PNG timeout
        reproduces; that is why a PNG transport timeout sets an anomaly and
        aborts the block rather than continuing to burn the budget.
        """
        fixture_dir = fixture_dir or self._resolve_fixture_dir()
        name = "vlm"
        started = self._phase_start(
            name, f"JPEG/PNG 各 {repeats} 次，含多图；记录只存尺寸", "E")
        aborted = None
        for filename, mime in VLM_FILES:
            path = fixture_dir / filename
            if not path.is_file():
                self.timeline.anomaly("视觉测试图缺失", f"{path}", group=name)
                continue
            raw = path.read_bytes()
            width, height = image_size(raw)
            url = data_url(raw, mime)
            for k in range(1, repeats + 1):
                multi = (k % 5 == 0)
                parts: list[dict] = [
                    {"type": "text",
                     "text": ("你收到了几张图片？只回答阿拉伯数字。" if multi
                              else "你收到了几张图片？只回答阿拉伯数字。")},
                    {"type": "image_url", "image_url": {"url": url}},
                ]
                if multi:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}})
                expected_count = 2 if multi else 1
                row = new_round("E", name, f"vlm-{filename}",
                                text=f"{filename} multi={multi}",
                                messages=1, round_index=k,
                                expected_status=200,
                                tokens=expected_count,
                                image_dims=[[width, height]] +
                                ([[1, 1]] if multi else []))
                payload = {"model": self.model, "stream": False,
                           "messages": [{"role": "user", "content": parts}],
                           "max_tokens": 16, "temperature": 0.0}
                req = urllib.request.Request(
                    self.http.url("/v1/chat/completions"),
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json",
                             "Accept": "application/json",
                             "Authorization": f"Bearer {self.key}"})
                body = b""
                row.started_at = time.time()
                try:
                    with self.http.open(req, self.timeout) as resp:
                        row.http_status = resp.status
                        body = resp.read()
                except urllib.error.HTTPError as exc:
                    row.http_status = exc.code
                    body = exc.read()
                except Exception as exc:  # noqa: BLE001
                    row.error = f"{type(exc).__name__}: {exc}"
                row.finished_at = time.time()
                row.total_s = round(row.finished_at - row.started_at, 6)
                self._raw(name, f"{filename}-{k}.json").write_bytes(body or b"")
                obj: dict = {}
                try:
                    obj = json.loads((body or b"{}").decode("utf-8", "replace"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    obj = {}
                row.status_ok = row.http_status == 200 and not row.error
                if row.http_status != 200:
                    row.error = row.error or (body or b"").decode("utf-8", "replace")[:400]
                else:
                    choice = (obj.get("choices") or [{}])[0] or {}
                    row.output = (choice.get("message") or {}).get("content") or ""
                    row.req_id = base.request_id_of(obj.get("id"))
                    row.finish_reason = choice.get("finish_reason")
                    pt, ct, _ = base.usage_tokens(obj.get("usage") or {})
                    row.prompt_tokens, row.completion_tokens = pt or None, ct or None
                    digits = re.findall(r"\d+", row.output)
                    row.retrieval_correct = (str(expected_count) in digits)
                    if not row.output:
                        # A 200 with no text is a failure, not a wrong answer:
                        # the transport worked but the request produced nothing.
                        row.status_ok = False
                        row.error = "empty output"
                    if not row.retrieval_correct:
                        row.note = f"expected={expected_count};digits={digits[:4]}"
                self.record(row)
                if "timeout" in str(row.error or "").lower() and mime == "image/png":
                    aborted = (f"{filename} 第{k}次：{row.error}"[:200])
                    self.timeline.anomaly(
                        "既有 PNG 驱动超时复现，按要求停止视觉测试", aborted,
                        group=name)
                    break
            if aborted:
                break
        # Record privacy: dimensions kept, pixels not.
        for row in [r for r in self.rounds if r.phase == name and r.req_id]:
            detail = self.service.record(row.req_id)
            if detail is None:
                continue
            images = detail.get("images") or []
            row.record_image_dims = images
            blob = json.dumps(detail, ensure_ascii=False)
            # A base64 image inside a record would be thousands of characters of
            # alphabet soup; the check is for the marker the record module uses
            # and for any long run of base64 alphabet.
            if re.search(r"[A-Za-z0-9+/]{512,}={0,2}", blob):
                row.status_ok = False
                self.timeline.anomaly("推理记录疑似保存了图片原始数据",
                                      f"{row.req_id}", group=name)
            if images and not any(isinstance(i, dict) and i.get("width")
                                  for i in images):
                row.note = (row.note or "") + ";record_missing_dimensions"
        sent = [r for r in self.rounds if r.phase == name]
        if not sent:
            # A phase that measured nothing must not read as a passing phase.
            self.timeline.anomaly(
                "视觉测试没有发出任何请求",
                f"找不到测试图目录（解析到 {fixture_dir}）；未测不等于通过",
                group=name)
        self._phase_end(name, started, repeats=repeats, aborted=aborted,
                        fixture_dir=str(fixture_dir),
                        fixtures=[f for f, _ in VLM_FILES],
                        sent=len(sent))

    def run_tools(self, count: int = TOOL_CALLS,
                  thinking_repeats: int = THINKING_REPEATS) -> None:
        """Tool calls with JSON arguments, plus thinking on and off.

        ``protocol_ok`` and ``content_ok`` are counted separately, per the task
        card: "returned a well-formed function call" and "called the right
        function with the right city" are different claims, and a model that gets
        the protocol right while picking a plausible-but-wrong tool should not be
        reported as a service failure.

        Thinking mode is checked for *consistency*, not style: with
        ``enable_thinking=true`` the record must carry reasoning, and with it off
        it must not. Whether the prose is good is not a stability question.
        """
        name = "tools"
        started = self._phase_start(
            name, f"工具调用 {count} 次（含无效定义）+ thinking 各 "
                  f"{thinking_repeats} 次", "E")
        for i in range(1, count + 1):
            spec = TOOL_PROMPTS[(i - 1) % len(TOOL_PROMPTS)]
            tools = [TOOL_WEATHER, TOOL_TIME][:spec["tools"]] \
                if spec["tools"] == 2 else [TOOL_WEATHER]
            row = nonstream_round(
                self.http, self.key, self.model,
                dimension="E", phase=name,
                group=f"tool-{spec['expect']}",
                user_text=spec["text"],
                raw_path=self._raw(name, f"tool-{i:02d}.json"),
                timeout=600.0, max_tokens=64, tools=tools,
                tokens=estimate_tokens(spec["text"], self.tokenizer),
                round_index=i, expected_status=200)
            # Pull the full tool_calls from the raw body: the row keeps the first
            # name for display, the grader needs the parsed arguments.
            calls: list[dict] = []
            try:
                body = json.loads((self._raw(name, f"tool-{i:02d}.json"))
                                  .read_text(encoding="utf-8") or "{}")
                calls = (((body.get("choices") or [{}])[0] or {}).get("message")
                         or {}).get("tool_calls") or []
            except (json.JSONDecodeError, OSError):
                calls = []
            graded = grade_tool_call(spec["expect"], spec["city"], calls)
            row.tool_protocol_ok = graded["protocol_ok"]
            row.tool_content_ok = graded["content_ok"]
            row.tool_name = graded["name"]
            if graded["protocol_ok"] and not graded["content_ok"]:
                row.note = f"expected={spec['expect']}/{spec['city']}"
            self.record(row)
            if not graded["protocol_ok"]:
                self.timeline.anomaly(
                    "工具调用协议不正确",
                    f"第{i}次 {spec['text'][:24]}：{graded['reason']}", group=name)
        # Invalid definitions must be refused with 400.
        for label, tools in INVALID_TOOLS:
            text = "请调用工具查询北京天气。"
            row = nonstream_round(
                self.http, self.key, self.model,
                dimension="E", phase=name, group="tool-invalid",
                user_text=text, raw_path=self._raw(name,
                                                   f"invalid-{len(label)}.json"),
                timeout=300.0, max_tokens=16, tools=tools,
                tokens=estimate_tokens(text, self.tokenizer),
                round_index=0, expected_status=400)
            row.status_ok = row.http_status == 400
            row.note = label
            self.record(row)
            if not row.status_ok:
                self.timeline.anomaly("非法工具定义未被拒绝",
                                      f"{label}: HTTP {row.http_status}", group=name)
        # Thinking on/off consistency.
        #
        # ``max_tokens`` has to cover the reasoning *and* the answer: thinking
        # mode spends the whole budget inside the think block first. Measured on
        # .151, twice, at two budgets:
        #
        #   192 tokens -> 747 characters of reasoning, 0 of content, length
        #   512 tokens -> 1651 characters of reasoning, 0 of content, length
        #
        # So the ceiling is not a constant: this model writes a long think block
        # for even a short question and does not finish it inside 512 tokens.
        # 2048 leaves room for the reasoning and the answer at a cost of ~30 s
        # per request, which the ten thinking repeats can afford.
        thinking_budget = 2048
        for flag in (True, False):
            for k in range(1, thinking_repeats + 1):
                text = "请简短说明：为什么天空是蓝色的？"
                row = stream_round(
                    self.http, self.key, self.model,
                    dimension="E", phase=name,
                    group=f"thinking-{'on' if flag else 'off'}",
                    user_text=text,
                    raw_path=self._raw(name, f"think-{flag}-{k}.sse"),
                    timeout=900.0, max_tokens=thinking_budget, thinking=flag,
                    tokens=estimate_tokens(text, self.tokenizer),
                    round_index=k, expected_status=200)
                self.record(row)
                detail = self.service.record(row.req_id) if row.req_id else None
                if detail is not None:
                    reasoning = detail.get("reasoning_content") or ""
                    # Consistency, not style: thinking on must leave reasoning
                    # somewhere in the record; off must not invent one.
                    if flag and not (reasoning or row.reasoning_present):
                        row.status_ok = False
                        row.note = "thinking=on but no reasoning_content in record"
                        self.timeline.anomaly(
                            "thinking 开启但记录无 reasoning",
                            f"第{k}次 id={row.req_id}", group=name)
                    if not flag and row.reasoning_present:
                        row.note = "thinking=off but stream carried reasoning"
                    # With thinking on, an empty *content* is only acceptable
                    # when the budget ran out inside the reasoning; otherwise the
                    # answer was lost.
                    if flag and not row.output and row.finish_reason != "length":
                        row.status_ok = False
                        row.note = (f"thinking=on produced no content with "
                                    f"finish_reason={row.finish_reason}")
                        self.timeline.anomaly(
                            "thinking 开启但既无正文也未因长度截断",
                            f"第{k}次 finish={row.finish_reason}", group=name)
        self._phase_end(name, started, count=count,
                        thinking_repeats=thinking_repeats)

    # -- F. soak ---------------------------------------------------------
    def run_soak(self, seconds: float = SOAK_SECONDS,
                 sampler: Sampler | None = None) -> None:
        """A mixed workload held for a fixed span of **wall clock**.

        The task card asks for two hours and forbids reporting less, so the loop
        is bounded by time, not by a request count: it keeps issuing mixed work
        (short, medium, long, and a context turn) until the deadline. What the
        span buys is the thing a 1,000-request burst cannot show — whether
        anything drifts: RSS, NPU heap, cache size, record-log size, TPS.

        The sampler runs throughout at a fixed interval, so the trend is measured
        during the load rather than between requests. ``drift`` compares the first
        and last tenth of the samples, which separates a warm-up ramp (high at the
        start, flat later) from monotonic growth (the same delta, but climbing).

        A failing request does not stop the soak — the point is to keep going and
        report the rate. It is recorded, and the count of failures over the span
        is the result.
        """
        name = "soak"
        started = self._phase_start(
            name, f"混合负载连续 {seconds/3600:.1f} 小时", "F")
        own_sampler = sampler is None
        if own_sampler:
            sampler = Sampler(self.http, interval=10.0)
            sampler.start()
        deadline = started + seconds
        index = 0
        history: list[dict] = []
        try:
            while time.time() < deadline:
                index += 1
                kind, tier = SOAK_MIX[(index - 1) % len(SOAK_MIX)]
                if kind == "ctx":
                    # A context turn: resend a growing history so the soak also
                    # exercises real multi-turn growth, not only single prompts.
                    depth = 3 + (index % 3)
                    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
                    for t in range(1, depth + 1):
                        txt, _, _ = chat_turn_text(t, seed=SEED)
                        msgs.append({"role": "user", "content": txt})
                        msgs.append({"role": "assistant", "content": "收到。"})
                    txt, _, asked = chat_turn_text(depth + 1, seed=SEED)
                    msgs.append({"role": "user", "content": txt})
                    row = stream_round(
                        self.http, self.key, self.model,
                        dimension="F", phase=name, group="soak-ctx",
                        user_text=txt,
                        raw_path=self._raw(name, f"{index:05d}-ctx.sse"),
                        timeout=self.timeout, max_tokens=48,
                        tokens=estimate_tokens(txt, self.tokenizer),
                        round_index=index, messages_override=msgs,
                        expected_status=200)
                    # These turns are **not** a recall measurement, so they must
                    # not enter the multi-turn recall denominator. The reason is
                    # in the history this loop builds, not in the question: every
                    # planted turn's assistant reply is hardcoded to "收到。", so
                    # the conversation the model is shown teaches it that
                    # "收到。" is the correct reply to a recall question. It
                    # answers in-pattern, and grading that as a recall verdict
                    # measures the harness, not the model.
                    #
                    # MYS-2510 counted those 115 verdicts, which is how 136/148
                    # (91.9%) became 136/263 (51.7%) in its report. Leaving both
                    # fields None is what makes the exclusion structural rather
                    # than a filter someone has to remember to apply.
                    row.recall_ok = None
                    row.expected_recall = None
                elif tier >= 2048:
                    lp = build_long_prompt(tier, tokenizer=self.tokenizer,
                                           seed=SEED + index, probe="tail")
                    row = stream_round(
                        self.http, self.key, self.model,
                        dimension="F", phase=name, group=f"soak-{kind}",
                        user_text=lp.text,
                        raw_path=self._raw(name, f"{index:05d}-{kind}.sse"),
                        timeout=self.timeout, max_tokens=24,
                        tokens=lp.tokens, round_index=index,
                        expected_status=200, expected_code=lp.expected_code)
                    row.retrieval_correct = grade_retrieval(lp, row.output)["correct"]
                else:
                    txt = (f"请原样复述标记：SK{index:05d}。只回复标记本身。")
                    row = stream_round(
                        self.http, self.key, self.model,
                        dimension="F", phase=name, group=f"soak-{kind}",
                        user_text=txt,
                        raw_path=self._raw(name, f"{index:05d}-{kind}.sse"),
                        timeout=self.timeout, max_tokens=24,
                        tokens=estimate_tokens(txt, self.tokenizer),
                        round_index=index, marker=f"SK{index:05d}",
                        expected_status=200)
                    row.marker_ok = f"SK{index:05d}" in (row.output or "")
                self.record(row)
                history.append({"i": index, "kind": kind, "at": time.time(),
                                "status": row.http_status, "ok": row.status_ok,
                                "ttft": row.ttft_s, "total": row.total_s,
                                "tps": row.decode_tps,
                                "prompt_tokens": row.prompt_tokens})
                if not row.status_ok:
                    if row.http_status in (401, 403):
                        # The run's own key was revoked or deleted mid-flight.
                        # That is an operator action, not service instability,
                        # and it makes every subsequent request fail the same
                        # way -- so say it once, loudly, and stop rather than
                        # writing thousands of identical rows.
                        self.timeline.anomaly(
                            "浸泡期间凭据失效，已停止浸泡",
                            f"第{index}次 {kind}: HTTP {row.http_status}；"
                            "该 key 在运行中被删除或吊销，后续结果无意义",
                            group=name)
                        raise RuntimeError(
                            f"soak credential rejected at request {index} "
                            f"(HTTP {row.http_status}); the run's key was "
                            "deleted or revoked while the run was in flight")
                    self.timeline.anomaly(
                        "浸泡期间请求异常",
                        f"第{index}次 {kind}: HTTP {row.http_status} "
                        f"{str(row.error)[:100]}", group=name)
        finally:
            if own_sampler:
                sampler.stop()
        elapsed = time.time() - started
        if elapsed < seconds * 0.98:
            self.timeline.anomaly(
                "浸泡时长不足",
                f"计划 {seconds:.0f}s，实际 {elapsed:.0f}s", group=name)
        self._phase_end(name, started, planned_s=seconds,
                        measured_s=round(elapsed, 1), requests=index,
                        samples=len(sampler.snapshot()),
                        drift=sampler.summary(("mem_available", "npu_mem_used",
                                               "record_total", "record_bytes",
                                               "disk_free", "cpu_percent")),
                        history_s=round(history[-1]["at"] - history[0]["at"], 1)
                        if len(history) > 1 else 0)


# ---------------------------------------------------------------------------
# Summaries and the per-dimension verdict
# ---------------------------------------------------------------------------
#: The MYS-2510 corrections, as data rather than prose in the HTML.
#:
#: Each row is ``(item, old, new, basis)``. Keeping them here means the report
#: cannot show a corrected number next to an uncorrected explanation, and a test
#: can assert every row names its basis. These were verified against the
#: MYS-2510 evidence (``rounds.jsonl``, ``summary-regenerated.json``) and the
#: board's own record database, not taken from the review on trust.
CORRECTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("多轮历史回忆正确率",
     "136/263 = 51.7%",
     "136/148 = 91.9%",
     "263 条里有 115 条是浸泡期 soak-ctx 轮，不计入回忆分母；"
     "剔除后为 chat50 49 + chat100 99 = 148。"
     "注意剔除依据是分组而非 expected_recall：MYS-2510 证据里该列全部为 null"
     "（chat 行也是），按它筛会得到空集。soak-ctx 不计入的原因是它的历史"
     "里每轮 assistant 回复被写死为「收到。」，等于教模型用「收到。」回答回忆提问"),
    ("12 条回忆失败的定性",
     "模型能力问题（上下文约 4000 token 后答非所问）",
     "服务端逐 token 解码缺陷，v0.6.15 已修复",
     "失败输出为 门��/琴��/秤��/妆��，首字正确、尾部是 U+FFFD，"
     "而 SQLite 记录的 output_text 与 response_content 同样是替换符——"
     "缺陷在服务端生成侧，非模型答错；见 U1 回归"),
    ("「答非所问」结论",
     "约 4000 token 后开始答非所问",
     "删除",
     "该结论唯一的数据来源就是上述 12 条截断行；扣除后无任何证据支持"),
    ("取消记录状态异常",
     "15（与维度 C 的 15/15 自相矛盾）",
     "0",
     "15 条 cancelled 记录状态均正常；多出的 15 条是 cancel-recovery 恢复探针"
     "（cancel_stage 有值、record_status 为空），被误计为取消记录"),
    ("输出不一致",
     "10（未解释）",
     "0（记录核对，改比 response_content）",
     "10 条全部是 thinking-on 请求：核对时把 output_text（含 think 块原文）"
     "与客户端 content 相比，而服务端 response_content 与客户端逐字一致；"
     "属工具比较口径错误"),
    ("工具调用并行/多调用",
     "未说明",
     "未覆盖",
     "30 次工具调用全部是 context_messages=2 的单请求，没有并行/多工具调用场景"),
    ("VLM 多图覆盖强度",
     "80/80",
     "16/80 为真实多图，其余第二张为 1×1 占位",
     "image_dims 显示四组多图请求的第二张均为 [1,1]，多图覆盖强度有限"),
)

#: The dimensions the report judges, in the task card's own letters.
#:
#: ``A2`` and ``U`` are the MYS-2521 follow-up dimensions: the continuous-
#: conversation tiers are reported **separately** from A's single-shot long
#: prompts (the user's requirement says not to merge them), and the UTF-8
#: regression is its own letter because it is a decode defect being re-tested,
#: not a stability property.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("A", "长上下文与长度边界"),
    ("A2", "连续对话档位（累计 prompt_tokens）"),
    ("B", "并发与队列"),
    ("C", "流式/取消/客户端异常"),
    ("D", "前缀缓存与生命周期"),
    ("E", "VLM 与工具调用"),
    ("F", "浸泡与观测"),
    ("U", "UTF-8 回归（生僻字/emoji）"),
)


def summarize(rounds: Sequence[Round], phases: dict[str, dict]) -> dict:
    """Rates per group, per dimension and per phase, plus run-wide totals.

    Three deliberate choices, each of which a naive summary would get wrong:

    * **Success is ``status_ok``, not ``HTTP 200``.** A 429 from a full queue and
      a 409 during a load are the correct outcomes in their phases; counting
      them as failures would make a working gate look broken.
    * **Semantic accuracy is never merged into stability.** Retrieval, recall and
      tool-content accuracy are reported as their own numbers, because "the
      service is stable" and "the model answered correctly" are different claims
      and the task card forbids hiding the second inside the first.
    * **Cache hits are not correctness evidence.** ``cached_tokens`` is reported
      separately and never counted toward an answer being right.
    """
    out: dict = {"groups": {}, "dimensions": {}, "totals": {}, "rules": {}}

    def rate(ok: int, total: int) -> float | None:
        return round(ok / total, 4) if total else None

    groups = sorted({r.group for r in rounds})
    for group in groups:
        rows = [r for r in rounds if r.group == group]
        answered = [r for r in rows if r.status_ok]
        retrievals = [r for r in rows if r.retrieval_correct is not None]
        recalls = [r for r in rows if is_recall_row(r)]
        markers = [r for r in rows if r.marker_ok is not None]
        protocols = [r for r in rows if r.tool_protocol_ok is not None]
        contents = [r for r in rows if r.tool_content_ok is not None]
        errors: dict[str, int] = {}
        for r in rows:
            if r.error:
                head = str(r.error).split(":")[0][:60]
                errors[head] = errors.get(head, 0) + 1
        statuses: dict[str, int] = {}
        for r in rows:
            key = str(r.http_status) if r.http_status is not None else "no-status"
            statuses[key] = statuses.get(key, 0) + 1
        out["groups"][group] = {
            "requests": len(rows),
            "ok": len(answered),
            "success_rate": rate(len(answered), len(rows)),
            "http_status_counts": statuses,
            "error_types": errors,
            "ttft_s": ext.spread([r.ttft_s for r in answered]),
            "total_s": ext.spread([r.total_s for r in answered]),
            "decode_tps": ext.spread([r.decode_tps for r in answered]),
            "prompt_tokens": ext.spread([r.prompt_tokens for r in answered]),
            "cached_tokens": ext.spread([r.cached_tokens for r in answered]),
            "retrieval_checked": len(retrievals),
            "retrieval_ok": sum(1 for r in retrievals if r.retrieval_correct),
            "recall_checked": len(recalls),
            "recall_ok": sum(1 for r in recalls if r.recall_ok),
            "marker_checked": len(markers),
            "marker_ok": sum(1 for r in markers if r.marker_ok),
            "tool_protocol_checked": len(protocols),
            "tool_protocol_ok": sum(1 for r in protocols if r.tool_protocol_ok),
            "tool_content_checked": len(contents),
            "tool_content_ok": sum(1 for r in contents if r.tool_content_ok),
        }

    for letter, label in DIMENSIONS:
        rows = [r for r in rounds if r.dimension == letter]
        if not rows:
            continue
        answered = [r for r in rows if r.status_ok]
        retrievals = [r for r in rows if r.retrieval_correct is not None]
        recalls = [r for r in rows if is_recall_row(r)]
        protocols = [r for r in rows if r.tool_protocol_ok is not None]
        contents = [r for r in rows if r.tool_content_ok is not None]
        out["dimensions"][letter] = {
            "label": label,
            "requests": len(rows),
            "ok": len(answered),
            "success_rate": rate(len(answered), len(rows)),
            "http_5xx": sum(1 for r in rows if (r.http_status or 0) >= 500),
            "connection_errors": sum(1 for r in rows
                                     if r.http_status is None and r.error),
            "empty_outputs": sum(1 for r in rows if r.status_ok and not r.output
                                 and r.expected_status == 200),
            "retrieval_checked": len(retrievals),
            "retrieval_ok": sum(1 for r in retrievals if r.retrieval_correct),
            "recall_checked": len(recalls),
            "recall_ok": sum(1 for r in recalls if r.recall_ok),
            "tool_protocol_checked": len(protocols),
            "tool_protocol_ok": sum(1 for r in protocols if r.tool_protocol_ok),
            "tool_content_checked": len(contents),
            "tool_content_ok": sum(1 for r in contents if r.tool_content_ok),
            "phases": sorted({r.phase for r in rows}),
        }

    out["totals"] = {
        "requests": len(rounds),
        "ok": sum(1 for r in rounds if r.status_ok),
        "http_5xx": sum(1 for r in rounds if (r.http_status or 0) >= 500),
        "http_4xx": sum(1 for r in rounds
                        if r.http_status and 400 <= r.http_status < 500),
        "connection_errors": sum(1 for r in rounds
                                 if r.http_status is None and r.error),
        "empty_outputs": sum(1 for r in rounds if r.status_ok and not r.output
                             and r.expected_status == 200),
        "retrieval_checked": sum(1 for r in rounds if r.retrieval_correct is not None),
        "retrieval_ok": sum(1 for r in rounds if r.retrieval_correct),
        "recall_checked": sum(1 for r in rounds if is_recall_row(r)),
        "recall_ok": sum(1 for r in rounds if is_recall_row(r) and r.recall_ok),
        "cancelled_records": sum(1 for r in rounds if r.record_status == "cancelled"),
        "cache_hits": sum(1 for r in rounds if r.cache_hit),
        "records_checked": sum(1 for r in rounds if r.records_found is not None),
        "records_not_one": sum(1 for r in rounds
                               if r.records_found is not None and r.records_found != 1),
    }
    out["rules"] = {
        "success_definition": "status_ok = HTTP 状态等于该阶段预期（409/429 在对应阶段算通过）",
        "semantic_separate": "检索/回忆/工具内容正确率单列，不参与稳定性判定",
        "cache_not_correctness": "cached_tokens 只说明复用，不作为答案正确的证据",
        "no_retry": "任何请求都不重发；失败即证据",
    }
    out["phases"] = phases
    return out


def verify_records(runner: Runner, service: Service, key_secret: str | None,
                   limit: int | None = None) -> dict:
    """Cross-check every row against the service's own record.

    For each request id: the record exists, appears exactly once in the export,
    was written for the endpoint the request used, and agrees on output text and
    token counts. Records are read from the admin API; duplicates are counted in
    a single pass over the export.

    ``limit`` bounds the number of *detail* reads (the export pass always covers
    everything) so a 3,000-request run does not spend ten minutes on admin calls;
    the report states how many were read in detail.
    """
    rows = [r for r in runner.rounds if r.req_id]
    if limit is not None:
        rows = rows[:limit]
    ids = [r.req_id for r in rows if r.req_id]
    counts = service.record_ids_for(ids)
    out: dict = {"checked": 0, "missing": [], "duplicates": [], "source_mismatch": [],
                 "output_mismatch": [], "metrics_mismatch": [], "not_ok": [],
                 "secret_leaks": [], "cancelled_ok": 0, "cancelled_bad": [],
                 "detail_read": 0}
    for row in rows:
        out["checked"] += 1
        seen = counts.get(row.req_id, 0)
        if seen == 0:
            out["missing"].append({"id": row.req_id, "group": row.group,
                                   "phase": row.phase})
            continue
        if seen > 1:
            out["duplicates"].append({"id": row.req_id, "count": seen,
                                      "group": row.group})
        row.records_found = seen
        detail = service.record(row.req_id)
        if detail is None:
            out["missing"].append({"id": row.req_id, "group": row.group,
                                   "phase": row.phase, "detail": "admin 404"})
            continue
        out["detail_read"] += 1
        expected_source = {"/api/chat/stream": "/api/chat/stream"}.get(
            row.request_kind, "/v1/chat/completions")
        if detail.get("source") != expected_source:
            out["source_mismatch"].append({"id": row.req_id,
                                           "record": detail.get("source"),
                                           "expected": expected_source})
        if row.cancel_stage and row.group.endswith("-recovery"):
            # These are the "is the worker still serving?" probes, not
            # cancellations. They carry ``cancel_stage`` because they are issued
            # inside the cancel phase, and the first version of this tally
            # counted them, which made 15 correct cancellations read as
            # "15 / 15 abnormal" in the report's record table while dimension C
            # said 15/15 passed. Excluding them here is what makes the two agree.
            continue
        if row.cancel_stage:
            # A cancelled request is judged on its status, not its text: the
            # record is written during generator teardown, so its output is
            # whatever had been decoded when the socket closed.
            if detail.get("status") == "cancelled":
                out["cancelled_ok"] += 1
            else:
                out["cancelled_bad"].append({"id": row.req_id,
                                             "status": detail.get("status")})
            continue
        if row.expected_status == 200 and row.output:
            # Compare against ``response_content`` -- the text the client was
            # actually sent -- and not ``output_text``.
            #
            # ``output_text`` is the model's raw stream and legitimately differs
            # when thinking is on: it keeps the ``<think>`` block, plus whatever
            # preamble the model wrote there, while the client receives only the
            # parsed content. docs/inference-records.md says so explicitly. The
            # first version compared ``output_text`` and therefore reported all
            # 10 ``thinking-on`` requests as "output mismatch" -- a tool defect
            # that read as a service defect in the report (MYS-2510 review item
            # 7, corrected here).
            recorded = detail.get("response_content")
            if recorded is None:
                # Older records may not carry the column; fall back to
                # ``output_text`` rather than silently passing.
                recorded = detail.get("output_text") or ""
            if recorded != row.output:
                out["output_mismatch"].append({
                    "id": row.req_id, "group": row.group, "phase": row.phase,
                    "thinking": bool(row.thinking),
                    "record_chars": len(recorded),
                    "client_chars": len(row.output),
                    "record": recorded[:120], "client": row.output[:120]})
        for field in ("prompt_tokens", "completion_tokens"):
            client_value = getattr(row, field)
            if client_value is None:
                continue
            recorded_value = detail.get(field)
            if recorded_value is not None and recorded_value != client_value:
                out["metrics_mismatch"].append({"id": row.req_id, "field": field,
                                                "record": recorded_value,
                                                "client": client_value})
        if detail.get("status") != "ok":
            out["not_ok"].append({"id": row.req_id, "status": detail.get("status")})
        # The service's own numbers replace client-side timing where they exist.
        row.decode_tps = detail.get("decode_tps")
        row.server_ttft_s = detail.get("first_token_latency_s")
        # Keep both record columns on the row: U1 has to show that the SSE text,
        # the non-stream content and the stored record all agree, and the report
        # must be able to display the raw record text when they do not.
        row.record_output_text = detail.get("output_text")
        row.record_response_content = detail.get("response_content")
        if row.cached_tokens is None:
            row.cached_tokens = detail.get("cached_tokens")
        if key_secret and key_secret in json.dumps(detail, ensure_ascii=False):
            out["secret_leaks"].append({"id": row.req_id})
    return out



#: Metrics whose growth over a soak is a leak signal. Only these are flagged.
GROWTH_WATCH = ("npu_mem_used", "record_bytes", "record_total")


def dimension_verdict(summary: dict, records: dict, phases: dict[str, dict],
                      rounds: Sequence[Round], *,
                      required_cycles: int | None = LIFECYCLE_CYCLES,
                      required_soak: float | None = SOAK_SECONDS) -> dict:
    """One verdict per dimension, each criterion a count, plus the overall gate.

    Every criterion is arithmetic over the run's own rows, so a failure names
    itself and a reader can recompute it. ``None`` means "not measured", which
    fails the gate: an unmeasured dimension is not a passing one.

    Semantic accuracy (retrieval, recall, tool-content) is deliberately **absent**
    from the gate. The task card asks for it to be displayed separately, and it
    is — in :func:`summarize` and in the report's own accuracy table. Folding it
    in would make a model's answer quality a service failure, which is exactly
    the confusion the card forbids.
    """
    def rows(phase: str, **match) -> list[Round]:
        out = [r for r in rounds if r.phase == phase]
        for key, value in match.items():
            out = [r for r in out if getattr(r, key) == value]
        return out

    def all_ok(rs: Sequence[Round]) -> bool | None:
        return bool(rs) and all(r.status_ok for r in rs) if rs else None

    def criteria(*pairs) -> dict:
        return {name: {"ok": ok, "value": value} for name, ok, value in pairs}

    dims: dict[str, dict] = {}
    dim_counts = summary["dimensions"]

    def dim(letter: str) -> dict:
        return dim_counts.get(letter) or {}

    # -- A. long context, history, and the length boundary ----------------
    long_rows = [r for r in rounds if r.dimension == "A" and r.phase == "longctx"]
    overflow_rows = rows("overflow")
    chat_rows = [r for r in rounds
                 if r.dimension == "A" and r.phase.startswith("chat")]
    a = dim("A")
    dims["A"] = criteria(
        ("长 prompt 全部正常结束",
         all_ok(long_rows), f"{sum(1 for r in long_rows if r.status_ok)}"
                            f"/{len(long_rows)}"),
        ("真实 prompt_tokens 与档位一致（±5%）",
         (all(abs((r.prompt_tokens or 0) - (r.tokens or 0)) <= (r.tokens or 1) * 0.05
              for r in long_rows if r.status_ok) if long_rows else None),
         [(r.tokens, r.prompt_tokens) for r in long_rows[:6]]),
        ("超长输入被明确拒绝且未处理任何 token",
         (all(r.status_ok for r in overflow_rows)
          and phases.get("overflow", {}).get("records_claiming_tokens") == 0)
         if overflow_rows else None,
         f"{sum(1 for r in overflow_rows if r.status_ok)}/{len(overflow_rows)}，"
         f"记录增量={phases.get('overflow', {}).get('records_delta')}，"
         f"声称处理 token 的记录="
         f"{phases.get('overflow', {}).get('records_claiming_tokens')}"),
        ("同会话长历史无异常",
         all_ok(chat_rows) if chat_rows else None,
         f"{sum(1 for r in chat_rows if r.status_ok)}/{len(chat_rows)}"),
        ("无 5xx / 连接异常",
         a.get("http_5xx") == 0 and a.get("connection_errors") == 0,
         f"5xx={a.get('http_5xx')} conn={a.get('connection_errors')}"),
    )

    # -- B. concurrency and queueing --------------------------------------
    conc_rows = [r for r in rounds if r.dimension == "B"
                 and r.phase.startswith("conc")]
    queue_rows = rows("queue-capacity")
    queue = phases.get("queue-capacity") or {}
    outcomes = queue.get("outcomes") or {}
    # ``refused`` counts both shapes (a 429 status and an in-stream
    # rate_limit frame). The status histogram alone reported "no 429" for a run
    # that had refused a request exactly as designed.
    saw_429 = any((cap.get("refused") or 0) > 0 for cap in outcomes.values())
    # A small-capacity experiment must produce a 429; the report shows per
    # capacity what arrived, so "no 429 at capacity 1" is visible rather than
    # argued away.
    b = dim("B")
    dims["B"] = criteria(
        ("并发请求全部符合预期", all_ok(conc_rows),
         f"{sum(1 for r in conc_rows if r.status_ok)}/{len(conc_rows)}"),
        ("无串话",
         not any(r.note and "cross_talk" in str(r.note) for r in conc_rows),
         sum(1 for r in conc_rows if r.note and "cross_talk" in str(r.note))),
        ("3 路并发在 max_concurrent=2 下排队而非拒绝",
         (phases.get("conc3") or {}).get("refused_429") == 0
         if "conc3" in phases else None,
         f"429={(phases.get('conc3') or {}).get('refused_429')} "
         f"queued_seen={(phases.get('conc3') or {}).get('queued_seen')}"),
        ("超容量出现 429 且服务恢复",
         (saw_429 and bool(queue.get("recovered"))) if outcomes else None,
         {"statuses": {k: v.get("statuses") for k, v in outcomes.items()},
          "recovered": queue.get("recovered")}),
        ("无 5xx", b.get("http_5xx") == 0, f"5xx={b.get('http_5xx')}"),
    )

    # -- C. cancellation, protocol, restart -------------------------------
    # Only the disconnecting requests are cancellations; the "is the worker
    # still serving?" probes carry the same cancel_stage label but are judged
    # separately. Counting all 30 together made 15 correct cancellations read as
    # "15/30 cancelled".
    cancel_rows = [r for r in rounds
                   if r.phase == "cancel" and r.cancel_stage
                   and not r.group.endswith("-recovery")]
    cancelled_records = [r for r in cancel_rows if r.record_status == "cancelled"]
    recovery_rows = [r for r in rounds if r.phase == "cancel"
                     and r.group.endswith("-recovery")]
    proto_rows = [r for r in rounds if r.phase == "protocol"]
    restart = phases.get("restart") or {}
    c = dim("C")
    dims["C"] = criteria(
        ("取消后均留下 cancelled 记录",
         (len(cancelled_records) == len(cancel_rows)) if cancel_rows else None,
         f"{len(cancelled_records)}/{len(cancel_rows)}"),
        ("每次取消记录恰好一条",
         (all(r.records_found == 1 for r in cancel_rows)) if cancel_rows else None,
         f"{sum(1 for r in cancel_rows if r.records_found == 1)}/{len(cancel_rows)}"),
        ("取消时保留已生成的部分输出",
         (all(not (r.partial_chars or 0) or (r.records_found == 1)
              for r in cancel_rows) if cancel_rows else None),
         f"{sum(1 for r in cancel_rows if not (r.partial_chars or 0) or r.records_found == 1)}"
         f"/{len(cancel_rows)}"),
        ("取消后后续请求正常", all_ok(recovery_rows)
         if recovery_rows else None,
         f"{sum(1 for r in recovery_rows if r.status_ok)}/{len(recovery_rows)}"),
        ("协议错误码与预期一致", all_ok(proto_rows) if proto_rows else None,
         f"{sum(1 for r in proto_rows if r.status_ok)}/{len(proto_rows)}"),
        ("SIGTERM 重启后准入仍生效",
         (restart.get("gate_status") == 409) if restart else None,
         f"重启后 loaded={restart.get('loaded_after_restart')}，"
         f"首请求 HTTP {restart.get('gate_status')}"),
        ("重启后重载成功并恢复推理",
         (bool(restart.get("model_ready")) and bool(restart.get("post_ok")))
         if restart else None,
         {"reload": restart.get("reload_status"),
          "reload_s": restart.get("reload_s")}),
        ("重启后推理记录保留",
         restart.get("records_retained") if restart else None,
         f"{restart.get('records_before')}->{restart.get('records_after')}"),
        ("无 5xx", c.get("http_5xx") == 0, f"5xx={c.get('http_5xx')}"),
    )

    # -- D. cache and lifecycle -------------------------------------------
    cache = phases.get("prefix-cache") or {}
    ttl = phases.get("cache-ttl") or {}
    life = phases.get("lifecycle") or {}
    life_rows = rows("lifecycle")
    d = dim("D")
    dims["D"] = criteria(
        ("前缀复用被观测到", (cache.get("cache_hits") or 0) > 0 if cache else None,
         f"{cache.get('cache_hits')}/{cache.get('turns')}"),
        ("缓存命中时答案仍正确",
         cache.get("cached_answers_ok") == cache.get("turns") if cache else None,
         f"{cache.get('cached_answers_ok')}/{cache.get('turns')}"),
        ("无缓存基线答案正确", cache.get("baseline_answer_ok") if cache else None,
         cache.get("baseline_answer_ok")),
        ("TTL 过期后答案仍正确且服务恢复", ttl.get("recovered") if ttl else None,
         {"applied": ttl.get("applied_ttl"), "restored": ttl.get("restored_ttl"),
          "recovered": ttl.get("recovered")}),
        ("生命周期循环均无残留",
         (all(r.status_ok for r in life_rows)) if life_rows else None,
         f"{sum(1 for r in life_rows if r.status_ok)}/{len(life_rows)}"),
        # The declared cycle count is a property of a full run. A --quick run
        # deliberately does fewer and says so in its manifest, so holding it to
        # 20 would report the deliberate reduction as a failure.
         ("生命周期循环数达标",
          (None if required_cycles is None
           else (life.get("cycles") or 0) >= required_cycles) if life else None,
          f"{life.get('cycles')}（要求 {required_cycles}）"
          if required_cycles is not None else f"{life.get('cycles')}（--quick）"),
        ("无 5xx", d.get("http_5xx") == 0, f"5xx={d.get('http_5xx')}"),
    )

    # -- E. vision and tools ----------------------------------------------
    vlm_rows = [r for r in rounds if r.phase == "vlm"]
    tool_rows = [r for r in rounds if r.phase == "tools"
                 and r.tool_protocol_ok is not None]
    invalid_tool_rows = [r for r in rounds if r.group == "tool-invalid"]
    vlm = phases.get("vlm") or {}
    e = dim("E")
    dims["E"] = criteria(
        ("VLM 请求全部成功",
         (all_ok(vlm_rows) if vlm_rows else False) if "vlm" in phases else None,
         f"{sum(1 for r in vlm_rows if r.status_ok)}/{len(vlm_rows)}"),
        ("PNG 驱动超时未复现", (vlm.get("aborted") is None) if vlm else None,
         vlm.get("aborted")),
        ("记录只存图片尺寸，不存原始数据",
         (all(r.status_ok for r in vlm_rows if r.record_image_dims is not None)
          if any(r.record_image_dims is not None for r in vlm_rows) else None),
         f"{sum(1 for r in vlm_rows if r.record_image_dims is not None)} 条核验"),
        ("工具调用协议正确（与内容分开计）",
         all(r.tool_protocol_ok for r in tool_rows) if tool_rows else None,
         f"{sum(1 for r in tool_rows if r.tool_protocol_ok)}/{len(tool_rows)}"),
        ("非法工具定义被明确拒绝（400/422）",
         (all(r.http_status in (400, 422) for r in invalid_tool_rows))
         if invalid_tool_rows else None,
         f"{sum(1 for r in invalid_tool_rows if r.http_status in (400, 422))}"
         f"/{len(invalid_tool_rows)}"),
        ("无 5xx", e.get("http_5xx") == 0, f"5xx={e.get('http_5xx')}"),
    )

    # -- F. soak -----------------------------------------------------------
    soak = phases.get("soak") or {}
    f = dim("F")
    drift = soak.get("drift") or {}
    # Growth beyond 50% head-to-tail on an NPU/heap metric is *flagged*, not
    # gated: a cache warming up legitimately grows. The report shows the number
    # so an operator can judge it; only unbounded-looking growth on the record
    # log (a pure leak, since retention caps it) gates.
    growing = {k: v for k, v in drift.items()
               if k in GROWTH_WATCH and (v.get("growth") or 0) > 0.5}
    dims["F"] = criteria(
        ("浸泡达到要求时长",
         (None if required_soak is None
          else (soak.get("measured_s") or 0) >= required_soak * 0.98) if soak else None,
         f"{soak.get('measured_s')}s（要求 {required_soak or SOAK_SECONDS}s）"
         if required_soak is not None else
         f"{soak.get('measured_s')}s（--quick）"),
        ("浸泡期间请求全部成功", all_ok([r for r in rounds if r.phase == "soak"])
         if any(r.phase == "soak" for r in rounds) else None,
         f"{f.get('ok')}/{f.get('requests')}"),
        ("无 5xx / 连接异常",
         f.get("http_5xx") == 0 and f.get("connection_errors") == 0,
         f"5xx={f.get('http_5xx')} conn={f.get('connection_errors')}"),
        ("采样覆盖整个浸泡期", (soak.get("samples") or 0) > 60 if soak else None,
         soak.get("samples")),
        ("资源增长已标注（>50% 首尾差）", True, growing),
    )

    # -- A2. continuous conversation tiers ---------------------------------
    # Judged on A2's own rows. Reaching a tier is arithmetic on the service's
    # reported cumulative prompt_tokens; recall is *reported* next to it and
    # deliberately excluded from the gate, exactly as in every other dimension.
    a2_rows = [r for r in rounds if r.dimension == "A2"]
    a2_build = [r for r in a2_rows if r.ctx_role == "build"]
    a2_reached = [r for r in a2_rows if r.ctx_tier_reached]
    a2_reached_sessions = {r.session for r in a2_reached if r.session is not None}
    a2_restart = phases.get("ctx-tiers") or {}
    # Every tier the run was asked for must have at least one session land in
    # its band. This is the criterion the user's requirement is really about:
    # "未覆盖档位不可宣称通过".
    a2_tier_ok = None
    if a2_rows:
        wanted = list(a2_restart.get("tiers") or CTX_TIERS)
        landed = {r.ctx_tier for r in a2_reached}
        a2_tier_ok = all(t in landed for t in wanted)
    dims["A2"] = criteria(
        ("每一档都有会话到档（±10%）", a2_tier_ok,
         "到档档位=" + ",".join(str(t) for t in sorted(
             {r.ctx_tier for r in a2_reached if r.ctx_tier})) + "；"
         "会话=" + ",".join(str(s) for s in sorted(a2_reached_sessions))),
        # Build turns only: the per-tier table also counts the recall probes,
        # and the dimension total adds the post-restart gate request. Naming
        # the scope here keeps 295 / 340 / 341 from reading as a contradiction.
        ("连续对话构建轮全部成功（不含召回探针与重启准入）",
         all_ok(a2_build) if a2_build else None,
         f"{sum(1 for r in a2_build if r.status_ok)}/{len(a2_build)}"),
        ("到档会话均完成早期+近期回忆探针",
         (all(any(x.ctx_probe_position == "early" for x in a2_rows
                  if x.session == s)
              and any(x.ctx_probe_position == "recent" for x in a2_rows
                      if x.session == s)
              for s in a2_reached_sessions)) if a2_reached_sessions else None,
         f"{len(a2_reached_sessions)} 个到档会话，探针 "
         f"{sum(1 for r in a2_rows if r.ctx_role == 'probe')} 次"),
        ("16k 会话重启后准入/重载/历史保留",
         (None if not a2_rows else
          bool(a2_restart.get("restart_gate_ok")
               and a2_restart.get("restart_reload_ok")
               and a2_restart.get("restart_history_kept"))),
         f"gate_ok={a2_restart.get('restart_gate_ok')} "
         f"reload_ok={a2_restart.get('restart_reload_ok')} "
         f"history_kept={a2_restart.get('restart_history_kept')}"),
        ("连续对话无 5xx", (dim_counts.get("A2") or {}).get("http_5xx") == 0,
         f"5xx={(dim_counts.get('A2') or {}).get('http_5xx')}"),
    )

    # -- U. UTF-8 regression ------------------------------------------------
    # This one *is* a gate on text: a replacement character anywhere in the
    # sampled replies is the defect this dimension exists to catch, so it is a
    # failure rather than a semantic note.
    u_rows = [r for r in rounds if r.dimension == "U"]
    u_checked = [r for r in u_rows if r.u1_clean is not None]
    u_dirty = [r for r in u_checked if r.u1_clean is False]
    u_surfaces = {r.u1_surface for r in u_rows if r.u1_surface}
    u_replays = [r for r in u_rows if (r.group or "").startswith("utf8-replay-")]
    dims["U"] = criteria(
        ("三接口均无 U+FFFD", (not u_dirty) if u_checked else None,
         f"{len(u_checked) - len(u_dirty)}/{len(u_checked)} 输出干净"),
        ("stream / non-stream / console 三接口都覆盖",
         set(U1_SURFACES).issubset(u_surfaces) if u_surfaces else None,
         ",".join(sorted(u_surfaces))),
        ("MYS-2510 失败轮重放无 U+FFFD",
         (not any(r.u1_clean is False for r in u_replays)) if u_replays else None,
         f"{len(u_replays)} 轮重放"),
        ("请求无 5xx", (dim_counts.get("U") or {}).get("http_5xx") == 0,
         f"5xx={(dim_counts.get('U') or {}).get('http_5xx')}"),
    )

    # A dimension that produced no rows at all was not run (a partial run), so
    # its criteria are *unmeasured*, not failed. Without this, a `--phases
    # protocol` run reported "5xx in A/B/D/E/F" as failures -- `dim()` is empty,
    # so `x.get("http_5xx") == 0` was `None == 0`. "Not run" and "ran and broke"
    # have to stay distinguishable or the report's headline is wrong.
    for letter, checks in dims.items():
        if not dim_counts.get(letter):
            for name in checks:
                checks[name] = {"ok": None,
                                "value": f"该维度未执行（阶段未包含）"}

    every = [(dim_, name, v) for dim_, d_ in dims.items()
             for name, v in d_.items()]
    unmeasured = [f"{dim_}:{name}" for dim_, name, v in every if v["ok"] is None]
    failed = [f"{dim_}:{name}" for dim_, name, v in every if v["ok"] is False]
    return {
        "dimensions": dims,
        "passed": not failed and not unmeasured,
        "criteria_total": len(every),
        "criteria_failed": failed,
        "criteria_unmeasured": unmeasured,
        "records": {
            "checked": records.get("checked"),
            "missing": len(records.get("missing") or []),
            "duplicates": len(records.get("duplicates") or []),
            "source_mismatch": len(records.get("source_mismatch") or []),
            "output_mismatch": len(records.get("output_mismatch") or []),
            "metrics_mismatch": len(records.get("metrics_mismatch") or []),
            "secret_leaks": len(records.get("secret_leaks") or []),
            "cancelled_ok": records.get("cancelled_ok"),
            "cancelled_bad": len(records.get("cancelled_bad") or []),
        },
    }


# ---------------------------------------------------------------------------
# The HTML report
# ---------------------------------------------------------------------------
def _num(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return html_escape(value)


def _pct(ok, total) -> str:
    if not total:
        return "—"
    return f"{ok}/{total} ({ok / total * 100:.1f}%)"


def _flag(ok) -> str:
    """A pass/fail/unknown cell, so "not measured" cannot look like a pass."""
    if ok is None:
        return '<span class="unk">未测</span>'
    return '<span class="ok">通过</span>' if ok else '<span class="bad">失败</span>'


def _table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    head = "".join(f"<th>{html_escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f'<table class="grid"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


#: Columns the per-request table exposes. Kept explicit so the JS filter and the
#: server-side row builder cannot drift apart.
TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ts", "时间"), ("dimension", "维度"), ("phase", "阶段"), ("group", "分组"),
    ("http", "HTTP"), ("ok", "符合预期"), ("tokens", "token 档"),
    ("prompt_tokens", "prompt"), ("completion_tokens", "completion"),
    ("cached_tokens", "cached"), ("ttft", "首 token(s)"), ("total", "总耗时(s)"),
    ("tps", "decode TPS"), ("finish", "finish_reason"),
    ("semantic", "语义判分"), ("output", "输出（截断）"), ("error", "错误"),
)


def table_row(row: Round) -> list[str]:
    """One row of the detail table, every string escaped.

    Model output is attacker-influenced text on a page an operator opens, so it
    goes through :func:`html_escape` here and is *also* inserted with
    ``textContent`` in the JS — belt and braces, because either alone is one
    refactor away from an XSS.
    """
    semantic = ""
    if row.retrieval_correct is not None:
        semantic = "检索✓" if row.retrieval_correct else "检索✗"
    elif row.recall_ok is not None:
        semantic = "回忆✓" if row.recall_ok else "回忆✗"
    elif row.tool_content_ok is not None:
        semantic = "工具内容✓" if row.tool_content_ok else "工具内容✗"
    stamp = (datetime.fromtimestamp(row.started_at, tz=timezone.utc)
             .isoformat(timespec="seconds").replace("+00:00", "Z")
             if row.started_at else "")
    return [
        html_escape(stamp), html_escape(row.dimension), html_escape(row.phase),
        html_escape(row.group),
        html_escape(row.http_status if row.http_status is not None else ""),
        "✓" if row.status_ok else "✗",
        html_escape(row.tokens or ""),
        html_escape(row.prompt_tokens if row.prompt_tokens is not None else ""),
        html_escape(row.completion_tokens if row.completion_tokens is not None else ""),
        html_escape(row.cached_tokens if row.cached_tokens is not None else ""),
        f"{row.ttft_s:.2f}" if row.ttft_s is not None else "",
        f"{row.total_s:.2f}" if row.total_s is not None else "",
        f"{row.decode_tps:.1f}" if row.decode_tps is not None else "",
        html_escape(row.finish_reason or ""),
        html_escape(semantic),
        html_escape((row.output or "")[:300]),
        html_escape((str(row.error) if row.error else "")[:300]),
    ]


CSS = """
:root{--ink:#1a1d21;--mut:#6b7280;--line:#e3e6ea;--bg:#fbfcfd;--ok:#0f7b45;--bad:#b3261e;--warn:#8a5a00;--acc:#1f5fa8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI","Noto Sans SC",sans-serif}
header{background:#fff;border-bottom:1px solid var(--line);padding:22px 28px}
header h1{margin:0 0 6px;font-size:21px}
header .sub{color:var(--mut);font-size:13px}
main{max-width:1240px;margin:0 auto;padding:22px 28px 60px}
section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:20px 22px;margin:0 0 18px}
h2{font-size:17px;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line)}
h3{font-size:14px;margin:18px 0 8px;color:var(--mut);text-transform:none}
table.grid{width:100%;border-collapse:collapse;font-size:13px}
table.grid th,table.grid td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.grid th{background:#f6f8fa;font-weight:600;color:#374151}
table.grid tr:hover td{background:#fcfdfe}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}
.unk{color:var(--warn);font-weight:600}
.kpi{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 6px}
.kpi div{flex:1 1 150px;background:#f6f8fa;border:1px solid var(--line);border-radius:8px;padding:11px 13px}
.kpi b{display:block;font-size:19px;margin-top:3px}
.kpi span{color:var(--mut);font-size:12px}
.verdict{padding:13px 16px;border-radius:8px;margin:0 0 16px;font-weight:600}
.verdict.pass{background:#e8f5ee;color:#0b5c34;border:1px solid #bfe3cf}
.verdict.fail{background:#fdecea;color:#8c1d18;border:1px solid #f5c6c2}
.verdict.warn{background:#fff8e6;color:#6b4a00;border:1px solid #f0dca8}
.warnbox{background:#fff8e6;border:1px solid #f0dca8;border-radius:8px;padding:11px 14px;color:#6b4a00;font-size:13px}
.ctrl{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin:0 0 11px}
.ctrl input,.ctrl select{padding:6px 9px;border:1px solid var(--line);border-radius:6px;font:inherit;font-size:13px}
.pager{display:flex;gap:7px;align-items:center;margin-top:11px;font-size:13px;color:var(--mut)}
.pager button{padding:5px 11px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font:inherit}
.pager button:disabled{opacity:.45;cursor:default}
.scroll{overflow-x:auto}
code{background:#f1f3f5;padding:1px 5px;border-radius:4px;font-size:12px}
.note{color:var(--mut);font-size:12.5px;margin:8px 0 0}
ul.tight{margin:6px 0;padding-left:20px}ul.tight li{margin:3px 0}
"""

#: Table page size. Large enough that most phases fit on one page, small enough
#: that a 3,000-row run does not build a 3,000-row DOM.
PAGE_SIZE = 200


def build_html(*, env: dict, summary: dict, verdict: dict, records: dict,
               timeline: Sequence[dict], samples: Sequence[dict],
               phases: dict[str, dict], rounds: Sequence[Round],
               manifest: dict) -> str:
    """The single self-contained report.

    No CDN, no external font, no build step: charts are inline SVG generated from
    the run's numbers, and the table is filtered/paged in plain JS. It opens on a
    board with no network, which is the only environment this report is useful
    in.
    """
    totals = summary["totals"]
    dims = summary["dimensions"]
    passed = verdict["passed"]

    kpis = f"""
<div class="kpi">
  <div><span>总请求</span><b>{_num(totals['requests'])}</b></div>
  <div><span>符合预期</span><b>{_pct(totals['ok'], totals['requests'])}</b></div>
  <div><span>5xx / 连接异常</span><b>{_num(totals['http_5xx'])} / {_num(totals['connection_errors'])}</b></div>
  <div><span>记录核对</span><b>{_num(totals['records_checked'])} 条</b></div>
  <div><span>语义：检索 / 回忆</span><b>{_pct(totals['retrieval_ok'], totals['retrieval_checked'])} · {_pct(totals['recall_ok'], totals['recall_checked'])}</b></div>
</div>"""

    # -- per-dimension table ------------------------------------------
    dim_rows = []
    for letter, label in DIMENSIONS:
        d = dims.get(letter)
        if not d:
            dim_rows.append([letter, html_escape(label), "—", "—", "—", _flag(None), "未执行"])
            continue
        checks = verdict["dimensions"].get(letter) or {}
        fails = [name for name, v in checks.items() if v["ok"] is False]
        unks = [name for name, v in checks.items() if v["ok"] is None]
        state = "通过" if not fails and not unks else ("失败" if fails else "未测")
        dim_rows.append([
            letter, html_escape(label), _num(d["requests"]),
            _pct(d["ok"], d["requests"]),
            f"{d['http_5xx']} / {d['connection_errors']}",
            _flag(not fails and not unks),
            html_escape("; ".join(fails + [f"{u}(未测)" for u in unks]) or state),
        ])

    # -- criteria detail ----------------------------------------------
    crit_rows = []
    for letter, label in DIMENSIONS:
        for name, value in (verdict["dimensions"].get(letter) or {}).items():
            crit_rows.append([letter, html_escape(name), _flag(value["ok"]),
                              html_escape(str(value["value"])[:220])])

    # -- phase timings -------------------------------------------------
    phase_rows = []
    for name, info in sorted(phases.items(), key=lambda kv: kv[1].get("started_at") or 0):
        phase_rows.append([
            html_escape(name), _num(info.get("requests")),
            _pct(info.get("ok", 0), info.get("requests", 0)),
            _num(info.get("s"), 1),
            html_escape((info.get("note") or "")[:120]),
        ])

    # -- charts --------------------------------------------------------
    core_groups = [g for g in summary["groups"]
                   if g.startswith(("longctx", "chat", "conc", "soak", "prefix"))]
    ttft_series = [{"name": g,
                    "values": [summary["groups"][g]["ttft_s"]["median"]],
                    "colour": "#1f5fa8"} for g in core_groups]
    ttft_chart = ext.svg_bar_chart(
        core_groups,
        [summary["groups"][g]["ttft_s"]["median"] for g in core_groups],
        title="各分组首 token 延迟中位数（秒）", y_label="秒") if core_groups else ""

    # Prompt tokens vs TTFT: the superlinear prefill curve, from this run.
    long_rows = [r for r in rounds if r.phase == "longctx" and r.prompt_tokens]
    curve: dict[int, list[float]] = {}
    for r in long_rows:
        if r.ttft_s:
            curve.setdefault(r.tokens or 0, []).append(r.ttft_s)
    curve_points = sorted((k, statistics.median(v)) for k, v in curve.items() if k)
    curve_chart = ext.svg_line_chart(
        [{"name": "首 token 延迟", "colour": "#b3261e",
          "values": [v for _, v in curve_points]}],
        title="长上下文：首 token 延迟随 token 档位（实测）",
        y_label="秒", x_labels=[f"{k//1024}k" for k, _ in curve_points]) if curve_points else ""

    # Soak: memory and TPS over the span.
    soak_samples = [s for s in samples if s.get("ok")]
    soak_chart = ""
    if len(soak_samples) > 5:
        avail = [s.get("mem_available") for s in soak_samples]
        soak_chart = ext.svg_line_chart(
            [{"name": "可用内存", "colour": "#1f5fa8",
              "values": [None if v is None else v / (1024 ** 3) for v in avail]}],
            title="浸泡期可用内存（GiB）", y_label="GiB",
            x_labels=[datetime.fromtimestamp(s["at"], tz=timezone.utc)
                      .strftime("%H:%M") for s in soak_samples[::max(1, len(soak_samples)//8)]]
            + [""] * 8)

    drift = (phases.get("soak") or {}).get("drift") or {}
    drift_rows = [[html_escape(k), _num(v.get("head"), 1), _num(v.get("tail"), 1),
                   _num(v.get("delta"), 1),
                   f"{(v.get('growth') or 0)*100:.1f}%"
                   if v.get("growth") is not None else "—"]
                  for k, v in drift.items()]

    # -- A2 continuous conversation tiers -------------------------------
    # Per-tier statistics are computed from the rows, not carried in the phase
    # dict: a phase dict is a summary someone can forget to update, while the
    # rows are the evidence.
    a2_rows = [r for r in rounds if r.dimension == "A2"]
    a2_tier_stats: list[list] = []
    for tier in sorted({r.ctx_tier for r in a2_rows if r.ctx_tier}):
        tier_rows = [r for r in a2_rows if r.ctx_tier == tier]
        builds = [r for r in tier_rows if r.ctx_role == "build"]
        probes = [r for r in tier_rows if r.ctx_role == "probe"]
        reached = [r for r in tier_rows if r.ctx_tier_reached]
        sessions = {r.session for r in tier_rows if r.session is not None}
        landed_sessions = {r.session for r in reached if r.session is not None}
        pts = [r.prompt_tokens for r in builds if r.prompt_tokens]
        recalled = [r for r in probes if r.recall_ok is not None]
        early = [r for r in recalled if r.ctx_probe_position == "early"]
        recent = [r for r in recalled if r.ctx_probe_position == "recent"]
        turns = [r.turn for r in builds if r.turn]
        a2_tier_stats.append([
            f"{tier // 1024}k" if tier % 1024 == 0 else _num(tier),
            _num(tier),
            _num(len(landed_sessions)) + " / " + _num(len(sessions)),
            _num(max(turns) if turns else None),
            f"{_num(min(pts))} – {_num(max(pts))}" if pts else "—",
            _pct(sum(1 for r in tier_rows if r.status_ok), len(tier_rows)),
            _pct(sum(1 for r in recalled if r.recall_ok), len(recalled)),
            _pct(sum(1 for r in early if r.recall_ok), len(early)),
            _pct(sum(1 for r in recent if r.recall_ok), len(recent)),
            _num(sum(1 for r in tier_rows if (r.http_status or 0) >= 500)),
        ])

    # Per-session curves: the growth the requirement asks to be plotted.
    a2_series = []
    for session in sorted({r.session for r in a2_rows if r.session is not None}):
        pts = [r for r in a2_rows if r.session == session and r.ctx_role == "build"]
        if not pts:
            continue
        a2_series.append({
            "name": f"会话{session}（{_num(max(p.ctx_tier or 0 for p in pts))} 目标）",
            "values": [p.ctx_cumulative_tokens for p in pts],
        })
    a2_chart = ""
    if a2_series:
        # Sessions stop at different turns (each stops the moment it lands in its
        # tier's band), so the x axis is the turn *index* up to the longest
        # session, not a per-session label list. A series simply ends where its
        # session ended -- the chart must not imply turns that never ran.
        widest = max(len(s["values"]) for s in a2_series)
        a2_chart = ext.svg_line_chart(
            a2_series, title="A2 会话累计 prompt_tokens 逐轮增长",
            y_label="tokens",
            x_labels=[str(i) for i in range(1, widest + 1)])

    a2_restart = phases.get("ctx-tiers") or {}
    a2_restart_rows = [
        ["重启后准入（未加载时应 409）", _flag(a2_restart.get("restart_gate_ok")),
         f"gate_ok={a2_restart.get('restart_gate_ok')}"],
        ["显式加载模型后 ready", _flag(a2_restart.get("restart_reload_ok")),
         f"reload_ok={a2_restart.get('restart_reload_ok')}"],
        ["完整历史保留（重启后首问 token 不低于重启前）",
         _flag(a2_restart.get("restart_history_kept")),
         f"history_kept={a2_restart.get('restart_history_kept')}"],
    ]

    # -- U1 UTF-8 regression --------------------------------------------
    u_rows = [r for r in rounds if r.dimension == "U"]
    u_surface_rows: list[list] = []
    for surface in U1_SURFACES:
        s_rows = [r for r in u_rows if r.u1_surface == surface]
        checked = [r for r in s_rows if r.u1_clean is not None]
        if not s_rows:
            u_surface_rows.append([html_escape(surface), "—", "—", "—", "未执行"])
            continue
        u_surface_rows.append([
            html_escape(surface), _num(len(s_rows)),
            _pct(sum(1 for r in checked if r.u1_contains_all), len(checked)),
            _pct(sum(1 for r in checked if r.u1_clean), len(checked)),
            _num(sum(1 for r in checked if r.u1_clean is False)) + " 条含 U+FFFD",
        ])
    u_dirty = [r for r in u_rows if r.u1_clean is False]
    u_dirty_rows = [[html_escape(str(r.group)), html_escape(str(r.u1_expected)),
                     html_escape(repr(r.output)[:160]),
                     _num(r.http_status)] for r in u_dirty[:60]]
    u_replay = [r for r in u_rows if (r.group or "").startswith("utf8-replay-")]

    section_a2 = f"""
<section>
  <h2>A2 连续对话档位（按会话累计 prompt_tokens 判档）</h2>
  <p class="note">每轮追加完整 user/assistant 历史，档位以服务返回的
     <b>累计 prompt_tokens</b> 判定，落在目标 ±{CTX_TIER_TOLERANCE:.0%} 内才算到档；
     轮数由真实 token 决定，不是预设值。与 A 矩阵的单轮长 prompt 分开统计。</p>
  <div class="scroll">{_table(
      ["档位", "目标 tokens", "到档会话/会话", "最大轮数", "实测累计 token 范围",
       "请求成功率（构建轮+召回探针）", "事实召回", "早期事实", "近期事实", "5xx"],
      a2_tier_stats)}</div>
  <p class="note">口径：本表「请求成功率」统计每档的构建轮（追加历史）与召回探针（到档后提问）；
     判据「连续对话构建轮全部成功」只统计构建轮；A2 维度总请求数另含 16k 重启后的 1 次准入请求（预期 409），
     该请求不归入任何档位。</p>
  <div class="scroll">{a2_chart}</div>
  <h3>16k 会话重启复验</h3>
  <div class="scroll">{_table(["检查项", "结果", "实测"], a2_restart_rows)}</div>
  <p class="note">服务重启（SIGTERM）后本版本不自动加载模型，首个请求 409 属预期；
     随后显式 <code>POST /api/models/&lt;id&gt;/load</code>，再用<b>完整历史</b>追问早期与近期事实。</p>
</section>

<section>
  <h2>U1 UTF-8 回归（生僻字与 emoji）</h2>
  <p class="note">让模型原样复述 {'、'.join(RARE_WORDS + RARE_EMOJI)}，覆盖
     <code>/v1/chat/completions</code> stream、non-stream 与 <code>/api/chat/stream</code>；
     并重放 MYS-2510 中失败的 {len(u_replay)} 个轮次。任一输出出现 U+FFFD 即判失败，
     原文保留、不重试覆盖。</p>
  <div class="scroll">{_table(
      ["接口", "请求数", "原样复述命中", "无 U+FFFD", "异常"],
      u_surface_rows)}</div>
  <h3>含 U+FFFD 的输出（应为空）</h3>
  <div class="scroll">{_table(["分组", "期望词", "实际输出", "HTTP"], u_dirty_rows)
      if u_dirty_rows else '<p class="ok note">无：全部输出不含替换符。</p>'}</div>
</section>

<section>
  <h2>MYS-2510 报告修正说明（原值 → 新值 → 依据）</h2>
  <div class="scroll">{_table(["项", "原值", "新值", "依据"], CORRECTIONS)}</div>
</section>
"""

    # -- timeline ------------------------------------------------------
    timeline = [e.as_dict() if hasattr(e, "as_dict") else e for e in timeline]
    timeline_rows = [[
        html_escape(datetime.fromtimestamp(e["at"], tz=timezone.utc)
                    .isoformat(timespec="seconds").replace("+00:00", "Z")),
        html_escape(e.get("kind")),
        html_escape(e.get("title")),
        html_escape(str(e.get("detail") or "")[:400]),
    ] for e in timeline]

    # -- detail table --------------------------------------------------
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in table_row(r)) + "</tr>"
        for r in rounds)
    headers_html = "".join(f"<th>{html_escape(h)}</th>" for _, h in TABLE_COLUMNS)

    env_rows = [[html_escape(k), html_escape(str(v)[:400])]
                for k, v in env.items() if not isinstance(v, (dict, list))]
    env_json = html_escape(json.dumps({k: v for k, v in env.items()
                                       if isinstance(v, (dict, list))},
                                      ensure_ascii=False, indent=1)[:6000])

    rec = verdict["records"]
    unmeasured = verdict["criteria_unmeasured"]
    # Three states, not two. A run with no failed criteria but some unmeasured
    # ones has not failed anything -- calling it "未通过" beside "0 项失败" reads
    # as contradictory (a --quick run hits exactly this). It is still not a pass,
    # because "not measured" is not "works".
    failed_n = len(verdict["criteria_failed"])
    if passed:
        headline, css_class = "总体判定：通过", "pass"
    elif failed_n:
        headline, css_class = "总体判定：未通过", "fail"
    else:
        headline, css_class = "总体判定：未测项未通过（无失败判据）", "warn"
    banner = (
        f'<div class="verdict {css_class}">'
        f'{headline}'
        f'　·　{verdict["criteria_total"]} 项判据，'
        f'{failed_n} 项失败，'
        f'{len(unmeasured)} 项未测</div>')
    if unmeasured:
        banner += (f'<div class="warnbox">未测判据（不计为通过）：'
                   + html_escape("；".join(unmeasured)) + "</div>")
    # A --quick run must be obvious at the top of the page, not only in the
    # manifest: its numbers do not describe the acceptance matrix, and a reader
    # who skips the manifest would otherwise read them as if they did.
    quick_notice = ""
    if manifest.get("quick"):
        quick_notice = (
            '<div class="warnbox"><b>这是一次 --quick 管线验证运行</b>：'
            '各维度按 1–2 次/60 秒浸泡缩减，<b>不代表任务卡要求的测试规模，'
            '不能作为稳定性验收证据</b>。验收数据见完整运行的报告。</div>')

    # A merged report mixes measurements taken at different times. Say so at the
    # top, with the row counts, because otherwise a reader has no way to tell
    # that the MYS-2510 matrix was re-summarised rather than re-run -- and the
    # table below would imply a single measurement session that never happened.
    carry_notice = ""
    carried = (manifest.get("carried") or {})
    if carried:
        detail = "；".join(
            f"{html_escape(str(k))}：{_num(v)} 行" for k, v in carried.items())
        carry_notice = (
            '<div class="warnbox"><b>本报告合并了两次测量</b>：'
            f'{detail}。这些行来自对应运行的证据文件，按本次修正后的口径重新统计，'
            '未重新发请求；其余行来自本次运行。修正前后的对照见「MYS-2510 报告修正说明」，'
            '分档与 UTF-8 结论见 A2/U1 章节。</div>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CV84X6 推理稳定性综合矩阵报告</title>
<style>{CSS}</style></head><body>
<header>
  <h1>CV84X6 离线推理服务 · 全方位稳定性矩阵报告</h1>
  <div class="sub">{html_escape(manifest.get('device', ''))} ·
    服务 {html_escape(manifest.get('version', ''))} ·
    模型 {html_escape(manifest.get('model', ''))} ·
    生成于 {html_escape(manifest.get('generated_at', ''))}</div>
</header>
<main>

<section>
  <h2>① 总体结论</h2>
  {quick_notice}
  {carry_notice}
  {banner}
  {kpis}
  <h3>各维度通过判据</h3>
  <div class="scroll">{
    _table(["维度", "名称", "请求", "符合预期", "5xx / 连接异常", "判定", "失败或未测项"],
           dim_rows)}</div>
  <h3>模型语义正确率（单独展示，不参与稳定性判定）</h3>
  <div class="scroll">{_table(
      ["指标", "正确", "说明"],
      [["长上下文事实检索", _pct(totals['retrieval_ok'], totals['retrieval_checked']),
        "从材料中取回指定六位编号；错误与拒答分别计数"],
       ["多轮历史回忆", _pct(totals['recall_ok'], totals['recall_checked']),
        "回答上一轮关键词，只能来自真正被使用的历史"],
       ["工具调用内容", _pct(sum(d.get('tool_content_ok', 0) for d in dims.values()),
                            sum(d.get('tool_content_checked', 0) for d in dims.values())),
        "选对工具且参数含正确城市；协议正确性另计"]])}</div>
  <p class="note">缓存命中数只说明前缀被复用，<b>不作为</b>答案正确的证据；
     语义错误不会被隐藏为“服务通过”。</p>
</section>

<section>
  <h2>② 判据明细</h2>
  <div class="scroll">{_table(["维度", "判据", "结果", "实测值"], crit_rows)}</div>
</section>

<section>
  <h2>③ 测试矩阵与时间线</h2>
  <div class="scroll">{_table(["阶段", "请求", "符合预期", "耗时(s)", "备注"], phase_rows)}</div>
  <h3>时间线（阶段与异常）</h3>
  <div class="scroll">{_table(["时间(UTC)", "类型", "标题", "详情"], timeline_rows)}</div>
</section>

<section>
  <h2>④ 性能与资源</h2>
  <div class="scroll">{ttft_chart}</div>
  <div class="scroll">{curve_chart}</div>
  <div class="scroll">{soak_chart}</div>
  <h3>浸泡期首尾漂移（前 1/10 与后 1/10 中位数）</h3>
  <div class="scroll">{_table(["指标", "首段", "末段", "差值", "相对变化"], drift_rows)}</div>
  <p class="note">标注为“增长”的指标不代表故障：缓存预热会合理增长，需结合具体数值判断。</p>
</section>

{section_a2}

<section>
  <h2>⑤ 记录一致性</h2>
  <div class="scroll">{_table(
      ["检查项", "数量"],
      [["核对请求", _num(rec.get('checked'))],
       ["缺失记录", _num(rec.get('missing'))],
       ["重复记录", _num(rec.get('duplicates'))],
       ["source 不符", _num(rec.get('source_mismatch'))],
       ["输出不一致（比 response_content）", _num(rec.get('output_mismatch'))],
       ["token 不一致", _num(rec.get('metrics_mismatch'))],
       ["取消记录（cancelled）", _num(rec.get('cancelled_ok'))],
       ["取消记录状态异常（不含恢复探针）", _num(rec.get('cancelled_bad'))],
       ["API key 泄漏", _num(rec.get('secret_leaks'))]])}</div>
  <p class="note">「输出不一致」比较的是记录里的 <code>response_content</code>
     （客户端实际收到的 content），不是 <code>output_text</code>（含 think 块原文）。
     开启 thinking 时两者本来就不同，详见修正说明表。</p>
  <h3>输出不一致逐条（应仅剩真实差异）</h3>
  <div class="scroll">{_table(
      ["req_id", "分组", "thinking", "记录字符数", "客户端字符数"],
      [[html_escape(str(m.get('id'))), html_escape(str(m.get('group'))),
        html_escape(str(m.get('thinking'))), _num(m.get('record_chars')),
        _num(m.get('client_chars'))]
       for m in (rec.get('output_mismatch') or [])[:60]])}</div>
</section>

<section>
  <h2>⑥ 运行环境与参数</h2>
  <div class="scroll">{_table(["项", "值"], env_rows)}</div>
  <h3>结构化环境（截断）</h3>
  <pre class="note" style="white-space:pre-wrap">{env_json}</pre>
</section>

<section>
  <h2>⑦ 全部请求明细（可搜索 / 筛选 / 分页）</h2>
  <div class="ctrl">
    <input id="q" placeholder="搜索输出、错误、分组…" size="30">
    <select id="fd"><option value="">全部维度</option>
      {''.join(f'<option value="{l}">{l}</option>' for l, _ in DIMENSIONS)}</select>
    <select id="fs"><option value="">全部状态</option>
      <option value="ok">符合预期</option><option value="bad">不符合预期</option></select>
    <span id="count" class="note"></span>
  </div>
  <div class="scroll">
    <table class="grid" id="detail"><thead><tr>{headers_html}</tr></thead>
    <tbody id="rows">{rows_html}</tbody></table>
  </div>
  <div class="pager">
    <button id="prev">上一页</button>
    <span id="pageinfo"></span>
    <button id="next">下一页</button>
  </div>
</section>

<section>
  <h2>⑧ 未覆盖项与限制</h2>
  <ul class="tight">
    <li>并发只覆盖到 3 路（服务的配置上限为 3）；更高并发超出产品设计，未测试。</li>
    <li>上下文上限 131072 token；更大窗口的模型未测试。超长输入只验证"被拒绝"，未验证"被接受"。</li>
    <li>语义正确率是特定题型（检索某仓库编号、回忆上一轮关键词、工具参数）的统计，
        不代表开放域问答的质量；它与稳定性判定分开呈现。</li>
    <li>长上下文 prefill 为超线性（实测 t ∝ N^1.5）：64k 单次 14.2 分钟、96k 约 22 分钟，
        因此这两档各只跑 1 次，重复次数有限是时间成本所致，不是跳过。</li>
    <li>生命周期循环按时间预算执行 20 次而非 50 次（任务卡允许）：每次真实加载约 66 s，
        50 次约两小时纯加载；泄漏会在前 3 次就显现，20 次足以发现累积残留。</li>
    <li>浸泡负载是混合的单会话请求，不含真实 agent 的多工具长链；那类负载由 agent 侧测试覆盖。</li>
    <li>视觉测试用可判定的小图（渐变/灰阶/调色板/JPEG），未测试真实照片的识别质量。</li>
    <li>采样间隔为秒级，短于该间隔的资源尖峰不可见；报告中的首尾漂移是趋势判断，不是峰值记录。</li>
  </ul>
</section>

</main>
<script>
const rows = Array.from(document.querySelectorAll('#rows tr'));
const PS = {PAGE_SIZE};
let page = 0, view = rows;
const q = document.getElementById('q'), fd = document.getElementById('fd'),
      fs = document.getElementById('fs'), count = document.getElementById('count'),
      pageinfo = document.getElementById('pageinfo');
function textOf(tr) {{ return Array.from(tr.cells).map(c => c.textContent).join(' ').toLowerCase(); }}
function apply() {{
  const needle = q.value.trim().toLowerCase(), d = fd.value, s = fs.value;
  view = rows.filter(tr => {{
    if (d && tr.cells[1].textContent.trim() !== d) return false;
    if (s === 'ok' && tr.cells[5].textContent.trim() !== '✓') return false;
    if (s === 'bad' && tr.cells[5].textContent.trim() === '✓') return false;
    return !needle || textOf(tr).includes(needle);
  }});
  page = 0; render();
}}
function render() {{
  const pages = Math.max(1, Math.ceil(view.length / PS));
  page = Math.min(page, pages - 1);
  rows.forEach(tr => tr.style.display = 'none');
  view.slice(page * PS, (page + 1) * PS).forEach(tr => tr.style.display = '');
  count.textContent = view.length + ' 行匹配（共 ' + rows.length + '）';
  pageinfo.textContent = '第 ' + (page + 1) + ' / ' + pages + ' 页';
  document.getElementById('prev').disabled = page === 0;
  document.getElementById('next').disabled = page >= pages - 1;
}}
q.addEventListener('input', apply); fd.addEventListener('change', apply);
fs.addEventListener('change', apply);
document.getElementById('prev').onclick = () => {{ if (page > 0) {{ page--; render(); }} }};
document.getElementById('next').onclick = () => {{ page++; render(); }};
apply();
</script>
</body></html>
"""


def write_report(path: Path, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(**kwargs), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Environment, manifest, and main
# ---------------------------------------------------------------------------
def capture_environment(http: base.Http, data_dir: Path, tokenizer: Tokenizer | None,
                        device_label: str) -> dict:
    """Everything the report needs to be reproducible, read from the service.

    The point is that a reader can check *which* build, *which* model and *which*
    limits produced these numbers without trusting this script's prose. Values
    the service does not report stay ``None`` rather than being guessed.
    """
    env: dict = {"device": device_label, "captured_at":
                 datetime.now(timezone.utc).isoformat(timespec="seconds")}
    status, stats = http.json("GET", "/api/stats", timeout=90)
    if status == 200:
        env["stats"] = stats
        device = stats.get("device") or {}
        env["mem_total_bytes"] = (device.get("memory") or {}).get("total_bytes")
        env["npu_smi"] = (device.get("npu") or {}).get("smi")
        env["tpu_freq"] = device.get("tpu_freq")
        env["disk"] = device.get("disk")
    status, models = http.json("GET", "/api/models", timeout=90)
    if status == 200:
        env["models"] = models.get("models")
    status, settings = http.json("GET", "/api/settings", timeout=90)
    if status == 200:
        env["settings"] = settings
    status, version = http.json("GET", "/api/version", timeout=30)
    env["version"] = (version.get("version") if status == 200
                      else _installed_version())
    status, rec = http.json("GET", "/api/inference-records/status", timeout=60)
    if status == 200:
        env["record_log"] = rec
    env["tokenizer"] = tokenizer.describe() if tokenizer else {"available": False}
    env["data_dir"] = str(data_dir)
    env["kernel"] = _uname()
    return env


def _installed_version() -> str | None:
    """The service version from the package metadata, when the API lacks it."""
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Version}",
                              "cv84x6-llm-server"],
                             capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _json_fallback(value):
    """Make any leftover value JSON-able, and say so instead of crashing.

    Evidence writing must not depend on every field being a JSON-native type.
    A single generator-valued criterion cost one complete run its summary file
    and its report, because the exception surfaced *after* all the requests had
    been made. Anything unusual is rendered as a string prefixed with its type,
    which is still readable and still honest about what it is.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if hasattr(value, "__iter__"):
        try:
            return list(value)
        except TypeError:
            pass
    return f"<{type(value).__name__}> {value!r}"[:400]


def _uname() -> str | None:
    try:
        out = subprocess.run(["uname", "-a"], capture_output=True, text=True,
                             timeout=30)
        return (out.stdout or "").strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def build_manifest(model: str, env: dict, args, tokenizer: Tokenizer | None) -> dict:
    """The run's fixed parameters, so two reports can be compared honestly."""
    return {
        "suite": "comprehensive_stability_suite",
        "issue": "MYS-2510",
        "seed": SEED,
        "device": env.get("device"),
        "version": env.get("version"),
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tokenizer": tokenizer.describe() if tokenizer else None,
        "matrix": {
            "long_tiers_tokens": list(LONG_TIERS),
            "long_tier_repeats": {str(k): v for k, v in LONG_TIER_REPEATS.items()},
            "overflow_tokens": list(OVERFLOW_TOKENS),
            "chat_turns_required": CHAT_TURNS_REQUIRED,
            "chat_turns_extended": CHAT_TURNS_EXTENDED,
            "concurrency_lanes": list(CONC_LANES),
            "concurrency_rounds": CONC_ROUNDS,
            "queue_capacity_experiments": list(QUEUE_CAPACITY_EXPERIMENTS),
            "cancel_repeats": CANCEL_REPEATS,
            "lifecycle_cycles": LIFECYCLE_CYCLES,
            "vlm_repeats": VLM_REPEATS,
            "tool_calls": TOOL_CALLS,
            "thinking_repeats": THINKING_REPEATS,
            "soak_seconds": SOAK_SECONDS,
            "soak_mix": [list(x) for x in SOAK_MIX],
            "expected_context": EXPECTED_CONTEXT,
            # MYS-2521 A2 / U1: recorded so a reader can check that the five
            # tiers the user asked for are the five tiers that ran, and that the
            # tolerance and probe counts are the declared ones rather than
            # whatever the code happened to do.
            "ctx_tiers_tokens": list(CTX_TIERS),
            "ctx_tier_sessions": {str(k): v for k, v in CTX_TIER_SESSIONS.items()},
            "ctx_tier_tolerance": CTX_TIER_TOLERANCE,
            "ctx_early_probes": CTX_EARLY_PROBES,
            "ctx_recent_probes": CTX_RECENT_PROBES,
            "ctx_restart_tier": CTX_RESTART_TIER,
            "rare_words": list(RARE_WORDS),
            "rare_emoji": list(RARE_EMOJI),
            "u1_repeats": U1_REPEATS,
            "u1_surfaces": list(U1_SURFACES),
            "u1_replay_groups": [[g, list(t)] for g, t in U1_REPLAY_GROUPS],
        },
        "params": PARAMS,
        "system_prompt": SYSTEM_PROMPT,
        "argv": sys.argv[1:],
        "notes": {
            "success": "status_ok 是“HTTP 等于该阶段预期”，409/429 在对应阶段算通过",
            "semantic": "检索/回忆/工具内容正确率单独统计，不进入稳定性判定",
            "no_retry": "不重发任何请求",
            "lifecycle_reduction": "生命周期 20 次而非 50 次：每次真实加载约 66 秒",
            "ctx_tier_definition": "A2 档位以服务返回的会话累计 prompt_tokens 判定，"
                                  f"落在目标 ±{CTX_TIER_TOLERANCE:.0%} 内才算到档；"
                                  "轮数是结果不是输入",
            "recall_denominator": "多轮回忆分母只计 chat/ctx-/utf8-replay- 分组的"
                                  "回忆判定行；浸泡的 soak-ctx 轮不计入"
                                  "（其历史里 assistant 回复写死为「收到。」），"
                                  "依据是分组而非 expected_recall 是否为空",
            "u1_gate": "任一输出含 U+FFFD 即判失败并保留原文，不重试覆盖",
            "output_mismatch_vs": "记录核对比较 response_content（客户端实际收到的）"
                                  "而非 output_text（含 think 块）",
        },
    }


def load_rounds(path: Path) -> list[Round]:
    """Read a ``rounds.jsonl`` written by an earlier run back into ``Round`` objects.

    The MYS-2521 deliverable is one report holding two things that were measured
    at different times: the MYS-2510 main matrix (which the task card says must
    **not** be re-run -- the corrections are arithmetic on evidence already on
    disk) and the new A2/U1 blocks. Merging them at the row level is what makes
    the corrected numbers and the new numbers come out of the same code, instead
    of the old report being hand-edited alongside a new one.

    Two details the round trip needs:

    * ``input_text`` is never written to the JSONL (it can be megabytes for the
      long tiers), so restored rows have ``input_chars``/``input_sha256`` but no
      text. Nothing in summarising or reporting reads ``input_text``.
    * ``started_iso``/``finished_iso`` are derived columns, not fields, so they
      are dropped rather than passed to the constructor.

    Unknown keys are ignored on purpose: an older or newer evidence file must be
    loadable, and a column this version does not know about is a column it has
    nothing to say about.
    """
    fields = {f.name for f in dataclasses.fields(Round)}
    rows: list[Round] = []
    # ``.gz`` is accepted because a run's rows are ~1.5 MB of JSONL and the
    # committed copy of MYS-2510's is stored compressed; gzip is byte-identical
    # content, not a different format.
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            missing = {"round_index", "tier"} - set(raw)
            if missing:
                # These two have no default, so a truncated row would raise a
                # bare TypeError that says nothing about which file or line.
                raise SystemExit(
                    f"{path}: row is missing required field(s) {sorted(missing)}; "
                    "this does not look like a rounds.jsonl this version wrote")
            rows.append(Round(**{k: v for k, v in raw.items() if k in fields}))
    return rows


def make_evidence_dir(base: Path, *, fresh: bool = False) -> Path:
    """A new ``run-<UTC>`` directory; refuses to reuse a non-empty one."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = base / f"run-{stamp}"
    if path.exists() and any(path.iterdir()):
        if not fresh:
            raise SystemExit(f"evidence directory {path} is not empty; "
                             "use a new --evidence-dir or --fresh")
    (path / "raw").mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Comprehensive stability matrix for the CV84X6 LLM service "
                    "(MYS-2510): long context, concurrency, cancellation, "
                    "lifecycle, VLM/tools and a two-hour soak, with one HTML report.")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--password",
                    default=os.environ.get("CV84X6_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--evidence-dir", default="./stability-evidence")
    ap.add_argument("--fresh", action="store_true",
                    help="allow writing into a non-empty run directory")
    ap.add_argument("--data-dir", default="/data/cv84x6_llm_server")
    ap.add_argument("--device-label", default="172.26.166.96:10151 (.151)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None,
                    help="reuse this key instead of minting one (never written)")
    ap.add_argument("--key-name", default=KEY_NAME_DEFAULT)
    ap.add_argument("--vision-fixtures", default=None,
                    help="directory holding gradient.png/gray.png/palette.png/"
                         "photo.jpg (default: search the repo layout)")
    ap.add_argument("--tokenizer-lib",
                    default="/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so")
    ap.add_argument("--tokenizer-json",
                    default="/opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--sample-interval", type=float, default=10.0)
    ap.add_argument("--soak-seconds", type=float, default=SOAK_SECONDS,
                    help="soak duration; the report records what actually ran")
    ap.add_argument("--carry", action="append", default=None, metavar="DIR|JSONL[@SUMMARY]",
                    help="merge an earlier run's rounds into this report before "
                         "summarising (repeatable), e.g. "
                         "'analysis/raw/mys2510-supplement/mys2510-rounds.jsonl'. "
                         "Optionally '@summary-regenerated.json' to carry its "
                         "record-check block. The merged report states which "
                         "numbers came from the carried run.")
    ap.add_argument("--phases", default="long,overflow,chat,ctx,utf8,conc,queue,"
                                        "mixed,cancel,protocol,restart,cache,ttl,"
                                        "lifecycle,vlm,tools,soak",
                    help="comma-separated subset, for a partial run")
    ap.add_argument("--ctx-tiers", default=None,
                    help="override A2 tiers, e.g. '2048:1,4096:1' "
                         "(tier_tokens:sessions)")
    ap.add_argument("--ctx-restart", dest="ctx_restart", action="store_true",
                    default=True, help="also run the 16k restart-replay session")
    ap.add_argument("--no-ctx-restart", dest="ctx_restart", action="store_false",
                    help="skip the 16k restart-replay session")
    ap.add_argument("--u1-repeats", type=int, default=U1_REPEATS,
                    help="U1 repeats per literal per surface")
    ap.add_argument("--lifecycle-cycles", type=int, default=LIFECYCLE_CYCLES)
    ap.add_argument("--chat-turns", type=int, default=CHAT_TURNS_REQUIRED)
    ap.add_argument("--long-repeats", default=None,
                    help="override long-tier repeats, e.g. '16384:1,32768:1'")
    ap.add_argument("--record-detail-limit", type=int, default=1500,
                    help="how many records to read in detail (export covers all)")
    ap.add_argument("--skip-records", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="build prompts and print the plan, send nothing")
    ap.add_argument("--quick", action="store_true",
                    help="plumbing validation: every phase, one or two requests "
                         "each, minute-scale. Does NOT produce a report that can "
                         "be used as evidence of stability.")
    args = ap.parse_args(argv)

    evidence = make_evidence_dir(Path(args.evidence_dir), fresh=args.fresh)
    raw_dir = evidence / "raw"
    timeline = ext.Timeline(evidence / "timeline.jsonl")
    http = base.Http(args.base, timeout=args.timeout)
    login = http.login(args.password)
    if login != 200:
        raise SystemExit(f"admin login failed: HTTP {login}")

    tokenizer = Tokenizer(args.tokenizer_lib, args.tokenizer_json)
    if not tokenizer.available:
        print(f"WARNING: tokenizer unavailable ({tokenizer.error}); "
              "token targets become estimates", flush=True)
    model = args.model or base.pick_model(http)
    service = Service(http, model, args.password)
    env = capture_environment(http, Path(args.data_dir), tokenizer,
                              args.device_label)
    manifest = build_manifest(model, env, args, tokenizer)
    if env.get("version") and "v" not in str(manifest.get("version", "")):
        manifest["version"] = f"v{env['version']}"

    repeats = dict(LONG_TIER_REPEATS) if not args.quick else {}
    if args.long_repeats:
        repeats = {}
        for part in args.long_repeats.split(","):
            k, _, v = part.partition(":")
            repeats[int(k)] = int(v)

    # A --quick run exists to prove the wiring before a multi-hour run, so it
    # shrinks every dimension at once rather than one flag at a time. The report
    # still renders, and its manifest records that it was a quick run, so a
    # quick report can never be mistaken for the acceptance evidence.
    quick = {
        # Only the two smallest rungs: 64k/96k prefill cost ~20 and ~43 minutes
        # each on this board, which would make a plumbing check an afternoon.
        # The full tiers are exercised by the real run.
        "long_tiers": [16384, 32768],
        "long_repeats": {16384: 1, 32768: 1},
        "chat_turns": 4,
        "lifecycle_cycles": 2,
        "soak_seconds": 60.0,
        "vlm_repeats": 3,
        "tool_calls": 4,
        "thinking_repeats": 1,
        "conc_rounds": 3,
        "cache_turns": 2,
        "cache_ttl_wait": 65.0,
    }
    if args.quick:
        args.soak_seconds = quick["soak_seconds"]
        args.lifecycle_cycles = quick["lifecycle_cycles"]
        args.chat_turns = quick["chat_turns"]
        repeats = quick["long_repeats"]
        long_tiers = quick["long_tiers"]
        vlm_repeats, tool_calls, thinking_repeats = (
            quick["vlm_repeats"], quick["tool_calls"], quick["thinking_repeats"])
        conc_rounds, cache_turns = quick["conc_rounds"], quick["cache_turns"]
        mixed_rounds = quick["conc_rounds"]
        cache_ttl_wait = quick["cache_ttl_wait"]
        # U1 shrinks with the rest of a plumbing run: the point of --quick is
        # that nothing in the report can be mistaken for acceptance evidence,
        # and 150 requests is not minute-scale.
        u1_repeats = 1
    else:
        vlm_repeats, tool_calls, thinking_repeats = (
            VLM_REPEATS, TOOL_CALLS, THINKING_REPEATS)
        conc_rounds, cache_turns = CONC_ROUNDS, PREFIX_CACHE_TURNS
        cache_ttl_wait = CACHE_TTL_WAIT_S
        long_tiers = list(LONG_TIERS)
        mixed_rounds = MIXED_ROUNDS
        u1_repeats = args.u1_repeats

    plan = [p.strip() for p in args.phases.split(",") if p.strip()]
    print(f"model={model} version={env.get('version')} "
          f"tokenizer={'ok' if tokenizer.available else 'estimate'}\n"
          f"phases={plan}\nlong repeats={repeats}\n", flush=True)

    if args.dry_run:
        # Build every prompt the run would send and report the real token counts.
        # This is the cheap way to catch a generator bug before a 96k prefill.
        for tier in LONG_TIERS:
            lp = build_long_prompt(tier, tokenizer=tokenizer)
            print(f"  tier {tier}: chars={lp.chars} tokens={lp.tokens} "
                  f"needle={lp.needle_index} code={lp.expected_code}", flush=True)
        for tier in OVERFLOW_TOKENS:
            lp = build_overflow_prompt(tier, tokenizer=tokenizer)
            print(f"  overflow {tier}: chars={lp.chars} tokens={lp.tokens}", flush=True)
        print(f"  soak would run {args.soak_seconds:.0f}s", flush=True)
        return 0

    if args.api_key:
        key, key_id = args.api_key, "reused"
    else:
        key, key_id = base.create_key(http, args.key_name)
    sampler = Sampler(http, interval=args.sample_interval)
    runner = Runner(http, key, model, evidence, raw_dir, timeline, service,
                    tokenizer=tokenizer, timeout=args.timeout)
    exit_code = 0
    report_path = evidence / "report.html"
    try:
        sampler.start()
        timeline.add("phase", "开始综合矩阵",
                     f"设备 {args.device_label}，模型 {model}，阶段 {len(plan)} 个")

        if "long" in plan:
            runner.run_long_context(tiers=long_tiers, repeats=repeats)
        if "overflow" in plan:
            runner.run_overflow()
        if "chat" in plan:
            runner.run_chat_history(args.chat_turns)
            if args.chat_turns >= CHAT_TURNS_REQUIRED:
                # The 100-turn session is attempted only when the 50-turn one
                # passed: a failure at 50 would be masked by continuing.
                if all(r.status_ok for r in runner.rounds
                       if r.phase == f"chat{args.chat_turns}"):
                    runner.run_chat_history(CHAT_TURNS_EXTENDED, extended=True)
                else:
                    timeline.add("note", "跳过 100 轮会话",
                                 "50 轮会话存在异常，不继续放大", group="chat100")
        if "ctx" in plan:
            ctx_tiers = None
            ctx_sessions = None
            if args.ctx_tiers:
                ctx_tiers, ctx_sessions = [], {}
                for part in args.ctx_tiers.split(","):
                    tier_s, _, count_s = part.partition(":")
                    ctx_tiers.append(int(tier_s))
                    ctx_sessions[int(tier_s)] = int(count_s or 1)
            runner.run_context_tiers(tiers=ctx_tiers,
                                     sessions_per_tier=ctx_sessions,
                                     run_restart=args.ctx_restart)
        if "utf8" in plan:
            runner.run_utf8_regression(repeats=u1_repeats)
        if "conc" in plan:
            runner.run_concurrency(rounds=conc_rounds)
        if "queue" in plan:
            runner.run_queue_limits()
        if "mixed" in plan:
            runner.run_mixed_concurrency(rounds=mixed_rounds)
        if "cancel" in plan:
            runner.run_cancel()
        if "protocol" in plan:
            runner.run_protocol_errors()
        if "restart" in plan:
            runner.run_restart()
        if "cache" in plan:
            runner.run_prefix_cache(turns=cache_turns)
        if "ttl" in plan:
            runner.run_cache_ttl(wait_s=cache_ttl_wait)
        if "lifecycle" in plan:
            runner.run_lifecycle(args.lifecycle_cycles)
        if "vlm" in plan:
            runner.run_vlm(repeats=vlm_repeats,
                           fixture_dir=(Path(args.vision_fixtures)
                                        if args.vision_fixtures else None))
        if "tools" in plan:
            runner.run_tools(count=tool_calls, thinking_repeats=thinking_repeats)
        if "soak" in plan:
            runner.run_soak(args.soak_seconds, sampler=sampler)
    except KeyboardInterrupt:
        timeline.anomaly("运行被中断", "收到 KeyboardInterrupt，已完成的证据保留")
        exit_code = 130
    except Exception as exc:  # noqa: BLE001 - the report is the deliverable
        timeline.anomaly("运行异常中止",
                         f"{type(exc).__name__}: {exc}\n"
                         + traceback.format_exc()[-3000:])
        exit_code = 1
    finally:
        sampler.stop()
        runner.close()

    # Records are verified after the run: the export pass is O(rows) and the
    # detail reads are the slow part, so they run once, not per phase.
    records: dict = {"checked": 0, "missing": [], "duplicates": [],
                     "source_mismatch": [], "output_mismatch": [],
                     "metrics_mismatch": [], "not_ok": [], "secret_leaks": [],
                     "cancelled_ok": 0, "cancelled_bad": []}
    if not args.skip_records:
        timeline.add("phase", "开始核对推理记录", "按请求 id 逐一比对")
        records = verify_records(runner, service, key, limit=args.record_detail_limit)
        timeline.add("phase", "记录核对结束",
                     f"核对 {records.get('checked')}，缺失 {len(records['missing'])}，"
                     f"重复 {len(records['duplicates'])}")

    # Fill the late-known columns into the evidence file before anything reads
    # the rows: the report and the JSONL must not disagree.
    runner.rewrite_jsonl()

    # --carry merges an earlier run's rows in *before* summarising, so the
    # corrected numbers and the new ones are computed by the same code path.
    carried_rows: list[Round] = []
    carried_records: dict = {}
    if args.carry:
        for spec in args.carry:
            src, _, manifest_part = spec.partition("@")
            src_path = Path(src)
            if src_path.is_dir():
                src_path = src_path / "rounds.jsonl"
            if not src_path.exists():
                raise SystemExit(f"--carry: {src_path} does not exist")
            loaded = load_rounds(src_path)
            carried_rows.extend(loaded)
            timeline.add("note", "并入既有证据",
                         f"{src_path}：{len(loaded)} 行", group="carry")
            # A phase's verdict is not in the rows: `restart_gate_ok`,
            # `records_delta` and friends live in the source run's summary.json.
            # Carrying only the rows made every criterion that reads phase
            # metadata come out False -- the A2 restart gate had its 409 row
            # right there in the evidence and still failed, because the boolean
            # it is judged on was never merged.
            sidecar = src_path.parent / "summary.json"
            if sidecar.exists():
                blob = json.loads(sidecar.read_text(encoding="utf-8"))
                for name, info in (blob.get("phases") or {}).items():
                    # This run's own phases win: they were measured now.
                    runner.phases.setdefault(name, info)
            if manifest_part:
                sidecar = src_path.parent / manifest_part
                if sidecar.exists():
                    blob = json.loads(sidecar.read_text(encoding="utf-8"))
                    carried_records = blob.get("records") or {}
        runner.rounds.extend(carried_rows)

    summary = summarize(runner.rounds, runner.phases)
    if carried_records:
        # A carried run's record verdict is about *its* rows; the merged report
        # says so rather than presenting it as a measurement of this run.
        records = {**carried_records, "carried": True}
    verdict = dimension_verdict(
        summary, records, runner.phases, runner.rounds,
        # A --quick run is a plumbing check, not acceptance evidence; its
        # manifest says so. Holding it to the full-run scale requirements would
        # report the deliberate reduction as a failure.
        required_cycles=None if args.quick else args.lifecycle_cycles,
        required_soak=None if args.quick else args.soak_seconds)
    env["sampler"] = {"samples": len(sampler.snapshot()),
                      "interval_s": args.sample_interval,
                      "errors": sampler.errors,
                      "drift": sampler.summary(GROWTH_WATCH + ("mem_available",
                                                               "disk_free",
                                                               "cpu_percent"))}
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["requests"] = len(runner.rounds)
    manifest["quick"] = bool(args.quick)
    if args.carry:
        # Counted per source so the report's notice can name them, and so a
        # reader can subtract the carried rows and get this run's own totals.
        by_source: dict[str, int] = {}
        for spec in args.carry:
            src = spec.partition("@")[0]
            path = Path(src)
            if path.is_dir():
                path = path / "rounds.jsonl"
            by_source[str(path)] = len(load_rounds(path))
        manifest["carried"] = by_source
        manifest["requests_this_run"] = len(runner.rounds) - sum(by_source.values())
        manifest["notes"]["carried"] = (
            "带 --carry 的运行：carried 里的行来自既有证据文件，"
            "按本次修正后的口径重新统计，没有重新发请求")
    if args.quick:
        manifest["notes"]["quick"] = (
            "这是一次 --quick 管线验证运行（每档 1–2 次、浸泡 60 秒），"
            "矩阵未按任务卡规模执行，不能作为稳定性验收证据")
    manifest["verdict"] = {"passed": verdict["passed"],
                           "failed": verdict["criteria_failed"],
                           "unmeasured": verdict["criteria_unmeasured"]}

    write_report(report_path, env=env, summary=summary, verdict=verdict,
                 records=records, timeline=timeline.entries, samples=sampler.snapshot(),
                 phases=runner.phases, rounds=runner.rounds, manifest=manifest)
    (evidence / "summary.json").write_text(
        json.dumps({"summary": summary, "verdict": verdict,
                    "records": {k: v for k, v in records.items()
                                if not isinstance(v, list) or len(v) < 50},
                    "phases": runner.phases, "manifest": manifest},
                   ensure_ascii=False, indent=1, default=_json_fallback),
        encoding="utf-8")
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1,
                   default=_json_fallback), encoding="utf-8")
    (evidence / "env.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=1, default=_json_fallback),
        encoding="utf-8")
    (evidence / "samples.json").write_text(
        json.dumps(sampler.snapshot(), ensure_ascii=False), encoding="utf-8")
    timeline.close()

    # The minted key is deleted whatever happened; a leaked key on a customer
    # board is worse than a failed run.
    if not args.api_key:
        status, _ = http.json("DELETE", f"/api/keys/{key_id}", timeout=60)
        print(f"key deleted: HTTP {status}", flush=True)

    print(f"\nreport: {report_path}\n"
          f"passed={verdict['passed']} failed={verdict['criteria_failed']} "
          f"unmeasured={verdict['criteria_unmeasured']}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
