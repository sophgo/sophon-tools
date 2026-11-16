# 辅助模型动态 shape 与长 seq 评估：动态 Reranker 会打死 NPU，动态 Embedding 不划算

> 子任务 MYS-2702（父 MYS-2695）。基线 `main` `375824d`（含 PR #120 / MYS-2696），
> 分支 `research/aux-dynamic-seq`。
> 本文只做研究与原型：**未改 `app/`、`native/src`、`web/`、标签、版本号、release**。
> 所有数字在 `.157`（`10.43.0.157`，CV84X6，libsophon 0.4.15，内核
> `5.10.4-9c6431d06-sophon-custom-00610`）实测，测量时间是 2026-11-08。
> 复现脚本在 [`../../tools/embed/`](../../tools/embed/)，命令见 §11。
>
> **过程中重启过一次板子**：动态 Reranker 让 NPU 进入不可恢复的死锁，
> 只能 `systemctl reboot --force --force`（§5.3）。重启后已确认线上模型文件
> md5 未变、服务自动恢复、已加载的四项辅助模型恢复原状。

## 0. 结论先行

1. **方案 A（动态 shape）对 Reranker 不可用：它会打死整卡 NPU。**
   动态 rerank bmodel **能加载**，但**第一次前向就让进程进入 D 状态**，
   驱动报 `wait api timeout, wait 120000ms` 并抛
   `synchronous external abort`；此后**任何新进程的 NPU 前向都会同样卡死**，
   连一个最简单的 seq512 Embedding 都跑不动。`kill -9` 无效，
   **只有 `systemctl reboot --force --force` 能恢复**（本次实测）。
   这不是性能问题，是稳定性硬否决 —— 一条就足以否掉整个方案 A。
   （§5.3 有完整现场与推断的根因。）

2. **方案 A 对 Embedding 稳定，但只在 ≤100 token 时才比 static2048 快。**
   实测：47 token 时动态 193 ms vs 静态 291 ms（**快 34%**），
   247 token 时已经反过来（328 vs 292 ms，**慢 12%**），
   4080 token 时 **9380 ms vs 842 ms**，8160 token 时 **32018 ms**。
   交叉点约在 **100 token**。动态图**不做 shape 特化缓存**，
   首次与后续同价（§3.1），所以没有冷启动惩罚，也没有预热可蹭。

3. **短输入的收益，缩小静态图远大于动态图。**
   知识库切片的真实长度是 400–500 token。这个区间里：
   动态 **558 ms**、static2048 **292 ms**、**static512 只有 82 ms**。
   static512 比动态图快 **6.8 倍**，比现状快 **3.6 倍**。
   动态图省的是「没算的 padding」，静态小图省的是「没编进去的位置」，
   在业务长度上后者严格更优。

4. **「多档静态图合进一个 bmodel」做不到，但多档本身可行且不用改代码。**
   `model_tool --combine` 拒绝同名不同形状的网络
   （`net[embedding_cache] input tensors is conflict`）——它的设计用途是
   把**一个**模型按设备切分，不是捆多个变体。
   多档的正确形态是**多个 bmodel 文件、按长度选档**，
   而当前架构（扫目录发现模型、一模型一 worker）**天然支持**，
   落地是部署与配置问题，不改 `app/`（§7.2）。

5. **推荐：维持 static2048 为默认，增设 static512 作为短文本档。**
   理由与代价见 §9。核心权衡是**多 1217 MiB 内存换 3.6 倍短文本速度**，
   且不需要改任何产品代码、不需要重建知识库（§8）。

6. **长输入（>2048）本轮不建议支持。** 没有证据表明存在真实需求
   （切片目标 400–500 token），而 static4096 要付 +354 MiB / +24% 耗时。

## 1. 三个方案是什么，为什么只有其中两个真能测

| 方案 | 做法 | 本次是否实测 | 原因 |
|---|---|---|---|
| **A. 动态 shape** | `llm_convert.py --dynamic -s 8192` | ✅ Embedding 完整；**Reranker 只测到挂死** | Reranker 动态图一跑就打死 NPU（§5.3） |
| **B. 多档静态图** | 512 / 1024 / 2048 / 4096 各自 `static` 编译 | ✅ 各档都编了、都测了 | 但「合成一个 bmodel」不成立，见 §4.1 |
| **C. 现状** | static seq2048 | ✅ 基线 | — |

任务卡把 B 描述成「三个 static net 合进一个 bmodel」。**这一步做不到**，
不是参数没调对，而是 `model_tool --combine` 的语义就不允许：

```
$ model_tool --combine out_seq1024/*.bmodel out_seq2048/*.bmodel -o combo.bmodel
[BMODEL][IsTensorConflict:298] ERROR: tensor shape should not be the same
[BMODEL][AddNet:172] FATAL: net[embedding_cache] input tensors is conflict
```

原因很直白：两个 bmodel 都有名为 `embedding`、`block_0`…`block_27` 的网络，
合并在同一个 model 里时，同名网络的**输入张量形状不同**（`[1,1024]` vs `[1,2048]`）
就冲突。`--combine` 的设计用途是**把一个模型的各段按设备切开**
（`llm_combine.py` 的 docstring：「Combine LLM bmodels into pipeline-parallel (PP) groups」），
不是把同一模型的多个变体捆在一起。

所以「多档」在工程上只能是**多个 bmodel 文件、按长度选用**。
这仍然是任务卡要评估的方案，只是实现形态与卡上的措辞不同，§4 给出实测与代价。

## 2. 编译参数（三个方案各自的完整命令）

全部在构建容器 `embed_build`（镜像 `ocr-tpu:1.30.2`，tpu-mlir `1.30.2-38`）里编译，
`/workspace` 是 13.24 的 `/mnt/sda2/cv84x6_llm_server/build_embed`。

### 2.1 Embedding（Qwen3-Embedding-0.6B，bf16，bm1684x2，4 core）

```shell
# 方案 C / B 的各档：只改 -s
llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s 2048 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_seq2048          # C，已发布

llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s  512 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_seq512           # B 的短档
llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s 1024 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_seq1024
llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s 4096 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_seq4096

# 方案 A：加 --dynamic，最大长度 8192（模型 max_position_embeddings 是 32768，
# 但 8192 是任务卡的上界，也远超任何实际切片）
llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s 8192 -c bm1684x2 -q bf16 \
  --num_core 4 --dynamic --out_dir /workspace/out_dyn8192
```

`tools/embed/build_bmodel.sh` 已封装静态档（`build_bmodel.sh 512` 等），
本次新增的是把 `--dynamic` 与目标长度解耦 —— 见 §11.1 的脚本改动。

### 2.2 Reranker（BGE-Reranker-v2-M3，bf16，bm1684x2，4 core）

**这个模型不能直接编**：tpu-mlir 1.30.2-38 里**没有** `XLMRobertaConverter`，
`llm_convert.py` 的 dispatch 表也没有 `xlm-roberta` 这个 model_type，会直接死在
`Unsupported model type: xlm-roberta`。上游 master 有这两样，本次的做法是把它们
取下来装进镜像（`tools/embed/setup_xlm_roberta.py`，带 `--revert`）：

```shell
docker exec embed_build python3 /workspace/setup_xlm_roberta.py
```

它做三件事：把 `XLMRobertaConverter.py` 放进 `tpu_mlir/python/llm/`；
往 `LlmInfo.py` 追加 `XLM_ROBERTA_INFO` 权重映射；在 `llm_convert.py` 的
`LLM_CONVERTERS` 表里注册 `("xlm-roberta", "xlm_roberta")`。三处都先备份为
`*.bak-mys2702`。

之后：

```shell
llm_convert.py -m ./weights/bge-reranker-v2-m3 -s 2048 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_rr_seq2048        # C
llm_convert.py -m ./weights/bge-reranker-v2-m3 -s  512 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_rr_seq512         # B 短档
llm_convert.py -m ./weights/bge-reranker-v2-m3 -s 4096 -c bm1684x2 -q bf16 \
  --num_core 4 --out_dir /workspace/out_rr_seq4096
llm_convert.py -m ./weights/bge-reranker-v2-m3 -s 8192 -c bm1684x2 -q bf16 \
  --num_core 4 --dynamic --out_dir /workspace/out_rr_dyn8192   # A
```

权重来自 ModelScope（`BAAI/bge-reranker-v2-m3`，2.27 GB）。**不要用 HuggingFace**：
同一时刻 HF 是 0.6 MB/s、ModelScope 是 9.3 MB/s，2.3 GB 的差别是 1 小时对 4 分钟。

### 2.3 产物清单

| 文件 | 大小 | md5 |
|---|---|---|
| `qwen3-embedding-0.6b_bf16_seq512_bm1684x2_4core_static_20261108_045357` | 1.21 GB | `864f09b7e7e2a37d420243d8be7a8346` |
| `qwen3-embedding-0.6b_bf16_seq1024_…_static_20261108_011924` | 1.21 GB | `81466ff1ddff4db3b81e16aae42b35a7` |
| `qwen3-embedding-0.6b_bf16_seq2048_…_static_20261108_011851` | 1.23 GB | `b68c2f784b8c93d82c35334d5451cac2` |
| `qwen3-embedding-0.6b_bf16_seq4096_…_static_20261108_045357` | 1.27 GB | `35d303974db394537984e94204d96d6f` |
| `qwen3-embedding-0.6b_bf16_seq8192_…_dynamic_20261108_044649` | 1.32 GB | `147f3f2344467e63f2c29aab4a5a8d44` |
| `bge-reranker-v2-m3_bf16_seq512_bm1684x2_4core_static_20261108_050751` | 1.14 GB | `05e49985475bf1404855dab7d089f8fb` |
| `bge-reranker-v2-m3_bf16_seq2048_…_static_20261108_050120` | 1.14 GB | `777b907cd36165336d84e8fe4b794b9d` |
| `bge-reranker-v2-m3_bf16_seq4096_…_static_20261108_050815` | 1.15 GB | `a73814f5cc9930bff0086109d7c00792` |
| `bge-reranker-v2-m3_bf16_seq8192_…_dynamic_20261108_050535` | 1.14 GB | `64041f10b7dac0d671283f2db55833ac` |

## 3. Embedding：各档耗时

单条前向，`libcv84x6_llm.so` 的 `cv_embed_forward`，中位数（10 次），
文本是真实中英混排散文（`aux_seq_sweep.py` 的 `FILLER`），逐档按实际 token 数标注。

| 输入 token | static512 | static1024 | **static2048（现状）** | static4096 | dyn8192 | shipped8192 |
|---|---|---|---|---|---|---|
| 47 | **82 ms** | 137 ms | 291 ms | 842 ms | 193 ms | 2793 ms |
| 247 | **82 ms** | 137 ms | 292 ms | 841 ms | 328 ms | 2792 ms |
| 484 | **83 ms** | 137 ms | 292 ms | 840 ms | 558 ms | 2795 ms |
| 1001 | n/a | **137 ms** | 294 ms | 842 ms | 1209 ms | 2794 ms |
| 2025 | n/a | n/a | **293 ms** | 842 ms | 3119 ms | 2795 ms |
| 4080 | n/a | n/a | n/a (>2048) | **846 ms** | 9380 ms | 2796 ms |
| 8160 | n/a | n/a | n/a | n/a (>4096) | **32018 ms** | **2807 ms** |

**四个可直接读出的事实：**

1. **静态图的耗时与输入长度无关**（291/292/292/294/293 —— 五个长度差 <1%），
   这正是静态图的定义；动态图的耗时**随长度超线性增长**。
2. **动态图不是「线性」而是接近二次**：1001→2025 token（1.02 倍）耗时 1209→3119 ms
   （2.6 倍），2025→4080（2.0 倍）耗时 3119→9380 ms（3.0 倍），
   4080→8160（2.0 倍）耗时 9380→32018 ms（**3.4 倍**）。
   这就是 attention 的 O(N²) —— 静态图同样要算 N²，但它的 **N 是编译期常数**
   且被排布优化过，所以长输入下反而快。
3. **交叉点在约 100 token**：短于它动态赢，长于它静态赢。
   所以「动态 shape」只解决了「短输入不该等长图」这一个具体问题。
4. **两个已发布数字都被复现**：`shipped8192` 2.79–2.81 s、`static2048` 291–294 ms，
   与 `docs/aux-models.md`（MYS-2696 / PR #120）的记录一致，
   说明本次测量口径与上一轮相同，可比。

### 3.1 首次某个长度有没有额外开销？

**没有。** 每一档的 `first`（第一次调用）与 `median` 差都在 1% 以内：
dyn8192 在 1001 token 上首次 1208.0 ms、中位 1208.6 ms；2025 token 上 3117.2 / 3118.8。
动态图**不做 JIT、不做 shape 特化缓存**，每次按实际 shape 发射，所以
「第一次见某个长度」和「第二次」一样慢。这对服务是个好消息（没有冷启动惩罚），
也意味着**不能用「预热」掩盖动态图的成本**。

### 3.2 精度（Embedding，对 static2048 的余弦）

| 输入 token | dyn8192 | static512 | static1024 | static4096 | shipped8192 |
|---|---|---|---|---|---|
| 47 | 0.9998947 | 0.9998886 | 1.0000000 | 0.9998886 | 0.9998886 |
| 247 | 0.9998512 | 0.9997866 | 1.0000000 | 0.9997866 | 0.9997866 |
| 484 | 0.9997163 | 0.9997840 | 1.0000000 | 0.9997840 | 0.9997840 |
| 1001 | 0.9996598 | n/a | 1.0000000 | 0.9995517 | 0.9995517 |
| 2025 | 0.9995431 | n/a | n/a | 0.9996940 | 0.9996940 |

全部 **≥ 0.9995**，过 MYS-2696 定的 0.999 门槛。注意 `static1024` 与 `static2048`
在共同支持的长度上是 **1.0000000**（逐位相同），说明「缩小静态图不改变向量」
这一前提依然成立 —— 与 PR #120 的结论一致。

`dyn8192` 的余弦略低于 `static1024`（0.9995–0.9999 vs 1.0），差异虽小但系统性存在：
动态图走的是另一条发射路径（`launch_dyn`，直接改写 `dims[1]`），
数值上等价但不逐位相同。这不影响可用性，但意味着**动态图不是「免费的 shape 参数」**。

**这张表是「各档之间」的一致性。** 与 HF 的一致性另有一层问题，值得单独记：

### 3.3 ★ Embedding 与 HF 的余弦只有 0.73–0.90 —— 原因是两侧分词差一个 token

`aux_vs_hf.py` 在板上对拍时，**每一档 bmodel 对 HF 参考的余弦都只有 0.73–0.90**，
远低于门槛。这个数字看起来像「模型编坏了」，但同一次测量里
**各档 bmodel 之间是 0.9995 以上**，所以 bmodel 之间不可能同时错成一样。
差异在参考侧。

逐层定位到**分词**：

- HF `AutoTokenizer` 与**服务用的 C++ 分词器**对同一段中文给出
  **相差 1 个 token** 的结果（64 档：HF 48、C++ 47；512 档：HF 485、C++ 484）。
  差别在结尾那个 special token 的处理上；
- Embedding 是 **last-token pooling** —— 池化的是**最后一个位置**。
  多一个或少一个 token，池化的就是**不同的位置**，向量自然大幅不同。
  实测把同一个 EOS 追加到 HF 序列尾部，余弦从 1.0 掉到 **0.775**；
  换成另一个 EOS（151645 而非 151643）掉到 **0.709**。
  **这个模型对尾部 token 极其敏感**，这是 last-token pooling 的固有性质，
  不是 bug。

**关键对照实验**：把**同一组 token id** 直接喂给两侧
（`diag_ab.json`，板上 `cv_embed_forward` vs 容器里 HF 前向），
余弦是 **0.9998796**。

所以结论是：
- **bmodel 与 HF 在数学上是一致的（0.9999）**，bmodel 没有编坏；
- 0.73–0.90 那组数字是**「用不同分词器切出的不同文本」之间的余弦**，
  衡量的是分词差异而不是模型精度；
- **不能**用它评价 bmodel 的精度。

这条对本轮方案取舍没有影响（取舍只看相对耗时与稳定性），
但它是一个**测量陷阱**：将来任何人用「HF 当参考」评价 embedding 精度，
必须先固定 token id，否则会得到一组看起来像精度事故的假数字。
`aux_vs_hf.py` 已改为直接比对**同一段文本**，但它仍受分词差异影响 ——
正确的做法是比对**同一组 token id**，这需要在 HF 侧构造 bmodel 实际收到的 ids
（即用服务的 `tokenizer.json` 而不带模板），已记入 §12 待办 6。

`static512`/`static4096`/`shipped8192` 三者余弦相同到 7 位小数，这不奇怪：
它们的差异与 `static2048` **同源**（都是 bf16 在不同编译长度下的舍入路径），
数值上落在同一个结果上。而 `static1024` 与 2048 **逐位一致**是另一件事 ——
它在三个共同长度上与参考完全相同，说明这两个编译长度产生的 bf16 舍入路径一致。
**这一条没有进一步验证机制**（需要逐层对拍），只作为一个观测记录；
但对迁移的结论不敏感：两种情况下余弦都 ≥0.9995。

## 4. 多档静态图（方案 B）的真实形态

### 4.1 为什么「合进一个 bmodel」不成立

见 §1 的 `model_tool --combine` 报错。补充两点验证：

- `--combine_dir` 同样失败，且报的是 `std::out_of_range`（它按目录名反推 net 名，
  两个目录都是同一模型的变体，名字解析直接越界）。
- `--combine_coeff` 断言 `model->net()->size() == 1`，即**只接受每个文件只有一个网络**，
  而 LLM bmodel 有 59 个。

所以 B 的正确实现是**多个文件**。剩下的问题只有两个：内存，和选档。

### 4.2 内存：各档的 NPU 占用

完整数字见 §6。要点：同族不同 seq 的 bmodel **权重完全相同**
（bf16 权重与 seq 无关），差别只在激活与 IO 缓冲，所以文件大小几乎一样
（512→8192 只从 1.21 GB 涨到 1.32 GB），但**NPU 堆增量差别明显**
（1217 → 2372 MiB），因为 embedding 图输出是 `[1, seq, 1024]`、
attention 激活随 seq 线性增长。

**「多档」省不了权重的钱**：装 512+2048 两档是 2682 MiB，
比单档 2048 的 1465 MiB 多 83%。这是方案 B 的真实代价，不是一个可以忽略的数字。

### 4.3 选档对批量请求的影响

服务的 Embedding 一次请求可带最多 64 条文本，**整批作为一次 worker 占用**
（`_run_whole`）。所以选档只能按「本批最长的那条」来：

- 一批里有一条 500 token 的切片，整批就必须走 512 档（1024 档浪费 33% 的时间：
  137 vs 82 ms，且没有精度收益 —— 1024 与 2048 逐位相同，见 §3.2）；
- 一批里有一条 2100 token 的，整批走 4096 档（842 ms/条），
  而现状是整批直接 400 —— **这是多档唯一真正优于现状的地方**：
  长输入从「拒绝」变成「变慢但能答」；
- 动态图在同一场景下是 3119 ms/条（2025 token），比 4096 档慢 3.7 倍。

**这也是为什么「按最长那条选档」不会浪费太多**：切片长度集中在 400–500，
绝大多数批次都会落在 512 档，而不是被偶尔一条长的拖到 2048 档。

## 5. Reranker：各档耗时、精度，以及动态图为什么不可用

### 5.1 静态各档耗时

单次前向（`cv_rerank_forward`，一次 = 一个 query/document 对），中位数 10 次。
表头是**编译长度**；「pair」是 query 与 document 拼接后的真实 token 数
（query 固定 50 token，document 递增）。

| pair token | **本次自编 seq2048（≡ 现状）** | seq4096 | seq512 | 厂商 seq2048（现网） |
|---|---|---|---|---|
| 95 | 302 ms | 1340 ms | **85 ms** | 304 ms |
| 288 | 302 ms | 1340 ms | **85 ms** | 302 ms |
| 528 | 302 ms | 1332 ms | n/a (>512) | 301 ms |
| 1034 | 301 ms | 1328 ms | n/a | 302 ms |
| 2050 | n/a (>2048) | **1333 ms** | n/a | n/a |

「本次自编 seq2048」与「厂商 seq2048（现网）」两列并存，是因为它们**本来就该相同**
（结论 2 证明了两者 logit 逐位一致）—— 并列是为了让这条交叉验证可见，
不是两组不同的测量。

**两点直接结论：**

1. **静态图的耗时与 pair 长度无关**（302/302/302/301 —— 差 <0.6%），
   与 Embedding 的结论完全一致。seq512 只要 **85 ms**，比 seq2048 快 **3.6 倍**。
2. **本次自编的 seq2048 与厂商发布的 bmodel 逐位一致**（logit 完全相同：
   -1.0312 / -6.0000 / -0.2441 / 2.6875）。这是本轮最有价值的交叉验证：
   它证明我用 `setup_xlm_roberta.py` 补的 `XLMRobertaConverter` 链路是**正确的**，
   而不是「编出来了但不是同一个模型」。没有这一步，后面所有 seq512/seq4096
   的数字都无法采信。

### 5.2 精度（对 HF 参考）

HF 参考来自原始 PyTorch checkpoint（`aux_hf_reference.py`，在构建容器里跑）。
Reranker 输出是单个 logit，所以比的是**绝对差**而不是余弦。

| pair token | HF logit | seq2048 logit | 绝对差 |
|---|---|---|---|
| 95 | -0.2323 | -1.0312 | 0.799 |
| 288 | -5.9258 | -6.0000 | 0.074 |
| 528 | 0.3972 | -0.2441 | 0.641 |
| 1034 | 2.4621 | 2.6875 | 0.225 |
| 2050 | 3.3826 | （seq4096: 3.2188） | 0.164 |

**logit 有 0.07–0.80 的绝对偏差。** 这个偏差**不是本次编译引入的**，证据：
我自编的 seq2048 与厂商发布的 seq2048 **logit 逐位相同**（§5.1 的 4 个点全部一致），
所以偏差存在于厂商那份 bmodel 里，早于本任务，本轮只是把它量出来了。

**偏差的来源本轮没有完全定论。** Reranker 与 Embedding 不同：它的两条链路
（HF 与 bmodel）**都用同一个 `tokenizer.json`** 分词，所以 §3.3 那个
「分词差一个 token」的问题在这里**不成立**。剩下的候选是：
(a) bf16 在 24 层编码器上的累积舍入；
(b) 两侧的 padding / position-id 语义不完全等价（我按服务的方式右填充到 SEQLEN
并屏蔽，HF 侧送的是未填充序列，XLM-R 的位置编码在两种情形下对真实 token 应当一致，
但 attention mask 的加性形式仍需逐层核对）。
要分清两者需要逐层对拍，超出本任务范围。

**对服务的影响需要分开看：**
- **排序**：rerank 的输出只用来排候选文档的序，而检索场景里相邻候选的分数差
  通常远大于 0.8，所以这个偏差大概率不改变顺序 —— 但这**本轮没有实测验证**，
  是推断。要确认需在真实知识库上做 rerank 前后 top-k 一致性对拍。
- **绝对分数**：当前服务不把 rerank 原始分数暴露给用户。若将来要暴露，
  这个偏差必须先解决。

这条留作待办，**不阻塞本轮的方案结论**（方案取舍取决于耗时与稳定性，
两者都不受它影响）。

### 5.3 ★ 动态 Reranker 会打死 NPU —— 方案 A 对 Reranker 不可用

**这是本轮最重要的否定性结论，也是任务卡问题 1「动态 shape 是否稳定」的直接答案：
对 Embedding 稳定，对 Reranker 不稳定，且失败方式是灾难性的。**

复现步骤（**不要在生产板重跑，除非接受重启**）：

```shell
# bmodel 本身能加载：cv_rerank_create 返回有效句柄
# 但第一次 cv_rerank_forward 就永久挂住
python3 bin/aux_seq_sweep.py --kind rerank \
  --model rrdyn8192=…bge-reranker-v2-m3_bf16_seq8192_…_dynamic_….bmodel \
  --reference rrdyn8192 --repeats 2
```

现场：

```
$ ps -o pid,stat,etime,wchan:26 -p <pid>
    PID STAT     ELAPSED WCHAN
3417501 D          01:52 bmdrv_thread_sync_api

$ dmesg
bmtpu: bmdrv_thread_sync_api:1471: bm-sophon0 bmdrv_thread_sync_api,
       wait api timeout, wait 120000ms, core_id=0
Internal error: synchronous external abort: 96000010 [#8] SMP
pc : bdc_reg_read+0x10/0x30 [bmtpu]
lr : bmdrv_thread_sync_api+0x2d8/0x4e4 [bmtpu]
```

**后果是整卡 NPU 不可用，不只是该进程。** 重启前的实测：

- 挂死进程处于 **D 状态**，`kill -TERM`/`kill -9` 都无效（D 状态不响应信号）；
- **之后任何新进程的 NPU 前向都会同样卡死**，包括一个最简单的
  seq512 Embedding 前向（`t.py`：`opened 512` → `fwd` → 再无输出），
  以及一个**本来可以正常工作的**已安装 seq8192 bmodel；
- 换用 `timeout 200` 等待超过驱动的 120 s 超时，仍然不返回 —— **不是慢，是死**；
- 板上其余进程（4 个既有 worker、HTTP 服务）不受影响，说明是 NPU 子系统的
  同步等待死锁，不是整机挂起。

**恢复只有重启**，且 `systemctl reboot` 会被 D 状态进程拖住，
必须 `systemctl reboot --force --force`（`BSP-NOTES.md` §MYS-2609 记的同一条）。
本次实测：14:02 发起、14:11 服务恢复，boot_id
`fe8852de-…` → `98d84287-…`，重启后 `bm_test` 与 seq512 Embedding 前向均正常。

**根因推断（未实测确认）**：`native/src/rerank_engine.cpp` 的 `launch()`
**没有动态发射路径** —— 对比 `embed_engine.cpp` 有 `launch_dyn()` 会按真实
token 数改写 `input_shapes[i].dims[1]`，rerank 的 `launch()` 直接按
`stages[0].input_shapes` 原样发射，而动态 bmodel 的那组 shape 是 `max:` 形式。
按一个 `max:` 形状发射，很可能让驱动按最大值配了描述符但没有有效的调度上下文。

**为什么没有继续修**：要确认或修复必须改 `native/` 加动态路径，而任务卡明确
禁止改产品代码；且每次验证失败都要重启一次共享板子。所以本轮把
「方案 A 对 Reranker 不可用」作为实测结论记录，把根因留作待办。

**这条结论改变了推荐**：即使忽略性能，动态 Reranker 也是不可选项 ——
它的失败模式是「整卡 NPU 死到重启」，对一个线上服务是不可接受的。

### 5.4 Reranker 引擎不能在同一进程里跑完多个档（段错误）

顺带测到的一个工具侧限制，**不影响上面的结论**，但复现时必须知道：
把两个不同 seq 的 rerank bmodel 交给**同一个** `aux_seq_sweep.py` 进程依次测，
进程会在**第二个档测完之后**段错误（`rc=139`），栈外可见
`bmlib mmap in d2s fast failed` 与 `mem guard fetch data failed`。

在**健康的板子上**（重启后、无其他模型加载）复测，稳定复现。
收缩到最小用例后，边界很窄：

| 用例 | 结果 |
|---|---|
| 同一个 bmodel create/destroy 两轮 | ✅ 正常 |
| A create → destroy → B create → destroy（**不跑前向**） | ✅ 正常 |
| A 加载+前向+销毁 → B 加载+前向+销毁（**各 1 次前向**） | ✅ 正常 |
| A（4 个长度 × 2 次前向）→ B（2 个长度 × 2 次前向） | ❌ **段错误** |

所以触发条件与前向**次数/长度跨度**有关，不是「换个 bmodel」本身。
`native/src/rerank_engine.cpp` 每次前向都会 `bm_malloc` 一块
`seq_len × hidden × 2` 的宿主侧 `std::vector` 并做 D2S，这个模式在
`seq2048`（4 MiB/次 × 6 次）后切换到 `seq512` 时崩在**销毁路径**上。
具体是 libsophon 的堆管理还是引擎的缓冲释放次序，本轮没有继续定位。

**规避方式（已验证）**：一次进程只测一个档，外部脚本循环。
这也是 §11.2 的写法。注意**这不影响线上服务** —— 服务是「一个 worker 一个
bmodel、生命周期内不换档」，正好避开了这个模式。

## 6. NPU 占用（`mem_probe.py`，加载后的堆增量）

测量方法是 `docs/model-settings.md` 的口径：NPU 堆在 `cv_*_create` 前后的差值，
不是 `bmrt_get_bmodel_info` 的 `io_mem`（后者高估数百 MiB）。
板上此时没有其他模型加载（`before: 0.0 MiB used`），所以数字是纯静态占用。

### 6.1 Embedding

| 档 | seq | 文件大小 | **NPU 堆增量** |
|---|---|---|---|
| static512 | 512 | 1150 MiB | **1217 MiB** |
| static1024 | 1024 | 1157 MiB | **1298 MiB** |
| **static2048（现状）** | 2048 | 1173 MiB | **1465 MiB** |
| static4096 | 4096 | 1211 MiB | **1819 MiB** |
| dyn8192 | 8192 | 1255 MiB | **2372 MiB** |

**关键读数：权重占绝大部分，seq 只影响激活/IO 那一小部分。**
从 512 到 8192（16 倍序列长度）堆只从 1217 涨到 2372 MiB（+95%），
因为 bf16 权重（约 1.1 GiB）与 seq 无关，涨的是 attention 的激活缓冲
（与 seq 成线性）和 embedding 图输出的 `[1, seq, 1024]` bf16 缓冲
（seq8192 时是 16 MiB）。

**对多档方案的含义：装 N 个档不省权重，每个档都要付一整份。**
- 现状（1 档 2048）：**1465 MiB**
- 两档（512 + 2048）：1217 + 1465 = **2682 MiB**（+1217，即 +83%）
- 三档（512 + 2048 + 4096）：**4501 MiB**（+307%）
- 单档动态 8192：**2372 MiB**（比两档方案少 310 MiB，但性能差得多，§3）

这是一个真实的取舍：**多档用小内存换性能，动态用中等内存换长输入能力
（但性能不可接受）。**

### 6.2 Reranker

| 档 | seq | 文件大小 | **NPU 堆增量** |
|---|---|---|---|
| static512 | 512 | 1089 MiB | **1096 MiB** |
| **static2048（现状）** | 2048 | 1089 MiB | **1136 MiB** |
| static4096 | 4096 | 1093 MiB | **1208 MiB** |
| 厂商 seq2048（现网） | 2048 | 1092 MiB | **1136 MiB** |

**Reranker 的各档差异更小**（1096 → 1208 MiB，seq 扩大 8 倍只涨 10%），
因为它的 block 图不产生 KV cache，只有 attention 的中间矩阵随 seq 增长。
本次自编的 seq2048 与厂商现网那份**堆占用完全相同（1136 MiB）** ——
又一个「两条链路等价」的证据。

**注意：厂商文件名写 `_cv84x6_`，本次自编写 `_bm1684x2_`，两者是同一种芯片**
（CV84X6 在 tpu-mlir 里的 target 名就是 `bm1684x2`），占用与输出都一致。

## 7. 对服务代码的改动面（任务卡问题 4）

分三种情况，改动量差别很大。

### 7.1 若采用「动态图」（方案 A）—— 不推荐，但列出需要改什么

| 文件 | 改动 | 为什么 |
|---|---|---|
| `native/src/rerank_engine.cpp` | **必须加 `launch_dyn()`** | 现在没有动态发射路径，动态 bmodel 一跑就打死 NPU（§5.3）。这是硬前置条件 |
| `native/src/embed_engine.cpp` | 无需改 | `launch_dyn()` 已存在，实测可用 |
| `app/engine/aux_backend.py:229`（embed）、`:282`（rerank） | 上限从 `seq_len` 变成实际可用上限 | 动态图的 `seq_len` 报的是最大值（8192），逻辑上不用改，但**错误信息会从「超过 2048」变成「超过 8192」**，用户感知变化 |
| `app/core/mem_limit.py` | 静态占用从 1465 → 2372 MiB | 默认上限会跟着涨，`docs/model-settings.md` 的表要更新 |
| Reranker padding | 改为不填充（按真实长度发射） | 这是动态图的**全部收益来源**；不改则动态图的收益为零 |

### 7.2 若采用「多档静态」（方案 B）—— 推荐，但**不需要改产品代码**

这是本轮最值得强调的一点：**当前架构天然支持多档**。

- `app/core/models.py` 的模型发现是**扫目录**，一个 `models/<kind>/` 下可以放多个
  bmodel 文件，每个都是独立的模型条目；
- 每个模型一个 worker、一个 bmodel（`app/engine/worker.py`），互不干扰；
- 服务已经支持「按已加载模型降级」（`docs/kb-app.md`）。

所以「多档」的落地是**部署与配置**，不是代码：
1. 在 `models/qwen3-embedding-0.6b/` 下放 seq512 与 seq2048 两个文件；
2. 在 `model-config/` 里各给一个 config（tokenizer 相同，可直接复用）；
3. 由调用方（或 KB 的切片器）按 `input_tokens()` 选模型。

**唯一需要写代码的地方**是「自动选档」——若希望服务自己按输入长度路由，
需要改 `app/engine/aux_backend.py` 或 KB 的检索路径加一层选择逻辑。
但即使不改，用户也可以手动指定模型，收益已经拿到。

### 7.3 必改项（无论哪个方案）

| 文件 | 现状 | 若上长 seq 必须改 |
|---|---|---|
| `app/engine/aux_backend.py:229` | `real_len > self.seq_len` → 400 | seq 变大后这条自然放宽，**无需改代码**，但 `docs/aux-models.md:45` 的「2048」要更新 |
| `app/engine/aux_backend.py:282` | 同上（rerank） | 同上 |
| `app/core/mem_limit.py` | 按 bmodel 静态估算 | 无需改；数字随 bmodel 自动变 |
| Reranker padding（`aux_tok.py:177`） | 静态填充到 SEQLEN | 静态多档方案下**保持现状**；只有动态方案才需要改 |

## 8. 迁移：已有知识库要不要重建（任务卡问题 5）

**不需要重建，前提是迁移到 static512 / static1024 / static2048。**

依据是 §3.2 的余弦：`static1024` 与 `static2048` 在所有共同长度上
**逐位相同（1.0000000）**，`static512` 也有 0.9998–0.9999 ——
**即同一段文本在新旧档位上得到几乎相同的向量**，所以已有向量仍然有效。
这与 PR #120 在 seq8192 → seq2048 迁移时的判据相同，当时用 `kb_recheck.py`
在 284 条切片的真实知识库上确认「六个探针查询的 top-3 完全一致」。

**注意**：`kb_recheck.py` 的对拍**本轮没有重跑**（板上没有可用的两档并行部署，
且 §3.2 的余弦已经给出同量级的证据）。若要把双档正式上线，
应在上线前用 `kb_recheck.py` 在真实知识库上复核一次 —— 这是低成本、高价值的确认。

**若采用动态图，理论上也不需要重建**（余弦同样 ≥0.9995），
但动态图因 §5.3 的稳定性问题不推荐，且它在 400–500 token 区间更慢，
迁移过去反而变差。

**唯一需要重建的情形**：把切片的**目标长度**也改掉（例如为了配合 seq512
把切片从 400–500 token 降到 400 以下）。那是切片策略变更，不是模型变更，
两者应分开评估 —— 本报告不建议同时做。

## 9. 推荐方案与理由

### 推荐：**维持 static2048 为默认，增设 static512 作为短文本档**
（若只允许选一个，则维持现状 static2048 不动。）

**理由（按重要性排序）：**

1. **动态图对 Reranker 会打死整卡 NPU**（§5.3）。这是不可接受的失败模式，
   一条就足以否决方案 A —— 即使它的性能更好也不行。
2. **动态图对 Embedding 虽稳定，但只在 ≤100 token 时赢**（§3），
   而知识库切片的真实长度是 400–500 token，检索 query 虽然短
   但**它和文档走同一次批量请求**（`_run_whole`），整批按最长的那条计时，
   所以实际业务里几乎总是落在「动态图更慢」的一侧。
3. **static512 在短档上比动态图快 6.8 倍**（82 ms vs 558 ms @484 token），
   且**不需要改任何产品代码**（§7.2）。
4. **static512 + static2048 的内存代价是 +83%**（1465 → 2682 MiB）。
   在 26 GiB 的板上这是可接受的；若内存紧张，可以只上 static512
   （放弃 512–2048 区间的输入，代价是这些输入回到 400）。
   **这是方案 B 唯一的实质成本，也是本推荐最可能被质疑的地方** ——
   如果 +1217 MiB 不可接受，那么正确答案是「维持现状不动」，
   而不是退回到方案 A。
5. **长输入（>2048）本轮不建议支持。** static4096 能把上限提到 4096，
   代价是 +354 MiB / +24% 耗时（1465 → 1819 MiB，292 → 842 ms）。
   但**当前没有任何证据表明有 >2048 token 的真实需求** ——
   切片目标长度是 400–500 token，而 400 字的切片离 2048 很远。
   在没有需求的情况下支持它，是付费换一个可能没人用的能力。

### 明确不推荐

- **方案 A（动态）**：Reranker 打死 NPU（硬否决），Embedding 在业务长度上更慢。
- **三档及以上静态**：内存涨 3 倍，而 512–2048 之间的档位（1024）
  与 2048 **逐位相同**（§3.2），没有精度收益，只有内存代价。

### 如果将来需求变化

若确实出现 >2048 token 的输入需求，正确的下一步**不是**上动态图，而是：
1. 先确认需求规模（有多少百分比的输入超过 2048）；
2. 若比例低，加一档 static4096 并只在必要时路由过去；
3. 只有在「输入长度分布极宽且长输入占比高」时，才值得回头修
   `rerank_engine.cpp` 的动态路径 —— 且必须先在非生产板验证不会打死 NPU。

## 10. 与任务卡的偏差

| 任务卡要求 | 实际 | 原因 |
|---|---|---|
| 方案 B = 「三个 static net 合进一个 bmodel」 | **做不到**，改为「三档各自一个 bmodel，按长度选」 | `model_tool --combine` 不接受同名不同形状的网络（§1、§4.1），这是工具语义限制，不是参数问题 |
| 「Reranker 各档耗时表」 | seq512/2048/4096 有完整数据；**seq8192 动态无数据** | 动态 rerank 一跑就打死 NPU（§5.3），每次尝试都要重启板子，未继续 |
| 「与 HF 参考的 logit 误差」 | 有完整数据（§5.2），但**偏差来源未定论** | 需要逐层对拍，超出本任务范围；且已证明偏差不是本次编译引入的 |
| 「首次某个长度是否有额外开销」 | 有答案：**没有**（§3.1） | — |
| 「测试结束后 .157 恢复原状」 | **已恢复**，但过程中重启过一次 | 动态 rerank 打死 NPU，只能重启恢复（§5.3）。重启前后线上模型文件 md5 一致、服务自动起来、已加载模型恢复为原先的 embedding+reranker+ASR+OCR 四项 |

## 11. 复现方式

### 11.1 编译（13.24，构建容器）

```shell
# 容器（已存在）
docker start embed_build

# Reranker 需要先补 tpu-mlir 的 XLM-R 支持（幂等，可用 --revert 撤销）
docker exec embed_build python3 /workspace/setup_xlm_roberta.py

# Embedding：各静态档 + 动态档
docker exec embed_build bash -lc 'cd /workspace && \
  llm_convert.py -m ./tpuc/Qwen3-Embedding-0.6B -s 512  -c bm1684x2 -q bf16 --num_core 4 --out_dir /workspace/out_seq512'
# … 1024 / 2048 / 4096 同理；动态档加 --dynamic -s 8192

# Reranker：权重（ModelScope 比 HF 快 15 倍）
docker exec embed_build python3 /workspace/dl_rerank.py
docker exec embed_build bash -lc 'cd /workspace && \
  llm_convert.py -m ./weights/bge-reranker-v2-m3 -s 512 -c bm1684x2 -q bf16 --num_core 4 --out_dir /workspace/out_rr_seq512'
```

### 11.2 板上测量

```shell
# 送到板上
scp -P 10157 tools/embed/aux_seq_sweep.py linaro@172.26.166.96:/data/mys2702/bin/

# Embedding 全长扫描（各档耗时 + 互比余弦）
PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor python3 bin/aux_seq_sweep.py \
  --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
  --kind embed --config /opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding \
  --reference static2048 --model static2048=… --model dyn8192=… --repeats 10 \
  --json /data/mys2702/embed_sweep.json

# Reranker（**一次只跑一个档**：多个档在同一进程里走完会段错误，见 §5.4）
PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor python3 bin/aux_seq_sweep.py \
  --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
  --kind rerank --config /opt/sophgo/cv84x6_llm_server/model-config/bge_reranker_v2_m3 \
  --reference rr2048 --model rr2048=… --repeats 10

# NPU 占用
python3 bin/mem_probe.py --lib … --kind embed --model s512=… --model s2048=…
```

### 11.3 HF 参考（构建容器，需要 torch）

```shell
docker exec embed_build python3 /workspace/aux_hf_reference.py \
  --kind embed --model /workspace/tpuc/Qwen3-Embedding-0.6B \
  --sweep /workspace/aux_seq_sweep.py --json /workspace/hf_embed.json
docker exec embed_build python3 /workspace/aux_hf_reference.py \
  --kind rerank --model /workspace/weights/bge-reranker-v2-m3 \
  --sweep /workspace/aux_seq_sweep.py --json /workspace/hf_rerank.json
```

原始输出在 [`../../analysis/raw/mys2702/`](../../analysis/raw/mys2702/)，
包含挂死现场的 `dmesg` 摘录。

## 12. 待办（不阻塞本报告的结论）

1. **`rerank_engine.cpp` 缺动态发射路径**：这是动态 rerank 打死 NPU 的推断根因。
   若将来要做动态 rerank，先补这条路径并在非生产板验证。
   相关：`embed_engine.cpp:97-119` 有 `launch_dyn()` 可参照。
2. **rerank logit 偏差 0.07–0.80 的来源**（§5.2）：需要逐层对拍分清楚是
   bf16 累积误差还是 padding 语义不等价。
3. **「rerank 偏差不改变 top-k 顺序」这一推断未实测**（§5.2）：
   需要在真实知识库上做一致性对拍才能确认。
4. **多档自动选档**（§7.2）：若采纳 static512 + static2048 双档，
   需要一层按 token 数路由的逻辑，否则要用户手动指定模型。
5. **`docs/aux-models.md:45` 的「2048」**：若上线新档位需同步更新。
6. **Embedding 精度的正确对拍方式未落地**（§3.3）：必须比对**同一组 token id**
   （用服务的 `tokenizer.json` 生成 ids，关掉模板后处理），而不是同一段文本 ——
   后者会因为两侧分词差一个 token 而给出 0.73–0.90 的假数字。
   已确认同 id 下是 **0.9999**，但 7 个长度的完整表未跑。
   `aux_vs_hf.py` 需要按这个方式改写（`diag_ab.json` 是手工做的对照）。
