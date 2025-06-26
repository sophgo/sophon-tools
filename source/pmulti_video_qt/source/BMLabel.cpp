// ===----------------------------------------------------------------------===
// 
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
// 
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
// 
// ===----------------------------------------------------------------------===

#include "BMLabel.h"

#define USE_MMAP (1)

void BMLabel::show_img(bm_image* bmimg_ptr){
    /* 转换为当前label大小 */
    int label_width = this->width();
    int label_height = this->height();
    int stride[3] = {label_width*3,0,0};
    bm_image resize_bmimg;
    bmcv_resize_image resize_attr[4];
    bmcv_resize_t resize_img_attr[1];
    resize_img_attr[0].start_x = 0;
    resize_img_attr[0].start_y = 0;
    resize_img_attr[0].in_width = bmimg_ptr->width;
    resize_img_attr[0].in_height = bmimg_ptr->height;
    resize_img_attr[0].out_width = label_width;
    resize_img_attr[0].out_height = label_height;
    resize_attr[0].resize_img_attr = &resize_img_attr[0];
    resize_attr[0].roi_num = 1;
    resize_attr[0].stretch_fit = 1;
    resize_attr[0].interpolation = BMCV_INTER_NEAREST;
    bm_image_create(handle,label_height,label_width,FORMAT_RGB_PACKED, DATA_TYPE_EXT_1N_BYTE,&resize_bmimg,stride);
    bmcv_image_resize(handle,1,resize_attr,bmimg_ptr,&resize_bmimg);

    /* 采用内存映射将数据传输到sysmem */
    unsigned char* buffer0;
    bm_device_mem_t oimagemem;
    bm_image_get_device_mem(resize_bmimg, &oimagemem);
    bm_mem_mmap_device_mem(handle, &oimagemem, (unsigned long long *)&buffer0);
    bm_mem_flush_device_mem(handle, &oimagemem);

    /* 交给QT绘图 */
    int resize_bmimg_stride = 0;
    bm_image_get_stride(resize_bmimg,&resize_bmimg_stride);
    QImage _image((uchar *)buffer0, label_width, label_height, resize_bmimg_stride, QImage::Format_RGB888);
    image_pixmap = QPixmap::fromImage(_image);
    bm_mem_unmap_device_mem(handle, buffer0, bm_mem_get_device_size(oimagemem));
    bm_image_destroy(resize_bmimg);

    emit BMLabel::show_signals();
}

void BMLabel::show_pixmap(){
    this->setPixmap(image_pixmap);
    this->update(); 
}
