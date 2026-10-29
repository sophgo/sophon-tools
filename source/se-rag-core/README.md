# se-rag-core

SE 系列知识库的 **Go RAG 检索核心**，替代现行 Python 栈（numpy / faiss-cpu / rank_bm25 / jieba）。
稳定静态二进制、启动快、内存占用低，适合默认部署到 SE 设备；支持 x86_64 本机构建 + arm64 交叉编译。

## 特性

- **混合检索**：向量语义检索（内存暴力内积，L2 归一化）+ BM25 关键词检索 → RRF 融合（k=60）→ Reranker 精排
- **A/B 双路径**：
  - 路径 A（在线，主路径）：embedding 供应商向量化 → 向量 + BM25 → RRF → rerank
  - 路径 B（BM25 兜底）：无 key / 断网 / embedding 失败时自动降级为纯 BM25，保证开箱即用、离线可用
- **多知识库兼容**：不同知识库用不同 `-index-dir` / `--docs-dir` 即可，复用同一检索核心仅换目录
- **供应商可切换**：siliconflow / sophnet 两族 embedding 与 reranker，可配置不写死
- **内置默认 key（混淆内嵌）**：预置 siliconflow 免费 key，源码中以 XOR 混淆字节内嵌（不落明文）；模型固定 `BAAI/bge-m3`（embedding）与 `BAAI/bge-reranker-v2-m3`（rerank）；使用内置 key 时强制限流（并发≤1、单次≤2段落）；用户自备 key 放开
- **内置网关故障转移链**：内置 key 请求经自建网关转发 SiliconFlow——主网关阿里云函数计算（FC3.0）同协议网关（`*.fcapp.run`，国内直连免备案）不可达（连接超时 / 5xx / DNS 失败）时自动切换备用 Cloudflare Worker 网关（`*.workers.dev`，对 DNS 污染走 IP 优先 + DoH 兜底拨号）；两网关均不可达时降级纯 BM25（见下文「内置网关故障转移链」）
- **供应商切换校验**：索引记录 embedding 指纹（`<provider>.<model>@<dim>`），切换供应商/模型后 `se-rag doctor` 检测并提示重建
- **检索输出含来源信息**：每条结果标记源文件的相对路径与片段行号区间
- **中文分词（BM25 兜底召回）**：汉字序列按 2-gram 滑窗切分（无词典、纯 Go 静态实现），
  查询/文档片段重叠即可命中（"如何配置网络" 可命中仅含 "配置网络" 的文档）；英文/数字保持单词 token
- **纯 Go，静态链接，零 C 依赖**：`CGO_ENABLED=0`，无 pip / aarch64 wheel 依赖

## 目录结构

```
source/se-rag-core/
├── cmd/se-rag/          CLI（build / query / doctor）
├── internal/
│   ├── chunker/         Markdown 分块（按标题切块；`*-faq.md` 一问一块，手册类相邻小节打包；见「分块策略」）
│   ├── vector/          暴力内积向量索引 + L2 归一化 + gob 持久化
│   ├── bm25/            BM25Okapi + 中英分词（中文 2-gram）+ 倒排 + gob 持久化
│   ├── embed/           Embedding / Reranker provider 抽象 + siliconflow/sophnet + 限流 + 重试
│   ├── fusion/          RRF 融合
│   ├── docstore/        索引持久化 + 指纹元信息
│   ├── retriever/       混合检索编排 + A/B 降级
│   └── config/          产品/供应商配置
├── example/se7/docs/    示例文档库（se7）
├── go.mod / go.sum
└── release.sh           统一构建接口（arm64 / amd64 / all）
```

## 构建

### 本机构建（x86_64）

```bash
cd source/se-rag-core
go build -o bin/se-rag ./cmd/se-rag
```

### 交叉编译（arm64）

```bash
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o bin/se-rag-arm64 ./cmd/se-rag
```

### 统一 release.sh（对齐 sophon-tools M1 规范）

```bash
bash release.sh all 1.0.0        # 同时产出 arm64 + amd64
bash release.sh arm64 1.0.0      # 仅 arm64
# 产物目录（可用 OUTPUT_DIR 覆盖，默认 <repo>/output/se-rag-core/）
```

## 使用

### 1. 建索引

```bash
# 真实 embedding（内置 siliconflow key，带限流）
./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data

# 离线假 embedding（无网络验证全链路，SE_RAG_FAKE_EMBED 内部开关）
SE_RAG_FAKE_EMBED=1 ./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data
```

> `build` 始终根据 docs **全量重建**索引（docs 是唯一真源）。切换供应商/模型后会带上新指纹重建，无需显式 force。

### 2. 查询

```bash
# 在线路径 A（真实 embedding），返回每条含源文件相对路径:行号区间
./bin/se-rag query -index-dir ./rag-data -top-n 8 "SE7 如何配置网络"

# 离线检索：不联网、不要求 key，纯 BM25（不外发查询内容；mode=bm25）
./bin/se-rag query -offline -index-dir ./rag-data "SE7 如何配置网络"

# 路径 B 兜底会自动触发：无 key / 断网 / embedding 失败时降级为 BM25
```

查询结果示例（每条头部 `源文件相对路径:行号区间`）：

```
### 1 [0.033] `00-introduce.md:1-26`
### 2 [0.032] `sdk-usage.md:1-40`
```

### 3. 检查供应商指纹 / 是否需要重建

```bash
./bin/se-rag doctor -index-dir ./rag-data
# 输出示例：
#   index  fp    : siliconflow.BAAI/bge-m3@1024
#   index  dim   : 1024
#   current fp    : siliconflow.BAAI/bge-m3@1024
#   chunk count  : 40
#   fingerprint OK: no rebuild needed
# 指纹比对含 provider/model/维度：切换供应商或模型后输出 WARNING 并提示重建
```

## 供应商配置

默认（`config.DefaultConfig`）使用 siliconflow + 内置混淆 key，模型 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`。
用户自备 key 时（flag 写在问题文本之前或之后均可；位置参数之后的 flag 自 1.1.0 起生效，
1.0.0 及更早写在后面会被静默忽略）：

```bash
export SE_RAG_EMBED_KEY="sk-user-embedding-key"
export SE_RAG_RERANK_KEY="sk-user-rerank-key"
./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data -builtin-key=false
./bin/se-rag query -builtin-key=false -index-dir ./rag-data "问题"
```

- 内置 key 启用的限流：并发 ≤ 1、单次 ≤ 2 段落（**进程内信号量**——单进程内有效；
  多进程并发调用 se-rag 时，各进程独立限流，网关侧总体并发不受本限流约束）
- 用户自备 key（`-builtin-key=false`）：放开限流；此时 key 必须由 `SE_RAG_EMBED_KEY` /
  `SE_RAG_RERANK_KEY` 环境变量提供，缺失即报错退出（不静默回落内置 key）
- 供应商切换（siliconflow ↔ sophnet）后，重建会用新指纹覆盖旧索引；用 `doctor` 校验

> **关于内置 key**：「混淆内嵌」是**伪保护**：内置 key 以 XOR 单字节掩码（0x5A）混淆字节存于
> 源码（密文与解码逻辑同文件），持有源码或二进制者可一键还原明文，不能视为机密。
> 其安全模型真正依赖**网关侧护栏**（模型白名单 + 限流 + 免费额度），网关侧白名单/配额/
> 吊销机制是否真实存在需向部署运维确认（仓库代码无法自证）。生产/共享部署应通过
> `SE_RAG_EMBED_KEY` / `SE_RAG_RERANK_KEY` 环境变量注入自备 key（也即放开限流），
> 切勿在公共镜像或日志中泄露内置 key。

## 内置网关故障转移链

内置 key 的上游链路为「网关 → SiliconFlow 源站」，网关承担鉴权与模型白名单（仅两模型）。为消除单点，
内置网关部署了两份同协议镜像，请求按有序列表轮转、失败自动切换：

| 优先级 | 网关 | 地址 | 说明 |
|--------|------|------|------|
| 1 | 阿里云函数计算 FC3.0（主） | `se-rag-gateway-chrzlcfiqt.cn-hangzhou.fcapp.run` | 国内直连免备案；`fcapp.run` 走系统 DNS，不受 IP 优先逻辑影响 |
| 2 | Cloudflare Worker（备） | `se-rag-gateway.zetao-zhang.workers.dev` | 对 `*.workers.dev` DNS 污染走 IP 优先 + DoH 兜底拨号，作用范围仅限该域名 |
| 3 | 纯 BM25（兜底） | — | 两网关均不可达时自动降级，离线可用（`mode=bm25`） |

行为约定：

- 同一 key / 同路径（`/v1/embeddings`、`/v1/rerank`）/ 同模型白名单，内置 key 零改动
- 5xx / 408 / 429 / 403 / 连接错误（超时、DNS 失败）→ 有界重试（最多 6 次）并轮转至 CF 备网关；
  401 / 400 / 404 快速失败不转移（这类错误换任何网关都一样复现）
- 403 参与转移的原因：网关侧欠费/配额耗尽、以及网关特有的上游拒绝都表现为 403，
  不像 401/400 那样能断定「换网关也一样」
- **熔断**：某网关失败后进入 60s 冷却，冷却期内后续请求直接跳过它（全部冷却时做一次半开探测）。
  内置 key 限流把 build 压成串行（约 950 次调用），没有熔断时主网关持续故障会把 1 次超时代价放大到 950 次
- 备用 CF 网关的拨号顺序为「硬编码 Anycast IP → DoH 实时解析」。两个硬编码 IP 只是起点：
  若出现 TLS 层失败（TCP 可连但握手失败，正是 CF 调整 anycast 段后的形态），
  静态 IP 会被标记可疑 10 分钟并改为 **DoH 优先**，避免反复命中坏 IP
- DoH 服务器按各自 JSON API 路径查询（Cloudflare `/dns-query`、Google `/resolve`），
  应答只采信 **Cloudflare 网段**内的地址——被污染的公共 DoH（实测阿里 223.5.5.5）对
  `*.workers.dev` 返回伪造 IP，不加这层过滤会把伪造地址当作权威记录去拨号
- `query` 输出新增 `gateway: <host>` 行，直接显示本次检索实际命中的网关，不需要再从外部推测
- **硬失败短路**：TLS RST/EOF、代理拒绝（`proxyconnect`/`502`）、连接被拒，都判定为
  「重试同一地址必然同样失败」，整条链跳过该网关，不再反复空试。这类形态下重试毫无收益——
  实测一次查询在降级前空等 65 秒（静默黑洞形态甚至撞满 query 的 120s 上限）
- **转移总预算 12s**：`SE_RAG_FAILOVER_BUDGET` 可覆盖（如 `30s`）。到点即认输降级，
  单次尝试也被同一 deadline 约束，不会因为一次 10s 级握手超时把总耗时撑到预算的倍数
- **端口降级**：`443` 上按 SNI 定向阻断时，Cloudflare 对同一 Worker 还开放
  `2053/2083/2087/2096/8443`（实测均可正常返回向量）。`*.workers.dev` 网关首次 TLS 硬失败后，
  自动换到首个备用端口重试一次——**无需自有域名即可恢复第二跳**。其它网关（如 `fcapp.run`）
  没有这套端口，不参与降级
- 故障转移链可配置：`Provider.BaseURL`（主）+ `Provider.FallbackBaseURL`（备，默认 CF 网关）；
  两者相同即显式禁用故障转移；`se-rag` CLI 默认即启用
- 环境变量覆盖（改链路不必重新编译）：`SE_RAG_GATEWAY_URL` 改主网关，
  `SE_RAG_FALLBACK_URL` 改备网关——指向自有域名（绑定 Custom Domain 后）或置空=单跳止血
- **明文 HTTP 兜底（保第二跳）**：阻断若按 TLS SNI 匹配，则明文请求根本没有 SNI 可匹配，
  因而穿得过去。`*.workers.dev` 网关的 TLS 通道（443 与全部备用 HTTPS 端口）判定不可用后，
  自动改走 `http://<host>:80` 再试一次。实测该通道返回合法 1024 维向量。
  `SE_RAG_ALLOW_HTTP_FALLBACK=0` 可关闭。
  > ⚠️ **安全权衡**：明文 HTTP 下内置 key 与查询文本在链路上不加密（内容仍受 TLS 之外
  > 的传输路径保护，但**不具备机密性**）。内置 key 只是网关侧的临时凭证、真 key 留在
  > 网关，泄露面有限；但若你的部署对传输机密性有硬要求，请置 `SE_RAG_ALLOW_HTTP_FALLBACK=0`，
  > 此时 SNI 全端口阻断的环境会退化为降级 BM25。更彻底的方案仍是绑定 Custom Domain
  > （见下）让 SNI 不再命中被封锁的模式。
- 转移链总预算：`SE_RAG_FAILOVER_BUDGET`（默认 18s = 明文兜底预留 12s + TLS 余量 6s）
- **熔断与粘滞跨进程持久化**：状态存于 `$SE_RAG_STATE_DIR`（默认用户缓存目录下的
  `se-rag/gateway-breaker.json`）。这一点对支撑 agent 很关键——它们每次查询都是独立 CLI
  进程，纯内存熔断等于没有：实测每次查询都要重付一遍失效链路的代价。落盘后，
  上次成功的通道（含运行时降级出的 `:80`）会被记住并优先复用，实测连续 4 次查询
  从 14.3s 收敛到 2.5s。粘滞有效期 `preferTTL` = 10 分钟，过期或失败即重新探测。
- 用户自备 key 不经网关，直达官方 SiliconFlow，无故障转移项

## 多知识库扩展

不同知识库用不同 `-index-dir` / `--docs-dir` 即可，无 `-product` 维度。新增 `se8` 知识库：

```bash
mkdir -p docs/se8
# 放入 se8 产品手册 / SDK 文档
./bin/se-rag build --docs-dir docs/se8 -index-dir ./rag-se8
./bin/se-rag query -index-dir ./rag-se8 -top-n 8 "se8 问题"
./bin/se-rag doctor -index-dir ./rag-se8
```

索引直接落盘到各自 `-index-dir/`（`meta.json` + `vectors.gob` + `bm25.gob` + `chunks.gob` +
`.complete` 完成标记），各知识库互不影响，可并存。保存为原子写入：先写临时文件、移除旧
完成标记、再 rename 替换、最后写回完成标记，构建中断只可能留下"无标记"状态而不会是半套
/混合代索引；`.complete` 或 `bm25.gob` 缺失时 query 显式报错并提示重建。
注意：本版本之前的旧索引目录（无 `.complete`）升级后需重新 `se-rag build` 一次。

## 测试

```bash
cd source/se-rag-core
go test ./...        # 单测（无网络）
go vet ./...
```

## 分块策略

所有 Markdown 按标题（`#` ~ `####`，围栏代码块内的 `#` 不算）切块，策略版本 `heading-v3`：

- **问答文档**（文件名以 `-faq.md` 结尾，如 `10-media-faq.md`）：每个小节（一个问答）独立成块，无论多短。
- **手册 / README 等其他文档**：相邻的小节打包到约 1800 字符一块（不越过 `#` 一级标题；当前块很小时可以越过）。
  API 手册每个接口下有"接口形式 / 参数说明 / 返回值…"一串很短的小节，单独成块只有几十个字，既没有检索价值又会让索引膨胀数倍。
- 块文本以 `【祖先标题1 › 祖先标题2】` 开头，让只含"参数说明"这类通用标题的块也带着所属主题；`LineStart/LineEnd` 仍是原文行号，不含该前缀。
- 超过 2400 字符的小节在行边界处二切：优先空行，其次强制；续块重复小节标题，表格被切开时续块重复表头；不再有 6000 字符的"硬切"块。
- 不单独成块的内容：只有标题没有正文、**且下一个标题更深**的小节（标题已在后代的祖先路径里；下一个标题同级或更浅时标题无处可去，仍会成块）、只有 frontmatter 的前言、`目录` / `Contents` 小节（自动生成的目录会命中几乎任何查询）。
  `目录` 小节是**逐行判定**后才丢弃的：小节里只要有一行不是目录条目，整节按普通小节保留成块。真实语料里有小节标题叫"目录"、内容却是本章导语（"C 接口详细介绍请阅读…"、"本章主要介绍…"）的文档，无条件丢弃会让这些导语离开索引、无法检索。
  目录条目 = 锚点链接（`- [标题](#锚点)`）/ 点线引导页码（`1 安全 ..... 1`）/ 列表项或编号短标题（`3.7.8 小数据包吞吐量不足导致丢包`）/ 很短且不带句读符号的行（`前言`）；引用块、表格行、代码围栏、带句读的长句都算正文。

效果（真实 bge-m3 + reranker，top8，MRR）：

| 评测集 | 旧分块 | 本策略 |
| --- | --- | --- |
| SE9 FAQ，29 题·口语 | 0.800 | 0.935 |
| SE9 FAQ，29 题·关键词 | 0.758 | 0.901 |
| SE7 手册 / README，25 题·口语 | 0.613 | 0.730 |
| SE7 手册 / README，25 题·关键词 | 0.727 | 0.786 |

FAQ 提升最大：旧分块把几个短问答合并进同一块，向量检索几乎失效（向量单路 MRR 0.32 → 0.80）。局限：查询由人工撰写，样本小。

索引 `meta.json` 的 `chunk_strategy` 记录策略版本。旧索引没有该字段：`doctor` 报告需要重建，`query` 向 stderr 提示 `rebuild recommended`；重建即可，`docs` 无需改动。块数比 `faq-heading-v1` 多约 60%（hub 现有 docs 实测 SE7/SE8/SE9 = 1682/1710/2186，旧策略 1037/1062/1340），单产品 build 约 3 分钟，`buildTimeout` 为 15 分钟。`heading-v3` 相对 `heading-v2` 只多 3 个块（5575 → 5578）。

## 对外接口（供 skill 调用）

`se-rag query -index-dir <dir> -top-n N "<问题>"` 输出紧凑 Markdown，
每条结果头部标注 `源文件相对路径:行号区间`，格式与 Python 版 `query.py` 一致（来源文件:行号、相关性分数、文本摘要、耗时）。skill 层可直接用 subprocess 调用。