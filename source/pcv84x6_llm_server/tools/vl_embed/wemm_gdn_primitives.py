"""Stateless WeMM GDN expressed in ordinary TOP operations.

The 64-row triangular system is inverted by merging 2/4/8/16/32/64-row
diagonal blocks. This avoids large cancelling powers of A for correlated
keys. Chunk state and gate cumulative sums stay in FP32. The caller
must keep ``.gdn_fp32.`` operations in FP32, except MatMul in FP16, and use
static codegen. The BM1684X2 compiler cannot emit a general FP32 MatMul.
"""
import re
from types import SimpleNamespace


def chunk_gated_delta_rule(output, query, key, value, g, beta, initial_state,
                          triu, strict_triu, tril, eye, *, num_k_heads,
                          num_v_heads, d, chunk_size, use_qk_l2norm, scale,
                          loc, ip):
    from mlir.ir import F32Type, Location, NoneType, RankedTensorType, StringAttr
    from mlir.dialects import top

    shape = list(RankedTensorType(query.type).shape)
    if (shape[0] != 1 or num_k_heads != 16 or num_v_heads != 16 or d != 128 or
            chunk_size != 64 or not use_qk_l2norm or shape[1] % 64 or
            not 64 <= shape[1] <= 8192):
        raise ValueError("WeMM GDN requires B=1, H=16, D=128 and 64-aligned rows in [64,8192]")
    length, heads, width = shape[1], num_k_heads, chunk_size
    chunks, batches = length // width, heads * (length // width)
    match = re.search(r'"([^\"]+)"', str(loc))
    if not match:
        raise ValueError("GDN operation must have a named location")
    prefix = match.group(1) + ".gdn_fp32."
    counter = 0

    def location(name):
        nonlocal counter
        counter += 1
        return Location.name(prefix + str(counter) + "_" + name)

    def tensor(shape):
        return RankedTensorType.get(shape, F32Type.get())

    none = top.NoneOp(NoneType.get(), loc=location("none"), ip=ip).result

    def emit(cls, out_shape, *inputs, **attrs):
        return cls(tensor(out_shape), *inputs, **attrs,
                   loc=location(cls.__name__), ip=ip).output

    def reshape(x, shape):
        return emit(top.ReshapeOp, shape, x, shape=shape)

    def permute(x, shape, order):
        return emit(top.PermuteOp, shape, x, order=order)

    def mul(x, y, shape):
        return emit(top.MulOp, shape, [x, y])

    def add(x, y, shape):
        return emit(top.AddOp, shape, [x, y])

    def sub(x, y, shape):
        return emit(top.SubOp, shape, [x, y])

    def mm(x, y, shape, *, rt=False, lt=False):
        def transpose_last(a):
            dims = list(RankedTensorType(a.type).shape)
            order = list(range(len(dims)))
            order[-1], order[-2] = order[-2], order[-1]
            return permute(a, [dims[i] for i in order], order)

        if lt:
            # TOP's CPU evaluator in 1.30.2 crashes on batched left_transpose.
            # Materialize it explicitly, also making the state update layout
            # unambiguous to static codegen.
            x = transpose_last(x)
        if rt:
            y = transpose_last(y)
        return emit(top.MatMulOp, shape, x, y, none)

    def exp(x, shape):
        return emit(top.ExpOp, shape, x)

    def normalize(x):
        square = mul(x, x, shape)
        norm = emit(top.ReduceOp, [1, length, heads, 1], square,
                    axes=[3], keepdims=True, mode=StringAttr.get("ReduceSum"))
        norm = emit(top.AddConstOp, [1, length, heads, 1], norm, const_val=1e-6)
        inv = emit(top.RsqrtOp, [1, length, heads, 1], norm)
        return mul(x, inv, shape)

    def to_chunks(x, trailing):
        if trailing:
            x = permute(x, [1, heads, length, d], [0, 2, 1, 3])
            return reshape(x, [batches, width, d])
        x = permute(x, [1, heads, length], [0, 2, 1])
        return reshape(x, [batches, width, 1])

    q = to_chunks(normalize(query), True)
    q = emit(top.MulConstOp, [batches, width, d], q, const_val=scale)
    k, v = to_chunks(normalize(key), True), to_chunks(value, True)
    b, gates = to_chunks(beta, False), to_chunks(g, False)
    vec, mat, col = [batches, width, d], [batches, width, width], [batches, width, 1]
    # A triangular reduction keeps cumulative gates in FP32. An FP16 MatMul
    # here both loses small decays and overflows for sufficiently large gates.
    gates_row = permute(gates, [batches, 1, width], [0, 2, 1])
    gcum = emit(top.ReduceOp, col, mul(gates_row, tril, mat), axes=[2],
                keepdims=True, mode=StringAttr.get("ReduceSum"))
    relative = sub(gcum, permute(gcum, [batches, 1, width], [0, 2, 1]), mat)
    relative = mul(relative, tril, mat)  # avoid exp(large positive upper entries)
    decay = mul(exp(relative, mat), tril, mat)
    kb, vb = mul(k, b, vec), mul(v, b, vec)
    lower = sub(tril, eye, [width, width])
    a = mul(mul(mm(kb, k, mat, rt=True), decay, mat), lower, mat)
    a = emit(top.MulConstOp, mat, a, const_val=-1.0)
    def corner(x, size):
        # shape-infer adds a leading broadcast dimension to shared masks.
        # Restore their two matrix axes before slicing a diagonal block.
        x = reshape(x, [width,width])
        return emit(top.SliceOp, [size,size], x, none, none, none,
                    offset=[0,0], steps=[1,1], ends=[size,size])

    # These masks depend only on the existing constant eye/tril weights and
    # fold away at compile time; the checkpoint weight archive stays intact.
    small_lower = reshape(corner(lower, 2), [2,1,2,1])
    inverse = None
    for half in (1,2,4,8,16,32):
        block_width, count = 2*half, width // (2*half)
        block = emit(top.TileOp, [2,half,2,half], small_lower, tile=[1,half,1,half])
        block = reshape(block, [1,block_width,1,block_width])
        diagonal = reshape(corner(eye, count), [count,1,count,1])
        mask = reshape(mul(diagonal, block, [count,block_width,count,block_width]), [width,width])
        cross = mul(a, mask, mat)
        if inverse is None:
            inverse = add(cross, eye, mat)
        else:
            # For [[L,0],[-C,R]], the inverse's lower-left block is
            # R^-1 C L^-1. Other blocks keep the previous inverse.
            cross = mm(mm(inverse, cross, mat), inverse, mat)
            inverse = add(inverse, cross, mat)
    solved_v = mm(inverse, vb, vec)
    eg = exp(gcum, col)
    solved_k = mm(inverse, mul(kb, eg, vec), vec)
    qexp = mul(q, eg, vec)
    attn = mul(mm(q, k, mat, rt=True), decay, mat)

    def chunk(x, index, rows=width, columns=d, last=False):
        x = reshape(x, [heads, chunks, rows, columns])
        offsets = [0, index, rows - 1 if last else 0, 0]
        ends = [heads, index + 1, rows, columns]
        result_rows = 1 if last else rows
        x = emit(top.SliceOp, [heads, 1, result_rows, columns], x, none, none, none,
                 offset=offsets, steps=[1, 1, 1, 1], ends=ends)
        return reshape(x, [heads, result_rows, columns])

    state_shape, row_shape = [heads, d, d], [heads, width, d]
    state = reshape(initial_state, state_shape)
    outputs = []
    for index in range(chunks):
        residual = sub(chunk(solved_v, index), mm(chunk(solved_k, index), state, row_shape), row_shape)
        outputs.append(add(mm(chunk(qexp, index), state, row_shape),
                           mm(chunk(attn, index, columns=width), residual, row_shape), row_shape))
        if index + 1 < chunks:
            last_g = chunk(gcum, index, columns=1, last=True)
            relative_g = sub(last_g, chunk(gcum, index, columns=1), [heads, width, 1])
            weighted_k = mul(chunk(k, index), exp(relative_g, [heads, width, 1]), row_shape)
            state = add(mul(state, exp(last_g, [heads, 1, 1]), state_shape),
                        mm(weighted_k, residual, state_shape, lt=True), state_shape)
    # CV84X6 multi-core Concat corrupts operands beyond 16 (reproduced with
    # an isolated 32-input graph). Eight-chunk groups, transposed before the
    # outer concat, keep both levels <=16 for the supported <=8192 context.
    # Different axes/layouts also prevent canonicalization flattening the tree.
    groups = []
    for start in range(0, chunks, 8):
        part = outputs[start:start + 8]
        rows = len(part) * width
        joined = emit(top.ConcatOp, [heads, rows, d], part, axis=1) if len(part) > 1 else part[0]
        groups.append(permute(joined, [rows, heads, d], [1, 0, 2]))
    result = emit(top.ConcatOp, [length, heads, d], groups, axis=0) if len(groups) > 1 else groups[0]
    return SimpleNamespace(attn_out=reshape(result, [1, length, heads, d]))
