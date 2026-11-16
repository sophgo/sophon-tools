"""The board stability suite against a real service process (mock backend).

``test_board_stability_suite.py`` pins the suite's arithmetic. This file pins the
part arithmetic cannot: that ``main()`` actually drives a running service end to
end -- login, key minting, 10 + 10 + 9 + 1 requests, the record cross-check, the
SQLite read, the report, the key cleanup, and the exit code.

It runs the service the suite will meet in production (``app.main.create_app``
with the mock backend, so a real worker subprocess exists) and points the suite
at it over HTTP. The mock answers "2" to every prompt, so most counting grades
come out wrong -- that is expected and, in fact, the point of one of the
assertions: **the verdict must fail when answers are wrong even though every
request succeeded and every record matches.** A suite that passed on wrong
answers would be worse than no suite.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.main import create_app

import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))

import board_stability_suite as suite  # noqa: E402


def make_model(root: Path, name: str) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_seq4096_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_service(tmp_path_factory):
    """A real service on a real port, with one model loaded.

    Module-scoped: starting a worker costs seconds, and the suite is run once
    against it. ``decode_delay_ms=0`` keeps the 30 requests quick.
    """
    root = tmp_path_factory.mktemp("stability")
    models = root / "models"
    make_model(models, "m")
    app = create_app(data_dir=root / "data", models_dir=models, backend_kind="mock",
                     web_dir=root / "web", context_length_override=8192,
                     decode_delay_ms=0.0)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    client = suite.Http(base, timeout=60)
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
    status, _ = client.json("POST", "/api/models/m/load", timeout=60)
    assert status == 200, status
    yield base, root
    server.should_exit = True
    thread.join(timeout=30)


def test_the_suite_runs_end_to_end_and_fails_a_wrong_answer(live_service, tmp_path):
    """The full run, with the headline verdict asserted in both directions.

    The mock worker replies "2" to every prompt. Some rounds genuinely expect 2,
    so ``count_ok`` is neither all-true nor all-false -- which is what proves the
    grader is actually reading the answers rather than defaulting.
    """
    base, root = live_service
    evidence = tmp_path / "evidence"
    code = suite.main([
        "--base", base,
        "--password", "admin",
        "--evidence-dir", str(evidence),
        "--data-dir", str(root / "data"),
        "--device-label", "test-board",
        "--timeout", "120",
    ])
    assert code == 1, "the mock answers '2' to a count task, so the run must not pass"

    run = next(evidence.glob("run-*"))
    rounds = [json.loads(line) for line in
              (run / "rounds.jsonl").read_text(encoding="utf-8").splitlines()]
    # 10 nocxt + 10 cxt + 9 concurrent (+ no restart request without --restart).
    assert len(rounds) == 29
    assert {r["group"] for r in rounds} == {"nocxt", "cxt",
                                           "conc-short", "conc-mid", "conc-long"}

    # Every request really reached the service and got a streamed answer.
    assert all(r["http_status"] == 200 for r in rounds), \
        [r for r in rounds if r["http_status"] != 200]
    assert all(r["output"] for r in rounds), "the mock always answers"
    assert all(r["stream_done"] for r in rounds)
    # The JSONL is rewritten after the record check, so the server-side metrics
    # are in it rather than null: the report's TPS/latency columns come from the
    # service's own numbers, and a reader of rounds.jsonl alone must see them.
    assert all(r["req_id"] for r in rounds), "every reply must carry a request id"
    assert all(r["decode_tps"] is not None for r in rounds), \
        [r["group"] for r in rounds if r["decode_tps"] is None]
    assert all(r["server_ttft_s"] is not None for r in rounds)

    # The context group really resent the history: message counts climb 2..20.
    cxt = sorted((r for r in rounds if r["group"] == "cxt"),
                 key=lambda r: r["round_index"])
    assert [r["context_messages"] for r in cxt] == [1 + 2 * i + 1 for i in range(10)]
    nocxt = [r for r in rounds if r["group"] == "nocxt"]
    assert {r["context_messages"] for r in nocxt} == {2}, "system + one user message"

    # Grading is live, and the verdict is driven by the answers: the mock emits a
    # word salad with no digits, so every count fails while every mechanical
    # check (record present, output identical, tokens equal) passes. That
    # separation is the point -- a suite that passed here would be scoring
    # nothing.
    graded = [r["count_ok"] for r in rounds if r["count_ok"] is not None]
    assert graded, "counting must be graded at all"
    assert not any(graded), (
        "the mock never answers with a number, so no count can be right")

    # Every request has exactly one matching record, and the record agrees.
    check = json.loads((run / "records-check.json").read_text(encoding="utf-8"))
    assert check["checked"] == 29
    assert not check["missing"], check["missing"]
    assert not check["missing_from_export"], check["missing_from_export"]
    assert not check["duplicates"], check["duplicates"]
    assert not check["output_mismatch"], check["output_mismatch"]
    assert not check["metrics_mismatch"], check["metrics_mismatch"]
    assert not check["context_mismatch"], check["context_mismatch"]
    assert not check["input_mismatch"], check["input_mismatch"]
    assert not check["not_ok_rows"], check["not_ok_rows"]
    assert not check["secret_leaks"], "the suite must never put a key in a record"
    assert check["export_lines"] >= 29

    # The on-disk record file was read directly and agrees with the client.
    db = json.loads((run / "sqlite-check.json").read_text(encoding="utf-8"))
    assert db["exists"] and db["readable"]
    assert db["found"] == 29 and not db["missing"] and not db["output_mismatch"]

    # Evidence files the report promises all exist and are non-empty.
    for name in ("report.md", "manifest.json", "summary.json", "env.json",
                 "records-export.ndjson", "journal-test.txt", "dmesg.txt"):
        path = run / name
        assert path.is_file() and path.stat().st_size > 0, name
    assert len(list((run / "raw").glob("*.sse"))) == 29

    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"]["passed"] is False
    assert summary["verdict"]["records_missing"] == 0
    assert summary["verdict"]["core_20_ok"] is True
    assert summary["totals"]["http_5xx"] == 0

    # The manifest is the reproducibility record: every prompt, exactly its length.
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["prompts"]) == 19
    for entry in manifest["prompts"]:
        assert entry["chars"] == entry["length"] == len(entry["text"])
        assert suite.sha256(entry["text"]) == entry["sha256"]

    # The report states the failure rather than hiding it.
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "未通过" in report
    assert "验收判定" in report


def test_the_run_removes_only_the_key_it_minted(live_service, tmp_path):
    """A minted key is deleted afterwards; a key it did not create is untouched.

    The acceptance key from the previous stage must survive: deleting other
    people's keys is not "cleanup".
    """
    base, root = live_service
    client = suite.Http(base, timeout=60)
    assert client.login("admin") == 200
    keep = client.json("POST", "/api/keys", {"name": "someone-elses-key"}, timeout=30)[1]

    before = {k["name"] for k in client.json("GET", "/api/keys", timeout=30)[1]["keys"]}
    evidence = tmp_path / "evidence"
    suite.main(["--base", base, "--password", "admin",
                "--evidence-dir", str(evidence), "--data-dir", str(root / "data"),
                "--timeout", "120", "--key-name", "MYS-2498-stability"])
    after = {k["name"] for k in client.json("GET", "/api/keys", timeout=30)[1]["keys"]}

    assert "MYS-2498-stability" not in after, "the run's own key must be removed"
    assert "someone-elses-key" in after, "keys it did not mint must survive"
    assert keep["key"].startswith("sk-")
    del before


def test_a_second_run_never_overwrites_the_first(live_service, tmp_path):
    """Two runs in the same second land in different directories.

    Evidence from a failed run has to outlive the retry, which only holds if the
    directory name cannot collide.
    """
    evidence = tmp_path / "evidence"
    first = suite.make_run_dir(evidence)
    second = suite.make_run_dir(evidence)
    assert first != second
    (first / "rounds.jsonl").write_text("first\n", encoding="utf-8")
    assert (first / "rounds.jsonl").read_text(encoding="utf-8") == "first\n"
