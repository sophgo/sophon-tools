# 使用libsophon开发

## SOC MODE

### SOC 板卡上编译程序

如果您希望在SOC模式的板子上运行的Linux环境下进行开发，则需要安装sophon-soc-libsophon-dev_0.5.1-LTS_arm64.deb工具包，使用以下命令安装。

```
sudo dpkg -i sophon-soc-libsophon-dev_0.5.1-LTS_arm64.deb
```

安装完成后，您可以参考PCIE MODE的开发方法，使用cmake将libsophon中的库链接到自己的程序中。

### x86 交叉编译程序

如果您希望使用SOPHON SDK搭建交叉编译环境，您需要用到的是gcc-aarch64-linux-gnu工具链以及sophon-img relesae包里的libsophon_soc_0.5.1-LTS_aarch64.tar.gz。首先使用如下命令安装gcc-aarch64-linux-gnu工具链。

```
sudo apt-get install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

其次解压sophon-img relesae包里的libsophon_soc_0.5.1-LTS_aarch64.tar.gz。

```
1. mkdir -p soc-sdk
2. tar -zxf libsophon_soc_0.5.1-LTS_aarch64.tar.gz
3. cp -rf libsophon_soc_0.5.1_aarch64/opt/sophon/libsophon-0.5.1/lib  soc-sdk
4. cp -rf libsophon_soc_0.5.1_aarch64/opt/sophon/libsophon-0.5.1/include  soc-sdk
```

libsophon包含了bmrt,bmlib和bmcv的库。 opencv 和ffmpeg 相关的库在sophon-mw-soc_0.5.1_aarch64.tar.gz中，
其目录结构与libsophon类似 ，只需要拷贝lib和include下所有内容到soc-sdk即可。
如果需要使用第三方库，可以使用qemu在x86上构建虚拟环境安装，再将头文件和库文件拷贝到soc-sdk目录中，命令如下：

```
构建qemu虚拟环境

sudo apt-get install qemu-user-static
mkdir rootfs
cd rootfs

构建Ubuntu 20.04的rootfs

sudo qemu-debootstrap --arch=arm64 focal .
sudo chroot . qemu-aarch64-static /bin/bash

进入qemu后，安装软件，以gflag为例

apt install software-properties-common
add-apt-repository universe
apt-get update
apt-get install libgflags-dev

通常情况下安装的so会在/usr/lib/aarch64-linux-gnu/libgflag* 下，只需要拷贝到soc-sdk/lib里即可。
```

下面以如下代码为例，介绍在您的代码中如何使用SOPHON SDK制作的soc-sdk交叉编译，以调用libbmlib中的函数：

```
#include <bmlib_runtime.h>
#include <stdio.h>

int main(int argc, char const *argv[])
{
    bm_status_t ret;
    unsigned int card_num = 0;

    ret = bm_get_card_num(&card_num);
    printf("card number: %d/%d\n", ret, card_num);

    return 0;
}
```

首先按照如下步骤创建新的工作目录

```
mkdir -p workspace && pushd workspace
touch CMakeLists.txt
touch get_dev_count.cpp
```

将上面的c++代码导入到get_dev_count.cpp中，在CMakeLists.txt中添加如下段落：

```
cmake_minimum_required(VERSION 2.8)

set(TARGET_NAME "test_bmlib")

project(${TARGET_NAME} C CXX)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_ASM_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

# 该demo链接了bmlib库，所以打开了BM_LIBS
set(BM_LIBS bmlib bmrt)
# 需要链接jpu相关的库可以打开JPU_LIBS
# set(JPU_LIBS bmjpuapi bmjpulite)
# 需要链接opencv相关的库可以打开OPENCV_LIBS
# set(OPENCV_LIBS opencv_imgproc opencv_core opencv_highgui opencv_imgcodecs
        opencv_videoio)
# 引入外部库，可以参看下面导入gflags的方法，打开EXTRA_LIBS
# set(EXTRA_LIBS gflags)

include_directories("${SDK}/include/")

link_directories("${SDK}/lib/")

set(src get_dev_count.cpp)
get_filename_component(target ${src} NAME_WE)
add_executable(${target} ${src})
target_link_libraries(${target} ${BM_LIBS} pthread dl)
# 未使用OPENCV和FFMPEG等库，所以不需要加下面的链接路径
# target_link_libraries(${target} ${BM_LIBS} ${OPENCV_LIBS} ${FFMPEG_LIBS}
                            ${JPU_LIBS} ${EXTRA_LIBS} pthread dl)
```

接着使用cmake来构建程序。

```
mkdir -p build && pushd build
cmake -DSDK=/path_to_sdk/soc-sdk ..
make
```

就可以在x86机器上编译出soc模式上运行的aarch64架构的程序。

上面例子只链接了bmlib的库，其它库如opencv，ffmpeg，其它lib同理。

# 术语解释

| **术语** | **说明** |
|----------|----------|
| BM1684 | 算能面向深度学习领域推出的第三代张量处理器 |
| BM1684X | 算能面向深度学习领域推出的第四代张量处理器 |
| NPU | 神经网络处理单元 |
| SOC模式 | 一种产品形态，SDK运行于A53 AARCH64平台，智能视觉深度学习处理器作为平台总线设备 |
| PCIe模式 | 一种产品形态，SDK运行于X86平台，BM1684、BM1684X存在于PCIe接口的深度学习计算加速卡上 |
| Drivers | Drivers是API接口访问硬件的通道 |
| Gmem | 卡上用于智能视觉深度学习处理器加速的DDR内存 |
| F | FAULT 故障状态 |
| N/A | 此项参数不支持 |

# bm-smi介绍

下表列举了bm-smi可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

| **设备信息** | **PCIe模式** | **SOC模式** |
|-------------|-------------|-------------|
| 显示时间日期 | 支持 | 支持 |
| Lib Version | 支持 | 支持 |
| Driver Version | 支持 | 支持 |
| 物理板卡id号 | 支持 | 支持 |
| 智能视觉深度学习处理器的设备号 | 支持 | 支持 |
| 板卡名称 | 支持 | 支持 |
| 板卡状态 | 支持 | 支持 |
| 板级温度 | 支持 | 不支持 |
| 片上温度 | 支持 | 不支持 |
| 板级功耗 | 支持 | 不支持 |
| 模块功耗 | 支持 | 不支持 |
| 模块电压 | 支持 | 不支持 |
| 供电电流 | 支持 | 不支持 |
| DDR ECC是否使能 | 支持 | 不支持 |
| DDR使能，纠正错误的次数 | 支持 | 不支持 |
| 板卡序列号 | 支持 | 不支持 |
| PCIe模式下domain:b:d.f | 支持 | 不支持 |
| PCIe or SOC mode | 支持 | 支持 |
| 最小工作频率 | 支持 | 支持 |
| 最大工作频率 | 支持 | 支持 |
| 当前工作频率 | 支持 | 支持 |
| 板卡最大功耗 | 支持 | 不支持 |
| 模块的工作电流 | 支持 | 不支持 |
| gmem总数和已使用数量 | 支持 | 支持 |
| 智能视觉深度学习处理器的瞬时利用率 | 支持 | 支持 |
| 风扇转速 | 支持 | 不支持 |
| 每个进程（或者线程）占用的gmem的数量 | 支持 | 不支持 |
| 文本模式 | 支持 | 不支持 |
| 参数 | 支持 | 仅支持file、lms、loop |

bm-smi是一个可执行文件，不依赖其他动态库，位于/opt/sophon/libsophon-current/bin目录下，上图为一个执行bm-smi的示意图。

**注意事项：**

1、因为我们的板卡是支持多任务多用户同时使用的，理论上可以有无限个进程创建无限个handle申请global memory，可以使用上下方向键以及翻页键去查看所有的process占用gmem的信息，通过标记保存成文件，也是包含所有process信息的。

2、process占用的gmem信息，每一行显示的是这个process创建的一个handle对应的gmem，如果这个process创建了多个handle，那么每个handle占用的gmem信息是单独一行显示的。

# 具体使用方法和参数

bm-smi支持的参数有：

- file (target file to save smi log.)
  type: string default: ""
  可以将设备的状态重定向到文本文档中，使用方法如下：
  ```
  bm-smi --dev=0x0 --file=./bm-smi.log
  ```
  该功能SOC模式支持。

- lms (sample interval in loop mode.) type: int32 default: 500

  用来设置运行bm-smi时查询设备状态的时间间隔，默认是500ms查询一次，这个参数的最小值是300ms。该功能SOC模式支持。

- loop (true is for loop mode, false is for only once mode.) type: bool，default: true

  用来设置运行bm-smi时是单次模式还是周期模式，默认周期模式。单次模式下查询一次设备状态后bm-smi就退出了；周期模式下按照lms为周期反复查询设备状态。示例如下：
  ```
  bm-smi --loop
  bm-smi --noloop
  ```
  该功能SOC模式支持。

# bm-smi的help信息

## SOC模式bm-smi的help信息

```
bm-smi --help

bm-smi: command line brew

usage: bm-smi [--opmode=display] [--file=/xx/yy.txt] [--lms=500] [-loop]

opmode:

SOC mode only use display for bm-smi.

file:

the target file to save smi log, default is empty.

lms:

how many ms of the sample interval, default is 500.

loop:

if -loop (default): smi sample device every lms ms.

if -noloop: smi sample device only once.

   No modules matched: use -help
```

SOC模式只支持opmode=display、file、lms和loop参数，其他参数无效。

# bm-smi用于SOC模式

PCIe 模式bm-smi支持上述所有功能，SOC 模式 bm-smi界面显示支持功能如图2所示，N/A表示该功能不支持；参数只支持opmode=display、file、lms和loop。

SOC模式bm-smi使用方法：登录soc后，直接运行bm-smi即可，
```
bm-smi or bm-smi --opmode=display
```

# proc文件系统介绍

proc文件系统接口在/proc节点下创建设备信息节点，用户通过cat或者编程的方式读取相关节点获取设备温度、版本等信息。

bm-smi侧重于以界面的形式直观显示设备信息，proc文件系统接口侧重于为用户提供编程获取设备信息的接口。

下表列举了proc文件系统可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

SOC 模式只有 JPU 和 VPU 支持 proc 文件系统接口，节点分别是 `/proc/jpuinfo` 和 `/proc/vpuinfo`。

## 各项参数的含义

SOC 模式只有 `/proc/jpuinfo` 和 `/proc/vpuinfo`; 

# 智能视觉深度学习处理器驱动sysfs文件系统介绍

sysfs文件系统接口用来获取智能视觉深度学习处理器的利用率等信息。

下表列举了智能视觉深度学习处理器驱动sysfs文件系统可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

| **设备信息** | **PCIe模式** | **SOC模式** |
|--------------|--------------|-------------|
| npu_usage | 支持 | 支持 |
| npu_usage_enable | 支持 | 支持 |
| npu_usage_interval | 支持 | 支持 |

驱动安装后，会为每个设备创建一些属性，用于查看和修改一些参数。这些属性所在的位置：

- PCIe模式：/sys/class/bm-sophon/bm-sophon0/device
- SOC模式：/sys/class/bm-tpu/bm-tpu0/device

## 各项参数的含义

下面逐一介绍每个部分代表的含义。

- npu_usage：智能视觉深度学习处理器在一段时间内（窗口宽度）处于工作状态的百分比。
- npu_usage_enable：是否使能统计npu利用率，默认使能。
- npu_usage_interval：统计npu利用率的时间窗口宽度，单位ms，默认500ms。取值范围[200,2000]。

## 智能视觉深度学习处理器驱动sysfs文件系统接口的具体使用方法

使用例子如下：

更改时间窗口宽度（只能在超级用户下）：

```
root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage_interval
"interval": 600

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# echo 500 > npu_usage_interval

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage_interval
"interval": 500
```

使能关闭对npu利用率的统计：

```
root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage_enable
"enable": 1

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# echo 0 > npu_usage_enable

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage_enable
"enable": 0

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage
Please, set [Usage enable] to 1

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# echo 1 > npu_usage_enable

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage_enable
"enable": 1

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage
"usage": 0, "avusage": 0

root@bitmain:/sys/class/bm-sophon/bm-sophon0/device#
```

查看npu利用率：

```
root@bitmain:/sys/class/bm-sophon/bm-sophon0/device# cat npu_usage
"usage": 0, "avusage": 0
```

Usage表示过去一个时间窗口内的npu利用率。
Avusage表示自安装驱动以来npu的利用率。

## SOC模式各个设备的详细信息

SOC模式只有JPU和VPU支持proc接口，对应的proc节点为/proc/jpuinfo和/proc/vpuinfo。

### jpuinfo

- 读写属性：只读
- JPU loadbalance：记录JPU0-JPU1(1684x),JPU0-JPU3(1684)编码/解码次数，JPU*为内部的JPEG编解码器，取值范围：0~ 2147483647

### vpuinfo

- 读写属性：只读
- id：vpu core的编号，取值范围：0~2(1684x), 0-4(1684)
- link_num：编/解码路数，取值范围：0~32

# Bmlib的基本概念和功能

Bmlib是在内核驱动之上封装的一层底层软件库，完成的主要功能有：

- 设备handle的创建和销毁
- Memory help函数接口
- Global memory的申请和释放
- 数据在host和global memory之间的搬运
- 数据在global memory内部的搬运
- API的发送和同步
- Global memory在host端的映射和一致性管理
- profile接口
- A53的使能和使用
- 杂项管理接口
- Power控制接口

## Handle的概念

我们的神经网络加速设备，无论是在PCIE模式，还是SOC模式，安装完智能视觉深度学习处理器的驱动后，会成为一个标准的字符设备。上层用户进程如果要使用这个设备，需要在这个设备上创建一个handle句柄。

Handle是管理api，申请memory，释放memory的handle，如果一个进程创建了两个handle，名字为handle_A1，handle_A2，这是两个独立的handle。

如果线程B是进程A的子线程，进程A创建handle_A，线程B创建handle_B，那么handle_A和handle_B也是两个独立的handle。

如果一个api是通过handle_A发送的，则必须通过handle_A sync；

如果一块memory是通过handle_A申请的，则必须通过handle_A 释放；

需要注意的是handle的创建者和使用者可以不一样，例如进程A创建了handle_A，A的子线程A1也可以使用handle_A，但是A1通过handle_A申请的memory在统计上算作A申请的。

我们推荐以下四种使用handle的方式：

进程A中创建Handle_A，Handle_A只在进程A中使用；

进程A中创建Handle_A，Handle_A在进程A的两个子线程（可以是多个，图中两个只是举例示意）中使用；

进程A及其子线程（可以是多个，图中两个只是举例示意）各自创建并使用自己创建的Handle；

进程A创建多个Handle，每个子线程分别使用这些Handle。

## Memory的种类

上图以PCIE模式介绍memory的种类，其中host可以是PC机/服务器，PCIE板卡就是SC5系列板卡。Host端的memory我们称之system memory，PCIE板卡上的memory我们称之为global memory，或者device memory。BM1684处理器中有专门的DMA硬件单元在system memory和global memory之间搬运数据。

## Api的概念和同步

Host这端的软件如果想让智能视觉深度学习处理器完成一个任务，需要向智能视觉深度学习处理器发送一个"api"，类似于一个命令。请注意发送api的函数和api的执行完成是异步的，所以host这端的软件还需要调用一个sync函数类等到api的真正完成。

目前发送api的动作，都已经封在bmcv/bmrt功能库中了，客户无法直接发送api，只能通过调用bmcv/bmrt的接口发送api。

调用完bmcv/bmrt的接口发送api后，是否需要调用sync函数等待api的完成，请参考bmcv/bmrt文档，bmcv/bmrt的接口可能已经将sync函数也封装在bmcv/bmrt的接口函数中了，这样bmcv/bmrt的接口函数返回后，api已经完成了。

## Profile接口

Profile接口用于获取智能视觉深度学习处理器处理api花费的时间，这个时间是从智能视觉深度学习处理器开始工作后一直累加的（如果有不断的api得到处理），如果系统中只有一个进程使用智能视觉深度学习处理器，我们可以通过计算调用api前后profile数据的差值来得到api的处理时间。

## A53的使能

在PCIE模式下，我们提供了一些接口用来启动BM1684中A53 core，并让他们完成一些加速任务。

## Power控制

我们提供了接口用于获取和设置智能视觉深度学习处理器的工作频率，用户可以自己定义一些自己的功耗控制策略。

## 杂项信息接口

用于获取板卡的信息和运行过程中的统计信息。目前包括memory总量和使用量，智能视觉深度学习处理器的利用率

# bmlib详细接口介绍

## 设备handle的创建和销毁

### bm_dev_getcount

函数原型：bm_status_t bm_dev_getcount(int \*count)

函数作用：获取当前系统中，存在多少个SOPHON设备，如果获取的设备个数为N，则devid的合法取值为[0,N-1]。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| count | 输出 | 用于存放SOPHON设备个数的指针 |

返回值：BM_SUCCESS代表获得正确个数；其他错误码代表无法获取个数

### bm_dev_query

函数原型：bm_status_t bm_dev_query(int devid)

函数作用：根据设备索引值查询某个设备是否存在

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| devid | 输入 | 被查询设备的索引值 |

返回值：BM_SUCCESS代表存在这个设备；其他错误码代表不存在这个设备

### bm_dev_request

函数原型：bm_status_t bm_dev_request(bm_handle_t \*handle, int devid)

函数作用：在指定的设备上创建handle

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输出 | 保存创建的handle的指针 |
| devid | 输入 | 指定具体设备 |

返回值：BM_SUCCESS代表创建成功；其他错误码代表创建失败

### bm_get_devid

函数原型：int bm_get_devid(bm_handle_t \*handle)

函数作用：根据给定handle获取设备索引

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：handle指向的int型设备索引

### bm_dev_free

函数原型：void bm_dev_free(bm_handle_t handle)

函数作用：释放创建的handle

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 将要被释放的handle |

返回值：无

## memory help函数接口

### bm_mem_get_type

函数原型：bm_mem_type_t bm_mem_get_type(struct bm_mem_desc mem);

函数作用：获取一块memory的种类

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem | 输入 | 被查询的memory |

返回值：BM_MEM_TYPE_DEVICE，代表global memory；BM_MEM_TYPE_SYSTEM，代表linux系统user层memory。

### bm_mem_get_device_addr

函数原型：unsigned long long bm_mem_get_device_addr(struct bm_mem_desc mem);

函数作用：获取device类型的memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem | 输入 | 被查询的memory |

返回值：返回device memory的地址，64bit的一个无符号数字

### bm_mem_set_device_addr

函数原型：void bm_mem_set_device_addr(struct bm_mem_desc \*pmem, unsigned long long addr);

函数作用：设置一个device类型 memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem | 输入/输出 | 被设置的memory的指针 |
| addr | 输入 | memory被设置的地址 |

返回值：无

### bm_mem_get_device_size

函数原型：unsigned int bm_mem_get_device_size(struct bm_mem_desc mem);

函数作用：获取一块device类型的memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem | 输入 | 被查询的memory |

返回值：返回memory大小，32位的无符号数

### bm_mem_set_device_size

函数原型：void bm_mem_set_device_size(struct bm_mem_desc \*pmem, unsigned int size);

函数作用：设置一块device类型的memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem | 输入/输出 | 被设置的memory的指针 |
| size | 输入 | memory的大小，单位是byte |

返回值：无

### bm_set_device_mem

函数原型：void bm_set_device_mem(bm_device_mem_t \*pmem, unsigned int size, unsigned long long addr);

函数作用：填充一个device类型的memory的大小和地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem | 输入/输出 | 被设置的memory的指针 |
| size | 输入 | memory的大小，单位是byte |
| addr | 输入 | memory的地址 |

返回值：无

### bm_mem_from_device

函数原型：bm_device_mem_t bm_mem_from_device(unsigned long long device_addr, unsigned int len);

函数作用：根据地址和大小构建一个bm_device_mem_t类型的结构体

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| device_addr | 输入 | memory的地址 |
| len | 输入 | memory的大小，单位是byte |

返回值：一个bm_device_mem_t类型的结构体

### bm_mem_get_system_addr

# 函数文档

## bm_mem_get_system_addr

**函数原型：** `void *bm_mem_get_system_addr(struct bm_mem_desc mem);`

**函数作用：** 获取system类型memory的地址

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem | 输入 | 被查询的memory |

**返回值：** 返回一个memory的地址

## bm_mem_set_system_addr

**函数原型：** `void bm_mem_set_system_addr(struct bm_mem_desc *pmem, void *addr);`

**函数作用：** 设置一个system类型memory的地址

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem | 输入/输出 | 被设置的memory的指针 |
| addr | 输入 | system 地址指针 |

**返回值：** 无

## bm_mem_from_system

**函数原型：** `bm_system_mem_t bm_mem_from_system(void *system_addr);`

**函数作用：** 根据一个system指针构建一个bm_system_mem_t类型的结构体

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| system_addr | 输入 | system 地址指针 |

**返回值：** 一个bm_system_mem_t类型的结构体

## Global memory的申请和释放

### bm_mem_null

**函数原型：** `bm_device_mem_t bm_mem_null(void);`

**函数作用：** 返回一个类型非法的bm memory结构体

**参数介绍：** 无

**返回值：** 一个bm_device_mem_t类型的结构体

### bm_malloc_neuron_device

**函数原型：** `bm_status_t bm_malloc_neuron_device(bm_handle_t handle, bm_device_mem_t *pmem, int n, int c, int h, int w);`

**函数作用：** 根据batch的形状信息申请一块device类型的memory，每个神经元的大小为一个FP32(4 bytes)

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| n/c/h/w | 输入 | batch 的形状 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_malloc_device_dword

**函数原型：** `bm_status_t bm_malloc_device_dword(bm_handle_t handle, bm_device_mem_t *pmem, int count);`

**函数作用：** 分配count个DWORD（4 bytes）大小的device类型的memory

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| count | 输入 | 需要分配的dword的个数 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_malloc_device_byte

**函数原型：** `bm_status_t bm_malloc_device_byte(bm_handle_t handle, bm_device_mem_t *pmem, unsigned int size);`

**函数作用：** 分配指定字节个数大小的device类型的memory

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| size | 输入 | 需要分配的byte的个数 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_malloc_device_mem

**函数原型：** `bm_status_t bm_malloc_device_mem(bm_handle_t handle, unsigned long long *paddr, int heap_id, unsigned long long size);`

**函数作用：** 分配指定字节个数大小的device类型的memory,输出分配的物理地址

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| paddr | 输出 | 分配出device memory的地址 |
| heap_id | 输入 | 所指定分配GMEM的HEAP（0/1/2） |
| size | 输入 | 需要分配的byte的个数 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_malloc_device_byte_heap

**函数原型：** `bm_status_t bm_malloc_device_byte_heap(bm_handle_t handle, bm_device_mem_t *pmem, int heap_id, unsigned int size);`

**函数作用：** 在指定的HEAP上分配指定字节个数大小的device类型的memory

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id | 输入 | 所指定分配GMEM的HEAP（0/1/2） |
| size | 输入 | 需要分配的byte的个数 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_malloc_device_byte_heap_mask

**函数原型：** `bm_status_t bm_malloc_device_byte_heap_mask(bm_handle_t handle, bm_device_mem_t *pmem, int heap_id_mask, unsigned int size);`

**函数作用：** 在指定的一个或多个HEAP上分配指定字节个数大小的device类型的memory

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id_mask | 输入 | 指定分配GMEM的HEAP id 的mask，每个bit代表一个HEAP，设置为1代表可以从这个HEAP分配，为0代表不能从这个HEAP分配，最低位bit0代表heap0，依次增加 |
| size | 输入 | 需要分配的byte的个数 |

**返回值：** BM_SUCCESS代表分配成功；其他错误码代表分配失败

### bm_free_device

**函数原型：** `void bm_free_device(bm_handle_t handle, bm_device_mem_t mem);`

# 函数文档

## bm_free_device_mem

**函数原型**：`void bm_free_device_mem(bm_handle_t handle, bm_device_mem_t mem)`

**函数作用**：释放一块device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| mem | 输入 | 要释放的device memory |

**返回值**：无

## bm_free_device_mem

**函数原型**：`void bm_free_device_mem(bm_handle_t handle, unsigned long long paddr)`

**函数作用**：释放一块device类型的memory，输入分配的物理地址

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| paddr | 输入 | 要释放的device addr |

**返回值**：无

## bm_gmem_arm_reserved_request

**函数原型**：`unsigned long long bm_gmem_arm_reserved_request(bm_handle_t handle)`

**函数作用**：获取为arm926保留的gmem的起始地址

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：为arm926保留的gmem的起始地址（一个绝对地址）

## bm_gmem_arm_reserved_release

**函数原型**：`void bm_gmem_arm_reserved_release(bm_handle_t handle)`

**函数作用**：释放为arm926保留的gmem

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：无

## 数据在host和global memory之间的搬运

### bm_memcpy_s2d

**函数原型**：`bm_status_t bm_memcpy_s2d(bm_handle_t handle, bm_device_mem_t dst, void *src)`

**函数作用**：拷贝system内存到device类型的内存中

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_s2d_partial_offset

**函数原型**：`bm_status_t bm_memcpy_s2d_partial_offset(bm_handle_t handle, bm_device_mem_t dst, void *src, unsigned int size, unsigned int offset)`

**函数作用**：拷贝system内存到device类型内存，指定长度和device内存的起始地址offset，效果是从src拷贝size长度的数据到(dst起始地址+offset)这个位置上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_s2d_partial

**函数原型**：`bm_status_t bm_memcpy_s2d_partial(bm_handle_t handle, bm_device_mem_t dst, void *src, unsigned int size)`

**函数作用**：拷贝system内存到device类型内存，指定长度；效果是从src拷贝size长度的数据到dst起始地址这个位置上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_d2s

**函数原型**：`bm_status_t bm_memcpy_d2s(bm_handle_t handle, void *dst, bm_device_mem_t src)`

**函数作用**：拷贝device类型内存到system内存

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_d2s_partial_offset

**函数原型**：`bm_status_t bm_memcpy_d2s_partial_offset(bm_handle_t handle, void *dst, bm_device_mem_t src, unsigned int size, unsigned int offset)`

**函数作用**：拷贝device类型内存到system内存，指定大小，和device memory端的offset，效果是从device memory起始地址+offset拷贝size字节数据到dst上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_d2s_partial

**函数原型**：`bm_status_t bm_memcpy_d2s_partial(bm_handle_t handle, void *dst, bm_device_mem_t src, unsigned int size)`

**函数作用**：拷贝device类型内存到system内存，指定大小；效果是从device memory起始地址拷贝size字节数据到dst上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_mem_convert_system_to_device_neuron

**函数原型**：`bm_status_t bm_mem_convert_system_to_device_neuron(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int n, int c, int h, int w)`

**函数作用**：按照batch形状申请一块device类型的memory（一个神经元大小为FP32(4 bytes)）,按需将一段system memory内存copy到这块device memory上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

### bm_mem_convert_system_to_device_neuron_byte

**函数原型**：`bm_status_t bm_mem_convert_system_to_device_neuron_byte(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int n, int c, int h, int w)`

**函数作用**：按照batch形状申请一块device类型的memory（一个神经元大小为1 bytes）,按需将一段system memory内存copy到这块device memory上。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

### bm_mem_convert_system_to_device_coeff

**函数原型**：`bm_status_t bm_mem_convert_system_to_device_coeff(bm_handle_t ...`

# bm_mem_convert_system_to_device_coeff

函数原型：bm_status_t bm_mem_convert_system_to_device_coeff(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int coeff_count);

函数作用：按照系数元素个数申请一块device类型的memory（一个系数元素大小为4个bytes）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| coeff_count | 输入 | 系数元素的个数 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_convert_system_to_device_coeff_byte

函数原型：bm_status_t bm_mem_convert_system_to_device_coeff_byte(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int coeff_count);

函数作用：按照系数元素个数申请一块device类型的memory（一个系数元素大小为1个byte）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| coeff_count | 输入 | 系数元素的个数，单位byte |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## 数据在global memory内部的搬运

### bm_memcpy_d2d

函数原型：bm_status_t bm_memcpy_d2d(bm_handle_t handle, bm_device_mem_t dst, int dst_offset, bm_device_mem_t src, int src_offset, int len);

函数作用：将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+ src_offset)拷贝len个DWORD（4字节）的数据到(dst起始地址+ dst_offset)

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory结构体 |
| dst_offset | 输入 | 用于计算数据拷贝的起始位置的offset |
| src | 输入 | 源device memory结构体 |
| src_offset | 输入 | 用于计算数据拷贝的起始位置的offset |
| len | 输入 | 数据copy长度，单位是DWORD（4字节） |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_d2d_byte

函数原型：bm_status_t bm_memcpy_d2d_byte(bm_handle_t handle, bm_device_mem_t dst, size_t dst_offset, bm_device_mem_t src, size_t src_offset, size_t size);

函数作用：将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+ src_offset)拷贝len个字节的数据到(dst起始地址+ dst_offset)

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory结构体 |
| dst_offset | 输入 | 用于计算数据拷贝的起始位置的offset |
| src | 输入 | 源device memory结构体 |
| src_offset | 输入 | 用于计算数据拷贝的起始位置的offset |
| size | 输入 | 数据copy长度，单位是字节 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memcpy_d2d_stride

函数原型：bm_status_t bm_memcpy_d2d_stride(bm_handle_t handle, bm_device_mem_t dst, int dst_stride, bm_device_mem_t src, int src_stride, int count, int format_size);

函数作用：将一块device类型的memory拷贝到另外一块device类型的memory，指定目的、源数据的stride，数据的个数，以及数据的类型字节大小；效果是从src起始地址按src_stride为间隔大小拷贝count个元素大小为format_size字节的数据到dst起始地址，以dst_stride为间隔大小存储。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory结构体 |
| dst_stride | 输入 | 目标每个元素的间隔 |
| src | 输入 | 源device memory结构体 |
| src_stride | 输入 | 源数据的每个元素的间隔 |
| count | 输入 | 需要拷贝的元素的个数 |
| format_size | 输入 | 每个元素的字节大小，比如float类型字节大小是4，uint8_t类型字节大小是1；拷贝个数、stride都是以format_size为单位 |

限制条件：dst_stride通常为1；只有一种情况可以不为1：dst_stride = 4 且 src_stride = 1 且 format_size = 1。

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

### bm_memset_device

函数原型：bm_status_t bm_memset_device(bm_handle_t handle, const int value, bm_device_mem_t mem);

函数作用：用value填充一块device memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| value | 输入 | 需要填充的值 |
| mem | 输入 | 目标device memory结构体，此函数只能填充大小为4字节整数倍的global memory空间 |

返回值：BM_SUCCESS代表填充成功；其他错误码代表填充失败

本函数的作用和bm_memset_device_ext函数mode为4时的作用一样。

### bm_memset_device_ext

函数原型：bm_status_t bm_memset_device_ext(bm_handle_t handle, void* value, int mode, bm_device_mem_t mem);

函数作用：用value指向的内容和指定的模式填充一块device memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| value | 输入 | 指向需要填充的值 |
| mode | 输入 | 填充模式，详见下图 |
| mem | 输入 | 目标device memory结构体 |

返回值：BM_SUCCESS代表填充成功；其他错误码代表填充失败

Mode为2时，dst memory的size必须是2字节的整数倍

Mode为3时，dst memory的size必须是3字节的整数倍

Mode为4时，dst memory的size必须是4字节的整数倍

# Global memory 在不同设备间搬运

## bm_memcpy_c2c

函数原型：`bm_status_t bm_memcpy_c2c(bm_handle_t src_handle, bm_handle_t dst_handle, bm_device_mem_t src, bm_device_mem_t dst, bool force_dst_cdma);`

函数作用：将global memory从一块设备搬运到另一个设备（目前仅支持同一张卡上的设备）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| src_handle | 输入 | 源地址的设备句柄 |
| dst_handle | 输入 | 目的地址的设备句柄 |
| src | 输入 | 源目标device memory 结构体 |
| dst | 输入 | 目的目标device memory 结构体 |
| force_dst_cdma | 输入 | 强制使用目的device的cdma进行搬运，默认使用源device的cdma搬运 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# Global memory在host端的映射和一致性管理

## bm_mem_mmap_device_mem

函数原型：`bm_status_t bm_mem_mmap_device_mem(bm_handle_t handle, bm_device_mem_t *dmem, unsigned long long *vmem);`

函数作用：将一块global memory映射到host的user空间，并开启cache（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被映射的global memory的结构体 |
| vmem | 输出 | 存储映射出来的虚拟地址的指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_mmap_device_mem_no_cache

函数原型：`bm_status_t bm_mem_mmap_device_mem_no_cache(bm_handle_t handle, bm_device_mem_t *dmem, unsigned long long *vmem);`

函数作用：将一块global memory映射到host的user空间，并关闭cache（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被映射的global memory的结构体 |
| vmem | 输出 | 存储映射出来的虚拟地址的指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_invalidate_device_mem

函数原型：`bm_status_t bm_mem_invalidate_device_mem(bm_handle_t handle, bm_device_mem_t *dmem);`

函数作用：invalidate一段被映射过的device memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被使无效的global memory的结构体指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_invalidate_partial_device_mem

函数原型：`bm_status_t bm_mem_invalidate_partial_device_mem(bm_handle_t handle, bm_device_mem_t *dmem, u32 offset, u32 len)`

函数作用：invalidate一段被映射过的device memory的一部分（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被使无效的global memory的结构体指针 |
| offset | 输入 | 地址偏移量 |
| len | 输入 | invalidate的长度 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_flush_device_mem

函数原型：`bm_status_t bm_mem_flush_device_mem(bm_handle_t handle, bm_device_mem_t *dmem);`

函数作用：flush一段被映射过的device global memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被flush的global memory的结构体 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_flush_partial_device_mem

函数原型：`bm_status_t bm_mem_flush_partial_device_mem(bm_handle_t handle, bm_device_mem_t *dmem, u32 offset, u32 len)`

函数作用：flush一段被映射过的device global memory的一部分（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被flush的global memory的结构体 |
| offset | 输入 | 地址偏移量 |
| len | 输入 | flush的长度 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_unmap_device_mem

函数原型：`bm_status_t bm_mem_unmap_device_mem(bm_handle_t handle, void *vmem, int size);`

函数作用：SOC 模式下，解除device内存的映射。（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| vmem | 输入 | unmap的虚拟地址 |
| size | 输入 | unmap的大小 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_vir_to_phy

函数原型：`bm_status_t bm_mem_vir_to_phy(bm_handle_t handle, unsigned long long vmem，unsigned long long *device_mem);`

函数作用：SOC 模式下，可以将bm_mem_mmap_device_mem函数得到的虚拟地址转换成device内存的物理地址。（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| vmem | 输入 | 虚拟地址 |
| device_mem | 输出 | 设备上的物理地址 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# API的同步

## bm_flush

函数原型：`void bm_flush(bm_handle_t handle);`

函数作用：此函数的功能等同于bm_handle_sync，此函数是为了保持对老的代码兼容存在的，不建议再继续使用。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：无返回值

## bm_device_sync

函数原型：`bm_status_t bm_device_sync(bm_handle_t handle);`

函数作用：这个函数的含义是：创建handle的进程调用这个函数时，在handle指向的设备上已经有了N个api在处理，函数返回后，这N个api都完成了。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_thread_sync

函数原型：`bm_status_t bm_thread_sync(bm_handle_t handle);`

函数作用：这个函数的确切含义是：等待本caller thread在handle上之前提交过的所有api完成，如果本caller thread没有在此handle上提交过api，则直接返回成功；本函数返回不能保证本caller thread在其他handle上提交过的api已经完成。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_handle_sync

函数原型：`bm_status_t bm_handle_sync(bm_handle_t handle);`

函数作用：同步提交到当前handle上所有的API操作，这个函数的含义是：调用这个函数时，通过此handle发送的API有N个，函数返回后，这N个api都完成了。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_set_sync_timeout

函数原型：`bm_status_t bm_set_sync_timeout(bm_handle_t handle, int timeout);`

函数作用：设置最大等待tpu返回消息的时间，单位ms

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| timeout | 输入 | 超时时间 |

返回值：BM_SUCCESS代表同步成功；其他错误码代表同步失败

# profile接口

## bm_get_profile

**函数原型：** `bm_status_t bm_get_profile(bm_handle_t handle, bm_profile_t *profile);`

**函数作用：** 获取当前时间点的profile数据

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| profile | 输出 | 指向一个存放profiling数据的结构体 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_last_api_process_time_us

**函数原型：** `bm_status_t bm_get_last_api_process_time_us(bm_handle_t handle, unsigned long *time_us);`

**函数作用：** 此函数已经废弃

**参数介绍：** 无

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

# power管理接口

## bm_set_clk_tpu_freq

**函数原型：** `bm_status_t bm_set_clk_tpu_freq(bm_handle_t handle, int freq);`

**函数作用：** 设置当前智能视觉深度学习处理器的工作频率，只在PCIE模式有效

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| freq | 输入 | 智能视觉深度学习处理器的目标工作频率 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_clk_tpu_freq

**函数原型：** `bm_status_t bm_get_clk_tpu_freq(bm_handle_t handle, int *freq);`

**函数作用：** 获取当前智能视觉深度学习处理器的工作频率

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| freq | 输出 | 保存智能视觉深度学习处理器当前工作频率的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

# 设备管理接口

## bm_get_misc_info

**函数原型：** `bm_status_t bm_get_misc_info(bm_handle_t handle, struct bm_misc_info *pmisc_info);`

**函数作用：** 获取设备相关的misc信息

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| pmisc_info | 输出 | 存放misc数据的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_card_num

**函数原型：** `bm_status_t bm_get_card_num(unsigned int *card_num);`

**函数作用：** 获取设备上卡的数量

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| card_num | 输出 | 存放卡数量的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_card_id

**函数原型：** `bm_status_t bm_get_card_id(bm_handle_t handle, unsigned int *card_id);`

**函数作用：** 获取设备对应卡的编号

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| card_id | 输出 | 存放卡id的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_chip_num_from_card

**函数原型：** `bm_get_chip_num_from_card(unsigned int card_id, unsigned int *chip_num, unsigned int *dev_start_index);`

**函数作用：** 获取卡上的设备编号

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| card_id | 输入 | 卡编号 |
| chip_num | 输出 | 卡上设备数量 |
| dev_start_index | 输出 | 卡上设备起始编号 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_chipid

**函数原型：** `bm_status_t bm_get_chipid(bm_handle_t handle, unsigned int *p_chipid);`

**函数作用：** 获取设备对应的处理器ID(0x1684和0x1686)

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| p_chipid | 输出 | 存放处理器ID的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_vpu_instant_usage

**函数原型：** `bm_status_t bm_get_vpu_instant_usage(bm_handle_t handle, int *vpu_usage);`

**函数作用：** 获取设备对应的vpu使用率

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| vpu_usage | 输出 | 存放vpu多核的使用率的数组 |

bm1684板卡为5核vpu，vpu_usage应为5位数组，bm1684x板卡为3核vpu，vpu_usage应为3位数组

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_jpu_core_usage

**函数原型：** `bm_status_t bm_get_jpu_core_usage(bm_handle_t handle, int *jpu_usage);`

**函数作用：** 获取设备对应的jpu使用率

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| jpu_usage | 输出 | 存放jpu多核的使用率的数组 |

bm1684板卡为4核jpu，jpu_usage应为4位数组，bm1684x板卡为2核jpu，jpu_usage应为2位数组

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_vpp_instant_usage

**函数原型：** `bm_status_t bm_get_vpp_instant_usage(bm_handle_t handle, int *vpp_usage);`

**函数作用：** 获取设备对应的vpp使用率

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| vpp_usage | 输出 | 存放vpp多核的使用率的数组 |

bm1684板卡与bm1684x板卡均为2核vpp，vpp_usage应为2位数组

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_stat

**函数原型：** `bm_status_t bm_get_stat(bm_handle_t handle, bm_dev_stat_t *stat);`

**函数作用：** 获取handle对应的设备的运行时统计信息

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Stat | 输出 | 存放统计信息的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_gmem_heap_id

**函数原型：** `bm_get_gmem_heap_id(bm_handle_t handle, bm_device_mem_t *pmem, unsigned int *heapid);`

**函数作用：** 获取pmem指向的设备内存的heap id

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Pmem | 输入 | 设备内存指针 |
| Heaped | 输出 | 存放设备内存所在heap id 的指针 |

**返回值：** BM_SUCCESS代表成功；其他错误码代表失败

## bmlib_log_get_level

**函数原型：** `int bmlib_log_get_level(void);`

**函数作用：** 获取bmlib log等级

**参数介绍：** void

**返回值：** bmlib log 等级

## bmlib_log_set_level

**函数原型：** `void bmlib_log_set_level(int level);`

**函数作用：** 设置bmlib log等级

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Level | 输入 | 要设置的bmlib log的等级 |

**返回值：** void

## bmlib_log_set_callback

**函数原型：** `void bmlib_log_set_callback((*callback)(const char* , int , const char*, va_list));`

**函数作用：** 设置callback获取bmlib log

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Callback | 输入 | 设置获取bmlib log的回调函数的函数指针 |

**返回值：** void

## bm_set_debug_mode

**函数原型：** `void bm_set_debug_mode(bm_handle_t handle, int mode);`

# bmlib_set_fw_log_dbg_mode

**函数原型：** `void bmlib_set_fw_log_dbg_mode(bm_handle_t handle, int mode);`

**函数作用：** 为智能视觉深度学习处理器 fw log 设置 debug 模式  
**备注：** 此函数 SC3 在使用

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Mode | 输入 | fw log debug 模式，0/1 表示 disable/enable |

**返回值：** void

# bmlib_set_api_dbg_callback

**函数原型：** `void bmlib_set_api_dbg_callback(bmlib_api_dbg_callback callback);`

**函数作用：** 设置 debug callback 获取 fw log  
**备注：** 此函数 SC3 在使用

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Callback | 输入 | 要设置的获取 fw log 回调函数的函数指针 |

**返回值：** void

# bm_get_tpu_current

**函数原型：** `bm_status_t bm_get_tpu_current(bm_handle_t handle, int *tpuc);`

**函数作用：** 获取句柄对应设备的电流值，默认单位毫安（mA）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpuc | 输出 | 要获取 tpuc 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_board_max_power

**函数原型：** `bm_status_t bm_get_board_max_power(bm_handle_t handle, int *maxp);`

**函数作用：** 获取设备所在板卡支持的最大功耗值，默认单位瓦（W）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| maxp | 输出 | 要获取 maxp 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_board_power

**函数原型：** `bm_status_t bm_get_board_power(bm_handle_t handle, int *boardp);`

**函数作用：** 获取设备所在板卡的当前功耗值，默认单位瓦（W）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| boardp | 输出 | 要获取 boardp 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_fan_speed

**函数原型：** `bm_status_t bm_get_fan_speed(bm_handle_t handle, int *fan);`

**函数作用：** 获取设备所在板卡的风扇占空比。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| fan | 输出 | 要获取 fan 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_ecc_correct_num

**函数原型：** `bm_status_t bm_get_ecc_correct_num(bm_handle_t handle, unsigned long *ecc_correct_num);`

**函数作用：** 获取设备在 DDR 使能时，纠正错误的次数。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| ecc_correct_num | 输出 | 要获取 ecc_correct_num 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_12v_atx

**函数原型：** `bm_status_t bm_get_12v_atx(bm_handle_t handle, int *atx_12v);`

**函数作用：** 获取设备板级 12V 供电电流，默认单位毫安（mA）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| atx_12v | 输出 | 要获取 atx_12v 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_sn

**函数原型：** `bm_status_t bm_get_sn(bm_handle_t handle, char *sn);`

**函数作用：** 获取板卡序列号（共 17 位）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| sn | 输出 | 要获取 sn 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_status

**函数原型：** `bm_status_t bm_get_status(bm_handle_t handle, int *status);`

**函数作用：** 获取句柄对应的设备状态，0 为活动状态，1 为故障状态。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| status | 输出 | 要获取 status 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_tpu_minclk

**函数原型：** `bm_status_t bm_get_tpu_minclk(bm_handle_t handle, unsigned int *tpu_minclk);`

**函数作用：** 获取句柄对应设备的最小工作频率，默认单位兆赫兹（MHz）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpu_minclk | 输出 | 要获取 tpu_minclk 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_tpu_maxclk

**函数原型：** `bm_status_t bm_get_tpu_maxclk(bm_handle_t handle, unsigned int *tpu_maxclk);`

**函数作用：** 获取句柄对应设备的最大工作频率，默认单位兆赫兹（MHz）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpu_maxclk | 输出 | 要获取 tpu_maxclk 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_driver_version

**函数原型：** `bm_status_t bm_get_driver_version(bm_handle_t handle, int *driver_version);`

**函数作用：** 获取板卡安装的驱动版本。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| driver_version | 输出 | 要获取 driver_version 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_board_name

**函数原型：** `bm_status_t bm_get_board_name(bm_handle_t handle, char *name);`

**函数作用：** 获取当前板卡的名称，名称：处理器 id-板卡类型（如：1684-SC5+）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| name | 输出 | 要获取 name 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_board_temp

**函数原型：** `bm_status_t bm_get_board_temp(bm_handle_t handle, unsigned int *board_temp);`

**函数作用：** 获取句柄对应设备所在板卡的板级温度，默认单位摄氏度（℃）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| board_temp | 输出 | 要获取 board_temp 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_chip_temp

**函数原型：** `bm_status_t bm_get_chip_temp(bm_handle_t handle, unsigned int *chip_temp);`

**函数作用：** 获取句柄对应设备的温度，默认单位摄氏度（℃）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| chip_temp | 输出 | 要获取 chip_temp 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_tpu_power

**函数原型：** `bm_status_t bm_get_tpu_power(bm_handle_t handle, float *tpu_power);`

**函数作用：** 获取句柄对应设备的功耗，默认单位瓦（W）。

**参数介绍：**

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpu_power | 输出 | 要获取 tpu_power 的函数指针 |

**返回值：** BM_SUCCESS 代表成功；其他错误码代表失败

# bm_get_tpu_volt

函数原型：`bm_status_t bm_get_tpu_volt(bm_handle_t handle, float *tpu_volt);`

函数作用：获取句柄对应设备的电压，默认单位毫伏（mV）。

参数介绍：

| 参数名   | 输入/输出 | 说明                      |
|----------|-----------|---------------------------|
| handle   | 输入      | 设备句柄                  |
| tpu_volt | 输出      | 要获取tpu_volt的函数指针  |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# A53使能

## bmcpu_start_cpu

函数原型：`bm_status_t bmcpu_start_cpu(bm_handle_t handle, char *boot_file, char *core_file);`

函数作用：启动设备上的ARM处理器A53。

参数介绍：

| 参数名    | 输入/输出 | 说明                      |
|-----------|-----------|---------------------------|
| handle    | 输入      | 设备句柄                  |
| boot_file | 输入      | ARM处理器启动的boot文件   |
| core_file | 输入      | ARM处理器启动的kernel文件 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bmcpu_open_process

函数原型：`int bmcpu_open_process(bm_handle_t handle, unsigned int flags, int timeout);`

函数作用：创建运行在A53上的进程。

参数介绍：

| 参数名 | 输入/输出 | 说明                    |
|--------|-----------|-------------------------|
| handle | 输入      | 设备句柄                |
| flags  | 输入      | 创建a53进程的标志位     |
| timeout| 输入      | 创建a53进程的超时时间   |

返回值：A53上进程句柄

## bmcpu_load_library

函数原型：`bm_status_t bmcpu_load_library(bm_handle_t handle, int process_handle, char *library_file, int timeout);`

函数作用：加载A53上进程所需要的动态库。

参数介绍：

| 参数名         | 输入/输出 | 说明                    |
|----------------|-----------|-------------------------|
| handle         | 输入      | 设备句柄                |
| process_handle | 输入      | A53上进程句柄           |
| library_file   | 输入      | 需要加载的动态库文件    |
| timeout        | 输入      | 加载动态库的超时时间    |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bmcpu_exec_function

函数原型：`int bmcpu_exec_function(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, int timeout);`

函数作用：在A53进程执行指定函数。

参数介绍：

| 参数名         | 输入/输出 | 说明                        |
|----------------|-----------|-----------------------------|
| handle         | 输入      | 设备句柄                    |
| process_handle | 输入      | A53上进程句柄               |
| function_name  | 输入      | 需要执行的函数名称          |
| function_param | 输入      | 需要执行的函数入参地址      |
| param_size     | 输入      | 需要执行的函数入参大小      |
| timeout        | 输入      | A53执行函数的超时时间       |

返回值：0代表成功；大于0代表bmlib失败，小于0代表function执行失败

## bmcpu_exec_function_ext

函数原型：`int bmcpu_exec_function_ext(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, unsigned int opt, int timeout);`

函数作用：在A53进程执行指定函数，设置是否刷新cache。

参数介绍：

| 参数名         | 输入/输出 | 说明                        |
|----------------|-----------|-----------------------------|
| handle         | 输入      | 设备句柄                    |
| process_handle | 输入      | A53上进程句柄               |
| function_name  | 输入      | 需要执行的函数名称          |
| function_param | 输入      | 需要执行的函数入参地址      |
| param_size     | 输入      | 需要执行的函数入参大小      |
| opt            | 输入      | 是否需要刷新cache           |
| timeout        | 输入      | A53执行函数的超时时间       |

返回值：0代表成功；大于0代表bmlib失敗，小于0代表function执行失败

## bmcpu_map_phys_addr

函数原型：`void *bmcpu_map_phys_addr(bm_handle_t handle, int process_handle, void *phys_addr, unsigned int size, int timeout);`

函数作用：将设备物理地址映射成A53能访问的虚拟地址。

参数介绍：

| 参数名         | 输入/输出 | 说明                                  |
|----------------|-----------|---------------------------------------|
| handle         | 输入      | 设备句柄                              |
| process_handle | 输入      | A53上进程句柄                         |
| phys_addr      | 输入      | host侧申请的设备内存对应的虚拟地址    |
| size           | 输入      | 申请的内存大小                        |
| timeout        | 输入      | A53映射地址的超时时间                 |

返回值：设备物理地址映射成的A53能访问的虚拟地址

## bmcpu_unmap_phys_addr

函数原型：`bm_status_t bmcpu_unmap_phys_addr(bm_handle_t handle, int process_handle, void *phys_addr, int timeout);`

函数作用：释放被A53映射的物理地址。

参数介绍：

| 参数名         | 输入/输出 | 说明                                  |
|----------------|-----------|---------------------------------------|
| handle         | 输入      | 设备句柄                              |
| process_handle | 输入      | A53上进程句柄                         |
| phys_addr      | 输入      | host侧申请的设备内存对应的A53虚拟地址 |
| timeout        | 输入      | A53映射地址的超时时间                 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bmcpu_close_process

函数原型：`int bmcpu_close_process(bm_handle_t handle, int process_handle, int timeout);`

函数作用：关闭运行在A53上的进程。

参数介绍：

| 参数名         | 输入/输出 | 说明                    |
|----------------|-----------|-------------------------|
| handle         | 输入      | 设备句柄                |
| process_handle | 输入      | A53上进程句柄           |
| timeout        | 输入      | 关闭a53进程的超时时间   |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

## bmcpu_reset_cpu

函数原型：`bm_status_t bmcpu_reset_cpu(bm_handle_t handle);`

函数作用：使A53进入关机状态。

参数介绍：

| 参数名 | 输入/输出 | 说明     |
|--------|-----------|----------|
| handle | 输入      | 设备句柄 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# 相关数据结构定义

## bm_status_t

```c
typedef enum {
    BM_SUCCESS = 0,
    BM_ERR_DEVNOTREADY = 1, /* Device not ready yet */
    BM_ERR_FAILURE = 2, /* General failure */
    BM_ERR_TIMEOUT = 3, /* Timeout */
    BM_ERR_PARAM = 4, /* Parameters invalid */
    BM_ERR_NOMEM = 5, /* Not enough memory */
    BM_ERR_DATA = 6, /* Data error */
    BM_ERR_BUSY = 7, /* Busy */
    BM_ERR_NOFEATURE = 8, /* Not supported yet */
    BM_NOT_SUPPORTED = 9
} bm_status_t;
```

## bm_mem_type_t

```c
typedef enum {
    BM_MEM_TYPE_DEVICE = 0,
    BM_MEM_TYPE_HOST = 1,
    BM_MEM_TYPE_SYSTEM = 2,
    BM_MEM_TYPE_INT8_DEVICE = 3,
    BM_MEM_TYPE_INVALID = 4
} bm_mem_type_t;
```

## bm_mem_flags_t

```c
typedef union {
    struct {
        bm_mem_type_t mem_type : 3;
        unsigned int reserved : 29;
    } u;
    unsigned int rawflags;
} bm_mem_flags_t;
```

## bm_mem_desc_t

```c
typedef struct bm_mem_desc {
    union {
        struct {
            unsigned long device_addr;
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

## bm_misc_info

```c
struct bm_misc_info {
    int pcie_soc_mode; /*0---pcie; 1---soc*/
    int ddr_ecc_enable; /*0---disable; 1---enable*/
    unsigned int chipid;
    #define BM1682_CHIPID_BIT_MASK (0X1 << 0)
    #define BM1684_CHIPID_BIT_MASK (0X1 << 1)
    unsigned long chipid_bit_mask;
    unsigned int driver_version;
    int domain_bdf;
};
```

## bm_profile_t

```c
typedef struct bm_profile {
    unsigned long cdma_in_time;
    unsigned long cdma_in_counter;
    unsigned long cdma_out_time;
    unsigned long cdma_out_counter;
    unsigned long tpu_process_time;
    unsigned long tpu1_process_time;
    unsigned long sent_api_counter;
    unsigned long completed_api_counter;
} bm_profile_t;
```

## bm_heap_stat

```c
struct bm_heap_stat {
    unsigned int mem_total;
    unsigned int mem_avail;
    unsigned int mem_used;
}
```

## bm_dev_stat_t

```c
typedef struct bm_dev_stat {
    int mem_total;
    int mem_used;
    int tpu_util;
    int heap_num;
    struct bm_heap_stat heap_stat[4];
} bm_dev_stat_t;
```

## bm_log_level

```c
#define BMLIB_LOG_QUIET -8
#define BMLIB_LOG_PANIC 0
#define BMLIB_LOG_FATAL 8
#define BMLIB_LOG_ERROR 16
#define BMLIB_LOG_WARNING 24
#define BMLIB_LOG_INFO 32
#define BMLIB_LOG_VERBOSE 40
#define BMLIB_LOG_DEBUG 48
#define BMLIB_LOG_TRACE 56
```