"""Native backend: drives the pure bmrt engine (native/) through its C ABI.

The engine only runs graphs. Everything the vendor demo does on the host --
tokenising, image resizing and patching, vit position tables, M-RoPE position
ids -- happens here, ported from sophon-demo sample/Qwen3_5/python/qwen3_5.py
so the NPU sees exactly the inputs the demo feeds it.

Threading: the engine serialises launches internally (one NPU), so every call
here is blocking; the async methods run it in a thread so the scheduler can
interleave sessions between steps.
"""

from __future__ import annotations

import asyncio
import ctypes
import io
import os
import threading
from typing import Sequence

from .base import EngineBackend, Session, Token
from .kv_pool import UNBOUNDED

_P = ctypes.POINTER
_c_int_p = _P(ctypes.c_int)
_c_float_p = _P(ctypes.c_float)


def _buffer_ptrs(items, ptr_type):
    """Addresses of ctypes arrays, as an array of the engine's ``const T*``.

    The vit inputs are ctypes arrays all the way from where they are allocated
    (_VisionProc's pixel buffer, _expand_image_pads' position tables), so the
    engine is handed their buffers directly: no copy, no numpy in between.
    """
    return (ptr_type * max(len(items), 1))(
        *[ctypes.cast(a, ptr_type) for a in items])


# Demo constants (qwen3_5.py __init__ / image_message).
_SPATIAL_MERGE = 2
_GRID_PER_SIDE = 48
_IMAGE_PATCH = 16
_MIN_PIXELS = 4 * 32 * 32
# A snapshot holds the whole linear-attention state (~32 MB on the 35B) no
# matter how short the prefix. Below this many tokens a hit saves under half a
# second of replay, so such prefixes are not cached. (It was 256, which meant a
# normal short chat in the console never produced a single hit.)
_MIN_SNAPSHOT_TOKENS = 16


class Prompt(list):
    """Token ids plus what the engine needs besides them for a VLM prompt.

    A list subclass so it flows through the scheduler like any token list;
    ``pos3`` is the [3, n] M-RoPE matrix and ``images`` the per-image vit
    inputs. Both are None/empty for plain text.
    """

    def __init__(self, tokens, pos3=None, images=None) -> None:
        super().__init__(tokens)
        self.pos3 = pos3
        self.images = images or []

    def segment(self, a: int, b: int) -> "Prompt":
        """Tokens [a, b) with their positions and the images inside them.

        Positions stay absolute (an extended session continues from them);
        image offsets become relative to ``a``. An image may not straddle the
        boundary -- the caller chooses boundaries outside image blocks.
        """
        imgs = []
        for im in self.images:
            lo, hi = im["offset"], im["offset"] + im["patches"] // 4
            if hi <= a or lo >= b:
                continue
            if lo < a or hi > b:
                raise ValueError("prompt segment would split an image")
            imgs.append(dict(im, offset=lo - a))
        pos = None
        if self.pos3 is not None:
            # pos3 is flat [3, n] row-major: slice the same columns of each row.
            pos = [self.pos3[r * len(self) + i] for r in range(3) for i in range(a, b)]
        elif a > 0:
            # Plain text: all three M-RoPE rows are the absolute position.
            row = list(range(a, b))
            pos = row * 3
        return Prompt(list.__getitem__(self, slice(a, b)), pos3=pos, images=imgs)


class _Lib:
    """Thin ctypes wrapper. Kept dumb: no policy lives here."""

    def __init__(self, path: str) -> None:
        self.lib = ctypes.CDLL(path)
        c = self.lib
        err = _P(ctypes.c_char_p)
        c.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.llm_engine_load.restype = ctypes.c_void_p
        c.llm_engine_free.argtypes = [ctypes.c_void_p]
        for name in ("num_layers", "context_length", "max_input_length",
                     "hidden_size", "has_vision", "vit_max_patches", "vit_dims",
                     "supports_history", "fault"):
            fn = getattr(c, f"llm_engine_{name}")
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_int
        c.llm_session_new.argtypes = [ctypes.c_void_p, err]
        c.llm_session_new.restype = ctypes.c_void_p
        c.llm_session_free.argtypes = [ctypes.c_void_p]
        c.llm_session_token_len.argtypes = [ctypes.c_void_p]
        c.llm_session_token_len.restype = ctypes.c_int
        c.llm_session_prefill.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, _c_int_p, ctypes.c_int, _c_int_p,
            ctypes.c_int, _c_int_p, _c_int_p, _P(_c_float_p), _P(_c_int_p),
            _P(_c_int_p), _P(_c_float_p), err]
        c.llm_session_prefill.restype = ctypes.c_int
        c.llm_session_extend.argtypes = c.llm_session_prefill.argtypes
        c.llm_session_extend.restype = ctypes.c_int
        c.llm_session_snapshot.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
        c.llm_session_snapshot.restype = ctypes.c_void_p
        c.llm_session_restore.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_void_p, err]
        c.llm_session_restore.restype = ctypes.c_int
        c.llm_snapshot_free.argtypes = [ctypes.c_void_p]
        c.llm_snapshot_bytes.argtypes = [ctypes.c_void_p]
        c.llm_snapshot_bytes.restype = ctypes.c_ulonglong
        c.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
        c.llm_session_decode.restype = ctypes.c_int
        # Embedding table size for the engine's token range check. Optional at
        # the ABI level: an older .so simply lacks it, and the engine then runs
        # without the check instead of the worker refusing to load.
        set_vocab = getattr(c, "llm_engine_set_vocab_size", None)
        if set_vocab is not None:
            set_vocab.argtypes = [ctypes.c_void_p, ctypes.c_int]
        c.llm_last_error.restype = ctypes.c_char_p

    def error(self) -> str:
        raw = self.lib.llm_last_error()
        return raw.decode("utf-8", "replace") if raw else "unknown engine error"


class _TokLib:
    """The engine library's tokenizer entry points, through ctypes.

    Tokenising lives in the C++ library (native/src/tokenizer.cpp) so the board
    needs no Python ML stack: the same tokenizer.json, the same ids. The wrapper
    keeps two ctypes arrays alive while a call runs and otherwise stays out of
    the way.
    """

    def __init__(self, lib: _Lib) -> None:
        c = lib.lib
        err = _P(ctypes.c_char_p)
        c.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
        c.llm_tokenizer_load.restype = ctypes.c_void_p
        c.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
        c.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                           _c_int_p, ctypes.c_int, err]
        c.llm_tokenizer_encode.restype = ctypes.c_int
        c.llm_tokenizer_decode.argtypes = [ctypes.c_void_p, _c_int_p, ctypes.c_int,
                                           ctypes.c_char_p, ctypes.c_int,
                                           ctypes.c_int, err]
        c.llm_tokenizer_decode.restype = ctypes.c_int
        c.llm_tokenizer_token_to_id.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        c.llm_tokenizer_token_to_id.restype = ctypes.c_int
        c.llm_tokenizer_vocab_size.argtypes = [ctypes.c_void_p]
        c.llm_tokenizer_vocab_size.restype = ctypes.c_int
        self._lib = lib
        self._handle = None

    def load(self, tokenizer_path: str) -> None:
        err = ctypes.c_char_p()
        handle = self._lib.lib.llm_tokenizer_load(tokenizer_path.encode(), ctypes.byref(err))
        if not handle:
            raise RuntimeError(self._lib.error() if not err.value
                               else err.value.decode("utf-8", "replace"))
        self._handle = handle

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            self._lib.lib.llm_tokenizer_free(handle)

    def encode(self, text: str) -> list[int]:
        """Ids for `text` (no BOS/EOS; literal specials become their own id)."""
        raw = text.encode("utf-8")
        # The count comes back first, so one call sizes and fills the buffer.
        n = self._lib.lib.llm_tokenizer_encode(self._handle, raw, None, 0, None)
        if n < 0:
            raise RuntimeError(self._lib.error())
        if n == 0:
            return []
        buf = (ctypes.c_int * n)()
        got = self._lib.lib.llm_tokenizer_encode(self._handle, raw, buf, n, None)
        if got < 0:
            raise RuntimeError(self._lib.error())
        return list(buf[:got])

    def decode_bytes(self, tokens: Sequence[int], skip_special: bool = True) -> bytes:
        """Raw decoded bytes for `tokens`, before UTF-8 validation.

        A byte-level token may hold a fragment of a character -- ``门簪`` comes
        back as three ids whose bytes only make sense concatenated -- so the
        caller has to be able to join fragments before deciding what is
        undecodable. Decoding to ``str`` here would commit the fragment to
        U+FFFD, which no later call can undo.
        """
        ids = (ctypes.c_int * max(len(tokens), 1))(*tokens)
        n = len(tokens)
        need = self._lib.lib.llm_tokenizer_decode(self._handle, ids, n, None, 0,
                                                  1 if skip_special else 0, None)
        if need < 0:
            raise RuntimeError(self._lib.error())
        if need == 0:
            return b""
        buf = ctypes.create_string_buffer(need + 1)
        got = self._lib.lib.llm_tokenizer_decode(self._handle, ids, n, buf, need + 1,
                                                  1 if skip_special else 0, None)
        if got < 0:
            raise RuntimeError(self._lib.error())
        return buf.raw[:got]

    def decode(self, tokens: Sequence[int], skip_special: bool = True) -> str:
        return self.decode_bytes(tokens, skip_special).decode("utf-8", "replace")

    def token_to_id(self, token: str) -> int | None:
        tid = self._lib.lib.llm_tokenizer_token_to_id(self._handle, token.encode())
        return None if tid < 0 else tid

    def vocab_size(self) -> int:
        return self._lib.lib.llm_tokenizer_vocab_size(self._handle)


class _VisionProc:
    """Image preprocessing in the engine library, through ctypes.

    Decode -> smart_resize -> Pillow-compatible bicubic resize -> normalise ->
    patchify, all in native/src/vision.cpp. The board needs no torch,
    transformers, pillow or qwen_vl_utils; the numbers are pinned to the
    reference stack's output by tests/vision_golden.json.
    """

    def __init__(self, lib: "_Lib", max_patches: int) -> None:
        c = lib.lib
        err = _P(ctypes.c_char_p)
        c.llm_image_preprocess.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong,
            _c_int_p, _P(ctypes.c_float), err]
        c.llm_image_preprocess.restype = ctypes.c_int
        c.llm_vision_pos_tables.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            _c_int_p, _c_int_p, _P(ctypes.c_float)]
        c.llm_vision_rope.argtypes = [
            _c_int_p, ctypes.c_int, _c_int_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, _c_int_p, err]
        c.llm_vision_rope.restype = ctypes.c_int
        self._lib = lib
        self._max_patches = max_patches

    def __call__(self, blob: bytes):
        """Returns ({t,h,w}, a ctypes float array of the vit input rows)."""
        max_pixels = self._max_patches * _IMAGE_PATCH * _IMAGE_PATCH
        info = (ctypes.c_int * 5)()
        # First call sizes the buffer, second fills it.
        n = self._lib.lib.llm_image_preprocess(
            blob, len(blob), self._max_patches, _IMAGE_PATCH, _SPATIAL_MERGE, 2,
            _MIN_PIXELS, max_pixels, info, None, None)
        if n < 0:
            raise ValueError(self._lib.error())
        buf = (ctypes.c_float * max(n, 1))()
        got = self._lib.lib.llm_image_preprocess(
            blob, len(blob), self._max_patches, _IMAGE_PATCH, _SPATIAL_MERGE, 2,
            _MIN_PIXELS, max_pixels, info, buf, None)
        if got < 0:
            raise ValueError(self._lib.error())
        return (info[0], info[1], info[2]), buf


class _Snapshot:
    """Engine snapshot (NPU memory) for the prefix cache; frees itself."""

    __slots__ = ("_lib", "ptr", "token_len", "nbytes")

    def __init__(self, lib: _Lib, ptr: int, token_len: int) -> None:
        self._lib = lib
        self.ptr = ptr
        self.token_len = token_len
        self.nbytes = int(lib.lib.llm_snapshot_bytes(ptr))

    def release(self) -> None:
        ptr, self.ptr = self.ptr, None
        if ptr:
            self._lib.lib.llm_snapshot_free(ptr)

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class _SnapshotStore:
    """What PrefixCache expects of a store: a byte budget and release().

    ``budget`` is what ``PrefixCache`` adopts as its own ceiling when it is built
    without one. The worker passes the model's runtime budget there instead
    (MYS-2785), so the value here is only the fallback for a backend built by
    hand; the engine allocates the snapshot and ``_Snapshot.nbytes`` is what the
    cache actually charges, so nothing is enforced twice.
    """

    kind = "device"

    def __init__(self, budget: int = UNBOUNDED) -> None:
        self.budget = budget

    def release(self, snap) -> None:
        snap.release()


_OOM_MARK = "NPU heap exhausted"
# The engine runs dynamic prefill graphs on multiples of this many rows only
# (llm_engine.cpp kAlign); cuts on it add no decode-replayed tail.
_PREFILL_ALIGN = 64


class NativeSession(Session):
    def __init__(self, backend: "NativeBackend", handle: int) -> None:
        self._backend = backend
        self._lib = backend._lib
        self._handle = handle

    async def _call(self, fn, *args, keep: object = None):
        """Run an engine call; when it ran out of NPU memory, let the owner
        free some (the prefix cache gives way to live sessions) and retry.

        Safe to retry: the engine fails an allocation before it touches any
        session state. The relief hook runs here, on the event loop, so it
        never races the scheduler over the cache.
        """
        while True:
            try:
                return await asyncio.to_thread(fn, *args)
            except RuntimeError as exc:
                relief = self._backend.oom_relief
                if _OOM_MARK in str(exc) and relief is not None and relief(keep):
                    continue
                raise

    @property
    def token_len(self) -> int:
        if not self._handle:
            return 0
        return int(self._lib.lib.llm_session_token_len(self._handle))

    def set_exact_tail(self, rows: int) -> None:
        """The next feed_prompt runs its last `rows` tokens through the decode
        graphs, whose routed-expert MoE is exact on CV84X6."""
        fn = getattr(self._lib.lib, "llm_session_set_exact_tail", None)
        if fn is not None and self._handle:
            fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
            fn(self._handle, int(rows))

    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        await self._call(self._prefill, tokens)

    def _prefill(self, tokens: Sequence[Token]) -> None:
        n = len(tokens)
        ids = (ctypes.c_int * max(n, 1))(*tokens)
        pos3 = getattr(tokens, "pos3", None)
        images = getattr(tokens, "images", None) or []
        pos_arr = None
        if pos3 is not None:
            # pos3 is a flat [3, n] row-major int32 buffer; the engine takes it
            # that way, so no reshape or copy is needed.
            pos_arr = (ctypes.c_int * (3 * n))(*pos3)
        k = len(images)
        offsets = (ctypes.c_int * max(k, 1))(*[im["offset"] for im in images])
        patches = (ctypes.c_int * max(k, 1))(*[im["patches"] for im in images])
        px = _buffer_ptrs([im["pixels"] for im in images], _c_float_p)
        pid = _buffer_ptrs([im["pos_ids"] for im in images], _c_int_p)
        pidx = _buffer_ptrs([im["pos_idx"] for im in images], _c_int_p)
        pw = _buffer_ptrs([im["pos_weight"] for im in images], _c_float_p)
        err = ctypes.c_char_p()
        # A session that already holds tokens (restored from the prefix cache,
        # or fed in segments) is extended; otherwise this is a fresh prefill.
        fn = (self._lib.lib.llm_session_extend if self.token_len > 0
              else self._lib.lib.llm_session_prefill)
        rc = fn(
            self._backend._handle, self._handle, ids, n,
            pos_arr if pos_arr is not None else None,
            k, offsets, patches, px, pid, pidx, pw, ctypes.byref(err))
        if rc != 0:
            raise RuntimeError(self._lib.error())

    def _decode(self) -> int:
        err = ctypes.c_char_p()
        tid = self._lib.lib.llm_session_decode(self._backend._handle, self._handle,
                                               ctypes.byref(err))
        if tid < 0:
            raise RuntimeError(self._lib.error())
        return int(tid)

    async def step(self) -> Token:
        return await self._call(self._decode)

    def decode(self, tokens: Sequence[Token]) -> str:
        return self._backend.tokenizer_decode(list(tokens))

    def decode_bytes(self, tokens: Sequence[Token]) -> bytes:
        # Byte-level BPE: a character can span tokens, so the scheduler joins
        # the raw bytes instead of trusting a per-token str (MYS-2496).
        return self._backend.tokenizer_decode_bytes(list(tokens))

    def is_stop_token(self, token: Token) -> bool:
        return token in self._backend._stop_ids

    async def snapshot(self, token_len: int) -> object:
        # Linear-attention state cannot be rolled back, so a snapshot exists
        # only for the session's current length; the scheduler takes it right
        # after feeding up to the boundary.
        if token_len != self.token_len:
            raise ValueError(f"snapshot at {token_len} but session holds {self.token_len}")
        err = ctypes.c_char_p()
        ptr = await asyncio.to_thread(self._lib.lib.llm_session_snapshot,
                                      self._backend._handle, self._handle,
                                      ctypes.byref(err))
        if not ptr:
            raise RuntimeError(self._lib.error())
        return _Snapshot(self._lib, ptr, token_len)

    def _restore(self, snap: "_Snapshot") -> None:
        err = ctypes.c_char_p()
        rc = self._lib.lib.llm_session_restore(self._backend._handle, self._handle,
                                               snap.ptr, ctypes.byref(err))
        if rc != 0:
            raise RuntimeError(self._lib.error())

    async def restore(self, snap: object) -> None:
        if not isinstance(snap, _Snapshot) or not snap.ptr:
            raise TypeError("not a live native snapshot")
        await self._call(self._restore, snap, keep=snap)

    async def close(self) -> None:
        if self._handle:
            h, self._handle = self._handle, None
            await asyncio.to_thread(self._lib.lib.llm_session_free, h)


class NativeBackend(EngineBackend):
    """One bmodel loaded onto the NPU, plus its tokenizer and image processor."""

    def __init__(self, model_path: str, tokenizer_path: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0,
                 snapshot_budget: int = UNBOUNDED) -> None:
        self._model_id = model_id
        self._model_path = model_path
        self._lib = _Lib(lib_path or os.environ.get("CV84X6_LLM_LIB") or os.path.join(
            os.path.dirname(__file__), "..", "..", "lib", "libcv84x6_llm.so"))
        err = ctypes.c_char_p()
        self._handle = self._lib.lib.llm_engine_load(
            model_path.encode(), dev_id, ctypes.byref(err))
        if not self._handle:
            raise RuntimeError(self._lib.error())
        lib = self._lib.lib
        self._ctx = int(lib.llm_engine_context_length(self._handle))
        self._max_input = int(lib.llm_engine_max_input_length(self._handle))
        self._vision = bool(lib.llm_engine_has_vision(self._handle))
        self._max_patches = int(lib.llm_engine_vit_max_patches(self._handle))
        self._vit_dims = int(lib.llm_engine_vit_dims(self._handle))
        self._history = bool(lib.llm_engine_supports_history(self._handle))
        lib.llm_engine_session_state_bytes.argtypes = [ctypes.c_void_p]
        lib.llm_engine_session_state_bytes.restype = ctypes.c_ulonglong
        # NPU bytes a parked session costs at full context. Parked FA KV grows
        # with the session, so the scheduler budgets per request instead:
        # linear state + kv_bytes_per_token * (prompt + max_tokens).
        self.session_state_bytes = int(lib.llm_engine_session_state_bytes(self._handle))
        try:
            for name in ("kv_bytes_per_token", "linear_state_bytes"):
                fn = getattr(lib, f"llm_engine_{name}")
                fn.argtypes = [ctypes.c_void_p]
                fn.restype = ctypes.c_ulonglong
            self.kv_bytes_per_token = int(lib.llm_engine_kv_bytes_per_token(self._handle))
            self.linear_state_bytes = int(lib.llm_engine_linear_state_bytes(self._handle))
        except AttributeError:  # an engine library from before v0.5
            self.kv_bytes_per_token = 0
            self.linear_state_bytes = 0
        # FA slots a *parked* session's buffer is rounded up to (MYS-2785).
        # ``ensure_park`` allocates ``round_up(tokens, kParkGranule)`` slots, so a
        # scheduler that budgets the raw token count under-reserves by up to one
        # granule -- on the 9B (32 KiB/token) that is 128 MiB per session, and a
        # two-session run was measured 37 MiB over the model's limit because of
        # it. 4096 is ``kParkGranule`` in ``native/src/llm_engine.cpp``; it is a
        # fallback for a library built before ``llm_engine_park_granule`` existed,
        # and the C getter wins when it is there, so the two cannot drift.
        try:
            fn = getattr(lib, "llm_engine_park_granule")
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_int
            self.park_granule = int(fn(self._handle))
        except AttributeError:  # an engine library from before this change
            self.park_granule = 4096
        # Set by the scheduler: frees NPU memory (prefix-cache entries, never
        # the snapshot passed in) when an engine call ran out of it; returns
        # False when nothing is left to free.
        self.oom_relief = None
        # Prefix-cache snapshots live in NPU memory; only history bmodels can
        # resume from one (block_kv_<i>), so plain ones get no store.
        self.snapshot_store = _SnapshotStore(snapshot_budget) if self._history else None

        # The tokenizer is part of the engine library: no Python ML stack.
        self._tok = _TokLib(self._lib)
        self._tok.load(tokenizer_path)
        # Tell the engine how big the embedding table is, so it can reject an
        # out-of-range token id instead of gathering out of bounds on the NPU
        # (which reads garbage or wedges the board). The bmodel does not carry
        # the vocabulary -- lm_head fuses argmax -- so it has to come from the
        # tokenizer. Both are optional: an older .so lacks the setter, and the
        # engine then runs without the check rather than refusing to load.
        set_vocab = getattr(self._lib.lib, "llm_engine_set_vocab_size", None)
        if set_vocab is not None and hasattr(self._tok, "vocab_size"):
            set_vocab(self._handle, self._tok.vocab_size())
        self._config_dir = os.path.dirname(tokenizer_path)
        # Image preprocessing lives in the engine library too; nothing to warm.
        self._vision_proc = _VisionProc(self._lib, self._max_patches) if self._vision else None

        def tid(name: str) -> int | None:
            return self._tok.token_to_id(name)

        self._vision_start_id = tid("<|vision_start|>")
        self._image_pad_id = tid("<|image_pad|>")
        self._stop_ids = {i for i in (tid("<|im_end|>"), tid("<|endoftext|>"))
                          if i is not None}

    # -- tokenizer helpers -------------------------------------------------
    def tokenizer_decode(self, tokens: Sequence[int]) -> str:
        return self._tok.decode(list(tokens), skip_special=True)

    def tokenizer_decode_bytes(self, tokens: Sequence[int]) -> bytes:
        return self._tok.decode_bytes(list(tokens), skip_special=True)

    def tokenizer_encode(self, text: str) -> list[int]:
        return self._tok.encode(text)

    # -- EngineBackend -----------------------------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self._ctx

    @property
    def fault(self) -> bool:
        """The TPU hung (launch/sync failed); only a reboot recovers it."""
        return bool(self._handle) and bool(self._lib.lib.llm_engine_fault(self._handle))

    @property
    def max_prompt_length(self) -> int:
        if self._history:
            return self._ctx - 1  # chunked through block_kv
        return min(self._max_input, self._ctx - 1)

    @property
    def prefill_chunk(self) -> int:
        """Tokens per scheduler prefill step: the graphs' own chunk width."""
        return self._max_input

    @property
    def supports_vision(self) -> bool:
        return self._vision

    @property
    def kv_snapshots_verified(self) -> bool:
        # Snapshot -> restore -> extend is the demo's prefix-cache recipe
        # (qwen3_5_prefix_cache.py) and needs the block_kv graphs; verified on
        # the board by tools/engine_check.py --cache-check.
        return self._history

    @property
    def supports_sampling(self) -> bool:
        # lm_head emits [1,1] int32: argmax is fused into the graph, so there
        # are no logits to sample from and temperature/top_p cannot apply.
        return False

    @property
    def supports_chunked_prefill(self) -> bool:
        return self._history

    def snapshot_points(self, tokens: Sequence[Token]) -> list[int]:
        """Where to snapshot while prefilling, so later prompts can resume.

        Two boundaries, each rounded down to a multiple of 64 (the engine's
        prefill alignment, so a cut adds no replayed tail of its own). A
        boundary below 64 tokens -- a short chat -- is kept exact instead,
        as long as cutting there leaves the rest of the prompt as many 64-row
        prefill blocks as before: rows outside those blocks are replayed one
        by one either way, so such a cut costs the first request nothing:
          * the end of the leading system message -- shared by every
            conversation of an agent;
          * the start of the final ``<|im_start|>assistant`` generation turn --
            the next turn of this conversation starts with everything before
            it, while the generation prompt itself (empty think block) is
            rendered differently once the turn is history.
        A boundary inside an image block is moved before the image.
        """
        if not self._history:
            return []
        toks = list(tokens)
        im_start = self._tok.token_to_id("<|im_start|>")
        im_end = self._tok.token_to_id("<|im_end|>")
        points = set()
        if len(toks) > 2 and toks[0] == im_start:
            try:
                points.add(toks.index(im_end) + 2)  # past "<|im_end|>\n"
            except ValueError:
                pass
        starts = [i for i, t in enumerate(toks) if t == im_start]
        if len(starts) > 1:
            points.add(starts[-1])
        # Image blocks as [first_pad, last_pad]; a cut strictly inside one would
        # split the vit rows across two prefill calls.
        spans, i = [], 0
        while i < len(toks):
            if toks[i] == self._image_pad_id:
                j = i
                while j + 1 < len(toks) and toks[j + 1] == self._image_pad_id:
                    j += 1
                spans.append((i, j))
                i = j + 1
            else:
                i += 1
        n = len(toks)

        def cut(p: int) -> int:
            aligned = (p // _PREFILL_ALIGN) * _PREFILL_ALIGN
            if aligned >= _PREFILL_ALIGN:
                return aligned
            if n // _PREFILL_ALIGN == (n - p) // _PREFILL_ALIGN:
                return p
            return 0

        out = []
        for p in sorted(points):
            p = cut(p)
            moved = True
            while moved:
                moved = False
                for lo, hi in spans:
                    if lo < p <= hi:
                        p = cut(lo)
                        moved = True
            if _MIN_SNAPSHOT_TOKENS <= p < n:
                out.append(p)
        return sorted(set(out))

    async def encode(self, text: str,
                     images: Sequence[bytes] | None = None) -> list[Token]:
        if not images:
            return Prompt(self.tokenizer_encode(text))
        if not self.supports_vision:
            raise ValueError("this model has no vit graph; it cannot take images")
        return await asyncio.to_thread(self._encode_with_images, text, list(images))

    # -- vision ------------------------------------------------------------
    def _expand_image_pads(self, text: str, blobs: list[bytes]):
        """Turn each single ``<|image_pad|>`` into the image's real pad run.

        The template (and so ``openai_api.build_prompt``) writes one
        ``<|vision_start|><|image_pad|><|vision_end|>`` per image; the model
        needs ``patches / spatial_merge^2`` pad tokens, which only preprocessing
        can know. Returns (token ids, per-image vit inputs, image grids).
        """
        ids = self.tokenizer_encode(text)
        starts = [i for i, t in enumerate(ids) if t == self._vision_start_id]
        if len(starts) != len(blobs):
            raise ValueError("prompt has %d vision markers for %d images"
                             % (len(starts), len(blobs)))

        out: list[int] = []
        vit = []
        grids = []
        cursor = 0
        for start, blob in zip(starts, blobs):
            grid, pixels = self._vision_proc(blob)
            t, gh, gw = grid
            patches = t * gh * gw
            pads = patches // (_SPATIAL_MERGE * _SPATIAL_MERGE)

            # Text up to and including <|vision_start|>.
            out.extend(ids[cursor:start + 1])
            vit.append({
                "offset": len(out),          # first pad row
                "patches": patches,
                "pixels": pixels,
                "pos_ids": (ctypes.c_int * (patches * 2))(),
                "pos_idx": (ctypes.c_int * (patches * 4))(),
                "pos_weight": (ctypes.c_float * (patches * 4))(),
            })
            self._lib.lib.llm_vision_pos_tables(
                t, gh, gw, _GRID_PER_SIDE,
                vit[-1]["pos_ids"], vit[-1]["pos_idx"], vit[-1]["pos_weight"])
            out.extend([self._image_pad_id] * pads)
            grids.append(grid)
            # Skip the placeholder pad and <|vision_end|>; the template's own
            # <|vision_end|> is re-emitted below so its position stays put.
            cursor = start + 2

        out.extend(ids[cursor:])
        return out, vit, grids

    def _encode_with_images(self, text: str, blobs: list[bytes]) -> Prompt:
        """Prompt tokens, M-RoPE positions and per-image vit inputs.

        All of the image work (decode, smart_resize, bicubic resize, normalise,
        patchify, position tables) happens in the engine library -- see
        native/src/vision.cpp -- so no Python ML stack is needed on the board.
        Those stages are pure host software and are pinned to the reference
        values by tests/vision_golden.json.
        """
        if text.count("<|image_pad|>") != len(blobs):
            raise ValueError("prompt has %d image placeholders for %d images"
                             % (text.count("<|image_pad|>"), len(blobs)))

        tokens, vit, grids = self._expand_image_pads(text, blobs)
        if len(tokens) > self.max_prompt_length:
            raise ValueError(f"prompt is {len(tokens)} tokens with images, "
                             f"limit is {self.max_prompt_length}")

        flat = [v for g in grids for v in g]
        garr = (ctypes.c_int * max(len(flat), 1))(*flat)
        tok_arr = (ctypes.c_int * max(len(tokens), 1))(*tokens)
        pos3 = (ctypes.c_int * (3 * max(len(tokens), 1)))()
        err = ctypes.c_char_p()
        rc = self._lib.lib.llm_vision_rope(
            tok_arr, len(tokens), garr, len(grids),
            self._vision_start_id, self._image_pad_id, _SPATIAL_MERGE,
            pos3, ctypes.byref(err))
        if rc != 0:
            raise RuntimeError(self._lib.error())
        return Prompt(tokens, pos3=list(pos3)[:3 * len(tokens)], images=vit)

    async def new_session(self) -> Session:
        err = ctypes.c_char_p()
        h = await asyncio.to_thread(self._lib.lib.llm_session_new, self._handle,
                                    ctypes.byref(err))
        if not h:
            raise RuntimeError(self._lib.error())
        return NativeSession(self, h)

    async def close(self) -> None:
        if self._handle:
            self._lib.lib.llm_engine_free(self._handle)
            self._handle = None
