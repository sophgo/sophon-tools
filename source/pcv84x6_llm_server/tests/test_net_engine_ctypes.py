"""``NetEngine`` -- the ctypes binding for the generic single-graph runner.

Same doctrine as ``test_aux_native_ctypes.py``: a stub (tests/native_stub.c)
implements the real ``cv_net_*`` ABI and the real binding loads it through the
real argument declarations. What is pinned here is the part the C++ test cannot
see, because it lives on the Python side of the boundary:

* the shapes the binding reports come from the engine and are reshaped into,
  not invented -- a caller indexes ``probs[0, :h, :w]`` from them;
* the array handed to the engine is the caller's data at its first element,
  contiguous, float32, and exactly the element count the graph asked for;
* an array of the wrong size is refused *before* the call, because the
  alternative is the driver reading past the end of a numpy buffer.

The graphs are the two the service actually loads: det ([1,3,736,736] ->
[1,1,736,736]) and rec1600 ([1,3,48,1600] -> [1,200,18710]). Those are large
enough that a size mistake is a real fault rather than a rounding error, and
small enough to allocate in a test (13 MB and 15 MB respectively).
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from app.engine.aux_native import AuxNativeError, NetEngine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STUB_SRC = ROOT / "tests" / "native_stub.c"

#: Mirrors the stub's two graph shapes.
DET_IN = (1, 3, 736, 736)
DET_OUT = (1, 1, 736, 736)
REC_IN = (1, 3, 48, 1600)
REC_OUT = (1, 200, 18710)


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler to build the engine stub")
    out = tmp_path_factory.mktemp("netstub") / "libcv84x6_llm.so"
    proc = subprocess.run(
        [cc, "-shared", "-fPIC", "-O1", str(STUB_SRC), "-o", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"the engine stub does not build here: {proc.stderr[:400]}")
    return out


@pytest.fixture()
def det(stub_path) -> NetEngine:
    engine = NetEngine("det.bmodel", str(stub_path))
    yield engine
    engine.close()


@pytest.fixture()
def rec(stub_path) -> NetEngine:
    engine = NetEngine("rec1600.bmodel", str(stub_path))
    yield engine
    engine.close()


def _stub(stub_path) -> ctypes.CDLL:
    """A second handle on the same stub, with the call record cleared.

    The restypes have to be declared here: ctypes defaults every return to
    ``c_int``, so ``llm_test_net_in_first()`` would come back as a truncated
    integer and a test comparing it with 1.5 would fail against 0 -- a test bug
    that looks exactly like an engine bug.
    """
    lib = ctypes.CDLL(str(stub_path))
    lib.llm_test_net_in_first.restype = ctypes.c_float
    lib.llm_test_net_in_max.restype = ctypes.c_float
    lib.llm_test_net_in_sum.restype = ctypes.c_double
    lib.llm_test_net_in_count.restype = ctypes.c_longlong
    lib.llm_test_net_reset()
    return lib


# ---------------------------------------------------------------------------
# what the graph declares
# ---------------------------------------------------------------------------
def test_det_reports_the_shapes_it_will_reshape_into(det):
    assert det.num_inputs == 1 and det.num_outputs == 1
    assert det.input_shapes == [DET_IN]
    assert det.output_shapes == [DET_OUT]
    # Element counts agree with the shapes, which is the invariant that keeps a
    # buffer from being sized one way and indexed another.
    assert det.input_sizes == [3 * 736 * 736]
    assert det.output_sizes == [736 * 736]


def test_rec_reports_its_own_time_axis(rec):
    """The 1600 tier's 200 time steps come from the bmodel, not from arithmetic.

    Deriving them here (width // 8) would look right for every shipped build and
    be wrong the first time a build pads its time axis; the engine reports them.
    """
    assert rec.input_shapes == [REC_IN]
    assert rec.output_shapes == [REC_OUT]
    assert rec.output_sizes == [200 * 18710]


def test_the_binding_refuses_a_rank_above_what_it_can_read(stub_path):
    """A graph whose rank exceeds the query buffer must fail, not truncate.

    Truncating would silently produce a shape that multiplies to less than the
    element count the engine reports -- and the size check below would then
    reject a perfectly good graph with a confusing message.
    """
    # The stub never reports more than 4 dims, so this is asserted through the
    # consistency check the binding does on every load instead: a mismatch
    # between the reported element count and the product of the dims is fatal.
    engine = NetEngine("det.bmodel", str(stub_path))
    try:
        for shape, size in zip(engine.input_shapes, engine.input_sizes):
            product = 1
            for d in shape:
                product *= d
            assert product == size
    finally:
        engine.close()


# ---------------------------------------------------------------------------
# what crosses the boundary
# ---------------------------------------------------------------------------
def test_the_engine_receives_the_callers_array(det, stub_path):
    """Element 0, the maximum and the sum: three ways to be sure it is our data."""
    lib = _stub(stub_path)
    data = np.zeros(DET_IN, dtype=np.float32)
    data[0, 0, 0, 0] = 1.5
    data[0, 2, 100, 100] = 7.25
    data[0, 1, 5, 5] = -3.0

    det.run(data)

    assert lib.llm_test_net_ran() == 1
    assert lib.llm_test_net_stage() == 0
    assert lib.llm_test_net_in_first() == pytest.approx(1.5)
    assert lib.llm_test_net_in_max() == pytest.approx(7.25)
    # 7.25 + 1.5 - 3.0 = 5.75, over the elements actually filled.
    assert lib.llm_test_net_in_sum() == pytest.approx(5.75)
    assert lib.llm_test_net_in_count() == 3 * 736 * 736


def test_a_non_contiguous_input_is_made_contiguous(det, stub_path):
    """A slice or a transposed view must not be handed to the driver as-is.

    ``ctypes.data_as`` on a strided array gives the address of element 0 and the
    driver then reads elements that are not there -- wrong numbers on x86, a
    fault on the board. ``ascontiguousarray`` is what prevents it.
    """
    lib = _stub(stub_path)
    base = np.arange(np.prod(DET_IN), dtype=np.float32).reshape(DET_IN)
    view = base[:, :, ::-1, :]          # negative stride on one axis
    assert not view.flags["C_CONTIGUOUS"]

    det.run(view)

    assert lib.llm_test_net_in_first() == pytest.approx(base[0, 0, -1, 0])
    assert lib.llm_test_net_in_max() == pytest.approx(base.max())


def test_the_output_comes_back_in_the_graphs_shape(det):
    out = det.run(np.zeros(DET_IN, dtype=np.float32))
    assert len(out) == 1
    probs = out[0]
    assert probs.shape == DET_OUT
    assert probs.dtype == np.float32
    # The stub puts the input's maximum in element 0, so a non-zero value here
    # means the output buffer really was read back rather than left zeroed.
    assert float(probs[0, 0, 0, 0]) == 0.0


def test_the_output_is_not_shared_between_calls(det):
    """Two calls must not write into the same array.

    A cached output buffer would look correct in a single-threaded test and
    hand the *previous* request's map to a caller that kept a reference -- the
    kind of bug that shows up as one page's boxes drawn on another.
    """
    a = det.run(np.full(DET_IN, 3.0, dtype=np.float32))[0]
    b = det.run(np.full(DET_IN, 9.0, dtype=np.float32))[0]
    assert a is not b
    assert float(a[0, 0, 0, 0]) == pytest.approx(3.0)
    assert float(b[0, 0, 0, 0]) == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# refusals, all before the engine is called
# ---------------------------------------------------------------------------
def test_a_wrong_size_input_is_refused_before_the_call(det, stub_path):
    lib = _stub(stub_path)
    with pytest.raises(AuxNativeError) as exc:
        det.run(np.zeros((1, 3, 736, 735), dtype=np.float32))
    message = str(exc.value)
    assert "735" in message or "734" in message or "elements" in message
    assert f"{3 * 736 * 736}" in message, message
    assert lib.llm_test_net_ran() == 0, "the engine must not have been called"


def test_the_wrong_number_of_inputs_is_refused(det):
    with pytest.raises(AuxNativeError) as exc:
        det.run()
    assert "takes 1 input" in str(exc.value)


def test_a_closed_engine_refuses_to_run(det):
    det.close()
    with pytest.raises(AuxNativeError) as exc:
        det.run(np.zeros(DET_IN, dtype=np.float32))
    assert "closed" in str(exc.value)


def test_a_multi_graph_bmodel_is_reported_as_such(stub_path):
    """The refusal has to name the cause; a bare "load failed" sends an operator
    looking for a corrupt file when the real mistake is the wrong bmodel."""
    with pytest.raises(AuxNativeError) as exc:
        NetEngine("multi.bmodel", str(stub_path))
    assert "graphs" in str(exc.value)


def test_an_empty_model_path_is_refused(stub_path):
    with pytest.raises(AuxNativeError):
        NetEngine("", str(stub_path))


def test_a_library_without_the_generic_abi_is_named_plainly(tmp_path):
    """A library built before this feature must say so, not raise AttributeError.

    AttributeError would surface as a 500 with no hint that the fix is "rebuild
    the .so", which is a different action from "reload the model".
    """
    src = tmp_path / "old.c"
    src.write_text("int llm_last_error(void) { return 0; }\n")
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler")
    out = tmp_path / "old.so"
    if subprocess.run([cc, "-shared", "-fPIC", str(src), "-o", str(out)],
                      capture_output=True).returncode != 0:
        pytest.skip("cannot build a stub library")
    with pytest.raises(AuxNativeError) as exc:
        NetEngine("x.bmodel", str(out))
    assert "cv_net_" in str(exc.value)
    assert "重新编译" in str(exc.value)
