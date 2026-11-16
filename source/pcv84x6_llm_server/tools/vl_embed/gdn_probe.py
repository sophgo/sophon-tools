#!/usr/bin/env python3
"""Generate a deterministic GDN operator probe, or compare its board output.

Generation requires TPU-MLIR, Torch and the pinned Transformers 5.2.0
modeling_qwen3_5.py source. Comparison needs only NumPy. This tests a nonzero
initial state and chunk carry independently of the full model and tokenizer.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--seq-length", type=int, default=2048)
    p.add_argument("--case", choices=("random", "correlated", "large-decay"), default="random")
    p.add_argument("--reference-source", help="Transformers 5.2.0 modeling_qwen3_5.py")
    p.add_argument("--actual", help="compare output0.bin from gdn_probe.cpp")
    a = p.parse_args()
    import numpy as np
    root = Path(a.out_dir).resolve()
    if a.actual:
        expected = np.fromfile(root / "reference.bin", np.float32).astype(np.float64)
        actual = np.fromfile(a.actual, np.float32).astype(np.float64)
        if actual.shape != expected.shape or not np.isfinite(actual).all():
            raise ValueError("board output has wrong size or non-finite values")
        norm = np.linalg.norm(expected) * np.linalg.norm(actual)
        cosine = float(expected @ actual / norm) if norm else 0.0
        report = {"cosine": cosine, "max_abs": float(abs(expected-actual).max()),
                  "relative_l2": float(np.linalg.norm(expected-actual)/np.linalg.norm(expected)),
                  "passed": cosine >= .999}
        (root / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
        if not report["passed"]:
            raise SystemExit(1)
        return
    if not a.reference_source:
        p.error("--reference-source is required when generating the probe")
    if not 64 <= a.seq_length <= 8192 or a.seq_length % 64:
        p.error("seq-length must be a multiple of 64 in [64,8192]")
    import tpu_mlir  # initializes compiler paths before the re-exec
    if not os.environ.get("GDN_PROBE_TPU_ENV"):
        os.environ["GDN_PROBE_TPU_ENV"] = "1"
        os.execvpe(sys.executable, [sys.executable, __file__, *sys.argv[1:]], os.environ)
    import torch
    import torch.nn.functional as F
    from mlir.ir import Location
    from llm.LlmConverter import MLIRImporter, Platform
    from wemm_gdn_primitives import chunk_gated_delta_rule

    # Run the original reference functions without importing optional vision
    # dependencies. Their source hash is recorded with the generated fixture.
    source = Path(a.reference_source).read_bytes()
    body = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
            and n.name in ("l2norm", "torch_chunk_gated_delta_rule")]
    if len(body) != 2:
        raise ValueError("reference source does not contain the expected GDN functions")
    ns = {"torch": torch, "F": F}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<reference-gdn>", "exec"), ns)
    torch.set_num_threads(2)
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    length = a.seq_length
    shapes = [[1,length,16,128]]*3 + [[1,length,16]]*2 + [[1,16,128,128]]
    names = ("q", "k", "v", "g", "beta", "state")
    m = MLIRImporter(shapes, [shapes[0]], "gdn_primitives", Platform.LLM,
                     ["F32"]*6, weight_file="gdn_weights.npz")
    inputs = [m.create_input_op(Location.name(name), i) for i,name in enumerate(names)]
    tril = m.create_weight_op("tril", [64,64])
    eye = m.create_weight_op("eye", [64,64])
    out = chunk_gated_delta_rule(m.get_tensor_type(shapes[0]), *inputs, eye, eye, tril, eye,
                                num_k_heads=16, num_v_heads=16, d=128, chunk_size=64,
                                use_qk_l2norm=True, scale=128**-.5,
                                loc=Location.name("probe"), ip=m.insert_point).attn_out
    m.create_return_op([out])
    mlir = m.print_module()
    Path("gdn_primitives.mlir").write_text(mlir)
    np.savez("gdn_weights.npz", tril=np.tril(np.ones((64,64),np.float32)),
             eye=np.eye(64,dtype=np.float32))
    checked = subprocess.run(["tpuc-opt", "--shape-infer", "gdn_primitives.mlir",
                              "-o", "gdn_checked.mlir"], capture_output=True, text=True)
    if checked.returncode:
        raise RuntimeError("GDN shape validation failed: " + checked.stderr)
    names_mm = re.findall(r'loc\("([^\"]+_MatMulOp)"\)', mlir)
    Path("gdn_precision.txt").write_text("".join(name+" F16\n" for name in names_mm))
    torch.manual_seed(34)
    q,k,v = [torch.randn(shapes[0]) for _ in range(3)]
    gates = -F.softplus(torch.randn(shapes[3])) * .3
    beta, state = torch.sigmoid(torch.randn(shapes[4])), torch.randn(shapes[5]) * .1
    if a.case == "correlated":
        q = q[:,:1].expand_as(q).clone()
        k = k[:,:1].expand_as(k).clone()
        gates.fill_(-.001)
        beta.fill_(.9)
    elif a.case == "large-decay":
        gates.fill_(-2000.)
    values = (q,k,v,gates,beta,state)
    ref,_ = ns["torch_chunk_gated_delta_rule"](
        q,k,v,gates,beta,initial_state=state,use_qk_l2norm_in_kernel=True)
    np.savez("inputs.npz", **{name:x.numpy() for name,x in zip(names,values)})
    np.savez("reference.npz", output=ref.numpy())
    for i,x in enumerate(values):
        x.numpy().tofile(f"input{i}.bin")
    ref.numpy().tofile("reference.bin")
    Path("fixture.json").write_text(json.dumps({
        "seed": 34, "case": a.case, "seq_length": length, "input_shapes": shapes,
        "reference_source_sha256": hashlib.sha256(source).hexdigest(),
    }, indent=2) + "\n")
    print(root)


if __name__ == "__main__":
    main()
