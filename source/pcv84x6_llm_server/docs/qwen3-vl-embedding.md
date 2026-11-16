# Qwen3-VL-Embedding-2B

推荐 **BF16、128/512/1024/2048 静态语言分档、1310720 图片预算、四核**。
56 输入与官方 FP32 对拍的最低余弦为 0.998420，完整维度双向检索结果一致。
该小样本不能代表完整 COCO 排名；各候选、边界输入和服务验收见
[验证记录](research/qwen3-vl-embedding-validation.md)。

将文字、图片或图文组合编码到同一个 2048 维空间。支持 MRL 截断到 64–2048 维，
先取前缀再做 L2 归一化。使用官方 embedding 权重，不能以 Qwen3-VL-Instruct 权重替代。

上游：[模型卡](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)、
[官方实现](https://github.com/QwenLM/Qwen3-VL-Embedding)。权重版本固定为
`9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda`；下载脚本校验该版本声明的 SHA-256。

## 编译与放置

在 TPU-MLIR 1.30.2 环境编译。需要含 `Qwen3VLConverter`、`submit_deploy_task`
与 Transformers 5 兼容层的工具链；本次使用 `tpu-mlir:1.30.2-38`。
CV84X6 在此版本的编译目标名是 `bm1684x2`，默认使用四核。

```bash
python3 tools/vl_embed/download_model.py --output-dir /build/hf
# 下载网关截断大文件时，可加 --mirror modelscope；最终仍校验固定 HF 版本的散列。
python3 tools/vl_embed/compile_model.py --model /build/hf --out-dir /build/out \
  --quantize bf16 --prefill buckets --seq-length 2048 --max-pixels 1310720 --cores 4 --jobs 4
```

编译器直接从权重生成 MLIR，复用 Qwen3-VL 的 M-RoPE、Q/K norm、ViT 和 DeepStack。
默认生成 embedding、四档各 28 个静态 prefill block、动态 ViT 和加法图；不生成 LM head 或 decode 图，
不建立持久 KV cache（上游 block 接口仍含未使用的 K/V 输出）。
运行时选择最小可容纳输入的一档，ViT 始终动态，避免图像 padding 改变双向注意力。
`--prefill dynamic` 保留动态语言图作为对照。262144 预算下，BF16 分档短文本约 80 ms，
相较动态约 486 ms 提速 6.1 倍；图片约 821 ms，对照约 1431 ms。
W8/W4 仍可显式编译，但本次未通过全部样本余弦 ≥0.99 的门槛，不作为质量默认。
最后一层包含模型最终 RMSNorm，取最后一个有效 token。
必须保留 tokenizer 的后处理：它在 assistant 前缀之后追加 `<|endoftext|>`（151643），
这才是最终池化位置；它不是 padding，也不是聊天配置中的 `<|im_end|>`。

将产物和**该次编译生成的整个 config 目录**放入服务的模型目录：

```text
<data-root>/models/qwen3-vl-embedding-2b/
  qwen3-vl-embedding-2b_bf16_seq2048_pixels1310720_cv84x6_4core_buckets.bmodel
  config/
    embedding_config.json
    tokenizer.json
    config.json
    ...
```

服务按 `qwen3-vl-embedding` / `qwen3_vl_embedding` 文件名前缀识别。在模型页刷新后加载，
或在设置中启用该模型的按需加载后，以目录名调用接口。配置缺失或与 bmodel 尺寸不符时拒绝加载；
不要套用纯文本 embedding 的 tokenizer。运行时需要发行包内的 `tokenizers` 和原生库，
不需要 PyTorch、Transformers 或 SAIL。视频和一条输入内的多张图片暂不支持。

## API

```python
import base64
import httpx

image = base64.b64encode(open("photo.jpg", "rb").read()).decode()
response = httpx.post("http://<板卡>:8000/v1/embeddings",
    headers={"Authorization": "Bearer <key>"},
    json={
        "model": "qwen3-vl-embedding-2b",
        "input": [
            "一张海边的照片",
            {"image": "data:image/jpeg;base64," + image},
            {"text": "海边的场景", "image": "data:image/jpeg;base64," + image},
        ],
        "dimensions": 512,
        "encoding_format": "float",
    }, timeout=300)
response.raise_for_status()
vectors = [row["embedding"] for row in response.json()["data"]]
```

普通字符串、字符串数组、`encoding_format="base64"` 与现有接口兼容。
图文对象是本服务的扩展，**不是 OpenAI 标准 embedding 输入格式**。返回顺序与输入一致，
`usage.prompt_tokens` 包含系统模板和图像占位 token。单条超出编译长度时返回 400，
不截断输入。每批最多 64 条；图像限 JPEG/PNG data URL，每条一张、单张 4 MiB，
每批最多 16 张、合计 16 MiB；原图解码尺寸最多 16,777,216 像素。
URL、文件路径、视频和未知字段返回 400。

可选 `instruction` 会作为全批的系统指令，去除首尾空白并在末尾缺少标点时补句号；
默认是 `Represent the user's input.`。因此不应手动把旧 Qwen3-Embedding 的
`Instruct: ...\nQuery: ...` 模板拼到这个模型输入前。

默认编译保留官方 1310720 图片预算。较小的 `--max-pixels 262144` 是性能候选：
FP32 小样本对拍中，2048 维文字→图片 Recall@1 从 31/32 降至 30/32，
且图像向量最低余弦只有 0.9328；不能把它视为无损优化。两种预算均已完成同预算 FP32 真机对拍；默认保留官方预算。

控制台「对话测试」选择此模型后可为每条输入附图，支持图片独立输入及图文相似度矩阵。
不同 embedding 模型族不能混用向量；手工安装的模型仍以自身模型 id 作为向量族，
切换模型应重建索引。

## 运行约束

所有前向共享同一个原生 encoder，并通过现有辅助模型队列串行执行。
请求取消后，已经提交的设备工作先完成再释放队列名额；卸载需等待在途工作结束。
批内所有输入先完成分词、图像校验和长度检查，再开始第一条 NPU 推理。
设备 launch / sync / copy 出错后引擎标记 fault，后续请求不再使用该句柄。

图像预处理使用官方 Torchvision 路径的融合归一化，且保持已有聊天模型的旧路径。
逐位 golden 覆盖 JPEG、PNG、灰度、调色板、透明图、小图和极端宽高比。
