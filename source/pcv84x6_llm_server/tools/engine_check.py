"""Drive NativeBackend directly (no HTTP, no scheduler) on the board.

    python3 tools/engine_check.py --model X.bmodel --config config/ \
        --prompt "What is the capital of France?" [--image test.jpg] [--sessions 2]

Prints each answer with FTL/TPS. With --sessions N, the N prompts are decoded
interleaved token by token, which exercises the engine's session parking.
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.native import NativeBackend  # noqa: E402


def render(question: str, image: bool) -> str:
    content = ("<|vision_start|><|image_pad|><|vision_end|>" if image else "") + question
    return (f"<|im_start|>user\n{content}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--lib", default=None)
    ap.add_argument("--prompt", action="append", required=True)
    ap.add_argument("--image", default=None)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--sessions", type=int, default=1)
    a = ap.parse_args()

    t = time.time()
    be = NativeBackend(a.model, os.path.join(a.config, "tokenizer.json"), "check",
                       lib_path=a.lib)
    print(f"load {time.time() - t:.1f}s ctx={be.context_length} vision={be.supports_vision}",
          flush=True)
    blobs = [open(a.image, "rb").read()] if a.image else None

    prompts = (a.prompt * a.sessions)[: max(a.sessions, len(a.prompt))]
    sess, out, done, t0, tfirst = [], [], [], [], []
    for p in prompts:
        toks = await be.encode(render(p, bool(blobs)), blobs)
        s = await be.new_session()
        t0.append(time.time())
        await s.feed_prompt(toks)
        sess.append(s)
        out.append([])
        done.append(False)
        tfirst.append(None)
        print(f"prompt tokens={len(toks)} images={len(getattr(toks, 'images', []))}", flush=True)
    while not all(done):
        for i, s in enumerate(sess):
            if done[i]:
                continue
            tok = await s.step()
            if tfirst[i] is None:
                tfirst[i] = time.time()
            if s.is_stop_token(tok) or len(out[i]) >= a.max_tokens:
                done[i] = True
                continue
            out[i].append(tok)
    for i, s in enumerate(sess):
        dt = time.time() - tfirst[i]
        print(f"--- [{i}] FTL={tfirst[i] - t0[i]:.2f}s TPS={len(out[i]) / dt if dt else 0:.2f} "
              f"n={len(out[i])}\n{s.decode(out[i])!r}", flush=True)
        await s.close()
    await be.close()


asyncio.run(main())
