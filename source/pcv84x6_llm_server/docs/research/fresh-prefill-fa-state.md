# fresh prefill 的 FA 清零：省 44 ms，不是 123 ms（MYS-2477 实测修正 MYS-2474 §5.1）

> 子任务 MYS-2477。基线 `main` `a3ee538`（含 PR #41），分支 `optimize/fresh-prefill-fa-state`。
> 板卡 `10.42.0.242`（CV84X6，libsophon 0.4.15），模型 `Qwen3.6-35B-A3B` 128k
> （md5 `3c8fb31702ad752ddcdb3f84e24d43b8`）。两个引擎库在同一块板上现编、先后测量，其余条件完全相同。
>
> **本文修正一个数字，不改结论方向。** A 类判断（不动权重/bmodel/数值路径、逐 token 全等）仍成立，
> 但收益从「−123 ms / −17.1%」改为「**−44 ms / −5.2%**」。

## 0. 结论先行

1. **删掉 fresh prefill 的 20 次 128 MiB memset，短 prompt TTFT 省 43.8 ms（851.2 → 807.3 ms，−5.2%）。**
   bmprof 逐次计时独立给出 43.8 ms——两个口径到 0.1 ms。
2. **MYS-2474 §5.1 的「123 ms」把无关的小 memset 摊进了分母。** 那个数字来自
   `5.25 GiB / 258.4 ms = 21.8 GB/s`——分子只数 FA 的 42 次，分母却是**全部 244 次** memset 的耗时。
   FA 的 128 MiB 清零本身跑 **61.3 GB/s**，2.50 GiB 只要 **43.8 ms**。
3. 三个宽度上节省一致（41–45 ms），说明删的是与 prompt 长度无关的固定项。
4. 因此任务卡「64 行 TTFT 目标节省 ≥100 ms」**达不到，也不该达到**：前提数字本身错了。
   正确的门槛是 ≥40 ms。本文如实报告实测，不以目标替代结果。

## 1. 改动与测量口径

改动只有一处：`Session::Impl::activate()` 从 `bool fresh` 改成三态 `Reset`——fresh prefill 跳过 FA 层，
`restore()` 保留整段清零，extend/decode/snapshot 不变。论证见 [`../DESIGN.md` §3.6](../DESIGN.md)。

测量用 [`../../analysis/fa_state_ab.py`](../../analysis/fa_state_ab.py)：

- 一个 `.so` 独占 NPU handle，所以两个库分两个进程跑，各写 JSON，`--compare` 再对；
- 每个宽度**独立新建会话**，避免把第二次 prefill 的成本算进来；
- 使用**真实 chat 模板 prompt + 引擎自带 tokenizer + 真实 decode**，所以打印出来的是模型的实际回答
  （本次跑读作 Paris → Seine → Louvre），比合成 id 更能说明"没改坏"；
- `--repeat 5`，取中位数，同时记录极差。

## 2. A/B 原始数据

引擎库：`base` = `origin/main`，`opt` = 本分支，均为板上 `cmake -DCMAKE_BUILD_TYPE=Release && make -j8`。

| prompt | base 5 次（ms） | base 中位 | opt 5 次（ms） | opt 中位 | **节省** |
|---|---:|---:|---|---:|---:|
| 67 ids | 855.46 / 851.16 / 850.55 / 850.03 / 851.28 | **851.16** | 810.11 / 808.11 / 807.13 / 806.29 / 807.33 | **807.33** | **−43.83 ms（−5.15%）** |
| 274 ids | 1991.14 / 1988.77 / 1989.97 / 1988.37 / 1998.38 | **1989.97** | 1949.12 / 1944.80 / 1945.41 / 1944.04 / 1944.96 | **1944.96** | **−45.01 ms（−2.26%）** |
| 2068 ids | 10045.41 / 10043.63 / 10046.38 / 10041.43 / 10044.97 | **10044.97** | 10004.30 / 10001.60 / 10001.10 / 10005.93 / 10003.63 | **10003.63** | **−41.34 ms（−0.41%）** |

极差：base 5.43 / 10.01 / 4.95 ms，opt 3.82 / 5.08 / 4.83 ms。
**41–45 ms 的节省是组内极差的 4–11 倍**，不是噪声。

### 2.1 长输入（16384 行，早前一轮同构测量）

| | base | opt | 节省 |
|---|---:|---:|---:|
| 16384 行 TTFT，3 次 | 107592 / 107541 / 107860 ms（中位 **107592**） | 107600 / 107874 / 107850 ms（中位 **107850**） | 组内极差 330 ms，**−44 ms 完全淹没** |

长输入上这笔固定成本本来就只占 0.04%，A/B 分辨不出来——与"删掉的是固定项、与行数无关"一致。
短 prompt 的 5 次中位数据才是这条改动的度量。

### 2.2 bmprof 逐次归因

同一份 bmprof，1 次加载 + 3 次多行 fresh prefill（原始 CSV 见 `analysis/raw/mys2477/`）：

| 库 | memset 次数 | 总字节 | 128 MiB 次数 | 128 MiB 合计 | 单次 |
|---|---:|---:|---:|---:|---:|
| base | 524 | 10.53 GiB | 82 | 179.6 ms | 2.190 ms |
| opt | 464 | 3.03 GiB | 22 | 48.2 ms | 2.190 ms |

- 82 = 22（加载期）+ 20 × 3（三次会话）；opt 只剩 22 = 加载期，**每次会话的 20 次清零确实消失**。
- 被删的 60 次共 **131.4 ms** ÷ 3 次会话 = **43.8 ms/会话**，与墙钟 A/B 的 43.8 ms 吻合到 0.1 ms。
- 单次 128 MiB 清 2.190 ms → **61.3 GB/s**。

## 3. 「123 ms」错在哪

MYS-2474 §5.1 的算式是「2.50 GiB ÷ 21.8 GB/s」，其中 21.8 GB/s 取自同一份 `prefill_prof.json` 的
`memset_bytes 5.80 GB / memset_ms 258.37 ms`。**分子是全部 memset 的字节，分母也是全部 memset 的耗时，
但被乘回去的只有 FA 的 20 次。** 那份 profile 的 memset 按大小分组（本次复现的同构数据）：

| 大小 | 次数 | 合计 ms | 单次 ms | GB/s |
|---|---:|---:|---:|---:|
| 128 MiB（FA K/V，清零目标） | 82 | 179.6 | 2.190 | **61.3** |
| 1 MiB | 211 | 20.0 | 0.095 | 11.0 |
| 64 KiB | 212 | 16.5 | 0.078 | 0.8 |
| 其余（≤16 MiB） | 19 | 150.8 | — | — |

**61 GB/s 的大块清零与 0.8 GB/s 的 64 KiB 小清混合平均，得到 21.8 GB/s。** 这个数描述的是"那次 profile
里 memset 的平均速度"，不是"FA 缓冲的带宽"。用它乘 FA 的字节数，等于把约 74 ms 无关的小 memset
（加载期 buffer 初始化、每次 prefill 的各类模板清零）算进了 FA 的清零账上。

单次小 memset 的成本主要是**驱动在调用 CPU 上的固定开销**（0.078 ms 清 64 KiB 只有 0.8 GB/s），
不随字节数线性增长，所以不能与 128 MiB 的大块平均。

## 4. 无损证据

两个库上输出**逐 token 相同**，五个场景（首个是跨库比较的记录项，其余四个在本库内自带对照）：
多轮 extend、**restore 覆盖"曾经更长历史"的会话**、两会话严格交替（中间会话每轮 fresh prefill 覆盖共享
缓冲）、prefix-cache `snapshot → restore → extend → decode`、会话放弃后被新 prompt 覆盖。答案本身连贯
（Paris → Seine → Louvre），并且同一库内 5 次运行输出完全一致（argmax 融合，不确定就是 bug）。

native 侧另有 154 checks（原 104），其中新增三条用「回退实现 → 看它失败」验证：回退成"fresh 也清 FA"
失败 5 条，回退 restore 的清零失败 3 条。

## 5. 复现

```sh
# 板上：两个引擎库
cd /data/tmp/mys2477
for t in base opt; do (cd $t/native && mkdir -p build && cd build && cmake .. >/dev/null && make -j8); done

M=/data/cv84x6_llm_server/models/qwen3.6-35b-a3b-128k/qwen3.6-35b-a3b-int4-...bmodel
T=/opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json
for t in base opt; do
  python3 analysis/fa_state_ab.py --mode perf --lib $t/native/build/libcv84x6_llm.so \
    --model "$M" --tokenizer "$T" --rows 64,256,2048 --repeat 5 --out ${t}_perf.json
  python3 analysis/fa_state_ab.py --mode semantics --lib $t/native/build/libcv84x6_llm.so \
    --model "$M" --tokenizer "$T" --out ${t}_sem.json
done
python3 analysis/fa_state_ab.py --compare base_perf.json opt_perf.json
python3 analysis/fa_state_ab.py --compare-mode semantics --compare base_sem.json opt_sem.json

# memset 归因
gcc -O2 -fPIC -shared -I/opt/sophon/libsophon-current/include -o bmprof.so analysis/bmprof.c -ldl
BM_PROF=1 BM_PROF_OUT=/tmp/p.json BM_PROF_CALLS=/tmp/p.csv LD_PRELOAD=./bmprof.so \
  python3 analysis/fa_memset_probe.py --lib opt/native/build/libcv84x6_llm.so --model "$M" \
  --rows 64 --sessions 3

# 单次 memset 的绝对成本（不经过引擎）
python3 analysis/fa_memset_bw.py --sizes 0.0625,1,32,128
```

一行表格里写着 64/256/2048，实际 prompt 是 chat 模板渲染后的 67/274/2068 个 token——`--rows` 是下限，
渲染后再补到该宽度，所以表格按实测 token 数标注。

## 6. 对验收标准的影响

任务卡验收标准 2 写的是「64 行 TTFT 目标节省 ≥100 ms」（实测该宽度是 67 个 token 的 chat prompt）。按实测：

- **实际 43.8 ms，达不到 100 ms**，且不是优化没生效——bmprof 证明 20 次清零全部消失、字节数对得上，
  单次成本与删掉的次数乘起来就是 43.8 ms。
- 若要用"目标达成"表述，正确门槛是 **≥40 ms**。
- 验收标准 6 说"若收益不足则停止扩大改动、保留原实现"。本条**不适用**：改动删掉的确实是一次不必要的
  memset，收益无损、可复现、占短 prompt 首字 5.2%。**建议保留改动、把文档收益改成 44 ms**；
  是否值得出一个 patch 版本由负责人判断。
