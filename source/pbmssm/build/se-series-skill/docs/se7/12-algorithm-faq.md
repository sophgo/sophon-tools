---
title: 算法移植FAQ
description: 算法移植常见问题
tableOfContents:
  maxHeadingLevel: 3
sidebar:
  hidden: true
---

## 通用问题

### 如何安装 SAIL？

```
pip3 install dfss --upgrade
python3 -m dfss --install sail
```

### 如何自动保存 SAIL/BMRT 推理的 input 和 output 数据？

```bash
# BMRT
export BMRT_SAVE_IO_TENSORS=1
# SAIL
export SAIL_SAVE_IO_TENSORS=1
```

### SAIL 如何自动打印推理、s2d、d2s 等操作的时间？

在代码中添加：

```bash
sail.set_print_flag(1);
```

### C++ 中如何将 BMImage/tensor 转成 mat ？

```
// BMImage转mat
cv::Mat temp_img = bm_cv.bm_image_to_mat(temp_bmimg);
cout << "count = " << sum(temp_img) <<endl;

// tensor转mat
sail::BMImage temp_bmimg = bm_cv.tensor_to_bm_image(in, false);
cv::Mat temp_img = bm_cv.bm_image_to_mat(temp_bmimg);
cout << "count = " << sum(temp_img) <<endl;
```

### BMCV 使用 bmcv_image_vpp_convert 返回 BM_NOT_SUPPORTED 如何解决？

可能是 crop_rect 设置的尺寸超过原图尺寸，需调整 crop_rect 参数至原图尺寸范围内。

### C++ 程序运行一段时间后 bm_mem_mmap_device_mem 返回失败

用 top 查看虚拟内存，判断是否存在内存泄漏；

检查代码中 mmap 接口是否对应调用 unmap

### 使用sail.EngineImagePreProcess进行推理，内存一直增加。

调用GetBatchData获取结果后，得手动释放设备内存。如果使用sail配套的后处理接口，可以使用release_input参数进行内存释放。

```python
output_array, ost_images, channels, image_idxs, padding_attrs = sail_eipp.GetBatchData()
    for out_tensor in output_array:
        sail.ReleaseTensorPtr(out_tensor)
```

### 特定图片使用sail.Decoder解码后BMImage内存不连续，导致bm_image_to_tensor报错。

可以使用bmcv.vpp_convert_format接口转成内存连续的BMImage。

### qwen3-vl运行时随机kill进程再重启出现tpu hang。

尽量使用静态模型，并且应确保推理线程已回收，内存已释放再重启。

### 算能适配sam3了吗？

【2026.03.30】只适配到sam2，还未适配sam3。

### 盒子上`import torch`后出现`Illegal instruction`。

PyTorch版本和CPU 指令集不兼容，不要指定版本重新安装pytorch后解决。

### bm1688 soc 能不能用bm1684X的SDK?

不行。

### SE9和SE7可以共用同一个sail包吗？

不行，并且sail包与sdk版本一一对应。

### 包含3D卷积的模型量化时出现`nodechip_conv3d_quant_local: Assertion "dilation[0] == 1" failed.`

3dconv不支持 int8 dilation>1，导致量化失败，最新的tpu-mlir已解决该问题。

### 如何升级tpu-mlir版本？

在模型编译环境内运行`pip3 install -U tpu_mlir`。

### sail.set_decoder_env设置的超时时间是连接超时，还是解码超时？

sail.set_decoder_env设置的是连接超时时间。

### YOLO26模型转F16 bmodel后精度差。

首先应根据sophon-demo的文档（https://github.com/sophgo/sophon-demo/blob/release/sample/YOLO26/docs/YOLO26_Calibration_Guide.md）生成qtable，混合精度编译F16 bmodel。

其次检查tpu_mlir的版本是否是最新的(v1.27以上)。

### v25.03.01的SDK，3.7.0版本的sail，同一个视频使用python sail.Decoder解码的帧数比opencv读取视频的帧数少。

sdk刷成LTS-SP4或LTS-SP5，装3.11.0版本的sail后解决。

### 在sophon-stream中运行yolov5，后处理采用tpu_kernel加速的话，模型输出只支持三输出吗，输出维度需要满足什么条件？

只支持三输出，每个输出包含BCHW4个维度。

### 如何在编译链接算能库的C++程序？

盒子默认包含libsophon的头文件，通常需要补充安装sophon-opencv和sophon-ffmpeg的头文件。具体方法：

从算能SDK中下面的sophon-mw下载sophon-mw-soc-sophon-ffmpeg-dev_X.X.X_arm64.deb和sophon-mw-soc-sophon-opencv-dev_X.X.X_arm64.deb，拷贝至盒子上安装。

### 同时运行bmcv_base64_enc接口和bmrt_launch_tensor_ex接口，设备卡死重启。

同时跑tpu和spacc会导致芯片总线挂掉，需添加硬件锁解决。LTS-SP5及以上版本已解决。

### bmcv_image_put_text无法支持中文渲染。

LTS-SP5及以上版本已解决。

### bmcv_image_put_text渲染中文出现乱码。

开启中文字库需要将thickness设置为0。

### 客户基于tpu-kernel开发了一个自定义算子，如果同时调用官方的算子和自定义的算子？
不需要重新编译libbm1684x_kernel_module.so，使用TPUKERNEL_FUNC_REGISTER注册自定义算子函数（具体可参考tpu-kernel开发包下samples/device代码），然后参考TPU-KERNEL函数使用说明（https://doc.sophgo.com/sdk-docs/v23.09.01-lts-sp5/docs_latest_release/docs/tpu_kernel/quick_start/html/usage.html#id10）进行调用。

### 客户在SE7(python版本 3.8.2)上使用sophon-demo的Audio_assistant(https://github.com/sophgo/sophon-demo/blob/release/application/Audio_assistant/python)，安装`torch`失败。
日志：`ERROR: Package 'typing-extensions' requires a different Python: 3.8.2 not in '>=3.9'`。
解决办法：
先指定版本安装`typing-extensions`
```
pip3 install typing-extensions==4.12.2
```
再安装`torch`
```
pip3 install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 --index-url https://downlo       ad.pytorch.org/whl/cpu
```

### 客户在SE7(python版本 3.8.2)上使用sophon-demo的Audio_assistant(https://github.com/sophgo/sophon-demo/blob/release/application/Audio_assistant/python)，安装编译`hf-xet`失败。
日志：`ERROR: Command errored out with exit status 1: /usr/bin/python3 /usr/lib/python3/dist-packages/pip install --ignore-installed --no-user --prefix /tmp/pip-build-env-yjets6k4/normal --no-warn-script-location --no-binary :none: --only-binary :none: -i https://pypi.org/simple -- puccinialin Check the logs for full command output.'`。
解决办法：先装好`huggingface_hub` 0.29.0，再走 requirements.txt，不需要安装`hf-xet`
```
pip3 install huggingface_hub==0.29.0
pip3 install transformers==4.30.2 sentencepiece
pip3 install -r requirements.txt
```

### 某算法使用全F16精度下降明显，使用混精后精度正常，但推理速度比全F16慢10%，如何优化。
可以尝试用int8量化提升速度，并使用混精优化精度。

### SE7 32-EP1-21用memory_edit.sh修改内存分布无法生效。
需要指定dts name
