# 更换模型文件：下载标签（dfss `--dflag`）

控制器里的模型不是跟随服务版本发布的。换一个 bmodel，只需要在 dfss 上把某个
**下载标签**指向新文件；装了旧版的板子会在控制台看到「有新版本」，一键更新即可。
这份文档是发布侧的操作手册，改动的是 dfss，不是代码。

前提：标签机制由 dfss 服务器提供，与本文档一起上线的是服务侧的消费逻辑
（`app/core/downloader.py` 的 `CATALOG[*]["dflag"]`、`GET /api/catalog` 的
`update_available`、`POST /api/models/<id>/update`）。

## 1. 机制

- 任意目录放一个 `.dfss_down_flag`，每行 `<标签> <相对该目录的文件名或 glob>`。
- 服务器定期（实测约 1 分钟）扫描全部 `.dfss_down_flag`，生成索引
  `/open/.dfss_flags`，内容为 `{"<标签>": {"filepath": "<相对 open 根的路径>"}}`。
- **同名标签先到先得，标签在所有 dfss 用户间全局唯一。**
- 客户端 `python3 -m dfss --dflag=<标签>` 把文件按**真实文件名**下到当前目录。
- 索引本身可以 `python3 -m dfss --url=open@sophgo.com:/.dfss_flags` 下载（几 KB）。

我们使用的标签统一带 `cv84x6_llm_` 前缀，配置在
`/open/tools/cv84x6_llm_server/.dfss_down_flag`。每个模型文件一个标签，外加一个
`<标签>.md5` 标签，指向内容为 `<md5>  <文件名>` 的 sidecar 文件。

sidecar 是升级检测的关键：它同时给出**摘要**和**真实文件名**，板子因此不需要下载
20 GB 就能知道「标签现在指向的文件，我这儿没有」。

## 2. 发布一个新版本的模型文件

以 `cv84x6_llm_qwen3-asr-0.6b` 为例。

**① 上传新 bmodel** 到 `/open/tools/cv84x6_llm_server/`，文件名按惯例带构建日期：

```
qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261110_093012.bmodel
```

**② 生成并上传 md5 sidecar**。格式必须能被 `md5sum -c` 和本服务解析
（`<32 位十六进制>  两个空格  <文件名>`）：

```bash
cd /open/tools/cv84x6_llm_server
md5sum qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261110_093012.bmodel \
  > qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261110_093012.bmodel.md5
```

**③ 改 `.dfss_down_flag` 里那两行**，指向新文件：

```
cv84x6_llm_qwen3-asr-0.6b      qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261110_093012.bmodel
cv84x6_llm_qwen3-asr-0.6b.md5  qwen3-asr-0.6b_bf16_seq1024_bm1684x2_4core_static_20261110_093012.bmodel.md5
```

上传 `.dfss_down_flag`。**两行必须同时改**：只改主标签而 sidecar 仍指向旧文件，
板子会看到「文件名不一致」并拒绝安装（这是有意的，见 §5）。

**④ 等约 1 分钟**，然后验证索引与下载：

```bash
python3 -m dfss --url=open@sophgo.com:/.dfss_flags   # filepath 应是新文件名
mkdir -p /tmp/dflag-check && cd /tmp/dflag-check
python3 -m dfss --dflag=cv84x6_llm_qwen3-asr-0.6b.md5
cat *.md5                                            # md5 与文件名都要对
```

**⑤ 更新服务目录里的 `md5` 与 `size_bytes`**（可选，但推荐）。
`CATALOG` 里这两个字段是该文件的**回退校验值**：标签不可用时（旧版 dfss、服务器
没有该标签、网络不通）服务会退回固定 `dfss` URL 下载，并用这两个值校验。
不更新的话回退路径会对新文件报 md5 不匹配——这是能立刻发现问题的失败，但会让回退
失去意义。

> 注意 `dfss` URL 字段**不要改**，除非新文件同时以新名字放到了同一个固定路径。
> 该字段是回退地址，保持指向一个确实存在的文件即可。

## 3. 设备侧看到什么

- 板子每 10 分钟（或服务重启后）刷新一次标签索引，控制台打开「模型」页时在后台
  线程刷新，页面不会被网络拖住。刷新失败后 2 分钟内不再重试（离线板子不会每翻一次页
  就去连一次 dfss），2 分钟后自动再试。
- 对**已安装**且有标签的模型，`GET /api/catalog` 返回
  `latest_file`、`latest_files`、`update_available`、`missing_files`。
- 「有新版本」= 标签指向的文件名不在本地模型目录里。多文件模型（PP-OCR 四个
  bmodel）只要有一个不同就算有更新。
- `POST /api/models/<id>/update` 下载新文件到暂存目录、校验、再**替换**旧 bmodel
  并删除不再属于新版本的文件。整个过程模型处于「下载中」锁定状态；模型已加载或
  正在加载时返回 409，须先卸载。失败时旧文件保持不动。
- **更新只走标签，不退回固定地址。** 固定地址是本服务发布时登记的文件，用它「更新」
  既可能什么都没换，也可能把已装的更新版本换回旧版本。所以任何一个文件没能从标签
  拿到，整个更新就失败并提示「标签不可用，无法更新」，磁盘上的模型保持原样。
- **在目录页点「下载」也有同样的替换效果。** 目标目录里已有的、不属于本次下载集合
  的 bmodel 会被删掉，不会出现新旧两份并存（否则加载器按文件名挑，可能加载到旧的，
  而「有新版本」还一直是 true）。`tokenizer`、配置目录等非 bmodel 文件不受影响。
  **URL 下载与 dfss 下载、更新走同一条安装路径**（`_install_set`）：装到已有目录时同样
  替换旧构建、同样在消息里写「已替换旧文件」。
- **多文件安装是全有或全无。** 每个文件先以 `<name>.part` 落到目标目录（扫描器不认这个
  后缀），全部到位后才逐个 rename 覆盖；rename 阶段任何一步失败，已经换掉的文件都会被
  恢复（旧文件先 rename 成 `<name>.bak`，回滚时 rename 回来）。所以一个四文件的 OCR 模型
  不会出现「装好了三个」的中间态 —— 那会扫成一个模型、报四个文件已服务、却因为缺一个而
  加载失败。
- **第一步是 rename，不是复制。** 暂存目录和数据根在同一个文件系统上，`os.replace` 就够了。
  以前这里 `shutil.copyfile`：峰值占用变成「旧构建 + 2 × 新构建」，而下载前的 `check_space`
  只按一份新构建检查，大模型升级会在一个其实装得下的盘上报空间不足；20 GB 的 bmodel 复制
  是这块板 eMMC 上的几分钟。只有暂存目录被指到另一个挂载点（`EXDEV`）时才复制。
- **安装不在事件循环上跑。** `_install_set` 由 `_run_url` / `_run_update` / `_run_dfss` 通过
  `asyncio.to_thread` 调用。以前同步执行，复制 20 GB 期间整个 API（推理流、`/healthz`）
  一起卡住。
- **`.bak` 残留分两种。** 目标文件**存在**时的 `.bak` 是回滚没删干净的重复副本，
  `orphan_free_space` 照旧统计成可回收；目标文件**不存在**时的 `.bak` 是那次安装唯一的
  构建（"移开"之后、"换进去"之前进程被杀），启动时 `_recover_backups` 会把它改名回去，
  `orphan_free_space` 把它排除在可回收之外，只在 `recoverable` 里列出 —— 否则界面会建议
  用户"清理"掉他的模型。

本地测试标签是否可用（不经过控制台）：

```bash
CV84X6_DFSS_PYTHON=/usr/bin/python3 python3 -c "
import asyncio
from app.core.downloader import DfssFlags, update_status, catalog_entry
from pathlib import Path
f = DfssFlags(); asyncio.run(f.refresh())
e = catalog_entry('qwen3-asr-0.6b')
print(update_status(e, Path('models/qwen3-asr-0.6b'), f))
"
```

## 4. 回退

旧文件**保留一段时间**再删。回退就是改标签：

1. 把 `.dfss_down_flag` 的两行改回旧文件名（sidecar 也改回），上传；
2. 等约 1 分钟，索引生效；
3. 在设备上一键更新（或删掉模型目录重新下载）。

不删旧文件，回退才是一次标签修改。确认新版本稳定后，旧 bmodel 可以改名成
`.bak`（服务只扫描 `*.bmodel`，`.bak` 不会被当成模型）或直接删除。

## 5. 常见失败与含义

| 现象 | 原因 | 处理 |
|---|---|---|
| 板子报「标签不可用，已使用固定地址」 | dfss < 1.10.9、标签不存在、或板子到 dfss 无路由 | 看服务日志里的 dfss 输出；板子上 `python3 -m dfss --help` 应能看到 `--dflag` |
| 更新报「标签不可用，无法更新」 | 同上，但这次是**更新**：更新不允许退回固定地址 | 先修好标签/网络，再重试更新；已安装的模型没有被动过 |
| 报「标签可能在下载过程中被改动」 | 主标签和 sidecar 指向了不同文件 | 两行一起改，见 §2 ③ |
| 报「md5 不匹配」 | sidecar 的摘要与文件不符（上传时算错了，或文件传坏） | 重新 `md5sum` 并重传 sidecar；必要时重传 bmodel |
| 报「无法校验」 | 既没有 sidecar，`CATALOG` 里也没有 md5 | 补 sidecar（首选），或补 `CATALOG` 的 md5 |
| 目录里模型没变，但报更新成功 | 极少数：新旧文件名相同 | 换文件名发布，不要覆盖同名文件——同名文件无法被「有新版本」检测出来 |

**关于同名覆盖**：标签机制靠**文件名**判断新旧。如果新版本仍用旧文件名（就像
2026-11-04 的 mask128 替换），板子无法察觉。要利用无感升级，新构建请换文件名。

## 6. 标签清单

`/open/tools/cv84x6_llm_server/.dfss_down_flag` 当前登记（2026-11-04）：

| 标签 | 对应目录条目 | 文件 |
|---|---|---|
| `cv84x6_llm_qwen3.6-35b-a3b-128k` | `qwen3.6-35b-a3b-128k` | 128k bmodel（mask128） |
| `cv84x6_llm_qwen3-asr-0.6b` | `qwen3-asr-0.6b` | ASR 0.6B |
| `cv84x6_llm_qwen3-asr-1.7b` | `qwen3-asr-1.7b` | ASR 1.7B |
| `cv84x6_llm_ppocrv6-medium-det` | `ppocrv6-medium` | det 736 |
| `cv84x6_llm_ppocrv6-medium-rec-320` | `ppocrv6-medium` | rec 320 |
| `cv84x6_llm_ppocrv6-medium-rec-640` | `ppocrv6-medium` | rec 640 |
| `cv84x6_llm_ppocrv6-medium-rec-1600` | `ppocrv6-medium` | rec 1600 |
| `cv84x6_llm_paddleocr-vl-1.5` | `paddleocr-vl-1.5` | PaddleOCR-VL-1.5（`kind: ocr_vl`） |

每个上面都另有 `<标签>.md5`。

embedding（`qwen3-embedding-0.6b`）和 reranker（`bge-reranker-v2-m3`）是厂商目录
`ext_model_information/LLM/LLM-TPU/` 下的官方文件，不由我们维护，**没有标签**，
继续用固定 URL 下载。

新增一个带标签的模型：先在 `.dfss_down_flag` 里加两行（主 + md5），等索引生效，
再在 `app/core/downloader.py` 的 `CATALOG` 条目上加 `dflag` 字段（多文件条目的
每个 `files[]` 项各加一个）。两处都完成，控制台的「有新版本」才会生效。

## WeMM-Embedding-2B 首次发布

2026-11-14 已完成资源发布、sample 全新下载走查和发行包目录下载端到端验收。
发布时保留了原有 28 个标签，两个 WeMM 标签均已在公开索引生效。

`/open/tools/cv84x6_llm_server/` 提供以下不可变文件：

- `wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel`
- 上述文件名加 `.md5`，内容为 `2065f4c866be364c0607b705c07f3dc4`、两个空格和完整文件名。
- `wemm-embedding-2b_config_20261114.tar.gz`，包含配套 `config/`；供 sophon-demo 下载。
- `wemm-embedding-2b_reference_20261114.tar.gz`，包含固定参考向量和边界输入；供 sample 对拍。

配置对应的权重 revision 为 `bbd6cd4bf52cfc6716f752a2df80b2706720bd95`。
配置的摘要清单见 `model-config/wemm_embedding/distribution.json`，bmodel 摘要见
[WeMM 文档](wemm-embedding.md#从目录下载安装)。sample 的 `scripts/assets.json` 固定三个
资源的 SHA-256；更新配置或参考数据时须使用新文件名，并同步该清单。

保留其他标签；首次发布已原子追加以下两行，并验证公开索引及 sidecar 的实际下载：

```text
cv84x6_llm_wemm-embedding-2b wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel
cv84x6_llm_wemm-embedding-2b.md5 wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel.md5
```

服务发行包内置配置，sample 单独下载配置，两者必须与此 bmodel 匹配。
本次 sample 从空目录下载三个资源并校验 SHA-256，SAIL、Python BMRT、C++ 各 236 条通过。
发行包 `service_check.py --catalog-id wemm-embedding-2b` 在另一个空目录通过 98 项检查，
包括标签下载、大小/MD5/SHA-256、内置配置、实际推理、并发及卸载重载。
后续更新也须完成这两条验收；本地预置 bmodel 不能替代下载验收。
