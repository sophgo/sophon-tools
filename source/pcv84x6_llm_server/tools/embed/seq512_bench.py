#!/usr/bin/env python3
"""MYS-2706 board measurements: single-text cost and NPU footprint, both builds.

Run on `.157` with the shipped service's lib and model-config, one process, and
nothing else of ours loaded (the resident service holds rerank+asr+ocr+seq8192,
so the "before" figure is not zero and every number below is a **delta**).

Three things this measures, and why each is worth a separate figure:

* **single text, median of 10** -- a static graph computes its whole compiled
  length on every forward, so this is the number that decides whether the short
 档 is worth having;
* **loaded, alone** -- what one build costs the heap, from ``cv_embed_create``;
* **loaded, together** -- the deployment where both are resident. Reported as the
  *second* model's incremental cost as well as the total. Both builds are loaded
  in **this one process**, where the runtime reuses the weights; the service
  runs one worker process per model, so its two-resident cost is the sum.
"""

from __future__ import annotations

import ctypes
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cmp_models import Lib  # noqa: E402
from mem_probe import MIB, device_memory  # noqa: E402


def destroy(lib, handle) -> None:
    """Release one embedding handle.

    ``cmp_models.Lib`` is the harness that has ``encode``/``forward`` but no
    destroy, and ``mem_probe.Lib`` has create/destroy but no forward -- so the
    benchmark uses the former and calls ``cv_embed_destroy`` through its
    ``ctypes`` handle directly. Passing the raw pointer (not the tuple
    ``open_model`` returns) is the whole trick.
    """
    lib.lib.cv_embed_destroy(ctypes.c_void_p(handle))

LIB = "/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so"
CONFIG = "/opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding"
HERE = Path("/data/mys2706/models")
S2048 = HERE / "qwen3-embedding-0.6b_bf16_seq2048_bm1684x2_4core_static_20261108_011851.bmodel"
S512 = HERE / "qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357.bmodel"

#: Four texts of rising length, so the cost is shown as flat (static graph) rather
#: than as one number a reader cannot place. The first is the MYS-2702 grid point
#: (~484 tokens), which is where the 83 ms / 292 ms pair comes from.
TEXTS = [
    "深度学习是机器学习的一个分支，它通过多层神经网络从数据中学习特征表示。"
    "本服务在 CV84X6 上提供离线向量化能力，用于知识库的语义检索。",
    "仓库盘点由仓管员在每个季度末执行。盘点前必须冻结出入库操作。"
    "盘点差异率超过千分之五须由财务复核，并在三个工作日内出具报告。",
    "库房管理制度第三十条：物料入库应当核对品名、规格、数量与送货单是否一致，"
    "发现短缺或破损应当在当日填写异常单并通知采购与质检；上架时按库位号顺序摆放，"
    "标识朝外，同类物料不得混放；每月末盘点一次，盘点结果由两人签字确认后归档。",
    "向量检索的候选数量由请求的 candidates 字段决定，默认二十条。"
    "BM25 与向量各取前 candidates 条，再用 RRF 融合，最后交给精排模型重排序。"
    "融合之所以用 RRF 而不是加权求和，是因为两者的分数量纲不同。",
]


def used() -> int:
    return sum(h["used_bytes"] for h in device_memory().values())


def bench(lib, handle, seq, hidden, tok, text, repeats=10):
    ids = lib.encode(tok, text)
    if len(ids) > seq:
        return None, len(ids)
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        lib.forward(handle, ids, hidden)
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times), len(ids)


def main() -> int:
    lib = Lib(LIB)
    tok = lib.open_tokenizer(str(Path(CONFIG) / "tokenizer.json"))
    base = used()
    print(f"== before: {base / MIB:.1f} MiB used")

    # -- alone, one at a time ---------------------------------------------
    alone = {}
    for name, path in (("seq2048", S2048), ("seq512", S512)):
        h, seq, hidden = lib.open_model(str(path))
        loaded = used()
        print(f"  {name:8s} seq={seq:<5d} alone delta {(loaded - base) / MIB:8.1f} MiB")
        for i, text in enumerate(TEXTS):
            median, ntokens = bench(lib, h, seq, hidden, tok, text)
            if median is None:
                print(f"    text{i + 1} ({ntokens:4d} tok): refused (over SEQLEN)")
            else:
                print(f"    text{i + 1} ({ntokens:4d} tok): {median:7.1f} ms")
        destroy(lib, h)
        assert abs(used() - base) < 8 * MIB, "the build did not release its heap"

    # -- together ----------------------------------------------------------
    h_long, seq_long, hidden_long = lib.open_model(str(S2048))
    u1 = used()
    h_short, seq_short, hidden_short = lib.open_model(str(S512))
    u2 = used()
    print(f"== together: seq2048 {((u1 - base) / MIB):.1f} MiB, "
          f"then seq512 +{((u2 - u1) / MIB):.1f} MiB, "
          f"total {((u2 - base) / MIB):.1f} MiB")
    destroy(lib, h_short)
    destroy(lib, h_long)
    print(f"== after unload both: {used() / MIB:.1f} MiB "
          f"(released {(u2 - used()) / MIB:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
