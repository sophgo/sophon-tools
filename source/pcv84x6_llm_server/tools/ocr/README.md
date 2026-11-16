# OCR on CV84X6 — bmodels, package config, golden

Three deliverables live here, and they answer three different questions:

| path | question it answers |
| --- | --- |
| `model-config/ppocr_v6/`, `model-config/paddleocr_vl_1_5/` | what the runtime must do to the pixels and to the tokens, and where every number came from |
| `tools/ocr/*.sh`, `tools/ocr/paddleocr_vl_convert.py` | how the bmodels in dfss were produced, reproducibly |
| `tests/data/ocr/golden.json` + `tests/test_ocr_assets.py` | what "correct" looked like on x86 before the board ever ran it |

The bmodel files themselves are **not** in git — they go to dfss next to the
existing ones (`/mnt/sda2/cv84x6_llm_server/build_ocr/out/` on the build host).
What is in git is everything needed to rebuild them and to check the result.

## Models

| model | bmodel | input | output |
| --- | --- | --- | --- |
| PP-OCRv6 medium det | `ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel` | `[1,3,736,736]` f32 | `[1,1,736,736]` f32 (sigmoid) |
| PP-OCRv6 medium rec @320 | `ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel` | `[1,3,48,320]` f32 | `[1,40,18710]` f32 (softmax) |
| PP-OCRv6 medium rec @640 | `ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel` | `[1,3,48,640]` f32 | `[1,80,18710]` f32 (softmax) |
| PP-OCRv6 medium rec @1600 | `ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel` | `[1,3,48,1600]` f32 | `[1,200,18710]` f32 (softmax) |
| PaddleOCR-VL-1.5 | `paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static_20261103.bmodel` | see below | 40 networks |

CV84X6 is `bm1684x2` in tpu-mlir. There is no `cv84x6` chip name; passing one
fails argument parsing.

**Rec is three models, not one.** The caller picks the tier from the crop's
aspect ratio (`model-config/ppocr_v6/ppocr.json` →
`rec.width_selection`): ratio ≤ 6.667 → 320, ≤ 13.333 → 640, ≤ 33.333 → 1600.
A single dynamic-width model would work but loses the compiler's static
scheduling for no benefit here.

1600 is required, not optional: with 640 as the ceiling a 34.8:1 report line is
squashed 2.3× and decodes as garbage. 3200 was built and measured — identical
text, twice the time — and deliberately not shipped.

**No direction classifier.** The PP-OCRv6 det+rec path in sophon-demo does not
invoke cls, so none was built. Recorded explicitly in `ppocr.json` under `cls`.

## Building

### Container

The existing `tpuc22` container holds tpu-mlir 1.30.2 (`1.30.2-20260831`) on
Ubuntu 22.04, and is shared with the 35B builds. Do not modify its
site-packages — that is exactly the trap MYS-2588 hit. Work in a separate
container from a committed snapshot, or at minimum never edit files under
`dist-packages`.

```bash
docker commit tpuc22 ocr-tpu:1.30.2
docker run -d --name tpuc_ocr \
  -v /home/zzt/workspace/tpu-mlir-toolchain:/tc:ro \
  -v /mnt/sda2/cv84x6_llm_server/build_ocr:/workspace \
  ocr-tpu:1.30.2 sleep infinity
```

### Weights and ONNX

Official inference models (PaddleOCR v3 model list) → onnx with paddle2onnx:

```bash
paddle2onnx --model_dir <official_inference_dir> \
            --model_params_filename inference.pdiparams \
            --model_filename inference.json \
            --save_file ppocrv6_medium_det.onnx
```

PaddleOCR-VL-1.5 comes from ModelScope (`PaddlePaddle/PaddleOCR-VL-1.5`) as a
plain HF directory; `llm_convert` reads the safetensors directly.

### PP-OCR

```bash
# inside tpuc_ocr, with the onnx files in /workspace/work
tools/ocr/build_ppocr.sh /workspace/work /workspace/out
```

About a minute per model. Both use `--quantize F16`.

The det model at 736×736 is a straight recompile of the same ONNX MYS-2551
used; it is rebuilt here rather than copied so the artifact matches the script
in this repo byte for byte.

### PaddleOCR-VL-1.5

```bash
tools/ocr/build_paddleocr_vl.sh /workspace/work/PaddleOCR-VL-1.5 /workspace/out
```

~20 minutes, 2.1 GB output, 40 networks. Requires `transformers` in the
container that knows `paddleocr_vl` (the base image does).

### Five converter defects this needs

The container's `PaddleOCRVLConverter.py` was written for the 0.9B release and
aborts on 1.5. `tools/ocr/paddleocr_vl_convert.py` patches it **in memory**
before importing, so site-packages is untouched. Each patch asserts it hits
exactly once; a silent miss would ship a bmodel built by the broken path.

1. **vit position-embedding interpolation.** `top.Interp` computes
   `H' = H × scale_h`; the converter passes `(grid-1)/(src-1)` but declares
   `grid`. For 784×784 that is `27 × 55/26 = 57` against a declared 56 →
   `error infer shape: 1 1152 57 57`. The reference uses
   `F.interpolate(size=...)`, so `scale = grid/src` is the correct expression.
2. **vit attention reshape rank.** After the attention permute the converter
   reshapes with `[-1, embed_dim]` (2 dims) while declaring a rank-3 result.
   The following `Add`/linear abort. Reference keeps the batch axis
   (`reshape(1, -1, embed_dim)`).
3. **`mlp_AR` permute declares its input shape.** `order=[0,1,3,2,4,5]` swaps
   dims 2 and 3, but the result type repeats the input
   (`1×28×2×28×2×1152` instead of `1×28×28×2×2×1152`).
4. **Duplicate loc name.** The K transpose before the attention matmul reuses
   `attn_k + ".permute"`. tpu-mlir asserts loc names are unique and aborts the
   module (`all_names.find(name) == all_names.end()`, Module.cpp:2120).
5. **mrope.** The converter calls the base 1-D `apply_rotary_pos` with a
   `[3, dim]` position tensor, and the naive fix (gather row 0 for all dims)
   is **wrong for image tokens**. 1.5 splits the head by
   `rope_scaling.mrope_section` `[16,24,24]` → `[32,48,48]`, taking 32 dims from
   the temporal row, 48 from the height row and 48 from the width row. Those
   three rows coincide only where t == h == w, i.e. for text; every image token
   has a constant t and grid-dependent h/w.

   The patch therefore gathers all three rows in one `Gather` over the `[3, seq]`
   index (the shape Qwen2VL's converter uses for the same mrope), slices the
   three sections out of the result and concatenates them. Gathering per row
   instead compiles through TOP but crashes `tpuc-opt` in `address-assign` on
   `bm1684x2`, so the single-Gather form is the one that works, not merely the
   tidier one. The frequency table must **not** be pre-halved —
   `rope_mode="contiguous_halves"` already halves internally.

   Getting this wrong is silent: the model keeps answering, it just stops
   depending on where a patch sits in the image. Measured on this config
   (head_dim 128, theta 500000), one image token at (t,h,w)=(5,12,18) puts
   58/128 cosines and 96/128 sines on the wrong angle, max |diff| 1.89.
   `tools/ocr/check_vl_mrope.py` recomputes both tables; the text case reads
   0/0, which is exactly why a text-only smoke test passed before.

If a future tpu-mlir ships a fixed converter, delete the shim and call
`llm_convert.py` directly; the script's argument list is the same.

### VL bmodel network layout

40 networks: `vit`, `embedding`, `lm_head`, `embedding_cache`, 18 ×
`block_cache_N` (decode) and 18 × `block_N` (prefill). Inputs/outputs for each
are in `model_tool --info`, and the runtime counterpart that already drives this
layout is `sophon-demo sample/PaddleOCR-VL/python/paddleocr_vl.py`.

## Golden

```bash
python3 tools/ocr/make_golden.py \
  --onnx-dir <dir with the two ppocr onnx> \
  --vl-model <PaddleOCR-VL-1.5 dir> \
  --img-dir tests/data/ocr/img \
  --out tests/data/ocr
```

Needs onnxruntime, opencv, pyclipper, shapely, torch, transformers and
(optionally) `paddleocr`. ~15 minutes on CPU. Writes
`tests/data/ocr/golden.json`.

What it records:

- **det**, per image: the four-point boxes, per-box scores, and the summary
  stats of the raw probability map (mean and the count of pixels above
  `thresh`) — the map itself would blow the 1 MB budget.
- **rec**, per image per detected line: the decoded text, its confidence, the
  width tier, and the input/output shapes. This is the number the ≥95 %
  agreement criterion is computed on.
- **`paddleocr_reference`**: the same images through the official package, as a
  second opinion on our pre/post-processing.
- **PaddleOCR-VL**, 3 images × 2 prompts: output text, plus `input_ids`,
  `pixel_values` shape, `image_grid_thw` and `image_token_count`. Stage 2 needs
  those inputs to align image embeddings token for token.
- **`provenance`**: onnx/dict SHA-256 and the onnxruntime version, so a later
  reader can tell whether the golden still corresponds to the bmodel.

## Test images

`tests/data/ocr/img/` — 7 images, ≤300 KB each, ≤2 MB total: Chinese document,
English report, mixed Chinese/English spec, a Chinese table, a UI screenshot,
vertical (top-to-bottom) Chinese, and skewed long lines. The last two are the
ones that break naive preprocessing.

### The tensor golden (`postprocess.npz`)

`golden.json` pins what the pipeline *produces*; it cannot tell a post-processing
bug from a detection bug, because a wrong box is a wrong box either way. So the
two tensors the bmodels emit are recorded separately:

```bash
PYTHONPATH=. python3 tools/ocr/make_postprocess_golden.py \
  --onnx-dir <dir with the two ppocr onnx>
```

Writes `tests/data/ocr/postprocess.npz` (7.3 MB, 110 tensors):

- `det/<image>` — the detector's probability map cropped to the region DB reads.
  **float32**, deliberately: quantising it to f16 moves boxes by hundreds of
  pixels on five of the seven images, because `thresh`/`box_thresh` sit on the
  edge of the distribution and a half-float rounding flips candidate contours in
  and out.
- `rec/<image>/<line>` — the recogniser's `[T, C]` softmax output per det crop.
  **float16**: decoded text is identical for all 103 lines and confidence moves
  by at most 1.6e-4, while the file is 7.7 MB instead of 543 MB.
  `tests/test_ocr_postprocess.py` asserts that equality rather than assuming it.

## Tests

```bash
python -m pytest -q tests/test_ocr_assets.py tests/test_ocr_postprocess.py \
                      tests/test_ocr_api.py
```

- `test_ocr_assets.py` — dictionary↔model consistency (18708 lines + blank +
  space = 18710 classes), config↔bmodel shape agreement, golden completeness,
  and that the VL config directory carries no weights. No onnxruntime/torch
  needed, so it also runs on the board.
- `test_ocr_postprocess.py` — the pipeline against `postprocess.npz`: boxes to
  the pixel, all 103 lines' text, the width-tier table, the crop geometry, CTC,
  reading order, and the backend wiring end to end. Needs opencv + pyclipper.
- `test_ocr_api.py` — `POST /v1/ocr` over the mock backend: both body forms,
  every spelling of `image`, the size/decode/kind refusals, `return_boxes`, and
  the record.

## Board acceptance

Three scripts, each answering a different question. All need the library built
on the board (`native/`, cmake) and the four bmodels in a directory.

| script | question |
|---|---|
| `board_acceptance.py` | does the pipeline reproduce the golden, and what does it cost? (drives `OcrBackend` directly, prints per-image text/box/time/NPU) |
| `board_http_acceptance.py` | the same over HTTP: starts the service, loads the model through the console API, posts multipart to `/v1/ocr` |
| `board_download_check.py` | the console's download → verify → install → scan path, serving the real bmodels from a local http server (dfss is not reachable from the test site) |

And one diagnostic:

`attribute_box_deviation.py` separates "our arithmetic is wrong" from "the
bmodel's f16 differs from the f32 reference" when a box misses the 3 px budget.
It feeds the golden's own f32 map to `det_postprocess` on the board (must give
0 px), compares the NPU's map with it, and sweeps `thresh` to show how far the
contour sits from the decision boundary. Measured on `.151`: 0 px on the
reference input, 22 threshold-crossing pixels out of ~21000 on the bmodel's, and
one box moving 0↔4 px under a ±0.004 threshold change.
