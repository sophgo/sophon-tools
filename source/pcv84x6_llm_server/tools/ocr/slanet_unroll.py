#!/usr/bin/env python3
"""Make SLANet_plus compilable: inline the Loop body's captured weights, then
replace the autoregressive Loop with straight-line graph.

Two problems, both in the *export*, not in the model.

**1. The Loop body captures outer-scope weights.** paddle2onnx emits the
autoregressive decoder as an ONNX ``Loop`` whose body reads ``gru_cell_0.w_0``
and the six ``linear_*.w_0`` straight from the enclosing graph instead of
declaring them. ONNX permits that; tpu-mlir's converter does not -- it resolves
operands only in the body's own scope and dies with
``KeyError: operand conv2d_24.b_0 not found``. ``inline_captures`` copies those
initializers into the body.

**2. tpu-mlir cannot convert a Loop at all**, and neither onnxruntime nor
onnx.shape_inference can run this export as-is (the body's ``If``/``SetValue``
path declares the carried condition rank-0 while the body yields rank-1). So the
reference and the board both need the same fixed graph, which is why this
rewrite is applied once and both sides consume its output.

Unrolling needs a fixed step count. SLANet_plus decodes until it emits ``eos``
or reaches ``max_text_length`` (500). Measured on the two tables in
``tests/data/ocr/img``: 44 and 21 steps. ``--steps`` is a parameter rather than
a constant because the unrolled graph is O(steps) in size, and picking a number
is exactly the trade-off the report has to state.

    python3 tools/ocr/slanet_unroll.py --onnx in.onnx --out out.onnx --steps 64
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import onnx
from onnx import helper, numpy_helper, numpy_helper


def _bodies(graph):
    for node in graph.node:
        if node.op_type == "Loop":
            yield node, [a for a in node.attribute if a.name == "body"][0].g


def hoist_constants(graph) -> int:
    """Turn outer-scope ``Constant`` nodes into graph initializers.

    paddle2onnx emits the decoder's weights (``gru_cell_0.w_0``, the six
    ``linear_*.w_0/b_0``) as ``Constant`` nodes rather than initializers, so
    inlining them into the Loop body means materialising their arrays first.
    Only the ones the body actually captures are hoisted: every other Constant
    stays where it is, which keeps the diff to this rewrite small.
    """
    captured = set()
    for _, body in _bodies(graph):
        declared = {i.name for i in body.input} | {i.name for i in body.initializer}
        produced = set()
        for n in body.node:
            produced.update(n.output)
        for n in body.node:
            for name in n.input:
                if name and name not in declared and name not in produced:
                    captured.add(name)

    hoisted = 0
    keep = []
    for node in graph.node:
        if (node.op_type == "Constant" and node.output
                and node.output[0] in captured):
            graph.initializer.append(
                numpy_helper.from_array(
                    numpy_helper.to_array(
                        [a for a in node.attribute if a.name == "value"][0].t),
                    name=node.output[0]))
            hoisted += 1
        else:
            keep.append(node)
    graph.ClearField("node")
    graph.node.extend(keep)
    return hoisted


def inline_captures(graph) -> int:
    """Copy outer-scope initializers into each Loop body that reads them.

    Also promotes rank-0 declarations inside the body to rank-1: the export
    declares the carried condition as a scalar while the body yields a length-1
    tensor, and both onnxruntime and onnx.checker reject the mismatch. The value
    is unaffected -- it is read as a boolean either way.
    """
    moved = 0
    inits = {i.name: i for i in graph.initializer}
    for _, body in _bodies(graph):
        declared = {i.name for i in body.input} | {i.name for i in body.initializer}
        produced = set()
        for n in body.node:
            produced.update(n.output)
        for node in body.node:
            for name in node.input:
                if not name or name in declared or name in produced:
                    continue
                if name in inits:
                    body.initializer.append(inits[name])
                    declared.add(name)
                    moved += 1
        for vi in list(body.input) + list(body.output):
            if len(vi.type.tensor_type.shape.dim) == 0:
                vi.type.tensor_type.shape.dim.add().dim_value = 1
    return moved


def replace_onehot_with_gather(graph) -> int:
    """Rewrite ``OneHot(idx, depth=D, values=[0,1])`` as ``Gather(eye(D), idx)``.

    This is the fix that actually removes the ``TPU_DYNAMIC`` subnet. The
    decoder picks a word embedding with ``OneHot(argmax(logits))`` then
    concatenates it with the image feature and feeds a MatMul; tpu-mlir lowers
    ``OneHot`` into its own dynamic subnet (measured: a 2-node ArgMax+OneHot
    graph on ``bm1684x2`` comes out as one STATIC and one DYNAMIC subnet), and a
    dynamic subnet wedges this chip's NPU.

    ``OneHot`` with a constant depth and ``[0,1]`` values *is* a row gather from
    an identity matrix, so the rewrite is exactly equivalent, not an
    approximation -- verified token-for-token against Paddle's predictor. The
    identity matrix is a D x D initializer (50x50 here, 10 KB), materialised
    once and shared.

    Only the shape ``(constant depth, constant [0,1] values)`` is rewritten;
    anything else raises rather than silently changing the semantics.
    """
    const = {}
    for node in graph.node:
        if node.op_type == "Constant":
            for a in node.attribute:
                if a.name == "value":
                    const[node.output[0]] = numpy_helper.to_array(a.t)

    rewritten = 0
    keep = []
    for node in graph.node:
        if node.op_type != "OneHot":
            keep.append(node)
            continue
        _idx, depth_t, values_t = node.input
        if depth_t not in const or values_t not in const:
            raise SystemExit(f"OneHot {node.name}: depth/values are not "
                             f"constants; cannot verify the Gather rewrite")
        depth = int(np.asarray(const[depth_t]).reshape(-1)[0])
        values = np.asarray(const[values_t]).reshape(-1)
        if values.tolist() != [0.0, 1.0]:
            raise SystemExit(f"OneHot {node.name}: values are {values.tolist()}, "
                             f"expected [0, 1]")
        axis = [a.i for a in node.attribute if a.name == "axis"]
        if axis and axis[0] not in (-1, 3):
            raise SystemExit(f"OneHot {node.name}: unexpected axis {axis[0]}")

        eye_name = f"__onehot_eye_{depth}"
        if eye_name not in {i.name for i in graph.initializer}:
            graph.initializer.append(numpy_helper.from_array(
                np.eye(depth, dtype=np.float32), name=eye_name))
        keep.append(helper.make_node(
            "Gather", [eye_name, node.input[0]], node.output,
            name=f"{node.name}_Gather", axis=0))
        rewritten += 1
    graph.ClearField("node")
    graph.node.extend(keep)
    return rewritten


def prune_dead(graph) -> int:
    """Drop nodes whose outputs nothing consumes, transitively.

    Removing the body's ``If`` leaves its bookkeeping consumers (``Not``,
    ``And``, the ``argmax`` fed only to the condition) reading values that no
    longer exist. They are pure termination logic and contribute nothing to the
    decoded output, so they go too -- identified structurally as "output has no
    consumer", not by name.
    """
    removed = 0
    while True:
        consumed = {i for n in graph.node for i in n.input if i}
        consumed |= {o.name for o in graph.output}
        keep = [n for n in graph.node if any(o in consumed for o in n.output)]
        if len(keep) == len(graph.node):
            return removed
        removed += len(graph.node) - len(keep)
        graph.ClearField("node")
        graph.node.extend(keep)


def topo_sort(graph) -> None:
    """Re-sort ``graph.node`` so every input is produced before it is read.

    Concatenating the unrolled steps ahead of the surviving outer nodes breaks
    the order: step 0 reads values the outer graph still produces (the carried
    dependencies and, before inlining, the captured weights). A plain Kahn pass
    over the whole node list fixes it without having to reason about which
    outer node feeds which step.

    Initializers and graph inputs are treated as already available; so are
    names produced by nested subgraphs (none remain after unrolling).
    """
    available = {i.name for i in graph.initializer} | {i.name for i in graph.input}
    nodes = list(graph.node)
    pending = []
    for n in nodes:
        missing = [i for i in n.input if i and i not in available]
        pending.append((n, set(missing)))

    # Map value -> indices of nodes waiting on it, to avoid rescanning.
    ordered = []
    progress = True
    while pending and progress:
        progress = False
        rest = []
        for node, missing in pending:
            if missing <= available:
                ordered.append(node)
                available.update(o for o in node.output if o)
                progress = True
            else:
                rest.append((node, missing))
        pending = rest
    if pending:
        stuck = pending[0]
        raise SystemExit(
            f"cannot topologically sort: {len(pending)} nodes unresolved, "
            f"first is {stuck[0].op_type} missing {sorted(stuck[1])[:4]}")
    graph.ClearField("node")
    graph.node.extend(ordered)


def _resolve_body_ops(body):
    """Drop the ops an unrolled graph cannot represent, and say what went.

    ``If`` computes the loop's own termination bookkeeping; the unrolled graph
    ignores it (it runs a fixed number of steps and the decoder's ``eos`` is
    handled by the caller), so the node is dropped together with anything that
    only fed it. ``Yield``-style pseudo-ops are dropped too: the carried values
    are taken from the body outputs directly.
    """
    dropped_types = {"If", "Yield", "YieldOp"}
    keep = [n for n in body.node if n.op_type not in dropped_types]
    return keep, [n.op_type for n in body.node if n.op_type in dropped_types]


def _initializer_value(graph, name):
    """Value of a graph initializer, tolerating a Constant node producer."""
    from onnx import numpy_helper
    for init in graph.initializer:
        if init.name == name:
            return int(numpy_helper.to_array(init))
    for node in graph.node:
        if node.op_type == "Constant" and name in node.output:
            for a in node.attribute:
                if a.name == "value":
                    return int(numpy_helper.to_array(a.t))
    raise SystemExit(f"no value for {name}")


def _cursor_input(body):
    """Name of the body's carried int64 write cursor, or ``None``.

    The decoder carries a scalar int64 ("how many tokens emitted so far"). It
    starts at the outer initializer's value (0) and the body adds a literal
    ``1.0`` to it once per step, so after unrolling it is exactly the step
    index -- a compile-time constant. That matters because it is the index of
    the per-step ``ScatterElements`` and of the slice that reads the previous
    token: leaving it as a tensor is what makes tpu-mlir emit a
    ``TPU_DYNAMIC`` subnet.

    Identified structurally (the only scalar int64 carried input), not by name,
    and the increment is asserted to be the literal 1 so a re-export that
    changes the stride fails loudly.
    """
    from onnx import TensorProto
    cursor = None
    for vi in body.input[2:]:
        t = vi.type.tensor_type
        if t.elem_type == TensorProto.INT64 and len(t.shape.dim) == 0:
            if cursor is not None:
                raise SystemExit("two scalar int64 carried inputs; cannot tell "
                                 "which is the write cursor")
            cursor = vi.name
    if cursor is None:
        return None
    return cursor


def _cursor_output(body, cursor_in: str):
    """The body output that carries the cursor into the next step.

    Found by signature: the only rank-0 int64 carried output. Matching on type
    rather than on a producer chain is deliberate -- the increment goes through
    a Cast into float and back, so the producer chain is not a simple Add.
    """
    from onnx import TensorProto
    cands = []
    for v in body.output[1:]:
        t = v.type.tensor_type
        if t.elem_type == TensorProto.INT64 and len(t.shape.dim) == 0:
            cands.append(v.name)
    if len(cands) != 1:
        raise SystemExit(f"expected one rank-0 int64 carried output (the cursor); "
                         f"found {cands}")
    return cands[0]


def unroll(graph, steps: int) -> int:
    """Replace the Loop with ``steps`` inline copies of its body."""
    loops = [n for n in graph.node if n.op_type == "Loop"]
    if len(loops) != 1:
        raise SystemExit(f"expected exactly one Loop, found {len(loops)}")
    loop = loops[0]
    body = [a for a in loop.attribute if a.name == "body"][0].g

    # body inputs: [iter, cond, carried...]; body outputs: [cond, carried...]
    # Body inputs are [iter, cond, carried...] and body outputs are
    # [cond, carried...], so ``body.output[1:]`` pairs with the 9 carried
    # inputs positionally.
    #
    # The Loop node exposes only **8** of those 9 -- it omits the decoder's
    # ``done`` flag (carried input ``full.26.0``, body output ``if.0.0``), which
    # is state the ``If`` updates but that nothing outside the loop reads. That
    # asymmetry is the export defect that makes the published ONNX unrunnable
    # outside Paddle: ONNX requires ``len(outputs) == len(carried_inputs) + 1``
    # and onnxruntime rejects the file at shape inference.
    #
    # The ``k+1`` offset below is not a guess -- it is pinned by the three Loop
    # outputs that are consumed, whose declared types match only at that offset:
    #   while.0.2 -> Cast,Cast -> Slice index  == scale.3.0     (int64 cursor)
    #   while.0.3 -> Slice (bbox)              == set_value_.1.0 (float bbox)
    #   while.0.6 -> Slice -> Softmax          == set_value_.0.0 (float struct)
    carried_in = [i.name for i in body.input[2:]]
    carried_out = [o.name for o in body.output[1:]]
    if len(carried_in) != len(carried_out):
        raise SystemExit(f"{len(carried_in)} carried inputs vs "
                         f"{len(carried_out)} carried outputs")
    if len(loop.input) - 2 != len(carried_in):
        raise SystemExit("Loop's carried inputs do not match the body's")
    n_exposed = len(loop.output) - 1
    if n_exposed != len(carried_out) - 1:
        raise SystemExit(f"Loop exposes {n_exposed} carried outputs; expected "
                         f"the body's {len(carried_out)} minus the done flag")

    body_nodes, dropped = _resolve_body_ops(body)
    produced_in_body = set()
    for n in body_nodes:
        produced_in_body.update(n.output)

    # The body's initializers (the inlined weights) must exist in the enclosing
    # graph once the body is gone. Names are unique across the two scopes in
    # this export, so hoisting them verbatim is safe and keeps the references
    # the unrolled nodes make resolvable.
    have = {i.name for i in graph.initializer}
    for init in body.initializer:
        if init.name not in have:
            graph.initializer.append(init)
            have.add(init.name)

    new_nodes = []

    # The per-step write cursor becomes a literal. Every unrolled step emits
    # exactly one token, so its value is the step index -- known at build time.
    # Substituting it here is what keeps Range/Slice/ScatterElements out of the
    # bmodel's index path (see ``_cursor_input``).
    cursor = _cursor_input(body)
    cursor_step = None
    if cursor is not None:
        # The increment is a Cast -> Mul chain, not an Add, so it is not
        # asserted structurally here: the pin only needs the cursor's *start*
        # to be 0, and that is checked. Whether the per-step value the pin
        # substitutes is the right one is settled by the bmodel itself --
        # `tests/test_ocr_layout.py` compares the decoded HTML against Paddle's
        # predictor, which is a far stronger check than pattern-matching the
        # graph.
        start = _initializer_value(graph, loop.input[2 + carried_in.index(cursor)])
        if start != 0:
            raise SystemExit(f"cursor starts at {start}, not 0 -- the step index "
                             f"is not the cursor value")
        # The cursor's carried *output* on the same rank-0 int64 signature is
        # the post-increment value, i.e. the slot this step writes to. Pinning
        # both collapses the clamp/Range chain the scatter index would
        # otherwise be computed from.
        cursor_step = _cursor_output(body, cursor)

    cur = list(loop.input[2:])            # values fed into step 0
    uid = 0
    for step in range(steps):
        subst = {}
        for name, value in zip(carried_in, cur):
            subst[name] = value
        if cursor is not None:
            for name, value in ((cursor, step), (cursor_step, step + 1)):
                if name is None:
                    continue
                subst[name] = f"{name}__const{step}"
                new_nodes.append(helper.make_node(
                    "Constant", [], [subst[name]],
                    name=f"{name}__Const{step}",
                    value=numpy_helper.from_array(
                        np.array(value, dtype=np.int64), name=f"{name}_v{step}")))

        def rename(name: str) -> str:
            """Step-local name for body-internal values; outer names unchanged."""
            if name in subst:
                return subst[name]
            if name in produced_in_body:
                return f"{name}__s{step}"
            return name

        for node in body_nodes:
            nn = onnx.NodeProto()
            nn.CopyFrom(node)
            nn.name = f"{node.name or node.op_type}_s{step}_{uid}"
            uid += 1
            for j, name in enumerate(nn.input):
                if name:
                    nn.input[j] = rename(name)
            for j, name in enumerate(nn.output):
                nn.output[j] = rename(name)
            # The body's copies of the cursor are superseded by the literals.
            if nn.output and nn.output[0] in (rename(cursor),
                                              rename(cursor_step or "")):
                continue
            new_nodes.append(nn)
        cur = [f"{name}__s{step}" for name in carried_out]

    # The graph's post-loop nodes read the Loop's outputs (cond, carried...).
    # The graph's post-loop nodes read the Loop's *output names*; point each at
    # the last unrolled step's value, then drop the Loop.
    rename = {}
    for k, out in enumerate(loop.output[1:]):
        rename[out] = cur[k + 1]      # +1: the Loop omits the `done` flag
    for node in graph.node:
        for j, name in enumerate(node.input):
            if name in rename:
                node.input[j] = rename[name]

    kept = [n for n in graph.node if n.op_type != "Loop"]
    graph.ClearField("node")
    graph.node.extend(new_nodes + kept)
    dead = prune_dead(graph)
    if dead:
        print(f"  pruned {dead} nodes left dangling by the dropped If")
    topo_sort(graph)
    print(f"  unrolled {steps} decoder steps "
          f"({len(new_nodes)} nodes added, body pseudo-ops dropped: "
          f"{sorted(set(dropped))})")
    return steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--steps", type=int, default=64,
                    help="decoder steps to unroll (SLANet_plus max is 500)")
    args = ap.parse_args()

    model = onnx.load(str(args.onnx))
    hoisted = hoist_constants(model.graph)
    print(f"hoisted {hoisted} captured Constant nodes to initializers")
    moved = inline_captures(model.graph)
    print(f"inlined {moved} captured initializers into the Loop body")
    unroll(model.graph, args.steps)
    gathered = replace_onehot_with_gather(model.graph)
    print(f"rewrote {gathered} OneHot -> Gather (removes the TPU_DYNAMIC subnet)")
    onnx.checker.check_model(model)
    onnx.save(model, str(args.out))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
