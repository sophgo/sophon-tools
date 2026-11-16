"""`/api/stats` device-memory and TPU-usage fields, and the VPP reserve.

What the console reads is the contract; these pin the shapes rather than the
probe implementations (those are in test_monitor_smi.py). Two things make the
shapes load-bearing:

* the mock backend must produce them too, with values that move -- the console
  is built against `--backend mock`, and a field that only exists on the board
  cannot be laid out or tested;
* the reserve has to be visible, because it changes what `free_bytes` means by
  ~256 MiB and an operator comparing our figure with `bm-smi` will otherwise
  think one of them is lying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import monitor
from app.core.vpp_reserve import (
    DEFAULT_RESERVE_BYTES,
    RESERVE_ENV,
    VPP_HEAP_MASK,
    VppReservation,
    reserve_bytes_from_env,
)


@pytest.fixture()
def client(tmp_path):
    """A mock-backend service with the console's login done."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models"
    models.mkdir()
    (models / "emb").mkdir()
    (models / "emb" / "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel").write_bytes(
        b"\0" * 4096)
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def test_stats_carries_device_mem_with_both_heaps(client):
    device = client.get("/api/stats").json()["device"]
    mem = device["device_mem"]
    assert mem["total_bytes"] > 0
    assert mem["used_bytes"] >= 0
    assert mem["free_bytes"] == mem["total_bytes"] - mem["used_bytes"]
    assert [h["name"] for h in mem["heaps"]] == ["npu", "vpp"]
    for heap in mem["heaps"]:
        assert heap["total_bytes"] > 0
        # Per-heap free is reported so "which heap is full" is answerable.
        assert heap["free_bytes"] == heap["total_bytes"] - heap["used_bytes"]
    # The mock says so, so nobody mistakes a demo number for a board reading.
    assert mem["source"] == "mock"


def test_stats_carries_tpu_usage_with_cores(client):
    usage = client.get("/api/stats").json()["device"]["tpu_usage"]
    assert set(usage) == {"percent", "cores", "source"}
    assert usage["source"] == "mock"
    assert usage["percent"] is not None
    assert len(usage["cores"]) == 4  # CV84X6 has four TPU cores


def test_the_tpu_frequency_is_gone_from_the_stats_payload(client):
    """MYS-2673: the performance card shows utilisation, not a clock."""
    device = client.get("/api/stats").json()["device"]
    import json
    body = json.dumps(device)
    assert "tpu_freq_mhz" not in body
    # The deprecated object survives but never carries a number.
    assert device["tpu_freq"]["mhz"] is None
    assert "tpu_hz" not in device["clocks"]


def test_the_deprecated_npu_view_is_kept_for_one_release(client):
    """An older console still reads `npu`; it now says it is deprecated."""
    npu = client.get("/api/stats").json()["device"]["npu"]
    assert npu["deprecated"] is True
    assert npu["use"] == "device_mem"
    # Its utilisation numbers are the same ones, not a second source.
    assert npu["total_percent"] == client.get("/api/stats").json()["device"]["tpu_usage"]["percent"]


def test_stats_reports_the_vpp_reserve(client):
    reserve = client.get("/api/stats").json()["vpp_reserve"]
    assert reserve["requested_bytes"] == DEFAULT_RESERVE_BYTES
    assert reserve["env"] == RESERVE_ENV
    # On a host there is no libbmlib, so the block cannot be taken -- and the
    # payload says why rather than claiming a reserve it does not hold.
    assert reserve["acquired"] is False
    assert reserve["reason"]


def test_mock_usage_moves_once_something_is_loaded(client):
    idle = client.get("/api/stats").json()["device"]["tpu_usage"]["percent"]
    assert idle == 0

    assert client.post("/api/models/emb/load").status_code == 200
    samples = {client.get("/api/stats").json()["device"]["tpu_usage"]["percent"]
               for _ in range(12)}
    assert len(samples) > 1, "a chart built on a constant is not a chart"
    assert all(0 <= s <= 100 for s in samples)


def test_mock_device_memory_grows_with_a_loaded_model(client):
    before = client.get("/api/stats").json()["device"]["device_mem"]["used_bytes"]
    assert client.post("/api/models/emb/load").status_code == 200
    after = client.get("/api/stats").json()["device"]["device_mem"]["used_bytes"]
    assert after > before


def test_the_mock_admits_the_same_query_as_the_board(monkeypatch, tmp_path):
    """An aux load is refused on the mock too, once the fake heaps are full.

    Without this the console's "device memory full" path could not be exercised
    off the board at all.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models"
    (models / "emb").mkdir(parents=True)
    (models / "emb" / "qwen3-embedding-0.6b.bmodel").write_bytes(b"\0" * 4096)
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    # Fill *both* simulated heaps: 26 GiB NPU + 2 GiB VPP.
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": True, "loaded_bytes": 28 * 2**30, "tick": 3})
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        r = c.post("/api/models/emb/load")
        assert r.status_code == 409, r.text
        assert "设备内存不足" in r.json()["detail"]
        # The refusal names both heaps, so the console can show which one is full.
        assert "NPU" in r.json()["detail"] and "VPP" in r.json()["detail"]


# -- the reservation ---------------------------------------------------------

def test_reserve_default_is_256_mib():
    assert DEFAULT_RESERVE_BYTES == 256 * 1024 * 1024


def test_reserve_is_configurable(monkeypatch):
    monkeypatch.setenv(RESERVE_ENV, "512")
    assert reserve_bytes_from_env() == 512 * 1024 * 1024
    monkeypatch.setenv(RESERVE_ENV, "0")
    assert reserve_bytes_from_env() == 0


def test_a_bad_reserve_value_falls_back_to_the_default(monkeypatch):
    """A typo in an environment file must not stop the service from starting."""
    monkeypatch.setenv(RESERVE_ENV, "lots")
    assert reserve_bytes_from_env() == DEFAULT_RESERVE_BYTES


def test_zero_disables_without_trying(monkeypatch):
    reserve = VppReservation(requested_bytes=0)
    assert reserve.acquire() is False
    assert reserve.reason == "disabled"
    assert reserve.status()["held_bytes"] == 0


def test_acquisition_without_libbmlib_says_so(monkeypatch):
    """A host: nothing to hold, and `acquired` must not claim otherwise."""
    monkeypatch.setattr(monitor, "_libmgr", {"tried": True, "lib": None})
    reserve = VppReservation(requested_bytes=1 << 20)
    assert reserve.acquire() is False
    assert reserve.acquired is False
    assert reserve.status()["reason"] == "libbmlib not available"


def test_release_is_safe_when_nothing_was_held():
    VppReservation(requested_bytes=1 << 20).release()


def test_the_reserve_asks_for_the_vpp_heap(monkeypatch):
    """Mask 2 is the VPP heap (bmlib `carveout_heap_id[1]`), not 3.

    Mask 3 would let bmlib satisfy the block from NPU, which protects nothing.
    """
    assert VPP_HEAP_MASK == 2


def test_the_reserve_is_taken_before_any_worker_can_start(tmp_path, monkeypatch):
    """Order matters: the block only works by occupying VPP, so a worker that
    allocates first can take the space it was meant to leave."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    calls: list[str] = []
    models = tmp_path / "models"
    models.mkdir()

    import app.main as main_mod

    real_acquire = main_mod.VppReservation.acquire
    real_adopt = main_mod.ModelManager.adopt

    def acquire(self):
        calls.append("reserve")
        return real_acquire(self)

    async def adopt(self):
        calls.append("adopt")
        return await real_adopt(self)

    monkeypatch.setattr(main_mod.VppReservation, "acquire", acquire)
    monkeypatch.setattr(main_mod.ModelManager, "adopt", adopt)
    monkeypatch.setattr(monitor, "_libmgr", {"tried": True, "lib": None})

    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    with TestClient(app):
        pass
    assert calls.index("reserve") < calls.index("adopt")


def test_device_mem_struct_matches_bmlib_layout():
    """``bm_device_mem_t`` is the union first (device_addr, reserved, dmabuf_fd),
    then flags, then size (bmlib_runtime.h:112). Reading ``size`` at offset 0
    returns the low half of the address, which is 0 at a 4 GiB-aligned heap
    base -- the VPP heap on the 10155 board starts at 0x1f00000000."""
    import ctypes

    from app.core.vpp_reserve import _DeviceMem

    assert ctypes.sizeof(_DeviceMem) == 24
    assert _DeviceMem.device_addr.offset == 0
    assert _DeviceMem.flags.offset == 16
    assert _DeviceMem.size.offset == 20
