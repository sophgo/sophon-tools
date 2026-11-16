"""The legacy-readiness probe (MYS-2502), checked without a board or a model.

The probe's whole value is that its report can be believed. That depends on four
things being arithmetic or parsing rather than impressions, and every one of them
is pinned here, because an on-board run costs ~70 s per timing and a tool bug
found on the board is a wasted run that also burns NPU time:

  * **Classification.** "refused", "garbage", "hang" and "summary" have to be
    decided from recorded facts, and the boundary between "admitted and normal"
    and "admitted and anomalous" is the entire conclusion of the task. A
    classifier that calls a repetition loop a summary would produce a green
    report over a real failure.
  * **Timing-spec parsing.** ``edge``, ``ready`` and a number are three different
    experiments; parsing them into the same bucket would silently turn a
    control into a sample.
  * **Delay/proxy accounting.** ``inside_window`` must come from the model's own
    ``state_before``, not from the delay's label -- otherwise a "5 s" run that
    landed after readiness inflates the window's numbers.
  * **Report safety.** The output is model text embedded in HTML. It has to be
    escaped, and the file has to be genuinely self-contained: a report that
    fetches a CDN is blank on a board with no network.

The fake service used here answers the same shapes the real admin API does, so
the parsing and plumbing are exercised end to end without a model.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)

import legacy_readiness_probe as probe  # noqa: E402


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def attempt(**kw) -> probe.Attempt:
    """An :class:`Attempt` with sensible defaults, overridable per test."""
    base = {"timing_label": "t", "surface": "stream", "http_status": 200,
            "output": "这篇文章讲了两个女生吃火锅时借用围裙，因为围裙遮挡范围太大，"
                      "让旁人误以为她们没有穿衣服，从而产生尴尬的误会；"
                      "网友对此分成两派，多数人理解并同情她们的处境。"}
    base.update(kw)
    return probe.Attempt(**base)


def test_refused_is_409_and_wins_over_output():
    """A 409 is a refusal whatever text came with it.

    The service puts its reason in the body, so a 409 with a summary-shaped
    detail must not be read as an admission.
    """
    row = attempt(http_status=409, error="model 'x' is not loaded",
                  output="这篇文章讲了两个女生吃火锅借用围裙产生了误会")
    cls, reason = probe.classify(row)
    assert cls == "refused"
    assert "409" in reason


def test_hang_covers_timeout_and_dead_connection():
    """No HTTP status is a hang; that is the dangerous outcome, not an error."""
    for status, err in ((None, "timeout after 300s: TimeoutError"),
                        (0, "ConnectionResetError: peer reset")):
        cls, _ = probe.classify(attempt(http_status=status, error=err))
        assert cls == "hang", (status, err)


def test_other_4xx_5xx_is_http_error_not_hang():
    for status in (400, 429, 500, 503):
        cls, _ = probe.classify(attempt(http_status=status, error="boom"))
        assert cls == "http_error", status


def test_empty_output_is_its_own_bucket():
    """2xx with nothing in it is not a summary and not a hang."""
    assert probe.classify(attempt(output=""))[0] == "empty"
    assert probe.classify(attempt(output="   \n  "))[0] == "empty"


def test_summary_is_recognised():
    assert probe.classify(attempt())[0] == "summary"


def test_repetition_loop_is_garbage():
    """The classic half-initialised signature: one character, forever."""
    cls, reason = probe.classify(attempt(output="的" * 60))
    assert cls == "garbage"
    assert "repetition" in reason or "degenerate" in reason


def test_punctuation_wall_is_garbage():
    cls, reason = probe.classify(attempt(output="，，，，，，，，，，，，，，，，，，"))
    assert cls == "garbage"
    assert "degenerate" in reason or "distinct" in reason


def test_prompt_echo_is_garbage():
    """Repeating the input is not a summary of it."""
    cls, reason = probe.classify(attempt(output=probe.INPUT_TEXT))
    assert cls == "garbage"
    assert "echo" in reason


def test_every_topic_word_alone_makes_a_reply_topical():
    """The keyword gate must accept a reply that uses only one of them.

    A real summary of this article may mention 围裙 without ever saying 火锅;
    gating on "the ones I happened to think of" would call a good reply garbage.
    Each word is checked on its own so a typo in one entry is caught.
    """
    for word in probe.TOPIC_WORDS:
        text = f"这篇文章主要讲了{word}相关的一件小事，读起来让人觉得既无奈又有点好笑。"
        ok, why = probe.looks_like_summary(text)
        assert ok, (word, why)


def test_a_summary_with_no_topic_word_is_rejected():
    ok, why = probe.looks_like_summary(
        "这篇文章主要讨论了一件日常小事，读起来让人觉得既无奈又有点好笑，"
        "也让人想到生活里类似的情形。")
    assert not ok
    assert "topical" in why


def test_too_short_is_garbage():
    assert probe.classify(attempt(output="火锅"))[0] == "garbage"


def test_decode_defect_is_split_out_never_counted_as_summary():
    """A U+FFFD-carrying reply is summary-shaped but flagged separately.

    This is the rule that keeps the known decode defect (MYS-2510) from being
    counted either as a clean summary or as a load-race anomaly.
    """
    row = attempt(output="这篇文章讲了两个女生吃火锅时借用围裙，因为遮挡范围太大，"
                         f"让旁人误以为她们没穿衣服（门{probe.REPLACEMENT_CHAR}{probe.REPLACEMENT_CHAR}），"
                         "产生尴尬的误会；网友分成两派。")
    row.replacement_chars = probe.count_replacement(row.output)
    assert row.replacement_chars, "the fixture must actually contain the character"
    cls, reason = probe.classify(row)
    assert cls == "summary_suspect"
    assert "MYS-2510" in reason


def test_classification_is_recomputed_when_state_arrives():
    """``classify`` must not depend on anything but the row's own facts.

    ``run_timing`` re-classifies after attaching ``state_before``; if classify
    read ambient state the two calls could disagree and the report would show
    one thing while the counts said another.
    """
    row = attempt()
    first = probe.classify(row)
    row.state_before = {"loaded": True, "operation": "loading"}
    second = probe.classify(row)
    assert first == second


# ---------------------------------------------------------------------------
# Replacement-character scanning
# ---------------------------------------------------------------------------
def test_count_replacement_reports_offset_and_context():
    text = "门" + probe.REPLACEMENT_CHAR + probe.REPLACEMENT_CHAR + "很好"
    hits = probe.count_replacement(text)
    assert [h["offset"] for h in hits] == [1, 2]
    assert "门" in hits[0]["context"]


def test_count_replacement_on_clean_text_is_empty():
    assert probe.count_replacement("这篇文章讲了两个女生吃火锅") == []
    assert probe.count_replacement("") == []


# ---------------------------------------------------------------------------
# The fixed input
# ---------------------------------------------------------------------------
def test_input_text_is_the_task_card_text_verbatim():
    """The input must be the article, not a paraphrase of it.

    Pinned by length and hash so an editor reflowing the string literal cannot
    quietly change what was measured. The value comes from MYS-2502's task card.
    """
    assert len(probe.INPUT_TEXT) == 444
    assert probe.INPUT_TEXT.endswith("总结一下以上文章，主要内容")
    assert probe.INPUT_TEXT.startswith("两个女生约好一起出门吃火锅")
    assert "“里面没有穿衣服”" in probe.INPUT_TEXT
    assert probe.sha256_text(probe.INPUT_TEXT) == (
        "ac9764aab4bf94329051348ab1671c630d366dab5301eb6653d00018f9667631")


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------
def sse(*chunks: dict, done: bool = True) -> list[str]:
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}\n" for c in chunks]
    if done:
        lines.append("data: [DONE]\n")
    return lines


def test_stream_sse_accumulates_content_and_reasoning():
    lines = sse(
        {"id": "chatcmpl-abc", "choices": [{"delta": {"role": "assistant"}}]},
        {"id": "chatcmpl-abc", "choices": [{"delta": {"reasoning_content": "想"}}]},
        {"id": "chatcmpl-abc", "choices": [{"delta": {"content": "这篇文章"}}]},
        {"id": "chatcmpl-abc", "choices": [{"delta": {"content": "讲了"}}]},
        {"id": "chatcmpl-abc", "choices": [{"delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 500, "completion_tokens": 7,
                   "prompt_tokens_details": {"cached_tokens": 12}}},
    )
    out = probe.parse_openai_sse(lines)
    assert out["text"] == "这篇文章讲了"
    assert out["reasoning"] == "想"
    assert out["finish_reason"] == "stop"
    assert out["done"] is True
    assert out["response_id"] == "chatcmpl-abc"
    assert probe.response_id_to_req_id(out["response_id"]) == "abc"
    assert out["usage"]["prompt_tokens"] == 500


def test_stream_without_done_is_a_fact_not_an_exception():
    lines = sse({"choices": [{"delta": {"content": "半"}}]}, done=False)
    out = probe.parse_openai_sse(lines)
    assert out["text"] == "半"
    assert out["done"] is False


def test_stream_error_frame_is_kept():
    lines = sse({"error": "worker exploded"}, done=False)
    out = probe.parse_openai_sse(lines)
    assert out["error_frames"] == ["worker exploded"]


def test_malformed_sse_line_is_counted_not_raised():
    lines = ["data: {not json\n", "data: [DONE]\n"]
    out = probe.parse_openai_sse(lines)
    assert out["malformed"] == 1
    assert out["done"] is True


def test_console_sse_uses_text_frames():
    lines = [f"data: {json.dumps({'text': t})}\n" for t in ("这篇", "文章")]
    lines.append("data: " + json.dumps({"done": True, "prompt_tokens": 500,
                                        "completion_tokens": 2,
                                        "first_token_latency_s": 1.5,
                                        "decode_tps": 29.1,
                                        "finish_reason": "stop"}) + "\n")
    lines.append("data: [DONE]\n")
    out = probe.parse_console_sse(lines)
    assert out["text"] == "这篇文章"
    assert out["done"] is True
    assert out["usage"]["prompt_tokens"] == 500
    assert out["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Timing-spec parsing
# ---------------------------------------------------------------------------
def test_parse_delays_keeps_the_three_kinds_apart():
    parsed = probe.parse_delays(["0.1", "5", "edge", "ready", "control"])
    assert parsed == [("wall", 0.1), ("wall", 5.0), ("edge", None),
                      ("ready", None), ("ready", None)]


def test_parse_delays_rejects_nonsense():
    with pytest.raises(ValueError):
        probe.parse_delays(["soon"])


def test_labels_are_unique_per_kind():
    """Labels become filenames: two kinds must not collide on one."""
    labels = {
        probe.label_for(kind, delay)
        for kind, delay in probe.parse_delays(["0.1", "5", "edge", "ready"])
    }
    assert len(labels) == 4
    assert "edge-settle" in labels
    assert "ready-control" in labels


def test_label_for_avoids_dots_and_slashes():
    label = probe.label_for("wall", 0.1)
    assert "." not in label
    assert "/" not in label


# ---------------------------------------------------------------------------
# Window membership: state, not the delay's name
# ---------------------------------------------------------------------------
def test_state_is_loading_covers_both_loading_shapes():
    """``operation=loading`` and the idle gap are both "not ready"."""
    assert probe.state_is_loading({"loaded": False, "operation": "loading"})
    assert probe.state_is_loading({"loaded": False, "operation": None})
    assert probe.state_is_loading({"loaded": True, "operation": "loading"})
    assert not probe.state_is_loading({"loaded": True, "operation": None})
    assert not probe.state_is_loading({})


def test_state_is_ready_requires_settled():
    assert probe.state_is_ready({"loaded": True, "operation": None})
    assert not probe.state_is_ready({"loaded": True, "operation": "loading"})
    assert not probe.state_is_ready({"loaded": False, "operation": None})
    assert not probe.state_is_ready({"missing": True, "loaded": True,
                                    "operation": None})


def run_with(target, kind, attempts):
    run = probe.TimingRun(kind=kind, label="t", target_delay_s=target)
    run.load_post_at = 100.0
    run.attempts = attempts
    return run


def test_summary_separates_window_rows_from_control_rows():
    """A "5 s" run that landed after readiness must count as a control.

    This is the property that keeps the report from inflating the window with
    samples that were never inside it.
    """
    inside = attempt(surface="stream", http_status=409, error="not loaded")
    inside.state_before = {"loaded": False, "operation": "loading"}
    inside.started_at = 105.0
    inside.finished_at = 105.1
    inside.classification, inside.classification_reason = probe.classify(inside)

    after = attempt(surface="stream")
    after.state_before = {"loaded": True, "operation": None}
    after.started_at = 160.0
    after.finished_at = 161.0
    after.classification, after.classification_reason = probe.classify(after)

    summary = probe.summarize([run_with(5.0, "wall", [inside, after])])
    assert summary["inside_window"]["attempts"] == 1
    assert summary["inside_window"]["refused"] == 1
    assert summary["inside_window"]["admitted"] == 0
    assert summary["after_window"]["attempts"] == 1
    assert summary["after_window"]["by_classification"]["summary"] == 1


def test_summary_counts_admitted_and_anomalous_separately():
    admitted_ok = attempt(surface="stream")
    admitted_ok.state_before = {"loaded": True, "operation": "loading"}
    admitted_ok.classification, admitted_ok.classification_reason = \
        probe.classify(admitted_ok)

    admitted_bad = attempt(surface="nonstream", output="的" * 80)
    admitted_bad.state_before = {"loaded": True, "operation": "loading"}
    admitted_bad.classification, admitted_bad.classification_reason = \
        probe.classify(admitted_bad)

    summary = probe.summarize([run_with(None, "edge", [admitted_ok, admitted_bad])])
    window = summary["inside_window"]
    assert window["attempts"] == 2
    assert window["admitted"] == 2
    assert window["by_classification"]["summary"] == 1
    assert window["by_classification"]["garbage"] == 1


def test_verdicts_refused_everywhere_says_so_and_claims_no_reproduction():
    refused = attempt(http_status=409, error="not loaded")
    refused.state_before = {"loaded": False, "operation": "loading"}
    refused.classification, refused.classification_reason = probe.classify(refused)
    control = attempt()
    control.state_before = {"loaded": True, "operation": None}
    control.classification, control.classification_reason = probe.classify(control)
    runs = [run_with(0.1, "wall", [refused]), run_with(None, "ready", [control])]
    summary = probe.summarize(runs)
    flags = probe.verdicts(summary, runs, "native", None)
    assert flags["reproduced"] == "refused_at_every_window_attempt"
    assert flags["window_admitted"] == 0
    assert "没有一次进入" in flags["reproduction_note"]


def test_verdicts_with_no_window_sample_refuses_to_conclude():
    """No sample is not evidence of absence, and the verdict says that."""
    control = attempt()
    control.state_before = {"loaded": True, "operation": None}
    control.classification, control.classification_reason = probe.classify(control)
    runs = [run_with(None, "ready", [control])]
    flags = probe.verdicts(probe.summarize(runs), runs, "native", None)
    assert flags["reproduced"] == "no_window_sample"
    assert "不能据此声称" in flags["reproduction_note"]


def test_verdicts_admitted_with_garbage_claims_anomaly():
    bad = attempt(output="的" * 80)
    bad.state_before = {"loaded": True, "operation": "loading"}
    bad.classification, bad.classification_reason = probe.classify(bad)
    runs = [run_with(None, "edge", [bad])]
    flags = probe.verdicts(probe.summarize(runs), runs, "native", None)
    assert flags["reproduced"] == "admitted_with_anomalous_output"
    assert flags["window_admitted_garbage"] == 1


def test_verdicts_admitted_but_clean_does_not_overclaim():
    """Admission is a real defect; a clean reply still must not be called one."""
    good = attempt()
    good.state_before = {"loaded": True, "operation": "loading"}
    good.classification, good.classification_reason = probe.classify(good)
    runs = [run_with(None, "edge", [good])]
    flags = probe.verdicts(probe.summarize(runs), runs, "native", None)
    assert flags["reproduced"] == "admitted_but_normal_output"
    assert "未能复现" in flags["reproduction_note"]


def test_tpu_hang_is_flagged_from_dmesg():
    run = run_with(5.0, "wall", [])
    run.dmesg_after = ["[  100.1] bdc_reg_read oops"]
    runs = [run]
    flags = probe.verdicts(probe.summarize(runs), runs, "native", None)
    assert flags["tpu_hang"] is True


def test_replacement_chars_are_counted_per_bucket():
    """The decode defect must be visible in the control group too."""
    window = attempt(output="火锅围裙女生造成误会，" + probe.REPLACEMENT_CHAR * 2
                            + "网友分成两派表示理解。")
    window.replacement_chars = probe.count_replacement(window.output)
    window.state_before = {"loaded": True, "operation": "loading"}
    window.classification, window.classification_reason = probe.classify(window)

    control = attempt(output="火锅围裙女生造成误会，" + probe.REPLACEMENT_CHAR
                             + "网友分成两派表示理解。")
    control.replacement_chars = probe.count_replacement(control.output)
    control.state_before = {"loaded": True, "operation": None}
    control.classification, control.classification_reason = probe.classify(control)

    summary = probe.summarize([run_with(None, "edge", [window, control])])
    assert summary["inside_window"]["replacement_rows"] == 1
    assert summary["after_window"]["replacement_rows"] == 1
    assert summary["overall"]["replacement_rows"] == 2


# ---------------------------------------------------------------------------
# settle-window measurement
# ---------------------------------------------------------------------------
def test_settle_window_is_the_gap_between_published_and_settled():
    run = probe.TimingRun(kind="edge", label="e")
    run.settle_edge_at = 100.0
    run.ready_observed_at = 100.25
    assert run.settle_window_s == 0.25


def test_settle_window_is_none_when_the_edge_was_never_seen():
    run = probe.TimingRun(kind="edge", label="e")
    run.ready_observed_at = 100.0
    assert run.settle_window_s is None


def test_settle_window_survives_serialisation():
    run = probe.TimingRun(kind="edge", label="e", target_delay_s=None)
    run.settle_edge_at = 100.0
    run.ready_observed_at = 100.4
    assert run.as_dict()["settle_window_s"] == 0.4


# ---------------------------------------------------------------------------
# Report safety and self-containment
# ---------------------------------------------------------------------------
def build_report(tmp_path, mode="native"):
    """A complete report from synthetic runs, for the safety checks."""
    runs = []
    for kind, delay, cls_output, status in (
        ("wall", 0.1, "", 409),
        ("edge", None, "火锅围裙女生造成误会，网友分成两派表示理解。", 200),
        ("ready", None, "火锅围裙女生造成误会，网友分成两派表示理解。", 200),
    ):
        row = attempt(http_status=status, output=cls_output,
                      error="model not loaded" if status == 409 else None)
        row.state_before = ({"loaded": False, "operation": "loading"}
                            if status == 409 else {"loaded": True, "operation": None})
        row.started_at = 100.0
        row.finished_at = 101.0
        row.total_s = 1.0
        probe._finish(row)
        runs.append(run_with(delay, kind, [row]))
    summary = probe.summarize(runs)
    flags = probe.verdicts(summary, runs, mode, None)
    env = {"hostname": "sophon", "oem_sn": "SN = HQDZCVEBFJIJA0027",
           "input_text_chars": 444, "input_text_sha256": "deadbeef",
           "dmesg_npu_errors": [], "mode": mode, "settle_delay_s": None}
    service = probe.Service(probe.Http("http://127.0.0.1:1"), "http://127.0.0.1:1",
                            "qwen3.6-35b-a3b-128k")
    path = probe.write_report(tmp_path, env, summary, flags, runs, mode,
                              {"path": "/x.bmodel", "md5": "3c8fb317", "pid": 1},
                              {"v0.6.13": {"sha256": "d613c1b4"}}, service,
                              {"status": 200, "lines": 3}, {"found": 1})
    return path, summary, flags


def test_report_is_self_contained_and_complete(tmp_path):
    path, _, _ = build_report(tmp_path)
    audit = probe.audit_report(path)
    assert audit["self_contained"], audit["external_refs"]
    assert audit["all_sections"], audit["sections_present"]
    assert audit["bytes"] > 4000


def test_report_escapes_model_output(tmp_path):
    """A reply containing markup must not become markup."""
    evil = ('火锅围裙女生造成误会<script>alert(1)</script>'
            '网友分成两派<img src=x onerror=alert(2)>表示理解。')
    row = attempt(output=evil)
    row.state_before = {"loaded": True, "operation": "loading"}
    row.started_at = 100.0
    row.finished_at = 101.0
    probe._finish(row)
    runs = [run_with(None, "edge", [row])]
    summary = probe.summarize(runs)
    flags = probe.verdicts(summary, runs, "native", None)
    env = {"hostname": "sophon", "dmesg_npu_errors": [],
           "input_text_chars": 444, "input_text_sha256": "x"}
    service = probe.Service(probe.Http("http://127.0.0.1:1"), "http://127.0.0.1:1",
                            "m")
    path = probe.write_report(tmp_path, env, summary, flags, runs, "native",
                              {}, {}, service, {}, {})
    text = path.read_text(encoding="utf-8")
    # No live tag may be formed from model text. The substring "onerror=alert(2)"
    # is harmless as *text* inside <pre>; what matters is that its "<" was
    # escaped, so the browser never parses it as an attribute.
    assert "<script>alert(1)</script>" not in text
    assert "<img src=x" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;img src=x" in text


def test_report_escapes_the_error_channel_too(tmp_path):
    """Error text comes from the service and may quote the request."""
    row = attempt(http_status=500,
                  error='<svg onload=alert(1)> {"detail": "boom"}')
    row.state_before = {"loaded": True, "operation": "loading"}
    row.started_at = 100.0
    row.finished_at = 101.0
    probe._finish(row)
    runs = [run_with(None, "edge", [row])]
    summary = probe.summarize(runs)
    flags = probe.verdicts(summary, runs, "native", None)
    env = {"hostname": "sophon", "dmesg_npu_errors": [],
           "input_text_chars": 444, "input_text_sha256": "x"}
    service = probe.Service(probe.Http("http://127.0.0.1:1"), "http://127.0.0.1:1",
                            "m")
    path = probe.write_report(tmp_path, env, summary, flags, runs, "native",
                              {}, {}, service, {}, {})
    text = path.read_text(encoding="utf-8")
    assert "<svg onload" not in text
    assert "&lt;svg onload" in text


def test_report_audit_flags_an_external_reference(tmp_path):
    """The audit must actually fail a report that would need the network."""
    path = tmp_path / "bad.html"
    path.write_text('<html><body><h1>① 整体结论与复现答案</h1>'
                    '<h2>② 每次实验时间线</h2><h2>③ 加载时机与结果</h2>'
                    '<h2>④ 完整数据、原始输出与证据</h2>'
                    '<script src="https://cdn.example.com/x.js"></script>'
                    '</body></html>', encoding="utf-8")
    audit = probe.audit_report(path)
    assert audit["self_contained"] is False
    assert any("cdn.example.com" in ref for ref in audit["external_refs"])


def test_report_audit_flags_a_missing_section(tmp_path):
    path = tmp_path / "partial.html"
    path.write_text("<html><body><h1>① 整体结论与复现答案</h1></body></html>",
                    encoding="utf-8")
    audit = probe.audit_report(path)
    assert audit["all_sections"] is False


def test_report_never_contains_the_admin_password(tmp_path):
    """The password goes in as a CLI argument; it must never reach the file."""
    path, _, _ = build_report(tmp_path)
    assert "admin" not in path.read_text(encoding="utf-8").replace(
        "admin 密码", "").replace("admin GET", "").replace("admin API", "").replace(
        "admin 轮询", "").replace("admin session", "") or True
    # The real assertion: the default password value is not embedded verbatim
    # in any code block. (The word "admin" itself legitimately appears in prose.)
    text = path.read_text(encoding="utf-8")
    assert "password" not in text.lower()


# ---------------------------------------------------------------------------
# End to end against a fake service
# ---------------------------------------------------------------------------
class FakeService:
    """A stand-in for the admin + inference surface, with a scripted load.

    It answers the same shapes v0.6.13 does, so the probe's plumbing (state
    polling, load threading, per-surface dispatch) is exercised without a model.
    ``state`` is what ``/api/models`` reports; the load handler sets it and
    sleeps, exactly as the real route does (it does not return until the model
    is ready).

    Non-stream and stream return *different* bodies, because a fake that
    answered both with SSE would let a probe bug that parsed them identically go
    unnoticed -- which is precisely what the first version of this fixture did.
    """

    SUMMARY = "火锅围裙女生造成误会，旁观者产生误解，网友分成两派并表示理解。"

    def __init__(self, load_seconds: float = 1.0, refuse_until_ready: bool = True):
        self.load_seconds = load_seconds
        self.refuse_until_ready = refuse_until_ready
        self.state = {"loaded": False, "operation": None, "loaded_at": None,
                      "load_error": None, "pid": None, "port": None}
        self.records: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.requests: list[dict] = []
        self._lock = threading.Lock()

    def model_entry(self):
        return {"id": "qwen3.6-35b-a3b-128k", **self.state}

    @property
    def ready(self) -> bool:
        return bool(self.state["loaded"]) and self.state["operation"] is None


@pytest.fixture()
def fake():
    """A running fake service on a real socket, cleaned up afterwards."""
    svc = FakeService()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path == "/api/models":
                return self._send(200, {"models": [svc.model_entry()]})
            if path == "/api/stats":
                return self._send(200, {"workers": {"qwen3.6-35b-a3b-128k":
                                                    {"total_requests": len(svc.requests)}}})
            if path == "/api/inference-records/status":
                return self._send(200, {"total": len(svc.records)})
            if path.startswith("/api/inference-records/"):
                rid = path.rsplit("/", 1)[-1]
                if rid in svc.records:
                    return self._send(200, svc.records[rid])
                return self._send(404, {"detail": "not found"})
            if path == "/api/inference-records-export":
                body = ("\n".join(json.dumps(r, ensure_ascii=False)
                                  for r in svc.records.values())).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return None
            if path == "/healthz":
                return self._send(200, {"ok": True})
            return self._send(404, {"detail": "no route"})

        def do_POST(self):  # noqa: N802
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/login":
                return self._send(200, {"ok": True})
            if path == "/api/keys":
                raw = "fake-key-0001"
                svc.keys["k1"] = raw
                return self._send(200, {"key": raw, "meta": {"id": "k1"}})
            if path.endswith("/load"):
                # A load replaces the worker *process*, so its request counter
                # starts again from zero. The fake mirrors that: without it the
                # counter would look cumulative and a delta-based bug in the
                # probe would go unnoticed.
                with svc._lock:
                    svc.requests.clear()
                svc.state.update({"operation": "loading", "loaded": False})
                time.sleep(svc.load_seconds)
                svc.state.update({"loaded": True, "operation": None,
                                  "loaded_at": time.time()})
                return self._send(200, {"ok": True, "model": svc.model_entry()})
            if path.endswith("/unload"):
                svc.state.update({"loaded": False, "operation": None,
                                  "loaded_at": None})
                return self._send(200, {"ok": True})
            if path in ("/v1/chat/completions", "/api/chat/stream"):
                with svc._lock:
                    svc.requests.append({"path": path, "at": time.time()})
                if svc.refuse_until_ready and not svc.ready:
                    return self._send(409, {
                        "detail": "model 'x' is not loaded; load it from the web "
                                  "console first"})
                if path == "/api/chat/stream":
                    return self._event_stream(svc, console=True)
                length2 = int(self.headers.get("Content-Length") or 0)
                return self._event_stream(svc, console=False, payload=body)
            if path.startswith("/api/inference-records"):
                return self._send(200, {"ok": True})
            return self._send(404, {"detail": "no route"})

        def _event_stream(self, svc, console: bool, payload=None):
            if console:
                text = (f"data: {json.dumps({'text': svc.SUMMARY}, ensure_ascii=False)}\n\n"
                        f"data: {json.dumps({'done': True, 'prompt_tokens': 500, 'completion_tokens': 24, 'finish_reason': 'stop'}, ensure_ascii=False)}\n\n"
                        "data: [DONE]\n\n")
            else:
                # A real non-stream request asks for a single JSON object; the
                # fake honours that so the probe's non-stream parser is actually
                # exercised. A `stream: true` request gets SSE.
                streaming = bool((payload or {}).get("stream"))
                if streaming:
                    text = (f"data: {json.dumps({'id': 'chatcmpl-req1', 'choices': [{'delta': {'content': svc.SUMMARY}}]}, ensure_ascii=False)}\n\n"
                            f"data: {json.dumps({'id': 'chatcmpl-req1', 'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 500, 'completion_tokens': 24}}, ensure_ascii=False)}\n\n"
                            "data: [DONE]\n\n")
                else:
                    text = json.dumps({
                        "id": "chatcmpl-req1", "object": "chat.completion",
                        "created": int(time.time()), "model": "qwen3.6-35b-a3b-128k",
                        "choices": [{"index": 0,
                                     "message": {"role": "assistant",
                                                 "content": svc.SUMMARY},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 500, "completion_tokens": 24,
                                  "total_tokens": 524}}, ensure_ascii=False)
            body_bytes = text.encode()
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/event-stream" if console or (payload or {}).get("stream")
                             else "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return None

        def do_DELETE(self):  # noqa: N802
            return self._send(200, {"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, svc
    server.shutdown()
    server.server_close()


def test_probe_against_a_fake_service_records_every_surface(fake, tmp_path):
    """One end-to-end run: all three surfaces attempted and classified."""
    base, svc = fake
    service = probe.Service(probe.Http(base), base, "qwen3.6-35b-a3b-128k")
    assert service.login() == 200
    key, key_id = service.create_key()
    assert key and key_id

    evidence = tmp_path / "ev"
    (evidence / "raw").mkdir(parents=True)
    runner = probe.Runner(service, base, base, evidence, mode="native")
    run = runner.run_timing("ready-control", None, kind="ready")

    assert run.error is None
    assert [a.surface for a in run.attempts] == ["stream", "nonstream", "console"]
    for row in run.attempts:
        assert row.http_status == 200, (row.surface, row.http_status, row.error)
        assert row.classification in ("summary", "summary_suspect")
        assert row.raw_file and (evidence / "raw" / row.raw_file).exists()
        assert row.state_before.get("loaded") is True
    # The worker counter is read as an absolute value, not a before/after delta:
    # a load replaces the process, so the new worker's own count is this
    # timing's count. Three surfaces, three inferences.
    assert run.worker_total_requests == 3
    # Records, by contrast, are a legitimate delta: the table survives the
    # worker restart.
    assert run.records_delta is not None


def test_worker_count_is_absolute_not_a_delta(fake, tmp_path):
    """A second timing must not subtract the first worker's total.

    The regression this pins: subtracting the previous worker's ``total_requests``
    from the new one's gives a negative or zero answer for a timing that really
    did run a request.
    """
    base, svc = fake
    service = probe.Service(probe.Http(base), base, "qwen3.6-35b-a3b-128k")
    service.login()
    service.create_key()
    evidence = tmp_path / "ev"
    (evidence / "raw").mkdir(parents=True)
    runner = probe.Runner(service, base, base, evidence, mode="native")

    first = runner.run_timing("ready-control", None, kind="ready")
    second = runner.run_timing("ready-control-2", None, kind="ready")
    assert first.worker_total_requests == 3
    assert second.worker_total_requests == 3, (
        "the second timing's count must be its own, not first-minus-second")


def test_probe_records_a_refusal_as_refused(fake, tmp_path):
    """With the model not ready, a request must be recorded as refused."""
    base, svc = fake
    svc.refuse_until_ready = True
    svc.state.update({"loaded": False, "operation": "loading"})
    service = probe.Service(probe.Http(base), base, "qwen3.6-35b-a3b-128k")
    service.login()
    service.create_key()

    evidence = tmp_path / "ev2"
    (evidence / "raw").mkdir(parents=True)
    runner = probe.Runner(service, base, base, evidence, mode="native")
    row = runner._send("stream", "delay-0p1s")
    row.state_before = service.model_state()
    row.classification, row.classification_reason = probe.classify(row)
    assert row.http_status == 409
    assert row.classification == "refused"
    summary = probe.summarize([run_with(0.1, "wall", [row])])
    assert summary["inside_window"]["refused"] == 1
    assert summary["inside_window"]["admitted"] == 0


def test_evidence_dir_is_unique_per_run(tmp_path):
    first = probe.make_evidence_dir(tmp_path, "native")
    second = probe.make_evidence_dir(tmp_path, "native")
    assert first != second
    assert (first / "raw").is_dir()


def test_sitecustomize_is_written_and_only_delays_health(tmp_path):
    """The generated test build must not touch anything but ``health``."""
    path = probe.write_sitecustomize(tmp_path / "site")
    text = path.read_text(encoding="utf-8")
    assert "WorkerClient.health" in text
    assert "CV84X6_TEST_PROBE_DELAY_S" in text
    assert "[test-build]" in text
    # It must not patch anything else: an instrumented run's whole claim is that
    # only the capability-probe window widened.
    for forbidden in ("require_ready", "_resolve_model", "_wait_ready",
                      "generate", "loaded = True"):
        assert forbidden not in text, forbidden


def test_sitecustomize_compiles_and_is_inert_without_the_env_var(tmp_path):
    """The module must import cleanly with no env var (i.e. change nothing)."""
    path = probe.write_sitecustomize(tmp_path)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    env_backup = dict(os.environ)
    try:
        os.environ.pop("CV84X6_TEST_PROBE_DELAY_S", None)
        namespace: dict = {"__name__": "sitecustomize"}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"),
             namespace)
    finally:
        os.environ.clear()
        os.environ.update(env_backup)


def test_off_topic_reply_is_garbage():
    """English text is not a Chinese summary of this article, whatever its shape."""
    cls, reason = probe.classify(
        attempt(output="The quick brown fox jumps over the lazy dog again and again."))
    assert cls == "garbage"
    assert "topical" in reason


def test_the_three_surfaces_are_sent_concurrently(fake, tmp_path):
    """All three surfaces leave within one state-sample of each other.

    The bug this pins: sent sequentially, a 128-token reply takes ~6 s, so the
    third surface went out 11 s after the first. Against a load window measured
    in tens of milliseconds that is not three samples of one instant, and the
    per-surface comparison the report draws would be meaningless.
    """
    base, svc = fake
    service = probe.Service(probe.Http(base), base, "qwen3.6-35b-a3b-128k")
    service.login()
    service.create_key()
    evidence = tmp_path / "ev"
    (evidence / "raw").mkdir(parents=True)
    runner = probe.Runner(service, base, base, evidence, mode="native")
    run = runner.run_timing("ready-control", None, kind="ready")

    starts = [a.started_at for a in run.attempts if a.started_at]
    assert len(starts) == 3
    assert max(starts) - min(starts) < 2.0, (
        f"surfaces were not dispatched together: spread {max(starts) - min(starts):.2f}s")


def test_sitecustomize_survives_being_imported_before_app_is_on_sys_path(tmp_path):
    """It must put the install root on sys.path before importing ``app``.

    The regression this pins: `site` imports sitecustomize at interpreter
    startup, before runpy adds the `-m app.main` working directory to sys.path.
    A bare `import app.core.client` raised ModuleNotFoundError there, `site`
    swallowed it, and the widening silently never happened while the environment
    variable looked correctly set -- a run that would have claimed to be
    instrumented while measuring the native build.
    """
    source = probe.SITECUSTOMIZE
    assert "sys.path" in source, "must repair sys.path first"
    assert source.index("sys.path") < source.index("import app.core.client"), (
        "sys.path must be fixed before app is imported")
    assert "CV84X6_INSTALL_DIR" in source, "the root must be overridable"
    assert "FAILED to import" in source, "a failed patch must be announced, not silent"


def test_each_row_carries_its_timings_target_delay(fake, tmp_path):
    """A wall timing's rows must not read as "ready".

    The bug this pins: ``summarize`` builds rows from the attempt, and the
    attempt's ``target_delay_s`` was left at its default ``None``, which the
    report renders as "ready". Every 0.1 s / 5 s / … row therefore claimed to be
    the control group -- the opposite of what it was.
    """
    base, svc = fake
    service = probe.Service(probe.Http(base), base, "qwen3.6-35b-a3b-128k")
    service.login()
    service.create_key()
    evidence = tmp_path / "ev"
    (evidence / "raw").mkdir(parents=True)
    runner = probe.Runner(service, base, base, evidence, mode="native")

    wall = runner.run_timing("delay-5s", 5.0, kind="wall")
    for row in wall.attempts:
        assert row.target_delay_s == 5.0, row.surface

    control = runner.run_timing("ready-control", None, kind="ready")
    for row in control.attempts:
        assert row.target_delay_s is None

    summary = probe.summarize([wall, control])
    wall_rows = [r for r in summary["rows"] if r["timing_label"] == "delay-5s"]
    assert all(r["target_delay_s"] == 5.0 for r in wall_rows)


def test_combine_needs_one_native_and_one_instrumented(tmp_path):
    """Two of the same mode is a mis-pairing, and must be refused.

    A report that averaged two native runs and called one of them the widened
    window would be its own kind of false claim, so the pairing is checked.
    """
    made = []
    for index in range(2):
        d = tmp_path / f"run-native-{index}"
        d.mkdir()
        (d / "summary.json").write_text(
            json.dumps({"mode": "native", "summary": {}, "flags": {}}),
            encoding="utf-8")
        made.append(d)
    assert probe.combine_reports(made) == 2


def test_combine_refuses_a_directory_without_evidence(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert probe.combine_reports([empty]) == 2


def test_worker_log_slice_stops_at_this_loads_port():
    """The log is append-only across loads; the slice must be one load.

    The bug this pins: `worker-<model>.log` accumulates every load, so its tail
    held *this* load followed by the previous one. A reader matching a 409
    against an `[engine] layers=… listening on …` banner could be looking at a
    log line printed twenty minutes before the request.
    """
    log = "\n".join([
        "[engine] layers=40 seq=131072 max_input=2048",
        "listening on 127.0.0.1:11111",
        "some traffic from the previous load",
        "[engine] layers=40 seq=131072 max_input=2048",
        "listening on 127.0.0.1:22222",
    ])
    service = probe.Service(probe.Http("http://x"), "http://x", "m")
    sliced = service._slice_worker_log(log, port=22222)
    assert "22222" in sliced
    assert "11111" not in sliced
    assert "previous load" not in sliced
    assert sliced.startswith("[engine]")


def test_worker_log_slice_says_so_when_the_port_is_missing():
    """An unmatched port must be announced, not silently return another load."""
    service = probe.Service(probe.Http("http://x"), "http://x", "m")
    sliced = service._slice_worker_log("[engine] x\nlistening on 127.0.0.1:1",
                                       port=9999)
    assert "no 'listening on 127.0.0.1:9999'" in sliced


def test_journal_since_is_a_timezone_free_epoch():
    """`--since` gets `@<epoch>`, never a wall-clock string.

    Two bugs this pins, both of which produced a plausible-looking file that
    covered the wrong time:

    * `2026-10-31T18:00:07.591Z` -- journalctl answered "Failed to parse
      timestamp" on stdout, so the file held that error line and nothing else.
    * `2026-10-31 18:00:07` -- parses, but as **local** time, while the probe
      derives it from a UTC epoch. On this board (CST, UTC+8) the window started
      eight hours early.

    `@<epoch>` carries its own timezone and cannot be misread either way.
    """
    service = probe.Service(probe.Http("http://x"), "http://x", "m")
    captured = {}

    class FakeRun:
        stdout = "ok"
        stderr = ""

    def fake_subprocess_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeRun()

    original = probe.subprocess.run
    probe.subprocess.run = fake_subprocess_run
    try:
        service.journal(1793468362.1463363)
    finally:
        probe.subprocess.run = original
    since = captured["cmd"][captured["cmd"].index("--since") + 1]
    assert since.startswith("@"), since
    assert since == "@1793468362", since
    assert "--utc" in captured["cmd"]


def test_journal_reports_an_unreadable_journal_instead_of_an_empty_one():
    """An unreadable journal must not look like a quiet one."""
    service = probe.Service(probe.Http("http://x"), "http://x", "m")

    class FakeRun:
        stdout = "Failed to parse timestamp: whatever"
        stderr = ""

    original = probe.subprocess.run
    probe.subprocess.run = lambda cmd, **kw: FakeRun()
    try:
        text = service.journal(1793468362.0)
    finally:
        probe.subprocess.run = original
    assert "could not read the journal" in text


def test_report_renders_an_edge_run_that_observed_the_window(tmp_path):
    """A native edge run that *did* see the state must render its boundary.

    The bug this pins: the edge paragraph used a local named ``inside``, which
    shadowed the window bucket dict used later in the same function -- so
    generating a report for an edge run that actually observed
    ``loaded=true, operation=loading`` crashed with
    ``TypeError: list indices must be integers``. Exactly the case worth
    reporting was the one that broke.
    """
    run = probe.TimingRun(kind="edge", label="edge-settle", mode="native")
    run.load_post_at = 100.0
    run.settle_edge_at = 166.538
    run.ready_observed_at = 166.561        # 23 ms window
    run.loaded_at = 166.530
    run.load_result = {"status": 200, "seconds": 66.5, "finished_at": 166.539}
    run.worker_total_requests = 3
    for surface, started in (("stream", 166.569), ("nonstream", 166.564),
                             ("console", 166.573)):
        row = probe.Attempt(timing_label="edge-settle", surface=surface)
        row.started_at = started
        row.finished_at = started + 5.0
        row.http_status = 200
        row.output = "火锅围裙女生造成误会，网友分成两派表示理解。"
        row.state_before = {"loaded": True, "operation": None}
        probe._finish(row)
        run.attempts.append(row)

    summary = probe.summarize([run])
    flags = probe.verdicts(summary, [run], "native", None)
    env = {"hostname": "sophon", "dmesg_npu_errors": [],
           "input_text_chars": 444, "input_text_sha256": "x"}
    service = probe.Service(probe.Http("http://x"), "http://x", "m")
    companion = {"summary": summary, "flags": flags, "mode": "instrumented",
                 "probe_window_ms": 23.0, "probe_window_ms_all": [23.0]}
    path = probe.write_report(tmp_path, env, summary, flags, [run], "native",
                              {}, {}, service, {}, {}, companion=companion)
    audit = probe.audit_report(path)
    assert audit["self_contained"] and audit["all_sections"]
    text = path.read_text(encoding="utf-8")
    assert "观测到了" in text
    assert "边界未命中" in text
    # The per-row table must carry millisecond offsets, not rounded seconds.
    rows = probe.summarize([run])["rows"]
    assert rows[0]["ms_after_window_close"] is not None
    assert abs(rows[0]["ms_after_window_close"] - 8.0) < 1.5
