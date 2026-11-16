"""Concurrency at the HTTP layer, which is what users actually experience."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def make_model(root: Path, name: str):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}_seq4096_4core.bmodel").write_bytes(b"\x00" * 512)
    (d / "config" / "config.json").write_text("{}")


@pytest.fixture()
def app_and_client(tmp_path):
    models = tmp_path / "models"
    make_model(models, "m")
    app = create_app(
        data_dir=tmp_path / "data", models_dir=models,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=8192,
        # 8 ms/token: fast enough for the suite, slow enough that serialised and
        # interleaved runs are distinguishable. At 0 ms the mock finishes a
        # request in microseconds and every concurrency assertion passes
        # trivially -- even against a scheduler that serialises everything.
        decode_delay_ms=8.0,
    )
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        c.post("/api/models/m/load")
        yield app, c


def key_of(c) -> str:
    return c.post("/api/keys", json={"name": "concurrency"}).json()["key"]


def run_concurrent(c, key: str, n: int, prompt_prefix: str) -> tuple[list[dict], float]:
    """Fire n streaming requests at once from a thread pool."""
    from concurrent.futures import ThreadPoolExecutor

    def one(i: int) -> dict:
        arrival = []
        with c.stream("POST", "/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": "m", "stream": True, "max_tokens": 24,
                            "messages": [{"role": "user", "content": f"{prompt_prefix} {i}"}]}) as r:
            assert r.status_code == 200, r.read()
            for line in r.iter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    try:
                        obj = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if obj.get("choices") and obj["choices"][0]["delta"].get("content"):
                        arrival.append(time.monotonic())
        return {"i": i, "arrivals": arrival}

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=n) as ex:
        out = list(ex.map(one, range(n)))
    return out, time.monotonic() - t0


def test_concurrent_streams_interleave(app_and_client):
    """N clients streaming at once must all get tokens, interleaved in time.

    N = 3, the per-model concurrency cap: a fourth request waits for a slot
    (covered by test_requests_over_the_cap_queue_then_run)."""
    _, c = app_and_client
    key = key_of(c)
    out, elapsed = run_concurrent(c, key, 3, "concurrent prompt")
    assert len(out) == 3
    for r in out:
        assert len(r["arrivals"]) > 0, f"request {r['i']} produced no tokens"

    # Order all first-token times. If the server serialised requests, they would
    # be spread out by roughly a full generation each; interleaved requests
    # start close together.
    firsts = sorted(r["arrivals"][0] for r in out)
    lasts = sorted(r["arrivals"][-1] for r in out)
    spread = firsts[-1] - firsts[0]
    total_span = lasts[-1] - firsts[0]
    # Interleaved: every request starts within about one generation step of the
    # others, and the whole batch takes about as long as one request.
    # Serialised: the last first-token is ~n generations late and the span is
    # close to n times a single request.
    assert spread < 0.35 * total_span or spread < 0.6, (
        f"first tokens were serialised: spread={spread:.2f}s of {total_span:.2f}s total"
    )


def test_concurrent_requests_all_complete(app_and_client):
    _, c = app_and_client
    key = key_of(c)
    out, _ = run_concurrent(c, key, 4, "second batch")
    for r in out:
        assert len(r["arrivals"]) >= 5, f"request {r['i']} starved: {len(r['arrivals'])} tokens"


def test_prefix_cache_hit_reported_over_http(app_and_client):
    """The same prompt twice must report cached tokens the second time."""
    _, c = app_and_client
    key = key_of(c)
    prompt = "a long identical system prompt that agents resend every turn " * 3
    h = {"Authorization": f"Bearer {key}"}
    body = {"model": "m", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2}

    first = c.post("/v1/chat/completions", headers=h, json=body).json()
    second = c.post("/v1/chat/completions", headers=h, json=body).json()
    assert first["usage"]["prompt_tokens"] > 8
    assert second["usage"]["prompt_tokens_details"]["cached_tokens"] > 0


def test_requests_over_the_cap_queue_then_run(app_and_client):
    """Six at once with a cap of 3: none refused (queue is 16), all complete."""
    _, c = app_and_client
    key = key_of(c)
    out, _ = run_concurrent(c, key, 6, "queued prompt")
    assert len(out) == 6
    for r in out:
        assert len(r["arrivals"]) > 0, f"request {r['i']} produced no tokens"
