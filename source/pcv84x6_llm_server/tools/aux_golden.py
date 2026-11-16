#!/usr/bin/env python3
"""Generate tests/data/aux_token_golden.json from the reference tokenizer.

The reference is HF ``transformers``' ``AutoTokenizer`` over the SAME
``tokenizer.json`` the service ships -- which is the only way to state "our
tokenisation matches the demo's" without trusting our own code to say so.

Run it on a machine that has transformers (13.24 does):

    /home/zzt/workspace/venv-ultra/bin/python tools/aux_golden.py

It reads the configs from ``model-config/`` (the copies this repository ships,
which are byte-identical to LLM-TPU's ``models/*/config/``), so regenerating
after a config bump produces a golden that matches the new files.

The corpus is deliberately awkward: mixed Chinese/English, emoji, whitespace
runs, a text that is one character, and texts long enough to hit truncation.
A golden built from tidy ASCII would pass even with several tokenizer rules
wrong.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMBED_DIR = ROOT / "model-config" / "qwen3_embedding"
RERANK_DIR = ROOT / "model-config" / "bge_reranker_v2_m3"
OUT = ROOT / "tests" / "data" / "aux_token_golden.json"

#: The embedding model's SEQLEN in the bmodel this service ships. seq2048 since
#: MYS-2696 (was 8192); the bmodel is our own build, see
#: tools/embed/build_bmodel.sh. This number decides where the golden's ids are
#: truncated, so it has to move with the shipped bmodel or the "our tokenisation
#: matches the reference" test compares against a truncation nobody uses.
EMBED_SEQ_LEN = 2048
#: The reranker's SEQLEN in the bmodel this service ships.
RERANK_SEQ_LEN = 2048

#: The instruction the reference pipeline puts in front of a *query*.
DEFAULT_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery: "
)

EMBED_TEXTS = [
    "What is deep learning?",
    "Deep learning is a subset of machine learning",
    "The weather is nice today",
    "Neural networks have many layers",
    "什么是深度学习？",
    "深度学习是机器学习的一个子集。",
    "今天天气不错",
    "神经网络有很多层",
    "Sophgo CV84X6 是一款边缘推理芯片，支持 bf16 和 int8 量化。",
    "A mixed 中英文 sentence with 标点，and a trailing space ",
    "  leading whitespace and a newline\nsecond line",
    "tab\tseparated\tvalues",
    "emoji 😀🚀🧠 and symbols ∑∫√",
    "1234567890 !@#$%^&*()_+-=[]{}|;:'\",.<>/?",
    "A",
    "的",
    "🙂",
    "",
    "a" * 100,
    "同" * 100,
    "Repeat the same token many times: " + "token " * 200,
    "Qwen3-Embedding-0.6B 支持 MRL 截断，从 1024 维截到 32 维。",
    "line1\nline2\nline3\n",
    "URLs: https://github.com/sophgo/LLM-TPU/tree/main/models/Qwen3_Embedding",
    "email@example.com and +86-138-0000-0000",
    "MixedCase AND UPPERCASE and lowercase",
    "numbers 3.14159 2.71828 1e-9 0x1F",
    "The quick brown fox jumps over the lazy dog.",
    "　　全角空格与、顿号；“引号”",
    "multi   spaces    between     words",
    "Very long English text: " + ", ".join(f"item{i}" for i in range(120)),
    "日本語のテキスト、ハングル도 섞어서",
    # Longer than SEQLEN, so these two exercise truncation. Written as
    # space-separated words rather than a repeated character: Qwen's BPE folds a
    # run of one character into a merge, so `"a" * 9000` is only ~1100 tokens.
    " ".join(f"w{i}" for i in range(EMBED_SEQ_LEN + 500)),
]

#: (query, document) pairs for the reranker's pair encoding.
RERANK_PAIRS = [
    ("what is panda?", "The giant panda is a bear species endemic to China."),
    ("what is panda?", "hi"),
    ("What is deep learning?", "Deep learning is a subset of machine learning."),
    ("什么是深度学习？", "深度学习是机器学习的一个子集。"),
    ("天气怎么样", "今天天气不错，适合出门。"),
    ("capital of France", "Paris is the capital and largest city of France."),
    ("empty-ish query", "x"),
    ("emoji 😀", "emoji 😀 and text"),
    ("same", "same"),
    ("long document", "word " * 400),
    ("混合语言 mixed", "Mixed 中英文 document 文档 with punctuation，标点。"),
    ("", "an empty query is legal at the tokenizer level"),
    ("   ", "whitespace-only query"),
    ("numbers", "3.14159 2.71828 1e-9"),
    ("truncation", "a" * 3000),   # longer than SEQLEN: exercises truncation
]


def _position_ids(ids: list[int], pad_id: int) -> list[int]:
    """XLM-R position ids, exactly as the reference pipeline derives them."""
    out = []
    pos = pad_id + 1
    for token in ids:
        if token != pad_id:
            out.append(pos)
            pos += 1
        else:
            out.append(pad_id)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    from transformers import AutoTokenizer  # only on a host with transformers

    embed = AutoTokenizer.from_pretrained(str(EMBED_DIR), trust_remote_code=True,
                                          padding_side="left")
    rerank = AutoTokenizer.from_pretrained(str(RERANK_DIR), trust_remote_code=True)

    embed_cases = []
    for text in EMBED_TEXTS:
        ids = embed(text, truncation=True, max_length=EMBED_SEQ_LEN).input_ids
        embed_cases.append({"text": text, "ids": ids})
    # The query form the reference actually uses: instruction + text.
    for text in EMBED_TEXTS[:4]:
        combined = DEFAULT_INSTRUCTION + text
        ids = embed(combined, truncation=True, max_length=EMBED_SEQ_LEN).input_ids
        embed_cases.append({"text": combined, "instruction": True, "ids": ids})

    pad_id = rerank.pad_token_id
    rerank_cases = []
    for query, document in RERANK_PAIRS:
        enc = rerank([[query, document]], padding="max_length", truncation=True,
                     max_length=RERANK_SEQ_LEN, return_tensors="np")
        ids = enc["input_ids"][0].astype("int32").tolist()
        mask = enc["attention_mask"][0].astype("int32").tolist()
        rerank_cases.append({
            "query": query,
            "document": document,
            "ids": ids,
            "attention_mask": mask,
            "position_ids": _position_ids(ids, pad_id),
        })

    payload = {
        "note": (
            "Generated by tools/aux_golden.py from HF transformers' AutoTokenizer "
            "over model-config/*/tokenizer.json -- the reference the demos use. "
            "Do not hand-edit; regenerate."
        ),
        "instruction": DEFAULT_INSTRUCTION,
        "embedding": {"seq_len": EMBED_SEQ_LEN, "cases": embed_cases},
        "rerank": {"seq_len": RERANK_SEQ_LEN, "pad_id": pad_id,
                   "cases": rerank_cases},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, "
          f"{len(embed_cases)} embedding + {len(rerank_cases)} rerank cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
