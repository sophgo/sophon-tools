#!/usr/bin/env python3
"""SLANet_plus / SLANeXt post-processing, transcribed from PaddleX.

The bmodel stops at ``[1, steps, 8]`` bboxes and ``[1, steps, 50]`` structure
probabilities (``slanet_unroll.py``); turning those into HTML is this file.

Transcribed from ``paddlex/inference/models/table_structure_recognition/
processors.py`` (``TableLabelDecode``) and the ``PreProcess`` block of the
model's own ``inference.yml``. The details that are easy to get wrong and are
therefore spelled out:

* **Pad with 0 *after* normalising.** Three routes are plausible and they
  decode differently, so this one is pinned by capturing what the model is
  actually fed rather than by reading the config:

  | route | padded corner | rows on `cn_table_merged`'s crop |
  |---|---|---|
  | 127.5 after normalising (what the config reads as) | 127.5 | 1 |
  | 0 *pixels*, canvas then normalised | -2.12 | 6 |
  | **0 in normalised space** (what the runner sends) | **0.0** | **5** |

  ``PaddingTableImage(val=127.5)`` does run after ``NormalizeImage``, but the
  runner PaddleX uses here does not feed its output to the model; capturing at
  ``PaddleStaticRunner.__call__`` gives a padded corner of exactly 0.0 with the
  content at min/max -2.05/2.64. The third row is that tensor, and it is the
  only one that reproduces PaddleX's 5 rows.
* The character dictionary gets ``sos`` prepended and ``eos`` appended, so the
  model's 50 classes are 48 dict entries + 2 sentinels. It is read from the
  model's ``inference.yml`` rather than hard-coded.
* ``merge_no_span_structure`` (default true in the config) *replaces*
  ``<td>`` with ``<td></td>`` in the dictionary: a cell with no span opens and
  closes at once. Getting this wrong yields HTML that parses but is a level
  deeper than PaddleX's.
* Decoding stops at the first ``eos`` after index 0. Index 0 is ``sos`` and is
  skipped rather than treated as a stop.
"""
from __future__ import annotations

import numpy as np

TARGET = 488          # ResizeTableImage max_len / PaddingTableImage size
PAD_VALUE = 0.0       # fill in *normalised* space (see the module docstring)


def load_chars(yml_path):
    """Dictionary + sentinels, exactly as PaddleX builds it."""
    import yaml

    cfg = yaml.safe_load(open(yml_path))
    chars = list(cfg["PostProcess"]["character_dict"])
    merge_no_span = True
    for op in cfg["PreProcess"]["transform_ops"]:
        if "TableLabelEncode" in op:
            merge_no_span = op["TableLabelEncode"].get("merge_no_span_structure", True)
    if merge_no_span:
        if "<td></td>" not in chars:
            chars.append("<td></td>")
        if "<td>" in chars:
            chars.remove("<td>")
    return ["sos"] + chars + ["eos"]


def preprocess(bgr: np.ndarray, target: int = TARGET):
    """Resize -> normalise -> pad, the order the model's config declares.

    Returns the ``[1,3,target,target]`` tensor plus the sizes the decoder needs
    to map cell boxes back: ``(ori_w, ori_h)`` and ``(padded_w, padded_h)``.
    """
    import cv2

    h, w = bgr.shape[:2]
    scale = target / max(h, w)
    hh, ww = round(h * scale), round(w * scale)
    resized = cv2.resize(bgr, (ww, hh))

    # Normalise the content, then pad with 0 in that same space -- what
    # PaddleStaticRunner actually receives (see the module docstring).
    content = resized.astype(np.float32) / 255.0
    content = (content - np.array([0.485, 0.456, 0.406], np.float32)) / \
        np.array([0.229, 0.224, 0.225], np.float32)
    canvas = np.full((target, target, 3), PAD_VALUE, np.float32)
    canvas[:hh, :ww] = content
    x = canvas
    tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None])
    return tensor, (ww, hh), (w, h)


def cell_scales(padded, ori):
    """PaddleX ``_get_bbox_scales`` for non-SLANet models (i.e. SLANet_plus).

    Cell boxes come out in padded-image pixels; this is the factor that maps
    them back to the original table crop.
    """
    w, h = padded
    ori_w, ori_h = ori
    ratio = min(w / ori_w, h / ori_h)
    return w / ratio, h / ratio


def decode(structure_probs, bbox_preds, chars, padded, ori):
    """Structure probabilities -> ``(html, cells)``.

    ``structure_probs`` is ``[steps, 50]`` for one image (the softmax the
    bmodel emits), ``bbox_preds`` ``[steps, 8]`` or ``None`` when the model has
    no location head.

    ``cells`` is a list of 8-point polygons in original-crop pixels, one per
    ``<td>``-family token, in emission order -- which is the order PaddleX's
    downstream cell matcher expects.
    """
    probs = np.asarray(structure_probs)
    if probs.ndim == 3:
        probs = probs[0]
    idx = probs.argmax(axis=1)
    conf = probs.max(axis=1)

    sos = chars.index("sos")
    eos = chars.index("eos")
    td_tokens = {"<td>", "<td", "<td></td>"}

    tokens, scores, cells = [], [], []
    h_scale = w_scale = None
    if bbox_preds is not None:
        w_scale, h_scale = cell_scales(padded, ori)

    for i, ci in enumerate(idx):
        ci = int(ci)
        if i > 0 and ci == eos:
            break
        if ci == sos:
            continue
        text = chars[ci]
        if text in td_tokens and bbox_preds is not None:
            box = np.asarray(bbox_preds[i] if np.ndim(bbox_preds) == 2
                             else bbox_preds[0][i], np.float64)
            scales = np.array([h_scale, w_scale] * 4, np.float64)
            cells.append((box * scales).astype(int).tolist())
        tokens.append(text)
        scores.append(float(conf[i]))

    html = "<html><body><table>" + "".join(tokens) + "</table></body></html>"
    return html, cells, (float(np.mean(scores)) if scores else 0.0)


def structure_only(structure_probs, chars):
    """Decode without a location head (the KL/UNet-free path)."""
    html, _cells, score = decode(structure_probs, None, chars, (TARGET, TARGET),
                                 (TARGET, TARGET))
    return html, score
