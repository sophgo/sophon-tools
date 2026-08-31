# 法律声明

**法律声明**
版权所有 © 算能 2025. 保留一切权利。
非经本公司书面许可, 任何单位和个人不得擅自摘抄、复制本文档内容的部分或全部, 并不得以任何形式传播。

**注意**
您购买的产品、服务或特性等应受算能商业合同和条款的约束, 本文档中描述的全部或部分产品、服务或特性可能不在您的购买或使用范围之内。除非合同另有约定, 算能对本文档内容不做任何明示或默示的声明或保证。由于产品版本升级或其他原因, 本文档内容会不定期进行更新。除非另有约定, 本文档仅作为使用指导, 本文档中的所有陈述、信息和建议不构成任何明示或暗示的担保。

**技术支持**

地址: 北京市海淀区丰豪东路9号院中关村集成电路设计园(ICPARK)1号楼
邮编: 100094
网址: https://www.sophgo.com/
邮箱: sales@sophgo.com
电话: 010-57590723

**发布记录**

| 版本 | 发布日期 | 说明 |
|------|----------|------|
| v1.19.0 | 2025.05.30 | 支持AWQ与GPTQ模型; 修复Deconv3D F16, F32精度问题 |
| v1.18.0 | 2025.05.01 | yolo系列增加自动混精设置; run_calibration增加SmoothQuant选择; 新增llm一键编译脚本 |
| v1.17.0 | 2025.04.03 | LLM模型编译速度大幅提升; TPULang支持PPL算子接入; 修复Trilu bf16在Mars3上随机出错问题 |
| v1.16.0 | 2025.03.03 | TPULang ROI_Extractor支持; Einsum支持 abcde,abfge->abcdfg模式; LLMC支持Vila模型 |
| v1.15.0 | 2025.02.05 | 支持LLMC量化; codegen地址越界判断; 修复若干对比问题 |
| v1.14.0 | 2025.01.02 | yolov8/v11后处理融合支持; Conv3D stride大于15支持; FAttention精度提升 |
| v1.13.0 | 2024.12.02 | 精简Release发布包; MaxPoolWithMask训练算子性能优化; RoPE大算子支持 |
| v1.12.0 | 2024.11.06 | tpuv7-runtime cmodel接入; BM1690多核LayerGroup优化; 支持PPL编写后端算子 |
| v1.11.0 | 2024.09.27 | BM1688 tdb增加soc模式; bmodel支持细粒度合并; 修复若干性能下降问题 |
| v1.10.0 | 2024.08.15 | 支持yolov10; 增加量化调优章节; 优化tpu-perf日志打印 |
| v1.9.0 | 2024.07.16 | BM1690新增40个模型回归测试; 量化算法新增octav,aciq_guas和aciq_laplace |
| v1.8.0 | 2024.05.30 | BM1690支持多核MatMul算子; TPULang支持输入输出顺序指定; tpuperf移除patchelf依赖 |
| v1.7.0 | 2024.05.15 | CV186X双核修改为单核; BM1690测试流程与BM1684X一致; 支持gemma/llama/qwen等模型 |
| v1.6.0 | 2024.02.23 | 添加了Pypi发布形式; 支持用户自定义Global算子; 支持了CV186X处理器平台 |
| v1.5.0 | 2023.11.03 | 更多Global Layer支持多核并行 |
| v1.4.0 | 2023.09.27 | 系统依赖升级到Ubuntu22.04; 支持了BM1684 Winograd |
| v1.3.0 | 2023.07.27 | 增加手动指定浮点运算区域功能; 添加支持的前端框架算子列表; 添加NNTC与TPU-MLIR量化方式比较 |
| v1.2.0 | 2023.06.14 | 调整了混合量化示例 |
| v1.1.0 | 2023.05.26 | 添加使用智能深度学习处理器做后处理 |
| v1.0.0 | 2023.04.10 | 支持PyTorch, 增加章节介绍转PyTorch模型 |
| v0.8.0 | 2023.02.28 | 添加使用智能深度学习处理器做前处理 |
| v0.6.0 | 2022.11.05 | 增加章节介绍混精度操作过程 |
| v0.5.0 | 2022.10.20 | 增加指定model-zoo, 测试其中的所有模型 |
| v0.4.0 | 2022.09.20 | 支持Caffe, 增加章节介绍转Caffe模型 |
| v0.3.0 | 2022.08.24 | 支持TFLite, 增加章节介绍转TFLite模型 |
| v0.2.0 | 2022.08.02 | 增加了运行SDK中的测试样例章节 |
| v0.1.0 | 2022.07.29 | 初版发布, 支持 `resnet/mobilenet/vgg/ssd/yolov5s` , 并用yolov5s作为用例 |

# 开发环境配置

本章介绍开发环境配置, 代码在Docker中编译和运行。

## 代码下载

代码路径: https://github.com/sophgo/tpu-mlir

克隆该代码后, 需要在Docker中编译。参考下文配置Docker。

## Docker配置

TPU-MLIR在Docker环境开发, 配置好Docker就可以编译和运行了。

从 DockerHub https://hub.docker.com/r/sophgo/tpuc_dev 下载所需的镜像:

```shell
$ docker pull sophgo/tpuc_dev:v3.4
```

若下载失败，可从官网开发资料 https://developer.sophgo.com/site/index/material/86/all.html 下载所需镜像文件，或使用下方命令下载镜像：

```shell
$ wget https://sophon-assets.sophon.cn/sophon-prod-s3/drive/25/04/15/16/tpuc_dev_v3.4.tar.gz
$ docker load -i tpuc_dev_v3.4.tar.gz
```

如果是首次使用Docker, 可执行下述命令进行安装和配置(仅首次执行):

```shell
$ sudo apt install docker.io
$ sudo systemctl start docker
$ sudo systemctl enable docker
$ sudo groupadd docker
$ sudo usermod -aG docker $USER
$ newgrp docker
```

确保安装包在当前目录, 然后在当前目录创建容器如下:

```shell
$ docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:v3.4
# myname只是举个名字的例子, 请指定成自己想要的容器的名字
# 使用 --privileged 参数以获取root权限，如果不需要root权限，请删除该参数
```

注意TPU-MLIR工程在Docker中的路径应该是/workspace/tpu-mlir

## ModelZoo(可选)

TPU-MLIR中自带yolov5s模型, 如果要跑其他模型, 需要下载ModelZoo, 路径如下:

https://github.com/sophgo/model-zoo

下载后放在与tpu-mlir同级目录, 在Docker中的路径应该是/workspace/model-zoo

## 代码编译

在Docker的容器中, 代码编译方式如下:

```shell
$ cd tpu-mlir
$ source ./envsetup.sh
$ ./build.sh
```

回归验证, 如下:

```shell
# 本工程包含yolov5s.onnx模型, 可以直接用来验证
$ pushd regression
$ python run_model.py yolov5s
$ popd
```

如果要验证更多网络, 需要依赖model-zoo, 回归时间比较久。

操作如下: (可选)

```shell
# 执行时间很长, 该步骤也可以跳过
$ pushd regression
$ ./run_all.sh
$ popd
```

# 用户界面

本章介绍用户的使用界面, 包括转换模型的基本过程, 和各类工具的使用方法。

## 模型转换过程

基本操作过程是用 `model_transform.py` 将模型转成mlir文件，然后用 `model_deploy.py` 将mlir转成对应的model。以 `somenet.onnx` 模型为例，操作步骤如下：

```shell
# To MLIR
$ model_transform.py \
    --model_name somenet \
    --model_def  somenet.onnx \
    --test_input somenet_in.npz \
    --test_result somenet_top_outputs.npz \
    --mlir somenet.mlir

# To Float Model
$ model_deploy.py \
   --mlir somenet.mlir \
   --quantize F32 \ # F16/BF16
   --processor BM1684X \
   --test_input somenet_in_f32.npz \
   --test_reference somenet_top_outputs.npz \
   --model somenet_f32.bmodel
```

### 支持图片输入

当用图片作为输入的时候, 需要指定预处理信息, 如下:

```shell
$ model_transform.py \
    --model_name img_input_net \
    --model_def img_input_net.onnx \
    --input_shapes [[1,3,224,224]] \
    --mean 103.939,116.779,123.68 \
    --scale 1.0,1.0,1.0 \
    --pixel_format bgr \
    --test_input cat.jpg \
    --test_result img_input_net_top_outputs.npz \
    --mlir img_input_net.mlir
```

### 支持多输入

当模型有多输入的时候, 可以传入1个npz文件, 或者按顺序传入多个npy文件, 用逗号隔开。如下:

```shell
$ model_transform.py \
    --model_name multi_input_net \
    --model_def  multi_input_net.onnx \
    --test_input multi_input_net_in.npz \ # a.npy,b.npy,c.npy
    --test_result multi_input_net_top_outputs.npz \
    --mlir multi_input_net.mlir
```

### 支持INT8对称和非对称

如果需要转INT8模型, 则需要进行calibration。如下:

```shell
$ run_calibration.py somenet.mlir \
    --dataset dataset \
    --input_num 100 \
    -o somenet_cali_table
```

传入校准表生成模型, 如下:

```shell
$ model_deploy.py \
   --mlir somenet.mlir \
   --quantize INT8 \
   --calibration_table somenet_cali_table \
   --processor BM1684X \
   --test_input somenet_in_f32.npz \
   --test_reference somenet_top_outputs.npz \
   --tolerance 0.9,0.7 \
   --model somenet_int8.bmodel
```

### 支持混精度

当INT8模型精度不满足业务要求时, 可以尝试使用混精度, 先生成量化表, 如下:

```shell
$ run_calibration.py somenet.mlir \
    --dataset dataset \
    --input_num 100 \
    --inference_num 30 \
    --expected_cos 0.99 \
    --calibration_table somenet_cali_table \
    --processor BM1684X \
    --search search_qtable \
    --quantize_method_list KL,MSE\
    --quantize_table somenet_qtable
```

然后将量化表传入生成模型, 如下:

```shell
$ model_deploy.py \
   --mlir somenet.mlir \
   --quantize INT8 \
   --calibration_table somenet_cali_table \
   --quantize_table somenet_qtable \
   --processor BM1684X \
   --model somenet_mix.bmodel
```

# 支持量化模型TFLite

支持TFLite模型的转换，命令参考如下：

```shell
# TFLite转模型举例
$ model_transform.py \
    --model_name resnet50_tf \
    --model_def  ../resnet50_int8.tflite \
    --input_shapes [[1,3,224,224]] \
    --mean 103.939,116.779,123.68 \
    --scale 1.0,1.0,1.0 \
    --pixel_format bgr \
    --test_input ../image/dog.jpg \
    --test_result resnet50_tf_top_outputs.npz \
    --mlir resnet50_tf.mlir

$ model_deploy.py \
    --mlir resnet50_tf.mlir \
    --quantize INT8 \
    --processor BM1684X \
    --test_input resnet50_tf_in_f32.npz \
    --test_reference resnet50_tf_top_outputs.npz \
    --tolerance 0.95,0.85 \
    --model resnet50_tf_1684x.bmodel
```

# 支持Caffe模型

```shell
# Caffe转模型示例
$ model_transform.py \
    --model_name resnet18_cf \
    --model_def  ../resnet18.prototxt \
    --model_data ../resnet18.caffemodel \
    --input_shapes [[1,3,224,224]] \
    --mean 104,117,123 \
    --scale 1.0,1.0,1.0 \
    --pixel_format bgr \
    --test_input ../image/dog.jpg \
    --test_result resnet50_cf_top_outputs.npz \
    --mlir resnet50_cf.mlir
```

# 支持LLM模型

```shell
$ llm_convert.py \
    -m /workspace/Qwen2.5-VL-3B-Instruct-AWQ \
    -s 2048 \
    -q w4bf16 \
    -c bm1684x \
    --max_pixels 672,896 \
    -o qwen2.5vl_3b
```

# 工具参数介绍

## model_transform.py

用于将各种神经网络模型转换成MLIR文件（`.mlir`后缀）以及配套的权重文件（`${model_name}_top_${quantize}_all_weight.npz`），支持的参数如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_name | 是 | 指定模型名称 |
| model_def | 是 | 指定模型定义文件，比如 `.onnx` 或 `.tflite` 或 `.prototxt` 文件 |
| mlir | 是 | 指定输出的mlir文件名称和路径，`.mlir` 后缀 |
| input_shapes | 否 | 指定输入的shape，例如 `[[1,3,640,640]]`；二维数组，可以支持多输入情况 |
| model_extern | 否 | 其他模型定义文件，用于与model_def模型合并（目前主要用于MaskRCNN功能），默认处理为None；多个输入模型文件时，用 `,` 隔开 |
| model_data | 否 | 指定模型权重文件，caffe模型需要，对应 `.caffemodel` 文件 |
| input_types | 否 | 当模型为 `.pt` 文件时指定输入的类型，例如int32；多输入用 `,` 隔开；不指定情况下默认处理为float32 |
| keep_aspect_ratio | 否 | 当test_input与input_shapes不同时，在resize时是否保持长宽比，默认为false；设置时会对不足部分补0 |
| mean | 否 | 图像每个通道的均值，默认为 0.0,0.0,0.0 |
| scale | 否 | 图片每个通道的比值，默认为 1.0,1.0,1.0 |
| pixel_format | 否 | 图片类型，可以是rgb、bgr、gray、rgbd四种情况，默认为bgr |
| channel_format | 否 | 通道类型，对于图片输入可以是nhwc或nchw，非图片输入则为none，默认是nchw |
| output_names | 否 | 指定输出的名称，如果不指定，则用模型的输出；指定后按照该指定名称的顺序做输出 |
| add_postprocess | 否 | 将后处理融合到模型中，指定后处理类型，目前支持yolov3、yolov3_tiny、yolov5、yolov8、yolov11、ssd、yolov8_seg后处理 |
| test_input | 否 | 指定输入文件用于验证，可以是jpg或npy或npz；可以不指定，则不会正确性验证 |
| test_result | 否 | 指定验证后的输出文件，`.npz` 格式 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用 `,` 隔开 |
| onnx_sim | 否 | onnx-sim 的可选项参数，目前仅支持 skip_fuse_bn 选项，用于关闭 batch_norm 和 Conv 层的合并 |
| debug | 否 | 保存可用于debug的模型 |
| tolerance | 否 | 模型转换的余弦与欧式相似度的误差容忍度，默认为0.99,0.99 |
| cache_skip | 否 | 是否在生成相同mlir/bmodel时跳过正确性的检查 |
| dynamic_shape_input_names | 否 | 具有动态shape的输入的名称列表，例如input1,input2。如果设置了，model_deploy需要设置参数'dynamic' |
| shape_influencing_input_names | 否 | 在推理过程中会影响其他张量形状的输入的名称列表，例如input1,input2。如果设置了，则必须指定test_input，且model_deploy需要设置参数'dynamic' |
| dynamic | 否 | 该参数只对onnx模型有效。如果设置了，工具链会自动将模型带有dynamic_axis的输入加入dynamic_shape_input_names列表中，将模型中1维的输入加入shape_influencing_input_names列表中，且model_deploy需要设置参数'dynamic' |
| resize_dims | 否 | 图像缩放到指定的固定尺寸h/w，缺省时为输入图像本身尺寸 |
| pad_value | 否 | 图片缩放时边框填充大小 |
| pad_type | 否 | 图片缩放时的填充类型，有normal, center |
| preprocess_list | 否 | 输入是否需要做预处理的选项，例如:'1,3' 表示输入1&3需要进行预处理，缺省代表所有输入要做预处理 |
| path_yaml | 否 | 单个 yaml文件 的路径（当前主要用于MaskRCNN参数配置） |
| enable_maskrcnn | 否 | 是否启用 MaskRCNN大算子 |

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是后续模型的输入文件。

注意：

1. `model_transform.py` 阶段输入的预处理参数会用于对 `test_input` 进行预处理，并且会记录到 `mlir` 文件中，后续执行 `run_calibration.py` 时会读取该预处理参数对校准数据集进行预处理。若 `model_transform.py` 阶段没有对应参数输入将可能影响到模型的实际量化效果。

2. 预处理参数计算方式：

```
input = scale × (input - mean)
scale = 1/(255 × std)
```

## run_calibration.py

用少量的样本做calibration，得到网络的校准表，即每一层op的threshold/min/max。

支持的参数如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| 无 | 是 | 指定mlir文件 |
| sq | 否 | SmoothQuant |
| we | 否 | 跨层权重均衡 |
| bc | 否 | 偏差校正 |
| dataset | 否 | 指定输入样本的目录，该路径放对应的图片，或npz，或npy |
| data_list | 否 | 指定样本列表，与dataset必须二选一 |
| input_num | 否 | 指定校准数量，如果为0，则使用全部样本 |
| inference_num | 否 | search_threshold 和 search_qtable 过程中所需推理图片数量，通常小于input_num |
| bc_inference_num | 否 | 偏差校正过程中所需推理图片数量 |
| tune_num | 否 | 指定微调样本数量，默认为10 |
| tune_list | 否 | 指定微调样本文件 |
| histogram_bin_num | 否 | 直方图bin数量，默认2048 |
| expected_cos | 否 | 期望search_qtable混精模型输出与浮点模型输出的相似度，取值范围[0,1] |
| min_layer_cos | 否 | bias_correction中该层量化输出与浮点输出的相似度下限，当低于该下限时需要对该层进行补偿，取值范围[0,1] |
| max_float_layers | 否 | search_qtable 浮点层数量 |
| processor | 否 | 处理器类型 |
| cali_method | 否 | 选择量化门限计算方法 |
| fp_type | 否 | search_qtable浮点层数据类型 |
| post_process | 否 | 后处理路径 |
| global_compare_layers | 否 | 指定全局对比层，例如 layer1,layer2 或 layer1:0.3,layer2:0.7 |
| search | 否 | 指定搜索类型，其中包括search_qtable,search_threshold,false。其中默认为false，不开启搜索 |
| transformer | 否 | 是否是transformer模型，search_qtable中如果是transformer模型可分配指定加速策略 |
| quantize_method_list | 否 | search_qtable用来搜索的门限方法 |
| benchmark_method | 否 | 指定search_threshold中相似度计算方法 |
| kurtosis_analysis | 否 | 指定生成各层激活值的kurtosis |
| part_quantize | 否 | 指定模型部分量化，获得cali_table同时会自动生成qtable。可选择N_mode,H_mode,custom_mode,H_mode通常精度较好 |
| custom_operator | 否 | 指定需要量化的算子，配合开启上述custom_mode后使用 |
| part_asymmetric | 否 | 指定当开启对称量化后，模型某些子网符合特定pattern时，将对应位置算子改为非对称量化 |
| mix_mode | 否 | 指定search_qtable特定的混精类型，目前支持8_16和4_8两种 |
| cluster | 否 | 指定search_qtable寻找敏感层时采用聚类算法 |
| quantize_table | 否 | search_qtable输出的混精度量化表 |
| o | 是 | 输出calibration table文件 |
| debug_cmd | 否 | debug cmd |
| debug_log | 否 | 日志输出级别 |

校准表的样板如下：

```shell
# genetated time: 2022-08-11 10:00:59.743675
# histogram number: 2048
# sample number: 100
# tune number: 5
###
# op_name    threshold    min    max
images 1.0000080 0.0000000 1.0000080
122_Conv 56.4281803 -102.5830231 97.6811752
124_Mul 38.1586478 -0.2784646 97.6811752
125_Conv 56.1447888 -143.7053833 122.0844193
127_Mul 116.7435987 -0.2784646 122.0844193
128_Conv 16.4931355 -87.9204330 7.2770605
130_Mul 7.2720342 -0.2784646 7.2720342
......
```

它分为4列：第一列是Tensor的名字；第二列是阈值（用于对称量化）；第三列第四列是min/max，用于非对称量化。

## model_deploy.py

将mlir文件转换成相应的model，参数说明如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定mlir文件 |
| processor | 是 | 指定模型将要用到的平台，支持BM1684，BM1684X，BM1688，BM1690，CV186X，CV183X，CV182X，CV181X，CV180X |
| quantize | 是 | 指定默认量化类型，支持F32/F16/BF16/INT8等，不同处理器支持的量化类型如下表所示 |
| quant_input | 否 | 指定输入数据类型是否与量化类型一致，例如int8模型指定quant_input，那么输入数据类型也为int8，若不指定则为F32 |
| quant_output | 否 | 指定输出数据类型是否与量化类型一致，例如int8模型指定quant_input，那么输出数据类型也为int8，若不指定则为F32 |
| quant_input_list | 否 | 选择要转换的索引，例如 1,3 表示第一个和第三个输入的强制转换 |
| quant_output_list | 否 | 选择要转换的索引，例如 1,3 表示第一个和第三个输出的强制转换 |
| quantize_table | 否 | 指定混精度量化表路径，如果没有指定则按quantize类型量化；否则优先按量化表量化 |
| fuse_preprocess | 否 | 指定是否将预处理融合到模型中，如果指定了此参数，则模型输入为uint8类型，直接输入resize后的原图即可 |
| calibration_table | 否 | 指定校准表路径，当存在INT8/F8E4M3量化的时候需要校准表 |
| high_precision | 否 | 打开时一部分算子会固定用float32 |
| tolerance | 否 | 表示 MLIR 量化后的结果与 MLIR fp32推理结果余弦与欧式相似度的误差容忍度，默认为0.8,0.5 |
| test_input | 否 | 指定输入文件用于验证，可以是jpg或npy或npz；可以不指定，则不会正确性验证 |
| test_reference | 否 | 用于验证模型正确性的参考数据（使用npz格式）。其为各算子的计算结果 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| op_divide | 否 | CV183x/CV182x/CV181x/CV180x only，尝试将较大的op拆分为多个小op以达到节省ion内存的目的，适用少数特定模型 |
| model | 是 | 指定输出的model文件名称和路径 |
| debug | 否 | 是否保留中间文件 |
| asymmetric | 否 | 指定做int8非对称量化 |
| dynamic | 否 | 动态编译 |
| includeWeight | 否 | tosa.mlir 的 includeWeight |
| customization_format | 否 | 指定模型输入帧的像素格式 |
| compare_all | 否 | 指定对比模型所有的张量 |
| num_device | 否 | 用于并行计算的设备数量，默认1 |
| num_core | 否 | 用于并行计算的智能视觉深度学习处理器核心数量，默认1 |
| skip_validation | 否 | 跳过检查 bmodel 的正确性 |
| merge_weight | 否 | 将权重与之前生成的 cvimodel 合并为一个权重二进制文件，默认否 |
| model_version | 否 | 如果需要旧版本的cvimodel，请设置版本，例如1.2，默认latest |
| q_group_size | 否 | 每组定量的组大小，仅用于 W4A16/W8A16 定量模式，默认0 |
| q_symmetric | 否 | 指定做W4A16对称量化，仅用于 W4A16/W8A16 定量模式 |
| compress_mode | 否 | 指定模型的压缩模式："none","weight","activation","all"。支持bm1688，默认为"none"，不进行压缩 |
| opt_post_processor | 否 | 是否对LayerGroup的结果继续图优化，支持mars3，默认为"none"，不进行 |
| lgcache | 否 | 指定是否暂存 LayerGroup 的切分结果： "true", "false"。默认为"true"，将每个子网的切分结果保存到工作目录 "cut_result_{subnet_name}.mlircache" |
| cache_skip | 否 | 是否在生成相同mlir/bmodel时跳过正确性的检查 |
| aligned_input | 否 | 是否输入图像的宽/通道是对齐的，仅用于CV系列处理器的VPSS输入对齐 |
| group_by_cores | 否 | layer groups是否根据core数目进行强制分组，可选auto/true/false，默认为auto |
| opt | 否 | LayerGroup优化类型，可选1/2/3，默认为2。1：简单LayerGroup模式，所有算子会尽可能做Group，编译速度较快；2：通过动态编译计算全局cycle最优的Group分组，适用于推理图编译；3：线性规划LayerGroup模式，适用于模型训练图编译 |
| addr_mode | 否 | 设置地址分配模式['auto', 'basic', 'io_alone', 'io_tag', 'io_tag_fuse']，默认为auto |
| disable_layer_group | 否 | 是否关闭LayerGroup |
| disable_gdma_check | 否 | 是否关闭gdma地址检查 |
| do_winograd | 否 | 是否使用WinoGrad卷积，仅用于BM1684平台 |
| matmul_perchannel | 否 | MatMul是否使用per-channel量化模式，目前支持BM1684X和BM1688处理器，打开可能影响运行时间 |
| enable_maskrcnn | 否 | 是否启用 MaskRCNN大算子 |

# 不同处理器支持的量化类型

对于不同处理器和支持的量化类型对应关系如下表所示：

| 处理器 | 支持的quantize |
|--------|----------------|
| BM1684 | F32, INT8 |
| BM1684X | F32, F16, BF16, INT8, W4F16, W8F16, W4BF16, W8BF16 |
| BM1688 | F32, F16, BF16, INT8, INT4, W4F16, W8F16, W4BF16, W8BF16 |
| BM1690 | F32, F16, BF16, INT8, F8E4M3, F8E5M2, W4F16, W8F16, W4BF16, W8BF16 |
| CV186X | F32, F16, BF16, INT8, INT4 |
| CV183X, CV182X, CV181X, CV180X | BF16, INT8 |

其中，`W4A16` 与 `W8A16` 的 `Weight-only` 量化模式仅作用于 MatMul 运算，其余算子根据实际情况仍会进行 `F16` 或 `BF16` 量化。

## llm_convert.py

用于将HuggingFace LLM模型转换成bmodel，支持的参数如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_path | 是 | 指定模型路径 |
| seq_length | 是 | 指定序列最大长度 |
| quantize | 是 | 指定量化类型，如w4bf16/w4f16/bf16/f16 |
| q_group_size | 否 | 每组量化的组大小 |
| chip | 是 | 指定处理器类型，支持bm1684x/bm1688/cv186ah |
| max_pixels | 否 | 多模态参数，指定最大尺寸，可以是 `672,896`，也可以是 `602112` |
| num_device | 否 | 指定 bmodel 部署的设备数 |
| num_core | 否 | 指定 bmodel 部署使用的核数，0表示采用最大核数 |
| embedding_disk | 否 | 如果设置该标志，则将word_embedding导出为二进制文件，并通过 CPU 进行推理 |
| out_dir | 是 | 指定输出的 bmodel 文件保存路径 |

## model_runner.py

对模型进行推理，支持mlir/pytorch/onnx/tflite/bmodel/prototxt。

执行参考如下：

```shell
$ model_runner.py \
   --input sample_in_f32.npz \
   --model sample.bmodel \
   --output sample_output.npz \
   --out_fixed
```

支持的参数如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| input | 是 | 指定模型输入，npz文件 |
| model | 是 | 指定模型文件，支持mlir/pytorch/onnx/tflite/bmodel/prototxt |
| dump_all_tensors | 否 | 开启后对导出所有的结果，包括中间tensor的结果 |
| out_fixed | 否 | 开启后当出现int8类型定点数时不再自动转成float32类型进行打印 |

## npz_tool.py

npz在TPU-MLIR工程中会大量用到，包括输入输出的结果等等。npz_tool.py用于处理npz文件。

执行参考如下：

```shell
# 查看sample_out.npz中output的数据
$ npz_tool.py dump sample_out.npz output
```

支持的功能如下：

| 功能 | 描述 |
|------|------|
| dump | 得到npz的所有tensor信息 |
| compare | 比较2个npz文件的差异 |
| to_dat | 将npz导出为dat文件，连续的二进制存储 |

## visual.py

量化网络如果遇到精度对比不过或者比较差，可以使用此工具逐层可视化对比浮点网络和量化后网络的不同，方便进行定位和手动调整。

执行命令可参考如下：

```shell
# 以使用9999端口为例
$ visual.py \
  --f32_mlir netname.mlir \
  --quant_mlir netname_int8_sym_tpu.mlir \
  --input top_input_f32.npz --port 9999
```

支持的功能如下：

| 功能 | 描述 |
|------|------|
| f32_mlir | fp32网络mlir文件 |
| quant_mlir | 量化后网络mlir文件 |
| input | 测试输入数据，可以是图像文件或者npz文件 |
| port | 使用的TCP端口，默认10000，需要在启动docker时映射至系统端口 |
| host | 使用的host ip地址，默认0.0.0.0 |
| manual_run | 启动后是否自动进行网络推理比较，默认False，会自动推理比较 |

注意：需要在model_deploy.py阶段打开 `--debug` 选项保留中间文件供visual.py使用，工具的详细使用说明见(:ref:`visual-usage`)。

## mlir2graph.py

基于 dot 对 mlir 文件可视化，支持所有阶段的 mlir 文件。执行后会在 mlir 对应目录生成对应的 .dot 文件和 .svg 文件。其中 .dot 文件可以基于 dot 渲染成其他格式的命令。.svg 是默认输出的渲染格式。可以直接在浏览器打开。

执行命令可参考如下：

```shell
$ mlir2graph.py \
  --mlir netname.mlir
```

对较大的 mlir 文件，dot 文件使用原始的渲染算法可能会消耗较长的时间，可以添加 --is_big 参数，会减少算法的迭代时间，出图更快：

```shell
$ mlir2graph.py \
  --mlir netname.mlir --is_big
```

支持的功能如下：

| 功能 | 描述 |
|------|------|
| mlir | 任意 mlir 文件 |
| is_big | 是否是比较大的 mlir 文件，没有明确指标，一般靠人为根据渲染用时判断 |
| failed_keys | 对比失败的节点名列表，多个用 "," 隔开，在渲染后对应节点会渲染为红色 |
| bmodel_checker_data | 使用 bmodel_checker.py 生成的 failed.npz 文件路径，当指定该路径时，会自动解析错误节点，并将对应节点渲染为红色 |
| output | 输出文件的路径，默认为 --mlir 的路径加格式后缀，如 netname.mlir.dot/netname.mlir.svg |

## gen_rand_input.py

在模型转换时，如果不想额外准备测试数据(test_input)，可以使用此工具生成随机的输入数据，方便模型验证工作。

基本操作过程是用 `model_transform.py` 将模型转成mlir文件，此步骤不进行模型验证；接下来，用 `gen_rand_input.py` 读取上一步生成的mlir文件，生成用于模型验证的随机测试数据；最后，再次使用 `model_transform.py` 进行完整的模型转换和验证工作。

执行的命令可参考如下：

```shell
# 模型初步转换为mlir文件
$ model_transform.py \
    --model_name yolov5s  \
    --model_def ../regression/model/yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --mlir yolov5s.mlir

# 生成随机测试数据，这里生成的是伪测试图片
$ gen_rand_input.py \
    --mlir yolov5s.mlir \
    --img --output yolov5s_fake_img.png

# 完整的模型转换和验证
$ model_transform.py \
    --model_name yolov5s  \
    --model_def ../regression/model/yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --test_input yolov5s_fake_img.png    \
    --test_result yolov5s_top_outputs.npz \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --mlir yolov5s.mlir
```

更详细的使用方法可参考如下：

```shell
# 可为多个输入分别指定取值范围
$ gen_rand_input.py \
  --mlir ernie.mlir \
  --ranges [[0,300],[0,0]] \
  --output ern.npz

# 可为输入指定type类型，如不指定，默认从mlir文件中读取
$ gen_rand_input.py \
  --mlir resnet.mlir \
  --ranges [[0,300]] \
  --input_types si32 \
  --output resnet.npz

# 指定生成随机图片，不指定取值范围和数据类型
$ gen_rand_input.py \
    --mlir yolov5s.mlir \
    --img --output yolov5s_fake_img.png
```

支持的功能如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定输出的mlir文件名称和路径，`.mlir` 后缀 |
| img | 否 | 用于CV任务生成随机图片，否则生成npz文件。默认图片的取值范围为[0,255]，数据类型为'uint8'，不通过'ranges'或'input_types'更改。 |
| ranges | 否 | 指定模型输入的取值范围，以列表形式表现，如[[0,300],[0,0]]。如果指定生成图片，则不需要指定取值范围，默认[0,255]。其他情况下，需要指定取值范围。 |
| input_types | 否 | 指定模型输入的数据类型，如si32,f32。目前仅支持 'si32' 和 'f32' 类型。如果不填，默认从mlir中读取。如果指定生成图片，则不需要指定数据类型，默认'uint8'。 |
| output | 是 | 指定输出的名称 |

注意：CV相关模型通常会对输入图片进行一系列预处理，为保证模型正确性验证通过，需要用'--img'生成随机图片作为输入，不能使用随机npz文件作为输入。值得关注的是，随机输入可能会引起模型正确性验证对比不通过，特别是NLP相关模型，因此建议优先使用真实的测试数据。

## model_tool

该工具用于处理最终的模型文件"bmodel"或者"cvimodel"，所有参数及对应功能描述可通过执行以下命令查看：

```shell
$ model_tool
```

以下均以"xxx.bmodel"为例，介绍该工具的主要功能。

### 1) 查看bmodel的基本信息

执行参考如下：

```shell
$ model_tool --info xxx.bmodel
```

显示模型的基本信息，包括模型的编译版本，编译日期，模型中网络名称，输入和输出参数等等。显示效果如下：

```
bmodel version: B.2.2+v1.7.beta.134-ge26380a85-20240430
processor: BM1684X
create time: Tue Apr 30 18:04:06 2024

kernel_module name: libbm1684x_kernel_module.so
kernel_module size: 3136888
==========================================
net 0: [block_0]  static
------------
stage 0:
input: input_states, [1, 512, 2048], bfloat16, scale: 1, zero_point: 0
input: position_ids, [1, 512], int32, scale: 1, zero_point: 0
input: attention_mask, [1, 1, 512, 512], bfloat16, scale: 1, zero_point: 0
output: /layer/Add_1_output_0_Add, [1, 512, 2048], bfloat16, scale: 1, zero_point: 0
output: /layer/self_attn/Add_1_output_0_Add, [1, 1, 512, 256], bfloat16, scale: 1, zero_point: 0
output: /layer/self_attn/Transpose_2_output_0_Transpose, [1, 1, 512, 256], bfloat16, scale: 1, zero_point: 0
==========================================
net 1: [block_1]  static
------------
stage 0:
input: input_states, [1, 512, 2048], bfloat16, scale: 1, zero_point: 0
input: position_ids, [1, 512], int32, scale: 1, zero_point: 0
input: attention_mask, [1, 1, 512, 512], bfloat16, scale: 1, zero_point: 0
output: /layer/Add_1_output_0_Add, [1, 512, 2048], bfloat16, scale: 1, zero_point: 0
output: /layer/self_attn/Add_1_output_0_Add, [1, 1, 512, 256], bfloat16, scale: 1, zero_point: 0
output: /layer/self_attn/Transpose_2_output_0_Transpose, [1, 1, 512, 256], bfloat16, scale: 1, zero_point: 0

device mem size: 181645312 (weight: 121487360, instruct: 385024, runtime: 59772928)
host mem size: 0 (weight: 0, runtime: 0)
```

### 2) 合并多个bmodel

执行参考如下：

```shell
$ model_tool --combine a.bmodel b.bmodel c.bmodel -o abc.bmodel
```

将多个bmodel合并成一个bmodel，如果bmodel中存在同名的网络，则会分不同的stage。

### 3) 分解成多个bmodel

执行参考如下：

```shell
$ model_tool --extract abc.bmodel
```

将一个bmodel分解成多个bmodel，与combine命令是相反的操作。

### 4) 显示权重信息

执行参考如下：

```shell
$ model_tool --weight xxx.bmodel
```

显示不同网络的各个算子的权重范围信息，显示效果如下：

```
net 0 : "block_0", stage:0
-------------------------------
tpu.Gather : [0x0, 0x40000)
tpu.Gather : [0x40000, 0x80000)
tpu.RMSNorm : [0x80000, 0x81000)
tpu.A16MatMul : [0x81000, 0x2b1000)
tpu.A16MatMul : [0x2b1000, 0x2f7000)
tpu.A16MatMul : [0x2f7000, 0x33d000)
tpu.A16MatMul : [0x33d000, 0x56d000)
tpu.RMSNorm : [0x56d000, 0x56e000)
tpu.A16MatMul : [0x56e000, 0x16ee000)
tpu.A16MatMul : [0x16ee000, 0x286e000)
tpu.A16MatMul : [0x286e000, 0x39ee000)
==========================================
net 1 : "block_1", stage:0
-------------------------------
tpu.Gather : [0x0, 0x40000)
tpu.Gather : [0x40000, 0x80000)
tpu.RMSNorm : [0x80000, 0x81000)
tpu.A16MatMul : [0x81000, 0x2b1000)
tpu.A16MatMul : [0x2b1000, 0x2f7000)
tpu.A16MatMul : [0x2f7000, 0x33d000)
tpu.A16MatMul : [0x33d000, 0x56d000)
tpu.RMSNorm : [0x56d000, 0x56e000)
tpu.A16MatMul : [0x56e000, 0x16ee000)
tpu.A16MatMul : [0x16ee000, 0x286e000)
tpu.A16MatMul : [0x286e000, 0x39ee000)
==========================================
```

## 5) 更新权重

执行参考如下:

```shell
# 将src.bmodel中网络名为src_net的网络，在0x2000位置的权重，更新到dst.bmodel的dst_net的0x1000位置
$ model_tool --update_weight dst.bmodel dst_net 0x1000 src.bmodel src_net 0x2000
```

可以实现将模型权重进行更新。比如某个模型的某个算子权重需要更新，则将该算子单独编译成bmodel，然后将其权重更新到原始的模型中。

## 6) 模型加密与解密

执行参考如下:

```shell
# -model输入combine后的模型或正常bmodel，-net输入要加密的网络，-lib实现具体的加密算法，-o输出加密后模型的名称
$ model_tool --encrypt -model combine.bmodel -net block_0 -lib libcipher.so -o encrypted.bmodel
$ model_tool --decrypt -model encrypted.bmodel -lib libcipher.so -o decrypted.bmodel
```

可以实现将模型的权重、flatbuffer结构化数据、header都进行加密。

加解密接口必须按照C风格来实现，不能使用C++，接口规定如下：

```
extern "C" uint8_t* encrypt(const uint8_t* input, uint64_t input_bytes, uint64_t* output_bytes);
extern "C" uint8_t* decrypt(const uint8_t* input, uint64_t input_bytes, uint64_t* output_bytes);
```

# 整体设计

## 分层

TPU-MLIR将网络模型的编译过程分两层处理:

**Top Dialect**
与硬件无关层, 包括图优化、量化、推理等等

**Tpu Dialect**
与硬件相关层, 包括权重重排、算子切分、地址分配、推理等等

整体的流程如图中所示, 通过Pass将模型逐渐转换成最终的指令, 这里具体说明Top层和Tpu层每个Pass的功能。后面章节会对每个Pass的关键点做详细说明。

TPU-MLIR整体流程

## Top Passes

**shape-infer**
做shape推导, 包括常量折叠。对于shape不确定的op, 在这里确定shape。

**canonicalize**
与具体op有关的图优化, 比如relu合并到conv、shape合并等等。

**extra-optimize**
额外的pattern实现, 比如求FLOPs、去除无效输出等等。

**processor-assign**
配置处理器, 如BM1684X或者CV183X等等; 并根据处理器对top层进行调整, 比如CV18XX将输入全部调整为F32。

**import-calibration-table**
按照calibration table, 给每个op插入min和max, 用于后续量化; 对应对称量化则插入threshold

**processor-top-optimize**
与处理器相关的top层算子优化, 这是一个权衡, 有些top算子与处理器具有相关性

**convert-top-to-tpu**
将top层下沉到tpu层; 如果是浮点类型(F32/F16/BF16), top层op基本上直接转换成相应的tpu层op即可; 如果是INT8类型, 则需要量化转换

## Tpu Passes

**canonicalize**
与tpu层具体op有关的图优化, 比如连续Requant的合并等等

**strip-io-quant**
决定输入或输出是否是量化类型, 否则就是默认F32类型

**processor-tpu-optimize**
与处理器相关的tpu层算子优化

**weight-reorder**
根据硬件特征对个别op的权重进行重新排列, 比如卷积的filter和bias

**subnet-divide**
将网络按照处理器类型切分成不同的子网络, 如果所有算子都是TPU, 则子网络只有一个

**op-reorder**
对op进行顺序调整, 让使用者离被使用者尽可能的靠近; 也有针对attention一类操作做特殊处理

**layer-group**
对网络进行切分, 使尽可能多的op在local mem中连续计算

**address-assign**
给需要global mem的op分配地址

**codegen**
执行op的codegen接口, 生成cmdbuf。并用Builder模块采用flatbuffers格式生成最终的模型

## Other Passes

还有一些可选的pass没有再图中标出来, 用于实现特定功能。

**fuse-preprocess**
用于预处理融合, 对于图片类输入, 将图片的预处理过程合并到模型中

**add-postprocess**
用于将ssd或yolo的后处理合并到模型中

# 前端转换

本章以 onnx 模型为例介绍模型/算子在本工程中的前端转换流程。

## 主要工作

前端主要负责将原始模型转换为 Top 层(硬件无关层)mlir 模型的工作(不包含 Canonicalize 部分, 因此生成的文件名为"*_origin.mlir"), 这个过程会根据原始模型与运行 model_transform.py 时输入的参数逐一创建并添加对应的算子(Op), 最终生成 mlir 文件与保存权重的 npz 文件。

## 工作流程

1. **前提(Prereq)**: Top 层算子定义, 该部分内容保存在 TopOps.td 文件

2. **输入(Input)**: 输入原始 onnx 模型与参数(主要是预处理参数)

3. **初始化 OnnxConverter(load_onnx_model + initMLIRImporter)**
   - load_onnx_model 部分主要是对模型进行精简化, 根据 arguments 中的 output_names 截取模型, 并提取精简后模型的相关信息
   - init_MLIRImporter 部分主要是生成初始的 mlir 文本

4. **generate_mlir**
   - 依次创建 input op, 模型中间 nodes op 以及 return op, 并将其补充到 mlir 文本中(如果该op带有权重, 则会额外创建weight op)

5. **输出(Output)**
   - 将精简后的模型保存为"*_opt.onnx"文件
   - 生成".prototxt"文件保存除权重外的模型信息
   - 将生成的文本转为字符串并保存为".mlir"文件
   - 将模型权重(tensors)保存为".npz"文件

前端转换的工作流程如图所示。

补充说明:
- Build input op 需要:
  1. input_names
  2. 每个 input 对应的 index
  3. 预处理参数(若输入为图像)

- Convert nodes op 需要:
  1. 从 operands 获取该 node 的输入 op(即前一个已经 build 或 convert 好的算子)
  2. 从 shapes 中获取 output_shape
  3. 从 onnx node 中提取的 attrs。Attrs 会通过 MLIRImporter 设定为与 TopOps.td 定义一一对应的属性

- Build return op 需要:
  依照 output_names 从 operands 获取相应的 op

- 每创建或者转换一个算子都会执行一次插入操作, 将算子插入到 mlir 文本中, 使最终生成的文本能从头到尾与原 onnx 模型一一对应

## 算子转换样例

本节以 Conv 算子为例, 将单 Conv 算子的 onnx 模型转换为 Top mlir, 原模型如图所示。

转换流程为:

1. **算子定义**
   在 TopOps.td 中定义 Top.Conv 算子, 算子定义如图所示。

2. **初始化 OnnxConverter**
   load_onnx_model:
   - 由于本例使用的是最简模型, 所以生成的 Conv_opt.onnx 模型与原模型相同。
   - input_names 保存了 Conv 算子的输入名"input"
   - tensors 中保存了 Conv 算子的权重 weight 与 bias
   - shapes 中保存了Conv算子的输入和输出shape。
   - output_names 中保存了 Conv 算子的输出名"output"

   init_MLIRImporter:
   根据 input_names 与 output_names 从 shapes 中获取了对应的 input_shape 与 output_shape, 加上model_name, 生成了初始的 mlir 文本 MLIRImporter.mlir_module, 如图所示。

3. **generate_mlir**
   - build input op, 生成的 Top.inputOp 会被插入到 MLIRImporter.mlir_module 中。
   - 根据 node.op_type (即" Conv ") 调用 convert_conv_op() ,  该函数中会调用MLIRImporter.create_conv_op 来创建 ConvOp, 而 create 函数需要的参数有:
     1) 输入 op: 从可知, Conv 算子的 inputs 一共包含了 input, weight 与 bias, inputOp 已被创建好, weight 与 bias 的 op 则通过 getWeightOp()创建。
     2) output_shape: 利用 onnx_node.name 从 shapes 中获取 Conv 算子的输出shape。
     3) Attributes: 从 onnx Conv 算子中获取如中的 attributes。
        在 create 函数里 Top.Conv 算子的 attributes 会根据中的定义来设定。Top.ConvOp 创建后会被插入到 mlir 文本中
   - 根据 output_names 从 operands 中获取相应的 op, 创建 return_op 并插入到 mlir 文本中。到此为止, 生成的 mlir 文本如图所示。

4. **输出**
   将 mlir 文本保存为 Conv_origin.mlir, tensors 中的权重保存为 Conv_TOP_F32_all_weight.npz。

# 量化

量化理论源于论文: Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference

该论文地址: https://arxiv.org/abs/1712.05877

本章介绍TPU-MLIR的量化设计, 重点在该论文在实际量化中的应用。

## 基本概念

INT8量化分为非对称量化和对称量化。对称量化是非对称量化的一个特例, 通常对称量化的性能会优于非对称量化, 而精度上非对称量化更优。

### 非对称量化

如上图所示, 非对称量化其实就是把[min,max]范围内的数值定点到[-128, 127]或者[0, 255]区间。

从int8到float的量化公式表达如下:

$$
r = S(q-Z) \\
S = \frac{max-min}{qmax-qmin} \\
Z = Round(- \frac{min}{S} + qmin)
$$

其中r是真实的值, float类型; q是量化后的值, INT8或者UINT8类型;

S表示scale, 是float; Z是zeropoint, 是INT8类型;

当量化到INT8时, qmax=127,qmin=-128; UINT8时, qmax=255,qmin=0

反过来从float到int8的量化公式如下:

$$
q = \frac{r}{S} + Z
$$

### 对称量化

对称量化是非对称量化Z=0时的特例, 公式表达如下:

$$
i8\_value = f32\_value \times \frac{128}{threshold} \\
f32\_value = i8\_value \times \frac{threshold}{128}
$$

threshold是阈值, 可以理解为Tensor的范围是[-threshold, threshold]

这里 $S = threshold / 128$, 通常是activation情况;

对于weight, 一般 $S = threshold / 127$

对于UINT8, Tensor范围是[0, threshold], 此时 $S = threshold/ 255.0$

## Scale转换

论文中的公式表达:

$$
M = 2^{-n}M_0, 其中M_0取值[0.5,1], n是一个非负数
$$

换个表述来说, 就是浮点数Scale, 可以转换成Multiplier和rshift, 如下表达:

$$
Scale = \frac{Multiplier}{2^{rshift}}
$$

举例说明:

$$
&y = x \times 0.1234 \\
&=> y = x \times 0.9872 \times 2^{-3} \\
&=> y = x \times (0.9872 \times 2^{31}) \times 2^{-34} \\
&=> y = x \times \frac{2119995857}{1 \ll 34} \\
&=> y = (x \times 2119995857) \gg 34
$$

Multiplier支持的位数越高, 就越接近Scale, 但是性能会越差。一般硬件会用32位或8位的Multiplier。

## 量化推导

我们可以用量化公式, 对不同的OP进行量化推导, 得到其对应的INT8计算方式。

对称和非对称都用在Activation上, 对于权重一般只用对称量化。

### Convolution

卷积的表示式简略为: $Y = X_{(n,ic,ih,iw)}\times W_{(oc,ic,kh,kw)} + B_{(1,oc,1,1)}$

代入int8量化公式, 推导如下:

$$
float:\quad & Y = X\times W + B \\
step 0\quad & => S_y(q_y-Z_y) = S_x(q_x-Z_x)\times S_wq_w + B \\
step 1\quad & => q_y - Z_y = S_1(q_x-Z_x)\times q_w + B_1 \\
step 2\quad & => q_y - Z_y = S_1 q_x\times q_w  + B_2 \\
step 3\quad & => q_y = S_3 (q_x \times q_w + B_3) + Z_{y} \\
step 4\quad & => q_y = (q_x \times q_w + b_{i32}) * M_{i32} >> rshift_{i8} + Z_{y}
$$

非对称量化特别注意的是, Pad需要填入Zx

对称量化时, Pad填入0, 上述推导中Zx和Zy皆为0

在PerAxis(或称PerChannal)量化时, 会取Filter的每个OC做量化, 推导公式不变, 但是会有OC个Multiplier、rshift

### InnerProduct

表达式和推导方式与相同

### Add

加法的表达式为: $Y = A + B$

代入int8量化公式, 推导如下:

$$
float:\quad & Y = A + B \\
step 0\quad & => S_y (q_y-Z_y) = S_a(q_a-Z_a) + S_b(q_b - Z_b) \\
step 1(对称) \quad & => q_y = (q_a * M_a + q_b * M_b)_{i16} >> rshift_{i8} \\
step 1(非对称) \quad & => q_y = requant(dequant(q_a) + dequant(q_b))
$$

加法最终如何用智能深度学习处理器实现, 与处理器具体的指令有关。

这里对称提供的方式是用INT16做中间buffer;

在网络中，输入A、B已经是量化后的结果 $q_a$、 $q_b$，因此非对称是先反量化成float, 做加法后再重量化成INT8

# AvgPool

平均池化的表达式可以简写为: $Y_i = \frac{\sum_{j=0}^{k}{(X_j)}}{k}, 其中k = kh \times kw$

代入int8量化公式, 推导如下:

$$
float:\quad & Y_i = \frac{\sum_{j=0}^{k}{(X_j)}}{k} \\
step0:\quad & => S_y(y_i - Z_y) = \frac{S_x\sum_{j=0}^{k}(x_j-Z_x)}{k}\\
step1:\quad & => y_i = \frac{S_x}{S_yk}\sum_{j=0}^{k}(x_j-Z_x) + Z_y \\
step2:\quad & => y_i = \frac{S_x}{S_yk}\sum_{j=0}^{k}(x_j) - (Z_y - \frac{S_x}{S_y}Z_x) \\
step3:\quad & => y_i = (Scale_{f32}\sum_{j=0}^{k}(x_j) - Offset_{f32})_{i8} \\
           & 其中Scale_{f32} = \frac{S_x}{S_yk}, Offset_{f32} = Z_y - \frac{S_x}{S_y}Z_x
$$

# LeakyReLU

LeakyReLU的表达式可以简写为: $Y = \begin{cases} X, if X \geq 0\\ \alpha X, if X < 0 \end{cases}$

代入int8量化公式, 推导如下:

$$
float:\quad & Y = \begin{cases} X, if \ X \geq 0\\ \alpha X, if \ X < 0 \end{cases} \\
step0:\quad & => S_y (q_y - Z_y) = \begin{cases} S_x(q_x - Z_x), if \ q_x \geq 0\\ \alpha S_x (q_x - Z_x), if \ q_x < 0 \end{cases} \\
step1:\quad & => q_y = \begin{cases} \frac{S_x}{S_y}(q_x - Z_x) + Z_y, if \ q_x \geq 0\\ \alpha \frac{S_x}{S_y} (q_x - Z_x) + Z_y, if \ q_x < 0 \end{cases}
$$

对称量化时, $S_y=\frac{threshold_y}{128}, S_x=\frac{threshold_x}{128}$, 非对称量化时, $S_y = \frac{max_y ⁡- min_y}{255}, S_x = \frac{max_x ⁡- min_x}{255}$。通过BackwardCalibration操作后, $max_y = max_x,  min_y = min_x, threshold_y = threshold_x$, 此时Sx/Sy = 1。

$$
step2:\quad & => q_y = \begin{cases} (q_x - Z_x) + Z_y,  if \ q_x \geq 0\\ \alpha (q_x - Z_x) + Z_y, if \ q_x < 0 \end{cases} \\
step3:\quad & => q_y = \begin{cases} q_x - Z_x + Z_y,  if \ q_x \geq 0\\ M_{i8} >> rshift_{i8} (q_x - Z_x) + Z_y, if \ q_x < 0 \end{cases}
$$

当为对称量化时, Zx和Zy均为0。

# Pad

Pad的表达式可以简写为: $Y = \begin{cases} X, \ origin\ location \\ value, \ padded\ location \end{cases}$

代入int8量化公式, 推导如下:

$$
float:\quad & Y = \begin{cases} X, \ origin\ location \\ value, \ padded\ location \end{cases} \\
step0:\quad & => S_y (q_y - Z_y) = \begin{cases} S_x (q_x - Z_x), \ origin\ location \\ value, \ padded\ location \end{cases} \\
step1:\quad & => q_y = \begin{cases} \frac{S_x}{S_y} (q_x - Z_x) + Z_y, \ origin\ location \\ \frac{value}{S_y} + Z_y, \ padded\ location \end{cases}
$$

通过ForwardCalibration操作后, $max_y = max_x,  min_y = min_x, threshold_y = threshold_x$, 此时Sx/Sy = 1。

$$
step2:\quad & => q_y = \begin{cases} (q_x - Z_x) + Z_y, \ origin\ location \\ \frac{value}{S_y} + Z_y, \ padded\ location \end{cases}
$$

对称量化时, Zx和Zy均为0, pad填入 round(value/Sy), 非对称量化时, pad填入round(value/Sy + Zy)。

# PReLU

PReLU的表达式可以简写为: $Y_i = \begin{cases} X_i, if \ X_i \geq 0\\ \alpha_i X_i, if \ X_i < 0 \end{cases}$

代入int8量化公式, 推导如下:

$$
float:\quad & Y_i = \begin{cases} X_i, if \  X_i \geq 0\\ \alpha_i X_i, if \ X_i < 0 \end{cases} \\
step0:\quad & => S_y (y_i - Z_y) = \begin{cases} S_x (x_i - Z_x), if \ x_i \geq 0\\ S_{\alpha}q_{\alpha_i}S_x (x_i - Z_x), if \ x_i < 0 \end{cases} \\
step1:\quad & => y_i = \begin{cases} \frac{S_x}{S_y} (x_i - Z_x) + Z_y, if \ x_i \geq 0\\ S_{\alpha}q_{\alpha_i}\frac{S_x}{S_y} (x_i - Z_x) + Z_y, if \ x_i < 0 \end{cases} \\
$$

通过BackwardCalibration操作后, $max_y = max_x,  min_y = min_x, threshold_y = threshold_x$, 此时Sx/Sy = 1。

$$
step2:\quad & => y_i = \begin{cases} (x_i - Z_x) + Z_y, if \ x_i \geq 0\\ S_{\alpha}q_{\alpha_i}(x_i - Z_x) + Z_y, if \ x_i < 0 \end{cases} \\
step3:\quad & => y_i = \begin{cases} (x_i - Z_x) + Z_y, if \ x_i \geq 0\\ q_{\alpha_i} * M_{i8} (x_i - Z_x) >> rshift_{i8} + Z_y, if \ x_i < 0 \end{cases} \\
$$

一共有oc个Multiplier和1个rshift。当为对称量化时, Zx和Zy均为0。

# Calibration

## 总体介绍

所谓校准, 就是用真实场景数据来调校出恰当的量化参数, 为何需要校准？当我们对激活进行非对称量化时, 需要预先知道其总体的动态范围, 即min/max值,对激活进行对称量化时, 需要预先使用合适的量化门限算法在激活总体数据分布的基础上计算得到其量化门限, 而一般训练输出的模型是不带有激活这些数据统计信息的, 因此这两者都要依赖于在一个微型的训练集子集上进行推理, 收集各个输入的各层输出激活。

tpu-mlir的校准过程包括了门限方法自动寻优(search_threshold),SmoothQuant(sq),跨层权重均衡(we),偏置修正(bc)以及自动混精功能(search_qtable)等方法。其中sq,we,bc,search_qtable和search_threshold都是可选择的,可以根据当前要量化的模型的实际情况进行搭配，后面章节也会具体给出各个方法的使用说明。上述过程整合在一起统一执行, 最后将各个op的优化后的threshold和min/max值输出到一个量化校准参数文件cali_table中, 后续`model_deploy.py`时就可使用这个参数文件来进行后续的int8量化。如果您使用了自动混精功能,在生成cali_table的同时,还会生成混合精度表qtable,后续`model_deploy.py`时需使用这两个文件来进行后续的int8混合精度量化。

## 默认流程介绍

当前的校准流程囊括了多项方法，同时也提供了默认校准流程。

如若使用search_qtable,还会生成qtable混精表。

## 校准数据筛选及预处理

### 筛选原则

在训练集中挑选约100~200张覆盖各个典型场景风格的图片来进行校准, 采用类似训练数据清洗的方式, 要排除掉一些异常样例;

### 输入格式及预处理

| 格式 | 描述 |
|------|------|
| 原始图片 | 对于CNN类图片输入网络, 支持直接输入图片, 要求在前面生成mlir文件时, model_transform.py命令要指定和训练时完全一致的图片预处理参数 |
| npz或npy文件 | 对于非图片输入或图片预处理类型较复杂tpu-mlir暂不支持的情形, 建议额外编写脚本将完成预处理后的输入数据保存到npz/npy文件中(npz文件是多个输入tensor按字典的方式打包在一起, npy文件是1个文件包含1个tensor), run_calibration.py支持直接导入npz/npy文件 |

上面2种格式, 在调用run_calibration.py调用mlir文件进行推理时, 就无需再指定校准图片的预处理参数了

| 方式 | 描述 |
|------|------|
| --dataset | 对于单输入网络, 放置输入的各个图片或已预处理的输入npy/npz文件(无顺序要求); 对于多输入网络, 放置各个样本的已预处理的npz文件 |
| --data_list | 将各个样本的图片文件地址, 或者npz文件地址, 或者npy文件地址, 一行放一个样本, 放置在文本文件中, 若网络有多个输入文件, 文件间通过逗号分割(注意npz文件应该只有1个输入地址) |

## 量化门限算法实现

tpu-mlir目前实现了七种量化门限计算方法,分别为kld+auto-tune,octav,minmax,percentile9999, aciq_gauss+auto-tune,aciq_laplace+auto-tune和基于torch的histogram算法,下面将对kld, octav,aciq和auto-tune算法进行介绍。

### kld算法

tpu-mlir实现的kld算法参考tensorRT的实现, 本质上是将abs(fp32_tensor)这个分布(用2048个fp32 bin的直方图表示),截掉一些高位的离群点后(截取的位置固定在128bin、256bin...一直到2048bin)得到fp32参考概率分布P, 这个fp32分布若用128个等级的int8类型来表达, 将相邻的多个bin(比如256bin是相邻的2个fp32 bin)合并成1个int8值等级计算分布概率后, 再扩展到相同的bin数以保证和P具有相同的长度, 最终得到量化后int8值的概率分布Q, 计算P和Q的KL散度, 在一个循环中, 分别对128bin、256bin、...、2048bin这些截取位置计算KL散度, 找出具有最小散度的截取位置, 这说明在这里截取, 能用int8这128个量化等级最好的模拟fp32的概率分布, 故量化门限设在这里是最合适的。kld算法实现伪码如下所示:

```
the pseudocode of computing int8 quantize threshold by kld:
    Prepare fp32 histogram H with 2048 bins
    compute the absmax of fp32 value

    for i in range(128,2048,128):
      Outliers_num=sum(bin[i], bin[i+1],…, bin[2047])
      Fp32_distribution=[bin[0], bin[1],…, bin[i-1]+Outliers_num]
      Fp32_distribution/= sum(Fp32_distribution)

      int8_distribution = quantize [bin[0], bin[1],…, bin[i]] into 128 quant level
      expand int8_distribution to i bins
      int8_distribution /= sum(int8_distribution)
      kld[i] = KLD(Fp32_distribution, int8_distribution)
    end for

    find i which kld[i] is minimal
    int8 quantize threshold = (i + 0.5)*fp32 absmax/2048
```

### auto-tune算法

从KLD算法的实际表现来看, 其候选门限相对较粗, 也没有考虑到不同业务的特性, 比如: 对于目标检测、关键点检测等业务, tensor的离群点可能对最终的结果的表现更加重要, 此时要求量化门限更大, 以避免对这些离群点进行饱和而影响到这些分布特征的表达; 另外, KLD算法是基于量化后int8概率分布与fp32概率分布的相似性来计算量化门限, 而评估分布相似性的方法还有其他比如欧式距离、cos相似度等方法, 这些度量方法不用考虑粗略的截取门限直接来评估tensor数值分布相似性, 很多时候能有更好的表现; 因此, 在高效的KLD量化门限的基础上, tpu-mlir提出了auto-tune算法对这些激活的量化门限基于欧式距离度量进行微调, 从而保证其int8量化具有更好的精度表现;

实现方案: 首先统一对网络中带权重layer的权重进行伪量化, 即从fp32量化为int8, 再反量化为fp32, 引入量化误差; 然后逐个对op的输入激活量化门限进行调优: 在初始KLD量化门限和激活的最大绝对值之间, 均匀选择20个候选值, 用这些候选值对fp32参考激活值进行量化加扰, 引入量化误差, 然后输入op进行fp32计算, 将输出的结果与fp32参考激活进行欧式距离计算, 选择20个候选值中具有最小欧式距离的值作为调优门限; 对于1个op输出连接到后面多个分支的情形, 多个分支分别按上述方法计算量化门限, 然后取其中较大者, 比如layer1的输出会分别针对layer2、layer3调节一次, 两次调节独立进行, 根据实验证明, 取最大值能兼顾两者;

### octav算法

tpu-mlir实现的octav算法参考了文章《Optimal Clipping and Magnitude-aware Differentiation for Improved Quantization-aware Training》。通常人们认为量化误差来源于舍入误差和截断误差,计算每个张量的最优截断(门限)可以最小化量化误差,ovtav采用了均方误差来衡量量化误差,采用递归方式并基于快速的牛顿-拉夫森(Newton-Raphson)方法用于动态确定最小化均方误差(MSE)的最优门限。

其设计之初用于QAT量化中,但在PTQ量化中同样有效。下面是其实现伪码:

```
the pseudocode of computing int8 quantize threshold by octav:
    Prepare T: Tensor to be quantized,
            B: Number of quantization bits,
            epsilon: Convergence threshold (e.g., 1e-5),
            s_0: Initial guess for the clipping scalar (e.g., max absolute value in tensor T)
    compute s_star: Optimal clipping scalar

    for n in range(20):
       Compute the indicator functions for the current clipping scalar:
       I_clip = 1{|T| > s_n}  (applied element-wise to tensor T)
       I_disc = 1{0 < |T| ≤ s_n}

       Update the clipping scalar s_n to the next one s_(n+1) using:
       s_(n+1) = (Σ|x| * I_clip) / ((4^{-B} / 3) * ΣI_disc + ΣI_clip)
       where Σ denotes the summation over the corresponding elements

       If |s_(n+1) - s_n| < epsilon, the algorithm is considered to have converged
    end for
    s_star = s_n
```

### aciq算法

tpu-mlir实现的aciq算法参考了文章《ACIQ:ANALYTICAL CLIPPING FOR INTEGER QUANTIZATION OF NEURAL NETWORKS》。该方法假设激活值满足固定分布,然后计算该激活值对应分布的统计量,并根据理论计算获得的最优截断分位来得到最优门限。

实现方案:tpu-mlir中提供了aciq_guass和aciq_laplace两种算法,分别假设激活值满足gauss分布和laplace分布,然后根据理论上8bit对应的最优截断分位来计算获得最优门限。

## 优化算法实现

在校准过程中,为了进一步提升量化模型的精度,tpu-mlir提供了多种优化算法,其中包括SmoothQuant(sq),跨层权重均衡(we),偏置修正(bc),search_qtable和search_threshold,下面是上述优化算法的介绍。

### sq算法

tpu-mlir实现的SmoothQuant算法参考了文章《SmoothQuant: Accurate and Efficient Post-Training Quantization for Large Language Models》, 该方法通过平滑地分配模型的张量比例,将模型的输入和权重的范围调整到一个更适合量化的范围,从而提高量化后的模型精度, 解决大规模预训练模型（如语言模型和视觉模型）在量化过程中精度下降的问题。

SmoothQuant通过调整模型的张量比例,将激活和权重的范围进行重新分配,使得量化过程更加稳定。具体来说,SmoothQuant在量化前引入一个平滑因子, 将激活值的范围部分转移到权重中,通过数学等价转换来调整模型权重,从而降低激活值的量化误差。

### we算法

tpu-mlir实现的跨层权重均衡算法参考了文章《Data-Free Quantization Through Weight Equalization and Bias Correction》,该方法主要针对模型权重,通过对符合conv-conv和conv-relu-conv这两种pattern的权重进行均衡,使两个相邻权重分布尽可能均匀。

之前研究发现在mobilenet这类可分离卷积较多的网络中,由于可分离卷积的channel间数据分布差异较大,如果采用per-layer的量化,会造成较大的量化误差。we算法很好的解决了这一问题,其利用了relu函数的线性特性,可以对相邻卷积权重进行均衡,使得卷积channel间的分布差距缩小,此时采用per-layer的效果可以与per-channel相当。

### bc算法

# 偏置修正算法

tpu-mlir实现的偏置修正算法参考了文章《Data-Free Quantization Through Weight Equalization and Bias Correction》。通常人们认为量化模型输出误差是无偏的，也就是其满足期望值为0，但在很多实际场景下，量化模型的输出误差是有偏的，也就是量化模型的输出与浮点模型的输出存在期望值上的偏离，这会对量化模型的精度造成影响。

偏置修正算法通过计算量化模型在校准数据上与浮点模型的统计偏差，然后对模型中Conv/Gemm算子的bias项进行补偿，从而尽可能减小二者输出的期望值偏差。

## search_threshold算法

tpu-mlir提供了七种独立的门限计算方法，当我们拿到一个需要做量化的模型时，该如何择优选择门限计算方法成为一个问题。search_threshold针对上述问题提供了一个解决方案。

实现方案：search_threshold首先会同时计算kld+tune,octav,max和percentile9999四种方法的门限值，然后计算不同方法门限值生成的量化模型输出与浮点模型输出的相似度，通过比较四种门限方法的相似度，选择最大相似度对应的门限方法的门限值作为当前模型量化参数。在使用过程中，需要注意以下几点：

1. search_threshold目前提供了cos和snr两种相似度计算方法，默认采用cos相似度计算方法
2. 如果量化模型与浮点模型cos相似度低于0.9，该量化模型的精度下降可能比较严重，search_threshold搜索结果可能存在偏差，在进行实际精度验证后建议采用search_qtable进行混精尝试。

## search_qtable算法

search_qtable是集成于校准过程中的自动混精功能，当全int8量化的模型精度无法满足需求时，可以尝试开启search_qtable算法，该算法相比run_sensitive_lyer，速度更快，同时提供了自定义门限算法混合以及自动生成qtable功能。

实现方案：search_qtable的输出会生成混合门限，混合门限是指对模型每一层门限都进行择优选择，也就是从用户所指定的多种门限计算方法结果中选择效果最好的一个，这种选择的依据是量化模型当前层输出与原始模型当前层输出的相似度比较。除了输出混合门限，search_qtable还会输出模型的混精层，当用户指定混精模型与原始模型的输出相似度后，search_qtable会自动输出满足该相似度所需的最少混精层。

## 示例-yolov5s校准

在tpu-mlir的docker环境中，在tpu-mlir目录执行source envsetup.sh初始化环境后，任意新建目录进入执行如下命令可以完成对yolov5s的校准过程：

```shell
model_transform.py \
   --model_name yolov5s \
   --model_def  ${REGRESSION_PATH}/model/yolov5s.onnx \
   --input_shapes [[1,3,640,640]] \
   --keep_aspect_ratio \  #keep_aspect_ratio、mean、scale、pixel_format均为预处理参数
   --mean 0.0,0.0,0.0 \
   --scale 0.0039216,0.0039216,0.0039216 \
   --pixel_format rgb \
   --output_names 350,498,646 \
   --test_input ${REGRESSION_PATH}/image/dog.jpg \
   --test_result yolov5s_top_outputs.npz \
   --mlir yolov5s.mlir
```

### model_transform.py参数

| 参数 | 描述 |
|------|------|
| model_name | 模型名 |
| --model_def | 模型类型文件(.onnx,.pt,.tflite or .prototxt) |
| --model_data | 指定模型权重文件，为caffe模型时需要（对应'.caffemodel'文件） |
| --input_shapes | 输入的形状，例如[[1,3,640,640]]（二维数组），可以支持多个输入 |
| --resize_dims | 要调整到的原始图像的大小。如果未指定，它将调整为模型的输入大小 |
| --keep_aspect_ratio | 调整大小时是否保持纵横比。默认为False。设置时不足的部分会补0 |
| --mean | 图像每个通道的平均值。默认为 0.0,0.0,0.0 |
| --scale | 图像每个通道的scale。默认为 1.0,1.0,1.0 |
| --pixel_format | 图像类型，可以是 rgb、bgr、gray 或 rgbd |
| --output_names | 输出的名称。如果未指定，则使用模型的输出，否则使用指定的名称作为输出 |
| --test_input | 用于验证的输入文件，可以是图像、npy 或 npz。如果不指定则不会进行验证 |
| --test_result | 输出文件保存验证结果 |
| --excepts | 验证过程中要排除的网络层名称。用逗号分隔 |
| --debug | 如果打开调试，则立即模型文件将保留；或将在转换完成后删除 |
| --mlir | 输出mlir文件名（包括路径） |

### 默认流程

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --tune_num 10 \
   -o yolov5s_cali_table
```

### 使用不同量化门限计算方法

**octav:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_mse \
   -o yolov5s_cali_table
```

**minmax:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_max \
   -o yolov5s_cali_table
```

**percentile9999:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_percentile9999 \
   -o yolov5s_cali_table
```

**aciq_gauss:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_aciq_gauss \
   -o yolov5s_cali_table
```

**aciq_laplace:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_aciq_laplace \
   -o yolov5s_cali_table
```

### 使用优化方法：

**sq:**

```shell
run_calibration.py yolov5s.mlir \
   --sq \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_mse \
   -o yolov5s_cali_table
```

**we:**

```shell
run_calibration.py yolov5s.mlir \
   --we \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --cali_method use_mse \
   -o yolov5s_cali_table
```

**we+bc:**

```shell
run_calibration.py yolov5s.mlir \
   --we \
   --bc \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --processor bm1684x \
   --bc_inference_num 200 \
   --cali_method use_mse \
   -o yolov5s_cali_table
```

**we+bc+search_threshold:**

```shell
run_calibration.py yolov5s.mlir \
   --we \
   --bc \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --processor bm1684x \
   --bc_inference_num 200 \
   --search search_threshold \
   -o yolov5s_cali_table
```

**search_qtable:**

```shell
run_calibration.py yolov5s.mlir \
   --dataset $REGRESSION_PATH/dataset/COCO2017 \
   --input_num 100 \
   --processor bm1684x \
   --max_float_layers 5 \
   --expected_cos 0.99 \
   --transformer False \
   --quantize_method_list KL,MSE \
   --search search_qtable \
   --quantize_table yolov5s_qtable \
   -o yolov5s_cali_table
```

### run_calibration.py参数

| 参数 | 描述 |
|------|------|
| mlir_file | mlir文件 |
| --sq | 开启SmoothQuant |
| --we | 开启weight_equalization |
| --bc | 开启bias_correction |
| --dataset | 校准数据集 |
| --data_list | input列表 |
| --input_num | 校准图像数量 |
| --inference_num | search_qtable 和 search_threshold 推理过程所需图片数量 |
| --bc_inference_num | bias_correction 推理过程所需图片数量 |
| --tune_list | tuning用到的input列表 |
| --tune_num | tuning的图像数量 |
| --histogram_bin_num | 指定 kld 计算的直方图 bin 数量 |
| --expected_cos | 期望search_qtable混精模型输出与浮点模型输出的相似度,取值范围[0,1] |
| --min_layer_cos | bias_correction中该层量化输出与浮点输出的相似度下限,当低于该下限时需要对该层进行补偿,取值范围[0,1] |
| --max_float_layers | search_qtable 浮点层数量 |
| --processor | 处理器类型 |
| --cali_method | 量化门限计算方法选择,可选择use_kl,use_mse,use_percentile9999,use_max,默认为use_kl |
| --fp_type | search_qtable浮点层数据类型 |
| --post_process | 后处理路径 |
| --global_compare_layers | 指定全局对比层，例如 layer1,layer2 或 layer1:0.3,layer2:0.7 |
| --search | 指定搜索类型,其中包括search_qtable,search_threshold,false。其中默认为false,不开启搜索 |
| --transformer | 是否是transformer模型,search_qtable中如果是transformer模型可分配指定加速策略 |
| --quantize_method_list | search_qtable用来搜索的门限方法,默认仅MSE,支持KL,MSE,MAX,Percentile9999自由选择 |
| --benchmark_method | 指定search_threshold中相似度计算方法 |
| --kurtosis_analysis | 指定生成各层激活值的kurtosis |
| --part_quantize | 指定模型部分量化,获得cali_table同时会自动生成qtable。可选择N_mode,H_mode,custom_mode,H_mode通常精度较好 |
| --custom_operator | 指定需要量化的算子,配合开启上述custom_mode后使用 |
| --part_asymmetric | 指定当开启对称量化后,模型某些子网符合特定pattern时,将对应位置算子改为非对称量化 |
| --mix_mode | 指定search_qtable特定的混精类型,目前支持8_16和4_8两种 |
| --cluster | 指定search_qtable寻找敏感层时采用聚类算法 |
| --quantize_table | search_qtable输出的混精度量化表 |
| -o | 输出门限表 |
| --debug_cmd | debug命令,可以选择校准模式;"percentile9999"采用99.99分位作为初始门限。"use_max"采用绝对值最大值作为门限。"use_torch_observer_for_cali"采用torch的observer进行校准。"use_mse"采用octav进行校准。 |
| --debug_log | 日志输出级别 |

## 可视化工具visual说明

可视化工具visual.py可以用来比较量化网络与原始网络的数据相似性，有助于在量化后精度不够满意时候定位问题。此工具在docker中启动，可以在宿主机中启动浏览器打开界面。工具默认使用tcp端口10000，需要在启动docker时候使用-p命令映射到宿主机，而工具的启动目录必须在网络所在目录。

### 可视化工具命令行参数

| 参数 | 描述 |
|------|------|
| --port | 服务程序的TCP监听端口，默认值为10000 |
| --f32_mlir | 量化前的浮点mlir网络的文件名，此文件为model_transform生成，一般为netname.mlir，是初始float32网络 |
| --quant_mlir | 量化后的定点mlir网络的文件名，此文件为model_deploy生成，一般文件名为netname_int8_sym_tpu.mlir，生成bmodel用的_final.mlir不适用此工具。 |
| --input | 运行网络比较的输入样本数据，可以是jpeg图片文件或者npy/npz数据文件，一般可使用网络转换时的test_input |
| --manual_run | 浏览器客户端打开时是否自动运行网络进行数据比较，默认为true，使用此参数则只显示网络结构 |

在浏览器地址栏输入localhost:9999可以打开程序界面，启动时候会自动进行浮点网络和量化后网络的推理，所以可能会有一定时间的等待。

程序界面主要显示了：
1. 当前工作目录，指定的浮点网络和量化后网络；
2. 精度数据总结区
3. layer属性显示区域
4. 网络图形化显示区
5. tensor数据对比区
6. tensor数据分布和信息总结显示区（切换tab页面）

鼠标在网络显示区滚动可以放大和缩小网络显示，鼠标悬停或者点击节点可以在layer属性显示区中显示此layer的属性列表，点击layer之间的连线（也就是tensor)，可以在tensor数据对比区显示此tensor的量化前后数据对比。点击精度数据显示区中的点或者列表中的tensor或者layer，会在网络中定位到这个选中的layer或者tensor。

**需要注意的一点是由于网络是基于量化后网络显示，可能会相比浮点网络有变化，对于浮点网络中不存在的tensor会临时用量化后网络的数据替代，表现出来精度数据等都非常好，实际需要忽略而只关注浮点和量化后网络都存在的tensor，不存在的tensor的数据类型一般是NA，shape也是[]这样的空值。**

**另外在deploy网络的时候如果没有使用 --debug 参数，一些可视化工具需要的中间数据和文件会被默认清除，造成可视化工具运行不正常，需要增加 --debug 选项重新生成。**

# LayerGroup

## 基本概念

智能深度学习处理器分为片外内存(或称Global Memory, 简称GMEM)和片内内存(或称Local Memory, 简称LMEM)。

通常片外内存非常大(比如4GB), 片内内存非常小(比如16MB)。神经网络模型的数据量和计算量都非常大，通常每层的OP都需要切分后放到Local Memory进行运算，结果再保存到Global Memory。

LayerGroup就是让尽可能多的OP经过切分后能够在Local Memory执行，而避免过多的Local和Global Memory的拷贝。

要解决的问题：如何使Layer数据保持在有限的Local Memory进行运算，而不是反复进行Local与Global Memory之间的拷贝

基本思路：通过切Activation的N和H，使每层Layer的运算始终在Local Memory中

## BackwardH

对网络进行H切分的时候，大多数Layer输入和输出的H是一致的。但是对于Conv、Pool等等需要特别计算。

以Conv举例

## 划分Mem周期

如何划分group？首先把每一层Layer需要的lmem罗列出来，大体可以归为三类：

1. Activation Tensor，用于保存输入输出结果，没有使用者后直接释放
2. Weight，用于保存权重，不切的情况下用完就释放；否则一直驻留在lmem
3. Buffer，用于Layer运算保存中间结果，用完就释放

然后依次广度优先的方式配置id

然后再配置周期，配置方法如下：

- [T2,T7]，表示在T2开始的时候就要申请lmem，在T7结束的时候释放lmem
- w4的原始周期应该是[T5,T5]，但是被修正成[T2,T5]，因为在T2做卷积运算时w4可以被同时加载
- 当N或者H被切分时，Weight不需要重新被加载，它的结束点会被修正为正无穷

## LMEM分配

当n或h存在切分的情况下，weight常驻LMEM，每一个切分都可以继续使用weight。

当n和h都没有切分的情况下，weight和activation处理过程一样，不使用时就释放。

# LMEM分配问题

那么LMEM分配问题就可以转换成这些方块如何摆放问题（注意方块只能左右移动，不能上下移动）。

另外LMEM分配时优先不要跨bank。

目前策略是按照op顺序依次分配，优先分配timestep长的，次分配LMEM大的。

## 划分最优Group

目前从尾部开始向头部方向划分group，优先切N，当N切到最小单位时还不能满足要求，则切h。

当网络很深的时候，因为Conv、Pool等等算子会有重复计算部分，h切的过多导致重复部分过多；

为了避免过多重复，当backward后的layer的输入，如果h_slice重复的部分>h/2，则认为失败。

举例：比如input的h = 100，经过切分后变成2个input，h[0, 80)和h[20, 100)，则重复部分为60，则认为失败；2个input对应h[0, 60)和h[20, 100)，重复部分为40，认为成功。

# GMEM分配

## 目的

为了节约global memory空间，最大程度复用内存空间，分配顺序：weight tensor、根据生命周期给全部global neuron tensor分配GMEM，在分配过程中会复用已分配GMEM。

> global neuron tensor定义：在Op运算结束后需要保存在GMEM的tensor。如果是layer Group，只有layer Group的input/output tensor属于global neuron tensor。

## 原理

### weight tensor分配GMEM

遍历所有WeightOp，依次分配，4K地址对齐，地址空间不断累加

### global neuron tensors分配GMEM

最大可能的复用内存空间，根据生命周期给全部global neuron tensor分配，在分配过程中会复用已分配GMEM。

#### a. 数据结构介绍

每次分配时把对应的tensor, address, size, ref_cnt(这个tensor有几个OP使用)记录在rec_tbl。同时将tensor, address记录在辅助数据结构hold_edges,in_using_addr中

```cpp
//Value, offset, size, ref_cnt
using gmem_entry = std::tuple<mlir::Value, int64_t, int64_t, int64_t>;
std::vector<gmem_entry> rec_tbl;
std::vector<mlir::Value> hold_edges;
std::set<int64_t> in_using_addr;
```

#### b. 流程介绍

* **遍历每个Op，在遍历Op时，判断Op的输入tensor是否位于rec_tbl中，如果yes，判断ref_cnt是否>=1，如果yes，则ref_cnt--，表示输入tensor的引用数降低1个。**

  如果ref_cnt等于0，表示生命周期已结束，后面的tensor可以复用它的地址空间。

* **在给每个Op的output tensor分配时，先check是否可以复用EOL的tensor地址，check思路，遍历rec_tbl，需要同时满足如下5个条件才能reuse:**

  * 对应的tensor不在hold_edges内
  * 对应tensor的地址不在in_using_addr内
  * 对应tensor已EOL
  * 对应tensor的地址空间>=当前tensor所需空间
  * 当前OP的输入tensor地址不能与对应tensor的地址相同（某些Op最终运算结果不正确，reshapeOP例外）

* 给当前Op的output tensor分配GMEM，如果step2显示可以reuse，就reuse。否则在ddr中新开辟GMEM。

* 调整当前Op的input tensor的生命周期，确认它是否位于hold_edges内，如果yes，则在rec_tbl中寻找，检查它的ref_cnt是否为0，如果yes，则把它从hold_edges中删除，并且把它的addr从in_using_addr中删除，意味着这个input tensor生命周期已结束，地址空间已释放。

> EOL定义：end of life。

# CodeGen

TPU-MLIR的CodeGen是BModel生成的最后一步，该过程目的是将mlir文件转换成最终的bmodel。本章主要介绍模型/算子在本工程中的CodeGen工作流程。

## 主要工作

CodeGen的目的在于将mlir文件转换成最终的bmodel文件输出，这个过程会执行各op的CodeGen接口，以生成cmdbuf，并用Builder模版生成采用flatbuffers格式的最终模型。

## 工作流程

CodeGen的大致工作流程可分为3个部分：指令生成、指令存储和指令取出以生成Bmodel。具体来说：

指令生成：将不同硬件的后端函数封装到类，执行不同op的CodeGen接口，生成相应指令（二进制码）；

指令存储：通过store_cmd将指令（二进制码）存储在指定数据结构中；

指令取出：所有op的二进制码全部生成完毕后，在编译器会调用BM168X系列类中封装的函数取走指令，最终生成Bmodel。

指令依据硬件的engine不同而有所差别，比如1684有GDMA和TIU，而新架构的硬件bm1690会存在sdma、cdma等engine。这里拿最通用的两种engine即BDC（后更名为TIU）和GDMA为例：

```shell
std::vector<uint32_t> bdc_buffer;
std::vector<uint32_t> gdma_buffer;
uint32_t gdma_total_id = 0;
uint32_t bdc_total_id = 0;
std::vector<uint32_t> gdma_group_id;
std::vector<uint32_t> bdc_group_id;
std::vector<uint32_t> gdma_bytes;
std::vector<uint32_t> bdc_bytes;
int cmdid_groupnum = 0;
CMD_ID_NODE *cmdid_node;
CMD_ID_NODE *bdc_node;
CMD_ID_NODE *gdma_node;
```

bdc_buffer：存储bdc指令

gdma_buffer：存储gdma指令

gdma_total_id：gdma指令存储的总数目

bdc_total_id：bdc指令存储的总数目

gdma_bytes：gdma指令字节数

bdc_bytes：bdc指令字节数

## TPU-MLIR中BM168X及其相关类

TPU-MLIR中BM168X及其相关类定义在include/tpu_mlir/Backend文件夹下，目的是将不同的硬件后端封装，以实现后端与Codegen过程的隔离。

在一次运行中只存储一个类实例（设计模式中单例），该类初始化时候会经过：读取后端动态链接库、加载函数（设置后端的函数指针）、指令数据结构的初始化、设置一些硬件相关的参数例如NPU_NUM、L2_SRAM起始地址等。

## 后端函数的加载

后端作为一个动态库放入了TPU-MLIR工程里，具体的位置在third_party/nntoolchain/lib/libbackend_xxx.so。后端函数的加载方式为：首先定义函数指针，再将动态库加载，使函数指针指向动态库中的函数。

以同步函数tpu_sync_all为例，由于之后要加上多核支持的，所以需要在相关后端cmodel库中定义好，

1. 注意必须和后端的函数名和参数保持一致typedef void (*tpu_sync_all)();
2. 在类内部加入该函数成员tpu_sync_all dl_tpu_sync_all;
3. 在该类load_functions函数的实现中加入宏，CAST_FUNCTION(tpu_sync_all);该宏可以将dl_tpu_sync_all指向动态库中的函数。

获得到该类实例后即可使用动态库中的函数。

## 后端Store_cmd

后端store_cmd的功能是在编译器调用算子的过程中，把配置的指令保存到约定空间。后端的重点函数在store_cmd.cpp中，以cmodel/src/store_cmd.cpp；cmodel/include/store_cmd.h为例。

store_cmd分别有EngineStorer系列类和CmdStorer系列类：
1. EngineStoreInterface（接口类）、继承于EngineStoreInterface接口的GDMAEngineStorer、BDEngineStorer等具体类、EngineStorerDecorator（装饰类接口）、继承于EngineStorerDecorator的VectorDumpEngineStorerDecorator等具体装饰类。
2. CmdStorerInterface（接口）、继承于接口的ConcretCmdStorer、StorerDecorator、VectorDumpStorerDecorator具体装饰类。

关于类之间的关系与逻辑：
1. 使用单例设计模式，在store_cmd中只存在一个ConcretCmdStorer类，该类中会存所有EngineStorer的类，当调用不同的engine时，会调用不同EengineStorer，如下代码。

```cpp
virtual void store_cmd(int engine_id, void *cmd, CMD_ID_NODE *cur_id_node,int port) override
{
    switch (engine_id)
    {
    case ENGINE_BD:
    case ENGINE_GDMA:
    case ENGINE_HAU:
    case ENGINE_SDMA:
        port = 0;
        break;
    case ENGINE_CDMA:
        ASSERT(port < CDMA_NUM);
        break;
    case ENGINE_VSDMA:
        engine_id = ENGINE_SDMA;
        break;
    default:
        ASSERT(0);
        break;
    }
    return this->get(engine_id, port)->store(cmd, cur_id_node);
}
```

2. EngineStorer功能为解析命令，VectorDumpEngineStorerDecorator执行EngineStorer类中的store函数和take_cmds函数，可将所有指令存储到output_中。

```cpp
class VectorDumpEngineStorerDecorator : public EngineStorerDecorator
{
private:
    std::vector<uint32_t> *&output_;

    void take_cmds()
    {
        auto cmds = EngineStorerDecorator::get_cmds();
        (*output_).insert((*output_).end(), cmds.begin(), cmds.end());
    }

public:
    VectorDumpEngineStorerDecorator(ComponentPtr component, std::vector<uint32_t> **output)
        : EngineStorerDecorator(component), output_(*output) {}

    virtual void store(void *cmd, CMD_ID_NODE *cur_id_node) override
    {
        EngineStorerDecorator::store(cmd, cur_id_node);
        if (!enabled_)
            return;
        this->take_cmds();
    }

    virtual void store_cmd_end(unsigned dep) override
    {
        EngineStorerDecorator::store_cmd_end(dep);
        this->take_cmds();
    }
};
```

# MLIR定义

本章介绍MLIR各个元素的定义，包括Dialect、Interface等等

## Top Dialect

### Operations

#### AddOp

**简述**
加法操作，$Y = coeff_0 * X_0 + coeff_1 * X_1$

**输入**
- inputs: tensor数组，对应2个或多个输入tensor

**输出**
- output: tensor

**属性**
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限
- coeff: 对应每个tensor的系数，默认为1.0

**接口**
无

**范例**
```shell
%2 = "top.Add"(%0, %1) {do_relu = false} : (tensor<1x3x27x27xf32>, tensor<1x3x27x27xf32>) -> tensor<1x3x27x27xf32> loc("add")
```

#### AvgPoolOp

**简述**
将输入的tensor进行均值池化，$S=\frac{1}{width\ *\ height}\sum_{i,j}a_{ij}$ 。大小给定的滑动窗口会依次将输入tensor进行池化

其中 $width$ 和 $height$ 表示kernel_shape的宽度和高度。$\sum_{i,j}a_{ij}$ 则表示对kernel_shape进行求和

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- kernel_shape: 控制均值池化滑动窗口的大小
- strides: 步长，控制滑动窗口每次滑动的距离
- pads: 控制填充形状，方便池化
- pad_value: 填充内容，常数，默认为0
- count_include_pad: 结果是否需要对填充的pad进行计数
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%90 = "top.AvgPool"(%89) {do_relu = false, kernel_shape = [5, 5], pads = [2, 2, 2, 2], strides = [1, 1]} : (tensor<1x256x20x20xf32>) -> tensor<1x256x20x20xf32> loc("resnetv22_pool1_fwd_GlobalAveragePool")
```

#### Depth2SpaceOp

**简述**
深度转空间操作，$Y = Depth2Space(X)$

**输入**
- inputs: tensor

**输出**
- output: tensor

**属性**
- block_h: tensor 高度改变的参数，i64类型
- block_w: tensor 宽度改变的参数，i64类型
- is_CRD: column-row-depth，如果true，则数据沿深度方向的排布按照HWC，否则为CHW，bool类型
- is_inversed: 如果true，那么结果的形状为: $[n, c * block_h * block_w, h / block_h, w / block_w]$，否则结果的形状为: $[n, c / (block_h * block_w), h * block_h, w * block_w]$

**接口**
无

**范例**
```shell
%2 = "top.Depth2Space"(%0) {block_h = 2, block_w = 2, is_CRD = true, is_inversed = false} : (tensor<1x8x2x3xf32>) -> tensor<1x2x4x6xf32> loc("add")
```

#### BatchNormOp

**简述**
在一个四维输入tensor上执行批标准化(Batch Normalization)。关于批标准化的更多细节可以参考论文《Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift》。

具体计算公式如下:

$y = \frac{x - \mathrm{E}[x]}{ \sqrt{\mathrm{Var}[x] + \epsilon}} * \gamma + \beta$

**输入**
- input: 四维输入tensor
- mean: input的均值tensor
- variance: input的方差tensor
- gamma: 公式中的 $\gamma$ tensor，可以为None
- beta: 公式中的 $\beta$ tensor，可以为None

**输出**
- output: 结果tensor

**属性**
- epsilon: 公式中的 $\epsilon$ 常量，默认为1e-05
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%5 = "top.BatchNorm"(%0, %1, %2, %3, %4) {epsilon = 1e-05, do_relu = false} : (tensor<1x3x27x27xf32>, tensor<3xf32>, tensor<3xf32>, tensor<3xf32>, tensor<3xf32>) -> tensor<1x3x27x27xf32> loc("BatchNorm")
```

#### CastOp
(待补充)

#### ClipOp

**简述**
将给定输入限制在一定范围内

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- min: 给定的下限
- max: 给定的上限

**接口**
无

**范例**
```shell
%3 = "top.Clip"(%0) {max = 1%: f64,min = 2%: f64} : (tensor<1x3x32x32xf32>) -> tensor<1x3x32x32xf32> loc("Clip")
```

#### ConcatOp

**简述**
将给定的tensor序列在给定的维度上连接起来。所有的输入tensor或者都具有相同的shape(待连接的维度除外)，或者都为空。

**输入**
- inputs: tensor数组，对应2个或多个输入tensor

**输出**
- output: 结果tensor

**属性**
- axis: 待连接的维度的下标
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%2 = "top.Concat"(%0, %1) {axis = 1, do_relu = false} : (tensor<1x3x27x27xf32>, tensor<1x3x27x27xf32>)  -> tensor<1x6x27x27xf32> loc("Concat")
```

#### ConvOp

**简述**
对输入tensor执行二维卷积操作。

简单来说，给定输入大小为 $(N, C_{\text{in}}, H, W)$，输出 $(N, C_{\text{out}}, H_{\text{out}}, W_{\text{out}})$ 的计算方法为:

$\text{out}(N_i, C_{\text{out}_j}) = \text{bias}(C_{\text{out}_j}) + \sum_{k = 0}^{C_{\text{in}} - 1} \text{weight}(C_{\text{out}_j}, k) \star \text{input}(N_i, k)$

其中 $\star$ 是有效的cross-correlation操作，$N$ 是batch的大小，$C$ 是channel的数量，$H, W$ 是输入图片的高和宽。

**输入**
- input: 输入tensor
- filter: 参数tensor，其形状为 $(\text{out\_channels}, \frac{\text{in\_channels}}{\text{groups}}, \text{kernel\_size[0]}, \text{kernel\_size[1]})$:
- bias: 可学习的偏差tensor，形状为 $(out\_channels)$.

**输出**
- output: 结果tensor

**属性**
- kernel_shape: 卷积核的尺寸
- strides: 卷积的步长
- pads: 输入的每一条边补充0的层数
- group: 从输入通道到输出通道的阻塞连接数，默认为1
- dilations: 卷积核元素之间的间距，可选
- inserts: 可选
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%2 = "top.Conv"(%0, %1) {kernel_shape = [3, 5], strides = [2, 1], pads = [4, 2]} : (tensor<20x16x50x100xf32>, tensor<33x3x5xf32>)  -> tensor<20x33x28x49xf32> loc("Conv")
```

#### DeconvOp

**简述**
对输入tensor执行反卷积操作。

**输入**
- input: 输入tensor
- filter: 参数tensor，其形状为 $(\text{out\_channels}, \frac{\text{in\_channels}}{\text{groups}}, \text{kernel\_size[0]}, \text{kernel\_size[1]})$:
- bias: 可学习的偏差tensor，形状为 $(out\_channels)$.

**输出**
- output: 结果tensor

**属性**
- kernel_shape: 卷积核的尺寸
- strides: 卷积的步长
- pads: 输入的每一条边补充0的层数
- group: 从输入通道到输出通道的阻塞连接数，默认为1
- dilations: 卷积核元素之间的间距，可选
- inserts: 可选
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%2 = "top.Deconv"(%0, %1) {kernel_shape = (3, 5), strides = (2, 1), pads = (4, 2)} : (tensor<20x16x50x100xf32>, tensor<33x3x5xf32>)  -> tensor<20x33x28x49xf32> loc("Deconv")
```

#### DivOp

**简述**
除法操作，$Y = X_0 / X_1$

**输入**
- inputs: tensor数组，对应2个或多个输入tensor

**输出**
- output: tensor

**属性**
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限
- multiplier: 量化用的乘数，默认为1
- rshift: 量化用的右移，默认为0

**接口**
无

**范例**
```shell
%2 = "top.Div"(%0, %1) {do_relu = false, relu_limit = -1.0, multiplier = 1, rshift = 0} : (tensor<1x3x27x27xf32>, tensor<1x3x27x27xf32>) -> tensor<1x3x27x27xf32> loc("div")
```

#### InputOp
(待补充)

#### LeakyReluOp

**简述**
tensor中每个元素执行LeakyRelu函数，函数可表示为: f(x) = alpha * x for x < 0, f(x) = x for x >= 0

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- alpha:对应每个tensor的系数

**接口**
无

**范例**
```shell
%4 = "top.LeakyRelu"(%3) {alpha = 0.67000001668930054 : f64} : (tensor<1x32x100x100xf32>) -> tensor<1x32x100x100xf32> loc("LeakyRelu")
```

#### LSTMOp

**简述**
执行RNN 的LSTM操作

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- filter:卷积核
- recurrence: 循环单元
- bias: LSTM的参数: 偏置
- initial_h: LSTM中的每句话经过当前cell后会得到一个state,state 是个tuple(c, h)，其中h=[batch_size, hidden_size]
- initial_c: c=[batch_size, hidden_size]
- have_bias: 是否设置偏置bias，默认为false
- bidirectional: 设置双向循环的LSTM，默认为false
- batch_first: 是否将batch放在第一维，默认为false

**接口**
无

**范例**
```shell
%6 = "top.LSTM"(%0, %1, %2, %3, %4, %5) {batch_first = false, bidirectional = true, have_bias = true} : (tensor<75x2x128xf32>,tensor<2x256x128xf32>, tensor<2x256x64xf32>, tensor<2x512xf32>, tensor<2x2x64xf32>, tensor<2x2x64xf32>) -> tensor<75x2x2x64xf32> loc("LSTM")
```

#### LogOp

**简述**
按元素计算给定输入张量的自然对数

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
无

**接口**
无

**范例**
```shell
%1 = "top.Log"(%0) : (tensor<1x3x32x32xf32>) -> tensor<1x3x32x32xf32> loc("Log")
```

#### MaxPoolOp

**简述**
将输入的tensor进行最大池化

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- kernel_shape: 控制均值池化滑动窗口的大小
- strides: 步长，控制滑动窗口每次滑动的距离
- pads: 控制填充形状，方便池化
- pad_value: 填充内容，常数，默认为0
- count_include_pad: 结果是否需要对填充的pad进行计数
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%8 = "top.MaxPool"(%7) {do_relu = false, kernel_shape = [5, 5], pads = [2, 2, 2, 2], strides = [1, 1]} : (tensor<1x256x20x20xf32>) -> tensor<1x256x20x20xf32> loc("resnetv22_pool0_fwd_MaxPool")
```

#### MatMulOp

**简述**
二维矩阵乘法操作，$C = A * B$

**输入**
- input: tensor: m*k 大小的矩阵
- right: tensor: k*n 大小的矩阵

**输出**
- output: tensor m*n 大小的矩阵

**属性**
- bias: 偏差，量化的时候会根据bias计算 bias_scale，可以为空
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%2 = "top.MatMul"(%0, %1) {do_relu = false, relu_limit = -1.0} : (tensor<3x4xf32>, tensor<4x5xf32>) -> tensor<3x5xf32> loc("matmul")
```

#### MulOp

**简述**
乘法操作，$Y = X_0 * X_1$

**输入**
- inputs: tensor数组，对应2个或多个输入tensor

**输出**
- output: tensor

**属性**
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限
- multiplier: 量化用的乘数，默认为1
- rshift: 量化用的右移，默认为0

**接口**
无

**范例**
```shell
%2 = "top.Mul"(%0, %1) {do_relu = false, relu_limit = -1.0, multiplier = 1, rshift = 0} : (tensor<1x3x27x27xf32>, tensor<1x3x27x27xf32>) -> tensor<1x3x27x27xf32> loc("mul")
```

#### MulConstOp

**简述**
和常数做乘法操作，$Y = X * Const_Val$

**输入**
- inputs: tensor

**输出**
- output: tensor

**属性**
- const_val: f64类型的常量
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%1 = arith.constant 4.7 : f64
%2 = "top.MulConst"(%0) {do_relu = false, relu_limit = -1.0} : (tensor<1x3x27x27xf64>, %1) -> tensor<1x3x27x27xf64> loc("mulconst")
```

#### PermuteOp

**简述**
改变tensor布局，变化tensor数据维度的顺序，将输入的tensor按照order给定的顺序重新布局

**输入**
- inputs: tensor数组，任意类型的tensor

**属性**
- order: 指定重新布局tensor的顺序

**输出**
- output: 输出tensor，按order的顺序重新布局后的tensor

**接口**
无

**范例**
```shell
%2 = "top.Permute"(%1) {order = [0, 1, 3, 4, 2]} : (tensor<4x3x85x20x20xf32>) -> tensor<4x3x20x20x85xf32> loc("output_Transpose")
```

#### ReluOp

**简述**
tensor中每个元素执行ReLU函数，如果极限为零，则不使用上限

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限。

**接口**
无

**范例**
```shell
%1 = "top.Relu"(%0) {relu_limit = 6.000000e+00 : f64} : (tensor<1x3x32x32xf32>) -> tensor<1x3x32x32xf32> loc("Clip")
```

#### ReshapeOp

**简述**
Reshape算子，返回一个给定形状的tensor，该tensor的类型和内部的值与输入tensor相同。reshape可能会对tensor的任何一行进行操作。在reshape过程中不会有任何数据的值被修改

**输入**
- input: tensor

**输出**
- output: tensor

**属性**
无

**接口**
无

**范例**
```shell
%133 = "top.Reshape"(%132) : (tensor<1x255x20x20xf32>) -> tensor<1x3x85x20x20xf32> loc("resnetv22_flatten0_reshape0_Reshape")
```

#### ScaleOp

**简述**
Scale操作 $Y = X * S + B$，其中X/Y的shape为[N, C, H, W], S/B的shape为[1, C, 1, ,1]。

**输入**
- input: 输入tensor
- scale: 保存input的放大倍数
- bias: 放大后加上的bias

**输出**
- output: 结果tensor

**属性**
- do_relu: 结果是否做Relu，默认为False
- relu_limit: 如果做Relu，指定上限值，如果是负数，则认为没有上限

**接口**
无

**范例**
```shell
%3 = "top.Scale"(%0, %1, %2) {do_relu = false} : (tensor<1x3x27x27xf32>, tensor<1x3x1x1xf32>, tensor<1x3x1x1xf32>) -> tensor<1x3x27x27xf32> loc("Scale")
```

#### SigmoidOp

**简述**
激活函数，将tensor中元素映射到特定区间，默认映射到[0, 1]，计算方法为:

$Y = \frac{scale}{1 + e^{-X}} + bias$

**输入**
- inputs: tensor数组，任意类型的tensor

**属性**
- scale: 倍数，默认是1
- bias: 偏置，默认是0

**输出**
- output: 输出tensor

**接口**
无

**范例**
```shell
%2 = "top.Sigmoid"(%1) {bias = 0.000000e+00 : f64, scale = 1.000000e+00 : f64} : (tensor<1x16x64x64xf32>) -> tensor<1x16x64x64xf32> loc("output_Sigmoid")
```

#### SiLUOp

**简述**
激活函数，$Y = \frac{X}{1 + e^{-X}}$ 或 $Y = X * Sigmoid(X)$

**输入**
- input: tensor数组，任意类型的tensor

**属性**
无

**输出**
- output: 输出tensor

**接口**
无

**范例**
```shell
%1 = "top.SiLU"(%0) : (tensor<1x16x64x64xf32>) -> tensor<1x16x64x64xf32> loc("output_Mul")
```

# SliceOp
## 简述
tensor切片, 将输入的tensor的各个维度, 根据offset和steps数组中的偏移和步长进行切片, 生成新的tensor

## 输入
- input: tensor数组, 任意类型的tensor

## 属性
- offset: 存储切片偏移的数组, offset数组的索引和输入tensor的维度索引对应
- steps: 存储切片步长的数组, steps数组的索引和输入tensor维度索引对应

## 输出
- output: 输出tensor

## 接口
无

## 范例
```shell
%1 = "top.Slice"(%0) {offset = [2, 10, 10, 12], steps = [1, 2, 2, 3]} : (tensor<5x116x64x64xf32>) -> tensor<3x16x16x8xf32> loc("output_Slice")
```

# SoftmaxOp
## 简述
对输入tensor, 在指定axis的维度上计算归一化指数值, 计算的方法如下:

σ(Z)_i = e^(βZ_i) / ∑(j=0 to K-1) e^(βZ_j)

其中, ∑(j=0 to K-1) e^(βZ_j) , 在axis维度上做指数值求和, j从0到K-1, K是输入tensor在axis维度上的尺寸。

例如: 输入tensor的尺寸为 (N, C, W, H),在axis=1的通道上计算Softmax, 计算方法为:

Y_{n,i,w,h} = e^(βX_{n,i,w,h}) / ∑(j=0 to C-1) e^(βX_{n,j,w,h})

## 输入
- input: tensor数组, 任意类型的tensor

## 属性
- axis: 维度索引, 用于指定对输入tensor执行Softmax对应的维度, axis可以取值[-r, r-1], r 为输入tensor维度的数量, 当axis为负数时, 表示倒序维度
- beta: tflite模型中对输入的缩放系数, 非tflite模型无效, 默认值为1.0

## 输出
- output: 输出tensor, 在指定维度做归一化指数值后的tensor

## 接口
无

## 范例
```shell
%1 = "top.Softmax"(%0) {axis = 1 : i64} : (tensor<1x1000x1x1xf32>) -> tensor<1x1000x1x1xf32> loc("output_Softmax")
```

# SqueezeOp
## 简述
对输入tensor进行指定维度的裁剪并返回裁剪后的tensor

## 输入
- input: tensor

## 输出
- output: tensor

## 属性
- axes: 指定需要裁剪的维度, 0代表第一个维度, -1代表最后一个维度

## 接口
无

## 范例
```shell
%133 = "top.Squeeze"(%132) {axes = [-1]} : (tensor<1x255x20x20xf32) -> tensor<1x255x20xf32> loc(#loc278)
```

# UpsampleOp
## 简述
上采样op, 将输入tensor进行nearest上采样并返回tensor

## 输入
tensor

## 属性
- scale_h: 目标图像与原图像的高度之比
- scale_w: 目标图像与原图像的宽度之比
- do_relu: 结果是否做Relu, 默认为False
- relu_limit: 如果做Relu, 指定上限值, 如果是负数, 则认为没有上限

## 输出
- output: tensor

## 接口
无

## 范例
```shell
%179 = "top.Upsample"(%178) {scale_h = 2 : i64, scale_w = 2 : i64} : (tensor<1x128x40x40xf32>) -> tensor<1x128x80x80xf32> loc("268_Resize")
```

# WeightOp
## 简述
权重op, 包括权重的读取和创建, 权重会存到npz文件中。权重的location与npz中的tensor名称是对应关系。

## 输入
无

## 属性
无

## 输出
- output: 权重Tensor

## 接口
- read: 读取权重数据, 类型由模型指定
- read_as_float: 将权重数据转换成float类型读取
- read_as_byte: 将权重数据按字节类型读取
- create: 创建权重op
- clone_bf16: 将当前权重转换成bf16, 并创建权重Op
- clone_f16: 将当前权重转换成f16, 并创建权重Op

## 范例
```shell
%1 = "top.Weight"() : () -> tensor<32x16x3x3xf32> loc("filter")
```

# 精度验证

## 整体介绍

### 验证对象
TPU-MLIR中的精度验证主要针对mlir模型, fp32采用top层的mlir模型进行精度验证, 而int8对称与非对称量化模式则采用tpu层的mlir模型。

### 评估指标
当前主要用于测试的网络有分类网络与目标检测网络，分类网络的精度指标采用Top-1与Top-5准确率，而目标检测网络采用COCO的12个评估指标，如下所示。通常记录精度时采用IoU=0.5时的Average Precision（即PASCAL VOC metric）。

Average Precision (AP):
- AP: % AP at IoU=.50:.05:.95 (primary challenge metric)
- AP^{IoU}=.50: % AP at IoU=.50 (PASCAL VOC metric)
- AP^{IoU}=.75: % AP at IoU=.75 (strict metric)

AP Across Scales:
- AP^{small}: % AP for small objects: area < 32^2
- AP^{medium}: % AP for medium objects: 32^2 < area < 96^2
- AP^{large}: % AP for large objects: area > 96^2

Average Recall (AR):
- AR^{max=1}: % AR given 1 detection per image
- AR^{max=10}: % AR given 10 detections per image
- AR^{max=100}: % AR given 100 detections per image

AP Across Scales:
- AP^{small}: % AP for small objects: area < 32^2
- AP^{medium}: % AP for medium objects: 32^2 < area < 96^2
- AP^{large}: % AP for large objects: area > 96^2

### 数据集
另外, 验证时使用的数据集需要自行下载, 分类网络使用ILSVRC2012的验证集(共50000张图片, https://www.image-net.org/challenges/LSVRC/2012/)。数据集中的图片有两种摆放方式, 一种是数据集目录下有1000个子目录, 对应1000个类别, 每个子目录下有50张该类别的图片, 该情况下无需标签文件; 另外一种是所有图片均在同一个数据集目录下, 有一个额外的txt标签文件, 按照图片编号顺序每行用1-1000的数字表示每一张图片的类别。

目标检测网络使用COCO2017验证集(共5000张图片, https://cocodataset.org/#download), 所有图片均在同一数据集目录下, 另外还需要下载与该数据集对应的标签文件.json。

## 精度验证接口

TPU-MLIR的精度验证命令参考如下:

```shell
$ model_eval.py \
    --model_file mobilenet_v2.mlir \
    --count 50 \
    --dataset_type imagenet \
    --postprocess_type topx \
    --dataset datasets/ILSVRC2012_img_val_with_subdir
```

所支持的参数如下:

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_file | 是 | 指定模型文件 |
| dataset | 否 | 数据集目录 |
| dataset_type | 否 | 数据集类型, 当前主要支持imagenet, coco, 默认为imagenet |
| postprocess_type | 是 | 精度评估方式, 当前支持topx和coco_mAP |
| label_file | 否 | txt标签文件, 在验证分类网络精度时可能需要 |
| coco_annotation | 否 | json标签文件, 在验证目标检测网络时需要 |
| count | 否 | 用来验证精度的图片数量, 默认使用整个数据集 |

## 精度验证样例
本节以mobilenet_v2和yolov5s分别作为分类网络与目标检测网络的代表进行精度验证。

### mobilenet_v2
1. 数据集下载

   下载ILSVRC2012验证集到datasets/ILSVRC2012_img_val_with_subdir目录下, 数据集的图片采用带有子目录的摆放方式, 因此不需要额外的标签文件。

2. 模型转换

   使用model_transform.py接口将原模型转换为mobilenet_v2.mlir模型, 并通过run_calibration.py接口获得mobilenet_v2_cali_table。具体使用方法请参照"用户界面"章节。tpu层的INT8模型则通过下方的命令获得，运行完命令后会获得一个名为mobilenet_v2_bm1684x_int8_sym_tpu.mlir的中间文件，接下来我们将用该文件进行INT8对称量化模型的精度验证：

```shell
# INT8 对称量化模型
$ model_deploy.py \
   --mlir mobilenet_v2.mlir \
   --quantize INT8 \
   --calibration_table mobilenet_v2_cali_table \
   --processor BM1684X \
   --test_input mobilenet_v2_in_f32.npz \
   --test_reference mobilenet_v2_top_outputs.npz \
   --tolerance 0.95,0.69 \
   --model mobilenet_v2_int8.bmodel
```

3. 精度验证

   使用model_eval.py接口进行精度验证:

```shell
# F32 模型精度验证
$ model_eval.py \
    --model_file mobilenet_v2.mlir \
    --count 50000 \
    --dataset_type imagenet \
    --postprocess_type topx \
    --dataset datasets/ILSVRC2012_img_val_with_subdir

# INT8 对称量化模型精度验证
$ model_eval.py \
    --model_file mobilenet_v2_bm1684x_int8_sym_tpu.mlir \
    --count 50000 \
    --dataset_type imagenet \
    --postprocess_type topx \
    --dataset datasets/ILSVRC2012_img_val_with_subdir
```

F32模型与INT8对称量化模型的精度验证结果如下:

```shell
# mobilenet_v2.mlir精度验证结果
2022/11/08 01:30:29 - INFO : idx:50000, top1:0.710, top5:0.899
INFO:root:idx:50000, top1:0.710, top5:0.899

# mobilenet_v2_bm1684x_int8_sym_tpu.mlir精度验证结果
2022/11/08 05:43:27 - INFO : idx:50000, top1:0.702, top5:0.895
INFO:root:idx:50000, top1:0.702, top5:0.895
```

### yolov5s
1. 数据集下载

   下载COCO2017验证集到datasets/val2017目录下, 该目录下即包含5000张用于验证的图片。对应的标签文件instances_val2017.json下载到datasets目录下。

2. 模型转换

   转换流程与mobilenet_v2相似。

3. 精度验证

   使用model_eval.py接口进行精度验证:

```shell
# F32 模型精度验证
$ model_eval.py \
    --model_file yolov5s.mlir \
    --count 5000 \
    --dataset_type coco \
    --postprocess_type coco_mAP \
    --coco_annotation datasets/instances_val2017.json \
    --dataset datasets/val2017

# INT8 对称量化模型精度验证
$ model_eval.py \
    --model_file yolov5s_bm1684x_int8_sym_tpu.mlir \
    --count 5000 \
    --dataset_type coco \
    --postprocess_type coco_mAP \
    --coco_annotation datasets/instances_val2017.json \
    --dataset datasets/val2017
```

F32模型与INT8对称量化模型的精度验证结果如下:

# yolov5s.mlir精度验证结果

```shell
Average Precision  (AP) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.369
Average Precision  (AP) @[ IoU=0.50      | area=   all | maxDets=100 ] = 0.561
Average Precision  (AP) @[ IoU=0.75      | area=   all | maxDets=100 ] = 0.393
Average Precision  (AP) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.217
Average Precision  (AP) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = 0.422
Average Precision  (AP) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = 0.470
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=  1 ] = 0.300
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets= 10 ] = 0.502
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.542
Average Recall     (AR) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.359
Average Recall     (AR) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = 0.602
Average Recall     (AR) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = 0.670
```

# yolov5s_bm1684x_int8_sym_tpu.mlir精度验证结果

```shell
Average Precision  (AP) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.337
Average Precision  (AP) @[ IoU=0.50      | area=   all | maxDets=100 ] = 0.544
Average Precision  (AP) @[ IoU=0.75      | area=   all | maxDets=100 ] = 0.365
Average Precision  (AP) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.196
Average Precision  (AP) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = 0.382
Average Precision  (AP) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = 0.432
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=  1 ] = 0.281
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets= 10 ] = 0.473
Average Recall     (AR) @[ IoU=0.50:0.95 | area=   all | maxDets=100 ] = 0.514
Average Recall     (AR) @[ IoU=0.50:0.95 | area= small | maxDets=100 ] = 0.337
Average Recall     (AR) @[ IoU=0.50:0.95 | area=medium | maxDets=100 ] = 0.566
Average Recall     (AR) @[ IoU=0.50:0.95 | area= large | maxDets=100 ] = 0.636
```

# QAT量化感知训练

## 基本原理

相比训练后量化因为其不是全局最优而导致的精度损失，QAT量化感知训练能做到基于loss优化的全局最优而尽可能的降低量化精度损失，其基本原理是：在fp32模型训练中就提前引入推理时量化导致的权重和激活的误差，用任务loss在训练集上来优化可学习的权重及量化的scale和zp值，当任务loss即使面临这个量化误差的影响，也能经学习达到比较低的loss值时，在后面真正推理部署量化时，因为量化引入的误差早已在训练时被很好的适应了，只要能保证推理和训练时的计算完全对齐，理论上就保证了推理时量化不会有精度损失。

## tpu-mlir QAT实现方案及特点

### 主体流程

在训练过程中，用户调用模型QAT量化API对训练模型进行修改：推理时op融合后需要量化的op的输入（包括权重和bias）前插入伪量化节点（可配置该节点的量化参数，比如per-chan/layer、是否对称、量化比特数等），然后用户使用修改后模型进行正常的训练流程，完成少数几个轮次的训练后，调用转换部署API接口将训练过的模型转为fp32权重的onnx模型，提取伪量化节点中参数导出到量化参数文本文件中，最后将调优后的onnx模型和该量化参数文件输入到tpu-mlir工具链中，按前面讲的训练后量化方式转换部署即可。

### 方案特点

特点1：基于pytorch；QAT是训练pipeline的一个附加finetune环节，只有与训练环境深度集成才能方便用户各种使用场景，考虑pytorch具有最广泛的使用率，故目前方案仅基于pytorch，若qat后续要支持其他框架，方案会大不相同，其trace、module替换等机制深度依赖原生训练平台的支持。

特点2：客户基本无感；区别于早期需人工深度介入模型转换的方案，本方案基于pytorch fx，能较方便实现模型trace、伪量化节点插入、自定义模块替换等操作，大多数情况下，客户使用较少的用户配置即可完成量化感知训练。

特点3：基于SOPHGO-mq训练框架，该框架基于商汤开源的mqbench修改，增加了对SOPHGO处理器量化特性的支持。

## 安装方法

建议在SOPHGO提供的docker镜像中使用SOPHGO-mq，镜像可以使用docker pull命令获取：

```shell
docker pull sophgo/tpuc_dev:v3.3-cuda
```

此镜像预装了torc2.3.0版本和cuda12.1,为SOPHGO-mq支持的最新版本，另外此镜像也支持tpu-mlir工具直接部署网络到处理器。

### 使用安装包安装

1、在SOPHGO-mq开源项目https://github.com/sophgo/sophgo-mq.git的release区获取最新的安装包，比如 sophgo_mq-1.0.1-cp310-cp310-linux_x86_64.whl
2、使用pip安装： pip3 install sophgo_mq-1.0.1-cp310-cp310-linux_x86_64.whl

### 从源码安装

1、执行命令获取github上最新代码:git clone https://github.com/sophgo/sophgo-mq.git

2、进入SOPHGO-mq目录后执行:

```shell
pip install -r requirements.txt #注:当前要求torch版本为2.3.0
python setup.py install
```

3、执行python -c 'import sophgo_mq'若没有返回任何错误，则说明安装正确，若安装有错，执行pip uninstall sophgo_mq卸载后再尝试。

## 基本步骤

### 步骤0：接口导入及模型prepare

在训练文件中添加如下python模块import接口:

```python
import torch
import torchvision.models as models
from sophgo_mq.prepare_by_platform import prepare_by_platform   #初始化接口
from sophgo_mq.utils.state import enable_quantization, enable_calibration    #校准和量化开关
from sophgo_mq.convert_deploy import convert_deploy                          #转换部署接口
import tpu_mlir			#tpu_mlir模块，引入之后可以实现一键式转换bmodel在处理器上部署
from tools.model_runner import mlir_inference  #tpu_mlir的推理模块，可以在量化感知训练阶段使用tpu_mlir的推理直接看到训练模型在处理器上的精度表现

#使用torchvision model zoo里的预训练resnet18模型
model = models.__dict__['resnet18'](pretrained=True)

#1.trace模型，使用字典来指定处理器类型为BM1690，量化模式为weight_activation，在该量化模式下，权重和激活都会被量化。指定量化策略为CNN类型
extra_prepare_dict = {
'quant_dict': {
                'chip': 'BM1690',
                'quantmode': 'weight_activation',
                'strategy': 'CNN',
                },
}
model_quantized = prepare_by_platform(model, prepare_custom_config_dict=extra_prepare_dict)
```

当上面接口选择处理器为BM1690时，此时默认的量化配置如下图所示：

上图量化配置中各项从上到下依次意义为：

1、权重量化方案为： per-channel对称8bit量化，scale系数不是power-of-2，而是任意的

2、激活量化方案为：per-layer对称8bit量化

3/4、权重和激活伪量化方案均为：LearnableFakeQuantize即LSQ算法

5/6、权重的动态范围统计及scale计算方案为：MinMaxObserver，激活的为带EMA指数移动平均的EMAMinMaxObserver

### 步骤1：用于量化参数初始化的校准及量化训练

设置好合理的训练超参数，就可以开始量化感知训练，建议如下:
      --epochs=1：约在1~3即可；
      --lr=1e-4：学习率应该是fp32收敛时的学习率，甚至更低些；
      --optim=sgd：默认使用sgd；

```python
#1.打开校准开关，容许在模型上推理时用pytorch observer对象来收集激活分布并计算初始scale和zp
enable_calibration(model_quantized)
# 校准循环
for i, (images, _) in enumerate(cali_loader):
    model_quantized(images) #只需要前向推理即可
#3.打开伪量化开关，在模型上推理时会调用QuantizeBase子对象来进行伪量化操作引入量化误差
enable_quantization(model_quantized)
# 训练循环
for i, (images, target) in enumerate(train_loader):
    #前向推理并计算loss
    output = model_quantized(images)
    loss = criterion(output, target)
    #后向反传梯度
    loss.backward()
    #更新权重和伪量化参数
    optimizer.step()
```

### 步骤2：导出调优后的fp32模型及量化参数文件

```python
#batch-size可根据需要调整，不必与训练batch-size一致
input_shape={'input': [4, 3, 224, 224]}
# 指定导出模型类型为CNN
net_type='CNN'
#4.导出前先融合conv+bn层（前面train时未真正融合），将伪量化节点参数保存到参数文件，然后移除。
convert_deploy(model_quantized, net_type, input_shape)
```

### 步骤3：转换部署

使用tpu-mlir的model_transform.py及model_deploy.py脚本完成到sophg-tpu硬件的转换部署。
在训练阶段引入tpu_mlir，可以直接使用tpu_mlir的推理接口直接模拟模型在处理器上的运行，从而了解训练进展，如果使用此接口，则在训练过程中就已经转化部署了模型文件，生成了bmodel。一般可以在传统的验证流程中将模型推理替换为mlir_inference，输入输出为numpy数组，调用tpu_mlir推理的示例接口如下：

```python
import tpu_mlir
from tools.model_runner import mlir_inference
...
for i, (images, target) in enumerate(bmodel_test_loader):
    images = images.cpu()
    target = target.cpu()
    inputs['data'] = images.numpy()
    output = mlir_inference(inputs, mlir_model_path, dump_all = False)
    output = torch.from_numpy(list(output.values())[0])
    loss = criterion(output, target)
```

## 使用样例-resnet18

执行application/imagenet_example/main.py对resent18进行qat训练，命令如下：

```shell
CUDA_VISIBLE_DEVICES=0 python application/imagenet_example/main.py \
    --arch=resnet18 \
    --batch-size=128 \
    --lr=1e-4 \
    --epochs=1 \
    --optim=sgd \
    --cuda=0 \
    --pretrained \
    --evaluate \
    --train_data=/home/data/imagenet \
    --val_data=/home/data/imagenet \
    --chip=BM1690 \
    --quantmode=weight_activation \
    --deploy_batch_size=10 \
    --pre_eval_and_export \
    --output_path=./
```

在上面命令输出日志中有如下图原始模型的精度信息（可与官方网页上精度进行比对以确认训练环境无误，比如官方标称：Acc@1 69.76 Acc@5 89.08，链接为:https://pytorch.apachecn.org/#/docs/1.0/torchvision_models）:

原始onnx模型精度

完成qat训练后，跑带量化节点的eval精度，理论上在tpu-mlir的int8精度应该与此完全对齐，如下图：

resnet18 qat训练精度

最终输出目录如下图：

resnet18 qat训练输出模型目录

上图中resnet18_ori.onnx为pytorch原始模型所转的onnx文件，将这个resnet18_ori.onnx用tpu-mlir工具链进行PTQ量化，衡量其对称和非对称量化精度作为比较的baseline。其中的resnet18_cali_table_from_sophgo_mq为导出的量化参数文件，内容如下图：

resnet18 qat量化参数表样例

a、上图中第一行红色框内:work_mode为QAT_all_int8表示整网int8量化，可以在[QAT_all_int8、 QAT_mix_prec]中选择，还会带上量化参数:对称非对称等参数。

b、上图中472_Relu_weight表示是conv权重的经过QAT调优过的scale和zp参数，第1个64表示后面跟着64个scale，第2个64表示后面跟着64个zp，tpu-mlir会导入到top层weight的weight_scale属性中，在int8 lowering时若该属性存在就直接使用该属性，不存在就按最大值重新计算。

c、上面的min、max是非对称量化时根据激活的qat调优过的scale、zp以及qmin、qmax算出来，threshold是在对称量化时根据激活的scale算出来，两者不会同时有效。

## QAT测试环境

量化感知训练输出的网络最终要在SOPHGO处理器上运行，其精度可以使用端到端的推理验证程序来验证，一般在模型部署的环境中测试即可。
在单机上也可以在tpu_mlir阶段使用tpu_mlir提供的模型验证程序在CPU上模拟验证，特别是简单的分类网络可以比较方便的验证其精度。一般步骤如下：

### 添加cfg文件

进入tpu-mlir/regression/eval目录，在qat_config子目录下增加{model_name}_qat.cfg，比如如下为resnet18_qat.cfg文件内容：

```shell
dataset=${REGRESSION_PATH}/dataset/ILSVRC2012
test_input=${REGRESSION_PATH}/image/cat.jpg
input_shapes=[[1,3,224,224]]  #根据实际shape修改
resize_dims=256,256           #下面为图片预处理参数，根据实际填写
mean=123.675,116.28,103.53
scale=0.0171,0.0175,0.0174
pixel_format=rgb
int8_sym_tolerance=0.97,0.80
int8_asym_tolerance=0.98,0.80
debug_cmd=use_pil_resize
```

也可增加{model_name}_qat_ori.cfg文件：将原始pytorch模型量化，作为baseline，内容可以和上面{model_name}_qat.cfg完全一样；

### 修改并执行run_eval.py

下图run_eval_param中在postprocess_type_all中填写更多不同精度评估方式的命令字符串，比如图中已有imagenet分类和coco检测精度计算字符串；下图run_eval_param中model_list_all填写模型名到参数的映射，比如：resnet18_qat的[0,0]，其中第1个参数表示用postprocess_type_all中第1个的命令串，第2个参数表示用qat_model_path第1个目录（以逗号分隔）：

run_eval待测模型列表及参数

根据需要配置上图postprocess_type_all和model_list_all数组后，执行下面run_eval.py命令:

```shell
python3 run_eval.py
    #qat验证模式，默认是使用tpu-mlir/regression/config中配置进行常规的模型精度测试
    --qat_eval
    --fast_test       #正式测试前的快速测试（只测试30张图的精度），确认所有case都能跑起来
    --pool_size 20    #默认起10个进程来跑，若机器闲置资源较多，可多配点
    --batch_size 10   #qat导出模型的batch-size，默认为1
    --qat_model_path '/workspace/classify_models/,/workspace/yolov5/qat_models'  #qat模型所在目录，比如model_list_all[‘resnet18_qat’][1]的取值为0，表示其模型目标在qat_model_path的第1个目录地址:/workspace/classify_models/
    --debug_cmd use_pil_resize      #使用pil resize方式
```

# TpuLang接口

本章节主要介绍使用TpuLang转换模型的流程。

## 主要工作

TpuLang提供了mlir对外的接口函数。用户通过TpuLang可以直接组建自己的网络，将模型转换为 Top 层(硬件无关层) mlir 模型(不包含 Canonicalize 部分, 因此生成的文件名为"*_origin.mlir")。这个过程会根据输入的接口函数逐一创建并添加算子(Op), 最终生成 mlir 文件与保存权重的 npz 文件。

## 工作流程

1. 初始化：设置运行平台，创建模型Graph。
2. 添加OPS：循环添加模型的OP
   - 输入参数转为dict格式；
   - 创建输出tensor；
   - 设置tensor的量化参数(scale, zero_point)；
   - 创建op(op_type, inputs, outputs, params)并insert到graph中。
3. 设置模型的输入输出tensor。得到全部模型信息。
4. 初始化TpuLangConverter(initMLIRImporter)
5. generate_mlir
   - 依次创建 input op, 模型中间 nodes op 以及 return op, 并将其补充到 mlir 文本中(如果该 op 带有权重, 则会额外创建 weight op)
6. 输出(Output)
   - 将生成的文本转为 str 并保存为".mlir"文件
   - 将模型权重(tensors)保存为".npz"文件
7. 结束：释放 graph。

TpuLang转换的工作流程如图所示。

## 补充说明

- op 接口需要：
  - op的输入tensor(即前一个算子的输出tensor或graph输入tensor，coeff)；
  - 从接口中提取的 attrs。Attrs 会通过 MLIRImporter 设定为与 TopOps.td 定义一一对应的属性
  - 如果接口中包括量化参数(scale，zero_point)，则该参数对应的tensor需要设置(或检查)量化参数。
  - 返回该op的输出tensor(tensors)
- 在所有算子都插入graph，并设置graph的input/output tensors之后，才会启动转换到 mlir 文本的工作。该部分由TpuLangConverter来实现。
- TpuLang Converter转换流程与onnx前端转换流程相同，具体参考相关文档。

## 算子转换样例

本节以 Conv 算子为例, 将单 Conv 算子模型转换为 Top mlir

```python
import numpy as np

def model_def(in_shape):
   tpul.init("BM1684X")
   in_shape = [1,3,173,141]
   k_shape =[64,1,7,7]
   x = tpul.Tensor(dtype='float32', shape=in_shape)
   weight_data = np.random.random(k_shape).astype(np.float32)
   weight = tpul.Tensor(dtype='float32', shape=k_shape, data=weight_data, is_const=True)
   bias_data = np.random.random(k_shape[0]).astype(np.float32)
   bias = tpul.Tensor(dtype='float32', shape=k_shape[0], data=bias_data, is_const=True)
   conv = tpul.conv(x, weight, bias=bias, stride=[2,2], pad=[0,0,1,1], out_dtype="float32")
   tpul.compile("model_def", inputs=[x],outputs=[conv], cmp=True)
   tpul.deinit()
```

单 Conv 模型

转换流程为:

### 1. 接口定义

conv 接口定义如下：

```python
def conv(input: Tensor,
         weight: Tensor,
         bias: Tensor = None,
         stride: List[int] = None,
         dilation: List[int] = None,
         pad: List[int] = None,
         group: int = 1,
         out_dtype: str = None,
         out_name: str = None):
   # pass
```

参数说明

- input：Tensor类型，表示输入Tensor，4维NCHW格式。
- weight：Tensor类型，表示卷积核Tensor，4维[oc, ic, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kh是kernel_h，kw是kernel_w。
- bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]。
- dilation：List[int]，表示空洞大小，取None则表示[1,1]，不为None时要求长度为2。List中顺序为[长，宽]
- pad：List[int]，表示填充大小，取None则表示[0,0,0,0]，不为None时要求长度为4。List中顺序为[上， 下， 左， 右]
- stride：List[int]，表示步长大小，取None则表示[1,1]，不为None时要求长度为2。List中顺序为[长，宽]
- groups：int型，表示卷积层的组数。若ic=oc=groups时，则卷积为depthwise conv
- out_dtype：string类型或None，表示输出Tensor的类型。输入tensor类型为float16/float32时，取None表示输出tensor类型与输入一致，否则取None表示为int32。取值范围：/int32/uint32/float32/float16
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

在 TopOps.td 中定义 Top.Conv 算子。

### 2. 构建 Graph

- 初始化模型：创建空Graph。
- 模型输入：给定shape与data type 创建输入tensor x。此处也可以指定tensor name。
- conv接口：
  - 调用conv接口，指定输入tensor以及输入参数。
  - 生成输出tensor
    ```python
    output = Tensor(dtype=out_dtype, name=out_name)
    ```
  - attributes，将输入参数打包成定义的attributes
    ```python
    attr = {
       "kernel_shape": ArrayAttr(weight.shape[2:]),
       "strides": ArrayAttr(stride),
       "dilations": ArrayAttr(dilation),
       "pads": ArrayAttr(pad),
       "do_relu": Attr(False, "bool"),
       "group": Attr(group)
    }
    ```
  - 定义输出tensor
  - 插入conv op，将Top.ConvOp插入到Graph中。
  - 返回输出tensor
- 设置Graph的输入，输出tensors。

### 3. init_MLIRImporter

根据 input_names 与 output_names 从 shapes 中获取了对应的 input_shape 与 output_shape, 加上model_name, 生成了初始的 mlir 文本 MLIRImporter.mlir_module。

### 4. generate_mlir

- build input op, 生成的 Top.inputOp 会被插入到 MLIRImporter.mlir_module 中。
- 调用Operation.create 来创建 Top.ConvOp, 而 create 函数需要的参数有:
  - 输入 op: 从接口定义可知, Conv 算子的 inputs 一共包含了 input, weight 与 bias, inputOp 已被创建好, weight 与 bias 的 op 则通过 getWeightOp()创建。
  - output_shape: 利用 Operator 中存储的输出 tensor 中获取其 shape。
  - Attributes: 从 Operator 中获取 attributes，并将attributes转换为MLIRImporter识别的Attributes
  Top.ConvOp 创建后会被插入到 mlir 文本中
- 根据 output_names 从 operands 中获取相应的 op, 创建 return_op 并插入到 mlir 文本中。

### 5. 输出

将 mlir 文本保存为 Conv_origin.mlir, tensors 中的权重保存为 Conv_TOP_F32_all_weight.npz。

## Tpulang接口使用方式

目前TpuLang只适用于推理框架的推理部分。类tensorflow等框架的静态图，使用TpuLang进行网络集成时，用户需要首先使用tpul.init('processor')初始化（processor可以是BM1684X或者BM1688），然后准备tensor，接着使用operator构建网络，最后调用tpul.compile接口编译生成bmodel。下面详细介绍一下每一步怎么做，以下使用到的各种接口（tpul.init, deinit, Tensor以及算子接口等）都可以在相关附录中查看到详细介绍。

以下步骤假定当前已经完成tpu-mlir发布包的加载。

### 初始化

具体的定义参见初始化函数

```python
import transform.TpuLang as tpul
import numpy as np

tpul.init('BM1684X')
```

### 准备Tensor

具体的定义参见tensor相关文档

```python
shape = [1, 1, 28, 28]
x_data = np.random.randn(*shape).astype(np.float32)
x = tpul.Tensor(dtype='float32', shape=shape, data=x_data)
```

### 构建graph

接着利用现有的OP和刚刚准备好的Tensor构建graph，下面是一个简单的模型构建示例：

```python
def conv_op(x,
            kshape,
            stride,
            pad=None,
            group=1,
            dilation=[1, 1],
            bias=False,
            dtype="float32"):
   oc = kshape[0]
   weight_data = np.random.randn(*kshape).astype(np.float32)
   weight = tpul.Tensor(dtype=dtype, shape=kshape, data=weight_data, ttype="coeff")
   bias_data = np.random.randn(oc).astype(np.float32)
   bias = tpul.Tensor(dtype=dtype, shape=[oc], data=bias_data, ttype="coeff")
   conv = tpul.conv(x,
               weight,
               bias=bias,
               stride=stride,
               pad=pad,
               dilation=dilation,
               group=group)
   return conv

def model_def(x):
   conv0 = conv_op(x, kshape=[32, 1, 5, 5], stride=[1,1], pad=[2, 2, 2, 2], dtype='float32')
   relu1 = tpul.relu(conv0)
   maxpool2 = tpul.maxpool(relu1, kernel=[2, 2], stride=[2, 2], pad=[0, 0, 0, 0])
   conv3 = conv_op(maxpool2, kshape=[64, 32, 5, 5], stride=[1,1], pad=[2, 2, 2, 2], dtype='float32')
   relu4 =  tpul.relu(conv3)
   maxpool5 = tpul.maxpool(relu4, kernel=[2, 2], stride=[2, 2], pad=[0, 0, 0, 0])
   conv6 = conv_op(maxpool5, kshape=[1024, 64, 7, 7], stride=[1,1], dtype='float32')
   relu7 =  tpul.relu(conv6)
   softmax8 = tpul.softmax(relu7, axis=1)
   return softmax8

y = model_def(x)
```

# compile

调用tpul.compile函数，编译完成后会得到 `example_f32.bmodel`：

```python
tpul.compile("example", [x], [y], mode="f32")
```

# deinit

具体的定义参见反初始化函数：

```python
tpul.deinit()
```

# deploy

最后使用model_deploy.py完成模型部署，具体使用方法参考定义。

# 用户自定义算子

## 概述

tpu-mlir当前已经包含了丰富的算子库，可以满足大部分神经网络模型的编译需求。但在某些场景下，可能需要用户自定义算子来实现对张量的计算。如：

1. tpu-mlir 还未支持的算子，且无法通过其它算子组合实现
2. 算子为用户私有，未对公众开源
3. 使用多个算子 API 组合无法取得最佳计算性能，直接从 tpu-kernel 层自定义运算可以提高运行效率

自定义算子功能允许用户自由使用tpu-kernel中的接口，自定义tensor在tpu上的计算，并将这一计算过程封装为后端算子（后端算子开发请参考TPU-KERNEL开发参考手册）。其中，后端算子计算涉及到global layer与local layer相关操作：

a. 算子必须实现 global layer ，global layer 的输入和输出数据都放在 ddr 中，数据需要从 global mem 搬运到 local mem 中执行运算，再将结果搬运至 global mem。其优点是 local mem 可以任意使用，比较灵活；缺点是会产生较多的 gdma 搬运，tpu 利用率较低。

b. 算子根据需要实现 local layer，local layer 的输入和输出的数据都放在 local mem 中，可以与其他 layer 组合进行 LayerGroup 优化，避免该 layer 计算时数据要搬入搬出到 global mem 中。其优点是可以节省 gdma 搬运, 运算效率高；缺点是比较复杂，local mem 在模型部署时会提前分配好，不可任意使用，在部分算子中无法实现，关于local layer的更多细节请参考 LayerGroup 章节。

c. 用户还需要实现自定义算子的一些补丁函数，用于在编译阶段进行正确性对比，形状推断以及实现更复杂的 local layer 等。

完成后端算子的封装后，前端可以通过tpulang或caffe构建包含自定义算子的模型,并最终通过 tpu-mlir 的模型转换接口完成模型部署。本章主要介绍在tpu-mlir发布包中使用自定义算子的流程。

## 自定义算子添加流程

注意: 在下文中, {op_name} 表示算子的名字, 且字符串长度应不超过 20 。{processor_arch} 表示架构名称，当前可选 `BM1684X` 和 `BM1688` 。

### TpuLang自定义算子添加

1. 加载tpu-mlir

2. 定义参数结构体与解析函数

a. 在 `$TPUC_ROOT/customlayer/include/backend_custom_param.h` 中定义算子参数的结构体，该结构体会被应用在后续步骤中的各个函数里。结构体示例如下：

```c
typedef struct {op_name}_param {
  ...
} {op_name}_param_t;
```

b. 用户需要根据算子所需的参数在 `$TPUC_ROOT/customlayer/include/param_parser.h` 中实现相应的函数用于解析由工具链前端传递过来的参数。工具链前端的参数是通过 `custom_param_t` 数组的指针进行传递，其中，数组的第一个元素是保留的，从第二个元素开始，每个元素对应前端的一个属性，每个 `custom_param_t` 结构体中包含了一个参数的信息，参数值会被存放在相应数据类型（其中包含了整数，浮点数，整数数组与浮点数数组）的 `custom_param_t` 成员变量中。参数的顺序与用户后续调用tpulang接口时提供的参数顺序相同。 `custom_param_t` 结构体的定义如下：

```c
typedef union {
  int int_t;
  float float_t;
  // max size of int and float array is set as 16
  int int_arr_t[16];
  float float_arr_t[16];
} custom_param_t;
```

解析函数的示例如下：

```c
static {op_name}_param_t {op_name}_parse_param(const void* param) {
  ...
}
```

3. 编译器补丁

有时候，需要对编译器进行修改，以对不同的自定义算子在不同参数下的编译行为进行控制，这时候就需要添加一些补丁。当前已支持以下补丁函数(在文件夹 ./plugin中定义)：

a. （必选）推理函数。此补丁函数用于TOP层和TPU层的数据比对。补丁函数形式如下：

```c
void inference_absadd(void* param, int param_size, const int (*input_shapes)[MAX_SHAPE_DIMS],
  const int* input_dims, const float** inputs, float** outputs);
```

其中，input_shapes为输入张量形状的数组，input_dims为输入张量维度的数组。inputs表示输入张量的指针数组，outputs表示输出张量的指针数组。

b. （可选）形状推断函数。此补丁函数用于TOP层形状推断，若不实现，默认只有一个输入一个输出，且输出形状跟输入形状相同。补丁函数形式如下：

```c
void shape_inference_absadd(void* param, int param_size, const int (*input_shapes)[MAX_SHAPE_DIMS],
  const int* input_dims, int (*output_shapes)[MAX_SHAPE_DIMS], int* output_dims);
```

其中，input_shapes/output_shapes为输入/出张量形状的数组，input_dims/output_dims为输入/出张量维度的数组。

c. （可选）强制动态运行。某些算子的形状会动态变化（如 NonZero 算子），即使在静态编译下也需要强制动态运行。补丁函数形式如下：

```c
bool force_dynamic_run_{op_name}(void* param, int param_size);
```

若不提供该函数，则{op_name}对应的算子必须静态运行。

d. （可选）是否支持与其他算子组合（用于local layer）。补丁函数形式如下：

```c
bool local_gen_support_{op_name}(void* param, int param_size);
```

若不提供该函数，则{op_name}对应的算子不支持与其他算子组合，即强制走global layer。否则，需要实现对应的 local layer 调用接口 `api_xxx_local`和 `api_xxx_local_bfsz` （可选）。

e. （可选）在支持与其他算子组合时，是否允许对轴axis进行切割。补丁函数形式如下：

```c
bool allow_data_split_{op_name}(void* param, int param_size, int axis, group_type_t group_type);
```

若不提供该函数，则默认与其他算子组合时，{op_name} 对应的算子允许对所有的轴进行切割。

f. （可选）切片反向推导函数，同样应用于 local layer （详情请参考 LayerGroup 章节）。补丁函数形式如下：

```c
bool backwardh_{op_name}(void* param, int param_size, int* in_idx, int* in_slice, int out_idx, int out_slice);

bool backwardw_{op_name}(void* param, int param_size, int* in_idx, int* in_slice, int out_idx, int out_slice);
```

其中，in_idx和in_slice分别表示指向该层输入张量切片的索引和大小的指针，out_idx和out_slice表示该层输出张量切片的索引索引和大小。若不提供该函数，则in_idx指向的数值与out_idx相同，in_slice指向的数值与out_slice相同。

4. 编写后端算子

后端算子可基于tpu-kernel编写（4.1）， 也可基于ppl编写（4.2）

#### 4.1 基于tpu-kernel编写后端算子

假定当前处于 $TPUC_ROOT/customlayer 路径下：

a. 在./include/tpu_impl_custom_ops.h 头文件中，声明 global layer 与 local layer 的自定义算子函数

```c
void tpu_impl_{op_name}_global // 必选

void tpu_impl_{op_name}_local  // 可选
```

b. 在 ./src 下添加 tpu_impl_{op_name}.c 文件，在其中调用tpu-kernel接口实现自定义算子kenel函数。

c. 在 ./src 下添加 interface_{op_name}.c 文件，在其中实现自定义算子调用接口:

```c
void api_{op_name}_global // 必选，用于调用 void tpu_impl_{op_name}_global

void api_{op_name}_local  // 可选，用于调用 void tpu_impl_{op_name}_local
```

#### 4.2 基于ppl编写后端算子

假定当前处于 $TPUC_ROOT/customlayer 路径下:

a. 在./PplBackend/src下导入{op_name}.pl（ppl kernel定义与实现）

b. 在./PplBackend/src下导入{op_name}_tile.cpp（切分函数，指定dtype对应的后端实现）

```c
// kernelFunc定义和函数名{op_name}.pl中保持一致
using KernelFunc = int (*)(global_addr_t, global_addr_t,
                          float, int, int, int, int, int, bool);

int {op_name}_tiling/{op_name}(...) { // 必选
  KernelFunc func;
  if (dtype == SG_DTYPE_FP32) {
    func = {op_name}_f32;
  } else if (dtype == SG_DTYPE_FP16) {
    func = {op_name}_f16;
  } else if (dtype == SG_DTYPE_BFP16) {
    func = {op_name}_bf16;
  ....
  } else {
    assert(0 && "unsupported dtype");
  }
  // 切分函数（可选）
...
}
```

c. 在./PplBackend/src下导入{op_name}_api.c（接口函数）

```c
extern int {op_name}_tiling/{op_name} (...); // 必选

void api_addconst_global/local(..., onst void *param) { // 必选
  PARSE_PARAM({op_name}, {op_name}_param, param);
  {op_name}_tiling/{op_name}(...);
}
```

5. 编写算子通用接口

在 ./src 目录下添加自定义算子函数的调用接口:

```c
int64_t api_{op_name}_global_bfsz (可选，计算global layer需要的缓存大小)

int api_{op_name}_local_bfsz (可选，计算local layer需要的缓存大小，缓存用于存储计算的中间结果，提前计算用于 LayerGroup 搜索 layer 间的最佳组合)

void type_infer_{op_name} (可选，动态时使用，从输入的形状和数据类型推理出输出的形状和数据类型，若不实现，则默认只有一个输入和一个输出，且输出的形状和数据类型与输入的形状和数据类型相同)

void slice_infer_{op_name} (可选，动态时使用，从输入的切片推理出输出的切片，若不实现，则默认只有一个输入和一个输出，且输出的切片与输入的切片相同)
```

6. 注册后端算子调用接口

在 register_ops.cmake 中添加算子的名字以注册自定义算子：

```shell
register_custom_op({op_name})     // 4.1 基于tpu-kernel编写后端算子

// OR

register_custom_ppl_op({op_name}) // 4.2 基于ppl编写后端算子
```

假如自定义算子存在local layer，则需要注册一下:

```shell
register_custom_local_op({op_name})       // 4.1 基于tpu-kernel编写后端算子

// OR

register_custom_ppl_local_op({op_name})   // 4.2 基于ppl编写后端算子
```

假如自定义算子global layer需要缓存，则需要注册一下:

```shell
register_custom_global_bfsz({op_name})
```

假如自定义算子local layer需要缓存，则需要注册一下:

```shell
register_custom_local_bfsz({op_name})
```

7. 编译并安装动态库

先初始化环境：

```shell
source $TPUC_ROOT/customlayer/envsetup.sh
```

然后需要完成补丁的编译（得到 `libplugin_custom.so`）：

```shell
rebuild_custom_plugin
```

自定义算子后端接口的编译（得到 `libbackend_custom.so`）：

```shell
rebuild_custom_backend
```

之后根据实际使用场景编译对应的固件（用于动态算子）：

a. CMODEL模式（得到 `libcmodel_custom_xxx.so`）

```shell
rebuild_custom_firmware_cmodel {processor_arch}
```

b. SoC模式（得到 `libxxx_kernel_module_custom_soc.so`）

```shell
rebuild_custom_firmware_soc {processor_arch}
```

c. PCIe模式（得到 `libxxx_kernel_module_custom_pcie.so`）

```shell
rebuild_custom_firmware_pcie {processor_arch}
```

至此我们就完成了自定义算子后端部分的工作。

8. 调用TpuLang构建模型

有关如何使用 TpuLang 的说明，请参阅 "TPULang接口" 部分。

TpuLang 提供了 `TpuLang.custom` 接口来在工具链前端构建自定义算子（请确保 `op_name` 与后端算子的名称匹配）：注意，`params` 应该是 python 中的字典，其 key 应该是 是一个表示参数名称的字符串，值应该是整数或浮点数，或者是整数或浮点数的列表（列表的长度不应大于16）。 在构建神经网络时，对于相同的自定义运算符和相同的键，键的数量和顺序应保持相同，如果其值为列表，则长度应保持相同。

```python
def custom(tensors_in: List[TpuLang.Tensor],
               op_name: str,
               out_dtypes: List[str],
               out_names: List[str] = None,
               params: dict = None)
               -> List[TpuLang.Tensor]
'''
    The custom op
    Arguments:
        tensors_in: list of input tensors (including weight tensors).
        op_name: name of the custom operator.
        out_dtypes: list of data type of outputs.
        out_names: list of name of outputs.
        params: parameters of the custom op.

    Return:
        tensors_out: list of output tensors.
'''
```

a. 定义自定义算子的tpulang接口

为了方便起见，可以在文件 $TPUC_ROOT/customlayer/python/my_tpulang_layer.py 中标准化自定义运算符：

```python
import transform.TpuLang as tpul

class xxx:
  @staticmethod
  def native(...):
      ...
      return ...
  @staticmethod
  def tpulang(inputs, ...):
      params = dict(...)
      outputs = tpul.custom(
          tensors_in=inputs,
          op_name={op_name},
          params=params,
          out_dtypes=...)
      return outputs
```

其中 `native` 函数用于计算自定义层的参考输出数据。 `tpulang` 函数使用 `TpuLang.custom` 函数构造自定义层。

b. 单元测试

定义完自定义算子后，需要测试一下这个接口是否可靠。 在目录 `$TPUC_ROOT/customlayer/test_if/unittest` 中，创建一个名为 `test_{op_name}.py` 的 python 文件。 在此文件中，创建一个派生自 `TestTPULangCustom` 的类并创建测试函数。

下面的 shell 命令将用于执行单元测试：

```shell
 run_custom_unittest {processor_arch}
```

9. 上卡测试

当网络中存在动态自定义算子时，bmodel中包含的固件可能无法使bmrt_test正常工作，这时就需要替换固件了，使用shell命令可以达到这一目标：

```shell
tpu_model --kernel_update xxx.bmodel libxxx_kernel_module_custom_soc.so #SoC模式下

tpu_model --kernel_update xxx.bmodel libxxx_kernel_module_custom_pcie.so #PCIe模式下
```

### Caffe自定义算子添加

# 定义Caffe的自定义算子

要定义 Caffe 的自定义算子，你需要在`$TPUC_ROOT/customlayer/python/my_caffe_layer.py`文件中定义一个类，该类继承自 caffe.Layer，并根据需要重写 `setup`, `reshape`, `forward` 和 `backward` 函数。

# 实现自定义算子前端转换函数

通过Python实现的自定义算子的caffe层类型为 "Python"，需要在 `$TPUC_ROOT/customlayer/python/my_converter.py` 中的 `MyCaffeConverter` 类里根据之前的自定义算子定义一个针对caffe层类型为 "Python" 的前端算子转换函数。完成转换函数后便可通过 `MyCaffeConverter` 对包含自定义算子的Caffe模型进行前端转换。

定义完成后，可以调用my_converter.py接口进行Top MLIR转换:

```shell
my_converter.py \
--model_name # the model name \
--model_def # .prototxt file \
--model_data # .caffemodel file \
--input_shapes # list of input shapes (e.g., [[1,2,3],[3,4,5]]) \
--mlir # output mlir file
```

后端部分与 "TpuLang自定义算子添加" 中的步骤相同，此处不再赘述。

# 自定义算子示例

本节内容假定已经完成了tpu-mlir发布包加载。

## TpuLang示例

本小节提供了一个swapchanel算子实现与通过TpuLang接口应用的样例。

### 1. 算子参数解析

在文件 `${TPUC_ROOT}/customlayer/include/backend_custom_param.h` 中定义参数结构体 `swapchannel_param_t`：

```c
typedef struct swapchannel_param {
  int order[3];
} swapchannel_param_t;
```

其中，这里的字段order对应前端的属性order 。

值得注意的是，从编译器传递到后端的是一个 `custom_param_t` 的数组A，它的第一个元素是保留的，从第二个元素开始，每个元素对应前端的一个属性。为方便起见，在头文件 `{TPUC_ROOT}/customlayer/include/api_common.h` 中，提供了一个宏来完成了一个对应： `PARSE_PARAM(swapchannel, sc_param, param)` , 其中， `param` 表示数组A， `sc_param` 表示后端参数结构体。用户需要在文件 `${TPUC_ROOT}/customlayer/include/param_parser.h` 中定义一个swapchannel_parse_param解析函数来完成这种转换，其输入实际上是数组A的剔除第一个元素后的子数组的指针。 在文件 `${TPUC_ROOT}/customlayer/include/param_parser.h` 中，实现参数解析代码：

```c
static swapchannel_param_t swapchannel_parse_param(const void* param) {
    swapchannel_param_t sc_param = {0};
    for (int i = 0; i < 3; i++) {
        sc_param.order[i] = ((custom_param_t *)param)[0].int_arr_t[i];
    }
    return sc_param;
}
```

参数解析在补丁函数和后端实现中都会被用到。

### 2. 补丁函数

在文件 `${TPUC_ROOT}/customlayer/plugin/plugin_swapchannel.c` 中：

```c
#include <string.h>
#include <assert.h>
#include "param_parser.h"

void inference_swapchannel(void* param, int param_size, const int (*input_shapes)[MAX_SHAPE_DIMS],
  const int* input_dims, const float** inputs, float** outputs) {
  PARSE_PARAM(swapchannel, sc_param, param);
  int in_num = 1;
  for (int i = 2; i < input_dims[0]; ++i) {
    in_num *= input_shapes[0][i];
  }
  int N = input_shapes[0][0];
  int C = input_shapes[0][1];
  assert(C == 3);
  for (int n = 0; n < N; ++n) {
    for (int c = 0; c < 3; ++c) {
      for (int x = 0; x < in_num; ++x) {
        memcpy(outputs[0] + n * C * in_num + sc_param.order[c] * in_num,
              inputs[0] + n * C * in_num + c * in_num, in_num * sizeof(float));
      }
    }
  }
}
```

### 3. 后端算子实现

在 `${TPUC_ROOT}/customlayer/include/tpu_impl_custom_ops.h` 头文件中添加如下声明：

```c
void tpu_impl_swapchannel_global(
    global_addr_t input_global_addr,
    global_addr_t output_global_addr,
    const int *shape,
    const int *order,
    data_type_t dtype);
```

`${TPUC_ROOT}/customlayer/src/tpu_impl_swapchannel.c` 代码如下：

```c
#include "tpu_impl_custom_ops.h"

void tpu_impl_swapchannel_global(
    global_addr_t input_global_addr,
    global_addr_t output_global_addr,
    const int *shape,
    const int *order,
    data_type_t dtype)
{
    dim4 channel_shape = {.n = shape[0], .c = shape[1], .h = shape[2], .w = shape[3]};
    dim4 stride = {0};
    stride.w = 1, stride.h = channel_shape.w;
    stride.c = stride.h * channel_shape.h;
    stride.n = stride.c * channel_shape.c;
    channel_shape.c = 1;
    int data_size = tpu_data_type_size(dtype);
    int offset = channel_shape.w * channel_shape.h * data_size;
    for (int i = 0; i < 3; i++) {
        tpu_gdma_cpy_S2S(
            output_global_addr + i * offset,
            input_global_addr + order[i] * offset,
            &channel_shape,
            &stride,
            &stride,
            dtype);
    }
}
```

### 4. 后端接口

在文件 `${TPUC_ROOT}/customlayer/src/interface_swapchannel.c` 中定义函数 `void type_infer_swapchannel`和 `void api_swapchannel_global`：

```c
#include <string.h>
#include "tpu_utils.h"
#include "tpu_impl_custom_ops.h"
#include "param_parser.h"

// type infer function
void type_infer_swapchannel(
    const global_tensor_spec_t *input,
    global_tensor_spec_t *output,
    const void *param) {
    output->dtype = input->dtype;
    output->dims = input->dims;
    memcpy(output->shape, input->shape, output->dims);
    output->elem_num = input->elem_num;
}

// global api function
void api_swapchannel_global(
    const global_tensor_spec_t *input,
    global_tensor_spec_t *output,
    const void *param) {
    PARSE_PARAM(swapchannel, sc_param, param);
    tpu_impl_swapchannel_global(
        input->addr,
        output->addr,
        input->shape,
        sc_param.order,
        tpu_type_convert(input->dtype));
}
```

### 5. 后端算子注册

在文件 `${TPUC_ROOT}/customlayer/register_ops.cmake` 添加如下代码，可用于注册后端算子：

```c
register_custom_op(swapchannel)
```

完成后，可参考《TpuLang自定义算子添加》小节进行动态库编译与安装。

### 6. 前端准备

在文件 `${TPUC_ROOT}/customlayer/python/my_tpulang_layer.py` 中调用TpuLang接口构建自定义算子swapChannel， 它只有一个输入和一个输出，且有一个属性order，是一个长度为3的整数列表：

```python
import transform.TpuLang as tpul

class swapChannel:
    @staticmethod
    def native(data):
        return data[:, [2, 1, 0], :, :]
    @staticmethod
    def tpulang(inputs, dtype="float32"):
        def shape_func(tensors_in:list):
            return [tensors_in[0].shape]
        params = {"order": [2, 1, 0]}
        outs = tpul.custom(
            tensors_in=inputs,
            shape_func=shape_func,
            # op_name should be consistent with the backend
            op_name="swapchannel",
            params=params,
            out_dtypes=[dtype])
        return outs
```

在文件 `${TPUC_ROOT}/customlayer/test_if/unittest/test_swapchannel.py` 中, 对自定义的swapChannel算子进行单元测试：

```python
import numpy as np
import unittest
from tpulang_custom_test_base import TestTPULangCustom
import transform.TpuLang as tpul
import my_tpulang_layer

class TestSwapChannel(TestTPULangCustom):
    def _test(self, dtype):
        shape = [4, 32, 36, 36]
        self.data_in = np.random.random(shape).astype(dtype)
        x = tpul.Tensor(name="in", dtype=dtype, shape=shape, data=self.data_in)
        y = my_tpulang_layer.swapChannel.tpulang(inputs=[x],
              dtype=dtype)[0]
        self.compile('SwapChannel', [x], [y], dtype)
    def test_fp32(self):
        self._test('float32')
    def test_fp16(self):
        self._test('float16')

if __name__ == '__main__':
    unittest.main()
```

## Caffe示例

本小节提供了Caffe中 absadd 和 ceiladd 自定义算子的应用示例。

### 1. 定义 Caffe 自定义算子

absadd 和 ceiladd 在 `$TPUC_ROOT/customlayer/python/my_caffe_layer.py` 中的定义如下：

```python
import caffe
import numpy as np

# Define the custom layer
class AbsAdd(caffe.Layer):

    def setup(self, bottom, top):
        params = eval(self.param_str)
        # define attributes here
        self.b_val = params['b_val']

    def reshape(self, bottom, top):
        top[0].reshape(*bottom[0].data.shape)

    def forward(self, bottom, top):
        top[0].data[...] = np.abs(np.copy(bottom[0].data)) + self.b_val

    def backward(self, top, propagate_down, bottom):
        pass

class CeilAdd(caffe.Layer):

    def setup(self, bottom, top):
        params = eval(self.param_str)
        # define attributes here
        self.b_val = params['b_val']

    def reshape(self, bottom, top):
        top[0].reshape(*bottom[0].data.shape)

    def forward(self, bottom, top):
        top[0].data[...] = np.ceil(np.copy(bottom[0].data)) + self.b_val

    def backward(self, top, propagate_down, bottom):
        pass
```

Caffe prototxt 中相应算子的表达如下：

```text
layer {
  name: "myabsadd"
  type: "Python"
  bottom: "input0_bn"
  top: "myabsadd"
  python_param {
    module: "my_caffe_layer"
    layer: "AbsAdd"
    param_str: "{ 'b_val': 1.2}"
  }
}

layer {
  name: "myceiladd"
  type: "Python"
  bottom: "input1_bn"
  top: "myceiladd"
  python_param {
    module: "my_caffe_layer"
    layer: "CeilAdd"
    param_str: "{ 'b_val': 1.5}"
  }
}
```

### 2. 实现算子前端转换函数

在 `$TPUC_ROOT/customlayer/python/my_converter.py` 中的 MyCaffeConverter 类里定义一个 convert_python_op 函数，代码如下：

```python
def convert_python_op(self, layer):
    assert (self.layerType(layer) == "Python")
    in_op = self.getOperand(layer.bottom[0])
    p = layer.python_param

    dict_attr = dict(eval(p.param_str))
    params = dict_attr_convert(dict_attr)

    # p.layer.lower() to keep the consistency with the backend op name
    attrs = {"name": p.layer.lower(), "params": params, 'loc': self.get_loc(layer.top[0])}

    # The output shape compute based on reshape function in my_caffe_layer
    out_shape = self.getShape(layer.top[0])
    outs = top.CustomOp([self.mlir.get_tensor_type(out_shape)], [in_op],
                        **attrs,
                        ip=self.mlir.insert_point).output
    # add the op result to self.operands
    self.addOperand(layer.top[0], outs[0])
```

### 3. Caffe前端转换

通过调用 my_converter.py 接口完成对 `$TPUC_ROOT/customlayer/test` 目录下的 my_model.prototxt, my_model.caffemodel Caffe模型进行转换 （该Caffe模型中包含了absadd与ceiladd算子），命令如下：

```shell
my_converter.py \
--model_name caffe_test_net \
--model_def $TPUC_ROOT/customlayer/test/my_model.prototxt \
--model_data $TPUC_ROOT/customlayer/test/my_model.caffemodel \
--input_shapes [[1,3,14,14],[1,3,24,26]] \
--mlir caffe_test_net.mlir
```

通过以上步骤可获得caffe_test_net.mlir的Top层mlir文件，后续的模型部署过程请参考 "用户接口" 章节。

### 4. 后端算子与接口实现

absadd 与 ceiladd 的实现部分和 swapchannel 算子相似，可在 `$TPUC_ROOT/customlayer/include` 和  `$TPUC_ROOT/customlayer/src` 目录下找到相应代码。

# 自定义AP（application processor）算子添加流程

## TpuLang自定义AP算子添加

### 1. 加载tpu-mlir
与TPU自定义算子时加载tpu-mlir一致。

### 2. 编写AP算子实现
假定当前处于 $TPUC_ROOT/customlayer 路径下，在./include/custom_ap/ap_impl_{op_name}.h 头文件中，声明一个继承ap_layer类的自定义派生类layer（其中"forward()"声明具体实现方法，"shape_infer()"声明推理前后张量形状变化方法，"dtype_infer()"声明推理前后数据类型变化方法，"get_param()"声明参数解析方法）。并且在./ap_src 目录下添加ap_impl_{op_name}.cpp，在其中实现相应的函数，定义新的成员变量，重写其中的成员函数。

### 3. 注册自定义算子

a. 在 ap_impl_{op_name}.cpp 中添加算子的名字以注册自定义算子：

```c++
REGISTER_APLAYER_CLASS(AP_CUSTOM, {op_name});
```

b. 并在./customlayer/include/customap_common.h中的枚举类型 `AP_CUSTOM_LAYER_TYPE_T`中定义成员 AP_CUSTOM_{OP_NAME}，其中OP_NAME为大写。

```c++
typedef enum {
  AP_CUSTOM                                 = 10001,
  AP_CUSTOM_TOPK                            = 10002,
  AP_CUSTOM_XXXX                            = 10003,
  AP_CUSTOM_LAYER_NUM                          ,
  AP_CUSTOM_LAYER_UNKNOW = AP_CUSTOM_LAYER_NUM,
} AP_CUSTOM_LAYER_TYPE_T;
```

c. 在customlayer/ap_src/ap_layer.cpp中定义实例化方法

```c++
bmap::ap_layer* create{OP_NAME}Layer() {
  return new bmap::ap_{op_name}layer();
}

void registerFactoryFunctions() {
  getFactoryMap()[std::string("{OP_NAME}")] = createTopkLayer;
  // Register other class creators
  // ...
}
```

### 4. 编译器补丁
有时候，需要对编译器进行修改，以对不同的自定义算子在不同参数下的编译行为进行控制，这时候就需要添加一些补丁。当前已支持以下补丁函数(在文件夹 ./plugin中定义)：

a. （必选）需要自行实现算子参数解析函数，用于获取算子所需的关键参数，重写自定义layer的get_param()方法：

```c++
int ap_mylayer::get_param(void *param, int param_size);
```

b. （必选）推理函数，即算子的C++实现。重写自定义layer的forward()方法：

```c++
int ap_mylayer::forward(void *raw_param, int param_size);
```

c. （可选）形状推断函数。此补丁函数用于编译器形状推断，若不实现，默认只有一个输入一个输出，且输出形状跟输入形状相同。补丁函数形式如下：

```c++
int ap_mylayer::shepe_infer(void *param, int param_size,
                            const vector<vector<int>> &input_shapes,
                            vector<vector<int>> &output_shapes);
```

其中，input_shapes/output_shapes为输入/出张量形状的数组，input_dims/output_dims为输入/出张量维度的数组。

### 5. 编译并安装动态库
先初始化环境：

```shell
source $TPUC_ROOT/customlayer/envsetup.sh
```

然后需要完成补丁的编译（得到 `libplugin_custom.so`）：

```shell
rebuild_custom_plugin
```

根据处理器架构编译自定义算子库文件（在目录build_ap下得到 `libcustomapop.so`），需要特别注意的是，编译自定义AP算子的环境要与bmodel运行环境中的glic版本兼容，命令如下：

a. x86架构

```shell
rebuild_custom_apop_x86
```

b. arm架构

```shell
rebuild_custom_apop_aarch64
```

至此我们完成了自定义AP算子后端部分的工作。

### 6. 利用TpuLang构建自定义AP算子
关于TpuLang的使用方式请参考TpuLang接口章节。

TpuLang中提供了 `TpuLang.custom` 接口可以同样用于自定义AP算子，使用方法与自定义Tpu算子基本一致，区别在定义"TpuLang.custom"对象时，"op_name"参数要以"ap."开头字段作为区分，例如"ap.topk"：

```python
class xxx:
  @staticmethod
  def native(...):
      ...
      return ...
  @staticmethod
  def tpulang(inputs, ...):
      def shape_func(tensors_in:list, ...):
          ...
          return ...
      params = dict(...)
      outputs = tpul.custom(
          tensors_in=inputs,
          shape_func=shape_func,
          op_name="ap.topk",
          params=params,
          out_dtypes=...)
      return outputs
```

### 7. 上卡测试
当网络中存在自定义AP算子时，bmodel需要包含算子信息，使用命令将libcustomapop.so写入bmodel文件，所有主机处理器架构均使用：

```shell
tpu_model --custom_ap_update xxx.bmodel libcustomapop.so
```

注：需要特别注意的是，编译自定义AP算子的环境要与bmodel运行环境中的glibc版本兼容。

## 自定义AP算子示例
本节内容假定已经完成了tpu-mlir发布包加载。

### TpuLang示例
本小节提供了一个swapchanel算子实现与通过TpuLang接口应用的样例。

#### 1. 自定义算子派生类
其中，这里的字段order对应前端的属性order 。

在{TPUC_ROOT}/customlayer/ap_src/ap_impl_{op_name}.cpp 的自定义类中定义成员变量：

```c++
private:
  int axis_;
  int K_;
```

在{TPUC_ROOT}/customlayer/ap_src/ap_impl_{op_name}.cpp 的自定义类中重写接口 `get_param()`。值得注意的是，从编译器传递到后端的是一个 custom_param_t 的数组A，它的第一个元素是保留的，从第二个元素开始，每个元素对应前端的一个属性：

```c++
int ap_topklayer::get_param(void *param, int param_size) {
  axis_ = ((custom_param_t *)param)[1].int_t;
  K_ = ((custom_param_t *)param)[2].int_t;
  return 0;
}
```

在{TPUC_ROOT}/customlayer/ap_src/ap_impl_{op_name}.cpp 的自定义类中重写接口 `shape_infer()`：

```c++
int ap_topklayer::shepe_infer(const vector<vector<int> > &input_shapes,
                                  vector<vector<int> > &output_shapes) {
  get_param(param, param_size);
  for (const auto& array : input_shapes) {
    output_shapes.emplace_back(array);
  }
  output_shapes[0][axis_] = std::min(K_, input_shapes[0][axis_]);
  return 0;
}
```

#### 2. AP算子实现
在{TPUC_ROOT}/customlayer/ap_src/ap_impl_{op_name}.cpp 的自定义类中重写接口 `forward()`：

```c++
int ap_topklayer::forward(void *raw_param, int param_size) {
  // implementation code right here
  return 0;
}
```

#### 3. AP算子注册

a. 在 ap_impl_{op_name}.cpp 中添加算子的名字以注册自定义算子：

```c++
REGISTER_APLAYER_CLASS(AP_CUSTOM_TOPK, ap_topk);
```

b. 并在./customlayer/include/customap_common.h中的枚举类型 `AP_CUSTOM_LAYER_TYPE_T`中定义成员 AP_CUSTOM_TOPK。

```c++
typedef enum {
  AP_CUSTOM                                 = 10001,
  AP_CUSTOM_TOPK                            = 10002,
  AP_CUSTOM_LAYER_NUM                          ,
  AP_CUSTOM_LAYER_UNKNOW = AP_CUSTOM_LAYER_NUM,
} AP_CUSTOM_LAYER_TYPE_T;
```

c. 在customlayer/ap_src/ap_layer.cpp中定义实例化方法

```c++
bmap::ap_layer* createTopkLayer() {
  return new bmap::ap_topklayer();
}

void registerFactoryFunctions() {
  getFactoryMap()[std::string("TOPK")] = createTopkLayer;
  // Register other class creators
  // ...
}
```

#### 4. 前端准备
调用TpuLang接口构建自定义AP算子的流程与TPU自定义算子基本一致，区别在定义"TpuLang.custom"对象时，"op_name"参数要以"ap."开头字段作为区分，例如"ap.topk"

# 用PPL写后端算子

PPL 是基于 C/C++ 语法扩展的、针对 TPU 编程的专用编程语言 (DSL)。开发者可以通过 PPL 在 TPU-MLIR 中编写后端算子。本章节以 `add_const_fp` 算子为例，介绍如何编写后端算子，以及 PPL 代码是如何被编译和使用的。

PPL 后端算子的实现位于 `tpu-mlir/lib/PplBackend/src` 目录；如果是发布包，则在 TPU-MLIR 发布包的 `PplBackend/src` 目录。有关如何编写 PPL 源码的详细信息，请参考 `tpu-mlir/third_party/ppl/doc` 中的文档。

## 如何编写和调用后端算子

### 第一步：实现三个源码文件
需要创建三个源码文件，一个是设备端的 `pl` 源码，一个是主机端的接口 `cpp` 源码， 另一个是主机端的tiling函数 `cpp` 源码。以 `add_const_fp` 为例，文件名分别为：

- `add_const_fp.pl`：实现 `add_const_f32` ， `add_const_f16` 及 `add_const_bf16` 等 kernel 接口。
- `add_const_fp_tile.cpp`：实现 `add_tiling` 函数以调用这些 kernel 接口。
- `add_const_fp_api.cpp`：实现 `api_add_const_fp_global` 函数以调用 `add_tiling` 接口。

**tiling.cpp文件示例**

```cpp
// 添加pl文件自动生成的头文件
#include "add_const_fp.h"
// 添加tpu-mlir数据类型及结构体头文件
#include "tpu_mlir/Backend/BM168x/Param.h"

// 需要用extern C来定义入口函数
extern "C" {
// 如果pl文件提供了多个算子，可以提前定义函数指针，这样可以减少一些重复代码
// 注意pl文件中的指针类型需要用gaddr_t定义
using KernelFunc = int (*)(gaddr_t, gaddr_t, float, int, int, int, int, int,
                           bool);
// 添加入口函数，输入参数由用户自定义
int add_tiling(gaddr_t ptr_dst, gaddr_t ptr_src, float rhs, int N, int C, int H,
               int W, bool relu, int dtype) {
  KernelFunc func;
  // 根据输入数据类型，选择合适的算子
  if (dtype == DTYPE_FP32) {
    func = add_const_f32;
  } else if (dtype == DTYPE_FP16) {
    func = add_const_f16;
  } else if (dtype == DTYPE_BFP16) {
    func = add_const_bf16;
  } else {
    assert(0 && "unsupported dtype");
  }

  // 计算block size，可以将block size对齐到EU_NUM，
  // 这样可以减少内存分配失败的次数，并且因为TPU上的内存大部分是按照EU_NUM对齐的，
  // 所以不会影响到内存分配
  int block_w = align_up(N * C * H * W, EU_NUM);
  int ret = -1;
  while (block_w > 1) {
    ret = func(ptr_dst, ptr_src, rhs, N, C, H, W, block_w, relu);
    if (ret == 0) {
      return 0;
    } else if (ret == PplLocalAddrAssignErr) {
      // 当错误类型为PplLocalAddrAssignErr时，说明block size太大，
      // local 内存放不下，需要减小block size
      block_w = align_up(block_w / 2, EU_NUM);
      continue;
    } else if (ret == PplL2AddrAssignErr) {
      // 当错误类型为PplL2AddrAssignErr时，说明block size太大，
      // L2 内存放不下，需要减小block size，本示例没有分配L2内存，
      // 因此不会出现这个错误
      assert(0);
    } else {
      // 其他错误，需要debug
      assert(0);
      return ret;
    }
  }
  return ret;
}
}
```

**注意事项**

- add_const_fp.h 头文件中包含了一些错误码和芯片相关的参数定义：
- pl 文件中的指针需要使用gaddr_t类型定义

| 参数名 | 说明 |
|--------|------|
| PplLocalAddrAssignErr | Local内存分配失败 |
| FileErr |  |
| LlvmFeErr |  |
| PplFeErr | AST转IR失败 |
| PplOpt1Err | 优化pass opt1失败 |
| PplOpt2Err | 优化pass opt2失败 |
| PplFinalErr | 优化pass final失败 |
| PplTransErr | 代码生成失败 |
| EnvErr | 环境变量异常 |
| PplL2AddrAssignErr | L2内存分配失败 |
| PplShapeInferErr | shape推导失败 |
| PplSetMemRefShapeErr |  |
| ToPplErr |  |
| PplTensorConvErr |  |
| PplDynBlockErr |  |

# 内置芯片参数

| 参数名   | 说明     |
|----------|----------|
| EU_NUM   | EU数量   |
| LANE_NUM | LANE数量 |

## 第二步：调用 Kernel 接口

在 `lib/Dialect/Tpu/Interfaces/BM1684X/AddConst.cpp` 的 `void tpu::AddConstOp::codegen_global_bm1684x()` 函数中，调用 `api_add_const_fp_global`，代码如下：

```cpp
BM168x::call_ppl_global_func("api_add_const_fp_global", &param,
                             sizeof(param), input_spec->data(),
                             output_spec->data());
```

如果该算子支持局部执行，则实现 `api_xxxxOp_local`，并使用 `BM168x::call_ppl_local_func` 进行调用。

```cpp
BM168x::call_ppl_local_func("api_xxxx_local", &spec, sizeof(spec),
                            &sec_info, input_spec->data(),
                            output_spec->data());
```

以上便完成了后端算子的实现。

# PPL 集成到 TPU-MLIR 的流程

1. 将 PPL 编译器精简后放入 `third_party/ppl` 目录，并更新 PPL 编译器，参考该目录下的 README.md 文件。
2. 在 `model_deploy.py` 中集成 PPL 源码编译，流程如图所示：

   PPL Workflow

# final.mlir 截断方式

`final.mlir` 作为 `codegen` 的输入文件，是模型在经过了所有硬件无关与硬件相关的优化后生成的最终中间表达（ `IR` ）。因为包含了硬件相关信息，结构相对于之前的 `IR` 要复杂的多。

而在进行模型适配时有时会出现 `Tpu` 层 `MLIR` 文件与 `bmodel` 的 `cmodel` 推理结果不一致的情况，为了快速定位到出问题的位置，除了使用 `bmodel_checker.py` 工具对每一层输出进行对比外，还可以手动对 `final.mlir` 文件进行截断，生成一个截断后的模型。

因此，本章主要会对 `final.mlir` 的结构进行剖析，并讲解如何基于 `final.mlir` 对模型进行截断以便于后续的问题定位。

* 建议使用 `IDE` ：VSCode。
* 建议使用插件：MLIR。

## `final.mlir` 结构介绍

`final.mlir` 中的单个算子组成部分如下：

注意：

* `value` 表示算子的输入/输出，为 `SSA` 形式
* out_num：表示输出的数量。如果是单输出算子，则不会显示 `:out_num`。
* 对于多输出算子的值，用户将按 `%value#in_index` 方式引用 （ `index` 从0开始）
* 每个输入/输出值都有对应的 `Tensor type`。
* 完整的 `Tensor type` 包含形状、数据类型和全局内存地址（ `Gmem addr` ）。

除了单算子外 `final.mlir` 中还存在着 `LayerGroup` 后生成的 `tpu.Group` 算子，其中包含了多个中间算子，这些算子均在 `Lmem` 上完成计算，由 `tpu.Group` 统一通过 `tpu.Load` 和 `tpu.Store` 控制输入数据加载和输出数据存储，所以中间算子的 `Tensor type` 并没有 `Gmem addr` ：

* `local_type` 指代不带有 `Gmem addr` 的 `Tensor type` 。
* 算子尾部的 `loc(#loc32)` 指代模型某层输出的 `location` ，即该输出的编号，可根据该编号在 `final.mlir` 文件尾部找到对应的输出名。
* `Yield` 表示 `tpu.Group` 的输出集合。

完整的 `final.mlir` 文件中存在的结构大致如下：

* 双层 `module` 中 包含了 `mainfunc` 和 `subfunc` ， `mainfunc` 和 `subfunc` 存在调用关系。
* mainfunc 中的 `arg0` 指代 `host` 端的输入，因此 `host_in_type` 不带有 `Gmem addr` 。
* 多输出的 `location` 会被添加在 `final.mlir` 文件的最尾端，并表述出与每个具体输出 `location` 间的包含关系，例如 `#loc950 = loc(fused[#loc2, #loc3])` 。

## `final.mlir` 截断流程

1. 修改 `subfunc` 。删减 `subfunc` 内部结构，并将返回值的 `value` 与对应 `type`：

2. 同步 `mainfunc` 中 `subfunc` 的调用方式（ `value` 与 `type` ）：

3. 检查 `bmodel` 是否修改成功。可首先通过执行 `codegen` 步骤看是否可以正常生成 `bmodel` (`<...>` 请替换为实际的文件或参数):

```shell
$ tpuc-opt <final.mlir> --codegen="model_file=<bmodel_file> embed_debug_info=<true/false> model_version=latest" -o /dev/null
```

当需要使用profile进行性能分析时， `embed_debug_info` 设置为 `true` 。

4. 使用 `model_tool` 检查该 `bmodel` 的输入输出信息是否符合预期：

```shell
$ model_tool --info <bmodel_file>
```

注意:

1. 截断时以算子为单位进行模型结构的删除，每个 `tpu.Group` 应当被看作是一个算子。

2. 仅修改函数返回值不对冗余的模型结构进行删除可能会造成输出结果错误的情况，该情况是由于每个激活的 `Gmem addr` 分配会根据激活的生命周期进行复用，一旦生命周期结束，将会被分配给下一个合适的激活，导致该地址上的数据被后续操作覆盖。

3. 需要确保 `tpu.Group` 的每个输出都有 `user` ，否则可能会出现 `codegen` 步骤报错的情况，如果不想输出 `tpu.Group` 的某个结果又不便将其完整删除，可以为没有user的输出添加一个无意义的 `tpu.Reshape` 算子，并配上相同的 `Gmem addr` 和 `location` ， 例如：

4. 对模型进行删减后可以更新 `module` 模块中的 `module.coeff_size` 信息以减少裁剪后生成的 `bmodel` 大小，公式如下：

$$
CoeffSize = NumElement_{weight} * DtypeBytes_{weight} + Addr_{weight} - CoeffAddr
$$

上述公式中的 `weight` 指代截断后 `final.mlir` 中最后一个 `top.Weight` 。 `neuron` （即激活）因为会对地址进行复用，因此不建议进行修改。

# MaskRCNN 大算子接口指南

## MaskRCNN 基础

两阶的 MaskRCNN 由两类组成:

- **3 个有权值模块**:  `backbone.pt` 和2个 `bbox/mask` 中间有权值层(按顺序命名为 `torch_bbox/mask.pt` ).
- **5 个动态无权值模块**:包括 `RPN head`, `bbox pooler`, `bbox head`, `mask pooler`, `mask head`.

因此,完整的MaskRCNN 可以通过以下过程表示:

- **bbox 检测头**: `backbone.pt` => `RPN head` => `bbox pooler` => `torch_bbox.pt` => `bbox head`.
- **mask 检测头**: `backbone.pt` => `RPN head` => `mask pooler` => `torch_mask.pt` => `mask head`.

### 模块快速分割方法

由于 MaskRCNN  拆分依赖原框架工程的兼容情况,  用户可能无法trace每部分,本章节中以 `mask head` 为无法trace的例子.

MaskRCNN 的两类模块分割点,  即再次进入有权值模块首层的接入点.

## MaskRCNN 大算子

由于基于细粒度操作的MaskRCNN部署, 操作动态IR的难度较高,因此提出了以下MaskRCNN 大算子解决方案:

**粗粒度**:

1. **内置 MaskRCNN 专属后端**:现在 mlir-backend 直接支持动态无权值模块, 目前包括 `RPN head`, `bbox head`, `bbox pooler` 和 `mask pooler`. 因此,大多数与前端推理图解析和优化相关的繁重工作得以节省, 如避免了大量动态形参推理或变种细粒度算子的支持.

2. **模型重建**:用户只需 4 个结构信息即可重建完整的 MaskRCNN:

 - **io_map**: 描述模块接口, 与MaskRCNN拓扑同构.定义为 `(目标模块索引, 操作数索引):(源模块索引: 操作数索引)`.
 - **config.yaml**: 用于存储MaskRCNN超参数的 YAML 文件,事先提供.
 - **BackBone**: 通常从顶部到 RPN,事先从原始 MaskRCNN 中拆分.
 - **有权值模块**: `bbox/mask` 中间有权值层,事先从原始 MaskRCNN 中拆分.

## 快速入门

在深入了解新的 MaskRCNN 特性之前,  请先了解新的 MaskRCNN yaml文件格式和单元测试.

### 准备您的 YAML

在 `regression/dataset/MaskRCNN/CONFIG_MaskRCNN.yaml` 中准备了一个默认的 YAML, 其结构如下:

 - **model_transform的编译参数**:重建 MaskRCNN 的结构信息.

   - **io_map**: 即定义 `(目标模块索引, 操作数索引):(源模块索引: 操作数索引)`,其中 -1 表示整体模型的顶层输入,-2 表示整体模型的顶层输出,0、1、2... 表示 MaskRCNN 模块的 ID.
       例如,{(0,0):(-1,0),(1,0):(0,0),(-2,0):(1,0)},表示 模块[0] 的 input[0] 来自整体模型的 input[0], 模块[1] 的 input[0] 来自 模块[0] 的 output[0],整体模型的 output[0] 来自 模块[1] 的 output[0].
   - **maskrcnn_output_num**: 整体 MaskRCNN 的最终输出操作数的数量.
   - **maskrcnn_structure**: 描述 MaskRCNN 模块顺序.1 表示 torch.pt 模型,0 表示 PPLOp.例如,[1,0,1] 表示第一个模块是  torch 模型,第二个模块是  PPLOp,第三个模块是  torch 模型.
   - **maskrcnn_ppl_op**:  后端已经用PPL实现的 MaskRCNN 算子名称.
   - **numPPLOp_InWithoutWeight_MaskRCNN**: 每个 PPLOp 的输入操作数；请不要计入权重.

 - **MaskRCNN 的超参数**: 必要 MaskRCNN 配置参数, 来自源码 MaskRCNN 框架.

### 模块单元测试

`--case` 提供单试模块的选择,当前支持 4 个动态无权值模块测试: `RPN head`, `bbox pooler`, `bbox head`, `mask pooler`.

更多指导请参见 `test_MaskRCNN.py`.

```bash
$ test_MaskRCNN.py --case MaskRCNN_Utest_RPNGetBboxes --debug
```

## 新前端接口API

### [步骤 1] 运行 model_transform

用于将 MaskRCNN 转换为 MLIR 文件.

 - **跳过推理**:请注意, 在此步骤中不需要形参推理或计算推理, 无需输入/比较参考的 数据 `.npz` 文件,但需要事先提供 `config.yaml`.
 - **跳过预处理**:请注意, 在此步骤中, 默认无预处理.
 - **新的启动符**: 注意 `enable_maskrcnn`.

```bash
$ model_transform.py \
    --model_def  backbone.pt \
    --model_extern torch_bbox.pt,torch_mask.pt \
    --model_name MaskRCNN \
    --input_shapes [[1,3,800,1216],[1,1,4741,4],[1,1,20000,4],[1,1,20000,4],[1,1,100,4]] \
    --mlir MaskRCNN.mlir \
    --enable_maskrcnn \
    --path_yaml regression/dataset/MaskRCNN/CONFIG_MaskRCNN.yaml
```

### [步骤 2] 生成输入数据

#### MaskRCNN 输入格式

MaskRCNN 大算子框架需要 5 个输入:

 - **预处理图片**:经过预处理的图片.
 - **max_shape_RPN/max_shape_GetBboxB**:如果输入图片的形参为 `S1`,原始形参为 `S0`,则最大形参为 `int(S0 * S1 / S0)`,并扩展为常量权重张量.
 - **scale_factor_GetBboxB/scale_factor_MaskPoolerB**:如果输入图片的形参为 `S1`,原始形参为 `S0`,则缩放因子为 `float(S1 / S0)`,并扩展为常量权重张量.

#### 输入格式化工具

在 `tpu-mlir/python/tools/tool_maskrcnn.py` 提供了一个格式化输入数据工具,以帮助您生成满足上述要求的数据.

- **跳过预处理**: 输入图像应为经过预处理的图像，因为 MaskRCNN 的预处理过程通常很复杂，并依赖于原框架中的特定函数.

除了 `path_yaml`，还需要指定三个参数:

 - **path_input_image**: 经过预处理的图像，保存为 npz 格式.
 - **basic_max_shape_inverse**:预处理后的高度和宽度.
 - **basic_scalar_factor**: 正是上述的 `float(S1 / S0)`, `basic_max_shape_inverse` 除以原始形状重新排序后的 `height, width`.

结果数据将存储在与 `path_input_image` 相同的路径中，但后缀为 `SuperiorMaskRCNNInputPreprocessed`.

请查看 `tool_maskrcnn.py` 以获取更多指导.

```bash
$ tool_maskrcnn.py \
  --path_yaml              ./regression/dataset/MaskRCNN/CONFIG_MaskRCNN.yaml \
  --path_input_image       Superior_IMG_BackBone.npz \
  --basic_max_shape_inverse 1216,800 \
  --basic_scalar_factor     1.8734375,1.8735363 \
  --debug
```

### [步骤 3] 运行 model_deploy

- **跳过推理**: 此处跳过量化比较和仿真比较。

- **强制参数**: `--quantize` 模式被强制为 `F32`, `--processor` 被强制为 `BM1684X`

 - **新的启动符**: 注意 `enable_maskrcnn`.

```bash
$ model_deploy.py \
    --mlir MaskRCNN.mlir \
    --quantize F32 \
    --processor BM1684X \
    --model MaskRCNN.bmodel \
    --debug \
    --enable_maskrcnn
```

# IO_MAP 指南

手动生成 io_map 分为两个步骤:

 - **模块接口的完备定义**: 准确收集输入和输出的操作数和形参,以及模块连接.
 - **创建相应的 io_map**: 应准确且唯一地重建完整的 MaskRCNN.

## [步骤 1] 描述模块接口

如开始所述, 完整的 MaskRCNN 被截断为多个模块.

请为每个模块描述以下信息:

- **输入**:输入操作数或常量权重

 * **形参**:以 4 维shape表示.
 * **数据类型**:仅支持 fp32 或 int32.
 * **连接**: 每个输入找出其来源的上层模块(可能不是上一个相邻模块), 和上层模块相应输出的操作序数.

请注意, -1 表示完整 MaskRCNN 的输入, 而 -2 表示完整模型的输出

**[-1] Top_In**

| 输入编号 | 名称                | 形参                  | 数据类型 | 连接信息[源模块-操作数序号] |
|----------|---------------------|-----------------------|----------|----------------------------|
| 输入 0)  | 'img.1'             | [1,3,800,1216]        | FP32     | from_[TOP_IN]Input-0       |
| 输入 1)  | 'max_shape_RPN'     | [bs,1,max_filter_num,4] | int32   |                            |
| 输入 2)  | 'max_shape_GetBboxB'| [1,bs*20000,1,4]      | int32   |                            |
| 输入 3)  | 'scale_factor_GetBboxB' | [1,bs,20000,4]    | FP32     |                            |
| 输入 4)  | 'scale_factor_MaskPooler' | [bs,1,roi_slice,4] | FP32     |                            |

**[Torch] SubBlock-0: BackBone.pt**

| IO类型   | 名称  | 形参           | 数据类型 | 连接信息[源模块-操作数序号] |
|----------|-------|----------------|----------|----------------------------|
| 输入 0)  | 'img.1' | [1,3,800,1216] | FP32     | from_[TOP_IN]Input-0       |
| 输出 0)  | '11'  | [1,256,200,304] | FP32    |                            |
| 输出 1)  | '12'  | [1,256,100,152] | FP32    |                            |
| 输出 2)  | '13'  | [1,256,50,76]  | FP32    |                            |
| 输出 3)  | '16'  | [1,256,25,38]  | FP32    |                            |
| 输出 4)  | '15'  | [1,256,13,19]  | FP32    |                            |
| 输出 5)  | '18'  | [1,3,200,304]  | FP32    |                            |
| 输出 6)  | '19'  | [1,3,100,152]  | FP32    |                            |
| 输出 7)  | '20'  | [1,3,50,76]    | FP32    |                            |
| 输出 8)  | '21'  | [1,3,25,38]    | FP32    |                            |
| 输出 9)  | '22'  | [1,3,3,19]     | FP32    |                            |
| 输出 10) | '23'  | [1, 2,200,304] | FP32    |                            |
| 输出 11) | '24'  | [1,12,100,152] | FP32    |                            |
| 输出 12) | '25'  | [1,12,50,76]   | FP32    |                            |
| 输出 13) | '26'  | [1,12,25,38]   | FP32    |                            |
| 输出 14) | '27'  | [1,12,13,19]   | FP32    |                            |

# [PPL] SubBlock-1: ppl::RPN_get_bboxes

| IO类型 | 名称 | 形参 | 连接信息[源模块-操作数序号] |
|--------|------|------|----------------------------|
| 输出 | 0 result_list | [bs,1,max_per_img,num_levels] | |
| 输入 | 1 cls_scores_0 | [bs,3,200,304] | [Torch][SubBlock-0]Output 5) |
| 输入 | 2 cls_scores_1 | [bs,3,100,152] | [Torch][SubBlock-0]Output 6) |
| 输入 | 3 cls_scores_2 | [bs,3,50,76] | [Torch][SubBlock-0]Output 7) |
| 输入 | 4 cls_scores_3 | [bs,3,25,38] | [Torch][SubBlock-0]Output 8) |
| 输入 | 5 cls_scores_4 | [bs,3,13,19] | [Torch][SubBlock-0]Output 9) |
| 输入 | 6 bbox_preds_0 | [bs,12,200,304] | [Torch][SubBlock-0]Output 10) |
| 输入 | 7 bbox_preds_1 | [bs,12,100,152] | [Torch][SubBlock-0]Output 11) |
| 输入 | 8 bbox_preds_2 | [bs,12,50,76] | [Torch][SubBlock-0]Output 12) |
| 输入 | 9 bbox_preds_3 | [bs,12,25,38] | [Torch][SubBlock-0]Output 13) |
| 输入 | 10 bbox_preds_4 | [bs,12,13,19] | [Torch][SubBlock-0]Output 14) |
| 输入 | 11 max_shape | [bs,1,max_filter_num,4] | [TOP_IN]Input-1 |
| 输入 | 12 mlvl_anchors_0 | [bs,1,3*200*304,4] | [mlir][Weight] |
| 输入 | 13 mlvl_anchors_1 | [bs,1,3*100*152,4] | [mlir][Weight] |
| 输入 | 14 mlvl_anchors_2 | [bs,1,3*50*76,4] | [mlir][Weight] |
| 输入 | 15 mlvl_anchors_3 | [bs,1,3*25*38,4] | [mlir][Weight] |
| 输入 | 16 mlvl_anchors_4 | [bs,1,3*13*19,4] | [mlir][Weight] |

# [PPL] SubBlock-2: ppl::Bbox_Pooler

| IO类型 | 名称 | 形参 | 连接信息[源模块-操作数序号] |
|--------|------|------|----------------------------|
| 输出 | 0 result_res | [bs*250,256,PH,PW] | |
| 输出 | 1 result_rois | [bs,max_per_img,1,roi_len] | |
| 输入 | 2 feat0 | [bs,256,H,W] | [Torch][SubBlock-0]Output 0) |
| 输入 | 3 feat1 | [bs,256,H/2,W/2] | [Torch][SubBlock-0]Output 1) |
| 输入 | 4 feat2 | [bs,256,H/4,W/4] | [Torch][SubBlock-0]Output 2) |
| 输入 | 5 feat3 | [bs,256,H/8,W/8] | [Torch][SubBlock-0]Output 3) |
| 输入 | 6 rois_multi_batch | [bs,roi_slice,1,roi_len] | [PPL][SubBlock-1]result_list |

# [Torch] SubBlock-3: torch_bbox.pt

| Batch | IO类型 | 名称 | 形参 | 数据类型 | 连接信息[源模块-操作数序号] |
|-------|--------|------|------|----------|----------------------------|
| Batch-1 | 输入 | 0 | [250,256,7,7] | FP32 | [PPL][SubBlock-2]result_res |
| | 输出 | 0 | [250,81] | FP32 | |
| | 输出 | 1 | [250,320] | FP32 | |
| Batch-4 | 输入 | 0 | [400,256,14,14] | FP32 | |
| | 输出 | 0 | [400,80,28,28] | FP32 | |

# [PPL] SubBlock-4: ppl::get_bboxes_B

| Batch | IO类型 | 名称 | 形参 | 连接信息[源模块-操作数序号] |
|-------|--------|------|------|----------------------------|
| Batch 1 | 输出 | result_det_bboxes | [bs,1,100,5] | |
| | 输出 | result_det_labels | [bs,1,100,1] | |
| | 输入 | rois | [1,bs*250,1,5] | [PPL][SubBlock-2]1-result_rois |
| | 输入 | bbox_pred | [1,bs*250,1,320] | [Torch][SubBlock-3]Output 1 |
| | 输入 | cls_score | [1,bs*250,1,81] | [Torch][SubBlock-3]Output 0 |
| | 输入 | max_val | [1,bs*20000,1,4] | [TOP_IN]Input-2 |
| | 输入 | scale_factor | [1,bs,20000,4] | [TOP_IN]Input-3 |

# [PPL] SubBlock-5: ppl::Mask_Pooler

| IO类型 | 序号 | 名称 | 形参 | 连接信息[源模块-操作数序号] |
|--------|------|------|------|----------------------------|
| 输出 | 0 | result_res | [roi_num,C,PH,PW] | |
| 输入 | 1 | x0 | [bs,256,H,W] | [Torch][SubBlock-0]Output 0 |
| 输入 | 2 | x1 | [bs,C,H/2,W/2] | [Torch][SubBlock-0]Output 1 |
| 输入 | 3 | x2 | [bs,C,H/4,W/4] | [Torch][SubBlock-0]Output 2 |
| 输入 | 4 | x3 | [bs,C,H/8,W/8] | [Torch][SubBlock-0]Output 3 |
| 输入 | 5 | det_bboxes_multi_batch | [bs,1,roi_slice,roi_len] | [PPL][SubBlock-4]0-result_det_bboxes |
| 输入 | 6 | det_labels_multi_batch | [bs,1,roi_slice,1] | [PPL][SubBlock-4]1-result_det_labels |
| 输入 | 7 | scale_factor | [bs,1,roi_slice,4] | [TOP_IN]Input-4 |

# [Torch] SubBlock-6: torch_mask.pt

| Batch | IO类型 | 序号 | 名称 | 形参 | 数据类型 | 连接信息[源模块-操作数序号] |
|-------|--------|------|------|------|----------|----------------------------|
| Batch 1 | 输入 | 0 | input.2 | [100,256,14,14] | FP32 | [PPL][SubBlock-5]0-result_res |
| | 输出 | 0 | 75 | [100,80,28,28] | FP32 | |
| Batch 4 | 输入 | 0 | input.2 | [400,256,14,14] | FP32 | |
| | 输出 | 0 | 75 | [400,80,28,28] | FP32 | |

# [-2] TOP_OUT

| IO类型 | 序号 | 形参 | 数据类型 | 连接信息[源模块-操作数序号] |
|--------|------|------|----------|----------------------------|
| 输出 | 0 | [bs,1,100,5] | FP32 | [PPL][SubBlock-5]0-result_det_bboxes |
| 输出 | 1 | [bs,1,100,1] | FP32 | [PPL][SubBlock-5]1-result_det_labels |
| 输出 | 2 | [100,80,28,28] | FP32 | [Torch][SubBlock-6] |

## 描述 IO_MAP

以以下格式重新组织上述模块接口:

- **模块名称**:一个模块的名称和序号.
- **上层输入**:每个输入找出其来源的上层模块(可能不是上一个相邻模块), 和上层模块相应输出的操作序数.
- **连接数**:记录输入操作数的总数.
- **映射**: (目标模块索引, 操作数索引):(源模块索引: 操作数索引)

请注意, -1 表示完整 MaskRCNN 的输入, 而 -2 表示完整模型的输出.

### [0]TORCH_0-rpn

- **上层输入**:
  * ← [-1]TOP_IN[0]
- **连接数**: 1
- **映射**:
  * (0,0):(-1,0)

### [1]PPL-RPNGetBboxes

- **上层输入**:
  * ← [0]TORCH_0-rpn[5:15]
  * ← [-1]TOP_IN[1]
- **连接数**: 10
- **映射**:
  * (1,0):(0,5)
  * (1,1):(0,6)
  * (1,2):(0,7)
  * (1,3):(0,8)
  * (1,4):(0,9)
  * (1,5):(0,10)
  * (1,6):(0,11)
  * (1,7):(0,12)
  * (1,8):(0,13)
  * (1,9):(0,14)
  * (1,10):(-1,1)

### [2]PPL-Bbox_Pooler

- **上层输入**:
  * ← [0]TORCH_0-rpn[0:4]
  * ← [1]PPL-RPNGetBboxes[0]
- **连接数**: 4 + 1
- **映射**:
  * (2,0):(0,0)
  * (2,1):(0,1)
  * (2,2):(0,2)
  * (2,3):(0,3)
  * (2,4):(1,0)

### [3]Torch-2

- **上层输入**:
  * ← [2]PPL-Bbox_Pooler
- **连接数**: 1
- **映射**:
  * (3,0):(2,0)

### [4]PPL-GetBboxB

- **上层输入**:
  * ← [2]PPL-Bbox_Pooler[1]
  * ← [3]Torch-2[0:2]_inverse
  * ← [-1]TOP_IN[2:4]
- **连接数**: 1 + 2 (逆向) + 2
- **映射**:
  * (4,0):(2,1)
  * (4,1):(3,1)
  * (4,2):(3,0)
  * (4,3):(-1,2)
  * (4,4):(-1,3)

### [5]ppl-MaskPooler

- **上层输入**:
  * ← [0]Torch-RPN[0:4]
  * ← [4]PPL-GetBboxB[0:2]
  * ← [-1]TOP_IN[4]
- **连接数**: 4 + 2
- **映射**:
  * (5,0):(0,0)
  * (5,1):(0,1)
  * (5,2):(0,2)
  * (5,3):(0,3)
  * (5,4):(4,0)
  * (5,5):(4,1)
  * (5,6):(-1,4)

### [6]Torch-3

- **上层输入**:
  * ← [5]ppl-MaskPooler
- **连接数**: 1
- **映射**:
  * (6,0):(5,0)

### [-2]TOP_OUT

- **上层输入**:
  * ← [4]PPL-GetBboxB[0:2]
  * ← [6]Torch-3
- **连接数**: 2 + 1
- **映射**:
  * (-2,0):(4,0)
  * (-2,1):(4,1)
  * (-2,2):(6,0)

## IO_MAP参数整理

收集上述所有映射信息后,生成 io_map 字典:

- **io_map**: {(0,0):(-1,0),(1,0):(0,5),(1,1):(0,6),(1,2):(0,7),(1,3):(0,8),(1,4):(0,9),(1,5):(0,10),(1,6):(0,11),(1,7):(0,12),(1,8):(0,13),(1,9):(0,14),(1,10):(-1,1),(2,0):(0,0),(2,1):(0,1),(2,2):(0,2),(2,3):(0,3),(2,4):(1,0),(3,0):(2,0),(4,0):(2,1),(4,1):(3,1),(4,2):(3,0),(4,3):(-1,2),(4,4):(-1,3),(5,0):(0,0),(5,1):(0,1),(5,2):(0,2),(5,3):(0,3),(5,4):(4,0),(5,5):(4,1),(5,6):(-1,4),(6,0):(5,0),(-2,0):(4,0),(-2,1):(4,1),(-2,2):(6,0)}

现直接在 `model_transform` 中使用它, 编译过程中将生成一个 `revised_io_map_${model_name}.svg` 图片,以帮助您检查和可视化 io_map.

## mAP 推理

转换和部署这样的粗粒度 MaskRCNN 进行到这里还不够, 要在 COCO2017 数据集上mAP推理, 需要仔细地接入原始推理框架.

有关更多推断细节,请参阅我们的 model-zoo 项目.

# LLMC使用指南

## TPU-MLIR weight-only 量化

TPU-MLIR中支持对大模型进行weight-only仅权重量化,采用的量化算法是RTN(round to nearest)算法,量化粒度为per-channel或者per-group。具体的量化配置如下:

| bit | symmetric | granularity | group_size |
|-----|-----------|-------------|------------|
| 4 | False | per-channel or per-group | -1 or 64(default) |
| 8 | True | per-channel | -1 |

RTN量化算法简洁高效,但也面临一些不足,对于一些要求模型精度比较高的场景,RTN算法量化的模型可能无法满足精度需求,此时需要借助大模型量化工具llmc_tpu来进一步提升精度。

# llmc_tpu

本项目源自 [ModelTC/llmc](https://github.com/ModelTC/llmc)。ModelTC/llmc是非常优秀的项目，专为压缩LLM设计，利用最先进的压缩算法提高效率并减少模型体积，同时不影响预测精度。如果要深入了解llmc项目，请转到 [https://github.com/ModelTC/llmc](https://github.com/ModelTC/llmc)。

本项目是基于 `ModelTC/llmc` 进行一些定制化修改，用于支持Sophgo处理器。

## 环境准备

1. **下载本项目**

```shell
git clone git@github.com:sophgo/llmc-tpu.git
```

2. **准备您需要量化的LLM或者VLM模型，放到`llmc-tpu`的同级目录**

比如huggingface上下载 `Qwen2-VL-2B-Instruct`，如下：

```shell
git lfs install
git clone git@hf.co:Qwen/Qwen2-VL-2B-Instruct
```

3. **下载Docker并建立Docker容器**

pull docker images

```shell
docker pull registry.cn-hangzhou.aliyuncs.com/yongyang/llmcompression:pure-latest
```

create container. llmc_test is just a name, and you can set your own name

```shell
docker run --privileged --name llmc_test -it --shm-size 64G --gpus all -v $PWD:/workspace  registry.cn-hangzhou.aliyuncs.com/yongyang/llmcompression:pure-latest
```

4. **进入`llmc-tpu`，安装依赖包**

注意现在已经在docker容器中

```shell
cd /workspace/llmc-tpu
pip3 install -r requirements.txt
```

## tpu 目录

```
├── README.md
├── data
│   ├──LLM
│      ├──cali                              #校准数据集
│      ├──eval                              #推理数据集
│   ├──VLM
│      ├──cali
│      ├──eval
├── config
│   ├──LLM                                  #LLM量化config
│      ├── Awq.yml                              #Awq config
│      ├── GPTQ.yml                             #GPTQ config
│   ├──VLM                                  #VLM量化config
│      ├── Awq.yml                              #Awq config
├── example.yml                             #量化参数参考例子
├── llm_quant.py                            #量化主程序
├── run_llmc.sh                             #量化运行脚本
```

## 操作步骤

### 【阶段一】准备校准数据集和测试数据集

* 注意点1: **校准数据集** 可以是开源数据集或者业务数据集，如果模型经过下游业务数据集微调，则需要选用业务数据集做校准
* 注意点2: **测试数据集** 主要用来评估当前模型的精度表现，包括预训练(pretrain)模型或者量化(fake_quant)模型的精度

可以选择用开源数据集，也可以选择用业务数据集。

#### 开源数据集

如果有业务数据集最好，没有的话可以用开源数据集，如下：

| 模型类型 | 量化算法 | 校准数据集(开源) | 测试数据集(开源) |
|----------|----------|------------------|------------------|
| LLM | Awq | pileval | wikitext2 |
| LLM | GPTQ | wikitext2 | wikitext2 |
| VLM | Awq | MME | MME |

校准数据集的选取与模型类型和量化算法相关，例如如果量化的是LLM模型，使用的是Awq算法，通常推荐使用pileval数据集作为校准集。针对这些开源数据集本文档提供了对应的下载命令，可以运行下载相应的数据集。具体操作如下：可打开llmc-tpu/tools文件，里面对应有download_calib_dataset.py和download_eval_dataset.py两个python脚本，分别用于下载校准集和测试集。

如果是VLM模型，建议使用Awq算法，下载数据集命令如下：

```shell
cd /workspace/llmc-tpu
```

* 校准数据集

```shell
python3 tools/download_calib_dataset.py --dataset_name MME --save_path tpu/data/VLM/cali
```

* 测试数据集

```shell
python3 tools/download_eval_dataset.py --dataset_name MME --save_path tpu/data/VLM/eval
```

如果是LLM模型，建议用Awq算法，下载数据集命令如下：

```shell
cd /workspace/llmc-tpu
```

* 校准数据集

```shell
python3 tools/download_calib_dataset.py --dataset_name pileval --save_path tpu/data/LLM/cali
```

* 测试数据集

```shell
python3 tools/download_eval_dataset.py --dataset_name wikitext2 --save_path tpu/data/LLM/eval
```

#### 业务数据集

1. **业务校准数据集**

如果模型经过下游业务数据集微调，在选择校准集时，通常应该选择业务数据集。
* 如果是LLM，将业务数据集放置于上述LLM/cali目录下即可。至于数据集具体的格式，用户可以将一条一条数据文本，写到txt文件里面，每一行代表一条文本数据，使用上述的配置，可以实现自定义数据集的校准。
* 如果是VLM，将业务数据集放置于上述VLM/cali目录下即可。至于数据集具体的格式，可以参考VLM/cali/general_custom_data中的格式，选择符合需求的格式即可。这里一定需要注意，最后的json文件应该命名为samples.json。

2. **业务测试数据集**

如果模型经过下游业务数据集校准，在选择测试集时，通常应该选择业务数据集测试。
* 如果是LLM，将业务数据集放置于上述LLM/eval目录下即可。至于数据集具体的格式，用户可以将一条一条数据文本，写到txt文件里面，每一行代表一条文本数据，使用上述的配置，可以实现自定义数据集的测试。
* 如果是VLM，将业务数据集放置于上述VLM/eval目录下即可。至于数据集具体的格式，可以参考VLM/cali/general_custom_data中的格式，选择符合需求的格式即可。这里一定需要注意，最后的json文件应该命名为samples.json。

### 【阶段二】配置量化config文件

* 注意点：量化config文件包括了量化过程中所需的量化配置，用户可按照需求进行选择，同时为了对齐TPU硬件的配置也会对某些参数做出限制，具体可看下文详细介绍。

#### config文件参数说明

```yaml
base:
    seed: &seed 42
model:
    type: Qwen2VL # 设置模型名，具体支持的模型参见llmc/models目录
    path: /workspace/Qwen2-VL-2B-Instruct    # 设置模型权重路径，请改成您需要的模型
    torch_dtype: auto
calib:
    name: mme   # 设置成实际的校准数据集名称，mme，pileval等等
    download: False
    path: /workspace/llmc-tpu/tpu/data/VLM/cali/MME  # 设置校准数据集路径
    n_samples: 128
    bs: 1
    seq_len: 512
    preproc: pileval_awq
    seed: *seed
eval:
    eval_pos: [pretrain, fake_quant]
    name: mme  # 设置成实际的测试数据集名称，mme,wikitext2等等
    download: False
    path: /workspace/llmc-tpu/tpu/data/VLM/eval/MME # 设置测试数据集路径
    bs: 1
    seq_len: 2048
quant:
    method: Awq
    quant_objects: [language] # 默认只量化LLM部分，如要量化VIT部分，则设置成[vision, language]
    weight:
        bit: 4 # 设置成想要的量化bit，可以支持4或8
        symmetric: False # 4bit填False；8bit填True
        granularity: per_group # 4bit填per_group；8bit，填per_channel
        group_size: 64 # 4bit填64(与TPU-MLIR对应)；8bit，填-1
    special:
        trans: True
        trans_version: v2
        weight_clip: True
        clip_sym: True
save:
    save_trans: True       # 当设置为True，可以保存下调整之后的浮点权重
    save_path: ./save_path # 设置保存权重的路径
run:
    task_name: awq_w_only
    task_type: VLM   # 设置成VLM或者LLM
```

上面是以Awq算法为例构建的一个完整的config文件。为了简便用户操作，用户可以将上面直接拷贝到自己的config中，然后对有注解的部分参数进行修改。
下面对重要的一些参数做详细的说明：

| 参数 | 描述 |
|------|------|
| model | 模型名称，支持的模型在llmc/models目录，可以自行支持新模型 `llmc/models/xxxx.py` |
| calib | calib类参数主要指定校准集相关的参数 |
| eval | eval类参数主要指定了和测试集相关的参数 |
| quant | 指定量化参数，一般建议用Awq算法，quant_objects一般选language，关于weight量化参数参考下表 |

为了与`TPU-MLIR`对齐，weight量化相关参数配置如下：

| bit | symmetric | granularity | group_size |
|-----|-----------|-------------|------------|
| 4 | False | per-channel or per-group | -1 or 64(default) |
| 8 | True | per-channel | -1 |

### 【阶段三】执行量化算法

```shell
cd /workspace/llmc-tpu
python3 tpu/llm_quant.py --llmc_tpu_path . --config_path ./tpu/example.yml
```

* config_path则表示量化config文件对应的路径，llmc_tpu_path表示当前llmc_tpu路径

# TPU Profile工具使用及分析

## 1. TPU软件与硬件架构

完整的TPU推理应用是通过软硬件相互配合完成的，如下图所示：

软件方面，Host端实现了libsophon、驱动两个软件包。驱动负责对实际的Host与设备基础通信和资源管理机制的抽象，提供了基础的功能接口。对于TPU推理来说，libsophon提供了具体的功能，其中BMLib(`libbmlib.so`)实现对驱动接口封装，提供兼容保证，简化调用流程，提升编程的效率和可移植性，TPU-RUNTIME(`libbmrt.so`)提供了模型(bmodel)的加载、管理与执行等功能。

硬件方面，TPU内部主要由MCU、GDMA、TIU三个engine来完成工作的。

- MCU在BM1684X上是一个单核的A53处理器，通过firmware固件程序完成向GDMA、TIU两个engine下发命令、驱动通信、简单计算等具体功能，实现了算子的具体逻辑。
- GDMA和TIU是实际的执行引擎，GDMA用于Global mem与Local mem之间传输数据，实现了1D、矩阵、4D等数据搬运功能；TIU对local mem中的数据执行密集计算命令，包括卷积、矩阵乘法、算术等原子操作。

TPU Profile是将Profile数据转换为可视化网页的工具。Profile数据的来源包括内部GDMA PMU和TIU PMU两个硬件模块记录的运行计时数据、各个软件模块关键函数信息、bmodel里的元数据等。这些数据是在编译模型、以及应用运行时收集的。在实际部署中，默认是关闭的，可以通过环境变量来开启。

本文主要是利用Profile数据及TPU Profile工具，可视化模型的完整运行流程，来让读者对TPU内部有一个直观的认识。

## 2. 编译bmodel

(本操作及下面操作会用到 [TPU-MLIR](https://github.com/sophgo/tpu-mlir))

由于Profile数据会编译中的一些layer信息保存到bmodel中，导致bmodel体积变大，所以默认是关闭的。打开方式是在调用 `model_deploy.py` 加上 `--debug` 选项。如果在编译时未开启该选项，运行时开启Profile得到的数据在可视化时，会有部分数据缺失。

下面以 tpu-mlir 工程中的 yolov5s 模型来演示。

```shell
# 生成 top mlir
model_transform.py \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s.mlir
```

```shell
# 将top mlir转换成fp16精度的bmodel
model_deploy.py \
  --mlir yolov5s.mlir \
  --quantize F16 \
  --chip bm1684x \
  --test_input yolov5s_in_f32.npz \
  --test_reference yolov5s_top_outputs.npz \
  --model yolov5s_1684x_f16.bmodel \
  --debug # 记录profile数据
```

通过以上命令，将 `yolov5s.onnx` 编译成了 `yolov5s_bm1684x_f16.bmodel`。更多用法可以参见 [TPU-MLIR](https://github.com/sophgo/tpu-mlir)。

## 3. 生成Profile原始数据

同编译过程，运行时的Profile功能默认是关闭的，防止在做profile保存与传输时产生额外时间消耗。需要开启profile功能时，在运行编译好的应用前设置环境变量 `BMRUNTIME_ENABLE_PROFILE=1` 即可。下面用libsophon中提供的模型测试工具 `bmrt_test` 来作为应用，生成profile数据。

```shell
# 通过环境变量(BMRUNTIME_ENABLE_PROFILE)使能profile，生成二进制数据
BMRUNTIME_ENABLE_PROFILE=1 bmrt_test --bmodel resnet50_fix8b.bmodel
```

下面是开启Profile后运行输出的日志：

同时在当前目录生成 `bmprofile_data-1` 文件夹，为全部的Profile数据。

## 4. 可视化Profile数据

tpu-mlir提供了 `tpu_profile.py` 脚本，来把生成的二进制profile数据转换成网页文件，来进行可视化。命令如下：

```shell
# 将bmprofile_data_0目录的profile原始数据转换成网页放置到bmprofile_out目录
# 如果有图形界面，会直接打开浏览器，直接看到结果
tpu_profile.py bmprofile_data-1 bmprofile_out

ls bmprofile_out
# echarts.min.js  profile_data.js  result.html
```

用浏览器打开 `bmprofile_out/result.html` 可以看到profile的图表。

此外，该工具还有其他用法，可以通过 `tpu_profile.py --help` 来查看。

## 5. 结果分析

### 5.1 整体界面说明

完整界面大致可分为运行时序图和内存时空图。默认情况下内存时空图是折叠的，需要通过界面的"显示LOCALMEM"和"显示GLOBAL MEM"来展开。

下面对这两部分分别说明如何来分析TPU运行状态：

上图是运行时序图，根据图中标号说明如下：

0. 在做Profile时，在Host的时间可能不准确，该部分仅用于表示子网分隔标记。
1. 该行表示的是整个网络中各个Layer的时序，是由下面的TPU_GDMA，TPU_BD(TIU)实际运行衍生计算得来。一个Layer Group会将一段算子分成数据搬运和计算两部分，并且是并行运行的，所以用半高的色块表示数据搬运，全高表示计算，避免重叠。
2. 该行表示MCU上的操作，记录的关键函数包括设置GDMA、TIU指令及等待完成等。加和后通常可以表示完整的实际运行时间。
3. 该行表示TPU中GDMA操作的时序。其中色块的高度表示实际使用的数据传输带宽大小。
4. 该行表示TPU中TIU操作的时序。其中色块高度表示该计算的有效利用率。

从NODE_OP的下方的统计 `total=5.542ms`，说明整个网络运行时间是5.542ms，也可以看出在实际网络运行时，配置指令只占非常短的时间，大部时间在等待。

整体运行过程可以分为三个部分 A 段， B–E 段， F 段。其中，A 段是利用MCU将用户空间的输入数据搬运到计算指令空间；F 段是利用MCU将计算指令空间的输出数据搬回到用户空间。下面主要对 B–E 段的模型计算过程进行说明。

熟悉 [TPU-MLIR](https://github.com/sophgo/tpu-mlir) 的同学应该清楚，完整的网络并不是 Layer By Layer 来运行的，中间会经过将多个 Layer 根据硬件资源和调度关系进行融合，将加载、计算、保存分离出来，去掉中间不必要的数据搬进与搬出，形成一个 Layer Group，并划分成多个 Slice 来周期运行。整个网络根据结构可能会分成多个 Layer Group。可以观察 B、C、D 段的 Layer Pattern，中间有半高的加载保存操作，而且呈现了一定周期的循环，根据这些，我们可以判断出 B、C、D 是三个被融合后的 Layer Group。而且后面 E 段并没有明显的周期，这几个 Layer 是没有被融合的 Global Layer。整体上看，网络中只有 20% 的部分没有被融合，在这个层面上看，网络结构对于编译器相对比较友好。

上图是整体的内存时空图，包括了 LOCAL MEM 和 GLOBAL MEM 上下两部分。横轴表示时间，可以结合上面的运行时序图来看。纵轴表示内存空间范围。图中绿色块高度表示占用空间大小，宽度表示占用时间长短，此外，红色表示 GDMA 写入或 TIU 输出，绿色表示 GDMA 读取或 TIU 输入。

- LOCAL MEM 是 TPU 内部计算空间，对于 BM1684X 来说，TIU 一共有 64 个 Lane，每个 Lane 可使用 128KB 的内存，并分为了 16 个 bank。由于各个 Lane 的操作与内存是一致的，故图中只放了 Lane0 的内存占用情况。在计算过程中，还有一个需要注意的地方，计算的输入和输出最好不要在同一个 Bank 上，由于数据读写冲突，会影响计算效率。
- GLOBAL MEM 空间相对比较庞大，通常在 4GB–12GB 范围，为方便显示，只针对运行时使用的空间块进行显示。由于只有 GDMA 能与 GLOBAL MEM 通信，故绿色表示 GDMA 的读取操作，红色表示 GDMA 的写入操作。

从内存时空图中可以看出，对于 Layer Group 来说，Local Mem 的使用也呈周期性；TIU 的输入和输出通常是在每个 Bank 边界上，并且没有冲突。仅就这个网络来说，Local Mem 占用空间相对均匀，整个范围都有分布。从 GLOBAL MEM 的时空图上可以看到，以 Layer Group 运行时，写数据操作相对较少，读数据偏多。而在 Global Layer 运行时，会经过写回->读出->写回->…等操作。

此外，还可以看到运行时的 GLOBAL MEM 空间占用细节，可以分解为 Coeff 占用 14.07MB、Runtime 占用 15.20MB、Tensor 占用 6.23MB。

### 5.2 Global Layer

下面以比较简单的 Global Layer 来分析，根据 Layer 信息，Cast 的前一层由于是 Permute（图中未显示）导致无法与其他算子融合。

从 Layer 上可以看到参数信息，当前层是将 1×3×80×80×85 的 fp16 tensor 数据转换为 fp32。计算过程为：

```
time --------------------------------------->

Load0 | Compute0 | Store0   |          |
      | Load1    | Compute1 | Store1   |
      |          | Load2    | Compute2 | Store2
```

由于只有一个 GDMA 器件，Load 和 Store 只能串行执行，所以流水变成了：

```
time --------------------------------------->

GDMA: Load0 | Load1    | Store0, Load2  | Store1   | Store2
TIU:        | Compute0 | Compute1       | Compute2 |
```

从对应的内存时空图也可以看出完整的数据流动关系，输入数据是 fp16 转换到输出 fp32 后，内存翻倍了，因而传输时间大概为原来的两倍。

在计算过程中虽然已经做到流水并行，但由于受带宽限制，无法满足算力的需要，所以整个运行时间取决于数据搬进与搬出的时间。从另一方面也说明了 Layer 融合的必要性。

### 5.3 Local Layer Group

根据上面的 Layer Group 的情况，分为两种 case 来分析:

1. 效率较高的情况。主要特征是：

   - 除了前面和后面，中间的只有很少的 GDMA 操作，显著地减少了数据的搬进搬出。
   - TIU 操作效率都比较高，几乎算力全部是有效的。
   - TIU 操作之间没有空隙（也是因为 GDMA 传输时间比较短）。

   在这种情况下，可提升的空间非常有限了，只能从网络结构或其他方面来优化。

2. 算力利用率比较低的情况。这种情况主要是网络算子参数与 TPU 架构不友好造成的。我们的 BM1684X 上有 64 个 Lane，对应于输入的 IC，也就是说输入 IC 是 64 的倍数才能充分利用 TIU 的 Conv 原子操作。但从图中参数可以看到网络 Conv 的输入 Channel 为 3，导致有效计算只有 3/64。

遇到参数不友好的情况，有以下几种解决办法：

- 充分利用 LOCAL MEM 增大 Slice 以减少循环次数；
- 利用一些变换，如数据排列，来充分利用 TPU。其实对于首层为输入 Channel 为 3 的情况，我们引入了一种 3IC 的技术，已经解决了这种计算效率低的问题；
- 修改原始代码，调整相关计算。

在实际中，也遇到过很多无法避免的效率低下的情况，只能随着我们对 TPU 计算理解逐步加深，通过改进 TPU 架构或指令来解决。

## 总结

本文演示了对 TPU 做 Profile 的完整流程，并介绍了如何利用 Profile 的可视化图表来分析 TPU 中的运行过程与问题。

Profile 工具对我们开发 AI 编译器来说，是一个必要的工具。我们不仅需要在理论上分析和思考优化手段和方法，还需要从芯片内部实际运行角度来观察计算过程中的瓶颈，为软件和硬件设计和演进提供深层次的信息。另外，Profile 工具也为我们 Debug 提供了一种手段，可以直观地发现错误，比如内存踩踏、同步出错等问题。

此外，TPU Profile 的显示功能在不断完善中。

## 附录01：从 NNTC 迁移至 TPU-MLIR

NNTC 所使用 Docker 版本为 sophgo/tpuc_dev:v2.1, MLIR 使用的版本及环境初始化请参考开发环境配置。

下面将以 yolov5s 为例, 讲解NNTC和TPU-MLIR在量化方面的异同, 浮点模型编译方面可以直接参考《TPU-MLIR快速入门指南》的"编译ONNX模型"章节内容，以下内容假设已经按照《TPU-MLIR快速入门指南》中描述准备好了yolov5s模型。

### ONNX模型导入

在TPU-MLIR中要对模型进行量化首先要把原始模型转为top层的mlir文件, 这一步可以类比为NNTC中分步量化生成fp32umodel的过程。

1. TPU-MLIR的模型转换命令

```shell
$ model_transform.py \
     --model_name yolov5s \
     --model_def ../yolov5s.onnx \
     --input_shapes [[1,3,640,640]] \
     --mean 0.0,0.0,0.0 \
     --scale 0.0039216,0.0039216,0.0039216 \
     --keep_aspect_ratio \
     --pixel_format rgb \
     --output_names 350,498,646 \
     --test_input ../image/dog.jpg \
     --test_result yolov5s_top_outputs.npz \
     --mlir yolov5s.mlir
```

TPU-MLIR可以直接把图片预处理编码到转换出的mlir文件中。

2. NNTC的模型转换命令

```shell
$ python3 -m ufw.tools.on_to_umodel \
     -m ../yolov5s.onnx \
     -s '(1,3,640,640)' \
     -d 'compilation' \
     --cmp
```

NNTC导入模型的时候不能指定预处理方式。

### 制作量化校准表

想要生成定点模型都需要经过量化工具对模型进行量化, nntc中分步量化这里使用的是 calibration_use_pb, mlir使用的是run_calibration.py

输入数据的数量根据情况准备100~1000张左右,用现有的100张来自COCO2017的图片举例, 执行calibration:

在nntc中使用分步量化还需要自行使用图片量化数据集制作lmdb量化数据集,并且修改fp32_protoxt,将数据输入指向lmdb文件

> 关于NNTC量化数据集制作方式可以参考《TPU-NNTC开发参考手册》的"模型量化"章节内容,且注意该lmdb数据集与TPU-MLIR并不兼容。TPU-MLIR可以直接使用原始图片作为量化工具输入。如果是语音、文字等非图片数据,需要将其转化为npz文件。

1. MLIR 量化模型

```shell
$ run_calibration.py yolov5s.mlir \
     --dataset ../COCO2017 \
     --input_num 100 \
     -o yolov5s_cali_table
```

经过量化之后会得到量化表yolov5s_cali_table。

2. NNTC 量化模型

```shell
$ calibration_use_pb quantize \
     --model=./compilation/yolov5s_bmneto_test_fp32.prototxt \
     --weights=./compilation/yolov5s_bmneto.fp32umodel \
     -save_test_proto=True --bitwidth=TO_INT8
```

在nntc中,量化之后得到的是int8umodel以及prototxt。

### 生成int8模型

转成INT8对称量化模型, 执行如下命令:

1. MLIR:

```shell
$ model_deploy.py \
     --mlir yolov5s.mlir \
     --quantize INT8 \
     --calibration_table yolov5s_cali_table \
     --processor bm1684 \
     --test_input yolov5s_in_f32.npz \
     --test_reference yolov5s_top_outputs.npz \
     --tolerance 0.85,0.45 \
     --model yolov5s_1684_int8_sym.bmodel
```

运行结束之后得到yolov5s_1684_int8_sym.bmodel。

2. NNTC:

在NNTC中,则是使用int8umodel以及prototxt使用bmnetu工具生成int8的bmodel。

```shell
$ bmnetu --model=./compilation/yolov5s_bmneto_deploy_int8_unique_top.prototxt \
     --weight=./compilation/yolov5s_bmneto.int8umodel
```

运行结束之后得到compilation.bmodel。

## 附录02：TpuLang的基本元素

本章将介绍TpuLang程序的基本元素：Tensor、Scalar、Control Functions和Operator。

### 张量(Tensor)

TpuLang中Tensor的name, data，data type, tensor type均最多只能声明或者设置1次。

一般情况下推荐创建Tensor不指定Name，以免因为Name相同导致问题。只有在必须指定Name时，才需要在创建Tensor时指定Name。

对于作为Operator输出的Tensor，可以不指定shape，因为Operator会自行推导。即使指定了shape，若Tensor是Operator的输出，则同样由Operator自行推导并修改。

TpuLang中Tensor的定义如下：

```python
class Tensor:

    def __init__(self,
                shape: list = [],
                name: str = None,
                ttype="neuron",
                data=None,
                dtype: str = "float32",
                scale: Union[float, List[float]] = None,
                zero_point: Union[int, List[int]] = None)
          #pass
```

如上所示，TpuLang中Tensor有5个参数。

- shape：Tensor的形状，List[int]，对于Operator输出的Tensor，可以不指定shape，默认值为[]。
- Name：Tensor的名称，string或None，该值推荐使用默认值None以免因为Name相同导致问题；
- ttype：Tensor的类型，可以是"neuron"或"coeff"，初始值为"neuron"；
- data：Tensor的数据，ndarray或None，默认值为None，此时Tensor将根据指定的形状初始化为全零。当ttype为coeff时，不可以为None，data为ndarray，此时data的shape，dtype必须与输入shape，dtype一致。
- dtype：Tensor的数据类型，默认值为"float32"，否则取值范围为"float32", "float16", "int32", "uint32", "int16", "uint16", "int8", "uint8"；
- scale：Tensor的量化参数，float或List[float]，默认值为None；
- zero_point：Tensor的偏移参数，int或List[int]，默认值为None；

声明Tensor的示例：

```python
#activation
input = tpul.Tensor(name='x', shape=[2,3], dtype='int8')
#weight
weight = tpul.Tensor(dtype='float32', shape=[3,4], data=np.random.uniform(0,1,shape).astype('float32'), ttype="coeff")
```

### 张量前处理(Tensor.preprocess)

TpuLang中Tensor如果是输入，且需要对输入进行前处理，可以调用该函数

TpuLang中Tensor.preprocess的定义如下：

```python
class Tensor:

    def preprocess(self,
                   mean : List[float] = [0, 0, 0],
                   scale : List[float] = [1.0, 1.0, 1.0],
                   pixel_format : str = 'bgr',
                   channel_format : str = 'nchw',
                   resize_dims : List[int] = None,
                   keep_aspect_ratio : bool = False,
                   keep_ratio_mode : str = 'letterbox',
                   pad_value : int = 0,
                   pad_type : str = 'center',
                   white_level : float = 4095,
                   black_level : float = 112):
          #pass
```

如上所示，TpuLang中Tensor的preprocess有如下几个参数。

- mean：Tensor的每个channel的平均值，默认值为[0, 0, 0]；
- scale：Tensor的每个channel的scale值，默认值为[1, 1, 1]；
- pixel_format：Tensor的pixel的方式，默认值为'bgr'，取值范围为：'rgb'，'bgr'，'gray'，'rgba'，'gbrg'，'grbg'，'bggr'，'rggb'；
- channel_format：Tensor的格式，channel维在前还是在最后。默认值为'nchw'，取值范围为"nchw"，"nhwc"。
- resize_dims：Tensor的resize后的[h，w]，默认值为None，表示取Tensor的h和w；
- keep_aspect_ratio：resize参数，是否保持相同的scale。bool量，默认值为False；
- keep_ratio_mode：resize参数，如果使能keep_aspect_ratio的两种模式，默认值'letterbox'，取值范围为'letterbox'，'short_side_scale'；
- pad_value：resize参数，当resize时pad的值。int类型，默认值为0；
- pad_type：resize参数，当resize时pad的方式。str类型，默认值为'center'，取值范围为'normal'，'center'；

# 标量(Scalar)

定义一个标量Scalar。Scalar是一个常量，在声明时指定，且不能修改。

```python
class Scalar:
    def __init__(self, value, dtype=None):
        #pass
```

Scalar构造函数有两个参数：

* value：Variable型，即int/float型，无默认值，必须指定
* dtype：Scalar的数据类型，为默认值None等同于"float32"，否则取值范围为"float32", "float16", "int32", "uint32", "int16", "uint16", "int8", "uint8"

使用实例：

```python
pad_val = tpul.Scalar(1.0)
pad = tpul.pad(input, value=pad_val)
```

# Control Functions

控制函数（control functions）主要包括控制TpuLang使用时的初始化、启动编译生成目标文件等。

控制函数常用于TpuLang程序的Tensor和Operator之前和之后。比如在写Tensor和Operator之前，可能需要做初始化。在完成Tensor和Operator编写之后，可能需要启动编译和反初始化。

## 初始化函数

初始化Function，在一个程序中构建网络之前使用。

初始化函数接口如下所示，选择处理器型号。

```python
def init(device):
    #pass
```

* device：string类型。取值范围"BM1684X"|"BM1688"|"CV183X"

## compile

### 接口定义

```python
def compile(name: str,
    inputs: List[Tensor],
    outputs: List[Tensor],
    cmp=True,
    refs=None,
    mode='f32',         # unused
    dynamic=False,
    asymmetric=False,
    no_save=False,
    opt=2,
    mlir_inference=True,
    bmodel_inference=True,
    log_level="normal",
    embed_debug_info=False):
```

### 功能描述

用于将TpuLang模型编译为bmodel。

### 参数说明

* name：string类型。模型名称
* inputs：List[Tensor]，表示编译网络的所有输入Tensor
* outputs：List[Tensor]，表示编译网络的所有输出Tensor
* cmp：bool类型，True表示需要结果比对，False表示仅编译；如果mlir_inference为False，cmp参数无效
* refs：List[Tensor]，表示编译网络的所有需要比对验证的Tensor
* mode：string类型，废弃
* dynamic：bool类型，是否进行动态编译
* no_save：bool类型，是否将中间文件暂存到共享内存并随进程释放，启用该项时Compile会返回生成的bmodel文件的bytes-like object，用户需要自行接收和处理，如使用f.write(bmodel_bin)保存
* asymmetric：bool类型，是否为非对称量化
* opt：int类型，表示编译器group优化级别。0，表示不需要进行group；1，表示尽可能进行group；2，表示根据动态规划进行group。默认值为2
* mlir_inference: bool类型，是否执行mlir的推理，如果为False, cmp参数无效
* bmodel_inference: bool类型，是否执行bmodel的推理
* log_level 用来控制日志等级，目前支持only-pass、only-layer-group、normal、quiet:
  - only-pass: 主要打印图优化pattern匹配情况
  - only-layer-group: 主要打印layer group 信息
  - normal: 编译生成bmodel的日志都会打印出来
  - quiet: 什么都不打印
* embed_debug_info: bool类型，是否开启profile模式

## 反初始化

在网络构建之后，需要进行反初始化结束。只有在反初始化后，之前Tpulang的数据才会得到释放

```python
def deinit():
    #pass
```

## 重置默认图

在网络构建之前，需要进行重置默认图操作。如果输入graph为None，重置默认图后，当前graph为空图。如果设置输入graph，会设置graph为默认图。如果只有一个子图，可以不需要显示调用reset_default_graph。因为init函数会调用该函数。

```python
def reset_default_graph(graph = None):
    #pass
```

## 获取当前默认图

在网络构建之后，如果需要得到默认的子图，调用该函数可以得到默认的graph。

```python
def get_default_graph():
    #pass
```

## 重置图

如果需要清除graph以及其保存的Tensor信息，可以调用该函数。graph为None时，清除当前默认图的信息。

```python
def reset_graph(graph = None):
    #pass
```

注意：如果graph中的Tensor还被其他graph使用，不要调用该函数清除graph信息

## 舍入模式

舍入是指按照一定的规则舍去某些数字后面多余的尾数的过程，以得到更简短、明确的数字表示。给定 x，舍入结果是 y，有下面的舍入模式供选择。

### 邻近偶数四舍五入(Half to Even)

四舍五入，当小数值为0.5时舍入到邻近的偶数，对应的值是 `half_to_even`。

### 远离原点四舍五入(Half Away From Zero)

四舍五入，正数接近于正无穷，负数接近于负无穷，对应的值是 `half_away_from_zero`，公式如下

$y = \mathrm{sign}(x)\left\lfloor|x| + 0.5\right\rfloor = -\mathrm{sign}(x)\left\lceil-|x| - 0.5\right\rceil$

### 截断取整(Towards Zero)

无条件舍去，接近于原点，对应的值是 `towards_zero`，公式如下

$y = \mathrm{sign}(x)\left\lfloor|x|\right\rfloor = -\mathrm{sign}(x)\left\lceil-|x|\right\rceil = {\begin{cases}\lfloor x\rfloor&{\text{if}}\ \ x > 0,\\ \lceil x\rceil&{\text{otherwise}}.\end{cases}}$

### 下取整(Down)

接近于负无穷，对应的值是 `down`，公式如下

$y = \lfloor x\rfloor = -\lceil-x\rceil$

### 上取整(Up)

接近于正无穷，对应的值是 `up`，公式如下

$y = \lceil x\rceil = -\lfloor-x\rfloor$

### 向上四舍五入(Half Up)

四舍五入，接近于正无穷，对应的值是 `half_up`，公式如下

$y = \lceil x + 0.5\rceil = -\lfloor-x - 0.5\rfloor = \left\lceil\frac{\lfloor 2x\rfloor}{2}\right\rceil$

### 向下四舍五入(Half Down)

四舍五入，接近于正无穷，对应的值是 `half_down`，公式如下

$y = \lfloor x - 0.5\rfloor = -\lceil-x + 0.5\rceil = \left\lfloor\frac{\lceil 2x\rceil}{2}\right\rfloor$

### 例子

下表列出不同舍入模式下 x 与 y 的对应关系。

| | Half to Even | Half Away From Zero | Towards Zero | Down | Up | Half Up | Half Down |
|---|---|---|---|---|---|---|---|
| +1.8 | +2 | +2 | +1 | +1 | +2 | +2 | +2 |
| +1.5 | +2 | +2 | +1 | +1 | +2 | +2 | +1 |
| +1.2 | +1 | +1 | +1 | +1 | +2 | +1 | +1 |
| +0.8 | +1 | +1 | 0 | 0 | +1 | +1 | +1 |
| +0.5 | 0 | +1 | 0 | 0 | +1 | +1 | 0 |
| +0.2 | 0 | 0 | 0 | 0 | +1 | 0 | 0 |
| -0.2 | 0 | 0 | 0 | -1 | 0 | 0 | 0 |
| -0.5 | 0 | -1 | 0 | -1 | 0 | 0 | -1 |
| -0.8 | -1 | -1 | 0 | -1 | 0 | -1 | -1 |
| -1.2 | -1 | -1 | -1 | -2 | -1 | -1 | -1 |
| -1.5 | -2 | -2 | -1 | -2 | -1 | -1 | -2 |
| -1.8 | -2 | -2 | -1 | -2 | -1 | -2 | -2 |

# Operator

为了TpuLang编程时可以考虑到获取好的性能，下面会将Operator分成本地操作（Local Operator）、受限本地操作（Limited Local Operator）和全局操作（Global Operator）。

* 本地操作：在启动编译时，可以与其它的本地操作进行合并优化，使得操作之间的数据只存在于TPU的本地存储中
* 受限本地操作：在一定条件下才能作为本地操作与其它本地操作进行合并优化
* 全局操作：不能与其它操作进行合并优化，操作的输入输出数据都需要放到TPU的全局存储中

以下操作中，很多属于按元素计算(Element-wise)的操作，要求输入输出Tensor的shape具备相同数量的维度。

当操作的输入Tensor是2个时，分为支持shape广播和不支持shape广播两种。支持shape广播表示tensor_i0（输入0）和tensor_i1（输入1）的同一维度的shape值可以不同，此时其中一个tensor的shape值必须是1，数据将被广播扩展到另一个tensor对应的shape值。不支持shape广播则要求tensor_i0（输入0）和tensor_i1（输入1）的shape值一致。

## NN/Matrix Operator

### conv

#### 接口定义

```python
def conv(input: Tensor,
         weight: Tensor,
         bias: Tensor = None,
         stride: List[int] = None,
         dilation: List[int] = None,
         pad: List[int] = None,
         group: int = 1,
         out_dtype: str = None,
         out_name: str = None):
    #pass
```

#### 功能描述

二维卷积运算。可参考各框架下的二维卷积定义。该操作属于 **本地操作**。

#### 参数说明

* input：Tensor类型，表示输入Tensor，4维NCHW格式
* weight：Tensor类型，表示卷积核Tensor，4维NCHW格式
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]，oc表示输出Channel数
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1]，不为None时要求长度2
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1]，不为None时要求长度为2
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0]，不为None时要求长度为4
* groups：int型，表示卷积层的组数
* out_dtype：string类型或None，为None时与input数据类型一致。取值为范围为"float32"，"float16"。表示输出Tensor的数据类型
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

#### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

#### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32

### conv_int

#### 接口定义

```python
def conv_int(input: Tensor,
             weight: Tensor,
             bias: Tensor = None,
             stride: List[int] = None,
             dilation: List[int] = None,
             pad: List[int] = None,
             group: int = 1,
             input_zp: Union[int, List[int]] = None,
             weight_zp: Union[int, List[int]] = None,
             out_dtype: str = None,
             out_name: str = None):
    # pass
```

#### 功能描述

二维卷积定点运算。可参考各框架下的二维卷积定义。

```
for c in channel
  izp = is_izp_const ? izp_val : izp_vec[c];
  wzp = is_wzp_const ? wzp_val : wzp_vec[c];
  output = (input - izp) Conv (weight - wzp) + bias[c];
```

该操作属于 **本地操作**。

#### 参数说明

* tensor_i：Tensor类型，表示输入Tensor，4维NCHW格式
* weight：Tensor类型，表示卷积核Tensor，4维[oc, ic, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kh是kernel_h，kw是kernel_w
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]。bias的数据类型为int32
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1]，不为None时要求长度为2
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1]，不为None时要求长度为2
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0]，不为None时要求长度为4
* groups：int型，表示卷积层的组数。若ic=oc=groups时，则卷积为depthwise conv
* input_zp：List[int]型或int型，表示输入偏移。取None则表示0，取List时要求长度为ic。当前不支持List[int]型
* weight_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为ic，其中ic表示输入的Channel数
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int32。取值范围：int32/uint32
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

#### 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype确定。

#### 处理器支持

* BM1688：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32
* BM1684X：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32

### conv_quant

#### 接口定义

```python
def conv_quant(input: Tensor,
             weight: Tensor,
             bias: Tensor = None,
             stride: List[int] = None,
             dilation: List[int] = None,
             pad: List[int] = None,
             group: int = 1,
             input_scale: Union[float, List[float]] = None,
             weight_scale: Union[float, List[float]] = None,
             output_scale: Union[float, List[float]] = None,
             input_zp: Union[int, List[int]] = None,
             weight_zp: Union[int, List[int]] = None,
             output_zp: Union[int, List[int]] = None,
             out_dtype: str = None,
             out_name: str = None):
    # pass
```

#### 功能描述

二维卷积定点运算。可参考各框架下的二维卷积定义。

```
for c in channel
  izp = is_izp_const ? izp_val : izp_vec[c];
  wzp = is_wzp_const ? wzp_val : wzp_vec[c];
  conv_i32 = (input - izp) Conv (weight - wzp) + bias[c];
  output = requant_int(conv_i32, mul, shift) + ozp
  其中mul，shift由iscale，wscale，oscale得到
```

该操作属于 **本地操作**。

#### 参数说明

* tensor_i：Tensor类型，表示输入Tensor，4维NCHW格式
* weight：Tensor类型，表示卷积核Tensor，4维[oc, ic, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kh是kernel_h，kw是kernel_w
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]。bias的数据类型为int32
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1]，不为None时要求长度为2
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1]，不为None时要求长度为2
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0]，不为None时要求长度为4
* groups：int型，表示卷积层的组数。若ic=oc=groups时，则卷积为depthwise conv
* input_scale：List[float]型或float型，表示输入量化参数。取None则使用input Tensor中的量化参数，取List时要求长度为ic。当前不支持List[float]型
* weight_scale：List[float]型或float型，表示卷积核量化参数。取None则使用weight Tensor中的量化参数，取List时要求长度为oc
* output_scale：List[float]型或float型，表示卷积核量化参数。不可以取None，取List时要求长度为oc。当前不支持List[float]型
* input_zp：List[int]型或int型，表示输入偏移。取None则表示0，取List时要求长度为ic。当前不支持List[int]型
* weight_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为oc
* output_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为oc。当前不支持List[int]型
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int8。取值范围：int8/uint8
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

#### 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype确定。

#### 处理器支持

* BM1688：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32

# deconv

## 接口定义

```python
def deconv(input: Tensor,
           weight: Tensor,
           bias: Tensor = None,
           stride: List[int] = None,
           dilation: List[int] = None,
           pad: List[int] = None,
           output_padding: List[int] = None,
           group: int = 1,
           out_dtype: str = None,
           out_name: str = None):
    #pass
```

## 功能描述

二维反卷积运算。可参考各框架下的二维反卷积定义。
该操作属于 **本地操作**。

## 参数说明

* input：Tensor类型，表示输入Tensor，4维NCHW格式。
* weight：Tensor类型，表示卷积核Tensor，4维NCHW格式。
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]，oc表示输出Channel数。
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1]，不为None时要求长度为2。
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1]，不为None时要求长度为2。
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0]，不为None时要求长度为4。
* output_padding：List[int]，表示输出每个空间维度的填充大小，取None则表示[0,0]，不为None时要求长度为2。
* group：int类型，表示表示反卷积层的组数。
* out_dtype：string类型或None，为None时与input数据类型一致。取值为范围为"float32"，"float16"。表示输出Tensor的数据类型。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32。

# deconv_int

## 接口定义

```python
def deconv_int(input: Tensor,
             weight: Tensor,
             bias: Tensor = None,
             stride: List[int] = None,
             dilation: List[int] = None,
             pad: List[int] = None,
             output_padding: List[int] = None,
             group: int = 1,
             input_zp: Union[int, List[int]] = None,
             weight_zp: Union[int, List[int]] = None,
             out_dtype: str = None,
             out_name: str = None):
    # pass
```

## 功能描述

二维反卷积定点运算。可参考各框架下的二维卷积定义。

```
for c in channel
  izp = is_izp_const ? izp_val : izp_vec[c];
  wzp = is_wzp_const ? wzp_val : wzp_vec[c];
  output = (input - izp) Deconv (weight - wzp) + bias[c];
```

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，4维NCHW格式。
* weight：Tensor类型，表示卷积核Tensor，4维[oc, ic, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kh是kernel_h，kw是kernel_w。
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1]。bias的数据类型为int32
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1]，不为None时要求长度为2。
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1]，不为None时要求长度为2。
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0]，不为None时要求长度为4。
* output_padding：List[int]，表示输出的填充大小，取None则表示[0,0]，不为None时要求长度为1或2。
* groups：int型，表示反卷积层的组数。
* input_zp：List[int]型或int型，表示输入偏移。取None则表示0，取List时要求长度为ic。当前不支持List[int]型。
* weight_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为ic，其中ic表示输入的Channel数。
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int32。取值范围：int32/uint32。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype确定。

## 处理器支持

* BM1688：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32。
* BM1684X：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32。

# conv3d

## 接口定义

```python
def conv3d(input: Tensor,
           weight: Tensor,
           bias: Tensor = None,
           stride: List[int] = None,
           dilation: List[int] = None,
           pad: List[int] = None,
           group: int = 1,
           out_dtype: str = None,
           out_name: str = None):
    #pass
```

## 功能描述

三维卷积运算。可参考各框架下的三维卷积定义。
该操作属于 **本地操作**。

## 参数说明

* input：Tensor类型，表示输入Tensor，5维NCDHW格式。
* weight：Tensor类型，表示卷积核Tensor，4维NCDHW格式。
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1, 1]或[oc]，oc表示输出Channel数。
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1,1]，不为None时要求长度为3。
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1,1]，不为None时要求长度为3。
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0,0,0]，不为None时要求长度为6。
* groups：int型，表示卷积层的组数。
* out_dtype：string类型或None，为None时与input数据类型一致。取值为范围为"float32"，"float16"。表示输出Tensor的数据类型。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。input与weight的数据类型必须一致。bias的数据类型必须是FLOAT32。

# conv3d_int

## 接口定义

```python
def conv3d_int(input: Tensor,
               weight: Tensor,
               bias: Tensor = None,
               stride: List[int] = None,
               dilation: List[int] = None,
               pad: List[int] = None,
               group: int = 1,
               input_zp: Union[int, List[int]] = None,
               weight_zp: Union[int, List[int]] = None,
               out_dtype: str = None,
               out_name: str = None):
```

## 功能描述

三维卷积定点运算。可参考各框架下的三维卷积定义。

```
for c in channel
  izp = is_izp_const ? izp_val : izp_vec[c];
  kzp = is_kzp_const ? kzp_val : kzp_vec[c];
  output = (input - izp) Conv3d (weight - kzp) + bias[c];
```

其中Conv3d表示3D卷积计算。

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，5维NCTHW格式。
* weight：Tensor类型，表示卷积核Tensor，5维[oc, ic, kt, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kt是kernel_t，kh是kernel_h，kw是kernel_w。
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1, 1]。
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1,1]，不为None时要求长度为3。
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1,1]，不为None时要求长度为3。
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0,0,0]。不为None时要求长度6。
* groups：int型，表示卷积层的组数。若ic=oc=groups时，则卷积为depthwise conv3d。
* input_zp：List[int]型或int型，表示输入偏移。取None则表示0，取List时要求长度为ic。当前不支持List[int]型。
* weight_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为ic，其中ic表示输入的Channel数。
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int32。取值范围：int32/uint32。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype确定。

## 处理器支持

* BM1688：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32。
* BM1684X：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32。

# conv3d_quant

## 接口定义

```python
def conv3d_quant(input: Tensor,
             weight: Tensor,
             bias: Tensor = None,
             stride: List[int] = None,
             dilation: List[int] = None,
             pad: List[int] = None,
             group: int = 1,
             input_scale: Union[float, List[float]] = None,
             weight_scale: Union[float, List[float]] = None,
             output_scale: Union[float, List[float]] = None,
             input_zp: Union[int, List[int]] = None,
             weight_zp: Union[int, List[int]] = None,
             output_zp: Union[int, List[int]] = None,
             out_dtype: str = None,
             out_name: str = None):
    # pass
```

## 功能描述

二维卷积定点运算。可参考各框架下的二维卷积定义。

```
for c in channel
  izp = is_izp_const ? izp_val : izp_vec[c];
  wzp = is_wzp_const ? wzp_val : wzp_vec[c];
  conv_i32 = (input - izp) Conv (weight - wzp) + bias[c];
  output = requant_int(conv_i32, mul, shift) + ozp
  其中mul，shift由iscale，wscale，oscale得到
```

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，5维NCTHW格式。
* weight：Tensor类型，表示卷积核Tensor，5维[oc, ic, kt, kh, kw]格式。其中oc表示输出Channel数，ic表示输入channel数，kt是kernel_t，kh是kernel_h，kw是kernel_w。
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[1, oc, 1, 1， 1]。bias的数据类型为int32。
* stride：List[int]，表示每个空间维度的步长大小，取None则表示[1,1,1]，不为None时要求长度为3。
* dilation：List[int]，表示每个空间维度的空洞大小，取None则表示[1,1,1]，不为None时要求长度为3。
* pad：List[int]，表示每个空间维度的填充大小，遵循[x1_begin, x2_begin…x1_end, x2_end,…]顺序。取None则表示[0,0,0,0,0,0]。不为None时要求长度6。
* groups：int型，表示卷积层的组数。若ic=oc=groups时，则卷积为depthwise conv3d
* input_scale：List[float]型或float型，表示输入量化参数。取None则使用input Tensor中的量化参数，取List时要求长度为ic。当前不支持List[float]型。
* weight_scale：List[float]型或float型，表示卷积核量化参数。取None则使用weight Tensor中的量化参数，取List时要求长度为oc。
* output_scale：List[float]型或float型，表示卷积核量化参数。不可以取None，取List时要求长度为oc。当前不支持List[float]型。
* input_zp：List[int]型或int型，表示输入偏移。取None则表示0，取List时要求长度为ic。当前不支持List[int]型。
* weight_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为oc。
* output_zp：List[int]型或int型，表示卷积核偏移。取None则表示0，取List时要求长度为oc。当前不支持List[int]型。
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int8。取值范围：int8/uint8。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype确定。

## 处理器支持

* BM1688：输入和权重的数据类型可以是INT8/UINT8。偏置的数据类型为INT32。

# matmul

## 接口定义

```python
def matmul(input: Tensor,
           right: Tensor,
           bias: Tensor = None,
           right_transpose: bool = False,
           left_transpose: bool = False,
           output_transpose: bool = False,
           keep_dims: bool = True,
           out_dtype: str = None,
           out_name: str = None):
    #pass
```

## 功能描述

矩阵乘运算。可参考各框架下的矩阵乘定义。
该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示输入左操作数，大于或等于2维，设最后两维shape=[m,k]
* right：Tensor类型，表示输入右操作数，大于或等于2维，设最后两维shape=[k,n]
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[n]
* left_transpose：bool型，默认为False。表示计算时是否对左矩阵进行转置
* right_transpose：bool型，默认为False。表示计算时是否对右矩阵进行转置
* output_transpose：bool型，默认为False。表示计算时是否对输出矩阵进行转置
* keep_dims：bool型，默认为True。表示结果是否保持原来的dim，False则shape为2维
* out_dtype：string类型或None，为None时与input数据类型一致。取值为范围为"float32"，"float16"。表示输出Tensor的数据类型
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

要求左右Tensor的维度长度一致。
当Tensor的维度长度为2时，表示矩阵和矩阵乘运算。
当Tensor的维度长度大于2时，表示批矩阵乘运算。要求input.shape[-1] == right.shape[-2]，input.shape[:-2]和right.shape[:-2]需要满足广播规则。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。input与right的数据类型必须一致。bias的数据类型必须是FLOAT32
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。input与right,bias的数据类型必须一致

# matmul_int

## 接口定义

```python
def matmul_int(input: Tensor,
               right: Tensor,
               bias: Tensor = None,
               right_transpose: bool = False,
               left_transpose: bool = False,
               output_transpose: bool = False,
               keep_dims: bool = True,
               input_zp: Union[int, List[int]] = None,
               right_zp: Union[int, List[int]] = None,
               out_dtype: str = None,
               out_name: str = None):
    #pass
```

## 功能描述

矩阵乘运算。可参考各框架下的矩阵乘定义。
该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示输入左操作数，大于或等于2维，设最后两维shape=[m,k]
* right：Tensor类型，表示输入右操作数，大于或等于2维，设最后两维shape=[k,n]
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[n]
* left_transpose：bool型，默认为False。表示计算时是否对左矩阵进行转置
* right_transpose：bool型，默认为False。表示计算时是否对右矩阵进行转置
* output_transpose：bool型，默认为False。表示计算时是否对输出矩阵进行转置
* keep_dims：bool型，默认为True。表示结果是否保持原来的dim，False则shape为2维
* input_zp：List[int]型或int型，表示input的偏移。取None则表示0。当前不支持List[int]型
* right_zp：List[int]型或int型，表示right的偏移。取None则表示0。当前不支持List[int]型
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int32。取值范围：int32/uint32
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

要求左右Tensor的维度长度一致。
当Tensor的维度长度为2时，表示矩阵和矩阵乘运算。
当Tensor的维度长度大于2时，表示批矩阵乘运算。要求input.shape[-1] == right.shape[-2]，input.shape[:-2]和right.shape[:-2]需要满足广播规则。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定。

## 处理器支持

* BM1688：输入数据类型可以是INT8/UINT8。偏置的数据类型为INT32
* BM1684X：输入数据类型可以是INT8/UINT8。偏置的数据类型为INT32

# matmul_quant

## 接口定义

```python
def matmul_quant(input: Tensor,
               right: Tensor,
               bias: Tensor = None,
               right_transpose: bool = False,
               keep_dims: bool = True,
               input_scale: Union[float, List[float]] = None,
               right_scale: Union[float, List[float]] = None,
               output_scale: Union[float, List[float]] = None,
               input_zp: Union[int, List[int]] = None,
               right_zp: Union[int, List[int]] = None,
               output_zp: Union[int, List[int]] = None,
               out_dtype: str = None,
               out_name: str = None):
    #pass
```

## 功能描述

量化的矩阵乘运算。可参考各框架下的矩阵乘定义。
该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示输入左操作数，大于或等于2维，设最后两维shape=[m,k]
* right：Tensor类型，表示输入右操作数，大于或等于2维，设最后两维shape=[k,n]
* bias：Tensor类型，表示偏置Tensor。为None时表示无偏置，反之则要求shape为[n]
* right_transpose：bool型，默认为False。表示计算时是否对右矩阵进行转置
* keep_dims：bool型，默认为True。表示结果是否保持原来的dim，False则shape为2维
* input_scale：List[float]型或float型，表示input的量化参数。取None则使用input Tensor中的量化参数。当前不支持List[float]型
* right_scale：List[float]型float型，表示right的量化参数。取None则使用right Tensor中的量化参数。当前不支持List[float]型
* output_scale：List[float]型float型，表示output的量化参数。不可以取None。当前不支持List[float]型
* input_zp：List[int]型或int型，表示input的偏移。取None则表示0。当前不支持List[int]型
* right_zp：List[int]型或int型，表示right的偏移。取None则表示0。当前不支持List[int]型
* output_zp：List[int]型或int型，表示output的偏移。取None则表示0。当前不支持List[int]型
* out_dtype：string类型或None，表示输入Tensor的类型，取None表示为int8。取值范围：int8/uint8
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

要求左右Tensor的维度长度一致。
当Tensor的维度长度为2时，表示矩阵和矩阵乘运算。
当Tensor的维度长度大于2时，表示批矩阵乘运算。要求input.shape[-1] == right.shape[-2]，input.shape[:-2]和right.shape[:-2]需要满足广播规则。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定。

## 处理器支持

* BM1688：输入数据类型可以是INT8/UINT8。偏置的数据类型为INT32
* BM1684X：输入数据类型可以是INT8/UINT8。偏置的数据类型为INT32

# Base Element-wise Operator

## add

### 接口定义

```python
def add(tensor_i0: Union[Tensor, Scalar, int, float],
      tensor_i1: Union[Tensor, Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_dtype: str = None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素加法运算。$tensor\_o = tensor\_i0 + tensor\_i1$。
该操作支持广播。
该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point
* out_dtype：string类型或None，表示输出Tensor的数据类型，为None时会与输入数据类型一致。可选参数为'float32'/'float16'/'int8'/'uint8'
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定，或与输入数据类型一致（当其中一个输入为'int8'则输出默认为'int8'类型）。当输入为'float32'/'float16'时，输出数据类型必须与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致

## sub

# sub

## 接口定义

```python
def sub(tensor_i0: Union[Tensor, Scalar, int, float],
        tensor_i1: Union[Tensor, Scalar, int, float],
        scale: List[float]=None,
        zero_point: List[int]=None,
        out_dtype: str = None,
        out_name: str = None):
    #pass
```

## 功能描述

张量和张量的按元素减法运算。 `tensor_o = tensor_i0 - tensor_i1`。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。
* out_dtype：string类型或None，表示输出Tensor的数据类型，为None时会与输入数据类型一致。可选参数为'float32'/'float16'/'int8'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。当输入为'float32'/'float16'时，输出数据类型必须与输入一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。

# mul

## 接口定义

```python
def mul(tensor_i0: Union[Tensor, Scalar, int, float],
        tensor_i1: Union[Tensor, Scalar, int, float],
        scale: List[float]=None,
        zero_point: List[int]=None,
        out_dtype: str = None,
        out_name: str = None):
    #pass
```

## 功能描述

张量和张量的按元素乘法运算。 `tensor_o = tensor_i0 * tensor_i1`。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。
* out_dtype：string类型或None，表示输出Tensor的数据类型，为None时会与输入数据类型一致。可选参数为'float32'/'float16'/'int8'/'uint8'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定，或与输入数据类型一致（当其中一个输入为'int8'则输出默认为'int8'类型）。当输入为'float32'/'float16'时，输出数据类型必须与输入一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。

# div

## 接口定义

```python
def div(tensor_i0: Union[Tensor, Scalar],
        tensor_i1: Union[Tensor, Scalar],
        out_name: str = None):
    #pass
```

## 功能描述

张量和张量的按元素除法运算。 `tensor_o = tensor_i0 / tensor_i1`。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32。

# max

## 接口定义

```python
def max(tensor_i0: Union[Tensor, Scalar, int, float],
        tensor_i1: Union[Tensor, Scalar, int, float],
        scale: List[float]=None,
        zero_point: List[int]=None,
        out_dtype: str = None,
        out_name: str = None):
    #pass
```

## 功能描述

张量和张量的按元素取最大值。 `tensor_o = max(tensor_i0, tensor_i1)`。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。
* out_dtype：string类型或None，表示输出Tensor的数据类型，为None时会与输入数据类型一致。可选参数为'float32'/'float16'/'int8'/'uint8'/'int16'/'uint16'/'int32'/'uint32'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT16/UINT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT16/UINT16/INT8/UINT8。

# min

## 接口定义

```python
def min(tensor_i0: Union[Tensor, Scalar, int, float],
        tensor_i1: Union[Tensor, Scalar, int, float],
        scale: List[float]=None,
        zero_point: List[int]=None,
        out_dtype: str = None,
        out_name: str = None):
    #pass
```

## 功能描述

张量和张量的按元素取最小值。 `tensor_o = min(tensor_i0, tensor_i1)`。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int、float，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int、float，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。
* out_dtype：string类型或None，表示输出Tensor的数据类型，为None时会与输入数据类型一致。可选参数为'float32'/'float16'/'int8'/'uint8'/'int16'/'uint16'/'int32'/'uint32'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。当数据类型为FLOAT16/FLOAT32时，tensor_i0与tensor_i1的数据类型必须一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT16/UINT16/INT32/UINT32/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT16/UINT16/INT32/UINT32/INT8/UINT8。

# add_shift

## 接口定义

```python
def add_shift(tensor_i0: Union[Tensor, Scalar, int],
              tensor_i1: Union[Tensor, Scalar, int],
              shift: int,
              out_dtype: str,
              round_mode: str='half_away_from_zero',
              is_saturate: bool=True,
              out_name: str = None):
    #pass
```

## 功能描述

运算公式 `tensor_o = (tensor_i0 + tensor_i1) << shift`。
张量和张量的按元素相加后再舍入算术移shift位，shift为正时，左移，shift为负时，右移。舍入模式由round_mode确定。
add_shift数据相加后，以INT64为中间结果保存，然后在INT64基础上做一次舍入的算数移位操作；
结果支持饱和处理；当tensor_i0、tensor_i1为signed，且tensor_o为unsigned时，结果必须饱和处理。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* shift：int型，表示移位的位数。
* round_mode：String型，表示舍入模式。默认值为'half_away_from_zero'。取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。
* is_saturate：Bool型，表示结果是否需要饱和处理，默认饱和处理。
* out_dtype：String或None，表示输出Tensor的数据类型，取默认值时则和tensor_i0的类型一致。可选参数为'int8'/'uint8'/'int16'/'uint16'/'int32'/'uint32'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor。
该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。

## 处理器支持

* BM1688：输入数据类型可以是INT32/UINT32/INT16/UINT6/INT8/UINT8。
* BM1684X：输入数据类型可以是INT32/UINT32/INT16/UINT6/INT8/UINT8。

# sub_shift

## 接口定义

```python
def sub_shift(tensor_i0: Union[Tensor, Scalar, int],
              tensor_i1: Union[Tensor, Scalar, int],
              shift: int,
              out_dtype: str,
              round_mode: str='half_away_from_zero',
              is_saturate: bool=True,
              out_name: str = None):
    #pass
```

## 功能描述

运算公式 `tensor_o = (tensor_i0 - tensor_i1) << shift`。
张量和张量的按元素相减后再舍入算术移shift位，shift为正时，左移，shift为负时，右移。舍入模式由round_mode确定。
sub_shift数据相减后，以INT64为中间结果保存，然后在INT64基础上做一次舍入的算数移位操作；结果支持饱和处理。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* shift：int型，表示移位的位数。
* round_mode：String型，表示舍入模式。默认值为'half_away_from_zero'。取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。
* is_saturate：Bool型，表示结果是否需要饱和处理，默认饱和处理。
* out_dtype：String或None，表示输出Tensor的数据类型，取默认值时则和tensor_i0的类型一致。可选参数为'int8'/'int16'/'int32'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor。
该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。

## 处理器支持

* BM1688：输入数据类型可以是INT32/UINT32/INT16/UINT6/INT8/UINT8。
* BM1684X：输入数据类型可以是INT32/UINT32/INT16/UINT6/INT8/UINT8。

# mul_shift

## 接口定义

```python
def mul_shift(tensor_i0: Union[Tensor, Scalar, int],
              tensor_i1: Union[Tensor, Scalar, int],
              shift: int,
              out_dtype: str,
              round_mode: str='half_away_from_zero',
              is_saturate: bool=True,
              out_name: str = None):
    #pass
```

## 功能描述

运算公式 `tensor_o = (tensor_i0 * tensor_i1) << shift`。
张量和张量的按元素相减后再舍入算术移shift位，shift为正时，左移，shift为负时，右移。舍入模式由round_mode确定。
mul_shift数据相乘后，以INT64为中间结果保存，然后在INT64基础上做一次舍入的算数移位操作；
结果支持饱和处理；当tensor_i0、tensor_i1为signed，且tensor_o为unsigned时，结果必须饱和处理。
该操作支持广播。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型或Scalar、int，表示输入左操作Tensor或Scalar。
* tensor_i1：Tensor类型或Scalar、int，表示输入右操作Tensor或Scalar。tensor_i0和tensor_i1至少有一个是Tensor。
* shift：int型，表示移位的位数。
* round_mode：String型，表示舍入模式。默认值为'half_away_from_zero'。取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。
* is_saturate：Bool型，表示结果是否需要饱和处理，默认饱和处理。
* out_dtype：String或None，表示输出Tensor的数据类型，取默认值时则和tensor_i0的类型一致。可选参数为'int8'/'uint8'/'int16'/'uint16'/'int32'/'uint32'。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor。
该Tensor的数据类型由out_dtype指定，或与输入数据类型一致。

## 处理器支持

# copy

## 接口定义

```python
def copy(input: Tensor, out_name: str = None):
    #pass
```

## 功能描述

copy，将输入数据复制到输出Tensor中。该操作属于**全局操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# clamp

## 接口定义

```python
def clamp(input: Tensor, min: float, max: float, out_name: str = None):
    #pass
```

## 功能描述

将输入Tensor中所有元素的值都限定在设置的最大最小值范围内，大于最大值则截断为最大值，小于最小值则截断为最小值。要求所有输入Tensor及Scalar的dtype一致。该操作属于**本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor。
* min：float类型，表示截断的下限。
* max：float类型，表示截断的上限。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# Element-wise Compare Operator

## gt

### 接口定义

```python
def gt(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素大于比较运算。`tensor_o = tensor_i0 > tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

## lt

### 接口定义

```python
def lt(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素小于比较运算。`tensor_o = tensor_i0 < tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

## ge

### 接口定义

```python
def ge(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素大于等于比较运算。`tensor_o = tensor_i0 >= tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

## le

### 接口定义

```python
def le(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素小于等于比较运算。`tensor_o = tensor_i0 <= tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

## eq

### 接口定义

```python
def eq(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素等于比较运算。`tensor_o = tensor_i0 == tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

## ne

### 接口定义

```python
def ne(tensor_i0: Tensor,
      tensor_i1: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

### 功能描述

张量和张量的按元素不等于比较运算。`tensor_o = tensor_i0 != tensor_i1 ? 1 : 0`。该操作支持广播。tensor_i0或者tensor_i1可以被指定为COEFF_TENSOR。该操作属于**本地操作**。

### 参数说明

* tensor_i0：Tensor类型，表示输入左操作Tensor。
* tensor_i1：Tensor类型，表示输入右操作Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的scale。tensor_i0与tensor_i1的scale必须一致。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为3，分别为tensor_i0，tensor_i1，output的zero_point。tensor_i0与tensor_i1的zero_point必须一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。tensor_i0与tensor_i1的数据类型必须一致。

# gts

## 接口定义

```python
def gts(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素大于比较运算。`tensor_o = tensor_i0 > scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# lts

## 接口定义

```python
def lts(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素小于比较运算。`tensor_o = tensor_i0 < scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# ges

## 接口定义

```python
def ges(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素大于等于比较运算。`tensor_o = tensor_i0 >= scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# les

## 接口定义

```python
def les(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素小于等于比较运算。`tensor_o = tensor_i0 <= scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# eqs

## 接口定义

```python
def eqs(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素等于比较运算。`tensor_o = tensor_i0 == scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# nes

## 接口定义

```python
def nes(tensor_i0: Tensor,
      scalar_i1: Union[Scalar, int, float],
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

张量和标量的按元素不等于比较运算。`tensor_o = tensor_i0 != scalar_i1 ? 1 : 0`。
该操作属于 **本地操作**。

## 参数说明

* tensor_i0：Tensor类型，表示输入左操作数。
* scalar_i1：Scalar，int或float类型，表示输入右操作数。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。scalar_i1数据类型为FLOAT32。

# Activation Operator

## relu

### 接口定义

```python
def relu(input: Tensor, out_name: str = None):
    #pass
```

### 功能描述

relu激活函数，逐元素实现功能 `y = max(0, x)`。
该操作属于 **本地操作**。

### 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。若输入是quantized类型，输出的scale与zero_point与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

## prelu

### 接口定义

```python
def prelu(input: Tensor, slope : Tensor, out_name: str = None):
    #pass
```

### 功能描述

prelu激活函数，逐元素实现功能 `y = { x if x>0; x*slope if x<=0 }`。
该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入Tensor。
* slope：Tensor类型，表示slope Tensor。仅支持slope为coeff Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# leaky_relu

## 接口定义

```python
def leaky_relu(input: Tensor,
              negative_slope: float = 0.01,
              out_name: str = None,
              round_mode: str = "half_away_from_zero"):
    #pass
```

## 功能描述

leaky_relu激活函数，逐元素实现功能 $y =\begin{cases}x\quad x>0\\x*params_[0] \quad x<=0\\\end{cases}$。
该操作属于 **本地操作**。

## 参数说明

* input：Tensor类型，表示输入Tensor。
* negative_slope：float类型，表示输入的负斜率，默认值为0.01。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。若输入是quantized类型，输出的scale与zero_point与输入一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# abs

## 接口定义

```python
def abs(input: Tensor, out_name: str = None):
    #pass
```

## 功能描述

abs绝对值激活函数，逐元素实现功能 $y = \left | x \right |$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。若输入是quantized类型，输出的scale与zero_point与输入一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# ln

## 接口定义

```python
def ln(input: Tensor,
      scale: List[float] = None,
      zero_point: List[int] = None,
      out_name: str = None):
    #pass
```

## 功能描述

ln激活函数，逐元素实现功能 $y = log(x)$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# ceil

## 接口定义

```python
def ceil(input: Tensor,
        scale: List[float] = None,
        zero_point: List[int] = None,
        out_name: str = None):
    #pass
```

## 功能描述

ceil向上取整激活函数，逐元素实现功能 $y = \left \lfloor x \right \rfloor$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# floor

## 接口定义

```python
def floor(input: Tensor,
         scale: List[float] = None,
         zero_point: List[int] = None,
         out_name: str = None):
    #pass
```

## 功能描述

floor向下取整激活函数，逐元素实现功能 $y = \left \lceil x \right \rceil$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# round

## 接口定义

```python
def round(input: Tensor, out_name: str = None):
    #pass
```

## 功能描述

round四舍五入整激活函数，逐元素实现功能 $y = round(x)$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# sin

## 接口定义

```python
def sin(input: Tensor,
       scale: List[float] = None,
       zero_point: List[int] = None,
       out_name: str = None):
    #pass
```

## 功能描述

sin正弦激活函数，逐元素实现功能 $y = sin(x)$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# cos

## 接口定义

```python
def cos(input: Tensor,
       scale: List[float] = None,
       zero_point: List[int] = None,
       out_name: str = None):
    #pass
```

## 功能描述

cos余弦激活函数，逐元素实现功能 $y = cos(x)$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# exp

## 接口定义

```python
def exp(input: Tensor,
       scale: List[float] = None,
       zero_point: List[int] = None,
       out_name: str = None):
    #pass
```

## 功能描述

exp指数激活函数，逐元素实现功能 $y = e^{x}$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# tanh

## 接口定义

```python
def tanh(input: Tensor,
        scale: List[float] = None,
        zero_point: List[int] = None,
        out_name: str = None,
        round_mode: str = "half_away_from_zero"):
    #pass
```

## 功能描述

tanh双曲正切激活函数，逐元素实现功能 $y=tanh(x)=\frac{e^{x}-e^{-x}}{e^{x}+e^{-x}}$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# sigmoid

## 接口定义

```python
def sigmoid(input: Tensor,
           scale: List[float] = None,
           zero_point: List[int] = None,
           out_name: str = None,
           round_mode: str = "half_away_from_zero"):
    #pass
```

## 功能描述

sigmoid激活函数，逐元素实现功能 $y = 1 / (1 + e^{-x})$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# log_sigmoid

## 接口定义

```python
def log_sigmoid(input: Tensor,
               scale: List[float] = None,
               zero_point: List[int] = None,
               out_name: str = None):
    #pass
```

## 功能描述

log_sigmoid激活函数，逐元素实现功能 $y = log(1 / (1 + e^{-x}))$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# elu

## 接口定义

```python
def elu(input: Tensor,
       scale: List[float] = None,
       zero_point: List[int] = None,
       out_name: str = None):
    #pass
```

## 功能描述

elu激活函数，逐元素实现功能 $y =  \begin{cases}x\quad x>=0\\e^{x}-1\quad x<0\\\end{cases}$。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。


* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

square
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def square(input: Tensor,
                scale: List[float]=None,
                zero_point: List[int]=None,
                out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
square平方激活函数，逐元素实现功能 :math:`y = \square{x}`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

sqrt
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def sqrt(input: Tensor,
            scale: List[float]=None,
            zero_point: List[int]=None,
            out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
sqrt平方根激活函数，逐元素实现功能 :math:`y = \sqrt{x}`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

rsqrt
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def rsqrt(input: Tensor,
                scale: List[float]=None,
                zero_point: List[int]=None,
                out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
rsqrt平方根取反激活函数，逐元素实现功能 :math:`y = 1 / (sqrt{x})`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

silu
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def silu(input: Tensor,
            scale: List[float]=None,
            zero_point: List[int]=None,
            out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
silu激活函数，逐元素实现功能 :math:`y = x * (1 / (1 + e^{-x}))`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* input：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

swish
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def swish(input: Tensor,
              beta: float,
              scale: List[float]=None,
              zero_point: List[int]=None,
              round_mode: str = "half_away_from_zero",
              out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
swish激活函数，逐元素实现功能 :math:`y = x * (1 / (1 + e^{-x * beta}))`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* input：Tensor类型，表示输入Tensor。
* beta: Scalar或float类型，表示beta值。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* round_mode：string型，表示舍入模式。默认为“half_away_from_zero”。round_mode取值范围为“half_away_from_zero”，“half_to_even”，“towards_zero”，“down”，“up”。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。


erf
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def erf(input: Tensor,
            scale: List[float]=None,
            zero_point: List[int]=None,
            out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
erf激活函数，对于输入输出Tensor对应位置的元素x和y，逐元素实现功能 :math:`y = \frac{2}{\sqrt{\pi }}\int_{0}^{x}e^{-\eta ^{2}}d\eta`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

tan
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def tan(input: Tensor, out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
tan正切激活函数，逐元素实现功能 :math:`y = tan(x)`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。


softmax
:::::::::::::::::::::::::::::::::::::::::::::::::

接口定义
""""""""""""""""""""""""""""""""""""""""""""""

    .. code-block:: python

      def softmax(input: Tensor,
                axis: int,
                out_name: str = None):
          #pass

功能描述
""""""""""""""""""""""""""""""""""""""""""""""
softmax激活函数，实现功能 :math:`tensor\_o = exp(tensor\_i)/sum(exp(tensor\_i),axis)`。
该操作属于 **本地操作** 。

参数说明
""""""""""""""""""""""""""""""""""""""""""""""
* tensor：Tensor类型，表示输入Tensor。
* axis：int型，表示进行运算的轴。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

返回值
""""""""""""""""""""""""""""""""""""""""""""""
返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

处理器支持
""""""""""""""""""""""""""""""""""""""""""""""
* BM1688：输入数据类型可以是FLOAT32/FLOAT16。

# softmax_int

## 接口定义

```python
def softmax_int(input: Tensor,
              axis: int,
              scale: List[float],
              zero_point: List[int] = None,
              out_name: str = None,
              round_mode : str="half_away_from_zero"):
    #pass
```

## 功能描述

softmax定点运算。可参考各框架下的softmax定义。

```
for i in range(256)
  table[i] = exp(scale[0] * i)

for n,h,w in N,H,W
  max_val = max(input[n,c,h,w] for c in C)
  sum_exp = sum(table[max_val - input[n,c,h,w]] for c in C)
  for c in C
    prob = table[max_val - input[n,c,h,w]] / sum_exp
    output[n,c,h,w] = saturate(int(round(prob * scale[1])) + zero_point[1]),    其中saturate饱和到output数据类型
```

其中table表示查表。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* axis：int型，表示进行运算的轴。
* scale：List[float]型，表示输入和输出的量化系数。长度必须时2。
* zero_point：List[int]型或None型，表示输入和输出偏移，长度与scale一致。如果为None，则取[0, 0]。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是INT8/UINT8。
* BM1684X：输入数据类型可以是INT8/UINT8。

# mish

## 接口定义

```python
def mish(input: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

mish激活函数，逐元素实现功能 `y = x * tanh(ln(1 + e^{x}))`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# hswish

## 接口定义

```python
def hswish(input: Tensor,
          scale: List[float]=None,
          zero_point: List[int]=None,
          out_name: str = None):
    #pass
```

## 功能描述

hswish激活函数，逐元素实现功能 `y = 0 (x<=-3); x (x>=3); x*((x+3)/6) (-3<x<3)`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# arccos

## 接口定义

```python
def arccos(input: Tensor, out_name: str = None):
    #pass
```

## 功能描述

arccos反余弦激活函数，逐元素实现功能 `y = arccos(x)`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。

# arctanh

## 接口定义

```python
def arctanh(input: Tensor, out_name: str = None):
    #pass
```

## 功能描述

arctanh反双曲正切激活函数，逐元素实现功能 `y = arctanh(x)=1/2 * ln((1+x)/(1-x))`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32。FLOAT16数据会自动转换为FLOAT32。

# sinh

## 接口定义

```python
def sinh(input: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

sinh双曲正弦激活函数，逐元素实现功能 `y = sinh(x)=(e^x-e^{-x})/2`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# cosh

## 接口定义

```python
def cosh(input: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

cosh双曲余弦激活函数，逐元素实现功能 `y = cosh(x)=(e^x+e^{-x})/2`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# sign

## 接口定义

```python
def sign(input: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None):
    #pass
```

## 功能描述

sign激活函数，逐元素实现功能 `y = 1 (x>0); 0 (x=0); -1 (x<0)`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# gelu

## 接口定义

```python
def gelu(input: Tensor,
      scale: List[float]=None,
      zero_point: List[int]=None,
      out_name: str = None,
      round_mode : str="half_away_from_zero"):
    #pass
```

## 功能描述

gelu激活函数，逐元素实现功能 `y = x* 0.5 * (1+ erf(x/√2))`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# hsigmoid

## 接口定义

```python
def hsigmoid(input: Tensor,
          scale: List[float]=None,
          zero_point: List[int]=None,
          out_name: str = None):
    #pass
```

## 功能描述

hsigmoid激活函数，逐元素实现功能 `y = min(1, max(0, x/6 + 0.5))`。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入Tensor。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的scale。
* zero_point：List[int]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为tensor_i0，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的形状和数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32/INT8/UINT8。FLOAT16数据会自动转换为FLOAT32。

# Data Arrange Operator

## permute

### 接口定义

```python
def permute(input:tensor,
            order:Union[List[int], Tuple[int]],
            out_name:str=None):
    #pass
```

### 功能描述

根据置换参数对输入Tensor进行重排。
例如：输入shape为（6，7，8，9），置换参数order为（1，3，2，0），则输出的shape为（7，9，8，6）。
该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入操作Tensor。
* order：List[int]或Tuple[int]型，表示置换参数。要求order长度和tensor维度一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

## tile

### 接口定义

```python
def tile(tensor_i: Tensor,
         reps: Union[List[int], Tuple[int]],
         out_name: str = None):
    #pass
```

### 功能描述

在指定的维度重复复制数据。
该操作属于 **受限本地操作**。

### 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* reps：List[int]或Tuple[int]型，表示每个维度的复制份数。要求order长度和tensor维度一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

## broadcast

### 接口定义

```python
def broadcast(input: Tensor,
              reps: Union[List[int], Tuple[int]],
              out_name: str = None):
    #pass
```

### 功能描述

在指定的维度重复复制数据。
该操作属于 **受限本地操作**。

### 参数说明

* input：Tensor类型，表示输入操作Tensor。
* reps：List[int]或Tuple[int]型，表示每个维度的复制份数。要求order长度和tensor维度一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8/INT16/UINT16。

# concat

## 接口定义

```python
def concat(inputs: List[Tensor],
           scales: Optional[Union[List[float],List[int]]] = None,
           zero_points: Optional[List[int]] = None,
           axis: int = 0,
           out_name: str = None,
           dtype="float32",
           round_mode: str="half_away_from_zero"):
    #pass
```

## 功能描述

对多个张量在指定的轴上进行拼接，以及支持不同量纲输入、输出。

该操作属于**受限本地操作**。

## 参数说明

* inputs：List[Tensor]类型，存放多个Tensor，所有的Tensor要求数据格式一致并具有相同的shape维度数，且除了待拼接的那一维，shape其他维度的值应该相等。
* scales：Optional[Union[List[float],List[int]]]类型，存放多个输入和一个输出scale，最后一个为输出的scale。
* zero_points：Optional[List[int]]类型，存放多个输入和一个输出的zero_point，最后一个为输出的zero_point。
* axis：int型，表示进行拼接运算的轴。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* dtype：string类型，默认是"float32"。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

# split

## 接口定义

```python
def split(input:tensor,
          axis:int=0,
          num:int=1,
          size:Union[List[int], Tuple[int]]=None,
          out_name:str=None):
    #pass
```

## 功能描述

对输入Tensor在指定的轴上拆成多个Tensor。如果size不为空，则由分裂后的大小由size决定，反之则会根据tensor尺寸和num计算平均分裂后的大小。

该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示将要进行切分的Tensor。
* axis：int型，表示进行切分运算的轴。
* num：int型，表示切分的份数；
* size：List[int]或Tuple[int]型，非平均分裂时，指定每一份大小，平均分裂时，设置为空即可。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个List[Tensor]，其中每个Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

# pad

## 接口定义

```python
def pad(input:tensor,
        method='constant',
        value:Union[Scalar, Variable, None]=None,
        padding:Union[List[int], Tuple[int], None]=None,
        out_name:str=None):
    #pass
```

## 功能描述

对输入Tensor进行填充。

该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示将要进行填充的Tensor。
* method：string类型，表示填充方法，可选方法"constant"，"reflect"，"symmetric"，"edge"。
* value：Saclar或Variable型或None，表示待填充的数值。数据类型和tensor一致；
* padding：List[int]或Tuple[int]型或None。padding为None时使用一个长度为2*len(tensor.shape)的全0 list。例如，一个hw的二维Tensor对应的padding是 [h_top, w_left, h_bottom, w_right]。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

# repeat

## 接口定义

```python
def repeat(tensor_i:Tensor,
           reps:Union[List[int], Tuple[int]],
           out_name:str=None):
    #pass
```

## 功能描述

在指定的维度重复复制数据。功能同tile。
该操作属于**受限本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* reps：List[int]或Tuple[int]型，表示每个维度的复制份数。要求order长度和tensor维度一致。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

# extract

## 接口定义

```python
def extract(input: Tensor,
            start: Union[List[int], Tuple[int]] = None,
            end: Union[List[int], Tuple[int]] = None,
            stride: Union[List[int], Tuple[int]] = None,
            out_name: str = None)
```

## 功能描述

对输入tensor进行切片提取操作。

## 参数说明

* input：Tensor类型，表示输入张量。
* start：整数的列表或者元组或None，表示切片的起始位置，为None时表示全为0。
* end：整数的列表或者元组或None，表示切片的终止位置，为None时表示输出张量的形状。
* stride：整数的列表或者元组或None，表示切片的步长，为None时表示全为1。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，数据类型与输入Tensor的数据类型相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8/INT16/UINT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8/INT16/UINT16。

# roll

## 接口定义

```python
def roll(input:Tensor,
         shifts: Union[int, List[int], Tuple[int]],
         dims: Union[int, List[int], Tuple[int]] = None,
         out_name:str=None):
    #pass
```

## 功能描述

沿给定维度滚动输入张量。移出最后一个位置的元素将在第一个位置重新引入。如果 dims 为 None，则张量将在滚动之前展平，然后恢复到原始形状。
该操作属于**本地操作**。

## 参数说明

* input：Tensor类型，表示输入操作Tensor。
* shifts：int，List[int]或Tuple[int]型，张量元素移动的位数。如果 shifts 是元组/列表，则 dims 必须是相同大小的元组/列表，并且每个维度将按相应的值滚动。
* dims：int，List[int]，Tuple[int]型或None，滚动的轴。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8/INT16/UINT16。

# Sort Operator

## arg

### 接口定义

```python
def arg(input: Tensor,
        method: str = "max",
        axis: int = 0,
        keep_dims: bool = True,
        out_name: str = None):
    #pass
```

### 功能描述
对输入tensor的指定的axis求最大或最小值，输出对应的index，并将该axis的dim设置为1。该操作属于**受限本地操作**。

### 参数说明
- input：Tensor类型，表示输入的操作Tensor
- method：string类型，表示操作的方法，可选'max'，'min'
- axis：int型，表示指定的轴。默认值为0
- keep_dims：bool型，表示是否保留运算后的指定轴，默认值为True表示保留（此时该轴长度为1）
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回两个Tensor，第一个Tensor表示indices，类型为int32；第二个Tensor表示values，类型会和input的类型一致。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32
- BM1684X：输入数据类型可以是FLOAT32

## topk

### 接口定义

```python
def topk(input: Tensor,
         axis: int,
         k: int,
         out_name: str = None):
```

### 功能描述
按某个轴排序后前K个数。

### 参数说明
- input：Tensor类型，表示输入Tensor
- axis：int型，表示排序所使用的轴
- k：int型，表示沿着轴排序靠前的数的个数
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回两个Tensor，第一个Tensor表示前几个数，其数据类型与输入类型相同，第二个Tensor表示前几个数在输入中的索引。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32
- BM1684X：输入数据类型可以是FLOAT32

## sort

### 接口定义

```python
def sort(input: Tensor,
         axis: int = -1,
         descending : bool = True,
         out_name = None)
```

### 功能描述
沿某个轴的输入张量进行排序，输出排序后的张量以及该张量的数据在输入张量中的索引。

### 参数说明
- input：Tensor类型，表示输入张量
- axis：int类型，表示指定的轴（暂时只支持axis==-1）
- descending：bool类型，表示是否按从大到小排列
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回两个Tensor，第一个张量的数据类型与输入张量的数据类型相同，第二个张量的数据类型为INT32。

### 处理器支持
- BM1688：输入张量的数据类型可以是FLOAT32/FLOAT16
- BM1684X：输入张量的数据类型可以是FLOAT32/FLOAT16

## argsort

### 接口定义

```python
def argsort(input: Tensor,
            axis: int = -1,
            descending : bool = True,
            out_name : str = None)
```

### 功能描述
沿某个轴的输入张量进行排序，输出排序后的张量的数据在输入张量中的索引。

### 参数说明
- input：Tensor类型，表示输入张量
- axis：int类型，表示指定的轴（暂时只支持axis==-1）
- descending：bool类型，表示是否按从大到小排列
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor，其数据类型为INT32。

### 处理器支持
- BM1688：输入张量的数据类型可以是FLOAT32/FLOAT16
- BM1684X：输入张量的数据类型可以是FLOAT32/FLOAT16

## sort_by_key

### 接口定义

```python
def sort_by_key(input: Tensor,
                key: Tensor,
                axis: int = -1,
                descending : bool = True,
                out_name = None)
```

### 功能描述
沿某个轴按键对输入张量进行排序，输出排序后的张量以及相应的键。

### 参数说明
- input：Tensor类型，表示输入
- key：Tensor类型，表示键
- axis：int类型，表示指定的轴
- descending：bool类型，表示是否按从大到小排列
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回两个Tensor，第一个张量的数据类型与输入的数据类型相同，第二个张量的数据类型与键的数据类型相同。

### 处理器支持
- BM1688：输入和键的数据类型可以是FLOAT32/FLOAT16
- BM1684X：输入和键的数据类型可以是FLOAT32/FLOAT16

# Shape About Operator

## squeeze

### 接口定义

```python
def squeeze(tensor_i: Tensor, axis: Union[Tuple[int], List[int]], out_name: str = None):
    #pass
```

### 功能描述
降维操作，去掉输入shape指定的某些1维的轴，如果没有指定轴(axis)则去除所有是1维的轴。该操作属于**本地操作**。

### 参数说明
- tensor_i：Tensor类型，表示输入操作Tensor
- axis：List[int]或Tuple[int]型，表示指定的轴
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8
- BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8

## reshape

### 接口定义

```python
def reshape(tensor: Tensor, new_shape: Union[Tuple[int], List[int], Tensor], out_name: str = None):
    #pass
```

### 功能描述
对输入tensor做reshape的操作。该操作属于**本地操作**。

### 参数说明
- tensor：Tensor类型，表示输入操作Tensor
- new_shape：List[int]或Tuple[int]或Tensor类型，表示转化后的形状
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8
- BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8

## shape_fetch

### 接口定义

```python
def shape_fetch(tensor_i: Tensor,
          begin_axis: int = None,
          end_axis: int = None,
          step: int = 1,
          out_name: str = None):
    #pass
```

### 功能描述
对输入tensor取指定轴(axis)之间的shape信息。该操作属于**本地操作**。

### 参数说明
- tensor_i：Tensor类型，表示输入操作Tensor
- begin_axis：int型，表示指定开始的轴
- end_axis：int型，表示指定结束的轴
- step：int型，表示步长
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor，该Tensor的数据类型为INT32。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8
- BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8

## unsqueeze

### 接口定义

```python
def unsqueeze(input: Tensor, axes: List[int] = [1,2], out_name: str = None):
    #pass
```

### 功能描述
增维操作。在axis指定的位置增加1。该操作属于**本地操作**。

### 参数说明
- input：Tensor类型，表示输入操作Tensor
- axis：int型，表示指定的轴，设tensor_i的维度长度是D，则axis范围[-D,D-1)
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8
- BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8

# Quant Operator

## requant_fp_to_int

### 接口定义

```python
def requant_fp_to_int(tensor_i,
                      scale,
                      offset,
                      requant_mode, #unused
                      out_dtype,
                      out_name = None,
                      round_mode='half_away_from_zero'):
```

### 功能描述
对输入tensor进行量化处理。

该操作对应的计算式为：

```
output = saturate(int(round(input * scale)) + offset)，
其中saturate为饱和到output的数据类型
```

该操作属于**本地操作**。

### 参数说明
- tensor_i：Tensor类型，表示输入Tensor，3-5维
- scale：List[float]型或float型，表示量化系数
- offset：List[int]型或int型；表示输出偏移
- requant_mode：int型，表示量化模式。废弃
- round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"（TODO）
- out_dtype：string类型，表示输入Tensor的类型。数据类型可以是"int16"/"uint16"/"int8"/"uint8"
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

### 返回值
返回一个Tensor。该Tensor的数据类型由out_dtype确定。

### 处理器支持
- BM1688：输入数据类型可以是FLOAT32
- BM1684X：输入数据类型可以是FLOAT32

## requant_fp

### 接口定义

```python
def requant_fp(tensor_i: Tensor,
       scale: Union[float, List[float]],
       offset: Union[float, List[float]],
       out_dtype: str,
       out_name: str=None,
       round_mode: str='half_away_from_zero',
       first_round_mode: str='half_away_from_zero'):
```

### 功能描述
对输入tensor进行量化处理。

该操作对应的计算式为：

```
output = saturate(int(round(float(input) * scale + offset)))，
其中saturate为饱和到output的数据类型
```

该操作属于**本地操作**。

### 参数说明
- tensor_i：Tensor类型，表示输入Tensor，3-5维
- scale：List[float]型或float型，表示量化系数
- offset：List[int]型或int型。表示输出偏移
- out_dtype：string类型，表示输入Tensor的类型。数据类型可以是"int16"/"uint16"/"int8"/"uint8"
- out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称
- round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"
- first_round_mode：string型，表示之前量化tensor_i时使用的舍入模式。默认为"half_away_from_zero"。first_round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"

# requant_int

对输入tensor进行量化处理。

```python
def requant_int(tensor_i: Tensor,
        mul: Union[int, List[int]],
        shift: Union[int, List[int]],
        offset: Union[int, List[int]],
        requant_mode: int,
        out_dtype: str="int8",
        out_name=None,
        round_mode='half_away_from_zero', rq_axis:int = 1, fuse_rq_to_matmul: bool = False):
```

## 功能描述

对输入tensor进行量化处理。

当requant_mode==0时，该操作对应的计算式为：

```
output = shift > 0 ? (input << shift) : input
output = saturate((output * multiplier) >> 31),     其中 >> 为round_half_up, saturate饱和到INT32
output = shift < 0 ? (output >> -shift) : output,   其中 >> 的舍入模式由round_mode确定。
output = saturate(output + offset),                 其中saturate饱和到output数据类型
```

* BM1684X：input数据类型可以是INT32, output数据类型可以是INT32/INT16/INT8
* BM1688：input数据类型可以是INT32, output数据类型可以是INT32/INT16/INT8

当requant_mode==1时，该操作对应的计算式为：

```
output = saturate((input * multiplier) >> 31)，     其中 >> 为round_half_up, saturate饱和到INT32
output = saturate(output >> -shift + offset)，      其中 >> 的舍入模式由round_mode确定, saturate饱和到output数据类型
```

* BM1684X：input数据类型可以是INT32, output数据类型可以是INT32/INT16/INT8
* BM1688：input数据类型可以是INT32, output数据类型可以是INT32/INT16/INT8

当requant_mode==2时，该操作对应的计算式为(建议使用)：

```
output = input * multiplier
output = shift > 0 ? (output << shift) : (output >> -shift),    其中 >> 的舍入模式由round_mode确定
output = saturate(output + offset),                             其中 saturate饱和到output数据类型
```

* BM1684X：input数据类型可以是INT32/INT16/UINT16, output数据类型可以是INT16/UINT16/INT8/UINT8
* BM1688：input数据类型可以是INT32/INT16/UINT16, output数据类型可以是INT16/UINT16/INT8/UINT8

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，3-5维。
* mul：List[int]型或int型，表示量化乘子系数。
* shift:List[int]型或int型，表示量化移位系数。右移为负，左移为正。
* offset：List[int]型或int型，表示输出偏移。
* requant_mode：int型，表示量化模式。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero", 范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。
* out_dtype：string类型或None，表示输出Tensor的类型。None代表输出数据类型为"int8"
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* rq_axis：int型，表示在rq_axis维度做requant。
* fuse_rq_to_matmul：bool类型，表示是否将requant 融合到matmul,默认是False。

## 返回值

返回一个Tensor。该Tensor的数据类型由out_dtype确定。

## 处理器支持

* BM1684X
* BM1688

# dequant_int_to_fp

## 接口定义

```python
def dequant_int_to_fp(tensor_i: Tensor,
              scale: Union[float, List[float]],
              offset: Union[int, List[int], float, List[float]],
              out_dtype: str="float32",
              out_name: str=None,
              round_mode: str='half_away_from_zero'):
```

## 功能描述

对输入tensor进行反量化处理。

该操作对应的计算式为：

```
output = (input - offset) * scale
```

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，3-5维。
* scale：List[float]型或float型，表示量化系数。
* offset：List[int]型或int型，表示输出偏移。
* out_dtype：string类型，表示输出Tensor的类型。默认输出数据类型为"float32"。当输入数据类型为int8/uint8时，取值范围为"float16"，"float32"。当输入类型为int16/uint16时，输出类型只能为"float32"。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：string型，表示舍入模式。默认为"half_away_from_zero"。round_mode取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。(TODO)

## 返回值

返回一个Tensor。该Tensor的数据类型由out_dtype指定。

## 处理器支持

* BM1684X：input数据类型可以是INT16/UINT16/INT8/UINT8。

# dequant_int

## 接口定义

```python
def dequant_int(tensor_i: Tensor,
        mul: Union[int, List[int]],
        shift: Union[int, List[int]],
        offset: Union[int, List[int]],
        lshift: int,
        requant_mode: int,
        out_dtype: str="int8",
        out_name=None,
        round_mode='half_up'):
```

## 功能描述

对输入tensor进行反量化处理。

当requant_mode==0时，该操作对应的计算式为：

```
output = (intpu - offset) * multiplier
output = saturate(output >> -shift),                其中 >> 的舍入模式由round_mode确定, saturate饱和到INT32
```

* BM1684X：input数据类型可以是INT16/UINT16/INT8/UINT8, output数据类型可以是INT32/INT16/UINT16

当requant_mode==1时，该操作对应的计算式为：

```
output = ((input - offset) * multiplier) << lshift
output = saturate(output >> 31)，                   其中 >> 为round_half_up, saturate饱和到INT32
output = saturate(output >> -shift)，               其中 >> 的舍入模式由round_mode确定, saturate饱和到output数据类型
```

* BM1684X：input数据类型可以是INT16/UINT16/INT8/UINT8, output数据类型可以是INT32/INT16/INT8

该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入Tensor，3-5维。
* mul：List[int]型或int型，表示量化乘子系数。
* shift:List[int]型或int型，表示量化移位系数。右移为负，左移为正。
* offset：List[int]型或int型，表示输出偏移。
* lshift：int型，表示左移位系数。
* requant_mode：int型，表示量化模式。取值为0和1，0表示"Normal"，1表示"TFLite"。
* round_mode：string型，表示舍入模式。默认为"half_up", 范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。
* out_dtype：string类型，表示输入Tensor的类型。默认为"int8"。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor。该Tensor的数据类型由out_dtype确定。

## 处理器支持

* BM1684X

# cast

## 接口定义

```python
def cast(tensor_i: Tensor,
   out_dtype: str = 'float32',
   out_name: str = None,
   round_mode: str = 'half_away_from_zero'):
```

## 功能描述

将输入张量 `tensor_i` 转换为指定的数据类型 `out_dtype`，并根据指定的舍入模式 `round_mode` 对数据进行舍入。
注意本算子不能单独使用，必须配合其他算子。

## 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* out_dtype: str = 'float32'，输出张量的数据类型，默认为 `float32`。
* out_name: str = None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode: str = 'half_away_from_zero', 舍入模式，默认为 `half_away_from_zero`。取值范围为"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"。注意，此函数round_mode不支持"half_up"与"half_down"。

## 返回值

返回一个Tensor，该Tensor的数据类型由输入的out_dtype决定。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/UINT8/INT8。

# Up/Down Scaling Operator

## maxpool2d

### 接口定义

```python
def maxpool2d(input: Tensor,
              kernel: Union[List[int],Tuple[int],None] = None,
              stride: Union[List[int],Tuple[int],None] = None,
              pad:    Union[List[int],Tuple[int],None] = None,
              ceil_mode: bool = False,
              scale: List[float] = None,
              zero_point: List[int] = None,
              out_name: str = None,
              round_mode: str="half_away_from_zero"):
    #pass
```

### 功能描述

对输入Tensor进行Max池化处理。请参考各大框架下的池化操作。
该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入操作Tensor。
* kernel：List[int]或Tuple[int]型或None，输入None表示使用global_pooling，不为None时要求该参数长度为2。
* stride：List[int]或Tuple[int]型或None，表示步长尺寸，输入None使用默认值[1,1]，不为None时要求该参数长度为2。
* pad：List[int]或Tuple[int]型或None，表示填充尺寸，输入None使用默认值[0,0,0,0]，不为None时要求该参数长度为4。
* ceil：bool型，表示计算output shape时是否向上取整。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为input，output的scale。
* zero_point：List[int]类型或None，偏移参数。取None代表非量化计算。若为List，长度为2，分别为input，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：String型，当输入输出Tensor为量化时，表示舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。

### 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

## maxpool2d_with_mask

### 接口定义

```python
def maxpool2d_with_mask(input: Tensor,
                        kernel: Union[List[int],Tuple[int],None] = None,
                        stride: Union[List[int],Tuple[int],None] = None,
                        pad:    Union[List[int],Tuple[int],None] = None,
                        ceil_mode: bool = False,
                        out_name: str = None,
                        mask_name: str = None):
    #pass
```

### 功能描述

对输入Tensor进行Max池化处理，并输出其mask index。请参考各大框架下的池化操作。
该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入操作Tensor。
* kernel：List[int]或Tuple[int]型或None，输入None表示使用global_pooling，不为None时要求该参数长度为2。
* pad：List[int]或Tuple[int]型或None，表示填充尺寸，输入None使用默认值[0,0,0,0]，不为None时要求该参数长度为4。
* stride：List[int]或Tuple[int]型或None，表示步长尺寸，输入None使用默认值[1,1]，不为None时要求该参数长度为2。
* ceil：bool型，表示计算output shape时是否向上取整。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* mask_name：string类型或None，表示输出Mask的名称，为None时内部会自动产生名称。

### 返回值

返回两个Tensor，一个Tensor的数据类型与输入Tensor相同。另一个返回一个坐标Tensor，该Tensor是记录使用比较运算池化时所选择的坐标。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32。

## maxpool3d

# maxpool3d

## 接口定义

```python
def maxpool3d(input: Tensor,
              kernel: Union[List[int],int,Tuple[int, ...]] = None,
              stride: Union[List[int],int,Tuple[int, ...]] = None,
              pad:    Union[List[int],int,Tuple[int, ...]] = None,
              ceil_mode: bool = False,
              scale: List[float] = None,
              zero_point: List[int] = None,
              out_name: str = None,
              round_mode : str="half_away_from_zero"):
    #pass
```

## 功能描述

对输入Tensor进行Max池化处理。请参考各大框架下的池化操作。
该操作属于 **本地操作**。

## 参数说明

* input：Tensor类型，表示输入操作Tensor。
* kernel：List[int]或Tuple[int]型或int或None，输入None表示使用global_pooling，不为None时若输入单个整数，表示在3个维度上的kernel大小相同，若输入List或Tuple，要求该参数长度为3。
* stride：List[int]或Tuple[int]型或int或None，表示步长尺寸，输入None使用默认值[1,1,1]，不为None时若输入单个整数，表示在3个维度上的stride大小相同，若输入List或Tuple，要求该参数长度为3。
* pad：List[int]或Tuple[int]型或int或None，表示填充尺寸，输入None使用默认值[0,0,0,0,0,0]，不为None时若输入单个整数，表示在3个维度上的pad大小相同，若输入List或Tuple，要求该参数长度为6。
* ceil_mode：bool型，表示计算output shape时是否向上取整。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为input，output的scale。
* zero_point：List[int]类型或None，偏移参数。取None代表非量化计算。若为List，长度为2，分别为input，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* round_mode：String型，当输入输出Tensor为量化时，表示舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# avgpool2d

## 接口定义

```python
def avgpool2d(input: Tensor,
              kernel: Union[List[int],Tuple[int],None] = None,
              stride: Union[List[int],Tuple[int],None] = None,
              pad:    Union[List[int],Tuple[int],None] = None,
              ceil_mode: bool = False,
              scale: List[float] = None,
              zero_point: List[int] = None,
              out_name: str = None,
              count_include_pad : bool = False,
              round_mode : str="half_away_from_zero",
              first_round_mode : str="half_away_from_zero"):
    #pass
```

## 功能描述

对输入Tensor进行Avg池化处理。请参考各大框架下的池化操作。
该操作属于 **本地操作**。

## 参数说明

* input：Tensor类型，表示输入操作Tensor。
* kernel：List[int]或Tuple[int]型或None，输入None表示使用global_pooling，不为None时要求该参数长度为2。
* stride：List[int]或Tuple[int]型或None，表示步长尺寸，输入None使用默认值[1,1]，不为None时要求该参数长度为2。
* pad：List[int]或Tuple[int]型或None，表示填充尺寸，输入None使用默认值[0,0,0,0]，不为None时要求该参数长度为4。
* ceil_mode：bool型，表示计算output shape时是否向上取整。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为input，output的scale。
* zero_point：List[int]类型或None，偏移参数。取None代表非量化计算。若为List，长度为2，分别为input，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* count_include_pad：Bool类型，表示在计算平均值时，是否将pad值计算在内，默认值为False。
* round_mode：String型，当输入输出Tensor为量化时，表示舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。
* first_round_mode：String型，当输入输出Tensor为量化时，表示第一次的舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# avgpool3d

## 接口定义

```python
def avgpool3d(input: Tensor,
              kernel: Union[List[int],int,Tuple[int, ...]] = None,
              stride: Union[List[int],int,Tuple[int, ...]] = None,
              pad:    Union[List[int],int,Tuple[int, ...]] = None,
              ceil_mode: bool = False,
              scale: List[float] = None,
              zero_point: List[int] = None,
              out_name: str = None,
              count_include_pad : bool = False,
              round_mode : str="half_away_from_zero",
              first_round_mode : str="half_away_from_zero"):
    #pass
```

## 功能描述

对输入Tensor进行Avg池化处理。请参考各大框架下的池化操作。
该操作属于 **本地操作**。

## 参数说明

* tensor：Tensor类型，表示输入操作Tensor。
* kernel：List[int]或Tuple[int]型或int或None，输入None表示使用global_pooling，不为None时若输入单个整数，表示在3个维度上的kernel大小相同，若输入List或Tuple，要求该参数长度为3。
* pad：List[int]或Tuple[int]型或int或None，表示填充尺寸，输入None使用默认值[0,0,0,0,0,0]，不为None时若输入单个整数，表示在3个维度上的pad大小相同，若输入List或Tuple，要求该参数长度为6。
* stride：List[int]或Tuple[int]型或int或None，表示步长尺寸，输入None使用默认值[1,1,1]，不为None时若输入单个整数，表示在3个维度上的stride大小相同，若输入List或Tuple，要求该参数长度为3。
* ceil_mode：bool型，表示计算output shape时是否向上取整。
* scale：List[float]类型或None，量化参数。取None代表非量化计算。若为List，长度为2，分别为input，output的scale。
* zero_point：List[int]类型或None，偏移参数。取None代表非量化计算。若为List，长度为2，分别为input，output的zero_point。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* count_include_pad：Bool类型，表示在计算平均值时，是否将pad值计算在内，默认值为False。
* round_mode：String型，当输入输出Tensor为量化时，表示第二次的舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。
* first_round_mode：String型，当输入输出Tensor为量化时，表示第一次的舍入模式。默认值为'half_away_from_zero'。round_mode取值范围为"half_away_from_zero", "half_to_even", "towards_zero", "down", "up"。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。
* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8/UINT8。

# upsample

## 接口定义

```python
def upsample(tensor_i: Tensor,
             scale: int = 2,
             out_name: str = None):
    #pass
```

## 功能描述

在h和w维度对输入tensor数据进行scale倍重复扩展输出。
该操作属于 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* scale：int型，表示扩展倍数。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16/INT8。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16/INT8。

# reduce

## 接口定义

```python
def reduce(tensor_i: Tensor,
           method: str = 'ReduceSum',
           axis: Union[List[int],Tuple[int],int] = None,
           keep_dims: bool = False,
           out_name: str = None):
    #pass
```

## 功能描述

依据axis_list，对输入的tensor做reduce操作。
该操作属于 **受限本地操作**；仅当输入数据类型为FLOAT32时是 **本地操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* method：string类型，表示reduce方法，目前可选"ReduceMin", "ReduceMax", "ReduceMean", "ReduceProd", "ReduceL2", "ReduceL1","ReduceSum"。
* axis：List[int]或Tuple[int]或int，表示需要reduce的轴。
* keep_dims：bool型，表示是否要保留原先的维度。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入Tensor相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# Normalization Operator

## batch_norm

### 接口定义

```python
def batch_norm(input: Tensor,
               mean: Tensor,
               variance: Tensor,
               gamma: Tensor = None,
               beta: Tensor = None,
               epsilon: float = 1e-5,
               out_name: str = None):
    #pass
```

### 功能描述

该batch_norm算子先完成输入值的批归一化，完成归一化之后再进行缩放和平移。
批归一化运算过程可参考各框架的batch_norm算子。

该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入待归一化的Tensor，维度不限，如果x只有1维，c为1，否则c等于x的shape[1]。
* mean：Tensor类型，表示输入的均值，shape为[c]。
* variance：Tensor类型，表示输入的方差值，shape为[c]。
* gamma：Tensor类型或None，表示批归一化之后进行的缩放，不为None时要求shape为[c]，取None时相当于shape为[c]的全1Tensor。
* beta：Tensor类型或None，表示批归一化和缩放之后进行的平移，不为None时要求shape为[c]，取None时相当于shape为[c]的全0Tensor。
* epsilon：FLOAT类型，表示为了除法运算数值稳定加在分母上的值。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回Tensor类型，表示输出归一化后的Tensor，数据类型与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

## layer_norm

### 接口定义

```python
def layer_norm(input: Tensor,
               gamma: Tensor = None,
               beta: Tensor = None,
               epsilon: float = 1e-5,
               axis: int,
               out_name: str = None):
    #pass
```

### 功能描述

该layer_norm算子先完成输入值的归一化，完成归一化之后再进行缩放和平移。
批归一化运算过程可参考各框架的layer_norm算子。

该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入待归一化的Tensor，维度不限，如果x只有1维，c为1，否则c等于x的shape[1]。
* gamma：Tensor类型或None，表示批归一化之后进行的缩放，不为None时要求shape为[c]，取None时相当于shape为[c]的全 1 Tensor。
* beta：Tensor类型或None，表示批归一化和缩放之后进行的平移，不为None时要求shape为[c]，取None时相当于shape为[c]的全 0 Tensor。
* epsilon：FLOAT类型，表示为了除法运算数值稳定加在分母上的值。
* axis：int型，第一个标准化的维度。 如果rank(X)为r，则axis的允许范围为[-r, r)。 负值表示从后面开始计算维度。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回Tensor类型，表示输出归一化后的Tensor，数据类型与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

## group_norm

### 接口定义

```python
def group_norm(input: Tensor,
               gamma: Tensor = None,
               beta: Tensor = None,
               epsilon: float = 1e-5,
               num_groups: int,
               out_name: str = None):
    #pass
```

### 功能描述

该group_norm算子先完成输入值的归一化，完成归一化之后再进行缩放和平移。
批归一化运算过程可参考各框架的group_norm算子。

该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入待归一化的Tensor，维度不限，如果x只有1维，c为1，否则c等于x的shape[1]。
* gamma：Tensor类型或None，表示批归一化之后进行的缩放，不为None时要求shape为[c]，取None时相当于shape为[c]的全1Tensor。
* beta：Tensor类型或None，表示批归一化和缩放之后进行的平移，不为None时要求shape为[c]，取None时相当于shape为[c]的全0Tensor。
* epsilon：FLOAT类型，表示为了除法运算数值稳定加在分母上的值。
* num_groups：int型，表示分组的数量。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回Tensor类型，表示输出归一化后的Tensor，数据类型与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

## rms_norm

### 接口定义

```python
def rms_norm(input: Tensor,
             gamma: Tensor = None,
             epsilon: float = 1e-5,
             axis: int = -1,
             out_name: str = None):
    #pass
```

### 功能描述

该rms_norm算子先完成输入值最后一个维度的归一化，完成归一化之后再进行缩放。运算过程可参考各框架的RMSNorm算子。

该操作属于 **本地操作**。

### 参数说明

* input：Tensor类型，表示输入待归一化的Tensor，维度不限。
* gamma：Tensor类型或None，表示批归一化之后进行的缩放，不为None时要求shape与input最后一维 `w` 相等，取None时相当于shape为[w]的全1Tensor。
* epsilon：FLOAT类型，表示为了除法运算数值稳定加在分母上的值。
* axis: int型，第一个标准化的维度。 如果rank(X)为r，则axis的允许范围为[-r, r)。 负值表示从后面开始计算维度。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值

返回Tensor类型，表示输出归一化的后的Tensor，数据类型与输入一致。

### 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。

# normalize

## 接口定义

```python
def normalize(input: Tensor,
        p: float = 2.0,
        axes: Union[List[int], int] = 1,
        eps : float = 1e-12,
        out_name: str = None):
```

## 功能描述

对输入张量input的指定维度进行 Lp 归一化。

对于大小为 (n0, ..., ndim, ..., nk) 的张量输入，每个 ndim元素向量v沿维度axes 的变换为

v = v / max(∥v∥p, ε)

在默认参数下，它对向量的维度1上进行L2归一化。

该操作属于**本地操作**。

## 参数说明

* input: Tensor类型。表示输入Tensor。数据类型为float32, float16。
* p: float类型，默认值为2.0。表示是归一化过程中的指数值。
* axes: Union[List[int], int]类型，默认为1。表示要归一化的维度。如果是list，那么list内的值必须是连续的。注意，axes = [0,-1]并不是连续的。
* eps : float类型，默认值为1e-12。 一个极小值，用来避免除以0。
* out_name: string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回Tensor类型，表示输出归一化的后的Tensor，数据类型与输入一致。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# nms

## 接口定义

```python
def nms(boxes: Tensor,
        scores: Tensor,
        format: str = 'PYTORCH',
        max_box_num_per_class: int = 1,
        out_name: str = None)
```

## 功能描述

对输入tensor进行非极大值抑制处理。

## 参数说明

* boxes：Tensor类型，表示输入框的列表。必须是三维张量，第一维为批的个数，第二维为框的个数，第三维为框的4个坐标。
* scores：Tensor类型，表示输入得分的列表。必须是三维张量，第一维为批的个数，第二维为类的个数，第三维为框的个数。
* format：string类型，'TENSORFLOW'表示Tensorflow格式[y1, x1, y2, x2]，'PYTORCH'表示Pytorch格式[x_center, y_center, width, height], 默认值为'PYTORCH'。
* max_box_num_per_class：int型，表示每个类中的输出框的最大个数。必须大于0，默认值为1。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，表示从框列表中选出的框的索引的列表，它是一个2维张量，格式为[num_selected_indices, 3], 其中每个索引的格式为[batch_index, class_index, box_index]。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32。
* BM1684X：输入数据类型可以是FLOAT32。

# interpolate

## 接口定义

```python
def interpolate(input: Tensor,
                scale_h: float,
                scale_w: float,
                method: str = 'nearest',
                coord_mode: str = "pytorch_half_pixel",
                out_name: str = None)
```

## 功能描述

对输入tensor进行插值。

## 参数说明

* input：Tensor类型，表示输入的Tensor。必须是至少2维的张量。
* scale_h：float型，表示高度方向的缩放系数，必须大于0。
* scale_w：float型，表示宽度方向的缩放系数，必须大于0。
* method: string类型，表示插值方法，可选项为"nearest"或"linear"。默认值为"nearest"。
* coord_mode: string类型，表示输出坐标的计算方法，可选项为"align_corners"、"pytorch_half_pixel"、"half_pixel"、"asymmetric"。默认值为"pytorch_half_pixel"。
* out_name：string类型或None，表示输出Tensor的名称。如果为None，内部会自动生成名称。

其中，`coord_mode` 的意义跟onnx的 `Resize` 算子的参数 `coordinate_transformation_mode` 的意义是一样的。若h/w方向的放缩因子为 `scale` ，输入坐标为 `x_in` ，输入尺寸为 `l_in` ，输出坐标为 `x_out` ，输出尺寸为 `l_out` ，则逆映射定义如下：

* `"half_pixel"`：
    x_in = (x_out + 0.5) / scale - 0.5

* `"pytorch_half_pixel"`：
    x_in = len > 1 ? (x_out + 0.5) / scale - 0.5 : 0

* `"align_corners"`：
    x_in = x_out * (l_in - 1) / (l_out - 1)

* `"asymmetric"`：
    x_in = x_out / scale

## 返回值

返回一个Tensor，表示插值后的结果。数据类型与输入类型相同，形状根据缩放系数进行调整。

## 处理器支持

* BM1688：支持的输入数据类型为FLOAT32/FLOAT16/INT8。
* BM1684X：支持的输入数据类型为FLOAT32/FLOAT16/INT8。

# yuv2rgb

## 接口定义

```python
def yuv2rgb(
    inputs: Tensor,
    src_format: int,
    dst_format: int,
    ImageOutFormatAttr: str,
    formula_mode: str,
    round_mode: str,
    out_name: str = None,
):
```

## 功能描述

对输入tensor进行yuv转rgb格式，输入的Tensor要求shape=[n,h*3/2,w]，其中n为批个数，h为图像的像素高，w为图像的像素宽。

## 参数说明

* inputs：Tensor类型，表示输入的yuv矩阵。必须是三维张量，第一维为批的个数，第二维为输入矩阵的高，第三维为输入矩阵的宽。
* src_format：Int类型，表示输入的格式。FORMAT_MAPPING_YUV420P_YU12=0，FORMAT_MAPPING_YUV420P_YV12=1，FORMAT_MAPPING_NV12=2，FORMAT_MAPPING_NV21=3。
* dst_format：Int类型，表示输出的格式。FORMAT_MAPPING_RGB=4，FORMAT_MAPPING_BGR=5。
* ImageOutFormatAttr：str型，目前只支持"UINT8"。
* formula_mode：string类型，表示使用的yuv2rgb转换公式，目前支持"_601_limited"、"_601_full"。
* round_mode：string类型，表示使用的舍入模式，目前支持"HalfAwayFromZero", "HalfToEven"。
* out_name：string类型，表示输出Tensor的名称，非必选，默认为None。

## 返回值

返回一个Tensor，表示转换出的rgb格式Tensor，shape=[n,3,h,w]，其中n为批个数，h为图像的像素高，w为图像的像素宽。

## 处理器支持

* BM1684X：输入数据类型是INT8/UINT8, 输出UINT8。
* BM1688：输入数据类型是INT8/UINT8，输出UINT8。

# roiExtractor

## 接口定义

```python
def roiExtractor(rois: Tensor,
                 target_lvls: Tensor,
                 feats: List[Tensor],
                 PH: int,
                 PW: int,
                 sampling_ratio: int,
                 list_spatial_scale: Union[int, List[int], Tuple[int]],
                 mode:str=None,
                 out_name:str=None)
```

## 功能描述

给定4个featrue map，根据target_lvls索引从rois中抽取对应的roi，并与对应的featrue map做roi align，得到最终输出。
该操作属于**本地操作**。

## 参数说明

* rois：Tensor类型，表示所有的rois。
* target_lvls：Tensor类型，表示roi对应哪层feature map。
* feats：List[Tensor]型，表示多层feature map。
* PH：int类型，表示输出的height。
* PW：int类型，表示输出的width。
* sampling_ratio：int类型，表示每层feature map的sample ratio。
* list_spatial_scale：int，List[int]或Tuple[int]型，表示每层feature map对应的spatial scale。
                      请注意，spatial scale遵循mmdetection风格，最初给定一个整数值，但其浮点倒数最終被用于RoIAlign。
* mode: string类型, 表示Op执行模式, 目前支持DynNormal, DynFuse。
        请注意，在DynFuse模式下，输入rois的坐标  支持2类风格,1)遵循mmdetection的风格，即5长度[batch_id, x0, y0, x1, y1]。
                                                       2)自定义的7长度[a, b, x0, y0, x1, y1, c], 特別注意如果batch_id和a,b,c难以匹配, 建议另外重新生成batch_id。
               在DynNormal模式下，输入rois的坐标风格是一种自定义的7长度[a, b, x0, y0, x1, y1, c]风格，以便应用客户独特的模型。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，该Tensor的数据类型与输入rois相同。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。
* BM1684X：输入数据类型可以是FLOAT32/FLOAT16。

# nonzero

## 接口定义

```python
def nonzero(tensor_i:Tensor,
            dtype: str = 'int32',
            out_name: str = None):
    #pass
```

## 功能描述

抽取输入Tensor data为true时对应的位置信息信息。
该操作属于**全局操作**。

## 参数说明

* tensor_i：Tensor类型，表示输入操作Tensor。
* dtype：string型，表示输出数据类型，目前仅可使用默认值"int32"。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值

返回一个Tensor，数据类型为INT32。

## 处理器支持

* BM1688：输入数据类型可以是FLOAT32/FLOAT16。

# lut

## 接口定义

```python
def lut(input: Tensor,
        table: Tensor,
        out_name: str = None):
    #pass
```

## 功能描述
对输入tensor进行查找表查找操作。

## 参数说明
* input：Tensor类型，表示输入。
* table：Tensor类型，表示查找表。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值
返回一个Tensor，数据类型与张量 `table` 的数据类型相同。

## 处理器支持
* BM1688： `input` 的数据类型可以是INT8/UINT8， `table` 的数据类型可以是INT8/UINT8。
* BM1684X： `input` 的数据类型可以是INT8/UINT8， `table` 的数据类型可以是INT8/UINT8。

# select

## 接口定义

```python
def select(lhs: Tensor,
           rhs: Tensor,
           tbrn: Tensor,
           fbrn: Tensor,
           type: str,
           out_name = None):
    #pass
```

## 功能描述
根据 `lhs` 与 `rhs` 的数值比较结果来选择，条件为真时，选择 `tbrn` ，条件为假时，选择 `fbrn` 。

## 参数说明
* lhs：Tensor类型，表示左边的张量。
* rhs：Tensor类型，表示右边的张量。
* tbrn：Tensor类型，表示条件为真时取的值。
* fbrn：Tensor类型，表示条件为假时取的值。
* type: string类型，表示比较符。可选项为"Greater"/"Less"/"GreaterOrEqual"/"LessOrEqual"/"Equal"/"NotEqual"。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

约束条件：要求 `lhs` 与 `rhs` 的形状和数据类型相同， `tbrn` 与 `fbrn` 的形状和数据类型相同。

## 返回值
返回一个Tensor，数据类型与张量 `tbrn`的数据类型相同。

## 处理器支持
* BM1688： `lhs` / `rhs` / `tbrn` / `fbrn` 的数据类型可以是FLOAT32/FLOAT16(TODO)。
* BM1684X： `lhs` / `rhs` / `tbrn` / `fbrn` 的数据类型可以是FLOAT32/FLOAT16(TODO)。

# cond_select

## 接口定义

```python
def cond_select(cond: Tensor,
                tbrn: Union[Tensor, Scalar],
                fbrn: Union[Tensor, Scalar],
                out_name:str = None):
    #pass
```

## 功能描述
根据条件 `cond` 来选择，条件为真时，选择 `tbrn` ，条件为假时，选择 `fbrn` 。

## 参数说明
* cond：Tensor类型，表示条件。
* tbrn：Tensor类型或Scalar类型，表示条件为真时取的值。
* fbrn：Tensor类型或Scalar类型，表示条件为假时取的值。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

约束条件：若 `tbrn` 和 `fbrn` 皆为张量，则要求 `tbrn` 与 `fbrn` 的形状和数据类型相同。

## 返回值
返回一个Tensor，数据类型与张量 `tbrn` 的数据类型相同。

## 处理器支持
* BM1688： `cond` / `tbrn` / `fbrn` 的数据类型可以是FLOAT32/FLOAT16(TODO)。
* BM1684X： `cond` / `tbrn` / `fbrn` 的输入数据类型可以是FLOAT32/FLOAT16(TODO)。

# bmodel_inference_combine

## 接口定义

```python
def bmodel_inference_combine(
    bmodel_file: str,
    final_mlir_fn: str,
    input_data_fn: Union[str, dict],
    tensor_loc_file: str,
    reference_data_fn: str,
    dump_file: bool = True,
    save_path: str = "",
    out_fixed: bool = False,
    dump_cmd_info: bool = True,
    skip_check: bool = True,  # disable data_check to increase processing speed
    run_by_op: bool = False, # enable to run_by_op, may cause timeout error when some OPs contain too many atomic cmds
    desire_op: list = [], # set ["A","B","C"] to only dump tensor A/B/C, dump all tensor as defalt
    is_soc: bool = False,  # soc mode ONLY support {reference_data_fn=xxx.npz, dump_file=True}
    using_memory_opt: bool = False, # required when is_soc=True
    enable_soc_log: bool = False, # required when is_soc=True
    soc_tmp_path: str = "/tmp",  # required when is_soc=True
    hostname: str = None,  # required when is_soc=True
    port: int = None,  # required when is_soc=True
    username: str = None,  # required when is_soc=True
    password: str = None,  # required when is_soc=True
):
```

## 功能描述
根据生成的bmodel进行推理和逐层Tensor数据打印，配合 `npz_tool.py` 进行bmodel正确性验证。

## 参数说明
* bmodel_file: String类型，表示bmodel绝对路径。
* final_mlir_fn: String类型，表示bmodel对应的final.mlir的绝对路径。
* input_data_fn: String类型或dict类型，表示输入数据的格式，支持 字典格式、.dat格式、.npz格式。
* tensor_loc_file: String类型，表示bmodel对应的tensor_location.json文件的绝对路径。
* reference_data_fn: String,类型，表示 `module.state = "TPU_LOWERED"`的.mlir文件或对应的.npz推理结果的绝对路径。bmodel推理时会将原本一个算子的shape拆散，该参数用于恢复原本的shape。
* dump_file: Bool类型，表示逐层Tensor数据是否以.npz文件形似保存，或直接返回字典。
* save_path: String类型，表示 `dump_file=True` 时的主机(host)端保存逐层推理的.npz文件的绝对路径。
* out_fixed: Bool类型，表示逐层Tensor数据输出是否保持为定点格式。
* dump_cmd_info: Bool类型，表示将当前bmodel中包含的所有原子指令对应的final.mlir的信息保存成txt文件，保存路径在save_path下。
* skip_check: Bool类型，启用此项可禁用数据对比，提高推理速度。soc模式下默认不进行数据对比。
* run_by_op: Bool类型，启用后按OP粒度运行，禁用时为按原子指令粒度运行。按OP粒度运行速度较快，但当一个OP中包含过多原子指令时可能会引发timeout错误。
* desire_op: List类型，其中当传入多个String类型的名字时，只会dump出给定名字的tensor。默认dump所有层tensor。
* is_soc: Bool类型，表示是否启用soc模式进行推理。
* using_memory_opt: Bool类型，启用后会减小在device端的内存消耗，但会增加耗时。推荐在大模型时启用。
* enable_soc_log: Bool类型，启用此项打印并在save_path下保存log日志。
* soc_tmp_path: String类型，表示soc模式下，板卡(device)端存放临时文件与推理工具的绝对路径。
* hostname: String类型，表示soc模式下，device端的ip地址。
* port: Int类型，表示soc模式下，device端的端口号。
* username: String类型，表示soc模式下，device端的用户名。
* password: String类型，表示soc模式下，device端的密码。

注意:
* 当使用pcie或soc模式进行逐层dump时，需先使用 `/tpu-mlir/envsetup.sh` 中的use_chip切换环境变量。当使用cmodel模式时，使用use_cmodel。
* 当使用soc模式时：reference_data_fn必须是.npz格式。

## 返回值
* cmodel/pcie模式下：如果 `dump_file=True`，则在save_path下生成bmodel_infer_xxx.npz文件，否则返回python字典。
* soc模式下：在save_path下生成soc_infer_xxx.npz文件。

## 处理器支持
* BM1688：  cmodel模式。
* BM1684X： cmodel/pcie/soc模式。

# scatter

## 接口定义

```python
def scatter(input: Tensor,
      index: Tensor,
      updates: Tensor,
      axis: int = 0,
      out_name: str = None):
    #pass
```

## 功能描述
根据指定的索引，将输入数据写入目标Tensor的特定位置。该操作允许将更新输入Tensor的元素散布到输出Tensor的指定位置。请参考各大框架下的ScatterElements操作。
该操作属于 **本地操作** 。

## 参数说明
* input：Tensor类型，表示输入操作Tensor，即需要更新的目标Tensor。
* index：Tensor类型，表示指定更新位置的索引Tensor。
* updates：Tensor类型，表示要写入目标Tensor的值。
* axis：int型，表示更新的轴。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值
返回一个新的Tensor，该Tensor在指定位置上进行了更新操作，其他位置保持了原始输入的Tensor值。

## 处理器支持
* BM1684X：输入数据类型可以是FLOAT32,FLOAT16,INT8。
* BM1688：输入数据类型可以是FLOAT32,FLOAT16,INT8。

# scatterND

## 接口定义

```python
def scatterND(input: Tensor,
      indices: Tensor,
      updates: Tensor,
      out_name: str = None):
    #pass
```

## 功能描述
根据指定的索引，将输入数据写入目标Tensor的特定位置。该操作允许将更新输入Tensor的元素散布到输出Tensor的指定位置。请参考ONNX 11下的ScatterND操作。
该操作属于 **本地操作** 。

## 参数说明
* input：Tensor类型，表示输入操作Tensor，即需要更新的目标Tensor。
* indices：Tensor类型，表示指定更新位置的索引Tensor。 数据类型必须是uint32。
* updates：Tensor类型，表示要写入目标Tensor的值。Rank(updates) = Rank(input) + Rank(indices) - shape(indices)[-1] -1 。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

## 返回值
返回一个新的Tensor，该Tensor在指定位置上进行了更新操作，其他位置保持了原始输入的Tensor值。形状与数据类型和input一致。

## 处理器支持
* BM1684X：输入数据类型可以是FLOAT32,FLOAT16,INT8。
* BM1688：输入数据类型可以是FLOAT32,FLOAT16,INT8。

# Preprocess Operator

## mean_std_scale

### 接口定义

```python
def mean_std_scale(input: Tensor,
                   std: List[float],
                   mean: List[float],
                   scale: Optional[Union[List[float],List[int]]] = None,
                   zero_points: Optional[List[int]] = None,
                   out_name: str = None,
                   odtype="float16",
                   round_mode: str = "half_away_from_zero"):
    #pass
```

### 功能描述
对输入Tensor 进行预处理操作。
该操作属于 **全局操作** 。

### 参数说明
* input：Tensor类型，表示输入操作Tensor。必须是4维或5维。
* std：List[float]类型，表示数据集的标准差。mean,std维度必须和input的channel维度一致,即input的第二维。
* mean: List[float]类型，表示数据集的均值。mean,std维度必须和input的channel维度一致，即input的第二维。
* scale: Optional[Union[List[float],List[int]]]类型或None，缩放系数。
* zero_points: Optional[List[int]]类型或None，表示零点。
* out_name：string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
* odtype：String类型，表示接口输出Tensor数据类型。默认值为"float16"。目前支持float16， int8。
* round_mode：String类型，表示取整方法。默认值为"half_away_from_zero",范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"

### 返回值
返回一个Tensor，数据类型为odtype。

### 处理器支持
* BM1684X：输入数据类型可以是FLOAT32/UINT8/INT8,输出类型可以为INT8/FLOAT16。

# Transform Operator

## rope

### 接口定义

```python
def rope(input: Tensor,
         weight0: Tensor,
         weight1: Tensor,
         is_permute_optimize: bool = False,    # unused
         mul1_round_mode: str = 'half_up',
         mul2_round_mode: str= 'half_up',
         add_round_mode: str = 'half_up',
         mul1_shift: int = None,
         mul2_shift: int = None,
         add_shift: int = None,
         mul1_saturation: bool = True,
         mul2_saturation: bool = True,
         add_saturation: bool = True,
         out_name: str = None):
    #pass
```

### 功能描述
对输入Tensor进行旋转编码（RoPE）操作。该操作属于**全局操作**。

### 参数说明
- input：Tensor类型，表示输入操作Tensor。必须是4维。
- weight0: Tensor，表示输入操作Tensor。
- weight1: Tensor，表示输入操作Tensor。
- is_permute_optimize：bool类型，表示是否做permute下沉，进行permute下沉shape的检查。# unused
- mul1_round_mode: String类型，表示RoPE中mul1的取整方法。默认值为"half_away_from_zero"，范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"，"half_up"，"half_down"。
- mul2_round_mode: String类型，表示RoPE中mul2的取整方法。默认值为"half_away_from_zero"，范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"，"half_up"，"half_down"。
- add_round_mode: String类型，表示RoPE中add的取整方法。默认值为"half_away_from_zero"，范围是"half_away_from_zero"，"half_to_even"，"towards_zero"，"down"，"up"，"half_up"，"half_down"。
- mul1_shift: int型，表示RoPE中mul1的移位的位数。
- mul2_shift: int型，表示RoPE中mul2的移位的位数。
- add_shift: int型，表示RoPE中add的移位的位数。
- mul1_saturation: bool类型，表示RoPE中的mul1计算结果是否需要饱和处理，默认为True饱和处理，非必要不修改。
- mul2_saturation: bool类型，表示RoPE中的mul2计算结果是否需要饱和处理，默认为True饱和处理，非必要不修改。
- add_saturation: bool类型，表示RoPE中的add计算结果是否需要饱和处理，默认为True饱和处理，非必要不修改。
- out_name: output name，string类型，默认为None。

### 返回值
返回一个Tensor，数据类型为odtype。

### 处理器支持
- BM1684X：输入数据类型可以是FLOAT32、FLOAT16和INT类型。

## multi_scale_deformable_attention

### 接口定义

```python
def multi_scale_deformable_attention(
    query: Tensor,
    value: Tensor,
    key_padding_mask: Tensor,
    reference_points: Tensor,
    sampling_offsets_weight: Tensor,
    sampling_offsets_bias_ori: Tensor,
    attention_weights_weight: Tensor,
    attention_weights_bias_ori: Tensor,
    value_proj_weight: Tensor,
    value_proj_bias_ori: Tensor,
    output_proj_weight: Tensor,
    output_proj_bias_ori: Tensor,
    spatial_shapes: List[List[int]],
    embed_dims: int,
    num_heads: int = 8,
    num_levels: int = 4,
    num_points: int = 4,
    out_name: str = None):
    #pass
```

### 功能描述
对输入进行多尺度可变形注意力机制，具体功能可参考https://github.com/open-mmlab/mmcv/blob/main/mmcv/ops/multi_scale_deform_attn.py:MultiScaleDeformableAttention:forward，该操作的实现方式与官方有所不同。目前只支持batch_size=1的情况。该操作属于**本地操作**。

### 参数说明
- query：Tensor类型，Transformer的查询张量，形状为(1, num_query, embed_dims)。
- value：Tensor类型，值投影张量，形状为(1, num_key, embed_dims)。
- key_padding_mask: Tensor类型，查询张量的mask，形状为(1, num_key)。
- reference_points: Tensor类型，归一化的参考点，形状为(1, num_query, num_levels, 2)，所有元素的范围在[0, 1]之间，左上角为(0,0)，右下角为(1,1)，包括填充区域。
- sampling_offsets_weight: Tensor类型，计算采样偏移量全连接层的权重，形状为(embed_dims, num_heads*num_levels*num_points*2)。
- sampling_offsets_bias_ori: Tensor类型，计算采样偏移量全连接层的偏置，形状为(num_heads*num_levels*num_points*2)。
- attention_weights_weight: Tensor类型，计算注意力权重全连接层的权重，形状为(embed_dims, num_heads*num_levels*num_points)。
- attention_weights_bias_ori: Tensor类型，计算注意力权重全连接层的偏置，形状为(num_heads*num_levels*num_points)。
- value_proj_weight: Tensor类型，计算值投影全连接层的权重，形状为(embed_dims, embed_dims)。
- value_proj_bias_ori: Tensor类型，计算值投影全连接层的偏置，形状为(embed_dims)。
- output_proj_weight: Tensor类型，计算输出投影全连接层的权重，形状为(embed_dims, embed_dims)。
- output_proj_bias_ori: Tensor类型，计算输出投影全连接层的偏置，形状为(embed_dims)。
- spatial_shapes: List[List[int]]类型，不同层级特征的空间形状，形状为(num_levels, 2)，最后一个维度表示(h, w)。
- embed_dims: int类型，查询、键、值的hidden_size。
- num_heads: int类型，注意力头数，默认值为8。
- num_levels: int类型，多尺度注意力的层级数，默认值为4。
- num_points: int类型，每个层级的采样点数，默认值为4。
- out_name: string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。

### 返回值
返回一个Tensor，数据类型为query.dtype。

### 处理器支持
- BM1684X: 输入数据类型可以是FLOAT32、FLOAT16类型。
- BM1688: 输入数据类型可以是FLOAT32、FLOAT16类型。

## a16matmul

### 接口定义

```python
def a16matmul(input: Tensor,
              weight: Tensor,
              scale: Tensor,
              zp: Tensor,
              bias: Tensor = None,
              right_transpose=True,
              out_dtype: str = 'float16',
              out_name: str = None,
              group_size: int = 128,
              bits: int = 4,
              g_idx: Tensor = None):
    #pass
```

### 功能描述
对输入进行W4A16/W8A16 MatMul。该操作属于**全局操作**。

### 参数说明
- input: Tensor类型，表示输入tensor。
- weight: Tensor类型，表示4bits/8bits量化后权重，以int32类型存储。
- scale: Tensor类型，表示权重量化缩放因子，以float32类型存储。
- zp: Tensor类型，表示权重量化零点，以int32类型存储。
- bias: Tensor类型，表示偏置，以float32类型存储。
- right_transpose: Bool类型，表示权重矩阵是否转置，目前仅支持为True。
- out_dtype: string类型，表示输出张量的数据类型。
- out_name: string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称。
- group_size: int类型，表示量化的group大小。
- bits: int类型，表示量化位宽，仅支持4bits/8bits。
- g_idx: Tensor类型，量化重排系数，目前不支持。

### 返回值
返回一个Tensor，数据类型为out_dtype。

### 处理器支持
- BM1684X: 输入数据类型可以是FLOAT32、FLOAT16类型。
- BM1688: 输入数据类型可以是FLOAT32、FLOAT16类型。

## qwen2_block

### 接口定义

```python
def qwen2_block(hidden_states: Tensor,
                position_ids: Tensor,
                attention_mask: Tensor,
                q_proj_weights: Tensor,
                q_proj_scales: Tensor,
                q_proj_zps: Tensor,
                q_proj_bias: Tensor,
                k_proj_weights: Tensor,
                k_proj_scales: Tensor,
                k_proj_zps: Tensor,
                k_proj_bias: Tensor,
                v_proj_weights: Tensor,
                v_proj_scales: Tensor,
                v_proj_zps: Tensor,
                v_proj_bias: Tensor,
                o_proj_weights: Tensor,
                o_proj_scales: Tensor,
                o_proj_zps: Tensor,
                o_proj_bias: Tensor,
                down_proj_weights: Tensor,
                down_proj_scales: Tensor,
                down_proj_zps: Tensor,
                gate_proj_weights: Tensor,
                gate_proj_scales: Tensor,
                gate_proj_zps: Tensor,
                up_proj_weights: Tensor,
                up_proj_scales: Tensor,
                up_proj_zps: Tensor,
                input_layernorm_weight: Tensor,
                post_attention_layernorm_weight: Tensor,
                cos: List[Tensor],
                sin: List[Tensor],
                out_dtype: str = 'float16',
                group_size: int = 128,
                weight_bits: int = 4,
                hidden_size: int = 3584,
                rms_norm_eps: float = 1e-06,
                num_attention_heads: int = 28,
                num_key_value_heads: int = 4,
                mrope_section: List[int] = [16, 24, 24],
                quant_method: str = "gptq",
                out_name: str = None):
    #pass
```

### 功能描述
qwen2在prefill阶段的一个block layer。该操作属于**全局操作**。

### 参数说明
- hidden_states: Tensor类型，表示激活值，形状为(1, seq_length, hidden_size)。
- position_ids: Tensor类型，表示位置索引，形状为(3, 1, seq_length)。
- attention_mask: Tensor类型，表示注意力掩码，形状为(1, 1, seq_length, seq_length)。
- q_proj_weights: Tensor类型，表示query量化后权重，以int32类型存储。
- q_proj_scales: Tensor类型，表示query量化缩放因子，以float32类型存储。
- q_proj_zps: Tensor类型，表示query量化零点，以int32类型存储。
- q_proj_bias: Tensor类型，表示query偏置，以float32类型存储。
- k_proj_weights: Tensor类型，表示key量化后权重，以int32类型存储。
- k_proj_scales: Tensor类型，表示key量化缩放因子，以float32类型存储。
- k_proj_zps: Tensor类型，表示key量化零点，以int32类型存储。
- k_proj_bias: Tensor类型，表示key偏置，以float32类型存储。
- v_proj_weights: Tensor类型，表示value量化后权重，以int32类型存储。
- v_proj_scales: Tensor类型，表示value量化缩放因子，以float32类型存储。
- v_proj_zps: Tensor类型，表示value量化零点，以int32类型存储。
- v_proj_bias: Tensor类型，表示value偏置，以float32类型存储。
- o_proj_weights: Tensor类型，表示输出投影层量化后权重，以int32类型存储。
- o_proj_scales: Tensor类型，表示输出投影层量化缩放因子，以float32类型存储。
- o_proj_zps: Tensor类型，表示输出投影层量化零点，以int32类型存储。
- o_proj_bias: Tensor类型，表示输出投影层偏置，以float32类型存储。

# qwen2_block_cache

## 接口定义

```python
def qwen2_block_cache(hidden_states: Tensor,
                      position_ids: Tensor,
                      attention_mask: Tensor,
                      k_cache: Tensor,
                      v_cache: Tensor,
                      q_proj_weights: Tensor,
                      q_proj_scales: Tensor,
                      q_proj_zps: Tensor,
                      q_proj_bias: Tensor,
                      k_proj_weights: Tensor,
                      k_proj_scales: Tensor,
                      k_proj_zps: Tensor,
                      k_proj_bias: Tensor,
                      v_proj_weights: Tensor,
                      v_proj_scales: Tensor,
                      v_proj_zps: Tensor,
                      v_proj_bias: Tensor,
                      o_proj_weights: Tensor,
                      o_proj_scales: Tensor,
                      o_proj_zps: Tensor,
                      o_proj_bias: Tensor,
                      down_proj_weights: Tensor,
                      down_proj_scales: Tensor,
                      down_proj_zps: Tensor,
                      gate_proj_weights: Tensor,
                      gate_proj_scales: Tensor,
                      gate_proj_zps: Tensor,
                      up_proj_weights: Tensor,
                      up_proj_scales: Tensor,
                      up_proj_zps: Tensor,
                      input_layernorm_weight: Tensor,
                      post_attention_layernorm_weight: Tensor,
                      cos: List[Tensor],
                      sin: List[Tensor],
                      out_dtype: str = 'float16',
                      group_size: int = 128,
                      weight_bits: int = 4,
                      hidden_size: int = 3584,
                      rms_norm_eps: float = 1e-06,
                      num_attention_heads: int = 28,
                      num_key_value_heads: int = 4,
                      mrope_section: List[int] = [16, 24, 24],
                      quant_method: str = "gptq",
                      out_name: str = None
                      ):
    #pass
```

## 功能描述

qwen2在decode阶段的一个block layer。
该操作属于 **全局操作**。

## 参数说明

* hidden_states: Tensor类型，表示激活值，形状为 (1, 1, hidden_size)
* position_ids: Tensor类型，表示位置索引，形状为 (3, 1, 1)
* attention_mask: Tensor类型，表示注意力掩码，形状为 (1, 1, 1, seq_length + 1)
* k_cache: Tensor类型，表示key cache，形状为 (1, seq_length, num_key_value_heads, head_dim)
* v_cache: Tensor类型，表示value cache，形状为 (1, seq_length, num_key_value_heads, head_dim)
* q_proj_weights: Tensor类型，表示query量化后权重，以int32类型存储
* q_proj_scales: Tensor类型，表示query量化缩放因子，以float32类型存储
* q_proj_zps: Tensor类型，表示query量化零点，以int32类型存储
* q_proj_bias: Tensor类型，表示query偏置，以float32类型存储
* k_proj_weights: Tensor类型，表示key量化后权重，以int32类型存储
* k_proj_scales: Tensor类型，表示key量化缩放因子，以float32类型存储
* k_proj_zps: Tensor类型，表示key量化零点，以int32类型存储
* k_proj_bias: Tensor类型，表示key偏置，以float32类型存储
* v_proj_weights: Tensor类型，表示value量化后权重，以int32类型存储
* v_proj_scales: Tensor类型，表示value量化缩放因子，以float32类型存储
* v_proj_zps: Tensor类型，表示value量化零点，以int32类型存储
* v_proj_bias: Tensor类型，表示value偏置，以float32类型存储
* o_proj_weights: Tensor类型，表示输出投影层量化后权重，以int32类型存储
* o_proj_scales: Tensor类型，表示输出投影层量化缩放因子，以float32类型存储
* o_proj_zps: Tensor类型，表示输出投影层量化零点，以int32类型存储
* o_proj_bias: Tensor类型，表示输出投影层偏置，以float32类型存储
* down_proj_weights: Tensor类型，表示降维投影层量化后权重，以int32类型存储
* down_proj_scales: Tensor类型，表示降维投影层量化缩放因子，以float32类型存储
* down_proj_zps: Tensor类型，表示降维投影层量化零点，以int32类型存储
* gate_proj_weights: Tensor类型，表示门投影层量化后权重，以int32类型存储
* gate_proj_scales: Tensor类型，表示门投影层量化缩放因子，以float32类型存储
* gate_proj_zps: Tensor类型，表示门投影层量化零点，以int32类型存储
* up_proj_weights: Tensor类型，表示升维投影层量化后权重，以int32类型存储
* up_proj_scales: Tensor类型，表示升维投影层量化缩放因子，以float32类型存储
* up_proj_zps: Tensor类型，表示升维投影层量化零点，以int32类型存储
* input_layernorm_weight: Tensor类型，表示对input做layernorm的权重，以int32类型存储
* post_attention_layernorm_weight: Tensor类型，表示对attention层输出做layernorm的权重，以int32类型存储
* cos: List[Tensor]型类型，表示cos位置编码
* sin: List[Tensor]型类型，表示sin位置编码
* out_dtype: string类型，表示输出张量的数据类型
* group_size: int类型，表示量化的group大小
* weight_bits: int类型，表示量化位宽，仅支持4bits/8bits
* hidden_size: int类型，表示query/key/value的hidden_size
* rms_norm_eps: float类型，表示layernorm中的eps参数
* num_attention_heads: int类型，表示注意力头的个数
* num_key_value_heads: int类型，表示key/value头的个数
* mrope_section: List[int]类型，表示位置编码的三个维度大小
* quant_method: str类型，表示量化方式，目前仅支持GPTQ量化
* out_name: string类型或None，表示输出Tensor的名称，为None时内部会自动产生名称

## 返回值

返回3个Tensor，分别为激活输出、key cache、value cache，数据类型为out_dtype。

## 处理器支持

* BM1684X: 输入数据类型可以是FLOAT32,FLOAT16类型
* BM1688: 输入数据类型可以是FLOAT32,FLOAT16类型

---

# 法律声明

**法律声明**

版权所有 © 算能 2025. 保留一切权利。
非经本公司书面许可, 任何单位和个人不得擅自摘抄、复制本文档内容的部分或全部, 并不得以任何形式传播。

**注意**

您购买的产品、服务或特性等应受 算能 商业合同和条款的约束,
本文档中描述的全部或部分产品、服务或特性可能不在您的购买或使用范围之内。
除非合同另有约定,  算能 对本文档内容不做任何明示或默示的声明或保证。
由于产品版本升级或其他原因, 本文档内容会不定期进行更新。
除非另有约定, 本文档仅作为使用指导, 本文档中的所有陈述、信息和建议不构成任何明示或暗示的担保。

**技术支持**

地址: 北京市海淀区丰豪东路9号院中关村集成电路设计园(ICPARK)1号楼
邮编: 100094
网址: https://www.sophgo.com/
邮箱: sales@sophgo.com
电话: 010-57590723

**发布记录**

| 版本 | 发布日期 | 说明 |
|------|----------|------|
| v1.19.0 | 2025.05.30 | 支持AWQ与GPTQ模型; 修复Deconv3D F16, F32精度问题 |
| v1.18.0 | 2025.05.01 | yolo系列增加自动混精设置; run_calibration增加SmoothQuant选择; 新增llm一键编译脚本 |
| v1.17.0 | 2025.04.03 | LLM模型编译速度大幅提升; TPULang支持PPL算子接入; 修复Trilu bf16在Mars3上随机出错问题 |
| v1.16.0 | 2025.03.03 | TPULang ROI_Extractor支持; Einsum支持 abcde,abfge->abcdfg模式; LLMC支持Vila模型 |
| v1.15.0 | 2025.02.05 | 支持LLMC量化; codegen地址越界判断; 修复若干对比问题 |
| v1.14.0 | 2025.01.02 | yolov8/v11后处理融合支持; Conv3D stride大于15支持; FAttention精度提升 |
| v1.13.0 | 2024.12.02 | 精简Release发布包; MaxPoolWithMask训练算子性能优化; RoPE大算子支持 |
| v1.12.0 | 2024.11.06 | tpuv7-runtime cmodel接入; BM1690多核LayerGroup优化; 支持PPL编写后端算子 |
| v1.11.0 | 2024.09.27 | BM1688 tdb增加soc模式; bmodel支持细粒度合并; 修复若干性能下降问题 |
| v1.10.0 | 2024.08.15 | 支持yolov10; 增加量化调优章节; 优化tpu-perf日志打印 |
| v1.9.0 | 2024.07.16 | BM1690新增40个模型回归测试; 量化算法新增octav,aciq_guas和aciq_laplace |
| v1.8.0 | 2024.05.30 | BM1690支持多核MatMul算子; TPULang支持输入输出顺序指定; tpuperf移除patchelf依赖 |
| v1.7.0 | 2024.05.15 | CV186X双核修改为单核; BM1690测试流程与BM1684X一致; 支持gemma/llama/qwen等模型 |
| v1.6.0 | 2024.02.23 | 添加了Pypi发布形式; 支持用户自定义Global算子; 支持了CV186X处理器平台 |
| v1.5.0 | 2023.11.03 | 更多Global Layer支持多核并行 |
| v1.4.0 | 2023.09.27 | 系统依赖升级到Ubuntu22.04; 支持了BM1684 Winograd |
| v1.3.0 | 2023.07.27 | 增加手动指定浮点运算区域功能; 添加支持的前端框架算子列表; 添加NNTC与TPU-MLIR量化方式比较 |
| v1.2.0 | 2023.06.14 | 调整了混合量化示例 |
| v1.1.0 | 2023.05.26 | 添加使用智能深度学习处理器做后处理 |
| v1.0.0 | 2023.04.10 | 支持PyTorch, 增加章节介绍转PyTorch模型 |
| v0.8.0 | 2023.02.28 | 添加使用智能深度学习处理器做前处理 |
| v0.6.0 | 2022.11.05 | 增加章节介绍混精度操作过程 |
| v0.5.0 | 2022.10.20 | 增加指定model-zoo, 测试其中的所有模型 |
| v0.4.0 | 2022.09.20 | 支持Caffe, 增加章节介绍转Caffe模型 |
| v0.3.0 | 2022.08.24 | 支持TFLite, 增加章节介绍转TFLite模型 |
| v0.2.0 | 2022.08.02 | 增加了运行SDK中的测试样例章节 |
| v0.1.0 | 2022.07.29 | 初版发布, 支持 `resnet/mobilenet/vgg/ssd/yolov5s` , 并用yolov5s作为用例 |

# 开发环境配置

首先检查当前系统环境是否满足Ubuntu 22.04和Python 3.10。如不满足，请进行下一节基础环境配置；如满足，直接跳至TPU-MLIR安装。

## 基础环境配置

如不满足上述系统环境，则需要使用Docker，从DockerHub https://hub.docker.com/r/sophgo/tpuc_dev 下载所需的镜像文件，或使用下方命令直接拉取镜像：

```shell
$ docker pull sophgo/tpuc_dev:v3.4
```

若下载失败，可从官网开发资料 https://developer.sophgo.com/site/index/material/86/all.html 下载所需镜像文件，或使用下方命令下载镜像：

```shell
$ wget https://sophon-assets.sophon.cn/sophon-prod-s3/drive/25/04/15/16/tpuc_dev_v3.4.tar.gz
$ docker load -i tpuc_dev_v3.4.tar.gz
```

如果是首次使用Docker，可执行下述命令进行安装和配置（仅首次执行）：

```shell
$ sudo apt install docker.io
$ sudo systemctl start docker
$ sudo systemctl enable docker
$ sudo groupadd docker
$ sudo usermod -aG docker $USER
$ newgrp docker
```

若下载镜像文件，则需要确保镜像文件在当前目录，并在当前目录创建容器如下：

```shell
# 使用 --privileged 参数以获取root权限，如果不需要root权限，请删除该参数
$ docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:v3.4
```

其中，`myname` 为容器名称，可以自定义；`$PWD` 为当前目录，与容器的 `/workspace` 目录同步。

后文假定用户已经处于docker里面的 `/workspace` 目录。

## 安装TPU-MLIR

目前支持2种安装方法，分别是在线安装和离线安装。

**在线安装**

直接从pypi下载并安装，默认安装最新版：

```shell
$ pip install tpu_mlir
```

**离线安装**

从Github的Assets处下载最新的 `tpu_mlir-*-py3-none-any.whl`，然后使用pip安装：

```shell
$ pip install tpu_mlir-*-py3-none-any.whl
```

## 安装TPU-MLIR依赖

TPU-MLIR在对不同框架模型处理时所需的依赖不同，在线安装和离线安装方式都需要安装额外依赖。

**在线安装**

在线安装方式对于 `onnx` 或 `torch` 生成的模型文件，可使用下方命令安装额外的依赖环境：

```shell
# 安装onnx依赖
$ pip install tpu_mlir[onnx]
# 安装torch依赖
$ pip install tpu_mlir[torch]
```

目前支持5种配置：

```shell
onnx, torch, tensorflow, caffe, paddle
```

可使用一条命令安装多个配置，也可直接安装全部依赖环境：

```shell
# 同时安装onnx, torch, caffe依赖
$ pip install tpu_mlir[onnx,torch,caffe]
# 安装全部依赖
$ pip install tpu_mlir[all]
```

**离线安装**

同理，离线安装方式可使用下方命令安装额外的依赖环境：

```shell
# 安装onnx依赖
$ pip install tpu_mlir-*-py3-none-any.whl[onnx]
# 安装全部依赖
$ pip install tpu_mlir-*-py3-none-any.whl[all]
```

# 编译ONNX模型

本章以 `yolov5s.onnx` 为例，介绍如何编译迁移一个onnx模型至深度学习处理器平台运行。

该模型来自yolov5的官网：https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx

本章需要安装TPU-MLIR。

| 平台 | 文件名 | 说明 |
|------|--------|------|
| cv183x/cv182x/cv181x/cv180x | xxx.cvimodel | 请参考：CV18xx使用指南 |
| 其它 | xxx.bmodel | 继续本章节 |

## 安装TPU-MLIR

进入Docker容器，并执行以下命令安装TPU-MLIR：

```shell
$ pip install tpu_mlir[onnx]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[onnx]
```

## 准备工作目录

建立 `model_yolov5s` 目录，并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

操作如下：

```shell
$ mkdir model_yolov5s && cd model_yolov5s
$ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
$ cp -rf tpu_mlir_resource/dataset/COCO2017 .
$ cp -rf tpu_mlir_resource/image .
$ mkdir workspace && cd workspace
```

## ONNX转MLIR

如果模型是图片输入，在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入，则不需要考虑预处理。

预处理过程用公式表达如下（x代表输入）：

y = (x - mean) × scale

官网yolov5的图片是rgb格式，每个值会乘以 `1/255`，转换成mean和scale对应为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216`。

模型转换命令如下：

```shell
$ model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s.mlir
```

`model_transform` 主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_name | 是 | 指定模型名称 |
| model_def | 是 | 指定模型定义文件，比如 `.onnx` 或 `.tflite` 或 `.prototxt` 文件 |
| input_shapes | 否 | 指定输入的shape，例如 `[[1,3,640,640]]`；二维数组，可以支持多输入情况 |
| input_types | 否 | 指定输入的类型，例如int32；多输入用,隔开；不指定情况下默认处理为float32 |
| resize_dims | 否 | 原始图片需要resize之后的尺寸；如果不指定，则resize成模型的输入尺寸 |
| keep_aspect_ratio | 否 | 当test_input与input_shapes不同时，在resize时是否保持长宽比，默认为false；设置时会对不足部分补0 |
| mean | 否 | 图像每个通道的均值，默认为0.0,0.0,0.0 |
| scale | 否 | 图片每个通道的比值，默认为1.0,1.0,1.0 |
| pixel_format | 否 | 图片类型，可以是rgb、bgr、gray、rgbd四种格式，默认为bgr |
| channel_format | 否 | 通道类型，对于图片输入可以是nhwc或nchw，非图片输入则为none，默认为nchw |
| output_names | 否 | 指定输出的名称，如果不指定，则用模型的输出；指定后用该指定名称做输出 |
| test_input | 否 | 指定输入文件用于验证，可以是jpg或npy或npz；可以不指定，则不会进行正确性验证 |
| test_result | 否 | 指定验证后的输出文件，`.npz`格式 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| mlir | 是 | 指定输出的mlir文件名称和路径，`.mlir`后缀 |

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是模型的输入文件。

## MLIR转F16模型

将mlir文件转换成f16的bmodel，操作方法如下：

```shell
$ model_deploy \
    --mlir yolov5s.mlir \
    --quantize F16 \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --model yolov5s_1684x_f16.bmodel
```

`model_deploy` 的主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定mlir文件 |
| quantize | 是 | 指定默认量化类型，支持F32/F16/BF16/INT8等，不同处理器支持的量化类型如下表所示 |
| processor | 是 | 指定模型将要用到的平台，支持bm1690, bm1688, bm1684x, bm1684, cv186x, cv183x, cv182x, cv181x, cv180x |
| calibration_table | 否 | 指定校准表路径，当存在INT8/F8E4M3量化的时候需要校准表 |
| tolerance | 否 | 表示MLIR量化后的结果与MLIR fp32推理结果相似度的误差容忍度 |
| test_input | 否 | 指定输入文件用于验证，可以是jpg或npy或npz；可以不指定，则不会进行正确性验证 |
| test_reference | 否 | 用于验证模型正确性的参考数据（使用npz格式）。其为各算子的计算结果 |
| compare_all | 否 | 验证正确性时是否比较所有中间结果，默认不比较中间结果 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| op_divide | 否 | cv183x/cv182x/cv181x/cv180x only，尝试将较大的op拆分为多个小op以达到节省ion内存的目的，适用少数特定模型 |
| model | 是 | 指定输出的model文件名称和路径 |
| num_core | 否 | 当target选择为bm1688时，用于选择并行计算的tpu核心数量，默认设置为1个tpu核心 |
| skip_validation | 否 | 跳过验证bmodel正确性环节，用于提升模型部署的效率，默认执行bmodel验证 |

对于不同处理器和支持的quantize类型对应关系如下表所示：

| 处理器 | 支持的quantize |
|--------|----------------|
| BM1688 | F32/F16/BF16/INT8/INT4 |
| BM1684X | F32/F16/BF16/INT8 |
| BM1684 | F32/INT8 |
| CV186X | F32/F16/BF16/INT8/INT4 |
| CV183X/CV182X/CV181X/CV180X | BF16/INT8 |
| BM1690 | F32/F16/BF16/INT8/F8E4M3/F8E5M2 |

编译完成后，会生成名为 `yolov5s_1684x_f16.bmodel` 的文件。

## MLIR转INT8模型

### 生成校准表

转INT8模型前需要跑calibration，得到校准表；输入数据的数量根据情况准备100~1000张左右。

然后用校准表，生成对称或非对称bmodel。如果对称符合需求，一般不建议用非对称，因为非对称的性能会略差于对称模型。

这里用现有的100张来自COCO2017的图片举例，执行calibration：

```shell
$ run_calibration yolov5s.mlir \
    --dataset ../COCO2017 \
    --input_num 100 \
    -o yolov5s_cali_table
```

运行完成后会生成名为 `yolov5s_cali_table` 的文件，该文件用于后续编译INT8模型的输入文件。

### 编译为INT8对称量化模型

转成INT8对称量化模型，执行如下命令：

```shell
$ model_deploy \
    --mlir yolov5s.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --model yolov5s_1684x_int8_sym.bmodel
```

编译完成后，会生成名为 `yolov5s_1684x_int8_sym.bmodel` 的文件。

## 效果对比

在本发布包中有用python写好的yolov5用例，使用 `detect_yolov5` 命令，用于对图片进行目标检测。

该命令对应源码路径 `{package/path/to/tpu_mlir}/python/samples/detect_yolov5.py`。

阅读该代码可以了解模型是如何使用的：先预处理得到模型的输入，然后推理得到输出，最后做后处理。

用以下代码分别来验证onnx/f16/int8的执行结果。

onnx模型的执行方式如下，得到 `dog_onnx.jpg`：

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model ../yolov5s.onnx \
    --output dog_onnx.jpg
```

f16 bmodel的执行方式如下，得到 `dog_f16.jpg`：

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_1684x_f16.bmodel \
    --output dog_f16.jpg
```

int8对称bmodel的执行方式如下，得到 `dog_int8_sym.jpg`：

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_1684x_int8_sym.bmodel \
    --output dog_int8_sym.jpg
```

对比结果如下：

由于运行环境不同，最终的效果和精度会有些差异。

## 模型性能测试

以下操作需要在Docker外执行。

### 安装 `libsophon` 环境

请参考 `libsophon` 使用手册安装 `libsophon`。

### 检查 `BModel` 的性能

安装好 `libsophon` 后，可以使用 `bmrt_test` 来测试编译出的 `bmodel` 的正确性及性能。可以根据 `bmrt_test` 输出的性能结果，来估算模型最大的fps，来选择合适的模型。

```shell
# 下面测试上面编译出的bmodel
# --bmodel参数后面接bmodel文件,

$ cd path/to/model_yolov5s/workspace
$ bmrt_test --bmodel yolov5s_1684x_f16.bmodel
$ bmrt_test --bmodel yolov5s_1684x_int8_sym.bmodel
```

以最后一个命令输出为例（此处对日志做了部分截断处理）：

```shell
[BMRT][load_bmodel:983] INFO:pre net num: 0, load net num: 1
[BMRT][show_net_info:1358] INFO: ########################
[BMRT][show_net_info:1359] INFO: NetName: yolov5s, Index=0
[BMRT][show_net_info:1361] INFO: ---- stage 0 ----
[BMRT][show_net_info:1369] INFO:   Input 0) 'images' shape=[ 1 3 640 640 ] dtype=FLOAT32
[BMRT][show_net_info:1378] INFO:   Output 0) '350_Transpose_f32' shape=[ 1 3 80 80 85 ] ...
[BMRT][show_net_info:1378] INFO:   Output 1) '498_Transpose_f32' shape=[ 1 3 40 40 85 ] ...
[BMRT][show_net_info:1378] INFO:   Output 2) '646_Transpose_f32' shape=[ 1 3 20 20 85 ] ...
[BMRT][show_net_info:1381] INFO: ########################
[BMRT][bmrt_test:770] INFO:==> running network #0, name: yolov5s, loop: 0
[BMRT][bmrt_test:834] INFO:reading input #0, bytesize=4915200
[BMRT][print_array:702] INFO:  --> input_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ...
[BMRT][bmrt_test:982] INFO:reading output #0, bytesize=6528000
[BMRT][print_array:702] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0...
[BMRT][bmrt_test:982] INFO:reading output #1, bytesize=1632000
[BMRT][print_array:702] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0...
[BMRT][bmrt_test:982] INFO:reading output #2, bytesize=408000
[BMRT][print_array:702] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0...
[BMRT][bmrt_test:1014] INFO:net[yolov5s] stage[0], launch total time is 4122 us (npu 4009 normal 113 us)
[BMRT][bmrt_test:1017] INFO:+++ The network[yolov5s] stage[0] output_data +++
[BMRT][print_array:702] INFO:output data #0 shape: [1 3 80 80 85 ] < 0.301003    ...
[BMRT][print_array:702] INFO:output data #1 shape: [1 3 40 40 85 ] < 0 0.228689  ...
[BMRT][print_array:702] INFO:output data #2 shape: [1 3 20 20 85 ] < 1.00135     ...
[BMRT][bmrt_test:1058] INFO:load input time(s): 0.008914
[BMRT][bmrt_test:1059] INFO:calculate  time(s): 0.004132
[BMRT][bmrt_test:1060] INFO:get output time(s): 0.012603
[BMRT][bmrt_test:1061] INFO:compare    time(s): 0.006514
```

从上面输出可以看到以下信息：

# 编译TORCH模型

本章以 `yolov5s.pt` 为例，介绍如何编译迁移一个pytorch模型至BM1684X 平台运行。

本章需要安装TPU-MLIR。

## 安装TPU-MLIR

进入Docker容器，并执行以下命令安装TPU-MLIR：

```shell
$ pip install tpu_mlir[torch]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[torch]
```

## 准备工作目录

建立 `model_yolov5s_pt` 目录，并把模型文件和图片文件都放入 `model_yolov5s_pt` 目录中。

操作如下:

```shell
$ mkdir model_yolov5s_pt && cd model_yolov5s_pt
$ wget -O yolov5s.pt "https://github.com/sophgo/tpu-mlir/raw/master/regression/model/yolov5s.pt"
$ cp -rf tpu_mlir_resource/dataset/COCO2017 .
$ cp -rf tpu_mlir_resource/image .
$ mkdir workspace && cd workspace
```

## TORCH转MLIR

本例中的模型是 `RGB` 输入，mean和scale分别为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216`。

模型转换命令如下:

```shell
$ model_transform \
    --model_name yolov5s_pt \
    --model_def ../yolov5s.pt \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_pt_top_outputs.npz \
    --mlir yolov5s_pt.mlir
```

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是模型的输入文件。值得注意的是，目前仅支持静态模型，模型在编译前需要调用 `torch.jit.trace()` 以生成静态模型。

## MLIR转F16模型

将mlir文件转换成f16的bmodel，操作方法如下:

```shell
$ model_deploy \
    --mlir yolov5s_pt.mlir \
    --quantize F16 \
    --processor bm1684x \
    --test_input yolov5s_pt_in_f32.npz \
    --test_reference yolov5s_pt_top_outputs.npz \
    --model yolov5s_pt_1684x_f16.bmodel
```

编译完成后，会生成名为 `yolov5s_pt_1684x_f16.bmodel` 的文件。

## MLIR转INT8模型

### 生成校准表

转INT8模型前需要跑calibration，得到校准表; 这里用现有的100张来自COCO2017的图片举例，执行calibration:

```shell
$ run_calibration yolov5s_pt.mlir \
    --dataset ../COCO2017 \
    --input_num 100 \
    -o yolov5s_pt_cali_table
```

运行完成后会生成名为 `yolov5s_pt_cali_table` 的文件，该文件用于后续编译INT8模型的输入文件。

### 编译为INT8对称量化模型

转成INT8对称量化模型，执行如下命令:

```shell
$ model_deploy \
    --mlir yolov5s_pt.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_pt_cali_table \
    --processor bm1684x \
    --test_input yolov5s_pt_in_f32.npz \
    --test_reference yolov5s_pt_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --model yolov5s_pt_1684x_int8_sym.bmodel
```

编译完成后，会生成名为 `yolov5s_pt_1684x_int8_sym.bmodel` 的文件。

## 效果对比

利用 `detect_yolov5` 命令，对图片进行目标检测。

用以下代码分别来验证pytorch/f16/int8的执行结果。

pytorch模型的执行方式如下，得到 `dog_torch.jpg` :

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model ../yolov5s.pt \
    --output dog_torch.jpg
```

f16 bmodel的执行方式如下，得到 `dog_f16.jpg` :

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_pt_1684x_f16.bmodel \
    --output dog_f16.jpg
```

int8对称bmodel的执行方式如下，得到 `dog_int8_sym.jpg` :

```shell
$ detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_pt_1684x_int8_sym.bmodel \
    --output dog_int8_sym.jpg
```

对比结果如下:

由于运行环境不同，最终的效果和精度会有差异。

# 编译Caffe模型

本章以 `mobilenet_v2_deploy.prototxt` 和 `mobilenet_v2.caffemodel` 为例, 介绍如何编译迁移一个caffe模型至 BM1684X 平台运行。

本章需要安装TPU-MLIR。

## 安装TPU-MLIR

进入Docker容器，并执行以下命令安装TPU-MLIR：

```shell
$ pip install tpu_mlir[caffe]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[caffe]
```

## 准备工作目录

建立 `mobilenet_v2` 目录, 并把模型文件和图片文件都放入 `mobilenet_v2` 目录中。

操作如下:

```shell
$ mkdir mobilenet_v2 && cd mobilenet_v2
$ wget https://raw.githubusercontent.com/shicai/MobileNet-Caffe/master/mobilenet_v2_deploy.prototxt
$ wget https://github.com/shicai/MobileNet-Caffe/raw/master/mobilenet_v2.caffemodel
$ cp -rf tpu_mlir_resource/dataset/ILSVRC2012 .
$ cp -rf tpu_mlir_resource/image .
$ mkdir workspace && cd workspace
```

## Caffe转MLIR

本例中的模型是 `BGR` 输入, mean和scale分别为 `103.94,116.78,123.68` 和 `0.017,0.017,0.017` 。

模型转换命令如下:

```shell
$ model_transform \
    --model_name mobilenet_v2 \
    --model_def ../mobilenet_v2_deploy.prototxt \
    --model_data ../mobilenet_v2.caffemodel \
    --input_shapes [[1,3,224,224]] \
    --resize_dims=256,256 \
    --mean 103.94,116.78,123.68 \
    --scale 0.017,0.017,0.017 \
    --pixel_format bgr \
    --test_input ../image/cat.jpg \
    --test_result mobilenet_v2_top_outputs.npz \
    --mlir mobilenet_v2.mlir
```

转成mlir文件后, 会生成一个 `${model_name}_in_f32.npz` 文件, 该文件是模型的输入文件。

## MLIR转F32模型

将mlir文件转换成f32的bmodel, 操作方法如下:

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize F32 \
    --processor bm1684x \
    --test_input mobilenet_v2_in_f32.npz \
    --test_reference mobilenet_v2_top_outputs.npz \
    --model mobilenet_v2_1684x_f32.bmodel
```

编译完成后, 会生成名为 `${model_name}_1684x_f32.bmodel` 的文件。

## MLIR转INT8模型

### 生成校准表

转INT8模型前需要跑calibration, 得到校准表; 输入数据的数量根据情况准备100~1000张左右。

然后用校准表, 生成对称或非对称bmodel。如果对称符合需求, 一般不建议用非对称, 因为非对称的性能会略差于对称模型。

这里用现有的100张来自ILSVRC2012的图片举例, 执行calibration:

```shell
$ run_calibration mobilenet_v2.mlir \
    --dataset ../ILSVRC2012 \
    --input_num 100 \
    -o mobilenet_v2_cali_table
```

运行完成后会生成名为 `${model_name}_cali_table` 的文件, 该文件用于后续编译INT8模型的输入文件。

### 编译为INT8对称量化模型

转成INT8对称量化模型, 执行如下命令:

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize INT8 \
    --calibration_table mobilenet_v2_cali_table \
    --processor bm1684x \
    --test_input mobilenet_v2_in_f32.npz \
    --test_reference mobilenet_v2_top_outputs.npz \
    --tolerance 0.96,0.70 \
    --model mobilenet_v2_1684x_int8.bmodel
```

编译完成后, 会生成名为 `${model_name}_1684x_int8.bmodel` 的文件。

# 编译TFLite模型

本章以 `lite-model_mobilebert_int8_1.tflite` 模型为例, 介绍如何编译迁移一个TFLite模型至 BM1684X 平台运行。

本章需要安装TPU-MLIR。

## 安装TPU-MLIR

进入Docker容器，并执行以下命令安装TPU-MLIR：

```shell
$ pip install tpu_mlir[tensorflow]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[tensorflow]
```

## 准备工作目录

建立 `mobilebert_tf` 目录, 注意是与tpu-mlir同级目录; 并把测试图片文件放入 `mobilebert_tf` 目录中。

操作如下:

```shell
$ mkdir mobilebert_tf && cd mobilebert_tf
$ wget -O lite-model_mobilebert_int8_1.tflite https://storage.googleapis.com/tfhub-lite-models/iree/lite-model/mobilebert/int8/1.tflite
$ cp -rf tpu_mlir_resource/npz_input/squad_data.npz .
$ mkdir workspace && cd workspace
```

## TFLite转MLIR

模型转换命令如下:

```shell
$ model_transform \
    --model_name mobilebert_tf \
    --mlir mobilebert_tf.mlir \
    --model_def ../lite-model_mobilebert_int8_1.tflite \
    --test_input ../squad_data.npz \
    --test_result mobilebert_tf_top_outputs.npz \
    --input_shapes [[1,384],[1,384],[1,384]] \
    --channel_format none
```

转成mlir文件后, 会生成一个 `mobilebert_tf_in_f32.npz` 文件, 该文件是模型的输入文件。

## MLIR转INT8模型

该模型是tflite int8模型, 可以按如下参数转成模型:

```shell
$ model_deploy \
    --mlir mobilebert_tf.mlir \
    --quantize INT8 \
    --processor bm1684x \
    --test_input mobilebert_tf_in_f32.npz \
    --test_reference mobilebert_tf_top_outputs.npz \
    --model mobilebert_tf_bm1684x_int8.bmodel
```

编译完成后, 会生成名为 `mobilebert_tf_bm1684x_int8.bmodel` 的文件。

# 量化与量化调优

神经网络在大规模部署时候，往往对吞吐量也就是推理时间有较高要求，硬件也专门对低比特计算进行了优化，其算力更加突出。所以以尽量高的精度进行低比特量化就显得尤为重要。
但是要保持高精度和高吞吐率，网络往往需要以混合精度方式运行，即大部分算子以低比特定点计算，少部分以浮点进行计算。如何决定哪些算子使用浮点往往与网络和网络权重有直接关系，需要根据网络特点来选择。

TPU-MLIR所采用的混合精度方式为搜索网络中不适于低比特量化的层生成 `quantize_table` ，用以在 `model_deploy` 阶段指定这些层采用较高比特的量化方式。

本章首先会对TPU-MLIR当前的全int8对称量化进行介绍,然后对TPU-MLIR现有的 `quantize_table` 自动生成工具使用方式进行介绍。

## TPU-MLIR全int8对称量化

TPU-MLIR默认采用全int8对称量化,全int8是指除编译器默认执行浮点运算的算子(如 `layernorm` )外,其余算子均进行int8量化。本节介绍如何使用TPU-MLIR全int8对称量化工具。

当按照之前教程通过 `model_transform` 命令将模型生成对应mlir文件之后,若要对模型进行int8对称量化,还需要通过 `run_calibration` 命令生成校准表 `cali_table` ,对于不同类型模型该如何使用
`run_calibration` 命令的参数,从而使得生成的量化模型精度较好,下面将给出详细指导。

### run_calibration流程介绍

下图量化部分展示了当前 `run_calibration` 整体流程,其中包括了自动混精模块 `search_qtable`,自动校准方法选择模块 `search_threshold` ,跨层权重均衡模块 `weight_equalization`
以及偏置修正模块 `bias_correction` 等,后面小节我们将结合实际情况给出上述方法的使用细节。

### run_calibration参数介绍

下表给出了 `run_calibration` 命令的参数介绍。

| 参数 | 描述 |
|------|------|
| mlir_file | mlir文件 |
| sq | 开启SmoothQuant |
| we | 开启weight_equalization |
| bc | 开启bias_correction |
| dataset | 校准数据集 |
| data_list | 样本列表 |
| input_num | 校准样本数量 |
| inference_num | search_qtable 和 search_threshold 推理过程所需图片数量,默认为30 |
| bc_inference_num | bias_correction 推理过程所需图片数量,默认为30 |
| tune_list | tuning用到的样本列表 |
| tune_num | tuning的图像数量 |
| histogram_bin_num | 指定 kld 计算的直方图 bin 数量,默认为2048 |
| expected_cos | 期望search_qtable混精模型输出与浮点模型输出的相似度,取值范围[0,1],默认为0.99 |
| min_layer_cos | bias_correction中该层量化输出与浮点输出的相似度下限,当低于该下限时需要对该层进行补偿,取值范围[0,1],默认为0.99 |
| max_float_layers | search_qtable 设置浮点层数量,默认为5 |
| processor | 处理器类型,默认为bm1684x |
| cali_method | 选择校准模式;不添加该参数默认为KLD校准。"use_percentile9999"采用99.99分位作为门限。"use_max"采用绝对值最大值作为门限。"use_torch_observer_for_cali"采用torch的observer进行校准。"use_mse"采用octav进行校准。 |
| fp_type | search_qtable浮点层数据类型 |
| post_process | 后处理路径 |
| global_compare_layers | 指定全局对比层，例如 layer1,layer2 或 layer1:0.3,layer2:0.7 |
| search | 指定搜索类型,其中包括search_qtable,search_threshold,false。其中默认为false,不开启搜索 |
| transformer | 是否是transformer模型,search_qtable中如果是transformer模型可分配指定加速策略,默认为False |
| quantize_method_list | search_qtable用来搜索的门限方法,默认为MSE,可选择范围为MSE,KL,MAX,Percentile9999 |
| benchmark_method | 指定search_threshold中相似度计算方法,默认为cos |
| kurtosis_analysis | 指定生成各层激活值的kurtosis |
| part_quantize | 指定模型部分量化,获得cali_table同时会自动生成qtable。可选择N_mode,H_mode,custom_mode,H_mode通常精度较好 |
| custom_operator | 指定需要量化的算子,配合开启上述custom_mode后使用 |
| part_asymmetric | 指定当开启对称量化后,模型某些子网符合特定pattern时,将对应位置算子改为非对称量化 |
| mix_mode | 指定search_qtable特定的混精类型,目前支持8_16和4_8两种 |
| cluster | 指定search_qtable寻找敏感层时采用聚类算法 |
| quantize_table | search_qtable输出的混精度量化表 |
| o | 输出门限表 |
| debug_cmd | debug命令 |
| debug_log | 日志输出级别 |

### run_calibration参数使用介绍

根据用户需求以及用户对模型本身和量化的了解程度,本节也针对性的给出了不同情况下 `run_calibration` 参数使用的方式。

| 场景 | 描述 | 量化速度 | 校准方法 | 推荐方法 |
|------|------|----------|----------|----------|
| case1 | 模型初次量化 | 不敏感 | 不清楚 | search_threshold |
| case2 | 模型初次量化 | / | 清楚 | cali_method直接选择对应校准方法 |
| case3 | 模型初次量化 | 敏感 | 不清楚 | cali_method选择固定校准方法,具体校准方法选择细节可看后续章节 |
| case4 | 模型量化后在bm1684处理器上部署精度无法满足需求 | / | / | 开启sq、we和bc方法 |

**case1**:当对您的模型进行初步量化时,也就是第一次使用 `run_calibration` 命令,此时您对当前模型所适应的校准方法并不清楚,并且对量化速度并不敏感,这里推荐您使用 `search_threshold` 方法,该方法可以
自动选择对应您当前模型最适合的校准方法,并且输出该种方法生成的校准表 `cali_table` 到您指定的输出路径。同时也会生成一个log日志文件 `Search_Threshold`,里面记录了不同校准方法的量化信息。具体操作如下:

```shell
$ run_calibration mlir.file \
    --dataset data_path \
    --input_num 100 \
    --processor bm1684x \
    --search search_threshold \
    --inference_num 30 \
    -o cali_table
```

注意事项:1.此时需要选择processor参数,该参数对应模型想要部署的处理器平台,当前默认是bm1684x。2. `inference_num` 对应 `search_threshold` 过程所需的推理数据数量(该数据将从您给定的dataset中抽取)。
`inference_num` 越大, `search_threshold` 结果也更加准确,但所需的量化时间也更长,这里默认 `inference_num` 等于30,可根据实际情况自定义。

**case2**:当对您的模型进行初步量化时您已经清楚该模型适合于何种校准方法,此时可以直接根据 `cali_method` 参数去选择固定的校准方法。具体操作如下:

```shell
$ run_calibration mlir.file \
    --dataset data_path \
    --input_num 100 \
    --cali_method use_mse \
    -o cali_table
```

注意事项:1.当不添加 `cali_method` 参数时,此时将采用默认的KLD校准方法。2.目前 `cali_method` 支持五种选择,包括 `use_mse`, `use_max` , `use_percentile9999` , `use_aciq_gauss` 以及 `use_aciq_laplace`。

**case3**:当您对量化时间比较敏感,希望尽可能快的生成校准表 `cali_table` ,但您不清楚该如何选择校准方法时,这里推荐您直接根据 `cali_method` 参数去选择固定的校准方法,相比于TPU-MLIR V1.8版本的量化速度,
V1.9版本的单个校准方法量化速度提升100%,因此所需时间也平均降低到之前的50%左右,加速效果明显。在V1.9版本校准方法中, `use_mse` 是平均量化速度最快的。对于校准方法的选择,可以参考以下几点经验性的结论:
1.当您的模型是不带有attention结构的非transformer模型,可以选择 `use_mse` 校准方法。具体操作如下:

```shell
$ run_calibration mlir.file \
    --dataset data_path \
    --input_num 100 \
    --cali_method use_mse \
    -o cali_table
```

或者也可选择默认的KLD校准方法。具体操作如下:

```shell
$ run_calibration mlir.file \
    --dataset data_path \
    --input_num 100 \
    -o cali_table
```

如果上述两种方法精度均不满足需求,可能需要采取混合精度策略或者混合门限方法,具体介绍可看后面小节。

2.当您的模型是带有attention结构的transformer模型,可以选择 `use_mse` 校准方法,如果 `use_mse` 校准方法效果略差,则可以尝试 `use_max` 校准方法,具体操作如下:

```shell
$ run_calibration mlir.file \
    --dataset data_path \
    --input_num 100 \
    --cali_method use_max \
    -o cali_table
```

如果 `use_max` 效果也无法满足需求,此时需要采取混合精度策略,可依据后续介绍的混精方法进行尝试。

除去上面总体的选择规则,也提供一些选择校准方法的细节:1.如果您的模型是yolo系列的检测模型,建议采取默认的KLD校准方法。2.如果您的模型是有多个输出的分类模型,建议采取默认的KLD校准方法。

**case4**:当您的模型是部署在bm1684处理器上时,如果通过上述方法获得的全int8量化模型精度较差,可以尝试开启SmoothQuant(`sq`)、跨层权重均衡( `we`)和偏置修正( `bc`),具体操作就是在原先的命令上面添加 `sq`、`we` 和 `bc` 参数。如果使用了
`search_threshold` 进行搜索,添加sq、we和bc操作如下:

```shell
$ run_calibration mlir.file \
    --sq \
    --we \
    --bc \
    --dataset data_path \
    --input_num 100 \
    --processor bm1684 \
    --search search_threshold \
    --inference_num 30 \
    --bc_inference_num 100 \
    -o cali_table
```

如果使用 `cali_method` 选择固定校准方法,下面以 `use_mse` 为例添加 `sq`、`we` 和 `bc` 方法,具体操作如下:

```shell
$ run_calibration mlir.file \
    --sq \
    --we \
    --bc \
    --dataset data_path \
    --input_num 100 \
    --processor bm1684 \
    --cali_method use_mse \
    --bc_inference_num 100 \
    -o cali_table
```

如果您采用的是默认的KLD校准方法,去掉 `cali_method` 参数即可。

注意事项:1.这里需要指定processor参数为bm1684。2. `bc_inference_num` 参数是使用 `bc` 量化方法时所需的推理数据数量(该数据将从您给定的dataset中抽取),这里图片数量不应太少。3. `sq`、`we` 和 `bc` 方法可单独使用,可以仅仅选择 `we` 方法,在操作上直接去掉 `sq` 和 `bc` 参数即可。4. run_calibration过程中会检查每个算子，找到进行shape计算的算子在当前目录生成名为net_name_shape_ops的qtable，将这些算子设置为不量化，里面内容可以手动和下面混精的配置合并作为qtable用在model_deploy中。

## TPU-MLIR混合精度量化概述

TPU-MLIR支持模型混精度量化,其核心步骤在于获得记录算子名称及其量化类型的 `quantize_table`,后称 `qtable`。

TPU-MLIR支持两种获取 `qtable` 的获取路径,对于典型模型,TPU-MLIR提供基于经验的 `pattern-match` 方法。对于特殊模型或非典型模型,TPU-MLIR提供三种基于检索的方法,分别为 `search_qtable` , `run_sensitive_layer` 和 `fp_forward` 。
在后续四个章节中会详细介绍上述四种方法工具

### pattern-match

`pattern-match` 方法集成于 `run_calibration` 中,不需要显示指定参数,当前共有两类模型提供经验 `qtable` ,一类为 YOLO 系列,另一类为 BERT 等 Transformer 系列。
在获得 `cali_table` 后,如果模型匹配上现有pattern,则会在 `path/to/cali_table/` 文件夹下生成qtable。

#### YOLO系列自动混精度方法

当前共支持YOLOV5,V6,V7,V8,V9,V10,11,12系列模型。

YOLO系列模型较为经典,使用广泛,在官方支持的模型导出时,通常会将数值差异较大的不同后处理分支合并输出,导致模型量化为全INT8精度损失大。
由于YOLO系列模型通常具有相似结构特征,即三级maxpool结构, `pattern-match` 会自动判断模型是否属于YOLO系列,如是,进一步识别后处理部分算子,将这些算子设置为不量化,生成qtable,该qtable可以手动和下面混精的配置合并作为qtable用在model_deploy中。
以yolov8模型输出为例:

```shell
['top.MaxPool', 'top.MaxPool', 'top.MaxPool', 'top.Concat'] (Name: yolo_block) is a subset of the main list. Count: 1
The [yolov6_8_9_11_12] post-processing pattern matches this model. Block count: 1
The [yolov6_8_9_11_12] post-processing pattern is: ['top.Sub', 'top.Add', 'top.Add', 'top.Sub', 'top.MulConst', 'top.Concat', 'top.Mul', 'top.Concat']
The qtable has been generated in: path/to/cali_table/qtable !!!
```

# transformer系列自动混精度方法

当前共支持BERT, EVA, DeIT, Swin, CSWin, ViT, DETR系列模型。

如识别到上述模块,会将Add后的LayerNorm,SiLU,GELU算子设置为不量化。同时,ViT会识别Softmax/GELU后的MatMul算子；EVA会识别Add,SiLU->Mul后的MatMul算子；
Swin会识别Add,Depth2Space和Reshape->LayerNorm前的Permute算子；DeIT会识别非Conv,Scale,Reshape及非LayerNorm/Reshape后的MatMul外所有算子。将这些算子设置为不量化,生成qtable。

## search_qtable

`search_qtable` 是集成于 `run_calibration` 中的混精功能,当全int8量化精度无法满足需求时,需要采用混合精度方法,也就是将部分算子设置为浮点运算。
`search_qtable` 是对于 `run_sensitive_layer` 的优化版本。相比 `run_sensitive_layer`, `search_qtable` 速度更快,支持更多自定义参数。
本节以检测网络 `mobilenet-v2` 网络模型为例, 介绍如何使用 `search_qtable`。

本节需要安装TPU-MLIR。

### 安装TPU-MLIR

```shell
$ pip install tpu_mlir[all]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[all]
```

### 准备工作目录

建立 `mobilenet-v2` 目录, 并把模型文件和图片文件都放入 `mobilenet-v2` 目录中。

操作如下:

```shell
$ mkdir mobilenet-v2 && cd mobilenet-v2
$ wget https://github.com/sophgo/tpu-mlir/releases/download/v1.4-beta.0/mobilenet_v2.pt
$ cp -rf tpu_mlir_resource/dataset/ILSVRC2012 .
$ mkdir workspace && cd workspace
```

### 测试Float和INT8对称量化模型分类效果

如上述章节介绍的转模型方法, 这里不做参数说明, 只有操作过程。

#### 步骤1: 转成FP32 mlir

```shell
$ model_transform.py \
    --model_name mobilenet_v2 \
    --model_def ../mobilenet_v2.pt \
    --input_shapes [[1,3,224,224]] \
    --resize_dims 256,256 \
    --mean 123.675,116.28,103.53 \
    --scale 0.0171,0.0175,0.0174 \
    --pixel_format rgb \
    --mlir mobilenet_v2.mlir
```

#### 步骤2: 生成calibartion table

这里我们采用 `use_mse` 方法进行校准。

```shell
$ run_calibration.py mobilenet_v2.mlir \
    --dataset ../ILSVRC2012 \
    --input_num 100 \
    --cali_method use_mse \
    -o mobilenet_v2_cali_table
```

#### 步骤3: 转FP32 bmodel

```shell
$ model_deploy.py \
    --mlir mobilenet_v2.mlir \
    --quantize F32 \
    --processor bm1684 \
    --model mobilenet_v2_bm1684_f32.bmodel
```

#### 步骤4: 转对称量化模型

```shell
$ model_deploy.py \
    --mlir mobilenet_v2.mlir \
    --quantize INT8 \
    --processor bm1684 \
    --calibration_table mobilenet_v2_cali_table \
    --model mobilenet_v2_bm1684_int8_sym.bmodel
```

#### 步骤5: 验证FP32模型和INT8对称量化模型

`classify_mobilenet_v2` 是已经写好的验证程序，可以用来对 `mobilenet_v2` 网络进行验证。执行过程如下，FP32模型：

```shell
$ classify_mobilenet_v2.py \
    --model_def mobilenet_v2_bm1684_f32.bmodel \
    --input ../ILSVRC2012/n02090379_7346.JPEG \
    --output mobilenet_v2_fp32_bmodel.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片 `mobilenet_v2_fp32_bmodel_1.JPEG` 中，正确结果 `sleeping bag` 排在第一名：

INT8对称量化模型：

```shell
$ classify_mobilenet_v2.py \
    --model_def mobilenet_v2_bm1684_int8_sym.bmodel \
    --input ../ILSVRC2012/n02090379_7346.JPEG \
    --output mobilenet_v2_INT8_sym_bmodel.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片 `mobilenet_v2_INT8_sym_bmodel_1.JPEG` 中，正确结果 `sleeping bag` 排在第二名：

## 转成混精度量化模型

在转int8对称量化模型的基础上, 执行如下步骤。

#### 步骤1: 执行search_qtable命令

`search_qtable` 功能目前集成于 `run_calibration` 流程中,因此在使用时只需要在 `run_calibration` 命令中添加相关参数即可。 `run_calibration` 中与 `search_qtable` 相关参数说明如下:

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| 无 | 是 | 指定mlir文件 |
| dataset | 否 | 指定输入样本的目录, 该路径放对应的图片, 或npz, 或npy |
| data_list | 否 | 指定样本列表, 与dataset必须二选一 |
| processor | 是 | 指定模型将要用到的平台, 支持bm1690, bm1688, bm1684x, bm1684, cv186x, cv183x, cv182x, cv181x, cv180x |
| fp_type | 否 | 指定混精度使用的float类型, 支持auto,F16,F32,BF16，默认为auto，表示由程序内部自动选择 |
| input_num | 是 | 指定用于量化的输入样本数量 |
| inference_num | 否 | 指定用于推理的输入样本数量, 默认用30个 |
| max_float_layers | 否 | 指定用于生成qtable的op数量, 默认用5个 |
| tune_list | 否 | 指定用于调整threshold的样本路径 |
| tune_num | 否 | 指定用于调整threshold的样本数量，默认为5 |
| post_process | 否 | 用户自定义后处理文件路径, 默认为空 |
| expected_cos | 否 | 指定期望网络最终输出层的最小cos值,一般默认为0.99即可，越小时可能会设置更多层为浮点计算 |
| debug_cmd | 否 | 指定调试命令字符串，开发使用, 默认为空 |
| global_compare_layers | 否 | 指定用于替换最终输出层的层，并用于全局比较,例如： `layer1,layer2` 或 `layer1:0.3,layer2:0.7` |
| search | 是 | 指定搜索类型,其中包括 `search_qtable`, `search_threshold` ,false。这里需要选择 `search_qtable` |
| transformer | 否 | 是否是transformer模型,search_qtable中如果是transformer模型可分配指定加速策略,默认是False |
| quantize_method_list | 否 | search_qtable用来搜索的校准方法,默认仅使用MSE校准方法,可选择 `MSE`, `KL`, `MAX`, `Percentile9999` |
| quantize_table | 是 | 输出混精度量化表 |
| calibration_table | 是 | 校准表输出路径 |

`search_qtable` 支持用户自定义的后处理方法 `post_process_func.py` ，可以放在当前工程目录下，也可以放在其他位置，如果放在其他位置需要在 `post_process` 中指明文件的完整路径。后处理方法函数名称需要定义为 `PostProcess` ，输入数据为网络的输出，输出数据为后处理结果。创建 `post_process_func.py` 文件，其示例内容如下：

```python
def PostProcess(data):
    print("in post process")
    return data
```

`search_qtable` 可以自定义混合门限的校准方法,由参数 `quantize_method_list` 控制,默认仅采用 `MSE` 校准方法进行搜索。当你想要使用KLD和MSE混合搜索时,参数 `quantize_method_list` 输入 `KL,MSE` 即可。 `search_qtable` 针对transformer模型设置了加速策略,如果模型是带有attention结构的transformer模型,可以设置参数 `transformer` 为True。

使用 `search_qtable` 搜索损失较大的layer,注意尽量使用bad cases进行搜索。

本例中采用100张图片做量化,30张图片做推理,使用KLD和MSE校准方法混合搜索,执行命令如下:

```shell
$ run_calibration.py mobilenet_v2.mlir \
    --dataset ../ILSVRC2012 \
    --input_num 100 \
    --inference_num 30 \
    --expected_cos 0.99 \
    --quantize_method_list KL,MSE \
    --search search_qtable \
    --transformer False \
    --processor bm1684 \
    --post_process post_process_func.py \
    --quantize_table mobilenet_v2_qtable \
    --calibration_table mobilenet_v2_cali_table \
```

执行完后最后输出如下打印:

```shell
 the layer input3.1 is 0 sensitive layer, loss is 0.004858517758037473, type is top.Conv
 the layer input5.1 is 1 sensitive layer, loss is 0.002798812150635266, type is top.Scale
 the layer input11.1 is 2 sensitive layer, loss is 0.0015642610676610547, type is top.Conv
 the layer input13.1 is 3 sensitive layer, loss is 0.0009357141882855302, type is top.Scale
 the layer input6.1 is 4 sensitive layer, loss is 0.0009211346574943269, type is top.Conv
 the layer input2.1 is 5 sensitive layer, loss is 0.0007767164275293004, type is top.Scale
 the layer input0.1 is 6 sensitive layer, loss is 0.0006842551513905892, type is top.Conv
 the layer input128.1 is 7 sensitive layer, loss is 0.0003780628201499603, type is top.Conv
 ......
 run result:
 int8 outputs_cos:0.986809 old
 mix model outputs_cos:0.993372
 Output mix quantization table to mobilenet_v2_qtable
 total time:667.644282579422
 success search qtable
```

上面int8 outputs_cos表示int8模型网络输出和fp32的cos相似度，mix model outputs_cos表示前五个敏感层使用混精度后网络输出的cos相似度，total time表示搜索时间为667秒，
另外，生成的混精度量化表 `mobilenet_v2_qtable`, 内容如下:

```shell
# op_name   quantize_mode
input3.1 F32
input5.1 F32
input11.1 F32
input13.1 F32
input6.1 F32
```

该表中, 第一列表示相应的layer, 第二列表示类型, 支持的类型有F32/F16/BF16/INT8。 `search_qtable` 会根据用户自定义的 `expected_cos` 参数值来确定混精量化表中混精层的数量,举例来说，
如果 `expected_cos` 参数值等于0.99,那么混精量化表中混精层个数对应着混精模型输出比对达到该水平的最小混精层数，当然混精量化表中混精层数会根据模型算子数量设置上限,如果最小混精层数超过上限，
那么只会取该上限对应的混精层。与此同时，也会生成一个log日志文件 `Search_Qtable`, 内容如下:

```shell
INFO:root:quantize_method_list =['KL', 'MSE']
INFO:root:run float mode: mobilenet_v2.mlir
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:all_int8_cos=0.9868090914371674
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:layer name check pass !
INFO:root:all layer number: 117
INFO:root:all layer number no float: 116
INFO:root:transformer model: False, all search layer number: 116
INFO:root:Global metrics layer is : None
INFO:root:start to handle layer: input0.1, type: top.Conv
INFO:root:adjust layer input0.1 th, with method KL, and threshlod 9.442267236793155
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:outputs_cos_los = 0.0006842551513905892
INFO:root:adjust layer input0.1 th, with method MSE, and threshlod 9.7417731
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:outputs_cos_los = 0.0007242344141149548
INFO:root:layer input0.1, layer type is top.Conv, best_th = 9.442267236793155, best_method = KL, best_cos_loss = 0.0006842551513905892
.....
```

日志文件首先给出了自定义的参数,包括混合门限所使用的校准方法 `quantize_method_list`,要搜索的op数量all search layer number以及
是否是transformer model等信息。然后记录了每个op在给定校准方法(此处是MSE和KL)下得到的threshold,
同时给出了在只对该op使用对应threshold做int8计算后的混精度模型与原始float模型输出的相似度的loss(1-余弦相似度)。
此外,日志还包含了屏幕端输出的每个op的loss信息以及最后的混精度模型与原始float模型的余弦相似度。
用户可以使用程序输出的qtable,也可以根据loss信息对qtable进行修改,然后生成混精度模型。
在 `search_qtable` 结束后,最优的threshold会被更新到一个新的量化表 `new_cali_table.txt`,
该量化表存储在当前工程目录下，在生成混精度模型时需要调用新量化表。

#### 步骤2: 生成混精度量化模型

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize INT8 \
    --processor bm1684 \
    --calibration_table new_cali_table.txt \
    --quantize_table mobilenet_v2_qtable \
    --model mobilenet_v2_bm1684_int8_mix.bmodel
```

#### 步骤3: 验证混精度模型

```shell
$ classify_mobilenet_v2 \
    --model_def mobilenet_v2_bm1684_int8_mix.bmodel \
    --input ../ILSVRC2012/n02090379_7346.JPEG \
    --output mobilenet_v2_INT8_mix_bmodel_1.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片 `mobilenet_v2_INT8_mix_bmodel_1.JPEG` 中，正确结果 `sleeping bag` 排在第一名：

# run_sensitive_layer

本节以检测网络 `mobilenet-v2` 网络模型为例，介绍如何使用敏感层搜索。

本节需要安装TPU-MLIR。

## 安装TPU-MLIR

```shell
$ pip install tpu_mlir[all]
# or
$ pip install tpu_mlir-*-py3-none-any.whl[all]
```

## 准备工作目录

建立 `mobilenet-v2` 目录，并把模型文件和图片文件都放入 `mobilenet-v2` 目录中。

操作如下：

```shell
$ mkdir mobilenet-v2 && cd mobilenet-v2
$ wget https://github.com/sophgo/tpu-mlir/releases/download/v1.4-beta.0/mobilenet_v2.pt
$ cp -rf tpu_mlir_resource/dataset/ILSVRC2012 .
$ mkdir workspace && cd workspace
```

## 测试Float和INT8对称量化模型分类效果

如前面章节介绍的转模型方法，这里不做参数说明，只有操作过程。

### 步骤0: 转成FP32 mlir

```shell
$ model_transform \
    --model_name mobilenet_v2 \
    --model_def ../mobilenet_v2.pt \
    --input_shapes [[1,3,224,224]] \
    --resize_dims 256,256 \
    --mean 123.675,116.28,103.53 \
    --scale 0.0171,0.0175,0.0174 \
    --pixel_format rgb \
    --mlir mobilenet_v2.mlir
```

### 步骤1: 生成calibartion table

```shell
$ run_calibration mobilenet_v2.mlir \
    --dataset ../ILSVRC2012 \
    --input_num 100 \
    -o mobilenet_v2_cali_table
```

### 步骤2: 转FP32 bmodel

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize F32 \
    --processor bm1684 \
    --model mobilenet_v2_bm1684_f32.bmodel
```

### 步骤3: 转对称量化模型

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize INT8 \
    --processor bm1684 \
    --calibration_table mobilenet_v2_cali_table \
    --model mobilenet_v2_bm1684_int8_sym.bmodel
```

### 步骤4: 验证FP32模型和INT8对称量化模型

classify_mobilenet_v2是已经写好的验证程序，可以用来对mobilenet_v2网络进行验证。执行过程如下，FP32模型：

```shell
$ classify_mobilenet_v2 \
    --model_def mobilenet_v2_bm1684_f32.bmodel \
    --input ../ILSVRC2012/n01440764_9572.JPEG \
    --output mobilenet_v2_fp32_bmodel.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片 `mobilenet_v2_fp32_bmodel.JPEG` 中，正确结果tench排在第一名。

INT8对称量化模型：

```shell
$ classify_mobilenet_v2 \
    --model_def mobilenet_v2_bm1684_int8_sym.bmodel \
    --input ../ILSVRC2012/n01440764_9572.JPEG \
    --output mobilenet_v2_INT8_sym_bmodel.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片 `mobilenet_v2_INT8_sym_bmodel.JPEG` 中，正确结果tench排在第一名。

## 转成混精度量化模型

在转int8对称量化模型的基础上，执行如下步骤。

### 步骤0: 进行敏感层搜索

使用 `run_sensitive_layer` 搜索损失较大的layer，注意尽量使用bad cases进行敏感层搜索，相关参数说明如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| 无 | 是 | 指定mlir文件 |
| dataset | 否 | 指定输入样本的目录，该路径放对应的图片，或npz，或npy |
| data_list | 否 | 指定样本列表，与dataset必须二选一 |
| calibration_table | 是 | 输入校准表 |
| processor | 是 | 指定模型将要用到的平台，支持bm1690, bm1688, bm1684x, bm1684, cv186x, cv183x, cv182x, cv181x, cv180x |
| fp_type | 否 | 指定混精度使用的float类型，支持auto,F16,F32,BF16，默认为auto，表示由程序内部自动选择 |
| input_num | 否 | 指定用于量化的输入样本数量，默认用10个 |
| inference_num | 否 | 指定用于推理的输入样本数量，默认用10个 |
| max_float_layers | 否 | 指定用于生成qtable的op数量，默认用5个 |
| tune_list | 否 | 指定用于调整threshold的样本路径 |
| tune_num | 否 | 指定用于调整threshold的样本数量，默认为5 |
| histogram_bin_num | 否 | 指定用于kld方法中使用的bin数量，默认为2048 |
| post_process | 否 | 用户自定义后处理文件路径，默认为空 |
| expected_cos | 否 | 指定期望网络最终输出层的最小cos值，一般默认为0.99即可，越小时可能会设置更多层为浮点计算 |
| debug_cmd | 否 | 指定调试命令字符串，开发使用，默认为空 |
| o | 是 | 输出混精度量化表 |
| global_compare_layers | 否 | 指定用于替换最终输出层的层，并用于全局比较，例如：`layer1,layer2` 或 `layer1:0.3,layer2:0.7` |
| fp_type | 否 | 指定混合精度的浮点类型 |

敏感层搜索支持用户自定义的后处理方法 `post_process_func.py` ，可以放在当前工程目录下，也可以放在其他位置，如果放在其他位置需要在 `post_process` 中指明文件的完整路径。后处理方法函数名称需要定义为 `PostProcess` ，输入数据为网络的输出，输出数据为后处理结果。创建 `post_process_func.py` 文件，其示例内容如下：

```python
def PostProcess(data):
    print("in post process")
    return data
```

本例中采用100张图片做量化，30张图片做推理，执行命令如下：

```shell
$ run_sensitive_layer mobilenet_v2.mlir \
    --dataset ../ILSVRC2012 \
    --input_num 100 \
    --inference_num 30 \
    --calibration_table mobilenet_v2_cali_table \
    --processor bm1684 \
    --post_process post_process_func.py \
    -o mobilenet_v2_qtable
```

执行完后最后输出如下打印：

```shell
the layer input3.1 is 0 sensitive layer, loss is 0.008808857469573828, type is top.Conv
the layer input11.1 is 1 sensitive layer, loss is 0.0016958347875666302, type is top.Conv
the layer input128.1 is 2 sensitive layer, loss is 0.0015641432811860367, type is top.Conv
the layer input130.1 is 3 sensitive layer, loss is 0.0014325751094084183, type is top.Scale
the layer input127.1 is 4 sensitive layer, loss is 0.0011817314259702227, type is top.Add
the layer input13.1 is 5 sensitive layer, loss is 0.001018420214596527, type is top.Scale
the layer 787 is 6 sensitive layer, loss is 0.0008603856180608993, type is top.Scale
the layer input2.1 is 7 sensitive layer, loss is 0.0007558935451825732, type is top.Scale
the layer input119.1 is 8 sensitive layer, loss is 0.000727441637624282, type is top.Add
the layer input0.1 is 9 sensitive layer, loss is 0.0007138056757098887, type is top.Conv
the layer input110.1 is 10 sensitive layer, loss is 0.000662179506136229, type is top.Conv
......
run result:
int8 outputs_cos:0.978803 old
mix model outputs_cos:0.989258
Output mix quantization table to mobilenet_v2_qtable
total time:402.15848112106323
success sensitive layer search
```

上面int8 outputs_cos表示int8模型原本网络输出和fp32的cos相似度，mix model outputs_cos表示前五个敏感层使用混精度后网络输出的cos相似度，total time表示搜索时间为402秒，
另外，生成的混精度量化表 `mobilenet_v2_qtable`，内容如下：

```shell
# op_name   quantize_mode
input3.1 F32
input11.1 F32
input128.1 F32
input130.1 F32
input127.1 F32
```

该表中，第一列表示相应的layer，第二列表示类型，支持的类型有F32/F16/BF16/INT8。
与此同时，也会生成一个log日志文件 `SensitiveLayerSearch`，内容如下：

```shell
INFO:root:start to handle layer: input3.1, type: top.Conv
INFO:root:adjust layer input3.1 th, with method MAX, and threshlod 5.5119305
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:outputs_cos_los = 0.014830573787862011
INFO:root:adjust layer input3.1 th, with method Percentile9999, and threshlod 4.1202815
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:outputs_cos_los = 0.011843443367980822
INFO:root:adjust layer input3.1 th, with method KL, and threshlod 2.6186381997094728
INFO:root:run int8 mode: mobilenet_v2.mlir
INFO:root:outputs_cos_los = 0.008808857469573828
INFO:root:layer input3.1, layer type is top.Conv, best_th = 2.6186381997094728, best_method = KL, best_cos_loss = 0.008808857469573828
```

日志文件记录了每个Op在不同量化方法（MAX/Percentile9999/KL）下得到的threshold，同时给出了在只对该Op使用对应threshold做int8计算后的混精度模型与原始float模型输出的相似度的loss（1-余弦相似度）。
此外，日志还包含了屏幕端输出的每个op的loss信息以及最后的混精度模型与原始float模型的余弦相似度。
用户可以使用程序输出的qtable，也可以根据loss信息对qtable进行修改，然后生成混精度模型。
在敏感层搜索结束后，最优的threshold会被更新到一个新的量化表new_cali_table.txt，
该量化表存储在当前工程目录下，在生成混精度模型时需要调用新量化表。
在本例中，根据输出的loss信息，观察到input3.1的loss比其他op高很多，可以在qtable中只设置input3.1为FP32。

### 步骤1: 生成混精度量化模型

```shell
$ model_deploy \
    --mlir mobilenet_v2.mlir \
    --quantize INT8 \
    --processor bm1684 \
    --calibration_table new_cali_table.txt \
    --quantize_table mobilenet_v2_qtable \
    --model mobilenet_v2_bm1684_mix.bmodel
```

### 步骤2: 验证混精度模型

```shell
$ classify_mobilenet_v2 \
    --model_def mobilenet_v2_bm1684_mix.bmodel \
    --input ../ILSVRC2012/n01440764_9572.JPEG \
    --output mobilenet_v2_INT8_sym_bmodel.JPEG \
    --category_file ../ILSVRC2012/synset_words.txt
```

在输出结果图片上可以看到如下分类信息，可以看出混精度后，正确结果tench排到了第一名。

```shell
Top-5
n01440764 tench, Tinca tinca
n02749479 assault rifle, assault gun
n02916936 bulletproof vest
n02536864 coho, cohoe, coho salmon, blue jack, silver salmon, Oncorhynchus kisutch
n04090263 rifle
```

# fp_forward

对于特定网络，部分层由于数据分布差异大，量化成INT8会大幅降低模型精度，使用局部不量化功能，可以一键将部分层之前、之后、之间添加到混精度表中，在生成混精度模型时，这部分层将不被量化。

## 使用方法

本节将沿用第三章提到的yolov5s网络的例子，介绍如何使用局部不量化功能，快速生成混精度模型。

生成FP32和INT8模型的过程与第三章相同，下面仅介绍精度测试方案与混精度流程。

对于yolo系列模型来说，最后三个卷积层由于数据分布差异较大，常常手动添加混精度表以提升精度。使用局部不量化功能，从 `model_transform` 生成的Top层 mlir文件搜索到对应的层。快速添加混精度表。

```shell
$ fp_forward \
    yolov5s.mlir \
    --quantize INT8 \
    --processor bm1684x \
    --fpfwd_outputs 474_Conv,326_Conv,622_Conv\
    -o yolov5s_qtable
```

点开yolov5s_qtable可以看见相关层都被加入到qtable中。

生成混精度模型

```shell
$ model_deploy \
    --mlir yolov5s.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --quantize_table yolov5s_qtable\
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --model yolov5s_1684x_mix.bmodel
```



验证FP32模型和混精度模型的精度
model-zoo中有对目标检测模型进行精度验证的程序yolo，可以在mlir.config.yaml中使用harness字段调用yolo：

相关字段修改如下

.. code-block:: shell

    $ dataset:
        imagedir: $(coco2017_val_set)
        anno: $(coco2017_anno)/instances_val2017.json

      harness:
        type: yolo
        args:
          - name: FP32
            bmodel: $(workdir)/$(name)_bm1684_f32.bmodel
          - name: INT8
            bmodel: $(workdir)/$(name)_bm1684_int8_sym.bmodel
          - name: mix
            bmodel: $(workdir)/$(name)_bm1684_mix.bmodel

切换到model-zoo顶层目录，使用tpu_perf.precision_benchmark进行精度测试，命令如下：

.. code-block:: shell

   $ python3 -m tpu_perf.precision_benchmark yolov5s_path --mlir --target BM1684X --devices 0

执行完后，精度测试的结果存放在output/yolo.csv中:

FP32模型mAP为： 37.14%

INT8模型mAP为： 34.70%

混精度模型mAP为： 36.18%

在yolov5以外的检测模型上，使用混精度的方式常会有更明显的效果。


参数说明
------------------
.. list-table:: fp_forward 参数功能
   :widths: 23 8 50
   :header-rows: 1

   * - 参数名
     - 必选？
     - 说明
   * - 无
     - 是
     - 指定mlir文件
   * - processor
     - 是
     - 指定模型将要用到的平台，支持bm1690, bm1688, bm1684x, bm1684, cv186x, cv183x, cv182x, cv181x, cv180x
   * - fpfwd_inputs
     - 否
     - 指定层（包含本层）之前不执行量化，多输入用 ``,`` 间隔
   * - fpfwd_outputs
     - 否
     - 指定层（包含本层）之后不执行量化，多输入用 ``,`` 间隔
   * - fpfwd_blocks
     - 否
     - 指定起点和终点之间的层不执行量化，起点和终点之间用 ``:`` 间隔，多个block之间用空格间隔
   * - fp_type
     - 否
     - 指定混精度使用的float类型, 支持auto,F16,F32,BF16，默认为auto，表示由程序内部自动选择
   * - o
     - 是
     - 输出混精度量化表



========================================
文件: /home/zzt/workspace/sex_support_web/docs/get_docs/se9/a2_ws/tpu-mlir/docs/quick_start/source_zh/08_fuse_preprocess.rst
========================================

.. _fuse preprocess:

使用智能深度学习处理器做前处理
==============================
目前TPU-MLIR支持的两个主要系列BM168x（除BM1684外）与CV18xx均支持将图像常见的预处理加入到模型中进行计算。开发者可以在模型编译阶段，通过编译选项传递相应预处理参数,由编译器直接在模型运算前插⼊相应前处理算⼦，⽣成的bmodel或cvimodel即可以直接以预处理前的图像作为输⼊，随模型推理过程使⽤深度学习处理器处理前处理运算。

.. list-table:: 预处理类型支持情况
   :align: center
   :widths: 22 15 15
   :header-rows: 1

   * - 预处理类型
     - BM168x
     - CV18xx
   * - 图像裁剪
     - True
     - True
   * - 归一化计算
     - True
     - True
   * - NHWC to NCHW
     - True
     - True
   * - BGR/RGB 转换
     - True
     - True

其中图像裁剪会先将图片按使用 ``model_transform`` 工具时输入的 “--resize_dims” 参数将图片调整为对应的大小，再裁剪成模型输入的尺寸。而归一化计算支持直接将未进行预处理的图像数据(即unsigned int8格式的数据)做归一化处理。

若要将预处理融入到模型中，则需要在使用 ``model_deploy`` 工具进行部署时使用 “--fuse_preprocess” 参数。如果要做验证，则传入的 ``test_input`` 需要是图像原始格式的输入(即jpg, jpeg和png格式)， 相应地会生成原始图像输入对应的npz文件，名称为 ``${model_name}_in_ori.npz``。

此外，当实际外部输入格式与模型的格式不相同时，用 “--customization_format” 指定实际的外部输入格式，支持的格式说明如下：

.. list-table:: customization_format格式和说明
   :widths: 27 43 12 10
   :header-rows: 1

   * - customization_format
     - 说明
     - BM1684X
     - CV18xx
   * - None
     - 与原始模型输入保持一致, 不做处理。默认
     - True
     - True
   * - RGB_PLANAR
     - rgb顺序,按照nchw摆放
     - True
     - True
   * - RGB_PACKED
     - rgb顺序,按照nhwc摆放
     - True
     - True
   * - BGR_PLANAR
     - bgr顺序,按照nchw摆放
     - True
     - True
   * - BGR_PACKED
     - bgr顺序,按照nhwc摆放
     - True
     - True
   * - GRAYSCALE
     - 仅有⼀个灰⾊通道,按nchw摆
     - True
     - True
   * - YUV420_PLANAR
     - yuv420 planner格式,来⾃vpss的输⼊
     - False
     - True
   * - YUV_NV21
     - yuv420的NV21格式,来⾃vpss的输⼊
     - False
     - True
   * - YUV_NV12
     - yuv420的NV12格式,来⾃vpss的输⼊
     - False
     - True
   * - RGBA_PLANAR
     - rgba格式,按照nchw摆放
     - False
     - True

其中 “YUV*” 类格式为CV18xx系列特有的输入格式。当 ``customization_format`` 中颜色通道的顺序与模型输入不同时，将会进行通道转换操作。若指令中未设置 ``customization_format`` 参数，则根据使用 ``model_transform ``工具时定义的 ``pixel_format`` 和 ``channel_format`` 参数自动获取对应的 ``customization_format`` 。


模型部署样例
------------
以mobilenet_v2模型为例, 参考 “编译Caffe模型” 章节，使用 ``model_transform`` 工具生成原始mlir, 并通过 ``run_calibration`` 工具生成校准表。


BM1684X部署
~~~~~~~~~~~

生成融合预处理的INT8对称量化bmodel模型指令如下:

.. code-block:: shell

   $ model_deploy \
       --mlir mobilenet_v2.mlir \
       --quantize INT8 \
       --calibration_table mobilenet_v2_cali_table \
       --processor bm1684x \
       --test_input ../image/cat.jpg \
       --test_reference mobilenet_v2_top_outputs.npz \
       --tolerance 0.96,0.70 \
       --fuse_preprocess \
       --model mobilenet_v2_bm1684x_int8_sym_fuse_preprocess.bmodel


CV18xx部署
~~~~~~~~~~

生成融合预处理的INT8对称量化cvimodel模型的指令如下:

.. code-block:: shell

   $ model_deploy \
       --mlir mobilenet_v2.mlir \
       --quantize INT8 \
       --calibration_table mobilenet_v2_cali_table \
       --processor cv183x \
       --test_input ../image/cat.jpg \
       --test_reference mobilenet_v2_top_outputs.npz \
       --tolerance 0.96,0.70 \
       --fuse_preprocess \
       --customization_format RGB_PLANAR \
       --model mobilenet_v2_cv183x_int8_sym_fuse_preprocess.cvimodel

VPSS作为输入
^^^^^^^^^^^^^
当输入数据是来自于CV18xx提供的视频后处理模块VPSS时(使⽤VPSS进⾏预处理的详细使⽤⽅法请参阅《CV18xx 媒体软件开发参考》,本⽂档不做介绍)，则会有数据对齐要求，⽐如w
按照32字节对齐，此时 ``fuse_preprocess, aligned_input`` 需要同时被设置，生成融合预处理的cvimodel模型的指令如下：

.. code-block:: shell

   $ model_deploy \
       --mlir mobilenet_v2.mlir \
       --quantize INT8 \
       --calibration_table mobilenet_v2_cali_table \
       --processor cv183x \
       --test_input ../image/cat.jpg \
       --test_reference mobilenet_v2_top_outputs.npz \
       --tolerance 0.96,0.70 \
       --fuse_preprocess \
       --customization_format YUV_NV21 \
       --aligned_input \
       --model mobilenet_v2_cv183x_int8_sym_fuse_preprocess_aligned.cvimodel

上述指令中， ``aligned_input`` 指定了模型需要做输入的对齐。

值得注意的是：vpss做输入，runtime可以使用 ``CVI_NN_SetTensorPhysicalAddr`` 减少数据的拷贝。



========================================
文件: /home/zzt/workspace/sex_support_web/docs/get_docs/se9/a2_ws/tpu-mlir/docs/quick_start/source_zh/09_add_postprocess.rst
========================================

.. _add_postprocess:

使用智能深度学习处理器做后处理
=================================
目前TPU-MLIR支持将yolo系列和ssd网络模型的后处理集成到模型中, 目前支持该功能的处理器有BM1684X、BM1688、CV186X、BM1690。

本章将yolov5s和yolov8s_seg转成为F16模型为例, 介绍该功能如何被使用。

本章需要安装TPU-MLIR
进入Docker容器，并执行以下命令安装TPU-MLIR：

.. code-block:: shell

   $ pip install tpu_mlir[onnx]
   # or
   $ pip install tpu_mlir-*-py3-none-any.whl[onnx]

.. include:: get_resource.rst

检测模型后处理添加（yolov5s）
-------------------------

准备工作目录
^^^^^^^^^^

建立 ``model_yolov5s`` 目录, 并把模型文件和图片文件都放入 ``model_yolov5s`` 目录中。

操作如下:

.. code-block:: shell
   :linenos:

   $ mkdir yolov5s_onnx && cd yolov5s_onnx
   $ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
   $ cp -rf tpu_mlir_resource/dataset/COCO2017 .
   $ cp -rf tpu_mlir_resource/image .
   $ mkdir workspace && cd workspace


ONNX转MLIR
^^^^^^^^^^

模型转换命令如下:

.. code-block:: shell

   $ model_transform \
       --model_name yolov5s \
       --model_def ../yolov5s.onnx \
       --input_shapes [[1,3,640,640]] \
       --mean 0.0,0.0,0.0 \
       --scale 0.0039216,0.0039216,0.0039216 \
       --keep_aspect_ratio \
       --pixel_format rgb \
       --output_names 326,474,622 \
       --add_postprocess yolov5 \
       --test_input ../image/dog.jpg \
       --test_result yolov5s_top_outputs.npz \
       --mlir yolov5s.mlir

这里要注意两点, 一是命令中需要加入 ``--add_postprocess`` 参数; 二是指定的 ``--output_names`` 对应最后的卷积操作。

生成后的 ``yolov5s.mlir`` 文件最后被插入了一个 ``top.YoloDetection``, 如下:

.. code-block:: text
    :linenos:

    %260 = "top.Weight"() : () -> tensor<255x512x1x1xf32> loc(#loc261)
    %261 = "top.Weight"() : () -> tensor<255xf32> loc(#loc262)
    %262 = "top.Conv"(%253, %260, %261) {dilations = [1, 1], do_relu = false, group = 1 : i64, kernel_shape = [1, 1], pads = [0, 0, 0, 0], relu_limit = -1.000000e+00 : f64, strides = [1, 1]} : (tensor<1x512x20x20xf32>, tensor<255x512x1x1xf32>, tensor<255xf32>) -> tensor<1x255x20x20xf32> loc(#loc263)
    %263 = "top.YoloDetection"(%256, %259, %262) {agnostic_nms = false, anchors = [10, 13, 16, 30, 33, 23, 30, 61, 62, 45, 59, 119, 116, 90, 156, 198, 373, 326], class_num = 80 : i64, keep_topk = 200 : i64, net_input_h = 640 : i64, net_input_w = 640 : i64, nms_threshold = 5.000000e-01 : f64, num_boxes = 3 : i64, obj_threshold = 5.000000e-01 : f64, version = "yolov5"} : (tensor<1x255x80x80xf32>, tensor<1x255x40x40xf32>, tensor<1x255x20x20xf32>) -> tensor<1x1x200x7xf32> loc(#loc264)
    return %263 : tensor<1x1x200x7xf32> loc(#loc)

这里看到 ``top.YoloDetection`` 包括了anchors、num_boxes等等参数, 如果并非标准的yolo后处理, 需要改成其他参数, 可以直接修改mlir文件的这些参数。

另外输出也变成了1个, shape为 ``1x1x200x7``, 其中200代表最大检测框数, 当有多个batch时, 它的数值会变为 ``batch x 200``;
7分别指 ``[batch_number, class_id, score, center_x, center_y, width, height]``。
其中坐标是相对模型输入长宽的坐标, 比如本例中640x640, 数值参考如下：

.. code-block:: text

   [0., 16., 0.924488, 184.21094, 401.21973, 149.66412, 268.50336 ]


MLIR转换成BModel
^^^^^^^^^^^^^^^

将mlir文件转换成F16的bmodel, 操作方法如下:

.. code-block:: shell

   $ model_deploy \
       --mlir yolov5s.mlir \
       --quantize F16 \
       --processor bm1684x \
       --fuse_preprocess \
       --test_input ../image/dog.jpg \
       --test_reference yolov5s_top_outputs.npz \
       --model yolov5s_1684x_f16.bmodel

这里加上参数 ``--fuse_preprocess``, 是为了将前处理也合并到模型中。
这样转换后的模型就是包含了前后处理的模型, 用 ``model_tool`` 查看模型信息如下:

.. code-block:: shell

   $ model_tool --info yolov5s_1684x_f16.bmodel


.. code-block:: text
    :linenos:

    bmodel version: B.2.2
    processor: BM1684X
    create time: Wed Jan  3 07:29:14 2024

    kernel_module name: libbm1684x_kernel_module.so
    kernel_module size: 2677600
    ==========================================
    net 0: [yolov5s]  static
    ------------
    stage 0:
    subnet number: 2
    input: images_raw, [1, 3, 640, 640], uint8, scale: 1, zero_point: 0
    output: yolo_post, [1, 1, 200, 7], float32, scale: 1, zero_point: 0

    device mem size: 31238060 (coeff: 14757888, instruct: 124844, runtime: 16355328)
    host mem size: 0 (coeff: 0, runtime: 0)

这里的 ``[1, 1, 200, 7]`` 是最大shape, 实际输出根据检测的框数有所不同。


# 模型验证

在本发布包中有用python写好的yolov5用例, 使用 `detect_yolov5` 命令, 用于对图片进行目标检测。
该命令对应源码路径 `{package/path/to/tpu_mlir}/python/samples/detect_yolov5.py` 。
阅读该代码可以了解最终输出结果是怎么转换画框的。

命令执行如下:

```shell
detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_1684x_f16.bmodel \
    --net_input_dims 640,640 \
    --fuse_preprocess \
    --fuse_postprocess \
    --output dog_out.jpg
```

## 分割模型后处理添加（yolov8s_seg）

### 准备工作目录

建立 `model_yolov8s_seg` 目录, 使用官方模型导出onnx模型文件，并将图片文件放入 `model_yolov8s_seg` 目录中。

操作如下:

```shell
mkdir yolov8s_seg_onnx && cd yolov8s_seg_onnx
python -c "import torch; from ultralytics import YOLO; model = YOLO('yolov8s-seg.pt'); model.export(format='onnx')"
cp -rf tpu_mlir_resource/dataset/COCO2017 .
cp -rf tpu_mlir_resource/image .
mkdir workspace && cd workspace
```

### ONNX转MLIR

模型转换命令如下:

```shell
model_transform \
    --model_name yolov8s_seg \
    --model_def ../yolov8s-seg.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --add_postprocess yolov8_seg \
    --test_input ../image/dog.jpg \
    --test_result yolov8s_seg_top_outputs.npz \
    --mlir yolov8s_seg.mlir
```

生成后的 `yolov8s_seg.mlir` 文件最后插入了若干命名为 `yolo_seg_post*` 的算子，用于执行后处理中的坐标变换、nms、矩阵乘等运算。

```text
%429 = "top.Sigmoid"(%428) {bias = 0.000000e+00 : f64, log = false, round_mode = "HalfAwayFromZero", scale = 1.000000e+00 : f64} : (tensor<8400x25600xf32>) -> tensor<8400x25600xf32> loc(#loc431)
%430 = "top.Reshape"(%429) {flatten_start_dim = -1 : i64} : (tensor<8400x25600xf32>) -> tensor<8400x160x160xf32> loc(#loc432)
%431 = "top.Slice"(%430, %0, %0, %0) {axes = [], ends = [100, 160, 160], hasparamConvert_axes = [], offset = [0, 0, 0], steps = [1, 1, 1]} : (tensor<8400x160x160xf32>, none, none, none) -> tensor<100x160x160xf32> loc(#loc433)
%432 = "top.Slice"(%425, %0, %0, %0) {axes = [], ends = [100, 6], hasparamConvert_axes = [], offset = [0, 0], steps = [1, 1]} : (tensor<8400x38xf32>, none, none, none) -> tensor<100x6xf32> loc(#loc434)
return %431, %432 : tensor<100x160x160xf32>, tensor<100x6xf32> loc(#loc)
```

模型的输出共有2个, 其中masks_uncrop_uncompare是原始的分割掩码，shape为 `100x160x160`, 其中100代表最大检测框数，160x160代表了最后一层特征图的像素大小。

seg_out是检测框，shape为 `100x6`,其中100代表最大检测框数，6分别指 `[x_left, y_up, x_right, y_bottom, score, class_id]`。目前暂不支持多batch的分割模型后处理添加，因此没有batch信息。
其中坐标是相对模型输入长宽的坐标, 比如本例中640x640, 数值参考如下：

```text
[-74.06776, 263.67566, 74.06777, 531.1172, 0.9523437, 16.]
```

从原始掩码到最后的掩码输出，还需要将其进行resize运算，放大回原始图片大小；并根据seg_out中检测框对mask多余部分进行crop；
最后对掩码进行阈值过滤，得到全分辨率的掩码。以上的处理代码可参考该源码路径 `{package/path/to/tpu_mlir}/python/samples/segment_yolo.py` 中的流程。

### MLIR转换成BModel

将mlir文件转换成F16的bmodel, 操作方法如下:

```shell
fp_forward.py yolov8s_seg.mlir \
    --fpfwd_outputs yolo_seg_post_mulconst3 \
    --chip bm1684x \
    --fp_type F32 \
    -o yolov8s_seg_qtable

model_deploy \
    --mlir yolov8s_seg.mlir \
    --quantize F16 \
    --processor bm1684x \
    --fuse_preprocess \
    --quantize_table yolov8s_seg_qtable \
    --model yolov8s_seg_1684x_f16.bmodel
```

这里加上参数 `--fuse_preprocess`, 是为了将前处理也合并到模型中；还使用了yolov8s_seg_qtable，这是因为后处理中会对box施加偏移运算，将框图的坐标数值乘以一个大整数，F16的特性会导致涉及大整数的运算存在偏差，
最终会导致产生过多的mask，影响后处理性能，因此需要将这一部分算子使用F32混合精度进行运算。

### 模型验证

在本发布包中有用python写好的yolov8s_seg用例, 使用 `segment_yolo` 命令, 用于对图片进行分割。
该命令对应源码路径  `{package/path/to/tpu_mlir}/python/samples/segment_yolo.py`。
阅读该代码可以了解最终输出结果；并且如何产生分割掩膜和框图。

命令执行如下:

```shell
segment_yolo \
    --input ../image/dog.jpg \
    --model yolov8s_seg_1684x_f16.bmodel \
    --net_input_dims 640,640 \
    --fuse_preprocess \
    --fuse_postprocess \
    --output dog_out.jpg
```

# 编译LLM模型

## 概述

`llm_convert.py` 是一个用于将大语言模型（LLM）转换成bmodel的工具，将原始模型权重转换为 bmodel 格式，以便在 BM1684X、BM1688 和 CV186AH 等芯片平台上进行高效推理。
目前支持的LLM类型包括qwen2和llama，比如Qwen2-7B-Instruct、Llama-2-7b-chat-hf等。

## 命令行参数说明

下面介绍该工具支持的各个命令行参数：

- `-m`, `--model_path` (string, 必填)
  指定原始模型权重的路径。例如：`./Qwen2-7B-Instruct`

- `-s`, `--seq_length` (integer, 必填)
  指定转换时使用的序列长度。

- `-q`, `--quantize` (string, 必填)
  指定 bmodel 的量化类型，必须从下面的选项中选择：
  - `bf16`
  - `w8bf16`
  - `w4bf16`
  - `f16`
  - `w8f16`
  - `w4f16`

- `-g`, `--q_group_size` (integer, 默认值: 64)
  如果使用 W4A16 量化模式，则用于设置每组量化的组大小。

- `-c`, `--chip` (string, 默认值: `bm1684x`)
  指定生成 bmodel 的芯片平台，支持如下选项：
  - `bm1684x`
  - `bm1688`
  - `cv186ah`

- `--num_device` (integer, 默认值: 1)
  指定 bmodel 部署的设备数。

- `--num_core` (integer, 默认值: 0)
  指定 bmodel 部署使用的核数，0表示采用最大核数。

- `--symmetric`
  如果设置该标志，则使用对称量化。

- `--embedding_disk`
  如果设置该标志，则将word_embedding导出为二进制文件，并通过 CPU 进行推理。

- `--max_pixels` (integer)
  对于多模态模型如qwen2.5vl，用于指定最大像素尺寸，比如可以指定为 `672,896`,表示 `672x896` 的图片；也可以是 `602112`，表示最大像素。

- `-o`, `--out_dir` (string, 默认值: `./tmp`)
  指定输出的 bmodel 文件保存路径。

## 示例用法

假设需要将位于 `/workspace/Qwen2-7B-Instruct` 的大模型转换为 `bm1684x` 平台的 bmodel，同时使用 `384` 的序列长度和`w4bf16` 的量化类型，设置 group size 为 `128`，并将输出文件存放在目录 `qwen2_7b` 下，可以执行以下命令：

首先需要将Qwen2-7B-Instruct从huggingface下载到本地，然后执行如下命令：

```bash
llm_convert.py -m /workspace/Qwen2-7B-Instruct -s 384 -q w4bf16 -g 128 -c bm1684x -o qwen2_7b
```

注意如果提示transformers找不到，则需要安装，命令如下（其他pip包同理）：

```bash
pip3 install transformers --upgrade
```

另外该命令也支持AWQ和GPTQ模型，参考命令如下：

```bash
llm_convert.py -m /workspace/Qwen2.5-0.5B-Instruct-AWQ -s 384 -q w4bf16 -c bm1684x -o qwen2.5_0.5b
llm_convert.py -m /workspace/Qwen2.5-0.5B-Instruct-GPTQ-Int4 -s 384 -q w4bf16 -c bm1684x -o qwen2.5_0.5b
```

# 附录01：各框架模型转ONNX参考

本章节主要提供了将PyTorch, TensorFlow与PaddlePaddle模型转为ONNX模型的方式参考，读者也可以参考ONNX官方仓库提供的转模型教程： https://github.com/onnx/tutorials。本章节中的所有操作均在Docker容器中进行，具体的环境配置方式请参考第二章的内容。

## PyTorch模型转ONNX

本节以一个自主搭建的简易PyTorch模型为例进行onnx转换

### 步骤0：创建工作目录

在命令行中创建并进入torch_model目录。

```shell
mkdir torch_model
cd torch_model
```

### 步骤1：搭建并保存模型

在该目录下创建名为 `simple_net.py` 的脚本并运行，脚本的具体内容如下：

```python3
#!/usr/bin/env python3
import torch

# Build a simple nn model
class SimpleModel(torch.nn.Module):

   def __init__(self):
      super(SimpleModel, self).__init__()
      self.m1 = torch.nn.Conv2d(3, 8, 3, 1, 0)
      self.m2 = torch.nn.Conv2d(8, 8, 3, 1, 1)

   def forward(self, x):
      y0 = self.m1(x)
      y1 = self.m2(y0)
      y2 = y0 + y1
      return y2

# Create a SimpleModel and save its weight in the current directory
model = SimpleModel()
torch.save(model.state_dict(), "weight.pth")
```

运行命令如下：

```shell
python simple_net.py
```

运行完后我们会在当前目录下获得一个 `weight.pth` 的权重文件。

### 步骤2：导出ONNX模型

在该目录下创建另一个名为 `export_onnx.py` 的脚本并运行，脚本的具体内容如下：

```python3
#!/usr/bin/env python3
import torch
from simple_net import SimpleModel

# Load the pretrained model and export it as onnx
model = SimpleModel()
model.eval()
checkpoint = torch.load("weight.pth", map_location="cpu")
model.load_state_dict(checkpoint)

# Prepare input tensor
input = torch.randn(1, 3, 16, 16, requires_grad=True)

# Export the torch model as onnx
torch.onnx.export(model,
                  input,
                  'model.onnx', # name of the exported onnx model
                  opset_version=13,
                  export_params=True,
                  do_constant_folding=True)
```

运行完脚本后，我们即可在当前目录下得到名为 `model.onnx` 的onnx模型。

## TensorFlow模型转ONNX

本节以TensorFlow官方仓库中提供的 `mobilenet_v1_0.25_224` 模型作为转换样例。

### 步骤0：创建工作目录

在命令行中创建并进入tf_model目录。

```shell
mkdir tf_model
cd tf_model
```

### 步骤1：准备并转换模型

命令行中通过以下命令下载模型并利用 `tf2onnx` 工具将其导出为ONNX模型：

```shell
wget -nc http://download.tensorflow.org/models/mobilenet_v1_2018_08_02/mobilenet_v1_0.25_224.tgz
# tar to get "*.pb" model def file
tar xzf mobilenet_v1_0.25_224.tgz
python -m tf2onnx.convert --graphdef mobilenet_v1_0.25_224_frozen.pb \
    --output mnet_25.onnx --inputs input:0 \
    --inputs-as-nchw input:0 \
    --outputs MobilenetV1/Predictions/Reshape_1:0
```

运行以上所有命令后我们即可在当前目录下得到名为 `mnet_25.onnx` 的onnx模型。

## PaddlePaddle模型转ONNX

本节以PaddlePaddle官方仓库中提供的SqueezeNet1_1模型作为转换样例。
本节需要额外安装openssl-1.1.1o（ubuntu 22.04默认提供openssl-3.0.2）。

### 步骤0：安装openssl-1.1.1o

```shell
wget http://nz2.archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.19_amd64.deb
sudo dpkg -i libssl1.1_1.1.1f-1ubuntu2.19_amd64.deb
```

如果上述链接失效，请参考 http://nz2.archive.ubuntu.com/ubuntu/pool/main/o/openssl/?C=M;O=D 更换有效链接.

### 步骤1：创建工作目录

在命令行中创建并进入pp_model目录。

```shell
mkdir pp_model
cd pp_model
```

### 步骤2：准备模型

在命令行中通过以下命令下载模型：

```shell
wget https://bj.bcebos.com/paddlehub/fastdeploy/SqueezeNet1_1_infer.tgz
tar xzf SqueezeNet1_1_infer.tgz
cd SqueezeNet1_1_infer
```

并用PaddlePaddle项目中的 `paddle_infer_shape.py` 脚本对模型进行shape推理，此处将输入shape以NCHW的格式设置为 `[1,3,224,224]` ：

```shell
wget https://raw.githubusercontent.com/jiangjiajun/PaddleUtils/main/paddle/paddle_infer_shape.py
python paddle_infer_shape.py  --model_dir . \
                      --model_filename inference.pdmodel \
                      --params_filename inference.pdiparams \
                      --save_dir new_model \
                      --input_shape_dict="{'inputs':[1,3,224,224]}"
```

运行完以上所有命令后我们将处于 `SqueezeNet1_1_infer` 目录下，并在该目录下生成 `new_model` 的目录。

# 步骤3：转换模型

在命令行中通过以下命令安装 `paddle2onnx` 工具，并利用该工具将PaddlePaddle模型转为ONNX模型：

```shell
pip install paddle2onnx
paddle2onnx  --model_dir new_model \
          --model_filename inference.pdmodel \
          --params_filename inference.pdiparams \
          --opset_version 13 \
          --save_file squeezenet1_1.onnx
```

运行完以上所有命令后我们将获得一个名为 `squeezenet1_1.onnx` 的onnx模型。

# 附录02: CV18xx使用指南

CV18xx支持ONNX系列和Caffe模型,目前不支持TFLite模型。在量化数据类型方面,CV18xx支持BF16格式的量化
和INT8格式的对称量化。本章节以CV183X为例,介绍CV18xx系列编译模型和运行runtime sample。

## 编译yolov5模型

### 安装tpu-mlir

进入Docker容器，并执行以下命令安装TPU-MLIR：

```shell
pip install tpu_mlir[all]
# or
pip install tpu_mlir-*-py3-none-any.whl[all]
```

### 准备工作目录

建立 `model_yolov5s` 目录, 并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

操作如下:

```shell
mkdir model_yolov5s && cd model_yolov5s
wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
cp -rf tpu_mlir_resource/dataset/COCO2017 .
cp -rf tpu_mlir_resource/image .
mkdir workspace && cd workspace
```

### ONNX转MLIR

如果模型是图片输入, 在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入, 则不需要考虑预处理。
预处理过程用公式表达如下( `x` 代表输入):

```
y = (x - mean) × scale
```

官网yolov5的图片是rgb, 每个值会乘以 `1/255` , 转换成mean和scale对应为
`0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216` 。

模型转换命令如下:

```shell
model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 326,474,622 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s.mlir
```

`model_transform` 的相关参数说明参考 model_transform参数说明 部分。

### MLIR转BF16模型

将mlir文件转换成bf16的cvimodel, 操作方法如下:

```shell
model_deploy \
    --mlir yolov5s.mlir \
    --quantize BF16 \
    --processor cv183x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --model yolov5s_cv183x_bf16.cvimodel
```

`model_deploy` 的相关参数说明参考 model_deploy参数说明 部分。

### MLIR转INT8模型

转INT8模型前需要跑calibration, 得到校准表; 输入数据的数量根据情况准备100~1000张左右。然后用校准表, 生成INT8对称cvimodel

这里用现有的100张来自COCO2017的图片举例, 执行calibration:

```shell
run_calibration yolov5s.mlir \
    --dataset ../COCO2017 \
    --input_num 100 \
    -o yolov5s_cali_table
```

运行完成后会生成名为 `${model_name}_cali_table` 的文件, 该文件用于后续编译INT8
模型的输入文件。

转成INT8对称量化cvimodel模型, 执行如下命令:

```shell
model_deploy \
    --mlir yolov5s.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor cv183x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --model yolov5s_cv183x_int8_sym.cvimodel
```

编译完成后, 会生成名为 `${model_name}_cv183x_int8_sym.cvimodel` 的文件。

### 效果对比

onnx模型的执行方式如下, 得到 `dog_onnx.jpg` :

```shell
detect_yolov5 \
    --input ../image/dog.jpg \
    --model ../yolov5s.onnx \
    --output dog_onnx.jpg
```

FP32 mlir模型的执行方式如下,得到 `dog_mlir.jpg` :

```shell
detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s.mlir \
    --output dog_mlir.jpg
```

BF16 cvimodel的执行方式如下, 得到 `dog_bf16.jpg` :

```shell
detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_cv183x_bf16.cvimodel \
    --output dog_bf16.jpg
```

INT8 cvimodel的执行方式如下, 得到 `dog_int8.jpg` :

```shell
detect_yolov5 \
    --input ../image/dog.jpg \
    --model yolov5s_cv183x_int8_sym.cvimodel \
    --output dog_int8.jpg
```

四张图片对比,由于运行环境不同, 最终的效果和精度会有些差异。

上述教程介绍了TPU-MLIR编译CV18xx系列的ONNX模型的过程,caffe模型的转换过程可参考"编译Caffe模型"章节,只需要将对应的处理器名称换成实际的CV18xx名称即可。

## 合并cvimodel模型文件

对于同一个模型,可以依据输入的batch size以及分辨率(不同的h和w)分别生成独立的cvimodel文件。不过为了节省外存和运存,可以选择将这些相关的cvimodel文件合并为一个cvimodel文件,共享其权重部分。具体步骤如下:

### 步骤0: 生成batch 1的cvimodel

请参考前述章节,新建workspace目录,通过model_transform将yolov5s转换成mlir fp32模型。

注意 :
1.需要合并的cvimodel使用同一个workspace目录,并且不要与不需要合并的cvimodel
共用一个workspace;
2.步骤0、步骤1中 --merge_weight是必需选项。

```shell
model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 326,474,622 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s_bs1.mlir
```

使用前述章节生成的yolov5s_cali_table;如果没有,则通过run_calibration工具对yolov5s.mlir进行量化校验获得calibration table文件。
然后将模型量化并生成cvimodel:

```shell
# 加上 --merge_weight参数
model_deploy \
    --mlir yolov5s_bs1.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor cv183x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --merge_weight \
    --model yolov5s_cv183x_int8_sym_bs1.cvimodel
```

### 步骤1: 生成batch 2的cvimodel

同步骤0,在同一个workspace中生成batch为2的mlir fp32文件:

```shell
model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[2,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 326,474,622 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s_bs2.mlir
```

```shell
# 加上 --merge_weight参数
model_deploy \
    --mlir yolov5s_bs2.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor cv183x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --merge_weight \
    --model yolov5s_cv183x_int8_sym_bs2.cvimodel
```

### 步骤2: 合并batch 1和batch 2的cvimodel

使用model_tool合并两个cvimodel文件:

```shell
model_tool \
  --combine \
    yolov5s_cv183x_int8_sym_bs1.cvimodel \
    yolov5s_cv183x_int8_sym_bs2.cvimodel \
    -o yolov5s_cv183x_int8_sym_bs1_bs2.cvimodel
```

### 步骤3: runtime接口调用cvimodel

可以通过以下命令查看bs1和bs2指令的program id:

```shell
model_tool --info yolov5s_cv183x_int8_sym_bs1_bs2.cvimodel
```

在运行时可以通过如下方式去运行不同的batch命令:

```c++
CVI_MODEL_HANDEL bs1_handle;
CVI_RC ret = CVI_NN_RegisterModel("yolov5s_cv183x_int8_sym_bs1_bs2.cvimodel", &bs1_handle);
assert(ret == CVI_RC_SUCCESS);
// 选择bs1的program id
CVI_NN_SetConfig(bs1_handle, OPTION_PROGRAM_INDEX, 0);
CVI_NN_GetInputOutputTensors(bs1_handle, ...);
....


CVI_MODEL_HANDLE bs2_handle;
// 复用已加载的模型
CVI_RC ret = CVI_NN_CloneModel(bs1_handle, &bs2_handle);
assert(ret == CVI_RC_SUCCESS);
// 选择bs2的program id
CVI_NN_SetConfig(bs2_handle, OPTION_PROGRAM_INDEX, 1);
CVI_NN_GetInputOutputTensors(bs2_handle, ...);
...

// 最后销毁bs1_handle, bs2_handel
CVI_NN_CleanupModel(bs1_handle);
CVI_NN_CleanupModel(bs2_handle);
```

### 综述: 合并过程

使用上面命令,不论是相同模型还是不同模型,均可以进行合并。
合并的原理是: 模型生成过程中,会叠加前面模型的weight(如果相同则共用)。

主要步骤在于:

1. 用model_deploy生成模型时,加上--merge_weight参数
2. 要合并的模型的生成目录必须是同一个,且在合并模型前不要清理任何中间文件(叠加前面模型weight通过中间文件_weight_map.csv实现)
3. 用model_tool --combine 将多个cvimodel合并

## 编译和运行runtime sample

本章首先介绍EVB如何运行sample应用程序,然后介绍如何交叉编译sample应用程序,最后介绍docker仿真编译和运行sample。具体包括4个samples:

* Sample-1 : classifier (mobilenet_v2)
* Sample-2 : classifier_bf16 (mobilenet_v2)
* Sample-3 : classifier fused preprocess (mobilenet_v2)
* Sample-4 : classifier multiple batch (mobilenet_v2)

### 在EVB运行release提供的sample预编译程序

需要如下文件:

* cvitek_tpu_sdk_[cv183x | cv182x | cv182x_uclibc | cv181x_glibc32 | cv181x_musl_riscv64_rvv | cv180x_musl_riscv64_rvv | cv181x_glibc_riscv64].tar.gz
* cvimodel_samples_[cv183x | cv182x | cv181x | cv180x].tar.gz

将根据处理器类型选择所需文件加载至EVB的文件系统,于evb上的linux console执行,以cv183x为例:

解压samples使用的model文件(以cvimodel格式交付),并解压TPU_SDK,并进入samples目录,执行测试,过程如下:

```shell
#env
tar zxf cvimodel_samples_cv183x.tar.gz
export MODEL_PATH=$PWD/cvimodel_samples
tar zxf cvitek_tpu_sdk_cv183x.tar.gz
export TPU_ROOT=$PWD/cvitek_tpu_sdk
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh
# get cvimodel info
cd samples
./bin/cvi_sample_model_info $MODEL_PATH/mobilenet_v2.cvimodel

####################################
# sample-1 : classifier
###################################
./bin/cvi_sample_classifier \
    $MODEL_PATH/mobilenet_v2.cvimodel \
    ./data/cat.jpg \
    ./data/synset_words.txt

# TOP_K[5]:
#  0.326172, idx 282, n02123159 tiger cat
#  0.326172, idx 285, n02124075 Egyptian cat
#  0.099609, idx 281, n02123045 tabby, tabby cat
#  0.071777, idx 287, n02127052 lynx, catamount
#  0.041504, idx 331, n02326432 hare

####################################
# sample-2 : classifier_bf16
###################################
./bin/cvi_sample_classifier_bf16 \
    $MODEL_PATH/mobilenet_v2_bf16.cvimodel \
    ./data/cat.jpg \
    ./data/synset_words.txt

# TOP_K[5]:
#  0.314453, idx 285, n02124075 Egyptian cat
#  0.040039, idx 331, n02326432 hare
#  0.018677, idx 330, n02325366 wood rabbit, cottontail, cottontail rabbit
#  0.010986, idx 463, n02909870 bucket, pail
#  0.010986, idx 852, n04409515 tennis ball

############################################
# sample-3 : classifier fused preprocess
############################################
./bin/cvi_sample_classifier_fused_preprocess \
    $MODEL_PATH/mobilenet_v2_fused_preprocess.cvimodel \
    ./data/cat.jpg \
    ./data/synset_words.txt

# TOP_K[5]:
#  0.326172, idx 282, n02123159 tiger cat
#  0.326172, idx 285, n02124075 Egyptian cat
#  0.099609, idx 281, n02123045 tabby, tabby cat
#  0.071777, idx 287, n02127052 lynx, catamount
#  0.041504, idx 331, n02326432 hare

############################################
# sample-4 : classifier multiple batch
############################################
./bin/cvi_sample_classifier_multi_batch \
    $MODEL_PATH/mobilenet_v2_bs1_bs4.cvimodel \
    ./data/cat.jpg \
    ./data/synset_words.txt

# TOP_K[5]:
#  0.326172, idx 282, n02123159 tiger cat
#  0.326172, idx 285, n02124075 Egyptian cat
#  0.099609, idx 281, n02123045 tabby, tabby cat
#  0.071777, idx 287, n02127052 lynx, catamount
#  0.041504, idx 331, n02326432 hare
```

同时提供脚本作为参考，执行效果与直接运行相同，如下：

```shell
./run_classifier.sh
./run_classifier_bf16.sh
./run_classifier_fused_preprocess.sh
./run_classifier_multi_batch.sh
```

**在cvitek_tpu_sdk/samples/samples_extra目录下有更多的samples，可供参考：**

```shell
./bin/cvi_sample_detector_yolo_v3_fused_preprocess \
    $MODEL_PATH/yolo_v3_416_fused_preprocess_with_detection.cvimodel \
    ./data/dog.jpg \
    yolo_v3_out.jpg

./bin/cvi_sample_detector_yolo_v5_fused_preprocess \
    $MODEL_PATH/yolov5s_fused_preprocess.cvimodel \
    ./data/dog.jpg \
    yolo_v5_out.jpg

./bin/cvi_sample_detector_yolox_s \
    $MODEL_PATH/yolox_s.cvimodel \
    ./data/dog.jpg \
    yolox_s_out.jpg

./bin/cvi_sample_alphapose_fused_preprocess \
    $MODEL_PATH/yolo_v3_416_fused_preprocess_with_detection.cvimodel \
    $MODEL_PATH/alphapose_fused_preprocess.cvimodel \
    ./data/pose_demo_2.jpg \
    alphapose_out.jpg

./bin/cvi_sample_fd_fr_fused_preprocess \
    $MODEL_PATH/retinaface_mnet25_600_fused_preprocess_with_detection.cvimodel \
    $MODEL_PATH/arcface_res50_fused_preprocess.cvimodel \
    ./data/obama1.jpg \
    ./data/obama2.jpg
```

## 交叉编译samples程序

发布包有samples的源代码，按照本节方法在Docker环境下交叉编译samples程序，然后在evb上运行。

本节需要如下文件：

- cvitek_tpu_sdk_[cv183x | cv182x | cv182x_uclibc | cv181x_glibc32 | cv181x_musl_riscv64_rvv | cv180x_musl_riscv64_rvv].tar.gz
- cvitek_tpu_samples.tar.gz

### aarch 64位 (如cv183x aarch64位平台)

SDK准备：

```shell
tar zxf host-tools.tar.gz
tar zxf cvitek_tpu_sdk_cv183x.tar.gz
export PATH=$PWD/host-tools/gcc/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin:$PATH
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build_soc
cd build_soc
cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DCMAKE_C_FLAGS_RELEASE=-O3 \
    -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
    -DCMAKE_TOOLCHAIN_FILE=$TPU_SDK_PATH/cmake/toolchain-aarch64-linux.cmake \
    -DTPU_SDK_PATH=$TPU_SDK_PATH \
    -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
    -DCMAKE_INSTALL_PREFIX=../install_samples \
    ..
cmake --build . --target install
```

### arm 32位 (如cv183x平台32位、cv182x平台)

SDK准备：

```shell
tar zxf host-tools.tar.gz
tar zxf cvitek_tpu_sdk_cv182x.tar.gz
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
export PATH=$PWD/host-tools/gcc/gcc-linaro-6.3.1-2017.05-x86_64_arm-linux-gnueabihf/bin:$PATH
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

如果docker版本低于1.7，则需要更新32位系统库（只需一次）：

```shell
dpkg --add-architecture i386
apt-get update
apt-get install libc6:i386 libncurses5:i386 libstdc++6:i386
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build_soc
cd build_soc
cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DCMAKE_C_FLAGS_RELEASE=-O3 \
    -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
    -DCMAKE_TOOLCHAIN_FILE=$TPU_SDK_PATH/cmake/toolchain-linux-gnueabihf.cmake \
    -DTPU_SDK_PATH=$TPU_SDK_PATH \
    -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
    -DCMAKE_INSTALL_PREFIX=../install_samples \
    ..
cmake --build . --target install
```

### uclibc 32位平台 (cv182x uclibc平台)

SDK准备：

```shell
tar zxf host-tools.tar.gz
tar zxf cvitek_tpu_sdk_cv182x_uclibc.tar.gz
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
export PATH=$PWD/host-tools/gcc/arm-cvitek-linux-uclibcgnueabihf/bin:$PATH
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

如果docker版本低于1.7，则需要更新32位系统库（只需一次）：

```shell
dpkg --add-architecture i386
apt-get update
apt-get install libc6:i386 libncurses5:i386 libstdc++6:i386
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build_soc
cd build_soc
cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DCMAKE_C_FLAGS_RELEASE=-O3 \
    -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
    -DCMAKE_TOOLCHAIN_FILE=$TPU_SDK_PATH/cmake/toolchain-linux-uclibc.cmake \
    -DTPU_SDK_PATH=$TPU_SDK_PATH \
    -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
    -DCMAKE_INSTALL_PREFIX=../install_samples \
    ..
cmake --build . --target install
```

### riscv64位 musl平台 (如cv181x、cv180x riscv64位 musl平台)

SDK准备：

```shell
tar zxf host-tools.tar.gz
tar zxf cvitek_tpu_sdk_cv181x_musl_riscv64_rvv.tar.gz
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
export PATH=$PWD/host-tools/gcc/riscv64-linux-musl-x86_64/bin:$PATH
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build_soc
cd build_soc
cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DCMAKE_C_FLAGS_RELEASE=-O3 \
    -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
    -DCMAKE_TOOLCHAIN_FILE=$TPU_SDK_PATH/cmake/toolchain-riscv64-linux-musl-x86_64.cmake \
    -DTPU_SDK_PATH=$TPU_SDK_PATH \
    -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
    -DCMAKE_INSTALL_PREFIX=../install_samples \
    ..
cmake --build . --target install
```

### riscv64位 glibc平台 (如cv181x、cv180x riscv64位glibc平台)

SDK准备：

```shell
tar zxf host-tools.tar.gz
tar zxf cvitek_tpu_sdk_cv181x_glibc_riscv64.tar.gz
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
export PATH=$PWD/host-tools/gcc/riscv64-linux-x86_64/bin:$PATH
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build_soc
cd build_soc
cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=RELEASE \
    -DCMAKE_C_FLAGS_RELEASE=-O3 \
    -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
    -DCMAKE_TOOLCHAIN_FILE=$TPU_SDK_PATH/cmake/toolchain-riscv64-linux-x86_64.cmake \
    -DTPU_SDK_PATH=$TPU_SDK_PATH \
    -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
    -DCMAKE_INSTALL_PREFIX=../install_samples \
    ..
cmake --build . --target install
```

## docker环境仿真运行的samples程序

需要如下文件：

- cvitek_tpu_sdk_x86_64.tar.gz
- cvimodel_samples_[cv183x|cv182x|cv181x|cv180x].tar.gz
- cvitek_tpu_samples.tar.gz

TPU sdk准备：

```shell
tar zxf cvitek_tpu_sdk_x86_64.tar.gz
export TPU_SDK_PATH=$PWD/cvitek_tpu_sdk
cd cvitek_tpu_sdk && source ./envs_tpu_sdk.sh && cd ..
```

编译samples，安装至install_samples目录：

```shell
tar zxf cvitek_tpu_samples.tar.gz
cd cvitek_tpu_samples
mkdir build
cd build
cmake -G Ninja \
   -DCMAKE_BUILD_TYPE=RELEASE \
   -DCMAKE_C_FLAGS_RELEASE=-O3 \
   -DCMAKE_CXX_FLAGS_RELEASE=-O3 \
   -DTPU_SDK_PATH=$TPU_SDK_PATH \
   -DCNPY_PATH=$TPU_SDK_PATH/cnpy \
   -DOPENCV_PATH=$TPU_SDK_PATH/opencv \
   -DCMAKE_INSTALL_PREFIX=../install_samples \
   ..
cmake --build . --target install
```

运行samples程序：

```shell
# envs
tar zxf cvimodel_samples_cv183x.tar.gz
export MODEL_PATH=$PWD/cvimodel_samples

# get cvimodel info
cd ../install_samples
./bin/cvi_sample_model_info $MODEL_PATH/mobilenet_v2.cvimodel
```

**其他samples运行命令参照EVB运行命令**

# 在开发板上进行模型测试及验证工作

在板子上可以通过cvitek_tpu_sdk/bin/下的model_runner程序进行模型验证；运行model_runner前需要将cvitek_tpu_sdk放到板子上，然后：

```shell
cd cvitek_tpu_sdk
source ./envs_tpu_sdk.sh
```

model_runner支持以下选项：

| 参数名 | 说明 |
|--------|------|
| --model | 指定模型文件 |
| --input | 指定输入npz文件 |
| --output | 指定输出npz文件 |
| --pmu | 打印性能数据 |
| --count | 循环运行次数 |
| --reference | 指定结果对比npz文件 |
| --tolerances | 指定结果对比相似度限制 |
| --enable-timer | 打印推理耗时信息 |

一般使用命令如下：

```shell
# 测试模型是否能正常推理
model_runner --model yolov5s.cvimodel

# 测试模型性能
model_runner --model yolov5s.cvimodel --pmu

# dump 模型结果
model_runner --model yolov5s.cvimodel --input input.npz --output output.npz

# 对比模型结果
model_runner --model yolov5s.cvimodel --input input.npz --reference ref.npz
```

## FAQ

### 模型转换常见问题

#### 模型转换问题

1. pytorch,tensorflow等是否能直接转换为cvimodel?

   pytorch: 支持通过 `jit.trace(torch_model.eval(), inputs).save(model_name.pt)` 静态化后的pt模型。

   tensorflow / 其它: 暂不支持,可以通过onnx间接支持tf模型。

2. 执行model_transform报错

   `model_transform` 命令作用是将onnx,caffe框架模型转化为fp32 mlir形式,报错很大概率就是存在不支持的算子或者算子属性不兼容,可以反馈给tpu团队解决。

3. 执行model_deploy报错

   `model_deploy` 作用是先将fp32 mlir通过量化转为int8/bf16mlir形式,然后再将int8/bf16mlir转化为cvimodel。在转化的过程中,会涉及到两次相似度的对比: 一次是fp32 mlir与int8/bf16mlir之间的量化对比,一次是int8/bf16mlir与最终转化出来的cvimodel的相似度对比,若相似度对比失败则会出现下列问题:

   解决方法: `tolerance` 参数不对。模型转换过程会对int8/bf16 mlir与fp32 mlir的输出计算相似度,而tolerance作用就是限制相似度的最低值,若计算出的相似度的最小值低于对应的预设的tolerance值则程序会停止执行, 可以考虑对tolerance进行调整。(如果相似度的最小值过低请反馈到tpu团队解决)。

4. `model_transform` 的 `pixel_format` 参数和 `model_deploy` 的 `customization_format` 参数的差异?

   channel_order是原始模型的输入图片类型(只支持gray/rgb planar/bgr planar),customization_format是转换成cvimodel后的输入图片类型,由客户自行决定,需与 fuse_preprocess 共同使用(如果输入图片是通过VPSS或者VI获取的YUV图片,可以设置customization_format为YUV格式)。如果pixel_format与customization_format不一致,cvimodel推理时会自动将输入转成pixel_format指定的类型。

5. 是否支持多输入模型,怎么进行预处理?

   仅支持多输入图片使用同一种预处理方式的模型,不支持多输入图片使用不同预处理方式的模型。

#### 量化问题

1. 跑run_calibration提示KeyError: 'images'

   传入的images的路径不对,请检查数据集的路径是否正确。

2. 跑量化如何处理多输入问题?

   多输入模型跑run_calibration时, 可使用.npz存储多个输入，或使用--data_list参数，且data_list中的每行的多个输入由"，"隔开。

3. 跑量化输入会进行预处理吗?

   会的,根据model_transform的预处理参数保存到mlir文件中,量化过程会进行加载预处理参数进行预处理。

4. 跑量化输入程序被系统kill或者显示分配内存失败

   需要先检查主机的内存是否足够,常见的模型需要8G内存左右即可。如果内存不够,可尝试在运行run_calibration时,添加以下参数来减少内存需求。

   ```shell
    --tune_num 2   			#默认为5
   ```

5. 是否支持手动修改calibration table?

   支持,但是不建议修改。

#### 其它常见问题

1. 转换后的模型是否支持加密?

   暂时不支持。

2. bf16的模型与int8模型的速度差异是多少?

   大约是3-4倍时间差异,具体的数据需要通过实验验证。

3. 是否支持动态shape?

   cvimodel不支持动态shape。如果是固定的几种shape可以依据输入的batch_size以及不同的h和w分别生成独立的cvimodel文件,通过共享权重的形式合并为一个cvimodel。详见: 合并cvimodel模型文件

### 模型评估常见问题

#### 模型的评估流程?

先转化为bf16模型,通过 `model_tool --info xxxx.cvimodel` 命令来评估模型所需要的ION内存以及所占的存储空间,接着在板子上执行 `model_runner` 来评估模型运行的时间,之后根据提供的sample来评估业务场景下模型精度效果。模型输出的效果准确性符合预期之后,再转化为int8模型再完成与bf16模型相同的流程

#### 量化后精度与原来模型对不上,如何调试?

1. 确保 `model_deploy` 的 `--test_input`, `--test_reference`, `--compare_all`, `--tolerance` 参数进行了正确设置。

2. 比较bf16模型与原始模型的运行结果,确保误差不大。如果误差较大,先确认预处理和后处理是否正确。

3. 如果int8模型精度差:

   a. 确认 `run_calibration` 使用的数据集为训练模型时使用的验证集;
   b. 可以增加 `run_calibration` 使用的业务场景数据集(一般为100-1000张图片)。

4. 确认输入类型:

   a. 若指定 `--fuse_preprocess` 参数,cvimodel的input类型为uint8;
   b. 若指定 `--quant_input` , 一般情况下,bf16_cvimoel的input类型为bf16,int8_cvimodel的input类型为int8;
   c. input类型也可以通过model_tool --info xxx.cvimodel查看

#### bf16模型的速度比较慢,int8模型精度不符合预期怎么办?

使用混精度量化方法,可参考 mix precision 。

### 模型部署常见问题

#### CVI_NN_Forward接口调用多次后出错或者卡住时间过长?

可能驱动或者硬件问题,需要反馈给tpu团队解决。

#### 模型预处理速度比较慢?

1. 转模型的时候可以在运行 `model_deploy` 时加上 `fuse_preprocess` 参数, 将预处理放到深度学习处理器内部来处理。

2. 如果图片是从vpss或者vi获取, 那么可以在转模型时使用 `fuse_preprocess、aligned_input` , 然后使用 `CVI_NN_SetTensorPhysicalAddr` 等接口直接将input tensor地址设置为图片的物理地址, 减少数据拷贝耗时。

#### docker的推理和evb推理的浮点和定点结果是否一样?

定点无差异, 浮点有差异, 但是相似度比较高, 误差可以忽略。

#### 如果要跑多个模型支持多线程并行吗?

支持多线程, 但是多个模型在深度学习处理器上推理时是串行进行的。

#### 填充input tensor相关接口区别

`CVI_NN_SetTensorPtr` : 设置input tensor的虚拟地址，原本的tensor 内存不会释放。推理时从用户设置的虚拟地址 **拷贝数据** 到原本的tensor内存上。

`CVI_NN_SetTensorPhysicalAddr` : 设置input tensor的物理地址，原本的tensor 内存会释放。推理时直接从新设置的物理地址读取数据, **无需拷贝数据** 。从VPSS获取的Frame可以调用这个接口，传入Frame的首地址。注意需要转模型的时候 `model_deploy` 设置 `--fused_preprocess --aligned_input` 才能调用此接口。

`CVI_NN_SetTensorWithVideoFrame` : 通过VideoFrame结构体来填充Input Tensor。注意VideoFrame的地址为物理地址。如果转模型设置 `--fuse_preprocess --aligned_input` ，则等同于 `CVI_NN_SetTensorPhysicalAddr` ，否则会将VideoFrame的数据拷贝到Input Tensor。

`CVI_NN_SetTensorWithAlignedFrames` : 与 `CVI_NN_SetTensorWithVideoFrame` 类似, 支持多batch。

`CVI_NN_FeedTensorWithFrames` : 与 `CVI_NN_SetTensorWithVideoFrame` 类似。

#### 模型载入后ion内存分配问题

1. 调用 `CVI_NN_RegisterModel` 后会为weight和cmdbuf分配ion内存(从model_tool可以看到weight和cmdbuf大小)

2. 调用 `CVI_NN_GetInputOutputTensors` 后会为tensor(包括private_gmem, shared_gmem, io_mem)分配ion内存

3. `CVI_NN_CloneModel` 可以共享weight和cmdbuf内存

4. 其他接口均不会再申请ion内存, 即除了初始化, 其他阶段模型都不会再申请内存。

5. 不同模型的shared_gmem是可以共享(包括多线程情况), 因此优先初始化shared_gmem最大的模型可以节省ion内存。

#### 加载业务程序后模型推理时间变长

设置环境变量 `export TPU_ENABLE_PMU=1` 后, 模型推理时会打印tpu日志, 记录tdma_exe_ms、tiu_exe_ms、inference_ms这3个耗时。一般加载业务后tdma_exe_ms会变长, tiu_exe_ms不变, 这是因为tdma_exe_ms是内存搬运数据耗时, 如果内存带宽不够用了, tdma耗时就会增加。

优化的方向:

a. vpss/venc等优化chn, 降低分辨率

b. 业务层减少内存拷贝, 如图片尽量保存引用, 减少拷贝等

c. 模型填充Input tensor时, 使用无拷贝的方式

### 其他常见问题

#### 在cv182x/cv181x/cv180x板端环境中出现: taz:invalid option --z解压失败的情况

先在其他linux环境下解压, 再放到板子中使用, 因为window不支持软链接, 所以在windows环境下解压可能导致软链接失效导致报错

#### 若tensorflow模型为saved_model的pb形式, 如何进行转化为frozen_model的pb形式

```shell
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2
from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input, decode_predictions
import numpy as np
import tf2onnx
import onnxruntime as rt

img_path = "./cat.jpg"
# pb model and variables should in model dir
pb_file_path = "your model dir"
img = image.load_img(img_path, target_size=(224, 224))
x = image.img_to_array(img)
x = np.expand_dims(x, axis=0)
# Or set your preprocess here
x = preprocess_input(x)

model = tf.keras.models.load_model(pb_file_path)
preds = model.predict(x)

# different model input shape and name will differently
spec = (tf.TensorSpec((1, 224, 224, 3), tf.float32, name="input"), )
output_path = model.name + ".onnx"

model_proto, _ = tf2onnx.convert.from_keras(model, input_signature=spec, opset=13, output_path=output_path)
```

# 附录03: BM168x使用指南

BM168x支持ONNX系列、pytorch模型、Caffe模型和TFLite模型。本章节以BM1684x为例,介绍BM168x系列bmodel文件的合并方法。

## 合并bmodel模型文件

对于同一个模型,可以依据输入的batch size以及分辨率(不同的h和w)分别生成独立的bmodel文件。不过为了节省外存和运存,可以选择将这些相关的bmodel文件合并为一个bmodel文件,共享其权重部分。具体步骤如下:

### 步骤0: 生成batch 1的bmodel

请参考前述章节,新建workspace目录,通过model_transform将yolov5s转换成mlir fp32模型。

> **注意**:
> 1.需要合并的bmodel使用同一个workspace目录,并且不要与不需要合并的bmodel共用一个workspace;
> 2.步骤0、步骤1中 --merge_weight是必需选项。

```shell
$ model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s_bs1.mlir
```

使用前述章节生成的yolov5s_cali_table;如果没有,则通过run_calibration工具对yolov5s.mlir进行量化校验获得calibration table文件。
然后将模型量化并生成bmodel:

```shell
# 加上 --merge_weight参数
$ model_deploy \
    --mlir yolov5s_bs1.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --merge_weight \
    --model yolov5s_bm1684x_int8_sym_bs1.bmodel
```

### 步骤1: 生成batch 2的bmodel

同步骤0,在同一个workspace中生成batch为2的mlir fp32文件:

```shell
$ model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[2,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s_bs2.mlir
```

```shell
# 加上 --merge_weight参数
$ model_deploy \
    --mlir yolov5s_bs2.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --merge_weight \
    --model yolov5s_bm1684x_int8_sym_bs2.bmodel
```

# 步骤2: 合并batch 1和batch 2的bmodel

使用model_tool合并两个bmodel文件:

```shell
model_tool \
  --combine \
    yolov5s_bm1684x_int8_sym_bs1.bmodel \
    yolov5s_bm1684x_int8_sym_bs2.bmodel \
    -o yolov5s_bm1684x_int8_sym_bs1_bs2.bmodel
```

# 综述: 合并过程

使用上面命令,不论是相同模型还是不同模型,均可以进行合并。
合并的原理是: 模型生成过程中,会叠加前面模型的weight(如果相同则共用)。

主要步骤在于:

1. 用model_deploy生成模型时,加上--merge_weight参数
2. 要合并的模型的生成目录必须是同一个,且在合并模型前不要清理任何中间文件(叠加前面模型weight通过中间文件_weight_map.csv实现)
3. 用model_tool --combine 将多个bmodel合并

# 附录04：Model-zoo测试

## 配置系统环境

如果是首次使用Docker, 那么请使用开发环境配置中的方法安装并配置Docker。同时, 本章中会使用到 `git-lfs` , 如果首次使用 `git-lfs` ，用户需要在自己系统中（并非Docker容器中）执行下述命令进行安装和配置：

```shell
$ curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
$ sudo apt-get install git-lfs
```

## 获取 `model-zoo` 模型

在工作目录下，从SOPHGO提供的SDK包中获取 `model-zoo` 测试包, 并执行以下操作创建并设置好 `model-zoo` ：

```shell
$ mkdir -p model-zoo
$ tar -xvf path/to/model-zoo_<date>.tar.bz2 --strip-components=1 -C model-zoo
```

model-zoo的目录结构如下：

```shell
├── config.yaml
├── requirements.txt
├── dataset
├── harness
├── output
└── ...
```

* config.yaml：包含通用的配置：数据集的目录、模型的根目录等，以及一些复用的参数和命令
* requirements.txt：model-zoo 的 python 依赖
* dataset：目录中包含modelzoo中模型的数据集，将作为 plugin 被 tpu_perf 调用
* output：目录将用于存放编译输出的 bmodel 和一些中间数据
* 其他目录包含各个模型的信息和配置。每个模型对应的目录都有一个 config.yaml 文件，该配置文件中配置了模型的名称、路径和 FLOPs、数据集制作参数，以及模型的量化编译命令。

## 准备运行环境

在系统中（Docker容器外）安装运行 `model-zoo` 所需的依赖:

```shell
# for ubuntu 操作系统
$ sudo apt install build-essential
$ sudo apt install python3-dev
$ sudo apt install -y libgl1
# for centos 操作系统
$ sudo yum install make automake gcc gcc-c++ kernel-devel
$ sudo yum install python-devel
$ sudo yum install mesa-libGL
# 精度测试需要执行以下操作，性能测试可以不执行，推荐使用Anaconda等创建python3.7或以上的虚拟环境
$ cd path/to/model-zoo
$ pip3 install -r requirements.txt
```

另外，进行性能和精度测试时需要调用 TPU 硬件，请安装 TPU 硬件对应的 runtime 环境。

## 配置SOC设备

注意: 如果您的设备是 PCIE 板卡, 可以直接跳过该节内容。

性能测试只依赖于 TPU 硬件对应的 runtime 环境, 所以在工具链编译环境编译完的模型连同 `model-zoo` 整个打包, 就可以在 SOC 环境使用 `tpu_perf` 进行性能与精度测试。但是, SOC设备上存储有限, 完整的 `model-zoo` 与编译输出内容可能无法完整拷贝到 SOC 中。这里介绍一种通过 linux nfs 远程文件系统挂载来实现在 SOC 设备上运行测试的方法。

首先, 在工具链环境服务器『host 系统』安装 nfs 服务:

```shell
$ sudo apt install nfs-kernel-server
```

在 `/etc/exports` 中添加以下内容(配置共享目录):

```shell
/the/absolute/path/of/model-zoo *(rw,sync,no_subtree_check,no_root_squash)
```

其中 `*` 表示所有人都可以访问该共享目录, 也可以配置成特定网段或 IP 可访问, 如:

```shell
/the/absolute/path/of/model-zoo 192.168.43.0/24(rw,sync,no_subtree_check,no_root_squash)
```

然后执行如下命令使配置生效:

```shell
$ sudo exportfs -a
$ sudo systemctl restart nfs-kernel-server
```

另外, 需要为 dataset 目录下的图片添加读取权限:

```shell
$ chmod -R +r path/to/model-zoo/dataset
```

在 SOC 设备上安装客户端并挂载该共享目录:

```shell
$ mkdir model-zoo
$ sudo apt-get install -y nfs-common
$ sudo mount -t nfs <IP>:/path/to/model-zoo ./model-zoo
```

这样便可以在 SOC 环境访问测试目录。SOC 测试其余的操作与 PCIE 基本一致, 请参考下文进行操作; 运行环境命令执行位置的差别, 已经在执行处添加说明。

## 准备数据集

### ImageNet

下载 ImageNet 2012 数据集。

解压后，将 `Data/CLS_LOC/val` 下的数据移动到 model-zoo 如下目录中：

```shell
$ cd path/to/sophon/model-zoo
$ mkdir -p dataset/ILSVRC2012/ILSVRC2012_img_val
$ mv path/to/imagenet-object-localization-challenge/Data/CLS_LOC/val dataset/ILSVRC2012/ILSVRC2012_img_val
# 也可以通过软链接 ln -s 将数据集目录映射到 dataset/ILSVRC2012/ILSVRC2012_img_val
```

### COCO (可选)

如果精度测试用到了 coco 数据集（如yolo等用coco训练的网络），请按照如下步骤下载解压：

```shell
$ cd path/to/model-zoo/dataset/COCO2017/
$ wget http://images.cocodataset.org/annotations/annotations_trainval2017.zip
$ wget http://images.cocodataset.org/zips/val2017.zip
$ unzip annotations_trainval2017.zip
$ unzip val2017.zip
```

### Vid4 (可选)

如果需要对 BasicVSR 进行精度测试，请按照如下步骤下载解压 Vid4 数据集：

```shell
$ pip3 install gdown
$ cd path/to/model-zoo/dataset/basicvsr/
$ gdown https://drive.google.com/open?id=1ZuvNNLgR85TV_whJoHM7uVb-XW1y70DW --fuzzy
$ unzip -o Vid4.zip -d eval
```

## 准备工具链编译环境

建议在 docker 环境使用工具链软件，可以参考基础环境配置安装Docker。并在工作目录（即 `model-zoo` 所在目录）下执行以下命令创建Docker容器：

```shell
$ docker pull sophgo/tpuc_dev:v3.4
$ docker run --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:v3.4
```

如果要让容器在退出后删除，可以添加 `--rm` 参数：

```shell
$ docker run --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:v3.4 --rm
```

运行命令后会处于Docker的容器中，从SOPHGO提供的SDK包中获取最新的 `tpu-mlir` wheel安装包，例如 `tpu_mlir-*-py3-none-any.whl`。在Docker容器中安装TPU-MLIR:

```shell
$ pip install tpu_mlir-*-py3-none-any.whl[all]
```

## 模型性能和精度测试流程

### 模型编译

模型编译过程需要在Docker内进行，Docker内需要按照上文要求安装 `tpu_mlir`。

`model-zoo` 的相关 `confg.yaml` 配置了SDK的测试内容。以 `resnet18-v2` 为例，其配置文件为 `model-zoo/vision/classification/resnet18-v2/mlir.config.yaml` 。

执行以下命令，可以编译 `resnet18-v2` 模型：

```shell
$ cd ../model-zoo
$ python3 -m tpu_perf.build --target BM1684X --mlir vision/classification/resnet18-v2/mlir.config.yaml
```

其中， `--target` 用于指定处理器型号，目前支持 `BM1684`  、 `BM1684X` 、 `BM1688` 、 `BM1690` 、 `CV186X` 。

执行以下命令, 可以编译全部高优先级测试样例:

```shell
$ cd ../model-zoo
$ python3 -m tpu_perf.build --target BM1684X --mlir -l full_cases.txt --priority_filter high
```

完整编译可能需要提前预留 2T 以上的空间，请根据实际情况调整。其中 `--clear_if_success` 参数可用于在编译成功后删除中间文件，节省空间。

此时会编译以下高优先级模型（由于model-zoo的模型在持续添加中，这里只列出部分模型）：

```shell
* efficientnet-lite4
* mobilenetv2
* resnet18-v2
* resnet50-v2
* shufflenet_v2
* squeezenet1.0
* vgg16
* yolov5s
* ...
```

编译结束后, 会看到新生成的 `output` 文件夹，编译输出内容都在该文件夹中，此编译结果可以用于性能测试和精度测试，无需重新编译。但需要修改 `output` 文件夹的属性, 以保证其可以被Docker外系统访问：

```shell
$ chmod -R a+rw output
```

### 性能测试

性能测试需要在 Docker 外面的环境中进行，此处假设已经安装并配置好了 TPU 硬件对应的 runtime 环境。退出 Docker 环境:

```shell
$ exit
```

**PCIE板卡**

PCIE 板卡下运行以下命令, 测试生成的高优先级模型的 `bmodel` 性能：

```shell
$ cd model-zoo
$ python3 -m tpu_perf.run --target BM1684X --mlir -l full_cases.txt --priority_filter high
```

其中， `--target` 用于指定处理器型号，目前支持 `BM1684`  、 `BM1684X` 、 `BM1688` 、 `BM1690` 、 `CV186X` 。

注意：如果主机上安装了多块SOPHGO的加速卡，可以在使用 `tpu_perf` 的时候，通过添加 `--devices id` 来指定 `tpu_perf` 的运行设备：

```shell
$ python3 -m tpu_perf.run --target BM1684X --devices 2 --mlir -l full_cases.txt --priority_filter high
```

**SOC设备**

SOC 设备使用以下步骤, 测试生成的高优先级模型的 `bmodel` 性能。

```shell
$ cd model-zoo
$ python3 -m tpu_perf.run --target BM1684X --mlir -l full_cases.txt --priority_filter high
```

**输出结果**

运行结束后, 性能数据在 `output/stats.csv` 中可以获得。该文件中记录了相关模型的运行时间、计算资源利用率和带宽利用率。下方为 `resnet18-v2` 的性能测试结果：

```shell
name,prec,shape,gops,time(ms),mac_utilization,ddr_utilization,processor_usage
resnet18-v2,FP32,1x3x224x224,3.636,6.800,26.73%,10.83%,3.00%
resnet18-v2,FP16,1x3x224x224,3.636,1.231,18.46%,29.65%,2.00%
resnet18-v2,INT8,1x3x224x224,3.636,0.552,20.59%,33.20%,3.00%
resnet18-v2,FP32,4x3x224x224,14.542,26.023,27.94%,3.30%,3.00%
resnet18-v2,FP16,4x3x224x224,14.542,3.278,27.73%,13.01%,2.00%
resnet18-v2,INT8,4x3x224x224,14.542,1.353,33.59%,15.46%,2.00%
```

### 精度测试

精度测试需要在 Docker 外面的环境中进行，此处假设已经安装并配置好了 TPU 硬件对应的 runtime 环境。退出 Docker 环境:

```shell
$ exit
```

PCIE 板卡下运行以下命令, 测试生成的高优先级模型的 `bmodel` 精度：

```shell
$ cd model-zoo
$ python3 -m tpu_perf.precision_benchmark --target BM1684X --mlir -l full_cases.txt --priority_filter high
```

其中， `--target` 用于指定处理器型号，目前支持 `BM1684`  、 `BM1684X` 、 `BM1688` 、 `BM1690` 、 `CV186X` 。

注意：

- 如果主机上安装了多块SOPHGO的加速卡，可以在使用 `tpu_perf` 的时候，通过添加 `--devices id` 来指定 `tpu_perf` 的运行设备。如：

```shell
$ python3 -m tpu_perf.precision_benchmark --target BM1684X --devices 2 --mlir -l full_cases.txt --priority_filter high
```

- `BM1688` 、 `BM1690` 、 `CV186X` 精度测试需要额外配置以下环境变量：

```shell
$ export SET_NUM_SAMPLES_YOLO=200
$ export SET_NUM_SAMPLES_TOPK=100
$ export SET_NUM_SAMPLES_BERT=200
```

具体参数说明可以通过以下命令获得：

```shell
$ python3 -m tpu_perf.precision_benchmark --help
```

输出的精度数据在 `output/topk.csv` 中可以获得。下方为 `resnet18-v2` 的精度测试结果：

```shell
name,top1,top5
resnet18-v2-FP32,69.68%,89.23%
resnet18-v2-INT8,69.26%,89.08%
```

## FAQ

此章节列出一些tpu_perf安装、使用中可能会遇到的问题及解决办法。

### invalid command 'bdist_wheel'

tpu_perf编译之后安装，如提示如下图错误，由于没有安装wheel工具导致。

则先运行：

```shell
$ pip3 install wheel
```

再安装whl包

### not a supported wheel

tpu_perf编译之后安装，如提示如下图错误，由于pip版本导致。

则先运行：

```shell
$ pip3 install --upgrade pip
```

再安装whl包

### no module named 'xxx'

安装运行model-zoo所需的依赖时，如提示如下图错误，由于pip版本导致。

则先运行：

```shell
$ pip3 install --upgrade pip
```

再安装运行 model-zoo 所需的依赖

### 精度测试因为内存不足被kill

# 附录05：TPU Profile工具使用指南

本章节主要是介绍如何利用Profile数据及TPU Profile工具，可视化模型的完整运行流程，以便于进行模型性能分析。当前Profile工具支持 `BM1684`， `BM1684X` , `BM1688` , `CV186X` , `BM1690` 。

## 编译bmodel

TPU Profile是将Profile数据转换为可视化网页的工具。首先先生成bmodel，下面以tpu-mlir工程中的yolov5s模型来演示。

由于Profile数据会把编译中的一些layer信息保存到bmodel中，导致bmodel体积变大，所以默认是关闭的。打开方式是在调用 `model_deploy` 时加上 `--debug` 选项。如果在编译时未开启该选项，运行时开启Profile得到的数据在可视化时，会有部分数据缺失。在Docker内生成bmodel的命令如下：

```shell
# 生成 top mlir
$ model_transform \
    --model_name yolov5s \
    --model_def ../yolov5s.onnx \
    --input_shapes [[1,3,640,640]] \
    --mean 0.0,0.0,0.0 \
    --scale 0.0039216,0.0039216,0.0039216 \
    --keep_aspect_ratio \
    --pixel_format rgb \
    --output_names 350,498,646 \
    --test_input ../image/dog.jpg \
    --test_result yolov5s_top_outputs.npz \
    --mlir yolov5s.mlir
```

```shell
# 将top mlir转换成fp16精度的bmodel
$ model_deploy \
    --mlir yolov5s.mlir \
    --quantize F16 \
    --processor BM1684X \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --model yolov5s_1684x_f16.bmodel \
    --debug
```

通过以上命令，将 `yolov5s.onnx` 编译成了 `yolov5s_bm1684x_f16.bmodel` ，其中， `--debug` 参数将记录profile数据。

## 生成Profile原始数据

将生成的 `yolov5s_bm1684x_f16.bmodel` 拷贝到已安装libsophon的运行环境上。同编译过程，运行时的Profile功能默认是关闭的，防止在做profile保存与传输时产生额外时间消耗。需要开启profile功能时，在运行编译好的bmodel前设置环境变量 `BMRUNTIME_ENABLE_PROFILE=1` 即可。然后用libsophon中提供的模型测试工具 `bmrt_test` 运行bmodel，生成profile数据。在Docker外执行如下命令：

```shell
export BMRUNTIME_ENABLE_PROFILE=1
bmrt_test --bmodel yolov5s_1684x_f16.bmodel
```

运行完成后会在当前目录生成 `bmprofile_data-1` 文件夹, 为全部的Profile数据。

## 可视化Profile数据

将 `bmprofile_data-1` 目录拷贝回Docker内的tpu-mlir工程环境。tpu-mlir提供了 `tpu_profile` 脚本，来把生成的二进制profile数据转换成网页文件并进行可视化。在Docker内执行如下命令：

```shell
# 将bmprofile_data-1目录的profile原始数据转换成网页放置到bmprofile_out目录
# 如果有图形界面，会直接打开浏览器，直接看到结果
tpu_profile bmprofile_data-1 bmprofile_out --arch BM1684X
ls bmprofile_out
# echarts.min.js  profile_data.js  result.html
```

对于 `BM1688` 或 `CV186X` 的模型，若要使profile中带有layer信息，需要额外拷贝 `yolov5s_1684x_f16` （与bmodel同名）目录下的 `tensor_location.json` 和 `final.mlir` 到 `bmprofile_data-1` 目录中。 `BM1690` 暂不支持显示模型layer信息。

用浏览器打开 `bmprofile_out/result.html` 可以看到profile的图表。此外，该工具还有其他用法，可通过如下命令进行查看：

```shell
tpu_profile --help
```

在开发手册中有更详细的Profile说明，可以参考。

# 附录06：TDB调试工具使用指南

本章节主要介绍TDB(Tensor Debugger)工具的使用方法，TDB提供了一个和gdb、pdb界面类似的调试窗口，可用于调试 BModel 运行流程，具有添加断点、单步执行、查看内存数据、数据比对、等功能。

此工具目前支持 BM1684、BM1684X、BM1688。

## 准备工作

**环境配置**

首先需要参考开发环境配置章节完成环境配置，进入TPU-MLIR的Docker容器，并在其中安装tpu_mlir。

若已完成环境配置可忽略此步骤。

**生成bmodel**

在使用TDB之前需要先通过TPU-MLIR生成bmodel文件，可参考编译ONNX模型章节中的命令从模型生成bmodel文件。

需要使用以下2个命令：

```shell
# 将ONNX模型转换为top_mlir
$ model_transform
# 将top_mlir转换为bmodel
$ model_deploy
```

其中，model_deploy 命令需要添加 `--debug` 和 `--compare_all` 参数，用于保存 tpu_output.npz 文件并保留中间数据。

生成 bmodel 时，会自动产生带有 compilation.bmodel 和 final.mlir 文件的目录，此目录称为 Context 目录。

## 启动TDB

```shell
$ tdb [-h]
      [--inputs [INPUTS]]
      [--ref_data [REF_DATA ...]]
      [--plugins [PLUGINS]]
      [--ddr_size [DDR_SIZE]] [-v]
      [context_dir]
```

`tdb` 命令的主要参数说明如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| context_dir | 是 | bmodel文件所在目录，默认为当前目录 |
| -h, --help | 否 | 显示帮助信息 |
| --inputs | 否 | 指定bmodel文件的输入数据 |
| --ref_data | 否 | 指定bmodel文件的参考数据 |
| --plugins | 否 | 添加额外的插件 |
| --ddr_size | 否 | 指定cmodel的ddr_size |
| -v, --verbose | 否 | 使用进度条 |

启动TDB示例：

```shell
$ tdb
# 等效于
$ tdb ./
```

## TDB命令汇总

在进入TDB后，按下两次 tab 可以获取命令提示。

进入TDB后，可使用的命令如下：

| 命令 | 说明 |
|------|------|
| s/start | 加载 bmodel 并进行初始化 |
| r/run | 从头执行到结束，run 指令包含初始化功能 |
| b/break | 在 final.mlir 中添加断点 |
| delete | 删除断点 |
| n/next | 执行下一条指令，可以使用 n [num] 执行多条指令 |
| c/continue | 继续执行指令，直至断点或运行结束 |
| info | 打印断点信息或不同格式的指令 |
| p/print | 打印当前指令或指令对应的数据 |
| w/watch | 监视当前或上一条原子指令的某个输入/输出，当其所在地址的数据变化时返回提示 |
| q/quit | 退出TDB |
| py [py_cmd] | 在TDB中执行 python 命令，集成了 pdb 的代码补全功能 |

其中，`num` 为数字；`py_cmd` 为python命令。

## TDB使用流程

```shell
# 在context目录启动TDB
$ cd path/to/context_dir
$ tdb
# 初始化
$ s
# 逐条执行
$ n
# 添加断点
$ b
# 继续运行
$ c
# 继续调试
$ info/p/w
# 退出
$ q
```

## TDB功能说明

### next功能

```shell
# 使用next单步执行
(tdb) n
# 使用next执行多条指令
(tdb) n [num]
# 使用next执行3条指令
(tdb) n 3
```

n 命令后显示的指令为下一条未执行指令。

### breakpoint功能

breakpoint功能包含查看断点、添加/删除断点、开启/关闭断点功能。使用方法如下：

| 命令 | 说明 | 示例 |
|------|------|------|
| info b/break | 查看断点信息 | info b; info break |
| b/break | 添加断点 | b 1 |
| enable | 开启断点 | enable 1; enable 1,2 |
| disable | 关闭断点 | disable 1; disable 1,2 |
| delete | 删除断点 | delete 1 |

目前支持的断点类型如下：

**value-id**

bmodel 对应的 final.mlir 中的 Operation 前缀，例如：

```shell
%140 = "tpu.Load"(%6) {do_bcast = false …
```

其中， `%140` 和 `%6` 即为 `value-id` ，添加此类型断点示例如下：

```shell
(tdb) b %140
(tdb) b %6
```

**op-name**

final.mlir 中的 Operation 的名称，上述例子中， `tpu.Load` 即为 Op 名称，添加此类型断点示例如下：

```shell
(tdb) b tpu.Load
```

**cmd-id**

解析出的 asm 的 `cmd-id`，上述例子中，D1 和 B0 即为 `cmd-id`，添加此类型断点示例如下：

```shell
(tdb) b D2
(tdb) b B4
```

### info功能

info功能可以打印断点信息或不同格式的指令，使用方法如下：

**info b**

查看断点信息。

```shell
(tdb) info b
index     type enable     text hit
    1  dialect      y tpu.load   0
    2     addr      y       R0   3
    3   cmd-id      y       D1   0
    4 value-id      y       %7   0
```

**info asm**

查看当前的 asm 指令。

```shell
(tdb) info asm
%R0, %B15 = "arith.add"(%R13, %C1.0, %D3) {round_mode = 0} : (memref<1x32x54x160xf32, strides: [8640, 8640, 160, 1]>, f32, none) -> (memref<1x32x54x160xf32, strides: [8640, 8640, 160, 1]>, none)
```

**info mlir**

查看当前指令对应在 final.mlir 中的 Operation 。

```shell
(tdb) info mlir
%137 = "tpu.Active"(%134) {ginfo = #tpu.lg<out_addr = 212992, out_size = 35456, buffer_addr = 0, buffer_size = 71040, eu_align = true, n_idx = [0], n_slice = [1], c_idx = [0], c_slice = [32], d_idx = [0], d_slice = [1], h_idx = [0, 53, 107, 161, 215, 267], h_slice = [54, 55, 55, 55, 53, 53], w_idx = [0, 159], w_slice = [160, 161], id = 6, stage = 1, group_type = 0>, mode = #tpu<active_mode SILU>} : (tensor<1x32x320x320xf32>) -> tensor<1x32x320x320xf32> loc(#loc19)
```

**info reg**

查看当前指令解析后各字段的值。

```shell
(tdb) info reg
{'cmd_short': 1, 'cmd_id': 15, 'cmd_id_dep': 3, 'tsk_typ': 3, 'tsk_eu_typ': 2, 'opd0_const': 0, 'opd1_const': 1, 'opd2_const': 0, 'tsk_opd_num': 2, 'cmd_id_en': 1, 'pwr_step': 0, 'intr_en': 0, 'res0_prec': 2, 'opd0_prec': 2, 'opd1_prec': 2, 'opd2_prec': 0, 'opd0_sign': 1, 'opd1_sign': 1, 'res0_str': 0, 'opd0_str': 0, 'opd1_str': 0, 'opd2_n_str': 0, 'rsvd0': 0, 'res0_n': 1, 'res0_c': 32, 'res0_h': 54, 'res0_w': 160, 'res0_addr': 0, 'opd0_addr': 212992, 'opd1_addr': 1065353216, 'opd2_addr': 0, 'res0_n_str': 0, 'res0_c_str': 0, 'opd0_n_str': 0, 'opd0_c_str': 0, 'opd1_n_str': 0, 'opd1_c_str': 0, 'res0_h_str': 0, 'res0_w_str': 0, 'opd0_h_str': 0, 'opd2_sign': 0, 'rsvd1': 0, 'opd0_w_str': 0, 'opd1_h_str': 0, 'opd1_w_str': 0, 'rsvd2': 0}
```

**info loc**

查看 Context 目录中，tensor_location.json 中对应的 Operation 信息。

```shell
(tdb) info loc
{'core_id': 0,
'file_line': 27,
'loc_index': 4,
'opcode': 'tpu.Active',
'operands': [@163840({name=122_Conv, layout=eu_align, slice=[0:1, 0:32, 0:1, 0:54, 0:160], mlir_type=tensor<1x32x320x320xf32>, memory_type=<1x32x54x160xf32>})],
'results': [@212992({name=124_Mul, layout=eu_align, slice=[0:1, 0:32, 0:1, 0:54, 0:160], mlir_type=tensor<1x32x320x320xf32>, memory_type=<1x32x54x160xf32>})],
'slice_all': False,
'subnet_id': 0,
'tiu_dma_id_after': [17, 3],
'tiu_dma_id_before': [1, 3]}
```

### print功能

print功能不仅可以打印当前的asm指令，还可以打印指令的输入和输出数据，使用方法如下：

| 命令 | 说明 | 示例 |
|------|------|------|
| p op | 查看即将执行的指令 | p op |
| p pre/next | 查看上一条或下一条指令 | p pre; p next |
| p in | 查看下一条未执行指令的输入数据 | p in; p in 0 |
| p out | 查看上一条已执行指令的输出数据 | p out; p out 0 |

### watchpoint功能

watchpoint功能可以监视指令的输入/输出数据，当某个监视变量的数据发生变化时会返回提示，使用方法如下：

**w**

查看当前已添加的 watchpoint，示例如下：

```shell
(tdb) w
index    cmd_type cmd_id core_id enabled                                                   value
    1 CMDType.dma      2       0       y %G0: memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>
```

**w in**

将下一条待执行指令的某个输入添加为 watchpoint，示例如下：

```shell
(tdb) n
%R15.2688, %D2 = "dma.tensor"(%G0, %B0) {decompress = False} : (memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>, none) -> (memref<1x32x3x36xf32, strides: [108, 108, 36, 1]>, none)
(tdb) w in 0
(tdb) w
index    cmd_type cmd_id core_id enabled                                                   value
    1 CMDType.dma      2       0       y %G0: memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>
```

可以看到，w in 0 将下一条待执行指令的第一个输入 %G0 添加为 watchpoint 。

**w out**

将上一条已执行指令的某个输出添加为 watchpoint，示例如下：

```shell
(tdb) w out 0
(tdb) w
index    cmd_type cmd_id core_id enabled                                                         value
    1 CMDType.dma      2       0       y       %G0: memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>
    2 CMDType.dma      1       0       y %R0: memref<1x3x110x322xf32, strides: [35424, 35424, 322, 1]>
```

**p w idx old/now**

打印已添加 watchpoint 的值，示例如下：

其中 idx 是使用 w 命令返回的 watchpoint 的 index ，old 表示查看该 watchpoint 最初被添加时的数据，now 表示查看 watchpoint 当前数据。

old/now 可省略，默认为 now，即查看 watchpoint 当前数据。

```shell
(tdb) w
index    cmd_type cmd_id core_id enabled                                                         value
    1 CMDType.dma      2       0       y       %G0: memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>
    2 CMDType.dma      1       0       y %R0: memref<1x3x110x322xf32, strides: [35424, 35424, 322, 1]>
(tdb) p w 1
(tdb) p w 1 old
```

**w delete [idx]**

删除已添加的 watchpoint，示例如下：

当输入 idx 时表示删除对应的 watchpoint，不输入 idx 时表示删除全部的 watchpoint。

```shell
(tdb) w
index    cmd_type cmd_id core_id enabled                                                         value
    1 CMDType.dma      2       0       y       %G0: memref<1x32x3x36xf32, strides: [3456, 108, 36, 1]>
    2 CMDType.dma      1       0       y %R0: memref<1x3x110x322xf32, strides: [35424, 35424, 322, 1]>
    3 CMDType.tiu     11       0       y %R13: memref<1x32x54x160xsi16, strides: [8640, 8640, 160, 1]>
(tdb) w delete 1
(tdb) w
index    cmd_type cmd_id core_id enabled                                                         value
    2 CMDType.dma      1       0       y %R0: memref<1x3x110x322xf32, strides: [35424, 35424, 322, 1]>
    3 CMDType.tiu     11       0       y %R13: memref<1x32x54x160xsi16, strides: [8640, 8640, 160, 1]>
(tdb) w delete
(tdb) w
index cmd_type cmd_id core_id enabled value
```

# py功能

py功能可以在TDB环境下直接执行python命令，使用方法如下：

```shell
(tdb) py a = 2
(tdb) py b = a + 2
(tdb) py print(b)
4
```

# BModel Disassembler

BModel Disassembler 可以对 bmodel 文件进行反汇编得到 MLIR 格式的 atomic 指令的汇编代码，即 asm 指令，用于分析模型的最终运行命令。

使用时首先需要进入 Context 目录，使用方法如下：

```shell
$ bmodel_dis [-h] [--format {mlir,reg,bits,bin,reg-set}] bmodels [bmodels ...]
```

其中，`--format` 可以指定输出格式，默认使用mlir格式，bmodels 表示要解析的bmodel文件。使用示例如下：

```shell
$ bmodel_dis compilation.bmodel
$ bmodel_dis --format reg compilation.bmodel
```

可将输出结果保存至文件，方法如下：

```shell
$ bmodel_dis compilation.bmodel > dis_bmodel.mlir
$ bmodel_dis --format reg compilation.bmodel > dis_reg.json
```

# BModel Checker

BModel Checker 用于查找 bmodel 中的错误（codegen错误），如果在 model_deploy 时发现生成的 bmodel 无法与 tpu 的参考数据对齐，则可以使用该工具来定位错误。目前支持 BM1684、BM1684X、BM1688 处理器的 BModel。

在生成 bmodel 文件时，model_deploy 命令需要添加 `--debug` 和 `--compare_all` 参数，用于保存 tpu_output.npz 文件并保留中间数据。

使用方法如下：

```shell
$ bmodel_checker [-h]
                 [--tolerance TOLERANCE]
                 [--report REPORT] [--fail_fast]
                 [--quiet] [--no_interactive]
                 [--dump_mode {failed,all,never}]
                 context_dir reference_data
```

`bmodel_checker` 的主要参数说明如下：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| context_dir | 是 | bmodel文件所在目录 |
| reference_data | 是 | tpu_output.npz文件位置 |
| quiet | 否 | 不显示执行进度条 |
| fail_fast | 否 | 在发现第一个错误的时候就停下来 |
| dump_mode | 否 | 指定dump命令下载的数据，默认为failed，还可以是all或never |
| tolerance | 否 | 指定比较容差，默认为 "0.99,0.90" |
| report | 否 | 将错误结果输出成文件，默认为 failed_bmodel_outputs.npz |
| no_interactive | 否 | 运行完 bmodel_checker 会直接退出 TDB 模式 |
| cache_mode | 否 | 缓存模式，有 online, offline, generate 三种选项，默认为 online |

使用 `bmodel_checker` 需要进入 Context 目录，使用示例如下：

```shell
$ bmodel_checker ./ ../yolov5s_bm1684x_f32_tpu_outputs.npz
$ bmodel_checker ./ ../yolov5s_bm1684x_f32_tpu_outputs.npz --fail_fast
$ bmodel_checker ./ ../yolov5s_bm1684x_f32_tpu_outputs.npz --tolerance 0.99,0.90
```

执行 `bmodel_checker` 命令后，会输出检查报告，并将错误的输出结果保存到 `failed_bmodel_outputs.npz` 文件中，下面对检查报告进行说明：

其中，"对勾"表示通过，即该数据被检查，且其相似度符合 `cos>0.99, eul>0.9` (默认阈值，可通过 tolerance 参数修改)；"叉号"表示错误，即该数据没有达到要求的相似度；"问号"表示未知，即没有找到对应的参考数据，无法确定此数据的正确性。

输出检查报告后会自动进入交互模式。交互模式可提供对错误的详细浏览，而且还可以快速在不同行之间跳转。

## check summary

使用 `check summary` 命令可以重新打印检查报告。

值得一提的是，使用 `check summary reduce` 命令可以聚合相同行号的输入和输出。

## check data

```shell
(tdb) check data [file-line]
```

其中，`file-line` 为检查报告中的行号，对应 final.mlir 的行号。此命令可以给出 `file-line` 对应指令的所有输入输出数据的描述信息。

```shell
(tdb) check data [file-line] [index]
```

其中，`index` 为 `check data [file-line]` 命令输出数据的 `index`。此命令可以给出对应 `index` 数据的详细信息。

## SOC 设备

当在 SOC 设备上执行时，为了在不引入 mlir 依赖的情况下执行比对，需要先在 Docker 环境内生成缓存，随后在 SOC 设备环境下使用缓存模型比对模型。

```shell
$ bmodel_checker ./ ../yolov5s_bm1684x_f32_tpu_outputs.npz --cache_mode generate # on docker
$ bmodel_checker ./ ../yolov5s_bm1684x_f32_tpu_outputs.npz --cache_mode offline # on soc
```