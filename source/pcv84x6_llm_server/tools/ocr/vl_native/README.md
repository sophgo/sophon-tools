# vl_native — PaddleOCR-VL-1.5 decode with a persistent KV cache

A single cross-compiled binary that runs one element end to end on the CV84X6
NPU: **vit → embedding → 18 prefill blocks → lm_head → per-token decode**. It
drives bmrt/bmlib directly (no sail, no Python on the board), which is why it
can do the one thing A3 could not: write `block_cache_N`'s `k_cache`/`v_cache`
outputs straight into a KV cache that outlives the launch.

## The A3 segfault, and what it actually was

A3 concluded that `block_cache_N`'s outputs "cannot leave the bmodel's own stage
memory" and that a KV cache spanning launches would need sail or a `native/`
change. Both halves of that are wrong. The crash was in the *readback*, not the
launch:

```
bm_memcpy_d2s copies bm_mem_get_device_size(src) bytes   bmlib_memory.cpp:3113
```

`Net.run()` read every output back through the descriptor it had bound. Bind
`k_cache` (a 512-byte tensor) to a 1 MiB KV cache and the readback memcpy's
1 MiB into the caller's 512-byte numpy array — heap corruption, which in
ctypes-land presents as a segfault inside bmrt.

Isolated on `.157`, one launch per process:

| case | what it does | result |
|---|---|---|
| a | outputs own exactly-sized buffers (A3 step 1) | OK |
| d | `k_cache`/`v_cache` bound into the caller's 1 MiB KV buffer, then sync | **OK** |
| e | ...then read `k_cache` back through a descriptor sized to the *tensor* | **OK** |
| f | ...then read it back through the *bound* descriptor (what A3 did) | **SIGSEGV** |

`d` is the answer to the design question: bmrt accepts caller memory for those
outputs. `f` is the answer to the root-cause question. This is KV option **(a)**
— no copies, the graph writes each new row at the offset it was handed.

## Build

```bash
tools/ocr/vl_native/build.sh          # -> tools/ocr/vl_native/out/vl_native
```

Cross-compiles with the aarch64 GCC 11.3 in this workspace against the libsophon
headers. The RPATH points at the board's `/opt/sophon/libsophon-0.4.15/lib`.

## Run

Host prepares, board runs, host compares — see `tools/ocr/vl_native_prep.py`:

```bash
# host: pack one element's patches + prompt ids
python3 tools/ocr/vl_native_prep.py prep --img page.png --label table \
    --stage 784x784 --tokenizer <model>/tokenizer.json --out work/el

# board
./vl_native --bmodel paddleocr-vl-1.5_....bmodel --work el --out el

# host: reference on the *same* patch tensor, then the diff
python3 tools/ocr/vl_native_prep.py reference --work work/el --model-dir <model>
python3 tools/ocr/vl_native_prep.py compare   --work work/el --tokenizer <model>/tokenizer.json
```

`vl_native` writes `tokens.i32`, `timings.txt`, and `vit_emb.bf16` (the vision
tower's output, so a mismatch can be attributed to the tower or to the LLM).

## Three bugs this program had, and how each presented

All three kept every tensor shape valid and kept producing tokens, so none of
them raised an error:

1. **Padding columns left unmasked in the prefill mask.** Masking only the
   causal future (`c > r`) left columns `L..SEQ-1` at zero penalty; their keys
   are `embedding(0)` pushed through 18 layers, which is not zero, so softmax
   gave them real weight. First token was `<|LOC_288|>` instead of `<fcel>`.
   The fix masks `r < c < SEQ`.
2. **Rotary table built for `L` positions but indexed to `L + max_new`.**
   Reading past the end of the vector. Correct first token, then padding.
   The fix builds the table over the whole sequence.
3. **The decode loop never fed `embedding_cache`'s output to layer 0.** It fed
   the stale prefill buffer. Correct first token, then 23 copies of token 0.
   The fix points `x_in` at the embedding for layer 0 and at the previous
   layer's output after that — taking it *after* the double-buffer swap, not
   before.

## Fixed-stage caveat

The vision tower's grid is not carried by the bmodel, and the patch count does
not name it: 576 patches is both 24x24 and 12x48. `vl576.bmodel` was compiled
from a 168x672 stage, so feeding it 336x336 pixels silently produces a different
answer (cosine 0.45 vs 0.956 against the reference for the same patch tensor).
Always pass the stage that matches the weights; `prep --stage` does this.
