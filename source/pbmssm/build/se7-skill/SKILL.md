---
name: se7-knowledge-base
version: 4.1.0
description: >-
  Technical knowledge base for Sophgo SE7 micro-server.
  BM1684X single SoC, Ubuntu 20.04. RAG retrieval via Go se-rag core
  (FAISS + BM25 + RRF + Rerank, A/B dual path, SophNet/siliconflow,
  CF→FC gateway fault transfer). Index: 951 chunks, 36 docs, 1024-dim.
---

# SE7 Knowledge Base

## 产品速查

| 项目 | SE7 |
|------|-----|
| SoC | BM1684X |
| 架构 | 单节点 |
| 系统 | Ubuntu 20.04 |
| 内核镜像 | /boot/emmcboot.itb |
| SDK 版本字段 | sophon-mw-soc-* |
| libsophon | v23.09-LTS |
| 模式 | SoC（不涉及 PCIE） |

## 关键要点（不可混淆）

- 内核镜像 emmcboot.itb；版本字段 sophon-mw-soc-*
- SAIL 包跨产品不通用，与 SoC 和 SDK 版本一一对应
- 所有产品均为 SoC 模式，不回答 PCIE 模式问题

## 文档结构

```
{baseDir}/                            # <此 skill 所在目录，通常：/data/sophon/reasonix-home/skills/se7-knowledge-base
├── rag/data_se7_go/                  ← Go se-rag 预建索引 (meta.json + vectors.gob + bm25.gob + chunks.gob)
├── docs/se7/                         ← 产品手册 + BM1684X SDK 文档 + FAQ + 工具文档
└── ../../bin/se-rag                  ← Go 检索核心（静态二进制）
```

## 检索（必须用 Go se-rag）

涉及 SE7 产品/技术问题，**先检索再回答**：

```bash
/data/sophon/reasonix-home/bin/se-rag query \
  -index-dir /data/sophon/reasonix-home/skills/se7-knowledge-base/rag/data_se7_go \
  -top-n 8 "你的问题"
```

- 输出每条含 `源文件相对路径:行号区间` + 分数 + 文本摘要 + 耗时 + 模式（hybrid/bm25）。
- 流水线：Embedding → FAISS 暴力内积 top-20 + BM25 top-20 → RRF 融合(k=60) → Rerank top-8。
- **路径 B 兜底**：无 key / 断网 / embedding 失败时自动降级为纯 BM25，仍要回答问题。
- 内置 key 走 CF→FC 网关故障转移链（CF Worker → 阿里云 FC），CF 不可达自动切 FC，零改动。
- 重建索引（改了 docs / 换 embedding 供应商）：
  ```bash
  /data/sophon/reasonix-home/bin/se-rag build \
    --docs-dir /data/sophon/reasonix-home/skills/se7-knowledge-base/docs/se7 \
    -index-dir /data/sophon/reasonix-home/skills/se7-knowledge-base/rag/data_se7_go
  /data/sophon/reasonix-home/bin/se-rag doctor \
    -index-dir /data/sophon/reasonix-home/skills/se7-knowledge-base/rag/data_se7_go
  ```
- 换 embedding 供应商后先用 `doctor` 校验向量库指纹是否需重建。

## 回答流程（三阶段）

每次回答前执行：**检索 → 评估 → 回答**。

### 阶段一：检索
用上面的 `se-rag query` 检索，得到分块摘要。

### 阶段二：评估与补漏

**核心原则：摘要优先。** RAG 返回的 800-token 分块摘要已含关键信息，能直接用就不读原文。

- 摘要完整（命令/参数/步骤齐全）→ 直接用，不读原文。
- 摘要模糊（有省略、缺参数、缺版本号）→ 标记需精读：`read` 对应源文件（`源文件相对路径:行号` 定位，缺多少读多少）。
- 评估摘要 + 已读原文是否全覆盖；仍有缺口（硬件规格、机型差异、接口定义等边缘信息）→ `grep -rn "关键词" docs/se7/` 定向补漏（最多 1 次），命中后精读；仍缺则换关键词回到阶段一重新检索。

### 阶段三：回答
- 先结论后展开，第一句给判断/方案。
- 每步附命令、路径、预期现象；排查路径从短到长。
- **禁止杜撰**，所有细节来自文档/代码原文；无法确认明说「无法确认，建议联系算能支持」。
- 涉及源码/API/驱动细节且知识库没有时，用 `read`/`grep` 查本地仓库或 `web_search` 定位，不编造。

## 已知要点

1. 模块加载失败：替换内核镜像后未同步 /opt/sophon/libsophon-current/data/
2. 设备出厂预装 SOPHONSDK runtime，不含 sophon-sail，需单独安装
3. TPU-MLIR 在 PC 上运行，不在 SE 设备上
4. sophon-demo 通常有预转换 bmodel，优先使用
5. 驱动模块：bmtpu, jpu, vpu；加载脚本：/usr/sbin/bmrt_loadko.sh
6. 看门狗：STM32 WDT，I2C 0x69，设备 /dev/bm-wdt-0，per-CPU 踢狗机制
7. 源码路径：SE7 驱动 → repos/ai_libs/bm1684x/