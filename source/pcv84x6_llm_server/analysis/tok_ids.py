"""Tokenise a chat-templated prompt on the board, print comma-separated ids.

    python3 analysis/tok_ids.py --lib <build>/libcv84x6_llm.so \
        --tokenizer <config>/tokenizer.json --prompt "..." [--repeat N]

Kept separate from decode_bench.py so the benchmark process loads nothing but
the bmodel: the tokenizer lives in the same .so, but a separate process keeps
the timed run free of Python work.
"""
import argparse
import ctypes

_CHAT = ("<|im_start|>user\n{body}<|im_end|>\n"
         "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--pad-to", type=int, default=0,
                    help="append ' the' repeats until at least this many tokens")
    a = ap.parse_args()

    lib = ctypes.CDLL(a.lib)
    err = ctypes.POINTER(ctypes.c_char_p)
    lib.llm_tokenizer_load.restype = ctypes.c_void_p
    lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
    lib.llm_tokenizer_encode.restype = ctypes.c_int
    lib.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                         ctypes.POINTER(ctypes.c_int),
                                         ctypes.c_int, err]
    e = ctypes.c_char_p()
    tok = lib.llm_tokenizer_load(a.tokenizer.encode(), ctypes.byref(e))
    if not tok:
        raise SystemExit(f"tokenizer: {e.value}")

    def enc(text: str) -> list[int]:
        raw = text.encode()
        n = lib.llm_tokenizer_encode(tok, raw, None, 0, None)
        buf = (ctypes.c_int * max(n, 1))()
        got = lib.llm_tokenizer_encode(tok, raw, buf, n, None)
        return list(buf[:got])

    body = a.prompt
    ids = enc(_CHAT.format(body=body))
    while len(ids) < a.pad_to:
        body += " the history of the city is long and detailed."
        ids = enc(_CHAT.format(body=body))
    print(",".join(str(i) for i in ids))


main()
