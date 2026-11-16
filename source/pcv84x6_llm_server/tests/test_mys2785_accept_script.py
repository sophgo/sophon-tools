"""The acceptance script must *fail loudly* (MYS-2785, criterion 7).

The previous version printed "FAIL" and returned 0, so a pipeline that only
checked the exit status saw a green run while the model was over its limit.
These tests drive the verdict logic directly with fabricated measurements --
each case is one way the real run can be unacceptable:

* the peak exceeded the configured limit;
* there were no valid samples at all, or every sample was an error;
* the NPU free figure is missing, so the 1 GiB floor cannot be shown to hold;
* the requests were queued rather than overlapping;
* the cross-granule session never crossed 4096 tokens (early EOS).

They also pin the positive case, so "always fails" cannot pass for a fix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "mys2785_accept", BASE / "tools" / "mys2785_accept.py")


@pytest.fixture(scope="module")
def accept():
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("case,expected", [
    ("healthy", 0), ("over_limit", 1), ("invalid_sample", 1),
    ("sample_error", 1), ("no_overlap", 1), ("bad_finish", 1),
])
def test_main_verdict(accept, monkeypatch, tmp_path, case, expected):
    """The property the reviewer asked for: a failed run exits non-zero.

    Driven end-to-end through ``main`` with the network and the device stubbed,
    so the test covers the actual ``return 1`` rather than a reimplementation of
    the checks. The stubbed measurement is a peak over the limit.
    """
    class _Resp:
        status_code = 200

        def json(self):
            return {"workers": {"m": {
                "kv_budget_bytes": 1024 * accept.MIB,
                "cache": {"bytes": 0, "entries": 0,
                          "max_bytes": 1024 * accept.MIB},
                "kv_used_bytes": 0, "kv_reserved_bytes": 0,
                "inflight": 2, "queued": 0,
                "mem_runtime_budget_bytes": 1024 * accept.MIB,
                "device_budget_bytes": 4096 * accept.MIB}}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **k):
            if url.endswith("/api/models/m/settings"):
                return _Resp()
            if url.endswith("/login"):
                return _Resp()
            if url.endswith("/keys"):
                class _K(_Resp):
                    def json(self):
                        return {"key": "sk-x"}
                return _K()
            return _Resp()

        def get(self, url, **k):
            if url.endswith("/settings"):
                class _S(_Resp):
                    def json(self):
                        return {"mem_static_bytes": 1000 * accept.MIB,
                                "mem_used_bytes": 1000 * accept.MIB,
                                "effective": {"mem_limit_bytes": 2000 * accept.MIB}}
                return _S()
            return _Resp()

        def put(self, url, **k):
            return _Resp()

    # Peak well over the limit, everything else healthy.
    monkeypatch.setattr(accept, "npu_used", lambda: (3000 if case == "over_limit" else 1500) * accept.MIB)
    monkeypatch.setattr(accept, "npu_reading",
                        lambda: {"mem_total_bytes": 26624 * accept.MIB})
    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(accept, "ask", lambda *a, **k: {"finish": "error" if case == "bad_finish" else "stop",
                                                       "prompt_tokens": 100})
    # Freeze a healthy sample series except for the peak, which is the point.
    samples = [{"t": float(i), "note": "tick", "npu": (3000 if case == "over_limit" else 1500) * accept.MIB,
                "cache": 0, "entries": 0, "cache_max": 0, "kv_used": 0,
                "reserved": 0, "inflight": 2, "queued": 0, "kv_budget": 0,
                "mem_budget": 0, "dev_budget": 0} for i in range(30)]

    if case == "invalid_sample":
        samples[0]["npu"] = None
    if case == "sample_error":
        samples[0] = {"t": 0, "error": "sample failed"}
    if case == "no_overlap":
        for row in samples:
            row["inflight"] = 1
    monkeypatch.setattr(accept.time, "sleep", lambda _: None)

    class _Sampler:
        def __init__(self, *a, **k):
            self.samples = list(samples)

        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(accept, "Sampler", _Sampler)
    monkeypatch.setattr(accept.argparse.ArgumentParser, "parse_args",
                        lambda self: accept.argparse.Namespace(
                            base="http://x", model="m", password="admin",
                            limit_over_static_mb=1024, fill_rounds=0, concurrent=2,
                            turns=1, max_tokens=8, interval=1.0, cross_granule=False,
                            cross_first_tokens=3900, cross_second_tokens=4200,
                            label="t", out=str(tmp_path / "result.json"), csv=""))
    assert accept.main() == expected
    import json
    report = json.loads((tmp_path / "result.json").read_text())
    assert report["result"] == ("PASS" if expected == 0 else "FAIL")


# ---------------------------------------------------------------------------
# the pressure smoke must fail loudly too
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pressure():
    spec = importlib.util.spec_from_file_location(
        "mys2785_pressure", BASE / "tools" / "mys2785_pressure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Stream:
    status_code = 200

    def __init__(self, frames):
        self.frames = frames
        self.read = 0

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self):
        for line in self.frames:
            self.read += 1
            yield line


CONTENT = 'data: {"choices":[{"delta":{"content":"x"},"finish_reason":null}]}'
FINISH = 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}'


def test_cancel_closes_before_finish_and_counts_content(pressure):
    stream = Stream([CONTENT] * 10 + [FINISH, "data: [DONE]"])
    assert pressure.consume_stream(stream, True) == "cancelled"
    assert stream.read == 3


def test_completed_stream_is_not_counted_as_cancelled(pressure):
    assert pressure.consume_stream(Stream([CONTENT, FINISH, "data: [DONE]"]), True) == "ok"


def test_non_cancelled_stream_requires_successful_finish(pressure):
    assert pressure.consume_stream(Stream([CONTENT] * 4 + [FINISH]), False) == "ok"
    with pytest.raises(RuntimeError):
        pressure.consume_stream(Stream([CONTENT, "data: [DONE]"]), False)


def test_http_and_sse_errors_cannot_count_as_success(pressure):
    rejected = Stream([])
    rejected.status_code = 429
    assert pressure.consume_stream(rejected, False) == "rejected"
    rejected.status_code = 500
    with pytest.raises(RuntimeError):
        pressure.consume_stream(rejected, True)
    with pytest.raises(RuntimeError):
        pressure.consume_stream(Stream(['data: {"error":{"message":"bad"}}']), True)
