---
title: SDK版本说明
description: 用于确定设备SDK版本
---

## 版本号对应关系

SDK包含了libsophon和多媒体组件。每一个SDK大版本号都对应了libsophon版本和多媒体组件版本

我们推荐开发时的SDK大版本号和目标设备runtime的版本号对齐。下面是版本对应关系：

| SDK大版本号 | libsophon版本 | 多媒体组件版本 |
|------------|---------------|----------------|
| V22.09.02  | 0.4.1         | 0.3.1          |
| V22.10.01  | 0.4.2         | 0.4.0          |
| V22.11.01  | 0.4.3         | 0.5.0          |
| V22.12.01  | 0.4.4         | 0.5.1          |
| V23.03.01  | 0.4.6         | 0.6.0          |
| V23.05.01  | 0.4.8         | 0.6.3          |
| V23.07.01  | 0.4.9         | 0.7.0          |
| V23.09 LTS | 0.4.9-LTS     | 0.7.1          |
| V23.09 LTS SP1 | 0.4.9-LTS  | 0.8.0          |
| V23.09 LTS SP2 | 0.4.9-LTS  | 0.8.0          |
| V23.09 LTS SP3 | 0.5.1-LTS  | 0.11.0         |
| V23.09 LTS SP4 | 0.5.1-LTS  | 0.12.0         |
| V23.10.01  | 0.5.0         | 0.7.3          |
| V24.04.01  | 0.5.1         | 0.10.0         |
| V25.03.01  | 0.5.2         | 0.13.0         |
| V23.09 LTS SP5 | 0.5.1-LTS  | 0.14.0         |

## 查询方式

使用`bm_version`命令查询，以下面的查询信息为例：

``` bash
linaro@sophon:~$ bm_version 
SophonSDK version: v23.09 LTS-SP5
sophon-soc-libsophon : 0.5.1
sophon-soc-libsophon-dev : 0.5.1
sophon-mw-soc-sophon-ffmpeg : 0.14.0
sophon-mw-soc-sophon-opencv : 0.14.0
BL2 v2.8(release):6003f3c33 Built : 06:55:32, Nov 25 2025
BL31 v2.8(release):6003f3c33 Built : 06:55:32, Nov 25 2025
U-Boot 2022.10 6003f3c33-dirty (Nov 25 2025 - 07:03:51 +0000) Sophon BM1684X
KernelVersion : Linux sophon 5.4.217-bm1684-g538a73e086dc-dirty #1 SMP Tue Nov 25 06:55:45 UTC 2025 aarch64 aarch64 aarch64 GNU/Linux
HWVersion: 0x00
MCUVersion: 0x05
```

可以获取如下信息：

* SDK大版本号：v23.09 LTS-SP5
* libsophon版本号： 0.5.1
* 多媒体组件版本号： 0.14.0
* 内核哈希： 538a73e086dc-dirty
