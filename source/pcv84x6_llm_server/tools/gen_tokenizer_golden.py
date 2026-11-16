#!/usr/bin/env python3
"""Generate tests/tokenizer_golden.json from the Python `tokenizers` package.

The C++ tokenizer (native/src/tokenizer.cpp) replaces that package on the board,
so its output has to stay byte-identical. This script records what the reference
produces for a corpus that exercises every branch of the pre-tokenizer regex,
NFC, the added tokens and the byte-level alphabet.

    python3 tools/gen_tokenizer_golden.py <tokenizer.json> [out.json]

Run it with the same `tokenizers` version the models were converted with; the
version is stored in the file so a mismatch is visible rather than silent.
"""

from __future__ import annotations

import json
import sys

CASES = [
    # -- plain ASCII, the common path -------------------------------------
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
    # -- contractions: alternation 1 --------------------------------------
    "don't can't won't it's",
    "I'm you're we've they'll he'd",
    "DON'T CAN'T IT'S",
    "rock'n'roll",
    "'s",
    "'ll",
    "'re",
    # -- numbers: alternation 3 (one digit at a time) ----------------------
    "1234567890 3.14159 -42 0x1F",
    "2026-10-26T11:57:07+08:00",
    "abc123def",
    "١٢٣ arabic-indic digits",
    # -- punctuation: alternation 4 ----------------------------------------
    "Special chars: !@#$%^&*()_+-=[]{}|;':\",./<>?`~",
    "a-b_c",
    "x == y && z != w",
    "def f(x): return x**2  # comment",
    '{"json": [1, 2, {"k": "v"}]}',
    "https://example.com/path?q=1&r=2#frag",
    "...",
    "!!!???",
    "-",
    "\\n literal",
    # -- newlines & whitespace runs: alternations 5, 6, 7 -------------------
    "line1\nline2\r\nline3",
    "tabs\tand\tspaces",
    "\n",
    "\n\n\n",
    "\r\n",
    "trailing\n",
    "a\nb",
    "a \n b",
    "a   \n   b",
    "  \n  ",
    "\t\t\t",
    " \t\n \t\n",
    "word \n",
    "end   ",
    "mid   dle",
    # -- letters/marks: alternation 2 --------------------------------------
    "MixedCASE camelCase snake_case kebab-case",
    "e.g. i.e. etc. U.S.A.",
    # -- non-ASCII / NFC ---------------------------------------------------
    "你好，世界。",
    "日本語のテスト",
    "한글 테스트",
    "Ünïcödé àccents ñ ß Ø",
    "café",           # already NFC
    "café",     # decomposed e + combining acute: NFC folds to café
    "Ünïcödé",  # decomposed umlaut
    "Å ring",   # A + combining ring -> Å
    "간 decomposed hangul",
    " non-breaking space",
    "　ideographic space　",
    "emoji 😀🚀 test",
    "《书名》「引用」『双引』",
    "Qwen3.5-35B-A3B 在 CV84X6 上推理速度约 24 tok/s。",
    # -- added tokens ------------------------------------------------------
    "<|im_start|>user\nhi<|im_end|>\n",
    "<|im_start|>system\nYou are helpful.<|im_end|>\n<|im_start|>user\nWhy?<|im_end|>\n<|im_start|>assistant\n",
    "a<tool_call>b",
    "a<think>b",
    "</tool_call><tool_response>",
    "<|vision_start|><|image_pad|><|vision_end|>",
    "<|endoftext|>",
    # -- volume ------------------------------------------------------------
    "a" * 500,
    "测试" * 200,
    "word " * 300,
    "x" * 17 + "\n" + "y" * 17,
]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "tests/tokenizer_golden.json"

    import tokenizers
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(path)
    cases = []
    for text in CASES:
        ids = tok.encode(text, add_special_tokens=False).ids
        cases.append({
            "text": text,
            "ids": ids,
            # decode(encode(x)) differs from x only where NFC folded it, which
            # is exactly what we want pinned.
            "decoded_skip_special": tok.decode(ids, skip_special_tokens=True),
            "decoded_keep_special": tok.decode(ids, skip_special_tokens=False),
        })

    specials = {}
    for name in ("<|im_end|>", "<|im_start|>", "<|endoftext|>", "<|vision_start|>",
                 "<|vision_end|>", "<|image_pad|>", "<tool_call>", "<think>"):
        specials[name] = tok.token_to_id(name)

    payload = {
        "generated_by": "tools/gen_tokenizer_golden.py",
        "tokenizers_version": tokenizers.__version__,
        "tokenizer_json": path,
        "specials": specials,
        "cases": cases,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    total = sum(len(c["ids"]) for c in cases)
    print(f"wrote {out_path}: {len(cases)} cases, {total} token ids, "
          f"tokenizers {tokenizers.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
