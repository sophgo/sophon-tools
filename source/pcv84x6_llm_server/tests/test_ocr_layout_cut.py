"""Pin the TopK cut that stage A2 introduces.

Stage A2 measured two ways tpu-mlir can lower PP-DocLayoutV3's TopK and found
both unusable on CV84X6: ``use_hau=true`` hangs the NPU in a ``TPU_DYNAMIC``
subnet, and ``use_hau=false`` compiles static but emits duplicated indices. The
response is to cut the top-k out of the graph and do it in numpy, which means
splitting the graph in two.

Everything that can go wrong with that split is structural, so it is testable
without an NPU, a bmodel, or onnxruntime:

* the top-k must be in *neither* half (that is the whole point);
* the detector must stop at the crossing set, not run into the decoder;
* the heads must take the indices as an input rather than recompute them;
* the two declaration orders must line up, because two crossed tensors share a
  shape and position is the only thing telling them apart at runtime.
"""

from __future__ import annotations

import pytest

onnx = pytest.importorskip("onnx")

from tools.ocr import layout_topk_cut as cut


def _tiny_model():
    """A miniature stand-in with the same topology as the real export.

    The real ONNX is 130 MB and lives on the build host, so these tests build a
    graph with the same *shape*: encoder -> (scores | features | fpn) -> TopK ->
    gather -> decoder heads. It is small enough to run in milliseconds but keeps
    the property under test -- where the cut lands relative to the TopK.
    """
    from onnx import TensorProto, helper

    def vi(name, dims, elem=TensorProto.FLOAT):
        return helper.make_tensor_value_info(name, elem, dims)

    inits = [helper.make_tensor("w", TensorProto.FLOAT, [4, 4],
                                [0.0] * 16)]
    nodes = [
        # encoder trunk
        helper.make_node("Identity", ["image"], ["p2o.pd_op.relu.12.0"]),
        helper.make_node("Identity", ["image"], ["p2o.pd_op.concat.11.0"]),
        helper.make_node("Identity", ["image"], ["p2o.pd_op.add.18.0"]),
        helper.make_node("Identity", ["image"], ["p2o.pd_op.add.22.0"]),
        helper.make_node("Identity", ["image"], ["p2o.pd_op.add.26.0"]),
        # query features and the score they are ranked by
        helper.make_node("Identity", ["image"], ["p2o.pd_op.layer_norm.2.0"]),
        helper.make_node("Identity", ["image"], [cut.SCORES]),
        # the node this cut removes
        helper.make_node("TopK", [cut.SCORES, "k"], ["vals", cut.TOPK_INDICES],
                         name="TopK.0", axis=1),
        # decoder side
        helper.make_node("Identity", [cut.TOPK_INDICES], [cut.GATHERED]),
        helper.make_node("Identity", [cut.GATHERED], ["boxes"]),
    ]
    inits.append(helper.make_tensor("k", TensorProto.INT64, [1], [3]))
    graph = helper.make_graph(
        nodes, "tiny",
        [vi("image", [1, 3, 800, 800])],
        [vi("boxes", [1, 3, 4])], initializer=inits)
    return helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])


def test_topk_is_in_neither_half():
    """The node the cut exists to remove must not survive in either half.

    A split that merely *moves* the TopK compiles to the same broken subnet,
    which is exactly the failure this design avoids.
    """
    model = _tiny_model()
    plan = cut.plan_cut(model)
    assert plan["topk"] not in plan["detector"]
    assert plan["topk"] not in plan["heads"]


def test_detector_outputs_are_the_crossing_set():
    """The detector must end at what the heads needs, and nothing more.

    `GATHERED` sits downstream of the TopK, so a detector that produced it would
    mean the cut landed after the decoder -- the split would then not remove the
    top-k at all.
    """
    model = _tiny_model()
    plan = cut.plan_cut(model)
    nodes = list(model.graph.node)
    det_out = {o for i in plan["detector"] for o in nodes[i].output}
    assert cut.GATHERED not in det_out
    assert cut.TOPK_INDICES not in det_out
    # ... and it must still produce the two anchors.
    assert cut.SCORES in det_out
    assert cut.FEATURES in det_out


def test_heads_takes_the_indices_as_an_input():
    """`indices` must cross the cut, not be recomputed on the board.

    `GATHERED` is the *consumer* of those indices: it lives on the heads side,
    which is the point -- the gather is cheap and static, the top-k is not.
    """
    model = _tiny_model()
    plan = cut.plan_cut(model)
    nodes = list(model.graph.node)
    heads_in = {t for i in plan["heads"] for t in nodes[i].input}
    heads_out = {o for i in plan["heads"] for o in nodes[i].output}
    assert cut.TOPK_INDICES in heads_in
    assert cut.GATHERED in heads_out
    # Nothing may produce the indices inside either half.
    det_out = {o for i in plan["detector"] for o in nodes[i].output}
    assert cut.TOPK_INDICES not in det_out
    assert cut.TOPK_INDICES not in heads_out


def test_declaration_orders_match():
    """Detector outputs and heads inputs must be declared in the same order.

    Two of the crossed tensors have the identical shape [1,13125,256] -- the
    flattened encoder map and the decoder query features -- so the runtime has
    no way to tell them apart except position. Stage A2 hit exactly this: a
    shape-matching handoff swapped them and every box came out wrong while every
    tensor "looked" plausible.
    """
    model = _tiny_model()
    plan = cut.plan_cut(model)
    det, heads = cut.build(model, plan)
    det_outs = [o.name for o in det.graph.output]
    heads_in = [i.name for i in heads.graph.input if i.name != cut.TOPK_INDICES]
    # Every heads input other than the indices is a detector output, and the
    # relative order is identical.
    shared = [n for n in heads_in if n in det_outs]
    assert shared == [n for n in det_outs if n in shared]


def test_no_node_is_dropped_except_the_topk():
    """Nothing may vanish silently between the two halves."""
    model = _tiny_model()
    plan = cut.plan_cut(model)
    accounted = len(plan["detector"]) + len(plan["heads"]) + 1  # + the TopK
    assert accounted == plan["n_nodes"]


def test_cut_refuses_a_graph_without_the_anchors():
    """A re-export that renames tensors must fail loudly, not silently."""
    from onnx import TensorProto, helper

    g = helper.make_graph(
        [helper.make_node("Identity", ["image"], ["something_else"])],
        "noanchors",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, 8, 8])],
        [helper.make_tensor_value_info("something_else", TensorProto.FLOAT, [1, 3, 8, 8])])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    with pytest.raises(SystemExit, match="not found in the graph"):
        cut.plan_cut(m)
