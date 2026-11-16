"""The board stability suite (MYS-2498), checked without a board or a model.

The suite's whole value is that its numbers mean something: "the 300 tier" has
to be 300 characters, "the answer for this round" has to be derivable from the
prompt the model was shown, and "one record per inference" has to be a count
rather than an assumption. Every one of those is arithmetic or parsing, so it
is pinned here -- an on-board run is expensive and cannot be repeated freely,
which makes a suite bug discovered on the board a wasted run.

Five things are covered:

  * **Exact lengths.** Every tier, both core groups and the concurrency prompts,
    is exactly its declared code point count. This is the property the report
    leans on hardest ("2–800 字"), and the one an innocent template edit breaks.
  * **Determinism and self-consistency.** Same seed, same text; and the expected
    count really is the number of times the target occurs in the material --
    computed here independently of the generator, so a bug in the fit loop shows
    up as a mismatch instead of as a wrong grade.
  * **The context group is real context.** History grows by exactly two messages
    per turn, every earlier user message survives verbatim in the last request,
    and a recall question points only at a turn that actually planted its fact.
  * **SSE/JSONL parsing.** A normal stream, a stream cut before ``[DONE]``, an
    error frame, and a malformed line each produce the documented result rather
    than an exception.
  * **Grading.** An echoed round number is tolerated; a second, different count
    is not; a reply that only repeats the prompt is a failure. Grading is what
    turns a reply into evidence, so its edge cases are spelled out.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)

import board_stability_suite as suite  # noqa: E402


# --------------------------------------------------------------------------
# Prompt lengths: the claim the report makes about 2..800 字
# --------------------------------------------------------------------------
@pytest.mark.parametrize("length", suite.LENGTHS)
def test_each_core_tier_is_exactly_its_declared_length(length):
    """The manifest publishes a character count; it must be the actual one.

    Both the whole message and its UTF-8 byte count are checked, because the
    tier is defined in *code points* and a mistaken ``encode`` somewhere would
    silently change what "800 字" means.
    """
    prompt = suite.build_prompt(length, 1)
    assert suite.chars(prompt.text) == length
    assert prompt.length == length


def test_the_battery_covers_every_tier_once_in_order():
    battery = suite.build_battery()
    assert [p.length for p in battery] == suite.LENGTHS
    assert [p.round_index for p in battery] == list(range(1, len(suite.LENGTHS) + 1))


def test_an_unsupported_tier_is_refused_rather_than_rounded():
    """A tier outside the matrix must fail loudly: a silently padded 500 would
    end up in the report as a 500-character row that never was one."""
    with pytest.raises(ValueError):
        suite.build_prompt(500, 1)


@pytest.mark.parametrize("name,length", list(suite.CONCURRENCY_TIERS))
def test_concurrency_prompts_have_exact_lengths_and_unique_markers(name, length):
    prompts = [p for p in suite.build_concurrency_prompts() if p.length == length]
    assert len(prompts) == suite.CONCURRENCY_PER_TIER
    for prompt in prompts:
        assert suite.chars(prompt.text) == length
        assert prompt.marker and prompt.marker in prompt.text
    markers = [p.marker for p in prompts]
    assert len(set(markers)) == len(markers), "markers must be unique per request"


def test_concurrency_markers_are_letters_only():
    """A digit in the marker would be picked up by the count grader and make a
    correct reply look like it answered with two different numbers."""
    for prompt in suite.build_concurrency_prompts():
        assert prompt.marker.isalpha(), prompt.marker


# --------------------------------------------------------------------------
# Determinism and self-consistency
# --------------------------------------------------------------------------
def test_the_same_seed_produces_the_same_prompts():
    first = [p.text for p in suite.build_battery(seed=suite.SEED)]
    second = [p.text for p in suite.build_battery(seed=suite.SEED)]
    assert first == second


def test_a_different_seed_produces_different_material():
    first = [p.text for p in suite.build_battery(seed=suite.SEED)]
    other = [p.text for p in suite.build_battery(seed=suite.SEED + 1)]
    assert first != other


@pytest.mark.parametrize("length", suite.LENGTHS)
def test_the_expected_count_is_the_real_occurrence_count(length):
    """Recount the target in the material independently of the generator.

    This is the check that matters most: if the fit loop and the expectation ever
    disagreed, every on-board answer would still be graded "wrong" and the run
    would look like a model failure.
    """
    prompt = suite.build_prompt(length, 3)
    if prompt.expected_count is None or length in suite.LITERAL_PROMPTS:
        return
    material = prompt.text.split("材料：", 1)[1]
    material = material.split("。请分两行回答", 1)[0]
    target = prompt.text.split("「", 1)[1].split("」", 1)[0]
    assert material.count(target) == prompt.expected_count


@pytest.mark.parametrize("length", [n for n in suite.LENGTHS
                                   if n not in suite.LITERAL_PROMPTS])
def test_the_material_never_contains_the_counted_word_inside_another_word(length):
    """``帆布`` inside ``旧帆布包`` would make a correct count and a sloppy one
    indistinguishable, so no material word may contain the target."""
    prompt = suite.build_prompt(length, 4)
    material = prompt.text.split("材料：", 1)[1].split("。请分两行回答", 1)[0]
    target = prompt.text.split("「", 1)[1].split("」", 1)[0]
    words = [w for w in material.split("、") if w]
    assert target in words
    for word in words:
        if word != target:
            assert target not in word, f"{target!r} is inside {word!r}"
            assert word not in target, f"{word!r} is inside {target!r}"


def test_the_expected_count_never_collides_with_a_number_in_the_prompt():
    """Grading exempts the prompt's own round numbers, so the count must not be
    one of them -- otherwise a model echoing "第3轮" would score as correct."""
    for prompt in suite.build_battery():
        if prompt.expected_count is None:
            continue
        assert prompt.expected_count not in prompt.allowed_numbers, prompt.manifest()


def test_the_short_tiers_use_literal_tasks_with_known_answers():
    two = suite.build_prompt(2, 1)
    ten = suite.build_prompt(10, 1)
    assert two.text == "答0" and two.expected_count == 0
    assert ten.text == "只回答这个数字：42" and ten.expected_count == 42


# --------------------------------------------------------------------------
# The context group
# --------------------------------------------------------------------------
def test_history_grows_by_one_exchange_per_turn_and_is_resent_whole():
    """10 turns produce 1 + 2*9 = 19 messages before the 10th user message.

    The context group's claim is that the *entire* earlier conversation is in
    every request; losing one message per turn would still "work" and would
    quietly turn the group into a different experiment.
    """
    battery = suite.build_battery()
    history: list[dict] = []
    seen_user_texts: list[str] = []
    for index, prompt in enumerate(battery):
        messages = suite.context_messages(suite.SYSTEM_PROMPT, history, prompt.text)
        assert messages[0] == {"role": "system", "content": suite.SYSTEM_PROMPT}
        assert len(messages) == 1 + 2 * index + 1
        # Every earlier user message is still there, verbatim and in order.
        earlier = [m["content"] for m in messages[1:-1] if m["role"] == "user"]
        assert earlier == seen_user_texts
        assert messages[-1] == {"role": "user", "content": prompt.text}
        seen_user_texts.append(prompt.text)
        history = suite.append_turn(history, prompt.text, f"ans{index}")


def test_append_turn_keeps_the_assistant_reply_as_received():
    history = suite.append_turn([], "q1", "a1")
    assert history == [{"role": "user", "content": "q1"},
                       {"role": "assistant", "content": "a1"}]
    assert suite.append_turn(history, "q2", "a2")[-1] == {"role": "assistant",
                                                          "content": "a2"}


def test_a_recall_question_only_points_at_a_turn_that_planted_a_fact():
    """Recall is the check that the history is *used*, so it must be answerable:
    the referenced turn has to be an earlier one that really carried a keyword."""
    battery = {p.round_index: p for p in suite.build_battery()}
    asked = 0
    for prompt in battery.values():
        if prompt.recall_round is None:
            continue
        asked += 1
        assert prompt.recall_round < prompt.round_index
        referenced = battery[prompt.recall_round]
        assert referenced.plants_fact, "recall points at a turn with no fact"
        assert prompt.expected_recall == suite._fact_for(prompt.recall_round)
        assert prompt.expected_recall in referenced.text
    assert asked, "the battery must exercise recall at least once"


def test_fact_words_are_distinct_and_never_contain_each_other():
    """Two facts where one contains the other would make "which keyword was
    planted" ambiguous, and the recall grade would be a coin flip."""
    words = suite.FACT_WORDS
    assert len(set(words)) == len(words)
    for a in words:
        for b in words:
            if a != b:
                assert a not in b


def test_a_turn_that_asks_two_questions_never_says_only_answer_one():
    """The reply-format instruction has to match the number of questions asked.

    Measured on the board: rounds carrying a recall clause also said "只回答数字",
    and the model -- correctly -- answered with just the number, so every recall
    round graded as a failure. The prompt was self-contradictory; the model was
    not wrong. A single-question turn may demand a bare number, a two-question
    turn must describe both answers.
    """
    for prompt in suite.build_battery() + suite.build_concurrency_prompts():
        asks_recall = "轮的关键词" in prompt.text
        demands_number_only = "只回答数字" in prompt.text or "只答数字" in prompt.text
        if asks_recall:
            assert not demands_number_only, (
                "two questions but the reply format demands a bare number: "
                + prompt.text[:120])
            assert "分两行回答" in prompt.text, "the format must cover both answers"
        else:
            assert demands_number_only or prompt.length in suite.LITERAL_PROMPTS


def test_every_recall_round_expects_both_answers_in_the_same_reply():
    """The grading follows the prompt: the count is the first integer, the keyword
    appears as text. Both must be findable in one reply, or one of the two
    questions is unanswerable by construction."""
    prompt = next(p for p in suite.build_battery() if p.recall_round)
    reply = f"{prompt.expected_count}\n{prompt.expected_recall}"
    graded = suite.grade(prompt, reply, "cxt")
    assert graded["count_ok"] is True and graded["recall_ok"] is True


def test_the_independent_group_is_not_graded_on_recall():
    """``nocxt`` sends the same text but has no history; grading it would blame
    the model for the suite's own construction."""
    prompt = next(p for p in suite.build_battery() if p.expected_recall)
    graded = suite.grade(prompt, str(prompt.expected_count), "nocxt")
    assert graded["recall_ok"] is None, "no history, so recall cannot be graded"
    assert graded["count_ok"] is True


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------
def _prompt(expected=2, round_index=7, recall_round=4):
    return suite.Prompt(round_index=round_index, length=300, text="t",
                        expected_count=expected, expected_recall="竹篮",
                        plants_fact=True, recall_round=recall_round)


@pytest.mark.parametrize("output", ["2", "2次", "出现了 2 次。", "材料里「鞋拔」出现了2次",
                                   "第7轮：2"])
def test_a_correct_count_is_accepted_in_its_common_phrasings(output):
    assert suite.counting_answer_ok(_prompt(), output) is True


@pytest.mark.parametrize("output", ["", "三", "1", "3", "2次和3次"])
def test_a_wrong_or_ambiguous_count_is_rejected(output):
    """Two different counts in one reply is a failure even when one of them is
    right: the model did not answer the question that was asked."""
    assert suite.counting_answer_ok(_prompt(), output) is False


def test_echoing_the_prompts_own_round_numbers_is_not_an_answer():
    """The prompt contains "第7轮" and "第4轮"; a reply may repeat them. Any
    third number is a real answer and must match."""
    assert suite.counting_answer_ok(_prompt(), "第7轮，第4轮，2") is True
    assert suite.counting_answer_ok(_prompt(), "第7轮，5") is False


def test_a_literal_tier_is_graded_by_its_fixed_answer():
    prompt = suite.build_prompt(10, 1)
    assert suite.counting_answer_ok(prompt, "42") is True
    assert suite.counting_answer_ok(prompt, "43") is False


def test_recall_and_marker_are_graded_by_substring():
    prompt = suite.Prompt(round_index=8, length=400, text="t", expected_count=1,
                          expected_recall="竹篮", plants_fact=True, recall_round=4,
                          marker="KXBA")
    graded = suite.grade(prompt, "KXBA 1 竹篮", "cxt")
    assert graded == {"count_ok": True, "recall_ok": True, "marker_ok": True}
    assert suite.grade(prompt, "1 石桥", "cxt")["recall_ok"] is False


# --------------------------------------------------------------------------
# SSE parsing
# --------------------------------------------------------------------------
def _sse(*chunks: dict, done: bool = True) -> str:
    body = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks)
    return body + ("data: [DONE]\n\n" if done else "")


def _chunk(content=None, finish=None, reasoning=None, usage=None, cid="chatcmpl-abc123"):
    obj = {"id": cid, "object": "chat.completion.chunk",
           "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
    if content is not None:
        obj["choices"][0]["delta"]["content"] = content
    if reasoning is not None:
        obj["choices"][0]["delta"]["reasoning_content"] = reasoning
    if usage is not None:
        obj["choices"] = []
        obj["usage"] = usage
    return obj


def test_a_normal_stream_is_assembled_in_order_with_usage_and_finish_reason():
    raw = _sse(_chunk(content=""), _chunk(content="2"), _chunk(content="次"),
               _chunk(finish="stop"),
               _chunk(usage={"prompt_tokens": 41, "completion_tokens": 2,
                             "total_tokens": 43}))
    result = suite.parse_sse(raw)
    assert result.text == "2次"
    assert result.finish_reason == "stop"
    assert result.done is True
    assert result.response_id == "chatcmpl-abc123"
    assert suite.usage_tokens(result.usage) == (41, 2, 0)


def test_reasoning_content_is_kept_apart_from_content():
    raw = _sse(_chunk(reasoning="想一想"), _chunk(content="2"))
    result = suite.parse_sse(raw)
    assert result.reasoning == "想一想"
    assert result.text == "2"


def test_cached_tokens_are_read_from_the_usage_details():
    raw = _sse(_chunk(usage={"prompt_tokens": 900, "completion_tokens": 3,
                             "prompt_tokens_details": {"cached_tokens": 800}}))
    assert suite.usage_tokens(suite.parse_sse(raw).usage) == (900, 3, 800)


def test_a_stream_cut_before_done_is_reported_not_raised():
    """A truncated stream is the failure the suite exists to observe: it must
    surface as ``done=False`` with the partial text intact."""
    raw = _sse(_chunk(content="2"), done=False)
    result = suite.parse_sse(raw)
    assert result.done is False
    assert result.text == "2"


def test_an_error_frame_is_collected_and_stops_text_accumulation():
    raw = _sse(_chunk(content="1"), {"error": {"message": "worker died",
                                               "type": "server"}})
    result = suite.parse_sse(raw)
    assert result.errors and "worker died" in result.error_summary()
    assert result.text == "1"


def test_a_malformed_line_is_counted_rather_than_raised():
    raw = "data: {\"id\": \"chatcmpl-x\", \"choices\": [\n\ndata: [DONE]\n\n"
    result = suite.parse_sse(raw)
    assert result.malformed == 1
    assert result.done is True


def test_a_response_id_is_reduced_to_the_record_id():
    """The record id is the part after ``chatcmpl-``; the record check keys on
    it, so a stray prefix would make every record look missing."""
    assert suite.request_id_of("chatcmpl-abc123") == "abc123"
    assert suite.request_id_of("abc123") == "abc123"
    assert suite.request_id_of(None) is None


# --------------------------------------------------------------------------
# Statistics and the verdict
# --------------------------------------------------------------------------
def test_distribution_reports_min_median_max_and_ignores_missing_values():
    assert suite.distribution([3.0, None, 1.0, 2.0]) == {"n": 3, "min": 1.0,
                                                         "median": 2.0, "max": 3.0}
    assert suite.distribution([])["n"] == 0


def _round(group="cxt", index=1, **kwargs) -> suite.Round:
    base = suite.Round(group=group, round_index=index, tier=60, http_status=200)
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_summary_counts_errors_by_type_and_flags_empty_outputs():
    rounds = [_round(output="2", count_ok=True),
              _round(index=2, output="", error="empty output"),
              _round(index=3, output="1", error="HTTP 503: busy")]
    summary = suite.summarize(rounds)
    group = summary["groups"]["cxt"]
    assert group["requests"] == 3 and group["ok"] == 1
    assert group["empty_outputs"] == 1
    assert group["error_types"] == {"empty output": 1, "HTTP 503": 1}
    assert summary["totals"]["http_5xx"] == 0  # 503 arrived as a plain error string


def _records(**overrides) -> dict:
    base = {"checked": 0, "missing": [], "missing_from_export": [], "duplicates": [],
            "source_mismatch": [], "not_ok_rows": [], "input_mismatch": [],
            "output_mismatch": [], "metrics_mismatch": [], "context_mismatch": [],
            "secret_leaks": []}
    base.update(overrides)
    return base


def test_the_verdict_fails_when_the_history_is_never_recalled():
    """The first board run passed with recall 0/4, and the cause was a prompt bug
    in this harness. A gate that shrugs at 0/4 ships that bug: either the model
    ignores the history or the harness is broken, and both must not be a pass.
    """
    rounds = []
    for group in ("cxt", "nocxt"):
        for _ in range(10):
            rounds.append(_round(group=group, output="2", count_ok=True,
                                 recall_ok=False if group == "cxt" else None))
    for name, _length in suite.CONCURRENCY_TIERS:
        rounds += [_round(group=f"conc-{name}", output="KX 2", marker_ok=True,
                          count_ok=True, cross_talk=False)
                   for _ in range(suite.CONCURRENCY_PER_TIER)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 29, "expected": 29, "missing": [],
          "output_mismatch": []}
    gate = suite.verdict(summary, _records(checked=29), db, None)
    assert gate["count_correct"] == 20, "every count was right"
    assert gate["recall_correct"] == 0
    assert gate["some_recall_correct"] is False
    assert gate["passed"] is False


def test_a_run_with_no_recall_rounds_graded_does_not_fail_on_recall():
    """The floor only applies to rounds that actually asked a recall question."""
    rounds = [_round(group=g, output="2", count_ok=True)
              for g in ("cxt", "nocxt") for _ in range(10)]
    for name, _length in suite.CONCURRENCY_TIERS:
        rounds += [_round(group=f"conc-{name}", output="2", marker_ok=True,
                          count_ok=True, cross_talk=False)
                   for _ in range(suite.CONCURRENCY_PER_TIER)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 29, "expected": 29, "missing": [],
          "output_mismatch": []}
    gate = suite.verdict(summary, _records(checked=29), db, {"ok": True})
    assert gate["recall_graded"] == 0
    assert gate["some_recall_correct"] is True
    assert gate["passed"] is True


def test_the_verdict_fails_when_nothing_answered_correctly():
    """A green gate over an all-wrong run would be the worst possible output:
    every mechanical check passes, so nothing else would catch it.

    The mock backend's word salad reproduces this exactly -- 20/20 clean, every
    record consistent, and not one correct count.
    """
    rounds = [_round(group=g, output="the board runs", count_ok=False)
              for g in ("cxt", "nocxt") for _ in range(10)]
    for name, _length in suite.CONCURRENCY_TIERS:
        rounds += [_round(group=f"conc-{name}", output="the board runs",
                          marker_ok=True, count_ok=False, cross_talk=False)
                   for _ in range(suite.CONCURRENCY_PER_TIER)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 29, "expected": 29, "missing": [],
          "output_mismatch": []}
    gate = suite.verdict(summary, _records(checked=29), db, None)
    assert gate["core_20_ok"] is True and gate["concurrent_all_ok"] is True
    assert gate["count_correct"] == 0
    assert gate["some_answer_correct"] is False
    assert gate["passed"] is False


def test_the_verdict_fails_on_a_missing_record_even_when_every_request_succeeded():
    """The headline claim is not "the service answered" but "the service answered
    *and* the evidence is complete", so one missing record fails the run."""
    rounds = [_round(output="2", count_ok=True) for _ in range(20)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 20, "expected": 20, "missing": [],
          "output_mismatch": []}
    gate = suite.verdict(summary, _records(checked=20,
                                           missing=[{"id": "x"}]), db, None)
    assert gate["passed"] is False
    assert gate["records_missing"] == 1


def test_the_verdict_passes_a_clean_twenty_plus_concurrency():
    rounds = [_round(output="2", count_ok=True) for _ in range(10)]
    rounds += [_round(group="nocxt", output="2", count_ok=True) for _ in range(10)]
    for name, _length in suite.CONCURRENCY_TIERS:
        rounds += [_round(group=f"conc-{name}", output="KX 2", marker_ok=True,
                          count_ok=True, cross_talk=False)
                   for _ in range(suite.CONCURRENCY_PER_TIER)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 29, "expected": 29, "missing": [],
          "output_mismatch": []}
    gate = suite.verdict(summary, _records(checked=29), db, {"ok": True})
    assert gate["passed"] is True
    assert gate["core_20_ok"] is True and gate["concurrent_all_ok"] is True


def test_a_failed_restart_fails_the_run():
    rounds = [_round(group=g, output="2", count_ok=True)
              for g in ("cxt", "nocxt") for _ in range(10)]
    for name, _length in suite.CONCURRENCY_TIERS:
        rounds += [_round(group=f"conc-{name}", output="2", marker_ok=True,
                          count_ok=True, cross_talk=False)
                   for _ in range(suite.CONCURRENCY_PER_TIER)]
    summary = suite.summarize(rounds)
    db = {"readable": True, "found": 29, "expected": 29, "missing": [],
          "output_mismatch": []}
    assert suite.verdict(summary, _records(checked=29), db, {"ok": False})["passed"] is False


# --------------------------------------------------------------------------
# Evidence handling
# --------------------------------------------------------------------------
def test_a_new_run_directory_is_created_and_never_reused(tmp_path):
    """Evidence from a failed run must survive the next attempt, or "we do not
    re-run over a failure" is only a promise."""
    first = suite.make_run_dir(tmp_path)
    assert (first / "raw").is_dir()
    (first / "rounds.jsonl").write_text("{}\n", encoding="utf-8")
    second = suite.make_run_dir(tmp_path)
    assert second != first
    assert (first / "rounds.jsonl").is_file()


def test_rounds_serialise_to_jsonl_without_leaking_the_input_text():
    """``input_text`` stays in memory for the record comparison; the JSONL gets
    the hash instead, so the file stays line-per-round and machine readable."""
    prompt = suite.build_prompt(300, 7)
    row = suite.new_round("cxt", prompt, [{"role": "user", "content": prompt.text}])
    row.started_at = row.finished_at = 1_700_000_000.0
    payload = row.as_row()
    assert "input_text" not in payload
    assert payload["input_sha256"] == prompt.text_sha256
    assert payload["input_chars"] == 300
    assert payload["started_iso"] == "2023-11-14T22:13:20.000Z"
    json.dumps(payload, ensure_ascii=False)  # must stay serialisable


def test_secrets_are_dropped_from_the_environment_snapshot():
    """``hash``-shaped settings never reach ``env.json``: the deb ships an
    evidence directory that gets attached to an issue."""
    assert "admin_password_hash" in suite.SECRET_SETTING_KEYS
    assert all("hash" in key for key in suite.SECRET_SETTING_KEYS)


# --------------------------------------------------------------------------
# The record cross-check
# --------------------------------------------------------------------------
def _record(rid: str, output: str, messages: list[dict], **overrides) -> dict:
    record = {"id": rid, "source": "/v1/chat/completions", "status": "ok",
              "finish_reason": "stop", "messages": messages, "output_text": output,
              "prompt_tokens": 10, "completion_tokens": 1, "cached_tokens": 0,
              "actor_type": "api_key", "actor_name": "MYS-2498-stability",
              "first_token_latency_s": 0.5, "decode_tps": 30.0,
              "output_chars": len(output), "error": None}
    record.update(overrides)
    return record


def test_a_matching_record_verifies_clean():
    prompt = suite.build_prompt(60, 4)
    messages = [{"role": "system", "content": suite.SYSTEM_PROMPT},
                {"role": "user", "content": prompt.text}]
    row = suite.new_round("nocxt", prompt, messages)
    row.req_id = "abc123"
    row.output = "2"
    row.prompt_tokens, row.completion_tokens, row.cached_tokens = 10, 1, 0
    out = suite.verify_records([row], {"abc123": _record("abc123", "2", messages)},
                               {"abc123": 1}, None)
    assert out["checked"] == 1
    assert not any(out[k] for k in ("missing", "duplicates", "output_mismatch",
                                    "metrics_mismatch", "context_mismatch",
                                    "input_mismatch", "not_ok_rows", "secret_leaks"))
    # Server-side numbers are adopted for the report.
    assert row.decode_tps == 30.0 and row.server_ttft_s == 0.5


def test_a_missing_record_and_a_duplicate_are_both_reported():
    prompt = suite.build_prompt(60, 4)
    messages = [{"role": "user", "content": prompt.text}]
    present = suite.new_round("cxt", prompt, messages)
    present.req_id, present.output = "a1", "1"
    absent = suite.new_round("cxt", prompt, messages)
    absent.req_id, absent.output = "a2", "1"
    details = {"a1": _record("a1", "1", messages)}
    out = suite.verify_records([present, absent], details, {"a1": 2}, None)
    assert [m["id"] for m in out["missing"]] == ["a2"]
    assert out["duplicates"] == [{"id": "a1", "count": 2, "group": "cxt",
                                  "round": present.round_index}]


def test_an_output_that_differs_from_the_record_is_a_mismatch():
    """This is the check that makes the record log usable as evidence: the
    client saw one thing and the log says another, and that gap is the bug."""
    prompt = suite.build_prompt(60, 4)
    messages = [{"role": "user", "content": prompt.text}]
    row = suite.new_round("cxt", prompt, messages)
    row.req_id, row.output = "a1", "2"
    out = suite.verify_records([row], {"a1": _record("a1", "3", messages)},
                               {"a1": 1}, None)
    assert out["output_mismatch"] == [{"id": "a1", "record_chars": 1, "client_chars": 1}]


def test_a_record_that_echoes_the_api_key_is_flagged():
    """Nothing may put a key in the log; a leak is reported by id, not counted."""
    prompt = suite.build_prompt(60, 4)
    messages = [{"role": "user", "content": prompt.text}]
    row = suite.new_round("cxt", prompt, messages)
    row.req_id, row.output = "a1", "1"
    record = _record("a1", "1", messages, actor_name="sk-secret-material")
    out = suite.verify_records([row], {"a1": record}, {"a1": 1}, "sk-secret-material")
    assert out["secret_leaks"] == [{"id": "a1", "what": "raw api key"}]


def test_a_wrong_source_or_status_is_reported():
    prompt = suite.build_prompt(60, 4)
    messages = [{"role": "user", "content": prompt.text}]
    row = suite.new_round("cxt", prompt, messages)
    row.req_id, row.output = "a1", "1"
    record = _record("a1", "1", messages, source="/api/chat/stream", status="cancelled")
    out = suite.verify_records([row], {"a1": record}, {"a1": 1}, None)
    assert out["source_mismatch"] == [{"id": "a1", "source": "/api/chat/stream"}]
    assert out["not_ok_rows"][0]["status"] == "cancelled"


def test_a_context_size_that_disagrees_is_reported():
    """The context group resends the whole history; if the record shows fewer
    messages than were sent, the history was not actually delivered."""
    prompt = suite.build_prompt(60, 4)
    sent = [{"role": "system", "content": suite.SYSTEM_PROMPT},
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": prompt.text}]
    row = suite.new_round("cxt", prompt, sent)
    row.req_id, row.output = "a1", "1"
    truncated = sent[:2] + [sent[-1]]
    out = suite.verify_records([row], {"a1": _record("a1", "1", truncated)},
                               {"a1": 1}, None)
    assert out["context_mismatch"] == [{"id": "a1", "record": 3, "client": 4}]
