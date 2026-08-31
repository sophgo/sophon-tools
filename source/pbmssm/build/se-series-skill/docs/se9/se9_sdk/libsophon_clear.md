# 安装libsophon

libsophon在不同的Linux发行版上提供不同类型的安装方式。请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。
以下描述中"0.4.9"仅为示例，视当前实际安装版本会有变化。

**如果安装了V3.0.0版本及之前版本的SDK驱动，请先卸载旧的驱动：**

进入SDK的安装目录，执行：
```
sudo ./remove_driver_pcie.sh
```
或者：
```
sudo rmmod bmsophon
sudo rm -f /lib/modules/$(uname -r)/kernel/drivers/pci/bmsophon.ko
```

## 如果使用Debian/Ubuntu系统：

安装包由三个文件构成，其中"$arch"为当前机器的硬件架构，使用以下命令可以获取当前服务器的arch：
```
uname -m
```

通常x86_64机器对应的硬件架构为amd64，arm64机器对应的硬件架构为arm64：
- sophon-driver_0.4.9_$arch.deb
- sophon-libsophon_0.4.9_$arch.deb
- sophon-libsophon-dev_0.4.9_$arch.deb

其中：sophon-driver包含了PCIe加速卡驱动；sophon-libsophon包含了运行时环境（库文件、工具等）；sophon-libsophon-dev包含了开发环境（头文件等）。
如果只是在部署环境上安装，则不需要安装sophon-libsophon-dev。

可以通过如下步骤安装：
```
安装依赖库，只需要执行一次：
sudo apt install dkms libncurses5
安装libsophon：
sudo dpkg -i sophon-*.deb
在终端执行如下命令，或者登出再登入当前用户后即可使用bm-smi等命令：
source /etc/profile
```

安装位置为：
```
/opt/sophon/
├── driver-0.4.9
├── libsophon-0.4.9
│   ├── bin
│   ├── data
│   ├── include
│   └── lib
└── libsophon-current -> /opt/sophon/libsophon-0.4.9
```

deb包安装方式并不允许您安装同一个包的多个不同版本，但您可能用其它方式在/opt/sophon下放置了若干不同版本。
在使用deb包安装时，/opt/sophon/libsophon-current会指向最后安装的那个版本。在卸载后，它会指向余下的最新版本（如果有的话）。

在使用deb包安装时，如果出现了下面的提示信息
```
modprobe: FATAL: Module bmsophon is in use.
```

需要您手动停止正在使用驱动的程序后，手动执行下面的命令来安装新的deb包里的驱动。
```
sudo modprobe -r bmsophon
sudo modprobe bmsophon
```

### 卸载方式：

注意：如果安装了sophon-mw及sophon-rpc，因为它们对libsophon有依赖关系，请先卸载它们。
```
sudo apt remove sophon-driver sophon-libsophon
或者:
sudo dpkg -r sophon-driver
sudo dpkg -r sophon-libsophon-dev
sudo dpkg -r sophon-libsophon
```

如果卸载时遇到问题，可以尝试如下方法：
```
手工卸载驱动：
dkms status
检查输出结果，通常如下：
bmsophon, 0.4.9, 5.15.0-41-generic, x86_64: installed
记下前两个字段，套用到如下命令中：
sudo dkms remove -m bmsophon -v 0.4.9 --all
然后再次卸载驱动：
sudo apt remove sophon-driver
sudo dpkg --purge sophon-driver
彻底清除libsophon：
sudo apt purge sophon-libsophon
```

## 如果使用Centos系统, 当前版本仅支持x86_64：

安装包由三个文件构成，其中"$arch"为当前机器的硬件架构，使用以下命令可以获取当前服务器的arch：
```
uname -m
```

x86_64机器对应的安装包名称为：
- sophon-driver-0.4.9-1.$arch.rpm
- sophon-libsophon-0.4.9-1.$arch.rpm
- sophon-libsophon-dev-0.4.9-1.$arch.rpm

安装前需要通过后面"卸载方式"中的步骤卸载旧版本libsophon，可以通过如下步骤安装：
```
安装依赖库，只需要执行一次:
sudo yum install -y epel-release
sudo yum install -y dkms
sudo yum install -y ncurses*
安装libsophon：
sudo  rpm -ivh sophon-driver-0.4.9-1.x86_64.rpm
sudo  rpm -ivh sophon-libsophon-0.4.9-1.x86_64.rpm
sudo  rpm -ivh --force sophon-libsophon-dev-0.4.9-1.x86_64.rpm
在终端执行如下命令，或者登出再登入当前用户后即可使用bm-smi等命令：
source /etc/profile
```

### 卸载方式：
```
sudo rpm -e sophon-driver
sudo rpm -e sophon-libsophon-dev
sudo rpm -e sophon-libsophon
```

## 如果使用其它Linux系统：

安装包由一个文件构成，其中"$arch"为当前机器的硬件架构，使用以下命令可以获取当前服务器的arch：
```
uname -m
```

通常x86_64机器对应的硬件架构为x86_64，arm64机器对应的硬件架构为aarch64：
- libsophon_0.4.9_$arch.tar.gz

可以通过如下步骤安装：

注意：如果有旧版本，先参考下面的卸载方式步骤卸载旧版本。
```
tar -xzvf libsophon_0.4.9_$arch.tar.gz
sudo cp -r libsophon_0.4.9_$arch/* /
sudo ln -s /opt/sophon/libsophon-0.4.9 /opt/sophon/libsophon-current
```

接下来请先按照您所使用Linux发行版的要求搭建驱动编译环境，然后做如下操作：
```
sudo ln -s /opt/sophon/driver-0.4.9/$bin /lib/firmware/bm1684x_firmware.bin
sudo ln -s /opt/sophon/driver-0.4.9/$bin /lib/firmware/bm1684_ddr_firmware.bin
sudo ln -s /opt/sophon/driver-0.4.9/$bin /lib/firmware/bm1684_tcm_firmware.bin
cd /opt/sophon/driver-0.4.9
```

此处"$bin"是bin文件全名, 对于bm1684x板卡，为a53lite_pkg.bin, 对于bm1684板卡，如bm1684_ddr.bin_v3.1.3-1b97c53f-221230和bm1684_tcm.bin_v3.1.3-1b97c53f-221230。

之后就可以编译驱动了（这里不依赖于dkms）：
```
sudo make SOC_MODE=0 PLATFORM=asic SYNC_API_INT_MODE=1 \
          TARGET_PROJECT=sg_pcie_device FW_SIMPLE=0 \
          PCIE_MODE_ENABLE_CPU=1
sudo cp ./bmsophon.ko /lib/modules/$(uname -r)/kernel/
sudo depmod
sudo modprobe bmsophon
```

最后是一些配置工作：
```
添加库和可执行文件路径：
sudo cp /opt/sophon/libsophon-current/data/libsophon.conf /etc/ld.so.conf.d/
sudo ldconfig
sudo cp /opt/sophon/libsophon-current/data/libsophon-bin-path.sh /etc/profile.d/
在终端执行如下命令，或者登出再登入当前用户后即可使用bm-smi等命令：
source /etc/profile

添加cmake config文件：
sudo mkdir -p /usr/lib/cmake/libsophon
sudo cp /opt/sophon/libsophon-current/data/libsophon-config.cmake /usr/lib/cmake/libsophon/
```

### 卸载方式：
```
sudo rm -f /etc/ld.so.conf.d/libsophon.conf
sudo ldconfig
sudo rm -f /etc/profile.d/libsophon-bin-path.sh
sudo rm -rf /usr/lib/cmake/libsophon
sudo rmmod bmsophon
sudo rm -f /lib/modules/$(uname -r)/kernel/bmsophon.ko
sudo depmod
sudo rm -f /lib/firmware/bm1684x_firmware.bin
sudo rm -f /lib/firmware/bm1684_ddr_firmware.bin
sudo rm -f /lib/firmware/bm1684_tcm_firmware.bin
sudo rm -f /opt/sophon/libsophon-current
sudo rm -rf /opt/sophon/libsophon-0.4.9
sudo rm -rf /opt/sophon/driver-0.4.9
```

# 使用libsophon开发

## PCIE MODE

在安装完libsophon后，推荐您使用cmake来将libsophon中的库链接到自己的程序中，可以在您程序的CMakeLists.txt中添加如下段落：
```
find_package(libsophon REQUIRED)
include_directories(${LIBSOPHON_INCLUDE_DIRS})

add_executable(${YOUR_TARGET_NAME} ${YOUR_SOURCE_FILES})

target_link_libraries(${YOUR_TARGET_NAME} ${the_libbmlib.so})
上面${the_libbmlib.so}即表示要链接libbmlib.so这个库，其它库同理。
```

在您的代码中即可以调用libbmlib中的函数：
```c
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

## SOC MODE

### SOC 板卡上编译程序

如果您希望在SOC模式的板子上运行的Linux环境下进行开发，则需要安装sophon-soc-libsophon-dev_0.4.8_arm64.deb工具包，使用以下命令安装。
```
sudo dpkg -i sophon-soc-libsophon-dev_0.4.8_arm64.deb
```

安装完成后，您可以参考PCIE MODE的开发方法，使用cmake将libsophon中的库链接到自己的程序中。

### x86 交叉编译程序

如果您希望使用SOPHON SDK搭建交叉编译环境，您需要用到的是gcc-aarch64-linux-gnu工具链以及sophon-img relesae包里的libsophon_soc_0.4.8_aarch64.tar.gz。首先使用如下命令安装gcc-aarch64-linux-gnu工具链。
```
sudo apt-get install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

其次解压sophon-img relesae包里的libsophon_soc_0.4.8_aarch64.tar.gz。
```
1. mkdir -p soc-sdk
2. tar -zxf libsophon_soc_0.4.8_aarch64.tar.gz
3. cp -rf libsophon_soc_0.4.8_aarch64/opt/sophon/libsophon-0.4.8/lib  soc-sdk
4. cp -rf libsophon_soc_0.4.8_aarch64/opt/sophon/libsophon-0.4.8/include  soc-sdk
```

libsophon包含了bmrt,bmlib和bmcv的库。 opencv 和ffmpeg 相关的库在sophon-mw-soc_0.4.8_aarch64.tar.gz中，
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
```c
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

```bash
mkdir -p build && pushd build
cmake -DSDK=/path_to_sdk/soc-sdk ..
make
```

就可以在x86机器上编译出soc模式上运行的aarch64架构的程序。

上面例子只链接了bmlib的库，其它库如opencv，ffmpeg，其它lib同理。

## 术语解释

| **术语** | **说明** |
|----------|----------|
| **BM1684** | 算能面向深度学习领域推出的第三代张量处理器 |
| **BM1684X** | 算能面向深度学习领域推出的第四代张量处理器 |
| **bm1688** | 算能面向深度学习领域推出的第五代张量处理器 |
| **TPU** | 芯片内部神经网络处理单元 |
| **SOC模式** | 一种产品形态，SDK运行于A53 AARCH64平台，TPU作为平台总线设备 |
| **PCIe模式** | 一种产品形态，SDK运行于X86平台，BM1684、BM1684X存在于PCIe接口的深度学习计算加速卡上 |
| **Drivers** | Drivers是API接口访问硬件的通道 |
| **Gmem** | 卡上用于TPU加速的DDR内存 |
| **F** | FAULT 故障状态 |
| **N/A** | 此项参数不支持 |

## bm-smi介绍

bm-smi工具以界面或者文本的形式显示设备状态信息，如设备的温度、风扇转速等信息；也可使能、禁用或者设置设备的某些功能，如led、ecc等。

bm-smi主要功能有：

1) 查看设备参数和运行时状态
   - 查看设备工作模式（PCIe/SOC）
   - 查看物理板卡ID
   - 查看设备芯片ID，所在PCIe总线ID
   - 查看设备温度和功耗
   - 查看设备ECC使能与否和纠正次数
   - 查看gmem总数和利率
   - 查看tpu利用率
   - 查看设备工作频率信息
   - 查看运行时，各进程所占gmem大小
   - 查看设备风扇状态

2) 修改板卡参数
   - 禁止、使能ECC
   - 打开、关闭板上led指示灯

3) 执行故障设备的recovery操作

下表列举了bm-smi可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

| **设备信息** | **PCIe模式** | **SOC模式** |
|-------------|-------------|------------|
| 显示时间日期 | 支持 | 支持 |
| SDK Version | 支持 | 支持 |
| Driver Version | 支持 | 支持 |
| 物理板卡id号 | 支持 | 支持 |
| tpu的设备号 | 支持 | 支持 |
| 板卡名称 | 支持 | 支持 |
| 板卡状态 | 支持 | 支持 |
| 板级温度 | 支持 | 不支持 |
| 芯片温度 | 支持 | 不支持 |
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
| tpu的瞬时利用率 | 支持 | 支持 |
| 风扇转速 | 支持 | 不支持 |
| 每个进程（或者线程）占用的gmem的数量 | 支持 | 不支持 |
| 文本模式 | 支持 | 不支持 |
| 参数 | 支持 | 仅支持file、lms、loop |

图1为SC5+(三芯)/SC5H/SC5P(八芯)的显示状态，每张卡之间用=======隔开，最左边显示的板卡级别的属性，右边和中间显示的是单个芯片的状态。

bm-smi是一个可执行文件，不依赖其他动态库，位于/opt/sophon/libsophon-current/bin目录下，上图为一个执行bm-smi的示意图。

## 各项参数的含义

下面逐一介绍每个部分代表的含义。

- Fri Aug 7 14:18:57 2020执行bm-smi时的时间日期，这里只是示例，实际执行时可能和这里显示的不同
- SDK Version: 2.3.2：sdk的版本号，这里只是示例，实际执行时可能和这里显示的不同
- Driver Version: 2.3.2：驱动的版本号，这里只是示例，实际执行时可能和这里显示的不同
- Card : 物理板卡id号
- Name：板卡名称
- Mode: PCIe or SOC mode
- SN : 板卡序列号（共17位）
- TPU : tpu的设备号
- BoardT:板级温度
- chipT:芯片温度
- TPU_P:TPU模块功耗
- TPU_V:TPU模块电压
- ECC: DDR ECC是否使能
- CorrectNum:若DDR使能，纠正错误的次数
- Tpu-Util:tpu的瞬时利用率
- 12V_ATX：板级12V供电电流
- MaxP:板卡最大功耗
- boardP:板级功耗
- Minclk:tpu最小工作频率
- Maxclk:tpu最大工作频率
- Fan:风扇转速，显示N/A 表示本卡无风扇，显示F 表示有风扇故障
- Bus-ID:PCIe模式下domain:b:d.f
- Status:板卡状态，Active为活动状态，Fault为故障状态
- Curclk:tpu当前工作频率，显示的值的颜色根据当前工作频率而不同，550M（bm1684）或1000M（bm1684x）显示白色，75M显示红色，其他频率显示黄色；红色和黄色用于提示用户当前工作频率不是最大工作频率。显示不同颜色只在2.1.0版本及以上版本才有。
- TPU_C: tpu模块的工作电流
- Ion-Usage:gmem总数和已使用数量。板卡上的memory有可能分布在不同的地址空间，我们分配的内存都是地址连续的内存，而且由于每次分配的大小不一样，会导致内存的碎片化，所以有可能出现利用率达不到100%的情况。
- Vpp-Usage:Vpp heap总数和已使用数量。
- Npu-Usage:Npu heap总数和已使用数量。

下面显示的是每个设备上每个进程（或者线程）通过bmlib handle申请的gmem的数量。

**注意事项：**

1、因为我们的板卡是支持多任务多用户同时使用的，理论上可以有无限个进程创建无限个handle申请global memory，可以使用上下方向键以及翻页键去查看所有的process占用gmem的信息，通过标记保存成文件，也是包含所有process信息的。

2、process占用的gmem信息，每一行显示的是这个process创建的一个bmlib handle对应的gmem，如果这个process创建了多个handle，那么每个handle占用的gmem信息是单独一行显示的。

## 具体使用方法和参数

bm-smi支持的参数有：

- dev (which dev is selected to query, 0xff is for all.) type: int32，default: 255

  用于选择查询或者修改哪个设备的参数，默认所有设备。

  该功能SOC模式不支持。

- ecc (ECC on DDR is on or off.)

  type: string default: ""

  用来配置DDR ECC的使能和关闭，示例如下

  ```
  bm-smi --dev=0x0 --ecc=on
  bm-smi --dev=0x0 --ecc=off
  ```

  执行这个命令时，不要让任何进程使用这个设备，设置完毕后，重启主机生效。

  执行这个命令时，请不要和其他参数一起使用，例如：
  ```
  bm-smi --dev=0x0 --ecc=on --file=~/a.txt
  ```
  这条命令中的--file=~/a.txt会被忽略，这条命令只会执行ecc相关的动作。

  如果不指定dev参数，默认对所有设备做操作。

  该功能SOC模式不支持。

- file (target file to save smi log.)

  type: string default: ""

  可以将设备的状态重定向到文本文档中，使用方法如下：

  ```
  bm-smi --dev=0x0 --file=./bm-smi.log
  ```

  该功能SOC模式支持。

- led (pcie card LED status: on/off/blink)

  type: string default: "on"

  用来配置板卡LED的亮和灭，示例如下

  ```
  bm-smi --dev=0x0 --led=on
  bm-smi --dev=0x0 --led=off
  ```

  注意：此功能在SC5+和SC5P上支持 on/off/blink，在SC5H上支持on/off，其它板卡类型不支持。SC5+板卡只有第一个芯片才能控制LED灯的状态，SC5P拥有8个led，每个设备都对应一个led，每个led都支持单独设置状态。

  该功能SOC模式不支持。

- lms (sample interval in loop mode.) type: int32 default: 500

  用来设置运行bm-smi时查询设备状态的时间间隔，默认是500ms查询一次，这个参数的最小值是300ms。该功能SOC模式支持。

- loop (true is for loop mode, false is for only once mode.) type: bool，default: true

  用来设置运行bm-smi时是单次模式还是周期模式，默认周期模式。单次模式下查询一次设备状态后bm-smi就退出了；周期模式下按照lms为周期反复查询设备状态。示例如下：

  ```
  bm-smi --loop
  bm-smi --noloop
  ```

  该功能SOC模式支持。

- recovery，使用方式为：发现某个设备x功能出现故障,用户将所有业务从这个卡上移走，达到没有任何上层业务和应用使用这个板卡的状态，执行

  ```
  bm-smi --dev=0x(0/1/2/3…..) --recovery
  ```

  三芯卡SC5+ 和八芯卡SC5P只支持整卡recovery，recovery 卡上的任意设备，就会把整个卡recovery，所以recovery 的时候需要把整个卡上的任务停掉。

  注意：不要在板卡正常工作时执行这个操作，某些服务器不支持这个功能，执行这个功能会导致服务器重启。目前已知不支持的有dell R740、dell R940、浪潮5468和曙光X785-G30。

  该功能SOC模式不支持。

- opmode和opval，使用方式为：选择bm-smi执行的模式以及模式值，兼容前面的标记，例如：

  ```
  bm-smi --opmode=display与bm-smi效果一样
  bm-smi --opmode=ecc --opval=on 与bm-smi --ecc=on效果一样。其他标记以此类推。
  ```

  目前opmode共有：display(显示)、ecc(使能)、led（指示灯）、recovery四种操作模式，后续新功能都将以这种方式使用，为了照顾旧版本用户操作习惯，旧版本的使用方法在新版依旧可以使用。（注：目前只有opmode为ecc和led时要搭配使用opval去赋值）

  2.5.0 display mode添加了对heap和vpu内存监控显示，使用方法为
  ```
  bm-smi --opmode=display_memory_detail
  ```

  同时还添加了对vpu和jpu的利用率显示，使用方法为
  ```
  bm-smi --opmode=display_util_detail
  ```

## 文本模式介绍

bm-smi输出的是一个简单的图形界面，描述了板卡的状态，为了满足部分用户对文本信息的需求（便于用脚本parse部分参数），支持了文本模式（SOC模式不支持文本模式），使用方法如下：

```
bm-smi --start_dev=0 --last_dev=2 --text_format

1684-SC5+ PCIE chip0: 0 000:01:00.0 Active 56C 55C 2W 615mV OFF N/A 0% 75M 550M 550M 3.3A 0MB 7086MB
1684-SC5+ PCIE chip1: 1 000:01:00.1 Active 56C 55C 2W 613mV OFF N/A 0% 75M 550M 550M 4.1A 0MB 7086MB
1684-SC5+ PCIE chip2: 2 000:01:00.2 Active 54C 53C 1W 615mV OFF N/A 0% 75M 550M 550M 2.6A 0MB 7086MB
```

上述命令的输出一行文本信息，分为三个区域：

第一个区域：
```
1684-SC5+ PCIE chip0: 0 000:01:00.0 Active 56C 55C 2W 615mV OFF N/A 0% 75M 550M 550M 3.3A 0MB 7086MB
```

三芯卡上的第0个chip的状态，1684-SC5+ PCIE chip0:
后面的信息依次对应bm-smi中的：TPU Bus-ID Status boardT chipT TPU_P TPU_V ECC CorrectN Tpu-Util Minclk Maxclk Curclk TPU_C Memory-Usage

第二个区域：
```
1684-SC5+ PCIE chip1: 1 000:01:00.1 Active 56C 55C 2W 613mV OFF N/A 0% 75M 550M 550M 4.2A 0MB 7086MB
```

三芯卡上的第1个chip的状态，1684-SC5+ PCIE chip1:
后面的信息依次对应bm-smi中的：TPU Bus-ID Status boardT chipT TPU_P TPU_V ECC CorrectN Tpu-Util Minclk Maxclk Curclk TPU_C Memory-Usage

第三个区域：
```
1684-SC5+ PCIE chip2: 2 000:01:00.2 Active 54C 53C 1W 615mV OFF N/A 0% 75M 550M 550M 2.6A 0MB 7086MB
```

三芯卡上的第2个chip的状态，1684-SC5+ PCIE chip2:
后面的信息依次对应bm-smi中的：TPU Bus-ID Status boardT chipT TPU_P TPU_V ECC CorrectN Tpu-Util Minclk Maxclk Curclk TPU_C Memory-Usage

注意事项：

1、--start_dev=0 --last_dev=2 表示bm-smi中显示的某张卡的第0个和最后1个chip对应的设备号；

2、--start_dev --last_dev --text_format要一起使用。

## bm-smi的help信息

### PCIe模式bm-smi的help信息

```
bm-smi --help

bm-smi: command line brew

usage: bm-smi [--ecc=on/off] [--file=/xx/yy.txt] [--dev=0/1...][--start_dev=x] [--last_dev=y]
[--text_format] [--lms=500] [--recovery] [-loop] [--led=on/off/blink]

ecc:
set ecc status, default is off

file:
the target file to save smi log, default is empty.

dev:
which device to be selected to query, default is all.

start_dev:
the first device to be selected to query, must chip0 of one card, default is invalid.

last_dev:
the last device to be selected to query, default is invalid.

lms:
how many ms of the sample interval, default is 500.

loop:
if -loop (default): smi sample device every lms ms.
if -noloop: smi sample device only once.

recovery:
recovery dev from fault to active status.

text_format:
if true only display attr value from start_dev to last_dev.

led:
pcie card LED status: on/off/blink.

New usage: bm-smi [--opmode=display/ecc/led/recovery][--opval=on/off/...] [--file=/xx/yy.txt]
[--dev=0/1...] [--start_dev=x] [--last_dev=y][--text_format][--lms=500] [-loop]

opmode(default null):
choose different mode,example:display, ecc, led, recovery
display: means open bm-smi window and check info, use like ./bm-smi
ecc: means enable or disable ecc, collocation opval=on/off
led: means modify led status, collocation opval=on/blink/off
recovery: means recovery dev from fault to active status.

opval(default null):
set mode value, use with opmode!
off: for led/ecc
on: for led/ecc
blink: for led

other flags have same usage, Both usage can be used!

   No modules matched: use -help
```

bm-smi在PCIe模式支持上面help列出的所有参数。

### SOC模式bm-smi的help信息

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

## bm-smi用于SOC模式

PCIe 模式bm-smi支持上述所有功能，SOC 模式 bm-smi界面显示支持功能如图2所示，N/A表示该功能不支持；参数只支持opmode=display、file、lms和loop。

SOC模式bm-smi使用方法：登录soc后，直接运行bm-smi即可，

```
bm-smi or bm-smi --opmode=display
```

# proc文件系统介绍

proc文件系统接口在/proc节点下创建设备信息节点，用户通过cat或者编程的方式读取相关节点获取设备温度、版本等信息。

bm-smi侧重于以界面的形式直观显示设备信息，proc文件系统接口侧重于为用户提供编程获取设备信息的接口。

下表列举了proc文件系统可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

| **设备信息** | **PCIe模式** | **SOC模式** |
|-------------|-------------|------------|
| card_num | 支持 | 不支持 |
| chip_num | 支持 | 不支持 |
| chip_num_on_card | 支持 | 不支持 |
| board_power | 支持 | 不支持 |
| board_temp | 支持 | 不支持 |
| chipid | 支持 | 不支持 |
| chip_temp | 支持 | 不支持 |
| dbdf | 支持 | 不支持 |
| dynfreq | 支持 | 不支持 |
| ecc | 支持 | 不支持 |
| maxboardp | 支持 | 不支持 |
| mode | 支持 | 不支持 |
| pcie_cap_speed | 支持 | 不支持 |
| pcie_cap_width | 支持 | 不支持 |
| pcie_link_speed | 支持 | 不支持 |
| pcie_link_width | 支持 | 不支持 |
| pcie_region | 支持 | 不支持 |
| tpuid | 支持 | 不支持 |
| tpu_maxclk | 支持 | 不支持 |
| tpu_minclk | 支持 | 不支持 |
| tpu_freq | 支持 | 不支持 |
| tpu_power | 支持 | 不支持 |
| firmware_info | 支持 | 不支持 |
| sn | 支持 | 不支持 |
| boot_loader_version | 支持 | 不支持 |
| board_type | 支持 | 不支持 |
| driver_version | 支持 | 不支持 |
| board_version | 支持 | 不支持 |
| mcu_version | 支持 | 不支持 |
| versions | 支持 | 不支持 |
| cdma_in_time | 支持 | 不支持 |
| cdma_in_counter | 支持 | 不支持 |
| cdma_out_time | 支持 | 不支持 |
| cdma_out_counter | 支持 | 不支持 |
| tpu_process_time | 支持 | 不支持 |
| completed_api_counter | 支持 | 不支持 |
| send_api_counter | 支持 | 不支持 |
| tpu_volt | 支持 | 不支持 |
| tpu_cur | 支持 | 不支持 |
| fan_speed | 支持 | 不支持 |
| media | 支持 | 不支持 |
| a53_enable | 支持 | 不支持 |
| arm9_cache | 支持 | 不支持 |
| bmcpu_status | 支持 | 不支持 |
| bom_version | 支持 | 不支持 |
| boot_mode | 支持 | 不支持 |
| clk | 支持 | 不支持 |
| ddr_capacity | 支持 | 不支持 |
| dumpreg | 支持 | 不支持 |
| heap | 支持 | 不支持 |
| location | 支持 | 不支持 |
| pcb_version | 支持 | 不支持 |
| pmu_infos | 支持 | 不支持 |
| status | 支持 | 不支持 |
| vddc_power | 支持 | 不支持 |
| vddphy_power | 支持 | 不支持 |
| jpu | 不支持 | 支持 |
| vpu | 不支持 | 支持 |

驱动安装时系统根据板卡数量依次创建/proc/bmsophon/card0…n目录，其中card0目录对应存放第0张板卡的信息，card1目录对应存放第1张板卡信息，依次类推。

在板卡目录下根据当前板卡上设备数量依次创建/proc/bmsophon/cardn/bmsophon0...x目录，其中bmsophonx中的x对应板卡n下设备id为x的设备信息，例如机器上只插了一张SC5+，安装驱动后对应生成/proc/bmsophon/card0，card0目录下会生成bmsophon0/1/2目录，分别存放设备0/1/2的信息。

SOC模式只有JPU和VPU支持 proc文件系统接口，节点分别是/proc/jpuinfo和/proc/vpuinfo。

## 各项参数的含义

SOC模式只有/proc/jpuinfo和/proc/vpuinfo; PCIe 模式proc文件系统中目录和文件节点安排如下：

```
bitmain@weiqiao-MS-7B46:~/work/bm168x$ ls /proc/bmsophon/ -l
total 0
-r--r--r--. 1 root root 0 5月 6 23:06 card_num
-r--r--r--. 1 root root 0 5月 6 23:06 chip_num
-r--r--r--. 1 root root 0 5月 6 23:06 driver_version
dr-xr-xr-x 2 root root 0 5月 6 13:46 card0
```

```
bitmain@weiqiao-MS-7B46:~/work/bm168x$ ls /proc/bmsophon/card0/ -l
total 0
-r--r--r--. 1 root root 0 5月 6 23:06 board_power
-r--r--r--. 1 root root 0 5月 6 23:06 board_temp
-r--r--r--. 1 root root 0 5月 6 23:06 board_type
-r--r--r--. 1 root root 0 5月 6 23:06 board_version
-r--r--r--. 1 root root 0 5月 6 23:06 bom_version
-r--r--r--. 1 root root 0 5月 6 23:06 chipid
-r--r--r--. 1 root root 0 5月 6 23:06 chip_num_on_card
-rw-r--r--. 1 root root 0 5月 6 23:06 fan_speed
-r--r--r--. 1 root root 0 5月 6 23:06 maxboardp
-r--r--r--. 1 root root 0 5月 6 23:06 mode
-r--r--r--. 1 root root 0 5月 6 23:06 pcb_version
-r--r--r--. 1 root root 0 5月 6 23:06 sn
-r--r--r--. 1 root root 0 5月 6 23:06 tpu_maxclk
-r--r--r--. 1 root root 0 5月 6 23:06 tpu_minclk
-r--r--r--. 1 root root 0 5月 6 23:06 versions
dr-xr-xr-x. 2 root root 0 5月 6 23:06 bmsophon0
```

```
bitmain@weiqiao-MS-7B46:~/work/bm168x$ ls /proc/bmsophon/card0/bmsophon0 -l
total 0
-r--r--r--. 1 root root 0 5月 6 23:11 a53_enable
-r--r--r--. 1 root root 0 5月 6 23:11 arm9_cache
-r--r--r--. 1 root root 0 5月 6 23:11 bmcpu_status
-r--r--r--. 1 root root 0 5月 6 23:11 boot_loader_version
-r--r--r--. 1 root root 0 5月 6 23:11 boot_mode
-r--r--r--. 1 root root 0 5月 6 23:11 cdma_in_counter
-r--r--r--. 1 root root 0 5月 6 23:11 cdma_in_time
-r--r--r--. 1 root root 0 5月 6 23:11 cdma_out_counter
-r--r--r--. 1 root root 0 5月 6 23:11 cdma_out_time
-r--r--r--. 1 root root 0 5月 6 23:11 chip_temp
-r--r--r--. 1 root root 0 5月 6 23:11 clk
-r--r--r--. 1 root root 0 5月 6 23:11 completed_api_counter
-r--r--r--. 1 root root 0 5月 6 23:11 dbdf
-r--r--r--. 1 root root 0 5月 6 23:11 ddr_capacity
-rw-r--r--. 1 root root 0 5月 6 23:11 dumpreg
-rw-r--r--. 1 root root 0 5月 6 23:11 dynfreq
-r--r--r--. 1 root root 0 5月 6 23:11 ecc
-r--r--r--. 1 root root 0 5月 6 23:11 heap
-rw-r--r--. 1 root root 0 5月 6 23:11 jpu
-r--r--r--. 1 root root 0 5月 6 23:11 location
-r--r--r--. 1 root root 0 5月 6 23:11 mcu_version
-rw-r--r--. 1 root root 0 5月 6 23:11 media
-r--r--r--. 1 root root 0 5月 6 23:11 pcie_cap_speed
-r--r--r--. 1 root root 0 5月 6 23:11 pcie_cap_width
-r--r--r--. 1 root root 0 5月 6 23:11 pcie_link_speed
-r--r--r--. 1 root root 0 5月 6 23:11 pcie_link_width
-r--r--r--. 1 root root 0 5月 6 23:11 pcie_region
-r--r--r--. 1 root root 0 5月 6 23:11 pmu_infos
-r--r--r--. 1 root root 0 5月 6 23:11 sent_api_counter
-r--r--r--. 1 root root 0 5月 6 23:11 status
-r--r--r--. 1 root root 0 5月 6 23:11 tpu_cur
-rw-r--r--. 1 root root 0 5月 6 23:06 tpu_freq
-r--r--r--. 1 root root 0 5月 6 23:11 tpuid
-r--r--r--. 1 root root 0 5月 6 23:11 tpu_power
-r--r--r--. 1 root root 0 5月 6 23:11 firmware_info
-r--r--r--. 1 root root 0 5月 6 23:11 tpu_process_time
-rw-r--r--. 1 root root 0 5月 6 23:11 tpu_volt
-rw-r--r--. 1 root root 0 5月 6 23:11 vddc_power
-rw-r--r--. 1 root root 0 5月 6 23:11 vddphy_power
```

注：如果PCIe模式使用SC5P，则mcu_version会创建在/proc/bmsophon/card/板卡目录下。

如果使用其他类型板卡，则mcu_version会创建在/proc/bmsophon/card/bmsophon/设备目录下。

## 各项参数的含义和使用方法

### PCIe模式各个设备的详细信息

#### card_num
读写属性：只读
含义：系统板卡数量

#### chip_num
读写属性：只读
含义：系统设备数量

#### chip_num_on_card
读写属性：只读
含义：对应板卡上设备数量

#### board_power
读写属性：只读
含义：板级功耗

#### board_temp
读写属性：只读
含义：板级温度

#### chipid
读写属性：只读
含义：芯片id（0x1684x/0x1684/0x1682）

#### chip_temp
读写属性：只读
含义：芯片温度

#### dbdf
读写属性：只读
含义：domain:bus:dev.function

#### dynfreq
读写属性：读写
含义：使能或者禁止动态tpu调频功能；0/1有效，其他值无效

#### ecc
读写属性：只读
含义：打开或者关闭ECC功能

#### maxboardp
读写属性：只读
含义：最大板级功耗

#### mode
读写属性：只读
含义：工作模式，PCIe/SOC

#### pcie_cap_speed
读写属性：只读
含义：设备支持的PCIe最大速度

#### pcie_cap_width
读写属性：只读
含义：设备支持的PCIe接口最大lane的宽度

#### pcie_link_speed
读写属性：只读
含义：设备的PCIe接口速度

#### pcie_link_width
读写属性：只读
含义：设备的PCIe接口lane宽度

#### pcie_region
读写属性：只读
含义：设备PCIe bar的大小

#### tpuid
读写属性：只读
含义：tpu的ID（0/1/2/3……）

#### tpu_maxclk
读写属性：只读
含义：tpu的最大工作频率

#### tpu_minclk
读写属性：只读
含义：tpu的最小工作频率

#### tpu_freq
读写属性：读写
含义：tpu的工作频率，可通过写入参数来改变频率，写入前应向dynfreq写入0来关闭动态tpu调频，示例如下：

```
sudo -s
echo 0 > /proc/bmsophon/card0/bmsophon0/dynfreq
echo 750 > /proc/bmsophon/card0/bmsophon0/tpu_freq
```

#### tpu_power
读写属性：只读
含义：tpu的瞬时功率

#### firmware_info
读写属性：只读
含义：firmware的版本信息，包括commit id和编译时间

#### sn
读写属性：只读
含义：板卡产品编号

#### boot_loader_version
读写属性：只读
含义：spi flash 中的bootloader 版本号

#### board_type
读写属性：只读
含义：板卡类型

#### driver_version
读写属性：只读
含义：驱动的版本号

#### board_version
读写属性：只读
含义：板卡硬件的版本号

#### mcu_version
读写属性：只读
含义：mcu软件版本号

#### versions
读写属性：只读
含义：板卡软硬件版本的集合

#### cdma_in_time
读写属性：只读
含义：cdma 从host搬数据到板卡消耗的总时间

#### cdma_in_counter
读写属性：只读
含义：cdma 从host搬数据到板卡的总次数

#### cdma_out_time
读写属性：只读
含义：cdma 从板卡搬数据到host消耗的总时间

#### cdma_out_counter
读写属性：只读
含义：cdma 从板卡搬数据到host的总次数

#### tpu_process_time
读写属性：只读
含义：tpu 处理过程中消耗的时间

#### completed_api_counter
读写属性：只读
含义：已完成api的次数

#### send_api_counter
读写属性：只读
含义：已发送api的次数

#### tpu_volt
读写属性：读写
含义：tpu的电压，可通过写入参数来改变电压

#### tpu_cur
读写属性：只读
含义：tpu 电流

# Tpu驱动sysfs文件系统介绍

sysfs文件系统接口用来获取TPU的利用率等信息。

下表列举了Tpu驱动sysfs文件系统可以获取的设备信息以及在PCIe和SOC模式下的支持情况：

| **设备信息** | **PCIe模式** | **SOC模式** |
|-------------|-------------|-------------|
| npu_usage | 支持 | 支持 |
| npu_usage_enable | 支持 | 支持 |
| npu_usage_interval | 支持 | 支持 |

驱动安装后，会为每个设备创建一些属性，用于查看和修改一些参数。这些属性所在的位置：

- PCIe模式：/sys/class/bm-sophon/bm-sophon0/device
- SOC模式：/sys/class/bm-tpu/bm-tpu0/device

## 各项参数的含义

下面逐一介绍每个部分代表的含义。

- npu_usage：Tpu（npu）在一段时间内（窗口宽度）处于工作状态的百分比。
- npu_usage_enable：是否使能统计npu利用率，默认使能。
- npu_usage_interval：统计npu利用率的时间窗口宽度，单位ms，默认500ms。取值范围[200,2000]。

## Tpu驱动sysfs文件系统接口的具体使用方法

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

- jpuinfo
  - 读写属性：只读
  - JPU loadbalance：记录JPU0-JPU1(1684x),JPU0-JPU3(1684)编码/解码次数，JPU*为芯片内部的JPEG编解码器，取值范围：0~2147483647

- vpuinfo
  - 读写属性：只读
  - id：vpu core的编号，取值范围：0~2(1684x), 0-4(1684)
  - link_num：编/解码路数，取值范围：0~32

## 其他设备信息

- fan_speed
  - 读写属性：只读
  - 含义：duty 风扇调速pwm 占空比，fan_speed 风扇实际转速

- media
  - 读写属性：只读
  - total_mem_size：vpu和jpu使用内存总大小
  - used_mem_size：vpu和jpu正在使用的内存
  - free_mem_size：空闲内存
  - id：vpu core的编号
  - link_num：编/解码路数

- a53_enable
  - 读写属性：只读
  - 含义：a53使能状态

- arm9_cache
  - 读写属性：只读
  - 含义：arm9的cache的使能状态

- bmcpu_status
  - 读写属性：只读
  - 含义：bmcpu的状态

- bom_version
  - 读写属性：只读
  - 含义：bom的版本号

- boot_mode
  - 读写属性：只读
  - 含义：启动方式

- clk
  - 读写属性：只读
  - 含义：各个模块的时钟

- ddr_capacity
  - 读写属性：只读
  - 含义：ddr的容量

- dumpreg
  - 读写属性：读写
  - 含义：转存寄存器，输入1转存到tpu寄存器，输入2转存到gdma寄存器

- heap
  - 读写属性：只读
  - 含义：显示各个heap的大小

- location
  - 读写属性：只读
  - 含义：显示当前位于哪个设备之上

- pcb_version
  - 读写属性：只读
  - 含义：pcb的版本号

- pmu_infos
  - 读写属性：只读
  - 含义：更详细的电流电压信息

- status
  - 读写属性：只读
  - 含义：板卡状态

- vddc_power
  - 读写属性：只读
  - 含义：vddc功率

- vddphy_power
  - 读写属性：只读
  - 含义：vddphy功率

# 使用 Docker 搭建测试环境

可使用 Docker 搭建 libsophon 的测试环境，这里介绍环境的搭建流程和使用方法。

进行此部分操作前请参照安装libsophon中内容在 host 端安装 sophon-driver！

## Docker 测试环境搭建

### 安装 Docker

参考官网教程进行安装：

```
# 卸载 docker
sudo apt-get remove docker docker.io containerd runc

# 安装依赖
sudo apt-get update
sudo apt-get install \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

# 获取密钥
sudo mkdir -p /etc/apt/keyrings
curl -fsSL \
    https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o docker.gpg && \
    sudo mv -f docker.gpg /etc/apt/keyrings/

# 添加 docker 软件包
echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 docker
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 构建测试镜像及容器

#### 构建镜像

使用 dockerfile 构建测试所需的 Docker 镜像，dockerfile 位于 libsophon 文件夹下。构建镜像前请检查系统时间是否准确，错误的系统时间会导致构建过程中更新 package list 时证书验证失败。

```
# 替换以下 path/to/libsophon 为实际 libsophon 路径
cd path/to/libsophon
sudo docker build --platform linux/arm64/v8 -t image_name:image_version -f libsophon_dockerfile .
```

以上 `image_name` 和 `image_version` 可自定义。

运行完以上命令后，可运行 `docker images` 命令核对构建结果，命令输出应如下：

```
$ sudo docker images
REPOSITORY   TAG               IMAGE ID     CREATED          SIZE
image_name      image_version  image_id        create_time        1.74GB
```

以上内容中 `image_name` 与 `image_version` 应与构建时设置内容一致，`image_id` 与 `create_time` 应与实际情况相符合。

#### 创建容器

在 Docker 容器中进行测试需要依赖 libsophon 动态库，依赖可分以下两种方法建立：

1. 在host端安装sophon-libsophon和sophon-libsophon-dev，然后通过文件映射将动态库映射进 Docker 容器中；

```
# sophon-libsophon 和 sophon-libsophon-dev 安装在 host 端
sudo docker run \
    -td \
    --privileged=true \
    -v /opt/sophon:/opt/sophon \
    -v /etc/profile.d:/etc/profile.d \
    -v /etc/ld.so.conf.d:/etc/ld.so.conf.d \
    --name container_name image_name:image_version bash
```

2. 直接在 Docker 容器中安装 sophon-libsophon 和 sophon-libsophon-dev。

```
# 在 Docker 容器中安装 sophon-libsophon 和 sophon-libsophon-dev
sudo docker run \
    -td \
    --privileged=true \
    --name container_name image_name:image_version bash
```

通过以上两种方法建立动态依赖前请首先前请参照安装libsophon中内容在 host 端安装 sophon-driver，安装 sophon-libsophon 和 sophon-libsophon-dev 参考安装libsophon中对应内容。

以上 `image_name` 和 `image_version` 对应创建镜像时的内容，`container_name` 可自定义。

## 测试环境生效

为确保已经构建的 Docker 环境能正常使用 libsophon，进入 Docker 容器运行以下命令：

```
# 进入 Docker 容器
sudo docker exec -it container_name bash

# 在 Docker 容器中运行此命令以确保 libsophon 动态库能被找到
ldconfig

# 在 Docker 容器中运行此命令以确保 libsophon 工具可使用
for f in /etc/profile.d/*sophon*; do source $f; done
```

运行以上命令后可运行 `bm-smi` 命令以检查是否可正常使用 libsophon，命令输出应与bm-smi使用说明中对应内容相符。

# 带外管理接口说明

## SMBUS 协议接口定义

### 命令组成

先写 1 byte 的 CMD 到 i2c slave，再读取 n byte 数据。以下为读取 CHIP0 芯片温度的例子：

```
#先往 slave 地址为 0x60 的设备写数据 0x0
i2c write 0x60 (slave addr) 0x0 (cmd)
#再从 slave 地址为 0x60 的设备读取 1 byte 数据
i2c read 0x60 (slave addr) 0x1 (n byte)
```

## SC5 系列板卡带外管理接口

### 说明

服务器厂商 BMC 控制：

- SC5 系列多芯卡 Slave 地址 CHIP0 为 0x60，CHIP1 为 0x61，CHIP2 为 0x62。
- 返回int类型数据时候按照高字节在前顺序发送（例如int类型数为 0x16841e30，返回顺序为 0x16, 0x84, 0x1e, 0x30）。

### SC5+ MCU 接口命令

| 含义 | 地址 | 属性 | 说明 |
|-----|-----|-----|------|
| 芯片温度 | 0x00 | RO | unsigned byte，单位：摄氏度 |
| 单板温度 | 0x01 | RO | unsigned byte，单位：摄氏度 |
| 单板功耗 | 0x02 | RO | unsigned byte，单位：瓦 |
| 风扇速度占比 | 0x03 | RO | unsigned byte，0xff表示无风扇 |
| Vendor ID | 0x10 | RO | unsigned int；[31:16]:Device ID 0x1684；[15:0]:Vendor ID 0x1e30 |
| 硬件版本 | 0x14 | RO | unsigned byte |
| 固件版本 | 0x18 | RO | unsigned int；[7:0]小版本号；[15:8]主版本号；[31:16]chip版本号 |
| 板卡种类 | 0x1c | RO | unsigned byte（代表板卡种类，sc5+是7） |
| Sub Vendor ID | 0x20 | RO | unsigned int；[15:0]:sub Vendor ID 0x0；[31:16]:sub system ID 0x0 |

备注：

- 单板功耗只能从 0x60 的 0x02 地址读取
- unsigned int 表示该地址有效数据4个字节大小
- unsigned byte 表示该地址有效数据1个字节大小

## SC7 系列板卡带外管理接口

### 说明

服务器厂商 BMC 控制：

- SC7 系列多芯卡 Slave 地址为 0x60，CHIP1 为 0x61，CHIP2 为 0x62，依此类推，CHIP7 为 0x67。
- 返回int类型数据时候按照高字节在前顺序发送（例如int类型数为 0x16861f1c，返回顺序为 0x16, 0x86, 0x1f, 0x1c）。

### SC7PRO MCU 接口命令

| 含义 | 地址 | 属性 | 说明 |
|-----|-----|-----|------|
| 芯片温度 | 0x00 | RO | unsigned byte，单位：摄氏度 |
| 单板温度 | 0x01 | RO | unsigned byte，单位：摄氏度 |
| 单板功耗 | 0x02 | RO | unsigned byte，单位：瓦 |
| 风扇速度占比 | 0x03 | RO | unsigned byte，0xff表示无风扇 |
| Vendor ID | 0x10 | RO | unsigned int；[31:16]:Device ID 0x1686；[15:0]:Vendor ID 0x1f1c |
| 硬件版本 | 0x14 | RO | unsigned byte |
| 固件版本 | 0x18 | RO | unsigned int；[7:0]小版本号；[15:8]主版本号；[31:16]chip版本号 |
| 板卡种类 | 0x1c | RO | unsigned byte（代表板卡种类，sc7pro是0x21） |
| Sub Vendor ID | 0x20 | RO | unsigned int；[15:0]:sub Vendor ID 0x0；[31:16]:sub system ID 0x0 |
| SN ID | 0x24 | RO | 产品序列号 |
| MCU Version | 0x36 | RO | unsigned byte；MCU版本号：0 |

备注：

- 单板功耗只能从 0x60 的 0x02 地址读取

# Bmlib的基本概念和功能

基于算能神经网络加速芯片设计的SDK的简单功能框图如下：

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

我们的神经网络加速设备，无论是在PCIE模式，还是SOC模式，安装完tpu的驱动后，会成为一个标准的字符设备。上层用户进程如果要使用这个设备，需要在这个设备上创建一个handle句柄。

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

上图以PCIE模式介绍memory的种类，其中host可以是PC机/服务器，PCIE板卡就是SC5系列板卡。Host端的memory我们称之system memory，PCIE板卡上的memory我们称之为global memory，或者device memory。BM1684芯片中有专门的DMA硬件单元在system memory和global memory之间搬运数据。

## Api的概念和同步

Host这端的软件如果想让tpu完成一个任务，需要向tpu发送一个"api"，类似于一个命令。请注意发送api的函数和api的执行完成是异步的，所以host这端的软件还需要调用一个sync函数类等到api的真正完成。

目前发送api的动作，都已经封在bmcv/bmrt功能库中了，客户无法直接发送api，只能通过调用bmcv/bmrt的接口发送api。

调用完bmcv/bmrt的接口发送api后，是否需要调用sync函数等待api的完成，请参考bmcv/bmrt文档，bmcv/bmrt的接口可能已经将sync函数也封装在bmcv/bmrt的接口函数中了，这样bmcv/bmrt的接口函数返回后，api已经完成了。

## Profile接口

Profile接口用于获取tpu处理api花费的时间，这个时间是从tpu开始工作后一直累加的（如果有不断的api得到处理），如果系统中只有一个进程使用tpu设备，我们可以通过计算调用api前后profile数据的差值来得到api的处理时间。

## A53的使能

在PCIE模式下，我们提供了一些接口用来启动BM1684中A53 core，并让他们完成一些加速任务。

## Power控制

我们提供了接口用于获取和设置tpu的工作频率，用户可以自己定义一些自己的功耗控制策略。

## 杂项信息接口

用于获取板卡的信息和运行过程中的统计信息。目前包括memory总量和使用量，tpu的利用率

# bmlib详细接口介绍

## 设备handle的创建和销毁

### bm_dev_getcount

函数原型：bm_status_t bm_dev_getcount(int \*count)

函数作用：获取当前系统中，存在多少个sophon设备，如果获取的设备个数为N，则devid的合法取值为[0,N-1]。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| count | 输出 | 用于存放sophon设备个数的指针 |

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

### bm_mem_get_type_u64

函数原型：bm_mem_type_t bm_mem_get_type_u64(struct bm_mem_desc_u64 mem);

函数作用：获取一块u64 memory的种类

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

### bm_mem_get_device_addr_u64

函数原型：unsigned long long bm_mem_get_device_addr_u64(struct bm_mem_desc_u64 mem);

函数作用：获取device类型的u64 memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem | 输入 | 被查询的memory |

返回值：返回device memory的地址，64bit的一个无符号数字

# bm_mem_set_device_addr

函数原型：`void bm_mem_set_device_addr(struct bm_mem_desc *pmem, unsigned long long addr);`

函数作用：设置一个device类型 memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| addr   | 输入      | memory被设置的地址 |

返回值：无

# bm_mem_set_device_addr_u64

函数原型：`void bm_mem_set_device_addr_u64(struct bm_mem_desc_u64* pmem, unsigned long long addr);`

函数作用：设置一个device类型u64 memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| addr   | 输入      | memory被设置的地址 |

返回值：无

# bm_mem_get_device_size

函数原型：`unsigned int bm_mem_get_device_size(struct bm_mem_desc mem);`

函数作用：获取一块device类型的memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem    | 输入      | 被查询的memory |

返回值：返回memory大小，32位的无符号数

# bm_mem_get_device_size_u64

函数原型：`unsigned long long bm_mem_get_device_size_u64(struct bm_mem_desc_u64 mem);`

函数作用：获取一块device类型的u64 memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem    | 输入      | 被查询的memory |

返回值：返回memory大小，32位的无符号数

# bm_mem_set_device_size

函数原型：`void bm_mem_set_device_size(struct bm_mem_desc *pmem, unsigned int size);`

函数作用：设置一块device类型的memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| size   | 输入      | memory的大小，单位是byte |

返回值：无

# bm_mem_set_device_size_u64

函数原型：`void bm_mem_set_device_size_u64(struct bm_mem_desc_u64* pmem, unsigned long long size);`

函数作用：设置一块device类型的memory的大小

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| size   | 输入      | memory的大小，单位是byte |

返回值：无

# bm_set_device_mem

函数原型：`void bm_set_device_mem(bm_device_mem_t *pmem, unsigned int size, unsigned long long addr);`

函数作用：填充一个device类型的memory的大小和地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| size   | 输入      | memory的大小，单位是byte |
| addr   | 输入      | memory的地址 |

返回值：无

# bm_set_device_mem_u64

函数原型：`void bm_set_device_mem_u64(bm_device_mem_u64_t* pmem, unsigned long long size, unsigned long long addr);`

函数作用：填充一个device类型的memory的大小和地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| size   | 输入      | memory的大小，单位是byte |
| addr   | 输入      | memory的地址 |

返回值：无

# bm_mem_from_device

函数原型：`bm_device_mem_t bm_mem_from_device(unsigned long long device_addr, unsigned int len);`

函数作用：根据地址和大小构建一个bm_device_mem_t类型的结构体

参数介绍：

| 参数名     | 输入/输出 | 说明 |
|------------|-----------|------|
| device_addr | 输入      | memory的地址 |
| len        | 输入      | memory的大小，单位是byte |

返回值：一个bm_device_mem_t类型的结构体

# bm_mem_from_device_u64

函数原型：`bm_device_mem_u64_t bm_mem_from_device_u64(unsigned long long device_addr, unsigned long long len);`

函数作用：根据地址和大小构建一个bm_device_mem_t类型的结构体

参数介绍：

| 参数名     | 输入/输出 | 说明 |
|------------|-----------|------|
| device_addr | 输入      | memory的地址 |
| len        | 输入      | memory的大小，单位是byte |

返回值：一个bm_device_mem_t类型的结构体

# bm_mem_get_system_addr

函数原型：`void *bm_mem_get_system_addr(struct bm_mem_desc mem);`

函数作用：获取system类型memory的地址

参数介绍：mem，被查询的memory

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem    | 输入      | 被查询的memory |

返回值：返回一个memory的地址

# bm_mem_get_system_addr_u64

函数原型：`void *bm_mem_get_system_addr_u64(struct bm_mem_desc_u64 mem);`

函数作用：获取system类型memory的地址

参数介绍：mem，被查询的memory

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| mem    | 输入      | 被查询的memory |

返回值：返回一个memory的地址

# bm_mem_set_system_addr

函数原型：`void bm_mem_set_system_addr(struct bm_mem_desc *pmem, void *addr);`

函数作用：设置一个system类型memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| addr   | 输入      | system 地址指针 |

返回值：无

# bm_mem_set_system_addr_u64

函数原型：`void bm_mem_set_system_addr_u64(struct bm_mem_desc_u64* pmem, void *addr);`

函数作用：设置一个system类型memory的地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| pmem   | 输入/输出 | 被设置的memory的指针 |
| addr   | 输入      | system 地址指针 |

返回值：无

# bm_mem_from_system

函数原型：`bm_system_mem_t bm_mem_from_system(void *system_addr);`

函数作用：根据一个system指针构建一个bm_system_mem_t类型的结构体

参数介绍：

| 参数名      | 输入/输出 | 说明 |
|-------------|-----------|------|
| system_addr | 输入      | system 地址指针 |

返回值：一个bm_system_mem_t类型的结构体

# bm_mem_from_system_u64

函数原型：`bm_system_mem_u64_t bm_mem_from_system_u64(void *system_addr);`

函数作用：根据一个system指针构建一个bm_system_mem_t类型的结构体

参数介绍：

| 参数名      | 输入/输出 | 说明 |
|-------------|-----------|------|
| system_addr | 输入      | system 地址指针 |

返回值：一个bm_system_mem_t类型的结构体

# Global memory的申请和释放

## bm_mem_null

**函数原型**：`bm_device_mem_t bm_mem_null(void);`

**函数作用**：返回一个类型非法的bm memory结构体

**参数介绍**：无

**返回值**：一个bm_device_mem_t类型的结构体

## bm_malloc_neuron_device

**函数原型**：`bm_status_t bm_malloc_neuron_device(bm_handle_t handle, bm_device_mem_t *pmem, int n, int c, int h, int w);`

**函数作用**：根据batch的形状信息申请一块device类型的memory，每个神经元的大小为一个FP32(4 bytes)

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| n/c/h/w | 输入 | batch 的形状 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_neuron_device_u64

**函数原型**：`bm_malloc_neuron_device_u64(bm_handle_t handle, bm_device_mem_u64_t *pmem, unsigned long long n, unsigned long long c, unsigned long long h, unsigned long long w);`

**函数作用**：根据batch的形状信息申请一块device类型的memory，每个神经元的大小为一个FP32(4 bytes)

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| n/c/h/w | 输入 | batch 的形状 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_dword

**函数原型**：`bm_status_t bm_malloc_device_dword(bm_handle_t handle, bm_device_mem_t *pmem, int count);`

**函数作用**：分配count个DWORD（4 bytes）大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| count | 输入 | 需要分配的dword的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_dword_u64

**函数原型**：`bm_status_t bm_malloc_device_dword_u64(bm_handle_t handle, bm_device_mem_u64_t *pmem, unsigned long long count);`

**函数作用**：分配count个DWORD（4 bytes）大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| count | 输入 | 需要分配的dword的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte

**函数原型**：`bm_status_t bm_malloc_device_byte(bm_handle_t handle, bm_device_mem_t *pmem, unsigned int size);`

**函数作用**：分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte_u64

**函数原型**：`bm_status_t bm_malloc_device_byte_u64(bm_handle_t handle, bm_device_mem_u64_t *pmem, unsigned long long size);`

**函数作用**：分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte_heap

**函数原型**：`bm_status_t bm_malloc_device_byte_heap(bm_handle_t handle, bm_device_mem_t *pmem, int heap_id, unsigned int size);`

**函数作用**：在指定的HEAP上分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id | 输入 | 所指定分配GMEM的HEAP（0/1/2） |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte_heap_u64

**函数原型**：`bm_malloc_device_byte_heap_u64(bm_handle_t handle, bm_device_mem_u64_t *pmem, int heap_id, unsigned long long size);`

**函数作用**：在指定的HEAP上分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id | 输入 | 所指定分配GMEM的HEAP（0/1/2） |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte_heap_mask

**函数原型**：`bm_status_t bm_malloc_device_byte_heap_mask(bm_handle_t handle, bm_device_mem_t *pmem, int heap_id_mask, unsigned int size);`

**函数作用**：在指定的一个或多个HEAP上分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id_mask | 输入 | 指定分配GMEM的HEAP id 的mask，每个bit代表一个HEAP，设置为1代表可以从这个HEAP分配，为0代表不能从这个HEAP分配，最低位bit0代表heap0，依次增加 |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_byte_heap_mask_u64

**函数原型**：`bm_status_t bm_malloc_device_byte_heap_mask_u64(bm_handle_t handle, bm_device_mem_u64_t *pmem, int heap_id_mask, unsigned long long size);`

**函数作用**：在指定的一个或多个HEAP上分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| pmem | 输出 | 分配出device memory的指针 |
| heap_id_mask | 输入 | 指定分配GMEM的HEAP id 的mask，每个bit代表一个HEAP，设置为1代表可以从这个HEAP分配，为0代表不能从这个HEAP分配，最低位bit0代表heap0，依次增加 |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

## bm_malloc_device_mem

**函数原型**：`bm_status_t bm_malloc_device_mem(bm_handle_t handle, unsigned long long *paddr, int heap_id, unsigned long long size);`

**函数作用**：在指定的HEAP上分配指定字节个数大小的device类型的memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| paddr | 输出 | 分配出device memory的地址 |
| heap_id | 输入 | 所指定分配GMEM的HEAP（0/1/2） |
| size | 输入 | 需要分配的byte的个数 |

**返回值**：BM_SUCCESS代表分配成功；其他错误码代表分配失败

# bm_malloc_device_mem_mask

函数原型：`bm_status_t bm_malloc_device_mem_mask(bm_handle_t handle, unsigned long long *paddr, int heap_id_mask, unsigned long long size)`

函数作用：在指定的HEAP上分配指定字节个数大小的device类型的memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| paddr | 输出 | 分配出device memory的地址 |
| heap_id_mask | 输入 | 指定分配GMEM的HEAP id 的mask，每个bit代表一个HEAP，设置为1代表可以从这个HEAP分配，为0代表不能从这个HEAP分配，最低位bit0代表heap0，依次增加 |
| size | 输入 | 需要分配的byte的个数 |

返回值：BM_SUCCESS代表分配成功；其他错误码代表分配失败

# bm_free_device_mem

函数原型：`void bm_free_device_mem(bm_handle_t ctx, unsigned long long paddr)`

函数作用：释放一块device类型的memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| ctx | 输入 | 设备句柄 |
| paddr | 输入 | 要释放的device memory地址 |

# bm_free_device

函数原型：`void bm_free_device(bm_handle_t handle, bm_device_mem_t mem)`

函数作用：释放一块device类型的memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| mem | 输入 | 要释放的device memory |

返回值：无

# bm_free_device_u64

函数原型：`void bm_free_device_u64(bm_handle_t handle, bm_device_mem_u64_t mem)`

函数作用：释放一块device类型的memory

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| mem | 输入 | 要释放的device memory |

返回值：无

# bm_gmem_arm_reserved_request

函数原型：`unsigned long long bm_gmem_arm_reserved_request(bm_handle_t handle)`

函数作用：获取为arm926保留的gmem的起始地址

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：为arm926保留的gmem的起始地址（一个绝对地址）

# bm_gmem_arm_reserved_release

函数原型：`void bm_gmem_arm_reserved_release(bm_handle_t handle)`

函数作用：释放为arm926保留的gmem

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

返回值：无

# 数据在host和global memory之间的搬运

## bm_memcpy_s2d

函数原型：`bm_status_t bm_memcpy_s2d(bm_handle_t handle, bm_device_mem_t dst, void *src)`

函数作用：拷贝system内存到device类型的内存中

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_u64

函数原型：`bm_status_t bm_memcpy_s2d_u64(bm_handle_t handle, bm_device_mem_u64_t dst, void *src)`

函数作用：拷贝system内存到device类型的内存中

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_partial_offset

函数原型：`bm_status_t bm_memcpy_s2d_partial_offset(bm_handle_t handle, bm_device_mem_t dst, void *src, unsigned int size, unsigned int offset)`

函数作用：拷贝system内存到device类型内存，指定长度和device内存的起始地址offset，效果是从src拷贝size长度的数据到(dst起始地址+offset)这个位置上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_partial_offset_u64

函数原型：`bm_status_t bm_memcpy_s2d_partial_offset_u64(bm_handle_t handle, bm_device_mem_u64_t dst, void *src, unsigned long long size, unsigned long long offset)`

函数作用：拷贝system内存到device类型内存，指定长度和device内存的起始地址offset，效果是从src拷贝size长度的数据到(dst起始地址+offset)这个位置上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_partial

函数原型：`bm_status_t bm_memcpy_s2d_partial(bm_handle_t handle, bm_device_mem_t dst, void *src, unsigned int size)`

函数作用：拷贝system内存到device类型内存，指定长度；效果是从src拷贝size长度的数据到dst起始地址这个位置上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_partial_u64

函数原型：`bm_status_t bm_memcpy_s2d_partial_u64(bm_handle_t handle, bm_device_mem_u64_t dst, void *src, unsigned long long size)`

函数作用：拷贝system内存到device类型内存，指定长度；效果是从src拷贝size长度的数据到dst起始地址这个位置上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| size | 输入 | 拷贝的长度 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_s2d_stride

函数原型：`bm_status_t bm_memcpy_s2d_stride(bm_handle_t handle, bm_device_mem_t dst, void *src, struct stride_cfg *stride)`

函数作用：拷贝system内存到device类型内存；效果是从src拷贝stride->width*stride->height长度的有效数据到dst起始地址这个位置上,shape由stride->src_width变为stride->dst_height，高度保持不变。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标device memory的结构体 |
| src | 输入 | 指向system内存的指针 |
| stride | 输入 | stride配置结构体 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_d2s

函数原型：`bm_status_t bm_memcpy_d2s(bm_handle_t handle, void *dst, bm_device_mem_t src)`

函数作用：拷贝device类型内存到system内存

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

## bm_memcpy_d2s_u64

函数原型：`bm_status_t bm_memcpy_d2s_u64(bm_handle_t handle, void *dst, bm_device_mem_u64_t src)`

函数作用：拷贝device类型内存到system内存

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2s_partial_offset

函数原型：`bm_status_t bm_memcpy_d2s_partial_offset(bm_handle_t handle, void *dst, bm_device_mem_t src, unsigned int size, unsigned int offset)`

函数作用：拷贝device类型内存到system内存，指定大小，和device memory端的offset，效果是从device memory起始地址+offset拷贝size字节数据到dst上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2s_partial_offset_u64

函数原型：`bm_status_t bm_memcpy_d2s_partial_offset_u64(bm_handle_t handle, void *dst, bm_device_mem_u64_t src, unsigned long long size, unsigned long long offset)`

函数作用：拷贝device类型内存到system内存，指定大小，和device memory端的offset，效果是从device memory起始地址+offset拷贝size字节数据到dst上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |
| offset | 输入 | 本次拷贝在device memory端相对于这块device memory起始地址的offset |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2s_partial

函数原型：`bm_status_t bm_memcpy_d2s_partial(bm_handle_t handle, void *dst, bm_device_mem_t src, unsigned int size)`

函数作用：拷贝device类型内存到system内存，指定大小；效果是从device memory起始地址拷贝size字节数据到dst上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2s_partial_u64

函数原型：`bm_status_t bm_memcpy_d2s_partial_u64(bm_handle_t handle, void *dst, bm_device_mem_u64_t src, unsigned long long size)`

函数作用：拷贝device类型内存到system内存，指定大小；效果是从device memory起始地址拷贝size字节数据到dst上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 指向system内存的指针 |
| src | 输入 | 源device memory的结构体 |
| size | 输入 | 拷贝的长度（单位为byte） |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2s_stride

函数原型：`bm_status_t bm_memcpy_d2s_stride(bm_handle_t handle, void *dst, bm_device_mem_t src, struct stride_cfg *stride)`

函数作用：拷贝system内存到device类型内存；效果是从src拷贝stride->width*stride->height长度的有效数据到dst起始地址这个位置上,shape由stride->src_width变为stride->dst_height，高度保持不变。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dst | 输入 | 目标system memory的结构体 |
| src | 输入 | 指向device内存的指针 |
| stride | 输入 | stride配置结构体 |

返回值：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_mem_convert_system_to_device_neuron

函数原型：`bm_status_t bm_mem_convert_system_to_device_neuron(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int n, int c, int h, int w)`

函数作用：按照batch形状申请一块device类型的memory（一个神经元大小为FP32(4 bytes)）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_convert_system_to_device_neuron_u64

函数原型：`bm_status_t bm_mem_convert_system_to_device_neuron_u64(bm_handle_t handle, struct bm_mem_desc_u64 *dev_mem, struct bm_mem_desc_u64 sys_mem, bool need_copy, int n, int c, int h, int w)`

函数作用：按照batch形状申请一块device类型的memory（一个神经元大小为FP32(4 bytes)）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_convert_system_to_device_neuron_byte

函数原型：`bm_status_t bm_mem_convert_system_to_device_neuron_byte(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int n, int c, int h, int w)`

函数作用：按照batch形状申请一块device类型的memory（一个神经元大小为1 bytes）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_convert_system_to_device_neuron_byte_u64

函数原型：`bm_status_t bm_mem_convert_system_to_device_neuron_byte_u64(bm_handle_t handle, struct bm_mem_desc_u64 *dev_mem, struct bm_mem_desc_u64 sys_mem, bool need_copy, int n, int c, int h, int w)`

函数作用：按照batch形状申请一块device类型的memory（一个神经元大小为1 bytes）,按需将一段system memory内存copy到这块device memory上。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dev_mem | 输出 | 指向分配出的device memory的指针 |
| sys_mem | 输入 | system类型的memory结构体 |
| need_copy | 输入 | 是否需要将system内存copy到新分配的这块device memory上 |
| n/c/h/w | 输入 | batch的形状 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_convert_system_to_device_coeff

函数原型：`bm_status_t bm_mem_convert_system_to_device_coeff(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int coeff_count)`

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

# bm_mem_convert_system_to_device_coeff_u64

函数原型：`bm_status_t bm_mem_convert_system_to_device_coeff_u64(bm_handle_t handle, struct bm_mem_desc_u64 *dev_mem, struct bm_mem_desc_u64 sys_mem, bool need_copy, int coeff_count)`

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

函数原型：`bm_status_t bm_mem_convert_system_to_device_coeff_byte(bm_handle_t handle, struct bm_mem_desc *dev_mem, struct bm_mem_desc sys_mem, bool need_copy, int coeff_count)`

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

# bm_mem_convert_system_to_device_coeff_byte_u64

函数原型：`bm_status_t bm_mem_convert_system_to_device_coeff_byte_u64(bm_handle_t handle, struct bm_mem_desc_u64 *dev_mem, struct bm_mem_desc_u64 sys_mem, bool need_copy, int coeff_count)`

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

# bm_memcpy_d2d

函数原型：`bm_status_t bm_memcpy_d2d(bm_handle_t handle, bm_device_mem_t dst, int dst_offset, bm_device_mem_t src, int src_offset, int len)`

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

# bm_memcpy_d2d_with_core

**函数原型**：`bm_status_t bm_memcpy_d2d_with_core(bm_handle_t handle, bm_device_mem_t dst, int dst_offset, bm_device_mem_t src, int src_offset, int len, int core_id)`

**函数作用**：指定使用第core_id个GDMA，将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+src_offset)拷贝len个DWORD（4字节）的数据到(dst起始地址+dst_offset)

**参数介绍**：

| 参数名     | 输入/输出 | 说明                                  |
|------------|-----------|---------------------------------------|
| handle     | 输入      | 设备句柄                              |
| dst        | 输入      | 目标device memory结构体               |
| dst_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| src        | 输入      | 源device memory结构体                 |
| src_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| len        | 输入      | 数据copy长度，单位是DWORD（4字节）    |
| core_id    | 输入      | 搬运的GDMA设备id                      |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_byte

**函数原型**：`bm_status_t bm_memcpy_d2d_byte(bm_handle_t handle, bm_device_mem_t dst, size_t dst_offset, bm_device_mem_t src, size_t src_offset, size_t size)`

**函数作用**：将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+src_offset)拷贝len个字节的数据到(dst起始地址+dst_offset)

**参数介绍**：

| 参数名     | 输入/输出 | 说明                                  |
|------------|-----------|---------------------------------------|
| handle     | 输入      | 设备句柄                              |
| dst        | 输入      | 目标device memory结构体               |
| dst_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| src        | 输入      | 源device memory结构体                 |
| src_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| size       | 输入      | 数据copy长度，单位是字节              |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_byte_with_core

**函数原型**：`bm_status_t bm_memcpy_d2d_byte_with_core(bm_handle_t handle, bm_device_mem_t dst, size_t dst_offset, bm_device_mem_t src, size_t src_offset, size_t size, int core_id)`

**函数作用**：指定使用第core_id个GDMA，将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+src_offset)拷贝len个字节的数据到(dst起始地址+dst_offset)

**参数介绍**：

| 参数名     | 输入/输出 | 说明                                  |
|------------|-----------|---------------------------------------|
| handle     | 输入      | 设备句柄                              |
| dst        | 输入      | 目标device memory结构体               |
| dst_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| src        | 输入      | 源device memory结构体                 |
| src_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| size       | 输入      | 数据copy长度，单位是字节              |
| core_id    | 输入      | 搬运的GDMA设备id                      |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_stride

**函数原型**：`bm_status_t bm_memcpy_d2d_stride(bm_handle_t handle, bm_device_mem_t dst, int dst_stride, bm_device_mem_t src, int src_stride, int count, int format_size)`

**函数作用**：将一块device类型的memory拷贝到另外一块device类型的memory，指定目的、源数据的stride，数据的个数，以及数据的类型字节大小；效果是从src起始地址按src_stride为间隔大小拷贝count个元素大小为format_size字节的数据到dst起始地址，以dst_stride为间隔大小存储。

**参数介绍**：

| 参数名      | 输入/输出 | 说明                                                                         |
|-------------|-----------|------------------------------------------------------------------------------|
| handle      | 输入      | 设备句柄                                                                     |
| dst         | 输入      | 目标device memory结构体                                                      |
| dst_stride  | 输入      | 目标每个元素的间隔                                                           |
| src         | 输入      | 源device memory结构体                                                        |
| src_stride  | 输入      | 源数据的每个元素的间隔                                                       |
| count       | 输入      | 需要拷贝的元素的个数                                                         |
| format_size | 输入      | 每个元素的字节大小，比如float类型字节大小是4，uint8_t类型字节大小是1；拷贝个数、stride都是以format_size为单位 |

**限制条件**：dst_stride通常为1；只有一种情况可以不为1：dst_stride = 4 且 src_stride = 1 且 format_size = 1。

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_stride_with_core

**函数原型**：`bm_status_t bm_memcpy_d2d_stride_with_core(bm_handle_t handle, bm_device_mem_t dst, int dst_stride, bm_device_mem_t src, int src_stride, int count, int format_size, int core_id)`

**函数作用**：指定使用第core_id个GDMA，将一块device类型的memory拷贝到另外一块device类型的memory，指定目的、源数据的stride，数据的个数，以及数据的类型字节大小；效果是从src起始地址按src_stride为间隔大小拷贝count个元素大小为format_size字节的数据到dst起始地址，以dst_stride为间隔大小存储。

**参数介绍**：

| 参数名      | 输入/输出 | 说明                                                                         |
|-------------|-----------|------------------------------------------------------------------------------|
| handle      | 输入      | 设备句柄                                                                     |
| dst         | 输入      | 目标device memory结构体                                                      |
| dst_stride  | 输入      | 目标每个元素的间隔                                                           |
| src         | 输入      | 源device memory结构体                                                        |
| src_stride  | 输入      | 源数据的每个元素的间隔                                                       |
| count       | 输入      | 需要拷贝的元素的个数                                                         |
| format_size | 输入      | 每个元素的字节大小，比如float类型字节大小是4，uint8_t类型字节大小是1；拷贝个数、stride都是以format_size为单位 |
| core_id     | 输入      | 搬运的GDMA设备id                                                             |

**限制条件**：dst_stride通常为1；只有一种情况可以不为1：dst_stride = 4 且 src_stride = 1 且 format_size = 1。

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_u64

**函数原型**：`bm_memcpy_d2d_u64(bm_handle_t handle, bm_device_mem_u64_t dst, unsigned long long dst_offset, bm_device_mem_u64_t src, unsigned long long src_offset, unsigned long long len)`

**函数作用**：将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+src_offset)拷贝len个DWORD（4字节）的数据到(dst起始地址+dst_offset)

**参数介绍**：

| 参数名     | 输入/输出 | 说明                                  |
|------------|-----------|---------------------------------------|
| handle     | 输入      | 设备句柄                              |
| dst        | 输入      | 目标device memory结构体               |
| dst_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| src        | 输入      | 源device memory结构体                 |
| src_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| len        | 输入      | 数据copy长度，单位是DWORD（4字节）    |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_byte_u64

**函数原型**：`bm_status_t bm_memcpy_d2d_byte_u64(bm_handle_t handle, bm_device_mem_u64_t dst, unsigned long long dst_offset, bm_device_mem_u64_t src, unsigned long long src_offset, unsigned long long size);`

**函数作用**：将一块device类型的memory拷贝到另外一块device类型的memory，指定大小和目的、源数据的offset；效果是从(src起始地址+src_offset)拷贝len个字节的数据到(dst起始地址+ dst_offset)

**参数介绍**：

| 参数名     | 输入/输出 | 说明                                  |
|------------|-----------|---------------------------------------|
| handle     | 输入      | 设备句柄                              |
| dst        | 输入      | 目标device memory结构体               |
| dst_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| src        | 输入      | 源device memory结构体                 |
| src_offset | 输入      | 用于计算数据拷贝的起始位置的offset    |
| size       | 输入      | 数据copy长度，单位是字节              |

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memcpy_d2d_stride_u64

**函数原型**：`bm_status_t bm_memcpy_d2d_stride_u64(bm_handle_t handle, bm_device_mem_u64_t dst, unsigned long long dst_stride, bm_device_mem_u64_t src, unsigned long long src_stride, unsigned long long count, int format_size);`

**函数作用**：将一块device类型的memory拷贝到另外一块device类型的memory，指定目的、源数据的stride，数据的个数，以及数据的类型字节大小；效果是从src起始地址按src_stride为间隔大小拷贝count个元素大小为format_size字节的数据到dst起始地址，以dst_stride为间隔大小存储。

**参数介绍**：

| 参数名      | 输入/输出 | 说明                                                                 |
|-------------|-----------|----------------------------------------------------------------------|
| handle      | 输入      | 设备句柄                                                             |
| dst         | 输入      | 目标device memory结构体                                              |
| dst_stride  | 输入      | 目标每个元素的间隔                                                   |
| src         | 输入      | 源device memory结构体                                                |
| src_stride  | 输入      | 源数据的每个元素的间隔                                               |
| count       | 输入      | 需要拷贝的元素的个数                                                 |
| format_size | 输入      | 每个元素的字节大小，比如float类型字节大小是4，uint8_t类型字节大小是1；拷贝个数、stride都是以format_size为单位 |

**限制条件**：dst_stride通常为1；只有一种情况可以不为1：dst_stride = 4 且 src_stride = 1 且 format_size = 1。

**返回值**：BM_SUCCESS代表传输成功；其他错误码代表传输失败

# bm_memset_device

**函数原型**：`bm_status_t bm_memset_device(bm_handle_t handle, const int value, bm_device_mem_t mem);`

**函数作用**：用value填充一块device memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明                                                                 |
|--------|-----------|----------------------------------------------------------------------|
| handle | 输入      | 设备句柄                                                             |
| value  | 输入      | 需要填充的值                                                         |
| mem    | 输入      | 目标device memory结构体，此函数只能填充大小为4字节整数倍的global memory空间 |

**返回值**：BM_SUCCESS代表填充成功；其他错误码代表填充失败

本函数的作用和bm_memset_device_ext函数mode为4时的作用一样。

# bm_memset_device_ext

**函数原型**：`bm_status_t bm_memset_device_ext(bm_handle_t handle, void* value, int mode, bm_device_mem_t mem);`

**函数作用**：用value指向的内容和指定的模式填充一块device memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明                    |
|--------|-----------|-------------------------|
| handle | 输入      | 设备句柄                |
| value  | 输入      | 指向需要填充的值        |
| mode   | 输入      | 填充模式，详见下图      |
| mem    | 输入      | 目标device memory结构体 |

**返回值**：BM_SUCCESS代表填充成功；其他错误码代表填充失败

Mode为2时，dst memory的size必须是2字节的整数倍

Mode为3时，dst memory的size必须是3字节的整数倍

Mode为4时，dst memory的size必须是4字节的整数倍

# bm_memset_device_ext_to_core

**函数原型**：`bm_status_t bm_memset_device_ext_to_core(bm_handle_t handle, void* value, int mode, bm_device_mem_t mem, int core_id);`

**函数作用**：用value指向的内容和指定的模式填充一块device memory

**参数介绍**：

| 参数名 | 输入/输出 | 说明                    |
|--------|-----------|-------------------------|
| handle | 输入      | 设备句柄                |
| value  | 输入      | 指向需要填充的值        |
| mode   | 输入      | 填充模式，详见下图      |
| mem    | 输入      | 目标device memory结构体 |
| core_id | 输入     | 搬运的GDMA设备id        |

**返回值**：BM_SUCCESS代表填充成功；其他错误码代表填充失败

Mode为2时，dst memory的size必须是2字节的整数倍

Mode为3时，dst memory的size必须是3字节的整数倍

Mode为4时，dst memory的size必须是4字节的整数倍

# Global memory 在不同设备间搬运

## bm_memcpy_c2c

**函数原型**：`bm_status_t bm_memcpy_c2c(bm_handle_t src_handle, bm_handle_t dst_handle, bm_device_mem_t src, bm_device_mem_t dst, bool force_dst_cdma);`

**函数作用**：将global memory从一块设备搬运到另一个设备（目前仅支持同一张卡上的设备）

**参数介绍**：

| 参数名           | 输入/输出 | 说明                                  |
|------------------|-----------|---------------------------------------|
| src_handle       | 输入      | 源地址的设备句柄                      |
| dst_handle       | 输入      | 目的地址的设备句柄                    |
| src              | 输入      | 源目标device memory 结构体            |
| dst              | 输入      | 目的目标device memory 结构体          |
| force_dst_cdma   | 输入      | 强制使用目的device的cdma进行搬运，默认使用源device的cdma搬运 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_memcpy_c2c_stride

**函数原型**：`bm_status_t bm_memcpy_c2c_stride(bm_handle_t src_handle, bm_handle_t dst_handle, bm_device_mem_t src, bm_device_mem_t dst, struct stride_cfg *stride, bool force_use_dst_cdma);`

**函数作用**：将global memory从一块设备搬运到另一个设备（目前仅支持同一张卡上的设备）

**参数介绍**：

| 参数名           | 输入/输出 | 说明                                  |
|------------------|-----------|---------------------------------------|
| src_handle       | 输入      | 源地址的设备句柄                      |
| dst_handle       | 输入      | 目的地址的设备句柄                    |
| src              | 输入      | 源目标device memory 结构体            |
| dst              | 输入      | 目的目标device memory 结构体          |
| stride           | 输入      | stride配置结构体                      |
| force_dst_cdma   | 输入      | 强制使用目的device的cdma进行搬运，默认使用源device的cdma搬运 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# Global memory在host端的映射和一致性管理

## bm_mem_mmap_device_mem

**函数原型**：`bm_status_t bm_mem_mmap_device_mem(bm_handle_t handle, bm_device_mem_t *dmem, unsigned long long *vmem);`

**函数作用**：将一块global memory映射到host的user空间，并开启cache（只在soc模式下面有效，pcie模式下不支持）

**参数介绍**：

| 参数名 | 输入/输出 | 说明                                  |
|--------|-----------|---------------------------------------|
| handle | 输入      | 设备句柄                              |
| dmem   | 输入      | 执行被映射的global memory的结构体     |
| vmem   | 输出      | 存储映射出来的虚拟地址的指针          |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_mmap_device_mem_u64

**函数原型**：`bm_status_t bm_mem_mmap_device_mem_u64(bm_handle_t handle, bm_device_mem_u64_t *dmem, unsigned long long *vmem);`

**函数作用**：将一块global memory映射到host的user空间，并开启cache（只在soc模式下面有效，pcie模式下不支持）

**参数介绍**：

| 参数名 | 输入/输出 | 说明                                  |
|--------|-----------|---------------------------------------|
| handle | 输入      | 设备句柄                              |
| dmem   | 输入      | 执行被映射的global memory的结构体     |
| vmem   | 输出      | 存储映射出来的虚拟地址的指针          |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_mmap_device_mem_no_cache

**函数原型**：`bm_status_t bm_mem_mmap_device_mem_no_cache(bm_handle_t handle, bm_device_mem_t *dmem, unsigned long long *vmem);`

**函数作用**：将一块global memory映射到host的user空间，并关闭cache（只在soc模式下面有效，pcie模式下不支持）

**参数介绍**：

| 参数名 | 输入/输出 | 说明                                  |
|--------|-----------|---------------------------------------|
| handle | 输入      | 设备句柄                              |
| dmem   | 输入      | 执行被映射的global memory的结构体     |
| vmem   | 输出      | 存储映射出来的虚拟地址的指针          |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_mem_mmap_device_mem_no_cache_u64

**函数原型**：`bm_status_t bm_mem_mmap_device_mem_no_cache_u64(bm_handle_t handle, bm_device_mem_u64_t *dmem, unsigned long long *vmem);`

**函数作用**：将一块global memory映射到host的user空间，并关闭cache（只在soc模式下面有效，pcie模式下不支持）

**参数介绍**：

| 参数名 | 输入/输出 | 说明                                  |
|--------|-----------|---------------------------------------|
| handle | 输入      | 设备句柄                              |
| dmem   | 输入      | 执行被映射的global memory的结构体     |
| vmem   | 输出      | 存储映射出来的虚拟地址的指针          |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_invalidate_device_mem

函数原型：`bm_status_t bm_mem_invalidate_device_mem(bm_handle_t handle, bm_device_mem_t *dmem);`

函数作用：invalidate一段被映射过的device memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被使无效的global memory的结构体指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_invalidate_device_mem_u64

函数原型：`bm_status_t bm_mem_invalidate_device_mem_u64(bm_handle_t handle, bm_device_mem_u64_t *dmem);`

函数作用：invalidate一段被映射过的device memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被使无效的global memory的结构体指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_invalidate_partial_device_mem

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

# bm_mem_invalidate_partial_device_mem_u64

函数原型：`bm_status_t sg_mem_invalidate_partial_device_mem(bm_handle_t handle, sg_device_mem_t *dmem, unsigned long long offset, unsigned long long len);`

函数作用：invalidate一段被映射过的device memory的一部分（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被使无效的global memory的结构体指针 |
| offset | 输入 | 地址偏移量 |
| len | 输入 | invalidate的长度 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_flush_device_mem

函数原型：`bm_status_t bm_mem_flush_device_mem(bm_handle_t handle, bm_device_mem_t *dmem);`

函数作用：flush一段被映射过的device global memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被flush的global memory的结构体 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_flush_device_mem_u64

函数原型：`bm_status_t bm_mem_flush_device_mem_u64(bm_handle_t handle, bm_device_mem_u64_t *dmem);`

函数作用：flush一段被映射过的device global memory（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被flush的global memory的结构体 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_flush_partial_device_mem

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

# bm_mem_flush_partial_device_mem_u64

函数原型：`bm_status_t bm_mem_flush_partial_device_mem_u64(bm_handle_t handle, bm_device_mem_u64_t *dmem, unsigned long long offset, unsigned long long len);`

函数作用：flush一段被映射过的device global memory的一部分（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| dmem | 输入 | 执行被flush的global memory的结构体 |
| offset | 输入 | 地址偏移量 |
| len | 输入 | flush的长度 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_unmap_device_mem

函数原型：`bm_status_t bm_mem_unmap_device_mem(bm_handle_t handle, void *vmem, int size);`

函数作用：SOC 模式下，解除device内存的映射。（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| vmem | 输入 | unmap的虚拟地址 |
| size | 输入 | unmap的大小 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_unmap_device_mem_u64

函数原型：`bm_status_t bm_mem_unmap_device_mem_u64(bm_handle_t handle, void *vmem, unsigned long long size);`

函数作用：SOC 模式下，解除device内存的映射。（只在soc模式下面有效，pcie模式下不支持）

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| vmem | 输入 | unmap的虚拟地址 |
| size | 输入 | unmap的大小 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_mem_vir_to_phy

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

**函数原型**：`void bm_flush(bm_handle_t handle);`

**函数作用**：此函数的功能等同于bm_handle_sync，此函数是为了保持对老的代码兼容存在的，不建议再继续使用。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：无返回值

## bm_device_sync

**函数原型**：`bm_status_t bm_device_sync(bm_handle_t handle);`

**函数作用**：这个函数的含义是：创建handle的进程调用这个函数时，在handle指向的设备上已经有了N个api在处理，函数返回后，这N个api都完成了。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_thread_sync

**函数原型**：`bm_status_t bm_thread_sync(bm_handle_t handle);`

**函数作用**：这个函数的确切含义是：等待本caller thread在handle上之前提交过的所有api完成，如果本caller thread没有在此handle上提交过api，则直接返回成功；本函数返回不能保证本caller thread在其他handle上提交过的api已经完成。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_thread_sync_from_core

**函数原型**：`bm_status_t bm_thread_sync_from_core(bm_handle_t handle, int core_id);`

**函数作用**：这个函数的确切含义是：等待本caller thread在handle上第core_id个核上之前提交过的所有api完成，如果本caller thread没有在此handle上第core_id个核上提交过api，则直接返回成功；本函数返回不能保证本caller thread在其他handle上第core_id个核上提交过的api已经完成。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_handle_sync

**函数原型**：`bm_status_t bm_handle_sync(bm_handle_t handle);`

**函数作用**：同步提交到当前handle上所有的API操作，这个函数的含义是：调用这个函数时，通过此handle发送的API有N个，函数返回后，这N个api都完成了。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_handle_sync_from_core

**函数原型**：`bm_status_t bm_handle_sync_from_core(bm_handle_t handle, int core_id);`

**函数作用**：同步提交到当前handle上第core_id个核上的所有API操作，这个函数的含义是：调用这个函数时，通过此handle向第core_id个核发送的API有N个，函数返回后，这N个api都完成了。

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| core_id | 输入 | 要同步的核id |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

## bm_set_sync_timeout

**函数原型**：`bm_status_t bm_set_sync_timeout(bm_handle_t handle, int timeout);`

**函数作用**：设置最大等待tpu返回消息的时间，单位ms

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| timeout | 输入 | 超时时间 |

**返回值**：BM_SUCCESS代表同步成功；其他错误码代表同步失败

# profile接口

## bm_get_profile

**函数原型**：`bm_status_t bm_get_profile(bm_handle_t handle, bm_profile_t *profile);`

**函数作用**：获取当前时间点的proflile数据

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| profile | 输出 | 指向一个存放profling数据的结构体 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_last_api_process_time_us

**函数原型**：`bm_status_t bm_get_last_api_process_time_us(bm_handle_t handle, unsigned long *time_us);`

**函数作用**：此函数已经废弃

**参数介绍**：无

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_enable_perf_monitor

**函数原型**：`bm_status_t bm_enable_perf_monitor(bm_handle_t handle, bm_perf_monitor_t *perf_monitor);`

**函数作用**：使能profile monitor

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| perf_monitor | 输出 | 指向一个存放prof perf_monitor数据的结构体 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_disable_perf_monitor

**函数原型**：`bm_status_t bm_disable_perf_monitor(bm_handle_t handle, bm_perf_monitor_t *perf_monitor);`

**函数作用**：关闭profile monitor

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| perf_monitor | 输出 | 指向一个存放prof perf_monitor数据的结构体 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# power管理接口

## bm_set_clk_tpu_freq

**函数原型**：`bm_status_t bm_set_clk_tpu_freq(bm_handle_t handle, int freq);`

**函数作用**：设置当前tpu的工作频率，只在PCIE模式有效

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| freq | 输入 | tpu的目标工作频率 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_clk_tpu_freq

**函数原型**：`bm_status_t bm_get_clk_tpu_freq(bm_handle_t handle, int *freq);`

**函数作用**：获取当前tpu的工作频率

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| freq | 输出 | 保存tpu当前工作频率的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# 设备管理接口

## bm_get_misc_info

**函数原型**：`bm_status_t bm_get_misc_info(bm_handle_t handle, struct bm_misc_info *pmisc_info);`

**函数作用**：获取设备相关的misc信息

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| pmisc_info | 输出 | 存放misc数据的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_card_num

**函数原型**：`bm_status_t bm_get_card_num(unsigned int *card_num);`

**函数作用**：获取设备上卡的数量

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| card_num | 输出 | 存放卡数量的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_card_id

**函数原型**：`bm_status_t bm_get_card_id(bm_handle_t handle, unsigned int *card_id);`

**函数作用**：获取设备对应卡的编号

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| card_id | 输出 | 存放卡id的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_chip_num_from_card

**函数原型**：`bm_get_chip_num_from_card(unsigned int card_id, unsigned int *chip_num, unsigned int *dev_start_index);`

**函数作用**：获取卡上的设备编号

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| card_id | 输入 | 卡编号 |
| chip_num | 输出 | 卡上设备数量 |
| dev_start_index | 输出 | 卡上设备起始编号 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

## bm_get_chipid

**函数原型**：`bm_status_t bm_get_chipid(bm_handle_t handle, unsigned int *p_chipid);`

**函数作用**：获取设备对应的芯片ID(0x1684和0x1686)

**参数介绍**：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| p_chipid | 输出 | 存放芯片ID的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_stat

函数原型：`bm_status_t bm_get_stat(bm_handle_t handle, bm_dev_stat_t *stat);`

函数作用：获取handle对应的设备的运行时统计信息

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Stat | 输出 | 存放统计信息的指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_gmem_heap_id

函数原型：`bm_status_t bm_get_gmem_heap_id(bm_handle_t handle, bm_device_mem_t *pmem, unsigned int *heapid);`

函数作用：获取pmem指向的设备内存的heap id

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Pmem | 输入 | 设备内存指针 |
| Heaped | 输出 | 存放设备内存所在heap id 的指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmlib_log_get_level

函数原型：`int bmlib_log_get_level(void);`

函数作用：获取bmlib log等级

参数介绍：void

返回值：bmlib log 等级

# bmlib_log_set_level

函数原型：`void bmlib_log_set_level(int level);`

函数作用：设置bmlib log等级

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Level | 输入 | 要设置的bmlib log的等级 |

返回值：void

# bmlib_log_set_callback

函数原型：`void bmlib_log_set_callback((*callback)(const char* , int , const char*, va_list));`

函数作用：设置callback获取bmlib log

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Callback | 输入 | 设置获取bmlib log的回调函数的函数指针 |

返回值：void

# bm_set_debug_mode

函数原型：`void bm_set_debug_mode(bm_handle_t handle, int mode);`

函数作用：为tpu fw log设置debug模式

备注：此函数SC3在使用

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Mode | 输入 | fw log debug模式，0/1表示disable/enable |

返回值：void

# bmlib_set_api_dbg_callback

函数原型：`void bmlib_set_api_dbg_callback(bmlib_api_dbg_callback callback);`

函数作用：设置debug callback获取fw log

备注：此函数SC3在使用

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| Callback | 输入 | 要设置的获取fw log 回调函数的函数指针 |

返回值：void

# bm_get_tpu_current

函数原型：`bm_status_t bm_get_tpu_current(bm_handle_t handle, int *tpuc);`

函数作用：获取句柄对应设备的电流值，默认单位毫安（mA）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpuc | 输出 | 要获取tpuc的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_board_max_power

函数原型：`bm_status_t bm_get_board_max_power(bm_handle_t handle, int *maxp);`

函数作用：获取设备所在板卡支持的最大功耗值，默认单位瓦（W）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| maxp | 输出 | 要获取maxp的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_board_power

函数原型：`bm_status_t bm_get_board_power(bm_handle_t handle, int *boardp);`

函数作用：获取设备所在板卡的当前功耗值，默认单位瓦（W）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| boardp | 输出 | 要获取boardp的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_fan_speed

函数原型：`bm_status_t bm_get_fan_speed(bm_handle_t handle, int *fan);`

函数作用：获取设备所在板卡的风扇占空比。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| fan | 输出 | 要获取fan的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_ecc_correct_num

函数原型：`bm_status_t bm_get_ecc_correct_num(bm_handle_t handle, unsigned long *ecc_correct_num);`

函数作用：获取设备在DDR使能时，纠正错误的次数。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| ec c_correct_num | 输出 | 要获取ecc_correct_num的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_12v_atx

函数原型：`bm_status_t bm_get_12v_atx(bm_handle_t handle, int *atx_12v);`

函数作用：获取设备板级12V供电电流，默认单位毫安（mA）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| Handle | 输入 | 设备句柄 |
| atx_12v | 输出 | 要获取atx_12v的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_sn

函数原型：`bm_status_t bm_get_sn(bm_handle_t handle, char *sn);`

函数作用：获取板卡序列号（共17位）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| sn | 输出 | 要获取sn的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_status

函数原型：`bm_status_t bm_get_status(bm_handle_t handle, int *status);`

函数作用：获取句柄对应的设备状态，0为活动状态，1为故障状态。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| status | 输出 | 要获取status的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_tpu_minclk

函数原型：`bm_status_t bm_get_tpu_minclk(bm_handle_t handle, unsigned int *tpu_minclk);`

函数作用：获取句柄对应设备的最小工作频率，默认单位兆赫兹（MHz）。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| tpu_minclk | 输出 | 要获取tpu_minclk的函数指针 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_tpu_maxclk

**函数原型**：`bm_status_t bm_get_tpu_maxclk(bm_handle_t handle, unsigned int *tpu_maxclk);`

**函数作用**：获取句柄对应设备的最大工作频率，默认单位兆赫兹（MHz）。

**参数介绍**：

| 参数名     | 输入/输出 | 说明                         |
|------------|-----------|------------------------------|
| handle     | 输入      | 设备句柄                     |
| tpu_maxclk | 输出      | 要获取tpu_maxclk的函数指针   |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_driver_version

**函数原型**：`bm_status_t bm_get_driver_version(bm_handle_t handle, int *driver_version);`

**函数作用**：获取板卡安装的驱动版本。

**参数介绍**：

| 参数名         | 输入/输出 | 说明                           |
|----------------|-----------|--------------------------------|
| handle         | 输入      | 设备句柄                       |
| driver_version | 输出      | 要获取driver_version的函数指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_board_name

**函数原型**：`bm_status_t bm_get_board_name(bm_handle_t handle, char *name);`

**函数作用**：获取当前板卡的名称，名称:芯片id-板卡类型（如：1684-SC5+）。

**参数介绍**：

| 参数名 | 输入/输出 | 说明                 |
|--------|-----------|----------------------|
| handle | 输入      | 设备句柄             |
| name   | 输出      | 要获取name的函数指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_board_temp

**函数原型**：`bm_status_t bm_get_board_temp(bm_handle_t handle, unsigned int *board_temp);`

**函数作用**：获取句柄对应设备所在板卡的板级温度，默认单位摄氏度（℃）。

**参数介绍**：

| 参数名     | 输入/输出 | 说明                       |
|------------|-----------|----------------------------|
| handle     | 输入      | 设备句柄                   |
| board_temp | 输出      | 要获取board_temp的函数指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_chip_temp

**函数原型**：`bm_status_t bm_get_chip_temp(bm_handle_t handle, unsigned int *chip_temp);`

**函数作用**：获取句柄对应设备的温度，默认单位摄氏度（℃）。

**参数介绍**：

| 参数名    | 输入/输出 | 说明                 |
|-----------|-----------|----------------------|
| handle    | 输入      | 设备句柄             |
| chip_temp | 输出      | 存储chip_temp的指针  |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_tpu_power

**函数原型**：`bm_status_t bm_get_tpu_power(bm_handle_t handle, float *tpu_power);`

**函数作用**：获取句柄对应设备的功耗，默认单位瓦（W）。

**参数介绍**：

| 参数名    | 输入/输出 | 说明                 |
|-----------|-----------|----------------------|
| handle    | 输入      | 设备句柄             |
| tpu_power | 输出      | 存储tpu_power的指针  |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_tpu_volt

**函数原型**：`bm_status_t bm_get_tpu_volt(bm_handle_t handle, float *tpu_volt);`

**函数作用**：获取句柄对应设备的电压，默认单位毫伏（mV）。

**参数介绍**：

| 参数名   | 输入/输出 | 说明                |
|----------|-----------|---------------------|
| handle   | 输入      | 设备句柄            |
| tpu_volt | 输出      | 存储tpu_volt的指针  |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_dynfreq_status

**函数原型**：`bm_status_t bm_get_dynfreq_status(bm_handle_t handle, int *dynfreq_status);`

**函数作用**：获取句柄对应设备的动态频率状态，默认为开。

**参数介绍**：

| 参数名        | 输入/输出 | 说明                     |
|---------------|-----------|--------------------------|
| handle        | 输入      | 设备句柄                 |
| dynfreq_status| 输出      | 存储dynfreq_status的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_change_dynfreq_status

**函数原型**：`bm_status_t bm_change_dynfreq_status(bm_handle_t handle, int new_status);`

**函数作用**：设置动态频率状态，默认为开。

**参数介绍**：

| 参数名     | 输入/输出 | 说明       |
|------------|-----------|------------|
| handle     | 输入      | 设备句柄   |
| new_status | 输入      | 要设置的值 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bmdev_get_idle_coreid

**函数原型**：`bm_status_t bmdev_get_idle_coreid(bm_handle_t handle, int *core_id);`

**函数作用**：获取当前为负载最低的tpu core id。

**参数介绍**：

| 参数名  | 输入/输出 | 说明               |
|---------|-----------|--------------------|
| handle  | 输入      | 设备句柄           |
| core_id | 输出      | 存储core_id的指针  |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_tpu_scalar_num

**函数原型**：`bm_status_t bm_get_tpu_scalar_num(bm_handle_t handle, unsigned int *core_num);`

**函数作用**：得到tpu核（tpu scalar）的数量

**参数介绍**：

| 参数名   | 输入/输出 | 说明             |
|----------|-----------|------------------|
| handle   | 输入      | 设备句柄         |
| core_num | 输出      | tpu scalar的数量 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_pwr_ctrl

**函数原型**：`bm_status_t bm_pwr_ctrl(bm_handle_t handle, void *bm_api_cfg_pwr_ctrl);`

**函数作用**：设置pwr ctrl。

**参数介绍**：

| 参数名           | 输入/输出 | 说明     |
|------------------|-----------|----------|
| handle           | 输入      | 设备句柄 |
| bm_api_cfg_pwr_ctrl | 输入      | 设置参数 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bm_get_boot_loader_version

**函数原型**：`bm_status_t bm_get_boot_loader_version(bm_handle_t handle, boot_loader_version *version);`

**函数作用**：获取boot loader版本信息。

**参数介绍**：

| 参数名  | 输入/输出 | 说明                 |
|---------|-----------|----------------------|
| handle  | 输入      | 设备句柄             |
| version | 输出      | 存储version信息的指针 |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# A53使能

## bmcpu_start_cpu

**函数原型**：`bm_status_t bmcpu_start_cpu(bm_handle_t handle, char *boot_file, char *core_file);`

**函数作用**：启动设备上的ARM处理器A53。

**参数介绍**：

| 参数名    | 输入/输出 | 说明                       |
|-----------|-----------|----------------------------|
| handle    | 输入      | 设备句柄                   |
| boot_file | 输入      | ARM处理器启动的boot文件    |
| core_file | 输入      | ARM处理器启动的kernel文件  |

**返回值**：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_open_process

函数原型：`int bmcpu_open_process(bm_handle_t handle, unsigned int flags, int timeout);`

函数作用：创建运行在A53上的进程。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| flags | 输入 | 创建a53进程的标志位 |
| timeout | 输入 | 创建a53进程的超时时间 |

返回值：A53上进程句柄

# bmcpu_load_library

函数原型：`bm_status_t bmcpu_load_library(bm_handle_t handle, int process_handle, char *library_file, int timeout);`

函数作用：加载A53上进程所需要的动态库。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| process_handle | 输入 | A53上进程句柄 |
| library_file | 输入 | 需要加载的动态库文件 |
| timeout | 输入 | 加载动态库的超时时间 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_unload_library

函数原型：`bm_status_t bmcpu_unload_library(bm_handle_t handle, int process_handle, char *library_file, int timeout);`

函数作用：卸载A53上进程所需要的动态库。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| process_handle | 输入 | A53上进程句柄 |
| library_file | 输入 | 需要卸载的动态库文件 |
| timeout | 输入 | 卸载动态库的超时时间 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_exec_function

函数原型：`int bmcpu_exec_function(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, int timeout);`

函数作用：在A53进程执行指定函数。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| process_handle | 输入 | A53上进程句柄 |
| function_name | 输入 | 需要执行的函数名称 |
| function_param | 输入 | 需要执行的函数入参地址 |
| param_size | 输入 | 需要执行的函数入参大小 |
| timeout | 输入 | A53执行函数的超时时间 |

返回值：0代表成功；大于0代表bmlib失败，小于0代表function执行失败

# bmcpu_exec_function_ext

函数原型：`int bmcpu_exec_function_ext(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, unsigned int opt, int timeout);`

函数作用：在A53进程执行指定函数，设置是否刷新cache。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| process_handle | 输入 | A53上进程句柄 |
| function_name | 输入 | 需要执行的函数名称 |
| function_param | 输入 | 需要执行的函数入参地址 |
| param_size | 输入 | 需要执行的函数入参大小 |
| opt | 输入 | 是否需要刷新cache |
| timeout | 输入 | A53执行函数的超时时间 |

返回值：0代表成功；大于0代表bmlib失敗，小于0代表function执行失败

# bmcpu_exec_function_async

函数原型：`bm_status_t bmcpu_exec_function_async(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, unsigned long long *api_handle);`

函数作用：在A53进程执行指定函数。

参数介绍：

| 参数名 | 输入/输出 | 说明 |
|--------|-----------|------|
| handle | 输入 | 设备句柄 |
| process_handle | 输入 | A53上进程句柄 |
| function_name | 输入 | 需要执行的函数名称 |
| function_param | 输入 | 需要执行的函数入参地址 |
| param_size | 输入 | 需要执行的函数入参大小 |
| api_handle | 输入 | API句柄 |

返回值：0代表成功；大于0代表bmlib失败，小于0代表function执行失败

# bmcpu_exec_function_async_ext

函数原型：bm_status_t bmcpu_exec_function_async_ext(bm_handle_t handle, int process_handle, char *function_name, void *function_param, unsigned int param_size, unsigned int opt, unsigned long long *api_handle);

函数作用：在A53进程执行指定函数，设置是否刷新cache。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| process_handle | 输入         | A53上进程句柄                         |
| function_name  | 输入         | 需要执行的函数名称                    |
| function_param | 输入         | 需要执行的函数入参地址                |
| param_size     | 输入         | 需要执行的函数入参大小                |
| opt            | 输入         | 是否需要刷新cache                     |
| api_handle     | 输入         | API句柄                             |

返回值：0代表成功；大于0代表bmlib失敗，小于0代表function执行失败

# bmcpu_query_exec_function_result

函数原型：int bmcpu_query_exec_function_result(bm_handle_t handle, unsigned long long api_handle, int timeout);

函数作用：查询A53进程执行函数的返回结果。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| api_handle     | 输入         | API句柄                             |
| timeout        | 输入         | A53执行函数的超时时间                 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_map_phys_addr

函数原型：void *bmcpu_map_phys_addr(bm_handle_t handle, int process_handle, void *phys_addr, unsigned int size, int timeout);

函数作用：将设备物理地址映射成A53能访问的虚拟地址。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| process_handle | 输入         | A53上进程句柄                         |
| phys_addr      | 输入         | host侧申请的设备内存对应的虚拟地址    |
| size           | 输入         | 申请的内存大小                        |
| timeout        | 输入         | A53映射地址的超时时间                 |

返回值：设备物理地址映射成的A53能访问的虚拟地址

# bmcpu_unmap_phys_addr

函数原型：bm_status_t bmcpu_unmap_phys_addr(bm_handle_t handle, int process_handle, void *phys_addr, int timeout);

函数作用：释放被A53映射的物理地址。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| process_handle | 输入         | A53上进程句柄                         |
| phys_addr      | 输入         | host侧申请的设备内存对应的A53虚拟地址 |
| timeout        | 输入         | A53映射地址的超时时间                 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_close_process

函数原型：int bmcpu_close_process(bm_handle_t handle, int process_handle, int timeout);

函数作用：关闭运行在A53上的进程。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| process_handle | 输入         | A53上进程句柄                         |
| timeout        | 输入         | 关闭a53进程的超时时间                 |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_reset_cpu

函数原型：bm_status_t bmcpu_reset_cpu(bm_handle_t handle);

函数作用：使A53进入关机状态。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_reset_tpu

函数原型：bm_status_t bm_reset_tpu(bm_handle_t handle);

函数作用：安全的重启TPU系统（仅bm1688使用）

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_set_log

函数原型：bm_status_t bmcpu_set_log(bm_handle_t handle, unsigned int log_level, unsigned int log_to_console, int timeout);

函数作用：设置cpu log 参数。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| log_level      | 输入         | log等级                               |
| log_to_console | 输入         | A53上进程句柄                         |
| timeout        | 输入         | 关闭a53进程的超时时间                  |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_get_log

函数原型：bm_status_t bmcpu_get_log(bm_handle_t handle, int process_handle, char *log_file, int timeout);

函数作用：获取cpu log 文件。

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| process_handle | 输入         | A53上进程句柄                         |
| log_file       | 输出         | 存储log的文件句柄                     |
| timeout        | 输入         | 关闭a53进程的超时时间                  |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bmcpu_sync_time

函数原型：bm_status_t bmcpu_sync_time(bm_handle_t handle);

函数作用：同步device和host时间

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# bm_load_firmware

函数原型：bm_status_t bm_load_firmware(bm_handle_t handle, const char *firmware_tcm, const char *firmware_ddr);

函数作用：加载firmware固件

参数介绍：

| 参数名         | 输入/输出    | 说明                                  |
|----------------|--------------|---------------------------------------|
| handle         | 输入         | 设备句柄                              |
| firmware_tcm   | 输入         | tcm 地址                             |
| firmware_ddr   | 输入         | ddr 地址                              |

返回值：BM_SUCCESS代表成功；其他错误码代表失败

# libsophon概述

libsophon目前包含如下组件：

1. TPU、VPU、JPU、VPP这几个模块的Linux驱动
2. 运行时库
    1. bmlib
    2. tpu runtime
    3. bmcv
3. 运行时库的开发环境（头文件等）
4. 辅助工具

**如何从源码编译PCIe版本：**

**安装依赖包：**

```
sudo -E apt update
sudo -E apt-get install -y \
        bsdmainutils \
        build-essential \
        cmake \
        ninja-build \
        pkg-config \
        libncurses5-dev \
        libgflags-dev \
        libgtest-dev \
        dkms \
        gcc-aarch64-linux-gnu \
        g++-aarch64-linux-gnu \
        git
```

**获取git submodules：**

```
git submodule update --init
```

**编译：**

使用Ninja：

```
mkdir build && cd build

cmake -G Ninja ..
# or, to install to certian destination, eg. $PWD/../install
cmake -G Ninja -DCMAKE_INSTALL_PREFIX=$PWD/../install ..

# build
cmake --build .

# build driver
cmake --build . --target driver

# install to the dest dir
cmake --build . --target install

# packing .tar.gz and .deb
cmake --build . --target package

# test bm-smi
sudo ln -s xxx/a53lite_pkg.bin /lib/firmware/bm1684x_firmware.bin.bin
# where xxx is the path of firmware, if firmware is modify, ln new firmware to /lib/firmware/bm1684x_firmware.bin.bin
insmod ./sg_x86_pcie_device/bmsophon.ko
./bm-smi/bm-smi

# test bmrt_test
./tpu-runtime/bmrt_test --context static.int8
./tpu-runtime/bmrt_test --context static.int8.b4
```

使用Make：

```
mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=$PWD/../install ..
make
make driver
make install
make package

sudo ln -s xxx/a53lite_pkg.bin /lib/firmware/bm1684x_firmware.bin.bin
# where xxx is the path of firmware, if firmware is modify, ln new firmware to /lib/firmware/bm1684x_firmware.bin

sudo dpkg -i sophon-*.deb
source /etc/profile
./bm-smi/bm-smi
./tpu-runtime/bmrt_test --context static.int8
./tpu-runtime/bmrt_test --context static.int8.b4
```

编译arm64架构的pcie模式libsophon安装包，推荐使用交叉编译工具链在x86_64的服务器上编译，需要准备aarch64架构用的交叉编译工具链gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu，按以下命令配置交叉编译工具链的目录，然后使用cmake进行编译。

```
mkdir build && cd build
cmake -DPLATFORM=pcie_arm64 -DCROSS_COMPILE_PATH=/absolute_path_to-gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu \
      -DCMAKE_TOOLCHAIN_FILE=/absolute_path_to_libsophon/toolchain-aarch64-linux.cmake \
      -DLIB_DIR=/absolute_path_to_libsophon/3rdparty/soc \
      -DCMAKE_INSTALL_PREFIX=$PWD/../install ..
make
make driver
make install
make package

sudo ln -s xxx/a53lite_pkg.bin /lib/firmware/bm1684x_firmware.bin
# where xxx is the path of firmware, if firmware is modify, ln new firmware to /lib/firmware/bm1684x_firmware.bin

sudo dpkg -i sophon-*.deb
source /etc/profile
./bm-smi/bm-smi
./tpu-runtime/bmrt_test --context static.int8
./tpu-runtime/bmrt_test --context static.int8.b4
```

编译 loongarch64 架构的 pcie 模式 libsophon 安装包，使用交叉编译工具链在 x86_64 的服务器上编译，需要准备 loongarch64 架构用的交叉编译工具链 loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1，按以下命令配置交叉编译工具链的目录，然后使用cmake进行编译。

```
mkdir build && cd build
cmake \
    -DPLATFORM=pcie_loongarch64 \
    -DCROSS_COMPILE_PATH=/absolute_path_to-loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1 \
    -DCMAKE_TOOLCHAIN_FILE=/absolute_path_to_libsophon/toolchain-loongarch64-linux.cmake \
    -DLIB_DIR=/absolute_path_to_libsophon/3rdparty/loongarch64 \
    -DCMAKE_INSTALL_PREFIX=$PWD/../install ..

PATH=/absolute_path_to-loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin:$PATH
make
make driver
make install
make package
```

# 编译文档

## 需要的依赖包

安装latex：
```
sudo apt install texlive-xetex texlive-latex-recommended
```

安装sphinx：
```
sudo apt install python-is-python3
pip install sphinx sphinx-autobuild sphinx_rtd_theme rst2pdf
```

安装结巴中文分词库，以支持中文搜索：
```
pip install jieba3k
```

安装中文字体：
```
wget http://mirrors.ctan.org/fonts/fandol.zip
unzip fandol.zip
sudo cp -r fandol /usr/share/fonts/
cp -r fandol ~/.fonts
```

## 编译

```
cmake --build . --target doc
```
或者：
```
make doc
```
在doc/build下即可以看到html和pdf格式的文档。

# 如何从源码编译SoC版本

首先您需要编译SoC BSP，请参考BSP的编译指导。

我们提供2种方式编译soc版本

## 交叉编译环境方式

### 环境准备

参考步骤是在docker里编译，如果已经有Ubuntu18.04以上环境，也可以直接在本机编译。

拷贝交叉编译工具链：
```
mkdir -p ${path_to_local_workspace}
cp -r ${path_to_gcc}/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu ${path_to_local_workspace}/
```

拷贝libsophon源码：
```
cp -r ${path_to_libsophon_repo}/libsophon ${path_to_local_workspace}/
```

从SoC BSP编译目录拷贝linux-headers安装包：
```
cp ${path_to_soc_bsp}/install/soc_bm1684/bsp-debs/linux-headers-*.deb ${path_to_local_workspace}/
mkdir -p ${path_to_local_workspace}/soc_kernel
dpkg -x ${path_to_local_workspace}/linux-headers-*.deb ${path_to_local_workspace}/soc_kernel
```

进入docker：
```
docker pull ubuntu:focal
sudo docker run -v ${path_to_local_workspace}:/workspace -it ubuntu:focal bash
```

此时您应该得到了如下层级的目录，请注意如果您的路径与下面不同，请同步修改toolchain-aarch64-linux.cmake文件中的路径：
```
/workspace
     |----gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu
     |----libsophon
     |----linux-headers-*.deb
     |----soc_kernel
```

### 编译

安装依赖包，请参考pcie模式。

手动修改aarch64-linux-gnu-成6.3.1版本：
```
cd /usr/bin/ && mkdir aarch64-bak
mv aarch64-linux-gnu-* aarch64-bak
ln -s /workspace/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-* .
```

假定前面拷贝的linux-headers安装包名叫linux-headers-5.4.207-bm1684-ga2f7484bf21a.deb：
```
header="linux-headers-5.4.207-bm1684-ga2f7484bf21a"

cd /workspace/libsophon
mkdir build && cd build
cmake -DPLATFORM=soc -DSOC_LINUX_DIR=/workspace/soc_kernel/usr/src/${header}/ -DLIB_DIR=/workspace/libsophon/3rdparty/soc/ \
      -DCROSS_COMPILE_PATH=/absolute_path_to-gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu \
      -DCMAKE_TOOLCHAIN_FILE=/absolute_path_to_libsophon/toolchain-aarch64-linux.cmake \
      -DCMAKE_INSTALL_PREFIX=$PWD/../install ..

make
make driver
make vpu_driver
make jpu_driver
make package
```

过程中如果遇到下面的问题，按照提示操作执行即可：
```
cd /workspace/libsophon/bmvid/jpeg/driver/bmjpulite && /usr/bin/cmake -E chdir .. git checkout -- include/version.h
fatal: detected dubious ownership in repository at '/workspace/bmvid'
To add an exception for this directory, call:

    git config --global --add safe.directory /workspace/bmvid
```

## qemu环境编译方式

从网络抓取构建Debian 9，进入qemu环境编译：

```
sudo apt update
sudo apt-get install qemu-user-static debootstrap
mkdir debian-rootfs
cd debian-rootfs
sudo qemu-debootstrap --arch=arm64 stretch .

从SoC BSP编译目录copy linux-headers安装包：
sudo cp ${path_to_soc_bsp}/install/soc_bm1684/bsp-debs/linux-headers-*.deb .
由于我们编译需要拉取libsophon代码，请再copy您的如下文件：
sudo cp ~/.gitconfig ./root/
sudo cp -r ~/.ssh ./root/

sudo chroot . /bin/bash
```

此时应该看到"/#"提示符了，之后的步骤都在这个qemu环境里进行，所有的文件操作都会保留在磁盘上。请务必确认chroot成功，以免后续操作对您的本机系统造成损坏。

在qemu环境里继续安装依赖包：

```
apt update
apt-get install -y \
        build-essential \
        git bc bison flex \
        ninja-build \
        pkg-config \
        libncurses5-dev \
        libgflags-dev \
        libgtest-dev \
        libssl-dev

把cmake 升级到3.13:
wget https://cmake.org/files/v3.13/cmake-3.13.2.tar.gz
tar xvf cmake-3.13.2.tar.gz
cd cmake-3.13.2
./bootstrap --prefix=/usr
make
make install
```

以上步骤只需要进行一次，以后再用到时只要chroot进来就可以了。

接下来安装最开始时copy进来的linux-headers deb包（编译SoC版驱动需要）:

```
假定前面拷贝到当前目录的linux-headers安装包名叫linux-headers-5.4.207-bm1684-ga2f7484bf21a.deb：
cd /
header="linux-headers-5.4.207-bm1684-ga2f7484bf21a"
dpkg -i ${header}.deb
cd /usr/src/${header}
rm ./scripts/mod/modpost
make prepare0
make scripts
```

上面这个步骤只有第一次，或当kernel发生了不向前兼容的改动时才需要进行，记得更新linux-headers安装包。

编译libsophon：

```
cd /
git clone ssh://${your_name}@gerrit-ai.sophgo.vip:29418/libsophon
cd libsophon
git submodule update --init
mkdir build && cd build
cmake -DPLATFORM=soc -DSOC_LINUX_DIR=/usr/src/${header}/  -DCMAKE_INSTALL_PREFIX=$PWD/../install ..
make
make driver
make vpu_driver
make jpu_driver
make package
```

最后用exit命令就可以退出qemu环境了。

## 在 windows 下编译

1. 安装 Visual Studio 并将其加入 PATH;

2. 安装 xxd 并将其加入 PATH;

3. 拉取 bm_prebuilt_toolchains_win 至 libsophon 同级目录下，目录结构如下:

```
.
├── bm_prebuilt_toolchains_win
└── libsophon
```

3. 在 CMD 中进入 libsophon 目录下进行编译:

```
call build.bat release MT
```

生成文件在 libsophon/release/libsophon 下，可使用以下命令对其进行打包:

```
call build.bat release MT pack
```

最后在 libsophon/release 下可获取 libsophon_win_x.x.x_arch.zip 形式的压缩包文件。