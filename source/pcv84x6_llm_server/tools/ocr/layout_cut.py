#!/usr/bin/env python3
"""Cut the detector tail (NMS + TopK + gather) out of a PicoDet-family ONNX.

PP-DocLayout-S / PP-DocLayout-M ship as ONNX with PaddleX's whole detection
post-processing folded in: a ``MulticlassNMS`` and the gather/topk pyramid that
turns it into ``[N, 6]`` rows. Those ops are data-dependent, so tpu-mlir lowers
them to a ``TPU_DYNAMIC`` subnet -- and a dynamic subnet hangs this chip's NPU
(``docs/ocr-stage-a.md`` §2). They also have to come out for a second reason:
the row count is data-dependent, so a static bmodel cannot declare the output
shape they produce.

The rewrite stops at the two dense tensors the NMS consumes:

    boxes   [1, anchors, 4]            decoded xyxy, *network-input* pixels
    scores  [1, num_classes, anchors]  class scores

Everything downstream (NMS, top-k, gather, PaddleX's layout post-processing) is
numpy in ``layout_postprocess.py``.

**The cut goes before the resolve, not after.** The original graph divides the
decoded boxes by ``scale_factor`` (a declared input) to map them to page
pixels. Cutting *after* that division keeps ``scale_factor`` as a second input
-- a shape-[1,2] input that every caller has to get right, and one more thing
for the compiler to leave symbolic. Cutting at the numerator instead drops
``scale_factor`` from the graph entirely, leaving a single-input static CNN;
the caller multiplies by ``scale_factor`` in numpy, where it is already known.
``--verify`` prints which route was taken.

    python3 tools/ocr/layout_cut.py --onnx in.onnx --out out.onnx \\
        --verify <img dir> [--net-size N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

NMS_OP = "NonMaxSuppression"


def _producer(graph):
    return {out: n for n in graph.node for out in n.output}


def find_cut_tensors(graph) -> tuple[str, str, bool]:
    """Return (boxes, scores, boxes_need_rescale).

    ``boxes`` is the decoded-box tensor *before* the page-pixel rescale when
    that rescale exists, in which case the caller must divide by
    ``scale_factor``; ``scores`` is the class-score tensor. Both are the two
    data inputs of the graph's ``NonMaxSuppression``.
    """
    nms = [n for n in graph.node if n.op_type == NMS_OP]
    if len(nms) != 1:
        raise SystemExit(f"expected exactly one {NMS_OP}, found {len(nms)}")
    boxes_t, scores_t = nms[0].input[0], nms[0].input[1]

    # boxes <- Identity <- Div(numerator, denominator-derived-from-scale_factor)
    producer = _producer(graph)
    node = producer.get(boxes_t)
    while node is not None and node.op_type == "Identity":
        boxes_t = node.input[0]
        node = producer.get(boxes_t)
    if node is not None and node.op_type == "Div":
        numerator, denominator = node.input[0], node.input[1]
        # Only peel the division when its divisor really comes from the
        # declared scale_factor input; a Div for another reason (a constant
        # normalisation, say) must stay inside the graph.
        if _derives_from(graph, denominator, "scale_factor"):
            print(f"  cut before the page rescale: {boxes_t} "
                  f"(caller divides by scale_factor)")
            return numerator, scores_t, True
    return boxes_t, scores_t, False


def _derives_from(graph, tensor: str, graph_input: str, depth: int = 12) -> bool:
    """Is ``tensor`` computed from ``graph_input`` within ``depth`` hops?"""
    producer = _producer(graph)
    frontier, seen = [tensor], set()
    for _ in range(depth):
        nxt = []
        for t in frontier:
            if t == graph_input:
                return True
            if t in seen:
                continue
            seen.add(t)
            n = producer.get(t)
            if n is not None:
                nxt.extend(n.input)
        frontier = nxt
        if not frontier:
            break
    return False


def cut(onnx_path: Path, out_path: Path) -> tuple[str, str, bool]:
    model = onnx.load(str(onnx_path))
    graph = model.graph
    boxes_t, scores_t, need_rescale = find_cut_tensors(graph)

    extra = [
        helper.make_tensor_value_info(t, TensorProto.FLOAT,
                                      ["batch", "dim_0", "dim_1"])
        for t in (boxes_t, scores_t)
    ]

    needed = {boxes_t, scores_t}
    live: list = []
    for node in reversed(list(graph.node)):
        if any(o in needed for o in node.output):
            live.append(node)
            needed.update(node.input)
    live.reverse()
    dropped = len(graph.node) - len(live)
    if dropped == 0:
        raise SystemExit("nothing was dropped -- is the NMS in this graph?")

    # Prune graph inputs that the remaining nodes no longer read. On this
    # export that is exactly ``scale_factor``; leaving it declared would force
    # every caller (and tpu-mlir's input_shape_assign) to carry a dead input.
    used = {i for n in live for i in n.input}
    inputs = [i for i in graph.input if i.name in used]
    dropped_inputs = [i.name for i in graph.input if i.name not in used]

    new_graph = helper.make_graph(
        live, f"{graph.name}_cut", inputs, extra,
        initializer=list(graph.initializer),
    )
    new_model = helper.make_model(new_graph, opset_imports=list(model.opset_import))
    new_model.ir_version = model.ir_version
    new_model.producer_name = "layout_cut"
    onnx.checker.check_model(new_model)
    onnx.save(new_model, str(out_path))
    print(f"cut {onnx_path.name}: {len(graph.node)} -> {len(live)} nodes "
          f"(dropped {dropped}); inputs {[i.name for i in graph.input]} -> "
          f"{[i.name for i in inputs]} (dropped {dropped_inputs}); "
          f"outputs -> [{boxes_t}, {scores_t}]")
    return boxes_t, scores_t, need_rescale


def verify(onnx_path: Path, cut_path: Path, img_dir: Path, net_hw: int,
           need_rescale: bool) -> int:
    """Two independent checks of the numpy tail.

    1. ``_multiclass_nms`` must reproduce the ONNX's own ``fetch_name_0`` rows
       (the NMS that was cut out), compared as a sorted set. This pins the
       arithmetic that was removed.
    2. ``det_postprocess`` on the cut outputs must reproduce PaddleX's own
       ``LayoutAnalysisProcess`` run on the uncut ONNX's rows. This pins the
       *transcription* of the Python tail, and it is what makes the on-board
       comparison meaningful: both sides then apply the same tail.
    """
    import cv2
    import onnxruntime as ort

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import layout_postprocess as post

    full = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    part = ort.InferenceSession(str(cut_path), providers=["CPUExecutionProvider"])

    labels = post.load_labels()
    images = sorted(p for p in img_dir.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))
    if not images:
        raise SystemExit(f"no images in {img_dir}")

    total = ok_nms = ok_tail = 0
    for p in images:
        img = cv2.imread(str(p))
        h, w = img.shape[:2]
        x = cv2.resize(img, (net_hw, net_hw), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / \
            np.array([0.229, 0.224, 0.225], np.float32)
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        sf = np.array([[net_hw / h, net_hw / w]], np.float32)

        ref_rows = full.run(None, {"image": x, "scale_factor": sf})[0]
        feed = {"image": x}
        if not need_rescale:
            feed["scale_factor"] = sf
        raw_boxes, raw_scores = part.run(None, feed)
        boxes = raw_boxes.reshape(-1, 4)
        if need_rescale:
            sf_h, sf_w = float(sf[0][0]), float(sf[0][1])
            boxes = boxes / np.array([sf_w, sf_h, sf_w, sf_h], np.float32)

        mine = post._multiclass_nms(boxes, raw_scores[0])
        same_nms = _same_rows(ref_rows, mine)
        ok_nms += bool(same_nms)

        got = post.det_postprocess(boxes[None], raw_scores, (h, w),
                                   num_classes=len(labels))
        want = _paddlex_tail(ref_rows, (h, w), labels)
        same_tail = _same_boxes(want, got)
        ok_tail += bool(same_tail)
        total += 1
        print(f"  {p.name:20s} rows ref={len(ref_rows):3d} nms={len(mine):3d} "
              f"{'OK' if same_nms else 'DIFF':4s} | "
              f"boxes paddlex={len(want):3d} ours={len(got):3d} "
              f"{'OK' if same_tail else 'DIFF'}")

    print(f"verify NMS tail:     {ok_nms}/{total}")
    print(f"verify PaddleX tail: {ok_tail}/{total}")
    return 0 if ok_nms == total and ok_tail == total else 1


def _same_rows(ref: np.ndarray, mine: np.ndarray, atol=2e-2) -> bool:
    """Same rows as a set, ignoring order.

    Ordered by ``(cls, -score)`` because that pair is unique in practice: the
    ONNX's ``keep_top_k`` and ours can tie-break differently on equal scores
    (10 of the 100 rows on ``skewed_lines``), and the row *set* is what the
    downstream NMS sees. Sorting on coordinates instead would mis-pair two
    boxes that merely start at nearly the same x.
    """
    if ref.shape != mine.shape:
        return False
    if len(ref) == 0:
        return True
    a = ref[np.lexsort((-ref[:, 1], ref[:, 0]))]
    b = mine[np.lexsort((-mine[:, 1], mine[:, 0]))]
    return bool(np.allclose(a, b, atol=atol, rtol=1e-4))


def _paddlex_tail(rows: np.ndarray, img_size, labels, threshold=0.5):
    from paddlex.inference.models.layout_analysis.processors import (
        LayoutAnalysisProcess,
    )
    proc = LayoutAnalysisProcess(labels=labels, scale_size=[img_size[0], img_size[1]])
    return proc.apply(rows.astype(np.float32), img_size, threshold,
                      True, None, None, None, "rect", None)


def _same_boxes(want, got) -> bool:
    if len(want) != len(got):
        return False
    for a, b in zip(want, got):
        if a["label"] != b["label"] or a["coordinate"] != b["coordinate"]:
            return False
        if abs(a["score"] - b["score"]) > 1e-4:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--verify", type=Path, default=None,
                    help="image dir; check the numpy tail against the uncut ONNX")
    ap.add_argument("--net-size", type=int, default=None,
                    help="network input side (default: from the graph input)")
    args = ap.parse_args()

    _, _, need_rescale = cut(args.onnx, args.out)
    if args.verify:
        size = args.net_size
        if size is None:
            m = onnx.load(str(args.onnx))
            dims = m.graph.input[0].type.tensor_type.shape.dim
            size = dims[2].dim_value
        return verify(args.onnx, args.out, args.verify, size, need_rescale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
