"""Prompt construction for Qwen3-ASR: tokenizer, chunking and the input_ids.

Stage 2 calls straight into this, so the shapes and token sequences match what
the reference processor produces for the same audio and language. The reference
is ``LLM-TPU/models/Qwen3_ASR/python_demo/pipeline.py``::

    messages = [{"role": "system", "content": <context>},
                {"role": "user", "content": [{"type": "audio", "audio": ""}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if language is not None:
        text += f"language {language}<asr_text>"

The chat template is fixed for this model, so the rendered text is assembled
here rather than by shipping jinja2 to the board:

    <|im_start|>system\n<context><|im_end|>\n
    <|im_start|>user\n<|audio_start|><|audio_pad|><|audio_end|><|im_end|>\n
    <|im_start|>assistant\n
    [language <Name><asr_text>]

The processor then replaces the audio pad token with ``n_audio_tokens`` copies
of ``<|audio_pad|>``: 13 per second of audio, one group per audio-tower call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: One audio chunk is ``n_window * 2`` mel frames (50 * 2 = 100 at 10 ms hop =
#: 1 s), and the tower emits ``AUDIO_LENGTH`` tokens for it -- 13 per second.
TOKENS_PER_CHUNK = 13
#: Mel frames per audio-tower invocation: ``n_window * 2`` from the model config.
FRAMES_PER_CHUNK = 100

#: The model's language list (config.json ``support_languages``) plus the
#: ISO-639-1 codes callers are likely to send. ``yue`` has no ISO-639-1 code of
#: its own; Cantonese is conventionally written ``zh-yue``, but this is what the
#: Qwen API accepts, so it is mapped too.
LANGUAGE_CODES: dict[str, str] = {
    "zh": "Chinese", "cmn": "Chinese", "zh-cn": "Chinese", "zh-hans": "Chinese",
    "zh-yue": "Cantonese", "yue": "Cantonese",
    "en": "English",
    "ar": "Arabic",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "id": "Indonesian",
    "it": "Italian",
    "ko": "Korean",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "tr": "Turkish",
    "hi": "Hindi",
    "ms": "Malay",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "fil": "Filipino", "tl": "Filipino",
    "fa": "Persian",
    "el": "Greek",
    "ro": "Romanian",
    "hu": "Hungarian",
    "mk": "Macedonian",
}

#: Canonical names, taken from the model's config.json ``support_languages``.
SUPPORTED_LANGUAGES: tuple[str, ...] = (
    "Chinese", "English", "Cantonese", "Arabic", "German", "French", "Spanish",
    "Portuguese", "Indonesian", "Italian", "Korean", "Russian", "Thai",
    "Vietnamese", "Japanese", "Turkish", "Hindi", "Malay", "Dutch", "Swedish",
    "Danish", "Finnish", "Polish", "Czech", "Filipino", "Persian", "Greek",
    "Romanian", "Hungarian", "Macedonian",
)

#: Tokens the prompt is built from; ids come from the model's tokenizer.json.
TOKEN_IM_START = "<|im_start|>"
TOKEN_IM_END = "<|im_end|>"
TOKEN_AUDIO_BOS = "<|audio_start|>"
TOKEN_AUDIO_EOS = "<|audio_end|>"
TOKEN_AUDIO_PAD = "<|audio_pad|>"


@dataclass(frozen=True)
class AsrTokenizer:
    """The model's tokenizer, loaded from the ``tokenizers`` package.

    The board vendors a Rust ``tokenizers`` wheel (stage 1A adds it to
    ``requirements-vendor.txt``), so this is the same implementation the
    reference ``AutoTokenizer`` wraps -- no torch, no transformers.
    """

    tokenizer: object
    _special: dict[str, int]
    _path: Path | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "AsrTokenizer":
        from tokenizers import Tokenizer  # imported here: the module stays importable without it

        path = Path(path)
        tok = Tokenizer.from_file(str(path))
        special: dict[str, int] = {}
        for token in (
            TOKEN_IM_START, TOKEN_IM_END, TOKEN_AUDIO_BOS, TOKEN_AUDIO_EOS,
            TOKEN_AUDIO_PAD, "<|endoftext|>", "<asr_text>",
        ):
            tid = tok.token_to_id(token)
            if tid is None:
                raise ValueError(f"tokenizer.json 缺少特殊 token {token}")
            special[token] = tid
        return cls(tokenizer=tok, _special=special, _path=path)

    def encode(self, text: str) -> list[int]:
        """Tokenise ``text`` exactly as the reference tokenizer does.

        The tokenizer is used without its padding/truncation pipeline, so the
        only thing that can differ is post-processing -- which is the identity
        for this model (``add_bos_token: false``).
        """
        return self.tokenizer.encode(text, add_special_tokens=False).ids

    def decode(self, ids: list[int]) -> str:
        return self.tokenizer.decode(list(ids), skip_special_tokens=True)

    def token_id(self, token: str) -> int:
        if token in self._special:
            return self._special[token]
        tid = self.tokenizer.token_to_id(token)
        if tid is None:
            raise ValueError(f"词表中没有 token {token!r}")
        return tid

    @property
    def im_end(self) -> int:
        return self._special[TOKEN_IM_END]

    @property
    def audio_pad(self) -> int:
        return self._special[TOKEN_AUDIO_PAD]

    @property
    def audio_bos(self) -> int:
        return self._special[TOKEN_AUDIO_BOS]

    @property
    def audio_eos(self) -> int:
        return self._special[TOKEN_AUDIO_EOS]


def normalize_language(language: str | None) -> str | None:
    """Map a language name or ISO code to the canonical Qwen name.

    Accepts the canonical name in any case (``chinese`` -> ``Chinese``) and the
    ISO-639-1 codes clients put in an OpenAI ``language`` field. ``None`` stays
    ``None``: the model then detects the language itself.
    """
    if language is None:
        return None
    key = str(language).strip()
    if not key:
        raise ValueError("language 为空；不指定语言请传 None")
    lowered = key.lower()
    if lowered in LANGUAGE_CODES:
        return LANGUAGE_CODES[lowered]
    for name in SUPPORTED_LANGUAGES:
        if lowered == name.lower():
            return name
    raise ValueError(
        f"不支持的语言 {language!r}；可用：{', '.join(SUPPORTED_LANGUAGES)}，"
        f"或 ISO-639-1 代码：{', '.join(sorted(LANGUAGE_CODES))}")


def _conv_downsample(frames: int) -> int:
    """Frames out of the audio tower's three stride-2 convolutions.

    ``frames -> (f-1)//2+1`` three times, which takes 100 mel frames to the 13
    tokens one chunk is worth. This is the reference's
    ``_get_feat_extract_output_lengths`` for the ragged tail.
    """
    for _ in range(3):
        frames = (frames - 1) // 2 + 1 if frames > 0 else 0
    return frames


def audio_token_count(n_frames: int, audio_length: int, tokens_per_chunk: int = TOKENS_PER_CHUNK) -> int:
    """How many ``<|audio_pad|>`` tokens ``n_frames`` mel frames expand to.

    Whole ``audio_length``-frame chunks are worth ``tokens_per_chunk`` tokens
    each -- 13 per 100 mel frames, i.e. 13 per second of audio, the constant the
    reference hard-codes as ``audio_tokens_per_chunk``. The ragged tail goes
    through the same three stride-2 convolutions the tower applies, so it
    contributes proportionally fewer tokens.

    ``audio_length`` is the bmodel's ``AUDIO_LENGTH`` (frames per tower call,
    100 for this model), ``n_frames`` the number of valid mel frames.
    """
    if n_frames <= 0:
        raise ValueError(f"n_frames 必须为正：{n_frames}")
    if audio_length <= 0:
        raise ValueError(f"audio_length 必须为正：{audio_length}")
    if tokens_per_chunk <= 0:
        raise ValueError(f"tokens_per_chunk 必须为正：{tokens_per_chunk}")

    whole, tail = divmod(n_frames, audio_length)
    return whole * tokens_per_chunk + _conv_downsample(tail)


def n_chunks(n_frames: int, audio_length: int) -> int:
    """How many ``audio_length``-frame chunks ``n_frames`` spans, rounded up."""
    if n_frames <= 0:
        raise ValueError(f"n_frames 必须为正：{n_frames}")
    if audio_length <= 0:
        raise ValueError(f"audio_length 必须为正：{audio_length}")
    return -(-n_frames // audio_length)


def chunk_features(feats: np.ndarray, audio_length: int) -> np.ndarray:
    """Cut ``[128, frames]`` features into ``[n_chunks, 128, audio_length]``.

    The reference truncates the audio to whole seconds before extracting
    features (``y[:(len(y)//sr)*sr]``), which silently drops the tail of every
    clip that is not a whole number of seconds. Here the features are instead
    padded with silence zeros to the chunk boundary, so the last chunk keeps its
    real frames and only the unused slots are zero.

    Zero is the right padding value: the extractor's own padding value is 0.0,
    and ``(log(1e-10) + 4) / 4`` for a zero-power mel bin is exactly -0.375, not
    0 -- so callers that need "no audio here" semantics should use the frame
    count, which is why this returns whole chunks and callers slice by
    ``audio_token_count``.
    """
    feats = np.asarray(feats, dtype=np.float32)
    if feats.ndim != 2:
        raise ValueError(f"特征应为 [128, frames]，实际 {feats.shape}")
    if audio_length <= 0:
        raise ValueError(f"audio_length 必须为正：{audio_length}")
    if feats.shape[1] == 0:
        raise ValueError("特征为空")

    total = n_chunks(feats.shape[1], audio_length)
    out = np.zeros((total, feats.shape[0], audio_length), dtype=np.float32)
    for i in range(total):
        part = feats[:, i * audio_length:(i + 1) * audio_length]
        out[i, :, :part.shape[1]] = part
    return out


def build_prompt(
    tok: AsrTokenizer,
    n_audio_tokens: int,
    language: str | None,
    context: str = "",
) -> tuple[list[int], int]:
    """Build ``input_ids`` for one transcription, plus the audio BOS position.

    ``n_audio_tokens`` is what :func:`audio_token_count` says the audio expands
    to. ``context`` is the reference's ``input_str``: free text handed to the
    model as a system prompt (a glossary, a domain hint, or empty).

    Returns ``(input_ids, start_offset)`` where ``start_offset`` is the index of
    the ``<|audio_start|>`` token -- the reference's ``start_offset``, which the
    native engine uses as the insertion point for the audio embeddings.

    The text is tokenised as one string, the way the reference does it. Encoding
    the pieces separately would be wrong: byte-level BPE merges across the joins
    (``assistant\\n`` + ``language …`` gives a different token than the pair
    inside one call).
    """
    if n_audio_tokens <= 0:
        raise ValueError(f"n_audio_tokens 必须为正：{n_audio_tokens}")
    name = normalize_language(language)

    # The model's chat_template.json, rendered. It always emits one system turn
    # (its content may be empty) and one user turn holding exactly one audio.
    text = (
        f"{TOKEN_IM_START}system\n{context}{TOKEN_IM_END}\n"
        f"{TOKEN_IM_START}user\n"
        f"{TOKEN_AUDIO_BOS}{TOKEN_AUDIO_PAD}{TOKEN_AUDIO_EOS}{TOKEN_IM_END}\n"
        f"{TOKEN_IM_START}assistant\n"
    )
    if name is not None:
        text += f"language {name}<asr_text>"

    # The processor's replace_multimodal_special_tokens, before tokenising.
    text = text.replace(TOKEN_AUDIO_PAD, TOKEN_AUDIO_PAD * n_audio_tokens)

    ids = tok.encode(text)
    try:
        start_offset = ids.index(tok.audio_bos)
    except ValueError:  # pragma: no cover - would mean a broken tokenizer.json
        raise ValueError("input_ids 里找不到 <|audio_start|>，tokenizer.json 有问题") from None
    return ids, start_offset
