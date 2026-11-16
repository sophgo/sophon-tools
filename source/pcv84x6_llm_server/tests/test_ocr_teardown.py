"""``OcrBackend.close()``: every engine it created, closed in reverse order.

Why this is a test file of its own rather than three asserts inside
``test_ocr_api.py``: the bug it pins was invisible to a mock that only counted
``close()`` calls. The board showed it as

    terminate called after throwing an instance of 'std::runtime_error'
      what():  BMRuntime internal error.

every single time the OCR worker was unloaded, with ``bm free gmem failed`` and
``bm_alloc_gmem failed`` in journalctl immediately before. The cause is
libbmrt's process-wide compute-memory pool: ``ComputeMemory::Destroy`` shrinks
the pool with ``Resize`` (a free followed by a *malloc* of the smaller size) when
the destroyed net was the largest net still sharing it. On this chip that
``Resize`` fails, ``BMRT_ASSERT`` throws, and the throw leaves a destructor --
hence ``terminate()``.

So the order is the fix, and the order is what these tests check:

  * det is created first and is the biggest graph, so destroying it while the
    rec tiers are alive is exactly the case that shrinks the pool;
  * reverse-of-creation order destroys the small rec tiers first, and by the
    time det goes the pool has nothing bigger left to shrink to.

Measured on the 10155 board, 3/3 each: det-first terminated every time, reverse
did not, and the journal was clean.

The other half is the layout engine: it is loaded lazily on the first
``mode="layout"`` request and today's ``close()`` simply forgot it, so a worker
that ever served a layout page leaked its ~21.5 MB until the process died.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.engine import ocr_ppocr

CONFIG = Path(__file__).resolve().parent.parent / "model-config" / "ppocr_v6"


class _FakeEngine:
    """A NetEngine stand-in: records close order against a shared journal."""

    def __init__(self, name: str, journal: list[str]) -> None:
        self.name = name
        self._journal = journal
        self.closed = False
        self.num_inputs = 1
        self.input_shapes = [(1, 3, 736, 736)]

    def close(self) -> None:
        self.closed = True
        self._journal.append(self.name)


def _backend_with(engines: dict[str, _FakeEngine], layout=None):
    """An OcrBackend with its engines replaced; everything else untouched.

    ``__new__`` rather than ``__init__`` because ``__init__`` loads real bmodels
    through the native library, which is not available off the board. What this
    file tests is the close order, which lives entirely in ``close()``.
    """
    backend = ocr_ppocr.OcrBackend.__new__(ocr_ppocr.OcrBackend)
    backend._model_id = "ppocrv6-medium"
    backend._config_dir = str(CONFIG)
    backend._lib_path = "unused"
    backend._dev_id = 0
    backend._gate = None
    backend._lock = threading.Lock()
    backend._det = engines["det"]
    backend._rec = {int(name): engine for name, engine in engines.items()
                    if name != "det"}
    backend._layout = layout
    backend._layout_cfg = None
    backend._rec_paths = {}
    return backend


def test_close_releases_every_engine_it_created():
    """det and all three rec tiers are closed -- none is forgotten."""
    journal: list[str] = []
    engines = {"det": _FakeEngine("det", journal)}
    engines.update({str(w): _FakeEngine(str(w), journal) for w in (320, 640, 1600)})
    backend = _backend_with(engines)

    asyncio.run(backend.close())

    assert sorted(journal) == ["1600", "320", "640", "det"], (
        f"closed {journal}; an engine left open leaks NPU memory for the life "
        "of the worker")
    assert all(e.closed for e in engines.values())
    # The dict is emptied too, so a second close() is a no-op rather than a
    # double free.
    assert backend._rec == {}


def test_close_is_reverse_of_creation_order():
    """Small rec tiers first, det last: the order that avoids bmrt's Resize.

    This is the assertion that would have caught the board's ``terminate``. It
    is stated as an order (not a set) because the failure is order-dependent:
    det is the largest graph and destroying it while the rec tiers are alive is
    what makes libbmrt shrink its shared compute pool.
    """
    journal: list[str] = []
    engines = {"det": _FakeEngine("det", journal)}
    engines.update({str(w): _FakeEngine(str(w), journal) for w in (320, 640, 1600)})
    backend = _backend_with(engines)

    asyncio.run(backend.close())

    assert journal == ["1600", "640", "320", "det"], (
        f"closed in {journal}; det must go last -- see this module's docstring")


def test_close_releases_the_lazily_loaded_layout_engine():
    """Layout mode's engine is closed too, not leaked.

    ``_layout`` is only created on the first ``mode="layout"`` request, which is
    why it went unnoticed: a worker that only ever served ``lines`` never had
    one to leak. After a layout request it is ~21.5 MB of NPU memory, and
    dropping the backend without closing it is a leak that only shows up as
    "the heap did not come back".
    """
    journal: list[str] = []
    layout = _FakeEngine("layout", journal)
    engines = {"det": _FakeEngine("det", journal)}
    engines.update({str(w): _FakeEngine(str(w), journal) for w in (320, 640, 1600)})
    backend = _backend_with(engines, layout=layout)

    asyncio.run(backend.close())

    assert layout.closed, "the layout engine was never closed"
    # Created last, so it goes first -- before det, and before/after the rec
    # tiers does not matter as long as det is last.
    assert journal[0] == "layout", journal
    assert journal[-1] == "det", journal
    assert backend._layout is None, (
        "the attribute must be cleared too, or a second close() calls into a "
        "destroyed engine")


def test_a_worker_that_never_used_layout_still_closes():
    """The common case: no layout engine was ever created."""
    journal: list[str] = []
    engines = {"det": _FakeEngine("det", journal)}
    engines.update({str(w): _FakeEngine(str(w), journal) for w in (320, 640, 1600)})
    backend = _backend_with(engines, layout=None)

    asyncio.run(backend.close())

    assert journal == ["1600", "640", "320", "det"], journal


def test_close_survives_an_engine_that_raises():
    """One failing close must not leave the rest open.

    A close that throws is exactly what the board did (the throw came from
    inside bmrt's destructor), and the remaining engines still have to be
    released: the process is going away and the driver reclaims what it can,
    but on the way out the others must at least have been asked.
    """

    class Exploding(_FakeEngine):
        def close(self) -> None:
            self._journal.append(self.name)
            raise RuntimeError("BMRuntime internal error.")

    journal: list[str] = []
    engines = {"det": _FakeEngine("det", journal)}
    engines.update({str(w): _FakeEngine(str(w), journal) for w in (320, 640, 1600)})
    engines["640"] = Exploding("640", journal)
    backend = _backend_with(engines)

    asyncio.run(backend.close())

    assert journal[-1] == "det", (
        f"a raising close stopped the sweep at {journal}; det was left open")
    for width in (320, 1600):
        assert engines[str(width)].closed, (
            f"rec tier {width} was skipped after another close raised")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
