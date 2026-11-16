"""Bounded, cancellation-safe service backend for multimodal embeddings."""
from __future__ import annotations

import base64
import binascii

from .aux_backend import (AUX_TEXT_MAX_QUEUE, AuxRequestError, _Serialised,
                          _default_lib_path, _run_whole)
from .vl_embed_native import VLEmbedder

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_BATCH_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_INPUTS = 16


def validate_items(items) -> list[dict]:
    """Validate the RPC/HTTP extension before any work is sent to the NPU.

    External URLs and local paths are deliberately not inputs to an offline
    inference API; the caller sends image bytes as a JPEG/PNG data URL.
    """
    if not isinstance(items, list) or not items or len(items) > 64:
        raise ValueError("input 必须包含 1–64 条输入")
    result, total, images = [], 0, 0
    for value in items:
        item = {"text": value} if isinstance(value, str) else value
        if not isinstance(item, dict) or set(item) - {"text", "image"}:
            raise ValueError("多模态 input 仅接受 text 和 image 字段")
        text, image = item.get("text", ""), item.get("image")
        if not isinstance(text, str) or (not text and not image):
            raise ValueError("每条 input 必须包含非空 text 或 image")
        if image is not None:
            if not isinstance(image, str):
                raise ValueError("image 必须是 JPEG/PNG base64 data URL")
            prefix, sep, payload = image.partition(",")
            if not sep or prefix not in ("data:image/jpeg;base64", "data:image/png;base64"):
                raise ValueError("image 必须是 JPEG/PNG base64 data URL；不读取网络 URL 或本地文件")
            if len(payload) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
                raise ValueError("单张 image 不能超过 4 MiB")
            try:
                raw = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("image 的 base64 无效") from exc
            valid_magic = (raw.startswith(b"\xff\xd8\xff") if "jpeg" in prefix
                           else raw.startswith(b"\x89PNG\r\n\x1a\n"))
            if not raw or not valid_magic or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("image 内容与 JPEG/PNG 类型不匹配，或超过 4 MiB")
            total += len(raw)
            images += 1
            if total > MAX_BATCH_IMAGE_BYTES or images > MAX_IMAGE_INPUTS:
                raise ValueError("每批最多 16 张图片，图片总大小不能超过 16 MiB")
        result.append({"text": text, **({"image": image} if image is not None else {})})
    return result


class VlEmbedBackend:
    kind = "embedding"
    supports_vision = True

    def __init__(self, model_path, config_dir, model_id, lib_path=None, dev_id=0, max_queue=16):
        self._model_id = model_id
        self._engine = VLEmbedder(model_path, config_dir, lib_path or _default_lib_path(), dev_id)
        self._gate = _Serialised(min(max_queue, AUX_TEXT_MAX_QUEUE))
        self.hidden = self._engine.hidden
        self.seq_len = self._engine.seq_len

    @property
    def model_id(self):
        return self._model_id

    @property
    def max_prompt_length(self):
        return self.seq_len

    def input_tokens(self, text, instruction=""):
        return self._engine.input_tokens(text, instruction)

    @property
    def fault(self):
        return self._engine.fault

    async def embed(self, texts, dimensions=None):
        return await self.embed_multimodal([{"text": t} for t in texts], dimensions)

    async def embed_multimodal(self, items, dimensions=None, instruction=None):
        try:
            validated = validate_items(items)
            if dimensions is not None and not 64 <= dimensions <= self.hidden:
                raise ValueError(f"dimensions 必须在 64–{self.hidden} 之间")
            return await _run_whole(self._gate, self._batch, validated, dimensions, instruction)
        except ValueError as exc:
            raise AuxRequestError(str(exc)) from exc

    def _batch(self, items, dimensions, instruction):
        prepared = []
        try:
            # Reject any bad image or over-long prompt before the first launch.
            for item in items:
                image = item.get("image")
                blob = base64.b64decode(image.partition(",")[2], validate=True) if image else None
                prepared.append(self._engine.prepare(item["text"], blob, instruction))
            vectors = [self._engine.forward(p, dimensions)[0] for p in prepared]
            return vectors, [len(p.ids) for p in prepared]
        finally:
            for p in prepared:
                p.close()

    async def close(self):
        self._engine.close()
