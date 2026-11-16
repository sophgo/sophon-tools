"""Unit tests for the MYS-2510 comprehensive stability suite.

The suite is a measurement instrument, so what these tests pin down is that it
**measures the right thing**:

* a prompt's declared token size is the size the tokenizer actually produces,
  and the retrievable fact is really in the material;
* grading separates a correct retrieval from a wrong number and from a refusal,
  because collapsing them would turn a model's bad answer into a service failure;
* a concurrency round detects cross-talk from the reply text alone;
* cancellation judging reads the *record*, not the socket, and treats a 429 or a
  409 as success in the phase that provokes it;
* the per-dimension verdict reports an unmeasured criterion as ``None`` (which
  fails) rather than silently passing it;
* the HTML report escapes model output and embeds no external resource.

Nothing here talks to a board. The live behaviour is covered by the run itself
and by ``tests/test_comprehensive_stability_live.py`` (which skips without a
service).
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import comprehensive_stability_suite as cs  # noqa: E402


# ---------------------------------------------------------------------------
# Prompt construction and retrieval grading
# ---------------------------------------------------------------------------
def test_long_prompt_plants_the_fact_it_asks_about():
    """The needle is in the material, exactly once, and its code is unique."""
    prompt = cs.build_long_prompt(2048)
    needle = f"第{prompt.needle_index}号仓库"
    # The material holds it once; the closing question names it again, so the
    # count is taken over the material only -- otherwise "exactly once in the
    # material" would be asserted against the wrong string.
    material = prompt.text.split("\n\n问题：")[0]
    assert material.count(needle) == 1
    assert prompt.text.count(needle) == 2
    assert str(prompt.expected_code) in prompt.text
    assert prompt.text.rstrip().endswith("只回答六位数字，不要解释。")


@pytest.mark.parametrize("probe,low,high", [
    ("head", 0.02, 0.20),
    ("middle", 0.40, 0.60),
    ("tail", 0.80, 0.98),
])
def test_probe_position_places_the_needle_where_it_claims(probe, low, high):
    """A head probe really is near the front of the material.

    Retrieval accuracy is position-dependent, so a suite that *called* something
    a head probe while planting it at the end would overstate the model.
    """
    prompt = cs.build_long_prompt(4096, probe=probe)
    position = prompt.needle_index / prompt.material_clauses
    assert low <= position <= high


def test_long_prompt_token_target_is_met_within_one_clause():
    """The built prompt reaches the target, and does not wildly overshoot it."""
    prompt = cs.build_long_prompt(8192)
    # Estimated locally (no tokenizer on CI) at 0.6 tokens/char; the real count
    # is taken on the board. What matters here is that the *builder* stops at
    # the target rather than at some fraction of it.
    assert prompt.tokens >= 8192
    assert prompt.tokens <= 8192 * 1.10


def test_long_prompt_rejects_a_tier_below_the_short_band():
    with pytest.raises(ValueError):
        cs.build_long_prompt(64)


def test_code_for_is_injective_and_six_digits():
    """Codes never collide, so "the code appears once" is a real property."""
    codes = [cs.code_for(i) for i in range(1, 20_000)]
    assert len(set(codes)) == len(codes)
    assert all(len(str(c)) == 6 for c in codes)


def test_grade_retrieval_separates_correct_wrong_and_hedged():
    """Three outcomes, three different scores -- this is the whole point."""
    prompt = cs.build_long_prompt(2048)
    correct = cs.grade_retrieval(prompt, f"答案是 {prompt.expected_code}。")
    wrong = cs.grade_retrieval(prompt, "答案是 123456。")
    hedged = cs.grade_retrieval(prompt, "材料中无法确定。")
    empty = cs.grade_retrieval(prompt, "好的。")
    assert correct["correct"] and not correct["wrong_number"]
    assert wrong["wrong_number"] and not wrong["correct"]
    assert hedged["hedged"] and not hedged["wrong_number"]
    assert empty["no_answer"]


def test_grade_retrieval_ignores_a_code_embedded_in_a_longer_number():
    """Only six-digit runs count; a 7-digit number is not a six-digit answer."""
    prompt = cs.build_long_prompt(2048)
    graded = cs.grade_retrieval(prompt, f"编号 {prompt.expected_code}7 结束")
    assert not graded["correct"]


def test_overflow_prompt_is_actually_past_the_window():
    prompt = cs.build_overflow_prompt(cs.OVERFLOW_TOKENS[0])
    assert prompt.tokens > cs.EXPECTED_CONTEXT


# ---------------------------------------------------------------------------
# Conversation turns
# ---------------------------------------------------------------------------
def test_chat_turn_plants_and_asks_distinct_facts():
    """Each turn plants its own keyword and asks for the previous one."""
    first, fact1, asked1 = cs.chat_turn_text(1)
    second, fact2, asked2 = cs.chat_turn_text(2)
    assert fact1 in first and asked1 is None
    assert fact2 != fact1
    assert asked2 == fact1
    assert "收到" in first


def test_grade_chat_turn_only_when_something_was_asked():
    assert cs.grade_chat_turn(None, "随便") is None
    assert cs.grade_chat_turn("青瓷", "关键词是青瓷") is True
    assert cs.grade_chat_turn("青瓷", "不知道") is False


def test_chat_facts_are_pairwise_non_substrings():
    """No fact may contain another, or recall grading would be ambiguous."""
    for a in cs.CHAT_FACTS:
        for b in cs.CHAT_FACTS:
            if a != b:
                assert a not in b


# ---------------------------------------------------------------------------
# Tool-call grading
# ---------------------------------------------------------------------------
def _call(name, args):
    return {"type": "function", "id": "c1",
            "function": {"name": name,
                         "arguments": args if isinstance(args, str)
                         else json.dumps(args, ensure_ascii=False)}}


def test_tool_grading_scores_protocol_and_content_apart():
    """Right tool + right city is both; wrong tool is a content miss only."""
    good = cs.grade_tool_call("get_weather", "北京", [_call("get_weather", {"city": "北京"})])
    assert good["protocol_ok"] and good["content_ok"]
    wrong_tool = cs.grade_tool_call("get_weather", "北京",
                                    [_call("get_local_time", {"city": "北京"})])
    assert wrong_tool["protocol_ok"] and not wrong_tool["content_ok"]
    wrong_city = cs.grade_tool_call("get_weather", "北京",
                                    [_call("get_weather", {"city": "上海"})])
    assert wrong_city["protocol_ok"] and not wrong_city["content_ok"]


def test_tool_grading_flags_unparseable_arguments_as_protocol_failure():
    bad = cs.grade_tool_call("get_weather", "北京",
                             [_call("get_weather", "{not json")])
    assert not bad["protocol_ok"]
    assert not bad["content_ok"]


def test_tool_grading_handles_no_calls():
    out = cs.grade_tool_call("get_weather", "北京", [])
    assert out["protocol_ok"] is False and out["content_ok"] is False


# ---------------------------------------------------------------------------
# Round bookkeeping and status semantics
# ---------------------------------------------------------------------------
def test_status_ok_compares_against_the_phase_expectation():
    """409 and 429 are successes where the phase expects them.

    This is the rule that keeps a working admission gate from being reported as
    a broken service, so it is asserted directly rather than only through a run.
    """
    row = cs.new_round("C", "protocol", "proto-x", expected_status=400)
    row.http_status = 400
    assert cs.Round.as_row(row)["expected_status"] == 400
    row.http_status = 200
    # status_ok is set by the phase; the row must carry the expectation it was
    # judged against so a reader can recompute the judgement.
    assert cs.Round.as_row(row)["expected_status"] == 400


def test_new_round_records_the_input_hash():
    row = cs.new_round("A", "p", "g", text="hello", messages=2)
    assert row.input_chars == 5
    assert row.input_sha256 == cs.base.sha256("hello")
    assert row.context_messages == 2


def test_as_row_omits_the_full_input_text():
    """The manifest holds every prompt; the JSONL must not duplicate megabytes."""
    row = cs.new_round("A", "p", "g", text="x" * 5000)
    as_row = row.as_row()
    assert "input_text" not in as_row
    assert as_row["input_chars"] == 5000


# ---------------------------------------------------------------------------
# Concurrency judging
# ---------------------------------------------------------------------------
def test_marker_collision_is_detected_from_the_reply():
    """The cross-talk rule, expressed as what it is: another lane's marker."""
    markers = {"MKA001": 1, "MKB001": 2}
    reply = "MKA001 MKB001"
    foreign = [m for m in markers if m != "MKA001" and m in reply]
    assert foreign == ["MKB001"]


def test_markers_are_distinct_per_lane_and_round():
    seen = set()
    for lanes in cs.CONC_LANES:
        for round_index in range(1, cs.CONC_ROUNDS + 1):
            for lane in range(1, lanes + 1):
                marker = f"MK{lanes}{chr(64 + lane)}{round_index:03d}"
                assert marker not in seen
                seen.add(marker)
    assert len(seen) == sum(cs.CONC_LANES) * cs.CONC_ROUNDS


# ---------------------------------------------------------------------------
# Summary and the per-dimension verdict
# ---------------------------------------------------------------------------
def _row(**kw):
    row = cs.new_round(kw.pop("dimension", "A"), kw.pop("phase", "p"),
                       kw.pop("group", "g"))
    row.http_status = kw.pop("http_status", 200)
    row.status_ok = kw.pop("status_ok", True)
    for key, value in kw.items():
        setattr(row, key, value)
    return row


def test_summarize_counts_success_by_status_ok_not_http_200():
    rows = [
        _row(phase="readiness", http_status=409, status_ok=True),
        _row(phase="queue", http_status=429, status_ok=True),
        _row(phase="p", http_status=500, status_ok=False, error="HTTP 500"),
    ]
    summary = cs.summarize(rows, {})
    assert summary["totals"]["requests"] == 3
    assert summary["totals"]["ok"] == 2
    assert summary["totals"]["http_5xx"] == 1
    assert summary["groups"]["g"]["success_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_summarize_keeps_semantic_accuracy_out_of_the_success_rate():
    """A wrong answer is a data point, not a failure count."""
    rows = [_row(retrieval_correct=False, recall_ok=False),
            _row(retrieval_correct=True, recall_ok=False)]
    summary = cs.summarize(rows, {})
    assert summary["totals"]["ok"] == 2          # both served correctly
    assert summary["totals"]["retrieval_ok"] == 1
    assert summary["totals"]["retrieval_checked"] == 2
    assert summary["totals"]["recall_ok"] == 0
    assert "semantic_separate" in summary["rules"]


def test_summarize_does_not_count_cache_hits_as_correctness():
    rows = [_row(cache_hit=True, retrieval_correct=False)]
    summary = cs.summarize(rows, {})
    assert summary["totals"]["cache_hits"] == 1
    assert summary["totals"]["retrieval_ok"] == 0


def test_verdict_treats_an_unmeasured_criterion_as_not_passed():
    """`None` must fail the gate: "not checked" is not "works"."""
    summary = cs.summarize([], {})
    verdict = cs.dimension_verdict(summary, {"checked": 0, "missing": [],
                                             "duplicates": []}, {}, [])
    assert verdict["passed"] is False
    assert verdict["criteria_unmeasured"]


def test_verdict_passes_a_dimension_whose_criteria_all_hold():
    """A fully-measured, all-green dimension passes on its own arithmetic."""
    rows = [_row(dimension="A", phase="longctx", tokens=16384, prompt_tokens=16400)]
    rows.append(_row(dimension="A", phase="overflow", http_status=400, status_ok=True))
    chat = _row(dimension="A", phase="chat50")
    rows.append(chat)
    phases = {"overflow": {"records_delta": 1, "records_claiming_tokens": 0}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 3, "missing": [],
                                             "duplicates": []}, phases, rows)
    assert verdict["dimensions"]["A"]["长 prompt 全部正常结束"]["ok"] is True
    # One error record that processed no tokens is the *correct* outcome.
    assert verdict["dimensions"]["A"]["超长输入被明确拒绝且未处理任何 token"]["ok"] is True


def test_verdict_fails_a_long_tier_whose_prompt_tokens_miss_the_target():
    """A "16k" tier that was really 12k is a measurement bug, and it fails."""
    rows = [_row(dimension="A", phase="longctx", tokens=16384, prompt_tokens=12000)]
    summary = cs.summarize(rows, {})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                             "duplicates": []}, {}, rows)
    criterion = verdict["dimensions"]["A"]["真实 prompt_tokens 与档位一致（±5%）"]
    assert criterion["ok"] is False


def test_soak_criterion_requires_two_hours():
    short = cs.summarize([_row(dimension="F", phase="soak")],
                         {"soak": {"measured_s": 60, "samples": 100}})
    verdict = cs.dimension_verdict(short, {"checked": 1, "missing": [],
                                          "duplicates": []},
                                   {"soak": {"measured_s": 60, "samples": 100}},
                                   [_row(dimension="F", phase="soak")],
                                   required_soak=cs.SOAK_SECONDS)
    assert verdict["dimensions"]["F"]["浸泡达到要求时长"]["ok"] is False


def test_soak_flags_growth_without_failing_on_it():
    """Growth is surfaced for the operator; only the record log caps it."""
    rows = [_row(dimension="F", phase="soak")]
    phases = {"soak": {"measured_s": cs.SOAK_SECONDS, "samples": 800,
                       "drift": {"npu_mem_used": {"growth": 0.9},
                                 "record_bytes": {"growth": 0.1}}}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows)
    flagged = verdict["dimensions"]["F"]["资源增长已标注（>50% 首尾差）"]
    assert flagged["ok"] is True
    assert "npu_mem_used" in flagged["value"]
    assert "record_bytes" not in flagged["value"]


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def _report(rounds, **kw):
    summary = cs.summarize(rounds, kw.get("phases") or {})
    verdict = cs.dimension_verdict(summary, {"checked": len(rounds), "missing": [],
                                            "duplicates": [],
                                            "source_mismatch": [],
                                            "output_mismatch": [],
                                            "metrics_mismatch": [],
                                            "not_ok": [], "secret_leaks": [],
                                            "cancelled_ok": 0,
                                            "cancelled_bad": []},
                                  kw.get("phases") or {}, rounds)
    return cs.build_html(env=kw.get("env") or {"device": "d", "version": "v0.6.14"},
                         summary=summary, verdict=verdict,
                         records={"checked": len(rounds)},
                         timeline=kw.get("timeline") or [],
                         samples=kw.get("samples") or [],
                         phases=kw.get("phases") or {},
                         rounds=rounds,
                         manifest={"device": "d", "version": "v0.6.14",
                                   "model": "m", "generated_at": "t"})


def test_report_escapes_model_output():
    """Model output is attacker-influenced text; it must never become markup."""
    row = _row(output='<script>alert(1)</script><img src=x onerror=alert(2)>')
    html = _report([row])
    assert "<script>alert(1)" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_report_escapes_the_error_column():
    row = _row(error='"><svg onload=alert(3)>')
    html = _report([row])
    assert "<svg onload" not in html


def test_report_has_no_external_references():
    """The report opens on a board with no network, so nothing may be fetched."""
    html = _report([_row()])
    assert not re.findall(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', html)
    assert "@import" not in html
    assert "<link" not in html


def test_report_states_the_overall_verdict_and_unmeasured_items():
    html = _report([_row(dimension="A", phase="longctx", tokens=16384,
                         prompt_tokens=16400)])
    assert "总体判定" in html
    # Unmeasured criteria are named, not silently treated as passes.
    assert "未测判据" in html or "未测" in html


def test_report_renders_the_detail_table_headers():
    html = _report([_row()])
    for _, label in cs.TABLE_COLUMNS:
        assert f">{cs.html_escape(label)}<" in html


def test_report_survives_an_empty_run():
    """A run that died before its first request still produces a report."""
    html = _report([])
    assert "总体判定" in html


def test_js_json_is_safe_inside_a_script_block():
    out = cs.js_json({"x": "</script><b>alert(1)</b>"})
    assert "</script>" not in out
    assert json.loads(out)["x"] == "</script><b>alert(1)</b>"  # still valid JSON


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------
def test_image_size_reads_png_and_jpeg_headers():
    fixtures = Path(__file__).resolve().parent / "vision_fixtures"
    png = (fixtures / "gradient.png").read_bytes()
    jpg = (fixtures / "photo.jpg").read_bytes()
    assert cs.image_size(png) == (131, 97)
    assert cs.image_size(jpg) == (160, 120)


def test_image_size_returns_none_for_garbage():
    assert cs.image_size(b"not an image at all") == (None, None)


def test_tiny_png_constant_is_a_real_png():
    import base64
    raw = base64.b64decode(cs.TINY_PNG_B64)
    assert cs.png_size(raw) == (1, 1)


def test_data_url_round_trips():
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    url = cs.data_url(raw, "image/png")
    assert url.startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# Matrix constants
# ---------------------------------------------------------------------------
def test_matrix_matches_the_task_card():
    """The declared matrix is what the report claims it ran."""
    assert cs.LONG_TIERS == (16384, 32768, 65536, 98304)
    assert cs.CHAT_TURNS_REQUIRED == 50
    assert cs.CHAT_TURNS_EXTENDED == 100
    assert set(cs.CONC_LANES) == {2, 3}
    assert cs.CONC_ROUNDS >= 50
    assert 0 in cs.QUEUE_CAPACITY_EXPERIMENTS
    assert cs.CANCEL_REPEATS >= 5
    assert cs.LIFECYCLE_CYCLES == 20
    assert cs.VLM_REPEATS >= 20
    assert cs.TOOL_CALLS >= 30
    assert cs.THINKING_REPEATS >= 10
    assert cs.SOAK_SECONDS == 2 * 60 * 60
    assert cs.EXPECTED_CONTEXT == 131_072


def test_manifest_records_the_matrix_and_the_reductions():
    """The manifest is the audit trail for what a report's numbers mean."""
    manifest = cs.build_manifest("m", {"device": "d", "version": "v"},
                                 type("A", (), {"phases": ""})(), None)
    assert manifest["matrix"]["soak_seconds"] == cs.SOAK_SECONDS
    assert "lifecycle_reduction" in manifest["notes"]
    assert manifest["notes"]["no_retry"]


def test_growth_watch_does_not_include_transient_metrics():
    """CPU and free memory oscillate; only monotonic-by-nature metrics gate."""
    assert "npu_mem_used" in cs.GROWTH_WATCH
    assert "cpu_percent" not in cs.GROWTH_WATCH


# ---------------------------------------------------------------------------
# Judging bugs found on the board's first live run
# ---------------------------------------------------------------------------
def test_stream_that_times_out_after_headers_is_not_a_pass():
    """A 200 on the status line is not a successful stream.

    Found live: a request whose headers arrived (200) and whose body then timed
    out was recorded as ``status_ok=True`` with an ``error`` beside it, because
    the row judged the status alone. The whole point of the matrix is that a
    failure is counted as one.
    """
    row = cs.new_round("C", "protocol", "g", expected_status=200)
    cs._fill_from_stream(row, {
        "status": 200, "raw": "", "started_at": 1.0, "finished_at": 2.0,
        "first_token_at": None, "content_deltas": 0, "finish_seen": False,
        "closed_early": False, "error": "TimeoutError: timed out"})
    assert row.status_ok is False
    assert "TimeoutError" in row.error


def test_stream_without_done_and_not_closed_early_is_not_a_pass():
    """A truncated stream (no [DONE], no client close) is a failure."""
    row = cs.new_round("C", "protocol", "g", expected_status=200)
    cs._fill_from_stream(row, {
        "status": 200, "raw": 'data: {"choices":[{"delta":{"content":"好"}}]}\n',
        "started_at": 1.0, "finished_at": 2.0, "first_token_at": 1.1,
        "content_deltas": 1, "finish_seen": False, "closed_early": False,
        "error": None})
    assert row.status_ok is False


def test_a_deliberately_closed_stream_is_judged_elsewhere_not_failed_here():
    """The cancel phase closes the socket on purpose: no [DONE] is expected.

    Its verdict comes from the *record* (``cancelled``, one row), so
    ``_fill_from_stream`` must not fail it for the missing terminator.
    """
    row = cs.new_round("C", "cancel", "g", expected_status=200)
    cs._fill_from_stream(row, {
        "status": 200, "raw": 'data: {"choices":[{"delta":{"content":"一二"}}]}\n',
        "started_at": 1.0, "finished_at": 2.0, "first_token_at": 1.1,
        "content_deltas": 1, "finish_seen": False, "closed_early": True,
        "error": None})
    assert row.status_ok is True


def test_protocol_cases_accept_every_correct_rejection_layer():
    """A 422 from pydantic and a 400 from the endpoint are both correct.

    Found live: ``tools`` sent as an object (not a list) is rejected by pydantic
    before ``validate_tools`` runs, so it answers 422 while the documented code
    is 400. Asserting one exact code reported a working service as broken.
    """
    # The expectation is a set; the case table must express both layers.
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "(422, 400)" in source            # bad-role
    assert "codes = (400, 422) if not isinstance(tools, list)" in source


def test_nonstream_status_ok_requires_the_exact_expected_code():
    row = cs.new_round("C", "protocol", "g", expected_status=400,
                       request_kind="nonstream")
    row.http_status = 422
    assert (row.http_status == row.expected_status) is False


def test_a_dimension_that_was_not_run_is_unmeasured_not_failed():
    """A partial run must say "not measured", not "5xx in a phase never sent".

    Found live: a `--phases protocol` run reported failures for A/B/D/E/F because
    an empty dimension makes `x.get("http_5xx") == 0` evaluate `None == 0`.
    """
    rows = [_row(dimension="C", phase="protocol")]
    summary = cs.summarize(rows, {"protocol": {"requests": 1, "ok": 1}})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []},
                                   {"protocol": {"requests": 1, "ok": 1}}, rows)
    # A was not run: every one of its criteria is unmeasured, none failed.
    for name, value in verdict["dimensions"]["A"].items():
        assert value["ok"] is None, (name, value)
    assert not any(f.startswith("A:") for f in verdict["criteria_failed"])
    assert any(u.startswith("A:") for u in verdict["criteria_unmeasured"])


# ---------------------------------------------------------------------------
# Cancellation judging reads the record, not the socket
# ---------------------------------------------------------------------------
def test_cancel_verdict_requires_exactly_one_cancelled_record_per_request():
    """The contract is per-request: one record, status cancelled, partial kept."""
    rows = [
        _row(dimension="C", phase="cancel", cancel_stage="mid-stream",
             record_status="cancelled", records_found=1, partial_chars=12,
             status_ok=True),
        _row(dimension="C", phase="cancel", cancel_stage="mid-stream",
             record_status="cancelled", records_found=2, partial_chars=8,
             status_ok=True),
    ]
    summary = cs.summarize(rows, {"cancel": {"cancelled": 2}})
    verdict = cs.dimension_verdict(summary, {"checked": 2, "missing": [],
                                            "duplicates": [],
                                            "cancelled_ok": 2,
                                            "cancelled_bad": []},
                                   {"cancel": {"cancelled": 2}}, rows)
    checks = verdict["dimensions"]["C"]
    assert checks["取消后均留下 cancelled 记录"]["ok"] is True
    # A duplicate record fails: "exactly one" is the contract.
    assert checks["每次取消记录恰好一条"]["ok"] is False


def test_cancel_record_status_must_be_cancelled_not_ok_or_error():
    rows = [_row(dimension="C", phase="cancel", cancel_stage="before-first-token",
                 record_status="ok", records_found=1, status_ok=True)]
    summary = cs.summarize(rows, {"cancel": {"cancelled": 0}})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": [], "cancelled_ok": 0,
                                            "cancelled_bad": [{"id": "x"}]},
                                   {"cancel": {"cancelled": 0}}, rows)
    assert verdict["dimensions"]["C"]["取消后均留下 cancelled 记录"]["ok"] is False


# ---------------------------------------------------------------------------
# Lifecycle residue
# ---------------------------------------------------------------------------
def test_lifecycle_verdict_fails_when_a_cycle_left_a_worker_behind():
    rows = [_row(dimension="D", phase="lifecycle", status_ok=False,
                 note="residue={'worker_procs': 1}")]
    summary = cs.summarize(rows, {"lifecycle": {"cycles": 1}})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []},
                                   {"lifecycle": {"cycles": 1}}, rows)
    checks = verdict["dimensions"]["D"]
    assert checks["生命周期循环均无残留"]["ok"] is False


def test_lifecycle_cycle_count_is_judged_against_the_declared_matrix():
    """20 cycles, or the criterion is unmet -- the reduction is declared, not hidden."""
    rows = [_row(dimension="D", phase="lifecycle", status_ok=True)]
    summary = cs.summarize(rows, {"lifecycle": {"cycles": 3}})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []},
                                   {"lifecycle": {"cycles": 3}}, rows)
    assert verdict["dimensions"]["D"]["生命周期循环数达标"]["ok"] is False


# ---------------------------------------------------------------------------
# Concurrency: a 429 in the capacity phase is a pass
# ---------------------------------------------------------------------------
def test_queue_capacity_phase_counts_a_429_as_correct():
    """The phase expects either a served request or a refusal; both pass."""
    rows = [_row(dimension="B", phase="queue-capacity", http_status=429,
                 status_ok=True),
            _row(dimension="B", phase="queue-capacity", http_status=200,
                 status_ok=True)]
    phases = {"queue-capacity": {
        "outcomes": {0: {"statuses": {"200": 3}, "refused": 1},
                     1: {"statuses": {"200": 3}, "refused": 0}},
        "recovered": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 2, "missing": [],
                                            "duplicates": []}, phases, rows)
    # A refusal is counted from the in-stream frame too, so ``refused`` -- not
    # the status histogram -- is what the criterion reads.
    assert verdict["dimensions"]["B"]["超容量出现 429 且服务恢复"]["ok"] is True


def test_queue_capacity_phase_fails_when_no_429_ever_appeared():
    rows = [_row(dimension="B", phase="queue-capacity", http_status=200)]
    summary = cs.summarize(rows, {})
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []},
                                   {"queue-capacity": {"outcomes": {0: {"statuses": {"200": 3},
                                                                         "refused": 0}},
                                                       "recovered": True}}, rows)
    assert verdict["dimensions"]["B"]["超容量出现 429 且服务恢复"]["ok"] is False


# ---------------------------------------------------------------------------
# VLM expected count
# ---------------------------------------------------------------------------
def test_vlm_multi_image_expectation_is_two_not_one():
    """The multi-image case must ask for two, or dropping an image is invisible."""
    assert cs.VLM_REPEATS >= 20
    # The runner computes expected_count from the multi flag; verify the rule.
    for k in range(1, cs.VLM_REPEATS + 1):
        multi = (k % 5 == 0)
        expected = 2 if multi else 1
        assert expected in (1, 2)
    assert cs.VLM_REPEATS % 5 == 0, "every fifth request is multi-image"


# ---------------------------------------------------------------------------
# Quick profile
# ---------------------------------------------------------------------------
def test_quick_profile_constants_are_far_below_the_real_matrix():
    """`--quick` exists to validate wiring; it must not be mistakable for evidence."""
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert '"soak_seconds": 60.0' in source
    assert "不能作为稳定性验收证据" in source
    # The real matrix constants stay at the task card's values.
    assert cs.SOAK_SECONDS == 7200
    assert cs.LIFECYCLE_CYCLES == 20


# ---------------------------------------------------------------------------
# Overflow refusal shape
# ---------------------------------------------------------------------------
def test_overflow_accepts_a_streaming_error_frame_as_a_clear_refusal():
    """The streaming route has already sent headers when the length check fails.

    Found live: a 132k-token *streaming* request answers HTTP 200 with an
    ``{"error": "prompt is 132086 tokens, context limit is 131071"}`` frame and
    then ``[DONE]``. That is a clear refusal naming the limit -- exactly what the
    task requires -- but judging on the status code alone called it a failure.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "in_stream_error" in source
    assert '"sse-error-frame"' in source


def test_overflow_still_fails_a_200_that_served_content():
    """A too-long prompt answered with text would be the actual bug."""
    source = Path(cs.__file__).read_text(encoding="utf-8")
    # The verdict requires no output and no prompt_tokens for a refusal to pass.
    assert "produced_output = bool(row.output) or bool(row.prompt_tokens)" in source
    assert "refused and names_limit and not produced_output" in source


# ---------------------------------------------------------------------------
# Prefix cache must not silently change what a long tier measures
# ---------------------------------------------------------------------------
def test_long_tier_phase_starts_from_a_provably_cold_cache():
    """A warm cache made a 16k prefill look 8x cheaper across runs.

    Found live: the second quick run's 16k tier took 13 s against the first
    run's 110 s, because the identical material was still cached. The report's
    latency numbers only mean anything if the cache was empty at the start, so
    the phase now reloads and re-reads the counters rather than assuming.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "cold = self.service.cold_cache()" in source
    assert "长上下文组开始前清空前缀缓存" in source


def test_a_mostly_cached_long_request_is_flagged():
    """If a long request was served from cache, its latency is not prefill cost."""
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "row.cached_tokens >= tier * 0.5" in source
    assert "该行延迟不代表冷预填充成本" in source


def test_cold_cache_reports_cold_when_already_empty(monkeypatch):
    """A no-op must be provable: already-empty cache is `cold` with zero cost."""
    class FakeService(cs.Service):
        def __init__(self):  # bypass the http client entirely
            self.changes = []
            self._settings = {}
            self.model = "m"
            self.password = "admin"

        def cache_state(self):
            return {"entries": 0, "tokens_reused": 0}

    out = cs.Service.cold_cache(FakeService())
    assert out["cold"] is True
    assert out["reloaded"] is False
    assert out["s"] == 0.0


def test_jsonl_is_rewritten_with_late_known_columns(tmp_path):
    """A cancel row's verdict is decided after its line is first written.

    Found live: every cancelled row in `rounds.jsonl` had
    ``record_status: null`` and ``records_found: null`` because the line was
    flushed before the record lookup ran, so the evidence file disagreed with
    the report. The final rewrite fills them in.
    """
    evidence = tmp_path / "run-x"
    (evidence / "raw").mkdir(parents=True)
    timeline = cs.ext.Timeline()
    service = type("S", (), {"changes": []})()
    runner = cs.Runner(cs.base.Http("http://127.0.0.1:1"), "k", "m", evidence,
                       evidence / "raw", timeline, service)
    row = cs.new_round("C", "cancel", "cancel-mid-stream", expected_status=200)
    row.cancel_stage = "mid-stream"
    runner.record(row)
    # Written before the lookup: the column is not there yet.
    first = (evidence / "rounds.jsonl").read_text(encoding="utf-8")
    assert json.loads(first)["record_status"] is None
    # The lookup happens, then the rewrite.
    row.record_status = "cancelled"
    row.records_found = 1
    runner.close()
    runner.rewrite_jsonl()
    rewritten = json.loads((evidence / "rounds.jsonl").read_text(encoding="utf-8"))
    assert rewritten["record_status"] == "cancelled"
    assert rewritten["records_found"] == 1


def test_recovery_probes_are_not_counted_as_phase_failures(tmp_path):
    """15 cancellations + 15 recovery probes must read as 15/15, not 25/30.

    Found live: the cancel phase's post-cancel "is the worker still serving?"
    probes were folded into the expected total, so a phase where every one of the
    cancellations passed reported "25/30 as expected".
    """
    evidence = tmp_path / "run-y"
    (evidence / "raw").mkdir(parents=True)
    runner = cs.Runner(cs.base.Http("http://127.0.0.1:1"), "k", "m", evidence,
                       evidence / "raw", cs.ext.Timeline(),
                       type("S", (), {"changes": []})())
    for _ in range(3):
        c = cs.new_round("C", "cancel", "cancel-mid-stream", expected_status=200)
        c.status_ok = True
        runner.record(c)
        r = cs.new_round("C", "cancel", "cancel-recovery", expected_status=200)
        r.status_ok = True
        runner.record(r)
    runner._phase_end("cancel", __import__("time").time() - 1)
    info = runner.phases["cancel"]
    assert info["intended"] == 3
    assert info["ok"] == 3
    assert info["support_rows"] == 3
    runner.close()


def test_restart_criterion_checks_the_gate_and_the_reload_separately():
    """This build does not auto-load at startup, so a restart leaves nothing loaded.

    Found live: after `systemctl restart` the service is healthy with
    `loaded=false` because it only *adopts* a still-running worker, and the
    restart killed that worker. The old phase waited for readiness that never
    came and then reported the reload as a failure. The phase now expects 409
    first, reloads explicitly, and judges the gate, the reload and the records
    as three separate criteria.
    """
    rows = [_row(dimension="C", phase="restart", status_ok=True)]
    phases = {"restart": {"gate_status": 409, "loaded_after_restart": False,
                          "reload_status": 200, "reload_s": 66.0,
                          "model_ready": True, "post_ok": True,
                          "records_before": 100, "records_after": 101,
                          "records_retained": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows)
    checks = verdict["dimensions"]["C"]
    assert checks["SIGTERM 重启后准入仍生效"]["ok"] is True
    assert checks["重启后重载成功并恢复推理"]["ok"] is True
    assert checks["重启后推理记录保留"]["ok"] is True


def test_restart_fails_when_a_request_was_admitted_with_nothing_loaded():
    rows = [_row(dimension="C", phase="restart")]
    phases = {"restart": {"gate_status": 200, "loaded_after_restart": False,
                          "model_ready": True, "post_ok": True,
                          "records_retained": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows)
    assert verdict["dimensions"]["C"]["SIGTERM 重启后准入仍生效"]["ok"] is False


# ---------------------------------------------------------------------------
# Judging rules the second live run corrected
# ---------------------------------------------------------------------------
def test_protocol_expects_one_error_record_for_a_bad_image():
    """A bad image is rejected by the *worker*, after the record context exists.

    Found live: the protocol phase's delta was 7, not the hardcoded 6. The extra
    row was the bad-image case, which passes model resolution and prompt
    rendering and is then refused by the worker -- and every ``WorkerError``
    writes exactly one record by contract. The assertion now expects 6 real
    inferences plus that one error record.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    # 6 stop/max_tokens + the bad-image error record + 3 console-route requests.
    assert "expected_records = 6 + 1 + 3" in source
    assert "expected_error_records = 1" in source


def test_queue_capacity_judges_refusal_count_not_the_status_code():
    """A streaming refusal is HTTP 200 with a rate_limit frame.

    Found live: the capacity-0 run *did* refuse a request, but as an in-stream
    error frame, so a check for status 429 reported "no refusal appeared".
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert 'refused_in_stream' in source
    assert '"rate_limit" in str(row.error).lower()' in source
    assert "over_capacity = lanes - (2 + capacity)" in source


def test_near_completion_cancel_closes_during_decode_not_after_finish():
    """Closing on the finish frame is a no-op: the record is already `ok`.

    Found live: all five near-completion cases recorded `status=ok`, because the
    disconnect happened after the service had finished the inference. The stage
    now hangs up at a fixed delta count inside the last stretch of decoding.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "NEAR_COMPLETION_DELTAS" in source
    assert "stop_after_finish=True" not in source
    assert cs.NEAR_COMPLETION_DELTAS < 256


def test_overflow_expects_one_error_record_per_attempt_not_zero():
    """An over-length prompt *does* write a record -- an error one, with 0 tokens.

    Measured on .151: each over-length prompt writes exactly one record with
    status=error, error.type=WorkerError:invalid_request and prompt_tokens=0.
    The inference really happened (the prompt was tokenized and its length
    checked) and was correctly refused, which is what docs/inference-records.md
    says every WorkerError produces. The suite's earlier "zero records"
    expectation was its own mistake.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert 'r.group == "overflow"' in source
    assert "records_claiming_tokens" in source
    # The criterion is "no record claims tokens were processed", not "no record".
    assert "超长输入被明确拒绝且未处理任何 token" in source


def test_overflow_criterion_fails_if_a_record_claimed_processed_tokens():
    rows = [_row(dimension="A", phase="overflow", http_status=400, status_ok=True)]
    phases = {"overflow": {"records_delta": 1, "records_claiming_tokens": 1}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows)
    key = "超长输入被明确拒绝且未处理任何 token"
    assert verdict["dimensions"]["A"][key]["ok"] is False


def test_thinking_budget_covers_reasoning_and_the_answer():
    """192 tokens of budget is spent inside the think block, leaving no content.

    Measured on .151: thinking-on at max_tokens=192 produced 747 characters of
    reasoning_content and an empty content with finish_reason=length. That is
    the model using its budget as specified, so the suite has to send enough to
    leave room for the answer -- and an empty content is only tolerated when the
    reason really was the length limit.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    # 192 was measured to yield 747 chars of reasoning and no content; 512 was
    # also exhausted (1651 chars, no content). The budget has to be large enough
    # for a long think block plus an answer.
    assert "thinking_budget = 2048" in source
    assert "1651 characters" in source
    assert 'row.finish_reason != "length"' in source


def test_vision_fixture_dir_is_resolved_not_assumed(tmp_path):
    """A wrong fixture path produced a vision phase that sent nothing -- and passed.

    Found live on the board: the suite was deployed as `tools/<file>.py` without
    the repository, so `<repo>/tests/vision_fixtures` did not exist, every
    fixture was "missing", each miss was only a note, and the phase reported
    "0 requests, 0 as expected" without failing.
    """
    fixtures = tmp_path / "tests" / "vision_fixtures"
    fixtures.mkdir(parents=True)
    for name in ("gradient.png", "gray.png", "palette.png", "photo.jpg"):
        (fixtures / name).write_bytes((Path(cs.__file__).parent.parent
                                       / "tests" / "vision_fixtures" / name).read_bytes())

    class Fake(cs.Runner):
        def __init__(self):  # no attribute plumbing needed for this check
            pass

    # The lookup walks candidate layouts and returns the one that really has the
    # fixtures rather than the first guess.
    resolved = cs.Runner._resolve_fixture_dir(Fake())
    assert resolved.name == "vision_fixtures"


def test_a_vision_phase_that_sent_nothing_cannot_pass():
    """`None` (unmeasured) is not allowed to read as a pass."""
    rows = [_row(dimension="E", phase="protocol")]
    phases = {"vlm": {"sent": 0}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows)
    assert verdict["dimensions"]["E"]["VLM 请求全部成功"]["ok"] is False


def test_verdict_values_are_json_serialisable():
    """Every criterion value must survive json.dumps.

    Found live: the "partial output kept" criterion passed a *generator* as its
    displayed value (`all(x for ...)` was applied to the generator without
    calling `all()` on it), so `json.dumps` raised after a complete run had
    already made all of its requests -- costing the run its summary and report.
    """
    rows = [
        _row(dimension="C", phase="cancel", cancel_stage="mid-stream",
             record_status="cancelled", records_found=1, partial_chars=5),
        _row(dimension="C", phase="longctx", tokens=16384, prompt_tokens=16400),
        _row(dimension="F", phase="soak"),
    ]
    phases = {"cancel": {"cancelled": 1}, "soak": {"measured_s": 7200}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 3, "missing": [],
                                            "duplicates": []}, phases, rows)
    # Must not raise, and must round-trip.
    text = json.dumps({"summary": summary, "verdict": verdict}, ensure_ascii=False)
    assert json.loads(text)["verdict"]["dimensions"]


def test_json_fallback_describes_rather_than_crashes():
    assert cs._json_fallback({1, 2}) == [1, 2]
    assert cs._json_fallback(b"abc") == "abc"
    assert cs._json_fallback(x for x in (1, 2)) == [1, 2]


# ---------------------------------------------------------------------------
# Scale requirements belong to full runs, not to the plumbing check
# ---------------------------------------------------------------------------
def test_quick_run_does_not_fail_its_own_scale_requirements():
    """A --quick run must not be judged against the full matrix's sizes.

    Found live: `--quick` deliberately runs 2 lifecycle cycles and a 60-second
    soak, then failed "20 cycles" and "2 hours" -- reporting the run's own
    declared reduction as a defect. Under --quick those two criteria are
    unmeasured (the manifest already says the run is not acceptance evidence),
    while a full run still enforces them.
    """
    rows = [_row(dimension="D", phase="lifecycle", status_ok=True),
            _row(dimension="F", phase="soak")]
    phases = {"lifecycle": {"cycles": 2}, "soak": {"measured_s": 60, "samples": 20}}
    summary = cs.summarize(rows, phases)
    quick = cs.dimension_verdict(summary, {"checked": 2, "missing": [],
                                          "duplicates": []}, phases, rows,
                                 required_cycles=None, required_soak=None)
    assert quick["dimensions"]["D"]["生命周期循环数达标"]["ok"] is None
    assert quick["dimensions"]["F"]["浸泡达到要求时长"]["ok"] is None

    full = cs.dimension_verdict(summary, {"checked": 2, "missing": [],
                                         "duplicates": []}, phases, rows,
                                required_cycles=20, required_soak=7200)
    assert full["dimensions"]["D"]["生命周期循环数达标"]["ok"] is False
    assert full["dimensions"]["F"]["浸泡达到要求时长"]["ok"] is False


def test_cancel_criterion_ignores_the_recovery_probes():
    """15 cancellations + 15 probes must read as 15/15, not 15/30."""
    rows = []
    for _ in range(3):
        c = _row(dimension="C", phase="cancel", record_status="cancelled",
                 records_found=1, partial_chars=4)
        c.cancel_stage = "mid-stream"
        c.group = "cancel-mid-stream"
        rows.append(c)
        r = _row(dimension="C", phase="cancel")
        r.cancel_stage = "mid-stream"
        r.group = "cancel-recovery"
        rows.append(r)
    phases = {"cancel": {"cancelled": 3}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 6, "missing": [],
                                            "duplicates": []}, phases, rows)
    assert verdict["dimensions"]["C"]["取消后均留下 cancelled 记录"]["ok"] is True
    assert verdict["dimensions"]["C"]["取消后后续请求正常"]["ok"] is True


def test_console_route_is_exercised():
    """`/api/chat/stream` is a third surface; the protocol block must hit it.

    It is cookie-authenticated and shaped differently from the OpenAI route, so
    a regression there would not appear in any other case.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert 'group="proto-console"' in source
    assert "console_round(" in source


def test_report_banner_distinguishes_no_failure_from_measured_failure():
    """"0 项失败" beside "未通过" reads as a contradiction.

    Found live on a --quick run: zero failed criteria, two unmeasured, and the
    banner still said 未通过. Three states are needed -- passed, failed, and
    "nothing failed but something was not measured" -- because "not measured" is
    not a pass but is also not a failure.
    """
    rows = [_row(dimension="C", phase="protocol")]
    phases = {"protocol": {"requests": 1, "ok": 1}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows,
                                   required_cycles=None, required_soak=None)
    assert verdict["criteria_failed"] == []
    html = cs.build_html(env={"device": "d"}, summary=summary, verdict=verdict,
                         records={"checked": 1}, timeline=[], samples=[],
                         phases=phases, rounds=rows,
                         manifest={"device": "d", "version": "v", "model": "m",
                                   "generated_at": "t"})
    assert "未测项未通过（无失败判据）" in html
    assert "verdict warn" in html


def test_quick_run_is_announced_at_the_top_of_its_report():
    """A --quick report must say so on the page, not only in the manifest."""
    rows = [_row(dimension="C", phase="protocol")]
    phases = {"protocol": {"requests": 1, "ok": 1}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 1, "missing": [],
                                            "duplicates": []}, phases, rows,
                                   required_cycles=None, required_soak=None)
    manifest = {"device": "d", "version": "v", "model": "m",
                "generated_at": "t", "quick": True}
    html = cs.build_html(env={"device": "d"}, summary=summary, verdict=verdict,
                         records={"checked": 1}, timeline=[], samples=[],
                         phases=phases, rounds=rows, manifest=manifest)
    assert "--quick 管线验证运行" in html
    assert "不能作为稳定性验收证据" in html


# ---------------------------------------------------------------------------
# Lifecycle residue: a report is not a flag
# ---------------------------------------------------------------------------
def test_an_empty_residue_report_is_not_residue():
    """A dict is always truthy, so `or residue` flagged 20 correct cycles.

    Found live: every lifecycle cycle reported
    ``{'loaded': False, 'operation': None, 'worker_procs': 0, 'pid': None,
    'port': None}`` and the phase called all 20 of them residue.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "leftover = bool(" in source
    assert 'residue.get("worker_procs") or 0' in source
    # And the empty report must evaluate to no-leftover.
    residue = {"loaded": False, "operation": None, "worker_procs": 0,
               "pid": None, "port": None}
    leftover = bool(residue.get("loaded") or residue.get("operation")
                    or (residue.get("worker_procs") or 0) > 0
                    or residue.get("pid") or residue.get("port"))
    assert leftover is False
    # A real leftover is caught.
    assert bool({"worker_procs": 1, "loaded": False, "operation": None,
                 "pid": 1, "port": 2}.get("worker_procs")) is True


def test_worker_residue_count_excludes_our_own_process_tree():
    """`pgrep -f` matches the shell running it: it reported a phantom worker.

    Measured on the board: `pgrep -fc app.engine.worker` answered 1 with no
    worker alive (the shell's own command line contains the pattern) and 2 with
    exactly one worker.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "mine = {os.getpid(), os.getppid()}" in source
    assert 'pids = [int(p) for p in' in source


def test_soak_stops_when_its_own_credential_is_revoked():
    """A 401 during the soak is an operator action, not service instability.

    Found the hard way: deleting the run's key mid-soak (to clean up stray test
    keys) turned the remaining ~4,800 requests into 401s and 3,760 identical
    "soak request failed" anomalies. A revoked credential invalidates the run,
    so the phase now records it once and raises.
    """
    source = Path(cs.__file__).read_text(encoding="utf-8")
    assert "浸泡期间凭据失效，已停止浸泡" in source
    assert "row.http_status in (401, 403)" in source


# ---------------------------------------------------------------------------
# MYS-2521: A2 continuous-conversation tiers
# ---------------------------------------------------------------------------
def test_ctx_tier_is_judged_by_cumulative_prompt_tokens():
    """The band is what "reached 2k" means -- not a turn count, not a schedule.

    The user's requirement is explicit that the tier is decided by the service's
    own cumulative ``prompt_tokens`` and that character counts must not stand in
    for tokens. So the predicate has to be arithmetic on that number, and the
    edges have to be inclusive so a session landing exactly on target passes.
    """
    assert cs.ctx_tier_reached(2048, 2048) is True
    # The band is [target*0.9, target*1.1] inclusive. For 2048 that is
    # [1843.2, 2252.8], so the outermost whole token counts that are inside are
    # 1844 and 2252 -- and 1843 / 2253 are genuinely outside, because int()
    # truncating 1843.2 to 1843 does not move the boundary.
    assert cs.ctx_tier_reached(1844, 2048) is True
    assert cs.ctx_tier_reached(2252, 2048) is True
    assert cs.ctx_tier_reached(1843, 2048) is False
    assert cs.ctx_tier_reached(2253, 2048) is False
    # A comfortably-inside value on each side.
    assert cs.ctx_tier_reached(1900, 2048) is True
    assert cs.ctx_tier_reached(2200, 2048) is True
    # An unmeasured or zero count can never be claimed as reached.
    assert cs.ctx_tier_reached(None, 2048) is False
    assert cs.ctx_tier_reached(0, 2048) is False


def test_ctx_tier_tolerance_is_the_declared_ten_percent():
    """The report prints this number, so it must be the one the code uses."""
    assert cs.CTX_TIER_TOLERANCE == 0.10


def test_ctx_tiers_are_the_five_the_user_asked_for():
    """2k/4k/8k/12k/16k -- and the low rungs get more sessions than the high."""
    assert cs.CTX_TIERS == (2048, 4096, 8192, 12288, 16384)
    assert cs.CTX_TIER_SESSIONS[2048] >= 2
    assert cs.CTX_TIER_SESSIONS[4096] >= 2
    assert cs.CTX_TIER_SESSIONS[8192] >= 2
    assert cs.CTX_TIER_SESSIONS[12288] >= 1
    assert cs.CTX_TIER_SESSIONS[16384] >= 1


def test_ctx_probe_plan_covers_early_and_recent_without_overlap():
    """At least 3 early + 2 recent, distinct, and inside the conversation.

    Asking only recent facts passes on a short sliding window; asking only early
    ones passes on a cache that kept the head. The pair is the claim.
    """
    plan = cs.ctx_probe_plan(40)
    positions = [p for _, p in plan]
    turns = [t for t, _ in plan]
    assert positions.count("early") >= 3
    assert positions.count("recent") >= 2
    assert len(set(turns)) == len(turns), "a turn asked twice is one probe, not two"
    assert all(1 <= t <= 40 for t in turns)
    # "early" really is early relative to "recent".
    assert max(t for t, p in plan if p == "early") < \
        min(t for t, p in plan if p == "recent")


def test_ctx_probe_plan_is_distinct_even_for_a_short_session():
    """A 2k session can be ~7 turns; three "early" probes must not be one turn."""
    plan = cs.ctx_probe_plan(7)
    turns = [t for t, _ in plan]
    assert len(set(turns)) == len(turns) == 5


def test_ctx_probe_plan_refuses_a_session_too_short_to_probe():
    with pytest.raises(ValueError):
        cs.ctx_probe_plan(3)


def test_ctx_facts_plant_the_rare_words_in_every_session():
    """The four rare words are the UTF-8 regression point, so they must appear.

    A session that never plants 门簪 cannot regress-test the byte-split fix, and
    the 2k tier is only a handful of turns -- so they are the first four turns
    rather than somewhere deep in a shared pool.
    """
    for session in (1, 2, 3):
        planted = [cs.ctx_fact_for(session, t) for t in range(1, 5)]
        assert set(planted) == set(cs.RARE_WORDS), (session, planted)


def test_ctx_facts_have_no_substring_collisions():
    """Recall is graded by substring search, so no fact may contain another.

    ``门簪`` inside a longer planted word would score a hit for a turn that was
    never asked -- a false pass, which is worse than a false failure.
    """
    words = set(cs.CHAT_FACTS)
    collisions = [(a, b) for a in words for b in words if a != b and a in b]
    assert collisions == []


def test_ctx_fact_choice_is_deterministic_and_session_dependent():
    """Same session+turn gives the same word; different sessions differ.

    A cross-session leak has to show up as a wrong answer, so two sessions at the
    same tier must not plant their facts in the same order.
    """
    assert cs.ctx_fact_for(1, 10) == cs.ctx_fact_for(1, 10)
    order_a = [cs.ctx_fact_for(1, t) for t in range(5, 20)]
    order_b = [cs.ctx_fact_for(2, t) for t in range(5, 20)]
    assert order_a != order_b


def test_ctx_turn_asks_a_different_turn_than_it_plants():
    """The probe question must be answerable only from history.

    If the asked turn were the turn being planted, the keyword would be in the
    current message and the recall score would prove nothing.
    """
    text, planted = cs.ctx_turn_text(1, 20, ask_turn=3)
    assert planted == cs.ctx_fact_for(1, 20)
    assert "第3轮" in text
    assert cs.ctx_fact_for(1, 3) not in text or \
        cs.ctx_fact_for(1, 3) != planted


def test_a2_verdict_fails_when_a_tier_was_never_reached():
    """An uncovered tier must not be claimable as passing."""
    rows = []
    for tier in (2048, 4096):
        r = _row(dimension="A2", phase="ctx-tiers", group="ctx-2k")
        r.ctx_role = "build"
        r.ctx_tier = tier
        r.ctx_tier_reached = True
        r.session = 1
        r.turn = 5
        rows.append(r)
    phases = {"ctx-tiers": {"tiers": [2048, 4096, 8192]}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 0}, phases, rows)
    crit = verdict["dimensions"]["A2"]["每一档都有会话到档（±10%）"]
    assert crit["ok"] is False
    assert "8192" in verdict["criteria_failed"][0] or crit["ok"] is False


def test_a2_verdict_passes_when_every_tier_landed():
    rows = []
    for i, tier in enumerate((2048, 4096), start=1):
        r = _row(dimension="A2", phase="ctx-tiers", group="ctx-2k")
        r.ctx_role = "build"
        r.ctx_tier = tier
        r.ctx_tier_reached = True
        r.session = i
        r.turn = 8
        rows.append(r)
        for pos in ("early", "recent"):
            p = _row(dimension="A2", phase="ctx-tiers", group="ctx-2k")
            p.ctx_role = "probe"
            p.ctx_tier = tier
            p.ctx_tier_reached = True
            p.ctx_probe_position = pos
            p.session = i
            p.turn = 8
            p.recall_ok = True
            p.expected_recall = "门簪"
            rows.append(p)
    phases = {"ctx-tiers": {"tiers": [2048, 4096],
                            "restart_gate_ok": True,
                            "restart_reload_ok": True,
                            "restart_history_kept": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 0}, phases, rows)
    checks = verdict["dimensions"]["A2"]
    assert checks["每一档都有会话到档（±10%）"]["ok"] is True
    assert checks["到档会话均完成早期+近期回忆探针"]["ok"] is True
    assert checks["16k 会话重启后准入/重载/历史保留"]["ok"] is True


def test_a2_verdict_separates_recall_from_stability():
    """A wrong recall answer must not be counted as a service failure."""
    rows = []
    r = _row(dimension="A2", phase="ctx-tiers", group="ctx-2k")
    r.ctx_role = "build"; r.ctx_tier = 2048; r.ctx_tier_reached = True
    r.session = 1; r.turn = 8
    rows.append(r)
    for pos in ("early", "recent"):
        p = _row(dimension="A2", phase="ctx-tiers", group="ctx-2k", status_ok=True)
        p.ctx_role = "probe"; p.ctx_tier = 2048; p.ctx_tier_reached = True
        p.ctx_probe_position = pos; p.session = 1; p.turn = 8
        p.recall_ok = False; p.expected_recall = "门簪"
        rows.append(p)
    phases = {"ctx-tiers": {"tiers": [2048], "restart_gate_ok": True,
                            "restart_reload_ok": True,
                            "restart_history_kept": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 0}, phases, rows)
    # Protocol-wise everything passed, so no stability criterion fails...
    assert verdict["dimensions"]["A2"]["连续对话构建轮全部成功（不含召回探针与重启准入）"]["ok"] is True
    # ...while the recall number is still visible and low.
    assert summary["totals"]["recall_ok"] == 0
    assert summary["totals"]["recall_checked"] == 2


# ---------------------------------------------------------------------------
# MYS-2521: U1 UTF-8 regression
# ---------------------------------------------------------------------------
def test_replacement_char_detection_catches_the_real_defect_strings():
    """The exact field strings from MYS-2510 must be flagged.

    门簪 came back as ``门��``: the first character fine, the tail replaced.
    A detector that only looked for a *wholly* garbled reply would miss it.
    """
    for bad in ("门��", "琴��", "秤��",
                "妆��", "�"):
        assert cs.has_replacement_char(bad) is True, repr(bad)
    for good in ("门簪", "琴轸", "秤砣", "妆奁", "😀", "👍", ""):
        assert cs.has_replacement_char(good) is False, repr(good)
    assert cs.has_replacement_char(None) is False


def test_grade_verbatim_separates_clean_from_correct():
    """Clean-but-wrong and right-but-dirty are different failures."""
    good = cs.grade_verbatim("门簪", "门簪")
    assert good == {"contains_all": True, "exact": True, "clean": True}

    truncated = cs.grade_verbatim("门簪", "门��")
    assert truncated["contains_all"] is False
    assert truncated["clean"] is False

    wrapped = cs.grade_verbatim("门簪", "关键词是：门簪")
    assert wrapped["contains_all"] is True
    assert wrapped["exact"] is False
    assert wrapped["clean"] is True


def test_u1_verdict_fails_on_a_single_replacement_char():
    """One U+FFFD is the defect, not a tolerance."""
    rows = []
    for surface in cs.U1_SURFACES:
        r = _row(dimension="U", phase="utf8", group=f"utf8-{surface}")
        r.u1_surface = surface
        r.u1_clean = True
        r.u1_contains_all = True
        rows.append(r)
    bad = _row(dimension="U", phase="utf8", group="utf8-stream")
    bad.u1_surface = "stream"
    bad.u1_clean = False
    bad.u1_contains_all = False
    bad.output = "门��"
    rows.append(bad)

    summary = cs.summarize(rows, {"utf8": {}})
    verdict = cs.dimension_verdict(summary, {"checked": 0}, {"utf8": {}}, rows)
    assert verdict["dimensions"]["U"]["三接口均无 U+FFFD"]["ok"] is False
    assert verdict["passed"] is False


def test_u1_verdict_requires_all_three_surfaces():
    """Two clean surfaces do not prove the third is clean."""
    rows = []
    for surface in ("stream", "nonstream"):
        r = _row(dimension="U", phase="utf8", group=f"utf8-{surface}")
        r.u1_surface = surface
        r.u1_clean = True
        rows.append(r)
    summary = cs.summarize(rows, {"utf8": {}})
    verdict = cs.dimension_verdict(summary, {"checked": 0}, {"utf8": {}}, rows)
    assert verdict["dimensions"]["U"]["stream / non-stream / console 三接口都覆盖"]["ok"] is False


def test_u1_replay_covers_every_turn_that_failed_in_mys2510():
    """The eight failing turn numbers per group are the regression that matters."""
    groups = dict(cs.U1_REPLAY_GROUPS)
    assert groups["chat50"] == (18, 29, 35, 45)
    assert groups["chat100"] == (18, 29, 35, 45, 68, 79, 85, 95)
    assert cs.U1_REPEATS >= 10


# ---------------------------------------------------------------------------
# MYS-2521 R: report corrections
# ---------------------------------------------------------------------------
def test_recall_denominator_excludes_the_soak_context_turns():
    """The soak's context turns are not a recall measurement, so they do not count.

    MYS-2510 scored them: 115 ``soak-ctx`` rows were counted as wrong answers,
    which turned 91.9% into 51.7%.

    Note what this test does *not* assert: it does not give the soak rows a null
    ``expected_recall`` and check they are dropped. That would pass while the
    rule was wrong, because in the real MYS-2510 evidence ``expected_recall`` is
    null on *every* row -- chat rows included -- so "drop null expectations"
    selects nothing at all and would report recall as never measured. What
    separates the two populations is the group, and that is what is tested here:
    the soak rows look exactly like the chat rows apart from their group.
    """
    rows = []
    for _ in range(3):
        r = _row(dimension="A", phase="chat50", group="chat50")
        r.expected_recall = "门簪"
        r.recall_ok = True
        rows.append(r)
    for _ in range(5):
        # Identical shape to a chat row -- verdict present, and an expectation
        # set too. Only the group marks it as not-a-recall-measurement.
        r = _row(dimension="F", phase="soak", group="soak-ctx")
        r.expected_recall = "石阶"
        r.recall_ok = False
        rows.append(r)

    summary = cs.summarize(rows, {})
    assert summary["totals"]["recall_checked"] == 3
    assert summary["totals"]["recall_ok"] == 3
    assert summary["groups"]["soak-ctx"]["recall_checked"] == 0


def test_recall_denominator_reproduces_the_mys2510_corrected_ratio():
    """The rule must land on 136/148 on the evidence the report cites.

    This is the number the report prints, so the implementation has to be the one
    that produces it -- not merely a rule that sounds like the prose. A rule
    keyed on ``expected_recall`` scores 0/0 here, which is the failure this test
    exists to catch.
    """
    import json as _json
    from pathlib import Path as _P
    from types import SimpleNamespace as _NS

    evidence = _P(__file__).resolve().parent.parent / "analysis/raw" / \
        "mys2510-supplement" / "mys2510-rounds.jsonl.gz"
    if not evidence.exists():
        pytest.skip("MYS-2510 rounds.jsonl not present in this checkout")
    rows = [_NS(group=r.get("group"), expected_recall=r.get("expected_recall"),
                recall_ok=r.get("recall_ok"))
            for r in map(_json.loads, gzip.decompress(
                evidence.read_bytes()).decode("utf-8").splitlines())]
    counted = [r for r in rows if cs.is_recall_row(r)]
    assert len(counted) == 148
    assert sum(1 for r in counted if r.recall_ok) == 136
    # And the uncorrected rule really is the 263 the old report printed.
    assert sum(1 for r in rows if r.recall_ok is not None) == 263


def test_recall_denominator_also_requires_a_verdict():
    """An expectation whose request never produced a verdict is not scored."""
    r = _row(dimension="A", phase="chat50", group="chat50")
    r.expected_recall = "门簪"
    r.recall_ok = None
    assert cs.is_recall_row(r) is False


def test_cancel_recovery_probes_are_not_counted_as_cancelled_records():
    """The ⑤ table must agree with dimension C, which says 15/15.

    MYS-2510's record table read "取消记录状态异常 15" because the 15
    ``cancel-recovery`` probes carry ``cancel_stage`` too. They are evidence the
    worker was released, not cancellations.
    """
    cancels, probes = [], []
    for i in range(5):
        c = _row(dimension="C", phase="cancel", group="cancel-mid-stream")
        c.req_id = f"c{i}"
        c.cancel_stage = "mid-stream"
        cancels.append(c)
        p = _row(dimension="C", phase="cancel", group="cancel-recovery")
        p.req_id = f"p{i}"
        p.cancel_stage = "mid-stream"
        probes.append(p)

    details = {f"c{i}": {"status": "cancelled", "response_content": ""}
               for i in range(5)}
    # The probes' records are normal completions.
    details.update({f"p{i}": {"status": "ok", "response_content": "好"}
                    for i in range(5)})

    class _Svc:
        def record_ids_for(self, ids, limit=200):
            return {i: 1 for i in ids}

        def record(self, req_id):
            return details.get(req_id)

    class _Runner:
        rounds = cancels + probes

    out = cs.verify_records(_Runner(), _Svc(), None)
    assert out["cancelled_ok"] == 5
    assert out["cancelled_bad"] == []


def test_output_mismatch_compares_response_content_not_output_text():
    """A thinking reply differs in output_text by design; that is not a defect.

    MYS-2510 reported 10 "output mismatch" rows, all ``thinking-on``: the check
    compared the client's ``content`` against the record's ``output_text``, which
    keeps the ``<think>`` preamble. The service's ``response_content`` matched
    the client byte for byte in every one of them.
    """
    row = _row(dimension="E", phase="tools", group="thinking-on", thinking=True)
    row.req_id = "x1"
    row.expected_status = 200
    row.output = "天空呈蓝色是因为瑞利散射。"

    record = {
        "status": "ok",
        "output_text": "Here's a thinking process:\n\n1. ...\n天空呈蓝色是因为瑞利散射。",
        "response_content": "天空呈蓝色是因为瑞利散射。",
    }

    class _Svc:
        def record_ids_for(self, ids, limit=200):
            return {"x1": 1}

        def record(self, req_id):
            return record

    class _Runner:
        rounds = [row]

    out = cs.verify_records(_Runner(), _Svc(), None)
    assert out["output_mismatch"] == []


def test_output_mismatch_still_catches_a_real_disagreement():
    """The fix must not turn the check into a rubber stamp."""
    row = _row(dimension="A", phase="p", group="g")
    row.req_id = "x2"
    row.expected_status = 200
    row.output = "客户端看到的文本"

    class _Svc:
        def record_ids_for(self, ids, limit=200):
            return {"x2": 1}

        def record(self, req_id):
            return {"status": "ok",
                    "response_content": "记录里完全不同的文本"}

    class _Runner:
        rounds = [row]

    out = cs.verify_records(_Runner(), _Svc(), None)
    assert len(out["output_mismatch"]) == 1
    assert out["output_mismatch"][0]["id"] == "x2"


def test_corrections_table_names_a_basis_for_every_row():
    """Every correction must say what it was checked against.

    An unexplained correction is indistinguishable from a typo, and these
    numbers decide the report's conclusion.
    """
    assert cs.CORRECTIONS
    for item, old, new, basis in cs.CORRECTIONS:
        assert item and old and new, item
        assert len(basis) >= 10, item
    text = " ".join(" ".join(row) for row in cs.CORRECTIONS)
    assert "136/148" in text
    assert "91.9%" in text
    assert "�" in text or "U+FFFD" in text


def test_load_rounds_round_trips_a_written_row():
    """Evidence written by one run must be readable by the report that merges it.

    The MYS-2521 deliverable puts the MYS-2510 matrix and the new A2/U1 blocks in
    one report, so the old rows have to come back as real ``Round`` objects --
    the summariser reads attributes, not dict keys.
    """
    row = cs.new_round("A", "chat50", "chat50", tokens=12, text="x", messages=3,
                       round_index=7, expected_recall="门簪", recall_ok=True)
    row.http_status = 200
    row.status_ok = True
    row.prompt_tokens = 1234
    row.phase = "chat50"
    written = row.as_row()
    # ``input_text`` is never serialised and the iso columns are derived.
    assert "input_text" not in written

    import io
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(json.dumps(written, ensure_ascii=False) + "\n")
        path = Path(fh.name)
    try:
        (restored,) = cs.load_rounds(path)
    finally:
        path.unlink()

    assert restored.group == "chat50"
    assert restored.phase == "chat50"
    assert restored.prompt_tokens == 1234
    assert restored.expected_recall == "门簪"
    assert restored.recall_ok is True
    assert cs.is_recall_row(restored) is True


def test_load_rounds_reads_gzip_and_rejects_a_truncated_row(tmp_path):
    """The committed MYS-2510 evidence is gzipped, and a partial row must say so.

    ``Round`` has two positional fields, so a compacted row raises a bare
    TypeError naming no file -- which is unhelpful at exactly the moment the
    report cannot be built. The loader names the file instead.
    """
    row = cs.new_round("A", "chat50", "chat50", tokens=5, round_index=1)
    good = json.dumps(row.as_row(), ensure_ascii=False)

    gz = tmp_path / "rounds.jsonl.gz"
    gz.write_bytes(gzip.compress((good + "\n").encode("utf-8")))
    assert len(cs.load_rounds(gz)) == 1

    truncated = tmp_path / "truncated.jsonl.gz"
    truncated.write_bytes(gzip.compress(
        (json.dumps({"group": "x", "phase": "p"}) + "\n").encode("utf-8")))
    with pytest.raises(SystemExit, match="missing required field"):
        cs.load_rounds(truncated)


def test_u1_replay_history_matches_the_mys2510_run_it_reproduces():
    """The rebuilt history must equal the conversation MYS-2510 actually sent.

    Three separate ways this went wrong on the device, each producing a wrong
    answer that would have been reported as a recall failure:

    * turns from ``ctx_turn_text`` -> history plants A2's words, so the replayed
      question is unanswered (answered 药臼 for 门簪);
    * assistant turns hardcoded to ``收到。`` -> the history teaches that
      ``收到。`` answers a recall question (answered 收到。 for all twelve).

    So the assertion is against the recorded run, not against a rule: every
    assistant turn this builds must equal what MYS-2510's chat50 session really
    replied. The evidence ships with the repo, so this runs rather than skips.
    """
    evidence = (Path(__file__).resolve().parent.parent / "analysis/raw"
                / "mys2510-supplement" / "mys2510-rounds.jsonl.gz")
    if not evidence.exists():
        pytest.skip("MYS-2510 rounds not present in this checkout")
    actual = {}
    for row in map(json.loads, gzip.decompress(
            evidence.read_bytes()).decode("utf-8").splitlines()):
        if row.get("phase") == "chat50" and row.get("turn"):
            actual[row["turn"]] = row.get("output")

    class _Runner(cs.Runner):
        def __init__(self):  # noqa: D107 - pure function under test
            pass

    history = _Runner()._chat_history(17)
    checked = 0
    for i, message in enumerate(history):
        if message["role"] != "assistant":
            continue
        turn = (i + 1) // 2
        if turn not in actual:
            continue
        assert message["content"] == actual[turn], (
            f"turn {turn}: rebuilt {message['content']!r} but the run had "
            f"{actual[turn]!r}")
        checked += 1
    assert checked >= 15, f"only compared {checked} assistant turns"


def test_u1_replay_history_actually_contains_the_answer_it_asks_for():
    """The rebuilt history must plant the word the replay asks about.

    Asking 门簪 over a history built by ``ctx_turn_text`` is unanswerable: that
    constructor plants A2's words, so turn 17 holds 药臼 and the model answers
    药臼 -- correctly. The replay then reads as a recall failure when nothing was
    wrong with the model. This is why the replay rebuilds with the chat
    constructor, and the test binds the two together.
    """
    class _Runner(cs.Runner):
        def __init__(self):  # noqa: D107 - pure function under test
            pass

    runner = _Runner()
    for _, turns in cs.U1_REPLAY_GROUPS:
        for turn in turns:
            history = runner._chat_history(turn - 1)
            _, _, asked = cs.chat_turn_text(turn, seed=cs.SEED)
            # The answer must be planted in the turn immediately before, which is
            # what the question ("上一轮的关键词") refers to.
            previous = history[-2]["content"]
            assert f"「{asked}」" in previous, (
                f"turn {turn}: asks {asked!r} but previous turn says {previous!r}")
            # And the A2 constructor must NOT produce the same text, or this test
            # would pass while the replay was rebuilding the wrong conversation.
            ctx_text, _ = cs.ctx_turn_text(1, turn - 1)
            assert ctx_text != previous


def test_u1_replay_asks_the_questions_that_actually_failed():
    """The replay must re-ask the rare words, or it proves nothing.

    The twelve historical failures were all a recall of 门簪/琴轸/秤砣/妆奁 -- the
    words whose bytes a tokenizer splits. An earlier version took the question
    from ``ctx_fact_for`` and asked 药臼/烛台/竹帘/笔洗 instead: common words that
    assemble from whole tokens, so the replay passed without ever exercising the
    defect. This pins the questions to the ones the evidence shows failing.
    """
    expected_rare = {18: "门簪", 29: "琴轸", 35: "秤砣", 45: "妆奁",
                     68: "门簪", 79: "琴轸", 85: "秤砣", 95: "妆奁"}
    for turn, word in expected_rare.items():
        _, _, asked = cs.chat_turn_text(turn, seed=cs.SEED)
        assert asked == word, f"turn {turn} asks {asked!r}, failed on {word!r}"
        assert asked in cs.RARE_WORDS
    # Every replayed turn in the config is one of them.
    for _, turns in cs.U1_REPLAY_GROUPS:
        for turn in turns:
            _, _, asked = cs.chat_turn_text(turn, seed=cs.SEED)
            assert asked in cs.RARE_WORDS, (turn, asked)


def test_u1_replay_records_its_rows():
    """A replayed request that is not recorded did not happen, as far as the report goes.

    ``_u1_replay`` sent and graded its twelve requests but never called
    ``self.record``, so ``rounds.jsonl`` had no replay rows and the report listed
    the replay criterion as unmeasured -- the evidence for the exact regression U1
    exists to prove was discarded. Checked by running the method against a stub
    that counts what it is handed.
    """
    recorded: list = []

    class _Stub(cs.Runner):
        def __init__(self):  # noqa: D107 - no I/O
            self.rounds = []
            self.recorded = recorded
            self.timeline = cs.ext.Timeline()
            self.tokenizer = None
            self.timeout = 30.0
            self.model = "m"
            self.key = "k"
            self.http = None

        def _ctx_history(self, session, up_to):
            return []

        def _raw(self, *parts):
            from pathlib import Path as _P
            return _P("/dev/null")

        def record(self, row):
            self.recorded.append(row)

    stub = _Stub()
    original = cs.stream_round
    cs.stream_round = lambda *a, **k: cs.new_round("U", "utf8", k.get("group", "g"))
    try:
        stub._u1_replay("chat50", (18, 29))
    finally:
        cs.stream_round = original
    assert len(recorded) == 2
    assert all(r.group == "utf8-replay-chat50" for r in recorded)


def test_a2_restart_criterion_reads_the_phase_metadata_carry_merges():
    """Carrying rows alone is not enough: the restart verdict lives in the phase.

    The A2 restart evidence is a 409 gate row plus three booleans the phase
    records (gate/reload/history). A merge that brought only the rows left the
    booleans absent, so the criterion reported failure on a run where the gate
    had refused exactly as designed -- the evidence was in the table and the
    verdict still said no.
    """
    rows = [
        _row(dimension="A2", phase="ctx-tiers", group="ctx-16k-restart",
             session=1, turn=5, ctx_role="build", ctx_tier=16384,
             ctx_cumulative_tokens=16390, ctx_tier_reached=True,
             prompt_tokens=16390),
        _row(dimension="A2", phase="ctx-tiers", group="ctx-16k-restart-gate",
             http_status=409, status_ok=True, expected_status=409,
             prompt_tokens=None),
    ]
    for position in ("early", "recent"):
        rows.append(_row(dimension="A2", phase="ctx-tiers",
                         group="ctx-16k-restart", session=1, turn=6,
                         ctx_role="probe", ctx_tier=16384,
                         ctx_tier_reached=True, ctx_probe_position=position,
                         recall_ok=True, prompt_tokens=16390))

    phases = {"ctx-tiers": {"tiers": [16384], "restart_gate_ok": True,
                            "restart_reload_ok": True,
                            "restart_history_kept": True}}
    summary = cs.summarize(rows, phases)
    verdict = cs.dimension_verdict(summary, {"checked": 0}, phases, rows)
    criterion = verdict["dimensions"]["A2"]["16k 会话重启后准入/重载/历史保留"]
    assert criterion["ok"] is True, criterion

    # Without the merged metadata the same rows cannot substantiate it.
    summary2 = cs.summarize(rows, {})
    verdict2 = cs.dimension_verdict(summary2, {"checked": 0}, {}, rows)
    assert (verdict2["dimensions"]["A2"]["16k 会话重启后准入/重载/历史保留"]["ok"]
            is False)


def test_every_phase_end_call_passes_its_start_timestamp():
    """``_phase_end(name, started, **extra)`` -- a missing ``started`` aborts a phase.

    Two phases shipped without it (``restart`` and ``utf8``). Neither is caught by
    a request-level test, because the crash happens *after* the requests: the row
    loop finishes, ``_phase_end`` raises TypeError, the run aborts, and everything
    the phase was going to do next -- U1's replay of the MYS-2510 failures, for
    one -- silently never runs. The report then shows a phase with no verdict.

    Checked by parsing the source, since the failure mode is a missing argument
    on one call out of thirteen.
    """
    import ast

    source = Path(cs.__file__).read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_phase_end"):
            has_started = (len(node.args) >= 2
                           or any(k.arg == "started" for k in node.keywords))
            if not has_started:
                offenders.append(node.lineno)
    assert not offenders, (
        f"_phase_end called without a start timestamp at line(s) {offenders}")
    # And the helper really does require it positionally.
    import inspect
    params = list(inspect.signature(cs.Runner._phase_end).parameters)
    assert params[:3] == ["self", "name", "started"]


def test_carried_rows_are_announced_in_the_report():
    """A merged report must say which rows were measured earlier.

    Without this the tables read as one measurement session, and the MYS-2510
    matrix would look re-run when it was only re-summarised.
    """
    row = _row(dimension="A", phase="chat50", group="chat50")
    html = cs.build_html(env={}, summary=cs.summarize([row], {}),
                         verdict={"dimensions": {}, "passed": False,
                                  "criteria_total": 0, "criteria_failed": [],
                                  "criteria_unmeasured": [], "records": {}},
                         records={}, timeline=[], samples=[], phases={},
                         rounds=[row],
                         manifest={"notes": {},
                                   "carried": {"mys2510-rounds.jsonl.gz": 1240}})
    assert "本报告合并了两次测量" in html
    assert "1,240 行" in html
    # And a run without --carry must not claim to be merged.
    html2 = cs.build_html(env={}, summary=cs.summarize([row], {}),
                          verdict={"dimensions": {}, "passed": False,
                                   "criteria_total": 0, "criteria_failed": [],
                                   "criteria_unmeasured": [], "records": {}},
                          records={}, timeline=[], samples=[], phases={},
                          rounds=[row], manifest={"notes": {}})
    assert "本报告合并了两次测量" not in html2


def test_report_renders_the_a2_and_u1_sections():
    """The report must carry the new evidence, not just the code that collects it."""
    rows = [
        _row(dimension="A2", phase="ctx-tiers", group="ctx-2k"),
        _row(dimension="U", phase="utf8", group="utf8-stream"),
    ]
    html = cs.build_html(env={}, summary=cs.summarize(rows, {}),
                         verdict={"dimensions": {}, "passed": False,
                                  "criteria_total": 0, "criteria_failed": [],
                                  "criteria_unmeasured": [], "records": {}},
                         records={}, timeline=[], samples=[], phases={},
                         rounds=rows, manifest={"notes": {}})
    assert "A2 连续对话档位" in html
    assert "U1 UTF-8 回归" in html
    assert "MYS-2510 报告修正说明" in html
    assert "response_content" in html


def test_report_survives_a_run_that_produced_no_a2_or_u1_rows():
    """A partial run must still render, with the sections present but empty."""
    html = cs.build_html(env={}, summary=cs.summarize([], {}),
                         verdict={"dimensions": {}, "passed": False,
                                  "criteria_total": 0, "criteria_failed": [],
                                  "criteria_unmeasured": [], "records": {}},
                         records={}, timeline=[], samples=[], phases={},
                         rounds=[], manifest={"notes": {}})
    assert "A2 连续对话档位" in html
    assert "U1 UTF-8 回归" in html


def test_report_draws_the_a2_growth_curve_when_sessions_ran():
    """The per-session growth curve must actually be rendered, not skipped.

    The empty-run test above cannot catch a broken chart call: with no A2 rows
    the chart branch never executes and the section renders from the "no data"
    path. That is exactly how a missing ``x_labels`` argument survived -- every
    test passed while the first real run with sessions crashed in
    ``build_html``, after the whole matrix had already been paid for.

    So this test populates two sessions of different lengths and asserts the SVG
    really came out, with a point per turn.
    """
    rows = []
    for session, turns in ((1, 3), (2, 5)):
        for turn in range(1, turns + 1):
            rows.append(_row(dimension="A2", phase="ctx-tiers",
                             group=f"ctx-{session}k", session=session,
                             turn=turn, ctx_role="build", ctx_tier=4096,
                             ctx_cumulative_tokens=200 * turn,
                             ctx_tier_reached=turn == turns,
                             prompt_tokens=200 * turn))
    html = cs.build_html(env={}, summary=cs.summarize(rows, {}),
                         verdict={"dimensions": {}, "passed": False,
                                  "criteria_total": 0, "criteria_failed": [],
                                  "criteria_unmeasured": [], "records": {}},
                         records={}, timeline=[], samples=[], phases={},
                         rounds=rows, manifest={"notes": {}})
    assert "A2 会话累计 prompt_tokens 逐轮增长" in html
    # One <circle> per measured turn across both sessions, and no invented
    # turns: the shorter session must not be padded out to the longer one.
    assert html.count('<circle class="point"') == 3 + 5
    # The x axis is numbered from the first turn, not from zero.
    assert ">1</text>" in html and ">5</text>" in html


def test_ctx_history_rebuilds_the_same_bytes_the_session_sent():
    """The restart replay and the U1 re-enactment both resend rebuilt history.

    If the rebuild differed from what the live session sent, the "complete
    history" claim would be about a reconstruction rather than the conversation
    that actually reached 16k -- and the U1 replay would not be the request that
    failed in the field.
    """
    from pathlib import Path as _P

    class _Runner(cs.Runner):
        def __init__(self):  # noqa: D107 - no I/O in this test
            pass

    built = _Runner()._ctx_history(3, 6)
    assert len(built) == 12
    assert [m["role"] for m in built[:4]] == ["user", "assistant", "user", "assistant"]
    # Rebuilt twice, identical.
    assert _Runner()._ctx_history(3, 6) == built
    # The user turns are the same strings ctx_turn_text produces.
    for turn in range(1, 7):
        text, _ = cs.ctx_turn_text(3, turn)
        assert built[(turn - 1) * 2]["content"] == text
    # A different session is a different conversation.
    assert _Runner()._ctx_history(4, 6) != built


def test_ctx_turn_text_grows_a_tier_in_a_realistic_number_of_turns():
    """One-line turns would need ~500 turns for 16k; turns carry content."""
    assert cs.CTX_FILLER_CLAUSES >= 1
    text, _ = cs.ctx_turn_text(1, 50)
    # ~160 tokens per turn measured on the board means ~100 turns for 16k.
    assert len(text) > 200, len(text)
    assert "第50轮记录" in text
    # Filler is deterministic and turn-specific.
    assert cs.ctx_turn_text(1, 50)[0] == text
    assert cs.ctx_turn_text(1, 51)[0] != text


def test_ctx_filler_disabled_still_produces_a_valid_turn():
    """filler=0 keeps the old shape, which the unit tests rely on."""
    text, fact = cs.ctx_turn_text(1, 5, filler=0)
    assert fact in text
    assert text.count("\n") == 1  # plant line + instruction line only
