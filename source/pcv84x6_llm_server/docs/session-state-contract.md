# Session state contract: snapshot, restore, extend (MYS-2381)

What a `Session` is allowed to promise when its state is copied out and put
back, what broke that promise, and how the fixes are checked on the host. No
claim is made here about the board's `bmdrv_thread_sync_api` timeout — that
investigation is separate and still open (see the last section).

## The state, and why the buffers are not the state

A history-bmodel session decodes from four numbers plus its device buffers:

| field      | meaning                                                        |
|------------|----------------------------------------------------------------|
| `history`  | KV slots written; the next decode appends at this slot, and its mask position is the same number |
| `pos_next` | M-RoPE position of the token `last_id` embeds                   |
| `last_id`  | the token the next `decode()` embeds — the previous `lm_head` argmax, **not yet in KV** |
| `pending`  | `last_id` while the caller has not been handed it yet           |

The device buffers (FA K/V for `[0, history)`, linear conv/rec state whole) are
only the first half. The second half is `last_id`: a session that has just
prefilled holds `history` KV rows but its next `decode()` embeds a token that is
not among them, because prefill's own row — the token being predicted — has not
been written to KV. Restoring the KV without the token leaves the session with
nothing valid to embed.

## What was wrong

`Session::restore()` did this:

```cpp
s->pending = -1;
s->last_id = -1;
```

So every restored session was one token short of a continuation. Two different
failures followed from that one line:

* **restore → decode** fed id `-1` to the embedding graph on the first step.
  The graph gathers by id, so this is an out-of-bounds read on the device: it
  returns whatever sits before the table (silently wrong tokens) or aborts.
* **restore → extend** was fine by accident, because `extend()` overwrites
  `last_id` from its own `lm_head` call and never reads the restored one. That
  accident hid the bug: the tool that exercised both paths only asserted on the
  extend path's return code, so a restore that was not a continuation still
  printed `OK`.

There were three more gaps in the same area:

1. `Snapshot` did not carry `pending`. A snapshot taken between `prefill()` and
   the first `decode()` therefore restored into a session that started one
   token later than the original — the two streams differed by exactly one.
2. `restore()` accepted a snapshot of any length and copied it into the
   session's buffers without checking it fits the model's context.
3. `decode()` on a session with no token at all (before any prefill, or after a
   restore that dropped `last_id`) submitted `-1` to the graph instead of
   refusing.

## What the engine does now

* `Snapshot` carries `len`, `pos_next`, `last_id` and `pending`; `restore()`
  puts all four back. `pending` matters as much as `last_id`: the session must
  hand back the *same* token the original would have.
* `restore()` rejects `len <= 0` or `len >= seq_len` before touching a buffer.
* `decode()` refuses a session with no token (`last_id < 0`) and says so,
  instead of launching an out-of-range embedding.
* `activate(true)` — which `restore()` uses — zeroes the whole per-layer state,
  FA KV included, so slots the snapshot leaves empty cannot carry a previous,
  longer session's KV. This was already true; it is now stated where the
  invariant is relied on.

`restore()` deliberately does **not** restore into a session's old state; it is
"become this prefix", not "merge into what I had". `extend()` after it is the
scheduler's resume path and appends the remaining prompt at `history`.

## Token ids are range-checked before any launch

`Session::prefill_impl()` now rejects a prompt containing a token id outside
`[0, vocab)` before it submits anything:

* the id would be an out-of-bounds gather inside the embedding graph — the TPU
  has no way to report it as a bad argument, it reads garbage or aborts;
* an abort sets `fault`, which refuses all further work until reboot. That is
  the wrong response to a caller's bug, so the check is a plain `fail()`:
  `fault` stays clear, the session is untouched, and a retry with a valid
  prompt works.

The bmodel does not carry the vocabulary size: `lm_head` fuses its argmax, so
the vocabulary never appears in a graph shape. The tokenizer knows it, and the
tokenizer sits behind its own opaque handle, so the C ABI gained
`llm_engine_set_vocab_size()` and the worker calls it right after loading the
tokenizer (`app/engine/native.py`). `0` (never set) disables the check, so an
older `.so` still loads.

## Load-time guard on the shared prefill buffers

`pf_in[]`/`pf_out[]` are allocated from one template layer per kind (`block_0`
for linear, `block_<FA-1>` for FA) and handed to every layer of that kind. That
is sound only while the template is the widest of its kind; a wider layer would
read or write past the end of the buffer, which on the device is a silent OOB
inside the TPU. `load()` now compares each layer's stage-0 IO against the shared
buffer and refuses a bmodel that does not fit. Shipped bmodels are uniform, so
this guards a malformed file rather than a supported layout.

## Host verification

```sh
tests/native/run_tests.sh /path/to/libsophon/include
python3 -m pytest -q
```

`tests/native/run_tests.sh` now runs 104 checks (was 61). The new ones, and what
each would catch:

| test | asserts |
|------|---------|
| `test_restore_then_extend_continues_the_snapshot` | a 64-row extend after restore runs `block_kv` **once**, with past-KV length exactly the snapshot's; only the 64 new rows are prefilled; a short extend writes its first FA KV row at slot `history` |
| `test_out_of_range_token_is_rejected_before_any_launch` | no launch, no `fault`, a `last_error` naming the token, and the session unchanged |
| `test_snapshot_keeps_the_pending_token` | a snapshot taken before the first `decode()` hands back the same token, with no graph run |
| `test_decode_rejects_a_missing_last_token` | an empty session's `decode()` is refused, not launched |

Each was checked by reverting the fix and watching it fail: dropping
`snap->last_id`/`snap->pending` fails 6 checks, disabling the range check fails
7, decrementing the restored length fails 9.

`pytest` grew two tests: `test_the_backend_tells_the_engine_the_tokenizers_vocabulary_size`
(the board-side wiring above) and `tests/test_tool_bindings.py`, which requires
every `llm_*` call in every `tools/*.py` to declare `argtypes`.

## The fixture was hiding the extend path

Two defects in `tests/native/fake_bm.h` meant none of the above could have been
caught before:

* a linear `block_<i>` declared **1 input / 1 output**. A real history bmodel's
  prefill linear block takes `(hidden, rec_state, conv_state)` and returns
  `(hidden, conv_state)`, with `rec_state` updated in place. The fixture now
  matches, so `prefill_impl`'s linear branch actually runs.
* the FA `block_<i>` always had a third (mask) input, i.e. `prefill_mask = 1`.
  The shipped 35B history bmodels report `prefill_mask = 0`, and the engine
  deliberately refuses `extend` on a masked prefill graph — so `extend()` could
  never reach the prefill path under test. `build()` takes `prefill_mask` and
  defaults to the shipped layout.

Fixing the first one exposed a real heap-buffer-overflow read in the engine
(`mem_size(pout[1])` past the end of a 1-output block's vector) that ASan found
immediately and the assertions alone would not have.

## `tools/session_bench.py`: the crash was in the tool

`session_bench.py` called `llm_session_extend` without declaring its
`argtypes`, while `llm_session_prefill` — same signature — had them. Without
`argtypes`, ctypes converts a ctypes array to a C `int`, i.e. truncates the
pointer to 32 bits. gdb on the reproduction:

```
Program received signal SIGSEGV
Session::prefill_impl (this=this@entry=0x5569cb90, tokens=0x7ffff733ee20, n=4, append=true)
rdi  0x5569cb90     <- truncated session handle
rsi  0x7ffff733ee20 <- the real one
```

The session pointer `0x7fff…` arrived as `0x5569cb90`. So the restore→extend
path in that tool crashed **before reaching the engine**, on both `origin/main`
and this branch. It is not evidence about the engine, and it must not be cited
as the board's snapshot-path SIGSEGV without reproducing on the fixed tool.

Fixed here (`llm_session_extend.argtypes = llm_session_prefill.argtypes`), and
guarded by `tests/test_tool_bindings.py`.

The tool's restore→extend check was also too weak — it printed `history=N` and
never compared tokens, so a wrong continuation looked like a pass. It now
restores one snapshot twice, extends both with the same 4 tokens, and compares
the generated continuations.

## Still open: the board's `bmdrv_thread_sync_api` timeout

Nothing above explains a driver timeout or a `bdc_reg_read` oops, and this
branch does not claim to. What it does contribute is a ranked set of hypotheses
and, for each, the cheapest test that would falsify it.

1. **A truncated handle or pointer on the way into the engine** (the
   `session_bench.py` defect above). It reproduces as a user-space SIGSEGV, not
   a driver timeout, so it does not match the reported signature — but it is
   the one confirmed defect in the exact tool that produced the failing run.
   *Status:* the fixed tool has now run on 10.42 and the restore→extend section
   printed its two-restore comparison, so this hypothesis is falsified as the
   cause of the timeout. It remains a real defect, fixed here.
2. **Short dynamic prefill widths.** The engine already carries independent
   evidence for this (`kAlign`, `llm_engine.cpp`: 2- and 5-row dynamic widths
   hung the TPU with the same 120 s timeout and oops after a restored
   2048-token state; every 64-row width was fine). The current PNG runs are
   280–326 tokens, so the last chunk is short and *is* replayed — but replay
   uses the decode graphs, which are static-shaped and were stable. A restored
   prefix changes the arithmetic: `L = (cur / 64) * 64` is computed from the
   chunk width, not from `old + cur`.
   *Falsify:* on an exclusive board, `LLM_TRACE=1` around a restored-prefix
   prefill and check no `block_<i>` launch has a row count that is not a
   multiple of 64, and that `old` at that launch equals the snapshot length.
3. **Park/unpark state swap under interleaved sessions.** `park()` copies only
   `[parked_kv, history)` of the FA buffers, relying on append-only growth and
   on `activate(fresh)` having zeroed the rest. Every path in this tree
   satisfies that, but it is an invariant across three functions with no
   assertion.
   *Falsify:* on the host, drive `A,B,A,B…` where A is snapshotted, restored,
   decayed and re-extended, and compare A's token stream against A run alone —
   the fake model cannot do this today because its tokens derive from buffer
   addresses. On the board, `session_bench.py`'s interleaved rounds already
   compare against solo runs.
4. **Board/driver health, independent of this code.** `docs/DESIGN.md` records
   that the unmodified vendor demo also kills this board, with the same
   `bdc_reg_read` abort, and that the kernel, libbmrt, bmtpu.ko and bmodel md5
   match the working MYS-2282 machine.
   *Falsify:* the same controlled sequence on a second known-good board.

What is **not** supported by evidence: PNG preprocessing, ctypes vit pointers
and two-session concurrency as sufficient causes — the crossed cases all passed
— and #13/#14 as regressions, since the unmodified baseline failed too.

## Board results (v0.6.3)

Run on 10.42.0.242 with the 2B model for the session bench and the released
35B 32k history bmodel for the cache check, after the fixes in this document
landed on `main`:

* `tools/session_bench.py` (2B) — two sessions advanced their history correctly
  over two rounds, restore→decode produced the same 8 tokens, two restores of
  one snapshot extended to the same continuation, and the run ended
  `SESSIONS OK`.
* `tools/cache_check.py` (35B 32k) — cache recall, the restore cut point, and
  the recall after it all passed: `ALL PASS`.
* Kernel counters for the boot (`bmdrv_thread_sync_api`, `bdc_reg_read`, `BUG:`,
  `Oops`) were 0.

That verifies the snapshot and session paths this document is about. It does
**not** close the driver-timeout investigation: the synthesised-PNG case that
produced the original failure has not been reproduced since, so there is still
no root cause for it, and none of the above is evidence that it is fixed.

## Board steps still required

This branch changes the engine and a tool, so the device is the only place the
remaining questions can be settled. In order, on an **exclusive** board:

1. ~~`bash tests/native/run_tests.sh` and `python3 -m pytest -q`~~ — host only,
   done: 104 checks / 0 failures, 330 passed with `jinja2` and `websockets 14.2`
   (312 passed / 18 skipped without `jinja2`).
2. ~~`tools/session_bench.py` with the fixed bindings~~ — done, `SESSIONS OK`.
3. ~~`tools/cache_check.py`~~ — done, `ALL PASS`.
4. Still open: the PNG/multi-session sequence from the parent issue, one
   variable at a time, with `LLM_TRACE=1`. This is what hypotheses 2 and 3 above
   need, and it is deliberately last: it is the sequence that killed the board
   before.
