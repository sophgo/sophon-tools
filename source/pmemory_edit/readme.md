# 内存布局修改工具

## 文件解析

``` bash

source
└── memory_edit
    ├── bintools
    │   ├── cpio
    │   ├── dtc
    │   ├── dumpimage
    │   ├── file
    │   └── mkimage
    └── memory_edit.sh

```

* `memory_edit.sh` 文件是主要程序内容
* `bintools` 文件中是编辑itb文件所需要的部分二进制程序

## 使用说明

``` bash

root@bm1684:/data/zzt/new_nfs/memory_edit# ./memory_edit.sh
INFO: version: 2.10
Error: Invalid parameters. Please refer to the following example
/data/zzt/new_nfs/memory_edit/memory_edit.sh -p [dts name] # for print infomation
/data/zzt/new_nfs/memory_edit/memory_edit.sh -c -npu 0x80000000 -vpu 0x80000000 -vpp 0x80000000 [dts name] # for config mem, The memory size unit is Byte
/data/zzt/new_nfs/memory_edit/memory_edit.sh -c -npu 2048 -vpu 2048 -vpp 2048 [dts name] # for config mem, The memory size unit is MiB
for bm1688, please use "memory_edit.sh -c -npu 2048 -vpu 0 -vpp 2048"
/data/zzt/new_nfs/memory_edit/memory_edit.sh -d dtbfile # for de_emmcboot.itb
/data/zzt/new_nfs/memory_edit/memory_edit.sh -e dtbfile # for en_emmcboot.itb
/data/zzt/new_nfs/memory_edit/memory_edit.sh --clean # clean this dir

```

### 内存布局修改

0. 获取memory_edit [https://github.com/sophgo/sophon-tools/releases](https://github.com/sophgo/sophon-tools/releases)
1. 通过 `./memory_edit -p` 查看当前配置
2. 通过 `./memory_edit -c -npu xxx -vpu xxx -vpp xxx` 进行内存布局的调整
3. 将新生成的itb文件cp到/boot目录下替换同名文件，然后执行sync并重启
4. 修改完成

### 设备树文件二次修改说明

0. 获取memory_edit [https://github.com/sophgo/sophon-tools/releases](https://github.com/sophgo/sophon-tools/releases)
1. 获取设备树信息：
    1. 如果是84，并且SDK版本低于或等于3.0.0。需要重启根据串口log确定。
        1. 重启获取使用的设备树配置，如通过 `Trying 'fdt-pcb141' fdt subimage` 获取配置为 `fdt-pcb141`
        2. 打开 `/boot/multi.its` 文件，查找该配置对应的设备树名称，如 `bm1684x_se7_v2.0.dtb`
    2. 其余情况使用 `./memory_edit -p` 查看 `use dts file /home/linaro/memory_edit/output/bm1684x_se7_v2.0.dts`
2. 解包启动文件
    1. 将/boot目录下的itb文件和its文件cp到memory_edit下
    2. 使用./memory_edit.sh -d <itb文件名称>解包
    3. 在output目录下按照之前获取的设备树文件名称，修改对应的设备树。
    4. 使用./memory_edit.sh -e <itb文件名称>重新打包，新的itb文件会在output目录下生成
    5. 使用新的itb文件替换/boot目录下旧的itb文件，然后执行sync并重启
3. 修改完成

#### 说明视频

https://github.com/user-attachments/assets/8b484c7f-2018-4049-ab6a-eecbed162f76

[演示视频](videos/memory_edit-video.mp4)

### ramdisk编辑功能说明

在执行`-d`前，使用`export MEMORY_EDIT_RAMDISK=1`配置环境变量，此时会在`output/ramdisk`下生成`ramdisk`中的文件

在执行`-e`前，使用`export MEMORY_EDIT_RAMDISK=1`配置环境变量，此时会将`output/ramdisk`下的文件打包到itb中的ramdisk中




