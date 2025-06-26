# sophon-tools

## 简介

本工程用于存放算丰设备当前易用性工具源码，便于发版与使用者二次开发

## 目录结构

* `source` 目录下存放各个工具的源码
* `output` 目录下存放编译的最终结果

## 子项目介绍

| 子项目名称 | 源码路径 | 是否支持一键编译 | 简介 |
| --- | --- | --- | --- |
| [bmsec](./source/pbmsec) | source/pbmsec | 是 | 用于SE6/8高密度服务器的易用性命令行工具 |
| [socbak](./source/psocbak)   | source/psocbak | 是 | 用于BM1684/BM1684X/BM1688/CV186AH芯片刷机包打包 |
| [get_info](./source/pget_info) | source/pget_info | 是 | 用于获取BM1684/BM1684X/BM1688/CV186AH芯片的性能指标 |
| [memory_edit](./source/pmemory_edit) | source/pmemory_edit | 是 | 用于修改BM1684/BM1684X/BM1688/CV186AH的设备内存布局 |
| [qt_memory_edit](./source/pqt_memory_edit) | source/pqt_memory_edit | 否 | 图形化的远程修改设备内存布局的工具 |
| [qt_batch_deployment](./source/pqt_batch_deployment) | source/pqt_batch_deployment | 否 | 基于SSH的批量部署工具 |
| [dfss_cpp](./source/pdfss_cpp) | source/pdfss_cpp | 否 | DFSS工具CPP工程 |
| [spacc_efuse_demo](./source/pspacc_efuse_demo) | source/pspacc_efuse_demo | 否 | efuse+spacc加解密Demo |
| [SophUI](./source/pSophUI) | source/pSophUI | 否 | HDMI配网页面工程 |
| [ota_update](./source/pota_update) | source/pota_update | 是 | OTA远程刷机工具 |
| [memtest](./source/pmemtest) | source/pmemtest | 是 | SoC模式DDR压测工具 |
| [autotelecomm](./source/pautotelecomm) | source/pautotelecomm | 是 | 4G/5G自动拨号工具 |
| [multi_video_qt](./source/pmulti_video_qt) | source/pmulti_video_qt | 否 | QT多路视频解码播放器 |

## 编译方式

1. 支持一键编译的子项目在本目录下执行 `release.sh` 后会将成果输出到 `output` 目录
2. 不支持一键编译的子项目请参考源码目录中的 `readme.md` 自行准备环境编译

## 一键编译的子项目的编译依赖

* 编译主机架构:amd64
* 7z/zip
* dpkg-deb
* pandoc
