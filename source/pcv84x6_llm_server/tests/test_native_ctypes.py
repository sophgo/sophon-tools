"""The vit inputs reach the engine's C ABI as the addresses of their own buffers.

This is the regression test for MYS-2298: `_prefill` used to call NumPy's
``.ctypes.data_as()`` on every image value, which broke the moment image
preprocessing moved into the C++ library (native/src/vision.cpp) and started
returning ctypes arrays -- ``'c_float_Array_1843200' object has no attribute
'ctypes'``, raised before any NPU work. A mock of the preprocessing cannot catch
that, because a mock is free to return whatever shape the caller assumes.

So nothing here is mocked: a stub C library implements the real C ABI
(tests/native_stub.c), the real ``NativeBackend`` loads it through the real
``_Lib``/``_VisionProc``/``_TokLib`` bindings, and the real ``_prefill`` runs.
The stub records the pointer arguments; the test then reads the memory back
*through those pointers* and checks it against the arrays it built -- so a
buffer that is merely alive somewhere is not enough, the engine has to be
pointed at its first element.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

from app.engine.native import NativeBackend, NativeSession

ROOT = Path(__file__).resolve().parent.parent
STUB_SRC = ROOT / "tests" / "native_stub.c"

# Mirrors struct llm_test_call in tests/native_stub.c.
MAX_IMAGES = 8
MAX_COPY = 512
VIT_DIMS = 1536


class _Call(ctypes.Structure):
    _fields_ = [
        ("is_extend", ctypes.c_int),
        ("n", ctypes.c_int),
        ("n_images", ctypes.c_int),
        ("tokens", ctypes.c_ssize_t),
        ("pos3", ctypes.c_ssize_t),
        ("offsets", ctypes.c_ssize_t),
        ("patches", ctypes.c_ssize_t),
        ("pixels", ctypes.c_ssize_t * MAX_IMAGES),
        ("pos_ids", ctypes.c_ssize_t * MAX_IMAGES),
        ("pos_idx", ctypes.c_ssize_t * MAX_IMAGES),
        ("pos_weight", ctypes.c_ssize_t * MAX_IMAGES),
        ("n_tokens", ctypes.c_int),
        ("n_pos3", ctypes.c_int),
        ("tokens_copy", ctypes.c_int * MAX_COPY),
        ("pos3_copy", ctypes.c_int * (3 * MAX_COPY)),
        ("offsets_copy", ctypes.c_int * MAX_IMAGES),
        ("patches_copy", ctypes.c_int * MAX_IMAGES),
    ]


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler to build the engine stub")
    out = tmp_path_factory.mktemp("nativestub") / "libcv84x6_llm.so"
    proc = subprocess.run(
        [cc, "-shared", "-fPIC", "-O1", str(STUB_SRC), "-o", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"the engine stub does not build here: {proc.stderr[:400]}")
    return out


@pytest.fixture()
def stub(stub_path):
    lib = ctypes.CDLL(str(stub_path))
    lib.llm_test_last.restype = ctypes.POINTER(_Call)
    lib.llm_test_calls.restype = ctypes.c_int
    lib.llm_test_token_len.restype = ctypes.c_int
    lib.llm_test_read_int.argtypes = [ctypes.c_ssize_t, ctypes.c_int]
    lib.llm_test_read_int.restype = ctypes.c_int
    lib.llm_test_read_float.argtypes = [ctypes.c_ssize_t, ctypes.c_int]
    lib.llm_test_read_float.restype = ctypes.c_float
    lib.llm_test_reset()
    return lib


@pytest.fixture()
def backend(tmp_path, stub_path, stub):
    """A real NativeBackend over the stub library; no bmodel, no NPU."""
    tok = tmp_path / "tokenizer.json"
    tok.write_text("{}", encoding="utf-8")
    be = NativeBackend("model.bmodel", str(tok), "stub", lib_path=str(stub_path))
    yield be
    be._handle = None  # the stub owns no engine state; skip llm_engine_free
    be._tok.close()


async def _encode(be, n_images: int):
    text = "<|im_start|>user\n" + (
        "<|vision_start|><|image_pad|><|vision_end|>" * n_images) + "hi<|im_end|>\n"
    return await be.encode(text, [b"\x89PNG fake"] * n_images)


@pytest.mark.asyncio
async def test_real_prefill_passes_the_addresses_of_the_ctypes_buffers(backend, stub):
    """The failure that started this: a real images prompt through a real prefill."""
    prompt = await _encode(backend, 1)
    sess = NativeSession(backend, 1)
    sess._prefill(prompt)  # AttributeError here is the bug

    call = stub.llm_test_last()[0]
    assert call.n == len(prompt)
    assert call.n_images == 1
    assert call.is_extend == 0

    image = prompt.images[0]
    assert call.pixels[0] == ctypes.addressof(image["pixels"])
    assert call.pos_ids[0] == ctypes.addressof(image["pos_ids"])
    assert call.pos_idx[0] == ctypes.addressof(image["pos_idx"])
    assert call.pos_weight[0] == ctypes.addressof(image["pos_weight"])

    # Read back through the engine's own pointers: the engine sees the values
    # _VisionProc and llm_vision_pos_tables produced, at element 0 and beyond.
    patches = image["patches"]
    assert patches == 1 * 4 * 4
    assert stub.llm_test_read_float(call.pixels[0], 0) == pytest.approx(0.0)
    assert stub.llm_test_read_float(call.pixels[0], VIT_DIMS + 3) == pytest.approx(
        (VIT_DIMS + 3) * 0.5)
    assert stub.llm_test_read_int(call.pos_ids[0], 0) == 0
    assert stub.llm_test_read_int(call.pos_ids[0], 2 * patches - 1) == patches - 1 + 100
    assert stub.llm_test_read_int(call.pos_idx[0], 4 * patches - 1) == 3 * (patches - 1) + 3
    assert stub.llm_test_read_float(call.pos_weight[0], 4 * patches - 1) == pytest.approx(
        (patches - 1 + 3) * 0.25)

    # The token / position arrays are locals inside _prefill, so their content
    # is compared from the copy the stub took while the call was running.
    assert call.n_tokens == len(prompt)
    assert list(call.tokens_copy[:call.n_tokens]) == list(prompt)
    assert call.n_pos3 == 3 * len(prompt)
    assert list(call.pos3_copy[:call.n_pos3]) == list(prompt.pos3)


@pytest.mark.asyncio
async def test_two_images_do_not_share_a_buffer(backend, stub):
    """Each image keeps its own pixels and tables; aliasing would be silent."""
    prompt = await _encode(backend, 2)
    sess = NativeSession(backend, 1)
    sess._prefill(prompt)

    call = stub.llm_test_last()[0]
    assert call.n_images == 2
    a, b = prompt.images
    assert call.pixels[0] == ctypes.addressof(a["pixels"])
    assert call.pixels[1] == ctypes.addressof(b["pixels"])
    assert call.pixels[0] != call.pixels[1]
    for field in ("pos_ids", "pos_idx", "pos_weight"):
        assert getattr(call, field)[0] == ctypes.addressof(a[field])
        assert getattr(call, field)[1] == ctypes.addressof(b[field])
        assert getattr(call, field)[0] != getattr(call, field)[1]
    # Offsets and patch counts are the images' own, not both the same.
    assert list(call.offsets_copy[:2]) == [a["offset"], b["offset"]]
    assert a["offset"] != b["offset"]
    assert list(call.patches_copy[:2]) == [a["patches"], b["patches"]]


@pytest.mark.asyncio
async def test_a_text_prompt_still_passes_no_image_pointers(backend, stub):
    """The text path must not start handing the engine stray arrays."""
    prompt = await backend.encode("<|im_start|>user\nhi<|im_end|>\n")
    sess = NativeSession(backend, 1)
    sess._prefill(prompt)

    call = stub.llm_test_last()[0]
    assert call.n_images == 0
    assert call.pos3 == 0  # plain text: the positions are implied
    assert call.n_tokens == len(prompt)
    assert list(call.tokens_copy[:call.n_tokens]) == list(prompt)


def test_the_bug_was_a_numpy_call_on_a_ctypes_array():
    """Pin the actual regression: the vit values have no `.ctypes` to call.

    If someone reintroduces ``.ctypes.data_as()`` on them, it fails exactly as
    it did on the board -- this asserts the shapes that made that call wrong,
    so the test above cannot be "fixed" by making the values look like arrays.
    """
    pixels = (ctypes.c_float * 8)()
    pos_ids = (ctypes.c_int * 8)()
    for value in (pixels, pos_ids):
        assert not hasattr(value, "ctypes")
        with pytest.raises(AttributeError):
            value.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def test_the_backend_tells_the_engine_the_tokenizers_vocabulary_size(backend, stub):
    """The engine cannot range-check token ids unless the worker tells it the size.

    The bmodel does not carry the vocabulary (lm_head fuses argmax, so it never
    appears as a shape), and the tokenizer that does know it sits behind its own
    opaque handle. So the backend has to pass it across on load; without this
    the engine's out-of-range token check is silently dead on the board, and a
    bad id becomes an out-of-bounds gather inside the embedding graph -- a
    corrupt read or a wedged TPU, neither of which the caller can see coming.
    """
    stub.llm_engine_vocab_size.argtypes = [ctypes.c_void_p]
    stub.llm_engine_vocab_size.restype = ctypes.c_int
    assert stub.llm_engine_vocab_size(None) == 2000, (
        "the backend loaded its tokenizer but never told the engine the size")
