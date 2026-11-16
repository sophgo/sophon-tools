"""Qwen3-VL/WeMM encoders; stdlib + tokenizers, with bmrt/vision in C++.

This module is also distributed with the standalone sophon-demo sample. It
contains no service imports. Each family preserves its pinned prompt,
pooling-token postprocessor and image-size contract.
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
import unicodedata

DEFAULT_INSTRUCTION = "Represent the user's input."
VISION_START, IMAGE_PAD, VISION_END = 151652, 151655, 151653


def instruction_text(instruction: str | None) -> str:
    text = (instruction or "").strip()
    if text and not unicodedata.category(text[-1]).startswith("P"):
        text += "."
    return text or DEFAULT_INSTRUCTION


def render_prompt(text: str, image_tokens: int = 0, instruction: str | None = None,
                  family: str = "qwen3_vl_embedding") -> str:
    image = ("<|vision_start|>" + "<|image_pad|>" * image_tokens + "<|vision_end|>"
             if image_tokens else "")
    if family == "wemm_embedding":
        system = ("<|im_start|>system\n" + instruction.strip() + "<|im_end|>\n"
                  if instruction and instruction.strip() else "")
        # The pinned tokenizer removes trailing newlines at special-token
        # boundaries and appends <embedding>; do not append it a second time.
        return system + "<|im_start|>user\n" + (image + text).strip() + "<|im_end|>\n"
    return ("<|im_start|>system\n" + instruction_text(instruction) + "<|im_end|>\n"
            "<|im_start|>user\n" + image + text + "<|im_end|>\n"
            "<|im_start|>assistant\n")


@dataclass
class PreparedInput:
    ids: list[int]
    image: int | None
    offset: int
    preprocess_ms: float
    _lib: object

    def close(self):
        if self.image:
            self._lib.cv_vle_image_destroy(self.image)
            self.image = None


class VLEmbedder:
    def __init__(self, model: str, config: str, library: str, device: int = 0):
        from tokenizers import Tokenizer

        root = Path(config)
        manifest = json.loads((root / "embedding_config.json").read_text())
        self.family = manifest.get("model_type")
        if self.family not in ("qwen3_vl_embedding", "wemm_embedding"):
            raise ValueError("config must contain a supported multimodal embedding_config.json")
        self.is_wemm = self.family == "wemm_embedding"
        self.vision_tokens = (248053, 248056, 248054) if self.is_wemm else (VISION_START, IMAGE_PAD, VISION_END)
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        # The service refuses over-length prompts; never let saved tokenizer
        # settings silently pad or truncate before we can count their tokens.
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        if self.tokenizer.encode("test", add_special_tokens=True).ids[-1] != (248077 if self.is_wemm else 151643):
            raise ValueError("embedding tokenizer must append the checkpoint's pooling token")
        self._lock = threading.RLock()
        self._handle = None
        self.lib = c = C.CDLL(library)
        ptr, integer, error = C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_char_p)
        c.cv_vle_create.argtypes = [C.c_char_p, C.c_int, error]
        c.cv_vle_create.restype = ptr
        c.cv_vle_destroy.argtypes = [ptr]
        c.cv_vle_destroy.restype = None
        c.cv_vle_fault.argtypes = [ptr]
        c.cv_vle_fault.restype = C.c_int
        c.cv_vle_info.argtypes = [ptr, integer, integer, integer]
        c.cv_vle_info.restype = C.c_int
        c.cv_vle_family.argtypes = [ptr]
        c.cv_vle_family.restype = C.c_int
        c.cv_vle_image_create.argtypes = [C.c_char_p, C.c_int, C.c_int, integer, integer, error]
        c.cv_vle_image_create.restype = ptr
        c.cv_vle_image_create_ex.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_int, integer, integer, error]
        c.cv_vle_image_create_ex.restype = ptr
        c.cv_vle_image_destroy.argtypes = [ptr]
        c.cv_vle_image_destroy.restype = None
        c.cv_vle_forward.argtypes = [ptr, integer, C.c_int, ptr, C.c_int, C.c_int,
                                    C.POINTER(C.c_float), C.POINTER(C.c_double), error]
        c.cv_vle_forward.restype = C.c_int
        err = C.c_char_p()
        self._handle = c.cv_vle_create(str(model).encode(), device, C.byref(err))
        if not self._handle:
            raise RuntimeError(self._error(err))
        try:
            seq, hidden, patches = C.c_int(), C.c_int(), C.c_int()
            if c.cv_vle_info(self._handle, C.byref(seq), C.byref(hidden), C.byref(patches)):
                raise RuntimeError("cannot read encoder metadata")
            self.seq_len, self.hidden, self.max_patches = seq.value, hidden.value, patches.value
            if c.cv_vle_family(self._handle) != int(self.is_wemm):
                raise ValueError("bmodel and embedding_config.json model families do not match")
            if manifest.get("seq_length") != self.seq_len or manifest.get("hidden_size") != self.hidden:
                raise ValueError("bmodel and embedding_config.json dimensions do not match")
            if manifest.get("max_pixels") != self.max_patches * 256:
                raise ValueError("bmodel and embedding_config.json image budgets do not match")
            self.min_pixels = 65536 if self.is_wemm else 4096
            if manifest.get("min_pixels", self.min_pixels) != self.min_pixels:
                raise ValueError("embedding_config.json min_pixels differs from the checkpoint")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _error(err):
        return err.value.decode("utf-8", "replace") if err.value else "encoder failed"

    @property
    def fault(self):
        # The native flag is atomic; health probes remain responsive during a
        # long forward. Worker shutdown drains inference before close.
        return bool(self.lib.cv_vle_fault(self._handle))

    def input_tokens(self, text: str, instruction: str | None = None) -> int:
        """Untruncated count, including the model's system/user template."""
        return len(self.tokenizer.encode(render_prompt(text, instruction=instruction, family=self.family),
                                         add_special_tokens=True).ids)

    def prepare(self, text: str = "", image: bytes | None = None,
                instruction: str | None = None) -> PreparedInput:
        start = time.perf_counter()
        if not isinstance(text, str) or (not text and not image):
            raise ValueError("each embedding input needs text or an image")
        if instruction is not None and not isinstance(instruction, str):
            raise ValueError("instruction must be a string")
        handle = None
        try:
            image_tokens = 0
            if image is not None:
                err, h, w = C.c_char_p(), C.c_int(), C.c_int()
                handle = self.lib.cv_vle_image_create_ex(image, len(image), self.max_patches, self.min_pixels,
                                                     int(self.is_wemm),
                                                     C.byref(h), C.byref(w), C.byref(err))
                if not handle:
                    raise ValueError(self._error(err))
                image_tokens = h.value // 2 * (w.value // 2)
            ids = self.tokenizer.encode(render_prompt(text, image_tokens, instruction, self.family),
                                        add_special_tokens=True).ids
            if len(ids) > self.seq_len:
                raise ValueError(f"输入编码后为 {len(ids)} 个 token，超过该模型上限 {self.seq_len}")
            offset = 0
            if image_tokens:
                vision_start, image_pad, vision_end = self.vision_tokens
                if ids.count(vision_start) != 1:
                    raise ValueError("text/instruction cannot contain reserved vision markers")
                offset = ids.index(vision_start) + 1
                if ids[offset:offset + image_tokens] != [image_pad] * image_tokens or \
                        ids[offset + image_tokens] != vision_end:
                    raise ValueError("tokenizer does not match the model's image token contract")
            return PreparedInput(ids, handle, offset, (time.perf_counter() - start) * 1000, self.lib)
        except BaseException:
            if handle:
                self.lib.cv_vle_image_destroy(handle)
            raise

    def forward(self, prepared: PreparedInput, dimensions: int | None = None):
        dim = self.hidden if dimensions is None else dimensions
        if isinstance(dim, bool) or not isinstance(dim, int) or not 64 <= dim <= self.hidden:
            raise ValueError(f"dimensions must be between 64 and {self.hidden}")
        with self._lock:
            if not self._handle:
                raise RuntimeError("encoder is closed")
            ids = (C.c_int * len(prepared.ids))(*prepared.ids)
            out, timings, err = (C.c_float * dim)(), (C.c_double * 3)(), C.c_char_p()
            if self.lib.cv_vle_forward(self._handle, ids, len(ids), prepared.image,
                                       prepared.offset, dim, out, timings, C.byref(err)):
                raise RuntimeError(self._error(err))
            return list(out), {
                "preprocess_ms": prepared.preprocess_ms, "embedding_ms": timings[0],
                "vision_ms": timings[1], "encoder_ms": timings[2],
            }

    def encode(self, text: str = "", image: bytes | None = None,
               instruction: str | None = None, dimensions: int | None = None):
        prepared = self.prepare(text, image, instruction)
        try:
            vector, timings = self.forward(prepared, dimensions)
            return vector, len(prepared.ids), timings
        finally:
            prepared.close()

    def close(self):
        with self._lock:
            if self._handle:
                self.lib.cv_vle_destroy(self._handle)
                self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
