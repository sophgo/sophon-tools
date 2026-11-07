# BM1688 SDK 使用

## tpu-mlir 编译模型

BM1688 的模型编译走 tpu-mlir：先用 `model_transform.py` 把 ONNX 转成 MLIR，
再用 `model_deploy.py` 按目标芯片生成 bmodel。BM1688 需要指定 `--chip bm1688`。
