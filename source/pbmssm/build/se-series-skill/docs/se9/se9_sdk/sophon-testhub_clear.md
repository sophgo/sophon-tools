# 引言

## 术语解释

| 术语 | 说明 |
|------|------|
| BM1688/CV186AH | 算能科技面向深度学习领域推出的两款第五代张量处理器 |
| BM1684X | 算能科技面向深度学习领域推出的第四代张量处理器 |
| BM1684 | 算能科技面向深度学习领域推出的第三代张量处理器 |
| 智能视觉深度学习处理器 | BM1688/CV186AH/BM1684/BM1684X中的神经网络运算单元 |
| VPSS | BM1688/CV186AH中的视频处理子系统，包括图形运算加速单元以及解码单元 |
| VPU | BM1684/BM1684X中的解码单元 |
| VPP | BM1684/BM1684X中的图形运算加速单元 |
| JPU | BM1688/CV186AH/BM1684/BM1684X中的图像JPEG编解码单元 |
| SOPHONSDK | 算能科技基于BM1688/CV186AH/BM1684/BM1684X的原创深度学习开发工具包 |
| PCIe Mode | BM1684/BM1684X的一种工作形态，作为加速设备来进行使用，客户算法运行于x86主机 |
| SoC Mode | BM1688/CV186AH/BM1684/BM1684X的一种工作形态，本身作为主机独立运行，客户算法可以直接运行其上 |
| arm_pcie Mode | BM1684/BM1684X的一种工作形态，搭载BM1684/BM1684X的板卡作为PCIe从设备插到ARM处理器的服务器上，客户算法运行于ARM处理器的主机上 |
| BMCompiler | 面向智能视觉深度学习处理器研发的深度神经网络的优化编译器，可以将深度学习框架的各种深度神经网络转化为处理器上运行的指令流 |
| BMRuntime | 智能视觉深度学习处理器推理接口库 |
| BMCV | 图形运算硬件加速接口库 |
| BMLib | 在内核驱动之上封装的一层底层软件库，设备管理、内存管理、数据搬运、API发送、A53使能、功耗控制 |
| mlir | 由TPU-MLIR生成的中间模型格式，用于迁移或者量化模型 |
| BModel | 面向智能视觉深度学习处理器的深度神经网络模型文件格式，其中包含目标网络的权重（weight）、指令流等 |
| BMLang | 面向智能视觉深度学习处理器的高级编程模型，用户开发时无需了解底层硬件信息 |
| TPUKernel | 基于智能视觉深度学习处理器原子操作(根据BM1688/CV186AH/BM1684/BM1684X指令集封装的一套接口)的开发库。 |
| SAIL | 支持Python/C++接口的SOPHON Inference推理库，是对BMCV、sophon-media、 BMLib、BMRuntime等的进一步封装 |
| TPU-MLIR | 智能视觉深度学习处理器编译器工程，可以将不同框架下预训练的神经网络，转化为可以在算能智能视觉深度学习处理器上高效运算的bmodel |

## 注意事项

- 推荐使用cmake中的find_package查找libsophon和sophon-media的库包，并进行链接。
- SoC模式下，SDK动态库文件位于/opt/sophon/目录下。
- SoC模式下，通过开机时的systemd服务，自动加载/opt/sophon/libsophon-current/data下的ko内核模块。如用户定义的自启动服务，并且依赖BM168X，请确保在ko加载后启动。

## 授权

BM1688/CV186AH SOPHONSDK是算能科技自主研发的原创深度学习开发工具包，未经算能科技事先书面授权，其它第三方公司或个人不得以任何形式或方式复制、发布和传播。

## 帮助与支持

在使用过程中，如有关于BM1688/CV186AH SOPHONSDK的任何问题或者意见和建议，请联系相关技术支持。

# 算法移植概述

**对于基于深度学习的视频/图片分析任务来说，通常都包括如下几个步骤：**

1. 视频/图片解码
2. 输入预处理
3. 模型推理
4. 输出后处理
5. 视频/图片编码

实际任务中，算法往往还会包含多个不同神经网络模型，因此，步骤2-4会根据需要反复执行多次。

## 硬件加速支持情况

实践证明，单纯针对神经网络运算进行加速，已经无法满足真实场景的需求。为了提高算法运行效率，BM1688、CV186AH在硬件设计中，还集成了编解码、图像处理等操作的硬件加速模块。

**用户通过 SOPHONSDK 中提供的相应软件接口库，可以对如上几个步骤进行针对性地加速，从而便捷地开发出高效的算法和应用。**

为了满足客户对不同风格接口使用的偏好，我们还对硬件加速接口库进行了多次封装，用户可以自行选取合适的接口库进行开发，具体情况总结如下：

| **任务流程** | **是否支持硬件加速** | **SAIL高级接口库** | **OPENCV接口库** | **FFMPEG接口库** | **Native接口库** |
|--------------|----------------------|--------------------|------------------|------------------|------------------|
| 视频/图片解码 | 支持                 | sail::Decoder      | Y                | Y                | BMCV(图片)       |
| 输入预处理    | 支持                 | sail::Bmcv         | Y                | N                | BMCV             |
| 模型推理      | 支持                 | sail::Engine       | N                | N                | BMruntime        |
| 输出后处理    | 部分支持             | sail::Bmcv         | N                | N                | BMCV             |
| 视频/图片编码 | 支持                 | sail::Bmcv         | Y                | Y                | BMCV(图片)       |

值得一提的是，为了提高算法效率以及硬件特性的要求，用户在调用硬件加速接口的时候需要注意以下几个方面，后续的文档会通过实例来进行具体阐述：

1. **内存零copy**
2. **申请物理连续内存**
3. **将多个预处理步骤进行合并**

## C/C++/Python三种编程接口

目前支持C/C++/Python三种编程接口：

**BMRuntime模块支持C/C++接口编程，BMCV、BMLib支持C++接口编程；Python/C++编程接口基于SAIL库实现**。

为进一步方便开发使用，sophon-demo在调用BMLib时，进行了简易的封装，用户可参考sophon-demo/include目录。

SAIL（SOPHON Artificial Intelligent Library），是 **对 SOPHONSDK 中的 BMRuntime、 BMCV、 BMLib、sophon-media库的高级封装**，将 SOPHONSDK中原有的"加载 BModel 并驱动智能视觉深度学习处理器推理"、"驱动视频处理子系统VPSS 做图像处理以及编解码"等功能抽象成更为简单的 C++ 接口对外提供；并且使用 pybind11 再次封装，提供了简洁易用的 Python 接口。目前， SAIL 模块中所有的类、枚举、函数都在 "sail" 命名空间下。

关于SAIL C++/Python 接口详细内容请阅读doc目录下的《sophon-sail_zh》。

# C/C++编程详解

这个章节将会选取 sophon-demo 中的 YOLOV5 检测算法作为示例，说明各个步骤的接口调用和注意事项，样例代码路径：sophon-demo/sample/YOLOV5。

[BMRUNTIME开发参考手册](https://doc.sophgo.com/sdk-docs/v23.07.01/docs_latest_release/docs/tpu-runtime/reference/html/index.html)

这个示例程序采用了 **OPENCV解码+BMCV图片预处理** 的组合进行开发，您也可以根据您的需要采用不同的接口开发

我们按照算法的执行先后顺序展开介绍：

1. **加载bmodel模型**
2. **预处理**
3. **推理**
4. **注意事项**

## 加载bmodel

```c++
BMNNContext(BMNNHandlePtr handle, const char* bmodel_file):m_handlePtr(handle){
    bm_handle_t hdev = m_handlePtr->handle();

    // init bmruntime contxt
    m_bmrt = bmrt_create(hdev);
    if (NULL == m_bmrt) {
        std::cout << "bmrt_create() failed!" << std::endl;
        exit(-1);
    }

    // load bmodel from file
    if (!bmrt_load_bmodel(m_bmrt, bmodel_file)) {
        std::cout << "load bmodel(" << bmodel_file << ") failed" << std::endl;
    }

    load_network_names();
}

void load_network_names() {
    const char **names;
    int num;

    // get network info
    num = bmrt_get_network_number(m_bmrt);
    bmrt_get_network_names(m_bmrt, &names);

    for(int i=0;i < num; ++i) {
        m_network_names.push_back(names[i]);
    }

    free(names);
}

BMNNNetwork(void *bmrt, const std::string& name):m_bmrt(bmrt) {
    m_handle = static_cast<bm_handle_t>(bmrt_get_bm_handle(bmrt));

    // get model info by model name
    m_netinfo = bmrt_get_network_info(bmrt, name.c_str());

    m_max_batch = -1;
    std::vector<int> batches;
    for(int i=0; i<m_netinfo->stage_num; i++){
        batches.push_back(m_netinfo->stages[i].input_shapes[0].dims[0]);
        if(m_max_batch<batches.back()){
            m_max_batch = batches.back();
        }
    }
    m_batches.insert(batches.begin(), batches.end());
    m_inputTensors = new bm_tensor_t[m_netinfo->input_num];
    m_outputTensors = new bm_tensor_t[m_netinfo->output_num];
    for(int i = 0; i < m_netinfo->input_num; ++i) {
        // get data type
        m_inputTensors[i].dtype = m_netinfo->input_dtypes[i];
        m_inputTensors[i].shape = m_netinfo->stages[0].input_shapes[i];
        m_inputTensors[i].st_mode = BM_STORE_1N;
        m_inputTensors[i].device_mem = bm_mem_null();
    }
}
```

这个几个函数的用法比较简单和固定，用户可以参考doc目录下的《算能边缘产品BMRUNTIME开发参考手册》了解更详细的信息。

唯一需要强调的是name字符串变量的用法：在推理代码中，模型的唯一标识就是他的name字符串，这个name需要在compile阶段就进行指定，算法程序也需要基于这个name开发；例如，在调用inference接口时，需要使用模型的name作为入参，让runtime作为索引去查询对应的模型，错误的name会造成inference失败。

## 预处理

### 预处理初始化

预处理初始化时，需要提前创建适当的bm_image对象保存中间结果，这样可以节省反复内存申请释放造成的开销，提高算法效率，具体代码如下：

```c++
int aligned_net_w = FFALIGN(m_net_w, 64);
int strides[3] = {aligned_net_w, aligned_net_w, aligned_net_w};
for(int i=0; i<max_batch; i++){
    // init bm images for storing results
    auto ret= bm_image_create(m_bmContext->handle(), m_net_h, m_net_w,
        FORMAT_RGB_PLANAR,
        DATA_TYPE_EXT_1N_BYTE,
        &m_resized_imgs[i], strides);
    assert(BM_SUCCESS == ret);
}
bm_image_alloc_contiguous_mem (max_batch, m_resized_imgs.data());

// bm images for storing inference inputs
bm_image_data_format_ext img_dtype = DATA_TYPE_EXT_FLOAT32;   //FP32

if (tensor->get_dtype() == BM_INT8) {   // INT8
    img_dtype = DATA_TYPE_EXT_1N_BYTE_SIGNED;
}

auto ret = bm_image_create_batch(m_bmContext->handle(), m_net_h, m_net_w,
    FORMAT_RGB_PLANAR,
    img_dtype,
    m_converto_imgs.data(), max_batch);
assert(BM_SUCCESS == ret);
```

不同于bm_image_create()函数只创建一个bm_image对象，bm_image_create_batch()会根据最后一个参数batch，创建一组bm_image对象，而且这组对象所使用的data域是物理连续的。使用物理连续的内存是硬件加速器的特殊需求，在析构函数，可以使用bm_image_destroy_batch()对内存进行释放。

接下来是输入的处理过程，这个示例算法同时支持图片和视频作为输入，在main.cpp的main()函数中，我们以视频为例，详细的写法如下：

### 打开视频流

```c++
// open stream
cv::VideoCapture cap(input_url, cv::CAP_ANY, dev_id);
if (!cap.isOpened()) {
    std::cout << "open stream " << input_url << " failed!" << std::endl;
    exit(1);
}

// get resolution
int w = int(cap.get(cv::CAP_PROP_FRAME_WIDTH));
int h = int(cap.get(cv::CAP_PROP_FRAME_HEIGHT));
std::cout << "resolution of input stream: " << h << "," << w << std::endl;
```

上面这段代码和标准的opencv处理视频流程几乎相同。

### 解码视频帧

```c++
// get one mat 
cv::Mat img;
if (!cap.read(img)) { //check
    std::cout << "Read frame failed or end of file!" << std::endl;
    exit(1);
}

std::vector<cv::Mat> images;
images.push_back(img);
```

### Mat 转换 bm_image

由于BMCV预处理接口和网络推理接口都需要使用bm_image对象作为输入，因此解码后的视频帧需要转换到bm_image对象。推理完成之后，再使用bm_image_destroy()接口进行释放。需要注意的是，这个转换过程没有发生内存拷贝。

```c++
// mat -> bm_image
CV_Assert(0 == cv::bmcv::toBMI((cv::Mat&)images[i], &image1, true));

//destroy
bm_image_destroy(image1);
```

### 预处理

bmcv_image_vpp_convert_padding()函数使用VPP硬件资源，是预处理过程加速的关键，需要配置参数 padding_attr。 bmcv_image_convert_to()函数用于进行线性变换，需要配置参数 converto_attr。

```c++
// set padding_attr
bmcv_padding_atrr_t padding_attr;
memset(&padding_attr, 0, sizeof(padding_attr));
padding_attr.dst_crop_sty = 0;
padding_attr.dst_crop_stx = 0;
padding_attr.padding_b = 114;
padding_attr.padding_g = 114;
padding_attr.padding_r = 114;
padding_attr.if_memset = 1;
if (isAlignWidth) {
    padding_attr.dst_crop_h = images[i].rows*ratio;
    padding_attr.dst_crop_w = m_net_w;

    int ty1 = (int)((m_net_h - padding_attr.dst_crop_h) / 2);
    padding_attr.dst_crop_sty = ty1;
    padding_attr.dst_crop_stx = 0;
}else{
    padding_attr.dst_crop_h = m_net_h;
    padding_attr.dst_crop_w = images[i].cols*ratio;

    int tx1 = (int)((m_net_w - padding_attr.dst_crop_w) / 2);
    padding_attr.dst_crop_sty = 0;
    padding_attr.dst_crop_stx = tx1;
}

// do not crop
bmcv_rect_t crop_rect{0, 0, image1.width, image1.height};

auto ret = bmcv_image_vpp_convert_padding(m_bmContext->handle(), 1, image_aligned, &m_resized_imgs[i],
    &padding_attr, &crop_attr);

// set converto_attr
float input_scale = input_tensor->get_scale();
input_scale = input_scale* (float)1.0/255;
bmcv_convert_to_attr converto_attr;
converto_attr.alpha_0 = input_scale;
converto_attr.beta_0 = 0;
converto_attr.alpha_1 = input_scale;
converto_attr.beta_1 = 0;
converto_attr.alpha_2 = input_scale;
converto_attr.beta_2 = 0;

// do converto
ret = bmcv_image_convert_to(m_bmContext->handle(), image_n, converto_attr, m_resized_imgs.data(), m_converto_imgs.data());

// attach to tensor
if(image_n != max_batch) image_n = m_bmNetwork->get_nearest_batch(image_n); 
bm_device_mem_t input_dev_mem;
bm_image_get_contiguous_device_mem(image_n, m_converto_imgs.data(), &input_dev_mem);
input_tensor->set_device_mem(&input_dev_mem);
input_tensor->set_shape_by_dim(0, image_n);  // set real batch number
```

# 推理

预处理过程的output是推理过程的input，当推理过程的input数据准备好后，就可以进行推理。

```c++
...

ret = m_bmNetwork->forward();
...
```

# 后处理

后处理的过程因模型而异，而且大部分是中央处理器执行的代码，就不再这里赘述。需要注意的是我们在BMCV中也提供了一些可以用于加速的接口，如bmcv_sort、bmcv_nms等，对于其他需要使用硬件加速的情况，可根据需要使用TPUKernel进行开发。

以上就是 YOLOV5 示例的简单描述，关于涉及到的接口更加详细的描述，请查看相应模块文档。

# 算法开发注意事项汇总

**根据上面的讨论，我们把一些注意事项汇总如下：**

- 视频解码需要注意：

> **注意**
> 1. 我们支持使用YUV格式作为缓存原始帧的格式，解码后可通过cap.set()接口设置YUV格式。

- 预处理过程需要注意：

> **注意**
> 1. 预处理的操作对象是bm_image，bm_image对象可以类比Mat对象。
> 2. 预处理流程中scale缩放是针对int8模型。在推理数据输入前需要乘scale系数。scale系数是在量化的过程中产生。
> 3. 为多个bm_image对象申请连续物理内存：bm_image_create_batch()。
> 4. resize默认双线性插值算法，具体参考bmcv接口说明。

- 推理过程需要注意：

> **注意**
> 1. 推理过程在device memory上进行，所以推理前输入数据必须已经存储在input tensors的device mem里面，推理结束后的结果数据也是保存在output tensors的device mem里面。

# 解码模块

## OpenCV解码

OpenCV支持YUVI420/BGR格式输出，为了提高性能，示例中解码输出设置yuv格式数据。

简单示例如下：

```c++
cv::VideoCapture cap;
  if (!cap.isOpened()) {
    cap.open(input_url);
}
cap.set(cv::CAP_PROP_OUTPUT_YUV, 1.0); //设置输出YUVI420格式数据，如选择BGR输出则注释掉此行代码
cv::Mat *img = new cv::Mat;
cap.read(*img);
//do something
......
//end
delete img;
```

cap.set接口函数对输出格式设置， cap::read获取cv::Mat对象img，img数据接下来需要通过图像运算加速接口（bmcv模块）对数据进行推理前的预处理操作。

**如果需要使用python-opencv，请正确设置环境变量**

```bash
export PYTHONPATH=/opt/sophon/sophon-opencv-latest/opencv-python:$PYTHONPATH
```

## FFmpeg解码

- C编程接口初始化配置:

```c
// ffmpeg默认输出NV12压缩格式数据, 初始化解码器配置方法如下：
/*set compressed output*/
av_dict_set(&opts, "output_format", "101", 0);

if ((ret = avcodec_open2(*dec_ctx, dec, &opts)) < 0) {
fprintf(stderr, "Failed to open %s codec\n",
            av_get_media_type_string(type));
return ret;
}
```

- Python编程接口

```python
import sophon.sail as sail
decoder = sail.Decoder(filename)
img0 = decoder.read(handle)   #默认输出yuv i420格式
```

# 图形运算加速模块

BMCV提供了一套基于算丰深度学习处理器优化的机器视觉库，目前可以完成色彩空间转换、尺度变换、仿射变换、投射变换、线性变换、画框、JPEG编码、BASE64编码、NMS、排序、特征匹配等操作。

C++接口实现请参考《算能边缘产品BMCV开发参考指南》。

Python接口的实现请参考《sophon-sail_zh》。

BMCV API均是围绕bm_image来进行的。一个bm_image结构对应于一张图片。

## C++语言编程接口

**bm_image结构体**

```c
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    bm_image_private* image_private;
};
```

bm_image 结构成员包括图片的宽高，图片格式，图片数据格式，以及该结构的私有数据。

**图片格式 image_format枚举类型**

```c
typedef enum bm_image_format_ext_{
    FORMAT_YUV420P,
    FORMAT_NV12,
    FORMAT_NV21,
    FORMAT_NV16,
    FORMAT_NV61,
    FORMAT_RGB_PLANAR,
    FORMAT_BGR_PLANAR,
    FORMAT_RGB_PACKED,
    FORMAT_BGR_PACKED,
    FORMAT_GRAY,
    FORMAT_COMPRESSED
}bm_image_format_ext;
```

| 格式              | 说明                                                  |
| ----------------- | ----------------------------------------------------- |
| FORMAT_YUV420P    | 表示预创建一个YUV420格式的图片，有三个plane           |
| FORMAT_NV12       | 表示预创建一个NV12格式的图片，有两个plane             |
| FORMAT_NV21       | 表示预创建一个NV21格式的图片，有两个plane             |
| FORMAT_RGB_PLANAR | 表示预创建一个RGB格式的图片，RGB分开排列，有一个plane |
| FORMAT_BGR_PLANAR | 表示预创建一个BGR格式的图片，BGR分开排列，有一个plane |
| FORMAT_RGB_PACKED | 表示预创建一个RGB格式的图片，RGB交错排列，有一个plane |
| FORMAT_BGR_PACKED | 表示预创建一个BGR格式的图片，BGR交错排列，有一个plane |
| FORMAT_GRAY       | 表示预创建一个灰度图格式的图片，有一个plane           |
| FORMAT_COMPRESSED | 表示预创建一个VPU内部压缩格式的图片，有四个plane      |

**数据存储格式枚举**

```c
typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_4N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
}bm_image_data_format_ext;
```

| 数据格式                     | 说明                                                               |
| ---------------------------- | ------------------------------------------------------------------ |
| DATA_TYPE_EXT_FLOAT32        | 表示所创建的图片数据格式为单精度浮点数                             |
| DATA_TYPE_EXT_1N_BYTE        | 表示所创建图片数据格式为普通带符号1N INT8                          |
| DATA_TYPE_EXT_4N_BYTE        | 表示所创建图片数据格式为4N INT8，即四张带符号INT8图片数据交错排列  |
| DATA_TYPE_EXT_1N_BYTE_SIGNED | 表示所创建图片数据格式为普通无符号1N UINT8                         |
| DATA_TYPE_EXT_4N_BYTE        | 表示所创建图片数据格式为4N UINT8，即四张无符号INT8图片数据交错排列 |

更多BMCV接口使用方法请参考《算能边缘产品BMCV开发参考指南》

## Python语言编程接口

本章节只简要介绍了用例 YOLOv5 所用到的接口函数。

更多接口定义请查阅《 sophon-sail_zh 》。

- **init**

```python
def __init__(handle): 
""" Constructor.
Parameters 
---------
handle : sail.Handle Handle instance 
"""
```

- **convert_to**

```python
def convert_to(input, alpha_beta): 
""" Applies a linear transformation to an image.
Parameters
---------
input : sail.BMImage Input image 
alpha_beta: tuple (a0, b0), (a1, b1), (a2, b2) factors
Returns 
---------
output : sail.BMImage Output image 
"""
```

- **convert_format**

```python
def convert_format(input, output):
"""Convert input to output format.

Parameters
----------
input : sail.BMImage
    BMimage instance
output : sail.BMImage
    output image
"""
```

- **vpp_crop_and_resize_padding**

```python
def vpp_crop_and_resize_padding(input, crop_x0, crop_y0, crop_w, crop_h, resize_w, resize_h, padding):
""" Crop then resize an image using vpp.

Parameters
----------
input : sail.BMImage
    Input image
crop_x0 : int
    Start point x of the crop window
crop_y0 : int
    Start point y of the crop window
crop_w : int
    Width of the crop window
crop_h : int
    Height of the crop window
resize_w : int
    Target width
resize_h : int
    Target height
padding : PaddingAtrr
    padding info

Returns
----------
output : sail.BMImage
    Output image
"""
```

# 微服务器定制化软件包

## 适配场景

1. 芯片：BM1688 CV186AH

2. SDK版本：
   * 1688/cv186 V1.3以及之后版本（适配只打包功能和打包做包功能）

3. 环境需求：
   * 外置存储：
     - 存储分区格式尽量保证ext4，防止特殊分区限制导致做包失败
     - 只打包功能要求外置存储至少是当前emmc使用总量的1.5倍以上
     - 打包做包功能要求外置存储至少是当前emmc使用总量的2.5倍以上
   * 设备需求：
     - 只打包功能要求除去打包设备外需要有一个ubuntu18/20的X86主机
     - 打包做包功能只要求有一个打包做包的设备

## 功能一：打包做包功能

本功能84&X和1688/cv186x平台使用方式完全一致

1. 使用如下命令下载打包需要使用的工具

```bash
pip3 install dfss --upgrade
python3 -m dfss --dflag=socbak
```

下载的文件是一个socbak.zip文件

2. 将外置存储插入目标设备，然后执行如下操作。

```bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

3. 执行如下命令进行打包

```bash
unzip socbak.zip
cd socbak
export SOC_BAK_ALL_IN_ONE=1
bash socbak.sh
```

等待一段时间

4. 执行成功后会生成如下文件

```bash
root@sophon:/socrepack/socbak# tree -L 1
.
├── binTools
├── output
├── script
├── socbak.sh
├── socbak_log.log
└── socbak_md5.txt

3 directories, 3 files
```

其中socbak_log.log文件是执行的信息记录，刷机包在output/sdcard/路径下

# 功能二：只打包功能

1688/186 V1.3以及之后版本

1. 使用如下命令下载打包需要使用的工具

```bash
pip3 install dfss --upgrade
python3 -m dfss --dflag=socbak
```

下载的文件是一个socbak.zip文件

2. 将外置存储插入目标设备，然后执行如下操作

```bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

3. 执行如下命令进行打包

```bash
unzip socbak.zip
cd socbak
bash socBak.sh
```

等待一段时间

4. 执行成功后会生成如下文件（这里的是一个示例，实际情况下生成的文件可能会多一些）

```bash
root@sophon:/socrepack/socbak# tree -L 1 .
.
├── binTools
├── boot.tgz
├── data.tgz
├── fip.bin
├── partition32G.xml
├── recovery.tgz
├── rootfs.tgz
├── script
├── socbak.sh
├── socbak_log.log
└── socbak_md5.txt

2 directories, 9 files
```

5. 使用《针对SOC模式的交叉编译的docekr环境准备方式》(https://developer.sophgo.com/thread/682.html)搭建正确的交叉编译docker环境

6. 下载最新的 bm1688_repack包，解压并进入

7. 建立目录pack,然后将原始刷机包解压到这个目录下

8. cd到depack.sh文件同目录,然后执行./depack.sh脚本进行解包

9. 生成的各个分区压缩包会在update目录下生成,此时将socbak生成的所有文件都拷贝到这个目录下

10. 修改完毕后cd到enpack.sh文件同目录,然后执行./enpack.sh sdcard 或者./enpack.sh tftp 命令进行打包

11. 生成的新的刷机包在update/sdcard和update/tftp

# SoC模式内存修改工具

## 目录

- [工具1:在SoC上使用脚本进行修改](#工具1在soc上使用脚本进行修改)
- [工具2:使用图像化程序远程修改](#工具2使用图像化程序远程修改)

> SoC模式下的内存修改脚本与远程内存修改工具使用时，均需要目标SoC服务器上rootfs-rw分区（即根目录），有200M以上空间。同时，内存修改脚本在目标SoC的存放目录也需要有200M以上空间；使用远程内存修改工具时，目标SoC的/data分区需要200M空间。
> 使用如下命令查看目录的空间大小：

```bash
# 查看根目录
sudo df -h /
# 查看/data分区
sudo df -h /data
# 查看当前目录
sudo df -h .
```

## 工具1:在SoC上使用脚本进行修改

说明：本脚本用于在SoC运行环境中修改 SE9 在SoC模式下的 NPU、VPP 的内存分配。同时，调整 NPU、VPP 后，SoC的操作系统将使用除了 NPU、VPP 、uboot固件之外的所有内存。

> 本脚本默认适配 v1.3release及之后版本。之前的版本修改后有启动失败的风险
> 如果发现设备树没有自动识别正确，请在命令末尾增加一个设备树文件名用于指定设备树

使用教程：

1. 使用浏览器打开并下载 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz ，选择"memory_edit_v<x.x>.tar.xz"压缩包。

2. 登录微服务器，并将脚本压缩包拷贝到SoC微服务器上，执行解压命令并进入该压缩包；并执行命令检查微服务器 NPU、VPU、VPP 当前可以配置的最大内存大小和当前配置的内存大小。

```bash
tar -xaf memory_edit_vx.x.tar.xz
cd memory_edit
./memory_edit.sh -p
```

其中类似如下的输出显示了可配置的最大内存。**其中, MiB（Mebibyte）是计算机存储容量的单位， 1 MiB = 1024 KiB = 1024*1024 Byte。**

```bash
Info: get max memory size ...
Info: max npu+vpp size: 0x97800000 [2424 MiB]
Info: max npu size: 0x97800000 [2424 MiB]
Info: max vpp size: 0x97800000 [2424 MiB]
```

其中类似如下的输出显示了当前配置的内存大小。

```bash
Info: get now memory size ...
Info: now npu size: 0x30000000 [768 MiB]
Info: now vpp size: 0x50000000 [1280 MiB]
```

请检查输出中是否有 Error ，如果有请检查SoC运行环境是否支持内存修改。

3. 进行内存布局的修改，其中输入的三个参数是需要 NPU、VPP 配置的大小的十进制数字，单位MiB；或者为十六进制数值，单位Byte。 **SE9默认没有VPU内存，配置为0即可。**

```bash
# 十进制，单位MiB
./memory_edit.sh -c -npu 300 -vpu 0 -vpp 300
# 十六进制，单位Byte
./memory_edit.sh -c -npu 0x12C00000 -vpu 0x0 -vpp 0x12C00000
```

请检查输出中是否有 Error ，以及类似于如下输出中三个部分的大小是否与您所需要配置的大小相同。

```bash
Info: =======================================================================
Info: output configuration results ...
Info: ion npu mem area(ddr1): 0x12c00000 [300 MiB] 0x68800000 -> 0x7b3fffff
Info: ion vpp mem area(ddr1): 0x12c00000 [300 MiB] 0xed400000 -> 0xffffffff
Info: =======================================================================
Info: start check memory size ...
Info: check npu size: 0x12c00000 [300 MiB]
Info: check vpp size: 0x12c00000 [300 MiB]
Info: check edit size ok
```

4. 如果检查无误，请保存当前工作，​将修改后的 boot.itb 文件替换启动分区中的启动映像，并重启机器使修改生效。

```bash
sudo cp boot.itb /boot && sync
sudo reboot
```

> 如果需要迁移修改配置，请导出这个 boot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version ​命令查看。**

## 工具2:使用图像化程序远程修改

说明：本工具是一个图形化程序，可以通过远程 SSH 修改工作在 SoC 模式下的 BM1688、CV186AH以及BM1684/BM1684X 的 NPU、VPU、VPP 占用空间。默认适配环境为 64 位 win10 操作系统或者带有桌面环境的linux系统。

> 该工具适用于BM1688/CV186AH SOPHONSDK v1.3及以上版本、BM1684/BM1684X SOPHONSDK V22.09.02 及以上SoC版本。
> 当前默认适配桌面系统如下: amd64-win10、amd64-linux(带有完整桌面，如xfce4)、aarch64-linux(带有完整桌面，如xfce4)。

**单远程目标**

使用教程：

1. 使用浏览器打开 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz 并下载最新的远程内存修改工具，选择"qt_mem_edit_V<x.x.x>."文件，其中.exe文件适用于win系统，.AppImage适用于带有桌面环境的linux系统。

2. windows 系统双击程序即可运行，linux 系统可能需要使用 `chmod +x qt_mem_edit_Vx.x.x-架构名.AppImage` 命令使能其具有运行权限后才能运行该程序。

3. 在该程序中配置微服务器远程 SSH 链接需要的 IP、端口、用户名和密码。

4. 点击"修改目录"按钮配置执行文件目录，该目录会在当前操作的host主机上存放远程修改内存的所有过程文件（默认目录为远程内存修改程序所在目录）。

5. 点击"获取信息"按钮获取微服务器当前 NPU、VPP 配置的内存大小信息和最大可以配置的内存大小信息，这些信息将在"获取信息"按钮左侧的文本框中显示。

6. 根据您的需要修改"进行配置"按钮等高的两个个数字框（SE9没有VPU内存，配置为0即可），它们代表了需要配置的 NPU、VPP 各个部分的内存大小（单位 MiB，十进制）。

7. 点击"进行配置"按钮，配置完成后。

8. 查看"远程执行信息"中是否有 Error 输出，如果没有错误输出，请登录微服务器，保存微服务器上当前工作，并重启微服务器使您的修改生效。

```bash
sudo reboot
```

9. 进行操作后执行文件目录下会存放从微服务器上获取的内存修改的所有过程文件，文件名以 memory_edit_p_为前缀代表该文件是"获取信息"操作的过程文件，文件名以 memory_edit_c_为前缀代表该文件是"进行配置"操作的过程文件。

文件名以 memory_edit_p_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── boot.itb                   
    ├── log.txt                   
    ├── memory_edit.sh                
    ├── multi.its                   
    ├── memory_edit_p.log           
    └── output
```

文件名以 memory_edit_c_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── boot.itb                   
    ├── log.txt                   
    ├── memory_edit.sh                
    ├── multi.its                   
    ├── memory_edit_c.log           
    └── output
```

> 在"进行配置"操作的过程文件压缩包中，有一个名为 boot.itb 的文件，如果需要迁移修改配置，请解压并导出这个 boot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下。 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version ​命令查看上述信息**

**多远程目标**

使用教程：

1. 使用浏览器打开 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz 并下载最新的远程内存修改工具，选择"qt_mem_edit_V<x.x.x>."文件，其中.exe文件适用于win系统，.AppImage适用于带有桌面环境的linux系统。

2. windows系统双击程序即可运行，linux系统可能需要使用 `chmod +x qt_mem_edit_Vx.x.x-架构名.AppImage` 命令使能其具有运行权限后才能运行该程序。

3. 修改"进行配置"按钮等高的两个数字框，它们代表了需要配置的 NPU、VPP 各个部分的内存大小（单位 MiB，十进制），配置SE9 VPU默认为空即可。

4. 点击远程内存布局修改工具中的"批量配置"按钮。

5. 配置好需要修改内存的批量远程目标后，点击"批量配置"，在弹出的窗口中选择"yes"，在多台远程设备内存修改时，远程微服务器将会自动重启。执行文件目录下会存放所有远程设备的执行文件。

# BM1688/CV186AH SOPHONSDK源码下载以及编译方法

目前，BM1688/CV186AH SOPHONSDK源码已在github开源发布，您可以下载源码编译生成刷机包，可用于软件定制。

## 编译环境配置

编译BM1688/CV186AH SOPHONSDK源码需要在linux系统上进行，推荐使用ubuntu20.04或者22.04。

在github建立个人账号，并配置好ssh key,下载代码需要用到个人github账号。

## 安装repo

（1）配置repo安装路径

```bash
mkdir ~/bin
```

（2）增加环境变量

```bash
vim ~/.profile
```

在文件最后增加

```bash
PATH=~/bin:$PATH
```

（3）安装repo

```bash
curl https://storage.googleapis.com/git-repo-downloads/repo > ~/bin/repo
chmod a+x ~/bin/repo
```

## 下载代码

请使用以下命令下载SDK源码

```bash
# 创建工作目录
mkdir /your/workspace/path && cd /your/workspace/path
# 下载代码
repo init -u https://github.com/sophgo/manifest.git -m release/edge.xml
```

## docker配置

使用以下命令下载docker镜像文件并导入

```bash
sudo apt-get install python3-pip  qemu qemu-user-static binfmt-support
pip3 install dfss --upgrade
python -m dfss --url=open@sophgo.com:/gemini-sdk/docker/ubuntu_bm1688.tar 

#导入docker镜像，有导入过的可以不用操作
sudo cat ubuntu_bm1688.tar | docker import - bm1688     
```

将以下命令添加到 `~/.bashrc`

```bash
function run_docker() {
    docker run  -e LOCAL_USER_ID=`id -u $USER_ID` --privileged -itd -v $2:/project/$1 --name $1  bm1688:latest /bin/bash
}
```

重新source文件，使改动生效

```bash
source ~/.bashrc
```

调用run_docker命令，进入docker编译环境

```bash
# 在进入docker前将代码下载到 /your/workspace/path
run_docker SDK_build  /your/workspace/path    
# 进入container
docker run -it SDK_build /bin/bash
pip3 install jinja2 
```

## 编译源码

请使用以下命令编译BM1688/CV186AH SOPHONSDK源码

```bash
defconfig  bm1688_wevb_emmc
#需要有root权限或者使用docker
build_bm1688_all  
```

生成的升级包在install/soc_bm1688_wevb_emmc/package_edge/sdcard

# BM1684(X)_to_BM1688(CV186AH)兼容性文档

该文档面向有一定SOPHONSDK使用经验的用户，它还需丰富和完善，如果您发现了新的问题或有改进建议，可以反馈给我们的工作人员。

## 目录

- [获取BM1688/CV186AH SOPHONSDK](#获取bm1688cv186ah-sophonsdk)
- [准备BM1688/CV186AH的bmodel](#准备bm1688cv186ah的bmodel)

## 获取BM1688/CV186AH SOPHONSDK

BM1688/CV186AH的SOPHONSDK与BM1684/BM1684X的SOPHONSDK不是同一套，所以需要另外从官网获取。下载后使用工具解压，可以得到各个模块的安装包、示例程序，SDK目录结构如下：

| 文件夹名 | 备注 |
|---------|------|
| sophon-img | SoC模式安装包等 |
| sophon_media | 支持SOPHON设备硬件加速的多媒体库 |
| tpu-mlir | TPU编译器工具链 |
| tpu-perf | 模型性能和精度验证工具包 |
| sophon-stream | 基于pipeline的高性能推理框架 |
| sophon-demo | 针对单模型或者场景的综合例程 |
| sophon-sail | 对底层接口进行C++/Python API封装的接口库 |
| isp-tools | ISP各个模块的参数调节工具 |
| doc | 各个模块的文档资料合集 |

## 准备BM1688/CV186AH的bmodel

重新编译能在BM1688/CV186AH上运行的bmodel，需要使用能够支持BM1688/CV186AH的tpu-mlir。

一般来说，有以下几个步骤：

1. 准备一台x86 ubuntu，相应的规格参数，取决于需要编译的模型大小，建议运行内存32GB以上，这样足够编译绝大多数模型。

2. 运行如下命令，搭建tpu-mlir环境：

```bash
# 拉取latest版本docker，目前对应tpuc_dev:v3.2，如果您的环境已经有这个image了，也需要重新执行以下命令。
docker pull sophgo/tpuc_dev:latest 

# 这里将本级目录映射到docker内的/workspace目录,用户需要根据实际情况将demo的目录映射到docker里面
# myname只是举个名字的例子, 请指定成自己想要的容器的名字
docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:latest

# 此时已经进入docker，并在/workspace目录下

# 通过pip下载tpu_mlir，如果下不下来，可以使用清华源加速。
pip install tpu_mlir

# TPU-MLIR在对不同框架模型处理时所需的依赖不同。对于onnx或torch生成的模型文件，使用类似下面命令安装额外的依赖环境:
pip install tpu_mlir[onnx]
pip install tpu_mlir[torch]

# 目前支持五种配置: onnx, torch, tensorflow, caffe, paddle。可使用一条命令安装多个配置，也可直接安装全部依赖环境:
pip install tpu_mlir[onnx,torch]
pip install tpu_mlir[all]
```

3. 编译模型：

只要将以前的编译命令或脚本中model_deploy.py部分的 `--chip` 或 `--processor`，参数值更改成bm1688/cv186x，其他的部分都不用改动，运行之后就可以获取能在BM1688/CV186AH上运行的bmodel。

## 编译BM1688双核模型

BM1688由两个相同的核组成，支持一个模型的数据切分到两个核上面跑，tpu-mlir model_deploy.py为BM1688新增了 `--num_core` 参数，如果您想要一个模型跑两个核，可以在model_deploy.py中新增 `--num_core 2` 参数，这样就编译出来的模型，会由两个核来执行。

## 量化注意事项

以前的calibration_table和qtable均是可以复用的，如果在mlir编译bmodel的过程中出现类似算子不支持的报错，或者量化出来的模型精度不好，再重新生成calibration_table或qtable。

## 准备编译依赖的SDK

如果您使用C++编程，您仍然需要获取sophon-img目录下的libsophon_soc_${x.y.z}/_aarch64.tar.gz和sophon_media目录下的sophon-media-soc_${x.y.z}/_aarch64.tar.gz发布包，作为交叉编译依赖的头文件和库文件。

如果以前有手动链接 **bmion/bmjpulite/bmjpuapi/bmvpulite/bmvpuapi/bmvideo/bmvppapi** 等库，可以直接去掉，这些库其实并没有暴露接口给用户，它们是供底层调用的。

和BM1684/BM1684X有一点不同的是，目前sophon_media中提供的库还依赖libisp模块，如果您使用BM1688/CV186AH的GeminiSDK1.3以上版本，您还需要做这些操作：

从sdk中获取sophon-img/bsp-debs/目录下的sophon-soc-libisp_${x.y.z}_arm64.deb，然后运行如下命令：

```bash
dpkg -x sophon-soc-libisp_${x.y.z}_arm64.deb sophon-libisp
cp -rf sophon-libisp/opt/sophon/sophon-soc-libisp_${x.y.z}/lib ${soc-sdk} #将libisp的库添加到已有的依赖库中。
```

如果您使用Python编程，那只需要重新编译sophon-sail的.whl安装包，编译流程与之前相同，参考sophon-sail开发指南即可。BM1688 SoC上自带libsophon和sophon_media的runtime。

## SDK版本≥1.7 兼容性适配

BM1688/CV186AH SOPHONSDK 1.7及以上版本，对兼容性问题做了进一步的优化，只需要保证您的代码引入了以下头文件即可。

```cpp
#include <bmcv_api.h>
```

## SDK版本<1.7 兼容性适配

BM1688/CV186AH SOPHONSDK1.7以下版本提供的接口相比BM1684/BM1684X SDK有一些变化，下面将分模块分别进行说明，并给出一套应用层代码兼容两套SDK的兼容性解决办法：

### 头文件改动

1. bmcv_api.h已废弃，兼容性解决办法如下：

```cpp
#if !(BMCV_VERSION_MAJOR > 1)
#include <bmcv_api.h>
#endif
```

### bmcv改动

1. 函数参数变为指针：

```cpp
DECL_EXPORT bm_status_t bm_image_destroy(bm_image image)
```

变为

```cpp
DECL_EXPORT bm_status_t bm_image_destroy(bm_image *image)
```

兼容性解决办法如下：

在公共头文件中添加如下代码：

```cpp
#if BMCV_VERSION_MAJOR > 1
    static inline bm_status_t bm_image_destroy(bm_image& image){
    return bm_image_destroy(&image);
    }
#endif
```

2. 函数名称变化：

```cpp
bm_image_dev_mem_alloc
```

变为

```cpp
bm_image_alloc_dev_mem
```

兼容性解决办法：

在公共头文件中封装一个相同功能的旧接口。

3. 接口名称修正：

```cpp
bm_image_dettach_contiguous_mem
```

修正为

```cpp
bm_image_detach_contiguous_mem
```

兼容性解决办法：

在公共头文件中封装一个相同功能的旧接口。

4. 结构体名称修正

```cpp
bmcv_padding_atrr_t
```

修正为

```cpp
bmcv_padding_attr_t
```

兼容性解决办法：

在公共头文件中添加 `typedef bmcv_padding_attr_t bmcv_padding_atrr_t;`。

5. 接口废弃：

```cpp
bmcv_image_crop
```

兼容性解决办法：

1. 使用bmcv_image_vpp_convert来代替。
2. 或者在公共头文件使用bmcv_image_vpp_convert封装一个bmcv_image_crop接口。

6. 数据类型废弃：

```cpp
DATA_TYPE_EXT_4N_BYTE_SIGNED
DATA_TYPE_EXT_4N_BYTE
```

兼容性解决办法：

4N数据类型在以前的SDK中也很少使用，不建议再使用4N数据类型，改用1N数据类型。

7. 内存布局改动导致的接口功能改动：

```cpp
bm_image_alloc_dev_mem(heap_id = 2)
bm_image_alloc_dev_mem_heap_mask(heap_mask = 1 << 2)
bm_image_alloc_contiguous_mem_heap_mask(heap_mask = 1 << 2)
```

BM1688/CV186AH上只有两个heap，原来放在heap2的内存需要挪到heap1，否则分配失败。如上接口的heap_id/heap_mask参数需要改为：

```cpp
bm_image_alloc_dev_mem(heap_id = 1)
bm_image_alloc_dev_mem_heap_mask(heap_mask = 1 << 1)
bm_image_alloc_contiguous_mem_heap_mask(heap_mask = 1 << 1)
```

8. 暂未支持的接口：

```cpp
bmcv_base64_enc()
bmcv_base64_dec()
bmcv_faiss_indexflatIP()
bmcv_nms()
bmcv_nms_ext()
bmcv_fft_1d_create_plan()
bmcv_fft_2d_create_plan()
bmcv_fft_execute()
bmcv_fft_execute_real_input()
bmcv_fft_destroy_plan()
```

### ffmpeg改动

ffmpeg版本从4.1升级到了6.0，由此引入了一些ffmpeg本身的改动，如下：

1. 接口废弃：

```cpp
av_register_all
```

兼容性解决办法：

1. 去掉
2. 或者封装一个av_register_all。

```cpp
avcodec_decode_video2
avcodec_encode_video2
```

兼容性解决办法：

1. 按照ffmpeg文档，改成avcodec_send_packet和avcodec_receive_frame的形式。
2. 可以自己封装一个avcodec_decode_video2，参考https://github.com/sophgo/sophon-demo/blob/release/include/ff_decode.hpp
3. 可以自己封装一个avcodec_encode_video2，参考sophon-sail src/internal.h

2. 结构体或函数类型变为const：

```cpp
struct AVOutputFormat *oformat;
AVInputFormat* av_find_input_format
AVCodec* avcodec_find_decoder
AVOutputFormat* av_guess_format
AVCodec* avcodec_find_decoder_by_name
AVCodec* avcodec_find_decoder_by_name
```

变为

```cpp
const struct AVOutputFormat *oformat
const AVInputFormat* av_find_input_format
const AVCodec* avcodec_find_decoder
const AVOutputFormat* av_guess_format
const AVCodec* avcodec_find_decoder_by_name
const AVCodec* avcodec_find_decoder_by_name
```

兼容性解决办法：

使用const_cast去掉const修饰符。

3. 结构体成员变量变化：

```cpp
AVStream->codec
```

变为

```cpp
AVStream->codecpar
```

兼容性解决办法：

avcodec_parameters_to_context重新获取上下文，avcodec_parameters_from_context把上下文内容重新拷贝到流中。

### bmlib改动

1. 新增接口：

```cpp
DECL_EXPORT bm_status_t bm_thread_sync_from_core(bm_handle_t handle, int core_id);
```

功能描述：

可以指定只sync某个核，在每个核各跑一个模型时会用到。

2. 内存布局改动导致的接口功能改动：

```cpp
bm_malloc_device_byte_heap(heap_id = 2)
bm_malloc_device_byte_heap_mask(heap_mask = 1 << 2)
```

BM1688/CV186AH上只有两个heap，原来放在heap2的内存需要挪到heap1，否则分配失败。如上接口的heap_id/heap_mask参数需要改为：

```cpp
bm_malloc_device_byte_heap(heap_id = 1)
bm_malloc_device_byte_heap_mask(heap_mask = 1 << 1)
```

### bmrt改动

1. 新增接口：

```cpp
DECL_EXPORT bool bmrt_launch_tensor_multi_cores(void *p_bmrt,
                                                const char *net_name,
                                                const bm_tensor_t input_tensors[],
                                                int input_num,
                                                bm_tensor_t output_tensors[],
                                                int output_num,
                                                bool user_mem,
                                                bool user_stmode,
                                                const int *core_list,
                                                int core_num);
```

功能描述：

该接口可以将单核模型指定在不同的核上运行，具体请查看SOPHONSDK的bmruntime接口文档或源码。

## 准备BM1688/CV186AH运行环境

BM1688/CV186AH的刷机步骤和BM1684/BM1684X相同，具体可以看相关的产品使用手册，在SDK中，sophon-img/sdcard.tgz文件就是刷机包。

准备好运行环境之后，就可以将编译好的程序拷贝到BM1688/CV186AH SoC上执行了。

## 其他注意事项

1. bmrt、bmcv相关的操作，最好把各自分配的内存隔离开，bmrt需要用到的内存放在heap0（也就是npu heap），bmcv需要用到的内存则放在heap1（也就是vpp heap）。

2. 由于BM1688的内存减小，ddr是全interleave的，没有带宽分配问题，因此不再预留vpu heap，多媒体模块共用vpp heap。

3. bm1688的sdk目前只把ddr划分成npu、vpp两个heap，查看方法改为：

```bash
sudo cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
sudo cat /sys/kernel/debug/ion/cvi_npu_heap_dump/summary
```

4. 内存布局修改工具：https://doc.sophgo.com/sdk-docs/v23.09.01-lts/docs_latest_release/docs/SophonSDK_doc/zh/html/appendix/2_mem_edit_tools.html

可以兼容BM1688/CV186AH Gemini v1.5以上SDK，vpu heap需要设置为0。

## FLOAT 模型生成

**算丰系列智能视觉深度学习处理器平台仅支持BModel模型加速, 用户需要首先进行模型迁移, 把其他框架下训练好的模型转换为BModel才能在算丰系列智能视觉深度学习处理器上运行。**

**TPU-MLIR工具包**

# 模型转换与部署指南

本文以 `yolov5s.onnx` 为例，介绍TPU-MLIR如何转换模型为FP32格式的BModel并部署。MLIR环境的配置，可以参考《TPU-MLIR开发环境配置》，**其他模型迁移请参考doc目录下的《TPU-MLIR快速入门指南》**。

yolov5的模型来自 [yolov5的官网](https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx)，可点击本链接进行下载。

## 加载tpu-mlir

参考《TPU-MLIR开发环境配置》，进入x86主机的Docker环境，并通过pip命令安装tpu-mlir。

## 准备工作目录

建立 `model_yolov5s` 目录，建议与tpu-mlir同级目录；并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

操作如下：

```shell
$ mkdir model_yolov5s && cd model_yolov5s
$ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
$ cp -rf $TPUC_ROOT/regression/dataset/COCO2017 .
$ cp -rf $TPUC_ROOT/regression/image .
$ mkdir workspace && cd workspace
```

这里的 `$TPUC_ROOT` 是环境变量，对应tpu-mlir_xxxx目录。

## ONNX转MLIR

如果模型是图片输入，在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入，则不需要考虑预处理。
预处理过程用公式表达如下（x 代表输入）：

```
y = (x - mean) × scale
```

官网yolov5的图片是rgb，每个值会乘以 `1/255`，转换成mean和scale对应为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216`。

模型转换命令如下：

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

`model_transform.py` 主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_name | 是 | 指定模型名称 |
| model_def | 是 | 指定模型定义文件，比如`.onnx`或`.tflite`或`.prototxt`文件 |
| input_shapes | 否 | 指定输入的shape，例如[[1,3,640,640]]；二维数组，可以支持多输入情况 |
| input_types | 否 | 指定输入的类型，例如int32；多输入用,隔开；不指定情况下默认处理为float32 |
| resize_dims | 否 | 原始图片需要resize之后的尺寸；如果不指定，则resize成模型的输入尺寸 |
| keep_aspect_ratio | 否 | 在Resize时是否保持长宽比，默认为false；设置时会对不足部分补0 |
| mean | 否 | 图像每个通道的均值，默认为0.0,0.0,0.0 |
| scale | 否 | 图片每个通道的比值，默认为1.0,1.0,1.0 |
| pixel_format | 否 | 图片类型，可以是rgb、bgr、gray、rgbd四种情况，默认为bgr |
| channel_format | 否 | 通道类型，对于图片输入可以是nhwc或nchw，非图片输入则为none，默认为nchw |
| output_names | 否 | 指定输出的名称，如果不指定，则用模型的输出；指定后用该指定名称做输出 |
| test_input | 否 | 指定输入文件用于验证，可以是图片或npy或npz；可以不指定，则不会正确性验证 |
| test_result | 否 | 指定验证后的输出文件 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| mlir | 是 | 指定输出的mlir文件名称和路径 |

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是模型的输入文件。

将mlir文件转换成f32的bmodel，操作方法如下：

```shell
#bm1688 
$ model_deploy.py \
     --mlir yolov5s.mlir \
     --quantize F32 \
     --processor bm1688 \
     --test_input yolov5s_in_f32.npz \
     --test_reference yolov5s_top_outputs.npz \
     --tolerance 0.99,0.99 \
     --num_core 2 \
     --model yolov5s_1688_f32_2core.bmodel

#cv186ah 
$ model_deploy.py \
     --mlir yolov5s.mlir \
     --quantize F32 \
     --processor cv186x \
     --test_input yolov5s_in_f32.npz \
     --test_reference yolov5s_top_outputs.npz \
     --tolerance 0.99,0.99 \
     --model yolov5s_cv186x_f32.bmodel
```

`model_deploy.py` 的主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定mlir文件 |
| quantize | 是 | 指定默认量化类型，支持F32/F16/BF16/INT8 |
| processor | 是 | 指定模型将要用到的平台，支持bm1684x/bm1684/bm1688/cv183x/cv182x/cv181x/cv180x/cv186x |
| calibration_table | 否 | 指定校准表路径，当存在INT8量化的时候需要校准表 |
| tolerance | 否 | 表示 MLIR 量化后的结果与 MLIR fp32推理结果相似度的误差容忍度 |
| test_input | 否 | 指定输入文件用于验证，可以是图片或npy或npz；可以不指定，则不会正确性验证 |
| test_reference | 否 | 用于验证模型正确性的参考数据（使用npz格式）。其为各算子的计算结果 |
| compare_all | 否 | 验证正确性时是否比较所有中间结果，默认不比较中间结果 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| num_core | 否 | 仅支持BM1688，选择并行计算的核心数量，默认设置为 1 个计算核心 |
| model | 是 | 指定输出的model文件名称和路径 |

仅BM1688 支持 `num_core` 选项，用于指定生成适用于BM1688双核高性能模型。

编译完成后，会生成名为 `yolov5s_1688_f32_2core.bmodel` 或者 `yolov5s_cv186x_f32.bmodel` 的文件。

如果想要生成float16的模型，则 **仅需要在model_deploy.py的时候指定quantize为F16**，其余步骤相同。

# INT8模型生成

相比于迁移float模型，如果要转INT8模型，则需要调用 `run_calibration.py` 生成校准表，然后传给 `model_deploy.py`。

具体更多细节请参考doc目录下的《TPU-MLIR快速入门指南》

本文以 `yolov5s.onnx` 为例，介绍TPU-MLIR如何转换模型为INT8格式的BModel并部署。开发环境的配置，可以参考《TPU-MLIR开发环境配置》，**其他模型迁移请参考doc目录下的《TPU-MLIR快速入门指南》**。

yolov5的模型来自 [yolov5的官网](https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx)，可点击本链接进行下载。

## 加载tpu-mlir

参考《TPU-MLIR开发环境配置》，进入x86主机的Docker环境，并通过pip命令安装tpu-mlir。

## 准备工作目录

建立 `model_yolov5s` 目录，建议与tpu-mlir同级目录；并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

```shell
$ mkdir model_yolov5s && cd model_yolov5s
$ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
$ cp -rf $TPUC_ROOT/regression/dataset/COCO2017 .
$ cp -rf $TPUC_ROOT/regression/image .
$ mkdir workspace && cd workspace
```

这里的 `$TPUC_ROOT` 是环境变量，对应tpu-mlir_xxxx目录。

## ONNX转MLIR

如果模型是图片输入，在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入，则不需要考虑预处理。
预处理过程用公式表达如下（x 代表输入）：

```
y = (x - mean) × scale
```

官网yolov5的图片是rgb，每个值会乘以 `1/255`，转换成mean和scale对应为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216`。

模型转换命令如下：

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

model_transform.py的相关参数已在上一小节说过，这里不再赘述。

**对于INT8模型的量化与迁移，需要确保前处理参数准确无误，否则生成的INT8可能会有严重的精度损失**。

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是模型的输入文件。

## MLIR转INT8模型

### 生成校准表

转INT8模型前需要跑calibration，得到校准表；输入数据的数量根据情况准备100~1000张左右，需要 **保证量化数据集与测试数据集的数据分布保持一致**。

然后用校准表，生成对称或非对称bmodel模型。如果对称量化精度符合需求，**一般不建议用非对称量化**，因为非对称量化的bmodel模型性能会略差于对称bmodel模型。

这里用现有的100张来自COCO2017的图片举例，执行calibration：

```shell
$ run_calibration.py yolov5s.mlir \
    --dataset ../COCO2017 \
    --input_num 100 \
    -o yolov5s_cali_table
```

运行完成后会生成名为 `yolov5s_cali_table` 的文件，该文件用于后续编译INT8模型的量化表文件。

### 编译为INT8对称量化模型

转成INT8对称量化模型，执行如下命令：

```shell
# bm1688
$ model_deploy.py \
    --mlir yolov5s.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor bm1688 \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --num_core 2 \
    --model yolov5s_1688_int8_sym_2core.bmodel

# cv186ah
$ model_deploy.py \
   --mlir yolov5s.mlir \
   --quantize INT8 \
   --calibration_table yolov5s_cali_table \
   --processor cv186x \
   --test_input yolov5s_in_f32.npz \
   --test_reference yolov5s_top_outputs.npz \
   --tolerance 0.85,0.45 \
   --model yolov5s_cv186ah_int8_sym.bmodel
```

编译完成后，会生成名为 `yolov5s_1688_int8_sym_2core.bmodel` 或者 `yolov5s_cv186ah_int8_sym.bmodel` 的文件。

# 模型效果演示

## 模型效果测试

MLIR发布包中有用python写好的yolov5用例，源码路径 `$TPUC_ROOT/python/samples/detect_yolov5.py`，下面将使用示例代码分别来验证onnx/f16/int8的执行结果。

onnx模型的执行方式如下，得到 `dog_onnx.jpg`：

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model ../yolov5s.onnx \
    --output dog_onnx.jpg
```

对于bmodel模型文件，由于开发环境没有相关设备，因此将会使用x86的主机cpu模拟运行bmodel模型，仅用于准确性验证。

f16 bmodel的执行方式如下，得到 `dog_f16.jpg`：

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model yolov5s_1688_f16.bmodel \
    --output dog_f16.jpg
```

int8对称bmodel的执行方式如下，得到 `dog_int8_sym.jpg`：

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model yolov5s_1688_int8_sym_2core.bmodel \
    --output dog_int8_sym.jpg
```

由于运行环境不同，最终的效果和精度会有些差异。

## 模型性能测试

以下操作需要在边缘服务器内执行，默认的出厂环境或者刷机完成后，可以使用 `bmrt_test` 来测试编译出的 `bmodel` 的正确性及性能。

**可以根据 `bmrt_test` 输出的性能结果，来估算模型最大的fps，来选择合适的模型**。

```shell
# 下面测试上面编译出的bmodel
# --bmodel参数后面接bmodel文件，

$ cd $TPUC_ROOT/../model_yolov5s/workspace
# BM1688
$ bmrt_test --bmodel yolov5s_1688_f16.bmodel
$ bmrt_test --bmodel yolov5s_1688_int8_sym_2core.bmodel
```

以最后一个命令输出为例（此处对日志做了部分截断处理）：

```shell
[BMRT][load_bmodel:1501] INFO:pre net num: 0, load net num: 1
[BMRT][show_net_info:1810] INFO: ########################
[BMRT][show_net_info:1814] INFO: NetName: yolov5s_v6.1_3output, Index=0
[BMRT][show_net_info:1817] INFO: ---- stage 0 ----
[BMRT][show_net_info:1827] INFO:   Input 0) 'images' shape=[ 1 3 640 640 ] dtype=FLOAT32 scale=1 zero_point=0 device_id=0
[BMRT][show_net_info:1838] INFO:   Output 0) 'output_Transpose_f32' shape=[ 1 3 80 80 85 ] dtype=FLOAT32 scale=1 zero_point=0 device_id=0
[BMRT][show_net_info:1838] INFO:   Output 1) '365_Transpose_f32' shape=[ 1 3 40 40 85 ] dtype=FLOAT32 scale=1 zero_point=0 device_id=0
[BMRT][show_net_info:1838] INFO:   Output 2) '385_Transpose_f32' shape=[ 1 3 20 20 85 ] dtype=FLOAT32 scale=1 zero_point=0 device_id=0
[BMRT][show_net_info:1841] INFO: ########################
[BMRT][bmrt_test:844] INFO:==> running network #0, name: yolov5s_v6.1_3output, loop: 0
[BMRT][bmrt_test:899] INFO:reading input #0, bytesize=4915200
[BMRT][print_array:755] INFO:  --> input_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ... > len=1228800
[BMRT][bmrt_test:1030] INFO:reading output #0, bytesize=6528000
[BMRT][print_array:755] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ... > len=1632000
[BMRT][bmrt_test:1030] INFO:reading output #1, bytesize=1632000
[BMRT][print_array:755] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ... > len=408000
[BMRT][bmrt_test:1030] INFO:reading output #2, bytesize=408000
[BMRT][print_array:755] INFO:  --> output ref_data: < 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ... > len=102000
[BMRT][bmrt_test:1065] INFO:net[yolov5s_v6.1_3output] stage[0], launch total time is 7083 us (npu 6387 us [6387 us, 2391 us], cpu 696 us), (issue 3000 us, sync 4136 us)
[BMRT][bmrt_test:1068] INFO:+++ The network[yolov5s_v6.1_3output] stage[0] output_data +++
[BMRT][print_array:755] INFO:output data #0 shape: [1 3 80 80 85 ] < -0.145839  ...
[BMRT][print_array:755] INFO:output data #1 shape: [1 3 40 40 85 ] < -0.726845  ...
[BMRT][print_array:755] INFO:output data #2 shape: [1 3 20 20 85 ] < 0.563809  ...
[BMRT][bmrt_test:1129] INFO:load input time(s): 0.018420
[BMRT][bmrt_test:1130] INFO:calculate  time(s): 0.007136
[BMRT][bmrt_test:1131] INFO:get output time(s): 0.020361
[BMRT][bmrt_test:1132] INFO:compare    time(s): 0.021095
```

# 重要概念

## 工作模式

SOPHON BM168X系列产品涵盖了从末端到边缘到中枢的多种产品形态，可以支持两种不同的工作模式，分别对应不同的产品形态，具体信息如下：

|            | SoC模式                                    | PCIe模式                                     |
|------------|--------------------------------------------|----------------------------------------------|
| 运行模式   | 独立主机，微服务器形态                     | 附属硬件，PCIe加速卡形态                     |
| 对外IO方式 | 千兆以太网                                 | PCIe接口                                     |
| 对应产品   | 微服务器/模组                              | PCIe加速卡                                   |

**目前，BM1688/CV186AH系列相关产品仅支持SoC模式**

## 硬件内存

内存是BM168X应用调试中经常会涉及的重要概念，特别地，有以下3个概念需要特别区分清楚：Global Memory、Host Memory、Device Memory。

对于BM1688/CV186AH的SoC工作模式，三种内存的解释如下

- **全局内存（Global Memory）**： 指处理器的片外存储DDR

- **设备内存（Device Memory）** ：划分给Tensor Computing Processor/VPSS的内存

- **系统内存（Host Memory）** ：划分给主控Cortex A53的内存

三者关系可以简单的理解为 **全局内存 = 设备内存 + 系统内存**。

内存同步问题是后续应用调试中经常会遇到的比较隐蔽的重要问题。我们在sophon-opencv和sophon-ffmpeg两个框架内都提供了内存同步操作的函数；而BMCV API只面向设备内存操作，因此不存在内存同步的问题，在调用BMCV API前，需要将输入数据在设备内存上准备好。

我们在BMLib中提供了接口，可以实现Host Memory和Global Memory之间、Global Memory内部以及不同设备的Global Memory之间的数据搬运。

更多详细信息请参考《 BMLib开发参考手册 》和《 多媒体开发参考手册 》。

## BModel

**BModel：** 是一种面向算能智能视觉深度学习处理器的 **神经网络模型文件格式**，其中包含目标网络的权重（weight）、指令流等等。

**Stage：** 支持将同一个网络的不同batch size的模型combine为一个BModel；同一个网络的不同batch size的输入对应着不同的stage，推理时BMRuntime会根据输入shape的大小自动选择相应stage的模型。也支持将不同的网络combine为一个BModel，通过网络名称来获取不同的网络。

**动态编译和静态编译：** 支持模型的动态编译和静态编译，可在转换模型时通过参数设定。动态编译的BModel，在Runtime时支持任意小于编译时设置的shape的输入shape；静态编译的BModel，在Runtime时只支持编译时所设置的shape。

**优先使用静态编译的模型：**
动态编译模型运行时需要BM168X内微控制器ARM9的参与，实时地根据实际输入shape，动态生成智能视觉深度学习处理器运行指令。因此，动态编译的模型执行效率要比静态编译的模型低。若可以，应当优先使用静态编译的模型或支持多种输入shape的静态编译模型。

## bm_image

```c++
typedef enum bm_image_format_ext_{
    FORMAT_YUV420P,
    FORMAT_YUV422P,
    FORMAT_YUV444P,
    FORMAT_NV12,
    FORMAT_NV21,
    FORMAT_NV16,
    FORMAT_NV61,
    FORMAT_RGB_PLANAR,
    FORMAT_BGR_PLANAR,
    FORMAT_RGB_PACKED,
    FORMAT_BGR_PACKED,
    PORMAT_RGBP_SEPARATE,
    PORMAT_BGRP_SEPARATE,
    FORMAT_GRAY,
    FORMAT_COMPRESSED
} bm_image_format_ext;

typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_4N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
}bm_image_data_format_ext;

// bm_image结构体定义如下
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    bm_image_private* image_private;
};
```

BMCV API均是围绕 bm_image 来进行的，一个 bm_image 对象对应于一张图片。

**用户通过 bm_image_create 构建 bm_image 对象，attach到device memory；使用完需要调用 bm_image_destroy 销毁；手动attach到device memory的还需要手动释放。**

不同BMCV API支持的image_format和data_type不同，注意格式要求，必要时需要进行格式转换。

更多详细信息请参考《算能边缘产品BMCV开发参考指南》。

另外，SAIL库中将bm_image封装为BMImage，相关信息请参考doc目录下的《sophon-sail_zh》。

# 快速跑通一个样例

我们提供了模型转换及量化样例程序、多媒体相关样例程序、以及涵盖图像分类、目标检测、图像分割、文本检测识别等领域的单个模型算法移植样例程序，具体如下：

1. BM1688/CV186AH SOPHONSDK中 doc文件夹下的《 TPU-MLIR快速入门手册》提供了模型转换与量化样例；

2. BM1688/CV186AH SOPHONSDK中 sophon-demo 提供了 CenterNet、LPRNet、PP-OCR、ResNet、RetinaFace、YOLOv3/v4、YOLOv5、YOLOv8 等单个模型的推理样例程序；

3. BM1688/CV186AH SOPHONSDK中 sophon-stream 提供了多线程任务构建的样例程序，只需要编写配置文件就可以完成流水线的搭建；

4. BM1688/CV186AH SOPHONSDK中 sophon-media 提供不同硬件架构下关于视频及图片编解码、bmcv格式转换的多媒体相关样例程序，具体可以参考doc文件夹下的多媒体参考手册

下面以YOLOv5算法为例，介绍如何快速跑通一个样例；

（1） **将sophon-sail、sophon-demo压缩包复制到SOPHON边缘服务器并解压**

（2） **进入sophon-sail文件夹，安装sophon-sail的python库,whl包位于python_wheels/soc_BM1688目录下，选择对应的版本进行安装**

```bash
pip3 install ./sophon_arm-3.7.0-py3-none-any.whl --force-reinstall
```

（3） **进入sophon-demo文件夹，下载官方模型以及数据集**

```bash
cd ./sample/YOLOv5/scripts
chmod +x /download.sh
./download.sh
```

（4） **执行yolov5的python检测代码**

```bash
cd ../python
# BM1688
python3 yolov5_bmcv.py --bmodel ../models/BM1688/yolov5s_v6.1_3output_int8_1b_2core.bmodel --conf_thresh 0.45

# CV186AH
python3 yolov5_bmcv.py --bmodel ../models/CV186X/yolov5s_v6.1_3output_int8_1b.bmodel --conf_thresh 0.45
```

测试结束后，会将预测的图片、json文件保存在results目录下，同时会打印预测结果、推理时间等信息。

模型性能、精度、C++程序编译等更多信息请参考YOLOv5/readme、YOLOv5/cpp/readme、YOLOv5/python/readme等文件。

# SDK 简介

"BM1688/CV186AH SOPHONSDK" 是算能科技基于BM1688/CV186AH定制的深度学习SDK，涵盖了神经网络推理阶段所需的模型优化、高效运行支持等能力，为深度学习应用开发和部署提供易用、高效的全栈式解决方案。

## BM1688/CV186AH SOPHONSDK 文件清单

解压后的SDK文件结构如下：

```bash
BM1688/CV186AH SOPHONSDK
├── doc
│   ├── BMLib_Technical_Reference_Manual.pdf
│   ├── BMLIB开发参考手册.pdf
│   ├── LIBSOPHON_User_Guide.pdf
│   ├── LIBSOPHON使用手册.pdf
│   ├── SOPHON BMRuntime Technical Reference Manual.pdf
│   ├── SOPHON-SAIL_en.pdf
│   ├── SOPHON-SAIL_zh.pdf
│   ├── TPU-MLIR_Quick_Start.pdf
│   ├── TPU-MLIR_Technical_Reference_Manual.pdf
│   ├── TPU-MLIR开发参考手册.pdf
│   ├── TPU-MLIR快速入门指南.pdf
│   ├── 算能边缘产品BMCV开发参考手册.pdf
│   ├── 算能边缘产品BMRUNTIME开发参考手册.pdf
│   ├── 算能边缘产品BSP开发参考手册_en.pdf
│   ├── 算能边缘产品BSP开发参考手册.pdf
│   ├── 算能边缘产品MULTIMEDIA常见问题手册.pdf
│   ├── 算能边缘产品MULTIMEDIA开发参考手册.pdf
│   └── 算能边缘产品多媒体使用参考指南.pdf
├── isp_tool
│   └── CviPQtool_20240403.zip
├── sophon-demo                                   
│   ├── release_version.txt
│   ├── sophon-demo.MD5
│   └── sophon-demo_v0.1.10_6375a8be_20240403.tar.gz
├── sophon-img
│   ├── boot
│   │   ├── boot.itb
│   │   ├── boot.scr.emmc
│   │   ├── fip.bin
│   │   ├── fip_debug.bin
│   │   └── multi.its
│   ├── bsp-debs
│   │   ├── bmssm_soc_1.2.0_SDK.deb
│   │   ├── linux-headers-5.10.4-tag--00082-g91a1fb25c7fb.deb
│   │   ├── linux-image-5.10.4-tag--00082-g91a1fb25c7fb-dbg.deb
│   │   ├── linux-image-5.10.4-tag--00082-g91a1fb25c7fb.deb
│   │   ├── linux-libc-dev_5.10.4-tag--00082-g91a1fb25c7fb-1_arm64.deb
│   │   ├── qt5-base.deb
│   │   ├── sophgo-bsp-rootfs_1.1.0_arm64.deb
│   │   ├── sophgo-hdmi_1.0.0_arm64.deb
│   │   ├── sophliteos_soc_1.1.2_sdk.deb
│   │   ├── sophon-media-soc-sophon-ffmpeg_1.5.0_arm64.deb
│   │   ├── sophon-media-soc-sophon-opencv_1.5.0_arm64.deb
│   │   ├── sophon-media-soc-sophon-sample_1.5.0_arm64.deb
│   │   ├── sophon-soc-libisp_1.0.0_arm64.deb
│   │   ├── sophon-soc-libisp-dev_1.0.0_arm64.deb
│   │   ├── sophon-soc-libsophon_0.4.9_arm64.deb
```

# 资料简介

BM1688/CV186AH SOPHONSDK是一个一站式SDK，其中包含了模型转换、模型量化、算法移植等相关模块，我们提供了包括文档、视频、论坛、开源仓库等一系列资料帮助用户进行算法移植和开发工作。

**请先阅读开发指南，其中包括：基本概念及SDK简介；资料简介、文档说明；SDK的获取、安装、配置及更新；快速入门例子、模型转换及模型量化、示例代码的讲解等内容**

当您在某个环节遇到问题时，可以在SOPHONSDK目录的doc文件夹下,查找对应问题的参考指南：

```
doc 
 ├── BMLib_Technical_Reference_Manual.pdf
 ├── BMLIB开发参考手册.pdf
 ├── LIBSOPHON_User_Guide.pdf
 ├── LIBSOPHON使用手册.pdf
 ├── SOPHON BMRuntime Technical Reference Manual.pdf
 ├── SOPHON-SAIL_en.pdf
 ├── SOPHON-SAIL_zh.pdf
 ├── TPU-MLIR_Quick_Start.pdf
 ├── TPU-MLIR_Technical_Reference_Manual.pdf
 ├── TPU-MLIR开发参考手册.pdf
 ├── TPU-MLIR快速入门指南.pdf
 ├── 算能边缘产品BMCV开发参考手册.pdf
 ├── 算能边缘产品BMRUNTIME开发参考手册.pdf
 ├── 算能边缘产品BSP开发参考手册_en.pdf
 ├── 算能边缘产品BSP开发参考手册.pdf
 ├── 算能边缘产品MULTIMEDIA常见问题手册.pdf
 ├── 算能边缘产品MULTIMEDIA开发参考手册.pdf
 └── 算能边缘产品多媒体使用参考指南.pdf
```

上述参考指南的相关说明如下所示

- **BMLIB开发参考手册**
  - BMLIB 是在内核驱动之上封装的一层底层软件库，负责设备Handle的管理、内存管理、数据搬运、API的发送和同步、A53使能、设置智能视觉深度学习处理器工作频率等

- **LIBSOPHON使用手册**
  - LIBSOPHON包含BMCV、BMRuntime、BMLib等库，用来驱动VPP、智能视觉深度学习处理器等硬件，完成图像处理、张量运算、模型推理等操作。

- **算能边缘产品BMRUNTIME开发参考手册**
  - BMRuntime 提供了丰富的接口，驱动BModel在 SOPHON 智能视觉深度学习处理器中执行

- **sophon-sail_zh**
  - sail开发参考手册，包含编译，C++接口调用，python接口调用方法等

- **TPU-MLIR快速入门指南**
  - 基于TPU-MLIR工具的模型迁移方法以及使用示例

- **TPU-MLIR开发参考手册**
  - Tensor Processing Unit编译器工程

- **算能边缘产品BMCV开发参考指南**
  - 算能硬件图像处理加速库开发参考手册，包含常见图像处理接口函数

- **算能边缘产品BSP开发参考手册**
  - BM168X系列深度学习处理器计算模组（含开发板）的详细手册

- **算能边缘产品MULTIMEDIA常见问题手册**
  - 多媒体方面的常见问题及解答

- **算能边缘产品MULTIMEDIA开发参考手册**
  - 驱动VPSS进行RTSP流、GB28181流的解析以及视频、图像编解码等多媒体相关

- **算能边缘产品多媒体使用参考指南**
  - 多媒体库安装以及编译指导手册

## 其他相关的开发参考资料

- **官网视频教程**：https://developer.sophgo.com/site/index/course/all/all.html，其中包括：智算卡、智算盒子、智算服务器等产品介绍视频；快速跑通PCIe模式的例程、快速跑通SoC模式的例程、SDK算法移植介绍、BMCV编程示例、编解码编程示例、BMLang编程示例、TPUKernel编程示例。

- **官网论坛**：https://developer.sophgo.com/forum/index/.html，欢迎在官网论坛向我们发起技术支持提问帖。

- **云开发平台（SOPHON NET）**：https://cloud.sophgo.com/developer/cloudSpace/index?lang=CN，提供在线的开发软硬件环境。

- **开源仓库：**
  (1) 针对单模型或场景的综合示例 sophon-demo：https://github.com/sophgo/sophon-demo
  (2) BSP：https://gitee.com/sophon-ai/bsp-sdk
  (3) sophon-ffmpeg：https://github.com/sophgo/sophon_ffmpeg
  (4) sophon-stream：https://github.com/sophgo/sophon-stream

欢迎各位通过github issues向我们反馈您在使用过程中遇到的问题，并向我们提交PR共同参与开源仓库的建设。

# 安装SDK

**SOPHON BM1688/CV186AH 目前支持SoC工作模式**，以下为SoC模式与PCIe模式之间的区别

|            | SoC模式                                    | PCIe模式                                     |
|------------|--------------------------------------------|----------------------------------------------|
| 运行模式   | 独立主机，微服务器形态                     | 附属硬件，PCIe加速卡形态                     |
| 对外IO方式 | 千兆以太网                                 | PCIe接口                                     |
| 对应产品   | 微服务器/模组                              | PCIe加速卡                                   |

对于BM1688/CV186AH的用户，推荐将开发环境与运行环境分离，其中开发环境是指用于模型转换或验证以及程序编译等开发过程的环境；运行环境是指在具备SOPHON设备的平台上实际使用设备进行算法应用部署的运行环境。

因此，您需要 **准备一台x86主机** 作为开发环境，用于模型的编译量化以及程序的交叉编译。目前，已在主流的Linux系统适配验证，推荐使用Ubuntu20.04的x86主机，运行内存建议12GB以上。

## 环境配置-Linux开发环境

我们提供了tpu-mlir的docker环境供用户在x86主机上进行模型的编译量化, 用户可以在x86主机上基于tpu-mlir和libsophon完成模型的编译量化与程序的交叉编译，部署时将编译好的程序拷贝至SoC平台（SE微服务器/SM模组）中执行。

### tpu-mlir 环境初始化

#### 1. Docker 安装

若已安装docker，请跳过本节。
执行以下脚本安装 docker 并将当前用户加入 docker 组，获得 docker 执行权限。

```bash
# 安装docker
sudo apt-get install docker.io
sudo systemctl start docker
sudo systemctl enable docker
# docker命令免root权限执行
# 创建docker用户组，若已有docker组会报错，可忽略
sudo groupadd docker
# 将当前用户加入docker组
sudo usermod -aG docker $USER
# 重启docker服务
sudo service docker restart
# 切换当前会话到新group或重新登录重启会话
newgrp docker
```

#### 2. 环境初始化

目前支持 **pip命令** 安装tpu-mlir库，并提供docker模型移植环境

注意，这里请使用 `pip` 命令安装，而不是 `pip3` 命令，否则可能会安装错误

(1) 创建docker容器并进入docker

```bash
docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:v3.2
```

(2) 安装tpu_mlir

```bash
pip install tpu_mlir
```

(3) 安装tpu_mlir依赖

```bash
# 安装onnx依赖
pip install tpu_mlir[onnx]
# 安装torch依赖
pip install tpu_mlir[torch]

# 同时安装onnx, torch, caffe依赖
pip install tpu_mlir[onnx,torch,caffe]
# 安装全部依赖
pip install tpu_mlir[all]
```

目前支持6种配置:onnx, torch, tensorflow, caffe, paddle, all。

如果您想要离线安装，可以从https://github.com/sophgo/tpu-mlir/releases/ 下载最新release包

### 交叉编译环境搭建

如果您希望使用SOPHONSDK搭建交叉编译环境，您需要用到gcc-aarch64-linux-gnu工具链，再将程序所依赖的头文件和库文件打包到soc-sdk目录中。

#### 1. 首先安装工具链：

```bash
sudo apt-get install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

您可以执行以下命令，验证开发环境中的交叉编译工具链是否配置成功：

```bash
which aarch64-linux-gnu-g++
# 终端输出内容
# /usr/bin/aarch64-linux-gnu-g++
```

如果终端输出了aarch64编译的路径，则说明交叉编译工具链正确，开发环境是可以正常使用的。

#### 2. 解压sophon-img包里的libsophon_soc\_<x.y.z>_aarch64.tar.gz，将lib和include的所有内容拷贝到soc-sdk文件夹。

```bash
cd sophon-img
# 创建依赖文件的根目录
mkdir -p soc-sdk
# 解压sophon-img release包里的libsophon_soc_${x.y.z}_aarch64.tar.gz，其中x.y.z为版本号
tar -zxf libsophon_soc_<x.y.z>_aarch64.tar.gz
# 将相关的库目录和头文件目录拷贝到依赖文件根目录下
cp -rf libsophon_soc_<x.y.z>_aarch64/opt/sophon/libsophon-<x.y.z>/lib ${soc-sdk}
cp -rf libsophon_soc_<x.y.z>_aarch64/opt/sophon/libsophon-<x.y.z>/include ${soc-sdk}
```

#### 3. 解压sophon-media包里的sophon-media-soc\_<x.y.z>_aarch64.tar.gz，将sophon-media下lib和include的所有内容拷贝到soc-sdk文件夹。

```bash
cd sophon-media_<date>_<hash>
# 解压sophon-media包里的sophon-media-soc_<x.y.z>_aarch64.tar.gz，其中x.y.z为版本号
tar -zxf sophon-media-soc_<x.y.z>_aarch64.tar.gz
# 将sophon-media目录下的库目录和头文件目录拷贝到依赖文件根目录下
cp -rf sophon-media-soc_<x.y.z>_aarch64/lib ${soc-sdk}
cp -rf sophon-media-soc_<x.y.z>_aarch64/include ${soc-sdk}
# 将ffmpeg和opencv的库目录和头文件目录拷贝到依赖文件根目录下
cp -rf sophon-media-soc_<x.y.z>_aarch64/opt/sophon/sophon-ffmpeg_<x.y.z>/lib ${soc-sdk}
cp -rf sophon-media-soc_<x.y.z>_aarch64/opt/sophon/sophon-ffmpeg_<x.y.z>/include ${soc-sdk}
cp -rf sophon-media-soc_<x.y.z>_aarch64/opt/sophon/sophon-opencv_<x.y.z>/lib ${soc-sdk}
cp -rf sophon-media-soc_<x.y.z>_aarch64/opt/sophon/sophon-opencv_<x.y.z>/include ${soc-sdk}
```

若您需要使用第三方库，可以使用qemu在x86上构建虚拟环境安装，再将头文件和库文件拷贝到soc-sdk目录中，具体可参考 [libsophon使用手册（构建qemu虚拟环境）](https://doc.sophgo.com/sdk-docs/v23.10.01/docs_latest_release/docs/libsophon/guide/html/2_develop.html?highlight=qemu#x86)。

若您需要使用SAIL模块，请参考doc目录下《sophon-sail_zh》中的安装说明。

## 环境配置-SoC

### 开发环境配置

对于SoC模式，**模型转换必须要在x86主机的docker开发容器中完成**；C/C++程序建议在x86主机上使用交叉编译工具链编译生成可执行文件后，再拷贝到SoC目标平台运行。

若您希望直接在SoC中进行C/C++程序的编译，则**需要先安装 sophon-soc-libsophon-dev\_<x.y.z>_arm64.deb 工具包**，使用以下命令安装：

```bash
sudo dpkg -i sophon-soc-libsophon-dev_<x.y.z>_arm64.deb
```

再安装sophon-media-soc-sophon-ffmpeg-dev\_<x.y.z>_arm64.deb、sophon-media-soc-sophon-opencv-dev\_<x.y.z>_arm64.deb 工具包，使用以下命令安装：

```bash
sudo dpkg -i sophon-media-soc-sophon-ffmpeg-dev_<x.y.z>_arm64.deb
sudo dpkg -i sophon-media-soc-sophon-opencv-dev_<x.y.z>_arm64.deb
```

**注意：**

1. 请先使用 `bm_version` 命令查看微服务器中的SDK版本与当前SDK版本是否一致，如果不一致，请参考下一小节对微服务器进行软件更新。
2. **SE微服务器自带的操作系统并没有桌面系统，您需要使用ssh登录到微服务器终端内进行操作开发。**

### 运行环境配置

对于SoC平台，内部已经集成了相应的libsophon、sophon-opencv和sophon-ffmpeg运行库包，位于/opt/sophon/下。如果您需要使用我们提供opencv-python，只需设置环境变量即可。

```bash
# 设置环境变量
export PYTHONPATH=$PYTHONPATH:/opt/sophon/sophon-opencv-latest/opencv-python
```

## 重要概念

### 名词解释

| 名词 | 说明 |
|------|------|
| BM1688/CV186AH | 算能面向深度学习领域推出的两款第五代张量处理器 |
| BM1684X | 算能面向深度学习领域推出的第四代张量处理器 |
| BM1684 | 算能面向深度学习领域推出的第三代张量处理器 |
| 智能视觉深度学习处理器 | BM1688/CV186AH,BM1684/BM1684X中的神经网络运算单元 |
| VPU | BM1688/CV186AH,BM1684/BM1684X中的编解码单元 |
| VPP | BM1684/BM1684X中的图形运算加速单元 |
| VPSS | BM1688/CV186AH中的的视频处理子系统，包括图形运算加速单元以及解码单元，也称为VPP |
| JPU | BM1688/CV186AH,BM1684/BM1684X中的图像JPEG编解码单元 |
| SOPHONSDK | 算能基于BM1688/CV186AH,BM1684/BM1684X的原创深度学习开发工具包 |
| PCIe Mode | BM1688/CV186AH,BM1684/BM1684X的一种工作形态，作为加速设备来进行使用 |
| SoC Mode | BM1688/CV186AH,BM1684/BM1684X的一种工作形态，本身作为主机独立运行，客户算法可以直接运行其上 |
| arm_pcie Mode | BM1684/BM1684X的一种工作形态，搭载BM1684/BM1684X的板卡作为PCIe从设备插到ARM处理器的服务器上，客户算法运行于ARM处理器的主机上 |
| BMCompiler | 面向智能视觉深度学习处理器研发的深度神经网络的优化编译器，可以将深度学习框架的各种深度神经网络转化为处理器上运行的指令流 |
| BMRuntime | 智能视觉深度学习处理器推理接口库 |
| BMCV | 图形运算硬件加速接口库 |
| BMLib | 在内核驱动之上封装的一层底层软件库，设备管理、内存管理、数据搬运、API发送、A53使能、功耗控制 |
| mlir | 由TPU-MLIR生成的中间模型格式，用于迁移或者量化模型 |
| BModel | 面向智能视觉深度学习处理器的深度神经网络模型文件格式，其中包含目标网络的权重（weight）、指令流等 |
| BMLang | 面向智能视觉深度学习处理器的高级编程模型，用户开发时无需了解底层硬件信息 |
| TPUKernel | 基于智能视觉深度学习处理器原子操作(根据BM1688/CV186AH,BM1684/BM1684X指令集封装的一套接口)的开发库。 |
| SAIL | 支持Python/C++接口的SOPHON Inference推理库，是对BMCV、sophon-media、 BMLib、BMRuntime等的进一步封装 |
| TPU-MLIR | 智能视觉深度学习处理器编译器工程，可以将不同框架下预训练的神经网络，转化为可以在算能智能视觉深度学习处理器上高效运算的bmodel |

### 工作模式

SOPHON BM168X系列产品涵盖了从末端到边缘到中枢的多种产品形态，可以支持两种不同的工作模式，分别对应不同的产品形态，具体信息如下：

| BM168X | SoC模式 | PCIe模式 |
|--------|---------|----------|
| 独立运行 | 是，BM168X即为独立主机，算法运行在BM168X上 | 否，算法部署在X86或ARM主机，推理运行在PCIe卡 |
| 对外IO方式 | 千兆以太网 | PCIe接口 |
| 对应产品 | 微服务器/模组 | PCIe加速卡 |

### 开发环境与运行环境

开发环境是指用于模型转换或验证以及程序编译等开发过程的环境；运行环境是指在具备SOPHON设备的平台上实际使用设备进行算法应用部署的运行环境。

开发环境与运行环境可能是统一的（如插有PCIE加速卡的x86主机，既是开发环境又是运行环境），也可能是分离的（如使用x86主机作为开发环境转换模型和编译程序，使用SoC模式的加速盒子部署运行最终的算法应用）。

但是，无论您使用的产品是SoC模式还是PCIe模式，您均需要一台x86主机作为开发环境，您的运行环境可以是任何我们已经测试支持的系统平台。

# 硬件内存

内存是BM168X应用调试中经常会涉及的重要概念，特别地，有以下3个概念需要特别区分清楚：Global Memory、Host Memory、Device Memory。

- **全局内存（Global Memory）：** 指BM168X的片外存储DDR，对BM1684来说，通常为12GB，最大支持定制为16GB。 **BM1688/CV186AH设备请参考SE9产品手册。**

- **设备内存（Device Memory）和系统内存（Host Memory）：** 根据BM168X产品类型或工作模式的不同，设备内存和系统内存具有不同的含义：

| **模式** | **SoC模式** | **PCIe模式** |
|----------|-------------|--------------|
| **产品** | SM5/SE5/SM7/SE7 | SC5/SC5H/SC5+/SC7FP75/SC7HP75 |
| **Global Memory** | 最大4GB Tensor Computing Processor 专用<br>最大3GB VPU 专用<br>最大4GB VPP 专用<br>（剩余内存供主控Cortex A53使用） | 最大4GB Tensor Computing Processor专用<br>4GB VPU专用<br>4GB VPP/A53专用<br>4GB VPP/A53专用 |
| **Host Memory** | 主控Cortex A53的内存 | 主机内存 |
| **Device Memory** | 划分给Tensor Computing Processor/VPP/VPU的设备内存 | PCIe板卡上的物理内存（Global Memory） |

内存同步问题是后续应用调试中经常会遇到的比较隐蔽的重要问题。我们在sophon-opencv和sophon-ffmpeg两个框架内都提供了内存同步操作的函数；而BMCV API只面向设备内存操作，因此不存在内存同步的问题，在调用BMCV API前，需要将输入数据在设备内存上准备好；我们在BMLib中提供了接口，可以实现Host Memory和Global Memory之间、Global Memory内部以及不同设备的Global Memory之间的数据搬运。更多详细信息请参考《BMLIB开发参考手册》和《多媒体开发参考手册》。

# BModel

**BModel：** 是一种面向算能智能视觉深度学习处理器的深度神经网络模型文件格式，其中包含目标网络的权重（weight）、指令流等等。

**Stage：** 支持将同一个网络的不同batch size的模型combine为一个BModel；同一个网络的不同batch size的输入对应着不同的stage，推理时BMRuntime会根据输入shape的大小自动选择相应stage的模型。也支持将不同的网络combine为一个BModel，通过网络名称来获取不同的网络。

**动态编译和静态编译：** 支持模型的动态编译和静态编译，可在转换模型时通过参数设定。动态编译的BModel，在Runtime时支持任意小于编译时设置的shape的输入shape；静态编译的BModel，在Runtime时只支持编译时所设置的shape。

> **优先使用静态编译的模型：**
> 动态编译模型运行时需要BM168X内微控制器ARM9的参与，实时地根据实际输入shape，动态生成智能视觉深度学习处理器运行指令。因此，动态编译的模型执行效率要比静态编译的模型低。若可以，应当优先使用静态编译的模型或支持多种输入shape的静态编译模型。

# bm_image

**BMCV:** BMCV提供了一套基于 SOPHON Deep learning 处理器优化的机器视觉库，通过利用处理器的 Tensor Computing Processor 和 VPP 模块，可以完成色彩空间转换、尺度变换、仿射变换、透射变换、线性变换、画框、JPEG编解码、BASE64编解码、NMS、排序、特征匹配等操作。

**bm_image:** BMCV api 均是围绕 **bm_image** 来进行的，一个 bm_image 对象对应于一张图片。用户通过 bm_image_create 来构建 bm_image 对象，然后供各个 bmcv 的功能函数使用，使用完需要调用 bm_image_destroy 销毁。

**BMImage:** SAIL库中将bm_image封装为BMImage，相关信息请参考《sophon-sail用户手册》。

如下是bm_image结构体及相关数据格式定义：

```c++
typedef enum bm_image_format_ext_{
    FORMAT_YUV420P,
    FORMAT_YUV422P,
    FORMAT_YUV444P,
    FORMAT_NV12,
    FORMAT_NV21,
    FORMAT_NV16,
    FORMAT_NV61,
    FORMAT_RGB_PLANAR,
    FORMAT_BGR_PLANAR,
    FORMAT_RGB_PACKED,
    FORMAT_BGR_PACKED,
    PORMAT_RGBP_SEPARATE,
    PORMAT_BGRP_SEPARATE,
    FORMAT_GRAY,
    FORMAT_COMPRESSED
} bm_image_format_ext;

typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_4N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
}bm_image_data_format_ext;

// bm_image结构体定义如下
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    bm_image_private* image_private;
};
```

# 算法移植概述

**对于基于深度学习的视频/图片分析任务来说，通常都包括如下几个步骤：**

1. 视频/图片解码
2. 输入预处理
3. 模型推理
4. 输出后处理
5. 视频/图片编码

实际任务中，算法往往还会包含多个不同神经网络模型，因此，步骤2-4会根据需要反复执行多次。

## 硬件加速支持情况

实践证明，单纯针对神经网络运算进行加速，已经无法满足真实场景的需求。为了提高算法运行效率，BM1684/BM1684X 中除智能视觉深度学习处理单元外，还集成了针对编解码、图像处理等操作的若干硬件加速模块。用户通过 SOPHONSDK 中提供的相应软件接口库，可以对如上几个步骤进行针对性地加速，从而便捷地开发出高效的算法和应用。

**为了满足客户对不同风格接口使用的偏好，我们还对硬件加速接口库进行了多次封装，用户可以自行选取合适的接口库进行开发，具体情况总结如下：**

| **任务流程** | **是否支持硬件加速** | **SAIL高级接口库** | **OPENCV接口库** | **FFMPEG接口库** | **Native接口库** |
|-------------|-------------------|-------------------|-----------------|-----------------|-----------------|
| 视频/图片解码 | 支持 | sail::Decoder | Y | Y | BMCV(图片) |
| 输入预处理 | 支持 | sail::Bmcv | Y | N | BMCV |
| 模型推理 | 支持 | sail::Engine | N | N | BMruntime |
| 输出后处理 | 部分支持 | sail::Bmcv | N | N | BMCV |
| 视频/图片编码 | 支持 | sail::Bmcv | Y | Y | BMCV(图片) |

值得一提的是，为了提高算法效率以及硬件特性的要求，用户在调用硬件加速接口的时候需要注意以下几个方面，后续的文档会通过实例来进行具体阐述：

1. 内存零copy
2. 申请物理连续内存
3. 将多个预处理步骤进行合并
4. 凑4nbatch进行推理；其中在BM1684X上由于架构原因，F32、F16 、INT8模型均不需要凑4nbatch也可以达到最高效率

## C/C++/Python三种编程接口

目前支持C/C++/Python三种编程接口：

**BMRuntime模块支持C/C++接口编程，BMCV、BMLib支持C++接口编程；Python/C++编程接口基于SAIL库实现。**

为进一步方便开发使用，sophon-demo在调用BMLib时，进行了简易的封装，用户可参考sophon-demo/include目录。

SAIL（SOPHON Artificial Intelligent Library），是对 SOPHONSDK 中的 BMRuntime、BMCV、BMLib、sophon-mw/sophon-media库的高级封装，将SOPHONSDK中原有的"加载 BModel 并驱动智能视觉深度学习处理器推理"、"驱动视频处理子系统VPP做图像处理以及编解码"等功能抽象成更为简单的 C++ 接口对外提供；并且使用 pybind11 再次封装，提供了简洁易用的 Python 接口。

目前， SAIL 模块中所有的类、枚举、函数都在 "sail" 命名空间下， 关于SAIL C++/Python 接口详细内容请阅读 《SOPHON-SAIL用户手册》。

## 图像类算法调用流程图

## 图像类模型精度调试流程图

# C/C++编程详解

这个章节将会选取 sophon-demo 中的 YOLOV5 检测算法作为示例，说明各个步骤的接口调用和注意事项。

> 样例代码路径：sophon-demo/sample/YOLOV5

这个示例程序采用了 **OPENCV解码+BMCV图片预处理** 的组合进行开发，您也可以根据您的需要采用不同的接口开发。

我们按照算法的执行先后顺序展开介绍：

1. **加载bmodel模型**
2. **预处理**
3. **推理**
4. **注意事项**

## 加载bmodel

```c++
...

BMNNContext(BMNNHandlePtr handle, const char* bmodel_file):m_handlePtr(handle){

    bm_handle_t hdev = m_handlePtr->handle();

    // init bmruntime contxt
    m_bmrt = bmrt_create(hdev);
    if (NULL == m_bmrt) {
    std::cout << "bmrt_create() failed!" << std::endl;
    exit(-1);
    }

    // load bmodel from file
    if (!bmrt_load_bmodel(m_bmrt, bmodel_file)) {
    std::cout << "load bmodel(" << bmodel_file << ") failed" << std::endl;
    }

    load_network_names();

}

...

void load_network_names() {

    const char **names;
    int num;

    // get network info
    num = bmrt_get_network_number(m_bmrt);
    bmrt_get_network_names(m_bmrt, &names);

    for(int i=0;i < num; ++i) {
    m_network_names.push_back(names[i]);
    }

    free(names);
}

...

BMNNNetwork(void *bmrt, const std::string& name):m_bmrt(bmrt) {
    m_handle = static_cast<bm_handle_t>(bmrt_get_bm_handle(bmrt));

    // get model info by model name
    m_netinfo = bmrt_get_network_info(bmrt, name.c_str());

    m_max_batch = -1;
    std::vector<int> batches;
    for(int i=0; i<m_netinfo->stage_num; i++){
        batches.push_back(m_netinfo->stages[i].input_shapes[0].dims[0]);
        if(m_max_batch<batches.back()){
            m_max_batch = batches.back();
        }
    }
    m_batches.insert(batches.begin(), batches.end());
    m_inputTensors = new bm_tensor_t[m_netinfo->input_num];
    m_outputTensors = new bm_tensor_t[m_netinfo->output_num];
    for(int i = 0; i < m_netinfo->input_num; ++i) {

        // get data type
        m_inputTensors[i].dtype = m_netinfo->input_dtypes[i];
        m_inputTensors[i].shape = m_netinfo->stages[0].input_shapes[i];
        m_inputTensors[i].st_mode = BM_STORE_1N;
        m_inputTensors[i].device_mem = bm_mem_null();
    }

...

}

...
```

这个几个函数的用法比较简单和固定，用户可以参考《BMRuntime开发参考手册》了解更详细的信息。唯一需要强调的是name字符串变量的用法：在推理代码中，模型的唯一标识就是他的name字符串，这个name需要在compile阶段就进行指定，算法程序也需要基于这个name开发；例如，在调用inference接口时，需要使用模型的name作为入参，让runtime作为索引去查询对应的模型，错误的name会造成inference失败。

## 预处理

### 预处理初始化

预处理初始化时，需要提前创建适当的bm_image对象保存中间结果，这样可以节省反复内存申请释放造成的开销，提高算法效率，具体代码如下：

```c++
...
m_resized_imgs.resize(max_batch);
m_converto_imgs.resize(max_batch);
// some API only accept bm_image whose stride is aligned to 64
int aligned_net_w = FFALIGN(m_net_w, 64);
int strides[3] = {aligned_net_w, aligned_net_w, aligned_net_w};
for(int i=0; i<max_batch; i++){
    auto ret= bm_image_create(m_bmContext->handle(), m_net_h, m_net_w, 
        FORMAT_RGB_PLANAR, 
        DATA_TYPE_EXT_1N_BYTE, 
        &m_resized_imgs[i], strides);
    assert(BM_SUCCESS == ret);
}
bm_image_alloc_contiguous_mem(max_batch, m_resized_imgs.data());
bm_image_data_format_ext img_dtype = DATA_TYPE_EXT_FLOAT32;
if (tensor->get_dtype() == BM_INT8){
    img_dtype = DATA_TYPE_EXT_1N_BYTE_SIGNED;
}
auto ret = bm_image_create_batch(m_bmContext->handle(), m_net_h, m_net_w, 
    FORMAT_RGB_PLANAR, 
    img_dtype, 
    m_converto_imgs.data(), max_batch);
assert(BM_SUCCESS == ret);
...
```

不同于bm_image_create()函数只创建一个bm_image对象，bm_image_create_batch()会根据最后一个参数batch，创建一组bm_image对象，而且这组对象所使用的data域是物理连续的。使用物理连续的内存是硬件加速器的特殊需求，在析构函数，可以使用bm_image_destroy_batch()对内存进行释放。

接下来是输入的处理过程，这个示例算法同时支持图片和视频作为输入，在main.cpp的main()函数中，我们以视频为例，详细的写法如下：

### 打开视频流

在sophon-demo的YOLOv5示例中，我们基于FFMPEG封装了一个VideoDecFFM类打开视频流或图片，方式如下：

```c++
...

// open stream
VideoDecFFM decoder;
decoder.openDec(&h, input.c_str());

...
```

详细信息可参考:YOLOv5/cpp/dependencies/include/ff_decode.hpp

您也可以通过OpenCV打开视频流

```c++
...

// open stream
cv::VideoCapture cap(input_url, cv::CAP_ANY, dev_id);
if (!cap.isOpened()) {
  std::cout << "open stream " << input_url << " failed!" << std::endl;
  exit(1);
}

// get resolution
int w = int(cap.get(cv::CAP_PROP_FRAME_WIDTH));
int h = int(cap.get(cv::CAP_PROP_FRAME_HEIGHT));
std::cout << "resolution of input stream: " << h << "," << w << std::endl;

...
```

上面这段代码和标准的opencv处理视频流程几乎相同。

### 解码视频帧

相应的

```c++
...

bm_image *img = decoder.grab();
if (!img){
end_flag=true;
}else {
batch_imgs.push_back(*img);
delete img;
img = nullptr;
}

...
```

OpenCV

```c++
...

// get one mat 
cv::Mat img;
if (!cap.read(img)) { //check
    std::cout << "Read frame failed or end of file!" << std::endl;
    exit(1);
}

std::vector<cv::Mat> images;
images.push_back(img);

...
```

# Mat 转换 bm_image

由于BMCV预处理接口和网络推理接口都需要使用bm_image对象作为输入，因此解码后的视频帧需要转换到bm_image对象。推理完成之后，再使用bm_image_destroy()接口进行释放。需要注意的是，这个转换过程没有发生内存拷贝。

```c++
// mat -> bm_image
CV_Assert(0 == cv::bmcv::toBMI((cv::Mat&)images[i], &image1, true));

//destroy
bm_image_destroy(image1);
```

## 预处理

bmcv_image_vpp_convert_padding()函数使用VPP硬件资源，是预处理过程加速的关键，需要配置参数 padding_attr。 bmcv_image_convert_to()函数用于进行线性变换，需要配置参数 converto_attr。

```c++
//resize image
int ret = 0;
for(int i = 0; i < image_n; ++i) {
    bm_image image1 = images[i];
    bm_image image_aligned;
    bool need_copy = image1.width & (64-1);
    if(need_copy){
        int stride1[3], stride2[3];
        bm_image_get_stride(image1, stride1);
        stride2[0] = FFALIGN(stride1[0], 64);
        stride2[1] = FFALIGN(stride1[1], 64);
        stride2[2] = FFALIGN(stride1[2], 64);
        bm_image_create(m_bmContext->handle(), image1.height, image1.width,
            image1.image_format, image1.data_type, &image_aligned, stride2);

        bm_image_alloc_dev_mem(image_aligned, BMCV_IMAGE_FOR_IN);
        bmcv_copy_to_atrr_t copyToAttr;
        memset(&copyToAttr, 0, sizeof(copyToAttr));
        copyToAttr.start_x = 0;
        copyToAttr.start_y = 0;
        copyToAttr.if_padding = 1;
        bmcv_image_copy_to(m_bmContext->handle(), copyToAttr, image1, image_aligned);
    } else {
        image_aligned = image1;
}

// set padding_attr
bmcv_padding_atrr_t padding_attr;
memset(&padding_attr, 0, sizeof(padding_attr));
padding_attr.dst_crop_sty = 0;
padding_attr.dst_crop_stx = 0;
padding_attr.padding_b = 114;
padding_attr.padding_g = 114;
padding_attr.padding_r = 114;
padding_attr.if_memset = 1;
if (isAlignWidth) {
  padding_attr.dst_crop_h = images[i].rows*ratio;
  padding_attr.dst_crop_w = m_net_w;

  int ty1 = (int)((m_net_h - padding_attr.dst_crop_h) / 2);
  padding_attr.dst_crop_sty = ty1;
  padding_attr.dst_crop_stx = 0;
}else{
  padding_attr.dst_crop_h = m_net_h;
  padding_attr.dst_crop_w = images[i].cols*ratio;

  int tx1 = (int)((m_net_w - padding_attr.dst_crop_w) / 2);
  padding_attr.dst_crop_sty = 0;
  padding_attr.dst_crop_stx = tx1;
}

// do not crop
bmcv_rect_t crop_rect{0, 0, image1.width, image1.height};

auto ret = bmcv_image_vpp_convert_padding(m_bmContext->handle(), 1, image_aligned, &m_resized_imgs[i],
    &padding_attr, &crop_rect);

// set converto_attr
float input_scale = input_tensor->get_scale();
input_scale = input_scale* (float)1.0/255;
bmcv_convert_to_attr converto_attr;
converto_attr.alpha_0 = input_scale;
converto_attr.beta_0 = 0;
converto_attr.alpha_1 = input_scale;
converto_attr.beta_1 = 0;
converto_attr.alpha_2 = input_scale;
converto_attr.beta_2 = 0;

// do converto
ret = bmcv_image_convert_to(m_bmContext->handle(), image_n, converto_attr, m_resized_imgs.data(), m_converto_imgs.data());

// attach to tensor
if(image_n != max_batch) image_n = m_bmNetwork->get_nearest_batch(image_n); 
bm_device_mem_t input_dev_mem;
bm_image_get_contiguous_device_mem(image_n, m_converto_imgs.data(), &input_dev_mem);
input_tensor->set_device_mem(&input_dev_mem);
input_tensor->set_shape_by_dim(0, image_n);  // set real batch number
```

## 推理

预处理过程的output是推理过程的input，当推理过程的input数据准备好后，就可以进行推理。

```c++
ret = m_bmNetwork->forward();
```

## 后处理

后处理的过程因模型而异，而且大部分是中央处理器执行的代码，就不再这里赘述。需要注意的是我们在BMCV中也提供了一些可以用于加速的接口，如bmcv_sort、bmcv_nms等，对于其他需要使用硬件加速的情况，可根据需要使用TPUKernel进行开发。

以上就是 YOLOV5 示例的简单描述，关于涉及到的接口更加详细的描述，请查看相应模块文档。

## 算法开发注意事项汇总

**根据上面的讨论，我们把一些注意事项汇总如下：**

- 视频解码需要注意：

> 我们支持使用YUV格式作为缓存原始帧的格式，解码后可通过cap.set()接口设置YUV格式。

- 预处理过程需要注意：

> 1. 预处理的操作对象是bm_image，bm_image对象可以类比Mat对象。
> 2. 预处理流程中scale缩放是针对int8模型。在推理数据输入前需要乘scale系数。scale系数是在量化的过程中产生。
> 3. 为多个bm_image对象申请连续物理内存：bm_image_create_batch()。
> 4. resize默认双线性插值算法，具体参考bmcv接口说明。

- 推理过程需要注意：

> 1. 推理过程在device memory上进行，所以推理前输入数据必须已经存储在input tensors的device mem里面，推理结束后的结果数据也是保存在output tensors的device mem里面。
> 2. 推荐使用4batch优化性能。

# 解码模块

关于解码详细内容请参考《多媒体开发参考手册》。
关于ffmpeg解码python接口请参考《SOPHON-SAIL用户手册》。

本章主要介绍以下两点内容：

- OpenCV解码
- FFmpeg解码

## OpenCV解码

OpenCV支持YUV/BGR格式输出，为了提高性能，示例中解码输出设置yuv格式数据。

简单示例如下：

```c++
cv::VideoCapture cap;
  if (!cap.isOpened()) {
    cap.open(input_url);
}
cap.set(cv::CAP_PROP_OUTPUT_YUV, 1.0); //设置输出YUVI420格式数据，如选择BGR输出则注释掉此行代码
cv::Mat *img = new cv::Mat;
cap.read(*img);
//do something
......
//end
delete img;
```

cap.set接口函数对输出格式设置， cap::read获取cv::Mat对象img，img数据接下来需要通过图像运算加速接口（bmcv模块）对数据进行推理前的预处理操作。

## FFmpeg解码

- C编程接口初始化配置:

```c
// ffmpeg默认输出NV12压缩格式数据, 初始化解码器配置方法如下：
/*set compressed output*/
av_dict_set(&opts, "output_format", "101", 0);

if ((ret = avcodec_open2(*dec_ctx, dec, &opts)) < 0) {
fprintf(stderr, "Failed to open %s codec\n",
            av_get_media_type_string(type));
return ret;
}
```

- Python编程接口

```python
import sophon.sail as sail
decoder = sail.Decoder(filename)
img0 = decoder.read(handle)   #默认输出yuv i420格式
```

# 图形运算加速模块

BMCV提供了一套基于算丰深度学习处理器优化的机器视觉库，目前可以完成色彩空间转换、尺度变换、仿射变换、投射变换、线性变换、画框、JPEG编码、BASE64编码、NMS、排序、特征匹配等操作。关于BMCV模块详细内容请阅读《BMCV开发参考手册》。

Python接口的实现请参考《SOPHON-SAIL用户手册》。

BMCV API均是围绕bm_image来进行的。一个bm_image结构对应于一张图片。

## C语言编程接口

**bm_image结构体**

```c
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    bm_image_private* image_private;
};
```

bm_image 结构成员包括图片的宽高，图片格式，图片数据格式，以及该结构的私有数据。

**图片格式 image_format枚举类型**

```c
typedef enum bm_image_format_ext_{
    FORMAT_YUV420P,
    FORMAT_NV12,
    FORMAT_NV21,
    FORMAT_NV16,
    FORMAT_NV61,
    FORMAT_RGB_PLANAR,
    FORMAT_BGR_PLANAR,
    FORMAT_RGB_PACKED,
    FORMAT_BGR_PACKED,
    FORMAT_GRAY,
    FORMAT_COMPRESSED
}bm_image_format_ext;
```

| 格式              | 说明                                                  |
|-------------------|-------------------------------------------------------|
| FORMAT_YUV420P    | 表示预创建一个YUV420格式的图片，有三个plane           |
| FORMAT_NV12       | 表示预创建一个NV12格式的图片，有两个plane             |
| FORMAT_NV21       | 表示预创建一个NV21格式的图片，有两个plane             |
| FORMAT_RGB_PLANAR | 表示预创建一个RGB格式的图片，RGB分开排列，有一个plane |
| FORMAT_BGR_PLANAR | 表示预创建一个BGR格式的图片，BGR分开排列，有一个plane |
| FORMAT_RGB_PACKED | 表示预创建一个RGB格式的图片，RGB交错排列，有一个plane |
| FORMAT_BGR_PACKED | 表示预创建一个BGR格式的图片，BGR交错排列，有一个plane |
| FORMAT_GRAY       | 表示预创建一个灰度图格式的图片，有一个plane           |
| FORMAT_COMPRESSED | 表示预创建一个VPU内部压缩格式的图片，有四个plane      |

# 数据存储格式枚举

```c
typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_4N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
}bm_image_data_format_ext;
```

| 数据格式 | 说明 |
|---------|------|
| DATA_TYPE_EXT_FLOAT32 | 表示所创建的图片数据格式为单精度浮点数 |
| DATA_TYPE_EXT_1N_BYTE | 表示所创建图片数据格式为普通带符号1N INT8 |
| DATA_TYPE_EXT_4N_BYTE | 表示所创建图片数据格式为4N INT8，即四张带符号INT8图片数据交错排列 |
| DATA_TYPE_EXT_1N_BYTE_SIGNED | 表示所创建图片数据格式为普通无符号1N UINT8 |
| DATA_TYPE_EXT_4N_BYTE | 表示所创建图片数据格式为4N UINT8，即四张无符号INT8图片数据交错排列 |

关于bm_image初始化，我们不建议用户直接填充bm_image结构使用，而是通过以下API来创建/销毁一个bm_image结构

## bm_image_create_batch

创建物理内存连续的多个bm image。

```c
/*
 * @param [in]     handle       handle of low level device             
 * @param [in]     img_h        image height                 
 * @param [in]     img_w        image width
 * @param [in]     img_format   format of image: BGR or YUV
 * @param [in]     data_type    data type of image: INT8 or FP32 
 * @param [out]    image        pointer of bm image object
 * @param [in]     batch_num    batch size
 */
static inline bool bm_image_create_batch (bm_handle_t              handle,  
                                          int                      img_h,  
                                          int                      img_w,    
                                          bm_image_format_ext      img_format,
                                          bm_image_data_format_ext data_type,  
                                          bm_image                 *image, 
                                          int                      batch_num)
```

## bm_image_destroy_batch

释放物理内存连续的多个bm image。要和bm_image_create_batch接口成对使用。

```c
/*
* @param [in]     image        pointer of bm image object
* @param [in]     batch_num    batch size
*/
static inline bool bm_image_destroy_batch (bm_image *image, int batch_num)
```

## bm_image_alloc_contiguous_mem

为多个 image 分配连续的内存

```c
bm_status_t bm_image_alloc_contiguous_mem(
                int image_num,
                bm_image *images,
                int bmcv_image_usage
);
```

| 参数 | 说明 |
|------|------|
| int image_num | 待分配内存的 image 个数 |
| bm_image \*images | 待分配内存的 image 的指针 |
| int bmcv_image_usage | 已经为客户默认设置了参数，（如果客户对于所分配内存位置有要求，可以通过该参数进行制定） |

## bm_image_free_contiguous_mem

释放通过bm_image_alloc_contiguous_mem申请的内存

```c
bm_status_t bm_image_free_contiguous_mem(
                int image_num,
                bm_image *images
        );
```

| 参数 | 说明 |
|------|------|
| int image_num | 待分配内存的 image 个数 |
| bm_image \*images | 待分配内存的 image 的指针 |

## bmcv_image_vpp_convert

BM1684上有专门的视频后处理硬件，满足一定条件下可以一次实现csc + crop + resize功能，速度比智能视觉深度学习处理器更快。

```c
bmcv_image_vpp_convert(
bm_handle_t           handle,
    int                   output_num,
    bm_image              input,
    bm_image *            output,
    bmcv_rect_t *         crop_rect,
    bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

该API将输入图像格式转化为输出图像格式，并支持crop + resize功能，支持从1张输入中crop多张输出并resize到输出图片大小。

| 参数 | 说明 |
|------|------|
| bm_handle_t handle | 设备环境句柄，通过调用bm_dev_request获取 |
| int output_num | 输出 bm_image 数量，和src image的crop 数量相等,一个src crop 输出一个dst bm_image |
| bm_image input | 输入bm_image对象 |
| bm_image\* output | 输出bm_image对象指针 |
| bmcv_rect_t \* crop_rect | 每个输出bm_image对象所对应的在输入图像上crop的参数，包括起始点x坐标、起始点y坐标、crop图像的宽度以及crop图像的高度，具体请查看BMCV用户开发手册 |
| bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR) | resize算法选择，包括 BMCV_INTER_NEAREST 和 BMCV_INTER_LINEAR 两种，默认情况下是双线性差值 |

# bmcv_convert_to

实现图像像素线性变化，具体数据关系可用公式表示：

y = α*x + β

```c
bm_status_t bmcv_convert_to (bm_handle_t handle, int input_num,
                        bmcv_convert_to_attr convert_to_attr, 
                        bm_image* input, bm_image* output)
```

| 参数 | 说明 |
|------|------|
| bm_handle_thandle | 输入的bm_handle句柄 |
| int input_num | 输入图片数。最多支持4 |
| bmcv_convert_to_attr convert_to_attr | 每张图片对应的配置参数 |
| bm_image* input | 输入bm_image。每个bm_image外部需要调用bmcv_image_create创建。image内存可以使用bmcv_image_dev_mem_alloc或者bmcv_image_copy_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。 |
| bm_image* output | 输出bm_image。每个bm_image外部需要调用bmcv_image_create创建。image内存可以通过bmcv_image_dev_mem_alloc来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配 |

## 结构体 bmcv_convert_to_attr_s

```c
typedef struct bmcv_convert_to_attr_s {
    float alpha_0;                 
    float beta_0;  
    float alpha_1;
    float beta_1;
    float alpha_2;
    float beta_2;
} bmcv_convert_to_attr;
```

| 参数 | 说明 |
|------|------|
| alpha_0 | 描述了第0个channel进行线性变换的系数 |
| beta_0 | 描述了第0个channel进行线性变换的偏移 |
| alpha_1 | 描述了第1个channel进行线性变换的系数 |
| beta_1 | 描述了第1个channel进行线性变换的偏移 |
| alpha_2 | 描述了第2个channel进行线性变换的系数 |
| beta_2 | 描述了第2个channel进行线性变换的偏移 |

结构体描述了三通道中的alpha和beta。实际要根据推理的输入数据是几通道来进行参数配置。

## Python语言编程接口

本章节只简要介绍了用例 YOLOv5 所用到的接口函数。

更多接口定义请查阅《SOPHON-SAIL用户手册》。

### init

```python
def __init__(handle): 
""" Constructor.
Parameters 
---------
handle : sail.Handle Handle instance 
"""
```

### convert_to

```python
def convert_to(input, alpha_beta): 
""" Applies a linear transformation to an image.
Parameters
---------
input : sail.BMImage Input image 
alpha_beta: tuple (a0, b0), (a1, b1), (a2, b2) factors
Returns 
---------
output : sail.BMImage Output image 
"""
```

### convert_format

```python
def convert_format(input, output):
"""Convert input to output format.

Parameters
----------
input : sail.BMImage
    BMimage instance
output : sail.BMImage
    output image
"""
```

### vpp_crop_and_resize_padding

```python
def vpp_crop_and_resize_padding(input, crop_x0, crop_y0, crop_w, crop_h, resize_w, resize_h, padding):
""" Crop then resize an image using vpp.

Parameters
----------
input : sail.BMImage
    Input image
crop_x0 : int
    Start point x of the crop window
crop_y0 : int
    Start point y of the crop window
crop_w : int
    Width of the crop window
crop_h : int
    Height of the crop window
resize_w : int
    Target width
resize_h : int
    Target height
padding : PaddingAtrr
    padding info

Returns
----------
output : sail.BMImage
    Output image
"""
```

# 微服务器定制化软件包

## 适配场景

1. 芯片：BM1684 BM1684X BM1688 CV186AH

2. SDK版本：
   - BM1688 & CV186AH v1.3以及之后版本（适配只打包功能和打包做包功能）
   - 84&X 3.0.0以及之前版本（适配只打包功能）
   - 84&X 3.0.0之后版本（适配只打包功能和打包做包功能）

3. 环境需求：
   - 外置存储：
     - 存储分区格式尽量保证ext4，防止特殊分区限制导致做包失败
     - 只打包功能要求外置存储至少是当前emmc使用总量的1.5倍以上
     - 打包做包功能要求外置存储至少是当前emmc使用总量的2.5倍以上
   - 设备需求：
     - 只打包功能要求除去打包设备外需要有一个ubuntu18/20的X86主机
     - 打包做包功能只要求有一个打包做包的设备

## 功能一：打包做包功能

本功能84&X和1688/CV186AH平台使用方式完全一致

1. 使用如下命令下载打包需要使用的工具

```bash
pip3 install dfss --upgrade
python3 -m dfss --dflag=socbak
```

下载的文件是一个socbak.zip文件

2. 将外置存储插入目标设备，然后执行如下操作。

```bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

3. 执行如下命令进行打包

```bash
unzip socbak.zip
cd socbak
export SOC_BAK_ALL_IN_ONE=1
bash socbak.sh
```

等待一段时间

4. 执行成功后会生成如下文件

```bash
root@sophon:/socrepack/socbak# tree -L 1
.
├── binTools
├── output
├── script
├── socbak.sh
├── socbak_log.log
└── socbak_md5.txt

3 directories, 3 files
```

其中socbak_log.log文件是执行的信息记录，刷机包在output/sdcard/路径下

## 功能二：只打包功能

84&X 3.0.0之后, BM1688/CV186AH V1.3以及之后的版本

1. 使用如下命令下载打包需要使用的工具。

```bash
pip3 install dfss --upgrade
python3 -m dfss --dflag=socbak
```

下载的文件是一个socbak.zip文件

2. 将外置存储插入目标设备，然后执行如下操作。

```bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

3. 执行如下命令进行打包。

```bash
unzip socbak.zip
cd socbak
bash socBak.sh
```

等待一段时间

4. 执行成功后会生成如下文件（这里的是一个示例，实际情况下生成的文件可能会多一些）。

```bash
root@sophon:/socrepack/socbak# tree -L 1 .
.
├── binTools
├── boot.tgz
├── data.tgz
├── fip.bin
├── partition32G.xml
├── recovery.tgz
├── rootfs.tgz
├── script
├── socbak.sh
├── socbak_log.log
└── socbak_md5.txt

2 directories, 9 files
```

5. 使用 https://developer.sophgo.com/thread/682.html 这个文档《SOC模式交叉编译docekr环境》搭建正确的交叉编译docker环境。

6. 下载重打包所需文件。**注意**：此步骤开始BM1688 & CV186AH 与 84&X 不同。

## BM1688 & CV186AH

BM1688 & CV186AH 需要下载的文件如下：

a. [bm1688_repack包](https://sophon-file.sophon.cn/sophon-prod-s3/drive/24/01/08/11/bm1688_repack.tgz)

7. 建立目录pack,然后将原始刷机包解压到这个目录下

8. cd到depack.sh文件同目录,然后执行./depack.sh脚本进行解包

9. 生成的各个分区压缩包会在update目录下生成,此时将socbak生成的所有文件都拷贝到这个目录下

10. 修改完毕后cd到enpack.sh文件同目录,然后执行./enpack.sh sdcard 或者./enpack.sh tftp 命令进行打包

11. 生成的新的刷机包在update/sdcard和update/tftp

## BM1684 & BM1684X

BM1684 & BM1684X 需要下载的文件如下：

a. `bootloader-arm64` : github上的源码，需要手动clone
b. sdcard.tgz : 微服务器原始卡刷包。

1. 在bootloader-arm64同级目录下创建install目录, 并在install目录下创建soc_bm1684目录；将sdcard.tgz移动到install/soc_bm1684路径下。

最终目录结构如下

```bash
├── bootloader-arm64
├── install
│   └── soc_bm1684
│       └── sdcard.tgz
```

2. cd到与bootloader-arm64同目录

3. 执行如下命令

```bash
source bootloader-arm64/scripts/envsetup.sh
revert_package
```

拆包结果会在install/soc_bm1684路径，其目录结构如下

```bash
└── soc_bm1684
    ├── boot.tgz
    ├── package_update
    ├── rootfs.tgz
    ├── sdcard.tgz
    ├── spi_flash_bm1684.bin
    ├── data.tgz
    ├── opt.tgz
    ├── recovery.tgz
    ├── rootfs_rw.tgz
    ├── spi_flash.bin
    └── spi_flash_bm1684x.bin
```

4. 将微服务器上生成的同名文件替换到install/soc_bm1684目录下。

5. 将微服务器上生成的partition32G.xml替换到bootloader-arm64/scripts/目录下。

6. 使用build_update sdcard指令更新刷机包，得到的定制刷机包位于install/soc_bm1684/sdcard目录下。

# SoC模式内存修改工具

> SoC模式下的内存修改脚本与远程内存修改工具使用时，均需要目标SoC服务器上rootfs-rw分区（即根目录），有200M以上空间。同时，内存修改脚本在目标SoC的存放目录也需要有200M以上空间；使用远程内存修改工具时，目标SoC的/data分区需要200M空间。
> 使用如下命令查看目录的空间大小：

```bash
# 查看根目录
sudo df -h /
# 查看/data分区
sudo df -h /data
# 查看当前目录
sudo df -h .
```

## 工具1:在SoC上使用脚本进行修改

说明：本脚本用于在SoC运行环境中修改 SE9 的 NPU、VPP 的内存分配；SE5、SE7、SE6 算力板等工作在SoC模式下的 BM1684/BM1684X 的 NPU、VPU、VPP 的内存分配。

同时， SE9 调整 NPU、VPP 后，SoC的操作系统将使用除了 NPU、VPP 、uboot固件之外的所有内存。

SE5、SE7、SE6 算力板等工作在SoC模式下的设备调整 NPU、VPU、VPP 后，SoC的操作系统将使用除了NPU、VPU、VPP、uboot固件之外的所有内存。

> SE9：本脚本默认适配 v1.3release及之后版本。之前的版本修改后有启动失败的风险；如果发现设备树没有自动识别正确，请在命令末尾增加一个设备树文件名用于指定设备树
>
> SE5、SE7、SE6算力板：本脚本默认适配官网 V22.09.02 及之后版本。可以通过手动在末尾增加当前运行的设备树的名称的方式使其适用于 V22.09.02 之前的版本，但此方法并不推荐。

使用教程：

1. 使用浏览器打开并下载 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz ，选择"memory_edit_v<x.x>.tar.xz"压缩包。

### SE9

1. 登录微服务器，并将脚本压缩包拷贝到SoC微服务器上，执行解压命令并进入该压缩包；并执行命令检查微服务器 NPU、VPP 当前可以配置的最大内存大小和当前配置的内存大小。

```bash
tar -xaf memory_edit_vx.x.tar.xz
cd memory_edit
./memory_edit.sh -p
```

其中类似如下的输出显示了可配置的最大内存。**其中, MiB（Mebibyte）是计算机存储容量的单位， 1 MiB = 1024 KiB = 1024*1024 Byte。**

```bash
Info: get max memory size ...
Info: max npu+vpp size: 0x97800000 [2424 MiB]
Info: max npu size: 0x97800000 [2424 MiB]
Info: max vpp size: 0x97800000 [2424 MiB]
```

其中类似如下的输出显示了当前配置的内存大小。

```bash
Info: get now memory size ...
Info: now npu size: 0x30000000 [768 MiB]
Info: now vpp size: 0x50000000 [1280 MiB]
```

请检查输出中是否有 Error ，如果有请检查SoC运行环境是否支持内存修改。

3. 进行内存布局的修改，其中输入的三个参数是需要 NPU、VPP 配置的大小的十进制数字，单位MiB；或者为十六进制数值，单位Byte。 **SE9默认没有VPU内存，配置为0即可。**

```bash
# 十进制，单位MiB
./memory_edit.sh -c -npu 300 -vpu 0 -vpp 300
# 十六进制，单位Byte
./memory_edit.sh -c -npu 0x12C00000 -vpu 0x0 -vpp 0x12C00000
```

请检查输出中是否有 Error ，以及类似于如下输出中三个部分的大小是否与您所需要配置的大小相同。

```bash
Info: =======================================================================
Info: output configuration results ...
Info: ion npu mem area(ddr1): 0x12c00000 [300 MiB] 0x68800000 -> 0x7b3fffff
Info: ion vpp mem area(ddr1): 0x12c00000 [300 MiB] 0xed400000 -> 0xffffffff
Info: =======================================================================
Info: start check memory size ...
Info: check npu size: 0x12c00000 [300 MiB]
Info: check vpp size: 0x12c00000 [300 MiB]
Info: check edit size ok
```

4. 如果检查无误，请保存当前工作，将修改后的 boot.itb 文件替换启动分区中的启动映像，并重启机器使修改生效。

```bash
sudo cp boot.itb /boot && sync
sudo reboot
```

> 如果需要迁移修改配置，请导出这个 boot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version 命令查看。**

### SE5、SE7、SE6算力板

2. 登录微服务器，并将脚本压缩包拷贝到SoC微服务器上，执行解压命令并进入该压缩包；并执行命令检查微服务器 NPU、VPU、VPP 当前可以配置的最大内存大小和当前配置的内存大小。

```bash
tar -xaf memory_edit_vx.x.tar.xz
cd memory_edit
./memory_edit.sh -p
```

其中类似如下的输出显示了可配置的最大内存。**其中, MiB（Mebibyte）是计算机存储容量的单位， 1 MiB = 1024 KiB = 1024*1024 Byte。**

```bash
Info: get max memory size ...
Info: max npu size: 0xfaf00000 [4015 MiB]
Info: max vpu size: 0xb8000000 [2944 MiB]
Info: max vpp size: 0x100000000 [4096 MiB]
```

其中类似如下的输出显示了当前配置的内存大小。

```bash
Info: get now memory size ...
Info: now npu size: 0x7d000000 [2000 MiB]
Info: now vpu size: 0x7e800000 [2024 MiB]
Info: now vpp size: 0x80000000 [2048 MiB]
```

请检查输出中是否有 Error ，如果有请检查SoC运行环境是否支持内存修改。

3. 进行内存布局的修改，其中输入的三个参数是需要 NPU、VPU、VPP 配置的大小的十进制数字，单位MiB；或者为十六进制数值，单位Byte。

```bash
# 十进制，单位MiB
./memory_edit.sh -c -npu 2048 -vpu 2048 -vpp 2048
# 十六进制，单位Byte
./memory_edit.sh -c -npu 0x80000000 -vpu 0x80000000 -vpp 0x80000000
```

请检查输出中是否有 Error ，以及类似于如下输出中三个部分的大小是否与您所需要配置的大小相同。

```bash
Info: =======================================================================
Info: output configuration results ...
Info: vpu mem area(ddr3): 0x8000000 [128 MiB] 0x78000000 -> 0x7fffffff
Info: ion npu mem area(ddr1): 0x80000000 [2048 MiB] 0x5100000 -> 0x850fffff
Info: ion vpu mem area(ddr3): 0x80000000 [2048 MiB] 0x80000000 -> 0xffffffff
Info: ion vpp mem area(ddr4): 0x80000000 [2048 MiB] 0x80000000 -> 0xffffffff
Info: =======================================================================
Info: start check memory size ...
Info: check npu size: 0x80000000 [2048 MiB]
Info: check vpu size: 0x80000000 [2048 MiB]
Info: check vpp size: 0x80000000 [2048 MiB]
Info: check edit size ok
```

4. 如果检查无误，请保存当前工作，将修改后的 emmcboot.itb 文件替换启动分区中的启动映像，并重启机器使修改生效。

```bash
sudo cp emmcboot.itb /boot 
sync
sudo reboot
```

> 如果需要迁移修改配置，请导出这个 emmcboot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version 命令查看。**

## 工具2:使用图像化程序远程修改

说明：本工具是一个图形化程序，可以通过远程 SSH 修改工作在 SoC 模式下的 BM1684/BM1684X 的 NPU、VPU、VPP 占用空间。默认适配环境为 64 位 win10 操作系统或者带有桌面环境的linux系统。

> 该工具只能适用于提供的 V22.09.02 及以后版本SoC版本。
> 当前默认适配桌面系统如下: amd64-win10、amd64-linux(带有完整桌面，如xfce4)、aarch64-linux(带有完整桌面，如xfce4)。

**单远程目标**

使用教程：

1. 使用浏览器打开 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz 并下载最新的远程内存修改工具，选择"qt_mem_edit_V<x.x.x>."文件，其中.exe文件适用于win系统，.AppImage适用于带有桌面环境的linux系统。

2. windows 系统双击程序即可运行，linux 系统可能需要使用 `chmod +x qt_mem_edit_Vx.x.x-架构名.AppImage` 命令使能其具有运行权限后才能运行该程序。

3. 在该程序中配置微服务器远程 SSH 链接需要的 IP、端口、用户名和密码。

4. 点击"修改目录"按钮配置执行文件目录，该目录会在当前操作的host主机上存放远程修改内存的所有过程文件（默认目录为远程内存修改程序所在目录）。

### SE9

5. 点击"获取信息"按钮获取微服务器当前 NPU、VPP 配置的内存大小信息和最大可以配置的内存大小信息，这些信息将在"获取信息"按钮左侧的文本框中显示。

6. 根据您的需要修改"进行配置"按钮等高的两个个数字框（SE9没有VPU内存，配置为0即可），它们代表了需要配置的 NPU、VPP 各个部分的内存大小（单位 MiB，十进制）。

7. 点击"进行配置"按钮，配置完成后，程序输出如下图。

8. 查看"远程执行信息"中是否有 Error 输出，如果没有错误输出，请登录微服务器，保存微服务器上当前工作，并重启微服务器使您的修改生效。

```bash
sudo reboot
```

9. 进行操作后执行文件目录下会存放从微服务器上获取的内存修改的所有过程文件，文件名以 memory_edit_p_为前缀代表该文件是"获取信息"操作的过程文件，文件名以 memory_edit_c_为前缀代表该文件是"进行配置"操作的过程文件。

文件名以 memory_edit_p_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── boot.itb
    ├── log.txt
    ├── memory_edit.sh
    ├── multi.its
    ├── memory_edit_p.log
    └── output
```

文件名以 memory_edit_c_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── boot.itb
    ├── log.txt
    ├── memory_edit.sh
    ├── multi.its
    ├── memory_edit_c.log
    └── output
```

> 在"进行配置"操作的过程文件压缩包中，有一个名为 boot.itb 的文件，如果需要迁移修改配置，请解压并导出这个 boot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下。 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version 命令查看上述信息**

### SE5、SE7、SE6算力板

5. 点击"获取信息"按钮获取微服务器当前 NPU、VPU、VPP 配置的内存大小信息和最大可以配置的内存大小信息，这些信息将在"获取信息"按钮左侧的文本框中显示。

6. 根据您的需要修改"进行配置"按钮等高的三个数字框，它们代表了需要配置的 NPU、VPU、VPP 各个部分的内存大小（单位 MiB，十进制）。

7. 点击"进行配置"按钮，配置完成后，程序输出如下图。

8. 查看"远程执行信息"中是否有 Error 输出，如果没有错误输出，请登录微服务器，保存微服务器上当前工作，并重启微服务器使您的修改生效。

```bash
sudo reboot
```

9. 进行操作后执行文件目录下会存放从微服务器上获取的内存修改的所有过程文件，文件名以 memory_edit_p_为前缀代表该文件是"获取信息"操作的过程文件，文件名以 memory_edit_c_为前缀代表该文件是"进行配置"操作的过程文件。

文件名以 memory_edit_p_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── emmcboot.itb
    ├── log.txt
    ├── memory_edit.sh
    ├── multi.its
    ├── memory_edit_p.log
    └── output
```

文件名以 memory_edit_c_为前缀的获取信息压缩包中文件目录如下：

```
└── memory_edit
    ├── bintools
    ├── emmcboot.itb
    ├── log.txt
    ├── memory_edit.sh
    ├── multi.its
    ├── memory_edit_c.log
    └── output
```

> 在"进行配置"操作的过程文件压缩包中，有一个名为 emmcboot.itb 的文件，如果需要迁移修改配置，请解压并导出这个 emmcboot.itb 文件，拷贝到其他需要修改的微服务器的/boot 目录下。 **要求：与修改时使用的微服务器型号、刷机包版本、SDK 版本相同，可以通过 bm_version 命令查看上述信息**

**多远程目标**

# 使用教程

1. 使用浏览器打开 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/13/DeviceMemoryModificationKit.tgz 并下载最新的远程内存修改工具，选择"qt_mem_edit_V<x.x.x>."文件，其中.exe文件适用于win系统，.AppImage适用于带有桌面环境的linux系统。

2. windows系统双击程序即可运行，linux系统可能需要使用 `chmod +x qt_mem_edit_Vx.x.x-架构名.AppImage` 命令使能其具有运行权限后才能运行该程序。

3. 修改"进行配置"按钮等高的三个数字框，它们代表了需要配置的 NPU、VPU、VPP 各个部分的内存大小（单位 MiB，十进制）。

远程内存修改工具进行配置

4. 点击远程内存布局修改工具中的"批量配置"按钮。其中，"载入文件"，可以载入一个json格式保存的远程批量信息文件，可以实现远程微服务器一键导入。若您使用的是SE6系列微服务器，"预设文件"中 "inse6conf"代表在SE6控制板上运行该程序的配置，"outse6conf"代表在SE6通过默认SSH端口运行该程序的配置。

5. 配置好需要修改内存的批量远程目标后，点击"批量配置"，在弹出的窗口中选择"yes"，在多台远程设备内存修改时，远程微服务器将会自动重启。执行文件目录下会存放所有远程设备的执行文件。

远程内存修改工具批量配置

# SE6/8易用性工具说明

本应用为SE6/SE8高密度服务器上运行的易用性工具，具有快速配置算力核心、快速上传下载文件、快速刷机、修改算力核心内存布局等功能，以便简化用户操作。

> 本工具在1.2.0及之后版本可以使用 `man bmsec` 命令，或者在/opt/sophon/bmsec/doc位置下查看html帮助文档。由于本文档可能并不适用于最新版本工具，推荐使用上述方式查看帮助文档。

## 安装与更新

使用浏览器打开并下载 https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/10/19/17/bmsec_V1.4.0.deb.tgz 。

并将下载后的deb文件拷贝至目标服务器，并使用如下命令解压、安装：

```bash
tar -xaf bmsec_V1.4.0.deb.tgz
sudo dpkg -i bmsec_V<x.x.x>.deb
```

## 运行方式

本工具共有两种运行方式:

1. 交互运行方式直接运行 `bmsec`，随后输入功能序号运行；
2. 命令行直接运行，如 `bmsec help` 、 `bmsec pconf` ，更多运行参数见8.3.3节主要功能列表。

## 主要功能列表

1. 打印帮助文档 [help]
2. 打印配置信息 [pconf]
3. 远程执行命令 [run <id> <cmd>]
4. 获取所有远程设备信息 [getbi]
5. 上传文件 [pf <id> <localFile> <remoteFile>]
6. 下载文件 [df <id> <remoteFile> <localFile>]
7. 链接指定ssh [ssh <id>]
8. 重启某个算力节点电源 [reset <id>]
9. 链接指定算力节点调试串口 [uart <id>]
10. 打印指定算力节点调试串口 [puart <id>]
11. 使用控制板自带刷机包升级指定算力板 [update <id>]
12. 检查当前tftp升级进度 [tftpc]
13. 启动NFS服务并共享到算力板 [nfs]
14. 批量修改内存布局 [cmem {<p> / < <c> <npuSize> <vpuSize> <vppSize> >} [dtsFile]]
15. 重新生成算力核心配置信息 [rconf]
16. 生成指定算力核心的刷机包 [sysbak]

更多功能请使用 `man bmsec` 命令或者查看/opt/sophon/bmsec/doc位置下的html帮助文档。

## 注意事项

> **重点：** 本工具的run功能只适合部署，不适合长时间运行此命令。

- 第一次运行 `bmsec` 将自动进行配置，算力核心节点域名为se.[x],[x]代表了算力核心的ID编号；之后可以通过 `bmsec rconf` 命令重置配置信息；

- 若用户修改了算力核心的SSH端口和密码等参数，需要修改工具安装目录的configs/sub/subInfo.12文件中对应的参数。

# 批量部署工具

说明：批量部署工具为方便在多台设备上进行命令批量执行，文件批量上传/下发的工具；该工具适用于可以进行SSH的SoC或PCIe设备；

## 工具的获取

使用浏览器打开并下载：https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/10/31/09/qt_batch_deployment.zip

文件下载完成后为压缩包，将压缩包解压完成后文件路径如下：

```
└── qt_batch_deployment
    ├── qt_batch_deployment_Vxxx_windows_x86_64.zip
    ├── qt_batch_deployment_Vxxx-x86_64.AppImage
    └── qt_batch_deployment_Vxxx-x86_64.AppImage
```

因为压缩包内将windows下工具进行了再打包，将上面的 *qt_batch_deployment_Vxxx_windows_x86_64.zip* 再次解压后得到如下工具：

```
└── qt_batch_deployment
    ├── qt_batch_deployment_no_ui_Vxxx.7z
    ├── qt_batch_deployment_Vxxx.exe
    ├── qt_batch_deployment_Vxxx-x86_64.AppImage
    └── qt_batch_deployment_Vxxx-x86_64.AppImage
```

qt_batch_deployment_no_ui_Vxxx.7z为windows下无ui版本工具，需要进一步解压，下列列表为将其中所有压缩包完成解压后的路径：

```
└── qt_batch_deployment
    ├── translations
    ├── libcrypto-3-x64.dll
    ├── libgcc_s_seh-1.dll
    ├── libssl-3-x64.dll
    ├── libstdc++-6.dll
    ├── libwinpthread-1.dll
    ├── qt_batch_deployment_no_ui.exe #Windows环境下无UI使用版本
    ├── qt_batch_deployment_Vxxx.exe #Windows环境下图形化界面版本
    ├── qt_batch_deployment_Vxxx-aarch64.AppImage #支持aarch64 Linux环境下使用版本
    ├── qt_batch_deployment_Vxxx-x86_64.AppImage #支持x86 Linux环境下使用版本
    └── Qt5Core.dll
```

其中可执行文件为qt_batch_deployment_no_ui.exe，qt_batch_deployment_Vxxx.exe，qt_batch_deployment_Vxxx-aarch64.AppImage，qt_batch_deployment_Vxxx-x86_64.AppImage。

- qt_batch_deployment_no_ui.exe为Windows环境下无UI使用版本；
- qt_batch_deployment_Vxxx.exe为Windows环境下图形化界面版本；
- qt_batch_deployment_Vxxx-aarch64.AppImage为支持aarch64 Linux环境下使用版本；
- qt_batch_deployment_Vxxx-x86_64.AppImage为支持x86 Linux环境下使用版本；

> xxx为工具更新的版本号，需要对应具体下载后得到的工具版本；

## 图形化模式使用指引

### 图形化模式启动方式

Linux系统：

- aarch64 Linux下，执行如下命令以启动程序：

```
./qt_batch_deployment_Vxxx-aarch64.AppImage
```

- x86 Linux下，执行如下命令以启动程序：

```
./qt_batch_deployment_Vxxx-x86_64.AppImage
```

Windows系统：

双击 *qt_batch_deployment_Vxxx.exe* 启动图形化模式；

### 图形化模式操作指引

Liunx系统下和Windows系统下图形化操作方法相同；

如下图为图形化模式的主界面；

图形化模式主界面

图形化模式操作流程如下所示：

1. 选择文件操作根目录：

文件操作根目录选择

红色框部分为选择进行文件操作的根目录，点击选择根目录按钮，会弹出路径选择框；

2. 进行远程设备信息配置：

远程设备信息配置区域

红色框部分为远程设备信息配置框，用来配置远程设备的基本信息；

信息包含：

- 1. IPv4地址：设备的IP地址；
- 2. SSH端口：通过SSH连接设备的端口号；
- 3. 用户名：通过SSH连接设备的用户名；
- 4. 密码：通过SSH连接设备相应用户的密码；

可以通过右键已配置的设备信息进行添加或删除设备信息，设备添加方式为克隆当前设备信息，克隆完成后进行修改；

3. 进行操作信息配置：

操作信息配置区域

在红色框部分中进行需要批量执行的操作配置；

通过右键已配置的操作信息进行添加或删除需要执行的操作信息，设备添加方式为克隆当前设备信息，克隆完成后进行修改；

批量操作共分为三类：

3.1 命令下发

命令下发类操作配置区域

即在目标设备上执行这里定义的指令，执行完成后会返回执行结果；

同时可以通过输入执行成功/失败关键字对执行结果进行判断，为空时不进行检查；

3.2 文件上传

文件上传类操作配置区域

选择将本地文件批量上传到目标设备上，通过点击选择文件选择需要上传的文件；

在配置目标路径中配置目标设备上的文件路径，需要为绝对路径且为全英文路径；

3.3 文件下载

文件下载类操作配置区域

将目标设备上的文件下载至本地；

在配置目标路径中配置目标设备上的需要下载的文件路径，需要为绝对路径且为全英文路径；

点击选择目录选择文件下载到的本地路径；

4. 选择内置预设文件（可选）：

选择内置预设文件区域

工具提供了inSE6conf.json和outSE6conf.json两个预置文件，用于SE6上的批量部署；

5. 载入/保存配置文件（可选）:

载入/保存配置文件区域

因为每次启动批量部署工具时配置信息会被初始化，因此可以选择将已配置好的配置项进行保存，点击保存配置文件进行保存；

可以通过载入配置文件对已保存的配置文件进行读取；

6. 配置并行上限：

配置并行上限按钮

这里可以选择最大并行上线已控制运行时的负载；

默认值为200，可以调整为200，100，50，20，2；

7. 点击执行配置按钮，开始进行批量部署；

执行按钮

在部署完成后，会在红色框的位置打印返回信息；

执行结果返回区域

多台设备的打印信息使用分页进行切换；

## 命令行模式使用指引

### 命令行模式启动方式

Linux系统：

- aarch64 Linux下，执行如下命令以启动程序：

```
./qt_batch_deployment_Vxxx-aarch64.AppImage [Root Directory] [Json File Path] [Max Value]
```

- x86 Linux下，执行如下命令以启动程序：

```
./qt_batch_deployment_Vxxx-x86_64.AppImage [Root Directory] [Json File Path] [Max Value]
```

Windows系统：

- Windows系统下，执行如下命令以启动程序：

```
./qt_batch_deployment_no_ui.exe [Root Directory] [Json File Path] [Max Value]
```

*[Root Directory]* 为文件操作的根目录，与图形化模式操作指引中第一条指引相同；

*[Json File Path]* 为批量部署设备和操作的配置文件，格式为Json，为图形化模式操作指引中第五条保存配置文件所得到的结果，也可以参考保存结果的格式进行手动编辑；

*[Max Value]* 为最大并行数设置，与图形化模式操作指引中第六条相同；

### 命令行模式操作指引

参考命令行模式启动方式进行指令启动；在启动完成后会将执行信息和执行结果进行打印；

打印信息与图形化界面的分页不同，会以设备ID的为序进行顺序输出；

最后会输出每个设备上执行成功/失败的信息。

# 微服务器对外接口文档说明

## 介绍

本文档介绍了算能微服务器的对外接口使用方式，提供了通过C语言demo控制和使用命令行控制的方法。

### C语言demo，可以点击下载demo

1. [led_crtl](https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/10/30/09/key_led.zip)

- 本Demo可以通过写入指定文件的值而控制继电器或者输出端口。

- 本Demo在测试继电器和输出端口章节使用。

2. [uartDemo](https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/09/11/15/uartDemo.zip)

- 本Demo可以打印当前用户可以使用的全部串口，可以发送bytes信号，进行串口的回环测试与两两对测，默认使用9600波特率。

- 本Demo中封装了检测串口、配置串口、简易的数据分割函数，可以参考源码以使用。

- 本Demo在测试RS485和RS232章节使用。

3. [key_input](https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/10/30/09/key_led.zip)

- 本Demo接受in接口的输入，并将接口输入打印在命令行里。

- 本Demo在测试输入端口章节使用。

### 协议介绍

RS232: 是一种串行通信协议，常用于连接计算机和外部设备。它使用传统的电压级别（正负12V）来表示逻辑1和逻辑0，通常使用DB9或DB25连接器。RS232通常用于短距离通信。

RS485: 是一种多点通信协议，适用于在工业环境中连接多个设备。它使用平衡传输，允许两根信号线在不同的电平上传输，以实现差分信号。这种设计使得RS485更具抗干扰能力，并适用于较长距离的通信，可以连接多个设备。

TTL: 是一种数字电平标准，通常用于数字电路之间的通信。它使用0V表示逻辑0，使用约3.3V至5V之间的电压表示逻辑1。TTL通信在数字设备之间进行，例如微控制器、传感器和逻辑处理器之间的通信。

### IN/OUT 引脚介绍

IN（输入）：IN通常表示一个设备或电路的输入引脚。这是信息或信号进入设备或电路的地方。通常，IN引脚接收来自其他设备、传感器或电路的信号或数据，并将其传递给设备的内部电子元件进行处理或操作。

举例：在一个数字电子器件中，IN引脚可能接收外部传感器的数据输入，然后将其传递给微处理器进行处理。

OUT（输出）：OUT通常表示一个设备或电路的输出引脚。这是信息或信号从设备或电路输出的地方。通常，OUT引脚从设备的内部电子元件输出已处理或操作的数据或信号，以供其他设备或电路使用。

举例：在一个音频放大器中，OUT引脚可能输出已放大的音频信号，以供连接到扬声器或其他音频设备使用。

### 继电器介绍

# 继电器

继电器是一种电子开关设备，它能够在一个电路中控制另一个电路的开关状态。继电器的操作基于电磁原理，通过一个电磁线圈控制内部开关的状态。它可以用来隔离电路、放大信号、控制高电流负载，以及实现自动化和远程控制。

继电器包含以下常见接口：

## 常闭触点（NC - Normally Closed）

- 端子标记：通常用 NC 表示
- 作用：这是一个常闭触点，当继电器未被激活时，这两个端子之间是连接的，允许电流流过。当继电器激活时，这两个端子分开，中断电流通路

## 常开触点（NO - Normally Open）

- 端子标记：通常用 NO 表示
- 作用：这是一个常开触点，当继电器未被激活时，这两个端子之间是分开的，电流无法通过。当继电器激活时，这两个端子闭合，允许电流流过

## 公共触点（COM - Common）

- 端子标记：通常用 COM 表示
- 作用：这是一个中性连接点，用于与常闭触点或常开触点连接。它是电流进出的通用接口

# 微服务器设备端口说明

## 微服务器外观1

| 面板丝印 | 名称 | 说明 |
|---------|------|------|
| TX | Debug发送信号 | Debug发送信号，需要与RX信号配合使用 |
| RX | Debug接收信号 | Debug接收信号，需要与TX信号配合使用 |
| A1 | RS485正极 | RS485接口正极，需要与B1信号配合使用 |
| B1 | RS485负极 | RS485接口负极，需要与A1信号配合使用 |
| A2 | RS485正极 | RS485接口正极，需要与B1信号配合使用 |
| B2 | RS485负极 | RS485接口负极，需要与A1信号配合使用 |
| IN1 | I/O1输入 | GPIO1输入，可作为告警输入 |
| IN2 | I/O2输入 | GPIO2输入，可作为告警输入 |
| COM | RELAY公共端子 | RELAY接线公共端子 |
| NO | RELAY常开 | RELAY接线常开端子 |
| NC | RELAY常闭 | RELAY接线常闭端子 |
| 12V | DC输出接口 | DC输出12V电源接口 |
| GND | 接地信号 | 凤凰端子接地信号 |

## 微服务器外观2

| 面板丝印 | 名称 | 说明 |
|---------|------|------|
| TXD | RS232发送信号 | RS232发送信号，需要与RXDRS232信号配合使用 |
| RXD | RS232接收信号 | RS232接收信号，需要与TXDRS232信号配合使用 |
| D+ | RS485正极 | RS485接口正极，需要与D-RS485信号配合使用 |
| D- | RS485负极 | RS485接口负极，需要与D+RS485信号配合使用 |
| IN1 | I/O1输入 | GPIO1输入，可作为告警输入 |
| IN2 | I/O2输入 | GPIO2输入，可作为告警输入 |
| OUT1 | I/O2输出 | GPIO1输出，可作为告警输出 |
| OUT2 | I/O2输出 | GPIO2输出，可作为告警输出 |
| GND | 接地信号 | 凤凰端子接地信号 |

## 微服务器外观3

| 面板丝印 | 名称 | 说明 |
|---------|------|------|
| RS232 | RS232接口 | RS232接口 |
| RS485 | RS485接口 | RS485接口 |

# 测试RS232使用说明

本章节根据具体的算能微服务器提供了回环测试和两两对测的详细接线示例及结果展示，注意此示例仅供参考，接线方式并不唯一，并没有提供所有接线方式的组合。

## 回环测试

1. 首先需要准备一台具有RS232串口的算能微服务器，不限于微服务器设备端口说明中的设备，以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明

2. 通过网络或串口线连接上微服务器并打开两个终端，并在两个终端使用如下命令，然后重新登陆。让linaro用户获取串口操作权限。否则请全程使用sudo或在root用户下操作：

```bash
sudo usermod -aG tty linaro
sudo usermod -aG dialout linaro
```

3. 将uartDemo.c拷贝到微服务器，并执行以下命令编译得到uartDemo

```bash
gcc uartDemo.c -o uartDemo
```

4. 在任意终端查看串口信息，使用以下命令检查当前系统可以使用的串口路径

```bash
./uartDemo -p
```

5. 并根据以下说明找到设备串口与路径的对应关系

一般微服务器外观2的RS232接口信息如下：
- RXD，TXD 为设备RS232接口，对应串口设备路径/dev/ttyS2，用作对外RS232接口，协议RS232

一般微服务器外观3的RS232接口信息如下：
- RS232 为设备RS232接口，对应串口设备路径/dev/ttyS1，用作对外RS232接口，协议RS232。需要您准备一个RS232转接头，引出RX和TX接口

6. 将算能微服务器设备串口的发送信号与接收信号连接，具体接线连接方式如下

7. 选择微服务器上打开的两个终端，选择其中一个终端为发送端，使用-r参数指定；另一个为接收端，使用-t参数指定

```bash
./uartDemo -[r/t] <串口设备路径>
```

8. 检查两个终端的输出，接收端输出带有--> Validation-successful ←表示验证完成

## 两两对测

1. 首先需要准备两台具有RS232串口的算能微服务器机器1、2，不限于微服务器设备端口说明中的设备，以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明

2. 通过网络或串口线分别连接两台微服务器并各自打开终端，并在两个终端使用如下命令，然后重新登陆。让linaro用户获取串口操作权限。否则请全程使用sudo或在root用户下操作：

```bash
sudo usermod -aG tty linaro
sudo usermod -aG dialout linaro
```

3. 将uartDemo.c拷贝到微服务器，并执行以下命令编译得到uartDemo

```bash
gcc uartDemo.c -o uartDemo
```

4. 分别在两台设备的终端查看串口信息，使用以下命令检查当前系统可以使用的串口路径

```bash
./uartDemo -p
```

5. 并根据以下说明找到设备串口与路径的对应关系

一般微服务器外观2的RS232接口信息如下：
- RXD TXD 为设备RS232接口，对应串口设备路径/dev/ttyS2，用作对外RS232接口，协议RS232

一般微服务器外观3的RS232接口信息如下：
- RS232 为设备RS232接口，对应串口设备路径/dev/ttyS1，用作对外RS232接口，协议RS232。需要您准备一个RS232转接头，引出RX和TX接口

6. 将机器1设备串口的发送信号与机器2接收信号连接，再将机器2设备串口的发送信号与机器1接收信号连接，具体接线连接方式如下

7. 把机器1的终端当作发送端，使用-r参数指定，机器2当作接收端，使用-t参数指定

```bash
./uartDemo -[r/t] <串口设备路径>
```

8. 检查两个终端的输出，接收端输出带有--> Validation-successful ←表示验证完成

9. ctrl+c分别中止以上命令，同理，将机器2设备串口的发送信号与机器1接收信号连接，再将机器1设备串口的发送信号与机器2接收信号连接，具体接线连接方式如下

10. 把机器2的终端当作发送端，使用-r参数指定，机器1当作接收端，使用-t参数指定

```bash
./uartDemo -[r/t] <串口设备路径>
```

11. 检查两个终端的输出，接收端输出带有--> Validation-successful ←表示验证完成

# 测试RS485使用说明

## 两两对测

由于RS485使用差分信号进行一对多通讯，所以不能通过短接进行回环测试。

1. 首先需要准备具有RS485串口的两台算能微服务器或者一台具有二个RS485串口的算能微服务器，分别对应串口1、2，不限于微服务器设备端口说明中的设备，以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明

2. 通过网络或串口线分别连接二个接口对应的微服务器并各自打开终端，并在两个终端使用如下命令，然后重新登陆。让linaro用户获取串口操作权限。否则请全程使用sudo或在root用户下操作：

```bash
sudo usermod -aG tty linaro
sudo usermod -aG dialout linaro
```

3. 将uartDemo.c拷贝到微服务器，并执行以下命令编译得到uartDemo

```bash
gcc uartDemo.c -o uartDemo
```

4. 分别在两台设备的终端查看串口信息，使用以下命令检查当前系统可以使用的串口路径

```bash
./uartDemo -p
```

5. 并根据以下说明找到设备串口与路径的对应关系，对应微服务器串口可以在微服务器设备端口说明章节查找

一般微服务器外观1的RS485接口信息如下：
- A1 B1 为设备RS485串口，对应串口设备路径/dev/ttyS1，用作对外RS485接口，协议RS485
- A2 B2 为设备RS485串口，对应串口设备路径/dev/ttyS2，用作对外RS485接口，协议RS485

一般微服务器外观2的RS485接口信息如下：
- D+ D- 为设备RS485串口，对应串口设备路径/dev/ttyS1，用作对外RS485接口，协议RS485

一般微服务器外观3的RS485接口信息如下：
- RS485 为设备RS485串口，对应串口设备路径/dev/ttyS2，用作对外RS485接口，协议RS485

注意微服务器外观3的RS485接口为db9接口，需要您准备一个RS485转接头，引出RX和TX接口。RX，TX接口分别为RS485的正极和负极

6. 将接口1 RS485正极与接口2 RS485正极连接，再将接口1 RS485设备串口的负极与接口2 RS485负极连接，具体接线连接方式如下

7. 把接口1对应的终端当作发送端，使用-r参数指定，接口2对应的终端当作接收端，使用-t参数指定

```bash
./uartDemo -[r/t] <串口设备路径>
```

8. 检查两个终端的输出，接收端输出带有--> Validation-successful ←表示验证完成

9. ctrl+c分别中止以上命令，同理，将接口2 RS485正极与接口1 RS485正极连接，再将接口2 RS485设备串口的负极与接口1 RS485负极连接，具体接线连接方式如下

10. 把接口2对应的终端当作发送端，使用-r参数指定，接口1对应的终端当作接收端，使用-t参数指定

```bash
./uartDemo -[r/t] <串口设备路径>
```

11. 检查两个终端的输出，接收端输出带有--> Validation-successful ←表示验证完成

## 备注

1. 以上测试也可以选择使用minicom工具进行简单测试，步骤如下，使用minicom代替uartDemo工具，和上面步骤类似

```bash
sudo apt-get install minicom
```

在发送端和接收端进入minicom

```bash
minicom -D /dev/ttyS串口号 -b 9600
```

在发送端输入便可以在输出端看到输出，验证完成

2. 也可以通过 `dmesg | grep ttyS*` 查看可用串口路径，串口描述如上述步骤

# 测试IN使用说明

1. 需要准备一台具有in接口的算能微服务器机器，不限于微服务器设备端口说明中的设备，以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明

2. 通过网络或串口线连接对应的微服务器并打开终端

3. 正确连接电路，可以外接电源正极连接in接口，负极连接地线，通过按钮/开关控制

4. 执行以下命令便可以监听设备

```bash
sudo apt-get install evtest
sudo evtest /dev/input/event1
```

或者使用key_input监听设备

1. 获取key_input.c ，复制到服务器上
2. 编译gcc key_input.c -o key_input获得可执行程序
3. sudo ./key_input就可以测试GPIO1获取读取输入电平

# 测试OUT使用说明

## 1. 设备准备
需要准备一台具有OUT接口的算能微服务器机器，不限于微服务器设备端口说明中的设备。以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明。

## 2. 连接设备
通过网络或串口线连接对应的微服务器并打开终端。

## 3. 设置输出电平

### 命令行执行方式

#### OUT1接口
```bash
sudo su
sudo echo 1 > /sys/class/leds/gpio5/brightness
```
此时，使用电压表测量电阻档可以连接OUT1和地线，发现电路是通的。

#### OUT2接口
```bash
sudo su
sudo echo 1 > /sys/class/leds/gpio6/brightness
```
此时，使用电压表测量电阻档可以连接OUT2和地线，发现电路是通的。

### C语言demo方式
也可以使用本章提供的led_ctrl C语言demo来设置输出电平：获取led_ctrl.c，复制到服务器上；并编译获得可执行程序。

#### OUT1接口
```bash
gcc led_ctrl.c -o led_ctrl
./led_ctrl 1 5
```
此时，使用电压表测量电阻档可以连接OUT1和地线，发现电路是通的。

#### OUT2接口
```bash
gcc led_ctrl.c -o led_ctrl
./led_ctrl 1 6
```
此时，使用电压表测量电阻档可以连接OUT2和地线，发现电路是通的。

# 测试继电器使用说明

## 1. 设备准备
需要准备一台具有继电器接口的算能微服务器机器，不限于微服务器设备端口说明中的设备。以下章节中包含对应专有名词，请在使用前仔细阅读设备端口说明。

## 2. 连接设备
通过网络或串口线连接对应的微服务器并打开终端。

## 3. 设置继电器开关

### 命令行执行方式
```bash
sudo su
echo 0 > /sys/class/leds/gpio7/brightness #正极连接常闭端子，测试电路是通的，正极连接常开端子，测试电阻，电路不通。
echo 1 > /sys/class/leds/gpio7/brightness #正极连接常开端子，测试电路是通的，正极连接常闭端子，测试电阻，电路不通。
```

### C语言demo方式
也可以使用本章提供的led_ctrl C语言demo来设置继电器开关：获取led_ctrl.c，复制到服务器上；并编译获得可执行程序。

```bash
gcc led_ctrl.c -o led_ctrl
./led_ctrl 0 7 #正极连接常闭端子，测试电路是通的，正极连接常开端子，测试电阻，电路不通。
./led_ctrl 1 7 #正极连接常开端子，测试电路是通的，正极连接常闭端子，测试电阻，电路不通。
```

# 刷机包类型转换工具与tftp刷机方法

说明：刷机包类型转换工具用于sdcard刷机包与tftp刷机包的相互转换；tftp刷机方法见本页末尾；

适用对象：该工具适用于官方刷机包，socbak工具制作的刷机包与bsp工具制作的刷机包；

执行环境：该工具的执行需要在Linux x86系统下，本文以Ubuntu 20.04 x86系统为例；

## 刷机包类型转换工具的获取

使用浏览器打开并下载：https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/11/16/15/sd2tftp.tar

文件下载完成后会得到一个压缩包，将压缩包解压后得到sd2tftp.sh脚本文件。

注意：
首次使用需要安装mkimage工具，可使用如下指令进行安装：
```
sudo apt install u-boot-tools
```

## 刷机包类型转换工具使用指引

1. 将sd2tftp.sh文件置入sdcard刷机包文件或tftp刷机包文件同路径下；
2. 执行指令
```
./sd2tftp.sh [Mode Choose]
```

参数[Mode Choose]为./sd2tftp.sh的输入参数，其值为0或1；
当参数[Mode Choose]为0时，运行S2T模式，S2T模式为将sdcard刷机包转换为tftp刷机包；
当参数[Mode Choose]为1时，运行T2S模式，T2S模式为将tftp刷机包转换为sdcard刷机包；

3. 执行成功后的刷机包会生成在output文件夹下。

## tftp刷机方法

SE5 的 u-boot 也支持通过以太网和tftp协议刷机。刷机步骤如下：

注意：
1. tftp 使用的刷机包与 SD 卡刷机使用的刷机包是不同的；
2. tftp刷机方法仅支持从SDKv22.09.02升级到以上版本。

### 1. 获取tftp刷机包
可以参照上文自行制作，也可以从 https://developer.sophgo.com/site/index/material/all/all.html 下载。其中v22.09.02之后版本的SOPHONSDK `sophon-img_<date>_<hash>` 文件夹中提供了 tftp.tgz 文件。

### 2. 在PC上安装tftp server，并指定tftp刷机包路径
- Ubuntu系统：运行：`apt-get install tftpd-hpa tftp-hpa`，下载tftp工具；然后查看`/etc/default/tftpd-hpa`文件中的`TFTP DIRECTORY`路径，将刷机包拷贝进去（您也可以修改这个路径配置，`sudo service tftpd-hpa restart`后即可生效）；
- windows系统：点击链接下载 https://pjo2.github.io/tftpd64/ ，随后打开下载好的 tftpd64.exe 图形界面，并将 Current Directory 设置指向tftp刷机包解压后的文件夹。

注意：
1. 使用的 PC 推荐尽可能使用 Ubuntu 系统，Windows 下的 tftpd64 对环境比较挑剔，在传输大文件时有时会不稳定，造成升级失败。
2. tftp server 搭建好后，您可以用另一台 PC 先测试一下，避免网络、防火墙等配置问题。

### 3. 搭建基础网络环境
将需要升级的设备和 PC 机放在同一个路由器下（也可以通过设备LAN口直连PC）。

### 4. 执行刷机步骤
a. 将需要升级的设备接上串口终端，启动盒子，快速按回车，进入uboot指令模式；

b. 输入如下指令：
```bash
setenv serverip 192.168.150.2
setenv ipaddr 192.168.150.1
setenv gatewayip 192.168.150.2
setenv update_all 0
setenv reset_after 1
tftp 0x310000000 boot.scr
source 0x310000000
set netretry yes
```

注意：
指令中的serverip为tftp服务器地址，ipaddr为盒子的ip地址，gatewayip为网关地址，需要根据实际情况进行调整；
在window使用场景下，通常是使用盒子的lan口和PC端进行连接，此时serverip和gatewayip是相同的；
用户可以在执行tftp指令之前先ping一下serverip，确认一下连接状态。

c. 随后开始刷机，您会看到#号表示的进度。

d. 由于通过指令配置了环境变量`reset_after 1`，在刷机完成后系统将会重新启动。同时，指令`set netretry yes`将传输超时后进行重试，而非直接重新启动设备。需要注意的是，如果刷机失败，系统同样会自动重启。请根据执行结束后的提示来判断刷机是否成功完成。

# BM1684(X)_to_BM1688(CV186AH)兼容性文档

该文档面向有一定SOPHONSDK使用经验的用户，它还需丰富和完善，如果您发现了新的问题或有改进建议，可以反馈给我们的工作人员。

## 获取BM1688/CV186AH SOPHONSDK

BM1688/CV186AH的SOPHONSDK与BM1684/BM1684X的SOPHONSDK不是同一套，所以需要另外从官网获取。下载后使用工具解压，可以得到各个模块的安装包、示例程序，SDK目录结构如下：

| 文件夹名 | 备注 |
|---------|------|
| sophon-img | SoC模式安装包等 |
| sophon_media | 支持SOPHON设备硬件加速的多媒体库 |
| tpu-mlir | TPU编译器工具链 |
| tpu-perf | 模型性能和精度验证工具包 |
| sophon-stream | 基于pipeline的高性能推理框架 |
| sophon-demo | 针对单模型或者场景的综合例程 |
| sophon-sail | 对底层接口进行C++/Python API封装的接口库 |
| isp-tools | ISP各个模块的参数调节工具 |
| doc | 各个模块的文档资料合集 |

## 准备BM1688/CV186AH的bmodel

重新编译能在BM1688/CV186AH上运行的bmodel，需要使用能够支持BM1688/CV186AH的tpu-mlir。

一般来说，有以下几个步骤：

### 1. 环境准备
准备一台x86 ubuntu，相应的规格参数，取决于需要编译的模型大小，建议运行内存32GB以上，这样足够编译绝大多数模型。

### 2. 搭建tpu-mlir环境
```bash
# 拉取latest版本docker，目前对应tpuc_dev:v3.2，如果您的环境已经有这个image了，也需要重新执行以下命令。
docker pull sophgo/tpuc_dev:latest 

# 这里将本级目录映射到docker内的/workspace目录,用户需要根据实际情况将demo的目录映射到docker里面
# myname只是举个名字的例子, 请指定成自己想要的容器的名字
docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:latest

# 此时已经进入docker，并在/workspace目录下

# 通过pip下载tpu_mlir，如果下不下来，可以使用清华源加速。
pip install tpu_mlir

# TPU-MLIR在对不同框架模型处理时所需的依赖不同。对于onnx或torch生成的模型文件，使用类似下面命令安装额外的依赖环境:
pip install tpu_mlir[onnx]
pip install tpu_mlir[torch]

# 目前支持五种配置: onnx, torch, tensorflow, caffe, paddle。可使用一条命令安装多个配置，也可直接安装全部依赖环境:
pip install tpu_mlir[onnx,torch]
pip install tpu_mlir[all]
```

### 3. 编译模型
只要将以前的编译命令或脚本中model_deploy.py部分的`--processor`，参数值更改成bm1688/cv186x，其他的部分都不用改动，运行之后就可以获取能在BM1688/CV186AH上运行的bmodel。

### 4. 编译BM1688双核模型
BM1688由两个相同的核组成，支持一个模型的数据切分到两个核上面跑，tpu-mlir model_deploy.py为BM1688新增了`--num_core`参数，如果您想要一个模型跑两个核，可以在model_deploy.py中新增`--num_core 2`参数，这样就编译出来的模型，会由两个核来执行。

### 5. 量化注意事项
以前的calibration_table和qtable均是可以复用的，如果在mlir编译bmodel的过程中出现类似算子不支持的报错，或者量化出来的模型精度不好，再重新生成calibration_table或qtable。

## 准备编译依赖的SDK

如果您使用C++编程，您仍然需要获取sophon-img目录下的libsophon_soc_${x.y.z}/_aarch64.tar.gz和sophon_media目录下的sophon-media-soc_${x.y.z}/_aarch64.tar.gz发布包，作为交叉编译依赖的头文件和库文件。

如果以前有手动链接**bmion/bmjpulite/bmjpuapi/bmvpulite/bmvpuapi/bmvideo/bmvppapi**等库，可以直接去掉，这些库其实并没有暴露接口给用户，它们是供底层调用的。

和BM1684/BM1684X有一点不同的是，目前sophon_media中提供的库还依赖libisp模块，如果您使用BM1688/CV186AH的GeminiSDK1.3以上版本，您还需要做这些操作：

从sdk中获取sophon-img/bsp-debs/目录下的sophon-soc-libisp_${x.y.z}_arm64.deb，然后运行如下命令：
```bash
dpkg -x sophon-soc-libisp_${x.y.z}_arm64.deb sophon-libisp
cp -rf sophon-libisp/opt/sophon/sophon-soc-libisp_${x.y.z}/lib ${soc-sdk} #将libisp的库添加到已有的依赖库中。
```

如果您使用Python编程，那只需要重新编译sophon-sail的.whl安装包，编译流程与之前相同，参考sophon-sail开发指南即可。BM1688 SoC上自带libsophon和sophon_media的runtime。

## SDK版本≥1.7 兼容性适配

BM1688/CV186AH SOPHONSDK 1.7及以上版本，对兼容性问题做了进一步的优化，只需要保证您的代码引入了以下头文件即可。
```cpp
#include <bmcv_api.h>
```

### 头文件改动

1. bmcv_api.h已废弃，兼容性解决办法如下：
```cpp
#if !(BMCV_VERSION_MAJOR > 1)
#include <bmcv_api.h>
#endif
```

### bmcv改动

1. 函数参数变为指针：
```cpp
DECL_EXPORT bm_status_t bm_image_destroy(bm_image image)
```
变为
```cpp
DECL_EXPORT bm_status_t bm_image_destroy(bm_image *image)
```
兼容性解决办法如下：
在公共头文件中添加如下代码：
```cpp
#if BMCV_VERSION_MAJOR > 1
    static inline bm_status_t bm_image_destroy(bm_image& image){
    return bm_image_destroy(&image);
    }
#endif
```

2. 函数名称变化：
```cpp
bm_image_dev_mem_alloc
```
变为
```cpp
bm_image_alloc_dev_mem
```
兼容性解决办法：
在公共头文件中封装一个相同功能的旧接口。

3. 接口名称修正：
```cpp
bm_image_dettach_contiguous_mem
```
修正为
```cpp
bm_image_detach_contiguous_mem
```
兼容性解决办法：
在公共头文件中封装一个相同功能的旧接口。

4. 结构体名称修正
```cpp
bmcv_padding_atrr_t
```
修正为
```cpp
bmcv_padding_attr_t
```
兼容性解决办法：
在公共头文件中添加`typedef bmcv_padding_attr_t bmcv_padding_atrr_t;`。

5. 接口废弃：
```cpp
bmcv_image_crop
```
兼容性解决办法：
1. 使用bmcv_image_vpp_convert来代替。
2. 或者在公共头文件使用bmcv_image_vpp_convert封装一个bmcv_image_crop接口。

## 6. 数据类型废弃

```cpp
DATA_TYPE_EXT_4N_BYTE_SIGNED
DATA_TYPE_EXT_4N_BYTE
```

兼容性解决办法：

1. 4N数据类型在以前的SDK中也很少使用，不建议再使用4N数据类型，改用1N数据类型。

## 7. 内存布局改动导致的接口功能改动

```cpp
bm_image_alloc_dev_mem(heap_id = 2)
bm_image_alloc_dev_mem_heap_mask(heap_mask = 1 << 2)
bm_image_alloc_contiguous_mem_heap_mask(heap_mask = 1 << 2)
```

BM1688/CV186AH上只有两个heap，原来放在heap2的内存需要挪到heap1，否则分配失败。如上接口的heap_id/heap_mask参数需要改为：

```cpp
bm_image_alloc_dev_mem(heap_id = 1)
bm_image_alloc_dev_mem_heap_mask(heap_mask = 1 << 1)
bm_image_alloc_contiguous_mem_heap_mask(heap_mask = 1 << 1)
```

## 8. 暂未支持的接口

```cpp
bmcv_base64_enc()
bmcv_base64_dec()
bmcv_faiss_indexflatIP()
bmcv_nms()
bmcv_nms_ext()
bmcv_fft_1d_create_plan()
bmcv_fft_2d_create_plan()
bmcv_fft_execute()
bmcv_fft_execute_real_input()
bmcv_fft_destroy_plan()
```

## ffmpeg改动

ffmpeg版本从4.1升级到了6.0，由此引入了一些ffmpeg本身的改动，如下：

### 1. 接口废弃

```cpp
av_register_all
```

兼容性解决办法：

1. 去掉
2. 或者封装一个av_register_all

```cpp
avcodec_decode_video2
avcodec_encode_video2
```

兼容性解决办法：

1. 按照ffmpeg文档，改成avcodec_send_packet和avcodec_receive_frame的形式
2. 可以自己封装一个avcodec_decode_video2，参考https://github.com/sophgo/sophon-demo/blob/release/include/ff_decode.hpp
3. 可以自己封装一个avcodec_encode_video2，参考sophon-sail src/internal.h

### 2. 结构体或函数类型变为const

```cpp
struct AVOutputFormat *oformat;
AVInputFormat* av_find_input_format
AVCodec* avcodec_find_decoder
AVOutputFormat* av_guess_format
AVCodec* avcodec_find_decoder_by_name
AVCodec* avcodec_find_decoder_by_name
```

变为

```cpp
const struct AVOutputFormat *oformat
const AVInputFormat* av_find_input_format
const AVCodec* avcodec_find_decoder
const AVOutputFormat* av_guess_format
const AVCodec* avcodec_find_decoder_by_name
const AVCodec* avcodec_find_decoder_by_name
```

兼容性解决办法：

1. 使用const_cast去掉const修饰符

### 3. 结构体成员变量变化

```cpp
AVStream->codec
```

变为

```cpp
AVStream->codecpar
```

兼容性解决办法：

1. avcodec_parameters_to_context重新获取上下文，avcodec_parameters_from_context把上下文内容重新拷贝到流中

## bmlib改动

### 1. 新增接口

```cpp
DECL_EXPORT bm_status_t bm_thread_sync_from_core(bm_handle_t handle, int core_id);
```

功能描述：

可以指定只sync某个核，在每个核各跑一个模型时会用到

### 2. 内存布局改动导致的接口功能改动

```cpp
bm_malloc_device_byte_heap(heap_id = 2)
bm_malloc_device_byte_heap_mask(heap_mask = 1 << 2)
```

BM1688/CV186AH上只有两个heap，原来放在heap2的内存需要挪到heap1，否则分配失败。如上接口的heap_id/heap_mask参数需要改为：

```cpp
bm_malloc_device_byte_heap(heap_id = 1)
bm_malloc_device_byte_heap_mask(heap_mask = 1 << 1)
```

## bmrt改动

### 1. 新增接口

```cpp
DECL_EXPORT bool bmrt_launch_tensor_multi_cores(void *p_bmrt,
                                                const char *net_name,
                                                const bm_tensor_t input_tensors[],
                                                int input_num,
                                                bm_tensor_t output_tensors[],
                                                int output_num,
                                                bool user_mem,
                                                bool user_stmode,
                                                const int *core_list,
                                                int core_num);
```

功能描述：

该接口可以将单核模型指定在不同的核上运行，具体请查看SOPHONSDK的bmruntime接口文档或源码

## 准备BM1688/CV186AH运行环境

BM1688/CV186AH的刷机步骤和BM1684/BM1684X相同，具体可以看相关的产品使用手册，在label-chapter-1章节下载的SDK中，sophon-img/sdcard.tgz文件就是刷机包。

准备好运行环境之后，就可以将编译好的程序拷贝到BM1688/CV186AH SoC上执行了。

## 其他注意事项

1. bmrt、bmcv相关的操作，最好把各自分配的内存隔离开，bmrt需要用到的内存放在heap0（也就是npu heap），bmcv需要用到的内存则放在heap1（也就是vpp heap）

2. 由于BM1688的内存减小，ddr是全interleave的，没有带宽分配问题，因此不再预留vpu heap，多媒体模块共用vpp heap

3. bm1688的sdk目前只把ddr划分成npu、vpp两个heap，查看方法改为：

```bash
sudo cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
sudo cat /sys/kernel/debug/ion/cvi_npu_heap_dump/summary
```

4. 内存布局修改工具：mem-edit-tools

可以兼容BM1688/CV186AH Gemini v1.5以上SDK，vpu heap需要设置为0

# 使用 TPU-MLIR 生成FLOAT BModel

算丰系列智能视觉深度学习处理器平台仅支持BModel模型加速，用户需要首先进行模型迁移，把其他框架下训练好的模型转换为BModel才能在算丰系列智能视觉深度学习处理器上运行。

## TPU-MLIR工具包

TPU-MLIR工具包目前支持的框架有PyTorch、ONNX、TFLite以及Caffe的模型，转换后会生成算丰系列平台支持的BModel模型进行加速，更多的网络层和模型也在持续支持中，具体使用指导方法如下所示：

| 功能 | 使用指导 |
|------|----------|
| 编译PyTorch模型 | Torch |
| 编译ONNX模型 | ONNX |
| 编译TFLite模型 | TFLite |
| 编译Caffe模型 | Caffe |

## 编译ONNX模型

本文通过ONNX框架的例子介绍TPU-MLIR如何转换模型为FP32格式的BModel并部署。开发环境的配置，可以参考TPU-MLIR快速入门手册

本章以 `yolov5s.onnx` 为例，介绍如何编译迁移一个onnx模型至BM1684X 平台运行，其他模型请参考上面表格中的模型使用指导。

该模型来自yolov5的官网：https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx

本节需要如下文件(其中xxxx对应实际的版本信息)：
tpu-mlir_xxxx.tar.gz (tpu-mlir的发布包)

### 加载tpu-mlir

以下操作需要在Docker容器中。关于Docker的使用，请参考TPU-MLIR快速入门手册

```shell
$ tar zxf tpu-mlir_xxxx.tar.gz
$ source tpu-mlir_xxxx/envsetup.sh
```

`envsetup.sh` 会添加以下环境变量：

| 变量名 | 值 | 说明 |
|--------|----|------|
| TPUC_ROOT | tpu-mlir_xxx | 解压后SDK包的位置 |
| MODEL_ZOO_PATH | ${TPUC_ROOT}/../model-zoo | model-zoo文件夹位置，与SDK在同一级目录 |
| REGRESSION_PATH | ${TPUC_ROOT}/regression | regression文件夹的位置 |

`envsetup.sh` 对环境变量的修改内容为：

```shell
export PATH=${TPUC_ROOT}/bin:$PATH
export PATH=${TPUC_ROOT}/python/tools:$PATH
export PATH=${TPUC_ROOT}/python/utils:$PATH
export PATH=${TPUC_ROOT}/python/test:$PATH
export PATH=${TPUC_ROOT}/python/samples:$PATH
export PATH=${TPUC_ROOT}/customlayer/python:$PATH
export LD_LIBRARY_PATH=$TPUC_ROOT/lib:$LD_LIBRARY_PATH
export PYTHONPATH=${TPUC_ROOT}/python:$PYTHONPATH
export PYTHONPATH=${TPUC_ROOT}/customlayer/python:$PYTHONPATH
export MODEL_ZOO_PATH=${TPUC_ROOT}/../model-zoo
export REGRESSION_PATH=${TPUC_ROOT}/regression
```

### 准备工作目录

建立 `model_yolov5s` 目录，注意是与tpu-mlir同级目录；并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

操作如下：

```shell
$ mkdir yolov5s_onnx && cd yolov5s_onnx
$ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
$ cp -rf $TPUC_ROOT/regression/dataset/COCO2017 .
$ cp -rf $TPUC_ROOT/regression/image .
$ mkdir workspace && cd workspace
```

这里的 `$TPUC_ROOT` 是环境变量，对应tpu-mlir_xxxx目录。

### ONNX转MLIR

如果模型是图片输入，在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入，则不需要考虑预处理。
预处理过程用公式表达如下( `x` 代表输入)：

y = (x - mean) × scale

官网yolov5的图片是rgb，每个值会乘以 `1/255` ，转换成mean和scale对应为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216` 。

模型转换命令如下：

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

`model_transform.py` 主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）：

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_name | 是 | 指定模型名称 |
| model_def | 是 | 指定模型定义文件，比如`.onnx`或`.tflite`或`.prototxt`文件 |
| input_shapes | 否 | 指定输入的shape，例如[[1,3,640,640]]；二维数组，可以支持多输入情况 |
| input_types | 否 | 指定输入的类型，例如int32；多输入用,隔开；不指定情况下默认处理为float32 |
| resize_dims | 否 | 原始图片需要resize之后的尺寸；如果不指定，则resize成模型的输入尺寸 |
| keep_aspect_ratio | 否 | 在Resize时是否保持长宽比，默认为false；设置时会对不足部分补0 |
| mean | 否 | 图像每个通道的均值，默认为0.0,0.0,0.0 |
| scale | 否 | 图片每个通道的比值，默认为1.0,1.0,1.0 |
| pixel_format | 否 | 图片类型，可以是rgb、bgr、gray、rgbd四种情况，默认为bgr |
| channel_format | 否 | 通道类型，对于图片输入可以是nhwc或nchw，非图片输入则为none，默认为nchw |
| output_names | 否 | 指定输出的名称，如果不指定，则用模型的输出；指定后用该指定名称做输出 |
| test_input | 否 | 指定输入文件用于验证，可以是图片或npy或npz；可以不指定，则不会正确性验证 |
| test_result | 否 | 指定验证后的输出文件 |
| excepts | 否 | 指定需要排除验证的网络层的名称，多个用,隔开 |
| mlir | 是 | 指定输出的mlir文件名称和路径 |

转成mlir文件后，会生成一个 `${model_name}_in_f32.npz` 文件，该文件是模型的输入文件。

# 将mlir文件转换成f32的bmodel, 操作方法如下:

```shell
$ model_deploy.py \
     --mlir yolov5s.mlir \
     --quantize F32 \
     --processor bm1684x \
     --test_input yolov5s_in_f32.npz \
     --test_reference yolov5s_top_outputs.npz \
     --tolerance 0.99,0.99 \
     --model yolov5s_1684x_f32.bmodel
```

`model_deploy.py` 的主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）:

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定mlir文件 |
| quantize | 是 | 指定默认量化类型, 支持F32/F16/BF16/INT8 |
| processor | 是 | 指定模型将要用到的平台, 支持bm1684x/bm1684/cv183x/cv182x/cv181x/cv180x |
| calibration_table | 否 | 指定校准表路径, 当存在INT8量化的时候需要校准表 |
| tolerance | 否 | 表示 MLIR 量化后的结果与 MLIR fp32推理结果相似度的误差容忍度 |
| test_input | 否 | 指定输入文件用于验证, 可以是图片或npy或npz; 可以不指定, 则不会正确性验证 |
| test_reference | 否 | 用于验证模型正确性的参考数据(使用npz格式)。其为各算子的计算结果 |
| compare_all | 否 | 验证正确性时是否比较所有中间结果, 默认不比较中间结果 |
| excepts | 否 | 指定需要排除验证的网络层的名称, 多个用,隔开 |
| model | 是 | 指定输出的model文件名称和路径 |

编译完成后, 会生成名为 `yolov5s_1684x_f32.bmodel` 的文件。

> 具体部署及测试方法，请参考 5.1.3.7模型性能测试。

# 使用 TPU-MLIR 进行模型量化

目前直接支持的框架有Pytorch、ONNX、TFLite和Caffe。其他框架的模型需要转换成onnx模型，再执行后续操作步骤。如何将其他深度学习架构的网络模型转换成onnx, 可以参考onnx官网: https://github.com/onnx/tutorials。

转模型需要在指定的docker执行, 主要分两步, 第一步是通过 `model_transform.py` 将原始模型 转换成mlir文件, 第二步是通过 `model_deploy.py` 将mlir文件转换成bmodel。

如果要转INT8模型, 则需要调用 `run_calibration.py` 生成校准表, 然后传给 `model_deploy.py`。

此外，如果INT8模型不满足精度需要, 可以调用 `run_qtable.py` 生成量化表, 用来决定哪些层采用浮点计算， 然后传给 `model_deploy.py` 生成混精度模型。

> **总而言之，生成int8量化模型，通常需要以下步骤：**
>
> 1. 将模型转换为mlir格式的model文件；
> 2. 利用上述mlir格式的model文件生成校准表；
> 3. 最后再生成int8 bmodel；

> 目前MLIR已支持Pytorch、ONNX、TFLite和Caffe框架，更多网络层和模型也在持续支持中，具体步骤请参考以下使用指导：
>
> | 功能 | 使用指导 |
> |------|----------|
> | 编译PyTorch模型 | Torch |
> | 编译ONNX模型 | ONNX |
> | 编译TFLite模型 | TFLite |
> | 编译Caffe模型 | Caffe |

## 5.3.1 编译ONNX模型

本文通过ONNX框架的例子介绍TPU-MLIR如何转换模型为INT8的格式并部署。开发环境的配置，可以参考 TPU-MLIR快速入门手册

> 本章以 `yolov5s.onnx` 为例, 介绍如何编译迁移一个onnx模型至BM1684X 智能视觉深度学习处理器平台运行，其他模型请参考上面表格中的 `模型使用指导`。
>
> 该模型来自yolov5的官网: 
> https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
>
> 本节需要如下文件(其中xxxx对应实际的版本信息):
> tpu-mlir_xxxx.tar.gz (tpu-mlir的发布包)

### 加载tpu-mlir

以下操作需要在Docker容器中。关于Docker的使用, 请参考 TPU-MLIR快速入门手册

```shell
$ tar zxf tpu-mlir_xxxx.tar.gz
$ source tpu-mlir_xxxx/envsetup.sh
```

`envsetup.sh` 会添加以下环境变量:

| 变量名 | 值 | 说明 |
|--------|----|------|
| TPUC_ROOT | tpu-mlir_xxx | 解压后SDK包的位置 |
| MODEL_ZOO_PATH | ${TPUC_ROOT}/../model-zoo | model-zoo文件夹位置, 与SDK在同一级目录 |
| REGRESSION_PATH | ${TPUC_ROOT}/regression | regression文件夹的位置 |

`envsetup.sh` 对环境变量的修改内容为:

```shell
export PATH=${TPUC_ROOT}/bin:$PATH
export PATH=${TPUC_ROOT}/python/tools:$PATH
export PATH=${TPUC_ROOT}/python/utils:$PATH
export PATH=${TPUC_ROOT}/python/test:$PATH
export PATH=${TPUC_ROOT}/python/samples:$PATH
export PATH=${TPUC_ROOT}/customlayer/python:$PATH
export LD_LIBRARY_PATH=$TPUC_ROOT/lib:$LD_LIBRARY_PATH
export PYTHONPATH=${TPUC_ROOT}/python:$PYTHONPATH
export PYTHONPATH=${TPUC_ROOT}/customlayer/python:$PYTHONPATH
export MODEL_ZOO_PATH=${TPUC_ROOT}/../model-zoo
export REGRESSION_PATH=${TPUC_ROOT}/regression
```

### 准备工作目录

建立 `model_yolov5s` 目录, 注意是与tpu-mlir同级目录; 并把模型文件和图片文件都放入 `model_yolov5s` 目录中。

操作如下:

```shell
$ mkdir yolov5s_onnx && cd yolov5s_onnx
$ wget https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5s.onnx
$ cp -rf $TPUC_ROOT/regression/dataset/COCO2017 .
$ cp -rf $TPUC_ROOT/regression/image .
$ mkdir workspace && cd workspace
```

这里的 `$TPUC_ROOT` 是环境变量, 对应tpu-mlir_xxxx目录。

### ONNX转MLIR

如果模型是图片输入, 在转模型之前我们需要了解模型的预处理。如果模型用预处理后的npz文件做输入, 则不需要考虑预处理。
预处理过程用公式表达如下( $x$ 代表输入):

$$ y = (x - mean) \times scale $$

官网yolov5的图片是rgb, 每个值会乘以 `1/255` , 转换成mean和scale对应为 `0.0,0.0,0.0` 和 `0.0039216,0.0039216,0.0039216` 。

模型转换命令如下:

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

`model_transform.py` 主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）:

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| model_name | 是 | 指定模型名称 |
| model_def | 是 | 指定模型定义文件, 比如`.onnx`或`.tflite`或`.prototxt`文件 |
| input_shapes | 否 | 指定输入的shape, 例如[[1,3,640,640]]; 二维数组, 可以支持多输入情况 |
| input_types | 否 | 指定输入的类型, 例如int32; 多输入用,隔开; 不指定情况下默认处理为float32 |
| resize_dims | 否 | 原始图片需要resize之后的尺寸; 如果不指定, 则resize成模型的输入尺寸 |
| keep_aspect_ratio | 否 | 在Resize时是否保持长宽比, 默认为false; 设置时会对不足部分补0 |
| mean | 否 | 图像每个通道的均值, 默认为0.0,0.0,0.0 |
| scale | 否 | 图片每个通道的比值, 默认为1.0,1.0,1.0 |
| pixel_format | 否 | 图片类型, 可以是rgb、bgr、gray、rgbd四种情况, 默认为bgr |
| channel_format | 否 | 通道类型, 对于图片输入可以是nhwc或nchw, 非图片输入则为none, 默认为nchw |
| output_names | 否 | 指定输出的名称, 如果不指定, 则用模型的输出; 指定后用该指定名称做输出 |
| test_input | 否 | 指定输入文件用于验证, 可以是图片或npy或npz; 可以不指定, 则不会正确性验证 |
| test_result | 否 | 指定验证后的输出文件 |
| excepts | 否 | 指定需要排除验证的网络层的名称, 多个用,隔开 |
| mlir | 是 | 指定输出的mlir文件名称和路径 |

转成mlir文件后, 会生成一个 `${model_name}_in_f32.npz` 文件, 该文件是模型的输入文件。

### MLIR转F16模型

> **BM1684** 平台不支持F16、BF16模型。完整支持细节请参见各设备产品手册。

将mlir文件转换成f16的bmodel, 操作方法如下:

```shell
$ model_deploy.py \
    --mlir yolov5s.mlir \
    --quantize F16 \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --model yolov5s_1684x_f16.bmodel
```

`model_deploy.py` 的主要参数说明如下（完整介绍请参见TPU-MLIR开发参考手册用户界面章节）:

| 参数名 | 必选？ | 说明 |
|--------|--------|------|
| mlir | 是 | 指定mlir文件 |
| quantize | 是 | 指定默认量化类型, 支持F32/F16/BF16/INT8 |
| processor | 是 | 指定模型将要用到的平台, 支持bm1684x/bm1684/cv183x/cv182x/cv181x/cv180x |
| calibration_table | 否 | 指定校准表路径, 当存在INT8量化的时候需要校准表 |
| tolerance | 否 | 表示 MLIR 量化后的结果与 MLIR fp32推理结果相似度的误差容忍度 |
| test_input | 否 | 指定输入文件用于验证, 可以是图片或npy或npz; 可以不指定, 则不会正确性验证 |
| test_reference | 否 | 用于验证模型正确性的参考数据(使用npz格式)。其为各算子的计算结果 |
| compare_all | 否 | 验证正确性时是否比较所有中间结果, 默认不比较中间结果 |
| excepts | 否 | 指定需要排除验证的网络层的名称, 多个用,隔开 |
| model | 是 | 指定输出的model文件名称和路径 |

编译完成后, 会生成名为 `yolov5s_1684x_f16.bmodel` 的文件。

### MLIR转INT8模型

#### 生成校准表

转INT8模型前需要跑calibration, 得到校准表; 输入数据的数量根据情况准备100~1000张左右。

然后用校准表, 生成对称或非对称bmodel。如果对称符合需求, 一般不建议用非对称, 因为非对称的性能会略差于对称模型。

这里用现有的100张来自COCO2017的图片举例, 执行calibration:

```shell
$ run_calibration.py yolov5s.mlir \
    --dataset ../COCO2017 \
    --input_num 100 \
    -o yolov5s_cali_table
```

运行完成后会生成名为 `yolov5s_cali_table` 的文件, 该文件用于后续编译INT8模型的输入文件。

#### 编译为INT8对称量化模型

转成INT8对称量化模型, 执行如下命令:

```shell
$ model_deploy.py \
    --mlir yolov5s.mlir \
    --quantize INT8 \
    --calibration_table yolov5s_cali_table \
    --processor bm1684x \
    --test_input yolov5s_in_f32.npz \
    --test_reference yolov5s_top_outputs.npz \
    --tolerance 0.85,0.45 \
    --model yolov5s_1684x_int8_sym.bmodel
```

编译完成后, 会生成名为 `yolov5s_1684x_int8_sym.bmodel` 的文件。

### 效果对比

在本发布包中有用python写好的yolov5用例, 源码路径 `$TPUC_ROOT/python/samples/detect_yolov5.py` , 用于对图片进行目标检测。阅读该代码可以了解模型是如何使用的: 先预处理得到模型的输入, 然后推理得到输出, 最后做后处理。用以下代码分别来验证onnx/f16/int8的执行结果。

onnx模型的执行方式如下, 得到 `dog_onnx.jpg` :

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model ../yolov5s.onnx \
    --output dog_onnx.jpg
```

f16 bmodel的执行方式如下, 得到 `dog_f16.jpg` :

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model yolov5s_1684x_f16.bmodel \
    --output dog_f16.jpg
```

int8对称bmodel的执行方式如下, 得到 `dog_int8_sym.jpg` :

```shell
$ detect_yolov5.py \
    --input ../image/dog.jpg \
    --model yolov5s_1684x_int8_sym.bmodel \
    --output dog_int8_sym.jpg
```

由于运行环境不同, 最终的效果和精度与 yolov5s_result 会有些差异。

# 模型性能测试

以下操作需要在Docker外执行。

## 安装 libsophon 环境

请参考 libsophon使用手册安装 `libsophon`。

## 检查 BModel 的性能

安装好 `libsophon` 后，可以使用 `bmrt_test` 来测试编译出的 `bmodel` 的正确性及性能。可以根据 `bmrt_test` 输出的性能结果，来估算模型最大的fps，来选择合适的模型。

```shell
# 下面测试上面编译出的bmodel
# --bmodel参数后面接bmodel文件

$ cd $TPUC_ROOT/../model_yolov5s/workspace
$ bmrt_test --bmodel yolov5s_1684x_f16.bmodel
$ bmrt_test --bmodel yolov5s_1684x_int8_sym.bmodel
```

以最后一个命令输出为例(此处对日志做了部分截断处理):

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
[BMRT][bmrt_test:1014] INFO:net[yolov5s] stage[0], launch total time is 4122 us
[BMRT][bmrt_test:1017] INFO:+++ The network[yolov5s] stage[0] output_data +++
[BMRT][print_array:702] INFO:output data #0 shape: [1 3 80 80 85 ] < 0.301003    ...
[BMRT][print_array:702] INFO:output data #1 shape: [1 3 40 40 85 ] < 0 0.228689  ...
[BMRT][print_array:702] INFO:output data #2 shape: [1 3 20 20 85 ] < 1.00135     ...
[BMRT][bmrt_test:1058] INFO:load input time(s): 0.008914
[BMRT][bmrt_test:1059] INFO:calculate  time(s): 0.004132
[BMRT][bmrt_test:1060] INFO:get output time(s): 0.012603
[BMRT][bmrt_test:1061] INFO:compare    time(s): 0.006514
```

从上面输出可以看到以下信息:

1. 05-08行是bmodel的网络输入输出信息
2. 19行是在智能视觉深度学习处理器上运行的时间，其中智能视觉深度学习处理器用时4009us，central processing unit用时113us。这里central processing unit用时主要是指在HOST端调用等待时间
3. 24行是加载数据到NPU的DDR的时间
4. 25行相当于12行的总时间
5. 26行是输出数据取回时间

# 快速跑通SoC模式

BModel模型的编译量化：需要在一台x86主机上按照指引配置docker环境，在docker环境内进行模型的编译量化。

BModel模型验证：需要将编译好的bmodel拷贝至SoC设备上运行验证。

程序的交叉编译：x86主机系统建议使用Ubuntu16.04~20.04。按照本章指引在x86主机上安装libsophon、sophon-mw，进行程序的交叉编译，待程序编译好后，您需要手动将编译好的程序拷贝到目标SoC中执行。

算法的应用部署：可直接在SoC设备上执行程序。

## 开发环境

按照如下步骤搭建环境：

1. 一台安装了Ubuntu16.04/18.04/20.04/22.04的x86主机，运行内存建议12GB以上
2. 下载SOPHONSDK开发包 SDK下载页面
3. 解压SDK压缩包

```bash
sudo apt-get install p7zip
sudo apt-get install p7zip-full
7z x Release_<date>-public.zip  # <date>指日期
cd Release_<date>-public
```

4. 随后进行 tpu-mlir 环境搭建：

### tpu-mlir 环境搭建

请阅读 SDK资料中心 的《TPU-MLIR快速入门手册》搭建环境，或直接阅读GitHub的MLIR文档 MLIR Assets。
如下为简要步骤参考：

1. 安装docker

```bash
# 安装docker，或者参考docker官方教程
sudo apt-get install docker.io
sudo systemctl start docker
sudo systemctl enable docker
# docker命令免root权限执行
# 创建docker用户组，若已有docker组会报错，可忽略
sudo groupadd docker
# 将当前用户加入docker组
sudo usermod -aG docker $USER
# 重启docker服务
sudo service docker restart
# 切换当前会话到新group或重新登录重启会话
newgrp docker
```

2. 创建docker容器并进入。 **TPU-MLIR使用的docker镜像和tpu-mlir有绑定关系，最新的镜像请参考《TPU-MLIR快速入门手册》**

```bash
cd tpu-mlir
#请参考《TPU-MLIR快速入门手册》拉取最新的镜像文件
#此处将tpu-mlir的当前目录映射到docker内的/workspace目录
#myname只是举个名字的例子, 请指定成自己想要的容器的名字
docker run --privileged --name myname -v $PWD:/workspace -it sophgo/tpuc_dev:latest
```

3. 安装tpu-mlir ：

通过pip安装:

进入docker环境后安装pip及其依赖，有在线安装和离线安装两种方式。tpu_mlir在对不同框架模型处理时所需的依赖不同，在线安装和离线安装方式都需要安装额外依赖。

1. 在线安装：直接从pypi源下载并安装，默认为最新版。依赖环境支持 onnx, torch, tensorflow, caffe, paddle

```bash
# 安装tpu_mlir
pip install tpu_mlir

# 安装onnx依赖
pip install tpu_mlir[onnx] # torch, tensorflow, caffe, paddle
# 安装全部依赖
pip install tpu_mlir[all]
```

2. 离线安装：从Github的 MLIR Assets 处下载最新的 `tpu_mlir-*-py3-none-any.whl`，然后使用pip安装。离线安装方式也需要安装额外的依赖环境。

```bash
# 安装tpu-mlir
pip install tpu_mlir-*-py3-none-any.whl

# 安装onnx依赖
pip install tpu_mlir-*-py3-none-any.whl[onnx] # torch, tensorflow, caffe, paddle
# 安装全部依赖
pip install tpu_mlir-*-py3-none-any.whl[all]
```

## 运行环境

1. 对于SoC平台，内部已经集成了相应的libsophon、sophon-opencv和sophon-ffmpeg运行库包，位于/opt/sophon/下。若您需要python环境中的sophon-opencv 还需设置环境变量。

```bash
# 设置环境变量
export PYTHONPATH=$PYTHONPATH:/opt/sophon/sophon-opencv_<x.y.z>/opencv-python
```

2. 若您需要使用python/c++ SAIL库，您还需要安装sophon-sail.whl，否则可跳过:

1. 需从算能官网上下载符合环境依赖的SDK，找到sophon-sail压缩包，命名如sophon-sail_x.y.z.tar.gz，x.y.z表示版本号。

2. 若您需要python库，您可以使用SDK中编译好的whl直接安装：

```bash
# 解压sail压缩包
tar -xvf sophon-sail_x.y.z.tar.gz
# 进入sail目录，<arch>指您需要选择当前需要安装的平台
cd sophon-sail/python_wheels/<arch>
# 查看当前设备libsophon sophonmw 版本 
ll /opt/sophon
# 选择当前设备libsophon sophonmw 对应版本的文件夹，进入文件夹
cd libsophon-<x.y.z>_sophonmw-<x.y.z>
# 选择当前设备python版本，安装sophon-sail
pip install py<xy>/sophon-sail-<x.y.z>-py3-none-any.whl
```

3. 若您需要c++库，您可以打开sophon-sail压缩包里面提供的用户手册(命名为sophon-sail_zh.pdf)，或者打开在线链接 SOPHON-SAIL用户手册 ，参考编译安装指南章节，选择您需要的模式(C++/Python，PCIe/SoC MODE)进行安装。

## SoC模式跑通Yolov5

按照上述步骤搭建环境后，请尝试跑通 SOPHON-DEMO YOLOv5 例程。

# 快速跑通PCIe模式

**注意：** 若您使用非x86架构的主机进行开发，模型转换还需要使用一台x86主机完成，开发及部署可以直接在裸机上进行。若有问题，请联系我们获取技术支持。

本教程后续的操作若无特殊说明，均是在x86主机上的ubuntu开发环境中。

BModel模型的编译量化：可按照指引配置docker环境，在docker环境中进行模型的编译量化。

BModel模型验证：需要在插有PCIe加速卡的主机中运行验证。

程序编译：本章假设您的开发环境和运行环境为同一架构。需要依次在开发环境中安装libsophon、sophon-mw，随后进行程序编译。

算法的应用部署：按照本章指引依次在运行环境中安装libsophon、sophon-mw；您也可以添加您需要的库包以及其他程序代码，构建您自己的生产环境。

## 开发环境

按照如下步骤搭建环境：

1. 一台安装了Ubuntu16.04/18.04/20.04/22.04的x86主机，运行内存建议12GB以上
2. 下载SOPHONSDK开发包 SDK下载页面 。请注意后续步骤适用SDK为Release\_<date>-public.zip，其中<date>为SDK Release 日期，会随着SDK的升级而不断变化。
3. 解压SDK压缩包

```bash
sudo apt-get install p7zip
sudo apt-get install p7zip-full
7z x Release_<date>-public.zip  # <date>指日期
cd Release_<date>-public
```

4. 随后依次进行 tpu-mlir 环境搭建，libsophon环境搭建，sophon-mw 环境搭建

### tpu-mlir 环境搭建

tpu-mlir 环境搭建

### libsophon环境搭建

**注意：**

libsophon 在不同的Linux发行版上提供不同类型的安装方式，请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。

1. 如果您安装的是V2.7.0，V3.0.0下BM1684 SDK的驱动，请先卸载旧的BM1684 SDK的驱动，请参考如下步骤；若您安装的是V22.xx.xx或者V23.xx.xx的SDK，请参考《 libsophon使用手册 》卸载旧驱动。

```bash
# 进入SDK安装目录下的scripts文件夹，执行
sudo ./remove_driver_pcie.sh
```

2. 如果您使用的是Debian/Ubuntu系统，安装包由三个文件构成：sophon-driver\_<x.y.z>_$arch.deb、sophon-libsophon\_<x.y.z>_$arch.deb、sophon-libsophon-dev\_<x.y.z>_$arch.deb

**注意：**

其中，<x.y.z> 指版本号，$arch 指当前机器的硬件架构，使用如下命令可获取当前服务器的arch。通常x86_64机器对应的硬件架构是amd64，arm64机器对应的硬件架构是arm64。请选择您对应的安装文件进行安装。

```bash
uname -m
```

可参考如下步骤进行安装：

```bash
cd libsophon_<date>_<hash>
# 安装依赖库，只需要执行一次
sudo apt install dkms libncurses5
sudo dpkg -i sophon-*.deb
# 在终端执行如下命令，或者log out再log in当前用户后即可使用bm-smi等命令
source /etc/profile
```

**注意：**

**检查驱动是否安装成功：**

执行 `ls /dev/bm*` 看看是否有 /dev/bm-sohponX （X表示0-N），如果有表示安装成功。正常情况下输出如下信息：

/dev/bmdev-ctl /dev/bm-sophon0

3. 如果您使用其它Linux系统，安装包只由一个文件构成：libsophon\_<x.y.z>_$arch.tar.gz，可参考《 libsophon使用手册 》进行安装。

其他疑问请参考《 libsophon使用手册 》

### sophon-mw 环境搭建

**在安装sophon-mw时，请确保已经安装libsophon**

1. 如果您使用的是Debian/Ubuntu系统，安装包由四个文件构成，分别为：sophon-mw-sophon-ffmpeg\_<x.y.z>_$arch.deb、sophon-mw-sophon-ffmpeg-dev\_<x.y.z>_$arch.deb、sophon-mw-sophon-opencv\_<x.y.z>_$arch.deb、sophon-mw-sophon-opencv-dev\_<x.y.z>_$arch.deb，请选择您对应的安装文件参考如下步骤进行安装：

```bash
cd sophon-mw_<date>_<hash>
# 必须先安装sophon-mw-sophon-ffmpeg，再安装sophon-mw-sophon-opencv
sudo dpkg -i sophon-mw-sophon-ffmpeg_<x.y.z>_*.deb sophon-mw-sophon-ffmpeg-dev_<x.y.z>_*.deb
sudo dpkg -i sophon-mw-sophon-opencv_<x.y.z>_*.deb sophon-mw-sophon-opencv-dev_<x.y.z>_*.deb
# 在终端执行如下命令，或者log out再log in当前用户后即可使用安装的工具
source /etc/profile
```

## sophon-sail 环境搭建

若您需要使用SAIL库，您还需要编译安装sophon-sail，否则可跳过本章节。

1. 需从算能官网上下载符合环境依赖的SDK，里面有sophon-sail的压缩包，命名如sophon-sail_x.y.z.tar.gz，x.y.z表示版本号。

2. 您可以打开sophon-sail压缩包里面提供的用户手册(命名为sophon-sail_zh.pdf)，或者打开在线链接 |SOPHON-SAIL用户手册| ，参考编译安装指南章节，选择您需要的模式(C++/Python，PCIe MODE)进行安装。

## 运行环境

按照如下步骤搭建环境：

1. 首先您需要将PCIe加速卡插到x86主机中，随后检查PCIe加速卡能否正常被系统识别：

   打开终端执行 `lspci | grep 168` 检查卡是否能够被识别。正常情况下应该输出如下信息：

   ```bash
   01:00.0 Processing accelerators: SOPHGO Technologies Inc. BM1684X, SOPHON Series Deep Learning Accelerator (rev 01)
   ```

   若PCIe加速卡没有被系统正常识别，则需要首先排除故障，通常引起PCIe加速卡未被正常识别的可能原因有：

   - PCIe加速卡在插糟中没有插紧；
   - 检查插卡的槽位是否是标准的X16槽位，X8槽位的功率支持通常最大只有45W，不建议使用；
   - PCIe加速卡从PCIe直接供电，不需要外接电源，若连接了外接电源，可能导致卡不能被正常识别；
   - 搭载三块BM1684/BM1684X以上PCIe加速卡需要足够的散热条件，若风道和风量不能符合PCIe加速卡的被动散热要求，则需要通过BIOS将风扇转速设置到足够大或者加装额外的风扇进行散热。

2. 下载SOPHONSDK开发包。请注意后续步骤适用SDK为Release_<date>-public.zip，其中<date>为SDK Release 日期，会随着SDK的升级而不断变化。

3. 解压SDK压缩包

   ```bash
   sudo apt-get install p7zip
   sudo apt-get install p7zip-full
   7z x Release_<date>-public.zip  # <date>指日期
   cd Release_<date>-public
   ```

4. 按照上述 libsophon环境搭建、sophon-mw环境搭建步骤，依次安装环境

5. 若您需要使用SAIL库，您还需要编译安装sophon-sail

## PCIe模式跑通Yolov5

按照上述步骤搭建环境后，请尝试跑通 |SOPHON-DEMO YOLOv5| 例程。

## SDK移植开发综述

BM1688/CV186AH 仅支持SoC模式。

## SDK学习路线

建议首次接触SOPHONSDK时，按照上图所示的学习路线进行模型移植和算法开发。

|SOPHON-DEMO YOLOv5| ，通过跑通此例程，您可以快速熟悉MLIR工具链及模型调用流程。

## 算法移植流程

基于SOPHON BM168X进行产品开发会经历如下几个阶段：

1. **评测选型：** 根据应用场景，确定使用的产品形态。

2. **模型迁移：** 将原始深度学习框架下训练生成的模型转换为BM168X平台运行的FP32 BModel，必要时使用BMLang开发不支持的算子；使用量化集量化生成INT8 BModel，并测试调优确保INT8 BModel精度符合要求（推荐使用4N Batch BModel以获得最佳性能）。

3. **算法移植：** 基于BM168X硬件加速接口，对模型的前后处理及推理现有算法进行移植。

4. **程序移植：** 移植任务管理、资源调度等算法引擎代码及逻辑处理、结果展示、数据推送等业务代码。

5. **测试调优：** 网络性能与精度测试、压力测试，基于网络编译、量化工具、多卡多芯、任务流水线等方面的深度优化。

6. **部署联调：** 将算法服务打包部署到BM168X硬件产品上，并在实际场景中与业务平台或集成平台进行功能联调；必要时在生产环境中调整参数配置并收集数据进一步优化模型。

在移植工作开始前，请先确保已经按照快速入门内容下载并安装配置好所需环境，确认sophon-demo中的示例能成功运行。

## 典型视频深度学习分析任务

一个典型的深度学习视频分析任务pipeline，通常包括：视频源 > 视频解码 > 预处理 > 推理 > 后处理 > 业务逻辑 > 视频/图片编码等环节。SOPHON设备对各环节的硬件加速支持情况如下：

| **算法步骤**    | **支持硬件加速** | **sophon-OpenCV** | **sophon-FFmpeg** | **Native接口**    |
|-----------------|------------------|-------------------|-------------------|-------------------|
| 视频/图片编解码 | 支持             | Y                 | Y                 | BMCV（图片）/SAIL |
| 输入预处理      | 支持             | Y                 | N                 | BMCV/SAIL         |
| 模型推理        | 支持             | N                 | N                 | BMRuntime/SAIL    |
| 输出后处理      | 部分支持         | N                 | N                 | BMCV              |

- MLIR模型支持情况和测试的模型案例，请参见《 |TPU-MLIR开发参考手册| 》
- 关于单模型或场景的例程可参考sophon-demo，关于使用多线程构建多模型推理任务pipeline示例代码可参考sophon-stream，sophon-pipeline
- 对于其他需要使用智能视觉深度学习处理器加速的算法可使用基于智能视觉深度学习处理器原子操作接口的 TPUKernel 开发，参考《 |TPUKernel用户开发文档| 》
- 对于不支持的层或者算子可以自行开发，然后融合到BModel中，详情请联系技术支持

## 常用样例

我们提供了模型转换及量化样例程序、多媒体相关样例程序、以及涵盖图像分类、目标检测、图像分割、文本检测识别等领域的单个模型算法移植样例程序，具体如下：

1. 《 |TPU-MLIR快速入门手册| 》提供了模型转换与量化样例；

2. SOPHONSDK中 |sophon-demo| 提供了 |CenterNet|、 |LPRNet|、 |PP-OCR|、 |ResNet|、 |RetinaFace|、 |SSD|、 |yolact|、 |YOLOv3/v4|、 |YOLOv5|、 |YOLOX| 等模型的推理样例程序；

3. SOPHONSDK中 |sophon-stream| 提供了基于C++11的支持多路数据流并发处理的流水线框架。基于现有的接口，SOPHON-STREAM 对用户具有易使用、易二次开发的优点，可以大大简化用户配置工程或添加插件的复杂度；

4. SOPHONSDK中 |sophon-pipeline| 提供了一个基于pipeline的（包含推流和结果展示的）任务构建的样例程序；

## SDK软件包内容简介

- BM1684 & BM1684X SOPHONSDK是算能基于BM1684、BM1684X定制的深度学习SDK;
- BM1688 & CV186AH SOPHONSDK是算能基于BM1688、CV186AH定制的深度学习SDK;

SDK涵盖了神经网络推理阶段所需的模型优化、高效运行支持等能力，为深度学习应用开发和部署提供易用、高效的全栈式解决方案。

## 获取SDK

- |SDK下载页面|

需要根据您当前的产品选择 BM1688/CV186AH 或 BM1684/BM1684X 对应的最新SDK。

- |SDK资料中心|
- |技术论坛|
- |FAQ|

## SDK主要模块

1. 基础工具包

   - **算丰深度学习处理加速库 SAIL** ： 支持Python/C++的高级接口，是对BMRuntime、BMCV、sophon-mw等底层库接口的封装，供用户进行深度学习应用开发。
   - **模型编译量化工具链 TPU-MLIR** ： 为Tensor Processing Unit编译器工程提供一套完整的工具链，可以将不同框架下预训练的神经网络，转化为可以在算能智能视觉深度学习处理器上高效运行的二进制文件BModel。目前直接支持的框架包括torch、tflite、onnx和Caffe等。
   - **硬件驱动及运行库 LIBSOPHON** ： 包含BMCV、BMRuntime、BMLib等库，用来驱动VPP、智能视觉深度学习处理器等硬件，完成图像处理、张量运算、模型推理等操作，供用户进行深度学习应用开发。
   - **多媒体库 SOPHON-MW/SOPHON-MEDIA** : 支持SOPHON设备硬件加速的SOPHON-OpenCV和SOPHON-FFmpeg，用来驱动VPU、JPU等硬件，支持RTSP流、GB28181流的解析，视频及图片的编解码加速等，供用户进行深度学习应用开发。
   - **张量运算及图像处理库 BMCV** ： 色彩空间转换、尺度变换、仿射变换、投射变换、线性变换、画框、JPEG编码、BASE64编码、NMS、排序、特征匹配。
   - **设备管理 BMLib** ： 基础接口：设备Handle的管理，内存管理、数据搬运、API的发送和同步、A53使能等。

2. 快速移植示例和工具包

   - **综合例程 DEMO** |sophon-demo| 提供了x86和SoC环境下针对单模型或场景的综合例程，供用户在深度学习应用开发过程中参考。
   - **数据流处理工具 STREAM**： |sophon-stream| 本软件基于插件化的思想，基于C++11的支持多路数据流并发处理的流水线框架。基于现有的接口，SOPHON-STREAM 对用户具有易使用、易二次开发的优点，可以大大简化用户配置工程或添加插件的复杂度。
   - **高性能推理 PIPELINE** |sophon-pipeline| 提供了一个简易的基于pipeline的高性能推理框架，能够将前处理/推理/后处理分别运行在3个线程上，最大化的实现并行，供用户在深度学习应用开发过程中参考。

3. 高阶工具包

   - **算法并行加速编程库 TPUKernel**：基于SOPHON BM1684、BM1684X底层原子操作接口的底层编程接口，需要用户熟悉设备硬件架构和指令集。
   - **模型性能和精度验证工具 TPUPerf** : 可对模型进行性能分析和精度验证。

## SDK文件目录

SDK提供了多个文件夹模块，具体如下表所示：

| 文件夹名        | 功能描述                                                     |
|-----------------|-------------------------------------------------------------|
| libsophon       | 硬件加速基础库 (图像处理/张量运算/模型推理)、工具            |
| sophon-mw       | BM1684/BM1684X 平台多媒体加速库                              |
| sophon-media    | BM1688/CV186AH 平台多媒体加速库                              |
| sophon-sail     | 对底层模型推理、图像处理API再封装(提供C++/Python API)        |
| tpu-kernel      | Tensor Computing Processor底层开发接口                       |
| tpu-mlir        | MLIR编译器工具链 (模型转换/量化)                             |
| tpu-perf        | 模型性能验证工具 (耗时/精度)                                 |
| sophon-rpc      | 仅BM1684X支持，PCIe模式使用                                  |
| sophon-img      | SoC模式刷机文件                                              |
| sophon-demo     | 模型推理示例程序                                             |
| sophon-pipeline | 流水线式高性能推理样例程序                                   |
| sophon-stream   | 多路流媒体处理框架                                           |

解压后的 BM1688 & CV186AH SDK， BM1684 & BM1684X SDK文件结构分别参考如下：

```
BM1688 & CV186AH SDK v<x.x.0>
├── doc
│   ├── BMLib_Technical_Reference_Manual.pdf
│   ├── BMLIB开发参考手册.pdf
│   ├── LIBSOPHON_User_Guide.pdf
│   ├── LIBSOPHON使用手册.pdf
│   ├── SOPHON BMRuntime Technical Reference Manual.pdf
│   ├── SOPHON-SAIL_en.pdf
│   ├── SOPHON-SAIL_zh.pdf
│   ├── TPU-MLIR_Quick_Start.pdf
│   ├── TPU-MLIR_Technical_Reference_Manual.pdf
│   ├── TPU-MLIR开发参考手册.pdf
│   ├── TPU-MLIR快速入门指南.pdf
│   ├── 算能边缘产品BMCV开发参考手册.pdf
│   ├── 算能边缘产品BMRUNTIME开发参考手册.pdf
│   ├── 算能边缘产品BSP开发参考手册_en.pdf
│   ├── 算能边缘产品BSP开发参考手册.pdf
│   ├── 算能边缘产品MULTIMEDIA常见问题手册.pdf
│   ├── 算能边缘产品MULTIMEDIA开发参考手册.pdf
│   └── 算能边缘产品多媒体使用参考指南.pdf
├── isp_tool
│   └── CviPQtool_<date>.zip
├── sophon-demo
│   ├── release_version.txt
│   ├── sophon-demo.MD5
│   └── sophon-demo_v<x.y.z>_<hash>_<date>.tar.gz
├── sophon-img
│   ├── boot
│   │   ├── boot.itb
│   │   ├── boot.scr.emmc
│   │   ├── fip.bin
│   │   ├── fip_debug.bin
│   │   └── multi.its
│   ├── bsp-debs
│   │   ├── bmssm_soc_<x.y.z>_SDK.deb
│   │   ├── linux-headers-<x.y.z>.deb
│   │   ├── linux-image-<x.y.z>-dbg.deb
│   │   ├── linux-image-<x.y.z>.deb
│   │   ├── linux-libc-dev_<x.y.z>_arm64.deb
│   │   ├── qt5-base.deb
│   │   ├── sophgo-bsp-rootfs_<x.y.z>_arm64.deb
│   │   ├── sophgo-hdmi_<x.y.z>_arm64.deb
│   │   ├── sophliteos_soc_<x.y.z>_sdk.deb
│   │   ├── sophon-media-soc-sophon-ffmpeg_<x.y.z>_arm64.deb
│   │   ├── sophon-media-soc-sophon-opencv_<x.y.z>_arm64.deb
│   │   ├── sophon-media-soc-sophon-sample_<x.y.z>_arm64.deb
│   │   ├── sophon-soc-libisp_<x.y.z>_arm64.deb
│   │   ├── sophon-soc-libisp-dev_<x.y.z>_arm64.deb
│   │   ├── sophon-soc-libsophon_<x.y.z>_arm64.deb
│   │   └── sophon-soc-libsophon-dev_<x.y.z>_arm64.deb
│   ├── doc
│   │   ├── BMLib_Technical_Reference_Manual.pdf
│   │   ├── BMLIB开发参考手册.pdf
│   │   ├── LIBSOPHON_User_Guide.pdf
│   │   ├── LIBSOPHON使用手册.pdf
│   │   ├── SOPHON_BMCV_Technical_Reference_Manual.pdf
│   │   ├── SOPHON BMRuntime Technical Reference Manual.pdf
│   │   ├── 算能边缘产品BMRUNTIME开发参考手册.pdf
│   │   └── 算能边缘产品BSP开发参考手册.pdf
│   ├── libsophon_soc_<x.y.z>_aarch64.tar.gz
│   ├── release_version.txt
│   ├── sdcard.tgz
│   ├── sophon-img-edge-auto.MD5
│   ├── tftp.tgz
│   └── usb.tgz
├── sophon_media
│   ├── doc
│   │   ├── Multimedia_FAQ_en.pdf
│   │   ├── Multimedia_Guide_en.pdf
│   │   ├── Multimedia_Manual_en.pdf
│   │   ├── 算能边缘产品MULTIMEDIA常见问题手册.pdf
│   │   ├── 算能边缘产品MULTIMEDIA开发参考手册.pdf
│   │   └── 算能边缘产品多媒体使用参考指南.pdf
```

```
├── release_version.txt
├── sophon_media.MD5
├── sophon-media-soc_<x.y.z>_aarch64.tar.gz
├── sophon-media-soc-sophon-ffmpeg_<x.y.z>_arm64.deb
├── sophon-media-soc-sophon-ffmpeg-dev_<x.y.z>_arm64.deb
├── sophon-media-soc-sophon-opencv_<x.y.z>_arm64.deb
├── sophon-media-soc-sophon-opencv-dev_<x.y.z>_arm64.deb
└── sophon-media-soc-sophon-sample_<x.y.z>_arm64.deb

├── sophon-sail
│   ├── release_version.txt
│   ├── sophon-sail_3.7.0.tar.gz
│   ├── SOPHON-SAIL_en.pdf
│   ├── sophon-sail.MD5
│   └── SOPHON-SAIL_zh.pdf

├── sophon-stream
│   ├── release_version.txt
│   ├── sophon-stream.MD5
│   └── sophon-stream_v<x.y.z>_<hash>_<date>.tar.gz

├── tpu-mlir
│   ├── tpu_mlir-<x.y.z>-py3-none-any.whl
│   └── tpu-mlir_readme.txt

└── tpu-perf
    ├── tpu_perf-<x.y.z>-py3-none-manylinux2014_aarch64.whl
    └── tpu_perf-<x.y.z>-py3-none-manylinux2014_x86_64.whl

BM1684 & BM1684X SDK v<xx.xx.0>
├── libsophon_<date>_<hash>
│   ├── BMCV_Technical_Reference_Manual.pdf
│   ├── BMCV开发参考手册.pdf
│   ├── BMLib_Technical_Reference_Manual.pdf
│   ├── BMLIB开发参考手册.pdf
│   ├── BMRuntime Technical Reference Manual.pdf
│   ├── BMRUNTIME开发参考手册.pdf
│   ├── libsophon_<x.y.z>_aarch64.tar.gz                           # arm64机器，其他LINUX系统对应的libsophon安装包
│   ├── libsophon_<x.y.z>_x86_64.tar.gz                            # x86_64机器，其他LINUX系统对应的libsophon安装包
│   ├── libsophon_dockerfile
│   ├── libsophon.MD5
│   ├── LIBSOPHON_User_Guide.pdf
│   ├── LIBSOPHON使用手册.pdf
│   ├── release_version.txt
│   ├── sophon-driver_<x.y.z>_amd64.deb                            # x86_64机器，Debian/Ubuntu系统对应的PCIe卡驱动安装文件
│   ├── sophon-driver_<x.y.z>_arm64.deb                            # arm64机器，Debian/Ubuntu系统对应的PCIe卡驱动安装文件
│   ├── sophon-libsophon_<x.y.z>_amd64.deb                         # x86_64机器，Debian/Ubuntu系统对应的libsophon运行时环境安装文件
│   ├── sophon-libsophon_<x.y.z>_arm64.deb                         # arm64机器，Debian/Ubuntu系统对应的libsophon运行时环境安装文件
│   ├── sophon-libsophon-dev_<x.y.z>_amd64.deb                     # x86_64机器，Debian/Ubuntu系统对应的libsophon开发环境安装文件
│   └── sophon-libsophon-dev_<x.y.z>_arm64.deb                     # arm64机器，Debian/Ubuntu系统对应的libsophon开发环境安装文件

├── sophon-demo_<date>_<hash>
│   ├── release_version.txt
│   ├── sophon-demo.MD5
│   └── sophon-demo_v<x.y.z>_b909566_20221027.tar.gz               # 针对单模型或场景的综合例程

├── sophon-img_<date>_<hash>
│   ├── bsp-debs
│   ├── bsp_update.tgz
│   ├── libsophon_soc_<x.y.z>_aarch64.tar.gz                       # 交叉编译所需文件
│   ├── release_version.txt
│   ├── sdcard.tgz                                                 # SoC卡刷包
│   ├── SOPHON_BSP_Technical_Reference_Manual.pdf
│   ├── SOPHON BSP开发参考手册.pdf
│   ├── sophon-img.MD5
│   ├── sophon-soc-libsophon_<x.y.z>_arm64.deb                     # SoC平台对应的libsophon安装文件
│   ├── sophon-soc-libsophon-dev_<x.y.z>_arm64.deb                 # SoC平台对应的libsophon安装文件
│   ├── system.tgz
│   └── tftp.tgz

├── sophon-mw_<date>_<hash>
│   ├── Multimedia FAQ.pdf                                         
│   ├── Multimedia Technical Reference Manual.pdf
│   ├── Multimedia User Guide.pdf
│   ├── MULTIMEDIA使用手册.pdf
│   ├── MULTIMEDIA常见问题手册.pdf
│   ├── MULTIMEDIA开发参考手册.pdf
│   ├── release_version.txt
│   ├── sophon-mw_<x.y.z>_aarch64.tar.gz                          # arm64机器，其他LINUX系统对应的sophon-mw安装包
│   ├── sophon-mw_<x.y.z>_x86_64.tar.gz                           # x86_64机器，其他LINUX系统对应的sophon-mw安装包
│   ├── sophon-mw.MD5
│   ├── sophon-mw-soc_<x.y.z>_aarch64.tar.gz                    
│   ├── sophon-mw-soc-sophon-ffmpeg_<x.y.z>_arm64.deb             # SoC平台，ffmpeg运行时环境安装文件
│   ├── sophon-mw-soc-sophon-ffmpeg-dev_<x.y.z>_arm64.deb         # SoC平台，ffmpeg开发环境安装文件
│   ├── sophon-mw-soc-sophon-opencv_<x.y.z>_arm64.deb             # SoC平台，opencv运行时环境安装文件
│   ├── sophon-mw-soc-sophon-opencv-dev_<x.y.z>_arm64.deb         # SoC平台，opencv开发环境安装文件
│   ├── sophon-mw-soc-sophon-sample_<x.y.z>_arm64.deb             # SoC平台，多媒体程序示例文件
│   ├── sophon-mw-sophon-ffmpeg_<x.y.z>_amd64.deb                 # x86_64机器，Debian/Ubuntu系统对应的ffmpeg运行时环境安装文件
│   ├── sophon-mw-sophon-ffmpeg_<x.y.z>_arm64.deb                 # arm64机器，Debian/Ubuntu系统对应的ffmpeg运行时环境安装文件
│   ├── sophon-mw-sophon-ffmpeg-dev_<x.y.z>_amd64.deb             # x86_64机器，Debian/Ubuntu系统对应的ffmpeg开发环境安装文件
│   ├── sophon-mw-sophon-ffmpeg-dev_<x.y.z>_arm64.deb             # arm64机器，Debian/Ubuntu系统对应的ffmpeg开发环境安装文件
│   ├── sophon-mw-sophon-opencv_<x.y.z>_amd64.deb                 # x86_64机器，Debian/Ubuntu系统对应的opencv运行时环境安装文件
│   ├── sophon-mw-sophon-opencv_<x.y.z>_arm64.deb                 # arm64机器，Debian/Ubuntu系统对应的opencv运行时环境安装文件
│   ├── sophon-mw-sophon-opencv-abi0_<x.y.z>_amd64.deb            # x86_64机器，CenterOS系统对应的opencv运行时环境安装文件
│   ├── sophon-mw-sophon-opencv-abi0_<x.y.z>_arm64.deb            # arm64机器，CenterOS系统对应的opencv运行时环境安装文件
│   ├── sophon-mw-sophon-opencv-abi0-dev_<x.y.z>_amd64.deb        # x86_64机器，CenterOS系统对应的opencv开发环境安装文件
│   ├── sophon-mw-sophon-opencv-abi0-dev_<x.y.z>_arm64.deb        # arm64机器，CenterOS系统对应的opencv开发环境安装文件
│   ├── sophon-mw-sophon-opencv-dev_<x.y.z>_amd64.deb             # x86_64机器，Debian/Ubuntu系统对应的opencv开发环境安装文件
│   ├── sophon-mw-sophon-opencv-dev_<x.y.z>_arm64.deb             # arm64机器，Debian/Ubuntu系统对应的opencv开发环境安装文件
│   ├── sophon-mw-sophon-sample_<x.y.z>_amd64.deb                 # x86_64机器，多媒体程序示例文件
│   └── sophon-mw-sophon-sample_<x.y.z>_arm64.deb                 # arm64机器，多媒体程序示例文件

├── sophon-pipeline_<date>_<hash>
│   ├── release_version.txt
│   ├── sophon-pipeline.MD5
│   └── sophon-pipeline_v<x.y.z>_<hash>_<date>.tar.gz          # 基于pipeline的高性能推理框架

├── sophon-rpc_<date>_<hash>
│   ├── release_version.txt
│   ├── sophon-rpc_<x.y.z>_amd64.deb                              # x86_64机器，Debian/Ubuntu系统对应的sophon-rpc安装文件
│   ├── sophon-rpc_<x.y.z>_arm64.deb                              # arm64机器，Debian/Ubuntu系统对应的sophon-rpc安装文件
│   ├── sophon-rpc_<x.y.z>.tar.gz                                 # 其他系统对应的sophon-rpc安装包
│   ├── sophon-rpc.MD5
│   └── sophon-rpc使用指南.pdf

├── sophon-sail_<date>_<hash>
│   ├── release_version.txt
│   ├── Sophon_Inference_zh.pdf
│   ├── sophon-sail_<x.y.z>.tar.gz                                # 封装了BMLib、sophon-mw、BMCV、BMRuntime的python接口库
│   └── sophon-sail.MD5

├── sophon-stream_<date>_<hash>
│   ├── release_version.txt
│   ├── sophon-stream.MD5
│   └── sophon-stream_v<x.y.z>-_<hash>_<date>.tar.gz          # 数据流处理工具，支持多路数据流并发处理的流水线框架

├── tpu-kernel_<date>_<hash>
│   ├── release_version.txt
│   ├── tpu-kernel-1684x_v<x.y.z>-<hash>-<date>.tar.gz          # 自定义算子开发工具
│   └── tpu-kernel.MD5

├── tpu-mlir_<date>_<hash>
│   ├── release_version.txt
│   ├── tpu-mlir.MD5
│   └── tpu-mlir_v<x.y.z>-<hash>-<date>.tar.gz                    # 编译器工具链

├── tpu-nntc_<date>_<hash>
│   ├── release_version.txt
│   ├── tpu-nntc.MD5
│   └── tpu-nntc_v<x.y.z>-<hash>-<date>.tar.gz                    # 模型编译量化工具链

└── tpu-perf_v<x.y.z>
    ├── md5sum.txt
    ├── tpu_perf-<x.y.z>-py3-none-manylinux2014_aarch64.whl         
    ├── tpu_perf-<x.y.z>-py3-none-manylinux2014_x86_64.whl
    └── tpu-perf-<x.y.z>.tar.gz                                   # 模型的性能分析和精度验证工具

提示：<date>指日期，<hash>指哈希值，<x.y.z>指版本号。后续使用${SOPHONSDK}来指代SDK解压后的根目录：在宿主机上时，它是您解压文件时指定的存放文件的路径；在docker容器中时，若您没有修改SDK下的创建容器脚本，该路径默认为/workspace。
```

# SDK在线资料链接

BM1684 & BM1684X 与 BM1688 & CV186AH 为两套不同的SDK，在线文档请参考官网不同栏目：SDK资料中心

| 资料 | 说明 |
|------|------|
| sophon-demo | 提供了常见模型的推理样例程序 |
| sophon-stream | 提供了基于C++11的支持多路数据流并发处理的流水线框架 |
| sophon-pipeline | 提供了一个基于pipeline的（包含推流和结果展示的）任务构建的样例程序 |
| SOPHON-SAIL用户手册 | 提供了底层库的再次封装，提供简洁易用的CPP和Python接口 |
| LIBSOPHON使用手册 | LIBSOPHON包含BMCV、BMRuntime、BMLib等库，用来驱动VPP、智能视觉深度学习处理器等硬件，完成图像处理、张量运算、模型推理等操作 |
| BMCV开发参考手册 | BMCV 提供了一套基于SOPHON BM168X优化的机器视觉库，可对图像处理和张量运算加速 |
| BMLIB开发参考手册 | BMLIB 是在内核驱动之上封装的一层底层软件库，负责设备Handle的管理、内存管理、数据搬运、API的发送和同步、A53使能、设置工作频率等 |
| BMRuntime开发参考手册 | BMRuntime 提供了丰富的接口，驱动BModel在智能视觉深度学习处理器中执行 |
| 多媒体开发参考手册 | 驱动VPU、JPU、VPP进行RTSP流、GB28181流的解析以及视频、图像编解码等多媒体相关 |
| 多媒体客户常见问题手册 | 多媒体方面的常见问题及解答 |
| MULTIMEDIA使用手册 | 多媒体工具用户手册 |
| TPU-MLIR开发参考手册 | Tensor Processing Unit编译器工程 |
| TPU-MLIR快速入门手册 | TPU-MLIR的样例程序 |
| TPUKernel用户开发文档 | 基于Tensor Processing Unit底层原子操作接口的编程接口 |
| TPUKernel快速入门指南 | TPU-Kernel的开发流程和步骤 |
| SOPHON BSP开发参考手册 | 模组（含开发板）使用开发手册 |