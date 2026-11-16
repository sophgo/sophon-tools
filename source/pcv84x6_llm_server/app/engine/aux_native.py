"""ctypes binding for the auxiliary model engines (embedding / rerank / ASR).

The C ABI is in native/src/c_api.cpp (``cv_embed_*`` / ``cv_rerank_*`` /
``cv_asr_*``), the implementations in native/src/embed_engine.cpp,
rerank_engine.cpp and asr_engine.cpp. This file is the Python half: load the
shared library, keep the handles alive, and do the host-side arithmetic the
reference pipelines do -- last-token pooling is in C++ (where the hidden states
already are), while the L2 normalisation and the sigmoid are here, because they
are about the API's numbers and a test can check them without an NPU.

Tokenisation is the caller's: HF ``tokenizers`` from the model's own
``tokenizer.json`` (see app/engine/aux_tok.py), which is the same file the
reference ``AutoTokenizer`` reads. This module never tokenises.

The ASR engine is the odd one out: it owns a KV cache, so it has a request
sequence rather than a single forward (see :class:`AsrEngine`). The decode loop
that runs on top of those primitives lives in ``aux_backend`` next to the
prompt construction, because it is the reference *pipeline*'s behaviour, not the
ABI's.
"""

from __future__ import annotations

import ctypes
import math
import threading
from typing import Sequence

_P = ctypes.POINTER
_c_int_p = _P(ctypes.c_int)
_c_float_p = _P(ctypes.c_float)
_c_float_p_p = _P(_P(ctypes.c_float))
_c_char_p_p = _P(ctypes.c_char_p)


class AuxNativeError(RuntimeError):
    """The native engine refused a call; the message is the engine's own."""


class _Lib:
    """The auxiliary entry points of libcv84x6_llm.so.

    Signature registration only -- no policy, exactly like ``native._Lib``.
    A library built before the auxiliary engines existed simply lacks these
    symbols, which surfaces as AttributeError at bind time and is reported by
    the worker as "this library cannot serve an embedding model" rather than as
    a confusing failure mid-request.
    """

    def __init__(self, path: str) -> None:
        self.lib = ctypes.CDLL(path)
        c = self.lib
        err = _c_char_p_p

        c.cv_embed_create.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.cv_embed_create.restype = ctypes.c_void_p
        c.cv_embed_destroy.argtypes = [ctypes.c_void_p]
        c.cv_embed_info.argtypes = [ctypes.c_void_p, _c_int_p, _c_int_p]
        c.cv_embed_forward.argtypes = [ctypes.c_void_p, _c_int_p, ctypes.c_int,
                                       ctypes.c_int, _c_float_p, err]
        c.cv_embed_forward.restype = ctypes.c_int

        c.cv_rerank_create.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.cv_rerank_create.restype = ctypes.c_void_p
        c.cv_rerank_destroy.argtypes = [ctypes.c_void_p]
        c.cv_rerank_info.argtypes = [ctypes.c_void_p, _c_int_p, _c_int_p]
        c.cv_rerank_forward.argtypes = [ctypes.c_void_p, _c_int_p, _c_int_p,
                                        _c_int_p, _c_float_p, err]
        c.cv_rerank_forward.restype = ctypes.c_int

        c.cv_asr_create.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.cv_asr_create.restype = ctypes.c_void_p
        c.cv_asr_destroy.argtypes = [ctypes.c_void_p]
        c.cv_asr_info.argtypes = [ctypes.c_void_p, _c_int_p, _c_int_p, _c_int_p,
                                  _c_int_p, _c_int_p]
        c.cv_asr_set_vocab.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        c.cv_asr_im_end.argtypes = [ctypes.c_void_p]
        c.cv_asr_im_end.restype = ctypes.c_int
        c.cv_asr_forward_audio.argtypes = [ctypes.c_void_p, _c_float_p,
                                           ctypes.c_int, _c_int_p, err]
        c.cv_asr_forward_audio.restype = ctypes.c_int
        c.cv_asr_forward_first.argtypes = [ctypes.c_void_p, _c_int_p,
                                           ctypes.c_int, err]
        c.cv_asr_forward_first.restype = ctypes.c_int
        c.cv_asr_forward_next.argtypes = [ctypes.c_void_p, err]
        c.cv_asr_forward_next.restype = ctypes.c_int
        c.cv_asr_clear.argtypes = [ctypes.c_void_p]

        # Shared last-error string. Absent from a library that predates the
        # auxiliary engines' error plumbing, hence the getattr.
        last_error = getattr(c, "llm_last_error", None)
        if last_error is not None:
            last_error.restype = ctypes.c_char_p
        self._error_text = ""
        self._has_last_error = last_error is not None

    def error(self, err_ptr: ctypes.c_char_p | None) -> str:
        if err_ptr is not None and err_ptr.value:
            return err_ptr.value.decode("utf-8", "replace")
        return self._error_text or "unknown engine error"


class _NetLib:
    """Only the generic-network entry points, plus the shared error string.

    Separate from ``_Lib`` because that class binds embed/rerank/ASR
    unconditionally: pointing an OCR model at a library old enough to lack
    ``cv_net_*`` would fail on ``cv_embed_create`` first, and "this library
    cannot serve an embedding model" is the wrong sentence for that mistake.
    Binding what this feature needs makes the failure name it.
    """

    def __init__(self, path: str) -> None:
        self.lib = ctypes.CDLL(path)
        c = self.lib
        err = _c_char_p_p
        missing = []
        for name in ("cv_net_create", "cv_net_destroy", "cv_net_info",
                     "cv_net_elements", "cv_net_dtype", "cv_net_run"):
            if not hasattr(c, name):
                missing.append(name)
        if missing:
            raise AuxNativeError(
                f"{path} 缺少通用网络 ABI（{'、'.join(missing)}）；"
                "这个库版本不能运行 OCR 模型，请用本版本重新编译 libcv84x6_llm.so")
        c.cv_net_create.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.cv_net_create.restype = ctypes.c_void_p
        c.cv_net_destroy.argtypes = [ctypes.c_void_p]
        c.cv_net_info.argtypes = [ctypes.c_void_p, _c_int_p, _c_int_p, _c_int_p,
                                  _c_int_p, ctypes.c_int, _c_int_p]
        c.cv_net_info.restype = ctypes.c_int
        c.cv_net_elements.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        c.cv_net_elements.restype = ctypes.c_longlong
        c.cv_net_dtype.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        c.cv_net_dtype.restype = ctypes.c_int
        c.cv_net_run.argtypes = [ctypes.c_void_p, ctypes.c_int, _c_float_p_p,
                                 _c_float_p_p, err]
        c.cv_net_run.restype = ctypes.c_int
        last_error = getattr(c, "llm_last_error", None)
        if last_error is not None:
            last_error.restype = ctypes.c_char_p

    def error(self, err_ptr: ctypes.c_char_p | None) -> str:
        if err_ptr is not None and err_ptr.value:
            return err_ptr.value.decode("utf-8", "replace")
        return "unknown engine error"


class EmbedEngine:
    """Qwen3-Embedding: text in, one L2-normalised vector out.

    One instance == one loaded bmodel. The engine is single-threaded on the NPU
    side (it holds a mutex), so callers do not need their own serialisation;
    they do need to keep the object alive while it runs.
    """

    def __init__(self, model_path: str, lib_path: str, dev_id: int = 0) -> None:
        self._lib = _Lib(lib_path)
        self._lock = threading.Lock()
        err = ctypes.c_char_p()
        handle = self._lib.lib.cv_embed_create(model_path.encode(), dev_id,
                                               ctypes.byref(err))
        if not handle:
            raise AuxNativeError(self._lib.error(err))
        self._handle = handle
        seqlen, hidden = ctypes.c_int(0), ctypes.c_int(0)
        self._lib.lib.cv_embed_info(handle, ctypes.byref(seqlen), ctypes.byref(hidden))
        self.seq_len = int(seqlen.value)
        self.hidden_size = int(hidden.value)

    def close(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self._lib.lib.cv_embed_destroy(handle)

    def forward(self, tokens: Sequence[int], dimensions: int | None = None) -> list[float]:
        """The pooled vector for one token sequence, truncated and normalised.

        ``dimensions`` is MRL truncation, applied *before* normalisation (the
        reference's order: truncate, then divide by the norm) -- doing it the
        other way round yields a vector whose norm is not 1, which is the one
        property an embedding client is entitled to assume.
        """
        if self._handle is None:
            raise AuxNativeError("embed engine is closed")
        if not tokens:
            raise AuxNativeError("embed engine needs at least one token")
        dim = self.hidden_size if dimensions is None else int(dimensions)
        if dim <= 0 or dim > self.hidden_size:
            raise AuxNativeError(
                f"dimensions {dim} outside 1..{self.hidden_size}")
        n = len(tokens)
        ids = (ctypes.c_int * n)(*tokens)
        out = (ctypes.c_float * dim)()
        err = ctypes.c_char_p()
        with self._lock:
            rc = self._lib.lib.cv_embed_forward(
                self._handle, ids, n, dim, out, ctypes.byref(err))
        if rc != 0:
            raise AuxNativeError(self._lib.error(err))
        vec = list(out)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        return vec


class RerankEngine:
    """BGE-Reranker-v2-M3: (query, document) in, one raw logit out."""

    def __init__(self, model_path: str, lib_path: str, dev_id: int = 0) -> None:
        self._lib = _Lib(lib_path)
        self._lock = threading.Lock()
        err = ctypes.c_char_p()
        handle = self._lib.lib.cv_rerank_create(model_path.encode(), dev_id,
                                                ctypes.byref(err))
        if not handle:
            raise AuxNativeError(self._lib.error(err))
        self._handle = handle
        seqlen, hidden = ctypes.c_int(0), ctypes.c_int(0)
        self._lib.lib.cv_rerank_info(handle, ctypes.byref(seqlen), ctypes.byref(hidden))
        self.seq_len = int(seqlen.value)
        self.hidden_size = int(hidden.value)

    def close(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self._lib.lib.cv_rerank_destroy(handle)

    def forward(self, input_ids: Sequence[int], position_ids: Sequence[int],
                attention_mask: Sequence[int]) -> float:
        """The raw logit for one pair; all three arrays are ``seq_len`` long."""
        if self._handle is None:
            raise AuxNativeError("rerank engine is closed")
        n = self.seq_len
        for name, arr in (("input_ids", input_ids), ("position_ids", position_ids),
                          ("attention_mask", attention_mask)):
            if len(arr) != n:
                raise AuxNativeError(
                    f"{name} is {len(arr)} long; this bmodel needs exactly {n}")
        ids = (ctypes.c_int * n)(*input_ids)
        pos = (ctypes.c_int * n)(*position_ids)
        mask = (ctypes.c_int * n)(*attention_mask)
        out = ctypes.c_float(0.0)
        err = ctypes.c_char_p()
        with self._lock:
            rc = self._lib.lib.cv_rerank_forward(self._handle, ids, pos, mask,
                                                 ctypes.byref(out),
                                                 ctypes.byref(err))
        if rc != 0:
            raise AuxNativeError(self._lib.error(err))
        return float(out.value)


class NetEngine:
    """One plain bmodel graph: a float32 tensor in, a float32 tensor out.

    The counterpart of ``native/src/net_engine.cpp``. Unlike the engines above
    it knows nothing about its graph: whatever tensor shapes the bmodel declares
    are reported here and the caller sizes its buffers from them. That is what
    lets one class run both the det graph ([1,3,736,736] -> [1,1,736,736]) and
    the three rec graphs ([1,3,48,W] -> [1,W/8,18710]).

    Both directions are float32 regardless of the graph's internal width: the
    engine converts, so this side never needs to know whether a build is f16,
    bf16 or quantised, and a rebuild at another precision needs no change here.

    One instance == one loaded bmodel. Calls are serialised by a mutex in the
    engine, so callers do not need their own, but they do need to keep the
    object alive while it runs.
    """

    def __init__(self, model_path: str, lib_path: str, dev_id: int = 0) -> None:
        self._lib = _NetLib(lib_path)
        self._lock = threading.Lock()
        err = ctypes.c_char_p()
        handle = self._lib.lib.cv_net_create(model_path.encode(), dev_id,
                                             ctypes.byref(err))
        if not handle:
            raise AuxNativeError(self._lib.error(err))
        self._handle = handle
        n_in = ctypes.c_int(0)
        n_out = ctypes.c_int(0)
        n_stage = ctypes.c_int(0)
        rc = self._lib.lib.cv_net_info(handle, ctypes.byref(n_in), ctypes.byref(n_out),
                                       ctypes.byref(n_stage), None, 0, None)
        if rc != 0:
            self.close()
            raise AuxNativeError("cv_net_info failed on a freshly loaded graph")
        self.num_inputs = int(n_in.value)
        self.num_outputs = int(n_out.value)
        self.num_stages = int(n_stage.value)
        #: (name, dims) for each tensor, read once: they are static for the life
        #: of the handle and every caller needs them before it can allocate.
        self.input_shapes: list[tuple[int, ...]] = []
        self.output_shapes: list[tuple[int, ...]] = []
        self.input_dtypes: list[int] = []
        self.output_dtypes: list[int] = []
        cap = 8  # a CNN tensor never has more than 8 dims; the engine clamps
        ranks = (ctypes.c_int * (self.num_inputs + self.num_outputs))()
        dims = (ctypes.c_int * ((self.num_inputs + self.num_outputs) * cap))()
        rc = self._lib.lib.cv_net_info(handle, None, None, None, ranks, cap, dims)
        if rc != 0:
            self.close()
            raise AuxNativeError("cv_net_info could not read the tensor shapes")
        for i in range(self.num_inputs + self.num_outputs):
            rank = int(ranks[i])
            if rank < 0 or rank > cap:
                self.close()
                raise AuxNativeError(f"tensor {i} reports rank {rank}")
            shape = tuple(int(dims[i * cap + d]) for d in range(rank))
            if i < self.num_inputs:
                self.input_shapes.append(shape)
            else:
                self.output_shapes.append(shape)
        for i in range(self.num_inputs):
            self.input_dtypes.append(int(self._lib.lib.cv_net_dtype(handle, 0, i)))
        for i in range(self.num_outputs):
            self.output_dtypes.append(int(self._lib.lib.cv_net_dtype(handle, 1, i)))
        # Element counts straight from the engine rather than a product here: if
        # the two ever disagreed, the buffer would be the wrong size and the
        # copy would fault on the board instead of raising here.
        self.input_sizes = [int(self._lib.lib.cv_net_elements(handle, 0, i))
                            for i in range(self.num_inputs)]
        self.output_sizes = [int(self._lib.lib.cv_net_elements(handle, 1, i))
                             for i in range(self.num_outputs)]
        for i, (size, shape) in enumerate(zip(self.input_sizes, self.input_shapes)):
            product = 1
            for d in shape:
                product *= d
            if size != product:
                self.close()
                raise AuxNativeError(
                    f"input {i}: engine says {size} elements, shape {shape} "
                    f"multiplies to {product}")

    def close(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self._lib.lib.cv_net_destroy(handle)

    def run(self, *inputs):
        """One forward. Returns a list of numpy arrays, one per output.

        The arrays are float32 and shaped like the graph's own output tensors,
        so a caller indexes ``probs[0, :resize_h, :resize_w]`` rather than
        computing offsets from a flat buffer. numpy is required here and only
        here -- the other auxiliary engines hand back plain lists because their
        outputs are vectors, not maps.
        """
        import numpy as np

        if self._handle is None:
            raise AuxNativeError("network engine is closed")
        if len(inputs) != self.num_inputs:
            raise AuxNativeError(
                f"this graph takes {self.num_inputs} input(s), {len(inputs)} given")
        buffers = []
        ptrs = (_c_float_p * self.num_inputs)()
        for i, value in enumerate(inputs):
            arr = np.ascontiguousarray(value, dtype=np.float32)
            if arr.size != self.input_sizes[i]:
                raise AuxNativeError(
                    f"input {i} has {arr.size} elements, this graph takes "
                    f"{self.input_sizes[i]} (shape {self.input_shapes[i]})")
            buffers.append(arr)
            ptrs[i] = arr.ctypes.data_as(_c_float_p)
        outs = [np.zeros(size, dtype=np.float32) for size in self.output_sizes]
        optrs = (_c_float_p * self.num_outputs)()
        for i, arr in enumerate(outs):
            optrs[i] = arr.ctypes.data_as(_c_float_p)
        err = ctypes.c_char_p()
        with self._lock:
            rc = self._lib.lib.cv_net_run(self._handle, 0, ptrs, optrs,
                                          ctypes.byref(err))
        if rc != 0:
            raise AuxNativeError(self._lib.error(err))
        # Keep the input buffers alive until after the call: ctypes does not own
        # them, and a local that went out of scope before the NPU read it would
        # be a use-after-free that only shows up as wrong numbers.
        del buffers
        return [arr.reshape(shape) for arr, shape in
                zip(outs, self.output_shapes)]


def sigmoid(x: float) -> float:
    """1/(1+e^-x), computed so a very negative logit cannot raise OverflowError.

    ``math.exp(1000)`` raises; the reference demo would only ever see small
    logits, but a corrupt bmodel or a wedged NPU can hand back anything, and a
    500 from a math domain error would hide which of the two happened.
    """
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class AsrEngine:
    """Qwen3-ASR: log-mel features + a prompt in, generated tokens out.

    Unlike the two above this engine is *stateful*: it owns a KV cache, so a
    request is a sequence of calls rather than one forward. The sequence is

        clear()            drop the previous request's history
        forward_audio()    run the audio tower over the mel chunks
        forward_first()    embed + splice + prefill, first token
        forward_next()     one token per call, until ``im_end``

    and :meth:`transcribe` is that sequence with the reference pipeline's
    decode loop around it. Callers should use ``transcribe``: driving the steps
    by hand means re-deriving the stop condition and the ``<asr_text>``
    unwrapping, which is exactly what the reference's pipeline.py does and what
    this class already encodes.
    """

    def __init__(self, model_path: str, lib_path: str, dev_id: int = 0,
                 vocab_size: int = 0, im_end_id: int = -1) -> None:
        self._lib = _Lib(lib_path)
        self._lock = threading.Lock()
        err = ctypes.c_char_p()
        handle = self._lib.lib.cv_asr_create(model_path.encode(), dev_id,
                                             ctypes.byref(err))
        if not handle:
            raise AuxNativeError(self._lib.error(err))
        self._handle = handle
        seqlen = ctypes.c_int(0)
        max_input = ctypes.c_int(0)
        audio_length = ctypes.c_int(0)
        hidden = ctypes.c_int(0)
        per_chunk = ctypes.c_int(0)
        self._lib.lib.cv_asr_info(handle, ctypes.byref(seqlen),
                                  ctypes.byref(max_input),
                                  ctypes.byref(audio_length),
                                  ctypes.byref(hidden), ctypes.byref(per_chunk))
        self.seq_len = int(seqlen.value)
        self.max_input_length = int(max_input.value)
        self.audio_length = int(audio_length.value)
        self.hidden_size = int(hidden.value)
        self.tokens_per_chunk = int(per_chunk.value)
        self._vocab_size = int(vocab_size)
        self._im_end = int(im_end_id)
        self._lib.lib.cv_asr_set_vocab(handle, self._vocab_size, self._im_end)

    def close(self) -> None:
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self._lib.lib.cv_asr_destroy(handle)

    # -- the primitive steps, in the order the reference runs them ----------
    def clear(self) -> None:
        """Drop the previous request's KV state and staged audio.

        Called by :meth:`transcribe` before every request. Exposed because a
        caller that drives the steps itself must do the same: the engine serves
        one sequence at a time and holding context across requests would make
        one transcript depend on another's.
        """
        if self._handle is None:
            raise AuxNativeError("asr engine is closed")
        with self._lock:
            self._lib.lib.cv_asr_clear(self._handle)

    def forward_audio(self, features, offsets) -> None:
        """Run the audio tower over ``[n_chunks, 128, audio_length]`` features.

        ``offsets[i]`` is the prompt index the i-th chunk's tokens start at --
        the reference's ``audio_offset_list``. The features are the log-mel
        values :func:`app.engine.asr_audio.log_mel` produced, chunk-major.
        """
        if self._handle is None:
            raise AuxNativeError("asr engine is closed")
        import numpy as np

        feats = np.ascontiguousarray(features, dtype=np.float32)
        if feats.ndim != 3:
            raise AuxNativeError(f"features should be [chunks, 128, frames], got {feats.shape}")
        n_chunks = int(feats.shape[0])
        if n_chunks == 0:
            raise AuxNativeError("asr engine needs at least one audio chunk")
        if int(feats.shape[1]) * int(feats.shape[2]) != 128 * self.audio_length:
            raise AuxNativeError(
                f"features are [_, {feats.shape[1]}, {feats.shape[2]}]; this bmodel "
                f"takes [_, 128, {self.audio_length}]")
        off = np.ascontiguousarray(offsets, dtype=np.int32)
        if off.size != n_chunks:
            raise AuxNativeError(
                f"{off.size} offsets for {n_chunks} chunks")
        flat = feats.reshape(-1)
        err = ctypes.c_char_p()
        with self._lock:
            rc = self._lib.lib.cv_asr_forward_audio(
                self._handle,
                flat.ctypes.data_as(_c_float_p), n_chunks,
                off.ctypes.data_as(_c_int_p), ctypes.byref(err))
        if rc != 0:
            raise AuxNativeError(self._lib.error(err))

    def forward_first(self, tokens: Sequence[int]) -> int:
        """Embed, splice the staged audio, prefill; returns the first token."""
        if self._handle is None:
            raise AuxNativeError("asr engine is closed")
        n = len(tokens)
        if n == 0:
            raise AuxNativeError("asr engine needs a non-empty prompt")
        ids = (ctypes.c_int * n)(*tokens)
        err = ctypes.c_char_p()
        with self._lock:
            token = self._lib.lib.cv_asr_forward_first(self._handle, ids, n,
                                                       ctypes.byref(err))
        if token < 0:
            raise AuxNativeError(self._lib.error(err))
        return int(token)

    def forward_next(self) -> int:
        """One decode step; returns the next token."""
        if self._handle is None:
            raise AuxNativeError("asr engine is closed")
        err = ctypes.c_char_p()
        with self._lock:
            token = self._lib.lib.cv_asr_forward_next(self._handle,
                                                      ctypes.byref(err))
        if token < 0:
            raise AuxNativeError(self._lib.error(err))
        return int(token)

    @property
    def im_end(self) -> int:
        return self._im_end
