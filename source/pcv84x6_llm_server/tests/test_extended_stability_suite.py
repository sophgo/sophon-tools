"""The extended stability suite (MYS-2501), checked without a board or a model.

The suite's numbers have to mean something before it is pointed at a board: a run
of 2100 requests on a 128k model takes hours, so a harness bug found on the board
is a wasted run and a report nobody can trust. Everything here is arithmetic,
parsing or string building, which is exactly the part that can be pinned on a
laptop.

Covered:

  * **The matrix adds up.** 12 tiers, 84/84/84/84 then 83 x 8, summing to 1000
    per core group; 100 sessions x 10 turns; 2 lanes x 50 rounds. A typo here
    would become a false claim in the report's headline.
  * **Every prompt is exactly its declared length**, in all 1000 no-context
    requests and all 1000 context turns, and the two core groups really do send
    the same new input turn-for-turn.
  * **The context group is 100 conversations, not one 1000-turn conversation.**
    History grows within a session and resets between sessions, each session's
    material is distinct, and the recall question always points at the turn
    immediately before it.
  * **The readiness phase is judged correctly in both directions**: a run where
    the model admitted a request during the load, wrote a record, or never showed
    ``loading`` must fail, and one where every attempt was refused and the model
    served afterwards must pass.
  * **The HTML report is self-contained and inert.** No external URL of any
    kind, and a model output containing ``<script>`` survives only as text.
  * **The old report still works.** The MYS-2498 suite's report generation is
    re-run here to prove this change did not disturb it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))

import board_stability_suite as base  # noqa: E402
import extended_stability_suite as ext  # noqa: E402


# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------
def test_the_tier_plan_is_exactly_the_requested_split():
    """84 for the four shortest tiers, 83 for the rest, 1000 in total.

    This is the one number the report leads with, so it is asserted as a literal
    rather than "sums to something".
    """
    plan = dict(ext.tier_plan())
    assert [length for length, _count in ext.tier_plan()] == ext.TIERS
    for index, length in enumerate(ext.TIERS):
        expected = 84 if index < 4 else 83
        assert plan[length] == expected, (length, plan[length], expected)
    assert ext.core_total() == 1000


def test_the_tiers_extend_the_old_matrix_to_1200():
    """MYS-2498's ten tiers are a prefix, and the two new tiers are the longest.

    The context group reuses the old ladder, so a changed prefix would silently
    move a turn's expected prompt tokens.
    """
    assert ext.TIERS[:len(base.LENGTHS)] == base.LENGTHS
    assert ext.TIERS[-2:] == [1000, 1200]


def test_the_no_context_order_sends_every_tier_its_declared_number_of_times():
    order = ext.nocxt_plan()
    assert len(order) == 1000
    assert ext.tier_counts(order) == dict(ext.tier_plan())


def test_the_tiered_and_cycled_orders_send_the_same_requests():
    """Two orders, one set: the order is a presentation choice, not a matrix
    change. If they diverged, a run's readability option would change its data.
    """
    assert (ext.tier_counts(ext.nocxt_plan("cycle"))
            == ext.tier_counts(ext.nocxt_plan("tiered")))
    assert ext.nocxt_plan("tiered") != ext.nocxt_plan("cycle")


def test_an_unknown_order_is_refused():
    with pytest.raises(ValueError):
        ext.nocxt_plan("random")


def test_the_context_plan_is_100_sessions_of_10_turns():
    plan = ext.context_session_plan()
    assert len(plan) == 100
    assert all(len(ladder) == 10 for ladder in plan)
    assert sum(len(ladder) for ladder in plan) == 1000
    # Every session walks the same ladder, in the same order.
    assert all(ladder == plan[0] for ladder in plan)


def test_the_context_ladder_is_the_first_ten_tiers():
    """The long tiers are no-context only: a session reaching 1200 would make
    every later turn a 100k-token prefill and measure the prefill path instead.
    """
    assert ext.context_session_plan()[0] == ext.TIERS[:10]


# --------------------------------------------------------------------------
# Prompt lengths, in every group
# --------------------------------------------------------------------------
def test_every_no_context_prompt_is_exactly_its_declared_length():
    for length, index in zip(ext.nocxt_plan(), range(1, 1001)):
        turn = (index - 1) % len(ext.TIERS) + 1
        prompt = base.build_prompt(length, turn, lengths=ext.TIERS,
                                   recall_target="previous",
                                   variant=(index - 1) // len(ext.TIERS) + 1,
                                   allow_recall=turn <= ext.CONTEXT_TURNS)
        assert base.chars(prompt.text) == length, (index, length, prompt.text[:40])


def test_every_context_prompt_is_exactly_its_declared_length():
    for session_index, ladder in enumerate(ext.context_session_plan(), start=1):
        for turn, length in enumerate(ladder, start=1):
            prompt = base.build_prompt(length, turn, lengths=ladder,
                                       recall_target="previous",
                                       variant=session_index)
            assert base.chars(prompt.text) == length


def test_the_two_core_groups_send_the_same_new_input_for_the_first_ten_requests():
    """"两组使用相同的新输入" has to be checkable, not approximate.

    Request `i` of a no-context cycle must be byte-identical to turn `i` of any
    context session, so the only difference between the groups is the history.
    """
    session = ext.context_session_plan()[0]
    for index in range(10):
        length = session[index]
        turn = index + 1
        nocxt = base.build_prompt(length, turn, lengths=ext.TIERS,
                                  recall_target="previous", variant=1,
                                  allow_recall=turn <= ext.CONTEXT_TURNS)
        cxt = base.build_prompt(length, turn, lengths=session,
                                recall_target="previous", variant=1)
        assert nocxt.text == cxt.text, index


# --------------------------------------------------------------------------
# The context group is 100 conversations
# --------------------------------------------------------------------------
def test_history_is_rebuilt_per_session_and_resent_whole():
    """Each session grows 1 -> 19 messages and then starts over.

    The MYS-2501 report must not be able to claim "1000 rounds of one
    conversation": the history resets at every session boundary.
    """
    ladder = ext.context_session_plan()[0]
    history: list[dict] = []
    counts: list[int] = []
    for turn, length in enumerate(ladder, start=1):
        messages = base.context_messages(ext.SYSTEM_PROMPT, history, "x" * length)
        counts.append(len(messages))
        history = base.append_turn(history, "x" * length, "2")
    assert counts == [2 + 2 * i for i in range(10)]
    # A new session starts from nothing.
    assert len(base.context_messages(ext.SYSTEM_PROMPT, [], "x")) == 2


def test_each_session_gets_its_own_material():
    """100 sessions sharing one text per turn would be one cached prefix sent
    100 times, not 100 independent conversations."""
    texts = {s[6]["text"] for s in ext.build_manifest("m", base.SEED)["cxt"]}
    assert len(texts) == 100


def test_the_recall_question_always_points_at_the_previous_turn():
    for session in ext.build_manifest("m", base.SEED)["cxt"][:5]:
        for turn_index, turn in enumerate(session, start=1):
            if turn["expected_recall"] is None:
                continue
            assert turn["recall_round"] == turn_index - 1, turn


def test_recall_starts_only_where_a_fact_was_planted():
    """The 2/10/30/60 tiers cannot hold a numbered fact *and* a word list, so a
    recall clause there would ask about a turn that planted nothing."""
    session = ext.build_manifest("m", base.SEED)["cxt"][0]
    for index, turn in enumerate(session):
        if turn["expected_recall"] is None:
            continue
        assert index >= 1, "turn 1 has no previous turn to ask about"
        assert session[index - 1]["plants_fact"] is True
        assert turn["expected_recall"] == session[index - 1]["text"].split(
            "关键词：", 1)[1].split("。", 1)[0]


def test_a_no_context_request_never_asks_about_a_turn_it_does_not_carry():
    """The 1000/1200 tiers sit past the last turn of any real conversation, so a
    recall clause there is unanswerable -- and an unanswerable question invites
    an extra digit into the reply the count grader then has to reject."""
    manifest = ext.build_manifest("m", base.SEED)
    for entry in manifest["nocxt"]:
        if entry["length"] in (1000, 1200):
            assert entry["expected_recall"] is None, entry["round"]
    # The first ten positions of a cycle do carry the clause, because there they
    # mirror a real turn of a real session.
    assert any(entry["expected_recall"] for entry in manifest["nocxt"][:10])


def test_the_no_context_group_reuses_twelve_texts_per_tier_not_one():
    """Without a variant, 1000 requests would be 12 texts sent 83 times each and
    the prefix cache would answer almost all of them for free."""
    entries = [e for e in ext.build_manifest("m", base.SEED)["nocxt"]
               if e["length"] not in base.LITERAL_PROMPTS]
    assert len({e["text"] for e in entries}) > 800


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------
def test_the_concurrency_plan_is_two_lanes_by_fifty_rounds():
    assert ext.CONCURRENCY_LANES * ext.CONCURRENCY_ROUNDS == 100
    assert len(ext.build_manifest("m", base.SEED)["concurrency"]) == 100


def test_concurrency_markers_are_unique_per_request_and_letters_only():
    """A repeated marker is a guaranteed false cross-talk positive; a digit in a
    marker collides with the counted answer."""
    entries = ext.build_manifest("m", base.SEED)["concurrency"]
    markers = [(e["round"], e["lane"], e["marker"]) for e in entries]
    assert len({m for _r, _l, m in markers}) == len(markers), "markers must be unique"
    for _r, _l, marker in markers:
        assert marker.isalpha(), marker


def test_concurrency_prompts_are_exactly_their_tier_length():
    for entry in ext.build_manifest("m", base.SEED)["concurrency"]:
        assert entry["chars"] == entry["length"] == len(entry["text"])


def test_the_readiness_probe_prompt_is_buildable():
    """Regression: the board run died here.

    The probe used to number its rounds 900+ so they would not collide with the
    core groups' round indices. On a 30-character prompt the head ("第901轮。" plus
    the ask and the 材料: label) leaves no room for a material list, and the
    generator rightly refused -- which aborted the whole readiness phase and left
    318 correctly-refused attempts with no analysis. The tier and the round index
    are now fixed constants, and this asserts they actually build.
    """
    prompt = base.build_prompt(ext.READINESS_TIER, ext.READINESS_ROUND,
                               lengths=ext.TIERS)
    assert base.chars(prompt.text) == ext.READINESS_TIER
    assert prompt.expected_count is not None


@pytest.mark.parametrize("round_index", [1, 2, 9, 10])
def test_every_tier_is_buildable_at_every_short_round_index(round_index):
    """The same class of bug, swept: a tier that builds at round 1 must build at
    any round index the groups actually use, or a run dies hours in."""
    for length in ext.TIERS:
        prompt = base.build_prompt(length, round_index, lengths=ext.TIERS,
                                   recall_target="previous")
        assert base.chars(prompt.text) == length, (length, round_index)


def test_a_tier_whose_head_cannot_fit_is_refused_rather_than_padded():
    """When even the head does not fit, the generator refuses instead of emitting
    a wrong-length prompt: the tier's length is what the whole report rests on.

    A round index of 10**9 makes "第1000000000轮。" plus the ask longer than 30
    characters, so there is no material room at all -- a genuinely impossible
    request, as opposed to the merely-tight one a shorter target can still fill.
    """
    with pytest.raises(ValueError):
        base.build_prompt(30, 10 ** 9, lengths=ext.TIERS)


def test_a_tight_tier_retries_a_shorter_target_instead_of_giving_up():
    """The bug the board found.

    A tier-30 prompt with a four-digit round number leaves 4 characters of
    material. A three-character fact word has no exact fit there at one copy (3)
    or two (7), so the first target can fail outright -- and the fallback used to
    recompute nothing, reusing the *original* target's room budget and therefore
    failing every shorter alternative too. It now recomputes the room per target.

    Round 1007 is the concrete case: the drawn target is 青苹果 (3 chars) and the
    prompt must still build, at exactly 30 characters, with a truthful count.
    """
    prompt = base.build_prompt(30, 1007, lengths=ext.TIERS)
    assert base.chars(prompt.text) == 30
    material = prompt.text.split("材料：", 1)[1]
    target = prompt.text.split("「", 1)[1].split("」", 1)[0]
    assert material.count(target) == prompt.expected_count


def test_every_round_of_a_high_numbered_probe_builds():
    """The readiness probe numbered its rounds past 900 and died on one of them
    hours into a board run. Sweep the whole band so a later refactor cannot
    reintroduce a round-dependent failure."""
    for round_index in range(901, 1901):
        prompt = base.build_prompt(30, round_index, lengths=ext.TIERS)
        assert base.chars(prompt.text) == 30, round_index


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def test_spread_reports_min_median_p95_and_max():
    out = ext.spread([1.0, 2.0, 3.0, 4.0, 5.0])
    assert out["n"] == 5
    assert out["min"] == 1.0 and out["max"] == 5.0
    assert out["median"] == 3.0
    assert out["p95"] == pytest.approx(4.8)


def test_spread_ignores_missing_values_rather_than_counting_them_as_zero():
    """A failed request has no latency; averaging it in as 0 would make the run
    look faster the more requests failed."""
    out = ext.spread([None, 2.0, None, 4.0])
    assert out["n"] == 2 and out["min"] == 2.0 and out["max"] == 4.0


def test_spread_of_nothing_is_none_not_zero():
    out = ext.spread([])
    assert out == {"n": 0, "min": None, "median": None, "p95": None, "max": None}


def test_percentile_matches_the_linear_interpolation_definition():
    values = [10, 20, 30, 40]
    assert ext.percentile(values, 0.5) == pytest.approx(25.0)
    assert ext.percentile(values, 0.95) == pytest.approx(38.5)
    assert ext.percentile([7], 0.95) == 7.0
    assert ext.percentile([], 0.95) is None


# --------------------------------------------------------------------------
# Summary and verdict
# --------------------------------------------------------------------------
def _round(group="nocxt", index=1, tier=60, status=200, **kw) -> ext.Round:
    row = ext.Round(group=group, round_index=index, tier=tier, http_status=status)
    row.status_ok = kw.pop("status_ok", status == 200)
    row.expected_status = kw.pop("expected_status", 200)
    for key, value in kw.items():
        setattr(row, key, value)
    return row


def _full_core(recall_ok=8):
    """2000 core rounds, all successful, with the real tier counts."""
    rows: list[ext.Round] = []
    for index, length in enumerate(ext.nocxt_plan(), start=1):
        rows.append(_round(group="nocxt", index=index, tier=length, output="2",
                           count_ok=True, total_s=1.0, ttft_s=0.5))
    for session in range(1, 101):
        for turn in range(1, 11):
            rows.append(_round(group="cxt", tier=ext.TIERS[turn - 1],
                               output="2", count_ok=True, total_s=2.0,
                               ttft_s=1.0, session=session, turn=turn,
                               recall_ok=(turn <= recall_ok if turn >= 7 else None)))
    return rows


def _records(**overrides) -> dict:
    data = {"checked": 0, "missing": [], "missing_from_export": [], "duplicates": [],
            "source_mismatch": [], "not_ok_rows": [], "input_mismatch": [],
            "output_mismatch": [], "metrics_mismatch": [], "context_mismatch": [],
            "secret_leaks": []}
    data.update(overrides)
    return data


def _readiness(**overrides) -> dict:
    """A readiness phase where the gate held: every attempt refused, then served."""
    data = {
        "attempts": 120,
        "by_surface": {
            "stream": {"attempts": 40, "refused": 40, "admitted": 0,
                       "other": 0, "records": 0},
            "nonstream": {"attempts": 40, "refused": 40, "admitted": 0,
                          "other": 0, "records": 0},
            "console": {"attempts": 40, "refused": 40, "admitted": 0,
                        "other": 0, "records": 0},
        },
        "observed_loading": True,
        "generate_after_load": 0,
        "records_delta_loading": 0,
        "after": {"http": 200, "req_id": "abc123", "records_delta": 1},
    }
    data.update(overrides)
    return data


def _summary_with(rows, readiness=None):
    return ext.summarize(rows, readiness)


def _concurrency_rows(cross_talk_round: int | None = None):
    """The 2 x 50 concurrency group, all successful unless asked otherwise."""
    rows: list[ext.Round] = []
    for round_index in range(1, ext.CONCURRENCY_ROUNDS + 1):
        for lane in range(1, ext.CONCURRENCY_LANES + 1):
            rows.append(_round(
                group="conc", index=1000 + round_index * 10 + lane, lane=lane,
                output="KX 2", marker_ok=True, count_ok=True,
                total_s=3.0, ttft_s=2.0,
                cross_talk=(cross_talk_round == round_index and lane == 1)))
    return rows


def _clean_run(rows=None, with_concurrency=True, **readiness_overrides):
    rows = list(rows) if rows is not None else _full_core()
    if with_concurrency and not any(r.group == "conc" for r in rows):
        rows += _concurrency_rows()
    summary = ext.summarize(rows, _readiness(**readiness_overrides))
    db = {"readable": True, "found": 2100, "expected": 2100, "missing": [],
          "output_mismatch": []}
    return summary, ext.verdict(summary, _records(checked=2100), db,
                                summary.get("readiness"))


def test_a_clean_run_passes():
    summary, gate = _clean_run()
    assert gate["passed"] is True, gate
    assert gate["core_ok_requests"] == 2000
    assert gate["readiness_refused"] == 120


def test_a_request_admitted_during_the_load_fails_the_run():
    """The whole point of the readiness phase: one request that got in while the
    model was loading is a failure, however few they are."""
    summary, gate = _clean_run(by_surface={
        "stream": {"attempts": 40, "refused": 39, "admitted": 1, "other": 0,
                   "records": 0},
        "nonstream": {"attempts": 40, "refused": 40, "admitted": 0, "other": 0,
                      "records": 0},
        "console": {"attempts": 40, "refused": 40, "admitted": 0, "other": 0,
                    "records": 0},
    })
    assert gate["readiness_no_admitted"] is False
    assert gate["readiness_admitted"] == 1
    assert gate["passed"] is False


def test_a_worker_generate_count_that_moved_fails_the_run():
    """A fresh worker starts at 0, so anything else means an inference reached it
    during the load."""
    _summary, gate = _clean_run(generate_after_load=1)
    assert gate["readiness_no_worker_generate"] is False
    assert gate["passed"] is False


def test_a_record_written_during_the_load_fails_the_run():
    _summary, gate = _clean_run(records_delta_loading=1)
    assert gate["readiness_no_records"] is False
    assert gate["passed"] is False


def test_a_load_window_that_was_never_observed_fails_the_run():
    """If `/api/models` never reported loading, the phase measured nothing. A
    gate that passed anyway would be reporting on a window it never hit."""
    _summary, gate = _clean_run(observed_loading=False)
    assert gate["readiness_observed_loading"] is False
    assert gate["passed"] is False


def test_a_model_that_does_not_serve_after_the_load_fails_the_run():
    _summary, gate = _clean_run(after={"http": 200, "req_id": "abc", "records_delta": 0})
    assert gate["readiness_serves_after"] is False
    assert gate["passed"] is False


def test_a_failed_core_request_fails_the_run():
    rows = _full_core()
    rows[17] = _round(group="nocxt", index=18, output="", status=500,
                      error="HTTP 500: boom", status_ok=False)
    _summary, gate = _clean_run(rows)
    assert gate["core_all_ok"] is False
    assert gate["http_5xx"] == 1
    assert gate["passed"] is False


def test_a_missing_concurrency_lane_fails_the_run():
    rows = _full_core() + _concurrency_rows()
    rows.pop()
    _summary, gate = _clean_run(rows, with_concurrency=False)
    assert gate["concurrency_all_ok"] is False
    assert gate["passed"] is False


def test_cross_talk_fails_the_run():
    rows = _full_core() + _concurrency_rows(cross_talk_round=7)
    _summary, gate = _clean_run(rows, with_concurrency=False)
    assert gate["cross_talk"] == 1
    assert gate["passed"] is False


def test_a_missing_record_fails_the_run_even_when_every_request_succeeded():
    summary = ext.summarize(_full_core(), _readiness())
    db = {"readable": True, "found": 2099, "expected": 2100,
          "missing": [{"id": "x"}], "output_mismatch": []}
    gate = ext.verdict(summary, _records(checked=2100, missing=[{"id": "x"}]), db,
                       summary["readiness"])
    assert gate["records_missing"] == 1
    assert gate["sqlite_missing"] == 1
    assert gate["passed"] is False


def test_answer_accuracy_is_reported_but_does_not_gate():
    """The task's acceptance is stability, not a correctness threshold. A run
    with some wrong answers still passes; the rates are printed either way so a
    low one is visible rather than hidden behind the gate.
    """
    rows = _full_core()
    for row in rows[:200]:
        row.count_ok = False
    summary, gate = _clean_run(rows)
    assert gate["count_accuracy"] < 1.0
    assert gate["passed"] is True


def test_a_run_where_nothing_was_answered_correctly_fails():
    """Not a threshold -- a floor of zero. A model that answered no question
    correctly has not demonstrated a working service, and the MYS-2498 recall bug
    is exactly what a gate that shrugged at 0 would have shipped."""
    rows = _full_core()
    for row in rows:
        if row.count_ok is not None:
            row.count_ok = False
        if row.recall_ok is not None:
            row.recall_ok = False
    _summary, gate = _clean_run(rows)
    assert gate["some_answer_correct"] is False
    assert gate["some_recall_correct"] is False
    assert gate["passed"] is False


def test_the_summary_separates_the_groups_and_counts_sessions():
    summary = ext.summarize(_full_core(), _readiness())
    assert summary["groups"]["nocxt"]["requests"] == 1000
    assert summary["groups"]["cxt"]["requests"] == 1000
    assert summary["groups"]["cxt"]["sessions"] == 100
    assert summary["totals"]["core_requests"] == 2000


def test_readiness_refusals_are_not_counted_as_failures():
    """A 409 during a load is the correct answer. Counting it as a failed request
    would make a working gate look broken."""
    rows = [_round(group="readiness-stream", status=409, expected_status=409,
                   status_ok=True, error="HTTP 409: loading"),
            _round(group="nocxt", status=200)]
    summary = ext.summarize(rows, _readiness())
    group = summary["groups"]["readiness-stream"]
    assert group["ok"] == 1, "a 409 matching its expected status is a success"
    assert group["status_matched"] == 1


def test_an_unexpected_status_is_a_failure():
    rows = [_round(group="readiness-stream", status=200, expected_status=409,
                   status_ok=False)]
    summary = ext.summarize(rows, _readiness())
    group = summary["groups"]["readiness-stream"]
    assert group["ok"] == 0
    assert group["status_matched"] == 0
    assert group["http_status_counts"] == {"200": 1}


def test_the_per_tier_breakdown_covers_every_tier_that_was_used():
    summary = ext.summarize(_full_core(), _readiness())
    assert set(summary["by_tier"]["nocxt"]) == {str(t) for t in ext.TIERS}
    assert set(summary["by_tier"]["cxt"]) == {str(t) for t in ext.TIERS[:10]}


# --------------------------------------------------------------------------
# HTML: escaping and self-containment
# --------------------------------------------------------------------------
def test_html_escape_neutralises_tags_and_quotes():
    assert ext.html_escape('<script>alert("x")</script>') == (
        "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;")
    assert ext.html_escape("it's") == "it&#x27;s"
    assert ext.html_escape(None) == ""


def test_js_json_cannot_close_the_script_block():
    """``</script>`` inside a JSON string ends the block early; escaping ``<``
    keeps it valid JSON and inert HTML."""
    payload = ext.js_json({"output": "</script><img src=x onerror=alert(1)>"})
    assert "</script>" not in payload
    assert "\\u003c" in payload
    assert json.loads(payload) == {"output": "</script><img src=x onerror=alert(1)>"}


def test_the_svg_charts_escape_their_labels():
    svg = ext.svg_line_chart(
        [{"name": "<b>x</b>", "values": [1.0, 2.0], "colour": "#123456"}],
        title="<i>t</i>", y_label="<u>y</u>", x_labels=["<a>", "<c>"])
    assert "<b>" not in svg and "&lt;b&gt;" in svg
    assert "<i>" not in svg and "&lt;i&gt;" in svg
    assert "<a>" not in svg and "&lt;a&gt;" in svg


def test_a_chart_breaks_its_line_rather_than_drawing_zero_for_a_missing_value():
    """A ``None`` means "not measured". Drawing it at y=0 would invent a datapoint
    and make a gap look like a 0-second request."""
    svg = ext.svg_line_chart([{"name": "s", "values": [1.0, None, 3.0]}],
                             title="t", y_label="y", x_labels=["a", "b", "c"])
    assert svg.count("<path") == 1
    assert svg.count("<circle") == 2, "only the two measured points are drawn"
    assert "Lnan" not in svg and "NaN" not in svg


def test_a_chart_with_no_data_still_renders():
    svg = ext.svg_line_chart([{"name": "s", "values": [None, None]}],
                             title="t", y_label="y", x_labels=["a", "b"])
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<path" not in svg


def test_the_bar_chart_escapes_labels_and_handles_missing_values():
    svg = ext.svg_bar_chart(["<x>", "b"], [3, None], title="t", y_label="y",
                            second=[1, None], first_name="f", second_name="s")
    assert "&lt;x&gt;" in svg
    assert "<x>" not in svg
    # Two measured bars (one per series; the ``None`` entries draw nothing) plus
    # one swatch per legend entry.
    assert svg.count("<rect") == 4


# --------------------------------------------------------------------------
# HTML: the whole document
# --------------------------------------------------------------------------
def rows_payload(text: str) -> list:
    """The ``window.__ROWS__ = [...]`` payload, parsed.

    Extracted with ``json.JSONDecoder.raw_decode`` rather than a regex: the rows
    contain ``]`` inside nested arrays and truncated model output, so a
    non-greedy pattern stops at the first inner bracket and the test would be
    measuring its own parser instead of the report.
    """
    marker = "window.__ROWS__ = "
    start = text.index(marker) + len(marker)
    payload, _end = json.JSONDecoder().raw_decode(text, start)
    return payload


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    """One rendered report, shared by the structural assertions below.

    Built from a synthetic but complete run: 2000 core rounds, 100 concurrent,
    a readiness phase that held, one round per tier with a deliberately hostile
    model output.
    """
    rows = _full_core() + _concurrency_rows()
    rows[0].output = '</script><img src=x onerror="alert(1)">＜恶意＞'
    rows[0].input_text = "<svg onload=alert(2)>"
    for attempt in range(1, 41):
        rows.append(_round(group="readiness-stream", index=900 + attempt,
                           status=409, expected_status=409, status_ok=True,
                           error="HTTP 409: model is loading"))
    rows.append(_round(group="readiness-after", index=990, status=200,
                       output="2", count_ok=True))
    readiness = _readiness()
    summary = ext.summarize(rows, readiness)
    db = {"readable": True, "found": 2101, "expected": 2101, "missing": [],
          "output_mismatch": [], "exists": True, "bytes": 4096, "error": None}
    records = _records(checked=2101, export_lines=2101)
    gate = ext.verdict(summary, records, db, readiness)
    timeline = ext.Timeline()
    timeline.add("phase", "开始无上下文组", "计划 1000 次", group="nocxt")
    timeline.add("phase", "开始带上下文组", "100 会话 × 10 轮", group="cxt")
    timeline.anomaly("无上下文请求异常", "第 5 次（100 字）：HTTP 500 <b>x</b>",
                     group="nocxt")
    samples = [{"at": 1_700_000_000 + 5 * i, "ok": True, "cpu_percent": 12.5,
                "mem_available": 3_000_000_000, "tpu_util": 40.0,
                "npu_mem_used": 24_000_000_000, "worker": {"active": 1, "queued": 0,
                                                           "total_requests": 100 + i,
                                                           "failed_requests": 0,
                                                           "rejected_requests": 0,
                                                           "cache_entries": 4}}
               for i in range(20)]
    env = {
        "captured_iso": "2026-10-31T00:00:00Z",
        "healthz": {"ok": True, "version": "0.6.14", "loaded": 1},
        "service": {"active": "active", "version_pkg": "0.6.14",
                    "version_file": "0.6.14", "main_pid": "1234",
                    "started": "Fri 2026-10-31 07:00:00 CST"},
        "kernel": "Linux 5.15 <x>",
        "sdk_version": "1.9.0",
        "libsophon": "",
        "data_dir": "/data/cv84x6_llm_server",
        "models": [{"id": "qwen3.6-35b-a3b-128k", "loaded": True,
                    "context_length": 131072, "supports_sampling": False,
                    "supports_vision": True, "load_seconds": 66.8}],
        "model_dirs": [{"bmodel": "x.bmodel", "bytes": 20638679040}],
        "settings": {"max_concurrent_per_model": 2, "max_queue": 16,
                     "prefix_cache_entries": 32, "prefix_cache_mb": 2048,
                     "inference_logging_enabled": True,
                     "inference_log_retention_count": 5000,
                     "inference_log_retention_days": 30,
                     "require_api_key": True},
        "record_log": {"path": "/data/x/state/inference_records.sqlite3",
                       "total": 101, "bytes": 299088, "retention_count": 5000,
                       "retention_days": 30},
    }
    out = tmp_path_factory.mktemp("report")
    path = ext.build_html(out, env, summary, records, db, readiness, gate,
                          {"model": "qwen3.6-35b-a3b-128k", "seed": base.SEED,
                           "params": ext.PARAMS, "system": ext.SYSTEM_PROMPT},
                          rows, timeline.entries, samples, "172.26.166.96:10151")
    return path, summary, gate, rows


def test_the_report_is_one_self_contained_file(report):
    """No CDN, no external font, no ``src=``/``href=`` to anywhere: it has to open
    on a board with no network and render the same as on a laptop."""
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert path.name == "report.html"
    for pattern in ("http://", "https://", "//cdn", "@import", "<link ",
                    "<iframe", "src=\"http", "src='http"):
        assert pattern not in text, pattern
    assert "<script>" in text and "<style>" in text


def test_the_report_renders_the_model_output_as_data_not_markup(report):
    """The hostile output must survive intact inside the JSON payload and appear
    nowhere as live markup."""
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert "<img src=x onerror" not in text
    assert "\\u003c/script\\u003e" in text, "the payload escaped the closing tag"
    rows = rows_payload(text)
    assert any("<img src=x onerror" in row[19] for row in rows), \
        "the output must survive as data"
    assert any("<svg onload" in row[18] for row in rows), "so must the input"


def test_the_report_has_the_four_requested_tabs(report):
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    for label in ("整体结论", "测试时间线", "性能图表", "测试数据详情"):
        assert label in text, label
    assert text.count('role="tabpanel"') == 4


def test_the_report_states_the_context_group_is_100_sessions_of_10(report):
    """The one claim that must never be blurred into "1000 rounds"."""
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert "100 个独立会话 × 每会话 10 轮" in text
    assert "不是 1000 轮同一会话" in text


def test_the_report_includes_every_request_in_the_detail_table(report):
    path, _summary, _gate, rows = report
    text = path.read_text(encoding="utf-8")
    payload = rows_payload(text)
    assert len(payload) == len(rows)
    assert len(payload) > 2100


def test_the_table_payload_has_one_value_per_declared_column(report):
    path, _summary, _gate, rows = report
    text = path.read_text(encoding="utf-8")
    for row in rows_payload(text):
        assert len(row) == len(ext.TABLE_COLUMNS), row


def test_the_table_is_searchable_and_paginated(report):
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert 'id="t-q"' in text, "a search box"
    assert 'id="t-prev"' in text and 'id="t-next"' in text, "pagination"
    assert 'id="t-size"' in text and 'id="t-body"' in text
    assert "textContent" in text, "cells must be set as text, never innerHTML"
    assert "innerHTML" not in text, "innerHTML would let a model output execute"


def test_the_report_draws_the_requested_charts(report):
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    for title in ("首 token 延迟", "decode 吞吐", "单请求总耗时", "prompt token"):
        assert title in text, title
    assert text.count("<svg") >= 6


def test_the_report_reports_min_median_p95_and_max(report):
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert "min / median / p95 / max" in text
    assert "p95" in text


def test_the_report_states_the_verdict_and_the_readiness_numbers(report):
    path, summary, gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert ("通过" in text)
    assert f'>{gate["readiness_refused"]}<' in text
    assert f'{gate["core_ok_requests"]}/{2000}' in text


def test_the_report_does_not_contain_an_api_key(report):
    """The raw key lives in memory only; nothing in the report may echo it."""
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)


def test_the_timeline_is_rendered_with_its_anomaly(report):
    path, _summary, _gate, _rows = report
    text = path.read_text(encoding="utf-8")
    assert "无上下文请求异常" in text
    assert "开始带上下文组" in text


# --------------------------------------------------------------------------
# The MYS-2498 report is untouched
# --------------------------------------------------------------------------
def test_the_previous_report_still_generates(tmp_path):
    """The MYS-2498 suite's markdown report is regenerated here so a change to
    the shared prompt builder cannot quietly break it."""
    rounds = [
        base.new_round("nocxt", base.build_prompt(60, 4), [{"role": "user"}] * 2),
        base.new_round("cxt", base.build_prompt(300, 7), [{"role": "user"}] * 14),
    ]
    for row in rounds:
        row.http_status = 200
        row.output = "2"
        row.count_ok = True
        row.total_s = 1.5
        row.ttft_s = 1.0
    summary = base.summarize(rounds)
    summary["verdict"] = {"passed": True}
    records = {"checked": 2, "missing": [], "missing_from_export": [],
               "duplicates": [], "source_mismatch": [], "not_ok_rows": [],
               "input_mismatch": [], "output_mismatch": [], "metrics_mismatch": [],
               "context_mismatch": [], "secret_leaks": [], "details": [],
               "export_lines": 2}
    db = {"path": "x", "exists": True, "bytes": 1, "readable": True, "found": 2,
          "expected": 2, "missing": [], "output_mismatch": [], "error": None}
    manifest = {"seed": base.SEED, "model": "m"}
    path = base.write_report(tmp_path, {"service": {}, "record_log": {}}, summary,
                             records, db, None, {"passed": True}, manifest,
                             rounds, "board")
    text = path.read_text(encoding="utf-8")
    assert "验收判定" in text
    assert "通过" in text


def test_the_previous_battery_is_unchanged_by_the_new_parameters():
    """MYS-2498's 10-tier battery must be byte-identical to before: the extended
    suite passes new keyword arguments, but the defaults are the old behaviour."""
    texts = [p.text for p in base.build_battery()]
    assert len(texts) == 10
    assert [p.length for p in base.build_battery()] == base.LENGTHS
    # Determinism, which is what the manifest promises.
    assert texts == [p.text for p in base.build_battery()]


def test_the_base_prompt_builder_still_refuses_an_unknown_tier():
    with pytest.raises(ValueError):
        base.build_prompt(500, 1)


def test_the_base_variant_does_not_change_what_a_tier_promises():
    """``variant`` reseeds the material only: the length, the round number, the
    planted fact and the expected count stay in the tier's contract."""
    for variant in (0, 1, 7):
        prompt = base.build_prompt(300, 7, variant=variant)
        assert base.chars(prompt.text) == 300
        assert prompt.round_index == 7
        assert prompt.plants_fact is True
        assert prompt.expected_count is not None
    first = base.build_prompt(300, 7, variant=0).text
    second = base.build_prompt(300, 7, variant=1).text
    assert first != second, "the variant must actually change the material"


# --------------------------------------------------------------------------
# Timeline and sampler plumbing
# --------------------------------------------------------------------------
def test_the_timeline_appends_and_serialises(tmp_path):
    path = tmp_path / "timeline.jsonl"
    timeline = ext.Timeline(path)
    timeline.add("phase", "开始", "detail", group="nocxt", count=3)
    timeline.anomaly("异常", "boom")
    timeline.close()
    lines = [json.loads(line) for line in
             path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["kind"] == "phase" and lines[0]["count"] == 3
    assert lines[1]["kind"] == "anomaly"
    assert lines[0]["iso"].endswith("Z")
    assert len(timeline.entries) == 2


def test_a_run_directory_is_never_reused(tmp_path):
    first = ext.make_run_dir(tmp_path)
    second = ext.make_run_dir(tmp_path)
    assert first != second
    assert (first / "raw").is_dir()
    (first / "rounds.jsonl").write_text("kept\n", encoding="utf-8")
    assert (first / "rounds.jsonl").read_text(encoding="utf-8") == "kept\n"


def test_sampler_interval_is_the_median_gap():
    samples = [{"at": 100.0}, {"at": 105.0}, {"at": 110.0}, {"at": 120.0}]
    assert ext.sampler_interval(samples) == 5.0
    assert ext.sampler_interval([{"at": 1.0}]) is None


# --------------------------------------------------------------------------
# End to end against a real service process (mock backend)
# --------------------------------------------------------------------------
#: A shrunken matrix for the live test. Same code paths -- same plan builder, same
#: phases, same record cross-check, same report -- with counts small enough to
#: run in seconds. The full 2100-request matrix is a board job, not a CI job.
SMALL_TIERS = [2, 10, 30, 60]
SMALL_PLAN = [(2, 2), (10, 2), (30, 1), (60, 1)]


@pytest.fixture(scope="module")
def live_service(tmp_path_factory):
    """A real service on a real port, one model loaded (mock backend)."""
    import socket
    import threading
    import time

    import uvicorn

    from app.main import create_app

    root = tmp_path_factory.mktemp("live")
    models = root / "models"
    model = models / "m"
    (model / "config").mkdir(parents=True)
    (model / "m-int4_w4bf16_seq4096_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (model / "config" / "config.json").write_text("{}")
    app = create_app(data_dir=root / "data", models_dir=models, backend_kind="mock",
                     web_dir=root / "web", context_length_override=8192,
                     decode_delay_ms=0.0)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    client = base.Http(url, timeout=60)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if client.login("admin") == 200:
                break
        except OSError:
            pass
        time.sleep(0.2)
    else:  # pragma: no cover
        pytest.fail("service did not come up")
    status, _ = client.json("POST", "/api/models/m/load", timeout=120)
    assert status == 200, status
    yield url, root, client
    server.should_exit = True
    thread.join(timeout=30)


def _small_manifest(model: str, seed: int) -> dict:
    """``build_manifest`` for the shrunken matrix -- same shapes, fewer requests."""
    original = (ext.TIERS, ext.REQUESTS_PER_TIER_SHORT, ext.REQUESTS_PER_TIER_LONG,
                ext.SHORT_TIER_COUNT, ext.CONTEXT_SESSIONS, ext.CONTEXT_TURNS,
                ext.CONCURRENCY_LANES, ext.CONCURRENCY_ROUNDS, ext.CONCURRENCY_TIERS)
    ext.TIERS = list(SMALL_TIERS)
    ext.REQUESTS_PER_TIER_SHORT = 2
    ext.REQUESTS_PER_TIER_LONG = 1
    ext.SHORT_TIER_COUNT = 2
    ext.CONTEXT_SESSIONS = 2
    ext.CONTEXT_TURNS = 3
    ext.CONCURRENCY_LANES = 2
    ext.CONCURRENCY_ROUNDS = 2
    ext.CONCURRENCY_TIERS = (30, 60)
    try:
        return ext.build_manifest(model, seed)
    finally:
        (ext.TIERS, ext.REQUESTS_PER_TIER_SHORT, ext.REQUESTS_PER_TIER_LONG,
         ext.SHORT_TIER_COUNT, ext.CONTEXT_SESSIONS, ext.CONTEXT_TURNS,
         ext.CONCURRENCY_LANES, ext.CONCURRENCY_ROUNDS,
         ext.CONCURRENCY_TIERS) = original


def test_the_phases_run_against_a_real_service(live_service, tmp_path):
    """Drive every phase over HTTP and check the evidence it leaves behind.

    The mock answers with words rather than a number, so counting grades mostly
    come out wrong -- which is the point of asserting that the *mechanical*
    checks (one record per request, output identical, tokens equal) still pass
    while the answer rate does not.
    """
    url, root, client = live_service
    key, key_id = ext.create_key(client, "MYS-2501-test-key")
    evidence = tmp_path / "run"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    timeline = ext.Timeline(evidence / "timeline.jsonl")
    runner = ext.Runner(client, key, "m", evidence, evidence / "raw",
                        timeline, timeout=120)
    try:
        runner.run_nocxt(ext.nocxt_plan("tiered")[:4], SMALL_TIERS)
        runner.run_cxt([[2, 10, 30], [2, 10, 30]])
        runner.run_concurrency(lanes=2, rounds=2, tiers=(30, 60))
    finally:
        runner.close()
        timeline.close()

    rows = runner.rounds
    assert sum(1 for r in rows if r.group == "nocxt") == 4
    assert sum(1 for r in rows if r.group == "cxt") == 6
    assert sum(1 for r in rows if r.group == "conc") == 4

    # Every request really reached the service and got a streamed answer.
    assert all(r.http_status == 200 for r in rows), [
        (r.group, r.http_status, r.error) for r in rows if r.http_status != 200]
    assert all(r.output for r in rows)
    assert all(r.stream_done for r in rows)
    assert all(r.req_id for r in rows), "every reply must carry a request id"

    # The context group resent its history: 1 turn grows 2 -> 4 -> 6 messages,
    # and the second session starts from 2 again rather than continuing to 8.
    cxt = sorted((r for r in rows if r.group == "cxt"),
                 key=lambda r: (r.session, r.turn))
    assert [r.context_messages for r in cxt] == [2, 4, 6, 2, 4, 6]
    assert [r.session for r in cxt] == [1, 1, 1, 2, 2, 2]

    # Concurrency really ran two lanes with distinct markers, no cross-talk.
    assert not any(r.cross_talk for r in rows)
    assert len({r.marker for r in rows if r.group == "conc"}) == 4

    # One record per request, and the record agrees with the client.
    details, no_ids = base.fetch_records(client, rows)
    assert not no_ids
    assert len(details) == len(rows)
    for row in rows:
        detail = details[row.req_id]
        assert detail["source"] == "/v1/chat/completions"
        assert (detail.get("output_text") or "") == row.output, row.req_id
        assert len(detail.get("messages") or []) == row.context_messages
        assert detail.get("prompt_tokens") == row.prompt_tokens

    # The evidence files the report promises exist.
    lines = (evidence / "rounds.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if line.strip()]) == 14
    assert (evidence / "timeline.jsonl").is_file()

    client.json("DELETE", f"/api/keys/{key_id}", timeout=30)


def test_the_readiness_probe_refuses_while_the_model_loads(live_service, tmp_path):
    """The real gate, end to end: stop the model, reload it, hammer it, then check.

    With the mock backend the load is fast, so the probe may only catch a few
    attempts inside the window -- hence the assertion is about *behaviour*
    (nothing admitted, nothing generated, nothing recorded) rather than a
    minimum attempt count, which would be a flaky assertion about timing.
    """
    url, root, client = live_service
    key, key_id = ext.create_key(client, "MYS-2501-readiness-key")
    evidence = tmp_path / "readiness"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    timeline = ext.Timeline(evidence / "timeline.jsonl")
    runner = ext.Runner(client, key, "m", evidence, evidence / "raw", timeline,
                        timeout=120)
    try:
        info = runner.run_readiness("admin", "m", load_timeout=120)
    finally:
        runner.close()
        timeline.close()

    assert info.get("error") is None, info
    assert info["loaded"] is True
    assert info["observed_loading"] is True, "the probe must have seen the window"
    assert info["attempts"] > 0
    assert info["by_surface"].keys() == set(ext.READINESS_SURFACES)
    for surface, bucket in info["by_surface"].items():
        assert bucket["admitted"] == 0, (surface, bucket)
        assert bucket["other"] == 0, (surface, bucket)
        assert bucket["refused"] == bucket["attempts"], (surface, bucket)
    assert info["generate_after_load"] == 0, info
    assert info["records_delta_loading"] == 0, info
    assert info["after"]["http"] == 200
    assert info["after"]["records_delta"] == 1

    # A refusal must leave no record behind: only the post-load request has one.
    attempts = [r for r in runner.rounds if r.group.startswith("readiness-")
                and r.group != "readiness-after"]
    assert attempts
    assert all(r.req_id is None for r in attempts), "a 409 carries no req_id"
    after = [r for r in runner.rounds if r.group == "readiness-after"]
    assert len(after) == 1 and after[0].req_id

    client.json("DELETE", f"/api/keys/{key_id}", timeout=30)


def test_main_writes_a_report_from_a_short_run(live_service, tmp_path, monkeypatch):
    """``main()`` end to end: mint a key, run the phases, verify, render, clean up.

    The matrix is shrunk through the module constants so the real ``main`` runs
    unmodified -- the same function the board run calls.
    """
    url, root, client = live_service
    monkeypatch.setattr(ext, "TIERS", list(SMALL_TIERS))
    monkeypatch.setattr(ext, "REQUESTS_PER_TIER_SHORT", 2)
    monkeypatch.setattr(ext, "REQUESTS_PER_TIER_LONG", 1)
    monkeypatch.setattr(ext, "SHORT_TIER_COUNT", 2)
    monkeypatch.setattr(ext, "CONTEXT_SESSIONS", 2)
    monkeypatch.setattr(ext, "CONTEXT_TURNS", 3)
    monkeypatch.setattr(ext, "CONCURRENCY_LANES", 2)
    monkeypatch.setattr(ext, "CONCURRENCY_ROUNDS", 2)
    monkeypatch.setattr(ext, "CONCURRENCY_TIERS", (30, 60))

    before = {k["name"] for k in client.json("GET", "/api/keys", timeout=30)[1]["keys"]}
    evidence = tmp_path / "evidence"
    code = ext.main(["--base", url, "--password", "admin",
                     "--evidence-dir", str(evidence),
                     "--data-dir", str(root / "data"),
                     "--device-label", "test-board",
                     "--timeout", "120",
                     "--key-name", "MYS-2501-stability"])
    run = next(evidence.glob("run-*"))

    # The mock does not answer the count task, so the run must not report a pass:
    # a suite that passed here would be scoring nothing.
    assert code == 1, "the mock never answers with the right number"
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"]["passed"] is False
    planned = 2 * ext.core_total()
    assert summary["verdict"]["core_ok_requests"] == planned
    assert summary["verdict"]["records_missing"] == 0
    assert summary["verdict"]["records_duplicated"] == 0
    assert summary["verdict"]["http_5xx"] == 0
    assert summary["totals"]["core_requests"] == planned
    assert summary["totals"]["concurrency_requests"] == (
        ext.CONCURRENCY_LANES * ext.CONCURRENCY_ROUNDS)

    # Every artifact the report claims to sit beside.
    for name in ("report.html", "report.md" if False else "manifest.json",
                 "summary.json", "env.json", "records-check.json",
                 "sqlite-check.json", "records-export.ndjson", "timeline.jsonl",
                 "evidence.json", "journal-test.txt", "dmesg.txt"):
        path = run / name
        assert path.is_file() and path.stat().st_size > 0, name

    # The key it minted is gone; nothing else was touched.
    after = {k["name"] for k in client.json("GET", "/api/keys", timeout=30)[1]["keys"]}
    assert "MYS-2501-stability" not in after
    assert before - {"MYS-2501-stability"} <= after

    # The HTML is a real page built from this run.
    html_text = (run / "report.html").read_text(encoding="utf-8")
    assert html_text.startswith("<!doctype html>")
    rows = rows_payload(html_text)
    assert len(rows) == planned + ext.CONCURRENCY_LANES * ext.CONCURRENCY_ROUNDS
    assert "http://" not in html_text.replace("http://127.0.0.1", "")


# --------------------------------------------------------------------------
# Resuming from an earlier run
# --------------------------------------------------------------------------
def test_a_resumed_run_adopts_rows_and_raw_bodies_without_touching_the_source(tmp_path):
    """The point of ``--resume-from``: keep hours of real evidence, add the phase
    that is missing, and leave the source directory exactly as it was.

    The source is snapshotted byte for byte before and after; a resume that
    rewrote it would be replacing evidence, which the task card forbids.
    """
    source = tmp_path / "source"
    (source / "raw").mkdir(parents=True)
    rows = [_round(group="nocxt", index=i, tier=60, output="2", count_ok=True)
            for i in range(1, 4)]
    rows.append(_round(group="conc", index=101, lane=1, output="KX 2"))
    (source / "rounds.jsonl").write_text(
        "".join(json.dumps(r.as_row(), ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    (source / "manifest.json").write_text(json.dumps({"seed": 1, "model": "m"}),
                                          encoding="utf-8")
    (source / "env.json").write_text('{"captured_iso": "x"}', encoding="utf-8")
    for name in ("nocxt-1.sse", "nocxt-2.sse"):
        (source / "raw" / name).write_text("data: [DONE]\n", encoding="utf-8")
    before = {p.relative_to(source): p.read_bytes()
              for p in source.rglob("*") if p.is_file()}

    evidence = tmp_path / "target"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    adopted, note = ext.adopt_previous_run(source, evidence)

    assert len(adopted) == 4
    assert {r.group for r in adopted} == {"nocxt", "conc"}
    assert note["adopted_rows"] == 4 and note["skipped_count"] == 0
    assert note["raw_copied"] == 2
    # The rows kept their own numbers, timestamps and grades.
    assert [r.round_index for r in adopted if r.group == "nocxt"] == [1, 2, 3]
    assert all(r.count_ok for r in adopted if r.group == "nocxt")
    # Manifest and env came across; the source is untouched.
    assert (evidence / "manifest.json").read_text(encoding="utf-8") == '{"seed": 1, "model": "m"}'
    assert (evidence / "raw" / "nocxt-1.sse").is_file()
    after = {p.relative_to(source): p.read_bytes()
             for p in source.rglob("*") if p.is_file()}
    assert before == after, "resuming must not modify the source run"


def test_a_truncated_source_yields_the_rows_it_had(tmp_path):
    """A run killed mid-write leaves a partial last line. Adopting what is there
    beats refusing to start, and the skipped line is reported rather than
    silently dropped."""
    source = tmp_path / "source"
    source.mkdir()
    good = _round(group="nocxt", index=1, output="2", count_ok=True).as_row()
    (source / "rounds.jsonl").write_text(
        json.dumps(good, ensure_ascii=False) + "\n" + '{"group": "nocxt", "rou',
        encoding="utf-8")
    evidence = tmp_path / "target"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    adopted, note = ext.adopt_previous_run(source, evidence)
    assert len(adopted) == 1
    assert note["skipped_count"] == 1


def test_a_source_without_rounds_jsonl_is_refused(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    evidence = tmp_path / "target"
    evidence.mkdir()
    with pytest.raises(SystemExit):
        ext.adopt_previous_run(source, evidence)


def test_a_row_missing_a_column_still_loads(tmp_path):
    """Forward/backward compatibility: a row from a build that lacked a field must
    load with that field null rather than be discarded."""
    source = tmp_path / "source"
    source.mkdir()
    payload = {"group": "nocxt", "round_index": 3, "tier": 60, "output": "2"}
    (source / "rounds.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")
    evidence = tmp_path / "target"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    adopted, _note = ext.adopt_previous_run(source, evidence)
    assert len(adopted) == 1
    assert adopted[0].output == "2"
    assert adopted[0].ttft_s is None and adopted[0].http_status is None


def test_the_report_discloses_a_resumed_run(report, tmp_path):
    """A merged report must say so: a reader has to be able to tell that the
    request rows did not all come from one sitting."""
    _path, summary, gate, rows = report
    resume = {"source_name": "run-earlier", "adopted_rows": 2000,
              "adopted_groups": ["cxt", "nocxt"]}
    env = {"captured_iso": "2026-10-31T00:00:00Z", "service": {}, "models": [],
           "record_log": {}, "settings": {}}
    db = {"readable": True, "found": 0, "expected": 0, "missing": [],
          "output_mismatch": [], "exists": True, "bytes": 1, "error": None}
    out = ext.build_html(tmp_path, env, summary, _records(), db, {}, gate,
                         {"model": "m", "seed": base.SEED, "params": {}, "system": ""},
                         rows, [], [], "board", resume)
    text = out.read_text(encoding="utf-8")
    assert "证据构成" in text
    assert "run-earlier" in text
    assert "2000" in text


def test_backfill_restores_prompt_text_and_verifies_it_by_hash(tmp_path):
    """The bug the first resume hit: every adopted row reported an input mismatch
    because the JSONL carries no prompt text, so the record cross-check compared
    the record's real message against an empty string -- 2100 false mismatches.

    The manifest is the authority, and the row's own SHA-256 is the check that the
    text found there is the text that was sent. A row whose hash does not match
    must be left unbackfilled and counted, never quietly accepted.
    """
    lengths = [2, 10, 30, 60]
    prompts = [base.build_prompt(n, i + 1, lengths=lengths)
               for i, n in enumerate(lengths)]
    manifest = {
        "nocxt": [{**p.manifest(), "request": i + 1}
                  for i, p in enumerate(prompts)],
        "cxt": [], "concurrency": [],
    }
    rows = []
    for i, prompt in enumerate(prompts):
        row = _round(group="nocxt", index=i + 1, tier=prompt.length)
        # Exactly what a JSONL round-trip leaves behind.
        row.input_text = ""
        row.input_sha256 = base.sha256(prompt.text)
        row.input_chars = base.chars(prompt.text)
        rows.append(row)
    # One row whose hash belongs to no manifest entry.
    forged = _round(group="nocxt", index=99, tier=60)
    forged.input_text = ""
    forged.input_sha256 = "0" * 64
    rows.append(forged)

    result = ext.backfill_inputs(rows, manifest)
    assert result["filled"] == len(prompts)
    assert result["missing"] == 1
    assert result["hash_mismatch_count"] == 0
    assert [r.input_text for r in rows[:len(prompts)]] == [p.text for p in prompts]
    assert rows[-1].input_text == "", "a hash that matches nothing must not be guessed"


def test_backfill_refuses_text_that_does_not_match_the_recorded_hash():
    """A manifest from a different seed produces right-looking rows; accepting
    them would make the report describe prompts that were never sent."""
    prompt = base.build_prompt(60, 1, lengths=ext.TIERS)
    other = base.build_prompt(60, 1, lengths=ext.TIERS, variant=5)
    manifest = {"nocxt": [{**other.manifest(), "request": 1}],
                "cxt": [], "concurrency": []}
    row = _round(group="nocxt", index=1, tier=60)
    row.input_text = ""
    row.input_sha256 = base.sha256(prompt.text)
    result = ext.backfill_inputs([row], manifest)
    assert result["filled"] == 0
    assert result["hash_mismatch_count"] == 1
    assert row.input_text == ""


def test_backfill_leaves_a_row_that_already_has_its_text_alone():
    prompt = base.build_prompt(60, 1, lengths=ext.TIERS)
    row = _round(group="nocxt", index=1, tier=60)
    row.input_text = "in-memory text from this run"
    result = ext.backfill_inputs([row], {"nocxt": [], "cxt": [], "concurrency": []})
    assert result["filled"] == 0
    assert row.input_text == "in-memory text from this run"


def test_backfill_matches_a_context_row_by_session_and_turn():
    ladder = ext.TIERS[:3]
    prompts = [base.build_prompt(n, t, lengths=ladder, recall_target="previous",
                                 variant=1)
               for t, n in enumerate(ladder, start=1)]
    manifest = {"nocxt": [], "concurrency": [],
                "cxt": [[{**p.manifest(), "session": 1, "turn": t}
                         for t, p in enumerate(prompts, start=1)]]}
    rows = []
    for t, prompt in enumerate(prompts, start=1):
        row = _round(group="cxt", index=t, tier=prompt.length, session=1, turn=t)
        row.input_text = ""
        row.input_sha256 = base.sha256(prompt.text)
        rows.append(row)
    result = ext.backfill_inputs(rows, manifest)
    assert result["filled"] == 3
    assert [r.input_text for r in rows] == [p.text for p in prompts]


def test_backfill_is_hash_primary_because_structural_keys_repeat():
    """The bug the second resume hit.

    The no-context group cycles 12 ladder positions, so its manifest has 1000
    entries but only 12 distinct ``(group, round)`` keys. A structural-key-first
    lookup returns some other cycle's text, which then fails the hash check -- 822
    rows reported as mismatches even though every one of their texts was present.

    This builds that exact shape and asserts the hash wins.
    """
    lengths = [60, 100]
    no_context = []
    for cycle in range(4):
        for turn, length in enumerate(lengths, start=1):
            prompt = base.build_prompt(length, turn, lengths=lengths, variant=cycle + 1)
            no_context.append({**prompt.manifest(), "request": cycle * 2 + turn})
    manifest = {"nocxt": no_context, "cxt": [], "concurrency": []}
    rows = []
    for entry in no_context:
        row = _round(group="nocxt", index=entry["round"], tier=entry["length"])
        row.input_text = ""
        row.input_sha256 = entry["sha256"]
        rows.append(row)

    result = ext.backfill_inputs(rows, manifest)
    assert result["hash_mismatch_count"] == 0
    assert result["filled"] == len(no_context)
    assert [r.input_text for r in rows] == [e["text"] for e in no_context], \
        "each row must get its own cycle's text, not the last cycle's"


def test_backfill_does_not_report_a_refusal_as_missing():
    """A 409 during a load never reaches the model, so it has no prompt in the
    manifest and none is needed. Counting it as missing would report the correct
    outcome as a defect."""
    row = _round(group="readiness-stream", index=1, tier=30, status=409,
                 expected_status=409, status_ok=True)
    row.input_text = ""
    row.input_sha256 = base.sha256("never sent")
    result = ext.backfill_inputs([row], {"nocxt": [], "cxt": [], "concurrency": []})
    assert result["missing"] == 0
    assert result["filled"] == 0


def test_a_success_that_started_after_the_model_was_ready_is_not_an_admission():
    """The second resume's finding, and the subtlety behind it.

    The probe polls readiness once per iteration, then fires three requests. A
    66-second load finished between that poll and the third request, so the
    console surface got a 200 -- 1.5 ms *after* the service's own ``loaded_at``.
    Nothing was admitted early; the window had simply ended. Judging by request
    number would call that a failure, so the judgement is by timestamp.
    """
    ready_at = 1000.0
    readiness = _readiness(
        ready_at=ready_at,
        admitted=1,
        admitted_inside_window=0,
        unexpected_inside_window=[],
        unexpected_after_ready=[{"surface": "console", "attempt": 233,
                                 "http": 200, "started_at": ready_at + 0.0015}],
    )
    summary = ext.summarize(_full_core() + _concurrency_rows(), readiness)
    db = {"readable": True, "found": 2100, "expected": 2100, "missing": [],
          "output_mismatch": []}
    gate = ext.verdict(summary, _records(checked=2100), db, summary["readiness"])
    assert gate["readiness_admitted"] == 0
    assert gate["readiness_no_admitted"] is True
    assert gate["passed"] is True


def test_a_success_that_started_before_ready_fails_the_run():
    """The other direction, so the timestamp rule cannot be used to explain away
    a real early admission."""
    ready_at = 1000.0
    readiness = _readiness(
        ready_at=ready_at,
        admitted=1,
        admitted_inside_window=1,
        unexpected_inside_window=[{"surface": "console", "attempt": 10,
                                   "http": 200, "started_at": ready_at - 3.0}],
        unexpected_after_ready=[],
    )
    summary = ext.summarize(_full_core() + _concurrency_rows(), readiness)
    db = {"readable": True, "found": 2100, "expected": 2100, "missing": [],
          "output_mismatch": []}
    gate = ext.verdict(summary, _records(checked=2100), db, summary["readiness"])
    assert gate["readiness_admitted"] == 1
    assert gate["readiness_no_admitted"] is False
    assert gate["passed"] is False


def test_an_unexplained_success_without_a_timestamp_counts_as_inside():
    """Missing evidence must not clear a request: absent a ``ready_at`` or a
    start time, the only safe reading is that it was in the window."""
    readiness = _readiness(
        ready_at=None, admitted=1, admitted_inside_window=1,
        unexpected_inside_window=[{"surface": "stream", "attempt": 1, "http": 200}],
        unexpected_after_ready=[],
    )
    summary = ext.summarize(_full_core() + _concurrency_rows(), readiness)
    db = {"readable": True, "found": 2100, "expected": 2100, "missing": [],
          "output_mismatch": []}
    gate = ext.verdict(summary, _records(checked=2100), db, summary["readiness"])
    assert gate["passed"] is False


def test_a_phase_being_rerun_does_not_contribute_its_old_rows(tmp_path):
    """Merging the old readiness rows while the summary described only the new
    probe would put two probes in one table and one in the headline -- a reader
    counting rows would get a different answer from the report's own claim."""
    source = tmp_path / "source"
    (source / "raw").mkdir(parents=True)
    rows = [_round(group="nocxt", index=i, tier=60) for i in range(1, 4)]
    rows += [_round(group="readiness-stream", index=900 + i, status=409,
                    expected_status=409, status_ok=True) for i in range(1, 4)]
    rows += [_round(group="readiness-after", index=990)]
    (source / "rounds.jsonl").write_text(
        "".join(json.dumps(r.as_row(), ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    evidence = tmp_path / "target"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    adopted, note = ext.adopt_previous_run(source, evidence,
                                           skip_groups=ext.READINESS_GROUPS)
    assert {r.group for r in adopted} == {"nocxt"}
    assert note["not_adopted_rows"] == 4
    assert note["not_adopted_rerun_groups"] == sorted(ext.READINESS_GROUPS)


def test_adopting_everything_by_default_keeps_the_readiness_rows(tmp_path):
    """Without a rerun, a ramp-up phase's evidence is exactly what should carry
    over."""
    source = tmp_path / "source"
    (source / "raw").mkdir(parents=True)
    rows = [_round(group="nocxt", index=1, tier=60),
            _round(group="readiness-stream", index=901, status=409,
                   expected_status=409, status_ok=True)]
    (source / "rounds.jsonl").write_text(
        "".join(json.dumps(r.as_row(), ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    evidence = tmp_path / "target"
    evidence.mkdir()
    (evidence / "raw").mkdir()
    adopted, note = ext.adopt_previous_run(source, evidence)
    assert len(adopted) == 2
    assert note["not_adopted_rows"] == 0
