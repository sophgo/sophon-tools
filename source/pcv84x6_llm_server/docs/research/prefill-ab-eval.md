# 预填充对齐 64 vs 16：回答正确率 A/B 与长历史边界补测（10.42.0.242，Qwen3.6-35B-A3B 32k）

| 项目 | 内容 |
|---|---|
| **历史结论** | 对齐从 64 降到 16 让 40 条正确率掉到 **35/40**（失败形态是不作答/拒答，确定性可复现），TTFT 中位数降 36% |
| **当前约束** | **否决 16 对齐**，预填充头保持 64，见 `docs/DESIGN.md` §3.3。正确率优先于首字时间 |
| **本篇保留** | 逐条对比、5 条差异用例原文、长历史边界补测——证明「输出变化」确实是「变差」 |

MYS-2396，接 MYS-2394（`prefill-width-probe.md`）。第 1 阶段测出「降低对齐值能省首字时间，但输出会变」。
本阶段回答的是决策真正依赖的那个问题：**输出变化是否等于回答变差**；并补测更深历史下 16 行 / 32 行动态
宽度是否安全。本阶段**不改引擎、不发版**，引擎默认规则仍是 `LLM_PREFILL_ALIGN=64`。

**结论先行**

1. **正确率确实下降：40 条从 40/40 掉到 35/40（-5 条，-12.5 个百分点）。** 下降全部落在「参考答案需要
   生成出来」的用例上，没有一条是「答案算错」，而是模型改走别的行为：
   - **a05**（短问答）：align=16 下模型不再直接给 `366`，而是把 `<think>` 块当正文写起「thinking
     process」分析，64 个 token 预算全部耗在推理上，答案没写出来。
   - **b10 / c02 / c06 / c08**（文中抽取 / 多轮追问）：align=16 下模型第一个 token 就是 `<|im_end|>`，
     **整轮拒答**（0 个 token）。
2. **下降是确定性的、可复现的**：把这 5 条单独重跑，align=16 仍然 0/5、align=64 仍然 5/5，逐 token
   一致（引擎 `lm_head` 融合 argmax，同一输入必然同一输出）。所以这不是采样噪声，是路径差异。
3. **首字时间收益是稳定的**：总体 TTFT 中位数 **1.326 → 0.847 s（-36%）**；分类看 A 1.280→0.802
   （-37%）、B 2.715→1.986（-27%）、C 0.800→0.644（-20%）。40 条里候选规则无一条变慢。
4. **第 2 部分全部安全**：16 / 32 行动态宽度在 history 2048 与 8192 下都通过（rc=0、无 oops、
   `dmesg` 无新条目），fresh 16 行也通过。**第 1 阶段「长历史 + 极小宽度」卡死的结论在 16 行以上不成立**，
   5 行以下仍是禁区（第 1 阶段已实测卡死，本阶段按卡未再试）。
5. **16 行动态发射是负收益**：同长度对比 align=64 基线，16 行反而慢 **+30% ~ +59%**（h2048+16
   0.396→0.558、h8192+16 0.479→0.762、fresh16 0.403→0.523），32 行才快（-8% ~ -14%）。
   候选规则的「至少 16 行」在安全性上够用，但在收益上取低了，**32 行才是既安全又划算的最小宽度**。
6. **建议**：不要把默认规则直接改成 16。若仍想要这部分首字收益，需要先解决「模型偶尔整轮拒答 / 把推理
   写进正文」这个问题（见「结论与建议」），或退到折中方案（例如仅对 ≥ 某长度的 prompt 放宽、或保留
   小 prompt 的精确尾部）。

## 环境

| 项 | 值 |
|---|---|
| 设备 | `10.42.0.242`，CV84X6 SOC，`linaro` |
| 内核 / 驱动 | `5.10.4-246eee117-sophon-custom-00607-g246eee117e03`，libsophon 0.4.15 |
| 安装包 | `/opt/sophgo/cv84x6_llm_server`，VERSION `0.6.4`，COMMIT `6bce71e85a40ea6a8a6f456fe8f96f30d2bf2214` |
| 引擎库 | `lib/libcv84x6_llm.so`，md5 `073d0e86333988b155a019d93a08bb83`（只读使用，未替换） |
| 模型 | `/data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel`，md5 `1178646a93a3ec0786e9de77ba57d6dd` |
| 引擎自报 | `layers=40 seq=32768 max_input=2048 hidden=2048 kv_bytes=1024 dynamic=1 prefill_mask=0 lm_topk=1 greedy=0 vit=1(2304 patches) history=1` |
| 分词器 | `/opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json`，vocab 248070 |

## 方法

### 用例集（40 条，`tools/prefill_ab_cases/`）

40 条全部是真实文本，用发布包原生分词器 + 生产 chat template（`app/api/tool_calls.py::render_messages`，
thinking 关闭）编码，**没有任何合成 id 序列**。每条有固定答案与大小写不敏感的判分正则。

| 类型 | 数量 | 构造 | 实测长度 |
|---|---:|---|---|
| A 短问答 | 15 | 一段答题约束 + 一个常识/四则/换算问题 | 52–92 token（卡要求 40–250） |
| B 文中抽取 | 15 | 300–1500 token 的自写文章 + 一个只问文中一个事实的问题 | 300–336 token |
| C 多轮追问 | 10 | 先 prefill「文章 + 问题 + 助手回答」作为历史，decode 1 token，再 extend 一条追问 | 历史 201–238 token，追问块 32–36 token |

**关键约束（生成器校验，写进 `cases.json`）**：每条用例必须让两种规则真的走不同路径。
- A/B：`n_prompt % 64 >= 16`。64 规则取 `n - n%64` 行 + 回放余数；16 规则至少多对齐 16 行。
- C：追问块 16–63 token。64 规则整块回放（逐行 29–33 ms/token），16 规则一次 16/32 行动态发射。
  实测落在 32–36（生成器优先选 36–60 区间，因为第 1 阶段测出 17 行动态发射反而比回放慢）。

C 类的历史与追问不是手写的，而是从**同一次三消息渲染**里切出来的：历史 = 第一轮 user + assistant
（模板的 `keep_thinking=False` 规则，即不再保留 think 块）+ 生成头，追问块 = 模板为下一轮追加的那段
（`<|im_end|>\n<|im_start|>user\n…<|im_end|>\n` + 生成头）。这样 assistant 轮次的渲染走的是生产同一条
路径，不是模仿。中间那次 `decode 1 token` 是引擎既有机制（让 FA 层走 `block_kv`、状态进入「已生成」），
它产生的 1 个 token 不参与判分，`cases.json` 的 `text` 字段是「历史 + 追问块」两段的原文。

长度微调用**整句追加**（每条 A/B 自带 3 句可选句，B 不够时再追加 8 句中性句），不是填充 token，
所以 prompt 始终是真实英文散文。生成后 `cases.json` 记录每条的长度与 sha256，`--verify` 不需要
分词器和 NPU 即可复验（主机测试就是跑它）。

### 评测脚本 `tools/prefill_ab_eval.py`

- 参数：`--lib --model --cases --out --dev`，另有默认值的 `--tokenizer`（安装包内的 tokenizer.json）
  与 `--only`（只跑指定 id，用于复验个别用例）。
- 对齐值**不做参数**，从环境变量 `LLM_PREFILL_ALIGN` 读，并写进输出；`LLM_ALIGN_ABOVE` 非 0 直接拒绝
  运行（引擎规则假设它是 0）。
- 一个进程加载一次模型，40 条顺序跑完；每条**新会话**，跑完 `llm_session_free` 释放。
- 每条 greedy decode 最多 64 token，遇 `<|im_end|>` / `<|endoftext|>` 停止，只判回答文本。
- 记录 `id, type, n_prompt, n_delta, ttft_s, text, tokens, pass`；C 类另记 `prefill_s`（历史预填充耗时）。
  `ttft_s` 对 A/B 是 prefill 调用耗时，对 C 是 **extend 调用耗时**（用户真正等的追问首字）。
- 进程内 `signal.alarm(300)` 每条前重新计时，超时先把已有结果落盘再 `os._exit(3)`；外层套 `timeout 3600`。

### 执行

```
LLM_PREFILL_ALIGN=64 timeout 3600 python3 tools/prefill_ab_eval.py \
  --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
  --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
  --cases tools/prefill_ab_cases/cases.json --out logs/align-64.json --dev 0
```

两轮各一轮。原始 JSON 提交在 `tools/prefill_ab_cases/logs/align-64.json` 与 `align-16.json`。

## 第 1 部分结果：正确率与首字时间

### 汇总

| 分类 | 64 通过 | 16 通过 | TTFT 中位数 64 | TTFT 中位数 16 | 变化 |
|---|---:|---:|---:|---:|---:|
| A 短问答（15） | 15 | 14 | 1.280 s | 0.802 s | **-37%** |
| B 文中抽取（15） | 15 | 14 | 2.715 s | 1.986 s | **-27%** |
| C 多轮追问（10） | 10 | 7 | 0.800 s | 0.644 s | **-20%** |
| **总体（40）** | **40** | **35** | **1.326 s** | **0.847 s** | **-36%** |

- 基线 40/40 全通过，所以「基线通过、候选失败」的 5 条就是全部差异，没有「基线失败、候选通过」。
- 两轮都没有 rc≠0、没有超时、`dmesg` 无新条目。
- TTFT 口径：只含 prefill / extend 调用本身，**不含** 20 GB 模型加载（每轮进程重新加载一次，约 63 s）。

### 逐条对比

「一致」指 16 个（或到停止符为止的）greedy token 与 align=64 逐 token 全等；「首个分叉位」是第一个不同
token 的下标（0 基）。`n` 列 A/B 是 prompt 长度，C 是「历史 + 追问块」。

| id | 类型 | n | 64 | 16 | token 全等 | 首个分叉位 | TTFT 64 (s) | TTFT 16 (s) |
|---|---|---:|---:|---:|---|---:|---:|---:|
| a01 | A | 56 | P | P | 否 | 1 | 1.3283 | 0.8487 |
| a02 | A | 54 | P | P | 是 | – | 1.2803 | 0.8021 |
| a03 | A | 53 | P | P | 是 | – | 1.2590 | 0.7785 |
| a04 | A | 92 | P | P | 是 | – | 1.3630 | 1.1392 |
| a05 | A | 54 | **P** | **F** | 否 | 2 | 1.2793 | 0.8011 |
| a06 | A | 52 | P | P | 否 | 1 | 1.2400 | 0.7534 |
| a07 | A | 52 | P | P | 是 | – | 1.2353 | 0.7544 |
| a08 | A | 52 | P | P | 是 | – | 1.2358 | 0.7548 |
| a09 | A | 56 | P | P | 否 | 1 | 1.3312 | 0.8475 |
| a10 | A | 54 | P | P | 否 | 1 | 1.2812 | 0.8045 |
| a11 | A | 56 | P | P | 否 | 1 | 1.3254 | 0.8471 |
| a12 | A | 58 | P | P | 否 | 1 | 1.3735 | 0.9015 |
| a13 | A | 52 | P | P | 否 | 1 | 1.2331 | 0.7582 |
| a14 | A | 56 | P | P | 否 | 1 | 1.3274 | 0.8476 |
| a15 | A | 52 | P | P | 是 | – | 1.2332 | 0.7574 |
| b01 | B | 336 | P | P | 否 | 11 | 2.1977 | 1.9566 |
| b02 | B | 316 | P | P | 否 | 29 | 2.9379 | 2.0697 |
| b03 | B | 306 | P | P | 否 | 26 | 2.6761 | 1.8114 |
| b04 | B | 309 | P | P | 否 | 12 | 2.7813 | 1.9157 |
| b05 | B | 308 | P | P | 是 | – | 2.7364 | 1.8701 |
| b06 | B | 314 | P | P | 否 | 5 | 2.8554 | 1.9857 |
| b07 | B | 313 | P | P | 否 | 12 | 2.8522 | 1.9878 |
| b08 | B | 300 | P | P | 否 | 28 | 2.5446 | 1.9909 |
| b09 | B | 307 | P | P | 是 | – | 2.7150 | 1.8564 |
| b10 | B | 306 | **P** | **F** | 否 | 0（16 侧 0 token） | 2.6874 | 1.8207 |
| b11 | B | 318 | P | P | 否 | 5 | 2.9846 | 2.1167 |
| b12 | B | 310 | P | P | 否 | 23 | 2.7803 | 1.9119 |
| b13 | B | 302 | P | P | 否 | 12 | 2.6027 | 2.0511 |
| b14 | B | 303 | P | P | 是 | – | 2.6352 | 2.0968 |
| b15 | B | 300 | P | P | 否 | 5 | 2.5530 | 1.9985 |
| c01 | C | 256+35 | P | P | 否 | 4 | 0.8221 | 0.6611 |
| c02 | C | 240+32 | **P** | **F** | 否 | 0（16 侧 0 token） | 0.7593 | 0.5907 |
| c03 | C | 235+34 | P | P | 否 | 38 | 0.8017 | 0.6413 |
| c04 | C | 269+34 | P | P | 否 | 1 | 0.8004 | 0.6501 |
| c05 | C | 253+34 | P | P | 否 | 15 | 0.7998 | 0.6309 |
| c06 | C | 242+32 | **P** | **F** | 否 | 0（16 侧 0 token） | 0.7529 | 0.5909 |
| c07 | C | 246+35 | P | P | 否 | 1 | 0.8243 | 0.6730 |
| c08 | C | 250+32 | **P** | **F** | 否 | 0（16 侧 0 token） | 0.7541 | 0.5917 |
| c09 | C | 251+36 | P | P | 是 | – | 0.8461 | 0.7001 |
| c10 | C | 272+34 | P | P | 否 | 15 | 0.8006 | 0.6467 |

统计：40 条中 **10 条 token 全等、30 条不等**；不等的用例首个分叉位从 0 到 38 都有，说明差异不是
「最后一个 token 的收尾不同」，而是从路径改变处就开始分叉（与第 1 阶段的结论一致：分叉来自「哪些行走
精确 decode 回放图」，不是随机性）。

### 差异用例原文（5 条，全部是「基线通过、候选失败」）

**a05 — 常识问答（闰年天数），候选规则把推理写进了正文，答案没写出来**

- align=64（通过）：`\n\n<think>\n\n</think>\n\n366`
- align=16（失败）：`\n\n<think>\nHere's a thinking process:\n\n1.  **Analyze User Input:**\n   - **Task:** Answer short factual questions\n   - **Constraint 1:** Answers must be easy to grade\n   - **Constraint 2:** Reply with the value or name only\n   …`（64 token 预算耗尽，仍在推理块内）

**b10 — 文中抽取（谁造的织机），候选规则整轮拒答**

- align=64（通过）：`\n\n<think>\n\n</think>\n\nBased on the text provided, the looms were built by
  **Fairweather and Sons**.\n\nThe article states: "The looms are the originals, built by Fairweather and
  Sons in 1911 and sold to the mill in the same year."`
- align=16（失败）：空字符串 —— 第一个采样 token 就是 `<|im_end|>`

**c02 — 多轮追问（哪个船厂建造），候选规则整轮拒答**

- align=64（通过）：`The ship was built at the **Nakai yard**.\n\nNo, that yard had **not** built a vessel
  of this size before.`
- align=16（失败）：空字符串

**c06 — 多轮追问（哪个基金会出资），候选规则整轮拒答**

- align=64（通过）：`The **Ostrowski Foundation** paid for the restoration. In return, it asked that:
  \n\n1. The work be **documented**.\n2. The **drawings be published**.`
- align=16（失败）：空字符串

**c08 — 多轮追问（建在哪个高原），候选规则整轮拒答**

- align=64（通过）：`The array is built on the **Karoo plateau**.\n\nThe site was chosen for two main
  reasons:\n1.  **Radio quietness**: …\n2.  **Flat ground**: …`
- align=16（失败）：空字符串

**复现性**：这 5 条单独重跑（`--only a05,b10,c02,c06,c08`），align=16 仍 0/5、align=64 仍 5/5，
token 序列与首轮完全一致（原始 JSON：`logs/recheck-16.json`、`logs/recheck-64.json`）。贪心解码下
同一输入必然同一输出，所以这不是偶发。

### 失败的性质

5 条失败**都不是「答案算错」**，而是模型行为变成了另外两种：

1. **整轮拒答（4 条）**：第一个 token 直接采到 `<|im_end|>`。这在预填充 MoE 近似误差下是可以预期的
   —— 预填充图的第 0 层余弦只有 0.75（`tools/precision/README.md`），原本 64 规则会把整段短 prompt
   逐行送进精确 decode 图；放宽到 16 后这些行改走近似图，状态在第一个 decode 步就已经偏向「结束」。
2. **把推理写进正文（1 条）**：`<think>` 块内的第一 token 变了，模型顺势按「显式推理」的样式展开，
   64 token 预算不够回到答案。这条在 64 规则下是「立刻关掉 think 块直接回答」。

也就是说：**对齐值改变的是「哪些 token 走近似预填充图」，而这类近似恰好击中了「是否开始作答」这个
最脆弱的决策点**。回答质量本身（抽取的事实、算出的数字）在通过的那些用例里没有观察到变差 —— 差异
集中在「答不答」而不是「答得对不对」。

## 第 2 部分结果：长历史边界补测

用 `tools/prefill_width_probe.py`，`LLM_PREFILL_ALIGN=16`，按任务卡顺序每条只跑 1 次；每条后看
`dmesg`。为满足「与同长度 64 基线全等」的比较需要，每个长度另补跑一条 align=64 基线（见「与任务卡的偏差」）。

| # | case | history | 追加 | align | 实际路径 | TTFT (s) | rc | dmesg | 与同长度 64 基线对比 |
|---:|---|---:|---:|---:|---|---:|---:|---|---|
| 1 | extend | 2048 | 32 | 16 | L=32 | 0.6740 | 0 | 干净 | 不一致（分叉位 0）；**-14%（更快）** |
| 2 | extend | 2048 | 16 | 16 | L=16 | 0.5577 | 0 | 干净 | 不一致（分叉位 12）；**+41%（更慢）** |
| 3 | extend | 8192 | 32 | 16 | L=32 | 0.8707 | 0 | 干净 | 不一致（分叉位 6）；**-8%（更快）** |
| 4 | extend | 8192 | 16 | 16 | L=16 | 0.7615 | 0 | 干净 | 不一致（分叉位 12）；**+59%（更慢）** |
| 5 | fresh | – | 16 | 16 | L=16 | 0.5228 | 0 | 干净 | 不一致（分叉位 0）；**+30%（更慢）** |

补跑的基线（align=64，全部 rc=0、`dmesg` 干净）：

| case | history | 追加 | align=64 实际路径 | TTFT (s) |
|---|---|---:|---|---:|
| extend | 2048 | 32 | L=0 / 逐行回放 32 | 0.7801 |
| extend | 2048 | 16 | L=0 / 逐行回放 16 | 0.3955 |
| extend | 8192 | 32 | L=0 / 逐行回放 32 | 0.9453 |
| extend | 8192 | 16 | L=0 / 逐行回放 16 | 0.4787 |
| fresh | – | 16 | L=0 / 逐行回放 16 | 0.4026 |

- **5 条全部 rc=0，无 oops、无 `bmdrv_thread_sync_api` 超时、`dmesg` 无新条目**（整轮测试期间
  `dmesg` 只有一条与测试无关的条目，见「dmesg 检查」）。
- 会话 token 数：h2048+32 → 2095、h2048+16 → 2079、h8192+32 → 8239、h8192+16 → 8223、fresh16 → 31，
  与「历史 + 追加 + 1 个 prefill 采样 token + 16 个 decode」逐条吻合，说明 extend 真的把整段追加进去了。

### 关键发现：16 行动态发射比回放更慢

这是本部分最重要的数据，也是任务卡预期之外的：

| 场景 | align=64（逐行回放） | align=16（一次动态发射） | 差 |
|---|---:|---:|---:|
| extend h2048 + **32** | 0.7801 | **0.6740** | **-13.6%** |
| extend h2048 + **16** | 0.3955 | **0.5577** | **+41.0%** |
| extend h8192 + **32** | 0.9453 | **0.8707** | -7.9% |
| extend h8192 + **16** | 0.4787 | **0.7615** | **+59.1%** |
| fresh **16** | 0.4026 | **0.5228** | **+29.9%** |

即：**动态发射本身有固定开销（启动 + 历史 KV 拷贝），宽度太小时这笔开销超过「省掉 N 次逐行回放」的
收益**。32 行仍然划算（-8% ~ -14%），16 行全是负收益（+30% ~ +59%）。这与第 1 阶段 h1000+17 的
观察（0.40 → 0.54，变慢）完全一致，并且在 2048 / 8192 历史下都成立。

**对候选规则的直接影响**：任务卡描述的候选规则是「动态宽度取 16 的倍数且 ≥16」。按本表数据，
16–31 行这一档会**变慢 30%–60%**，也就是候选规则在一个它本来想优化的区间上做了负优化。
若最终采用放宽方案，下限更合理的取值是 **32 行**，而不是 16。

### 与第 1 阶段结论的关系

第 1 阶段卡死的是 history 2048 + **5 行**动态宽度。本次 16 / 32 行在 2048 与 8192 历史下都安全，
所以「长历史 + 极小宽度」的禁区边界在 5 与 16 之间 —— 安全性上「至少 16 行」这条下限站得住；
但从**收益**看 16 行不划算，32 行才是既安全又有收益的最小宽度。5 行这一格本阶段按任务卡未再试
（第 1 阶段已实测会卡死且需重启）。

## dmesg 检查

- 整轮测试（两次 A/B 评测 + 5 条边界补测 + 2 条基线）期间 `dmesg` **没有新增任何条目**，更无
  `Internal error` / `bmdrv_thread_sync_api` / `bdc_reg_read` oops。
- `dmesg` 中确实存在 1 条 oops，但它是**本次任务在实验开始前误触发的**，与 NPU 计算无关，也不是
  任何一次 prefill / extend 造成的：

  ```
  [664.437808] Unable to handle kernel paging request at virtual address 0000000000002014
  [664.488225] Internal error: Oops: 96000005 [#1] SMP
  [664.517582] CPU: 7 PID: 22957 Comm: cat
  [664.540226] pc : otp_reg_read+0x10/0x30 [bmtpu]
  [664.540226] lr : bm1688_base_get_core_num+0x14/0x3c [bmtpu]
  [664.540226] Call trace: otp_reg_read+0x10/0x30 [bmtpu] -> api_proc_show+0x34/0x1a0 [bmtpu] -> seq_read
  ```

  触发方式是 `cat /proc/bmtpu/bmdi_api_info`（我在实验准备阶段用它确认 NPU 空闲，这一步是多做的，
  任务卡只要求 `bm-smi` + `dmesg`；本机没有装 `bm-smi`）。**结论：这是驱动的一个 proc 读取缺陷
  —— `otp_reg_read` 在 `api_proc_show` 里读 OTP 寄存器时用了空指针**，与预填充宽度、与本阶段任何
  一次测试都无关。它出现后系统正常，后续 2 次 20 GB 模型加载与全部 46 次发射都成功，`bm-smi`
  （`/proc/bmtpu` 系列）与推理服务都恢复正常。
  - 影响评估：oops 发生在测试开始前（时间戳 664 s，`uptime` 当时约 11 分钟）；此后 `Internal error`
    计数始终为 1、`wait api timeout` 计数为 0，说明它没有把 TPU 或驱动带进异常状态。
  - **建议**：其它人在这块板子上不要 `cat /proc/bmtpu/bmdi_api_info`（以及同类 proc 入口），
    这条已在本报告留档。

## 结论与建议

按证据分三档给结论：

### 正确率

- **候选规则（align=16）会让一部分用例从「正常作答」变成「不答」**：40 条里 5 条（12.5%），
  且全部是「基线通过 → 候选失败」，无一条反向。失败形态是整轮拒答（4 条）与把推理写进正文（1 条），
  不是答案算错。
- 这个代价与首字收益是同一枚硬币的两面：收益来自「更多行走近似预填充图」，代价也一样。
- **不建议直接把默认规则改成 16**，理由就是这 12.5%。若要用这部分收益，需要先解决
  「是否开始作答」这个决策点的稳定性，可考虑的方向（本阶段未验证，只作为下一阶段的候选）：
  1. 折中阈值：只对超过某个长度的 prompt（例如 ≥ 256 token）放宽对齐，短 prompt 仍整段走精确回放
     —— 短 prompt 恰恰是首字收益最大的一档，所以这条会牺牲大部分收益，需要评估；
  2. 保留 `set_exact_tail`（只把最后 N 行送精确图）与放宽对齐组合，让「生成头之后的那几行」始终精确；
  3. 等厂商修复预填充图 MoE 算子（根治），这也是精度问题的最终解。

### 安全性

- **16 / 32 行动态宽度在 history 2048、8192 下都安全**（5/5 通过，无 oops），fresh 16 行安全。
  第 1 阶段的卡死只在 5 行这种极小宽度出现，候选规则「至少 16 行」的下限在这两个历史深度上站得住。
- **但 16 行不是合适的下限**：动态发射的固定开销（启动 + 历史 KV 拷贝）在 16–31 行这一档超过
  逐行回放的成本，实测慢 30%–60%；32 行才转为正收益（-8% ~ -14%）。若采用放宽方案，建议下限取 32。
- 仍未测：16 行以上但更长的历史（本阶段上限 8192）、以及 8192 以上的历史；按卡未超出范围。

## 与任务卡的偏差

1. **B 类问题加了「According to the article above, …」前缀。** 第一轮实测里 b02 / b08 / b10 在
   **两种对齐下都**整轮拒答（0 token），这类用例对 A/B 没有区分度。加了这句之后基线 15/15 全通过，
   对比才有意义。这是为了让用例「两种规则都真的走不同路径且能判分」，不改变考题。
2. **C 类追问长度落在 32–36 token，而不是更靠 20。** 卡要求 16–63；第 1 阶段测出 17 行动态发射比
   回放**更慢**（0.54 s vs 0.40 s），所以生成器优先选 36–60 区间，实际落在 32–36（仍有 4 条在 32）。
   这只是「落在区间内哪个位置」的选择，约束本身满足。
3. **补跑了 5 条 align=64 基线**（第 2 部分 h2048+32、h2048+16、h8192+32、h8192+16、fresh16）：
   验收要求「与同长度 64 基线全等」，原表未列这些基线。仍是一次只改一个变量、先基线后变对齐。
   正是这 5 条基线暴露出「16 行比回放更慢」。
4. **`--tokenizer` 与 `--only` 是任务卡参数表之外新增的可选项**（都有默认值 / 可省略），
   `--tokenizer` 用于把输出 token 解码成文本判分，`--only` 用于复验个别用例。任务卡列的 5 个参数
   仍是全部必需项，命令行与卡上写的一致。
5. **用例生成器放在 `tools/prefill_ab_cases/gen_cases.py`**，与任务卡列出的目录一致；id 文件与
   `cases.json` 同目录。另有 `logs/`（两轮原始 JSON + 复验 JSON）一并提交，便于复核。
6. **样机恢复**按卡执行：实验前 `systemctl stop cv84x6-llm`（SIGTERM，等其自行退出），结束后
   `systemctl start`，`/data/tmp/prefill-ab/` 已删。中间那次驱动 oops 见「dmesg 检查」，不是本阶段
   测试造成的，设备未重启、也未再出现异常。
7. 未改动 `native/`、`app/`、`web/`、默认配置与 `/opt/sophgo/cv84x6_llm_server`；未访问 2282。
   `tools/gen_prefill_probe_prompts.py` 只新增了 `delta-16` / `delta-32` / `turn-8192` 三个长度，
   **已有 8 个 id 文件逐字节未变**，`--verify` 仍 0 mismatches。

## 复现

```bash
# 1) 用例：板上生成（需发布包 lib + tokenizer），任意机器校验
python3 tools/prefill_ab_cases/gen_cases.py \
    --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --tokenizer /opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json
python3 tools/prefill_ab_cases/gen_cases.py --verify     # 40 cases, 0 problems

# 2) 第 1 部分：同一进程跑完 40 条，对齐值由环境变量决定
LLM_PREFILL_ALIGN=64 timeout 3600 python3 tools/prefill_ab_eval.py \
    --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
    --cases tools/prefill_ab_cases/cases.json --out logs/align-64.json --dev 0
LLM_PREFILL_ALIGN=16 timeout 3600 python3 tools/prefill_ab_eval.py \
    --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
    --cases tools/prefill_ab_cases/cases.json --out logs/align-16.json --dev 0

# 3) 第 2 部分：长历史边界（每条一次，每条后看 dmesg）
LLM_PREFILL_ALIGN=16 timeout 360 python3 tools/prefill_width_probe.py \
    --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
    --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \
    --case extend --history tools/prefill_probe_prompts/turn-2048.txt \
    --prompt tools/prefill_probe_prompts/delta-32.txt --decode 16 --dev 0
```

## 样机状态（已按任务卡恢复）

| 项 | 状态 |
|---|---|
| `cv84x6-llm` 服务 | **active**（实验前 `systemctl stop` 等其自行退出，结束后 `start`） |
| `healthz` | `{"ok":true,"version":"0.6.4","loaded":0}` |
| 模型 | 未加载（保持按需加载） |
| `/data/tmp/prefill-ab/` | **已删除**（日志已提交到仓库 `tools/prefill_ab_cases/logs/`） |
| NPU | 正常，`dmesg` 自测试开始无新增条目；驱动 oops 见上，出现于测试前且未复现 |
| 设备重启 | 未重启（本轮无需重启） |
