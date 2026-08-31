---
name: se-series-knowledge-base
version: 4.1.0
description: >-
  Technical knowledge base for Sophgo SE7, SE8, SE9 series micro-servers.
  SE7: BM1684X single SoC. SE8: BM1684X distributed cluster.
  SE9: BM1688/CV186AH single SoC. Contains product docs, SDK references,
  FAQ archives. RAG retrieval via se-rag-core Go binary (FAISS + BM25 + RRF +
  Rerank, A/B dual path, SophNet/siliconflow, CF→FC gateway fault transfer).
---

# SE Series Knowledge Base

## 产品速查

| 项目 | SE7 | SE8 | SE9 |
|------|-----|-----|-----|
| SoC | BM1684X | BM1684X | BM1688 / CV186AH |
| 架构 | 单节点 | 集群（主控+算力节点） | 单节点 |
| 系统 | Ubuntu 20.04 | Ubuntu 20.04 | Ubuntu 22.04 |
| 内核镜像 | /boot/emmcboot.itb | /boot/emmcboot.itb | /boot/boot.itb |
| SDK 版本字段 | sophon-mw-soc-* | sophon-mw-soc-* | sophon-media-soc-* |
| SE9 16路 = BM1688（8核），SE9 8路 = CV186AH（6核） |

## 关键差异（不可混淆）

- SE7/SE8 内核镜像 emmcboot.itb，SE9 是 boot.itb
- SE7/SE8 版本字段 sophon-mw-soc-*，SE9 是 sophon-media-soc-*
- SE7/SE8 用 libsophon v23.09-LTS，SE9 用 bm1688 分支
- SAIL 包跨产品不通用，与 SoC 和 SDK 版本一一对应
- SE8 先区分主控/算力节点：SDK、驱动、推理问题在算力节点排查
- SE8 集群规模见 `docs/se8/00-introduce.md`；各产品具体机型差异优先查对应规格书
- 所有产品均为 SoC 模式，不回答 PCIE 模式问题

## 文档结构（部署后固定布局）

```
{baseDir}/                          # /data/sophon/reasonix-home/skills/se-series-knowledge-base
├── rag/
│   ├── data_se7/          ← SE7 Go 检索索引 (meta.json + vectors.gob + bm25.gob + chunks.gob)
│   ├── data_se8/          ← SE8 Go 检索索引
│   └── data_se9/          ← SE9 Go 检索索引
├── docs/
│   ├── se7/               ← 产品手册 + BM1684X SDK 文档 + FAQ + 工具文档
│   ├── se8/               ← 产品手册 + BM1684X SDK 文档 + FAQ + 工具文档
│   └── se9/               ← 产品手册 + BM1688 SDK 文档 + FAQ + 规格书 + 工具文档
└── SKILL.md
```

检索二进制已预置于 `/data/sophon/reasonix-home/bin/se-rag`，无需构建。

## 检索（必须用 Go se-rag）

涉及 SE7/SE8/SE9 产品/技术问题，**先检索再回答**。三套索引隔离，**严禁跨产品线混用**：

```bash
/data/sophon/reasonix-home/bin/se-rag query \
  -index-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/rag/data_se7 \
  -top-n 8 "你的问题"      # SE7
/data/sophon/reasonix-home/bin/se-rag query \
  -index-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/rag/data_se8 \
  -top-n 8 "你的问题"      # SE8
/data/sophon/reasonix-home/bin/se-rag query \
  -index-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/rag/data_se9 \
  -top-n 8 "你的问题"      # SE9
```

- 输出每条含 `源文件相对路径:行号区间` + 分数 + 文本摘要 + 耗时 + 模式（hybrid/bm25）。
- 流水线：Embedding → FAISS 暴力内积 top-20 + BM25 top-20 → RRF 融合(k=60) → Rerank top-8。
- **路径 B 兜底**：无 key / 断网 / embedding 失败时自动降级为纯 BM25，仍要回答问题。
- 内置 key 走 CF→FC 网关故障转移链（CF Worker → 阿里云 FC），CF 不可达自动切 FC，零改动。
- 重建索引（改了 docs / 换 embedding 供应商）：
  ```bash
  /data/sophon/reasonix-home/bin/se-rag build \
    --docs-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/docs/se7 \
    -index-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/rag/data_se7
  /data/sophon/reasonix-home/bin/se-rag doctor \
    -index-dir /data/sophon/reasonix-home/skills/se-series-knowledge-base/rag/data_se7
  ```
  （se8/se9 同理，换 `--docs-dir`/`-index-dir` 即可）
- 换 embedding 供应商后先用 `doctor` 校验向量库指纹是否需重建。

## 源码检索（涉及 API/驱动/代码时）

无本地 repo 时用 GitHub 公开仓库，直接以 `sophgo/<仓库>` 定位源码路径线索：
- 优先：GitHub 仓库浏览 `libsophon`/`sophon-sail`/`sophon-demo`/`sophon-stream`/`sophon-tools` 等组织仓库
- 兜底：`web_search "sophgo <关键词> github"` 定位仓库与文件
- SE7/SE8 驱动源码 → `repos/ai_libs/bm1684x/`；SE9 → `repos/ai_libs/bm1688/`

## 回答流程（三阶段）

每次回答前执行：**确认产品 → 检索 → 评估 → 回答**。

### 阶段零：确认产品线（必做）

**先查明是哪个产品的问题**：提取产品型号，SE7 → BM1684X 单体 | SE8 → BM1684X 分布式（主控+算力）| SE9 → BM1688/CV186AH 单体。
- 用户已说明型号（如"我的 SE8"）→ 直接按对应索引检索。
- 用户未说明 / 描述模糊（如"我的设备起不来"）→ 先追问一句确认型号，**不要**在型号未明时猜测索引检索。
- 判定为跨产品共性问题（通用 Linux/uboot/工具使用）→ 可在对应产品索引检索后，再按需补问。

### 阶段一：检索
用上面的 `se-rag query`（按产品线选索引）检索，得到分块摘要。

### 阶段二：评估与补漏

**核心原则：摘要优先。** RAG 返回的 800-token 分块摘要已含关键信息，能直接用就不读原文。

- 摘要完整（命令/参数/步骤齐全）→ 直接用，不读原文。
- 摘要模糊（有省略、缺参数、缺版本号）→ 标记需精读：`read` 对应源文件（`源文件相对路径:行号` 定位，缺多少读多少）。
- 评估摘要 + 已读原文是否全覆盖；仍有缺口（硬件规格、机型差异、接口定义等边缘信息）→ `grep -rn "关键词" docs/se{7|8|9}/` 定向补漏（最多 1 次），命中后精读；仍缺则换关键词回到阶段一重新检索。

### 阶段三：回答
- 先结论后展开，第一句给判断/方案。
- 每步附命令、路径、预期现象；排查路径从短到长，能一步定位的不给三步。
- **禁止杜撰**，所有细节来自文档/代码原文；无法确认明说「无法确认，建议联系算能支持」。
- 涉及源码/API/驱动细节且知识库没有时，用 `read`/`grep` 查本地或 `web_search` 定位，不编造。

## 已知要点

1. 模块加载失败：替换内核镜像后未同步 /opt/sophon/libsophon-current/data/
2. 设备出厂预装 SOPHONSDK runtime，不含 sophon-sail，需单独安装
3. TPU-MLIR 在 PC 上运行，不在 SE 设备上
4. sophon-demo 通常有预转换 bmodel，优先使用
5. 驱动模块：bmtpu, jpu, vpu；加载脚本：/usr/sbin/bmrt_loadko.sh
6. 看门狗（SE7/SE8）：STM32 WDT，I2C 0x69，设备 /dev/bm-wdt-0，per-CPU 踢狗机制
7. 源码路径：SE7/SE8 驱动 → repos/ai_libs/bm1684x/，SE9 → repos/ai_libs/bm1688/