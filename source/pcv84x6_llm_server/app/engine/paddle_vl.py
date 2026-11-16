"""PaddleOCR-VL-1.5: a chat-shaped OCR model on the NPU.

The model answers the OpenAI chat shape the rest of the service already speaks
(``POST /v1/chat/completions``), so the official PaddleOCR client can point at
this box with ``vl_rec_backend="vllm-server"`` and get the same OTSL text a vLLM
server would return. What is *not* the same as the 35B chat models is the
machinery behind the interface:

* **One session at a time.** The engine owns a single persistent KV cache (36
  MiB, allocated with the weights), so a second concurrent request has nowhere
  to write. Requests queue in front of it exactly like any other model's -- the
  worker runs one at a time (``serial_only``) and the scheduler's
  ``max_queue`` still applies.
* **Greedy only.** ``lm_head`` fuses the argmax into the graph, so there are no
  logits to sample from; ``supports_sampling`` is False, which is what makes the
  API say so instead of silently ignoring ``temperature``.
* **No loop cut-off.** A table is *supposed* to repeat ``<fcel>value`` hundreds
  of times, so the scheduler's repetition heuristic would truncate legitimate
  OTSL. ``detects_loops`` is False for exactly that reason.
* **Its own prompt format.** PaddleOCR-VL is not a Qwen chat model: the template
  is ``<|begin_of_sentence|>User: <|IMAGE_START|>…<|IMAGE_END|>{prompt}\\n
  Assistant:\\n``, and the assistant turn's newline is load-bearing (A3 measured
  that ``Assistant:\\n`` and ``Assistant: `` are different token spans and only
  one of them is what the reference continues).

Everything host-side here is pinned by tests that need no NPU: the prompt
rendering against the model's own ``chat_template.jinja``, the pixel tensor
against HF's processor, and the tokenizer against the reference (the C++
tokenizer learned this family's normalizer, byte fallback and decoder in
``native/src/tokenizer.cpp``).

The NPU half is ``native/src/vl_engine.cpp``; the arithmetic it must reproduce
is ``tools/ocr/vl_native/vl_native.cpp`` (MYS-2660), including the three fixes
that each produced valid shapes and wrong tokens.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import threading
from dataclasses import dataclass
from typing import Sequence

from .base import EngineBackend, Session, Token
from .native import _Lib, _TokLib, _c_int_p, _P, _c_float_p

#: The vit stage the bmodel was compiled for. 56 x 56 patches of 14 x 14 pixels
#: is 784 x 784, which is the only grid this build accepts -- the patch count
#: alone does not name a grid (3136 is also 28 x 112), so it is stated here and
#: checked against the graph's own patch count at load.
PATCH = 14
MERGE = 2
STAGE = 784
GRID = STAGE // PATCH

#: The image token: `<|IMAGE_PLACEHOLDER|>` is vocabulary entry 100295 and is
#: also the model's ``image_token_id``. One prompt placeholder expands to
#: ``GRID*GRID / MERGE^2`` = 784 rows, one per merged patch.
PLACEHOLDER = "<|IMAGE_PLACEHOLDER|>"

#: Prompt literals, verbatim from chat_template.jinja. Spelled out because the
#: service renders the template itself (as it does for Qwen) rather than
#: shipping jinja2 to the board.
CLS_TOKEN = "<|begin_of_sentence|>"
EOS_TOKEN = "</s>"
IMAGE_BLOCK = "<|IMAGE_START|>" + PLACEHOLDER + "<|IMAGE_END|>"
USER_PREFIX = "User: "
ASSISTANT_PREFIX = "Assistant:\n"

#: The four task prompts the official pipeline uses. Not a whitelist -- any
#: text is accepted -- but they are what a caller will send, so they are named
#: once for the docs and the tests.
TASK_PROMPTS = (
    "OCR:",
    "Table Recognition:",
    "Formula Recognition:",
    "Chart Recognition:",
)

#: Prompt + generation must fit the bmodel's SEQLEN (2048). Checked here so the
#: caller gets a 400 rather than a truncated answer: the engine can only stop
#: at the sequence end, and a table that silently lost its last rows is worse
#: than a refusal.
MIN_NEW_TOKENS = 1


class OcrVlError(RuntimeError):
    """An engine failure, as opposed to a request this model cannot serve."""


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------
@dataclass
class _Turn:
    role: str
    texts: list[str]
    images: int


def _turns(messages: Sequence) -> list[_Turn]:
    """Flatten the OpenAI content shape into turns, in the template's order.

    * one text part per ``{"type": "text"}``;
    * one image per ``{"type": "image_url"}``, which the template renders as the
      ``<|IMAGE_START|><|IMAGE_PLACEHOLDER|><|IMAGE_END|>`` block.

    The template writes every image of a user turn first and every text after,
    regardless of the order they arrived in, so the parts are split by type
    rather than kept in sequence.
    """
    from ..api.tool_calls import _part_field

    out: list[_Turn] = []
    for m in messages:
        role = _part_field(m, "role")
        content = _part_field(m, "content")
        texts: list[str] = []
        images = 0
        if isinstance(content, str):
            texts.append(content)
        elif content is not None:
            for part in content:
                ptype = _part_field(part, "type")
                if ptype == "text":
                    text = _part_field(part, "text")
                    if text:
                        texts.append(text)
                elif ptype == "image_url":
                    images += 1
                else:
                    raise ValueError(f"content part type {ptype!r} is not supported")
        out.append(_Turn(role=role, texts=texts, images=images))
    return out


def render_prompt(messages: Sequence) -> tuple[str, list[str]]:
    """The model's chat template, rendered; returns (prompt, image data URLs).

    The second value is the *list of images* the request carried, not just their
    count, because the rest of the service speaks that shape: ``images`` from
    ``build_prompt`` / ``flatten_content`` is the list of base64 payloads the
    worker decodes. Keeping the same shape here means one branch of the API
    cannot quietly disagree with the other about how many images a request had.

    The rendering itself is what ``chat_template.jinja`` does, transcribed:

    Mirrors ``model-config/paddleocr_vl_1_5/chat_template.jinja`` exactly, the
    way ``app/api/tool_calls.render_messages`` mirrors Qwen's: the board has no
    jinja2, and a template rendered twice from two implementations is a template
    rendered two ways. ``tests/test_ocr_vl_prompt.py`` renders the same messages
    with jinja2 and compares the two byte for byte.

    The template has no tool support and no system role of its own: a system
    message is written as its text plus a newline, before any user turn, which
    is what the template's ``system`` branch does.
    """
    turns = _turns(messages)
    if not turns:
        raise ValueError("messages must not be empty")

    out = CLS_TOKEN
    for turn in turns:
        if turn.role == "user":
            out += USER_PREFIX
            out += IMAGE_BLOCK * turn.images
            out += "".join(turn.texts)
            out += "\n"
        elif turn.role == "assistant":
            out += ASSISTANT_PREFIX
            out += "".join(turn.texts)
            out += EOS_TOKEN
        elif turn.role == "system":
            out += "".join(text + "\n" for text in turn.texts)
        else:
            raise ValueError(f"unsupported message role {turn.role!r}")
    out += ASSISTANT_PREFIX
    # One data URL per image: the template writes only the marker, but the
    # caller (the API) needs the payloads to hand to the worker, and both
    # surfaces must count them the same way.
    from ..api.tool_calls import _DATA_URL, _part_field

    images: list[str] = []
    for m in messages:
        content = _part_field(m, "content")
        if isinstance(content, str) or content is None:
            continue
        for part in content:
            if _part_field(part, "type") != "image_url":
                continue
            url = (_part_field(part, "image_url") or {}).get("url", "")
            match = _DATA_URL.match(url)
            if not match:
                raise ValueError(
                    "remote image URLs are not supported on this offline device; "
                    "send the image as a base64 data: URL")
            images.append(match.group("data"))
    return out, images


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------
def preprocess_image(blob: bytes, stage: int = STAGE,
                     cv2=None) -> tuple[int, int, "object"]:
    """Decode, resize to the vit stage, normalise and patchify.

    The arithmetic is ``tools/ocr/vl_native_prep.py``'s ``vit_input``, plus the
    letterbox the page path added (MYS-2664 §11.9) and that both paths now use
    (MYS-2681):

      * ``cv2.INTER_CUBIC``, **preserving the aspect ratio**, into the stage and
        padded to the square with white. This is *not* the processor's own
        resize (PIL/torchvision BICUBIC) -- on a 1240x1400 table crop the two
        disagree by up to 1.42 in normalised units, so the choice is part of the
        contract, not an implementation detail;
      * RGB, ``(x/255 - 0.5) / 0.5``;
      * patch-major ``[gh*gw, 3, 14, 14]`` float32.

    Returns ``(grid_h, grid_w, patches)`` where ``patches`` is a numpy array.
    OpenCV comes from the device's Sophon build (``ensure_opencv``), so this is
    the same resampler the prototype ran.
    """
    import numpy as np

    if cv2 is None:
        from .ocr_ppocr import ensure_opencv

        cv2 = ensure_opencv()
    data = np.frombuffer(blob, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("cannot decode the image; only JPEG and PNG are supported")
    if bgr.ndim != 3 or bgr.shape[0] < 1 or bgr.shape[1] < 1:
        raise ValueError("the image has no pixels")

    gh, gw, patches = _patchify(bgr, stage, cv2=cv2)
    return gh, gw, patches


def _fit_into_square(bgr, stage: int, cv2):
    """Scale a crop to fit the stage **preserving its aspect**, then pad.

    Both callers use this, and the board settled it: ``table_stats.png``'s title
    region is 706x47 (15:1), and squashing it to 784x784 compresses the glyphs
    16.7x vertically. The model then answers ``1990年日本国立大学成立`` for a page
    that says ``2026年第三季度生产数据统计表`` -- a fluent, confident, completely
    invented line. Padding instead reads both text regions correctly *and*
    leaves the table unchanged.

    The chat path used to stretch on the theory that a chat caller sends one
    near-square element it cropped itself. That theory does not survive contact
    with the official client: PaddleX's ``PaddleOCRVL`` pipeline
    (``vl_rec_backend="vllm-server"``) runs layout first and posts **each
    region crop** to ``/v1/chat/completions``, and the titles and footnotes it
    sends are exactly these 10:1-and-wider strips (MYS-2681). Stretching them
    made a standards-conforming client silently wrong, which is the one failure
    mode an OpenAI-compatible surface must not have.

    Why the reference never hits this: PaddleX's ``smart_resize`` keeps the
    aspect and **grows** a small crop to at least ``min_pixels`` (336x336) -- a
    706x47 title becomes 112x1316, so the network always sees legible glyphs.
    This service's vit is compiled for one fixed 784x784 stage (MYS-2660 §7),
    so it cannot reproduce that grid; preserving the aspect and padding is the
    closest a fixed square stage can come, and it is what keeps the glyphs
    readable.

    Padding colour is white, which is what the crops' own background is: these
    are page regions, not photos, so white introduces no new edges.
    """
    import numpy as np

    height, width = bgr.shape[:2]
    scale = min(stage / float(height), stage / float(width))
    new_h = max(1, int(round(height * scale)))
    new_w = max(1, int(round(width * scale)))
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((stage, stage, 3), 255, dtype=np.uint8)
    top = (stage - new_h) // 2
    left = (stage - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


def _patchify(bgr, stage: int = STAGE, cv2=None, *, fit: bool = True):
    """Resize a decoded BGR crop to the vit stage and pack it into patches.

    Split out of :func:`preprocess_image` so ``mode: "vl"`` can feed a crop it
    already has: a page crop is decoded pixels, and encoding it to PNG only to
    decode it again would be a round trip that changes nothing. One
    implementation means the two paths cannot produce different tensors for the
    same pixels -- ``tests/test_ocr_vl_page_mode.py`` asserts exactly that.

    Same arithmetic as the prototype's ``vit_input`` except for the resize:
    ``INTER_CUBIC``, RGB, ``(x/255 - 0.5) / 0.5``,
    patch-major ``[gh*gw, 3, 14, 14]``.

    ``fit`` is kept as a parameter because the arithmetic is a contract, but
    **both callers pass ``True``**: preserve the aspect and pad
    (:func:`_fit_into_square`). ``False`` stretches to the square and is now
    only used by tests, as the control that shows what stretching costs.

    The chat path used to be the ``False`` one, on the theory that a chat caller
    sends one near-square element it cropped itself. MYS-2681 retired that
    theory: the official PaddleOCR-VL pipeline runs layout first and posts each
    region crop to ``/v1/chat/completions``, so its 706x47 titles and 537x29
    footnotes arrive at the chat path as 15:1 and 18:1 strips. Stretched, those
    hallucinate fluent nonsense; padded, the page path already read them
    correctly on the board (``docs/ocr-vl.md`` §11.9). Two paths, one
    arithmetic, no way for a conforming client to land on the wrong one.
    """
    import numpy as np

    if cv2 is None:
        from .ocr_ppocr import ensure_opencv

        cv2 = ensure_opencv()
    if fit:
        resized = _fit_into_square(bgr, stage, cv2)
    else:
        resized = cv2.resize(bgr, (stage, stage), interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    x = (rgb / 255.0 - 0.5) / 0.5
    gh, gw = stage // PATCH, stage // PATCH
    x = x.reshape(gh, PATCH, gw, PATCH, 3).transpose(0, 2, 4, 1, 3)
    patches = np.ascontiguousarray(x.reshape(gh * gw, 3, PATCH, PATCH),
                                   dtype=np.float32)
    return gh, gw, patches


# ---------------------------------------------------------------------------
# The engine library
# ---------------------------------------------------------------------------
class _VlLib:
    """ctypes binding for cv_vl_* (native/src/c_api.cpp)."""

    def __init__(self, lib: _Lib) -> None:
        c = lib.lib
        err = _P(ctypes.c_char_p)
        c.cv_vl_create.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
        c.cv_vl_create.restype = ctypes.c_void_p
        c.cv_vl_destroy.argtypes = [ctypes.c_void_p]
        c.cv_vl_info.argtypes = [ctypes.c_void_p] + [_c_int_p] * 5 + \
            [_P(ctypes.c_ulonglong)]
        c.cv_vl_prefill.argtypes = [ctypes.c_void_p, _c_int_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    _c_float_p, err]
        c.cv_vl_prefill.restype = ctypes.c_int
        c.cv_vl_step.argtypes = [ctypes.c_void_p, err]
        c.cv_vl_step.restype = ctypes.c_int
        c.cv_vl_timings.argtypes = [ctypes.c_void_p] + \
            [_P(ctypes.c_double)] * 5 + [_c_int_p] * 3
        self._lib = lib
        self._handle = None

    def create(self, model_path: str, dev_id: int) -> None:
        err = ctypes.c_char_p()
        handle = self._lib.lib.cv_vl_create(model_path.encode(), dev_id,
                                            ctypes.byref(err))
        if not handle:
            raise OcrVlError(self._lib.error() if not err.value
                             else err.value.decode("utf-8", "replace"))
        self._handle = handle

    def destroy(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            self._lib.lib.cv_vl_destroy(handle)

    def info(self) -> dict:
        seqlen, layers, hidden, image_tokens, patches = (ctypes.c_int() for _ in range(5))
        kv = ctypes.c_ulonglong()
        self._lib.lib.cv_vl_info(self._handle, ctypes.byref(seqlen),
                                 ctypes.byref(layers), ctypes.byref(hidden),
                                 ctypes.byref(image_tokens), ctypes.byref(patches),
                                 ctypes.byref(kv))
        return {"seq_len": seqlen.value, "layers": layers.value,
                "hidden": hidden.value, "image_tokens": image_tokens.value,
                "vit_patches": patches.value, "kv_bytes_per_layer": kv.value}

    def prefill(self, ids, head_len: int, grid: tuple[int, int], patches) -> None:
        n = len(ids)
        id_arr = (ctypes.c_int * max(n, 1))(*ids)
        ptr = patches.ctypes.data_as(_c_float_p)
        err = ctypes.c_char_p()
        rc = self._lib.lib.cv_vl_prefill(self._handle, id_arr, n, head_len,
                                         int(grid[0]), int(grid[1]), ptr,
                                         ctypes.byref(err))
        if rc != 0:
            raise OcrVlError(self._lib.error())

    def step(self) -> int:
        err = ctypes.c_char_p()
        tok = self._lib.lib.cv_vl_step(self._handle, ctypes.byref(err))
        if tok < 0:
            raise OcrVlError(self._lib.error())
        return int(tok)

    def timings(self) -> dict:
        vals = [ctypes.c_double() for _ in range(5)]
        ints = [ctypes.c_int() for _ in range(3)]
        self._lib.lib.cv_vl_timings(self._handle,
                                    *[ctypes.byref(v) for v in vals],
                                    *[ctypes.byref(v) for v in ints])
        return {
            "vit_ms": vals[0].value, "embed_ms": vals[1].value,
            "prefill_ms": vals[2].value, "decode_ms": vals[3].value,
            "lm_ms": vals[4].value, "prompt_tokens": ints[0].value,
            "image_tokens": ints[1].value, "decode_steps": ints[2].value,
        }


# ---------------------------------------------------------------------------
# The prompt, as the engine needs it
# ---------------------------------------------------------------------------
class VlPrompt(list):
    """Token ids plus the one image they stand for.

    A list subclass so it flows through the scheduler like any other token list
    (``native.Prompt`` does the same for the 35B VLMs). ``image`` is None for a
    text-only prompt, which this model can technically answer but is not what it
    is for.
    """

    def __init__(self, tokens, image=None) -> None:
        super().__init__(tokens)
        self.image = image  # dict(patches, grid, head_len) or None

    def segment(self, a: int, b: int) -> "VlPrompt":
        """This backend never chunks prefill, so a segment must be the whole
        prompt. Kept so a future caller cannot silently lose the image."""
        if a != 0 or b != len(self):
            raise ValueError("this model prefills the whole prompt in one call")
        return self


# ---------------------------------------------------------------------------
class PaddleVlSession(Session):
    """One request's decoding state: the engine's single KV cache.

    Not concurrent with another session -- the backend hands out the engine
    under a lock and the worker runs one request at a time (see
    ``PaddleVlBackend.serial_only``).

    The engine lock is taken in ``feed_prompt`` and released in ``close``, not
    per step: the KV cache *is* this session's state, so a second request must
    not enter the engine between two of its steps. That is affordable precisely
    because the worker admits one request at a time.
    """

    def __init__(self, backend: "PaddleVlBackend", prompt: VlPrompt) -> None:
        self._backend = backend
        self._prompt = prompt
        self._tokens = 0
        self._first = True
        self._closed = False
        #: The prompt length, so the scheduler sees `token_len` grow.
        self._token_len = 0

    @property
    def token_len(self) -> int:
        return self._token_len

    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        if self._token_len:
            raise OcrVlError("this model cannot extend a prompt: prefill once")
        await self._backend._prefill(self._prompt)
        # The prompt occupies rows 0..L-1 and the first generated token comes
        # out of row L-1, so the session holds L rows after prefill.
        self._token_len = len(self._prompt)

    async def step(self) -> Token:
        if self._first:
            # The first token is already decided; the engine's step() hands it
            # out and only decodes from the second call on.
            self._first = False
        tok = await self._backend._step()
        self._token_len += 1
        return tok

    def decode(self, tokens: Sequence[Token]) -> str:
        return self._backend.tokenizer_decode(tokens)

    def decode_bytes(self, tokens: Sequence[Token]) -> bytes:
        # The decoder is a ByteFallback sequence: a CJK character can arrive as
        # several <0xXX> byte tokens, so the scheduler has to join the raw bytes
        # (the same reason the 35B byte-level backend overrides this).
        return self._backend.tokenizer_decode_bytes(tokens)

    def is_stop_token(self, token: Token) -> bool:
        return token in self._backend._stop_ids

    async def snapshot(self, token_len: int) -> object:
        # There is one KV cache and no way to copy it out cheaply; the prefix
        # cache is disabled for this backend (kv_snapshots_verified = False), so
        # this is only reachable from a caller that ignored that flag.
        raise OcrVlError("this model does not support KV snapshots")

    async def restore(self, snap: object) -> None:
        raise OcrVlError("this model does not support KV snapshots")

    async def close(self) -> None:
        self._closed = True
        self._backend._release()


# ---------------------------------------------------------------------------
class PaddleVlBackend(EngineBackend):
    """One resident PaddleOCR-VL bmodel: tokenizer, preprocessing, one session."""

    #: What the worker and the scheduler need to know about this model beyond
    #: the EngineBackend contract.
    kind = "ocr_vl"
    serial_only = True          # one KV cache: one request at a time
    detects_loops = False       # OTSL repeats on purpose

    def __init__(self, model_path: str, tokenizer_path: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0) -> None:
        self._model_id = model_id
        self._model_path = model_path
        self._lib = _Lib(lib_path or os.environ.get("CV84X6_LLM_LIB") or os.path.join(
            os.path.dirname(__file__), "..", "..", "lib", "libcv84x6_llm.so"))
        self._vl = _VlLib(self._lib)
        self._vl.create(model_path, dev_id)
        info = self._vl.info()
        self._seq = int(info["seq_len"])
        self._image_tokens = int(info["image_tokens"])
        patches = int(info["vit_patches"])
        if patches != GRID * GRID:
            self._vl.destroy()
            raise OcrVlError(
                f"this bmodel's vit takes {patches} patches, but the only stage "
                f"this service ships is {STAGE}x{STAGE} ({GRID * GRID} patches); "
                "the fixed-stage contract would be violated silently")
        #: NPU bytes one parked session would cost. Reported so the scheduler's
        #: memory arithmetic has a number rather than guessing.
        self.session_state_bytes = int(info["kv_bytes_per_layer"]) * int(info["layers"])
        self.kv_bytes_per_token = 0     # the KV is per session, not per token
        self.linear_state_bytes = 0

        # The tokenizer is the engine library's, like every other model here.
        self._tok = _TokLib(self._lib)
        self._tok.load(tokenizer_path)
        self._placeholder_id = self._tok.token_to_id(PLACEHOLDER)
        if self._placeholder_id is None:
            self._vl.destroy()
            raise OcrVlError(f"tokenizer has no {PLACEHOLDER}")
        self._stop_ids = {i for i in (self._tok.token_to_id(EOS_TOKEN),) if i is not None}
        # One request at a time: the engine has one KV cache, and the lock is
        # what keeps a second request from writing into it.
        self._lock = asyncio.Lock()
        # img decode/resize/patchify is CPU work under the GIL in OpenCV's C++;
        # the backend keeps a thread lock so two calls cannot interleave.
        self._cpu_lock = threading.Lock()
        self.last_timings: dict = {}

    # -- EngineBackend -----------------------------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self._seq

    @property
    def max_prompt_length(self) -> int:
        # One row is reserved: the first generated token comes out of the
        # prompt's last row, and decode writes row L.
        return self._seq - 2

    @property
    def prefill_chunk(self) -> int:
        return self._seq

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_sampling(self) -> bool:
        # lm_head emits one int32: the argmax is inside the graph.
        return False

    @property
    def supports_chunked_prefill(self) -> bool:
        # The prefill mask is built for the whole prompt in one launch.
        return False

    @property
    def kv_snapshots_verified(self) -> bool:
        return False

    # -- tokenizer ---------------------------------------------------------
    def tokenizer_decode(self, tokens: Sequence[int]) -> str:
        # skip_special_tokens=True, exactly as the reference client decodes:
        # `</s>` and the image markers go, while the OTSL markers (`<fcel>`,
        # `<nl>`, `<lcel>`, `<ucel>`, …) are ordinary vocabulary entries and stay
        # -- the official client's OTSL -> HTML post-processing needs them.
        return self._tok.decode(list(tokens), skip_special=True)

    def tokenizer_decode_bytes(self, tokens: Sequence[int]) -> bytes:
        return self._tok.decode_bytes(list(tokens), skip_special=True)

    def tokenizer_encode(self, text: str) -> list[int]:
        return self._tok.encode(text)

    # -- prompt / images ---------------------------------------------------
    def _encode(self, text: str, blobs: list[bytes]) -> VlPrompt:
        if text.count(PLACEHOLDER) != len(blobs):
            raise ValueError("prompt has %d image placeholders for %d images"
                             % (text.count(PLACEHOLDER), len(blobs)))
        ids = self.tokenizer_encode(text)
        if not blobs:
            return VlPrompt(ids)

        gh, gw, patches = preprocess_image(blobs[0])
        n_img = (gh // MERGE) * (gw // MERGE)
        head_len = ids.index(self._placeholder_id)
        # One prompt placeholder expands to one row per merged patch: the vit
        # writes its output straight into those rows, so a mismatch would put
        # image embeddings in the wrong positions -- and still emit text.
        out = ids[:head_len] + [self._placeholder_id] * n_img + ids[head_len + 1:]
        return VlPrompt(out, image={"patches": patches, "grid": (gh, gw),
                                    "head_len": head_len})

    async def encode(self, text: str,
                     images: Sequence[bytes] | None = None) -> list[Token]:
        blobs = list(images or [])
        if len(blobs) > 1:
            raise ValueError(
                "这个模型一次只接受一张图片：请把多页拆成多次请求"
                "（PaddleOCR 的产线本来就是逐元素调用）")
        if not blobs:
            return VlPrompt(self.tokenizer_encode(text))
        # Decode + resize + patchify is milliseconds of CPU; a thread keeps the
        # event loop answering health probes while it runs.
        return await asyncio.to_thread(self._encode, text, blobs)

    # -- engine ------------------------------------------------------------
    async def _prefill(self, prompt: VlPrompt) -> None:
        await self._lock.acquire()
        try:
            image = prompt.image
            if image is None:
                raise ValueError("this model needs an image")
            await asyncio.to_thread(self._vl.prefill, list(prompt),
                                    image["head_len"], image["grid"],
                                    image["patches"])
            self.last_timings = self._vl.timings()
        except BaseException:
            self._release()
            raise

    async def _step(self) -> int:
        try:
            tok = await asyncio.to_thread(self._vl.step)
            self.last_timings = self._vl.timings()
            return tok
        except BaseException:
            self._release()
            raise

    def _release(self) -> None:
        """Give the engine back. Idempotent: close() and a failure both call it."""
        try:
            if self._lock.locked():
                self._lock.release()
        except RuntimeError:  # pragma: no cover - released from another loop
            pass

    async def new_session(self) -> Session:
        # The prompt (and with it the image) travels through ``encode``'s return
        # value, so the scheduler hands it back to ``new_session_for``. The
        # worker does that; a plain ``new_session`` has nothing to prefill.
        raise NotImplementedError("vl sessions are created by new_session_for")

    async def new_session_for(self, prompt: VlPrompt) -> Session:
        return PaddleVlSession(self, prompt)

    # -- whole-page mode: one region at a time -----------------------------
    async def recognise_block(self, crop_bgr, task: str,
                              max_new_tokens: int | None = None) -> dict:
        """Read one page region: ``crop`` + a task prompt -> its text.

        This is what ``mode: "vl"`` of ``/v1/ocr`` calls once per layout region,
        and it exists on the backend rather than as a second engine path for two
        reasons:

        * **the lock.** The engine owns one KV cache, so a page's regions must
          queue behind chat requests exactly as a chat request queues behind
          them -- through the same ``_lock`` the scheduler uses, which is
          ``serial_only``'s whole content. A page is therefore one long
          occupancy of the model, and a chat request that arrives mid-page waits
          rather than corrupting the cache.
        * **no scheduler.** A region is a single prompt + a bounded greedy loop
          with no streaming and no prefix cache; going through the scheduler
          would enqueue a session per region and pay its per-request bookkeeping
          for an answer nobody streams.

        The decode loop is the reference's own: greedy, stop at EOS, stop at
        ``max_new_tokens``. It does **not** apply the loop heuristic -- a table
        legitimately repeats ``<fcel>`` hundreds of times, which is why
        ``detects_loops`` is False for this model everywhere else too.

        Returns ``{"text", "tokens", "timings"}``. ``timings`` carries the
        engine's own per-stage numbers, which the page reports as ``vl_ms``.
        """
        import numpy as np

        lock = self._lock
        await lock.acquire()
        try:
            prompt = self._encode_block(task)
            patches = await asyncio.to_thread(self._crop_patches, crop_bgr)
            await asyncio.to_thread(self._vl.prefill, list(prompt),
                                    prompt.image["head_len"],
                                    prompt.image["grid"], patches)
            produced: list[int] = []
            timings = self._vl.timings()
            eos = self._stop_ids
            for _ in range(max_new_tokens):
                token = await asyncio.to_thread(self._vl.step)
                if token in eos:
                    break
                produced.append(token)
            timings = self._vl.timings()
        finally:
            self._release()

        text = self.tokenizer_decode(produced)
        return {"text": text, "tokens": len(produced), "timings": timings}

    # -- whole-page mode ---------------------------------------------------
    def decode_page(self, image: bytes):
        """A page image's bytes -> BGR pixels, for ``mode: "vl"`` to crop.

        Lives on the backend because OpenCV comes from the device (see
        ``ocr_ppocr.ensure_opencv``): the mock backend has to serve the same
        callable on a laptop with no Sophon SDK, and the worker must not import
        cv2 itself.
        """
        import numpy as np

        from .ocr_ppocr import ensure_opencv

        cv2 = ensure_opencv()
        bgr = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(
                "无法解码这张图片；支持 PNG/JPEG/BMP/WebP 等 OpenCV 能读的格式")
        if bgr.ndim != 3 or bgr.shape[0] < 2 or bgr.shape[1] < 2:
            raise ValueError(f"图片太小：{bgr.shape[1]}x{bgr.shape[0]}")
        return bgr

    def region_prompt(self, task: str) -> VlPrompt:
        """The prompt for one page region: the task instruction + one image.

        Rendered by the same code a chat request uses (:func:`render_prompt`), so
        the two surfaces cannot spell the template differently -- the trailing
        ``Assistant:\n`` in particular, which A3 measured as load-bearing. The
        image itself is a placeholder only; its pixels arrive separately from the
        page crop, because the crop is already decoded pixels and re-encoding it
        to PNG just to decode it again would be a lossless round trip nobody
        needs.
        """
        text, _images = render_prompt([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,"}},
            {"type": "text", "text": task},
        ]}])
        ids = self.tokenizer_encode(text)
        head_len = ids.index(self._placeholder_id)
        n_img = (GRID // MERGE) * (GRID // MERGE)
        return VlPrompt(ids[:head_len] + [self._placeholder_id] * n_img
                        + ids[head_len + 1:],
                        image={"patches": None, "grid": (GRID, GRID),
                               "head_len": head_len})

    async def recognise_block(self, crop_bgr, task: str,
                              max_new_tokens: int | None = None) -> dict:
        """Read one page region: ``crop`` + a task prompt -> its text.

        This is what ``mode: "vl"`` of ``/v1/ocr`` calls once per layout region,
        and it lives on the backend rather than in a second engine path for two
        reasons:

        * **the lock.** The engine owns one KV cache, so a page's regions queue
          behind chat requests through the same ``_lock`` the scheduler's
          session takes -- which is ``serial_only``'s whole content. Note the
          granularity: the lock is taken and released **per region**, not once
          per page, so a chat request that arrives mid-page is served after the
          region in flight rather than after all twelve.
        * **no scheduler.** A region is one prompt plus a bounded greedy loop:
          no streaming, and no prefix cache to consult. Enqueueing a scheduler
          request per region would pay its bookkeeping for an answer nobody
          streams.

        The decode loop is the reference's: greedy, stop at EOS, stop at
        ``max_new_tokens``. It deliberately does **not** apply the scheduler's
        loop heuristic -- a table repeats ``<fcel>`` hundreds of times by design,
        which is why ``detects_loops`` is False for this model everywhere else.

        Returns ``{"text", "tokens", "timings"}``, the timings being the engine's
        own per-stage numbers for the page's ``usage`` block.
        """
        from .ocr_vl_page import effective_max_new

        budget = effective_max_new(max_new_tokens)
        await self._lock.acquire()
        try:
            prompt = self.region_prompt(task)
            # ``_patchify`` returns ``(grid_h, grid_w, patches)`` because its
            # other caller (``preprocess_image``) reports the grid too; the grid
            # here comes from the bmodel's fixed stage, so only the tensor is
            # wanted. Passing the tuple through is what a first version did, and
            # it failed inside ctypes with "tuple has no attribute ctypes".
            _grid_h, _grid_w, patches = await asyncio.to_thread(
                _patchify, crop_bgr, STAGE, None, fit=True)
            await asyncio.to_thread(self._vl.prefill, list(prompt),
                                    prompt.image["head_len"],
                                    prompt.image["grid"], patches)
            produced: list[int] = []
            eos_ids = self._stop_ids
            for _ in range(budget):
                token = await asyncio.to_thread(self._vl.step)
                if token in eos_ids:
                    break
                produced.append(token)
            timings = self._vl.timings()
        finally:
            self._release()
        return {"text": self.tokenizer_decode(produced), "tokens": len(produced),
                "timings": timings}

    async def close(self) -> None:
        self._release()
        self._vl.destroy()
