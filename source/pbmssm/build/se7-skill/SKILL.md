---
name: se7-knowledge-base
version: 4.0.0
description: >-
  Technical knowledge base for Sophgo SE7 micro-server.
  BM1684X single SoC, Ubuntu 20.04. RAG retrieval via Go se-rag core
  (vector + BM25 + RRF + rerank, siliconflow/sophnet). Index: 1183 chunks, 36 docs, 1024-dim.
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

## 文档结构

```
{baseDir}/                            # <此 skill 所在目录，通常：/data/sophon/reasonix-home/skills/se7-knowledge-base
├── rag/data_se7_go/                  ← Go se-rag 预建索引 (meta.json + vectors.gob + bm25.gob + chunks.gob)
├── docs/se7/                         ← 产品手册 + BM1684X SDK 文档 + FAQ + 工具文档
└── ../../bin/se-rag                  ← Go 检索核心（静态二进制）
```

## 检索（必须用 Go se-rag）

涉及 SE7 产品/技术问题，先检索再回答：

```bash
/data/sophon/reasonix-home/bin/se-rag query \
  -index-dir /data/sophon/reasonix-home/skills/se7-knowledge-base/rag/data_se7_go \
  -top-n 8 "你的问题"
```

- 默认在线（内置 siliconflow embedding + rerank）；无 key / 断网 / embedding 失败自动降级 BM25。
- 输出每条含 `源文件相对路径:行号区间` + 分数 + 文本。
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

**检索 → 评估 → 回答**。

### 阶段一：检索
用上面的 `se-rag query` 检索，得到分块摘要。

### 阶段二：评估与补漏
- 摘要完整（命令/参数/步骤齐全）→ 直接用，不读原文。
- 摘要模糊 → `read` 对应源文件精读（`源文件相对路径:行号` 定位）。
- 缺口 → `grep -rn "关键词" docs/se7/` 定向补漏（最多 1 次），命中后精读；仍缺则换关键词重检索。

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
7. 源码路径：驱动 → repos/ai_libs/bm1684x/