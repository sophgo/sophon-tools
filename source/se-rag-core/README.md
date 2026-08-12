# se-rag-core

SE 系列知识库的 **Go RAG 检索核心**，替代现行 Python 栈（numpy / faiss-cpu / rank_bm25 / jieba）。
稳定静态二进制、启动快、内存占用低，适合默认部署到 SE 设备；支持 x86_64 本机构建 + arm64 交叉编译。

## 特性

- **混合检索**：向量语义检索（FAISS 暴力内积，L2 归一化）+ BM25 关键词检索 → RRF 融合（k=60）→ Reranker 精排
- **A/B 双路径**：
  - 路径 A（在线，主路径）：embedding 供应商向量化 → 向量 + BM25 → RRF → rerank
  - 路径 B（BM25 兜底）：无 key / 断网 / embedding 失败时自动降级为纯 BM25，保证开箱即用、离线可用
- **多产品兼容**：产品文档库作为可配置输入，支持 se7 / se8 / se9 并存，复用同一检索核心仅换数据
- **供应商可切换**：siliconflow / sophnet 两族 embedding 与 reranker，可配置不写死
- **内置默认 key**：预置 siliconflow 免费 key，使用内置 key 时强制限流（并发≤2、单次≤3段落）；用户自备 key 放开
- **供应商切换校验**：索引记录 embedding 指纹（`<provider>.<model>@<dim>`），切换供应商/模型后 `se-rag doctor` 检测并提示重建
- **纯 Go，零 C 依赖**：`CGO_ENABLED=0`，无 pip / aarch64 wheel 依赖

## 目录结构

```
source/se-rag-core/
├── cmd/se-rag/          CLI（build / query / doctor）
├── internal/
│   ├── chunker/         Markdown 分块（800 token / 80 overlap，保护代码块/表格）
│   ├── vector/          暴力内积向量索引 + L2 归一化 + gob 持久化
│   ├── bm25/            BM25Okapi + 中英分词 + 倒排 + gob 持久化
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
./bin/se-rag build -product se7 --docs-dir example/se7/docs -index-dir ./rag-data

# 离线假 embedding（无网络验证全链路，SE_RAG_FAKE_EMBED 内部开关）
SE_RAG_FAKE_EMBED=1 ./bin/se-rag build -product se7 --docs-dir example/se7/docs -index-dir ./rag-data
```

> `build` 始终根据 docs **全量重建**索引（docs 是唯一真源）。切换供应商/模型后会带上新指纹重建，无需显式 force。

### 2. 查询

```bash
# 在线路径 A（真实 embedding）
./bin/se-rag query -product se7 -index-dir ./rag-data -top-n 8 "SE7 如何配置网络"

# 路径 B 兜底会自动触发：无 key / 断网 / embedding 失败时降级为 BM25
```

### 3. 检查供应商指纹 / 是否需要重建

```bash
./bin/se-rag doctor -product se7 -index-dir ./rag-data
# 输出示例：
#   index  fp    : siliconflow.BAAI/bge-m3@1024
#   index  dim   : 1024
#   current dim  : 1024
#   fingerprint OK: no rebuild needed
```

## 供应商配置

默认（`config.DefaultConfig`）使用 siliconflow + 内置免费 key。用户自备 key 时：

```bash
export SE_RAG_EMBED_KEY="sk-user-embedding-key"
export SE_RAG_RERANK_KEY="sk-user-rerank-key"
./bin/se-rag build -product se7 --docs-dir example/se7/docs -index-dir ./rag-data -builtin-key=false
./bin/se-rag query -product se7 -index-dir ./rag-data "问题" -builtin-key=false
```

- 内置 key 启用的限流：并发 ≤ 2、单次 ≤ 3 段落
- 用户自备 key（`-builtin-key=false`）：放开限流
- 供应商切换（siliconflow ↔ sophnet）后，重建会用新指纹覆盖旧索引；用 `doctor` 校验

> **关于内置 key**：源码内置的 siliconflow key 是免费额度、用于默认开箱即用的 throwaway key（限流，避免滥用）。
> 生产/共享部署应通过 `SE_RAG_EMBED_KEY` / `SE_RAG_RERANK_KEY` 环境变量注入自备 key（也即放开限流），
> 切勿在公共镜像或日志中泄露内置 key。

## 多产品扩展

产品作为独立目录与索引隔离，复用同一检索核心。新增 `se8`：

```bash
mkdir -p docs/se8
# 放入 se8 产品手册 / SDK 文档
./bin/se-rag build -product se8 --docs-dir docs/se8 -index-dir ./rag-data
./bin/se-rag query -product se8 -index-dir ./rag-data "se8 问题" -top-n 8
./bin/se-rag doctor -product se8 -index-dir ./rag-data
```

索引落盘到 `<index-dir>/<product>/`（`meta.json` + `vectors.gob` + `bm25.gob` + `chunks.gob`），
各产品互不影响，可并存。

## 测试

```bash
cd source/se-rag-core
go test ./...        # 单测（无网络）
go vet ./...
```

## 对外接口（供 skill 调用）

`se-rag query "<问题>" -product <name> -index-dir <dir> -top-n N` 输出紧凑 Markdown，
格式与 Python 版 `query.py` 一致（来源文件:行号、相关性分数、文本摘要、耗时）。skill 层可直接用 subprocess 调用。