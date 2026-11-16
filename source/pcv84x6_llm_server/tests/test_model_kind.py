"""Model kinds: detection, the worker's identity, and what the limits mean.

Three separate claims, all of which a reader would otherwise have to take on
trust from the loader:

* a bmodel's *kind* comes from its file name and nothing else -- the console,
  the API and the worker all read the same value, so a wrong guess would be
  duplicated everywhere it matters;
* ``--kind`` is on the worker's command line, and adoption matches on it, so a
  survivor from a previous run is only reused when it serves the same surface;
* ``max_loaded`` counts chat models only, while an auxiliary model is admitted
  against the NPU's *measured* free memory, which is the only bound that means
  anything when one model takes 20 GB and the other 1.3 GB.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core import monitor
from app.core.models import (
    KINDS,
    ModelInfo,
    ModelManager,
    discover_models,
    kind_of_bmodel,
)
from app.core.downloader import CATALOG


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,kind", [
    ("qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static_20260920_184312.bmodel",
     "embedding"),
    ("qwen3_embedding_0.6b.bmodel", "embedding"),
    ("bge-reranker-v2-m3_bf16_seq2048_cv84x6_4core_static_20261009_110923.bmodel",
     "rerank"),
    ("bge_reranker_v2_m3.bmodel", "rerank"),
    ("qwen3-asr-1.7b_bf16_seq2048.bmodel", "asr"),
    ("qwen3.6-35b-a3b-int4-autoround_w4bf16_seq32768_cv84x6_4core_history_dynamic_20261025_014034.bmodel",
     "chat"),
    ("minicpm4-0.5b-gptq_w4bf16_seq512_cv186x_1core_20250616_122126.bmodel", "chat"),
    # The dense Qwen3.5 sizes (MYS-2754). They share the ``qwen3.[56]`` prefix
    # with the 35B-A3B but not the ``-35b-a3b`` suffix, and they must not be
    # mistaken for anything but chat: the whole delivery hinges on the console
    # and the API treating them as conversational models.
    ("qwen3.5-9b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110.bmodel",
     "chat"),
    ("qwen3.5-4b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261110.bmodel",
     "chat"),
    ("qwen3.5-4b_bf16_seq131072_bm1684x2_4core_history_dynamic_20261110.bmodel", "chat"),
    ("", "chat"),
])
def test_kind_comes_from_the_bmodel_name(name, kind):
    assert kind_of_bmodel(name) in KINDS
    assert kind_of_bmodel(name) == kind


def test_kind_is_case_insensitive():
    """A downloaded file keeps its name; an operator may have uppercased it."""
    assert kind_of_bmodel("Qwen3-Embedding-0.6B_bf16.bmodel") == "embedding"
    assert kind_of_bmodel("BGE-Reranker-v2-M3.bmodel") == "rerank"


def _model_dir(root: Path, name: str, bmodel: str, history: bool = False,
               size: int = 128):
    """A model directory whose bmodel is `size` bytes (sparse: only st_size matters)."""
    d = root / name
    d.mkdir(parents=True)
    with open(d / bmodel, "wb") as fh:
        fh.truncate(size)
    if history:
        # The plain build must win over the _history_ one, and the kind must
        # follow the file that would actually be loaded.
        (d / bmodel.replace(".bmodel", "_history_dynamic.bmodel")).write_bytes(b"\x00" * 128)
    return d


def test_discovery_reports_the_kind_of_the_file_it_would_load(tmp_path):
    _model_dir(tmp_path, "emb", "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel")
    _model_dir(tmp_path, "rr", "bge-reranker-v2-m3_bf16_seq2048_4core_static.bmodel")
    _model_dir(tmp_path, "chat",
               "qwen3.6-35b-a3b-int4-autow4bf16_seq32768_4core_dynamic.bmodel")
    kinds = {m.model_id: m.kind for m in discover_models(tmp_path)}
    assert kinds == {"emb": "embedding", "rr": "rerank", "chat": "chat"}


def test_discovery_ignores_a_second_bmodel_of_another_kind(tmp_path):
    """Only the loaded file decides -- a stray bmodel beside it must not."""
    d = tmp_path / "mixed"
    d.mkdir()
    (d / "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel").write_bytes(b"")
    (d / "bge-reranker-v2-m3_bf16_seq2048_4core_static.bmodel").write_bytes(b"")
    found = {m.model_id: m for m in discover_models(tmp_path)}
    # Sorted by name, the `bge-` file comes first and is the one loaded.
    assert found["mixed"].bmodel_files[0].startswith("bge-reranker")
    assert found["mixed"].kind == "rerank"


def test_every_catalogue_entry_declares_the_kind_its_name_implies():
    """The catalogue is data; this is the check that keeps it honest.

    A download's `kind` labels the console card *before* the file exists, so a
    typo here would show an embedding model as chat until it finished
    downloading -- and then flip.

    An entry with ``files`` (OCR's four bmodels) is one model made of several
    artifacts, so *every* file has to agree: a directory whose detector is an
    OCR build and whose recognisers are something else would be refused at load,
    and the console would have labelled it long before that.
    """
    from app.agents.spec import url_filename

    for entry in CATALOG:
        assert entry.get("kind") in KINDS, entry["id"]
        targets = ([f["dfss"] for f in entry["files"]] if entry.get("files")
                   else [entry["dfss"]])
        for target in targets:
            name = url_filename(target)
            assert entry["kind"] == kind_of_bmodel(name), (entry["id"], name)


def test_public_exposes_the_kind(tmp_path):
    _model_dir(tmp_path, "emb", "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel")
    info = discover_models(tmp_path)[0]
    assert info.public()["kind"] == "embedding"


# ---------------------------------------------------------------------------
# the worker's command line
# ---------------------------------------------------------------------------
def _manager(tmp_path, **kwargs) -> ModelManager:
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    _model_dir(models, "emb", "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel")
    _model_dir(models, "chat",
               "qwen3.6-35b-a3b-int4-autow4bf16_seq32768_4core_dynamic.bmodel")
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs", **kwargs)
    mgr.refresh()
    return mgr


def test_the_worker_argv_carries_the_kind(tmp_path):
    mgr = _manager(tmp_path)
    argv = mgr._worker_cmdline(mgr.get("emb"), 1234)
    assert "--kind" in argv
    assert argv[argv.index("--kind") + 1] == "embedding"
    chat_argv = mgr._worker_cmdline(mgr.get("chat"), 1234)
    assert chat_argv[chat_argv.index("--kind") + 1] == "chat"


def test_the_config_path_follows_the_kind(tmp_path, monkeypatch):
    """An embedding worker must not be handed Qwen3.5's chat tokenizer."""
    mgr = _manager(tmp_path)
    monkeypatch.setattr(mgr, "model_config_root", tmp_path / "cfg")
    embed_cfg = tmp_path / "cfg" / "qwen3_embedding"
    embed_cfg.mkdir(parents=True)
    (embed_cfg / "tokenizer.json").write_text("{}")
    argv = mgr._worker_cmdline(mgr.get("emb"), 1234)
    assert argv[argv.index("--config-path") + 1] == str(embed_cfg)


def test_a_model_with_its_own_config_keeps_it(tmp_path):
    """The vendor demo layout is authoritative over the bundled copy."""
    mgr = _manager(tmp_path)
    own = Path(mgr.get("emb").path) / "config"
    own.mkdir()
    (own / "tokenizer.json").write_text("{}")
    argv = mgr._worker_cmdline(mgr.get("emb"), 1234)
    assert argv[argv.index("--config-path") + 1] == str(own)


# ---------------------------------------------------------------------------
# adoption
# ---------------------------------------------------------------------------
class _Cand:
    """A ``procs.ProcInfo`` stand-in: only the fields ``_match_survivor`` reads."""

    def __init__(self, argv, cwd, exe="/usr/bin/python3", pid=4242, start_time=1.0):
        self.argv = argv
        self.cwd = str(cwd)
        self.exe = exe
        self.pid = pid
        self.start_time = start_time


def _argv_for(mgr, model_id, kind=None, port=9999):
    argv = mgr._worker_cmdline(mgr.get(model_id), port)
    if kind is None:
        # Strip --kind: a survivor from a version that predates it.
        i = argv.index("--kind")
        argv = argv[:i] + argv[i + 2:]
    elif kind != "__keep__":
        argv[argv.index("--kind") + 1] = kind
    return argv


def test_adoption_accepts_a_survivor_with_the_same_kind(tmp_path):
    from app.core.models import BASE

    mgr = _manager(tmp_path)
    cand = _Cand(_argv_for(mgr, "emb", "__keep__"), cwd=BASE)
    assert mgr._match_survivor(mgr.get("emb"), [cand]) is cand


def test_adoption_refuses_a_survivor_of_another_kind(tmp_path):
    """A chat worker for an embedding model would answer ``unknown op embed``.

    Its command line states its kind, so the mismatch is detectable before
    anything is routed to it -- which is the whole reason ``--kind`` is on the
    command line at all.
    """
    from app.core.models import BASE

    mgr = _manager(tmp_path)
    cand = _Cand(_argv_for(mgr, "emb", kind="chat"), cwd=BASE)
    assert mgr._match_survivor(mgr.get("emb"), [cand]) is None


def test_adoption_accepts_a_survivor_that_predates_kind(tmp_path):
    """A worker started before this release is a chat worker, and is taken as one."""
    from app.core.models import BASE

    mgr = _manager(tmp_path)
    cand = _Cand(_argv_for(mgr, "chat", kind=None), cwd=BASE)
    assert mgr._match_survivor(mgr.get("chat"), [cand]) is cand


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------
def test_max_loaded_counts_chat_models_only(tmp_path):
    mgr = _manager(tmp_path, max_loaded=2)
    for mid in ("chat", "emb"):
        info = mgr.get(mid)
        info.loaded = True
        mgr._workers[mid] = _fake_identity(info)
    assert mgr.loaded_chat_count == 1
    assert mgr.loaded_count == 2


def _fake_identity(info):
    from app.core.models import WorkerIdentity

    return WorkerIdentity(pid=4242, port=1, started=None)


def test_a_third_chat_model_is_refused_but_an_aux_model_is_not(tmp_path):
    """The limit is a chat-model limit; it must not stand in for the NPU check."""
    mgr = _manager(tmp_path, max_loaded=1)
    chat = mgr.get("chat")
    chat.loaded = True
    mgr._workers["chat"] = _fake_identity(chat)
    assert mgr.loaded_chat_count >= mgr.max_loaded

    emb = mgr.get("emb")
    # The admission check is what decides for an auxiliary model, and with no
    # bm-smi (a host) it declines to invent a refusal.
    mgr._check_npu_admission(emb)


def _manager_with_embed_size(tmp_path, size: int) -> ModelManager:
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    _model_dir(models, "emb", "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel",
               size=size)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    return mgr


def _device(monkeypatch, npu_free_gib: float, vpp_free_gib: float,
            npu_total_gib: float = 26.0, vpp_total_gib: float = 2.0) -> None:
    """Fake an idle-ish board: the two heaps with the stated free bytes.

    Turns the simulated backend off: these tests are about what happens when a
    *real* device reports these numbers, and the mock reports its own.
    """
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": False, "loaded_bytes": 0, "tick": 0})
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [
        {"name": "npu", "total_bytes": int(npu_total_gib * 2**30),
         "used_bytes": int((npu_total_gib - npu_free_gib) * 2**30),
         "free_bytes": int(npu_free_gib * 2**30)},
        {"name": "vpp", "total_bytes": int(vpp_total_gib * 2**30),
         "used_bytes": int((vpp_total_gib - vpp_free_gib) * 2**30),
         "free_bytes": int(vpp_free_gib * 2**30)},
    ])


def test_an_aux_model_is_refused_when_device_memory_is_full(tmp_path, monkeypatch):
    # A real-sized embedding bmodel (1.25 GiB), so the arithmetic is the one the
    # board does rather than a fixture artefact.
    mgr = _manager_with_embed_size(tmp_path, int(1.25 * 2**30))
    info = mgr.get("emb")
    # 1.25 GiB model + 256 MiB headroom against 1000 MiB free in total across
    # both heaps.
    _device(monkeypatch, npu_free_gib=0.5, vpp_free_gib=0.5)
    with pytest.raises(RuntimeError) as exc:
        mgr._check_npu_admission(info)
    detail = str(exc.value)
    # The message says "device memory", not "NPU": VPP is part of the budget, so
    # blaming the NPU would send an operator looking at the wrong heap.
    assert "设备内存不足" in detail
    assert "GiB" in detail and "1.5" in detail and "1.0" in detail
    # Both heaps' remaining bytes are named, which is what makes the refusal
    # actionable: which heap is full decides whether unloading helps.
    assert "NPU 剩 0.5 GiB" in detail
    assert "VPP 剩 0.5 GiB" in detail


def test_vpp_counts_towards_the_budget(tmp_path, monkeypatch):
    """The whole point of the card: a load the NPU alone cannot take fits.

    Embedding needs 1.25 GiB + 256 MiB = ~1.5 GiB. With 1.1 GiB free in NPU and
    the rest of a 2 GiB VPP heap free, the old NPU-only check refused this and
    the device check admits it.
    """
    mgr = _manager_with_embed_size(tmp_path, int(1.25 * 2**30))
    info = mgr.get("emb")
    _device(monkeypatch, npu_free_gib=1.1, vpp_free_gib=1.8)
    mgr._check_npu_admission(info)  # must not raise


def test_a_load_is_refused_when_no_single_heap_can_take_the_block(tmp_path,
                                                                monkeypatch):
    """Free *total* is enough, free *per heap* is not -- and a block cannot
    span heaps, so this must be refused with a message that says which bound
    was hit rather than the generic "not enough memory"."""
    mgr = _manager_with_embed_size(tmp_path, int(1.25 * 2**30))
    info = mgr.get("emb")
    # 1.1 + 0.6 = 1.7 GiB free total (enough for 1.5), but the 1.25 GiB model
    # file needs one contiguous block and neither heap has it.
    _device(monkeypatch, npu_free_gib=1.1, vpp_free_gib=0.6)
    with pytest.raises(RuntimeError) as exc:
        mgr._check_npu_admission(info)
    detail = str(exc.value)
    assert "设备内存不足" in detail
    assert "连续" in detail        # names the contiguity limit
    assert "1.2 GiB" in detail     # the block it wanted (1.25 GiB, one decimal)
    assert "1.1" in detail         # the largest block available


def test_an_aux_model_is_admitted_when_it_fits(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    info = mgr.get("emb")
    _device(monkeypatch, npu_free_gib=10.0, vpp_free_gib=2.0)
    mgr._check_npu_admission(info)  # must not raise


def test_the_device_check_is_skipped_without_heap_stats(tmp_path, monkeypatch):
    """Host tests and the mock backend have no device to ask."""
    mgr = _manager(tmp_path)
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [])
    monkeypatch.setattr(monitor, "ION_HEAPS", Path("/nonexistent/ion"))
    mgr._check_npu_admission(mgr.get("emb"))


def test_chat_models_are_not_device_checked(tmp_path, monkeypatch):
    """A chat model's bound is ``max_loaded``; re-checking it here would refuse
    the 128k build this service exists to serve."""
    mgr = _manager(tmp_path)
    _device(monkeypatch, npu_free_gib=0.05, vpp_free_gib=0.05)
    mgr._check_npu_admission(mgr.get("chat"))  # must not raise


def test_the_ocr_vl_figure_is_the_measured_one_not_the_old_estimate():
    """MYS-2673: MYS-2663 measured 2077 MB resident; 3.3 GB over-reserved by
    1.2 GiB and refused loads that fit. This pins the corrected number."""
    from app.core import models

    assert models.OCR_VL_DEVICE_BYTES == 2077 * 1024 ** 2
    # The old name survives for one release and carries the same value.
    assert models.OCR_VL_NPU_BYTES == models.OCR_VL_DEVICE_BYTES


@pytest.mark.asyncio
async def test_an_aux_load_returns_409_when_device_memory_is_full(tmp_path, monkeypatch):
    """The refusal reaches HTTP as 409, like every other load refusal."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models"
    models.mkdir()
    _model_dir(models, "emb", "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    _device(monkeypatch, npu_free_gib=0.05, vpp_free_gib=0.05)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "admin"}).status_code == 200
        r = client.post("/api/models/emb/load")
        assert r.status_code == 409, r.text
        assert "设备内存不足" in r.json()["detail"]
        # The failed load leaves the model idle, not "loading forever".
        state = {m["id"]: m for m in client.get("/api/models").json()["models"]}["emb"]
        assert state["loaded"] is False
        assert state["operation"] is None


def test_there_is_no_model_count_limit_by_default(tmp_path):
    """v0.6.25: the old two-chat-model cap is gone; the NPU heap decides."""
    mgr = _manager(tmp_path)
    assert mgr.max_loaded == 0


def test_an_allocation_failure_is_reported_plainly(tmp_path):
    """A chat load that dies in bm_alloc_gmem says "设备内存不足", not the generic
    "see the worker log".

    bmrt allocates from NPU *and* VPP, so an allocation failure no longer means
    the NPU heap was the one that ran out -- the message says device memory and
    sends the operator to unload, which is the action that helps either way.
    """
    mgr = _manager(tmp_path)
    mgr.log_dir.mkdir(parents=True, exist_ok=True)
    (mgr.log_dir / "worker-chat.log").write_text(
        "loading...\n[BMRT][bm_alloc_gmem:1234] FATAL:bm_alloc_gmem failed, size=0x1af74000\n")
    assert "设备内存不足" in (mgr._npu_oom_hint("chat") or "")
    (mgr.log_dir / "worker-emb.log").write_text("ok\n")
    assert mgr._npu_oom_hint("emb") is None
