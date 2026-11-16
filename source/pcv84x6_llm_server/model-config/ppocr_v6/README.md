# PP-OCRv6 medium — runtime configuration

`ppocr.json` is everything the caller needs to turn pixels into text with the
detector and three recognisers in dfss. `ppocr_keys_v1.txt` is the character
dictionary.

`layout.json` describes the fifth bmodel, the **PP-DocLayout-M** page segmenter
that `mode: "layout"` uses. It is a separate file rather than a section of
`ppocr.json` because it describes a different model family with its own
pre/post-processing, its own class list and its own bmodel — folding it into
`ppocr.json` would make one file describe two unrelated graphs, and the loader
could not refuse a half-updated pair.

## Why these numbers, and where each came from

Every value is traceable to one of two sources, and the two disagree in one
place. That is recorded rather than smoothed over.

| section | source |
| --- | --- |
| `det.preprocess`, `rec.preprocess` | the model's own `inference.yml` (`PreProcess.transform_ops`), cross-checked against `sophon-demo sample/PP-OCR/python/ppocr_{det,rec}_opencv.py` |
| `det.postprocess` | the model's own `inference.yml` (`PostProcess`) |
| `rec.postprocess` | PaddleOCR's `CTCLabelDecode` defaults plus this model's `inference.yml` |
| tensor shapes | `model_tool --info` on the compiled bmodels |

**`det.postprocess` differs from the sophon-demo python sample.** Their
`ppocr_det_opencv.py` hardcodes `thresh=0.3, box_thresh=0.6, unclip_ratio=1.5`
for PP-OCR**v4**. PP-OCRv6 ships `thresh=0.2, box_thresh=0.45,
unclip_ratio=1.4, max_candidates=3000`. The v6 model's own file wins: it is the
threshold the model was trained to produce, and using v4's numbers loses
low-confidence boxes that v6 deliberately emits. If a caller wants the v4
behaviour it can override; the default here follows the shipped model.

## The dictionary is one character short of the model on purpose

The rec bmodels emit **18710** classes. The dictionary file has **18708** lines.
The gap is not an error:

```
class 0        -> <blank>     (CTC blank, prepended by the decoder)
class 1..18708 -> ppocr_keys_v1.txt, line by line
class 18709    -> ' '         (appended by the decoder, use_space_char=True)
```

PaddleOCR appends the space character at inference time and never stores it in
the dictionary, because a literal space in a line-based text file is easy to
lose. `tests/test_ocr_assets.py` pins the arithmetic, so a dictionary that
drifts by a line fails the suite instead of silently shifting every recognised
character by one class.

## Width tiers

Rec runs at a fixed 48-pixel height and one of three widths. Pick by aspect
ratio of the *detected box*, not the page:

```
ratio = crop_width / crop_height
ratio <= 6.667    -> 320    (output [1, 40, 18710])
ratio <= 13.333   -> 640    (output [1, 80, 18710])
ratio <= 33.333   -> 1600   (output [1, 200, 18710])
otherwise         -> clamp to 1600
```

Then `resized_w = int(48 * ratio)`, right-pad to the tier width with zeros.

**640 alone is not enough, and that is measured, not theorised.** `en_report.png`
has 34.8:1 body lines. Squeezed into 640 they are compressed 2.3× horizontally
and the recogniser returns `dubuy` for a line that reads "downtime events
occurred in September…". The same crop at 1600 decodes correctly. A 3200 tier
was also compiled and measured: identical text to 1600 on every image in the
golden set, at twice the time steps (78 ms vs 26 ms on the board), so it is not
shipped. 1600 is the ceiling the model's own `inference.yml` comfortably
supports (`trt_dynamic_shapes` declares up to 3200).

The caller may prefer the narrower tier when the squash is small: the golden
generator picks the narrowest tier whose capacity is at least `1.15 ×` the
ideal width (`WIDTH_SQUASH_TOLERANCE`), which keeps short lines on 320 and
still sends the long ones to 1600.

## Cropping: warp the quadrilateral, do not take the bounding box

Det returns four points, and for skewed text an axis-aligned bounding box is
much taller than the glyphs — a 7° line yields a bbox several times the text
height, and the recogniser sees the rotation smeared across the crop. The
golden generator originally used a bbox and decoded the skewed sample as
`库盘点WarehousenySt`; with a four-point perspective warp it reads
`仓库盘点单 Warehouse Inventory Sheet`, matching the reference. Both PaddleOCR
and sophon-demo warp; an integration that only clips a rectangle will
underperform on any photographed page.

## Agreement with the official pipeline

`tests/test_ocr_assets.py::test_agreement_with_official_paddleocr` computes the
line-level agreement the acceptance criteria ask about, normalising whitespace
and full/half-width forms:

| set | agreement |
| --- | --- |
| horizontal images (6 of 7) | **94/96 = 97.9 %** |
| vertical image | 0/7 |

The split is deliberate. Vertical text is a genuine limitation of this model
pair (see below), and folding it into one number would either fail forever or
force the threshold down until the horizontal cases stopped being defended.


## No direction classifier

`sophon-demo sample/PP-OCR` does not run a cls model in the det+rec path, and
neither do we. `cls.required = false` records the decision so nobody has to
re-derive it.

The consequence is measured: the vertical-text sample (`vertical_text.png`,
traditional top-to-bottom, right-to-left Chinese) decodes as fragments — 0 of 7
lines match the reference. That is expected, not a regression: the recogniser is
trained on horizontal lines and nothing in this pipeline rotates them. Callers
that must handle rotated pages need a detection/orientation stage in front
(either a cls model or a page-orientation pass), which is out of scope here.


## Softmax is already inside the graph

Both the ONNX and the bmodel end in `Softmax`, so `argmax` over the class axis
gives the class and `max` gives a calibrated confidence in `[0,1]`. Do not apply
a second softmax — the numbers will look plausible and be wrong.

Confidence is reported as the mean over the *kept* time steps (after collapsing
repeats and dropping blanks), which is what `sophon-demo` and PaddleOCR both do.

## Golden

`tests/data/ocr/golden.json` was produced by `tools/ocr/make_golden.py` from the
same ONNX this bmodel was compiled from, and is what the board's output is
compared against. Its `provenance` block carries the ONNX and dictionary
SHA-256 so a later reader can tell whether it still corresponds.

## `layout.json` — the page segmenter

The 23-class label list is the bmodel's **class axis order**, not alphabetical
and not ours: `paragraph_title, image, text, number, abstract, content,
figure_title, formula, table, table_title, reference, doc_title, footnote,
header, algorithm, footer, seal, chart_title, chart, formula_number,
header_image, footer_image, aside_text`. Reordering it relabels every region,
which reads as "the model got worse" rather than as a configuration error, so
`load_layout_config` refuses to start if the file and the code disagree.

Values that are easy to get wrong, and why each one is what it is:

| value | source | why it matters |
| --- | --- | --- |
| `resize.side = 640` | `PP-DocLayout-M` input | It is also what page coordinates are scaled *through*; the loader refuses a file whose side disagrees with the bmodel input |
| `resize.policy = stretch_to_square` | PaddleX `Resize(keep_ratio=false)` | **Not** PP-OCR det's letterbox. Letterboxing here shifts every detected box by the pad |
| `normalize.color = RGB` | PaddleX `ToCHWImage` after BGR→RGB | The wrong channel order still produces boxes, just with lower scores — the hardest kind of bug to see |
| `threshold = 0.5` | MYS-2615's x86 comparison | It is the threshold the board was compared against; note that `0.50055`-scored boxes are unreliable under f16 (`docs/ocr-structure.md` §2) |
| `iou_same = 0.6`, `iou_diff = 0.98` | PaddleX `layout_nms` | These belong to PaddleX's layout NMS, which uses the legacy `+1` IoU — **not** the plain IoU of the NMS that was cut out of the graph |
| `merge_mode` | `PP-StructureV3.yaml` → `layout_merge_bboxes_mode` | `large` drops a box fully contained in another; unlisted classes are `union`. Getting it wrong drops the paragraph titles that sit inside a text block |

The bmodel is the **cut** graph: `tools/ocr/layout_cut.py` removed the
`MulticlassNMS`/top-k tail, because a data-dependent tail lowers to
`TPU_DYNAMIC` and wedges this chip. It therefore emits two dense tensors —
`boxes [1, 8500, 4]` and `scores [1, 23, 8500]` — and everything downstream is
the numpy transcription in `app/engine/ocr_layout.py`.

**`-M`, not `-S`.** `S` classifies a table as `image` (`cn_table_simple.png`:
`image 0.708` for S, `table 0.786` for M), and a table is exactly the region
layout mode exists to report. `S` is smaller and faster (5.3 MB / 0.97 ms vs
21.5 MB / 2.88 ms) and would be the right choice for text-only layout.
`docs/ocr-structure.md` §2 has the measurements.
