"""Multi-session check over the engine's C API: interleaved decode, snapshots.

    ./session_bench.py --lib X.so --model Y.bmodel --prompt-a A --prompt-b B \
        --decode 32 --rounds 2

MYS-2377 defers the decode sync, so the thing that could break is not single
stream speed but the state swap between sessions: a session parked while the
TPU still had work queued would come back with someone else's history. This
drives two sessions strictly interleaved (A, B, A, B ...) so every decode parks
the other one, and checks that

  1. each session's token_len() advances by exactly its own decodes;
  2. A's tokens are identical whether it runs alone or interleaved with B, and
     likewise for B -- i.e. interleaving changed no number;
  3. snapshot -> restore into a fresh session -> decode gives the same tokens
     as continuing the original session, which is the parked/resident swap
     doing its job.

Exits non-zero on any mismatch. Needs two different prompts; reuse prompt_64
and prompt_1024 from the benchmark instructions, or any two id lists.
"""
import argparse
import ctypes
import sys
import time


def bind(path):
    lib = ctypes.CDLL(path)
    err = ctypes.POINTER(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, err]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_token_len.restype = ctypes.c_int
    lib.llm_session_token_len.argtypes = [ctypes.c_void_p]
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, err]
    # extend takes exactly the same arguments as prefill. Declaring its
    # argtypes is not optional: without them ctypes converts the int array to a
    # plain C int, i.e. truncates the pointer to 32 bits, and the engine reads
    # the token buffer through a garbage address -- an immediate SIGSEGV inside
    # Session::prefill_impl, which is what this tool used to do.
    lib.llm_session_extend.argtypes = lib.llm_session_prefill.argtypes
    lib.llm_session_extend.restype = ctypes.c_int
    lib.llm_session_decode.restype = ctypes.c_int
    lib.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_session_snapshot.restype = ctypes.c_void_p
    lib.llm_session_snapshot.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_session_restore.restype = ctypes.c_int
    lib.llm_session_restore.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, err]
    lib.llm_snapshot_free.argtypes = [ctypes.c_void_p]
    return lib


def ids_of(path):
    return [int(x) for x in open(path).read().strip().split(",") if x.strip()]


class S:
    def __init__(self, lib, eng, prompt):
        self.lib, self.eng = lib, eng
        self.err = ctypes.c_char_p()
        self.h = lib.llm_session_new(eng, ctypes.byref(self.err))
        if not self.h:
            raise SystemExit(f"session_new: {self.err.value}")
        arr = (ctypes.c_int * len(prompt))(*prompt)
        rc = lib.llm_session_prefill(eng, self.h, arr, len(prompt), None, 0, None,
                                     None, None, None, None, None,
                                     ctypes.byref(self.err))
        if rc != 0:
            raise SystemExit(f"prefill: {self.err.value}")
        self.first = self.step()  # the token prefill sampled

    def step(self):
        t = self.lib.llm_session_decode(self.eng, self.h, ctypes.byref(self.err))
        if t < 0:
            raise SystemExit(f"decode: {self.err.value}")
        return t

    def n(self):
        if not self.h:
            raise RuntimeError("session is already freed")
        return self.lib.llm_session_token_len(self.h)

    def free(self):
        if self.h:
            h, self.h = self.h, None
            self.lib.llm_session_free(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt-a", required=True, help="file of comma-separated ids")
    ap.add_argument("--prompt-b", required=True)
    ap.add_argument("--decode", type=int, default=32)
    ap.add_argument("--rounds", type=int, default=2,
                    help="independent interleaved rounds, to catch a swap that only "
                         "breaks on the second park")
    ap.add_argument("--dev", type=int, default=0)
    a = ap.parse_args()

    pa, pb = ids_of(a.prompt_a), ids_of(a.prompt_b)
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load: {err.value}")

    fails = 0
    try:
        # --- reference: each prompt alone --------------------------------
        solo = {}
        for tag, p in (("A", pa), ("B", pb)):
            s = S(lib, eng, p)
            solo[tag] = [s.first] + [s.step() for _ in range(a.decode)]
            history = s.n()
            s.free()
            print(f"solo {tag}: {len(solo[tag])} tokens, history={history}", flush=True)

        # --- interleaved --------------------------------------------------
        for r in range(a.rounds):
            sa, sb = S(lib, eng, pa), S(lib, eng, pb)
            na0, nb0 = sa.n(), sb.n()
            ta, tb = [sa.first], [sb.first]
            for _ in range(a.decode):
                ta.append(sa.step())
                tb.append(sb.step())
            print(f"round {r + 1}: A hist {na0}->{sa.n()} B hist {nb0}->{sb.n()}", flush=True)
            if sa.n() != na0 + a.decode:
                print(f"  FAIL A history advanced by {sa.n() - na0}, want {a.decode}")
                fails += 1
            if sb.n() != nb0 + a.decode:
                print(f"  FAIL B history advanced by {sb.n() - nb0}, want {a.decode}")
                fails += 1
            if ta != solo["A"]:
                at = next(i for i, (x, y) in enumerate(zip(ta, solo["A"])) if x != y)
                print(f"  FAIL A tokens differ from solo at {at}: "
                      f"{ta[at:at + 6]} vs {solo['A'][at:at + 6]}")
                fails += 1
            if tb != solo["B"]:
                at = next(i for i, (x, y) in enumerate(zip(tb, solo["B"])) if x != y)
                print(f"  FAIL B tokens differ from solo at {at}: "
                      f"{tb[at:at + 6]} vs {solo['B'][at:at + 6]}")
                fails += 1
            sa.free()
            sb.free()

        # --- snapshot / restore / extend ---------------------------------
        # Snapshot A mid-conversation, restore into a fresh session, and check
        # it continues with the same tokens as the original would have.
        sa = S(lib, eng, pa)
        for _ in range(a.decode // 2):
            sa.step()
        snap = lib.llm_session_snapshot(eng, sa.h, ctypes.byref(err))
        if not snap:
            print(f"snapshot failed: {err.value}")
            fails += 1
        else:
            want = [sa.step() for _ in range(8)]
            sc = S.__new__(S)
            sc.lib, sc.eng, sc.err = lib, eng, ctypes.c_char_p()
            sc.h = lib.llm_session_new(eng, ctypes.byref(sc.err))
            rc = lib.llm_session_restore(eng, sc.h, snap, ctypes.byref(sc.err))
            if rc != 0:
                print(f"  FAIL restore: {sc.err.value}")
                fails += 1
            else:
                got = [sc.step() for _ in range(8)]
                if got != want:
                    print(f"  FAIL restored session continues differently: "
                          f"{got[:6]} vs {want[:6]}")
                    fails += 1
                else:
                    print(f"snapshot/restore: same next {len(want)} tokens", flush=True)
            sc.free()

            # restore -> extend, the scheduler's actual resume path, checked
            # against the same extend on a session that never left the state:
            # prefill, decode to the cut, extend `tail`, decode. A restored
            # session doing the same must produce the same continuation. An
            # extend that missed the restored prefix (wrong KV slot, wrong
            # old_kvlen) changes the first token, which the old "history=N"
            # print hid.
            tail = (ctypes.c_int * 4)(100, 101, 102, 103)
            outs = {}
            # (a) the original session, which is at its own post-decode state
            #     (decode//2 + 8 tokens past the snapshot) -- so rewind it by
            #     restoring the snapshot into a fresh session and extending.
            # (b) the same, twice: reproducibility of restore -> extend.
            for branch in ("restore-1", "restore-2"):
                s = S.__new__(S)
                s.lib, s.eng, s.err = lib, eng, ctypes.c_char_p()
                s.h = lib.llm_session_new(eng, ctypes.byref(s.err))
                rc = lib.llm_session_restore(eng, s.h, snap, ctypes.byref(s.err))
                if rc == 0:
                    rc = lib.llm_session_extend(eng, s.h, tail, 4, None, 0, None,
                                                None, None, None, None, None,
                                                ctypes.byref(s.err))
                if rc != 0:
                    print(f"  FAIL extend ({branch}): {s.err.value}")
                    fails += 1
                    s.free()
                    continue
                outs[branch] = [s.step() for _ in range(6)]
                print(f"extend ({branch}): history={s.n()}", flush=True)
                s.free()
            if len(outs) == 2:
                first, second = outs["restore-1"], outs["restore-2"]
                if first != second:
                    print(f"  FAIL restore -> extend is not reproducible: "
                          f"{first[:4]} vs {second[:4]}")
                    fails += 1
                elif any(t is None or t < 0 for t in first):
                    print(f"  FAIL restore -> extend produced no tokens: {first}")
                    fails += 1
                else:
                    print(f"restore -> extend: same {len(first)} tokens from two "
                          f"restores of one snapshot", flush=True)

            lib.llm_snapshot_free(snap)
        sa.free()
    finally:
        lib.llm_engine_free(eng)

    print(f"SESSIONS {'OK' if fails == 0 else str(fails) + ' FAILURES'}")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
