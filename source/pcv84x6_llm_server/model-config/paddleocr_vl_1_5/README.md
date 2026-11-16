# PaddleOCR-VL-1.5 — runtime configuration

The non-weight files the runtime needs to reproduce the reference's token
layout. Weights are not here; the bmodel is in dfss and the tokenizer weights
are regenerated from `tokenizer.json`.

| file | why the runtime needs it |
| --- | --- |
| `config.json` | text + vision hyperparameters, including `rope_scaling.mrope_section` `[16,24,24]` — the bmodel's RoPE depends on it |
| `preprocessor_config.json` | image resize/normalise: `patch_size` 14, `merge_size` 2, `temporal_patch_size` 1, `min_pixels` 112896, `max_pixels` 1003520, mean/std 0.5 |
| `processor_config.json` | ties the image processor and tokenizer together |
| `tokenizer.json`, `tokenizer.model`, `tokenizer_config.json` | the 103424-entry vocabulary |
| `added_tokens.json` | the special tokens the prompt template uses |
| `special_tokens_map.json` | which id is bos/eos/pad |
| `chat_template.jinja` | how a prompt is assembled; the `<|IMAGE_PLACEHOLDER|>` count must match the image token count |
| `generation_config.json` | greedy decode settings |

The four files that actually encode the model's structure —
`configuration_paddleocr_vl.py`, `modeling_paddleocr_vl.py`,
`image_processing_paddleocr_vl.py`, `processing_paddleocr_vl.py` — are **not**
vendored. The board runs the bmodel, not the HF modules, and copying reference
model code into a runtime config directory invites someone to import it and get
a second, divergent implementation. They live with the weights in dfss.

## The three ids that matter

```
vision_start_token_id  101305
image_token_id         100295
vision_end_token_id    101306
```

The image token is **100295**, but runtime code that searches for
`<|IMAGE_PLACEHOLDER|>` will not find it in the prompt as the model emits it —
sophon-demo's `paddleocr_vl.py` notes this explicitly and falls back to
sequential positions. Whatever the stage-2 integration does, it must agree with
the golden's `input_ids` (see below), not with what looks right in the template.

## mrope

`rope_scaling.mrope_section = [16, 24, 24]` splits the 128-wide frequency table
into temporal/height/width chunks. The reference interleaves them per token; the
compiled bmodel reduces that to a single row because every position it is given
has `t == h == w` (one row per token, single image per prompt). Both are the
same arithmetic for those positions — see `tools/ocr/paddleocr_vl_convert.py`
for the exact reduction and why it is safe.

`use_3d_rope: true` and `rope_is_neox_style: true` in `config.json` are the
switches the reference reads to pick that path.

## Golden

`tests/data/ocr/golden.json` → `paddleocr_vl.cases` holds, for 2 images × 2
prompts (`OCR:` and `Table Recognition:`):

- `output_text` — the reference generation, greedy, capped at 48 new tokens
  (CPU prefill is ~9 min/image, so the cap is what makes the run finish; the
  golden proves the layout and the opening of the answer, not a full page)
- `input_ids` — the exact prompt tokens, so stage 2 can diff token for token
- `pixel_values_shape` and `image_grid_thw` — the post-preprocessing tensor
  shape; `[5040, 3, 14, 14]` means 5040 patches for a `[1, 84, 60]` grid
- `image_token_count` — how many embedding rows to overwrite; a one-token slip
  writes embeddings into the wrong rows and the model answers nonsense

Alignment is checked by comparing the board's prefill input against
`input_ids` and `image_token_count`, not by comparing final text — text can
coincidentally match while the layout is wrong.

## Reference environment

The shipped `modeling_paddleocr_vl.py` targets transformers 4.51–4.56 and does
not load on transformers 5.x. `tools/ocr/make_golden.py` bridges the two
differences in memory (`create_causal_mask`'s `inputs_embeds` rename and the
removed `default` rope initialiser) rather than pinning the environment, because
the rest of the toolchain needs a newer transformers. The bridges are
documented at their definition sites.
