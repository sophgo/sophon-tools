# bmcv_image_absdiff

两张大小相同的图片对应像素值相减并取绝对值。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_absdiff(
            bm_handle_t handle,
            bm_image input1,
            bm_image input2,
            bm_image output);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_image input1
  输入参数。输入第一张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image input2
  输入参数。输入第二张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output
  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下image_format:

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

目前支持以下data_type:

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1、在调用bmcv_image_absdiff()之前必须确保输入的image内存已经申请。

2、input output的data_type，image_format必须相同。

**代码示例：**

```c
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include "bmcv_api_ext.h"

static void readBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input1, input2, output;
    int img_size = width * height * channel;
    const char *src1_name = "path/to/src1";
    const char *src2_name = "path/to/src2";
    const char *dst_name = "path/to/dst";
    unsigned char* input1_data = (unsigned char*)malloc(width * height * channel);
    unsigned char* input2_data = (unsigned char*)malloc(width * height * channel);
    unsigned char* output_tpu = (unsigned char*)malloc(width * height * channel);
    unsigned char *in1_ptr[3] = {input1_data, input1_data + height * width, input1_data + 2 * height * width};
    unsigned char *in2_ptr[3] = {input2_data, input2_data + width * height, input2_data + 2 * height * width};
    unsigned char *out_ptr[3] = {output_tpu, output_tpu + height * width, output_tpu + 2 * height * width};

    bm_dev_request(&handle, dev_id);

    readBin(src1_name, input1_data, img_size);
    readBin(src2_name, input2_data, img_size);
    // calculate res
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input1);
    bm_image_alloc_dev_mem(input1);
    bm_image_copy_host_to_device(input1, (void**)in1_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input2);
    bm_image_alloc_dev_mem(input2);
    bm_image_copy_host_to_device(input2, (void**)in2_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_absdiff(handle, input1, input2, output);
    bm_image_copy_device_to_host(output, (void**)out_ptr);
    writeBin(dst_name, output_tpu, img_size);

    bm_image_destroy(input1);
    bm_image_destroy(input2);
    bm_image_destroy(output);
    free(input1_data);
    free(input2_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_add_weighted

实现两张相同大小图像的加权融合，具体如下：

output = alpha * input1 + beta * input2 + gamma

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_add_weighted(
            bm_handle_t handle,
            bm_image input1,
            float alpha,
            bm_image input2,
            float beta,
            float gamma,
            bm_image output);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_image input1
  输入参数。输入第一张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* float alpha
  第一张图像的权重。

* bm_image input2
  输入参数。输入第二张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* float beta
  第二张图像的权重。

* float gamma
  融合之后的偏移量。

* bm_image output
  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下image_format:

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

目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |
| 2   | DATA_TYPE_EXT_FLOAT32 |

**注意事项：**

1. 在调用该接口之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format 必须相同。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input1, input2, output;
    unsigned char* input1_data = (unsigned char*)malloc(width * height * channel);
    unsigned char* input2_data = (unsigned char*)malloc(width * height * channel);
    unsigned char* output_tpu = (unsigned char*)malloc(width * height * channel);
    const char *src1_name = "path/to/src1";
    const char *src2_name = "path/to/src2";
    const char *dst_name = "path/to/dst";
    unsigned char* in1_ptr[3] = {input1_data, input1_data + height * width, input1_data + 2 * height * width};
    unsigned char* in2_ptr[3] = {input2_data, input2_data + height * width, input2_data + 2 * height * width};
    unsigned char* out_ptr[3] = {output_tpu, output_tpu + height * width, output_tpu + 2 * height * width};
    int img_size = width * height * channel;

    readBin(src1_name, input1_data, img_size);
    readBin(src2_name, input2_data, img_size);

    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input1);
    bm_image_alloc_dev_mem(input1);
    bm_image_copy_host_to_device(input1, (void **)&in1_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input2);
    bm_image_alloc_dev_mem(input2);
    bm_image_copy_host_to_device(input2, (void **)&in2_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_add_weighted(handle, input1, 0.5, input2, 0.5, 0, output);
    bm_image_copy_device_to_host(output, (void **)&out_ptr);
    writeBin(dst_name, output_tpu, img_size);

    bm_image_destroy(input1);
    bm_image_destroy(input2);
    bm_image_destroy(output);
    bm_dev_free(handle);
    free(input1_data);
    free(input2_data);
    free(output_tpu);
    return 0;
}
```

# BMCV API

简要说明 BMCV API 由哪一部分硬件实现

**以下接口 BM1684X 尚未实现:**

* bmcv_image_canny
* bmcv_image_dct
* bmcv_image_draw_lines
* bmcv_fft
* bmcv_image_lkpyramid
* bmcv_image_morph
* bmcv_image_sobel

| num | API                             | BM1684    | BM1684X   |
|-----|---------------------------------|-----------|-----------|
| 1   | bmcv_as_strided                 | NOT SUPPORT | TPU       |
| 2   | bmcv_image_absdiff              | TPU       | TPU       |
| 3   | bmcv_image_add_weighted         | TPU       | TPU       |
| 4   | bmcv_base64                     | SPACC     | SPACC     |
| 5   | bmcv_image_bayer2rgb            | NOT SUPPORT | TPU       |
| 6   | bmcv_image_bitwise_and          | TPU       | TPU       |
| 7   | bmcv_image_bitwise_or           | TPU       | TPU       |
| 8   | bmcv_image_bitwise_xor          | TPU       | TPU       |
| 9   | bmcv_calc_hist                  | TPU       | TPU       |
| 10  | bmcv_image_canny                | TPU       | TPU       |
| 11  | bmcv_image_convert_to           | TPU       | VPP+TPU   |
| 12  | bmcv_image_copy_to              | TPU       | VPP+TPU   |
| 13  | bmcv_image_dct                  | TPU       | TPU       |
| 14  | bmcv_distance                   | TPU       | TPU       |
| 15  | bmcv_image_draw_lines           | CPU       | VPP       |
| 16  | bmcv_image_draw_rectangle       | TPU       | VPP       |
| 17  | bmcv_feature_match              | TPU       | TPU       |
| 18  | bmcv_fft                        | TPU       | TPU       |
| 19  | bmcv_image_fill_rectangle       | TPU       | VPP       |
| 20  | bmcv_image_gaussian_blur        | TPU       | TPU       |
| 21  | bmcv_gemm                       | TPU       | TPU       |
| 22  | bmcv_image_jpeg_enc             | JPU       | JPU       |
| 23  | bmcv_image_jpeg_dec             | JPU       | JPU       |
| 24  | bmcv_image_laplacian            | TPU       | TPU       |
| 25  | bmcv_matmul                     | TPU       | TPU       |
| 26  | bmcv_min_max                    | TPU       | TPU       |
| 27  | bmcv_nms_ext                    | TPU       | TPU       |
| 28  | bmcv_nms                        | TPU       | TPU       |
| 29  | bmcv_image_resize               | VPP+TPU   | VPP       |
| 30  | bmcv_image_sobel                | TPU       | TPU       |
| 31  | bmcv_sort                       | TPU       | TPU       |
| 32  | bmcv_image_storage_convert      | VPP+TPU   | VPP       |
| 33  | bmcv_image_threshold            | TPU       | TPU       |
| 34  | bmcv_image_transpose            | TPU       | TPU       |
| 35  | bmcv_image_vpp_basic            | VPP       | VPP       |
| 36  | bmcv_image_vpp_convert_padding  | VPP       | VPP       |
| 37  | bmcv_image_vpp_convert          | VPP       | VPP       |
| 38  | bmcv_image_vpp_csc_matrix_convert | VPP     | VPP       |
| 39  | bmcv_image_vpp_stitch           | VPP       | VPP       |
| 40  | bmcv_image_warp_affine          | TPU       | TPU       |
| 41  | bmcv_image_warp_perspective     | TPU       | TPU       |
| 42  | bmcv_image_watermark_superpose  | NOT SUPPORT | TPU       |
| 43  | bmcv_nms_yolo                   | TPU       | TPU       |
| 44  | bmcv_cmulp                      | TPU       | TPU       |
| 45  | bmcv_faiss_indexflatIP          | NOT SUPPORT | TPU       |
| 46  | bmcv_faiss_indexflatL2          | NOT SUPPORT | TPU       |
| 47  | bmcv_image_yuv2bgr_ext          | TPU       | VPP       |

| 48  | bmcv_image_yuv2hsv               | TPU       | VPP+TPU   |
| 49  | bmcv_batch_topk                  | TPU       | TPU       |
| 50  | bmcv_image_put_text              | CPU       | CPU       |
| 51  | bmcv_hm_distance                 | NOT SUPPORT | TPU     |
| 52  | bmcv_axpy                        | TPU       | TPU       |
| 53  | bmcv_image_pyramid_down          | TPU       | TPU       |
| 54  | bmcv_image_quantify              | NOT SUPPORT | TPU     |
| 55  | bmcv_image_rotate                | NOT SUPPORT | TPU     |
| 56  | bmcv_cos_similarity              | NOT SUPPORT | TPU     |
| 57  | bmcv_matrix_prune                | NOT SUPPORT | TPU     |
| 58  | bmcv_median_blur                 | NOT SUPPORT | TPU     |
| 59  | bmcv_assigned_area_blur          | NOT SUPPORT | TPU     |
| 60  | bmcv_image_crop                  | TPU       | TPU+VPP   |
| 61  | bmcv_image_split                 | TPU       | TPU       |
| 62  | bmcv_hamming_distance            | NOT SUPPORT | TPU     |
| 63  | bmcv_image_yuv_resize            | TPU       | TPU+VPP   |
| 64  | bmcv_width_align                 | TPU       | TPU       |
| 65  | bmcv_faiss_indexPQ_ADC           | NOT SUPPORT | TPU     |
| 66  | bmcv_faiss_indexPQ_SDC           | NOT SUPPORT | TPU     |
| 67  | bmcv_faiss_indexPQ_encode        | NOT SUPPORT | TPU     |
| 68  | bmcv_image_axpy                  | NOT SUPPORT | TPU     |
| 69  | bmcv_image_fusion                | TPU       | NOT SUPPORT |
| 70  | bmcv_calc_hist_with_weight       | TPU       | TPU       |
| 71  | bmcv_hist_balance                | TPU       | TPU       |
| 72  | bmcv_lap_matrix                  | NOT SUPPORT | TPU     |
| 73  | bmcv_stft                        | NOT SUPPORT | TPU     |
| 74  | bmcv_istft                       | NOT SUPPORT | TPU     |
| 75  | bmcv_image_rotate                | NOT SUPPORT | TPU     |
| 76  | bmcv_cos_similarity              | NOT SUPPORT | TPU     |
| 77  | bmcv_matrix_prune                | NOT SUPPORT | TPU     |
| 78  | bmcv_image_overlay               | NOT SUPPORT | TPU     |
| 79  | bmcv_get_structuring_element     | CPU       | CPU       |
| 80  | bmcv_image_erode                 | TPU       | NOT SUPPORT |
| 81  | bmcv_image_dilate                | TPU       | NOT SUPPORT |
| 82  | bmcv_image_lkpyramid_create_plan | CPU       | CPU       |
| 83  | bmcv_image_lkpyramid_execute     | CPU       | NOT SUPPORT |
| 84  | bmcv_dct_coeff                   | NOT SUPPORT | VPP     |
| 85  | bmcv_image_mosaic                | NOT SUPPORT | VPP     |
| 86  | bmcv_gen_text_watermark          | CPU       | CPU       |
| 87  | bmcv_image_csc_convert_to        | TPU       | VPP+TPU   |
| 88  | bmcv_image_vpp_basic_v2          | NOT SUPPORT | VPP+TPU |
| 89  | bmcv_image_draw_point            | NOT SUPPORT | VPP     |
| 90  | bmcv_knn                         | NOT SUPPORT | TPU     |

**注意：**

对于BM1684和BM1684X而言，以下两个算子的实现需要结合BMCPU与Tensor Computing Processor：

| num | API                |
|-----|--------------------|
| 1   | bmcv_image_lkpyramid |
| 2   | bmcv_image_morph   |

## bmcv_as_strided

该接口可以根据现有矩阵以及给定的步长来创建一个视图矩阵。

**处理器型号支持：**

该接口仅支持BM1684X。

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

**输入参数说明：**

- bm_handle_t handle：输入参数。bm_handle 句柄。
- bm_device_mem_t input：输入参数。存放输入矩阵 input 数据的设备内存地址。
- bm_device_mem_t output：输入参数。存放输出矩阵 output 数据的设备内存地址。
- int input_row：输入参数。输入矩阵 input 的行数。
- int input_col：输入参数。输入矩阵 input 的列数。
- int output_row：输入参数。输出矩阵 output 的行数。
- int output_col：输入参数。输出矩阵 output 的列数。
- int row_stride：输入参数。输出矩阵行之间的步长。
- int col_stride：输入参数。输出矩阵列之间的步长。

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

**示例代码**

```c
#include "bmcv_api_ext.h"
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
    bm_handle_t handle;
    int len = input_row * input_col;
    bm_device_mem_t input_dev_mem, output_dev_mem;
    bm_dev_request(&handle, 0);

    float* input_data = new float[input_row * input_col];
    float* output_data = new float[output_row * output_col];

    for (int i = 0; i < len; i++) {
        input_data[i] = (float)rand() / (float)RAND_MAX * 100;
    }

    bm_malloc_device_byte(handle, &input_dev_mem, input_row * input_col * sizeof(float));
    bm_malloc_device_byte(handle, &output_dev_mem, output_row * output_col * sizeof(float));
    bm_memcpy_s2d(handle, input_dev_mem, input_data);
    bmcv_as_strided(handle, input_dev_mem, output_dev_mem, input_row, input_col,
                    output_row, output_col, row_stride, col_stride);
    bm_memcpy_d2s(handle, output_data, output_dev_mem);

    bm_free_device(handle, input_dev_mem);
    bm_free_device(handle, output_dev_mem);
    delete[] output_data;
    delete[] input_data;
    bm_dev_free(handle);
    return 0;
}
```

## bmcv_image_assigned_area_blur

对图像指定区域进行模糊处理。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_assigned_area_blur(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            int ksize,
            int assigned_area_num,
            float center_weight_scale,
            bmcv_rect_t *assigned_area);
```

**参数说明：**

- bm_handle_t handle：输入参数。 bm_handle 句柄。
- bm_image input：输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。
- bm_image output：输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。
- int ksize：输入参数。区域模糊卷积核的宽高尺寸。ksize的有效值为3，5，7，9，11。
- int assigned_area_num：输入参数。模糊区域的个数。assigned_area_num的有效值为1-200。
- float center_weight_scale：输入参数。区域模糊卷积核中心权重缩放系数。缩放系数越小，卷积时中心像素权重越低，边缘像素权重约高。center_weight_scale有效值为0.0-1.0。
- bmcv_rect_t *assigned_area：指定区域的详细信息。其中包含指定区域的起始横坐标和纵坐标，还有指定区域的宽和高大小。

其中bmcv_rect_t结构体定义如下：

```c
typedef struct bmcv_rect {
    unsigned int start_x;
    unsigned int start_y;
    unsigned int crop_w;
    unsigned int crop_h;
} bmcv_rect_t;
```

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

**格式支持：**

该接口目前支持以下 image_format：

| num | image_format         |
|-----|----------------------|
| 1   | FORMAT_YUV420P       |
| 2   | FORMAT_YUV444P       |
| 3   | FORMAT_RGB_PLANNAR   |
| 4   | FORMAT_BGR_PLANAR    |
| 5   | FORMAT_RGBP_SEPARATE |
| 6   | FORMAT_BGRP_SEPARATE |
| 7   | FORMAT_GRAY          |

目前支持以下 data_type：

| num | data_type |
|-----|-----------|

| DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1. 在调用 bmcv_image_assigned_area_blur() 之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format 必须相同。
3. 需要处理的底图尺寸有效值为 8*8-4096-4096，指定区域起始横坐标有效值为 0～底图宽，纵坐标有效值为 0～底图高，指定区域宽的有效值为 1～（底图宽 - 起始横坐标），高的有效值为 1～（底图高 - 起始纵坐标）。
4. 如果输入图像格式为 yuv420p 和 yuv444p，可在调用接口前将 bm_image 创建为 FORMAT_GRAY 格式，进入算子后仅处理 Y 通道，处理效果和三通道处理近似，性能较三通道处理有较大优势，具体处理请参考代码示例。

**代码示例：**

```c
#include <cerrno>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <pthread.h>
#include <math.h>
#include "bmcv_api_ext_c.h"
#define ASSIGNED_AREA_MAX_NUM 200

static int read_bin_yuv420p(const char *input_path, unsigned char *input_data, int width, int height, float channel) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
        printf("无法打开输入文件 %s: %s\n", input_path, strerror(errno));
        return -1;
    }
    if(fread(input_data, sizeof(char), width * height * channel, fp_src) != 0) {
        printf("read image success\n");
    }
    fclose(fp_src);
    return 0;
}

static int write_bin_yuv420p(const char *output_path, unsigned char *output_data, int width, int height, float channel) {
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL) {
        printf("无法打开输出文件 %s\n", output_path);
        return -1;
    }
    fwrite(output_data, sizeof(char), width * height * channel, fp_dst);
    fclose(fp_dst);
    return 0;
}

//yuv420p——api input yuv420p
int main() {
    int base_width = 1920;
    int base_height = 1088;
    int ksize = 5;
    int assigned_area_num = 5;
    int format = FORMAT_YUV420P;
    int dev_id = 0;
    float center_weight_scale = 0.01;
    const char* input_path = "image/420_1920x1088_input.bin";
    const char* output_path = "image/2105output_assigned_area.bin";
    bm_handle_t handle;
    bm_dev_request(&handle, dev_id);
    bmcv_rect assigned_area[ASSIGNED_AREA_MAX_NUM];
    bm_image img_i, img_o;
    int assigned_width[ASSIGNED_AREA_MAX_NUM];
    int assigned_height[ASSIGNED_AREA_MAX_NUM];
    int dis_x_max[ASSIGNED_AREA_MAX_NUM];
    int dis_y_max[ASSIGNED_AREA_MAX_NUM];
    int start_x[ASSIGNED_AREA_MAX_NUM];
    int start_y[ASSIGNED_AREA_MAX_NUM];

    for (int i = 0; i < assigned_area_num; i++) {
        int w = 1 + rand() % (500);
        int h = 1 + rand() % (500);
        assigned_width[i] = w > base_width ? base_width : w;
        assigned_height[i] = h > base_height ? base_height : h;
        dis_x_max[i] = base_width - assigned_width[i];
        dis_y_max[i] = base_height - assigned_height[i];
        start_x[i] = rand() % (dis_x_max[i] + 1);
        start_y[i] = rand() % (dis_y_max[i] + 1);
    }

    for (int i = 0; i < assigned_area_num; i++) {
        assigned_area[i].start_x = start_x[i];
        assigned_area[i].start_y = start_y[i];
        assigned_area[i].crop_w = assigned_width[i];
        assigned_area[i].crop_h = assigned_height[i];
    }
    unsigned char *input_data = (unsigned char*)malloc(base_width * base_height * 3 / 2);
    unsigned char *output_tpu = (unsigned char*)malloc(base_width * base_height * 3 / 2);
    read_bin_yuv420p(input_path, input_data, base_width, base_height, 1.5);
    bm_image_create(handle, base_height, base_width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &img_i, NULL);
    bm_image_create(handle, base_height, base_width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &img_o, NULL);
    bm_image_alloc_dev_mem(img_i, 2);
    bm_image_alloc_dev_mem(img_o, 2);
    unsigned char *input_addr[3] = {input_data, input_data + base_height * base_width, input_data + base_height * base_width * 5 / 4};
    bm_image_copy_host_to_device(img_i, (void **)(input_addr));
    bmcv_image_assigned_area_blur(handle, img_i, img_o, ksize, assigned_area_num, center_weight_scale, assigned_area);
    unsigned char *output_addr[3] = {output_tpu, output_tpu + base_height * base_width, output_tpu + base_height * base_width * 5 / 4};
    bm_image_copy_device_to_host(img_o, (void **)output_addr);
    write_bin_yuv420p(output_path, output_tpu, base_width, base_height, 1.5);
    bm_image_destroy(img_i);
    bm_image_destroy(img_o);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}

//yuv420p——api input gray
int main() {
    int base_width = 1920;
    int base_height = 1088;
    int ksize = 5;
    int assigned_area_num = 5;
    int dev_id = 0;
    float center_weight_scale = 0.01;
    const char* input_path = "image/420_1920x1088_input.bin";
    const char* output_path = "image/2105output_assigned_area.bin";
    bm_handle_t handle;
    bm_dev_request(&handle, dev_id);
    bmcv_rect assigned_area[ASSIGNED_AREA_MAX_NUM];
    bm_image img_i, img_o;
    int assigned_width[ASSIGNED_AREA_MAX_NUM];
    int assigned_height[ASSIGNED_AREA_MAX_NUM];
    int dis_x_max[ASSIGNED_AREA_MAX_NUM];
    int dis_y_max[ASSIGNED_AREA_MAX_NUM];
    int start_x[ASSIGNED_AREA_MAX_NUM];
    int start_y[ASSIGNED_AREA_MAX_NUM];

    for (int i = 0; i < assigned_area_num; i++) {
        int w = 1 + rand() % (500);
        int h = 1 + rand() % (500);
        assigned_width[i] = w > base_width ? base_width : w;
        assigned_height[i] = h > base_height ? base_height : h;
        dis_x_max[i] = base_width - assigned_width[i];
        dis_y_max[i] = base_height - assigned_height[i];
        start_x[i] = rand() % (dis_x_max[i] + 1);
        start_y[i] = rand() % (dis_y_max[i] + 1);
    }

    for (int i = 0; i < assigned_area_num; i++) {
        assigned_area[i].start_x = start_x[i];
        assigned_area[i].start_y = start_y[i];
        assigned_area[i].crop_w = assigned_width[i];
        assigned_area[i].crop_h = assigned_height[i];
    }
    unsigned char *input_data = (unsigned char*)malloc(base_width * base_height * 3 / 2);
    unsigned char *output_tpu = (unsigned char*)malloc(base_width * base_height * 3 / 2);
    read_bin_yuv420p(input_path, input_data, base_width, base_height, 1.5);
    bm_image_create(handle, base_height, base_width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &img_i, NULL);
    bm_image_create(handle, base_height, base_width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &img_o, NULL);
    bm_image_alloc_dev_mem(img_i, 2);
    bm_image_alloc_dev_mem(img_o, 2);
    unsigned char *input_addr[1] = {input_data};
    bm_image_copy_host_to_device(img_i, (void **)(input_addr));
    bm_image_copy_host_to_device(img_o, (void **)(input_addr));
    bmcv_image_assigned_area_blur(handle, img_i, img_o, ksize, assigned_area_num, center_weight_scale, assigned_area);
    memcpy(output_tpu, input_data, base_height * base_width * 3 / 2);
    unsigned char *output_addr[1] = {output_tpu};
    bm_image_copy_device_to_host(img_o, (void **)output_addr);
    write_bin_yuv420p(output_path, output_tpu, base_width, base_height, 1.5);
    bm_image_destroy(img_i);
    bm_image_destroy(img_o);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_axpy

该接口实现 F = A * X + Y，其中 A 是常数，大小为 n * c，F、X、Y 都是大小为 n * c * h * w 的矩阵。

**处理器型号支持：**

该接口支持 BM1684/BM1684X。

**接口形式：**

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

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t tensor_A
  输入参数。存放常数 A 的设备内存地址。

* bm_device_mem_t tensor_X
  输入参数。存放矩阵 X 的设备内存地址。

* bm_device_mem_t tensor_Y
  输入参数。存放矩阵 Y 的设备内存地址。

* bm_device_mem_t tensor_F
  输出参数。存放结果矩阵 F 的设备内存地址。

* int input_n
  输入参数。n 维度大小。

* int input_c
  输入参数。c 维度大小。

* int input_h
  输入参数。h 维度大小。

* int input_w
  输入参数。w 维度大小。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**代码示例：**

```c
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext.h"

#define N (10)
#define C 256 //(64 * 2 + (64 >> 1))
#define H 8
#define W 8
#define TENSOR_SIZE (N * C * H * W)

int main()
{
    bm_handle_t handle;
    bm_dev_request(&handle, 0);

    float* tensor_X = new float[TENSOR_SIZE];
    float* tensor_A = new float[N*C];
    float* tensor_Y = new float[TENSOR_SIZE];
    float* tensor_F = new float[TENSOR_SIZE];

    for (int idx = 0; idx < TENSOR_SIZE; idx++) {
        tensor_X[idx] = (float)idx - 5.0f;
        tensor_Y[idx] = (float)idx/3.0f - 8.2f;  //y
    }

    for (int idx = 0; idx < N * C; idx++) {
        tensor_A[idx] = (float)idx * 1.5f + 1.0f;
    }

    bmcv_image_axpy(handle, bm_mem_from_system((void *)tensor_A),
                    bm_mem_from_system((void *)tensor_X),
                    bm_mem_from_system((void *)tensor_Y),
                    bm_mem_from_system((void *)tensor_F),
                    N, C, H, W);

    delete []tensor_A;
    delete []tensor_X;
    delete []tensor_Y;
    delete []tensor_F;
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_base64_enc(dec)

base64 网络传输中常用的编码方式，利用64个常用字符来对6位二进制数编码。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_base64_enc(bm_handle_t handle,
            bm_device_mem_t src,
            bm_device_mem_t dst,
            unsigned long len[2]);

bm_status_t bmcv_base64_dec(bm_handle_t handle,
            bm_device_mem_t src,
            bm_device_mem_t dst,
            unsigned long len[2]);
```

**参数说明:**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_device_mem_t src
  输入参数。输入字符串所在地址，类型为bm_device_mem_t。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* bm_device_mem_t dst
  输入参数。输出字符串所在地址，类型为bm_device_mem_t。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* unsigned long len[2]
  输入参数。进行base64编码或解码的长度，单位是字节。其中len[0]代表输入长度，需要调用者给出。而len[1]为输出长度，由api计算后给出。

**返回值：**

* BM_SUCCESS: 成功
* 其他: 失败

**代码示例：**

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include "bmcv_api_ext.h"

static void test_base64_enc(int len, char *src, char *dst)
{
    bm_handle_t handle;
    unsigned long lenth[2];

    lenth[0] = (unsigned long)len;
    bm_dev_request(&handle, 0);
    bmcv_base64_enc(handle, bm_mem_from_system(src), bm_mem_from_system(dst), lenth);
    bm_dev_free(handle);
}

static void test_base64_dec(int len, char *src, char *dst)
{
    bm_handle_t handle;
    unsigned long lenth[2];

    lenth[0] = (unsigned long)len;
    bm_dev_request(&handle, 0);
    bmcv_base64_dec(handle, bm_mem_from_system(src), bm_mem_from_system(dst), lenth);
    bm_dev_free(handle);
}
int main()
{
    int original_len = (rand() % 134217728) + 1;
    int encoded_len = (original_len + 2) / 3 * 4;
    char* a = (char *)malloc((original_len + 3) * sizeof(char));
    char* b = (char *)malloc((encoded_len + 3) * sizeof(char));
    for (int j = 0; j < original_len; j++) {
        a[j] = (char)((rand() % 100) + 1);
    }

    test_base64_enc(original_len, a, b);
    test_base64_dec(encoded_len, b, a);

    free(a);
    free(b);
    return 0;
}
```

**注意事项：**

1、该 api 一次最多可对 128MB 的数据进行编解码，即参数 len 不可超过128MB。

2、同时支持传入地址类型为system或device。

3、encoded_len[1]在会给出输出长度，尤其是解码时根据输入的末尾计算需要去掉的位数

# bmcv_batch_topk

计算每个 db 中最大或最小的k个数，并返回index。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_batch_topk(
            bm_handle_t handle,
            bm_device_mem_t src_data_addr,
            bm_device_mem_t src_index_addr,
            bm_device_mem_t dst_data_addr,
            bm_device_mem_t dst_index_addr,
            bm_device_mem_t buffer_addr,
            bool src_index_valid,
            int k,
            int batch,
            int* per_batch_cnt,
            bool same_batch_cnt,
            int src_batch_stride,
            bool descending);
```

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_device_mem_t src_data_addr
  输入参数。input_data的设备地址信息。

* bm_device_mem_t src_index_addr
  输入参数。input_index的设备地址信息，当src_index_valid为true时，设置该参数。

* bm_device_mem_t dst_data_addr
  输出参数。output_data设备地址信息。

* bm_device_mem_t dst_index_addr
  输出参数。output_index设备信息

* bm_device_mem_t buffer_addr
  输入参数。缓冲区设备地址信息

* bool src_index_valid
  输入参数。如果为true， 则使用src_index，否则使用自动生成的index。

* int k
  输入参数。k的值。

* int batch
  输入参数。batch数量。

* int * per_batch_cnt
  输入参数。每个batch的数据数量。

* bool same_batch_cnt
  输入参数。判断每个batch数据是否相同。

* int src_batch_stride
  输入参数。两个batch之间的距离。

* bool descending
  输入参数。升序或者降序

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前仅支持float32类型数据。

**代码示例：**

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext.h"

int main()
{
    int batch_num = 10000;
    int k = batch_num / 10;
    int descending = rand() % 2;
    int batch = rand() % 20 + 1;
    int batch_stride = batch_num;
    bool bottom_index_valid = true;
    bm_handle_t handle;
    float* bottom_data = new float[batch * batch_stride * sizeof(float)];
    int* bottom_index = new int[batch * batch_stride];
    float* top_data = new float[batch * batch_stride * sizeof(float)];
    int* top_index = new int[batch * batch_stride];
    float* buffer = new float[3 * batch_stride * sizeof(float)];

    bm_dev_request(&handle, 0);

    for(int i = 0; i < batch; i++){
        for(int j = 0; j < batch_num; j++){
            bottom_data[i * batch_stride + j] = rand() % 10000 * 1.0f;
            bottom_index[i * batch_stride + j] = i * batch_stride + j;
        }
    }

    bmcv_batch_topk(handle, bm_mem_from_system((void*)bottom_data),
                    bm_mem_from_system((void*)bottom_index),
                    bm_mem_from_system((void*)top_data),
                    bm_mem_from_system((void*)top_index),
                    bm_mem_from_system((void*)buffer),
                    bottom_index_valid, k, batch,
                    &batch_num, true, batch_stride,
                    descending);

    delete [] bottom_data;
    delete [] bottom_index;
    delete [] top_data;
    delete [] top_index;
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_bayer2rgb

将bayerBG8或bayerRG8格式图像转成RGB Plannar格式。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_bayer2rgb(
            bm_handle_t handle,
            unsigned char* convd_kernel,
            bm_image input
            bm_image output);
```

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* unsigned char* convd_kernel
  输入参数。用于卷积计算的卷积核。

* bm_image input
  输入参数。输入bayer格式图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下输入格式:

| num | image_format |
|-----|--------------|
| 1   | FORMAT_BAYER |
| 2   | FORMAT_BAYER_RG8 |

该接口目前支持以下输出格式:

| num | image_format |
|-----|--------------|
| 1   | FORMAT_RGB_PLANAR |

目前支持以下 data_type:

| num | data_type |
|-----|-----------|

# bmcv_image_bayer2rgb

## 注意事项

1. input的格式目前支持bayerBG8或bayerRG8，bm_image_create步骤中bayerBG8创建为FORMAT_BAYER格式，bayerRG8创建为FORMAT_BAYER_RG8格式。

2. output的格式是rgb plannar，data_type均为uint8类型。

3. 该接口支持的尺寸范围是 2*2 ~ 8192*8192，且图像的宽高需要是偶数。

4. 如调用该接口的程序为多线程程序，需要在创建bm_image前和销毁bm_image后加线程锁。

## 代码示例

```c
#include "bmcv_api_ext.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>

#define KERNEL_SIZE 3 * 3 * 3 * 4 * 64
#define CONVD_MATRIX 12 * 9
const unsigned char convd_kernel_bg8[CONVD_MATRIX] = {1, 0, 1, 0, 0, 0, 1, 0, 1, //Rb
                                                      0, 0, 2, 0, 0, 0, 0, 0, 2, //Rg1
                                                      0, 0, 0, 0, 0, 0, 2, 0, 2, //Rg2
                                                      0, 0, 0, 0, 0, 0, 0, 0, 4, //Rr
                                                      4, 0, 0, 0, 0, 0, 0, 0, 0, //Bb
                                                      2, 0, 2, 0, 0, 0, 0, 0, 0, //Bg1
                                                      2, 0, 0, 0, 0, 0, 2, 0, 0, //Bg2
                                                      1, 0, 1, 0, 0, 0, 1, 0, 1, //Br
                                                      0, 1, 0, 1, 0, 1, 0, 1, 0, //Gb
                                                      0, 0, 0, 0, 0, 4, 0, 0, 0, //Gg1
                                                      0, 0, 0, 0, 0, 0, 0, 4, 0, //Gg2
                                                      0, 1, 0, 1, 0, 1, 0, 1, 0};//Gr

const unsigned char convd_kernel_rg8[CONVD_MATRIX] = {4, 0, 0, 0, 0, 0, 0, 0, 0, //Rr
                                                      2, 0, 2, 0, 0, 0, 0, 0, 0, //Rg1
                                                      2, 0, 0, 0, 0, 0, 2, 0, 0, //Rg2
                                                      1, 0, 1, 0, 0, 0, 1, 0, 1, //Rb
                                                      1, 0, 1, 0, 0, 0, 1, 0, 1, //Br
                                                      0, 0, 2, 0, 0, 0, 0, 0, 2, //Bg1
                                                      0, 0, 0, 2, 0, 2, 0, 0, 0, //Bg2
                                                      0, 0, 0, 0, 0, 0, 0, 0, 4, //Bb
                                                      1, 0, 1, 0, 0, 0, 1, 0, 1, //Gr
                                                      0, 0, 0, 0, 0, 4, 0, 0, 0, //Gg1
                                                      0, 0, 0, 0, 0, 0, 0, 4, 0, //Gg2
                                                      0, 1, 0, 1, 0, 1, 0, 1, 0};//Gb

static void readBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    unsigned char* input = (unsigned char*)malloc(width * height);
    unsigned char* output_tpu = (unsigned char*)malloc(width * height * 3);
    unsigned char kernel_data[KERNEL_SIZE] = {0};
    bm_handle_t handle;
    bm_image input_img;
    bm_image output_img;
    const char *src_name = "path/to/src";
    const char *dst_name = "path/to/dst";
    int src_type = 0;
    unsigned char* out_ptr[3] = {output_tpu, output_tpu + height * width, output_tpu + 2 * height * width};

    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input_img, NULL);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_img, NULL);
    bm_image_alloc_dev_mem(input_img, BMCV_HEAP_ANY);
    bm_image_alloc_dev_mem(output_img, BMCV_HEAP_ANY);

    for (int i = 0;i < height;i++) {
        for (int j = 0;j < width;j++) {
            input[i * width + j] = rand() % 255;
        }
    }

    for (int i = 0;i < 12;i++) {
        for (int j = 0;j < 9;j++) {
            if (src_type == 0) {
                kernel_data[i * 9 * 64 + 64 * j] = convd_kernel_bg8[i * 9 + j];
            } else {
                kernel_data[i * 9 * 64 + 64 * j] = convd_kernel_rg8[i * 9 + j];
            }
        }
    }

    readBin(src_name, input, height * width);
    bm_image_copy_host_to_device(input_img, (void**)&input);
    bmcv_image_bayer2rgb(handle, kernel_data, input_img, output_img);
    bm_image_copy_device_to_host(output_img, (void **)out_ptr);
    writeBin(dst_name, output_tpu, width * height * 3);

    bm_image_destroy(input_img);
    bm_image_destroy(output_img);
    free(input);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_bitwise_and

两张大小相同的图片对应像素值进行按位与操作。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_bitwise_and(
            bm_handle_t handle,
            bm_image input1,
            bm_image input2,
            bm_image output);
```

## 参数说明

* bm_handle_t handle

  输入参数。bm_handle句柄。

* bm_image input1

  输入参数。输入第一张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image input2

  输入参数。输入第二张图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output

  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

该接口目前支持以下image_format:

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

目前支持以下data_type:

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1、在调用bmcv_image_bitwise_and()之前必须确保输入的image内存已经申请。

2、input output的data_type，image_format必须相同。

## 代码示例

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}
```

# bmcv_image_bitwise_or

两张大小相同的图片对应像素值进行按位或操作。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_bitwise_or(
            bm_handle_t handle,
            bm_image input1,
            bm_image input2,
            bm_image output);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **bm_image input1**  
  输入参数。输入第一张图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image input2**  
  输入参数。输入第二张图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image output**  
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 格式支持

该接口目前支持以下 image_format:

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PACKED |
| 2   | FORMAT_BGR_PLANAR |
| 3   | FORMAT_RGB_PACKED |
| 4   | FORMAT_RGB_PLANAR |
| 5   | FORMAT_RGBP_SEPARATE |
| 6   | FORMAT_BGRP_SEPARATE |
| 7   | FORMAT_GRAY       |
| 8   | FORMAT_YUV420P    |
| 9   | FORMAT_YUV422P    |
| 10  | FORMAT_YUV444P    |
| 11  | FORMAT_NV12       |
| 12  | FORMAT_NV21       |
| 13  | FORMAT_NV16       |
| 14  | FORMAT_NV61       |
| 15  | FORMAT_NV24       |

目前支持以下 data_type:

| num | data_type            |
|-----|----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用 bmcv_image_bitwise_or() 之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format 必须相同。

## 代码示例

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input1_img, input2_img, output_img;
    unsigned char* input1 = (unsigned char*)malloc(width * height * channel);
    unsigned char* input2 = (unsigned char*)malloc(width * height * channel);
    unsigned char* output = (unsigned char*)malloc(width * height * channel);
    const char* src1_name = "path/to/src1";
    const char* src2_name = "path/to/src2";
    const char* dst_name = "path/to/dst";
    unsigned char* in1_ptr[3] = {input1, input1 + height * width, input1 + 2 * height * width};
    unsigned char* in2_ptr[3] = {input2, input2 + height * width, input2 + 2 * height * width};
    unsigned char* out_ptr[3] = {output, output + height * width, output + 2 * height * width};
    int img_size = height * width * 3;

    readBin(src1_name, input1, img_size);
    readBin(src2_name, input2, img_size);

    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input1_img);
    bm_image_alloc_dev_mem(input1_img);
    bm_image_copy_host_to_device(input1_img, (void **)in1_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input2_img);
    bm_image_alloc_dev_mem(input2_img);
    bm_image_copy_host_to_device(input2_img, (void **)in2_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_img);
    bm_image_alloc_dev_mem(output_img);
    bmcv_image_bitwise_or(handle, input1_img, input2_img, output_img);
    bm_image_copy_device_to_host(output_img, (void **)out_ptr);
    writeBin(dst_name, output, img_size);

    bm_image_destroy(input1_img);
    bm_image_destroy(input2_img);
    bm_image_destroy(output_img);
    bm_dev_free(handle);
    free(input1);
    free(input2);
    free(output);
    return 0;
}
```

# bmcv_image_bitwise_xor

两张大小相同的图片对应像素值进行按位异或操作。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_bitwise_xor(
            bm_handle_t handle,
            bm_image input1,
            bm_image input2,
            bm_image output);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **bm_image input1**  
  输入参数。输入第一张图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image input2**  
  输入参数。输入第二张图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* **bm_image output**  
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 格式支持

该接口目前支持以下 image_format:

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PACKED |
| 2   | FORMAT_BGR_PLANAR |
| 3   | FORMAT_RGB_PACKED |
| 4   | FORMAT_RGB_PLANAR |
| 5   | FORMAT_RGBP_SEPARATE |
| 6   | FORMAT_BGRP_SEPARATE |
| 7   | FORMAT_GRAY       |
| 8   | FORMAT_YUV420P    |
| 9   | FORMAT_YUV422P    |
| 10  | FORMAT_YUV444P    |
| 11  | FORMAT_NV12       |
| 12  | FORMAT_NV21       |
| 13  | FORMAT_NV16       |
| 14  | FORMAT_NV61       |

目前支持以下 data_type:

| num | data_type            |
|-----|----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用 bmcv_image_bitwise_xor() 之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format 必须相同。

| 15 | FORMAT_NV24 |
|----|-------------|

目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1. 在调用 bmcv_image_bitwise_xor() 之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format 必须相同。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input1_img, input2_img, output_img;
    unsigned char* input1 = (unsigned char*)malloc(width * height * channel);
    unsigned char* input2 = (unsigned char*)malloc(width * height * channel);
    unsigned char* output = (unsigned char*)malloc(width * height * channel);
    const char* src1_name = "path/to/src1";
    const char* src2_name = "path/to/src2";
    const char* dst_name = "path/to/dst";
    unsigned char* in1_ptr[3] = {input1, input1 + height * width, input1 + 2 * height * width};
    unsigned char* in2_ptr[3] = {input2, input2 + height * width, input2 + 2 * height * width};
    unsigned char* out_ptr[3] = {output, output + height * width, output + 2 * height * width};
    int img_size = height * width * 3;

    readBin(src1_name, input1, img_size);
    readBin(src2_name, input2, img_size);

    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input1_img);
    bm_image_alloc_dev_mem(input1_img);
    bm_image_copy_host_to_device(input1_img, (void **)in1_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input2_img);
    bm_image_alloc_dev_mem(input2_img);
    bm_image_copy_host_to_device(input2_img, (void **)in2_ptr);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_img);
    bm_image_alloc_dev_mem(output_img);
    bmcv_image_bitwise_xor(handle, input1_img, input2_img, output_img);
    bm_image_copy_device_to_host(output_img, (void **)out_ptr);
    writeBin(dst_name, output, img_size);

    bm_image_destroy(input1_img);
    bm_image_destroy(input2_img);
    bm_image_destroy(output_img);
    bm_dev_free(handle);
    free(input1);
    free(input2);
    free(output);
    return 0;
}
```

## bmcv_hist_balance

对图像进行直方图均衡化操作，提高图像的对比度。

**处理器型号支持：**

该接口支持 BM1684X。

**接口形式：**

```c
bm_status_t bmcv_hist_balance(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int H,
            int W);
```

**参数说明：**

- bm_handle_t handle
  输入参数。bm_handle 句柄

- bm_device_mem_t input
  输入参数。存放输入图像的 device 空间。其大小为 H * W * sizeof(uint8_t)。

- bm_device_mem_t output
  输出参数。存放输出图像的 device 空间。其大小为 H * W * sizeof(uint8_t)。

- int H
  输入参数。图像的高。

- int W
  输入参数。图像的宽。

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

**注意事项：**

1. 数据类型仅支持 uint8_t。
2. 支持的最小图像尺寸为 H = 1, W = 1。
3. 支持的最大图像尺寸为 H = 8192, W = 8192。

**示例代码**

```c
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext.h"

int main()
{
    int H = 1024;
    int W = 1024;
    uint8_t* input_addr = (uint8_t*)malloc(H * W * sizeof(uint8_t));
    uint8_t* output_addr = (uint8_t*)malloc(H * W * sizeof(uint8_t));
    bm_handle_t handle;
    bm_device_mem_t input, output;

    for (int i = 0; i < W * H; ++i) {
        input_addr[i] = (uint8_t)rand() % 256;
    }

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &input, H * W * sizeof(uint8_t));
    bm_malloc_device_byte(handle, &output, H * W * sizeof(uint8_t));

    bm_memcpy_s2d(handle, input, input_addr);
    bmcv_hist_balance(handle, input, output, H, W);
    bm_memcpy_d2s(handle, output_addr, output);

    free(input_addr);
    free(output_addr);
    bm_free_device(handle, input);
    bm_free_device(handle, output);
    bm_dev_free(handle);
    return 0;
}
```

## bmcv_calc_hist

### 直方图

**处理器型号支持：**

该接口支持 BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_calc_hist(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int C,
            int H,
            int W,
            const int *channels,
            int dims,
            const int *histSizes,
            const float *ranges,
            int inputDtype);
```

**参数说明：**

- bm_handle_t handle
  输入参数。bm_handle 句柄。

- bm_device_mem_t input
  输入参数。该 device memory 空间存储了输入数据，类型可以是 float32 或者 uint8，由参数 inputDtype 决定。其大小为 C*H*W*sizeof(Dtype)。

- bm_device_mem_t output
  输出参数。该 device memory 空间存储了输出结果，类型为 float，其大小为 histSizes[0]\*histSizes[1]\*……\*histSizes[n]\*sizeof(float)。

- int C
  输入参数。输入数据的通道数量。

- int H
  输入参数。输入数据每个通道的高度。

- int W
  输入参数。输入数据每个通道的宽度。

- const int *channels
  输入参数。需要计算直方图的 channel 列表，其长度为 dims，每个元素的值必须小于 C。

- int dims
  输入参数。输出的直方图维度，要求不大于 3。

- const int *histSizes
  输入参数。对应每个 channel 统计直方图的份数，其长度为 dims。

- const float *ranges
  输入参数。每个通道参与统计的范围，其长度为 2*dims。

- int inputDtype
  输入参数。输入数据的类型：0 表示 float，1 表示 uint8。

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int main()
{
    int H = 1024;
    int W = 1024;
    int C = 3;
    int dim = 3;
    int channels[3] = {0, 1, 2};
    int histSizes[3] = {32, 32, 32};
    float ranges[6] = {0, 256, 0, 256, 0, 256};
    int totalHists = 1;
    bm_handle_t handle;
    float *inputHost = new float[C * H * W];
    float *outputHost = new float[totalHists];
    bm_device_mem_t input, output;

    for (int i = 0; i < dim; ++i) {
        totalHists *= histSizes[i];
    }

    bm_dev_request(&handle, 0);

    for (int i = 0; i < C; ++i) {
        for (int j = 0; j < H * W; ++j) {
            inputHost[i * H * W + j] = (float)(rand() % 256);
        }
    }

    bm_malloc_device_byte(handle, &input, C * H * W * sizeof(float));
    bm_memcpy_s2d(handle, input, inputHost);
    bm_malloc_device_byte(handle, &output, totalHists * sizeof(float));
    bmcv_calc_hist(handle, input, output, C, H, W, channels, dim, histSizes, ranges, 0);
    bm_memcpy_d2s(handle, outputHost, output);

    bm_free_device(handle, input);
    bm_free_device(handle, output);
    bm_dev_free(handle);
    delete[] inputHost;
    delete[] outputHost;
    return 0;
}
```

### 带权重的直方图

**处理器型号支持：**

该接口支持 BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_calc_hist_with_weight(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            const float *weight,
            int C,
            int H,
            int W,
            const int *channels,
            int dims,
            const int *histSizes,
            const float *ranges,
            int inputDtype);
```

**参数说明：**

- bm_handle_t handle
  输入参数。bm_handle 句柄。

- bm_device_mem_t input
  输入参数。该 device memory 空间存储了输入数据，其大小为 C*H*W*sizeof(Dtype)。

- bm_device_mem_t output
  输出参数。该 device memory 空间存储了输出结果，类型为 float，其大小为 histSizes[0]\*histSizes[1]\*……\*histSizes[n]\*sizeof(float)。

- const float *weight
  输入参数。channel 内部每个元素在统计直方图时的权重，其大小为 H*W*sizeof(float)，如果所有值全为 1 则与普通直方图功能相同。

- int C
  输入参数。输入数据的通道数量。

- int H
  输入参数。输入数据每个通道的高度。

- int W
  输入参数。输入数据每个通道的宽度。

- const int *channels
  输入参数。需要计算直方图的 channel 列表，其长度为 dims，每个元素的值必须小于 C。

- int dims
  输入参数。输出的直方图维度，要求不大于 3。

- const int *histSizes
  输入参数。对应每个 channel 统计直方图的份数，其长度为 dims。

- const float *ranges
  输入参数。每个通道参与统计的范围，其长度为 2*dims。

- int inputDtype
  输入参数。输入数据的类型：0 表示 float，1 表示 uint8。

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

## bmcv_image_canny

边缘检测 Canny 算子。

**处理器型号支持：**

该接口支持 BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_canny(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            float threshold1,
            float threshold2,
            int aperture_size = 3,
            bool l2gradient = false);
```

**参数说明：**

- bm_handle_t handle
  输入参数。bm_handle 句柄。

- bm_image input
  输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

- bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

- float threshold1
  滞后处理过程中的第一个阈值。

- float threshold2
  滞后处理过程中的第二个阈值。

- int aperture_size = 3
  Sobel 核的大小，目前仅支持 3。

- bool l2gradient = false
  是否使用 L2 范数来求图像梯度，默认值为 false。

**返回值说明：**

- BM_SUCCESS: 成功
- 其他: 失败

## 格式支持

该接口目前支持以下 image_format：

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1   | FORMAT_GRAY       | FORMAT_GRAY       |

目前支持以下 data_type：

| num | data_type           |
|-----|-------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用该接口之前必须确保输入的 image 内存已经申请
2. input output 的 data_type，image_format必须相同
3. 目前支持图像的最大width为2048
4. 输入图像的stride必须和width一致

## 代码示例

```c
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input, output;
    float low_thresh = 100;
    float high_thresh = 200;
    unsigned char * src_data = (unsigned char*)malloc(channel * width * height * sizeof(unsigned char));
    unsigned char * res_data = (unsigned char*)malloc(channel * width * height * sizeof(unsigned char));
    const char* src_name = "path/to/src";
    const char* dst_name = "path/to/dst";

    readBin(src_name, src_data, channel * width * height);
    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void **)&src_data);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_canny(handle, input, output, low_thresh, high_thresh);
    bm_image_copy_device_to_host(output, (void **)&res_data);
    writeBin(dst_name, res_data, channel * width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_cluster

谱聚类。内部通过依次调用：bmcv_cos_similarity、bmcv_matrix_prune、bmcv_lap_matrix、bmcv_qr、bmcv_knn 接口实现谱聚类。

## 处理器型号支持

该接口支持 BM1684X。

## 接口形式

```c
bm_status_t bmcv_cluster(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int row,
            int col,
            float p,
            int min_num_spks,
            int max_num_spks,
            int user_num_spks,
            int weight_mode_KNN,
            int num_iter_KNN);
```

## 参数说明

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_image input
  输入参数。存放输入矩阵，其大小为 row * col * sizeof(float32)。

* bm_image output
  输出参数。存放 KNN 结果标签，其大小为 row * sizeof(int)。

* int row
  输入参数。输入矩阵的行数。

* int col
  输入参数。输入矩阵的列数。

* float p
  输入参数。用于剪枝步骤中的比例参数，控制如何减少相似性矩阵中的连接。

* int min_num_spks
  输入参数。最小的聚类数。

* int max_num_spks
  输入参数。最大的聚类数。

* int user_num_spks
  输入参数。指定要使用的特征向量数量，可用于直接控制输出的聚类数。如果未指定，则根据数据动态计算。

* int weight_mode_KNN
  在SciPy库中，K-means算法的质心初始化方法, 0 表示 CONST_WEIGHT，1 表示 POISSON_CPP，2 表示 MT19937_CPP。默认使用 CONST_WEIGHT。

* int num_iter_KNN
  输入参数。KNN 算法的迭代次数。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

1. 目前该接口只支持矩阵的数据类型为float。

## 代码示例

```c
#include "bmcv_api.h"
#include "test_misc.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main()
{
    int row = 128;
    int col = 128;
    float p = 0.01;
    int min_num_spks = 2;
    int max_num_spks = 8;
    int num_iter_KNN = 2;
    int weight_mode_KNN = 0;
    int user_num_spks = -1;
    float* input_data = (float *)malloc(row * col * sizeof(float));
    int* output_data = (int *)malloc(row * max_num_spks * sizeof(int));
    bm_handle_t handle;
    bm_device_mem_t input, output;

    bm_dev_request(&handle, 0);

    for (int i = 0; i < row * col; ++i) {
        input_data[i] = (float)rand() / RAND_MAX;
    }

    bm_malloc_device_byte(handle, &input, sizeof(float) * row * col);
    bm_malloc_device_byte(handle, &output, sizeof(float) * row * max_num_spks);
    bm_memcpy_s2d(handle, input, input_data);
    bmcv_cluster(handle, input, output, row, col, p, min_num_spks, max_num_spks,
                user_num_spks, weight_mode_KNN, num_iter_KNN);
    bm_memcpy_d2s(handle, output_data, output);

    bm_free_device(handle, input);
    bm_free_device(handle, output);
    free(input_data);
    free(output_data);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_cmulp

该接口实现复数乘法运算，运算公式如下：

outputReal + outputImag × i = (inputReal + inputImag × i) × (pointReal + pointImag × i)

outputReal = inputReal × pointReal - inputImag × pointImag

outputImag = inputReal × pointImag + inputImag × pointReal

其中，i 是虚数单位，满足公式 i² = -1。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c++
bm_status_t bmcv_cmulp(
            bm_handle_t handle,
            bm_device_mem_t inputReal,
            bm_device_mem_t inputImag,
            bm_device_mem_t pointReal,
            bm_device_mem_t pointImag,
            bm_device_mem_t outputReal,
            bm_device_mem_t outputImag,
            int batch,
            int len);
```

## 输入参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t inputReal
  输入参数。存放输入实部的 device 地址。

* bm_device_mem_t inputImag
  输入参数。存放输入虚部的 device 地址。

* bm_device_mem_t pointReal
  输入参数。存放另一个输入实部的 device 地址。

* bm_device_mem_t pointImag
  输入参数。存放另一个输入虚部的 device 地址。

* bm_device_mem_t outputReal
  输出参数。存放输出实部的 device 地址。

* bm_device_mem_t outputImag
  输出参数。存放输出虚部的 device 地址。

* int batch
  输入参数。batch 的数量。

* int len
  输入参数。一个 batch 中复数的数量。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 数据类型仅支持 float。

## 示例代码

```c++
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>

int main()
{
    int L = 1 + rand() % 4096;
    int batch = 1 + rand() % 1980;
    float *XRHost = new float[L * batch];
    float *XIHost = new float[L * batch];
    float *PRHost = new float[L];
    float *PIHost = new float[L];
    float *YRHost = new float[L * batch];
    float *YIHost = new float[L * batch];
    bm_handle_t handle;
    bm_device_mem_t XRDev, XIDev, PRDev, PIDev, YRDev, YIDev;

    for (int i = 0; i < L * batch; ++i) {
        XRHost[i] = rand() % 5 - 2;
        XIHost[i] = rand() % 5 - 2;
    }
    for (int i = 0; i < L; ++i) {
        PRHost[i] = rand() % 5 - 2;
        PIHost[i] = rand() % 5 - 2;
    }

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &XRDev, L * batch * sizeof(float));
    bm_malloc_device_byte(handle, &XIDev, L * batch * sizeof(float));
    bm_malloc_device_byte(handle, &PRDev, L * sizeof(float));
    bm_malloc_device_byte(handle, &PIDev, L * sizeof(float));
    bm_malloc_device_byte(handle, &YRDev, L * batch * sizeof(float));
    bm_malloc_device_byte(handle, &YIDev, L * batch * sizeof(float));
    bm_memcpy_s2d(handle, XRDev, XRHost);
    bm_memcpy_s2d(handle, XIDev, XIHost);
    bm_memcpy_s2d(handle, PRDev, PRHost);
    bm_memcpy_s2d(handle, PIDev, PIHost);

    bmcv_cmulp(handle, XRDev, XIDev, PRDev, PIDev, YRDev, YIDev, batch, L);
    bm_memcpy_d2s(handle, YRHost, YRDev);
    bm_memcpy_d2s(handle, YIHost, YIDev);

    delete[] XRHost;
    delete[] XIHost;
    delete[] PRHost;
    delete[] PIHost;
    delete[] YRHost;
    delete[] YIHost;
    bm_free_device(handle, XRDev);
    bm_free_device(handle, XIDev);
    bm_free_device(handle, YRDev);
    bm_free_device(handle, YIDev);
    bm_free_device(handle, PRDev);
    bm_free_device(handle, PIDev);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_convert_to

该接口用于实现图像像素线性变化，具体数据关系可用如下公式表示：

$$y=kx+b$$

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_convert_to (
            bm_handle_t handle,
            int input_num,
            bmcv_convert_to_attr convert_to_attr,
            bm_image* input,
            bm_image* output
);
```

**输入参数说明:**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* int input_num
  输入参数。输入图片数，如果 input_num > 1, 那么多个输入图像必须是连续存储的（可以使用 bm_image_alloc_contiguous_mem 给多张图申请连续空间）。

* bmcv_convert_to_attr convert_to_attr
  输入参数。每张图片对应的配置参数。

* bm_image* input
  输入参数。输入 bm_image。每个 bm_image 外部需要调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存,或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image* output
  输出参数。输出 bm_image。每个 bm_image 外部需要调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明:**

```c
typedef struct bmcv_convert_to_attr_s{
        float alpha_0;
        float beta_0;
        float alpha_1;
        float beta_1;
        float alpha_2;
        float beta_2;
} bmcv_convert_to_attr;
```

* alpha_0 描述了第 0 个 channel 进行线性变换的系数
* beta_0 描述了第 0 个 channel 进行线性变换的偏移
* alpha_1 描述了第 1 个 channel 进行线性变换的系数
* beta_1 描述了第 1 个 channel 进行线性变换的偏移
* alpha_2 描述了第 2 个 channel 进行线性变换的系数
* beta_2 描述了第 2 个 channel 进行线性变换的偏移

**代码示例:**

```c
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int image_num = 4, image_channel = 3;
    int image_w = 1920, image_h = 1080;
    bm_handle_t handle;
    bm_image input_images[4], output_images[4];
    bmcv_convert_to_attr convert_to_attr;
    convert_to_attr.alpha_0 = 1;
    convert_to_attr.beta_0 = 0;
    convert_to_attr.alpha_1 = 1;
    convert_to_attr.beta_1 = 0;
    convert_to_attr.alpha_2 = 1;
    convert_to_attr.beta_2 = 0;
    int img_size = image_w * image_h * image_channel;
    int image_len = image_num * image_channel * image_w * image_h;
    unsigned char* img_data = (unsigned char*)malloc(image_len * sizeof(unsigned char));
    unsigned char *res_data = (unsigned char*)malloc(image_len * sizeof(unsigned char));
    const char *src_names[4] = {"path/to/src0", "path/to/src1", "path/to/src2", "path/to/src3"};
    const char *dst_names[4] = {"path/to/dst0", "path/to/dst1", "path/to/dst2", "path/to/dst3"};

    for(int i = 0; i < image_num; i++){
        readBin(src_names[i], img_data + i * img_size, img_size);
    }

    bm_dev_request(&handle, 0);
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input_images[img_idx]);
    }

    bm_image_alloc_contiguous_mem(image_num, input_images, BMCV_IMAGE_FOR_IN);
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        unsigned char *input_img_data = img_data + img_size * img_idx;
        bm_image_copy_host_to_device(input_images[img_idx], (void **)&input_img_data);
    }

    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_images[img_idx]);
    }
    bm_image_alloc_contiguous_mem(image_num, output_images, BMCV_IMAGE_FOR_OUT);
    bmcv_image_convert_to(handle, image_num, convert_to_attr, input_images, output_images);
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        unsigned char *res_img_data = res_data + img_size * img_idx;
        bm_image_copy_device_to_host(output_images[img_idx], (void **)&res_img_data);
        writeBin(dst_names[img_idx], res_img_data, img_size);
    }

    bm_image_free_contiguous_mem(image_num, input_images);
    bm_image_free_contiguous_mem(image_num, output_images);
    for(int i = 0; i < image_num; i++) {
        bm_image_destroy(input_images[i]);
        bm_image_destroy(output_images[i]);
    }
    bm_dev_free(handle);
    free(img_data);
    free(res_data);
    return 0;
}
```

**格式支持:**

1. 该接口支持下列 image_format 的转化：
* FORMAT_BGR_PLANAR ——> FORMAT_BGR_PLANAR
* FORMAT_RGB_PLANAR ——> FORMAT_RGB_PLANAR
* FORMAT_GRAY ——> FORMAT_GRAY

2. 该接口支持下列情形data type之间的转换：

bm1684支持：
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_FLOAT32
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_1N_BYTE
* DATA_TYPE_EXT_1N_BYTE_SIGNED ——> DATA_TYPE_EXT_1N_BYTE_SIGNED
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_1N_BYTE_SIGNED
* DATA_TYPE_EXT_FLOAT32 ——> DATA_TYPE_EXT_FLOAT32
* DATA_TYPE_EXT_4N_BYTE ——> DATA_TYPE_EXT_FLOAT32

bm1684x支持：
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_FLOAT32
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_1N_BYTE
* DATA_TYPE_EXT_1N_BYTE_SIGNED ——> DATA_TYPE_EXT_1N_BYTE_SIGNED
* DATA_TYPE_EXT_1N_BYTE ——> DATA_TYPE_EXT_1N_BYTE_SIGNED
* DATA_TYPE_EXT_FLOAT32 ——> DATA_TYPE_EXT_FLOAT32

**注意事项:**

1. 在调用 bmcv_image_convert_to()之前必须确保输入的 image 内存已经申请。
2. 输入的各个 image 的宽、高以及 data_type、image_format 必须相同。
3. 输出的各个 image 的宽、高以及 data_type、image_format 必须相同。
4. 输入 image 宽、高必须等于输出 image 宽高。
5. image_num 必须大于 0。
6. 输出 image 的 stride 必须等于 width。
7. 输入 image 的 stride 必须大于等于 width。
8. bm1684支持最大尺寸为2048*2048，最小尺寸为16*16，当 image format 为 DATA_TYPE_EXT_4N_BYTE 时，w * h 不应大于 1024 * 1024。
9. bm1684x支持最小尺寸为16*16, 当input data_type 为 DATA_TYPE_EXT_1N_BYTE_SIGNED 或 DATA_TYPE_EXT_FLOAT32 时 ，支持最大尺寸为4096*4096，当input data_type 为 DATA_TYPE_EXT_1N_BYTE 时，支持最大尺寸为8192*8192。

# bmcv_image_copy_to

该接口实现将一幅图像拷贝到目的图像的对应内存区域。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_copy_to(
            bm_handle_t handle,
            bmcv_copy_to_atrr_t copy_to_attr,
            bm_image input,
            bm_image output);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bmcv_copy_to_atrr_t copy_to_attr
  输入参数。api 所对应的属性配置。

* bm_image input
  输入参数。输入 bm_image，bm_image 需要外部调用 bmcv_image _create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明：**

```c
typedef struct bmcv_copy_to_atrr_s {
    int           start_x;
    int           start_y;
    unsigned char padding_r;
    unsigned char padding_g;
    unsigned char padding_b;
    int if_padding;
} bmcv_copy_to_atrr_t;
```

* padding_b 表示当 input 的图像要小于输出图像的情况下，多出来的图像 b 通道上被填充的值。
* padding_r 表示当 input 的图像要小于输出图像的情况下，多出来的图像 r 通道上被填充的值。
* padding_g 表示当 input 的图像要小于输出图像的情况下，多出来的图像 g 通道上被填充的值。
* start_x 描述了 copy_to 拷贝到输出图像所在的起始横坐标。
* start_y 描述了 copy_to 拷贝到输出图像所在的起始纵坐标。
* if_padding 表示当 input 的图像要小于输出图像的情况下，是否需要对多余的图像区域填充特定颜色，0表示不需要，1表示需要。当该值填0时，padding_r，padding_g，padding_b 的设置将无效

## 格式支持

bm1684支持以下 image_format 和 data_type 的组合：

| num | image_format       | data_type               |
|-----|--------------------|-------------------------|
| 1   | FORMAT_BGR_PACKED  | DATA_TYPE_EXT_FLOAT32   |
| 2   | FORMAT_BGR_PLANAR  | DATA_TYPE_EXT_FLOAT32   |
| 3   | FORMAT_BGR_PACKED  | DATA_TYPE_EXT_1N_BYTE   |
| 4   | FORMAT_BGR_PLANAR  | DATA_TYPE_EXT_1N_BYTE   |
| 5   | FORMAT_BGR_PLANAR  | DATA_TYPE_EXT_4N_BYTE   |
| 7   | FORMAT_RGB_PACKED  | DATA_TYPE_EXT_FLOAT32   |
| 8   | FORMAT_RGB_PLANAR  | DATA_TYPE_EXT_FLOAT32   |
| 9   | FORMAT_RGB_PACKED  | DATA_TYPE_EXT_1N_BYTE   |
| 10  | FORMAT_RGB_PLANAR  | DATA_TYPE_EXT_1N_BYTE   |
| 11  | FORMAT_RGB_PLANAR  | DATA_TYPE_EXT_4N_BYTE   |
| 12  | FORMAT_GRAY        | DATA_TYPE_EXT_1N_BYTE   |

bm1684x支持以下数据输入、输出类型：

| num | input data type       | output data type          |
|-----|-----------------------|---------------------------|
| 1   |                       | DATA_TYPE_EXT_FLOAT32     |
| 2   |                       | DATA_TYPE_EXT_1N_BYTE     |
| 3   | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4   |                       | DATA_TYPE_EXT_FP16        |
| 5   |                       | DATA_TYPE_EXT_BF16        |
| 6   | DATA_TYPE_EXT_FLOAT32 | DATA_TYPE_EXT_FLOAT32     |

输入和输出支持的色彩格式为：

| num | image_format          |
|-----|-----------------------|
| 1   | FORMAT_YUV420P        |
| 2   | FORMAT_YUV444P        |
| 3   | FORMAT_NV12           |
| 4   | FORMAT_NV21           |
| 5   | FORMAT_RGB_PLANAR     |
| 6   | FORMAT_BGR_PLANAR     |
| 7   | FORMAT_RGB_PACKED     |
| 8   | FORMAT_BGR_PACKED     |
| 9   | FORMAT_RGBP_SEPARATE  |
| 10  | FORMAT_BGRP_SEPARATE  |
| 11  | FORMAT_GRAY           |

## 注意事项

1. 在调用 bmcv_image_copy_to()之前必须确保输入的 image 内存已经申请。
2. bm1684中的input output 的 data_type，image_format 必须相同。
3. 为了避免内存越界，输入图像width + start_x 必须小于等于输出图像width stride。

## 代码示例

```c
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "bmcv_api_ext.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 4, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 4, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int in_w = 400;
    int in_h = 400;
    int out_w = 800;
    int out_h = 800;
    int dev_id = 0;
    int image_n = 1;
    bm_handle_t handle;
    bmcv_copy_to_atrr_t copy_to_attr;
    bm_image input, output;
    float* src_data = (float *)malloc(image_n * channel * in_w * in_h * sizeof(float));
    float* res_data = (float *)malloc(image_n * channel * out_w * out_h * sizeof(float));
    const char* src_name = "path/to/src";
    const char* dst_name = "path/to/dst";

    bm_dev_request(&handle, dev_id);
    readBin(src_name, (unsigned char*)src_data, channel * in_w * in_h);

    copy_to_attr.start_x = 200;
    copy_to_attr.start_y = 200;
    copy_to_attr.padding_r = 0;
    copy_to_attr.padding_g = 0;
    copy_to_attr.padding_b = 0;
    copy_to_attr.if_padding = 1;

    bm_image_create(handle, in_h, in_w, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_FLOAT32, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void **)&src_data);
    bm_image_create(handle, out_h, out_w, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_FLOAT32, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_copy_to(handle, copy_to_attr, input, output);
    bm_image_copy_device_to_host(output, (void **)&res_data);
    writeBin(dst_name, (unsigned char*)res_data, channel * out_w * out_h);

    bm_image_destroy(input);
    bm_image_destroy(output);
    free(src_data);
    free(res_data);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_cos_similarity

对输入矩阵的每行元素进行规范化（除以l2范数），随后计算规范化矩阵和其转置矩阵的点积，得到余弦相似度矩阵，最后将相似度矩阵元素调整至0～1的范围内。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_cos_similarity(
            bm_handle_t handle,
            bm_device_mem_t in_global,
            bm_device_mem_t norm_global,
            bm_device_mem_t out_global,
            int vec_num,
            int vec_dims);
```

## 参数说明

* bm_handle_t handle

  输入参数。 bm_handle 句柄。

* bm_device_mem_t in_global

  输入参数。存放输入数据的设备内存地址。

* bm_device_mem_t norm_global

  输入参数。暂存规范化矩阵的设备内存地址。

* bm_device_mem_t out_global

  输出参数。存放输出数据的设备内存地址。

* int vec_num

  输入参数。数据数量，对应输入矩阵的行数。

* int vec_dims

  输入参数。数据维度数，对应输入矩阵的列数。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 数据类型支持

输入数据目前支持以下 data_type:

| num | data_type              |
|-----|------------------------|
| 1   | DATA_TYPE_EXT_FLOAT32  |

输出数据目前支持以下 data_type:

| num | data_type              |
|-----|------------------------|
| 1   | DATA_TYPE_EXT_FLOAT32  |

## 注意事项

1. 在调用该接口之前必须确保所用设备内存已经申请。
2. 该接口支持的输入矩阵列数为256，矩阵行数范围为8-6000。

## 代码示例

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <float.h>

float random_float(float min, float max) {
    return min + ((float)rand() / RAND_MAX) * (max - min);
}
int main()
{
    int vec_num = 2614;
    int vec_dims = 256;
    bm_handle_t handle;
    bm_dev_request(&handle, 0);
    float* output_tpu = (float*)malloc(vec_num * vec_num * sizeof(float));
    float* input_data = (float*)malloc(vec_num * vec_dims * sizeof(float));
    bm_device_mem_t in_global, norm_global, out_global;

    for (int i = 0; i < vec_num; ++i) {
        for (int j = 0; j < vec_dims; ++j) {
            input_data[i * vec_dims + j] = random_float(-100.0f, 300.0f);
        }
    }

    bm_malloc_device_byte(handle, &in_global, sizeof(float) * vec_num * vec_dims);
    bm_malloc_device_byte(handle, &norm_global, sizeof(float) * vec_num * vec_dims);
    bm_malloc_device_byte(handle, &out_global, sizeof(float) * vec_num * vec_num);
    bm_memcpy_s2d(handle, in_global, bm_mem_get_system_addr(bm_mem_from_system(input_data)));
    bmcv_cos_similarity(handle, in_global, norm_global, out_global, vec_num, vec_dims);
    bm_memcpy_d2s(handle, bm_mem_get_system_addr(bm_mem_from_system(output_tpu)), out_global);

    bm_free_device(handle, in_global);
    bm_free_device(handle, norm_global);
    bm_free_device(handle, out_global);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_crop

该接口实现从一幅原图中 crop 出若干个小图。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_crop(
            bm_handle_t handle,
            int crop_num,
            bmcv_rect_t* rects,
            bm_image input,
            bm_image* output);
```

## 参数说明

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* int crop_num
  输入参数。需要 crop 小图的数量，既是指针 rects 所指向内容的长度，也是输出 bm_image 的数量。

* bmcv_rect_t* rects
  输入参数。表示crop相关的信息，包括起始坐标、crop宽高等，具体内容参考下边的数据类型说明。该指针指向了若干个 crop 框的信息，框的个数由 crop_num 决定。

* bm_image input
  输入参数。输入的 bm_image，bm_image 需要外部调用 bmcv_image _create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image* output
  输出参数。输出 bm_image 的指针，其数量即为 crop_num。bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

## 返回值说明

* BM_SUCCESS: 成功
* 其他:失败

## 数据类型说明

```c
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

## 格式支持

crop 目前支持以下 image_format:

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PACKED |
| 2   | FORMAT_BGR_PLANAR |
| 3   | FORMAT_RGB_PACKED |
| 4   | FORMAT_RGB_PLANAR |
| 5   | FORMAT_GRAY       |

bm1684 crop 目前支持以下 data_type:

| num | data_type                    |
|-----|------------------------------|
| 1   | DATA_TYPE_EXT_FLOAT32        |
| 2   | DATA_TYPE_EXT_1N_BYTE        |
| 3   | DATA_TYPE_EXT_1N_BYTE_SIGNED |

bm1684x crop 目前支持以下data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1、在调用 bmcv_image_crop()之前必须确保输入的 image 内存已经申请。

2、input output 的 data_type，image_format必须相同。

3、为了避免内存越界, start_x + crop_w 必须小于等于输入图像的 width， start_y + crop_h 必须小于等于输入图像的 height。

## 代码示例

```c
#include <cfloat>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <math.h>
#include <string.h>
#include <vector>
#include "bmcv_api.h"
#include "test_misc.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int in_w = 1024;
    int in_h = 1024;
    int out_w = 64;
    int out_h = 64;
    int dev_id = 0;
    bm_handle_t handle;
    bmcv_rect_t crop_attr;
    bm_image input, output;
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";
    unsigned char* src_data = new unsigned char[channel * in_w * in_h];
    unsigned char* res_data = new unsigned char[channel * out_w * out_h];

    bm_dev_request(&handle, dev_id);
    readBin(input_path, src_data, channel * in_w * in_h);

    crop_attr.start_x = 0;
    crop_attr.start_y = 0;
    crop_attr.crop_w = 50;
    crop_attr.crop_h = 50;

    bm_image_create(handle, in_h, in_w, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void **)&src_data);
    bm_image_create(handle, out_h, out_w, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_crop(handle, 1, &crop_attr, input, &output);
    bm_image_copy_device_to_host(output, (void **)&res_data);
    writeBin(output_path, res_data, channel * out_w * out_h);

    bm_image_destroy(input);
    bm_image_destroy(output);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    return 0;
}
```

# bmcv_image_csc_convert_to

该 API 可以实现对多张图片的 crop、color-space-convert、resize、padding、convert_to及其任意若干个功能的组合。

```c
bm_status_t bmcv_image_csc_convert_to(
            bm_handle_t handle,
            int in_img_num,
            bm_image* input,
            bm_image* output,
            int* crop_num_vec = NULL,
            bmcv_rect_t* crop_rect = NULL,
            bmcv_padding_atrr_t* padding_attr = NULL,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR,
            csc_type_t csc_type = CSC_MAX_ENUM,
            csc_matrix_t* matrix = NULL,
            bmcv_convert_to_attr* convert_to_attr);
```

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 传入参数说明

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* int in_img_num
  输入参数。输入 bm_image 数量。

* bm_image* input
  输入参数。输入 bm_image 对象指针，其指向空间的长度由 in_img_num 决定。

* bm_image* output
  输出参数。输出 bm_image 对象指针，其指向空间的长度由 in_img_num 和 crop_num_vec 共同决定，即所有输入图片 crop 数量之和。

* int* crop_num_vec = NULL
  输入参数。该指针指向对每张输入图片进行 crop 的数量，其指向空间的长度由 in_img_num 决定，如果不使用 crop 功能可填 NULL。

* bmcv_rect_t * crop_rect = NULL
  输入参数。具体格式定义如下：

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

每个输出 bm_image 对象所对应的在输入图像上 crop 的参数，包括起始点x坐标、起始点y坐标、crop图像的宽度以及crop图像的高度。图像左上顶点作为坐标原点。如果不使用 crop 功能可填 NULL。

* bmcv_padding_atrr_t*  padding_attr = NULL
  输入参数。所有 crop 的目标小图在 dst image 中的位置信息以及要 padding 的各通道像素值，若不使用 padding 功能则设置为 NULL。

```c
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

* bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR
  输入参数。resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR 和 BMCV_INTER_BICUBIC三种，默认情况下是双线性差值。

  - bm1684 支持 : BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。
  - bm1684x 支持: BMCV_INTER_NEAREST， BMCV_INTER_LINEAR。

* csc_type_t csc_type = CSC_MAX_ENUM
  输入参数。color space convert 参数类型选择，填 CSC_MAX_ENUM 则使用默认值，默认为 CSC_YCbCr2RGB_BT601 或者 CSC_RGB2YCbCr_BT601，支持的类型包括：

| 类型                       |
|----------------------------|
| CSC_YCbCr2RGB_BT601        |
| CSC_YPbPr2RGB_BT601        |
| CSC_RGB2YCbCr_BT601        |
| CSC_YCbCr2RGB_BT709        |
| CSC_RGB2YCbCr_BT709        |
| CSC_RGB2YPbPr_BT601        |
| CSC_YPbPr2RGB_BT709        |
| CSC_RGB2YPbPr_BT709        |
| CSC_USER_DEFINED_MATRIX    |
| CSC_MAX_ENUM               |

* csc_matrix_t* matrix = NULL
输入参数。如果 csc_type 选择 CSC_USER_DEFINED_MATRIX，则需要传入系数矩阵，格式如下：

```c
typedef struct {
    int csc_coe00;
    int csc_coe01;
    int csc_coe02;
    int csc_add0;
    int csc_coe10;
    int csc_coe11;
    int csc_coe12;
    int csc_add1;
    int csc_coe20;
    int csc_coe21;
    int csc_coe22;
    int csc_add2;
} __attribute__((packed)) csc_matrix_t;
```

* bmcv_convert_to_attr* convert_to_attr
输入参数。线性变换系数：

```c
typedef struct bmcv_convert_to_attr_s{
        float alpha_0;
        float beta_0;
        float alpha_1;
        float beta_1;
        float alpha_2;
        float beta_2;
} bmcv_convert_to_attr;
```

* alpha_0 描述了第 0 个 channel 进行线性变换的系数
* beta_0 描述了第 0 个 channel 进行线性变换的偏移
* alpha_1 描述了第 1 个 channel 进行线性变换的系数
* beta_1 描述了第 1 个 channel 进行线性变换的偏移
* alpha_2 描述了第 2 个 channel 进行线性变换的系数
* beta_2 描述了第 2 个 channel 进行线性变换的偏移

## 返回值说明

- BM_SUCCESS: 成功
- 其他: 失败

## 注意事项

### bm1684x支持的要求

1. 支持数据类型为：

| num | input data_type       | output data_type             |
|-----|-----------------------|------------------------------|
| 1   |                       | DATA_TYPE_EXT_FLOAT32        |
| 2   |                       | DATA_TYPE_EXT_1N_BYTE        |
| 3   | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4   |                       | DATA_TYPE_EXT_FP16           |
| 5   |                       | DATA_TYPE_EXT_BF16           |

2. 输入支持色彩格式为：

| num | input image_format   |
|-----|----------------------|
| 1   | FORMAT_YUV420P       |
| 2   | FORMAT_YUV422P       |
| 3   | FORMAT_YUV444P       |
| 4   | FORMAT_NV12          |
| 5   | FORMAT_NV21          |
| 6   | FORMAT_NV16          |
| 7   | FORMAT_NV61          |
| 8   | FORMAT_RGB_PLANAR    |
| 9   | FORMAT_BGR_PLANAR    |
| 10  | FORMAT_RGB_PACKED    |
| 11  | FORMAT_BGR_PACKED    |
| 12  | FORMAT_RGBP_SEPARATE |
| 13  | FORMAT_BGRP_SEPARATE |
| 14  | FORMAT_GRAY          |
| 15  | FORMAT_COMPRESSED    |
| 16  | FORMAT_YUV444_PACKED |
| 17  | FORMAT_YVU444_PACKED |
| 18  | FORMAT_YUV422_YUYV   |
| 19  | FORMAT_YUV422_YVYU   |
| 20  | FORMAT_YUV422_UYVY   |
| 21  | FORMAT_YUV422_VYUY   |

3. 输出支持色彩格式为：

| num | output image_format  |
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
| 12  | FORMAT_RGBYP_PLANAR  |
| 13  | FORMAT_BGRP_SEPARATE |
| 14  | FORMAT_HSV180_PACKED |
| 15  | FORMAT_HSV256_PACKED |

4. 1684x vpp 不支持从FORMAT_COMPRESSED 转为 FORMAT_HSV180_PACKED 或 FORMAT_HSV256_PACKED。

5. 图片缩放倍数（(crop.width / output.width) 以及 (crop.height / output.height)）限制在 1/128 ～ 128 之间。

6. 输入输出的宽高（src.width, src.height, dst.width, dst.height）限制在 8 ～ 8192 之间。

7. 输入必须关联 device memory，否则返回失败。

8. FORMAT_COMPRESSED 格式的使用方法见bm1684部分介绍。

### bm1684支持的要求

1. 该 API 所需要满足的格式以及部分要求，如下表格所示：

| src format    | dst format    | 其他限制 |
|---------------|---------------|----------|
| RGB_PACKED    | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| BGR_PACKED    | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| RGB_PLANAR    | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| BGR_PLANAR    | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| RGBP_SEPARATE | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| BGRP_SEPARATE | RGB_PLANAR    | 条件1    |
|               | BGR_PLANAR    | 条件1    |
| GRAY          | GRAY          | 条件1    |
| YUV420P       | RGB_PLANAR    | 条件4    |
|               | BGR_PLANAR    | 条件4    |
| NV12          | RGB_PLANAR    | 条件4    |
|               | BGR_PLANAR    | 条件4    |
| COMPRESSED    | RGB_PLANAR    | 条件4    |
|               | BGR_PLANAR    | 条件4    |

其中：

- 条件1：src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- 条件2：src.width, src.height, dst.width, dst.height 必须是2的整数倍，src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- 条件3：dst.width, dst.height 必须是2的整数倍，src.width == dst.width，src.height == dst.height，crop.x == 0，crop.y == 0, src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- 条件4：src.width, src.height 必须是2的整数倍，src.width >= crop.x + crop.width，src.height >= crop.y + crop.height

2. 输入 bm_image 的 device mem 不能在 heap0 上。

3. 所有输入输出 image 的 stride 必须 64 对齐。

4. 所有输入输出 image 的地址必须 32 byte 对齐。

5. 图片缩放倍数（(crop.width / output.width) 以及 (crop.height / output.height)）限制在 1/32 ～ 32 之间。

6. 输入输出的宽高（src.width, src.height, dst.width, dst.height）限制在 16 ～ 4096 之间。

7. 输入必须关联 device memory，否则返回失败。

8. FORMAT_COMPRESSED 是 VPU 解码后内置的一种压缩格式，它包括4个部分：Y compressed table、Y compressed data、CbCr compressed table 以及 CbCr compressed data。请注意 bm_image 中这四部分存储的顺序与 FFMPEG 中 AVFrame 稍有不同，如果需要 attach AVFrame 中 device memory 数据到 bm_image 中时，对应关系如下，关于 AVFrame 详细内容请参考 VPU 的用户手册。

```c
bm_device_mem_t src_plane_device[4];
src_plane_device[0] = bm_mem_from_device((u64)avframe->data[6], avframe->linesize[6]);
src_plane_device[1] = bm_mem_from_device((u64)avframe->data[4], avframe->linesize[4] * avframe->h);
src_plane_device[2] = bm_mem_from_device((u64)avframe->data[7], avframe->linesize[7]);
src_plane_device[3] = bm_mem_from_device((u64)avframe->data[5], avframe->linesize[4] * avframe->h / 2);
bm_image_attach(*compressed_image, src_plane_device);
```

# bmcv_image_overlay

该API实现了在图像上覆盖具有alpha通道的水印。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_overlay(
            bm_handle_t handle,
            bm_image input_base_img,
            int overlay_num,
            bmcv_rect_t* overlay_info,
            bm_image* input_overlay_img);
```

## 参数说明

- **bm_handle_t handle**：输入参数。bm_handle 句柄。
- **bm_image input_base_img**：输入/输出参数。对应底图的 bm_image 图片信息。
- **int overlay_num**：输入参数。水印数量。
- **bmcv_rect_t* overlay_info**：输入参数。关于输入图像上水印位置的信息。
- **bm_image* input_overlay_img**：输入参数。输入的 bm_image 对象，用于叠加。

## 数据类型支持

```c
```

```c
typedef struct bmcv_rect {
    unsigned int start_x;
    unsigned int start_y;
    unsigned int crop_w;
    unsigned int crop_h;
} bmcv_rect_t;
```

`start_x`, `start_y`, `crop_w` 和 `crop_h` 表示覆盖图像在输入图像上的位置和大小信息，包括起始点的x坐标、起始点的y坐标、覆盖图像的宽度和覆盖图像的高度。图像的左上角用作原点。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项**

1. 基础图像和输出图像的颜色格式如下：

| 编号 | 输入图像格式      | 输出图像格式      |
|------|-------------------|-------------------|
| 1    | FORMAT_RGB_PACKED | FORMAT_RGB_PACKED |

2. 叠加图像的颜色格式如下：

| 编号 | 输入叠加图像格式      |
|------|-----------------------|
| 1    | FORMAT_ABGR_PACKED    |
| 2    | FORMAT_ARGB1555_PACKED|
| 3    | FORMAT_ARGB4444_PACKED|

3. 目前支持的输入和输出图像数据的 data_type 值如下：

| 编号 | 数据类型              |
|------|-----------------------|
| 1    | DATA_TYPE_EXT_1N_BYTE |

4. 背景图像支持的最小尺寸为8 * 8，最大尺寸为8192 * 8192。

5. 最大可以叠加的图像数量为10，叠图最大尺寸为850 * 850（单张叠图最大尺寸也为850 * 850）。

**代码示例**

```c++
#include "stb_image.h"
#include <stdio.h>
#include <stdlib.h>
#include <random>
#include <algorithm>
#include <vector>
#include <iostream>
#include <string.h>
#include "bmcv_api_ext.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_dst);
}

int main()
{
    int overlay_num = 1;
    int base_width = 1920;
    int base_height = 1080;
    int pos_x[overlay_num] = {50};
    int pos_y[overlay_num] = {150};
    int overlay_width[overlay_num] = {400};
    int overlay_height[overlay_num] = {400};
    bm_handle_t handle;
    unsigned char* base_image = (unsigned char*)malloc(base_width * base_height * 3 * sizeof(unsigned char));
    unsigned char* output_tpu = (unsigned char*)malloc(base_width * base_height * 3 * sizeof(unsigned char));
    unsigned char* overlay_image[overlay_num];
    bm_image input_base_img;
    bm_image input_overlay_img[overlay_num];
    unsigned char** in_overlay_ptr[overlay_num];
    bmcv_rect rect_array[overlay_num];
    unsigned char* out_ptr[1] = {output_tpu};
    const char *base_path = "path/to/base";
    const char *overlay_path = "path/to/overlay";
    const char *output_path = "path/to/output";

    bm_dev_request(&handle, 0);
    for (int i = 0; i < overlay_num; i++) {
        overlay_image[i] = (unsigned char*)malloc(overlay_width[i] * overlay_height[i] * 4 * sizeof(unsigned char));
        readBin(overlay_path, overlay_image[i], overlay_width[i] * overlay_height[i] * 4);
    }

    readBin(base_path, base_image, base_width * base_height * 3);
    memcpy(output_tpu, base_image, base_width * base_height * 3);

    for (int i = 0; i < overlay_num; i++) {
        bm_image_create(handle, overlay_height[i], overlay_width[i], FORMAT_ABGR_PACKED, DATA_TYPE_EXT_1N_BYTE, input_overlay_img + i, NULL);
    }
    for (int i = 0; i < overlay_num; i++) {
        bm_image_alloc_dev_mem(input_overlay_img[i], 2);
    }

    for (int i = 0; i < overlay_num; i++) {
        in_overlay_ptr[i] = new unsigned char*[1];
        in_overlay_ptr[i][0] = overlay_image[i];
    }
    for (int i = 0; i < overlay_num; i++) {
        bm_image_copy_host_to_device(input_overlay_img[i], (void **)in_overlay_ptr[i]);
    }

    bm_image_create(handle, base_height, base_width, FORMAT_RGB_PACKED, DATA_TYPE_EXT_1N_BYTE, &input_base_img, NULL);
    bm_image_alloc_dev_mem(input_base_img, 2);
    unsigned char* in_base_ptr[1] = {output_tpu};
    bm_image_copy_host_to_device(input_base_img, (void **)in_base_ptr);

    for (int i = 0; i < overlay_num; i++) {
        rect_array[i].start_x = pos_x[i];
        rect_array[i].start_y = pos_y[i];
        rect_array[i].crop_w = overlay_width[i];
        rect_array[i].crop_h = overlay_height[i];
    }

    bmcv_image_overlay(handle, input_base_img, overlay_num, rect_array, input_overlay_img);
    bm_image_copy_device_to_host(input_base_img, (void **)out_ptr);
    writeBin(output_path, output_tpu, base_width * base_height * 3);

    bm_image_destroy(input_base_img);
    for (int i = 0; i < overlay_num; i++) {
        bm_image_destroy(input_overlay_img[i]);
    }
    free(base_image);
    free(output_tpu);
    for (int i = 0; i < overlay_num; i++) {
        free(overlay_image[i]);
    }
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_dct

对图像进行DCT变换。

**处理器型号支持：**

该接口仅支持BM1684。

**接口形式：**

```c
bm_status_t bmcv_image_dct(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            bool is_inversed);
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_image input
  输入参数。输入 bm_image，bm_image 需要外部调用 bmcv_image _create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

* bool is_inversed
  输入参数。是否为逆变换。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项**

由于DCT变换的系数仅与图像的width和height相关，而上述接口每次调用都需要重新计算变换系数，对于相同大小的图像，为了避免重复计算变换系数的过程，可以将上述接口拆分成两步完成：

1. 首先算特定大小的变换系数;
2. 然后可以重复利用改组系数对相同大小的图像做DCT变换。

计算系数的接口形式如下：

```c
bm_status_t bmcv_dct_coeff(
            bm_handle_t handle,
            int H,
            int W,
            bm_device_mem_t hcoeff_output,
            bm_device_mem_t wcoeff_output,
            bool is_inversed);
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* int H
  输入参数。图像的高度。

* int W
  输入参数。图像的宽度。

* bm_device_mem_t hcoeff_output
  输出参数。该device memory空间存储着h维度的DCT变换系数，对于H*W大小的图像，该空间的大小为H*H*sizeof(float)。

* bm_device_mem_t wcoeff_output
  输出参数。该device memory空间存储着w维度的DCT变换系数，对于H*W大小的图像，该空间的大小为W*W*sizeof(float)。

* bool is_inversed
  输入参数。是否为逆变换。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

得到系数之后，将其传给下列接口开始计算过程：

```c
bm_status_t bmcv_image_dct_with_coeff(
            bm_handle_t handle,
            bm_image input,
            bm_device_mem_t hcoeff,
            bm_device_mem_t wcoeff,
            bm_image output);
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_image input
  输入参数。输入 bm_image，bm_image 需要外部调用 bmcv_image _create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_device_mem_t hcoeff
  输入参数。该device memory空间存储着h维度的DCT变换系数，对于H*W大小的图像，该空间的大小为H*H*sizeof(float)。

* bm_device_mem_t wcoeff
  输入参数。该device memory空间存储着w维度的DCT变换系数，对于H*W大小的图像，该空间的大小为W*W*sizeof(float)。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下 image_format:

| num | input image_format | output image_format |
|-----|--------------------|---------------------|
| 1   | FORMAT_GRAY        | FORMAT_GRAY         |

目前支持以下 data_type:

| num | data_type              |
|-----|------------------------|
| 1   | DATA_TYPE_EXT_FLOAT32  |

**注意事项：**

1. 在调用该接口之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type必须相同。

**示例代码**

```c
#include <iostream>
#include <fstream>
#include <assert.h>
#include <memory>
#include <string>
#include <numeric>
#include <vector>
#include <cmath>
#include <cassert>
#include <algorithm>
#include "bmcv_api_ext.h"
#include "test_misc.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 4, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 4, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image bm_input, bm_output;
    float * src_data = new float[channel * width * height];
    float * res_data = new float[channel * width * height];
    bm_device_mem_t hcoeff_mem;
    bm_device_mem_t wcoeff_mem;
    bool is_inversed = true;
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";

    bm_dev_request(&handle, dev_id);
    readBin(input_path, (unsigned char*)src_data, channel * width * height);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_FLOAT32, &bm_input);
    bm_image_alloc_dev_mem(bm_input);
    bm_image_copy_host_to_device(bm_input, (void **)&src_data);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_FLOAT32, &bm_output);
    bm_image_alloc_dev_mem(bm_output);
    bm_malloc_device_byte(handle, &hcoeff_mem, height * height * sizeof(float));
    bm_malloc_device_byte(handle, &wcoeff_mem, width * width * sizeof(float));
    bmcv_dct_coeff(handle, bm_input.height, bm_input.width, hcoeff_mem, wcoeff_mem, is_inversed);
    bmcv_image_dct_with_coeff(handle, bm_input, hcoeff_mem, wcoeff_mem, bm_output);
    bm_image_copy_device_to_host(bm_output, (void **)&res_data);
    writeBin(output_path, (unsigned char*)res_data, channel * width * height);

    bm_image_destroy(bm_input);
    bm_image_destroy(bm_output);
    bm_free_device(handle, hcoeff_mem);
    bm_free_device(handle, wcoeff_mem);
    delete[] src_data;
    delete[] res_data;
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_draw_lines

可以实现在一张图像上画一条或多条线段，从而可以实现画多边形的功能，并支持指定线的颜色和线的宽度。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

bm_status_t bmcv_image_draw_lines(
            bm_handle_t handle,
            bm_image img,
            const bmcv_point_t* start,
            const bmcv_point_t* end,
            int line_num,
            bmcv_color_t color,
            int thickness);
```

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_image img
  输入/输出参数。需处理图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* const bmcv_point_t* start
  输入参数。线段起始点的坐标指针，指向的数据长度由 line_num 参数决定。图像左上角为原点，向右延伸为x方向，向下延伸为y方向。

* const bmcv_point_t* end
  输入参数。线段结束点的坐标指针，指向的数据长度由 line_num 参数决定。图像左上角为原点，向右延伸为x方向，向下延伸为y方向。

* int line_num
  输入参数。需要画线的数量。

* bmcv_color_t color
  输入参数。画线的颜色，分别为RGB三个通道的值。

* int thickness
  输入参数。画线的宽度，对于YUV格式的图像建议设置为偶数。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下 image_format:

| num | image_format |
|-----|--------------|
| 1   | FORMAT_GRAY  |
| 2   | FORMAT_YUV420P |
| 3   | FORMAT_YUV422P |
| 4   | FORMAT_YUV444P |
| 5   | FORMAT_NV12  |
| 6   | FORMAT_NV21  |
| 7   | FORMAT_NV16  |
| 8   | FORMAT_NV61  |

目前支持以下 data_type:

| num | data_type |
|-----|-----------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    int thickness = 4;
    bmcv_point_t start = {0, 0};
    bmcv_point_t end = {100, 100};
    bmcv_color_t color = {255, 0, 0};
    bm_image img;
    bm_handle_t handle;
    unsigned char* data_ptr = new unsigned char[channel * width * height];
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";

    bm_dev_request(&handle, dev_id);
    readBin(input_path, data_ptr, channel * width * height);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &img);
    bm_image_alloc_dev_mem(img);
    bm_image_copy_host_to_device(img, (void**)&data_ptr);
    bmcv_image_draw_lines(handle, img, &start, &end, 1, color, thickness);
    bm_image_copy_device_to_host(img, (void**)&data_ptr);
    writeBin(output_path, data_ptr, channel * width * height);

    bm_image_destroy(img);
    bm_dev_free(handle);
    delete[] data_ptr;
    return 0;
}
```

# bmcv_image_draw_point

该接口用于在图像上填充一个或者多个point。

**处理器型号支持：**

该接口仅支持BM1684X。

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
  输入参数。需要在其上填充point的 bm_image 对象。

* int point_num
  输入参数。需填充point的数量，指 coord 指针中所包含的 bmcv_point_t 对象个数。

* bmcv_point_t* rect
  输入参数。point位置指针。具体内容参考下面的数据类型说明。

* int length
  输入参数。point的边长，取值范围为[1, 510]。

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

1. 该接口支持输入 bm_image 的图像格式为

| num | input image_format |
|-----|-------------------|
| 1   | FORMAT_NV12       |
| 2   | FORMAT_NV21       |
| 3   | FORMAT_YUV420P    |
| 4   | RGB_PLANAR        |
| 5   | RGB_PACKED        |
| 6   | BGR_PLANAR        |
| 7   | BGR_PACKED        |

支持输入 bm_image 数据格式为

| num | intput data_type |
|-----|-----------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

如果不满足输入输出格式要求，则返回失败。

3. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

4. 所有输入point对象区域必须在图像以内。

5. 当输入是FORMAT_YUV420P、FORMAT_NV12、FORMAT_NV21时，length必须为偶数。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bmcv_point_t rect = {100, 100};
    int length = 10;
    bm_image img;
    bm_handle_t handle;
    unsigned char* data_ptr = new unsigned char[channel * width * height];
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";

    bm_dev_request(&handle, dev_id);
    readBin(input_path, data_ptr, channel * width * height);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &img);
    bm_image_alloc_dev_mem(img);
    bm_image_copy_host_to_device(img, (void**)&data_ptr);
    bmcv_image_draw_point(handle, img, 1, &rect, length, 255, 255, 255);
    bm_image_copy_device_to_host(img, (void**)&data_ptr);
    writeBin(output_path, data_ptr, channel * width * height);

    bm_image_destroy(img);
    bm_dev_free(handle);
    delete[] data_ptr;
    return 0;
}
```

# bmcv_image_draw_rectangle

该接口用于在图像上画一个或多个矩形框。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_draw_rectangle(
            bm_handle_t handle,
            bm_image image,
            int rect_num,
            bmcv_rect_t* rects,
            int line_width,
            unsigned char r,
            unsigned char g,
            unsigned char b);
```

**传入参数说明:**

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* bm_image image
  输入参数。需要在其上画矩形框的 bm_image 对象。

* int rect_num
  输入参数。矩形框数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数。

* bmcv_rect_t* rect
  输入参数。矩形框对象指针，包含矩形起始点和宽高。具体内容参考下面的数据类型说明。

* int line_width
  输入参数。矩形框线宽。

* unsigned char r
  输入参数。矩形框颜色的r分量。

* unsigned char g
  输入参数。矩形框颜色的g分量。

* unsigned char b
  输入参数。矩形框颜色的g分量。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明：**

```c
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

**注意事项:**

1. bm1684x要求如下：
- 输入和输出的数据类型必须为：

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

- 输入和输出的色彩格式必须保持一致，可支持：

| num | image_format |
|-----|--------------|
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

如果不满足输入输出格式要求，则返回失败。

2. bm1684部分：
- 该 API 输入 NV12 / NV21 / NV16 / NV61 / YUV420P / RGB_PLANAR / RGB_PACKED / BGR_PLANAR / BGR_PACKED 格式的 image 对象，并在对应的device memory上直接画框，没有额外的内存申请和copy。
- 目前该 API 支持输入 bm_image 图像格式为

| num | image_format |
|-----|--------------|
| 1 | FORMAT_NV12 |
| 2 | FORMAT_NV21 |
| 3 | FORMAT_NV16 |
| 4 | FORMAT_NV61 |
| 5 | FORMAT_YUV420P |
| 6 | FORMAT_RGB_PLANAR |
| 7 | FORMAT_BGR_PLANAR |
| 8 | FORMAT_RGB_PACKED |
| 9 | FORMAT_BGR_PACKED |

支持输入 bm_image 数据格式为

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

如果不满足输入输出格式要求，则返回失败。

3. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。
4. 如果image为NV12/NV21/NV16/NV61/YUV420P格式，则线宽line_width会自动偶数对齐。
5. 如果rect_num为0，则自动返回成功。
6. 如果line_width小于零，则返回失败。
7. 所有输入矩形对象部分在image之外，则只会画出在image之内的线条，并返回成功。

**代码示例**

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src;
    unsigned char* data_ptr = new unsigned char[image_h * image_w * 3 / 2];
    bmcv_rect_t rect;
    const char* filename_src= "path/to/src";
    const char* filename_dst = "path/to/dst";

    bm_dev_request(&handle, 0);
    bm_image_create(handle, image_h, image_w, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &src);

    readBin(filename_src, data_ptr, image_h * image_w * 3 / 2);
    bm_image_copy_host_to_device(src, (void**)&data_ptr);
    rect.start_x = 100;
    rect.start_y = 100;
    rect.crop_w = 200;
    rect.crop_h = 300;
    bmcv_image_draw_rectangle(handle, src, 1, &rect, 3, 255, 0, 0);
    writeBin(filename_dst, data_ptr, image_h * image_w * 3 / 2);

    bm_image_destroy(src);
    bm_dev_free(handle);
    delete[] data_ptr;
    return 0;
}
```

# bmcv_faiss_indexPQ_ADC

该接口通过 query 和 centroids 计算距离表，对底库编码查表并排序，输出前 K (sort_cnt) 个最匹配的向量索引及其对应的距离。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

```c++
bm_status_t bmcv_faiss_indexPQ_ADC(
            bm_handle_t handle,
            bm_device_mem_t centroids_input_dev,
            bm_device_mem_t nxquery_input_dev,
            bm_device_mem_t nycodes_input_dev,
            bm_device_mem_t distance_output_dev,
            bm_device_mem_t index_output_dev,
            int vec_dims,
            int slice_num,
            int centroids_num,
            int database_num,
            int query_num,
            int sort_cnt,
            int IP_metric);
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t centroids_input_dev
  输入参数。存储聚类中心数据的 device 空间。

* bm_device_mem_t nxquery_input_dev
  输入参数。存储查询向量组成的矩阵的 device 空间。

* bm_device_mem_t nycodes_input_dev
  输入参数。存放底库向量组成的矩阵的 device 空间。

* bm_device_mem_t distance_output_dev
  输出参数。存放输出距离的 device 空间。

* bm_device_mem_t index_output_dev
  输出参数。存放输出排序的 device 空间。

* int vec_dims
  输入参数。原始向量的维度。

* int slice_num
  输入参数。原始维度切分数量。

* int centroids_num
  输入参数。聚类中心的数量。

* int database_num
  输入参数。数据底库的数量。

* int query_num
  输入参数。检索向量的数量。

* int sort_cnt
  输入参数。输出前sort_cnt个最匹配的底库向量。

* int IP_metric
  输入参数。0 表示L2距离计算; 1 表示IP距离计算。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他:失败

**注意事项：**

1、输入数据 (查询向量) 和聚类中心的数据类型为 float，底库数据 (底库编码)的数据类型为uint8，都存储在设备内存上。
2、输出的排序后的相似度结果的数据类型为 float, 相对应的索引的数据类型为 int，存储在设备内存上。
3、L2_metric 计算的是 L2 距离平方，没有进行开方 (参考faiss源码的实现)。
4、查询向量和数据库向量 L2 距离越小, 表示两者的相似度越高。输出 L2 topk距离按升序排序。
5、查询向量和数据库向量 IP 距离越大, 表示两者的相似度越高。输出 IP topk距离按降序排序。
6、faiss系列算子有多个输入参数，每个参数都有一个使用范围限制，超过该范围的入参对应tpu输出会出错，我们选择了三个主要参数做了测试，固定其中两个维度，测试了第三个维度的最大值，测试结果如下表格所示：

| query_num | vec_dims | max_database_num |
|-----------|----------|------------------|
| 1 | 128 | 6500万 |
| 1 | 256 | 6500万 |
| 1 | 512 | 6500万 |
| 64 | 128 | 2500万 |
| 64 | 256 | 2500万 |
| 64 | 512 | 1500万 |
| 256 | 128 | 600万 |
| 256 | 256 | 600万 |
| 256 | 512 | 600万 |

# bmcv_faiss_indexPQ_encode

该接口输入 vectors 和 centroids 计算距离表并排序，输出 vectors 的量化编码。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```cpp
bm_status_t bmcv_faiss_indexPQ_encode(
            bm_handle_t handle,
            bm_device_mem_t vector_input_dev,
            bm_device_mem_t centroids_input_dev,
            bm_device_mem_t buffer_table_dev,
            bm_device_mem_t codes_output_dev,
            int encode_vec_num,
            int vec_dims,
            int slice_num,
            int centroids_num,
            int IP_metric);
```

## 输入参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_device_mem_t vector_input_dev**  
  输入参数。存放待编码向量的 device 空间。

- **bm_device_mem_t centroids_input_dev**  
  输入参数。存储聚类中心数据的 device 空间。

- **bm_device_mem_t buffer_table_dev**  
  输入参数。存放计算出的距离表的缓存空间。

- **bm_device_mem_t codes_output_dev**  
  输出参数。存放向量编码结果的 device 空间。

- **int encode_vec_num**  
  输入参数。待编码向量的个数。

- **int vec_dims**  
  输入参数。原始向量的维度。

- **int slice_num**  
  输入参数。原始维度切分数量。

- **int centroids_num**  
  输入参数。聚类中心的数量。

- **int IP_metric**  
  输入参数。0 表示L2距离计算; 1 表示IP距离计算。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 注意事项

1. 输入数据 (查询向量) 和聚类中心的数据类型为 float，输出向量编码的数据类型为 uint8，存储在设备内存上。
2. buffer_table 的大小为 slice_num * centroids_num，数据类型为float。

## 示例代码

```cpp
#include "bmcv_api_ext.h"
#include "test_misc.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

int main()
{
    int vec_dims = 256;
    int encode_vec_num = 1;
    int slice_m = 32;
    int ksub = 256;
    int dsub = vec_dims / slice_m;
    int input_dtype = 5; // 5: float
    int IP_metric = 0;
    bm_handle_t handle;
    int centroids_size = slice_m * ksub * dsub * dtype_size((data_type_t)input_dtype);
    int nxcodes_size = encode_vec_num * vec_dims * dtype_size((data_type_t)input_dtype);;
    int buffer_table_size = slice_m * ksub * dtype_size((data_type_t)input_dtype);;
    int output_codes_size = encode_vec_num * slice_m;
    bm_device_mem_t centroids_input_dev, nxcodes_input_dev, buffer_table_dev, codes_output_dev;
    float* centroids_input_sys_fp32 = (float*)malloc(slice_m * ksub * dsub * sizeof(float));
    unsigned char* nxcodes_input_sys = (unsigned char*)malloc(encode_vec_num * vec_dims);
    unsigned char* output_codes_sys = (unsigned char*)malloc(encode_vec_num * slice_m);

    for (int i = 0; i < slice_m; i++) {
        for (int j = 0; j < ksub; j++) {
            for (int n = 0; n < dsub; n++) {
                float value = (float)rand() / RAND_MAX * 20.0 - 10.0;
                centroids_input_sys_fp32[i * dsub * ksub + j * dsub + n] = value;
            }
        }
    }
    for (int i = 0; i < encode_vec_num; i++) {
        for (int j = 0; j < slice_m; j++) {
            nxcodes_input_sys[i * slice_m + j] = rand() % 256;
        }
    }

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &centroids_input_dev, centroids_size);
    bm_malloc_device_byte(handle, &nxcodes_input_dev, nxcodes_size);
    bm_malloc_device_byte(handle, &buffer_table_dev, buffer_table_size);
    bm_malloc_device_byte(handle, &codes_output_dev, output_codes_size);
    bm_memcpy_s2d(handle, centroids_input_dev, centroids_input_sys_fp32);
    bm_memcpy_s2d(handle, nxcodes_input_dev, nxcodes_input_sys);

    bmcv_faiss_indexPQ_encode(handle, nxcodes_input_dev, centroids_input_dev, buffer_table_dev,
                codes_output_dev, encode_vec_num, vec_dims, slice_m, ksub, IP_metric);
    bm_memcpy_d2s(handle, output_codes_sys, codes_output_dev);

    bm_free_device(handle, centroids_input_dev);
    bm_free_device(handle, nxcodes_input_dev);
    bm_free_device(handle, buffer_table_dev);
    bm_free_device(handle, codes_output_dev);
    free(centroids_input_sys_fp32);
    free(nxcodes_input_sys);
    free(output_codes_sys);
    bm_dev_free(handle);
    return 0;
}
```

## 性能参数表

| database_num | vec_dims | max_query_num |
|--------------|----------|---------------|
| 1000         | 128      | 1000          |
| 1000         | 256      | 1000          |
| 1000         | 512      | 1000          |
| 1万          | 128      | 1000          |
| 1万          | 256      | 1000          |
| 1万          | 512      | 1000          |
| 10万         | 128      | 100           |
| 10万         | 256      | 50            |
| 10万         | 512      | 50            |

| database_num | query_num | max_vec_dims |
|--------------|-----------|--------------|
| 1万          | 1         | 2048         |
| 1万          | 64        | 512          |
| 1万          | 128       | 512          |
| 1万          | 256       | 512          |
| 10万         | 1         | 2048         |
| 10万         | 32        | 512          |
| 10万         | 64        | 512          |
| 100万        | 1         | 128          |

# bmcv_faiss_indexPQ_SDC

该接口通过检索向量编码和底库编码在 sdc_table 中查表并累加，输出前 K (sort_cnt) 个最匹配的向量索引及其对应的距离。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c++
bm_status_t bmcv_faiss_indexPQ_SDC(
            bm_handle_t handle,
            bm_device_mem_t sdc_table_input_dev,
            bm_device_mem_t nxcodes_input_dev,
            bm_device_mem_t nycodes_input_dev,
            bm_device_mem_t distance_output_dev,
            bm_device_mem_t index_output_dev,
            int slice_num,
            int centroids_num,
            int database_num,
            int query_num,
            int sort_cnt,
            int IP_metric);
```

## 输入参数说明

* `bm_handle_t handle` - 输入参数。bm_handle 句柄。
* `bm_device_mem_t sdc_table_input_dev` - 输入参数。存放对称距离表的 device 空间。
* `bm_device_mem_t nxcodes_input_dev` - 输入参数。存放检索向量编码的 device 空间。
* `bm_device_mem_t nycodes_input_dev` - 输入参数。存放底库编码的 device 空间。
* `bm_device_mem_t distance_output_dev` - 输出参数。存放输出距离的 device 空间。
* `bm_device_mem_t index_output_dev` - 输出参数。存放输出排序的 device 空间。
* `int slice_num` - 输入参数。原始维度切分数量。
* `int centroids_num` - 输入参数。聚类中心的数量。
* `int database_num` - 输入参数。数据底库的数量。
* `int query_num` - 输入参数。检索向量的数量。
* `int sort_cnt` - 输入参数。输出的前 sort_cnt 个最匹配底库向量。
* `int IP_metric` - 输入参数。0 表示L2距离计算; 1 表示IP距离计算。

## 返回值说明

* `BM_SUCCESS`: 成功
* 其他: 失败

## 注意事项

1. 输入数据 (查询向量) 和对称距离表的数据类型为 float，底库数据 (底库编码)的数据类型为uint8，存储在设备内存上。
2. 输出的排序后的相似度结果的数据类型为 float, 相对应的索引的数据类型为 int，存储在设备内存上。
3. SDC检索过程中 metric 的选择没有区别，因为距离在于输入的sdc table，主要区别在于其 topk 结果是降序，L2的结果为升序。
4. 查询向量和数据库向量 L2 距离越小, 表示两者的相似度越高。输出 L2 topk距离按升序排序。
5. 查询向量和数据库向量 IP 距离越大, 表示两者的相似度越高。输出 IP topk距离按降序排序。
6. faiss系列算子有多个输入参数，每个参数都有一个使用范围限制，超过该范围的入参对应tpu输出会出错，我们选择了三个主要参数做了测试，固定其中两个维度，测试了第三个维度的最大值，测试结果如下表格所示：

### 参数限制测试结果

| query_num | vec_dims | max_database_num |
|-----------|----------|------------------|
| 1         | 128      | 6500万           |
| 1         | 256      | 6500万           |
| 1         | 512      | 6500万           |
| 64        | 128      | 2500万           |
| 64        | 256      | 2500万           |
| 64        | 512      | 1500万           |
| 256       | 128      | 600万            |
| 256       | 256      | 600万            |
| 256       | 512      | 600万            |

| database_num | vec_dims | max_query_num |
|--------------|----------|---------------|
| 1000         | 128      | 1000          |
| 1000         | 256      | 1000          |
| 1000         | 512      | 1000          |
| 1万          | 128      | 1000          |
| 1万          | 256      | 1000          |
| 1万          | 512      | 1000          |
| 10万         | 128      | 100           |
| 10万         | 256      | 50            |
| 10万         | 512      | 50            |

| database_num | query_num | max_vec_dims |
|--------------|-----------|--------------|
| 1万          | 1         | 2048         |
| 1万          | 64        | 512          |
| 1万          | 128       | 512          |
| 1万          | 256       | 512          |
| 10万         | 1         | 2048         |
| 10万         | 32        | 512          |
| 10万         | 64        | 512          |
| 100万        | 1         | 128          |

## 示例代码

```c++
#include "bmcv_api_ext.h"
#include "test_misc.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

#define BMLIB_SAFE_CALL(cmd) assert(cmd == BM_SUCCESS)

int main()
{
    int sort_cnt = 100;
    int query_num = 1;
    int slice_m = 32;
    int ksub = 256;
    int database_num = 2000000;
    int input_dtype = 5; // 5: float
    int output_dtype = 5;
    int IP_metric = 0;
    bm_handle_t handle;
    int round = 1;
    fp16 *sdc_table_input_sys_fp16 = (fp16*)malloc(slice_m * ksub * ksub * sizeof(fp16));
    float *sdc_table_input_sys_fp32 = (float*)malloc(slice_m * ksub * ksub * sizeof(float));
    unsigned char *nxcodes_input_sys = (unsigned char*)malloc(query_num * slice_m);
    unsigned char *nycodes_input_sys = (unsigned char*)malloc(database_num * slice_m);
    unsigned char *distance_output_sys = (unsigned char*)malloc(query_num * database_num * dtype_size((data_type_t)output_dtype));
    int *index_output_sys = (int*)malloc(query_num * database_num * sizeof(int));
    int sdc_table_size = slice_m * ksub * ksub * dtype_size((data_type_t)input_dtype);
    int nxcodes_size = query_num * slice_m;
    int nycodes_size = database_num * slice_m;
    int output_distance_size = query_num * database_num * dtype_size((data_type_t)output_dtype);
    int output_index_size = query_num * database_num * sizeof(int);
    bm_device_mem_t sdc_table_input_dev, nxcodes_input_dev, nycodes_input_dev, distance_output_dev, index_output_dev;

    for (int i = 0; i < slice_m; i++) {
        for (int j = 0; j < ksub; j++) {
            for (int n = 0; n < ksub; n++) {
                float value = (n > j) ? (float)rand() / RAND_MAX * 20.0 : 0.0;
                sdc_table_input_sys_fp32[i * ksub * ksub + j * ksub + n] = value;
                sdc_table_input_sys_fp16[i * ksub * ksub + j * ksub + n] = fp32tofp16(value, round);
            }
        }
    }
    for (int i = 0; i < query_num; i++) {
        for (int j = 0; j < slice_m; j++) {
            nxcodes_input_sys[i * slice_m + j] = rand() % 256;
        }
    }
    for (int i = 0; i < database_num; i++) {
        for (int j = 0; j < slice_m; j++) {
            nycodes_input_sys[i * slice_m + j] = rand() % 256;
        }
    }

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &sdc_table_input_dev, sdc_table_size);
    bm_malloc_device_byte(handle, &nxcodes_input_dev, nxcodes_size);
    bm_malloc_device_byte(handle, &nycodes_input_dev, nycodes_size);
    bm_malloc_device_byte(handle, &distance_output_dev, output_distance_size);
    bm_malloc_device_byte(handle, &index_output_dev, output_index_size);

    if (input_dtype == DT_FP16) {
        bm_memcpy_s2d(handle, sdc_table_input_dev, sdc_table_input_sys_fp16);
    } else {
        bm_memcpy_s2d(handle, sdc_table_input_dev, sdc_table_input_sys_fp32);
    }
    bm_memcpy_s2d(handle, nxcodes_input_dev, nxcodes_input_sys);
    bm_memcpy_s2d(handle, nycodes_input_dev, nycodes_input_sys);

    bmcv_faiss_indexPQ_SDC_ext(handle, sdc_table_input_dev, nxcodes_input_dev, nycodes_input_dev,
                            distance_output_dev, index_output_dev, slice_m, ksub, database_num,
                            query_num, sort_cnt, IP_metric, input_dtype, output_dtype);
    bm_memcpy_d2s(handle, distance_output_sys, distance_output_dev);
    bm_memcpy_d2s(handle, index_output_sys, index_output_dev);

    bm_free_device(handle, sdc_table_input_dev);
```

# bmcv_faiss_indexflatIP

计算查询向量与数据库向量的内积距离，输出前 K（sort_cnt）个最匹配的内积距离值及其对应的索引。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c++
bm_status_t bmcv_faiss_indexflatIP(
            bm_handle_t handle,
            bm_device_mem_t input_data_global_addr,
            bm_device_mem_t db_data_global_addr,
            bm_device_mem_t buffer_global_addr,
            bm_device_mem_t output_sorted_similarity_global_addr,
            bm_device_mem_t output_sorted_index_global_addr,
            int vec_dims,
            int query_vecs_num,
            int database_vecs_num,
            int sort_cnt,
            int is_transpose,
            int input_dtype,
            int output_dtype);
```

## 输入参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_device_mem_t input_data_global_addr**  
  输入参数。存放查询向量组成的矩阵的 device 空间。

- **bm_device_mem_t db_data_global_addr**  
  输入参数。存放底库向量组成的矩阵的 device 空间。

- **bm_device_mem_t buffer_global_addr**  
  输入参数。存放计算出的内积值的缓存空间。

- **bm_device_mem_t output_sorted_similarity_global_addr**  
  输出参数。存放排序后的最匹配的内积值的 device 空间。

- **bm_device_mem_t output_sorted_index_global_add**  
  输出参数。存储输出内积值对应索引的 device 空间。

- **int vec_dims**  
  输入参数。向量维数。

- **int query_vecs_num**  
  输入参数。查询向量的个数。

- **int database_vecs_num**  
  输入参数。底库向量的个数。

- **int sort_cnt**  
  输入参数。输出的前 sort_cnt 个最匹配的内积值。

- **int is_transpose**  
  输入参数。0 表示底库矩阵不转置；1 表示底库矩阵转置。

- **int input_dtype**  
  输入参数。输入数据类型，支持 float 和 char，5 表示float，1 表示char。

- **int output_dtype**  
  输出参数。输出数据类型，支持 float 和 int，5 表示float，9 表示int。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 注意事项

1. 输入数据（查询向量）和底库数据（底库向量）的数据类型为 float 或 char。
2. 输出的排序后的相似度的数据类型为 float 或 int，相对应的索引的数据类型为 int。
3. 底库数据通常以 database_vecs_num * vec_dims 的形式排布在内存中。此时，参数 is_transpose 需要设置为 1。
4. 查询向量和数据库向量内积距离值越大，表示两者的相似度越高。因此，在 TopK 过程中对内积距离值按降序排序。
5. 该接口用于 Faiss::IndexFlatIP.search()，在 BM1684X 上实现。考虑 BM1684X 上 Tensor Computing Processor 的连续内存，针对 100W 底库，可以在单处理器上一次查询最多约 512 个 256 维的输入。
6. faiss系列算子有多个输入参数，每个参数都有一个使用范围限制，超过该范围的入参对应tpu输出会出错，我们选择了三个主要参数做了测试，固定其中两个维度，测试了第三个维度的最大值，测试结果如下表格所示：

### 最大数据库数量测试

| query_num | vec_dims | max_database_num |
|-----------|----------|------------------|
| 1         | 128      | 800万            |
| 1         | 256      | 400万            |
| 1         | 512      | 200万            |
| 64        | 128      | 800万            |
| 64        | 256      | 400万            |
| 64        | 512      | 200万            |
| 128       | 128      | 400万            |
| 128       | 256      | 250万            |
| 128       | 512      | 200万            |
| 256       | 128      | 550万            |
| 256       | 256      | 400万            |
| 256       | 512      | 200万            |

### 最大查询数量测试

| database_num | vec_dims | max_query_num |
|--------------|----------|---------------|
| 1000         | 128      | 1000          |
| 1000         | 256      | 1000          |
| 1000         | 512      | 1000          |
| 1万          | 128      | 1000          |
| 1万          | 256      | 1000          |
| 1万          | 512      | 1000          |
| 10万         | 128      | 1000          |
| 10万         | 256      | 1000          |
| 10万         | 512      | 1000          |
| 100万        | 128      | 100           |
| 100万        | 256      | 100           |
| 100万        | 512      | 100           |
| 400万        | 128      | 100           |
| 400万        | 256      | 100           |
| 400万        | 512      | 100           |

### 最大向量维度测试

| database_num | query_num | max_vec_dims |
|--------------|-----------|--------------|
| 1万          | 1         | 512          |
| 1万          | 64        | 512          |
| 1万          | 128       | 512          |
| 1万          | 256       | 512          |
| 10万         | 1         | 512          |
| 10万         | 32        | 512          |
| 10万         | 64        | 512          |
| 100万        | 1         | 512          |
| 100万        | 16        | 512          |
| 400万        | 1         | 128          |

## 示例代码

```c++
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "bmcv_api_ext.h"
#include "test_misc.h"

int main()
{
    int sort_cnt = 100;
    int vec_dims = 256;
    int query_vecs_num = 1;
    int database_vecs_num = 10000;
    int is_transpose = 1;
    int input_dtype = 5; // 5: float
    int output_dtype = 5;
    float* input_data = new float[query_vecs_num * vec_dims];
    float* db_data = new float[database_vecs_num * vec_dims];
    bm_handle_t handle;
    bm_device_mem_t query_data_dev_mem;
    bm_device_mem_t db_data_dev_mem;
    float *output_dis = new float[query_vecs_num * sort_cnt];
    int *output_inx = new int[query_vecs_num * sort_cnt];
    bm_device_mem_t buffer_dev_mem;
    bm_device_mem_t sorted_similarity_dev_mem;
    bm_device_mem_t sorted_index_dev_mem;

    bm_dev_request(&handle, 0);
    for (int i = 0; i < query_vecs_num * vec_dims; i++) {
        input_data[i] = ((float)rand() / (float)RAND_MAX) * 3.3;
    }
    for (int i = 0; i < vec_dims * database_vecs_num; i++) {
        db_data[i] = ((float)rand() / (float)RAND_MAX) * 3.3;
    }

    bm_malloc_device_byte(handle, &query_data_dev_mem, query_vecs_num * vec_dims * sizeof(float));
    bm_malloc_device_byte(handle, &db_data_dev_mem, database_vecs_num * vec_dims * sizeof(float));
    bm_memcpy_s2d(handle, query_data_dev_mem, input_data);
    bm_memcpy_s2d(handle, db_data_dev_mem, db_data);

    bm_malloc_device_byte(handle, &buffer_dev_mem, query_vecs_num * database_vecs_num * sizeof(float));
    bm_malloc_device_byte(handle, &sorted_similarity_dev_mem, query_vecs_num * sort_cnt * sizeof(float));
    bm_malloc_device_byte(handle, &sorted_index_dev_mem, query_vecs_num * sort_cnt * sizeof(int));

    bmcv_faiss_indexflatIP(handle, query_data_dev_mem, db_data_dev_mem, buffer_dev_mem,
                        sorted_similarity_dev_mem, sorted_index_dev_mem, vec_dims,
                        query_vecs_num, database_vecs_num, sort_cnt, is_transpose,
                        input_dtype, output_dtype);

    bm_memcpy_d2s(handle, output_dis, sorted_similarity_dev_mem);
    bm_memcpy_d2s(handle, output_inx, sorted_index_dev_mem);

    delete[] input_data;
```

# bmcv_faiss_indexflatL2

计算查询向量与数据库向量 L2 距离的平方，输出前 K（sort_cnt）个最匹配的 L2 距离的平方值及其对应的索引。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c++
bm_status_t bmcv_faiss_indexflatL2(
            bm_handle_t handle,
            bm_device_mem_t input_data_global_addr,
            bm_device_mem_t db_data_global_addr,
            bm_device_mem_t query_L2norm_global_addr,
            bm_device_mem_t db_L2norm_global_addr,
            bm_device_mem_t buffer_global_addr,
            bm_device_mem_t output_sorted_similarity_global_addr,
            bm_device_mem_t output_sorted_index_global_addr,
            int  vec_dims,
            int query_vecs_num,
            int database_vecs_num,
            int sort_cnt,
            int is_transpose,
            int input_dtype,
            int output_dtype);
```

## 输入参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_device_mem_t input_data_global_addr**  
  输入参数。存放查询向量组成的矩阵的 device 空间。

- **bm_device_mem_t db_data_global_addr**  
  输入参数。存放底库向量组成的矩阵的 device 空间。

- **bm_device_mem_t query_L2norm_global_addr**  
  输入参数。存放计算出的内积值的缓存空间。

- **bm_device_mem_t db_L2norm_global_addr**  
  输入参数。数据库向量L2范数的 device 空间。

- **bm_device_mem_t buffer_global_addr**  
  输入参数。缓存 device 空间。

- **bm_device_mem_t output_sorted_similarity_global_addr**  
  输出参数。存放排序后的最匹配的内积值的 device 空间。

- **bm_device_mem_t output_sorted_index_global_addr**  
  输出参数。存储输出内积值对应索引的 device 空间。

- **int vec_dims**  
  输入参数。向量维数。

- **int query_vecs_num**  
  输入参数。查询向量的个数。

- **int database_vecs_num**  
  输入参数。底库向量的个数。

- **int sort_cnt**  
  输入参数。输出的前 sort_cnt 个最匹配的 L2 距离的平方值。

- **int is_transpose**  
  输入参数。0 表示底库矩阵不转置；1 表示底库矩阵转置。

- **int input_dtype**  
  输入参数。输入数据类型，仅支持 float，5 表示float。

- **int output_dtype**  
  输出参数。输出数据类型，仅支持 float，5 表示float。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 注意事项

1. 输入数据（查询向量）和底库数据（底库向量）的数据类型为 float。
2. 输出的排序后的相似度结果的数据类型为 float，相对应的索引的数据类型为 int。
3. 假设输入数据和底库数据的 L2 范数的平方值已提前计算完成，并存储在处理器上。
4. 底库数据通常以 database_vecs_num * vec_dims 的形式排布在内存中。此时，参数 is_transpose 需要设置为 1。
5. 查询向量和数据库向量 L2 距离的平方值越小，表示两者的相似度越高。因此，在 TopK 过程中对 L2 距离的平方值按升序排序。
6. 该接口用于 Faiss::IndexFlatL2.search()，在 BM1684X 上实现。考虑 BM1684X 上 Tensor Computing Processor 的连续内存，针对 100W 底库，可以在单处理器上一次查询最多约 512 个 256 维的输入。
7. database_vecs_num与sort_cnt的取值需要满足条件：database_vecs_num > sort_cnt。
8. faiss系列算子有多个输入参数，每个参数都有一个使用范围限制，超过该范围的入参对应tpu输出会出错，我们选择了三个主要参数做了测试，固定其中两个维度，测试了第三个维度的最大值，测试结果如下表格所示：

### 参数范围测试结果

#### 固定query_num和vec_dims，测试max_database_num

| query_num | vec_dims | max_database_num |
|-----------|----------|------------------|
| 1         | 128      | 800万            |
| 1         | 256      | 400万            |
| 1         | 512      | 200万            |
| 64        | 128      | 500万            |
| 64        | 256      | 300万            |
| 64        | 512      | 180万            |
| 128       | 128      | 400万            |
| 128       | 256      | 200万            |
| 128       | 512      | 150万            |
| 256       | 128      | 200万            |
| 256       | 256      | 150万            |
| 256       | 512      | 100万            |

#### 固定database_num和vec_dims，测试max_query_num

| database_num | vec_dims | max_query_num |
|--------------|----------|---------------|
| 1000         | 128      | 128           |
| 1000         | 256      | 128           |
| 1000         | 512      | 128           |
| 1万          | 128      | 128           |
| 1万          | 256      | 128           |
| 1万          | 512      | 128           |
| 10万         | 128      | 50            |
| 10万         | 256      | 50            |

#### 固定database_num和query_num，测试max_vec_dims

| database_num | query_num | max_vec_dims |
|--------------|-----------|--------------|
| 1万          | 1         | 8192         |
| 1万          | 64        | 4096         |
| 1万          | 128       | 4096         |
| 1万          | 256       | 4096         |
| 10万         | 1         | 4096         |
| 10万         | 64        | 4096         |

## 示例代码

```c++
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "bmcv_api_ext_c.h"
#include "test_misc.h"
#include <string.h>

void matrix_gen_data(float* data, u32 len)
{
    for (u32 i = 0; i < len; i++) {
        data[i] = ((float)rand() / (float)RAND_MAX) * 3.3;
    }
}

void fvec_norm_L2sqr_ref(float* vec, float* matrix, int row_num, int col_num)
{
    for (int i = 0; i < row_num; i++) {
        for (int j = 0; j < col_num; j++) {
            vec[i] += matrix[i * col_num + j] * matrix[i * col_num + j];
        }
    }
}

int main()
{
    int sort_cnt = 100;
    int vec_dims = 256;
    int query_vecs_num = 1;
    int database_vecs_num = 20000;
    int is_transpose = 1;
    int input_dtype = 5; // 5: float
    int output_dtype = 5;
    float* input_data = new float[query_vecs_num * vec_dims];
    float* db_data = new float[database_vecs_num * vec_dims];
    float* vec_query = new float[1 * query_vecs_num];
    float* vec_db = new float[1 * database_vecs_num];
    bm_handle_t handle;
    bm_device_mem_t query_data_dev_mem;
    bm_device_mem_t db_data_dev_mem;
    bm_device_mem_t query_L2norm_dev_mem;
    bm_device_mem_t db_L2norm_dev_mem;
    float* output_dis = new float[query_vecs_num * sort_cnt];
    int* output_inx = new int[query_vecs_num * sort_cnt];
    bm_device_mem_t buffer_dev_mem;
    bm_device_mem_t sorted_similarity_dev_mem;
    bm_device_mem_t sorted_index_dev_mem;

    matrix_gen_data(input_data, query_vecs_num * vec_dims);
    matrix_gen_data(db_data, vec_dims * database_vecs_num);
    fvec_norm_L2sqr_ref(vec_query, input_data, query_vecs_num, vec_dims);
    fvec_norm_L2sqr_ref(vec_db, db_data, database_vecs_num, vec_dims);

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &query_data_dev_mem, query_vecs_num * vec_dims * sizeof(float));
    bm_malloc_device_byte(handle, &db_data_dev_mem, database_vecs_num * vec_dims * sizeof(float));
    bm_malloc_device_byte(handle, &query_L2norm_dev_mem, 1 * query_vecs_num * sizeof(float));
    bm_malloc_device_byte(handle, &db_L2norm_dev_mem, 1 * database_vecs_num * sizeof(float));

    bm_memcpy_s2d(handle, query_data_dev_mem, input_data);
    bm_memcpy_s2d(handle, db_data_dev_mem, db_data);
    bm_memcpy_s2d(handle, query_L2norm_dev_mem, vec_query);
    bm_memcpy_s2d(handle, db_L2norm_dev_mem, vec_db);

    bm_malloc_device_byte(handle, &buffer_dev_mem, query_vecs_num * database_vecs_num * sizeof(float));
    bm_malloc_device_byte(handle, &sorted_similarity_dev_mem, query_vecs_num * sort_cnt * sizeof(float));
    bm_malloc_device_byte(handle, &sorted_index_dev_mem, query_vecs_num * sort_cnt * sizeof(int));

    bmcv_faiss_indexflatL2(handle, query_data_dev_mem, db_data_dev_mem, query_L2norm_dev_mem,
                        db_L2norm_dev_mem, buffer_dev_mem, sorted_similarity_dev_mem,
                        sorted_index_dev_mem, vec_dims, query_vecs_num, database_vecs_num,
                        sort_cnt, is_transpose, input_dtype, output_dtype);

    bm_memcpy_d2s(handle, output_dis, sorted_similarity_dev_mem);
    bm_memcpy_d2s(handle, output_inx, sorted_index_dev_mem);

    delete[] input_data;
    delete[] db_data;
    delete[] vec_query;
    delete[] vec_db;
    delete[] output_dis;
    delete[] output_inx;
    bm_free_device(handle, query_data_dev_mem);
    bm_free_device(handle, db_data_dev_mem);
    bm_free_device(handle, query_L2norm_dev_mem);
    bm_free_device(handle, db_L2norm_dev_mem);
    bm_free_device(handle, buffer_dev_mem);
    bm_free_device(handle, sorted_similarity_dev_mem);
    bm_free_device(handle, sorted_index_dev_mem);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_feature_match

该接口用于将网络得到特征点（int8格式）与数据库中特征点（int8格式）进行比对，输出最佳匹配的top-k。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_feature_match(
    bm_handle_t handle,
    bm_device_mem_t input_data_global_addr,
    bm_device_mem_t db_data_global_addr,
    bm_device_mem_t output_sorted_similarity_global_addr,
    bm_device_mem_t output_sorted_index_global_addr,
    int batch_size,
    int feature_size,
    int db_size,
    int sort_cnt = 1,
    int rshiftbits = 0);
```

## 输入参数说明

* **bm_handle_t handle**
  
  输入参数。bm_handle 句柄。

* **bm_device_mem_t input_data_global_addr**
  
  输入参数。所要比对的特征点数据存储的地址。该数据按照 batch_size * feature_size 的数据格式进行排列。batch_size，feature_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t db_data_global_addr**
  
  输入参数。数据库的特征点数据存储的地址。该数据按照 feature_size * db_size 的数据格式进行排列。feature_size，db_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t output_sorted_similarity_global_addr**
  
  输出参数。每个batch得到的比对结果的值中最大几个值（降序排列）存储地址，具体取多少个值由sort_cnt决定。该数据按照 batch_size * sort_cnt 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **bm_device_mem_t output_sorted_index_global_addr**
  
  输出参数。每个batch得到的比对结果的在数据库中的序号的存储地址。如对于 batch 0 ，如果 output_sorted_similarity_global_addr 中 bacth 0 的数据是由输入数据与数据库的第800组特征点进行比对得到的，那么 output_sorted_index_global_addr 所在地址对应 batch 0 的数据为800。output_sorted_similarity_global_addr 中的数据按照 batch_size * sort_cnt 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* **int batch_size**
  
  输入参数。待输入数据的 batch 个数，如输入数据有4组特征点，则该数据的 batch_size 为4。batch_size最大值不应超过8。

* **int feature_size**
  
  输入参数。每组数据的特征点个数。feature_size最大值不应该超过4096。

* **int db_size**
  
  输入参数。数据库中数据特征点的组数。db_size最大值不应该超过500000。

* **int sort_cnt**
  
  输入参数。每个 batch 对比结果中所要排序个数，也就是输出结果个数，如需要最大的3个比对结果，则sort_cnt设置为3。该值默认为1。sort_cnt最大值不应该超过30。

* **int rshiftbits**
  
  输入参数。对结果进行右移处理的位数，右移采用round对小数进行取整处理。该参数默认为0。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 注意事项

1. 输入数据和数据库中数据的数据类型为 char。
2. 输出的比对结果数据类型为 short，输出的序号类型为 int。
3. 数据库中的数据在内存的排布为 feature_size * db_size，因此需要将一组特征点进行转置之后再放入数据库中。
4. sort_cnt的取值范围为 1 ~ 30。

## 示例代码

```c
#include "bmcv_api_ext.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

int main()
{
    int batch_size = rand() % 10 + 1;
    int feature_size = rand() % 1000 + 1;
    int rshiftbits = rand() % 3;
    int sort_cnt = rand() % 30 + 1;
    int db_size = (rand() % 90 + 1) * 1000;
    bm_handle_t handle;
    int ret = 0;

    ret = (int)bm_dev_request(&handle, 0);

    int8_t* input_data = (int8_t*)malloc(sizeof(int8_t) * batch_size * feature_size);
    int8_t* db_data = (int8_t*)malloc(sizeof(int8_t) * db_size * feature_size);
    short* output_similarity = (short*)malloc(sizeof(short) * batch_size * db_size);
    int* output_index = (int*)malloc(sizeof(int) * batch_size * db_size);
    int i, j;
    int8_t temp_val;

    int8_t** db_content_vec = (int8_t**)malloc(sizeof(int8_t*) * feature_size);
    for (i = 0; i < feature_size; ++i) {
        db_content_vec[i] = (int8_t*)malloc(sizeof(int8_t) * db_size);
    }
    int8_t** input_content_vec = (int8_t**)malloc(sizeof(int8_t*) * batch_size);
    for (i = 0; i < batch_size; ++i) {
        input_content_vec[i] = (int8_t*)malloc(sizeof(int8_t) * feature_size);
    }

    short** ref_res = (short**)malloc(sizeof(short*) * batch_size);
    for (i = 0; i < batch_size; ++i) {
        ref_res[i] = (short*)malloc(sizeof(short) * db_size);
    }

    for (i = 0; i < feature_size; ++i) {
        for (j = 0; j < db_size; ++j) {
            temp_val = rand() % 20 - 10;
            db_content_vec[i][j] = temp_val;
        }
    }

    for (i = 0; i < batch_size; ++i) {
        for (j = 0; j < feature_size; ++j) {
            temp_val = rand() % 20 - 10;
            input_content_vec[i][j] = temp_val;
        }
    }

    for (i = 0; i < feature_size; ++i) {
        for (j = 0; j < db_size; ++j) {
            db_data[i * db_size + j] = db_content_vec[i][j];
        }
    }

    for (i = 0; i < batch_size; ++i) {
        for (j = 0; j < feature_size; ++j) {
            input_data[i * feature_size + j] = input_content_vec[i][j];
        }
    }

    ret = bmcv_feature_match(handle, bm_mem_from_system(input_data), bm_mem_from_system(db_data),
                          bm_mem_from_system(output_similarity), bm_mem_from_system(output_index),
                          batch_size, feature_size, db_size, sort_cnt, rshiftbits);

    free(input_data);
    free(db_data);
    free(output_similarity);
    free(output_index);
    for(i = 0; i < batch_size; ++i) {
        free(input_content_vec[i]);
        free(ref_res[i]);
    }
    for(i = 0; i < feature_size; ++i) {
        free(db_content_vec[i]);
    }
    free(input_content_vec);
    free(db_content_vec);
    free(ref_res);

    bm_dev_free(handle);
    return ret;
}
```

```c
int batch_size = 4;
int feature_size = 512;
int db_size = 1000;
int sort_cnt = 1;
unsigned char src_data_p[4 * 512];
unsigned char db_data_p[512 * 1000];
short output_val[4];
int output_index[4];
for (int i = 0; i < 4 * 512; i++) {
    src_data_p[i] = rand() % 1000;
}
for (int i = 0; i < 512 * 1000; i++) {
    db_data_p[i] = rand() % 1000;
}
bmcv_feature_match(handle,
    bm_mem_from_system(src_data_p),
    bm_mem_from_system(db_data_p),
    bm_mem_from_system(output_val),
    bm_mem_from_system(output_index),
    batch_size,
    feature_size,
    db_size,
    sort_cnt, 8);
```

# bmcv_feature_match_normalized

该接口用于将网络得到特征点（float格式）与数据库中特征点（float格式）进行比对，输出最佳匹配。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input_data_global_addr
  输入参数。所要比对的特征点数据存储的地址。该数据按照 batch_size * feature_size 的数据格式进行排列。batch_size，feature_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t db_data_global_addr
  输入参数。数据库的特征点数据存储的地址。该数据按照 feature_size * db_size 的数据格式进行排列。feature_size，db_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t db_feature_global_addr
  输入参数。数据库的特征点的 feature_size 方向模的倒数的地址。该数据按照 db_size 的数据格式进行排列。

* bm_device_mem_t output_similarity_global_addr
  输出参数。每个batch得到的比对结果的值中最大值存储地址。该数据按照 batch_size 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t output_index_global_addr
  输出参数。每个batch得到的比对结果的在数据库中的序号的存储地址。如对于 batch 0 ，如果 output_sorted_similarity_global_addr 中 bacth 0 的数据是由输入数据与数据库的第800组特征点进行比对得到的，那么 output_sorted_index_global_addr 所在地址对应 batch 0 的数据为800. output_sorted_similarity_global_addr 中的数据按照 batch_size 的数据格式进行排列。batch_size 具体含义将在下面进行介绍。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* int batch_size
  输入参数。待输入数据的 batch 个数，如输入数据有4组特征点，则该数据的 batch_size 为4。batch_size最大值不应超过 10。

* int feature_size
  输入参数。每组数据的特征点个数。feature_size最大值不应该超过1000。

* int db_size
  输入参数。数据库中数据特征点的组数。db_size最大值不应该超过90000。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项：**

1. 输入数据 和 数据库中数据的数据类型为 float 类型。
2. 输出的比对结果数据类型为 float，输出的序号类型为 int。
3. 数据库中的数据在内存的排布为 feature_size * db_size，因此需要将一组特征点进行转置之后再放入数据库中。
4. db_feature_global_addr 模的倒数计算方法为：1 / sqrt(y1 * y1 + y2 * y2 + ...... + yn * yn);

**示例代码**

```c
#include "bmcv_api_ext.h"
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
    float** input_content_vec = (float**)malloc(batch_size * sizeof(float*)); /*row = batch_size col = feature_size*/
    float** ref_res = (float**)malloc(sizeof(float*) * batch_size); /* row = batch_size col = db_size */

    for (i = 0; i < feature_size; ++i) {
        db_content_vec[i] = (float*)malloc(db_size * sizeof(float));
        for (j = 0; j < db_size; ++j) {
            db_content_vec[i][j] = rand() % 20 -10;
        }
    }

    for (i = 0; i < batch_size; ++i) {
        input_content_vec[i] = (float*)malloc(feature_size * sizeof(float));
        for (j = 0; j < feature_size; ++j) {
            input_content_vec[i][j] = rand() % 20 -10;
        }
    }

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
            void *&plan);
```

**处理器型号支持：**

该接口支持BM1684和BM1684X。

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* int batch
  输入参数。batch的数量。

* int len
  输入参数。每个batch的长度。

* bool forward
  输入参数。是否为正向变换，false表示逆向变换。

* void \*\&plan
  输出参数。执行阶段需要使用的句柄。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

对于两维M*N的FFT运算，接口形式如下：

```c
bm_status_t bmcv_fft_2d_create_plan(
            bm_handle_t handle,
            int M,
            int N,
            bool forward,
            void *&plan);
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* int M
  输入参数。第一个维度的大小。

* int N
  输入参数。第二个维度的大小。

* bool forward
  输入参数。是否为正向变换，false表示逆向变换。

* void \*\&plan
  输出参数。执行阶段需要使用的句柄。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

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

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_device_mem_t inputReal
  输入参数。存放输入数据实数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

* bm_device_mem_t inputImag
  输入参数。存放输入数据虚数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

* bm_device_mem_t outputReal
  输出参数。存放输出结果实数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

* bm_device_mem_t outputImag
  输出参数。存放输出结果虚数部分的device memory空间，对于一维的FFT，其大小为batch*len*sizeof(float)，对于两维FFT，其大小为M*N*sizeof(float)。

* const void \*plan
  输入参数。创建阶段所得到的句柄。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

# 销毁

当执行完成后需要销毁所创建的句柄。

```c
void bmcv_fft_destroy_plan(bm_handle_t handle, void *plan);
```

## 示例代码

```c
#include "bmcv_api_ext.h"
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
    bm_device_mem_t XRDev, XIDev, YRDev, YIDev;
    void* plan = NULL;

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

    ret = bm_malloc_device_byte(handle, &XRDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &XIDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &YRDev, L * batch * sizeof(float));
    ret = bm_malloc_device_byte(handle, &YIDev, L * batch * sizeof(float));

    ret = bm_memcpy_s2d(handle, XRDev, XRHost);
    ret = bm_memcpy_s2d(handle, XIDev, XIHost);

    ret = bmcv_fft_2d_create_plan(handle, L, batch, forward, plan);
    if (realInput) {
        bmcv_fft_execute_real_input(handle, XRDev, YRDev, YIDev, plan);
    } else {
        bmcv_fft_execute(handle, XRDev, XIDev, YRDev, YIDev, plan);
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
    bm_free_device(handle, XRDev);
    bm_free_device(handle, XIDev);
    bm_free_device(handle, YRDev);
    bm_free_device(handle, YIDev);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_image_fill_rectangle

该接口用于在图像上填充一个或者多个矩形。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_fill_rectangle(
            bm_handle_t handle,
            bm_image image,
            int rect_num,
            bmcv_rect_t* rects,
            unsigned char r,
            unsigned char g,
            unsigned char b);
```

**传入参数说明：**

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* bm_image image
  输入参数。需要在其上填充矩形的 bm_image 对象。

* int rect_num
  输入参数。需填充矩形的数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数。

* bmcv_rect_t* rect
  输入参数。矩形对象指针，包含矩形起始点和宽高。具体内容参考下面的数据类型说明。

* unsigned char r
  输入参数。矩形填充颜色的r分量。

* unsigned char g
  输入参数。矩形填充颜色的g分量。

* unsigned char b
  输入参数。矩形填充颜色的b分量。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明：**

```c
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

**注意事项：**

1. bm1684 支持输入 bm_image 图像格式为

| num | input image_format |
|-----|-------------------|
| 1   | FORMAT_NV12       |
| 2   | FORMAT_NV21       |
| 3   | FORMAT_NV16       |
| 4   | FORMAT_NV61       |
| 5   | FORMAT_YUV420P    |
| 6   | RGB_PLANAR        |
| 7   | RGB_PACKED        |
| 8   | BGR_PLANAR        |
| 9   | BGR_PACKED        |

bm1684x 支持输入 bm_image 图像格式为

| num | input image_format |
|-----|-------------------|
| 1   | FORMAT_NV12       |
| 2   | FORMAT_NV21       |
| 3   | FORMAT_YUV420P    |
| 4   | RGB_PLANAR        |
| 5   | RGB_PACKED        |
| 6   | BGR_PLANAR        |
| 7   | BGR_PACKED        |

支持输入 bm_image 数据格式为

| num | intput data_type      |
|-----|----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

如果不满足输入输出格式要求，则返回失败。

2. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

3. 如果rect_num为0，则自动返回成功。

4. 所有输入矩形对象部分在image之外，则只会填充在image之内的部分，并返回成功。

**代码示例**

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <memory>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src;
    int src_size = image_h * image_w * 3 / 2;
    unsigned char* input_data = (unsigned char*)malloc(src_size);
    unsigned char* in_ptr[3] = {input_data, input_data + image_h * image_w, input_data + 2 * image_h * image_w};
    bmcv_rect_t rect;
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";

    readBin(input_path, input_data, src_size);
    bm_dev_request(&handle, 0);
    bm_image_create(handle, image_h, image_w, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_alloc_dev_mem(src);
    bm_image_copy_host_to_device(src, (void**)in_ptr);
    rect.start_x = 100;
    rect.start_y = 100;
    rect.crop_w = 200;
    rect.crop_h = 300;
    bmcv_image_fill_rectangle(handle, src, 1, &rect, 255, 0, 0);
    bm_image_copy_device_to_host(src, (void**)in_ptr);
    writeBin(output_path, input_data, src_size);

    bm_image_destroy(src);
    free(input_data);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_gaussian_blur

该接口用于对图像进行高斯滤波。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_image input
  输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

* int kw
  kernel 在width方向上的大小。

* int kh
  kernel 在height方向上的大小。

* float sigmaX
  X方向上的高斯核标准差。

* float sigmaY = 0
  Y方向上的高斯核标准差。如果为0则表示与X方向上的高斯核标准差相同。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下 image_format:

| num | input image_format   | output image_format  |
|-----|---------------------|---------------------|
| 1   | FORMAT_BGR_PLANAR   | FORMAT_BGR_PLANAR   |
| 2   | FORMAT_RGB_PLANAR   | FORMAT_RGB_PLANAR   |
| 3   | FORMAT_RGBP_SEPARATE| FORMAT_RGBP_SEPARATE|
| 4   | FORMAT_BGRP_SEPARATE| FORMAT_BGRP_SEPARATE|
| 5   | FORMAT_GRAY         | FORMAT_GRAY         |

目前支持以下 data_type:

| num | data_type |
|-----|-----------|

| 1 | DATA_TYPE_EXT_1N_BYTE |
|---|---|

**注意事项：**

1. 在调用该接口之前必须确保输入的 image 内存已经申请。
2. input output 的 data_type，image_format必须相同。
3. BM1684支持的图像最大宽为(2048 - kw)，BM1684X芯片下该算子在卷积核大小为3时，支持的宽高范围为8*8～8192*8192，核大小为5时支持的宽高范围为8*8～4096*8192，核大小为7时支持的宽高范围为8*8～2048*8192。
4. BM1684X下卷积核支持的大小为3*3,5*5和7*7。
5. BM1684支持的最大卷积核宽高为31，BM1684X支持的最大卷积核宽高为7。

**代码示例：**

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>
#include <float.h>
#include <math.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input, output;
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";
    unsigned char* src_data = new unsigned char[channel * width * height];
    unsigned char* res_data = new unsigned char[channel * width * height];

    readBin(input_path, src_data, channel * width * height);
    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void**)&src_data);
    bm_image_create(handle, height,width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_gaussian_blur(handle, input, output, 3, 3, 0.1);
    bm_image_copy_device_to_host(output, (void**)&res_data);
    writeBin(output_path, res_data, channel * width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    free(src_data);
    free(res_data);
    bm_dev_free(handle);
    return 0;
}
```

## bmcv_gemm

该接口可以实现 float32 类型矩阵的通用乘法计算，如下公式：

C = α × A × B + β × C

其中，A、B、C均为矩阵，α 和 β 均为常系数

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

**输入参数说明：**

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

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**示例代码**

```c
#include "bmcv_api_ext.h"
#include "bmcv_api.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

int main()
{
    int M = 3, N = 4, K = 5;
    float alpha = 0.4, beta = 0.6;
    bool if_A_trans = false;
    bool if_B_trans = false;
    float* A = new float[M * K];
    float* B = new float[K * N];
    float* C = new float[M * N];
    bm_handle_t handle;
    int lda = if_A_trans ? M : K;
    int ldb = if_B_trans ? K : N;

    for (int i = 0; i < M * K; ++i) {
        A[i] = 1.0f;
    }

    for (int i = 0; i < N * K; ++i) {
        B[i] = 2.0f;
    }

    for (int i = 0; i < M * N; ++i) {
        C[i] = 3.0f;
    }

    bm_dev_request(&handle, 0);
    bmcv_gemm(handle, if_A_trans, if_B_trans, M, N, K, alpha, bm_mem_from_system((void *)A),
            lda, bm_mem_from_system((void *)B), ldb, beta, bm_mem_from_system((void *)C), N);

    delete[] A;
    delete[] B;
    delete[] C;
    bm_dev_free(handle);
    return 0;
}
```

## bmcv_gemm_ext

该接口可以实现 fp32/fp16 类型矩阵的通用乘法计算，如下公式：

Y = α × A × B + β × C

其中，A、B、C、Y均为矩阵，α 和 β 均为常系数

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

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

**输入参数说明：**

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

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意：**

1. 该接口在FP16输入、A矩阵转置的情况下，M仅支持小于等于64的取值。
2. 该接口不支持FP32输入且FP16输出。

**示例代码**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

int main()
{
    int M = 3, N = 4, K = 5;
    float alpha = 0.4, beta = 0.6;
    bool is_A_trans = false;
    bool is_B_trans = false;
    float* A = new float[M * K];
    float* B = new float[N * K];
    float* C = new float[M * N];
    float* Y_tpu = new float[M * N];
    bm_device_mem_t input_dev_buffer[3];
    bm_device_mem_t output_dev_buffer[1];
    bm_image_data_format_ext in_dtype = DATA_TYPE_EXT_FLOAT32;
    bm_image_data_format_ext out_dtype = DATA_TYPE_EXT_FLOAT32;
    bm_handle_t handle;

    memset(A, 0x11, M * K * sizeof(float));
    memset(B, 0x22, N * K * sizeof(float));
    memset(C, 0x33, M * N * sizeof(float));

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &input_dev_buffer[0], M * K * sizeof(float));
    bm_malloc_device_byte(handle, &input_dev_buffer[1], N * K * sizeof(float));
    bm_malloc_device_byte(handle, &input_dev_buffer[2], M * N * sizeof(float));
    bm_malloc_device_byte(handle, &output_dev_buffer[0], M * N * sizeof(float));
    bm_memcpy_s2d(handle, input_dev_buffer[0], (void*)A);
    bm_memcpy_s2d(handle, input_dev_buffer[1], (void*)B);
    bm_memcpy_s2d(handle, input_dev_buffer[2], (void*)C);

    bmcv_gemm_ext(handle, is_A_trans, is_B_trans, M, N, K, alpha,
                input_dev_buffer[0], input_dev_buffer[1], beta,
                input_dev_buffer[2], output_dev_buffer[0], in_dtype,
                out_dtype);
    bm_memcpy_d2s(handle, (void*)Y_tpu, output_dev_buffer[0]);

    delete[] A;
    delete[] B;
    delete[] C;
    delete[] Y_tpu;
    for (int i = 0; i < 3; i++) {
        bm_free_device(handle, input_dev_buffer[i]);
    }
    bm_free_device(handle, output_dev_buffer[0]);
    bm_dev_free(handle);
    return 0;
}
```

## bmcv_hm_distance

计算两个向量中各个元素的汉明距离。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

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

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_image input1
  输入参数。向量1数据的设备地址信息。

* bm_image input2
  输入参数。向量2数据的设备地址信息。

* bm_image output
  输出参数。output向量数据的设备地址信息。

* int bits_len
  输入参数。向量中的每个元素的长度

* int input1_num
  输入参数。向量1的数据个数

* int input2_num
  输入参数。向量2的数据个数

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**示例代码**

```c
#include <math.h>
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include "bmcv_api_ext.h"

int main()
{
    int bits_len = 8;
    int input1_num = 2;
    int input2_num = 2562;
    int* input1_data = new int[input1_num * bits_len];
    int* input2_data = new int[input2_num * bits_len];
    int* output_tpu  = new int[input1_num * input2_num];
    bm_device_mem_t input1_dev_mem;
    bm_device_mem_t input2_dev_mem;
    bm_device_mem_t output_dev_mem;
    bm_handle_t handle;

    memset(input1_data, 0, input1_num * bits_len * sizeof(int));
    memset(input2_data, 0, input2_num * bits_len * sizeof(int));
    memset(output_tpu,  0,  input1_num * input2_num * sizeof(int));

    // fill data
    for(int i = 0; i < input1_num * bits_len; i++) {
        input1_data[i] = rand() % 10;
    }
    for(int i = 0; i < input2_num * bits_len; i++) {
        input2_data[i] = rand() % 20 + 1;
    }

    bm_dev_request(&handle, 0);
    bm_malloc_device_byte(handle, &input1_dev_mem, input1_num * bits_len * sizeof(int));
    bm_malloc_device_byte(handle, &input2_dev_mem, input2_num * bits_len * sizeof(int));
    bm_malloc_device_byte(handle, &output_dev_mem, input1_num * input2_num * sizeof(int));
    bm_memcpy_s2d(handle, input1_dev_mem, input1_data);
    bm_memcpy_s2d(handle, input2_dev_mem, input2_data);
    bmcv_hamming_distance(handle, input1_dev_mem, input2_dev_mem, output_dev_mem,
                        bits_len, input1_num, input2_num);
    bm_memcpy_d2s(handle, output_tpu, output_dev_mem);

    delete[] input1_data;
    delete[] input2_data;
    delete[] output_tpu;
    bm_free_device(handle, input1_dev_mem);
    bm_free_device(handle, input2_dev_mem);
    bm_free_device(handle, output_dev_mem);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_jpeg_dec

该接口可以实现对多张图片的 JPEG 解码过程。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_jpeg_dec(
            bm_handle_t handle,
            void* p_jpeg_data[],
            size_t* in_size,
            int image_num,
            bm_image* dst);
```

## 输入参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* void * p_jpeg_data[]
  输入参数。待解码的图片数据指针，由于该接口支持对多张图片的解码，因此为指针数组。

* size_t *in_size
  输入参数。待解码各张图片的大小（以 byte 为单位）存放在该指针中，也就是上述 p_jpeg_data 每一维指针所指向空间的大小。

* int image_num
  输入参数。输入图片数量，最多支持 4

* bm_image* dst
  输出参数。输出 bm_image的指针。每个 dst bm_image 用户可以选择自行调用 bm_image_create 创建，也可以选择不创建。如果用户只声明而不创建则由接口内部根据待解码图片信息自动创建，默认的 format 如下表所示, 当不再需要时仍然需要用户调用 bm_image_destory 来销毁。

| 码流   | 默认输出 format |
|--------|-----------------|
| YUV420 | FORMAT_YUV420P  |
| YUV422 | FORMAT_YUV422P  |
| YUV444 | FORMAT_YUV444P  |
| YUV400 | FORMAT_GRAY     |

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 如果用户没有使用bmcv_image_create创建dst的bm_image，那么需要将参数传入指针所指向的空间置0。

2. 目前解码支持的图片格式及其输出格式对应如下，如果用户需要指定以下某一种输出格式，可通过使用 bmcv_image_create 自行创建 dst bm_image，从而实现将图片解码到以下对应的某一格式。

| 码流   | 输出 format     |
|--------|-----------------|
| YUV420 | FORMAT_YUV420P  |
|        | FORMAT_NV12     |
|        | FORMAT_NV21     |
| YUV422 | FORMAT_YUV422P  |
|        | FORMAT_NV16     |
|        | FORMAT_NV61     |
| YUV444 | FORMAT_YUV444P  |
| YUV400 | FORMAT_GRAY     |

目前解码支持的数据格式如下：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 示例代码

```c
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <memory.h>
#include "bmcv_api_ext.h"
#include <assert.h>
#include <math.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int format = FORMAT_YUV420P;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src;
    bm_image dst;
    bm_handle_t handle;
    size_t byte_size = image_w * image_h * 3 / 2;
    unsigned char* input_data = (unsigned char*)malloc(byte_size);
    unsigned char* output_data = (unsigned char*)malloc(byte_size);
    unsigned char* in_ptr[3] = {input_data, input_data + image_h * image_w, input_data + 2 * image_h * image_w};
    unsigned char* out_ptr[3] = {output_data, output_data + image_h * image_w, output_data + 2 * image_h * image_w};
    void* jpeg_data[4] = {NULL, NULL, NULL, NULL};
    const char *dst_name = "path/to/dst";
    const char *src_name = "path/to/src";

    readBin(src_name, input_data, byte_size);
    bm_dev_request(&handle, 0);
    bm_image_create(handle, image_h, image_w, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    bm_image_create(handle, image_h, image_w, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);
    bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);
    bm_image_copy_host_to_device(src, (void**)in_ptr);
    bmcv_image_jpeg_enc(handle, 1, &src, jpeg_data, &byte_size, 95);
    bmcv_image_jpeg_dec(handle, (void**)jpeg_data, &byte_size, 1, &dst);
    bm_image_copy_device_to_host(dst, (void**)out_ptr);
    writeBin(dst_name, output_data, byte_size);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    free(input_data);
    free(output_data);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_jpeg_enc

该接口可以实现对多张 bm_image 的 JPEG 编码过程。

## 接口形式

```c
bm_status_t bmcv_image_jpeg_enc(
            bm_handle_t handle,
            int image_num,
            bm_image* src,
            void* p_jpeg_data[],
            size_t* out_size,
            int quality_factor = 85);
```

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 输入参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* int image_num
  输入参数。输入图片数量，最多支持 4。

* bm_image* src
  输入参数。输入 bm_image的指针。每个 bm_image 需要外部调用 bmcv_image_create 创建，image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存,或者使用 bmcv_image_attach 来 attach 已有的内存。

* void * p_jpeg_data,
  输出参数。编码后图片的数据指针，由于该接口支持对多张图片的编码，因此为指针数组，数组的大小即为 image_num。用户可以选择不为其申请空间（即数组每个元素均为NULL），在 api 内部会根据编码后数据的大小自动分配空间，但当不再使用时需要用户手动释放该空间。当然用户也可以选择自己申请足够的空间。

* size_t *out_size,
  输出参数。完成编码后各张图片的大小（以 byte 为单位）存放在该指针中。

* int quality_factor = 85
  输入参数。编码后图片的质量因子。取值 0～100 之间，值越大表示图片质量越高，但数据量也就越大，反之值越小图片质量越低，数据量也就越少。该参数为可选参数，默认值为85。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

# bmcv_knn

KNN。kmeans++随机初始化需要额外实现。

## 处理器型号支持

该接口支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_knn(
            bm_handle_t handle,
            bm_device_mem_t centroids_global_addr,//[m_code,  n_feat]
            bm_device_mem_t labels_global_addr,   //[m_obs]
            bm_device_mem_t input_global_addr,    //[m_obs,   n_feat]
            bm_device_mem_t weight_global_addr,   //[m_code,  n_feat]
            bm_device_mem_t buffer_global_addr,
            int* Shape_Input,
            int* Shape_Weight,
            int dims_Input,
            int dims_Weight,
            int n_feat,
            int k,
            int num_iter,
            int buffer_coeff,
            unsigned int buffer_max_cnt,
            int dtype);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **bm_device_mem_t centroids_global_addr**  
  输出参数。存放聚类距离。形状为[m_obs, m_code]。

* **bm_device_mem_t labels_global_addr**  
  输出参数。存放KNN结果标签。形状为[m_obs]。  
  只有labels存储为int32!

* **bm_device_mem_t input_global_addr**  
  输入参数。存放输入矩阵。形状为[m_obs, n_feat]。

* **bm_device_mem_t weight_global_addr**  
  输入参数。存放初始化的聚类中心权值矩阵。形状为[m_code, n_feat]。

* **bm_device_mem_t buffer_global_addr**  
  输入参数。存放buffer。

* **const int* Shape_Input**  
  输入参数。存放输入矩阵形参，为[m_obs, n_feat]。

* **const int* Shape_Weight**  
  输入参数。存放权值矩阵的形参，为[m_code, n_feat]。

* **int dims_Input**  
  输入参数。存放输入矩阵维度。

* **int dims_Weight**  
  输入参数。存放权值矩阵的维度。

* **int n_feat**  
  输入参数。存放输入矩阵、初始化权值矩阵的公有列数，或最后维度。  
  是来自上层 qr_cpu block 的num_spks_global_addr[0]。

* **int k**  
  输入参数。存放KNN的聚类簇个数。

* **int num_iter**  
  输入参数。存放KNN迭代次数。

* **int buffer_coeff**  
  输入参数。buffer面积为buffer_coeff * buffer_max_cnt。

* **int buffer_max_cnt**  
  输入参数。单个buffer默认有效面积，形状具体为[m_obs, m_code]。

* **int dtype**  
  输入参数。数据类型。

## 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

## 数据类型支持

### 输入数据目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

### 输出数据目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

## 注意事项

1. default seed 为 42。
2. buffer_coeff必须至少为3。
3. 对KNN例，buffer_max_cnt必须覆盖输入矩阵、初始化权值矩阵，即两矩阵元素的最大个数。
4. 每个dims_Input、dims_Weight只支持描述单个二维矩阵，一般如[1,1,n,n]。
5. kmeans++初始化应绑定随机种子和随机分布具体实现。

## kmeans++初始化例

```c
#define UNIVERSAL_SEED 42
void _kpp_weight_generator_kmeans(
    const float*        data,
    float*              out,
    int*            Shape_Output,
    const int*      Shape_Input,
    const int       dims_Input,
    const int       dims_Output,
    const int       k,
    const int       random_mode) {
    int dims = 1;
    if (dims_Input > 1) dims = Shape_Input[dims_Input - 1];
    int shape_cnt = 1;
    for (int i = 0; i < dims_Input; i++) {
        shape_cnt *= Shape_Input[i];
    }
    for (int i = 0; i < dims_Output; i++) {
        Shape_Output[i] = 1;
    }
    int m_obs = shape_cnt/dims;
    Shape_Output[dims_Output - 1] = dims;
    Shape_Output[dims_Output - 2] = k;

    std::mt19937 mt(UNIVERSAL_SEED);
    std::cout << "[Random info]"<<mt() << std::endl;
    std::uniform_real_distribution<float> dist_float(0.0, 1.0);
    for (int i = 0; i < k ; i++) {
        if (i == 0) {
            std::uniform_int_distribution<int> dist(0, m_obs);
            int randint  = dist(mt);
            if (random_mode == POISSON_CPP || random_mode == MT19937_CPP) {
            memcpy(out, data + randint * dims, dims * sizeof(float));
            } else if (random_mode == CONST_WEIGHT) {
            int fake_rng_randint = int(m_obs/2);
            memcpy(out, data + fake_rng_randint * dims, dims * sizeof(float));
            } else { assert(0); }
        } else {
            //sqeuclidean(init[:i,:], data)
            float* D2_0 = new float [i * m_obs];
            for(int m = 0; m < i; m++) {
                for(int idx_data = 0; idx_data < m_obs; idx_data++) {
                    D2_0[m * m_obs + idx_data] = sqeucliden(out, data,  m ,idx_data, dims);
                }
            }
            float* D2 = new float [m_obs];
            for (int j = 0; j < m_obs; j++) {
                float min = D2_0[j];
                for(int m = 0; m < i; m++) {
                    min = std::min(D2_0[m*m_obs + j], min);
                }
                D2[j] = min;
            }
            float T_sum = 0.0;
            for (int j = 0; j < m_obs; j++) {
                T_sum +=  D2[j];
            }
            float* probs = new float [m_obs];
            for (int j = 0; j < m_obs; j++) {
                probs[j] =  D2[j]/T_sum;
            }
            float* cumprobs = new float [m_obs];
            cumprobs[0] = probs[0];
            for (int j = 1; j < m_obs; j++) {
                cumprobs[j] =  cumprobs[j-1] + probs[j];
            }
            //r = rng.uniform()
            float r = 0.0;//dist_float(mt);
            if (random_mode == MT19937_CPP || random_mode == POISSON_CPP) {
            r = dist_float(mt);
            } else if (random_mode == CONST_WEIGHT) {
            //np.min(cumprobs) + (np.max(cumprobs)- np.min(cumprobs))/2
            float max_temp = cumprobs[0];
            float min_temp = cumprobs[0];
            for (int idx = 1; idx < m_obs; idx++) {
                min_temp = cumprobs[idx] > min_temp ? min_temp : cumprobs[idx];
                max_temp = cumprobs[idx] > max_temp ? cumprobs[idx] : max_temp;
            }
            r = min_temp + (max_temp - min_temp)/2.0;//0.5072551558477147;
            } else { assert(0); }
            int sort_idx = 0;
            for (int j = 1; j < m_obs; j++) {
                if ((cumprobs[j - 1] < r) && (r <= cumprobs[j]))  {
                    sort_idx = j;
                    break;
                }
            }
            memcpy(out + i * dims, data + sort_idx * dims, dims * sizeof(float));
            delete [] D2;
            delete [] D2_0;
            delete [] probs;
            delete [] cumprobs;
        }
    }
}
```

# bmcv_knn2

KNN，距离为欧式距离。

## 处理器型号支持

该接口支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_knn2(
    bm_handle_t handle,
    bm_device_mem_t ref_data_addr,
    bm_device_mem_t test_data_addr,
    bm_device_mem_t distance_addr,
    bm_device_mem_t indices_addr,
    int n_test,
    int n_ref,
    int n_feat,
    int k);
```

## 参数说明

* **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

* **bm_device_mem_t ref_data_addr**  
  输入参数。存放底库数据。形状为[n_ref, n_feat]。

* **bm_device_mem_t test_data_addr**  
  输入参数。存放测试数据。形状为[n_test, n_feat]。

* **bm_device_mem_t distance_addr**  
  输出参数。存放KNN距离结果。形状为[n_test, k]。

* **bm_device_mem_t indices_addr**  
  输出参数。存放KNN索引结果。形状为[n_test, k]。

* **int n_test**  
  输入参数。存放测试数据行数(第一个维度)。

* **int n_ref**  
  输入参数。存放底库数据行数(第一个维度)。

* **int n_feat**  
  输入参数。存放输入矩阵的公有列数，或最后维度。

* **int k**  
  输入参数。存放KNN的聚类簇个数。

## 返回值说明：

- BM_SUCCESS: 成功
- 其他: 失败

## 数据类型支持：

输入数据目前支持以下 data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

输出数据目前支持以下 data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

## 代码示例：

```c
#include <iostream>
#include "test_misc.h"
#include <random>
#include <unordered_map>
#include "bmcv_api_ext.h"
#include <sys/time.h>

#define TIME_COST_US(start, end) ((end.tv_sec - start.tv_sec) * 1000000 + (end.tv_usec - start.tv_usec))

using namespace std;

static void get_prediction(
    int             n_tests,
    int*            indices,
    int             k,
    const float*    ref_labels,
    int             ref_labels_size,
    float*          predictions)
{
    if (!indices || !ref_labels || !predictions) {
        std::cerr << "Error: Null pointer detected!" << std::endl;
        return;
    }

    for (int i = 0; i < n_tests; i++) {
        std::unordered_map<int, int> label_counts;

        for (int j = 0; j < k; j++) {
            int neighbor_index = indices[i * k + j];

            if (neighbor_index < 0 || neighbor_index >= ref_labels_size) {
                std::cerr << "Warning: Invalid neighbor index " << neighbor_index << std::endl;
                continue;
            }

            float label = ref_labels[neighbor_index];
            label_counts[label]++;
        }

        int max_count = 0;
        float predicted_label = -1.0;

        for (const auto& pair : label_counts) {
            if (pair.second > max_count ||
                (pair.second == max_count && pair.first < predicted_label)) {
                max_count = pair.second;
                predicted_label = pair.first;
            }
        }
        predictions[i] = predicted_label;
    }
}

void generate_data(
    float*              ref_data,
    float*              test_data,
    int                 n_ref,
    int                 n_test,
    int                 n_feat,
    int                 n_class,
    float*              ref_label,
    float*              test_label) {
    // Set seed for random generator
    std::random_device rd;
    std::mt19937 gen(rd());

    // Generate n_class normal distributions
    std::vector<std::normal_distribution<>> distributions;
    for (int c = 0; c < n_class; c++) {
        // You can customize mean and stddev for each class here
        // For example, means spaced evenly between -2.0 and 2.0
        double mean = -2.0 + 4.0 * c / (n_class - 1);
        double stddev = 0.3 + 0.1 * c;  // Varying stddev slightly
        distributions.emplace_back(mean, stddev);
    }

    // Generate ref_data
    for (int i = 0; i < n_ref; i++) {
        // Assign class labels evenly
        int class_id = i % n_class;
        ref_label[i] = static_cast<float>(class_id);

        for (int j = 0; j < n_feat; j++) {
            // Generate data from the corresponding distribution
            ref_data[i * n_feat + j] = distributions[class_id](gen);
        }
    }

    // Generate test_data
    std::vector<float> class_proportions(n_class);
    float sum = 0.0f;
    for (int c = 0; c < n_class; c++) {
        class_proportions[c] = 1.0f / (c + 1);  // Example decreasing proportion
        sum += class_proportions[c];
    }
    // Normalize proportions
    for (int c = 0; c < n_class; c++) {
        class_proportions[c] /= sum;
    }

    // Generate test samples according to proportions
    std::discrete_distribution<> test_dist(class_proportions.begin(), class_proportions.end());

    for (int i = 0; i < n_test; i++) {
        // Assign class labels according to specified proportions
        int class_id = test_dist(gen);
        test_label[i] = static_cast<float>(class_id);

        for (int j = 0; j < n_feat; j++) {
            // Generate data from the corresponding distribution
            test_data[i * n_feat + j] = distributions[class_id](gen);
        }
    }
}

void print_result(
    int n_class,
    int n_test,
    float* test_label,
    float* prediction_cpu) {
    // Count different classes num
    std::vector<int> class_num(n_class, 0);
    for (int i = 0; i < n_test; i++) {
        int class_id = static_cast<int>(prediction_cpu[i]);
        class_num[class_id] += 1;
    }
    for (int i = 0; i < n_class; i++) {
        std::cout << "Class " << i << ": " << class_num[i] << std::endl;
    }

    int correct = 0;
    for (int i = 0; i < n_test; i++) {
        if (prediction_cpu[i] == test_label[i]) {
            correct++;
        }
    }
    float accuracy = (float)correct / n_test * 100;
    printf("Accuracy: %.2f%%\n", accuracy);
}

int main() {
    struct timespec tp;
    clock_gettime_(0, &tp);
    srand(tp.tv_nsec);

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<int> ref_dist(3000, 5000);
    std::uniform_int_distribution<int> test_dist(1000, 3000);
    std::uniform_int_distribution<int> feat_dist(5, 55);
    std::uniform_int_distribution<int> class_dist(2, 12);
    std::uniform_int_distribution<int> k_dist(1, 20);

    int n_ref = ref_dist(gen);
    int n_test = test_dist(gen);
    int n_feat = feat_dist(gen);
    int n_class = class_dist(gen);
    int k = k_dist(gen);
    int ret = 0;
    bm_handle_t handle;

    ret = bm_dev_request(&handle, 0);
    if (ret) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return ret;
    }
    printf("KNN params: n_ref = %d, n_test = %d, n_feat = %d, n_class = %d, k = %d\n", n_ref, n_test, n_feat, n_class, k);
    float *ref_data = new float[n_ref * n_feat];
    float *ref_label = new float[n_ref];
    float *test_data = new float[n_test * n_feat];
    float *test_label = new float[n_test];

    generate_data(ref_data, test_data, n_ref, n_test, n_feat, n_class, ref_label, test_label);

    float *distance_tpu = new float[n_test * k];
    int *indices_tpu = new int[n_test * k];
    float *prediction_tpu = new float[n_test];

    struct timeval t1, t2;
    bm_device_mem_t ref_data_dev_mem;       // [n_ref, n_feat]
    bm_device_mem_t test_data_dev_mem;      // [n_test, n_feat]
    bm_device_mem_t distance_tpu_dev_mem;   // [n_test, k]
    bm_device_mem_t indices_tpu_dev_mem;    // [n_test, k]

    ret = bm_malloc_device_byte(handle, &ref_data_dev_mem, n_ref * n_feat * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte ref_data_dev_mem failed.\n");
        goto exit0;
    }
    ret = bm_memcpy_s2d(handle, ref_data_dev_mem, ref_data);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d ref_data failed!\n");
        goto exit1;
    }
    ret = bm_malloc_device_byte(handle, &test_data_dev_mem, n_test * n_feat * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte test_data_dev_mem failed.\n");
        goto exit1;
    }
    ret = bm_memcpy_s2d(handle, test_data_dev_mem, test_data);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d test_data failed!\n");
        goto exit2;
    }
    ret = bm_malloc_device_byte(handle, &distance_tpu_dev_mem, n_test * k * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte distance failed!\n");
        goto exit2;
    }
    ret = bm_malloc_device_byte(handle, &indices_tpu_dev_mem, n_test * k * sizeof(int));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte indices failed!\n");
        goto exit3;
    }

    gettimeofday(&t1, NULL);
    ret = bmcv_knn2(handle, ref_data_dev_mem, test_data_dev_mem, distance_tpu_dev_mem, indices_tpu_dev_mem, n_test, n_ref, n_feat, k);
    if (ret != BM_SUCCESS) {
        printf("KNN2 failed!\n");
        return ret;
    }
    gettimeofday(&t2, NULL);
    printf("KNN TPU using time = %ld(us)\n", TIME_COST_US(t1, t2));
    ret = bm_memcpy_d2s(handle, distance_tpu, distance_tpu_dev_mem);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_d2s distance failed\n");
        goto exit4;
    }
    ret = bm_memcpy_d2s(handle, indices_tpu, indices_tpu_dev_mem);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_d2s indices failed\n");
        goto exit4;
    }

    get_prediction(n_test, indices_tpu, k, ref_label, n_ref, prediction_tpu);

    printf("KNN TPU using time = %ld(us)\n", TIME_COST_US(t1, t2));

    print_result(n_class, n_test, test_label, prediction_tpu);
```

# bmcv_knn_match

在KNN算法的基础上添加多次匹配功能，并统计匹配的好特征点个数，距离为汉明距离。

## 处理器型号支持

该接口支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_knn_match(
  bm_handle_t handle,
  bm_device_mem_t ref_addr,
  bm_device_mem_t test_addr,
  bm_device_mem_t distance_addr,
  bm_device_mem_t good_match_addr,
  bm_device_mem_t match_index_addr,
  int n_ref,
  int n_ref_feat,
  int n_test_feat,
  int n_descriptor,
  float ratio_thresh);
```

## 参数说明

* `bm_handle_t handle`
  输入参数。bm_handle 句柄。

* `bm_device_mem_t ref_addr`
  输入参数。存放底库数据。形状为[n_ref x n_ref_feat, n_descriptor]。

* `bm_device_mem_t test_addr`
  输入参数。存放测试数据。形状为[n_test_feat, n_descriptor]。

* `bm_device_mem_t distance_addr`
  输出参数。存放KNN距离结果。形状为[n_ref x k, n_test_feat]。

* `bm_device_mem_t good_match_addr`
  输出参数。存放KNN好的匹配特征点结果。形状为[2, n_ref]。前n_ref个点为原始排列匹配好的特征点结果，后n_ref个点为降序排列后的匹配好的特征点结果。

* `bm_device_mem_t match_index_addr`
  输出参数。存放KNN好的匹配特征点结果降序排列后在底库的索引。形状为[n_ref]。

* `int n_ref`
  输入参数。存放底库数据个数。

* `int n_ref_feat`
  输入参数。存放每个底库数据的特征点个数。

* `int n_test_feat`
  输入参数。存放测试数据的特征点个数。

* `int n_descriptor`
  输入参数。存放每个特征点描述子个数。

* `float ratio_thresh`
  输入参数。最近邻比率。判断是否是匹配的好的特征点。

## 返回值说明

* `BM_SUCCESS`: 成功
* 其他: 失败

## 数据类型支持

输入数据目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

输出数据目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

由于KNN中使用汉明距离，输入参数须为无符号整数。

## 代码示例

```c
#include <iostream>
#include <random>
#include <unordered_map>
#include "bmcv_api_ext.h"
#include <queue>
#include <sys/time.h>

#define TIME_COST_US(start, end) ((end.tv_sec - start.tv_sec) * 1000000 + (end.tv_usec - start.tv_usec))

using namespace std;

void generate_data(
    int* ref_data,
    int* test_data,
    int n_ref,
    int n_ref_feat,
    int n_test_feat,
    int n_descriptor,
    int n_class,
    int* ref_label,
    int* test_label) {
    std::random_device rd;
    std::mt19937 gen(rd());

    std::vector<std::normal_distribution<>> distributions;
    for (int c = 0; c < n_class; c++) {
        double mean = 5.0 + 10.0 * c / (n_class - 1);
        double stddev = 1.0 + 0.5 * c;
        distributions.emplace_back(mean, stddev);
    }

    for (int n = 0; n < n_ref; n++) {
        for (int i = 0; i < n_ref_feat; i++) {
            int class_id = i % n_class;
            ref_label[n * n_ref_feat + i] = class_id;
            for (int j = 0; j < n_descriptor; j++) {
                int value;
                do {
                    value = static_cast<int>(std::round(distributions[class_id](gen)));
                } while (value < 0);
                ref_data[n * n_ref_feat * n_descriptor + i * n_descriptor + j] = value;
            }
        }
    }

    std::vector<float> class_proportions(n_class);
    float sum = 0.0f;
    for (int c = 0; c < n_class; c++) {
        class_proportions[c] = 1.0f / (c + 1);
        sum += class_proportions[c];
    }
    for (int c = 0; c < n_class; c++) {
        class_proportions[c] /= sum;
    }

    std::discrete_distribution<> test_dist(class_proportions.begin(), class_proportions.end());

    for (int i = 0; i < n_test_feat; i++) {
        int class_id = test_dist(gen);
        test_label[i] = class_id;

        for (int j = 0; j < n_descriptor; j++) {
            int value;
            do {
                value = static_cast<int>(std::round(distributions[class_id](gen)));
            } while (value < 0);
            test_data[i * n_descriptor + j] = value;
        }
    }
}

int main() {
    struct timespec tp;
    clock_gettime(0, &tp);
    srand(tp.tv_nsec);

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<int> ref_dist(200, 1000);
    std::uniform_int_distribution<int> ref_feat_dist(200, 500);
    std::uniform_int_distribution<int> test_feat_dist(200, 500);
    std::uniform_int_distribution<int> descriptor_dist(10, 55);
    std::uniform_int_distribution<int> class_dist(2, 12);

    int n_ref = ref_dist(gen);
    int n_ref_feat = ref_feat_dist(gen);
    int n_test_feat = test_feat_dist(gen);
    int n_descriptor = descriptor_dist(gen);
    int n_class = class_dist(gen);
    float ratio_thresh = 0.7;
    int ret = 0;
    bm_handle_t handle;

    ret = bm_dev_request(&handle, 0);
    if (ret) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return ret;
    }

    printf("KNN_match params: n_ref = %d, n_ref_feat = %d, n_test_feat = %d, n_descriptor = %d, n_class = %d, ratio_thresh = %f\n", n_ref, n_ref_feat, n_test_feat, n_descriptor, n_class, ratio_thresh);

    int *ref_data = new int[n_ref * n_ref_feat * n_descriptor];
    int *ref_label = new int[n_ref * n_ref_feat];
    int *test_data = new int[n_test_feat * n_descriptor];
    int *test_label = new int[n_test_feat];
    int k = 2;

    generate_data(ref_data, test_data, n_ref, n_ref_feat, n_test_feat, n_descriptor, n_class, ref_label, test_label);

    float *distance_tpu = new float[n_ref * n_test_feat * k];
    int *good_match_tpu = new int[2 * n_ref];
    int *match_index = new int[n_ref];
    struct timeval t1, t2;
    bm_device_mem_t ref_data_dev_mem;
    bm_device_mem_t test_data_dev_mem;
    bm_device_mem_t distance_tpu_dev_mem;
    bm_device_mem_t good_match_dev_mem;
    bm_device_mem_t index_sorted_dev_mem;
    
    ret = bm_malloc_device_byte(handle, &ref_data_dev_mem, n_ref * n_ref_feat * n_descriptor * sizeof(int));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte ref_data_dev_mem failed.\n");
        goto exit0;
    }
    ret = bm_memcpy_s2d(handle, ref_data_dev_mem, ref_data);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d ref_data failed!\n");
        goto exit1;
    }
    ret = bm_malloc_device_byte(handle, &test_data_dev_mem, n_test_feat * n_descriptor * sizeof(int));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte test_data_dev_mem failed.\n");
        goto exit1;
    }
    ret = bm_memcpy_s2d(handle, test_data_dev_mem, test_data);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d test_data failed!\n");
        goto exit2;
    }
    ret = bm_malloc_device_byte(handle, &distance_tpu_dev_mem, n_ref * n_test_feat * k * sizeof(int));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte distance failed!\n");
        goto exit2;
    }
    ret = bm_malloc_device_byte(handle, &good_match_dev_mem, (2 * n_ref) * sizeof(int));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte indices failed!\n");
        goto exit3;
    }

    ret = bm_malloc_device_byte(handle, &index_sorted_dev_mem, n_ref * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte indices failed!\n");
        goto exit4;
    }

exit4:
    bm_free_device(handle, indices_tpu_dev_mem);
exit3:
    bm_free_device(handle, distance_tpu_dev_mem);
exit2:
    bm_free_device(handle, test_data_dev_mem);
exit1:
    bm_free_device(handle, ref_data_dev_mem);
exit0:
    delete[] ref_data;
    delete[] ref_label;
    delete[] test_data;
    delete[] test_label;
    delete[] distance_tpu;
    delete[] indices_tpu;
    delete[] prediction_tpu;
    bm_dev_free(handle);
    return ret;
}
```

```c
gettimeofday(&t1, NULL);
ret = bmcv_knn_match(handle, ref_data_dev_mem, test_data_dev_mem, distance_tpu_dev_mem, good_match_dev_mem, index_sorted_dev_mem, n_ref, n_ref_feat, n_test_feat, n_descriptor, ratio_thresh);
if (ret != BM_SUCCESS) {
    printf("KNN_match failed!\n");
    return ret;
}
gettimeofday(&t2, NULL);

ret = bm_memcpy_d2s(handle, distance_tpu, distance_tpu_dev_mem);
if (ret != BM_SUCCESS) {
    printf("bm_memcpy_d2s distance failed\n");
    goto exit5;
}
ret = bm_memcpy_d2s(handle, good_match_tpu, good_match_dev_mem);
if (ret != BM_SUCCESS) {
    printf("bm_memcpy_d2s good_match failed\n");
    goto exit5;
}
ret = bm_memcpy_d2s(handle, match_index, index_sorted_dev_mem);
if (ret != BM_SUCCESS) {
    printf("bm_memcpy_d2s match_index failed\n");
    goto exit5;
}

printf("KNN TPU using time = %ld(us)\n", TIME_COST_US(t1, t2));
printf("best_match_time = %d, index = %d\n", good_match_tpu[n_ref], match_index[0]);

exit5:
    bm_free_device(handle, index_sorted_dev_mem);
exit4:
    bm_free_device(handle, good_match_dev_mem);
exit3:
    bm_free_device(handle, distance_tpu_dev_mem);
exit2:
    bm_free_device(handle, test_data_dev_mem);
exit1:
    bm_free_device(handle, ref_data_dev_mem);
exit0:
    delete[] ref_data;
    delete[] ref_label;
    delete[] test_data;
    delete[] test_label;
    delete[] distance_tpu;
    delete[] good_match_tpu;
    delete[] match_index;
    bm_dev_free(handle);
    return ret;
```

# bmcv_image_laplacian

梯度计算laplacian算子。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_laplacian(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            unsigned int ksize);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_image input
  输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image output
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。如果不主动分配将在 api 内部进行自行分配。

* int ksize = 3
  Laplacian核的大小，必须是1或3。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下 image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1   | FORMAT_GRAY       | FORMAT_GRAY       |

目前支持以下 data_type:

| num | data_type             |
|-----|----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1、在调用该接口之前必须确保输入的 image 内存已经申请。
2、input output 的 data_type必须相同。
3、目前支持图像的最大width为2048。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int height = 1080;
    int width = 1920;
    unsigned int ksize = 3;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bm_handle_t handle;
    bm_image_data_format_ext data_type = DATA_TYPE_EXT_1N_BYTE;
    bm_image input;
    bm_image output;
    unsigned char* input_data = (unsigned char*)malloc(width * height * sizeof(unsigned char));
    unsigned char* tpu_out = (unsigned char*)malloc(width * height * sizeof(unsigned char));
    const char* src_name = "path/to/src";
    const char* dst_name = "path/to/dst";

    bm_dev_request(&handle, 0);
    bm_image_create(handle, height, width, fmt, data_type, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_create(handle, height, width, fmt, data_type, &output);
    bm_image_alloc_dev_mem(output);

    readBin(src_name, input_data, width * height);
    bm_image_copy_host_to_device(input, (void**)&input_data);
    bmcv_image_laplacian(handle, input, output, ksize);
    bm_image_copy_device_to_host(output, (void **)&tpu_out);
    writeBin(dst_name, tpu_out, width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    bm_dev_free(handle);
    free(input_data);
    free(tpu_out);
    return 0;
}
```

# bmcv_lap_matrix

拉普拉斯矩阵是图论中一个非常重要的概念，用于分析图的性质。

**处理器型号支持：**

该接口支持BM1684X。

**接口形式：**

```c
bm_status_t bmcv_lap_matrix(
            bm_handle_t handle,
            bm_device_mem_t input,
            bm_device_mem_t output,
            int row,
            int col);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input
  输入参数。输入矩阵的 device 空间。其大小为 row * col * sizeof(float32)。

* bm_device_mem_t output
  输出参数。输出矩阵的 device 空间。其大小为 row * col * sizeof(float32)。

* int row
  输入参数。矩阵的行数。

* int col
  输入参数。矩阵的列数。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他:失败

**注意事项：**

1、目前该接口只支持矩阵的数据类型为float。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
int main()
{
    int row = 1024;
    int col = 1024;
    float* input_addr = (float*)malloc(row * col * sizeof(float));
    float* output_addr = (float*)malloc(row * col * sizeof(float));
    bm_handle_t handle;
    bm_status_t ret = BM_SUCCESS;
    bm_device_mem_t input, output;
    int i;

    for (i = 0; i < row * col; ++i) {
        input_addr[i] = (float)rand() / RAND_MAX;
    }

    ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        exit(-1);
    }

    ret = bm_malloc_device_byte(handle, &input, row * col * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte failed. ret = %d\n", ret);
        exit(-1);
    }

    ret = bm_malloc_device_byte(handle, &output, row * col * sizeof(float));
    if (ret != BM_SUCCESS) {
        printf("bm_malloc_device_byte failed. ret = %d\n", ret);
        exit(-1);
    }

    ret = bm_memcpy_s2d(handle, input, input_addr);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d failed. ret = %d\n", ret);
        exit(-1);
    }

    ret = bmcv_lap_matrix(handle, input, output, row, col);
    if (ret != BM_SUCCESS) {
        printf("bmcv_lap_matrix failed. ret = %d\n", ret);
        exit(-1);
    }

    ret = bm_memcpy_d2s(handle, output_addr, output);
    if (ret != BM_SUCCESS) {
        printf("bm_memcpy_d2s failed. ret = %d\n", ret);
        exit(-1);
    }

    free(input_addr);
    free(output_addr);
    bm_free_device(handle, input);
    bm_free_device(handle, output);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_lkpyramid

LK金字塔光流算法。完整的使用步骤包括创建、执行、销毁三步。该算法前半部分使用智能视觉深度学习处理器，而后半部分为串行运算需要使用处理器，因此对于PCIe模式，建议使能处理器进行加速，具体步骤参考第5章节。

## 创建

由于该算法的内部实现需要一些缓存空间，为了避免重复申请释放空间，将一些准备工作封装在该创建接口中，只需要在启动前调用一次便可以多次调用execute接口（创建函数参数不变的情况下），接口形式如下：

```c
bm_status_t bmcv_image_lkpyramid_create_plan(
            bm_handle_t handle,
            void*& plan,
            int width,
            int height,
            int winW = 21,
            int winH = 21,
            int maxLevel = 3);
```

**处理器型号支持：**

该接口仅支持BM1684。

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* void*& plan
  输出参数。执行阶段所需要的句柄。

* int width
  输入参数。待处理图像的宽度。

* int height
  输入参数，待处理图像的高度。

* int winW
  输入参数，算法处理窗口的宽度，默认值为21。

* int winH
  输入参数，算法处理窗口的高度，默认值为21。

* int maxLevel
  输入参数，金字塔处理的高度，默认值为3, 目前支持的最大值为5。该参数值越大，算法执行时间越长，建议根据实际效果选择可接受的最小值。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他：失败

# 执行

使用上述接口创建后的plan就可以开始真正的执行阶段了，接口格式如下：

```c
typedef struct {
    float x;
    float y;
} bmcv_point2f_t;

typedef struct {
    int type;   // 1: maxCount   2: eps   3: both
    int max_count;
    double epsilon;
} bmcv_term_criteria_t;

bm_status_t bmcv_image_lkpyramid_execute(
            bm_handle_t handle,
            void* plan,
            bm_image prevImg,
            bm_image nextImg,
            int ptsNum,
            bmcv_point2f_t* prevPts,
            bmcv_point2f_t* nextPts,
            bool* status,
            bmcv_term_criteria_t criteria = {3, 30, 0.01});
```

**输入参数说明：**

* bm_handle_t handle
  输入参数。bm_handle 句柄

* const void *plan
  输入参数。创建阶段所得到的句柄。

* bm_image prevImg
  输入参数。前一幅图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* bm_image nextImg
  输入参数。后一幅图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* int ptsNum
  输入参数。需要追踪点的数量。

* bmcv_point2f_t* prevPts
  输入参数。需要追踪点在前一幅图中的坐标指针，其指向的长度为ptsNum。

* bmcv_point2f_t* nextPts
  输出参数。计算得到的追踪点在后一张图像中坐标指针，其指向的长度为ptsNum。

* bool* status
  输出参数。nextPts中的各个追踪点是否有效，其指向的长度为ptsNum，与nextPts中的坐标一一对应，如果有效则为true，否则为false（表示没有在后一张图像中找到对应的跟踪点，可能超出图像范围）。

* bmcv_term_criteria_t criteria
  输入参数。迭代结束标准，type表示以哪个参数作为结束判断条件：若为1则以迭代次数max_count为结束判断参数，若为2则以误差epsilon为结束判断参数，若为3则两者均需满足。该参数会影响执行时间，建议根据实际效果选择最优的停止迭代标准。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

# 销毁

当执行完成后需要销毁所创建的句柄。该接口必须和创建接口bmcv_image_lkpyramid_create_plan成对使用。

```c
void bmcv_image_lkpyramid_destroy_plan(bm_handle_t handle, void *plan);
```

**格式支持：**

该接口目前支持以下 image_format:

| num | image_format |
|-----|--------------|
| 1   | FORMAT_GRAY  |

目前支持以下 data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

# 示例代码

```c
#include <iostream>
#include <fstream>
#include <thread>
#include <mutex>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include "bmcv_api_ext.h"
#include "test_misc.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

int main()
{
    bm_handle_t handle;
    int width = 1024;
    int height = 1024;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bm_image prevImg;
    bm_image nextImg;
    void *plan = nullptr;
    unsigned char* prevPtr = new unsigned char[width * height];
    unsigned char* nextPtr = new unsigned char[width * height];
    bmcv_term_criteria_t criteria = {3, 10, 0.03};
    int ptsNum = 10;
    int kw = 41;
    int kh = 47;
    int maxLevel = 3;
    bool* status = new bool [ptsNum];
    bmcv_point2f_t* prevPts = new bmcv_point2f_t [ptsNum];
    bmcv_point2f_t* nextPts = new bmcv_point2f_t [ptsNum];
    const char *src_names[2] = {"path/to/src0", "path/to/src1"};

    readBin(src_names[0], prevPtr, width * height);
    readBin(src_names[1], nextPtr, width * height);

    for (int i = 0; i < ptsNum; ++i) {
        prevPts[i].x = (float)rand() / RAND_MAX;
        nextPts[i].y = (float)rand() / RAND_MAX;
    }

    bm_dev_request(&handle, 0);
    bmcv_open_cpu_process(handle);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &prevImg);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &nextImg);
    bm_image_alloc_dev_mem(prevImg);
    bm_image_alloc_dev_mem(nextImg);
    bm_image_copy_host_to_device(prevImg, (void **)(&prevPtr));
    bm_image_copy_host_to_device(nextImg, (void **)(&nextPtr));

    bmcv_image_lkpyramid_create_plan(handle, plan, width, height, kw, kh, maxLevel);
    bmcv_image_lkpyramid_execute(handle, plan, prevImg, nextImg, ptsNum,
                                prevPts, nextPts, status, criteria);
    bmcv_image_lkpyramid_destroy_plan(handle, plan);
    bmcv_close_cpu_process(handle);

    bm_image_destroy(prevImg);
    bm_image_destroy(nextImg);
    bm_dev_free(handle);
    delete[] prevPtr;
    delete[] nextPtr;
    delete[] prevPts;
    delete[] nextPts;
    delete[] status;
    return 0;
}
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
  当 C 是 int8 或者 int16 时，执行上述公式的功能， 而其符号取决于A和B，当A和B均为无符号时C才为无符号数，否则为有符号;
  当 C 是 float32 时，执行上述公式的功能。
* rshift_bit 是矩阵乘积的右移数，当 C 是 int8 或者 int16 时才有效，由于矩阵的乘积有可能会超出 8-bit 或者 16-bit 的范围，所以用户可以配置一定的右移数，通过舍弃部分精度来防止溢出。
* alpha和beta 是 float32 的常系数，当 C 是 float32 时才有效。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

**输入参数说明：**

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
  输入参数。输出的结果矩阵数据类型，0表示是 int8，1表示int16, 2表示 float32。

* bool is_B_trans
  输入参数。输入右矩阵B是否需要计算前做转置。

* float alpha
  常系数，输入矩阵 A 和 B 相乘之后再乘上该系数，只有当 result_type 等于2时才有效，默认值为1。

* float beta
  常系数，在输出结果矩阵 C 之前，加上该偏移量，只有当 result_type 等于2时才有效，默认值为0。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**示例代码**

```c
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "test_misc.h"

int main()
{
    int M = 3, N = 4, K = 5;
    int result_type = 1;
    bool is_B_trans = false;
    int rshift_bit = 0;
    char* A = new char[M * K];
    char* B = new char[N * K];
    short* C = new short[M * N];
    bm_handle_t handle;

    bm_dev_request(&handle, 0);
    memset(A, 0x11, M * K * sizeof(char));
    memset(B, 0x22, N * K * sizeof(char));
    bmcv_matmul(handle, M, N, K, bm_mem_from_system((void *)A), bm_mem_from_system((void *)B),
                bm_mem_from_system((void *)C), 1, 1, rshift_bit, result_type, is_B_trans);

    delete[] A;
    delete[] B;
    delete[] C;
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_matrix_prune

对矩阵进行稀疏化处理，参数p用于控制保留的边的比例。

1.根据数据点的数量选择不同的策略来确定每个点保留的邻接点数量。
2.对每个点，将与其余点的相似度进行排序，保留相似度最高的部分，并将其余的设置为0，从而使得矩阵变得稀疏。
3.返回稀疏化后的对称相似度矩阵（通过取原矩阵与其转置的平均实现对称化）。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

```c
bm_status_t bmcv_matrix_prune(
            bm_handle_t handle,
            bm_device_mem_t input_data_global_addr,
            bm_device_mem_t output_data_global_addr,
            bm_device_mem_t sort_index_global_addr,
            int matrix_dims,
            float p);
```

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_device_mem_t input_data_global_addr
  输入参数。存放输入数据的设备内存地址。

* bm_device_mem_t output_data_global_addr
  输出参数。存放输出数据的设备内存地址。

* bm_device_mem_t sort_index_global_addr
  输入参数。暂存排序后索引的设备内存地址。

* int matrix_dims
  输入参数。矩阵维度，同时控制矩阵的行和列。

* float p
  输入参数。控制保留的边的比例。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

## 数据类型支持

输入数据目前支持以下 data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

输出数据目前支持以下 data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_FLOAT32 |

## 注意事项

1. 在调用该接口之前必须确保所用设备内存已经申请
2. 该接口支持的输入矩阵维度范围为8-6000，参数p的范围为0.0-1.0

## 代码示例

```c
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "test_misc.h"

int main()
{
    int matrix_dims = 2164;
    float p = 0.5;
    bm_handle_t handle;
    float* output_tpu = (float*)malloc(matrix_dims * matrix_dims * sizeof(float));
    float* input_data = (float*)malloc(matrix_dims * matrix_dims * sizeof(float));
    bm_device_mem_t input_data_global_addr, output_data_global_addr, sort_index_global_addr;
    bm_dev_request(&handle, 0);

    for (int i = 0; i < matrix_dims; ++i) {
        for (int j = 0; j < matrix_dims; ++j) {
            input_data[i * matrix_dims + j] = (float)rand() / RAND_MAX;
        }
    }

    bm_malloc_device_byte(handle, &input_data_global_addr, sizeof(float) * matrix_dims * matrix_dims);
    bm_malloc_device_byte(handle, &output_data_global_addr, sizeof(float) * matrix_dims * matrix_dims);
    bm_malloc_device_byte(handle, &sort_index_global_addr, sizeof(DT_INT32) * matrix_dims * matrix_dims);
    bm_memcpy_s2d(handle, input_data_global_addr, bm_mem_get_system_addr(bm_mem_from_system(input_data)));
    bmcv_matrix_prune(handle, input_data_global_addr, output_data_global_addr,
                    sort_index_global_addr, matrix_dims, p);
    bm_memcpy_d2s(handle, bm_mem_get_system_addr(bm_mem_from_system(output_tpu)), output_data_global_addr);

    bm_free_device(handle, input_data_global_addr);
    bm_free_device(handle, sort_index_global_addr);
    bm_free_device(handle, output_data_global_addr);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_median_blur

该接口用于对图像进行中值滤波。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_median_blur(
    bm_handle_t handle,
    bm_device_mem_t input_data_global_addr,
    bm_device_mem_t padded_input_data_global_addr,
    unsigned char *output,
    int width,
    int height,
    int format,
    int ksize);
```

## 参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_device_mem_t input_data_global_addr
  输入参数。输入图像的 device 空间

* bm_device_mem_t padded_input_data_global_addr
  输入参数。输入图像pad0后的 device 空间

* unsigned char* output
  输出参数。中值滤波后的输出图像

* int width
  输入参数。表示输入图像的宽

* int height
  输入参数。表示输入图像的高

* int format
  输入参数。表示输入图像的格式

* int ksize
  输入参数。表示中值滤波核尺寸

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

该接口目前支持以下 image_format：

| num | input image_format   | output image_format  |
|-----|----------------------|----------------------|
| 1   | FORMAT_YUV444P       | FORMAT_YUV444P       |
| 2   | FORMAT_RGBP_SEPARATE | FORMAT_RGBP_SEPARATE |
| 3   | FORMAT_BGRP_SEPARATE | FORMAT_BGRP_SEPARATE |
| 4   | FORMAT_GRAY          | FORMAT_GRAY          |

目前支持以下 data_type：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用该接口之前需确保输入的 input_data_global_addr，padded_input_data_global_addr 和 output 内存已经申请
2. 支持的图像宽高范围为8*8～4096*3000
3. 支持的中值滤波核尺寸为3*3，5*5, 7*7, 9*9

## 代码示例

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include "stdlib.h"
#include "string.h"
#include <sys/time.h>
#include <pthread.h>

#define TIME_COST_US(start, end) ((end.tv_sec - start.tv_sec) * 1000000 + (end.tv_usec - start.tv_usec))

static void read_bin(const char *input_path, unsigned char *input_data, int width, int height, int channel) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
        printf("无法打开输出文件 %s\n", input_path);
        return;
    }
    if(fread(input_data, sizeof(char), width * height * channel, fp_src) != 0) {
        printf("read image success\n");
    }
    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int width, int height, int channel) {
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL) {
        printf("无法打开输出文件 %s\n", output_path);
        return;
    }
    fwrite(output_data, sizeof(unsigned char), width * height * channel, fp_dst);
    fclose(fp_dst);
}

int main(int argc, char *args[]) {
    char *input_path = NULL;
    char *output_path = NULL;
    if (argc > 1) input_path = args[1];
    if (argc > 2) output_path = args[2];

    int width = 1920;
    int height = 1080;
    int ksize = 9;
    int format = FORMAT_RGBP_SEPARATE;
    int channel = 3;
    int dev_id = 0;
    bm_handle_t handle;
    bm_dev_request(&handle, dev_id);
    unsigned char *input_data = (unsigned char*)malloc(width * height * 3);
    unsigned char *output_tpu = (unsigned char*)malloc(width * height * 3);
    read_bin(input_path, input_data, width, height, channel);
    int padd_width = ksize - 1 + width;
    int padd_height = ksize - 1 + height;
    bm_device_mem_t input_data_global_addr, padded_input_data_global_addr;
    bm_malloc_device_byte(handle, &input_data_global_addr, channel * width * height);
    bm_malloc_device_byte(handle, &padded_input_data_global_addr, channel * padd_width * padd_height);
    struct timeval t1, t2;
    bm_memcpy_s2d(handle, input_data_global_addr, bm_mem_get_system_addr(bm_mem_from_system(input_data)));
    gettimeofday(&t1, NULL);
    if(BM_SUCCESS != bmcv_image_median_blur(handle, input_data_global_addr, padded_input_data_global_addr, output_tpu, width, height, format, ksize)){
        printf("bmcv_image_median_blur error\n");
        return -1;
    }
    gettimeofday(&t2, NULL);
    printf("median_blur TPU using time = %ld(us)\n", TIME_COST_US(t1, t2));
    write_bin(output_path, output_tpu, width, height, channel);
    bm_free_device(handle, input_data_global_addr);
    bm_free_device(handle, padded_input_data_global_addr);
    free(input_data);
    free(output_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_morph

可以实现对图像的基本形态学运算，包括膨胀(Dilation)和腐蚀(Erosion)。

用户可以分为以下两步使用该功能：

## 获取 Kernel 的 Device Memory

可以在初始化时使用以下接口获取存储 Kernel 的 Device Memory，当然用户也可以自定义 Kernel 直接忽略该步骤。

函数通过传入所需 Kernel 的大小和形状，返回对应的 Device Memory 给后面的形态学运算接口使用，用户应用程序的最后需要用户手动释放该空间。

### 处理器型号支持

该接口仅支持BM1684。

### 接口形式

```c
typedef enum {
    BM_MORPH_RECT,
    BM_MORPH_CROSS,
    BM_MORPH_ELLIPSE
} bmcv_morph_shape_t;

bm_device_mem_t bmcv_get_structuring_element(
                bm_handle_t handle,
                bmcv_morph_shape_t shape,
                int kw,
                int kh);
```

### 参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bmcv_morph_shape_t shape
  输入参数。表示 Kernel 的形状，目前支持矩形、十字、椭圆

* int kw
  输入参数。Kernel 的宽度

* int kh
  输入参数。Kernel 的高度

### 返回值说明

返回 Kernel 对应的 Device Memory 空间。

## 形态学运算

目前支持腐蚀和膨胀操作，用户也可以通过这两个基本操作的组合实现以下功能：

* 开运算(Opening)
* 闭运算(Closing)
* 形态梯度(Morphological Gradient)
* 顶帽(Top Hat)
* 黑帽(Black Hat)

### 接口形式

```c
bm_status_t bmcv_image_erode(
            bm_handle_t handle,
            bm_image src,
            bm_image dst,
            int kw,
            int kh,
            bm_device_mem_t kmem);

bm_status_t bmcv_image_dilate(
            bm_handle_t handle,
            bm_image src,
            bm_image dst,
            int kw,
            int kh,
            bm_device_mem_t kmem);
```

### 参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄

* bm_image src
  输入参数。需处理图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存

* bm_image dst
  输出参数。处理后图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存，如用户不申请内部会自动申请

* int kw
  输入参数。Kernel 的宽度

* int kh
  输入参数。Kernel 的高度

* bm_device_mem_t kmem
  输入参数。存储 Kernel 的 Device Memory 空间，可以通过接口bmcv_get_structuring_element获取，用户也可以自定义，其中值为1表示选中该像素，值为0表示忽略该像素

### 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

# bmcv_image_mosaic

该接口用于在图像上打一个或多个马赛克。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_mosaic(
            bm_handle_t handle,
            int mosaic_num,
            bm_image input,
            bmcv_rect_t* mosaic_rect,
            int is_expand);
```

## 传入参数说明

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* int mosaic_num
  输入参数。马赛克数量，指 mosaic_rect 指针中所包含的 bmcv_rect_t 对象个数。

* bm_image input
  输入参数。需要打马赛克的 bm_image 对象。

* bmcv_rect_t* mosaic_rect
  输入参数。马赛克对象指针，包含每个马赛克起始点和宽高。具体内容参考下面的数据类型说明。

* int is_expand
  输入参数。是否扩列。值为0时表示不扩列, 值为1时表示在原马赛克周围扩列一个宏块(8个像素)。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 数据类型说明

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

* start_x 描述了马赛克在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)。
* start_y 描述了马赛克在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)。
* crop_w 描述的马赛克的宽度。
* crop_h 描述的马赛克的高度。

## 注意事项

1. 输入和输出的数据类型必须为：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

输入的色彩格式可支持：

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

2. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

3. 如果马赛克宽高非8对齐，则会自动向上8对齐，若在边缘区域，则8对齐时会往非边缘方向延展。

4. 如果马赛克区域超出原图宽高，超出部分会自动贴到原图边缘。

5. 仅支持8x8以上的马赛克尺寸。

## 代码示例

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>
#include <sstream>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle = NULL;
    int width = 1024;
    int height = 1024;
    int dev_id = 0;
    int mosaic_num = 1;
    bm_image_format_ext src_fmt = FORMAT_GRAY;
    bm_image src;
    bmcv_rect_t* rect = new bmcv_rect_t [mosaic_num];
    unsigned char* data_ptr = new unsigned char[width * height];
    unsigned int is_expand = 1;
    const char *src_name = "path/to/src";
    const char *dst_name = "path/to/dst";

    for(int i = 0; i < mosaic_num; i++){
        rect[i].start_x = 8 + i * 8;
        rect[i].start_y = 8 + i * 8;
        rect[i].crop_w = 8 + i * 8;
        rect[i].crop_h = 8 + i * 8;
    }

    readBin(src_name, data_ptr, width * height);
    bm_dev_request(&handle, dev_id);
    bm_image_create(handle, height, width, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_alloc_dev_mem(src);
    bm_image_copy_host_to_device(src, (void**)&data_ptr);
    bmcv_image_mosaic(handle, mosaic_num, src, rect, is_expand);
    bm_image_copy_device_to_host(src, (void**)&data_ptr);
    writeBin(dst_name, data_ptr,  width * height);

    bm_image_destroy(src);
    bm_dev_free(handle);
    delete[] rect;
    delete[] data_ptr;
    return 0;
}
```

# bmcv_nms

该接口用于消除网络计算得到过多的物体框，并找到最佳物体框。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_nms(
            bm_handle_t handle,
            bm_device_mem_t input_proposal_addr,
            int proposal_size,
            float nms_threshold,
            bm_device_mem_t output_proposal_addr);
```

## 参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input_proposal_addr
  输入参数。输入物体框数据所在地址，输入物体框数据结构为 face_rect_t,详见下面数据结构说明。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int proposal_size
  输入参数。物体框个数。

* float nms_threshold
  输入参数。过滤物体框的阈值，分数小于该阈值的物体框将会被过滤掉。

* bm_device_mem_t output_proposal_addr
  输出参数。输出物体框数据所在地址，输出物体框数据结构为 nms_proposal_t，详见下面数据结构说明。需要调用 bm_mem_from_system() 将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

## 返回值

* BM_SUCCESS: 成功
* 其他: 失败

## 数据类型说明

face_rect_t 描述了一个物体框坐标位置以及对应的分数。

```c
typedef struct
{
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
}face_rect_t;
```

* x1 描述了物体框左边缘的横坐标
* y1 描述了物体框上边缘的纵坐标
* x2 描述了物体框右边缘的横坐标
* y2 描述了物体框下边缘的纵坐标
* score 描述了物体框对应的分数

nms_proposal_t 描述了输出物体框的信息。

```c
typedef struct
{
    face_rect_t face_rect[MAX_PROPOSAL_NUM];
    int size;
    int capacity;
    face_rect_t *begin;
    face_rect_t *end;
} nms_proposal_t;
```

* face_rect 描述了经过过滤后的物体框信息
* size 描述了过滤后得到的物体框个数
* capacity 描述了过滤后物体框最大个数
* begin 暂不使用
* end 暂不使用

## 代码示例

```c
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <algorithm>
#include <functional>
#include <iostream>
#include <memory>
#include <set>
#include <string>
#include <vector>
#include <math.h>
#include "bmcv_api.h"
#include "bmcv_internal.h"
#include "bmcv_common_bm1684.h"
#include "bmcv_api_ext.h"

int main()
{
    face_rect_t *proposal_rand = new face_rect_t[MAX_PROPOSAL_NUM];
    nms_proposal_t *output_proposal = new nms_proposal_t[1];
    int proposal_size =32;
    float nms_threshold = 0.2;
    bm_handle_t handle;
    bm_dev_request(&handle, 0);

    for (int i = 0; i < proposal_size; i++) {
        proposal_rand[i].x1 = ((float)(rand() % 100)) / 10;
        proposal_rand[i].x2 = proposal_rand[i].x1 + ((float)(rand() % 100)) / 10;
        proposal_rand[i].y1 = ((float)(rand() % 100)) / 10;
        proposal_rand[i].y2 =proposal_rand[i].y1 + ((float)(rand() % 100)) / 10;
        proposal_rand[i].score = (float)rand() / (float)RAND_MAX;
    }
    bmcv_nms(handle, bm_mem_from_system(proposal_rand), proposal_size, nms_threshold,
            bm_mem_from_system(output_proposal));
    delete[] proposal_rand;
    delete[] output_proposal;
    bm_dev_free(handle);
    return 0;
}
```

## 注意事项

该 api 可输入的最大 proposal 数为 56000。

# bmcv_nms_ext

该接口是bmcv_nms接口的广义形式，支持Hard_NMS/Soft_NMS/Adaptive_NMS/SSD_NMS，用于消除网络计算得到过多的物体框，并找到最佳物体框。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_nms_ext(
            bm_handle_t handle,
            bm_device_mem_t input_proposal_addr,
            int proposal_size,
            float nms_threshold,
            bm_device_mem_t output_proposal_addr,
            int topk,
            float score_threshold,
            int nms_alg,
            float sigma,
            int weighting_method,
            float* densities,
            float eta);
```

**参数说明:**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* bm_device_mem_t input_proposal_addr
  输入参数。输入物体框数据所在地址，输入物体框数据结构为 face_rect_t,详见下面数据结构说明。需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int proposal_size
  输入参数。物体框个数。

* float nms_threshold
  输入参数。过滤物体框的阈值，分数小于该阈值的物体框将会被过滤掉。

* bm_device_mem_t output_proposal_addr
  输出参数。输出物体框数据所在地址，输出物体框数据结构为 nms_proposal_t，详见下面数据结构说明。需要调用 bm_mem_from_system() 将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int topk
  输入参数。当前未使用，为后续可能的的扩展预留的接口。

* float score_threshold
  输入参数。当使用Soft_NMS或者Adaptive_NMS时，最低的score threshold。当score低于该值时，score所对应的框将被过滤掉。

* int nms_alg
  输入参数。不同的NMS算法的选择，包括 Hard_NMS/Soft_NMS/Adaptive_NMS/SSD_NMS。

* float sigma
  输入参数。当使用Soft_NMS或者Adaptive_NMS时，Gaussian re-score函数的参数。

* int weighting_method
  输入参数。当使用Soft_NMS或者Adaptive_NMS时，re-score函数选项：包括线性权值和Gaussian权值。可选参数：

```c
typedef enum {
    LINEAR_WEIGHTING = 0,
    GAUSSIAN_WEIGHTING,
    MAX_WEIGHTING_TYPE
} weighting_method_e;
```

线性权值表达式如下：

$$ s_i = \begin{cases} s_i,  & {iou(\mathcal{M}, b_i)<N_t} \\ s_i \times (1-iou(\mathcal{M},b_i)), & {iou(\mathcal{M}, b_i) \geq N_t} \end{cases} $$

Gaussian权值表达式如下：

$$ s_i = s_i \times e^{-iou(\mathcal{M}, \  b_i)^2/\sigma} $$

上面两个表达式中，$\mathcal{M}$ 表示当前score最大的物体框，$b_i$ 表示其他score比 $\mathcal{M}$ 低的物体框，$s_i$ 表示其他score比 $\mathcal{M}$ 低的物体框的score值，$N_t$ 表示NMS门限，$\sigma$ 对应本接口的参数 float sigma。

* float\* densities
  输入参数。Adaptive-NMS密度值。

* float eta
  输入参数。SSD-NMS系数，用于调整iou阈值。

**返回值:**

* BM_SUCCESS: 成功
* 其他: 失败

**代码示例:**

```c
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <algorithm>
#include <functional>
#include <iostream>
#include <memory>
#include <set>
#include <string>
#include <vector>
#include <math.h>
#include "bmcv_api.h"
#include "bmcv_internal.h"
#include "bmcv_common_bm1684.h"
#include "bmcv_api_ext.h"

int main()
{
    float nms_threshold = 0.22;
    float nms_score_threshold = 0.22;
    float sigma = 0.4;
    int proposal_size = 500;
    int weighting_method = GAUSSIAN_WEIGHTING;
    int nms_type = SOFT_NMS; // ADAPTIVE NMS / HARD NMS / SOFT NMS
    face_rect_t* proposal_rand = (face_rect_t*)malloc(MAX_PROPOSAL_NUM * sizeof(face_rect_t));
    nms_proposal_t* output_proposal = (nms_proposal_t*)malloc(1 * sizeof(nms_proposal_t));
    float* densities = (float*)malloc(proposal_size * sizeof(float));
    float eta = ((float)(rand() % 10)) / 10;
    bm_handle_t handle;

    bm_dev_request(&handle, 0);
    for (int32_t i = 0; i < proposal_size; i++) {
        proposal_rand[i].x1 = ((float)(rand() % 100)) / 10;
        proposal_rand[i].x2 = proposal_rand[i].x1 + ((float)(rand() % 100)) / 10;
        proposal_rand[i].y1 = ((float)(rand() % 100)) / 10;
        proposal_rand[i].y2 = proposal_rand[i].y1  + ((float)(rand() % 100)) / 10;
        proposal_rand[i].score = ((float)(rand() % 100)) / 10;
        densities[i] = (float)rand() / (float)RAND_MAX;
    }

    bmcv_nms_ext(handle, bm_mem_from_system(proposal_rand), proposal_size, nms_threshold,
                bm_mem_from_system(output_proposal), 1, nms_score_threshold,
                nms_type, sigma, weighting_method, densities, eta);

    free(proposal_rand);
    free(output_proposal);
    free(densities);
    bm_dev_free(handle);
    return 0;
}
```

**注意事项:**

该 api 可输入的最大 proposal 数为 1024。

# bmcv_image_put_text

可以实现在一张图像上写字的功能（中英文），并支持指定字的颜色、大小和宽度。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式：**

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

**参数说明：**

* bm_handle_t handle
  输入参数。 bm_handle 句柄。

* bm_image image
  输入/输出参数。需处理图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

* const char* text
  输入参数。待写入的文本内容，当文本内容中有中文时，参数thickness请设置为0。

* bmcv_point_t org
  输入参数。第一个字符左下角的坐标位置。图像左上角为原点，向右延伸为x方向，向下延伸为y方向。

* bmcv_color_t color
  输入参数。画线的颜色，分别为RGB三个通道的值。

* float fontScale
  输入参数。字体大小。

* int thickness
  输入参数。画线的宽度，对于YUV格式的图像建议设置为偶数。开启中文字库请将该参数设置为0。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项：**

1. 该接口目前支持以下 image_format:

| num | image_format |
|-----|--------------|
| 1   | FORMAT_GRAY  |
| 2   | FORMAT_YUV420P |
| 3   | FORMAT_YUV422P |
| 4   | FORMAT_YUV444P |
| 5   | FORMAT_NV12  |
| 6   | FORMAT_NV21  |
| 7   | FORMAT_NV16  |
| 8   | FORMAT_NV61  |

thickness参数配置为0，即开启中文字库后，image_format 扩展支持 bmcv_image_watermark_superpose API 底图支持的格式。

2. 目前支持以下 data_type:

| num | data_type |
|-----|-----------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

3. 若文字内容不变，推荐使用 bmcv_gen_text_watermark 与 bmcv_image_watermark_superpose 搭配的文字绘制方式，文字生成水印图，重复使用水印图进行osd叠加，以提高处理效率。示例参见bmcv_image_watermark_superpose接口文档。

**代码示例：**

```c
#include "bmcv_api_ext.h"
#include <stdio.h>
#include <stdlib.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
int channel = 1;
int width = 1920;
int height = 1080;
int dev_id = 0;
int thickness = 4;
float fontScale = 4;
char text[20] = "hello world";
bmcv_point_t org = {100, 100};
bmcv_color_t color = {255, 0, 0};
bm_handle_t handle;
bm_image img;
const char* input_path = "path/to/input";
const char* output_path = "path/to/output";
unsigned char* data_ptr = new unsigned char[channel * width * height];

readBin(input_path, data_ptr, channel * width * height);
bm_dev_request(&handle, dev_id);
bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &img);
bm_image_alloc_dev_mem(img);
bm_image_copy_host_to_device(img, (void**)&data_ptr);
bmcv_image_put_text(handle, img, text, org, color, fontScale, thickness);
bm_image_copy_device_to_host(img, (void**)&data_ptr);
writeBin(output_path, data_ptr, channel * width * height);

bm_image_destroy(img);
bm_dev_free(handle);
free(data_ptr);
return 0;
}
```

# bmcv_image_pyramid_down

该接口实现图像高斯金字塔操作中的向下采样。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_pyramid_down(
            bm_handle_t handle,
            bm_image input,
            bm_image output);
```

## 参数说明

* bm_handle_t handle

  输入参数。bm_handle句柄。

* bm_image input

  输入参数。输入图像bm_image，bm_image需要外部调用bmcv_image_create创建。bm_image的内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output

  输出参数。输出图像bm_image，bm_image需要外部调用bmcv_image_create创建。bm_image的内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

该接口目前支持以下image_format与data_type:

| num | image_format | data_type |
|-----|--------------|-----------|
| 1 | FORMAT_GRAY | DATA_TYPE_EXT_1N_BYTE |

## 代码示例

```c
#include <assert.h>
#include "bmcv_api_ext.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    fclose(fp_dst);
}

int main()
{
    int height = 1080;
    int width = 1920;
    int ow = width / 2;
    int oh = height / 2;
    int channel = 1;
    unsigned char* input = new unsigned char [width * height * channel];
    unsigned char* output = new unsigned char [ow * oh * channel];
    bm_handle_t handle;
    bm_image_format_ext fmt = FORMAT_GRAY;
    bm_image img_i;
    bm_image img_o;
    const char* src_name = "path/to/src";
    const char* dst_name = "path/to/dst";

    readBin(src_name, input, width * height * channel);
    bm_dev_request(&handle, 0);
    bm_image_create(handle, height, width, fmt, DATA_TYPE_EXT_1N_BYTE, &img_i);
    bm_image_create(handle, oh, ow, fmt, DATA_TYPE_EXT_1N_BYTE, &img_o);
    bm_image_alloc_dev_mem(img_i);
    bm_image_alloc_dev_mem(img_o);
    bm_image_copy_host_to_device(img_i, (void**)(&input));
    bmcv_image_pyramid_down(handle, img_i, img_o);
    bm_image_copy_device_to_host(img_o, (void **)(&output));
    writeBin(dst_name, output, ow * oh * channel);

    bm_image_destroy(img_i);
    bm_image_destroy(img_o);
    bm_dev_free(handle);
    free(input);
    free(output);
    return 0;
}
```

# bmcv_image_quantify

将float类型数据转化成int类型(舍入模式为小数点后直接截断)，并将小于0的数变为0，大于255的数变为255。

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_quantify(
            bm_handle_t handle,
            bm_image input,
            bm_image output);
```

## 参数说明

* bm_handle_t handle

  输入参数。bm_handle句柄。

* bm_image input

  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output

  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

该接口目前支持以下image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1 | FORMAT_RGB_PLANAR | FORMAT_RGB_PLANAR |
| 2 | FORMAT_BGR_PLANAR | FORMAT_BGR_PLANAR |

输入数据目前支持以下data_type:

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_FLOAT32 |

输出数据目前支持以下data_type:

| num | data_type |
|-----|-----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用该接口之前必须确保输入的image内存已经申请。
2. 如调用该接口的程序为多线程程序，需要在创建bm_image前和销毁bm_image后加线程锁。
3. 该接口支持图像宽高范围为1x1～8192x8192。

## 代码示例

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <float.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 4, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int width = 1920;
    int height = 1080;
    bm_handle_t handle;
    bm_image input_img;
    bm_image output_img;
    float* input = (float*)malloc(width * height * 3 * sizeof(float));
    unsigned char* output = (unsigned char*)malloc(width * height * 3 * sizeof(unsigned char));
    const char *input_path = "path/to/input";
    const char *output_path = "path/to/output";

    readBin(input_path, (unsigned char*)input, width * height * 3);

    bm_dev_request(&handle, 0);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_FLOAT32, &input_img, NULL);
    bm_image_create(handle, height, width, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output_img, NULL);
    bm_image_alloc_dev_mem(input_img, 2);
    bm_image_alloc_dev_mem(output_img, 2);
    bm_image_copy_host_to_device(input_img, (void **)&input);
    bmcv_image_quantify(handle, input_img, output_img);
    bm_image_copy_device_to_host(output_img, (void **)&output);
    writeBin(output_path, output, (width * height * 3));

    bm_image_destroy(input_img);
    bm_image_destroy(output_img);
    free(input);
    free(output);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_remap

使用指定的x轴与y轴映射表数据，对源图像进行重映射操作，边缘填充方式为填充常数0。

**处理器型号支持：**

该接口仅支持BM1684X。

**接口形式：**

```c
bm_status_t bmcv_image_remap(
    bm_handle_t handle,
    bm_image input,
    bm_image output,
    bm_device_mem_t mapx_data_global_addr,
    bm_device_mem_t mapy_data_global_addr,
    int interpolation_mode);
```

**参数说明：**

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_image input
  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output
  输出参数。输出图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

* bm_device_mem_t mapx_data_global_addr
  输入参数。x轴方向映射表数据的设备内存地址。

* bm_device_mem_t mapy_data_global_addr
  输入参数。y轴方向映射表数据的设备内存地址。

* int interpolation_mode
  输入参数。插值方式，0将启用Nearest近邻插值算法，1将启用Bilinear双线性插值算法。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他: 失败

**格式支持：**

该接口目前支持以下image_format:

| num | image_format           |
|-----|------------------------|
| 1   | FORMAT_YUV444P         |
| 2   | FORMAT_RGB_PLANAR      |
| 3   | FORMAT_BGR_PLANAR      |
| 4   | FORMAT_RGBP_SEPARATE   |
| 5   | FORMAT_BGRP_SEPARATE   |
| 6   | FORMAT_GRAY            |

目前支持以下data_type:

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

**注意事项：**

1. 在调用bmcv_image_remap()之前必须确保输入的image内存已经申请。
2. 输入输出图像的data_type，image_format必须相同。
3. 输入图像的宽高尺寸支持范围为8*8-8192*8192，当插值方式为Nearest时，输出图像尺寸支持范围为8*8-8192*8192，当插值方式为Bilinear时，输出图像尺寸支持范围为8*8-4096*4096。

**代码示例：**

```c
#include <stdio.h>
#include "bmcv_api_ext_c.h"
#include "stdlib.h"

static void read_bin_float(const char *input_path, float *input_data, int width, int height, int channel) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
        printf("无法打开输出文件 %s\n", input_path);
        return;
    }
    if(fread(input_data, sizeof(float), width * height * channel, fp_src) != 0) {
        printf("read map success\n");
    }
    fclose(fp_src);
}

static void read_bin(const char *input_path, unsigned char *input_data, int input_width, int input_height, int channel) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
        printf("无法打开输入文件 %s\n", input_path);
        return;
    }
    if(fread(input_data, sizeof(char), input_width * input_height * channel, fp_src) != 0) {
        printf("read image success\n");
    }
    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int width, int height, int channel) {
    FILE *fp_dst = fopen(output_path, "wb");
    if (fp_dst == NULL) {
        printf("无法打开输出文件 %s\n", output_path);
        return;
    }
    fwrite(output_data, sizeof(unsigned char), width * height * channel, fp_dst);
    fclose(fp_dst);
    printf("write image success\n");
}

int main() {
    int input_width = 1920;
    int input_height = 1080;
    int output_width = 1920;
    int output_height = 1080;
    int format = 8;
    int interpolation_mode = 1; //0-nearest 1-bilinear
    const char *mapx_path = "mapx.bin";
    const char *mapy_path = "mapy.bin";
    const char *input_path = "rgbplanar_1920_1080.bin";
    const char *output_path = "remap_output.bin";
    int ret = 0;
    bm_handle_t handle;
    ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("bm_dev_request failed. ret = %d\n", ret);
        return -1;
    }
    unsigned char *input_data, *output_tpu;
    float *mapx_data = (float*)malloc(output_width * output_height * 3 * sizeof(float));
    float *mapy_data = (float*)malloc(output_width * output_height * 3 * sizeof(float));
    input_data = (unsigned char*)malloc(input_width * input_height * 3);
    output_tpu = (unsigned char*)malloc(output_width * output_height * 3);
    read_bin(input_path, input_data, input_width, input_height, 3);
    read_bin_float(mapx_path, mapx_data, output_width, output_height, 3);
    read_bin_float(mapy_path, mapy_data, output_width, output_height, 3);
    bm_status_t bm_ret = BM_SUCCESS;
    bm_image input_image, output_image;
    bm_device_mem_t mapx_data_global_addr, mapy_data_global_addr;
    bm_ret = bm_image_create(handle, input_height, input_width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &input_image, NULL);
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_create input_image error\n");
        return bm_ret;
    }
    bm_ret = bm_image_create(handle, output_height, output_width, (bm_image_format_ext)format, DATA_TYPE_EXT_1N_BYTE, &output_image, NULL);
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_create output_image error\n");
        return bm_ret;
    }
    bm_ret = bm_image_alloc_dev_mem(input_image, BMCV_HEAP_ANY);
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_alloc_dev_mem input_image error\n");
        return bm_ret;
    }
    bm_ret = bm_image_alloc_dev_mem(output_image, BMCV_HEAP_ANY);
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_alloc_dev_mem output_image error\n");
        return bm_ret;
    }
    unsigned char *input_addr[3] = {input_data, input_data + input_height * input_width, input_data + 2 * input_height * input_width};
    bm_ret = bm_image_copy_host_to_device(input_image, (void **)(input_addr));
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_copy_host_to_device input_image error\n");
        return bm_ret;
    }
    bm_ret = bm_malloc_device_byte(handle, &mapx_data_global_addr, output_width * output_height * sizeof(float));
    if (BM_SUCCESS != bm_ret) {
        printf("bm_malloc_device_byte mapx_data_global_addr error\n");
        return bm_ret;
    }
    bm_ret = bm_malloc_device_byte(handle, &mapy_data_global_addr, output_width * output_height * sizeof(float));
    if (BM_SUCCESS != bm_ret) {
        printf("bm_malloc_device_byte mapy_data_global_addr error\n");
        return bm_ret;
    }
    bm_ret = bm_memcpy_s2d(handle, mapx_data_global_addr, bm_mem_get_system_addr(bm_mem_from_system(mapx_data)));
    if (bm_ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d mapx_data error\n");
        return bm_ret;
    }
    bm_ret = bm_memcpy_s2d(handle, mapy_data_global_addr, bm_mem_get_system_addr(bm_mem_from_system(mapy_data)));
    if (bm_ret != BM_SUCCESS) {
        printf("bm_memcpy_s2d mapy_data error\n");
        return bm_ret;
    }
    bm_ret = bmcv_image_remap(handle, input_image, output_image, mapx_data_global_addr, mapy_data_global_addr, interpolation_mode);
    if(bm_ret != BM_SUCCESS){
        printf("bmcv_image_remap error\n");
        return bm_ret;
    }
    unsigned char *output_addr[3] = {output_tpu, output_tpu + output_height * output_width, output_tpu + 2 * output_height * output_width};
    bm_ret = bm_image_copy_device_to_host(output_image, (void **)output_addr);
    if (bm_ret != BM_SUCCESS) {
        printf("bm_image_copy_device_to_host output_image error\n");
    }
    write_bin(output_path, output_tpu, output_width, output_height, 3);
    free(input_data);
    free(output_tpu);
    free(mapx_data);
    free(mapy_data);
    bm_image_destroy(input_image);
    bm_image_destroy(output_image);
    bm_free_device(handle, mapx_data_global_addr);
    bm_free_device(handle, mapy_data_global_addr);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_image_resize

该接口用于实现图像尺寸的变化,如放大、缩小、抠图等功能。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_resize(
        bm_handle_t handle,
        int input_num,
        bmcv_resize_image resize_attr[4],
        bm_image* input,
        bm_image* output);
```

**参数说明:**

* bm_handle_t handle
  输入参数。bm_handle句柄。

* int input_num
  输入参数。输入图片数，最多支持4，如果input_num > 1, 那么多个输入图像必须是连续存储的（可以使用bm_image_alloc_contiguous_mem给多张图申请连续空间）。

* bmcv_resize_image resize_attr [4]
  输入参数。每张图片对应的resize参数,最多支持4张图片。

* bm_image\* input
  输入参数。输入bm_image。每个bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image\* output
  输出参数。输出bm_image。每个bm_image需要外部调用bmcv_image_create创建，image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存，如果不主动分配将在api内部进行自行分配。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**数据类型说明:**

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

* bmcv_resize_image描述了一张图中resize配置信息。
* roi_num描述了一副图中需要进行resize的子图总个数。
* stretch_fit表示是否按照原图比例对图片进行缩放，1表示无需按照原图比例进行缩放，0表示按照原图比例进行缩放，当采用这种方式的时候，结果图片中进行缩放的地方将会被填充成特定值。
* padding_b表示当stretch_fit设成0的情况下，b通道上被填充的值。
* padding_r表示当stretch_fit设成0的情况下，r通道上被填充的值。
* padding_g表示当stretch_fit设成0的情况下，g通道上被填充的值。
* interpolation表示缩图所使用的算法。BMCV_INTER_NEAREST表示最近邻算法，BMCV_INTER_LINEAR表示线性插值算法, BMCV_INTER_BICUBIC表示双三次插值算法。bm1684支持BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。

bm1684x支持BMCV_INTER_NEAREST，BMCV_INTER_LINEAR。

* start_x 描述了resize起始横坐标(相对于原图)，常用于抠图功能。
* start_y 描述了resize起始纵坐标(相对于原图)，常用于抠图功能。
* in_width 描述了crop图像的宽。
* in_height 描述了crop图像的高。
* out_width 描述了输出图像的宽。
* out_height 描述了输出图像的高。

## 代码示例

```c
#include <memory>
#include <assert.h>
#include <iostream>
#include <set>
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <vector>
#include <cmath>
#include <cstring>
#include "bmcv_api.h"
#include "bmcv_api_ext.h"
#include "test_misc.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int image_num = 4;
    int crop_w = 711, crop_h = 400, resize_w = 711, resize_h = 400;
    int image_w = 1920, image_h = 1080;
    int img_size_i = image_w * image_h * 3;
    int img_size_o = resize_w * resize_h * 3;
    unsigned char* img_data = new unsigned char[img_size_i * image_num];
    unsigned char* res_data = new unsigned char[img_size_o * image_num];
    bmcv_resize_image resize_attr[image_num];
    bmcv_resize_t resize_img_attr[image_num];
    bm_image input[image_num];
    bm_image output[image_num];
    bm_handle_t handle;
    const char *src_names[4] = {"path/to/src0", "path/to/src1", "path/to/src2", "path/to/src3"};
    const char *dst_names[4] = {"path/to/dst0", "path/to/dst1", "path/to/dst2", "path/to/dst3"};

    bm_dev_request(&handle, 0);

    for(int i = 0; i < image_num; ++i) {
        readBin(src_names[i], img_data + i * img_size_i, img_size_i);
    }

    memset(res_data, 0, img_size_o * image_num);

    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        resize_img_attr[img_idx].start_x = 0;
        resize_img_attr[img_idx].start_y = 0;
        resize_img_attr[img_idx].in_width = crop_w;
        resize_img_attr[img_idx].in_height = crop_h;
        resize_img_attr[img_idx].out_width = resize_w;
        resize_img_attr[img_idx].out_height = resize_h;
    }

    for (int img_idx = 0; img_idx < image_num; img_idx++) {
    resize_attr[img_idx].resize_img_attr = &resize_img_attr[img_idx];
    resize_attr[img_idx].roi_num = 1;
    resize_attr[img_idx].stretch_fit = 1;
    resize_attr[img_idx].interpolation = BMCV_INTER_NEAREST;
    }

    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &input[img_idx]);
    }
    bm_image_alloc_contiguous_mem(image_num, input, 1);
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        unsigned char * input_img_data = img_data + img_size_i * img_idx;
        bm_image_copy_host_to_device(input[img_idx], (void **)&input_img_data);
    }
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        bm_image_create(handle, resize_h, resize_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &output[img_idx]);
    }
    bm_image_alloc_contiguous_mem(image_num, output, 1);
    bmcv_image_resize(handle, image_num, resize_attr, input, output);
    for (int img_idx = 0; img_idx < image_num; img_idx++) {
        unsigned char *res_img_data = res_data + img_size_o * img_idx;
        bm_image_copy_device_to_host(output[img_idx], (void **)&res_img_data);
        for(int i = 0; i < image_num; ++i) {
            writeBin(dst_names[i], res_img_data, img_size_o);
        }
    }

    bm_image_free_contiguous_mem(image_num, input);
    bm_image_free_contiguous_mem(image_num, output);
    for(int i = 0; i < image_num; i++) {
        bm_image_destroy(input[i]);
        bm_image_destroy(output[i]);
    }
    delete[] img_data;
    delete[] res_data;
    bm_dev_free(handle);
    return 0;
}
```

## 格式支持

### resize支持下列image_format的转化：

| 序号 | 格式转换 |
|------|----------|
| 1 | FORMAT_BGR_PLANAR → FORMAT_BGR_PLANAR |
| 2 | FORMAT_RGB_PLANAR → FORMAT_RGB_PLANAR |
| 3 | FORMAT_BGR_PACKED → FORMAT_BGR_PACKED |
| 4 | FORMAT_RGB_PACKED → FORMAT_RGB_PACKED |
| 5 | FORMAT_BGR_PACKED → FORMAT_BGR_PLANAR |
| 6 | FORMAT_RGB_PACKED → FORMAT_RGB_PLANAR |

### resize支持下列情形data type之间的转换：

bm1684支持：

- 1 vs 1：1幅图像resize(crop)一幅图像的情形
- 1 vs N：1幅图像resize(crop)多幅图像的情形

| 序号 | 数据类型转换 | 模式 |
|------|--------------|------|
| 1 | DATA_TYPE_EXT_1N_BYTE → DATA_TYPE_EXT_1N_BYTE | 1 vs 1 |
| 2 | DATA_TYPE_EXT_FLOAT32 → DATA_TYPE_EXT_FLOAT32 | 1 vs 1 |
| 3 | DATA_TYPE_EXT_4N_BYTE → DATA_TYPE_EXT_4N_BYTE | 1 vs 1 |
| 4 | DATA_TYPE_EXT_4N_BYTE → DATA_TYPE_EXT_1N_BYTE | 1 vs 1 |
| 5 | DATA_TYPE_EXT_1N_BYTE → DATA_TYPE_EXT_1N_BYTE | 1 vs N |
| 6 | DATA_TYPE_EXT_FLOAT32 → DATA_TYPE_EXT_FLOAT32 | 1 vs N |
| 7 | DATA_TYPE_EXT_4N_BYTE → DATA_TYPE_EXT_1N_BYTE | 1 vs N |

bm1684x支持：

| 序号 | 输入数据类型 | 输出数据类型 |
|------|--------------|--------------|
| 1 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_FLOAT32 |
| 2 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE |
| 3 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_FP16 |
| 5 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_BF16 |

## 注意事项

1. 在调用bmcv_image_resize()之前必须确保输入的image内存已经申请。
2. bm1684支持最大尺寸为2048*2048，最小尺寸为16*16，最大缩放比为32。
3. bm1684x支持最大尺寸为8192*8192，最小尺寸为8*8，最大缩放比为128。

# bmcv_image_rotate

实现图像顺时针旋转90度，180度，270度

## 处理器型号支持

该接口仅支持BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_rotate(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            int rotation_angle);
```

## 参数说明

* bm_handle_t handle

  输入参数。bm_handle句柄。

* bm_image input

  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output

  输出参数。输出图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

* rotation_angle

  顺时针旋转角度。可选角度90度，180度，270度。

## 返回值说明

## bmcv_image_sobel

边缘检测Sobel算子。

### 处理器型号支持

该接口支持BM1684/BM1684X。

### 接口形式

```c
bm_status_t bmcv_image_sobel(
            bm_handle_t handle,
            bm_image input,
            bm_image output,
            int dx,
            int dy,
            int ksize = 3,
            float scale = 1,
            float delta = 0);
```

### 参数说明

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_image input
  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output
  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

* int dx
  x方向上的差分阶数。

* int dy
  y方向上的差分阶数。

* int ksize = 3
  Sobel核的大小，必须是1，3，5或7。3，5，7取值情况下，核大小为3*3，5*5，7*7。如果取1，则按照dx和dy的值决定Sobel核的大小，dx=1，dy=0则核大小为3×1，dx=0，dy=1，则核大小为1×3，dx=1,dy=1,核大小变为3*3。ksize默认值为3。

* float scale = 1
  对求出的差分结果乘以该系数，默认值为1。

* float delta = 0
  在输出最终结果之前加上该偏移量，默认值为0。

### 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

### 格式支持

该接口目前支持以下image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1 | FORMAT_BGR_PLANAR | FORMAT_BGR_PLANAR |
| 2 | FORMAT_RGB_PLANAR | FORMAT_RGB_PLANAR |
| 3 | FORMAT_RGBP_SEPARATE | FORMAT_RGBP_SEPARATE |
| 4 | FORMAT_BGRP_SEPARATE | FORMAT_BGRP_SEPARATE |
| 5 | FORMAT_GRAY | FORMAT_GRAY |
| 6 | FORMAT_YUV420P | FORMAT_GRAY |
| 7 | FORMAT_YUV422P | FORMAT_GRAY |
| 8 | FORMAT_YUV444P | FORMAT_GRAY |
| 9 | FORMAT_NV12 | FORMAT_GRAY |
| 10 | FORMAT_NV21 | FORMAT_GRAY |
| 11 | FORMAT_NV16 | FORMAT_GRAY |
| 12 | FORMAT_NV61 | FORMAT_GRAY |
| 13 | FORMAT_NV24 | FORMAT_GRAY |

目前支持以下data_type:

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

### 注意事项

1、在调用该接口之前必须确保输入的image内存已经申请。

2、input output的data_type必须相同。

3、BM1684芯片下该算子支持图像的最大width为(2048 - ksize)。BM1684X芯片下该算子在Sobel核大小为1和3时，支持的宽高范围为8*8～8192*8192，核大小为5时支持的宽高范围为8*8～4096*8192，核大小为7时支持的宽高范围为8*8～2048*8192。

### 代码示例

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "bmcv_api_ext.h"
#include "test_misc.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input, output;
    unsigned char* src_data = new unsigned char[channel * width * height];
    unsigned char* res_data = new unsigned char[channel * width * height];
    const char *src_name = "/path/to/src";
    const char *dst_name = "path/to/dst";

    bm_dev_request(&handle, dev_id);
    readBin(src_name, src_data, channel * width * height);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void**)&src_data);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_sobel(handle, input, output, 0, 1);
    bm_image_copy_device_to_host(output, (void**)&res_data);
    writeBin(dst_name, res_data, channel * width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    return 0;
}
```

# bmcv_sort

该接口可以实现浮点数据的排序（升序/降序），并且支持排序后可以得到原数据所对应的 index。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_sort(
            bm_handle_t handle,
            bm_device_mem_t src_index_addr,
            bm_device_mem_t src_data_addr,
            int data_cnt,
            bm_device_mem_t dst_index_addr,
            bm_device_mem_t dst_data_addr,
            int sort_cnt,
            int order,
            bool index_enable,
            bool auto_index);
```

## 输入参数说明

* bm_handle_t handle
  输入参数。输入的 bm_handle 句柄。

* bm_device_mem_t src_index_addr
  输入参数。每个输入数据所对应 index 的地址。如果使能 index_enable 并且不使用 auto_index 时，则该参数有效。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t src_data_addr
  输入参数。待排序的输入数据所对应的地址。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* int data_cnt
  输入参数。待排序的输入数据的数量。

* bm_device_mem_t dst_index_addr
  输出参数。排序后输出数据所对应 index 的地址， 如果使能 index_enable 并且不使用 auto_index 时，则该参数有效。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* bm_device_mem_t dst_data_addr
  输出参数。排序后的输出数据所对应的地址。bm_device_mem_t 为内置表示地址的数据类型，可以使用函数 bm_mem_from_system(addr) 将普通用户使用的指针或地址转为该类型，用户可参考示例代码中的使用方式。

* int sort_cnt
  输入参数。需要排序的数量，也就是输出结果的个数，包括排好序的数据和对应 index 。比如降序排列，如果只需要输出前 3 大的数据，则该参数设置为 3 即可。

* int order
  输入参数。升序还是降序，0 表示升序， 1 表示降序。

* bool index_enable
  输入参数。是否使能 index。如果使能即可输出排序后数据所对应的 index ，否则 src_index_addr 和 dst_index_addr 这两个参数无效。

* bool auto_index
  输入参数。是否使能自动生成 index 功能。使用该功能的前提是 index_enable 参数为 true，如果该参数也为 true 则表示按照输入数据的存储顺序从 0 开始计数作为 index，参数 src_index_addr 便无效，输出结果中排好序数据所对应的 index 即存放于 dst_index_addr 地址中。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 要求 sort_cnt <= data_cnt。
2. 若需要使用 auto index 功能，前提是参数 index_enable 为 true。
3. 该 api 至多可支持 1MB 数据的全排序。

## 示例代码

```c
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include "bmcv_api_ext.h"

int main()
{
    int data_cnt = 100;
    int sort_cnt = 50;
    float src_data_p[100];
    int src_index_p[100];
    float dst_data_p[50];
    int dst_index_p[50];
    int order = 0;
    bm_handle_t handle;

    bm_dev_request(&handle, 0);
    for (int i = 0; i < 100; i++) {
        src_data_p[i] = rand() % 1000;
        src_index_p[i] = 100 - i;
    }
    bmcv_sort(handle, bm_mem_from_system(src_index_p), bm_mem_from_system(src_data_p), data_cnt,
            bm_mem_from_system(dst_index_p), bm_mem_from_system(dst_data_p), sort_cnt, order,
            true, false);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_stft

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_stft(
            bm_handle_t handle,
            float* XRHost,
            float* XIHost,
            float* YRHost,
            float* YIHost,
            int batch,
            int L,
            bool realInput,
            int pad_mode,
            int n_fft,
            int win_mode,
            int hop_len,
            bool normalize);
```

## 参数说明

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* float* XRHost
  输入参数。输入信号的实部地址，空间大小为 batch * L。

* float* XIHost
  输入参数。输入信号的虚部地址，空间大小为 batch * L。

* float* YRHost
  输入参数。输出信号的实部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* float* YIHost
  输入参数。输出信号的虚部地址，空间大小为 (n_fft / 2 + 1) * (1 + L / hop_len)。

* int batch
  输入参数。batch数量。

* int L
  输入参数。每个batch的信号长度。

* bool realInput
  输入参数。输入是否为实数， false 为复数， true 为实数。

* int pad_mode
  输入参数。信号填充模式, 0 为 constant, 1 为 reflect。

* int n_fft
  输入参数。每个 L 信号长度做 FFT 的长度

* int win_mode
  输入参数。信号加窗模式, 0 为 hanning窗, 1 为 hamming窗。

* int hop_len
  输入参数。信号做 FFT 的滑动距离，一般为 n_fft / 4 或者 n_fft / 2。

* bool normalize
  输入参数。输出结果是否要进行归一化。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 本接口只处理一维信号的STFT变换。

## 示例代码

```c
#include "bmcv_api_ext.h"
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

int main()
{
    bm_handle_t handle;
    int i;
    int L = 4096;
    int batch = 1;
    bool realInput = true;
    int pad_mode = REFLECT;
    int win_mode = HANN;
    int n_fft = 4096;
    int hop_length = 1024;
    bool norm = true;
    float* XRHost = (float*)malloc(L * batch * sizeof(float));
    float* XIHost = (float*)malloc(L * batch * sizeof(float));
    int num_frames = 1 + L / hop_length;
    int row_num = n_fft / 2 + 1;
    float* YRHost_tpu = (float*)malloc(batch * row_num * num_frames * sizeof(float));
    float* YIHost_tpu = (float*)malloc(batch * row_num * num_frames * sizeof(float));

    bm_dev_request(&handle, 0);
    memset(XRHost, 0, L * batch * sizeof(float));
    memset(XIHost, 0, L * batch * sizeof(float));

    for (i = 0; i < L * batch; i++) {
        XRHost[i] = (float)rand() / RAND_MAX;;
        XIHost[i] = realInput ? 0 : ((float)rand() / RAND_MAX);
    }

    bmcv_stft(handle, XRHost, XIHost, YRHost_tpu, YIHost_tpu, batch, L,
            realInput, pad_mode, n_fft, win_mode, hop_length, norm);

    free(XRHost);
    free(XIHost);
    free(YRHost_tpu);
    free(YIHost_tpu);
    bm_dev_free(handle);
    return 0;
}
```

# bmcv_image_storage_convert

该接口将源图像格式的对应的数据转换为目的图像的格式数据，并填充在目的图像关联的 device memory 中。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_storage_convert(
            bm_handle_t handle,
            int image_num,
            bm_image* input_image,
            bm_image* output_image);
```

## 传入参数说明

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* int image_num
  输入参数。输入/输出 image 数量。

* bm_image* input
  输入参数。输入 bm_image 对象指针。

* bm_image* output
  输出参数。输出 bm_image 对象指针。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. bm1684 下该 API 支持以下格式的两两相互转换：

| num | image_format           | data type                     |
|-----|------------------------|-------------------------------|
| 1   | FORMAT_RGB_PLANAR      | DATA_TYPE_EXT_FLOAT32         |
| 2   | FORMAT_RGB_PLANAR      | DATA_TYPE_EXT_1N_BYTE         |
| 3   | FORMAT_RGB_PLANAR      | DATA_TYPE_EXT_4N_BYTE         |
| 4   | FORMAT_BGR_PLANAR      | DATA_TYPE_EXT_FLOAT32         |
| 5   | FORMAT_BGR_PLANAR      | DATA_TYPE_EXT_1N_BYTE         |
| 6   | FORMAT_BGR_PLANAR      | DATA_TYPE_EXT_4N_BYTE         |
| 7   | FORMAT_RGB_PACKED      | DATA_TYPE_EXT_FLOAT32         |
| 8   | FORMAT_RGB_PACKED      | DATA_TYPE_EXT_1N_BYTE         |
| 9   | FORMAT_RGB_PACKED      | DATA_TYPE_EXT_4N_BYTE         |
| 10  | FORMAT_BGR_PACKED      | DATA_TYPE_EXT_FLOAT32         |
| 11  | FORMAT_BGR_PACKED      | DATA_TYPE_EXT_1N_BYTE         |
| 12  | FORMAT_BGR_PACKED      | DATA_TYPE_EXT_4N_BYTE         |
| 13  | FORMAT_RGBP_SEPARATE   | DATA_TYPE_EXT_FLOAT32         |
| 14  | FORMAT_RGBP_SEPARATE   | DATA_TYPE_EXT_1N_BYTE         |
| 15  | FORMAT_RGBP_SEPARATE   | DATA_TYPE_EXT_4N_BYTE         |
| 16  | FORMAT_BGRP_SEPARATE   | DATA_TYPE_EXT_FLOAT32         |
| 17  | FORMAT_BGRP_SEPARATE   | DATA_TYPE_EXT_1N_BYTE         |
| 18  | FORMAT_BGRP_SEPARATE   | DATA_TYPE_EXT_4N_BYTE         |
| 19  | FORMAT_NV12            | DATA_TYPE_EXT_1N_BYTE         |
| 20  | FORMAT_NV21            | DATA_TYPE_EXT_1N_BYTE         |
| 21  | FORMAT_NV16            | DATA_TYPE_EXT_1N_BYTE         |
| 22  | FORMAT_NV61            | DATA_TYPE_EXT_1N_BYTE         |
| 23  | FORMAT_YUV420P         | DATA_TYPE_EXT_1N_BYTE         |
| 24  | FORMAT_YUV444P         | DATA_TYPE_EXT_1N_BYTE         |

# bmcv_surf

## 接口形式

```c
bm_status_t bmcv_image_surf_response(
        bm_handle_t handle,
        float* img_data,
        FastHessian *hessian,
        int width,
        int height,
        int layer_num);
```

## 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **float* img_data**  
  输入参数。输入图像的加权灰度图数据。

- **FastHessian* hessian**  
  输入参数。描述图片特征的FastHessian结构体。

- **int width**  
  输入参数。输出图像的宽。

- **int height**  
  输入参数。输入图像的高。

- **int layer_num**  
  输入参数。金字塔层数。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 格式支持

该接口目前支持以下 image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1   | FORMAT_BGR_PLANAR | FORMAT_BGR_PLANAR |
| 2   | FORMAT_BGR_PACKED | FORMAT_BGR_PACKED |

目前支持以下 data_type:

| num | data_type |
|-----|-----------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1. 在调用该接口之前必须先初始化 SURFDescriptor 结构体。
2. 该接口目前支持 layer_num = 4。
3. BM1684x芯片下该算子支持图像的最大width为1059。支持的高范围为8*8～8192*8192。

## 示例代码

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>

typedef struct
{
    Ipoint *pt1, *pt2;
    int size;
    int count;
} IpointPair;

typedef struct {
    double **integralImage; // 积分图像
    int width;
    int height;
} Image;

static void readbin(const char *input_path, unsigned char *input_data, int width, int height, int channel) {
    FILE *fp_src = fopen(input_path, "rb");
    if (fp_src == NULL) {
        printf("Can not open input_file %s\n", input_path);
        return;
    }
    if (fread(input_data, sizeof(unsigned char), width * height * channel, fp_src) != (size_t)(width * height * channel)) {
        printf("Failed to read img!\n");
    }
    fclose(fp_src);
}

static void writebin(const char *output_path, unsigned char *data, int byte_size) {
    FILE *fp_dst = fopen(output_path, "wb");
    if (!fp_dst) {
        perror("failed to open destination file\n");
    }
    if (fwrite((void*)data, 1, byte_size, fp_dst) < (unsigned int)byte_size) {
        printf("Failed to write all required bytes\n");
    }
    fclose(fp_dst);
}

unsigned char** channel_split(unsigned char* buffer, int width, int height) {
    unsigned char** chan_buffers = NULL;
    int i, num_frames = width * height;
    int samples;
    chan_buffers = (unsigned char**)malloc(3 * sizeof(unsigned char*));
    for (i = 0; i < 3; i++) {
        chan_buffers[i] = (unsigned char*)malloc(num_frames * sizeof(unsigned char));
    }
    samples = 3 * num_frames;
    for (i = 0; i < samples; i++) {
        chan_buffers[(i % 3)][i / 3] = buffer[i];
    }

    return chan_buffers;
}

float* LoadToMatrixGreyWeighted(unsigned char *input_data, int width, int height, int format) {
    int i, num_frams = width * height;
    float tofloat = 1.0f / 255.0f;
    float *data = (float*)malloc(width*height*sizeof(float));
    switch (format)
    {
    case FORMAT_RGB_PACKED: {
        unsigned char **buffer = channel_split(input_data, width, height);
        for (i = 0; i < num_frams; i++) {
            data[i] = ((float)buffer[0][i] * 0.2989f + (float)buffer[1][i] * 0.587f + (float)buffer[2][i] * 0.114f) * tofloat;
        }
        for (i = 0; i < 3; i++) {
            free(buffer[i]);
        }
        free(buffer);
        break;
    }
    default:
        for (i = 0; i < num_frams; i++) {
            data[i] = ((float)input_data[i] * 0.2989f + (float)input_data[num_frams + i] * 0.587f + (float)input_data[num_frams * 2 + i] * 0.114f) * tofloat;
        }
        break;
    }

    return data;
}

void ResLayer(ResponseLayer *Res, int width, int height, int step, int filter)
{
    Res->width = width;
    Res->height = height;
    Res->step = step;
    Res->filter = filter;
    Res->responses = (float*)malloc(width * height * sizeof(float));
    Res->laplacian = (unsigned char*)malloc(width * height * sizeof(unsigned char));
}

void allocateResponseMap(FastHessian *fh)
{
    int w = (fh->i_width / fh->init_sample);
    int h = (fh->i_height / fh->init_sample);
    int s = fh->init_sample;
    if (fh->octaves >= 1)
    {
        ResLayer(&fh->responseMap[0], w, h, s, 9);
        ResLayer(&fh->responseMap[1], w, h, s, 15);
        ResLayer(&fh->responseMap[2], w, h, s, 21);
        ResLayer(&fh->responseMap[3], w, h, s, 27);

    }
    if (fh->octaves >= 2)
    {
        ResLayer(&fh->responseMap[4], w >> 1, h >> 1, s << 1, 39);
        ResLayer(&fh->responseMap[5], w >> 1, h >> 1, s << 1, 51);
    }
    if (fh->octaves >= 3)
    {
        ResLayer(&fh->responseMap[6],
```

```c
w >> 2, h >> 2, s << 2, 75);
ResLayer(&fh->responseMap[7], w >> 2, h >> 2, s << 2, 99);
}
if (fh->octaves >= 4)
{
    ResLayer(&fh->responseMap[8], w >> 3, h >> 3, s << 3, 147);
    ResLayer(&fh->responseMap[9], w >> 3, h >> 3, s << 3, 195);
}
if (fh->octaves >= 5)
{
    ResLayer(&fh->responseMap[10], w >> 4, h >> 4, s << 4, 291);
    ResLayer(&fh->responseMap[11], w >> 4, h >> 4, s << 4, 387);
}
}

void FastHessianInit(FastHessian *fhts, float *img, int width, int height, const int octaves, const int init_sample, const float thres)
{
    fhts->img = img;
    fhts->i_height = height;
    fhts->i_width = width;
    fhts->octaves = octaves;
    fhts->init_sample = init_sample;
    fhts->thresh = thres;
    fhts->iptssize = 0;
    allocateResponseMap(fhts);
}

static void SURFInitialize(SURFDescriptor *surf, int width, int height, int octaves, int init_sample, float thres) {
    surf->hessians = (FastHessian*)malloc(sizeof(FastHessian));
    surf->integralImg = (float*)malloc(width*height*sizeof(float));
    memset(surf->hessians->responseMap, 0, 12 * sizeof(ResponseLayer));
    FastHessianInit(surf->hessians, surf->integralImg, width, height, octaves, init_sample, thres);
    surf->hessians->ipts = 0;
}

void IpointPair_add(IpointPair *v, Ipoint *first, Ipoint *second)
{
    size_t memSize;
    if (!v->size)
    {
        v->size = 10;
        memSize = sizeof(Ipoint) * v->size;
        v->pt1 = (Ipoint*)malloc(memSize);
        v->pt2 = (Ipoint*)malloc(memSize);
        memset(v->pt1, 0, memSize);
        memset(v->pt2, 0, memSize);
    }
    if (v->size == v->count)
    {
        v->size <<= 1;
        memSize = sizeof(Ipoint) * v->size;
        v->pt1 = (Ipoint*)realloc(v->pt1, memSize);
        v->pt2 = (Ipoint*)realloc(v->pt2, memSize);
    }
    memcpy(&v->pt1[v->count], first, sizeof(Ipoint));
    memcpy(&v->pt2[v->count], second, sizeof(Ipoint));
    v->count++;
}

IpointPair getMatches(SURFDescriptor *surf1, SURFDescriptor *surf2, float threshold)
{
    IpointPair pair = {
        nullptr,
        nullptr,
        0,
        0
    };
    float dist, d1, d2;
    Ipoint *match = nullptr;
    int i, j, idx;
    for (i = 0; i < surf1->hessians->interestPtsLen; i++)
    {
        d1 = d2 = FLT_MAX;
        for (j = 0; j < surf2->hessians->interestPtsLen; j++)
        {
            dist = 0.0f;
            for (idx = 0; idx < 64; ++idx)
                dist += (surf1->hessians->ipts[i].descriptor[idx] - surf2->hessians->ipts[j].descriptor[idx])*(surf1->hessians->ipts[i].descriptor[idx] - surf2->hessians->ipts[j].descriptor[idx]);
            dist = sqrtf(dist);
            if (dist < d1)
            {
                d2 = d1;
                d1 = dist;
                match = &surf2->hessians->ipts[j];
            }
            else if (dist < d2)
                d2 = dist;
        }
        if (d1 / d2 < threshold)
        {
            surf1->hessians->ipts[i].dx = match->x - surf1->hessians->ipts[i].x;
            surf1->hessians->ipts[i].dy = match->y - surf1->hessians->ipts[i].y;
            IpointPair_add(&pair, &surf1->hessians->ipts[i], match);
        }
    }
    return pair;
}

#ifndef M_PI
#define M_PI 3.141592653589793f
#endif
#ifndef M_PI_2
#define M_PI_2 1.570796326794897f
#endif
double RandomFloat(double a, double b, double amplitude)
{
    double random = ((double)rand()) / 32768.0;
    double diff = b - a;
    double r = random * diff;
    return amplitude * (a + r);
}
void setPixel(float *mat, float fx, float fy, float r, float g, float b, int width, int height, int colourComponent, int is_added)
{
    const int
        x = (int)fx - (fx >= 0 ? 0 : 1), nx = x + 1,
        y = (int)fy - (fy >= 0 ? 0 : 1), ny = y + 1;
    const float
        dx = fx - x,
        dy = fy - y;
    if (y >= 0 && y < height)
    {
        if (x >= 0 && x < width)
        {
            const float w1 = (1.0f - dx)*(1.0f - dy);
            float w2 = is_added ? 1.0f : (1.0f - w1);
            int pos = y * width * colourComponent + x * colourComponent;
            mat[pos] = (w1 * r) + (w2 * mat[pos]);
            mat[pos + 1] = (w1 * g) + (w2 * mat[pos + 1]);
            mat[pos + 2] = (w1 * b) + (w2 * mat[pos + 2]);
        }
        if (nx >= 0 && nx < width)
        {
            const float w1 = dx * (1.0f - dy);
            float w2 = is_added ? 1.0f : (1.0f - w1);
            int pos = y * width * colourComponent + nx * colourComponent;
            mat[pos] = (w1 * r) + (w2 * mat[pos]);
            mat[pos + 1] = (w1 * g) + (w2 * mat[pos + 1]);
            mat[pos + 2] = (w1 * b) + (w2 * mat[pos + 2]);
        }
    }
    if (ny >= 0 && ny < height)
    {
        if (x >= 0 && x < width)
        {
            const float w1 = (1.0f - dx)*dy;
            float w2 = is_added ? 1.0f : (1.0f - w1);
            int pos = ny * width * colourComponent + x * colourComponent;
            mat[pos] = (w1 * r) + (w2 * mat[pos]);
            mat[pos + 1] = (w1 * g) + (w2 * mat[pos + 1]);
            mat[pos + 2] = (w1 * b) + (w2 * mat[pos + 2]);
        }
        if (nx >= 0 && nx < width)
        {
            const float w1 = dx * dy;
            float w2 = is_added ? 1.0f : (1.0f - w1);
            int pos = ny * width * colourComponent + nx * colourComponent;
            mat[pos] = (w1 * r) + (w2 * mat[pos]);
            mat[pos + 1] = (w1 * g) + (w2 * mat[pos + 1]);
            mat[pos + 2] = (w1 * b) + (w2 * mat[pos + 2]);
        }
    }
}
void DrawCircle(float *img, float x0, float y0, float r, int width, int height, int colourComponent, float red, float green, float blue)
{
    float x = 0.0f, y = 0.0f;
    float r2 = r * r;
    float d2;
    x = r;
    while (y < x)
    {
        setPixel(img, x0 + x, y0 + y, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 + y, y0 + x, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 - x, y0 - y, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 - y, y0 - x, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 + x, y0 - y, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 - x, y0 + y, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 + y, y0 - x, red, green, blue, width, height, colourComponent, 1);
        setPixel(img, x0 - y, y0 + x, red, green, blue, width, height, colourComponent, 1);
        d2 = x * x + y * y;
        if (d2 > r2)
            x--;
        else
            y++;
    }
}

void drawPoint(float *img, int width, int height, int colourComponent, Ipoint *ipt, float red, float green, float blue)
{
    // float o = ipt->orientation;
    DrawCircle(img, ipt->x, ipt->y, 3.0f, width, height, colourComponent, red, green, blue);
}
float orientationCal(float p1X, float p1Y, float p2X, float p2Y)
{
    float y = p2Y - p1Y, x = p2X - p1X;
    float result = 0.f;
    if (x != 0.0f)
    {
        const union { float flVal; unsigned int nVal; } tYSign = { y };
        const union { float flVal; unsigned int nVal; } tXSign = { x };
        if (fabsf(x) >= fabsf(y))
        {
            union { float flVal; unsigned int nVal; } tOffset = { M_PI };
            tOffset.nVal |= tYSign.nVal & 0x80000000u;
            tOffset.nVal *= tXSign.nVal >> 31;
            result = tOffset.flVal;
            const float z = y / x;
            result += (0.97239411f + -0.19194795f * z * z) * z;
        }
        else
        {
            union { float flVal; unsigned int nVal; } tOffset = { M_PI_2 };
            tOffset.nVal |= tYSign.nVal & 0x80000000u;
            result = tOffset.flVal;
            const float z = x / y;
            result -= (0.97239411f + -0.19194795f * z * z) * z;
        }
    }
    else if (y > 0.0f)
        result = M_PI_2;
    else if (y < 0.0f)
        result = -M_PI_2;
    return result;
}
float lengthCal(float p1X, float p1Y, float p2X, float p2Y)
{
    float x = (p1X - p2X) * (p1X - p2X) + (p1Y - p2Y) * (p1Y - p2Y);
    unsigned int i = *(unsigned int*)&x;
    i += 127 << 23;
    i >>= 1;
    return *(float*)&i;
}
```

```c
void DrawLine(float *img, float x0, float y0, float length, float ori, int width, int height, int colourComponent, float red, float green, float blue)
{
    float sinori = sinf(ori);
    float cosori = cosf(ori);
    int i;
    float x, y;
    float rouneD = roundf(length);
    for (i = 1; i < (int)rouneD; i++)
    {
        x = cosori * i;
        y = sinori * i;
        setPixel(img, x0 + x, y0 + y, red, green, blue, width, height, colourComponent, 1);
    }
    if (fabsf(length - rouneD) > 0.0f)
    {
        x = cosori * (length - 1.0f);
        y = sinori * (length - 1.0f);
        setPixel(img, x0 + x, y0 + y, red, green, blue, width, height, colourComponent, 1);
    }
    setPixel(img, x0, y0, 0.775f, 0.775f, 0.775f, width, height, colourComponent, 1);
}

void matcherFree(IpointPair *pair)
{
    free(pair->pt1);
    free(pair->pt2);
}

void printResponseMap(FastHessian *fh) {
    for (int i = 0; i < 1; i++) { // 假设responseMap有12层
        ResponseLayer *layer = &fh->responseMap[9];
        printf("Response Layer %d:\n", i);
        printf("  Width: %d, Height: %d, Step: %d, Filter: %d\n", layer->width, layer->height, layer->step, layer->filter);

        printf("  Responses:\n");
        for (int y = 0; y < layer->height; y++) {
            for (int x = 0; x < layer->width; x++) {
                int index = y * layer->width + x;
                printf("%f ", layer->responses[index]);
            }
            printf("\n");
        }

        printf("  Laplacians:\n");
        for (int y = 0; y < layer->height; y++) {
            for (int x = 0; x < layer->width; x++) {
                int index = y * layer->width + x;
                printf("%d ", layer->laplacian[index]);
            }
            printf("\n");
        }
    }
}

void get_output_data(int width1, int height1, int width2, int height2, unsigned char *input_data1, unsigned char *input_data2, SURFDescriptor *surf1, SURFDescriptor *surf2, float threshold) {
    IpointPair matches = getMatches(surf1, surf2, threshold);
    printf("matches.size: %d\n", matches.size);
    printf("matches.count: %d\n", matches.count);
    float *imageFloat1 = (float*)malloc(width1 * height1 * 3 * sizeof(float));
    float *imageFloat2 = (float*)malloc(width2 * height2 * 3 * sizeof(float));
    int i;
    for (i = 0; i < width1 * height1 * 3; i++)
        imageFloat1[i] = input_data1[i] / 255.0f;
    for (i = 0; i < width2 * height2 * 3; i++)
        imageFloat2[i] = input_data2[i] / 255.0f;
    for (i = 0; i < matches.count; ++i)
    {
        float red = (float)RandomFloat(0.0, 1.0, 1.0);
        float green = (float)RandomFloat(0.0, 1.0, 1.0);
        float blue = (float)RandomFloat(0.0, 1.0, 1.0);
        drawPoint(imageFloat1, width1, height1, 3, &matches.pt1[i], red, green, blue);
        drawPoint(imageFloat2, width2, height2, 3, &matches.pt2[i], red, green, blue);
        float circleOrientation = orientationCal(matches.pt1[i].x, matches.pt1[i].y, matches.pt2[i].x + width1, matches.pt2[i].y);
        float distance = lengthCal(matches.pt1[i].x, matches.pt1[i].y, matches.pt2[i].x + width1, matches.pt2[i].y);
        DrawLine(imageFloat1, matches.pt1[i].x, matches.pt1[i].y, distance, circleOrientation, width1, height1, 3, red, green, blue);
        circleOrientation = orientationCal(matches.pt1[i].x - width1, matches.pt1[i].y, matches.pt2[i].x, matches.pt2[i].y);
        distance = lengthCal(matches.pt1[i].x - width1, matches.pt1[i].y, matches.pt2[i].x, matches.pt2[i].y);
        DrawLine(imageFloat2, matches.pt1[i].x - width1, matches.pt1[i].y, distance, circleOrientation, width2, height2, 3, red, green, blue);
    }

    matcherFree(&matches);
    for (i = 0; i < width1 * height1 * 3; i++)
    {
        float value = imageFloat1[i] * 255.0f;
        if (value > 255.0f)
            input_data1[i] = 255U;
        else if (value < 0.0f)
            input_data1[i] = 0U;
        else
            input_data1[i] = (unsigned char)value;
    }
    free(imageFloat1);
    for (i = 0; i < width2 * height2 * 3; i++)
    {
        float value = imageFloat2[i] * 255.0f;
        if (value > 255.0f)
            input_data2[i] = 255U;
        else if (value < 0.0f)
            input_data2[i] = 0U;
        else
            input_data2[i] = (unsigned char)value;
    }
}

void get_output_img(unsigned char *input_data1, unsigned char *input_data2, int width1, int height1, int width2, int height2, const char *combined_output) {
    // 创建新图像缓冲区以合并两个图像
    int combined_width = width1 + width2;
    int combined_height = height1 > height2 ? height1 : height2;
    unsigned char *combined_image = (unsigned char*)malloc(combined_width * combined_height * 3);

    // 清空图像
    memset(combined_image, 0, combined_width * combined_height * 3);

    // 拷贝第一个图像到组合图像
    for (int y = 0; y < height1; y++) {
        memcpy(combined_image + y * combined_width * 3, input_data1 + y * width1 * 3, width1 * 3);
    }

    // 拷贝第二个图像到组合图像
    for (int y = 0; y < height2; y++) {
        memcpy(combined_image + y * combined_width * 3 + width1 * 3, input_data2 + y * width2 * 3, width2 * 3);
    }

    // 保存合并后的图像
    writebin(combined_output, combined_image, combined_width * combined_height * 3);
}

void SURFFree(SURFDescriptor *surf)
{
    free(surf->integralImg);
    if (surf->hessians->interestPtsLen > 0)
        free(surf->hessians->ipts);
    for (int i = 0; i < 12; i++)
    {
        if (surf->hessians->responseMap[i].responses)
        {
            free(surf->hessians->responseMap[i].responses);
            free(surf->hessians->responseMap[i].laplacian);
        }
    }
    free(surf->hessians);
}

int main() {
    int width1 = 457;
    int height1 = 630;
    int width2 = 300;
    int height2 = 414;
    int format = FORMAT_RGB_PACKED;
    int octave = 1;
    int step = 2;
    float threshold_surf = 0.01f;
    float threshold_match = 0.75f;
    const char *input_path1 = "/home/zyz/TPU1686/tpu-kernel-1684x/samples/host/test_picture/output.rgb";
    const char *input_path2 = "/home/zyz/TPU1686/tpu-kernel-1684x/samples/host/test_picture/output2.rgb";
    const char *output_path_tpu = "/home/zyz/middleware-soc/bmvid/bmcv/test/image/output_tpu.bin";
    bm_handle_t handle;
    int ret = bm_dev_request(&handle, 0);
    if (ret != BM_SUCCESS) {
        printf("Create bm handle failed. ret = %d\n", ret);
        return -1;
    }

    unsigned char* input_data1 = (unsigned char*)malloc(width1 * height1 * 3 * sizeof(unsigned char));
    unsigned char* input_data2 = (unsigned char*)malloc(width2 * height2 * 3 * sizeof(unsigned char));

    readbin(input_path1, input_data1, width1, height1, 3);
    readbin(input_path2, input_data2, width2, height2, 3);

    float *data1 = LoadToMatrixGreyWeighted(input_data1, width1, height1, format);
    float *data2 = LoadToMatrixGreyWeighted(input_data2, width2, height2, format);

    SURFDescriptor surf1, surf2;
    SURFInitialize(&surf1, width1, height1, octave, step, threshold_surf);
    SURFInitialize(&surf2, width2, height2, octave, step, threshold_surf);

    int layer_num;
    layer_num = 4 + (octave - 1) * 2;

    ret = bmcv_image_surf_response(handle, data1, &surf1, width1, height1, layer_num);
    ret = bmcv_image_surf_response(handle, data2, &surf2, width2, height2, layer_num);

    get_output_data(width1, height1, width2, height2, input_data1, input_data2, &surf1, &surf2, threshold_match);
    get_output_img(input_data1, input_data2, width1, height1, width2, height2, output_path_tpu);

    if(ret != BM_SUCCESS) {
        free(input_data1);
        free(input_data2);
        return ret;
    }

    free(input_data1);
    free(input_data2);
    free(data1);
    free(data2);

    bm_dev_free(handle);
}
```

# bmcv_image_threshold

图像阈值化操作。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

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

## 参数说明

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bm_image input
  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output
  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

* unsigned char thresh
  阈值。

* max_value
  最大值。

* bm_thresh_type_t type
  阈值化类型。

## 返回值说明

* BM_SUCCESS: 成功
* 其他:失败

## 格式支持

该接口目前支持以下image_format:

| num | input image_format     | output image_format    |
|-----|------------------------|------------------------|
| 1   | FORMAT_BGR_PACKED      | FORMAT_BGR_PACKED      |
| 2   | FORMAT_BGR_PLANAR      | FORMAT_BGR_PLANAR      |
| 3   | FORMAT_RGB_PACKED      | FORMAT_RGB_PACKED      |
| 4   | FORMAT_RGB_PLANAR      | FORMAT_RGB_PLANAR      |
| 5   | FORMAT_RGBP_SEPARATE   | FORMAT_RGBP_SEPARATE   |
| 6   | FORMAT_BGRP_SEPARATE   | FORMAT_BGRP_SEPARATE   |
| 7   | FORMAT_GRAY            | FORMAT_GRAY            |
| 8   | FORMAT_YUV420P         | FORMAT_YUV420P         |
| 9   | FORMAT_YUV422P         | FORMAT_YUV422P         |
| 10  | FORMAT_YUV444P         | FORMAT_YUV444P         |
| 11  | FORMAT_NV12            | FORMAT_NV12            |
| 12  | FORMAT_NV21            | FORMAT_NV21            |
| 13  | FORMAT_NV16            | FORMAT_NV16            |
| 14  | FORMAT_NV61            | FORMAT_NV61            |
| 15  | FORMAT_NV24            | FORMAT_NV24            |

目前支持以下data_type:

| num | data_type              |
|-----|------------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE  |

## 注意事项

1、在调用该接口之前必须确保输入的image内存已经申请。

2、input output的image_format以及data_type必须相同。

## 代码示例

```c
#include <stdio.h>
#include "bmcv_api_ext.h"
#include "test_misc.h"
#include "stdlib.h"
#include "string.h"
#include <assert.h>
#include <float.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 1;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    unsigned char* src_data = new unsigned char[channel * width * height];
    unsigned char* res_data = new unsigned char[channel * width * height];
    bm_image input, output;
    const char *src_name = "/path/to/src";
    const char *dst_name = "path/to/dst";

    bm_dev_request(&handle, dev_id);
    readBin(src_name, src_data, channel * width * height);

    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void**)&src_data);
    bm_image_create(handle, height, width, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_threshold(handle, input, output, 200, 200, BM_THRESH_BINARY);
    bm_image_copy_device_to_host(output, (void**)&res_data);
    writeBin(dst_name, res_data, channel * width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    return 0;
}
```

# bmcv_image_transpose

该接口可以实现图片宽和高的转置。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_transpose(
            bm_handle_t handle,
            bm_image input,
            bm_image output);
```

## 传入参数说明

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用bm_dev_request获取。

* bm_image input
  输入参数。输入图像的bm_image结构体。

* bm_image output
  输出参数。输出图像的bm_image结构体。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 代码示例

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    int channel = 3;
    bm_image src, dst;
    unsigned char* src_data = new unsigned char[image_h * image_w * channel];
    unsigned char* res_data = new unsigned char[image_h * image_w * channel];
    const char *src_name = "/path/to/src";
    const char *dst_name = "path/to/dst";

    bm_dev_request(&handle, 0);
    readBin(src_name, src_data, image_h * image_w * channel);
    bm_image_create(handle, image_h, image_w, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_create(handle, image_w, image_h, FORMAT_RGB_PLANAR, DATA_TYPE_EXT_1N_BYTE, &dst);
    bm_image_copy_host_to_device(src, (void **)&src_data);
    bmcv_image_transpose(handle, src, dst);
    bm_image_copy_device_to_host(dst, (void**)&res_data);
    writeBin(dst_name, res_data, image_h * image_w * channel);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    return 0;
}
```

# bmcv_image_vpp_basic

## 概述

bm1684和bm1684x上有专门的视频后处理模块VPP，在满足一定条件下可以一次实现crop、color-space-convert、resize以及padding功能，速度比Tensor Computing Processor更快。该API可以实现对多张图片的crop、color-space-convert、resize、padding及其任意若干个功能的组合。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_vpp_basic(
            bm_handle_t handle,
            int in_img_num,
            bm_image* input,
            bm_image* output,
            int* crop_num_vec = NULL,
            bmcv_rect_t* crop_rect = NULL,
            bmcv_padding_atrr_t* padding_attr = NULL,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR,
            csc_type_t csc_type = CSC_MAX_ENUM,
            csc_matrix_t* matrix = NULL);
```

## 传入参数说明

### bm_handle_t handle
输入参数。设备环境句柄，通过调用bm_dev_request获取。

### int in_img_num
输入参数。输入bm_image数量。

### bm_image* input
输入参数。输入bm_image对象指针，其指向空间的长度由in_img_num决定。

### bm_image* output
输出参数。输出bm_image对象指针，其指向空间的长度由in_img_num和crop_num_vec共同决定，即所有输入图片crop数量之和。

### int* crop_num_vec = NULL
输入参数。该指针指向对每张输入图片进行crop的数量，其指向空间的长度由in_img_num决定，如果不使用crop功能可填NULL。

### bmcv_rect_t * crop_rect = NULL
输入参数。每个输出bm_image对象所对应的在输入图像上crop的参数，包括起始点x坐标、起始点y坐标、crop图像的宽度以及crop图像的高度。图像左上顶点作为坐标原点。如果不使用crop功能可填NULL。

结构定义：
```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

### bmcv_padding_atrr_t* padding_attr = NULL
输入参数。所有crop的目标小图在dst image中的位置信息以及要padding的各通道像素值，若不使用padding功能则设置为NULL。

结构定义：
```c
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

参数说明：
1. 目标小图的左上角顶点相对于dst image原点（左上角）的offset信息：dst_crop_stx和dst_crop_sty；
2. 目标小图经resize后的宽高：dst_crop_w和dst_crop_h；
3. dst image如果是RGB格式，各通道需要padding的像素值信息：padding_r、padding_g、padding_b，当if_memset=1时有效，如果是GRAY图像可以将三个值均设置为同一个值；
4. if_memset表示要不要在该api内部对dst image按照各个通道的padding值做memset，仅支持RGB和GRAY格式的图像。如果设置为0则用户需要在调用该api前，根据需要padding的像素值信息，调用bmlib中的api直接对device memory进行memset操作，如果用户对padding的值不关心，可以设置为0忽略该步骤。

### bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR
输入参数。resize算法选择，包括BMCV_INTER_NEAREST、BMCV_INTER_LINEAR和BMCV_INTER_BICUBIC三种，默认情况下是双线性差值。

- bm1684支持：BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC
- bm1684x支持：BMCV_INTER_NEAREST，BMCV_INTER_LINEAR

### csc_type_t csc_type = CSC_MAX_ENUM
输入参数。color space convert参数类型选择，填CSC_MAX_ENUM则使用默认值，默认为CSC_YCbCr2RGB_BT601或者CSC_RGB2YCbCr_BT601，支持的类型包括：

| 类型 |
|------|
| CSC_YCbCr2RGB_BT601 |
| CSC_YPbPr2RGB_BT601 |
| CSC_RGB2YCbCr_BT601 |
| CSC_YCbCr2RGB_BT709 |
| CSC_RGB2YCbCr_BT709 |
| CSC_RGB2YPbPr_BT601 |
| CSC_YPbPr2RGB_BT709 |
| CSC_RGB2YPbPr_BT709 |
| CSC_USER_DEFINED_MATRIX |
| CSC_MAX_ENUM |

### csc_matrix_t* matrix = NULL
输入参数。如果csc_type选择CSC_USER_DEFINED_MATRIX，则需要传入系数矩阵，格式如下：

```c
typedef struct {
    int csc_coe00;
    int csc_coe01;
    int csc_coe02;
    int csc_add0;
    int csc_coe10;
    int csc_coe11;
    int csc_coe12;
    int csc_add1;
    int csc_coe20;
    int csc_coe21;
    int csc_coe22;
    int csc_add2;
} __attribute__((packed)) csc_matrix_t;
```

## 返回值说明

- BM_SUCCESS: 成功
- 其他: 失败

## 注意事项

### bm1684x支持的要求

#### 1. 支持数据类型

| num | input data_type | output data_type |
|-----|-----------------|------------------|
| 1 | | DATA_TYPE_EXT_FLOAT32 |
| 2 | | DATA_TYPE_EXT_1N_BYTE |
| 3 | DATA_TYPE_EXT_1N_BYTE | DATA_TYPE_EXT_1N_BYTE_SIGNED |
| 4 | | DATA_TYPE_EXT_FP16 |
| 5 | | DATA_TYPE_EXT_BF16 |

#### 2. 输入支持色彩格式

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

#### 3. 输出支持色彩格式

| num | output image_format |
|-----|-------------------|
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
| 12 | FORMAT_RGBYP_PLANAR |
| 13 | FORMAT_BGRP_SEPARATE |
| 14 | FORMAT_HSV180_PACKED |
| 15 | FORMAT_HSV256_PACKED |

## bm1684x vpp 格式转换限制

1. bm1684x vpp 不支持从 FORMAT_COMPRESSED 转为 FORMAT_HSV180_PACKED 或 FORMAT_HSV256_PACKED。
2. 图片缩放倍数（(crop.width / output.width) 以及 (crop.height / output.height)）限制在 1/128 ～ 128 之间。
3. 输入输出的宽高（src.width, src.height, dst.width, dst.height）限制在 8 ～ 8192 之间。
4. 输入必须关联 device memory，否则返回失败。
5. FORMAT_COMPRESSED 格式的使用方法见 bm1684 部分介绍。

## bm1684 支持要求

### 格式转换要求

该 API 所需要满足的格式以及部分要求如下表所示：

| 源格式 | 目标格式 | 其他限制 |
|--------|----------|----------|
| RGB_PACKED | RGB_PACKED | 条件1 |
| RGB_PACKED | RGB_PLANAR | 条件1 |
| RGB_PACKED | BGR_PLANAR | 条件1 |
| RGB_PACKED | BGR_PACKED | 条件1 |
| RGB_PACKED | RGBP_SEPARATE | 条件1 |
| RGB_PACKED | BGRP_SEPARATE | 条件1 |
| RGB_PACKED | ARGB_PACKED | 条件1 |
| BGR_PACKED | RGB_PACKED | 条件1 |
| BGR_PACKED | RGB_PLANAR | 条件1 |
| BGR_PACKED | BGR_PACKED | 条件1 |
| BGR_PACKED | BGR_PLANAR | 条件1 |
| BGR_PACKED | RGBP_SEPARATE | 条件1 |
| BGR_PACKED | BGRP_SEPARATE | 条件1 |
| RGB_PLANAR | RGB_PACKED | 条件1 |
| RGB_PLANAR | RGB_PLANAR | 条件1 |
| RGB_PLANAR | BGR_PACKED | 条件1 |
| RGB_PLANAR | BGR_PLANAR | 条件1 |
| RGB_PLANAR | RGBP_SEPARATE | 条件1 |
| RGB_PLANAR | BGRP_SEPARATE | 条件1 |
| RGB_PLANAR | ARGB_PACKED | 条件1 |
| BGR_PLANAR | RGB_PACKED | 条件1 |
| BGR_PLANAR | RGB_PLANAR | 条件1 |
| BGR_PLANAR | BGR_PACKED | 条件1 |
| BGR_PLANAR | BGR_PLANAR | 条件1 |
| BGR_PLANAR | RGBP_SEPARATE | 条件1 |
| BGR_PLANAR | BGRP_SEPARATE | 条件1 |
| RGBP_SEPARATE | RGB_PACKED | 条件1 |
| RGBP_SEPARATE | RGB_PLANAR | 条件1 |
| RGBP_SEPARATE | BGR_PACKED | 条件1 |
| RGBP_SEPARATE | BGR_PLANAR | 条件1 |
| RGBP_SEPARATE | RGBP_SEPARATE | 条件1 |
| RGBP_SEPARATE | BGRP_SEPARATE | 条件1 |
| BGRP_SEPARATE | RGB_PACKED | 条件1 |
| BGRP_SEPARATE | RGB_PLANAR | 条件1 |
| BGRP_SEPARATE | BGR_PACKED | 条件1 |
| BGRP_SEPARATE | BGR_PLANAR | 条件1 |
| BGRP_SEPARATE | RGBP_SEPARATE | 条件1 |
| BGRP_SEPARATE | BGRP_SEPARATE | 条件1 |
| ARGB_PACKED | RGB_PLANAR | 条件1 |
| ARGB_PACKED | RGB_PACKED | 条件1 |
| ARGB_PACKED | ARGB_PACKED | 条件1 |
| GRAY | GRAY | 条件1 |
| YUV420P | YUV420P | 条件2 |
| COMPRESSED | YUV420P | 条件2 |
| RGB_PACKED | YUV420P | 条件3 |
| RGB_PLANAR | YUV420P | 条件3 |
| BGR_PACKED | YUV420P | 条件3 |
| BGR_PLANAR | YUV420P | 条件3 |
| RGBP_SEPARATE | YUV420P | 条件3 |
| BGRP_SEPARATE | YUV420P | 条件3 |
| ARGB_PACKED | YUV420P | 条件3 |
| YUV420P | RGB_PACKED | 条件4 |
| YUV420P | RGB_PLANAR | 条件4 |
| YUV420P | BGR_PACKED | 条件4 |
| YUV420P | BGR_PLANAR | 条件4 |
| YUV420P | RGBP_SEPARATE | 条件4 |
| YUV420P | BGRP_SEPARATE | 条件4 |
| YUV420P | ARGB_PACKED | 条件4 |
| NV12 | RGB_PACKED | 条件4 |
| NV12 | RGB_PLANAR | 条件4 |
| NV12 | BGR_PACKED | 条件4 |
| NV12 | BGR_PLANAR | 条件4 |
| NV12 | RGBP_SEPARATE | 条件4 |
| NV12 | BGRP_SEPARATE | 条件4 |
| COMPRESSED | RGB_PACKED | 条件4 |
| COMPRESSED | RGB_PLANAR | 条件4 |
| COMPRESSED | BGR_PACKED | 条件4 |
| COMPRESSED | BGR_PLANAR | 条件4 |
| COMPRESSED | RGBP_SEPARATE | 条件4 |
| COMPRESSED | BGRP_SEPARATE | 条件4 |

### 条件说明

- **条件1**：src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- **条件2**：src.width, src.height, dst.width, dst.height 必须是 2 的整数倍，src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- **条件3**：dst.width, dst.height 必须是 2 的整数倍，src.width == dst.width，src.height == dst.height，crop.x == 0，crop.y == 0，src.width >= crop.x + crop.width，src.height >= crop.y + crop.height
- **条件4**：src.width, src.height 必须是 2 的整数倍，src.width >= crop.x + crop.width，src.height >= crop.y + crop.height

### 其他要求

1. 输入 bm_image 的 device mem 不能在 heap0 上。
2. 所有输入输出 image 的 stride 必须 64 对齐。
3. 所有输入输出 image 的地址必须 32 byte 对齐。
4. 图片缩放倍数（(crop.width / output.width) 以及 (crop.height / output.height)）限制在 1/32 ～ 32 之间。
5. 输入输出的宽高（src.width, src.height, dst.width, dst.height）限制在 16 ～ 4096 之间。
6. 输入必须关联 device memory，否则返回失败。

### FORMAT_COMPRESSED 格式说明

FORMAT_COMPRESSED 是 VPU 解码后内置的一种压缩格式，它包括 4 个部分：Y compressed table、Y compressed data、CbCr compressed table 以及 CbCr compressed data。请注意 bm_image 中这四部分存储的顺序与 FFMPEG 中 AVFrame 稍有不同，如果需要 attach AVFrame 中 device memory 数据到 bm_image 中时，对应关系如下：

```c
bm_device_mem_t src_plane_device[4];
src_plane_device[0] = bm_mem_from_device((u64)avframe->data[6], avframe->linesize[6]);
src_plane_device[1] = bm_mem_from_device((u64)avframe->data[4], avframe->linesize[4] * avframe->h);
src_plane_device[2] = bm_mem_from_device((u64)avframe->data[7], avframe->linesize[7]);
src_plane_device[3] = bm_mem_from_device((u64)avframe->data[5], avframe->linesize[4] * avframe->h / 2);
bm_image_attach(*compressed_image, src_plane_device);
```

# bmcv_image_vpp_convert

该 API 将输入图像格式转化为输出图像格式，并支持 crop + resize 功能，支持从 1 张输入中 crop 多张输出并 resize 到输出图片大小。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_vpp_convert(
            bm_handle_t handle,
            int output_num,
            bm_image input,
            bm_image *output,
            bmcv_rect_t *crop_rect,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

**传入参数说明:**

* bm_handle_t handle

  输入参数。设备环境句柄，通过调用 bm_dev_request 获取

* int output_num

  输出参数。输出 bm_image 数量，和src image的crop 数量相等，一个src crop 输出一个dst bm_image

* bm_image input

  输入参数。输入 bm_image 对象

* bm_image* output

  输出参数。输出 bm_image 对象指针

* bmcv_rect_t * crop_rect

  输入参数。具体格式定义如下：

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

每个输出 bm_image 对象所对应的在输入图像上 crop 的参数，包括起始点x坐标、起始点y坐标、crop图像的宽度以及crop图像的高度。

* bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR

  输入参数。resize 算法选择，包括 BMCV_INTER_NEAREST 、 BMCV_INTER_LINEAR 和 BMCV_INTER_BICUBIC 三种，默认情况下是双线性差值。

  bm1684 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。

  bm1684x 支持BMCV_INTER_NEAREST， BMCV_INTER_LINEAR。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项:**

1. 该 API 所需要满足的格式以及部分要求与 bmcv_image_vpp_basic 中的表格相同。

2. bm1684 输入输出的宽高（src.width, src.height, dst.widht, dst.height）限制在 16 ～ 4096 之间。

   bm1684x 输入输出的宽高（src.width, src.height, dst.widht, dst.height）限制在 8 ～ 8192 之间，缩放128倍。

3. 输入必须关联 device memory，否则返回失败。

4. FORMAT_COMPRESSED 是 VPU 解码后内置的一种压缩格式，它包括4个部分：Y compressed table、Y compressed data、CbCr compressed table 以及 CbCr compressed data。请注意 bm_image 中这四部分存储的顺序与 FFMPEG 中 AVFrame 稍有不同，如果需要 attach AVFrame 中 device memory 数据到 bm_image 中时，对应关系如下，关于 AVFrame 详细内容请参考 VPU 的用户手册。

```c
bm_device_mem_t src_plane_device[4];
src_plane_device[0] = bm_mem_from_device((u64)avframe->data[6], avframe->linesize[6]);
src_plane_device[1] = bm_mem_from_device((u64)avframe->data[4], avframe->linesize[4] * avframe->h);
src_plane_device[2] = bm_mem_from_device((u64)avframe->data[7], avframe->linesize[7]);
src_plane_device[3] = bm_mem_from_device((u64)avframe->data[5], avframe->linesize[4] * avframe->h / 2);
bm_image_attach(*compressed_image, src_plane_device);
```

**代码示例：**

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include <memory>
#include "stdio.h"
#include "stdlib.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src, dst[4];
    bmcv_rect_t rect[] = {{0, 0, image_w / 2, image_h / 2},
            {0, image_h / 2, image_w / 2, image_h / 2},
            {image_w / 2, 0, image_w / 2, image_h / 2},
            {image_w / 2, image_h / 2, image_w / 2, image_h / 2}};
    unsigned char* src_data = new unsigned char[image_h * image_w * 3 / 2];
    unsigned char* dst_data = new unsigned char[image_h / 2 * image_w / 2 * 3];
    unsigned char* in_ptr[3] = {src_data, src_data + image_h * image_w, src_data + 2 * image_h * image_w};
    unsigned char* out_ptr[3] = {dst_data, dst_data + image_h * image_w, dst_data + 2 * image_h * image_w};
    const char *src_name = "/path/to/src";
    const char *dst_names[4] = {"path/to/dst0", "path/to/dst1", "path/to/dst2", "path/to/dst3"};

    bm_dev_request(&handle, 0);
    readBin(src_name, src_data, image_h * image_w * 3 / 2);
    bm_image_create(handle, image_h, image_w, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_alloc_dev_mem(src, 1);
    for (int i = 0; i < 4; i++) {
        bm_image_create(handle, image_h / 2, image_w / 2, FORMAT_BGR_PACKED, DATA_TYPE_EXT_1N_BYTE, dst + i);
        bm_image_alloc_dev_mem(dst[i]);
    }

    bm_image_copy_host_to_device(src, (void **)in_ptr);
    bmcv_image_vpp_convert(handle, 4, src, dst, rect);

    for(int i = 0; i < 4; ++i) {
        bm_image_copy_device_to_host(dst[i], (void**)out_ptr);
        writeBin(dst_names[i], dst_data, image_h / 2 * image_w / 2 * 3);
    }

    for (int i = 0; i < 4; i++) {
        bm_image_destroy(dst[i]);
    }
    bm_image_destroy(src);
    bm_dev_free(handle);
```

# bmcv_image_vpp_convert_padding

使用vpp硬件资源，通过对 dst image 做 memset 操作，实现图像padding的效果。这个效果的实现是利用了vpp的dst crop的功能，通俗的讲是将一张小图填充到大图中。
可以从一张src image上crop多个目标图像，对于每一个目标小图，可以一次性完成csc+resize操作，然后根据其在大图中的offset信息，填充到大图中。
一次crop的数量不能超过256。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_vpp_convert_padding(
            bm_handle_t handle,
            int output_num,
            bm_image input,
            bm_image* output,
            bmcv_padding_atrr_t* padding_attr,
            bmcv_rect_t* crop_rect = NULL,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

**传入参数说明:**

* bm_handle_t handle

  输入参数。设备环境句柄，通过调用 bm_dev_request 获取

* int output_num

  输出参数。输出 bm_image 数量，和src image的crop 数量相等，一个src crop 输出一个dst bm_image

* bm_image input

  输入参数。输入 bm_image 对象

* bm_image* output

  输出参数。输出 bm_image 对象指针

* bmcv_padding_atrr_t *  padding_attr

  输入参数。src crop的目标小图在dst image中的位置信息以及要pdding的各通道像素值

```c
typedef struct bmcv_padding_atrr_s {
    unsigned int    dst_crop_stx;
    unsigned int    dst_crop_sty;
    unsigned int    dst_crop_w;
    unsigned int    dst_crop_h;
    unsigned char padding_r;
    unsigned char padding_g;
    unsigned char padding_b;
    int           if_memset;
} bmcv_padding_atrr_t;
```

1. 目标小图的左上角顶点相对于 dst image 原点（左上角）的offset信息：dst_crop_stx 和 dst_crop_sty；
2. 目标小图经resize后的宽高：dst_crop_w 和 dst_crop_h；
3. dst image 如果是RGB格式，各通道需要padding的像素值信息：padding_r、padding_g、padding_b，当if_memset=1时有效，如果是GRAY图像可以将三个值均设置为同一个值；
4. if_memset表示要不要在该api内部对dst image 按照各个通道的padding值做memset，仅支持RGB和GRAY格式的图像。

* bmcv_rect_t *   crop_rect

  输入参数。在src image上的各个目标小图的坐标和宽高信息

  具体格式定义如下：

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

* bmcv_resize_algorithm algorithm

  输入参数。resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR 和 BMCV_INTER_BICUBIC 三种，默认情况下是双线性差值。

  bm1684 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。

  bm1684x 支持BMCV_INTER_NEAREST， BMCV_INTER_LINEAR。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**注意事项:**

1. 该 API 的dst image的格式仅支持:

| num | dst image_format              |
|-----|-------------------------------|
| 1   | FORMAT_RGB_PLANAR             |
| 2   | FORMAT_BGR_PLANAR             |
| 3   | FORMAT_RGBP_SEPARATE          |
| 4   | FORMAT_BGRP_SEPARATE          |
| 5   | FORMAT_RGB_PACKED             |
| 6   | FORMAT_BGR_PACKED             |

2. 该 API 所需要满足的格式以及部分要求与 bmcv_image_vpp_basic 一致。

**代码示例**

```c
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    const char *filename_src = "path/to/src";
    const char *filename_dst = "path/to/dst";
    int in_width = 1920;
    int in_height = 1080;
    int out_width = 1920;
    int out_height = 1080;
    bm_image_format_ext src_format = FORMAT_YUV420P0;
    bm_image_format_ext dst_format = FORMAT_YUV420P;
    bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR;

    bmcv_rect_t crop_rect = {
        .start_x = 100,
        .start_y = 100,
        .crop_w = 500,
        .crop_h = 500
        };

    bmcv_padding_atrr_t padding_rect = {
        .dst_crop_stx = 0,
        .dst_crop_sty = 0,
        .dst_crop_w = 1000,
        .dst_crop_h = 1000,
        .padding_r = 155,
        .padding_g = 20,
        .padding_b = 36,
        .if_memset = 1
        };

    bm_status_t ret = BM_SUCCESS;
    int src_size = in_height * in_width * 3 / 2;
    int dst_size = in_height * in_width * 3 / 2;
    unsigned char *src_data = (unsigned char *)malloc(src_size);
    unsigned char *dst_data = (unsigned char *)malloc(dst_size);

    readBin(filename_src, src_data, src_size);
    bm_handle_t handle = NULL;
    int dev_id = 0;
    bm_image src, dst;

    ret = bm_dev_request(&handle, dev_id);
    bm_image_create(handle, in_height, in_width, src_format, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, out_height, out_width, dst_format, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);
    bm_image_alloc_dev_mem(src, BMCV_HEAP1_ID);
    bm_image_alloc_dev_mem(dst, BMCV_HEAP1_ID);

    int src_image_byte_size[4] = {0};
    bm_image_get_byte_size(src, src_image_byte_size);
    void *src_in_ptr[4] = {(void *)src_data,
                            (void *)((char *)src_data + src_image_byte_size[0]),
                            (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1]),
                            (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1] + src_image_byte_size[2])};

    bm_image_copy_host_to_device(src, (void **)src_in_ptr);
    ret = bmcv_image_vpp_convert_padding(handle, 1, src, &dst, &padding_rect, &crop_rect, algorithm);

    int dst_image_byte_size[4] = {0};
    bm_image_get_byte_size(dst, dst_image_byte_size);
    void *dst_in_ptr[4] = {(void *)dst_data,
                            (void *)((char *)dst_data + dst_image_byte_size[0]),
                            (void *)((char *)dst_data + dst_image_byte_size[0] + dst_image_byte_size[1]),
                            (void *)((char *)dst_data + dst_image_byte_size[0] + dst_image_byte_size[1] + dst_image_byte_size[2])};

    bm_image_copy_device_to_host(dst, (void **)dst_in_ptr);
    writeBin(filename_dst, dst_data, dst_size);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    free(src_data);
    free(dst_data);
    return ret;
}
```

# bmcv_image_vpp_csc_matrix_convert

默认情况下，bmcv_image_vpp_convert使用的是BT_601标准进行色域转换。有些情况下需要使用其他标准，或者用户自定义csc参数。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_vpp_csc_matrix_convert(
            bm_handle_t handle,
            int output_num,
            bm_image input,
            bm_image* output,
            csc_type_t csc,
            csc_matrix_t* matrix = nullptr,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

**传入参数说明:**

* bm_handle_t handle

  输入参数。设备环境句柄，通过调用 bm_dev_request 获取

* int image_num

  输入参数。输入 bm_image 数量

* bm_image input

  输入参数。输入 bm_image 对象

* bm_image* output

  输出参数。输出 bm_image 对象指针

* csc_type_t csc

  输入参数。色域转换枚举类型，目前可选：

```c
typedef enum csc_type {
    CSC_YCbCr2RGB_BT601 = 0,
    CSC_YPbPr2RGB_BT601,
    CSC_RGB2YCbCr_BT601,
    CSC_YCbCr2RGB_BT709,
    CSC_RGB2YCbCr_BT709,
    CSC_RGB2YPbPr_BT601,
    CSC_YPbPr2RGB_BT709,
    CSC_RGB2YPbPr_BT709,
    CSC_USER_DEFINED_MATRIX = 1000,
    CSC_MAX_ENUM
} csc_type_t;
```

* csc_matrix_t * matrix

  输入参数。色域转换自定义矩阵，当且仅当csc为CSC_USER_DEFINED_MATRIX时这个值才生效。

  具体格式定义如下：

```c
typedef struct {
    int csc_coe00;
    int csc_coe01;
    int csc_coe02;
    int csc_add0;
    int csc_coe10;
    int csc_coe11;
    int csc_coe12;
    int csc_add1;
    int csc_coe20;
    int csc_coe21;
    int csc_coe22;
    int csc_add2;
} __attribute__((packed)) csc_matrix_t;
```

bm1684：

# bmcv_image_vpp_csc_matrix_convert

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_vpp_csc_matrix_convert(
            bm_handle_t handle,
            int input_num,
            bm_image* input,
            bm_image* output,
            bmcv_csc_type_t csc_type,
            bmcv_csc_matrix_t* matrix = NULL,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

## 传入参数说明

### bm_handle_t handle

输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

### int input_num

输入参数。输入 bm_image 数量。

### bm_image* input

输入参数。输入 bm_image 对象指针。

### bm_image* output

输出参数。输出 bm_image 对象指针。

### bmcv_csc_type_t csc_type

输入参数。色域转换类型。

### bmcv_csc_matrix_t* matrix

输入参数。用户自定义的色域转换矩阵。

### bmcv_resize_algorithm algorithm

输入参数。resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR 和 BMCV_INTER_BICUBIC 三种，默认情况下是双线性插值。

bm1684 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。

bm1684x 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 该 API 所需要满足的格式以及部分要求与vpp_convert一致。

2. 如果色域转换枚举类型与input和output格式不对应，如csc == CSC_YCbCr2RGB_BT601，而input image_format为RGB格式，则返回失败。

3. 如果csc == CSC_USER_DEFINED_MATRIX而matrix为nullptr，则返回失败。

## 代码示例

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include <memory>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src, dst[4];
    unsigned char* src_data = new unsigned char[image_h * image_w * 3 / 2];
    unsigned char* dst_data = new unsigned char[image_h / 2 * image_w / 2 * 3];
    unsigned char* in_ptr[3] = {src_data, src_data + image_h * image_w, src_data + 2 * image_h * image_w};
    unsigned char* out_ptr[3] = {dst_data, dst_data + image_h * image_w, dst_data + 2 * image_h * image_w};
    const char *src_name = "/path/to/src";
    const char *dst_names = {"path/to/dst0", "path/to/dst1", "path/to/dst2", "path/to/dst3"};

    bm_dev_request(&handle, 0);
    readBin(src_name, src_data, image_h * image_w * 3 / 2);
    bm_image_create(handle, image_h, image_w, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_alloc_dev_mem(src, 1);
    for (int i = 0; i < 4; i++) {
        bm_image_create(handle, image_h / 2, image_w / 2, FORMAT_BGR_PACKED, DATA_TYPE_EXT_1N_BYTE, dst + i);
        bm_image_alloc_dev_mem(dst[i]);
    }
    memset(src_data, 148, image_h * image_w * 3 / 2);
    bm_image_copy_host_to_device(src, (void**)in_ptr);
    bmcv_image_vpp_csc_matrix_convert(handle, 4, src, dst, CSC_YCbCr2RGB_BT601);

    for(int i = 0; i < 4; ++i) {
        bm_image_copy_device_to_host(dst[i], (void**)out_ptr);
        writeBin(dst_names[i], dst_data, image_h / 2 * image_w / 2 * 3);
    }

    for (int i = 0; i < 4; i++) {
        bm_image_destroy(dst[i]);
    }
    bm_image_destroy(src);
    bm_dev_free(handle);
    delete[] src_data;
    return 0;
}
```

# bmcv_image_vpp_stitch

使用vpp硬件资源的 crop 功能，实现图像拼接的效果，对输入 image 可以一次完成 src crop + csc + resize + dst crop操作。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_vpp_stitch(
            bm_handle_t handle,
            int input_num,
            bm_image* input,
            bm_image output,
            bmcv_rect_t* dst_crop_rect,
            bmcv_rect_t* src_crop_rect = NULL,
            bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR);
```

## 传入参数说明

### bm_handle_t handle

输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

### int input_num

输入参数。输入 bm_image 数量。

### bm_image* input

输入参数。输入 bm_image 对象指针。

### bm_image output

输出参数。输出 bm_image 对象。

### bmcv_rect_t* dst_crop_rect

输入参数。在dst images上，各个目标小图的坐标和宽高信息。

### bmcv_rect_t* src_crop_rect

输入参数。在src image上，各个目标小图的坐标和宽高信息。

具体格式定义如下：

```c
typedef struct bmcv_rect {
    int start_x;
    int start_y;
    int crop_w;
    int crop_h;
} bmcv_rect_t;
```

### bmcv_resize_algorithm algorithm

输入参数。resize 算法选择，包括 BMCV_INTER_NEAREST、BMCV_INTER_LINEAR 和 BMCV_INTER_BICUBIC 三种，默认情况下是双线性插值。

bm1684 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR，BMCV_INTER_BICUBIC。

bm1684x 支持 BMCV_INTER_NEAREST，BMCV_INTER_LINEAR。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 该 API 的src image不支持压缩格式的数据。

2. 该 API 所需要满足的格式以及部分要求与 bmcv_image_vpp_basic 一致。

3. 如果对src image做crop操作，一张src image只crop一个目标。

4. 1684支持 input_num 最大为256，1684x支持 input_num 最大为512。

## 代码示例

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bmcv_api_ext_c.h"
#include <unistd.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_status_t ret;
    int src_h = 1080, src_w = 1920, dst_w = 1920, dst_h = 2160, dev_id = 0;
    bm_image_format_ext src_fmt = FORMAT_YUV420P, dst_fmt = FORMAT_YUV420P;
    const char *src_name = "path/to/src", *dst_name = "/path/to/dst";
    bmcv_rect_t dst_rect0 = {.start_x = 0, .start_y = 0, .crop_w = 1920, .crop_h = 1080};
    bmcv_rect_t dst_rect1 = {.start_x = 0, .start_y = 1080, .crop_w = 1920, .crop_h = 1080};
    bm_handle_t handle = NULL;
    bm_image src, dst;
    ret = bm_dev_request(&handle, dev_id);
    bm_image_create(handle, src_h, src_w, src_fmt, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_create(handle, dst_h, dst_w, dst_fmt, DATA_TYPE_EXT_1N_BYTE, &dst, NULL);

    ret = bm_image_alloc_dev_mem(src,BMCV_HEAP1_ID);
    ret = bm_image_alloc_dev_mem(dst,BMCV_HEAP1_ID);

    int src_size = src_h * src_w * 3 / 2;
    int dst_size = src_h * src_w * 3 / 2;
    unsigned char *src_data = (unsigned char *)malloc(src_size);
    unsigned char *dst_data = (unsigned char *)malloc(dst_size);

    readBin(src_name, src_data, src_size);

    int src_image_byte_size[4] = {0};
    bm_image_get_byte_size(src, src_image_byte_size);
    void *src_in_ptr[4] = {(void *)src_data,
                            (void *)((char *)src_data + src_image_byte_size[0]),
                            (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1]),
                            (void *)((char *)src_data + src_image_byte_size[0] + src_image_byte_size[1] + src_image_byte_size[2])};
    bm_image_copy_host_to_device(src, (void **)src_in_ptr);

    bmcv_rect_t rect = {.start_x = 0, .start_y = 0, .crop_w = src_w, .crop_h = src_h};
    bmcv_rect_t src_rect[2] = {rect, rect};
    bmcv_rect_t dst_rect[2] = {dst_rect0, dst_rect1};

    bm_image input[2] = {src, src};
    bmcv_image_vpp_stitch(handle, 2, input, dst, dst_rect, src_rect, BMCV_INTER_LINEAR);

    int dst_image_byte_size[4] = {0};
    bm_image_get_byte_size(dst, dst_image_byte_size);
    void *dst_in_ptr[4] = {(void *)dst_data,
                            (void *)((char *)dst_data + dst_image_byte_size[0]),
                            (void *)((char *)dst_data + dst_image_byte_size[0] + dst_image_byte_size[1]),
                            (void *)((char *)dst_data + dst_image_byte_size[0] + dst_image_byte_size[1] + dst_image_byte_size[2])};
    bm_image_copy_device_to_host(dst, (void **)dst_in_ptr);
    writeBin(dst_name, dst_data, dst_size);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_image_warp_affine

该接口实现图像的仿射变换，可实现旋转、平移、缩放等操作。仿射变换是一种二维坐标 (x , y) 到二维坐标(x0 , y0)的线性变换，该接口的实现是针对输出图像的每一个像素点找到在输入图像中对应的坐标，从而构成一幅新的图像，其数学表达式形式如下：

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

bmcv_affine_matrix定义了一个坐标变换矩阵，其顺序为float m[6] = {a1, b1, c1, a2, b2, c2}。
而bmcv_affine_image_matrix定义了一张图片里面有几个变换矩阵，通常来说一张图片有多个人脸时，会对应多个变换矩阵。

```c
typedef struct bmcv_affine_matrix_s{
        float m[6];
} bmcv_warp_matrix;

typedef struct bmcv_affine_image_matrix_s{
        bmcv_affine_matrix *matrix;
        int matrix_num;
} bmcv_affine_image_matrix;
```

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式一:**

```c
bm_status_t bmcv_image_warp_affine(
            bm_handle_t handle,
            int image_num,
            bmcv_affine_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

**接口形式二:**

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

## 输入参数说明

* bm_handle_t handle

  输入参数。输入的bm_handle句柄。

* int image_num

  输入参数。输入图片数，最多支持4。

* bmcv_affine_image_matrix matrix[4]

  输入参数。每张图片对应的变换矩阵数据结构，最多支持4张图片。

* bm_image* input

  输入参数。输入bm_image，对于1N模式，最多4个bm_image，对于4N模式，最多一个bm_image。

* bm_image* output

  输出参数。输出bm_image，外部需要调用bmcv_image_create创建，建议用户调用bmcv_image_attach来分配device memory。如果用户不调用attach，则内部分配device memory。对于输出bm_image，其数据类型和输入一致，即输入是4N模式，则输出也是4N模式,输入1N模式，输出也是1N模式。所需要的bm_image大小是所有图片的变换矩阵之和。比如输入1个4N模式的bm_image，4张图片的变换矩阵数目为【3,0,13,5】，则共有变换矩阵3+0+13+5=21，由于输出是4N模式，则需要(21+4-1)/4=6个bm_image的输出。

* int use_bilinear

  输入参数。是否使用bilinear进行插值，若为0则使用nearest插值，若为1则使用bilinear插值，默认使用nearest插值。选择nearest插值的性能会优于bilinear，因此建议首选nearest插值，除非对精度有要求时可选择使用bilinear插值。

## 返回值说明:

* BM_SUCCESS: 成功
* 其他: 失败

## 注意事项

1. 该接口所支持的image_format包括：

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PLANAR |
| 2   | FORMAT_RGB_PLANAR |
| 3   | FORMAT_GRAY       |

2. bm1684中该接口所支持的data_type包括：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |
| 2   | DATA_TYPE_EXT_4N_BYTE |

3. bm1684X中该接口所支持的data_type包括：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

4. 该接口的输入以及输出bm_image均支持带有stride。

5. 要求该接口输入bm_image的width、height、image_format以及data_type必须保持一致。

6. 要求该接口输出bm_image的width、height、image_format、data_type以及stride必须保持一致。

## 代码示例

```c
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>
#include <iostream>
#include "bmcv_api_ext.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    int dst_h = 256;
    int dst_w = 256;
    int use_bilinear = 0;
    bmcv_affine_image_matrix matrix_image;
    bm_image src, dst;
    bmcv_affine_matrix* matrix_data = (bmcv_affine_matrix*)malloc(sizeof(bmcv_affine_matrix) * 1);
    unsigned char* src_data = new unsigned char[image_h * image_w * 3];
    unsigned char* res_data = new unsigned char[dst_h * dst_w * 3];
    const char *filename_src = "path/to/src";
    const char *filename_dst = "path/to/dst";

    readBin(filename_src, src_data, image_h * image_w * 3);
    matrix_image.matrix_num = 1;
    matrix_image.matrix = matrix_data;
    matrix_image.matrix->m[0] = 3.848430;
    matrix_image.matrix->m[1] = -0.02484;
    matrix_image.matrix->m[2] = 916.7;
    matrix_image.matrix->m[3] = 0.02;
    matrix_image.matrix->m[4] = 3.8484;
    matrix_image.matrix->m[5] = 56.4748;

    bm_dev_request(&handle, 0);
    bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_create(handle, dst_h, dst_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &dst);
    bm_image_copy_host_to_device(src, (void**)&src_data);
    bmcv_image_warp_affine(handle, 1, &matrix_image, &src, &dst, use_bilinear);
    bm_image_copy_device_to_host(dst, (void**)&res_data);
    writeBin(filename_dst, res_data, dst_h * dst_w * 3);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    free(matrix_data);
    return 0;
}
```

# bmcv_image_warp_affine_padding

**接口说明**

* 所有的使用方式均和上述的bmcv_image_warp_affine相同，仅仅改变了接口名字，具体的padding zero的接口名字如下：

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

* 接口仅仅支持1684x

**代码示例说明**

* 同bmcv_image_warp_affine接口使用方式相同，只需要将接口名字换成bmcv_image_warp_affine_padding或bmcv_image_warp_affine_similar_to_opencv_padding即可。

# bmcv_image_warp_perspective

该接口实现图像的透射变换，又称投影变换或透视变换。透射变换将图片投影到一个新的视平面，是一种二维坐标(x0 , y0)到二维坐标(x , y)的非线性变换，该接口的实现是针对输出图像的每一个像素点坐标得到对应输入图像的坐标，然后构成一幅新的图像，其数学表达式形式如下：

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

坐标变换矩阵是一个9点的矩阵（通常c3 = 1），利用该变换矩阵可以从输出图像坐标推导出对应的输入原图坐标，该变换矩阵可以通过输入输出图像对应的4个点的坐标来获取。

为了更方便地完成透射变换，该库提供了两种形式的接口供用户使用：一种是用户提供变换矩阵给接口作为输入;另一种接口是提供输入图像中4个点的坐标作为输入，适用于将一个不规则的四边形透射为一个与输出大小相同的矩形，可以将输入图像A'B'C'D'映射为输出图像ABCD，用户只需要提供输入图像中A'、B'、C'、D'四个点的坐标即可，该接口内部会根据这四个的坐标和输出图像四个顶点的坐标自动计算出变换矩阵，从而完成该功能。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

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

其中，bmcv_perspective_matrix定义了一个坐标变换矩阵，其顺序为float m[9] = {a1, b1, c1, a2, b2, c2, a3, b3, c3}。
而bmcv_perspective_image_matrix定义了一张图片里面有几个变换矩阵，可以实现对一张图片里的多个小图进行透射变换。

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

其中，bmcv_perspective_coordinate定义了四边形四个顶点的坐标，按照左上、右上、左下、右下的顺序存储。
而bmcv_perspective_image_coordinate定义了一张图片里面有几组四边形的坐标，可以实现对一张图片里的多个小图进行透射变换。

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

## 接口形式三

```c
bm_status_t bmcv_image_warp_perspective_similar_to_opencv(
            bm_handle_t handle,
            int image_num,
            bmcv_perspective_image_matrix matrix[4],
            bm_image* input,
            bm_image* output,
            int use_bilinear = 0);
```

本接口中bmcv_perspective_image_matrix定义的变换矩阵与opencv的warpPerspective接口要求输入的变换矩阵相同，且与接口一中同名结构体定义的矩阵互为逆矩阵，其余参数与接口一相同。

```c
typedef struct bmcv_perspective_matrix_s{
        float m[9];
} bmcv_perspective_matrix;

typedef struct bmcv_perspective_image_matrix_s{
        bmcv_perspective_matrix *matrix;
        int matrix_num;
} bmcv_perspective_image_matrix;
```

### 输入参数说明

* **bm_handle_t handle**  
  输入参数。输入的bm_handle句柄。

* **int image_num**  
  输入参数。输入图片数，最多支持4。

* **bmcv_perspective_image_matrix matrix[4]**  
  输入参数。每张图片对应的变换矩阵数据结构，最多支持4张图片。

* **bmcv_perspective_image_coordinate coord[4]**  
  输入参数。每张图片对应的四边形坐标信息，最多支持4张图片。

* **bm_image\* input**  
  输入参数。输入bm_image，对于1N模式，最多4个bm_image，对于4N模式，最多一个bm_image。

* **bm_image\* output**  
  输出参数。输出bm_image，外部需要调用bmcv_image_create创建，建议用户调用bmcv_image_attach来分配device memory。如果用户不调用attach，则内部分配device memory。对于输出bm_image，其数据类型和输入一致，即输入是4N模式，则输出也是4N模式,输入1N模式，输出也是1N模式。所需要的bm_image大小是所有图片的变换矩阵之和。比如输入1个4N模式的bm_image，4张图片的变换矩阵数目为【3,0,13,5】，则共有变换矩阵3+0+13+5=21，由于输出是4N模式，则需要(21+4-1)/4=6个bm_image的输出。

* **int use_bilinear**  
  输入参数。是否使用bilinear进行插值，若为0则使用nearest插值，若为1则使用bilinear插值，默认使用nearest插值。选择nearest插值的性能会优于bilinear，因此建议首选nearest插值，除非对精度有要求时可选择使用bilinear插值。1684x尚不支持bilinear插值。

### 返回值说明

* **BM_SUCCESS**: 成功
* **其他**: 失败

### 注意事项

1. 该接口要求输出图像的所有坐标点都能在输入的原图中找到对应的坐标点，不能超出原图大小，建议优先使用接口二，可以自动满足该条件。

2. 该接口所支持的image_format包括：

| num | image_format      |
|-----|-------------------|
| 1   | FORMAT_BGR_PLANAR |
| 2   | FORMAT_RGB_PLANAR |

3. bm1684中，该接口所支持的data_type包括：

| num | data_type           |
|-----|---------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |
| 2   | DATA_TYPE_EXT_4N_BYTE |

4. bm1684X中，该接口所支持的data_type包括：

| num | data_type           |
|-----|---------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

5. 该接口的输入以及输出bm_image均支持带有stride。

6. 要求该接口输入bm_image的width、height、image_format以及data_type必须保持一致。

7. 要求该接口输出bm_image的width、height、image_format、data_type以及stride必须保持一致。

### 代码示例

```c
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>
#include <iostream>
#include "bmcv_api_ext.h"

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_h = 1080;
    int image_w = 1920;
    int dst_h = 1080;
    int dst_w = 1920;
    int use_bilinear = 0;
    bm_image src, dst;
    bmcv_perspective_image_matrix matrix_image;
    matrix_image.matrix_num = 1;
    bmcv_perspective_matrix* matrix_data = (bmcv_perspective_matrix*)malloc(sizeof(bmcv_perspective_matrix) * 1);
    unsigned char* src_data = new unsigned char[image_h * image_w * 3];
    unsigned char* res_data = new unsigned char[dst_h * dst_w * 3];
    const char *filename_src = "path/to/src";
    const char *filename_dst = "path/to/dst";

    matrix_image.matrix = matrix_data;
    matrix_image.matrix->m[0] = 0.529813;
    matrix_image.matrix->m[1] = -0.806194;
    matrix_image.matrix->m[2] = 1000.000;
    matrix_image.matrix->m[3] = 0.193966;
    matrix_image.matrix->m[4] = -0.019157;
    matrix_image.matrix->m[5] = 300.000;
    matrix_image.matrix->m[6] = 0.000180;
    matrix_image.matrix->m[7] = -0.000686;
    matrix_image.matrix->m[8] = 1.000000;

    bm_dev_request(&handle, 0);
    readBin(filename_src, src_data, image_h * image_w * 3);
    bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_create(handle, dst_h, dst_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &dst);
    bm_image_copy_host_to_device(src, (void **)&src_data);
    bmcv_image_warp_perspective(handle, 1, &matrix_image, &src, &dst, use_bilinear);
    bm_image_copy_device_to_host(dst, (void**)&res_data);
    writeBin(filename_dst, res_data, dst_h * dst_w * 3);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    free(matrix_data);
    return 0;
}
```

# bmcv_image_watermark_superpose

该接口用于在图像上叠加一个或多个水印。该接口可搭配bmcv_gen_text_watermark接口实现绘制中英文的功能，参照代码示例2。

**处理器型号支持：**  
该接口仅支持BM1684X。

## 接口形式一

```c
bm_status_t bmcv_image_watermark_superpose(
            bm_handle_t handle,
            bm_image* image,
            bm_device_mem_t* bitmap_mem,
            int bitmap_num,
            int bitmap_type,
            int pitch,
            bmcv_rect_t* rects,
            bmcv_color_t color);
```

此接口可实现在不同的输入图的指定位置，叠加不同的水印。

## 接口形式二

```c
bm_status_t bmcv_image_watermark_repeat_superpose(
            bm_handle_t handle,
            bm_image image,
            bm_device_mem_t bitmap_mem,
            int bitmap_num,
            int bitmap_type,
            int pitch,
            bmcv_rect_t* rects,
            bmcv_color_t color);
```

此接口为接口一的简化版本，可在一张图中的不同位置重复叠加一种水印。

## 传入参数说明

* **bm_handle_t handle**  
  输入参数。设备环境句柄，通过调用bm_dev_request获取。

* **bm_image\* image**  
  输入参数。需要打水印的bm_image对象指针。

* **bm_device_mem_t\* bitmap_mem**  
  输入参数。水印的bm_device_mem_t对象指针。

* **int bitmap_num**  
  输入参数。水印数量，指rects指针中所包含的bmcv_rect_t对象个数、也是image指针中所包含的bm_image对象个数、也是bitmap_mem指针中所包含的bm_device_mem_t对象个数。

* **int bitmap_type**  
  输入参数。水印类型,值0表示水印为8bit数据类型(有透明度信息),值1表示水印为1bit数据类型(无透明度信息)。

* **int pitch**  
  输入参数。水印文件每行的byte数,可理解为水印的宽。

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

* **start_x** 描述了水印在原图中所在的起始横坐标。自左而右从0开始，取值范围[0, width)。
* **start_y** 描述了水印在原图中所在的起始纵坐标。自上而下从0开始，取值范围[0, height)。
* **crop_w** 描述的水印的宽度。
* **crop_h** 描述的水印的高度。
* **r** 颜色的r分量。
* **g** 颜色的g分量。
* **b** 颜色的b分量。

## 注意事项

1. bm1684x要求如下：

- 输入和输出的数据类型必须为：

| num | data_type           |
|-----|---------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

- 输入的色彩格式可支持：

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

# bmcv_image_watermark_superpose

该接口用于在图像上叠加一个或多个水印。

**处理器型号支持：**

该接口仅支持BM1684X。

## 接口形式一

```c
bm_status_t bmcv_image_watermark_superpose(
    bm_handle_t handle,
    bm_image * image,
    bm_device_mem_t * bitmap_mem,
    int bitmap_num,
    int bitmap_type,
    int pitch,
    bmcv_rect_t * rects,
    bmcv_color_t color)
```

此接口可实现在不同的输入图的指定位置，叠加不同的水印。

## 接口形式二

```c
bm_status_t bmcv_image_watermark_repeat_superpose(
    bm_handle_t handle,
    bm_image image,
    bm_device_mem_t bitmap_mem,
    int bitmap_num,
    int bitmap_type,
    int pitch,
    bmcv_rect_t * rects,
    bmcv_color_t color)
```

此接口为接口一的简化版本，可在一张图中的不同位置重复叠加一种水印。

## 传入参数说明

* `bm_handle_t handle` - 输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* `bm_image* image` - 输入参数。需要打水印的 bm_image 对象指针。

* `bm_device_mem_t* bitmap_mem` - 输入参数。水印的 bm_device_mem_t 对象指针。

* `int bitmap_num` - 输入参数。水印数量，指 rects 指针中所包含的 bmcv_rect_t 对象个数、也是 image 指针中所包含的 bm_image 对象个数、也是 bitmap_mem 指针中所包含的 bm_device_mem_t 对象个数。

* `int bitmap_type` - 输入参数。水印类型, 值0表示水印为8bit数据类型(有透明度信息), 值1表示水印为1bit数据类型(无透明度信息)。

* `int pitch` - 输入参数。水印文件每行的byte数, 可理解为水印的宽。

* `bmcv_rect_t* rects` - 输入参数。水印位置指针，包含每个水印起始点和宽高。

* `bmcv_color_t color` - 输入参数。水印的颜色。

## 返回值说明

* `BM_SUCCESS`: 成功
* 其他: 失败

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

* `start_x` - 描述了水印在原图中所在的起始横坐标。自左而右从 0 开始，取值范围 [0, width)
* `start_y` - 描述了水印在原图中所在的起始纵坐标。自上而下从 0 开始，取值范围 [0, height)
* `crop_w` - 描述的水印的宽度
* `crop_h` - 描述的水印的高度
* `r` - 颜色的r分量
* `g` - 颜色的g分量
* `b` - 颜色的b分量

## 注意事项

1. bm1684x要求如下：

- 输入和输出的数据类型必须为：

| num | data_type             |
|-----|-----------------------|
| 1   | DATA_TYPE_EXT_1N_BYTE |

- 输入的色彩格式可支持：

| num | image_format          |
|-----|-----------------------|
| 1   | FORMAT_YUV420P        |
| 2   | FORMAT_YUV444P        |
| 3   | FORMAT_NV12           |
| 4   | FORMAT_NV21           |
| 5   | FORMAT_RGB_PLANAR     |
| 6   | FORMAT_BGR_PLANAR     |
| 7   | FORMAT_RGB_PACKED     |
| 8   | FORMAT_BGR_PACKED     |
| 9   | FORMAT_RGBP_SEPARATE  |
| 10  | FORMAT_BGRP_SEPARATE  |
| 11  | FORMAT_GRAY           |

2. 输入输出所有 bm_image 结构必须提前创建，否则返回失败。

3. 水印数量最多可设置512个。

4. 如果水印区域超出原图宽高，会返回失败。

## 代码示例1

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include <sstream>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    
    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };
    
    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle = NULL;
    int src_w, src_h, water_h, water_w, font_mode, water_byte;
    bmcv_color_t color;
    bm_image src;
    int dev_id = 0;
    bm_device_mem_t water;
    unsigned char* water_data;
    int font_num;
    bmcv_rect_t* rect;
    const char *filename_src = "path/to/src";
    const char *filename_water = "path/to/water_file";
    const char *filename_dst = "path/to/dst";
    
    src_w = 800;
    src_h = 800;
    font_mode = 0;
    water_byte = 1024;
    water_w = 32;
    water_h = 32;
    dev_id = 0;
    color.r = 128;
    color.g = 128;
    color.b = 128;
    water_data = new unsigned char [water_byte];
    bm_dev_request(&handle, dev_id);
    font_num = 2;
    rect = new bmcv_rect_t [font_num];
    
    unsigned char* input_data = (unsigned char*)malloc(src_h * src_w);
    unsigned char* in_ptr[3] = {input_data, input_data + src_h * src_w, input_data + 2 * src_h * src_w};
    
    for(int font_idx = 0; font_idx < font_num; font_idx++) {
        rect[font_idx].start_x = font_idx * water_w;
        rect[font_idx].start_y = font_idx * water_h;
        rect[font_idx].crop_w = water_w;
        rect[font_idx].crop_h = water_h;
    }
    readBin(filename_src, input_data, src_h * src_w);
    readBin(filename_water, water_data, water_byte);
    
    bm_malloc_device_byte(handle, &water, water_byte);
    bm_memcpy_s2d(handle, water, (void*)water_data);
    bm_image_create(handle, src_h, src_w, FORMAT_GRAY, DATA_TYPE_EXT_1N_BYTE, &src, NULL);
    bm_image_alloc_dev_mem(src);
    bm_image_copy_host_to_device(src, (void**)in_ptr);
    bmcv_image_watermark_repeat_superpose(handle, src, water, font_num, font_mode, water_w, rect, color);
    bm_image_copy_device_to_host(src, (void **)in_ptr);
    writeBin(filename_dst, input_data, src_h * src_w);
    
    bm_image_destroy(src);
    bm_free_device(handle, water);
    bm_dev_free(handle);
    delete [] rect;
    delete [] water_data;
    free(input_data);
    return 0;
}
```

## 代码示例2

```c
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdbool.h>
#include <stdlib.h>
#include <iostream>
#include <cstring>
#include <wchar.h>
#include <locale.h>
#include <bmcv_api_ext.h>

#define BITMAP_1BIT 1
#define BITMAP_8BIT 0

int main(int argc, char* args[]){
    
    setlocale(LC_ALL, "");
    bm_status_t ret = BM_SUCCESS;
    wchar_t hexcode[256];
    unsigned char r = 255, g = 255, b = 0, fontScale = 2;
    std::string output_path = "out.bmp";
    if ((argc == 1) ||
        (argc == 2 && atoi(args[1]) == -1)) {
        printf("usage: %d\n", argc);
        printf("%s text_string r g b fontscale out_name\n", args[0]);
        printf("example:\n");
        printf("%s bitmain.go\n", args[0]);
        printf("%s bitmain.go 255 255 255 2 out.bmp\n", args[0]);
        return 0;
    }
    mbstowcs(hexcode, args[1], sizeof(hexcode) / sizeof(wchar_t)); //usigned
    printf("Received wide character string: %ls\n", hexcode);
    if (argc > 2) r = atoi(args[2]);
    if (argc > 3) g = atoi(args[3]);
    if (argc > 4) b = atoi(args[4]);
    if (argc > 5) fontScale = atoi(args[5]);
    if (argc > 6) output_path = args[6];
    printf("output path: %s\n", output_path.c_str());
    
    bm_image image;
    bm_handle_t handle = NULL;
    bm_dev_request(&handle, 0);
    bm_image_create(handle, 1080, 1920, FORMAT_YUV420P, DATA_TYPE_EXT_1N_BYTE, &image, NULL);
    bm_image_alloc_dev_mem(image, BMCV_HEAP1_ID);
    bm_read_bin(image,"path/to/src");
    bmcv_point_t org;
    org.x = 10;
    org.y = 10;
    bmcv_color_t color;
    color.r = r;
    color.g = g;
    color.b = b;
    
    bm_image watermark;
    bm_device_mem_t watermark_mem;
    bmcv_rect_t rect;
    int stride;
    ret = bmcv_gen_text_watermark(handle, hexcode, color, fontScale, FORMAT_GRAY, &watermark);
    if (ret != BM_SUCCESS) {
        printf("bmcv_gen_text_watermark fail\n");
        goto fail1;
    }
    
    rect.start_x = org.x;
    rect.start_y = org.y;
    rect.crop_w = watermark.width;
    rect.crop_h = watermark.height;
    
    bm_image_get_stride(watermark, &stride);
    bm_image_get_device_mem(watermark, &watermark_mem);
    ret = bmcv_image_watermark_superpose(handle, &image, &watermark_mem, 1, BITMAP_8BIT,
        stride, &rect, color);
    if (ret != BM_SUCCESS) {
        printf("bmcv_image_overlay fail\n");
        goto fail2;
    }
    bm_image_write_to_bmp(image, output_path.c_str());
    
fail2:
    bm_image_destroy(watermark);
fail1:
    bm_image_destroy(image);
    bm_dev_free(handle);
    return ret;
}
```

# bmcv_width_align

将内存区域的数据按照指定的宽的布局转换并存储到目标内存区域

## 处理器型号支持

该接口支持BM1684X/BM1688/BM1690。

## 接口形式

```c
bm_status_t bmcv_width_align(
            bm_handle_t handle,
            bm_image    input,
            bm_image    output)
```

## 参数说明

- **bm_handle_t handle**  
  输入参数。bm_handle 句柄。

- **bm_image input**  
  输入参数。输入图像的 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以使用 bm_image_alloc_dev_mem 或者 bm_image_copy_host_to_device 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

- **bm_image output**  
  输出参数。输出 bm_image，bm_image 需要外部调用 bmcv_image_create 创建。image 内存可以通过 bm_image_alloc_dev_mem 来开辟新的内存，或者使用 bmcv_image_attach 来 attach 已有的内存。

## 返回值说明

- **BM_SUCCESS**: 成功
- **其他**: 失败

## 格式支持

该接口目前支持以下 image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1 | FORMAT_BGR_PACKED | FORMAT_BGR_PACKED |
| 2 | FORMAT_BGR_PLANAR | FORMAT_BGR_PLANAR |
| 3 | FORMAT_RGB_PACKED | FORMAT_RGB_PACKED |
| 4 | FORMAT_RGB_PLANAR | FORMAT_RGB_PLANAR |
| 5 | FORMAT_RGBP_SEPARATE | FORMAT_RGBP_SEPARATE |
| 6 | FORMAT_BGRP_SEPARATE | FORMAT_BGRP_SEPARATE |
| 7 | FORMAT_GRAY | FORMAT_GRAY |
| 8 | FORMAT_YUV420P | FORMAT_YUV420P |
| 9 | FORMAT_YUV422P | FORMAT_YUV422P |
| 10 | FORMAT_YUV444P | FORMAT_YUV444P |
| 11 | FORMAT_NV12 | FORMAT_NV12 |
| 12 | FORMAT_NV21 | FORMAT_NV21 |
| 13 | FORMAT_NV16 | FORMAT_NV16 |
| 14 | FORMAT_NV61 | FORMAT_NV61 |
| 15 | FORMAT_NV24 | FORMAT_NV24 |

目前支持以下 data_type:

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |
| 2 | DATA_TYPE_EXT_FLOAT32 |
| 3 | DATA_TYPE_EXT_FP16 |

## 注意事项

1. 在调用该接口之前必须确保输入的 image 内存已经申请。
2. input output 的image_format以及data_type必须相同。

## 代码示例

```c
#include <iostream>
#include <memory>
#ifdef __linux__
#include <sys/time.h>
#endif

#include "bmcv_api_ext.h"
#include "test_misc.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"

#include <assert.h>
#include <vector>

#define DEBUG_FILE (0)

#define MODE (STORAGE_MODE_1N_INT8)

using namespace std;

static bm_handle_t handle;

static int
bmcv_width_align_cmp(unsigned char *p_exp, unsigned char *p_got, int count) {
    int ret = 0;
    for (int j = 0; j < count; j++) {
        if (p_exp[j] != p_got[j]) {
            printf("error: when idx=%d,  exp=%d but got=%d\n",
                j,
                (int)p_exp[j],
                (int)p_got[j]);
            return -1;
        }
    }

    return ret;
}
static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");
    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void write_bin(const char *output_path, unsigned char *output_data, int size)
{
    FILE *fp_dst = fopen(output_path, "wb");

    if (fp_dst == NULL) {
        printf("unable to open output file %s\n", output_path);
        return;
    }

    if(fwrite(output_data, sizeof(unsigned char), size, fp_dst) != 0) {
        printf("write image success\n");
    }
    fclose(fp_dst);
}

int main() {
    int         dev_id = 0;
    bm_status_t ret    = bm_dev_request(&handle, dev_id);
    bm_image src_img;
    bm_image dst_img;

    int image_h = 1080;
    int image_w = 1920;

    int                      default_stride[3] = {0};
    int                      src_stride[3]     = {0};
    int                      dst_stride[3]     = {0};
    bm_image_format_ext      image_format      = FORMAT_BGR_PLANAR;
    bm_image_data_format_ext data_type         = DATA_TYPE_EXT_1N_BYTE;
    int                      raw_size          = 0;

    image_format      = FORMAT_GRAY;
    default_stride[0] = image_w;
    src_stride[0]     = image_w + rand() % 16;
    dst_stride[0]     = image_w + rand() % 16;

    raw_size = image_h * image_w;
    unsigned char* raw_image = (unsigned char*)malloc(image_w * image_h * sizeof(unsigned char));
    unsigned char* dst_data = (unsigned char*)malloc(image_w * image_h * sizeof(unsigned char));
    unsigned char* src_image = (unsigned char*)malloc(src_stride[0] * image_h * sizeof(unsigned char));
    unsigned char* dst_image = (unsigned char*)malloc(dst_stride[0] * image_h * sizeof(unsigned char));

    const char* input_path = "path/to/input";
    const char* output_path = "path/to/output";
    readBin(input_path, raw_image, raw_size);

    // calculate use reference for compare.
    unsigned char *src_s_offset;
    unsigned char *src_d_offset;
    for (int i = 0; i < image_h; i++) {
        src_s_offset = raw_image + i * default_stride[0];
        src_d_offset = src_image + i * src_stride[0];
        memcpy(src_d_offset, src_s_offset, image_w);
    }

    // create source image.
    bm_image_create(handle, image_h, image_w,image_format, data_type, &src_img, src_stride);
    bm_image_create(handle, image_h, image_w, image_format, data_type, &dst_img, dst_stride);

    int size[3] = {0};
    bm_image_get_byte_size(src_img, size);
    u8 *host_ptr_src[] = {src_image,
                            src_image + size[0],
                            src_image + size[0] + size[1]};
    bm_image_get_byte_size(dst_img, size);
    u8 *host_ptr_dst[] = {dst_image,
                            dst_image + size[0],
                            dst_image + size[0] + size[1]};

    ret = bm_image_copy_host_to_device(src_img, (void **)(host_ptr_src));
    if (ret != BM_SUCCESS) {
        printf("test data prepare failed");
        return ret;
    }

    ret = bmcv_width_align(handle, src_img, dst_img);
    if (ret != BM_SUCCESS) {
        printf("bmcv width align failed");
        return ret;
    }

    ret = bm_image_copy_device_to_host(dst_img, (void **)(host_ptr_dst));
    if (ret != BM_SUCCESS) {
        printf("test data copy_back failed");
        return ret;
    }
    bm_image_destroy(src_img);
    bm_image_destroy(dst_img);

    unsigned char *dst_s_offset;
    unsigned char *dst_d_offset;
    for (int i = 0; i < image_h; i++) {
        dst_s_offset = dst_image + i * dst_stride[0];
        dst_d_offset = dst_data + i * default_stride[0];
        memcpy(dst_d_offset, dst_s_offset, image_w);
    }
    write_bin(output_path, dst_data, raw_size);
    // compare.

    int cmp_res =
        bmcv_width_align_cmp(raw_image, dst_data, raw_size);
    if (cmp_res != 0) {
        printf("cv_width_align comparing failed\n");
        ret = BM_ERR_FAILURE;
        return ret;
    }
    std::cout << "------[TEST WIDTH ALIGN] ALL TEST PASSED!" << std::endl;
    free(raw_image);
    free(dst_data);
    free(src_image);
    free(dst_image);
    return 0;
}
```

# bmcv_nms_yolo

该接口目前支持yolov3/yolov7，用于消除网络计算得到过多的物体框，并找到最佳物体框。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_nms_yolo(
            bm_handle_t handle,
            int input_num,
            bm_device_mem_t bottom[3],
            int batch_num,
            int hw_shape[3][2],
            int num_classes,
            int num_boxes,
            int mask_group_size,
            float nms_threshold,
            float confidence_threshold,
            int keep_top_k,
            float bias[18],
            float anchor_scale[3],
            float mask[9],
            bm_device_mem_t output,
            int yolo_flag,
            int len_per_batch,
            void *ext);
```

**参数说明:**

* bm_handle_t handle
  输入参数。bm_handle 句柄。

* int input_num
  输入参数。输入feature map数量。

* bm_device_mem_t bottom[3]
  输入参数。bottom的设备地址，需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int batch_num
  输入参数。batch 的数量。

* int hw_shape[3][2]
  输入参数。输入feature map的h、w。

* int num_classes
  输入参数。图片的类别数量。

* int num_boxes
  输入参数。每个网格包含多少个不同尺度的anchor box。

* int mask_group_size
  输入参数。掩膜的尺寸。

* float nms_threshold
  输入参数。过滤物体框的阈值，分数小于该阈值的物体框将会被过滤掉。

* int confidence_threshold
  输入参数。置信度。

* int keep_top_k
  输入参数。保存前 k 个数。

* int bias[18]
  输入参数。偏置。

* float anchor_scale[3]
  输入参数。anchor的尺寸。

* float mask[9]
  输入参数。掩膜。

* bm_device_mem_t output
  输入参数。输出的设备地址，需要调用 bm_mem_from_system()将数据地址转化成转化为 bm_device_mem_t 所对应的结构。

* int yolo_flag
  输入参数。yolov3时yolo_flag=0，yolov7时yolo_flag=2。

* int len_per_batch
  输入参数。该参数无效，仅为了维持接口的兼容性。

* int scale
  输入参数。目标尺寸。该参数仅在yolov7中生效。

* int \*orig_image_shape
  输入参数。原始图片的w/h, 按batch排布，比如batch4: w1 h1 w2 h2 w3 h3 w4 h4。该参数仅在yolov7中生效。

* int model_h
  输入参数。模型的shape h，该参数仅在yolov7中生效。

* int model_w
  输入参数。模型的shape w，该参数仅在yolov7中生效。

* void \*ext
  预留参数。如果需要新增参数，可以在这里新增。yolov7 中新增了4个参数为：

```c
typedef struct yolov7_info{
    int scale;
    int *orig_image_shape;
    int model_h;
    int model_w;
} yolov7_info_t;
```

上面结构体中，int scale：scale_flag。int* orig_image_shape：原始图片的w/h, 按batch排布，比如batch4: w1 h1 w2 h2 w3 h3 w4 h4。int model_h：模型的shape h。int model_w：模型的shape w。这些参数仅在yolov7中生效。

**返回值:**

* BM_SUCCESS: 成功
* 其他: 失败

**代码示例:**

```c
#include <time.h>
#include <random>
#include <algorithm>
#include <map>
#include <vector>
#include <iostream>
#include <cmath>
#include <getopt.h>
#include "bmcv_api_ext.h"
#include "bmcv_common_bm1684.h"
#include "math.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <iostream>
#include <new>
#include <fstream>

typedef struct yolov7_info{
    int scale;
    int *orig_image_shape;
    int model_h;
    int model_w;
} yolov7_info_t;

int main()
{
    int DEV_ID = 0;
    int H = 16, W = 30;
    int bottom_num = 3;
    int dev_count;
    int f_tpu_forward = 1;
    int batch_num = 32;
    int num_classes = 6;
    int num_boxes = 3;
    int yolo_flag = 0; //yolov3: 0, yolov7: 2
    int len_per_batch = 0;
    int keep_top_k = 100;
    float nms_threshold = 0.1;
    float conf_threshold = 0.98f;
    int mask_group_size = 3;
    float bias[18] = {10, 13, 16, 30, 33, 23, 30, 61, 62, 45, 59, 119, 116, 90, 156, 198, 373, 326};
    float anchor_scale[3] = {32, 16, 8};
    float mask[9] = {6, 7, 8, 3, 4, 5, 0, 1, 2};
    int scale = 0; //for yolov7 post handle
    int model_h = 0;
    int model_w = 0;
    int mode_value_end = 0;
    int hw_shape[3][2] = {{H * 1, W * 1},
                        {H * 2, W * 2},
                        {H * 4, W * 4},};
    int size_bottom[3];
    float* data_bottom[3];
    int origin_image_shape[batch_num * 2] = {0};
    float* output_bmdnn;
    float* output_native;
    bm_handle_t handle;
    int output_size = 1;

    bm_dev_request(&handle, 0);
    if (yolo_flag == 1) {
        num_boxes = 1;
        len_per_batch = 12096 * 18;
        bottom_num = 1;
    } else if (yolo_flag == 2) {
        //yolov7 post handle;
        num_boxes = 1;
        bottom_num = 3;
        mask_group_size = 1;
        scale = 1;
        model_h = 512;
        model_w = 960;
        for (int i = 0 ; i < 3; i++) {
            mask[i] = i;
        }
        for (int i = 0; i < 6; i++) {
            bias[i] = 1;
        }
        for (int i = 0; i < 3; i++) {
            anchor_scale[i] = 1;
        }
        for (int i = 0; i < batch_num; i++) {
            origin_image_shape[i * 2 + 0] = 1920;
            origin_image_shape[i * 2 + 1] = 1080;
        }
    }
    // alloc input data
    for (int i = 0; i < 3; ++i) {
        if (yolo_flag == 1){
            size_bottom[i] = batch_num * len_per_batch;
        } else {
            size_bottom[i] = batch_num * num_boxes * (num_classes + 5) * hw_shape[i][0] * hw_shape[i][1];
        }
        data_bottom[i] = new float[size_bottom[i]];
    }
    // alloc and init input data
    for (int j = 0; j < size_bottom[0]; ++j) {
        data_bottom[0][j] = (rand() % 1000 - 999.0f) / (124.0f);
    }
    for (int j = 0; j < size_bottom[1]; ++j) {
        data_bottom[1][j] = (rand() % 1000 - 999.0f) / (124.0f);
    }
    for (int j = 0; j < size_bottom[2]; ++j) {
        data_bottom[2][j] = (rand() % 1000 - 999.0f) / (124.0f);
    }

    output_bmdnn = new float[output_size];
    memset(output_bmdnn, 0, output_size * sizeof(float));

    bm_dev_request(&handle, 0);
    bm_device_mem_t bottom[3] = {
                                bm_mem_from_system((void*)data_bottom[0]),
                                bm_mem_from_system((void*)data_bottom[1]),
                                bm_mem_from_system((void*)data_bottom[2])};
    yolov7_info_t *ext = (yolov7_info_t*)malloc (sizeof(yolov7_info_t));
    ext->scale = scale;
    ext->orig_image_shape = origin_image_shape;
    ext->model_h = model_h;
    ext->model_w = model_w;

    bmcv_nms_yolo(handle, bottom_num, bottom, batch_num, hw_shape, num_classes, num_boxes, mask_group_size,
                nms_threshold, conf_threshold, keep_top_k, bias, anchor_scale, mask,
                bm_mem_from_system((void*)output_bmdnn), yolo_flag,
                len_per_batch, (void*)ext);

    bm_dev_free(handle);
    free(ext);
    delete[] data_bottom[0];
    delete[] data_bottom[1];
    delete[] data_bottom[2];
    delete[] output_bmdnn;
    return 0;
}
```

# bmcv_image_yuv2bgr_ext

该接口实现YUV格式到RGB格式的转换。

**处理器型号支持：**

该接口支持BM1684/BM1684X。

**接口形式:**

```c
bm_status_t bmcv_image_yuv2bgr_ext(
            bm_handle_t handle,
            int image_num,
            bm_image* input,
            bm_image* output);
```

**传入参数说明:**

* bm_handle_t handle
  输入参数。设备环境句柄，通过调用 bm_dev_request 获取。

* int image_num
  输入参数。输入/输出 image 数量。

* bm_image* input
  输入参数。输入 bm_image 对象指针。

* bm_image* output
  输出参数。输出 bm_image 对象指针。

**返回值说明:**

* BM_SUCCESS: 成功
* 其他: 失败

**代码示例**

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    bm_handle_t handle;
    int image_n = 1;
    int image_h = 1080;
    int image_w = 1920;
    bm_image src, dst;
    unsigned char* src_data = new unsigned char[image_h * image_w * 3 / 2];
    unsigned char* res_data = new unsigned char[image_h * image_w * 3];
    const char *filename_src = "path/to/src";
    const char *filename_dst = "path/to/dst";

    bm_dev_request(&handle, 0);
    readBin(filename_src, src_data, image_h * image_w * 3 / 2);
    bm_image_create(handle, image_h, image_w, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &src);
    bm_image_create(handle, image_h, image_w, FORMAT_BGR_PLANAR, DATA_TYPE_EXT_1N_BYTE, &dst);
    memset(src_data, 148, image_h * image_w * 3 / 2);
    bm_image_copy_host_to_device(src, (void**)&src_data);
    bmcv_image_yuv2bgr_ext(handle, image_n, &src, &dst);
    bm_image_copy_device_to_host(dst, (void**)&res_data);
    writeBin(filename_dst, res_data, image_h * image_w * 3);

    bm_image_destroy(src);
    bm_image_destroy(dst);
    bm_dev_free(handle);
    delete[] src_data;
    delete[] res_data;
    return 0;
}
```

# bmcv_image_yuv2hsv

对YUV图像的指定区域转为HSV格式。

## 处理器型号支持

该接口支持BM1684/BM1684X。

## 接口形式

```c
bm_status_t bmcv_image_yuv2hsv(
            bm_handle_t handle,
            bmcv_rect_t rect,
            bm_image input,
            bm_image output);
```

## 参数说明

* bm_handle_t handle
  输入参数。bm_handle句柄。

* bmcv_rect_t rect
  描述了原图中待转换区域的起始坐标以及大小。具体参数可参见bmcv_image_crop接口中的描述。

* bm_image input
  输入参数。输入图像的bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以使用bm_image_alloc_dev_mem或者bm_image_copy_host_to_device来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。

* bm_image output
  输出参数。输出bm_image，bm_image需要外部调用bmcv_image_create创建。image内存可以通过bm_image_alloc_dev_mem来开辟新的内存，或者使用bmcv_image_attach来attach已有的内存。如果不主动分配将在api内部进行自行分配。

## 返回值说明

* BM_SUCCESS: 成功
* 其他: 失败

## 格式支持

bm1684：该接口目前支持以下image_format:

| num | input image_format | output image_format |
|-----|-------------------|-------------------|
| 1 | FORMAT_YUV420P | FORMAT_HSV_PLANAR |
| 2 | FORMAT_NV12 | FORMAT_HSV_PLANAR |
| 3 | FORMAT_NV21 | FORMAT_HSV_PLANAR |

bm1684x：该接口目前

- 支持以下输入色彩格式:

| num | input image_format |
|-----|-------------------|
| 1 | FORMAT_YUV420P |
| 2 | FORMAT_NV12 |
| 3 | FORMAT_NV21 |

- 支持输出色彩格式:

| num | output image_format |
|-----|-------------------|
| 1 | FORMAT_HSV180_PACKED |
| 2 | FORMAT_HSV256_PACKED |

目前支持以下data_type:

| num | data_type |
|-----|----------|
| 1 | DATA_TYPE_EXT_1N_BYTE |

## 注意事项

1、在调用该接口之前必须确保输入的image内存已经申请。

## 代码示例

```c
#include <iostream>
#include <vector>
#include "bmcv_api_ext.h"
#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <memory>

static void readBin(const char* path, unsigned char* input_data, int size)
{
    FILE *fp_src = fopen(path, "rb");

    if (fread((void *)input_data, 1, size, fp_src) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_src);
}

static void writeBin(const char * path, unsigned char* input_data, int size)
{
    FILE *fp_dst = fopen(path, "wb");
    if (fwrite((void *)input_data, 1, size, fp_dst) < (unsigned int)size) {
        printf("file size is less than %d required bytes\n", size);
    };

    fclose(fp_dst);
}

int main()
{
    int channel = 3;
    int width = 1920;
    int height = 1080;
    int dev_id = 0;
    bm_handle_t handle;
    bm_image input, output;
    bmcv_rect_t rect;
    unsigned char* src_data = (unsigned char*)malloc(channel * width * height / 2);
    unsigned char* res_data = (unsigned char*)malloc(channel * width * height);
    unsigned char* in_ptr[3] = {src_data, src_data + height * width, src_data + 2 * height * width};
    unsigned char* out_ptr[3] = {res_data, res_data + height * width, res_data + 2 * height * width};
    const char *filename_src = "path/to/src";
    const char *filename_dst = "path/to/dst";

    rect.start_x = 0;
    rect.start_y = 0;
    rect.crop_w = width;
    rect.crop_h = height;

    bm_dev_request(&handle, dev_id);
    readBin(filename_src, src_data, channel * width * height / 2);
    bm_image_create(handle, height, width, FORMAT_NV12, DATA_TYPE_EXT_1N_BYTE, &input);
    bm_image_alloc_dev_mem(input);
    bm_image_copy_host_to_device(input, (void**)in_ptr);
    bm_image_create(handle, height, width, FORMAT_HSV180_PACKED, DATA_TYPE_EXT_1N_BYTE, &output);
    bm_image_alloc_dev_mem(output);
    bmcv_image_yuv2hsv(handle, rect, input, output);
    bm_image_copy_device_to_host(output, (void**)out_ptr);
    writeBin(filename_dst, res_data, channel * width * height);

    bm_image_destroy(input);
    bm_image_destroy(output);
    free(src_data);
    free(res_data);
    bm_dev_free(handle);
    return 0;
}
```

# bm_image结构体

bmcv api均是围绕bm_image来进行的，一个bm_image对象对应于一张图片。用户通过bm_image_create来构建bm_image对象，然后供各个bmcv的功能函数使用，使用完需要调用bm_image_destroy销毁。

## bm_image

bm_image结构体定义如下:

```c
struct bm_image {
    int width;
    int height;
    bm_image_format_ext image_format;
    bm_data_format_ext data_type;
    bm_image_private* image_private;
};
```

bm_image结构成员包括图片的宽高（width、height），图片格式image_format，图片数据格式data_type，以及该结构的私有数据。

## bm_image_format_ext image_format

其中image_format有以下枚举类型

```c
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
    FORMAT_BAYER
} bm_image_format_ext;
```

# 各个格式说明

## FORMAT_YUV420P
表示预创建一个 YUV420 格式的图片，有三个 plane

## FORMAT_YUV422P
表示预创建一个 YUV422 格式的图片，有三个 plane

## FORMAT_YUV444P
表示预创建一个 YUV444 格式的图片，有三个 plane

## FORMAT_NV12
表示预创建一个 NV12 格式的图片，有两个 plane

## FORMAT_NV21
表示预创建一个 NV21 格式的图片，有两个 plane

## FORMAT_NV16
表示预创建一个 NV16 格式的图片，有两个 plane

## FORMAT_NV61
表示预创建一个 NV61 格式的图片，有两个 plane

## FORMAT_RGB_PLANAR
表示预创建一个 RGB 格式的图片，RGB 分开排列，有一个 plane

## FORMAT_BGR_PLANAR
表示预创建一个 BGR 格式的图片，BGR 分开排列，有一个 plane

## FORMAT_RGB_PACKED
表示预创建一个 RGB 格式的图片，RGB 交错排列，有一个 plane

## FORMAT_BGR_PACKED
表示预创建一个 BGR 格式的图片，BGR 交错排列，有一个 plane

## FORMAT_RGBP_SEPARATE
表示预创建一个 RGB planar 格式的图片，RGB 分开排列并各占一个 plane，共有 3 个 plane

## FORMAT_BGRP_SEPARATE
表示预创建一个 BGR planar 格式的图片，BGR 分开排列并各占一个 plane，共有 3 个 plane

## FORMAT_GRAY
表示预创建一个灰度图格式的图片，有一个 plane

## FORMAT_COMPRESSED
表示预创建一个 VPU 内部压缩格式的图片，共有四个 plane，分别存放内容如下：
- plane0: Y 压缩表
- plane1: Y 压缩数据
- plane2: CbCr 压缩表
- plane3: CbCr 压缩数据

## FORMAT_HSV_PLANAR
表示预创建一个 HSV planar 格式的图片，H 的范围为 0~180，有三个 plane

## FORMAT_ARGB_PACKED
表示预创建一个 ARGB 格式的图片，该图片仅有一个 plane，并且像素值以 RGBA 顺序交错连续排列，即 RGBARGBA

## FORMAT_ABGR_PACKED
表示预创建一个 ABGR 格式的图片，该图片仅有一个 plane，并且像素值以 BGRA 顺序交错连续排列，即 BGRABGRA

## FORMAT_YUV444_PACKED
表示预创建一个 YUV444 格式的图片，YUV 交错排列，有一个 plane

## FORMAT_YVU444_PACKED
表示预创建一个 YVU444 格式的图片，YVU 交错排列，有一个 plane

## FORMAT_YUV422_YUYV
表示预创建一个 YUV422 格式的图片，YUYV 交错排列，有一个 plane

## FORMAT_YUV422_YVYU
表示预创建一个 YUV422 格式的图片，YVYU 交错排列，有一个 plane

## FORMAT_YUV422_UYVY
表示预创建一个 YUV422 格式的图片，UYVY 交错排列，有一个 plane

## FORMAT_YUV422_VYUY
表示预创建一个 YUV422 格式的图片，VYUY 交错排列，有一个 plane

## FORMAT_RGBYP_PLANAR
表示预创建一个 RGBY planar 格式的图片，有四个 plane

## FORMAT_HSV180_PACKED
表示预创建一个 HSV 格式的图片，H 的范围为 0~180，HSV 交错排列，有一个 plane

## FORMAT_HSV256_PACKED
表示预创建一个 HSV 格式的图片，H 的范围为 0~255，HSV 交错排列，有一个 plane

## FORMAT_BAYER
表示预创建一个 bayer 格式的图片，有一个 plane，像素排列方式是 BGGR，RGGB，GRBG 或者 GBRG，且宽高需要是偶数

# bm_data_format_ext data_type

data_type 有以下枚举类型：

```c
typedef enum bm_image_data_format_ext_{
    DATA_TYPE_EXT_FLOAT32,
    DATA_TYPE_EXT_1N_BYTE,
    DATA_TYPE_EXT_4N_BYTE,
    DATA_TYPE_EXT_1N_BYTE_SIGNED,
    DATA_TYPE_EXT_4N_BYTE_SIGNED,
    DATA_TYPE_EXT_FP16,
    DATA_TYPE_EXT_BF16,
} bm_image_data_format_ext;
```

## 各个格式说明

### DATA_TYPE_EXT_FLOAT32
表示所创建的图片数据格式为单精度浮点数

### DATA_TYPE_EXT_1N_BYTE
表示所创建图片数据格式为普通无符号 1N UINT8

### DATA_TYPE_EXT_4N_BYTE
表示所创建图片数据格式为 4N UINT8，即四张无符号 INT8 图片数据交错排列，一个 bm_image 对象其实含有四张属性相同的图片

### DATA_TYPE_EXT_1N_BYTE_SIGNED
表示所创建图片数据格式为普通有符号 1N INT8

### DATA_TYPE_EXT_4N_BYTE_SIGNED
表示所创建图片数据格式为 4N INT8，即四张有符号 INT8 图片数据交错排列

### DATA_TYPE_EXT_FP16
表示所创建的图片数据格式为半精度浮点数，5bit 表示指数，10bit 表示小数

### DATA_TYPE_EXT_BF16
表示所创建的图片数据格式为 16bit 浮点数，实际是对 FLOAT32 单精度浮点数截断数据，即用 8bit 表示指数，7bit 表示小数

其中，对于 4N 排列方式可参考下图：

如上图所示，将 4 张 1N 格式图像相应通道内第 i 个位置的 4Byte 拼接在一起作为 1 个 32 位的 DWORD，作为 4N 格式图相应通道内第 i 个位置的值，比如说通道 1 内 a1/b1/c1/d1 合成 x1；对于不足 4 张图的情形，在图 x 中仍需保留占位。

4N 仅支持 RGB 相关格式，不支持 YUV 相关格式及 FORMAT_COMPRESSED。

# bm_image_copy_host_to_device

**接口形式:**

```c
bm_status_t bm_image_copy_host_to_device(
    bm_image image,
    void* buffers[]
);
```

该 API 将 host 端数据拷贝到 bm_image 结构对应的 device memory 中。

## 传入参数说明

### bm_image image
输入参数。待填充 device memory 数据的 bm_image 对象。

### void* buffers[]
输入参数。host 端指针，buffers 为指向不同 plane 数据的指针，数量应由创建 bm_image 结构时 image_format 对应的 plane 数所决定。每个 plane 的数据量会由创建 bm_image 时的图片宽高、stride、image_format、data_type 决定。具体的计算方法如下：

```c
switch (res->image_format) {
    case FORMAT_YUV420P: {
        width[0]  = res->width;
        width[1]  = ALIGN(res->width, 2) / 2;
        width[2]  = width[1];
        height[0] = res->height;
        height[1] = ALIGN(res->height, 2) / 2;
        height[2] = height[1];
        break;
    }
    case FORMAT_YUV422P: {
        width[0]  = res->width;
        width[1]  = ALIGN(res->width, 2) / 2;
        width[2]  = width[1];
        height[0] = res->height;
        height[1] = height[0];
        height[2] = height[1];
        break;
    }
    case FORMAT_YUV444P: {
        width[0]  = res->width;
        width[1]  = width[0];
        width[2]  = width[1];
        height[0] = res->height;
        height[1] = height[0];
        height[2] = height[1];
        break;
    }
    case FORMAT_NV12:
    case FORMAT_NV21: {
        width[0]  = res->width;
        width[1]  = ALIGN(res->width, 2);
        height[0] = res->height;
        height[1] = ALIGN(res->height, 2) / 2;
        break;
    }
    case FORMAT_NV16:
    case FORMAT_NV61: {
        width[0]  = res->width;
        width[1]  = ALIGN(res->width, 2);
        height[0] = res->height;
        height[1] = res->height;
        break;
    }
    case FORMAT_GRAY: {
        width[0]  = res->width;
        height[0] = res->height;
        break;
    }
    case FORMAT_COMPRESSED: {
        width[0]  = res->width;
        height[0] = res->height;
        break;
    }
    case FORMAT_BGR_PACKED:
    case FORMAT_RGB_PACKED: {
        width[0]  = res->width * 3;
        height[0] = res->height;
        break;
    }
    case FORMAT_BGR_PLANAR:
    case FORMAT_RGB_PLANAR: {
        width[0]  = res->width;
        height[0] = res->height * 3;
        break;
    }
    case FORMAT_RGBP_SEPARATE:
    case FORMAT_BGRP_SEPARATE: {
        width[0]  = res->width;
        width[1]  = width[0];
        width[2]  = width[1];
        height[0] = res->height;
        height[1] = height[0];
        height[2] = height[1];
        break;
    }
}
```

因此，对应的 host 端指针所指向的每个 plane 的 buffers 所对应的数据量和上述代码中各个类型的通道数一致，比如 FORMAT_BGR_PLANAR 只需要 1 个 buffer 的首地址即可，而 FORMAT_RGBP_SEPARATE 则需要 3 个。

## 返回值说明
该函数成功调用时，返回 BM_SUCCESS。

**注意：**

1. 如果 bm_image 未由 bm_image_create 创建，则返回失败。
2. 如果所传入的 bm_image 对象还没有与 device memory 相关联的话，会自动为每个 plane 申请对应 image_private->plane_byte_size 大小的 device memory，并将 host 端数据拷贝到申请的 device memory 中。如果申请 device memory 失败，则该 API 调用失败。
3. 如果所传入的 bm_image 对象图片格式为 FORMAT_COMPRESSED 时，直接返回失败，FORMAT_COMPRESSED 不支持由 host 端指针拷贝输入。
4. 如果拷贝失败，则该 API 调用失败。

# bm_image_create

我们不建议用户直接填充 bm_image 结构，而是通过以下 API 来创建一个 bm_image 结构。

**接口形式:**

```c
bm_status_t bm_image_create(
    bm_handle_t handle,
    int img_h,
    int img_w,
    bm_image_format_ext image_format,
    bm_image_data_format_ext data_type,
    bm_image *image,
    int* stride=nullptr);
```

## 传入参数说明

### bm_handle_t handle
输入参数。设备环境句柄，通过调用 bm_dev_request 获取

### int img_h
输入参数。图片高度

### int img_w
输入参数。图片宽度

### bmcv_image_format_ext image_format
输入参数。所需创建 bm_image 图片格式，所支持图片格式在 bm_image_format_ext 中介绍

### bm_image_format_ext data_type
输入参数。所需创建 bm_image 数据格式，所支持数据格式在 bm_image_data_format_ext 中介绍

### bm_image *image
输出参数。输出填充的 bm_image 结构指针

### int* stride
输入参数。stride 描述了所创建 bm_image 将要关联的 device memory 内存布局。在每个 plane 的 width stride 值，以 byte 计数。在不填写时候默认为和一行的数据宽度相同（以 BYTE 计数）

## 返回值说明
bmcv_image_create 成功调用将返回 BM_SUCCESS，并填充输出的 image 指针结构。这个结构中记录了图片的大小，以及相关格式。但此时并没有与任何 device memory 关联，也没有申请数据对应的 device memory。

## 注意事项

1. 以下图片格式的宽和高可以是奇数，接口内部会调整到偶数再完成相应功能。但建议尽量使用偶数的宽和高，这样可以发挥最大的效率：
   - FORMAT_YUV420P
   - FORMAT_NV12
   - FORMAT_NV21
   - FORMAT_NV16
   - FORMAT_NV61

2. FORMAT_COMPRESSED 图片格式的图片宽度或者 stride 必须 64 对齐，否则返回失败。

3. stride 参数默认值为 NULL，此时默认各个 plane 的数据是 compact 排列，没有 stride。

4. 如果 stride 非 NULL，则会检测 stride 中的 width stride 值是否合法。所谓的合法，即 image_format 对应的所有 plane 的 stride 大于默认 stride。默认 stride 值的计算方法如下：

```c
int data_size = 1;
switch (data_type) {
    case DATA_TYPE_EXT_FLOAT32:
        data_size = 4;
        break;
    case DATA_TYPE_EXT_4N_BYTE:
    case DATA_TYPE_EXT_4N_BYTE_SIGNED:
        data_size = 4;
        break;
    default:
        data_size = 1;
        break;
}
int default_stride[3] = {0};
switch (image_format) {
    case FORMAT_YUV420P: {
        image_private->plane_num = 3;
        default_stride[0] = width * data_size;
        default_stride[1] = (ALIGN(width, 2) >> 1) * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_YUV422P: {
        default_stride[0] = res->width * data_size;
        default_stride[1] = (ALIGN(res->width, 2) >> 1) * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_YUV444P: {
        default_stride[0] = res->width * data_size;
        default_stride[1] = res->width * data_size;
        default_stride[2] = default_stride[1];
        break;
    }
    case FORMAT_NV12:
    case FORMAT_NV21: {
        image_private->plane_num = 2;
        default_stride[0] = width * data_size;
        default_stride[1] = ALIGN(res->width, 2) * data_size;
        break;
    }
    case FORMAT_NV16:
    case FORMAT_NV61: {
        image_private->plane_num = 2;
        default_stride[0] = res->width * data_size;
        default_stride[1] = ALIGN(res->width, 2) * data_size;
        break;
    }
    case FORMAT_GRAY: {
        image_private->plane_num = 1;
        default_stride[0] = res->width * data_size;
        break;
    }
    case FORMAT_COMPRESSED: {
        image_private->plane_num = 4;
        break;
    }
    case FORMAT_BGR_PACKED:
    case FORMAT_RGB_PACKED: {
        image_private->plane_num = 1;
        default_stride[0] = res->width * 3 * data_size;
        break;
    }
    case FORMAT_BGR_PLANAR:
    case FORMAT_RGB_PLANAR: {
        image_private->plane_num = 1;
        default_stride[0] = res->width * data_size;
        break;
    }
    case FORMAT_BGRP_SEPARATE:
    case FORMAT_RGBP_SEPARATE: {
        image_private->plane_num = 3;
        default_stride[0] = res->width * data_size;
        default_stride[1] = res->width * data_size;
        default_stride[2] = res->width * data_size;
        break;
    }
}
```

# BMCV 开发参考手册

## 声明
- 0_disclaimer

## BMCV 介绍
- bmcv

## bm_image 介绍
- bm_image/bm_image
- bm_image/bm_image_create
- bm_image/bm_image_destroy
- bm_image/bm_image_copy_host_to_device
- bm_image/bm_image_copy_device_to_host
- bm_image/bm_image_attach
- bm_image/bm_image_detach
- bm_image/bm_image_alloc_dev_mem
- bm_image/bm_image_alloc_dev_mem_heap_mask
- bm_image/bm_image_get_byte_size
- bm_image/bm_image_get_device_mem
- bm_image/bm_image_alloc_contiguous_mem
- bm_image/bm_image_alloc_contiguous_mem_heap_mask
- bm_image/bm_image_free_contiguous_mem
- bm_image/bm_image_attach_contiguous_mem
- bm_image/bm_image_dettach_contiguous_mem
- bm_image/bm_image_get_contiguous_device_mem
- bm_image/bm_image_get_format_info
- bm_image/bm_image_get_stride
- bm_image/bm_image_get_plane_num
- bm_image/bm_image_is_attached
- bm_image/bm_image_get_handle
- bm_image/bm_image_write_to_bmp
- bm_image/bmcv_calc_cbcr_addr

## bm_image device memory 管理
- memory

## BMCV API
- api/api_introduct
- api/bmcv_hist_balance
- api/yuv2bgr
- api/warp_affine
- api/warp_perspective
- api/watermark_superpose
- api/crop
- api/resize
- api/convert_to
- api/csc_convert_to
- api/storage_convert
- api/vpp_basic
- api/vpp_convert
- api/vpp_convert_padding
- api/vpp_stitch
- api/vpp_csc_matrix_convert
- api/jpeg_encode
- api/jpeg_decode
- api/copy_to
- api/draw_lines
- api/draw_point
- api/draw_rectangle
- api/put_text
- api/fill_rectangle
- api/absdiff
- api/bitwise_and
- api/bitwise_or
- api/bitwise_xor
- api/add_weighted
- api/threshold
- api/dct
- api/sobel
- api/canny
- api/yuv2hsv
- api/gaussian_blur
- api/median_blur
- api/assigned_area_blur
- api/transpose
- api/morph
- api/mosaic
- api/laplacian
- api/lkpyramid
- api/debug_savedata
- api/sort
- api/base64
- api/feature_match_normalized
- api/feature_match
- api/gemm
- api/gemm_ext
- api/matmul
- api/distance
- api/min_max
- api/fft
- api/stft
- api/calc_hist
- api/nms
- api/nms_ext
- api/yolo_nms
- api/cmulp
- api/faiss_indexflatIP
- api/faiss_indexflatL2
- api/faiss_indexPQ_adc
- api/faiss_indexPQ_encode
- api/faiss_indexPQ_sdc
- api/batch_topk
- api/hm_distance
- api/axpy
- api/pyramid
- api/bayer2rgb
- api/as_strided
- api/quantify
- api/rotate
- api/remap
- api/cos_similarity
- api/matrix_prune
- api/lapmatrix
- api/knn
- api/knn2
- api/knn_match
- api/qr
- api/cluster
- api/cv_overlay

## PCIe CPU
- pcie_cpu

# bmcv_img_scale

此接口用于BM1682对图像进行缩放，并支持从原图中抠图缩放，以及对输出图像进行归一化操作

```c
bm_status_t bmcv_img_scale(
    bm_handle_t handle,
    bmcv_image input,
    int n, int do_crop, int top, int left, int height, int width,
    unsigned char stretch, unsigned char padding_b, unsigned char padding_g, unsigned char padding_r,
    int pixel_weight_bias,
    float weight_b, float bias_b,
    float weight_g, float bias_g,
    float weight_r, float bias_r,
    bmcv_image output
);
```

## 传入参数说明

**bm_handle_t handle**

bmcv初始化获取的handle

**bmcv_image input**

输入图像数据地址，只支持BGR planar或者RGB planar格式数据，支持float或者byte类型数据

**int n**

处理图像的数量，目前只支持1

**int do_crop**

是否进行抠图缩放。0：不抠图，下面四个参数无用。1：抠图，下面四个参数用于确定抠图的尺寸

**int top**

抠图开始点纵坐标，图片左上角为原点，单位为像素

**int left**

抠图开始点横坐标，图片左上角为原点，单位为像素

**int height**

抠图高度，单位为像素

**int width**

抠图宽度，单位为像素

**unsigned char stretch**

scale模式。0：fit模式，等比例缩放，按照下面的padding参数填充颜色；1：拉伸模式，填满目标大小，下面的padding参数无用

**unsigned char padding_b**

fit模式下蓝色填充色值，为0-255之byte类型，如果输出类型为byte或float但未指定归一化计算，则此值为填充颜色分量，如果输出为float类型且需要归一化，则此分量也相应进行归一化计算。

**unsigned char padding_g**

fit模式下绿色填充色值，为0-255之byte类型，如果输出类型为byte或float但未指定归一化计算，则此值为填充颜色分量，如果输出为float类型且需要归一化，则此分量也相应进行归一化计算。

**unsigned char padding_r**

fit模式下红色填充色值，为0-255之byte类型，如果输出类型为byte或float但未指定归一化计算，则此值为填充颜色分量，如果输出为float类型且需要归一化，则此分量也相应进行归一化计算。

**int pixel_weight_bias**

是否对输出图像进行归一化计算。0：不做归一化计算，下面weight和bias参数无用；1：进行归一化计算

**float weight_b**

b通道的系数

**float bias_b**

b通道偏移量

**float weight_g**

g通道的系数

**float bias_g**

g通道的偏移量

**float weight_r**

r通道的系数

**float bias_r**

r通道的偏移量

**bmcv_image ouput**

输出的图像的描述结构，支持BGR planar或者RGB planar格式，但是必须与输入相同。