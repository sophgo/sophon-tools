# MYS-2702 原始测量数据

本目录是 [`docs/research/aux-dynamic-seq.md`](../../../docs/research/aux-dynamic-seq.md)
的原始数据与设备日志。所有文件由 `tools/embed/` 下的脚本产生，命令见报告的「复现」一节。

## 文件

| 文件 | 内容 | 产生命令 |
|---|---|---|
| `hf_embed.json` | HF `Qwen3-Embedding-0.6B` 在 7 个长度上的 1024 维向量（已 L2 归一化） | `aux_hf_reference.py --kind embed` |
| `hf_rerank.json` | HF `bge-reranker-v2-m3` 在 7 个 pair 长度上的 logit | `aux_hf_reference.py --kind rerank` |
| `embed_sweep.txt` | 板侧 Embedding 扫描的原始 stdout（首次运行，未封顶文本） | `run_embed.sh` |
| `embed_sweep2.txt` | 板侧 Embedding 扫描的原始 stdout（定稿，文本按网格封顶） | `run_embed.sh` |
| `rerank_sweep.txt` | 板侧 Reranker 扫描的原始 stdout | `run_rerank.sh` |
| `dyn_rerank_hang.txt` | 动态 Reranker 在板上挂死的现场（§ 见下） | 见报告 §5.3 |

## `dyn_rerank_hang.txt`：动态 Reranker 会挂死 NPU

**这是本次最重要的否定性结论。**

`bge-reranker-v2-m3` 的 `--dynamic` 8192 bmodel **加载成功**（
`cv_rerank_create` 返回有效句柄），但**第一次 `cv_rerank_forward` 就永久挂住**：

```
$ ps -o pid,stat,etime,wchan:20 -p <pid>
    PID STAT     ELAPSED WCHAN
3417501 D          01:52 bmdrv_thread_sync_api
```

进程进入 **D 状态**（不可中断睡眠），`wchan` 是 `bmdrv_thread_sync_api` ——
即卡在驱动的线程同步上，与 `BSP-NOTES.md` §「MYS-2609」记录的
「卡死 NPU 的进程处于 D 状态，无法回收，只能重启设备」同一类现场。

- `kill -TERM` **无效**（D 状态进程不响应信号），这是已知且预期的。
- 它占住 **10.7 GB** NPU 堆（`bm-smi` 的 `10763MB/26624`）。
- **没有** oops、没有内核 panic、没有重启；同板的另外 4 个既有 worker
  （embedding / reranker / ASR / OCR）不受影响，仍能正常服务 ——
  说明挂死是**该进程自己的同步等待**，不是整卡挂死。

这个 bmodel 的 `block_<i>` 图有 2 个输入（`input_states` 动态、`attention_mask`
动态），而**静态版也是 2 个输入**；差别只在 `is_dynamic` 标记。
`native/src/rerank_engine.cpp` 的 `launch()` **没有**动态发射路径
（对比 `embed_engine.cpp` 有 `launch_dyn()`），它按 `stages[0].input_shapes`
原样发射，而那组 shape 是 `max:` 形式 —— 这几乎肯定就是挂死的原因。
**但这是推断，不是实测确认**：要确认需要改 `native/` 加动态路径再测，
而任务卡禁止改产品代码，所以本轮到此为止，把它作为「方案 A 对 Reranker
不可用」的实测结论记录，理由见报告 §5.3。

## `diag_ab.json` + `diag_embed_ref.py`：HF 与 bmodel 为什么对不上

`diag_ab.json` 是同一组 token id 在两侧的向量：
`ids` 来自服务的 `tokenizer.json`（带 `<|endoftext|>` 模板），
`vec_plain` 是 HF 对**不带模板**的 ids 的输出，`vec_tmpl` 是对**带模板** ids 的输出。
`diag_embed_ref.py` 是产生它的诊断脚本，量化了「尾部多一个 token」对这个
last-token-pooling 模型的影响：追加 151643 → 余弦 0.9960，
追加 151645 → 0.7093。

**用它来核对的关键数字**：把同一组 `ids` 同时喂给 bmodel（板上
`cv_embed_forward`）和 HF，余弦 = **0.9998796**。
而如果两侧各自用**自己的分词器**处理同一段文本，余弦只有 **0.73–0.90**。
两者相差的那个 1 token 就是全部原因，不是精度问题。

详见 [`docs/research/aux-dynamic-seq.md`](../../../docs/research/aux-dynamic-seq.md) §3.3。
