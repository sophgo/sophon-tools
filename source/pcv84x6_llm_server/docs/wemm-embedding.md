# WeMM-Embedding-2B

使用腾讯的 [WeMM-Embedding-2B](https://huggingface.co/tencent/WeMM-Embedding-2B)
专用向量权重，将文字、单张图片或图文组合编码到同一向量空间。底座是 Qwen3.5：
24 层语言编码器中包含 18 层线性注意力和 6 层全注意力，视觉分支没有 DeepStack。
取最后一个 `<embedding>` token 的最终隐藏状态，截取 MRL 前缀后再做 L2 归一化。

输出上限为 2048 维；官方训练的 MRL 档位为 64、128、256、512、1024、2048。
本服务只接入文字、单图和图文组合，未接入视频、多图或音频。

## 从目录下载安装

目录 ID 为 `wemm-embedding-2b`，下载标签为 `cv84x6_llm_wemm-embedding-2b`。
发行包内置 `model-config/wemm_embedding/`，与下列 W8BF16 构建配套；目录下载只需取得
bmodel，无需用户另找 tokenizer。模型自己携带的 `config/` 仍优先于内置配置。

下列资源及主/MD5 下载标签已发布。CV84X6 上已从空目录通过真实管理 API 下载，
校验文件摘要后使用发行包内置配置完成 98 项端到端检查。

| 项目 | 固定值 |
|---|---|
| 文件 | `wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel` |
| dfss 目录 | `open@sophgo.com:/tools/cv84x6_llm_server/` |
| 大小 | 3121778688 bytes |
| MD5 | `2065f4c866be364c0607b705c07f3dc4` |
| SHA-256 | `480a67420d349c2898816749019785b68e8608cdbe00403e526e8e90179713bd` |

完整配置各文件的 SHA-256 保存在 `model-config/wemm_embedding/distribution.json`。
下载器先使用主标签和 `.md5` 标签；固定地址仅作为既有下载机制的回退。发布流程见
[模型文件发布](model-release.md#wemm-embedding-2b-首次发布)。

## 自行编译与安装模型

权重固定到 `bbd6cd4bf52cfc6716f752a2df80b2706720bd95`；完整 safetensors 的
SHA-256 为 `e1a1ad752808c26965aa97d37bf4a9bca71d838513f41e83790cb1e71cac6e59`。
使用含 `Qwen3_5Converter` 的 TPU-MLIR 1.30.2（本任务环境 `tpu-mlir:1.30.2-38`），
目标芯片名为 `bm1684x2`，四核。

```bash
python3 tools/vl_embed/download_model.py --family wemm --output-dir /build/wemm/hf
# 可用 --mirror modelscope；镜像文件仍按固定 HF revision 的 SHA-256 验证。
python3 tools/vl_embed/compile_model.py --family wemm --model /build/wemm/hf \
  --out-dir /build/wemm/bf16 --quantize w8bf16 --prefill buckets \
  --seq-length 2048 --max-pixels 1310720 --cores 4 --jobs 4
```

直接从 safetensors 生成 MLIR，不导出 LM head 或逐 token 解码图。
语言图按 128/512/1024/2048 分档，选择能容纳输入的最小一档。
全注意力和 Gated DeltaNet 均使用静态图。GDN 使用普通算子实现：归一化、衰减和状态
累积保留 FP32，矩阵乘法使用 FP16，其余网络保持所选 BF16/W8BF16 精度。
ViT 保持动态形状，图片不补齐到最大预算。
全注意力图关闭当前编译器的 layer group 优化，保留四核 attention 内核。
上下文长度须是 128 的倍数，最大图片预算不能小于 65536 pixels。

自行编译时，将 bmodel 和**同次编译生成的完整 config 目录**一起放置：

```text
<data-root>/models/wemm-embedding-2b/
  wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed.bmodel
  config/
    embedding_config.json
    tokenizer.json
    config.json
    processor_config.json
    ...
```

服务按 `wemm-embedding` / `wemm_embedding` 文件名前缀识别为支持图片的 embedding 模型。
加载时核对模型家族、隐藏维度、上下文和图片预算；配置不能借用 Qwen3-VL 或纯文本模型。
板端只需发行包的 Python、tokenizers 和 BMRT 原生库，无需 Torch、Transformers 或 SAIL。

## 调用

接口和批处理规则与 [Qwen3-VL 的多模态接口](qwen3-vl-embedding.md#api)相同，模型名改为
`wemm-embedding-2b`：

```json
{
  "model": "wemm-embedding-2b",
  "input": ["海边的照片", {"image": "data:image/jpeg;base64,..."}],
  "dimensions": 256,
  "encoding_format": "float"
}
```

WeMM 默认没有系统指令，也没有 assistant 前缀。可选 `instruction` 放入系统消息，
只去除首尾空白，不自动补标点。用户内容按官方模板去除整体首尾空白；图像之后的文本
前导空白仍保留。分词器负责追加唯一的池化 token `<embedding>`（248077），不要手工追加。

图像使用官方最小 65536 pixels 和所编译的最大预算，等比缩放到 32 的倍数。
RGBA 图片按官方入口先合成到白底，再做缩放。
先完成整批的图像、分词和长度检查，再串行执行 NPU 推理；超长输入返回 400，不截断。
每次请求、每个线性注意力层都清零循环状态，不继承上一条文字或图片的状态。

WeMM 与 Qwen3-VL 的向量空间不同。切换模型时须重建索引，不能直接比较两种模型产生的向量。
模型自身的检索质量应在相同原始输入和候选库上分别计算。

## GDN 实现与算子验证

`wemm_gdn_primitives.py` 按 64 token 分块。三角系统按 2/4/8/16/32/64 行逐级合并逆矩阵块，
避免高相关 key 的幂级数产生巨大中间值；累积衰减与跨块状态保留 FP32。
输出先按八块分组、转置，再拼接，避免当前四核后端在 Concat 超过 16 输入时写错结果。
原生引擎只接受此静态 FP32 状态契约；早期融合 GDN 实验模型不兼容。

另一个独立问题出现在全注意力层的分组代码生成路径：同一 285-token 中文输入，
第 4 层在 TOP FP32、TPU BF16 CPU 模拟上正确，板端部分 token 的余弦却降到 0.96910。
单独的 attention、RoPE、位置编码索引探针均正确；仅加 `--disable_layer_group`
后，该层最差 token 余弦为 0.99996。编译入口只对 WeMM 的全注意力图应用这一选项，
并使用独立缓存目录，防止复用未修正的图。

可在 TPU-MLIR 环境复现含非零初始状态的独立算子对拍：

```bash
python3 tools/vl_embed/gdn_probe.py --out-dir /build/gdn-probe --seq-length 2048 --case correlated \
  --reference-source /path/to/transformers/models/qwen3_5/modeling_qwen3_5.py
cd /build/gdn-probe
model_deploy --mlir gdn_primitives.mlir --chip bm1684x2 --quantize F32 \
  --quantize_table gdn_precision.txt --num_core 4 --model gdn.bmodel
```

参考函数来自 Transformers 5.2.0，源文件 SHA 写入 `fixture.json`。将 bmodel 和
`input*.bin` 复制到无其他 NPU 推理任务的板卡，用 `tools/vl_embed/gdn_probe.cpp`
链接 `bmrt`、`bmlib` 后运行 `gdn_probe gdn.bmodel <fixture-directory>`。
把 `output0.bin` 取回，再运行 `gdn_probe.py --out-dir /build/gdn-probe --actual output0.bin`。
分别使用 `--case random`、`--case correlated`、`--case large-decay` 生成三类输入。
该检查只验证算子；最终精度门槛仍是完整模型在六档 MRL 的对拍。

## 板端验证（2026-11-14）

推荐 W8BF16、四核、128/512/1024/2048 分档、1310720 最大图片预算。
只量化语言层支持的权重；embedding、ViT 保留 BF16，GDN 使用上述混合精度。
BF16 对照也通过精度门槛，但体积和延迟更高。推荐模型 SHA-256：
`480a67420d349c2898816749019785b68e8608cdbe00403e526e8e90179713bd`（3121778688 bytes）。

固定种子的 64 张 COCO 图片、128 条英文说明、16 条预先翻译的中文说明和 8 条组合/边界
输入，共 216 条；另有 17 条长度/图片边界。中文并非官方标注，这只是回归集，不能作为完整
COCO/MMEB 排名。所有输入 token 与官方 FP32 相同，六档 MRL 的逐样本余弦均 ≥0.99。

| 配置 | 216 条最低余弦 | 17 条边界最低余弦 | 模型大小（十进制 GB） |
|---|---:|---:|---:|
| BF16 + FP32 GDN 状态 | 0.996424 | 0.993768 | 4.453 |
| W8BF16 + FP32 GDN 状态 | 0.995931 | 0.993148 | 3.122 |

同一候选库、分别在各自向量空间计算英文 Recall@1：

| 配置 | 2048 维文字→图片 | 2048 维图片→文字 | 256 维文字→图片 | 256 维图片→文字 |
|---|---:|---:|---:|---:|
| Qwen3-VL-2B 板端 BF16 | 119/128 | 62/64 | 117/128 | 62/64 |
| WeMM-2B 官方 FP32 | 122/128 | 63/64 | 123/128 | 63/64 |
| WeMM-2B 板端 W8BF16 | 122/128 | 63/64 | 123/128 | 63/64 |

WeMM 的 2048/256 维中文双向均为 16/16。其他维度并非完全保持 FP32 排名：
1024 维中文 `caption-90108-0-zh` 从命中变为未命中，BF16/W8 都如此；64 维合并中英文
文字→图片命中分别为 FP32 130/144、BF16 132/144、W8 131/144。
默认 2048 维，节省索引空间时可选此次也保持命中的 256 维。

同一板卡、同一原始输入，预热 2 次、重复 30 次；表中为 p50（ms），不含模型加载。
各模型保留官方最小图片预算（WeMM 65536、Qwen3-VL 4096），最大预算相同。

| 输入 | Qwen3-VL BF16 | WeMM BF16 | WeMM W8BF16 |
|---|---:|---:|---:|
| 短英文 | 79.66 | 110.67 | 80.83 |
| 短中文 | 79.68 | 110.77 | 80.81 |
| 图片 | 1036.84 | 1108.49 | 1077.60 |
| 图文 | 1037.01 | 1108.35 | 1077.74 |
| 长英文 | 151.09 | 270.93 | 240.38 |
| 长中文 | 149.38 | 269.44 | 239.03 |

WeMM W8 加载约 12.63 秒，进程峰值 RSS 227764 KiB。它在此回归集上检索更好，短文本
速度接近旧模型；图片约慢 4%，长文本约慢 59%–60%，因此不是全场景的速度升级。
64-token 小档试编译触发当前后端 BF16→FP16 Cast 断言，未纳入支持范围。

主机全量回归：3090 passed、17 skipped；原生行为检查 1147 项通过；Web 构建通过。
追加 63/64/65-token 三条边界也通过。14 组像素逐位一致；四条 C++/Python 输出最大误差
<5e-10。真实发行包 HTTP 87 项通过，包括 48 个并发请求（12 个成功、36 个预期 429）、
客户端取消、卸载重载与 NPU 内存回收。加载后 NPU 堆占用 3406360576 bytes，卸载归零。
完整输入、原始向量、p95 和故障记录见随交付附带的验证报告。

早期实验触发过驱动超时/内核异常；最终验收前已重启，最终 BF16/W8 的完整对拍与计时
均无新增驱动错误。历史故障的驱动根因仍未确定，这些短期测试不等于长期稳定性证明。
原有服务没有升级；新增模型不会自动替换已有索引或模型。

## 目录下载端到端验收

`tools/vl_embed/service_check.py` 的目录模式必须使用全新的数据目录。它通过真实管理 API
启动 dfss 下载，要求标签成功（固定地址回退不计通过），检查文件名、大小、MD5、SHA-256，
确认没有手工复制的 config，并使用发行包内置配置加载。随后验证三类输入、批次顺序、
base64、MRL、非法输入、48 个并发请求、取消、卸载重载和 NPU 内存回收。

脚本随发行包提供在 `tools/vl_embed/`，导入该包的 `app/` 和内置配置；将 `PYTHONPATH`
指向该包的 `vendor/`，程序文件不得从源码覆盖。在无其他 NPU 任务时，从待测发行包
解包后的根目录执行：

```bash
PYTHONPATH="$PWD/vendor" python3 tools/vl_embed/service_check.py \
  --catalog-id wemm-embedding-2b --library "$PWD/lib/libcv84x6_llm.so" \
  --work-dir /data/wemm-catalog-acceptance-new \
  --image /path/to/000000355325.jpg --output /path/to/wemm-catalog-report.json
```

工作目录至少预留 4 GiB 空间。脚本使用临时 localhost 端口，结束时排空并关闭 worker，
不占用生产端口 8000。运行前后保存 dmesg，发现新增驱动错误即停止后续验证。
手工指定 `--bmodel --config` 的已有 87 项 HTTP 结果只证明推理链路；它不证明 dfss 发布
或全新下载可用。

2026-11-14 的目录模式验收通过 98 项：实际通过主/MD5 标签下载 3121778688 bytes，
文件名、MD5 和 SHA-256 与上表一致，未回退固定地址，也未手工复制配置。
发行包内置配置完成文本、图片、图文、MRL、错误输入、取消及卸载重载验证；
48 个并发请求为 12×200、36×预期 429。加载时 NPU 堆占用 3406360576 bytes，
卸载及验收进程退出后均为 0，前后驱动日志无新增错误。
主机代码阶段全量回归 3094 passed / 17 skipped；发布复验相关用例 119 passed，Web 构建通过。
