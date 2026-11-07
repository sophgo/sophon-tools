# se-rag-core

SE 系列知识库的 **Go RAG 检索核心**，替代现行 Python 栈（numpy / faiss-cpu / rank_bm25 / jieba）。
稳定静态二进制、启动快、内存占用低，适合默认部署到 SE 设备；支持 x86_64 本机构建 + arm64 交叉编译。

## 特性

- **混合检索**：向量语义检索（内存暴力内积，L2 归一化）+ BM25 关键词检索 → RRF 融合（k=60）→ Reranker 精排
- **标识符—标题精确匹配提权**：查询里含标识符（寄存器名 / 函数名 / 命令名，如 `rtc_ctrl_status1`、`build_kernel`）时，**以该标识符命名的那一节**作为第三路（权重 2）参与 RRF，压过只在正文里提到它的概览表；无标识符的查询结果与旧版逐字节一致（见「标识符—标题精确匹配提权」）
- **注册表驱动**：`registry.json` 是实体（产品 / 模组 / 芯片）的唯一真源——按实体建索引、按别名解析问题、
  跨实体合并检索（见「注册表与多索引检索」）；旧路径模式 `--docs-dir` / `-index-dir` 保持兼容
- **A/B/C 三条路径**：
  - 路径 A（在线，主路径）：embedding 供应商向量化 → 向量 + BM25 → RRF → rerank
  - 路径 B（BM25 兜底）：无 key / 断网 / embedding 失败时自动降级为纯 BM25，保证开箱即用、离线可用
  - 路径 C（离线索引）：`build -offline` 建出的纯 BM25 索引，查询**根本不构造 embedder**，
    查询文本从不离开进程；用于含内部内容、不得外发的资料
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
├── cmd/se-rag/          CLI（list / resolve / build / query / doctor）
├── internal/
│   ├── registry/        registry.json 读取与校验（实体、别名解析、关联展开）
│   ├── chunker/         Markdown 分块（按标题切块；`*-faq.md` 一问一块，手册类相邻小节打包；见「分块策略」）
│   ├── vector/          暴力内积向量索引 + L2 归一化 + gob 持久化
│   ├── bm25/            BM25Okapi + 中英分词（中文 2-gram）+ 倒排 + gob 持久化
│   ├── embed/           Embedding / Reranker provider 抽象 + siliconflow/sophnet + 限流 + 重试
│   ├── fusion/          RRF 融合（支持多路加权）
│   ├── ident/           标识符提取（含下划线、去下划线后 ≥4 字符）
│   ├── titlematch/      标识符—分块标题精确匹配（第三路排名）
│   ├── docstore/        索引持久化 + 指纹元信息
│   ├── retriever/       混合检索编排 + A/B 降级 + 多索引合并
│   └── config/          产品/供应商配置
├── example/se7/docs/    示例文档库（se7）
├── example/registry.json 示例注册表（复用 example/se7，演示注册表模式）
├── cmd/se-rag/testdata/ 测试夹具（夹具 registry.json + golden 输出）
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
bash release.sh all 1.8.0        # 同时产出 arm64 + amd64
bash release.sh arm64 1.8.0      # 仅 arm64
# 产物目录（可用 OUTPUT_DIR 覆盖，默认 <repo>/output/se-rag-core/）
```

## 使用

### 1. 建索引

```bash
# 真实 embedding（内置 siliconflow key，带限流）
./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data

# 纯 BM25 离线索引：不构造 embedder、不读 key、不联网（dim=0，search_mode=bm25）
./bin/se-rag build -offline --docs-dir example/se7/docs -index-dir ./rag-data

# 离线假 embedding（无网络验证全链路，SE_RAG_FAKE_EMBED 内部开关）
SE_RAG_FAKE_EMBED=1 ./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data
```

三种模式的差别（含取舍）：

| | `build` | `build -offline` | `SE_RAG_FAKE_EMBED=1` |
| --- | --- | --- | --- |
| 构造 embedder | 是（走网络） | **否** | 是（fake，不发网络） |
| 需要 key | 是 | **否** | 否 |
| `dim` | 真实维度 | **0** | 2 |
| `embedder_fingerprint` | `provider.model` | **`bm25`** | 真实 provider 名（伪装） |
| `search_mode` | `hybrid` | **`bm25`** | `hybrid` |
| 用途 | 生产混合检索 | 生产离线检索 | 仅链路验证 |

`-offline` 与 `SE_RAG_FAKE_EMBED` **不是等价物**：fake 模式会把 dim=2 的假向量写进索引、指纹仍写真实
provider 名，索引看起来"正常"但检索质量是空的；`-offline` 明确写 `dim=0 / fingerprint=bm25`，
不含任何伪装成真实向量的数据。需要"不外发任何文本"的生产场景只能用前者。

离线索引里空向量是**合法**的（本来就没有向量），但空 BM25 或缺 chunks 仍是不完整索引，会显式报错。

> `build` 始终根据 docs **全量重建**索引（docs 是唯一真源）。切换供应商/模型后会带上新指纹重建，无需显式 force。

### 2. 查询

```bash
# 在线路径 A（真实 embedding），返回每条含源文件相对路径:行号区间
./bin/se-rag query -index-dir ./rag-data -top-n 8 "SE7 如何配置网络"

# 离线检索：不联网、不要求 key，纯 BM25（不外发查询内容；mode=bm25）
./bin/se-rag query -offline -index-dir ./rag-data "SE7 如何配置网络"

# 路径 B 兜底会自动触发：无 key / 断网 / embedding 失败时降级为 BM25
# 路径 C：索引本身是 bm25（build -offline 产出）→ 直接纯 BM25，不构造 embedder，
#        结果末行 fallback: index is bm25-only（此时加不加 -offline 都不会联网）
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

离线索引（`search_mode=bm25`）输出 `search mode : bm25`、`current fp : (none: bm25-only index has no
embedding fingerprint)` 与 `bm25 index OK: no rebuild needed`，不会拿 `bm25@0` 去比对 `bge-m3@1024` 而误报。

### 4. 注册表模式（示例）

`example/registry.json` 复用 `example/se7`，可直接试：

```bash
cd example
../bin/se-rag list                        # 列出实体与索引状态
../bin/se-rag build -all -offline         # 按实体建索引（示例里只有 se7 是 ready）
../bin/se-rag query -entity se7 -offline "网络怎么配"
../bin/se-rag resolve "SE7 32-BP1 的 I2C"  # 别名最长匹配
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
  **标记 24 小时自动刷新**：状态文件带 `stamp_ns` 生成时间，超过 24 小时整份作废并
  在下次写入时重新生成（`SE_RAG_STATE_TTL` 可覆盖）。这是比单条 TTL 更外一层的兜底——
  冷却管 60s、粘滞管 10min，都只管「条目」；标记管「整份状态还能不能代表当前网络」。
  无 `stamp_ns` 的旧版文件、以及时钟回拨到未来的标记，同样按过期处理。
  注意进程启动只读不写：只有真正产生路由判断（成功/失败）时才落盘，
  因此 `--help`、离线查询、以及仅启动进程都不会凭空创建状态文件。
- 用户自备 key 不经网关，直达官方 SiliconFlow，无故障转移项

## 注册表与多索引检索

技能根目录的 `registry.json` 是实体（产品 / 模组 / 芯片）的唯一真源：别名、文档目录、索引目录、
关联关系、边界都在这里。CLI 通过 `-registry`（默认 `./registry.json`）读取它，注册表里的路径
一律相对 `registry.json` 所在目录。

schema version 3 的关系是**四层**：`product.modules → module.chips → chip.sdk →
sdk.versions`。产品不再直接挂芯片；芯片通过 `chip.sdk` 指向 sdk 实体，`chip.sdk_since`
标注该芯片从哪个 SDK 版本起被支持。SDK 的文档与索引挂在**版本**上（每个版本一套索引），
所以 sdk 实体自身是 `placeholder`。

SE9 的 16 路 / 8 路是**规格**（`product.specs`）而不是独立实体：SE9 是一个实体，
两种路数只是规格不同，所以规格没有 id，不进入实体命名空间，`-entity` 也不接受规格名。
版本同理：`versions[].slug` 是定位键，不是实体 id，也不能单独当 `-entity` 用
（要写 `<sdk-id>@<slug>`）。

```bash
# 列出实体与索引状态（规格缩进列在产品下，标注共用的索引）
./bin/se-rag list                       # 人类可读
./bin/se-rag list -json                 # 结构化输出

# 从自然语言里解析实体（别名最长匹配；大小写、空格、连字符、下划线不敏感）
./bin/se-rag resolve "SE9 8-BP1-17 怎么装 sail"
#   se9 product ready alias="SE9 8-BP1-17" spec="SE9 8" chips=cv186ah related=bm1688 skipped=sm9-16,sm9-8,cv186ah
./bin/se-rag resolve "SM9 16"
#   sm9-16 module placeholder alias="SM9 16" related=bm1688 skipped=sm9-16 used_by=se9
./bin/se-rag resolve "use 7 days"       # 词边界：不命中 SE7（见下）

# 按实体建索引（-all 覆盖全部 ready 实体 + sdk 的全部版本；placeholder 没有资料，不参与）
./bin/se-rag build -entity se9
./bin/se-rag build -entity se9,bm1688 -offline
./bin/se-rag build -all
# 规格不是实体：-entity se9-8 / "SE9 8" 会报 unknown entity，提示改用 -entity se9

# sdk 默认只建/查最新版本；-sdk-version 可指定 slug 或 all，也可写 <sdk>@<slug>
./bin/se-rag build -entity sophonsdk-edge                   # 最新版本
./bin/se-rag build -entity sophonsdk-edge -sdk-version all   # 全部版本
./bin/se-rag build -entity sophonsdk-edge@v2.2               # 指定版本

# 按实体检索；-with-related 展开关联（产品 → 模组 → 芯片 → sdk 版本）
./bin/se-rag query -entity se9 -with-related "I2C 怎么接"
./bin/se-rag query -entity se9 -with-related -doc-type sdk "sophon-sail 安装"
./bin/se-rag query -entity sophonsdk-edge -sdk-version v2.2 "sophon-sail"
./bin/se-rag query -all -top-n 10 "OTA 升级"

# 逐实体体检
./bin/se-rag doctor -all
```

### 关联展开（-with-related）

按"产品 → 模组 → 芯片 → sdk → sdk 版本"遍历（产品最后再加 toolkits），去重保序。
**规格不影响检索目标**：

- **placeholder 参与遍历，但不进入检索目标。** 例如 `sm9-8`（模组，placeholder）→
  `cv186ah`（芯片，placeholder）→ `sophonsdk-edge`（sdk，placeholder，因为索引在版本上）：
  链一路走到底，检索目标是同系列 SDK 的版本（如 `sophonsdk-edge@v2.3`），
  跳过的实体照常提示。
- **sdk 默认只取最新版本**（按 `versions[].release_date` 排序，不看版本号大小）。
  `-sdk-version <slug>` 指定版本，`all` 取全部版本。
- **`chip.sdk_since`**：所选版本早于该芯片支持的起始版本时跳过并提示
  （如 `cv84x6` 标了 `sdk_since: v2.3`，查 `all` 时只保留 v2.3 及以后）。
- 产品按 `product.modules` 展开全部模组——SE9 的两种规格最终都落到同一对索引
  （`se9` + `bm1688`），所以问 `SE9 8-BP1-17` 与问 `SE9` 的检索范围完全相同。
- 只命中产品（只说 `SE9`）时额外列出规格对照：
  `note: se9 specs: SE9 16 (sm9-16 → bm1688) | SE9 8 (sm9-8 → cv186ah); ask which one if the answer depends on chip`
- 命中模组（`SM9 16`）：模组 → 芯片 → sdk 版本，**不反向展开到产品**；
  `resolve` 输出里另给 `used_by=`，列出使用该模组的产品，供 Agent 参考。
- 命中规格别名（`SE9 8-BP1-17`、`SE9 16`）时实体仍是 `se9`，另附
  `spec="SE9 8" chips=cv186ah`，供 Agent 判断芯片级数值该用哪颗芯片。
- 命中 sdk 或带 sdk 的芯片时，`resolve` 一并给出版本列表并标出本次检索目标
  （`search targets: sophonsdk-edge@v2.3`）。

### SE_RAG_DATA_DIR：索引改落点

设置 `SE_RAG_DATA_DIR=<目录>` 后，所有实体的索引（含 sdk 各版本）改落到
`<目录>/<index_dir 的末级目录名>`；文档目录不动。用于技能目录只读、或多个 agent 共享
一份只读技能副本的场景。`list` / `doctor` / `build` 输出都会显示实际落点
（`list -json` 里是 `index_at` 与 `versions[].index_at`）。

### 别名的词边界

别名匹配在归一化后的文本上进行（转小写、去掉空格 / `-` / `_`），但命中位置会映射回原文，
要求原文中命中片段的前后字符都不是 ASCII 字母或数字——中文、标点、空格与文本首尾都算边界。

没有这一步时，`use 7 days` 去空格后会变成 `use7days`，其中的 `se7` 就会误命中 SE7；
`case8` 同理会误命中 SE8。加上词边界后：

| 输入 | 结果 |
| --- | --- |
| `SE9 16-BP1-11 怎么装` | 命中完整型号别名（解析到 se9，规格 `SE9 16`） |
| `SE916 规格` | 命中规格别名 `SE9 16`（解析到 se9） |
| `SE9的I2C` | 命中 `se9`（中文算边界） |
| `use 7 days` | 不命中 |
| `case8` | 不命中 |

### -doc-type 过滤

按块的**源路径**推断文档类型，不改文档内容、不改索引格式——同一份索引既能全量检索，
也能只检索某几类文档。文档写了 frontmatter `doc_type` 时**以文档自述为准**，缺失时才看路径。

两种模式都可用，但推断基准不同：

| 模式 | 源路径基准 | 推断规则 |
| --- | --- | --- |
| 注册表模式（`-entity` / `-all`） | 技能根相对路径 | `docs/<layer>/<entity>/<doc_type>/…`；`00-introduce.md` → `overview`、`image-catalog.md` → `image`；`docs/modules/<id>/**` → `module`、`docs/sdks/<sdk>/<slug>/**` → `sdk` |
| 路径模式（`-index-dir`） | 相对 `--docs-dir` 的路径 | 第一层子目录名是合法类型即为该类型；根目录文件 → `overview`；`_meta/`、`assets/` 与不认识的第一层目录 → `other` |

注册表模式的完整映射（示例）：

| 路径 | doc_type |
| --- | --- |
| `docs/products/<id>/manuals/**` | `manual` |
| `docs/products/<id>/tools/**` | `tools` |
| `docs/products/<id>/*.md` | `faq` |
| `docs/chips/<id>/sdk/**` | `sdk` |
| `docs/chips/<id>/datasheet/**` | `datasheet` |
| `docs/modules/<id>/**` | `module` |
| 其余 | `other` |

```bash
# 注册表模式：结果行在实体标注后追加 doc_type
./bin/se-rag query -entity bm1688 -doc-type datasheet,sdk "内存带宽"
# ### 1 [0.033] `docs/chips/bm1688/datasheet/spec.md:3-6` [bm1688/datasheet]

# 路径模式：结果行在路径后追加 doc_type
./bin/se-rag query -offline -index-dir ./rag-data -doc-type datasheet,sdk "内存带宽"
# ### 1 [0.033] `datasheet/spec.md:3-6` [datasheet]
```

过滤发生在融合（RRF）之前：带过滤时每个索引先放大预取深度再按类型筛，避免被排除的块
占掉候选名额。**不带 `-doc-type` 时输出逐字节不变**——单索引结果只在 `-doc-type` 生效时才追加类型标注，
即使文档 frontmatter 自述了 `doc_type` 也一样（1.8.1 修正）；多索引结果的 `[实体id/doc_type 版本]` 标注规则照旧。
`-with-related`、`-sdk-version` 只在注册表模式（`-entity` / `-all`）下有效，路径模式下传入会直接报错。

**单索引行为不变**：目标是单个实体（没带 `-with-related`，或展开后仍只有一个）时，检索流程与输出
格式与路径模式逐字节一致（`cmd/se-rag/testdata/golden/` 里保存了改动前的 golden 输出做回归）。
旧命令 `build --docs-dir` / `query -index-dir` / `doctor -index-dir` 全部保留。

**多索引合并**（`-with-related`、`-entity a,b`、`-all`，或路径模式传多个 `-index-dir`）：

- 在线：每个索引先做常规 hybrid（向量 top20 + BM25 top20 + 标题精确匹配 → 加权 RRF）取前 20 条，
  **此阶段不 rerank**；按各索引排名轮转截取合并候选（上限 40 条）→ 统一 **rerank 一次** → 取 top-n。
- 离线（`-offline`、全部索引都是 `build -offline` 产出的 bm25-only，或 rerank 失败）：
  按各索引内排名做 RRF（k=60）合并；有标识符时叠加标题精确匹配这一路（权重 2）。
- 三路融合始终在**每个索引内部**先完成，再做跨索引合并。
- 结果每条标注 `[实体id]`，路径改为相对技能根目录（如 `docs/chips/bm1688/sdk/tpu-mlir.md:3-7`）；
  用了 `-doc-type` 时标注再追加 `/doc_type`（如 `[bm1688/datasheet]`）；路径模式没有实体信息，
  沿用原格式。
- 任一目标索引缺失直接报错，并给出对应的 `se-rag build -entity <id>` 命令，不静默只查已有的那几个。

实体模式建的索引，`meta.json` 的 `product` 字段写实体 id；路径模式仍写 `default`。

## 标识符—标题精确匹配提权

查一个寄存器名时，BM25 与向量都会把**寄存器概览表**排到前面：表里同类寄存器名成行出现，
内容相似度天然高于只有一张字段表的那个小节。结果是查 `rtc_ctrl_status1` 拿到概览表，
真正的字段表 `#### rtc_ctrl_status1（Offset 0x010）` 排不进前三。

标题命中是比内容相似度更强的意图信号——用户写下标识符，要看的就是以它命名的那一节。
因此融合时加入**第三路**排名：

1. **标识符提取**（`internal/ident`）：查询里满足「含 `_`，且去掉 `_` 后长度 ≥ 4」的
   ASCII token，大小写不敏感。`rtc_ctrl_status1`、`build_kernel`、`WDT_STAT` 是；
   `I2C`、`1080p`、中文、`sophon-sail`（连字符不是下划线）都不是。
2. **分块自身标题**（`chunker.SelfHeadings`）：取块正文里的标题行（`#`~`####`，围栏代码块内不算），
   **不含** heading-v3 加的 `【祖先 › 祖先】` 前缀。从标题里按同一套规则取标识符：
   `#### WDT_STAT（Offset 0x010）` → `wdt_stat`；`### 6.2 build_kernel（…）` → `build_kernel`。
   一个块可能打包多个小节（`6.1 build_fsbl` + `6.2 build_kernel` 同块），所以看**全部**标题行，
   而不是只看第一条。**全部在查询期从块文本推导，不改索引格式，已有索引不需重建。**
3. **排序与权重**（`internal/titlematch`、`fusion.RRFWeighted`）：命中块按「命中标识符个数降序 →
   标题越短越靠前 → 原块序」排序，最多 20 个候选；**即使它不在向量 / BM25 的 top20 里也加入候选**。
   这一路 RRF 权重为 **2**（其余两路为 1），`k=60`。

各模式行为一致：在线 hybrid、离线 BM25、`-doc-type` 过滤、多索引（每个索引内部先三路融合再合并）
都走同一套。rerank 仍在其后执行；rerank 若把命中块压下去，以 rerank 结果为准，不再干预。

**没有标识符的查询第三路为空**（零个名次），融合结果与旧版逐字节一致——`cmd/se-rag/testdata/golden/`
的 golden 回归锁住这一点。分数列在有提权时是加权 RRF 值，与纯 BM25 的分数不可直接比大小。

```bash
# 第一名是以该寄存器命名的字段表，而不是概览表
./bin/se-rag query -entity bm1688 -offline "rtc_ctrl_status1"
# 命令名同样生效
./bin/se-rag query -entity cv84x6 -offline "build_kernel 报错"
```

## 多知识库扩展

不同知识库用不同 `-index-dir` / `--docs-dir` 即可，无 `-product` 维度。新增 `se8` 知识库：

```bash
mkdir -p docs/se8
# 放入 se8 产品手册 / SDK 文档
./bin/se-rag build --docs-dir docs/se8 -index-dir ./rag-se8
./bin/se-rag query -index-dir ./rag-se8 -top-n 8 "se8 问题"
./bin/se-rag doctor -index-dir ./rag-se8
```

多个知识库要一起检索时，`-index-dir` 可重复传入或用逗号分隔（合并规则见上一节）：

```bash
./bin/se-rag query -index-dir ./rag-se7 -index-dir ./rag-se8 "两代产品的网络配置差异"
./bin/se-rag query -index-dir ./rag-se7,./rag-se8 "两代产品的网络配置差异"
```

如果这些知识库已经在 `registry.json` 里登记为实体，改用 `-entity` / `-all` 更省事——
目录、别名和关联关系都由注册表提供，不用每次手写路径。

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

注册表模式同一个命令换成 `-entity <id> [-with-related]`：单实体输出格式不变（逐字节一致），
多实体合并时结果行尾多一个 `[实体id]` 标注、路径改为相对技能根目录。

`se-rag list -json` / `se-rag resolve -json "<文本>"` 输出结构化 JSON，便于 skill 层按实体路由，
不必自己解析人类可读表格。