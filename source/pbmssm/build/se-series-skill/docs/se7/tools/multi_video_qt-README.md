# QT多路视频解码播放器

## 介绍

本工程是基于QT实现的一个多路视频解码并播放的Demo,支持1-32路同时播放,支持本地MP4文件和RTSP视频流,支持使用BM1684X VPU/VPP硬件加速.运行截图如下.

![运行截图](screenshot.png)

## 编译运行方式

需要准备如下依赖: QT编译工具链,libsophon开发用头文件和库,sophon-mw开发用头文件和库.

工程默认配置为在SE7上编译,采用`公版QT+X11桌面`方案,需要卸载`sophgo-bsp-qt5`包,然后安装`qt5-default`.

如果需要裸QT方案,请参考同仓库的`pSophUI`目录.

编译运行方式如下:

``` bash
mkdir build
cd build
qmake ..
make -j4
./multi_video_qt --config=../config_30.json
```
