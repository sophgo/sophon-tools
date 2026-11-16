# WeMM 重复推理零向量：隔离诊断（MYS-2913，第 3 版）

服务：cv84x6-llm 0.6.37　模型：wemm-embedding-2b（W8BF16, seq2048, buckets, gdnmixed）
芯片：CV84X6　现场 libsophon 0.4.15

> 第 3 版按负责人二次验收的收敛要求重写：结论收敛为"服务对现场 SDK 拷贝完成顺序的
> 假设不成立"，补无模型最小复现与二进制证据，明确边界，并删除现场地址/账户/指纹。
> 第 1、2 版的错误已在文末"版本更正记录"中列明。

## 一、结论

**服务对现场 SDK 的设备拷贝完成顺序假设不成立。** `native/src/vl_embed_engine.cpp` 的
`copy()`（:92-98）在 `bm_memcpy_d2d_byte` 返回后，立刻把目标缓冲当作已就绪数据交给下一张
图；现场 `libbmlib.so.0` 的这个调用路径**不建立完成序**。当图链路存在"图输出 → 独立
buffer → 下一图输入"的连续依赖拷贝时，后一次拷贝可能在第一次拷贝落地前就读源缓冲，
从而读到尚未写入的内容——表现为整块全零，或（更常见）只是错误的数值。

这是**依赖顺序问题**，与模型、bmodel、量化、显存容量无关。

## 二、无模型最小复现（不依赖 WeMM / 图片 / 模型文件）

程序：`tools/vl_embed/copy_chain.cpp`。只用三块 2 MiB 自有分配缓冲：

```
A = 确定性非零数据（主机写入）
B = 0, C = 0
A --d2d--> B
[可选：此处设备同步 = fence 臂]
B --d2d--> C
同步，回读 C，与 A 逐字节比较
```

若第二次拷贝在第一次落地前读 B，C 得到的是 B 的清零内容，即整块全零。

**结果（64 次/臂）：**

| 臂 | 负责人实测 | 本次独立复验 |
|---|---|---|
| 无中间同步 | 1/64、3/64 整块全零 | **2/64 整块全零** |
| 两次拷贝间加同步 | 0/64、0/64 | **0/64** |

失败样本形如 `mismatched=2097152/2097152 zero_bytes=2097152 first_actual=0`，
即目标块整块保持清零状态，源数据完全没有到达。**每次 API 返回值都检查**；有 mismatch
时程序退出码为 1（"发现现象"），API 失败为 2–9（"工具失败"）——所以 `exit 0` 不能被
当作"所有数据正确"。

编译/运行：

```bash
bash tools/vl_embed/copy_chain_build.sh            # 新临时目录，-Werror
<out>/copy-chain --trials 64 --no-fence            # 预期间歇性整块全零
<out>/copy-chain --trials 64 --fence               # 预期 0 错
```

## 三、二进制证据（现场库）

现场 `libbmlib.so.0`（SHA256 `cf17bc768920c49fc906133f4213edd2906c653b90c616ee79931318b77fb620`）：

| 地址 | 内容 |
|---|---|
| `bm_memcpy_d2d_byte_with_core` 的 CV84X6 分支 `0x1954c–0x19584` | 调用 `tpu_kernel_launch_from_multi_cores`（`0x19580`）后，`0x19584` 直接返回，**无完成同步** |
| `tpu_kernel_launch_from_multi_cores` `0x1d320–0x1d41c` | 只提交任务，不做额外同步 |

因此"`bm_memcpy_d2d_byte` 返回时数据已在目的缓冲"这一假设，在现场库上**不成立**。

## 四、与服务故障的对应

WeMM 路径每层都有"图输出 → 独立 `hidden` → 下一图输入"的依赖拷贝，`copy()` 返回后即
继续使用结果。实测（同一输入重复、每 trial 独立进程、trace 关闭）：

| 条件 | 结果 |
|---|---|
| 逐次拷贝后同步 | 6/6 逐位一致，摘要均为 `eaa8e9c5de63dea3` |
| 无等待 | 首个 zero 后连续保护性拒绝 |
| 仅在每次图执行前同步 | 3 个不同结果后 zero，再 2 次拒绝 |

**这解释了此前"launch 前同步仍失败"的反例**：末尾或执行前的同步无法恢复**前一次拷贝
已经读错**的数据。另外，主机上传前同步、最终回读前同步这两种新对照同样失败，证据保留；
**不宣称这些对照已修复任何问题**。

负责人从干净源码重建的诊断库 SHA256 与本侧交付一致。

## 五、边界（明确未完成）

- **SDK / 固件内部的调度原因未定论。** 本节只证明"该拷贝路径不建立完成序"，不解释
  SDK 为何如此调度。
- **未完成修复后的参考数值与性能验证。** 没有任何"已修复"的结论。
- 不能用固定 sleep 作为修复，也不移除引擎的 fault 保护。
- 现场 `driver/bm_api.c:1438` 附近把 CV84X6 的 `core_id` 统一映射为 0，因此
  **不能宣称"core0 同步漏了另外 3 核"**——该说法不成立。
- 本地 SDK 仅用于核对：libsophon commit `5b8db401a53e1941fa154743ead24d54935243a6`；
  历史 `9579e22e` 的 `bmlib_memory.cpp` CV84X6 分支在 `multi_cores` 后**有**
  `bm_sync_api_from_core`，与现场二进制不同。**不能因为同为 0.4.15 就假设实现相同。**
  该 SDK 与内部路径不进入本报告结论，也不随本 PR 分发。

## 六、诊断工具与失败语义

工具本身会失败，且失败必须可见——否则损坏的是证据而不是程序：

- `MYS-2913-build-diag.sh` / `run_from_clean.sh` / `copy_chain_build.sh` **不删除调用者
  目录**：工作目录必须不存在，否则拒绝并退出非零；省略时用 `mktemp` 新建。
- 克隆 / 打补丁 / 编译 / 子进程 / 汇总任一步失败都使整体非零退出，不会留下"假成功"。
- `repeat_compare.py` 的错误分类：`ok` / `zero` / `nonfinite` / `refused` /
  `input_error` / **`other_error`**。未知错误归 `other_error`，其"是否执行了 forward"
  记为**未知**，不再默认判成 input_error 并断言未执行。
- `--trials > 1` 逐 trial **独立子进程**（已 fault 的进程内重建 handle 会
  `bmodel loading failed`，同进程多 trial 不独立）。
- `aggregate.py` 对缺失文件、损坏 JSON、`load_failed` 显式报错并非零退出。
- 无板卡测试 `test_diag_tools.py`（12 项）：哨兵目录不被改动、下游失败非零、
  分类口径、脚本/Python 语法。

**关于 trace：** 出厂库与诊断库都按 `atoi` 判断 `CV_VLE_TRACE`（patch 已改为
`getenv && atoi(...) != 0`），`=0` 为关闭。诊断运行一律 `env -u CV_VLE_TRACE`，
因为 trace 每层回读会串行化设备、掩盖待测竞态。

## 七、复现与验收

```bash
# 无板卡：工具安全与失败传播
python3 tools/vl_embed/test_diag_tools.py -v          # 12 passed

# 板端：诊断库构建（新临时目录，-Werror，0 警告）
bash tools/vl_embed/MYS-2913-build-diag.sh <package-root>

# 板端：无模型 A→B→C 两臂
bash tools/vl_embed/copy_chain_build.sh
<out>/copy-chain --trials 64 --no-fence
<out>/copy-chain --trials 64 --fence
```

## 八、版本更正记录

- 第 1 版把 fault 后的保护性拒绝计为新的零向量（引擎 `:281` 直接拒绝，未执行 forward）。
- 第 1 版称"旧测试全是单次调用"——实测为假：`service_check.py:150-152` 有逐位相等检查。
- 第 1 版把"d2d 异步"写成已证实根因——当时只有头文件间接依据，现由二进制证据支持
  其**完成序缺失**，但 SDK 内部原因仍未定。
- 第 2 版表格中"18/18"为**单轮**数字（3 trial × 6 次），两轮合计应为 36 次；
  该表述已在本版更正。
