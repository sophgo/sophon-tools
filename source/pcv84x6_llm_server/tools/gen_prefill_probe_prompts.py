#!/usr/bin/env python3
"""Regenerate the prompt id files the prefill-width probe reads (MYS-2394).

The probe compares a dynamic prefill width against the 64-aligned baseline, which
is only a comparison if both runs read the *same* ids. The ids also have to be
real: an earlier multi-session driver fed hand-written id sequences to the engine
and the TPU timed out, so "any id list will do" is not true on this board.

So every file here is produced the way the worker produces a prompt -- real text
through the release package's own tokenizer, wrapped by the model's chat
template -- and tuned to an exact token count, because the width is the whole
point:

  * ``fresh-N``   a whole one-turn prompt (ends at the generating
                  ``<|im_start|>assistant`` header), exactly N tokens. Prefilling
                  this is the first turn: no history, FA runs ``block_<i>``.
  * ``turn-N``    the same shape at a longer length, used as the history of an
                  ``extend`` run -- a complete conversation up to the header.
  * ``delta-N``   the first N tokens of the chunk the template appends for the
                  *next* user turn (``<|im_end|>\\n<|im_start|>user\\n...``). That
                  is literally what the worker extends a session with when a
                  follow-up message arrives; ``delta-48`` is the whole chunk,
                  the shorter ones are its leading tokens, which is how a
                  five-token message reaches the engine in practice.

Lengths are tuned by walking the corpus in ``corpus.txt``: the body is a real
question followed by corpus words, and the word count is searched until
``len(encode(render(text))) == N``. Every file is verified after writing, and the
manifest records the length and sha256 so the committed ids can be checked
without an NPU.

    python3 tools/gen_prefill_probe_prompts.py --lib \\
        /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --tokenizer /opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json

``--verify`` re-reads the committed files and checks them against the manifest
(no tokenizer, no NPU: it is what the host test runs).
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "prefill_probe_prompts")
CORPUS = os.path.join(OUT_DIR, "corpus.txt")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

# The template's generating header (app/api/tool_calls.py, thinking off) and the
# opening of the chunk it appends for the turn after.
HEADER = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
NEXT_TURN = "<|im_end|>\n<|im_start|>user\n"

# The lengths the probe matrix asks for. `delta-16` / `delta-32` and
# `turn-8192` were added for the long-history boundary check in MYS-2396; the
# earlier files must stay byte-identical, which they do because the search below
# only ever reads a prefix of the corpus.
FRESH = (63, 200)
TURN = (1000, 2048, 8192)
DELTA = (5, 16, 17, 32, 33, 48)

QUESTION = "Please summarise the following notes in one paragraph."
NEXT_QUESTION = "Thanks. Can you say a little more about the third point?"

# Words that cost one token with a leading space, used to land on an exact count
# when the corpus word at that position overshoots by one.
TAIL_WORDS = ("the", "a", "of", "and", "to", "is", "in")


def bind(lib_path: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(lib_path)
    err = ctypes.POINTER(ctypes.c_char_p)
    lib.llm_tokenizer_load.restype = ctypes.c_void_p
    lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
    lib.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
    lib.llm_tokenizer_encode.restype = ctypes.c_int
    lib.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                         ctypes.POINTER(ctypes.c_int), ctypes.c_int, err]
    return lib


class Tokenizer:
    def __init__(self, lib: ctypes.CDLL, path: str):
        self.lib = lib
        self.err = ctypes.c_char_p()
        self.h = lib.llm_tokenizer_load(path.encode(), ctypes.byref(self.err))
        if not self.h:
            raise SystemExit(f"tokenizer_load: {self.err.value}")

    def encode(self, text: str) -> list[int]:
        raw = text.encode("utf-8")
        n = self.lib.llm_tokenizer_encode(self.h, raw, None, 0,
                                          ctypes.byref(self.err))
        if n < 0:
            raise SystemExit(f"encode: {self.err.value}")
        buf = (ctypes.c_int * max(n, 1))()
        got = self.lib.llm_tokenizer_encode(self.h, raw, buf, n,
                                            ctypes.byref(self.err))
        if got != n:
            raise SystemExit(f"encode: asked for {n}, wrote {got}")
        return list(buf)[:n]

    def close(self) -> None:
        if self.h:
            self.lib.llm_tokenizer_free(self.h)
            self.h = None


def corpus_words() -> list[str]:
    with open(CORPUS, encoding="utf-8") as f:
        words = f.read().split()
    # The longest file is an 8192-token prompt, roughly 6000 words, so a few
    # passes over the corpus cover it. Only prefixes are ever read, so raising
    # this number cannot change an already generated file.
    return words * 12


class Msg:
    """Just enough of the API's ChatMessage for the renderer, which reads
    ``.role`` / ``.content`` / ``.reasoning_content`` / ``.tool_calls``."""

    def __init__(self, role: str, content: str, reasoning_content: str = "",
                 tool_calls=None):
        self.role = role
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


def render(body: str) -> str:
    from app.api.tool_calls import render_messages
    return render_messages([Msg("user", body)])[0]


def turn_one(k: int, words: list[str], tail: str = "") -> str:
    return render(QUESTION + " " + " ".join(words[:k] + ([tail] if tail else [])))


def next_chunk(k: int, words: list[str], tail: str = "") -> str:
    body = NEXT_QUESTION + " " + " ".join(words[:k] + ([tail] if tail else []))
    return NEXT_TURN + body.strip() + "<|im_end|>\n" + HEADER


def tune(make_text, target: int, words: list[str], what: str) -> str:
    """Smallest-prefix search for a text that encodes to exactly `target` ids.

    Token count grows with the number of corpus words, so a binary search lands
    next to the answer and a short linear scan -- with and without a one-token
    tail word -- finds the exact count. BPE merges can move the count by two
    between neighbours, which is why the scan is not just the search result.
    """
    def count(k: int, tail: str = "") -> int:
        return len(ENC.encode(make_text(k, words, tail)))

    lo, hi = 0, len(words) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if count(mid) < target:
            lo = mid + 1
        else:
            hi = mid
    for k in range(max(0, lo - 48), min(len(words), lo + 48)):
        for tail in ("",) + TAIL_WORDS:
            text = make_text(k, words, tail)
            if len(ENC.encode(text)) == target:
                return text
    raise SystemExit(f"{what}: no text encodes to exactly {target} ids "
                     f"(nearest {count(lo)} at {lo} corpus words)")


def verify_manifest() -> int:
    """Check the committed id files against the manifest; no tokenizer needed."""
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    bad = 0
    for name, want in manifest["files"].items():
        path = os.path.join(OUT_DIR, name)
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        ids = [int(x) for x in raw.replace("\n", ",").split(",") if x.strip()]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if len(ids) != want["tokens"]:
            print(f"{name}: {len(ids)} ids, manifest says {want['tokens']}")
            bad += 1
        if digest != want["sha256"]:
            print(f"{name}: sha256 {digest[:16]}..., manifest says "
                  f"{want['sha256'][:16]}...")
            bad += 1
    print(f"{len(manifest['files'])} files, {bad} mismatches")
    return 0 if bad == 0 else 1


def write(name: str, ids: list[int], meta: dict) -> dict:
    path = os.path.join(OUT_DIR, name)
    raw = ",".join(str(i) for i in ids) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    want = dict(meta)
    want["tokens"] = len(ids)
    want["sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    print(f"{name}: {len(ids)} ids")
    return want


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lib", help="path to libcv84x6_llm.so")
    ap.add_argument("--tokenizer", help="path to the model's tokenizer.json")
    ap.add_argument("--verify", action="store_true",
                    help="check the committed files against the manifest only")
    a = ap.parse_args()
    if a.verify:
        return verify_manifest()
    if not a.lib or not a.tokenizer:
        ap.error("--lib and --tokenizer are required to regenerate")

    words = corpus_words()
    lib = bind(a.lib)
    globals()["ENC"] = Tokenizer(lib, a.tokenizer)
    files: dict[str, dict] = {}
    try:
        for n in FRESH:
            files[f"fresh-{n}.txt"] = write(
                f"fresh-{n}.txt", ENC.encode(tune(turn_one, n, words, f"fresh-{n}")),
                {"kind": "fresh", "source": "one user turn rendered by the chat "
                                           "template, ending at the generating header"})
        for n in TURN:
            files[f"turn-{n}.txt"] = write(
                f"turn-{n}.txt", ENC.encode(tune(turn_one, n, words, f"turn-{n}")),
                {"kind": "history", "source": "same shape as fresh, used as the "
                                              "history of an extend run"})

        # One complete next-turn chunk, then the leading tokens of it: the
        # longest delta is a whole turn, the shorter ones are what a short
        # follow-up message looks like arriving at the engine.
        longest = max(DELTA)
        chunk = tune(next_chunk, longest, words, f"delta-{longest}")
        chunk_ids = ENC.encode(chunk)
        if not chunk.startswith(NEXT_TURN) or not chunk.endswith(HEADER):
            raise SystemExit("delta chunk does not have the template's shape")
        # The renderer must still build the pieces above exactly; this is what
        # keeps the hand-written opener honest against the chat template.
        from app.api.tool_calls import render_messages as _rm
        two = _rm([Msg("user", "x"), Msg("assistant", "y"), Msg("user", "z")])[0]
        if two != ("<|im_start|>user\nx<|im_end|>\n<|im_start|>assistant\ny"
                   + NEXT_TURN + "z<|im_end|>\n" + HEADER):
            raise SystemExit("the template's next-turn opener changed; "
                             "NEXT_TURN/HEADER need updating")
        for n in DELTA:
            files[f"delta-{n}.txt"] = write(
                f"delta-{n}.txt", chunk_ids[:n],
                {"kind": "extend", "source": "leading tokens of the next turn's "
                                             "template chunk; delta-%d is the whole chunk"
                                             % longest})
        header_ids = ENC.encode(HEADER)
        next_turn_ids = ENC.encode(NEXT_TURN)
    finally:
        ENC.close()

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"corpus": "corpus.txt",
                   "question": QUESTION, "next_question": NEXT_QUESTION,
                   # What the template's two fixed pieces encode to, so a test
                   # without a tokenizer can check the files are shaped right.
                   "header_ids": header_ids,
                   "next_turn_ids": next_turn_ids,
                   "files": files}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {MANIFEST}")
    return verify_manifest()


ENC: Tokenizer | None = None


if __name__ == "__main__":
    sys.exit(main())
