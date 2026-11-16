"""Board stability suite: fixed-length, self-verifying chats against a running service.

    python3 tools/board_stability_suite.py --evidence-dir ./evidence --restart

Written for MYS-2498, which asked for a *repeatable* answer to "is this build
still sane on the board after a long conversation?": 10 independent requests,
10 turns of one growing conversation, a concurrency bolt-on, and a normal
service restart -- with per-request evidence kept so a failure can be explained
instead of re-run.

Six rules shape the design:

* **Standard library only.** The board runs CPython 3.10 with no httpx, and a
  harness that needs installing is one that gets skipped. HTTP, SSE parsing,
  cookies, JSON and SQLite all come from the stdlib.
* **Every prompt is exactly the length it claims.** The tiers are 2..800
  *Unicode code points of the whole user message*, built by a seeded assembler
  whose filler is a natural word list rather than padding characters. The
  manifest records each text and its SHA-256, so "the 300 tier" is a byte-exact
  fact instead of an impression.
* **Every prompt has a mechanically checkable answer.** The core task is "count
  how often word W appears in the material below"; the expected number is
  computed from the same word list the model was shown, and the material is
  built so ``W`` can never occur inside another word (``帆布`` inside
  ``旧帆布包``) -- otherwise a correct count and a sloppy one are
  indistinguishable. The two shortest tiers cannot hold a word list at all, so
  they degrade to a literal instruction ("答0"), which is still exactly
  checkable.
* **Grading tolerates an echoed header, not a wrong answer.** Integer tokens
  that merely repeat the prompt's own round numbers are ignored; any other
  integer must be the expected count. See :func:`counting_answer_ok`.
* **A failure is evidence, not a reason to retry.** Every round is written to
  JSONL whether it succeeded or not, the raw SSE body is kept verbatim, and a
  failed request is never re-sent. A new run is a new evidence directory, and
  the suite refuses to write into a non-empty one.
* **The record log is checked from the outside.** Per request the suite reads
  back the service's own inference record (admin API *and* a direct read-only
  SQLite query) and compares message text, output text, token counts and
  context size. "Exactly one record per inference" is a counted fact here.

Groups (never mixed, never compared as an A/B -- the context group's prompt
tokens are larger by construction, so a latency difference between them means
nothing):

  ``nocxt``    10 independent requests: system + the one user message.
  ``cxt``      one logical session, 10 turns, each turn resending every earlier
               user/assistant message. From the 60 tier on a turn also plants a
               numbered fact ("本轮记录编号R4，关键词：竹篮。"); from the 300 tier
               on it also asks for an *earlier* turn's keyword, which can only
               be answered if the history is really being used.
  ``conc-*``   3 tiers x 3 simultaneous requests, each carrying its own letter
               marker it must echo -- the cross-talk check.
  ``restart``  one short request after a normal systemd restart.

The reference for what a record must contain is ``docs/inference-records.md``;
this tool verifies it from the outside, which is also what an operator would do
by hand in the console.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import random
import re
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
from typing import Sequence

# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

#: Generator seed. Changing it changes every prompt, so it is recorded in the
#: manifest; two runs are only comparable when it matches.
SEED = 24982496

#: Tier lengths: Unicode code points of the whole user message.
LENGTHS = [2, 10, 30, 60, 100, 200, 300, 400, 600, 800]

#: Tiers at or above this length additionally plant a numbered fact.
FACT_TIER = 60

#: Tiers at or above this length additionally ask for an earlier turn's fact.
RECALL_TIER = 300

#: Concurrency bolt-on: (group suffix, tier length).
CONCURRENCY_TIERS = (("short", 60), ("mid", 200), ("long", 600))
CONCURRENCY_PER_TIER = 3

#: Fixed system message for the core groups, so both see the same prefix and the
#: only difference between them is the history.
SYSTEM_PROMPT = "你是严谨的中文助手，只按用户的要求简短作答，不要解释。"

#: Fixed sampling parameters, identical for every request in the run.
#:
#: On this board's bmodel ``supports_sampling`` is **false**: ``lm_head`` emits a
#: single int32 with the argmax fused into the graph, so there is no distribution
#: left to sample from and ``temperature``/``top_p``/``top_k`` cannot change the
#: output (see ``NativeBackend.supports_sampling``). Decoding is therefore
#: already deterministic, which is exactly what makes "count the word" a usable
#: correctness check. The values are still sent explicitly so that
#: (a) every request in the run has an identical, recorded shape, and
#: (b) the same suite stays meaningful if it is pointed at a model whose
#:     sampling is real -- there they pin it to greedy.
#: ``env.json`` records the live ``supports_sampling`` so the report cannot claim
#: these parameters did something they did not.
PARAMS: dict = {
    "max_tokens": 128,
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 1,
    "repetition_penalty": 1.0,
    "enable_thinking": False,
}

#: Facts a turn can plant. Every entry is distinct, and none can contain another
#: entry, so "which keyword was planted in round N" has exactly one answer.
FACT_WORDS = (
    "青苹果", "河流", "灯塔", "竹篮", "石桥", "陶罐", "铁钉", "帆布", "铜铃", "木梳",
    "椅背", "枕套", "门环", "窗棂", "砚台", "书签", "茶盏", "鞋拔", "算盘", "风箱",
)

#: Material word pool by character length. Filler is drawn from here, so a
#: padded prompt reads like a word list ("木、石头、河流") -- not like padding.
#: The pools are deliberately much larger than any single prompt needs: with a
#: small pool a 600-character material becomes the same four words repeated,
#: which turns "count W" into "count a wall of identical text" and says nothing
#: about the service.
MATERIAL_WORDS: dict[int, tuple[str, ...]] = {
    1: ("木", "石", "水", "土", "火", "山", "田", "林", "草", "鱼",
        "鸟", "舟", "桥", "灯", "布", "纸", "铁", "铜", "绳", "瓦",
        "沙", "泥", "松", "竹", "藤", "麻", "棉", "锡", "银", "玉"),
    2: ("河流", "石头", "木箱", "竹篮", "陶罐", "铁钉", "帆布", "铜铃", "木梳", "藤椅",
        "陶碗", "铜锁", "纸伞", "麻绳", "瓷瓶", "木桨", "竹席", "铁锤", "灯罩", "石碑",
        "瓦片", "草帽", "竹筒", "木盆", "铁锅", "铜镜", "纸灯", "石磨", "陶壶", "木屐",
        "布鞋", "竹筏", "铁锹", "铜壶", "纸扇", "石阶", "木椅", "陶杯", "竹筷", "瓦罐"),
    3: ("红灯笼", "木栅栏", "石台阶", "竹篱笆", "旧铜锁", "麻布袋", "铁皮桶", "陶土罐",
        "木雕盒", "硬纸板", "青石板", "竹扁担", "铁纱窗", "陶制杯", "木门槛", "石臼窝",
        "竹蒸笼", "铁栏杆", "陶水缸", "木窗框", "石碾子", "竹箩筐", "铁皮箱", "陶灯座"),
    4: ("白瓷花瓶", "老式木箱", "粗麻绳结", "青铜烛台", "竹编提篮", "旧帆布包",
        "木制衣架", "铁艺灯架", "陶制花盆", "石雕栏杆", "竹节茶杯", "木质书架",
        "铁皮水壶", "铜制门牌", "藤编摇椅", "纸糊灯罩", "石砌水槽", "木刻印章"),
}

#: Literal tasks for the two tiers too short to hold a word list: (text, answer).
#: The answer is a fixed string, so "did the model follow the instruction at
#: all" is still a machine-checkable question.
LITERAL_PROMPTS = {2: ("答0", 0), 10: ("只回答这个数字：42", 42)}

KEY_NAME_DEFAULT = "MYS-2498-stability"


def chars(text: str) -> int:
    """Length in code points -- the unit every tier is defined in.

    ``len`` on a ``str`` is exactly the Unicode code point count, including the
    CJK punctuation the templates use. The suite never measures bytes.
    """
    return len(text)


def sha256(text: str) -> str:
    """SHA-256 of the UTF-8 bytes: the same recipe the manifest publishes."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Prompt:
    """One round's user message plus everything needed to grade it.

    ``expected_count`` is the integer the answer must reduce to;
    ``expected_recall`` is the keyword a *later* turn asks about (``None`` when
    this turn does not ask); ``plants_fact`` says whether this message carries a
    numbered fact other turns can recall. ``allowed_numbers`` are the integers a
    reply may repeat from the prompt itself without being counted as answers.
    """

    round_index: int
    length: int
    text: str
    expected_count: int | None
    expected_recall: str | None
    plants_fact: bool
    recall_round: int | None
    marker: str | None = None

    @property
    def text_sha256(self) -> str:
        return sha256(self.text)

    @property
    def allowed_numbers(self) -> set[int]:
        """Integers in the reply that are the prompt talking about itself.

        The prompt contains its own round number, and a recall clause names
        another round; a model that echoes "第7轮" is not answering 7. Those are
        the only exempt values -- everything else must be the count.
        """
        allowed = {self.round_index}
        if self.recall_round:
            allowed.add(self.recall_round)
        return allowed

    def manifest(self) -> dict:
        return {
            "round": self.round_index,
            "length": self.length,
            "chars": chars(self.text),
            "sha256": self.text_sha256,
            "text": self.text,
            "expected_count": self.expected_count,
            "expected_recall": self.expected_recall,
            "plants_fact": self.plants_fact,
            "recall_round": self.recall_round,
            "marker": self.marker,
            "allowed_numbers": sorted(self.allowed_numbers),
        }


def _split_lengths(rnd: random.Random, count: int, total: int) -> list[int]:
    """``count`` word lengths in 1..4 summing to ``total``.

    The caller guarantees ``count <= total <= 4 * count``, so the surplus
    ``total - count`` is at most ``3 * count`` and can be handed out one
    character at a time in a shuffled rotation -- which keeps the list from
    degenerating into one long word followed by a row of single characters.
    """
    if count <= 0 or not (count <= total <= 4 * count):
        raise ValueError(f"cannot split {total} over {count} words of 1..4 chars")
    sizes = [1] * count
    remaining = total - count
    order = list(range(count))
    rnd.shuffle(order)
    pos = 0
    while remaining > 0:
        i = order[pos % count]
        if sizes[i] < 4:
            sizes[i] += 1
            remaining -= 1
        pos += 1
        if pos > 8 * count:  # pragma: no cover - unreachable given the range check
            raise AssertionError("length split failed to converge")
    return sizes


def _compatible(candidate: str, banned: frozenset[str]) -> bool:
    """True when ``candidate`` is neither a substring of nor a superstring of a
    banned word.

    Containment is what makes a count ambiguous: with ``帆布`` as the target,
    the filler ``旧帆布包`` holds one more occurrence that a careful counter
    would (rightly) include and the expected number would miss.
    """
    return all(candidate not in b and b not in candidate for b in banned)


def _pick_words(rnd: random.Random, sizes: list[int],
                banned: frozenset[str]) -> list[str] | None:
    """One material word per requested length, avoiding ``banned`` and runs.

    Each character-length bucket is shuffled once and drawn from until it is
    exhausted, then reshuffled -- a 250-character material needs 50+ filler
    words and the 4-character pool holds fewer than that, so returning ``None``
    on exhaustion would make every long tier unsolvable. Reusing a word is
    harmless (the filler is never counted); clustering it is not, which is why
    the next draw is swapped when it would repeat the previous word.
    """
    bags: dict[int, list[str]] = {}
    chosen: list[str] = []
    for n in sizes:
        if n not in bags:
            pool = [w for w in MATERIAL_WORDS[n] if _compatible(w, banned)]
            if not pool:
                return None
            rnd.shuffle(pool)
            bags[n] = pool
        bag = bags[n]
        if not bag:
            pool = [w for w in MATERIAL_WORDS[n] if _compatible(w, banned)]
            rnd.shuffle(pool)
            bag = bags[n] = pool
        if chosen and bag[-1] == chosen[-1] and len(bag) > 1:
            bag[-1], bag[-2] = bag[-2], bag[-1]
        chosen.append(bag.pop())
    return chosen


def _fit_material(rnd: random.Random, target: str, occurrences: int, total: int,
                  banned: frozenset[str]) -> str | None:
    """A ``、``-joined list of exactly ``total`` chars holding ``target`` x N.

    With ``f`` filler words the joined length is ``sum(len) + (f + N - 1)``, and
    ``f`` words of 1..4 chars reach every sum in ``[f, 4f]``. That contiguous
    range is why an exact fit exists at every tier rather than only at the
    lengths that happen to line up: for each ``f`` in turn the required filler
    total either lands in the range or the next ``f`` is tried.
    The exact-fit search is bounded by ``total`` rather than by a fixed 160
    fillers: the MYS-2501 matrix adds 1000- and 1200-character tiers, and a
    1140-character material needs well over 160 one-to-four-character words.
    The bound is the number of fillers itself, so it cannot truncate a solvable
    tier; each candidate is a range test, not a build.
    """
    if total <= 0:
        return None
    for fillers in range(0, total + 1):
        separators = occurrences + fillers - 1
        filler_total = total - separators - occurrences * chars(target)
        if fillers == 0:
            if filler_total != 0:
                continue
            fill: list[str] = []
        else:
            if not (fillers <= filler_total <= 4 * fillers):
                continue
            fill = _pick_words(rnd, _split_lengths(rnd, fillers, filler_total),
                               banned | {target})
            if fill is None:
                continue
        words = list(fill)
        # The target copies are interleaved, not appended, so the count cannot be
        # answered by looking at one end of the string.
        for _ in range(occurrences):
            words.insert(rnd.randrange(len(words) + 1), target)
        joined = "、".join(words)
        if chars(joined) == total:
            return joined
    return None


def _fact_for(round_index: int) -> str:
    return FACT_WORDS[(round_index - 1) % len(FACT_WORDS)]


def build_prompt(length: int, round_index: int, *, seed: int = SEED,
                 marker: str | None = None,
                 lengths: Sequence[int] | None = None,
                 recall_target: str | None = None,
                 variant: int = 0,
                 allow_recall: bool = True) -> Prompt:
    """One user message of exactly ``length`` code points.

    The template varies with the tier because a 30-character message cannot
    carry a numbered fact *and* a word list. Which tiers carry facts is recorded
    on the result (``plants_fact``), and a recall clause only ever points at an
    earlier turn that actually planted one. The expected count never equals a
    round number in the phrase, so grading cannot confuse the two.

    ``lengths`` is the tier ladder this call belongs to; it defaults to the
    MYS-2498 matrix so every existing caller is unchanged. MYS-2501 passes its
    own ladder (which extends to 1000/1200) because the recall candidates are
    derived from it -- a round can only be asked about if its tier was long
    enough to plant a fact.

    The recall candidate list is capped at the ladder length. A caller may number
    rounds past the ladder (MYS-2501's no-context group cycles 12 tiers), and an
    uncapped ``range(1, round_index)`` would index off the end. The cap also
    states the real constraint: a recall clause can only point at a turn that
    exists in *this* ladder.

    ``allow_recall`` suppresses the recall clause for a request that is sent
    without its earlier turns. A no-context request occupying a ladder position
    past the last turn of any real conversation (MYS-2501's 1000 and 1200 tiers)
    would otherwise ask about a turn that does not exist -- an unanswerable
    question whose only effect is to invite an extra integer into the reply the
    count grader then has to reject.

    ``variant`` reseeds the material while keeping everything the tier promises
    (its exact length, its round number, its planted fact, its recall target).
    MYS-2501's no-context group needs it: its 1000 requests cycle through 12
    lengths, so without a variant they would be 12 distinct texts sent 83 times
    each -- and the service's prefix cache would answer most of them from a
    cached prefix, turning "1000 independent requests" into "12 requests and 988
    cache hits". Different material per request is what makes the prompt tokens
    real work. The context group passes ``variant=session_index`` for the same
    reason across sessions: 100 sessions sharing one text per turn would be one
    cached prefix, not 100 independent conversations.
    """
    ladder = list(LENGTHS if lengths is None else lengths)
    if length not in ladder:
        raise ValueError(f"unsupported tier {length}; expected one of {ladder}")
    rnd = random.Random((seed * 1_000_003) ^ (round_index * 7919) ^ length
                        ^ (variant * 2_654_435_761))

    if length in LITERAL_PROMPTS:
        text, answer = LITERAL_PROMPTS[length]
        if chars(text) != length:  # pragma: no cover - pinned by the unit tests
            raise AssertionError(f"literal prompt for tier {length} is {chars(text)} chars")
        return Prompt(round_index=round_index, length=length, text=text,
                      expected_count=answer, expected_recall=None,
                      plants_fact=False, recall_round=None)

    fact = _fact_for(round_index)
    # A recall clause only makes sense inside a growing conversation, so the
    # independent-request group gets the same text but is not graded on it.
    #
    # ``recall_target`` exists for the MYS-2501 context group. Its sessions are
    # ten turns long and each plants a fact, so asking about an arbitrary
    # earlier turn (the MYS-2498 behaviour, kept as the default) puts a
    # different keyword in every round and the report could only say "some
    # recalls worked". Pinning it to one fixed turn -- always the previous one,
    # which is the cheapest thing a broken history would still get right -- makes
    # "10/10 recalls correct" a statement about the same question being answered
    # ten times.
    recall_round = None
    if (allow_recall and length >= RECALL_TIER and round_index >= 2
            and marker is None):
        candidates = [i for i in range(1, min(round_index, len(ladder) + 1))
                      if ladder[i - 1] >= FACT_TIER]
        if recall_target is not None:
            pinned = round_index - 1
            recall_round = pinned if pinned in candidates else None
        else:
            recall_round = rnd.choice(candidates) if candidates else None
    plants_fact = length >= FACT_TIER and marker is None

    banned = frozenset({fact} | ({_fact_for(recall_round)} if recall_round else set()))
    target_pool = [w for w in FACT_WORDS if _compatible(w, banned)]
    target = rnd.choice(target_pool)

    head = f"第{round_index}轮。"
    fact_line = f"本轮记录编号R{round_index}，关键词：{fact}。" if plants_fact else ""
    # The reply format depends on whether a second question follows. Asking for
    # "只回答数字" and then adding "另外：第4轮的关键词是什么？" is self-contradictory,
    # and a model that obeys the first instruction (the correct reading) would be
    # graded as failing the second. Measured on the board: every recall round
    # answered "3" and nothing else. So when there is a recall clause the format
    # is spelled out for both answers instead.
    wants_recall = recall_round is not None
    if length < FACT_TIER:
        ask = f"数「{target}」出现几次，只答数字。"
    elif marker:
        ask = f"先原样输出标记{marker}，再数「{target}」出现几次，只答数字。"
    elif wants_recall:
        ask = f"数一数下面材料里「{target}」出现了几次。"
    else:
        ask = f"数一数下面材料里「{target}」出现了几次，只回答数字。"
    # A full stop before the clause, or the question runs straight on from the
    # last material word ("、白瓷花瓶另外：…") and reads as one garbled sentence.
    if wants_recall:
        recall_q = (f"。请分两行回答：第一行只写出现次数，"
                    f"第二行只写第{recall_round}轮的关键词。")
    else:
        recall_q = ""
    material_head = "材料："

    fixed = head + fact_line + ask + material_head + recall_q
    room = length - chars(fixed)
    # Vary the true count across rounds (1..3) but never let it collide with a
    # number the prompt already contains, so a correct answer is unambiguous.
    reserved = {round_index} | ({recall_round} if recall_round else set())
    desired = [n for n in (1 + (round_index % 3), 2, 3, 1) if n not in reserved]
    for occurrences in dict.fromkeys(desired):
        material = _fit_material(rnd, target, occurrences, room, banned | {target})
        if material is None:
            continue
        text = head + fact_line + ask + material_head + material + recall_q
        if chars(text) != length:  # pragma: no cover - guarded by the fit above
            continue
        return Prompt(round_index=round_index, length=length, text=text,
                      expected_count=occurrences,
                      expected_recall=_fact_for(recall_round) if recall_round else None,
                      plants_fact=plants_fact, recall_round=recall_round,
                      marker=marker)

    # No exact fit at any allowed count for *this* target. On a tight tier that
    # is a property of the target's length, not of the tier: with four characters
    # of room, a three-character target has no exact fit at all (one copy is 3,
    # two copies need 7), while a two-character target fits as "XY、<filler>".
    # Retrying with a different target is therefore the right fix rather than a
    # workaround -- the target is drawn at random from a compatible pool, so any
    # of them is an equally valid prompt.
    #
    # This is latent flakiness, not a hypothetical: a tier-30 prompt with a
    # four-digit round number leaves 4 characters of material, and 1 of the 20
    # fact words is three characters long. A numbered-to-forever caller (the
    # MYS-2501 readiness probe did exactly that) hit it on 5 of 200 rounds --
    # enough to abort a phase hours into a run.
    #
    # ``room`` is recomputed per alternative: it is
    # ``length - len(fixed)`` and ``fixed`` contains the target itself, so a
    # shorter target leaves more room. Reusing the original budget would silently
    # miss every alternative one character shorter than the first.
    for alternative in target_pool:
        if alternative == target:
            continue
        ask_alt = ask.replace(f"「{target}」", f"「{alternative}」")
        room_alt = length - chars(head + fact_line + ask_alt + material_head + recall_q)
        for occurrences in dict.fromkeys(desired):
            material = _fit_material(rnd, alternative, occurrences, room_alt,
                                     banned | {alternative})
            if material is None:
                continue
            text = head + fact_line + ask_alt + material_head + material + recall_q
            if chars(text) != length:  # pragma: no cover
                continue
            return Prompt(round_index=round_index, length=length, text=text,
                          expected_count=occurrences,
                          expected_recall=(_fact_for(recall_round)
                                           if recall_round else None),
                          plants_fact=plants_fact, recall_round=recall_round,
                          marker=marker)
    raise ValueError(
        f"tier {length} leaves no room for a material list ({room} chars, "
        f"round {round_index}, {len(target_pool) + 1} targets tried)")


def build_battery(seed: int = SEED, lengths: Sequence[int] | None = None,
                  recall_target: str | None = None) -> list[Prompt]:
    """The core rounds in tier order. Sent unchanged by both core groups."""
    ladder = list(LENGTHS if lengths is None else lengths)
    return [build_prompt(length, i + 1, seed=seed, lengths=ladder,
                         recall_target=recall_target)
            for i, length in enumerate(ladder)]


def build_concurrency_prompts(seed: int = SEED,
                              tiers: Sequence[tuple[str, int]] | None = None,
                              per_tier: int | None = None) -> list[Prompt]:
    """One prompt per concurrent request, each with a unique letter-only marker.

    Letters only: a digit in the marker would collide with the counted answer
    when the reply is graded.
    """
    tiers = list(CONCURRENCY_TIERS if tiers is None else tiers)
    per_tier = CONCURRENCY_PER_TIER if per_tier is None else per_tier
    if per_tier > 26:
        # The marker's second letter is what distinguishes requests inside one
        # tier; running past the alphabet would silently reuse a marker and turn
        # the cross-talk check into a false positive.
        raise ValueError(f"at most 26 requests per tier; got {per_tier}")
    out: list[Prompt] = []
    for tier_index, (_name, length) in enumerate(tiers):
        for k in range(per_tier):
            marker = f"KX{chr(65 + tier_index)}{chr(65 + k)}"
            out.append(build_prompt(length, 101 + tier_index * 10 + k,
                                    seed=seed, marker=marker))
    return out


# ---------------------------------------------------------------------------
# Conversation assembly
# ---------------------------------------------------------------------------
def context_messages(system: str | None, history: list[dict], user_text: str) -> list[dict]:
    """The message list for one turn: system, every earlier turn, this turn.

    The context group's point is that the history is *resent*, not referenced by
    an id, so this is a plain list build -- there is deliberately no server-side
    session state for it to depend on.
    """
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.extend(dict(m) for m in history)
    messages.append({"role": "user", "content": user_text})
    return messages


def append_turn(history: list[dict], user_text: str, assistant_text: str) -> list[dict]:
    """Grow the history by one complete exchange (user, then assistant)."""
    return history + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
def integers_in(text: str) -> list[int]:
    """Every integer token in a reply, in order."""
    return [int(m.group()) for m in re.finditer(r"-?\d+", text or "")]


def counting_answer_ok(prompt: Prompt, output: str) -> bool | None:
    """Did the reply answer the count, allowing it to echo the prompt's numbers?

    A model may answer "2" or "材料里出现了2次" or "第7轮，2次". The first two are
    straightforward; in the third, 7 is the prompt quoting itself. So: the
    expected count must appear, and every *other* integer must be one of the
    prompt's own numbers (``Prompt.allowed_numbers``). Two different counts in
    one reply is a failure, not a lucky match.
    """
    if prompt.expected_count is None:
        return None
    found = integers_in(output)
    if prompt.expected_count not in found:
        return False
    noise = set(found) - prompt.allowed_numbers - {prompt.expected_count}
    return not noise


def grade(prompt: Prompt, output: str, group: str) -> dict:
    """Mechanical checks for one answer.

    ``nocxt`` is graded on the count only: the recall clause is present in its
    text (both groups send identical new input, by design) but there is no
    history to answer it from, so scoring it as an error would blame the model
    for the suite's own construction.
    """
    out: dict = {"count_ok": counting_answer_ok(prompt, output),
                 "recall_ok": None, "marker_ok": None}
    if prompt.expected_recall is not None and group != "nocxt":
        out["recall_ok"] = prompt.expected_recall in (output or "")
    if prompt.marker is not None:
        out["marker_ok"] = prompt.marker in (output or "")
    return out


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------
@dataclass
class SseResult:
    """What one ``/v1/chat/completions`` stream actually delivered."""

    text: str = ""
    reasoning: str = ""
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    response_id: str | None = None
    done: bool = False
    chunks: int = 0
    malformed: int = 0
    errors: list = field(default_factory=list)

    def error_summary(self) -> str:
        return "; ".join(str(e)[:400] for e in self.errors)


def _delta_text(obj: dict) -> tuple[str, str]:
    """(content, reasoning_content) carried by one chunk, empty when none."""
    content = reasoning = ""
    for choice in obj.get("choices") or []:
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content += delta["content"]
        if delta.get("reasoning_content"):
            reasoning += delta["reasoning_content"]
    return content, reasoning


def parse_sse(raw: str) -> SseResult:
    """Parse an OpenAI-style SSE body.

    Tolerant by design: a stream cut mid-frame is exactly the failure this suite
    exists to observe, so a malformed line is counted and kept rather than
    raised. A missing ``[DONE]`` is a fact about the stream, not a parse error --
    the caller decides what it means.
    """
    res = SseResult()
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if payload == "[DONE]":
            res.done = True
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            res.malformed += 1
            continue
        res.chunks += 1
        if obj.get("id") and res.response_id is None:
            res.response_id = obj["id"]
        if obj.get("error") or obj.get("detail"):
            res.errors.append(obj.get("error") or obj.get("detail"))
            continue
        if obj.get("usage"):
            res.usage = obj["usage"]
        for choice in obj.get("choices") or []:
            if choice.get("finish_reason"):
                res.finish_reason = choice["finish_reason"]
        content, reasoning = _delta_text(obj)
        res.text += content
        res.reasoning += reasoning
    return res


def usage_tokens(usage: dict) -> tuple[int, int, int]:
    """(prompt, completion, cached) from an OpenAI usage block; missing reads 0."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    return prompt, completion, cached


def request_id_of(response_id: str | None) -> str | None:
    """The record id from a response id: ``chatcmpl-<req_id>`` -> ``<req_id>``."""
    if not response_id:
        return None
    return response_id[len("chatcmpl-"):] if response_id.startswith("chatcmpl-") else response_id


# ---------------------------------------------------------------------------
# HTTP (stdlib)
# ---------------------------------------------------------------------------
class Http:
    """Minimal urllib client with a cookie jar for the admin session.

    One instance per thread when concurrency matters: a ``CookieJar`` is not
    written for parallel use, and the concurrent requests authenticate with an
    API key anyway, so they need no session at all.
    """

    def __init__(self, base: str, timeout: float = 1800.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def url(self, path: str) -> str:
        return self.base + (path if path.startswith("/") else "/" + path)

    def open(self, req: urllib.request.Request, timeout: float | None = None):
        return self.opener.open(req, timeout=timeout or self.timeout)

    def request(self, method: str, path: str, payload=None, headers: dict | None = None,
                timeout: float | None = None) -> tuple[int, bytes]:
        data = None
        hdrs = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = urllib.request.Request(self.url(path), data=data, headers=hdrs, method=method)
        try:
            with self.open(req, timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def json(self, method: str, path: str, payload=None, headers: dict | None = None,
             timeout: float | None = None) -> tuple[int, dict]:
        status, body = self.request(method, path, payload, headers, timeout)
        try:
            return status, json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status, {"_raw": body.decode("utf-8", "replace")[:2000]}

    def login(self, password: str) -> int:
        status, _ = self.json("POST", "/api/login", {"password": password}, timeout=60)
        return status


# ---------------------------------------------------------------------------
# One round
# ---------------------------------------------------------------------------
@dataclass
class Round:
    """Everything one request produced -- the row that goes into the JSONL.

    Unknowns stay ``None`` rather than 0, so a failed request is never silently
    averaged in as a fast one. ``input_text`` is the message the request sent; it
    is dropped from the JSONL (the manifest carries every text) but kept in
    memory so the record check can compare it byte for byte.
    """

    group: str
    round_index: int
    tier: int
    input_text: str = ""
    input_chars: int = 0
    input_sha256: str = ""
    context_messages: int = 0
    req_id: str | None = None
    http_status: int | None = None
    started_at: float | None = None
    finished_at: float | None = None
    ttft_s: float | None = None
    total_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    decode_tps: float | None = None
    server_ttft_s: float | None = None
    finish_reason: str | None = None
    stream_done: bool | None = None
    output: str = ""
    error: str | None = None
    expected_count: int | None = None
    expected_recall: str | None = None
    marker: str | None = None
    count_ok: bool | None = None
    recall_ok: bool | None = None
    marker_ok: bool | None = None
    cross_talk: bool | None = None

    def iso(self, key: str) -> str | None:
        value = getattr(self, key)
        return (datetime.fromtimestamp(value, tz=timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z")
                if value else None)

    def as_row(self) -> dict:
        row = asdict(self)
        row.pop("input_text", None)
        row["started_iso"] = self.iso("started_at")
        row["finished_iso"] = self.iso("finished_at")
        return row


def new_round(group: str, prompt: Prompt, messages: list[dict]) -> Round:
    return Round(group=group, round_index=prompt.round_index, tier=prompt.length,
                 input_text=prompt.text, input_chars=chars(prompt.text),
                 input_sha256=sha256(prompt.text), context_messages=len(messages),
                 expected_count=prompt.expected_count,
                 expected_recall=prompt.expected_recall, marker=prompt.marker)


def chat_once(http: Http, key: str, model: str, prompt: Prompt, group: str,
              messages: list[dict], raw_dir: Path, timeout: float = 1800.0) -> Round:
    """POST one streaming completion and capture it, failures included.

    Nothing here retries: re-sending would hide exactly the failure the run is
    supposed to document. Every exception becomes ``error`` on the row, and the
    raw body is written before it is parsed, so the evidence survives even a
    parser bug.
    """
    row = new_round(group, prompt, messages)
    payload = {"model": model, "messages": messages, "stream": True,
               "seed": SEED, **PARAMS}
    req = urllib.request.Request(
        http.url("/v1/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream",
                 "Authorization": f"Bearer {key}",
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
                        content, reasoning = _delta_text(json.loads(decoded[5:].strip()))
                    except (json.JSONDecodeError, ValueError):
                        content = reasoning = ""
                    # The first chunk carries an *empty* role delta; TTFT is the
                    # first chunk that actually carries a token.
                    if content or reasoning:
                        first_token_at = time.time()
            row.finished_at = time.time()
    except urllib.error.HTTPError as exc:
        row.http_status = exc.code
        row.finished_at = time.time()
        row.error = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:2000]}"
    except Exception as exc:  # noqa: BLE001 - every failure is a row, not a crash
        row.finished_at = time.time()
        row.error = f"{type(exc).__name__}: {exc}"

    raw = "".join(collected)
    (raw_dir / f"{group}-{prompt.round_index}.sse").write_text(raw, encoding="utf-8")
    parsed = parse_sse(raw)
    row.req_id = request_id_of(parsed.response_id)
    row.output = parsed.text
    row.finish_reason = parsed.finish_reason
    row.stream_done = parsed.done
    prompt_tokens, completion_tokens, cached = usage_tokens(parsed.usage)
    row.prompt_tokens = prompt_tokens or None
    row.completion_tokens = completion_tokens or None
    row.cached_tokens = cached if parsed.usage else None
    if row.error is None and parsed.errors:
        row.error = f"stream error: {parsed.error_summary()}"
    if row.error is None and not parsed.text:
        row.error = "empty output"
    if row.error is None and not parsed.done:
        row.error = "stream ended without [DONE]"
    if row.finished_at and row.started_at:
        row.total_s = round(row.finished_at - row.started_at, 6)
        if first_token_at:
            row.ttft_s = round(first_token_at - row.started_at, 6)
    graded = grade(prompt, parsed.text, group)
    row.count_ok = graded["count_ok"]
    row.recall_ok = graded["recall_ok"]
    row.marker_ok = graded["marker_ok"]
    return row


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
def run_concurrent(base: str, key: str, model: str, prompt: Prompt, group: str,
                   raw_dir: Path, timeout: float = 1800.0) -> Round:
    """Thread entry point: one independent request with its own HTTP client."""
    client = Http(base, timeout=timeout)
    return chat_once(client, key, model, prompt, group,
                     [{"role": "user", "content": prompt.text}], raw_dir, timeout)


def run_concurrency_tier(base: str, key: str, model: str, name: str, length: int,
                         raw_dir: Path, timeout: float = 1800.0) -> list[Round]:
    """Fire one tier's requests simultaneously and mark cross-talk.

    Cross-talk is checked across the whole batch: a reply carrying another
    request's marker came out of the wrong scheduler slot, which no per-request
    assertion would catch.
    """
    group = f"conc-{name}"
    prompts = [p for p in build_concurrency_prompts() if p.length == length]
    results: list[Round] = []
    lock = threading.Lock()
    start = time.time()

    def work(p: Prompt) -> None:
        try:
            row = run_concurrent(base, key, model, p, group, raw_dir, timeout)
        except Exception as exc:  # noqa: BLE001 - a thread must not die silently
            row = new_round(group, p, [{"role": "user", "content": p.text}])
            row.error = f"{type(exc).__name__}: {exc}"
        with lock:
            results.append(row)

    threads = [threading.Thread(target=work, args=(p,)) for p in prompts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start
    markers = {p.marker: p for p in prompts}
    for row in results:
        foreign = [m for m in markers if m != row.marker and m in (row.output or "")]
        row.cross_talk = bool(foreign)
        if foreign:
            row.error = row.error or f"cross-talk: reply carried {','.join(foreign)}"
    print(f"  {group}: {len(results)} requests in {elapsed:.1f}s", flush=True)
    return results


# ---------------------------------------------------------------------------
# The service's own records
# ---------------------------------------------------------------------------
def fetch_records(http: Http, rounds: list[Round]) -> tuple[dict[str, dict], list[str]]:
    """Per-request record detail, plus the ids that have no record at all."""
    details: dict[str, dict] = {}
    missing: list[str] = []
    for row in rounds:
        if not row.req_id:
            missing.append(f"{row.group}-{row.round_index}")
            continue
        status, body = http.json("GET", f"/api/inference-records/{row.req_id}", timeout=60)
        if status == 200:
            details[row.req_id] = body
        else:
            missing.append(row.req_id)
    return details, missing


def export_records(http: Http, out_path: Path) -> tuple[dict[str, int], int]:
    """Download the NDJSON export, counting occurrences of every record id.

    Streamed line by line into the file: the export holds each row's full
    conversation and this board has 2.6 GB of RAM, so only the per-id counts are
    retained in memory.
    """
    counts: dict[str, int] = {}
    lines = 0
    req = urllib.request.Request(http.url("/api/inference-records-export"),
                                headers={"Accept": "application/x-ndjson"})
    try:
        with http.open(req, 600) as resp, out_path.open("w", encoding="utf-8") as fh:
            for raw in resp:
                line = raw.decode("utf-8", "replace")
                fh.write(line)
                if not line.strip():
                    continue
                lines += 1
                try:
                    rid = json.loads(line).get("id")
                except json.JSONDecodeError:
                    continue
                if rid:
                    counts[rid] = counts.get(rid, 0) + 1
    except (urllib.error.HTTPError, OSError) as exc:
        out_path.write_text("", encoding="utf-8")
        print(f"  export failed: {type(exc).__name__}: {exc}", flush=True)
    return counts, lines


def verify_records(rounds: list[Round], details: dict[str, dict],
                   export_counts: dict[str, int], key_secret: str | None) -> dict:
    """Compare every request with the record the service wrote for it.

    Per request: the record exists, appears exactly once in the export, was
    written for ``/v1/chat/completions``, carries the same message text and the
    same output, and agrees on token counts and message count. A missing or
    doubled record is reported by id, never smoothed into a rate.
    """
    out: dict = {
        "checked": 0, "missing": [], "missing_from_export": [], "duplicates": [],
        "source_mismatch": [], "not_ok_rows": [], "input_mismatch": [],
        "output_mismatch": [], "metrics_mismatch": [], "context_mismatch": [],
        "secret_leaks": [], "details": [],
    }
    for row in rounds:
        rid = row.req_id
        if not rid:
            out["missing"].append({"group": row.group, "round": row.round_index,
                                   "reason": "request produced no response id"})
            continue
        out["checked"] += 1
        seen_in_export = export_counts.get(rid, 0)
        if seen_in_export == 0:
            # Absent from the export is a *missing* record, not a duplicate: the
            # two are reported apart because they point at different bugs (a lost
            # write versus a double finish).
            out["missing_from_export"].append({"id": rid, "group": row.group,
                                               "round": row.round_index})
        elif seen_in_export > 1:
            out["duplicates"].append({"id": rid, "count": seen_in_export,
                                      "group": row.group, "round": row.round_index})
        detail = details.get(rid)
        if detail is None:
            out["missing"].append({"group": row.group, "round": row.round_index, "id": rid})
            continue
        if detail.get("status") != "ok":
            out["not_ok_rows"].append({"id": rid, "status": detail.get("status"),
                                       "error": detail.get("error")})
        if detail.get("source") != "/v1/chat/completions":
            out["source_mismatch"].append({"id": rid, "source": detail.get("source")})
        messages = detail.get("messages") or []
        if len(messages) != row.context_messages:
            out["context_mismatch"].append({"id": rid, "record": len(messages),
                                            "client": row.context_messages})
        last_user = next((m.get("content") for m in reversed(messages)
                          if m.get("role") == "user"), None)
        if last_user != row.input_text:
            out["input_mismatch"].append({"id": rid, "record_chars": len(last_user or ""),
                                          "client_chars": row.input_chars})
        if (detail.get("output_text") or "") != row.output:
            out["output_mismatch"].append({"id": rid,
                                           "record_chars": len(detail.get("output_text") or ""),
                                           "client_chars": len(row.output)})
        for field_name in ("prompt_tokens", "completion_tokens"):
            client_value = getattr(row, field_name)
            if client_value is None:
                continue
            record_value = detail.get(field_name)
            if record_value is not None and record_value != client_value:
                out["metrics_mismatch"].append({"id": rid, "field": field_name,
                                                "record": record_value,
                                                "client": client_value})
        # The server-side numbers are what the report should show: they come from
        # the worker's own `done` event, not from client-side timing.
        row.decode_tps = detail.get("decode_tps")
        row.server_ttft_s = detail.get("first_token_latency_s")
        if row.cached_tokens is None:
            row.cached_tokens = detail.get("cached_tokens")
        if key_secret and key_secret in json.dumps(detail, ensure_ascii=False):
            out["secret_leaks"].append({"id": rid, "what": "raw api key"})
        out["details"].append({
            "id": rid, "group": row.group, "round": row.round_index,
            "status": detail.get("status"), "finish_reason": detail.get("finish_reason"),
            "actor_type": detail.get("actor_type"), "actor_name": detail.get("actor_name"),
            "prompt_tokens": detail.get("prompt_tokens"),
            "completion_tokens": detail.get("completion_tokens"),
            "cached_tokens": detail.get("cached_tokens"),
            "first_token_latency_s": detail.get("first_token_latency_s"),
            "decode_tps": detail.get("decode_tps"),
            "output_chars": detail.get("output_chars"),
        })
    return out


def rewrite_jsonl(path: Path, rounds: list[Round]) -> None:
    """Rewrite ``rounds.jsonl`` from memory, after the record check filled in
    ``decode_tps`` and ``first_token_latency_s``.

    The file is appended to row by row during the run, on purpose: a run that
    dies mid-flight leaves whatever it had already observed. Those two columns
    come from the service's own records and are only known at the end, so the
    first copy would carry nulls. Rewriting the same rows in the same order only
    fills them in -- nothing is dropped, and a row that failed keeps its null.

    Written via a temporary file and ``os.replace`` so an interrupted rewrite
    cannot leave a half-written evidence file behind.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rounds:
            fh.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def record_log_path(env: dict, data_dir: str | os.PathLike) -> Path:
    """Where the record file actually is, per the service itself.

    ``/api/inference-records/status`` reports the live path, which survives a
    ``--storage move``. The derived default is only a fallback for an older
    build that does not report it (or an unreachable status route): checking the
    wrong file would otherwise report "missing" records that are all present.
    """
    reported = (env.get("record_log") or {}).get("path")
    if reported:
        return Path(reported)
    return Path(data_dir) / "state" / "inference_records.sqlite3"


def sqlite_check(path: Path, rounds: list[Round]) -> dict:
    """Read the record file directly, without going through the service.

    The admin API proves what the service will tell you; this proves what is
    actually on disk, which is what "the record survived" has to mean. Opened
    through a read-only URI so a live WAL database is never modified.

    The path comes from ``/api/inference-records/status`` rather than being
    derived from ``--data-dir``: the data directory can be moved with
    ``--storage move``, and a guessed path would then silently check a stale file
    (or none) while reporting green.
    """
    out: dict = {"path": str(path), "exists": path.is_file(),
                 "bytes": path.stat().st_size if path.is_file() else None,
                 "readable": False, "found": 0, "expected": 0,
                 "missing": [], "output_mismatch": [], "error": None}
    if not path.is_file():
        out["error"] = "file not found"
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            out["readable"] = True
            for row in rounds:
                if not row.req_id:
                    continue
                out["expected"] += 1
                found = conn.execute(
                    "SELECT output_text FROM inference_records WHERE id = ?",
                    (row.req_id,)).fetchall()
                if len(found) != 1:
                    out["missing"].append({"id": row.req_id, "rows": len(found)})
                    continue
                out["found"] += 1
                if (found[0][0] or "") != row.output:
                    out["output_mismatch"].append({"id": row.req_id})
        finally:
            conn.close()
    except sqlite3.Error as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ---------------------------------------------------------------------------
# Environment capture and restart
# ---------------------------------------------------------------------------
def run_cmd(cmd: list[str], timeout: float = 120.0) -> str:
    """Run a read-only command and return its combined output; never raises."""
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        return (done.stdout + done.stderr).decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(command failed: {type(exc).__name__}: {exc})"


SECRET_SETTING_KEYS = ("admin_password_hash", "key_hash")


def capture_environment(http: Http, data_dir: Path) -> dict:
    """Version, model, settings and service state as the board reports them.

    Read-only: the settings are copied from the live service, not changed, and
    anything hash-shaped is dropped before the result reaches disk.
    """
    out: dict = {"captured_iso": datetime.now(timezone.utc)
                 .isoformat(timespec="seconds").replace("+00:00", "Z")}
    _, out["healthz"] = http.json("GET", "/healthz", timeout=30)
    status, stats = http.json("GET", "/api/stats", timeout=90)
    if status == 200:
        out["models"] = [
            {k: m.get(k) for k in ("id", "loaded", "context_length",
                                   "supports_vision", "supports_sampling", "port",
                                   "size_bytes", "bmodel_files", "load_seconds")}
            for m in stats.get("models") or []
        ]
        device = stats.get("device") or {}
        out["device"] = {k: device.get(k) for k in
                         ("kernel", "libsophon", "product", "serial", "cpu", "memory")}
        out["usage"] = {k: (stats.get("usage") or {}).get(k)
                        for k in ("requests", "prompt_tokens", "completion_tokens",
                                  "cached_tokens")}
    status, settings = http.json("GET", "/api/settings", timeout=30)
    if status == 200:
        out["settings"] = {k: v for k, v in settings.items()
                           if k not in SECRET_SETTING_KEYS and "hash" not in k}
    _, out["record_log"] = http.json("GET", "/api/inference-records/status", timeout=30)
    version_file = Path("/opt/sophgo/cv84x6_llm_server/VERSION")
    out["service"] = {
        "active": run_cmd(["systemctl", "is-active", "cv84x6-llm"]).strip(),
        "version_pkg": run_cmd(["dpkg-query", "-W", "-f=${Version}",
                                "cv84x6-llm-server"]).strip(),
        "version_file": version_file.read_text().strip() if version_file.is_file() else None,
        "main_pid": run_cmd(["systemctl", "show", "-p", "MainPID", "--value",
                             "cv84x6-llm"]).strip(),
        "started": run_cmd(["systemctl", "show", "-p", "ActiveEnterTimestamp",
                            "--value", "cv84x6-llm"]).strip(),
        "command_line": run_cmd(["systemctl", "show", "-p", "ExecStart", "--value",
                                 "cv84x6-llm"]).strip(),
    }
    out["kernel"] = run_cmd(["uname", "-a"]).strip()
    out["libsophon"] = run_cmd(["bash", "-lc",
                                "ls /opt/sophon/libsophon-current/lib/libbmrt.so* "
                                "2>/dev/null"]).strip()
    out["sdk_version"] = run_cmd(["bash", "-lc",
                                  "cat /opt/sophon/libsophon-current/version.txt "
                                  "2>/dev/null || true"]).strip()
    out["data_dir"] = str(data_dir)
    out["model_dirs"] = []
    models_root = data_dir / "models"
    if models_root.is_dir():
        for d in sorted(models_root.iterdir()):
            if not d.is_dir():
                continue
            bmodels = sorted(d.glob("*.bmodel"))
            out["model_dirs"].append({
                "dir": d.name,
                "bmodel": bmodels[0].name if bmodels else None,
                "bytes": bmodels[0].stat().st_size if bmodels else None,
            })
    return out


def restart_service(http: Http, password: str, evidence: Path, model: str,
                    timeout: float = 300.0, load_timeout: float = 900.0) -> dict:
    """Normal ``systemctl restart`` plus the checks that make it meaningful.

    SIGTERM only: the service's own shutdown reaps the worker. ``kill -9`` on a
    process holding the NPU heap is what wedges the TPU, so it is never used
    here. The record count is compared across the restart to prove the log
    survived, and the admin session is re-established -- sessions live in the
    service's memory, so the pre-restart cookie is worthless afterwards.

    The model does **not** come back by itself: this service has no autoload,
    and a restart's worker takeover only adopts a worker that is still running.
    Reloading it through the console API is therefore part of the restart
    procedure, not an extra step, and the load time is recorded -- it is the
    real "time to serving again" an operator cares about.
    """
    out: dict = {"ok": False, "method": "systemctl restart cv84x6-llm",
                 "steps": [], "before": {}, "after": {}, "model": model}
    before_pid = run_cmd(["systemctl", "show", "-p", "MainPID", "--value",
                          "cv84x6-llm"]).strip()
    _, before_status = http.json("GET", "/api/inference-records/status", timeout=30)
    out["before"] = {"main_pid": before_pid, "records": before_status.get("total")}

    started = time.time()
    out["steps"].append({"step": "restart", "output": run_cmd(
        ["sudo", "-n", "systemctl", "restart", "cv84x6-llm"], timeout=180).strip()})

    health: dict = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, health = http.json("GET", "/healthz", timeout=10)
        except OSError:
            status, health = 0, {}
        if status == 200 and health.get("ok"):
            break
        time.sleep(3)
    out["recovery_s"] = round(time.time() - started, 2)
    out["after"]["healthz"] = health
    out["after"]["main_pid"] = run_cmd(["systemctl", "show", "-p", "MainPID", "--value",
                                        "cv84x6-llm"]).strip()
    out["new_pid"] = out["after"]["main_pid"] != before_pid

    login_status = http.login(password)
    load_started = time.time()
    load_status, load_body = http.json("POST", f"/api/models/{model}/load",
                                       timeout=load_timeout)
    out["model_load"] = {"status": load_status, "s": round(time.time() - load_started, 2),
                         "ok": load_status == 200,
                         "detail": None if load_status == 200 else str(load_body)[:400]}
    out["serving_again_s"] = round(time.time() - started, 2)

    _, listing = http.json("GET", "/api/inference-records?limit=1", timeout=30)
    out["after"]["records_total"] = listing.get("total")
    out["after"]["login_status"] = login_status
    out["records_survived"] = (out["before"].get("records") is not None
                               and (listing.get("total") or 0) >= (out["before"]["records"] or 0))
    out["steps"].append({"step": "health", "ok": bool(health.get("ok")),
                         "loaded": health.get("loaded"), "login": login_status,
                         "model_load": out["model_load"]})

    (evidence / "journal-restart.txt").write_text(
        run_cmd(["sudo", "-n", "journalctl", "-u", "cv84x6-llm",
                 "--since", f"@{int(started) - 5}", "--no-pager"], timeout=120),
        encoding="utf-8")
    out["ok"] = (bool(health.get("ok")) and out["new_pid"]
                 and login_status == 200 and out["records_survived"]
                 and out["model_load"]["ok"])
    return out


def post_restart_request(http: Http, key: str, model: str, raw_dir: Path,
                         timeout: float = 600.0) -> Round:
    """One short request after the restart: does the service still answer and log?

    Returns the round without recording it; the caller writes it to the JSONL so
    every row reaches the file through exactly one path.
    """
    prompt = build_prompt(30, 201)
    row = chat_once(http, key, model, prompt, "restart",
                    [{"role": "user", "content": prompt.text}], raw_dir, timeout=timeout)
    if row.req_id:
        status, detail = http.json("GET", f"/api/inference-records/{row.req_id}", timeout=60)
        if status != 200:
            row.error = row.error or f"post-restart record missing (HTTP {status})"
        elif (detail.get("output_text") or "") != row.output:
            row.error = row.error or "post-restart record output differs"
        else:
            row.decode_tps = detail.get("decode_tps")
            row.server_ttft_s = detail.get("first_token_latency_s")
    return row


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def distribution(values: list[float]) -> dict:
    """min / median / max over the non-None values.

    Not a mean: on this board one queued request among twenty moves a mean far
    more than it moves the median, and the tail is what an operator needs.
    """
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {"n": len(clean), "min": round(min(clean), 4),
            "median": round(statistics.median(clean), 4), "max": round(max(clean), 4)}


def summarize(rounds: list[Round]) -> dict:
    """Per-group rates and distributions, plus run-wide totals."""
    out: dict = {"groups": {}, "totals": {}}
    for group in sorted({r.group for r in rounds}):
        rows = [r for r in rounds if r.group == group]
        ok = [r for r in rows if r.http_status == 200 and r.error is None]
        counts = [r.count_ok for r in rows if r.count_ok is not None]
        recalls = [r.recall_ok for r in rows if r.recall_ok is not None]
        markers = [r.marker_ok for r in rows if r.marker_ok is not None]
        errors: dict[str, int] = {}
        for r in rows:
            if r.error:
                head = r.error.split(":")[0][:60]
                errors[head] = errors.get(head, 0) + 1
        empty = sum(1 for r in rows if not r.output)
        out["groups"][group] = {
            "requests": len(rows),
            "ok": len(ok),
            "success_rate": round(len(ok) / len(rows), 4) if rows else None,
            "empty_outputs": empty,
            "empty_rate": round(empty / len(rows), 4) if rows else None,
            "error_types": errors,
            "ttft_s": distribution([r.ttft_s for r in rows]),
            "server_ttft_s": distribution([r.server_ttft_s for r in rows]),
            "total_s": distribution([r.total_s for r in rows]),
            "decode_tps": distribution([r.decode_tps for r in rows]),
            "prompt_tokens": distribution([r.prompt_tokens for r in rows]),
            "completion_tokens": distribution([r.completion_tokens for r in rows]),
            "cached_tokens": distribution([r.cached_tokens for r in rows]),
            "count_checked": len(counts),
            "count_ok": sum(1 for c in counts if c),
            "recall_checked": len(recalls),
            "recall_ok": sum(1 for r in recalls if r),
            "marker_checked": len(markers),
            "marker_ok": sum(1 for r in markers if r),
            "cross_talk": sum(1 for r in rows if r.cross_talk),
        }
    core = [r for r in rounds if r.group in ("nocxt", "cxt")]
    out["totals"] = {
        "requests": len(rounds),
        "core_requests": len(core),
        "core_ok": sum(1 for r in core if r.http_status == 200 and r.error is None),
        "http_5xx": sum(1 for r in rounds if (r.http_status or 0) >= 500),
        "http_4xx": sum(1 for r in rounds
                        if r.http_status and 400 <= r.http_status < 500),
        "connection_errors": sum(1 for r in rounds
                                 if r.http_status is None and r.error),
        "empty_outputs": sum(1 for r in rounds if not r.output),
    }
    return out


def verdict(summary: dict, records: dict, db: dict | None, restart: dict | None) -> dict:
    """The acceptance gate, computed rather than asserted in prose.

    Counting checks are compared against zero; boolean checks must all hold.
    ``core_20_ok`` is separate because "20 of 20 ended cleanly" is the headline
    claim of the whole run.

    Answer correctness enters as a **floor, not a threshold**: at least one core
    answer must be right, and -- when the battery graded any -- at least one
    recall too. The task card defines acceptance as stability -- 20/20 clean, no
    5xx, no cross-talk, records consistent -- and inventing a "90% correct" bar
    would be adding an acceptance criterion nobody asked for. But a run where the
    model answered *nothing* correctly has not demonstrated a working service
    either, and calling that "通过" would be exactly the kind of green-but-empty
    report this suite exists to prevent.

    The recall floor is there because the first board run proved it matters: its
    mechanical checks were all green and its recall was 0/4, and the cause was a
    self-contradictory prompt in this harness. A gate that shrugged at 0/4 would
    have shipped that bug. Either the model is ignoring the history or the
    harness is broken -- both deserve a non-pass.

    The full accuracy rates are always printed in the report, so a low-but-nonzero
    rate is visible rather than hidden behind the gate.
    """
    conc = {g: v for g, v in summary["groups"].items() if g.startswith("conc-")}
    core_groups = {g: v for g, v in summary["groups"].items() if g in ("nocxt", "cxt")}
    counts_graded = sum(v["count_checked"] for v in core_groups.values())
    counts_ok = sum(v["count_ok"] for v in core_groups.values())
    recall_graded = sum(v["recall_checked"] for v in core_groups.values())
    recall_ok = sum(v["recall_ok"] for v in core_groups.values())
    counts = {
        "records_missing": len(records["missing"]),
        "records_missing_from_export": len(records.get("missing_from_export") or []),
        "records_duplicated": len(records["duplicates"]),
        "records_output_mismatch": len(records["output_mismatch"]),
        "records_metrics_mismatch": len(records["metrics_mismatch"]),
        "records_context_mismatch": len(records["context_mismatch"]),
        "records_input_mismatch": len(records["input_mismatch"]),
        "records_not_ok": len(records["not_ok_rows"]),
        "records_source_mismatch": len(records["source_mismatch"]),
        "secret_leaks": len(records["secret_leaks"]),
        "http_5xx": summary["totals"]["http_5xx"],
        "empty_outputs": summary["totals"]["empty_outputs"],
        "cross_talk": sum(v["cross_talk"] for v in summary["groups"].values()),
    }
    flags = {
        "core_20_ok": summary["totals"]["core_ok"] == 2 * len(LENGTHS),
        "concurrent_all_ok": (len(conc) == len(CONCURRENCY_TIERS)
                              and all(v["ok"] == CONCURRENCY_PER_TIER for v in conc.values())),
        "some_answer_correct": counts_ok >= 1,
        "some_recall_correct": recall_ok >= 1 if recall_graded else True,
    }
    if db is not None:
        counts["sqlite_missing"] = len(db["missing"])
        counts["sqlite_output_mismatch"] = len(db["output_mismatch"])
        flags["sqlite_readable"] = db["readable"]
    if restart is not None:
        flags["restart_ok"] = bool(restart.get("ok"))
    gate: dict = {**flags, **counts}
    gate["count_graded"] = counts_graded
    gate["count_correct"] = counts_ok
    gate["count_accuracy"] = (round(counts_ok / counts_graded, 4)
                              if counts_graded else None)
    gate["recall_graded"] = recall_graded
    gate["recall_correct"] = recall_ok
    gate["recall_accuracy"] = (round(recall_ok / recall_graded, 4)
                               if recall_graded else None)
    gate["passed"] = all(v == 0 for v in counts.values()) and all(flags.values())
    return gate


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _short(value) -> str:
    """Three decimals at most, trailing zeros dropped: 46.0 -> 46, 0.010021 -> 0.010.

    Display only -- the JSON beside the report keeps full precision.
    """
    if value is None:
        return "-"
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _d(d: dict) -> str:
    """min / median / max as one cell; ``-`` when nothing was measured."""
    if not d or not d.get("n"):
        return "-"
    return f"{_short(d['min'])} / {_short(d['median'])} / {_short(d['max'])}"


def _num(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return _short(value)
    return str(value)


def write_report(evidence: Path, env: dict, summary: dict, records: dict, db: dict,
                 restart: dict | None, gate: dict, manifest: dict,
                 rounds: list[Round], device_label: str) -> Path:
    """The human-readable report, generated from the same numbers as the JSON.

    Regenerated from data rather than written by hand, so its tables cannot
    drift away from the JSONL sitting beside them.
    """
    lines: list[str] = []
    add = lines.append
    svc = env.get("service") or {}
    rec_log = env.get("record_log") or {}
    conc = {g: v for g, v in summary["groups"].items() if g.startswith("conc-")}

    add("# CV84X6 上下文/并发稳定性测试报告")
    add("")
    add(f"生成时间（UTC）：{env.get('captured_iso')}　·　证据目录：`{evidence.name}/`")
    add("")
    add("## 结论先行")
    add("")
    add(f"- 核心 20 次（无上下文 10 + 带上下文 10）：**{summary['totals']['core_ok']}/20** "
        f"正常结束；HTTP 5xx {summary['totals']['http_5xx']} 次、4xx "
        f"{summary['totals']['http_4xx']} 次、连接异常 "
        f"{summary['totals']['connection_errors']} 次、空回复 "
        f"{summary['totals']['empty_outputs']} 条。")
    add("- 并发 9 次（3 档 × 3 路）："
        + "，".join(f"{g} {v['ok']}/{v['requests']}" for g, v in conc.items())
        + f"；串话 {sum(v['cross_talk'] for v in conc.values())} 次，"
          f"标记回显正确 {sum(v['marker_ok'] for v in conc.values())}/"
          f"{sum(v['marker_checked'] for v in conc.values())}。")
    add(f"- 推理记录一致性：核对 {records['checked']} 条请求，缺失 "
        f"{len(records['missing'])}、导出中缺失 "
        f"{len(records.get('missing_from_export') or [])}、重复 "
        f"{len(records['duplicates'])}、输出不一致 "
        f"{len(records['output_mismatch'])}、token 不一致 "
        f"{len(records['metrics_mismatch'])}、上下文条数不一致 "
        f"{len(records['context_mismatch'])}；直接读 SQLite 命中 "
        f"{db['found']}/{db['expected']}。")
    if restart is not None:
        add(f"- 正常重启（`{restart['method']}`，SIGTERM）：PID "
            f"`{restart['before'].get('main_pid')}` → `{restart['after'].get('main_pid')}`，"
            f"恢复 {restart.get('recovery_s')}s，历史记录保留 "
            f"{'是' if restart.get('records_survived') else '否'}，重启后新请求"
            f"{'已落盘且一致' if restart.get('ok') else '存在问题'}。")
    add(f"- 计数正确 {gate.get('count_correct')}/{gate.get('count_graded')}"
        f"（准确率 {gate.get('count_accuracy')}），回忆正确 "
        f"{gate.get('recall_correct')}/{gate.get('recall_graded')}"
        f"（准确率 {gate.get('recall_accuracy')}）；正确率只作参考，判定口径见「验收判定」。")
    add(f"- 验收判定：**{'通过' if gate['passed'] else '未通过'}**")
    add("")

    add("## 环境与版本")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 设备 | {device_label} |")
    pkg = (svc.get("version_pkg") or "").strip()
    add(f"| 安装版本 | deb `{pkg}`"
        + (f"；`VERSION` 文件 `{svc.get('version_file')}`"
           if svc.get("version_file") else "")
        + f"；服务自报 `/healthz` `{(env.get('healthz') or {}).get('version')}` |")
    add(f"| 服务状态 | `{svc.get('active')}`，MainPID `{svc.get('main_pid')}`，启动于 "
        f"`{svc.get('started')}` |")
    add(f"| `/healthz` | `{json.dumps(env.get('healthz'), ensure_ascii=False)}` |")
    for m in env.get("models") or []:
        if m.get("id"):
            add(f"| 模型 | `{m.get('id')}`，loaded={m.get('loaded')}，"
                f"context_length={m.get('context_length')}，"
                f"supports_sampling={m.get('supports_sampling')}，"
                f"加载耗时 {m.get('load_seconds')}s |")
    for d in env.get("model_dirs") or []:
        add(f"| 权重文件 | `{d.get('bmodel')}`（{d.get('bytes')} 字节） |")
    add(f"| 内核 | `{(env.get('kernel') or '').strip()}` |")
    add(f"| libsophon | `{(env.get('sdk_version') or '').strip() or (env.get('libsophon') or '').strip()}` |")
    add(f"| 数据目录 | `{env.get('data_dir')}` |")
    add(f"| 记录库（测试开始前） | `{rec_log.get('path')}`，{rec_log.get('total')} 条，"
        f"{rec_log.get('bytes')} 字节 |")
    add("")
    add("服务启动命令（`systemctl show -p ExecStart`）：")
    add("")
    add("```text")
    add((svc.get("command_line") or "").strip())
    add("```")
    add("")
    settings = env.get("settings") or {}
    add("关键设置（`GET /api/settings`，已去除所有 hash 字段）：")
    add("")
    add("| 设置 | 值 |")
    add("|---|---|")
    for key in ("max_concurrent_per_model", "max_queue", "prefix_cache_entries",
                "prefix_cache_ttl_min", "prefill_exact_tail",
                "inference_logging_enabled", "inference_log_retention_count",
                "inference_log_retention_days", "require_api_key"):
        if key in settings:
            add(f"| `{key}` | `{settings[key]}` |")
    add("")
    sampling = {m.get("id"): m.get("supports_sampling") for m in env.get("models") or []}
    if any(value is False for value in sampling.values()):
        add("> 本板 bmodel 的 `supports_sampling` 为 `false`：`lm_head` 只输出 int32，argmax 融在"
            "图里，`temperature`/`top_p`/`top_k` **不生效**，解码本身即确定。参数仍按固定值发送"
            "并记录，用于保证每次请求形状一致；不要把上表参数当作本机型实际可调的采样手段。")
        add("")

    add("## 测试矩阵与参数")
    add("")
    add(f"固定参数：`{json.dumps(PARAMS, ensure_ascii=False)}`、`seed={SEED}`；"
        f"核心 20 次串行，每轮完整收到响应（含 `[DONE]`）才发下一轮；"
        f"system prompt 固定为「{SYSTEM_PROMPT}」。长度档是整个 user message 的 "
        f"Unicode 码点数：`{LENGTHS}`，每个长度一轮。")
    add("")
    add("| 组 | 轮次 | 输入字数 | SHA-256（前 12） | 期望计数 | 期望回忆 | 上下文消息数 | HTTP | 首 token(s) | 总耗时(s) | prompt/completion/cached | decode_tps | finish_reason | 判分 |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rounds:
        if row.group not in ("nocxt", "cxt"):
            continue
        score = []
        if row.count_ok is not None:
            score.append("计数" + ("✓" if row.count_ok else "✗"))
        if row.recall_ok is not None:
            score.append("回忆" + ("✓" if row.recall_ok else "✗"))
        add(f"| {row.group} | {row.round_index} | {row.input_chars} | "
            f"`{row.input_sha256[:12]}` | {_num(row.expected_count)} | "
            f"{row.expected_recall or '-'} | {row.context_messages} | "
            f"{_num(row.http_status)} | {_num(row.ttft_s)} | {_num(row.total_s)} | "
            f"{_num(row.prompt_tokens)}/{_num(row.completion_tokens)}/"
            f"{_num(row.cached_tokens)} | {_num(row.decode_tps)} | "
            f"{row.finish_reason or '-'} | {' '.join(score) or '-'} |")
    add("")

    add("## 成功率与分布（min / median / max）")
    add("")
    add("| 组 | 请求 | 成功 | 成功率 | 空回复 | 首 token(s) | 总耗时(s) | decode_tps | prompt tokens | completion tokens | cached tokens | 计数正确 | 回忆正确 |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for group, g in summary["groups"].items():
        add(f"| {group} | {g['requests']} | {g['ok']} | {g['success_rate']} | "
            f"{g['empty_outputs']} | {_d(g['ttft_s'])} | {_d(g['total_s'])} | "
            f"{_d(g['decode_tps'])} | {_d(g['prompt_tokens'])} | "
            f"{_d(g['completion_tokens'])} | {_d(g['cached_tokens'])} | "
            f"{g['count_ok']}/{g['count_checked']} | "
            f"{g['recall_ok']}/{g['recall_checked'] or '-'} |")
    add("")
    add("错误分类（按组）：")
    add("")
    add("| 组 | 错误类型 | 次数 |")
    add("|---|---|---|")
    printed = False
    for group, g in summary["groups"].items():
        for kind, count in (g["error_types"] or {}).items():
            printed = True
            add(f"| {group} | `{kind}` | {count} |")
    if not printed:
        add("| — | 无 | 0 |")
    add("")
    add("> 两组不构成性能 A/B：带上下文组每轮重发全部历史，prompt token 必然更大。"
        "上表只用于判断服务是否稳定、时延是否出现异常长尾。")
    add("")

    if conc:
        add("## 并发组（3 档 × 3 路独立请求）")
        add("")
        add("| 组 | 档位字数 | 请求 | 成功 | 标记回显 | 串话 | 总耗时(s) | decode_tps | prompt tokens |")
        add("|---|---|---|---|---|---|---|---|---|")
        for name, length in CONCURRENCY_TIERS:
            g = conc.get(f"conc-{name}")
            if not g:
                continue
            add(f"| conc-{name} | {length} | {g['requests']} | {g['ok']} | "
                f"{g['marker_ok']}/{g['marker_checked']} | {g['cross_talk']} | "
                f"{_d(g['total_s'])} | {_d(g['decode_tps'])} | {_d(g['prompt_tokens'])} |")
        add("")

    if restart is not None:
        add("## 重启恢复")
        add("")
        add(f"- 方式：`{restart['method']}`（SIGTERM，未使用任何强杀手段）。")
        add(f"- MainPID：`{restart['before'].get('main_pid')}` → "
            f"`{restart['after'].get('main_pid')}`，`/healthz` ok 耗时 "
            f"{restart.get('recovery_s')}s；重启后重新登录 "
            f"HTTP {restart['after'].get('login_status')}。")
        load = restart.get("model_load") or {}
        add(f"- 模型 `{restart.get('model')}` 重新加载：HTTP {load.get('status')}，"
            f"耗时 {load.get('s')}s"
            + ("" if load.get("ok") else f"，失败详情：`{load.get('detail')}`")
            + f"；从 restart 到可服务合计 {restart.get('serving_again_s')}s。")
        add("  > 该服务没有开机自动加载模型：`systemctl restart` 后 worker 需要重新加载，"
            "因此「重启恢复」包含这一步，时间也照实计入。")
        add(f"- 记录数：重启前 {restart['before'].get('records')} → 重启后 "
            f"{restart['after'].get('records_total')}；历史记录保留 "
            f"{'是' if restart.get('records_survived') else '否'}。")
        rr = next((r for r in rounds if r.group == "restart"), None)
        if rr is not None:
            add(f"- 重启后短请求（{rr.input_chars} 字）：HTTP {rr.http_status}，输出"
                f"「{(rr.output or '').strip()[:60]}」，记录"
                f"{'已落盘且与服务响应一致' if rr.error is None else '异常：' + str(rr.error)}。")
        add("- 重启时间窗内的 `journalctl` 已存为 `journal-restart.txt`。")
        add("")

    add("## 推理记录一致性")
    add("")
    add(f"- 管理 API 逐条按 `req_id` 核对：检查 {records['checked']} 条；详情缺失 "
        f"{len(records['missing'])}、导出中缺失 "
        f"{len(records.get('missing_from_export') or [])}、导出中重复 "
        f"{len(records['duplicates'])}、"
        f"来源不符 {len(records['source_mismatch'])}、状态非 `ok` "
        f"{len(records['not_ok_rows'])}。")
    add(f"- 字段比对：输入文本不一致 {len(records['input_mismatch'])}、输出文本不一致 "
        f"{len(records['output_mismatch'])}、token 不一致 "
        f"{len(records['metrics_mismatch'])}、上下文消息数不一致 "
        f"{len(records['context_mismatch'])}。")
    add(f"- NDJSON 导出 {records.get('export_lines', 0)} 行，逐行按 id 计数核对。")
    add(f"- 直接读 SQLite（`mode=ro`）：文件"
        f"{'存在' if db['exists'] else '不存在'}，{_num(db['bytes'])} 字节，"
        f"可读={db['readable']}，按 id 命中 {db['found']}/{db['expected']}"
        + (f"，错误：`{db['error']}`" if db.get("error") else "") + "。")
    add(f"- 记录内是否出现原始 API key："
        f"{'出现（不合格）' if records['secret_leaks'] else '未出现'}。")
    add("")
    bad = {k: records[k] for k in ("missing", "missing_from_export", "duplicates",
                                   "output_mismatch",
                                   "metrics_mismatch", "context_mismatch",
                                   "input_mismatch", "not_ok_rows", "secret_leaks")
           if records.get(k)}
    if bad:
        add("异常明细：")
        add("")
        add("```json")
        add(json.dumps(bad, ensure_ascii=False, indent=1))
        add("```")
        add("")

    add("## 验收判定")
    add("")
    add("| 判据 | 值 |")
    add("|---|---|")
    for key, value in gate.items():
        add(f"| `{key}` | `{value}` |")
    add("")

    add("## 证据清单")
    add("")
    add("| 文件 | 内容 |")
    add("|---|---|")
    add(f"| `rounds.jsonl` | 每轮一行机器可读数据（{len(rounds)} 行，含失败行） |")
    add("| `manifest.json` | 每条 prompt 的全文、字符数、SHA-256、期望答案与 seed |")
    add("| `summary.json` | 上面表格的原始数字与验收判定 |")
    add("| `records-export.ndjson` | 服务导出的全部记录 |")
    add("| `records-check.json` | 逐条记录一致性核对结果 |")
    add("| `sqlite-check.json` | 直接读记录库的结果 |")
    add("| `env.json` | 版本、模型、设置、设备快照 |")
    add("| `raw/*.sse` | 每个请求的原始 SSE 响应体（失败也保留） |")
    add("| `journal-test.txt` | 测试时间窗内的服务日志 |")
    add("| `journal-restart.txt` | 重启时间窗内的服务日志 |")
    add("| `dmesg.txt` | 测试结束时的内核日志（检查 NPU 报错） |")
    add("")
    add(f"重跑参数：`seed={manifest['seed']}`、模型 `{manifest['model']}`；prompt 由 "
        f"`tools/board_stability_suite.py` 的 `build_prompt` 按 seed 确定性生成，"
        f"同一 seed 下可用 `manifest.json` 逐字复核。重跑会新建 `run-*` 目录，"
        f"不覆盖本次证据。")
    add("")
    path = evidence / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def make_run_dir(base: Path) -> Path:
    """A fresh run directory; refusing to reuse one is the point.

    Evidence from a failed run must never be overwritten by the next attempt --
    that is what makes "we do not re-run over a failure" true in practice rather
    than a promise. Two runs inside the same second get ``-2``, ``-3``, ... rather
    than sharing a directory.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base.mkdir(parents=True, exist_ok=True)
    for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
        run = base / f"run-{stamp}{suffix}"
        try:
            run.mkdir()
        except FileExistsError:
            continue
        if any(run.iterdir()):  # pragma: no cover - mkdir already guarantees empty
            continue
        (run / "raw").mkdir()
        return run
    raise SystemExit(f"cannot find a free run directory under {base}")


def pick_model(http: Http) -> str:
    """The loaded model's id, so the suite cannot silently test another one."""
    status, stats = http.json("GET", "/api/stats", timeout=90)
    if status != 200:
        raise SystemExit(f"cannot read /api/stats (HTTP {status})")
    loaded = [m for m in stats.get("models") or [] if m.get("loaded")]
    if not loaded:
        raise SystemExit("no model is loaded; load one through the console first")
    return loaded[0]["id"]


def create_key(http: Http, name: str) -> tuple[str, str]:
    """Mint a key for this run. The raw value stays in memory only."""
    status, body = http.json("POST", "/api/keys", {"name": name}, timeout=60)
    if status != 200 or not body.get("key"):
        raise SystemExit(f"key creation failed: HTTP {status} {body}")
    return body["key"], body["meta"]["id"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Board stability suite: fixed-length chats, context growth, "
                    "concurrency and a restart, with per-request evidence.")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--password", default=os.environ.get("CV84X6_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--evidence-dir", default="./stability-evidence",
                    help="parent directory; a timestamped run-* subdirectory is created")
    ap.add_argument("--data-dir", default="/data/cv84x6_llm_server")
    ap.add_argument("--device-label", default="10.43.0.151")
    ap.add_argument("--model", default=None, help="model id (default: the loaded one)")
    ap.add_argument("--api-key", default=None,
                    help="reuse this key instead of minting one (never written to evidence)")
    ap.add_argument("--key-name", default=KEY_NAME_DEFAULT)
    ap.add_argument("--timeout", type=float, default=1800.0, help="per-request timeout")
    ap.add_argument("--restart", action="store_true",
                    help="restart the service through systemd after the core run "
                         "(needs passwordless sudo)")
    args = ap.parse_args(argv)

    evidence = make_run_dir(Path(args.evidence_dir))
    raw_dir = evidence / "raw"
    print(f"evidence: {evidence}", flush=True)

    http = Http(args.base, timeout=max(args.timeout, 120.0))
    if http.login(args.password) != 200:
        raise SystemExit("console login failed")

    model = args.model or pick_model(http)
    print(f"model: {model}", flush=True)
    key, key_id, minted = args.api_key, None, False
    if not key:
        key, key_id = create_key(http, args.key_name)
        minted = True
    print(f"api key: {'minted ' + args.key_name if minted else 'reused from --api-key'}",
          flush=True)

    env = capture_environment(http, Path(args.data_dir))
    (evidence / "env.json").write_text(json.dumps(env, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    battery = build_battery()
    manifest = {
        "seed": SEED,
        "model": model,
        "lengths": LENGTHS,
        "params": PARAMS,
        "system": SYSTEM_PROMPT,
        "concurrency": [{"name": n, "length": n_len} for n, n_len in CONCURRENCY_TIERS],
        "generated_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompts": [p.manifest() for p in battery + build_concurrency_prompts()],
    }
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    rounds: list[Round] = []
    restart_info: dict | None = None
    jsonl = (evidence / "rounds.jsonl").open("w", encoding="utf-8")

    def record(row: Round) -> Round:
        rounds.append(row)
        jsonl.write(json.dumps(row.as_row(), ensure_ascii=False) + "\n")
        jsonl.flush()
        mark = "计数✓" if row.count_ok else ("计数✗" if row.count_ok is False else "")
        if row.recall_ok is not None:
            mark += "回忆✓" if row.recall_ok else "回忆✗"
        tail = (row.output or "").strip().replace("\n", " ")[:30]
        print(f"  {row.group:<10} r{row.round_index:>3} {row.input_chars:>4}字 "
              f"HTTP {_num(row.http_status)} {_num(row.total_s)}s "
              f"pt={_num(row.prompt_tokens)} ct={_num(row.completion_tokens)} {mark} "
              f"out={tail!r}"
              + (f" ERR {row.error[:70]}" if row.error else ""), flush=True)
        return row

    try:
        print("== nocxt: 10 independent requests ==", flush=True)
        for prompt in battery:
            messages = context_messages(SYSTEM_PROMPT, [], prompt.text)
            record(chat_once(http, key, model, prompt, "nocxt", messages, raw_dir,
                             args.timeout))

        print("== cxt: 10 turns of one growing conversation ==", flush=True)
        history: list[dict] = []
        for prompt in battery:
            messages = context_messages(SYSTEM_PROMPT, history, prompt.text)
            row = record(chat_once(http, key, model, prompt, "cxt", messages, raw_dir,
                                   args.timeout))
            # The assistant turn enters the history exactly as received, so the
            # next request really contains what the model said, not an idealised
            # version of it.
            history = append_turn(history, prompt.text, row.output)

        print("== concurrency: 3 tiers x 3 requests ==", flush=True)
        for name, length in CONCURRENCY_TIERS:
            for row in run_concurrency_tier(args.base, key, model, name, length,
                                            raw_dir, args.timeout):
                record(row)

        if args.restart:
            print("== restart: systemctl restart + reload the model ==", flush=True)
            restart_info = restart_service(http, args.password, evidence, model)
            print(f"  ok={restart_info['ok']} pid {restart_info['before'].get('main_pid')}"
                  f" -> {restart_info['after'].get('main_pid')}, health "
                  f"{restart_info.get('recovery_s')}s, model load "
                  f"{restart_info['model_load']['s']}s"
                  f" (HTTP {restart_info['model_load']['status']})", flush=True)
            record(post_restart_request(http, key, model, raw_dir, args.timeout))
    finally:
        jsonl.close()
        summary: dict = summarize(rounds)
        records: dict = {}
        db: dict = {"readable": False, "found": 0, "expected": 0, "missing": [],
                    "output_mismatch": [], "exists": False, "bytes": None,
                    "error": "not checked"}
        gate: dict = {"passed": False, "reason": "run aborted before verification"}
        try:
            details, no_ids = fetch_records(http, rounds)
            counts, export_lines = export_records(http, evidence / "records-export.ndjson")
            records = verify_records(rounds, details, counts, key)
            records["no_record_ids"] = no_ids
            records["export_lines"] = export_lines
            db = sqlite_check(record_log_path(env, args.data_dir), rounds)
            # Rewrite the JSONL now that verification has adopted the server-side
            # numbers (decode_tps, first_token_latency_s). The file was written
            # row by row as the run went -- which is what keeps evidence when a
            # run dies mid-flight -- but those two fields only exist once the
            # records have been read back, so the first copy has them null. Same
            # rows, same order, only the two columns filled in.
            rewrite_jsonl(evidence / "rounds.jsonl", rounds)
            summary = summarize(rounds)
            gate = verdict(summary, records, db, restart_info)
        except Exception:  # noqa: BLE001 - a broken verification still leaves a report
            traceback.print_exc()
            records.setdefault("verification_error", traceback.format_exc()[-2000:])
        (evidence / "records-check.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        (evidence / "sqlite-check.json").write_text(
            json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
        dmesg = run_cmd(["sudo", "-n", "dmesg"], timeout=60)
        (evidence / "dmesg.txt").write_text(dmesg, encoding="utf-8")
        window = min((r.started_at for r in rounds if r.started_at), default=time.time())
        (evidence / "journal-test.txt").write_text(
            run_cmd(["sudo", "-n", "journalctl", "-u", "cv84x6-llm",
                     "--since", f"@{int(window) - 30}", "--no-pager"], timeout=180),
            encoding="utf-8")
        summary["verdict"] = gate
        if restart_info is not None:
            summary["restart"] = restart_info
        (evidence / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        report = write_report(evidence, env, summary, records, db, restart_info, gate,
                              manifest, rounds, args.device_label)
        if minted and key_id:
            status, _ = http.json("DELETE", f"/api/keys/{key_id}", timeout=30)
            print(f"cleanup: removed key {args.key_name} (HTTP {status})", flush=True)
        print(f"report: {report}", flush=True)
        print(f"verdict: {'PASS' if gate['passed'] else 'FAIL'}", flush=True)
        for key_name, value in gate.items():
            print(f"  {key_name}: {value}", flush=True)
        npu_errors = [ln for ln in dmesg.splitlines()
                      if "wait api timeout" in ln or "bdc_reg_read" in ln]
        if npu_errors:
            print("NPU error signature in dmesg -- stop and report, do not retry:",
                  flush=True)
            for line in npu_errors[-3:]:
                print("  " + line, flush=True)
    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - a traceback is evidence too
        traceback.print_exc()
        sys.exit(2)
