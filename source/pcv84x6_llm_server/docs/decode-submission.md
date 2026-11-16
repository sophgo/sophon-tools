# Decode submission and linear-state handling (MYS-2377)

Two changes to `native/src/llm_engine.cpp` for single-token decode, and how to
re-check them. Nothing here changes numerical semantics: same graphs, same
inputs, same KV/mask/position convention.

## 1. The linear layer's conv_state is not copied onto itself any more

`decode_layers()` used to do this after every linear layer, unconditionally:

```cpp
d2d(state_a(idx), 0, st.output_mems[1], 0, min(...));   // "conv_state comes back as output 1"
```

`state_a(i)` **is** `blocks_cache[i]->stages[0].input_mems[1]` — the graph's own
template memory, which is where `addr_mode=1` writes output 1. The copy was
therefore a device-to-device copy of a buffer onto itself: 18 linear layers ×
96 KB per token on the 35B model, doing nothing.

Measured on the board (`model_tool --info` plus a probe printing the loaded
graph's addresses):

```
block_cache_0  in[1] addr=0x10fd1b0000 size=49152   (conv_state)
               out[1] addr=0x10fd1b0000 size=49152   out1 == in1: YES
               in[0]/out[0] likewise alias (hidden state)
```

The skip is **not hardcoded**. `Engine::Impl::measure_state_layout()` compares
each linear graph's output 1 address and size against input 1 at load time and
records the answer per layer; the copy still happens for a bmodel that returns
a separate buffer. Same for the optional rec_state output 2 (the shipped
bmodels do not emit it — rec_state is updated in place in input 2 — so that
path only fires for a bmodel that does).

Load log line, 35B on 10.42.0.242:

```
[engine] linear state in place: conv 18/18, rec 0/0
```

## 2. One sync per decode, not one per layer

`bmrt_launch_tensor_ex` does not block (`bmruntime_interface.h:476`: "the CPU
program will not be blocked. bm_thread_sync should be called to make sure
inference finished"). The engine was syncing after every layer launch — 24
syncs per token. The reference `LLM-TPU/models/Qwen3_5/cpp_demo/chat.cpp`
launches all blocks then lm_head and syncs once, in `net_launch` +
`forward_next` (`chat.cpp:123`, `:709-750`).

`Engine::Impl::run()` gained a `wait` parameter (default `true`, so every other
call site is unchanged). `decode_layers()` passes `wait=false` for the layers
and then calls `sync_launches()` once, **before returning** — so before the
caller's state copies, any D2S, and lm_head.

Why that is safe:

* Layer *i+1* consumes layer *i*'s hidden state through the runtime's own
  graph-to-graph ordering, which is the same ordering the demo relies on. No
  barrier is needed between layers; the sync is needed before the CPU reads,
  copies, or hands the memory to something outside that chain.
* **The public contract is unchanged.** `Session::decode()` still returns only
  after this token's graphs have retired, so a session can be parked,
  snapshotted, extended or decoded again the moment it returns. The sync was
  not moved past lm_head to let the API return early with work still queued.
* A failed launch sets `fault` immediately (it is the TPU refusing work, not a
  timing artefact). A failed *sync* is reported by `sync_launches()`, which
  every non-waiting path reaches before returning, so `fault` and `last_error`
  keep their meaning. A deferred failure can never be silently dropped: the
  batch sync sits on the success path, not in a cleanup branch.
* Prefill, embedding, vit, lm_head and greedy head keep `wait=true`.

## 3. What is unchanged on purpose

* `blocks_cache[0]`'s shared IO flow: still bound to the graph's own template
  memory; no per-layer buffers were opened.
* `history` bookkeeping, mask `[cur_pos, win)`, KV offset, position ids.
* `kAlign = 64` and the prefill rule that a chunk shorter than 64 rows (or a
  chunk whose length is not a multiple of 64) goes through the decode graphs.
  `LLM_PREFILL_ALIGN` still defaults to 64.
* No version bump, no release: this is a task-card branch, merged by the owner.

## Re-checking

Host (no NPU, no libsophon install needed — `tests/native/fake_bm.cpp`
supplies the bmrt/bmlib symbols):

```sh
tests/native/run_tests.sh /path/to/libsophon/include
```

51 checks over the real `llm_engine.cpp`. They observe behaviour (launch order,
sync points, d2d source/destination addresses, fault state), so they fail if a
future edit re-adds the self-copy, re-syncs per layer, or drops the sync before
lm_head. Verified by reverting each change and watching the corresponding
check fail.

Board, A/B of two `.so` builds on the same model and prompt:

```sh
python3 tools/decode_bench.py --lib <build>/libcv84x6_llm.so --model X.bmodel \
    --tokens <comma-separated ids> --decode 128 --runs 2 [--expect baseline_ids.txt]
```

`--expect` compares generated token ids against the baseline build's and exits
non-zero on the first difference; on a `lm_head`-argmax model that is an exact
check, not a similarity score.

## Board reliability caveat (2026-10-26, 10.42.0.242)

Single-session decode at these prompt sizes was stable across every A/B round.
**Multi-session runs on that board hang the TPU regardless of which build is
used**: the same `tools/session_bench.py` invocation hung the *unmodified*
`origin/main` build as well as this one, with

```
bmdrv_thread_sync_api:1471: wait api timeout, wait 120000ms, core_id=0
pc : bdc_reg_read+0x10/0x30 [bmtpu]
Fixing recursive fault but reboot is needed!
```

so this failure alone does not identify a regression in this change; it reproduces
on the baseline, and its exact trigger is not yet isolated. Multi-session
correctness is covered on the host by `test_two_sessions_interleaved()`
(interleaved decode, park/unpark, snapshot/restore, extend). Board acceptance
must use the currently authorized test device and valid natural-language
prompts; the previous synthetic prompt sequence is not a service-level test.
