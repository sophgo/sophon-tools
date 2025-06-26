// ===----------------------------------------------------------------------===
// 
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
// 
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
// 
// ===----------------------------------------------------------------------===

#ifndef BMIMG_LABEL_H_
#define BMIMG_LABEL_H_

#include <iostream>
#include <QApplication>
#include <QWidget>
#include <QLabel>
#include <QPainter>
#include <QRect>
#include <QGridLayout>
#include <QDebug>
#include <vector>
#include <memory>
#include <unordered_map>
#include <mutex>
#include <thread>
#include "bmcv_api.h"
#include "bmcv_api_ext.h"
#include "bmlib_runtime.h"
#include "opencv2/opencv.hpp"

/*
    BmimgLabel类继承了QLabel,具备QLabel的基本显示功能，在此基础拓展了show_bmimg的显示接口，传入bm_image即可显示其中的图片
    传入的bm_image有像素格式要求：FORMAT_RGB_PACKED, DATA_TYPE_EXT_1N_BYTE
*/

class BMLabel : public QLabel{
    Q_OBJECT
public:

    explicit BMLabel(QWidget *parent=nullptr, int dev_id=0,  Qt::WindowFlags f=Qt::WindowFlags()){
        bm_dev_request(&handle,dev_id);
        connect(this, &BMLabel::show_signals,this,&BMLabel::show_pixmap);
    }
    ~BMLabel() override {
        disconnect(this, &BMLabel::show_signals, this, &BMLabel::show_pixmap);
        bm_dev_free(handle);
    }

    void show_img(bm_image* bmimg_ptr);

public slots:

    void show_pixmap();

signals:
    void show_signals();

private:
    QPixmap image_pixmap;
    bm_handle_t handle;
};

#endif 