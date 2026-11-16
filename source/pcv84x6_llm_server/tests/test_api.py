"""End-to-end tests of the HTTP surface, driving real worker subprocesses."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def make_model(root: Path, name: str, ctx="seq2048"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "test-model")
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/api/login", json={"password": "admin"})
    assert r.status_code == 200, r.text
    return r


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_admin_endpoints_require_login(client):
    for path in ("/api/stats", "/api/models", "/api/keys"):
        assert client.get(path).status_code == 401, path


def test_login_wrong_password(client):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_model_lifecycle_and_openai_call(client):
    login(client)
    models = client.get("/api/models").json()["models"]
    assert [m["id"] for m in models] == ["test-model"]
    assert models[0]["loaded"] is False

    r = client.post("/api/models/test-model/load")
    assert r.status_code == 200, r.text
    assert r.json()["model"]["loaded"] is True

    # Create a key and use it against the OpenAI surface.
    r = client.post("/api/keys", json={"name": "pytest"})
    raw = r.json()["key"]
    assert raw.startswith("sk-")

    h = {"Authorization": f"Bearer {raw}"}
    assert client.get("/v1/models", headers=h).status_code == 200
    assert [m["id"] for m in client.get("/v1/models", headers=h).json()["data"]] == ["test-model"]

    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello there"}],
        "max_tokens": 8,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(body["choices"][0]["message"]["content"], str)
    assert body["usage"]["total_tokens"] == (
        body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )

    # Usage is recorded and visible in stats.
    st = client.get("/api/stats").json()
    assert st["usage"]["requests"] >= 1
    assert st["usage"]["prompt_tokens"] > 0

    assert client.post("/api/models/test-model/unload").status_code == 200
    assert client.get("/api/models").json()["models"][0]["loaded"] is False


def test_openai_rejects_bad_key(client):
    login(client)
    client.post("/api/models/test-model/load")
    r = client.post("/v1/chat/completions", headers={"Authorization": "Bearer sk-bogus"}, json={
        "model": "test-model", "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 401


def test_openai_rejects_missing_key(client):
    login(client)
    client.post("/api/models/test-model/load")
    r = client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 401


def test_chat_on_unloaded_model_is_409(client):
    login(client)
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"}, json={
        "model": "test-model", "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 409
    assert "not loaded" in r.json()["detail"]


def test_streaming_returns_sse_with_done(client):
    login(client)
    client.post("/api/models/test-model/load")
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    with client.stream("POST", "/v1/chat/completions",
                       headers={"Authorization": f"Bearer {raw}"},
                       json={"model": "test-model",
                             "messages": [{"role": "user", "content": "stream please"}],
                             "max_tokens": 6, "stream": True}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "data: " in text
    assert "[DONE]" in text
    chunks = [ln[6:] for ln in text.splitlines() if ln.startswith("data: ") and "[DONE]" not in ln]
    parsed = [json.loads(c) for c in chunks]
    assert parsed[0]["choices"][0]["delta"]["role"] == "assistant"
    assert parsed[0]["object"] == "chat.completion.chunk"
    contents = "".join(
        p["choices"][0]["delta"].get("content", "")
        for p in parsed if p.get("choices")
    )
    assert contents, "streaming must yield actual content"


def test_stop_string_truncates(client):
    login(client)
    client.post("/api/models/test-model/load")
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"}, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "stop test"}],
        "max_tokens": 30,
        "stop": ["the"],
    })
    assert r.status_code == 200
    assert "the" not in r.json()["choices"][0]["message"]["content"]


def test_revoked_key_cannot_call(client):
    login(client)
    client.post("/api/models/test-model/load")
    created = client.post("/api/keys", json={"name": "k"}).json()
    raw, kid = created["key"], created["meta"]["id"]
    h = {"Authorization": f"Bearer {raw}"}
    assert client.get("/v1/models", headers=h).status_code == 200
    assert client.post(f"/api/keys/{kid}/revoke").status_code == 200
    assert client.get("/v1/models", headers=h).status_code == 401


def test_playground_chat(client):
    login(client)
    client.post("/api/models/test-model/load")
    r = client.post("/api/chat", json={"model": "test-model", "prompt": "hi", "max_tokens": 4})
    assert r.status_code == 200, r.text
    assert r.json()["prompt_tokens"] > 0


def test_vision_request_rejected_for_text_model(client):
    login(client)
    client.post("/api/models/test-model/load")
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"}, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "what is this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}],
    })
    assert r.status_code == 400
    assert "does not accept images" in r.json()["detail"]


def test_remote_image_url_rejected(client):
    login(client)
    client.post("/api/models/test-model/load")
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"}, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "http://example.com/x.png"}},
        ]}],
    })
    assert r.status_code == 400
    assert "offline" in r.json()["detail"]


def test_stats_reports_max_loaded_models(client):
    """The UI shows this number; hardcoding it in the front-end drifts from config."""
    login(client)
    st = client.get("/api/stats").json()
    assert isinstance(st["max_loaded_models"], int)
    assert st["max_loaded_models"] >= 0


@pytest.mark.asyncio
async def test_client_stats_do_not_collide(tmp_path):
    """Two concurrent control calls must not steal each other's reply.

    Regression: health/stats used a fixed queue key, so concurrent callers
    overwrote one another and the first hung until timeout -- which made
    /api/stats take a full 3s on every poll.
    """
    import time

    from app.core.client import WorkerClient

    models = tmp_path / "models"
    make_model(models, "m")
    from app.core.models import ModelManager

    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    info = await mgr.load("m")
    try:
        c = WorkerClient(info.port)
        t0 = time.monotonic()
        results = await asyncio.gather(c.stats(), c.stats(), c.health(), c.stats())
        elapsed = time.monotonic() - t0
        await c.close()
        assert elapsed < 2.0, f"control calls serialised or timed out: {elapsed:.2f}s"
        assert results[0]["op"] == "stats"
        assert results[2]["op"] == "health"
    finally:
        await mgr.unload_all()


def test_playground_chat_counts_toward_usage(client):
    """Console traffic must appear in the totals the overview page shows."""
    login(client)
    client.post("/api/models/test-model/load")
    before = client.get("/api/stats").json()["usage"]["requests"]
    with client.stream("POST", "/api/chat/stream",
                       json={"model": "test-model", "prompt": "benchmark me", "max_tokens": 4}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "[DONE]" in body
    after = client.get("/api/stats").json()
    assert after["usage"]["requests"] == before + 1, "console traffic was not recorded"
    assert after["usage"]["prompt_tokens"] > 0


def test_catalog_lists_the_release_models(client):
    """The four self-built 32k/128k chat models, plus the two auxiliary ones.

    The two sophon-demo seq2048 builds used to be listed here; 2k context cannot
    hold the prompts this service exists for, so the chat downloads are those
    four. The embedding and rerank builds sit beside them and are labelled with
    their own ``kind`` -- they are not chat models, and the console uses that
    field rather than the position in this list to tell them apart.
    """
    assert client.get("/api/catalog").status_code == 401
    login(client)
    r = client.get("/api/catalog")
    assert r.status_code == 200
    models = r.json()["models"]
    chat = [m for m in models if m.get("kind") == "chat"]
    assert [m["id"] for m in chat] == [
        "qwen3.6-35b-a3b-128k",
        # MYS-2754: the dense sizes. They exist for the boards that cannot give a
        # chat model 23 GB of NPU, which is most of them once the auxiliary
        # models are resident (docs/qwen35-small.md).
        "qwen3.5-9b-128k",
        "qwen3.5-4b-128k",
    ], "the chat download list is the 35B plus the dense Qwen3.5 9B / 4B w4 (4B bf16 dropped in v0.6.32)"
    assert {m["context"] for m in chat} == {131072}
    assert chat[0]["md5"] == "76b3795892a6debc1159630c879ed05b", "the mask128 build (MYS-2588)"
    for m in chat:
        assert m["dfss"].startswith("open@sophgo.com:/tools/cv84x6_llm_server/")
        assert "installed" in m and m["verified"] is True and m["prefix_cache"] is True
        assert m["md5"] and m["size_bytes"]

    aux = {m["id"]: m for m in models if m.get("kind") != "chat"}
    assert set(aux) == {
        "qwen3-embedding-0.6b", "qwen3-embedding-0.6b-seq512",
        "wemm-embedding-2b",
        "bge-reranker-v2-m3",
        "qwen3-asr-0.6b", "qwen3-asr-1.7b", "ppocrv6-medium",
        # Not chat (it cannot hold a conversation) and not `ocr` (that kind is
        # the det+rec pair behind /v1/ocr); see tests/test_model_kind_ocr_vl.py.
        "paddleocr-vl-1.5",
    }
    assert aux["qwen3-embedding-0.6b"]["kind"] == "embedding"
    assert aux["qwen3-embedding-0.6b-seq512"]["kind"] == "embedding"
    assert aux["bge-reranker-v2-m3"]["kind"] == "rerank"
    assert aux["qwen3-asr-0.6b"]["kind"] == "asr"
    assert aux["qwen3-asr-1.7b"]["kind"] == "asr"
    assert aux["ppocrv6-medium"]["kind"] == "ocr"
    assert aux["paddleocr-vl-1.5"]["kind"] == "ocr_vl"
    assert aux["paddleocr-vl-1.5"]["dfss"].startswith(
        "open@sophgo.com:/tools/cv84x6_llm_server/")
    assert aux["paddleocr-vl-1.5"]["verified"] is True
    assert aux["paddleocr-vl-1.5"]["prefix_cache"] is False, (
        "one KV cache, and there is no way to copy it out")
    for mid in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3"):
        m = aux[mid]
        assert m["verified"] is True and m["md5"] and m["size_bytes"]
        assert m["prefix_cache"] is False, "an aux model has no KV state to cache"
    # The embedding build is ours since MYS-2696: seq2048, published under
    # /tools/ with a download tag so an installed seq8192 board is offered the
    # update. The reranker is still the vendor's file under ext_model_information,
    # which is why only one of the two carries a dflag.
    embed = aux["qwen3-embedding-0.6b"]
    assert embed["dfss"].startswith("open@sophgo.com:/tools/cv84x6_llm_server/")
    assert embed["dfss"].endswith(
        "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel")
    assert embed["dflag"] == "cv84x6_llm_qwen3-embedding-0.6b"
    assert embed["context"] == 2048, "the bmodel's SEQLEN, which is what /v1 refuses on"
    assert embed["md5"] == "b68c2f784b8c93d82c35334d5451cac2"
    # The optional short-text build (MYS-2706): same weights at seq512, its own
    # download tag, and the **same** vector_family -- that field is what lets one
    # knowledge base move between the two without a rebuild.
    short = aux["qwen3-embedding-0.6b-seq512"]
    assert short["dfss"].startswith("open@sophgo.com:/tools/cv84x6_llm_server/")
    assert short["dfss"].endswith(
        "qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel")
    assert short["dflag"] == "cv84x6_llm_qwen3-embedding-0.6b-seq512", (
        "its own tag: repointing the seq2048 tag must not silently move a board "
        "onto the shorter graph")
    assert short["context"] == 512
    assert short["md5"] == "864f09b7e7e2a37d420243d8be7a8346"
    assert short["size_bytes"] == 1205460992
    assert short["verified"] is True and short["prefix_cache"] is False
    assert short["vector_family"] == embed["vector_family"] == "qwen3-embedding-0.6b"
    assert "seq512" in short["title"] and "seq2048" in short["title"], (
        "the card has to say both which档 it is and that the vectors interoperate")
    assert "seq512" in embed["title"] or embed["context"] == 2048
    assert aux["bge-reranker-v2-m3"]["dfss"].startswith(
        "open@sophgo.com:/ext_model_information/LLM/LLM-TPU/")
    assert "dflag" not in aux["bge-reranker-v2-m3"]
    # The two ASR builds are ours, published beside the 35B models: the vendor
    # ships no CV84X6 Qwen3-ASR.
    for mid in ("qwen3-asr-0.6b", "qwen3-asr-1.7b"):
        m = aux[mid]
        assert m["dfss"].startswith("open@sophgo.com:/tools/cv84x6_llm_server/")
        assert m["verified"] is True and m["md5"] and m["size_bytes"]
        assert m["prefix_cache"] is False
    # OCR is one model made of five artifacts (det, three rec tiers and the
    # PP-DocLayout-M segmenter layout mode needs). Its `dfss` is the *first*
    # file (the console enables the card's button when one is present, and posts
    # only url+name), and `files` is the set the API expands it back into -- so
    # a one-click download cannot install just the detector. `size_bytes` is the
    # sum, which is what the disk check and the console's bar read.
    ocr = aux["ppocrv6-medium"]
    assert ocr["dfss"] == ocr["files"][0]["dfss"], (
        "the card's url must be the first file of the set")
    assert len(ocr["files"]) == 5
    # The fifth file is what `mode: "layout"` needs; a set that lost it would
    # ship an OCR model whose layout mode 400s on every request.
    assert ocr["files"][-1]["dflag"] == "cv84x6_llm_ppdoclayout-m"
    assert ocr["files"][-1]["dfss"].endswith(".bmodel")
    for entry in ocr["files"]:
        assert entry["dfss"].startswith("open@sophgo.com:/tools/cv84x6_llm_server/")
        assert entry["md5"] and entry["size_bytes"]
    assert ocr["size_bytes"] == sum(f["size_bytes"] for f in ocr["files"])
    assert ocr["prefix_cache"] is False


def test_a_local_seq2048_model_still_scans_loads_and_serves(tmp_path):
    """Dropping the 2k builds from the catalogue must not touch the engine.

    MYS-2411 removes the two sophon-demo seq2048 entries from the *download
    list*. An operator who already has one on disk (or copies it in by hand)
    must still see it, load it and call it: the console shows a model because a
    directory exists, not because the catalogue names it.
    """
    models = tmp_path / "models"
    make_model(models, "qwen3.5-35b-a3b")          # seq2048, as sophon-demo names it
    app = create_app(
        data_dir=tmp_path / "data", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web",
    )
    with TestClient(app) as c:
        login(c)
        ids = [m["id"] for m in c.get("/api/models").json()["models"]]
        assert ids == ["qwen3.5-35b-a3b"]
        assert [m["id"] for m in c.get("/api/catalog").json()["models"]] != ids, (
            "the 2k model is not in the download list ..."
        )

        assert c.post("/api/models/qwen3.5-35b-a3b/load").status_code == 200
        listed = {m["id"]: m for m in c.get("/api/models").json()["models"]}
        assert listed["qwen3.5-35b-a3b"]["loaded"] is True

        raw = c.post("/api/keys", json={"name": "2k"}).json()["key"]
        h = {"Authorization": f"Bearer {raw}"}
        assert [m["id"] for m in
                c.get("/v1/models", headers=h).json()["data"]] == ["qwen3.5-35b-a3b"]
        r = c.post("/v1/chat/completions", headers=h, json={
            "model": "qwen3.5-35b-a3b",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 4,
        })
        assert r.status_code == 200, r.text
        assert c.post("/api/models/qwen3.5-35b-a3b/unload").status_code == 200


def test_over_long_prompt_is_a_client_error(client):
    login(client)
    assert client.post("/api/models/test-model/load").status_code == 200
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    h = {"Authorization": f"Bearer {raw}"}
    big = "word " * 20000  # far past the 4096-token context of the fixture
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": big}], "max_tokens": 4})
    assert r.status_code == 400, r.text
    assert "context limit" in r.text
    # Streaming reports it as an invalid request too, then ends cleanly.
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": big}], "max_tokens": 4})
    assert "invalid_request_error" in r.text and "[DONE]" in r.text
    assert client.post("/api/models/test-model/unload").status_code == 200


def test_settings_are_clamped_persisted_and_applied_live(client, tmp_path):
    login(client)
    assert client.post("/api/models/test-model/load").status_code == 200
    r = client.post("/api/settings", json={
        "max_concurrent_per_model": 9, "prefix_cache_max_mb": 512,
        "prefix_cache_ttl_min": 30, "max_queue": 4, "prefill_exact_tail": 5000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["max_concurrent_per_model"] == 3   # hard cap
    assert body["settings"]["prefill_exact_tail"] == 1024       # clamped
    applied = body["applied"]["test-model"]
    assert applied["max_concurrent"] == 3 and applied["max_queue"] == 4
    assert applied["exact_tail"] == 1024
    assert applied["cache_ttl_s"] == 1800
    st = client.get("/api/settings").json()
    assert st["prefix_cache_ttl_min"] == 30 and st["max_concurrency_limit"] == 3
    # The service-wide cache ceiling was deleted (MYS-2785) and is no longer
    # reported. The POST above sent 512 anyway and got a 200: a console built
    # before v0.6.34 posts the whole form, and a 422 would break every save.
    assert "prefix_cache_max_mb" not in st
    assert client.post("/api/settings", json={"max_queue": "x"}).status_code == 422
    assert client.post("/api/models/test-model/unload").status_code == 200


def test_the_cache_ceiling_follows_the_model_limit_and_not_a_global_setting(client):
    """The whole MYS-2785 chain, through the real worker process.

    Three steps, each of which failed before the change:

    1. a model with an explicit limit reports a cache ceiling of ``limit -
       static`` -- not 2048 MiB and not whatever ``/api/settings`` says;
    2. posting a huge ``prefix_cache_max_mb`` does not move it;
    3. raising the limit on the *loaded* model raises the ceiling, with no
       unload/reload in between.

    The manager derives the static footprint from the fixture's 1 KiB file (no
    libbmrt on a host), so the assertions are relative to
    ``mem_limit_default_bytes`` rather than to absolute MiB. The limit is set in
    MiB, but the static footprint must reach the worker byte-exact: losing its
    sub-MiB remainder breaks recovery's comparison with the applied budget.

    The mock worker reports no bm-smi, so the *model's* budget is the only
    ceiling in play here -- which is exactly the configuration where the old
    global setting used to win. On the board the device reading can only make
    the ceiling smaller, never larger.
    """
    MIB = 1 << 20
    login(client)
    assert client.post("/api/models/test-model/load").status_code == 200

    view = client.get("/api/models/test-model/settings").json()
    static = view["mem_static_bytes"]
    # A limit that leaves a distinctive amount of runtime budget.
    wanted = static + 640 * MIB
    limit_mb = wanted // MIB
    assert wanted - static >= limit_mb * MIB - MIB      # the quantization bound
    r = client.put("/api/models/test-model/settings", json={"mem_limit_mb": limit_mb})
    assert r.status_code == 200, r.text
    applied = r.json()["applied"]
    expected = limit_mb * MIB - static
    assert applied["mem_runtime_budget_bytes"] == expected
    assert applied["cache_max_bytes"] == expected, (
        "the cache ceiling is not the model's runtime budget")
    assert abs(expected - (wanted - static)) < MIB
    assert applied["device_budget_bytes"] is None, (
        "the mock worker should have no device reading, so this test is about "
        "the model's budget alone")

    # A global number must not be able to enlarge it, and the worker's own stats
    # must agree with what the save reported.
    client.post("/api/settings", json={"prefix_cache_max_mb": 16384})
    st = client.get("/api/stats").json()
    cache = st["kv_cache"]["test-model"]
    assert cache["max_bytes"] == expected
    assert st["workers"]["test-model"]["mem_runtime_budget_bytes"] == expected

    # Raising the limit gives the cache its room back without a reload.
    bigger_mb = (static + 900 * MIB) // MIB
    r = client.put("/api/models/test-model/settings", json={"mem_limit_mb": bigger_mb})
    assert r.status_code == 200, r.text
    assert r.json()["applied"]["cache_max_bytes"] == bigger_mb * MIB - static
    assert r.json()["applied"]["cache_max_bytes"] > expected

    assert client.post("/api/models/test-model/unload").status_code == 200


def test_full_queue_answers_429_not_an_error(client):
    import concurrent.futures

    login(client)
    assert client.post("/api/models/test-model/load").status_code == 200
    client.post("/api/settings", json={"max_queue": 0, "max_concurrent_per_model": 1})
    raw = client.post("/api/keys", json={"name": "q"}).json()["key"]
    h = {"Authorization": f"Bearer {raw}"}

    def one(_):
        return client.post("/v1/chat/completions", headers=h, json={
            "model": "test-model", "max_tokens": 64,
            "messages": [{"role": "user", "content": "count slowly"}]}).status_code
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(one, range(6)))
    assert set(codes) <= {200, 429} and 429 in codes and 200 in codes, codes
    client.post("/api/settings", json={"max_queue": 16, "max_concurrent_per_model": 3})
    assert client.post("/api/models/test-model/unload").status_code == 200


def test_v1_errors_use_openai_error_objects(client):
    """OpenAI SDKs read body["error"]["message"]; FastAPI's bare {"detail": ...}
    reached SDK users as an opaque JSON string (v0.6.29 E2E, MYS-2682).
    `detail` stays alongside so existing callers keep working."""
    r = client.post("/v1/chat/completions", json={"model": "x", "messages": []})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["message"] == "missing API key"
    assert body["error"]["type"] == "invalid_request_error"
    assert "detail" in body

    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    raw = client.post("/api/keys", json={"name": "t"}).json()["key"]
    h = {"Authorization": f"Bearer {raw}"}
    r = client.post("/v1/chat/completions", headers=h, json={"model": "not-loaded", "messages": [
        {"role": "user", "content": "hi"}]})
    assert r.status_code in (404, 409)
    err = r.json()["error"]
    assert err["message"] and err["type"] in ("not_found_error", "invalid_request_error")
    assert isinstance(r.json()["detail"], str)

    r = client.post("/v1/chat/completions", headers=h, json={"model": 3})
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert isinstance(r.json()["detail"], list)


def test_api_errors_keep_their_own_shape(client):
    """The /api format ({detail, code}) is not affected by the /v1 change."""
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    r = client.post("/api/models/no-such/load")
    assert r.status_code == 404 and set(r.json()) == {"detail", "code"}


def test_a_worker_timeout_is_a_503_with_a_reason(client, app, monkeypatch):
    """A worker that never answers surfaced as an unhandled 500 with no message
    (seen on the board while the TPU was wedged, MYS-2682); it is a 503."""
    import asyncio

    login(client)
    client.post("/api/models/test-model/load")
    raw = client.post("/api/keys", json={"name": "t"}).json()["key"]

    async def hang(*a, **k):
        raise asyncio.TimeoutError()

    from app.api import openai_api
    monkeypatch.setattr(openai_api, "_resolve_model", hang)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"},
                   json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    assert "没有响应" in r.json()["error"]["message"]
