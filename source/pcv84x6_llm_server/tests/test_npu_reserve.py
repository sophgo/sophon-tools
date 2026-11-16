"""NPU headroom admission: the floor that stops the TPU wedging (MYS-2703).

The failure this guards is not "the model did not fit" -- every one of the six
models on the reproduction board fit (30440 MiB allocated of 30720), and the
board still died in two minutes. It is that with the NPU heap nearly full the
*chip* stops: the driver halts completions, `using_flag` sticks at `0xa5a5`, and
only a reboot clears it. So the rule is about the room left over *after* a load.

What the tests pin, and why each is worth writing down:

* the check subtracts the incoming model's footprint, then compares against the
  floor. Comparing against free-as-it-is-now would be the pre-existing "does it
  fit" question, which answered "yes" for the configuration that wedged;
* a **chat** model is checked, not just an auxiliary one -- chat is where the
  failure was observed, and the older admission check deliberately skips it;
* the boundary is `left >= reserve`, so the configured number is admitted;
* the reading is the **NPU** heap. VPP sat at its startup reserve in every
  capture of this failure, so a check that counted VPP would pass exactly the
  configuration that wedges;
* the floor is settable and disableable, because it is a property of this chip.
"""

from __future__ import annotations

import pytest

from app.core import monitor
from app.core.models import (
    AUX_DEVICE_HEADROOM,
    NPU_RESERVE_DEFAULT_BYTES,
    NPU_RESERVE_ENV,
    ModelManager,
    npu_reserve_bytes,
)

RESERVE_MB = NPU_RESERVE_DEFAULT_BYTES >> 20


def _manager(tmp_path) -> ModelManager:
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    # Real-ish sizes: the check subtracts this model's own footprint, so a
    # fixture whose bmodel is a few bytes would make "footprint" zero and the
    # test would pass without the subtraction happening at all.
    for name, size in (("chat", 20480), ("emb", 2605)):
        d = models / name
        d.mkdir()
        with open(d / f"{name}.bmodel", "wb") as f:
            f.truncate(size * 2**20)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    return mgr


def _heaps(monkeypatch, npu_free_mb: int, vpp_free_mb: int = 3838) -> None:
    """Report the two heaps with these free figures, bypassing the mock device."""
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": False, "loaded_bytes": 0, "tick": 0})
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [
        {"name": "npu", "total_bytes": 30720 * 2**20,
         "used_bytes": (30720 - npu_free_mb) * 2**20,
         "free_bytes": npu_free_mb * 2**20},
        {"name": "vpp", "total_bytes": 4094 * 2**20,
         "used_bytes": (4094 - vpp_free_mb) * 2**20,
         "free_bytes": vpp_free_mb * 2**20},
    ])


def _footprint_mb(mgr: ModelManager, kind: str) -> int:
    """What the manager thinks this model will take, in MiB.

    Taken from the manager rather than hard-coded so a change to the estimate
    updates these tests instead of making them pass for the wrong reason. The
    fixture bmodels are 1 KiB, so the raw figure rounds to 0 MiB; the tests need
    a footprint that dominates the arithmetic, so a realistic minimum is used
    when the estimate is smaller than one -- and the *real* estimate is still
    what goes into the check.
    """
    info = mgr.get(kind)
    # The model's limit (static + runtime budget): what it can grow to after the
    # load, which is what the floor has to survive (see _check_npu_reserve).
    if info.kind in ("chat", "ocr_vl"):
        full = mgr.static_bytes(info) + mgr.runtime_budget_bytes(info)
    else:
        full = mgr.static_bytes(info) + AUX_DEVICE_HEADROOM
    mb = -(-full // 2**20)
    assert mb > 0, "fixture has no footprint; the subtraction would be untested"
    return mb


# ---------------------------------------------------------------------------
# the floor itself
# ---------------------------------------------------------------------------
def test_the_default_floor_is_above_the_measured_cliff():
    """1024 MiB, deliberately not the edge of the measured interval.

    The sweep bracketed the boundary between 512 MiB (wedged) and 640 MiB
    (clean) without finding the exact edge. The pre-existing evidence for this
    failure is that 20 clean minutes do not imply clean hours (MYS-2693 R17
    wedged after 130 clean minutes), so the default sits a whole step above the
    highest known-bad point rather than at the boundary.
    """
    assert RESERVE_MB == 1024
    assert RESERVE_MB > 512
    assert RESERVE_MB > 640


def test_the_floor_can_be_set_and_disabled(monkeypatch):
    monkeypatch.setenv(NPU_RESERVE_ENV, "640")
    assert npu_reserve_bytes() == 640 * 2**20
    # 0 is the documented "this board does not have this problem" switch, not a
    # malformed value that should silently revert to the default.
    monkeypatch.setenv(NPU_RESERVE_ENV, "0")
    assert npu_reserve_bytes() == 0
    # A junk value falls back rather than raising: this is read on the load path
    # of a live service, and refusing every load because an env var is a typo
    # would be worse than the reservation it configures.
    monkeypatch.setenv(NPU_RESERVE_ENV, "not-a-number")
    assert npu_reserve_bytes() == NPU_RESERVE_DEFAULT_BYTES


# ---------------------------------------------------------------------------
# what the check does
# ---------------------------------------------------------------------------
def test_the_incoming_model_is_subtracted_before_comparing(tmp_path, monkeypatch):
    """The bug the first version had, pinned.

    Measuring only the free heap asks "is there room right now", which is what
    the pre-existing admission check does and what passed the board that wedged.
    The question has to be "what is left after this model loads".

    Here the heap has plenty free *now*, but the model would consume nearly all
    of it, so the load must be refused.
    """
    mgr = _manager(tmp_path)
    foot = _footprint_mb(mgr, "emb")
    # Free is well above the floor, but footprint leaves less than the floor.
    _heaps(monkeypatch, npu_free_mb=foot + RESERVE_MB - 1)
    with pytest.raises(RuntimeError) as exc:
        mgr._check_npu_reserve(mgr.get("emb"))
    assert "NPU 显存余量不足" in str(exc.value)


def test_the_reproduction_configuration_is_refused(tmp_path, monkeypatch):
    """6-model board before its last load: 280 MiB free, a ~2.1 GiB model coming."""
    mgr = _manager(tmp_path)
    _heaps(monkeypatch, npu_free_mb=280 + 2170)
    with pytest.raises(RuntimeError) as exc:
        mgr._check_npu_reserve(mgr.get("emb"))
    detail = str(exc.value)
    assert f"{RESERVE_MB} MiB" in detail
    # The message has to say what to do about it, and that the consequence is a
    # reboot rather than a failed request -- otherwise "unload a model" reads as
    # a performance suggestion.
    assert "卸载" in detail
    assert "重启" in detail
    assert NPU_RESERVE_ENV in detail


def test_a_chat_model_is_checked_not_just_an_auxiliary_one(tmp_path, monkeypatch):
    """The gap this closes: ``_check_npu_admission`` returns early for chat.

    Reproducing the original bug means loading a chat model onto a heap that is
    already nearly full, so a check that only ran for auxiliary models would
    pass this test's setup and wedge the board.
    """
    mgr = _manager(tmp_path)
    foot = _footprint_mb(mgr, "chat")
    _heaps(monkeypatch, npu_free_mb=foot + 200)
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(mgr.get("chat"))


def test_exactly_the_floor_still_fits(tmp_path, monkeypatch):
    """The boundary is `left >= reserve`: the configured number is admitted, so
    the setting is not off by one against itself."""
    mgr = _manager(tmp_path)
    foot = _footprint_mb(mgr, "chat")
    _heaps(monkeypatch, npu_free_mb=foot + RESERVE_MB)
    mgr._check_npu_reserve(mgr.get("chat"))  # must not raise
    _heaps(monkeypatch, npu_free_mb=foot + RESERVE_MB - 1)
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(mgr.get("chat"))


def test_the_clean_sweep_point_is_admitted(tmp_path, monkeypatch):
    """640 and 1024 MiB free ran 12 min / ~400 requests clean."""
    mgr = _manager(tmp_path)
    foot = _footprint_mb(mgr, "chat")
    _heaps(monkeypatch, npu_free_mb=foot + 2432)
    mgr._check_npu_reserve(mgr.get("chat"))


def test_vpp_does_not_count_towards_the_floor(tmp_path, monkeypatch):
    """VPP was never the heap that ran out; counting it would admit the wedge.

    The reproduction board had 3838 MiB free in VPP at the moment the NPU heap
    had 280 MiB free. A check that summed the two heaps would have seen ~4 GiB
    and admitted the load that killed the board.
    """
    mgr = _manager(tmp_path)
    foot = _footprint_mb(mgr, "chat")
    _heaps(monkeypatch, npu_free_mb=foot + 280, vpp_free_mb=3838)
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(mgr.get("chat"))


def test_the_check_is_off_when_the_floor_is_zero(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    _heaps(monkeypatch, npu_free_mb=10)
    monkeypatch.setenv(NPU_RESERVE_ENV, "0")
    mgr._check_npu_reserve(mgr.get("chat"))  # must not raise


def test_no_device_reading_means_no_refusal(tmp_path, monkeypatch):
    """A dev checkout has no bm-smi; inventing a refusal there breaks every test
    and laptop, and there is no device to be wrong about."""
    mgr = _manager(tmp_path)
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": False, "loaded_bytes": 0, "tick": 0})
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [])
    mgr._check_npu_reserve(mgr.get("chat"))  # must not raise


def test_a_board_without_an_npu_heap_is_not_judged(tmp_path, monkeypatch):
    """Only the heap named ``npu`` is the subject. A reading that lists some
    other heap must not be mistaken for "zero NPU free" and refuse everything."""
    mgr = _manager(tmp_path)
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": False, "loaded_bytes": 0, "tick": 0})
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [
        {"name": "vpp", "total_bytes": 4094 * 2**20,
         "used_bytes": 256 * 2**20, "free_bytes": 3838 * 2**20},
    ])
    mgr._check_npu_reserve(mgr.get("chat"))  # must not raise


def test_the_refusal_names_what_is_loaded(tmp_path, monkeypatch):
    """An operator reading the 409 needs to know which model to unload; the
    check knows the loaded set and saying it costs nothing."""
    mgr = _manager(tmp_path)
    mgr.get("chat").loaded = True
    foot = _footprint_mb(mgr, "emb")
    _heaps(monkeypatch, npu_free_mb=foot + 100)
    with pytest.raises(RuntimeError) as exc:
        mgr._check_npu_reserve(mgr.get("emb"))
    assert "chat" in str(exc.value)


# ---------------------------------------------------------------------------
# the API surface an operator actually sees
# ---------------------------------------------------------------------------
def test_the_refusal_keeps_a_meaningful_error_code():
    """The 409 body's ``code`` must not fall back to the generic one.

    ``classify`` matches a Chinese phrase to decide the code, and falls back to
    the status default when nothing matches (deliberately: a reworded message
    degrades rather than lying). So a new refusal message needs its phrase in
    that table, or the console reports it as a nameless 409.
    """
    from app.core.errors import classify
    from app.core.models import DeviceMemoryError

    try:
        raise DeviceMemoryError("NPU 显存余量不足：加载 chat 后 NPU 只剩 280 MiB")
    except DeviceMemoryError as exc:
        assert classify(str(exc), 409) == "device_memory_insufficient"


# ---------------------------------------------------------------------------
# growth after the load (lead review of MYS-2703)
# ---------------------------------------------------------------------------
def test_a_chat_model_is_counted_at_its_limit_not_its_static_figure(tmp_path, monkeypatch):
    """The 35B grows by its runtime budget after loading (462 MiB by default).

    Counting only static would admit a board at exactly the floor and then let
    the sessions and prefix cache take it into the measured wedge band
    (512 MiB wedged, 640 MiB clean).
    """
    mgr = _manager(tmp_path)
    info = mgr.get("chat")
    static_mb = mgr.static_bytes(info) >> 20
    budget_mb = mgr.runtime_budget_bytes(info) >> 20
    assert budget_mb > 0, "fixture chat model has no runtime budget; nothing to test"
    # Enough for static + floor, not for the runtime budget on top.
    _heaps(monkeypatch, npu_free_mb=static_mb + RESERVE_MB + budget_mb // 2)
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(info)
    _heaps(monkeypatch, npu_free_mb=_footprint_mb(mgr, "chat") + RESERVE_MB)
    mgr._check_npu_reserve(info)


def test_a_loaded_models_runtime_budget_is_committed_even_while_unused(tmp_path, monkeypatch):
    """Free-now includes what the loaded 35B may still grow into; it is not free.

    With the chat model loaded and none of its runtime budget used yet, an
    embedding load that leaves exactly the floor *now* would leave the floor
    minus that budget once the chat model's sessions fill up -- so it is refused.

    **What changed in MYS-2795, and why the second half is no longer the
    opposite of the first.** This test used to continue: set the chat model's
    ``runtime_bytes`` to its whole budget and expect the same load to be
    admitted, on the reading that memory a model has already taken is no longer
    "still to come". That is wrong as an admission rule. ``runtime_bytes`` is a
    per-token *estimate* -- it excludes the park granule rounding and the
    old-plus-new buffer peak a growth holds -- so it understates what the engine
    physically has. Treating it as credit admits an operation against bytes that
    may not exist, and the failure mode is the wedged board this whole check
    exists to prevent. The budget therefore stays committed whether or not the
    model reports using it; a load that physically fits may now be refused, and
    ``docs/model-settings.md`` says to unload first. When a cheaper figure can be
    trusted is a separate question with its own evidence to gather.
    """
    mgr = _manager(tmp_path)
    chat = mgr.get("chat")
    budget = mgr.runtime_budget_bytes(chat)
    assert budget > 0
    chat.loaded = True
    chat.runtime_bytes = 0
    free_mb = _footprint_mb(mgr, "emb") + RESERVE_MB
    _heaps(monkeypatch, npu_free_mb=free_mb)
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(mgr.get("emb"))
    # A model that reports its budget as fully used commits exactly as much.
    chat.runtime_bytes = budget
    with pytest.raises(RuntimeError):
        mgr._check_npu_reserve(mgr.get("emb"))
    # Not a blanket refusal: the same load is admitted once the budget is really
    # free, i.e. once the chat model is gone.
    chat.loaded = False
    mgr._check_npu_reserve(mgr.get("emb"))


def test_a_loaded_auxiliary_models_budget_is_not_committed(tmp_path, monkeypatch):
    """Native auxiliary engines allocate at load and never grow.

    Their configured runtime budget is not future allocation, so it must not be
    held back: doing so refused OCR on the RC board with 2.5 GiB free.
    """
    mgr = _manager(tmp_path)
    emb = mgr.get("emb")
    # The fixture's file name carries no kind marker, so it scans as chat; this
    # test is about an auxiliary engine, so say so explicitly.
    emb.kind = "embedding"
    emb.loaded = True
    emb.runtime_bytes = 0
    assert mgr.runtime_budget_bytes(emb) > 0, "nothing to (not) commit"
    chat = mgr.get("chat")
    # Room for the chat model at its limit plus the floor, nothing more: if the
    # loaded embedding's budget were counted as committed this would be refused.
    _heaps(monkeypatch, npu_free_mb=_footprint_mb(mgr, "chat") + RESERVE_MB)
    mgr._check_npu_reserve(chat)
