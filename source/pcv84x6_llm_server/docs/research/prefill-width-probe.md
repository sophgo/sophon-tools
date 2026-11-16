# 预填充非 64 对齐宽度探针结果（10.42.0.242，Qwen3.6-35B-A3B 32k）

| 项目 | 内容 |
|---|---|
| **历史结论** | 「长历史 + 极小动态宽度」（2048 历史 + 5 行 extend）会卡死 TPU，硬件修复后仍复现；其余非 64 对齐宽度安全但输出会分叉；放宽对齐能把短 prompt 首字省 49% |
| **当前约束** | 动态预填充只跑 **64 的倍数行**，尾部与不足 64 行的整块走 decode 回放，见 `docs/DESIGN.md` §3.3；**卡死这一格不要在本机重试** |
| **本篇保留** | 宽度反推表、卡死现场的完整 dmesg、TTFT 收益——第 2 阶段（对齐 16）的决策依据 |

MYS-2394。目标：用受控实验回答三件事——非 64 对齐的动态预填充宽度**会不会卡死 TPU**、输出与当前
`LLM_PREFILL_ALIGN=64` 默认**是否一致**、首字时间（TTFT）**能省多少**。只做探针与数据，未改引擎
默认策略，未发版。

**结论先行**

1. **卡死仍然存在，但只在「有历史 + 宽度极小」这一格**：2048-token 会话上用 **5 行动态宽度 extend**
   会让 TPU 卡死（`bmdrv_thread_sync_api` 等待 120 s 超时 → `bdc_reg_read` 同步外部中止 oops →
   `reboot is needed`）。这与 v0.4 之前的旧结论一致，**硬件修复后仍然复现**。
2. **其余 16 条全部通过**（rc=0）：fresh 预填充 63 / 200 / 1000 行在 align=16、1 下都正常；有历史的
   extend 在 17 / 33 / 48 行、history 1000 与 2048 下都正常。所以「非 64 对齐」本身不是问题，
   **宽度下限**才是。
3. **输出与 64 基线不一致，但不是「算错」**：只要对齐值改变了「哪些行走精确的 decode 回放」，
   token 就会分叉；回放集合不变时（fresh 200：16 与 64 都取 192）两者 16 个 token **完全相同**。
   同一宽度下结果可复现，align=16 与 align=1 在宽度相同时逐 token 全等。
4. **TTFT 收益**：63-token 首轮 1.49 s → 0.76 s（**省 0.74 s，-49%**，与 TPU-LLM 的 0.77 s 持平）；
   有历史的 48-token 追问 1.13 s → 0.71 s（**省 0.42 s，-37%**）。长 prompt 收益递减（1000-token
   首轮 -13%，200-token -4%）。

> 本轮因第 11 行复现卡死而**按任务卡维护纪律停止**：不重试、不重启设备。样机 NPU 当前处于 wedged
> 状态，需要重启才能恢复（见「样机状态」）。

## 环境

| 项 | 值 |
|---|---|
| 设备 | `10.42.0.242`，CV84X6 SOC，`linaro` |
| 内核 / 驱动 | `5.10.4-246eee117-sophon-custom-00607-g246eee117e03`，libsophon 0.4.15 |
| 安装包 | `/opt/sophgo/cv84x6_llm_server`，VERSION `0.6.4`，COMMIT `6bce71e85a40ea6a8a6f456fe8f96f30d2bf2214` |
| 引擎库 | `lib/libcv84x6_llm.so`，md5 `073d0e86333988b155a019d93a08bb83` |
| 模型 | `/data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel`，md5 `1178646a93a3ec0786e9de77ba57d6dd` |
| 引擎自报 | `layers=40 seq=32768 max_input=2048 hidden=2048 kv_bytes=1024 dynamic=1 prefill_mask=0 lm_topk=1 greedy=0 vit=1(2304 patches) history=1` |

引擎库按任务卡要求**只读使用**，未替换安装目录任何文件；`native/` 未改动。

## 方法

`tools/prefill_width_probe.py` 直接调用引擎 C ABI（和 worker 同一条路径），一次进程只做一条测量：

- `fresh`：新会话 `prefill(prompt)`，记录该调用耗时（TTFT），再 greedy decode 16 个 token。
- `extend`：新会话 `prefill(history)` → `decode` 1 个 token（prefill 采样的那个）→ `extend(prompt)`，
  记录 extend 耗时（TTFT）→ greedy decode 16 个 token。

对齐值不通过参数传，而是**读环境变量 `LLM_PREFILL_ALIGN`**（引擎每次调用都重读），输出里打印的就是
引擎实际用的值；`LLM_ALIGN_ABOVE` 保持未设置（探针检测到非 0 会直接拒绝运行）。每条进程内
`signal.alarm(300)` 硬超时（加载 20 GB 模型后重新计时，避免加载吃掉发射预算），外层再套
`timeout 360`。

prompt 全部是**真实文本经发布包自带分词器 + chat template 编码出来的 id**（任务卡硬约束，禁止合成
id 序列）。`tools/gen_prefill_probe_prompts.py` 用安装包的 `libcv84x6_llm.so::llm_tokenizer_encode`
编码 `corpus.txt` 里的真实英文散文，并通过 `app/api/tool_calls.py::render_messages`（生产同一条
chat template 路径）包装，再搜索语料词数使 token 数**精确等于**目标长度；生成的 id 文件连同
manifest（长度 + sha256）一起提交在 `tools/prefill_probe_prompts/`，可复现、可校验。

三种 id 文件的构造：

| 文件 | 内容 |
|---|---|
| `fresh-63` / `fresh-200` | 完整单轮 prompt，结尾是生成用的 assistant 头（`im_start` + `assistant` + 空 think 块） |
| `turn-1000` / `turn-2048` | 同形状的长 prompt，作为 extend 的 history |
| `delta-5/17/33/48` | 模板为**下一轮**追加的那段 chunk 的前 N 个 token（以 `im_end` + `im_start` + `user` 开头）；`delta-48` 是完整的一段，短的几份是它的前缀 |

`delta-48` 恰好就是一个真实追问在引擎里 `extend` 时会收到的令牌流；`delta-5` 就是验证旧卡死场景的
5 行宽度。

### 宽度是否真的生效（不只看代码，用 `LLM_TRACE=1` 数发射次数）

40 层里 FA 层用 `block_kv_<i>`、其余层用 `block_<i>`；回放走 `block_cache`（每行一次）。每 40 次
`block_cache` 发射 = 全部 40 层跑一遍，所以下表把它除以 40 便于和对齐/回放行数对照；建立 KV 之后的
FA 层才走 `block_kv`（`old > 0`），首轮一律走 `block_`。由此反推的实际宽度与任务卡的预期**逐条
吻合**，说明测的确实是目标宽度：

| 运行 | `block` | `block_kv` | `block_cache`/40 | 反推：对齐宽度 + 回放行数 |
|---|---:|---:|---:|---|
| fresh 63 align=64 | 0 | 0 | 78 | L=0，回放 63 行（+15 解码步） |
| fresh 63 align=16 | 40 | 0 | 30 | L=48，回放 15 行 |
| fresh 63 align=1 | 40 | 0 | 15 | L=63，回放 0 |
| fresh 200 align=64/16 | 40 | 0 | 23 | L=192，回放 8 行（两者相同） |
| fresh 200 align=1 | 40 | 0 | 15 | L=200，回放 0 |
| fresh 1000 align=64 | 40 | 0 | 55 | L=960，回放 40 行 |
| fresh 1000 align=16 | 40 | 0 | 23 | L=992，回放 8 行 |
| fresh 1000 align=1 | 40 | 0 | 15 | L=1000，回放 0 |
| extend h1000 +48 align=64 | 40 | 0 | 103 | extend L=0，回放 48 行（+history 回放 40 + 15 解码） |
| extend h1000 +48 align=16/1 | 70 | 10 | 23 | extend L=48（10 个 FA 层 `block_kv`），回放 0 |
| extend h2048 +48 align=64 | 40 | 0 | 63 | extend L=0，回放 48 行（history 无回放） |
| extend h2048 +48 align=16/1 | 70 | 10 | 15 | extend L=48，回放 0 |
| extend h2048 +5 align=1 | 40 | 0 | **0** | history 一次 2048 行发射后**再无任何发射** → 卡在 5 行 extend |

## 结果表

每条各跑 1 次（任务卡要求）。TTFT 只含 prefill/extend 调用本身，**不含** 20 GB 模型加载
（每次进程重新加载，约 63 s）。「一致」指 16 个 greedy token 与**同长度 ALIGN=64 基线**逐 token 全等。
同一宽度 n=1，小于约 5% 的 TTFT 差异不具意义。

### fresh（首轮预填充，无历史，FA 走 `block_<i>`）

| # | prompt | align | 实际宽度 | TTFT (s) | rc | 16 token 与 64 基线 | 首个分叉位 | dmesg |
|---:|---:|---:|---:|---:|---:|---|---:|---|
| 1 | 63 | 64 | L=0 / 回放 63 | **1.4939** | 0 | 基线 | – | 干净 |
| 2 | 63 | 16 | L=48 + 回放 15 | 1.0382 | 0 | 不一致 | 3 | 干净 |
| 3 | 63 | 1 | L=63 | **0.7580** | 0 | 不一致 | 3 | 干净 |
| 4 | 200 | 64 | L=192 + 回放 8 | 1.5019 | 0 | 基线 | – | 干净 |
| 4 | 200 | 16 | L=192 + 回放 8 | 1.4980 | 0 | **完全一致** | – | 干净 |
| 4 | 200 | 1 | L=200 | 1.4365 | 0 | 不一致 | 12 | 干净 |
| 5 | 1000 | 64 | L=960 + 回放 40 | 5.4407 | 0 | 基线 | – | 干净 |
| 5 | 1000 | 16 | L=992 + 回放 8 | 4.8862 | 0 | 不一致 | 0 | 干净 |
| 5 | 1000 | 1 | L=1000 | 4.7421 | 0 | 不一致 | 0 | 干净 |

### extend（有历史，FA 走 `block_kv_<i>`）

| # | history | 追加 | align | 实际宽度 | TTFT (s) | rc | 16 token 与 64 基线 | 首个分叉位 | dmesg |
|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| 6 | 1000 | 48 | 64 | L=0 / 回放 48 | 1.1251 | 0 | 基线 | – | 干净 |
| 7 | 1000 | 48 | 16 | L=48 | 0.7067 | 0 | 不一致 | 0 | 干净 |
| 8 | 1000 | 48 | 1 | L=48 | 0.7062 | 0 | 不一致（与 #7 **全等**） | 0 | 干净 |
| 9 | 1000 | 33 | 64 | L=0 / 回放 33 | 0.7775 | 0 | 基线（补跑） | – | 干净 |
| 9 | 1000 | 33 | 1 | L=33 | 0.6478 | 0 | 不一致 | 1 | 干净 |
| 9 | 1000 | 17 | 64 | L=0 / 回放 17 | 0.4045 | 0 | 基线（补跑） | – | 干净 |
| 9 | 1000 | 17 | 1 | L=17 | 0.5432 | 0 | 不一致 | 4 | 干净 |
| 10 | 2048 | 48 | 64 | L=0 / 回放 48 | 1.1655 | 0 | 基线（补跑） | – | 干净 |
| 10 | 2048 | 48 | 16 | L=48 | 0.7514 | 0 | 不一致 | 0 | 干净 |
| 10 | 2048 | 48 | 1 | L=48 | 0.7517 | 0 | 不一致（与 align=16 **全等**） | 0 | 干净 |
| 11 | 2048 | 5 | 64 | L=0 / 回放 5 | 0.1311 | 0 | 基线（补跑） | – | 干净 |
| 11 | 2048 | 5 | 1 | **L=5** | **无** | **挂起** | – | – | **oops** |

补跑说明：任务卡第 9/10/11 行的验收要求「与同长度的 ALIGN=64 基线全等」，表内原矩阵未列基线，
故每个新长度先补跑一条 64 基线，顺序仍是「先基线、后变对齐」，一次只改一个变量。

TTFT 对比（同一行内）：

- fresh 63：1.49 → 1.04（-30%）→ **0.76（-49%）**
- fresh 200：1.50 → 1.50（不变，回放集合未变）→ 1.44（-4%）
- fresh 1000：5.44 → 4.89（-10%）→ 4.74（-13%）
- extend h1000 +48：1.13 → **0.71（-37%）**
- extend h2048 +48：1.17 → **0.75（-36%）**
- extend h1000 +17：0.40 → 0.54（**变慢**，见下）

唯一变慢的是 17 行：align=64 时 17 行走回放只花 0.40 s，反而比一次 17 行动态 `block_kv` 发射
（含 2048 token 的历史 KV 拷贝）的 0.54 s 更快。即**极短宽度下动态图并不划算**，这条对第 2 阶段的
规则同样有参考价值（n=1，量级差异 0.14 s 超过噪声）。

## 第 11 行失败的完整证据

命令：

```
cd /data/tmp/prefill-probe
timeout 360 env LLM_PREFILL_ALIGN=1 LLM_TRACE=1 python3 tools/prefill_width_probe.py \
  --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
  --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
  --case extend --history tools/prefill_probe_prompts/turn-2048.txt \
  --prompt tools/prefill_probe_prompts/delta-5.txt --decode 16 --dev 0
```

`LLM_TRACE` 显示 history（2048 行，一次发射）正常跑完，之后**再无任何发射**——即卡在紧接着的 5 行
`extend` 发射上（prefill 之后的第一个 `decode()` 只是把 prefill 采样的 token 交回，不发射图）：

```
[engine] layers=40 seq=32768 max_input=2048 hidden=2048 kv_bytes=1024 dynamic=1 ... history=1
load 63.13s max_input=2048
[launch] embedding 0.9 ms @0.000
[launch] block_0 239.9 ms @0.240
...
[launch] block_39 203.2 ms @9.420
[launch] lm_head 10.1 ms @9.431
[launch] embedding 0.7 ms @9.432      <-- 之后挂起，无输出，rc 未产生
```

内核日志（120 s 驱动超时后）：

```
bmtpu: bmdrv_thread_sync_api:1471: bm-sophon0 bmdrv_thread_sync_api, wait api timeout, wait 120000ms, core_id=0
Internal error: synchronous external abort: 96000010 [#1] SMP
CPU: 0 PID: 1406219 Comm: python3 Tainted: GF     O
pc : bdc_reg_read+0x10/0x30 [bmtpu]
lr : bmdrv_thread_sync_api+0x2d8/0x4e4 [bmtpu]
Call trace:
 bdc_reg_read+0x10/0x30 [bmtpu]
 bm_ioctl+0xc84/0x1c5c [bmtpu]
 bmdev_ioctl+0x54/0xd0 [bmtpu]
 __arm64_sys_ioctl+0x46c/0xbd0
...
Fixing recursive fault but reboot is needed!
```

之后又出现一次同样的 `bmdrv_thread_sync_api ... wait api timeout`（另一个 ioctl 读寄存器时），
`python3` 进程停在 `D` 状态。按任务卡纪律**未重试、未 `kill -9`、未重启设备**。

与旧结论的关系：旧报告触发条件是「**恢复** 2048-token 状态后用 2 行、5 行动态宽度 extend」。本次没有
用快照恢复，而是同进程顺次 prefill 出 2048 token 的状态，**同样在 5 行上挂起**——说明触发条件不是
「快照恢复」这个动作，而是「长历史 + 极小动态宽度」这个组合本身，硬件修复后依然成立。

## 结论（按证据分三档）

### fresh（首轮预填充）

- **安全且一致**：`align=16, prompt=200`（对齐后仍是 192 行、回放 8 行，与 64 基线逐 token 全等）。
- **安全但输出有差异**：`align=16/1` 对 63、200、1000 都 rc=0、无 oops；分叉点分别在 token 3 / 12 / 0。
- **卡死/失败**：无。

### extend（有历史）

- **安全且一致**：无（只要对齐值改变了回放集合，输出就会变）。
- **安全但输出有差异**：history 1000 × 追加 {17, 33, 48}、history 2048 × 追加 48，在 `align=16/1`
  下全部 rc=0；align=16 与 align=1 在宽度相同时（L=48）**逐 token 全等**，说明差异来自「走哪条图」，
  不是随机性。分叉点见上表。
- **卡死/失败**：history 2048 × 追加 **5**，`align=1`（真实宽度 5 行）→ TPU 卡死，只能重启。

### 关于「输出不一致」的性质

现有的 `LLM_PREFILL_ALIGN=64` 规则把不足 64 行的尾部逐行走 **decode 图**，而 decode 图的 MoE 是精确
路径（`tools/precision/README.md`、MYS-2293：预填充图的 MoE 在 CV84X6 上是近似，第 0 层余弦 0.75 vs
0.9999）。所以降低对齐值 = 把原本走精确回放的那些行改成走近似预填充图，**输出变化是这条路径本身
的数值特性，不是新引入的错误**：

- 回放集合不变 → 输出全等（fresh 200 的 16 与 64）。
- 回放集合变化 → 输出分叉，且分叉在第一个采样 token 就可能出现（fresh 1000、extend 全部）。
- 同一宽度、不同对齐值（16 vs 1，都落在 L=48）→ **逐 token 全等**，可复现。

也就是说第 2 阶段若要放宽 64 规则，**必须同时决定「短 prompt 还想不想保留精确尾部」**：现在的 63-token
prompt 是 100% 走精确 decode 路径的，放宽后会变成走近似预填充图。这两件事（安全下限、精度取舍）是
独立的两个决策，本报告只提供证据。

## 样机状态（未恢复到验收要求）

按任务卡，失败后立即停止。当前状态：

| 项 | 状态 |
|---|---|
| `cv84x6-llm` 服务 | **inactive**（实验前已按纪律 `systemctl stop` 等其自行退出，此后未再启动） |
| `healthz` | 无响应（服务未启动） |
| NPU | **wedged**：`bmtpu` 已 oops，`bm-smi` 在 `D` 状态阻塞，`python3`（探针进程 1406219）同样卡在 `D` |
| `/data/tmp/prefill-probe/` | **保留**（失败证据：`logs/*.json`、`logs/*.trace`，已同步到本报告与 PR） |

未做、也不应在本任务里做的：重启设备（属服务器运维范围），`kill -9` 卡住的进程（任务卡明令禁止，
且 D 状态进程无法被回收）。

**恢复需要一次重启**。重启后建议依次：`systemctl start cv84x6-llm` → `curl -s
http://127.0.0.1:8000/healthz` 应为 `{"ok":true,"version":"0.6.4","loaded":0}`（不加载模型）→
删除 `/data/tmp/prefill-probe/`。第 11 行 `align=1` 这一格**不建议在本机再试**。

## 与任务卡的偏差

1. 补跑了 3 条 `ALIGN=64` 基线（第 9 行的 33/17、第 10/11 行的 2048 history +48/+5）。原因：验收要求
   「与同长度的 ALIGN=64 基线全等」，原矩阵未列这些长度。仍是一次只改一个变量、先基线后变对齐。
2. 第 11 行 `align=1` 无结果：卡死，按纪律停止（这是本任务的有效结论，不是缺数据）。
3. 样机未按「全部结束后」的要求恢复（服务未启动、临时目录未删、NPU 需重启）：因实验在最后一条失败，
   任务卡规定此时停止并把状态置 blocked。
4. `signal.alarm(300)` 在模型加载完成后**重新计时一次**：单次 20 GB 加载约 63 s，若不重算，加载慢时
   会误判为发射超时。
5. 未改动 `native/`、`app/`、`web/`、默认配置，未修改 `/opt/sophgo/cv84x6_llm_server` 安装目录，
   未访问 2282。

## 复现

```bash
# 1) 生成 / 校验 prompt id 文件（板上：需要发布包的 lib + tokenizer）
python3 tools/gen_prefill_probe_prompts.py \
    --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --tokenizer /opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json
python3 tools/gen_prefill_probe_prompts.py --verify        # 任意机器，不需要 NPU

# 2) 单条测量（每进程一条；先 64 基线，再改一个变量）
LLM_PREFILL_ALIGN=1 LLM_TRACE=1 timeout 360 python3 tools/prefill_width_probe.py \
    --lib  /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
    --case fresh --prompt tools/prefill_probe_prompts/fresh-63.txt --decode 16

LLM_PREFILL_ALIGN=16 LLM_TRACE=1 timeout 360 python3 tools/prefill_width_probe.py \
    --lib  /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
    --case extend --history tools/prefill_probe_prompts/turn-1000.txt \
    --prompt tools/prefill_probe_prompts/delta-48.txt --decode 16
```

每跑一条都要 `dmesg | tail`；出现超时 / oops / rc≠0 / 卡住就停，不要重试。
