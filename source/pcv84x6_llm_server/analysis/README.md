# Decode-pipeline and queue-depth probes (MYS-2457 / MYS-2469)

Reproducible measurements behind `docs/research/decode-optimization.md` and `docs/research/bmrt-queue-depth.md`. Everything here runs on the board against the **unmodified** engine library and bmodel — no engine edit, no weight modification, no private flag. Nothing in this directory is built into the service.

Board: `10.42.0.242` (user `linaro`; credential in the device ledger), libsophon 0.4.15, model
`Qwen3.6-35B-A3B 128k`
(`qwen3.6-35b-a3b-int4-autoround_w4bf16_seq131072_bm1684x2_4core_history_dynamic_20261025_051759.bmodel`).

## Build

```sh
# engine library (already built by the service install; rebuild from source if needed)
cd native && mkdir -p build && cd build && cmake .. && make -j8

# probes (link the board's libsophon)
cd analysis
INC=/opt/sophon/libsophon-current/include
LIB=/opt/sophon/libsophon-current/lib
gcc -O2 -fPIC -shared -I$INC -o bmprof.so bmprof.c -ldl
for p in graph_probe token_probe bw_probe probe_lm overlap queue_depth io_override; do
  g++ -O2 -I$INC -o $p $p.cpp -L$LIB -lbmrt -lbmlib
done
for p in queue_model queue_scope tpu_busy token_shape graph_tpu queue_occupancy; do
  g++ -O2 -I$INC -o $p $p.cpp -L$LIB -lbmrt -lbmlib
done
g++ -O2 -pthread -I$INC -o queue_threads queue_threads.cpp -L$LIB -lbmrt -lbmlib
```

## Tools

| file | what it answers |
|---|---|
| `bmprof.c` | `LD_PRELOAD` shim: per-call CPU time inside `bmrt_launch_tensor_ex`, inside `bm_thread_sync`, and per copy, split by graph name. The engine is untouched, so the numbers describe the shipped `.so`. |
| `graph_probe.cpp` | One graph at a time: submit cost vs sync cost, per net and per decode stage. |
| `token_probe.cpp` | One decode token's real launch pattern (40 blocks queued, one sync) with `--lm` for the `lm_head` tail and `--sync-per-layer` for the pre-MYS-2377 shape. |
| `bw_probe.cpp` | Board memory bandwidth (`d2d`, `s2d`), so a graph time can be judged against the roofline. |
| `probe_lm.cpp` | Does `lm_head`'s launch block? Times it launched twice with no sync in between, and 40 launches of one block graph. |
| `overlap.cpp` | Is `lm_head` + the 40-layer chain additive (serialised) or max (overlappable)? Decides whether cross-session batching across the `lm_head` boundary can buy anything. |
| `queue_depth.cpp` | Per-launch submit time for an unsynced run of the same graph: finds the runtime's unfinished-queue depth and the cost of a full queue. |
| `io_override.cpp` | Is the chain's submit cost caused by overriding each graph's IO addresses? Compares chained vs own-template IO, submit split out. |
| `agg_probe.py` | Aggregate tok/s for N sessions interleaved, with `--quantum` to price the per-switch state copy. |
| `prefill_scaling.py` | Prefill cost vs row count: ms/row at each width, multi-chunk totals, and the `--tail` mode that grows one session by repeated `extend`. Splits prefill into a per-chunk fixed cost, a per-row marginal cost, and the O(past) attention term (MYS-2474). |
| `tok_ids.py` | Tokenise a chat-templated prompt to comma-separated ids on the board. |
| `tokdec_probe.py` | Host cost of `tokenizer_decode()` for one token (the per-token host tax). |
| `queue_model.cpp` | One graph launched N times without syncing: backlog fill point, per-launch cost, and whether wall time per layer depends on queue depth. |
| `queue_scope.cpp` | Single-thread launch costs and driver per-HWQ free slots. |
| `queue_threads.cpp` | Thread/HWQ ownership of queue stalls. |
| `queue_occupancy.cpp` | Observed queue occupancy while a chain is backlogged. |
| `tpu_busy.cpp` | Wall time vs `bm_get_profile()` TPU processing time. |
| `token_shape.cpp` | Real 40-graph token shape and empty-queue lm_head launch cost. |
| `graph_tpu.cpp` | Per-graph TPU time and the inter-graph dispatch gap. |

## Reproduce the headline numbers

```sh
M=/data/cv84x6_llm_server/models/qwen3.6-35b-a3b-128k/qwen3.6-35b-a3b-....bmodel
LIB=native/build/libcv84x6_llm.so
TOK=/opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json

# 1. baseline single-stream decode
P=$(python3 analysis/tok_ids.py --lib $LIB --tokenizer $TOK \
      --prompt "What is the capital of France?" --pad-to 64)
python3 tools/decode_bench.py --lib $LIB --model $M --tokens "$P" --decode 64 --runs 2

# 2. per-graph decomposition of the same run
BM_PROF=1 BM_PROF_OUT=/tmp/p.json BM_PROF_CALLS=/tmp/p.csv \
  LD_PRELOAD=./analysis/bmprof.so \
  python3 tools/decode_bench.py --lib $LIB --model $M --tokens "$P" --decode 64 --runs 2

# 3. lm_head alone, and the chain alone
LD_LIBRARY_PATH=/opt/sophon/libsophon-current/lib ./analysis/graph_probe $M \
  --iters 10 --net lm_head --net block_cache_0 --net block_cache_3
LD_LIBRARY_PATH=/opt/sophon/libsophon-current/lib ./analysis/token_probe $M \
  --stage 6 --iters 10 --lm

# 4. concurrency, and the per-switch tax
for q in 1 2 4 8; do
  python3 analysis/agg_probe.py --lib $LIB --model $M --prompt /tmp/p64.ids \
    --sessions 2 --decode 24 --quantum $q
done
```

## Caveats that cost a board reboot each to learn

* **Zero every graph input before launching it out of context.** The decode
  graphs index their KV/state with the position ids they are handed; template
  garbage puts that index outside the buffer, and on CV84X6 an out-of-range
  device read inside a graph is not reportable by the driver — it wedges the
  TPU (`bmdrv_thread_sync_api` timeout → `bdc_reg_read` oops → "reboot is
  needed") and the offending process becomes unkillable D-state. `graph_probe`
  and `token_probe` zero all inputs first for exactly this reason.
* **Check the row count as carefully as the input contents (MYS-2474).** A
  prefill probe that passed a pointer where `n` belonged made the engine run a
  prefill of an absurd number of rows; the FA graph then indexed past its KV
  buffer and wedged the TPU the same way, costing a board reboot. Re-derive the
  C ABI argument order from `native/src/c_api.cpp` and diff it against the call
  site — do not trust memory. `prefill_scaling.py` now refuses any `n` outside
  `(0, context)` before calling.
* **Pass a real error buffer that outlives the call.**
  `ctypes.byref(ctypes.c_char_p())` makes a temporary the callee can write
  through after it is collectable; the reference tools keep `err` on the session
  object for this reason.
* `npu_usage` in sysfs reads 0 even under full decode load, so it cannot be
  used to argue "the TPU is idle". Use the probes' own submit/sync split, or
  `bm_get_profile()` for the MYS-2469 queue measurements.
* Only one probe at a time. Two decode processes on the same TPU contend for
  the whole device, and the resulting numbers are meaningless.
* **Do not read `/proc/bmtpu/bmdi_api_info`.** It oopses the driver on CV84X6
  (`api_proc_show` → `otp_reg_read` with a null OTP base), although the device
  keeps working. `bmdi_base_info` / `bmdi_lib_info` are the same family — avoid
  them too. Use only `kernel_info` and `wakeup_control`.

## Raw data

> sophon-tools source snapshot: the board-side original logs and bulky run
> records (dmesg/journal dumps, SSE streams, NDJSON exports, the
> mys2498/mys2501/mys2502 run directories, the D7 hang-scene captures, and
> `raw/dmesg_wedged_tpu.txt` / `raw/hang_prof.csv`) are NOT distributed here --
> they stay in the upstream private repository. What ships is the measurement
> anchors the research docs' "复现" sections and the unit tests reference:
> the probe/profile CSVs, `model_info_*`, `queue_depth_table.txt`,
> `driver-evidence/`, `decode_bench_crosscheck.txt`, `mys2474/`, `mys2477/`,
> `mys2510-supplement/` and `mys2702/` (minus its hang traces).

`raw/ok_prof.csv` is the per-call log of the baseline run in the report;
`raw/hang_prof.csv` and `raw/dmesg_wedged_tpu.txt` are the wedged-TPU trace from the
probe bug described above. `raw/model_info_{128k,32k}.txt` are
`model_tool --info` dumps (read-only, from the `tpuc22` container on 13.24).
MYS-2469 queue evidence: `raw/queue_depth_table.txt` and `raw/driver-evidence/`
are the excerpts kept in git; the full board log (`board_2026-10-29.log`) is not
committed. `raw/decode_bench_crosscheck.txt` compares the queue result with the
real engine.

MYS-2501 extended stability run: `raw/mys2501/` held the delivered run on `.151`
(`0.6.14`, `qwen3.6-35b-a3b-128k`, 2100 requests + a readiness probe) upstream --
self-contained `report.html`, per-request `rounds.jsonl`, `summary.json`,
`env.json`, `samples.json`, `timeline.jsonl`, `sqlite-check.json` and a
`README.md` with the findings. As noted above, that directory is not part of
this snapshot; the bulky parts (26 MB of raw SSE bodies, the NDJSON export,
journal and dmesg) stayed on the board under
`/data/stability/evidence/run-20261031T025800Z/`.
