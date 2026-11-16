# CV84X6 prefill precision: Qwen3.5/3.6-35B-A3B

These tools located the cause of wrong long-context answers in MYS-2293. Ground truth is the
HF `transformers` model on CPU, built from the same int4 AutoRound checkpoint (GPTQ dequantised to bf16).

## Findings (2026-10-25, tpu-mlir 1.30.2, bm1684x2 4-core, libsophon on board 2282)

1. **The routed-expert MoE in the prefill graphs (`block_<i>` / `block_kv_<i>`, many tokens per launch) is
   inaccurate on the device.** The single-token decode graphs (`block_cache_<i>`) are accurate.
   The table compares layer 0 (`block_0`, 2048 real tokens) with HF, op by op, using `run_dbg.py`
   and `cmp_dbg.py`:

   | tensor | device vs HF (cos, mean) |
   |---|---|
   | chunk_gated_delta_rule (linear attention core) | 0.99996 |
   | linear_attn.out_proj.add (attention + residual) | 0.99998 |
   | shared expert | 0.99988 |
   | **routed experts** | **0.754** |
   | expert set chosen by top-k | identical in 91% of rows |

   The fp32 top-level MLIR and the bf16 tpu-level interpreter both match HF for every op except the
   routed experts. The CPU interpreter does not evaluate those (its output is all zeros), so the error is
   in the device kernel of `tpu.Mlp {is_expert = true}` for seq_len > 1. Compiling the router top-k with
   `use_hau=False` changes nothing.

2. **The error builds up across layers.** These are the last-layer cos to HF, averaged over 512 positions (`lc_rows.py`, `cmp_layers.py`):

   | layer | decode graphs | prefill graphs |
   |---|---|---|
   | 0 | 0.9999 | 0.9889 |
   | 3 | 0.9995 | 0.9766 |
   | 15 | 0.9847 | 0.8977 |
   | 39 | 0.9167 | 0.8122 |

   **The vendor's own `qwen3.5-35b-int4-autoround_w4bf16_seq2048_cv84x6_4core_dynamic_20260917` bmodel
   shows the same thing** (layer 0: 0.9893, layer 39: 0.8490), so this is not specific to our builds. Chunk
   size (64…2048) and 16/64 alignment make no difference.

3. **Dynamic prefill with a few rows can hang the TPU.** For example, 2 or 5 rows after a restored
   2048-token state timed out in the driver (`bmdrv_thread_sync_api ... wait api timeout`, then a
   `bdc_reg_read` oops) and needed a reboot. This reproduced with the v0.4.0 engine too.

## What the engine does about it (v0.5.0)

* Dynamic prefill graphs only ever run on multiples of 64 rows. The rest of a chunk goes through the
  decode graphs, and so does every chunk shorter than 64 rows. Removes the hang in 3.
* For prompts of 2048+ tokens, the last `prefill_exact_tail` tokens (64 by default; console setting) are
  prefilled through the decode graphs. Because the linear-attention state decays, this corrects most of the
  state the answer is generated from: final-position cos to HF rose from ~0.87 to ~0.95 with 128+ replayed
  tokens. The 15523-token "repeat forever" prompt that stopped after one word now continues as HF
  predicts (HF: 96% continue). Cost: ~40 ms per replayed token.
* A real fix needs the vendor kernel for multi-token expert MLP.

## Reproduce

```
# board: per-layer capture, prefill vs decode path (needs the debug engine build)
LLM_DEBUG_HIDDEN=2 python3 lc_rows.py --model X.bmodel --config cfg/ --lib libcv84x6_llm.so \
    --chunks 512 --n 512 --replay 512 --layers 0,3,15,39 --out rows/
# host: HF reference, then compare
python3 hf_layers.py --hf <ckpt> --n 512 --out hf_layers.npz
python3 cmp_layers.py hf_layers.npz rows/

# op level: expose intermediates of block_0, compile, run alone on the board
python3 add_outputs.py block_0.mlir block_0_dbg.mlir <loc names...>
model_deploy.py --mlir block_0_dbg.mlir --chip bm1684x2 --model dbg.bmodel --quantize w4bf16 \
    --q_group_size 128 --num_core 4 --high_precision --dynamic
python3 run_dbg.py dbg.bmodel in2048.npz out.npz           # on the board (sophon.sail)
python3 hf_l0.py --hf <ckpt> --input in2048.npz --out hf_l0.npz
python3 cmp_dbg.py out.npz hf_l0.npz in2048.npz
```

`LLM_PREFILL_ALIGN`, `LLM_ALIGN_ABOVE`, `LLM_DEBUG_HIDDEN` and `LLM_DEBUG_LAYER` are engine debug knobs
for these experiments. Do not set them in production.
