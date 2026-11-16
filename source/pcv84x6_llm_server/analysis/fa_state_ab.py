#!/usr/bin/env python3
"""A/B the FA state reset (MYS-2477) on the board.

A fresh prefill used to memset the ten FA layers' full 131072-slot K/V buffers
even though it then sets `history = 0`, so no FA slot belongs to the new
session. `activate()` now skips the FA buffers on that path and keeps clearing
them for `restore()` (see docs/DESIGN.md §3.6 for why that is sound).

Two .so builds cannot share a process -- each owns the NPU handle -- so this
tool runs against one build per invocation and writes JSON; `--compare` then
diffs the files. Two modes:

  --mode perf       time to first token, per prompt width, `--repeat` runs,
                    median plus spread, and the decoded text per width.
  --mode semantics  the lossless suite: multi-turn, restore over a session that
                    had a *longer* history, two sessions strictly alternating,
                    prefix-cache restore+extend, and a fresh prefill on a session
                    abandoned mid-conversation. Every scenario compares against
                    a same-build reference run of the same state, and prints the
                    generated text.

Real chat-templated prompts, real tokenizer, real decode: the tokens printed are
what a user would get from the model, and lm_head fuses argmax (no sampling), so
equal ids mean an equal answer. A token that differs between builds is a real
difference, not jitter.

    python3 analysis/fa_state_ab.py --mode perf --lib base/...so --model X.bmodel \\
        --tokenizer tokenizer.json --rows 64,256,2048 --repeat 5 --out base_perf.json
    python3 analysis/fa_state_ab.py --compare base_perf.json opt_perf.json

Watchdog: a launch that wedges the TPU never runs a Python signal handler, so
os._exit is the only thing that fires (analysis/README.md).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import statistics
import sys
import time

WATCHDOG_SECS = 900
EXIT_WATCHDOG = 3
_P = ctypes.POINTER

# The chat template the service uses (app/api/openai_api.build_prompt): thinking
# is off by default, so the pre-filled <think></think> block is empty and the
# model answers directly.
CHAT = ("<|im_start|>user\n{body}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def bind(path):
    lib = ctypes.CDLL(path)
    err = _P(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
    for name in ("num_layers", "context_length", "max_input_length", "hidden_size",
                 "supports_history"):
        fn = getattr(lib, f"llm_engine_{name}")
        fn.restype = ctypes.c_int
        fn.argtypes = [ctypes.c_void_p]
    lib.llm_engine_set_vocab_size.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, err]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_token_len.restype = ctypes.c_int
    lib.llm_session_token_len.argtypes = [ctypes.c_void_p]
    # prefill and extend take the same arguments; declaring argtypes is not
    # optional (without them ctypes truncates the id array to a C int).
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        _P(ctypes.c_int), ctypes.c_int, _P(ctypes.c_int),
        ctypes.c_int, _P(ctypes.c_int), _P(ctypes.c_int),
        _P(_P(ctypes.c_float)), _P(_P(ctypes.c_int)), _P(_P(ctypes.c_int)),
        _P(_P(ctypes.c_float)), err]
    lib.llm_session_extend.argtypes = lib.llm_session_prefill.argtypes
    lib.llm_session_extend.restype = ctypes.c_int
    lib.llm_session_decode.restype = ctypes.c_int
    lib.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_session_snapshot.restype = ctypes.c_void_p
    lib.llm_session_snapshot.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_session_restore.restype = ctypes.c_int
    lib.llm_session_restore.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, err]
    lib.llm_snapshot_free.restype = None
    lib.llm_snapshot_free.argtypes = [ctypes.c_void_p]
    # tokenizer (same .so)
    lib.llm_tokenizer_load.restype = ctypes.c_void_p
    lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
    lib.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
    lib.llm_tokenizer_encode.restype = ctypes.c_int
    lib.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                         _P(ctypes.c_int), ctypes.c_int, err]
    lib.llm_tokenizer_decode.restype = ctypes.c_int
    lib.llm_tokenizer_decode.argtypes = [ctypes.c_void_p, _P(ctypes.c_int),
                                         ctypes.c_int, ctypes.c_char_p,
                                         ctypes.c_int, ctypes.c_int, err]
    lib.llm_tokenizer_vocab_size.restype = ctypes.c_int
    lib.llm_tokenizer_vocab_size.argtypes = [ctypes.c_void_p]
    return lib


def watchdog_rearm(secs=WATCHDOG_SECS):
    signal.alarm(0)
    signal.alarm(secs)


def _alarm(signum, frame):
    sys.stderr.write(f"[ab] watchdog fired after {WATCHDOG_SECS}s; hard exit\n")
    sys.stderr.flush()
    os._exit(EXIT_WATCHDOG)


class Ctx:
    """One loaded engine, its tokenizer, and the shared ctypes plumbing."""

    def __init__(self, lib, eng, err, tok):
        self.lib = lib
        self.eng = eng
        self.err = err
        self.tok = tok

    # -- tokenizer ---------------------------------------------------------
    def encode(self, text):
        raw = text.encode()
        n = self.lib.llm_tokenizer_encode(self.tok, raw, None, 0, self.err)
        if n < 0:
            raise SystemExit(f"encode: {self.err.value}")
        buf = (ctypes.c_int * max(n, 1))()
        got = self.lib.llm_tokenizer_encode(self.tok, raw, buf, n, self.err)
        return list(buf[:got])

    def text(self, ids):
        arr = (ctypes.c_int * max(len(ids), 1))(*ids)
        n = self.lib.llm_tokenizer_decode(self.tok, arr, len(ids), None, 0, 1,
                                          self.err)
        if n < 0:
            raise SystemExit(f"decode: {self.err.value}")
        out = ctypes.create_string_buffer(n + 1)
        self.lib.llm_tokenizer_decode(self.tok, arr, len(ids), out, n + 1, 1,
                                      self.err)
        return out.value.decode("utf-8", "replace")

    def chat(self, body):
        return self.encode(CHAT.format(body=body))

    # -- engine ------------------------------------------------------------
    def session(self):
        s = self.lib.llm_session_new(self.eng, ctypes.byref(self.err))
        if not s:
            raise SystemExit(f"session_new: {self.err.value}")
        return s

    def tok_len(self, s):
        return self.lib.llm_session_token_len(s)

    def prefill(self, s, ids):
        n = len(ids)
        arr = (ctypes.c_int * n)(*ids)
        watchdog_rearm()
        t0 = time.perf_counter()
        rc = self.lib.llm_session_prefill(
            self.eng, s, arr, n, None, 0,
            None, None, None, None, None, None, ctypes.byref(self.err))
        dt = time.perf_counter() - t0
        if rc != 0:
            raise SystemExit(f"prefill({n}): {self.err.value}")
        return dt

    def extend(self, s, ids):
        """Append `ids` after the session's history with absolute positions."""
        n = len(ids)
        arr = (ctypes.c_int * n)(*ids)
        start = self.tok_len(s)
        pos = (ctypes.c_int * (3 * n))()
        for r in range(3):
            for i in range(n):
                pos[r * n + i] = start + i
        watchdog_rearm()
        rc = self.lib.llm_session_extend(
            self.eng, s, arr, n, pos, 0,
            None, None, None, None, None, None, ctypes.byref(self.err))
        if rc != 0:
            raise SystemExit(f"extend({n}) at {start}: {self.err.value}")

    def decode(self, s, k):
        """`k` decode calls; the first is the token prefill/extend sampled,
        handed back without touching the NPU."""
        out = []
        for _ in range(k):
            watchdog_rearm()
            t = self.lib.llm_session_decode(self.eng, s, ctypes.byref(self.err))
            if t < 0:
                raise SystemExit(f"decode: {self.err.value}")
            out.append(t)
        return out

    def snapshot(self, s):
        p = self.lib.llm_session_snapshot(self.eng, s, ctypes.byref(self.err))
        if not p:
            raise SystemExit(f"snapshot: {self.err.value}")
        return p

    def restore(self, s, snap):
        watchdog_rearm()
        rc = self.lib.llm_session_restore(self.eng, s, snap,
                                          ctypes.byref(self.err))
        if rc != 0:
            raise SystemExit(f"restore: {self.err.value}")

    def free(self, s):
        if s:
            self.lib.llm_session_free(s)


def pad_prompt(cx, body, target):
    """Grow `body` with real prose until the rendered chat prompt reaches
    `target` tokens. Real text, not filler ids: the model's routing and its
    answer are then representative, and the same text drives both builds."""
    filler = (" The history of this city is long and detailed, and each"
              " century added another layer to what people wrote about it.")
    ids = cx.chat(body)
    while len(ids) < target:
        body += filler
        ids = cx.chat(body)
    return ids


# ---------------------------------------------------------------------------
def run_perf(cx, args):
    ctx_len = cx.lib.llm_engine_context_length(cx.eng)
    widths = [int(x) for x in args.rows.split(",") if x.strip()]
    result = {"mode": "perf", "lib": args.lib, "repeat": args.repeat,
              "max_input": cx.lib.llm_engine_max_input_length(cx.eng),
              "context": ctx_len, "decode_tokens": args.decode,
              "prompt": args.prompt, "items": {}}
    for n in widths:
        if not 0 < n < ctx_len:
            raise SystemExit(f"refusing width {n} (context {ctx_len})")
        ids = pad_prompt(cx, args.prompt, n)
        samples, streams = [], []
        for _ in range(args.repeat):
            # A fresh session per run: the point is the *new session* cost, so
            # reusing one would measure a later prefill's cost instead.
            s = cx.session()
            try:
                dt = cx.prefill(s, ids)
                toks = cx.decode(s, args.decode)
            finally:
                cx.free(s)
            samples.append(dt)
            streams.append(toks)
        # Same input, same build, argmax-fused lm_head: a difference between
        # runs is nondeterminism, not noise, and would make the cross-build
        # comparison meaningless.
        if any(t != streams[0] for t in streams[1:]):
            raise SystemExit(f"width {n}: runs produced different tokens -- "
                             f"the build is not deterministic")
        result["items"][str(n)] = {
            "prompt_tokens": len(ids),
            "samples_ms": [round(x * 1000, 2) for x in samples],
            "median_ms": round(statistics.median(samples) * 1000, 2),
            "min_ms": round(min(samples) * 1000, 2),
            "max_ms": round(max(samples) * 1000, 2),
            "tokens": streams[0],
            "text": cx.text(streams[0]),
        }
        it = result["items"][str(n)]
        print(f"rows~{n:>6} ({len(ids)} ids) median={it['median_ms']:>10.2f} ms  "
              f"samples={it['samples_ms']}", flush=True)
        print(f"  tokens={','.join(str(t) for t in streams[0])}", flush=True)
        print(f"  text={it['text']!r}", flush=True)
    return result


def run_semantics(cx, args):
    """Token-stream equality scenarios, each against a same-build reference.

    Every scenario is chosen to break a specific way if an FA slot that should
    not be read is read:

    * multi_turn       -- extend after a live history: turn 2+ must see exactly
                          the previous turns' slots;
    * restore_over_longer -- the restore target is first given a LONGER history,
                          so slots past the snapshot are exactly the ones a
                          skipped clear would leave reachable;
    * alternating      -- two sessions share one set of resident buffers and B
                          fresh-prefills between A's decodes;
    * prefix_cache     -- snapshot a cut point, restore, extend the rest: the
                          scheduler's resume path, compared against growing the
                          same prefix in place;
    * fresh_after_abandon -- a session abandoned mid-decode is reused for a new
                          prompt, compared against a brand-new session.
    """
    ctx_len = cx.lib.llm_engine_context_length(cx.eng)
    r = {"mode": "semantics", "lib": args.lib, "context": ctx_len,
         "decode_tokens": args.decode, "scenarios": {}}

    def show(k, v):
        """Print one field. A token stream prints as ids plus the text they
        decode to; a list of streams (multi-turn) prints one line per stream."""
        if isinstance(v, list) and v and isinstance(v[0], list):
            for i, stream in enumerate(v):
                print(f"  {k}[{i}].tokens={','.join(str(x) for x in stream)}",
                      flush=True)
                print(f"  {k}[{i}].text={cx.text(stream)!r}", flush=True)
        elif isinstance(v, list):
            print(f"  {k}.tokens={','.join(str(x) for x in v)}", flush=True)
            print(f"  {k}.text={cx.text(v)!r}", flush=True)
        else:
            print(f"  {k}={v}", flush=True)

    def put(name, **fields):
        # `same*` fields are this build's own comparisons; the scenario passes
        # only if every one holds. A scenario with no such field is a pure
        # recording -- there is nothing inside one build to compare it against,
        # so its verdict comes from --compare across builds. Labelling that
        # "PASS" would be a check that never ran.
        checks = {k: v for k, v in fields.items() if k.startswith("same")}
        fields["pass"] = all(checks.values()) if checks else None
        r["scenarios"][name] = fields
        verdict = ("recorded" if not checks
                   else "PASS" if fields["pass"] else "FAIL")
        print(f"--- {name}: {verdict}", flush=True)
        for k, v in fields.items():
            show(k, v)

    k = args.decode
    short = cx.chat("Name the capital of France in one word.")
    second = cx.chat("Now name its river.")

    # --- 1: prefill -> decode -> extend -> decode, three turns ------------
    s = cx.session()
    try:
        cx.prefill(s, short)
        turns = [cx.decode(s, k)]
        for q in ("Now name its river.", "And one famous museum there."):
            cx.extend(s, cx.chat(q))
            turns.append(cx.decode(s, k))
        put("multi_turn", turns=turns, token_len=cx.tok_len(s))
    finally:
        cx.free(s)

    # --- 2: restore into a session that had a LONGER history --------------
    # The scenario the "restore must still clear" rule exists for.
    longer = pad_prompt(cx, "Describe the history of Paris.", len(short) * 8)
    a = cx.session()
    snap = None
    try:
        cx.prefill(a, short)
        # Snapshot at the prefill boundary, *before* the reference decode: both
        # sides must start from the same state, or the comparison is vacuous.
        snap = cx.snapshot(a)
        ref_restored = cx.decode(a, k)          # what a restore must reproduce
        # A different session, deliberately given a much longer history first.
        b = cx.session()
        try:
            cx.prefill(b, longer)
            cx.decode(b, 4)
            cx.restore(b, snap)
            got = cx.decode(b, k)
            cx.extend(b, second)
            ext_got = cx.decode(b, k)
        finally:
            cx.free(b)
        # The reference continuation: the same sequence from a session that
        # never saw the longer prompt.
        c = cx.session()
        try:
            cx.prefill(c, short)
            cx.decode(c, k)
            cx.extend(c, second)
            ext_ref = cx.decode(c, k)
        finally:
            cx.free(c)
        put("restore_over_longer", restored=got, restored_ref=ref_restored,
            extended=ext_got, extended_ref=ext_ref,
            same_restored=got == ref_restored,
            same_extended=ext_got == ext_ref)
    finally:
        if snap:
            cx.lib.llm_snapshot_free(snap)
        cx.free(a)

    # --- 3: two sessions strictly alternating ----------------------------
    a_ids = pad_prompt(cx, "Describe the history of Paris.", len(short) * 8)
    b_ids = cx.chat("Name the capital of Japan in one word.")
    solo = cx.session()
    try:
        cx.prefill(solo, a_ids)
        solo_a = cx.decode(solo, k)
    finally:
        cx.free(solo)
    sa, sb = cx.session(), cx.session()
    try:
        cx.prefill(sa, a_ids)
        inter_a, inter_b = [], []
        for _ in range(k):
            inter_a.append(cx.decode(sa, 1)[0])
            # B is replaced every round: a fresh prefill parks A and rewrites
            # the shared FA buffers right where A's live KV is.
            cx.prefill(sb, b_ids)
            inter_b.append(cx.decode(sb, 1)[0])
        put("alternating", solo_a=solo_a, interleaved_a=inter_a,
            interleaved_b=inter_b, same_a=inter_a == solo_a)
    finally:
        cx.free(sa)
        cx.free(sb)

    # --- 4: prefix-cache restore -> extend -> decode ----------------------
    full = pad_prompt(cx, "Describe the history of Paris.", len(short) * 16)
    cut = (len(full) // 2 // 64) * 64      # a 64-aligned cut, as the scheduler
    src = cx.session()                     # uses (a cut costs no replayed tail)
    snap4 = None
    try:
        cx.prefill(src, full[:cut])
        snap4 = cx.snapshot(src)
        target = cx.session()
        try:
            cx.restore(target, snap4)
            cx.extend(target, full[cut:])
            restored = cx.decode(target, k)
            restored_len = cx.tok_len(target)
        finally:
            cx.free(target)
        inline = cx.session()
        try:
            cx.prefill(inline, full[:cut])
            cx.extend(inline, full[cut:])
            grown = cx.decode(inline, k)
        finally:
            cx.free(inline)
        put("prefix_cache", restored=restored, grown=grown,
            same=restored == grown, cut=cut, total=len(full),
            token_len=restored_len)
    finally:
        if snap4:
            cx.lib.llm_snapshot_free(snap4)
        cx.free(src)

    # --- 5: fresh prefill on a session abandoned mid-conversation ---------
    fresh = cx.chat("Name the capital of Italy in one word.")
    reuse = cx.session()
    try:
        cx.prefill(reuse, pad_prompt(cx, "Describe the history of Rome.",
                                     len(short) * 8))
        cx.decode(reuse, 16)                 # abandoned mid-decode
        cx.prefill(reuse, fresh)             # same session, brand-new prompt
        reused = cx.decode(reuse, k)
        reused_len = cx.tok_len(reuse)
    finally:
        cx.free(reuse)
    clean = cx.session()
    try:
        cx.prefill(clean, fresh)
        ref = cx.decode(clean, k)
    finally:
        cx.free(clean)
    put("fresh_after_abandon", reused=reused, clean=ref,
        same=reused == ref, reused_len=reused_len, clean_len=len(fresh))

    return r


def compare(paths, mode):
    runs = [json.load(open(p)) for p in paths]
    names = [os.path.basename(p) for p in paths]
    if mode == "perf":
        widths = sorted({w for r in runs for w in r["items"]}, key=int)
        print(f"{'rows':>6} " + " ".join(f"{n:>24}" for n in names) + "   delta")
        bad = False
        for w in widths:
            cells, med, toks = [], [], []
            for r in runs:
                it = r["items"].get(w)
                if not it:
                    cells.append("missing")
                    med.append(None)
                    continue
                cells.append(f"{it['median_ms']:>11.2f} ms "
                             f"[{it['min_ms']:.0f}-{it['max_ms']:.0f}]")
                med.append(it["median_ms"])
                toks.append(it["tokens"])
            delta = ""
            if len(med) == 2 and None not in med:
                delta = f"{med[1] - med[0]:+.2f} ms"
                if med[0] > 0:
                    delta += f" ({100 * (med[1] - med[0]) / med[0]:+.1f}%)"
            print(f"{w:>6} " + " ".join(f"{c:>24}" for c in cells) + f"   {delta}")
            if any(t != toks[0] for t in toks[1:]):
                bad = True
                print(f"{'':>6} TOKENS DIFFER at {w} rows")
        # Text is the human-readable form of the same claim.
        for w in widths:
            texts = [r["items"].get(w, {}).get("text") for r in runs]
            if any(t != texts[0] for t in texts[1:]):
                print(f"TEXT DIFFERS at {w} rows")
                for n, t in zip(names, texts):
                    print(f"   {n}: {t!r}")
        return 1 if bad else 0

    bad = 0
    keys = sorted({k for r in runs for k in r["scenarios"]})
    for key in keys:
        vals = [r["scenarios"].get(key) for r in runs]
        # Same-build verdicts are shown for context; the cross-build diff below
        # is what this mode actually decides. A scenario whose own checks fail
        # in both builds still "differs 0" -- so report those separately.
        passed = [v.get("pass") if v else None for v in vals]
        if any(p is False for p in passed):
            bad += 1
            print(f"SELF-FAIL {key}: same-build check failed (pass: {passed})")
        if any(v != vals[0] for v in vals[1:]):
            bad += 1
            print(f"DIFF {key}  (pass: {passed})")
            for n, v in zip(names, vals):
                print(f"   {n}: {json.dumps(v, sort_keys=True)}")
        else:
            print(f"same {key}  (pass: {passed[0]})")
    print(f"{len(keys)} scenarios, {bad} differ")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib")
    ap.add_argument("--model")
    ap.add_argument("--tokenizer")
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--mode", choices=("perf", "semantics"), default="perf")
    ap.add_argument("--prompt", default="Name the capital of France in one word.")
    ap.add_argument("--rows", default="64,256,2048,16384")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--decode", type=int, default=8,
                    help="decode tokens recorded (short output)")
    ap.add_argument("--out", help="write the JSON result here")
    ap.add_argument("--compare", nargs="+", metavar="JSON",
                    help="diff two or more result files instead of running")
    ap.add_argument("--compare-mode", choices=("perf", "semantics"),
                    default="perf")
    a = ap.parse_args()

    if a.compare:
        raise SystemExit(compare(a.compare, a.compare_mode))
    if not a.lib or not a.model or not a.tokenizer:
        raise SystemExit("--lib, --model and --tokenizer are required to run")

    signal.signal(signal.SIGALRM, _alarm)
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    tok = lib.llm_tokenizer_load(a.tokenizer.encode(), ctypes.byref(err))
    if not tok:
        raise SystemExit(f"tokenizer: {err.value}")
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load: {err.value}")
    # Range-check prompt ids the way the worker does, so a real prompt is
    # checked exactly as in production (the bmodel cannot carry the vocabulary).
    lib.llm_engine_set_vocab_size(eng, lib.llm_tokenizer_vocab_size(tok))
    print(f"loaded {a.lib}: layers={lib.llm_engine_num_layers(eng)} "
          f"context={lib.llm_engine_context_length(eng)} "
          f"max_input={lib.llm_engine_max_input_length(eng)}", flush=True)
    cx = Ctx(lib, eng, err, tok)
    try:
        r = run_perf(cx, a) if a.mode == "perf" else run_semantics(cx, a)
    finally:
        lib.llm_engine_free(eng)
        lib.llm_tokenizer_free(tok)
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(r, fh, indent=1, sort_keys=True)
        print(f"wrote {a.out}", flush=True)
    if r["mode"] == "semantics":
        failed = [k for k, v in r["scenarios"].items() if v.get("pass") is False]
        if failed:
            print(f"SCENARIOS FAILED: {', '.join(failed)}", flush=True)
            sys.exit(1)
    # `pass` is written by put() only for the scenarios that compare streams;
    # a run that reached here without raising is otherwise clean.


main()
