# BMCV基础结构体

本章节主要用于介绍BMCV使用的基础结构体；我们不保证此文档更改后能及时告知用户，因此请使用最新版 released SDK 里面的文档。

## bm_image

bm_image 结构体定义如下:

```c
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    struct bm_image_private* image_private;
};
```

| **序号** | **术语** | **定义说明** |
|----------|----------|--------------|
| 1 | width | 图像的宽 |
| 2 | height | 图像的高 |
| 3 | image_format | 图像的色彩格式 |
| 4 | data_type | 图像的数据格式 |
| 5 | image_private | 图像的私有数据 |

## bm_image_format_ext

bm_image_format_ext 有以下枚举类型。

```cpp
typedef enum bm_image_format_ext_{
    FORMAT_YUV420P,
    FORMAT_YUV422P,
    FORMAT_YUV444P,
    FORMAT_NV12,
    FORMAT_NV21,
    FORMAT_NV16,
    FORMAT_NV61,
    FORMAT_NV24,
    FORMAT_RGB_PLANAR,
    FORMAT_BGR_PLANAR,
    FORMAT_RGB_PACKED,
    FORMAT_BGR_PACKED,
    FORMAT_RGBP_SEPARATE,
    FORMAT_BGRP_SEPARATE,
    FORMAT_GRAY,
    FORMAT_COMPRESSED,
    FORMAT_HSV_PLANAR,
    FORMAT_ARGB_PACKED,
    FORMAT_ABGR_PACKED,
    FORMAT_YUV444_PACKED,
    FORMAT_YVU444_PACKED,
    FORMAT_YUV422_YUYV,
    FORMAT_YUV422_YVYU,
    FORMAT_YUV422_UYVY,
    FORMAT_YUV422_VYUY,
    FORMAT_RGBYP_PLANAR,
    FORMAT_HSV180_PACKED,
    FORMAT_HSV256_PACKED,
    FORMAT_BAYER,
    FORMAT_BAYER_RG8,
    FORMAT_ARGB4444_PACKED,
    FORMAT_ABGR4444_PACKED,
    FORMAT_ARGB1555_PACKED,
    FORMAT_ABGR1555_PACKED,
} bm_image_format_ext;
```

| **序号** | **格式名称** | **说明** |
|----------|--------------|----------|
| 1 | FORMAT_YUV420P | 表示预创建一个 YUV420 格式的图片，有三个plane。 |
| 2 | FORMAT_YUV422P | 表示预创建一个 YUV422 格式的图片，有三个plane。 |
| 3 | FORMAT_YUV444P | 表示预创建一个 YUV444 格式的图片，有三个plane。 |
| 4 | FORMAT_NV12 | 表示预创建一个 NV12 格式的图片，有两个plane。 |
| 5 | FORMAT_NV21 | 表示预创建一个 NV21 格式的图片，有两个plane。 |
| 6 | FORMAT_NV16 | 表示预创建一个 NV16 格式的图片，有两个plane。 |
| 7 | FORMAT_NV61 | 表示预创建一个 NV61 格式的图片，有两个plane。 |
| 8 | FORMAT_NV24 | 表示预创建一个 NV24 格式的图片，有两个plane。 |
| 9 | FORMAT_RGB_PLANAR | 表示预创建一个 RGB 格式的图片，RGB 分开排列,有一个 plane。 |
| 10 | FORMAT_BGR_PLANAR | 表示预创建一个 BGR 格式的图片，BGR 分开排列,有一个 plane。 |
| 11 | FORMAT_RGB_PACKED | 表示预创建一个 RGB 格式的图片，RGB 交错排列,有一个 plane。 |
| 12 | FORMAT_BGR_PACKED | 表示预创建一个 BGR 格式的图片，BGR 交错排列,有一个 plane。 |
| 13 | FORMAT_RGBP_SEPARATE | 表示预创建一个 RGB planar 格式的图片，RGB 分开排列并各占一个 plane，共有 3 个 plane。 |
| 14 | FORMAT_BGRP_SEPARATE | 表示预创建一个 BGR planar 格式的图片，BGR 分开排列并各占一个 plane，共有 3 个 plane。 |
| 15 | FORMAT_GRAY | 表示预创建一个灰度图格式的图片，有一个 plane。 |
| 16 | FORMAT_COMPRESSED | 表示预创建一个 VPU 内部压缩格式的图片，共有四个 plane，分别存放内容如下：plane0: Y 压缩表、plane1: Y 压缩数据、plane2: CbCr 压缩表、plane3: CbCr 压缩数据。 |
| 17 | FORMAT_HSV_PLANAR | 表示预创建一个HSV planar格式的图片，H 的范围为 0~180，有三个 plane。 |
| 18 | FORMAT_ARGB_PACKED | 表示预创建一个ARGB 格式的图片，该图片仅有一个 plane，并且像素值以 BGRA 顺序交错连续排列，即 BGRABGRA。 |
| 19 | FORMAT_ABGR_PACKED | 表示预创建一个ABGR 格式的图片，该图片仅有一个 plane，并且像素值以 RGBA 顺序交错连续排列，即 RGBARGBA。 |
| 20 | FORMAT_YUV444_PACKED | 表示预创建一个YUV444 格式的图片，YUV 交错排列，有一个 plane。 |
| 21 | FORMAT_YVU444_PACKED | 表示预创建一个YVU444 格式的图片，YVU 交错排列，有一个 plane。 |
| 22 | FORMAT_YUV422_YUYV | 表示预创建一个YUV422 格式的图片，YUYV 交错排列，有一个 plane。 |
| 23 | FORMAT_YUV422_YVYU | 表示预创建一个YUV422 格式的图片，YVYU 交错排列，有一个 plane。 |
| 24 | FORMAT_YUV422_UYVY | 表示预创建一个YUV422 格式的图片，UYVY 交错排列，有一个 plane。 |
| 25 | FORMAT_YUV422_VYUY | 表示预创建一个YUV422 格式的图片，VYUY 交错排列，有一个 plane。 |
| 26 | FORMAT_RGBYP_PLANAR | 表示预创建一个RGBY planar格式的图片，有四个 plane。 |
| 27 | FORMAT_HSV180_PACKED | 表示预创建一个HSV 格式的图片，H 的范围为 0~180，HSV 交错排列，有一个 plane。 |
| 28 | FORMAT_HSV256_PACKED | 表示预创建一个HSV 格式的图片，H 的范围为 0~255，HSV 交错排列，有一个 plane。 |
| 29 | FORMAT_BAYER | 表示预创建一个bayer 格式的图片，有一个 plane，像素排列方式是BGGR，且宽高需要是偶数。 |
| 30 | FORMAT_BAYER_RG8 | 表示预创建一个bayer 格式的图片，有一个 plane，像素排列方式是RGGB，且宽高需要是偶数。 |
| 31 | FORMAT_ARGB4444_PACKED | 表示预创建一个ARGR 格式的图片，包含四个通道，即A：透明度（Alpha）、R：红色（Red）、G：绿色（Green）、B：蓝色（Blue），每个通道占4位，共16位，有一个 plane。 |
| 32 | FORMAT_ABGR4444_PACKED | 表示预创建一个ABGR 格式的图片，包含四个通道，即A：透明度（Alpha）、B：蓝色（Blue）、G：绿色（Green）、R：红色（Red），每个通道占4位，共16位，有一个 plane。 |
| 33 | FORMAT_ARGB1555_PACKED | 表示预创建一个ARGB 格式的图片，包含四个通道，即A：透明度（Alpha）、R：红色（Red）、G：绿色（Green）、B：蓝色（Blue），各个通道分别占1、5、5、5位，共16位，有一个 plane。 |
| 34 | FORMAT_ABGR1555_PACKED | 表示预创建一个ABGR 格式的图片，包含四个通道，即A：透明度（Alpha）、B：蓝色（Blue）、G：绿色（Green）、R：红色（Red），各个通道分别占1、5、5、5位，共16位，有一个 plane。 |

## bm_data_format_ext

bm_data_format_ext 有以下枚举类型。

```cpp
typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_FP16,
    DATA_TYPE_EXT_BF16,
    DATA_TYPE_EXT_U16,
    DATA_TYPE_EXT_S16,
    DATA_TYPE_EXT_U32,
    DATA_TYPE_EXT_4N_BYTE = 254,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
}bm_image_data_format_ext;
```

| **序号** | **格式名称** | **说明** |
|----------|--------------|----------|
| 1 | DATA_TYPE_EXT_FLOAT32 | 表示所创建的图片数据格式为单精度浮点数。 |
| 2 | DATA_TYPE_EXT_1N_BYTE | 表示所创建图片数据格式为普通无符号UINT8。 |
| 3 | DATA_TYPE_EXT_1N_BYTE_SIGNED | 表示所创建图片数据格式为普通有符号INT8。 |
| 4 | DATA_TYPE_EXT_FP16 | 表示所创建的图片数据格式为半精度浮点数，5bit表示指数，10bit表示小数。 |
| 5 | DATA_TYPE_EXT_BF16 | 表示所创建的图片数据格式为16bit浮点数，实际是对FLOAT32单精度浮点数截断数据，即用8bit表示指数，7bit表示小数。 |
| 6 | DATA_TYPE_EXT_U16 | 表示所创建图片数据格式为普通无符号UINT16。 |
| 7 | DATA_TYPE_EXT_S16 | 表示所创建图片数据格式为普通有符号INT16。 |
| 8 | DATA_TYPE_EXT_U32 | 表示所创建图片数据格式为普通无符号UINT32。 |
| 9 | DATA_TYPE_EXT_4N_BYTE | 表示所创建图片数据格式为 4N UINT8，即四张无符号 UINT8 图片数据交错排列，一个 bm_image 对象其实含有四张属性相同的图片。 |
| 10 | DATA_TYPE_EXT_4N_BYTE_SIGNED | 表示所创建图片数据格式为 4N INT8，即四张有符号 INT8 图片数据交错排列。 |

# bmcv_as_strided

该接口可以根据现有矩阵以及给定的步长来创建一个视图矩阵。

**接口形式：**

```c
bm_status_t bmcv_as_strided(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int input_row,
            int input_col,
            int output_row,
            int output_col,
            int row_stride,
            int col_stride);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input
  输入参数。存放输入矩阵 input 数据的设备内存地址。

* bm_device_mem_t output
  输入参数。存放输出矩阵 output 数据的设备内存地址。

* int input_row
  输入参数。输入矩阵 input 的行数。

* int input_col
  输入参数。输入矩阵 input 的列数。

* int output_row
  输入参数。输出矩阵 output 的行数。

* int output_col
  输入参数。输出矩阵 output 的列数。

* int row_stride
  输入参数。输出矩阵行之间的步长。

* int col_stride
  输入参数。输出矩阵列之间的步长。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项：**

1. 该接口可通过设置环境变量启用双核计算，运行程序前：export TPU_CORES=2或export TPU_CORES=both即可。

**示例代码**

```c
#include "bmcv_api_ext_c.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main()
{
  int input_row = 5;
  int input_col = 5;
  int output_row = 3;
  int output_col = 3;
  int row_stride = 1;
  int col_stride = 2;
  int input_size = input_row * input_col;
  int output_size = output_row * output_col;
  int ret = 0;
  bm_handle_t handle;
  ret = bm_dev_request(&handle, 0);

  float* input_data = (float*)malloc(input_size  * sizeof(float));
  float* tpu_output = (float*)malloc(output_size * sizeof(float));

  for (int i = 0; i < input_size; i++) {
    input_data[i] = (float)rand() / (float)RAND_MAX * 100;
  }

  memset(tpu_output, 0, output_size * sizeof(float));

  bm_device_mem_t input_dev_mem, output_dev_mem;
  ret = bm_malloc_device_byte(handle, &input_dev_mem, input_size * sizeof(float));
  ret = bm_malloc_device_byte(handle, &output_dev_mem, output_size * sizeof(float));

  ret = bm_memcpy_s2d(handle, input_dev_mem, input_data);

  ret = bmcv_as_strided(handle, input_dev_mem, output_dev_mem, input_row, \
                  input_col, output_row, output_col, row_stride, col_stride);

  ret = bm_memcpy_d2s(handle, tpu_output, output_dev_mem);

  bm_free_device(handle, input_dev_mem);
  bm_free_device(handle, output_dev_mem);

  free(input_data);
  free(tpu_output);
  bm_dev_free(handle);
  return ret;
}
```

# bmcv_base64_enc(dec)

## 描述

base64 网络传输中常用的编码方式，利用64个常用字符来对6位二进制数编码。

## 语法

```c++
bm_status_t bmcv_base64_enc(bm_handle_t handle,
        bm_device_mem_t src,
        bm_device_mem_t dst,
        unsigned long len[2])

bm_status_t bmcv_base64_dec(bm_handle_t handle,
        bm_device_mem_t src,
        bm_device_mem_t dst,
        unsigned long len[2])
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| src | 输入 | 输入字符串所在地址，类型为bm_device_mem_t。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。 |
| dst | 输出 | 输出字符串所在地址，类型为bm_device_mem_t。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。 |
| len[2] | 输出 | 进行base64编码或解码的长度，单位是字节。其中len[0]代表输入长度，需要调用者给出。而len[1]为输出长度，由api计算后给出。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 代码示例

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include "bmcv_api_ext_c.h"

int main() {
  int original_len = (rand() % 134217728) + 1; //128M
  int encoded_len = (original_len + 2) / 3 * 4;
  char* src = (char *)malloc((original_len + 3) * sizeof(char));
  char* dst = (char *)malloc((encoded_len + 3) * sizeof(char));
  for (int j = 0; j < original_len; j++){
    src[j] = (char)((rand() % 256) + 1);
  }
  bm_handle_t handle;
  int ret = bm_dev_request(&handle, 0);
  if (ret != BM_SUCCESS) {
    printf("Create bm handle failed. ret = %d\n", ret);
    exit(-1);
  }
  unsigned long lenth[2];
  lenth[0] = (unsigned long)original_len;

  bmcv_base64_enc(handle, bm_mem_from_system(src), bm_mem_from_system(dst), lenth);
  bmcv_base64_dec(handle, bm_mem_from_system(dst), bm_mem_from_system(src), lenth);

  bm_dev_free(handle);
  free(src);
  free(dst);
  return 0;
}
```

# bmcv_batch_topk

## 描述

计算每个 batch 中最大或最小的k个数，并返回index。

## 语法

```c
bm_status_t bmcv_batch_topk(
    bm_handle_t handle,
    bm_device_mem_t src_data_addr,
    bm_device_mem_t src_index_addr,
    bm_device_mem_t dst_data_addr,
    bm_device_mem_t dst_index_addr,
    bm_device_mem_t buffer_addr,
    int k,
    int batch,
    int *per_batch_cnt,
    int src_batch_stride,
    bool src_index_valid,
    bool same_batch_cnt,
    bool descending);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用bm_dev_request获取。 |
| src_data_addr | 输入 | 输入数据的地址信息。 |
| src_index_addr | 输入 | 输入数据索引的地址信息，当src_index_valid为true时，设置该参数。 |
| dst_data_addr | 输出 | 输出数据的地址信息。 |
| dst_index_addr | 输出 | 输出数据索引的地址信息。 |
| buffer_addr | 输入 | 缓冲区地址信息。 |
| k | 输入 | 取每个batch中最大或最小数的数量，取值范围为1-100。 |
| batch | 输入 | batch的数量，取值范围为1-20。 |
| *per_batch_cnt | 输入 | 每个batch的数据数量，取值范围为1-100000。 |
| src_batch_stride | 输入 | 两个batch之间的间隔数。 |
| src_index_valid | 输入 | 如果为true， 则使用src_index，否则使用自动生成的index。 |
| same_batch_cnt | 输入 | 每个batch数据是否相同。 |
| descending | 输入 | 对数据进行升序或者降序。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 格式支持

该接口目前仅支持float32类型数据。

## 代码示例

```c
#include <stdio.h>
#include "stdlib.h"
#include <string.h>
#include "bmcv_api_ext_c.h"

int main() {
  int batch_num = 10 + rand() % 999990;
  int k = 1 + rand() % 100;
  k = k < batch_num ? k : batch_num;
  int descending = rand() % 2;
  int batch = rand() % 32 + 1;
  bool bottom_index_valid = true;

  printf("batch_topk_params: \n");
  printf("batch_num = %d, k = %d, descending = %d, batch = %d, bottom_index_valid = %d \n", batch_num, k, descending, batch, bottom_index_valid);
  bm_handle_t handle;
  bm_status_t ret = bm_dev_request(&handle, 0);
  if (ret != BM_SUCCESS) {
    printf("Create bm handle failed. ret = %d\n", ret);
    return -1;
  }

  int batch_stride = batch_num;

  float* bottom_data = (float*)malloc(batch * batch_stride * sizeof(float));
  int* bottom_index = (int*)malloc(batch * batch_stride * sizeof(int));
  float* top_data = (float*)malloc(batch * batch_stride * sizeof(float));
  int* top_index = (int*)malloc(batch * batch_stride * sizeof(int));
  float* top_data_ref = (float*)malloc(batch * k * sizeof(float));
  int* top_index_ref = (int*)malloc(batch * k * sizeof(int));
  float* buffer = (float*)malloc(3 * batch_stride * sizeof(float));

  for(int i = 0; i < batch; i++){
    for(int j = 0; j < batch_num; j++){
      bottom_data[i * batch_stride + j] = rand() % 10000 * 1.0f;
      bottom_index[i * batch_stride + j] = i * batch_stride + j;
    }
  }

  ret = bmcv_batch_topk(handle, bm_mem_from_system((void*)bottom_data), bm_mem_from_system((void*)bottom_index),
                    bm_mem_from_system((void*)top_data), bm_mem_from_system((void*)top_index),
                    bm_mem_from_system((void*)buffer), bottom_index_valid, k, batch, &batch_num,
                    true, batch_stride, descending);

  bm_dev_free(handle);

  free(bottom_data);
  free(bottom_index);
  free(top_data);
  free(top_data_ref);
  free(top_index);
  free(top_index_ref);
  free(buffer);

  return ret;
}
```

# bmcv_blend

该接口可调用芯片上的stitch硬件模块，实现2～4路图像拼接功能。

图b展示了基于Image Stitching模块的2路图片拼接的原理。在进行拼接之前，用户需要指定重叠区域及左右权重图（weighted map）；接着，将左右权重图分别与输入的左右图像进行相乘；最后，将结果相加以获得最终的图片拼接结果。

当多路图像输入Image Blend模块前，或需要通过其他模块对多路图片进行影像几何畸变校正 (DWA), 抠图(Crop)，图像缩放(resize)等操作。

Image Blend模块接受双路图片作为输入，通过Image Blend算法根据相同的图像区间，将这些图片拼接在一起。

## 加速原理介绍

图片融合模块（Image Blend）用于加速影像拼接的相关计算。对于有着不同图片输入数量的图片拼接任务，拼接方式有多种方案。

## 接口函数介绍

### 接口形式

```c
bm_status_t bmcv_blending(
            bm_handle_t handle,
            int input_num,
            bm_image* input,
            bm_image output,
            struct stitch_param stitch_config);
```

### 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input_num | 输入 | 输入 image 数量，2或3或4。 |
| *input | 输入 | 输入待拼接 bm_image 对象指针，其指向空间的长度由 input_num 决定。 |
| output | 输出 | 输出拼接后 bm_image 对象。 |
| stitch_config | 输入 | 该结构描述了拼接融合中所需要设置的参数。 |

### 数据类型说明

```c
struct stitch_param {
    struct bm_stitch_src_ovlp_attr ovlap_attr;
    struct bm_stitch_src_bd_attr bd_attr;
    bm_device_mem_t wgt_phy_mem[3][2];
    enum bm_stitch_wgt_mode wgt_mode;
};
```

| **参数名称** | **描述** |
|-------------|----------|
| ovlap_attr | 输入源重叠区域属性。 |
| bd_attr | 输入域左右边界区域属性，目前参数未开放，设为0。 |
| wgt_phy_mem | 权重图的物理地址和大小。 |
| wgt_mode | 权重图的模式。 |

```c
struct bm_stitch_src_ovlp_attr {
    short ovlp_lx[3];
    short ovlp_rx[3];
};
```

| **参数名称** | **描述** |
|-------------|----------|
| ovlp_lx | 重叠区域左边界点x坐标。 |
| ovlp_rx | 重叠区域右边界点x坐标。 |

```c
struct bm_stitch_src_bd_attr {
    short bd_lx[4];
    short bd_rx[4];
};
```

| **参数名称** | **描述** |
|-------------|----------|
| bd_lx | 左侧图片的黑边宽度。 |
| bd_rx | 右侧图片的黑边宽度。 |

```c
typedef struct bm_mem_desc {
  union {
    struct {
#ifdef __linux__
      unsigned long device_addr;
#else
      unsigned long long device_addr;
#endif
      unsigned int reserved;
      int dmabuf_fd;
    } device;

    struct {
      void *system_addr;
      unsigned int reserved0;
      int reserved1;
    } system;
  } u;

  bm_mem_flags_t flags;
  unsigned int size;
} bm_mem_desc_t;
```

**bm_device_mem_t wgt_phy_mem 参数介绍**

| 参数名称 | 描述 |
|---------|------|
| wgt_phy_mem[0][0] | 第1处融合区域，y通道权重图数据 |
| wgt_phy_mem[0][1] | 第1处融合区域，uv通道权重图数据 |
| device_addr | 权重图的物理地址 |
| size | 权重图的字节数大小 |

```c
enum bm_stitch_wgt_mode {
    BM_STITCH_WGT_YUV_SHARE = 0,
    BM_STITCH_WGT_UV_SHARE,
    BM_STITCH_WGT_SEP,
};
```

**bm_stitch_wgt_mode 参数介绍**

| 参数名称 | 描述 |
|---------|------|
| BM_STITCH_WGT_YUV_SHARE | YUV share alpha and beta (1 alpha + 1 beta)，优先推荐这个 |
| BM_STITCH_WGT_UV_SHARE | UV share alpha and beta (2 alpha + 2 beta)，不推荐选这个 |

**返回值**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持**

* 输入、输出图像格式支持：
    * FORMAT_RGBP_SEPARATE、FORMAT_BGRP_SEPARATE
    * FORMAT_YUV420P、FORMAT_YUV422P
    * FORMAT_YUV444P、FORMAT_GRAY

**注意事项：**

1. 图像stride要求16byte对齐。输入图片最小像素支持64x64，最大支持4608x8192
2. 输入输出数据类型要求：DATA_TYPE_EXT_1N_BYTE
3. 输入输出格式需保持一致；输入输出图片高需要相等
4. wgt_phy_mem参数，请用bmlib相关api设置，不要直接赋值。使用例如：bm_malloc_device_byte，bm_memcpy_s2d等接口。传入的权重数据须为char类型数据，对于重叠区域的每个像素，左权重+右权重数值须为255

**示例代码：**

```c
#include "stdio.h"
#include "stdlib.h"
#include <unistd.h>
#include "string.h"
#include "getopt.h"
#include "signal.h"
#include "bmcv_api_ext_c.h"
#include <stdatomic.h>

#define ALIGN(x, a) (((x) + ((a)-1)) & ~((a)-1))

void bm_dem_read_bin(bm_handle_t handle, bm_device_mem_t* dmem, const char *input_name, unsigned int size)
{
  if (access(input_name, F_OK) != 0 || strlen(input_name) == 0 || 0 >= size)
  {
    return;
  }

  char* input_ptr = (char *)malloc(size);
  FILE *fp_src = fopen(input_name, "rb+");

  if (fread((void *)input_ptr, 1, size, fp_src) < (unsigned int)size){
      printf("file size is less than %d required bytes\n", size);
  };
  fclose(fp_src);

  if (BM_SUCCESS != bm_malloc_device_byte(handle, dmem, size)){
    printf("bm_malloc_device_byte failed\n");
  }

  if (BM_SUCCESS != bm_memcpy_s2d(handle, *dmem, input_ptr)){
    printf("bm_memcpy_s2d failed\n");
  }

  free(input_ptr);
  return;
}

void blend_HandleSig(int signum)
{
  signal(SIGINT, SIG_IGN);
  signal(SIGTERM, SIG_IGN);
  printf("signal happen  %d \n",signum);
  exit(-1);
}

int main() {
  bm_handle_t handle = NULL;
  bm_image src[2], dst;
  int src_h[2] = {288, 288}, src_w[2] = {2304, 4608}, dst_w = 4608, dst_h = 288, wgtWidth, wgtHeight;
  bm_image_format_ext src_fmt = FORMAT_YUV420P, dst_fmt = FORMAT_YUV420P;
  char *src_name[2] = {"path/to/src1", "path/to/src2"}, *dst_name = "path/to/dst", *wgt_name[2] = {"path/to/wgt1", "path/to/wgt2"};
  int dev_id = 0, ret = 0, wgt_len = 0, input_num = 2;

  struct stitch_param stitch_config;
  memset(&stitch_config, 0, sizeof(stitch_config));
  stitch_config.wgt_mode = BM_STITCH_WGT_YUV_SHARE;

  signal(SIGINT, blend_HandleSig);
  signal(SIGTERM, blend_HandleSig);

  bm_status_t ret1 = bm_dev_request(&handle, dev_id);
  if (ret1 != BM_SUCCESS) {
      printf("Create bm handle failed. ret = %d\n", ret);
      exit(-1);
  }
  stitch_config.ovlap_attr.ovlp_rx[0] = 2303;
  stitch_config.ovlap_attr.ovlp_lx[0] = 0;
  wgtWidth = ALIGN(stitch_config.ovlap_attr.ovlp_rx[0] - stitch_config.ovlap_attr.ovlp_lx[0] + 1, 16);
  wgtHeight = src_h[0];

  int byte_size = 0;
  for(int i = 0; i < 2; i++)
  {
    bm_image_create(handle, src_h[i], src_w[i], src_fmt, DATA_TYPE_EXT_1N_BYTE, &src[i], NULL);
    bm_image_alloc_dev_mem(src[i], 1);
    byte_size = src_w[i] * src_h[i] * 3 / 2;
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name[i], "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data, (void *)((unsigned char*)input_data + src_w[i] * src_h[i]), (void *)((unsigned char*)input_data + src_w[i] * src_h[i] * 5 / 4)};
    bm_image_copy_host_to_device(src[i], in_ptr);
    wgt_len = wgtWidth * wgtHeight;
    if (stitch_config.wgt_mode == BM_STITCH_WGT_UV_SHARE)
      wgt_len = wgt_len << 1;

    bm_dem_read_bin(handle, &stitch_config.wgt_phy_mem[0][i], wgt_name[i], wgt_len);
  }
  bm_image_create(handle, dst_h, dst_w, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);
  bm_image_alloc_dev_mem(dst, 1);

  ret = bmcv_blending(handle, input_num, src, dst, stitch_config);

  unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
  void* out_ptr[4] = {(void*)output_ptr, (void*)((unsigned char*)output_ptr + dst_w * dst_h), (void*)((unsigned char*)output_ptr + dst_w * dst_h * 5 / 4)};
  bm_image_copy_device_to_host(dst, (void **)out_ptr);

  FILE *fp_dst = fopen(dst_name, "wb");
  if (fwrite((void *)output_ptr, 1, byte_size, fp_dst) < (unsigned int)byte_size){
      printf("file size is less than %d required bytes\n", byte_size);
  };
  fclose(fp_dst);

  bm_image_destroy(&src[0]);
  bm_image_destroy(&src[1]);
  bm_image_destroy(&dst);
  bm_dev_free(handle);

  return ret;
}
```

# bmcv_calc_hist

直方图

**接口形式：**

```c
bm_status_t bmcv_calc_hist(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int C,
            int H,
            int W,
            const int* channels,
            int dims,
            const int* histSizes,
            const float* ranges,
            int inputDtype);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_device_mem_t input
  输入参数。该device memory空间存储了输入数据，类型可以是float32或者uint8，由参数inputDtype决定。其大小为 C * H * W * sizeof(Dtype)。

* bm_device_mem_t output
  输出参数。该device memory空间存储了输出结果，类型为float，其大小为histSizes[0] * histSizes[1] * …… * histSizes[n] * sizeof(float)。

* int C
  输入参数。输入数据的通道数量。

* int H
  输入参数。输入数据每个通道的高度。

* int W
  输入参数。输入数据每个通道的宽度。

* const int* channels
  输入参数。需要计算直方图的channel列表，其长度为dims，每个元素的值必须小于C。

* int dims
  输入参数。输出的直方图维度，要求不大于3。

* const int* histSizes
  输入参数。对应每个channel统计直方图的份数，其长度为dims。

* const float* ranges
  输入参数。每个通道参与统计的范围，其长度为2 * dims。

* int inputDtype
  输入参数。输入数据的类型：0表示float，1表示uint8。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**示例代码**

```c
#include "bmcv_api_ext_c.h"
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int main() {
  int H = 1024;
  int W = 1024;
  int C = 3;
  int dim = 3;
  int data_type = 0; // 0: float; 1: uint8

  int channels[3] = {0, 1, 2};
  int histSizes[3] = {32, 32, 32};
  float ranges[6] = {0, 256, 0, 256, 0, 256};

  int totalHists = 1;
  int ret = 0;
  int i, j;
  int Num = 0;
  bm_handle_t handle;

  ret = bm_dev_request(&handle, 0);
  if (ret != BM_SUCCESS) {
    printf("bm_dev_request failed. ret = %d\n", ret);
    return -1;
  }
  for (i = 0; i < dim; i++) {
    totalHists *= histSizes[i];
  }
  float* output_tpu = (float*)malloc(totalHists * sizeof(float));
  memset(output_tpu, 0, totalHists * sizeof(float));

  float* input_host = (float*)malloc(C * H * W * sizeof(float));

  // randomly initialize input_host
  for (i = 0; i < C; i++) {
    for (j = 0; j < H * W; j++) {
      Num = (int)ranges[2*C-1];
      input_host[i * H * W + j] = (float)(rand() % Num);
    }
  }

  bm_device_mem_t input, output;
  ret = bm_malloc_device_byte(handle, &output, totalHists * sizeof(float));
  ret = bm_malloc_device_byte(handle, &input, C * H * W * sizeof(float));
  ret = bm_memcpy_s2d(handle, input, input_host);
  ret = bmcv_calc_hist(handle, input, output, C, H, W, channels, dim, histSizes, ranges, data_type);

  ret = bm_memcpy_d2s(handle, output_tpu, output);
  if (ret != BM_SUCCESS) {
    printf("test calc hist failed. ret = %d\n", ret);
    bm_free_device(handle, input);
  }

  free(input_host);
  free(output_tpu);
  bm_dev_free(handle);
  return ret;
}
```

# 带权重的直方图

**接口形式：**

```c
bm_status_t bmcv_calc_hist_with_weight(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            const float* weight,
            int C,
            int H,
            int W,
            const int* channels,
            int dims,
            const int* histSizes,
            const float* ranges,
            int inputDtype);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input
  输入参数。该device memory空间存储了输入数据，其大小为 C * H * W * sizeof(Dtype)。

* bm_device_mem_t output
  输出参数。该device memory空间存储了输出结果，类型为float，其大小为histSizes[0] * histSizes[1] * …… * histSizes[n] * sizeof(float)。

* const float* weight
  输入参数。channel内部每个元素在统计直方图时的权重，其大小为H * W * sizeof(float)，如果所有值全为 1 则与普通直方图功能相同。

* int C
  输入参数。输入数据的通道数量。

* int H
  输入参数。输入数据每个通道的高度。

* int W
  输入参数。输入数据每个通道的宽度。

* const int* channels
  输入参数。需要计算直方图的 channel 列表，其长度为 dims，每个元素的值必须小于 C。

* int dims
  输入参数。输出的直方图维度，要求不大于 3。

* const int* histSizes
  输入参数。对应每个channel统计直方图的份数，其长度为 dims。

* const float* ranges
  输入参数。每个通道参与统计的范围，其长度为2 * dims。

* int inputDtype
  输入参数。输入数据的类型：0 表示float，1 表示uint8。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

# bmcv_dpu_fgs_disp

**【描述】**

该 API 使用 DPU 硬件资源，快速全局平滑算法FGS(Fast Global Smoothing)。

**【语法】**

```c++
bm_status_t bmcv_dpu_fgs_disp(
    bm_handle_t handle,
    bm_image *guide_image,
    bm_image *smooth_image,
    bm_image *disp_image,
    bmcv_dpu_fgs_attrs *fgs_attr,
    bmcv_dpu_fgs_mode fgs_mode);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| *guide_image | 输入 | bm_image 类型，指导图指针，不能为空。 |
| *smooth_image | 输入 | bm_image 类型，视差图指针，不能为空，宽、高同 guide_image。 |
| *disp_image | 输出 | bm_image 类型，平滑图，不能为空，宽、高同 guide_image。 |
| *fgs_attr | 输入 | bmcv_dpu_fgs_attrs 类型，FGS 部分控制参数。 |
| fgs_mode | 输入 | DPU FGS 输出模式。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| guide_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| smooth_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 guide_image |
| disp_image | GRAY | DATA_TYPE_EXT_1N_BYTE<br>DATA_TYPE_EXT_U16 | 同 guide_image |

**【数据类型说明】**

**【说明】** 定义 DPU FGS 输出模式。

```c++
typedef enum bmcv_dpu_fgs_mode_{
    DPU_FGS_MUX0 = 7,
    DPU_FGS_MUX1 = 8,
} bmcv_dpu_fgs_mode;
```

| 成员名称 | 描述 |
|---------|------|
| DPU_FGS_MUX0 | 使用FGS处理左图和右图，输出一张8bit视差图（也可用于图像的降噪，类似于引导滤波）。 |
| DPU_FGS_MUX1 | 使用FGS处理左图和右图，输出一张16bit深度图。 |

**【说明】** 定义 DPU FGS 深度单位。

```c++
typedef enum bmcv_dpu_depth_unit_{
    BMCV_DPU_DEPTH_UNIT_DEFAULT,
    BMCV_DPU_DEPTH_UNIT_MM,
    BMCV_DPU_DEPTH_UNIT_CM,
    BMCV_DPU_DEPTH_UNIT_DM,
    BMCV_DPU_DEPTH_UNIT_M,
    BMCV_DPU_DEPTH_UNIT_BUTT
} bmcv_dpu_depth_unit;
```

| 成员名称 | 描述 |
|---------|------|
| BMCV_DPU_DEPTH_UNIT_DEFAULT | 默认深度单位，mm。 |
| BMCV_DPU_DEPTH_UNIT_MM | 深度单位是 mm。 |
| BMCV_DPU_DEPTH_UNIT_CM | 深度单位是 cm。 |
| BMCV_DPU_DEPTH_UNIT_DM | 深度单位是 dm。 |
| BMCV_DPU_DEPTH_UNIT_M | 深度单位是 m。 |
| BMCV_DPU_DEPTH_UNIT_BUTT | 枚举数组最大值，用于判断输入是否在范围内。 |

**【说明】** 定义 DPU FGS 控制参数。

```c++
typedef struct bmcv_dpu_fgs_attrs_{
    unsigned int         fgs_max_count;
    unsigned int         fgs_max_t;
    unsigned int         fxbase_line;
    bmcv_dpu_depth_unit  depth_unit_en;
} bmcv_dpu_fgs_attrs;
```

| 成员名称 | 描述 |
|---------|------|
| fgs_max_count | Fgs中转变为0的最大次数。 |
| fgs_max_t | Fgs的最大迭代次数（至少设置为2），由于 FGS 计算量较大，一般设置为 3。 |
| fxbase_line | 左右摄像头的基线值。 |
| depth_unit_en | 深度的度量单位，取值可参考 bmcv_dpu_depth_unit 说明。 |

**【返回值】**

该函数成功调用时，返回 BM_SUCCESS。

**【注意】**

1. 左右图像的 height 和 width 必须相同。
2. 左右图像的 width 要求 4 对齐，height 要求 2 对齐，输入图 stride 需要 16 对齐，输出图 stride 需要 32 对齐。
3. Fgs的最大迭代次数至少设置为 2。

# bmcv_dpu_online_disp

**【描述】**

该 API 使用 DPU 硬件资源，实现半全局块匹配算法 SGBM(Semi-Global Block Maching) 跟快速全局平滑算法FGS(Fast Global Smoothing)。

**【语法】**

```c++
bm_status_t bmcv_dpu_online_disp(
    bm_handle_t handle,
    bm_image *left_image,
    bm_image *right_image,
    bm_image *disp_image,
    bmcv_dpu_sgbm_attrs *dpu_attr,
    bmcv_dpu_fgs_attrs *fgs_attr,
    bmcv_dpu_online_mode online_mode);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| *left_image | 输入 | bm_image 类型，指导图指针，不能为空。 |
| *right_image | 输入 | bm_image 类型，平滑图指针，不能为空，宽、高同 left_image。 |
| *disp_image | 输出 | bm_image 类型，视差图，不能为空，宽、高同 left_image。 |
| *dpu_attr | 输入 | bmcv_dpu_sgbm_attrs 类型，SGBM 部分控制参数。 |
| *fgs_attr | 输入 | bmcv_dpu_fgs_attrs 类型，FGS 部分控制参数。 |
| online_mode | 输入 | DPU online（SGBM_TO_FGS）输出模式。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| left_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| right_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 left_image |
| disp_image | GRAY | DATA_TYPE_EXT_1N_BYTE<br>DATA_TYPE_EXT_U16 | 同 left_image |

**【数据类型说明】**

**【说明】** 定义 DPU FGS 输出模式。

```c++
typedef enum bmcv_dpu_online_mode_{
    DPU_ONLINE_MUX0 = 4,
    DPU_ONLINE_MUX1 = 5,
    DPU_ONLINE_MUX2 = 6,
} bmcv_dpu_online_mode;
```

| 成员名称 | 描述 |
|---------|------|
| DPU_ONLINE_MUX0 | 该模式下，使用FGS处理左图和右图，输出一张8bit视差图（也可用于图像的降噪，类似于引导滤波）。 |
| DPU_ONLINE_MUX1 | 该模式下，使用SGBM、FGS处理左图和右图，输出一张16bit深度图。 |
| DPU_ONLINE_MUX2 | 该模式下，单独使用SGBM处理左图和右图，输出一张16bit深度图。 |

**【注意】** bmcv_dpu_sgbm_attrs 及 bmcv_dpu_fgs_attrs 类型的说明，详见bmcv_dpu_fgs_disp 及 bmcv_dpu_sgbm_disp。

**【返回值】**

该函数成功调用时，返回 BM_SUCCESS。

**【注意】**

1. 左右图像的 height 和 width 必须相同。
2. 左右图像的 width 要求 16 对齐，height 要求 2 对齐，输入图 stride 需要 16 对齐，输出图 stride 需要 32对齐。

# bmcv_dpu_sgbm_disp

**【描述】**

该 API 使用 DPU 硬件资源，实现半全局块匹配算法 SGBM(Semi-Global Block Maching)。

**【语法】**

```c++
bm_status_t bmcv_dpu_sgbm_disp(
    bm_handle_t handle,
    bm_image *left_image,
    bm_image *right_image,
    bm_image *disp_image,
    bmcv_dpu_sgbm_attrs *dpu_attr,
    bmcv_dpu_sgbm_mode sgbm_mode);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| *left_image | 输入 | bm_image 类型，参考图指针，不能为空。 |
| *right_image | 输入 | bm_image 类型，搜索图指针，不能为空，宽、高同 left_image。 |
| *disp_image | 输出 | bm_image 类型，视差图，不能为空，宽、高同 left_image。 |
| *dpu_attr | 输入 | bmcv_dpu_sgbm_attrs 类型，SGBM 部分控制参数。 |
| sgbm_mode | 输入 | DPU SGBM 输出模式。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| left_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| right_image | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 left_image |
| disp_image | GRAY | DATA_TYPE_EXT_1N_BYTE<br>DATA_TYPE_EXT_U16 | 同 left_image |

**【数据类型说明】**

**【说明】** 定义 DPU SGBM 输出模式。

```c++
typedef enum bmcv_dpu_sgbm_mode_{
    DPU_SGBM_MUX0 = 1,
    DPU_SGBM_MUX1 = 2,
    DPU_SGBM_MUX2 = 3,
} bmcv_dpu_sgbm_mode;
```

| 成员名称 | 描述 |
|---------|------|
| DPU_SGBM_MUX0 | 使用SGBM处理左图和右图，输出一张没有经过后处理的8bit视差图。 |
| DPU_SGBM_MUX1 | 使用SGBM处理左图和右图，输出一张经过后处理的16bit视差图。 |
| DPU_SGBM_MUX2 | 使用SGBM处理左图和右图，输出一张经过后处理的8bit视差图。 |

**【说明】** 定义 DPU SGBM 右图搜索范围。

```c++
typedef enum bmcv_dpu_disp_range_{
    BMCV_DPU_DISP_RANGE_DEFAULT,
    BMCV_DPU_DISP_RANGE_16,
    BMCV_DPU_DISP_RANGE_32,
    BMCV_DPU_DISP_RANGE_48,
    BMCV_DPU_DISP_RANGE_64,
    BMCV_DPU_DISP_RANGE_80,
    BMCV_DPU_DISP_RANGE_96,
    BMCV_DPU_DISP_RANGE_112,
    BMCV_DPU_DISP_RANGE_128,
    BMCV_DPU_DISP_RANGE_BUTT
} bmcv_dpu_disp_range;
```

| 成员名称 | 描述 |
|---------|------|
| BMCV_DPU_DISP_RANGE_DEFAULT | 默认右图搜索范围为 16 pixel。 |
| BMCV_DPU_DISP_RANGE_16 | 右图搜索范围为 16 pixel。 |
| BMCV_DPU_DISP_RANGE_32 | 右图搜索范围为 32 pixel。 |
| BMCV_DPU_DISP_RANGE_48 | 右图搜索范围为 48 pixel。 |
| BMCV_DPU_DISP_RANGE_64 | 右图搜索范围为 64 pixel。 |
| BMCV_DPU_DISP_RANGE_80 | 右图搜索范围为 80 pixel。 |
| BMCV_DPU_DISP_RANGE_96 | 右图搜索范围为 96 pixel。 |
| BMCV_DPU_DISP_RANGE_112 | 右图搜索范围为 112 pixel。 |
| BMCV_DPU_DISP_RANGE_128 | 右图搜索范围为 128 pixel。 |
| BMCV_DPU_DISP_RANGE_BUTT | 枚举数组最大值，用于判断输入是否在范围内。 |

**【说明】** 定义 DPU SGBM BoxFilter 模式。

```c++
typedef enum bmcv_dpu_bfw_mode_{
    DPU_BFW_MODE_DEFAULT,
    DPU_BFW_MODE_1x1,
    DPU_BFW_MODE_3x3,
    DPU_BFW_MODE_5x5,
    DPU_BFW_MODE_7x7,
    DPU_BFW_MODE_BUTT
} bmcv_dpu_bfw_mode;
```

| 成员名称 | 描述 |
|---------|------|
| DPU_BFW_MODE_DEFAULT | 默认BoxFilter窗口大小为 7x7。 |
| DPU_BFW_MODE_1x1 | BoxFilter窗口大小为 1x1。 |
| DPU_BFW_MODE_3x3 | BoxFilter窗口大小为 3x3。 |
| DPU_BFW_MODE_5x5 | BoxFilter窗口大小为 5x5。 |
| DPU_BFW_MODE_7x7 | BoxFilter窗口大小为 7x7。 |
| DPU_BFW_MODE_BUTT | 枚举数值的最大值，用于判断输入的枚举值是否在范围内。 |

**【说明】** 定义 DPU SGBM DCC 代价聚合的模式。

```c++
typedef enum bmcv_dpu_dcc_dir_{
    BMCV_DPU_DCC_DIR_DEFAULT,
    BMCV_DPU_DCC_DIR_A12,
    BMCV_DPU_DCC_DIR_A13,
    BMCV_DPU_DCC_DIR_A14,
    BMCV_DPU_DCC_DIR_BUTT
} bmcv_dpu_dcc_dir;
```

| 成员名称 | 描述 |
|---------|------|
| BMCV_DPU_DCC_DIR_DEFAULT | DCC 默认代价聚合方向：A1+A2。 |
| BMCV_DPU_DCC_DIR_A12 | DCC 代价聚合方向：A1+A2。 |
| BMCV_DPU_DCC_DIR_A13 | DCC 代价聚合方向：A1+A3。 |
| BMCV_DPU_DCC_DIR_A14 | DCC 代价聚合方向：A1+A4。 |
| DPU_BFW_MODE_BUTT | 枚举数值的最大值，用于判断输入的枚举值是否在范围内。 |

# 定义 DPU SGBM 控制参数

```c++
typedef struct bmcv_dpu_sgbm_attrs_{
    bmcv_dpu_bfw_mode    bfw_mode_en;
    bmcv_dpu_disp_range  disp_range_en;
    unsigned short       disp_start_pos;
    unsigned int         dpu_census_shift;
    unsigned int         dpu_rshift1;
    unsigned int         dpu_rshift2;
    bmcv_dpu_dcc_dir     dcc_dir_en;
    unsigned int         dpu_ca_p1;
    unsigned int         dpu_ca_p2;
    unsigned int         dpu_uniq_ratio;
    unsigned int         dpu_disp_shift;
} bmcv_dpu_sgbm_attrs;
```

| 成员名称 | 描述 |
|---------|------|
| bfw_mode_en | DPU SGBM BoxFilter窗口大小，取值可参考 bmcv_dpu_bfw_mode 的说明 |
| disp_range_en | 右图搜索范围，取值可参考 bmcv_dpu_disp_range 的说明 |
| disp_start_pos | 右图搜索的起始位置 |
| dpu_census_shift | Census Transform 偏移量 |
| dpu_rshift1 | 原图的BTcost map的权值 |
| dpu_rshift2 | Census Transform的BTcost map的权值 |
| dcc_dir_en | DCC 代价聚合方向，取值可参考 bmcv_dpu_dcc_dir 的说明 |
| dpu_ca_p1 | DCC 代价聚合 P1 惩罚因子 |
| dpu_ca_p2 | DCC 代价聚合 P2 惩罚因子 |
| dpu_uniq_ratio | 唯一性检查因子，取值范围:[0, 100] |
| dpu_disp_shift | 视差偏移量 |

**返回值**

该函数成功调用时，返回 BM_SUCCESS。

**注意**

1. 右图像的 width 必须大于或等于视差搜索的起始位置与视差搜索范围的和，即：`right_image->width ≥ disp_start_pos + disp_range_en`

2. 左右图像的 height 和 width 必须相同

3. 左右图像的 width 要求 4 对齐，height 要求 2 对齐，stride 需要 16 对齐

# bmcv_dwa_affine

**描述**

去畸变仿射(DWA)模块的仿射校正功能，通过线性组合和平移操作，来保持图像中的平行线仍然平行，并保持源图像两点之间的距离比例，从而对图像进行旋转、缩放、平移和倾斜等变换。

**语法**

```c++
bm_status_t bmcv_dwa_affine(bm_handle_t          handle,
                            bm_image             input_image,
                            bm_image             output_image,
                            bmcv_affine_attr_s   affine_attr);
```

**参数**

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| input_image | 输入 | 输入的源图像，通过调用 bm_image_create 创建 |
| output_image | 输出 | 输出的仿射变化校正后的图像，通过调用 bm_image_create 创建 |
| affine_attr | 输入 | affine功能的参数配置列表，包括u32RegionNum astRegionAttr stDestSize |

**返回值**

该函数成功调用时，返回 BM_SUCCESS。

**数据类型说明**

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| u32RegionNum | 输入 | 配置范围:[1, 32]，在源图像中进行 Affine 操作的区域数量 |
| astRegionAttr | 输入 | 结构体数组，存储源图像中每个 Affine 区域的四个顶点坐标 |
| stDestSize | 输入 | 结构体，存储 Affine 操作后的目标区域尺寸 |

**格式支持**

1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_RGB_PLANAR |
| 2 | FORMAT_YUV420P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_GRAY |

**注意**

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败

2. 支持图像的分辨率为32x32~4096x4096，且要求32对齐

3. 用户需根据源图像中想要进行 Affine 操作的位置及目标区域尺寸自行输入配置参数列表affine_attr

4. astRegionAttr数组中，原图中某区域四个顶点的坐标顺序分别为左上、右上、左下、右下

5. 推荐stDestSize的width与输出图像output_image的width相同，否则结果需要裁剪

**代码示例**

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int main() {
    int src_h = 1080, src_w = 1920, dst_w = 1920, dst_h = 1080, dev_id = 0;
    bm_image_format_ext fmt = FORMAT_YUV420P;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    bmcv_affine_attr_s affine_attr = {0};
    affine_attr.u32RegionNum = 4;
    affine_attr.stDestSize.u32Width = 400;
    affine_attr.stDestSize.u32Height = 400;
    // bmcv_point2f_s faces[9][4] = {0};
    bmcv_point2f_s faces[9][4] = {
        { {.x = 722.755, .y = 65.7575}, {.x = 828.402, .y = 80.6858}, {.x = 707.827, .y = 171.405}, {.x = 813.474, .y = 186.333} },
        { {.x = 494.919, .y = 117.918}, {.x = 605.38,  .y = 109.453}, {.x = 503.384, .y = 228.378}, {.x = 613.845, .y = 219.913} },
        { {.x = 1509.06, .y = 147.139}, {.x = 1592.4,  .y = 193.044}, {.x = 1463.15, .y = 230.48 }, {.x = 1546.5,  .y = 276.383} },
        { {.x = 1580.21, .y = 66.7939}, {.x = 1694.1,  .y = 70.356 }, {.x = 1576.65, .y = 180.682}, {.x = 1690.54, .y = 184.243} },
        { {.x = 178.76,  .y = 90.4814}, {.x = 286.234, .y = 80.799 }, {.x = 188.442, .y = 197.955}, {.x = 295.916, .y = 188.273} },
        { {.x = 1195.57, .y = 139.226}, {.x = 1292.69, .y = 104.122}, {.x = 1230.68, .y = 236.34}, {.x = 1327.79, .y = 201.236}, },
        { {.x = 398.669, .y = 109.872}, {.x = 501.93, .y = 133.357}, {.x = 375.184, .y = 213.133}, {.x = 478.445, .y = 236.618}, },
        { {.x = 845.989, .y = 94.591}, {.x = 949.411, .y = 63.6143}, {.x = 876.966, .y = 198.013}, {.x = 980.388, .y = 167.036}, },
        { {.x = 1060.19, .y = 58.7882}, {.x = 1170.61, .y = 61.9105}, {.x = 1057.07, .y = 169.203}, {.x = 1167.48, .y = 172.325}, },
    };
    memcpy(affine_attr.astRegionAttr, faces, sizeof(faces));

    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;

    bm_image_create(handle, src_h, src_w, fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, dst_h, dst_w, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char*)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void*)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
        printf("file size is less than required bytes%d\n", byte_size);
    }
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    bmcv_dwa_affine(handle, src, dst, affine_attr);

    bm_image_get_byte_size(dst, image_byte_size);
    byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + image_byte_size[0]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_device_to_host(dst, (void **)out_ptr);

    FILE *fp_dst = fopen(dst_name, "wb");
    if (fwrite((void *)output_ptr, 1, byte_size, fp_dst) < (unsigned int)byte_size){
        printf("file size is less than %d required bytes\n", byte_size);
    };
    fclose(fp_dst);

    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    free(input_data);
    free(output_ptr);

    bm_dev_free(handle);

    return 0;
}
```

# bmcv_dwa_fisheye

## 描述

去畸变仿射(DWA)模块的鱼眼畸变校正功能，通过配置校正参数获取适当的校正模型来消除鱼眼镜头造成的图像畸变，从而使弯曲的图像呈现出人眼能够感受到的更真实的形式。

其中，提供两种校正的方式供用户选择，分别为：
1. 用户根据鱼眼畸变的类型及校正模型输入配置参数列表对图像进行校正
2. 用户使用 Grid_Info(输入输出图像坐标映射关系描述)文件校正图像，以获得更好的图像校正效果

## 语法

```c++
bm_status_t bmcv_dwa_fisheye(bm_handle_t          handle,
                             bm_image             input_image,
                             bm_image             output_image,
                             bmcv_fisheye_attr_s  fisheye_attr);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| input_image | 输入 | 输入的畸变图像，通过调用 bm_image_create 创建 |
| output_image | 输出 | 输出的畸变校正后的图像，通过调用 bm_image_create 创建 |
| fisheye_attr | 输入 | Fisheye功能的参数配置列表，包括 bEnable bBgColor u32BgColor s32HorOffset s32VerOffset u32TrapezoidCoef s32FanStrength enMountMode enUseMode u32RegionNum enViewMode \*grid_info |

## 返回值

该函数成功调用时，返回 BM_SUCCESS。

## 数据类型说明

### bmcv_fisheye_attr_s 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| bEnable | 输入 | 配置范围:bool，是否开启鱼眼校正功能 |
| bBgColor | 输入 | 配置范围:bool，是否使用背景颜色功能 |
| u32BgColor | 输入 | 配置范围:[0, 0xffffff]，背景颜色的 RGB888 值，bBgColor=1 时生效 |
| s32HorOffset | 输入 | 图像中心点相对于物理中心点的水平偏移 |
| s32VerOffset | 输入 | 图像中心点相对于物理中心点的垂直偏移 |
| u32TrapezoidCoef | 输入 | 配置范围:[0, 32]，梯形校正强度系数，默认输入配置为0 |
| s32FanStrength | 输入 | 配置范围:[-760, 760]，扇形校正强度系数，默认输入配置为0 |
| enMountMode | 输入 | 配置范围:[0, 2]，鱼眼校正的安装模式，包括地装、顶装、和壁装三种安装模式 |
| enUseMode | 输入 | 配置范围:[1, 9]，鱼眼校正的应用模式 |
| u32RegionNum | 输入 | 配置范围:[1, 4]，鱼眼校正的区域数量 |
| enViewMode | 输入 | 配置范围:[0, 3], 客户端的鱼眼视图模式，即不同的鱼眼摄像头观看模式 |
| grid_info | 输入 | 用于存储 grid_info 的信息，包含 grid_info 的大小和数据 |

### 鱼眼校正的应用模式

| 应用模式 | 效果示例 |
|---------|----------|
| BMCV_MODE_PANORAMA_360 | |
| BMCV_MODE_PANORAMA_180 | |
| BMCV_MODE_01_1O | |
| BMCV_MODE_02_1O4R | |
| BMCV_MODE_03_4R | |
| BMCV_MODE_04_1P2R | |
| BMCV_MODE_05_1P2R | |
| BMCV_MODE_06_1P | |
| BMCV_MODE_07_2P | |

注：BMCV_MODE_STEREO_FIT暂不支持。

### Fisheye Correction 客户端的鱼眼视图模式 enViewMode 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| BMCV_FISHEYE_VIEW_360_PANORAMA | 输入 | 代表360度全景模式的鱼眼视图 |
| BMCV_FISHEYE_VIEW_180_PANORAMA | 输入 | 代表180度全景模式的鱼眼视图 |
| BMCV_FISHEYE_VIEW_NORMAL | 输入 | 代表普通视图模式 |
| BMCV_FISHEYE_NO_TRANSFORMATION | 输入 | 代表没有任何变换的鱼眼视图模式 |
| BMCV_FISHEYE_VIEW_MODE_BUTT | 输入 | 表示枚举的结束标记 |

## 格式支持

### 1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

### 2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_RGB_PLANAR |
| 2 | FORMAT_YUV420P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_GRAY |

## 注意

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

2. 支持图像的分辨率为32x32~4096x4096，且要求32对齐。

3. 若用户决定使用第一种方式进行图像校正，用户需根据鱼眼畸变的类型及校正模型自行输入配置参数列表 fisheye_attr，此时要将 grid_info 设置为空。

4. 若用户决定使用第二种方式进行图像校正，需提供 Grid_Info 文件，具体使用方式请参考下面的代码示例。

## 代码示例

### 1. 通过配置参数列表进行图像校正

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define YUV_8BIT(y, u, v) ((((y)&0xff) << 16) | (((u)&0xff) << 8) | ((v)&0xff))

int main() {
  int src_h = 1024, src_w = 1024, dst_w = 1280, dst_h = 720, dev_id = 0;
  int yuv_8bit_y = 0, yuv_8bit_u = 0, yuv_8bit_v = 0;
  bm_image_format_ext fmt = FORMAT_YUV420P;
  char *src_name = "path/to/src", *dst_name = "path/to/dst";
  bm_handle_t handle = NULL;
  bmcv_fisheye_attr_s fisheye_attr = {0};
  dst_w = 1280;
  dst_h = 720;
  fmt = FORMAT_RGB_PLANAR;
  fisheye_attr.bEnable = 1;
  fisheye_attr.bBgColor = 1;
  yuv_8bit_y = 0;
  yuv_8bit_u = 128;
  yuv_8bit_v = 128;
  fisheye_attr.u32BgColor = YUV_8BIT(yuv_8bit_y, yuv_8bit_u, yuv_8bit_v);
  fisheye_attr.s32HorOffset = src_w / 2;
  fisheye_attr.s32VerOffset = src_h / 2;
  fisheye_attr.u32TrapezoidCoef = 0;
  fisheye_attr.s32FanStrength = 0;
  fisheye_attr.enMountMode = 0;
  fisheye_attr.enUseMode = 1;
  fisheye_attr.enViewMode = 0;
  fisheye_attr.u32RegionNum = 1;
  fisheye_attr.grid_info.u.system.system_addr = NULL;
  fisheye_attr.grid_info.size = 0;
  dst_name = "dwa_fisheye_output_rand.yuv";
  // rand_mode = 1;
  int ret = (int)bm_dev_request(&handle, dev_id);
  if (ret != 0) {
      printf("Create bm handle failed. ret = %d\n", ret);
      exit(-1);
  }
  bm_image src, dst;

  bm_image_create(handle, src_h, src_w, fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
  bm_image_create(handle, dst_h, dst_w, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

  ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
  ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

  int image_byte_size[4] = {0};
  bm_image_get_byte_size(src, image_byte_size);
  int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
  unsigned char *input_data = (unsigned char *)malloc(byte_size);
  FILE *fp_src = fopen(src_name, "rb");
  if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
    printf("file size is less than required bytes%d\n", byte_size);
  };
  fclose(fp_src);
  void* in_ptr[4] = {(void *)input_data,
                      (void *)((unsigned char*)input_data + image_byte_size[0]),
                      (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                      (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
  bm_image_copy_host_to_device(src, in_ptr);

  bmcv_dwa_fisheye(handle, src, dst, fisheye_attr);

  bm_image_get_byte_size(src, image_byte_size);
  byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
  unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
  void* out_ptr[4] = {(void*)output_ptr,
                      (void*)((unsigned char*)output_ptr + image_byte_size[0]),
                      (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                      (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
  bm_image_copy_device_to_host(src, (void **)out_ptr);

  FILE *fp_dst = fopen(dst_name, "wb");
  if (fwrite((void *)input_data, 1, byte_size, fp_dst) < (unsigned int)byte_size){
      printf("file size is less than %d required bytes\n", byte_size);
  };
  fclose(fp_dst);

  free(input_data);
  free(output_ptr);
  bm_image_destroy(&src);
  bm_image_destroy(&dst);

  bm_dev_free(handle);

  return 0;
}
```

# bmcv_dwa_gdc

## 描述
去畸变仿射(DWA)模块的几何畸变校正功能，通过校正镜头引起的图像畸变（针对桶形畸变 (Barrel Distortion) 及枕形畸变 (Pincushion Distortion) ），使图像中的直线变得更加准确和几何正确，提高图像的质量和可视化效果。

其中，提供两种畸变校正的方式供用户选择，分别为：
1. 用户根据图像畸变的类型及校正强度输入配置参数列表对图像进行校正
2. 用户使用 Grid_Info(输入输出图像坐标映射关系描述)文件校正图像，以获得更好的图像校正效果

## 语法

```cpp
bm_status_t bmcv_dwa_gdc(bm_handle_t          handle,
                         bm_image             input_image,
                         bm_image             output_image,
                         bmcv_gdc_attr        ldc_attr);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| input_image | 输入 | 输入的畸变图像，通过调用 bm_image_create 创建 |
| output_image | 输出 | 输出的畸变校正后的图像，通过调用 bm_image_create 创建 |
| ldc_attr | 输入 | GDC功能的参数配置列表，包括bAspect s32XRatio s32YRatio s32XYRatio s32CenterXOffset s32CenterYOffset s32DistortionRatio *grid_info |

## 返回值
该函数成功调用时，返回 BM_SUCCESS。

## 数据类型说明

### bmcv_gdc_attr 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| bAspect | 输入 | 畸变校正的过程中是否保持幅型比，0：不保持，1：保持 |
| s32XRatio | 输入 | 配置范围:[0, 100]，水平方向视野大小参数，bAspect=0 时有效 |
| s32YRatio | 输入 | 配置范围:[0, 100]，垂直方向视野大小参数，bAspect=0 时有效 |
| s32XYRatio | 输入 | 配置范围:[0, 100]，视野大小参数，bAspect=1 时有效 |
| s32CenterXOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的水平偏移 |
| s32CenterYOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的垂直偏移 |
| s32DistortionRatio | 输入 | 配置范围:[-300, 500]，畸变校正强度参数，畸变类型为桶形时配置为负，畸变类型为枕形时配置为负 |
| grid_info | 输入 | 用于存储 grid_info 的信息，包含 grid_info 的大小和数据 |

## 格式支持

### 1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

### 2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_RGB_PLANAR |
| 2 | FORMAT_YUV420P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_GRAY |

## 注意

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
2. 支持图像的分辨率为32x32~4096x4096，且要求宽 64 stride对齐。
3. 若用户决定使用第一种方式进行图像校正，需根据图像畸变的类型及校正强度自行输入配置参数列表 ldc_attr，此时要将 grid_info 设置为空。
4. 若用户决定使用第二种方式进行图像校正，需提供 Grid_Info 文件，具体使用方式请参考下面的代码示例。

## 代码示例

### 1. 通过配置参数列表进行图像校正

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int main() {
    int src_h = 1080, src_w = 1920, dev_id = 0;
    bm_image_format_ext fmt = FORMAT_YUV420P;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    bmcv_gdc_attr ldc_attr = {true, 0, 0, 0, 0, 0, -200, };
    fmt = FORMAT_RGB_PLANAR;
    ldc_attr.grid_info.size = 0;
    ldc_attr.grid_info.u.system.system_addr = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;
    int dst_w, dst_h;

    bm_image_create(handle, src_h, src_w, fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);

    dst_w = src_w;
    dst_h = src_h;
    bm_image_create(handle, dst_h, dst_w, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    for (int i = 0; i < 4; i++) {
        printf("image_byte_size[%d] is : %d\n", i, image_byte_size[i]);
    }
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    // int byte_size = src_w * src_h * 3 / 2;
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
    printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    bm_image_copy_host_to_device(src, (void *)&input_data);

    bmcv_dwa_gdc(handle, src, dst, ldc_attr);

    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + dst_w * dst_h),
                        (void*)((unsigned char*)output_ptr + 5 / 4 * dst_w * dst_w)};
    bm_image_copy_device_to_host(dst, (void **)out_ptr);

    FILE *fp_dst = fopen(dst_name, "wb");
    if (fwrite((void *)input_data, 1, byte_size, fp_dst) < (unsigned int)byte_size){
        printf("file size is less than %d required bytes\n", byte_size);
    };
    fclose(fp_dst);

    free(input_data);
    free(output_ptr);
    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);

    return 0;
}
```

### 2. 通过 Grid_Info 文件进行图像校正

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int main() {
    int src_h = 1080, src_w = 1920, dst_h = 1080, dst_w = 1920, dev_id = 0;
    bm_image_format_ext fmt = FORMAT_YUV420P;
    char *src_name = "path/to/src", *dst_name = "path/to/dst", *grid_name = "path/to/grid_info";
    bm_handle_t handle = NULL;
    bmcv_gdc_attr ldc_attr = {true, 0, 0, 0, 0, 0, -200, };
    fmt = FORMAT_RGB_PLANAR;
    ldc_attr.grid_info.size = 0;
    ldc_attr.grid_info.u.system.system_addr = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    FILE *fp = fopen(grid_name, "rb");
    if (!fp) {
        printf("open file:%s failed.\n", grid_name);
        exit(-1);
    }
    u32 grid_size = 32768;    // grid_info文件的字节数
    char *grid_data = (char *)malloc(grid_size);
    fread(grid_data, 1, grid_size, fp);

    fclose(fp);

    bm_image src, dst;
    bm_image_create(handle, src_h, src_w, fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, dst_h, dst_w, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    for (int i = 0; i < 4; i++) {
        printf("image_byte_size[%d] is : %d\n", i, image_byte_size[i]);
    }
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    // int byte_size = src_w * src_h * 3 / 2;
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
    printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    bm_image_copy_host_to_device(src, (void *)&input_data);

    ldc_attr.grid_info.u.system.system_addr = (void *)grid_data;
    ldc_attr.grid_info.size = grid_size;

    bmcv_dwa_gdc(handle, src, dst, ldc_attr);

    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + dst_w * dst_h),
                        (void*)((unsigned char*)output_ptr + 5 / 4 * dst_w * dst_w)};
    bm_image_copy_device_to_host(dst, (void **)out_ptr);

    FILE *fp_dst = fopen(dst_name, "wb");
    if (fwrite((void *)input_data, 1, byte_size, fp_dst) < (unsigned int)byte_size){
        printf("file size is less than %d required bytes\n", byte_size);
    };
    fclose(fp_dst);

    free(input_data);
    free(output_ptr);
    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);

    return 0;
}
```

# bmcv_dwa_rot

## 描述
去畸变仿射(DWA)模块的旋转功能，通过围绕固定点旋转图像，改变其方向与角度，从而使其在平面上发生旋转。

## 语法

```c++
bm_status_t bmcv_dwa_rot( bm_handle_t          handle,
                          bm_image             input_image,
                          bm_image             output_image,
                          bmcv_rot_mode        rot_mode);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| input_image | 输入 | 输入的待旋转图像，通过调用 bm_image_create 创建 |
| output_image | 输出 | 输出的旋转后图像，通过调用 bm_image_create 创建 |
| rot_mode | 输入 | 旋转类型，取值为[0, 4]内的整数，其中0为0°，1为90°，2为180°，3为270°，4为xy flip |

## 返回值
该函数成功调用时，返回 BM_SUCCESS。

## 数据类型说明

```cpp
typedef enum bmcv_rot_mode_ {
    BMCV_ROTATION_0 = 0,
    BMCV_ROTATION_90,
    BMCV_ROTATION_180,
    BMCV_ROTATION_270,
    BMCV_ROTATION_XY_FLIP,
    BMCV_ROTATION_MAX
} bmcv_rot_mode;
```

* BMCV_ROTATION_0 代表0度的旋转，即图像不进行旋转，保持原状。
* BMCV_ROTATION_90 代表90度的旋转，即图像顺时针旋转90度。
* BMCV_ROTATION_180 代表180度的旋转，即图像顺时针旋转180度。
* BMCV_ROTATION_270 代表270度的旋转，即图像顺时针旋转270度。
* BMCV_ROTATION_XY_FLIP 代表XY翻转，即图像在X轴和Y轴上都进行翻转（镜像翻转）。
* BMCV_ROTATION_MAX 代表枚举最大值，用于指示枚举的结束或作为范围检查的标记。

## 格式支持

### 1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

### 2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_RGB_PLANAR |
| 2 | FORMAT_YUV420P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_GRAY |

## 注意

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
2. 支持图像的分辨率为32x32~4096x4096，且要求32对齐。

## 代码示例

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int main() {
    int src_h = 1080, src_w = 1920, dev_id = 0;
    bm_image_format_ext fmt = FORMAT_GRAY;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    bmcv_rot_mode rot_mode = BMCV_ROTATION_0;
    bm_status_t ret;
    bm_image src, dst;
    int dst_w, dst_h;
    ret = bm_dev_request(&handle, dev_id);

    bm_image_create(handle, src_h, src_w, fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    dst_w = src_w;
    dst_h = src_h;

    bm_image_create(handle, dst_h, dst_w, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
    printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    bmcv_dwa_rot(handle, src, dst, rot_mode);

    bm_image_get_byte_size(src, image_byte_size);
    byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + image_byte_size[0]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_device_to_host(src, (void **)out_ptr);

    FILE *fp_dst = fopen(dst_name, "wb");
    if (fwrite((void *)input_data, 1, byte_size, fp_dst) < (unsigned int)byte_size){
        printf("file size is less than %d required bytes\n", byte_size);
    };
    fclose(fp_dst);

    free(input_data);
    free(output_ptr);
    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);

    return ret;
}
```

# bmcv_feature_match

该接口用于将网络得到特征点（int8格式）与数据库中特征点（int8格式）进行比对，输出最佳匹配的top-k。

## 接口形式：

```c
bm_status_t bmcv_feature_match(
            bm_handle_t handle,
            bm_device_mem_t input_data_global_addr,
            bm_device_mem_t db_data_global_addr,
            bm_device_mem_t output_sorted_similarity_global_addr,
            bm_device_mem_t output_sorted_index_global_addr,
            int batch_size,
            int  feature_size,
            int db_size,
            int sort_cnt,
            int rshiftbits);
```

## 参数说明：

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input_data_global_addr
  输入参数。所要比对的特征点数据存储的地址。该数据按照 batch_size * feature_size 的数据格式进行排列。batch_size，feature_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t db_data_global_addr
  输入参数。数据库的特征点数据存储的地址。该数据按照 feature_size * db_size 的数据格式进行排列。feature_size，db_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t output_sorted_similarity_global_addr
  输出参数。每个batch得到的比对结果的值中最大几个值（降序排列）存储地址，具体取多少个值由sort_cnt决定。该数据按照 batch_size * sort_cnt 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t output_sorted_index_global_addr
  输出参数。每个batch得到的比对结果的在数据库中的序号的存储地址。如对于 batch 0 ，如果 output_sorted_similarity_global_addr 中 bacth 0 的数据是由输入数据与数据库的第800组特征点进行比对得到的，那么 output_sorted_index_global_addr 所在地址对应 batch 0 的数据为800. output_sorted_similarity_global_addr 中的数据按照 batch_size * sort_cnt 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* int batch_size
  输入参数。待输入数据的 batch 个数，如输入数据有4组特征点，则该数据的 batch_size 为4。batch_size最大值不应超过10。

* int feature_size
  输入参数。每组数据的特征点个数。feature_size最大值不应该超过3000。

* int db_size
  输入参数。数据库中数据特征点的组数。db_size最大值不应该超过100000。

* int sort_cnt
  输入参数。每个 batch 对比结果中所要排序个数，也就是输出结果个数，如需要最大的3个比对结果，则sort_cnt设置为3。该值默认为1。sort_cnt最大值不应该超过30。

* int rshiftbits
  输入参数。对结果进行右移处理的位数，右移采用round对小数进行取整处理。该参数默认为0。

## 返回值说明:

* BM_SUCCESS: 成功
* 其他: 失败

# bmcv_feature_match_normalized

该接口用于将网络得到特征点（float格式）与数据库中特征点（float格式）进行比对，输出最佳匹配。

## 接口形式

```c
bm_status_t bmcv_feature_match_normalized(
            bm_handle_t handle,
            bm_device_mem_t input_data_global_addr,
            bm_device_mem_t db_data_global_addr,
            bm_device_mem_t db_feature_global_addr,
            bm_device_mem_t output_similarity_global_addr,
            bm_device_mem_t output_index_global_addr,
            int batch_size,
            int feature_size,
            int db_size);
```

## 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_device_mem_t input_data_global_addr**  
  输入参数。所要比对的特征点数据存储的地址。该数据按照 batch_size * feature_size 的数据格式进行排列。batch_size，feature_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

- **bm_device_mem_t db_data_global_addr**  
  输入参数。数据库的特征点数据存储的地址。该数据按照 feature_size * db_size 的数据格式进行排列。feature_size，db_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

- **bm_device_mem_t db_feature_global_addr**  
  输入参数。数据库的特征点的 feature_size 方向模的倒数的地址。该数据按照 db_size 的数据格式进行排列。

- **bm_device_mem_t output_similarity_global_addr**  
  输出参数。每个batch得到的比对结果的值中最大值存储地址。该数据按照 batch_size 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

- **bm_device_mem_t output_index_global_addr**  
  输出参数。每个batch得到的比对结果的在数据库中的序号的存储地址。如对于 batch 0 ，如果 output_sorted_similarity_global_addr 中 bacth 0 的数据是由输入数据与数据库的第800组特征点进行比对得到的，那么 output_sorted_index_global_addr 所在地址对应 batch 0 的数据为800. output_sorted_similarity_global_addr 中的数据按照 batch_size 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

- **int batch_size**  
  输入参数。待输入数据的 batch 个数，如输入数据有4组特征点，则该数据的 batch_size 为4。batch_size最大值不应超过 10。

- **int feature_size**  
  输入参数。每组数据的特征点个数。feature_size最大值不应该超过1000。

- **int db_size**  
  输入参数。数据库中数据特征点的组数。db_size最大值不应该超过90000。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 注意事项

1. 输入数据 和 数据库中数据的数据类型为 float 类型。
2. 输出的比对结果数据类型为 float，输出的序号类型为 int。
3. 数据库中的数据在内存的排布为 feature_size * db_size，因此需要将一组特征点进行转置之后再放入数据库中。
4. db_feature_global_addr 模的倒数计算方法为：1 / sqrt(y1 * y1 + y2 * y2 + ...... + yn * yn);

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static int calc_sqrt_transposed(float** feature, int rows, int cols, float* db_feature)
{
    int i, j;
    float tmp;
    float result;

    for (i = 0; i < cols; ++i) {
        tmp = 0.f;
        for (j = 0; j < rows; ++j) {
            tmp += feature[j][i] * feature[j][i];
        }
        result = 1.f / sqrt(tmp);
        db_feature[i] = result;
    }

    return 0;
}

int main()
{
    int batch_size = rand() % 8 + 1;
    int feature_size = rand() % 1000 + 1;
    int db_size = (rand() % 90 + 1) * 1000;
    bm_handle_t handle;
    int ret = 0;

    ret = (int)bm_dev_request(&handle, 0);
    if (ret) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return ret;
    }

    float* input_data = (float*)malloc(sizeof(float) * batch_size * feature_size);
    float* db_data = (float*)malloc(sizeof(float) * db_size * feature_size);
    float* db_feature = (float*)malloc(sizeof(float) * db_size);
    float* output_similarity = (float*)malloc(sizeof(float) * batch_size); /*float*/
    int* output_index = (int*)malloc(sizeof(int) * batch_size);
    int i, j;

    float** db_content_vec = (float**)malloc(feature_size * sizeof(float*)); /*row = feature_size col = db_size*/
    for (i = 0; i < feature_size; ++i) {
        db_content_vec[i] = (float*)malloc(db_size * sizeof(float));
        for (j = 0; j < db_size; ++j) {
            db_content_vec[i][j] = rand() % 20 -10;
        }
    }

    float** input_content_vec = (float**)malloc(batch_size * sizeof(float*)); /*row = batch_size col = feature_size*/
    for (i = 0; i < batch_size; ++i) {
        input_content_vec[i] = (float*)malloc(feature_size * sizeof(float));
        for (j = 0; j < feature_size; ++j) {
            input_content_vec[i][j] = rand() % 20 -10;
        }
    }

    float** ref_res = (float**)malloc(sizeof(float*) * batch_size); /* row = batch_size col = db_size */
    for (i = 0; i < batch_size; ++i) {
        ref_res[i] = (float*)malloc(db_size * sizeof(float));
    }

    for (i = 0; i < feature_size; ++i) {
        for (j = 0; j < db_size; ++j) {
            db_data[i * db_size + j] = db_content_vec[i][j];
        }
    }

    ret = calc_sqrt_transposed(db_content_vec, feature_size, db_size, db_feature);

    for (i = 0; i < batch_size; i++) {
        for (j = 0; j < feature_size; j++) {
            input_data[i * feature_size + j] = input_content_vec[i][j];
        }
    }

    ret = bmcv_feature_match_normalized(handle, bm_mem_from_system(input_data), bm_mem_from_system(db_data),
                                bm_mem_from_system(db_feature), bm_mem_from_system(output_similarity),
                                bm_mem_from_system(output_index), batch_size, feature_size, db_size);

    free(input_data);
    free(db_data);
    free(db_feature);
    free(output_similarity);
    free(output_index);
    for(i = 0; i < batch_size; i++) {
        free(input_content_vec[i]);
        free(ref_res[i]);
    }
    for(i = 0; i < feature_size; i++) {
        free(db_content_vec[i]);
    }
    free(input_content_vec);
    free(db_content_vec);
    free(ref_res);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_fft

FFT运算。完整的使用步骤包括创建、执行、销毁三步。

## 创建

支持一维或者两维的FFT计算，其区别在于创建过程中，后面的执行和销毁使用相同的接口。

对于一维的FFT，支持多batch的运算，接口形式如下：

```c
bm_status_t bmcv_fft_1d_create_plan(
            bm_handle_t handle,
            int batch,
            int len,
            bool forward,
            void** plan);
```

### 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **int batch**  
  输入参数。batch的数量。

- **int len**  
  输入参数。每个batch的长度。len需要是2、3、4或5的幂。

- **bool forward**  
  输入参数。是否为正向变换，false表示逆向变换。

- **void\*\* plan**  
  输出参数。执行阶段需要使用的句柄。

### 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

对于两维M * N的FFT运算，接口形式如下：

```c
bm_status_t bmcv_fft_2d_create_plan(
            bm_handle_t handle,
            int M,
            int N,
            bool forward,
            void** plan);
```

### 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **int M**  
  输入参数。第一个维度的大小。

- **int N**  
  输入参数。第二个维度的大小。

- **bool forward**  
  输入参数。是否为正向变换，false表示逆向变换。

- **void\*\* plan**  
  输出参数。执行阶段需要使用的句柄。

### 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 执行

使用上述创建后的plan就可以开始真正的执行阶段了，支持复数输入和实数输入两种接口，其格式分别如下：

```c
bm_status_t bmcv_fft_execute(
            bm_handle_t handle,
            bm_device_mem_t inputReal,
            bm_device_mem_t inputImag,
            bm_device_mem_t outputReal,
            bm_device_mem_t outputImag,
            const void *plan);

bm_status_t bmcv_fft_execute_real_input(
            bm_handle_t handle,
            bm_device_mem_t inputReal,
            bm_device_mem_t outputReal,
            bm_device_mem_t outputImag,
            const void *plan);
```

### 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_device_mem_t inputReal**  
  输入参数。存放输入数据实数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

- **bm_device_mem_t inputImag**  
  输入参数。存放输入数据虚数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

- **bm_device_mem_t outputReal**  
  输出参数。存放输出结果实数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

- **bm_device_mem_t outputImag**  
  输出参数。存放输出结果虚数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

- **const void\* plan**  
  输入参数。创建阶段所得到的句柄。

### 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

# 销毁

当执行完成后需要销毁所创建的句柄。

```c
void bmcv_fft_destroy_plan(bm_handle_t handle, void* plan);
```

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

int main()
{
    bm_handle_t handle;
    int ret = 0;
    int i;
    int L = 100;
    int batch = 100;
    bool forward = true;
    bool realInput = false;

    ret = (int)bm_dev_request(&handle, 0);
    if (ret) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return ret;
    }

    float* XRHost = (float*)malloc(L * batch * sizeof(float));
    float* XIHost = (float*)malloc(L * batch * sizeof(float));
    float* YRHost_tpu = (float*)malloc(L * batch * sizeof(float));
    float* YIHost_tpu = (float*)malloc(L * batch * sizeof(float));

    for (i = 0; i < L * batch; ++i) {
        XRHost[i] = (float)rand() / RAND_MAX;
        XIHost[i] = realInput ? 0 : ((float)rand() / RAND_MAX);
    }

    bm_device_mem_t XRDev, XIDev, YRDev, YIDev;
    void* plan = NULL;

    ret = bm_malloc_device_byte(handle, &XRDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &XIDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &YRDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &YIDev, L * batch * sizeof(float));

    ret = bm_memcpy_s2d(handle, XRDev, XRHost);
    ret = bm_memcpy_s2d(handle, XIDev, XIHost);

    ret = bmcv_fft_2d_create_plan(handle, L, batch, forward, &plan);

    ret = bmcv_fft_execute(handle, XRDev, XIDev, YRDev, YIDev, plan);
    if (ret != BM_SUCCESS) {
        printf("bmcv_fft_execute failed!\n");
        if (plan != NULL) {
            bmcv_fft_destroy_plan(handle, plan);
        }
    }
    ret = bm_memcpy_d2s(handle, (void*)YRHost_tpu, YRDev);
    ret = bm_memcpy_d2s(handle, (void*)YIHost_tpu, YIDev);

    if (plan != NULL) {
        bmcv_fft_destroy_plan(handle, plan);
    }

    free(XRHost);
    free(XIHost);
    free(YRHost_tpu);
    free(YIHost_tpu);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_gemm

该接口可以实现 float32 类型矩阵的通用乘法计算，如下公式：

C = α × A × B + β × C

其中，A、B、C均为矩阵，α 和 β 均为常系数

## 接口形式：

```c
bm_status_t bmcv_gemm(
            bm_handle_t handle,
            bool is_A_trans,
            bool is_B_trans,
            int M,
            int N,
            int K,
            float alpha,
            bm_device_mem_t A,
            int lda,
            bm_device_mem_t B,
            int ldb,
            float beta,
            bm_device_mem_t C,
            int ldc);
```

## 参数说明：

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bool is_A_trans
  输入参数。设定矩阵 A 是否转置

* bool is_B_trans
  输入参数。设定矩阵 B 是否转置

* int M
  输入参数。矩阵 A 和矩阵 C 的行数

* int N
  输入参数。矩阵 B 和矩阵 C 的列数

* int K
  输入参数。矩阵 A 的列数和矩阵 B 的行数

* float alpha
  输入参数。数乘系数

* bm_device_mem_t A
  输入参数。根据数据存放位置保存左矩阵 A 数据的 device 地址或者 host 地址。如果数据存放于 host 空间则内部会自动完成 s2d 的搬运

* int lda
  输入参数。矩阵 A 的 leading dimension, 即第一维度的大小，在行与行之间没有stride的情况下即为 A 的列数（不做转置）或行数（做转置）

* bm_device_mem_t B
  输入参数。根据数据存放位置保存右矩阵 B 数据的 device 地址或者 host 地址。如果数据存放于 host 空间则内部会自动完成 s2d 的搬运。

* int ldb
  输入参数。矩阵 C 的 leading dimension, 即第一维度的大小，在行与行之间没有stride的情况下即为 B 的列数（不做转置）或行数（做转置。

* float beta
  输入参数。数乘系数。

* bm_device_mem_t C
  输出参数。根据数据存放位置保存矩阵 C 数据的 device 地址或者 host 地址。如果是 host 地址，则当beta不为0时，计算前内部会自动完成 s2d 的搬运，计算后再自动完成 d2s 的搬运。

* int ldc
  输入参数。矩阵 C 的 leading dimension, 即第一维度的大小，在行与行之间没有stride的情况下即为 C 的列数。

## 返回值说明:

* BM_SUCCESS: 成功
* 其他: 失败

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define GEMM_INPUT_NUM 3
#define GEMM_OUTPUT_NUM 1

static int assign_values_to_matrix(float* matrix, int size)
{
    int i;

    if (matrix == NULL || size <= 0) {
        printf("the assign_values_to_matrix func error!\n");
        return -1;
    }

    for (i = 0; i < size; ++i) {
        matrix[i] = (rand() % 100) * 0.01f;
    }

    return 0;
}

int main()
{
    int M = 1 + rand() % 800;
    int N = 1 + rand() % 800;
    int K = 1 + rand() % 800;
    int rand_sign_a = (rand() % 2 == 0) ? 1 : -1;
    int rand_sign_b = (rand() % 2 == 0) ? 1 : -1;
    float alpha = rand_sign_a * (rand() % 100) * 0.05;
    float beta  = rand_sign_b * (rand() % 100) * 0.05;
    bool if_A_trans = rand() % 2;
    bool if_B_trans = rand () % 2;
    int ret = 0;
    bm_handle_t handle;

    if (if_A_trans) {
        if_B_trans = true;
    }

    ret = bm_dev_request(&handle, 0);
    if (ret) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return ret;
    }

    float* src_A = (float*)malloc(M * K * sizeof(float));
    float* src_B = (float*)malloc(N * K * sizeof(float));
    float* src_C = (float*)malloc(M * N * sizeof(float));
    int lda = if_A_trans ? M : K;
    int ldb = if_B_trans ? K : N;

    ret = assign_values_to_matrix(src_A, M * K);
    ret = assign_values_to_matrix(src_B, N * K);
    ret = assign_values_to_matrix(src_C, M * N);

    ret= bmcv_gemm(handle, if_A_trans, if_B_trans, M, N, K, alpha, bm_mem_from_system((void *)src_A),
                    lda, bm_mem_from_system((void *)src_B), ldb, beta,
                    bm_mem_from_system((void *)src_C), N);

    free(src_A);
    free(src_B);
    free(src_C);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_gemm_ext

该接口可以实现 fp32/fp16 类型矩阵的通用乘法计算，如下公式：

Y = α × A × B + β × C

其中，A、B、C、Y均为矩阵，α 和 β 均为常系数

## 接口形式：

```c
bm_status_t bmcv_gemm_ext(
            bm_handle_t handle,
            bool is_A_trans,
            bool is_B_trans,
            int M,
            int N,
            int K,
            float alpha,
            bm_device_mem_t A,
            bm_device_mem_t B,
            float beta,
            bm_device_mem_t C,
            bm_device_mem_t Y,
            bm_image_data_format_ext input_dtype,
            bm_image_data_format_ext output_dtype);
```

## 参数说明：

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bool is_A_trans
  输入参数。设定矩阵 A 是否转置

* bool is_B_trans
  输入参数。设定矩阵 B 是否转置

* int M
  输入参数。矩阵 A、C、Y 的行数

* int N
  输入参数。矩阵 B、C、Y 的列数

* int K
  输入参数。矩阵 A 的列数和矩阵 B 的行数

* float alpha
  输入参数。数乘系数

* bm_device_mem_t A
  输入参数。根据数据存放位置保存左矩阵 A 数据的 device 地址，需在使用前完成数据s2d搬运。

* bm_device_mem_t B
  输入参数。根据数据存放位置保存右矩阵 B 数据的 device 地址，需在使用前完成数据s2d搬运。

* float beta
  输入参数。数乘系数。

* bm_device_mem_t C
  输入参数。根据数据存放位置保存矩阵 C 数据的 device 地址，需在使用前完成数据s2d搬运。

* bm_device_mem_t Y
  输出参数。矩阵 Y 数据的 device 地址，保存输出结果。

* bm_image_data_format_ext input_dtype
  输入参数。输入矩阵A、B、C的数据类型。支持输入FP16-输出FP16或FP32，输入FP32-输出FP32。

* bm_image_data_format_ext output_dtype
  输入参数。输出矩阵Y的数据类型。

## 返回值说明:

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项：

1. 该接口在 FP16 输入、A 矩阵转置的情况下，M 仅支持小于等于 64 的取值。
2. 该接口不支持 FP32 输入且 FP16 输出。

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define GEMM_INPUT_NUM 3
#define GEMM_OUTPUT_NUM 1

static int assign_values_to_matrix(float* matrix, int size)
{
    int i;

    if (matrix == NULL || size <= 0) {
        printf("the assign_values_to_matrix func error!\n");
        return -1;
    }

    for (i = 0; i < size; ++i) {
        matrix[i] = (rand() % 100) * 0.01f;
    }

    return 0;
}

int main()
{
    int M = 1 + rand() % 800;
    int N = 1 + rand() % 800;
    int K = 1 + rand() % 800;
    int rand_sign_a = (rand() % 2 == 0) ? 1 : -1;
    int rand_sign_b = (rand() % 2 == 0) ? 1 : -1;
    float alpha = rand_sign_a * (rand() % 100) * 0.05;
    float beta  = rand_sign_b * (rand() % 100) * 0.05;
    bool is_A_trans = rand() % 2;
    bool is_B_trans = rand () % 2;
    int ret = 0;
    bm_handle_t handle;

    if (is_A_trans) {
        is_B_trans = true;
    }

    ret = bm_dev_request(&handle, 0);
    if (ret) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return ret;
    }

    float* A = (float*)malloc(M * K * sizeof(float));
    float* B = (float*)malloc(N * K * sizeof(float));
    float* C = (float*)malloc(M * N * sizeof(float));
    float* tpu_C = (float*)malloc(M * N * sizeof(float));
    bm_image_data_format_ext in_dtype, out_dtype;

    ret = assign_values_to_matrix(A, M * K);
    ret = assign_values_to_matrix(B, N * K);
    ret = assign_values_to_matrix(C, M * N);
    memset(tpu_C, 0.f, sizeof(float) * M * N);

    in_dtype = DATA_TYPE_EXT_FLOAT32;
    out_dtype = DATA_TYPE_EXT_FLOAT32;
    memset(tpu_C, 0.f, sizeof(float) * M * N);

    if (in_dtype == DATA_TYPE_EXT_FP16 && is_A_trans && M > 64) {
        printf("Error! It only support M <= 64 when A is trans and input_dtype is FP16\n");
        return -1;
    }

    unsigned short* A_fp16 = (unsigned short*)malloc(M * K * sizeof(unsigned short));
    unsigned short* B_fp16 = (unsigned short*)malloc(N * K * sizeof(unsigned short));
    unsigned short* C_fp16 = (unsigned short*)malloc(M * N * sizeof(unsigned short));
    unsigned short* Y_fp16 = (unsigned short*)malloc(M * N * sizeof(unsigned short));
    bm_device_mem_t input_dev_buffer[GEMM_INPUT_NUM];
    bm_device_mem_t output_dev_buffer[GEMM_OUTPUT_NUM];

    ret = bm_malloc_device_byte(handle, &input_dev_buffer[0], M * K * sizeof(float));
```

# bmcv_hist_balance

对图像进行直方图均衡化操作，提高图像的对比度。

## 接口形式

```c
bm_status_t bmcv_hist_balance(
    bm_handle_t handle,
    bm_device_mem_t input,
    bm_device_mem_t output,
    int H,
    int W);
```

## 参数说明

- `bm_handle_t handle`：输入参数。bm_handle 句柄
- `bm_device_mem_t input`：输入参数。存放输入图像的 device 空间。其大小为 H * W * sizeof(uint8_t)
- `bm_device_mem_t output`：输出参数。存放输出图像的 device 空间。其大小为 H * W * sizeof(uint8_t)
- `int H`：输入参数。图像的高
- `int W`：输入参数。图像的宽

## 返回值说明

- `BM_SUCCESS`：成功
- 其他：失败

## 注意事项

1. 数据类型仅支持 uint8_t
2. 支持的最小图像尺寸为 H = 1, W = 1
3. 支持的最大图像尺寸为 H = 8192, W = 8192

## 示例代码

```c
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"

int main()
{
    int height = rand() % 8192 + 1;
    int width = rand() % 8192 + 1;
    int ret = 0;
    bm_handle_t handle;
    int i;

    ret = bm_dev_request(&handle, 0);
    if (ret) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return ret;
    }

    int len = height * width;

    uint8_t* inputHost = (uint8_t*)malloc(len * sizeof(uint8_t));
    uint8_t* output_tpu = (uint8_t*)malloc(len * sizeof(uint8_t));

    for (i = 0; i < len; ++i) {
        inputHost[i] = (uint8_t)(rand() % 256);
    }

    bm_device_mem_t input, output;
    int H = height;
    int W = width;

    ret = bm_malloc_device_byte(handle, &output, H * W * sizeof(uint8_t));
    ret = bm_malloc_device_byte(handle, &input, H * W * sizeof(uint8_t));
    ret = bm_memcpy_s2d(handle, input, inputHost);

    ret = bmcv_hist_balance(handle, input, output, H, W);
    ret = bm_memcpy_d2s(handle, output_tpu, output);

    bm_free_device(handle, input);
    bm_free_device(handle, output);

    free(inputHost);
    free(output_tpu);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_hm_distance

## 描述

该接口用来计算两个向量中各个元素的汉明距离，该接口支持启用双核处理。

## 语法

```c
bm_status_t bmcv_hamming_distance(
    bm_handle_t handle,
    bm_device_mem_t input1,
    bm_device_mem_t input2,
    bm_device_mem_t output,
    int bits_len,
    int input1_num,
    int input2_num);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用bm_dev_request获取 |
| input1 | 输入 | 向量1数据的地址信息 |
| input2 | 输入 | 向量2数据的地址信息 |
| output | 输出 | output向量数据的地址信息 |
| bits_len | 输入 | 向量中的每个元素的长度 |
| input1_num | 输入 | 向量1的数据个数 |
| input2_num | 输入 | 向量2的数据个数 |

## 返回值

该函数成功调用时，返回BM_SUCCESS。

## 注意事项

1. bits_len支持到4, 8, 16, 32
2. input1_num支持1～16，input2_num支持2～50000000，但因TPU能调度的存储空间容量有限，不同bits_len和input1_num的组合下，input2_num能支持的最大值可能受限
3. 该接口支持启用双核处理，在运行程序前可通过设置环境变量来改变使用的TPU core，例如：export TPU_CORES=0/1/2/both，如不设置环境变量，默认使用core0处理。其中TPU_CORES=0代表仅启用TPU core0进行处理，TPU_CORES=1代表仅启用TPU core1进行处理，TPU_CORES=2和TPU_CORES=both代表启用双核进行处理

## 代码示例

```c
#include <math.h>
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include "bmcv_api_ext_c.h"

int main() {
    int bits_len = 8;
    int input1_num = 1 + rand() % 16;
    int input2_num = 1 + rand() % 10000;
    bm_handle_t handle;
    bm_status_t ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return -1;
    }

    bm_device_mem_t input1_dev_mem;
    bm_device_mem_t input2_dev_mem;
    bm_device_mem_t output_dev_mem;

    uint32_t* input1_data = (uint32_t*)malloc(input1_num * bits_len * sizeof(uint32_t));
    uint32_t* input2_data = (uint32_t*)malloc(input2_num * bits_len * sizeof(uint32_t));
    uint32_t* output_tpu  = (uint32_t*)malloc(input1_num * input2_num * sizeof(uint32_t));

    printf("bits_len is %u\n", bits_len);
    printf("input1_data len is %u\n", input1_num);
    printf("input2_data len is %u\n", input2_num);
    memset(input1_data, 0, input1_num * bits_len * sizeof(uint32_t));
    memset(input2_data, 0, input2_num * bits_len * sizeof(uint32_t));
    memset(output_tpu,  0,  input1_num * input2_num * sizeof(uint32_t));

    // fill data
    for(int i = 0; i < input1_num * bits_len; i++) {
        input1_data[i] = rand() % 10;
    }
    for(int i = 0; i < input2_num * bits_len; i++) {
        input2_data[i] = rand() % 20 + 1;
    }
    // tpu_cal
    bm_malloc_device_byte(handle, &input1_dev_mem, input1_num * bits_len * sizeof(uint32_t));
    bm_malloc_device_byte(handle, &input2_dev_mem, input2_num * bits_len * sizeof(uint32_t));
    bm_malloc_device_byte(handle, &output_dev_mem, input1_num * input2_num * sizeof(uint32_t));
    bm_memcpy_s2d(handle, input1_dev_mem, input1_data);
    bm_memcpy_s2d(handle, input2_dev_mem, input2_data);

    bmcv_hamming_distance(handle, input1_dev_mem, input2_dev_mem, output_dev_mem, bits_len, input1_num, input2_num);

    bm_memcpy_d2s(handle, output_tpu, output_dev_mem);

    for (int i = 0; i < 8; i++) {
        printf("output_tpu[%d] is: %d\n", i, output_tpu[i]);
    }
    free(input1_data);
    free(input2_data);
    free(output_tpu);
    bm_free_device(handle, input1_dev_mem);
    bm_free_device(handle, input2_dev_mem);
    bm_free_device(handle, output_dev_mem);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_image_axpy

该接口实现 F = A * X + Y，其中 A 是常数，大小为 n * c ，F 、X 、Y 都是大小为n * c * h * w的矩阵。

## 接口形式

```c
bm_status_t bmcv_image_axpy(
            bm_handle_t handle,
            bm_device_mem_t tensor_A,
            bm_device_mem_t tensor_X,
            bm_device_mem_t tensor_Y,
            bm_device_mem_t tensor_F,
            int input_n,
            int input_c,
            int input_h,
            int input_w);
```

## 参数说明

* **handle** - 输入参数。bm_handle 句柄。
* **tensor_A** - 输入参数。存放常数 A 的设备内存地址。
* **tensor_X** - 输入参数。存放矩阵X的设备内存地址。
* **tensor_Y** - 输入参数。存放矩阵Y的设备内存地址。
* **tensor_F** - 输出参数。存放结果矩阵F的设备内存地址。
* **input_n** - 输入参数。n 维度大小。
* **input_c** - 输入参数。c 维度大小。
* **input_h** - 输入参数。h 维度大小。
* **input_w** - 输入参数。w 维度大小。

## 返回值说明

* **BM_SUCCESS**: 成功
* 其他: 失败

## 示例代码

```c
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"

#define N (10)
#define C 256 //(64 * 2 + (64 >> 1))
#define H 8
#define W 8
#define TENSOR_SIZE (N * C * H * W)

int main(){
  int trials = 1;
  int ret = 0;
  bm_handle_t handle;
  ret = bm_dev_request(&handle, 0);
  if (ret != BM_SUCCESS) {
    printf("bm_dev_request failed. ret = %d\n", ret);
    return -1;
  }

  float *tensor_X = malloc(TENSOR_SIZE * sizeof(float));
  float *tensor_A = malloc(N * C * sizeof(float));
  float *tensor_Y = malloc(TENSOR_SIZE * sizeof(float));
  float *tensor_F = malloc(TENSOR_SIZE * sizeof(float));
  int idx_trial;

  for (idx_trial = 0; idx_trial < trials; idx_trial++) {
    for (int idx = 0; idx < TENSOR_SIZE; idx++) {
      tensor_X[idx] = (float)idx - 5.0f;
      tensor_Y[idx] = (float)idx/3.0f - 8.2f;  //y
    }

    for (int idx = 0; idx < N*C; idx++) {
      tensor_A[idx] = (float)idx * 1.5f + 1.0f;
    }

    ret = bmcv_image_axpy(handle,
                        bm_mem_from_system((void *)tensor_A),
                        bm_mem_from_system((void *)tensor_X),
                        bm_mem_from_system((void *)tensor_Y),
                        bm_mem_from_system((void *)tensor_F),
                        N, C, H, W);
    }
  free(tensor_X);
  free(tensor_A);
  free(tensor_Y);
  free(tensor_F);

  bm_dev_free(handle);
  return ret;
}
```

# bmcv_image_circle

## 描述

在图像上绘制圆形。支持绘制空心圆（CIR_LINE）、实心圆（CIR_SHAPE）、和圆形相框（CIR_EMPTY）。

## 语法

```c++
bm_status_t bmcv_image_circle(
    bm_handle_t          handle,
    bm_image             image,
    bmcv_point_t         center,
    int                  radius,
    bmcv_color_t         color,
    int                  line_width)
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image | 输入/输出 | 输入/输出 bm_image 对象。 |
| center | 输入 | 圆心的位置(x, y)（以图片左上角为原点）。 |
| radius | 输入 | 圆的半径。 |
| color | 输入 | 所填充颜色的R/G/B值。 |
| line_width | 输入 | 画圆的线宽，取值范围为[-2, 15], 当传入 -1 时表示绘制实心圆， 当传入 -2 时表示绘制相框。 |

## 数据类型说明

```c++
typedef struct {
    int x;
    int y;
} bmcv_point_t;

typedef struct {
    unsigned char r;
    unsigned char g;
    unsigned char b;
} bmcv_color_t;

typedef enum {
    CIR_EMPTY = -2,
    CIR_SHAPE = -1,
} bmcv_cir_mode;
```

1. x, y 代表坐标点的横纵坐标。
2. CIR_EMPTY 表示相框模式，即填充圆形外部区域，圆形内部不变；
3. CIR_SHAPE 表示绘制实心圆；

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 该 API 所需要满足的图像格式、尺寸等要求与 bmcv_image_vpp_basic 中的表格相同。
2. 输入必须关联 device memory，否则返回失败。

## 代码示例

```c++
bm_handle_t handle;
int src_w = 1920, src_h = 1080, dev_id = 0;
bmcv_point_t center = {960, 540};
bmcv_color_t color = {151, 255, 152};
int radius = 250, line_width = 10;
bm_image_format_ext src_fmt = FORMAT_YUV420P;
char *src_name = "1920x1080_yuv420.bin", *dst_name = "dst.bin";

bm_image src;
bm_dev_request(&handle, 0);
bm_image_create(handle, src_h, src_w, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

bm_read_bin(src,src_name);
bmcv_image_circle(handle, src, center, radius, color, line_width);
bm_write_bin(src, dst_name);

bm_image_destroy(&src);
bm_dev_free(handle);
```

# bmcv_image_copy_to

## 描述

该接口实现将一幅图像拷贝到目的图像的对应内存区域。

## 语法

```c++
bm_status_t bmcv_image_copy_to(
        bm_handle_t handle,
        bmcv_copy_to_atrr_t copy_to_attr,
        bm_image            input,
        bm_image            output
);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| copy_to_attr | 输入 | api 所对应的属性配置。 |
| input | 输入 | 输入 bm_image。 |
| output | 输出 | 输出 bm_image。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 数据类型说明

```c++
typedef struct bmcv_copy_to_atrr_s {
    int           start_x;
    int           start_y;
    unsigned char padding_r;
    unsigned char padding_g;
    unsigned char padding_b;
    int if_padding;
} bmcv_copy_to_atrr_t;
```

* **padding_b** - 表示当 input 的图像要小于输出图像的情况下，多出来的图像 b 通道上被填充的值。
* **padding_r** - 表示当 input 的图像要小于输出图像的情况下，多出来的图像 r 通道上被填充的值。
* **padding_g** - 表示当 input 的图像要小于输出图像的情况下，多出来的图像 g 通道上被填充的值。
* **start_x** - 描述了 copy_to 拷贝到输出图像所在的起始横坐标。
* **start_y** - 描述了 copy_to 拷贝到输出图像所在的起始纵坐标。
* **if_padding** - 表示当 input 的图像要小于输出图像的情况下，是否需要对多余的图像区域填充特定颜色，0表示不需要，1表示需要。当该值填0时，padding_r，padding_g，padding_b 的设置将无效。

## 格式支持

### 1. 输入和输出的数据类型

| num | input data type | output data type |
|-----|-----------------|------------------|
| 1 | | DATA_TYPE_EXT_FLOAT32 |
| 2 | | DATA_TYPE_EXT_1N_BYTE |
| 3 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4 | | DATA_TYPE_EXT_FP16 |
| 5 | | DATA_TYPE_EXT_BF16 |
| 6 | DATA_TYPE_EXT_FLOAT32 | DATA_TYPE_EXT_FLOAT32 |
| 7 | DATA_TYPE_EXT_1N_BYTE_SIGNED | DATA_TYPE_EXT_1N_BYTE_SIGNED |

### 2. 输入和输出支持的色彩格式

| num | image_format |
|-----|--------------|
| 1 | FORMAT_RGB_PLANAR |
| 2 | FORMAT_BGR_PLANAR |
| 3 | FORMAT_RGB_PACKED |
| 4 | FORMAT_BGR_PACKED |

| 5 | FORMAT_GRAY |

**注意：**

1. 在调用 bmcv_image_copy_to()之前必须确保输入的 image 内存已经申请。
2. 为了避免内存越界，输入图像 width + start_x 必须小于等于输出图像 width stride。

**代码示例：**

```cpp
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "bmcv_api_ext_c.h"

typedef enum { COPY_TO_GRAY = 0, COPY_TO_BGR, COPY_TO_RGB } padding_corlor_e;
typedef enum { PLANNER = 0, PACKED } padding_format_e;

static int writeBin(const char* path, void* output_data, int size)
{
    int len = 0;
    FILE* fp_dst = fopen(path, "wb+");

    if (fp_dst == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    len = fwrite((void*)output_data, 1, size, fp_dst);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_dst);
    return 0;
}

int main() {
    int         dev_id = 0;
    bm_handle_t handle;
    bm_status_t ret = bm_dev_request(&handle, dev_id);

    int in_w    = 400;
    int in_h    = 400;
    int out_w   = 800;
    int out_h   = 800;
    int start_x = 200;
    int start_y = 200;

    int image_format = FORMAT_RGB_PLANAR;
    int data_type = DATA_TYPE_EXT_FLOAT32;
    int channel   = 3;

    int image_n = 1;

    float* src_data = (float *)malloc(image_n * channel * in_w * in_h * sizeof(float));
    float* res_data = (float *)malloc(image_n * channel * out_w * out_h * sizeof(float));

    for (int i = 0; i < image_n * channel * in_w * in_h; i++) {
        src_data[i] = rand() % 255;
    }
    // calculate res
    bmcv_copy_to_atrr_t copy_to_attr;
    copy_to_attr.start_x    = start_x;
    copy_to_attr.start_y    = start_y;
    copy_to_attr.padding_r  = 0;
    copy_to_attr.padding_g  = 0;
    copy_to_attr.padding_b  = 0;
    copy_to_attr.if_padding = 1;
    bm_image input, output;
    bm_image_create(handle,
                    in_h,
                    in_w,
                    (bm_image_format_ext)image_format,
                    (bm_image_data_format_ext)data_type,
                    &input, NULL);
    bm_image_alloc_dev_mem(input, BMCV_HEAP1_ID);
    bm_image_copy_host_to_device(input, (void **)&src_data);
    bm_image_create(handle,
                    out_h,
                    out_w,
                    (bm_image_format_ext)image_format,
                    (bm_image_data_format_ext)data_type,
                    &output, NULL);
    bm_image_alloc_dev_mem(output, BMCV_HEAP1_ID);
    ret = bmcv_image_copy_to(handle, copy_to_attr, input, output);

    if (BM_SUCCESS != ret) {
        printf("bmcv_copy_to error 1 !!!\n");
        bm_image_destroy(&input);
        bm_image_destroy(&output);
        free(src_data);
        free(res_data);
        return -1;
    }
    bm_image_copy_device_to_host(output, (void **)&res_data);

    char *dst_name = "path/to/dst";
    writeBin(dst_name, res_data, out_w * out_h * 3);
    writeBin("path/to/src", src_data, in_h * in_w * 3);

    bm_image_destroy(&input);
    bm_image_destroy(&output);
    free(src_data);
    free(res_data);

    return ret;
}
```

# bmcv_image_csc_convert_to

**描述：**

该 API 可以实现对多张图片的 crop、color-space-convert、resize、padding、convert_to及其任意若干个功能的组合。

**语法：**

```cpp
bm_status_t bmcv_image_csc_convert_to(
    bm_handle_t           handle,
    int                   in_img_num,
    bm_image*             input,
    bm_image*             output,
    int*                  crop_num_vec = NULL,
    bmcv_rect_t*          crop_rect = NULL,
    bmcv_padding_atrr_t*  padding_attr = NULL,
    bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR,
    csc_type_t            csc_type = CSC_MAX_ENUM,
    csc_matrix_t*         matrix = NULL,
    bmcv_convert_to_attr* convert_to_attr = NULL);
```

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| in_img_num | 输入 | 输入 bm_image 数量。 |
| *input | 输入 | 输入 bm_image 对象指针，其指向空间的长度由 in_img_num 决定。 |
| *output | 输出 | 输出 bm_image 对象指针，其指向空间的长度由 in_img_num 和 crop_num_vec 共同决定，即所有输入图片 crop 数量之和。 |
| *crop_num_vec | 输入 | 该指针指向对每张输入图片进行 crop 的数量，其指向空间的长度由 in_img_num 决定，如果不使用 crop 功能可填 NULL。 |
| *crop_rect | 输入 | 输出 bm_image 对象所对应的在输入图像上 crop 的参数。 |
| *padding_attr | 输入 | 所有 crop 的目标小图在 dst image 中的位置信息以及要 padding 的各通道像素值，若不使用 padding 功能则设置为 NULL。 |
| algorithm | 输入 | resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR、BMCV_INTER_AREA 和 BMCV_INTER_BICUBIC 四种，默认情况下是双线性差值。 |
| csc_type | 输入 | color space convert 参数类型选择，填 CSC_MAX_ENUM 则使用默认值，默认为 CSC_YCbCr2RGB_BT601 或者 CSC_RGB2YCbCr_BT601，支持的类型见表 csc_type |
| *matrix | 输入 | 如果 csc_type 选择 CSC_USER_DEFINED_MATRIX，则需要传入系数矩阵。 |
| *convert_to_attr | 输入 | 线性变换系数。当convert_to_attr参数非空时，输出格式仅支持FORMAT_RGB_PLANAR和FORMAT_BGR_PLANAR。 |

**csc_type 支持类型：**

- CSC_YCbCr2RGB_BT601
- CSC_YPbPr2RGB_BT601
- CSC_RGB2YCbCr_BT601
- CSC_YCbCr2RGB_BT709
- CSC_RGB2YCbCr_BT709
- CSC_RGB2YPbPr_BT601
- CSC_YPbPr2RGB_BT709
- CSC_RGB2YPbPr_BT709
- CSC_FANCY_PbPr_BT601
- CSC_FANCY_PbPr_BT709
- CSC_USER_DEFINED_MATRIX
- CSC_MAX_ENUM

**数据类型说明：**

```cpp
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

start_x、start_y、crop_w、crop_h分别表示每个输出 bm_image 对象所对应的在输入图像上 crop 的参数，包括起始点x坐标、起始点y坐标、crop图像的宽度以及crop图像的高度。图像左上顶点作为坐标原点。如果不使用 crop 功能可填 NULL。

```cpp
typedef struct bmcv_padding_atrr_s {
    unsigned int  dst_crop_stx;
    unsigned int  dst_crop_sty;
    unsigned int  dst_crop_w;
    unsigned int  dst_crop_h;
    unsigned char padding_r;
    unsigned char padding_g;
    unsigned char padding_b;
    int           if_memset;
} bmcv_padding_atrr_t;
```

1. 目标小图的左上角顶点相对于 dst image 原点（左上角）的offset信息：dst_crop_stx 和 dst_crop_sty；
2. 目标小图经resize后的宽高：dst_crop_w 和 dst_crop_h；
3. dst image 如果是RGB格式，各通道需要padding的像素值信息：padding_r、padding_g、padding_b，当if_memset=1时有效，如果是GRAY图像可以将三个值均设置为同一个值；
4. if_memset表示要不要在该api内部对dst image 按照各个通道的padding值做memset，仅支持RGB和GRAY格式的图像。如果设置为0则用户需要在调用该api前，根据需要 padding 的像素值信息，调用 bmlib 中的 api 直接对 device memory 进行 memset 操作，如果用户对padding的值不关心，可以设置为0忽略该步骤。

```cpp
typedef struct {
    short csc_coe00;
    short csc_coe01;
    short csc_coe02;
    unsigned char csc_add0;
    unsigned char csc_sub0;
    short csc_coe10;
    short csc_coe11;
    short csc_coe12;
    unsigned char csc_add1;
    unsigned char csc_sub1;
    short csc_coe20;
    short csc_coe21;
    short csc_coe22;
    unsigned char csc_add2;
    unsigned char csc_sub2;
} csc_matrix_t;
```

自定义csc_matrix 的系数。

```cpp
typedef struct bmcv_convert_to_attr_s{
        float alpha_0;
        float beta_0;
        float alpha_1;
        float beta_1;
        float alpha_2;
        float beta_2;
} bmcv_convert_to_attr;
```

- alpha_0 描述了第 0 个 channel 进行线性变换的系数
- beta_0 描述了第 0 个 channel 进行线性变换的偏移
- alpha_1 描述了第 1 个 channel 进行线性变换的系数
- beta_1 描述了第 1 个 channel 进行线性变换的偏移
- alpha_2 描述了第 2 个 channel 进行线性变换的系数
- beta_2 描述了第 2 个 channel 进行线性变换的偏移

**返回值：**

该函数成功调用时, 返回 BM_SUCCESS。

**格式支持：**

1. 支持的数据类型为：

| num | input data_type | output data_type |
|-----|-----------------|------------------|
| 1 | | DATA_TYPE_EXT_FLOAT32 |
| 2 | | DATA_TYPE_EXT_1N_BYTE |
| 3 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4 | | DATA_TYPE_EXT_FP16 |
| 5 | | DATA_TYPE_EXT_BF16 |

2. 输入支持色彩格式为：

| num | input image_format |
|-----|-------------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_YUV422P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_NV12 |
| 5 | FORMAT_NV21 |
| 6 | FORMAT_NV16 |
| 7 | FORMAT_NV61 |
| 8 | FORMAT_RGB_PLANAR |
| 9 | FORMAT_BGR_PLANAR |
| 10 | FORMAT_RGB_PACKED |
| 11 | FORMAT_BGR_PACKED |
| 12 | FORMAT_RGBP_SEPARATE |
| 13 | FORMAT_BGRP_SEPARATE |
| 14 | FORMAT_GRAY |

# bmcv_image_csc_overlay

**描述：**

该 API 可以实现对单张图片的 crop、color-space-convert、resize、padding、convert_to、flip、draw/fill rect、circle、overlay任意若干个功能的组合。

**语法：**

```c++
DECL_EXPORT bm_status_t bmcv_image_csc_overlay(
    bm_handle_t             handle,
    int                     crop_num,
    bm_image                input,
    bm_image*               output,
    bmcv_rect_t*            crop_rect = NULL,
    bmcv_padding_attr_t*    padding_attr = NULL,
    bmcv_resize_algorithm   algorithm = BMCV_INTER_LINEAR,
    csc_type_t              csc_type = CSC_MAX_ENUM,
    bmcv_flip_mode          flip_mode = NO_FLIP,
    bmcv_convert_to_attr*   convert_to_attr = NULL,
    bmcv_overlay_attr*      overlay_attr = NULL,
    bmcv_draw_rect_attr*    draw_rect_attr = NULL,
    bmcv_fill_rect_attr*    fill_rect_attr = NULL,
    bmcv_circle_attr*       circle_attr = NULL);
```

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| crop_num | 输入 | 对输入 bm_image 进行 crop 的数量。 |
| input | 输入 | 输入 bm_image 对象。 |
| * output | 输出 | 输出 bm_image 对象指针，其指向空间的长度由 crop_num 决定。 |
| * crop_rect | 输入 | 输出 bm_image 对象所对应的在输入图像上 crop 的参数，其指向空间的长度由 crop_num 决定。若不使用 crop 功能则设置为 NULL。 |
| * padding_attr | 输入 | 所有 crop 的目标小图在 dst image 中的位置信息以及要 padding 的各通道像素值，其指向空间的长度由 crop_num 决定。若不使用 padding 功能则设置为 NULL。 |
| algorithm | 输入 | resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR、BMCV_INTER_AREA 和 BMCV_INTER_BICUBIC 四种，默认情况下是双线性差值。 |
| csc_type | 输入 | color space convert 参数类型选择，填 CSC_MAX_ENUM 则使用默认值，默认为 CSC_YCbCr2RGB_BT601 或者 CSC_RGB2YCbCr_BT601。 |
| flip_mode | 输入 | flip模式，可选择水平翻转，垂直翻转和旋转180度。 |
| *convert_to_attr | 输入 | 线性变换系数，其指向空间的长度为1。若不使用 convert_to 功能则设置为 NULL。当convert_to_attr参数非空时，输出格式仅支持FORMAT_RGB_PLANAR和FORMAT_BGR_PLANAR。 |
| *overlay_attr | 输入 | overlay功能参数，其指向空间的长度由 crop_num 决定。若不使用 overlay 功能则设置为 NULL。 |
| *draw_rect_attr | 输入 | 绘制长方形空心框功能参数，其指向空间的长度由 crop_num 决定。若不使用画框功能则设置为 NULL。 |
| *fill_rect_attr | 输入 | 绘制长方形实心框功能参数，其指向空间的长度由 crop_num 决定。若不使用填框功能则设置为 NULL。 |
| *circle_attr | 输入 | 绘制圆功能参数，其指向空间的长度由 crop_num 决定。若不使用画圆功能则设置为 NULL。 |

**数据类型说明：**

除下述数据类型之外，未说明的数据类型请参阅 bmcv_image_csc_convert_to 接口文档。

```c++
typedef enum {
    NO_FLIP = 0,
    HORIZONTAL_FLIP = 1,
    VERTICAL_FLIP = 2,
    ROTATE_180 = 3,
} bmcv_flip_mode;
```

NO_FLIP 表示不做处理，HORIZONTAL_FLIP 表示水平翻转，VERTICAL_FLIP 表示垂直翻转，ROTATE_180表示旋转180度。

```c++
typedef struct bmcv_overlay_attr {
    char          overlay_num;
    bmcv_rect_t*  overlay_info;
    bm_image*     overlay_image;
} bmcv_overlay_attr;
```

* overlay_num 描述需要叠图的数量，该接口最高支持在单张目的图上叠 16 张图。
* overlay_info 描述叠图位置信息指针，其指向空间的长度由 overlay_num 决定。
* overlay_image 描述需要叠图的 bm_image 指针，其指向空间的长度由 overlay_num 决定。

```c++
typedef struct bmcv_draw_rect_attr {
    char          rect_num;
    bmcv_rect_t   draw_rect[4];
    unsigned int  color[4];
    short         line_width[4];
} bmcv_draw_rect_attr;
```

* rect_num 描述需要画框的数量，该接口最高支持在单张目的图上画 4 个框。
* draw_rect 描述画框位置信息。
* color 描述画框的颜色信息，可由 ((r << 16) | (g << 8) | b) 表示。
* line_width 描述画框的线宽。

```c++
typedef struct bmcv_fill_rect_attr {
    char          rect_num;
    bmcv_rect_t   fill_rect[4];
    unsigned int  color[4];
} bmcv_fill_rect_attr;
```

* rect_num 描述需要填框的数量，该接口最高支持在单张目的图上填 4 个框。
* draw_rect 描述填框位置信息。
* color 描述填框的颜色信息，可由 ((r << 16) | (g << 8) | b) 表示。

```c++
typedef struct bmcv_circle_attr {
    bmcv_point_t  center;
    short         radius;
    bmcv_color_t  color;
    signed char   line_width;
} bmcv_circle_attr;
```

* 该接口最高支持在单张目的图上画 1 个圆。
* center 描述画圆中心位置信息。
* radius 描述画圆半径。
* color 描述画圆的颜色信息。
* line_width 描述画圆的线宽，取值为 [-2, 15]， -2 表示画圆形相框， -1 表示画实心圆。

**返回值：**

该函数成功调用时, 返回 BM_SUCCESS。

**格式支持：**

本接口格式支持情况与 bmcv_image_csc_convert_to 接口相同，请参阅该接口文档。

# bmcv_image_draw_point

该接口用于在图像上填充一个或者多个point。

**接口形式：**

```c
bm_status_t bmcv_image_draw_point(
            bm_handle_t handle,
            bm_image image,
            int point_num,
            bmcv_point_t* coord,
            int length,
            unsigned char r,
            unsigned char g,
            unsigned char b);
```

**传入参数说明:**

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* bm_image image
  输入参数。需要在其上填充 point 的 bm_image 对象。

* int point_num
  输入参数。需填充 point 的数量，指 coord 指针中所包含的 bmcv_point_t 对象个数。

* bmcv_point_t* rect
  输入参数。point 位置指针。具体内容参考下面的数据类型说明。

* int length
  输入参数。point 的边长。

* unsigned char r
  输入参数。矩形填充颜色的r分量。

* unsigned char g
  输入参数。矩形填充颜色的g分量。

* unsigned char b
  输入参数。矩形填充颜色的b分量。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明：**

```c
typedef struct {
    int x;
    int y;
} bmcv_point_t;
```

* x 描述了 point 在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)。
* y 描述了 point 在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)。

**注意事项:**

1. 该接口底图的格式与尺寸限制于 bmcv_image_vpp_basic 接口相同。
2. 所有输入point对象区域须在图像以内。

# bmcv_image_draw_rectangle

**描述：**

该接口用于在图像上画一个或多个矩形框。

**语法：**

```cpp
bm_status_t bmcv_image_draw_rectangle(
        bm_handle_t   handle,
        bm_image      image,
        int           rect_num,
        bmcv_rect_t * rects,
        int           line_width,
        unsigned char r,
        unsigned char g,
        unsigned char b)
```

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image | 输入 | 需要在其上画矩形框的 bm_image 对象。 |
| rect_num | 输入 | 矩形框数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数。 |
| \*rect | 输出 | 矩形框对象指针，包含矩形起始点和宽高。具体内容参考下面的数据类型说明。 |
| line_width | 输入 | 矩形框线宽。line_width取值范围：`[1, min{crop_w / 2, crop_h / 2}]` |
| r | 输入 | 矩形框颜色的 r 分量。 |
| g | 输入 | 矩形框颜色的 g 分量。 |
| b | 输入 | 矩形框颜色的 b 分量。 |

**返回值：**

该函数成功调用时, 返回 BM_SUCCESS。

**数据类型说明：**

```cpp
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

* start_x 描述了 crop 图像在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)。
* start_y 描述了 crop 图像在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)。
* crop_w 描述的 crop 图像的宽度，也就是对应输出图像的宽度。
* crop_h 描述的 crop 图像的高度，也就是对应输出图像的高度。

**格式支持：**

1. 输入和输出的数据类型

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_YUV444P |
| 3 | FORMAT_NV12 |
| 4 | FORMAT_NV21 |
| 5 | FORMAT_RGB_PLANAR |
| 6 | FORMAT_BGR_PLANAR |
| 7 | FORMAT_RGB_PACKED |
| 8 | FORMAT_BGR_PACKED |
| 9 | FORMAT_RGBP_SEPARATE |
| 10 | FORMAT_BGRP_SEPARATE |
| 11 | FORMAT_GRAY |

**注意：**

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
2. 如果image为NV12/NV21/NV16/NV61/YUV420P格式，则线宽line_width会自动偶数对齐。
3. 如果rect_num为0，则自动返回成功。
4. 如果line_width小于零，则返回失败。
5. 所有输入矩形对象部分在image之外，则只会画出在image之内的线条，并返回成功。

**代码示例：**

```cpp
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmcv_api_ext_c.h"

int main() {
  char* filename_src= "path/to/src";
  char* filename_dst = "path/to/dst";
  int in_width = 1920;
  int in_height = 1080;
  int rect_num = 1;
  int line_width = 10;
  bm_image_format_ext src_format = 8;
  bmcv_rect_t crop_rect = {
      .start_x = 100,
      .start_y = 100,
      .crop_w = 200,
      .crop_h = 200};
  unsigned char r = 0;
  unsigned char g = 0;
  unsigned char b = 0;

  bm_status_t ret = BM_SUCCESS;

  int src_size = in_height * in_width * 3;
  unsigned char *input_data = (unsigned char *)malloc(src_size * sizeof(unsigned char));

  FILE *file;
  file = fopen(filename_src, "rb");
  fread(input_data, sizeof(unsigned char), src_size, file);
  fclose(file);

  bm_handle_t handle;
  int dev_id = 0;
  bm_image src;

  ret = bm_dev_request(&handle, dev_id);
  if (ret != BM_SUCCESS) {
    printf("Create bm handle failed. ret = %d\n", ret);
    return ret;
  }

  bm_image_create(handle, in_height, in_width, src_format, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
  bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

  void *src_in_ptr[3] = {(void *)input_data,
                        (void *)((char *)input_data + in_height * in_width),
                        (void *)((char *)input_data + 2 * in_height * in_width)};

  bm_image_copy_host_to_device(src, (void **)src_in_ptr);
  ret = bmcv_image_draw_rectangle(handle, src, rect_num, &crop_rect, line_width, r, g, b);
  bm_image_copy_device_to_host(src, (void **)src_in_ptr);

  bm_image_destroy(&src);
  bm_dev_free(handle);

  file = fopen(filename_dst, "wb");
  fwrite(input_data, sizeof(unsigned char), src_size, file);
  fclose(file);

  free(input_data);
  return ret;
}
```

# bmcv_image_fill_rectangle

**描述：**

该接口用于在图像上填充一个或者多个矩形。

**语法：**

```cpp
bm_status_t bmcv_image_fill_rectangle(
        bm_handle_t   handle,
        bm_image      image,
        int           rect_num,
        bmcv_rect_t * rects,
        unsigned char r,
        unsigned char g,
        unsigned char b)
```

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image | 输入 | 需要在其上画矩形框的 bm_image 对象。 |
| rect_num | 输入 | 矩形框数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数。 |
| \*rect | 输出 | 矩形框对象指针，包含矩形起始点和宽高。具体内容参考下面的数据类型说明。 |
| r | 输入 | 矩形框颜色的 r 分量。 |
| g | 输入 | 矩形框颜色的 g 分量。 |
| b | 输入 | 矩形框颜色的 b 分量。 |

**返回值：**

该函数成功调用时, 返回 BM_SUCCESS。

**数据类型说明：**

```cpp
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

* start_x 描述了 crop 图像在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width-1)。
* start_y 描述了 crop 图像在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height-1)。
* crop_w 描述的 crop 图像的宽度，也就是对应输出图像的宽度。
* crop_h 描述的 crop 图像的高度，也就是对应输出图像的高度。

**格式支持：**

1. 输入和输出的数据类型

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_YUV444P |
| 3 | FORMAT_NV12 |
| 4 | FORMAT_NV21 |
| 5 | FORMAT_RGB_PLANAR |
| 6 | FORMAT_BGR_PLANAR |
| 7 | FORMAT_RGB_PACKED |
| 8 | FORMAT_BGR_PACKED |
| 9 | FORMAT_RGBP_SEPARATE |
| 10 | FORMAT_BGRP_SEPARATE |
| 11 | FORMAT_GRAY |

**注意：**

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
2. 如果rect_num为0，则自动返回成功。
3. 如果line_width小于零，则返回失败。
4. 所有输入矩形对象部分在image之外，则只会画出在image之内的线条，并返回成功。

**代码示例：**

```cpp
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmcv_api_ext_c.h"

int main() {
  char* filename_src = "path/to/src";
  char* filename_dst = "path/to/dst";
  int in_width = 1920;
  int in_height = 1080;
  int rect_num = 1;
  bm_image_format_ext src_format = 8;
  bmcv_rect_t crop_rect = {
      .start_x = 100,
      .start_y = 100,
      .crop_w = 100,
      .crop_h = 100};
  unsigned char r = 0;
  unsigned char g = 0;
  unsigned char b = 0;

  bm_status_t ret = BM_SUCCESS;

  int src_size = in_width * in_height * 3;
  unsigned char *input_data = (unsigned char *)malloc(src_size);

  FILE *file;
  file = fopen(filename_src, "rb");
  fread(input_data, sizeof(unsigned char), src_size, file);
  fclose(file);

  bm_handle_t handle = NULL;
  int dev_id = 0;
  bm_image src;

  ret = bm_dev_request(&handle, dev_id);
  if (ret != BM_SUCCESS) {
      printf("Create bm handle failed. ret = %d\n", ret);
      return ret;
  }

  bm_image_create(handle, in_height, in_width, src_format, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
  bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

  void *src_in_ptr[3] = {(void *)input_data,
                        (void *)((char *)input_data + in_height * in_width),
                        (void *)((char *)input_data + 2 * in_height * in_width)};

  bm_image_copy_host_to_device(src, (void **)src_in_ptr);
  ret = bmcv_image_fill_rectangle(handle, src, rect_num, &crop_rect, r, g, b);
  bm_image_copy_device_to_host(src, (void **)src_in_ptr);

  bm_image_destroy(&src);
  bm_dev_free(handle);

  file = fopen(filename_dst, "wb");
```

# bmcv_image_flip

## 描述

该 API 可将输入图像进行水平翻转、垂直翻转或旋转180度的处理。

## 语法

```c++
bm_status_t bmcv_image_flip(
      bm_handle_t          handle,
      bm_image             input,
      bm_image             output,
      bmcv_flip_mode       flip_mode)
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象。 |
| output | 输出 | 输出 bm_image 对象。 |
| flip_mode | 输入 | flip模式，可选择水平翻转，垂直翻转和旋转180度。 |

## 数据类型说明

```c++
typedef enum {
    NO_FLIP = 0,
    HORIZONTAL_FLIP = 1,
    VERTICAL_FLIP = 2,
    ROTATE_180 = 3,
} bmcv_flip_mode;
```

NO_FLIP 表示不做处理，HORIZONTAL_FLIP 表示水平翻转，VERTICAL_FLIP 表示垂直翻转，ROTATE_180表示旋转180度。

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 该 API 所需要满足的格式以及部分要求与 bmcv_image_vpp_basic 中的表格相同。

2. 输入输出的宽高（src.width, src.height, dst.widht, dst.height）限制在 8 ～ 8192 之间，缩放128倍。

3. 输入必须关联 device memory，否则返回失败。

## 代码示例

```c++
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int readBin(const char * path, unsigned char* input_data, int size) {
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size){
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_src);
    return 0;
}

int writeBin(const char * path, unsigned char* input_data, int size) {
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size){
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_dst);
    return 0;
}

int main() {
    int src_h = 1080;
    int src_w = 1920;
    int dst_w = 1920;
    int dst_h = 1080;
    bm_image_format_ext src_fmt = FORMAT_GRAY;
    bm_image_format_ext dst_fmt = 14;
    char *src_name = "path/to/src";
    char *dst_name = "path/to/dst";
    bmcv_flip_mode flip_mode = HORIZONTAL_FLIP;
    bm_handle_t handle;
    bm_status_t ret = 0;
    bm_image src, dst;
    unsigned char* data_tpu = (unsigned char*)malloc(src_w * src_h * sizeof(unsigned char));
    ret = bm_dev_request(&handle, 0);
    ret = readBin(src_name, data_tpu, src_h * src_w);
    bm_image_create(handle, src_h, src_w, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, dst_h, dst_w, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);
    ret = bm_image_alloc_dev_mem(src,BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst,BMCV_HEAP1_ID);
    unsigned char* in_ptr[1] = {0};
    in_ptr[0] = data_tpu;
    ret = bm_image_copy_host_to_device(src, (void**)in_ptr);
    bmcv_image_flip(handle, src, dst, flip_mode);
    ret = bm_image_copy_device_to_host(dst, (void**)in_ptr);
    bm_image_destroy(&src);
    bm_image_destroy(&dst);
    ret = writeBin(dst_name, data_tpu, src_w * src_h);
    return ret;
}
```

# bmcv_image_gaussian_blur

**描述：**

该接口用于对图像进行高斯滤波操作。

**语法：**

```c
bm_status_t bmcv_image_gaussian_blur(
    bm_handle_t handle,
    bm_image input,
    bm_image output,
    int kw,
    int kh,
    float sigmaX,
    float sigmaY = 0);
```

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用bm_dev_request获取。 |
| input | 输入 | 输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。 |
| output | 输出 | 输出图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。 |
| kw | 输入 | kernel宽的大小。 |
| kh | 输入 | kernel高的大小。 |
| sigmaX | 输入 | X方向上的高斯核标准差，取值范围为0-4.0。 |
| sigmaY = 0 | 输入 | Y方向上的高斯核标准差，取值范围为0-4.0。如果为0则表示与X方向上的高斯核标准差相同。 |

**返回值：**

该函数成功调用时, 返回BM_SUCCESS。

**格式支持：**

该接口目前支持以下图像格式:

| num | image_format |
|-----|--------------|
| 1 | FORMAT_BGR_PLANAR |
| 2 | FORMAT_RGB_PLANAR |
| 3 | FORMAT_RGBP_SEPARATE |
| 4 | FORMAT_BGRP_SEPARATE |
| 5 | FORMAT_GRAY |

该接口目前支持的数据格式：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1. 在调用该接口之前必须确保输入图像的内存已经申请。

2. 输入输出图像的数据格式，图像格式必须相同。

3. 目前卷积核支持的大小有3*3, 5*5， 7*7,当卷积核大小为3时，支持的宽高范围为8*8～4096*8192，核大小为5时支持的宽高范围为8*8～2048*8192，核大小为7时支持的宽高范围为8*8～1500*8192。

**代码示例：**

```c
#include <stdio.h>
#include "bmcv_api_ext_c.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>
#include <float.h>
#include <math.h>

static void read_bin(const char *input_path, unsigned char *input_data, int width, int height) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
    printf("无法打开输出文件 %s\n", input_path);
    return;
    }
    if(fread(input_data, sizeof(char), width * height, fp_src) != 0) {
    printf("read image success\n");
    }
    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int width, int height) {
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL) {
    printf("无法打开输出文件 %s\n", output_path);
    return;
    }
    fwrite(output_data, sizeof(char), width * height, fp_dst);
    fclose(fp_dst);
}

int main() {
    int width = 1920;
    int height = 1080;
    int format = FORMAT_GRAY;
    float sigmaX = (float)rand() / RAND_MAX * 5.0f;
    float sigmaY = (float)rand() / RAND_MAX * 5.0f;
    int ret = 0;
    char *input_path = "path/to/input";
    char *output_path = "path/to/output";
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return -1;
    }
    int kw = 3, kh = 3;
    unsigned char *input_data = (unsigned char*)malloc(width * height);
    unsigned char *output_tpu = (unsigned char*)malloc(width * height);
    read_bin(input_path, input_data, width, height);
    bm_image img_i;
    bm_image img_o;
    bm_image_create(handle, height, width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &img_i, NULL);
    bm_image_create(handle, height, width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &img_o, NULL);
    bm_image_alloc_dev_mem(img_i, 2);
    bm_image_alloc_dev_mem(img_o, 2);
    unsigned char *input_addr[3] = {input_data, input_data + height * width, input_data + 2 * height * width};
    bm_image_copy_host_to_device(img_i, (void **)(input_addr));
    ret = bmcv_image_gaussian_blur(handle, img_i, img_o, kw, kh, sigmaX, sigmaY);
    unsigned char *output_addr[3] = {output_tpu, output_tpu + height * width, output_tpu + 2 * height * width};
    bm_image_copy_device_to_host(img_o, (void **)output_addr);
    bm_image_destroy(&img_i);
    bm_image_destroy(&img_o);
```

# bmcv_ive_ccl

## 描述

该 API 使用ive硬件资源的 ccl 功能, 创建二值图像的连通区域标记任务，即图像中具有相同像素值且位置相邻的前景像素点组成的图像区域。

## 语法

```c++
bm_status_t bmcv_ive_ccl(
    bm_handle_t      handle,
    bm_image         src_dst_image,
    bm_device_mem_t  ccblob_output,
    bmcv_ive_ccl_attr  ccl_attr);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| src_dst_image | 输入、输出 | 输入 bm_image 对象结构体, 连通区域标记在输入图像上进行，即输入图像同时也是标记图像输出, 不能为空。 |
| ccblob_output | 输出 | 连通区域信息数据结构体，不能为空，内存至少需要配置 sizoef(bm_ive_ccblob) 大小, 最多输出254个有效连通区域。 |
| ccl_attr | 输入 | 连通区域标记控制参数结构体, 不能为空。 |

| **参数名称** | **图像格式** | **数据类型** | **分辨率** |
|-------------|-------------|-------------|-----------|
| srcDstImage | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |

## 数据类型说明

### 定义连通区域信息

```c++
typedef struct bmcv_ive_region_s{
    int u32_area;
    unsigned short u16_left;
    unsigned short u16_right;
    unsigned short u16_top;
    unsigned short u16_bottom;
} bmcv_ive_region;
```

| **成员名称** | **描述** |
|-------------|----------|
| u32_area | 连通区域面积，以及连通区域像素数目。 |
| u16_left | 连通区域外接矩形的最左边坐标。 |
| u16_right | 连通区域外接矩形的最右边坐标。 |
| u16_top | 连通区域外接矩形的最上边坐标。 |
| u16_bottom | 连通区域外接矩形的最下边坐标。 |

### 定义连通区域标记的输出信息

```c++
typedef struct bmcv_ive_ccblob_s{
    unsigned short    u16_cur_aera_thr;
    signed char       s8_label_status;
    unsigned char     u8_region_num;
    bmcv_ive_region   ast_region[BM_IVE_MAX_REGION_NUM];
} bmcv_ive_ccblob;
```

| **成员名称** | **描述** |
|-------------|----------|
| u16_cur_aera_thr | 有效连通区域的面积阈值，astRegion 中面积小于这个阈值的都被置为 0 。 |
| s8_label_status | 连通区域标记是否成功。1： 标记失败; 0：标记成功。 |
| u8_region_num | 有效连通区域个数。 |
| ast_region | 连通区域信息：有效的连通区域其面积大于 0, 对应标记为数组下标加 1。 |

### 定义连通区域模式

```c++
typedef enum bmcv_ive_ccl_mode_e{
    BM_IVE_CCL_MODE_4C = 0x0,
    BM_IVE_CCL_MODE_8C = 0x1,
} bmcv_ive_ccl_mode;
```

| **成员名称** | **描述** |
|-------------|----------|
| BM_IVE_CCL_MODE_4C | 4 连通。 |
| BM_IVE_CCL_MODE_8C | 8 连通。 |

### 定义连通区域标记控制参数

```c++
typedef struct bmcv_ive_ccl_attr_s{
    bmcv_ive_ccl_mode en_mode;
    unsigned short  u16_init_area_thr;
    unsigned short  u16_step;
} bmcv_ive_ccl_attr;
```

| **成员名称** | **描述** |
|-------------|----------|
| en_mode | 连通区域模式。 |
| u16_init_area_thr | 初始面积阈值。取值范围：[0, 65535]，参考取值：4。 |
| u16_step | 面积阈值增长步长。取值范围：[1, 65535]，参考取值：2。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。

2. 连通区域的信息保存在 ccblob_output.ast_region 中。

3. ccblob_output.u8_region_num 表示有效的连通区域数目，最多 254 个有效连通区域；有效的连通区域的面积大于 ccblob_output.u16_cur_aera_thr, 标记号为其所在 ccblob_output.ast_region 数组元素的下标 + 1。有效的连通区域并不一定连续地存储在数组中, 而很可能是间断的分布在数组中。

4. 若 ccblob_output.s8_label_status 为0, 则标记成功(一个区域一个标记); 若为 -1, 则标记失败(一个区域多个标记或者多个区域共用一个标记)。对于后者， 若用户需要正确的标记号， 还需要再次根据 ccblob_output 中的外接矩形信息重新标记。 不管标记是否成功，连通区域的外接矩形信息一定是正确可用的。

5. 输出的连通区域会用 ccl_attr.u16_init_area_thr 进行筛选， 面积小于等于pstCclCtrl→u16_init_area_thr 均会被置为 0。

6. 当连通区域数目大于 254, 会用 ccl_attr.u16_init_area_thr 删除面积小的连通区域；若 ccl_attr.u16_init_area_thr 不满足删除条件，会以 pstCclCtrl→u16_step 为步长，增大删除连通区域的面积阈值。

7. 最终的面积阈值存储在 ccblob_output.u16_cur_aera_thr 中。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bmcv_ive_ccl_mode enMode = BM_IVE_CCL_MODE_8C;
    unsigned short u16InitAreaThr = 4;
    unsigned short u16Step = 2;

    char *src_name = "path/to/src";
    char *ive_res_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    bm_image src_dst_img;
    bm_device_mem_t pst_blob;
    bmcv_ive_ccl_attr ccl_attr;
    bmcv_ive_ccblob *ccblob = NULL;
    int stride[4];

    ccl_attr.en_mode = enMode;
    ccl_attr.u16_init_area_thr = u16InitAreaThr;
    ccl_attr.u16_step = u16Step;

    ccblob = (bmcv_ive_ccblob *)malloc(sizeof(bmcv_ive_ccblob));
    memset(ccblob, 0, sizeof(bmcv_ive_ccblob));

    // calc ive image stride && create bm image struct
    int data_size = 1;
    stride[0] = align_up(width, 16) * data_size;
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &src_dst_img, stride);

    ret = bm_image_alloc_dev_mem(src_dst_img, BMCV_HEAP1_ID);
    ret = bm_malloc_device_byte(handle, &pst_blob, sizeof(bmcv_ive_ccblob));

    // bm_ive_read_bin(src_dst_img, src_name);
    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src_dst_img, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src_dst_img, in_ptr);

    ret = bmcv_ive_ccl(handle, src_dst_img, pst_blob, ccl_attr);

    ret = bm_memcpy_d2s(handle, (void*)ccblob, pst_blob);
    FILE *fp = fopen(ive_res_name, "wb");
    fwrite((void *)ccblob, 1, sizeof(bmcv_ive_ccblob), fp);
    fclose(fp);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_ive_csc

## 描述

该 API 使用ive硬件资源的 csc 功能, 创建色彩空间转换任务, 可实现YUV2RGB、YUV2HSV、RGB2YUV 的色彩空间转换。

## 语法

```c++
bm_status_t bmcv_ive_csc(
        bm_handle_t     handle,
        bm_image        input,
        bm_image        output,
        csc_type_t      csc_type);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体, 不能为空。 |
| output | 输出 | 输出 bm_image 对象结构体, 不能为空, 宽、高同 input。 |
| csc_type | 输入 | csc 工作模式。 |

| **参数名称** | **图像格式** | **数据类型** | **分辨率** |
|-------------|-------------|-------------|-----------|
| input | FORMAT_NV21<br>FORMAT_NV61<br>FORMAT_RGB_PACKED<br>FORMAT_RGB_PLANAR<br>FORMAT_RGBP_SEPARATE | U8 | 64x64~1920x1080 |
| output | FORMAT_NV21<br>FORMAT_NV61<br>FORMAT_RGB_PACKED<br>FORMAT_RGB_PLANAR<br>FORMAT_RGBP_SEPARATE | U8 | 同 input |

**补充**：FORMAT_YUV444P可以转FORMAT_HSV_PLANAR，转换模式色彩空间转换控制模式选择CSC_YCbCr2RGB_BT601或者CSC_YCbCr2RGB_BT709。

## 数据类型说明

### 定义色彩空间转换控制模式

```c++
typedef enum csc_type {
    CSC_YCbCr2RGB_BT601 = 0,
    CSC_YPbPr2RGB_BT601,
    CSC_RGB2YCbCr_BT601,
    CSC_YCbCr2RGB_BT709,
    CSC_RGB2YCbCr_BT709,
    CSC_RGB2YPbPr_BT601,
    CSC_YPbPr2RGB_BT709,
    CSC_RGB2YPbPr_BT709,
    CSC_FANCY_PbPr_BT601 = 100,
    CSC_FANCY_PbPr_BT709,
    CSC_USER_DEFINED_MATRIX = 1000,
    CSC_MAX_ENUM
} csc_type_t;
```

| **成员名称** | **描述** |
|-------------|----------|
| CSC_YCbCr2RGB_BT601 | BT601 的 YUV2RGB 图片变换 |
| CSC_YPbPr2RGB_BT601 | BT601 的 YUV2RGB 视频变换。 |
| CSC_RGB2YCbCr_BT601 | BT601 的 RGB2YUV 图像变换。 |
| CSC_YCbCr2RGB_BT709 | BT709 的 YUV2RGB 图像变换。 |
| CSC_RGB2YCbCr_BT709 | BT709 的 RGB2YUV 图像变换。 |
| CSC_RGB2YPbPr_BT601 | BT601 的 RGB2YUV 视频变换。 |
| CSC_YPbPr2RGB_BT709 | BT709 的 YUV2RGB 视频变换。 |
| CSC_RGB2YPbPr_BT709 | BT709 的 RGB2YUV 视频变换。 |

## 注意

* CSC_YPbPr2RGB_BT601 和 CSC_YPbPr2RGB_BT709 模式，输出满足 16≤R、 G、 B≤235。

* CSC_YCbCr2RGB_BT601 和 CSC_YCbCr2RGB_BT709 模式，输出满足 0≤R、 G、 B≤255。

* CSC_RGB2YPbPr_BT601 和 CSC_RGB2YPbPr_BT709 模式，输出满足 0≤Y、 U、 V≤ 255。

* CSC_RGB2YCbCr_BT601 和 CSC_RGB2YCbCr_BT709 模式。, 输出满足 0≤Y≤235, 0≤U、 V≤240。

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

# bmcv_ive_dma

## 描述

该 API 使用ive硬件资源, 创建直接内存访问任务，支持快速拷贝、间隔拷贝；可实现数据从一块内存快速拷贝到另一块内存，或者从一块内存有规律的拷贝一些数据到另一块内存。

## 语法

```c
bm_status_t bmcv_ive_dma(
    bm_handle_t                      handle,
    bm_image                         input,
    bm_image                         output,
    bmcv_ive_dma_mode                dma_mode,
    bmcv_ive_interval_dma_attr *     attr);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体, 不能为空。 |
| output | 输出 | 输出 bm_image 对象结构体，不能为空。 |
| dma_mode | 输入 | 定义 DMA copy操作模式。 |
| attr | 输入 | DMA 在间隔拷贝模式下需要的控制参数结构体，直接拷贝可以为空。 |

**分辨率**：32x1 ~ 1920x1080

## 数据类型说明

**说明**：定义 DMA 操作模式。

```c
typedef enum bmcv_ive_dma_mode_e {
    IVE_DMA_DIRECT_COPY = 0x0,
    IVE_DMA_INTERVAL_COPY = 0x1
} bmcv_ive_dma_mode;
```

| 成员名称 | 描述 |
|---------|------|
| IVE_DMA_DIRECT_COPY | 直接快速拷贝模式。 |
| IVE_DMA_INTERVAL_COPY | 间隔拷贝模式。 |

**说明**：定义 DMA 间隔拷贝需要的控制信息。

```c
typedef struct bmcv_ive_interval_dma_attr_s {
    unsigned char hor_seg_size;
    unsigned char elem_size;
    unsigned char ver_seg_rows;
} bmcv_ive_interval_dma_attr;
```

| 成员名称 | 描述 |
|---------|------|
| hor_seg_size | 仅间隔拷贝模式使用, 水平方向将源图像一行分割的段大小。取值范围：{2, 3, 4, 8, 16}。 |
| elem_size | 仅间隔拷贝模式使用, 分割的每一段中前 elem_size 为有效拷贝字段。取值范围：[1, hor_seg_size - 1]。 |
| ver_seg_rows | 仅间隔拷贝模式使用, 将每 ver_seg_rows 行中第一行数据分割为 hor_seg_size 大小的段, 拷贝每段的前 elem_size 大小的字节。取值范围：[1, min{65535 / srcStride, srcHeight}]。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。

2. 模式是指 IVE_DMA_DIRECT_COPY 和 IVE_DMA_INTERVAL_COPY 模式;

3. IVE_DMA_DIRECT_COPY : 快速拷贝模式, 可实现直接从大块内存中扣取小块内存，计算公式如下：

   I_out(x, y) = I(x, y) (0 ≤ x ≤ width, 0 ≤ y ≤ height)

   其中，I(x, y) 对应 input， I_out(x, y) 对应 output。

4. IVE_DMA_INTERVAL_COPY : 间隔拷贝模式，要求输入数据宽度为 hor_seg_size 的倍数; 间隔拷贝的方式, 即将每 ver_seg_rows 行中第一行数据分割成 hor_seg_size 大小的段, 拷贝每段的前 elem_size 大小的字节。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

int main() {
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext src_fmt = FORMAT_GRAY, dst_fmt = FORMAT_GRAY;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    bm_image src, dst;

    // create bm image struct
    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, height, width, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    // alloc bm image memory
    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    // read image data from input files
    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
    printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    ret = bmcv_ive_dma(handle, src, dst, 0, NULL);

    unsigned char *ive_res = (unsigned char*) malloc (width * height * sizeof(unsigned char));
    memset(ive_res, 0, width * height * sizeof(unsigned char));
    ret = bm_image_copy_device_to_host(dst, (void**)&ive_res);
    if(ret != BM_SUCCESS){
        printf("dst bm_image_copy_device_to_host is failed \n");
        exit(-1);
    }

    FILE *fp = fopen(dst_name, "wb");
    fwrite((void *)ive_res, 1, width * height * sizeof(unsigned char), fp);
    fclose(fp);

    free(input_data);
    free(ive_res);

    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);

    return ret;
}
```

# bmcv_ive_gmm2

## 描述

该 API 使用ive硬件资源, 创建 GMM 背景建模任务，支持 1-5 个高斯模型，支持灰度图和 RGB_PACKED 图输入，支持全局及像素级别的灵敏度系数以及前景模型时长更新系数。

## 语法

```c
bm_status_t bmcv_ive_gmm2(
    bm_handle_t        handle,
    bm_image *         input,
    bm_image *         input_factor,
    bm_image *         output_fg,
    bm_image *         output_bg,
    bm_image *         output_match_model_info,
    bm_device_mem_t    output_model,
    bmcv_ive_gmm2_ctrl   gmm2_attr);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| *input | 输入 | 输入 bm_image 对象指针, 不能为空。 |
| *input_factor | 输入 | 输入 bm_image 对象指针, 表示模型更新参数, 当且仅仅当 gmm2_attr.en_sns_factor_mode、gmm2_attr.en_life_update_factor_mode 均使用全局模式时可以为空。 |
| *output_fg | 输出 | 输出 bm_image 对象指针, 表示前景图像, 不能为空, 宽、高同 input。 |
| *output_bg | 输出 | 输出 bm_image 对象指针, 表示背景图像, 不能为空, 宽、高同 input。 |
| *output_match_model_info | 输出 | 输出 bm_image 对象指针, 对应模型匹配系数, 不能为空。 |
| output_model | 输入、输出 | bm_device_mem_t 对象结构体, 对应 GMM 模型参数, 不能为空。 |
| gmm2_attr | 输入 | 控制信息结构体, 不能为空。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|----------|--------|
| input | GRAY<br>RGB PACKED | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| input_factor | GRAY | DATA_TYPE_EXT_U16 | 同 input |
| output_fg | GRAY 二值图 | DATA_TYPE_EXT_1N_BYTE | 同 input |
| output_bg | 同 input | DATA_TYPE_EXT_1N_BYTE | 同 input |
| match_model_info | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 input |

## 数据类型说明

**说明**：定义灵敏度系数模式。

```c
typedef enum gmm2_sns_factor_mode_e{
    SNS_FACTOR_MODE_GLB = 0x0,
    SNS_FACTOR_MODE_PIX = 0x1,
} gmm2_sns_factor_mode;
```

| 成员名称 | 描述 |
|---------|------|
| SNS_FACTOR_MODE_GLB | 全局灵敏度系数模式，每个像素在模型匹配过程中, 方差灵敏度使用 gmm2_attr.u8_glb_sns_factor。 |
| SNS_FACTOR_MODE_PIX | 像素级灵敏度系数模式，每个像素在模型匹配过程中，方差灵敏度使用 input_factor 的灵敏度系数。 |

**说明**：定义模型时长参数更新模式。

```c
typedef enum gmm2_life_update_factor_mode_e{
    LIFE_UPDATE_FACTOR_MODE_GLB = 0x0,
    LIFE_UPDATE_FACTOR_MODE_PIX = 0x1,
} gmm2_life_update_factor_mode;
```

| 成员名称 | 描述 |
|---------|------|
| LIFE_UPDATE_FACTOR_MODE_GLB | 模型时长参数全局更新模式，每个像素模型时长参数在更新时使用 gmm2_attr.u16_glb_life_update_factor。 |
| LIFE_UPDATE_FACTOR_MODE_PIX | 模型时长参数像素级更新模式，每个像素模型时长在更新时使用 input_factor 的模型更新参数。 |

# 定义 GMM2 背景建模的控制参数

```c++
typedef struct bmcv_ive_gmm2_ctrl_s{
    gmm2_sns_factor_mode en_sns_factor_mode;
    gmm2_life_update_factor_mode en_life_update_factor_mode;
    unsigned short u16_glb_life_update_factor;
    unsigned short u16_life_thr;
    unsigned short u16_freq_init_val;
    unsigned short u16_freq_redu_factor;
    unsigned short u16_freq_add_factor;
    unsigned short u16_freq_thr;
    unsigned short u16_var_rate;
    unsigned short u9q7_max_var;
    unsigned short u9q7_min_var;
    unsigned char u8_glb_sns_factor;
    unsigned char u8_model_num;
} bmcv_ive_gmm2_ctrl;
```

## 参数说明

| 成员名称 | 描述 |
|---------|------|
| en_sns_factor_mode | 灵敏度模式, 默认全局模式。<br>全局模式使用 u8_glb_sns_factor 作为灵敏度系数;<br>像素模式使用 input_factor 的低 8 bit 值作为灵敏度系数。 |
| en_life_update_factor_mode | 模型时长更新模式, 默认全局模式。<br>全局模式使用 u16_glb_life_update_factor 作为前进模型更新参数;<br>像素模式使用 input_factor 的高 8bit 值作为前进模型时长更新参数。 |
| u16_glb_life_update_factor | 全局模型更新参数。<br>取值范围： [0, 65535]，默认： 4。 |
| u16_life_thr | 背景模型生成时间，表示一个模型从前景模型转成背景模型需要的时间。<br>取值范围： [0, 65535]，默认： 5000。 |
| u16_freq_init_val | 初始频率。<br>取值范围： [0, 65535]，默认： 20000。 |
| u16_freq_redu_factor | 频率衰减系数。<br>取值范围： [0, 65535]，默认： 0xFF00。 |
| u16_freq_add_factor | 模型匹配频率增加系数。<br>取值范围：[0, 65535]，默认： 0xEF。 |
| u16_freq_thr | 模型失效频率阈值。<br>取值范围： [0, 65535]，默认： 12000。 |
| u16_var_rate | 方差更新率。<br>取值范围： [0, 65535]，默认： 1。 |
| u9q7_max_var | 方差最大值。<br>取值范围： [0, 65535]，默认： (16x16) << 7。 |
| u9q7_min_var | 方差最小值。<br>取值范围：[0, u9q7MaxVar]，默认： (8x8) << 7。 |
| u8_glb_sns_factor | 方差最小值。<br>取值范围： [0, 255]，默认： 8。 |
| u8_model_num | 模型数量。<br>取值范围 [1, 5]，默认： 3。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意事项

1. 输入输出图像的 width 都需要16对齐。
2. GMM2 在参考了 OPENCV 的 MOG 和 MOG2 的基础上，增加了像素级别的参数控制。
3. 源图像 pstSrc 类型只能为 U8C1 或 U8C3_PACKAGE，分别用于灰度图和 RGB 图的 GMM 背景建模。
4. 模型更新参数 pstFactor 为 U16C1 图像：每个元素用 16 bit 表示，低 8 bit 为灵敏度系数，用于控制模型匹配时方差倍数；高 8 bit 为前景模型时长更新参数，用于控制背景模型形成时间。
5. 模型匹配系数指针 pstMatchModelInfo 为 U8C1 图像：每个元素用 8bit 表示， 低 1 bit 为高斯模型匹配标志， 0 表示匹配失败， 1 表示匹配成功； 高 7 bit 为频率最大模型序号。
6. GMM2 的频率参数（pstGmm2Ctrl 中的 u16_freq_init_val、 u16_freq_redu_factor、u16_freq_add_factor、 u16_freq_thr） 用于控制模型排序和模型有效时间。
   - u16_freq_init_val 越大，模型有效时间越大；
   - u16_freq_redu_factor 越大，模型有效时间越长，模型频率通过乘以频率衰减系数 u16_freq_redu_factor/65536，达到频率衰减的目的；
   - u16_freq_add_factor 越大，模型有效时间越长；
   - u16_freq_thr 越大，模型有效时间越短。
7. GMM2 的模型时长参数(pstGmm2Ctrl 中的 u16_life_thr)用于控制前景模型成为背景的时间。
   - u16_life_thr 越大，前景持续时间越长；
   - 单高斯模型下，模型时长参数不生效。
8. 灰度图像 GMM2 采用 n 个（1≤n≤5） 高斯模型。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    bool pixel_ctrl = false;
    gmm2_life_update_factor_mode
            life_update_enMode = LIFE_UPDATE_FACTOR_MODE_GLB;
    int height = 1080, width = 1920;
    bm_image_format_ext src_fmt = FORMAT_GRAY;
    char *input_name = "path/to/input";
    char *dstFg_name = "path/to/dst_Fg", *dstBg_name = "path/to/dst_Bg";

    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    bm_image src, src_factor;
    bm_image dst_fg, dst_bg, dst_model_match_model_info;
    bm_device_mem_t dst_model;
    int stride[4], factorStride[4];
    unsigned int u32FrameNumMax = 32;
    unsigned int u32FrmCnt = 0;
    unsigned int u32FrmNum = 0;

    bmcv_ive_gmm2_ctrl gmm2Attr;
    gmm2Attr.u16_var_rate = 1;
    gmm2Attr.u8_model_num = 3;
    gmm2Attr.u9q7_max_var = (16 * 16) << 7;
    gmm2Attr.u9q7_min_var = (8 * 8) << 7;
    gmm2Attr.u8_glb_sns_factor = 8;
    gmm2Attr.en_sns_factor_mode = SNS_FACTOR_MODE_GLB;
    gmm2Attr.u16_freq_thr = 12000;
    gmm2Attr.u16_freq_init_val = 20000;
    gmm2Attr.u16_freq_add_factor = 0xEF;
    gmm2Attr.u16_freq_redu_factor = 0xFF00;
    gmm2Attr.u16_life_thr = 5000;
    gmm2Attr.en_life_update_factor_mode = life_update_enMode;

    unsigned char* inputData = malloc(width * height * u32FrameNumMax * sizeof(unsigned char));
    FILE *input_fp = fopen(input_name, "rb");
    fread((void *)inputData, sizeof(unsigned char), width * height * u32FrameNumMax, input_fp);
    fclose(input_fp);

    unsigned char* srcData = malloc(width * height * sizeof(unsigned char));
    unsigned short* srcFactorData = malloc(width * height * sizeof(unsigned short));
    memset(srcData, 0, width * height * sizeof(unsigned char));
    memset(srcFactorData, 0, width * height * sizeof(unsigned short));

    int model_len = width * height * gmm2Attr.u8_model_num * 8;
    unsigned char* model_data = malloc(model_len * sizeof(unsigned char));
    memset(model_data, 0, model_len * sizeof(unsigned char));

    unsigned char* ive_fg_res = malloc(width * height * sizeof(unsigned char));
    unsigned char* ive_bg_res = malloc(width * height * sizeof(unsigned char));
    unsigned char* ive_pc_match_res = malloc(width * height * sizeof(unsigned char));

    memset(ive_fg_res, 0, width * height * sizeof(unsigned char));
    memset(ive_bg_res, 0, width * height * sizeof(unsigned char));
    memset(ive_pc_match_res, 0, width * height * sizeof(unsigned char));

    // calc ive image stride && create bm image struct
    int data_size = 1;
    stride[0] = align_up(width, 16) * data_size;

    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, stride);
    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

    factorStride[0] = align_up(width, 16) * data_size;

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_U16, &src_factor, factorStride);
    ret = bm_image_alloc_dev_mem(src_factor, BMCV_HEAP1_ID);
    ret = bm_image_copy_host_to_device(src_factor, (void **)&srcFactorData);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &dst_fg, stride);
    ret = bm_image_alloc_dev_mem(dst_fg, BMCV_HEAP1_ID);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &dst_bg, stride);
    ret = bm_image_alloc_dev_mem(dst_bg, BMCV_HEAP1_ID);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &dst_model_match_model_info, stride);
    ret = bm_image_alloc_dev_mem(dst_model_match_model_info, BMCV_HEAP1_ID);

    ret = bm_malloc_device_byte(handle, &dst_model, model_len);

    ret = bm_memcpy_s2d(handle, dst_model, model_data);

    for(u32FrmCnt = 0; u32FrmCnt < u32FrameNumMax; u32FrmCnt++){
        if(width > 480){
            for(int i = 0; i < 288; i++){
                memcpy(srcData + (i * width),
                        inputData + (u32FrmCnt * 352 * 288 + i * 352), 352);
                memcpy(srcData + (i * width + 352),
                        inputData + (u32FrmCnt * 352 * 288 + i * 352), 352);

            }
        } else {
            for(int i = 0; i < 288; i++){
                memcpy(srcData + i * stride[0],
                        inputData + u32FrmCnt * width * 288 + i * width, width);
                int s = stride[0] - width;
                memset(srcData + i * stride[0] + width, 0, s);
            }
        }

        ret = bm_image_copy_host_to_device(src, (void**)&srcData);

        u32FrmNum = u32FrmCnt + 1;
        if(gmm2Attr.u8_model_num == 1)
            gmm2Attr.u16_freq_redu_factor = (u32FrmNum >= 500) ? 0xFFA0 : 0xFC00;
        else
            gmm2Attr.u16_glb_life_update_factor =
                                    (u32FrmNum >= 500) ? 4 : 0xFFFF / u32FrmNum;

        if(pixel_ctrl && u32FrmNum > 16)
            gmm2Attr.en_life_update_factor_mode = LIFE_UPDATE_FACTOR_MODE_PIX;

        ret = bmcv_ive_gmm2(handle, &src, &src_factor, &dst_fg, &dst_bg, &dst_model_match_model_info, dst_model, gmm2Attr);
    }

    ret = bm_image_copy_device_to_host(dst_fg, (void **)&ive_fg_res);
    ret = bm_image_copy_device_to_host(dst_bg, (void **)&ive_bg_res);
    ret = bm_image_copy_device_to_host(dst_model_match_model_info, (void **)&ive_pc_match_res);

    FILE *fg_fp = fopen(dstFg_name, "wb");
    fwrite((void *)ive_fg_res, 1, width * height, fg_fp);
    fclose(fg_fp);

    FILE *bg_fp = fopen(dstBg_name, "wb");
    fwrite((void *)ive_bg_res, 1, width * height, bg_fp);
    fclose(bg_fp);

    free(inputData);
    free(srcData);
    free(srcFactorData);
    free(model_data);
    free(ive_fg_res);
    free(ive_bg_res);
    free(ive_pc_match_res);
    bm_image_destroy(&src);
    bm_image_destroy(&src_factor);
    bm_image_destroy(&dst_fg);
    bm_image_destroy(&dst_model_match_model_info);
    bm_free_device(handle, dst_model);
}
```

# bmcv_ive_gradfg

## 描述

该 API 使用ive硬件资源, 根据背景图像和当前帧图像的梯度信息计算梯度前景图像。

## 语法

```c
bm_status_t bmcv_ive_gradfg(
    bm_handle_t           handle,
    bm_image              input_bgdiff_fg,
    bm_image              input_curgrad,
    bm_image              intput_bggrad,
    bm_image              output_gradfg,
    bmcv_ive_gradfg_attr    gradfg_attr);
```

## 参数

### bmcv_ive_gradfg 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input_bgdiff_fg | 输入 | 背景差分前景图像bm_image结构体, 不能为空。 |
| input_curgrad | 输入 | 当前帧梯度图像bm_image结构体, 不能为空。 |
| intput_bggrad | 输入 | 背景梯度图像bm_image结构体, 不能为空，宽、高同 input_curgrad。 |
| output_gradfg | 输出 | 梯度前景图像bm_image结构体, 不能为空，宽、高同 input_curgrad。 |
| gradfg_attr | 输入 | 计算梯度前景控制参数结构体，不能为空。 |

### 图像参数规格

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| input_bgdiff_fg | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| input_curgrad | GRAY | DATA_TYPE_EXT_U16 | 同 input |
| intput_bggrad | GRAY | DATA_TYPE_EXT_U16 | 同 input |
| output_gradfg | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 input |

## 数据类型说明

### 梯度前景计算模式

```c
typedef enum bmcv_ive_gradfg_mode_e{
    GRAD_FG_MODE_USE_CUR_GRAD = 0x0,
    GRAD_FG_MODE_FIND_MIN_GRAD = 0x1,
} bmcv_ive_gradfg_mode;
```

| 成员名称 | 描述 |
|---------|------|
| GRAD_FG_MODE_USE_CUR_GRAD | 当前位置梯度计算模式。 |
| GRAD_FG_MODE_FIND_MIN_GRAD | 周边最小梯度计算模式。 |

### 计算梯度前景控制参数

```c
typedef struct bmcv_ive_gradfg_attr_s{
    bmcv_ive_gradfg_mode en_mode;
    unsigned short u16_edw_factor;
    unsigned char u8_crl_coef_thr;
    unsigned char u8_mag_crl_thr;
    unsigned char u8_min_mag_diff;
    unsigned char u8_noise_val;
    unsigned char u8_edw_dark;
} bmcv_ive_gradfg_attr;
```

| 成员名称 | 描述 |
|---------|------|
| en_mode | 梯度前景计算模式。参考 bm_ive_gradfg_mode。 |
| u16_edw_factor | 边缘宽度调节因子。取值范围: [500, 2000], 参考取值: 100。 |
| u8_crl_coef_thr | 梯度向量相关系数阈值。取值范围: [50, 100], 参考取值: 80。 |
| u8_mag_crl_thr | 梯度幅度阈值。取值范围: [0, 20], 参考取值: 4。 |
| u8_min_mag_diff | 梯度幅值差值阈值。取值范围: [2, 8], 参考取值: 2。 |
| u8_noise_val | 梯度幅值差值阈值。取值范围: [1, 8], 参考取值: 1。 |
| u8_edw_dark | 黑像素使能标志。0 表示不开启, 1 表示开启，参考取值: 1。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。
2. 背景梯度图像和当前梯度图像的类型为 DATA_TYPE_EXT_U16, 水平和竖直方向梯度按照 `[xyxyxyxy...]` 格式存储。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bmcv_ive_gradfg_mode gradfg_mode = GRAD_FG_MODE_USE_CUR_GRAD;
    char *src_name = "path/to/src";
    char *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    /* 3 by 3*/
    signed char arr3by3[25] = { 0, 0, 0, 0, 0, 0, -1, 0, 1, 0, 0, -2, 0,
                    2, 0, 0, -1, 0, 1, 0, 0, 0, 0, 0, 0 };
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image stBgdiffFg;
    bm_image stCurGrad, stBgGrad, stGragFg;
    int u8Stride[4], u16Stride[4];

    // config setting

    // normGrad config
    bmcv_ive_normgrad_ctrl normGradAttr;
    normGradAttr.en_mode = BM_IVE_NORM_GRAD_OUT_COMBINE;
    normGradAttr.u8_norm = 8;
    memcpy(&normGradAttr.as8_mask, arr3by3, 5 * 5 * sizeof(signed char));

    bmcv_ive_gradfg_attr gradFgAttr;
    gradFgAttr.en_mode = gradfg_mode;
    gradFgAttr.u16_edw_factor = 1000;
    gradFgAttr.u8_crl_coef_thr = 80;
    gradFgAttr.u8_mag_crl_thr = 4;
    gradFgAttr.u8_min_mag_diff = 2;
    gradFgAttr.u8_noise_val = 1;
    gradFgAttr.u8_edw_dark = 1;

    // calc ive image stride && create bm image struct
    int data_size = 1;
    u8Stride[0] = align_up(width, 16) * data_size;
    data_size = 2;
    u16Stride[0] = align_up(width, 16) * data_size;

    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &stBgdiffFg, u8Stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_U16, &stCurGrad, u16Stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_U16, &stBgGrad, u16Stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &stGragFg, u8Stride);

    ret = bm_image_alloc_dev_mem(stBgdiffFg, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(stBgdiffFg, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(stBgdiffFg, in_ptr);

    ret = bm_image_alloc_dev_mem(stCurGrad, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(stBgGrad, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(stGragFg, BMCV_HEAP1_ID);

    // Create Fake Data.
    ret = bmcv_ive_norm_grad(handle, &stBgdiffFg, NULL, NULL, &stCurGrad, normGradAttr);

    normGradAttr.u8_norm = 2;
    ret = bmcv_ive_norm_grad(handle, &stBgdiffFg, NULL, NULL, &stBgGrad, normGradAttr);
    ret = bmcv_ive_gradfg(handle, stBgdiffFg, stCurGrad, stBgGrad, stGragFg, gradFgAttr);

    unsigned char *gradFg_res = (unsigned char*)malloc(width * height * sizeof(unsigned char));
    memset(gradFg_res, 0, width * height * sizeof(unsigned char));

    ret = bm_image_copy_device_to_host(stGragFg, (void**)&gradFg_res);

    FILE *ive_fp = fopen(dst_name, "wb");
    fwrite((void *)gradFg_res, 1, width * height, ive_fp);
    fclose(ive_fp);
    free(gradFg_res);

    bm_image_destroy(&stBgdiffFg);
    bm_image_destroy(&stCurGrad);
    bm_image_destroy(&stBgGrad);
    bm_image_destroy(&stGragFg);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_ive_integ

## 描述

该 API 使用ive硬件资源, 创建灰度图像的积分图计算任务，积分像素值等于灰度图的左上角与当前点所围成的矩形区域内所有像素点灰度值之和/平方和。

## 语法

```c++
bm_status_t bmcv_ive_integ(
    bm_handle_t        handle,
    bm_image           input,
    bm_device_mem_t    output,
    bmcv_ive_integ_ctrl_s  integ_attr);
```

## 参数

### bmcv_ive_integ 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体, 不能为空。 |
| output | 输出 | 输入 bm_device_mem_t 对象数据结构体, 宽、高同 input。 |
| integ_attr | 输入 | 积分图计算控制参数结构体，不能为空。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| input | GRAY | DATA_TYPE_EXT_1N_BYTE | 32x16~1920x1080 |

## 数据类型说明

### 定义积分图输出控制参数

```c++
typedef enum _ive_integ_out_ctrl_e {
    IVE_INTEG_MODE_COMBINE = 0x0,
    IVE_INTEG_MODE_SUM = 0x1,
    IVE_INTEG_MODE_SQSUM = 0x2,
    IVE_INTEG_MODE_BUTT
} ive_integ_out_ctrl_e;
```

| 成员名称 | 描述 |
|---------|------|
| IVE_INTEG_MODE_COMBINE | 和、平方和积分图组合输出。 |
| IVE_INTEG_MODE_SUM | 仅和积分图输出。 |
| IVE_INTEG_MODE_SQSUM | 仅平方和积分图输出。 |

### 定义积分图计算控制参数

```c++
typedef struct bmcv_integ_ctrl_t{
    ive_integ_out_ctrl_e en_out_ctrl;
} bmcv_ive_integ_ctrl_s;
```

| 成员名称 | 描述 |
|---------|------|
| en_out_ctrl | 积分图输出控制参数。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入图像的 width 都需要16对齐。

2. IVE_INTEG_MODE_COMBINE, 组合输出模式, 输出图像数据类型必须为u64, 计算公式如下:

   $$
   \begin{aligned}
      & I_{\text{sum}}(x, y) = \sum_{i \geq 0}^{i \leq x} \sum_{j \geq 0}^{j \leq y} I(i, j) \\
      & I_{\text{sq}}(x, y)  = \sum_{i \geq 0}^{i \leq x} \sum_{j \geq 0}^{j \leq y} (I(i, j) \cdot I(i, j)) \\
      & I_{\text{out}}(x, y) = (I_{\text{sq}}(x, y) \ll 28 \mid I_{\text{sum}}(x, y) \& 0xFFFFFFF)
   \end{aligned}
   $$

3. IVE_INTEG_MODE_SUM, 仅和积分图输出模式, 输出图像数据类型必须为u32。

   $$
   \begin{aligned}
      & I_{\text{sum}}(x, y) = \sum_{i \geq 0}^{i \leq x} \sum_{j \geq 0}^{j \leq y} I(i, j) \\
      & I_{\text{out}}(x, y) = I_{\text{sum}}(x, y)
   \end{aligned}
   $$

4. IVE_INTEG_MODE_SQSUM, 仅平方和积分图输出模式, 输出图像数据类型必须为u32。

   $$
   \begin{aligned}
      & I_{\text{sq}}(x, y)  = \sum_{i \geq 0}^{i \leq x} \sum_{j \geq 0}^{j \leq y} (I(i, j) \cdot I(i, j)) \\
      & I_{\text{out}}(x, y) = I_{\text{sq}}(x, y)
   \end{aligned}
   $$

其中，$I(x, y)$ 对应 input, $I_{\text{sum}}$ 对应 output。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext src_fmt = FORMAT_GRAY;
    ive_integ_out_ctrl_e integ_mode = 0;
    char* src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bmcv_ive_integ_ctrl_s integ_attr;
    bm_image src;
    bm_device_mem_t dst;
    int src_stride[4];

    // calc ive image stride && create bm image struct
    int data_size = 1;
    src_stride[0] = align_up(width, 16) * data_size;

    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, src_stride);
    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    if (ret != BM_SUCCESS) {
        printf("bm_image_alloc_dev_mem_src. ret = %d\n", ret);
        exit(-1);
    }

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);
    data_size = sizeof(unsigned int);

    ret = bm_malloc_device_byte(handle, &dst, height * width * data_size);
    integ_attr.en_out_ctrl = integ_mode;

    ret = bmcv_ive_integ(handle, src, dst, integ_attr);

    unsigned int *dst_intg_u32 =  malloc(width * height * data_size);
    ret = bm_memcpy_d2s(handle, dst_intg_u32, dst);
    FILE *intg_result_fp = fopen(dst_name, "wb");
    fwrite((void *)dst_intg_u32, data_size, width * height, intg_result_fp);
    fclose(intg_result_fp);

    free(dst_intg_u32);

    bm_image_destroy(&src);
    bm_free_device(handle, dst);

    bm_dev_free(handle);
    return 0;
}
```

# bmcv_ive_lbp

## 描述

该 API 使用ive硬件资源, lbp是描述图像局部特征的算子，邻域窗口内的像素值与中心像素值进行相减结果和阈值对比求和得到这一局部的中心像素值。

## 语法

```c++
bm_status_t bmcv_ive_lbp(
    bm_handle_t         handle,
    bm_image            input,
    bm_image            output,
    bmcv_ive_lbp_ctrl_attr    lbp_attr);
```

## 参数

### bmcv_ive_lbp 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体, 不能为空。 |
| output | 输出 | 输出 bm_image 对象结构体, 不能为空, 宽、高同 input。 |
| lbp_attr | 输入 | LBP 纹理计算控制参数结构体, 不能为空。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| input | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| output | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |

## 数据类型说明

### 定义LBP计算的比较模式

```c++
typedef enum bmcv_lbp_cmp_mode_e{
    BM_IVE_LBP_CMP_MODE_NORMAL = 0x0,
    BM_IVE_LBP_CMP_MODE_ABS    = 0x1,
} bmcv_lbp_cmp_mode;
```

| 成员名称 | 描述 |
|---------|------|
| BM_IVE_LBP_CMP_MODE_NORMAL | LBP 简单比较模式。 |
| BM_IVE_LBP_CMP_MODE_ABS | LBP 绝对值比较模式。 |

### 定义 8 bit 数据联合体

```c++
typedef union bmcv_ive_8bit_u{
    signed char  s8_val;
    unsigned char u8_val;
} bmcv_ive_8bit;
```

| 成员名称 | 描述 |
|---------|------|
| s8_val | 有符号的 8bit 值。 |
| u8_val | 无符号的 8bit 值。 |

### 定义 LBP 纹理计算控制参数

```c++
typedef struct bmcv_lbp_ctrl_attr_s{
    bmcv_lbp_cmp_mode en_mode;
    bmcv_ive_8bit     un8_bit_thr;
} bmcv_ive_lbp_ctrl_attr;
```

| 成员名称 | 描述 |
|---------|------|
| en_mode | LBP 比较模式。 |
| un8_bit_thr | LBP 比较阈值。BM_IVE_LBP_CMP_MODE_NORMAL：取值范围：[-128, 127]; BM_IVE_LBP_CMP_MODE_ABS：取值范围：[0, 255]。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。

2. LBP 计算公式：

* BM_IVE_LBP_CMP_MODE_NORMAL:
   $$
   \begin{aligned}
    & lbp(x, y) = \sum_{i = 0}^{7} ((I_{i} - I_{c}) \geq thr ) \ll (7 - i), \text{其中} thr \in [-128, 127];
  \end{aligned}
   $$

* BM_IVE_LBP_CMP_MODE_ABS:
   $$
   \begin{aligned}
    & lbp(x, y) = \sum_{i = 0}^{7} (abs(I_{i} - I_{c}) \geq thr ) \ll (7 - i), \text{其中} thr \in [0, 255]; \\
   \end{aligned}
   $$

其中，$I(x, y)$ 对应 input， $lbp(x, y)$ 对应 output， $thr$ 对应 lbp_attr.un8_bit_thr。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bmcv_lbp_cmp_mode lbpCmpMode = BM_IVE_LBP_CMP_MODE_NORMAL;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;
    int stride[4];

    // calc ive image stride && create bm image struct
    int data_size = 1;
    stride[0] = align_up(width, 16) * data_size;
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &src, stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, stride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);
    bmcv_ive_lbp_ctrl_attr lbp_ctrl;
    lbp_ctrl.en_mode = lbpCmpMode;
    lbp_ctrl.un8_bit_thr.s8_val = (lbpCmpMode == BM_IVE_LBP_CMP_MODE_ABS ? 35 : 41);

    ret = bmcv_ive_lbp(handle, src, dst, lbp_ctrl);

    unsigned char* ive_lbp_res = malloc(width * height * sizeof(unsigned char));
    memset(ive_lbp_res, 0, width * height * sizeof(unsigned char));

    ret = bm_image_copy_device_to_host(dst, (void **)&ive_lbp_res);

    FILE *ive_result_fp = fopen(dst_name, "wb");
    fwrite((void *)ive_lbp_res, 1, width * height, ive_result_fp);
    fclose(ive_result_fp);

    free(input_data);
    free(ive_lbp_res);

    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);
```

# bmcv_ive_mag_and_ang

## 描述

该 API 使用ive硬件资源, 创建 5x5 模板，计算灰度图的每个像素区域位置灰度值变化梯度的幅值和幅角任务。

## 语法

```c++
bm_status_t bmcv_ive_mag_and_ang(
    bm_handle_t            handle,
    bm_image  *             input,
    bm_image  *            mag_output,
    bm_image  *            ang_output,
    bmcv_ive_mag_and_ang_ctrl  attr);
```

## 参数

### bmcv_ive_magandang 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| \*input | 输入 | 输入 bm_image 对象指针, 不能为空。 |
| \*mag_output | 输出 | 输出 bm_image 对象数据指针, 输出幅值图像, 不能为空, 宽、高同 input。 |
| \*ang_output | 输出 | 输出 bm_image 对象数据指针, 输出幅角图像。根据 attr.en_out_ctrl, 需要输出则不能为空, 宽、高同 input。 |
| \attr | 输入 | 控制信息结构体, 存放梯度幅值和幅角计算的控制信息，不能为空。 |

### 图像参数表

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|----------|----------|--------|
| input | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| mag_output | GRAY | DATA_TYPE_EXT_U16 | 同 input |
| ang_output | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 input |

## 数据类型说明

### 梯度幅值与角度计算的输出格式

```c++
typedef enum bmcv_ive_mag_and_ang_outctrl_e{
    BM_IVE_MAG_AND_ANG_OUT_MAG = 0x0,
    BM_IVE_MAG_AND_ANG_OUT_ALL = 0X1,
} bmcv_ive_mag_and_ang_outctrl;
```

| 成员名称 | 描述 |
|---------|------|
| BM_IVE_MAG_AND_ANG_OUT_MAG | 仅输出幅值。 |
| BM_IVE_MAG_AND_ANG_OUT_ALL | 同时输出幅值和角度值。 |

### 梯度幅值和幅角计算的控制信息

```c++
typedef struct bmcv_ive_mag_and_ang_ctrl_s{
    bmcv_ive_mag_and_ang_outctrl     en_out_ctrl;
    unsigned short               u16_thr;
    signed char                  as8_mask[25];
} bmcv_ive_mag_and_ang_ctrl;
```

| 成员名称 | 描述 |
|---------|------|
| en_out_ctrl | 输出格式。 |
| u16_thr | 用于对幅值进行阈值化的阈值。 |
| as8_mask | 5x5 模板系数。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。
2. 可配置两种输出模式, 详细请参考 bm_ive_mag_and_ang_outctrl。
3. 配置 BM_IVE_MAG_AND_ANG_OUT_ALL 时， 要求 mag_output 与 ang_output 跨度一致。
4. 用户可以通过 attr.u16_thr 对幅值图进行阈值化操作(可用来实现EOH), 计算公式如下:

$$
\text{Mag}(x, y) =
\begin{cases}
    \text{0} & \ (Mag(x, y) < u16_thr) \\
    \text{Mag(x, y)} & \ (Mag(x, y) \geq u16_thr) \\
\end{cases}
$$

其中, $Mag(x, y)$ 对应 mag_output。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    // int templateSize = 0; // 0: 3x3 1:5x5
    unsigned short thrValue = 0;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bmcv_ive_mag_and_ang_outctrl enMode = BM_IVE_MAG_AND_ANG_OUT_ALL;
    char *src_name = "path/to/src";
    char *dst_magName = "path/to/mag_dst", *dst_angName = "path/to/ang_dst";
    /* 3 by 3*/
    signed char arr3by3[25] = { 0, 0, 0, 0,  0, 0, -1, 0, 1, 0, 0, -2, 0,
                    2, 0, 0, -1, 0, 1, 0,  0, 0, 0, 0, 0 };
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    bm_image src;
    bm_image dst_mag, dst_ang;
    int stride[4];
    int magStride[4];

    bmcv_ive_mag_and_ang_ctrl magAndAng_attr;
    memset(&magAndAng_attr, 0, sizeof(bmcv_ive_mag_and_ang_ctrl));
    magAndAng_attr.en_out_ctrl = enMode;
    magAndAng_attr.u16_thr = thrValue;
    memcpy(magAndAng_attr.as8_mask, arr3by3, 5 * 5 * sizeof(signed char));

    // calc ive image stride && create bm image struct
    int data_size = 1;
    stride[0] = align_up(width, 16) * data_size;
    data_size = 2;
    magStride[0] = align_up(width, 16) * data_size;

    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &src, stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_U16, &dst_mag, magStride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst_mag, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);


    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &dst_ang, stride);
    ret = bm_image_alloc_dev_mem(dst_ang, BMCV_HEAP1_ID);

    ret = bmcv_ive_mag_and_ang(handle, &src, &dst_mag, &dst_ang, magAndAng_attr);

    unsigned short* magOut_res = malloc(width * height * sizeof(unsigned short));
    unsigned char*  angOut_res = malloc(width * height * sizeof(unsigned char));
    memset(magOut_res, 0, width * height * sizeof(unsigned short));
    memset(angOut_res, 0, width * height * sizeof(unsigned char));

    ret = bm_image_copy_device_to_host(dst_mag, (void **)&magOut_res);
    ret = bm_image_copy_device_to_host(dst_ang, (void **)&angOut_res);


    FILE *mag_fp = fopen(dst_magName, "wb");
    fwrite((void *)magOut_res, 1, width * height, mag_fp);
    fclose(mag_fp);

    FILE *ang_fp = fopen(dst_angName, "wb");
    fwrite((void *)angOut_res, 1, width * height, ang_fp);
    fclose(ang_fp);

    free(input_data);
    free(magOut_res);
    free(angOut_res);

    bm_image_destroy(&src);
    bm_image_destroy(&dst_mag);
    bm_image_destroy(&dst_ang);

    bm_dev_free(handle);
    return 0;
}
```

# bmcv_ive_normgrad

## 描述

该 API 使用ive硬件资源, 创建归一化梯度计算任务，梯度分量均归一化到 S8。

## 语法

```c++
bm_status_t bmcv_ive_norm_grad(
    bm_handle_t             handle,
    bm_image  *             input,
    bm_image  *             output_h,
    bm_image  *             output_v,
    bm_image  *             output_hv,
    bmcv_ive_normgrad_ctrl    normgrad_attr);
```

## 参数

### bmcv_ive_norm_grad 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| \*input | 输入 | 输入 bm_image 对象数据指针, 不能为空。 |
| \*output_h | 输出 | 输出 bm_image 对象数据指针, 由模板直接滤波并归一到 s8 后得到的梯度分量图像 (H) 指针, 根据 normgrad_attr.en_mode, 若需要输出，则不能为空。 |
| \*output_v | 输出 | 输出 bm_image 对象数据指针, 由模板直接滤波并归一到 s8 后得到的梯度分量图像 (V) 指针, 根据 normgrad_attr.en_mode, 若需要输出则不能为空。 |
| \*output_hv | 输出 | 输出 bm_image 对象数据指针, 由模板和转置后的模板直接滤波, 并归一到 s8 后采用 package 格式存储的图像指针。根据 normgrad_attr.en_mode, 若需要输出则不为空。 |
| \normgrad_attr | 输入 | 归一化梯度信息计算参数, 不能为空。 |

### 图像参数表

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|----------|----------|--------|
| input | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| output_h | GRAY | DATA_TYPE_EXT_1N_BYTE_SIGNED | 64x64~1920x1080 |
| output_v | GRAY | DATA_TYPE_EXT_1N_BYTE_SIGNED | 64x64~1920x1080 |
| output_hv | GRAY | DATA_TYPE_EXT_U16 | 64x64~1920x1080 |

## 数据类型说明

### 归一化梯度信息计算任务输出控制枚举类型

```c++
typedef enum bmcv_ive_normgrad_outmode_e{
    BM_IVE_NORM_GRAD_OUT_HOR_AND_VER = 0x0,
    BM_IVE_NORM_GRAD_OUT_HOR         = 0x1,
    BM_IVE_NORM_GRAD_OUT_VER         = 0x2,
    BM_IVE_NORM_GRAD_OUT_COMBINE     = 0x3,
} bmcv_ive_normgrad_outmode;
```

| 成员名称 | 描述 |
|---------|------|
| BM_IVE_NORM_GRAD_OUT_HOR_AND_VER | 同时输出梯度信息的H、V 分量图。 |
| BM_IVE_NORM_GRAD_OUT_HOR | 仅输出梯度信息的 H 分量图。 |
| BM_IVE_NORM_GRAD_OUT_VER | 仅输出梯度信息的 V 分量图。 |
| BM_IVE_NORM_GRAD_OUT_COMBINE | 输出梯度信息以 package 存储的 HV 图。 |

### 归一化梯度信息计算任务输出控制枚举类型

```c++
typedef struct bmcv_ive_normgrad_ctrl_s{
    bmcv_ive_normgrad_outmode en_mode;
    signed char as8_mask[25];
    unsigned char u8_norm;
} bmcv_ive_normgrad_ctrl;
```

| 成员名称 | 描述 |
|---------|------|
| en_mode | 梯度信息输出控制模式。 |
| as8_mask | as8Mask 计算梯度需要的模板。 |
| u8_norm | 归一化参数, 取值范围: [1, 13]。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。

2. 控制参数中输出模式如下：
   - BM_IVE_NORM_GRAD_OUT_HOR_AND_VER 时，output_h 和 output_v 指针不能为空，且要求跨度一致。
   - BM_IVE_NORM_GRAD_OUT_HOR 时，output_h 不能为空。
   - BM_IVE_NORM_GRAD_OUT_VER 时，output_v 不能为空。
   - BM_IVE_NORM_GRAD_OUT_COMBINE 时，output_hv 不能为空。

3. 计算公式如下：

```
I_out(x, y) = { ∑_{-2 < j < 2} ∑_{-2 < i < 2} I(x+i, y+j) · coef(i, j) } >> norm(x)
```

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    bmcv_ive_normgrad_outmode enMode = BM_IVE_NORM_GRAD_OUT_HOR_AND_VER;
    bm_image_format_ext fmt = FORMAT_GRAY;
    char *src_name = "path/to/src";
    char *dst_hName = "path/to/dst_h", *dst_vName = "path/to/dst_v";

    bm_handle_t handle = NULL;
    /* 3 by 3*/
    signed char arr3by3[25] = { 0, 0, 0, 0,  0, 0, -1, 0, 1, 0, 0, -2, 0,
                    2, 0, 0, -1, 0, 1, 0,  0, 0, 0, 0, 0 };
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src;
    bm_image dst_H, dst_V, dst_conbine_HV;
    int src_stride[4];
    int dst_stride[4];

    bmcv_ive_normgrad_ctrl normgrad_attr;
    normgrad_attr.u8_norm = 8;
    normgrad_attr.en_mode = enMode;
    (memcpy(normgrad_attr.as8_mask, arr3by3, 5 * 5 * sizeof(signed char)));

    // calc ive image stride && create bm image struct
    int data_size = 1;
    src_stride[0] = align_up(width, 16) * data_size;
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &src, src_stride);
    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    dst_stride[0] = align_up(width, 16) * data_size;
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE_SIGNED, &dst_H, dst_stride);
    ret = bm_image_alloc_dev_mem(dst_H, BMCV_HEAP1_ID);

    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE_SIGNED, &dst_V, dst_stride);
    ret = bm_image_alloc_dev_mem(dst_V, BMCV_HEAP1_ID);

    ret = bmcv_ive_norm_grad(handle, &src, &dst_H, &dst_V, &dst_conbine_HV, normgrad_attr);

    signed char* ive_h_res = malloc(width * height * sizeof(signed char));
    signed char* ive_v_res = malloc(width * height * sizeof(signed char));
    unsigned short* ive_combine_res = malloc(width * height * sizeof(unsigned short));

    memset(ive_h_res, 0, width * height * sizeof(signed char));
    memset(ive_v_res, 0, width * height * sizeof(signed char));
    memset(ive_combine_res, 1, width * height * sizeof(unsigned short));

    ret = bm_image_copy_device_to_host(dst_H, (void**)&ive_h_res);
    ret = bm_image_copy_device_to_host(dst_V, (void**)&ive_v_res);

    FILE *iveH_fp = fopen(dst_hName, "wb");
    fwrite((void *)ive_h_res, sizeof(signed char), width * height, iveH_fp);
    fclose(iveH_fp);

    FILE *iveV_fp = fopen(dst_vName, "wb");
    fwrite((void *)ive_v_res, sizeof(signed char), width * height, iveV_fp);
    fclose(iveV_fp);

    free(input_data);
    free(ive_h_res);
    free(ive_v_res);
    free(ive_combine_res);

    bm_image_destroy(&dst_H);
    bm_image_destroy(&dst_V);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_ive_resize

## 描述

该 API 使用ive硬件资源，创建图像缩放任务，支持双线性插值、区域插值缩放，支持多张 GRAY 与 RGB PLANAR 图像同时输入做一种类型的缩放。

## 语法

```c
bm_status_t bmcv_ive_resize(
    bm_handle_t              handle,
    bm_image                 input,
    bm_image                 output,
    bmcv_resize_algorithm     resize_mode);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体，不能为空。 |
| output | 输出 | 输出 bm_image 对象结构体，不能为空，每张图像类型同input。 |
| resize_mode | 输入 | 输入 bmcv_resize_algorithm 对象，枚举控制信息。 |

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| input | GRAY<br>RGB_PLANAR | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| output | GRAY<br>RGB_PLANAR | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |

## 数据类型说明

定义 Resize 模式。

```c
typedef enum bmcv_resize_algorithm_ {
    BMCV_INTER_NEAREST = 0,
    BMCV_INTER_LINEAR  = 1,
    BMCV_INTER_BICUBIC = 2,
    BMCV_INTER_AREA = 3,
} bmcv_resize_algorithm;
```

| 成员名称 | 描述 |
|---------|------|
| BMCV_INTER_NEAREST | 最近邻插值模式。 |
| BMCV_INTER_LINEAR | 双线性插值缩放模式。 |
| BMCV_INTER_BICUBIC | 双三次插值模式。 |
| BMCV_INTER_AREA | 区域插值缩放模式。 |

## 返回值

该函数成功调用时，返回 BM_SUCCESS。

## 注意

1. 支持 GRAY、RGB_PLANAR 混合图像数组输入，但所有图像的缩放模式相同。
2. 目前插值模式只支持双线性插值和区域插值缩放模式。
3. 最大支持 16 倍缩放。
4. 输入输出图像的 width 都需要16对齐。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    bmcv_resize_algorithm resize_mode = BMCV_INTER_AREA;
    bm_image_format_ext format = FORMAT_GRAY;
    int src_width = 1920, src_height = 1080;
    int dst_width = 400;
    int dst_height = 300;

    char *src_name = "path/to/src";
    char *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;
    int src_stride[4], dst_stride[4];

    int data_size= 1;
    int byte_size;
    int image_byte_size[4] = {0};
    // calc ive image stride && create bm image struct
    src_stride[0] = align_up(src_width, 16) * data_size;
    bm_image_create(handle, src_height, src_width, format, DATA_TYPE_EXT_1N_BYTE, &src, src_stride);

    dst_stride[0] = align_up(dst_width, 16) * data_size;
    bm_image_create(handle, dst_height, dst_width, format, DATA_TYPE_EXT_1N_BYTE, &dst, dst_stride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    bm_image_get_byte_size(src, image_byte_size);
    byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
        printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    ret = bmcv_ive_resize(handle, src, dst, resize_mode);

    bm_image_get_byte_size(dst, image_byte_size);
    byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char* output_ptr = (unsigned char *)malloc(byte_size);
    memset(output_ptr, 0, sizeof(byte_size));

    void* out_ptr[4] = {(void*)output_ptr,
                    (void*)((char*)output_ptr + image_byte_size[0]),
                    (void*)((char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                    (void*)((char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};

    ret = bm_image_copy_device_to_host(dst, (void **)out_ptr);

    FILE *ive_fp = fopen(dst_name, "wb");
    fwrite((void *)output_ptr, 1, byte_size, ive_fp);
    fclose(ive_fp);

    free(input_data);
    free(output_ptr);

    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);
    return 0;
}
```

# bmcv_ive_stcandicorner

## 描述

该 API 使用ive硬件资源, 完成灰度图像 Shi-Tomasi-like 角点（两条边缘的交点）计算，角点在任意一个方向上做微小移动，都会引起该区域的梯度图的方向和幅值发生很大变化。

## 语法

```c++
bm_status_t bmcv_ive_stcandicorner(
    bm_handle_t                 handle,
    bm_image                    input,
    bm_image                    output,
    bmcv_ive_stcandicorner_attr   stcandicorner_attr);
```

## 参数

### bmcv_ive_stcandicorner 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| input | 输入 | 输入 bm_image 对象结构体, 不能为空。 |
| output | 输出 | 输出 bm_image 对象数据结构体, 候选角点响应值图像指针, 不能为空, 宽、高同 input。 |
| stcandicorner_attr | 输入 | Shi-Tomas-like 候选角点计算控制参数结构体, 不能为空。 |

### 图像格式参数

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| input | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64～1920x1080 |
| output | GRAY | DATA_TYPE_EXT_1N_BYTE | 同 input |

## 数据类型说明

### 定义 Shi-Tomas-like 候选角点计算控制参数

```c++
typedef struct bmcv_ive_stcandicorner_attr_s{
    bm_device_mem_t st_mem;
    unsigned char   u0q8_quality_level;
} bmcv_ive_stcandicorner_attr;
```

| 成员名称 | 描述 |
|---------|------|
| st_mem | 内存配置大小见 bmcv_image_ive_stcandicorner 的注意。 |
| u0q8_quality_level | ShiTomasi 角点质量控制参数，角点响应值小于 u0q8_quality_level * 最大角点响应值 的点将直接被确认为非角点。取值范围: [1, 255], 参考取值: 25。 |

### 定义 Shi-Tomas-like 角点计算时最大角点响应值结构体

```c++
typedef struct bmcv_ive_st_max_eig_s{
    unsigned short u16_max_eig;
    unsigned char  u8_reserved[14];
} bmcv_ive_st_max_eig;
```

| 成员名称 | 描述 |
|---------|------|
| u16_max_eig | 最大角点响应值。 |
| u8_reserved | 保留位。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

1. 输入输出图像的 width 都需要16对齐。
2. 与 OpenCV 中 ShiTomas 角点计算原理类似。
3. stcandicorner_attr.st_mem 至少需要开辟的内存大小: stcandicorner_attr.st_mem.size = 4 * input_stride * input.height + sizoef(bm_ive_st_max_eig)。
4. 该任务完成后, 得到的并不是真正的角点, 还需要进行下一步计算。

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main(){
    int dev_id = 0;
    int height = 1080, width = 1920;
    int u0q8QualityLevel = 25;
    bm_image_format_ext fmt = FORMAT_GRAY;
    char *src_name = "path/to/src";
    char *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;
    int stride[4];

    bmcv_ive_stcandicorner_attr stCandiCorner_attr;
    memset(&stCandiCorner_attr, 0, sizeof(bmcv_ive_stcandicorner_attr));

    // calc ive image stride && create bm image struct
    int data_size = 1;
    stride[0] = align_up(width, 16) * data_size;
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &src, stride);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &dst, stride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int attr_len = 4 * height * stride[0] + sizeof(bmcv_ive_st_max_eig);
    ret = bm_malloc_device_byte(handle, &stCandiCorner_attr.st_mem, attr_len * sizeof(unsigned char));
    stCandiCorner_attr.u0q8_quality_level = u0q8QualityLevel;

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
      printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    ret = bmcv_ive_stcandicorner(handle, src, dst, stCandiCorner_attr);

    unsigned char *ive_res = (unsigned char *)malloc(width * height * sizeof(unsigned char));
    memset(ive_res, 0, width * height * sizeof(unsigned char));

    ret = bm_image_copy_device_to_host(dst, (void**)&ive_res);

    FILE *ive_fp = fopen(dst_name, "wb");
    fwrite((void *)ive_res, 1, width * height, ive_fp);
    fclose(ive_fp);

    free(input_data);
    free(ive_res);

    bm_image_destroy(&src);
    bm_image_destroy(&dst);
    bm_free_device(handle, stCandiCorner_attr.st_mem);

    bm_dev_free(handle);
    return 0;
}
```

# bmcv_ive_update_bgmodel

## 描述

该 API 使用ive硬件资源, 输入当前图像和模型，更新背景模型。

## 语法

```c++
bm_status_t bmcv_ive_update_bgmodel(
    bm_handle_t                handle,
    bm_image  *                cur_img,
    bm_image  *                bgmodel_img,
    bm_image  *                fgflag_img,
    bm_image  *                bg_img,
    bm_image  *                chgsta_img,
    bm_device_mem_t            stat_data_mem,
    bmcv_ive_update_bgmodel_attr attr);
```

## 参数

### bmcv_ive_update_bgmodel 参数表

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| *cur_img | 输入 | 输入 bm_image 对象指针, 当前图像指针，不能为空。 |
| *bgmodel_img | 输入/输出 | 背景模型数据 bm_image 对象指针，不能为空。 |
| *fgflag_img | 输入/输出 | 前景状态图像 bm_image 对象指针, 不能为空。 |
| *bg_img | 输出 | 背景图像 bm_image 对象指针，不能为空，宽、高同 fgflag_img。 |
| *chgsta_img | 输出 | 前景更新状态图像 bm_image 对象指针，当 updateBgmodel_attr.u8DetChgRegion 为 0 时，可以为空，宽、高同 fgflag_img。 |
| stat_data_mem | 输出 | 前景状态数据结构体，不能为空，内存至少需配置 sizeof(bm_ive_bg_stat_data)。 |
| attr | 输入 | 控制参数结构体, 不能为空。 |

### 图像格式参数

| 参数名称 | 图像格式 | 数据类型 | 分辨率 |
|---------|---------|---------|--------|
| cur_img | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| bgmodel_img | GRAY | DATA_TYPE_EXT_1N_BYTE | -- |
| fgflag_img | GRAY | DATA_TYPE_EXT_1N_BYTE | 64x64~1920x1080 |
| bg_img | GRAY | DATA_TYPE_EXT_S16 | 64x64~1920x1080 |
| chgsta_img | GRAY | DATA_TYPE_EXT_U32 | 64x64~1920x1080 |

## 数据类型说明

### 定义背景更新控制参数

```c++
typedef struct bmcv_ive_update_bgmodel_attr_s{
    unsigned int u32_cur_frm_num;
    unsigned int u32_pre_chk_time;
    unsigned int u32_frm_chk_period;
    unsigned int u32_init_min_time;
    unsigned int u32_sty_bg_min_blend_time;
    unsigned int u32_sty_bg_max_blend_time;
    unsigned int u32_dyn_bg_min_blend_time;
    unsigned int u32_static_det_min_time;
    unsigned short u16_fg_max_fade_time;
    unsigned short u16_bg_max_fade_time;
    unsigned char u8_sty_bg_acc_time_rate_thr;
    unsigned char u8_chg_bg_acc_time_rate_thr;
    unsigned char u8_dyn_bg_acc_time_thr;
    unsigned char u8_dyn_bg_depth;
    unsigned char u8_bg_eff_sta_rate_thr;
    unsigned char u8_acce_bg_learn;
    unsigned char u8_det_chg_region;
} bmcv_ive_update_bgmodel_attr;
```

| 成员名称 | 描述 |
|---------|------|
| u32_cur_frm_num | 当前帧时间。 |
| u32_pre_chk_time | 上次进行背景状态检查的时间点。 |
| u32_frm_chk_period | 背景状态检查时间周期。取值范围：[0, 2000]。参考取值：50。 |
| u32_init_min_time | 背景初始化最短时间。取值范围：[20, 6000]。参考取值：100。 |
| u32_sty_bg_min_blend_time | 稳定背景融入最短时间取值范围：[u32_init_min_time, 6000]。参考取值：20。 |
| u32_sty_bg_max_blend_time | 稳定背景融入最长时间取值范围：[u32_sty_bg_min_blend_time, 40000]。参考取值：1500。 |
| u32_dyn_bg_min_blend_time | 动态背景融入最短时间。取值范围：[0, 6000]。参考取值：1500。 |
| u32_static_det_min_time | 静物检测最短时间。取值范围：[20, 6000]。参考取值：80。 |
| u16_fg_max_fade_time | 前景持续消失最长时间。取值范围：[1, 255]。参考取值：15。 |
| u16_bg_max_fade_time | 背景持续消失时间。取值范围：[1, 255]。参考取值：60。 |
| u8_sty_bg_acc_time_rate_thr | 稳态背景访问时间比率阈值。取值范围：[10, 100]。参考取值：80。 |
| u8_chg_bg_acc_time_rate_thr | 变化背景访问时间比率阈值。取值范围：[10, 100]。参考取值：60。 |
| u8_dyn_bg_acc_time_thr | 动态背景访问时间比率阈值。取值范围：[0, 50]。参考取值：0。 |
| u8_dyn_bg_depth | 动态背景深度。取值范围：[0, 3]。参考取值：3。 |
| u8_bg_eff_sta_rate_thr | 背景初始化阶段背景状态时间比率阈值。取值范围：[90, 100]。参考取值：90。 |
| u8_acce_bg_learn | 是否加速背景学习。取值范围：{0, 1}，0 表示不加速，1 表示加速。参考取值：0。 |
| u8_det_chg_region | 是否检测变化区域。取值范围：{0, 1}，0 表示不检测，1 表示检测。参考取值：0。 |

# bmcv_image_jpeg_enc

## 描述

该接口可以实现对多张 bm_image 的 JPEG 编码过程。

## 语法

```cpp
bm_status_t bmcv_image_jpeg_enc(
        bm_handle_t handle,
        int         image_num,
        bm_image *  src,
        void *      p_jpeg_data[],
        size_t *    out_size,
        int         quality_factor = 85
);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image_num | 输入 | 输入图片数量，最多支持 4。 |
| *src | 输入 | 输入 bm_image的指针。每个 bm_image 需要外部调用 bmcv_image_create 创建，image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存,或者使用 bmcv_image_attach 来 attach 已有的内存。 |
| *p_jpeg_data[] | 输出 | 编码后图片的数据指针，由于该接口支持对多张图片的编码，因此为指针数组，数组的大小即为 image_num。用户可以选择不为其申请空间（即数组每个元素均为NULL），在 api 内部会根据编码后数据的大小自动分配空间，但当不再使用时需要用户手动释放该空间。当然用户也可以选择自己申请足够的空间。 |
| *out_size | 输入 | 完成编码后各张图片的大小（以 byte 为单位）存放在该指针中。 |
| quality_factor | 输入 | 编码后图片的质量因子。取值 0～100 之间，值越大表示图片质量越高，但数据量也就越大，反之值越小图片质量越低，数据量也就越少。该参数为可选参数，默认值为85。 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 注意

目前编码支持的图片格式包括以下几种：
- FORMAT_YUV420P
- FORMAT_YUV422P
- FORMAT_YUV444P
- FORMAT_NV12
- FORMAT_NV21
- FORMAT_NV16
- FORMAT_NV61
- FORMAT_GRAY

目前编码支持的数据格式如下：
- DATA_TYPE_EXT_1N_BYTE

## 代码示例

```cpp
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <memory.h>
#include "bmcv_api_ext_c.h"
#include <assert.h>
#include <math.h>

#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main() {
    int dev_id = -1;
    int dev_cnt;
    int ret = 0;
    bm_dev_getcount(&dev_cnt);
    if (dev_id >= dev_cnt) {
        printf("[TEST JPEG] dev_id should less than device count, only detect %d devices\n", dev_cnt);
        exit(-1);
    }
    printf("device count = %d\n", dev_cnt);
    bm_handle_t handle[dev_cnt];

    for (int i = 0; i < dev_cnt; i++) {
        int id;
        if (dev_id != -1) {
            dev_cnt = 1;
            id = dev_id;
        } else {
            id = i;
        }
        bm_status_t req = bm_dev_request(handle + i, id);
        if (req != BM_SUCCESS) {
            printf("create bm handle for dev%d failed!\n", id);
            exit(-1);
        }
    }
    for (int j = 0; j < dev_cnt; j++) {
        char *src_name = "path/to/src";
        int format = FORMAT_YUV420P;
        int image_n = 1;
        int image_h = 1080;
        int image_w = 1920;
        int* stride = (int*)malloc(3 * sizeof(int));
        stride[0] = align_up(image_w, 16);
        stride[1] = align_up(image_w / 2, 16);
        stride[2] = align_up(image_w / 2, 16);

        bm_image src[4];
        for (int i = 0; i < image_n; i++) {
            bm_image_create(handle[j], image_h, image_w, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, src + i, stride);
            bm_image_alloc_dev_mem(src[i], BMCV_HEAP1_ID);
        }
        int image_byte_size[4] = {0};
        bm_image_get_byte_size(src[0], image_byte_size);
        for (int i = 0; i < 4; i++) {
            printf("src_%d_byte_size: %d\n", i, image_byte_size[i]);
        }
        int byte_size = image_w * image_h * 3 / 2;
        unsigned char *input_data = (unsigned char *)malloc(byte_size);
        FILE *fp_src = fopen(src_name, "rb");
        if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
        printf("file size is less than required bytes%d\n", byte_size);
        };
        fclose(fp_src);
        void* in_ptr[4] = {(void *)input_data,
                            (void *)((unsigned char*)input_data + image_byte_size[0]),
                            (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                            (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
        bm_image_copy_host_to_device(src[0], in_ptr);
        void* jpeg_data[4] = {NULL, NULL, NULL, NULL};
        size_t* size = (size_t*)malloc(image_n * sizeof(size_t));
        ret = bmcv_image_jpeg_enc(handle[j], image_n, src, jpeg_data, size, 95);
        if (ret != BM_SUCCESS) exit(-1);

        for (int i = 0; i < image_n; i++) {
            free(jpeg_data[i]);
            bm_image_destroy(&src[i]);
        }
        free(input_data);
        free(size);
        free(stride);
    }
    for (int i = 0; i < dev_cnt; i++) {
        bm_dev_free(handle[i]);
    }
    return ret;
}
```

# bmcv_image_mosaic

**描述：**

该接口用于在图像上打一个或多个马赛克。

**语法：**

```cpp
bm_status_t bmcv_image_mosaic(
            bm_handle_t handle,
            int mosaic_num,
            bm_image input,
            bmcv_rect_t * mosaic_rect,
            int is_expand)
```

**参数：**

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| mosaic_num | 输入 | 马赛克数量，指 mosaic_rect 指针中所包含的 bmcv_rect_t 对象个数。 |
| input | 输入 | 需要打马赛克的 bm_image 对象。 |
| *mosaic_rect | 输入 | 马赛克对象指针，包含每个马赛克起始点和宽高。具体内容参考下面的数据类型说明。 |
| is_expand | 输入 | 是否扩列。值为0时表示不扩列, 值为1时表示在原马赛克周围扩列一个宏块(8个像素)。 |

# 数据类型说明：

```cpp
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

* start_x 描述了马赛克在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)
* start_y 描述了马赛克在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)
* crop_w 描述的马赛克的宽度
* crop_h 描述的马赛克的高度

## 返回值：

该函数成功调用时，返回 BM_SUCCESS。

## 格式支持：

### 1. 输入和输出的数据类型

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

### 2. 输入和输出的色彩格式

| num | image_format         |
|-----|----------------------|
| 1   | FORMAT_YUV420P       |
| 2   | FORMAT_YUV444P       |
| 3   | FORMAT_NV12          |
| 4   | FORMAT_NV21          |
| 5   | FORMAT_RGB_PLANAR    |
| 6   | FORMAT_BGR_PLANAR    |
| 7   | FORMAT_RGB_PACKED    |
| 8   | FORMAT_BGR_PACKED    |
| 9   | FORMAT_RGBP_SEPARATE |
| 10  | FORMAT_BGRP_SEPARATE |
| 11  | FORMAT_GRAY          |

## 注意：

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败
2. 如果马赛克宽高非8对齐，则会自动向上8对齐，若在边缘区域，则8对齐时会往非边缘方向延展
3. 如果马赛克区域超出原图宽高，超出部分会自动贴到原图边缘
4. 仅支持8x8以上的马赛克尺寸

## 示例代码

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

void readBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size){
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size){
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main() {
    int src_h = 1080, src_w = 1920, dev_id = 0;
    bm_image_format_ext src_fmt = FORMAT_RGB_PACKED;
    char *src_name = "path/to/src";
    char *dst_name = "path/to/dst";

    bmcv_rect_t rect = {.start_x = 100, .start_y = 100, .crop_w = 500, .crop_h = 500};
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);

    unsigned char* input_data = malloc(src_h * src_w * 3);
    unsigned char* output_tpu = malloc(src_h * src_w * 3);
    readBin(src_name, input_data, src_h * src_w * 3);
    memset(output_tpu, 0, src_h * src_w * 3);

    bm_image src;
    bm_image_create(handle, src_h, src_w, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    ret = bm_image_alloc_dev_mem(src,BMCV_HEAP1_ID);
    unsigned char *in1_ptr[1] = {input_data};
    bm_image_copy_host_to_device(src, (void **)(in1_ptr));
    bmcv_image_mosaic(handle, 1, src, &rect, false);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + image_byte_size[0]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_device_to_host(src, (void **)out_ptr);
    writeBin(dst_name, output_ptr, src_h * src_w *3);

    free(input_data);
    free(output_ptr);
    bm_image_destroy(&src);
    return ret;
}
```

# bmcv_image_put_text

可以实现在一张图像上写字的功能，并支持指定字的颜色、大小和宽度。

## 接口形式：

```c
typedef struct {
    int x;
    int y;
} bmcv_point_t;

typedef struct {
    unsigned char r;
    unsigned char g;
    unsigned char b;
} bmcv_color_t;

bm_status_t bmcv_image_put_text(
            bm_handle_t handle,
            bm_image image,
            const char* text,
            bmcv_point_t org,
            bmcv_color_t color,
            float fontScale,
            int thickness);
```

## 参数说明：

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_image image
  输入/输出参数。需处理图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* const char* text
  输入参数。待写入的文本内容。当文本内容中有中文时，thickness请设置为0。

* bmcv_point_t org
  输入参数。第一个字符左下角的坐标位置。图像左上角为原点，向右延伸为x方向，向下延伸为y方向。

* bmcv_color_t color
  输入参数。画线的颜色，分别为RGB三个通道的值。

* float fontScale
  输入参数。字体大小。

* int thickness
  输入参数。画线的宽度，对于YUV格式的图像建议设置为偶数。开启中文字库请将该参数设置为0。

## 返回值说明：

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持：

### 1. 该接口目前支持以下 image_format:

| num | image_format   |
|-----|----------------|
| 1   | FORMAT_GRAY    |
| 2   | FORMAT_YUV420P |
| 3   | FORMAT_YUV422P |
| 4   | FORMAT_YUV444P |
| 5   | FORMAT_NV12    |
| 6   | FORMAT_NV21    |
| 7   | FORMAT_NV16    |
| 8   | FORMAT_NV61    |

thickness参数配置为0，即开启中文字库后，image_format 扩展支持 bmcv_image_overlay API 底图支持的格式。

### 2. 目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

### 3. 若文字内容不变，推荐使用 bmcv_gen_text_watermark 与 bmcv_image_overlay 搭配的文字绘制方式，文字生成水印图，重复使用水印图进行osd叠加，以提高处理效率。示例参见bmcv_image_overlay接口文档。

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdio.h>
#include <stdlib.h>

#define IMAGE_CHN_NUM_MAX 3
#define __ALIGN_MASK(x, mask) (((x) + (mask)) & ~(mask))
#define ALIGN(x, a) __ALIGN_MASK(x, (__typeof__(x))(a)-1)

static bmcv_point_t org = {500, 500};
static int fontScale = 5;
static const char text[30] = "Hello, world!";
static unsigned char color[3] = {255, 0, 0};
static int thickness = 2;

static int writeBin(const char* path, void* output_data, int size)
{
    int len = 0;
    FILE* fp_dst = fopen(path, "wb+");

    if (fp_dst == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    len = fwrite((void*)output_data, 1, size, fp_dst);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_dst);
    return 0;
}

static int readBin(const char* path, void* input_data)
{
    int len;
    int size;
    FILE* fp_src = fopen(path, "rb");

    if (fp_src == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    fseek(fp_src, 0, SEEK_END);
    size = ftell(fp_src);
    fseek(fp_src, 0, SEEK_SET);

    len = fread((void*)input_data, 1, size, fp_src);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_src);
    return 0;
}

int main()
{
    int width = 1920;
    int height = 1080;
    int format = FORMAT_YUV420P;
    int ret = 0;
    char* input_path = "path/to/input";
    char* output_path = "path/to/output";
    int i;
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);

    int offset_list[IMAGE_CHN_NUM_MAX] = {0};
    offset_list[0] = width * height;
    offset_list[1] = ALIGN(width, 2) * ALIGN(height, 2) >> 2;
    offset_list[2] = ALIGN(width, 2) * ALIGN(height, 2) >> 2;

    int total_size = 0;
    unsigned char* data_tpu = (unsigned char*)malloc(width * height * IMAGE_CHN_NUM_MAX * sizeof(unsigned char));

    ret = readBin(input_path, data_tpu);

    bm_image input_img;
    unsigned char* in_ptr[IMAGE_CHN_NUM_MAX] = {0};
    bmcv_color_t rgb = {color[0], color[1], color[2]};

    ret = bm_image_create(handle, height, width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &input_img, NULL);
    ret = bm_image_alloc_dev_mem(input_img, BMCV_HEAP1_ID);

    in_ptr[0] = data_tpu;
    in_ptr[1] = data_tpu + offset_list[0];
    in_ptr[2] = data_tpu + offset_list[0] + offset_list[1];

    ret = bm_image_copy_host_to_device(input_img, (void**)in_ptr);
    ret = bmcv_image_put_text(handle, input_img, text, org, rgb, fontScale, thickness);
    ret = bm_image_copy_device_to_host(input_img, (void**)in_ptr);

    bm_image_destroy(&input_img);

    for (i = 0; i < IMAGE_CHN_NUM_MAX; ++i) {
        total_size += offset_list[i];
    }
```

# bmcv_image_quantify

将float类型数据转化成int类型(舍入模式为小数点后直接截断)，并将小于0的数变为0，大于255的数变为255。

## 接口形式

```c
bm_status_t bmcv_image_quantify(
    bm_handle_t handle,
    bm_image input,
    bm_image output);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **bm_image input**  
  输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image output**  
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

## 返回值说明

* **BM_SUCCESS**: 成功
* 其他: 失败

## 格式支持

该接口目前支持以下 image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1 | FORMAT_YUV444P | FORMAT_YUV444P |
| 2 | FORMAT_RGB_PLANAR | FORMAT_RGB_PLANAR |
| 3 | FORMAT_BGR_PLANAR | FORMAT_BGR_PLANAR |
| 4 | FORMAT_RGB_PACKED | FORMAT_RGB_PACKED |
| 5 | FORMAT_BGR_PACKED | FORMAT_BGR_PACKED |
| 6 | FORMAT_RGBP_SEPARATE | FORMAT_RGBP_SEPARATE |
| 7 | FORMAT_BGRP_SEPARATE | FORMAT_BGRP_SEPARATE |
| 8 | FORMAT_GRAY | FORMAT_GRAY |

输入数据目前支持以下 data_type:

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_FLOAT32 |

输出数据目前支持以下 data_type:

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用该接口之前必须确保输入的 image 内存已经申请。
2. 如调用该接口的程序为多线程程序，需要在创建bm_image前和销毁bm_image后加线程锁。
3. 该接口支持图像宽高范围为1x1～8192x8192。
4. 该接口可通过设置环境变量启用双核计算，运行程序前：export TPU_CORES=2或export TPU_CORES=both即可。

## 代码示例

```c
#include <stdio.h>
#include "bmcv_api_ext_c.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>
#include <float.h>

static void read_bin(const char *input_path, float *input_data, int width, int height)
{
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL)
    {
        printf("无法打开输出文件 %s\n", input_path);
        return;
    }
    if(fread(input_data, sizeof(float), width * height, fp_src) != 0)
        printf("read image success\n");
    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int width, int height)
{
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL)
    {
        printf("无法打开输出文件 %s\n", output_path);
        return;
    }
    fwrite(output_data, sizeof(int), width * height, fp_dst);
    fclose(fp_dst);
}

int main() {
    int height = 1080;
    int width = 1920;
    char *input_path = "path/to/input";
    char *output_path = "path/to/output";
    bm_handle_t handle;
    bm_status_t ret = bm_dev_request(&handle, 0);

    float* input_data = (float*)malloc(width * height * 3 * sizeof(float));
    unsigned char* output_tpu = (unsigned char*)malloc(width * height * 3 * sizeof(unsigned char));
    read_bin(input_path, input_data, width, height);

    bm_image input_img;
    bm_image output_img;
    bm_image_create(handle, height, width, (bm_image_format_ext)FORMAT_RGB_PLANAR, DATA_TYPE_EXT_FLOAT32, &input_img, NULL);
    bm_image_create(handle, height, width, (bm_image_format_ext)FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_img, NULL);
    bm_image_alloc_dev_mem(input_img, 1);
    bm_image_alloc_dev_mem(output_img, 1);
    float* in_ptr[1] = {input_data};

    bm_image_copy_host_to_device(input_img, (void **)in_ptr);
    bmcv_image_quantify(handle, input_img, output_img);
    unsigned char* out_ptr[1] = {output_tpu};

    bm_image_copy_device_to_host(output_img, (void **)out_ptr);
    bm_image_destroy(&input_img);
    bm_image_destroy(&output_img);

    write_bin(output_path, output_tpu, width, height);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_image_resize

该接口用于实现图像尺寸的变化,如放大、缩小、抠图等功能。

## 接口形式

```c
bm_status_t bmcv_image_resize(
    bm_handle_t handle,
    int input_num,
    bmcv_resize_image resize_attr[4],
    bm_image* input,
    bm_image* output
);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **int input_num**  
  输入参数。输入图片数，最多支持 4。

* **bmcv_resize_image resize_attr [4]**  
  输入参数。每张图片对应的 resize 参数,最多支持 4 张图片。

* **bm_image\* input**  
  输入参数。输入 bm_image。每个 bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image\* output**  
  输出参数。输出 bm_image。每个 bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存，如果不主动分配将在 api 内部进行自行分配。

## 返回值说明

* **BM_SUCCESS**: 成功
* 其他: 失败

## 数据类型说明

```c
typedef struct bmcv_resize_s{
    int start_x;
    int start_y;
    int in_width;
    int in_height;
    int out_width;
    int out_height;
}bmcv_resize_t;

typedef struct bmcv_resize_image_s{
    bmcv_resize_t *resize_img_attr;
    int roi_num;
    unsigned char stretch_fit;
    unsigned char padding_b;
    unsigned char padding_g;
    unsigned char padding_r;
    unsigned int interpolation;
}bmcv_resize_image;
```

* **bmcv_resize_image** 描述了一张图中 resize 配置信息。
* **roi_num** 描述了一副图中需要进行 resize 的子图总个数。
* **stretch_fit** 表示是否按照原图比例对图片进行缩放，1 表示无需按照原图比例进行缩放，0 表示按照原图比例进行缩放，当采用这种方式的时候，结果图片中为进行缩放的地方将会被填充成特定值。
* **padding_b** 表示当 stretch_fit 设成 0 的情况下，b 通道上被填充的值。
* **padding_r** 表示当 stretch_fit 设成 0 的情况下，r 通道上被填充的值。
* **padding_g** 表示当 stretch_fit 设成 0 的情况下，g 通道上被填充的值。
* **interpolation** 表示缩图所使用的算法。BMCV_INTER_NEAREST 表示最近邻算法，BMCV_INTER_LINEAR 表示线性插值算法，BMCV_INTER_AREA 表示区域差值算法，BMCV_INTER_BICUBIC 表示双三次插值算法。
* **start_x** 描述了 resize 起始横坐标(相对于原图)，常用于抠图功能。
* **start_y** 描述了 resize 起始纵坐标(相对于原图)，常用于抠图功能。
* **in_width** 描述了crop图像的宽。
* **in_height** 描述了crop图像的高。
* **out_width** 描述了输出图像的宽。
* **out_height** 描述了输出图像的高。

## 注意事项

该接口的注意事项与 bmcv_image_vpp_basic 接口相同。

# bmcv_image_rotate_trans

## 描述

实现图像顺时针旋转90度，180度和270度

## 语法

```c++
bm_status_t bmcv_image_rotate_trans(
    bm_handle_t handle,
    bm_image input,
    bm_image output,
    int rotation_angle);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|----------|------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| input | 输出 | 输入的待旋转图像，需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。 |
| output | 输出 | 输出的旋转后图像，需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配 |
| rotation_angle | 输入 | 顺时针旋转角度。可选角度90度，180度，270度 |

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 格式支持

1. 输入和输出的数据类型：

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_YUV444P |
| 2 | FORMAT_NV12 |
| 3 | FORMAT_NV21 |
| 4 | FORMAT_RGB_PLANAR |
| 5 | FORMAT_BGR_PLANAR |
| 6 | FORMAT_RGBP_SEPARATE |
| 7 | FORMAT_BGRP_SEPARATE |
| 8 | FORMAT_GRAY |

## bmcv_image_threshold

**描述：**

该接口用于对图像进行像素阈值化操作。

**语法：**

```c
bm_status_t bmcv_image_threshold(
    bm_handle_t handle,
    bm_image input,
    bm_image output,
    unsigned char thresh,
    unsigned char max_value,
    bm_thresh_type_t type);
```

其中thresh类型如下：

```c
typedef enum {
    BM_THRESH_BINARY = 0,
    BM_THRESH_BINARY_INV,
    BM_THRESH_TRUNC,
    BM_THRESH_TOZERO,
    BM_THRESH_TOZERO_INV,
    BM_THRESH_TYPE_MAX
} bm_thresh_type_t;
```

各个类型对应的具体公式如下：

**参数：**

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 设备环境句柄，通过调用bm_dev_request获取。 |
| input | 输入 | 输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。 |
| output | 输出 | 输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。 |
| thresh | 输入 | 像素阈值，取值范围为0-255。 |
| max_value | 输入 | 阈值化操作后的像素最大值，取值范围为0-255。 |
| type | 输入 | 阈值化类型，取值范围为0-4。 |

**返回值：**

该函数成功调用时，返回BM_SUCCESS。

**格式支持：**

该接口目前支持以下图像格式：

| num | image_format |
|-----|--------------|
| 1 | FORMAT_BGR_PACKED |
| 2 | FORMAT_BGR_PLANAR |
| 3 | FORMAT_RGB_PACKED |
| 4 | FORMAT_RGB_PLANAR |
| 5 | FORMAT_RGBP_SEPARATE |
| 6 | FORMAT_BGRP_SEPARATE |
| 7 | FORMAT_GRAY |
| 8 | FORMAT_YUV420P |
| 9 | FORMAT_YUV422P |
| 10 | FORMAT_YUV444P |
| 11 | FORMAT_NV12 |
| 12 | FORMAT_NV21 |
| 13 | FORMAT_NV16 |
| 14 | FORMAT_NV61 |
| 15 | FORMAT_NV24 |

该接口目前支持的数据格式：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1. 在调用该接口之前必须确保输入图像的内存已经申请。
2. 输入输出图像的数据格式，图像格式必须相同。
3. 目前支持的图像最大宽和高为4096。

**代码示例：**

```c
#include <stdio.h>
#include "bmcv_api_ext_c.h"
#include "test_misc.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>
#include <float.h>

static void read_bin(const char *input_path, unsigned char *input_data, int width, int height)
{
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL)
    {
        printf("无法打开输出文件 %s\n", input_path);
        return;
    }
    if(fread(input_data, sizeof(char), width * height, fp_src) != 0)
        printf("read image success\n");
    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int width, int height)
{
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL)
    {
        printf("无法打开输出文件 %s\n", output_path);
        return;
    }
    fwrite(output_data, sizeof(char), width * height, fp_dst);
    fclose(fp_dst);
}

int main() {
    int height = 1080;
    int width = 1920;
    int type = rand() % 5;
    char *input_path = "path/to/input";
    char *output_path = "path/to/output";
    bm_handle_t handle;
    bm_status_t ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return -1;
    }
    int channel = 1;

    unsigned char threshold = 50;
    unsigned char max_value = 228;
    printf("type: %d\n", type);
    printf("threshold: %d , max_value: %d\n", threshold, max_value);
    printf("width: %d , height: %d , channel: %d \n", width, height, channel);

    unsigned char* input_data = (unsigned char*)malloc(width * height);
    unsigned char* output_tpu = (unsigned char*)malloc(width * height);
    read_bin(input_path, input_data, width, height);

    bm_image input_img;
    bm_image output_img;

    bm_image_create(handle, height, width, (bm_image_format_ext)FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input_img, NULL);
    bm_image_create(handle, height, width, (bm_image_format_ext)FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &output_img, NULL);
    bm_image_alloc_dev_mem(input_img, 1);
    bm_image_alloc_dev_mem(output_img, 1);

    unsigned char* in_ptr[1] = {input_data};
    bm_image_copy_host_to_device(input_img, (void **)in_ptr);
    bmcv_image_threshold(handle, input_img, output_img, threshold, max_value, (bm_thresh_type_t)type);
    unsigned char* out_ptr[1] = {output_tpu};
    bm_image_copy_device_to_host(output_img, (void **)out_ptr);

    bm_image_destroy(&input_img);
    bm_image_destroy(&output_img);

    write_bin(output_path, output_tpu, width, height);
```

# bmcv_image_vpp_basic

## 描述

该 API 可以实现对多张图片的 crop、color-space-convert、resize、padding 及其任意若干个功能的组合。

## 语法

```c++
bm_status_t bmcv_image_vpp_basic(
    bm_handle_t           handle,
    int                   in_img_num,
    bm_image*             input,
    bm_image*             output,
    int*                  crop_num_vec = NULL,
    bmcv_rect_t*          crop_rect = NULL,
    bmcv_padding_atrr_t*  padding_attr = NULL,
    bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR,
    csc_type_t            csc_type = CSC_MAX_ENUM,
    csc_matrix_t*         matrix = NULL);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image_num | 输入 | 输入 image 数量。 |
| \*input | 输入 | 输入 bm_image 对象指针，其指向空间的长度由 in_img_num 决定。 |
| \* output | 输出 | 输出 bm_image 对象指针，其指向空间的长度由 in_img_num 和 crop_num_vec 共同决定，即所有输入图片 crop 数量之和。 |
| \* crop_num_vec | 输入 | 该指针指向对每张输入图片进行 crop 的数量，其指向空间的长度由 in_img_num 决定，如果不使用 crop 功能可填 NULL。 |
| \* crop_rect | 输入 | 每个输出 bm_image 对象所对应的在输入图像上 crop 的参数。 |
| \* padding_attr | 输入 | 所有 crop 的目标小图在 dst image 中的位置信息以及要 padding 的各通道像素值，若不使用 padding 功能则设置为 NULL。 |
| algorithm | 输入 | resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR、BMCV_INTER_AREA 和 BMCV_INTER_BICUBIC 四种，默认情况下是双线性差值。 |
| csc_type | 输入 | color space convert 参数类型选择，填 CSC_MAX_ENUM 则使用默认值，默认为 CSC_YCbCr2RGB_BT601 或者 CSC_RGB2YCbCr_BT601。 |
| \*matrix | 输入 | 如果 csc_type 选择 CSC_USER_DEFINED_MATRIX，则需要用该指针传入系数矩阵。 |

## 数据类型说明

```c++
typedef enum csc_type {
    CSC_YCbCr2RGB_BT601 = 0,
    CSC_YPbPr2RGB_BT601,
    CSC_RGB2YCbCr_BT601,
    CSC_YCbCr2RGB_BT709,
    CSC_RGB2YCbCr_BT709,
    CSC_RGB2YPbPr_BT601,
    CSC_YPbPr2RGB_BT709,
    CSC_RGB2YPbPr_BT709,
    CSC_FANCY_PbPr_BT601 = 100,
    CSC_FANCY_PbPr_BT709,
    CSC_USER_DEFINED_MATRIX = 1000,
    CSC_MAX_ENUM
} csc_type_t;
```

可选的 csc_type 参数。

其中 CbCr 表示 Limit range，其应用 YUV 数据像素范围为[16, 235]，PbPr 表示 Full range，其应用 YUV 数据像素范围为[0, 255]。

BT601/BT709 代表相应的视频颜色空间标准。

FANCY 表示采用与 opencv 相同的处理方式计算上采样（如从 YUV420P 上采样到 RGB）。

```c++
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

start_x、start_y、crop_w、crop_h 分别表示每个输出 bm_image 对象所对应的在输入图像上 crop 的参数，包括起始点 x 坐标、起始点 y 坐标、crop 图像的宽度以及 crop 图像的高度。图像左上顶点作为坐标原点。如果不使用 crop 功能可填 NULL。

```c++
typedef struct bmcv_padding_atrr_s {
    unsigned int  dst_crop_stx;
    unsigned int  dst_crop_sty;
    unsigned int  dst_crop_w;
    unsigned int  dst_crop_h;
    unsigned char padding_r;
    unsigned char padding_g;
    unsigned char padding_b;
    int           if_memset;
} bmcv_padding_atrr_t;
```

1. 目标小图的左上角顶点相对于 dst image 原点（左上角）的 offset 信息：dst_crop_stx 和 dst_crop_sty；
2. 目标小图经resize后的宽高：dst_crop_w 和 dst_crop_h；
3. dst image 如果是RGB格式，各通道需要 padding 的像素值信息：padding_r、padding_g、padding_b，当 if_memset=1 时有效，如果是 GRAY 图像可以将三个值均设置为同一个值；
4. if_memset 表示要不要在该 api 内部对 dst image 按照各个通道的 padding 值做 memset。如果设置为 0 则用户需要在调用该 api 前，根据需要 padding 的像素值信息，调用 bmlib 中的 api 直接对 device memory 进行 memset 操作，如果用户对 padding 的值不关心，可以设置为 0 忽略该步骤。

```c++
typedef struct {
    short csc_coe00;
    short csc_coe01;
    short csc_coe02;
    unsigned char csc_add0;
    unsigned char csc_sub0;
    short csc_coe10;
    short csc_coe11;
    short csc_coe12;
    unsigned char csc_add1;
    unsigned char csc_sub1;
    short csc_coe20;
    short csc_coe21;
    short csc_coe22;
    unsigned char csc_add2;
    unsigned char csc_sub2;
} csc_matrix_t;
```

自定义 csc_matrix 的系数。其中，矩阵变换关系如下：

$$
\left\{
\begin{array}{c}
dst_0=(coe_{00} * (src_0-sub_0)+coe_{01} * (src_1-sub_1)+coe_{02} * (src_2-sub_2))>>10 + add_0 \\
dst_1=(coe_{10} * (src_0-sub_0)+coe_{11} * (src_1-sub_1)+coe_{12} * (src_2-sub_2))>>10 + add_1 \\
dst_2=(coe_{20} * (src_0-sub_0)+coe_{21} * (src_1-sub_1)+coe_{22} * (src_2-sub_2))>>10 + add_2 \\
\end{array}
\right.
$$

## 返回值

该函数成功调用时, 返回 BM_SUCCESS。

## 格式支持

### 1. 支持的数据类型为：

| num | input data_type | output data_type |
|-----|----------------|------------------|
| 1 | | DATA_TYPE_EXT_FLOAT32 |
| 2 | | DATA_TYPE_EXT_1N_BYTE |
| 3 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4 | | DATA_TYPE_EXT_FP16 |
| 5 | | DATA_TYPE_EXT_BF16 |

### 2. 输入支持色彩格式为：

| num | input image_format |
|-----|-------------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_YUV422P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_NV12 |
| 5 | FORMAT_NV21 |
| 6 | FORMAT_NV16 |
| 7 | FORMAT_NV61 |
| 8 | FORMAT_RGB_PLANAR |
| 9 | FORMAT_BGR_PLANAR |
| 10 | FORMAT_RGB_PACKED |
| 11 | FORMAT_BGR_PACKED |
| 12 | FORMAT_RGBP_SEPARATE |
| 13 | FORMAT_BGRP_SEPARATE |
| 14 | FORMAT_GRAY |
| 15 | FORMAT_COMPRESSED |
| 16 | FORMAT_YUV444_PACKED |
| 17 | FORMAT_YVU444_PACKED |
| 18 | FORMAT_YUV422_YUYV |
| 19 | FORMAT_YUV422_YVYU |
| 20 | FORMAT_YUV422_UYVY |
| 21 | FORMAT_YUV422_VYUY |

### 3. 输出支持色彩格式为：

| num | input image_format |
|-----|-------------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_YUV422P |
| 3 | FORMAT_YUV444P |
| 4 | FORMAT_NV12 |
| 5 | FORMAT_NV21 |
| 6 | FORMAT_NV16 |
| 7 | FORMAT_NV61 |
| 8 | FORMAT_RGB_PLANAR |
| 9 | FORMAT_BGR_PLANAR |
| 10 | FORMAT_RGB_PACKED |
| 11 | FORMAT_BGR_PACKED |
| 12 | FORMAT_RGBP_SEPARATE |
| 13 | FORMAT_BGRP_SEPARATE |
| 14 | FORMAT_GRAY |
| 15 | FORMAT_YUV422_YUYV |
| 16 | FORMAT_YUV422_YVYU |
| 17 | FORMAT_YUV422_UYVY |
| 18 | FORMAT_YUV422_VYUY |
| 19 | FORMAT_HSV_PLANAR |

## 注意

1. 图片实际缩放倍数（（crop.width / output.width) 以及 (crop.height / output.height））限制在 1/128 ～ 128 之间。

2. 输入输出的宽高（src.width, src.height, dst.widht, dst.height）限制在 16 ～ 8192 之间。

3. 输入必须关联 device memory，否则返回失败。

4. 该接口支持 byte align 的数据输入。但当输入为 YUV420P / NV12 / NV21 格式时，使用 stride 32 byte align 的数据作为输入可使转换效率更高。

5. FORMAT_COMPRESSED 是 VPU 解码后内置的一种压缩格式，它包括4个部分：Y compressed table、Y compressed data、CbCr compressed table 以及 CbCr compressed data。请注意 bm_image 中这四部分存储的顺序与 FFMPEG 中 AVFrame 稍有不同，如果需要 attach AVFrame 中 device memory 数据到 bm_image 中时，对应关系如下，关于 AVFrame 详细内容请参考 VPU 的用户手册。

```c
bm_device_mem_t src_plane_device[4];
src_plane_device[0] = bm_mem_from_device((u64)avframe->data[6],
        avframe->linesize[6]);
src_plane_device[1] = bm_mem_from_device((u64)avframe->data[4],
        avframe->linesize[4] * avframe->h);
src_plane_device[2] = bm_mem_from_device((u64)avframe->data[7],
        avframe->linesize[7]);
src_plane_device[3] = bm_mem_from_device((u64)avframe->data[5],
        avframe->linesize[4] * avframe->h / 2);

bm_image_attach(*compressed_image, src_plane_device);
```

# bmcv_image_warp_affine

该接口实现图像的仿射变换，可实现旋转、平移、缩放等操作。仿射变换是一种二维坐标 (x , y) 到二维坐标(x₀ , y₀)的线性变换，该接口的实现是针对输出图像的每一个像素点找到在输入图像中对应的坐标，从而构成一幅新的图像，其数学表达式形式如下：

$$
\left\{
\begin{array}{c}
x_0=a_1x+b_1y+c_1 \\
y_0=a_2x+b_2y+c_2 \\
\end{array}
\right.
$$

对应的齐次坐标矩阵表示形式为：

$$
\left[\begin{matrix} x_0 \\ y_0 \\ 1 \end{matrix} \right]=\left[\begin{matrix} a_1&b_1&c_1 \\ a_2&b_2&c_2 \\ 0&0&1 \end{matrix} \right]\times \left[\begin{matrix} x \\ y \\ 1 \end{matrix} \right]
$$

坐标变换矩阵是一个6点的矩阵，该矩阵是从输出图像坐标推导输入图像坐标的系数矩阵，可以通过输入输出图像上对应的3个点坐标来获取。在人脸检测中，通过获取人脸定位点来获取变换矩阵。

bmcv_affine_matrix定义了一个坐标变换矩阵，其顺序为float m[6] = {a1, b1, c1, a2, b2, c2}。而bmcv_affine_image_matrix定义了一张图片里面有几个变换矩阵，通常来说一张图片有多个人脸时，会对应多个变换矩阵。

```c
typedef struct bmcv_affine_matrix_s{
        float m[6];
} bmcv_warp_matrix;

typedef struct bmcv_affine_image_matrix_s{
        bmcv_affine_matrix *matrix;
        int matrix_num;
} bmcv_affine_image_matrix;
```

## 接口形式一:

```c
bm_status_t bmcv_image_warp_affine(
            bm_handle_t handle,
            int image_num,
            bmcv_affine_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

## 接口形式二:

```c
bm_status_t bmcv_image_warp_affine_similar_to_opencv(
            bm_handle_t handle,
            int image_num,
            bmcv_affine_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

本接口是对齐opencv仿射变换的接口，该矩阵是从输入图像坐标推导输出图像坐标的系数矩阵。

## 参数说明

* **bm_handle_t handle**  
  输入参数。输入的bm_handle句柄。

* **int image_num**  
  输入参数。输入图片数，最多支持4。

* **bmcv_affine_image_matrix matrix[4]**  
  输入参数。每张图片对应的变换矩阵数据结构，最多支持4张图片。

* **bm_image\* input**  
  输入参数。输入bm_image，对于1N模式，最多4个bm_image，对于4N模式，最多一个bm_image。

* **bm_image\* output**  
  输出参数。输出bm_image，外部需要调用bmcv_image_create创建，建议用户调用bmcv_image_attach来分配device memory。如果用户不调用attach，则内部分配device memory。对于输出bm_image，其数据类型和输入一致，即输入是4N模式，则输出也是4N模式,输入1N模式，输出也是1N模式。所需要的bm_image大小是所有图片的变换矩阵之和。比如输入1个4N模式的bm_image，4张图片的变换矩阵数目为【3,0,13,5】，则共有变换矩阵3+0+13+5=21，由于输出是4N模式，则需要(21+4-1)/4=6个bm_image的输出。

* **int use_bilinear**  
  输入参数。是否使用bilinear进行插值，若为0则使用nearest插值，若为1则使用bilinear插值，默认使用nearest插值。选择nearest插值的性能会优于bilinear，因此建议首选nearest插值，除非对精度有要求时可选择使用bilinear插值。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 注意事项

1. 该接口所支持的image_format包括：

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PLANAR |
| 2   | FORMAT_RGB_PLANAR |

2. 该接口所支持的data_type包括：

| num | data_type           |
|-----|---------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |
| 2   | DATA_TYPE_EXT_4N_BYTE |

3. 该接口的输入以及输出bm_image均支持带有stride。

4. 要求该接口输入bm_image的width、height、image_format以及data_type必须保持一致。

5. 要求该接口输出bm_image的width、height、image_format、data_type以及stride必须保持一致。

## 示例代码

```c
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"

static int writeBin(const char* path, void* output_data, int size)
{
    int len = 0;
    FILE* fp_dst = fopen(path, "wb+");

    if (fp_dst == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    len = fwrite((void*)output_data, 1, size, fp_dst);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_dst);
    return 0;
}

static unsigned char* image_read_2(
                    int            image_n,
                    int            image_c,
                    int            image_sh,
                    int            image_sw,
                    int            image_dh,
                    int            image_dw) {

    unsigned char* res          = (unsigned char*) malloc(image_n * image_c * image_sh * image_sw * sizeof(unsigned char));
    unsigned char* res_temp     = (unsigned char*) malloc(image_n * image_c * image_dh * image_dw * sizeof(unsigned char));
    unsigned char* res_temp_bak = (unsigned char*) malloc(image_n * image_c * image_dh * image_dw * sizeof(unsigned char));

    for (int i = 0; i < image_n * image_c * image_sh * image_sw; i++)
    {
        res[i] = i % 255;
    }

    if (image_dh <= image_sh && image_dw <= image_sw)
        return res;

    if (image_dh > image_sh){
        int pad_h_value = (image_dh - image_sh) / 2;
        for (int i = 0;i < pad_h_value * image_sw;i++)
            res_temp[i] = 0;

        for (int i = pad_h_value * image_sw, j = 0; i < pad_h_value * image_sw + image_n * image_c * image_sh * image_sw;i++,j++)
            res_temp[i] = res[j];

        for (int i = pad_h_value * image_sw + image_n * image_c * image_sh * image_sw;i <  pad_h_value * image_sw + image_n * image_c * image_sh * image_sw + pad_h_value * image_sw;i++)
            res_temp[i] = 0;
    }

    if (image_dw > image_sw){
        int pad_w_value = (image_dw - image_sw) / 2;
        int j = 0;
        for (int i = 0;i < image_dh;i++){
            for (;j < pad_w_value + i * image_dw;j++)
                res_temp_bak[j] = 0;
            for (;j < pad_w_value + image_sw + i * image_dw;j++)
                res_temp_bak[j] = res_temp[j - pad_w_value - i * image_dw + i * image_sw];
            for (;j < pad_w_value + pad_w_value + image_sw + i * image_dw;j++)
                res_temp_bak[j] = 0;
        }
    }

    free(res);
    free(res_temp);
    return res_temp_bak;
}

int main() {
    int image_sh = 1080;
    int image_sw = 1920;
    int image_dh = 112;
    int image_dw = 112;
    int is_bilinear = 0;
    bm_handle_t handle;
    int dev_id = 0;
    bm_status_t ret = bm_dev_request(&handle, dev_id);

    int image_c = 3;
    int image_n = 1;
    int output_num = 1;

    unsigned char* src_data = image_read_2(image_n, image_c, image_sh, image_sw, image_dh, image_dw);
    float* trans_mat = (float*)malloc(output_num * 6 * sizeof(float));

    for (int i = 0; i < output_num; i++){
        trans_mat[0 + i * 6] = 3.84843f;
        trans_mat[1 + i * 6] = -0.0248411f;
        trans_mat[2 + i * 6] = 916.203f;
        trans_mat[3 + i * 6] = 0.0248411;
        trans_mat[4 + i * 6] = 3.84843f;
        trans_mat[5 + i * 6] = 55.9748f;
    }

    unsigned char* dst_image_tpu = (unsigned char*)malloc(output_num * image_c * image_dh * image_dw * sizeof(unsigned char));

    bmcv_affine_image_matrix matrix_image[4];
    bmcv_affine_matrix *     matrix = (bmcv_affine_matrix *)(trans_mat);
    for (int i = 0; i < image_n; i++) {
        matrix_image[i].matrix_num = 1;
        matrix_image[i].matrix     = matrix;
        matrix += 1;
    }

    bm_image                 src_img[4];
    bm_image_format_ext      image_format = FORMAT_BGR_PLANAR;
    bm_image_data_format_ext data_type    = DATA_TYPE_EXT_1N_BYTE;

    for (int i = 0; i < image_n; i++){
        bm_image_create(handle, image_sh, image_sw, image_format, data_type, src_img + i, NULL);
        int stride = 0;
        bm_image_get_stride(src_img[i], &stride);
        void *ptr = (void *)(src_data + 3 * stride * image_sh * i);
        bm_image_copy_host_to_device(src_img[i], (void **)(&ptr));
    }

    bm_image* dst_img = (bm_image*)malloc(image_n * sizeof(bm_image));

    for (int i = 0; i < image_n; i++) {
        bm_image_create(handle, image_dh, image_dw, image_format, data_type, dst_img + i, NULL);
    }
    ret = bmcv_image_warp_affine(handle, image_n, matrix_image, src_img, dst_img, is_bilinear);

    int size = 0;
    bm_image_get_byte_size(dst_img[0], &size);
    unsigned char* temp_out = (unsigned char*)malloc(output_num * size * sizeof(unsigned char));
    for (int i = 0; i < image_n; i++) {
        void *ptr = (void *)(temp_out + size * i);
        bm_image_copy_device_to_host(dst_img[i], (void **)&ptr);
    }
    memcpy(dst_image_tpu, temp_out, image_n * image_c * image_dh * image_dw);

    for (int i = 0; i < image_n; i++){
        bm_image_destroy(&src_img[i]);
    }
    char *dst_name = "path/to/dst";
    writeBin(dst_name, temp_out,  size);
    writeBin("path/to/src", src_data, image_sh * image_sw * 3);
    free(src_data);
    free(dst_img);
    free(temp_out);
    free(dst_image_tpu);

    return ret;
}
```

# bmcv_image_warp_affine_padding

**接口说明**

所有的使用方式均和上述的 bmcv_image_warp_affine 相同，仅仅改变了接口名字，具体的 padding zero 的接口名字如下：

**接口形式一:**

```c
bm_status_t bmcv_image_warp_affine_padding(
    bm_handle_t handle,
    int image_num,
    bmcv_affine_image_matrix matrix[4],
    bm_image *input,
    bm_image *output,
    int use_bilinear);
```

**接口形式二:**

```c
bm_status_t bmcv_image_warp_affine_similar_to_opencv_padding(
    bm_handle_t handle,
    int image_num,
    bmcv_affine_image_matrix matrix[4],
    bm_image *input,
    bm_image *output,
    int use_bilinear);
```

**代码示例说明**

同 bmcv_image_warp_affine 接口使用方式相同，只需要将接口名字换成 bmcv_image_warp_affine_padding 或 bmcv_image_warp_affine_similar_to_opencv_padding 即可。

# bmcv_image_warp_perspective

该接口实现图像的透射变换，又称投影变换或透视变换。透射变换将图片投影到一个新的视平面，是一种二维坐标 (x₀ , y₀) 到二维坐标(x , y)的非线性变换，该接口的实现是针对输出图像的每一个像素点坐标得到对应输入图像的坐标，然后构成一幅新的图像，其数学表达式形式如下：

$$
\left\{
\begin{array}{c}
x'=a_1x+b_1y+c_1 \\
y'=a_2x+b_2y+c_2 \\
w'=a_3x+b_3y+c_3 \\
x_0 = x' / w'          \\
y_0 = y' / w'          \\
\end{array}
\right.
$$

对应的齐次坐标矩阵表示形式为：

$$
\left[\begin{matrix} x' \\ y' \\ w' \end{matrix} \right]=\left[\begin{matrix} a_1&b_1&c_1 \\ a_2&b_2&c_2 \\ a_3&b_3&c_3 \end{matrix} \right]\times \left[\begin{matrix} x \\ y \\ 1 \end{matrix} \right]
$$

$$
\left\{
\begin{array}{c}
x_0 = x' / w'   \\
y_0 = y' / w'   \\
\end{array}
\right.
$$

坐标变换矩阵是一个 9 点的矩阵（通常c3 = 1），利用该变换矩阵可以从输出图像坐标推导出对应的输入原图坐标，该变换矩阵可以通过输入输出图像对应的 4 个点的坐标来获取。

为了更方便地完成透射变换，该库提供了两种形式的接口供用户使用：一种是用户提供变换矩阵给接口作为输入; 另一种接口是提供输入图像中 4 个点的坐标作为输入，适用于将一个不规则的四边形透射为一个与输出大小相同的矩形，可以将输入图像A'B'C'D'映射为输出图像ABCD，用户只需要提供输入图像中A'、B'、C'、D'四个点的坐标即可，该接口内部会根据这四个的坐标和输出图像四个顶点的坐标自动计算出变换矩阵，从而完成该功能。

**接口形式一:**

```c
bm_status_t bmcv_image_warp_perspective(
            bm_handle_t handle,
            int image_num,
            bmcv_perspective_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

其中，bmcv_perspective_matrix 定义了一个坐标变换矩阵，其顺序为 float m[9] = {a1, b1, c1, a2, b2, c2, a3, b3, c3}。
而 bmcv_perspective_image_matrix 定义了一张图片里面有几个变换矩阵，可以实现对一张图片里的多个小图进行透射变换。

```c
typedef struct bmcv_perspective_matrix_s{
        float m[9];
} bmcv_perspective_matrix;

typedef struct bmcv_perspective_image_matrix_s{
        bmcv_perspective_matrix *matrix;
        int matrix_num;
} bmcv_perspective_image_matrix;
```

**接口形式二:**

```c
bm_status_t bmcv_image_warp_perspective_with_coordinate(
            bm_handle_t handle,
            int image_num,
            bmcv_perspective_image_coordinate coord[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

其中，bmcv_perspective_coordinate 定义了四边形四个顶点的坐标，按照左上、右上、左下、右下的顺序存储。
而 bmcv_perspective_image_coordinate 定义了一张图片里面有几组四边形的坐标，可以实现对一张图片里的多个小图进行透射变换。

```c
typedef struct bmcv_perspective_coordinate_s{
        int x[4];
        int y[4];
} bmcv_perspective_coordinate;

typedef struct bmcv_perspective_image_coordinate_s{
        bmcv_perspective_coordinate *coordinate;
        int coordinate_num;
} bmcv_perspective_image_coordinate;
```

**接口形式三:**

```c
bm_status_t bmcv_image_warp_perspective_similar_to_opencv(
            bm_handle_t handle,
            int image_num,
            bmcv_perspective_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

本接口中bmcv_perspective_image_matrix 定义的变换矩阵与opencv的warpPerspective接口要求输入的变换矩阵相同，且与接口一中同名结构体定义的矩阵互为逆矩阵，其余参数与接口一相同。

```c
typedef struct bmcv_perspective_matrix_s{
        float m[9];
} bmcv_perspective_matrix;

typedef struct bmcv_perspective_image_matrix_s{
        bmcv_perspective_matrix *matrix;
        int matrix_num;
} bmcv_perspective_image_matrix;
```

**参数说明**

* bm_handle_t handle

  输入参数。输入的 bm_handle 句柄。

* int image_num

  输入参数。输入图片数，最多支持 4。

* bmcv_perspective_image_matrix matrix[4]

  输入参数。每张图片对应的变换矩阵数据结构，最多支持 4 张图片。

* bmcv_perspective_image_coordinate coord[4]

  输入参数。每张图片对应的四边形坐标信息，最多支持 4 张图片。

* bm_image\* input

  输入参数。输入 bm_image，对于 1N 模式，最多 4 个 bm_image，对于 4N 模式，最多一个 bm_image。

* bm_image\* output

  输出参数。输出 bm_image，外部需要调用 bmcv_image_create 创建，建议用户调用 bmcv_image_attach 来分配 device memory。如果用户不调用 attach，则内部分配 device memory。对于输出 bm_image，其数据类型和输入一致，即输入是 4N 模式，则输出也是 4N 模式,输入 1N 模式，输出也是 1N 模式。所需要的 bm_image 大小是所有图片的变换矩阵之和。比如输入 1 个 4N 模式的 bm_image，4 张图片的变换矩阵数目为【3,0,13,5】，则共有变换矩阵 3+0+13+5=21，由于输出是 4N 模式，则需要(21+4-1)/4=6 个 bm_image 的输出。

* int use_bilinear

  输入参数。是否使用 bilinear 进行插值，若为 0 则使用 nearest 插值，若为 1 则使用 bilinear 插值，默认使用 nearest 插值。选择 nearest 插值的性能会优于 bilinear，因此建议首选 nearest 插值，除非对精度有要求时可选择使用 bilinear 插值。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项**

1. 该接口要求输出图像的所有坐标点都能在输入的原图中找到对应的坐标点，不能超出原图大小，建议优先使用接口二，可以自动满足该条件。

2. 该接口所支持的 image_format 包括：

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PLANAR |
| 2   | FORMAT_RGB_PLANAR |

3. 该接口所支持的 data_type 包括：

| num | data_type           |
|-----|---------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |
| 2   | DATA_TYPE_EXT_4N_BYTE |

4. 该接口的输入以及输出 bm_image 均支持带有 stride。

5. 要求该接口输入 bm_image 的 width、height、image_format 以及 data_type 必须保持一致。

6. 要求该接口输出 bm_image 的 width、height、image_format、data_type 以及 stride 必须保持一致。

**示例代码**

```c
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext_c.h"

#define BM_MIN(x, y) (((x)) < ((y)) ? (x) : (y))
#define BM_MAX(x, y) (((x)) > ((y)) ? (x) : (y))

#define NO_USE 0
#define MAX_INT (float)(pow(2, 31) - 2)
#define MIN_INT (float)(1 - pow(2, 31))
#define UNUSED(x) (void)(x)

static int image_sh = 500;
static int image_sw = 500;
static int image_dh = 200;
static int image_dw = 200;
static int use_bilinear = 0;
static bm_handle_t handle;

static int writeBin(const char* path, void* output_data, int size)
{
    int len = 0;
    FILE* fp_dst = fopen(path, "wb+");

    if (fp_dst == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    len = fwrite((void*)output_data, 1, size, fp_dst);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_dst);
    return 0;
}

static void my_get_perspective_transform(int* sx, int* sy, int dw, int dh, float* matrix) {
    int A = sx[3] + sx[0] - sx[1] - sx[2];
    int B = sy[3] + sy[0] - sy[1] - sy[2];
    int C = sx[2] - sx[3];
    int D = sy[2] - sy[3];
    int E = sx[1] - sx[3];
    int F = sy[1] - sy[3];
    matrix[8] = 1;
    matrix[7] = ((float)(A * F - B * E) / (float)dh) / (float)(C * F - D * E);
    matrix[6] = ((float)(A * D - B * C) / (float)dw) / (float)(D * E - C * F);
    matrix[0] = (matrix[6] * dw * sx[1] + sx[1] - sx[0]) / dw;
    matrix[1] = (matrix[7] * dh * sx[2] + sx[2] - sx[0]) / dh;
    matrix[2] = sx[0];
    matrix[3] = (matrix[6] * dw * sy[1] + sy[1] - sy[0]) / dw;
    matrix[4] = (matrix[7] * dh * sy[2] + sy[2] - sy[0]) / dh;
    matrix[5] = sy[0];
}

unsigned char* read_pixel_data(const char* filename, size_t* data_size) {
    FILE* file = fopen(filename, "rb");
    if (!file) {
        fprintf(stderr, "Can not open: %s\n", filename);
        return NULL;
    }
    fseek(file, 0, SEEK_END);
    long file_size = ftell(file);
    fseek(file, 0, SEEK_SET);

    if (file_size <= 0) {
        fprintf(stderr, "invalid file size: %ld\n", file_size);
        fclose(file);
        return NULL;
    }

    unsigned char* res = (unsigned char*)malloc(file_size);
    if (!res) {
        fprintf(stderr, "malloc failed\n");
        fclose(file);
        return NULL;
    }

    size_t bytes_read = fread(res, 1, file_size, file);
    if (bytes_read != (size_t)file_size) {
        fprintf(stderr, "Read file error: %s (expect %ld bytes, actual %zu bytes)\n",
                filename, file_size, bytes_read);
        free(res);
        fclose(file);
        return NULL;
    }

    fclose(file);
    *data_size = (size_t)file_size;
    return res;
}
```

```c
static bm_status_t src_data_generation(int i, int* coordinate, float* trans_mat, float* tensor_S) {
    int border_x1 = rand() % image_sw;
    int border_x2 = rand() % image_sw;
    while (border_x1 == border_x2) border_x2 = rand() % image_sw;
    int border_y1 = rand() % image_sh;
    int border_y2 = rand() % image_sh;
    while (border_y1 == border_y2) border_y2 = rand() % image_sh;
    int x_min = BM_MIN(border_x1, border_x2);
    int x_max = BM_MAX(border_x1, border_x2);
    int y_min = BM_MIN(border_y1, border_y2);
    int y_max = BM_MAX(border_y1, border_y2);

    int x[4], y[4];
    int sx[4], sy[4];
    int idx = rand() % 4;
    x[0] = x_min + rand() % (x_max - x_min);
    y[0] = y_min;
    x[1] = x_max;
    y[1] = y_min + rand() % (y_max - y_min);
    x[2] = x_max - rand() % (x_max - x_min);
    y[2] = y_max;
    x[3] = x_min;
    y[3] = y_max - rand() % (y_max - y_min);
    sx[0] = x[(0 + idx) % 4];
    sy[0] = y[(0 + idx) % 4];
    sx[1] = x[(1 + idx) % 4];
    sy[1] = y[(1 + idx) % 4];
    sx[2] = x[(3 + idx) % 4];
    sy[2] = y[(3 + idx) % 4];
    sx[3] = x[(2 + idx) % 4];
    sy[3] = y[(2 + idx) % 4];
    printf("src coordinate: (%d %d) (%d %d) (%d %d) (%d %d)\n", sx[0], sy[0], sx[1], sy[1], sx[2], sy[2], sx[3], sy[3]);

    coordinate[0 + i * 8] = sx[0];
    coordinate[1 + i * 8] = sx[1];
    coordinate[2 + i * 8] = sx[2];
    coordinate[3 + i * 8] = sx[3];
    coordinate[4 + i * 8] = sy[0];
    coordinate[5 + i * 8] = sy[1];
    coordinate[6 + i * 8] = sy[2];
    coordinate[7 + i * 8] = sy[3];

    float matrix_cv[9];
    my_get_perspective_transform(sx, sy, image_dw-1, image_dh-1, matrix_cv);
    trans_mat[0 + i * 9] = matrix_cv[0];
    trans_mat[1 + i * 9] = matrix_cv[1];
    trans_mat[2 + i * 9] = matrix_cv[2];
    trans_mat[3 + i * 9] = matrix_cv[3];
    trans_mat[4 + i * 9] = matrix_cv[4];
    trans_mat[5 + i * 9] = matrix_cv[5];
    trans_mat[6 + i * 9] = matrix_cv[6];
    trans_mat[7 + i * 9] = matrix_cv[7];
    trans_mat[8 + i * 9] = matrix_cv[8];

    printf("trans_mat[0 + i * 9] = %f\n", trans_mat[0 + i * 9]);
    printf("trans_mat[1 + i * 9] = %f\n", trans_mat[1 + i * 9]);
    printf("trans_mat[2 + i * 9] = %f\n", trans_mat[2 + i * 9]);
    printf("trans_mat[3 + i * 9] = %f\n", trans_mat[3 + i * 9]);
    printf("trans_mat[4 + i * 9] = %f\n", trans_mat[4 + i * 9]);
    printf("trans_mat[5 + i * 9] = %f\n", trans_mat[5 + i * 9]);
    printf("trans_mat[6 + i * 9] = %f\n", trans_mat[6 + i * 9]);
    printf("trans_mat[7 + i * 9] = %f\n", trans_mat[7 + i * 9]);
    printf("trans_mat[8 + i * 9] = %f\n", trans_mat[8 + i * 9]);

    float* tensor_SX = tensor_S;
    float* tensor_SY = tensor_SX + image_dh * image_dw;
    for (int y = 0; y < image_dh; y++) {
        for (int x = 0; x < image_dw; x++) {
            float dx = tensor_SX[y * image_dw + x] * trans_mat[0 + i * 9] +
                tensor_SY[y * image_dw + x] * trans_mat[1 + i * 9] + trans_mat[2 + i * 9];
            float dy = tensor_SX[y * image_dw + x] * trans_mat[3 + i * 9] +
                    tensor_SY[y * image_dw + x] * trans_mat[4 + i * 9] + trans_mat[5 + i * 9];
            float dz = tensor_SX[y * image_dw + x] * trans_mat[6 + i * 9] +
                    tensor_SY[y * image_dw + x] * trans_mat[7 + i * 9] + trans_mat[8 + i * 9];

            dx = dx / dz;
            dy = dy / dz;

            if (dx < MIN_INT || dx > MAX_INT || dy < MIN_INT || dy > MAX_INT || fabs(dz) == 0) {
                printf("--------- the input data is not leagel! --------- \n");
                return BM_ERR_DATA;
            }
        }
    }
    return BM_SUCCESS;
}

int main() {
    int dev_id = 0;
    bm_status_t ret = bm_dev_request(&handle, dev_id);
    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    int matrix_num[4] = {1, 1, 1, 1};
    int image_n = 1;

    int output_num = 0;
    for (int i = 0; i < image_n; i++) {
        output_num += matrix_num[i];
    }

    const char* filename = "/home/linaro/output.bin";
    size_t data_size = 0;
    unsigned char* src_data = read_pixel_data(filename, &data_size);
    if (src_data) {
        printf("Get %zu bytes\n", data_size);
    }
    float* trans_mat = (float*) malloc(output_num * 9 * sizeof(float));
    int* coordinate = (int*) malloc(output_num * 8 * sizeof(int));
    float* tensor_S = (float*) malloc(image_dh *image_dw * 2 * sizeof(float));
    float* tensor_SX = tensor_S;
    float* tensor_SY = tensor_SX + image_dh * image_dw;
    for (int y = 0; y < image_dh; y++) {
        for (int x = 0; x < image_dw; x++) {
            tensor_SX[y * image_dw + x] = (float)x;
            tensor_SY[y * image_dw + x] = (float)y;
        }
    }

    for (int i = 0; i < output_num; i++) {
        ret = src_data_generation(i, coordinate, trans_mat, tensor_S);
        while (BM_ERR_DATA == ret)
            ret = src_data_generation(i, coordinate, trans_mat, tensor_S);
    }

    bmcv_perspective_image_matrix matrix_image[4];
    bmcv_perspective_matrix* matrix = (bmcv_perspective_matrix *)(trans_mat);
    for (int i = 0; i < image_n; i++) {
        matrix_image[i].matrix_num = matrix_num[i];
        matrix_image[i].matrix = matrix;
        matrix += matrix_num[i];
    }

    bm_image src_img[4];
    bm_image_format_ext image_format = FORMAT_BGR_PLANAR;
    bm_image_data_format_ext data_type = DATA_TYPE_EXT_1N_BYTE;
    int in_image_num = image_n;
    int out_image_num = output_num;

    for (int i = 0; i < in_image_num; i++) {
        bm_image_create(
            handle, image_sh, image_sw, image_format, data_type, src_img + i, NULL);
        int stride = 0;
        bm_image_get_stride(src_img[i], &stride);
        void *ptr = (void *)(src_data + 3 * stride * image_sh * i);
        bm_image_copy_host_to_device(src_img[i], (void **)(&ptr));
    }

    bm_image* dst_img = (bm_image*)malloc(out_image_num * sizeof(bm_image));

    for (int i = 0; i < out_image_num; i++) {
        bm_image_create(handle, image_dh, image_dw, image_format, data_type, dst_img + i, NULL);
    }
    printf("No coordinate\n");
    ret = bmcv_image_warp_perspective(handle, image_n, matrix_image, src_img, dst_img, use_bilinear);
    int size = 0;
    bm_image_get_byte_size(dst_img[0], &size);
    unsigned char* temp_out = (unsigned char*)malloc(out_image_num * size * sizeof(unsigned char));

    for (int i = 0; i < out_image_num; i++) {
        void *ptr = (void *)(temp_out + size * i);
        bm_image_copy_device_to_host(dst_img[i], (void **)&ptr);
    }

    char *dst_name = "/home/linaro/output_warp.bin";
    writeBin(dst_name, temp_out, size);

    free(temp_out);
    free(dst_img);
    free(src_data);

    free(trans_mat);
    free(coordinate);
    free(tensor_S);

    bm_dev_free(handle);

    return ret;
}
```

# bmcv_image_watermark_superpose

以下接口用于在图像上叠加一个或多个水印。

## 描述接口一

接口一可实现在不同的输入图的指定位置，叠加不同的水印。

### 语法

```c++
bm_status_t bmcv_image_watermark_superpose(
                  bm_handle_t handle,
                  bm_image * image,
                  bm_device_mem_t * bitmap_mem,
                  int bitmap_num,
                  int bitmap_type,
                  int pitch,
                  bmcv_rect_t * rects,
                  bmcv_color_t color);
```

## 描述接口二

此接口为接口一的简化版本，可在一张图中的不同位置重复叠加一种水印。

### 语法

```c++
bm_status_t bmcv_image_watermark_repeat_superpose(
                  bm_handle_t handle,
                  bm_image image,
                  bm_device_mem_t bitmap_mem,
                  int bitmap_num,
                  int bitmap_type,
                  int pitch,
                  bmcv_rect_t * rects,
                  bmcv_color_t color);
```

## 传入参数说明

* **bm_handle_t handle**  
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* **bm_image\* image**  
  输入参数。需要打水印的 bm_image 对象指针。

* **bm_device_mem_t\* bitmap_mem**  
  输入参数。水印的 bm_device_mem_t 对象指针。

* **int bitmap_num**  
  输入参数。水印数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数、也是 image 指针中所包含的 bm_image 对象个数、也是 bitmap_mem 指针中所包含的 bm_device_mem_t 对象个数。

* **int bitmap_type**  
  输入参数。水印类型, 值 0 表示水印为 8bit 数据类型(有透明度信息), 值 1 表示水印为 1bit 数据类型(无透明度信息)。

* **int pitch**  
  输入参数。水印文件每行的 byte 数, 可理解为水印的宽。

* **bmcv_rect_t\* rects**  
  输入参数。水印位置指针，包含每个水印起始点和宽高。具体内容参考下面的数据类型说明。

* **bmcv_color_t color**  
  输入参数。水印的颜色。具体内容参考下面的数据类型说明。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 数据类型说明

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;

typedef struct {
    unsigned char r;
    unsigned char g;
    unsigned char b;
} bmcv_color_t;
```

* **start_x** 描述了水印在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)
* **start_y** 描述了水印在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)
* **crop_w** 描述的水印的宽度
* **crop_h** 描述的水印的高度
* **r** 颜色的r分量
* **g** 颜色的g分量
* **b** 颜色的b分量

## 注意事项

1. 该API要求如下：

- 底图的数据类型必须为：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

- 底图的色彩格式可支持：

| num | image_format         |
|-----|----------------------|
| 1   | FORMAT_YUV420P       |
| 2   | FORMAT_YUV444P       |
| 3   | FORMAT_NV12          |
| 4   | FORMAT_NV21          |
| 5   | FORMAT_RGB_PLANAR    |
| 6   | FORMAT_BGR_PLANAR    |
| 7   | FORMAT_RGB_PACKED    |
| 8   | FORMAT_BGR_PACKED    |
| 9   | FORMAT_RGBP_SEPARATE |
| 10  | FORMAT_BGRP_SEPARATE |
| 11  | FORMAT_GRAY          |

如果不满足输入输出格式要求，则返回失败。

- 水印图两种格式的数据排列：

**8bit数据格式：**

用每个byte [0-255]存储单个像素的透明度信息，0 代表完全透明，255 代表完全不透明。其数据量为 width * height byte。

```
dst = (alpha * color + (255 - alpha) * src) / 255
```

dst 表示输出图该位置像素点的值，alpha 表示水印图存储的透明度信息，color代表接口中color参数传入的值，src 代表底图该位置像素点的值。

如下代码，A_8bit是一个宽高为8*8的8bit水印，内容为字母A。

```c
unsigned char A_8bit[8][8] = {
  {0,  0,  255, 255,  0,  0, 0, 0},
  {0, 255,  0,   0,  255, 0, 0, 0},
  {0, 255,  0,   0,  255, 0, 0, 0},
  {0, 255, 255, 255, 255, 0, 0, 0},
  {0, 255,  0,   0,  255, 0, 0, 0},
  {0, 255,  0,   0,  255, 0, 0, 0},
  {0,  0,   0,   0,   0,  0, 0, 0},
  {0,  0,   0,   0,   0,  0, 0, 0}};
```

**1bit数据格式：**

用每个bit [0-1]存储单个像素是否在有效区域，0 代表在无效区域，1 代表在有效区域。其数据量为 width * height / 8 byte。

```
dst = (alpha == 1 ? color : src)
```

dst 表示输出图该位置像素点的值，alpha 表示水印图存储的区域信息，color代表接口中color参数传入的值，src 代表底图该位置像素点的值。

将上述A_8bit矩阵用1bit存储，即如下代码。

```c
unsigned char A_1bit[8] = {
  0xc, //(二进制表示 0000 1100)
  0x12,//(二进制表示 0001 0010)
  0x12,//(二进制表示 0001 0010)
  0x1e,//(二进制表示 0001 1110)
  0x12,//(二进制表示 0001 0010)
  0x12,//(二进制表示 0001 0010)
  0x0, //(二进制表示 0000 0000)
  0x0};//(二进制表示 0000 0000)
```

2. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

3. 水印数量最多可设置512个。

4. 如果水印区域超出原图宽高，会返回失败。

5. 不支持对单底图进行位置重叠的多图叠加。

## 示例代码

```c
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmcv_api_ext_c.h"

static int writeBin(const char* path, void* output_data, int size)
{
    int len = 0;
    FILE* fp_dst = fopen(path, "wb+");

    if (fp_dst == NULL) {
        perror("Error opening file\n");
        return -1;
    }

    len = fwrite((void*)output_data, 1, size, fp_dst);
    if (len < size) {
        printf("file size = %d is less than required bytes = %d\n", len, size);
        return -1;
    }

    fclose(fp_dst);
    return 0;
}

bm_status_t open_water(
    bm_handle_t           handle,
    char *                src_name,
    int                   src_size,
    bm_device_mem_t *     dst)
{
    bm_status_t ret = BM_SUCCESS;
    unsigned char * src = (unsigned char *)malloc(sizeof(unsigned char) * src_size);
    ret = bm_malloc_device_byte(handle, dst, src_size);
    if(ret != BM_SUCCESS){
        printf("bm_malloc_device_byte fail %s: %s: %d\n", __FILE__, __func__, __LINE__);
        goto fail;
    }

    FILE * fp_src = fopen(src_name, "rb");
    size_t read_size = fread((void *)src, src_size, 1, fp_src);
    printf("fread %ld byte\n", read_size);
    fclose(fp_src);
#ifdef _FPGA
    ret = bm_memcpy_s2d_fpga(handle, dst[0], (void*)src);
#else
    ret = bm_memcpy_s2d(handle, dst[0], (void*)src);
#endif
    if(ret != BM_SUCCESS){
        printf("bm_memcpy_s2d fail %s: %s: %d\n", __FILE__, __func__, __LINE__);
    }
fail:
    free(src);
    return ret;
}

int main() {
    char *filename_src = "path/to/src";
    char *filename_water = "path/to/water_file";
    char *filename_dst = "path/to/dst";
    int in_width = 1920;
    int in_height = 1080;
    int water_width = 800;
    int water_height = 600;
    bm_image_format_ext src_format = FORMAT_RGB_PLANAR;
    bmcv_rect_t rects = {
        .start_x = 200,
        .start_y = 200,
        .crop_w = 800,
        .crop_h = 600};
    bmcv_color_t color = {
        .r = 0,
        .g = 0,
        .b = 0};

    bm_status_t ret = BM_SUCCESS;

    int src_size = in_width * in_height * 3;
    int water_size = water_width * water_height * 3;
    unsigned char *src_data = (unsigned char *)malloc(src_size);
    unsigned char *water_data = (unsigned char *)malloc(water_size);

    FILE *file;
    file = fopen(filename_water, "rb");
    fread(water_data, sizeof(unsigned char), water_size, file);
    fclose(file);

    file = fopen(filename_src, "rb");
    fread(src_data, sizeof(unsigned char), src_size, file);
    fclose(file);

    bm_handle_t handle = NULL;
    int dev_id = 0;
    bm_image src;
    bm_device_mem_t water;
    ret = bm_dev_request(&handle, dev_id);

    open_water(handle, filename_water, water_size, &water);

    bm_image_create(handle, in_height, in_width, src_format, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);

    int src_image_byte_size[4] = {0};
    bm_image_get_byte_size(src, src_image_byte_size);

    void *src_in_ptr[4] = {(void *)src_data,
                        (void *)((char *)src_data + src_image_byte_size[0]),
                        (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1]),
                        (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1] + src_image_byte_size[2])};

    bm_image_copy_host_to_device(src, (void **)src_in_ptr);
    ret = bmcv_image_watermark_superpose(handle, &src, &water, 1, 0, water_width, &rects, color);
    bm_image_copy_device_to_host(src, (void **)src_in_ptr);

    writeBin(filename_dst, src_data, src_size);

    bm_image_destroy(&src);
    bm_dev_free(handle);

    free(src_data);
    free(water_data);

    return ret;
}
```

# bmcv_istft

接口形式如下：

```c
bm_status_t bmcv_istft(
            bm_handle_t handle,
            float* XRHost, float* XIHost,
            float* YRHost, float* YIHost,
            int batch, int L,
            bool realInput, int pad_mode,
            int n_fft, int win_mode, int hop_len,
            bool normalize);
```

## 参数说明

* `bm_handle_t handle`
  
  输入参数。bm_handle 句柄。

* `float* XRHost`
  
  输入参数。输入信号的实部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* `float* XIHost`
  
  输入参数。输入信号的虚部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* `float* YRHost`
  
  输入参数。输出信号的实部地址，空间大小为 batch * L。

* `float* YIHost`
  
  输入参数。输出信号的虚部地址，空间大小为 batch * L。

* `int batch`
  
  输入参数。batch数量。

* `int L`
  
  输入参数。每个batch的信号长度。L需要是2、3、4或5的幂。

* `bool realInput`
  
  输入参数。输出的信号是否为实数，false 为复数，true 为实数。

* `int pad_mode`
  
  输入参数。信号填充模式，0 为 constant，1 为 reflect。

* `int n_fft`
  
  输入参数。每个 L 信号长度做 FFT 的长度

* `int win_mode`
  
  输入参数。信号加窗模式，0 为 hanning窗，1 为 hamming窗。

* `int hop_len`
  
  输入参数。信号做 FFT 的滑动距离，一般为 n_fft / 4 或者 n_fft / 2。

* `bool normalize`
  
  输入参数。输出结果是否要进行归一化。

## 返回值说明

* `BM_SUCCESS`: 成功
* 其他: 失败

## 注意事项

1. 本接口只处理一维信号的ISTFT变换。

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#define M_PI 3.14159265358979323846

enum Pad_mode {
    CONSTANT = 0,
    REFLECT = 1,
};

enum Win_mode {
    HANN = 0,
    HAMM = 1,
};

typedef struct {
    float real;
    float imag;
} Complex;

int main()
{
    bm_handle_t handle;
    int ret = 0;
    int i;
    int L = 4096;
    bool real_input = true;
    int pad_mode = REFLECT;
    int win_mode = HANN;
    int n_fft = 4096;
    int hop_length = n_fft / 4;
    bool norm = true;

    ret = (int)bm_dev_request(&handle, 0);
    if (ret) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return ret;
    }

    int num_frames = 1 + L / hop_length;
    int row_num = n_fft / 2 + 1;

    float* input_R = (float*)malloc(row_num * num_frames * sizeof(float));
    float* input_I = (float*)malloc(row_num * num_frames * sizeof(float));
    float* YRHost_cpu = (float*)malloc(L * sizeof(float));
    float* YRHost_tpu = (float*)malloc(L * sizeof(float));
    float* YIHost_cpu = (float*)malloc(L * sizeof(float));
    float* YIHost_tpu = (float*)malloc(L * sizeof(float));

    memset(input_R, 0, row_num * num_frames * sizeof(float));
    memset(input_I, 0, row_num * num_frames * sizeof(float));

    for (i = 0; i < row_num * num_frames; i++) {
        input_R[i] = (float)rand() / RAND_MAX;
        input_I[i] = (float)rand() / RAND_MAX;
    }

    ret = bmcv_istft(handle, input_R, input_I, YRHost_tpu, YIHost_tpu, 1, L, real_input,
                    pad_mode, n_fft, win_mode, hop_length, norm);

    free(input_R);
    free(input_I);
    free(YRHost_cpu);
    free(YIHost_cpu);
    free(YRHost_tpu);
    free(YIHost_tpu);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_ldc_gdc

## 描述
镜头畸变校正(LDC)模块的几何畸变校正功能，通过校正镜头引起的图像畸变（针对桶形畸变 (Barrel Distortion) 及枕形畸变 (Pincushion Distortion) ），使图像中的直线变得更加准确和几何正确，提高图像的质量和可视化效果。
其中，提供两种畸变校正的方式供用户选择，分别为：1. 用户根据图像畸变的类型及校正强度输入配置参数列表对图像进行校正；2. 用户使用 Grid_Info(输入输出图像坐标映射关系描述)文件校正图像，以获得更好的图像校正效果。

## 语法

```cpp
bm_status_t bmcv_ldc_gdc(bm_handle_t          handle,
                         bm_image             in_image,
                         bm_image             out_image,
                         bmcv_gdc_attr        ldc_attr);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| in_image | 输入 | 输入的畸变图像，通过调用 bm_image_create 创建 |
| out_image | 输出 | 输出的畸变校正后的图像，通过调用 bm_image_create 创建 |
| ldc_attr | 输入 | GDC功能的参数配置列表，包括bAspect XRatio YRatio XYRatio CenterXOffset CenterYOffset DistortionRatio \*grid_info |

## 返回值
该函数成功调用时, 返回 BM_SUCCESS。

## 数据类型说明

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| bAspect | 输入 | 畸变校正的过程中是否保持幅型比，0：不保持，1：保持 |
| s32XRatio | 输入 | 配置范围:[0, 100]，水平方向视野大小参数，bAspect=0 时有效 |
| s32YRatio | 输入 | 配置范围:[0, 100]，垂直方向视野大小参数，bAspect=0 时有效 |
| s32XYRatio | 输入 | 配置范围:[0, 100]，视野大小参数，bAspect=1 时有效 |
| s32CenterXOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的水平偏移 |
| s32CenterYOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的垂直偏移 |
| s32DistortionRatio | 输入 | 配置范围:[-300, 500]，畸变校正强度参数，畸变类型为桶形时配置为负，畸变类型为枕形时配置为负 |
| grid_info | 输入 | 用于存储 grid_info 的信息，包含 grid_info 的大小和数据 |

## 格式支持

1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_NV12 |
| 2 | FORMAT_NV21 |
| 3 | FORMAT_GRAY |

## 注意

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

2. 支持图像的分辨率为64x64~4608x4608，且要求64位对齐。

3. 若用户决定使用第一种方式进行图像校正，需根据图像畸变的类型及校正强度自行输入配置参数列表 ldc_attr，此时要将 grid_info 设置为空。

4. 若用户决定使用第二种方式进行图像校正，需提供 Grid_Info 文件，具体使用方式请参考下面的代码示例。

## 代码示例

1. 通过配置参数列表进行图像校正

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define LDC_ALIGN 64
#define ALIGN(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main() {
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext src_fmt = FORMAT_GRAY, dst_fmt = FORMAT_GRAY;
    bmcv_gdc_attr stLDCAttr = {0};
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }
    bm_image src, dst;
    int src_stride[4];
    int dst_stride[4];
    // align
    int align_height = (height + (LDC_ALIGN - 1)) & ~(LDC_ALIGN - 1);
    int align_width  = (width  + (LDC_ALIGN - 1)) & ~(LDC_ALIGN - 1);

    // calc image stride
    int data_size = 1;
    src_stride[0] = ALIGN(width, 16) * data_size;
    dst_stride[0] = ALIGN(align_width, 16) * data_size;
    // create bm image
    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, src_stride);
    bm_image_create(handle, align_height, align_width, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, dst_stride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
        printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);

    ret = bmcv_ldc_gdc(handle, src, dst, stLDCAttr);

    bm_image_get_byte_size(src, image_byte_size);
    byte_size = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char* output_ptr = (unsigned char*)malloc(byte_size);
    void* out_ptr[4] = {(void*)output_ptr,
                        (void*)((unsigned char*)output_ptr + image_byte_size[0]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1]),
                        (void*)((unsigned char*)output_ptr + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_device_to_host(src, (void **)out_ptr);

    FILE *fp_dst = fopen(dst_name, "wb");
    if (fwrite((void *)input_data, 1, byte_size, fp_dst) < (unsigned int)byte_size){
        printf("file size is less than %d required bytes\n", byte_size);
    };
    fclose(fp_dst);

    free(input_data);
    free(output_ptr);


    bm_image_destroy(&src);
    bm_image_destroy(&dst);

    bm_dev_free(handle);

    return 0;
}
```

# bmcv_ldc_gen_mesh

## 描述
镜头畸变校正(LDC)模块的几何畸变校正功能，通过校正镜头引起的图像畸变（针对桶形畸变 (Barrel Distortion) 及枕形畸变 (Pincushion Distortion) ），使图像中的直线变得更加准确和几何正确，提高图像的质量和可视化效果。
在这个过程中，需要通过CPU计算 MESH 表用于后续的畸变校正，因此可以通过该函数计算并保存 MESH 表用于后续的畸变校正。

## 语法

```cpp
bm_status_t bmcv_ldc_gdc_gen_mesh(bm_handle_t          handle,
                                bm_image             in_image,
                                bm_image             out_image,
                                bmcv_gdc_attr        ldc_attr,
                                bm_device_mem_t      dmem);
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| in_image | 输入 | 输入的畸变图像，通过调用 bm_image_create 创建 |
| out_image | 输出 | 输出的畸变校正后的图像，通过调用 bm_image_create 创建 |
| ldc_attr | 输入 | GDC功能的参数配置列表，包括bAspect XRatio YRatio XYRatio CenterXOffset CenterYOffset DistortionRatio |
| dmem | 输入 | 用于存储 MESH 表的设备内存，通过调用 bm_malloc_device_byte 创建 |

## 返回值
该函数成功调用时, 返回 BM_SUCCESS。

## 数据类型说明

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| bAspect | 输入 | 畸变校正的过程中是否保持幅型比，0：不保持，1：保持 |
| s32XRatio | 输入 | 配置范围:[0, 100]，水平方向视野大小参数，bAspect=0 时有效 |
| s32YRatio | 输入 | 配置范围:[0, 100]，垂直方向视野大小参数，bAspect=0 时有效 |
| s32XYRatio | 输入 | 配置范围:[0, 100]，视野大小参数，bAspect=1 时有效 |
| s32CenterXOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的水平偏移 |
| s32CenterYOffset | 输入 | 配置范围:[-511, 511]，畸变中心点相对于图像中心点的垂直偏移 |
| s32DistortionRatio | 输入 | 配置范围:[-300, 500]，畸变校正强度参数，畸变类型为桶形时配置为负，畸变类型为枕形时配置为负 |
| grid_info | 输入 | 用于存储 grid_info 的信息，包含 grid_info 的大小和数据 |

## 格式支持

1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_NV12 |
| 2 | FORMAT_NV21 |
| 3 | FORMAT_GRAY |

## 注意

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

## bmcv_ldc_rot

**【描述】**
镜头畸变校正(LDC)模块的旋转功能，通过围绕固定点旋转图像，改变其方向与角度，从而使其在平面上发生旋转。

**【语法】**

```cpp
bm_status_t bmcv_ldc_rot(bm_handle_t          handle,
                         bm_image             in_image,
                         bm_image             out_image,
                         bmcv_rot_mode        rot_mode);
```

**【参数】**

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取 |
| in_image | 输入 | 输入的待旋转图像，通过调用 bm_image_create 创建 |
| out_image | 输出 | 输出的旋转后图像，通过调用 bm_image_create 创建 |
| rot_mode | 输入 | 旋转类型，取值为[0, 4]内的整数，其中0为0°，1为90°，2为180°，3为270°，4为xy flip |

**【返回值】**
该函数成功调用时，返回 BM_SUCCESS。

**【数据类型说明】**

```cpp
typedef enum bmcv_rot_mode_ {
    BMCV_ROTATION_0 = 0,
    BMCV_ROTATION_90,
    BMCV_ROTATION_180,
    BMCV_ROTATION_270,
    BMCV_ROTATION_XY_FLIP,
    BMCV_ROTATION_MAX
} bmcv_rot_mode;
```

* BMCV_ROTATION_0 代表0度的旋转，即图像不进行旋转，保持原状。
* BMCV_ROTATION_90 代表90度的旋转，即图像顺时针旋转90度。
* BMCV_ROTATION_180 代表180度的旋转，即图像顺时针旋转180度。
* BMCV_ROTATION_270 代表270度的旋转，即图像顺时针旋转270度。
* BMCV_ROTATION_XY_FLIP 代表XY翻转，即图像在X轴和Y轴上都进行翻转（镜像翻转）。
* BMCV_ROTATION_MAX 代表枚举最大值，用于指示枚举的结束或作为范围检查的标记。

**【格式支持】**

1. 输入和输出的数据类型：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

2. 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|-------------|
| 1 | FORMAT_NV12 |
| 2 | FORMAT_NV21 |
| 3 | FORMAT_GRAY |

**【注意】**

1. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
2. 支持图像的分辨率为64x64~4608x4608，且要求64位对齐。
3. 当前ldc模块固件原生支持90°与270°旋转，所以rot_mode选择0，1，3。

**【代码示例】**

```cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

#define LDC_ALIGN 64
#define align_up(num, align) (((num) + ((align) - 1)) & ~((align) - 1))

int main() {
    int dev_id = 0;
    int height = 1080, width = 1920;
    bm_image_format_ext src_fmt = FORMAT_GRAY, dst_fmt = FORMAT_GRAY;
    bmcv_rot_mode rot_mode = BMCV_ROTATION_0;
    char *src_name = "path/to/src", *dst_name = "path/to/dst";
    bm_handle_t handle = NULL;
    int ret = (int)bm_dev_request(&handle, dev_id);
    if (ret != 0) {
        printf("Create bm handle failed. ret = %d\n", ret);
        exit(-1);
    }

    bm_image src, dst;
    int src_stride[4];
    int dst_stride[4];

    // align
    int align_width  = (width  + (LDC_ALIGN - 1)) & ~(LDC_ALIGN - 1);

    int data_size = 1;
    src_stride[0] = align_up(width, 16) * data_size;
    dst_stride[0] = align_up(align_width, 16) * data_size;
    // create bm image
    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, src_stride);
    bm_image_create(handle, height, width, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, dst_stride);

    ret = bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int image_byte_size[4] = {0};
    bm_image_get_byte_size(src, image_byte_size);
    int byte_size  = image_byte_size[0] + image_byte_size[1] + image_byte_size[2] + image_byte_size[3];
    unsigned char *input_data = (unsigned char *)malloc(byte_size);
    FILE *fp_src = fopen(src_name, "rb");
    if (fread((void *)input_data, 1, byte_size, fp_src) < (unsigned int)byte_size) {
        printf("file size is less than required bytes%d\n", byte_size);
    };
    fclose(fp_src);
    void* in_ptr[4] = {(void *)input_data,
                        (void *)((unsigned char*)input_data + image_byte_size[0]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1]),
                        (void *)((unsigned char*)input_data + image_byte_size[0] + image_byte_size[1] + image_byte_size[2])};
    bm_image_copy_host_to_device(src, in_ptr);
```

# bmcv_matmul

该接口可以实现 8-bit 数据类型矩阵的乘法计算，如下公式：

$$ C = (A\times B) >> rshift\_bit $$

或者

$$ C = alpha \times (A\times B) + beta $$

其中，

* A 是输入的左矩阵，其数据类型可以是 unsigned char 或者 signed char 类型的 8-bit 数据，大小为（M，K）;
* B 是输入的右矩阵，其数据类型可以是 unsigned char 或者 signed char 类型的 8-bit 数据，大小为（K，N）;
* C 是输出的结果矩阵， 其数据类型长度可以是 int8、int16 或者 float32，用户配置决定。
    * 当 C 是 int8 或者 int16 时，执行上述公式 $$ C = (A\times B) >> rshift\_bit $$ 的功能， 而其符号取决于A和B，当A和B均为无符号时C才为无符号数，否则为有符号;
    * 当 C 是 float32 时，执行上述公式 $$ C = alpha \times (A\times B) + beta $$ 的功能。
* rshift_bit 是矩阵乘积的右移数，当 C 是 int8 或者 int16 时才有效，由于矩阵的乘积有可能会超出 8-bit 或者 16-bit 的范围，所以用户可以配置一定的右移数，通过舍弃部分精度来防止溢出。
* alpha 和 beta 是 float32 的常系数，当 C 是 float32 时才有效。

**接口形式:**

```c
bm_status_t bmcv_matmul(
            bm_handle_t handle,
            int M,
            int N,
            int K,
            bm_device_mem_t A,
            bm_device_mem_t B,
            bm_device_mem_t C,
            int A_sign,
            int B_sign,
            int rshift_bit,
            int result_type,
            bool is_B_trans,
            float alpha = 1,
            float beta = 0);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* int M
  输入参数。矩阵 A 和矩阵 C 的行数

* int N
  输入参数。矩阵 B 和矩阵 C 的列数

* int K
  输入参数。矩阵 A 的列数和矩阵 B 的行数

* bm_device_mem_t A
  输入参数。根据左矩阵 A 数据存放位置保存其 device 地址或者 host 地址。如果数据存放于 host 空间则内部会自动完成 s2d 的搬运

* bm_device_mem_t B
  输入参数。根据右矩阵 B 数据存放位置保存其 device 地址或者 host 地址。如果数据存放于 host 空间则内部会自动完成 s2d 的搬运。

* bm_device_mem_t C
  输出参数。根据矩阵 C 数据存放位置保存其 device 地址或者 host 地址。如果是 host 地址，则当beta不为0时，计算前内部会自动完成 s2d 的搬运，计算后再自动完成 d2s 的搬运。

* int A_sign
  输入参数。左矩阵A的符号，1 表示有符号，0 表示无符号。

* int B_sign
  输入参数。右矩阵B的符号，1 表示有符号，0 表示无符号。

* int rshift_bit
  输入参数。矩阵乘积的右移数，为非负数。只有当 result_type 等于 0 或者 1 时才有效。

* int result_type
  输入参数。输出的结果矩阵数据类型，0 表示是 int8，1 表示int16, 2 表示 float32。

* bool is_B_trans
  输入参数。输入右矩阵B是否需要计算前做转置。

* float alpha
  常系数，输入矩阵 A 和 B 相乘之后再乘上该系数，只有当 result_type 等于 2 时才有效，默认值为 1。

* float beta
  常系数，在输出结果矩阵 C 之前，加上该偏移量，只有当 result_type 等于 2 时才有效，默认值为 0。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**示例代码**

```c
#include "bmcv_api_ext_c.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "test_misc.h"

static void assign_fix8b_matrix(void* mat, int size, int is_16bit)
{
    int i;

    for (i = 0; i < size; i++) {
        if (is_16bit) {
            *((signed short*)mat + i) = rand() % 65536 - 32768;
        } else {
            *((signed char*)mat + i) = rand() % 256 - 128;
        }
    }
}

int main()
{
    int M = 1 + rand() % 6;
    int K = 1 + rand() % 512;
    int N = 1 + rand() % 9216;
    // int trans_A = 0;  //whether to transpose
    int trans_B = 0;
    int A_sign = 0;  //unsigned or singned
    int B_sign = 0;
    int result_type = 0;  //0-int8 1-int16 2-flaot
    int right_shift_bit = 1;
    float alpha = 1;
    float beta = 0;
    int ret = 0;
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);

    signed char* input_A;
    signed char* input_B;
    void* tpu_out;
    input_A = (signed char*)malloc(M * K * sizeof(signed char));
    input_B = (signed char*)malloc(K * N * sizeof(signed char));

    if (result_type == 0) {
        tpu_out = (signed char*)malloc(M * N * sizeof(signed char));
        memset(tpu_out, 0, M * N * sizeof(signed char));
    }

    assign_fix8b_matrix((void*)input_A, M * K, 0);
    assign_fix8b_matrix((void*)input_B, K * N, 0);

    ret = bmcv_matmul(handle, M, N, K, bm_mem_from_system((void*)input_A),
                    bm_mem_from_system((void*)input_B), bm_mem_from_system(tpu_out), A_sign,
                    B_sign, right_shift_bit, result_type, trans_B, alpha, beta);

    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        bm_dev_free(handle);
        return -1;
    }

    free(input_A);
    free(input_B);
    free(tpu_out);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_min_max

对于存储于device memory中连续空间的一组数据，该接口可以获取这组数据中的最大值和最小值。

**接口形式:**

```c
bm_status_t bmcv_min_max(
            bm_handle_t handle,
            bm_device_mem_t input,
            float* minVal,
            float* maxVal,
            int len);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_device_mem_t input
  输入参数。输入数据的 device 地址。

* float\* minVal
  输出参数。运算后得到的最小值结果, 如果为 NULL 则不计算最小值。

* float\* maxVal
  输出参数。运算后得到的最大值结果，如果为 NULL 则不计算最大值。

* int len
  输入参数。输入数据的长度。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项：**

1. 该接口可通过设置环境变量启用双核计算，运行程序前：export TPU_CORES=2或export TPU_CORES=both即可。

**示例代码**

```c
#include "bmcv_api_ext_c.h"
#include "stdio.h"
#include "stdlib.h"

int main() {
    int L = 50 + rand() % 260095;
    int ret = 0;
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);

    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return -1;
    }

    float min_tpu = 0, max_tpu = 0;
    float* XHost = (float*)malloc(L * sizeof(float));
    int i;

    for (i = 0; i < L; ++i)
        XHost[i] = (float)((rand() % 2 ? 1 : -1) * (rand() % 1000 + (rand() % 100000) * 0.01));

    bm_device_mem_t XDev;

    ret = bm_malloc_device_byte(handle, &XDev, L * sizeof(float));
    ret = bm_memcpy_s2d(handle, XDev, XHost);
    ret = bmcv_min_max(handle, XDev, &min_tpu, &max_tpu, L);
    if (ret != BM_SUCCESS) {
        printf("Calculate bm min_max failed. ret = %d\n", ret);
        return -1;
    }

    bm_free_device(handle, XDev);

    free(XHost);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_nms

该接口用于消除网络计算得到过多的物体框，并找到最佳物体框。

**接口形式:**

```c
bm_status_t bmcv_nms(bm_handle_t handle,
            bm_device_mem_t input_proposal_addr,
            int proposal_size,
            float nms_threshold,
            bm_device_mem_t output_proposal_addr);
```

**参数说明:**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input_proposal_addr
  输入参数。输入物体框数据所在地址，输入物体框数据结构为 face_rect_t，详见下面数据结构说明。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int proposal_size
  输入参数。物体框个数。

* float nms_threshold
  输入参数。过滤物体框的阈值，分数小于该阈值的物体框将会被过滤掉。

* bm_device_mem_t output_proposal_addr
  输出参数。输出物体框数据所在地址，输出物体框数据结构为 nms_proposal_t，详见下面数据结构说明。需要调用 bm_mem_from_system() 将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明:**

face_rect_t 描述了一个物体框坐标位置以及对应的分数。

```c
struct face_rect_t {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
};
```

* x1 描述了物体框左边缘的横坐标
* y1 描述了物体框上边缘的纵坐标
* x2 描述了物体框右边缘的横坐标
* y2 描述了物体框下边缘的纵坐标
* score 描述了物体框对应的分数

nms_proposal_t 描述了输出物体框的信息。

```c
struct nms_proposal_t {
    struct face_rect_t face_rect[MAX_PROPOSAL_NUM];
    int size;
    int capacity;
    struct face_rect_t* begin;
    struct face_rect_t* end;
};
```

* face_rect 描述了经过过滤后的物体框信息
* size 描述了过滤后得到的物体框个数
* capacity 描述了过滤后物体框最大个数
* begin 暂不使用
* end 暂不使用

**示例代码:**

```c
#include "bmcv_api_ext_c.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include "test_misc.h"

#define SCORE_RAND_LEN_MAX 50000

int main()
{
    int num = rand() % SCORE_RAND_LEN_MAX + 1;
    int i;
    int ret = 0;
    float nms_threshold = 0.7;
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);

    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return -1;
    }

    face_rect_t* input = (face_rect_t*)malloc(num * sizeof(face_rect_t));
    nms_proposal_t tpu_out[1];

    for (i = 0; i < num; ++i) {
        input[i].x1 = ((float)(rand() % 100)) / 10;
        input[i].x2 = input[i].x1 + ((float)(rand() % 100)) / 10;
        input[i].y1 = ((float)(rand() % 100)) / 10;
        input[i].y2 = input[i].y1 + ((float)(rand() % 100)) / 10;
        input[i].score = (float)rand() / (float)RAND_MAX;
    }

    ret = bmcv_nms(handle, bm_mem_from_system(input), num, nms_threshold, bm_mem_from_system(tpu_out));
    if (ret != BM_SUCCESS) {
        printf("Calculate bm_nms failed.\n");
        bm_dev_free(handle);
        return -1;
    }

    free(input);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_sort

该接口可以实现浮点数据的排序（升序/降序），并且支持排序后可以得到原数据所对应的索引值。

## 接口形式

```c
bm_status_t bmcv_sort(
            bm_handle_t handle,
            bm_device_mem_t src_index_addr,
            bm_device_mem_t src_data_addr,
            bm_device_mem_t dst_index_addr,
            bm_device_mem_t dst_data_addr,
            int data_cnt,
            int sort_cnt,
            int order,
            bool index_enable,
            bool auto_index);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle_t handle 设备环境句柄，通过调用bm_dev_request获取。

* **bm_device_mem_t src_index_addr**  
  输入参数。每个输入数据所对应index的地址。如果使能index_enable并且不使用auto_index时，则该参数有效。bm_device_mem_t为内置表示地址的数据类型，可以使用函数bm_mem_from_system(addr)将用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t src_data_addr**  
  输入参数。待排序的输入数据所对应的地址。bm_device_mem_t为内置表示地址的数据类型，可以使用函数bm_mem_from_system(addr)将用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t dst_index_addr**  
  输出参数。排序后输出数据所对应index的地址，如果使能index_enable并且不使用auto_index 时，则该参数有效。bm_device_mem_t为内置表示地址的数据类型，可以使用函数bm_mem_from_system(addr)将用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t dst_data_addr**  
  输出参数。排序后的输出数据所对应的地址。bm_device_mem_t为内置表示地址的数据类型，可以使用函数bm_mem_from_system(addr)将用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **int data_cnt**  
  输入参数。待排序的输入数据的数量。

* **int sort_cnt**  
  输入参数。需要排序的数量，也就是输出结果的个数，包括排好序的数据和对应index。比如降序排列，如果只需要输出最大的前三个数据，该参数设置为3即可。

* **int order**  
  输入参数。升序还是降序，0表示升序，1表示降序。

* **bool index_enable**  
  输入参数。是否使能index。如果使能即可输出排序后数据所对应的index，否则src_index_addr和dst_index_addr这两个参数无效。

* **bool auto_index**  
  输入参数。是否使能自动生成index功能。使用该功能的前提是index_enable参数为true，如果该参数也为true则表示按照输入数据的存储顺序从0开始计数作为index，参数src_index_addr便无效，输出结果中排好序数据所对应的index即存放于dst_index_addr地址中。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 注意事项

1. 要求输入参数满足：0 < sort_cnt <= data_cnt。
2. 若需要使用auto index功能，前提是参数 index_enable 为 true。
3. 该接口可通过设置环境变量启用双核计算，运行程序前：export TPU_CORES=2或export TPU_CORES=both即可。
4. 由于TPU排序类计算的底层机制限制，该接口在输入参数sort_cnt>128时，输出数据地址和输出索引地址空间需要申请为data_num * sizeof(data_type)而不是sort_num * sizeof(data_type),否则接口输出将会出错。

## 示例代码

```c
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include "bmcv_api_ext_c.h"

#define MAX_SORT_NUM (500000)

typedef float bm_sort_data_type_t;
typedef enum { ASCEND_ORDER, DESCEND_ORDER } cdma_sort_order_e;

typedef struct {
    int   index;
    float val;
} __attribute__((packed)) sort_t;

int32_t main() {
    int dev_id = 0;
    int data_num = 1 + rand() % 500000;
    int sort_num = 1 + rand() % data_num;
    int ret = 0;
    bm_handle_t handle;
    cdma_sort_order_e order1 = DESCEND_ORDER;
    // cdma_sort_order_e order2 = ASCEND_ORDER;
    ret = bm_dev_request(&handle, dev_id);

    bm_sort_data_type_t *src_data = (bm_sort_data_type_t*)malloc(data_num * sizeof(float));
    int *src_index_p = (int*)malloc(data_num * sizeof(int));
    sort_t *ref_res = (sort_t*)malloc(data_num * sizeof(sort_t));
    sort_t *cdma_res = (sort_t*)malloc(sort_num * sizeof(sort_t));
    bm_sort_data_type_t *dst_data = (bm_sort_data_type_t*)malloc(sort_num * sizeof(bm_sort_data_type_t));
    int *dst_data_index = (int*)malloc(sort_num * sizeof(int));
    bool index_enable = rand() % 2 ? true : false;
    bool auto_index = rand() % 2 ? true : false;
    printf("data num: %d, sort num: %d\n", data_num, sort_num);

    // produce src data and index
    for (int32_t i = 0; i < data_num; i++) {
        if(auto_index){
          src_index_p[i] = i;
        }else{
          src_index_p[i] = rand() % MAX_SORT_NUM;
        }
        ref_res[i].index = src_index_p[i];
        ref_res[i].val = ((float)(rand() % MAX_SORT_NUM)) / 100;
        src_data[i] = ref_res[i].val;
    }

    int                 *dst_index_p = NULL;
    bm_sort_data_type_t *dst_data_p  = NULL;
    dst_index_p = (int*)malloc(sort_num * sizeof(int));
    dst_data_p = (bm_sort_data_type_t*)malloc(sort_num * sizeof(int));

    bmcv_sort(handle, bm_mem_from_system(src_index_p), bm_mem_from_system(src_data), data_num,
              bm_mem_from_system(dst_index_p), bm_mem_from_system(dst_data_p), sort_num, (int)order1,
              index_enable, auto_index);

    for (int i = 0; i < sort_num; i++) {
        cdma_res[i].index = dst_index_p[i];
        cdma_res[i].val   = dst_data_p[i];
    }
    free(dst_index_p);
    free(dst_data_p);

    // release memory
    free(src_data);
    free(src_index_p);
    free(ref_res);
    free(cdma_res);
    free(dst_data);
    free(dst_data_index);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_stft

## 接口形式

```c
bm_status_t bmcv_stft(
            bm_handle_t handle,
            float* XRHost, float* XIHost,
            float* YRHost, float* YIHost,
            int batch, int L,
            bool realInput, int pad_mode,
            int n_fft, int win_mode, int hop_len,
            bool normalize);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **float\* XRHost**  
  输入参数。输入信号的实部地址，空间大小为 batch * L。

* **float\* XIHost**  
  输入参数。输入信号的虚部地址，空间大小为 batch * L。

* **float\* YRHost**  
  输入参数。输出信号的实部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* **float\* YIHost**  
  输入参数。输出信号的虚部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* **int batch**  
  输入参数。batch数量。

* **int L**  
  输入参数。每个batch的信号长度。L需要是2、3、4或5的幂。

* **bool realInput**  
  输入参数。输入是否为实数， false 为复数， true 为实数。

* **int pad_mode**  
  输入参数。信号填充模式, 0 为 constant, 1 为 reflect。

* **int n_fft**  
  输入参数。每个 L 信号长度做 FFT 的长度

* **int win_mode**  
  输入参数。信号加窗模式, 0 为 hanning窗, 1 为 hamming窗。

* **int hop_len**  
  输入参数。信号做 FFT 的滑动距离，一般为 n_fft / 4 或者 n_fft / 2。

* **bool normalize**  
  输入参数。输出结果是否要进行归一化。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 注意事项

1. 本接口只处理一维信号的STFT变换。

## 示例代码

```c
#include "bmcv_api_ext_c.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

enum Pad_mode {
    CONSTANT = 0,
    REFLECT = 1,
};

enum Win_mode {
    HANN = 0,
    HAMM = 1,
};

static void readBin_4b(const char* path, float* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 4, size, fp_src) < (unsigned int)size){
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

int main()
{
    bm_handle_t handle;
    int ret = 0;
    int i;
    int L = 4096;
    int batch = 1;
    bool realInput = true;
    int pad_mode = REFLECT;
    int win_mode = HANN;
    int n_fft = 4096;
    int hop_length = 1024;
    bool norm = true;
    char* src_name = NULL;

    ret = (int)bm_dev_request(&handle, 0);
    if (ret) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return ret;
    }

    float* XRHost = (float*)malloc(L * batch * sizeof(float));
    float* XIHost = (float*)malloc(L * batch * sizeof(float));
    int num_frames = 1 + L / hop_length;
    int row_num = n_fft / 2 + 1;
    float* YRHost_tpu = (float*)malloc(batch * row_num * num_frames * sizeof(float));
    float* YIHost_tpu = (float*)malloc(batch * row_num * num_frames * sizeof(float));

    memset(XRHost, 0, L * batch * sizeof(float));
    memset(XIHost, 0, L * batch * sizeof(float));

    if (src_name != NULL) {
        readBin_4b(src_name, XRHost, L * batch);
    } else {
        for (i = 0; i < L * batch; i++) {
            XRHost[i] = (float)rand() / RAND_MAX;;
            XIHost[i] = realInput ? 0 : ((float)rand() / RAND_MAX);
        }
    }
    ret = bmcv_stft(handle, XRHost, XIHost, YRHost_tpu, YIHost_tpu, batch, L,
                    realInput, pad_mode, n_fft, win_mode, hop_length, norm);

    free(XRHost);
    free(XIHost);
    free(YRHost_tpu);
    free(YIHost_tpu);

    bm_dev_free(handle);
    return ret;
}
```

# bmcv_tde_draw

## 描述

利用 TDE 硬件在 bm_image 的指定位置填充不规则图形。输入各顶点坐标，按顺序连接顶点，最后一个顶点则连接首顶点，填充围成的所有封闭部分。

## 语法

```c++
bm_status_t bmcv_tde_draw(
  bm_handle_t      handle,
  bm_image         image,
  bmcv_point_t    *point,
  int              path_num,
  bmcv_color_ext   color)
```

## 参数

| **参数名称** | **输入/输出** | **描述** |
|-------------|--------------|----------|
| handle | 输入 | 设备环境句柄，通过调用 bm_dev_request 获取。 |
| image | 输入 | 待处理图像的 bm_image。 |
| point | 输入 | 多边形顶点坐标指针。 |
| path_num | 输入 | 多边形顶点数。 |
| color | 输入 | 填充图形颜色，包含 A/R/G/B 四个值。可调节 A 来改变填充封闭图形的透明度。 |

## 结构体

```c++
typedef struct {
    unsigned char r;
    unsigned char g;
    unsigned char b;
    unsigned char a;
} bmcv_color_ext;
```

## 格式支持

| num | input image_format |
|-----|-------------------|
| 1 | FORMAT_RGB_PACKED |
| 2 | FORMAT_BGR_PACKED |
| 3 | FORMAT_ARGB_PACKED |
| 4 | FORMAT_ABGR_PACKED |
| 5 | FORMAT_ARGB1555_PACKED |
| 6 | FORMAT_ABGR1555_PACKED |
| 7 | FORMAT_ARGB4444_PACKED |
| 8 | FORMAT_ABGR4444_PACKED |

## 返回值

该函数成功调用时，返回 BM_SUCCESS。

## 代码示例

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include "bmcv_api_ext_c.h"

int main() {
  bm_handle_t handle;
  bm_image image;
  bmcv_color_ext color = {.a = 255, .r = 255, .g = 0, .b = 0};
  bmcv_point_t point[5] =
    {{.x = 100, .y = 70},
      {.x = 128, .y = 90},
      {.x = 117, .y = 124},
      {.x = 82, .y = 124},
      {.x = 71, .y = 90}}; //五边形
  int h = 1080, w = 1920;
  bm_image_format_ext fmt = FORMAT_RGB_PACKED;
  int point_num = 5;

  bm_dev_request(&handle, 0);
  bm_image_create(handle, h, w, fmt, DATA_TYPE_EXT_1N_BYTE, &image, NULL);
  bm_image_alloc_dev_mem(image, BMCV_HEAP1_ID);
  bm_read_bin(image, "/opt/sophon/libsophon-current/bin/res/1920x1080_rgb.bin");

  bmcv_tde_draw(handle, image, point, point_num, color);

  bm_write_bin(image, "out.raw");
  bm_image_destroy(&image);
  bm_dev_free(handle);
  return 0;
}
```

# BMCV 接口总览

将 BMCV API 按实现的硬件分类，并简要说明功能。

## 多模块实现接口

| **num** | **API** | **功能** | **硬件** |
|---------|---------|----------|----------|
| 1 | bmcv_image_copy_to | 拷贝到目的图指定区域 | TPU / VPSS |
| 2 | bmcv_image_put_text | 写字 | CPU / VPSS |
| 3 | bmcv_image_convert_to | 线性变换 | TPU / VPSS |
| 4 | bmcv_image_rotate | 旋转 | LDC / VPSS |
| 5 | bmcv_image_rotate_trans | 旋转(指定TPU实现) | TPU / VPSS |

## VPSS实现接口

| **num** | **API** | **功能** |
|---------|---------|----------|
| 1 | bmcv_image_vpp_convert | crop+色彩转换+缩放 |
| - | bmcv_image_vpp_convert_padding | 填充背景色 |
| 2 | bmcv_image_vpp_csc_matrix_convert | 自定义矩阵色彩转换 |
| 3 | bmcv_image_vpp_basic | 多功能组合 |
| 4 | bmcv_image_csc_convert_to | 多功能组合+线性变换 |
| 5 | bmcv_image_draw_rectangle | 画空心框 |
| 6 | bmcv_image_fill_rectangle | 画实心框 |
| 7 | bmcv_image_flip | 图像横向/纵向翻转 |
| 8 | bmcv_image_mosaic | 图像局部马赛克 |
| 9 | bmcv_image_storage_convert | 色彩转换+缩放 |
| - | bmcv_image_storage_convert_with_csctype | 可选标准色彩转换+缩放 |
| 10 | bmcv_image_resize | 图像缩放 |
| 11 | bmcv_image_watermark_superpose | 水印叠加 |
| - | bmcv_image_watermark_repeat_superpose | 重复水印叠加 |
| 12 | bmcv_image_overlay | OSD叠加 |
| 13 | bmcv_image_vpp_stitch | 图像拼接(无重叠) |
| 14 | bmcv_image_circle | 画圆 |
| 15 | bmcv_image_draw_point | 画正方形实心点 |
| 16 | bmcv_image_csc_overlay | 多功能组合+OSD |

## JPEG实现接口

| **num** | **API** | **功能** |
|---------|---------|----------|
| 1 | bmcv_image_jpeg_dec | 图像解码 |
| 2 | bmcv_image_jpeg_enc | 图像编码 |

## TPU实现接口

| **num** | **API** | **功能** |
|---------|---------|----------|
| 1 | bmcv_image_absdiff | 两图相减取绝对值 |
| 2 | bmcv_image_axpy | F=A*X+Y的缩放加法 |
| 3 | bmcv_image_add_weighted | 两图加权融合 |
| 4 | bmcv_image_bitwise_and | 按位与 |
| - | bmcv_image_bitwise_or | 按位或 |
| - | bmcv_image_bitwise_xor | 按位异或 |
| 5 | bmcv_image_width_align | 按指定宽对齐 |
| 6 | bmcv_sort | 浮点数据排序 |
| 7 | bmcv_image_threshold | 像素阈值化 |
| 8 | bmcv_feature_match | 特征比对(INT8) |
| - | bmcv_feature_match_normalized | 特征比对(FP32) |
| 9 | bmcv_hist_balance | 直方图均衡化 |
| 10 | bmcv_image_quantify | FP32转INT8 |
| 11 | bmcv_faiss_indexflatIP | 向量相似度搜索 |
| - | bmcv_faiss_indexflatL2 | L2距离的平方 |
| - | bmcv_faiss_indexPQ_encode | 向量量化编码 |
| - | bmcv_faiss_indexPQ_encode_ext | 可选数据类型 |
| - | bmcv_faiss_indexPQ_ADC | 原始向量查询 |
| - | bmcv_faiss_indexPQ_ADC_ext | 可选数据类型 |
| - | bmcv_faiss_indexPQ_SDC | 编码向量查询 |
| - | bmcv_faiss_indexPQ_SDC_ext | 可选数据类型 |
| 12 | bmcv_image_transpose | 图像转置 |
| 13 | bmcv_image_pyramid_down | 高斯金字塔下采样 |
| 14 | bmcv_image_bayer2rgb | Bayer转RGBP |
| 15 | bmcv_batch_topk | 取前K个最大/小值 |
| 16 | bmcv_matmul | 矩阵乘法 |
| 17 | bmcv_calc_hist | 直方图计算 |
| - | bmcv_calc_hist_with_weight | 带权重直方图 |
| - | bmcv_hist_balance | 直方图均衡化 |
| 18 | bmcv_as_strided | 重指定行列和步长 |
| 19 | bmcv_min_max | 取最大/小值。 |
| 20 | bmcv_cmulp | 复数乘法 |
| 21 | bmcv_image_laplacian | 梯度计算 |
| 22 | bmcv_gemm | 广义矩阵乘加 |
| - | bmcv_gemm_ext | 可选数据类型 |
| 23 | bmcv_image_warp | 仿射变换 |
| - | bmcv_image_warp_affine | 仿射变换 |
| - | bmcv_image_warp_affine_padding | 背景图填充 |
| - | bmcv_image_warp_affine_similar_to_opencv | 矩阵对齐opencv |
| - | bmcv_image_warp_affine_similar_to_opencv_padding | 功能结合 |
| 24 | bmcv_image_warp_perspective | 透射变换 |
| - | bmcv_image_warp_perspective_with_coordinate | 坐标输入 |
| - | bmcv_image_warp_perspective_similar_to_opencv | 矩阵对齐opencv |
| 25 | bmcv_distance | 多点到一点欧式距离 |
| 26 | bmcv_fft_execute | 快速傅里叶变换 |
| - | bmcv_fft_execute_real_input | 实数输入 |
| 27 | bmcv_stft | 短时傅里叶变换 |
| - | bmcv_istft | 逆短时傅里叶变换 |

# IVE实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_ive_filter | 5x5模板滤波 |
| 2 | bmcv_ive_csc | 色彩空间转换 |
| 3 | bmcv_ive_filter_and_csc | 功能组合 |
| 4 | bmcv_ive_dilate | 5x5模板膨胀 |
| 5 | bmcv_ive_erode | 5x5模板腐蚀 |
| 6 | bmcv_ive_ccl | 连通区域标记 |
| 7 | bmcv_ive_integ | 积分图计算 |
| 8 | bmcv_ive_hist | 直方图计算 |
| 9 | bmcv_ive_gradfg | 梯度前景图计算 |
| 10 | bmcv_ive_lbp | 局部二值计算 |
| 11 | bmcv_ive_normgrad | 归一化梯度计算 |
| 12 | bmcv_ive_sad | 绝对差和 |
| 13 | bmcv_ive_stcandicorner | 角点计算 |
| 14 | bmcv_ive_mag_and_ang | 5x5模板幅值/幅角计算 |
| 15 | bmcv_ive_map | 映射赋值 |
| 16 | bmcv_ive_ncc | 归一化互相关系数计算 |
| 17 | bmcv_ive_ord_stat_filter | 3x3模板顺序统计量滤波 |
| 18 | bmcv_ive_sobel | 5x5模板梯度计算 |
| 19 | bmcv_ive_gmm | 背景建模 |
| 20 | bmcv_ive_gmm2 | 背景建模支持更多参数 |
| 21 | bmcv_ive_resize | 图像缩放 |
| 22 | bmcv_ive_thresh | 阈值化 |
| 23 | bmcv_ive_add | 两图加权相加 |
| 24 | bmcv_ive_sub | 两图相减 |
| 25 | bmcv_ive_and | 两图相与 |
| 26 | bmcv_ive_or | 两图相或 |
| 27 | bmcv_ive_xor | 两图异或 |
| 28 | bmcv_ive_canny | 边缘图计算 |
| 29 | bmcv_ive_match_bgmodel | 获取前景数据 |
| 30 | bmcv_ive_update_bgmodel | 更新背景模型 |
| 31 | bmcv_ive_frame_diff_motion | 背景相减 |
| 32 | bmcv_ive_bernsen | 图像二值化 |
| 33 | bmcv_ive_16bit_to_8bit | 16Bit转8Bit |
| 34 | bmcv_ive_dma | 内存拷贝 |

# LDC实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_ldc_rot | 旋转 |
| 2 | bmcv_ldc_gdc | 畸变校正 |
| 3 | bmcv_ldc_gdc_load_mesh | 畸变校正(加载已有MESH表) |

# DWA实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_dwa_rot | 旋转 |
| 2 | bmcv_dwa_gdc | 畸变校正 |
| 3 | bmcv_dwa_affine | 仿射校正 |
| 4 | bmcv_dwa_fisheye | 鱼眼校正 |
| 5 | bmcv_dwa_dewarp | 畸变校正(输入GRIDINFO) |

# DPU实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_dpu_sgbm_disp | 半全局块匹配计算 |
| 2 | bmcv_dpu_fgs_disp | 快速全局平滑计算 |
| 3 | bmcv_dpu_online_disp | 功能组合 |

# BLEND实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_blend | 图像拼接(重叠区域平滑过渡) |

# TDE实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_tde_fill | 颜色填充 |
| 2 | bmcv_tde_convert | crop/csc/缩放/旋转/叠图 |
| 3 | bmcv_tde_line | 绘制线条 |
| 4 | bmcv_tde_draw | 填充多边形 |
| 5 | bmcv_tde_warp_affine | 仿射变换 |

# SPACC实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_base64_enc | base64编码 |
| 2 | bmcv_base64_dec | base64解码 |

# CPU实现接口

| num | API | 功能 |
|-----|-----|------|
| 1 | bmcv_image_draw_lines | 划线 |
| 2 | bmcv_fft_1d_create_plan | 一维FFT任务创建 |
|  | bmcv_fft_2d_create_plan | 二维FFT任务创建 |
|  | bmcv_fft_destroy_plan | FFT任务销毁 |
| 3 | bmcv_ldc_gdc_gen_mesh | 畸变校正MESH表计算 |
| 4 | bmcv_gen_text_watermark | 生成文字水印 |
| 5 | bm_image_write_to_bmp | 保存BMP图像到文件 |
| 6 | bm_read_bin | 读取RAW图像到内存 |
| 7 | bm_write_bin | 保存RAW图像到文件 |

# bm_image_alloc_contiguous_mem_heap_mask

**【描述】**
为多个 image 在指定的 heap 上分配连续的内存。

**【语法】**
```c++
bm_status_t bm_image_alloc_contiguous_mem_heap_mask(
        int           image_num,
        bm_image      *images,
        int           heap_mask
);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|----------|-----------|------|
| image_num | 输入 | 待分配内存的 image 个数。 |
| *images | 输入 | 待分配内存的 image 的指针。 |
| heap_mask | 输入 | 选择一个或多个 heap id 的掩码，每一个 bit 表示一个 heap id 的是否有效, 1 表示可以在该 heap 上分配，0 则表示不可以在该 heap 上分配，最低位表示 heap0，以此类推。比如 heap_mask=0b10 则表示指定在 heap1 上分配空间，heap_mask=0b101 则表示指定在 heap0 或者 heap2 上分配空间。 |

**【返回值】**
函数调用成功时返回BM_SUCCESS。

**【注意事项】**
1. image_num 应该大于 0,否则将返回错误。
2. 如传入的 image 已分配或者 attach 过内存，应先 detach 已有内存，否则将返回失败。
3. 所有待分配的 image 应该尺寸相同，否则将返回错误。
4. 当希望 destory 的 image 是通过调用本 api 所分配的内存时，应先调用 bm_image_free_contiguous_mem 将分配内存释放，再用 bm_image_destroy 来实现 destory image
5. bm_image_alloc_contiguous_mem 与 bm_image_free_contiguous_mem 应成对使用。

# bm_image_copy_device_to_host

**【描述】**
该 API 将 device memory 中的图片数据拷贝到 host 端。

**【语法】**
```c++
bm_status_t bm_image_copy_device_to_host(
        bm_image image,
        void* buffers[]
);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|----------|-----------|------|
| image | 输入 | 待传输数据的 bm_image 对象。 |
| * buffers[] | 输出 | host 端指针，buffers 为指向不同 plane 数据的指针，每个 plane 需要传输的数据量可以通过 bm_image_get_byte_size API 获取。 |

**【返回值】**
该函数成功调用时, 返回 BM_SUCCESS。

**注意：**
1. 如果 bm_image 未由 bm_image_create 创建，则返回失败。
2. 如果 bm_image 没有与 device memory 相关联的话，将返回失败。
3. 数据传输失败的话，API 将调用失败。
4. 如果该函数成功返回，会将所关联的 device memory 中的数据拷贝到 host 端 buffers 中。
5. 调用之前，请为 buffers 中的各指针提前分配虚拟内存，内存大小应为每个 plane 需要传输的数据量。

# bm_image_copy_host_to_device

**【描述】**
该 API 将 host 端数据拷贝到 bm_image 结构对应的 device memory 中。

**【语法】**
```c++
bm_status_t bm_image_copy_host_to_device(
    bm_image image,
    void* buffers[]
);
```

**【参数】**

| 参数名称 | 输入/输出 | 描述 |
|----------|-----------|------|
| image | 输入 | 待填充 device memory 数据的 bm_image 对象。 |
| * buffers[] | 输入 | host 端指针，buffers 为指向不同 plane 数据的指针。 |

其中，buffers[]的数组长度应等于创建 bm_image 结构时 image_format 对应的 plane 数。每个 plane 数据量的具体计算方法如下（以紧凑排列的默认stride为例）:

```c++
switch (image_format) {
    case FORMAT_YUV420P: {
        size[0] = width * height * data_size;
        size[1] = ALIGN(width, 2) * ALIGN(height, 2) / 4 * data_size;
        size[2] = ALIGN(width, 2) * ALIGN(height, 2) / 4 * data_size;
        break;
    }
    case FORMAT_YUV422P: {
        size[0] = width * height * data_size;
        size[1] = ALIGN(width, 2) * ALIGN(height, 2) / 2 * data_size;
        size[2] = ALIGN(width, 2) * ALIGN(height, 2) / 2 * data_size;
        break;
    }
    case FORMAT_YUV444P:
    case FORMAT_BGRP_SEPARATE:
    case FORMAT_RGBP_SEPARATE:
    case FORMAT_HSV_PLANAR: {
        size[0] = width * height * data_size;
        size[1] = width * height * data_size;
        size[2] = width * height * data_size;
        break;
    }
    case FORMAT_NV24: {
        size[0] = width * height * data_size;
        size[1] = width * 2 * height * data_size;
        break;
    }
    case FORMAT_NV12:
    case FORMAT_NV21: {
        size[0] = width * height * data_size;
        size[1] = ALIGN(width, 2) * ALIGN(height, 2) / 2 * data_size;
        break;
    }
    case FORMAT_NV16:
    case FORMAT_NV61: {
        size[0] = width * height * data_size;
        size[1] = ALIGN(width, 2) * height * data_size;
        break;
    }
    case FORMAT_GRAY:
    case FORMAT_BAYER:
    case FORMAT_BAYER_RG8: {
        size[0] = width * height * data_size;
        break;
    }
    case FORMAT_COMPRESSED: {
        break;
    }
    case FORMAT_YUV444_PACKED:
    case FORMAT_YVU444_PACKED:
    case FORMAT_HSV180_PACKED:
    case FORMAT_HSV256_PACKED:
    case FORMAT_BGR_PACKED:
    case FORMAT_RGB_PACKED: {
        size[0] = width * 3 * height * data_size;
        break;
    }
    case FORMAT_ABGR_PACKED:
    case FORMAT_ARGB_PACKED: {
        size[0] = width * 4 * height * data_size;
        break;
    }
    case FORMAT_BGR_PLANAR:
    case FORMAT_RGB_PLANAR: {
        size[0] = width * height * 3 * data_size;
        break;
    }
    case FORMAT_RGBYP_PLANAR: {
        size[0] = width * height * data_size;
        size[1] = width * height * data_size;
        size[2] = width * height * data_size;
        size[3] = width * height * data_size;
        break;
    }
```

```c
case FORMAT_YUV422_YUYV:
case FORMAT_YUV422_YVYU:
case FORMAT_YUV422_UYVY:
case FORMAT_YUV422_VYUY:
case FORMAT_ARGB4444_PACKED:
case FORMAT_ABGR4444_PACKED:
case FORMAT_ARGB1555_PACKED:
case FORMAT_ABGR1555_PACKED: {
    size[0] = width * 2 * height * data_size;
    break;
}
```

## 返回值

该函数成功调用时，返回 BM_SUCCESS。

**注意：**

1. 如果 bm_image 未由 bm_image_create 创建，则返回失败。
2. 如果所传入的 bm_image 对象还没有与 device memory 相关联的话，会自动为每个 plane 申请对应 image_private->plane_byte_size 大小的 device memory，并将 host 端数据拷贝到申请的 device memory 中。如果申请 device memory 失败，则该 API 调用失败。
3. 如果所传入的 bm_image 对象图片格式为 FORMAT_COMPRESSED，且该 bm_image 在 create 时没有设置 stride 参数，则直接返回失败。
4. 如果拷贝失败，则该 API 调用失败。

# bm_image_create

## 描述

创建一个 bm_image 结构。

## 语法

```c++
bm_status_t bm_image_create(
    bm_handle_t handle,
    int img_h,
    int img_w,
    bmcv_image_format_ext image_format,
    bmcv_data_format_ext data_type,
    bm_image *image,
    int* stride = NULL);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| handle | 输入 | 输入参数。设备环境句柄，通过调用 bm_dev_request 获取。 |
| img_h | 输入 | 图片高度。 |
| img_w | 输入 | 图片宽度。 |
| image_format | 输入 | 所需创建 bm_image 图片格式。 |
| data_type | 输入 | 所需创建 bm_image 数据格式。 |
| *image | 输出 | 输出填充的 bm_image 结构指针。 |
| *stride | 输入 | 所创建 bm_image 将要关联的 device memory 内存布局，即每个 plane 的 width stride 值。在传入NULL时默认与一行的数据宽度相同，以 byte 计数。更多用法请参阅注意事项。 |

## 返回值

成功调用将返回 BM_SUCCESS，并填充输出的 image 指针结构。这个结构中记录了图片的大小，以及相关格式。但此时并没有与任何 device memory 关联，也没有申请数据对应的 device memory。

## 注意事项

1. 以下图片格式的宽可以是奇数，接口内部会调整到偶数再完成相应功能。但建议尽量使用偶数的宽，这样可以发挥最大的效率：
   - FORMAT_YUV420P
   - FORMAT_YUV422P
   - FORMAT_NV12
   - FORMAT_NV21
   - FORMAT_NV16
   - FORMAT_NV61

2. 以下图片格式的高可以是奇数，接口内部会调整到偶数再完成相应功能。但建议尽量使用偶数的高，这样可以发挥最大的效率：
   - FORMAT_YUV420P
   - FORMAT_NV12
   - FORMAT_NV21

3. FORMAT_COMPRESSED 图片格式的图片创建时需要将 stride 参数的数组设置为各通道的数据长度。若 stride 设置为 NULL，后续则需要用 bm_image_attach 绑定 device memory。
4. 若 stride 参数设置为 NULL，此时默认各个 plane 的数据是 compact 排列，创建的 bm_image 各 plane 的 stride 被设置为与 image_format 对应的默认值。
5. 如果传入 stride 非 NULL，则会检测传入的各 stride 值是否大于 image_format 对应的所有 plane 的默认 stride，若大于，则创建的 bm_image 各 plane 的 stride 值设定为传入值；若反之，则设定为默认 stride 值向上对齐传入值的值。
6. 默认 stride 值的计算方法如下：

```c++
int data_size = 1;
switch (data_type) {
    case DATA_TYPE_EXT_FLOAT32:
    case DATA_TYPE_EXT_U32:
        data_size = 4;
        break;
    case DATA_TYPE_EXT_FP16:
    case DATA_TYPE_EXT_BF16:
    case DATA_TYPE_EXT_U16:
    case DATA_TYPE_EXT_S16:
        data_size = 2;
        break;
    default:
        data_size = 1;
        break;
}
int default_stride[3] = {0};
switch (image_format) {
    case FORMAT_YUV420P: {
        plane_num = 3;
        default_stride[0] = width * data_size;
        default_stride[1] = (ALIGN(width, 2) >> 1) * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_YUV422P: {
        plane_num = 3;
        default_stride[0] = width * data_size;
        default_stride[1] = (ALIGN(width, 2) >> 1) * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_YUV444P:
    case FORMAT_BGRP_SEPARATE:
    case FORMAT_RGBP_SEPARATE:
    case FORMAT_HSV_PLANAR: {
        plane_num = 3;
        default_stride[0] = width * data_size;
        default_stride[1] = width * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_NV24: {
        plane_num = 2;
        default_stride[0] = width * data_size;
        default_stride[1] = width * 2 * data_size;
        break;
    }
    case FORMAT_NV12:
    case FORMAT_NV21: {
        plane_num = 2;
        default_stride[0] = width * data_size;
        default_stride[1] = ALIGN(width, 2) * data_size;
        break;
    }
    case FORMAT_NV16:
    case FORMAT_NV61: {
        plane_num = 2;
        default_stride[0] = width * data_size;
        default_stride[1] = ALIGN(width, 2) * data_size;
        break;
    }
    case FORMAT_GRAY:
    case FORMAT_BAYER:
    case FORMAT_BAYER_RG8: {
        plane_num = 1;
        default_stride[0] = width * data_size;
        break;
    }
    case FORMAT_COMPRESSED: {
        plane_num = 4;
        break;
    }
    case FORMAT_YUV444_PACKED:
    case FORMAT_YVU444_PACKED:
    case FORMAT_HSV180_PACKED:
    case FORMAT_HSV256_PACKED:
    case FORMAT_BGR_PACKED:
    case FORMAT_RGB_PACKED: {
        plane_num = 1;
        default_stride[0] = width * 3 * data_size;
        break;
    }
    case FORMAT_ABGR_PACKED:
    case FORMAT_ARGB_PACKED: {
        plane_num = 1;
        default_stride[0] = width * 4 * data_size;
        break;
    }
    case FORMAT_BGR_PLANAR:
    case FORMAT_RGB_PLANAR: {
        plane_num = 1;
        default_stride[0] = width * data_size;
        break;
    }
    case FORMAT_RGBYP_PLANAR: {
        plane_num = 4;
        default_stride[0] = width * data_size;
        default_stride[1] = width * data_size;
        default_stride[2] = width * data_size;
        default_stride[3] = width * data_size;
        break;
    }
    case FORMAT_YUV422_YUYV:
    case FORMAT_YUV422_YVYU:
    case FORMAT_YUV422_UYVY:
    case FORMAT_YUV422_VYUY:
    case FORMAT_ARGB4444_PACKED:
    case FORMAT_ABGR4444_PACKED:
    case FORMAT_ARGB1555_PACKED:
    case FORMAT_ABGR1555_PACKED: {
        plane_num = 1;
        default_stride[0] = width * 2 * data_size;
        break;
    }
}
```

# bm_image_get_contiguous_device_mem

## 描述

从多个内存连续的 image 中得到连续内存的 device memory 信息。

## 语法

```c++
bm_status_t bm_image_get_contiguous_device_mem(
        int image_num,
        bm_image *images,
        bm_device_mem_t * mem
);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| image_num | 输入 | 待获取信息的 image 个数。 |
| *images | 输入 | 待获取信息的 image 指针。 |
| *mem | 输出 | 得到的连续内存的 device memory 信息。 |

## 返回值

函数调用成功时返回 BM_SUCCESS。

## 注意事项

1. image_num 应该大于 0，否则将返回错误。
2. 所填入的 image 应该尺寸相同，否则将返回错误。
3. 所填入的 image 必须是内存连续的，否则返回错误。
4. 所填入的 image 内存必须是通过 bm_image_alloc_contiguous_mem 或者 bm_image_attach_contiguous_mem 获得。

# bm_image_get_format_info

## 描述

该接口用于获取 bm_image 的一些信息。

## 语法

```c++
bm_status_t bm_image_get_format_info(
        bm_image *              src,
        bm_image_format_info_t *info
);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| *src | 输入 | 所要获取信息的目标 bm_image。 |
| *info | 输出 | 保存所需信息的数据结构，返回给用户，具体内容见下面的数据结构说明。 |

## 返回值

函数调用成功时返回 BM_SUCCESS。

## 数据类型说明

```c++
typedef struct bm_image_format_info {
        int                      plane_nb;
        bm_device_mem_t          plane_data[8];
        int                      stride[8];
        int                      width;
        int                      height;
        bm_image_format_ext      image_format;
        bm_image_data_format_ext data_type;
        bool                     default_stride;
} bm_image_format_info_t;
```

* int plane_nb：该 image 的 plane 数量
* bm_device_mem_t plane_data[8]：各个 plane 的 device memory
* int stride[8]：各个 plane 的 stride 值
* int width：图片的宽度
* int height：图片的高度
* bm_image_format_ext image_format：图片的格式
* bm_image_data_format_ext data_type：图片的存储数据类型
* bool default_stride：是否使用了默认的 stride

# bm_image_write_to_bmp

## 描述

该接口用于将 bm_image 的数据保存成 bmp 格式存到文件中。

## 语法

```c++
bm_status_t bm_image_write_to_bmp(bm_image image, const char *filename);
```

## 参数

| 参数名称 | 输入/输出 | 描述 |
|---------|-----------|------|
| image | 输入 | 目标 bm_image。 |
| filename | 输入 | 保存 bmp 文件的名称。 |

## 返回值

成功则返回 BM_SUCCESS。

## 注意事项

1. 该 api 要求输入 bm_image 对象关联 device memory，否则返回失败。

BMCV 还提供类似接口读入或写出 bm_image 的数据。如下：

```c++
void bm_read_bin(bm_image src, const char *input_name);
void bm_read_compact_bin(bm_image src, const char *input_name);

void bm_write_bin(bm_image dst, const char *output_name);
void bm_write_compact_bin(bm_image dst, const char *output_name);
```

其中，bm_read_bin 和 bm_write_bin 可以读入和写出 raw 数据文件，读入写出数据按照每行间距为 bm_image 中各 plane 的 stride 来进行。（若 stride 大于默认 stride，可能会读取或写出无效数据）

bm_read_compact_bin 和 bm_write_compact_bin 适合读入和写出紧凑排列的 raw 数据文件，读入写出数据按照每行间距为 bm_image 中各 plane 的默认 stride 来进行。