"""Board check for history bmodels: chunked prefill, extend, snapshot/restore.

    python3 tools/cache_check.py --model X_history.bmodel --config config/ --lib libcv84x6_llm.so

1. Long-context recall: a "needle" fact at the start of a long filler text,
   prompt longer than one prefill chunk (exercises block_kv across chunks).
2. Snapshot resume at several cuts k (also unaligned): prefill P[:k] ->
   snapshot -> restore twice -> extend P[k:] must give the same answer both
   times; whether it equals the cold full-prefill answer is reported.
3. Recall through a snapshot: the long needle context is cached, only the
   question is prefilled after restore, and the needle must still be found.
Exits non-zero on any mismatch.
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.native import NativeBackend, Prompt  # noqa: E402

FILLER = ("The archive room held shelves of ledgers, maps and letters, each catalogued by "
          "a clerk who wrote the date, the sender and a short summary on a card. ")


def render(user: str, system: str | None = None) -> str:
    sys_part = f"<|im_start|>system\n{system}<|im_end|>\n" if system else ""
    return (f"{sys_part}<|im_start|>user\n{user}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


async def answer(be, sess, max_tokens):
    out = []
    for _ in range(max_tokens):
        t = await sess.step()
        if sess.is_stop_token(t):
            break
        out.append(t)
    return be.tokenizer_decode(out)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--lib", default=None)
    ap.add_argument("--filler-repeat", type=int, default=120)
    a = ap.parse_args()

    be = NativeBackend(a.model, os.path.join(a.config, "tokenizer.json"), "chk", lib_path=a.lib)
    print(f"ctx={be.context_length} max_prompt={be.max_prompt_length} "
          f"chunk={be.prefill_chunk} history={be.supports_chunked_prefill}", flush=True)
    fails = 0

    # 1. long-context recall
    needle = "The secret code of the archive is BLUE-HERON-4471."
    text = needle + " " + FILLER * a.filler_repeat + "\nWhat is the secret code of the archive? Answer with the code only."
    toks = Prompt(be.tokenizer_encode(render(text)))
    s = await be.new_session()
    t0 = time.time()
    await s.feed_prompt(toks)
    t1 = time.time()
    got = await answer(be, s, 24)
    await s.close()
    ok = "BLUE-HERON-4471" in got
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] recall over {len(toks)} tokens "
          f"(prefill {t1 - t0:.1f}s, {len(toks) / (t1 - t0):.0f} tok/s): {got!r}", flush=True)

    # 2. snapshot equivalence
    system = "You are a careful assistant. " + FILLER * 8
    P = Prompt(be.tokenizer_encode(render("Summarise the archive description in one sentence.", system)))
    s = await be.new_session()
    await s.feed_prompt(P)
    ref = await answer(be, s, 40)
    await s.close()
    print(f"reference ({len(P)} tokens): {ref!r}", flush=True)
    same_as_cold = 0
    cuts = sorted({16 * (len(P) // 32), len(P) // 2 + 3, len(P) - 7} | set(be.snapshot_points(P)))
    for k in cuts:
        s1 = await be.new_session()
        await s1.feed_prompt(P.segment(0, k))
        snap = await s1.snapshot(k)
        await s1.close()
        results = []
        for _ in range(2):
            s2 = await be.new_session()
            await s2.restore(snap)
            await s2.feed_prompt(P.segment(k, len(P)))
            results.append(await answer(be, s2, 40))
            await s2.close()
        snap.release()
        # A resumed prefill runs the remaining rows through block_kv instead of
        # block_ + decode replay: mathematically the same, numerically not
        # bit-identical, and a MoE model can route differently on that. So the
        # hard requirement is determinism across restores; equality with the
        # cold run is reported, not required.
        ok = results[0] == results[1] and len(results[0]) > 0
        same_as_cold += results[0] == ref
        fails += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] resume at {k} "
              f"({'same as' if results[0] == ref else 'differs from'} cold): {results[0]!r}"
              + ("" if results[0] == results[1] else f" / second restore {results[1]!r}"),
              flush=True)
    print(f"resume outputs identical to the cold run: {same_as_cold}/{len(cuts)}", flush=True)

    # 3. recall through a snapshot: cache the long context, resume, ask
    ctx = needle + " " + FILLER * a.filler_repeat
    full = Prompt(be.tokenizer_encode(render(ctx + "\nWhat is the secret code of the archive? Answer with the code only.")))
    cut = len(be.tokenizer_encode("<|im_start|>user\n" + ctx)) // 16 * 16
    s1 = await be.new_session()
    await s1.feed_prompt(full.segment(0, cut))
    snap = await s1.snapshot(cut)
    await s1.close()
    s2 = await be.new_session()
    await s2.restore(snap)
    t0 = time.time()
    await s2.feed_prompt(full.segment(cut, len(full)))
    t1 = time.time()
    got = await answer(be, s2, 24)
    await s2.close()
    snap.release()
    ok = "BLUE-HERON-4471" in got
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] recall after resuming {cut} cached tokens "
          f"(prefilled {len(full) - cut} in {t1 - t0:.2f}s): {got!r}", flush=True)

    await be.close()
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
