#!/usr/bin/env python3
"""Cut PP-DocLayoutV3's TopK out of the compiled graph, in two halves.

Stage A2 measured both ways tpu-mlir can lower this graph's ``TopK``, and both
are unusable on CV84X6:

* ``use_hau=true`` (the ONNX default) puts it in a ``TPU_DYNAMIC`` subnet, and
  launching that subnet hangs the NPU in ``bmdrv_thread_sync_api wait api
  timeout`` (stage A, reproduced);
* ``use_hau=false`` compiles into a *single* ``TPU_STATIC`` subnet and runs, but
  its index output is wrong: it emits duplicated query indices -- 68 duplicated
  pairs out of 300, on every one of the 7 reference images -- so the decoder
  gathers the wrong queries and boxes are lost (52/60 reference boxes survive at
  IoU >= 0.9, vs the 57/60 target).

So the top-k has to happen outside the bmodel, in numpy, as the design already
says. That splits the graph in two, because the selected indices feed the
second-stage decoder attention:

* **detector** — ``image`` -> 7 tensors: the ``13125`` reduce-max scores, the
  ``13125x256`` decoder features, and the five encoder feature maps the decoder
  attends over (one ``1x32x40000`` flattened level plus four ``8x32xHxW``
  pyramid levels).
* **heads** — those 7 plus ``indices[1,300]`` -> ``boxes``/``logits``/``order``.
  The indices come from numpy's ``argpartition``; on the board this half is only
  gathers and decoder layers.

Both halves carry the original initializer list, so the split adds no weights.

**Why a rewrite rather than "export at a different node".** The shipped ONNX
folds PaddleX's whole post-processing into the graph: the top-k, the
``GatherND`` of the selected queries, a 300x300 vote matrix and a 300x200x200
mask branch. Several of those are ``Where``/``Range`` over data-dependent
shapes, which is what made the module dynamic in the first place. The cut has to
pick the tensors that cross the top-k *and* delete everything downstream of it,
which is what :func:`plan_cut` computes.

    python3 tools/ocr/layout_topk_cut.py --onnx PP-DocLayoutV3_fixed.onnx \\
        --out-dir build/layout --prefix dl3cut

Needs onnx (any host); no NPU, no tpu-mlir.
"""

from __future__ import annotations

import argparse
from pathlib import Path

#: The ONNX export's own tensor names (``p2o.pd_op.*`` comes from PaddleX's
#: ``paddle2onnx`` pass). Stable for a given export; a re-export moves them,
#: which is why :func:`plan_cut` asserts rather than best-effort matches.
SCORES = "p2o.pd_op.max.0.0"            # (1, 13125) reduce-max over classes
FEATURES = "p2o.pd_op.layer_norm.2.0"   # (1, 13125, 256) decoder query features
TOPK_INDICES = "TopK.2"                 # (1, 300) selected query indices
GATHERED = "p2o.pd_op.gather_nd.0.0"     # (1, 300, 256) features at those indices

#: Shapes of the five encoder feature maps the decoder cross-attends to. Fixed
#: by the 800x800 input, so they are literals; :func:`plan_cut` cross-checks them
#: against what the graph actually records rather than trusting them blindly.
FPN_SHAPES = {
    # (1, 13125, 256) in ONNX; the compiler flattens it to 1x32x40000 for the
    # attention. The ONNX-level shape is what the graph declares, so that is
    # what the cut declares too.
    "p2o.pd_op.concat.11.0": [1, 13125, 256],
    "p2o.pd_op.relu.12.0": [1, 128, 200, 200],
    "p2o.pd_op.add.18.0": [1, 256, 100, 100],
    "p2o.pd_op.add.22.0": [1, 256, 50, 50],
    "p2o.pd_op.add.26.0": [1, 256, 25, 25],
}


def _reachable(index: dict[str, int], nodes, outputs) -> set[int]:
    """Indices of nodes ``outputs`` transitively depend on."""
    keep: set[int] = set()
    stack = list(outputs)
    while stack:
        name = stack.pop()
        i = index.get(name)
        if i is None or i in keep:
            continue
        keep.add(i)
        stack.extend(nodes[i].input)
    return keep


def plan_cut(model) -> dict:
    """Partition the graph and report what crosses the cut.

    Pure function of the graph so the tests can call it directly and pin the
    four properties that matter: the top-k is in neither half, the detector ends
    at the crossing set, the heads take the indices as an input, and the two
    halves together account for every node except the one being dropped.
    """
    g = model.graph
    nodes = list(g.node)
    index = {o: i for i, n in enumerate(nodes) for o in n.output}

    for required in (SCORES, FEATURES):
        if required not in index:
            raise SystemExit(
                f"tensor {required!r} not found in the graph. The ONNX export "
                "changed; re-derive SCORES/FEATURES from the new node names "
                "before trusting this cut.")

    topk = [i for i, n in enumerate(nodes) if n.op_type == "TopK"]
    if len(topk) != 1:
        raise SystemExit(f"expected exactly one TopK, found {len(topk)}")
    topk_idx = topk[0]

    out_names = [o.name for o in g.output]
    # Everything the heads need, before subtracting the detector: this is what
    # makes the encoder feature maps show up on the *detector* side instead of
    # being recomputed. They are found as "produced upstream of the heads but
    # not by the heads", which is exactly the crossing set once the detector is
    # known -- so anchor the detector on scores+features first and let the
    # second pass pull in whatever the heads still reference.
    heads_closure = _reachable(index, nodes, out_names + [GATHERED])

    # The decoder cross-attends to five encoder feature maps. They are on the
    # *detector* side of the cut -- recomputing them in the heads half would
    # duplicate the whole conv trunk -- so the detector is anchored on them too.
    # Every one must exist: a missing entry means the decoder's inputs changed.
    absent = [t for t in FPN_SHAPES if t not in index]
    if absent:
        raise SystemExit(
            f"encoder feature map {absent} not found; the decoder's inputs "
            "changed and this cut's anchors are stale")
    det_keep = _reachable(index, nodes, [SCORES, FEATURES] + sorted(FPN_SHAPES))

    heads_keep = heads_closure - det_keep
    # The top-k is what this cut exists to remove: its *indices* output becomes
    # a declared input of the heads half, so python does the selection.
    if topk_idx in heads_keep:
        heads_keep.discard(topk_idx)
    if topk_idx in det_keep:
        # The scores path is `... -> MatMul.9 -> ReduceMax -> TopK`; the anchors
        # stop before the reduce-max chain, so this would mean the anchors moved.
        raise SystemExit("the TopK node is on the detector side; the anchor "
                         "tensors no longer bracket it")

    det_keep.discard(topk_idx)
    if not heads_keep:
        raise SystemExit("the heads half is empty")

    det_out = {o for i in det_keep for o in nodes[i].output}
    heads_in = {t for i in heads_keep for t in nodes[i].input}
    crossing = sorted(det_out & heads_in)
    missing = sorted(t for t in heads_in - det_out
                     if t not in {o for i in heads_keep for o in nodes[i].output}
                     and t not in FPN_SHAPES)
    if missing:
        # These are the initializer names (weights) and the ONNX graph's own
        # declared inputs; both are re-supplied wholesale when the halves are
        # materialised, so they are reported rather than treated as errors.
        pass

    return {"detector": det_keep, "heads": heads_keep, "topk": topk_idx,
            "crossing": crossing, "inits": {i.name for i in g.initializer},
            "graph_inputs": [i.name for i in g.input],
            "n_nodes": len(nodes),
            "heads_shape_inputs": sorted(
                t for t in heads_in - det_out
                if t not in {o for i in heads_keep for o in nodes[i].output})}


def build(model, plan):
    """Materialise the two halves from a :func:`plan_cut` result."""
    from onnx import TensorProto, helper

    g = model.graph
    nodes = list(g.node)

    def half(keep: set[int], name: str, declared_in: dict[str, list],
             out_names: list[str], out_dims: dict[str, list] | None = None):
        out_dims = out_dims or {}
        body = [nodes[i] for i in sorted(keep)]
        produced = {o for n in body for o in n.output}
        consumed = {t for n in body for t in n.input}
        inputs = []
        for tensor in sorted(consumed - produced - inits):
            if tensor not in declared_in:
                raise SystemExit(
                    f"{name}: {tensor!r} is consumed but neither produced inside "
                    "this half nor declared. It is an initializer or an ONNX "
                    "graph input that the caller must forward.")
            dims, elem = declared_in[tensor]
            inputs.append(helper.make_tensor_value_info(tensor, elem, dims))
        outputs = [helper.make_tensor_value_info(n, TensorProto.FLOAT,
                                                 out_dims.get(n))
                   for n in out_names]
        graph = helper.make_graph(body, name, inputs, outputs,
                                  initializer=list(g.initializer))
        return helper.make_model(graph, opset_imports=list(model.opset_import),
                                 producer_name="layout_topk_cut")

    # Weights arrive through the shared initializer list, so any name that is an
    # initializer is simply not a graph input; `half` only declares tensors that
    # are genuinely activations.
    # (dims, elem_type). `TopK.2` is int64 -- it is an index tensor, and
    # declaring it float makes every downstream Concat fail to unify its type.
    declared = {
        "image": ([1, 3, 800, 800], TensorProto.FLOAT),
        TOPK_INDICES: ([1, 300], TensorProto.INT64),
        FEATURES: ([1, 13125, 256], TensorProto.FLOAT),
        SCORES: ([1, 13125], TensorProto.FLOAT),
        **{k: (v, TensorProto.FLOAT) for k, v in FPN_SHAPES.items()},
    }
    inits = {i.name for i in g.initializer}
    # Output order matters: the runtime hands these positionally to the heads
    # half, and two of them share the shape [1,13125,256] (the flattened
    # encoder feature map and the decoder query features) so a shape-based
    # match cannot tell them apart. Declaring the detector's outputs in the
    # same sorted order the heads declares its inputs makes position the key.
    det_outs = sorted([SCORES, FEATURES] + list(FPN_SHAPES))
    detector = half(plan["detector"], "detector", declared, det_outs,
                    {SCORES: [1, 13125], FEATURES: [1, 13125, 256],
                     **FPN_SHAPES})
    heads = half(plan["heads"], "heads", declared,
                 [o.name for o in g.output])
    return detector, heads


def main() -> int:
    import onnx

    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--prefix", default="dl3cut")
    args = ap.parse_args()

    model = onnx.load(str(args.onnx))
    try:
        plan = plan_cut(model)
    except SystemExit:
        # The cut only applies to the head-trimmed graph. On the raw export the
        # post-processing is still folded in, so say which file this wants
        # rather than letting the node counts look like a mystery.
        raise
    print(f"nodes {plan['n_nodes']}: detector {len(plan['detector'])}, "
          f"heads {len(plan['heads'])}, dropped 1 (the TopK)")
    print(f"crossing ({len(plan['crossing'])}): {plan['crossing']}")

    detector, heads = build(model, plan)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, m in ((f"{args.prefix}_detector.onnx", detector),
                    (f"{args.prefix}_heads.onnx", heads)):
        path = args.out_dir / name
        onnx.save(m, str(path))
        print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
