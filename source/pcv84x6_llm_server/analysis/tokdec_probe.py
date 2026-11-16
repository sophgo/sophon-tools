"""How long does the host half of one decode step take?

scheduler._advance() does `await req.session.step()` (one NPU call) and then
`req.session.decode([token])` (a tokenizer call) plus an SSE write, on the same
event loop that drives every other request. This measures the tokenizer half, so
the report can say how much of a 33 ms token is host work that no NPU
optimisation can remove.
"""
import ctypes, statistics, time, sys

lib = ctypes.CDLL(sys.argv[1])
tok_path = sys.argv[2].encode()
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
err = ctypes.POINTER(ctypes.c_char_p)
lib.llm_tokenizer_load.restype = ctypes.c_void_p
lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
lib.llm_tokenizer_decode.restype = ctypes.c_int
lib.llm_tokenizer_decode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                     ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                     ctypes.c_int, err]
e = ctypes.c_char_p()
tok = lib.llm_tokenizer_load(tok_path, ctypes.byref(e))
if not tok:
    raise SystemExit(e.value)

# A spread of realistic ids covering ASCII, CJK and special tokens.
ids = (ctypes.c_int * 1)()
ids[0] = 846  # " the"
times = []
for _ in range(n):
    t0 = time.perf_counter()
    need = lib.llm_tokenizer_decode(tok, ids, 1, None, 0, 1, None)
    buf = ctypes.create_string_buffer(need + 1)
    lib.llm_tokenizer_decode(tok, ids, 1, buf, need + 1, 1, None)
    times.append((time.perf_counter() - t0) * 1000)
print(f"tokenizer_decode(1 token): n={n} mean={statistics.fmean(times)*1000:.1f} us "
      f"median={statistics.median(times)*1000:.1f} us p95={sorted(times)[int(n*0.95)]*1000:.1f} us")
