#!/usr/bin/env python3
"""Generate the PaddleOCR-VL tokenizer golden, the C++ tokenizer's oracle.

``native/src/tokenizer.cpp`` replaces the Python ``tokenizers`` package on the
board for every model that needs a tokenizer. The Qwen family is pinned by
``tests/tokenizer_golden.json``; this is the same thing for PaddleOCR-VL-1.5,
whose tokenizer is a *different* algorithm (metaspace Replace instead of NFC, no
pre-tokenizer, byte fallback, ByteFallback decoding) and therefore needs its own
corpus: the Qwen file's cases would not exercise the branches that differ.

The cases are chosen from what this deployment actually encodes -- the chat
template's own literals, the four task prompts, OTSL markup and CJK -- plus the
cases where a byte fallback fires. Run it against the shipped tokenizer.json:

    python3 tools/gen_tokenizer_golden_paddleocr_vl.py \
        model-config/paddleocr_vl_1_5/tokenizer.json

The version of `tokenizers` that produced the file is recorded in it, so a
mismatch is visible rather than silent (the reference's own decoding of an
incomplete byte sequence is a rare place where versions have differed).
"""

from __future__ import annotations

import json
import sys

#: The literals the chat template writes, character for character. ``HEAD`` and
#: ``TAIL`` are what tools/ocr/vl_native_prep.py uses and what the board's
#: prompt rendering must reproduce; the ``Assistant:\\n`` newline is the one A3
#: recorded as load-bearing.
TEMPLATE_CASES = [
    "<|begin_of_sentence|>",
    "User: ",
    "<|IMAGE_START|>",
    "<|IMAGE_PLACEHOLDER|>",
    "<|IMAGE_END|>",
    "Assistant:\n",
    "</s>",
    "<|begin_of_sentence|>User: <|IMAGE_START|>",
    "<|IMAGE_END|>OCR:\nAssistant:\n",
    "<|IMAGE_END|>Table Recognition:\nAssistant:\n",
    "<|begin_of_sentence|>User: <|IMAGE_START|><|IMAGE_PLACEHOLDER|>"
    "<|IMAGE_END|>OCR:\nAssistant:\n",
    # The four official task prompts.
    "OCR:",
    "Table Recognition:",
    "Formula Recognition:",
    "Chart Recognition:",
]

OTSL_CASES = [
    "<fcel>", "<nl>", "<lcel>", "<ucel>", "<ecel>", "<xcel>",
    "<fcel>产线<fcel>产量（台）<fcel>合格率<fcel>负责人<nl>",
    "<fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>",
    "<fcel>2026年第三季度设备巡检记录<lcel><lcel><lcel><lcel><nl>",
    "<ucel><fcel>服务器B<fcel>2026-08-09<fcel>告警<fcel>李娜<nl>",
]

TEXT_CASES = [
    "",
    "Hello",
    "Hello, world!",
    "The capital of France is Paris.",
    "a",
    " ",
    "  ",
    "   leading",
    "trailing   ",
    "multi    spaces     here",
    "don't can't won't it's",
    "  two  spaces",
    "3.14",
    "2026-10-26T11:57:07+08:00",
    "abc123def",
    "line1\nline2\r\nline3",
    "tabs\tand\tspaces",
    "\n",
    "\n\n\n",
    "\r\n",
    "trailing\n",
    "a \n b",
    "word \n",
    "end   ",
    "mid   dle",
    "Special chars: !@#$%^&*()_+-=[]{}|;':\",./<>?`~",
    '{"json": [1, 2, {"k": "v"}]}',
    "https://example.com/path?q=1&r=2#frag",
    "你好，世界。",
    "日本語のテスト",
    "한글 테스트",
    "Ünïcödé àccents ñ ß Ø",
    "café",          # already NFC
    "café",    # decomposed: this tokenizer does NOT fold it
    "Ünïcödé",
    "Å ring",
    "간 decomposed hangul",
    " non-breaking space",
    "　ideographic space　",
    "emoji 😀🚀 test",
    "《书名》「引用」『双引』",
    "Qwen3.5-35B-A3B 在 CV84X6 上推理速度约 24 tok/s。",
    # -- byte fallback: characters the 100295-entry vocabulary does not hold ---
    # ``门簪`` is the case MYS-2496 found in the chat model: 门 is a token, 簪 is
    # three byte tokens. Its ids are what tells a working byte fallback from a
    # silent drop.
    "门簪",
    "龘",
    "🙂",
    "中文混合 English 和 123",
    # -- volume ---------------------------------------------------------------
    "a" * 500,
    "测试" * 200,
    "word " * 300,
    "<fcel>cell<fcel>cell<nl>" * 60,
]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = sys.argv[1]
    out_path = (sys.argv[2] if len(sys.argv) > 2
                else "tests/data/ocr/tokenizer_golden_paddleocr_vl.json")

    import tokenizers
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(path)
    cases = []
    for text in TEMPLATE_CASES + OTSL_CASES + TEXT_CASES:
        ids = tok.encode(text, add_special_tokens=False).ids
        cases.append({
            "text": text,
            "ids": ids,
            "decoded_skip_special": tok.decode(ids, skip_special_tokens=True),
            "decoded_keep_special": tok.decode(ids, skip_special_tokens=False),
        })

    specials = {}
    for name in ("<|IMAGE_PLACEHOLDER|>", "<|IMAGE_START|>", "<|IMAGE_END|>",
                 "<|begin_of_sentence|>", "</s>", "<unk>", "<fcel>", "<nl>",
                 "<lcel>", "<ucel>", "<ecel>", "<xcel>"):
        specials[name] = tok.token_to_id(name)

    payload = {
        "generated_by": "tools/gen_tokenizer_golden_paddleocr_vl.py",
        "tokenizers_version": tokenizers.__version__,
        "tokenizer_json": path,
        "specials": specials,
        "cases": cases,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print(f"{len(cases)} cases -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
