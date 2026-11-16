"""Tokenisation for the auxiliary models, from the model's own tokenizer.json.

Why HF ``tokenizers`` and not the engine library's own tokenizer: the engine's
``native/src/tokenizer.cpp`` implements the Qwen chat vocabulary (byte-level BPE
with a fixed special-token table), which is right for Qwen3.5/3.6 but cannot
tokenise an XLM-R sentencepiece model at all. The auxiliary models ship a
``tokenizer.json`` each, and HF's Rust library reads exactly that file -- so the
ids are the ones the reference ``AutoTokenizer`` produces, by construction
rather than by reimplementation.

Two entry points, both mirroring the reference pipelines exactly:

* :meth:`AuxTokenizer.encode_single` -- ``AutoTokenizer(text, truncation=True,
  max_length=SEQLEN).input_ids``. Used by embedding, where each text is encoded
  on its own and the last token is pooled.
* :meth:`AuxTokenizer.encode_pair` -- ``AutoTokenizer([[q, d]],
  padding="max_length", truncation=True, max_length=SEQLEN)``. Returns ids, the
  attention mask, **and the XLM-R position ids** the reference derives by hand
  (padding -> ``pad_id``, everything else -> a running counter starting at
  ``pad_id + 1``). That rule is not a detail: the embedding table is indexed by
  it, and getting it wrong shifts every position by one.

Both are pinned token-for-token against the reference implementation by
``tests/test_aux_tokenize.py`` and ``tests/data/aux_token_golden.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The instruction prefix the reference pipeline uses for a *query* by default
#: (``models/Qwen3_Embedding/python_demo/pipeline.py``). Documents are encoded
#: with no prefix. Kept here so the API's ``instruction`` default and the golden
#: generator cannot disagree.
DEFAULT_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery: "
)


class TokenizerUnavailable(RuntimeError):
    """The ``tokenizers`` package (or the model's tokenizer.json) is missing."""


def _import_tokenizers():
    try:
        import tokenizers  # noqa: F401 - imported for its side effect
        return tokenizers
    except ImportError as exc:  # pragma: no cover - packaging guarantees it
        raise TokenizerUnavailable(
            "缺少 tokenizers 依赖；本版本的安装包会在 vendor/ 中提供，"
            "开发环境请 pip install tokenizers"
        ) from exc


class AuxTokenizer:
    """One model config directory's tokenizer, with the reference's two modes.

    ``config_dir`` is where the worker was pointed (``--config-path``): either
    the model directory's own ``config/`` or the bundled ``model-config/<kind>/``.
    """

    def __init__(self, config_dir: str | Path, seq_len: int) -> None:
        self.config_dir = Path(config_dir)
        self.seq_len = int(seq_len)
        tokenizer_json = self.config_dir / "tokenizer.json"
        if not tokenizer_json.exists():
            raise TokenizerUnavailable(f"{tokenizer_json} 不存在")
        tokenizers = _import_tokenizers()
        self._tok = tokenizers.Tokenizer.from_file(str(tokenizer_json))
        # NO truncation on the tokenizer object, deliberately. The reference
        # passes `truncation=True, max_length=SEQLEN`, but the service needs the
        # *untruncated* length as well -- to refuse an over-long input with a 400
        # instead of silently embedding a prefix of it -- and a tokenizer that
        # has already cut cannot report it. So truncation is applied by hand in
        # the two encode helpers below, at exactly the same boundary, and the
        # real count comes back with the ids.
        self.pad_token_id, self.pad_token = self._read_pad_token()
        #: The model's own special-token strings, so "is this trailing id
        #: special?" is answered by the tokenizer rather than by a guess.
        self._special_tokens = {
            added.content
            for added in self._tok.get_added_tokens_decoder().values()
            if added.special
        }
        self.eos_token_id = self._read_eos_token()

    def _read_pad_token(self) -> tuple[int, str]:
        """``tokenizer_config.json``'s pad token, falling back to the vocab.

        The reference reads ``tokenizer.pad_token_id``, which for XLM-R is
        ``<pad>`` (id 1). A config without one is an error rather than a silent
        zero: position ids are derived from this value, so a wrong pad id
        silently mis-positions every token.
        """
        cfg_path = self.config_dir / "tokenizer_config.json"
        pad = None
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cfg = {}
            pad = cfg.get("pad_token")
        if not pad:
            pad = "<pad>"
        tid = self._tok.token_to_id(pad)
        if tid is None:
            raise TokenizerUnavailable(
                f"{self.config_dir} 的 tokenizer.json 中没有 pad token {pad!r}")
        return int(tid), pad

    def _read_eos_token(self) -> int | None:
        """The special token the post-processor appends last, if any.

        Not ``tokenizer_config.json``'s ``eos_token``: Qwen3-Embedding's config
        says ``<|im_end|>`` (151645), while its ``tokenizer.json`` template
        appends ``<|endoftext|>`` (151643) -- and the template is what actually
        runs. Reading the config would therefore drop the wrong token.

        Derived from behaviour instead of parsing the template: encode two
        ids' worth of text and take the trailing special token, which is the one
        truncation has to preserve.
        """
        ids = self._tok.encode("a").ids
        for token in reversed(ids):
            if self._tok.id_to_token(token) in self._special_tokens:
                return int(token)
        return None

    # -- the two reference modes -----------------------------------------
    def _truncate(self, ids: list[int]) -> list[int]:
        """Cut to SEQLEN the way ``enable_truncation`` does -- keeping the EOS.

        ``tokenizers`` truncation runs *before* the post-processor, so the
        template's trailing special token is still appended and the result is
        ``ids[:n-1] + [eos]``, not ``ids[:n]``. That trailing ``<|endoftext|>``
        is not cosmetic: it is the token whose hidden state last-token pooling
        reads, so cutting it off would embed the position *before* the end of
        the text -- correct for every short input and wrong for every long one.
        Reproduced by hand here because this object must not enable truncation
        (see ``__init__``: the untruncated length is needed too).
        """
        n = self.seq_len
        if len(ids) <= n:
            return ids
        if self.eos_token_id is None:
            return ids[:n]
        return ids[: n - 1] + [self.eos_token_id]

    def encode_single(self, text: str) -> list[int]:
        """Ids for one text, truncated to SEQLEN (embedding's mode)."""
        return self.encode_single_full(text)[0]

    def encode_single_full(self, text: str) -> tuple[list[int], int]:
        """``(ids truncated to SEQLEN, the untruncated token count)``.

        The pair exists because the two facts are needed at once and must come
        from one encode: the caller needs the ids to run the model *and* the
        real length to decide whether the text fits at all. Inferring the length
        from the byte count is wrong by a factor of five for Chinese text
        (2701 tokens for 13500 UTF-8 bytes), so a byte-based check refuses
        inputs that would have been fine.
        """
        ids = list(self._tok.encode(text).ids)
        return self._truncate(ids), len(ids)

    def encode_pair(self, query: str, document: str) -> tuple[list[int], list[int], list[int]]:
        """ids / attention mask / position ids for one (query, document) pair.

        Right-padded to exactly SEQLEN, which is what ``padding="max_length"``
        produces and what the block graphs' static shape requires.
        """
        ids, mask, pos, _ = self.encode_pair_full(query, document)
        return ids, mask, pos

    def encode_pair_full(self, query: str, document: str
                         ) -> tuple[list[int], list[int], list[int], int]:
        """``encode_pair`` plus the untruncated length (see encode_single_full)."""
        n = self.seq_len
        enc = self._tok.encode(query, document)
        raw_ids = list(enc.ids)
        real_len = len(raw_ids)
        ids = raw_ids[:n]
        mask = list(enc.attention_mask)[:n]
        ids += [self.pad_token_id] * (n - len(ids))
        mask += [0] * (n - len(mask))
        return ids, mask, self.position_ids(ids), real_len

    def position_ids(self, ids: list[int]) -> list[int]:
        """XLM-R position ids, exactly as the reference pipeline computes them.

        Padding positions take ``pad_id`` (whose embedding row is zero, so they
        contribute nothing), and every real token counts up from ``pad_id + 1``
        -- the sentencepiece offset XLM-R is trained with. Right padding means
        this is a prefix of the counting sequence followed by pad ids.
        """
        pad = self.pad_token_id
        out = [0] * len(ids)
        pos = pad + 1
        for i, token in enumerate(ids):
            if token != pad:
                out[i] = pos
                pos += 1
            else:
                out[i] = pad
        return out

    def token_count(self, ids: list[int]) -> int:
        """Real (non-pad) token count, i.e. what the reference reports."""
        return sum(1 for t in ids if t != self.pad_token_id)
