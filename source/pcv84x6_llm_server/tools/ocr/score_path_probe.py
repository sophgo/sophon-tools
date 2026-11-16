#!/usr/bin/env python3
"""Why the score path cannot be made F32 on CV84X6, and what was measured.

MYS-2610's design fixed plan (b): keep the operator path that produces the
layout scores (``linear_16`` and everything after it up to the score output) in
F32 with tpu-mlir's ``--quantize_table``, leave the rest F16. If that cannot
reach the 95% box-match target, plan (a) follows: emit the score itself as
unquantised F32 and do the projection in numpy.

**Both are blocked by the backend, not by the qtable machinery.** This file
records the probes so the next person does not repeat them, and so the report's
claim is backed by commands rather than by an impression.

What each probe establishes
---------------------------

``qtable`` is honoured end to end. ``--quantize_table`` with ``score_add F32``
really does lower the score matmul to ``tpu.MatMul ... xf32`` — the MLIR proves
it. What then fails is ``--codegen``::

    ERROR: ASSERT .../atomic_mm_gen_cmd.c: 25: 0
    ASSERT info: mm1 removed, use mm2 instead

i.e. the FP32 matmul emitter on ``bm1684x2`` only has the "mm2" form and the
planner still hands it an "mm1" request. A **two-node** ONNX (MatMul + Add,
``[1,300,256] x [256,25]``) reproduces it on its own, so it is not the size or
the shape of the layout graph:

===========================  ==========  ============
probe                        chip        result
===========================  ==========  ============
F32 MatMul, 6 shapes         bm1684x2    **all fail** (same assert)
same probe                   bm1684x     compiles
F32 1x1 Conv (K=256,N=25)    bm1684x2    compiles
F32 LayerNorm                bm1684x2    compiles
F32 MatMul, 1/2/4 cores      bm1684x2    all fail
F32 MatMul + --high_precision bm1684x2   fails
F32 MatMul + --opt 1         bm1684x2    fails
===========================  ==========  ============

So the chip's F32 support is real but excludes matmul. That kills plan (b) at
the qtable step and plan (a)'s "unquantised F32 score inside the graph".

The 1x1-conv substitution does compile, and is what a reader would try next, so
it is measured too: rewriting the score ``MatMul`` as a mathematically
equivalent ``Transpose -> Unsqueeze -> Conv1x1 -> Squeeze -> Transpose`` keeps
the output contract, but any tensor left in F32 re-exposes the ``Shape``/
``Range`` operators that the F16 build had constant-folded away. Those lower to
``tpu.Device2Host`` (a host round-trip), which makes tpu-mlir split the module
into a second ``TPU_DYNAMIC`` subnet — the exact construct stage A recorded as
hanging this chip. Adding one extra F32 output to the *unmodified* baseline
graph does the same, which isolates the cause to "any F32 island", not to the
conv rewrite.

``--quant_output`` was also tried (it casts outputs, and the A2 report already
noted it does not change internal F16). Measured: all seven detector outputs
stay ``float16``, so it moves nothing.

Usage
-----

    python3 tools/ocr/score_path_probe.py --work-dir /tmp/probe   # builds probes
    # then, inside the tpu-mlir container, run the emitted commands

The script only *writes* the probe ONNX files and prints the compile commands;
it does not need tpu-mlir itself, so it runs on any host that has onnx.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

#: The score projection's real shape, taken from the cut heads graph
#: (``linear_16.w_0_deepcopy_712`` is ``[256, 25]``: 256 hidden -> 25 classes).
SCORE_K, SCORE_N = 256, 25
#: The query count the TopK ranks over.
SCORE_M = 300


def build_matmul_probe(path: Path, m: int, k: int, n: int) -> None:
    """The smallest graph that reproduces the codegen assert: MatMul + bias."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(0)
    w = numpy_helper.from_array((rng.standard_normal((k, n)) * 0.02).astype(np.float32), "W")
    b = numpy_helper.from_array(np.zeros((1, 1, n), np.float32), "B")
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, m, k])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, m, n])
    nodes = [helper.make_node("MatMul", ["x", "W"], ["mm"], name="mm"),
             helper.make_node("Add", ["mm", "B"], ["y"], name="score_add")]
    graph = helper.make_graph(nodes, path.stem, [x], [y], [w, b])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def build_conv_probe(path: Path, m: int, k: int, n: int) -> None:
    """The 1x1-conv substitution for the same projection.

    ``y[m,n] = x[m,k] @ W[k,n] + b[n]`` becomes, with the weight laid out as a
    ``[N, K, 1, 1]`` conv kernel and the activation transposed to ``[1,K,M,1]``,
    a convolution with a 1x1 kernel: identical arithmetic, and it compiles in
    F32 on this chip where the matmul does not.
    """
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(0)
    w = rng.standard_normal((k, n)) * 0.02
    kernel = numpy_helper.from_array(w.T.reshape(n, k, 1, 1).astype(np.float32), "score_conv_w")
    bias = numpy_helper.from_array(np.zeros((n,), np.float32), "score_conv_b")
    axes = numpy_helper.from_array(np.array([3], np.int64), "score_ax")
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, m, k])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, m, n])
    nodes = [
        helper.make_node("Transpose", ["x"], ["t"], perm=[0, 2, 1], name="score_t"),
        helper.make_node("Unsqueeze", ["t", "score_ax"], ["t4"], name="score_u"),
        helper.make_node("Conv", ["t4", "score_conv_w", "score_conv_b"], ["c"],
                         name="score_conv", kernel_shape=[1, 1]),
        helper.make_node("Squeeze", ["c", "score_ax"], ["c3"], name="score_s"),
        helper.make_node("Transpose", ["c3"], ["y"], perm=[0, 2, 1], name="score_o"),
    ]
    graph = helper.make_graph(nodes, path.stem, [x], [y], [kernel, bias, axes])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def conv_equivalent(w: np.ndarray, b: np.ndarray, x: np.ndarray) -> np.ndarray:
    """The numpy side of :func:`build_conv_probe`, for the equivalence test.

    Kept next to the graph rewrite on purpose: a test can then assert that the
    rewritten graph and this expression agree, so the substitution is verified
    by arithmetic rather than by reading it.
    """
    return x @ w + b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True, type=Path)
    args = ap.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    shapes = [(SCORE_M, SCORE_K, SCORE_N), (SCORE_M, SCORE_K, 32),
              (SCORE_M, SCORE_K, 64), (SCORE_M, 1024, SCORE_N),
              (1024, SCORE_K, SCORE_N), (64, SCORE_K, SCORE_N)]
    for m, k, n in shapes:
        p = args.work_dir / f"mm_{m}_{k}_{n}.onnx"
        build_matmul_probe(p, m, k, n)
        print(f"wrote {p}")

    p = args.work_dir / f"conv_{SCORE_M}_{SCORE_K}_{SCORE_N}.onnx"
    build_conv_probe(p, SCORE_M, SCORE_K, SCORE_N)
    print(f"wrote {p}")

    print("\n# Inside the tpu-mlir container, for each probe (the qtable key is")
    print("# the *op's* loc name, which is what tpuc-opt matches on):")
    print("  model_transform --model_name mm --model_def mm_300_256_25.onnx \\")
    print("      --input_shapes '[[1,300,256]]' --mlir mm.mlir")
    print("  printf 'score_add F32\\n' > q.txt")
    print("  model_deploy --mlir mm.mlir --quantize F16 --quantize_table q.txt \\")
    print("      --chip bm1684x2 --num_core 4 --model mm.bmodel")
    print("  # -> ASSERT atomic_mm_gen_cmd.c: 'mm1 removed, use mm2 instead'")
    print("  # Same command with --chip bm1684x compiles, which is what makes")
    print("  # this a bm1684x2 backend gap rather than a qtable problem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
