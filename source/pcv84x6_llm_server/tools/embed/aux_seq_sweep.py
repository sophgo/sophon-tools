#!/usr/bin/env python3
"""Time and check an embedding or rerank bmodel at each input length, on the board.

MYS-2702 compares three ways of serving the two auxiliary text models:

    A. one dynamic-shape bmodel, maximum length 8192;
    B. several static bmodels at different lengths, picked per request;
    C. the shipped static 2048 (the baseline).

Answering that needs one number per (build, input length) that is measured the
same way in all three cases, plus a precision check against a reference build.
``cmp_models.py`` next to this file does the first of those for *two* embedding
builds and only at three fixed corpus lengths; this tool does it for any number
of builds, both model kinds, and an exact length grid.

    # on the board
    python3 aux_seq_sweep.py --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --kind embed --config /opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding \\
        --model static2048=/data/.../*seq2048*.bmodel \\
        --model dynamic8192=/data/.../*seq8192*bm1684x2_4core_dynamic*.bmodel \\
        --model static512=/data/.../*seq512*.bmodel \\
        --repeats 10 --json /data/mys2702/embed.json

Every timing is the median of ``--repeats`` whole forwards through
``libcv84x6_llm.so`` -- one text, tokenised then embedded, i.e. the same call
the worker makes -- and the harness also reports the *first* forward separately,
because a dynamic graph that pays a one-off cost the first time it sees a length
would otherwise hide that cost inside the median.

Precision is the minimum cosine (embed) or the maximum absolute logit
difference (rerank) against the build named by ``--reference``, over the same
texts. For rerank the inputs are (query, document) pairs, and both the query and
the document length are varied, because that is what the padding costs depend on.
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

#: The length grid the issue asks for, in tokens. A build whose compiled length
#: is below an entry cannot serve it; that is reported as "n/a", never by
#: truncating, because truncation would silently change the subject.
GRID = (64, 256, 512, 1024, 2048, 4096, 8192)

#: Filler sentences, rotated and repeated to reach a requested token count. They
#: are written as prose in three languages so the tokenizer's compression is
#: realistic: repeating one short sentence would compress and understate the
#: work a real document of that length costs.
FILLER = [
    "知识库的切片目标长度是四百字，重叠六十个字。切片按句子边界切分，因此相邻两片之间共享的是一句完整的话，而不是从中间截断的半句。",
    "如果一句话本身超过目标长度，它会被整句保留；只有超过硬上限时才会按字符切开。这样做的好处是每条向量描述的都是完整的语义单元。",
    "向量检索先用余弦相似度排序，再用重排序模型对候选重新打分，因为双塔模型的召回率高但精度有限。",
    "A bmodel compiled for a fixed sequence length computes every position of that length on each forward pass, regardless of how many tokens the input actually contains.",
    "Padding positions are masked out of the attention, so the embedding of a short text does not change when the compiled length changes; only the time it takes to compute it does.",
    "The service keeps one worker process per model, and a worker serves requests one at a time, because the device has a single NPU.",
    "在嵌入式设备上部署大模型，内存是最先遇到的约束。权重、神经元工作区和输入输出缓冲三者相加构成静态占用。",
    "Retrieval systems fail in two different ways and the fixes are not the same: a recall failure and a precision failure.",
]


def text_at_tokens(tok_encode, want: int, *, seed: int = 0,
                   cap: int | None = None) -> tuple[str, int]:
    """Filler prose that tokenises as close to ``want`` tokens as it can get.

    Built by appending rotated sentences until the encoded length reaches the
    target, so the caller gets a real text of the requested size rather than a
    number.

    ``cap`` bounds the result: sentences are appended only while the text stays
    at or below it. Without a cap the loop overshoots by up to one sentence,
    which is harmless for a 64-token target but fatal for an 8192-token one --
    the last point would then exceed every build's SEQLEN and measure nothing.
    When the cap binds, the result is the largest whole-sentence prefix that
    fits, and the caller reports the length it actually got.

    Returns ``(text, tokens)``.
    """
    limit = cap if cap is not None else float("inf")
    parts: list[str] = []
    index = seed
    best = ("", 0)
    while True:
        text = "".join(parts)
        got = tok_encode(text)
        if got > limit:
            return best          # the previous, still-fitting prefix
        best = (text, got)
        if got >= want:
            return best
        parts.append(FILLER[index % len(FILLER)])
        index += 1


class Lib:
    """The C entry points this tool needs, for both model kinds."""

    def __init__(self, path: str):
        self.lib = ctypes.CDLL(path)
        L = self.lib
        # -- embedding ------------------------------------------------------
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
        # -- rerank ---------------------------------------------------------
        L.cv_rerank_create.restype = ctypes.c_void_p
        L.cv_rerank_create.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_char_p)]
        L.cv_rerank_destroy.argtypes = [ctypes.c_void_p]
        L.cv_rerank_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int)]
        L.cv_rerank_forward.restype = ctypes.c_int
        L.cv_rerank_forward.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_float),
                                        ctypes.POINTER(ctypes.c_char_p)]
        # -- tokenizer ------------------------------------------------------
        L.llm_tokenizer_load.restype = ctypes.c_void_p
        L.llm_tokenizer_load.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)]
        L.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
        L.llm_tokenizer_encode.restype = ctypes.c_int
        L.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                           ctypes.POINTER(ctypes.c_int), ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_char_p)]

    def _err(self, err) -> str:
        return err.value.decode() if err.value else "unknown error"

    # -- embedding ----------------------------------------------------------
    def open_embed(self, path: str):
        err = ctypes.c_char_p()
        h = self.lib.cv_embed_create(path.encode(), 0, ctypes.byref(err))
        if not h:
            raise RuntimeError("cv_embed_create: %s" % self._err(err))
        seq, hidden = ctypes.c_int(), ctypes.c_int()
        self.lib.cv_embed_info(h, ctypes.byref(seq), ctypes.byref(hidden))
        return h, seq.value, hidden.value

    def embed(self, h, ids: list[int], dim: int) -> list[float]:
        arr = (ctypes.c_int * len(ids))(*ids)
        out = (ctypes.c_float * dim)()
        err = ctypes.c_char_p()
        rc = self.lib.cv_embed_forward(h, arr, len(ids), dim, out, ctypes.byref(err))
        if rc != 0:
            raise RuntimeError("cv_embed_forward (n=%d): %s" % (len(ids), self._err(err)))
        return list(out)

    # -- rerank -------------------------------------------------------------
    def open_rerank(self, path: str):
        err = ctypes.c_char_p()
        h = self.lib.cv_rerank_create(path.encode(), 0, ctypes.byref(err))
        if not h:
            raise RuntimeError("cv_rerank_create: %s" % self._err(err))
        seq, hidden = ctypes.c_int(), ctypes.c_int()
        self.lib.cv_rerank_info(h, ctypes.byref(seq), ctypes.byref(hidden))
        return h, seq.value, hidden.value

    def rerank(self, h, ids, pos, mask) -> float:
        n = len(ids)
        i_a = (ctypes.c_int * n)(*ids)
        p_a = (ctypes.c_int * n)(*pos)
        m_a = (ctypes.c_int * n)(*mask)
        out = ctypes.c_float(0.0)
        err = ctypes.c_char_p()
        rc = self.lib.cv_rerank_forward(h, i_a, p_a, m_a, ctypes.byref(out),
                                        ctypes.byref(err))
        if rc != 0:
            raise RuntimeError("cv_rerank_forward: %s" % self._err(err))
        return float(out.value)

    # -- tokenizer ----------------------------------------------------------
    def open_tokenizer(self, tokenizer_json: str):
        err = ctypes.c_char_p()
        tok = self.lib.llm_tokenizer_load(tokenizer_json.encode(), ctypes.byref(err))
        if not tok:
            raise RuntimeError("llm_tokenizer_load: %s" % self._err(err))
        return tok

    def encode(self, tok, text: str) -> list[int]:
        cap = 1 << 16
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


class HFTokenizer:
    """The model's own tokenizer, for the pair encoding rerank needs.

    ``llm_tokenizer_encode`` is the Qwen chat vocabulary and cannot tokenise
    XLM-R's sentencepiece model at all, so rerank goes through HF ``tokenizers``
    on the model's ``tokenizer.json`` -- exactly what ``app/engine/aux_tok.py``
    does, including the XLM-R position-id rule (padding -> pad id, real tokens
    counting up from ``pad_id + 1``).
    """

    def __init__(self, config_dir: str):
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(config_dir, "tokenizer.json"))
        path = os.path.join(config_dir, "tokenizer_config.json")
        pad = "<pad>"
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                pad = json.load(f).get("pad_token") or pad
        self.pad_token = pad
        tid = self.tok.token_to_id(pad)
        if tid is None:
            raise RuntimeError("%s has no pad token %r" % (config_dir, pad))
        self.pad_id = int(tid)

    def encode_pair(self, query: str, document: str, seq_len: int):
        """``(ids, mask, position_ids, real_len)`` padded to ``seq_len``."""
        enc = self.tok.encode(query, document)
        ids = list(enc.ids)[:seq_len]
        mask = list(enc.attention_mask)[:seq_len]
        real = len(enc.ids)
        ids += [self.pad_id] * (seq_len - len(ids))
        mask += [0] * (seq_len - len(mask))
        return ids, mask, self.position_ids(ids), real

    def position_ids(self, ids: list[int]) -> list[int]:
        out = [0] * len(ids)
        pos = self.pad_id + 1
        for i, token in enumerate(ids):
            if token != self.pad_id:
                out[i] = pos
                pos += 1
            else:
                out[i] = self.pad_id
        return out


def _ms(entry: dict) -> str:
    """The median/min/first triple, or "not timed" when it was skipped."""
    if entry.get("median_ms") is None:
        return "not timed"
    return "median %8.1f ms  min %8.1f ms  first %8.1f ms" % (
        entry["median_ms"], entry["min_ms"], entry["first_ms"])


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def timed(fn, repeats: int) -> dict:
    """``fn`` run ``repeats`` times; the median, the min and the first call.

    The first call is reported on its own, not folded into the median: a
    dynamic graph may compile or allocate for a shape the first time it sees it,
    and a median of ten would report that once-in-ten cost as if it were free.
    """
    times = []
    first = None
    for i in range(repeats):
        t0 = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - t0) * 1000.0
        if i == 0:
            first = elapsed
        times.append(elapsed)
    return {"median_ms": round(statistics.median(times), 1),
            "min_ms": round(min(times), 1),
            "first_ms": round(first or 0.0, 1),
            "all_ms": [round(t, 1) for t in times]}


def sweep_embed(lib: Lib, args, tok, models) -> dict:
    """One forward per (build, length); precision against ``--reference``.

    **One model is loaded at a time.** Each of these builds costs 1.2-1.5 GiB of
    device heap, and the board has ~26 GiB shared with whatever else is loaded,
    so holding all of them at once is how the sweep would fail rather than
    finish. The reference's vectors are kept in host memory (7 lengths x 1024
    floats), which is all that is needed to compare later builds against it.
    """
    texts = {}
    for want in GRID:
        text, got = text_at_tokens(lambda t: len(lib.encode(tok, t)), want,
                                   seed=want, cap=want)
        texts[want] = (text, got)

    ref = args.reference
    result = {"kind": "embed", "reference": ref, "models": {}, "lens": {}}
    ref_vectors: dict[int, list[float]] = {}
    #: (length, model) -> vector, so the second pass can compute cosines without
    #: reloading anything. 7 lengths x 5 builds x 1024 floats is 140 KiB.
    vectors: dict[tuple[int, str], list[float]] = {}

    for name, path in models:
        h, seq, hidden = lib.open_embed(path)
        print("== %-14s seq=%-5d hidden=%-5d %s" % (
            name, seq, hidden, os.path.basename(path)))
        result["models"][name] = {"seq": seq, "hidden": hidden}
        for want, (text, got) in texts.items():
            if got > seq:
                result["lens"].setdefault(want, {"tokens": got})[name] = None
                continue
            ids = lib.encode(tok, text)
            vec = lib.embed(h, ids, hidden)
            vectors[(want, name)] = vec
            if name == ref:
                ref_vectors[want] = vec
            entry = ({"median_ms": None, "min_ms": None, "first_ms": None,
                      "all_ms": []} if name in args.skip_timing_for
                     else timed(lambda: lib.embed(h, ids, hidden), args.repeats))
            entry["cosine"] = None  # filled in below, once every build is measured
            result["lens"].setdefault(want, {"tokens": got})[name] = entry
            print("  %-14s %4d tok  %s" % (name, got, _ms(entry)))
        lib.lib.cv_embed_destroy(h)

    # Every build has now been measured; compare vectors while they are in hand.
    for want, row in result["lens"].items():
        ref_vec = ref_vectors.get(want)
        for name, entry in row.items():
            if not isinstance(entry, dict):
                continue
            vec = vectors.get((want, name))
            entry["cosine"] = (None if ref_vec is None or vec is None
                               else (1.0 if name == ref else cosine(ref_vec, vec)))
        for name, entry in row.items():
            if isinstance(entry, dict):
                print("  cos  %-14s %4d tok  %s" % (
                    name, row["tokens"],
                    "n/a" if entry["cosine"] is None else "%.7f" % entry["cosine"]))
    return result


def sweep_rerank(lib: Lib, args, hf, models) -> dict:
    """One forward per (build, *pair* length); logit error against ``--reference``.

    The grid is a **pair** length, not a document length, because a rerank
    forward pads ``[CLS] query [SEP] document [SEP]`` to SEQLEN and that one
    number is the cost. Sizing the document at 8192 with a 50-token query would
    overflow every build in the grid and measure nothing; sizing the *pair* at
    8192 asks the question the service actually faces -- can this build take a
    full-length pair at all.

    The query is a realistic one (a search query, well under 64 tokens), and the
    document is grown until the encoded pair reaches the wanted length.

    One model loaded at a time, for the same heap reason as ``sweep_embed``.
    """
    query = args.query or FILLER[0][:60]
    query_tokens = len(hf.tok.encode(query).ids)
    docs = {}
    for want in GRID:
        # Grow the document until query + document + 3 specials >= want.
        # Bounded by the grid maximum so the 8192 point lands at 8190 rather
        # than overshooting past every build's SEQLEN.
        text, _ = text_at_tokens(
            lambda t: query_tokens + len(hf.tok.encode(t).ids) + 3, want,
            seed=want + 1, cap=max(GRID))
        pair_len = len(hf.tok.encode(query, text).ids)
        docs[want] = (text, pair_len)

    ref = args.reference
    result = {"kind": "rerank", "reference": ref, "query": query,
              "query_tokens": query_tokens, "models": {}, "lens": {}}
    ref_logits: dict[int, float] = {}

    for name, path in models:
        h, seq, hidden = lib.open_rerank(path)
        print("== %-14s seq=%-5d %s" % (name, seq, os.path.basename(path)))
        result["models"][name] = {"seq": seq}
        for want, (doc, pair_len) in docs.items():
            ids, mask, pos, real = hf.encode_pair(query, doc, seq)
            if real > seq:
                result["lens"].setdefault(want, {"pair_tokens": pair_len})[name] = None
                continue
            logit = lib.rerank(h, ids, pos, mask)
            if name == ref:
                ref_logits[want] = logit
            entry = ({"median_ms": None, "min_ms": None, "first_ms": None,
                      "all_ms": []} if name in args.skip_timing_for
                     else timed(lambda: lib.rerank(h, ids, pos, mask), args.repeats))
            entry["logit"] = round(logit, 6)
            entry["real_len"] = real
            entry["logit_delta"] = None
            result["lens"].setdefault(want, {"pair_tokens": pair_len})[name] = entry
            print("  %-14s pair %5d tok  %s  logit %8.4f" % (
                name, pair_len, _ms(entry), logit))
        lib.lib.cv_rerank_destroy(h)

    for want, row in result["lens"].items():
        base = ref_logits.get(want)
        if base is None:
            continue
        for entry in row.values():
            if isinstance(entry, dict):
                entry["logit_delta"] = round(abs(entry["logit"] - base), 6)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True, help="libcv84x6_llm.so")
    ap.add_argument("--kind", choices=("embed", "rerank"), required=True)
    ap.add_argument("--config", required=True,
                    help="the model's config directory (holds tokenizer.json)")
    ap.add_argument("--model", action="append", required=True, metavar="NAME=PATH",
                    help="repeatable; load order matters only for memory")
    ap.add_argument("--reference", required=True,
                    help="which --model name is the precision reference")
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--skip-timing-for", action="append", default=[],
                    metavar="NAME", help="repeatable; still measured for precision")
    ap.add_argument("--query", help="rerank only: the query to pair with each "
                                    "document (default: the first filler sentence)")
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv[1:])

    models = []
    for spec in args.model:
        if "=" not in spec:
            ap.error("--model expects NAME=PATH, got %r" % spec)
        models.append(tuple(spec.split("=", 1)))
    names = [n for n, _ in models]
    if args.reference not in names:
        ap.error("--reference %r is not one of %s" % (args.reference, names))

    lib = Lib(args.lib)
    if args.kind == "embed":
        tok = lib.open_tokenizer(os.path.join(args.config, "tokenizer.json"))
        result = sweep_embed(lib, args, tok, models)
    else:
        hf = HFTokenizer(args.config)
        result = sweep_rerank(lib, args, hf, models)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n== wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
