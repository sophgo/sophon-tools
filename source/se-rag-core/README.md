# se-rag-core

SE 系列知识库的 **Go RAG 检索核心**，替代现行 Python 栈（numpy / faiss-cpu / rank_bm25 / jieba）。
稳定静态二进制、启动快、内存占用低，适合默认部署到 SE 设备；支持 x86_64 本机构建 + arm64 交叉编译。

## 特性

- **混合检索**：向量语义检索（FAISS 暴力内积，L2 归一化）+ BM25 关键词检索 → RRF 融合（k=60）→ Reranker 精排
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
│   ├── chunker/         Markdown 分块（800 token / 80 overlap，保护代码块/表格）
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
用户自备 key 时：

```bash
export SE_RAG_EMBED_KEY="sk-user-embedding-key"
export SE_RAG_RERANK_KEY="sk-user-rerank-key"
./bin/se-rag build --docs-dir example/se7/docs -index-dir ./rag-data -builtin-key=false
./bin/se-rag query -index-dir ./rag-data "问题" -builtin-key=false
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
- 5xx / 429 / 连接错误（超时、DNS 失败）→ 有界重试（最多 6 次）并轮转至 CF 备网关；4xx 快速失败不转移
- 备用 CF 网关的「IP 优先 + DoH 兜底」拨号依赖硬编码的 Cloudflare Anycast IP 与公共 DoH 服务器
  （cf IP 段调整或 DoH 不可达时备路径失效；此时 FC 主网关走系统 DNS 不受此影响）
- 故障转移链可配置：`Provider.BaseURL`（主）+ `Provider.FallbackBaseURL`（备，默认 CF 网关）；
  两者相同即显式禁用故障转移；`se-rag` CLI 默认即启用
- 用户自备 key 不经网关，直达官方 SiliconFlow，无故障转移项

## 多知识库扩展

不同知识库用不同 `-index-dir` / `--docs-dir` 即可，无 `-product` 维度。新增 `se8` 知识库：

```bash
mkdir -p docs/se8
# 放入 se8 产品手册 / SDK 文档
./bin/se-rag build --docs-dir docs/se8 -index-dir ./rag-se8
./bin/se-rag query -index-dir ./rag-se8 "se8 问题" -top-n 8
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

## 对外接口（供 skill 调用）

`se-rag query "<问题>" -index-dir <dir> -top-n N` 输出紧凑 Markdown，
每条结果头部标注 `源文件相对路径:行号区间`，格式与 Python 版 `query.py` 一致（来源文件:行号、相关性分数、文本摘要、耗时）。skill 层可直接用 subprocess 调用。