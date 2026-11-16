#!/usr/bin/env python3
"""Compare an embedding bmodel against another one, and time it, on the board.

Two questions, one tool, because both need the same thing: a forward through
``libcv84x6_llm.so`` with a real tokenizer in front of it.

**Precision.** P1 replaces the shipped seq8192 build with seq2048. Padding is
masked, so the same text through both builds must produce the same vector; the
acceptance bar is cosine >= 0.999 on every one of >= 20 mixed Chinese/English
inputs spanning 10..1900 tokens. This tool embeds each text through both models
and prints per-text cosine plus the minimum.

**Latency.** seq8192 runs a fixed 8192 positions per forward no matter how short
the input; seq2048 runs 2048. That is the whole reason for P1, so the tool also
reports the median of N single-text calls and one 4-text batch, per model.

    # on the board, inside the installed layout
    python3 cmp_models.py --lib lib/libcv84x6_llm.so \\
        --config model-config/qwen3_embedding \\
        --model old=…seq8192….bmodel --model new=…seq2048….bmodel \\
        --repeats 10 --json out.json

Only ``libcv84x6_llm.so`` and a tokenizer directory are needed: the embedding
engine has no session state, so nothing else from the service is involved and
the measurement is not coloured by the HTTP layer.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import statistics
import sys
import time

#: The corpus. Deliberately mixed and deliberately spread over the token range
#: the acceptance criterion names (10..1900): a comparison run only on tidy
#: short English would not exercise the padding mask, and one only on long
#: inputs would not catch a broken short path.
CORPUS: list[tuple[str, str]] = [
    ("short-zh", "深度学习是机器学习的一个分支。"),
    ("short-en", "Deep learning is a subset of machine learning."),
    ("short-mixed", "TPU 的 SEQLEN 决定单次前向的算量。"),
    ("digits", "2026 年 11 月 8 日，版本 0.6.29，端口 8000。"),
    ("punct", "问题：为什么要改 seq？回答：因为 8192 太慢！"),
    ("one-char", "嵌"),
    ("emoji", "部署完成 ✅ 接下来跑精度对比 🚀"),
    ("en-sentence", "Retrieval augmented generation combines a vector index with a "
                    "language model, so an answer can cite the passage it came from."),
    ("zh-paragraph",
     "知识库的切片目标长度是四百字，重叠六十个字。切片按句子边界切分，"
     "因此相邻两片之间共享的是一句完整的话，而不是从中间截断的半句。"
     "如果一句话本身超过目标长度，它会被整句保留；只有超过硬上限时才会按字符切开。"),
    ("en-paragraph",
     "A bmodel compiled for a fixed sequence length computes every position of "
     "that length on each forward pass, regardless of how many tokens the input "
     "actually contains. Padding positions are masked out of the attention, so "
     "the embedding of a short text does not change when the compiled length "
     "changes; only the time it takes to compute it does."),
    ("zh-table",
     "模型\t维度\t耗时\nEmbedding\t1024\t2.8 s\nReranker\t1\t0.32 s\n"),
    ("code", "def embed(texts):\n    return [model.encode(t) for t in texts]\n"),
    ("url", "https://github.com/zzttzzmyswy/cv84x6-llm-server/blob/main/docs/kb-app.md"),
    ("numbers", "3.14159 271828 161803 141421 173205 223606 244948 264575"),
    ("zh-long",
     "向量检索的第一步是把查询和文档都编码成向量，然后用余弦相似度排序。"
     "第二步是用重排序模型对前若干条候选重新打分，因为双塔模型的召回率高但精度有限。"
     "两步之间共享的候选数量决定了整体延迟：候选越多，重排序越慢，但漏掉正确答案的概率越低。"
     "实践中的折中是取前一百条候选，这在演示数据上把召回率保持在九成以上，"
     "同时让一次检索的总耗时控制在一分钟以内。"),
    ("en-long",
     "The service keeps one worker process per model. A worker loads its bmodel "
     "once and serves requests one at a time, because the device has a single "
     "NPU and two concurrent forwards on it would simply queue inside the driver "
     "anyway. What the worker does control is admission: a request that would "
     "exceed the model's queue depth is refused immediately with a 429 rather "
     "than waiting behind an unbounded backlog, so a client learns quickly that "
     "it should back off."),
    ("mixed-long",
     "混合负载下，Embedding 每条请求占用 TPU 约二点八秒。这个数字来自一个静态 "
     "seq8192 的图：无论输入只有十个 token 还是八千个 token，一次前向都要把 "
     "8192 个位置全部算完。The linear layers scale with the sequence length and "
     "the attention scales with its square, so shortening the compiled length "
     "from 8192 to 2048 cuts the work by roughly a factor of four in the linear "
     "part and by sixteen in the attention part."),
    ("zh-800",
     "在嵌入式设备上部署大模型，内存是最先遇到的约束。权重、神经元工作区和输入输出缓冲"
     "三者相加构成静态占用，会话的 KV 缓存和前缀缓存则在其上浮动。服务在加载前先读 "
     "bmodel 的元信息估算静态占用，加载后再用设备堆的差值校准，两者都保守取大。"
     "这样做的原因是估算会低估某些只在首次请求时才映射的分级模型，而低估会导致加载成功"
     "但随后的一次请求把堆撑爆。把一个模型的内存上限拆成静态与运行时两部分，"
     "好处是运行时的那部分可以随并发数调整，而不必让每个模型都预留最坏情况。"),
    ("en-1200",
     " ".join([
        "Retrieval systems fail in two different ways and the fixes are not the same.",
        "The first is a recall failure: the passage that answers the question was "
        "never returned, so no amount of reranking will recover it. The usual "
        "cause is a chunking scheme that cut the answer in half, or an embedding "
        "that was computed over a prefix of the text.",
        "The second is a precision failure: the right passage was returned but "
        "ranked below several plausible-looking neighbours. That is what a "
        "cross-encoder is for, and it is why a two-stage pipeline is standard.",
        "Both failures get worse when the compiled sequence length is much larger "
        "than the text, because an over-long forward pass does not merely cost "
        "time; it also tempts an implementer to truncate instead of refusing.",
    ])),
    ("zh-nospace-long",
     "本段没有标点也没有空格因此切片器无法在其中找到任何句子边界" * 12),
]

#: Long entries, assembled from the material above rather than invented, so the
#: 228..1900-token band is covered by text that tokenises like real prose. A
#: single sentence repeated would compress in the tokenizer and understate the
#: work; these rotate through distinct sentences at three different join styles.
_LONG_SOURCES = [
    "知识库的切片目标长度是四百字，重叠六十个字。切片按句子边界切分，因此相邻两片之间共享的是一句完整的话。",
    "如果一句话本身超过目标长度，它会被整句保留；只有超过硬上限时才会按字符切开。",
    "A bmodel compiled for a fixed sequence length computes every position on each forward pass.",
    "Padding positions are masked out of the attention, so the embedding does not change.",
    "向量检索先用余弦相似度排序，再用重排序模型对候选重新打分。",
    "The service keeps one worker per model, and a worker serves requests one at a time.",
    "在嵌入式设备上部署大模型，内存是最先遇到的约束。",
    "The linear layers scale with sequence length and the attention scales with its square.",
]


def _long_text(sentences: int, joiner: str) -> str:
    """``sentences`` rotating source sentences joined by ``joiner``."""
    parts = [_LONG_SOURCES[i % len(_LONG_SOURCES)] for i in range(sentences)]
    return joiner.join(parts)


CORPUS.extend([
    ("long-zh-600", _long_text(20, "")),
    ("long-en-900", _long_text(26, " ")),
    ("long-mixed-1300", _long_text(40, "")),
    ("long-mixed-1900", _long_text(90, " ")),
])


class Lib:
    """The handful of C entry points this tool needs."""

    def __init__(self, path: str):
        self.lib = ctypes.CDLL(path)
        L = self.lib
        L.cv_embed_create.restype = ctypes.c_void_p
        L.cv_embed_create.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_char_p)]
        L.cv_embed_destroy.argtypes = [ctypes.c_void_p]
        L.cv_embed_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_int)]
        L.cv_embed_forward.restype = ctypes.c_int
        L.cv_embed_forward.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.POINTER(ctypes.c_char_p)]
        L.llm_tokenizer_load.restype = ctypes.c_void_p
        L.llm_tokenizer_load.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)]
        L.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
        L.llm_tokenizer_encode.restype = ctypes.c_int
        # `int llm_tokenizer_encode(tok, text, int *out, int cap, const char **err)`
        # returns the token count itself; there is no count out-parameter.
        L.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                           ctypes.POINTER(ctypes.c_int), ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_char_p)]

    def _err(self, err) -> str:
        return err.value.decode() if err.value else "unknown error"

    def open_model(self, path: str):
        err = ctypes.c_char_p()
        h = self.lib.cv_embed_create(path.encode(), 0, ctypes.byref(err))
        if not h:
            raise RuntimeError("cv_embed_create(%s): %s" % (path, self._err(err)))
        seq = ctypes.c_int()
        hidden = ctypes.c_int()
        self.lib.cv_embed_info(h, ctypes.byref(seq), ctypes.byref(hidden))
        return h, seq.value, hidden.value

    def open_tokenizer(self, tokenizer_json: str):
        err = ctypes.c_char_p()
        tok = self.lib.llm_tokenizer_load(tokenizer_json.encode(), ctypes.byref(err))
        if not tok:
            raise RuntimeError("llm_tokenizer_load: %s" % self._err(err))
        return tok

    def encode(self, tok, text: str) -> list[int]:
        # The API fills a caller buffer and returns the FULL length; when the
        # buffer is too small it writes `cap` ids and still returns the needed
        # count, so size once from the return value and encode again.
        cap = 65536
        out = (ctypes.c_int * cap)()
        err = ctypes.c_char_p()
        n = self.lib.llm_tokenizer_encode(tok, text.encode(), out, cap,
                                          ctypes.byref(err))
        if n < 0:
            raise RuntimeError("llm_tokenizer_encode: %s" % self._err(err))
        if n > cap:
            cap = n
            out = (ctypes.c_int * cap)()
            n = self.lib.llm_tokenizer_encode(tok, text.encode(), out, cap,
                                              ctypes.byref(err))
            if n < 0:
                raise RuntimeError("llm_tokenizer_encode: %s" % self._err(err))
        return [out[i] for i in range(n)]

    def forward(self, h, ids: list[int], dim: int) -> list[float]:
        arr = (ctypes.c_int * len(ids))(*ids)
        out = (ctypes.c_float * dim)()
        err = ctypes.c_char_p()
        rc = self.lib.cv_embed_forward(h, arr, len(ids), dim, out, ctypes.byref(err))
        if rc != 0:
            raise RuntimeError("cv_embed_forward (n=%d): %s" % (len(ids), self._err(err)))
        return list(out)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True, help="libcv84x6_llm.so")
    ap.add_argument("--config", required=True,
                    help="tokenizer dir (the qwen3_embedding config directory)")
    ap.add_argument("--model", action="append", required=True,
                    metavar="NAME=PATH", help="repeatable; first is the reference")
    ap.add_argument("--repeats", type=int, default=10,
                    help="single-text timing repeats (median is reported)")
    ap.add_argument("--skip-timing", action="store_true")
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv[1:])

    models: list[tuple[str, str]] = []
    for spec in args.model:
        if "=" not in spec:
            ap.error("--model expects NAME=PATH, got %r" % spec)
        name, path = spec.split("=", 1)
        models.append((name, path))

    lib = Lib(args.lib)
    tok = lib.open_tokenizer(os.path.join(args.config, "tokenizer.json"))

    encoded = [(name, text, lib.encode(tok, text)) for name, text in CORPUS]
    print("== corpus: %d texts, %d..%d tokens" % (
        len(encoded), min(len(e[2]) for e in encoded), max(len(e[2]) for e in encoded)))

    handles = {}
    for name, path in models:
        h, seq, hidden = lib.open_model(path)
        handles[name] = (h, seq, hidden)
        print("== %s: seq=%d hidden=%d  %s" % (name, seq, hidden, os.path.basename(path)))

    ref_name = models[0][0]
    ref_h, ref_seq, ref_hidden = handles[ref_name]

    # -- precision ---------------------------------------------------------
    print("\n== precision (cosine vs %s)" % ref_name)
    per_text = []
    for name, text, ids in encoded:
        vecs = {}
        for mname, (h, seq, hidden) in handles.items():
            if len(ids) > seq:
                vecs[mname] = None  # over this build's limit; skip, do not truncate
            else:
                vecs[mname] = lib.forward(h, ids, hidden)
        row = {"text": name, "tokens": len(ids), "cos": {}}
        for mname, v in vecs.items():
            if mname == ref_name:
                continue
            row["cos"][mname] = (None if v is None or vecs[ref_name] is None
                                 else cosine(vecs[ref_name], v))
        per_text.append(row)
        cols = "  ".join("%s=%s" % (m, "n/a" if c is None else "%.7f" % c)
                         for m, c in row["cos"].items())
        print("  %-18s %5d tok  %s" % (name, len(ids), cols))

    mins = {}
    for mname in handles:
        if mname == ref_name:
            continue
        vals = [r["cos"][mname] for r in per_text if r["cos"][mname] is not None]
        mins[mname] = min(vals) if vals else None
        print("  min cosine(%s, %s) = %.7f over %d texts" % (
            ref_name, mname, mins[mname] if vals else float("nan"), len(vals)))

    # -- latency -----------------------------------------------------------
    timing = {}
    if not args.skip_timing:
        print("\n== latency (one forward = one text unless stated)")
        # A short, a mid and a long text, so the per-text cost is visible and
        # the median is not dominated by one length.
        by_name = {name: ids for name, _, ids in encoded}
        picks = ["short-en", "en-sentence", "en-long"]
        for mname, (h, seq, hidden) in handles.items():
            entry = {"seq": seq, "single": {}, "batch4": None}
            for pick in picks:
                ids = by_name[pick][:seq]
                times = []
                for _ in range(args.repeats):
                    t0 = time.perf_counter()
                    lib.forward(h, ids, hidden)
                    times.append((time.perf_counter() - t0) * 1000.0)
                entry["single"][pick] = {
                    "tokens": len(ids),
                    "median_ms": round(statistics.median(times), 1),
                    "min_ms": round(min(times), 1),
                    "all_ms": [round(t, 1) for t in times],
                }
                print("  %-6s %-12s n=%4d  median %7.1f ms   min %7.1f ms" % (
                    mname, pick, len(ids), entry["single"][pick]["median_ms"],
                    entry["single"][pick]["min_ms"]))
            batch = [by_name[p][:seq] for p in picks] + [by_name["short-zh"][:seq]]
            t0 = time.perf_counter()
            for ids in batch:
                lib.forward(h, ids, hidden)
            entry["batch4"] = round((time.perf_counter() - t0) * 1000.0, 1)
            print("  %-6s 4-text batch   total %7.1f ms" % (mname, entry["batch4"]))
            timing[mname] = entry

    result = {
        "reference": ref_name,
        "corpus": [{"text": n, "tokens": len(ids)} for n, _, ids in encoded],
        "per_text": per_text,
        "min_cosine": mins,
        "timing": timing,
        "models": {n: {"seq": s, "hidden": hd, "path": p}
                   for (n, p), (h, s, hd) in zip(models, handles.values())},
    }
    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n== wrote %s" % args.json)

    verdict = [m for m, v in mins.items() if v is not None and v < 0.999]
    print("\n== precision bar (>= 0.999): %s" % ("PASS" if not verdict else
                                                "FAIL for " + ", ".join(verdict)))
    return 0 if not verdict else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
