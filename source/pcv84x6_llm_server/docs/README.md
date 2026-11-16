# 文档索引

三类文档，不要混读：**当前契约**描述代码现在保证什么；**研究专题**是某个问题的实测证据与结论；
**历史评测**是当时的实验报告，结论已并入当前契约，报告本身保留作证据。

## 当前契约

| 文档 | 内容 |
|---|---|
| [`DESIGN.md`](DESIGN.md) | 架构、引擎数据流、关键不变量、调度与准入、进程协议、数据目录、发布边界 |
| [`device-memory.md`](device-memory.md) | 设备内存 = NPU + VPP：heap id 与 mask 3 的真实含义、bmrt 的堆回退与实测、VPP 承载权重/激活的逐位一致证据、单块连续性与 256 MiB 多媒体保留、TPU 使用率的取法与实测、`/api/stats` 新字段 |
| [`session-state-contract.md`](session-state-contract.md) | `Session` 在快照/恢复/续算时保证什么，哪些曾经不成立，怎么验 |
| [`decode-submission.md`](decode-submission.md) | decode 的提交粒度与线性状态原地更新，以及**不要**改回去的理由 |
| [`console-design.md`](console-design.md) | 控制台视觉规范：四套尺度、层级、主题、无障碍底线 |
| [`inference-records.md`](inference-records.md) | 推理记录：一次推理一条的时机与终结路径、原始输出 vs 展示输出、配置与保留、存储与迁移、故障与隐私 |
| [`admin-api.md`](admin-api.md) | 管理接口 `/api/*` 的对外契约（由代码生成）：admin key 认证与 `scope`、统一错误码表、分页与时间格式约定、每个接口的字段与 curl 示例、离线 Swagger/ReDoc（`/api/docs`、`/api/redoc`）与 `/v1` 文档为何单独提供 |
| [`logs.md`](logs.md) | 日志与审计：平台 / worker / agent 三类日志的路径与轮转、`/api/logs` 的过滤与字节游标翻页、从文件尾读最新 N 行、下载（过滤文本 / 带轮转的 zip）、`/api/audit` 中间件记什么与**不**记什么、保留期与迁移 |
| [`aux-models.md`](aux-models.md) | 辅助模型（embedding / rerank）：类型判定、两个接口的字段与拒绝规则、内存准入、worker 协议、分词与真机验收 |
| [`qwen3-vl-embedding.md`](qwen3-vl-embedding.md) | Qwen3-VL 图文向量：编译、部署、图片输入、MRL 与测试记录 |
| [`wemm-embedding.md`](wemm-embedding.md) | WeMM-2B 图文向量：Qwen3.5 混合编码器、独立状态、提示模板、编译与部署 |
| [`ocr.md`](ocr.md) | OCR：`/v1/ocr` 的三种模式（`lines` / `layout` / `vl`）与响应、四 bmodel 一个模型的目录与下载、按需 rec 档位、前后处理与依赖（设备自带 OpenCV + 随包 pyclipper）、阅读顺序与限制、推理记录 |
| [`kb-app.md`](kb-app.md) | 知识库问答演示应用（`/api/apps/kb`）：按已加载模型降级的四阶段流水线、存储布局与不变式、解析与切片规则、BM25/RRF/精排、带引用的 SSE、串行建库队列与重启恢复 |
| [`mcp.md`](mcp.md) | MCP 服务（`POST /mcp`）：Streamable HTTP 与 JSON-RPC 分层、九个工具（知识库 / OCR / 语音转写）、本地路径白名单与单描述符读取、资源上限、Origin 校验、三个内置 agent 的接入格式与实测证据、stdio 桥接、外部客户端怎么接 |
| [`agents-dsh.md`](agents-dsh.md) | DSH（DeepSeek Harness）Web agent：安装包构成、按行合并的配置与每个字段的实测依据、`--profile web` 的启动参数顺序、启动 token 的代理交接（Host/Origin、cookie 收窄）、健康检查、重置/同步/卸载 |
| [`model-release.md`](model-release.md) | 更换模型文件：dfss 下载标签（`--dflag`）的机制、发布步骤、设备侧的「有新版本」与一键更新、回退与常见失败 |
| [`ocr-stage-a.md`](ocr-stage-a.md) | PaddleOCR-VL 接入可行性：版面检测切掉 TopK 后在板上跑通的实测、vit 与参考对齐的逐层证据与根因（阶段 A + A2） |
| [`ocr-structure.md`](ocr-structure.md) | 表格与复杂版面识别：PP-DocLayout-S/-M + SLANet_plus 的编译、切图/展开的根因、板上对齐数字、整页原型的耗时构成，以及是否接入 `/v1/ocr` 的建议 |
| [`ocr-vl.md`](ocr-vl.md) | PaddleOCR-VL-1.5：解码段（A3 段错误的真正根因、C++ KV cache 方案与三个静默 bug、与 x86 参考的逐 token 对齐、表格 OTSL、整页耗时与内存）**+ 服务接口**（`/v1/chat/completions`、`ocr_vl` 类型、常驻引擎、与 MYS-2660 的逐 token 复核、官方客户端兼容、真机数字）**+ 整页模式**（`/v1/ocr` 的 `mode: "vl"`：两 worker 编排、OTSL→HTML 与 PaddleX 对拍、区域合并、与原设计的偏差） |
| [`qwen35-small.md`](qwen35-small.md) | 稠密 Qwen3.5-9B / 4B（w4 与 bf16）：128k + 视觉的编译配方与两处容器补丁、w4 权重为什么必须用预量化包、逐 token 精度与首个分歧点、板上加载/占用/decode/TTFT/双会话、与四个辅助模型的共存算术、目录条目与 dfss 发布信息 |

## 研究专题

实测驱动的决策依据。每个专题都说明了测量条件、数据和复现方式；结论已落到上面的契约里。

| 文档 | 回答的问题 |
|---|---|
| [`research/decode-optimization.md`](research/decode-optimization.md) | 一个 decode token 的 42 次图发射分别花在哪；为什么并发要靠时间片；`lm_head` 与队列的优化上限 |
| [`research/bmrt-queue-depth.md`](research/bmrt-queue-depth.md) | BMRT 未完成队列能否配置、实际收益多少（结论：no-go，约 3%） |
| [`research/prefill-width-probe.md`](research/prefill-width-probe.md) | 非 64 对齐的动态预填充宽度：哪些会卡死 TPU，TTFT 能省多少 |
| [`research/prefill-ab-eval.md`](research/prefill-ab-eval.md) | 对齐 64 vs 16 的回答正确率 A/B（结论：16 掉 5/40，否决） |
| [`research/prefill-exact-tail-eval.md`](research/prefill-exact-tail-eval.md) | 64 对齐下低余数 prompt 的失败率与精确尾部修复（v0.6.5 的依据） |
| [`research/prefill-tail-align-grid.md`](research/prefill-tail-align-grid.md) | 精确尾部 K × 对齐 16 的组合评测；G1 首条即卡死 TPU |
| [`research/qwen36-lossless-optimization.md`](research/qwen36-lossless-optimization.md) | decode 是否已到访存下界、prefill 的成本结构，以及无损项的定位与否决 |
| [`research/fresh-prefill-fa-state.md`](research/fresh-prefill-fa-state.md) | fresh prefill 的 FA 清零省多少：实测 44 ms，并修正上一篇的 123 ms 口径 |
| [`research/aux-dynamic-seq.md`](research/aux-dynamic-seq.md) | Embedding / Reranker 该不该用动态 shape：动态图只在 ≤100 token 赢、≥250 token 输、长输入输一个数量级；多档静态图不能合进一个 bmodel，只能按长度选档；推荐维持 static2048 + 增设 static512 |
| [`research/d7-tpu-hang.md`](research/d7-tpu-hang.md) | D7 TPU 偶发卡死：触发条件（同一 worker 并发 ≥2 + 堆几乎占满）、驱动侧根因与取证、给驱动团队的复现步骤 |

可复现探针在 [`../analysis/`](../analysis/README.md)（decode/队列）与
[`../tools/prefill_ab_eval.py`](../tools/prefill_ab_eval.py)（预填充评测）；
精度问题的证据在 [`../tools/precision/README.md`](../tools/precision/README.md)。

## 测试报告

| 文档 | 内容 |
|---|---|
| [`e2e-0.6.29.md`](e2e-0.6.29.md) | v0.6.29 在 10155 新板上的全功能端到端测试：发现的问题与处理（含已知问题 D7：TPU 偶发卡死）、稳定性数据、RC1 / RC2 逐项证据表 |

## 其他

- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)：开发环境、测试、真机验收与发布纪律
- [`../tools/README.md`](../tools/README.md)：真机与端到端验证工具分类索引
- [`../web/acceptance/README.md`](../web/acceptance/README.md)：控制台浏览器验收
- 面向使用者的功能说明在服务内的「文档」页（`web/src/pages/Docs.tsx`），随版本更新
