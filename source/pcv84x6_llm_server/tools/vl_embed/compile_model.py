#!/usr/bin/env python3
"""Compile pinned Qwen3-VL/WeMM encoders with TPU-MLIR's native lowering.

The existing converter supplies M-RoPE, Q/K norms, ViT and DeepStack. This
adapter generates only the embedding/prefill graphs: no LM head or KV cache
is needed for retrieval. The final block includes the model's final RMSNorm.
Requires TPU-MLIR 1.30.2 with Qwen3VLConverter and submit_deploy_task.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import shutil
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--family", choices=["qwen3-vl", "wemm"], default="qwen3-vl")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seq-length", type=int, default=2048)
    parser.add_argument("--max-pixels", type=int, default=1310720,
                        help="official image budget; 262144 is a lower-quality performance candidate")
    parser.add_argument("--quantize", choices=["bf16", "w8bf16", "w4bf16"], default="bf16")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--cores", type=int, choices=[1, 4], default=4)
    parser.add_argument("--prefill", choices=["dynamic", "buckets"], default="buckets",
                        help="dynamic language graphs, or aligned 128/512/1024/context buckets")
    parser.add_argument("--again", action="store_true")
    opts = parser.parse_args()
    wemm = opts.family == "wemm"
    if wemm and opts.prefill != "buckets":
        parser.error("WeMM uses aligned buckets for the Gated DeltaNet prefill")
    if wemm and opts.seq_length % 128:
        parser.error("WeMM sequence length must be a multiple of the 128-token compiler mask")
    if wemm and opts.max_pixels < 65536:
        parser.error("WeMM max-pixels must cover its 65536-pixel minimum")
    if opts.seq_length < 64 or opts.max_pixels < 4096 or opts.max_pixels % 1024:
        parser.error("seq-length >= 64; max-pixels >= 4096 and divisible by 1024")
    if opts.seq_length > (8192 if opts.prefill == "buckets" else 32768):
        parser.error("seq-length exceeds the runtime limit (buckets: 8192; dynamic: 32768)")
    if opts.max_pixels // 1024 + 64 > opts.seq_length:
        parser.error("seq-length must leave room for image tokens and the prompt")
    import tpu_mlir  # populates the compiler and runtime environment
    if not os.environ.get("VL_EMBED_TPU_ENV"):
        os.environ["VL_EMBED_TPU_ENV"] = "1"
        os.execvpe(sys.executable, [sys.executable, __file__, *sys.argv[1:]], os.environ)

    import numpy as np
    if wemm:
        from llm.Qwen3_5Converter import Qwen3_5Converter as BaseConverter
    else:
        from llm.Qwen3VLConverter import Qwen3VLConverter as BaseConverter
    from llm.LlmConverter import LlmList, MLIRImporter, top
    from llm.ModelHandle import SafetensorsModelHandle
    from llm.transformers_compat import load_auto_config
    if wemm:
        from wemm_gdn_primitives import chunk_gated_delta_rule

    source_root = Path(opts.model).resolve()
    source = json.loads((source_root / "source_manifest.json").read_text())
    repo = "tencent/WeMM-Embedding-2B" if wemm else "Qwen/Qwen3-VL-Embedding-2B"
    revision = ("bbd6cd4bf52cfc6716f752a2df80b2706720bd95" if wemm
                else "9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda")
    if source.get("repo") != repo or source.get("revision") != revision:
        raise ValueError("Run download_model.py for the pinned embedding checkpoint first")
    expected = ("e1a1ad752808c26965aa97d37bf4a9bca71d838513f41e83790cb1e71cac6e59" if wemm
                else "c73fa9caeddeb3ff831d46c085a7a5708343248ca777e90f2d486964464509c1")
    digest = hashlib.sha256()
    with (source_root / "model.safetensors").open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Checkpoint SHA-256 differs from the pinned embedding model")

    class EmbeddingConverter(BaseConverter):
        def gen_config(self):
            Path(self.config_dir).mkdir(parents=True, exist_ok=True)
            # Do not bundle partial downloads or weight files in the runtime
            # config; the generic converter recursively copies its model dir.
            for name in ("config.json", "tokenizer.json", "tokenizer_config.json",
                         "special_tokens_map.json", "added_tokens.json", "chat_template.jinja",
                         "merges.txt", "vocab.json", "preprocessor_config.json", "processor_config.json",
                         "embedding_chat_template.jinja", "source_manifest.json"):
                if (source_root / name).is_file():
                    shutil.copy2(source_root / name, Path(self.config_dir) / name)

        def gen_embedding_lmhead_mlir(self):
            # Same embedding gather as the upstream LLM converter, without its
            # vocabulary projection or decode-only single-token graph.
            key = self.model_info.weights[LlmList.EMBEDING] + ".weight"
            np.savez("embedding_top_weights.npz", **{key: self.model.read(key)})
            shape = [1, self.max_input_length, self.hidden_size]
            m = MLIRImporter([[1, self.max_input_length]], [shape], "embedding",
                             self.platform, ["INT32"],
                             weight_file="../embedding_top_weights.npz")
            ids = m.create_input_op(self.get_loc("input_ids", m), 0)
            table = m.create_weight_op(key, [self.vocab_size, self.hidden_size])
            out = top.GatherOp(m.get_tensor_type(shape), table, ids, axis=0,
                               loc=self.get_loc("embedding", m), ip=m.insert_point).output
            m.create_return_op([out])
            self.save_mlir_module(m, "embedding")

        def save_mlir_module(self, module, name):
            if name.startswith("block_cache_"):
                return
            if wemm and name == "embedding":
                # A distinct BMRT network name prevents accidentally pairing
                # this hybrid encoder with the old Qwen3-VL tokenizer/runtime.
                src = module.print_module()
                if src.count("module @embedding ") != 1:
                    raise RuntimeError("unexpected embedding MLIR module header")
                src = src.replace("module @embedding ", "module @wemm_embedding ", 1)
                module = SimpleNamespace(print_module=lambda: src)
            bucket = getattr(self, "active_bucket", None)
            if bucket and name.startswith("block_"):
                renamed = f"{name}_s{bucket}"
                # Each shape needs a unique BMRT network name. Preserve the
                # shared weight filename so model_tool can deduplicate weights.
                src = module.print_module()
                marker = f"module @{name} "
                if src.count(marker) != 1:
                    raise RuntimeError("unexpected TPU-MLIR module header")
                src = src.replace(marker, f"module @{renamed} ", 1)
                module = SimpleNamespace(print_module=lambda: src)
                name = renamed
            BaseConverter.save_mlir_module(module, name)
            # Upstream's shape-infer check materializes a second copy of every
            # weight in the graph folder. Deployment reads the original MLIR
            # and its shared ../*_top_weights.npz, not these check artifacts.
            graph_dir = Path(name)
            checked_weights = graph_dir / f"{name}_top_f32_all_weight.npz"
            if checked_weights.name not in module.print_module():
                (graph_dir / f"{name}_test.mlir").unlink(missing_ok=True)
                checked_weights.unlink(missing_ok=True)

        def gen_all_mlir(self):
            self.gen_embedding_lmhead_mlir()
            if not wemm:
                self.gen_add_mlir()
            # Visual attention is bidirectional: padding changes its result.
            # Keep ViT dynamic even when language prefill uses static buckets.
            self.dynamic = True
            self.gen_vit_mlir()
            self.dynamic = opts.prefill == "dynamic"
            # The vendor converter has no GDN factory hook. Scope this
            # replacement to WeMM export, including its joined worker threads.
            original_gdn = top.ChunkGatedDeltaRuleOp if wemm else None
            try:
                if wemm:
                    top.ChunkGatedDeltaRuleOp = chunk_gated_delta_rule
                for bucket in buckets:
                    self.active_bucket = bucket if not self.dynamic else None
                    self.max_input_length = bucket
                    self.position_shape = [3, bucket]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=opts.jobs) as pool:
                        for future in [pool.submit(self.gen_block_mlir, i)
                                       for i in range(self.num_layers)]:
                            future.result()
            finally:
                if wemm:
                    top.ChunkGatedDeltaRuleOp = original_gdn
            self.active_bucket = None
            self.max_input_length = opts.seq_length
            self.position_shape = [3, opts.seq_length]

        def compile_all(self):
            self.compile_common("embedding", with_size=True)
            if not wemm:
                self.compile_add_mlir()
            self.dynamic = True
            if wemm:
                self.compile_vit()
            else:
                self.compile_vit_mlir()
            for bucket in buckets:
                for i in range(self.num_layers):
                    name = f"block_{i}" + (f"_s{bucket}" if opts.prefill == "buckets" else "")
                    self.dynamic = opts.prefill == "dynamic"
                    if not self.register_bmodel(name, with_size=True):
                        if wemm and self.llm_config.layer_types[i] == "linear_attention":
                            source_mlir = (Path(name) / f"{name}.mlir").read_text()
                            locations = re.findall(r'loc\("([^\"]+)"\)', source_mlir)
                            precision = {n: ("F16" if n.endswith("_MatMulOp") else "F32")
                                         for n in locations if ".gdn_fp32." in n}
                            if not precision or '"top.ChunkGatedDeltaRule"' in source_mlir:
                                raise ValueError("WeMM requires the static primitive GDN export")
                            precision.update({"recurrent_states": "F32"})
                            for n in locations:
                                if n.endswith(("linear_attn.in_proj_a.softplus", "linear_attn.in_proj_a.mul")):
                                    precision[n] = "F32"
                            table = "gdn_precision.txt"
                            (Path(name) / table).write_text("".join(
                                f"{n} {mode}\n" for n, mode in sorted(precision.items())))
                            self.submit_deploy_task(name, [
                                f"--quantize {self.quantize}",
                                f"--q_group_size {self.q_group_size}",
                                f"--quantize_table {table}", "--quant_input", "--quant_output",
                            ], symmetric=self.symmetric)
                        elif wemm:
                            # The 1.30.2 four-core layer-group path corrupts
                            # this partial-RoPE attention block on real inputs
                            # (isolated block cosine .9691; ungrouped .99996).
                            # Keep its attention kernel; disable only grouping.
                            self.submit_deploy_task(name, [
                                f"--quantize {self.quantize}",
                                f"--q_group_size {self.q_group_size}",
                                "--quant_input", "--quant_output", "--disable_layer_group",
                            ], symmetric=self.symmetric)
                        else:
                            self._deploy_block_phase(name, i)
            self.execute_tasks()
            self.combine()

    buckets = (sorted({min(128, opts.seq_length), min(512, opts.seq_length),
                       min(1024, opts.seq_length), opts.seq_length})
               if opts.prefill == "buckets" else [opts.seq_length])
    args = SimpleNamespace(
        model_path=str(Path(opts.model).resolve()), out_dir=str(Path(opts.out_dir).resolve()),
        seq_length=opts.seq_length, max_input_length=opts.seq_length, chunk_length=0,
        quantize=opts.quantize, num_device=1, distribute_strategy="tp", batch=1,
        q_group_size=64 if opts.quantize == "w4bf16" else 0, symmetric=False,
        chip="bm1684x2", embedding_disk=False, dynamic=opts.prefill == "dynamic", use_history_kv=False,
        debug=False, only_mlir=False, lora_max_rank=0, do_sample=False, num_core=opts.cores,
        again=opts.again, max_pixels=opts.max_pixels,
        max_shape=[int(opts.max_pixels ** 0.5)] * 2, gen_test_input=False,
    )
    config = load_auto_config(args.model_path, trust_remote_code=False)
    if config.model_type != ("qwen3_5" if wemm else "qwen3_vl") or config.text_config.hidden_size != 2048:
        raise ValueError("Model architecture does not match the selected 2B checkpoint")
    converter = EmbeddingConverter(args, config, loader=SafetensorsModelHandle(args.model_path))
    if wemm:
        # Never reuse compiled fused-GDN graphs from an earlier experiment.
        converter.bmodel_dir += "_gdn_primitives_v2_fa_ungrouped"
    converter.max_workers = max(1, opts.jobs)
    converter.out_bmodel = str(Path(args.out_dir) / (
        f"{'wemm-embedding-2b' if wemm else 'qwen3-vl-embedding-2b'}_{opts.quantize}_seq{opts.seq_length}_"
        f"pixels{opts.max_pixels}_cv84x6_{opts.cores}core"
        f"{'_buckets' if opts.prefill == 'buckets' else ''}"
        f"{'_gdnmixed' if wemm else ''}.bmodel"))
    converter.run()
    manifest = {
        "model_type": "wemm_embedding" if wemm else "qwen3_vl_embedding",
        "kind": "embedding", "supports_vision": True,
        "vector_family": repo, "hidden_size": 2048,
        "seq_length": opts.seq_length, "max_pixels": opts.max_pixels,
        "min_pixels": 65536 if wemm else 4096,
        "quantize": opts.quantize, "source_revision": revision,
        "chip": "bm1684x2", "cores": opts.cores,
        "prefill": opts.prefill, "buckets": buckets,
        "default_instruction": "" if wemm else "Represent the user's input.",
    }
    if wemm:
        manifest["gdn_implementation"] = "static_primitives_v2"
        manifest["gdn_precision"] = "fp32_state_fp16_matmul"
        manifest["full_attention_codegen"] = "static_ungrouped"
    (Path(converter.config_dir) / "embedding_config.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    print(converter.out_bmodel)


if __name__ == "__main__":
    main()
