"""The auxiliary engines' ctypes binding, driven against a stub C library.

Nothing here is mocked: a stub (tests/native_stub.c) implements the real
``cv_embed_*`` / ``cv_rerank_*`` ABI, the real ``aux_native.py`` loads it through
the real argument declarations, and calls it with real arrays. The stub records
the pointers it was handed, so a test can read the memory back through them --
which is how "the engine got the token ids we built, at their first element, as
int32" becomes checkable on a machine with no NPU.

Two things are pinned that a mock backend could never catch:

* the host-side arithmetic the binding owns (L2 normalisation after MRL
  truncation -- the stub deliberately returns an unnormalised ramp), and
* the *sizes* passed across the ABI. ``cv_rerank_forward`` takes three
  SEQLEN-long arrays; a binding that passed a shorter one would read past the
  buffer, which is silent on x86 and a wrong-logit on the board.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

from app.engine.aux_native import (
    AsrEngine,
    AuxNativeError,
    EmbedEngine,
    RerankEngine,
    sigmoid,
)

ROOT = Path(__file__).resolve().parent.parent
STUB_SRC = ROOT / "tests" / "native_stub.c"

STUB_SEQ = 2048
STUB_HIDDEN = 1024
#: The ASR stub's geometry and stop token; see tests/native_stub.c.
STUB_ASR_SEQ = 1024
STUB_ASR_MAX_INPUT = 512
STUB_ASR_AUDIO_LEN = 100
STUB_ASR_PER_CHUNK = 13
STUB_ASR_HIDDEN = 1024
STUB_IM_END = 7


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler to build the engine stub")
    out = tmp_path_factory.mktemp("auxstub") / "libcv84x6_llm.so"
    proc = subprocess.run(
        [cc, "-shared", "-fPIC", "-O1", str(STUB_SRC), "-o", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"the engine stub does not build here: {proc.stderr[:400]}")
    return out


@pytest.fixture()
def embed(stub_path) -> EmbedEngine:
    engine = EmbedEngine("stub.bmodel", str(stub_path))
    yield engine
    engine.close()


@pytest.fixture()
def rerank(stub_path) -> RerankEngine:
    engine = RerankEngine("stub.bmodel", str(stub_path))
    yield engine
    engine.close()


def test_embed_reports_the_graph_dimensions(embed):
    assert embed.seq_len == STUB_SEQ
    assert embed.hidden_size == STUB_HIDDEN


def test_embed_hands_the_engine_the_token_ids_it_was_given(embed, stub_path):
    lib = ctypes.CDLL(str(stub_path))
    lib.llm_test_embed_last.restype = ctypes.POINTER(ctypes.c_int)
    tokens = [11, 22, 33, 44, 55]
    embed.forward(tokens, dimensions=8)

    n, dim = ctypes.c_int(0), ctypes.c_int(0)
    ptr = lib.llm_test_embed_last(ctypes.byref(n), ctypes.byref(dim))
    assert n.value == len(tokens)
    assert dim.value == 8
    assert [ptr[i] for i in range(n.value)] == tokens


def test_embed_normalises_after_truncation(embed):
    """The stub returns ``1, 2, 3, ... dim``; the binding must divide by the norm.

    Doing it the other way round (normalise, then truncate) leaves the norm below
    1, and every client that treats the vector as a unit vector -- which is the
    format's whole promise -- silently computes wrong cosine similarities.
    """
    vec = embed.forward([1, 2, 3], dimensions=4)
    assert vec == pytest.approx([1 / 30**0.5, 2 / 30**0.5, 3 / 30**0.5, 4 / 30**0.5])
    assert sum(x * x for x in vec) ** 0.5 == pytest.approx(1.0, abs=1e-6)


def test_embed_defaults_to_the_full_hidden_size(embed):
    vec = embed.forward([7])
    assert len(vec) == STUB_HIDDEN
    assert sum(x * x for x in vec) ** 0.5 == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("dim", [0, -1, STUB_HIDDEN + 1])
def test_embed_refuses_a_dimension_outside_the_graph(embed, dim):
    with pytest.raises(AuxNativeError) as exc:
        embed.forward([1, 2], dimensions=dim)
    assert "dimensions" in str(exc.value)


def test_embed_refuses_an_empty_token_list(embed):
    with pytest.raises(AuxNativeError):
        embed.forward([])


def test_a_closed_embed_engine_refuses_further_calls(embed):
    embed.close()
    with pytest.raises(AuxNativeError):
        embed.forward([1])


def test_embed_create_reports_the_engines_own_error(stub_path):
    with pytest.raises(AuxNativeError) as exc:
        EmbedEngine("", str(stub_path))
    assert "empty model path" in str(exc.value)


def test_rerank_passes_all_three_arrays_at_full_seq_len(rerank, stub_path):
    """``ids``/``pos``/``mask`` are each exactly SEQLEN long.

    A shorter array would be read past its end by the engine -- silent on x86,
    a garbled position id on the board.
    """
    lib = ctypes.CDLL(str(stub_path))
    ids = [5] * 8 + [1] * (STUB_SEQ - 8)
    pos = [2] * 8 + [1] * (STUB_SEQ - 8)
    mask = [1] * 8 + [0] * (STUB_SEQ - 8)
    score = rerank.forward(ids, pos, mask)
    assert score == pytest.approx(2.0)

    assert [lib.llm_test_rerank_ids(i) for i in range(8)] == [5] * 8
    assert [lib.llm_test_rerank_pos(i) for i in range(8)] == [2] * 8
    assert [lib.llm_test_rerank_mask(i) for i in range(8)] == [1] * 8
    assert lib.llm_test_rerank_mask(8) == 0


@pytest.mark.parametrize("field", ["ids", "pos", "mask"])
def test_rerank_refuses_a_wrong_length_array(rerank, field):
    ids = [0] * STUB_SEQ
    pos = [1] * STUB_SEQ
    mask = [1] * STUB_SEQ
    arrays = {"ids": ids, "pos": pos, "mask": mask}
    arrays[field] = arrays[field][: STUB_SEQ - 1]
    with pytest.raises(AuxNativeError) as exc:
        rerank.forward(arrays["ids"], arrays["pos"], arrays["mask"])
    assert str(STUB_SEQ) in str(exc.value)


def test_a_closed_rerank_engine_refuses_further_calls(rerank):
    rerank.close()
    with pytest.raises(AuxNativeError):
        rerank.forward([0] * STUB_SEQ, [1] * STUB_SEQ, [1] * STUB_SEQ)


def test_sigmoid_is_the_reference_function():
    """``1/(1+e^-x)``, and finite for the logits a broken bmodel can emit."""
    import math

    for x in (-30.0, -1.0, 0.0, 1.0, 30.0):
        assert sigmoid(x) == pytest.approx(1.0 / (1.0 + math.exp(-x)))
    assert sigmoid(1e6) == pytest.approx(1.0)
    assert sigmoid(-1e6) == pytest.approx(0.0)
    assert sigmoid(-1e6) >= 0.0


# ---------------------------------------------------------------------------
# ASR: the one engine with state
# ---------------------------------------------------------------------------
@pytest.fixture()
def asr(stub_path) -> AsrEngine:
    # The stub's vocabulary and stop token are what the real binding passes from
    # the tokenizer; the numbers are arbitrary here.
    engine = AsrEngine("stub.bmodel", str(stub_path), vocab_size=2000,
                       im_end_id=STUB_IM_END)
    yield engine
    engine.close()


def _stub(stub_path):
    lib = ctypes.CDLL(str(stub_path))
    return lib


def test_asr_reports_the_graph_geometry(asr):
    assert asr.seq_len == STUB_ASR_SEQ
    assert asr.max_input_length == STUB_ASR_MAX_INPUT
    assert asr.audio_length == STUB_ASR_AUDIO_LEN
    assert asr.tokens_per_chunk == STUB_ASR_PER_CHUNK
    assert asr.hidden_size == STUB_ASR_HIDDEN


def test_asr_passes_the_vocabulary_and_stop_token_to_the_engine(asr, stub_path):
    """The engine cannot know either -- they live in tokenizer.json."""
    lib = _stub(stub_path)
    lib.llm_test_asr_vocab.restype = ctypes.c_int
    assert lib.llm_test_asr_vocab() == 2000
    assert asr.im_end == STUB_IM_END


def test_asr_hands_the_engine_chunk_major_features_and_their_offsets(asr, stub_path):
    """The tower reads one chunk at a time, so the layout has to be chunk-major.

    Get this wrong -- for instance by passing the frame-major array the extractor
    returned -- and every chunk but the first hears the wrong audio, with no
    error anywhere.
    """
    import numpy as np

    lib = _stub(stub_path)
    lib.llm_test_asr_audio_chunks.restype = ctypes.c_int
    lib.llm_test_asr_audio_feat_count.restype = ctypes.c_int
    lib.llm_test_asr_audio_feat.restype = ctypes.c_float
    lib.llm_test_asr_audio_offset.restype = ctypes.c_int

    chunks = np.arange(3 * 128 * STUB_ASR_AUDIO_LEN, dtype=np.float32).reshape(
        3, 128, STUB_ASR_AUDIO_LEN)
    offsets = [9, 22, 35]
    asr.forward_audio(chunks, offsets)

    assert lib.llm_test_asr_audio_chunks() == 3
    # The whole array is accounted for, and what the engine reads is the
    # chunk-major flattening: sample k of the call is element k of `chunks`.
    assert lib.llm_test_asr_audio_feat_count() == 3 * 128 * STUB_ASR_AUDIO_LEN
    assert lib.llm_test_asr_audio_feat(0) == 0.0
    assert lib.llm_test_asr_audio_feat(128 * STUB_ASR_AUDIO_LEN) == pytest.approx(
        float(128 * STUB_ASR_AUDIO_LEN))
    for i, expected in enumerate(offsets):
        assert lib.llm_test_asr_audio_offset(i) == expected


def test_asr_refuses_features_of_the_wrong_shape(asr):
    import numpy as np

    with pytest.raises(AuxNativeError, match="128"):
        asr.forward_audio(np.zeros((1, 64, STUB_ASR_AUDIO_LEN), dtype=np.float32),
                          [9])
    with pytest.raises(AuxNativeError, match="offsets"):
        asr.forward_audio(np.zeros((2, 128, STUB_ASR_AUDIO_LEN), dtype=np.float32),
                          [9])


def test_asr_passes_the_prompt_through_unchanged(asr, stub_path):
    lib = _stub(stub_path)
    lib.llm_test_asr_first_len.restype = ctypes.c_int
    lib.llm_test_asr_first_token.restype = ctypes.c_int
    lib.llm_test_asr_set_script.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    script = (ctypes.c_int * 2)(11, 12)
    lib.llm_test_asr_set_script(script, 2)

    tokens = [151644, 8948, 198, 151669] + [151676] * 13 + [151670, 151645]
    first = asr.forward_first(tokens)
    assert lib.llm_test_asr_first_len() == len(tokens)
    for i, expected in enumerate(tokens):
        assert lib.llm_test_asr_first_token(i) == expected
    assert first == 11


def test_asr_clear_reaches_the_engine(asr, stub_path):
    """A request must not see the previous one's KV state."""
    lib = _stub(stub_path)
    lib.llm_test_asr_cleared.restype = ctypes.c_int
    before = lib.llm_test_asr_cleared()
    asr.clear()
    assert lib.llm_test_asr_cleared() == before + 1


def test_asr_refuses_a_prompt_longer_than_the_graph(asr):
    with pytest.raises(AuxNativeError, match="MAX_INPUT_LENGTH|longer"):
        asr.forward_first([1] * (STUB_ASR_MAX_INPUT + 1))


def test_a_closed_asr_engine_refuses_further_calls(asr):
    asr.close()
    for call in (lambda: asr.clear(),
                 lambda: asr.forward_audio(__import__("numpy").zeros(
                     (1, 128, STUB_ASR_AUDIO_LEN), dtype="float32"), [9]),
                 lambda: asr.forward_first([1, 2, 3]),
                 lambda: asr.forward_next()):
        with pytest.raises(AuxNativeError, match="closed"):
            call()
