# Qwen3-Embedding-0.6B on CV84X6

Reproducible build of the embedding bmodel this service ships, and the two
measurements MYS-2696 was decided on.

The shipped default is **seq2048** (bf16, bm1684x2, 4 cores, static). It replaced
the vendor's seq8192 file in `ext_model_information/LLM/LLM-TPU/`; the vectors
are the same, the per-text cost is not. Since MYS-2706 there is also **seq512**
as an optional short-text档 -- same weights, `-s 512`, ~3.5x faster on a short
text, and the same vectors (see below).

## Dynamic shape and other sequence lengths (MYS-2702)

MYS-2702 asked whether a `--dynamic` build, or a set of static builds at
different lengths, would be better than the shipped static 2048. The answer and
all the numbers are in [`docs/research/aux-dynamic-seq.md`](../../docs/research/aux-dynamic-seq.md).
These are the tools it used, in the order a rerun needs them:

| tool | what it does |
|---|---|
| `setup_xlm_roberta.py` | patches the build container so it can compile bge-reranker-v2-m3 at all (tpu-mlir 1.30.2-38 ships no `XLMRobertaConverter`). `--revert` undoes it |
| `dl_rerank.py` | downloads the reranker checkpoint from ModelScope (15x faster than HF on this host) |
| `aux_seq_sweep.py` | per-length sweep of any number of builds: median/min/first latency at each grid length, plus cross-build cosine (embed) or logit delta (rerank) |
| `aux_hf_reference.py` | the same texts through the original PyTorch checkpoint — the out-of-band answer. Runs in the build container (needs torch) |
| `aux_vs_hf.py` | compares a board build against that HF reference |

Two things these tools encode that cost time to learn:

* **Load one model at a time.** Each build is 1.1–1.5 GiB of device heap; a
  sweep that opens five at once fails on the heap instead of measuring.
* **`--dynamic` on the reranker wedges the NPU** — the process goes to `D` in
  `bmdrv_thread_sync_api` and only `systemctl reboot --force --force` recovers
  it. `aux_seq_sweep.py --kind rerank` is safe with static builds only.

## Why the length matters

The bmodel is `_static_`, so one forward pass computes all `SEQLEN` positions
regardless of how many tokens the input actually has. The compiled length *is*
the per-text cost. Measured on `.157`, one text, median of ten, through
`libcv84x6_llm.so` (`cmp_models.py`):

| build | single text | 4-text batch | loaded (NPU heap delta) |
|---|---|---|---|
| seq8192 (was shipped) | 2811 ms | 11201 ms | 2605 MiB |
| **seq2048 (default)** | **291 ms** | **1165 ms** | **1465 MiB** |
| **seq512 (short-text档, MYS-2706)** | **82 ms** | — | **1217 MiB** |
| seq1024 (comparison only) | 136 ms | 545 ms | 1298 MiB |

The seq512 row is MYS-2706's rerun of the same measurement on the same board
(`seq512_bench.py`, four 41-74 token Chinese inputs, median of ten each; the
static graph makes the length irrelevant). The batch column was not re-measured
for it. Through HTTP the same call is 105 ms.

Through HTTP, against the 0.6.29 service on the same board: 313 ms median per
`/v1/embeddings` call, and a 72-chunk knowledge-base build went from **201.3 s
to 23.0 s** (`board_kb_time.sh`). That is the P1 finding in
`docs/e2e-0.6.29.md` addressed: an embed request no longer holds the NPU for
three seconds at a time.

## Building it

```shell
# on the build host (13.24); needs the embed_build container
tools/embed/build_bmodel.sh 2048      # shipped
tools/embed/build_bmodel.sh 1024      # comparison only, not published
```

The container's `/workspace` is `/mnt/sda2/cv84x6_llm_server/build_embed`:

```
weights/Qwen3-Embedding-0.6B      ModelScope download (keys unprefixed)
tpuc/Qwen3-Embedding-0.6B         same weights, keys prefixed for tpu-mlir
out_seq2048/                      output
```

Create the container with:

```shell
docker run -d --name embed_build \
  -v /mnt/sda2/cv84x6_llm_server/build_embed:/workspace ocr-tpu:1.30.2 sleep infinity
```

### The checkpoint needs a key prefix

`llm_convert.py -m <dir>` cannot read the published `Qwen/Qwen3-Embedding-0.6B`
checkpoint as downloaded. tpu-mlir's qwen3 weight map (`LlmInfo.COMMON_INFO`)
addresses the decoder as `model.layers.<i>.…`, `model.embed_tokens` and
`model.norm`; the checkpoint -- identical on HuggingFace and ModelScope -- stores
`layers.<i>.…`, `embed_tokens.weight` and `norm.weight`. Conversion dies on the
first block:

```
RuntimeError: Can't find key: model.layers.1.input_layernorm
```

`fix_weight_prefix.py` writes a copy whose header carries the prefix, leaving the
tensor bytes untouched, and `build_bmodel.sh` runs it when the copy is missing.
Do not "fix" this by patching tpu-mlir: the same container builds the 35B and the
ASR models.

## Checking the build

`cmp_models.py` embeds a mixed corpus through two or more builds and reports the
per-text cosine and the latency:

```shell
# on the board
python3 cmp_models.py --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
  --config /opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding \
  --model old=seq8192.bmodel --model new=seq2048.bmodel --repeats 10
```

The corpus spans 1 to 1932 tokens across Chinese, English, digits, punctuation,
emoji, code and tables. Padding is masked, so the vectors should not move; the
acceptance bar is cosine >= 0.999 per text. The seq2048 build measures
**0.99963 minimum** over 24 texts, and is identical to seq1024's vectors to
seven decimals on every text both accept.

`kb_recheck.py` answers the question a user actually asks -- does an existing
library still retrieve the same chunks:

```shell
python3 kb_recheck.py --lib … --config … --old seq8192.bmodel --new seq2048.bmodel \
  --library /data/cv84x6_llm_server/apps/kb/<id> --top 3
```

Against the 284-chunk demo library on `.157`, all six probe queries return the
same top-3 chunks under both builds. **No rebuild is needed.**

`mem_probe.py` reports what a build costs the NPU heap, measured as the heap
delta across `cv_embed_create` -- not from `bmrt_get_bmodel_info`, whose `io_mem`
over-states a build by hundreds of MiB (see `docs/model-settings.md`).

### The MYS-2706 measurements

```shell
# per-text cost and heap, both builds, in one process (loads them one at a time,
# then together) -- writes nothing, releases everything it opens
python3 seq512_bench.py

# the six demo-library queries under both builds; exits non-zero on any diff
python3 kb_recheck.py --lib … --config … --old seq2048.bmodel --new seq512.bmodel \
  --library /data/cv84x6_llm_server/apps/kb/<id> --top 3

# a real library built through /api/apps/kb on the seq512 build: end-to-end
# time, and what fraction of the chunks the 512-token limit splits (measured
# with the model's own tokenizer, not from character counts)
python3 board_kb_seq512.py 6 qwen3-embedding-0.6b-seq512
```

`seq512_bench.py` exists because the two figures it prints answer different
questions and neither is derivable from the other: 82 ms vs 292 ms is why the
档 exists. The "together" figure (+907 MiB for the second build, 2372 total)
is measured with both builds in **one process**, where the runtime reuses the
weights; the service runs each model in its own worker process, so two resident
builds there cost the sum (~2682 MiB). Do not use the in-process figure for
capacity planning.

`board_seq512_side.sh` starts the side instance those tools talk to (port 8031,
its own data root and model tree, the branch's `app/`). It does not touch the
installed 0.6.28 service.

## Publishing

The file is published under `/tools/cv84x6_llm_server/` with a download tag, so
an installed seq8192 board is offered the update. `docs/model-release.md` §2 has
the full procedure; the two files to add are:

```
qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel
qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel.md5
```

and the two lines to add to `.dfss_down_flag`:

```
cv84x6_llm_qwen3-embedding-0.6b     qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel
cv84x6_llm_qwen3-embedding-0.6b.md5 qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel.md5
```

The md5 sidecar is `<md5>  <filename>` (`md5sum` format); the catalogue's `md5`
and `size_bytes` for the entry are the same values, and are already set in
`app/core/downloader.py`.

### The seq512 short-text档 (MYS-2706)

Same procedure, its **own** tag -- `cv84x6_llm_qwen3-embedding-0.6b-seq512`, not
the seq2048 one. Two separate tags is deliberate: repointing the default tag
must never move a board onto the shorter graph, which would push every
1000-character chunk through the split-and-pool path.

```
qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel
qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel.md5
```

and the two lines to add to `.dfss_down_flag`:

```
cv84x6_llm_qwen3-embedding-0.6b-seq512     qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel
cv84x6_llm_qwen3-embedding-0.6b-seq512.md5 qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel.md5
```

`md5 864f09b7e7e2a37d420243d8be7a8346`, 1205460992 bytes. Build it with
`tools/embed/build_bmodel.sh 512`; the output lands in `out_seq512/`.

**It is a second build, not a replacement.** The two share `vector_family` in the
catalogue, so a knowledge base moves between them without a rebuild; see
`docs/aux-models.md` for what that does and does not cover.

`dfss --upflag` is **not** how these files are published: it is the customer drop
path, and it renames what it uploads to `<timestamp>_<name>`, which a tag cannot
point at. Use the maintainer account's sftp write access.
