#!/usr/bin/env python3
"""Run tpu-mlir's ``llm_convert.py`` with the PaddleOCR-VL converter corrected.

The tpuc22 image (tpu-mlir ``1.30.2-20260831``) ships a ``PaddleOCRVLConverter``
that cannot compile PaddleOCR-VL **1.5**. The image was written against the 0.9B
release; 1.5 changed the vision tower and the text RoPE in ways the converter
never picked up. Three defects, all confirmed by running the converter and by
reading the 1.5 reference modelling code:

1. **vit position-embedding interpolation is declared at the wrong size.**
   ``gen_vit_mlir`` emits ``top.Interp`` with ``scale_h = (grid_h-1)/(src-1)``
   but declares an output of ``[1, C, grid_h, grid_w]``. tpu-mlir's Interp
   computes ``H' = H x scale_h`` (TopOps.td, ``Top_InterpOp``), so for the
   784x784 compile target -- grid 56, source 27 -- it infers ``27 x 55/26 =
   57`` against a declared ``56`` and ``tpuc-opt`` aborts:
   ``error infer shape: 1 1152 57 57``. The reference uses
   ``F.interpolate(size=(56,56), align_corners=False)``, so the scale is simply
   the wrong way to express it; passing ``scale = grid/src`` gives the intended
   56 and leaves the sampling geometry alone. (This is the first abort, so the
   two below only surface once it is fixed.)

2. **the vit attention output reshape drops the batch dimension.** After the
   attention permute back to ``[1, P, H, D]`` the converter reshapes with
   ``shape=[-1, embed_dim]`` -- two dims -- while declaring a rank-3 result
   ``[1, P, embed_dim]``. tpu-mlir takes the rank from the literal shape, so the
   result is rank 2 and the following ``Add`` / linear, which expect rank 3,
   abort: ``top.Reshape ... (tensor<1x3136x16x72xf32>) -> tensor<1x3136x1152xf32>
   | error infer shape: 3136 1152``. The reference keeps the batch axis
   (``reshape(1, -1, embed_dim)``), so the shape literal has to be
   ``[1, -1, self.embed_dim]``.

3. **text RoPE ignores 1.5's interleaved mrope.** 1.5's
   ``apply_multimodal_rotary_pos_emb`` splits the frequency table with
   ``mrope_section`` ([16, 24, 24]) and interleaves t/h/w, then the attention
   halves it. The converter calls the *base* ``apply_rotary_pos``, which does a
   plain 1-D ``Gather`` on a 3-row position tensor -- it declares the result as
   ``[1, dim, 1, head_dim]`` while Gather actually returns
   ``[3, dim, 1, head_dim]``, and that is the next abort
   (``error infer shape: 3 2048 1 128``). For a bmodel whose every token has
   ``t == h == w`` a single row is equivalent, and the runtime ships one row of
   positions per token, so gathering row 0 reproduces the reference exactly;
   this is the same reduction the base converter already documents for
   `sequence` positions.

4. **two ops share one loc name.** The transpose of K before the attention
   matmul reuses ``attn_k + ".permute"``, already used by the reshape-permute
   above it. tpu-mlir requires unique loc names and aborts the module with
   ``ASSERT INFO: all_names.find(name) == all_names.end()`` (Module.cpp:2120).
   Renaming the second one changes no geometry.

All fixes are applied **in memory**; nothing under site-packages changes. The
35B builds share this image, and MYS-2588 already showed what hand-edited
converters in this container cost when they leak into an unrelated build.

    python3 tools/ocr/build_paddleocr_vl.sh   # wraps this

The patch is applied by rewriting the converter's module source before it is
imported: the defects are in the middle of large methods, so a targeted textual
substitution is far less brittle than re-implementing the class here.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

CONVERTER = Path(
    "/usr/local/lib/python3.10/dist-packages/tpu_mlir/python/llm/PaddleOCRVLConverter.py")

#: (old, new) pairs applied to the converter source. Each is asserted to hit
#: exactly once -- a silent miss would mean shipping a bmodel built by the
#: unfixed code path, which is precisely the failure this shim exists to stop.
PATCHES = (
    # ---- 1. vit interp scale AND mode ------------------------------------- #
    # The reference is `F.interpolate(size=(grid_h, grid_w), mode="bilinear",
    # align_corners=False)` (modeling_paddleocr_vl.py:935-939). The converter
    # emits `mode="linear", coord_mode="align_corners"` -- both halves wrong.
    #
    # Measured on a 12x48 grid against a 27x27 source: the two coordinate modes
    # differ by up to 0.145 per position-embedding element (mean 0.012), which
    # after 27 layers put the board's vision output at cosine 0.39 against the
    # reference on identical pixels. That is the whole mismatch -- the weights
    # and the rest of the graph agree.
    #
    # Note `mode` stays "linear": TopOps.td's `InterpModeAttr` only allows
    # {nearest, linear} (it is 2-D interpolation, so "linear" already means
    # bilinear), and only `coord_mode` selects the sampling geometry.
    (
        "scale_h=float((grid_h - 1) / (sqrt_num_positions - 1)),",
        "scale_h=float(grid_h / sqrt_num_positions),",
    ),
    (
        'coord_mode=StringAttr.get("align_corners"),',
        'coord_mode=StringAttr.get("half_pixel"),',
    ),
    (
        "scale_w=float((grid_w - 1) / (sqrt_num_positions - 1)),",
        "scale_w=float(grid_w / sqrt_num_positions),",
    ),
    # ---- 2. vit attention reshape rank ------------------------------------ #
    (
        "                shape=[-1, self.embed_dim],",
        "                shape=[1, -1, self.embed_dim],",
    ),
    # ---- 3. mlp_AR permute declares its input shape ----------------------- #
    (
        """        new_op = top.PermuteOp(T([1, grid_h, 2, grid_w, 2, self.embed_dim]),
                               new_op,
                               order=[0, 1, 3, 2, 4, 5],""",
        """        new_op = top.PermuteOp(T([1, grid_h, grid_w, 2, 2, self.embed_dim]),
                               new_op,
                               order=[0, 1, 3, 2, 4, 5],""",
    ),
    # ---- 3b. vit attention mask -------------------------------------------- #
    # The generated vit declares a `full_attn_mask` input (arg2) and then never
    # uses it: the attention is a plain MatMul -> Softmax -> MatMul, so the
    # compiler prunes the argument and the graph attends over every row it is
    # given. That is why a padded image would poison real patches -- padding
    # rows would be attended to as if they were pixels.
    #
    # Adding the mask before the softmax is what makes padding legal, and it is
    # the mechanism the plan-1 acceptance criterion depends on. The mask is
    # additive with 0 on visible pairs and a large negative on masked ones,
    # which is what `modeling_paddleocr_vl.py` builds (`-10000` in the demo's
    # `make_qwen2vl_vit_attention_mask`) and what this converter's own
    # `mask_shape` input already assumes.
    (
        """    def vision_block(self, vit_mlir, id: int, in_op, cos_op, sin_op):""",
        """    def vision_block(self, vit_mlir, id: int, in_op, cos_op, sin_op,
                     mask_op=None):""",
    ),
    (
        """            new_op = self.vision_block(vit_mlir, idx, new_op, cos_op, sin_op)""",
        """            new_op = self.vision_block(vit_mlir, idx, new_op, cos_op, sin_op,
                                       mask_op=in2_op)""",
    ),
    # Create the mask input this graph already declares. `create_input_op` with
    # index 2 is what emits `full_attn_mask`; without a caller the argument was
    # dead and got pruned.
    (
        """        in0_op = vit_mlir.create_input_op(L('input_states'), 0)""",
        """        in0_op = vit_mlir.create_input_op(L('input_states'), 0)
        in2_op = vit_mlir.create_input_op(L('full_attn_mask'), 2)""",
    ),
    (
        """            attn_weights = top.SoftmaxOp(T([1, self.vnum_heads, self.num_patches,
                                            self.num_patches]),
                                         attn_weights,
                                         axis=3,""",
        """            if mask_op is not None:
                # Broadcast the [1, 1, P, P] additive mask over the head axis.
                attn_weights = top.AddOp(
                    T([1, self.vnum_heads, self.num_patches, self.num_patches]),
                    [attn_weights, mask_op],
                    do_relu=False,
                    is_scalar=False,
                    relu_limit=-1.0,
                    loc=L(eager_attn + ".mask_add"),
                    ip=ip).output
            attn_weights = top.SoftmaxOp(T([1, self.vnum_heads, self.num_patches,
                                            self.num_patches]),
                                         attn_weights,
                                         axis=3,""",
    ),
    # ---- 4. duplicate loc name ---------------------------------------------#
    # The k transpose before the attention matmul reuses the ".permute" loc of
    # the earlier reshape-permute. tpu-mlir asserts loc names are unique
    # (Module.cpp:2120), so the whole graph fails to load with
    # `all_names.find(name) == all_names.end()`.
    (
        """            k_op = top.PermuteOp(T([1, self.vnum_heads, self.vhead_dim, self.num_patches]),
                                 k_op,
                                 order=[0, 1, 3, 2],
                                 loc=L(attn_k + ".permute"),""",
        """            k_op = top.PermuteOp(T([1, self.vnum_heads, self.vhead_dim, self.num_patches]),
                                 k_op,
                                 order=[0, 1, 3, 2],
                                 loc=L(attn_k + ".permute_t"),""",
    ),
    # ---- 5. mrope --------------------------------------------------------- #
    # 1.5 interleaves three position rows (t/h/w) across the head dimension
    # using `rope_scaling.mrope_section = [16, 24, 24]`; the head's 128 dims
    # therefore split into 32 dims from the temporal row, 48 from the height row
    # and 48 from the width row. The base converter's `apply_rotary_pos` instead
    # gathers *one* row, which is only correct when t == h == w -- true for text
    # tokens, false for every image token, where t is a constant, h is the grid
    # row and w the grid column.
    #
    # Getting this wrong is silent: the model still runs, still produces
    # plausible-looking text, and simply stops depending on where a patch sits
    # in the image. Measured on one image token whose (t, h, w) was (5, 12, 18):
    # 58/128 cosines and 96/128 sines differ from the reference, by up to 1.89.
    #
    # The fix gathers each of the three rows and concatenates them in the
    # mrope_section proportions. tpu-mlir's Rope with
    # rope_mode="contiguous_halves" takes the full head_dim table and halves it
    # internally, so the frequency table must NOT be pre-halved here.
    (
        "    @override\n    def load_pretrained(self, config):",
        '''    def apply_rotary_pos(self, mlir_gen, pos_op, q_op, k_op, rotary_cos: str,
                         rotary_sin: str):
        """Interleaved M-RoPE over the three position rows of 1.5.

        `pos_op` is the bmodel's [3, dim] position tensor: row 0 carries the
        temporal index of each token, row 1 the height index and row 2 the
        width index. The reference's `apply_multimodal_rotary_pos_emb` splits
        the head dimension by `mrope_section` ([16, 24, 24], doubled to
        [32, 48, 48] because it is applied to the full head_dim) and takes those
        slices from rows 0, 1 and 2 respectively.

        The base converter took row 0 for all 128 dims. That reproduces the
        reference exactly for text (t == h == w) and is wrong for every image
        token, so the model would ignore where a patch sits in the image.
        """
        dim = pos_op.type.shape[-1]
        section = getattr(self.config.rope_scaling, "mrope_section", [16, 24, 24])
        # The reference doubles the section because it indexes the full head_dim
        # table, not the half-width frequency table.
        widths = [int(s) * 2 for s in section]
        if sum(widths) != self.head_dim:
            raise RuntimeError(
                f"mrope_section {section} covers {sum(widths)} of the "
                f"{self.head_dim} rotary dims; the section does not match this "
                "head_dim")

        def build(name: str, weight: str):
            table = mlir_gen.create_weight_op(weight + ".weight",
                                              [self.seq_length, 1, self.head_dim])
            # One Gather over all three rows, exactly as the Qwen2VL converter
            # does for the same mrope: the index tensor is [3, seq], so Gather
            # yields [3, seq, 1, head_dim] and each plane can be sliced out of
            # that single result. Gathering per row instead (three Gathers)
            # compiled but crashed the bm1684x2 address-assignment pass.
            gathered = top.GatherOp(
                mlir_gen.get_tensor_type([3, dim, 1, self.head_dim]),
                table, pos_op, axis=0,
                loc=self.get_loc(name, mlir_gen),
                ip=mlir_gen.insert_point).output
            pieces = []
            offset = 0
            for row, width in enumerate(widths):
                pieces.append(top.SliceOp(
                    mlir_gen.get_tensor_type([1, dim, 1, width]),
                    gathered,
                    mlir_gen.none_op, mlir_gen.none_op, mlir_gen.none_op,
                    offset=[row, 0, 0, offset],
                    steps=[1, 1, 1, 1],
                    ends=[row + 1, dim, 1, offset + width],
                    loc=self.get_loc(f"{name}.slice{row}", mlir_gen),
                    ip=mlir_gen.insert_point).output)
                offset += width
            return top.ConcatOp(
                mlir_gen.get_tensor_type([1, dim, 1, self.head_dim]),
                pieces, axis=3,
                loc=self.get_loc(name + ".concat", mlir_gen),
                ip=mlir_gen.insert_point).output

        cos_op = build(rotary_cos, rotary_cos)
        sin_op = build(rotary_sin, rotary_sin)
        q_op = top.RopeOp(mlir_gen.get_tensor_type(q_op.type.shape),
                          q_op, sin_op, cos_op,
                          rope_mode=StringAttr.get("contiguous_halves"),
                          loc=self.get_loc("q_proj", mlir_gen),
                          ip=mlir_gen.insert_point).output
        k_op = top.RopeOp(mlir_gen.get_tensor_type(k_op.type.shape),
                          k_op, sin_op, cos_op,
                          rope_mode=StringAttr.get("contiguous_halves"),
                          loc=self.get_loc("k_cache", mlir_gen),
                          ip=mlir_gen.insert_point).output
        return q_op, k_op

    @override
    def load_pretrained(self, config):''',
    ),
    # The base class slices the table in half; 1.5 stores the full table, so
    # rotary_embedding must not halve it a second time.
    (
        "    @override\n    def gen_vit_mlir(self):",
        '''    @override
    def rotary_embedding(self):
        from .transformers_compat import text_rotary_cos_sin
        cos, sin = text_rotary_cos_sin(self.llm_config, self.seq_length)
        return cos, sin  # full table; apply_rotary_pos slices the half it needs

    @override
    def gen_vit_mlir(self):''',
    ),
)


def _patched_source() -> str:
    src = CONVERTER.read_text(encoding="utf-8")
    for old, new in PATCHES:
        hits = src.count(old)
        if hits != 1:
            raise SystemExit(
                f"shim: expected exactly one occurrence of {old!r} in {CONVERTER}, "
                f"found {hits}. The container's converter changed; re-derive the patch.")
        src = src.replace(old, new)
    return src


def main() -> None:
    import types

    import tpu_mlir.python.llm as _llm_pkg

    mod = types.ModuleType("llm.PaddleOCRVLConverter")
    mod.__file__ = str(CONVERTER)
    exec(compile(_patched_source(), str(CONVERTER), "exec"), mod.__dict__)
    # llm_convert re-imports the converter by module name, so both spellings
    # have to resolve to the patched module.
    sys.modules["llm.PaddleOCRVLConverter"] = mod
    sys.modules["tpu_mlir.python.llm.PaddleOCRVLConverter"] = mod
    setattr(_llm_pkg, "PaddleOCRVLConverter", mod.PaddleOCRVLConverter)

    target = "/usr/local/lib/python3.10/dist-packages/tpu_mlir/python/tools/llm_convert.py"
    sys.argv = [target, *sys.argv[1:]]
    runpy.run_path(target, run_name="__main__")


if __name__ == "__main__":
    main()
