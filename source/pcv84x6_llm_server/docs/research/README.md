# 研究专题：历史评测报告

这里是实测驱动的决策依据，按专题保留原始数据与复现方式。**结论已落到
[`../DESIGN.md`](../DESIGN.md) 的当前契约里**；这些文档保留的是「当时测了什么、数据是什么、
为什么这样决定」，不是待办清单。

阅读顺序建议：先看每篇开头的「结论先行」，需要核对时再往下看数据表与复现命令。

| 文档 | 子任务 | 结论一句话 |
|---|---|---|
| [`qwen36-lossless-optimization.md`](qwen36-lossless-optimization.md) | MYS-2474 | **decode 已到访存下界（91–92%）**；缺口在 prefill，**76% 是 O(N²) history attention**；短 prompt 首字可省 123 ms |
| [`decode-optimization.md`](decode-optimization.md) | MYS-2457 | 一个 token 是「固定 27 ms + 10 × FA 层」；并发靠时间片，`lm_head` 是 30% 且只能靠改 bmodel |
| [`bmrt-queue-depth.md`](bmrt-queue-depth.md) | MYS-2469 | 队列深度没有运行时开关；即使能加深，收益上限约 1 ms/token（3%），no-go |
| [`prefill-width-probe.md`](prefill-width-probe.md) | MYS-2394 | 「长历史 + 极小动态宽度」（5 行）会卡死 TPU；其余宽度安全但输出会分叉 |
| [`prefill-ab-eval.md`](prefill-ab-eval.md) | MYS-2396 | 对齐降到 16 让 40 条正确率掉到 35/40，TTFT 倒是稳定降 36% |
| [`prefill-exact-tail-eval.md`](prefill-exact-tail-eval.md) | MYS-2403 | 64 对齐下 `n%64 ≤ 7` 的短 prompt 已 5/40 失败；补 16 行精确修到 39/40 |
| [`prefill-tail-align-grid.md`](prefill-tail-align-grid.md) | MYS-2405 | K × 对齐 16 组合评测首条就打死 TPU，该方向停止 |
| [`aux-dynamic-seq.md`](aux-dynamic-seq.md) | MYS-2702 | 动态 shape 只在 ≤100 token 快于 static2048；知识库切片的 400–500 token 区间 static512 快 6.8 倍；**动态图不值得引入**，多档静态图不能合并、只能按长度选档 |
| [`d7-tpu-hang.md`](d7-tpu-hang.md) | MYS-2693 | D7 偶发卡死要「同一 worker 并发 ≥2」且「NPU 几乎占满」同时成立；固件一次 launch 不应答，驱动把 core0 的问题放大成整块设备 120 s 全哑 |

## 共同的测量条件

除另有说明，所有数字都在 `10.42.0.242`（CV84X6，libsophon 0.4.15）上实测，
模型是自编译的 `Qwen3.6-35B-A3B`（32k 或 128k，每篇开头写明 md5）。
每篇的「环境」表记录了内核、安装包版本、引擎库 md5 与引擎自报参数。

## 纪律

这些实验都**只读**：不改引擎、不改 bmodel、不改服务默认值、不发版。探针一律带硬超时
（`signal.alarm` + 外层 `timeout`），每轮之后看 `dmesg`；出现超时或 oops 立即停止，不重试、
不 `kill -9`（卡死 NPU 的进程处于 D 状态，无法回收，只能重启设备）。

原始测量数据在 [`../../analysis/raw/`](../../analysis/raw/)（decode/队列）与各篇「复现」一节引用的
日志目录（预填充）。
