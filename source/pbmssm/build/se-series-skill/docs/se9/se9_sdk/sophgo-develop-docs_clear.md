# 前言

## 文档概述

本文档详细介绍了 BM1688 系列AI计算模组（含开发板）的外观特点、应用场景、设备参数、电气特性、配套软件、使用环境等，使得该设备的用户及开发者对 BM1688 系列AI计算模组（含开发板）有比较全面深入的了解。设备用户及开发者可依据此手册，开展对该设备的安装、调试、部署、维护等一系列工作。

## 读者对象

本文档主要适用于如下人员：

- 算丰FAE工程师、售前工程师
- 生态合作伙伴的开发人员
- 用户企业研发工程师、售前工程师

## 约定的符号、标志、专用语解释

在本文中可能出现如下符号、标志，它们所代表的含义如下：

| 符号 | 含义 |
|------|------|
| 危险 | 表示有高度危险，如果不能避免，可能导致人员伤亡或严重伤害 |
| 警告 | 表示有中度或低度潜在危险，如果不能避免，可能导致人员轻微或中等伤害 |
| 注意 | 表示有潜在风险，如果忽视这部分文本，可能导致设备损坏、数据丢失、设备性能降低或不可预知的结果 |
| 防静电 | 防静电标识，表示静电敏感的设备或操作 |
| 当心触电 | 电击防护标识，标识高压危险，需做好防护 |
| 窍门 | 表示能帮助您解决某个问题或节省您的时间 |
| 说明 | 表示是正文的附加信息，是对正文的强调和补充 |

## 缩略语

| 缩略语 | 英文全称 | 中文含义 |
|--------|----------|----------|
| JPU | JPEG Process Unit | JPEG处理单元 |
| VPP | Video Post Process | 图像后处理 |
| VPU | Video Process Unit | 视频编解码单元 |

## 修改记录

| 文档版本 | 发布日期 | 修订说明 | 对应硬件版本 | 对应软件版本 |
|----------|----------|----------|--------------|--------------|
| V0.1 | 2024-4-3 | 首次正式发布 | BM1688 EVB:V1.5 | v1.5 |

## 声明

Copyright ©️2022 北京算能科技有限公司。

我们对本产品手册及其中的内容具有全部的知识产权。除非特别授权，禁止复制或向第三方分发。凡侵犯本公司版权等知识产权权益的行为，本公司保留依法追究其法律责任的权利。

本产品系列将有不断地更新迭代，我们将定期检查本产品手册中的内容，在后续的版本中将出现不可避免的修正、删减、补充。

我们保留在不事先通知的情况下进行技术改进、文档变更、产品改进升级、增加或减少产品型号和功能的权利。

# 软件安装

## 软件更新

BM1688 出厂时已经预装系统软件，在Ubuntu下可通过如下命令检查其版本：

```bash
linaro@sophon:~$ bm_version
SophonSDK(BM1688) 1.7
sophon-soc-libsophon : 0.4.9
sophon-soc-libsophon-dev : 0.4.9
sophon-media-soc-sophon-ffmpeg : 1.7.0
sophon-media-soc-sophon-opencv : 1.7.0
BL2 bm1688:g 2024-07-23T07:28:45+00:00
BL31 bm1688:gc3fb9f5-dirty 2024-07-22T15:27:39+08:00
U-Boot 2021.10 (Jul 23 2024 -07:28:41 +0000) cvitek_sophgo
Kernelversion : Linux sophon 5.10.4-sophon-custom #1 SMP Tue Jul 23 07:28:49 UTC 2024 aarch64 aarch64 aarch64 GNU/Linux
Mode: soc mode
MCUVersion: 0.17.19
```

BM1688 目前提供支持的更新方式：SD卡刷机，USB烧录，OTA。其中SD卡刷机会重写整个eMMC，也即您存储在eMMC的数据全部会丢失。这种方式最为干净可靠，理论上只要您的 BM1688 没有硬件损坏，都可以进行SD卡刷机。文件替换方式是指在Ubuntu下通过替换对应文件的方式分别升级bootloader、kernel和其它软件。这种方式有一定的风险，如不同软件组件之间的版本匹配、文件损坏等。以下分别介绍两种软件更新方式的操作：

### a. SD卡刷机

请将SD卡格式化为FAT32格式（如果SD卡上有多个分区，只能使用第一个分区），大小为1GB以上。

请下载 BM1688 最新刷机包，地址为算能官网

```bash
https://developer.sophgo.com/site/index/material/all/all.html
```

请将下载的sdcard.tgz解压到SD卡根目录。确认文件如下（数量不一定相同）：

请将 BM1688 断电，插入SD卡，并连接串口终端，然后给 BM1688 上电。您将看到 BM1688 自动进入刷机流程：

刷机通常耗时约3分钟，结束后，会看到拔掉SD卡并重启 BM1688 的提示，请依照操作即可：

请注意：刷机后Ubuntu系统第一次启动时会进行文件系统初始化等关键动作，请勿随意断电，待开机进入命令行后使用sudo poweroff命令关机。

### b. USB烧录

**注意事项**

1、usb烧录的时候不能插入sd卡

2、usb_dl.exe要和cv_dl_magic.bin在同一目录下

3、usb_dl.exe所在的路径和要烧录的固件的路径不能有中文

**硬件连接**

1、使用跳线帽短路如图的位置(J2503 短接顺着字体的右侧两个脚)

2、准备一根typec USB线，一端接到板子的typec母口，另一端接到PC

**安装windows驱动**

运行CviUsbDownloadInstallDriver.exe，点击下一步，然后再点击完成即可

**烧录步骤**

1、打开windows控制台

2、把usb烧录工具放到本地（usb烧录工具的路径为<SDK>/build/tools/<chip>/usb_dl）

3、在usb_dl相同的目录新建文件夹fw，放入要升级的文件

4、执行升级命令：usb_dl.exe -c cv186x -s ubuntu -i ../fw

输入命令后，打印如下图

表示等待板子连接

5、用usb数据线连接电脑和设备

6、对设备重新上下电（如果usb数据线也会供电，则在下电的时候，还要拔出usb线）

### c. OTA

OTA升级会重写除data分区外的所有分区，data分区的数据会被保留，但还是建议用户升级前能备份data分区数据。

**web升级步骤**

1、通过chrome浏览器访问192.168.150.1:8080

2、输入密码登录成功后进入到系统升级界面

3、点击选择文件，选中sdcard.tgz后点击上传文件

4、待完成上传操作后，点击开始升级

5、等待升级自动完成

**使用串口命令行升级步骤**

1、需要将sdcard.tgz 拷贝到U盘

2、插上U盘，系统会自动识别U盘并挂载到/media/storage-hot-sda1/

3、将sdcard.tgz解压到/data/ota目录

4、移动刷机包内容到/data/ota目录，即

```shell
mv /data/ota/sdcard/* /data/ota
```

5.执行 /data/ota/local_update.sh /data/ota/md5.txt

6.等待系统升级完成

## 构建安装包

除了使用已有的安装包进行升级外，也可以自行构建安装包。

### 安装ubuntu

推荐安装ubuntu 20.04

注：使用docker编译软件的可以选择其它ubuntu版本，直接使用ubuntu系统编译的必须要选择20.04，以下环境配置相关的均为20.04

### 配置编译环境

1、配置repo安装路径

```shell
mkdir ~/bin
```

2、增加环境变量

```shell
vim ~/.profile
```

在文件的最后添加PATH=~/bin:$PATH

3、安装repo

```shell
curl https://storage.googleapis.com/git-repo-downloads/repo > ~/bin/repo
```

4、安装相关软件包

```shell
sudo apt-get update

sudo apt-get install -y build-essential ninja-build automake autoconf libtool wget \
curl git gcc libssl-dev bc slib squashfs-tools android-sdk-libsparse-utils \
android-sdk-ext4-utils jq cmake python3-distutils tcl scons parallel \
openssh-client tree python3-dev python3-pip ssh libncurses5 pkg-config \
lzop bison flex rsync kmod cpio sudo fakeroot dpkg-dev device-tree-compiler \
u-boot-tools uuid-dev libxml2-dev debootstrap qemu qemu-user-static kpartx \
binfmt-support git-lfs libisl-dev texlive-xetex libgflags-dev python3-sphinx nasm
```

5、安装升级python库

```shell
pip3 install dfss --upgrade
```

### 配置本地github账号

在github官网建立个人账号，并配置好ssh key，下载代码需要用到个人github账号

1. 设置账号邮箱

```shell
git config --global user.name "your_name"

git config --global user.email "your_email@example.com"
```

2. 配置密钥

```shell
ssh-keygen -t ed25519 -C "your_email@example.com"

cat ~/.ssh/id_ed25519.pub
```

将公钥添加到github

获取github公钥配置到本地ssh信任列表

```shell
ssh-keyscan github.com >> ~/.ssh/known_hosts 
```

验证ssh是否配置成功

```shell
ssh -T git@github.com
```

# 获取源码

提供两种源码的方式

## 1. 从github获取

获取最新SDK源码

```shell
repo init -u https://github.com/sophgo/manifest.git -m release/all_repos.xml
repo sync -j4 -d --force-sync --force-remove-dirty
```

获取指定SDK版本v2.0:

```shell
repo init -u https://github.com/sophgo/manifest.git -m release/v2.0_all_repos.xml
repo sync -j4 -d --force-sync --force-remove-dirty
```

获取指定SDK版本v1.9:

```shell
repo init -u https://github.com/sophgo/manifest.git -m release/v1.9_all_repos.xml
repo sync -j4 -d --force-sync --force-remove-dirty
```

## 2. 从算能官网获取

从算能官网 (https://developer.sophgo.com/site/index/material/all/all.html) 下载BM1688 & CV186AH选项中最新SDK，然后执行下面的命令可获取SDK最新版本

```shell
unzip sophonsdk_v2.x_source_code.zip
cd sophonsdk_v2.x_source_code
tar -xvf 1688_v2.x_source.tgz
```

进入代码主目录(注：目录名称在每个版本可能会有改动,代码主目录中包含.repo目录)

```shell
repo sync -j4 -d --force-sync --force-remove-dirty
```

注：如果更新代码遇到错误可以尝试使用以下命令恢复后再更新

1. 更新repo库后再更新代码
   ```shell
   cd .repo/repo && git pull && cd - && repo sync
   ```

2. 清除所有仓库中没有被git跟踪的文件及目录
   ```shell
   repo forall -c git clean -fdx
   ```

3. 还原所有仓库代码到git记录的最新，有修改代码的情况注意做备份
   ```shell
   repo forall -c git reset --hard HEAD
   ```

4. 删除本地代码重新还原，同命令3，如果有修改代码的情况注意做备份
   ```shell
   rm * -rf && repo sync -j4 -d --force-sync --force-remove-dirty
   ```

# 文件结构

SDK文件结构说明如下:

```
top
├── build                         ## 编译脚本集合
├── fsbl                          ## ATF
├── host-tools                    ## 编译工具链
├── isp_tuning                    ## isp tuning工具
├── libsophon                     ## 多媒体及tpu库
├── linux_5.10                    ## linux内核
├── middleware                    ## isp库
├── osdrv                         ## 驱动
├── oss                           ## 开源代码库
├── ramdisk                       ## ram disk
├── sophon_media                  ## ffmpeg与opencv库
├── u-boot-2021.10                ## uboot
├── libsophon                     ## tpu及tpu驱动
├── libsophon/libsophav           ## 多媒体hal层
└── ubuntu/bootloader-arm64       ## 边侧文件系统依赖
```

# 导入docker

docker主要是用来编译边侧代码刷机包的，如果是更新代码请退出docker环境进行更新。

## 1、运行dfss，如果python不能用就用python3

```shell
python -m dfss --url=open@sophgo.com:/gemini-sdk/docker/bm1688_docker.tar
```

或者从如下官网获取，下载成功后改为bm1688_docker.tar再进行第2步操作

https://sophon-assets.sophon.cn/sophon-prod-s3/drive/25/06/11/18/docker.zip

## 2、导入docker镜像，有导入过的可以不用操作

```shell
sudo apt-get update
sudo apt-get install -y docker.io
docker load -i bm1688_docker.tar
```

## 3、将以下命令添加到~/.bashrc，并执行source ~/.bashrc

```shell
function run_docker() {
 docker run -e LOCAL_USER_ID=`id -u $USER_ID` --privileged -v /dev:/dev -itd -v $2:/project/$1 --name $1 bm1688_docker:latest /bin/bash
}
```

## 4、进入docker目录工作目录会转换成/project/user.name/，这里请在进入docker前将代码下载到/your/workspace/path

```shell
run_docker sophon /your/workspace/path
cd /project/sophon/   (在此目录下可以找到提前下载好的代码)
```

## 5、进入docker容器中的shell

```shell
docker exec -it sophon /bin/bash
```

## 6、退出docker容器

```shell
exit
```

# 编译边侧固件

ubuntu编译，请在docker环境中执行

```shell
source build/envsetup_soc.sh
defconfig edge_wevb_emmc (注: 1.8版本及以前的版本是 bm1688_wevb_emmc)
clean_edge_all (清除旧的编译目标文件,1.8版本及以前是 clean_bm1688_all)
build_edge_all (边侧全编译,1.8版本及以前是build_bm1688_all)
```

## 部分编译

注：需要在全编译一次后才能支持部分编译打包

- `build_kernel && build_edge_rootfs` (只更新kernel)
- `build_uboot && build_edge_rootfs` (只更新uboot或者atf)
- `build_libsophon && build_edge_rootfs` (只更新libsophon)
- `build_sophon_media && build_edge_rootfs` (只更新sophon_media)
- `build_v4l2_isp && build_edge_rootfs` (只更新isp)

## buildroot编译

```shell
source build/envsetup_soc.sh
defconfig edge_buildroot
clean_edge_all
build_edge_all
```

# 烧录边侧固件

ubuntu固件：将编译生成的刷机包，即install/soc_edge_wevb_emmc/package_edge/sdcard内容拷贝到tf卡根目录即可使用sd升级

buildroot固件：固件生成的位置在install/soc_edge_buildroot/upgrade.zip，解压放在tf卡根目录，插平台后重新上电即可升级

# 硬件安装

## 板卡安装

BM1688 AI计算模组仅指包括BM1688、LPDDR4X、eMMC等核心组件的板卡

为方便后面的描述，下文以"核心板"指代这块板卡。

## 附件安装

为方便调试，建议您准备如下附件：

a. USB转UART线缆一条：核心板引出的UART0(UART for BM1688)为调试口，TTL电平，波特率115200，8比特数据，1比特停止位，无奇偶校验，无硬件流控。

b. 以太网线缆一条：接以太网口0（eth0），预装系统默认设置为DHCP，所以将 BM1688 通过eth0和您的调试机都部署在同一路由器下比较方便。

c. SD卡一张：刷机或调试时使用，建议8GB/class10或更高规格。

d. 与您的底板设计相匹配的电源：如果您使用我们提供的参考底板，电源适配器，默认规格：220V AC IN，12V 5A OUT。

e. 散热：请安装散热片、风扇等必要的散热设备，以免出现过热关机等异常状况。

## 上电开机

一切就绪后，您就可以为底板加电了，如果您使用我们提供的参考底板进行串口连接，需要准备一根Micro B USB线，一端接到板子的Micro B母口，另一端接到PC连接好串口后，串口示意图参考5.11节示意图5.1。

请先插上电源（此时从串口终端应该也应可以看到log打印了）。请检查您的串口终端，BM1688 出厂时已经预装Ubuntu 20.04系统，初始用户名和密码均为linaro（root账户无初始密码，使用前需要先用linaro账户做sudo passwd root设置密码）：

```bash
Ubuntu 20.04 LTS sophon ttyS0

sophon login: linaro
Password:
Welcome to Ubuntu 20.04 LTS (GNU/Linux 5.10.4-tag--g09c5e5af6d9b aarch64)

* Documentation:  https://help.ubuntu.com
* Management:     https://landscape.canonical.com
* Support:        https://ubuntu.com/advantage

* Strictly confined Kubernetes makes edge and IoT secure. Learn how MicroK8s
just raised the bar for easy, resilient and secure K8s cluster deployment.

https://ubuntu.com/engage/secure-kubernetes-at-the-edge
overlay / overlay rw,relatime,lowerdir=/media/root-ro,upperdir=/media/root-rw/overlay,workdir=/media/root-rw/overlay-workdir 0 0
/dev/mmcblk0p5 /media/root-rw ext4 rw,relatime 0 0
/dev/mmcblk0p4 /media/root-ro ext4 ro,relatime 0 0

Last login: Fri Sep  8 20:07:47 CST 2023 on ttyS0
linaro@sophon:~$
```

检查IP地址请使用ifconfig或ip a命令:

```bash
ifconfig
ip a
```

如果需要手工配置静态IP，可按如下方法修改/etc/netplan/01-netcfg.yaml配置文件，并使能所修改的配置文件：

```bash
$ cat /etc/netplan/01-netcfg.yaml
network:
        version: 2
        renderer: networkd
        ethernets:
                eth0:
                        dhcp4: no                        # 静态IP需要改成no, 动态IP则为yes
                        addresses: [192.168.1.100/24]    # 加上IP，动态ip则中括号内放空即可
                        optional: yes
                        dhcp-identifier: mac             # 静态IP需要删掉这行
                eth1:
                        dhcp4: no
                        addresses: [192.168.150.1/24]
                        optional: yes
                enp3s0:
                        dhcp4: yes
                        addresses: []
                        dhcp-identifier: mac
                        optional: yes
$ sudo netplan try      # 测试配置是否可用
$ sudo netplan apply    # 使能最新配置
```

拿到IP地址后就可以使用ssh登录了，端口号为22，用户名密码同样均为linaro。

```bash
ssh linaro@your_ip
```

关机时建议使用sudo poweroff命令，尽量避免直接断电，以免文件系统损坏。

核心板有两个网卡，eth0默认为DHCP，故您需要通过上述方法获取IP。eth1默认配置为静态IP：192.168.150.1。

# 系统软件构成

## 启动流程

BM1688 的系统软件属于典型的嵌入式ARM64 Linux，由bootloader、kernel、ramdisk和Ubuntu 20.04构成，当开机后，依次执行如下：

其中：boot ROM、bootloader基于fsbl和u-boot构建；kernel基于Linux的5.10分支构建；Ubuntu 20.04基于Ubuntu官方arm64源构建，不包含GUI相关组件。

## eMMC分区

| 分区设备文件   | 挂载点         | 文件系统 | 内容                             |
|---------------|---------------|----------|----------------------------------|
| /dev/mmcblk0p1 | /boot         | FAT32    | 存放kernel和ramdisk镜像         |
| /dev/mmcblk0p2 | /recovery     | EXT4     | 存放recovery mode镜像           |
| /dev/mmcblk0p3 | 无            | 无       | 存放配置信息，目前未使用        |
| /dev/mmcblk0p4 | /media/root-ro | EXT4    | Ubuntu 20.04系统的read-only部分 |
| /dev/mmcblk0p5 | /media/root-rw | EXT4    | Ubuntu 20.04系统的read-write部分|
| /dev/mmcblk0p6 | /data         | EXT4     | 存放sophon                      |

# 文件系统支持

如果您使用参考底板，当插入U盘或者移动硬盘后（需考虑USB供电能力），存储设备会被识别为/dev/sdb1或类似节点，与桌面PC Linux环境下相同。文件系统支持FAT、FAT32、EXT2/3/4、NTFS。产品不支持自动挂载，所以需要手工进行挂载：`sudo mount /dev/sdb1 /mnt`。当访问NTFS格式的存储设备时，预装的内核版本仅支持读取，如果需要写入，需要手工安装ntfs-3g软件包，请参考https://packages.ubuntu.com/search?keywords=ntfs-3g。完成数据写入后，请及时使用sync或umount操作，关机时请使用sudo poweroff命令，避免暴力下电关机，以免数据丢失。

# Ethernet操作指南

## 操作示例

Ethernet模块默认为编入内核，不需另外执行加载操作。

内核下使用网口的操作步骤如下：

- 配置ip地址和子网掩码

```
sudo ifconfig eth0 xxx.xxx.xxx.xxx netmask xxx.xxx.xxx.xxx up
```

- 设置缺省网关

```
sudo route add default gw xxx.xxx.xxx.xxx
```

- 挂载 nfs

```
sudo busybox mount -t nfs -o nolock xxx.xxx.xxx.xxx:/your/path /mount-dir
```

示例：`sudo busybox mount -t nfs -o nolock 192.168.2.10:/NFS /mnt/sd`

### tftp使用说明

- 首先在Windows下打开Tftp server

1. 如果没有tftp工具，请先下载tftpd64工具，链接为https://pjo2.github.io/tftpd64/；
2. 点击Download page，下载tftpd64位软件安装包后，安装tftpd工具；
3. 对tftpd64工具进行以下配置；

可以点击Browse按键将图中的Current Directory设置为tftp进行文件传输的路径比如：C:\Program Files\Tftpd64；

Server interfaces设置为本机的网络接口，例如192.168.137.1；

进入setting界面,勾选TFTP页面中的Reduce '//' in file path。

注意：请一定要使用64位软件，并勾选Reduce '//' in file path。

在windows下打开Tftp server之后可以在uboot以及kernel下从PC端的Tftp server下载文件。

- uboot下通过tftp下载

1. 将板卡和PC通过网线连接，使用串口线连接PC和板卡，打开PC的串口终端。
2. 上电后在看到串口终端提示Hit any key to stop autoboot时按下回车进入u-boot的命令行模式，看到提示符sophon#
3. 输入以下命令配置网络：

```
setenv ipaddr 192.168.137.11
setenv gatewayip 192.168.337.1
setenv serverip 192.168.137.1;
```

ipaddr是板端IP，serverip是tftp server所在PC的IP，gatewayip是网关地址。

4. 输入以下命令开始tftp下载：

```
tftp xxxxxxxxx filename
```

这条命令表示从tftp server上下载名filename的文件到地址xxxxxxxxx。

5. 通过tftp升级系统

产品支持在uboot阶段通过tftp升级系统，请先下载可以使用的系统安装包tftp.tgz。将安装包解压缩后，把所有的安装文件拷贝到PC server的Current Directory路径下。
此时点击PC server的Show Dir按键，可以显示路径下的系统升级文件。

在配置网络后输入以下命令进行系统升级：

```
tftp 0x120000000 boot.scr   // 下载boot.scr到0x120000000
source 0x120000000          //执行boot.scr文件
```

此时串口会打印以下信息，并使用"#"提示升级进度。

耐心等待直到串口打印"Please remove the installation medium, then reboot",系统升级成功。

- kernel下通过tftp上传下载

在PC端运行Tftp server后，将板卡和PC通过网线连接。进入系统后输入以下命令下载文件和上传文件。

下载文件：

```
sudo busybox tftp –g -r [remote file name] [server ip]
```

备注: remote file name 为欲下载的文件名称，server ip为下载文件所在server的ip地址 (ex：sudo busybox tftp -g -r test.txt 192.168.0.11)。

上传文件：

```
sudo busybox tftp –p -l [local file name] [server ip]
```

备注: local file name 为本地欲上传的文件名称，server ip为上传文件的目标server的ip地址 (ex：sudo busybox tftp -p -l test.txt 192.168.0.11)。

## IPv6说明

IPv6环境配置方法如下：

- 配置ip地址以及网关

```
sudo ip -6 addr add <ipv6 address>/ipv6 prefixlen dev <port name>
```

示例：`sudo ip -6 addr add 3FFE:FFFF:7654:FEDA:1245:BA98:3210:4564/64 dev eth1`

- Ping指定的IPv6地址

```
ping -6 <ipv6 address>
```

示例：`ping -6 3FFE:FFFF:7654:FEDA:1245:BA98:3210:4563`

## IEEE 802.3x流控功能

### 流控功能描述

BM1688 Ethernet支持IEEE 802.3x所定义的流控功能，透过发送流控帧以及接收对端所发送过来的流控帧的方式来达到流控的目的。

- 发送流控帧：

在接收由对端发送过来的封包的过程中，若发现目前接收端的接收对列可能无法满足接收后续送达的封包时，则本地端会发送流控帧至对端，要求对端暂停一段时间不发送封包，藉此来进行流量控制。

- 接收流控帧：

当本地端接收到由对端发送过来的流控帧时，本地端会根据帧内的流控时间描述延迟发送封包至对端，等到过了流控延迟时间后，再启动发送。若在等待过程中收到了由对端发送的流控帧其描述的流控时间为0时，则会直接启动发送。

### 流控功能配置

发送流控帧功能的相关文件配置在linux/drivers/net/ethernet/stmicro/stmmac/stmmac_main.c

```c
static int flow_ctrl = FLOW_AUTO;
module_param(flow_ctrl, int, 0644);
MODULE_PARM_DESC(flow_ctrl, "Flow control ability [on/off]");

static int pause = PAUSE_TIME;
module_param(pause, int, 0644);
MODULE_PARM_DESC(pause, "Flow Control Pause Time");
```

若欲修改默认pause time，可配置 pause至目标植。

### ethtool配置接口流控功能

用户可以通过标准ethtool工具接口进行流控功能的使能。

ethtool –a eth0 命令查看eth0口流控功能状态；打印如下

```
# ethtool -a eth0
Pause parameters for eth0:
Autonegotiate: on
RX: off
TX: off
```

其中，RX流控是关闭的，TX流控是关闭的；用户可以通过以下命令打开或关闭TX流控：

```
# ethtool -A eth0 tx off（关闭TX流控）                             
# ethtool -A eth0 tx on（打开TX流控）                              
```

备注：ethtool工具默认不会编入文件系统，需要用户在需要时候加入。

# USB操作指南

## 操作准备

USB 3.0 Host/Device的操作准备如下:

- Linux 内核使用SDK发布 Kernel。
- 文件系统可以使用本地文件系统ext4或squashfs，也可以使用NFS。
- Shell script"run_usb.sh"。run_usb.sh使用内核的USB ConfigFS功能来客制化USB device装置.使用者可参考并修改run_usb.sh来变更PID/VID与function的相关参数。详细操作可参考内核文件" linux/Documentation/usb/gadget_configfs.txt"。

## linux Host

### USB 3.0 Host 操作过程 (以 usb1 为例)

步骤1. 启动平台，加载ext4或squashfs，也可以使用NFS。

步骤2. 设置usb角色

`echo host > /sys/kernel/debug/usb/39110000.usb/mode`

### U盘操作范例

插入检测：

直接插入U盘，观察是否枚举成功。
正常情况下串口打印为:

```
[ 72.061964] usb 1-1: new high-speed USB device number 2 usingdwc2
[ 72.315816] usb-storage 1-1:1.0: USB Mass Storage device detected
[ 72.335934] scsihost0: usb-storage 1-1:1.0
[ 73.363027] scsi 0:0:0:0: Direct-Access Generic STORAGE DEVICE1532 PQ: 0 ANSI: 6
[ 73.374407] sd 0:0:0:0: Attached scsigeneric sg0 type 0
[ 73.558597] sd 0:0:0:0: [sda] 30253056 512-byte logical blocks:(15.5 GB/14.4 GiB)
[ 73.566961] sd 0:0:0:0: [sda] Write Protect is off
[ 73.571922] sd 0:0:0:0: [sda] Mode Sense: 21 00 00 00
[ 73.577899] sd 0:0:0:0: [sda] Write cache: disabled, read cache:enabled, doesn't support DPO or FUA
[ 73.593961] sda: sda1[ 73.602607] sd 0:0:0:0: [sda] Attached SCSI removable disk
```

其中，sda1表示U盘或移动硬盘上的第一个分区，当存在多个分区时，会出现sda1，sd2，sda3等字样。

初始化及应用：

插入检测后，进行如下操作:

sdXY中X代表磁盘号，Y代表分区号，请根据具体系统环境进行修改。

- 分区命令操作的具设备节点为sdX，范例: `~$ fdisk /dev/sda`。
- 用mkdosfs工具格式化的具体分区为sdXY: `~$ mkdosfs -F 32 /dev/sda1`。
- 挂载的具体分区为sdXY: `~$ mount /dev/sda1 /mnt`。

1. 查看分区信息
   - 运行命令"ls /dev"查看系统设备文件，若没有分区信息sdXY，表示还没有分区。请用fdisk进行分区后进入步骤2。
   - 若有分区信息sdXY，则已经检测到U盘分区，进入步骤2。

2. 查看格式化信息
   - 若没有格式化，请使用mkdosfs进行格式化后进入步骤3。
   - 若已格式化，进入步骤3。

3. 挂载目录
   - 运行"mount /dev/sdaXY /mnt"挂载目录。

4. 对硬盘进行读写操作

## linux Device

### USB 3.0 Device 操作过程 (以 usb0 为例)

步骤1. 编译USB3.0 Device相关的内核驱动模块

- 进入menuconfig的如下路径，并配置如下。

```
Device Driver --->
   [*] USB support --->
      <*> USB Gadget Support --->
         <M> USB functions configurable through configfs
         [*] Abstract Control Model (CDC ACM)
         [*] Mass storage
```

- 编译内核模块，生成.ko文件。

步骤2. 加载驱动
`insmod /mnt/system/ko/usb_f_mass_storage.ko`

步骤3. 启动平台，加载ext4或squashfs文件系统，也可以使用NFS。

步骤4. 將otg controller 切换至device mode

步骤5. `echo device > /sys/kernel/debug/usb/39010000.usb/mode`

步骤6. 运行shell script "run_usb.sh"

```
/etc/run_usb.sh probe msc /dev/mmcblkXY
/etc/run_usb.sh start
```

其中mmcblkXY为第X个磁盘的eMMC或SD中第Y个分区。请用户根据具体情况选择。

步骤7. 在Host端可将平台当成一个普通的USB存储设备，对其进行分区，格式化，读写等。

### USB Device终端设备操作范例

平台作Device时可当作终端设备，操作如下:

步骤1. 插入模块。
```
insmod /mnt/system/ko/u_serial.ko
insmod /mnt/system/ko/usb_f_acm.ko
insmod /mnt/system/ko/usb_f_serial.ko
```

步骤2. 將otg controller 切换至device mode

`echo device > /sys/kernel/debug/usb/39010000.usb/mode`

步骤3. 运行shell script "run_usb.sh"
```
/etc/run_usb.sh probe acm
/etc/run_usb.sh start
```

通过USB将平台与Host端相连，即可在Host端将平台识别成USB终端设备，并在/dev目录下生成相应的设备节点ttyACMX，X 为同类型终端设备号码。在device端/dev目录下会生成ttyGSY，Y为同类型终端设备号码。

Host和Device可透过终端设备进行数据传输。

### USB Device RNDIS设备操作范例

平台作Device时可当作RNDIS设备，操作如下:

步骤1. 插入模块。
```
insmod /mnt/system/ko/u_ether.ko
insmod /mnt/system/ko/usb_f_ecm.ko
insmod /mnt/system/ko/usb_f_eem.ko
insmod /mnt/system/ko/usb_f_rndis.ko
```

步骤2. 將otg controller 切换至device mode

`echo device > /sys/kernel/debug/usb/39010000.usb/mode`

步骤3. 运行shell script "run_usb.sh"
```
/etc/run_usb.sh probe rndis
/etc/run_usb.sh start
```

步骤4. 通过USB将平台与Host端相连，即可在Host端将平台识别成USB Remote NDIS设备，在Windows安装"Remote NDIS Compatible Device"驱动。

步骤5. 在单板设定IP地址，例如"ifconfig usb0 192.168.3.101 up"。

步骤6. 在Window设定IP地址。

Host和Device可透过RNDIS设备进行数据传输。

## 操作中需注意问题

操作中需要注意的问题如下:

- 系统开机后默认是Host mode。若要使用Device mode须加载模块并执行USB ConfigFS 脚本。当切换Device前，用户须确认以下事项：
  - USB Cable未连接Host。
  - 平台上的硬件须切换到对应的USB mode。例如: 在切换到Device mode前，须关闭平台上的USB 5V供电。若平台上有带Hub,需关闭Hub电源并切换路径Switch到Device mode connector。

- 切换为Device mode后，若要再使用Host mode，用户须重新启动平台。

- 当平台做终端设备时，因TTY终端特性，若在短时间内传送大量数据, 可能造成数据遗失。用户使用此功能须注意此限制。

- 在Uboot下使用USB Host读取U盘时，注意若平台上有Hub，须打开Hub电源并切换路径Switch到正确的Connector。

# SD/MMC 卡操作指南

## 操作准备

1. 使用SDK 发布的 U-boot 和 kernel。
2. 文件系统：对于SD/MMC卡来说，SDK仅支持FAT文件系统，支持可读可写。启动至kernel后需挂载至/mnt/sd目录或根据项目需求的目录即可。
3. 可透过fdisk工具实现分区的工作。
4. BM1688 SD 支持 2.0与3.0：目前SD卡支持1.8/3.3V VDDIO，EMMC仅支持1.8V，使用者需注意。

## 操作过程

5. 默认SD/MMC 相关驱动模块已全部编入内核，不需再额外执行加载命令。
6. 插入卡片上电启动，可以在U-boot下，通过fat相关指令查看卡片内容。启动平台至kernel后，会自扫卡识别产生响应节点：/dev/mmcblk0和/dev/mmcblk0p1。
7. Uboot下卡片不支持热插拔操作，kernel下支持热插拔。在kernel下插入 SD 卡，就可以对 SD卡进行相关的操作。具体操作请参见"3.3 操作示例"

## 操作示例

SD 卡的读写操作示例如下。

**初始化及应用：**

待 SD卡插入后，进行如下操作（下文 X 为分区号，其值由 fdisk 工具进行分区时决定）：
指定fdisk 操作的具体目录为：`~ $ fdisk /dev/mmcblk0` // 需分情况讨论，如果是EMMC启动，SD的设备节点通常是 /dev/mmcblk1 或 /dev/mmcblk2。

步骤1. 检查分区信息

a. 若没有显示出 p1，表示SD卡还没有分区， 请在Linux下用 fdisk 工具进行分区或是在windows系统上将SD卡进行格式化之后，进入步骤 2。

b. 若有显示分区信息 p1，则表示 SD卡已经被检测到，并已进行过分区，可进入步骤 2进行挂载。

步骤2. 挂载

`~ $ mount /dev/mmcblk1pX /mnt/sd`，此命令会将SD卡上第X个分区挂载至/mnt/sd目录

# 操作中需要注意的问题

## 1. 硬件接触
需确保SD卡与卡槽硬件脚位接触良好，如若接触不良，有可能会出现检测错误或读写数据错误相关错误信息，并导致读写失败。

## 2. 挂载与卸载操作
每次插入SD卡后，都需要做一次挂载操作，才能读写SD卡；如果SD卡已经挂载到文件系统，拔卡前则必须做一次卸载（umount）操作，否则有可能在下次插入SD卡后看不到SD卡分区。另，异常拔卡亦需要进行卸载动作。

## 3. 分区与文件系统
必须确保SD卡已经创建分区，并将该分区格式化为FAT或FAT32文件系统（LINUX下通过fdisk命令，Windows下使用磁盘管理工具）。

## 4. 正常操作过程中的禁止事项

- 读写SD卡时不要拔卡，否则会打印一些异常信息，并且可能会导致卡中文件或文件系统被破坏。
- 若当前目录是处于挂载目录之下如/mnt/sd时，则无法进行卸载操作，必须离开当前目录如/mnt/sd，才能进行卸载操作。
- 系统中读写挂载目录的进程没有完全结束前，不能进行卸载操作，必须完全结束操作挂载目录的任务才能正常卸载。

## 5. 异常处理操作

1. 如果因为读写数据或其它不明原因导致文件系统被破坏，读写SD卡时可能会出现文件系统错误信息，这时需要进行卸载操作，拔卡，再次插卡并挂载，才能再次正常读写SD卡。
2. 因为SD卡的注册，检测/注销过程需要一定的时间，因此拔卡后若再快速地插入卡，有可能会出现检测不到SD卡的现象。
3. 如果在测试过程中异常拔卡，使用者需要按ctrl+c以回退出到kernel shell下，否则会一直不停地打印异常信息。
4. SD卡上有一个以上的分区时，可以通过挂载操作切换挂载不同的分区，但最后需确认挂载操作的次数与卸载操作次数相等，才能确保完全卸载所有的挂载分区。

# I2C操作指南

## 操作准备

I2C的操作准备如下：
- 使用SDK发布的kernel。

## 操作过程

- 加载内核。默认I2C相关模块已全部编入内核，不需要再执行加载命令。
- 在控制台下运行I2C读写命令或者自行在内核态或者用户态编写I2C读写程序，就可以对挂载在I2C控制器上的外围设备进行读写操作。

## 接口速率设置说明

如果要更改接口速率，需要修改build/boards/default/dts/sophon/sophon_base.dtsi中i2c node里的clock_frequency，如下所示，并重新编译内核。

```none
i2c0: i2c@29000000 {
   compatible = "snps,designware-i2c";
   clocks = <&clk CV186X_CLK_I2C0>;
   reg = <0x0 0x29000000 0x0 0x1000>;
   clock-frequency = <400000>;

   #size-cells = <0x0>;
   #address-cells = <0x1>;
   resets = <&rst RST_I2C0>;
   reset-names = "i2c0";
};
```

## I2C读写命令示例

可在linux终端上发iic相关命令detect总线设备和对总线上i2c设备进行读写。

1. i2cdetect -l
   检测系统中的iic总线（在BM1688中可为i2c-0~8）

2. i2cdetect -y -r N
   检测接到i2c-N总线上的所有设备地址，如下检测i2c-2上有哪些设备

3. i2cdump -f -y N M
   查看i2c-N上地址为M的设备中所有寄存器的值

4. i2cget -f -y 0 0x3c 0x00
   读取i2c-0上地址为0x3c的设备上0x00寄存器的值

5. i2cset -f -y 0 0x3c 0x40 0x12
   写入i2c-0上地址为0x3c的设备上0x40寄存器

## 内核态I2C读写程序示例

此示例说明在内核态下如何通过I2C读写程序对I2C外围设备进行读写操作。

**步骤1**
假设已知外围设备挂载在I2C控制器0上，调用i2c_get_adapter()函数以获得I2C控制器结构体adapter:
`adapter = i2c_ger_adapter(0);`

**步骤2**
透过i2c_new_device()函数关连I2C控制器与I2c外围设备，以得到I2C外围设备的客户端结构体client:
`client = i2c_new_device(adapter, &info)`
备注：info结构体提供i2c外围设备的设备地址

**步骤3**
调用I2C核心层提供的标准读写函数对外围设备进行读写操作：
`ret = i2c_master_send(client, buf, count);`
`ret = i2c_master_recv(client, buf, count);`
备注：client为步骤2所得之客户端结构体，buf为需要读写的寄存器地址以及数据，count为buf的长度。

代码示例如下：

```none
//宣告一个外围设备名字叫做"dummy"，设备地址为0x3c                     
static struct i2c_board_info info = {
               I2C_BOARD_INFO("dummy", 0x3C),
};
static struct i2c_client *client;

static int cvi_i2c_dev_init(void) {
   //分配 i2c控制器指针                                                  
   struct i2c_adapter *adapter;
   
   adapter =i2c_get_adapter(0);
   client = i2c_new_device(adapter, &info);
   i2c_put_adapter(adapter);
   return 0;
}

static int i2c_dev_write(char *buf, unsigned int count){
   int ret;

   ret = i2c_master_write(client, buf, count);
   return ret;
}

static int i2c_dev_read(char *buf, unsigned int count) {
   int ret;
   
   ret =i2c_master_recv(client, buf, count);
   return ret;
}
```

## 用户态I2C读写程序示例

此操作示例在用户态下通过I2C读写程序实现对I2C外围设备的读写操作。

**步骤1**
打开I2C总线对应的设备文件，获取文件描述符：

```none
i2c_file = open("/dev/i2c-0", O_RDWR);
   if (i2c_file < 0) {
      printf("open I2C device failed %d\n", errno);
      return -ENODEV;
   }
```

**步骤2**
进行数据读写：

```none
ret = ioctl(file, I2C_RDWR, &packets);
   if (ret < 0) {
      perror("Unable to send data");
      return ret;
   }
```

备注：需于flags指定读写操作

```none
struct i2c_msg messages[2];
   int ret;

   /*
   * In order to read a register, we first do a "dummy write" by writing
   * 0 bytes to the register we want to read from.  This is similar to
   * the packet in set_i2c_register, except it's 1 byte rather than 2.
   */
   outbuf = reg;
   messages[0].addr = addr;
   messages[0].flags = 0;
   messages[0].len = sizeof(outbuf);
   messages[0].buf = &outbuf;

   /* The data will get returned in this structure */
   messages[1].addr = addr;
   /* | I2C_M_NOSTART */
   messages[1].flags = I2C_M_RD;
   messages[1].len = sizeof(inbuf);
   messages[1].buf = &inbuf;
```

# SPI操作指南

## 操作准备

SPI的操作准备如下：
- 使用SDK发布的内核以及文件系统。文件系统可使用SDK所发布的squashFS或ext4。也可透过本地文件系统再透过网络挂载至NFS。

## 操作过程

- 加载内核。把SPI相关模块全部编入内核，不需要再执行加载命令。
- 在控制台下运行SPI读写命令或者自行在内核态或者用户态编写SPI读写程序，就可以对挂载在SPI控制器上的外围设备进行读写操作。

## 操作示例

### 内核态SPI读写程序示例

此操作示例说明在内核态下如何通过SPI读写程序实现对SPI外围设备的读写操作。

**步骤1**
调用SPI核心层函数spi_busnum_to_master()，以获取一个描述SPI控制器结构体：
`master = spi_busnum_to_master(bus_num);`
//bus_num为要读写的SPI外围设备所在的控制器号
//master为描述SPI控制器的spi_master结构体类型指针

**步骤2**
通过spi外围设备在核心层的名称调用SPI核心层函数取得挂载在SPI控制器上描述SPI外围设备的结构体：
`snprintf(str, sizeof(str), "%s.%u", dev_name(&master->dev), cs);`
`dev = bus_find_device_by_name(&spi_bus_type, NULL, str);`
`spi = to_spi_device(dev);`
//spi_buf_type为描述SPI总线的bus_type结构体类型变量
//spi为描述SPI外围设备spi_device结构体类型指针

**步骤3**
调用SPI核心层函数将spi_transfer添加到spi_message队列中。
`spi_message_init(&m)`
`spi_message_add_tail(&t, &m)`
//t为spi_transfer结构体类型变量
//m为spi_message结构体类型变量

**步骤4**
调用SPI核心层停工的读写函数对外围设备进行读写操作
`status = spi_sync(spi, &m);`
`status = spi_async(spi, &m)`
//spi为描述SPI外围设备的spi_device结构体类型指针
//spi_sync函数为进行spi同步读写操作
//spi_async函数为进行spi异步读写操作

代码示例如下：
此段代码示例仅供参考，而非实际应用功能。

```none
//传入SPI控制器总线号和片选号                                       
static unsigned int busnum;module_param(busnum, uint, 0);
MODULE_PARM_DESC(busnum, "SPI busnumber (default=0)");

static unsigned int cs;
module_param(cs, uint, 0);
MODULE_PARM_DESC(cs, "SPI chip select (default=0)");

extern struct bus_typespi_bus_type;

//宣告SPI控制器的结构体                                               
static struct spi_master *master;

//宣告SPI外围设备的结构体
static struct spi_device *spi_device;

static int __init spidev_init(void) {
   char *spi_name;
   struct device *spi;
   master =spi_busnum_to_master(busnum);
   spi_name = kzalloc(strlen(dev_name(&master->dev)), GFP_KERNEL);
   
   if (!spi_name)
      return -ENOMEM;
      
   snprintf(spi_name,sizeof(spi_name), "%s.%u", dev_name(&master->dev),cs);
   spi = bus_find_device_by_name(&spi_bus_type, NULL, spi_name);
   if (spi == NULL)
      return -EPERM;
   
   spi_device = to_spi_device(spi);
   if (spi_device ==NULL)
      return -EPERM;
   
   put_device(spi);
   kfree(spi_name);
   
   return 0;
}
int spi_dev_write(, void *buf,unsigned long len, int buswidth)
{
   struct spi_device *spi = spi_device;
   struct spi_transfer t = {
      .speed_hz = 2000000,
      .tx_buf = buf,
      //buf里需依外围设备规范填入device addr, register addr, write data等资讯                                                                  
      .len = len,
   };
   struct spi_message m;
   spi->mode = SPI_MODE_0;
   
   if (buswidth == 16)
      t.bits_per_word = 16;
      else
         t.bits_per_word = 8;
      if (!spi) {
         return -ENODEV;
      }
      spi_message_init(&m);
      spi_message_add_tail(&t, &m);
      return spi_sync(spi, &m);
}
int spi_dev_read(unsigned char devaddr, unsigned char reg_addr,void*buf, size_t len)
{
   struct spi_device *spi = spi_device;
   int ret;
   u8 txbuf[4] = { 0, };
   struct spi_transfer t = {
      .speed_hz = 2000000,
      .rx_buf =buf,
      .len = len,
      };
   struct spi_message m;
   spi->mode = SPI_MODE_0;
   
   if (!spi) {
      return -ENODEV;
   }
   txbuf[0] = devaddr;
   txbuf[1] = 0;
   txbuf[2] = reg_addr;//txbuf[1]&txbuf[2]需根据外围设备位宽来决定填写1 byte or 2 bytes，此范例为2     |bytes位宽                                                             
   t.tx_buf =txbuf;
   
   spi_message_init(&m);
   spi_message_add_tail(&t, &m);
   ret = spi_sync(spi, &m);
   
   return ret;
}
```

### 用户态SPI读写程序示例

此操作示例在用户态下实现对挂载在SPI控制器0上的SPI外围设备的读写操作。(具体实现可参考tools/spi/spidev_test.c)

**步骤1**: 打开SPI总线对应的设备文件，获取文件描述符。

```none
tatic const char *device = "/dev/spidev3.0";
…
fd = open(device, O_RDWR);
if (fd < 0)
   pabort("can't open device");
```

备注：SPI控制器1上挂载的外围设备默认节点为"dev/spidev1.0"
SPI控制器2上挂载的外围设备默认节点为"dev/spidev2.0"
SPI控制器3上挂载的外围设备默认节点为"dev/spidev3.0"
仅需替换节点名称即可，其馀操作与SPI控制器0上挂载的外围设备相同。

**步骤2**: 通过ioctl设置SPI传输模式：

```none
/* 
*spi mode
*/
ret = ioctl(fd, SPI_IOC_WR_MODE32, &mode);
if (ret == -1)
   pabort("can't set spi mode");
ret = ioctl(fd, SPI_IOC_RD_MODE32, &mode);
if(ret == -1)
   pabort("can't get spi mode");
```

备注：mode值配置请参考下图或是内核代码include/linux/spi/spi.h,
Ex. `mode = SPI_MODE_3 | SPI_LSB_FIRST;`

```c
#define SPI_CPHA 0x01 /* clock phase */
#define SPI_CPOL 0x02 /* clock polarity */
#define SPI_MODE_0 (0|0) /* (original MicroWire) */
#define SPI_MODE_1 (0|SPI_CPHA)
#define SPI_MODE_2 (SPI_CPOL|0)
#define SPI_MODE_3 (SPI_CPOL|SPI_CPHA)
```

**步骤3**: 通过ioctl设置SPI传输频宽：

```none
/*
* bits per word
*/
ret = ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
if (ret == -1)
   pabort("can't set bits per word");
ret = ioctl(fd,SPI_IOC_RD_BITS_PER_WORD, &bits);
if (ret == -1)
   pabort("can't get bits per word");
```

**步骤4**: 通过ioctl设置SPI传输速度（一般建议speed = 25M）：

```none
/*
* max speed hz
*/
ret = ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
if (ret == -1)
   pabort("can't set max speed hz");

ret = ioctl(fd,SPI_IOC_RD_MAX_SPEED_HZ, &speed);
if (ret == -1)
   pabort("can't get max speed hz");
```

# 步骤5: 使用ioctl进行数据读写：

```c
ret = ioctl(fd, SPI_IOC_MESSAGE(1), &tr);
if (ret < 1)
   pabort("can't send spi message");
```

备注： tr传输一帧消息的spi_ioc结构体数组首地址。

# GPIO操作指南

## GPIO的操作准备如下：

- 使用SDK发布的kernel

## 操作过程

- 默认GPIO相关模块已全部编入内核，不需要再执行加载命令。
- 在控制台下运行GPIO读写命令或者自行在内核态或者用户态编写GPIO读写程序，就可以对GPIO进行输入输出操作。

## 操作示例

### GPIO操作命令示例：

步骤1: 在控制台使用echo命令, 指定待操作的GPIO编号N：

```
echo N > /sys/class/gpio/export
```

N为待操作的GPIO编号，GPIO编号 = GPIO组号值 + 偏移值。

以原理图中GPIO_num管脚为例，num % 32 = base ... off，对应的组号为base，偏移值为off。
例如GPIO32，32 % 32 = 1 ... 0，则其组号为1，偏移值为0，组号1对应的组号值为448

因此GPIO编号N为448 + 0 = 448

计算编号公式：N = 480 - base*32 + off

组号值对应如下：

| 组号 | Linux组号值 |
|------|-------------|
| 组号0 | 480 |
| 组号1 | 448 |
| 组号2 | 416 |
| 组号3 | 384 |
| 组号4 | 352 |
| 组号5 | 320 |
| 组号pwr_gpio | 288 |

echo N > /sys/class/gpio/export 之后, 生成/sys/class/gpio/gpioN目录

步骤2: 在控制台使用echo命令设置GPIO方向：

设置为输入：
```
echo in > /sys/class/gpio/gpioN/direction
```

设置为输出：
```
echo out > /sys/class/gpio/gpioN/direction
```

例: 设置GPIO32 (即编号448)方向为输入：
```
echo in > /sys/class/gpio/gpio448/direction
```

设置GPIO32 (即编号448)方向为输出：
```
echo out > /sys/class/gpio/gpio448/direction
```

步骤3: 在控制台使用cat命令查看GPIO输入值, 或使用echo命令设置GPIO输出值：

查看输入值：
```
cat /sys/class/gpio/gpioN/value
```

输出低：
```
echo 0 > /sys/class/gpio/gpioN/value
```

输出高：
```
echo 1 > /sys/class/gpio/gpioN/value
```

步骤4: 使用完毕后, 在控制台使用echo命令释放资源：

```
echo N > /sys/class/gpio/unexport
```

注：可以通过打开 CONFIG_DEBUG_FS 选项开启gpio的sysfs debug功能，在操作前通过如下命令查看gpio pin具体对应的组号值：

```
cat /sys/kernel/debug/gpio
```

### 内核态GPIO操作程序示例：

**内核态GPIO读写操作程序示例：**

步骤1: 注册GPIO：

```c
gpio_request(gpio_num, NULL);
```

gpio_num为要操作的GPIO编号，该编号等于"GPIO组号 + 组内偏移号"

步骤2: 设置GPIO方向：

对于输入：`gpio_direction_input(gpio_num)`                           
对于输出：`gpio_direction_output(gpio_num, gpio_out_val)`

步骤3: 查看GPIO输入值或设置GPIO输出值：

查看输入值: `gpio_get_value(gpio_num)`                              
输出低：`gpio_set_value(gpio_num, 0)`
输出高：`gpio_set_value(gpio_num, 1)`

步骤4: 释放注册的GPIO编号：

```c
gpio_free(gpio_num);
```

**内核态GPIO中断操作程序示例：**

步骤1: 注册GPIO：

```c
gpio_request(gpio_num, NULL);
```

gpio_num为要操作的GPIO编号，该编号等于"GPIO组号 + 组内偏移号"

步骤2: 设置GPIO方向：

```c
gpio_direction_input(gpio_num);
```

对于要作为中断源的GPIO引脚，方向必须配置为输入

步骤3: 映射操作的GPIO编号对应的中断号：

```c
irq_num = gpio_to_irq(gpio_num);
```

中断号为gpio_to_irq(gpio_num)的返回值

步骤4: 注册中断：

```none
request_irq(irq_num, gpio_dev_test_isr, irqflags, "gpio_dev_test",&gpio_irq_type))
```

Irqflags为需要注册的中断类型，常用类型为：

- IRQF_SHARED ：共享中断；
- IRQF_TRIGGER_RISING ：上升沿触发；
- IRQF_TRIGGER_FALLING ：下降沿触发；
- IRQF_TRIGGER_HIGH ：高电平触发；
- IRQF_TRIGGER_LOW ：低电平触发

步骤5: 结束时释放注册的中断和GPIO编号：

```c
free_irq(gpio_to_irq(gpio_num), &gpio_irq_type);
gpio_free(gpio_num);
```

### 用户态GPIO操作程序示例：

**用户态GPIO读写操作程序示例：**

步骤1: 将要操作的GPIO编号export：

```c
fp = fopen("/sys/class/gpio/export", "w");
fprintf(fp, "%d", gpio_num);
fclose(fp);
```

gpio_num为要操作的GPIO编号，该编号等于"GPIO组号 + 组内偏移号"

步骤2: 设置GPIO方向：

```c
fp = fopen("/sys/class/gpio/gpio%d/direction", "rb+");
对于输入：fprintf(fp, "in");     
对于输出：fprintf(fp, "out");
fclose(fp);
```

步骤3: 查看GPIO输入值或设置GPIO输出值：

```c
fp = fopen("/sys/class/gpio/gpio%d/direction", "rb+");
查看输入：fread(buf, sizeof(char), sizeof(buf) - 1, fp);           
输出低:
   strcpy(buf, "0");
   fwrite(buf, sizeof(char), sizeof(buf) - 1, fp);
输出高:                                                             
   strcpy(buf,"1");
   fwrite(buf, sizeof(char), sizeof(buf) - 1, fp);
```

步骤4: 将操作的GPIO编号unexport：

```c
fp = fopen("/sys/class/gpio/unexport", "w");
fprintf(fp, "%d", gpio_num);
fclose(fp);
```

# UART操作指南

## UART的操作准备如下

- 使用SDK发布的kernel；
- 将需要测试的设备树节点status改为"okay"；

```none
uart0: serial@29180000 {
    compatible = "snps,dw-apb-uart";
    reg = <0x0 0x29180000 0x0 0x1000>;
    clock-frequency = <200000000>;
    reg-shift = <2>;
    reg-io-width = <4>;
    status = "okay";
};
```

## 操作过程

### 命令行操作示例：

- 设置好对应引脚的PINMUX；
- 执行以下指令设定波特率为115200，数据位8，停止位1（ttySx，x为0~8）：

```
stty -F /dev/ttySx ispeed 115200 ospeed 115200 cs8 stop 1
```

- 进行收发数据：

```
echo 123 > /dev/ttySx	# 向uartx输入123
cat /dev/ttySx
```

### 用户态UART操作程序示例：

```none
/* Open your specific device (e.g., /dev/mydevice): */
fd = open ("/dev/ttyS0", O_RDWR);
if (fd < 0) {
    /* Error handling. See errno. */
    return -1;
}

struct termios t;
tcgetattr(fd, &t);
cfsetispeed(&t, B115200); // 设置输入波特率为115200
cfsetospeed(&t, B115200); // 设置输出波特率为115200
t.c_cflag &= ~PARENB;   // 不使用奇偶校验
t.c_cflag &= ~CSTOPB;   // 使用1位停止位
t.c_cflag &= ~CSIZE;    // 清除数据位设置
t.c_cflag |= CS8;       // 设置数据位为8位
tcsetattr(fd, TCSANOW, &t);
// read/write ...
```

# Watchdog操作指南

## Watchdog的操作准备如下：

- 使用SDK发布的Linux kernel。

### 模块编译

- Linux WDT驱动默认是build-in形式，不需要手动编译和insmod。

## 操作示例

Watchdog SDK采用Linux标准WDT框架, 为用户提供操作接口。

- Watchdog 特征 

Watchdog 默认是开启的，默认超时时长30s，由内核负责喂狗，内核异常时会重启，客户可自行决定是否在用户层使用 Watchdog，

应用 open Watchdog设备节点后，喂狗操作转由用户层负责，内核停止喂狗，当用户层或者内核层异常时，都会触发wdt 重启设备。

Watchdog 支持高精度超时时长，可以配置并以任意超时时长工作，没有特殊限制（例如：只支持1秒, 2秒, 5秒, 10秒, 21秒, 42秒, 85秒，当使用者配置timtout时间为8秒, 驱动会选择大于等于该值的timeout即10秒）

- 使用方式

用户可以在Linux shell下运行Watchdog 操作命令或者自行在内核态或者用户态编写程序，操作硬件Watchdog

用户只需打开, start/stop wdt或设定timeout，即可使用watchdog。当watchdog timeout发生时, 系统重新启动.

注意：watchdog 默认以30s超时时长运行，设置超时时长需要先stop wdt

- 包含 WATCHDOG 接口头文件

```c
#include <linux/watchdog.h>
```

- 打开 WATCHDOG

open /dev/watchdog 或 /dev/watchdog0 设备节点，watchdog 即被启动。

```c
int wdt_fd = -1;

wdt_fd = open("/dev/watchdog", O_WRONLY);
if (wdt_fd == -1)
{
   // fail to open watchdog device
}
```

- 关闭 WATCHDOG

驱动支持"Magic Close", 在关闭watchdog前必须将magic字符'V'写入watchdog设备。
如果userspace daemon没有发送'V'而直接关闭设备，则watchdog驱动持续计数, 在给定时间内未喂狗仍会导致timeout, 系统重启.

参考代码如下：

```c
int option = WDIOS_DISABLECARD;

ioctl(wdt_fd, WDIOC_SETOPTIONS, &option);
if (wdt_fd != -1)
{
   write(wdt_fd, "V", 1);
   close(wdt_fd);
   wdt_fd = -1;
}
```

- 设定 TIMEOUT值

通过标准的 IOCTL 命令 WDIOC_SETTIMEOUT设定 timeout，单位为秒.

```c
int timeout = 10;
ioctl(wdt_fd, WDIOC_SETTIMEOUT, &timeout);
```

- PING watchdog (喂狗)

通过标准的 IOCTL 命令 WDIOC_KEEPALIVE喂狗.

```c
while (1) {
   ioctl(fd, WDIOC_KEEPALIVE, 0);
   sleep(1);
}
```

# PWM操作指南

## PWM的操作准备如下：

- 使用SDK发布的kernel。

### 操作过程

- 插入模块: insmod cv186x_pwm.ko;
- 在控制台下运行PMW读写命令或者自行在内核态或者用户态编写PWM读写程序，就可以对PWM进行输入输出操作;
- PWM 操作在定频时钟100MHz，共有20路，每路可单独控制;
- BM1688共有5个PWM IP (pwmchip0/ pwmchip4/ pwmchip8/ pwmchip12/ pwmchip16), 各IP控制4路讯号, 总共可控制20路讯号；
  电路图上以 pwm0~pwm19表示

在Linux sysfs中, pwm0~pwm3的device node各自如下：

/sys/class/pwm/pwmchip0/pwm0~3

在Linux sysfs中, pwm4~pwm7的device node各自如下：

/sys/class/pwm/pwmchip4/pwm4~7

以此类推

## 操作示例

### PWM操作命令示例：

步骤1:

在控制面板使用echo命令，配置待操作的PWM编号, 此例为PWM1：

```
echo 1 > /sys/class/pwm/pwmchip0/export
```

步骤2:

设置PWM一个周期的持续时间，单位为ns：

```
echo 1000000 >/sys/class/pwm/pwmchip0/pwm1/period
```

步骤3:

设置一个周期中的"ON"时间，单位为ns，即占空比=duty_cycle/period=50% ：

```
echo 500000 >/sys/class/pwm/pwmchip0/pwm1/duty_cycle
```

步骤4:

设置PWM使能

```
echo 1 >/sys/class/pwm/pwmchip0/pwm1/enable
```

### 通过文件IO操作程序示例：

**用户态GPIO读写操作程序示例：**

步骤1: 配置待操作的PWM编号, 以PWM1为例：

```c
fd = open("/sys/class/pwm/pwmchip0/export", O_WRONLY);
if(fd < 0)
{
dbmsg("open export error\n");
return -1;
}
ret = write(fd, "1", strlen("0"));
if(ret < 0)
{
dbmsg("Export pwm1 error\n");
return -1;
}
```

步骤2: 设置PWM一个周期的持续时间，单位为ns：

```none
fd_period = open("/sys/class/pwm/pwmchip0/pwm1/period", O_RDWR);
ret = write(fd_period, "1000000",strlen("1000000"));
if(ret < 0)
{
dbmsg("Set period error\n");
return -1;
}
```

步骤3: 设置一个周期中的"ON"时间，单位为ns: (此例占空比为50%)

```c
fd_duty = open("/sys/class/pwm/pwmchip0/pwm1/duty_cycle", O_RDWR);
ret = write(fd_duty, "500000", strlen("500000"));
if(ret < 0)
{
dbmsg("Set period error\n");
return -1;
}
```

步骤4: 设置PWM使能

```c
fd_enable = open("/sys/class/pwm/pwmchip0/pwm1/enable", O_RDWR);
ret = write(fd_enable, "1", strlen("1")); 
if(ret < 0) 
{
   dbmsg("enable pwm0 error\n");
   return -1;
}
```

# ADC操作指南

## ADC的操作准备如下

- 使用SDK发布的kernel

## 操作过程

- 插入模块: insmod cv186x_saradc.ko
- 在控制台下运行ADC读写命令或者自行在内核态或者用户态编写ADC读写程序，就可以对ADC进行输入输出操作
- 用户层通过访问IIO接口来实现5通道，12-bit ADC的触发、采样等操作
- 1.5v ref参考电压
- adc引脚和sysfs文件对应关系如下：
  - adc1 对应sysfs文件为 in_voltage1_raw
  - adc2 对应sysfs文件为 in_voltage2_raw
  - adc3 对应sysfs文件为 in_voltage3_raw
  - sar0 对应sysfs文件为 in_voltage4_raw
  - sar1 对应sysfs文件为 in_voltage5_raw
- 电压值计算公式：vol = val * 1500 / 4096，单位：mV

## 操作示例

### ADC操作命令示例

**步骤1:**
指定ADC通道 1~5, 此例为ADC1:
```
echo 1 > /sys/bus/iio/devices/iio\:device0/in_voltage1_raw
```

**步骤2:**
读出刚才指定的ADC channel值:
```
cat /sys/bus/iio/devices/iio\:device0/in_voltage1_raw
```

### 用户态ADC读取操作程序示例

**用户态ADC读写操作程序示例：**

```c
fd = open("/sys/bus/iio/devices/iio:device0/in_voltage1_raw", O_RDWR|O_NOCTTY|O_NDELAY);
if (fd < 0)
    printf("open adc err!\n");

write(fd, "1", 1);
lseek(fd, -1, SEEK_CUR);

char buffer[512] = {0};
int len = 0;
unsigned int adc_value = 0;

len = read(fd, buffer, 5);
if (len != 0) {
    printf("read buf: %s\n", buffer);
    adc_value= atoi(buffer);
    printf("adc value is %d\n", adc_value);
}
write(fd, "0", 1);
close(fd);
```

# PINMUX操作指南

## uboot下pinmux设置

u-boot下pinmux头文件u-boot-2021.10/board/cvitek/cv186x/pinmux目录下，要在uboot下配置pinmux，需要包含cv186x_pinmux.h，其中：

- PINMUX_CONFIG(PIN_NAME, FUNC_NAME, GROUP):
  - PIN_NAME：引脚名，对应pinlist文档中第一列的Signal Name
  - FUNC_NAME：功能名，对应pinlist文档中要切换的功能
  - GROUP：该功能所在group，对应pinlist文档中group列（具体见group_pin_t enum）

例如，要将PWR_WAKEUP0引脚的功能切为PWR_IRRX0：

- 首先，去pinlist中找到PWR_WAKEUP0引脚所在行，并找到group(7)和目标function(PWR_IRRX0)
- 在代码中通过PINMUX_CONFIG(PWR_WAKEUP0, PWR_IRRX0, G7)设置好pinmux
- 重新编译u-boot，烧录固件重启

## kernel下pinmux设置

kernel下pinmux头文件位于linux_5.10/drivers/pinctrl/cvitek/pinctrl-cv186x.h，使用同u-boot

## userspace下pinmux设置

userspace下提供了cvi_pinmux工具，支持设置pinmux、内部上下拉以及驱动能力，使用方法如下：

```bash
cvi_pinmux for bm1688
./cvi_pinmux -p          <== List all pins
./cvi_pinmux -l          <== List all pins and its func
./cvi_pinmux -r pin      <== Get func from pin
./cvi_pinmux -w pin/func <== Set func to pin
./cvi_pinmux -c <pin name>,<0 or 1 or 2>  <== Set pin pull up/down (0:pull down; 1:pull up; 2:pull off)
./cvi_pinmux -d <pin name>,<0 ~ 15>  <== Set pin driving
```

例如，要设置PWR_WAKEUP0引脚为PWR_IRRX0功能，并设置其内部上拉，驱动能力设置为15（0~15数值越大驱动能力越强）：

- cvi_pinmux -w PWR_WAKEUP0/PWR_IRRX0
- cvi_pinmux -c PWR_WAKEUP0,1
- cvi_pinmux -d PWR_WAKEUP0,15

另外，可以通过cvi_pinmux -l列出soc上所有pin和其functions，或通过cvi_pinmux -r pin_name，读取对应pin所包含的功能

# BM1688内置mcu功能说明

## BM1688内置mcu加载程序和启动

内置8051 mcu的固件已经放在"fsbl/plat/cv186x/prebuilt/cv186x_mcu_fw.bin"，编译fsbl时，固件被编入fip.bin。mcu固件将在bl2阶段加载。进入系统后可以查看使用以下命令检查mcu是否正在运行。

```bash
busybox devmem 0x05025018
```

通过这个命令检查寄存器的bit 1位是否为1，若为1，代表mcu已启动。 将此位写0，即可关闭mcu

## mcu根据OEM判断是否开启相关功能

mcu根据OEM中的product参数判断是否执行相关代码

fsbl阶段将OEM（256Byte）从EMMC的硬件boot1分区读入mcu的sram的最后256Byte。具体请见OEM说明

mcu读其中的product参数，若参数为SE9，则启用SE9相关功能。若参数为若参数为SE9Bx，则启用SM9相关功能。您可以进入kernel后使用下面的命令将SE9或SE9B写入OEM的product参数：

```bash
echo 0 > /sys/block/mmcblk0boot1/force_ro
echo "SE9" > se9.txt
dd if=se9.txt of=/dev/mmcblk0boot1 count=4 bs=1 seek=208
echo 1 > /sys/block/mmcblk0boot1/force_ro
```

## SE9内置mcu功能

目前内置mcu承担了两部分的功能，其一是负责ddr retrain的部分功能。其二是按键与led的相关需求。以下是mcu按键与led功能介绍

- 以下代码仅在SE9上运行：mcu通过读OEM的产品参数来判断是否是SE9。如果是则开启以下功能
- STAT指示灯在系统加载过程中亮红灯：mcu将pwr_gpio4拉低熄灭绿灯、pwr_gpio5拉高亮红灯
- SSD指示灯在系统加载过程中亮红灯：mcu将pwr_gpio3拉低熄灭绿灯、pwr_gpio6拉高亮红灯
- 电源指示灯开机长亮关机熄灭：mcu将pwr_gpio1拉低熄灭，拉高点亮
- 长按电源键2s下电：mcu检测到引脚PWR_BUTTON1低电平2s，通知系统层下电。三个指示灯熄灭
- 长按电源键5s下电：mcu检测到PWR_BUTTON1低电平5s，mcu控制系统下电。三个指示灯熄灭
- 短按电源键上电：mcu控制系统上电，电源指示灯亮绿灯。其他指示灯亮红灯
- 长按复位键12s恢复出厂设置：mcu检测到PWR_ON低电平12s，通知系统层恢复出厂设置并重启。STAT、SSD亮红灯
- 短按复位键重启：mcu检测到引脚低电平控制系统热重启。STAT、SSD亮红灯

mcu通过向0x0502601c写1通知系统层软件下电。写2通知系统层恢复出厂。另外mcu记录了由mcu触发的上下电原因，可以从寄存器0x05026030读出，0~3bit记录下电原因：

- 0x1：短按重启
- 0x2：长安12s回恢复出厂设置
- 0x4：长按2s下电
- 0x5：长按5s下电
- 0x6：127摄氏度过热下电

4~7bit记录上电原因：

- 0x1：短按重启
- 0x2：长按恢复出厂设置
- 0x3：短按上电

## SM9内置mcu功能

目前内置mcu承担了两部分的功能，其一是负责ddr retrain的部分功能。其二是按键的相关需求

- 以下代码仅在SM9上运行：mcu通过读OEM的产品参数来判断是否是SM9。如果是则开启以下功能
- 长按复位键12s恢复出厂设置：mcu检测到PWR_GPIO12低电平12s，通知系统层恢复出厂设置并重启

# CAN操作指南

## 准备过程

CAN 的操作准备如下：

- 使用 SDK 发布的 kernel

## 操作过程

加载内核，默认 CAN 驱动已经全部编入内核，不需要再执行加载命令

在控制台下使用 ip 命令配置 can 波特率，使用 cansend 发送数据，使用 candump 接收数据

使用 ifconfig -a 命令可以查看 can 的网络节点

## CAN 读写命令示例

波特率设置 CAN2.0 A/B 波特率设置成 250K

```bash
ip link set can0 up type can bitrate 250000
```

如果是CANFD模式，波特率设置成 250K 的方法如下

```bash
ip link set can0 type can bitrate 250000 sample-point 0.8 dbitrate 250000 dsample-point 0.75 fd on
```

打开 CAN 设备

```bash
ifconfig can0 up
```

接收 CAN 数据

```bash
candump can0
```

发送 CAN 数据

```bash
cansend can0 -i 0x55 0x12 0x13 0x14 0x13
```

其中 -i 是指定 CAN 发送帧的 ID，0x55 就是 CAN ID

芯片的 CAN 总线可以支持发送标准帧和拓展帧，但是在同一种配置下仅支持接收标准帧或者仅支持接收拓展帧。下面是切换接收模式的命令。默认状态下仅接收拓展帧

```bash
#切换模式前先关闭CAN
canconfig can0 stop 或者 ifconfig can0 down

#切换到仅接收标准帧模式
canconfig can0 ctrlmode STD on

#切换到仅接收拓展帧模式
canconfig can0 ctrlmode STD off

#打开CAN
canconfig can0 start 或者 ifconfig can0 up
```

切换模式是通过内核中的ctrlmode新增CAN_CTRLMODE_STD实现的

```c
#define CAN_CTRLMODE_STD 0x100
sdvt_can_dev->can.ctrlmode_supported = CAN_CTRLMODE_LOOPBACK |
                CAN_CTRLMODE_LISTENONLY |
                CAN_CTRLMODE_BERR_REPORTING |
                CAN_CTRLMODE_FD |
                CAN_CTRLMODE_ONE_SHOT |
                CAN_CTRLMODE_STD;
```

## 操作示例

内核态 can 读写程序示例:

此操作示例说明内核状态下如何接收 can 数据

步骤 1 调用 alloc_can_skb 函数，获得 can 网络节点的 skb

步骤 2 判断帧类型，调用 receive_remote_frame 或者 receive_frame 来读取 FIFO 中的数据，将接收到的数据传递给结构体 cf

```c
static void sdvt_can_read_fifo(struct net_device *dev)
{
    struct net_device_stats *stats = &dev->stats;
    struct sdvt_can_classdev *cdev = netdev_priv(dev);
    struct canfd_frame *cf;
    struct sk_buff *skb;
    int m_i_i   = 0;

    skb = alloc_can_skb(dev, (struct can_frame **)&cf);
    // cdev->ops->write_reg(cdev,SDVT_CAN_FIFO_FLUSH,0x2);
    if (!skb) {
        stats->rx_dropped++;
        return;
    }

    if(cmd_o.irq_status0_8b & (1 << SDVT_CAN_IRQ_REMOTE_FRAME)){
        // Read the length from RX LENGTH FIFO
        receive_remote_frame(cdev,&cmd_o,&cfg_o);
        cf->can_id = cmd_o.ident_32b | CAN_RTR_FLAG;
        netdev_dbg(dev, "remote frame\n");
    }else{
        receive_frame(cdev,&cmd_o,&cfg_o);
        cf->len =  cmd_o.rx_len_2d_8b[1];
        cf->can_id =  cmd_o.ident_32b;
        for (m_i_i = 0; m_i_i < cf->len; m_i_i += 1) {
            ((u_int8_t *)cf->data)[m_i_i] = cmd_o.rx_data_2d_8b[m_i_i];
        }
    }

    cmd_o.irq_status1_8b = 0x00;
    cmd_o.irq_status0_8b = 0x00;
    dev_info(cdev->dev,"\n");

    stats->rx_packets++;
    stats->rx_bytes += cf->len;
    netif_receive_skb(skb);
}
```

此操作示例说明内核状态如何发送 can 数据:

步骤 1 获得结构体 cf

# CAN 驱动发送函数示例

步骤2：从结构体 cf 获得的 cf->len 赋值给 cmd_o.dlc_4b，将 cf->data 赋值给 cmd_o.data_2d_8b，然后通过 send_command(cdev,&cmd_o,&cfg_o) 函数将这些值写入到 CAN FIFO 中。

```c
static netdev_tx_t stvd_can_tx_handler(struct sdvt_can_classdev *cdev)
{
    struct canfd_frame *cf = (struct canfd_frame *)cdev->tx_skb->data;
    int m_i_i   = 0;
    cmd_o.data_len_code_4b  = cf->len;
    cmd_o.dlc_4b = cmd_o.data_len_code_4b;

    pr_info("send data:");
    for (m_i_i = 0; m_i_i < cmd_o.data_len_code_4b; m_i_i += 1) {
        cmd_o.data_2d_8b[m_i_i] = ((u_int8_t *)cf->data)[m_i_i];
        pr_info(" get xmit data %#x", cmd_o.data_2d_8b[m_i_i]);
    }
    pr_info("\n");

    send_command(cdev,&cmd_o,&cfg_o);

    return NETDEV_TX_OK;
}
```

# 用户态 CAN 读写程序示例

CAN 用户态的数据接收使用的是 socket 的方式。

CAN 用户态发送和接收数据，使用 socket() 函数创建 socket 描述符，但是要注意 socket 的 domain,type,protocol 的设定，然后使用 bind()函数将一个地址族中的特定地址赋给 socket。建立连接后，使用 write/read 进行数据读写。

```c
int main(int argc, char **argv)
{
    struct can_frame frame = {
        .can_id = 1,
    };
    struct ifreq ifr;
    struct sockaddr_can addr;
    char *interface;
    int family = PF_CAN, type = SOCK_RAW, proto = CAN_RAW;
    int loopcount = 1, infinite = 0;
    int s, opt, ret, i,nbytes, err,dlc = 0, rtr = 0, extended = 0;
    int verbose = 0;
    int count = 0;
    int read_enable =0;
    char buf[BUF_SIZ];
    unsigned char send_data[8] = {0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08};

    interface = "can0";

    printf("interface = %s, family = %d, type = %d, proto = %d\n",
        interface, family, type, proto);

    s = socket(family, type, proto);
    if (s < 0) {
        perror("socket");
        return 1;
    }

    addr.can_family = family;
    strcpy(ifr.ifr_name, interface);
    if (ioctl(s, SIOCGIFINDEX, &ifr)) {
        perror("ioctl");
        return 1;
    }
    addr.can_ifindex = ifr.ifr_ifindex;

    if (bind(s, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        return 1;
    }

    for (i = 0; i < sizeof(send_data); i++) {
        frame.data[dlc] = send_data[i];
        dlc++;
    }
    frame.can_dlc = dlc;

    if (extended) {
        frame.can_id &= CAN_EFF_MASK;
        frame.can_id |= CAN_EFF_FLAG;
    } else {
        frame.can_id &= CAN_SFF_MASK;
    }

    if (rtr)
        frame.can_id |= CAN_RTR_FLAG;

    ret = write(s, &frame, sizeof(frame));

    read_enable = 1;
    while (read_enable) {
        if ((nbytes = read(s, &frame, sizeof(struct can_frame))) < 0) {
            perror("read");
            return 1;
        } else {
            if (frame.can_id & CAN_EFF_FLAG)
                n = snprintf(buf, BUF_SIZ, "<0x%08x> ", frame.can_id & CAN_EFF_MASK);
            else
                n = snprintf(buf, BUF_SIZ, "<0x%03x> ", frame.can_id & CAN_SFF_MASK);

            n += snprintf(buf + n, BUF_SIZ - n, "[%d] ", frame.can_dlc);
            for (i = 0; i < frame.can_dlc; i++) {
                n += snprintf(buf + n, BUF_SIZ - n, "%02x ", frame.data[i]);
            }
            if (frame.can_id & CAN_RTR_FLAG)
                n += snprintf(buf + n, BUF_SIZ - n, "remote request");

            fprintf(out, "%s\n", buf);

            do {
                err = fflush(out);
                if (err == -1 && errno == EPIPE) {
                    err = -EPIPE;
                    fclose(out);
                    out = fopen(optout, "a");
                    if (!out)
                        exit (EXIT_FAILURE);
                }
            } while (err == -EPIPE);

            n = 0;
        }
    }

    close(s);
    return 0;
}
```

# 4G/5G模块操作指南

## 检查 USB 设备枚举

首先，您需要确认系统是否已经识别并枚举了连接的 USB 设备。使用 `lsusb` 命令可以列出所有已连接的 USB 设备：

```bash
lsusb
```

如果命令的输出中显示了您的设备信息，这意味着设备已经被系统成功识别。例如，下面的输出展示了一个已经被系统枚举的 Fibocom 无线模块：

```
Bus 004 Device 002: ID 2cb7:0a06 Fibocom Wireless
```

在本例中，我们关注的是 Fibocom 的 FM650 型号模块。

## 验证网络接口是否注册

接下来，需要确认网络接口是否已经在系统中注册。运行 `ifconfig -a` 命令可以列出所有的网络接口，包括那些尚未配置的：

```bash
ifconfig -a
```

检查输出结果，以确保您的网络接口已经列出，这表明接口已经在系统中注册，即使它可能还没有配置 IP 地址。

## 查看 USB 串口是否正常

```bash
# 列出所有连接的 USB 串行设备
ls /dev/ttyUSB*

# 在本文的环境中，执行上述命令应会显示如下设备列表：
# 注意：这些设备信息表明了各个 USB 设备的总线位置和设备 ID

Bus 004 Device 002: ID 2cb7:0a06 Fibocom Wireless Inc. FM650 Module
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 002 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 003 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub

# 如果你的设备没有在列表中显示，需要进行故障排除：
# 确认 USB 设备是否已经正确连接到计算机上。
# 检查设备的模块是否已经正确插入到转接口中，以及转接口是否有任何物理损坏。
```

## 启动拨号服务（仅支持 supportlist 上的型号）

```bash
systemctl start lteModemManager
```

等待一段时间后，若成功启动，可使用 `ifconfig -a` 命令查看网卡获取的上网 IP。

## 验证是否连上网

```bash
# lteModemManager 服务启动后在 60s 左右的时间内会自动配置 DNS 为 8.8.8.8
systemd-resolved --status

# 打印如下
Link 8 (usb0)
    Current Scopes: DNS
DefaultRoute setting: yes
    LLMNR setting: yes
MulticastDNS setting: no
DNSOverTLS setting: no
    DNSSEC setting: no
DNSSEC supported: no
Current DNS Server: 8.8.8.8
    DNS Servers: 8.8.8.8

# 也可以手动进行设置，操作如下
# 修改 DNS 设置
vim /etc/systemd/resolved.conf

# 在文件中找到 [Resolve] 部分，并设置 DNS 为 Google 的公共 DNS
[Resolve]
DNS=8.8.8.8

# 保存并退出，然后重启 systemd-resolved 服务以应用更改
systemctl restart systemd-resolved

# 检查配置是否生效，尝试 ping 百度网站
ping baidu.com
```

> SIM 卡不支持热插拔，需要可联网的 SIM。

# WiFi 和 Bluetooth 操作指南

## WiFi/BT操作流程

### 确认 PCIE 是否枚举上

```bash
# 使用 lspci 命令列出所有 PCI 设备
lspci

# 如果系统正常，你将看到类似以下的输出：
# 其中包含了 PCI 设备的列表和相关信息

00:00.0 PCI bridge: Device 1f1c:186a (rev 01)
01:00.0 Network controller: Realtek Semiconductor Co., Ltd. Device b852
```

### 加载 WiFi 驱动

```bash
insmod /mnt/system/ko/3rd/8852be.ko
```

### 加载蓝牙驱动

```bash
insmod /mnt/system/ko/3rd/hci_uart.ko
```

> 上述两个内核模块已存在，只需加载就行。

### 安装对应的 wpa 和 bluez 工具

```bash
dpkg -i wpa_xxx.deb bluez_xxx.deb
```

上述两个安装包可根据模块官网信息使用 apt install 进行安装。

### 配置 wpa_supplicant

为了使您的系统能够自动连接到无线网络，您需要在 `/etc/wpa_supplicant/` 目录中创建一个名为 `wpa_supplicant.conf` 的配置文件。以下是一个配置示例，它会配置您的系统以自动连接到一个名为"123"，密码为"12345678"的无线网络：

```bash
# wpa_supplicant 全局控制接口设置
ctrl_interface=/var/run/wpa_supplicant

# 网络配置块
network={
    ssid="123"          # 无线网络的名称（SSID）
    psk="12345678"      # 无线网络的预共享密钥（密码）
}
```

### 启动 wpa 服务

```bash
systemctl start wpa_supplicant
```

### 启动 dhclient 服务，自动获取 IP

```bash
# 启动 dhclient 以自动获取 IP 地址
systemctl start dhclient

# 成功获取 IP 地址后，可以使用 ifconfig -a 命令查看网络接口信息
# 以下是在本环境中执行该命令后的输出示例：

wlp1s0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
    inet 192.168.137.175  netmask 255.255.255.0  broadcast 192.168.137.255
    inet6 fe80::7a8a:86ff:fe51:59d6  prefixlen 64  scopeid 0x20<link>
    ether 78:8a:86:51:59:d6  txqueuelen 1000  (Ethernet)
    RX packets 450  bytes 85032 (85.0 KB)
    RX errors 0  dropped 0  overruns 0  frame 0
    TX packets 193  bytes 15220 (15.2 KB)
    TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

### 测试网络连通

```bash
# 手动配置 DNS
vim /etc/systemd/resolved.conf

# 在文件中找到 [Resolve] 部分，并设置 DNS 为 Google 的公共 DNS
[Resolve]
DNS=8.8.8.8

# 保存并退出，然后重启 systemd-resolved 服务以应用更改
systemctl restart systemd-resolved

# 检查配置是否生效，尝试 ping 百度网站
ping baidu.com
```

### 配置蓝牙（需确认蓝牙连接的 UART 引脚，并进行相应的 pinmux 切换）

```bash
# 配置 UART 引脚
cvi_pinmux -w UART4_RX/UART4_RX
cvi_pinmux -w UART4_TX/UART4_TX
cvi_pinmux -w UART4_CTS/UART4_CTS
cvi_pinmux -w UART4_RTS/UART4_RTS

# 启动蓝牙 HCI
rtk_hciattach -n -s 115200 ttyS4 rtk_h5 &

# 如果蓝牙初始化失败，需要断电重启
# 重置蓝牙
cvi_pinmux -w PAD_MIPI1_TX0P/GPIO185
echo 345 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio345/direction
echo 1 > /sys/class/gpio/gpio345/value
echo 0 > /sys/class/gpio/gpio345/value
```

### 查看蓝牙节点是否生成

```bash
# 检查蓝牙节点
hciconfig -a

# 预期输出示例
hci0:   Type: Primary  Bus: UART
    BD Address: 78:8A:86:51:59:D7  ACL MTU: 1021:5  SCO MTU: 255:11
    UP RUNNING PSCAN
    RX bytes:912735 acl:38 sco:0 events:4708 errors:0
    TX bytes:44343 acl:37 sco:0 commands:218 errors:0
    Features: 0xff 0xff 0xff 0xfa 0xdb 0xbf 0x7b 0x87
    Packet type: DM1 DM3 DM5 DH1 DH3 DH5 HV1 HV2 HV3
    Link policy: RSWITCH HOLD SNIFF PARK
    Link mode: SLAVE ACCEPT
```

### 启动蓝牙

```bash
# 启动蓝牙服务
systemctl start bluetooth
```

### 使用 BlueZ 工具进行通信

```bash
# 进入蓝牙命令行界面
bluetoothctl

# 命令行显示
Agent registered
[CHG] Controller 78:8A:86:51:59:D7 Pairable: yes
[bluetooth]#

# 打开蓝牙电源
power on

# 打印如下
[bluetooth]# power on
Changing power on succeeded
[bluetooth]#

# 扫描周围的蓝牙设备
scan on

# 打印如下
[bluetooth]# scan on
Discovery started
[CHG] Controller 78:8A:86:51:59:D7 Discovering: yes
[NEW] Device 7B:4F:A0:69:9F:CB 7B-4F-A0-69-9F-CB
[NEW] Device 73:D7:AE:07:F8:79 73-D7-AE-07-F8-79
[NEW] Device 68:F3:5C:FD:59:25 68-F3-5C-FD-59-25
[NEW] Device 1C:3A:C6:A6:AC:B2 1C-3A-C6-A6-AC-B2
[NEW] Device 5A:27:AF:9D:F0:BE 5A-27-AF-9D-F0-BE

# 蓝牙配对
pair <XX:XX:XX:XX:XX:XX>

# 打印如下
pair F4:1A:9C:BA:30:E3
Attempting to pair with F4:1A:9C:BA:30:E3
[CHG] Device F4:1A:9C:BA:30:E3 Connected: yes
Request confirmation
[agent] Confirm passkey 442308 (yes/no): yes
[CHG] Device F4:1A:9C:BA:30:E3 Modalias: bluetooth:v038Fp1200d1436
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001105-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 0000110a-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 0000110c-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001112-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001115-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001116-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 0000111f-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 0000112f-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001132-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001200-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001800-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001801-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 00001855-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 0000fdaa-0000-1000-8000-00805f9b34fb
[CHG] Device F4:1A:9C:BA:30:E3 UUIDs: 98b97136-36a2-11ea-8467-484d7e99a198
```

# WiFi AP操作流程

## 设置 5G 无线接入点 (AP)

为了设置 5G AP，您需要使用 US 的国家代码:

```bash
insmod /mnt/system/ko/3rd/8852be.ko rtw_country_code=US
sudo apt install iw
iw reg set US
ifconfig wlp1s0 192.168.1.10
```

## 安装 DHCP 服务器

对于大多数 Linux 发行版，您可以使用包管理器安装 `isc-dhcp-server`。例如，在 Debian/Ubuntu 上，您可以使用以下命令:

```bash
sudo apt update
sudo apt install isc-dhcp-server
```

## 配置 DHCP 服务器

您需要编辑 DHCP 服务器的配置文件，通常是 `/etc/dhcp/dhcpd.conf`，以定义 IP 地址范围和其他网络设置。以下是一个配置示例:

```bash
subnet 192.168.1.0 netmask 255.255.255.0 {
    range 192.168.1.11 192.168.1.254;
    option domain-name-servers 8.8.8.8, 8.8.4.4;
    option routers 192.168.1.1;
}
```

## 指定监听的接口

在 `/etc/default/isc-dhcp-server` 文件中，指定 DHCP 服务器应该监听的网络接口:

```bash
INTERFACESv4="wlp1s0"
INTERFACESv6=""
```

启动服务:

```bash
systemctl start isc-dhcp-server
```

## 设置无线接入点

您可以使用 `hostapd` 来设置无线接入点。首先，安装 `hostapd`:

```bash
sudo apt install hostapd
```

安装后最好禁用自启动，在配置 hostapd 之前，最好禁用其自动启动，以避免在配置文件未完全设置好时自动启动:

```bash
sudo systemctl unmask hostapd
sudo systemctl disable hostapd
```

然后，创建配置文件 `/etc/hostapd/hostapd.conf`，包含如下内容:

```bash
interface=wlp1s0
driver=nl80211

# Control interface directory
ctrl_interface=/var/run/hostapd
# Control interface group
ctrl_interface_group=0

ssid=SE9
wpa=2
wpa_passphrase=12345678
wpa_key_mgmt=WPA-PS

country_code=US

#ieee80211d=1
#ieee80211n=1
ieee80211ac=1

hw_mode=a
channel=40

# 和上述一样开启channel bonding
ht_capab=[MAX-AMSDU-3839][HT40-][SHORT-GI-20][SHORT-GI-40][DSSS_CCK-40]
require_ht=1

# 来自官网的解释：
# vht_capab: VHT capabilities (list of flags)
# vht_max_mpdu_len: [MAX-MPDU-7991] [MAX-MPDU-11454]
# Indicates maximum MPDU length
#
# Short GI for 80 MHz: [SHORT-GI-80]
# Indicates short GI support for reception of packets transmitted with TXVECTOR
# params format equal to VHT and CBW = 80Mhz
#
# SU Beamformee Capable: [SU-BEAMFORMEE]
# Indicates support for operation as a single user beamformee
vht_capab=[MAX-MPDU-3895][SHORT-GI-80][SU-BEAMFORMEE]

# Require stations to support VHT PHY (reject association if they do not)
require_vht=1

# 0 = 20 or 40 MHz operating Channel width
# 1 = 80 MHz channel width
# 2 = 160 MHz channel width
# 3 = 80+80 MHz channel width
vht_oper_chwidth=0

#详情可以查看官网
beacon_int=100
dtim_period=2
max_num_sta=255
preamble=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wmm_enabled=1
eapol_key_index_workaround=0
eap_server=0
rsn_pairwise=CCMP
```

# KEYSCAN操作指南

## KEYSCAN的操作准备如下：

- 使用SDK发布的kernel。

## 准备过程

- 插入模块: insmod /mnt/system/ko/keyscan.ko;
- 将相关引脚pinmux到keyscan,参考pinmux章节,导出的func为:KEY_COL0~KEY_COL3,KEY_ROW0~KEY_ROW3;
- keyscan 支持4x4按键矩阵,共16个按键,找到KEY_COL0~KEY_COL3,KEY_ROW0~KEY_ROW3引出,接到keyscan键盘模块;

## 操作示例

以evtest为例 来自http://archive.ubuntu.com/ubuntu/pool/universe/e/evtest/,包含源码，编译后可运行在开发板

```bash
tar -xjvf  evtest_1.33.orig.tar.bz2
cd evtest-1.33/
./configure
vim Makefile //修改CC=自己的交叉编译器，若用bm1688 SDK,则修改为:CC=aarch64-none-linux-gnu-gcc
make //当前目录下会生成 evtest 可执行文件，拷贝到开发板上运行
./evtest /dev/input/event0
```

- 按下按键, 读取按键事件,判断按键是否按下;
- echo 0x0f0f > /dev/cvi-keyscan0 (屏蔽0~3row, 0~3col的所有按键);
- 按下被屏蔽的按键, 读取按键事件,判断按键是否按下;

# IRRX操作指南

## IRRX的操作准备如下：

- 使用SDK发布的kernel。

## 准备过程

- 插入模块: insmod /mnt/system/ko/irrx.ko;
- 将相关引脚pinmux到irrx;
- irrx 支持红外接收,需要外接红外接收器,红外遥控器(支持NEC协议),输入到pwr_wakeup0引脚,使用的映射表如下：

```c
static struct rc_map_table anysee[] = {
   { 0x0800, KEY_NUMERIC_0 },
   { 0x0801, KEY_NUMERIC_1 },
   { 0x0802, KEY_NUMERIC_2 },
   { 0x0803, KEY_NUMERIC_3 },
   { 0x0804, KEY_NUMERIC_4 },
   { 0x0805, KEY_NUMERIC_5 },
   { 0x0806, KEY_NUMERIC_6 },
   { 0x0807, KEY_NUMERIC_7 },
   { 0x0808, KEY_NUMERIC_8 },
   { 0x0809, KEY_NUMERIC_9 },
   { 0x080a, KEY_POWER2 }, /* [red power button] */
   { 0x080b, KEY_VIDEO }, /* [*] MODE */
   { 0x080c, KEY_CHANNEL }, /* [symbol counterclockwise arrow] */
   { 0x080d, KEY_NEXT }, /* [>>|] */
   { 0x080e, KEY_MENU }, /* MENU */
   { 0x080f, KEY_EPG }, /* [EPG] */
   { 0x0810, KEY_CLEAR }, /* EXIT */
   { 0x0811, KEY_CHANNELUP },
   { 0x0812, KEY_VOLUMEDOWN },
   { 0x0813, KEY_VOLUMEUP },
   { 0x0814, KEY_CHANNELDOWN },
   { 0x0815, KEY_OK },
   { 0x0816, KEY_RADIO }, /* [symbol TV/radio] */
   { 0x0817, KEY_INFO }, /* [i] */
   { 0x0818, KEY_PREVIOUS }, /* [|<<] */
   { 0x0819, KEY_FAVORITES }, /* FAV. */
   { 0x081a, KEY_SUBTITLE }, /* Subtitle */
   { 0x081b, KEY_CAMERA }, /* [symbol camera] */
   { 0x081c, KEY_YELLOW },
   { 0x081d, KEY_RED },
   { 0x081e, KEY_LANGUAGE }, /* [symbol Second Audio Program] */
   { 0x081f, KEY_GREEN },
   { 0x0820, KEY_SLEEP }, /* Sleep */
   { 0x0821, KEY_SCREEN }, /* 16:9 */ /*4:3 */
   { 0x0822, KEY_ZOOM }, /* SIZE */
   { 0x0824, KEY_FN }, /* [F1] */
   { 0x0825, KEY_FN }, /* [F2] */
   { 0x0842, KEY_MUTE }, /* symbol mute */
   { 0x0844, KEY_BLUE },
   { 0x0847, KEY_TEXT }, /* TEXT */
   { 0x0848, KEY_STOP },
   { 0x0849, KEY_RECORD },
   { 0x0850, KEY_PLAY },
   { 0x0851, KEY_PAUSE },
};
```

## 操作示例

以evtest为例 来自http://archive.ubuntu.com/ubuntu/pool/universe/e/evtest/,包含源码，编译后可运行在开发板

```bash
//同keyscan操作示例，编译evtest
evtest /dev/input/event0 //可能不是event0,需要根据实际情况调整
```

- 按下红外遥控器，查看串口打印

# WIEGAND操作指南

## WIEGAND的操作准备如下：

- 使用SDK发布的kernel。

## 操作过程

- 插入模块: insmod /mnt/system/ko/soph_wiegand.ko;
- 将相关引脚pinmux到wiegand;

## 操作示例

1.打开wiegand设备节点

```bash
char *dev_name = "/dev/cvi-wiegand0";
fd = open(dev_name, O_RDWR);
if (fd < 0) {
    printf("open %s failed\n", dev_name);
    return -1;
}
```

2.配置wiegand参数

```bash
struct wgn_tx_cfg {
   uint32_t tx_lowtime;
   uint32_t tx_hightime;
   uint32_t tx_bitcount;
   uint32_t tx_msb1st;
   uint32_t tx_opendrain;
};
struct wgn_rx_cfg {
   uint32_t rx_debounce;
   uint32_t rx_idle_timeout;
   uint32_t rx_bitcount;
   uint32_t rx_msb1st;
};

cmd = IOCTL_WGN_SET_TX_CFG;
tx_cfg.tx_lowtime = 0x00186A;
tx_cfg.tx_hightime = 0x00C350;
tx_cfg.tx_bitcount = 26;
tx_cfg.tx_msb1st = 1;
tx_cfg.tx_opendrain = 0;

ret = ioctl(fd, cmd, &tx_cfg);
if (ret < 0) {
   printf("ioctl %d failed\n", cmd);
   return -1;
}

cmd = IOCTL_WGN_SET_RX_CFG;
rx_cfg.rx_debounce = 100;
rx_cfg.rx_idle_timeout = 0x2625A0;
rx_cfg.rx_bitcount = 26;
rx_cfg.rx_msb1st = 1;

ret = ioctl(fd, cmd, &rx_cfg);
if (ret < 0) {
   printf("ioctl %d failed\n", cmd);
   return -1;
}
```

3.发送wiegand数据

```bash
uint64_t tx_data = 0x166866b;
cmd = IOCTL_WGN_TX;
ret = ioctl(fd, cmd, &tx_data);
if (ret < 0) {
   printf("ioctl %d failed\n", cmd);
   return -1;
}
```

4.接收wiegand数据

```bash
uint64_t rx_data;
int timeoutflag = 0;

cmd = IOCTL_WGN_RX;
ret = ioctl(fd, cmd, &timeoutflag);
if (ret < 0) {
      printf("ioctl %d failed\n", cmd);
      return -1;
}

cmd = IOCTL_WGN_GET_VAL;
ret = ioctl(fd, cmd, &rx_data);
if (ret < 0) {
      printf("ioctl %d failed\n", cmd);
      return -1;
}
```

# 系统接口使用

## RTC_SRAM存储OEM说明

OEM参数位置是eMMC的硬件boot1分区，进入kernel后挂载在/dev/mmcblk0boot1。MCU在fsbl阶段开始运行，需要OEM参数用于设置不同的board，A53和MCU不能同时访问eMMC，因此在FSBL加载MCU之前，先从eMMC的boot1分区读OEM参数到RTC_SRAM，然后MCU再去取参数。

RTC_SRAM起始地址：0x5200000，长度：0x8000(32K)，预留RTC_SRAM最后256 byte用于存储OEM参数，OEM组成结构如下：

| offset | name           | description                     |
|--------|----------------|---------------------------------|
| 0x00   | SN0            | chip sn                         |
| 0x20   | SN1            | reserve for product or customer |
| 0x40   | MAC0           |                                 |
| 0x50   | MAC1           |                                 |
| 0x60   | PRODUCT_TYPE   |                                 |
| 0x70   | MODULE_TYPE    |                                 |
| 0x80   | INTERFACE_FLAG |                                 |
| 0x81   | AGING_FLAG     |                                 |
| 0x90   | VENDER         |                                 |
| 0xa0   | DTS_TYPE       |                                 |
| 0xc0   | HW_VERSION     |                                 |
| 0xd0   | PRODUCT        | 产品系列，例如: SE9             |
| 0xe0   | CHIP           | BM1688/CV186AH                  |
| 0xf0   | DDR_SIZE       | ddr total size(HEX)             |

## 修改和读取SN和MAC地址

BM1688的SN和MAC地址存放在MCU的EEPROM中，您可以通过如下方式进行修改和读取操作。

首先需要解锁mmcblk0boot1设备节点：

```bash
sudo -i
echo 0 > /sys/block/mmcblk0boot1/force_ro
```

写入SN：

```bash
echo "HQATEVBAIAIAI0001" > sn.txt
dd if=sn.txt of=/dev/mmcblk0boot1 count=17 bs=1
echo "HQATEVBAIAIAI0002" > sn.txt
dd if=sn.txt of=/dev/mmcblk0boot1 count=17 bs=1 seek=32
```

读取SN：

```bash
dd if=/dev/mmcblk0boot1 of=dump.bin count=17 bs=1
hexdump -C dump.bin | head
```

写入MAC（双网卡各有一个MAC）：

```bash
echo "E0A509261417" > mac0.txt
xxd -p -u -r mac0.txt > mac0.bin
dd if=mac0.bin of=/dev/mmcblk0boot1 count=6 bs=1 seek=64
echo "E0A509261418" > mac1.txt
xxd -p -u -r mac1.txt > mac1.bin
dd if=mac1.bin of=/dev/mmcblk0boot1 count=6 bs=1 seek=80
```

读取MAC:

```bash
dd if=/dev/mmcblk0boot1 of=mac_dump.bin count=6 bs=1 skip=64
hexdump mac_dump.bin
```

最后重新对mmcblk0boot1设备节点加锁，以避免意外改写：

```bash
echo 1 > /sys/block/mmcblk0boot1/force_ro
```

新的MAC地址将在重启系统后生效。

## 读取BM1688芯片温度

命令：

```bash
cat /sys/class/thermal/thermal_zone0/temp
```

返回（单位为毫摄氏度）：

```bash
38745
```

即38.745摄氏度。

Linux的thermal框架会使用这个温度做管理(需要加载soph_clock_cooling驱动)：

- 当温度升到110度时，TPU频率会降到450MHz，CPU降频到1GHz；
- 当温度升高到120度时，TPU降频到100MHz，CPU降频到1GHz;
- 当温度回落到100度时，TPU和CPU频率恢复额定值;
- 当温度升高到125度时，系统关机。

另支持pwm控制风扇进行主动降温，默认策略为：

- 温度在40度以下时，风扇不转；
- 温度升高到40度时，风扇以100/255最大转速运行；
- 温度升高到60度时，风扇以170/255最大转速运行；
- 温度升高到80度时，风扇以最大转速运行。

注：可以通过设备树修改以上策略，在soph_base.dtsi文件中:

```
sophgo_cooling:sophgo-cooling {
    clocks = <&clk CV186X_AP_CPU_CLK>, <&clk CV186X_TPU_CLK_TPU>;
    clock-names = "clk_cpu", "clk_tpu_axi";
    dev-freqs = <1650000000 900000000>,
        <1000000000 450000000>,
        <1000000000 100000000>;
    compatible = "cvitek,cv186x-cooling";
    #cooling-cells = <2>;
};

fan0: pwm-fan {
    compatible = "pwm-fan";
    #cooling-cells = <2>;
    pwms = <&pwm0 0 1000000 0>; // default pwm0, 1ms period, normal polarity
    cooling-levels = <1 100 170 255>; // max 255
};

thermal-zones {
    soc_thermal_0: soc_thermal_0 {
        polling-delay-passive = <1000>; /* milliseconds */
        polling-delay = <1000>; /* milliseconds */
        thermal-sensors = <&thermal 0>;

        trips {
            soc_thermal_trip_0: soc_thermal_trip_0 {
                temperature = <110000>; /* millicelsius */
                hysteresis = <10000>; /* millicelsius */
                type = "passive";
            };

            soc_thermal_trip_1: soc_thermal_trip_1 {
                temperature = <120000>; /* millicelsius */
                hysteresis = <20000>; /* millicelsius */
                type = "passive";
            };

            soc_thermal_crtical_0: soc_thermal_crtical_0 {
                temperature = <125000>; /* millicelsius */
                hysteresis = <0>; /* millicelsius */
                type = "critical";
            };

            soc_thermal_active_0: soc_thermal_active_0 {
                temperature = <40000>; /* millicelsius */
                hysteresis = <0>; /* millicelsius */
                type = "active";
            };

            soc_thermal_active_1: soc_thermal_active_1 {
                temperature = <60000>; /* millicelsius */
                hysteresis = <0>; /* millicelsius */
                type = "active";
            };

            soc_thermal_active_2: soc_thermal_active_2 {
                temperature = <80000>; /* millicelsius */
                hysteresis = <0>; /* millicelsius */
                type = "active";
            };
        };

        cooling-maps {
            map0 {
                trip = <&soc_thermal_trip_0>;
                cooling-device = <&sophgo_cooling 1 1>;
            };

            map1 {
                trip = <&soc_thermal_trip_1>;
                cooling-device = <&sophgo_cooling 2 2>;
            };

            map2 {
                trip = <&soc_thermal_active_0>;
                cooling-device = <&fan0 1 1>;
            };

            map3 {
                trip = <&soc_thermal_active_1>;
                cooling-device = <&fan0 2 2>;
            };

            map4 {
                trip = <&soc_thermal_active_2>;
                cooling-device = <&fan0 3 3>;
            };
        };
    };
```

修改以上设备树节点即可自定义温控策略（TPU分频只可整数倍），参考linux Documention相关设备树说明。

## 查询内存用量

BM1688板载了16GB DDR，可以分为三类：

1. kernel管理的部分，即可以用malloc、kmalloc等常规API分配出来使用。
2. ION管理的部分，预留给TPU、VPU、VPP使用，需要使用ION的ionctl接口，或使用sophonSDK中bmlib库提供的接口分配出来使用。
3. 预留给固件的部分，用户无法使用。

您可以使用如下方式检查各部分内存的用量：

1. 查看系统内存

```bash
linaro@bm1684:~$ free -h
              total        used        free      shared  buff/cache   available
Mem:          6.6Gi       230Mi       6.2Gi       1.0Mi       230Mi       6.3Gi
Swap:            0B          0B          0B
```

2. 查看ION内存

```bash
sudo -i
root@bm1684:~# cat /sys/kernel/debug/ion/cvi_npu_heap_dump/summary  | head -2
Summary:
[0] npu heap size:4141875200 bytes, used:0 bytes        usage rate:0%, memory usage peak
0 bytes

root@bm1684:~# cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary  | head -2
Summary:
[2] vpu heap size:2147483648 bytes, used:0 bytes        usage rate:0%, memory usage peak
0 bytes
```

如上，通常会有2个ION heap（即两块预留的内存区域），如名字所示，分别供TPU、VPP使用。以上示例中只打印了每个heap使用信息的开头，如果完整地cat summary文件，可以看到其中分配的每块buffer的地址和大小信息。

## 查询EMMC寿命信息

BM1688支持通过以下两种方式查询EMMC的寿命信息：

1. 使用mmc-utils工具查询（需要安装mmc-utils包）：

```bash
# 首先确认EMMC是否支持v5协议
mmc extcsd read /dev/mmcblk0 | head -1

# 查询寿命信息
mmc extcsd read /dev/mmcblk0 | grep -E 'LIFE|EOL'
```

输出示例：

```bash
eMMC Life Time Estimation A [EXT_CSD_DEVICE_LIFE_TIME_EST_TYP_A]: 0x01
eMMC Life Time Estimation B [EXT_CSD_DEVICE_LIFE_TIME_EST_TYP_B]: 0x01
eMMC Pre EOL information [EXT_CSD_PRE_EOL_INFO]: 0x01
```

输出说明：

- Life Time Estimation A：表示SLC模式下的寿命估计值
- Life Time Estimation B：表示MLC/TLC模式下的寿命估计值
  * 寿命值范围从0x01到0x0a，分别对应10%到100%的磨损程度
- Pre EOL information：表示EMMC保留块的消耗程度
  * 0x01：正常状态
  * 0x02：已消耗80%的保留块
  * 0x03：已消耗90%的保留块

2. 通过sys文件系统查询（推荐方式）：

```bash
# 查询寿命信息
cat /sys/class/mmc_host/mmc0/mmc0:0001/life_time

# 查询保留块信息
cat /sys/class/mmc_host/mmc0/mmc0:0001/pre_eol_info
```

输出示例：

```bash
# life_time输出
0x01 0x01

# pre_eol_info输出
0x01
```

- life_time：两个值分别对应SLC和MLC/TLC模式的寿命估计值
- pre_eol_info：单个值表示保留块的消耗程度

注意：不同厂商的EMMC芯片可能对寿命信息的定义略有不同，建议参考具体EMMC芯片的数据手册获取更详细的信息。寿命估计值仅供参考，实际使用寿命可能因使用环境、工作负载等因素而有所不同。

# 系统定制

## 修改kernel

修改 kernel, 重新编译 Linux kernel image, 每张 EVB 都有对应的 dts 档案来定义其 device tree, 以 bm1688_wevb_emmc 为例, 其 DTS 档案定义在:

./build/boards/sophon/bm1688_wevb_emmc/dts_arm64/bm1688_wevb_emmc.dts

```
/dts-v1/;
#include "soph_base_arm64.dtsi"
//#include "soph_asic_bga.dtsi"
#include "soph_asic_emmc.dtsi"
#include "soph_default_memmap.dtsi"
...
```

其相对应的 linux 组态，定义在：

./build/boards/sophon/bm1688_wevb_emmc/linux/bm1688_wevb_emmc_defconfig

```
CONFIG_SYSVIPC=y
CONFIG_POSIX_MQUEUE=y
CONFIG_NO_HZ_IDLE=y
CONFIG_HIGH_RES_TIMERS=y
CONFIG_TASKSTATS=y
CONFIG_IKCONFIG=y
CONFIG_IKCONFIG_PROC=y
CONFIG_SCHED_AUTOGROUP=y
CONFIG_BLK_DEV_INITRD=y
CONFIG_BLK_DEV_RAM=y
...
```

以图形化接口修改 Kernel Config

```console
$ menuconfig_kernel
```

退出后会把设定储存在：
./linux/build/bm1688_wevb_emmc/.config

```console
$ build_kernel
```

完成后会生成 boot.itb

## 定制化软件包

您可以通过以下操作获取您所需要的特定的软件包:

1. 从官网获取sdcard.tgz基础软件包。

2. 您需要参考文件结构一节准备相关文件，将 sdcard.tgz 软件包复制到 $OUTPUT_DIR 目录下，其中 $OUTPUT_DIR 所代表的目录与defconfig命令指定的配置有关系，例如

```bash
source build/cvisetup.sh

defconfig edge_wevb_emmc
```

终端会打印如下内容：

```bash
Run defconfig function
Loaded configuration '/project/sophon/1688_v2.0_source/build/boards/sophon/edge_wevb_emmc/edge_wevb_emmc_defconfig'
Configuration saved to '.config'
Loaded configuration '.config'
Minimal configuration saved to '/project/sophon/1688_v2.0_source/build/.defconfig'
/project/sophon/1688_v2.0_source/build /project/sophon/1688_v2.0_source
/project/sophon/1688_v2.0_source

====== Environment Variables =======

PROJECT: edge_wevb_emmc, DDR_CFG=ddr_auto
CHIP_ARCH: SOPHON, DEBUG=0
SDK VERSION: 64bit, RPC=0
ATF options: ATF_KEY_SEL=default, BL32=1
Linux source folder:linux_5.10, Uboot source folder: u-boot-2021.10
CROSS_COMPILE_PREFIX: aarch64-none-linux-gnu-
ENABLE_BOOTLOGO: 0
Flash layout xml: /project/sophon/1688_v2.0_source/build/boards/sophon/edge_wevb_emmc/partition/partition_emmc.xml
Sensor tuning bin: ov_os08b10
Output path: /project/sophon/1688_v2.0_source/install/soc_edge_wevb_emmc
```

其中最后一行，Output path对应的结果即为$OUTPUT_DIR对应的目录,如果$OUTPUT_DIR对应的目录不存在，则可以执行如下命令创建：

```bash
mkdir -p $OUTPUT_DIR
```

创建目录后，将 sdcard.tgz 基础软件包复制到该目录下，使用命令：

```bash
cp -rf {your_path}/sdcard.tgz $OUTPUT_DIR/    // {your_path}是您获取的sdcard.tgz基础软件包的本地路径
```

3. 执行revert_package命令:

```bash
revert_package
```

该命令执行完成之后，会在$OUTPUT_DIR/package_edge目录下生成boot.tgz，data.tgz，recovery.tgz，rootfs.tgz，rootfs_rw.tgz 这五个软件包，并且在 $OUTPUT_DIR/package_update/目录下生成 sdcard 和 update 两个文件夹。

这里的 sdcard 文件夹是 sdcard.tgz 软件包解压出来的文件，update 文件夹保存了执行revert_package 命令之后初始打包的五个软件包。

boot.tgz 软件包主要用于 kernel。

data.tgz 软件包主要用于 data 分区。

recovery.tgz 软件包主要用于用户恢复出厂设置。

rootfs.tgz 软件包可以用来制作您所需要的文件系统。

rootfs_rw.tgz 软件包文件系统 overlay 区，包括了所有系统安装的 app，lib，脚本，服务，/etc 下的设置，更新后都会清除。

4. 如果您要修改分区信息，您需要修改build/scripts/下的partition32G.xml文件。

5. 将修改后的*.tgz包替换掉$OUTPUT_DIR/package_edge下的同名*.tgz包，然后根据需要重新编译刷机包。

```bash
build
```

# 在 |Product| 上编译内核模块

您可以选择直接在 |Product| 板卡上直接编译kernel module，可以省去上述搭建交叉编译环境的麻烦。步骤如下：

1. uname -r得到kernel版本号，与/home/linaro/bsp-debs和/lib/modules里面的文件名比较，确保一致

2. 因为kernel在交叉编译环境下做make bindeb-pkg的缺陷，需要再额外做如下处理：

   a. 用date命令检查当前系统时间，如果跟实际时间相差太多，请设置为当前时间，如

   ```bash
   sudo date -s "01:01:01 2021-03-01"
   ```

   b. 检查是否存在/home/linaro/bsp-debs/linux-headers-install.sh，如果有的话，执行它即可

   c. 如果没有的话，需要手工操作：

   ```bash
   sudo dpkg -i /home/linaro/bsp-debs/linux-headers-*.deb
   sudo mkdir -p /usr/src/linux-headers-$(uname -r)/tools/include/tools
   sudo cp /home/linaro/bsp-debs/*.h /usr/src/linux-headers-$(uname-r)/tools/include/tools
   cd /usr/src/linux-headers-$(uname -r)
   sudo apt update
   sudo apt-get install -y build-essential bc bison flex libssl-dev
   sudo make scripts
   ```

# 修改分区表

|Product| 使用GPT分区表。分区表的配置文件在

```bash
build/scripts/partition32G.xml
```

其中依次描述了每个分区的大小信息。不建议您修改分区的顺序和个数，以及readonly和format属性，以免与其它一些预装脚本中的写法发生冲突。您可以修改每个分区的大小。最后一个分区的大小不需要凑满eMMC实际容量，可以把它设成一个比较小的值，只要足够存放您准备预装的文件（即data.tgz解开后的内容）就可以。刷机后第一次开机时，会有一个脚本将这个分区自动扩大到填满eMMC的全部剩余可用空间。

如果是边侧的buildroot,分区表配置文件为

```bash
build/boards/sophon/edge_buildroot/partition/partition_emmc.xml
```

# 开机自启动服务

如果您有开机自动启动某些服务的需求，可以参考本节内容。
BM1688系列芯片使用systemd实现核心服务bmrt_setup的开机自启动，该服务包含以下三个关键文件：

```bash
/etc/systemd/system/bmrt_setup.service （服务描述文件）
/etc/systemd/system/multi-user.target.wants/bmrt_setup.service （软链接）
/usr/sbin/bmrt_setup.sh （执行脚本）
```

其中bmrt_setup.service的内容如下，您可以参考它的写法，在/etc/systemd/system目录下构建自己的服务。

```bash
[Unit]
Description=setup bitmain runtime env.
After=docker.service # 表明该服务在docker服务后启动

[Service]
User=root
ExecStart=/usr/sbin/bmrt_setup.sh # 指定服务启动执行的命令
Type=oneshot

[Install]
WantedBy=multi-user.target
```

在bmrt_setup.sh脚本中，我们加载了VPU、JPU以及TPU等关键驱动，所以请您把自定义的服务放在这个服务后面执行，或者在您的业务逻辑中等待驱动加载完成（可以使用systemd-analyze plot > boot.svg 生成一张启动详细信息矢量图，然后用图像浏览器或者网页浏览器打开查看所有服务的启动顺序和耗时）。

# 修改DTS_TYPE

如果进入了linux系统shell界面，则可直接使用dts_tool工具进行更改。

输入dts_tool后会读出当前使用的dts_type为bm1688_se9v1_8G，选中目标平台要使用的dts_type的序号，比如bm1688_se9v1_8G，序号为23，输入23再回车即可

如果是在uboot界面，默认的dts配置不能进入系统，需要选择正确的dts_type，可以在系统固件包sophon-img/boot/muilt.its查询正确的dts_type。

设置命令如下：

```bash
setenv DTS_TYPE config-bm1688_se9v1_8G   ###设置dts_type
bootd  #启动系统
```

# 修改默认串口终端

BM1688芯片内置8个UART接口，即从UART0、UART1，UART2递增到UART7，在系统上电后，Boot引导程序和Linux内核使用的默认串口终端分别由两个变量控制。

引导阶段，引导程序会查找OEM信息中的Console Flag变量，选择该变量指定的UART作为默认终端。OEM信息存储在eMMC芯片的boot1分区中，Console Flag字节相对起始地址0的偏移为130，其取值从0x00到0x07，分别对应UART0到UART7。下图中的命令可以显示所有OEM信息，图中的Console Flag为0x02，表示选择UART2为引导程序默认终端。

Linux内核所使用的默认串口终端则由设备树中的chosen/stdout-path属性指定，如下图所示，图中的serial2代表使用UART2作为串口终端。设备启动后，使用的设备树文件名是由上图OEM信息中的DTS_TYPE指定的。

官方的BSP通常设置UART2为默认串口终端，但用户也可以根据具体硬件设计设置其他的UART接口为默认串口终端（理论上所有UART均可选，实际上仅有UART0到UART6设置了Pinmux并在设备树中使能了，因此UART7是不可用的）。假设需要修改默认串口终端为UART0，请首先确保您的硬件设计已经引出了UART0；然后，打开用于烧录OEM信息的burn_oem脚本（在操作系统中通常位于/sbin/burn_oem），找到您的设备型号对应的函数，将Console Flag行的参数从0x02修改为0x00，如下图（假设设备型号为SM9_8_ENC_B3），并保存。设备型号通常可以从包装盒铭牌上查到，如果您的OEM信息已经烧录，请保持跟原先相同的型号。

此外，还需要将OEM信息中对应的设备树文件里的Chosen/stdout-path修改为serial0，对应UART0，然后执行build_kernel重新编译内核，生成新的boot.itb文件。这个流程与修改kernel设备树的流程是一致的。更为推荐的做法是通过设备树修改工具直接在原有boot.itb文件基础上修改型号对应的设备树文件，得到新的boot.itb，参考链接 [内存布局修改工具](https://github.com/sophgo/sophon-tools/blob/main/source/pmemory_edit/readme.md) 。

最后，需要执行上面已经修改过的burn_oem脚本，选择您的设备型号对应的数字，以烧录修改后的Console Flag到eMMC，然后将新编译的boot.itb文件替换到设备的/boot目录（最好先备份设备上旧的/boot/boot.itb，以防出现意外）。以上都完成之后即可执行重启，重启后应当在UART0看到所有的串口输出。

# Dec_api

## parse_args

这个接口实现解析输入参数，并存储在input_params里面。

**接口形式：**

```c
static int parse_args(
   int argc, 
   char *argv[], 
   EncInputParam *input_params
   );
```

**参数说明：**

* **int argc** - 输入参数个数

* **char * argv[]** - 输入的具体参数，-f pixel format: 0.YUV420P(default) 1.YUV422P；-w 宽度；-h 高度；-i 输入文件名；-o 输出文件名；-n 循环次数；-g 旋转，默认为0 1:90 2:180 3:270；-y:y分量的跨度；-c:色度分量的跨度

* **EncInputParam * input_params** - 该参数是一个EncInputParam结构体指针变量，可以用来记录输入的参数

**返回值说明：**

* 0: 成功
* -1: 失败

**代码示例：**

```c
static int parse_args(int argc, char *argv[], DecInputParam *input_params)
{
   int opt;

   memset(input_params, 0, sizeof(DecInputParam));

   while ((opt = getopt(argc, argv, "i:o:n:d:c:g:s:r:")) != -1) {
       switch (opt) {
           case 'i':
               input_params->input_filename = optarg;
               break;
           case 'o':
               input_params->output_filename = optarg;
               break;
           case 'n':
               input_params->loop_num = atoi(optarg);
               break;
           case 'd':
           #ifdef BM_PCIE_MODE
               input_params->device_index = atoi(optarg);
           #endif
               break;
           case 'c':
               input_params->dump_crop = atoi(optarg);
               break;
           case 'g':
               input_params->rotate = atoi(optarg);
               break;
           case 's':
               input_params->scale = atoi(optarg);
               break;
           case 'r':
               sscanf(optarg, "%d,%d,%d,%d", &input_params->roi.x, &input_params->roi.y, &input_params->roi.w, &input_params->roi.h);
               break;
           default:
               usage(argv[0]);
               return -1;
       }
   }
```

## bm_jpu_dec_load

这个接口实现打开并获取设备节点的标识，可以管理内存分配。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_dec_load(int device_index);
```

**参数说明：**

* **int device_index** - 该参数是设备的序号

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
bm_jpu_dec_load(0);
```

## bm_jpu_jpeg_dec_open

这个接口实现打开设备节点并选取编码设备，在多线程下可以实现获取不同的编码设备的序号，最高是可以32路。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_open(BmJpuJPEGDecoder **jpeg_decoder,
                                BmJpuDecOpenParams *open_params,
                                unsigned int num_extra_framebuffers)
```

**参数说明：**

* **jpeg_decoder** - 该参数是一个BmJpuJPEGDecoder的二级指针变量，记录了解码器需要的所有参数包括输入数据的存储位置等信息

* **open_params** - 该参数是一个BmJpuDecOpenParams结构体指针，记录了打开一个解码器并设置解码器的一些参数，比如感兴趣区域的宽高等

* **num_extra_framebuffers** - 该参数是记录需要额外的缓冲区的数量

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他：失败

**函数调用实例:**

```c
ret = bm_jpu_jpeg_dec_open(&jpeg_decoder, &dec_open_params, 0);
```

## start_decode

这个接口开始解码过程通过接口传入解码器需要的所有参数，然后传入输入数据，以及输入数据所占空间的大小。

**接口形式：**

```c
BmJpuDecReturnCodes start_decode(
   BmJpuJPEGDecoder *jpeg_decoder, 
   uint8_t *bs_buffer, 
   size_t bs_size, 
   FILE *fp_out, 
   int inst_idx, 
   const uint8_t *ref_md5, 
   int dump_crop);
```

**参数说明：**

* **jpeg_decoder** - 该参数是结构体BmJpuJPEGDecoder的结构体指针变量, 里面存放了解码需要的所有信息，在后面的接口中会将相应的参数进行记录在该结构体里面

* **bs_buffer** - 该参数是malloc出来的一块用于存放输入图片数据的一块空间，里面是图片数据

* **bs_size** - 该参数是读取的原始图像数据所占的空间字节数

* **fp_out** - 该参数是输出文件指针变量，将编码后的数据写入到目标文件中

* **inst_idx** - 该参数是表示解码器的索引号

* **ref_md5** - 该参数用来对比编解码输出的结果的MD5值

**返回值说明：**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
ret = start_decode(jpeg_decoder, bs_buffer, bs_size, fp_output, 0, NULL, input_params.dump_crop);
```

## bm_jpu_jpeg_dec_decode

这个接口实现单纯的解码工作，将解码器需要的参数以及输入图片的数据信息，以及数据信息所占用的空间字节大小。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_decode(
   BmJpuJPEGDecoder *jpeg_decoder, 
   uint8_t const *jpeg_data, 
   size_t const jpeg_data_size);
```

**参数说明：**

* **jpeg_decoder** - 该参数是结构体BmJpuJPEGDecoder的结构体指针变量, 里面存放了解码需要的所有信息，在后面的接口中会将相应的参数进行记录在该结构体里面

* **jpeg_data** - 该参数是一个指向用于存放输入图片数据的空间的指针，用于取出图片数据

* **jpeg_data_size** - 该参数是一个表示存储数据占用空间大小参数，和jpeg_data指针变量搭配使用

**返回值说明：**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
ret = bm_jpu_jpeg_dec_decode(jpeg_decoder, bs_buffer, bs_size);
if (ret != 0) {
   fprintf(stderr, "decode failed!\n");
   return BM_JPU_DEC_RETURN_CODE_ERROR;
}
```

# bm_jpu_jpeg_dec_get_info

这个接口实现了从解码器输出获取有关可以读取到输出数据的信息，包括数据的像素格式，输出帧数据的宽度高度等。

## 接口形式

```c
void bm_jpu_jpeg_dec_get_info(
    BmJpuJPEGDecoder *jpeg_decoder, 
    BmJpuJPEGDecInfo *info);
```

## 参数说明

* **jpeg_decoder**

该参数是结构体BmJpuJPEGDecoder的结构体指针变量, 里面存放了解码需要的所有信息，在后面的接口中会将相应的参数进行记录在该结构体里面。

* **info**

该参数是一个BmJpuJPEGDecInfo的结构体指针变量，用来从解码器里面拿到关于解码后数据帧的信息，包括数据的起始地址，以及帧长度。

## 返回值说明

* 无返回值

## 函数调用实例

```c
ret = bm_jpu_jpeg_dec_decode(jpeg_decoder, bs_buffer, bs_size);
if (ret != 0) {
    fprintf(stderr, "decode failed!\n");
    return BM_JPU_DEC_RETURN_CODE_ERROR;
}
```

# bm_mem_get_device_addr

这个接口获取申请到的物理地址，目的是为了后续mmap虚拟地址使用。

## 接口形式

```c
unsigned long long bm_mem_get_device_addr(struct bm_mem_desc mem);
```

## 参数说明

* **struct bm_mem_desc mem**

输入参数。由typedef struct bm_mem_desc bm_device_mem_t的参数输入，并返回一个物理地址。

## 函数调用实例

```c
unsigned long long phys_addr = bm_mem_get_device_addr(*framebuffer.dma_buffer);
```

# bm_mem_mmap_device_mem

这个接口实现了将申请到的设备的物理地址映射出一块相同大小的虚拟地址，后续虚拟地址对应的空间将存放输入图片的数据，也就是物理内存中有了输入图片的数据。

## 接口形式

```c
bm_status_t bm_mem_mmap_device_mem(
    bm_handle_t handle, 
    bm_device_mem_t *dmem,
    unsigned long long *vmem);
```

## 参数说明

* **bm_handle_t handle**

输入参数是设备单元句柄，用来管理内存空间

* **bm_device_mem_t * dmem**

输入参数是带有申请到的物理空间大小以及物理空间对应的首地址的结构体指针参数，

* **unsigned long long * vmem**

输入参数是一个长长整形的执行，用来存储指向和物理空间相同大小的虚拟地址。也是后续用于读取数据的起始地址。

## 返回值说明

* 0: 成功
* 其他:失败

## 函数调用实例

```c
bm_ret = bm_mem_mmap_device_mem(bm_handle, framebuffer.dma_buffer, &vaddr);
if (bm_ret != BM_SUCCESS) {
    fprintf(stderr, "bm_mem_mmap_device_mem failed, device_addr: %#lx, size: %u\n", framebuffer.dma_buffer->u.device.device_addr, framebuffer.dma_buffer->size);
    goto finish;
}
```

# bm_mem_unmap_device_mem

这个接口是在读取完输入图片的数据之后，物理空间已经存在需要的数据之后，归还这块虚拟空间的作用。

## 接口形式

```c
bm_status_t bm_mem_unmap_device_mem(
    bm_handle_t handle, 
    void *vmem, 
    int size);
```

## 参数说明

* **bm_handle_t handle**

输入参数是设备单元句柄，用来管理内存空间

* **void * vmem**

输入参数是存放了虚拟空间地址的地址，用于指向内存首地址的地址，解引用就可以获取首地址。

* **int size**

输入参数是需要释放掉的空间内存大小。

## 函数调用实例

```c
virt_addr = (uint8_t *)vaddr;
bm_mem_unmap_device_mem(bm_handle, virt_addr, total_size);
```

# bm_jpu_jpeg_dec_frame_finished

这个接口用于将传递将解码器释放到解码之前的状态。

## 接口形式

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_frame_finished(
    BmJpuJPEGDecoder *jpeg_decoder, 
    BmJpuFramebuffer *framebuffer);
```

## 参数说明

* **jpeg_decoder**

该参数是结构体BmJpuJPEGDecoder的结构体指针变量, 里面存放了解码需要的所有信息，在后面的接口中会将相应的参数进行记录在该结构体里面。

* **framebuffer**

该参数是一个BmJpuFramebuffer结构体指针变量，是解码器输出的帧数据对应的缓冲区信息。

## 返回值说明

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

## 函数调用实例

```c
bm_jpu_jpeg_dec_frame_finished(jpeg_decoder, dec_info.framebuffer);
```

# del_fb_list

这个接口就是传递帧缓冲区列表所有处理过的帧数据都需要进行释放。

## 接口形式

```c
FramebufferList* del_fb_list(
    FramebufferList *list, 
    BmJpuFramebuffer *fb, 
    FramebufferList *list_curr);
```

## 参数说明

* **list**

参数表示帧缓冲区列表中的前一帧的数据信息。

* **fb**

参数表示从解码器取出来的当前帧的数据信息。

* **list_curr**

参数表示帧缓冲区列表中的当前帧的数据信息。

## 返回值说明

* 返回是一个FramebufferList结构体数据类型。

## 函数调用实例

```c
list_curr = del_fb_list(jpeg_decoder->decoder->fb_list_head, framebuffer, jpeg_decoder->decoder->fb_list_curr);
```

# release_fb_node

这个接口实现了最终解码器的释放操作。

## 接口形式

```c
void release_fb_node(FramebufferList *node)
```

## 参数说明

* **node**

参数表示帧缓冲区列表中的当前帧的数据信息。后续会调用驱动的释放接口来实现最终的释放。

## 函数调用实例

```c
release_fb_node(curr);
```

# Dec_struct

## DecInputParam

DecInputParam 是在解码测试选项下的包括输入参数的结构体，用于存储输入的参数。

### DecInputParam 结构体定义

```c
typedef struct {
    char *input_filename;
    char *output_filename;
    char *refer_filename;
    int loop_num;
    int inst_idx;
    unsigned int width;
    unsigned int height;
} DecInputParam;
```

### 成员变量说明

* **input_filename**

输入参数：一个指向字符数组（字符串）的指针，用于存储输入文件名。

* **output_filename**

输入参数：一个指向字符数组（字符串）的指针，用于存储输出文件名。

* **refer_filename**

输入参数：一个指向字符数组（字符串）的指针，用于存储参考文件名。

* **loop_num**

输入参数：循环次数。

* **inst_idx**

输入参数：索引值。

* **width**

输入参数：图像的宽度。

* **height**

输入参数：图像的高度。

## BmJpuDecOpenParams

BmJpuDecOpenParams 该结构体的参数用来打开一个解码器，换句话说是设置一个解码器属性（要接收图片的大小，需要的缓存区大小等属性）。

### BmJpuDecOpenParams 结构体定义

```c
typedef struct {
    unsigned int frame_width;
    unsigned int frame_height;
    int chroma_interleave;
    unsigned int scale_ratio;
    int bs_buffer_size;
    uint8_t *buffer;
    int device_index;
    int rotationEnable;
    int mirrorEnable;
    int mirrorDirection;
    int rotationAngle;
    int roiEnable;
    int roiWidth;
    int roiHeight;
    int roiOffsetX;
    int roiOffsetY;
    int framebuffer_recycle;
    size_t framebuffer_size;
} BmJpuDecOpenParams;
```

### 成员变量说明

* **frame_width**

输入参数：输入图像帧的宽度。

* **frame_height**

输入参数：输入图像帧的高度。

* **chroma_interleave**

输入参数：色度分量的存储方式的标识选项，可以是交错存储也可以是分开存储

* **scale_ratio**

输入参数：用于指定视频解码时的缩放比例。它决定了图像在解码过程中是否进行大小调整（即缩放）。如果值为 0，则表示不进行任何缩放；如果值在1到3之间（包括1和3），则表示将图像按照2的n次幂进行缩放，其中n为scale_ratio的值

* **bs_buffer_size**

输入参数：表示bitstream的缓冲区的大小，这里记录了输入图片需要字节的大小。

* **buffer**

输入参数：在WIN32的情况下，该参数被使用，用于存储输入图片的具体内容。

* **device_index**

输入参数：设备索引（解码器通道）。

* **rotationEnable**

输入参数：是否可以旋转的标识参数，0表示不需要旋转，1表示旋转，

* **mirrorEnable**

输入参数：是否需要镜像操作的标识参数，0表示不用，1表示使用。

* **mirrorDirection**

输入参数：镜像的方向是如何的，0是水平，1是垂直。

* **rotationAngle**

输入参数：旋转的角度，可以是90、180、270度。

* **roiEnable**

输入参数：是否设置感兴趣区域。

* **roiWidth**

输入参数：如果设置感兴趣区域，感兴趣区域的宽度。

* **roiHeight**

输入参数：如果设置感兴趣区域，感兴趣区域的高度。

* **roiOffsetX**

输入参数：如果设置感兴趣区域，感兴趣区域相对图像的左上角的水平偏移量。

* **roiOffsetY**

输入参数：如果设置感兴趣区域，感兴趣区域相对于图像的左上角的垂直偏移量。

* **framebuffer_recycle**

输入参数：是否需要回收缓冲区中的帧数据信息。

* **framebuffer_size**

输入参数：大小表示帧数据需要的缓冲区大小。

# BmJpuJPEGDecoder

**BmJpuJPEGDecoder** 结构体定义了解码过程需要的所有参数，换句话说它记录了输入参数，以及解码器设置参数信息。

```c
typedef struct _BMJpuJPEGDecoder
{
    BmJpuDecoder *decoder;

    bm_device_mem_t *bitstream_buffer;
    size_t bitstream_buffer_size;
    unsigned int bitstream_buffer_alignment;

    BmJpuDecInitialInfo initial_info;

    BmJpuFramebuffer *framebuffers;
    bm_device_mem_t *fb_dmabuffers;
    unsigned int num_framebuffers;
    unsigned int num_extra_framebuffers; 
    BmJpuFramebufferSizes calculated_sizes;

    BmJpuRawFrame raw_frame;
    int device_index;

    BmJpuFramebuffer *cur_framebuffer;
    bm_device_mem_t *cur_dma_buffer;
    void *opaque;

    int rotationEnable;
    int mirrorEnable;
    int mirrorDirection;
    int rotationAngle;
    
    int framebuffer_recycle;
    size_t framebuffer_size;

}BmJpuJPEGDecoder;
```

## 成员变量说明

### decoder

输入参数：decoder是一个BmJpuDecoder的指针变量，其中BmJpuDecoder是一个结构体，存储了解码需要的设备序号，输入的数据格式等

**BmJpuDecoder** 结构体定义如下:

```c
struct _BmJpuDecoder
{
    unsigned int device_index;
    DecHandle handle;
    bm_device_mem_t *bs_dma_buffer;
    uint8_t *bs_virt_addr;
    uint64_t bs_phys_addr;
    int chroma_interleave;
    int scale_ratio;
    unsigned int old_jpeg_width;
    unsigned int old_jpeg_height;
    BmJpuColorFormat old_jpeg_color_format;
    unsigned int num_framebuffers, num_used_framebuffers;
    FrameBuffer *internal_framebuffers;
    BmJpuFramebuffer *framebuffers;
    BmJpuDecFrameEntry *frame_entries;
    DecInitialInfo initial_info;
    int initial_info_available;
    DecOutputInfo dec_output_info;
    int available_decoded_frame_idx;
    bm_jpu_dec_new_initial_info_callback initial_info_callback;
    void *callback_user_data;
    int framebuffer_recycle;
    int channel_id;
    FramebufferList *fb_list_head;
    FramebufferList *fb_list_curr;
};
```

成员包括表示设备序号的device_index，标识的句柄handle，存放物理地址和虚拟地址以及内存空间大小的bs_dma_buffer，存放虚拟地址的bs_virt_addr，bs_phys_addr：表示bs_dma_buffer在物理内存中的地址等

### chroma_interleave

输入参数：表示色度插值的标志位或设置值，用来指定色度信息的排列顺序。

### scale_ratio

输入参数：scale_ratio图像缩放比例的参数。该参数可以控制图像在水平和垂直方向上的缩放级别。

### old_jpeg_width

输入参数：表示原先图片的宽度，同old_jpeg_height类似，与处理缩放操作相关，用于保存初始图片的宽高。

### old_jpeg_color_format

输入参数：old_jpeg_color_format一个BmJpuColorFormat枚举类型的参数，具体的如下。

**BmJpuColorFormat** 枚举了图片的颜色格式类型

```c
typedef enum{
    BM_JPU_COLOR_FORMAT_YUV420                  = 0,
    BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL       = 1,
    BM_JPU_COLOR_FORMAT_YUV422_VERTICAL         = 2,
    BM_JPU_COLOR_FORMAT_YUV444                  = 3,
    BM_JPU_COLOR_FORMAT_YUV400                  = 4,
    BM_JPU_COLOR_FORMAT_RGB                     = 5
} BmJpuColorFormat;
```

**各个格式说明:**

- **BM_JPU_COLOR_FORMAT_YUV420**

表示对应的是yuv420p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV12。

- **BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL**

表示对应的是yuv422p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV16。

- **BM_JPU_COLOR_FORMAT_YUV422_VERTICAL**

表示对应的是yuv422p的数据格式, 包括三个通道, 需要说明这种格式很少使用, 只在少数JPEG文件中出现过。

- **BM_JPU_COLOR_FORMAT_YUV444**

表示对应的是yuv444p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV24。

- **BM_JPU_COLOR_FORMAT_YUV400**

表示对应的灰度图, 只有Y分量。

- **BM_JPU_COLOR_FORMAT_RGB**

表示对应用于存储RGB（红绿蓝）颜色数据的格式。

### num_framebuffers和num_used_framebuffers

输入参数：num_framebuffers表示数据帧需要的缓冲区域数量，num_used_framebuffers表示已使用的帧缓冲的数量。

### internal_framebuffers

输入参数：internal_framebuffers是一个FrameBuffer的结构体指针，用于记录的帧缓冲区的信息，注意的是它用于和解码器直接交互的缓冲区。

具体的 **FrameBuffer** 结构体如下：

```c
typedef struct {
    uint64_t bufY;
    uint64_t bufCb;
    uint64_t bufCr;
    int strideY;
    int strideC;
    int myIndex;
} FrameBuffer;
```

FrameBuffer结构体成员主要包括了代表 Y 分量（亮度）的缓冲区地址（bufY）;代表 Cb 分量（蓝色差）的缓冲区地址;代表 Cr 分量（红色差）的缓冲区地址。
以上用于存储对应的区域的数据。另外，strideY和strideC分别表示 Y 分量的行跨度（stride）和 Cb 和 Cr 分量的行跨度（stride），它们可以通过偏移量来确定数据值所在位置，读取数据。
最后myIndex：是一个整数型的索引变量，可能用于标识该帧缓冲在某个上下文中的位置或者其他特定的目的。

### framebuffers

输入参数：framebuffers是一个BmJpuFramebuffer的结构体类型指针，用于存放一个指向该结构体对应空间的首地址，该结构体的缓冲区需要用户自己创建。

具体的 **BmJpuFramebuffer** 结构体如下：

```c
typedef struct {
    unsigned int y_stride;
    unsigned int cbcr_stride;
    bm_device_mem_t *dma_buffer;
    size_t y_offset;
    size_t cb_offset;
    size_t cr_offset;

    void *context;
    int already_marked;
    void *internal;
} BmJpuFramebuffer;
```

BmJpuFramebuffer结构体成员主要包括缓冲区数据在亮度层面的步距（y_stride）和在色度分量上的步距（cbcr_stride）也就是一行所占用的字节数,以及用于记录数据物理空间和虚拟空间地址结构体（bm_device_mem_t）；size_t y_offset, size_t cb_offset, 和 size_t cr_offset 则是表示各个色度分量（Cb和Cr）在帧缓冲中的偏移量（以字节为单位），偏移量指定了从帧缓冲的起始位置开始，到达相应色度分量数据的位置需要跳过的字节数。
context指针变量用在当使用 JPU 进行编解码时，可以通过这个指针来识别正在使用的帧缓冲，从而进行相关的操作和追踪。例如，在多线程环境下，这个指针可用于跟踪每个线程使用的帧缓冲，以确保并发访问的正确性。
already_marked成员使用内部获取，外部不能提供和修改其值，用于标识帧缓冲是不是已显示。internal是一个空类型指针变量，不被改变。

### frame_entries

输入参数：frame_entries是一个BmJpuDecFrameEntry类型的结构体指针变量，指向该结构体对应空间的首地址。

具体的 **BmJpuDecFrameEntry** 成员如下：

```c
typedef struct
{
    void *context;
    uint64_t pts;
    uint64_t dts;
    FrameMode mode;
} BmJpuDecFrameEntry;
```

BmJpuDecFrameEntry结构体成员主要包括context无类型指针在使用过程中会被赋予不同含义，pts表示显示时间戳的64位无符号整数，显示时间戳是媒体帧在播放器中显示的时间点，以确定其在时间轴上的位置
dts表示解码时间戳的64位无符号整数，用于显示媒体帧被解码的时间点，用于确保帧的正确顺序和同步。mode成员是一个枚举类型变量，

具体的 **FrameMode** 枚举成员如下:

```c
typedef enum
{
    FrameMode_Free,
    FrameMode_ContainsDisplayableFrame
} FrameMode;
```

枚举类型FrameMode有两种模式：FrameMode_Free表示帧模式为自由帧，只是作为其他操作或处理的输入或输出。FrameMode_ContainsDisplayableFrame表示帧模式为包含可显示的图像帧，可用于指示该帧包含可以在屏幕上显示的有效图像数据。

### initial_info

输入参数：initial_info是一个DecInitialInfo结构体类型变量，用于记录了解码器的一些初始参数和信息。

具体的 **DecInitialInfo** 结构体成员如下:

```c
typedef struct {
    int picWidth;
    int picHeight;
    int minFrameBufferCount;
    int sourceFormat;
    int ecsPtr;
    int roiFrameWidth;
    int roiFrameHeight;
    int roiFrameOffsetX;
    int roiFrameOffsetY;
    int roiMCUSize;
    int colorComponents;
} DecInitialInfo;
```

DecInitialInfo结构体成员主要包括图像宽度（picWidth）、高度（picHeight），表示最小帧缓冲数量的minFrameBufferCount，记录存储解码后的图像帧的缓冲区数量
sourceFormat源数据格式对应前面的数据格式的枚举类型；ecsPtr指向外部控制序列 (External Control Sequence) 的指针。外部控制序列是一种特殊的数据流，包含对解码过程进行控制和调整所需的参数和命令。
roiFrameWidth和roiFrameHeight：分别表示感兴趣区域帧的宽度和高度。roiFrameOffsetX表示感兴趣区域帧左上角相对于完整图像左上角的X偏移量，
roiFrameOffsetY表示感兴趣区域帧左上角相对于完整图像左上角的Y偏移量。roiMCUSize表示感兴趣区域的最小编码单元大小，换句话说就是在压缩编码过程中图片被分割的最小区域大下。
colorComponents表示图像中使用的颜色通道数量，比如RGB是三个通道。

### initial_info_available

输入参数：initial_info_available用来标识初始化参数是否在用。

### dec_output_info

输入参数：dec_output_info是一个DecOutputInfo类型的结构体，记录了解码器的输出信息。

具体的 **DecOutputInfo** 成员如下：

```c
typedef struct {
    int indexFrameDisplay;
    int numOfErrMBs;
    int decodingSuccess;
    int decPicHeight;
    int decPicWidth;
    int consumedByte;
    int bytePosFrameStart;
    int ecsPtr;
} DecOutputInfo;
```

DecOutputInfo结构体的成员包括indexFrameDisplay表示显示帧的索引，表示当前输出的是第几个要显示的帧；numOfErrMBs：表示在解码过程中发现的错误宏块的数量
decodingSuccess：解码成功标志，1表示解码成功，0表示解码失败。decPicHeight和decPicWidth分别表示解码后图片的宽高
consumedByte：表示在解码过程中实际使用的输入数据的字节数量。bytePosFrameStart：表示帧在输入数据流中的起始位置。
ecsPtr：外部控制序列指针，用于指示解码器处理的外部控制序列。

### available_decoded_frame_idx

输入参数：available_decoded_frame_idx表示可用的已解码帧的索引，并可以在后续处理中使用。

### initial_info_callback

输入参数：initial_info_callback是一个函数指针变量，指向的函数是一个回调函数，当解码器需要提供新的初始信息时，会调用这个函数来获取该信息

具体的 **bm_jpu_dec_new_initial_info_callback** 如下

```c
int (*bm_jpu_dec_new_initial_info_callback)(BmJpuDecoder *decoder,
                                            BmJpuDecInitialInfo *new_initial_info,
                                            unsigned int output_code,
                                            void *user_data);
```

在该函数的实现中，可以根据需要对解码器进行操作，并将新的初始信息存储在 new_initial_info 中。最后，通过返回一个整数值作为标识来告知解码器是否成功获取了新的初始信息。

### callback_user_data

输入参数：callback_user_data：表示一个指向 `void` 类型的指针，用于存储回调函数中传递的用户自定义数据。

### framebuffer_recycle

输入参数：framebuffer_recycle表示一个整数变量，用于表示帧缓冲区是否可循环利用的标识

### channel_id

输入参数：channel_id表示一个整数变量，用于表示通道的编号或标识符

### fb_list_head

输入参数：fb_list_head和fb_list_curr均为一个指向 **FramebufferList** 结构体的指针，用于指向帧缓冲区列表的头节点。帧缓冲区列表是一种数据结构，用于存储多个帧缓冲区的信息。

### fb_list_curr

输入参数：fb_list_curr表示一个指向 **FramebufferList** 结构体的指针，用于指向当前正在处理的帧缓冲区节点。在进行遍历或操作帧缓冲区列表时，可以使用这个指针来获取当前节点的信息或进行相应的操作。

具体的 **FramebufferList** 成员如下：

```c
typedef struct FramebufferList {
    struct FramebufferList *next;
    BmJpuFramebuffer *fb;
    int chn_id;
    int chn_fd;
} FramebufferList;
```

FramebufferList结构体包括了一个新的 **FramebufferList** 结构体指针next，用于存放下一帧的信息。一个指向 **BmJpuFramebuffer** 结构体的指针变量fp，表示帧缓冲区的信息和数据。
chn_id表示通道的编号或标识符，用于唯一标识不同的通道; chn_fd表示通道的文件描述符或句柄，用于与通道进行输入输出操作。

### bitstream_buffer

输入参数：bitstream_buffer是一个指向bm_device_mem_t类型的指针，表示bitstream缓冲区的地址。

### bitstream_buffer_size

输入参数：bitstream_buffer_size表示比特流缓冲区的大小，即可以容纳的比特流数据的最大字节数。

### bitstream_buffer_alignment

输入参数：bitstream_buffer_alignment表示bitstream需要的缓冲区对齐要求。

### initial_info

参数：initial_info是一个BmJpuDecInitialInfo结构体变量，存放了解码器的初始化参数。

具体的 **BmJpuDecInitialInfo** 如下：

```c
typedef struct{
    unsigned int frame_width, frame_height;
    unsigned int min_num_required_framebuffers;
    BmJpuColorFormat color_format;
    unsigned int framebuffer_alignment;
    int roiFrameWidth;
    int roiFrameHeight;
} BmJpuDecInitialInfo;
```

BmJpuDecInitialInfo结构体的成员包括帧数据的宽（frame_width），高（frame_height）
min_num_required_framebuffers表示所需要的最小帧缓冲数量，也就是说操作中至少选哟多少个帧缓冲区。
color_format参数是一个枚举类型，包括了可以处理的图片的数据格式。framebuffer_alignment参数表示帧缓冲区的对齐方式，目的是提高性能或者满足硬件的需要。
最后，roiFrameHeight和roiFrameWidth分别表示感兴趣区域的帧宽度和高度。

### framebuffers

参数：framebuffers是一个BmJpuFramebuffer的结构体类型指针，用于存放一个指向该结构体对应空间的首地址，该结构体的缓冲区需要用户自己创建

### fb_dmabuffers

参数：fb_dmabuffers是一个bm_device_mem_t结构体类型的指针变量，可以存放指向给结构对应空间的首地址，而里面的物理地址可以是指向framebuffers的首地址。

### num_framebuffers

参数：num_framebuffers参数表示所需要的帧缓冲数量，帧缓冲区域用于临时存储图像和视频数据。

### num_extra_framebuffers

参数：num_extra_framebuffers表示额外需要的帧缓冲数量，提供额外的空间。

### calculated_sizes

参数：calculated_sizes参数是一个BmJpuFramebufferSizes结构体变量，表示计算得出的帧缓冲的大小。

具体的 **BmJpuFramebufferSizes** 结构体如下：

```c
typedef struct{
    unsigned int aligned_frame_width, aligned_frame_height;
    unsigned int y_stride, cbcr_stride;
    unsigned int y_size, cbcr_size;
    unsigned int total_size;
    int chroma_interleave;
} BmJpuFramebufferSizes;
```

BmJpuFramebufferSizes结构体的成员主要是由对齐后的宽高aligned_frame_width和aligned_frame_height；亮度分量和色度分量每一行对用的字节数的y_stride和cbcr_stride；
分别表示亮度分量和色度分量总共占有的字节大小的y_size和cbcr_size；表示缓冲区的总字节数的total_size；最后是表示色度交错方式的chroma_interleave。

# Enc_api

## parse_args

这个接口实现解析输入参数，并存储在input_params里面。

**接口形式：**

```c
static int parse_args(
   int argc, 
   char *argv[], 
   EncInputParam *input_params
);
```

**参数说明：**

* **int argc**
  输入参数个数。

* **char * argv[]**
  输入的具体参数，-f pixel format: 0.YUV420P(default) 1.YUV422P；-w 宽度；-h 高度；-i 输入文件名；-o 输出文件名；-n 循环次数；-g 旋转，默认为0 1:90 2:180 3:270；-y:y分量的跨度；-c:色度分量的跨度;

* **EncInputParam * input_params**
  该参数是一个EncInputParam结构体指针变量，可以用来记录输入的参数。

**返回值说明：**

* 0: 成功
* -1: 失败

**代码示例：**

```c
static int parse_args(int argc, char *argv[], EncInputParam *input_params)
{
   int opt;

   memset(input_params, 0, sizeof(EncInputParam));

   while ((opt = getopt(argc, argv, "i:o:n:w:h:v:f:y:c:g:")) != -1)
   {
       switch (opt) {
           case 'i':
               input_params->input_filename = optarg;
               break;
           case 'o':
               input_params->output_filename = optarg;
               break;
           case 'n':
               input_params->loop_num = atoi(optarg);
               break;
           case 'w':
               input_params->enc_params.width = atoi(optarg);
               break;
           case 'h':
               input_params->enc_params.height = atoi(optarg);
               break;
           case 'v':
               input_params->enc_params.aligned_height = atoi(optarg);
               break;
           case 'f':
               input_params->enc_params.pix_fmt = atoi(optarg);
               break;
           case 'y':
               input_params->enc_params.y_stride = atoi(optarg);
               break;
           case 'c':
               input_params->enc_params.c_stride = atoi(optarg);
               break;
           case 'g':
               input_params->enc_params.rotate = atoi(optarg);
               break;
           default:
               usage(argv[0]);
               return -1;
       }
   }
}
```

## bm_jpu_enc_load

这个接口实现打开并获取设备节点的标识，可以管理内存分配。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_enc_load(int device_index);
```

**参数说明：**

* **int device_index**
  该参数是设备的序号。

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
bm_jpu_enc_load(0);
```

## bm_jpu_jpeg_enc_open

这个接口实现打开设备节点并选取编码设备，在多线程下可以实现获取不同的编码设备的序号，最高是可以32路。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_open(
       BmJpuJPEGEncoder **jpeg_encoder,
       int bs_buffer_size,
       int device_index
);
```

**参数说明：**

* **jpeg_encoder**
  该参数是结构体BmJpuJPEGEncoder的二级指针变量，在函数里面申请了内存空间，并记录了打开的编码设备的序号、设置了bs_buffer_size和bitstream_buffer_alignment。

* **int bs_buffer_size**
  该输入参数是提示编码器需要预备多大空间来存放编码的输出数据，输入为0。

* **int device_index**
  该输入参数是设备序号，输入为0。

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
ret = bm_jpu_jpeg_enc_open(&jpeg_encoder, 0, 0);
```

## bm_jpu_jpeg_enc_close

这个接口释放之前打开的编码器设备，将是否使用的标识为恢复成未使用，将malloc出来内存进行释放。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_close(BmJpuJPEGEncoder *jpeg_encoder);
```

**参数说明：**

* **jpeg_encoder**
  该参数是结构体BmJpuJPEGEncoder的指针变量，在函数里面申请了内存空间，并记录了打开的编码设备的序号、设置了bs_buffer_size和bitstream_buffer_alignment。

**返回值说明：**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
BmJpuJPEGEncoder *jpeg_encoder = NULL;

jpeg_encoder = (BmJpuJPEGEncoder *)malloc(sizeof(BmJpuJPEGEncoder));
jpeg_encoder->encoder = (BmJpuEncoder *)malloc(sizeof(BmJpuEncoder));
ret = bm_jpu_jpeg_enc_close(jpeg_encoder);
```

## start_encode

这个接口开始编码实际上是完成编码前的一部分预备工作，包括读取数据，记录编码器设置的一些参数需要，然后进行真正的编码操作，最后完成将编码数据读取并获取MD5值进行对比，确保输出正确。

**接口形式：**

```c
BmJpuEncReturnCodes start_encode(
   BmJpuJPEGEncoder *jpeg_encoder, 
   EncParam *enc_params, 
   FILE *fp_in, 
   FILE *fp_out, 
   int inst_idx, 
   const uint8_t *ref_md5
);
```

**参数说明：**

* **jpeg_encoder**
  该参数是结构体BmJpuJPEGEncoder的二级指针变量, 里面存放了编码需要的所有信息，在后面的接口中会将相应的参数进行记录在该结构体里面。

* **enc_params**
  该参数是结构体EncParam的指针变量，里面存放了输入的参数数据，包括宽高，Y分量和色度分量的跨度等。

* **fp_in**
  该参数是输入文件指针变量，用于读取原始图像数据。

* **fp_out**
  该参数是输出文件指针变量，将编码后的数据写入到目标文件中。

* **inst_idx**
  该参数是表示编码器的索引号。

* **ref_md5**
  该参数用来对比编解码输出的结果的MD5值。

**返回值说明：**

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

**函数调用实例:**

```c
ret = start_encode(
   jpeg_encoder, 
   &input_params.enc_params, 
   fp_in, 
   fp_out, 
   0, 
   NULL);
```

## bm_malloc_device_byte_heap_mask

这个接口申请一定字节大小的空间，并记录对应空间的起始物理地址。

**接口形式：**

```c
bm_status_t bm_malloc_device_byte_heap_mask(
   bm_handle_t handle, 
   bm_device_mem_t *pmem,
   int heap_id_mask, 
   unsigned int size
);
```

**参数说明：**

* **bm_handle_t handle**
  输入参数。bm_handle 句柄。通过bm_dev_request函数来获得。

* **bm_device_mem_t * pmem**
  输入参数。用来存放数据的物理地址的地方，也是数据实际写入的位置。

* **int heap_id_mask**
  输入参数。内存堆掩码（heap mask）。这个参数指示了使用哪些类型的内存堆来进行分配。

* **unsigned int size**
  输入参数。需要申请字节空间的大小。

**返回值说明：**

* BM_SUCCESS: 成功
* 其他:失败

**函数调用实例:**

```c
bm_handle_t handle;
ret = bm_dev_request(&handle, 0);
ret = bm_malloc_device_byte_heap_mask(handle, framebuffer.dma_buffer, HEAP_MASK_1_2, total_size);
```

## bm_mem_get_device_addr

这个接口获取申请到的物理地址，目的是为了后续mmap虚拟地址使用。

**接口形式:**

```c
unsigned long long bm_mem_get_device_addr(struct bm_mem_desc mem);
```

**参数说明：**

* **struct bm_mem_desc mem**
  输入参数。由typedef struct bm_mem_desc bm_device_mem_t的参数输入，并返回一个物理地址。

**函数调用实例:**

```c
unsigned long long phys_addr = bm_mem_get_device_addr(*framebuffer.dma_buffer);
```

## bm_jpu_enc_get_channel_fd

这个接口通过BmJpuJPEGEncoder里面记录的设备序号来获取对应的标识，拿到控制权。

**接口形式：**

```c
int bm_jpu_enc_get_channel_fd(int chn_id);
```

**参数说明：**

* **int chn_id**
  输入参数。通过打开编码设备选取对应的编码通道序号。

**函数调用实例:**

```c
int chn_fd = bm_jpu_enc_get_channel_fd(jpeg_encoder->encoder->device_index);
```

## bmjpeg_ioctl_mmap

这个接口通过设备的通道，根据申请的物理地址来申请对应大小字节的虚拟内存，并返回一个虚拟地址。

**接口形式：**

```c
void* bmjpeg_ioctl_mmap(int chn_fd, unsigned long long phys_addr, size_t len);
```

**参数说明：**

* **int chn_id**
  输入参数。通过打开编码设备选取对应的编码通道序号。

* **unsigned long long phys_addr**
  输入参数。在设备上申请一定字节对应返回的物理地址。

* **size_t len**
  输入参数。空间对应的字节大小。

**返回参数：**
mmap出来的虚拟内存对应的虚拟地址

**函数调用实例:**

```c
virt_addr = bmjpeg_ioctl_mmap(chn_fd, phys_addr, total_size);
```

## bm_mem_mmap_device_mem

这个接口实现了将申请到的设备的物理地址映射出一块相同大小的虚拟地址，后续虚拟地址对应的空间将存放输入图片的数据，也就是物理内存中有了输入图片的数据。

**接口形式：**

```c
bm_status_t bm_mem_mmap_device_mem(
           bm_handle_t handle, 
           bm_device_mem_t *dmem,
           unsigned long long *vmem);
```

**参数说明：**

* **bm_handle_t handle**
  输入参数是设备单元句柄，用来管理内存空间

* **bm_device_mem_t * dmem**
  输入参数是带有申请到的物理空间大小以及物理空间对应的首地址的结构体指针参数，

* **unsigned long long * vmem**
  输入参数是一个长长整形的vmem，用来存储指向和物理空间相同大小的虚拟地址。也是后续用于读取数据的起始地址。

**返回值说明：**

* 0: 成功
* 其他:失败

**函数调用实例:**

```c
bm_ret = bm_mem_mmap_device_mem(bm_handle, framebuffer.dma_buffer, &vaddr);
if (bm_ret != BM_SUCCESS) {
   fprintf(stderr, "bm_mem_mmap_device_mem failed, device_addr: %#lx, size: %u\n", framebuffer.dma_buffer->u.device.device_addr, framebuffer.dma_buffer->size);
   goto finish;
}
```

# bm_mem_unmap_device_mem

这个接口是在读取完输入图片的数据之后，物理空间已经存在需要的数据之后，归还这块虚拟空间的作用。

## 接口形式

```c
bm_status_t bm_mem_unmap_device_mem(
                bm_handle_t handle, 
                        void *vmem, 
                         int size);
```

## 参数说明

* **bm_handle_t handle**

输入参数是设备单元句柄，用来管理内存空间

* **void * vmem**

输入参数是存放了虚拟空间地址的地址，用于指向内存首地址的地址，解引用就可以获取首地址。

* **int size**

输入参数是需要释放掉的空间内存大小。

## 函数调用实例

```c
virt_addr = (uint8_t *)vaddr;
bm_mem_unmap_device_mem(bm_handle, virt_addr, total_size);
```

# bm_jpu_jpeg_enc_encode

这个接口实现了真正的编码过程，会进行编码器的相关参数的设置、输出需要的存储空间、接收到的原始图片的数据信息以及编码后的数据情况，并将编码后的包数据存储到对应的参数里面。

## 接口形式

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_encode(
        BmJpuJPEGEncoder *jpeg_encoder,
        BmJpuFramebuffer const *framebuffer,
        BmJpuJPEGEncParams const *params,
        void **acquired_handle,
        size_t *output_buffer_size
        );
```

## 参数说明

* **BmJpuJPEGEncoder * jpeg_encoder**

输入参数是结构体指针，指向的结构体是存放了编码过程需要的所有信息包括输入信息、编码器属性设置的参数信息以及编码器输出时需要的信息。

* **BmJpuFramebuffer const * framebuffer**

输入参数是结构体指针，指向的结构体是存放了输入的帧数据，并存储了相应的参数需要，如Y分量的跨度，Y分量的偏移量等。

* **BmJpuJPEGEncParams const * params**

输入参数是结构体指针，指向的结构体里定义了编码图像的信息、编码信息以及后续获取编码器输出结果的函数

* **acquired_handle**

输入参数是空类型二级指针，用于指向存放数据的最终位置。

* **output_buffer_size**

输入参数是指向最终编码数据包的总长度。

## 返回值说明

* BM_JPU_ENC_RETURN_CODE_O: 成功
* 其他:失败

## 函数调用实例

```c
BmJpuJPEGEncoder *jpeg_encoder;
BmJpuFramebuffer framebuffer;
BmJpuJPEGEncParams jpu_enc_params;
bm_handle_t handle;
ret = bm_dev_request(&handle, 0);

fp_out = fopen(input_params.output_filename, "wb");
fp_in = fopen(input_params.input_filename, "rb");

framebuffer.dma_buffer = (bm_device_mem_t *)malloc(sizeof(bm_device_mem_t));
ret = bm_malloc_device_byte_heap_mask(handle, framebuffer.dma_buffer, HEAP_MASK_1_2, total_size);

unsigned long long phys_addr = bm_mem_get_device_addr(*framebuffer.dma_buffer);
int chn_fd = bm_jpu_enc_get_channel_fd(jpeg_encoder->encoder->device_index);
virt_addr = bmjpeg_ioctl_mmap(chn_fd, phys_addr, total_size);
fread(virt_addr, sizeof(uint8_t), total_size, fp_in);

jpu_enc_params.frame_width = enc_params->width;
jpu_enc_params.frame_height = enc_params->height;
jpu_enc_params.quality_factor = 85;
jpu_enc_params.color_format = enc_params->pix_fmt;
jpu_enc_params.chroma_interleave = enc_params->cbcr_interleave;//0
jpu_enc_params.acquire_output_buffer = acquire_output_buffer;
jpu_enc_params.finish_output_buffer = finish_output_buffer;
jpu_enc_params.output_buffer_context = NULL;
jpu_enc_params.mirrorDirection = 1;
jpu_enc_params.rotationAngle = 90;

ret = bm_jpu_jpeg_enc_encode(jpeg_encoder, &framebuffer, &jpu_enc_params, &acquired_handle, &output_buffer_size);
fwrite(acquired_handle, 1, output_buffer_size, fp_out);

finish_output_buffer(NULL, acquired_handle);
bmjpeg_ioctl_munmap(virt_addr, total_size);
bm_free_device(handle, *framebuffer.dma_buffer);
free(framebuffer.dma_buffer);
bm_dev_free(handle);

fflush(fp_out);
fclose(fp_out);
fclose(fp_in);
```

# acquire_output_buffer

这个接口用于获取需要申请需要大小的内存去接收。

## 接口形式

```c
void* acquire_output_buffer(void *context, unsigned int size, void **acquired_handle);
```

## 参数说明

* **context**

输入参数通常用于存储某种上下文信息或数据。

* **size**

输入参数大小是编码输出所占的内存大小。

* **void **acquired_handle**

输入参数是用来存储申请的内存空间所对应的起始地址。

## 函数调用实例

```c
BmJpuJPEGEncParams const *params;
void **acquired_handle;
params->acquire_output_buffer(params->output_buffer_context, *output_buffer_size, acquired_handle);
```

# finish_output_buffer

这个接口用于释放存储的编码数据的内存，说明编码结束。

## 接口形式

```c
void finish_output_buffer(void *context, void *acquired_handle);
```

## 参数说明

* **context**

输入参数在调用该接口的时候传入NULL。

* **acquired_handle**

输入参数是指向编码结果输出存储位置的指针。

## 函数调用实例

```c
finish_output_buffer(NULL, acquired_handle);
```

# bmjpeg_ioctl_munmap

这个接口用于释放由物理内存映射的虚拟内存。

## 接口形式

```c
void bmjpeg_ioctl_munmap(uint8_t *virt_addr, size_t len)
```

## 参数说明

* **virt_addr**

输入参数是指向物理内存映射对应的虚拟内存的起始地址。

* **len**

输入参数是对应的内存空间的大小。

## 函数调用实例

```c
bmjpeg_ioctl_munmap(virt_addr, total_size);
```

# Enc_struct

## EncInputParam

EncInputParam是在编码测试的选项下的输入参数结构体。

EncInputParam 结构体定义如下:

```c
typedef struct {
     char *input_filename;
     char *output_filename;
     char *refer_filename;
     int loop_num;
     int inst_idx;

     EncParam enc_params;
 } EncInputParam;
```

EncInputParam 结构体成员包括输入图像的名称（input_filename），输出图片的名称（output_filename），比对的图片的名称（refer_filename），循环次数（loop_num），标识符（inst_idx）和存放编码信息的EncParam结构体变量enc_params。

其中: **EncParam** 结构体定义如下:

```c
typedef struct {
     int width;
     int height;
     int y_stride;
     int c_stride;
     int aligned_height;
     int pix_fmt;
     int cbcr_interleave;
     int rotate;
 } EncParam;
```

EncParam 结构体成员包括输入图片的实际宽高（width, height）, Y分量的跨度（y_stride）, 色彩分量Cb或Cr的跨度（c_stride）, 对齐后的高度（aligned_height）, 输入图像的色彩格式（pix_fmt），是否将色度分量交错存储选项（cbcr_interleave）,图像的旋转角度（rotate）。

其中，cbcr_interleave: Cb和Cr两个色差分量是否交错存储，0表示不交错，1表示交错。图像的旋转角度（rotate）包括0度、90度和180度。

**另外**, 输入图像的色彩格式（pix_fmt）是一个枚举类型，具体的定义如下：

```c
typedef enum{
     BM_JPU_COLOR_FORMAT_YUV420                  = 0,
     BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL       = 1,
     BM_JPU_COLOR_FORMAT_YUV422_VERTICAL         = 2,
     BM_JPU_COLOR_FORMAT_YUV444                  = 3,
     BM_JPU_COLOR_FORMAT_YUV400                  = 4,
     BM_JPU_COLOR_FORMAT_RGB                     = 5
 } BmJpuColorFormat;
```

**各个格式说明:**

* **BM_JPU_COLOR_FORMAT_YUV420**

表示对应的是yuv420p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV12。

* **BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL**

表示对应的是yuv422p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV16。

* **BM_JPU_COLOR_FORMAT_YUV422_VERTICAL**

表示对应的是yuv422p的数据格式, 包括三个通道, 需要说明这种格式很少使用, 只在少数JPEG文件中出现过。

* **BM_JPU_COLOR_FORMAT_YUV444**

表示对应的是yuv444p的数据格式, 包括三个通道, 同时, 在cbcr_interleave=1的时候对应NV24。

* **BM_JPU_COLOR_FORMAT_YUV400**

表示对应的灰度图, 只有Y分量。

* **BM_JPU_COLOR_FORMAT_RGB**

表示对应用于存储RGB（红绿蓝）颜色数据的格式。

## BmJpuJPEGEncoder

BmJpuJPEGEncoder 结构体记录了编码过程的全部信息。

**BmJpuJPEGEncoder** 结构体的定义如下:

```c
typedef struct _BmJpuJPEGEncoder
{
     BmJpuEncoder *encoder;

     bm_device_mem_t *bitstream_buffer;

     size_t bitstream_buffer_size;
     unsigned int bitstream_buffer_alignment;

     BmJpuEncInitialInfo initial_info;

     unsigned int frame_width, frame_height;

     BmJpuFramebufferSizes calculated_sizes;

     unsigned int quality_factor;

     BmJpuColorFormat color_format;
     int packed_format;
     int chroma_interleave;
     int device_index;

     int rotationEnable;
     int mirrorEnable;
     int mirrorDirection;
     int rotationAngle;

 } BmJpuJPEGEncoder;
```

**成员说明:**

* **encoder**

encoder是一个BmJpuEncoder的指针变量，其中BmJpuEncoder是一个结构体，存储了编码的需要的设备序号，输入的数据格式等。

# BmJpuEncoder 结构体定义

```c
typedef struct _BmJpuEncoder
{
    unsigned int device_index;
    EncHandle handle;
    bm_device_mem_t *bs_dma_buffer;
    uint8_t *bs_virt_addr;
    BmJpuColorFormat color_format;
    unsigned int frame_width, frame_height;
    BmJpuFramebuffer *framebuffers;
} BmJpuEncoder;
```

**成员说明：**
- **device_index**：表示设备序号
- **handle**：标识的句柄
- **bs_dma_buffer**：存放有设备物理地址
- **bs_virt_addr**：存放虚拟地址
- **color_format**：对应前面的数据格式并存在于BmJpuColorFormat结构体里
- **frame_width, frame_height**：存放帧宽高数据
- **framebuffers**：用来存放输入图片的帧数据

# BmJpuFramebuffer 结构体

```c
typedef struct{
    unsigned int y_stride;
    unsigned int cbcr_stride;
    bm_device_mem_t *dma_buffer;
    size_t y_offset;
    size_t cb_offset;
    size_t cr_offset;
    void *context;
    int already_marked;
    void *internal;
}BmJpuFramebuffer;
```

**成员说明：**
- **y_stride**：Y分量的跨度
- **cbcr_stride**：色彩分量的跨度
- **dma_buffer**：用来存放输入图片的数据，后续会通过mmap操作，分配出虚拟内存来写入数据
- **y_offset**：数据存储的偏移量，y_offset=0
- **cb_offset**：等于Y分量所占字节的大小
- **cr_offset**：大小是Y分量和Cb分量总的所占字节大小
- **context**：无类型的指针，后续用于记录数据
- **already_marked**：标记位
- **internal**：内部数据

# 其他重要成员

- **bitstream_buffer**：指向位流数据缓冲区的指针，用来记录了编码输出的物理地址
- **bitstream_buffer_size**：记录了编码输出的数据存放的空间所占的大小
- **bitstream_buffer_alignment**：指定了缓冲区起始地址与其对齐边界之间的字节数，提高访问缓冲区的效率
- **initial_info**：结构体，记录了缓冲区的初始化的信息

# BmJpuEncInitialInfo 结构体

```c
typedef struct
{
    unsigned int min_num_required_framebuffers;
    unsigned int framebuffer_alignment;
} BmJpuEncInitialInfo;
```

**成员说明：**
- **min_num_required_framebuffers**：要求的帧缓冲区数量
- **framebuffer_alignment**：对齐方式

# BmJpuFramebufferSizes 结构体

```c
typedef struct
{
    unsigned int aligned_frame_width, aligned_frame_height;
    unsigned int y_stride, cbcr_stride;
    unsigned int y_size, cbcr_size;
    unsigned int total_size;
    int chroma_interleave;
} BmJpuFramebufferSizes;
```

**成员说明：**
- **aligned_frame_width, aligned_frame_height**：对齐像素的帧宽高
- **y_stride, cbcr_stride**：Y分量和色度分量的跨度（注意：Cb和Cr使用的是相同的跨度）
- **y_size, cbcr_size**：Y分量和色度分量存储空间大小（注意：Cb和Cr所用的空间总是相同的）
- **total_size**：帧数据需要的总的空间大小
- **chroma_interleave**：色度分量的存储方式（0和1对应不同的存储方式）

# 其他配置参数

- **quality_factor**：质量因子，通常用于控制图像或视频的压缩比例
- **color_format**：颜色格式，指示图像或视频数据所采用的颜色编码方式
- **packed_format**：指示图像或视频数据中像素值的打包格式
- **chroma_interleave**：表示色度分量的存储方式
- **device_index**：记录了设备序号
- **rotationEnable**：选择图片是否可以旋转，由输入的rotate选项确认
- **mirrorEnable**：选择图片是否可以镜像操作
- **mirrorDirection**：用于指示镜像操作的方向，可能是水平或者垂直
- **rotationAngle**：表示图片需要旋转的角度，可以有90、180、270度

# BmJpuJPEGEncParams 结构体

```c
typedef struct
{
    unsigned int frame_width, frame_height;
    unsigned int quality_factor;
    BmJpuColorFormat color_format;
    BmJpuEncAcquireOutputBuffer acquire_output_buffer;
    BmJpuEncFinishOutputBuffer finish_output_buffer;
    BmJpuWriteOutputData write_output_data;
    void *output_buffer_context;
    int packed_format;
    int chroma_interleave;
    int rotationEnable;
    int mirrorEnable;
    int mirrorDirection;
    int rotationAngle;
}BmJpuJPEGEncParams;
```

**成员说明：**
- **frame_width, frame_height**：输入帧图片的宽高
- **quality_factor**：编码质量的控制选项，1为最好的压缩，100是最好的编码质量
- **color_format**：BmJpuColorFormat结构体变量，包括输入图片的颜色格式
- **acquire_output_buffer**：BmJpuEncAcquireOutputBuffer的函数指针变量，指向acquire_output_buffer函数，用来存储编码器的输出流数据
- **finish_output_buffer**：BmJpuEncFinishOutputBuffer的函数指针变量，指向finish_output_buffer函数，用来释放空间
- **write_output_data**：BmJpuWriteOutputData类型的函数指针变量，指向的函数可以无需执行拷贝操作，避免acquire_output_buffer和finish_output_buffer等的操作，允许将输出数据直接传递给用户
- **output_buffer_context**：同之前的context参数相同，用来记录
- **packed_format**：指示了图像或视频数据中像素值的打包格式
- **chroma_interleave**：指示色度分量是否交错存储
- **rotationEnable**：指示是否可以旋转操作
- **mirrorEnable**：指示是否要镜像操作
- **mirrorDirection**：指示镜像操作的方向是水平的或者是垂直的（0，1）
- **rotationAngle**：指示旋转的角度，90，180，270

# Multi_api

## parse_args

这个接口实现解析输入参数，并存储在解码的配置参数里面。

**接口形式：**
```c
static int parse_args(
    int argc, 
    char **argv,  
    void* pConfig, 
    CodecType codecType
);
```

**参数说明：**
- **int argc**：输入参数个数
- **char * argv**：输入的具体参数
- **pConfig**：将解析输入的参数存储的位置
- **codecType**：用于确定是进行的解码还是编码

**代码示例：**
```c
static int parse_args(int argc, char **argv,  void* pConfig, CodecType codecType)
{
    int opt;
    DecConfigParam* decConfig = NULL;
    EncConfigParam* encConfig = NULL;
    extern char *optarg;
    if(codecType == DEC)
    {
        decConfig = (DecConfigParam*)pConfig;
        while ((opt = getopt(argc, argv, "t:i:o:r:n:d:")) != -1)
        {
            switch (opt)
            {
            case 't':
                break;
            case 'i':
                memcpy(decConfig->bitStreamFileName, optarg, strlen(optarg));
                break;
            case 'o':
                memcpy(decConfig->yuvFileName, optarg, strlen(optarg));
                break;
            case 'r':
                memcpy(decConfig->refFileName, optarg, strlen(optarg));
                break;
            case 'n':
                decConfig->loopNums = atoi(optarg);
                break;
            case 'd':
                decConfig->device_index = atoi(optarg);
                break;
            default:
                usage(argv[0]);
                return 0;
            }
        }
        if (decConfig->loopNums <= 0)
            decConfig->loopNums = 1;
    }
}
```

## getJpgEncOpenParam

这个接口实现从输入参数解析到内容的配置结构体中拿到关于打开一个编码器需要的部分参数。

**接口形式：**
```c
static int getJpgEncOpenParam(
    EncConfigParam *pEncConfig, 
    BmJpuEncOpenParams* pEncOP
);
```

**参数说明：**
- **pEncConfig**：EncConfigParam结构体指针变量，指向的对象保存了从输入参数解析到的数据，对应编码需要的配置参数
- **pEncOP**：BmJpuEncOpenParams结构体指针变量，该指针指向的对象将获取配置参数中相关的参数，用于打开一个编码器

**代码示例：**
```c
static int getJpgEncOpenParam(EncConfigParam *pEncConfig,
                                BmJpuEncOpenParams* pEncOP)
{
    int ret = 0;
    if(pEncConfig == NULL || pEncOP == NULL)
        return 1;
    strcpy(cfgFileName, pEncConfig->cfgFileName);
    ret = parseJpgCfgFile(pEncConfig, cfgFileName);
    pEncOP->frame_width = pEncConfig->picWidth;
    pEncOP->frame_height = pEncConfig->picHeight;
    pEncOP->color_format = pEncConfig->srcFormat;
}
```

**其中parseJpgCfgFile接口** 实现了将编码配置参数里的对比文件名中的内容读取到了编码配置文件中。

## bm_jpu_calc_framebuffer_sizes

这个接口是用来转换参数，将从用编码配置文件中去读到的关于编码器的设置的一些信息进行转化。

**接口形式：**
```c
int bm_jpu_calc_framebuffer_sizes(
    BmJpuColorFormat color_format, 
    unsigned int frame_width, 
    unsigned int frame_height, 
    unsigned int framebuffer_alignment, 
    int chroma_interleave, 
    BmJpuFramebufferSizes *calculated_sizes
);
```

**参数说明：**
- **color_format**：BmJpuColorFormat结构体变量，用于记录处理编码帧数据的数据格式
- **frame_width**：表示帧数据的宽度
- **frame_height**：表示帧数据的高度
- **framebuffer_alignment**：表示缓冲区在内存中的对齐方式，设置的大小为16
- **chroma_interleave**：表示色度分量的存储方式，是否需要色度交错存储
- **calculated_sizes**：BmJpuFramebufferSizes结构体变量，用于存储计算得到的帧缓冲区大小

**代码示例：**
```c
int framebuffer_alignment = 16;
bm_jpu_calc_framebuffer_sizes(open_params.color_format,
                            open_params.frame_width,
                            open_params.frame_height,
                            framebuffer_alignment,
                            open_params.chroma_interleave,
                            &calculated_sizes);
```

## bm_jpu_jpeg_enc_open

这个接口是用来打开一个对应索引号的编码器，并将索引号保留在结构体中。

**接口形式：**
```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_open(
                    BmJpuJPEGEncoder **jpeg_encoder,
                    int                bs_buffer_size,
                    int                device_index
)
```

**参数说明：**
- **jpeg_encoder**：BmJpuJPEGEncoder结构体二级指针变量，对应的结构体成员具有整个编码过程需要的所有信息
- **bs_buffer_size**：表示用于存储图片编码输出数据所需要的缓冲区大小
- **device_index**：表示设备索引号来确定使用的设备

**代码示例：**
```c
ret = bm_jpu_jpeg_enc_open(&(jpeg_encoder), bs_buffer_size, encConfig.device_index);
if (ret != BM_JPU_ENC_RETURN_CODE_OK)
{
    fprintf(stderr, "Error! Failed to open bm_jpu_jpeg_enc_open() :  %s\n",
            bm_jpu_enc_error_string(ret));
    goto  cleanup;
}
```

# LoadYuvImage

这个接口是将源图像数据存储的地址，通过framebuffer的偏移将目的内存进行分开，然后实现数据的拷贝。

## 接口形式

```c
int LoadYuvImage(
    int format, 
    int interleave, 
    int packed, 
    int width, 
    int height, 
    BmJpuFramebuffer* framebuffer,
    BmJpuFramebufferSizes * calculated_sizes, 
    uint8_t* dst, 
    uint8_t* src
);
```

## 参数说明

- **format**：format表示图像的格式，对应YUV图像的颜色空间编码方式如FORMAT_420等。

- **interleave**：interleave表示是否使用色差交错进行存储，非零值表示进行交错，零表示分开存储。

- **packed**：packed表示输出的打包方式。非零则表示使用一种打包方式，零则是不打包输出。

- **width**：width表示输出图像的宽度。

- **height**：height表示输出图像的高度。

- **framebuffer**：framebuffer是一个BmJpuFramebuffer结构体指针变量，用来用处指向buffer空间的首地址。

- **calculated_sizes**：calculated_sizes指向 BmJpuFramebufferSizes 结构体的指针，用于输出计算得到的帧缓冲区大小。

- **dst**：dst是一个指向目标缓冲区的指针，表示要将加载的图片数据拷贝到位置。

- **src**：src是一个指向原图像数据的指针，表示要加载的图像数据的起始位置。

## 代码示例

```c
LoadYuvImage(encConfig.srcFormat, open_params.chroma_interleave, open_params.packed_format, encConfig.picWidth,
encConfig.picHeight, &framebuffer, &calculated_sizes, (uint8_t*)p_virt_addr, pSrcYuv);
```

# WritePlane

这个接口是完成数据按照宽度拷贝的具体实现。

## 接口形式

```c
void WritePlane(
    int width, 
    int height, 
    int stride, 
    uint8_t* dst, 
    uint8_t* src
    );
```

## 参数说明

- **width**：width表示图片的宽度。

- **height**：height表示图片的高度。

- **stride**：stride表示拷贝一个宽度的数据因为对其需要指针移动对对齐的宽度大小。

- **dst**：dst是一个指向目标缓冲区的指针，表示要将加载的图片数据拷贝到位置。

- **src**：src是一个指向原图像数据的指针，表示要加载的图像数据的起始位置。

## 代码示例

```c
chromaSize = cbcr_w * cbcr_h;
lumaSize = width * height;
if(!packed)  //planner mode
{
    WritePlane(width, height, stride, dst_y,src);           // write Y
    WritePlane(cbcr_w, cbcr_h, cbcr_stride, dst_cb, src+lumaSize);   // write U or UV(interleave)
    if(interleave == CBCR_SEPARATED)
        WritePlane(cbcr_w, cbcr_h, cbcr_stride, dst_cr, src+lumaSize + chromaSize);   // write V
}
else{   //packed mode
    if(packed == PACKED_FORMAT_444)
    {
        w = 3 * width;
        packed_stride = 3 * stride;
    }
    else
    {
        w = 2 * width;
        packed_stride = 2 * stride;
    }
    h = height;
    lumaSize =w * h;
    if(width == stride)
        memcpy(dst_y, src,lumaSize);
    else
        WritePlane(w, h, packed_stride, dst_y,src);
}
```

# Multi_struct

## MultiConfigParam

MultiConfigParam 是在一个包括编码或者解码的选项参数的结构体。

MultiConfigParam 结构体定义如下:

```c
typedef struct {
    int codecMode;
    int numMulti;
    int saveYuv;
    int multiMode[MAX_NUM_INSTANCE];
    EncConfigParam encConfig[MAX_NUM_INSTANCE];
    DecConfigParam decConfig[MAX_NUM_INSTANCE];
} MultiConfigParam;
```

### 成员说明

- **codecMode**：codecMode表示

- **numMulti**：numMulti参数

- **saveYuv**：saveYuv用于指示是否要保存原始的YUV数据。

- **multiMode**：multiMode是一个数组，数组的大小是由MAX_NUM_INSTANCE来确定，每一个成员可以对应是编码还是解码模式。

- **encConfig**：encConfig参数是一个EncConfigParam结构体数组，数组大小是由MAX_NUM_INSTANCE来确定，数组的每一个成员都是一个确定编码的数组，来确定每一个编码的过程的需要。

**其中 EncConfigParam 的定义如下**

```c
typedef struct
    {
        char yuvFileName[MAX_FILE_PATH];
        char bitStreamFileName[MAX_FILE_PATH];
        char cfgFileName[MAX_FILE_PATH];
        char refFileName[MAX_FILE_PATH];
        int picWidth;
        int picHeight;
        int frameFormat;
        int srcFormat;
        unsigned int loopNums;
        int  instanceIndex;
        int device_index;
        int rotate;
        int Skip;
    } EncConfigParam;
```

EncConfigParam结构体是包括编码输入的文件名yuvFileName，编码输出的文件名bitStreamFileName，对比文件名refFileName，包括打开编码器需要的配置信息的文件名cfgFileName，可以在这个里面获得原图片大小等信息。表示输入图片宽度的picWidth，表示输入图片高度的picHeight，表示帧格式的frameFormat，输出图片的格式srcFormat，表示循环次数的loopNums，表示在具有多实例的情况通过索引确定实例，表示要使用设备的索引参数的device_index,表示是否使用旋转的选项的rotation表示跳过标志指示是否跳过部分编码操作或处理流程的Skip。

- **decConfig**：decConfig参数是一个DecConfigParam结构体数组，数组大小是由MAX_NUM_INSTANCE来确定，数组的每一个成员都是一个确定解码的数组，来确定每一个解码的过程的需要。

**其中 DecConfigParam 的定义如下**

```c
typedef struct
    {
        char yuvFileName[MAX_FILE_PATH];
        char bitStreamFileName[MAX_FILE_PATH];
        char refFileName[MAX_FILE_PATH];
        unsigned int loopNums;
        int  instanceIndex;
        int device_index;
        int Skip;
    } DecConfigParam;
```

DecConfigParam 结构体是包括解码输出的文件名yuvFileName，解码输入的文件名bitStreamFilename，以及进行对比的文件名refFileName，表示循环次数的loopNums，表示要进行线程数量instanceIndex，表示要使用的设备的索引device_index，表示跳过标志指示是否跳过部分解码过程或处理过程的Skip。

## BmJpuEncOpenParams

BmJpuEncOpenParams结构体的成员包括了用配置文件中去读到数对一个编码器的设置的一些信息。

BmJpuEncOpenParams 结构体定义如下:

```c
typedef struct{
    unsigned int frame_width;
    unsigned int frame_height;
    BmJpuColorFormat color_format;
    unsigned int quality_factor;
    int chroma_interleave;
    int packed_format;
    int device_index;
    int rotationEnable;
    int mirrorEnable;
    int mirrorDirection;
    int rotationAngle;
}BmJpuEncOpenParams;
```

### 成员说明

- **frame_width**：frame_width表示输入图像帧的宽度。

- **frame_height**：frame_height表示输入图像帧的高度。

- **color_format**：color_format是一个BmJpuColorFormat枚举类型变量，包括了图片的颜色格式类型。

- **quality_factor**：quality_factor表示质量因子，通常用于控制图像或视频的压缩比例

- **chroma_interleave**：chroma_interleave用于表示色度分量的存储方式。

- **packed_format**：packed_format指示了图像或视频数据中像素值的打包格式。

- **device_index**：device_index记录了设备序号。

- **rotationEnable**：rotationEnable表示是否使用翻转的操作。

- **mirrorEnable**：mirrorEnable选择图片是否可以镜像操作。

- **mirrorDirection**：mirrorDirection用于指示镜像操作的方向，可能是水平或者垂直。

- **rotationAngle**：rotationAngle表示图片需要旋转的角度，可以有90、180、270度。

# Use case

## JPEG DEC

### 单路解码

```c
bmjpegdec -i JPEG_1920x1088_yuv420_planar.jpg -o out_1920x1088_yuv420_planar.yuv -n 1
```

### 单路解码循环

```c
bmjpegdec -i JPEG_1920x1088_yuv420_planar.jpg -o out_1920x1088_yuv420_planar.yuv -n 10
```

### 32路解码

```c
首先设置multi.lst配置文件，内容如下（每一行表示路数和每路的循环次数，之后每一行表示每一路的配置）

32 100
JPEG_352x288_yuv420_planar.jpg 32 1 0 0
JPEG_352x288_yuv420_planar.jpg 32 1 0 0
...(重复配置到32行)

然后执行

bmjpegmulti -f multi.lst

选项输入 30
```

## JPEG Enc

### 单路编码

```c
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1
```

### 单路编码循环

```c
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 10000
```

### 单路旋转编码

```c
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1 -g 1
```

### 单路镜像编码

```c
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1 -g 4
```

### 32路编码

```c
首先编写配置文件

touch enc.cfg; vim enc.cfg

    enc.cfg配置如下：

YUV_SRC_IMG JPEG_352x288_yuv420_planar.yuv
FRAME_FORMAT 0
PICTURE_WIDTH 352
PICTURE_HEIGHT 288
IMG_FORMAT 0

然后编写multi.lst配置文件

touch multi.lst; vim multi.lst

    multi.lst配置文件内容

32 1000000
enc.cfg 32 0 0 0
enc.cfg 32 0 0 0
...（重复到32行）

最后执行

bmjpegmulti -f multi.lst

选项输入 30
```

### YUV400的编码，YUV420P编码和YUV422P编码

```c
YUV400----bmjpegmulti -t 1 -i JPEG_1920x1088_yuv400_planar.yuv -o OUT400.jpg -w 1920 -h 1088 -s 4 -f 0 -n 4

YUV420P---bmjpegmulti -t 1 -i JPEG_1920x1088_yuv420_planar.yuv -o OUT420_planar.jpg -w 1920 -h 1088 -s 0 -f 0 -n 4

YUV422P---bmjpegmulti -t 1 -i JPEG_1920x1088_yuv422_planar.yuv -o OUT422_planar.jpg -w 1920 -h 1088 -s 1 -f 0 -n 4
```

# 视频解码

## 常见问题

### 如何判断视频花屏的原因

答：这里提的视频花屏是长时间的花屏，对于偶尔的花屏有可能是网络数据传输错误导致的，此类不属于应用代码可控的方位。如果视频出现长时间的花屏，很大概率是由于视频帧读取不及时，导致内部缓存满以后，socket recv buffer溢出导致的。

1. 将加大rmem_max到2M，如果此时花屏消失，说明应用的数据处理抖动很大，应该要加大buffer queue进行平滑

   ```
   echo 2097152 > /proc/sys/net/core/rmem_max
   ```

2. 用netstat -na，一般是一下格式，找到rtsp的那个端口（udp在应用中会有打印，tcp的话可以看目标rtsp地址），这里的Recv-Q，Send-Q在正常情况应该都是0，或者不满的，如果Recv-Q经常有很大的数，就说明overflow了。一般Send-Q不会出问题，如果这个也很大的话，那么很可能network driver驱动挂死了。

   ```
   Proto Recv-Q Send-Q Local Address Foreign Address State
   tcp 0 0 0.0.0.0:111 0.0.0.0:* LISTEN
   ```

### 解码不正确或者无法解码的最终调试手段

答：如果经常各种调试后，在现场仍然无法解决问题，可以通过打开环境变量，把问题发生前后的数据dump下来，供后续进行进一步分析

```
export BMVPU_DEC_DUMP_NUM=1000
```

这个配置会在两个文件之间循环存储1000帧数据，当问题发生的时候，把这两个发生前后的那个1000帧文件拷贝回来就可以。两个文件的存储位置在/data/core_%dinst%d_stream%d.bin。

### 判断rtsp是否正常工作

答：

方法一：通过vlc播放视频（推荐），分别设置tcp，udp方式

方法二：使用vidmutil测试程序播放，vidmutil默认是 udp方式，通过设置环境变量使用tcp方式。

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|buffer_size;1024000|max_delay;50000"
sudo -E ./vidmulti thread_num input_video [card] [enc_enable] input_video [card] [enc_enable]...
```

### 播放rtsp流出现断连情况验证

答：可以使用vlc播放相同的视频，在相同的时间下，看vlc播放是否有断连的情况，注意设置vlc的缓冲区大小。

### 验证当前rtsp服务输出的视频是否有花屏

答：使用vlc播放视频，持续一段时间，看视频是否有花屏

### 查看rtsp服务是否实时推流

答：通过rtspserver日志，查看当前播放的文件是否正在发送。

### ffmpeg&opencv 支持 gb28181 协议，传入的url地址形式如下

**udp实时流地址**

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip：本地ip，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口（rtp:11801,rtcp:11802），两个端口映射的in和out要相同。同一个核心板端口不可重复。
```

**udp回放流地址**

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype：录像存储累类型
localid：本地20位编码，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localip：本地ip，可选项
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口（rtp:11801,rtcp:11802），两个端口映射的in和out要相同。同一个核心板端口不可重复。
begtime：录像起始时间
endtime：录像结束时间
```

**tcp实时流地址**

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip: 本地ip，是可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
```

**tcp回放流地址**

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype :录像存储累类型
localid :本地20位编码，可选项
localip :本地ip，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
begtime :录像起始时间
endtime :录像结束时间
```

注意：

1. 流媒体传输默认是udp方式，如果使用tcp方式获取实时流或回放流，需要显示的指定。

   Ffmpeg指定tcp方式为接口调用 通过av_dict_set设置 gb28181_transport_rtp 为tcp。

   Opencv指定方式是设置环境变量

   ```
   export OPENCV_FFMPEG_CAPTURE_OPTIONS="gb28181_transport_rtp;tcp"
   ```

2. 如果使用udp方式外部无法访问到内部ip/port，localmediaport需要做端口映射，端口映射需要两个 rtp和rtcp。

3. 做端口映射时，使用的端口号尽量不要太大，推荐10000--20000的端口，socket端口号的最大值时65536，但是很情况下，端口号是受很多资源的限制。端口号使用过大可能会出现：[bind failed] 错误打印。

### BM168x解码性能对于H264/H265有差别吗？如果调整码率的话，最多可以解多少路呢？有没有对应的数据参考？

答：

264，265是解码路数相同的。

码率对解码帧率会有影响，这个变化就需要实测，例如我们说的BM1688解码能达到480fps是针对监控码流而言的，这类监控码流没有B帧，场景波动较小，码率基本在2~4Mbps。如果是电影或者其他码率很高的，比如10Mbps，20Mbps甚至更多，是会有明显影响的，具体多大这个需要实测。

分辨率对于解码帧率的影响，是可以按照比例来换算的。我们说的480fps是针对1920x1080 HD分辨率而言的。

### 是否可以通过抽帧来提高BM168x的解码路数

答：

我们opencv中提供的抽帧，是在解码出来的结果中做的，并不是只解I/P帧的抽帧概念。这里的抽帧解码主要是保证出来帧数的均匀，使得后续的分析处理是等间隔的进行，这是为后续模型分析比较复杂的时候，不能达到每帧都检测而设计的解决方案，但并不能达到增加解码路数的效果。

这里顺便解释下，为什么不提供只解I/P帧的抽帧功能。如果只解I、P帧的话，抽帧的间隔就完全取决于码流的编码结构，这样是比较难控制住性能，比如监控码流中的没有B帧，那其实就相当于没有抽帧了。如果客户可以控制编码端，那更切合实际的做法是直接降低编码端的编码帧率，比如降到15fps，那样解码路数就可以直接提升；反之，如果客户没有办法控制编码端，那么同样的，只解IP帧的抽帧方式就也无法达到增加解码路数的效果。

### Valgrind内存检查为什么有那么多警告，影响到应用的调试了

答：

我们的版本发布每次都会用valgrind检查一遍内存泄漏问题，如果有内存泄露问题我们会检查修正的。之所以没有去掉有些警告，是因为这些警告大部分都是内存没有初始化，如果对这些内存每个都加上初始化，会明显导致速度性能下降，而且我们确认后续操作是在硬件对其赋值后再进行的，对于此类警告，我们就不会去消除。

为了避免警告过多对上层应用调试造成影响，建议使用valgrind的suppression功能，可以通过过滤配置文件，来避免我们模块产生的valgrind警告，从而方便上层应用调试自身的程序。

### 如何查看vpu/jpu的内存、使用率等状态

答：

1）BM1684 & 84x

在soc模式下，可以用下面的方法查看：

```
cat /proc/vpuinfo
cat /proc/jpuinfo
```

2）BM1688

```
cat /proc/soph/vpuinfo
cat /proc/soph/jpuinfo
A2上vpp和jpeg共用同一个heap
cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
```

### 视频支持16路甚至更多的时候，报视频内存不够使用，如何优化内存使用空间

答：

在soc模式下，不同信号的设备VPP HEAP的默认大小是不同的，需要根据应用场景来合理规划内存。

如果解码使用的是FFMPEG框架，首先保证视频输出格式使用压缩格式，即output_format 101。Opencv框架的话，内部已经默认使用压缩格式了；

其次如果应用在获取到解码输出avFrame后，并不是直接压入队列，而是转换到RGB或者非压缩数据后再缓存的话，可以用av_dict_set extra_frame_buffer_num为1（默认为2）。Opencv内部在最新版本中会默认优化。

最后，如果以上优化过后，仍然不够的话，在soc模式下可以考虑更改dtb设置，给视频挪用分配更多的内存，当然相应的，其他模块就要相应的减少内存。这个要从系统角度去调配。

### 启动设备首次执行某个函数慢，重启进程再次运行正常

现象：设备上电后第一次执行程序，函数处理时间长，再次执行程序，运行正常。

解决：先做个验证，如果不重启可复现，就说明是文件cache导致的变慢。

1. 上电后第一次执行慢，第二次执行正常，之后进入root用户
2. 清除cache echo 3 > /proc/sys/vm/drop_caches
3. 再次执行程序，运行慢，即可确定是cache导致的。

### 程序提示"VPU_DecGetOutputInfo decode fail framdIdx xxx error(0x00000000) reason(0x00400000), reasonExt(0x00000000)"是可能什么问题，这里reason的具体数值可能不同

这个提示通常是由码流错误造成的，提示的含义是第xxx帧解码错误，错误原因为....。这里具体原因对于上层应用来说，不用关心，只需知道这是由码流错误导致的即可。

进一步分析，导致码流错误的原因通常可以分为两类，我们要有针对的进行处理。因为一旦频繁出现这种提示，说明解码出来的数据是不正确的，这时候有可能是各种马赛克或者图像花，对于后续的处理会造成各种异常情况，所以我们必须尽量减少这种情况的发生。

1. 网络情况导致的丢包。这时候可以用我们的测试程序vidmulti验证下，如果vidmulti没有解码错误，那么可以排除这种情况。如果确认网络丢包的话，要分辨下是否网络带宽本身就不够，如果本身带宽不够，那没有办法，只能降低视频码流的码率。如果带宽是够的，要检查下网线。当码流连接数超过20多路的时候，这时候有可能已经超出百兆了，这时网线也必须换到CAT6，与千兆网相匹配

2. 解码性能达到上限造成丢包。这种情况发生在流媒体环境中，对于文件播放是不会发生的。这时也可以用我们的vidmulti跑一下，作为比较。如果vidmulti也发生错误，说明性能确实到了上限了，否则说明应用本身还有优化的空间。

### 程序提示"coreIdx 0 InstIdx 0: VPU interrupt wait timeout"，这是怎么回事？

这个提示表示视频解码或者编码中断超时。这个提示只是警告，会再次尝试，因此只要没有连续出现就可以忽略。这种情况一般是由解码数据错误导致或者负荷过重产生的。例如在板卡情况下，由于板卡数据交换过于频繁，造成解码或者编码数据传输堵塞，使得中断超时。

### 申请设备内存失败，错误返回-24。

设备内存每一次申请都会有一个fd，ubuntu上最大1024。如果持续申请且不释放，fd数量超过1024，就会导致申请设备内存失败，错误返回-24。
如果想扩大ubuntu的fd数量，可通过ulimit命令修改限制。如 ulimit -n 10000 可将ubuntu的fd数量扩大至10000。

### url特殊字符对照表

有些符号在URL中是不能直接传递的，如果要在URL中传递这些特殊符号，需要使用其编码值。

编码的格式为：%加字符的ASCII码。

| 字符 | 编码值 |
|------|--------|
| 空格 | %20    |
| "    | %22    |
| #    | %23    |
| &    | %26    |
| (    | %28    |
| )    | %29    |
| +    | %2B    |
| ,    | %2C    |
| /    | %2F    |
| :    | %3A    |
| ;    | %3B    |
| <    | %3C    |
| =    | %3D    |
| >    | %3E    |
| ?    | %3F    |
| @    | %40    |
| \\   | %5C    |
| \|   | %7C    |

## bm_ffmpeg问题

### Ffmpeg的阻塞问题

原因分析：如果没有及时释放avframe，就会导致阻塞，vpu内部是循环buffer。

### 无法连接rtsp？

答：可以通过ffmpeg固有命令来进行连接测试：（url为rtsp连接地址）

```
ffmpeg -rtsp_transport tcp -i url -f rawvideo -y /dev/null
或者
ffmpeg -rtsp_transport udp -i url -f rawvideo -y /dev/null
若以上无法连接成功，请检查网络。
```

### 确认解码器是否能正常工作：（url为文件名或者rtsp连接地址）

答：

```
ffmpeg -i url -f rawvideo -y /dev/null
```

# FFMPEG JPEG 编码与转码应用示例

## 调用JPEG编码的ffmpeg命令

```
ffmpeg -c:v jpeg_bm -i src/5.jpg -c:v jpeg_bm -is_dma_buffer 1 -y 5nx.jpg
```

## 调用动态JPEG转码的ffmpeg命令

```
ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.avi -c:v jpeg_bm -is_dma_buffer 1 -y test_avi.mov

ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.mov -c:v jpeg_bm -is_dma_buffer 1 -y test_mov.mov
```

# 如何从FFMPEG的输入缓冲区中读取 bitstream?

FFMPEG 源码应用示例
/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_reading.c (or http://www.ffmpeg.org/doxygen/trunk/doc_2examples_2avio_reading_8c-example.html)

在这一示例中，libavformat demuxer 通过 **custom AVIOContext read callback** 访问媒体信息，而不是通过在传入FFMPEG中的文件、rstp等协议访问媒体信息的。

以下是middleware-soc中的一个使用avio + jpeg_bm解码静态jpeg图片的例子。
(/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_decode_jpeg.c)

# 在soc模式下客户用ffmpeg解码时拿到AVframe将data[0-3] copy到系统内存发现copy时间是在20ms左右而相同数据量在系统内存两块地址copy只需要1-3ms

上述问题的原因是系统在ffmpeg中默认是禁止cache的，因此用cpu copy性能很低。

使能cache就能达到系统内存互相copy同样的速度。可以用以下接口使能cache。

```
av_dict_set_int(&opts, "enable_cache", 1, 0);
```

但是这样直接copy数据保存是非常占用内存、带宽和cpu算力的，我们推荐采用零拷贝的方式来实现原始解码数据的保存：

1. 推荐使用 extra_frame_buffer_num 参数指定增大硬件帧缓存数量，可以根据自己的需要选择缓存帧的数量。这个方式的弊端，一个是占用解码器内存，可能减少视频解码的路数；另一个是当不及时释放，当缓存帧全部用完时，会造成视频硬件解码堵塞。

```
av_dict_set_int(&opts, "extra_frame_buffer_num", extra_frame_buffer_num, 0);
```

2. 推荐使用 output_format参数设置解码器输出压缩格式数据，然后使用vpp处理输出非压缩yuv数据（当需要缩放，crop时，可以同步完成），然后直接零拷贝引用非压缩yuv数据。这种方式不会影响到硬件解码性能，并且可以缓存的数据空间也大很多。

```
av_dict_set_int(&opts, "output_format", 101, 0);
```

# [问题分析]客户反馈碰到如下错误提示信息"VPU_DecRegisterFrameBuffer failed Error code is 0x3", 然后提示Allocate Frame Buffer内存失败

这个提示信息表示：分配的解码器缓存帧个数，超过了最大允许的解码帧。导致这个问题的原因有可能是：

1. 不支持的视频编码格式，比如场格式，此时可以用FAQ14的方法，把码流数据录下来，提交给我们分析。

2. 设置了过大的extra_frame_buffer_num。理论上，extra_frame_buffer_num不能超过15，超过了以后就有可能不能满足标准所需的最大缓存帧数。因为大部分编码码流并没有用到最大值，所以extra_frame_buffer_num大于15的时候，对大部分码流仍然是可以工作的。

目前发现可能导致这个问题的原因有上述两种，后续有新的案例继续增补

# 采用TCP传输码流的时候如果码流服务器停止推流，ffmpeg阻塞在av_read_frame

这是因为超时时间过长导致的，可以用一下参数设置超时时间减短。

```
av_dict_set(&options, "timeout", "1000000", 0);
```

# 将 output_format 设置为101后，发现解压缩后的yuv花屏

这是因为输入码流的编码分辨率和显示分辨率存在差异导致的，avFrame中保存的是yuv的显示分辨率，而vpp解压缩需要使用编码分辨率。

解决方案是使用 AVCodecContext 中的 coded_width 和 coded_height 来作为宽高信息传递给VPSS做解压缩。

# 使用ffmpeg命令 "ffmpeg -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4" 进行转码时，程序卡死

提示如下错误信息：

```
[h264_bm @ 0x481190] bmvpu_dec_get_output timeout. dec_status:6 endof_flag=0 pkg:1
```

原因是默认的解码输出缓冲区配置较小，编码需要的参考帧较多，导致输出缓冲区不够用，解码器被block住。解码器默认的输出缓冲区配置的比较小是考虑到设备内存的资源占用，并非所有使用场景都需要较大的输出缓冲区。

可以通过配置 "extra_frame_buffer_num" 参数来增加解码缓冲区。

例如采用以下命令：

```
ffmpeg -extra_frame_buffer_num 10 -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4
```

程序运行日志中会通过以下信息提示所需配置的解码缓冲区的大小，可以参考该信息进行配置。

```
[h264_bm @ 0x491500] Minimum number of input frame buffers for BM video encoder: 8
```

# ffmpeg 命令使用压缩模式解码、解压缩、编码

将 scale_bm 设为输入的w和h，将只做解压缩，数据在转码过程中，没有经过系统内存拷贝

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=iw:ih:zero_copy=1" -c:v h264_bm -g 50 -b:v 32K -y wkc_100_out.h264
```

# cmd_queue设置

cmd_queue可以设置的值为1--4，是为硬件编解码增加队列，提高性能，带来的坏处就是增加了物理内存的消耗。如果物理内存不足，可以尝试将cmd_queue设置为1。

编码cmd_queue设置
```
av_dict_set_int(&opts, "enc_cmd_queue", 1, 0);
```

解码cmd_queue设置
```
av_dict_set_int(&opts, "dec_cmd_queue", 1, 0);
```

# bm_opencv问题

## opencv下如何获取视频帧的timestamp？

opencv原生提供了获取timestamp的接口，可以在cap.read()每一帧后获取当前帧的timestamp。

代码如下：

```
Mat frame;
cap.read(frame);
/* 获取timestamp，返回值为double类型 */
int64_t timestamp = (int64_t)cap.getProperty(CAP_PROP_TIMESTAMP);
```

## SA3 opencv下videocapture经常5分钟左右断网的解决方案

在udp方式下,SA3经常发生RTSP数据连上后3-5分钟就"connection timeout"的问题，这个问题最终解决方案是更新最新的路由板软件。验证方法可以用TCP测试下，如果TCP没有问题可以确认是这类问题。

使用TCP的方式见下面：

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"
```

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）
注意：最新的middleware-soc将使用TCP作为默认协议，对原来客户需要使用UDP传输协议的，需要引导客户按照下面方式进行设置

使用UDP方式：

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;udp"
```

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）

UDP适用的环境：当网络带宽比较窄，比如4G/3G等移动通信系统，此时用udp比较合适
TCP适用的环境：网络带宽足够，对视频花屏要求比较高，对延时要求较小的应用场景，适合TCP

## 如何获取rtsp中原来的timestamp

opencv中默认获取的rtsp时间戳是从0开始的，如果想获取rtsp中的原始时间戳，可以用环境变量进行控制, 然后按照问题1进行获取即可

```
export OPENCV_FFMPEG_CAPTURE_OPTOINS="keep_rtsp_timestamp;1"
```

注意:外置的options会覆盖内部默认的设置，因此最好按照完整的options来设置

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="keep_rtsp_timestamp;1|buffer_size;1024000|max_delay;500000|stimeout;20000000"
```

## 确认解码器和VPSS的OpenCV接口是否正常工作：

```
vidmulti number_of_instances url1 url2
```

## 对于cvQueryFrame等老的opencv接口支持状况

有些客户采用旧版opencv的C接口，接口列表如下

```
void cvReleaseCapture( CvCapture** pcapture )

IplImage* cvQueryFrame( CvCapture* capture )

int cvGrabFrame( CvCapture* capture )

IplImage* cvRetrieveFrame( CvCapture* capture, int idx )

double cvGetCaptureProperty( CvCapture* capture, int id )

int cvSetCaptureProperty( CvCapture* capture, int id, double value )

int cvGetCaptureDomain( CvCapture* capture)

CvCapture * cvCreateCameraCapture (int index)

CvCapture * cvCreateFileCaptureWithPreference (const char * filename, int apiPreference)

CvCapture * cvCreateFileCapture (const char * filename)
```

对于这些接口，大部分都是支持的，只有返回值是iplImage的接口无法支持，这是因为我们硬件底层的ion内存类型是保存在MAT的uMatData类型中的，而iplIMage类型没有uMatData数据结构。

因此对于客户目前使用 cvQueryFrame接口的，建议客户基于cap.read接口封一个返回值为Mat数据的C函数接口，不要直接调用opencv老版的接口。

## Opencv中mat是如何分配设备内存和系统内存的？

因为受设计影响，这个问题细节比较多，主要从三方面能解释。

1. 在soc模式下，设备内存和系统内存是同一份物理内存，通过操作系统的ION内存进行管理，系统内存是ION内存的mmap获得。

在pcie模式下，设备内存和系统内存是两份物理内存，设备内存指BM168x卡上的内存，系统内存指服务器上操作系统内存。如果用户想只开辟系统内存，和开源opencv保持一致，可以参见FAQ26的回答。

2. 在sophon opencv中默认会同时开辟设备内存和系统内存，其中系统内存放在mat.u->data或mat.data中，设备内存放在mat.u->addr中。只有以下几种情况会不开辟设备内存，而仅提供系统内存：

   - 当data由外部开辟并提供给mat的时候。即用以下方式声明的时候：
     ```
     Mat mat(h, w, type, data); 或 mat.create(h, w, type, data)；
     ```

   - 在soc模式下，当type不属于（CV_8UC3, CV_32FC1, CV_32FC3）其中之一的时候。这里特别注意CV_8UC1是不开辟的，这是为了保证我们的opencv能够通过开源opencv的opencv_test_core的一致性验证检查。

   - 当宽或者高小于16的时候。因为这类宽高，硬件不支持

3. 在BM1688的SOC模式下，mat分配的CV_8UC3类型的设备内存会自动做64对齐，即分配的内存大小一定是64对齐的（注意：仅对soc模式的CV_8UC3而言，且仅对BM1688芯片）。

在PCIE模式下，分配的内存是byte对齐的。

## Opencv mat创建失败，提示"terminate called after throwing an instance of 'cv::Exception' what(): OpenCV(4.1.0) …… matrix.cpp:452: error: (-215:Assertion failed) u != 0 in function 'creat'"

这种错误主要是设备内存分配失败。失败的原因有两种：

1. 句柄数超过系统限制，原因有可能是因为句柄泄漏，或者系统句柄数设置过小，可以用如下方法确认：

   查看系统定义的最大句柄数：
   ```
   ulimit -n
   ```

   查看当前进程所使用的句柄数：
   ```
   lsof -n|awk '{print $2}'|sort|uniq -c|sort -nr|more
   ```

2. 设备内存不够用。可以用如下方法确认：

   - SOC模式下
     ```
     cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary
     ```

   - PCIE模式下， bm-smi工具可以查看设备内存空间

解决方案：在排除代码本身的内存泄漏或者句柄泄漏问题后，可以通过加大系统最大句柄数来解决句柄的限制问题：ulimit -HSn 65536

设备内存不够就需要通过优化程序来减少对设备内存的占用，或者通过修改dts文件中的内存布局来增加对应的设备内存。

## Opencv用已有Mat的内存data，宽高去创建新的Mat后，新Mat保存的图像数据错行，显示不正常

保存的图像错行，通常是由于Mat中step信息丢失所造成。

一般用已有Mat去生成一个新Mat，并且要求内存复用时，可以直接赋值给新的Mat来简单实现，如 Mat1 = Mat2.

但在某些情况下，比如有些客户受限于架构，函数参数只能用C风格的指针传递，就只能用Mat中的data指针，rows，cols成员来重新恢复这个Mat。这时候就需要注意step变量的设置，在默认情况下是AUTO_STEP配置，即每行数据没有填充数据。但是在很多种情况下，经过opencv处理后，会导致每行出现填充数据。如，

1. soc模式下，我们的Mat考虑执行效率，在创建Mat内存时每行数据会做64字节对齐，以适配硬件加速的需求（仅在soc模式下）
2. opencv的固有操作，如这个Mat是另一个Mat的子矩阵（即rect的选定区域），或者其他可能导致填充的操作。

因此，按照opencv定义，通用处理方式就是在生成新的Mat的时候必须指定step，如下所示:

```
cv::Mat image_mat = cv::imread(filename,IMREAD_COLOR,0);
cv::Mat image_mat_temp(image_mat.rows,image_mat.cols,CV_8UC3,image_mat.data,image_mat.step[0]);
cv::imwrite("sophgo1.jpg",image_mat_temp);
```

## 在opencv VideoCapture 解码视频时提示: maybe grab ends normally, retry count = 513

上述问题是因为在VideoCapture存在超时检测，如果在一定时间未收到有效的packet则会输出以上log，此时如果视频源是网络码流可以用vlc拉流验证码流是否正常，如果是文件一般是文件播放到末尾需调用VidoeCapture.release后重新VideoCapture.open

## SOC模式下，opencv在使用8UC1 Mat的时候报错，而当Mat格式为8UC3的时候，同样的程序完全工作正常

这个问题碰到的客户比较多，这次专门设立一个FAQ以便搜索。其核心内容在FAQ46 "Opencv中mat是如何分配设备内存和系统内存的"有过介绍，可以继续参考FAQ46

在soc模式下，默认创建的8UC1 Mat是不分配设备内存的。因此当需要用到硬件加速的时候，比如推理，bmcv操作等，就会导致各种内存异常错误。

解决方案可以参看FAQ26 "如何指定Mat对象基于system memory内存去创建使用", 指定8UC1 Mat在创建的时候，内部使用ion分配器去分配内存。如下所示。

```
cv::Mat gray_mat;
gray_mat.allocator = hal::getAllocator();
gray_mat.create(h, w, CV_8UC1);
```

# 如何跨进程传递Mat信息，使不同进程间零拷贝地共享Mat中的设备内存数据？

跨进程共享Mat的障碍在于虚拟内存和句柄在进程间共享非常困难，因此解决这个问题的本质是：如何由一块设备内存，零拷贝地重构出相同的Mat数据结构。

解决这个问题会用到下面三个接口，其中前两个接口用于重构yuvMat的数据，后一个接口用于重构opencv 标准Mat的数据。

```cpp
cv::av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MMPEG, int id = 0)
cv::Mat(AVFrame *frame, int id)
Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data,unsigned long addr, int fd, int id = 0)
```

```cpp
/* 完整的跨进程共享Mat的代码如下所示。跨进程共享的方法很多，下面的例子目的在于展示如何
   使用上面的函数重构Mat数据，其他的代码仅供参考。其中image为需要被共享的Mat */
    union ipc_mat{
      struct{
          unsigned long long addr;
          int total;
          int type;
          size_t step[2];
          int plane_size[4];
          int plane_step[4];
          int pix_fmt;
          int height;
          int width;
          int color_space;
          int color_range;
          int dev_id;
          int isYuvMat;
      }message;
      unsigned char data[128];
  }signal;
  memset(signal.data, 0, sizeof(signal));

  if (isSender){  // 后面是send的代码
      int fd = open("./ipc_sample", O_WRONLY);
      signal.message.addr = image.u->addr;
      signal.message.height = image.rows;
      signal.message.width = image.cols;
      signal.message.isYuvMat = image.avOK() ? 1 : 0;
      if (signal.message.isYuvMat){  // 处理yuvMat
                              //avAddr(4~6)对应设备内存
          signal.message.plane_size[0] = image.avAddr(5) - image.avAddr(4);
          signal.message.plane_step[0] = image.avStep(4);

          signal.message.pix_fmt = image.avFormat();
          if (signal.message.pix_fmt == AV_PIX_FMT_YUV420P){
              signal.message.plane_size[2] =
              signal.message.plane_size[1] = image.avAddr(6) - image.avAddr(5);
              signal.message.plane_step[1] = image.avStep(5);
              signal.message.plane_step[2] = image.avStep(6);
          } else if (signal.message.pix_fmt == AV_PIX_FMT_NV12){
              signal.message.plane_size[1] = signal.message.plane_size[0] / 2;
              signal.message.plane_step[1] = image.avStep(5);
          }   // 此处仅供展示，更多的色彩格式可以继续扩展

          signal.message.color_space = image.u->frame->colorspace;
          signal.message.color_range = image.u->frame->color_range;

          signal.message.dev_id = image.card;
      } else { // 处理bgrMat
          signal.message.total = image.total();
          signal.message.type = image.type();
          signal.message.step[0] = image.step[0];
          signal.message.step[1] = image.step[1];
      }

      write(fd, signal.data, 128);

      while(1) sleep(1); //此处while(1)仅供举例，要注意实际应用中后面还需要close(fd)
  } else if (!isSender){
      if ((mkfifo("./ipc_example", 0600) == -1) && errno != EEXIST){  // ipc共享仅供举例
          printf("mkfifo failed\n");
          perror("reason");
      }

      int fd = open("./ipc", O_RDONLY);
      Mat f_mat;  // 要重构的共享Mat
      int cnt = 0;

      while (cnt < 128){
          cnt += read(fd, signal.data+cnt, 128-cnt);
      }

      if(signal.message.isYuvMat) { // yuvMat
          AVFrame *f = cv::av::create(signal.message.height,
                                      signal.message.width,
                                      signal.message.pix_fmt,
                                      NULL,
                                      signal.message.addr,
                       /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                                      0,
                                      signal.message.plane_step,
                                      signal.message.plane_size,
                                      signal.message.color_space,
                                      signal.message.color_range,
                                      signal.message.dev_id);
          f_mat.create(f, signal.message.dev_id);
      } else {
          f_mat.create(signal.message.height,
                       signal.message.width,
                       signal.message.total,
                       signal.message.type,
                       signal.message.step,
                       NULL,
                       signal.message.addr,
                      /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                       0,
                       signal.message.dev_id);
          bmcv::downloadMat(f_mat);
                      /* 注意这里需要将设备内存的数据及时同步到系统内存中。因为yuvMat使
                        用中约定设备内存数据永远是最新的，bgrMat使用中约定系统内存数据永远
                        是最新的，这是我们opencv中遵循的设计原则 */
      }
      close(fd);
  }

 /* 以上代码仅供参考，请使用者根据自己实际需要修改定制 */
```

# 调用bm_opencv imread/imwrite 编译报错

```cpp
/usr/bin/ld: /tmp/ccozaFei.o: in function `.LEHE0':
test_opencv.cpp:(.text+0x50): undefined reference to `cv::imread(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, int, int)'
/usr/bin/ld: /tmp/ccozaFei.o: in function `.LEHE3':
test_opencv.cpp:(.text+0xf0): undefined reference to `cv::imwrite(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, cv::_InputArray const&, std::vector<int, std::allocator<int> > const&)'
collect2: 错误：ld 返回 1
```

在排查了引用so路径等问题之后，可以排查 libstdc++  版本
可能是使用的sdk和编译环境的libstdc++ 版本不匹配导致的。

解决办法是：
设置abi0、abi1
g++ -D_GLIBCXX_USE_CXX11_ABI=0 ......  或 g++ -D_GLIBCXX_USE_CXX11_ABI=1 ......

# 视频编码

## 常见问题

### bm_ffmpeg问题

### bm_opencv问题

#### VideoWriter.write性能问题，有些客户反应，存文件慢。

解析：就目前来看看采用YUV采集，然后编码10-20ms之间写入一帧数据属于正常现象。

# 图片编解码

## 常见问题

### 是否支持avi, f4v, mov, 3gp, mp4, ts, asf, flv, mkv封装格式的H264/H265视频解析？

答：我们使用ffmpeg对这些封装格式进行支持，ffmpeg支持的我们也支持。经查，这些封装格式ffmpeg都是支持的。但是封装格式对于H265/264的支持，取决于该封装格式的标准定义，比如flv标准中对h265就没有支持，目前国内的都是自己扩展的。

### 是否支持png, jpg, bmp, jpeg等图像格式

答：Jpg/jpeg格式除了有jpeg2000外，自身标准还有很多档次，我们采用软硬结合的方式对其进行支持。对jpeg baseline的除了极少部分外，都用硬件加速支持，其他的jpeg/jpg/bmp/png采用软件加速的方式进行支持。主要的接口有opencv/ffmpeg库。

## bm_ffmpeg问题

### 从内存读取图片，用AVIOContext *avio =avio_alloc_context()，以及avformat_open_input()来初始化，发现初始化时间有290ms；但是如果从本地读取图片，只有3ms。为啥初始化时间要这么长？怎样减少初始化时间？

答：

```
ret = avformat_open_input(&fmt_ctx, NULL, NULL, NULL);
```

这里是最简单的调用。因此，avformat内部会会读取数据，并遍历所有的数据，来确认avio中的数据格式。

若是避免在这个函数中读取数据、避免做这种匹配工作。在已经知道需要使用的demuxer的前提下，譬如，已知jpeg的demuxer是mjpeg，可将代码改成下面的试试。

```
AVInputFormat* input_format = av_find_input_format("mjpeg");

ret = avformat_open_input(&fmt_ctx, NULL, input_format, NULL);
```

### 如何查看FFMPEG中支持的分离器的名称?

答：

```
root@linaro-developer:~# ffmpeg -demuxers | grep jpeg
D jpeg_pipe piped jpeg sequence
D jpegls_pipe piped jpegls sequence
D mjpeg raw MJPEG video
D mjpeg_2000 raw MJPEG 2000 video
D mpjpeg MIME multipart JPEG
D smjpeg Loki SDL MJPEG
```

### 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm解码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -decoders | grep _bm
V..... avs_bm bm AVS decoder wrapper (codec avs)
V..... cavs_bm bm CAVS decoder wrapper (codec cavs)
V..... flv1_bm bm FLV1 decoder wrapper (codec flv1)
V..... h263_bm bm H.263 decoder wrapper (codec h263)
V..... h264_bm bm H.264 decoder wrapper (codec h264)
V..... hevc_bm bm HEVC decoder wrapper (codec hevc)
V..... jpeg_bm BM JPEG DECODER (codec mjpeg)
V..... mpeg1_bm bm MPEG1 decoder wrapper (codec mpeg1video)
V..... mpeg2_bm bm MPEG2 decoder wrapper (codec mpeg2video)
V..... mpeg4_bm bm MPEG4 decoder wrapper (codec mpeg4)
V..... mpeg4v3_bm bm MPEG4V3 decoder wrapper (codec msmpeg4v3)
V..... vc1_bm bm VC1 decoder wrapper (codec vc1)
V..... vp3_bm bm VP3 decoder wrapper (codec vp3)
V..... vp8_bm bm VP8 decoder wrapper (codec vp8)
V..... wmv1_bm bm WMV1 decoder wrapper (codec wmv1)
V..... wmv2_bm bm WMV2 decoder wrapper (codec wmv2)
V..... wmv3_bm bm WMV3 decoder wrapper (codec wmv3)
```

### 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h decoder=jpeg_bm
Decoder jpeg_bm [BM JPEG DECODER]:
General capabilities: avoidprobe
Threading capabilities: none
jpeg_bm_decoder AVOptions:
-bs_buffer_size <int> .D.V..... the bitstream buffer size (Kbytes) for bm jpeg decoder (from 0 to INT_MAX) (default 5120)
-chroma_interleave <flags> .D.V..... chroma interleave of output frame for bm jpeg decoder (default 0)
-num_extra_framebuffers <int> .D.V..... the number of extra frame buffer for jpeg decoder (0 for still jpeg, at least 2 for motion jpeg) (from 0 to INT_MAX) (default 0)
```

### 如何在FFMPEG中查看编码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h encoder=jpeg_bm
Encoder jpeg_bm [BM JPEG ENCODER]:
```

# 调用API实现jpeg编码的应用示例

## 答：

```c
AVDictionary* dict = NULL;
av_dict_set_int(&dict, "is_dma_buffer", 1, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

# 调用FFMPEG的API实现静态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

## 答：

```c
AVDictionary* dict = NULL;

/* bm_jpeg 解码器的输出是 chroma-interleaved模式,例如, NV12 */
av_dict_set_int(&dict, "chroma_interleave", 1, 0);

/* The bitstream buffer 为 3100KB(小于 1920x1080x3) */
/* 假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 0, 0);

ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

# 调用FFMPEG的API实现动态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

## 答：

```c
AVDictionary* dict = NULL;

/* bm_jpeg 解码器输出的是 chroma-separated 模式, 例如, YUVJ420 */
av_dict_set_int(&dict, "chroma_interleave", 0, 0);

/* The bitstream buffer 为 3100KB */
/* 假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 2, 0);

ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

# [问题分析]当用ffmpeg jpeg_bm解码超大JPEG图片的时候，有时候会报"ERROR:DMA buffer size(5242880) is less than input data size(xxxxxxx)"，如何解决？

在用FFMPEG的jpeg_bm硬件解码器解码JPEG图片的时候，默认的输入buffer是5120K。在拿到JPEG文件前提前分配好输入缓存，在MJPG文件解码时可以避免频繁地创建和销毁内存。当出现默认输入buffer大小比输入jpeg文件小的时候，可以通过下面的命令来调大输入缓存。

```c
av_dict_set_int(&opts, "bs_buffer_size", 8192, 0);   //注意： bs_buffer_size是以Kbyte为单位的
```

# bm_opencv问题

## 4K图片的问题

### 答：

有些客户需要的图片较大如8K等，由于VPSS只支持4K大小的图片，所以通过opencv读取图片后，会自动保持比例缩放到一个4K以内的尺寸。

如果客户需要传递原始图片的坐标位置给远端，可以有以下两种做法：

1. imread中设置flag = IMREAD_UNCHANGED_SCALE，此时图片不会真正解码，会在mat.rows/cols中返回图片的原始宽高，然后可根据缩放比例计算得到原图的坐标

2. 传递相对坐标给远端，即坐标x/缩放后的宽， 坐标y/缩放后的高传递到远端。这步相对坐标计算也可以在远端完成，然后可以根据远端知道的原始图像宽高计算得到正确的原图坐标

## Opencv imread读取图片性能问题

### 原因分析：

如果碰到图片小于16x16大小的图片，或者progressive 格式的jpeg，芯片不能实现加速，结果走了CPU的路径，导致客户发现图片解码并没有加速。

## 若是采用libyuv处理JPEG方面的输出或者输入，需要注意什么事项？

### 答：

若是处理jpeg方面的输出或者输入，需要使用J400，J420，J422，J444等字样的函数，不然输出结果会有色差。

原因是JPEG的格式转换矩阵跟视频的不一样。

## Bm_opencv的imread jpeg解码结果和原生opencv的imread jpeg结果不同，有误差

### 答：

是的。原生opencv使用libjpeg-turbo,而bm_opencv采用了bm168x芯片中的jpeg硬件加速单元进行解码。

误差主要来自解码输出YUV转换到BGR的过程中。1）YUV需要上采样到YUV444才能进行BGR转换。这个upsample的做法没有标准强制统一，jpeg-turbo提供了默认Fancy upsample，也提供了快速复制上采样的算法，原生opencv在cvtColor函数中采用了快速复制上采样算法，而在imread和imdecode中沿用了libjpeg-turbo默认的fancy upsample；而BM168x硬件加速单元采用快速复制的算法。2）YUV444到BGR的转换是浮点运算，浮点系数精度的不同会有+/-1的误差。其中1）是误差的主要来源。

这个误差并不是错误，而是双方采用了不同的upsample算法所导致的,即使libjpeg-turbo也同时提供了两种upsample算法。

如果用户非常关注这两者之间的差异，因为这两者之间的数值差异导致了AI模型精度的下降，我们建议有两种解决办法：

1. 设置环境变量 export USE_SOFT_JPGDEC=1，可以指定仍然使用libjpeg-turbo进行解码。但是这样会导致cpu的loading上升，不推荐

2. 可能过去模型太依赖开源opencv的解码结果了，可以用bm_opencv的解码结果重新训练模型，提高模型参数的适用范围。

可以使用libjpeg-turbo提供的djpeg工具对于测试工具集的数据进行重新处理，然后用处理后的数据对模型进行训练。djpeg的命令如下：

```bash
./djpeg -nosmooth -bmp -outfile xxxxx.bmp input.jpg
```

然后用重新生成bmp文件作为训练数据集，进行训练即可。

# 图像处理

## 常见问题

### bm_image_create、bm_image_alloc_dev_mem、bm_image_attach相关疑问

1. bm_image_create：用于创建bm_image结构体。
2. bm_image_alloc_dev_mem：申请设备内存，且内部会attach上bm_image。
3. bm_image_attach：用于将从opencv等处获取到的设备内存与bm_image_create申请到的bm_image进行绑定。

### bm_image_destroy、bm_image_detach相关疑问

1. bm_image_detach：用于将bm_image关联的设备内存进行解绑， 如果设备内存是内部自动申请的，才会释放这块设备内存；如果bm_image未绑定设备内存，则直接返回。
2. bm_image_destroy：该函数内部嵌套调用bm_image_detach。也就是说，调用该函数，如果bm_image绑定的设备内存是通过bm_image_alloc_dev_mem申请，就会释放；如果是通过bm_image_attach绑定的设备内存则不会被释放，此时需要注意该设备内存是否存在内存泄露，如果存在其他模块继续使用，则由相应模块进行释放。
3. 总的来说，设备内存由谁申请则由谁释放，如果是通过attach绑定的设备内存，则不能调用 bm_image_destroy 进行释放，如果确定attach绑定的设备内存不再使用，可通过bm_free_device等接口进行释放。

# bm_ffmpeg问题

## ffmpeg中做图像格式/大小变换导致视频播放时回退或者顺序不对的情况处理办法

### 答：

ffmpeg在编码的时候底层维护了一个avframe的队列作为编码器的输入源，编码期间应保证队列中数据有效，如果在解码后需要缩放或者像素格式转换时候需要注意送进编码器的avframe的数据有效和释放问题。

在例子ff_bmcv_transcode中从解码输出src-avframe转换成src-bm_image然后做像素格式转换或者缩放为dst-bm_image最后转回dst-avframe 去编码的过程中src-avframe、src-bm_image的设备内存是同一块，dst-avframe、dst-bm_image的设备内存是同一块。在得到dst-bm_image后即可释放src_avframe和src-bm_image的内存（二者释放其中一个即可释放设备内存），作为编码器的输入dts-bm_image在转换成dst-avframe之后其设备内存依然不能被释放（常见的异常情况是函数结束dts-bm_image的引用计数为0导致其被释放），如果dst-bm_image被释放了此时用dst-avframe去编码结果肯定会有问题。

解决方法是dst-bm_image的指针是malloc一块内存，然后将其传给av_buffer_create，这样就保证在函数结束的时候dst-bm_image引用计数不会减1，释放的方法是将malloc的dst-bm_image指针通过av_buffer_create传给释放的回调函数，当dst-avframe引用计数为0的时候会调用回调函数将malloc的指针和dst-bm_image的设备内存一起释放。详见例子ff_bmcv_transcode/ff_avframe_convert.cpp。

# bm_opencv问题

## Opencv读取图片后，cvMat转为bmimage, 之后，调用bmcv_image_vpp_convert做缩放或者颜色空间转换，得到的图片不一致

### 原因分析：

opencv内部的转换矩阵和bmcv_image_vpp_convert使用的转换矩阵不一致，需要调用bmcv_image_vpp_csc_matrix_covert, 并且指定CSC_YPbPr2RGB_BT601来进行转换才能保持一致。

## 关于什么时候调用uploadMat/downloadMat接口的问题

### 解析：

当创建了一个cv::Mat, 然后调用cv::bmcv里面的接口进行了一些处理后，设备内存的内容改变了，这时候需要downloadMat来同步一下设备内存和系统内存。当调用了cv::resize等opencv原生的接口后，系统内存的内容改变了，需要uploadMat，使设备内存和系统内存同步。

## 对于VPSS硬件不支持的YUV格式转换，采取什么样的软件方式最快？

### 答：

建议采用内部增强版本的libyuv。

相比较原始版本，增加了许多NEON64优化过的格式转换API函数。其中包含许多JPEG YCbCr相关的函数。

位置：/opt/sophon/libsophon-current/lib/

## OpenCV中的BGR格式，在libyuv中对应的那个格式？OpenCV中的RGB格式呢？

### 答：

- OpenCV中的BGR格式，在libyuv中对应的格式为RGB24
- OpenCV中的RGB格式，在libyuv中对应的格式为RAW。

## 现在opencv中默认是使用ION内存作为MAT的data空间，如何指定Mat对象基于system memory内存去创建使用？

### 答：

```cpp
using namespace cv;
Mat m; m.allocator = m.getDefaultAllocator();     // get system allocator
```

然后就可以正常调用各种mat函数了，如m.create() m.copyto()，后面就会按照指定的allocator来分配内存了。

```cpp
m.allocator = hal::getDefaultAllocator();  // get ion allocator
```

就又可以恢复使用ION内存分配器来分配内存。

## opencv转bm_image的时候，报错"Memory allocated by user, no device memory assigned. Not support BMCV!"

### 答：

这种错误通常发生在soc模式下，所转换的Mat只分配了系统内存，没有分配设备内存，而bm_image要求必须有设备内存，因此转换失败。

会产生这类问题的Mat通常是由外部分配的data内存attach过去的，即调用Mat(h, w, data) 或者Mat.create(h,w, data)来创建的，而data!=NULL,由外部分配。

对于这种情况，因为bm_image必须要求设备内存，因此解决方案有

1. 新生成个Mat，默认创建设备内存，然后用copyTo()拷贝一次，把数据移到设备内存上，再重新用这个Mat来转成bm_image
2. 直接创建bm_image，然后用bm_image_copy_host_to_device,将Mat.data中的数据拷贝到bm_image的设备内存中。

## 调用 bmcv_image_vpp_convert_padding 接口时，报缩放比例超过32倍的错："vpp not support: scaling ratio greater than 32"

bm1688的VPSS中硬件限制图片的缩放不能超过32倍（bm1688的VPSS中硬件限制图片的缩放不能超过128倍）。即应满足 dst_crop_w <= src_crop_w * 32，  src_crop_w <= dst_crop_w * 32， dst_crop_h <= src_crop_h * 32 , src_crop_h <= dst_crop_h * 32。

此问题原因可能是：

1. 输入 crop_rect 中的crop_w, crop_h 与 输出 padding_attr 中的dst_crop_w ，dst_crop_h 缩放比例超过了32倍。
2. crop_rect，padding_attr 值的数量应与 output_num的数量一致。

## 调用 bmcv_image_vpp_basic 接口时，csc_type_t, csc_type 和 csc_matrix_t* matrix该如何填？

bmcv中VPSS在做csc 色彩转换时，默认提供了4组601系数和4组709系数， 如csc_type_t所示。

1. csc_type可以填为CSC_MAX_ENUM， matrix填NULL，会默认配置 601 YCbCr与RGB互转系数。
2. csc_type可以填csc_type_t中参数，如YCbCr2RGB_BT709，matrix填NULL，会按照所选类型配置对应系数。
3. csc_type可以填CSC_USER_DEFINED_MATRIX，matrix填自定义系数。会按照自定义系数配置。

csc_matrix_t 中系数参考如下公式：

Y = csc_coe00 * R + csc_coe01 * G + csc_coe02 * B + csc_add0;
U = csc_coe10 * R + csc_coe11 * G + csc_coe12 * B + csc_add1;
V = csc_coe20 * R + csc_coe21 * G + csc_coe22 * B + csc_add2;

由于bm1688 VPSS精度为FP32，整数处理。

csc_coe 与 csc_add的计算方法为: csc_coe = round（浮点数 * 1024）后按整数取补码。

csc_coe取低13bit，即 csc_coe = csc_coe & 0x1fff，csc_add取低21bit，即 csc_add = csc_add & 0x1fffff。

举例如下：

floating-point coe matrix               =>          fixed-point coe matrix
0.1826	0.6142	0.0620	16.0000         =>          0x00bb    0x0275   0x003f   0x004000

## [问题分析]不同线程对同一个bm_imag调用 bm_image_destroy 时，程序崩溃

bm_image_destroy(bm_image image) 接口设计时，采用了结构体做形参，内部释放了image.image_private指向的内存，但是对指针image.image_private的修改无法传到函数外，导致第二次调用时出现了野指针问题。

为了使客户代码对于sdk的兼容性达到最好，目前不对接口做修改。
建议使用bm_image_destroy（image）后将 image.image_private = NULL，避免多线程时引发野指针问题。

# 在bmcv::toBMI之前是否需要调用bm_create_image，如果调用，在最后使用bm_image_destroy会不会引起内存泄露？

1. bmcv::toBMI内部嵌套调用bm_image_create，无需再次调用bm_create_image。
2. 如果在bmcv::toBMI前调用了bm_create_image，会导致内存泄露。
3. 调用bmcv::toBMI后，除了需要调用bm_image_destroy，还需要image.image_private = NULL。

## 其他

### 常见问题

#### 查看物理内存方式

SOC模式命令：

```
sudo su
cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
```

说明：

```
root@sophon:/home/linaro# cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
Summary:
[1] vpp heap size:1342177280 bytes, used:85245952 bytes
usage rate:7%, memory usage peak 326098944 bytes

Details:
         heap_id   alloc_buf_size         phy_addr         kmap_cnt      buffer name
               1            73728        15fa18000                1 VCODEC_2_DEC_FBCY_TBL
               1          3133440        15d500000                1      static_pool
               1            73728        15fa2a000                1 VCODEC_2_DEC_FBCY_TBL

vpu只能使用该heap，可以看到总的物理内存和已申请物理内存大小

Details显示已被分配的物理内存情况
heap_id: heapid
alloc_buf_size: 物理内存大小，单位是字节
phy_addr: 物理内存的地址，16进制表示
kmap_cnt: 引用次数，也可以理解过做过map的次数
buffer name: 可以判断物理内存是哪里分配的或者被用在哪里
```

# SOPHGO多媒体框架介绍

## 简介

本文档所述多媒体框架的描述对象为算能的算丰BM1688产品系列，目前该产品系列仅包括BM1688。其中1）本文中所有关于视频硬件编码的内容均只针对BM1688而言；2）本文中提到的Opencv中的bmcv名字空间下的函数，仅针对BM1688版本产品而言。

本文档所述多媒体框架的覆盖范围包括BM1688产品系列中的视频解码VPU模块、视频编码VPU模块、图像编码JPU模块、图像解码JPU模块、图像处理模块VPSS。这些模块的功能封装到FFMPEG和OPENCV开源框架中，客户可以根据自己的开发习惯，选择FFMPEG API或者OPENCV API。其中图像处理模块，我们还单独提供了算能自有的BMCV API底层接口，这部分接口有专门的文档介绍，可以参考《BMCV User Guide》，本文档不再详细介绍，仅介绍这三套API之间的层级关系及如何互相转换。

OPENCV，FFMPEG和BMCV这三套API在功能上是子集的关系，但有少部分不能全部包含，下面的括号中进行了特别标注。

1. BMCV API包含了所有能用硬件加速的图像处理加速接口（这里图像处理硬件加速，包括硬件图像处理VPSS模块加速，以及借用其他硬件模块实现的图像处理功能）
2. FFMPEG API包含了所有硬件加速的视频/图像编解码接口，所有软件支持的视频/图像编解码接口（即所有FFMPEG开源支持的格式），通过bm_scale filter支持的部分硬件加速的图像处理接口（这部分图像处理接口，仅包括用硬件图像处理VPSS模块加速的缩放、crop、padding、色彩转换功能）
3. OPENCV API包含了所有FFMPEG支持的硬件及软件视频编解码接口（视频底层通过FFMPEG支持，这部分功能完全覆盖），硬件加速的JPEG编解码接口，软件支持的其他所有图像编解码接口（即所有OPENCV开源支持的图像格式），部分硬件加速的图像处理接口（指用图像处理VPSS模块加速的缩放、crop、padding、色彩转换功能），所有软件支持的OPENCV图像处理功能。

这三个框架中，BMCV 专注于图像处理功能，且能用BM1688硬件加速的部分；FFMPEG框架强于图像和视频的编解码，几乎所有格式都可以支持，只是是否能用硬件加速的区别；OPENCV框架强于图像处理，各种图像处理算法最初都先集成到OPENCV框架中，而视频编解码通过底层调用FFMPEG来实现。

因为BMCV仅提供了图像处理接口，因此FFMPEG或者OPENCV框架中，客户一般会选择其中一个作为主框架进行开发。这两个框架，从功能抽象上来说，OPENCV的接口要更加简洁，一个接口就可以实现一次视频编解码操作；从性能上说，这两个的性能是完全一致的，几乎没有差别，在视频编解码上，OPENCV只是对 FFMPEG接口的一层封装；从灵活性上说，FFMPEG的接口更加分离，可插入的操作粒度更细。最重要的，客户还是要根据自己对于某个框架的熟悉程度来做选择，只有深入了解，才能把框架用好。

在很多应用场景下，需要用到某个框架下的特殊功能，因此在第4节中给出了三个框架之间灵活转换的方案。这种转换是不需要发生大量数据拷贝的，对性能几乎没有损失。

## BM1688硬件加速功能

本节给出了多媒体框架中硬件加速模块能支持的功能。其中硬件加速模块包括视频解码VPU模块，视频编码VPU模块，图像编解码JPU模块，图像处理VPSS模块。

需要特别注意，这里只列出能够用硬件加速的能力，以及典型场景下的性能估计值。更详细的性能指标参考BM1688产品规格书。

### 视频编解码

BM1688产品支持H264（AVC），HEVC视频格式的硬件解码加速，最高支持到4K视频的实时解码。支持H264(AVC), HEVC视频格式的硬件编码，最高支持到HD(1080p)视频的实时编码。

视频解码的速度与输入视频码流的格式有很大关系，不同复杂度的码流的解码速度有比较大的波动，比如码率、GOP结构，分辨率等，都会影响到具体的测试结果。一般来说，针对视频监控应用场景，BM1688产品单芯片可以支持到16路1080p30高清实时解码。

视频编码的速度与编码的配置参数有很大关系，不同的编码配置下，即使相同的视频内容，编码速度也不是完全相同的。一般来说，BM1688产品单芯片最高可以支持到10路1080p30高清实时编码。

### 图像编解码

BM1688产品支持JPEG baseline格式的硬件编/解码加速。注意，仅支持JPEG baseline档次的硬件编解码加速，对于其他图片格式，包括JPEG2000, BMP, PNG以及JPEG标准的progressive, lossless等档次均自动采用软解支持。在opencv框架中，这种兼容支持对于客户是透明的，客户应用开发时无需特别处理。

图像硬件编解码的处理速度和图像的分辨率、图像色彩空间（YUV420/422/444）有比较大的关系，一般而言，对于1920x1080分辨率的图片，色彩空间为YUV420的，单芯片1080p图像硬件编解码可以达到480fps左右。

### 图像处理

BM1688产品有专门的视频处理VPSS单元对图像进行硬件加速处理。支持的图像操作有色彩转换、图像缩放、图像切割crop、图像拼接stitch功能。最大支持到8k图像输入。对于VPSS不支持的一些常用复杂图像处理功能，如线性变换ax+b，直方图等, 我们在BMCV API接口中，利用其他硬件单元做了特殊的加速处理。

## 硬件内存分类

在后续的讨论中，内存同步问题是应用调试中经常会遇到的，比较隐蔽的问题。我们通常统一用设备内存和系统内存来称呼这两类内存间的同步。

SOC模式，是指用BM1688芯片中的处理器作为主控CPU，BM1688产品独立运行应用程序。典型的产品有SE9、SM9模组。在这类模式下，采用Linux系统下的ION内存对设备内存进行管理。在SOC模式下，设备内存指ION分配的物理内存，系统内存其实是cache，这里的命名只是为了和PCIE模式保持一致。从系统内存（cache）到设备内存，称为Upload上传（实质是cache flush）；从设备内存到系统内存（cache），称为Download下载（实质是cache invalidation）。在SOC模式下，设备内存和系统内存最终操作的其实是同一块物理内存，大部分时间，操作系统会自动对其进行同步，这也导致内存没有及时同步时的现象更加隐蔽和难以复现。

在OPENCV框架中，部分函数的形参中就提供了update的标志位，当标志位设置true的时候，函数内部会自动进行内存同步操作。这部分可以参考后续的第二章第3节的API介绍。用户也可以通过bmcv::downloadMat() 和 bmcv::uploadMat()两个函数，主动控制内存同步。同步的基本原则是：a) opencv原生函数中，yuv Mat格式下设备内存中的数据永远是最新的，RGB Mat格式下系统内存中的数据永远是最新的 b) 当opencv函数向BMCV API切换的时候，根据上一个原则，将最新数据同步到设备内存中；反之，从BMCV API向opencv函数切换的时候，在RGB Mat下将最新数据同步到系统内存中。c) 在不发生框架切换的时候，要尽量减少内存同步的操作。频繁的内存同步操作会明显降低性能。

在常规FFMPEG框架中，有两类称之为软（常规）和硬（hwaccel）的codec API和filter API。这两套API的框架都可以支持BM1688的硬件视频编解码和硬件图像filter，从这个角度上说，所谓的软解码和硬解码在底层性能上是完全一样的，只是在使用习惯上的区别。软codec/filter API的使用方式和通常ffmpeg 内置codec完全一致，硬codec/filter API要用-hwaccel来指定使能bmcodec专用硬件设备。当在软codec API和filter API中，通过av_dict_set传入标志参数"is_dma_buffer"或者"zero_copy"，来控制内部codec或filter是否将设备内存数据同步到系统内存中，具体参数使用可以用ffmpeg -h来查看。当后续直接衔接硬件处理的时候，通常不需要将设备内存数据同步到系统内存中。

在hwaccel codec API和filter API中，内存默认只有设备内存，没有分配系统内存。如果需要内存同步，则要通过hwupload和hwdownload filter来完成。

综上所述，OPENCV和FFMPEG框架都对内存同步提供了支持，应用可以根据自己的使用习惯选择相应的框架，对数据同步进行精准控制。BMCV API则始终工作在设备内存上。

## 框架之间转换

在应用开发中，总会碰到一些情况下，某个框架无法完全满足设计需求。这时就需要在各种框架之间快速切换。BM1688多媒体框架对其提供了支持，可以满足这种需求，并且这种切换是不发生数据拷贝的，对于性能几乎没有影响。

### FFMPEG和OPENCV转换

FFMPEG和OPENCV之间的转换，主要是数据格式AVFrame和cv::Mat之间的格式转换。

当需要FFMPEG和OPENCV配合解决的时候，推荐使用常规非HWAccel API的通路，目前OPENCV内部采用是这种方式，验证比较完备。

FFMPEG AVFrame转到OPENCV Mat格式如下：

1. AVFrame * picture；
2. 中间经过ffmpeg API的一系列处理，比如avcodec_decode_video2 或者 avcodec_receive_frame，然后将得到的结果转成Mat
3. card_id 为进行ffmpeg硬件加速解码的设备序号，在常规codec API中，通过av_dict_set的sophon_idx指定，或者hwaccel API中，在hwaccel设备初始化的时候指定，soc模式下默认为0
4. cv::Mat ocv_frame(picture, card_id)；
5. 或可以通过分步方式进行格式转换
6. cv::Mat ocv_frame;
7. ocv_frame.create(picture, card_id);
8. 然后可以用ocv_frame进行opencv的操作，此时ocv_frame格式为BM1688扩展的yuv mat类型，如果后续想转成opencv标准的bgr mat格式，可以按下列操作。
9. 注意：这里就有内存同步的操作，如果没有设置，ffmpeg默认是在设备内存中的，如果update=false, 那么转成bgr的数据也一直在设备内存中，系统内存中为无效数据，如果update=true，则设备内存同步到系统内存中。如果后续还是硬件加速处理的话，可以update=false, 这样可以提高效率，当需要用到系统内存数据的时候，显式调用bmcv::downloadMat()来同步即可。
10. cv::Mat bgr_mat;
11. cv::bmcv::toMAT(ocv_frame, bgr_mat, update);
12. 最后AVFrame *picture会被Mat ocv_frame释放，因此不需要对picture进行av_frame_free()操作。如果希望外部调用av_frame_free来释放picture，则可以加上card_id = card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED,0,0), 该标准表明AVFrame的创建和释放由外部管理
13. ocv_frame.release();
14. picture = nullptr;

OPENCV Mat转成FFMPEG AVFrame的情况比较少见，因为几乎所有需要的FFMPEG操作都在opencv中有对应的封装接口。比如：ffmpeg解码在opencv有videoCapture类，ffmpeg编码在opencv中有videoWriter类，ffmpeg的filter操作对应的图像处理在opencv中有bmcv名字空间下的接口以及丰富的原生图像处理函数。

一般来说，opencv Mat转成FFMPEG AVFrame，指的是yuv Mat。在这种情况下，可以按下进行转换：

1. 创建yuv Mat，如果yuv Mat已经存在，可以忽略此步.card_id为BM1688设备序号，soc模式下默认为0
2. AVFrame * f = cv::av::create(height, width, AV_PIX_FMT_YUV420P, NULL, 0, -1, NULL, NULL, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, card_id);
3. cv::Mat image(f, card_id);
4. do something in opencv
5. AVFrame * frame = image.u->frame;
6. call FFMPEG API
7. 注意：在ffmpeg调用完成前，必须保证Mat image没有被释放，否则AVFrame会和Mat image一起释放。如果需要将两个的声明周期分离开来，则上面的image声明要改成如下格式。
8. cv::Mat image(f, card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED, 0, 0));
9. 这样Mat就不会接管AVFrame的内存释放工作

### FFMPEG和BMCV API转换

FFMPEG经常需要和BMCV API搭配使用，因此FFMPEG和BMCV之间的转换是比较频繁的。为此我们专门给了一个例子ff_bmcv_transcode，该例子可以在SDK发布包里找到。

ff_bmcv_transcode例子演示了用ffmpeg解码，将解码结果转换到BMCV下进行处理，然后再转换回到ffmpeg进行编码的过程。FFMPEG和BMCV之间的互相转换可以参考ff_avframe_convert.cpp文件中的avframe_to_bm_image()和bm_image_to_avframe()函数。

### OPENCV和BMCV API转换

OPENCV和BMCV API之间的转换，专门在opencv扩展的bmcv名字空间下提供了专门的转换函数。

OPENCV Mat转换到BMCV bm_image格式：

1. cv::Mat m(height, width, CV_8UC3, card_id);
2. opencv 操作
3. bm_image bmcv_image;

# SOPHGO OpenCV使用指南

## OpenCV简介

BM1688系列芯片中的多媒体、BMCV模块可以加速对图片和视频的处理：

1) 多媒体模块：硬件加速JPEG编码解码和Video编解码操作。

2) BMCV模块：包含TPU、VPSS、IVE、GDC等硬件模块。对resize、color conversion、crop、split、linear transform、nms、sort、rgb2gray、mean、scale、int8tofloat32等操作实现硬件加速。

为了方便客户使用芯片上的硬件模块加速图片和视频的处理，提升应用OpenCV软件性能，算能修改了OpenCV库，在其内部调用硬件模块进行Image和Video相关的处理。

算能当前OpenCV的版本为4.1.0，除了以下几个算能自有的API以外，其它的所有API与OpenCV API都是一致的。

在SOC模式下，由于硬件限制，OpenCV库的Mat对象中，step值会被自动设置为64bytes对齐，不足64bytes的数据用0补齐。而在PCIE模式下，Mat的step不存在64bytes的对齐限制。例如，一张100*100的图片，每个像素的RGB由3个U8值表示，正常的step值为300，但是经过64bytes对齐，step值最终为320。如下图所示，Mat对象的data中，每一个step的数据是连续的320个bytes，其中前300个是真实数据，后面20个是自动填充的0值。

在SOC模式下，由于填充了多余的0值，Mat对象中存储数据的data变量不能直接传递给BMRuntime库的API做推理，否则会降低模型的准确率。请在最后一次BMCV做变换的时候，将stride设置为非对齐方式，多余的0会被自动清除掉。

## 数据结构扩展说明

OpenCV内置标准处理的色彩空间为BGR格式，但是很多情况下，对于视频、图片源，直接在YUV色彩空间上处理，可以节省带宽和避免不必要的YUV和RGB之间的互相转换。因此SOPHGO Opencv对于Mat类进行了扩展。

1) 在Mat.UMatData中，引入了AVFrame成员，扩展支持各种YUV格式。其中AVFrame的格式定义与FFMPEG中的定义兼容

2) 在Mat.UMatData中增加了fd，addr（soc模式下）的定义，分别表示对应的内存管理句柄和物理内存地址

3) 在Mat类中增加了fromhardware变量，标识当前的视频、图片解码是由硬件或是软件计算完成的，开发者在程序开发过程中无需考虑该变量的值。

## API扩展说明

### bool VideoCapture::get_resampler(int \*den, int \*num)

| 函数原型 | bool VideoCapture::get_resampler(int \*den, int \*num) |
|----------|--------------------------------------------------------|
| 功能 | 取视频的采样速率。如den=5, num=3表示每5帧中有2帧被丢弃 |
| 输入参数 | int \*den – 采样速率的分母<br>int \*num – 采样速率的分子 |
| 输出参数 | 无 |
| 返回值 | true – 执行成功  false - 执行失败 |
| 说明 | 此接口将废弃。推荐用double VideoCapture::get(CAP_PROP_OUTPUT_SRC)接口。 |

### bool VideoCapture::set_resampler(int den, int num)

| 函数原型 | bool VideoCapture::set_resampler(int den, int num) |
|----------|----------------------------------------------------|
| 功能 | 置视频的采样速率。如den=5, num=3，表示每5帧中有2帧被丢弃。 |
| 输入参数 | int den – 采样速率的分母<br>int num – 采样速率的分子 |
| 输出参数 | 无 |
| 返回值 | true – 执行成功  false - 执行失败 |
| 说明 | 此接口将废弃。推荐用bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)接口。 |

### double VideoCapture::get(CAP_PROP_TIMESTAMP)

| 函数原型 | double VideoCapture::get(CAP_PROP_TIMESTAMP) |
|----------|----------------------------------------------|
| 功能 | 提供当前图片的时间戳，时间基数取决于在流中给出的时间基数 |
| 输入参数 | CAP_PROP_TIMESTAMP – 特定的枚举类型指示获取时间戳,此类型由Sophgo定义 |
| 输出参数 | 无 |
| 返回值 | 在使用前先将返回值转成unsigned int64数据类型<br>0x8000000000000000L-No AV PTS value<br>other-AV PTS value |

### double VideoCapture::get(CAP_PROP_STATUS)

| 函数原型 | double VideoCapture::get(CAP_PROP_STATUS) |
|----------|-------------------------------------------|
| 功能 | 该函数提供了一个接口，用于检查视频抓取的内部运行状态 |
| 输入参数 | CAP_PROP_STATUS – 枚举类型，此类型由Sophgo定义 |
| 输出参数 | 无 |
| 返回值 | 在使用返回值前请将转换成int类型<br>0  视频抓取停止，暂停或者其他无法运行的状态<br>1  视频抓取正在进行<br>2  视频抓取结束 |

### bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)

| 函数原型 | double VideoCapture::get(CAP_PROP_OUTPUT_SRC, double resampler) |
|----------|-----------------------------------------------------------------|
| 功能 | 设置YUV视频的采样速率。如resampler为0.4，表示每5帧中保留2帧，有3帧被丢弃 |
| 输入参数 | CAP_PROP_OUTPUT_SRC–枚举类型，此类型由Sophgo定义<br>double resampler – 采样速率 |
| 输出参数 | 无 |
| 返回值 | true 执行成功<br>false执行失败 |

### double VideoCapture::get(CAP_PROP_OUTPUT_SRC)

| 函数原型 | double VideoCapture::get(CAP_PROP_OUTPUT_SRC) |
|----------|-----------------------------------------------|
| 功能 | 取视频的采样速率。 |
| 输入参数 | CAP_PROP_OUTPUT_SRC - 特定的枚举类型，指视频输出，此类型由SOPHGO定义 |
| 输出参数 | 无 |
| 返回值 | 采样率数值 |

### bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)

| 函数原型 | bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable) |
|----------|-----------------------------------------------------------|
| 功能 | 开或者关闭YUV格式的frame输出。BM1688系列下YUV格式为I420 |
| 输入参数 | CAP_PROP_OUTPUT_YUV - 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义;<br>double enable - 操作码，1表示打开，0表示关闭 |
| 输出参数 | 无 |
| 返回值 | true：执行成功 false：执行失败 |

### double VideoCapture::get(CAP_PROP_OUTPUT_YUV)

| 函数原型 | double VideoCapture::get(CAP_PROP_OUTPUT_YUV) |
|----------|-----------------------------------------------|
| 功能 | 取YUV视频frame输出的状态。 |
| 输入参数 | CAP_PROP_OUTPUT_YUV - 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义。 |
| 输出参数 | 无 |
| 返回值 | YUV视频frame输出的状态。1表示打开，0表示关闭。 |

### bm_status_t bmcv::toBMI(Mat &m, bm_image \*image, bool update = true)

| 函数原型 | bm_status_t bmcv::toBMI(Mat &m, bm_image \*image, bool date = true) |
|----------|---------------------------------------------------------------------|
| 功能 | OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不会发生copy操作。本接口仅支持1N模式 |
| 输入参数 | Mat& m – Mat对象，可以为扩展YUV格式或者标准OpenCV BGR格式;<br>bool update – 是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | bm_image \*image – 对应格式的BMCV bm_image数据对象 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换 |

### bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image \*image, bool update = true)

| 函数原型 | bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image \*image, bool update = true) |
|----------|--------------------------------------------------------------------------------------------------|
| 功能 | OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不发生copy操作。本接口针对BMCV的4N模式。要求所有Mat的输入图像格式一致,仅对BM1688有效 |
| 输入参数 | Mat &m - 4N中的第1幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m1 - 4N中的第2幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m2 - 4N中的第3幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m3 - 4N中的第4幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | bm_image \*image - 对应格式的BMCV bm_image数据对象，其中包含4个图像数据 |
| 返回值 | BM_SUCCESS(0)：执行成功  其他：执行失败 |
| 说明 | 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换 |

## 内存同步说明

这里update用来控制内存同步，是否需要内存同步取决于前面的opencv操作，如果前面的操作都是用硬件加速完成，设备内存中就是最新数据，就没必要进行内存同步，如果前面的操作调用了opencv函数，没有使用硬件加速（后续opencv章节6.2中提到了哪些函数采用了硬件加速），对于bgr mat格式就需要做内存同步。

也可以在调用下面函数之前，显式的调用cv::bmcv::uploadMat(m)来实现内存同步：

```cpp
cv::bmcv::toBMI(m, &bmcv_image, update);
```

使用bmcv_image就可以进行bmcv api调用，调用期间注意保证Mat m不能被释放，因为bmcv_image使用的是Mat m中分配的内存空间。handle可以通过bm_image_get_handle()获得。

释放：必须调用此函数，因为在toBMI中create了bm_image, 否则会有内存泄漏：

```cpp
bm_image_destroy(bmcv_image);
m.release();
```

## 格式转换说明

由BMCV bm_image格式转换到OPENCV Mat有两种方式，一种是会发生数据拷贝，这样bm_image和Mat之间相互独立，可以分别释放，但是有性能损失；一种是直接引用bm_image内存，性能没有任何损失。

下面接口将发生内存数据拷贝，转换成标准bgr mat格式：

```cpp
bm_image bmcv_image;
// 调用bmcv API给bmcv_image分配内存空间，并进行操作
Mat m_copy, m_nocopy;
cv::bmcv::toMAT(&bmcv_image, m_copy, update, csc_type);
```

update控制内存同步，也可以在调用完这个函数后用bmcv::downloadMat()来控制内存同步。csc_type是控制颜色转换系数矩阵，控制不同yuv色彩空间转换到bgr。

下面接口将直接引用bm_image内存 (nocopy标志位true), update仍然按照之前的描述，选择是否同步内存。在后续opencv操作中，必须保证bmcv_image没有释放，因为mat的内存直接引用自bm_image：

```cpp
cv::bmcv::toMAT(&bmcv_image, &m_nocopy, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, NULL, -1, update, true);
```

# bmcv::toMAT 函数

## bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update=true)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update = true) |
| 功能 | 输入的MAT对象，可以为各种YUV或BGR格式，转换成BGR packet格式的MAT对象输出 |
| 输入参数 | Mat &in - 输入的MAT对象，可以为各种YUV格式或者BGR格式;<br>bool update – 是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | Mat &m0 - 输出的MAT对象，转成标准OpenCV的BGR格式 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1到BGR packed格式转换。在YUV格式下，会自动根据AVFrame结构体中colorspace,color_range信息选择正确的色彩转换矩阵。 |

## bm_status_t toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr = NULL, int fd0 = -1, bool update = true, bool nocopy = true)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr=NULL, int fd0=-1, bool update=true, bool nocopy=true) |
| 功能 | 输入的bm_image对象，当nocopy为true时，直接复用设备内存转成Mat格式，当nocopy为false时，行为类似3.13toMAT接口，1N模式。 |
| 输入参数 | bm_image *image - 输入的bm_image对象，可以为各种YUV格式或者BGR格式;<br>Int color_space – 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义;<br>Int color_range – 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义;<br>Void* vaddr – 输出Mat的系统虚拟内存指针，如果已分配，输出Mat直接使用该内存作为Mat的系统内存。如果为NULL，则Mat内部自动分配;<br>Int fd0 – 输出Mat的物理内存句柄，如果为负，则使用bm_image内的设备内存句柄，否则使用fd0给定的句柄来mmap设备内存;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>bool nocopy – 如果是true，则直接引用bm_image的设备内存，如果为false，则转换成标准BGR Mat格式 |
| 输出参数 | Mat &m - 输出的MAT对象，当nocopy为true时，输出标准BGR格式或扩展的YUV格式的Mat；当nocopy为false时，转成标准OpenCV的BGR格式。 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 1.no copy方式只支持1N模式，4N模式因为内存排列方式，不能支持引用<br>2.在nocopy为false的情况下，会自动根据参数colorspace,color_range信息选择正确的色彩转换矩阵进行色彩转换。<br>3.如果系统内存vaddr来自于外部，那么外部需要来管理这个内存的释放，Mat释放的时候不会释放该内存 |

## bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update = true, csc_type_t csc = CSC_MAX_ENUM)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update=true, csc_type_t csc=CSC_MAX_ENUM) |
| 功能 | 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，1N模式 |
| 输入参数 | bm_image *image - 输入的bm_image对象，可以为各种YUV格式或者BGR格式;<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>csc_type_t csc – 色彩转换类型，仅当输入bm_image为YUV格式时需要csc转换，默认type为YCbCr2RGB_BT601 |
| 输出参数 | Mat &m0 - 输出的MAT对象，转成标准OpenCV的BGR格式 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

## bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update=true, csc_type_t csc=CSC_MAX_ENUM)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update=true, csc_type_t csc=CSC_MAX_ENUM) |
| 功能 | 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，4N模式，仅在BM1684下有效 |
| 输入参数 | bm_image *image - 输入的4N模式下的bm_image对象，可以为各种YUV格式或者BGR格式;<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>csc_type_t csc – 色彩转换类型，仅当输入bm_image为YUV格式时需要csc转换，默认type为YCbCr2RGB_BT601 |
| 输出参数 | Mat &m0 - 输出的第一个MAT对象，转成标准OpenCV的BGR格式;<br>Mat &m1 - 输出的第二个MAT对象，转成标准OpenCV的BGR格式;<br>Mat &m2 - 输出的第三个MAT对象，转成标准OpenCV的BGR格式;<br>Mat &m3 - 输出的第四个MAT对象，转成标准OpenCV的BGR格式 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

# bmcv::resize 函数

## bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation= BMCV_INTER_NEAREST)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation = BMCV_INTER_NEAREST) |
| 功能 | 输入的MAT对象，缩放到输出Mat给定的大小，输出格式为输出Mat指定的色彩空间，因为MAT支持扩展的YUV格式，因此本接口支持的色彩空间并不仅局限于BGR packed。 |
| 输入参数 | Mat &m - 输入的Mat对象，可以为标准BGR packed格式或者扩展YUV格式;<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>int interpolation – 缩放算法，可为NEAREST或者LINEAR算法 |
| 输出参数 | Mat &out - 输出的缩放后的Mat对象 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 支持Gray、YUV444P、YUV420P、BGR/RGB separate、BGR/RGB packed、ARGB packed格式缩放 |

# bmcv::convert 函数

## bm_status_t bmcv::convert(Mat &m, Mat &out, bool update=true)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::convert(Mat &m, Mat &out, bool update = true) |
| 功能 | 实现两个mat之间的色彩转换，它与toMat接口的区别在于toMat只能实现各种色彩格式到BGR packed的色彩转换，而本接口可以支持BGR packed或者YUV格式到BGR packed或YUV之间的转换。 |
| 输入参数 | Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | Mat &out - 输出的色彩转换后的Mat对象，可以为BGR packed或者YUV格式。 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

## bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update= true, csc_type_t csc=CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix = nullptr, bmcv_resize_algorithm algorithm= BMCV_INTER_LINEAR)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update = true, csc_type_t csc=CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix=nullptr, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR) |
| 功能 | 接口采用内置的VPSS硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，给定的多个缩放size，将输入的Mat对象，输出到多个Mat对象中，输出为OpenCV标准的BGR pack格式或扩展YUV格式 |
| 输入参数 | Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式;<br>std::vector<Rect> &vrt - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同;<br>std::vector<Size> &vsz - 多个resize大小，与vrt的矩形框一一对应;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>csc_type_t csc – 色彩转换矩阵，可以根据颜色空间指定合适的色彩转换矩阵;<br>csc_matrix_t *matrix – 当色彩转换矩阵不在列表中时，可以给出外置的用户自定义的转换矩阵;<br>bmcv_resize_algorithm algorithm – 缩放算法，可以为Nearest或者Linear算法 |
| 输出参数 | std::vector<Mat> &out - 输出的缩放、crop以及色彩转换后的标准BGR pack格式或YUV格式的Mat对象。 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 接口可以将resize,crop,csc三种操作在一步之内完成，效率最高。在可能的情况下，要尽可能的使用该接口提高效率 |

## bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update= true)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update= true) |
| 功能 | 接口采用内置的VPSS硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，按照多个bm_image中指定的size，将输入的Mat对象，输出到多个bm_image对象中，输出格式由bm_image初始化值决定。注意，bm_image必须由调用者初始化好，并且个数和vrt一一对应。 |
| 输入参数 | Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式;<br>std::vector<Rect> &vrt - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | bm_image *out - 输出的缩放、crop以及色彩转换后的bm_image对象，输出色彩格式由bm_image初始化值决定。同时该bmimage参数包含的初始化的size、色彩信息也作为输入信息，用于处理。 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

# bmcv::warpAffine 函数

## bm_status_t bmcv::warpAffine(InputArray src, OutputArray dst, InputArray M0, Size dsize, int flags = 1, int borderMode = 0, bool update = true)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::warpAffine(InputArray src, OutputArray dst, InputArray M0, Size dsize, int flags = 1, int borderMode = 0, bool update = true) |
| 功能 | 接口采用内置的TPU硬件加速单元, 将输入的Mat对象, 按给定的坐标变换矩阵进行旋转, 平移, 缩放等实现图像的仿射变换, 结果输出到Mat对象中。 |
| 输入参数 | InputArray src - 仅支持输入为Mat的对象, 可以为扩展的YUV格式或者标准BGR packed格式;<br>InputArray M0 - 仅支持输入为Mat的对象, 坐标变换矩阵是一个6点的2x3矩阵;<br>Size dsize - 输出图的大小<br>int flags - 插值方法, 当flag = 0时, 使用nearest, 当flag = 1时, 使用bilinear;<br>int borderMode - 像素外推方法, 当borderMode = 0时, 边缘像素设置为0, 当borderMode = 1时, 复制边缘像素<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 输出参数 | OutputArray dst - 输出的仿射变换后的Mat对象, 输出色彩格式为BGR_PACKED。 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

# bmcv::rectangle 函数

## bm_status_t bmcv::rectangle(InputOutputArray _img, Point pt1, Point pt2, const Scalar& color, int thickness, bool update)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::rectangle(InputOutputArray _img, Point pt1, Point pt2, const Scalar& color, int thickness, bool update) |
| 功能 | 接口采用内置的VPP硬件加速单元, 在输入的Mat对象上按pt1和pt2定义的矩形大小和位置画矩形框, 该图像会被直接修改。 |
| 输入参数 | InputOutputArray _img - 绘制矩形的图像, 输入只支持Mat对象, 可以为扩展的YUV格式或者标准BGR packed格式;<br>Point pt1 - 矩形左上角的坐标, 以(x, y)表示, 该点定义了矩形的一个顶点;<br>Point pt2 - 矩形右下的坐标, 以(x, y)表示, 与pt1一起定义了矩形的大小和位置;<br>const Scalar& color - 矩形的颜色, 由BGR值构成, 这里的Scalar类只接受1到3个参数, 对应图像的通道数(3);<br>int thickness(可选) - 矩形边框的厚度, 单位为像素, 默认值为1, 若设置为负数(通常为-1), 则绘制实心矩阵, 填充矩阵内部;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

## bm_status_t bmcv::rectangle(InputOutputArray img, Rect rec, const Scalar& color, int thickness, bool update)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::rectangle(InputOutputArray img, Rect rec, const Scalar& color, int thickness, bool update) |
| 功能 | 接口采用内置的VPP硬件加速单元, 在输入的Mat对象上按rec定义的矩形大小和位置画矩形框, 该图像会被直接修改。 |
| 输入参数 | InputOutputArray _img - 绘制矩形的图像, 输入只支持Mat对象, 可以为扩展的YUV格式或者标准BGR packed格式;<br>Rect rec - 指定矩形左上角的坐标x, y和矩形的宽高, 指定矩形规格;<br>const Scalar& color - 矩形的颜色, 由BGR值构成, 这里的Scalar类只接受1到3个参数, 对应图像的通道数(3);<br>int thickness(可选) - 矩形边框的厚度, 单位为像素, 默认值为1, 若设置为负数(通常为-1), 则绘制实心矩阵, 填充矩阵内部;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

## bm_status_t bmcv::rectangle(Mat &m, std::vector<Rect> &vrt, const Scalar& color, int thickness, bool update)

| 属性 | 说明 |
|------|------|
| 函数原型 | bm_status_t bmcv::rectangle(Mat &m, std::vector<Rect> &vrt, const Scalar& color, int thickness, bool update) |
| 功能 | 接口采用内置的VPP硬件加速单元, 在输入的Mat对象上按vrt定义的矩形大小和位置画矩形框, 该图像会被直接修改。 |
| 输入参数 | Mat &m - 绘制矩形的Mat对象, 可以为扩展的YUV格式或者标准BGR packed格式;<br>std::vector<Rect> &vrt - 多个rect框;<br>const Scalar& color - 矩形的颜色, 由BGR值构成, 这里的Scalar类只接受1到3个参数, 对应图像的通道数(3);<br>int thickness(可选) - 矩形边框的厚度, 单位为像素, 默认值为1, 若设置为负数(通常为-1), 则绘制实心矩阵, 填充矩阵内部;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |

# bmcv 函数文档

## bitwise_and

### 函数原型
```cpp
bm_status_t bmcv::bitwise_and(InputArray a, InputArray b, OutputArray c, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，对输入的两个大小相同的Mat对象对应像素值进行按位与操作。

### 输入参数
- **InputArray a** - 第一张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **InputArray b** - 第二张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray c** - Mat a 和 Mat b 按位与的输出对象，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## bitwise_or

### 函数原型
```cpp
bm_status_t bmcv::bitwise_or(InputArray a, InputArray b, OutputArray c, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，对输入的两个大小相同的Mat对象对应像素值进行按位或操作。

### 输入参数
- **InputArray a** - 第一张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **InputArray b** - 第二张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray c** - Mat a 和 Mat b 按位或的输出对象，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## bitwise_xor

### 函数原型
```cpp
bm_status_t bmcv::bitwise_xor(InputArray a, InputArray b, OutputArray c, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，对输入的两个大小相同的Mat对象对应像素值进行按位与操作。

### 输入参数
- **InputArray a** - 第一张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **InputArray b** - 第二张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray c** - Mat a 和 Mat b 按位异或的输出对象，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## absdiff

### 函数原型
```cpp
bm_status_t bmcv::absdiff(InputArray src1, InputArray src2, OutputArray dst, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，对输入的两个大小相同的Mat对象对应像素值相减并取绝对值。

### 输入参数
- **InputArray src1** - 第一张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **InputArray src2** - 第二张图像的Mat对象（只支持Mat输入），可以为扩展的YUV格式或者标准BGR packed格式
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray dst** - Mat src1 和 Mat src2 按位与的输出对象，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## rotate

### 函数原型
```cpp
bm_status_t bmcv::rotate(InputArray _src, OutputArray _dst, int rotateMode, bool update)
```

### 功能
接口采用内置的VPP和TPU硬件加速单元，实现图像顺时针旋转90度、180度和270度。

### 输入参数
- **InputArray _src** - 进行旋转的图像，输入只支持Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- **int rotateMode** - rotateMode = 0, 1, 2 分别对应顺时针旋转90度、180度、270度
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray _dst** - 旋转后的图像，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## threshold

### 函数原型
```cpp
bm_status_t bmcv::threshold(InputArray _src, OutputArray _dst, unsigned char thresh, unsigned char max_value, int type, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，实现图像阈值化处理。

### 输入参数
- **InputArray _src** - 进行阈值化处理的图像，输入只支持Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- **unsigned char thresh** - 像素阈值，取值范围为0-255
- **unsigned char max_value** - 阈值化操作后的像素最大值，取值范围为0-255
- **int type** - 阈值化类型，取值范围为0-4，分别对应BM_THRESH_BINARY = 0、BM_THRESH_BINARY_INV、BM_THRESH_TRUNC、BM_THRESH_TOZERO、BM_THRESH_TOZERO_INV
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray _dst** - 阈值化后的图像，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## convertTo（多通道版本）

### 函数原型
```cpp
bm_status_t bmcv::convertTo(InputArray _srcs, OutputArray _dsts, int _type, std::array<float, 3> alpha, std::array<float, 3> beta, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，实现一个或多个图像像素线性变化，具体数据关系为：y=kx+b。

### 输入参数
- **InputArray _src** - 进行像素线性变换的图像，输入支持Mat或std::vector<Mat>对象，可以为扩展的YUV格式或者标准BGR packed格式
- **int _type** - 需要输出的矩阵类型，如果是负值（常用-1），输出矩阵和输入矩阵类型相同
- **std::array<float, 3> alpha** - 比例因子，对应图像的3通道
- **std::array<float, 3> beta** - 将输入数组元素按比例缩放后添加的值，对应图像的3通道
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray _dst** - 像素线性变化后的图像，支持Mat或std::vector<Mat>对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## convertTo（单通道版本）

### 函数原型
```cpp
bm_status_t bmcv::convertTo(InputArray _srcs, OutputArray _dsts, int _type, float alpha, float beta, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，实现一个图像像素线性变化，具体数据关系为：y=kx+b。

### 输入参数
- **InputArray _src** - 进行像素线性变换的图像，输入只支持Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- **int _type** - 需要输出的矩阵类型，如果是负值（常用-1），输出矩阵和输入矩阵类型相同
- **float alpha** - 比例因子，图像所有通道的比例因子相同
- **float beta** - 将输入数组元素按比例缩放后添加的值，图像所有通道的值相同
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **OutputArray _dst** - 像素线性变化后的图像，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## mosaic

### 函数原型
```cpp
bm_status_t bmcv::mosaic(Mat &m, std::vector<Rect> &vrt, int is_expand, bool update)
```

### 功能
接口采用内置的VPP硬件加速单元，按给定的一个或多个rect框，在输入的Mat对象上打一个或多个马赛克，输出到原Mat对象上。

### 输入参数
- **Mat &m** - 输入的Mat对象，输出为加马赛克后的原始Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- **std::vector<Rect> &vrt** - 多个rect框，输入Mat中的ROI区域
- **int is_expand** - 是否扩列。值为0时表示不扩列，值为1时表示在原马赛克周围扩列一个宏块（8个像素）
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

## quantify

### 函数原型
```cpp
bm_status_t bmcv::quantify(Mat &m, Mat &output, bool update)
```

### 功能
接口采用内置的TPU硬件加速单元，将输入的Mat对象的float类型数据转化成int类型（舍入模式为小数点后直接截断），并将小于0的数变为0，大于255的数变为255。

### 输入参数
- **Mat &m** - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- **bool update** - 是否需要同步cache或内存。如果为true，则转换完成后同步cache

### 输出参数
- **Mat &output** - 数据类型转化后的图像，只支持Mat对象

### 返回值
- **BM_SUCCESS(0)**：执行成功
- **其他**：执行失败

# void bmcv::uploadMat(Mat &mat)

| 函数原型 | void bmcv::uploadMat(Mat &mat) |
|----------|--------------------------------|
| 功能 | cache同步或者设备内存同步接口。当执行此函数时，cache中内容会flush到实际内存中（SOC模式） |
| 输入参数 | Mat &mat - 输入的需要内存同步的mat对象 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。 |

# void bmcv::downloadMat(Mat &mat)

| 函数原型 | void bmcv::downloadMat(Mat &mat) |
|----------|--------------------------------|
| 功能 | cache同步或者设备内存同步接口。当执行此函数时，cache中内容会invalidate（SOC模式） |
| 输入参数 | Mat &mat - 输入的需要内存同步的mat对象 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。 |

# bm_status_t bmcv::stitch(std::vector<Mat> &in, std::vector<Rect>& srt, std::vector<Rect>& drt, Mat &out, bool update = true, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)

| 函数原型 | bm_status_t bmcv::stitch(std::vector<Mat> &in, std::vector<Rect> &src, std::vector<Rect> &drt, Mat &out, bool update=true, bmcv_resize_alogrithm algorithm=BMCV_INTER_LINEAR) |
|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 功能 | 图像拼接，将输入的多个Mat按照按照给定的位置缩放并拼接到一个Mat中 |
| 输入参数 | std::vector<Mat> &in – 多个输入的Mat对象，可以为扩展的YUV格式或者标准BGR pack格式;<br>std::vector<Rect> &src – 对应每个Mat对象的显示内容框;<br>std::vector<Rect> &drt – 对应每个显示内容在目标Mat中的显示位置;<br>bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache<br>bmcv_resize_algorithm algorithm – 缩放算法,可以为Nearest或者Linear算法 |
| 输出参数 | Mat &out – 输出拼接后的Mat对象，可以为BGR packed或者YUV格式 |
| 返回值 | BM_SUCCESS(0)：执行成功  其他：执行失败 |
| 说明 | |

# void bmcv::print(Mat &m, bool dump = false)

| 函数原型 | void bmcv::print(Mat &m, bool dump = false) |
|----------|---------------------------------------------|
| 功能 | 调试接口，打印输入Mat对象的色彩空间，宽高以及数据。 |
| 输入参数 | Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGRpacked格式;<br>bool dump - true的时候打印Mat中的数据值，默认不打印。如果为true，则会在当前目录下生成mat_dump.bin文件 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 当前支持dump OpenCV标准BGRpacked或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGRSeparate格式数据 |

# void bmcv::print(bm_image *image, bool dump)

| 函数原型 | void bmcv::print(bm_image *image, bool dump) |
|----------|----------------------------------------------|
| 功能 | 调试接口，打印输入bm_image对象的色彩空间，宽高以及数据。 |
| 输入参数 | bm_image *image - 输入的bm_image对象;<br>bool dump - true的时候打印Mat中的数据值，默认不打印，如果为true，则会在当前目录下生成BMI-“宽”x”高”.bin文件 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 当前支持dump BGR packed,NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式的bm_image数据 |

# void bmcv::dumpMat(Mat &image, const String &fname)

| 函数原型 | void bmcv::dumpMat(Mat &image, const String &fname) |
|----------|-----------------------------------------------------|
| 功能 | 调试接口，专门dumpMat的数据到指定命名的文件。功能同3.23的dump为true时的功能。 |
| 输入参数 | Mat &image - 输入的Mat对象,可以为扩展的YUV格式或者标准BGR packed格式;<br>const String &fname – dump的输出文件名 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 当前支持dump OpenCV标准BGR packed或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式数据 |

# void bmcv::dumpBMImage(bm_image *image, const String &fname)

| 函数原型 | void bmcv::dumpBMImage(bm_image *image, const String &fname) |
|----------|--------------------------------------------------------------|
| 功能 | 调试接口，专门dump bm_image的数据到指定命名的文件。功能同3.25的dump为true时的功能。 |
| 输入参数 | bm_image *image - 输入的bm_image对象;<br>const String &fname – dump的输出文件名 |
| 输出参数 | 无 |
| 返回值 | 无 |
| 说明 | 当前支持dump BGR packed, NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式的bm_image数据 |

# bool Mat::avOK()

| 函数原型 | bool Mat::avOK() |
|----------|------------------|
| 功能 | 判断当前Mat是否为扩展的YUV格式 |
| 输入参数 | 无 |
| 输出参数 | 无 |
| 返回值 | true – 表示当前Mat为扩展的YUV格式<br>false – 表示当前Mat为标准OpenCV格式 |
| 说明 | 接口和接口3.21 3.22 downloadMat、uploadMat结合起来，可以有效地管理内存同步。<br>一般avOK为true的Mat，物理内存是最新的，而avOK为false的Mat，其cache或者host内存中的数据是最新的。可以根据这个信息，决定是调用uploadMat还是downloadMat。<br>如果一直在设备内存中通过硬件加速单元工作，则可以省略内存同步，仅在需要交换到系统内存中时再调用downloadMat。 |

# int Mat::avCols()

| 函数原型 | int Mat::avCols() |
|----------|-------------------|
| 功能 | 获取YUV扩展格式的Y的宽 |
| 输入参数 | 无 |
| 输出参数 | 无 |
| 返回值 | 返回扩展的YUV格式的Y的宽，如果为标准OpenCV Mat格式，返回0 |

# int Mat::avRows()

| 函数原型 | int Mat::avRows() |
|----------|-------------------|
| 功能 | 获取YUV扩展格式的Y的高 |
| 输入参数 | 无 |
| 输出参数 | 无 |
| 返回值 | 返回扩展的YUV格式的Y的高，如果为标准OpenCV Mat格式，返回0 |

# int Mat::avFormat()

| 函数原型 | int Mat::avFormat() |
|----------|---------------------|
| 功能 | 获取YUV格式信息 |
| 输入参数 | 无 |
| 输出参数 | 无 |
| 返回值 | 返回扩展的YUV格式信息，如果为标准OpenCV Mat格式，返回0 |

# int Mat::avAddr(int idx)

| 函数原型 | int Mat::avAddr(int idx) |
|----------|--------------------------|
| 功能 | 获取YUV各分量的物理地址 |
| 输入参数 | int idx – 指定YUV plane的序号 |
| 输出参数 | 无 |
| 返回值 | 返回指定的plane的物理首地址，如果为标准OpenCV Mat格式，返回0 |

# int Mat::avStep(int idx)

| 函数原型 | int Mat::avStep(int idx) |
|----------|--------------------------|
| 功能 | 获取YUV格式中指定plane的line size |
| 输入参数 | int idx – 指定YUV plane的序号 |
| 输出参数 | 无 |
| 返回值 | 指定的plane的line size，如果为标准OpenCV Mat格式，返回0 |

# AVFrame* av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MPEG, int id = 0)

| 函数原型 | AVFrame* av::create(int height, int width, int clor_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MPEG, int id = 0) |
|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 功能 | AVFrame的创建接口，允许外部创建系统内存和物理内存，创建的格式与FFMPEG下的AVFrame定义兼容 |
| 输入参数 | int height – 创建图像数据的高;<br>int width – 创建图像数据的宽;<br>int color_format – 创建图像数据的格式，详见FFMPEG pixfmt.h定义;<br>void *data – 系统内存地址，当为null时，表示该接口内部自己创建管理;<br>long addr – 设备内存地址;<br>int fd – 设备内存地址的句柄。如果为-1，表示设备内存由内部分配，反之则由addr参数给出。<br>int* plane_stride – 图像数据每层的每行stride数组;<br>int* plane_size – 图像数据每层的大小;<br>int color_space – 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义,默认为AVCOL_SPC_BT709;<br>int color_range – 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义，默认为AVCOL_RANGE_MPEG;<br>int id –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0 |
| 输出参数 | 无 |
| 返回值 | AVFrame结构体指针 |
| 说明 | 1.本接口支持创建以下图像格式的AVFrame数据结构：AV_PIX_FMT_GRAY8, AV_PIX_FMT_GBRP, AV_PIX_FMT_YUV420P, AV_PIX_FMT_NV12, AV_PIX_FMT_YUV422P horizontal, AV_PIX_FMT_YUV444P, AV_PIX_FMT_NV16<br>2.当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建失败 |

# AVFrame* av::create(int height, int width, int id = 0)

| 函数原型 | AVFrame* av::create(int height, int width, int id = 0) |
|----------|--------------------------------------------------------|
| 功能 | AVFrame的简易创建接口，所有内存均由内部创建管理,仅支持YUV420P格式 |
| 输入参数 | int height – 创建图像数据的高;<br>int width – 创建图像数据的宽;<br>int id –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0 |
| 输出参数 | 无 |
| 返回值 | AVFrame结构体指针 |
| 说明 | 本接口仅支持创建YUV420P格式的AVFrame数据结构 |

# int av::copy(AVFrame *src, AVFrame *dst, int id)

| 函数原型 | int av::copy(AVFrame *src, AVFrame *dst, int id) |
|----------|--------------------------------------------------|
| 功能 | AVFrame的深度copy函数，将src的有效图像数据拷贝到dst中 |
| 输入参数 | AVFrame *src – 输入的AVFrame原始数据指针;<br>int id – 指定设备卡号，详见5.1 |
| 输出参数 | AVFrame *dst – 输出的AVFrame目标数据指针 |
| 返回值 | 返回copy的有效图像数据个数，为0则没有发生拷贝 |
| 说明 | 1.本接口仅支持同设备卡号内的图像数据拷贝，即id相同<br>2.函数中的id仅需要指定设备卡号，不需要其他标志位 |

# int av::get_scale_and_plane(int color_format, int wscale[], int hscale[])

| 函数原型 | int av::get_scale_and_plane(int color_format, int wcale[], int hscale[]) |
|----------|--------------------------------------------------------------------------|
| 功能 | 获取指定图像格式相对于YUV444P的宽高比例系数 |
| 输入参数 | int color_format – 指定图像格式，详见FFMPEG pixfmt.h定义 |
| 输出参数 | int wscale[] – 对应格式相对于YUV444P每一层的宽度比例;<br>int hscale[] - 对应格式相对于YUV444P每一层的高度比例 |
| 返回值 | 返回给定图像格式的plane层数 |
| 说明 | |

# cv::Mat(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, SophonDevice device=SophonDevice())

| 函数原型 | cv::Mat(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, SophonDevice device=SophonDevice()) |
|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| 功能 | 新增的Mat构造接口。可以创建opencv标准格式或扩展的YUV Mat格式，并且系统内存和设备内存都允许通过外部分配给定 |
| 输入参数 | int height – 输入图像数据的高;<br>int width – 输入图像数据的宽;<br>int total – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小;<br>int _type – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1;<br>const size_t *steps – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP;<br>void *_data – 系统内存指针，如果为null，则内部分配该内存;<br>unsigned long addr – 设备物理内存地址，任意值均被认为有效的物理地址;<br>int fd – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理;<br>SophonDevice device –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0 |
| 输出参数 | 构造的标准BGR或扩展YUV的Mat数据类型 |
| 返回值 | 无 |
| 说明 | 1.SophonDevice是为了避免C++隐含类型匹配造成函数匹配失误而引入的类型，可以用SophonDevice(int id)直接从5.1节的ID转换过来<br>2.当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存 |

# Mat::Mat(SophonDevice device)

## 函数原型
`Mat::Mat(SophonDevice device)`

## 功能
新增的Mat构造接口，指定该Mat的后续操作在给定的device设备上

## 输入参数
`SophonDevice device` - 指定设备卡号以及HEAP位置的标志，详见5.1

## 输出参数
声明Mat数据类型

## 返回值
无

## 说明
1. 本构造函数仅初始化Mat内部的设备index，并不实际创建内存
2. 本构造函数的最大作用是对于某些内部create内存的函数，可以通过这个构造函数，提前指定创建内存的设备号和HEAP位置，从而避免将大量的内存分配在默认的设备号0上

# void Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, int id = 0)

## 函数原型
`void Mat::create(int height, int width, int total, int type, const size_t* _steps, void* _data, unsigned long addr, int fd, int id = 0)`

## 功能
Mat分配内存接口，该接口系统内存和设备内存都允许通过外部分配给定，也可内部分配。

## 输入参数
- `int height` – 输入图像数据的高
- `int width` – 输入图像数据的宽
- `int total` – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小
- `int _type` – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1
- `const size_t *steps` – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP
- `void *_data` – 系统内存指针，如果为null，则内部分配该内存
- `unsigned long addr` – 设备物理内存地址，任意值均被认为有效的物理地址
- `int fd` – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理
- `int id` – 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

## 输出参数
无

## 返回值
无

## 说明
1. 扩展的内存分配接口，主要改进目的是允许外置指定设备物理内存，当设备或者系统内存由外部创建的时候，则外部必须负责该内存的释放，否则会造成内存泄漏
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存

# void VideoWriter::write(InputArray image)

## 函数原型
`void VideoWriter::write(InputArray image)`

## 功能
与OpenCV标准VideoWriter::write接口用法和功能一致

**在调用write将全部frame传入之后，需要额外调用一次write，传入空的Mat进行flush操作**

## 输入参数
`InputArray image` – 输入的图像数据Mat结构

## 返回值
无

## 使用示例
```cpp
// General use, frame is the actual data you get from VideoCapture or somewhere
write(frame);
// Flush, empty is an empty data need not to be initialized
Mat emptyMat;
write(emptyMat);   // 仅需要调用一次
```

# void VideoWriter::write(InputArray image, char *data, int *len, cv::CV_RoiInfo *roiinfo)

## 函数原型
`void VideoWriter::write(InputArray image, char *data, int len)`

## 功能
新增的视频编码接口。与OpenCV标准VideoWriter::write接口不同，他提供了将编码视频数据输出到buffer的功能，便于后续处理

**在调用write将全部frame传入之后，需要额外调用多次write，传入空的Mat进行flush操作，直到接收不到新数据(len=0)停止flush**

## 输入参数
- `InputArray image` – 输入的图像数据Mat结构
- `cv::CV_RoiInfo *roiinfo`(可选) - 输入的roi信息

## 输出参数
- `char *data` – 输出的编码数据缓存
- `int *len` – 输出的编码数据长度

## 返回值
无

## 使用示例
```cpp
// General use, frame is the actual data you get from VideoCapture or somewhere
write(frame, data ,&data_len);
fwrite(data, 1, data_len, fp_out);  //fp_out is the file to be written
// Flush, empty is an empty data need not to be initialized
Mat emptyMat;
while(1){   //需要多次调用
    writer.write(emptyMat, data, &data_len);
    if(len > 0){
        fwrite(data, 1, data_len, fp_out);
        len = 0; //reset data_len
    }else
        break;  //直到拿不出数据结束flush
}
```

# virtual bool VideoCapture::grab(char *buf, unsigned int len_in, unsigned int *len_out);

## 函数原型
`bool VideoCapture::grab(char *buf, unsigned int len_in, usigned int *len_out);`

## 功能
新增的收流解码接口。与OpenCV标准VideoWriter::grab接口不同，他提供了将解码前的视频数据输出到buf的功能。

## 输入参数
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

## 输出参数
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

## 返回值
- `true` 表示收流解码成功
- `false` 表示收流解码失败

# virtual bool VideoCapture::read_record(OutputArray image, char *buf, unsigned int len_in, unsigned int *len_out);

## 函数原型
`bool VideoCapture::read_record(OutputArray image, char *buf, unsigned int len_in, unsigned int *len_out);`

## 功能
新增的读取码流视频接口。他提供了将解码前的视频数据输出到buf的功能，将解码后的数据输出到image。

## 输入参数
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

## 输出参数
- `OutputArray image` – 输出解码后的视频数据
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

## 返回值
- `true` 表示收流解码成功
- `false` 表示收流解码失败

# 硬件JPEG解码器的OpenCV 扩展

在BM1688系列芯片中，提供JPEG硬件编码解码模块。为使用这些硬件模块，SDK软件包中，扩展了OpenCV中与JPEG图片处理相关的API函数，如：`cv::imread()`、`cv::imwrite()`、`cv::imdecode()`、`cv::imencode()`等。您在使用这些函数做JPEG编解码的时候，函数内部会自动调用底层的硬件加速资源，从而大幅度提高了编解码的效率。如果您想保持这些函数原始的OpenCV API使用习惯，可以略过本节介绍；但如果你还想了解一下我们提供的简单易用的扩展功能，这节可能对您非常有帮助。

## 输出yuv格式的图像数据

OpenCV原生的`cv::imread()`、`cv::imdecode()` API函数执行JPEG图片的解码操作，返回一个Mat结构体，该Mat结构体中保存有BGR packed格式的图片数据，算能扩展的API函数功能可以返回JPEG图片解码后的原始的YUV格式数据。用法如下：

当这两个函数的第二个参数flags被设置成`cv::IMREAD_AVFRAME`时，表示解码后返回的Mat结构体out中保存着YUV格式的数据。具体是什么格式的YUV数据要根据JPEG文件的image格式而定。当flags被设置成其它值或者省略不设置时，表示解码输出OpenCV原生的BGR packed格式的Mat数据。解码器输入输出扩展数据格式说明如下表所示：

| 输入Image格式 | 输入YUV格式 | FFMPEG对应格式 |
|--------------|------------|---------------|
| I400         | I400       | AV_PIX_FMT_GRAY8 |
| I420         | NV12       | AV_PIX_FMT_NV12 |
| I422         | NV16       | AV_PIX_FMT_NV16 |
| I444         | I444 planar | AV_PIX_FMT_YUV444P |

可以通过`Mat::avFormat()`扩展函数，得到当前数据所对应的具体的FFmpeg格式。可以通过`Mat::avOK()`扩展函数，得知`cv::imdecode(buf, cv::IMREAD_AVFRAME, &out)`解码返回的out，是否是算能扩展的Mat数据格式。

另外在这两个接口中的flags增加`cv::IMREAD_RETRY_SOFTDEC`标志时会在硬件解码失败的情况下尝试切换软件解码，也可以通过设置环境变量`OPENCV_RETRY_SOFTDEC=1`实现此功能。

## 支持YUV格式的函数列表

目前算能Opencv已经支持YUV Mat扩展格式的函数接口列表如下：

- 视频解码类接口
  - VideoCapture类的成员函数

这类成员函数如read, grab，对于常用的HEVC, H264视频格式都使用了BM1688系列的硬件加速，并支持YUV Mat扩展格式。

- 视频编码类接口
  - VideoWriter类的成员函数

这类成员函数如write，对于常用的HEVC,H264视频格式已经使用了BM1688系列的硬件加速，并支持YUV Mat扩展格式。

- JPEG编码类接口
- JPEG解码类接口
  - Imread
  - Imwrite
  - Imdecode
  - Imencode

以上接口在处理JPEG格式的时候，已经使用了BM1688系列的硬件加速功能，并支持YUV Mat扩展格式。

# 图像处理类接口

## cvtColor
## resize

这两个接口在BM1688系列 SOC模式下支持YUV Mat扩展格式，并使用硬件加速进行了优化。

**尤其需要注意的是cvtColor接口，只在YUV转换成BGR或者GRAY输出的时候支持硬件加速和YUV Mat的格式，即只支持输入为YUV Mat格式，并进行了硬件加速，输出不支持YUV Mat格式。**

在PCIE模式下，考虑到服务器的CPU性能较强，仍然采用原来的opencv原生处理方式，并不支持YUV扩展格式。

## line
## rectangle
## circle
## putText

以上四个接口均支持YUV扩展格式。注意，这四个接口并没有采用硬件加速，而是使用CPU对YUV Mat扩展格式进行的支持。

# 基本操作类接口

## Mat类部分接口

### 创建释放接口
- create
- release
- Mat声明接口

### 内存赋值接口
- clone
- copyTo
- cloneAll
- copyAllTo
- assignTo
- operator =

### 扩展AV接口
- avOK
- avComp
- avRows
- avCols
- avFormat
- avStep
- avAddr

以上接口均支持YUV扩展格式，尤其是copyTo, clone接口都采用硬件进行了加速。

# 扩展类接口

## Bmcv接口
详见opencv2/core/bmcv.hpp

## AvFrame接口
详见opencv2/core/av.hpp

以上算能扩展类接口，均支持YUV Mat扩展格式，并均针对硬件加速处理进行了优化。

**注意：支持YUV Mat扩展格式的接口并不等价于使用了硬件加速，部分接口是通过CPU处理来实现。这点需要特别注意。**

# 在指定设备上运行硬件加速

本节内容适用于VideoCapture, 图像编解码的Imread, Imwrite等接口。

## PCIE ID参数的定义

ID参数为32位整型，它定义了pcie设备卡以及部分内存扩展标志信息，具体定义如下：

| Bit位域 | 描述 |
|---------|------|
| Bit0-7 | 描述了PCIE设备的卡号，宏定义BM_CARD_ID(id)可以获取这信息 |
| Bit8-10 | 描述对应PCIE卡上的HEAP内存位置。<br>Bit8为1表示硬件内存分配在 heap0上；<br>Bit9为1表示硬件内存内存分配在 heap1上；<br>Bit10为1表示硬件内存内存分配在 heap2上；<br>Bit8-10全为0默认分配在 heap1上；<br>Heap0/1/2的内存位置详见BMLIB API手册。<br>宏定义BM_CARD_HEAP(id)可获取该信息 |
| Bit11-20 | 描述了Mat的内存扩展标志。<br>B11-B18为opencv标准定义，见MemoryFlag枚举类型<br>B19-为扩展的DEVICE_MEM_ATTACHED，标志该设备内存为外部管理，不需要Opencv来管理释放<br>B20-为扩展的AVFRAME_ATTACHED，标志创建YUV Mat的AVFrame为外部管理，不需要Opencv来管理释放。<br>宏定义BM_CARD_MEMFLAG(id)可获取该信息 |
| B21-31 | 扩展保留 |
| 说明 | 宏定义BM_MAKEFLAG(attach,heap,card)可用来生成完整的ID定义，其中attach对应B11-20,heap对应 B8-10,card对应B0-7 |

## 利用ID参数指定PCIE设备

在PCIE模式下，多设备情况下需要指定在特定卡上运行硬件加速功能。为了满足这个需要，SOPHGO OpenCV对VideoCapture::Open, imread, imdecode以及mat.create接口进行了扩展，增加了int id参数。

```
bool VideoCapture::open(const String& filename, int apiPreference, int id)
Mat imdecode(InputArray _buf, int flags, int id )
Mat imread(const String& filename, int flags, int id )
void Mat::create(int d, const int* _sizes, int _type, int id)
```

通过指定id，可以指定视频解码、图片解码运行在指定PCIE设备上，并且解码出来的Mat输出记录了该PCIE卡设备的序号。后续的硬件加速操作会继续在该指定PCIE设备上运行。

对于输入是Mat的大部分接口来说，因为Mat在调用create接口分配内存的时候已经指定了设备号，就不需要额外增加参数来指定PCIE卡设备。可以根据Mat内置的设备号在对应的设备上进行加速处理。

## SOC ID参数的定义

soc 下id的含义，可以参考pcie，在id使用上可以将soc看做是pcie设备的卡号0(Bit0-7)，其他字段含义相同

# OpenCV与BMCV API的调用原则

BMCV API充分发挥了BM1688系列芯片中的硬件单元的加速能力，能提高数据处理的效率。而OpenCV软件提供了非常丰富的图像图形处理能力，将两者有机的结合起来，使客户开发既能利用OpenCV丰富的函数库，又能在硬件支持的功能上获得加速，是本节的主要目的。

在BMCV API和OpenCV函数以及数据类型的切换过程中，最关键是要尽量避免数据拷贝，使得切换代价最小。因此在调用流程中要遵循以下原则。

1. 由OpenCV Mat到BMCV API的切换，可以利用toBMI()函数，该函数以零拷贝的方式，将Mat中的数据转换成了BMCV API调用所需的bm_image类型。

2. 当BMCV API需要切换到OpenCV Mat的时候，要将最后一步的操作通过OpenCV中的bmcv函数来实现。这样既完成所需的图像处理操作，同时也为后续OpenCV操作完成了数据类型准备。因为一般OpenCV都要求BGR Pack的色彩空间，所以一般用toMat()函数作为切换前的最后一步操作。

3. 一般神经网络处理的数据为不带padding的RGB planar数据，并且对于输入尺寸有特定的要求。因此建议将resize()函数作为调用神经网络NPU接口前的最后一步操作。

4. 当crop、resize、color conversion三个操作是连续的时候，强烈建议客户使用convert()函数，这可以在带宽优化和速度优化方面都获得理想的收益。即使后续可能还需要做一次拷贝，但因为拷贝发生在缩放之后的图像上，这种代价也是值得的。

# OpenCV中GB28181国标接口介绍

SOPHGO复用OpenCV原生的Cap接口，通过对于url定义进行扩展，提供GB28181国标的播放支持。因此客户并不需要重新熟悉接口，只要对扩展的url定义进行理解，即可像播放rtsp视频一样，无缝的播放GB28181视频。

注意：国标中的SIP代理注册步骤，需要客户自己管理。当获取到前端设备列表后，可以直接用url的方式进行播放。

## 国标GB28181支持的一般步骤

- 启动SIP代理（一般客户自己部署或者平台方提供）
- 客户的下级应用平台注册到SIP代理
- 客户应用获取前端设备列表，如下所示。其中，34010000001310000009等为设备20位编码。

```
{"devidelist":
[{"id": "34010000001310000009"}
{"id": "34010000001310000010"}
{"id": "34020000001310101202"}]}
```

- 组织GB28181 url直接调用OpenCV Cap接口进行播放

## GB28181 url格式定义

### UDP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=34010000001310000009#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108:
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`：前端设备20位编码
- `localid`：本地二十位编码，可选项
- `localip`：本地ip，可选项
- `localmediaport`：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

### UDP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713:
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`：前端设备20位编码
- `devicetype`：录像存储类型
- `localid`：本地二十位编码，可选项
- `localip`：本地ip，可选项
- `localmediaport`：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。
- `begtime`：录像起始时间
- `endtime`：录像结束时间

### TCP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201:
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`：前端设备20位编码
- `localid`：本地二十位编码，可选项
- `localip`：本地ip，可选项

### TCP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713:
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`：前端设备20位编码
- `devicetype`：录像存储类型
- `localid`：本地二十位编码，可选项
- `localip`：本地ip，可选项
- `begtime`：录像起始时间
- `endtime`：录像结束时间

# PCIE模式下BMCPU OPENCV加速

## 概念介绍

Opencv有大量的图像处理函数在host cpu上实现，这样在PCIE环境下，就造成了host和板卡device设备之间交换同步内存的需求，而这种内存同步的速度要远远慢于内存cache的数据同步速度，从而给PCIE环境下的应用开发造成了瓶颈。而我们在的BM168x板卡上的每颗SOC都有强大的ARM Cortex A53处理器资源，目前在PCIE环境下处于闲置状态，因此BMCPU Opencv试图将Host Opencv和Device Opencv之间的功能函数映射起来，将Host Opencv的操作实际用Device Opencv的操作来实现，保证所有的数据都在Device Memory中进行，无需通过PCIE和host发生交换，从而一方面降低对Host CPU的压力，降低CPU处理器的处理性能要求，另一方面提高运行速度，消除PCIE带宽所带来的瓶颈。

BMCPU OPENCV的函数用法与原生OPENCV完全一致，只是为了区别在前面加上"bmcpu_"前缀。

## 使用说明

**说明1.凡是用BMCPU OPENCV改造过的接口，最新数据都位于device memory中。**

这点与之前的opencv cache管理策略有不同。之前在YUV Mat中，最新数据都位于device memory中，而在RGB Mat中，最新数据都位于host memory中。经过BMCPU OPENCV引入后，后续当函数支持到足够数目的时候，我们将在PCIE模式下，无论RGB Mat还是YUV Mat都以device memory为准，这样所有的pcie opencv操作的内存都移到了device memory上，不占用host memory。

**在达到这个目的之前，为了兼容原有opencv函数的调用，保留原函数，然后统一加上"bmcpu_"前缀的方式，重命名已修改的函数。** 可以查询我们的已完成函数列表来做对应操作。

对于列表中的函数，无论yuv Mat还是RGB Mat最新数据都在device memory中。当客户需要将其同步到host memory中的时候，需要手动调用bmcv::downloadMat()接口，当需要将host memory中的数据同步到device memory中时，需要调用bmcv::uploadMat()接口。

这点尤其重要，在调用改造过的函数前，如果最新数据在host memory中，就需要将其同步到device memory。**这在当Mat采用Scalar::all()，Zeros(), Ones()等函数初始化的时候尤其容易忽略，这时候要记得调用bmcv::uploadMat()将初始化同步到设备内存中。** 反之，当函数结束，后续处理需要在host memory中进行的时候，就需要调用bmcv::downloadMat()下载下来。

当输入输出Mat没有device内存的时候，函数会自动同步到host内存中，并且释放内部开辟的device内存。

**说明2. 参数传递的时候，要求与Mat有关的参数放在最前面。因为Mat的内存结构是提前分配好的，只能修改，不能重新分配。**

**说明3. 已完成函数列表**

| 已完成函数接口 | 修改后函数 | 说明 |
|---------------|-----------|------|
| cv::calcOpticalFlowPyrLK() | cv::bmcpu_calcOpticalFlowPyrLK() | 稀疏光流函数，支持标准BGR Mat格式 |
| cv::calcOpticalFlowFarneback() | cv::bmcpu_calcOpticalFlowFarneback() | 稠密光流函数，支持标准BGR Mat格式 |
| cv::gaussianBlur() | cv::bmcpu_gaussianBlur() | 支持BGR Mat格式 |
| cv::bilateralFilter() | cv::bmcpu_bilateralFilter() | 支持BGR Mat格式 |
| cv::boxFilter() | cv::bmcpu_boxFilter() | 支持BGR Mat格式 |
| cv::calcHist() | cv::bmcpu_calcHist() | calcHist函数共有三个函数类型，除了SparseMat不支持外，其他两个均支持 |
| cv::warpAffine() | cv::bmcpu_warpAffine() | 支持BGR Mat格式 |
| cv::sobel() | cv::bmcpu_sobel() | 支持BGR Mat格式 |
| cv::erode() | cv::bmcpu_erode() | 支持BGR Mat格式 |
| cv::dialet() | cv::bmcpu_dialet() | 支持BGR Mat格式 |
| cv::morphologyEx | cv::bmcpu_morphologyEx() | 支持BGR Mat格式 |
| cv::line() | cv::bmcpu_line() | Opencv中的画线函数，可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::putText() | cv::bmcpu_putText() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::rectangle() | cv::bmcpu_rectangle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::circle() | cv::bmcpu_circle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse() | 1.对应opencv中的函数:void ellipse(InputOutput Array _img, Point center, Size axes,double angle,double start_angle,double end_angle,const Scalar & color,int thickness,int line_type,int shift)<br>2.可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse2() | 1.对应opencv中的函数:void ellipse(InputOutput Array _img, const RotatedRect& box, const Scalar & color,int thickness, int lineType)<br>2.可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |

* cv::polylines() - cv::bmcpu_polylines() - 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式
* FreeType2::loadFontData() - cv::bmcpu_loadFontData() - 对应FreeType2类加载字库
* cv::bmcpu_unloadFontData() - 释放字库资源，与bmcpu_loadFontData成对调用
* FreeType2::setSplitNumber() - cv::bmcpu_setSplitNumber() - Ft2类接口
* FreeType2::getTextSize() - cv::bmcpu_getTextSize() - Ft2类接口
* FreeType2::putText() - cv::bmcpu_ft2_putText() - 可同时支持YUV和RGB Mat

代码实例见bmnnsdk2软件包中的examples/multimedia。

# SOPHGO FFMPEG使用指南

## 前言

BM1688系列芯片中，有一个8核的A53处理器，同时还内置有视频、图像相关硬件加速模块。在SOPHGO提供的FFMPEG SDK开发包中，提供了对这些硬件模块的接口。其中，通过这些硬件接口，提供了如下模块：硬件视频解码器、硬件视频编码器、硬件JPEG解码器、硬件JPEG编码器、硬件scale filter、硬件overlay filter、hwupload filter、hwdownload filter。

FFMPEG SDK开发包符合FFMPEG hwaccel编写规范，实现了视频转码硬件加速框架，实现了硬件内存管理、各个硬件处理模块流程的组织等功能。同时FFMPEG SDK也提供了与通常CPU解码器兼容的接口，以匹配部分客户的使用习惯。这两套接口我们称之为HWAccel接口和常规接口，他们底层共享BM1688硬件加速模块，在性能上是相同的。区别仅在于1）HWAccel需要初始化硬件设备; 2）HWAccel接口只面向设备内存，而常规接口同时分配了设备内存和系统内存; 3）他们的参数配置和接口调用上有轻微差别。

下面描述中，如非特殊说明，对常规接口和HWAccel接口都适用。

## 硬件视频解码器

BM1688系列支持H.264和H.265硬件解码。硬件解码器性能详情如下表所述。

| **Standard** | **Profile** | **Level** | **Max Resolution** | **Min Resolution** | **Bit rate** |
|--------------|-------------|-----------|-------------------|-------------------|-------------|
| H.264/AVC | BP/CBP/MP/HP | 4.1 | 8192x8192 | 16x16 | 50Mbps |
| H.265/HEVC | Main/Main10 | L5.1 | 8192x8192 | 16x16 | N/A |

在SophGo的FFMPEG发布包中，H.264硬件视频解码器的名字为*h264_bm*，H.265硬件视频解码器的名字为*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -decoders | grep _bm
```

### 硬件视频解码器支持的选项

FFMPEG中，BM1688系列的硬件解码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h decoder=h264_bm
$ ffmpeg -h decoder=hevc_bm
```

这些选项可以使用av_dict_set API来设置。在设置之前，需要对对这些选项有正确的理解。下面详细解释一下这些选项。

**output_format:**
- 输出数据的格式。
- 设为0，则输出线性排列的未压缩数据；设为101，则输出压缩数据。
- 缺省值为0。
- *推荐设置为101，输出压缩数据。可以节省内存、节省带宽。输出的压缩数据，可以调用后面介绍的scale_bm filter解压缩成正常的YUV数据。具体可参考应用示例中的示例1。*

**cbcr_interleave:**
- 硬件视频解码器解码输出的帧色度数据是否是交织格式。
- 设为1，则输出为semi-planar yuv图像，譬如nv12；设为0，则输出planar yuv图像，譬如yuv420p。
- 缺省值为1。

**extra_frame_buffer_num:**
- 硬件视频解码器额外提供硬件帧缓存数量。
- 缺省值为7。最小值为1。

**skip_non_idr:**
- 跳帧模式。0，关闭；1，跳过Non-RAP帧；2，跳过非参考帧。
- 缺省值为0。

**handle_packet_loss**
- 出错时，对H.264, H.265解码器使能丢包处理。0, 不做丢包处理；1，进行丢包处理。
- 缺省值为0。

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的系统内存里。1，关闭拷贝；0，使能拷贝。
- 缺省值为1。

**dec_cmd_queue:**
- 设置 cmmond queue 的深度，可选值为1~4。cmmond queue 可以提高解码器并行处理效率，但是会占用额外的内存资源。
- 缺省值为4。

## 硬件视频编码器

BM1688硬件视频编码器，支持H.264/AVC和H.265/HEVC视频编码。

BM1688硬件编码器设计的能力为: 能够实时编码10路1080P30的视频。具体指标如下：

**H.265编码器:**
- Capable of encoding HEVC Main/Main10/MSP(Main Still Picture) Profile @ L5.1 High-tier

**H.264编码器:**
- Capable of encoding Baseline/Constrained Baseline/Main/High/High 10 Profiles Level @ L5.2

**通用指标**
- 最大分辨率 : 8192x8192
- 最小分辨率 : 256x128
- 编码图像宽度须为8的倍数
- 编码图像高度宽度须为8的倍数

在SophGo的FFMPEG发布包中，H.264硬件视频编码器的名字为*h264_bm*，H.265硬件视频编码器的名字为*h265_bm*或*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -encoders
```

### 硬件视频编码器支持的选项

FFMPEG中， 硬件视频编码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h encoder=h264_bm
$ ffmpeg -h encoder=hevc_bm
```

BM1688硬件视频编码器支持如下选项:

**preset:** 预设编码模式。推荐通过enc-params设置。
- 0 - fast, 1 - medium, 2 - slow。
- 缺省值为2。

**gop_preset:** gop预设索引值。推荐通过enc-params设置。
- 1: all I, gopsize 1
- 2: IPP, cyclic gopsize 1
- 3: IBB, cyclic gopsize 1
- 4: IBPBP, cyclic gopsize 2
- 5: IBBBP, cyclic gopsize 4
- 6: IPPPP, cyclic gopsize 4
- 7: IBBBB, cyclic gopsize 4
- 8: random access, IBBBBBBBB, cyclic gopsize 8

**qp:**
- 恒定量化参数的码率控制方法
- 取值范围为0至51

**perf:**
- 用于指示是否需要测试编码器性能
- 取值范围为0或1。

**enc-params:**
- 用于设置视频编码器内部参数。
- 支持的编码参数：preset，gop_preset，qp，bitrate，mb_rc，delta_qp，min_qp，max_qp
- 编码参数preset：取值范围为fast, medium, slow或者是0，1，2
- 编码参数gop_preset：gop预设索引值。参考上面已有详细解释。
- 编码参数qp：恒定量化参数，取值范围为[0, 51]。当该值有效时，关闭码率控制算法，用固定的量化参数编码。
- 编码参数bitrate：用于编码所指定的码率。单位是Kbps，1Kbps=1000bps。当指定改参数时，请不要设置编码参数qp。
- 编码参数mb_rc：取值范围0或1。当设为1时，开启宏块级码率控制算法；当设为0时，开启帧级码率控制算法。
- 编码参数delta_qp：用于码率控制算法的QP最大差值。该值太大影响视频主观质量。太小影响码率调整的速度。
- 编码参数min_qp和max_qp：码率控制算法中用于控制码率和视频质量的最小量化参数和最大量化参数。取值范围[0, 51]。

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

**roi_enable**
- 使能roi。
- 缺省值为0

**enc_cmd_queue**
- 设置 cmmond queue 的深度，可选值为1~4。cmmond queue 可以提高编码器并行处理效率，但是会占用额外的内存资源。
- 缺省值为4

## 硬件JPEG解码器

在BM1688系列芯片中，硬件JPEG解码器提供硬件JPEG图像解码输入能力。这里介绍一下，如何通过FFMPEG来实现硬件JPEG解码。

在FFMPEG中, 硬件JPEG解码器的名称为*jpeg_bm*。可以通过如下命令, 来查看FFMPEG中是否有*jpeg_bm*解码器。

```
$ ffmpeg -decoders | grep jpeg_bm
```

### 硬件JPEG解码器支持的选项

FFMPEG中， 可以通过如下命令, 来查看*jpeg_bm*解码器支持的选项

```
$ ffmpeg -h decoder=jpeg_bm
```

解码选项的说明如下。硬件JPEG解码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**bs_buffer_size:** 用于设置硬件JPEG解码器中输入比特流的缓存大小(KBytes)。
- 取值范围(0到INT_MAX)
- 缺省值5120

**cbcr_interleave:** 用于指示JPEG解码器输出的帧数据中色度数据是否为交织的格式。
- 0: 输出的帧数据中色度数据为plannar的格式
- 1: 输出的帧数据中色度数据为interleave的格式
- 缺省值为0

**num_extra_framebuffers:** JPEG解码器需要的额外帧缓存数量
- 对于Still JPEG的输入, 建议该值设为0
- 对于Motion JPEG的输入, 建议该值至少为2
- 取值范围(0到INT_MAX)
- 缺省值为2

## 硬件JPEG编码器

在BM1688系列芯片中，硬件JPEG编码器提供硬件JPEG图像编码输出能力。这里介绍一下，*如何通过FFMPEG来实现硬件JPEG编码*。

在FFMPEG中，硬件JPEG编码器的名称为*jpeg_bm*。可以通过如下命令，来查看FFMPEG中是否有jpeg_bm编码器。

```
$ ffmpeg -encoders | grep jpeg_bm
```

### 硬件JPEG编码器支持的选项

FFMPEG中，可以通过如下命令, 来查看jpeg_bm编码器支持的选项

```
$ ffmpeg -h encoder=jpeg_bm
```

编码选项的说明如下。硬件JPEG编码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

## 硬件scale filter

BM1688系列硬件scale filter用于将输入的图像进行"缩放/裁剪/补边"操作。譬如，转码应用。在将1080p的视频解码后，使用硬件scale缩放成720p的，再进行压缩输出。

| *内容* | *最大分辨率* | *最小分辨率* | *放大倍数* |
|--------|-------------|-------------|-----------|
| 硬件限制 | 4096 * 4096 | 8*8 | 32 |

在FFMPEG中，硬件scale filter的名称为 *scale_bm*。

```
$ ffmpeg -filters | grep bm
```

### 硬件scale filter支持的选项

FFMPEG中，可以通过如下命令, 来查看scaler_bm编码器支持的选项

```
$ ffmpeg -h filter=scale_bm
```

scale_bm选项的说明如下:

**w:**
- 缩放输出视频的宽度。 请参考ffmpeg scale filter的用法。

**h:**
- 缩放输出视频的高度。 请参考ffmpeg scale filter的用法。

**format:**
- 缩放输出视频的像素格式。 请参考ffmpeg scale filter的用法。
- 输入输出支持的格式详见附表7.1。
- 缺省值"none"。 即输出像素格式为系统自动。输入为yuv420p，输出为yuv420p; 输入为yuvj420p，输出为yuvj420p。输入为nv12时，缺省输出为yuv420p。
- 在HWAccel框架下：支持nv12到yuv420p、nv12到yuvj420p、yuv420p到yuvj420p、yuvj422p到yuvj420p、yuvj422p到yuv420p的格式转换。在不启用HWAccel框架的正常模式下支持情况见附表7.1。

| 输入 | 输出 | 是否持缩放 | 是否支持颜色转换 |
|------|------|------------|-----------------|
| GRAY8 | GRAY8 | 是 | 是 |
| NV12（压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| NV12（非压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV420P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV422P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 否 |
|  | YUV444P | 否 | 否 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV444P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| BGR、RGB | YUV420P | 是 |  |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| RGBP、BGRP | YUV420P | 是 |  |

| 像素格式 | 支持缩放 | 支持补黑边 |
|---------|---------|-----------|
| YUV422P | 否      | 是        |
| YUV444P | 是      | 是        |
| BGR     | 是      | 是        |
| RGB     | 是      | 是        |
| RGBP    | 是      | 是        |
| BGRP    | 是      | 是        |

表7.1 scale_bm像素格式支持列表

**opt:**
- 缩放操作 (from 0 to 2) (default 0)
- 值0 - 仅支持缩放操作。缺省值。
- 值1 - 支持缩放+自动裁剪操作。命令行参数中可用crop来表示。
- 值2 - 支持缩放+自动补黑边操作。命令行参数中可用pad来表示。

**flags:**
- 缩放方法 (from 0 to 2) (default 1)
- 值0 - nearest滤波器。命令行参数中，可用nearest来表示。
- 值1 - bilinear滤波器。命令行参数中，可用bilinear来表示。
- 值2 - bicubic滤波器。命令行参数中，可用bicubic来表示。

**sophon_idx:**
- 设备ID , 从0开始。

**zero_copy:**
- 值0 - 表示scale_bm的输出AVFrame将同时包含设备内存和主机内存指针，兼容性最好，性能稍有下降。缺省为0
- 值1 - 表示scale_bm的输出到下一级的AVFrame中将只包含有效设备地址，不会对数据进行从设备内存到系统内存的同步。建议对于下一级接使用SOPHGO的编码/filter的情况，可以选择设置为1，其他建议设置为0。
- 缺省为0

## 硬件overlay filter

BM1688系列硬件overlay filter用于将一个视频流叠加在另一个视频流上, 可以用于实现水印/字幕/画中画等效果。

例如，在一个1080p的主输入视频上使用硬件overlay叠加一个352x288大小的滤镜视频。具体地，将两个视频解码后，使用硬件overlay把352x288大小的滤镜视频叠加到1080p的视频上，再将处理后的主输入视频进行压缩输出。

在FFMPEG中，硬件overlay filter的名称为 *overlay_bm*。

```
$ ffmpeg -filters | grep bm
```

### 硬件overlay filter支持的选项

FFMPEG中，可以通过如下命令, 来查看overlay_bm filter支持的选项

```
$ ffmpeg -h filter=overlay_bm
```

overlay_bm选项的说明如下:

**sophon_idx:**
- 设备ID，缺省值为0。

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的系统内存里，缺省值为1。
- 值1，关闭拷贝。
- 值0，使能拷贝。

**x:**
- 设置叠加滤镜的水平位置

**y:**
- 设置叠加滤镜的垂直位置

**eof_action:**
- 当遇到叠加输入的EOF（文件结束）状态时，overlay接下来的操作，缺省值为0。
- 值0 - repeat，重复叠加输入的上一帧
- 值1 - endall，立即结束叠加
- 值2 - pass，仅输入主输入流

**eval:**
- 用于指定在视频处理阶段的何时评估表达式，缺省值为1。
- 值0 - init，在初始化时评估表达式一次
- 值1 - frame，每帧都评估表达式，可以根据输入的变化动态调整overlay的属性。

**shortest:**
- 如果设置为1，则当较短的输入流结束时，整个处理将结束，缺省值为0。

**repeatlast:**
- 如果设置为1，当叠加内容结束后，将重复最后一帧的内容，缺省值为1。

**ts_sync_mode:**
- 控制流之间的时间同步策略，缺省值为0。
- 值0，从叠加流中选择时间戳最接近且小于等于主输入流当前帧的帧。
- 值1，从叠加流中选择与主输入流当前帧时间戳绝对最接近的帧。

## AVFrame特殊定义说明

遵从FFMPEG的规范, 硬件解码器是通过AVFrame来提供输出的，硬件编码器是通过AVFrame来提供输入的。因此，在通过API方式，调用FFMPEG SDK、进行硬件编解码处理时，需要注意到AVFrame的如下特殊规定。AVFrame是线性YUV输出。在AVFrame中，data为数据指针, 用于保存物理地址，linesize为每个平面的线跨度。

### 硬件解码器输出的avframe接口定义

#### 常规接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | cbcr_interleave=1 时CbCr的虚拟地址; cbcr_interleave=0 时Cb的虚拟地址 |
| 2 | cbcr_interleave=0 时Cr的虚拟地址 |
| 3 | 未使用 |
| 4 | Y的物理地址 |
| 5 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 |
| 6 | cbcr_interleave=0 时Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | cbcr_interleave=1时CbCr的虚拟地址的跨度；cbcr_interleave=0时Cb的虚拟地址的跨度 |
| 2 | cbcr_interleave=0时Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 |
| 6 | cbcr_interleave=0时Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

**data数组的定义**

| 下标 | 未压缩格式说明 | 压缩格式说明 |
|------|---------------|-------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 | 压缩的色度数据的物理地址 |
| 2 | cbcr_interleave=0 时Cr的物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

**linesize数组的定义**

| 下标 | 未压缩格式说明 | 压缩格式说明 |
|------|---------------|-------------|
| 0 | Y的物理地址的跨度 | 亮度数据的跨度 |
| 1 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 | 色度数据的跨度 |
| 2 | cbcr_interleave=0时Cr的物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 色度偏移量表的大小 |

### 硬件编码器输入的avframe接口定义

#### 常规接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的物理地址 |
| 1 | Cb的物理地址 |
| 2 | Cr的物理地址 |
| 3 | 保留 |
| 4 | 保留 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的物理地址的跨度 |
| 1 | Cb的物理地址的跨度 |
| 2 | Cr的物理地址的跨度 |
| 3 | 未使用 |

### 硬件filter输入输出的AVFrame接口定义

1. 在不启用HWAccel加速功能时，AVFrame接口定义采用常规接口的内存布局。

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

2. HWAccel接口下AVFrame接口定义

**data数组的定义**

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | Cb物理地址 | 压缩的色度数据的物理地址 |
| 2 | Cr物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

**linesize数组的定义**

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y物理地址的跨度 | 亮度数据的跨度 |
| 1 | Cb物理地址的跨度 | 色度数据的跨度 |
| 2 | Cr物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 色度偏移量表的大小 |

## 硬件加速在FFMPEG命令中的应用示例

下面同时给出常规模式和HWAccel模式对应的FFMPEG命令行参数。

为便于理解，这里汇总说明：
- 常规模式下，bm解码器的输出内存是否同步到系统内存上，用zero_copy控制，默认为1。
- 常规模式下，bm编码器的输入内存在系统内容还是设备内存上，用is_dma_buffer控制，默认值为1。
- 常规模式下，bm滤波器会自动判断输入内存的同步，输出内存是否同步到系统内存，用zero_copy控制，默认值为0。
- HWAccel模式下，设备内存和系统内存的同步用hwupload和hwdownload来控制。
- 常规模式下，用sophon_idx来指定设备，默认为0；HWAccel模式下用hwaccel_device来指定。

### 示例 1

使用设备0。解码H.265视频，输出compressed frame buffer，scale_bm解压缩compressed frame buffer并缩放成CIF，然后编码成H.264码流。

常规模式：
```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

HWAccel模式：
```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

### 示例 2

使用设备0。解码H.265视频，按比例缩放并自动裁剪成CIF，然后编码成H.264码流。

常规模式：
```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

HWAccel模式：
```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

### 示例 3

使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成H.264码流。

常规模式：
```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：
```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

### 示例 4

演示视频截图功能。使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成jpeg图片。

常规模式：
```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:format=yuvj420p:zero_copy=1" \
-c:v jpeg_bm -vframes 1 \
-y wkc_100_cif_scale.jpeg
```

HWAccel模式：
```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 \
-i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:format=yuvj420p" \
-c:v jpeg_bm -vframes 1 -y wkc_100_cif_scale.jpeg
```

### 示例 5

演示视频转码+视频截图功能。使用设备0。硬件解码H.265视频，缩放成CIF，然后编码成H.264码流；同时缩放成720p，然后编码成JPEG图片。

常规模式：
```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -filter_complex \
"[0:v]scale_bm=352:288:zero_copy=1[img1];[0:v]scale_bm=1280:720:format=yuvj420p:zero_copy=1[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

HWAccel模式：
```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 \
-i src/wkc_100.265 -filter_complex \
"[0:v]scale_bm=352:288[img1];[0:v]scale_bm=1280:720:format=yuvj420p[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

# 示例6

演示hwdownload功能。硬件解码H.265视频，然后下载存储成YUV文件。

Filter hwdownload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过codec中指定zero_copy选项来实现，因此不需要hwdownload滤波器。

常规模式：

```shell
ffmpeg -c:v hevc_bm -cbcr_interleave 0 -zero_copy 0 \
-i src/wkc_100.265 -y test_transfer.yuv
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -cbcr_interleave 0 \
-i src/wkc_100.265 -vf "hwdownload,format=yuv420p|bmcodec" -y test_transfer.yuv
```

# 示例7

演示hwdownload功能。硬件解码H.265视频，缩放成CIF格式，然后下载存储成YUV文件。

在常规模式中， scale_bm会自动根据filter的链条判定是否同步内存，因此不需要hwdownload。

常规模式：

```shell
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,format=yuv420p" \
-y test_transfer_cif.yuv
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,hwdownload,format=yuv420p|bmcodec" \
-y test_transfer_cif.yuv
```

# 示例8

演示hwupload功能。使用设备0。上传YUV视频，然后编码H.264视频。

Filter hwupload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过编码器中指定is_dma_buffer选项来实现，因此不需要hwupload滤波器。

常规模式：

```shell
ffmpeg -s 1920x1080 -pix_fmt yuv420p -i test_transfer.yuv \
-c:v h264_bm -b:v 3M -is_dma_buffer 0 -y test_transfer.264
```

HWAccel模式：

```shell
ffmpeg -init_hw_device bmcodec=foo:0 \
-s 1920x1080 -i test_transfer.yuv \
-filter_hw_device foo -vf "format=yuv420p|bmcodec,hwupload" \
-c:v h264_bm -b:v 3M -y test_transfer.264
```

这里foo为设备0的别名。

# 示例9

演示hwupload功能。使用设备1。上传YUV视频，并缩放成CIF，然后编码H.264视频。

常规模式：

```shell
ffmpeg -s 1920x1080 -i test_transfer.yuv \
-vf "scale_bm=352:288:sophon_idx=0:zero_copy=1" \
-c:v h264_bm -b:v 256K -sophon_idx 0 \
-y test_transfer_cif.264
```

说明：
1）这里不指定-pix_fmt yuv420p是因为默认输入为yuv420p格式
2）常规模式下,bm_scale filter, bm_overlay filter, decoder，encoder通过参数sophon_idx来指定使用哪个设备

HWAccel模式：

```shell
ffmpeg -init_hw_device bmcodec=foo:1 \
-s 1920x1080 -i test_transfer.yuv -filter_hw_device foo \
-vf "format=yuv420p|bmcodec,hwupload,scale_bm=352:288" \
-c:v h264_bm -b:v 256K -y test_transfer_cif.264
```

说明：这里foo为设备1的别名，HWAccel模式下通过init_hw_device来指定使用具体的硬件设备。

# 示例10

演示hwdownload功能。硬件解码YUVJ444P的JPEG视频，然后下载存储成YUV文件。

常规模式：

```shell
ffmpeg -c:v jpeg_bm -zero_copy 0 -i src/car/1920x1080_yuvj444.jpg \
-y car_1080p_yuvj444_dec.yuv
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v jpeg_bm -i src/car/1920x1080_yuvj444.jpg \
-vf "hwdownload,format=yuvj444p|bmcodec" \
-y car_1080p_yuvj444_dec.yuv
```

# 示例11

演示hwupload功能。使用设备1。上传YUVJ444P图像数据，然后编码JPEG图片。

常规模式：

```shell
ffmpeg -s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-frames:v 1 -c:v jpeg_bm -sophon_idx 1 -is_dma_buffer 0 \
-y car_1080p_yuvj444_enc.jpg
```

HWAccel模式：

```shell
ffmpeg -init_hw_device bmcodec=foo:1 -filter_hw_device foo \
-s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-frames:v 1 -vf 'format=yuvj444p|bmcodec,hwupload' \
-c:v jpeg_bm -y car_1080p_yuvj444_enc.jpg
```

这里foo为设备1的别名。

# 示例12

演示软解码和硬编码混合使用的方法。使用设备2。使用ffmpeg自带的*h264*软解码器，解码H.264视频，上传解码后数据到芯片2，然后编码H.265视频。

常规模式：

```shell
ffmpeg -c:v h264 -i src/1920_18MG.mp4 \
-c:v h265_bm -is_dma_buffer 0 -sophon_idx 2 -g 256 -b:v 5M \
-y test265.mp4
```

HWAccel模式：

```shell
ffmpeg -init_hw_device bmcodec=foo:2 -c:v h264 -i src/1920_18MG.mp4 \
-filter_hw_device foo -vf 'format=yuv420p|bmcodec,hwupload' \
-c:v h265_bm -g 256 -b:v 5M -y test265.mp4
```

这里foo为设备2的别名。

# 示例13

演示使用enc-params设置视频编码器的方法。使用设备0。解码H.265视频，缩放成CIF，然后编码成H.264码流。

常规模式：

```shell
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" -c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 \
-i src/wkc_100.265 -vf "scale_bm=352:288" -c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

# 示例14

使用设备0。解码H.265视频，使用bilinear滤波器，按比例缩放成CIF，并自动补黑边，然后编码成H.264码流。

常规模式：

```shell
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:flags=bilinear:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 \
-i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:flags=bilinear" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

# 示例15

演示overlay在图片上叠加图片滤镜功能。上传两个JPEG图片，overlay处理后，保存为JPEG文件。

常规模式：

```shell
ffmpeg -zero_copy 1 -c:v jpeg_bm -i JPEG_1920x1088_yuv420_planar.jpg \
-zero_copy 1 -c:v jpeg_bm -i JPEG_1280x720_yuv420_planar.jpg \
-filter_complex "overlay_bm=x=99:y=99:eof_action=1:zero_copy=1" \
-is_dma_buffer 1 -c:v jpeg_bm overlay_jpeg_to_jpeg.jpg
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -zero_copy 1 -c:v jpeg_bm \
-i JPEG_1920x1088_yuv420_planar.jpg \
-hwaccel bmcodec -hwaccel_device 0 -zero_copy 1 -c:v jpeg_bm \
-i JPEG_1280x720_yuv420_planar.jpg \
-filter_complex "overlay_bm=x=0:y=0:eof_action=1:zero_copy=1" \
-is_dma_buffer 1 -c:v jpeg_bm overlay_jpeg_to_jpeg.jpg
```

# 示例16

演示overlay在视频上叠加图片滤镜功能。上传一个264视频和一个JPEG图片，overlay处理后，保存为264文件。

常规模式：

```shell
ffmpeg -zero_copy 0 -extra_frame_buffer_num 5 -c:v h264_bm -i 1920x1080.264 \
-zero_copy 0 -c:v jpeg_bm -i JPEG_1280x720_yuv420_planar.jpg \
-filter_complex "scale_bm=1920:1088,overlay_bm=x=0:y=0:eof_action=0:zero_copy=0" \
-pix_fmt yuv420p -is_dma_buffer 0 -qp 30 -c:v h264_bm -vframes 100 overlay_jpeg_to_video.264
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -zero_copy 0 -extra_frame_buffer_num 5 \
-c:v h264_bm -i 1920x1080.264 \
-hwaccel bmcodec -hwaccel_device 0 -zero_copy 0 -c:v jpeg_bm \
-i JPEG_1280x720_yuv420_planar.jpg \
-filter_complex "scale_bm=1920:1088,overlay_bm=x=0:y=0:eof_action=0:zero_copy=0,hwdownload,format=yuv420p|bmcodec" \
-pix_fmt yuv420p -is_dma_buffer 0 -qp 30 -c:v h264_bm -vframes 100 overlay_jpeg_to_video.264
```

# 示例17

演示overlay在视频上叠加视频滤镜功能。上传两个264视频，overlay处理后，保存为264文件。

常规模式：

```shell
ffmpeg -zero_copy 1 -extra_frame_buffer_num 5 -c:v h264_bm -i 1920x1080.264 \
-c:v h264_bm -extra_frame_buffer_num 2 -zero_copy 1 -i test_352x288.264 \
-filter_complex "overlay_bm=x=300:y=100:eof_action=1:zero_copy=1" \
-is_dma_buffer 1 -qp 30 -c:v h264_bm -vframes 6 -an overlay_video_to_video.264
```

HWAccel模式：

```shell
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -zero_copy 1 -extra_frame_buffer_num 10 \
-c:v h264_bm -i 1920x1080.264 \
-hwaccel bmcodec -hwaccel_device 0 -c:v h264_bm -extra_frame_buffer_num 2 \
-zero_copy 1 -i test_352x288.264 \
-filter_complex "overlay_bm=x=10:y=10:eof_action=0:zero_copy=1" \
-is_dma_buffer 0 -qp 30 -c:v h264_bm -vframes 6 -an overlay_video_to_video.264
```

## 通过调用API方式来使用硬件加速功能

examples/multimedia/ff_bmcv_transcode/例子演示了使用ffmpeg做编解码，用bmcv做图像处理的整个流程。

examples/multimedia/ff_video_decode/例子演示了使用ffmpeg做解码的流程。

examples/multimedia/ff_video_encode/例子演示了使用ffmpeg做编码的流程。

## 硬件编码支持roi编码

参考examples/multimedia/ff_video_encode/例子。设置roi_enable既可启用roi编码。

Roi编码数据通过av_frame side data传递。

Roi数据结构定义为

**字段说明:**

- QP Map

H264下QP以宏块16x16为单位给出。HEVC下QP以sub-ctu（32x32）为单位给出。QP对应的就是video编码中的Qstep，取值范围为0-51.

- Lamda Map

lamda是用来控制和调节IP内部的RC计算公式
cost = distortion + lamda * rate
这个调节参数仅在HEVC下有效，允许以32x32 sub-CTU模块为单位控制。

- Mode Map

这个参数用来指定模式选择。 0 – 不适用 1 – skip mode 2- intra mode。H264下以宏块16x16为单位控制，HEVC下以CTU 64x64为单位控制。

- Zero-cut Flag

仅在HEVC下有效。将当前CTU 64x64残差系数全部置为0，从而节省出更多的比特给其他更重要的部分。

# SOPHGO LIBYUV使用指南

## 简介

BM1688系列芯片中的各种硬件模块，可以加速对图片和视频的处理。颜色转换方面，采用专用硬件来加速速度很快。

但在有些场合，也会存在一些专用硬件覆盖不到的特殊情况。此时采用经过SIMD加速优化的软件实现, 成为专用硬件有力的补充。

SOPHGO增强版**libyuv**，是随同SDK一同发布的一个组件。目的是充分利用BM1688系列芯片提供的8核A53处理器，通过软件手段为硬件的局限性提供补充。

除了libyuv提供的标准函数之外，针对AI的需求，在SOPHGO增强版libyuv中，补充了27个扩展函数。

注意：这里说的是运行在BM1688系列的A53处理器上，而不是host的处理器。这从设备加速的角度是可以理解的。这样可以避免占用host的CPU。

## libyuv扩展说明

新增了如下增强AI应用方面的API。

### fast_memcpy

`void* fast_memcpy(void *dst, const void *src, size_t n)`

| 功能 | CPU SIMD指令实现memcpy功能。从内存区域src拷贝n个字节到内存区域dst |
|------|-------------------------------------------------------------------|
| 参数 | src - 源内存区域<br>n - 需要拷贝的字节数<br>dst - 目的内存区域 |
| 返回值 | 返回一个指向dst的指针 |

### RGB24ToI400

`int RGB24ToI400(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, int width, int height);`

| 功能 | 将一帧BGR数据转换成BT.601灰度数据 |
|------|-----------------------------------|
| 参数 | src_rgb24 - packed BGR图像数据所在的内存虚地址<br>src_stride_rgb24 - 内存中每行BGR图像实际跨度<br>dst_y - 灰度图像虚拟地址<br>dst_stride_y - 内存中每行灰度图像实际跨度<br>width - 每行BGR图像数据中packed BGR的数量<br>height - BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

### RAWToI400

# RAWToI400

```c
int RAWToI400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);
```

| 功能 | 将一帧RGB数据转换成BT.601灰度数据 |
|------|----------------------------------|
| **参数** | |
| src_raw | packed BGR图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行BGR图像实际跨度 |
| dst_y | 灰度图像虚拟地址 |
| dst_stride_y | 内存中每行灰度图像实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# I400ToRGB24

```c
int I400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

| 功能 | 将一帧BT.601灰度数据转换成BGR数据 |
|------|----------------------------------|
| **参数** | |
| src_y | 灰度图像虚拟地址 |
| src_stride_y | 内存中每行灰度图像实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# I400ToRAW

```c
int I400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

| 功能 | 将一帧BT.601灰度数据转换成RGB数据 |
|------|----------------------------------|
| **参数** | |
| src_y | 灰度图像虚拟地址 |
| src_stride_y | 内存中每行灰度图像实际跨度 |
| dst_rgb24 | packed RGB图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行RGB图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# J400ToRGB24

```c
int J400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

| 功能 | 将一帧BT.601 full range 灰度数据转换成BGR数据 |
|------|----------------------------------|
| **参数** | |
| src_y | 灰度图像虚拟地址 |
| src_stride_y | 内存中每行灰度图像实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# RAWToJ400

```c
int RAWToJ400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);
```

| 功能 | 将一帧RGB数据转换成BT.601 full range灰度数据 |
|------|----------------------------------|
| **参数** | |
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | 灰度图像虚拟地址 |
| dst_stride_y | 内存中每行灰度图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# J400ToRAW

```c
int J400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

| 功能 | 将一帧BT.601 full range 灰度数据转换成RGB数据 |
|------|----------------------------------|
| **参数** | |
| src_y | 灰度图像虚拟地址 |
| src_stride_y | 内存中每行灰度图像实际跨度 |
| dst_rgb24 | packed RGB图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行RGB图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| **返回值** | 0, 正常结束; 非0, 参数异常 |

# RAWToNV12

```c
int RAWToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 功能 | 将一帧RGB数据转换成BT.601 limited range的semi-planar YCbCr 420数据 |
|------|----------------------------------|
| **参数** | |
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## RGB24ToNV12

```c
int RGB24ToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

**功能**：将一帧BGR数据转换成BT.601 limited range的semi-planar YCbCr 420数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_raw | packed BGR图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RAWToJ420

```c
int RAWToJ420(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧RGB数据转换成BT.601 full range的semi-planar YCbCr 420数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J420ToRAW

```c
int J420ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 420数据转换成RGB数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RAWToJ422

```c
int RAWToJ422(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧RGB数据转换成BT.601 full range的YCbCr 422数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J422ToRAW

```c
int J422ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 422数据转换成RGB数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RGB24ToJ422

```c
int RGB24ToJ422(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BGR数据转换成BT.601 full range的YCbCr 422数据

**参数**：
- `src_rgb24`：packed BGR图像数据所在的内存虚地址
- `src_stride_rgb24`：内存中每行BGR图像实际跨度
- `dst_y`：Y分量的虚拟地址
- `dst_stride_y`：内存中每行Y分量数据的实际跨度
- `dst_u`：Cb分量的虚拟地址
- `dst_stride_u`：内存中每行Cb分量数据的实际跨度
- `dst_v`：Cr分量的虚拟地址
- `dst_stride_v`：内存中每行Cr分量数据的实际跨度
- `width`：每行BGR图像数据中packed BGR的数量
- `height`：BGR图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## J422ToRGB24

```c
int J422ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 422数据转换成BGR数据

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_rgb24`：packed BGR图像数据所在的内存虚地址
- `dst_stride_rgb24`：内存中每行BGR图像数据的实际跨度
- `width`：每行RGB图像数据中packed BGR的数量
- `height`：BGR图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## RAWToJ444

```c
int RAWToJ444(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧RGB数据转换成BT.601 full range的YCbCr 444数据

**参数**：
- `src_row`：packed RGB图像数据所在的内存虚地址
- `src_stride_row`：内存中每行RGB图像实际跨度
- `dst_y`：Y分量的虚拟地址
- `dst_stride_y`：内存中每行Y分量数据的实际跨度
- `dst_u`：Cb分量的虚拟地址
- `dst_stride_u`：内存中每行Cb分量数据的实际跨度
- `dst_v`：Cr分量的虚拟地址
- `dst_stride_v`：内存中每行Cr分量数据的实际跨度
- `width`：每行RGB图像数据中packed RGB的数量
- `height`：RGB图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## J444ToRAW

```c
int J444ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 444数据转换成RGB数据

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_raw`：packed RGB图像数据所在的内存虚地址
- `dst_stride_raw`：内存中每行RGB图像数据的实际跨度
- `width`：每行RGB图像数据中packed RGB的数量
- `height`：RGB图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## RGB24ToJ444

```c
int RGB24ToJ444(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BGR数据转换成BT.601 full range的YCbCr 444数据

**参数**：
- `src_rgb24`：packed BGR图像数据所在的内存虚地址
- `src_stride_rgb24`：内存中每行BGR图像实际跨度
- `dst_y`：Y分量的虚拟地址
- `dst_stride_y`：内存中每行Y分量数据的实际跨度
- `dst_u`：Cb分量的虚拟地址
- `dst_stride_u`：内存中每行Cb分量数据的实际跨度
- `dst_v`：Cr分量的虚拟地址
- `dst_stride_v`：内存中每行Cr分量数据的实际跨度

## J420ToBGR24

```c
int J420ToBGR24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_bgr24, int dst_stride_bgr24, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 420数据转换成BGR数据

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_bgr24`：packed BGR图像数据所在的内存虚地址
- `dst_stride_bgr24`：内存中每行BGR图像数据的实际跨度
- `width`：每行BGR图像数据中packed BGR的数量
- `height`：BGR图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## J444ToRGB24

```c
int J444ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 444数据转换成BGR数据

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_rgb24`：packed BGR图像数据所在的内存虚地址
- `dst_stride_rgb24`：内存中每行BGR图像数据的实际跨度
- `width`：每行RGB图像数据中packed BGR的数量
- `height`：BGR图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## H420ToJ420

```c
int H420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.709 limited range的YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_y`：Y分量的虚拟地址
- `dst_stride_y`：内存中每行Y分量数据的实际跨度
- `dst_u`：Cb分量的虚拟地址
- `dst_stride_u`：内存中每行Cb分量数据的实际跨度
- `dst_v`：Cr分量的虚拟地址
- `dst_stride_v`：内存中每行Cr分量数据的实际跨度
- `width`：每行RGB图像数据中packed RGB的数量
- `height`：RGB图像数据的有效行数

**返回值**：0, 正常结束; 非0, 参数异常。

## I420ToJ420

```c
int I420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用

**参数**：
- `src_y`：Y分量的虚拟地址
- `src_stride_y`：内存中每行Y分量数据的实际跨度
- `src_u`：Cb分量的虚拟地址
- `src_stride_u`：内存中每行Cb分量数据的实际跨度
- `src_v`：Cr分量的虚拟地址
- `src_stride_v`：内存中每行Cr分量数据的实际跨度
- `dst_y`：Y分量的虚拟地址
- `dst_stride_y`：内存中每行Y分量数据的实际跨度
- `dst_u`：Cb分量的虚拟地址
- `dst_stride_u`：内存中每行Cb分量数据的实际跨度
- `dst_v`：Cr分量的虚拟地址
- `dst_stride_v`：内存中每行Cr分量数据的实际跨度
- `width`：每行RGB图像数据中packed RGB的数量
- `height`：RGB图像数据的有效行数

## NV12ToJ420

```c
int NV12ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_uv, int src_stride_uv,
uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_uv | CbCr分量的虚拟地址 |
| src_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## NV21ToJ420

```c
int NV21ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_vu, int src_stride_vu,
uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_vu | CrCb分量的虚拟地址 |
| src_stride_vu | 内存中每行CrCb分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## I444ToNV12

```c
int I444ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

**功能**：将一帧YCbCr 444数据转换成semi-plannar YCbCr 420数据。可用于full range,也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | 源图像Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | 源图像Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | 源图像Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | 目的图像Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | 目的图像CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行图像数据中像素的数量 |
| height | 图像数据像素的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## I422ToNV12

```c
int I422ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

**功能**：将一帧YCbCr 422数据转换成semi-plannar YCbCr 420数据。可用于full range,也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | 源图像Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | 源图像Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | 源图像Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | 目的图像Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | 目的图像CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行图像数据中像素的数量 |
| height | 图像数据像素的有效行数 |

# I400ToNV12

## 函数原型

```c
int I400ToNV12(const uint8_t* src_y, int src_stride_y, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

## 功能说明

将一帧YCbCr 400数据转换成semi-plannar YCbCr 420数据。可用于full range，也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用。

## 参数说明

| 参数 | 描述 |
|------|------|
| src_y | 源图像Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_y | 目的图像Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | 目的图像CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行图像数据中像素的数量 |
| height | 图像数据像素的有效行数 |

## 返回值

0, 正常结束; 非0, 参数异常。

# SOPHGO JPEG使用指南

## 简介

JPEG在BM1688产品系列中是一个可以实现多种图片格式编解码的功能模块。该模块包含编码、解码、镜像、旋转及ROI等功能，支持各种YUV格式。可以支持的分辨率范围为16x16~32768x32768，通过硬件加速，编解码性能也十分出色。

## JPEG数据结构说明

### BmJpuLogLevel

该类型表示jpeg动态库内日志等级。

**BmJpuLogLevel** 类型定义如下：

```c
typedef enum
{
    BM_JPU_LOG_LEVEL_ERROR   = 0,
    BM_JPU_LOG_LEVEL_WARNING = 1,
    BM_JPU_LOG_LEVEL_INFO    = 2,
    BM_JPU_LOG_LEVEL_DEBUG   = 3,
    BM_JPU_LOG_LEVEL_LOG     = 4,
    BM_JPU_LOG_LEVEL_TRACE   = 5
} BmJpuLogLevel;
```

### BmJpuImageFormat

该类型表示图像的格式。

**BmJpuImageFormat** 类型定义如下：

```c
typedef enum
{
    BM_JPU_IMAGE_FORMAT_YUV420P = 0,
    BM_JPU_IMAGE_FORMAT_YUV422P,
    BM_JPU_IMAGE_FORMAT_YUV444P,
    BM_JPU_IMAGE_FORMAT_NV12,
    BM_JPU_IMAGE_FORMAT_NV21,
    BM_JPU_IMAGE_FORMAT_NV16,
    BM_JPU_IMAGE_FORMAT_NV61,
    BM_JPU_IMAGE_FORMAT_GRAY,
    BM_JPU_IMAGE_FORMAT_RGB  /* for opencv */
} BmJpuImageFormat;
```

### BmJpuColorFormat

该类型表示图像的像素格式。

**BmJpuColorFormat** 类型定义如下：

```c
typedef enum
{
    /* planar 4:2:0; if the chroma_interleave parameter is 1, the corresponding format is NV12, otherwise it is I420 */
    BM_JPU_COLOR_FORMAT_YUV420            = 0,
    /* planar 4:2:2; if the chroma_interleave parameter is 1, the corresponding format is NV16 */
    BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL = 1,
    /* 4:2:2 vertical, actually 2:2:4 (according to the JPU docs); no corresponding format known for the chroma_interleave=1 case */
    /* NOTE: this format is rarely used, and has only been seen in a few JPEG files */
    BM_JPU_COLOR_FORMAT_YUV422_VERTICAL   = 2,
    /* planar 4:4:4; if the chroma_interleave parameter is 1, the corresponding format is NV24 */
    BM_JPU_COLOR_FORMAT_YUV444            = 3,
    /* 8-bit greayscale */
    BM_JPU_COLOR_FORMAT_YUV400            = 4,
    /* RGBP */
    BM_JPU_COLOR_FORMAT_RGB               = 5,
    /* BUTT */
    BM_JPU_COLOR_FORMAT_BUTT
} BmJpuColorFormat;
```

- **BM_JPU_COLOR_FORMAT_YUV420**
  YUV420格式。在cbcr_interleave=1的时候对应NV12格式。

- **BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL**
  YUV422格式。在cbcr_interleave=1的时候对应NV16格式。

- **BM_JPU_COLOR_FORMAT_YUV422_VERTICAL**
  YUV422格式（实际按2：2：4排列），JPU定义的一种格式，不常用。

- **BM_JPU_COLOR_FORMAT_YUV444**
  YUV444格式。在cbcr_interleave=1的时候对应NV24格式。

- **BM_JPU_COLOR_FORMAT_YUV400**
  YUV400格式。对应灰度图，只有Y分量。

- **BM_JPU_COLOR_FORMAT_RGB**
  RGB格式，暂未使用。

- **BM_JPU_COLOR_FORMAT_BUTT**
  未定义格式，用于设置默认值和异常判断。

### BmJpuChromaFormat

该类型表示色度格式。

**BmJpuChromaFormat** 类型定义如下：

```c
typedef enum
{
    BM_JPU_CHROMA_FORMAT_CBCR_SEPARATED = 0,
    BM_JPU_CHROMA_FORMAT_CBCR_INTERLEAVE = 1,
    BM_JPU_CHROMA_FORMAT_CRCB_INTERLEAVE = 2
} BmJpuChromaFormat;
```

- **BM_JPU_CHROMA_FORMAT_CBCR_SEPARATED**
  cb与cr分开，不交织。

- **BM_JPU_CHROMA_FORMAT_CBCR_INTERLEAVE**
  cb与cr交织。

- **BM_JPU_CHROMA_FORMAT_CRCB_INTERLEAVE**
  cr与cb交织。

### BmJpuRotateAngle

旋转角度。

**BmJpuRotateAngle** 类型定义如下：

```c
typedef enum
{
    BM_JPU_ROTATE_NONE = 0,
    BM_JPU_ROTATE_90 = 90,
    BM_JPU_ROTATE_180 = 180,
    BM_JPU_ROTATE_270 = 270
} BmJpuRotateAngle;
```

- **BM_JPU_ROTATE_NONE**
  不旋转。

- **BM_JPU_ROTATE_90**
  逆时针旋转90度。

- **BM_JPU_ROTATE_180**
  逆时针旋转180度。

- **BM_JPU_ROTATE_270**
  逆时针旋转270度。

### BmJpuMirrorDirection

镜像方向。

**BmJpuMirrorDirection** 类型定义如下：

```c
typedef enum
{
    BM_JPU_MIRROR_NONE = 0,
    BM_JPU_MIRROR_VER = 1,
    BM_JPU_MIRROR_HOR = 2,
    BM_JPU_MIRROR_HOR_VER = 3
} BmJpuMirrorDirection;
```

- **BM_JPU_MIRROR_NONE**
  不旋转。

- **BM_JPU_MIRROR_VER**
  竖直镜像。

- **BM_JPU_MIRROR_HOR**
  水平镜像。

- **BM_JPU_MIRROR_HOR_VER**
  竖直水平镜像。

### BmJpuFramebuffer

该结构体用于在BMAPI中描述一帧YUV数据。

**BmJpuFramebuffer** 结构体定义如下：

```c
typedef struct {
    unsigned int y_stride;
    unsigned int cbcr_stride;
    bm_device_mem_t *dma_buffer;
    size_t y_offset;
    size_t cb_offset;
    size_t cr_offset;

    void *context;
    int already_marked;
    void *internal;
} BmJpuFramebuffer;
```

- **y_stride**
  亮度（Y）分量的步长。

- **cbcr_stride**
  色度（Cb、Cr）分量的步长。

- **dma_buffer**
  用于存放YUV数据的一块设备内存，由bmlib分配。

- **y_offset**
  Y分量起始地址相对于dma_buffer中物理地址的偏移量。

- **cb_offset**
  Cb分量起始地址相对于dma_buffer中物理地址的偏移量。

- **cr_offset**
  Cr分量起始地址相对于dma_buffer中物理地址的偏移量。

- **context**
  用于保存解码上下文信息。

- **already_marked**
  标记当前帧是否可以输出。

- **internal**
  内部数据，由用户决定如何使用。

# BmJpuFramebufferSizes

该结构体用于记录对齐之后的framebuffer信息

**BmJpuFramebufferSizes** 结构体定义如下：

```c
typedef struct{
    unsigned int aligned_frame_width, aligned_frame_height;
    unsigned int y_stride, cbcr_stride;
    unsigned int y_size, cbcr_size;
    unsigned int total_size;
    BmJpuImageFormat image_format;
} BmJpuFramebufferSizes;
```

- **aligned_frame_width**：对齐之后的宽度
- **aligned_frame_height**：对齐之后的高度
- **y_stride**：亮度（Y）分量的步长
- **cbcr_stride**：色度（Cb、Cr）分量的步长
- **y_size**：Y分量的总数据量，单位：byte
- **cbcr_size**：Cb、Cr分量的总数据量，单位：byte
- **total_size**：framebuffer的总数据量，单位：byte
- **image_format**：图像格式，参考BmJpuImageFormat

# BmJpuEncodedFrame

编码出的jpeg的信息（未使用）

**BmJpuEncodedFrame** 结构体定义如下：

```c
typedef struct{
    uint8_t *data;
    size_t data_size;
    void *acquired_handle;
    void *context;
    uint64_t pts, dts;
} BmJpuEncodedFrame;
```

- **data**：编码出的jpeg data
- **data_size**：编码出的jpeg data的长度
- **acquired_handle**：在bm_jpu_jpeg_enc_encode时，用户定义的acquire_output_buffer函数指针
- **context**：用户定义的context，动态库内不会用到
- **pts, dts**：用户定义的时间戳

# BmJpuRawFrame

用于编码的原始的yuv图像的信息

**BmJpuRawFrame** 结构体定义如下：

```c
typedef struct{
    BmJpuFramebuffer *framebuffer;
    void *context;
    uint64_t pts, dts;
} BmJpuRawFrame;
```

- **BmJpuFramebuffer**：用于编码的yuv帧，参考BmJpuFramebuffer
- **context**：用户定义的context，动态库内不会用到
- **pts, dts**：用户定义的时间戳

# BmJpuDecOpenParams

该结构体用于定义打开解码器的参数，换句话说是设置解码器的属性（接收图片的大小，解码缓存区大小等属性）

**BmJpuDecOpenParams** 结构体定义如下：

```c
typedef struct
{
    unsigned int min_frame_width;
    unsigned int min_frame_height;
    unsigned int max_frame_width;
    unsigned int max_frame_height;

    BmJpuColorFormat color_format;
    int chroma_interleave;
    unsigned int scale_ratio;
    int bs_buffer_size;
#ifdef _WIN32
    uint8_t *buffer;
#else
    uint8_t *buffer __attribute__((deprecated));
#endif

    int device_index;
    int rotationEnable;
    BmJpuRotateAngle rotationAngle;
    int mirrorEnable;
    BmJpuMirrorDirection mirrorDirection;
    int roiEnable;
    int roiWidth;
    int roiHeight;
    int roiOffsetX;
    int roiOffsetY;
    bool framebuffer_recycle;
    size_t framebuffer_size;
    bool bitstream_from_user;
    bm_jpu_phys_addr_t bs_buffer_phys_addr;
    bool framebuffer_from_user;
    int framebuffer_num;
    bm_jpu_phys_addr_t *framebuffer_phys_addrs;
    int timeout;
    int timeout_count;
} BmJpuDecOpenParams;
```

- **min_frame_width**：解码器支持的最小width
- **min_frame_height**：解码器支持的最小height
- **max_frame_width**：解码器支持的最大width
- **max_frame_height**：解码器支持的最大height
- **color_format**：输入图像的编码格式（BM1688弃用）
- **chroma_interleave**：色度分量的存储方式的标识选项，可以是交错存储也可以是分开存储（BM1688弃用）
- **scale_ratio**：用于指定视频解码时的缩放比例。它决定了图像在解码过程中是否进行大小调整（即缩放）。如果值为0，则表示不进行任何缩放；如果值在1到3之间（包括1和3），则表示将图像按照2的n次幂进行缩放，其中n为scale_ratio的值
- **bs_buffer_size**：表示码流的缓冲区的大小，这里记录了存储输入图片需要的字节大小。当用户外部申请bitstream的设备内存时，buffer size需要1024对齐
- **buffer**：用于存储输入图片的具体内容（BM1688弃用）
- **device_index**：解码设备ID
- **rotationEnable**：是否做旋转操作的标识，0表示不旋转，1表示旋转
- **rotationAngle**：参考BmJpuRotateAngle
- **mirrorEnable**：是否做镜像操作的标识，0表示不镜像，1表示镜像
- **mirrorDirection**：参考BmJpuMirrorDirection
- **roiEnable**：是否设置ROI（感兴趣区域）
- **roiWidth**：ROI的宽度
- **roiHeight**：ROI的高度
- **roiOffsetX**：ROI相对图像左上角的水平偏移量
- **roiOffsetY**：ROI相对图像左上角的垂直偏移量
- **framebuffer_recycle**：是否复用framebuffer（BM1688弃用）
- **framebuffer_size**：设置framebuffer的大小，单位：byte
- **bitstream_from_user**：jpeg data的设备内存是否由用户设置
- **bs_buffer_phys_addr**：用户设置的jpeg data的设备内存地址
- **framebuffer_from_user**：解码得到的yuv图像的设备内存是否由用户设置
- **framebuffer_num**：framebuffer_num个数（BM1688弃用）
- **framebuffer_phys_addrs**：用户设置的解码得到的yuv图像的设备内存地址的指针
- **timeout**：用户设置解码超时时间（毫秒），不设置默认为20000ms
- **timeout_count**：用户设置解码超时重试次数（BM1688弃用）

# BmJpuDecoder

该结构体定义了BMAPI内部的解码器，包含解码器句柄、设备ID、解码分配的framebuffer等信息

**BmJpuDecoder** 结构体定义如下：

```c
struct _BmJpuDecoder
{
    unsigned int device_index;
    DecHandle handle;
    bm_device_mem_t *bs_dma_buffer;
    uint8_t *bs_virt_addr;
    uint64_t bs_phys_addr;
    int chroma_interleave;
    int scale_ratio;
    unsigned int old_jpeg_width;
    unsigned int old_jpeg_height;
    BmJpuColorFormat old_jpeg_color_format;
    unsigned int num_framebuffers, num_used_framebuffers;
    FrameBuffer *internal_framebuffers;
    BmJpuFramebuffer *framebuffers;
    BmJpuDecFrameEntry *frame_entries;
    DecInitialInfo initial_info;
    int initial_info_available;
    DecOutputInfo dec_output_info;
    int available_decoded_frame_idx;
    bm_jpu_dec_new_initial_info_callback initial_info_callback;
    void *callback_user_data;
    int framebuffer_recycle;
    int channel_id;
    FramebufferList *fb_list_head;
    FramebufferList *fb_list_curr;
    int timeout;
};
typedef struct _BmJpuDecoder BmJpuDecoder;
```

- **device_index**：解码设备ID
- **handle**：解码器句柄
- **bs_dma_buffer**：用于存放待解码码流的一块设备内存，由bmlib分配
- **bs_virt_addr**：存放待解码码流的虚拟地址
- **bs_phys_addr**：存放待解码码流的物理地址
- **chroma_interleave**：表示色度分量是否交叉排列
- **scale_ratio**：表示图像缩放比例。该参数同时控制图像在水平和垂直方向上的缩放级别
- **old_jpeg_width**：表示上一帧解码图像的宽度
- **old_jpeg_height**：表示上一帧解码图像的高度
- **old_jpeg_color_format**：表示上一帧解码图像的编码格式
- **num_framebuffers**：表示已分配的解码buffer数量
- **num_used_framebuffers**：表示已使用的解码buffer数量
- **internal_framebuffers**：解码器内部注册到JPU的framebuffer，用于和JPU交互
- **framebuffers**：解码器内部分配的全部framebuffer
- **frame_entries**：解码器内部解码buffer控制结构，指定了当前帧的PTS（显示时间）、DTS（解码时间）及使用状态
- **initial_info**：用于记录解码器的一些初始配置
- **initial_info_available**：用来标识解码器是否完成初始化
- **dec_output_info**：用于记录解码器的输出信息
- **available_decoded_frame_idx**：表示当前使用的解码帧序号
- **initial_info_callback**：一个用于初始化framebuffer的回调函数，当解码器输入码流变化时会重新分配framebuffer
- **callback_user_data**：用于存储上述回调函数中传递的用户自定义数据
- **framebuffer_recycle**：用于表示framebuffer是否复用的标识。在复用的情况下，可用同一个解码器实例解码不同分辨率、格式的码流
- **channel_id**：表示解码器通道ID
- **fb_list_head**：表示framebuffer链表中的头节点。解码器中使用链表存储当前使用中的framebuffer，会在执行flush或close操作时全部释放，也可以使用**bm_jpu_jpeg_dec_frame_finished**接口释放某一帧
- **fb_list_curr**：表示framebuffer链表中的当前节点。用于将新生成的framebuffer加入链表
- **timeout**：用户设置的超时时间

# BmJpuJPEGDecoder

该结构体定义了对外提供的解码器，包含解码器句柄、设备ID、解码分配的framebuffer等信息

**BmJpuJPEGDecoder** 结构体定义如下：

```c
typedef struct _BMJpuJPEGDecoder
{
    BmJpuDecoder *decoder;
    bm_jpu_phys_addr_t bitstream_buffer_addr;
    size_t bitstream_buffer_size;
    unsigned int bitstream_buffer_alignment;
    BmJpuDecInitialInfo initial_info;
    BmJpuFramebuffer *framebuffers;
    bm_jpu_phys_addr_t *framebuffer_addrs;
    unsigned int num_framebuffers;
    unsigned int num_extra_framebuffers;
    BmJpuFramebufferSizes calculated_sizes;
    BmJpuRawFrame raw_frame;
    int device_index;
    void *opaque;
    int rotationEnable;
    BmJpuRotateAngle rotationAngle;
    int mirrorEnable;
    BmJpuMirrorDirection mirrorDirection;
    bool framebuffer_recycle;
    bool bitstream_from_user;
    bool framebuffer_from_user;
}BmJpuJPEGDecoder;
```

- **decoder**：BMAPI内部定义的解码器
- **bitstream_buffer_addr**：用户外部申请，存放待解码码流的一块设备内存（在BmJpuDecOpenParams里生效，BM1688弃用）
- **bitstream_buffer_size**：表示上述码流的内存大小，单位：byte（在BmJpuDecOpenParams里生效，BM1688弃用）
- **bitstream_buffer_alignment**：表示上述码流的对齐要求，单位：byte（BM1688弃用）
- **initial_info**：用于记录解码器的一些初始配置
- **framebuffers**：用于记录解码器中framebuffer的地址及大小（BM1688弃用）
- **framebuffer_addrs**：用户申请的用于存储解码器中framebuffer的设备内存（在BmJpuDecOpenParams里生效，BM1688弃用）
- **num_framebuffers**：解码需要的framebuffer总帧数
- **num_extra_framebuffers**：解码需要的framebuffer额外帧数，通常为0
- **calculated_sizes**：记录对齐后的framebuffer大小信息
- **raw_frame**：表示原始帧数据，用于存储图像的原始数据和时间戳（BM1688弃用）
- **device_index**：表示解码设备ID
- **opaque**：未定义数据，由用户决定如何使用
- **rotationEnable**：是否做旋转操作的标识，0表示不旋转，1表示旋转
- **rotationAngle**：参考BmJpuRotateAngle
- **mirrorEnable**：是否做镜像操作的标识，0表示不镜像，1表示镜像
- **mirrorDirection**：参考BmJpuMirrorDirection
- **framebuffer_recycle**：用于表示framebuffer是否复用的标识。在复用的情况下，可用同一个解码器实例解码不同分辨率、格式的码流
- **bitstream_from_user**：用户申请jpeg data的设备内存（在BmJpuDecOpenParams里生效，BM1688弃用）
- **framebuffer_from_user**：用户申请解码得到的yuv图像的设备内存（在BmJpuDecOpenParams里生效，BM1688弃用）

# BmJpuJPEGDecInfo

该结构体记录了解码后的YUV数据信息，用于用户获取解码数据

**BmJpuJPEGDecInfo** 结构体定义如下：

```c
typedef struct
{
    unsigned int aligned_frame_width, aligned_frame_height;
    unsigned int actual_frame_width, actual_frame_height;
    unsigned int y_stride, cbcr_stride;
    unsigned int y_size, cbcr_size;
    unsigned int y_offset, cb_offset, cr_offset;
    BmJpuFramebuffer *framebuffer;
    BmJpuImageFormat image_format;
    bool framebuffer_recycle;
    size_t framebuffer_size;
} BmJpuJPEGDecInfo;
```

- **aligned_frame_width**：对齐之后该帧数据的宽度
- **aligned_frame_height**：对齐之后该帧数据的高度
- **actual_frame_width**：原始图像的宽度
- **actual_frame_height**：原始图像的高度
- **y_stride**：Y分量的步长
- **cbcr_stride**：Cb、Cr分量的步长
- **y_size**：Y分量的总数据量，单位：byte
- **cbcr_size**：Cb、Cr分量的总数据量，单位：byte
- **y_offset**：Y分量起始地址相对于framebuffer中物理地址的偏移量
- **cb_offset**：Cb分量起始地址相对于framebuffer中物理地址的偏移量
- **cr_offset**：Cr分量起始地址相对于framebuffer中物理地址的偏移量
- **framebuffer**：用来记录解码后的YUV数据相关信息
- **image_format**：图像格式
- **framebuffer_recycle**：用于表示framebuffer是否复用的标识。在复用的情况下，可用同一个解码器实例解码不同分辨率、格式的码流
- **framebuffer_size**：framebuffer_recycle模式下需要申请的framebuffer内存大小，单位：byte

# BmJpuEncoder

该结构体定义了BMAPI内部的编码器，包含编码器句柄、设备ID、输出码流等信息。

**BmJpuEncoder** 结构体定义如下:

```c
typedef struct _BmJpuEncoder
{
    unsigned int device_index;
    EncHandle handle;

    bm_device_mem_t *bs_dma_buffer;
    uint8_t *bs_virt_addr;

    BmJpuColorFormat color_format;
    unsigned int frame_width, frame_height;

    BmJpuFramebuffer *framebuffers;

    int channel_id;
    int timeout;
} BmJpuEncoder;
```

* **device_index** - 编码设备ID
* **handle** - 编码器句柄
* **bs_dma_buffer** - 用于存放输出码流的一块设备内存，由bmlib分配
* **bs_virt_addr** - 存放输出码流的虚拟地址
* **color_format** - 输出码流的编码格式
* **frame_width** - 输出码流的宽度
* **frame_height** - 输出码流的高度
* **framebuffers** - 编码器内部使用的framebuffer
* **channel_id** - 内部channel id
* **timeout** - 编码器超时时间

# BmJpuJPEGEncoder

该结构体定义了对外提供的编码器，包含编码器句柄、设备ID、输出码流等信息。

**BmJpuJPEGEncoder** 结构体定义如下:

```c
typedef struct _BmJpuJPEGEncoder
{
    BmJpuEncoder *encoder;

    bm_jpu_phys_addr_t bitstream_buffer_addr;
    size_t bitstream_buffer_size;
    unsigned int bitstream_buffer_alignment;

    BmJpuEncInitialInfo initial_info;

    unsigned int frame_width, frame_height;

    BmJpuFramebufferSizes calculated_sizes;

    unsigned int quality_factor;

    BmJpuImageFormat image_format;

    int device_index;

    int rotationEnable;
    BmJpuRotateAngle rotationAngle;
    int mirrorEnable;
    BmJpuMirrorDirection mirrorDirection;

    bool bitstream_from_user;
} BmJpuJPEGEncoder;
```

* **encoder** - BMAPI内部定义的编码器
* **bitstream_buffer_addr** - 用户外部申请的jpeg data的设备内存地址
* **bitstream_buffer_size** - 用户外部申请的jpeg data的大小
* **bitstream_buffer_alignment** - 表示上述码流的对齐要求，单位：byte
* **initial_info** - 用于记录编码器的framebuffer初始配置
* **frame_width** - 输入图像的宽度
* **frame_height** - 输入图像的高度
* **calculated_sizes** - 记录对齐后的framebuffer大小信息
* **quality_factor** - 编码质量
* **image_format** - 输入图像的编码格式
* **device_index** - 表示编码设备ID
* **rotationEnable** - 是否做旋转操作的标识，0表示不旋转，1表示旋转
* **rotationAngle** - 参考BmJpuRotateAngle
* **mirrorEnable** - 是否做镜像操作的标识，0表示不镜像，1表示镜像
* **mirrorDirection** - 参考BmJpuMirrorDirection
* **bitstream_from_user** - jpeg data的设备内存是否由用户外部申请（BM1688弃用）

# BmJpuJPEGEncParams

该结构体定义了编码配置参数及可配置的获取输出数据的接口函数。

**BmJpuJPEGEncParams** 结构体定义如下:

```c
typedef struct
{
    /* Frame width and height of the input frame. These are the actual sizes;
    * they will be aligned internally if necessary. These sizes must not be
    * zero. */
    unsigned int frame_width, frame_height;

    /* Quality factor for JPEG encoding. 1 = best compression, 100 = best quality.
    * This is the exact same quality factor as used by libjpeg. */
    unsigned int quality_factor;

    /* Image format of the input frame. */
    BmJpuImageFormat image_format;

    /* Functions for acquiring and finishing output buffers. See the
    * typedef documentations in bmjpuapi.h for details about how
    * these functions should behave. */
    BmJpuEncAcquireOutputBuffer acquire_output_buffer;
    BmJpuEncFinishOutputBuffer finish_output_buffer;

    /* Function for directly passing the output data to the user
    * without copying it first.
    * Using this function will inhibit calls to acquire_output_buffer
    * and finish_output_buffer. */
    BmJpuWriteOutputData write_output_data;

    /* User supplied value that will be passed to the functions:
    * acquire_output_buffer, finish_output_buffer, write_output_data */
    void *output_buffer_context;

    int rotationEnable;
    BmJpuRotateAngle rotationAngle;
    int mirrorEnable;
    BmJpuMirrorDirection mirrorDirection;

    /* Identify the output data is in device memory or system memory */
    int bs_in_device;

    int timeout;
    int timeout_count;

    /* Optional: User supplied device memory for following encode,
     * will replace the bitstream buffer in encoder */
    bm_jpu_phys_addr_t bs_buffer_phys_addr;
    int bs_buffer_size;
} BmJpuJPEGEncParams;
```

* **frame_width** - 输出码流的宽度
* **frame_height** - 输出码流的高度
* **quality_factor** - 编码质量，可选1（压缩率最高）~100（图像质量最好）
* **image_format** - 输出图片的编码格式
* **acquire_output_buffer** - 用来获取编码码流输出buffer的回调函数
* **finish_output_buffer** - 用来释放上述buffer的回调函数
* **write_output_data** - 用来指定编码码流输出方式的回调函数，如：写入文件或写入指定的内存地址，与上述两个接口互斥
* **output_buffer_context** - 用来保存输出数据的上下文
* **rotationEnable** - 是否做旋转操作的标识，0表示不旋转，1表示旋转
* **rotationAngle** - 参考BmJpuRotateAngle
* **mirrorEnable** - 是否做镜像操作的标识，0表示不镜像，1表示镜像
* **mirrorDirection** - 参考BmJpuMirrorDirection
* **bs_in_device** - 编码得到的jpeg data输出到设备内存（BM1688弃用）
* **timeout** - 用户设置编码器超时时间（ms），默认20000ms
* **timeout_count** - 用户设置超时重试次数（BM1688弃用）
* **bs_buffer_phys_addr** - 用户设置jpeg data的设备内存地址
* **bs_buffer_size** - 用户设置jpeg data的size

# JPEG接口说明

## bm_jpu_dec_load

该接口根据传入的ID打开指定的解码设备节点，可以通过bmlib管理内存分配。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_dec_load(int device_index);
```

**参数说明：**

* **device_index** - 解码设备ID

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK: 成功
* 其他: 失败

## bm_jpu_dec_unload

该接口释放指定的解码设备节点。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_dec_unload(int device_index);
```

**参数说明：**

* **device_index** - 解码设备ID

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK: 成功
* 其他: 失败

## bm_jpu_jpeg_dec_open

该接口打开一个解码器，根据传入的参数配置解码通道。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_open(BmJpuJPEGDecoder **jpeg_decoder,
                                 BmJpuDecOpenParams *open_params,
                                 unsigned int num_extra_framebuffers)
```

**参数说明：**

* **jpeg_decoder** - 指向解码器的二级指针，在接口内部完成初始化
* **open_params** - 打开解码器时的配置参数
* **num_extra_framebuffers** - 需要额外申请的framebuffer个数（BM1688弃用）

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他：失败

## bm_jpu_jpeg_dec_close

该接口用来关闭解码器，释放资源。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_close(BmJpuJPEGDecoder *jpeg_decoder);
```

**参数说明：**

* **jpeg_decoder** - 一个已经打开的解码器

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他：失败

## bm_jpu_jpeg_dec_decode

该接口执行解码操作。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_decode(
    BmJpuJPEGDecoder *jpeg_decoder,
    uint8_t const *jpeg_data,
    size_t const jpeg_data_size
    int timeout,
    int timeout_count);
```

**参数说明：**

* **jpeg_decoder** - 一个已经打开的解码器
* **jpeg_data** - 待解码的图像数据
* **jpeg_data_size** - 待解码的图像数据大小
* **timeout** - 解码器超时时间
* **timeout_count** - 解码器超时重试次数（BM1688弃用）

**返回值说明：**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他: 失败

## bm_jpu_jpeg_dec_get_info

该接口从解码器获取解码信息。

**接口形式：**

```c
void bm_jpu_jpeg_dec_get_info(
    BmJpuJPEGDecoder *jpeg_decoder,
    BmJpuJPEGDecInfo *info);
```

**参数说明：**

* **jpeg_decoder** - 一个已经打开的解码器
* **info** - 用于存储解码信息的数据结构

**返回值说明：**

* 无

## bm_jpu_jpeg_dec_frame_finished

该接口释放一帧解码完成的framebuffer。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_frame_finished(
    BmJpuJPEGDecoder *jpeg_decoder,
    BmJpuFramebuffer *framebuffer);
```

**参数说明：**

* **jpeg_decoder** - 一个已经打开的解码器
* **framebuffer** - 一帧解码完成的framebuffer

**返回值说明：**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他: 失败

## bm_jpu_jpeg_dec_flush

该接口用来刷新解码器，释放所有解码完成的framebuffer。

**接口形式：**

```c
BmJpuDecReturnCodes bm_jpu_jpeg_dec_flush(BmJpuJPEGDecoder *jpeg_decoder);
```

**参数说明：**

* **jpeg_decoder** - 一个已经打开的解码器

**返回值说明:**

* BM_JPU_DEC_RETURN_CODE_OK：成功
* 其他：失败

## bm_jpu_enc_load

该接口根据传入的ID打开指定的编码设备节点，可以通过bmlib管理内存分配。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_enc_load(int device_index);
```

**参数说明：**

* **device_index** - 编码设备ID

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_OK: 成功
* 其他: 失败

## bm_jpu_enc_unload

该接口释放指定的编码设备节点。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_enc_unload(int device_index);
```

**参数说明：**

* **device_index** - 编码设备ID

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_OK: 成功
* 其他: 失败

## bm_jpu_jpeg_enc_open

该接口打开一个编码器，并申请指定大小的bitstream buffer。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_open(
        BmJpuJPEGEncoder **jpeg_encoder,
        bm_jpu_phys_addr_t bs_buffer_phys_addr,
        int bs_buffer_size,
        int device_index
        );
```

**参数说明：**

* **jpeg_encoder** - 指向编码器的二级指针，在接口内部完成初始化
* **bs_buffer_phys_addr** - 用户外部申请的bitstream buffer设备内存地址
* **bs_buffer_size** - bistream buffer的大小，输入为0则默认申请5MB
* **device_index** - 编码设备ID

**返回值说明:**

* BM_JPU_ENC_RETURN_CODE_OK: 成功
* 其他:失败

## bm_jpu_jpeg_enc_close

该接口用来关闭编码器，释放资源。

**接口形式：**

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_close(BmJpuJPEGEncoder *jpeg_encoder);
```

**参数说明：**

* **jpeg_encoder** - 一个已经打开的编码器

**返回值说明：**

* BM_JPU_ENC_RETURN_CODE_OK: 成功
* 其他: 失败

# bm_jpu_jpeg_enc_encode

该接口执行编码操作。

## 接口形式

```c
BmJpuEncReturnCodes bm_jpu_jpeg_enc_encode(
        BmJpuJPEGEncoder *jpeg_encoder,
        BmJpuFramebuffer const *framebuffer,
        BmJpuJPEGEncParams const *params,
        void **acquired_handle,
        size_t *output_buffer_size
        );
```

## 参数说明

* **jpeg_encoder**：一个已经打开的编码器。
* **framebuffer**：输入的frame数据。
* **params**：编码相关参数。
* **acquired_handle**：用于存放编码数据的位置，由用户指定。如果为NULL，则通过write_output_data接口输出。
* **output_buffer_size**：输出数据buffer的大小，单位：byte。

## 返回值说明

* BM_JPU_ENC_RETURN_CODE_OK: 成功
* 其他: 失败

# acquire_output_buffer

该接口用于获取buffer接收编码数据。

## 接口形式

```c
void* acquire_output_buffer(void *context, unsigned int size, void **acquired_handle);
```

## 参数说明

* **context**：输出buffer上下文。
* **size**：输出buffer大小，单位：byte。
* **acquired_handle**：输出buffer的起始地址。

# finish_output_buffer

该接口用于释放上述接口获取的buffer。

## 接口形式

```c
void finish_output_buffer(void *context, void *acquired_handle);
```

## 参数说明

* **context**：输出buffer上下文。
* **acquired_handle**：输出buffer的起始地址。

# JPEG测试用例说明

## bmjpegdec

代码请参考example/jpeg_dec_test.c

### 参数说明

```sh
usage:  bmjpegdec [option]
option:
        -i input_file
        -o output_file
        -n loop_num
        -c crop function(0:disable  1:enable crop)
        -g rotate (default 0) [rotate mode[1:0]  0:No rotate  1:90  2:180  3:270] [rotator mode[2]:vertical flip] [rotator mode[3]:horizontal flip]
        -s scale (default 0) -> 0 to 3
        -r roi_x,roi_y,roi_w,roi_h
```

### 单路解码

```sh
bmjpegdec -i JPEG_1920x1088_yuv420_planar.jpg -o out_1920x1088_yuv420_planar.yuv -n 1
```

### 单路循环解码

```sh
bmjpegdec -i JPEG_1920x1088_yuv420_planar.jpg -o out_1920x1088_yuv420_planar.yuv -n 10
```

## bmjpegenc

代码请参考example/jpeg_enc_test.c

### 参数说明

```sh
usage:  bmjpegenc [option]
option:
        -f pixel format: 0.YUV420(default); 1.YUV422; 2.YUV444; 3.YUV400. (optional)
        -w actual width
        -h actual height
        -y luma stride (optional)
        -c chroma stride (optional)
        -v aligned height (optional)
        -i input file
        -o output file
        -n loop num
        -g rotate (default 0) [rotate mode[1:0]  0:No rotate  1:90  2:180  3:270] [rotator mode[2]:vertical flip] [rotator mode[3]:horizontal flip]
```

### 单路编码

```sh
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1
```

### 单路循环编码

```sh
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 10000
```

### 旋转

```sh
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1 -g 1
```

### 镜像

```sh
bmjpegenc -f 0 -w 1920 -h 1088 -i JPEG_1920x1088_yuv420_planar.yuv -o JPEG_1920x1088_yuv420_planar.jpg -n 1 -g 4
```

## bmjpegmulti

代码请参考example/jpeg_multi_test.c

### 32路解码

```sh
首先编写配置文件 multi.lst，内容如下:（第一行表示路数和每路的循环次数，之后每一行表示每一路的配置）

  32 100
  JPEG_352x288_yuv420_planar.jpg 32 1 0 0
  JPEG_352x288_yuv420_planar.jpg 32 1 0 0
  ...(重复到32行)

然后执行 bmjpegmulti -f multi.lst
选项输入 30
```

### 32路编码

```sh
首先编写配置文件 enc.cfg，内容如下:

  YUV_SRC_IMG JPEG_352x288_yuv420_planar.yuv
  FRAME_FORMAT 0
  PICTURE_WIDTH 352
  PICTURE_HEIGHT 288
  IMG_FORMAT 0

然后编写配置文件 multi.lst，内容如下:（第一行表示路数和每路的循环次数，之后每一行表示每一路的配置）

  32 1000000
  enc.cfg 32 0 0 0
  enc.cfg 32 0 0 0
  ...（重复到32行）

然后执行 bmjpegmulti -f multi.lst
选项输入 30
```

### 单路YUV400编码

```sh
bmjpegmulti -t 1 -i JPEG_1920x1088_yuv400_planar.yuv -o OUT400.jpg -w 1920 -h 1088 -s 4 -f 0 -n 4
```

### 单路YUV420P编码

```sh
bmjpegmulti -t 1 -i JPEG_1920x1088_yuv420_planar.yuv -o OUT420_planar.jpg -w 1920 -h 1088 -s 0 -f 0 -n 4
```

### 单路YUV422P编码

```sh
bmjpegmulti -t 1 -i JPEG_1920x1088_yuv422_planar.yuv -o OUT422_planar.jpg -w 1920 -h 1088 -s 1 -f 0 -n 4
```

# SOPHGO Video Decoder使用指南

## 简介

### 概述

VDEC 模块提供驱动视频解码硬件工作的对应接口，实现视频解码功能。

BM1688 VDEC 模块支持 H.264 和 H.265 解码，支持对16路 1080P 视频同时以 30fps 的性能进行解码。

### 定义及缩写

| 缩写 | 含义 |
|------|------|
| VPU | 视频处理单元 |
| VDEC | 视频解码器 |
| core | 核心 |
| BitStream | 输入码流数据 |
| Frame | 帧 |
| Buffer | 缓冲区 |
| channel | 通道 |

## VDEC 数据类型介绍

### BMVidDecRetStatus

定义了解码器错误返回值类型。

#### 枚举定义

```c
typedef enum
{
    BM_ERR_VDEC_INVALID_CHNID = -27,
    BM_ERR_VDEC_ILLEGAL_PARAM,
    BM_ERR_VDEC_EXIST,
    BM_ERR_VDEC_UNEXIST,
    BM_ERR_VDEC_NULL_PTR,
    BM_ERR_VDEC_NOT_CONFIG,
    BM_ERR_VDEC_NOT_SUPPORT,
    BM_ERR_VDEC_NOT_PERM,
    BM_ERR_VDEC_INVALID_PIPEID,
    BM_ERR_VDEC_INVALID_GRPID,
    BM_ERR_VDEC_NOMEM,
    BM_ERR_VDEC_NOBUF,
    BM_ERR_VDEC_BUF_EMPTY,
    BM_ERR_VDEC_BUF_FULL,
    BM_ERR_VDEC_SYS_NOTREADY,
    BM_ERR_VDEC_BADADDR,
    BM_ERR_VDEC_BUSY,
    BM_ERR_VDEC_SIZE_NOT_ENOUGH,
    BM_ERR_VDEC_INVALID_VB,
    BM_ERR_VDEC_ERR_INIT,
    BM_ERR_VDEC_ERR_INVALID_RET,
    BM_ERR_VDEC_ERR_SEQ_OPER,
    BM_ERR_VDEC_ERR_VDEC_MUTEX,
    BM_ERR_VDEC_ERR_SEND_FAILED,
    BM_ERR_VDEC_ERR_GET_FAILED,
    BM_ERR_VDEC_BUTT,
    BM_ERR_VDEC_FAILURE
}BMVidDecRetStatus;
```

#### 参数含义

* **BM_ERR_VDEC_INVALID_CHNID**: 无效的channel id。
* **BM_ERR_VDEC_ILLEGAL_PARAM**: 非法参数。
* **BM_ERR_VDEC_NULL_PTR**: 空指针。
* **BM_ERR_VDEC_NOBUF**: 无效的缓冲区。
* **BM_ERR_VDEC_BUF_FULL**: 缓冲区空。
* **BM_ERR_VDEC_BUF_FULL**: 缓冲区满。
* **BM_ERR_VDEC_BUSY**: 解码器忙。
* **BM_ERR_VDEC_FAILURE**: 解码器一般错误。

### BmVpuDecStreamFormat

码流格式。

#### 枚举定义

```c
typedef enum{
    BMDEC_AVC       = 0,
    BMDEC_HEVC      = 12,
}BmVpuDecStreamFormat;
```

#### 参数含义

* **BMDEC_AVC**: AVC码流。
* **BMDEC_HEVC**: HEVC码流。

### BmVpuDecSkipMode

设置跳帧模式。

#### 枚举定义

```c
typedef enum  {
    BMDEC_FRAME_SKIP_MODE	      = 0,
    BMDEC_SKIP_NON_REF_NON_I    = 1,
    BMDEC_SKIP_NON_I            = 2,
}BmVpuDecSkipMode;
```

#### 参数含义

* **BMDEC_FRAME_SKIP_MODE**: 禁用跳帧模式。
* **BMDEC_SKIP_NON_REF_NON_I**: 开启跳帧模式，跳过除参考帧和I帧外的视频帧。
* **BMDEC_SKIP_NON_I**: 开启跳帧模式，跳过除I帧外的视频帧。

### BmVpuDecDMABuffer

存储 VPU 缓冲区的信息。

#### 结构体定义

```c
typedef struct {
    unsigned int  size;
    u64           phys_addr;
    u64           virt_addr;
} BmVpuDecDMABuffer;
```

#### 参数含义

* **size**: 缓冲区的大小。
* **phys_addr**: 缓冲区的物理地址。
* **virt_addr**: 缓冲区的虚拟地址。

### BmVpuDecOutputMapType

设置输出数据的类型。

#### 枚举定义

```c
typedef enum {
    BMDEC_OUTPUT_UNMAP,
    BMDEC_OUTPUT_TILED = 100,
    BMDEC_OUTPUT_COMPRESSED,
} BmVpuDecOutputMapType;
```

#### 参数含义

* **BMDEC_OUTPUT_UNMAP**: 输出 yuv 数据。
* **BMDEC_OUTPUT_COMPRESSED**: 输出压缩模式数据。

### BmVpuDecBitStreamMode

设置 VPU 解码方式。

#### 枚举定义

```c
typedef enum {
    BMDEC_BS_MODE_INTERRUPT = 0,
    BMDEC_BS_MODE_RESERVED,
    BMDEC_BS_MODE_PIC_END = 2,
} BmVpuDecBitStreamMode;
```

#### 参数含义

* **BMDEC_BS_MODE_INTERRUPT**: 采用流模式解码，当输入缓冲区填满后送入解码器。
* **BMDEC_BS_MODE_PIC_END**: 采用帧模式解码，获取到一帧数据就送入解码器，需要提前解析码流。

# BmVpuDecPixFormat

设置输出数据的格式

## 枚举定义

```c
typedef enum
{
    BM_VPU_DEC_PIX_FORMAT_YUV420P = 0,
    BM_VPU_DEC_PIX_FORMAT_YUV422P = 1,
    BM_VPU_DEC_PIX_FORMAT_YUV444P = 3,
    BM_VPU_DEC_PIX_FORMAT_YUV400  = 4,
    BM_VPU_DEC_PIX_FORMAT_NV12    = 5,
    BM_VPU_DEC_PIX_FORMAT_NV21    = 6,
    BM_VPU_DEC_PIX_FORMAT_NV16    = 7,
    BM_VPU_DEC_PIX_FORMAT_NV24    = 8,
    BM_VPU_DEC_PIX_FORMAT_COMPRESSED = 9,
    BM_VPU_DEC_PIX_FORMAT_COMPRESSED_10BITS = 10,
} BmVpuDecPixFormat;
```

## 参数含义

- **BM_VPU_DEC_PIX_FORMAT_YUV420P**: 输出 YUV420P 数据
- **BM_VPU_DEC_PIX_FORMAT_YUV422P**: 输出 YUV422P 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_YUV444P**: 输出 YUV444P 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_YUV400**: 输出 YUV400 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_NV12**: 输出 NV12 数据
- **BM_VPU_DEC_PIX_FORMAT_NV21**: 输出 NV21 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_NV16**: 输出 NV16 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_NV24**: 输出 NV24 数据，BM1688 不支持
- **BM_VPU_DEC_PIX_FORMAT_COMPRESSED**: 输出压缩格式数据
- **BM_VPU_DEC_PIX_FORMAT_COMPRESSED_10BITS**: 输出10bits压缩格式数据，BM1688 不支持

# BMDecStatus

用于指示解码器的状态。

## 枚举定义

```c
typedef enum {
    BMDEC_UNCREATE,
    BMDEC_UNLOADING,
    BMDEC_UNINIT,
    BMDEC_INITING,
    BMDEC_WRONG_RESOLUTION,
    BMDEC_FRAMEBUFFER_NOTENOUGH,
    BMDEC_DECODING,
    BMDEC_FRAME_BUF_FULL,
    BMDEC_ENDOF,
    BMDEC_STOP,
    BMDEC_HUNG,
    BMDEC_CLOSE,
    BMDEC_CLOSED,
} BMDecStatus;
```

## 参数含义

目前只有以下几个状态有效：

- **BMDEC_UNINIT**: 解码器未进行初始化
- **BMDEC_INITING**: 解码器正在进行初始化
- **BMDEC_WRONG_RESOLUTION**: 设置的分辨率不匹配
- **BMDEC_FRAMEBUFFER_NOTENOUGH**: 分配的 Frame Buffer 不足
- **BMDEC_DECODING**: 解码器正在解码
- **BMDEC_STOP**: 解码器解码结束

# BMVidDecParam

BMVidDecParam 用于设置解码器的初始化参数，在调用接口 bmvpu_dec_create 前需要创建BMVidDecParam 对象，并对其进行初始化。

## 结构体定义

```c
typedef struct {
    BmVpuDecStreamFormat        streamFormat;
    BmVpuDecOutputMapType       wtlFormat;
    BmVpuDecSkipMode            skip_mode;
    BmVpuDecBitStreamMode       bsMode;
    int                         enableCrop;
    BmVpuDecPixFormat           pixel_format;
    int                         secondaryAXI;
    int                         mp4class;
    int                         frameDelay;
    int                         pcie_board_id;
    int                         pcie_no_copyback;
    int                         enable_cache;
    int                         perf;
    int                         core_idx;
    int                         cmd_queue_depth;
    int                         decode_order;
    int                         picWidth;
    int                         picHeight;
    int                         timeout;
    int                         timeout_count;
    int                         extraFrameBufferNum;
    int                         min_framebuf_cnt;
    int                         framebuf_delay;
    int                         streamBufferSize;
    BmVpuDecDMABuffer*          bitstream_buffer;
    BmVpuDecDMABuffer*          frame_buffer;
    BmVpuDecDMABuffer*          Ytable_buffer;
    BmVpuDecDMABuffer*          Ctable_buffer;
    int                         reserved[13];
} BMVidDecParam;
```

## 参数含义

- **streamFormat**: 设置输入码流类型，0为H.264(AVC)，12为H.265(HEVC)
- **wtlFormat**: 设置输出数据类型。设置为0，则根据yuv类型输出对应的yuv数据；设置为101，则输出压缩的fbc数据
- **skip_mode**: 设置跳帧模式
- **bsMode**: 设置解码器工作方式
- **pixel_format**: 输出图像格式
- **secondaryAXI**: BM1688中不在需要设置此参数，SDK中会根据码流类型，自动选择是否开启secondary AXI功能
- **decode_order**: 设置解码器出帧顺序。0，以显示序出帧；1，以解码序出帧
- **timeout**: 解码超时时间
- **timeout_count**: 解码超时重试次数
- **extraFrameBufferNum**: 设置Frame Buffer的数量
- **min_framebuf_cnt**: 输入码流所需要的最小的 Frame Buffer 的数量
- **framebuf_delay**: 解码延迟出帧所需要的 Frame Buffer 的数量
- **streamBufferSize**: 设置输入码流的缓冲区大小。若设置为0，则默认缓冲区大小为0x700000
- **bitstream_buffer**: 输入码流缓冲区信息
- **frame_buffer**: Frame Buffer 缓冲区信息
- **Ytable_buffer**: 压缩模式 Y table 缓冲区信息
- **Ctable_buffer**: 压缩模式 C table 缓冲区信息

# BMVidStream

通过 BMVidStream 对象，向解码器传递码流数据。

## 结构体定义

```c
typedef struct BMVidStream {
    unsigned char*  buf;
    unsigned int    length;
    unsigned char*  header_buf;
    unsigned int    header_size;
    unsigned char*  extradata;
    unsigned int    extradata_size;
    unsigned char   end_of_stream;
    u64             pts;
    u64             dts;
} BMVidStream;
```

## 参数含义

- **buf、length**: BitStream Buffer的地址和大小
- **end_of_stream**: 码流结束标志。当码流读取完成后，需要将这个标志位置1
- **pts、dts**: 时间戳
- BM1688中，不再接受 header 和 extradata 的数据。为了和前序产品保持一致，以上变量仍然存在

# BMVidFrame

BMVidFrame 用于接收解码器输出的帧信息。

## 结构体定义

```c
typedef struct BMVidFrame {
    BmVpuDecPicType     picType;
    unsigned char*      buf[8];
    int                 stride[8];
    unsigned int        width;
    unsigned int        height;
    BmVpuDecLaceFrame   interlacedFrame;
    int                 lumaBitDepth;
    int                 chromaBitDepth;
    BmVpuDecPixFormat   pixel_format;
    int                 endian;
    int                 sequenceNo;
    int                 frameIdx;
    u64                 pts;
    u64                 dts;
    int                 colorPrimaries;
    int                 colorTransferCharacteristic;
    int                 colorSpace;
    int                 colorRange;
    int                 chromaLocation;
    int                 size;
    unsigned int        coded_width;
    unsigned int        coded_height;
} BMVidFrame;
```

## 参数含义

- **picType**: 表示当前Frame的类型，对应关系如下：

| picType | 类型       |
|---------|------------|
| 0       | I picture  |
| 1       | P picture  |
| 2       | B picture  |
| 4       | IDR picture|

- **buf**: 存放输出数据的地址。各通道对应的含义如下表：

| channel | YUV420P           | NV12/NV21         | FBC                   |
|---------|-------------------|-------------------|-----------------------|
| 0       | Y分量虚拟地址     | Y分量虚拟地址     | /                     |
| 1       | Cb分量虚拟地址    | CbCr分量虚拟地址  | /                     |
| 2       | Cr分量虚拟地址    | /                 | /                     |
| 3       | /                 | /                 | /                     |
| 4       | Y分量物理地址     | Y分量物理地址     | Y 分量物理地址        |
| 5       | Cb分量物理地址    | CbCr分量物理地址  | Cb分量物理地址        |
| 6       | Cr分量物理地址    | /                 | Y table分量物理地址   |
| 7       | /                 | /                 | Cb table分量物理地址  |

- **stride**: 和buf对应，存放对应通道的宽度，该宽度是进行对齐后的宽度。对于FBC数据，stride存放的数据稍有不同：
  - channel 0和4，存放Y分量的宽度
  - channel 1和5，存放Cb分量的宽度
  - channel 2和6，存放Y table的长度
  - channel 3和7，存放Cb table的长度

- **width**: 存放Frame的宽度
- **height**: 存放Frame的高度
- **frameFormat**: 存放图像的格式
- **interlacedFrame**: 图像扫描方式
- **lumaBitDepth**: 亮度数据的深度
- **chromaBitDepth**: 色度数据的深度
- **cbcrInterleave**: 表示色度分量的存储方式。cbcrInterleave为0，Cb和Cr分量存储在不同的内存空间中；cbcrInterleave为1，Cb和Cr分量存储在同一个内存空间中
- **nv21**: 表示YUV数据的存储格式，仅当 cbcrInterleave=1 时有效。nv21=0，以Nv12格式存储；nv21=1，以NV21格式存储
- **endian**: 表示帧缓冲区的段序。endian=0，以小端模式存储；endian=1，以大端模式存储；endian=2，以32位小端模式存储；endian=3，以32位大端模式存储
- **sequenceNo**: 表示码流序列的状态。当码流序列改变时，sequenceNo的值会进行累加
- **frameIdx**: 图像帧缓冲区的索引。用于表示该帧缓冲区在解码器中位置
- **pts**: 显示时间戳
- **dts**: 解码时间戳
- **size**: 帧缓冲区的大小
- **coded_width**: 用于显示的图片宽度
- **coded_height**: 用于显示的图片高度
- **compressed_mode**: 表示解码器输出数据的格式

# CropRect

CropRect 用于保存图像的剪裁信息。

## 结构体定义

```c
typedef struct {
    unsigned int left;
    unsigned int top;
    unsigned int right;
    unsigned int bottom;
} CropRect;
```

## 参数含义

- **left**: 剪裁框左上角相对于像素原点的水平偏移量
- **top**: 剪裁框左上角相对于像素原点的垂直偏移量
- **right**: 剪裁框右下角相对于像素原点的水平偏移量
- **bottom**: 剪裁框右下角相对于像素原点的垂直偏移量

# BMVidStreamInfo

BMVidStreamInfo 用于接收输入码流的信息。

## 结构体定义

```c
typedef struct BMVidStreamInfo {
    int           picWidth;
    int           picHeight;
    int           fRateNumerator;
    int           fRateDenominator;
    CropRect      picCropRect;
    int           mp4DataPartitionEnable;
    int           mp4ReversibleVlcEnable;
    int           mp4ShortVideoHeader;
    int           h263AnnexJEnable;
    int           minFrameBufferCount;
    int           frameBufDelay;
    int           normalSliceSize;
    int           worstSliceSize;
    int           maxSubLayers;
    int           profile;
    int           level;
    int           tier;
    int           interlace;
    int           constraint_set_flag[4];
    int           direct8x8Flag;
    int           vc1Psf;
    int           isExtSAR;
    int           maxNumRefFrmFlag;
    int           maxNumRefFrm;
    int           aspectRateInfo;
    int           bitRate;
    int           mp2LowDelay;
    int           mp2DispVerSize;
    int           mp2DispHorSize;
    unsigned int  userDataHeader;
    int           userDataNum;
    int           userDataSize;
    int           userDataBufFull;
    int           chromaFormatIDC;
    int           lumaBitdepth;
    int           chromaBitdepth;
    int           seqInitErrReason;
    int           warnInfo;
    unsigned int  sequenceNo;
} BMVidStreamInfo;
```

## 参数含义

- **picWidth**: 图片宽度

# VDEC API 介绍

## bmvpu_dec_create

bmvpu_dec_create 用来创建一个解码器通道。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_create (
    BMVidCodHandle* pVidCodHandle,
    BMVidDecParam decParam );
```

**参数说明**

* **pVidCodHandle**: 输出参数。解码器句柄，当解码器创建成功后将会返回一个句柄，用句柄可以对解码器进行后续的操作。
* **decParam**: 输入参数。解码器初始化参数。

**返回值**

当解码器创建成功，会返回 0，否则将返回对应的错误码。

## bmvpu_dec_decode

利用 bmvpu_dec_decode 将 BitStream 送入 VDEC 进行解码。BM1688支持两种解码模式，分别是 INTERRUPT 和 PIC_END 模式。

**INTERRUPT模式** 是按照预先设置的 BitStream Buffer 大小，每次送入固定大小的码流数据，并不存在帧的概念。

**PIC_END模式** 是根据 H.264/H.265 协议，预先解析出一帧数据的位置，每次只向解码器传输一帧数据对应的 BitStream，因此在创建解码器时，需要合理考虑 streamBufferSize 的值。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_decode (
    BMVidCodHandle vidCodHandle,
    BMVidStream vidStream );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。
* **vidStream**: 输入参数。BitStream的地址和大小。

**返回值**

当码流成功送入解码器，会返回 0，否则将返回对应的错误码。返回错误并不代表解码器工作异常。若返回 BM_ERR_VDEC_BUF_FULL，需要检查解码器状态，并再次尝试送 BitStream。

## bmvpu_dec_get_output

bmvpu_dec_get_output 这个接口用于来获取解码器的输出数据。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_get_output (
    BMVidCodHandle vidCodHandle,
    BMVidFrame *bmFrame );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。
* **bmFrame**: 输出参数。用于接收解码器的输出数据。

**返回值**

当成功获得到解码数据，会返回0，否则返回对应的错误码。返回错误码并不代表解码器工作异常，以下情况都有可能造成返回错误码：

1. 没有输入BitStream数据；
2. 解码尚未完成，输出数据未准备好；
3. 解码器关闭；
4. 解码器异常。

## bmvpu_dec_clear_output

当 Frame Buffer 不再使用时，需要调用 bmvpu_dec_clear_output 对其进行释放。否则解码器可能因为没有足够的 Frame Buffer 而工作异常。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_clear_output (
    BMVidCodHandle vidCodHandle,
    BMVidFrame *frame );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。
* **frame**: 输入参数。需要释放的 bmFrame 对象的地址。

**返回值**

当 frame 释放成功，会返回0，否则返回对应的错误码。

## bmvpu_dec_flush

当 BitStream 全部送入解码器后，并不代表解码已经完成，还需要等待解码器将全部的 Frame 输出。用 bmvpu_dec_flush 来刷出剩余的 Frame。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_flush (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

当 Frame 全部取出后，将会返回0。

## bmvpu_dec_get_all_frame_in_buffer

同样用于在码流传送完毕后，获取解码器中的剩余的 Frame 数据。和 bmvpu_dec_flush 不同之处在于，bmvpu_dec_get_all_frame_in_buffer 不会阻塞。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_get_all_frame_in_buffer (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

当 Frame 全部拿出解码器后，将会返回0。

## bmvpu_dec_delete

当解码任务完成后，调用 bmvpu_dec_delete 销毁解码器，释放解码器占用的资源。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_delete (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

解码器销毁成功后，会返回0，否则返回对应的错误码。

## bmvpu_dec_get_caps

bmvpu_dec_get_caps 用于获取解码器信息，主要是送入解码器的码流信息。能够获取到的信息可以参考 BMVidStreamInfo 结构体的定义。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_get_caps (
    BMVidCodHandle vidCodHandle,
    BMVidStreamInfo *streamInfo );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。
* **streamInfo**: 输出参数。接收解码器信息。

**返回值**

成功获取解码器信息，返回0，否则返回对应的错误码。

## bmvpu_dec_get_status

bmvpu_dec_get_status用于获取解码器的工作状态。目前所支持的解码器状态可以参考 BMDecStatus 的定义。

**接口形式**

```c
BMDecStatus bmvpu_dec_get_status (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

若成功获取到解码器状态，将会返回对应的状态，反则将返回错误码。

## bmvpu_dec_get_all_empty_input_buf_cnt

用于获取空闲的 BitStream Buffer 的数量。

**接口形式**

```c
int bmvpu_dec_get_all_empty_input_buf_cnt (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

若成功获取到 BitStream 的数量，则返回空闲 Buffer 的数量，否则返回错误码。

## bmvpu_dec_get_stream_buffer_empty_size

用于获取 BitStream Buffer 未使用的空间大小。

**接口形式**

```c
int bmvpu_dec_get_stream_buffer_empty_size (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

若成功则返回 BitStream Buffer 未使用的空间大小，否则返回错误码。

## bmvpu_dec_get_pkt_in_buf_cnt

用于获取被占用的 BitStream Buffer 的数量。

**接口形式**

```c
int bmvpu_dec_get_pkt_in_buf_cnt (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

若成功获取到 BitStream 的数量，则返回被占用 Buffer 的数量，否则返回错误码。

## bmvpu_dec_dump_stream

用于保存输入码流数据，目前仅支持保存 INTERRUPT 模式的数据；若为 PIC_END 模式，保存的数据可能出现无法播放的情况（缺少一些非显示帧的信息）。该接口已经写入 bmvpu_dec_decode 中，通过设置环境变量 BMVPU_DEC_DUMP_NUM 可以使能该功能。

**接口形式**

```c
BMVidDecRetStatus bmvpu_dec_dump_stream (
    BMVidCodHandle vidCodHandle,
    BMVidStream vidStream );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。
* **vidStream**: 输入参数。BitStream的地址和大小。

**返回值**

码流保存成功，则返回0，否则返回错误码。

## bmvpu_dec_get_core_idx

用于获取 VPU 的 core id。对于 BM1688，有两个解码core，分别是 core 0 和 core 1。

**接口形式**

```c
int bmvpu_dec_get_core_idx (
    BMVidCodHandle handle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

成功则返回 VPU 的 core id，否则返回错误码。

## bmvpu_dec_get_inst_idx

用于获取 VDEC 的 channel id。对于 BM1688 来说，每个 core 最多可以申请32个 channel。

**接口形式**

```c
int bmvpu_dec_get_inst_idx (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

成功则返回 VDEC 的 channel id，否则返回错误码。

## bmvpu_dec_get_device_fd

用于获取 VDEC channel 对应的设备节点 id。

**接口形式**

```c
int bmvpu_dec_get_device_fd (
    BMVidCodHandle vidCodHandle );
```

**参数说明**

* **vidCodHandle**: 输入参数。解码器句柄，在使用该接口前需要先创建解码器。

**返回值**

成功则返回设备节点的 id，否则返回错误码。

# VDEC API 测试例程

针对 VDEC 提供了专用的测试例程 bm_test。其中调用了 VDEC API 来实现对本地 H.264/H.265 码流文件进行解码。

bm_test 提供了以下可配置参数

* **-h**: 查看提示信息，可以看到 bm_test 的可选参数以及对应的参数说明。
* **-v**: 设置 LOG 等级。0：none；1：error；2：warning；3：info；4：trace。缺省值为1。
* **-c**: 设置输出校验方式。0：不进行输出校验；1：直接对比yuv数据；2：对比输出yuv的md5值。开启输出校验前需提前准备好参考文件，通过 --comp-skip 设置对比的频率。缺省值为0。
* **-n**: 设置解码的轮数。缺省值为1。
* **-m**: 设置解码模式。0：设置为 INTERRUPT 模式；2：设置为 PIC_END 模式。
* **--input**: 设置输入文件。
* **--cbcr_interleave**: 设置Cb和Cr是否交错，0表⽰不交错，1表⽰交错。
* **--nv21**: 仅当--cbcr_interleave设置为 1 时有效。设置为 0，以 NV12 格式输出；设置为 1，以 NV21 格式输出。
* **--stream-type**: 设置输入码流类型。0：H.264；12：H.265。
* **--ref-yuv**: 设置参考文件路径。当开启输出校验后，必须设置此参数，否则不会进行输出校验。
* **--instance**: 设置解码线程数。
* **--write_yuv**: 设置输出帧数。这个参数只用于设置需要写文件的帧数，并不是解码帧数。
* **--wtl-format**: 设置输出模式。0：输出 YUV；1：输出 FBC。
* **--read-block-len**: 设置输入缓冲区大小。缺省值为0x80000。

## 示例1

采用 INTERRUPT 模式对 H.264 码流进行解码，采用 yuv420p 格式进行输出。

```shell
bm_test -c 0 -n 1 -m 0 --input wkc_h264_100.264 --cbcr_interleave 0 --instance 1
```

## 示例2

采用 PIC_END 模式对 H.265 码流进行解码，采用 yuv420p 格式进行输出。

```shell
bm_test -c 0 -n 1 -m 2 --stream-type 12 --input wkc_h265_100.265 --cbcr_interleave 0 --instance 1
```

## 示例3

采用 INTERRUPT 模式对 H.264 码流进行解码，采用 nv12 格式进行输出，并且开启4个解码线程。

```shell
bm_test -c 0 -n 1 -m 0 --input wkc_h264_100.264 --cbcr_interleave 1 --nv21 0 --instance 4
```

## 示例4

采用 INTERRUPT 模式对 H.264 码流进行解码，采用 nv12 格式进行输出，并且开启yuv对比。

```shell
bm_test -c 1 -n 1 -m 0 --input wkc_h264_100.264 --cbcr_interleave 1 --nv21 0 \
--ref-yuv wkc_h264_100.yuv --instance 1
```

## 示例5

采用 PIC_END 模式对 H.265 码流进行解码，采用 yuv420p 格式进行输出，并且开启yuv对比，将前10帧写入文件。

```shell
bm_test -c 1 -n 1 -m 2 --stream-type 12 --input wkc_h265_100.265 --cbcr_interleave 0 \
--ref-yuv wkc_h265_100.yuv --instance 1 --write_yuv 10
```

# SOPHGO Video Encoder使用指南

## 简介

Encoder模块主要包括了视频的编码，该模块囊括了所有对用户开放的接口以及其参数详解

## 数据结构说明

### 1. BmVpuEncReturnCodes

```c
typedef enum
{
    BM_VPU_ENC_RETURN_CODE_OK = 0,
    BM_VPU_ENC_RETURN_CODE_ERROR,
    BM_VPU_ENC_RETURN_CODE_INVALID_PARAMS,
    BM_VPU_ENC_RETURN_CODE_INVALID_HANDLE,
    BM_VPU_ENC_RETURN_CODE_INVALID_FRAMEBUFFER,
    BM_VPU_ENC_RETURN_CODE_INSUFFICIENT_FRAMEBUFFERS,
    BM_VPU_ENC_RETURN_CODE_INVALID_STRIDE,
    BM_VPU_ENC_RETURN_CODE_WRONG_CALL_SEQUENCE,
    BM_VPU_ENC_RETURN_CODE_TIMEOUT,
    BM_VPU_ENC_RETURN_CODE_RESEND_FRAME,
    BM_VPU_ENC_RETURN_CODE_ENC_END,
    BM_VPU_ENC_RETURN_CODE_END
} BmVpuEncInitialInfo;
```

**参数说明**

* BM_VPU_ENC_RETURN_CODE_OK - 操作成功完成
* BM_VPU_ENC_RETURN_CODE_ERROR - 通用错误代码，用作其他错误返回代码不匹配时的通用错
* BM_VPU_ENC_RETURN_CODE_INVALID_PARAMS - 输入参数无效
* BM_VPU_ENC_RETURN_CODE_INVALID_HANDLE - VPU 编码器句柄无效，内部错误，可能是库中的错误，请报告此类错误
* BM_VPU_ENC_RETURN_CODE_INVALID_FRAMEBUFFER - 帧缓冲区信息无效，通常发生在将包含无效值的 BmVpuFramebuffer 结构传递给 bmvpu_enc_register_framebuffers() 函数时
* BM_VPU_ENC_RETURN_CODE_INSUFFICIENT_FRAMEBUFFERS - 注册用于编码的帧缓冲区失败，因为未提供足够的帧缓冲区给 bmvpu_enc_register_framebuffers() 函数
* BM_VPU_ENC_RETURN_CODE_INVALID_STRIDE - 步幅值无效，例如帧缓冲区的一个步幅值无效
* BM_VPU_ENC_RETURN_CODE_WRONG_CALL_SEQUENCE - 在不适当的时间调用函数
* BM_VPU_ENC_RETURN_CODE_TIMEOUT - 操作超时
* BM_VPU_ENC_RETURN_CODE_RESEND_FRAME - 重复送帧
* BM_VPU_ENC_RETURN_CODE_ENC_END - 编码结束
* BM_VPU_ENC_RETURN_CODE_END - 编码结束

### 2. BmVpuEncOutputCodes

```c
typedef enum
{
    BM_VPU_ENC_OUTPUT_CODE_INPUT_USED = 1 << 0,
    BM_VPU_ENC_OUTPUT_CODE_ENCODED_FRAME_AVAILABLE = 1 << 1,
    BM_VPU_ENC_OUTPUT_CODE_CONTAINS_HEADER = 1 << 2
} BmVpuEncOutputCodes;
```

**参数说明**

* BM_VPU_ENC_OUTPUT_CODE_INPUT_USED - 表示输入数据已被使用。如果未设置该标志位，则编码器尚未使用输入数据，因此请将其再次输入给编码器，直到此标志位被设置或返回错误
* BM_VPU_ENC_OUTPUT_CODE_ENCODED_FRAME_AVAILABLE - 表示现在有一个完全编码的帧可用。传递给 `bmvpu_enc_encode()` 的 `encoded_frame` 参数包含有关此帧的信息
* BM_VPU_ENC_OUTPUT_CODE_CONTAINS_HEADER - 表示编码帧中的数据还包含头信息，如 h.264 的 SPS/PSS。头信息始终放置在编码数据的开头，如果未设置 `BM_VPU_ENC_OUTPUT_CODE_ENCODED_FRAME_AVAILABLE`，则该标志位不会被设置

### 3. BmVpuEncHeaderDataTypes

```c
typedef enum
{
    BM_VPU_ENC_HEADER_DATA_TYPE_VPS_RBSP = 0,
    BM_VPU_ENC_HEADER_DATA_TYPE_SPS_RBSP,
    BM_VPU_ENC_HEADER_DATA_TYPE_PPS_RBSP
} BmVpuEncHeaderDataTypes;
```

**参数说明**

* BM_VPU_ENC_HEADER_DATA_TYPE_VPS_RBSP - 视频参数集 (VPS) 的 RBSP（Raw Byte Sequence Payload）数据类型
* BM_VPU_ENC_HEADER_DATA_TYPE_SPS_RBSP - 序列参数集 (SPS) 的 RBSP 数据类型
* BM_VPU_ENC_HEADER_DATA_TYPE_PPS_RBSP - 图像参数集 (PPS) 的 RBSP 数据类型

### 4. BmVpuCodecFormat

```c
typedef enum
{
    BM_VPU_CODEC_FORMAT_H264 = 0,
    BM_VPU_CODEC_FORMAT_H265
} BmVpuCodecFormat;
```

**参数说明**

* BM_VPU_CODEC_FORMAT_H264 - 编码类型 h264
* BM_VPU_CODEC_FORMAT_H265 - 编码类型 h265

### 5. BmVpuEncPixFormat

```c
typedef enum
{
    BM_VPU_ENC_PIX_FORMAT_YUV420P = 0,
    BM_VPU_ENC_PIX_FORMAT_YUV422P   = 1,
    BM_VPU_ENC_PIX_FORMAT_YUV444P   = 3,
    BM_VPU_ENC_PIX_FORMAT_YUV400 = 4,
    BM_VPU_ENC_PIX_FORMAT_NV12   = 5,
    BM_VPU_ENC_PIX_FORMAT_NV16 = 6,
    BM_VPU_ENC_PIX_FORMAT_NV24 = 7,
    BM_VPU_ENC_PIX_FORMAT_NV21 = 8
} BmVpuEncPixFormat;
```

**参数说明**

* 编码器输入yuv格式 - 目前仅支持nv12，nv21，yuv420p

### 6. BMVpuEncGopPreset

```c
typedef enum
{
    BM_VPU_ENC_GOP_PRESET_ALL_I = 1,
    BM_VPU_ENC_GOP_PRESET_IPP   = 2,
    BM_VPU_ENC_GOP_PRESET_IBBB   = 3,
    BM_VPU_ENC_GOP_PRESET_IBPBP = 4,
    BM_VPU_ENC_GOP_PRESET_IBBBP   = 5,
    BM_VPU_ENC_GOP_PRESET_IPPPP = 6,
    BM_VPU_ENC_GOP_PRESET_IBBBB = 7,
    BM_VPU_ENC_GOP_PRESET_RA_IB = 8
} BMVpuEncGopPreset;
```

**参数说明**

* BM_VPU_ENC_GOP_PRESET_ALL_I - 全I帧模式 gopsize=1
* BM_VPU_ENC_GOP_PRESET_IPP - 全IP帧模式 gopsize=1
* BM_VPU_ENC_GOP_PRESET_IBBB - 全IB帧模式 gopsize=1
* BM_VPU_ENC_GOP_PRESET_IBPBP - 全IBP帧模式 gopsize=2
* BM_VPU_ENC_GOP_PRESET_IBBBP - 全IBP帧模式 gopsize=4
* BM_VPU_ENC_GOP_PRESET_IPPPP - 全IP帧模式 gopsize=4
* BM_VPU_ENC_GOP_PRESET_IBBBB - 全IB帧模式 gopsize=4
* BM_VPU_ENC_GOP_PRESET_RA_IB - Random IB帧模式 gopsize=8

### 7. BMVpuEncMode

```c
typedef enum
{
    BM_VPU_ENC_CUSTOM_MODE = 0,
    BM_VPU_ENC_RECOMMENDED_MODE   = 1,
    BM_VPU_ENC_BOOST_MODE   = 2,
    BM_VPU_ENC_FAST_MODE = 3
} BMVpuEncMode;
```

**参数说明**

* BM_VPU_ENC_CUSTOM_MODE - 自定义模式
* BM_VPU_ENC_RECOMMENDED_MODE - 推荐模式（慢编码速度，最高画质）
* BM_VPU_ENC_BOOST_MODE - 提升模式（正常编码速度，正常画质）
* BM_VPU_ENC_FAST_MODE - 快速模式（高编码速度，低画质）

### 8. BmVpuMappingFlags

```c
typedef enum
{
    BM_VPU_MAPPING_FLAG_WRITE = 1 << 0,
    BM_VPU_MAPPING_FLAG_READ   = 1 << 1
} BmVpuMappingFlags;
```

**参数说明**

* BM_VPU_MAPPING_FLAG_WRITE - 可写权限标志
* BM_VPU_MAPPING_FLAG_READ - 可读权限标志

### 9. BmVpuEncH264Params

```c
typedef struct
{
    int enable_transform8x8;
} BmVpuEncH264Params;
```

**参数说明**

* enable_transform8x8 - 启用 8x8 帧内预测和 8x8 变换。默认值为 1

### 10. BmVpuEncH265Params

```c
typedef struct
{
    int enable_tmvp;
    int enable_wpp;
    int enable_sao;
    int enable_strong_intra_smoothing;
    int enable_intra_trans_skip;
    int enable_intraNxN;
} BmVpuEncH265Params;
```

**参数说明**

* enable_tmvp - 启用时域运动矢量预测。默认值为 1
* enable_wpp - 启用线性缓冲区模式的波前并行处理。默认值为 0
* enable_sao - 如果设置为 1，则启用 SAO；如果设置为 0，则禁用。默认值为 1
* enable_strong_intra_smoothing - 启用对带有少量 AC 系数的区域进行强烈的帧内平滑，以防止伪影。默认值为 1
* enable_intra_trans_skip - 启用帧内 CU 的变换跳过。默认值为 0
* enable_intraNxN - 启用帧内 NxN PUs。默认值为 1

### 11. BmVpuEncOpenParams

```c
typedef struct
{
    BmVpuCodecFormat codec_format;
    BmVpuEncPixFormat color_format;
    uint32_t frame_width;
    uint32_t frame_height;
    uint32_t timebase_num;
    uint32_t timebase_den;
    uint32_t fps_num;
    uint32_t fps_den;
    int64_t  bitrate;
    uint64_t vbv_buffer_size;
    int cqp;
    BMVpuEncMode enc_mode;
    int max_num_merge;
    int enable_constrained_intra_prediction;
    int enable_wp;
    int disable_deblocking;
    int offset_tc;
    int offset_beta;
    int enable_cross_slice_boundary;
    int enable_nr;
    union
    {
        BmVpuEncH264Params h264_params;
        BmVpuEncH265Params h265_params;
    };
    int soc_idx;
    BMVpuEncGopPreset gop_preset;
    int intra_period;
    int bg_detection;
    int mb_rc;
    int delta_qp;

    /* minimum QP for rate control
    * Default value is 8 */
    int min_qp;
    /* maximum QP for rate control
    * Default value is 51 */
    int max_qp;

    /* roi encoding flag
    * Default value is 0 */
    int roi_enable;
    /* set cmd queue depath
      * Default value is 4
      * the value must 1 <= value <= 4*/
    int cmd_queue_depth;

    int timeout;
    int timeout_count;

    BmVpuEncBufferAllocFunc buffer_alloc_func;
    BmVpuEncBufferFreeFunc buffer_free_func;
    void *buffer_context;
} BmVpuEncOpenParams;
```

**参数说明**

* BmVpuCodecFormat codec_format - 指定要生成的编码数据的编码格式
* BmVpuEncPixFormat color_format - 指定传入帧使用的图像格式
* uint32_t frame_width - 传入帧的宽度（以像素为单位），无需对齐
* uint32_t frame_height - 传入帧的高度（以像素为单位），无需对齐
* uint32_t timebase_num - 时间基数，以分数形式给出
* uint32_t timebase_den - 时间分母，以分数形式给出
* uint32_t fps_num - 帧率，以分数形式给出
* uint32_t timebase_den - 帧率分母，以分数形式给出
* int64_t bitrate - 比特率（以 bps 为单位）。如果设置为 0，则禁用码率控制，而使用常量质量模式。默认值为 100000
* int cqp - 常量质量模式的量化参数
* int enc_mode - 0:自定义模式 1:推荐的编码器参数（慢编码速度，最高画质） 2:提升模式（正常编码速度，正常画质） 3:快速模式（高编码速度，低画质）
* int max_num_merge - RDO 中的合并候选数（1 或 2）。1：提高编码性能，2：提高编码图像的质量。默认值为 2
* int enable_constrained_intra_prediction - 启用受限帧内预测。如果设置为 1，则启用；如果设置为 0，则禁用。默认值为 0
* int enable_wp - 启用加权预测。默认值为 1
* int disable_deblocking - 如果设置为 1，则禁用去块滤波器。如果设置为 0，则保持启用。默认值为 0
* int offset_tc - deblocking 滤波器的 Alpha/Tc 偏移。默认值为 0
* int offset_beta - deblocking 滤波器的 Beta 偏移。默认值为 0
* int enable_cross_slice_boundary - 启用帧内循环滤波中的跨切片边界滤波。默认值为 0
* int enable_nr - 启用帧内循环滤波中的跨切片边界滤波。默认值为 0
* int h264_params - H.264 编码器参数。(union，从 *h264_params* 和 *h265_params* 中选择一个)
* int h265_params - H.265 编码器参数。(union，从 *h264_params* 和 *h265_params* 中选择一个)
* int soc_idx - 仅用于 PCIe 模式。对于 SOC 模式，此值必须为 0。默认值为 0。
* int gop_preset - 1: all I, all Intra, gopsize = 1 2: I-P-P, consecutive P, cyclic gopsize = 1 3: I-B-B-B, consecutive B, cyclic gopsize = 1 4: I-B-P-B-P, gopsize = 2 5: I-B-B-B-P, gopsize = 4 6: I-P-P-P-P, consecutive P, cyclic gopsize = 4 7: I-B-B-B-B, consecutive B, cyclic gopsize = 4 8: Random Access, I-B-B-B-B-B-B-B-B, cyclic gopsize = 8 低延迟情况为 1、2、3、6、7。默认值为 5
* int intra_period - GOP 大小内的帧内图片周期。默认值为 28
* int bg_detection - 启用背景检测。默认值为 0
* int mb_rc - 启用 MB 级/CU 级码率控制。默认值为 1
* int delta_qp - 码率控制的最大 delta QP。默认值为 5
* int min_qp - 码率控制的最小 QP。默认值为 8
* int max_qp - 码率控制的最大 QP。默认值为 51
* int roi_enable - ROI 编码标志。默认值为 0
* int cmd_queue_depth - 编码队列深度，可提升编码器性能，同时需要消耗一定的物理内存
* int timeout - 编码超时时间，默认为1000ms（即VPU_WAIT_TIMEOUT）(bm1688为异步接口，无需设置timeout)
* int timeout_count - 编码超时重试次数，默认为40（即VPU_MAX_TIMEOUT_COUNTS）(bm1688为异步接口，无需设置timeout_count)
* BmVpuEncBufferAllocFunc buffer_alloc_func - 缓冲区内存分配函数接口
* BmVpuEncBufferFreeFunc buffer_free_func - 缓冲区内存释放函数接口
* void* buffer_context - 缓冲区上下文信息

### 12. BmVpuEncInitialInfo

```c
typedef struct
{
    uint32_t min_num_rec_fb;
    uint32_t min_num_src_fb;
    uint32_t framebuffer_alignment;
    BmVpuFbInfo rec_fb;
    BmVpuFbInfo src_fb;
} BmVpuEncInitialInfo;
```

**参数说明**

* min_num_src_fb - 最小推荐帧缓冲区数量，分配少于此数量可能会影响编码质量
* rec_fb - 输入 YUV 数据帧的最小数量，分配少于此数量可能会影响编码
* framebuffer_alignment - 物理帧缓冲区地址的对齐要求
* rec_fb - 用于重建的帧缓冲区大小信息。包括宽度、高度等信息
* src_fb - 输入 YUV 数据的宽高信息

### 13. BmCustomMapOpt

```c
typedef struct
{
    int roiAvgQp;
    int customRoiMapEnable;
    int customLambdaMapEnable;
    int customModeMapEnable;
    int customCoefDropEnable;
    bmvpu_phys_addr_t addrCustomMap;
} BmCustomMapOpt;
```

**参数说明**

* roiAvgQp - ROI 映射的平均 QP
* customRoiMapEnable - 是否开启 ROI 映射
* customLambdaMapEnable - 是否开启 Lambda 映射
* customModeMapEnable - 是否指定 CTU 使用帧间编码，否则跳过
* customCoefDropEnable - 对于每个 CTU，是否设置 TQ 系数为全0，系数全0的 CTU 将被丢弃
* addrCustomMap - 自定义映射缓冲区的起始地址

# 14. BmVpuEncParams

```c
typedef struct
{
    int skip_frame;
    int forcePicTypeEnable;
    int forcePicType;
    BmVpuEncAcquireOutputBuffer acquire_output_buffer;
    BmVpuEncFinishOutputBuffer finish_output_buffer;
    void* output_buffer_context;
    BmCustomMapOpt* customMapOpt;
} BmVpuEncParams;
```

**参数说明**

* **skip_frame**  
  默认值为 0，禁用跳帧生成。如果设置为 1，则 VPU 忽略给定的原始帧，而生成一个"跳帧"，它是前一帧的复制。这个跳帧被编码为 P 帧

* **forcePicTypeEnable**  
  是否强制指定编码帧类

* **forcePicType**  
  强制指定的编码帧类型（I帧、P帧、B帧、IDR帧、CRA帧），只有当 *forcePicTypeEnable* 为1时有效

* **acquire_output_buffer**  
  用于获取输出缓冲区的函数

* **finish_output_buffer**  
  用于释放输出缓冲区的函数

* **output_buffer_context**  
  传递给上述函数的用户提供的值

* **customMapOpt**  
  指向自定义映射选项的指针

# 15. BmVpuEncoder

```c
/* BM VPU Encoder structure. */
typedef struct
{
    void* handle;

    int soc_idx; /* The index of Sophon SoC.
                  * For PCIE mode, please refer to the number at /dev/bm-sophonxx.
                  * For SOC mode, set it to zero. */
    int core_idx; /* unified index for vpu encoder cores at all Sophon SoCs */

    BmVpuCodecFormat codec_format;
    BmVpuEncPixFormat pix_format;

    uint32_t frame_width;
    uint32_t frame_height;

    uint32_t fps_n;
    uint32_t fps_d;

    int first_frame;

    int rc_enable;
    /* constant qp when rc is disabled */
    int cqp;

    /* DMA buffer for working */
    BmVpuEncDMABuffer*   work_dmabuffer;

    /* DMA buffer for bitstream */
    BmVpuEncDMABuffer* bs_dmabuffer;

    unsigned long long bs_virt_addr;
    bmvpu_phys_addr_t bs_phys_addr;

    /* DMA buffer for frame data */
    uint32_t      num_framebuffers;
    void * /*VpuFrameBuffer**/   internal_framebuffers;
    BmVpuFramebuffer* framebuffers;

    /* TODO change all as the parameters of bmvpu_enc_register_framebuffers() */
    /* DMA buffer for colMV */
    BmVpuEncDMABuffer*   buffer_mv;

    /* DMA buffer for FBC luma table */
    BmVpuEncDMABuffer*   buffer_fbc_y_tbl;

    /* DMA buffer for FBC chroma table */
    BmVpuEncDMABuffer*   buffer_fbc_c_tbl;

    /* Sum-sampled DMA buffer for ME */
    BmVpuEncDMABuffer*   buffer_sub_sam;

    uint8_t* headers_rbsp;
    size_t   headers_rbsp_size;

    BmVpuEncInitialInfo initial_info;

    int timeout;
    int timeout_count;

    /* internal use */
    void *video_enc_ctx;
} BmVpuEncoder;
```

**参数说明**

* **handle**  
  编码器句柄

* **soc_idx**  
  Sophon SoC 的索引。对于 PCIE 模式，请参考 /dev/bm-sophonxx 中的编号。对于 SOC 模式，请将其设置为零

* **core_idx**  
  所有 Sophon SoC 中 VPU 编码器core的统一索引

* **codec_format**  
  编码器使用的视频编解码格式

* **color_format**  
  传入帧使用的图像格式

* **frame_width**  
  传入帧的宽度（以像素为单位）

* **frame_height**  
  传入帧的高度（以像素为单位）

* **fps_n**  
  帧率的分子

* **fps_d**  
  帧率的分母

* **first_frame**  
  是否为第一帧

* **rc_enable**  
  是否启用码率控制

* **cqp**  
  在禁用码率控制时，使用恒定的量化参数 QP

* **work_dmabuffer**  
  用于编码器工作的 DMA 缓冲区

* **bs_dmabuffer**  
  用于存储码流的 DMA 缓冲区

* **bs_virt_addr**  
  码流的虚拟地址

* **bs_phys_addr**  
  码流的物理地址

* **num_framebuffers**  
  帧缓冲区的数量

* **internal_framebuffers**  
  编码器内部的帧缓冲区

* **framebuffers**  
  帧缓冲区

* **buffer_mv**  
  用于存储运动矢量的 DMA 缓冲区

* **buffer_fbc_y_tbl**  
  用于存储 FBC 亮度表的 DMA 缓冲区

* **buffer_fbc_c_tbl**  
  用于存储 FBC 色度表的 DMA 缓冲区

* **buffer_sub_sam**  
  用于 ME 的子采样 DMA 缓冲区

* **headers_rbsp**  
  帧头 RBSP 数据

* **headers_rbsp_size**  
  帧头 RBSP 数据的大小

* **initial_info**  
  编码器的初始信息

* **timeout**  
  编码超时时间，默认为1000ms（即VPU_WAIT_TIMEOUT）

* **timeout_count**  
  编码超时重试次数，默认为40（即VPU_MAX_TIMEOUT_COUNTS）

* **video_enc_ctx**  
  编码上下文信息，内部使用

# 16. BmVpuFbInfo

```c
typedef struct {
    int width;
    int height;
    int y_stride;
    int c_stride;
    int y_size;
    int c_size;
    int size;
} BmVpuFbInfo;
```

**参数说明**

* **width**  
  帧的宽度，按照 VPU 要求的 16 像素边界对齐

* **height**  
  帧的高度，按照 VPU 要求的 16 像素边界对齐

* **y_stride**  
  对齐后的 Y 分量的跨距大小，以字节为单位

* **c_stride**  
  对齐后的 Cb 和 Cr 分量的跨距大小，以字节为单位（可选）

* **y_size**  
  Y 分量的 DMA 缓冲区大小，以字节为单位

* **c_size**  
  Cb 和 Cr 分量的 DMA 缓冲区大小，以字节为单位

* **size**  
  帧缓冲区 DMA 缓冲区的总大小，以字节为单位。这个值包括所有通道的大小

# 17. BmVpuEncodedFrame

```c
typedef struct
{
    uint8_t *data;
    size_t data_size;
    BmVpuFrameType frame_type;
    void *acquired_handle;
    void *context;
    uint64_t pts;
    uint64_t dts;
    int src_idx;
    bmvpu_phys_addr_t u64CustomMapPhyAddr;
    int avg_ctu_qp;
} BmVpuEncodedFrame;
```

**参数说明**

* **uint8_t \*data**  
  在解码时，data 必须指向包含码流数据的内存块，编码器不使用

* **size_t data_size**  
  编码数据的大小。在编码时，由编码器设置，表示获取的输出块的大小，以字节为单位

* **BmVpuFrameType frame_type**  
  编码帧的帧类型（I、P、B 等）。由编码器填充。仅由编码器使用

* **void* acquired_handle**  
  在编码时由用户定义的 **acquire_output_buffer** 函数生成的句柄。仅由编码器使用

* **void* context**  
  用户定义的指针。编码器不会更改此值。这个指针和相应原始帧的指针将具有相同的值，在编码器中传递

* **uint64_t pts**  
  用户定义的显示时间戳（Presentation Timestamp）。与 *context* 指针一样，编码器只是将其传递到关联的原始帧，并不实际更改其值

* **uint64_t dts**  
  用户定义的解码时间戳（Decoding Timestamp）。与 *pts* 指针一样，编码器只是将其传递到关联的原始帧，并不实际更改其值

* **int src_idx**  
  原始帧的索引

* **bmvpu_phys_addr_t u64CustomMapPhyAddr**  
  用户自定义映射选项的起始地址

* **int avg_ctu_qp**  
  平均 CTU QP（Quantization Parameter）

# 18. BmVpuEncDMABuffer

```c
typedef struct
{
    unsigned int  size;
    uint64_t      phys_addr;
    uint64_t      virt_addr;
    int           enable_cache;
    int           dmabuf_fd;
} BmVpuEncDMABuffer;
```

**参数说明**

* **size**  
  物理内存的大小

* **phys_addr**  
  物理内存的地址

* **virt_addr**  
  物理内存mmap后的虚拟地址

* **enable_cache**  
  是否开启cache

* **dmabuf_fd**  
  文件句柄，用户不可以修改直接透传即可

# 19. BmVpuRawFrame

```c
typedef struct
{
    BmVpuFramebuffer *framebuffer;
    void *context;
    uint64_t pts;
    uint64_t dts;
} BmVpuRawFrame;
```

**参数说明**

* **BmVpuFramebuffer \*framebuffer**  
  原始帧的帧缓冲区

* **void* context**  
  用户定义的指针。编码器不会更改此值。这个指针和相应编码帧的指针将具有相同的值，在编码器中传递

* **uint64_t pts**  
  用户定义的显示时间戳（Presentation Timestamp）。与 *context* 指针一样，编码器只是将其传递到关联的编码帧，并不实际更改其值

* **uint64_t dts**  
  用户定义的解码时间戳（Decoding Timestamp）。与 *pts* 指针一样，编码器只是将其传递到关联的编码帧，并不实际更改其值

# 20. BmVpuFramebuffer

```c
typedef struct
{
    BmVpuEncDMABuffer *dma_buffer;
    int          myIndex;
    unsigned int y_stride;
    unsigned int cbcr_stride;
    unsigned int width;
    unsigned int height;
    size_t y_offset;
    size_t cb_offset;
    size_t cr_offset;
    int already_marked;
    void *internal;
    void *context;
} BmVpuFramebuffer;
```

**参数说明**

* **BmVpuEncDMABuffer \*dma_buffer**  
  保存YUV数据的物理内存

* **int myIndex**  
  YUV 索引，用户设置，用于释放 YUV 数据

* **unsigned int y_stride**  
  Y 通道对齐后的大小

* **unsigned int cbcr_stride**  
  UV 通道对齐后的大小

* **unsigned int width**  
  编码 YUV 图像的宽

* **unsigned int height**  
  编码 YUV 图像的高

* **size_t y_offset**  
  Y 通道 offset。相对于缓冲区起始位置，指定每个分量的起始偏移量。以字节为单位指定

* **size_t cb_offset**  
  U 通道 offset

* **size_t cr_offset**  
  V 通道 offset

* **int already_marked**  
  如果帧缓冲区已在编码器中标记为已使用，则设置为 1。仅供内部使用。不要从外部读取或写入

* **void* internal**  
  内部实现定义的数据。不要修改

* **void* context**  
  用户定义的指针，编码器不会修改此值。用法由用户决定，例如，可以用于标识在编码器中包含该帧的帧缓冲区的序号

# API扩展说明

## 1. char const * bmvpu_enc_error_string(BmVpuEncReturnCodes code)

| 字段 | 说明 |
|------|------|
| 功能 | 返回编码错误码的具体描述 |
| 输入参数 | `BmVpuEncReturnCodes code` 编码错误码 |

## 2. int bmvpu_enc_get_core_idx(int soc_idx)

| 字段 | 说明 |
|------|------|
| 功能 | 在指定的Sophon SoC上，获取VPU编码器core的唯一索引 |
| 输入参数 | `int soc_idx` 设备索引号 |

## 3. int bmvpu_enc_load(int soc_idx)

| 字段 | 说明 |
|------|------|
| 功能 | 加载Sophon设备上的视频处理单元（VPU）的编码模块 |
| 输入参数 | `int soc_idx` 设备索引号 |
| 函数说明 | unload()和load()的调用次数要一致。在对编码器执行任何其他操作之前，必须先加载(load)编码器。同样，在完成所有编码器活动之前，不得卸载(unload)编码器，包括打开编码器实例 |

## 4. int bmvpu_enc_unload(int soc_idx)

| 字段 | 说明 |
|------|------|
| 功能 | 卸载(unload)编码器 |
| 输入参数 | `int soc_idx` 设备索引号 |

## 5. void bmvpu_enc_get_bitstream_buffer_info(size_t *size, uint32_t *alignment)

| 字段 | 说明 |
|------|------|
| 功能 | 该函数得到编码器所需的bitstream buffer的大小(size)和所需要的alignment值 |
| 输入参数 | size_t *size - 码流缓冲区所需的物理内存块的大小<br>uint32_t *alignment - 码流缓冲区所需的物理内存块的对齐方式 |
| 返回值 | 返回编码器的码流缓冲区所需的物理内存块的对齐方式和大小 |
| 函数说明 | 需要在bmvpu_enc_open之前调用<br>用户必须分配至少此大小的 DMA 缓冲区，并且必须根据对齐值对其物理地址进行对齐 |

## 6. void bmvpu_enc_set_default_open_params(BmVpuEncOpenParams *open_params, BmVpuCodecFormat codec_format)

| 字段 | 说明 |
|------|------|
| 功能 | 设置编码器的默认变量，用于编码器初始化时传递参数 |
| 输入参数 | BmVpuEncOpenParams *open_params - 用于返回编码器的参数<br>BmVpuCodecFormat codec_format - 编码器和解码器的选择,h264和h265 |
| 返回值 | 无 |
| 函数说明 | 在bmvpu_enc_open之前调用<br>如果调用方只想修改几个成员变量（或者不做修改），可以调用此函数 |

## 7. int bmvpu_fill_framebuffer_params(BmVpuFramebuffer *fb, BmVpuFbInfo *info, bm_device_mem_t *fb_dma_buffer, int fb_id, void *context)

| 字段 | 说明 |
|------|------|
| 功能 | 根据bmvpufbinfo获取的数据填充缓冲区结构体BmVpuFramebuffer结构体的字段,同时也设置了指定的 DMA 缓冲区和上下文指针 |
| 输入参数 | BmVpuFramebuffer *fb - 一个实际的缓冲区,通过接收info中的信息来设置缓冲区,例如缓冲区索引、指针和帧的宽高以及Y、U、V三分量在帧缓冲区中的偏移等<br>BmVpuFbInfo *info - 存放缓冲区设置的相关信息<br>bm_device_mem_t *fb_dma_buffer - 指针指向了实际的 DMA 缓冲区的起始地址,通过这个指针,程序可以直接访问和操作 DMA 缓冲区中的数据,而无需通过中央处理器进行复制或处理<br>int fb_id - 缓冲区索引<br>void *context - 上下文信息 |
| 返回值 | BM_SUCESS - 分配成功 else - 分配失败 |
| 函数说明 | 无 |

## 8. int bmvpu_enc_open(BmVpuEncoder **encoder, BmVpuEncOpenParams *open_params, BmVpuDMABuffer *bs_dmabuffer, BmVpuEncInitialInfo *initial_info)

| 字段 | 说明 |
|------|------|
| 功能 | 打开一个新的编码器实例,设置编码器参数并开始接收视频帧 |
| 输入参数 | BmVpuEncOpenParams *open_params - 编码器各项参数<br>BmVpuEncoder **encoder - 指向编码器实例的二级指针，接收编码器的属性和视频帧的部分设置, 例如设备 id、缓冲区设置和帧率、宽高等<br>BmVpuDMABuffer *bs_dmabuffer - 指向码流缓冲区的指针，使用之前已经分配的码流缓冲区<br>BmVpuEncInitialInfo *initial_info - 编码器的初始化信息，返回给用户编码器需要的帧缓冲区最小个数和大小 |
| 返回值 | BM_SUCESS - 打开成功 else - 打开失败 |
| 函数说明 | 调用前需要确保BmVpuEncOpenParams 和 BmVpuDMABuffer 不为空 |

## 9. int bmvpu_enc_close(BmVpuEncoder *encoder)

| 字段 | 说明 |
|------|------|
| 功能 | 关闭编码器实例 |
| 输入参数 | `BmVpuEncoder *encoder` - 视频编码器实例 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 多次尝试关闭同一实例会导致未定义的行为 |

## 10. int bmvpu_enc_encode(BmVpuEncoder *encoder, BmVpuRawFrame const *raw_frame, BmVpuEncodedFrame *encoded_frame, BmVpuEncParams *encoding_params, uint32_t *output_code)

| 字段 | 说明 |
|------|------|
| 功能 | 使用给定的编码参数对给定的原始输入帧进行编码。encoded_frame 填充有关于所得到的编码输出帧的信息<br>bm1688 编码使用异步接口，不支持此接口 |
| 输入参数 | `BmVpuEncoder *encoder` - 视频编码器实例<br>`BmVpuRawFrame const *raw_frame` - 原始视频帧，包括帧数据、时间戳等<br>`BmVpuEncodedFrame *encoded_frame` - 编码后的视频帧，包括帧数据、帧类型、时间戳等<br>`BmVpuEncParams *encoding_params` - 用于编码的参数<br>`uint32_t *output_code` - 返回输出状态代码 |
| 返回值 | BM_SUCESS - 编码成功 else - 编码失败 |
| 函数说明 | 编码的帧数据本身被存储在由用户提供的函数（在 encoding_params 中被设置为 acquire_output_buffer 和 finish_output_buffer 函数指针）分配的缓冲区中 |

## 11. int bmvpu_enc_send_frame(BmVpuEncoder *encoder, BmVpuRawFrame const *raw_frame, BmVpuEncParams *encoding_params)

| 字段 | 说明 |
|------|------|
| 功能 | 使用给定的编码参数对给定的原始输入帧进行编码<br>bm1688 新增接口 |
| 输入参数 | `BmVpuEncoder *encoder` - 视频编码器实例<br>`BmVpuRawFrame const *raw_frame` - 原始视频帧，包括帧数据、时间戳等<br>`BmVpuEncParams *encoding_params` - 用于编码的参数 |
| 返回值 | BM_SUCESS - 送数据成功 else - 送数据失败 |

## 12. int bmvpu_enc_get_stream(BmVpuEncoder *encoder, BmVpuEncodedFrame *encoded_frame, BmVpuEncParams *encoding_params)

| 字段 | 说明 |
|------|------|
| 功能 | 获取编码后的码流数据，数据存在 encoded_frame中<br>bm1688 新增接口 |
| 输入参数 | `BmVpuEncoder *encoder` - 视频编码器实例<br>`BmVpuEncodedFrame *encoded_frame` - 编码后的视频帧，包括帧数据、帧类型、时间戳等<br>`BmVpuEncParams *encoding_params` - 用于编码的参数 |
| 返回值 | BM_SUCESS - 获取成功 else - 获取失败 |
| 函数说明 | 编码的帧数据本身被存储在由用户提供的函数（在 encoding_params 中被设置为 acquire_output_buffer 和 finish_output_buffer 函数指针）分配的缓冲区中 |

## 13. int bmvpu_enc_dma_buffer_allocate(int vpu_core_idx, BmVpuEncDMABuffer *buf, unsigned int size)

| 字段 | 说明 |
|------|------|
| 功能 | 根据用户指定的size分配设备内存 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` - 输出参数，函数执行后，将会填充该结构体的 phys_addr、size、enable_cache 成员变量<br>`unsigned int size`- 输入参数，以字节为单位，指定需要的缓冲区大小 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 14. int bmvpu_enc_dma_buffer_deallocate(int vpu_core_idx, BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 释放由 **bmvpu_enc_dma_buffer_allocate** 函数分配的设备内存 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` - 输出参数，函数执行后，将会填充该结构体的 phys_addr、size、enable_cache 成员变量 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 15. int bmvpu_enc_dma_buffer_attach(int vpu_core_idx, uint64_t paddr, unsigned int size)

| 字段 | 说明 |
|------|------|
| 功能 | 将用户通过 **bmvpu_enc_dma_buffer_allocate** 函数以外的其它方式申请的设备内存地址绑定至编码器 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`uint64_t paddr` - 输入参数，由用户通过 **bmvpu_enc_dma_buffer_allocate** 函数以外的其它方式申请的设备内存地址<br>`unsigned int size` 输入参数，该块设备内存大小(byte) |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 16. int bmvpu_enc_dma_buffer_deattach(int vpu_core_idx, uint64_t paddr, unsigned int size)

| 字段 | 说明 |
|------|------|
| 功能 | 将用户通过 **bmvpu_enc_dma_buffer_attach** 函数绑定的设备内存解绑 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`uint64_t paddr` - 输入参数，由用户通过 **bmvpu_enc_dma_buffer_allocate** 函数以外的其它方式申请的设备内存地址<br>`unsigned int size` 输入参数，该块设备内存大小(byte) |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 17. int bmvpu_dma_buffer_map(int vpu_core_idx, BmVpuEncDMABuffer *buf, int port_flag)

| 字段 | 说明 |
|------|------|
| 功能 | 将对应core上申请的设备内存映射到系统内存 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` - 输入参数，指定设备内存的地址、大小等信息<br>`int port_flag` 输入参数，配置 **mmap** 内存可读(BM_VPU_MAPPING_FLAG_READ)或可写(BM_VPU_MAPPING_FLAG_WRITE) |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 18. int bmvpu_dma_buffer_unmap(int vpu_core_idx, BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 对某个core上映射过的设备内存解除映射 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` - 输入参数，指定设备内存的地址、大小等信息 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 19. int bmvpu_enc_dma_buffer_flush(int vpu_core_idx, BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 对已分配的设备内存进行flush操作 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` -  输入参数，调用前用户至少要填充该结构体的 phys_addr、size 成员变量 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 20. int bmvpu_enc_dma_buffer_invalidate(int vpu_core_idx, BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 对已分配的设备内存进行invalid操作 |
| 输入参数 | `int vpu_core_idx` - 输入参数，指定编码器所在core的索引<br>`BmVpuEncDMABuffer *buf` -  输入参数，调用前用户至少要填充该结构体的 phys_addr、size 成员变量 |
| 返回值 | BM_SUCESS - 关闭成功 else - 关闭失败 |
| 函数说明 | 无 |

## 21. uint64_t bmvpu_enc_dma_buffer_get_physical_address(BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 返回已分配的设备内存的地址 |
| 输入参数 | `BmVpuEncDMABuffer *buf` -  输入参数，已分配的设备内存 |
| 返回值 | 已分配的设备内存的物理地址 |
| 函数说明 | 无 |

## 22. unsigned int bmvpu_enc_dma_buffer_get_size(BmVpuEncDMABuffer *buf)

| 字段 | 说明 |
|------|------|
| 功能 | 返回已分配的设备内存的大小 |
| 输入参数 | `BmVpuEncDMABuffer *buf` -  输入参数 |
| 返回值 | 已分配的设备内存的大小 |
| 函数说明 | 无 |

# 21. int bmvpu_enc_upload_data(int vpu_core_idx, const uint8_t* host_va, int host_stride, uint64_t vpu_pa, int vpu_stride, int width, int height)

| 功能 | 向使用 **bmvpu_enc_dma_buffer_allocate()** 分配的设备内存地址传输数据 |
|------|----------------------------------------------------------------------|
| 输入参数 | int vpu_core_idx - 输入参数，指定编码器所在core的索引<br>const uint8_t \*host_va - 输入参数, 待传输数据的host端虚拟地址<br>int host_stride - 输入参数，host端的数据跨距<br>uint64_t vpu_pa - 输入参数，传输数据的目标物理地址<br>int vpu_stride - 输入参数，device端的数据跨距<br>int width - 输入参数，数据宽度<br>int height - 输入参数，数据高度 |
| 返回值 | BM_SUCESS - 成功 else - 失败 |
| 函数说明 | 仅支持PCie模式 |

# 22. int bmvpu_enc_download_data(int vpu_core_idx, uint8_t* host_va, int host_stride, uint64_t vpu_pa, int vpu_stride, int width, int height)

| 功能 | 从 **bmvpu_enc_dma_buffer_allocate()** 分配的设备内存地址向host端传输数据 |
|------|-------------------------------------------------------------------------|
| 输入参数 | int vpu_core_idx - 输入参数，指定编码器所在core的索引<br>const uint8_t \*host_va - 输入参数, 待传输数据的host端虚拟地址<br>int host_stride - 输入参数，host端的数据跨距<br>uint64_t vpu_pa - 输入参数，传输数据的目标物理地址<br>int vpu_stride - 输入参数，device端的数据跨距<br>int width - 输入参数，数据宽度<br>int height - 输入参数，数据高度 |
| 返回值 | BM_SUCESS - 成功 else - 失败 |
| 函数说明 | 仅支持PCie模式 |

# SOPHGO多媒体框架介绍

## 简介

本文档所述多媒体框架的描述对象为算能的算丰BM168x产品系列，目前该产品系列包括BM1682、BM1684、BM1684X、BM1688四款。其中1）BM1682没有视频编码硬件单元，因此本文中所有关于视频硬件编码的内容均只针对BM1684及以上版本产品而言（BM1684、BM1684X、BM1688）；2）本文中提到的Opencv中的bmcv名字空间下的函数，仅针对BM1684及以上版本产品而言（BM1684、BM1684X、BM1688）。

本文档所述多媒体框架的覆盖范围包括BM168x产品系列中的视频解码VPU模块、视频编码VPU模块、图像编码JPU模块、图像解码JPU模块、图像处理模块VPSS。这些模块的功能封装到FFMPEG和OPENCV开源框架中，客户可以根据自己的开发习惯，选择FFMPEG API或者OPENCV API。其中图像处理模块，我们还单独提供了算能自有的BMCV API底层接口，这部分接口有专门的文档介绍，可以参考《BMCV User Guide》，本文档不再详细介绍，仅介绍这三套API之间的层级关系及如何互相转换。

OPENCV，FFMPEG和BMCV这三套API在功能上是子集的关系，但有少部分不能全部包含，下面的括号中进行了特别标注。

1）BMCV API包含了所有能用硬件加速的图像处理加速接口（这里图像处理硬件加速，包括硬件图像处理VPSS模块加速，以及借用其他硬件模块实现的图像处理功能）

2）FFMPEG API包含了所有硬件加速的视频/图像编解码接口，所有软件支持的视频/图像编解码接口（即所有FFMPEG开源支持的格式），通过bm_scale filter支持的部分硬件加速的图像处理接口（这部分图像处理接口，仅包括用硬件图像处理VPSS模块加速的缩放、crop、padding、色彩转换功能）

3）OPENCV API包含了所有FFMPEG支持的硬件及软件视频编解码接口（视频底层通过FFMPEG支持，这部分功能完全覆盖），硬件加速的JPEG编解码接口，软件支持的其他所有图像编解码接口（即所有OPENCV开源支持的图像格式），部分硬件加速的图像处理接口（指用图像处理VPSS模块加速的缩放、crop、padding、色彩转换功能），所有软件支持的OPENCV图像处理功能。

这三个框架中，BMCV 专注于图像处理功能，且能用BM168x硬件加速的部分；FFMPEG框架强于图像和视频的编解码，几乎所有格式都可以支持，只是是否能用硬件加速的区别；OPENCV框架强于图像处理，各种图像处理算法最初都先集成到OPENCV框架中，而视频编解码通过底层调用FFMPEG来实现。

因为BMCV仅提供了图像处理接口，因此FFMPEG或者OPENCV框架中，客户一般会选择其中一个作为主框架进行开发。这两个框架，从功能抽象上来说，OPENCV的接口要更加简洁，一个接口就可以实现一次视频编解码操作；从性能上说，这两个的性能是完全一致的，几乎没有差别，在视频编解码上，OPENCV只是对 FFMPEG接口的一层封装；从灵活性上说，FFMPEG的接口更加分离，可插入的操作粒度更细。最重要的，客户还是要根据自己对于某个框架的熟悉程度来做选择，只有深入了解，才能把框架用好。

这三个框架层级关系如图所示

图 1 OPENCV/FFMPEG/BMCV与BMSDK之间的层级调用关系

在很多应用场景下，需要用到某个框架下的特殊功能，因此在第4节中给出了三个框架之间灵活转换的方案。这种转换是不需要发生大量数据拷贝的，对性能几乎没有损失。

## BM1688硬件加速功能

本节给出了多媒体框架中硬件加速模块能支持的功能。其中硬件加速模块包括视频解码VPU模块，视频编码VPU模块，图像编解码JPU模块，图像处理VPSS模块。

需要特别注意，这里只列出能够用硬件加速的能力，以及典型场景下的性能估计值。更详细的性能指标参考BM168x产品规格书。

### 视频编解码

BM1688产品支持H264（AVC），HEVC视频格式的硬件解码加速，最高支持到4K视频的实时解码。支持H264(AVC), HEVC视频格式的硬件编码，最高支持到HD(1080p)视频的实时编码。

视频解码的速度与输入视频码流的格式有很大关系，不同复杂度的码流的解码速度有比较大的波动，比如码率、GOP结构，分辨率等，都会影响到具体的测试结果。一般来说，针对视频监控应用场景，BM1688产品单芯片可以支持到32路HD高清实时解码。

视频编码的速度与编码的配置参数有很大关系，不同的编码配置下，即使相同的视频内容，编码速度也不是完全相同的。一般来说，BM1688产品单芯片最高可以支持到2路HD高清实时编码。

### 图像编解码

BM1688产品支持JPEG baseline格式的硬件编/解码加速。注意，仅支持JPEG baseline档次的硬件编解码加速，对于其他图片格式，包括JPEG2000, BMP, PNG以及JPEG标准的progressive, lossless等档次均自动采用软解支持。在opencv框架中，这种兼容支持对于客户是透明的，客户应用开发时无需特别处理。

图像硬件编解码的处理速度和图像的分辨率、图像色彩空间（YUV420/422/444）有比较大的关系，一般而言，对于1920x1080分辨率的图片，色彩空间为YUV420的，单芯片图像硬件编解码可以达到600fps左右。

### 图像处理

BM1688产品有专门的视频处理VPSS单元对图像进行硬件加速处理。支持的图像操作有色彩转换、图像缩放、图像切割crop、图像拼接stitch功能。最大支持到4k图像输入。对于VPSS不支持的一些常用复杂图像处理功能，如线性变换ax+b，直方图等, 我们在BMCV API接口中，利用其他硬件单元做了特殊的加速处理。

## 硬件内存分类

在后续的讨论中，内存同步问题是应用调试中经常会遇到的，比较隐蔽的问题。我们通常统一用设备内存和系统内存来称呼这两类内存间的同步。

SOC模式，是指用BM168x芯片中的处理器作为主控CPU，BM168x产品独立运行应用程序。典型的产品有SE5、SM5-soc模组。在这类模式下，采用Linux系统下的ION内存对设备内存进行管理。在SOC模式下，设备内存指ION分配的物理内存，系统内存其实是cache，这里的命名只是为了和PCIE模式保持一致。从系统内存（cache）到设备内存，称为Upload上传（实质是cache flush）；从设备内存到系统内存（cache），称为Download下载（实质是cache invalidation）。在SOC模式下，设备内存和系统内存最终操作的其实是同一块物理内存，大部分时间，操作系统会自动对其进行同步，这也导致内存没有及时同步时的现象更加隐蔽和难以复现。

图 2 内存同步模型

FFMPEG和OPENCV两个框架都提供了内存同步操作的函数。而BMCV API只面向设备内存操作，因此不存在内存同步的问题，在调用BMCV API的时候，需要将数据在设备内存准备好。

在OPENCV框架中，部分函数的形参中就提供了update的标志位，当标志位设置true的时候，函数内部会自动进行内存同步操作。这部分可以参考后续的第二章第3节的API介绍。用户也可以通过bmcv::downloadMat() 和 bmcv::uploadMat()两个函数，主动控制内存同步。同步的基本原则是：a) opencv原生函数中，yuv Mat格式下设备内存中的数据永远是最新的，RGB Mat格式下系统内存中的数据永远是最新的 b) 当opencv函数向BMCV API切换的时候，根据上一个原则，将最新数据同步到设备内存中；反之，从BMCV API向opencv函数切换的时候，在RGB Mat下将最新数据同步到系统内存中。c) 在不发生框架切换的时候，要尽量减少内存同步的操作。频繁的内存同步操作会明显降低性能。

在常规FFMPEG框架中，有两类称之为软（常规）和硬（hwaccel）的codec API和filter API。这两套API的框架都可以支持BM168x的硬件视频编解码和硬件图像filter，从这个角度上说，所谓的软解码和硬解码在底层性能上是完全一样的，只是在使用习惯上的区别。软codec/filter API的使用方式和通常ffmpeg 内置codec完全一致，硬codec/filter API要用-hwaccel来指定使能bmcodec专用硬件设备。当在软codec API和filter API中，通过av_dict_set传入标志参数"is_dma_buffer"或者"zero_copy"，来控制内部codec或filter是否将设备内存数据同步到系统内存中，具体参数使用可以用ffmpeg -h来查看。当后续直接衔接硬件处理的时候，通常不需要将设备内存数据同步到系统内存中。

在hwaccel codec API和filter API中，内存默认只有设备内存，没有分配系统内存。如果需要内存同步，则要通过hwupload和hwdownload filter来完成。

综上所述，OPENCV和FFMPEG框架都对内存同步提供了支持，应用可以根据自己的使用习惯选择相应的框架，对数据同步进行精准控制。BMCV API则始终工作在设备内存上。

## 框架之间转换

在应用开发中，总会碰到一些情况下，某个框架无法完全满足设计需求。这时就需要在各种框架之间快速切换。BM168x多媒体框架对其提供了支持，可以满足这种需求，并且这种切换是不发生数据拷贝的，对于性能几乎没有影响。

### FFMPEG和OPENCV转换

FFMPEG和OPENCV之间的转换，主要是数据格式AVFrame和cv::Mat之间的格式转换。

当需要FFMPEG和OPENCV配合解决的时候，推荐使用常规非HWAccel API的通路，目前OPENCV内部采用是这种方式，验证比较完备。

FFMPEG AVFrame转到OPENCV Mat格式如下。

1. AVFrame * picture；
2. 中间经过ffmpeg API的一系列处理，比如avcodec_decode_video2 或者 avcodec_receive_frame，然后将得到的结果转成Mat
4. card_id 为进行ffmpeg硬件加速解码的设备序号， 在常规codec API中，通过av_dict_set的sophon_idx指定，或者hwaccel API中，在hwaccel设备初始化的时候指定， soc模式下默认为0
5. cv::Mat ocv_frame(picture, card_id)；
6. 或可以通过分步方式进行格式转换
7. cv::Mat ocv_frame;
8. ocv_frame.create(picture, card_id);
9. 然后可以用ocv_frame进行opencv的操作，此时ocv_frame格式为BM168x扩展的yuv mat类型，如果后续想转成opencv标准的bgr mat格式，可以按下列操作。
10. 注意：这里就有内存同步的操作， 如果没有设置，ffmpeg默认是在设备内存中的，如果update=false, 那么转成bgr的数据也一直在设备内存中，系统内存中为无效数据，如果update=true，则设备内存同步到系统内存中。如果后续还是硬件加速处理的话，可以update=false, 这样可以提高效率，当需要用到系统内存数据的时候，显式调用bmcv::downloadMat()来同步即可。
11. cv::Mat bgr_mat;
12. cv::bmcv::toMAT(ocv_frame, bgr_mat, update);
13. 最后AVFrame *picture会被Mat ocv_frame释放，因此不需要对picture进行av_frame_free()操作。如果希望外部调用av_frame_free来释放picture， 则可以加上card_id = card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED,0,0), 该标准表明AVFrame的创建和释放由外部管理
14. ocv_frame.release();
15. picture = nullptr;

OPENCV Mat转成FFMPEG AVFrame的情况比较少见，因为几乎所有需要的FFMPEG操作都在opencv中有对应的封装接口。比如：ffmpeg解码在opencv有videoCapture类，ffmpeg编码在opencv中有videoWriter类，ffmpeg的filter操作对应的图像处理在opencv中有bmcv名字空间下的接口以及丰富的原生图像处理函数。

一般来说，opencv Mat转成FFMPEG AVFrame，指的是yuv Mat。在这种情况下，可以按下进行转换。

1. 创建yuv Mat，如果yuv Mat已经存在，可以忽略此步.card_id为BM168x设备序号，soc模式下默认为0
2. AVFrame * f = cv::av::create(height, width, AV_PIX_FMT_YUV420P,  NULL, 0, -1, NULL, NULL, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, card_id);
3. cv::Mat image(f, card_id);
4. do something in opencv
5. AVFrame * frame = image.u->frame;
6. call FFMPEG API
7. 注意：在ffmpeg调用完成前，必须保证Mat image没有被释放，否则AVFrame会和Mat image一起释放。如果需要将两个的声明周期分离开来，则上面的image声明要改成如下格式。
8. cv::Mat image(f, card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED, 0, 0));
9. 这样Mat就不会接管AVFrame的内存释放工作

# FFMPEG和BMCV API转换

FFMPEG经常需要和BMCV API搭配使用，因此FFMPEG和BMCV之间的转换是比较频繁的。为此我们专门给了一个例子ff_bmcv_transcode，该例子可以在bmnnsdk2发布包里找到。

ff_bmcv_transcode例子演示了用ffmpeg解码，将解码结果转换到BMCV下进行处理，然后再转换回到ffmpeg进行编码的过程。FFMPEG和BMCV之间的互相转换可以参考ff_avframe_convert.cpp文件中的avframe_to_bm_image()和bm_image_to_avframe()函数。

# OPENCV和BMCV API转换

OPENCV和BMCV API之间的转换，专门在opencv扩展的bmcv名字空间下提供了专门的转换函数。

## OPENCV Mat转换到BMCV bm_image格式

1. `cv::Mat m(height, width, CV_8UC3, card_id);`
2. opencv 操作
3. `bm_image bmcv_image;`
4. 这里update用来控制内存同步，是否需要内存同步取决于前面的opencv 操作，如果前面的操作都是用硬件加速完成，设备内存中就是最新数据，就没必要进行内存同步，如果前面的操作调用了opencv函数，没有使用硬件加速（后续opencv章节6.2中提到了哪些函数采用了硬件加速），对于bgr mat格式就需要做内存同步。
5. 也可以在调用下面函数之前，显式的调用`cv::bmcv::uploadMat(m)`来实现内存同步
6. `cv::bmcv::toBMI(m, &bmcv_image, update);`
7. 使用bmcv_image就可以进行bmcv api调用，调用期间注意保证Mat m不能被释放，因为bmcv_image使用的是Mat m中分配的内存空间。handle可以通过`bm_image_get_handle()`获得
8. 释放：必须调用此函数，因为在toBMI中create了bm_image, 否则会有内存泄漏
9. `bm_image_destroy(bmcv_image);`
10. `m.release();`

## 由BMCV bm_image格式转换到OPENCV Mat

由BMCV bm_image格式转换到OPENCV Mat有两种方式，一种是会发生数据拷贝，这样bm_image和Mat之间相互独立，可以分别释放，但是有性能损失；一种是直接引用bm_image内存，性能没有任何损失。

1. `bm_image bmcv_image;`
2. 调用bmcv API给bmcv_image分配内存空间，并进行操作
3. `Mat m_copy, m_nocopy;`
4. 下面接口将发生内存数据拷贝，转换成标准bgr mat格式。
5. update控制内存同步，也可以在调用完这个函数后用`bmcv::downloadMat()`来控制内存同步
6. csc_type是控制颜色转换系数矩阵，控制不同yuv色彩空间转换到bgr
7. `cv::bmcv::toMAT(&bmcv_image, m_copy, update, csc_type);`
8. 下面接口接口将直接引用bm_image内存 (nocopy标志位true), update仍然按照之前的描述，
9. 选择是否同步内存。在后续opencv操作中，必须保证bmcv_image没有释放，因为mat的内存
10. 直接引用自bm_image `cv::bmcv::toMAT(&bmcv_image, &m_nocopy, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, NULL, -1, update, true);`
11. 进行opencv

# SOPHGO OpenCV使用指南

## OpenCV简介

BM168x系列芯片中的多媒体、BMCV和NPU硬件模块可以加速对图片和视频的处理：

1. 多媒体模块：硬件加速JPEG编码解码 和Video编解码操作。
2. BMCV模块：硬件加速对图片的resize、color conversion、crop、split、linear transform、nms、sort等操作。
3. NPU模块：硬件加速对图片的split、rgb2gray、mean、scale、int8tofloat32操作。

为了方便客户使用芯片上的硬件模块加速图片和视频的处理，提升应用OpenCV软件性能，算能修改了OpenCV库，在其内部调用硬件模块进行Image和Video相关的处理。

算能当前OpenCV的版本为4.1.0，除了以下几个算能自有的API以外，其它的所有API与OpenCV API都是一致的。

BM168x系列芯片有两种应用环境：SOC模式和PCIE卡模式。在SOC模式下，使用BM168x系列内置的ARM A53 core作为主控CPU，直接对芯片内部资源进行控制分配。PCIE模式下，BM168x系列作为PCIE卡插到主机上，由主机CPU通过PCIE接口对资源进行控制分配。SOPHGO OpenCV接口在两种模式下互相兼容，行为基本一致，只有以下微小的差异：

在SOC模式下，由于硬件限制，OpenCV库的Mat对象中，step值会被自动设置为64bytes对齐，不足64bytes的数据用0补齐。而在PCIE模式下，Mat的step不存在64bytes的对齐限制。例如，一张100*100的图片，每个像素的RGB由3个U8值表示，正常的step值为300，但是经过64bytes对齐，step值最终为320。如下图所示，Mat对象的data中，每一个step的数据是连续的320个bytes，其中前300个是真实数据，后面20个是自动填充的0值。

在SOC模式下，由于填充了多余的0值，Mat对象中存储数据的data变量不能直接传递给BMRuntime库的API做推理，否则会降低模型的准确率。请在最后一次BMCV做变换的时候，将stride设置为非对齐方式，多余的0会被自动清除掉。

## 数据结构扩展说明

OpenCV内置标准处理的色彩空间为BGR格式，但是很多情况下，对于视频、图片源，直接在YUV色彩空间上处理，可以节省带宽和避免不必要的YUV和RGB之间的互相转换。因此SOPHGO Opencv对于Mat类进行了扩展。

1. 在Mat.UMatData中，引入了AVFrame成员，扩展支持各种YUV格式。其中AVFrame的格式定义与FFMPEG中的定义兼容
2. 在Mat.UMatData中增加了fd，addr（soc模式下）的定义，分别表示对应的内存管理句柄和物理内存地址
3. 在Mat类中增加了fromhardware变量，标识当前的视频、图片解码是由硬件或是软件计算完成的，开发者在程序开发过程中无需考虑该变量的值。

## API扩展说明

### bool VideoCapture::get_resampler(int *den, int *num)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bool VideoCapture::get_resampler(int *den, int *num)` |
| 功能 | 取视频的采样速率。如den=5, num=3表示每5帧中有2帧被丢弃 |
| 输入参数 | int *den – 采样速率的分母<br>int *num – 采样速率的分子 |
| 输出参数 | 无 |
| 返回值 | true – 执行成功  false - 执行失败 |
| 说明 | 此接口将废弃。推荐用`double VideoCapture::get(CAP_PROP_OUTPUT_SRC)`接口。 |

### bool VideoCapture::set_resampler(int den, int num)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bool VideoCapture::set_resampler(int den, int num)` |
| 功能 | 置视频的采样速率。如den=5, num=3，表示每5帧中有2帧被丢弃。 |
| 输入参数 | int den – 采样速率的分母<br>int num – 采样速率的分子 |
| 输出参数 | 无 |
| 返回值 | true – 执行成功  false - 执行失败 |
| 说明 | 此接口将废弃。推荐用`bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)`接口。 |

### double VideoCapture::get(CAP_PROP_TIMESTAMP)

| 属性 | 说明 |
|------|------|
| 函数原型 | `double VideoCapture::get(CAP_PROP_TIMESTAMP)` |
| 功能 | 提供当前图片的时间戳，时间基数取决于在流中给出的时间基数 |
| 输入参数 | CAP_PROP_TIMESTAMP – 特定的枚举类型指示获取时间戳,此类型由Sophgo定义 |
| 输出参数 | 无 |
| 返回值 | 在使用前先将返回值转成unsigned int64数据类型<br>0x8000000000000000L-No AV PTS value<br>other-AV PTS value |

### double VideoCapture::get(CAP_PROP_STATUS)

| 属性 | 说明 |
|------|------|
| 函数原型 | `double VideoCapture::get(CAP_PROP_STATUS)` |
| 功能 | 该函数提供了一个接口，用于检查视频抓取的内部运行状态 |
| 输入参数 | CAP_PROP_STATUS – 枚举类型，此类型由Sophgo定义 |
| 输出参数 | 无 |
| 返回值 | 在使用返回值前请将转换成int类型<br>0  视频抓取停止，暂停或者其他无法运行的状态<br>1  视频抓取正在进行<br>2  视频抓取结束 |

### bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)

| 属性 | 说明 |
|------|------|
| 函数原型 | `double VideoCapture::get(CAP_PROP_OUTPUT_SRC, double resampler)` |
| 功能 | 设置YUV视频的采样速率。如resampler为0.4，表示每5帧中保留2帧，有3帧被丢弃 |
| 输入参数 | CAP_PROP_OUTPUT_SRC–枚举类型，此类型由Sophgo定义<br>double resampler – 采样速率 |
| 输出参数 | 无 |
| 返回值 | true 执行成功<br>false执行失败 |

### double VideoCapture::get(CAP_PROP_OUTPUT_SRC)

| 属性 | 说明 |
|------|------|
| 函数原型 | `double VideoCapture::get(CAP_PROP_OUTPUT_SRC)` |
| 功能 | 取视频的采样速率。 |
| 输入参数 | CAP_PROP_OUTPUT_SRC - 特定的枚举类型，指视频输出，此类型由SOPHGO定义 |
| 输出参数 | 无 |
| 返回值 | 采样率数值 |

### bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)` |
| 功能 | 开或者关闭YUV格式的frame输出。BM168x系列下YUV格式为I420 |
| 输入参数 | CAP_PROP_OUTPUT_YUV - 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义;<br>double enable - 操作码，1表示打开，0表示关闭 |
| 输出参数 | 无 |
| 返回值 | true：执行成功 false：执行失败 |

### double VideoCapture::get(CAP_PROP_OUTPUT_YUV)

| 属性 | 说明 |
|------|------|
| 函数原型 | `double VideoCapture::get(CAP_PROP_OUTPUT_YUV)` |
| 功能 | 取YUV视频frame输出的状态。 |
| 输入参数 | CAP_PROP_OUTPUT_YUV - 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义。 |
| 输出参数 | 无 |
| 返回值 | YUV视频frame输出的状态。1表示打开，0表示关闭。 |

### bm_handle_t bmcv::getCard(int id = 0)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bm_handle_t bmcv::getCard(int id = 0)` |
| 功能 | 取SOPHGO OpenCV内部使用的PCIE卡设备句柄。PCIE模式下有效 |
| 输入参数 | int id – PCIE卡序号，SOC下恒定为0 |
| 输出参数 | 无 |
| 返回值 | PCIE卡设备句柄 |
| 说明 | 通过toBMI接口转换得到bm_image，在调用bmcv API的时候会要求创建bm_image时的句柄，本接口可以支持获取得到该句柄。 |

### int bmcv::getId(bm_handle_t handle)

| 属性 | 说明 |
|------|------|
| 函数原型 | `int bmcv::getId(bm_handle_t handle)` |
| 功能 | 据PCIE设备句柄查询卡序号 |
| 输入参数 | Bm_handle_t handle – PCIE设备句柄 |
| 输出参数 | 无 |
| 返回值 | PCIE卡的序号 |

### bm_status_t bmcv::toBMI(Mat &m, bm_image *image, bool update = true)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bm_status_t bmcv::toBMI(Mat &m, bm_image *image, bool date = true)` |
| 功能 | OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不会发生copy操作。本接口仅支持1N模式 |
| 输入参数 | Mat& m – Mat对象，可以为扩展YUV格式或者标准OpenCV BGR格式;<br>bool update – 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存 |
| 输出参数 | bm_image *image – 对应格式的BMCV bm_image数据对象 |
| 返回值 | BM_SUCCESS(0)：执行成功 其他：执行失败 |
| 说明 | 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换 |

### bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)

| 属性 | 说明 |
|------|------|
| 函数原型 | `bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)` |
| 功能 | OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不发生copy操作。本接口针对BMCV的4N模式。要求所有Mat的输入图像格式一致,仅对BM1688有效 |
| 输入参数 | Mat &m - 4N中的第1幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m1 - 4N中的第2幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m2 - 4N中的第3幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>Mat &m3 - 4N中的第4幅图像，扩展YUV格式或者标准OpenCV BGR格式。<br>bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存 |
| 输出参数 | bm_image *image - 对应格式的BMCV bm_image数据对象，其中包含4个图像数据 |
| 返回值 | BM_SUCCESS(0)：执行成功  其他：执行失败 |
| 说明 | 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换 |

# bmcv::toMAT 函数

## bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update=true)

**函数原型**: `bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update = true)`

**功能**: 输入的MAT对象，可以为各种YUV或BGR格式，转换成BGR packet格式的MAT对象输出

**输入参数**:
- Mat &in - 输入的MAT对象，可以为各种YUV格式或者BGR格式
- bool update – 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存

**输出参数**:
- Mat &m0 - 输出的MAT对象，转成标准OpenCV的BGR格式

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**: 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1到BGR packed格式转换。在YUV格式下，会自动根据AVFrame结构体中colorspace,color_range信息选择正确的色彩转换矩阵。

## bm_status_t toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr = NULL, int fd0 = -1, bool update = true, bool nocopy = true)

**函数原型**: `bm_status_t bmcv::toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr=NULL, int fd0=-1, bool update=true, bool nocopy=true)`

**功能**: 输入的bm_image对象，当nocopy为true时，直接复用设备内存转成Mat格式，当nocopy为false时，行为类似3.13toMAT接口，1N模式。

**输入参数**:
- bm_image *image - 输入的bm_image对象，可以为各种YUV格式或者BGR格式
- Int color_space – 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义
- Int color_range – 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义
- Void* vaddr – 输出Mat的系统虚拟内存指针，如果已分配，输出Mat直接使用该内存作为Mat的系统内存。如果为NULL，则Mat内部自动分配
- Int fd0 – 输出Mat的物理内存句柄，如果为负，则使用bm_image内的设备内存句柄，否则使用fd0给定的句柄来mmap设备内存
- bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存到系统内存中
- bool nocopy – 如果是true，则直接引用bm_image的设备内存，如果为false，则转换成标准BGR Mat格式

**输出参数**:
- Mat &m - 输出的MAT对象，当nocopy为true时，输出标准BGR格式或扩展的YUV格式的Mat；当nocopy为false时，转成标准OpenCV的BGR格式。

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**:
1. no copy方式只支持1N模式，4N模式因为内存排列方式，不能支持引用
2. 在nocopy为false的情况下，会自动根据参数colorspace,color_range信息选择正确的色彩转换矩阵进行色彩转换
3. 如果系统内存vaddr来自于外部，那么外部需要来管理这个内存的释放，Mat释放的时候不会释放该内存

## bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update = true, csc_type_t csc = CSC_MAX_ENUM)

**函数原型**: `bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update=true, csc_type_t csc=CSC_MAX_ENUM)`

**功能**: 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，1N模式

**输入参数**:
- bm_image *image - 输入的bm_image对象，可以为各种YUV格式或者BGR格式
- bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存
- csc_type_t csc – 色彩转换矩阵，默认为YPbPr2RGB_BT601

**输出参数**:
- Mat &m0 - 输出的MAT对象，转成标准OpenCV的BGR格式

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

## bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update=true, csc_type_t csc=CSC_MAX_ENUM)

**函数原型**: `bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update=true, csc_type_t csc=CSC_MAX_ENUM)`

**功能**: 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，4N模式，仅在BM1688下有效

**输入参数**:
- bm_image *image - 输入的4N模式下的bm_image对象，可以为各种YUV格式或者BGR格式
- bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存
- csc_type_t csc – 色彩转换矩阵，默认为YPbPr2RGB_BT601

**输出参数**:
- Mat &m0 - 输出的第一个MAT对象，转成标准OpenCV的BGR格式
- Mat &m1 - 输出的第二个MAT对象，转成标准OpenCV的BGR格式
- Mat &m2 - 输出的第三个MAT对象，转成标准OpenCV的BGR格式
- Mat &m3 - 输出的第四个MAT对象，转成标准OpenCV的BGR格式

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

# bmcv::resize 函数

## bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation= BMCV_INTER_NEAREST)

**函数原型**: `bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation = BMCV_INTER_NEAREST)`

**功能**: 输入的MAT对象，缩放到输出Mat给定的大小，输出格式为输出Mat指定的色彩空间，因为MAT支持扩展的YUV格式，因此本接口支持的色彩空间并不仅局限于BGR packed。

**输入参数**:
- Mat &m - 输入的Mat对象，可以为标准BGR packed格式或者扩展YUV格式
- bool update - 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存
- int interpolation – 缩放算法，可为NEAREST或者LINEAR算法

**输出参数**:
- Mat &out - 输出的缩放后的Mat对象

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**: 支持Gray、YUV444P、YUV420P、BGR/RGB separate、BGR/RGB packed、ARGB packed格式缩放

# bmcv::convert 函数

## bm_status_t bmcv::convert(Mat &m, Mat &out, bool update=true)

**函数原型**: `bm_status_t bmcv::convert(Mat &m, Mat &out, bool update = true)`

**功能**: 实现两个mat之间的色彩转换，它与toMat接口的区别在于toMat只能实现各种色彩格式到BGR packed的色彩转换，而本接口可以支持BGR packed或者YUV格式到BGR packed或YUV之间的转换。

**输入参数**:
- Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存

**输出参数**:
- Mat &out - 输出的色彩转换后的Mat对象，可以为BGR packed或者YUV格式。

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

## bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update= true, csc_type_t csc=CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix = nullptr, bmcv_resize_algorithm algorithm= BMCV_INTER_LINEAR)

**函数原型**: `bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update = true, csc_type_t csc=CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix=nullptr, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)`

**功能**: 接口采用内置的VPSS硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，给定的多个缩放size，将输入的Mat对象，输出到多个Mat对象中，输出为OpenCV标准的BGR pack格式或扩展YUV格式

**输入参数**:
- Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- std::vector<Rect> &vrt - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同
- std::vector<Size> &vsz - 多个resize大小，与vrt的矩形框一一对应
- bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存
- csc_type_t csc – 色彩转换矩阵，可以根据颜色空间指定合适的色彩转换矩阵
- csc_matrix_t *matrix – 当色彩转换矩阵不在列表中时，可以给出外置的用户自定义的转换矩阵
- bmcv_resize_algorithm algorithm – 缩放算法，可以为Nearest或者Linear算法

**输出参数**:
- std::vector<Mat> &out - 输出的缩放、crop以及色彩转换后的标准BGR pack格式或YUV格式的Mat对象。

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**: 接口可以将resize,crop,csc三种操作在一步之内完成，效率最高。在可能的情况下，要尽可能的使用该接口提高效率

## bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update= true)

**函数原型**: `bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update= true)`

**功能**: 接口采用内置的VPSS硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，按照多个bm_image中指定的size，将输入的Mat对象，输出到多个bm_image对象中，输出格式由bm_image初始化值决定。注意，bm_image必须由调用者初始化好，并且个数和vrt一一对应。

**输入参数**:
- Mat &m - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- std::vector<Rect> &vrt - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同
- bool update -是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存

**输出参数**:
- bm_image *out - 输出的缩放、crop以及色彩转换后的bm_image对象，输出色彩格式由bm_image初始化值决定。同时该bmimage参数包含的初始化的size、色彩信息也作为输入信息，用于处理。

**返回值**:
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

# bmcv::uploadMat 函数

## void bmcv::uploadMat(Mat &mat)

**函数原型**: `void bmcv::uploadMat(Mat &mat)`

**功能**: cache同步或者设备内存同步接口。当执行此函数时，cache中内容会flush到实际内存中（SOC模式），或者host内存同步到PCIE卡设备内存（PCIE模式）。

**输入参数**:
- Mat &mat - 输入的需要内存同步的mat对象

**输出参数**: 无

**返回值**: 无

**说明**: 合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。这在PCIE模式下更为重要，因为每次PCIE设备内存的同步时间耗时较大。

# bmcv::downloadMat 函数

## void bmcv::downloadMat(Mat &mat)

**函数原型**: `void bmcv::downloadMat(Mat &mat)`

**功能**: cache同步或者设备内存同步接口。当执行此函数时，cache中内容会invalidate（SOC模式），或者PCIE卡设备内存同步到host内存中（PCIE模式）。本接口的内存同步方向与3.21接口正好相反

**输入参数**:
- Mat &mat - 输入的需要内存同步的mat对象

**输出参数**: 无

**返回值**: 无

**说明**: 合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。这在PCIE模式下更为重要，因为每次PCIE设备内存的同步时间耗时较大。

# bmcv::stitch

**函数原型**
```cpp
bm_status_t bmcv::stitch(std::vector<Mat> &in, std::vector<Rect> &src, std::vector<Rect> &drt, Mat &out, bool update=true, bmcv_resize_algorithm algorithm=BMCV_INTER_LINEAR)
```

**功能**
图像拼接，将输入的多个Mat按照按照给定的位置缩放并拼接到一个Mat中

**输入参数**
- `std::vector<Mat> &in` – 多个输入的Mat对象，可以为扩展的YUV格式或者标准BGR pack格式
- `std::vector<Rect> &src` – 对应每个Mat对象的显示内容框
- `std::vector<Rect> &drt` – 对应每个显示内容在目标Mat中的显示位置
- `bool update` - 是否需要同步cache或内存。如果为true,则转换完成后同步cache或者PCIE卡设备内存
- `bmcv_resize_algorithm algorithm` – 缩放算法,可以为Nearest或者Linear算法

**输出参数**
- `Mat &out` – 输出拼接后的Mat对象，可以为BGR packed或者YUV格式

**返回值**
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

# bmcv::print

**函数原型**
```cpp
void bmcv::print(Mat &m, bool dump = false)
```

**功能**
调试接口，打印输入Mat对象的色彩空间，宽高以及数据。

**输入参数**
- `Mat &m` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGRpacked格式
- `bool dump` - true的时候打印Mat中的数据值，默认不打印。如果为true，则会在当前目录下生成mat_dump.bin文件

**输出参数**
无

**返回值**
无

**说明**
当前支持dump OpenCV标准BGRpacked或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGRSeparate格式数据

# bmcv::print

**函数原型**
```cpp
void bmcv::print(bm_image *image, bool dump)
```

**功能**
调试接口，打印输入bm_image对象的色彩空间，宽高以及数据。

**输入参数**
- `bm_image *image` - 输入的bm_image对象
- `bool dump` - true的时候打印Mat中的数据值，默认不打印，如果为true，则会在当前目录下生成BMI-“宽”x”高”.bin文件

**输出参数**
无

**返回值**
无

**说明**
当前支持dump BGR packed,NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式的bm_image数据

# bmcv::dumpMat

**函数原型**
```cpp
void bmcv::dumpMat(Mat &image, const String &fname)
```

**功能**
调试接口，专门dumpMat的数据到指定命名的文件。功能同3.23的dump为true时的功能。

**输入参数**
- `Mat &image` - 输入的Mat对象,可以为扩展的YUV格式或者标准BGR packed格式
- `const String &fname` – dump的输出文件名

**输出参数**
无

**返回值**
无

**说明**
当前支持dump OpenCV标准BGR packed或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式数据

# bmcv::dumpBMImage

**函数原型**
```cpp
void bmcv::dumpBMImage(bm_image *image, const String &fname)
```

**功能**
调试接口，专门dump bm_image的数据到指定命名的文件。功能同3.25的dump为true时的功能。

**输入参数**
- `bm_image *image` - 输入的bm_image对象
- `const String &fname` – dump的输出文件名

**输出参数**
无

**返回值**
无

**说明**
当前支持dump BGR packed, NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式的bm_image数据

# Mat::avOK

**函数原型**
```cpp
bool Mat::avOK()
```

**功能**
判断当前Mat是否为扩展的YUV格式

**输入参数**
无

**输出参数**
无

**返回值**
- `true` – 表示当前Mat为扩展的YUV格式
- `false` – 表示当前Mat为标准OpenCV格式

**说明**
接口和接口3.21 3.22 downloadMat、uploadMat结合起来，可以有效地管理内存同步。

一般avOK为true的Mat，物理内存是最新的，而avOK为false的Mat，其cache或者host内存中的数据是最新的。可以根据这个信息，决定是调用uploadMat还是downloadMat。

一般avOK为true的Mat，物理内存或者PCIE卡设备内存是最新的，而avOK为false的Mat，其cache或者host内存中的数据是最新的。可以根据这个信息，决定是调用uploadMat还是downloadMat。

如果一直在设备内存中通过硬件加速单元工作，则可以省略内存同步，仅在需要交换到系统内存中时再调用downloadMat。

# Mat::avCols

**函数原型**
```cpp
int Mat::avCols()
```

**功能**
获取YUV扩展格式的Y的宽

**输入参数**
无

**输出参数**
无

**返回值**
返回扩展的YUV格式的Y的宽，如果为标准OpenCV Mat格式，返回0

# Mat::avRows

**函数原型**
```cpp
int Mat::avRows()
```

**功能**
获取YUV扩展格式的Y的高

**输入参数**
无

**输出参数**
无

**返回值**
返回扩展的YUV格式的Y的高，如果为标准OpenCV Mat格式，返回0

# Mat::avFormat

**函数原型**
```cpp
int Mat::avFormat()
```

**功能**
获取YUV格式信息

**输入参数**
无

**输出参数**
无

**返回值**
返回扩展的YUV格式信息，如果为标准OpenCV Mat格式，返回0

# Mat::avAddr

**函数原型**
```cpp
int Mat::avAddr(int idx)
```

**功能**
获取YUV各分量的物理地址

**输入参数**
- `int idx` – 指定YUV plane的序号

**输出参数**
无

**返回值**
返回指定的plane的物理首地址，如果为标准OpenCV Mat格式，返回0

# Mat::avStep

**函数原型**
```cpp
int Mat::avStep(int idx)
```

**功能**
获取YUV格式中指定plane的line size

**输入参数**
- `int idx` – 指定YUV plane的序号

**输出参数**
无

**返回值**
指定的plane的line size，如果为标准OpenCV Mat格式，返回0

# av::create

**函数原型**
```cpp
AVFrame* av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MPEG, int id = 0)
```

**功能**
AVFrame的创建接口，允许外部创建系统内存和物理内存，创建的格式与FFMPEG下的AVFrame定义兼容

**输入参数**
- `int height` – 创建图像数据的高
- `int width` – 创建图像数据的宽
- `int color_format` – 创建图像数据的格式，详见FFMPEG pixfmt.h定义
- `void *data` – 系统内存地址，当为null时，表示该接口内部自己创建管理
- `long addr` – 设备内存地址
- `int fd` – 设备内存地址的句柄。如果为-1，表示设备内存由内部分配，反之则由addr参数给出。在pcie模式下，如果设备内存由外部给出，该值可以设为0，在soc模式下，该值应该为ion内存的句柄
- `int* plane_stride` – 图像数据每层的每行stride数组
- `int* plane_size` – 图像数据每层的大小
- `int color_space` – 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义,默认为AVCOL_SPC_BT709
- `int color_range` – 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义，默认为AVCOL_RANGE_MPEG
- `int id` – 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

**输出参数**
无

**返回值**
AVFrame结构体指针

**说明**
1. 本接口支持创建以下图像格式的AVFrame数据结构：AV_PIX_FMT_GRAY8, AV_PIX_FMT_GBRP, AV_PIX_FMT_YUV420P, AV_PIX_FMT_NV12, AV_PIX_FMT_YUV422P horizontal, AV_PIX_FMT_YUV444P, AV_PIX_FMT_NV16

2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建失败

# av::create

**函数原型**
```cpp
AVFrame* av::create(int height, int width, int id = 0)
```

**功能**
AVFrame的简易创建接口，所有内存均由内部创建管理,仅支持YUV420P格式

**输入参数**
- `int height` – 创建图像数据的高
- `int width` – 创建图像数据的宽
- `int id` – 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

**输出参数**
无

**返回值**
AVFrame结构体指针

**说明**
本接口仅支持创建YUV420P格式的AVFrame数据结构

# av::copy

**函数原型**
```cpp
int av::copy(AVFrame *src, AVFrame *dst, int id)
```

**功能**
AVFrame的深度copy函数，将src的有效图像数据拷贝到dst中

**输入参数**
- `AVFrame *src` – 输入的AVFrame原始数据指针
- `int id` – 指定设备卡号，详见5.1

**输出参数**
- `AVFrame *dst` – 输出的AVFrame目标数据指针

**返回值**
返回copy的有效图像数据个数，为0则没有发生拷贝

**说明**
1. 本接口仅支持同设备卡号内的图像数据拷贝，即id相同
2. 函数中的id仅需要指定设备卡号，不需要其他标志位

# av::get_scale_and_plane

## 函数原型
`int av::get_scale_and_plane(int color_format, int wscale[], int hscale[])`

## 功能
获取指定图像格式相对于YUV444P的宽高比例系数

## 输入参数
- `int color_format` – 指定图像格式，详见FFMPEG pixfmt.h定义

## 输出参数
- `int wscale[]` – 对应格式相对于YUV444P每一层的宽度比例
- `int hscale[]` - 对应格式相对于YUV444P每一层的高度比例

## 返回值
返回给定图像格式的plane层数

## 说明

# cv::Mat

## 函数原型
`cv::Mat(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, SophonDevice device=SophonDevice())`

## 功能
新增的Mat构造接口。可以创建opencv标准格式或扩展的YUV Mat格式，并且系统内存和设备内存都允许通过外部分配给定

## 输入参数
- `int height` – 输入图像数据的高
- `int width` – 输入图像数据的宽
- `int total` – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小
- `int _type` – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1
- `const size_t *steps` – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP
- `void *_data` – 系统内存指针，如果为null，则内部分配该内存
- `unsigned long addr` – 设备物理内存地址，任意值均被认为有效的物理地址
- `int fd` – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理
- `SophonDevice device` –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

## 输出参数
构造的标准BGR或扩展YUV的Mat数据类型

## 返回值
无

## 说明
1. SophonDevice是为了避免C++隐含类型匹配造成函数匹配失误而引入的类型，可以用SophonDevice(int id)直接从5.1节的ID转换过来
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存

# Mat::Mat

## 函数原型
`Mat::Mat(SophonDevice device)`

## 功能
新增的Mat构造接口，指定该Mat的后续操作在给定的device设备上

## 输入参数
- `SophonDevice device` - 指定设备卡号以及HEAP位置的标志，详见5.1

## 输出参数
声明Mat数据类型

## 返回值
无

## 说明
1. 本构造函数仅初始化Mat内部的设备index，并不实际创建内存
2. 本构造函数的最大作用是对于某些内部create内存的函数，可以通过这个构造函数，提前指定创建内存的设备号和HEAP位置，从而避免将大量的内存分配在默认的设备号0上

# void Mat::create

## 函数原型
`void Mat::create(int height, int width, int total, int type, const size_t* _steps, void* _data, unsigned long addr, int fd, int id = 0)`

## 功能
Mat分配内存接口，该接口系统内存和设备内存都允许通过外部分配给定，也可内部分配。

## 输入参数
- `int height` – 输入图像数据的高
- `int width` – 输入图像数据的宽
- `int total` – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小
- `int _type` – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1
- `const size_t *steps` – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP
- `void *_data` – 系统内存指针，如果为null，则内部分配该内存
- `unsigned long addr` – 设备物理内存地址，任意值均被认为有效的物理地址
- `int fd` – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理
- `int id` –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

## 输出参数
无

## 返回值
无

## 说明
1. 扩展的内存分配接口，主要改进目的是允许外置指定设备物理内存，当设备或者系统内存由外部创建的时候，则外部必须负责该内存的释放，否则会造成内存泄漏
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存

# VideoWriter::write

## 函数原型
`void VideoWriter::write(InputArray image, char *data, int len)`

## 功能
新增的视频编码接口。与OpenCV标准VideoWriter::write接口不同，他提供了将编码视频数据输出到buffer的功能，便于后续处理

## 输入参数
- `InputArray image` – 输入的图像数据Mat结构

## 输出参数
- `char *data` – 输出的编码数据缓存
- `int *len` – 输出的编码数据长度

## 返回值
无

# VideoCapture::grab

## 函数原型
`bool VideoCapture::grab(char *buf, unsigned int len_in, usigned int *len_out);`

## 功能
新增的收流解码接口。与OpenCV标准VideoWriter::grab接口不同，他提供了将解码前的视频数据输出到buf的功能。

## 输入参数
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

## 输出参数
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

## 返回值
- true 表示 收流解码成功
- false表示收流解码失败

# VideoCapture::read_record

## 函数原型
`bool VideoCapture::read_record(OutputArray image, char *buf, unsigned int len_in, unsigned int *len_out);`

## 功能
新增的读取码流视频接口。他提供了将解码前的视频数据输出到buf的功能，将解码后的数据输出到image。

## 输入参数
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

## 输出参数
- `OutputArray image` – 输出解码后的视频数据
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

## 返回值
- true 表示 收流解码成功
- false表示收流解码失败

# 硬件JPEG解码器的OpenCV 扩展

在BM168x系列芯片中，提供JPEG硬件编码解码模块。为使用这些硬件模块，SDK软件包中，扩展了OpenCV中与JPEG图片处理相关的API函数，如：cv::imread()、 cv::imwrite()、cv::imdecode()、cv::imencode()等。您在使用这些函数做JPEG编解码的时候，函数内部会自动调用底层的硬件加速资源，从而大幅度提高了编解码的效率。如果您想保持这些函数原始的OpenCV API使用习惯，可以略过本节介绍；但如果你还想了解一下我们提供的简单易用的扩展功能，这节可能对您非常有帮助。

## 输出yuv格式的图像数据

OpenCV原生的cv::imread()、cv::imdecode()　API函数执行JPEG图片的解码操作，返回一个Ｍat结构体，该Mat结构体中保存有BGR packed格式的图片数据，算能扩展的API函数功能可以返回JPEG图片解码后的原始的YUV格式数据。用法如下：

当这两个函数的第二个参数flags被设置成cv::IMREAD_AVFRAME时，表示解码后返回的Mat结构体out中保存着YUV格式的数据。具体是什么格式的YUV数据要根据JPEG文件的image格式而定。当flags被设置成其它值或者省略不设置时，表示解码输出OpenCV原生的BGR packed格式的Mat数据。解码器输入输出扩展数据格式说明如下表所示：

| 输入Image格式 | 输入YUV格式 | FFMPEG对应格式 |
|--------------|------------|---------------|
| I400         | I400       | AV_PIX_FMT_GRAY8 |
| I420         | NV12       | AV_PIX_FMT_NV12 |
| I422         | NV16       | AV_PIX_FMT_NV16 |
| I444         | I444 planar | AV_PIX_FMT_YUV444P |

可以通过Mat::avFormat()扩展函数，得到当前数据所对应的具体的FFmpeg格式。可以通过Mat::avOK()扩展函数，得知cv::imdecode(buf, cv::IMREAD_AVFRAME, &out)解码返回的out，是否是算能扩展的Mat数据格式。

另外在这两个接口中的flags增加cv::IMREAD_RETRY_SOFTDEC标志时会在硬件解码失败的情况下尝试切换软件解码，也可以通过设置环境变量OPENCV_RETRY_SOFTDEC=1实现此功能。

## 支持YUV格式的函数列表

目前算能Opencv已经支持YUV Mat扩展格式的函数接口列表如下：

### 视频解码类接口
- VideoCapture类的成员函数

这类成员函数如read, grab，对于常用的HEVC, H264视频格式都使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

### 视频编码类接口
- VideoWriter类的成员函数

这类成员函数如write，对于常用的HEVC,H264视频格式已经使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

### JPEG编码类接口
### JPEG解码类接口
- Imread
- Imwrite
- Imdecode
- Imencode

以上接口在处理JPEG格式的时候，已经使用了BM168x系列的硬件加速功能，并支持YUV Mat扩展格式。

### 图像处理类接口
- cvtColor
- resize

这两个接口在BM168x系列 SOC模式下支持YUV Mat扩展格式，并使用硬件加速进行了优化。

**尤其需要注意的是cvtColor接口，只在YUV转换成BGR或者GRAY输出的时候支持硬件加速和YUV Mat的格式，即只支持输入为YUV Mat格式，并进行了硬件加速，输出不支持YUV Mat格式。**

在PCIE模式下，考虑到服务器的CPU性能较强，仍然采用原来的opencv原生处理方式，并不支持YUV扩展格式。

- line
- rectangle
- circle
- putText

以上四个接口均支持YUV扩展格式。注意，这四个接口并没有采用硬件加速，而是使用CPU对YUV Mat扩展格式进行的支持。

### 基本操作类接口
- Mat类部分接口
  - 创建释放接口：create，release，Mat声明接口
  - 内存赋值接口：clone，copyTo， cloneAll，copyAllTo，assignTo, operator =,
  - 扩展AV接口：avOK, avComp, avRows, avCols, avFormat, avStep, avAddr

以上接口均支持YUV扩展格式，尤其是copyTo, clone接口都采用硬件进行了加速。

### 扩展类接口
- Bmcv接口: 详见opencv2/core/bmcv.hpp
- AvFrame接口: 详见opencv2/core/av.hpp

以上算能扩展类接口，均支持YUV Mat扩展格式，并均针对硬件加速处理进行了优化。

**注意：支持YUV Mat扩展格式的接口并不等价于使用了硬件加速，部分接口是通过CPU处理来实现。这点需要特别注意。**

# 指定PCIE设备运行硬件加速

本节内容适用于VideoCapture, 图像编解码的Imread, Imwrite等接口。

## ID参数的定义

ID参数为32位整型，它定义了pcie设备卡以及部分内存扩展标志信息，具体定义如下：

| Bit位域 | 描述 |
|---------|------|
| Bit0-7 | 描述了PCIE设备的卡号，宏定义BM_CARD_ID(id)可以获取这信息 |
| Bit8-10 | 描述对应PCIE卡上的HEAP内存位置。<br>Bit8为1表示硬件内存分配在 heap0上；<br>Bit9为1表示硬件内存内存分配在 heap1上；<br>Bit10为1表示硬件内存内存分配在 heap2上；<br>Bit8-10全为0默认分配在 heap1上；<br>Heap0/1/2的内存位置详见BMLIB API手册。<br>宏定义BM_CARD_HEAP(id)可获取该信息 |
| Bit11-20 | 描述了Mat的内存扩展标志。<br>B11-B18为opencv标准定义，见MemoryFlag枚举类型<br>B19-为扩展的DEVICE_MEM_ATTACHED，标志该设备内存为外部管理，不需要Opencv来管理释放<br>B20-为扩展的AVFRAME_ATTACHED，标志创建YUV Mat的AVFrame为外部管理，不需要Opencv来管理释放。<br>宏定义BM_CARD_MEMFLAG(id)可获取该信息 |
| B21-31 | 扩展保留 |
| 说明 | 宏定义BM_MAKEFLAG(attach,heap,card)可用来生成完整的ID定义，其中attach对应B11-20,heap对应 B8-10,card对应B0-7 |

## 利用ID参数指定PCIE设备

在PCIE模式下，多设备情况下需要指定在特定卡上运行硬件加速功能。为了满足这个需要，SOPHGO OpenCV对VideoCapture::Open, imread, imdecode以及mat.create接口进行了扩展，增加了int id参数。

```
bool VideoCapture::open(const String& filename, int apiPreference, int id)
Mat imdecode(InputArray _buf, int flags, int id )
Mat imread(const String& filename, int flags, int id )
void Mat::create(int d, const int* _sizes, int _type, int id)
```

通过指定id，可以指定视频解码、图片解码运行在指定PCIE设备上，并且解码出来的Mat输出记录了该PCIE卡设备的序号。后续的硬件加速操作会继续在该指定PCIE设备上运行。

对于输入是Mat的大部分接口来说，因为Mat在调用create接口分配内存的时候已经指定了设备号，就不需要额外增加参数来指定PCIE卡设备。可以根据Mat内置的设备号在对应的设备上进行加速处理。

# OpenCV与BMCV API的调用原则

BMCV API充分发挥了BM168x系列芯片中的硬件单元的加速能力，能提高数据处理的效率。而OpenCV软件提供了非常丰富的图像图形处理能力，将两者有机的结合起来，使客户开发既能利用OpenCV丰富的函数库，又能在硬件支持的功能上获得加速，是本节的主要目的。

在BMCV API和OpenCV函数以及数据类型的切换过程中，最关键是要尽量避免数据拷贝，使得切换代价最小。因此在调用流程中要遵循以下原则。

1) 由OpenCV Mat到BMCV API的切换，可以利用toBMI()函数，该函数以零拷贝的方式，将Mat中的数据转换成了BMCV API调用所需的bm_image类型。

2) 当BMCV API需要切换到OpenCV Mat的时候，要将最后一步的操作通过OpenCV中的bmcv函数来实现。这样既完成所需的图像处理操作，同时也为后续OpenCV操作完成了数据类型准备。因为一般OpenCV都要求BGR Pack的色彩空间，所以一般用toMat()函数作为切换前的最后一步操作。

3) 一般神经网络处理的数据为不带padding的RGB planar数据，并且对于输入尺寸有特定的要求。因此建议将resize()函数作为调用神经网络NPU接口前的最后一步操作。

4) 当crop、resize、color conversion三个操作是连续的时候，强烈建议客户使用convert()函数，这可以在带宽优化和速度优化方面都获得理想的收益。即使后续可能还需要做一次拷贝，但因为拷贝发生在缩放之后的图像上，这种代价也是值得的。

# OpenCV中GB28181国标接口介绍

SOPHGO复用OpenCV原生的Cap接口，通过对于url定义进行扩展，提供GB28181国标的播放支持。因此客户并不需要重新熟悉接口，只要对扩展的url定义进行理解，即可像播放rtsp视频一样，无缝的播放GB28181视频。

注意：国标中的SIP代理注册步骤，需要客户自己管理。当获取到前端设备列表后，可以直接用url的方式进行播放。

## 国标GB28181支持的一般步骤

- 启动SIP代理（一般客户自己部署或者平台方提供）
- 客户的下级应用平台注册到SIP代理
- 客户应用获取前端设备列表，如下所示。其中，34010000001310000009等为设备20位编码。

```
{"devidelist":
[{"id": "34010000001310000009"}
{"id": "34010000001310000010"}
{"id": "34020000001310101202"}]}
```

- 组织GB28181 url直接调用OpenCV Cap接口进行播放

## GB28181 url格式定义

### UDP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=34010000001310000009#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108:
```

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=34010000001310000009#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108:
```

*注释*

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

localmediaport: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

### UDP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713:
```

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713:
```

*注释*

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

devicetype: 录像存储类型

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

localmediaport: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

begtime: 录像起始时间

endtime: 录像结束时间

### TCP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201:
```

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201:
```

*注释*

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

### TCP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713:
```

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713:
```

*注释*

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

devicetype: 录像存储类型

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

begtime: 录像起始时间

endtime: 录像结束时间

代码实例见bmnnsdk2软件包中的examples/multimedia。

# SOPHGO FFMPEG使用指南

## 前言

BM168x系列芯片中，有一个8核的A53处理器，同时还内置有视频、图像相关硬件加速模块。在SOPHGO提供的FFMPEG SDK开发包中，提供了对这些硬件模块的接口。其中，通过这些硬件接口，提供了如下模块：硬件视频解码器、硬件视频编码器、硬件JPEG解码器、硬件JPEG编码器、硬件scale filter、hwupload filter、hwdownload filter。

FFMPEG SDK开发包符合FFMPEG hwaccel编写规范，实现了视频转码硬件加速框架，实现了硬件内存管理、各个硬件处理模块流程的组织等功能。同时FFMPEG SDK也提供了与通常CPU解码器兼容的接口，以匹配部分客户的使用习惯。这两套接口我们称之为HWAccel接口和常规接口，他们底层共享BM168x硬件加速模块，在性能上是相同的。区别仅在于1）HWAccel需要初始化硬件设备; 2）HWAccel接口只面向设备内存，而常规接口同时分配了设备内存和系统内存; 3）他们的参数配置和接口调用上有轻微差别。

下面描述中，如非特殊说明，对常规接口和HWAccel接口都适用。

## 硬件视频解码器

BM168x系列支持H.264和H.265硬件解码。硬件解码器性能详情如下表所述。

| **Standard** | **Profile** | **Level** | **Max Resolution** | **Min Resolution** | **Bit rate** |
|--------------|-------------|-----------|-------------------|-------------------|-------------|
| H.264/AVC | BP/CBP/MP/HP | 4.1 | 8192x8192 | 16x16 | 50Mbps |
| H.265/HEVC | Main/Main10 | L5.1 | 8192x8192 | 16x16 | N/A |

在SophGo的FFMPEG发布包中，H.264硬件视频解码器的名字为*h264_bm*，H.265硬件视频解码器的名字为*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -decoders | grep _bm
```

### 硬件视频解码器支持的选项

FFMPEG中，BM168x系列的硬件解码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h decoder=h264_bm
$ ffmpeg -h decoder=hevc_bm
```

这些选项可以使用av_dict_set API来设置。在设置之前，需要对对这些选项有正确的理解。下面详细解释一下这些选项。

**output_format:**
- 输出数据的格式。
- 设为0，则输出线性排列的未压缩数据；设为101，则输出压缩数据。
- 缺省值为0。
- *推荐设置为101，输出压缩数据。可以节省内存、节省带宽。输出的压缩数据，可以调用后面介绍的scale_bm filter解压缩成正常的YUV数据。具体可参考应用示例中的示例1。*

**cbcr_interleave:**
- 硬件视频解码器解码输出的帧色度数据是否是交织格式。
- 设为1，则输出为semi-planar yuv图像，譬如nv12；设为0，则输出planar yuv图像，譬如yuv420p。
- 缺省值为1。

**extra_frame_buffer_num:**
- 硬件视频解码器额外提供硬件帧缓存数量。
- 缺省值为7。最小值为1。

**skip_non_idr:**
- 跳帧模式。0，关闭；1，跳过Non-RAP帧；2，跳过非参考帧。
- 缺省值为0。

**handle_packet_loss:**
- 出错时，对H.264, H.265解码器使能丢包处理。0, 不做丢包处理；1，进行丢包处理。
- 缺省值为0。

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的系统内存里。1，关闭拷贝；0，使能拷贝。
- 缺省值为1。

## 硬件视频编码器

从BM1684开始首次添加了硬件视频编码器。支持H.264/AVC和H.265/HEVC视频编码。

BM1684硬件编码器设计的能力为: 能够实时编码10路1080P30的视频。具体指标如下：

**H.265编码器:**
- Capable of encoding HEVC Main/Main10/MSP(Main Still Picture) Profile @ L5.1 High-tier

**H.264编码器:**
- Capable of encoding Baseline/Constrained Baseline/Main/High/High 10 Profiles Level @ L5.2

**通用指标**
- 最大分辨率 : 8192x8192
- 最小分辨率 : 256x128
- 编码图像宽度须为8的倍数
- 编码图像高度宽度须为8的倍数

在SophGo的FFMPEG发布包中，H.264硬件视频编码器的名字为*h264_bm*，H.265硬件视频编码器的名字为*h265_bm*或*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -encoders
```

### 硬件视频编码器支持的选项

FFMPEG中，硬件视频编码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h encoder=h264_bm
$ ffmpeg -h encoder=hevc_bm
```

BM1684硬件视频编码器支持如下选项:

**preset:** 预设编码模式。推荐通过enc-params设置。
- 0 - fast, 1 - medium, 2 - slow。
- 缺省值为2。

**gop_preset:** gop预设索引值。推荐通过enc-params设置。
- 1: all I, gopsize 1
- 2: IPP, cyclic gopsize 1
- 3: IBB, cyclic gopsize 1
- 4: IBPBP, cyclic gopsize 2
- 5: IBBBP, cyclic gopsize 4
- 6: IPPPP, cyclic gopsize 4
- 7: IBBBB, cyclic gopsize 4
- 8: random access, IBBBBBBBB, cyclic gopsize 8

**qp:**
- 恒定量化参数的码率控制方法
- 取值范围为0至51

**perf:**
- 用于指示是否需要测试编码器性能
- 取值范围为0或1。

**enc-params:**
- 用于设置视频编码器内部参数。
- 支持的编码参数：preset，gop_preset，qp，bitrate，mb_rc，delta_qp，min_qp，max_qp，bg，nr，deblock，weightp
- 编码参数preset：取值范围为fast, medium, slow或者是0，1，2
- 编码参数gop_preset：gop预设索引值。参考上面已有详细解释。
- 编码参数qp：恒定量化参数，取值范围为[0, 51]。当该值有效时，关闭码率控制算法，用固定的量化参数编码。
- 编码参数bitrate：用于编码所指定的码率。单位是Kbps，1Kbps=1000bps。当指定改参数时，请不要设置编码参数qp。
- 编码参数mb_rc：取值范围0或1。当设为1时，开启宏块级码率控制算法；当设为0时，开启帧级码率控制算法。
- 编码参数delta_qp：用于码率控制算法的QP最大差值。该值太大影响视频主观质量。太小影响码率调整的速度。
- 编码参数min_qp和max_qp：码率控制算法中用于控制码率和视频质量的最小量化参数和最大量化参数。取值范围[0, 51]。
- 编码参数bg：是否开启背景检测。取值范围0或1。
- 编码参数nr：是否开启降噪算法。取值范围0或1。
- 编码参数deblock：是否开启环状滤波器。有如下几种用法：
  - 关闭环状滤波器"deblock=0"或"no-deblock"。
  - 简单开启环状滤波器，使用缺省环状滤波器参数"deblock=1"。
  - 开启环状滤波器并设置参数，譬如"deblock=6,6"。
- 编码参数weightp：是否开启P帧、B帧加权预测。取值范围0或1。

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

## 硬件JPEG解码器

在BM168x系列芯片中，硬件JPEG解码器提供硬件JPEG图像解码输入能力。这里介绍一下，如何通过FFMPEG来实现硬件JPEG解码。

在FFMPEG中, 硬件JPEG解码器的名称为*jpeg_bm*。可以通过如下命令, 来查看FFMPEG中是否有*jpeg_bm*解码器。

```
$ ffmpeg -decoders | grep jpeg_bm
```

### 硬件JPEG解码器支持的选项

FFMPEG中，可以通过如下命令, 来查看*jpeg_bm*解码器支持的选项

```
$ ffmpeg -h decoder=jpeg_bm
```

解码选项的说明如下。硬件JPEG解码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**bs_buffer_size:** 用于设置硬件JPEG解码器中输入比特流的缓存大小(KBytes)。
- 取值范围(0到INT_MAX)
- 缺省值5120

**cbcr_interleave:** 用于指示JPEG解码器输出的帧数据中色度数据是否为交织的格式。
- 0: 输出的帧数据中色度数据为plannar的格式
- 1: 输出的帧数据中色度数据为interleave的格式
- 缺省值为0

**num_extra_framebuffers:** JPEG解码器需要的额外帧缓存数量
- 对于Still JPEG的输入, 建议该值设为0
- 对于Motion JPEG的输入, 建议该值至少为2
- 取值范围(0到INT_MAX)
- 缺省值为2

## 硬件JPEG编码器

在BM168x系列芯片中，硬件JPEG编码器提供硬件JPEG图像编码输出能力。这里介绍一下，*如何通过FFMPEG来实现硬件JPEG编码*。

在FFMPEG中，硬件JPEG编码器的名称为*jpeg_bm*。可以通过如下命令，来查看FFMPEG中是否有jpeg_bm编码器。

```
$ ffmpeg -encoders | grep jpeg_bm
```

### 硬件JPEG编码器支持的选项

FFMPEG中，可以通过如下命令, 来查看jpeg_bm编码器支持的选项

```
$ ffmpeg -h encoder=jpeg_bm
```

编码选项的说明如下。硬件JPEG编码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

## 硬件scale filter

BM168x系列硬件scale filter用于将输入的图像进行"缩放/裁剪/补边"操作。譬如，转码应用。在将1080p的视频解码后，使用硬件scale缩放成720p的，再进行压缩输出。

| *内容* | *最大分辨率* | *最小分辨率* | *放大倍数* |
|--------|-------------|-------------|-----------|
| 硬件限制 | 4096 * 4096 | 8*8 | 32 |

在FFMPEG中，硬件scale filter的名称为 *scale_bm*。

```
$ ffmpeg -filters | grep bm
```

### 硬件scale filter支持的选项

FFMPEG中，可以通过如下命令, 来查看scaler_bm编码器支持的选项

```
$ ffmpeg -h filter=scale_bm
```

scale_bm选项的说明如下:

**w:**
- 缩放输出视频的宽度。请参考ffmpeg scale filter的用法。

**h:**
- 缩放输出视频的高度。请参考ffmpeg scale filter的用法。

**format:**
- 缩放输出视频的像素格式。请参考ffmpeg scale filter的用法。
- 输入输出支持的格式详见附表7.1。
- 缺省值"none"。即输出像素格式为系统自动。输入为yuv420p，输出为yuv420p; 输入为yuvj420p，输出为yuvj420p。输入为nv12时，缺省输出为yuv420p。
- 在HWAccel框架下：支持nv12到yuv420p、nv12到yuvj420p、yuv420p到yuvj420p、yuvj422p到yuvj420p、yuvj422p到yuv420p的格式转换。在不启用HWAccel框架的正常模式下支持情况见附表7.1。

| 输入 | 输出 | 是否持缩放 | 是否支持颜色转换 |
|------|------|------------|-----------------|
| GRAY8 | GRAY8 | 是 | 是 |
| NV12（压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| NV12（非压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV420P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV422P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 否 |
|  | YUV444P | 否 | 否 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV444P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| BGR、RGB | YUV420P | 是 |  |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| RGBP、BGRP | YUV420P | 是 |  |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |

表7.1 scale_bm像素格式支持列表

**opt:**
- 缩放操作 (from 0 to 2) (default 0)
- 值0 - 仅支持缩放操作。缺省值。
- 值1 - 支持缩放+自动裁剪操作。命令行参数中可用crop来表示。
- 值2 - 支持缩放+自动补黑边操作。命令行参数中可用pad来表示。

**flags:**
- 缩放方法 (from 0 to 2) (default 1)
- 值0 - nearest滤波器。命令行参数中，可用nearest来表示。
- 值1 - bilinear滤波器。命令行参数中，可用bilinear来表示。
- 值2 - bicubic滤波器。命令行参数中，可用bicubic来表示。

**sophon_idx:**
- 设备ID , 从0开始。

**zero_copy:**
- 值0 - 表示scale_bm的输出AVFrame将同时包含设备内存和主机内存指针，兼容性最好，性能稍有下降。缺省为0
- 值1 - 表示scale_bm的输出到下一级的AVFrame中将只包含有效设备地址，不会对数据进行从设备内存到系统内存的同步。建议对于下一级接使用SOPHGO的编码/filter的情况，可以选择设置为1，其他建议设置为0。
- 缺省为0

## AVFrame特殊定义说明

遵从FFMPEG的规范, 硬件解码器是通过AVFrame来提供输出的，硬件编码器是通过AVFrame来提供输入的。因此，在通过API方式，调用FFMPEG SDK、进行硬件编解码处理时，需要注意到AVFrame的如下特殊规定。AVFrame是线性YUV输出。在AVFrame中，data为数据指针, 用于保存物理地址，linesize为每个平面的线跨度。

### 硬件解码器输出的avframe接口定义

#### 常规接口

*data数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址 |
| 1 | cbcr_interleave=1 时CbCr的虚拟地址; cbcr_interleave=0 时Cb的虚拟地址 |
| 2 | cbcr_interleave=0 时Cr的虚拟地址 |
| 3 | 未使用 |
| 4 | Y的物理地址 |
| 5 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 |
| 6 | cbcr_interleave=0 时Cr的物理地址 |
| 7 | 未使用 |

*linesize数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址的跨度 |
| 1 | cbcr_interleave=1时CbCr的虚拟地址的跨度；cbcr_interleave=0时Cb的虚拟地址的跨度 |
| 2 | cbcr_interleave=0时Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 |
| 6 | cbcr_interleave=0时Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

*data数组的定义*

| **下标** | **未压缩格式说明** | **压缩格式明** |
|----------|-------------------|---------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 | 压缩的色度数据的物理地址 |
| 2 | cbcr_interleave=0 时Cr的物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

*linesize数组的定义*

| **下标** | **未压缩格式说明** | **压缩格式说明** |
|----------|-------------------|-----------------|
| 0 | Y的物理地址的跨度 | 亮度数据的跨度 |
| 1 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 | 色度数据的跨度 |
| 2 | cbcr_interleave=0时Cr的物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 偏移量表的大小 |

### 硬件编码码器输入的avframe接口定义

#### 常规接口

*data数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

*linesize数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

*data数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的物理地址 |
| 1 | Cb的物理地址 |
| 2 | Cr的物理地址 |
| 3 | 保留 |
| 4 | 保留 |

*linesize数组的定义*

| **下标** | **说明** |
|----------|----------|
| 0 | Y的物理地址的跨度 |

# 硬件filter输入输出的AVFrame接口定义

## 1. 在不启用HWAccel加速功能时，AVFrame接口定义采用常规接口的内存布局

### data数组的定义

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

### linesize数组的定义

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

## 2. HWAccel接口下AVFrame接口定义

### data数组的定义

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | Cb物理地址 | 压缩的色度数据的物理地址 |
| 2 | Cr物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

### linesize数组的定义

| 下标 | 说明 | 缩格式的输入接口 |
|------|------|-----------------|
| 0 | Y物理地址的跨度 | 亮度数据的跨度 |
| 1 | Cb物理地址的跨度 | 色度数据的跨度 |
| 2 | Cr物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 色度偏移量表的大小 |

# 硬件加速在FFMPEG命令中的应用示例

下面同时给出常规模式和HWAccel模式对应的FFMPEG命令行参数。

为便于理解，这里汇总说明：

- 常规模式下，bm解码器的输出内存是否同步到系统内存上，用zero_copy控制，默认为1
- 常规模式下，bm编码器的输入内存在系统内容还是设备内存上，用is_dma_buffer控制，默认值为1
- 常规模式下，bm滤波器会自动判断输入内存的同步，输出内存是否同步到系统内存，用zero_copy控制，默认值为0
- HWAccel模式下，设备内存和系统内存的同步用hwupload和hwdownload来控制
- 常规模式下，用sophon_idx来指定设备，默认为0；HWAccel模式下用hwaccel_device来指定

## 示例 1

使用设备0。解码H.265视频，输出compressed frame buffer，scale_bm解压缩compressed frame buffer并缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

## 示例 2

使用设备0。解码H.265视频，按比例缩放并自动裁剪成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

## 示例 3

使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

## 示例 4

演示视频截图功能。使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成jpeg图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:format=yuvj420p:zero_copy=1" \
-c:v jpeg_bm -vframes 1 \
-y wkc_100_cif_scale.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:format=yuvj420p" \
-c:v jpeg_bm -vframes 1 \
-y wkc_100_cif_scale.jpeg
```

## 示例 5

演示视频转码+视频截图功能。使用设备0。硬件解码H.265视频，缩放成CIF，然后编码成H.264码流；同时缩放成720p，然后编码成JPEG图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-filter_complex "[0:v]scale_bm=352:288:zero_copy=1[img1];[0:v]scale_bm=1280:720:format=yuvj420p:zero_copy=1[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-filter_complex "[0:v]scale_bm=352:288[img1];[0:v]scale_bm=1280:720:format=yuvj420p[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

## 示例6

演示hwdownload功能。硬件解码H.265视频，然后下载存储成YUV文件。

Filter hwdownload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过codec中指定zero_copy选项来实现，因此不需要hwdownload滤波器。

常规模式：

```
ffmpeg -c:v hevc_bm -cbcr_interleave 0 -zero_copy 0 \
-i src/wkc_100.265 -y test_transfer.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -cbcr_interleave 0 -i src/wkc_100.265 \
-vf "hwdownload,format=yuv420p bmcodec" \
-y test_transfer.yuv
```

## 示例7

演示hwdownload功能。硬件解码H.265视频，缩放成CIF格式，然后下载存储成YUV文件。

在常规模式中， scale_bm会自动根据filter的链条判定是否同步内存，因此不需要hwdownload。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,format=yuv420p" \
-y test_transfer_cif.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,hwdownload,format=yuv420p bmcodec" \
-y test_transfer_cif.yuv
```

## 示例8

演示hwupload功能。使用设备0。上传YUV视频，然后编码H.264视频。

Filter hwupload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过编码器中指定is_dma_buffer选项来实现，因此不需要hwupload滤波器。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuv420p -i test_transfer.yuv \
-c:v h264_bm -b:v 3M -is_dma_buffer 0 -y test_transfer.264
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:0 \
-s 1920x1080 -i test_transfer.yuv \
-filter_hw_device foo -vf "format=yuv420p bmcodec,hwupload" \
-c:v h264_bm -b:v 3M -y test_transfer.264
```

这里foo为设备0的别名。

## 示例9

演示hwupload功能。使用设备1。上传YUV视频，并缩放成CIF，然后编码H.264视频。

常规模式：

```
ffmpeg -s 1920x1080 -i test_transfer.yuv \
-vf "scale_bm=352:288:sophon_idx=1:zero_copy=1" \
-c:v h264_bm -b:v 256K -sophon_idx 1 \
-y test_transfer_cif.264
```

说明：
1. 这里不指定-pix_fmt yuv420p是因为默认输入为yuv420p格式
2. 常规模式下,bm_scale filter, decoder，encoder通过参数sophon_idx来指定使用哪个设备

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 \
-s 1920x1080 -i test_transfer.yuv \
-filter_hw_device foo \
-vf "format=yuv420p bmcodec,hwupload,scale_bm=352:288" \
-c:v h264_bm -b:v 256K -y test_transfer_cif.264
```

说明：这里foo为设备1的别名，HWAccel模式下通过init_hw_device来指定使用具体的硬件设备。

## 示例10

演示hwdownload功能。硬件解码YUVJ444P的JPEG视频，然后下载存储成YUV文件。

常规模式：

```
ffmpeg -c:v jpeg_bm -zero_copy 0 -i src/car/1920x1080_yuvj444.jpg \
-y car_1080p_yuvj444_dec.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v jpeg_bm -i src/car/1920x1080_yuvj444.jpg \
-vf "hwdownload,format=yuvj444p bmcodec" \
-y car_1080p_yuvj444_dec.yuv
```

## 示例11

演示hwupload功能。使用设备1。上传YUVJ444P图像数据，然后编码JPEG图片。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-c:v jpeg_bm -sophon_idx 1 -is_dma_buffer 0 \
-y car_1080p_yuvj444_enc.jpg
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 \
-s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-filter_hw_device foo -vf 'format=yuvj444p bmcodec,hwupload' \
-c:v jpeg_bm -y car_1080p_yuvj444_enc.jpg
```

这里foo为设备1的别名。

## 示例12

演示软解码和硬编码混合使用的方法。使用设备2。使用ffmpeg自带的*h264*软解码器，解码H.264视频，上传解码后数据到芯片2，然后编码H.265视频。

常规模式：

```
ffmpeg -c:v h264 -i src/1920_18MG.mp4 \
-c:v h265_bm -is_dma_buffer 0 -sophon_idx 2 -g 256 -b:v 5M \
-y test265.mp4
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:2 \
-c:v h264 -i src/1920_18MG.mp4 \
-filter_hw_device foo -vf 'format=yuv420p bmcodec,hwupload' \
-c:v h265_bm -g 256 -b:v 5M \
-y test265.mp4
```

这里foo为设备2的别名。

## 示例13

演示使用enc-params设置视频编码器的方法。使用设备0。解码H.265视频，缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" \
-c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288" \
-c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

## 示例14

使用设备0。解码H.265视频，使用bilinear滤波器，按比例缩放成CIF，并自动补黑边，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:flags=bilinear:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:flags=bilinear" \
```

```bash
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

## 通过调用API方式来使用硬件加速功能

examples/multimedia/ff_bmcv_transcode/例子演示了使用ffmpeg做编解码，用bmcv做图像处理的整个流程。

examples/multimedia/ff_video_decode/例子演示了使用ffmpeg做解码的流程。

examples/multimedia/ff_video_encode/例子演示了使用ffmpeg做编码的流程。

## 硬件编码支持roi编码

参考examples/multimedia/ff_video_encode/例子。设置roi_enable既可启用roi编码。

Roi编码数据通过av_frame side data传递。

Roi数据结构定义为

**字段说明:**

### QP Map

H264下QP以宏块16x16为单位给出。HEVC下QP以sub-ctu（32x32）为单位给出。QP对应的就是video编码中的Qstep，取值范围为0-51.

### Lamda Map

lamda是用来控制和调节IP内部的RC计算公式

cost = distortion + lamda * rate

这个调节参数仅在HEVC下有效，允许以32x32 sub-CTU模块为单位控制。

### Mode Map

这个参数用来指定模式选择。 0 – 不适用 1 – skip mode 2- intra mode。H264下以宏块16x16为单位控制，HEVC下以CTU 64x64为单位控制。

### Zero-cut Flag

仅在HEVC下有效。将当前CTU 64x64残差系数全部置为0，从而节省出更多的比特给其他更重要的部分。

# SOPHGO LIBYUV使用指南

## 简介

BM168x系列芯片中的各种硬件模块，可以加速对图片和视频的处理。颜色转换方面，采用专用硬件来加速速度很快。

但在有些场合，也会存在一些专用硬件覆盖不到的特殊情况。此时采用经过SIMD加速优化的软件实现, 成为专用硬件有力的补充。

SOPHGO增强版**libyuv**，是随同SDK一同发布的一个组件。目的是充分利用BM168x系列芯片提供的8核A53处理器，通过软件手段为硬件的局限性提供补充。

除了libyuv提供的标准函数之外，针对AI的需求，在SOPHGO增强版libyuv中，补充了27个扩展函数。

注意：这里说的是运行在BM168x系列的A53处理器上，而不是host的处理器。这从设备加速的角度是可以理解的。这样可以避免占用host的CPU。

## libyuv扩展说明

新增了如下增强AI应用方面的API。

### fast_memcpy

```c
void* fast_memcpy(void *dst, const void *src, size_t n)
```

| 功能 | CPU SIMD指令实现memcpy功能。从内存区域src拷贝n个字节到内存区域dst |
|------|-------------------------------------------------------------------|
| 参数 | src: 源内存区域<br>n: 需要拷贝的字节数<br>dst: 目的内存区域 |
| 返回值 | 返回一个指向dst的指针 |

### RGB24ToI400

```c
int RGB24ToI400(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, int width, int height);
```

| 功能 | 将一帧BGR数据转换成BT.601灰度数据 |
|------|-----------------------------------|
| 参数 | src_rgb24: packed BGR图像数据所在的内存虚地址<br>src_stride_rgb24: 内存中每行BGR图像实际跨度<br>dst_y: 灰度图像虚拟地址<br>dst_stride_y: 内存中每行灰度图像实际跨度<br>width: 每行BGR图像数据中packed BGR的数量<br>height: BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

### RAWToI400

```c
int RAWToI400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);
```

| 功能 | 将一帧RGB数据转换成BT.601灰度数据 |
|------|-----------------------------------|
| 参数 | src_row: packed BGR图像数据所在的内存虚地址<br>src_stride_row: 内存中每行BGR图像实际跨度<br>dst_y: 灰度图像虚拟地址<br>dst_stride_y: 内存中每行灰度图像实际跨度<br>width: 每行BGR图像数据中packed BGR的数量<br>height: BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

### I400ToRGB24

```c
int I400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

| 功能 | 将一帧BT.601灰度数据转换成BGR数据 |
|------|-----------------------------------|
| 参数 | src_y: 灰度图像虚拟地址<br>src_stride_y: 内存中每行灰度图像实际跨度<br>dst_rgb24: packed BGR图像数据所在的内存虚地址<br>dst_stride_rgb24: 内存中每行BGR图像实际跨度<br>width: 每行BGR图像数据中packed BGR的数量<br>height: BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

### I400ToRAW

```c
int I400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

| 功能 | 将一帧BT.601灰度数据转换成RGB数据 |
|------|-----------------------------------|
| 参数 | src_y: 灰度图像虚拟地址<br>src_stride_y: 内存中每行灰度图像实际跨度<br>dst_rgb24: packed RGB图像数据所在的内存虚地址<br>dst_stride_rgb24: 内存中每行RGB图像实际跨度<br>width: 每行RGB图像数据中packed RGB的数量<br>height: RGB图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

### J400ToRGB24

```c
int J400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

| 功能 | 将一帧BT.601 full range 灰度数据转换成BGR数据 |
|------|-----------------------------------------------|
| 参数 | src_y: 灰度图像虚拟地址<br>src_stride_y: 内存中每行灰度图像实际跨度<br>dst_rgb24: packed BGR图像数据所在的内存虚地址<br>dst_stride_rgb24: 内存中每行BGR图像实际跨度<br>width: 每行BGR图像数据中packed BGR的数量<br>height: BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# RAWToJ400

```c
int RAWToJ400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);
```

| 属性 | 描述 |
|------|------|
| 功能 | 将一帧RGB数据转换成BT.601 full range灰度数据 |
| 参数 | |
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | 灰度图像虚拟地址 |
| dst_stride_y | 内存中每行灰度图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# J400ToRAW

```c
int J400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

| 属性 | 描述 |
|------|------|
| 功能 | 将一帧BT.601 full range 灰度数据转换成RGB数据 |
| 参数 | |
| src_y | 灰度图像虚拟地址 |
| src_stride_y | 内存中每行灰度图像实际跨度 |
| dst_rgb24 | packed RGB图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行RGB图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# RAWToNV12

```c
int RAWToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 属性 | 描述 |
|------|------|
| 功能 | 将一帧RGB数据转换成BT.601 limited range的semi-planar YCbCr 420数据 |
| 参数 | |
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# RGB24ToNV12

```c
int RGB24ToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 属性 | 描述 |
|------|------|
| 功能 | 将一帧BGR数据转换成BT.601 limited range的semi-planar YCbCr 420数据 |
| 参数 | |
| src_raw | packed BGR图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_uv | CbCr分量的虚拟地址 |
| dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# RAWToJ420

```c
int RAWToJ420(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

| 属性 | 描述 |
|------|------|
| 功能 | 将一帧RGB数据转换成BT.601 full range的semi-planar YCbCr 420数据 |
| 参数 | |
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## J420ToRAW

```c
int J420ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 420数据转换成RGB数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RAWToJ422

```c
int RAWToJ422(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧RGB数据转换成BT.601 full range的YCbCr 422数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J422ToRAW

```c
int J422ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 422数据转换成RGB数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RGB24ToJ422

```c
int RGB24ToJ422(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BGR数据转换成BT.601 full range的YCbCr 422数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_rgb24 | packed BGR图像数据所在的内存虚地址 |
| src_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J422ToRGB24

```c
int J422ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 422数据转换成BGR数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行BGR图像数据的实际跨度 |
| width | 每行RGB图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RAWToJ444

```c
int RAWToJ444(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧RGB数据转换成BT.601 full range的YCbCr 444数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J444ToRAW

```c
int J444ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 444数据转换成RGB数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## RGB24ToJ444

```c
int RGB24ToJ444(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BGR数据转换成BT.601 full range的YCbCr 444数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_rgb24 | packed BGR图像数据所在的内存虚地址 |
| src_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行BGR图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## J444ToRGB24

```c
int J444ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);
```

**功能**：将一帧BT.601 full range的YCbCr 444数据转换成BGR数据

**参数**：

| 参数名 | 描述 |
|--------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行BGR图像数据的实际跨度 |
| width | 每行RGB图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## H420ToJ420

```c
int H420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.709 limited range的YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## I420ToJ420

```c
int I420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## NV12ToJ420

```c
int NV12ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_uv, int src_stride_uv,
uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_uv | CbCr分量的虚拟地址 |
| src_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## NV21ToJ420

```c
int NV21ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_vu, int src_stride_vu,
uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u,
uint8_t* dst_v, int dst_stride_v, int width, int height);
```

**功能**：将一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的数据。可以在jpeg编码之前，作预处理函数使用。

**参数**：

| 参数 | 描述 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_vu | CrCb分量的虚拟地址 |
| src_stride_vu | 内存中每行CrCb分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

**返回值**：0, 正常结束; 非0, 参数异常。

## I444ToNV12

```c
int I444ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 属性 | 说明 |
|------|------|
| 功能 | 将一帧YCbCr 444数据转换成semi-plannar YCbCr 420数据。可用于full range，也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用 |
| 参数 | **src_y** - 源图像Y分量的虚拟地址<br>**src_stride_y** - 内存中每行Y分量数据的实际跨度<br>**src_u** - 源图像Cb分量的虚拟地址<br>**src_stride_u** - 内存中每行Cb分量数据的实际跨度<br>**src_v** - 源图像Cr分量的虚拟地址<br>**src_stride_v** - 内存中每行Cr分量数据的实际跨度<br>**dst_y** - 目的图像Y分量的虚拟地址<br>**dst_stride_y** - 内存中每行Y分量数据的实际跨度<br>**dst_uv** - 目的图像CbCr分量的虚拟地址<br>**dst_stride_uv** - 内存中每行CbCr分量数据的实际跨度<br>**width** - 每行图像数据中像素的数量<br>**height** - 图像数据像素的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

## I422ToNV12

```c
int I422ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u,
const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 属性 | 说明 |
|------|------|
| 功能 | 将一帧YCbCr 422数据转换成semi-plannar YCbCr 420数据。可用于full range，也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用 |
| 参数 | **src_y** - 源图像Y分量的虚拟地址<br>**src_stride_y** - 内存中每行Y分量数据的实际跨度<br>**src_u** - 源图像Cb分量的虚拟地址<br>**src_stride_u** - 内存中每行Cb分量数据的实际跨度<br>**src_v** - 源图像Cr分量的虚拟地址<br>**src_stride_v** - 内存中每行Cr分量数据的实际跨度<br>**dst_y** - 目的图像Y分量的虚拟地址<br>**dst_stride_y** - 内存中每行Y分量数据的实际跨度<br>**dst_uv** - 目的图像CbCr分量的虚拟地址<br>**dst_stride_uv** - 内存中每行CbCr分量数据的实际跨度<br>**width** - 每行图像数据中像素的数量<br>**height** - 图像数据像素的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

## I400ToNV12

```c
int I400ToNV12(const uint8_t* src_y, int src_stride_y, uint8_t* dst_y, int dst_stride_y,
uint8_t* dst_uv, int dst_stride_uv, int width, int height);
```

| 属性 | 说明 |
|------|------|
| 功能 | 将一帧YCbCr 400数据转换成semi-plannar YCbCr 420数据。可用于full range，也可以用于limited range的数据。不涉及颜色空间转换，可灵活使用 |
| 参数 | **src_y** - 源图像Y分量的虚拟地址<br>**src_stride_y** - 内存中每行Y分量数据的实际跨度<br>**dst_y** - 目的图像Y分量的虚拟地址<br>**dst_stride_y** - 内存中每行Y分量数据的实际跨度<br>**dst_uv** - 目的图像CbCr分量的虚拟地址<br>**dst_stride_uv** - 内存中每行CbCr分量数据的实际跨度<br>**width** - 每行图像数据中像素的数量<br>**height** - 图像数据像素的有效行数 |
| 返回值 | 0, 正常结束; 非0, 参数异常 |

# 安装 sophon-media

sophon-media 在不同的 Linux 发行版上提供不同类型的安装方式。请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。以下描述中以"1.0.0"为示例，当前实际安装版本会有变化。

**下文中 $arch $system 根据实际架构进行配置：**
- 主机为 x86 cpu 的，$arch 为 amd64，$system 为 x86_64
- 主机为 arm64 或飞腾 cpu 的，$arch 为 arm64，$system 为 aarch64

## 如果使用 Debian/Ubuntu 系统

**sophon-media 安装包由六个文件构成：**
- sophon-media-soc-sophon-ffmpeg_1.0.0_arm64.deb
- sophon-media-soc-sophon-ffmpeg-dev_1.0.0_arm64.deb
- sophon-media-soc-sophon-opencv_1.0.0_arm64.deb
- sophon-media-soc-sophon-opencv-dev_1.0.0_arm64.deb
- sophon-media-soc-sophon-gstreamer_1.0.0_arm64.deb
- sophon-media-soc-sophon-gstreamer-dev_1.0.0_arm64.deb

其中：
- sophon-media-soc-sophon-ffmpeg/sophon-media-soc-sophon-opencv/sophon-media-soc-sophon-gstreamer 包含了 ffmpeg/opencv/gstreamer 运行时环境（库文件、工具等）
- sophon-media-soc-sophon-ffmpeg-dev/sophon-media-soc-sophon-opencv-dev/sophon-media-soc-sophon-gstreamer-dev 包含了开发环境（头文件、pkgconfig、cmake 等）
- 如果只是在部署环境上安装，则不需要安装 sophon-media-soc-sophon-ffmpeg-dev/sophon-media-soc-sophon-opencv-dev/sophon-media-soc-sophon-gstreamer-dev

依赖关系：
- sophon-media-soc-sophon-ffmpeg 依赖 sophon-libsophon 包
- sophon-media-soc-sophon-opencv 依赖 sophon-media-soc-sophon-ffmpeg
- 因此在安装次序上必须先安装 libsophon，然后 sophon-media-soc-sophon-ffmpeg，最后安装 sophon-media-soc-sophon-opencv
- sophon-media-soc-sophon-gstreamer 仅依赖 sophon-libsophon 包，与 sophon-media-soc-sophon-opencv 和 sophon-media-soc-sophon-ffmpeg 不存在依赖关系

### 安装步骤

1. 安装libsophon依赖库---参考《LIBSOPHON使用手册》
   ```
   sudo dpkg -i sophon-soc-libsophon_0.4.9_arm64.deb
   ```

2. 安装plugin依赖：
   ```shell
   sudo apt install libgstreamer1.0-dev gstreamer1.0-plugins-base libgstreamer-plugins-base1.0-dev \
   gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-dev gstreamer1.0-gl gstreamer1.0-tools \
   gstreamer1.0-plugins-good
   ```

3. 安装sophon-media
   ```shell
   sudo dpkg -i sophon-media-soc-sophon-ffmpeg_1.0.0_arm64.deb
   sudo dpkg -i sophon-media-soc-sophon-ffmpeg-dev_1.0.0_arm64.deb
   sudo dpkg -i sophon-media-soc-sophon-opencv_1.0.0_arm64.deb
   sudo dpkg -i sophon-media-soc-sophon-opencv-dev_1.0.0_arm64.deb
   sudo dpkg -i sophon-media-soc-sophon-gstreamer_1.0.0_arm64.deb
   sudo dpkg -i sophon-media-soc-sophon-gstreamer-dev_1.0.0_arm64.deb
   ```

4. 在终端执行如下命令，或者logout再login当前用户后即可使用安装的工具：
   ```shell
   source /etc/profile
   ```

**注意：**位于SOC模式时，系统已经预装了：
- sophon-media-soc-sophon-ffmpeg
- sophon-media-soc-sophon-opencv

只需要按照上述步骤安装：
- sophon-media-soc-sophon-ffmpeg-dev_1.0.0_arm64.deb
- sophon-media-soc-sophon-opencv-dev_1.0.0_arm64.deb
- sophon-media-soc-sophon-gstreamer_1.0.0_arm64.deb
- sophon-media-soc-sophon-gstreamer-dev_1.0.0_arm64.deb

### 安装位置

```
/opt/sophon/
├── libsophon-0.4.9
├── libsophon-current -> /opt/sophon/libsophon-0.4.9
├── sophon-ffmpeg_1.0.0
│   ├── bin
│   ├── data
│   ├── include
│   ├── lib
│   │   ├── cmake
│   │   └── pkgconfig
│   └── share
├── sophon-ffmpeg-latest -> /opt/sophon/sophon-ffmpeg_1.0.0
├── sophon-opencv_1.0.0
│   ├── bin
│   ├── data
│   ├── include
│   ├── lib
│   │   ├── cmake
│   │   ├── opencv4
│   │   └── pkgconfig
│   ├── opencv-python
│   ├── share
│   └── test
├── sophon-opencv-latest -> /opt/sophon/sophon-opencv_1.0.0
├── sophon-gstreamer_1.0.0
│   ├── data
│   ├── include
│   ├── lib
└── sophon-gstreamer-latest -> /opt/sophon/sophon-gstreamer_1.0.0
```

deb 包安装方式并不允许您安装同一个包的多个不同版本，但您可能用其它方式在 /opt/sophon 下放置了若干不同版本。在使用 deb 包安装时，/opt/sophon/sophon-ffmpeg-latest，/opt/sophon/sophon-opencv-latest 和 /opt/sophon/sophon-gstreamer-latest 会指向最后安装的那个版本。在卸载后，它会指向余下的最新版本（如果有的话）。

其中 include、lib/cmake、lib/pkgconfig 和 include 目录，分别由 sophon-media-soc-sophon-ffmpeg-dev、sophon-media-soc-sophon-opencv-dev 和 sophon-media-soc-sophon-gstreamer-dev 包安装产生。

### 卸载方式

**如果使用 Debian/Ubuntu 系统：**
```shell
sudo apt remove sophon-media-soc-sophon-opencv-dev sophon-media-soc-sophon-opencv
sudo apt remove sophon-media-soc-sophon-ffmpeg-dev sophon-media-soc-sophon-ffmpeg
sudo apt remove sophon-media-soc-sophon-gstreamer-dev sophon-media-soc-sophon-gstreamer
```
或者：
```shell
sudo dpkg -r sophon-media-soc-sophon-opencv-dev
sudo dpkg -r sophon-media-soc-sophon-opencv
sudo dpkg -r sophon-media-soc-sophon-ffmpeg-dev
sudo dpkg -r sophon-media-soc-sophon-ffmpeg
sudo dpkg -r sophon-media-soc-sophon-gstreamer-dev
sudo dpkg -r sophon-media-soc-sophon-gstreamer
```

## 如果使用其它 Linux 系统

**安装包由一个文件构成：**
- sophon-media-soc_1.0.0_aarch64.tar.gz

可以通过如下步骤安装：
1. 先按照《LIBSOPHON 使用手册》安装好 libsophon 包，然后
   ```shell
   tar -xzvf sophon-media-soc_1.0.0_aarch64.tar.gz
   sudo cp -r sophon-media_1.0.0_$system/* /
   sudo ln -s /opt/sophon/sophon-ffmpeg_1.0.0 /opt/sophon/sophon-ffmpeg-latest
   sudo ln -s /opt/sophon/sophon-opencv_1.0.0 /opt/sophon/sophon-opencv-latest
   sudo ln -s /opt/sophon/sophon-sample_1.0.0 /opt/sophon/sophon-sample-latest
   sudo sed -i "s/usr\/local/opt\/sophon\/sophon-ffmpeg-latest/g" /opt/sophon/sophon-ffmpeg-latest/lib/pkgconfig/*.pc
   sudo sed -i "s/^prefix=.*$/prefix=\/opt\/sophon\/sophon-opencv-latest/g" /opt/sophon/sophon-opencv-latest/lib/pkgconfig/opencv4.pc
   ```

2. 最后，安装bz2 libc6 libgcc依赖库（这部分需要根据操作系统不同，选择对应的安装包，这里不统一介绍）

3. 配置工作：
   ```shell
   # 添加库和可执行文件路径：
   sudo cp /opt/sophon/sophon-ffmpeg-latest/data/01_sophon-ffmpeg.conf /etc/ld.so.conf.d/
   sudo cp /opt/sophon/sophon-opencv-latest/data/02_sophon-opencv.conf /etc/ld.so.conf.d/
   sudo ldconfig
   sudo cp /opt/sophon/sophon-ffmpeg-latest/data/sophon-ffmpeg-autoconf.sh /etc/profile.d/
   sudo cp /opt/sophon/sophon-opencv-latest/data/sophon-opencv-autoconf.sh /etc/profile.d/
   sudo cp /opt/sophon/sophon-sample-latest/data/sophon-sample-autoconf.sh /etc/profile.d/
   source /etc/profile
   ```

### 卸载方式
```shell
sudo rm -f /etc/ld.so.conf.d/01_sophon-ffmpeg.conf
sudo rm -f /etc/ld.so.conf.d/02_sophon-opencv.conf
sudo ldconfig
sudo rm -f /etc/profile.d/sophon-ffmpeg-autoconf.sh
sudo rm -f /etc/profile.d/sophon-opencv-autoconf.sh
sudo rm -f /etc/profile.d/sophon-sample-autoconf.sh
sudo rm -f /opt/sophon/sophon-ffmpeg-latest
sudo rm -f /opt/sophon/sophon-opencv-latest
sudo rm -f /opt/sophon/sophon-sample-latest
sudo rm -rf /opt/sophon/sophon-ffmpeg_1.0.0
sudo rm -rf /opt/sophon/sophon-opencv_1.0.0
sudo rm -rf /opt/sophon/sophon-sample_1.0.0
sudo rm -rf /opt/sophon/opencv-bmcpu_1.0.0
```

## 注意事项

**- 如果需要用 sophon-opencv 的 python 接口，手动设置环境变量：**
```shell
export PYTHONPATH=$PYTHONPATH:/opt/sophon/sophon-media_1.0.0/opencv-python
```

# 使用 sophon-sample

sophon-sample 在不同的 Linux 发行版上提供不同类型的安装方式。请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。以下描述中"1.0.0"仅为示例，视当前实际安装版本会有变化。

**下文中 $arch $system 根据实际架构进行配置：**
- 主机为 x86 cpu 的，$arch 为 amd64，$system 为 x86_64
- 主机为 arm64 或飞腾 cpu 的，$arch 为 arm64，$system 为 aarch64

## 如果使用 Debian/Ubuntu 系统

**sophon-sample 安装包由以下文件构成：**
- sophon-media-soc-sophon-sample_1.0.0_arm64.deb

其中：
- sophon-media-soc-sophon-sample 包含了数个用于测试 sophon-ffmpeg/sophon-opencv 的应用程序
- sophon-media-soc-sophon-sample 依赖上一章节的 sophon-ffmpeg/sophon-opencv 包

### 安装步骤
1. 安装libsophon依赖库（参考《LIBSOPHON使用手册》）
2. 安装sophon-media（参考上一章节）
3. 安装sophon-sample
   ```shell
   sudo dpkg -i sophon-media-soc-sophon-sample_1.0.0_arm64.deb
   ```

### 安装位置
```
/opt/sophon/
├── libsophon-0.4.9
├── libsophon-current -> /opt/sophon/libsophon-0.4.9
├── sophon-ffmpeg_1.0.0
├── sophon-ffmpeg-latest -> /opt/sophon/sophon-ffmpeg_1.0.0
├── sophon-opencv_1.0.0
├── sophon-opencv-latest -> /opt/sophon/sophon-opencv_1.0.0
├── sophon-gstreamer_1.0.0
├── sophon-gstreamer-latest -> /opt/sophon/sophon-gstreamer_1.0.0
├── sophon-sample_1.0.0
│   ├── bin
│   │   ├── test_bm_restart
│   │   ├── test_ff_bmcv_transcode
│   │   ├── test_ff_scale_transcode
│   │   ├── test_ff_overlay_transcode
│   │   ├── test_ff_video_encode
│   │   ├── test_ff_video_xcode
│   │   ├── test_ff_hw_bmcv_transcode
│   │   ├── test_ff_resize_transcode
│   │   ├── test_ff_bmjpeg
│   │   ├── test_ff_bmjpeg_dec_recycle
│   │   ├── test_ff_hw_bmcv_transcode
│   │   ├── test_ff_sns_xcode
│   │   ├── test_ocv_jpubasic
│   │   ├── test_ocv_jpumulti
│   │   ├── test_ocv_vidbasic
│   │   ├── test_ocv_video_xcode
│   │   ├── test_ocv_vidmulti
│   │   ├── test_gst_transcode
│   │   ├── test_gst_bmcv_transcode
│   │   └── test_gst_vcmulti
│   ├── data
│   └── samples
└── sophon-sample-latest -> /opt/sophon/sophon-sample_1.0.0
```

deb 包安装方式并不允许您安装同一个包的多个不同版本，但您可能用其它方式在/opt/sophon下放置了若干不同版本。在使用deb包安装时/opt/sophon/sophon-sample-latest 会指向最后安装的那个版本。在卸载后，它会指向余下的最新版本（如果有的话）。

**注意：** soc 模式下，deb 安装包为 sophon-media-soc-sophon-sample_1.0.0_arm64.deb，安装位置同上。

### 卸载方式
**如果使用 Debian/Ubuntu 系统：**
```shell
sudo apt remove sophon-media-soc-sophon-sample
```
或者：
```shell
sudo dpkg -r sophon-media-soc-sophon-sample_1.0.0_arm64.deb
```

## 用例介绍

### test_bm_restart

此用例主要用于测试 ffmpeg 模块下的视频解码功能和性能，支持多路解码和断线重连功能。用户可以通过用例监测视频、码流的解码情况。

```
test_bm_restart [api_version] [yuv_format] [pre_allocation_frame] [codec_name] [sophon_idx] [zero_copy] [input_file/url] [input_file/url]
```

**参数：**

- **api_version**
  指定解码过程使用的 ffmpegAPI 版本
  - 0: 使用老版本的解码 avcodec_decode_video2 接口
  - 1: 使用新版解码 avcodec_send_packet 接口
  - 2: 使用 av_parser_parse2 的 API 用于抓包

- **yuv_format**
  是否压缩数据
  - 0 表示不压缩
  - 1 表示压缩

- **pre_allocation_frame**
  允许的缓存帧数，最多为 64

- **codec_name**
  指定解码器，可选择 h264_bm/hevc_bm，no 为不指定

- **sophon_idx**
  若处于 SOC 模式，该选项可以随意设置（不可为空），其值将会被忽略

- **zero_copy**
  SOC 模式，0 表示启用 Host memory，1 表示不启用

- **input_file_or_url**
  输入的文件路径或码流地址

**示例：**
```
test_bm_restart 1 0 1 no 0 0 ./example0.mp4 ./example1.mp4 ./example2.mp4
```

### test_ff_bmcv_transcode

此用例主要用于测试 ffmpeg 模块下的视频转码功能和性能，通过调用 ff_video_decode、ff_video_encode 用例中的数据类型和函数，来实现先解码后编码的转码过程，以此保证解码和编码功能的正确性。同时此用例也可测试 ffmpeg 下的转码性能，运行时程序会输出即时转码帧率供参考。

```
test_ff_bmcv_transcode [platform] [src_filename] [output_filename] [encode_pixel_format] [codecer_name] [width] [height] [frame_rate] [bitrate] [thread_num]
```

**参数：**

- **platform**
  平台：soc

- **src_filename**
  输入文件名如 x.mp4 x.ts 等

- **output_filename**
  转码输出文件名如 x.mp4，x.ts 等

- **encode_pixel_format**
  编码格式如 I420

- **encoder_name**
  编码 h264_bm，h265_bm

- **width**
  编码宽度 (32，4096]

- **height**
  编码高度 (32，4096]

- **frame_rate**
  编码帧率

- **bitrate**
  编码比特率 encode bitrate 500 < bitrate < 10000

- **thread_num**
  线程数量

**示例：**

soc mode example:
```
test_ff_bmcv_transcode soc example.mp4 test.ts I420 h264_bm 800 400 25 3000 3
```

# test_ff_scale_transcode

此用例主要用于测试 ffmpeg 下视频转码的功能和性能。此功能通过先解码再编码的过程实现，主要调用了 ff_video_decode, ff_video_encode 中的数据类型和函数。

```
test_ff_scale_transcode [src_filename] [output_filename] [encode_pixel_format] [codecer_name] [height] [width] [frame_rate] [bitrate] [thread_num] [zero_copy] [sophon_idx]
```

## 参数

- **src_filename**: 输入文件名如 x.mp4 x.ts…
- **output_filename**: 输出文件名如 x.mp4 x.ts…
- **encode_pixel_format**: 编码格式如 I420
- **codecer_name**: 编码名如 h264_bm,hevc_bm,h265_bm
- **height**: 编码高度
- **width**: 编码宽度
- **frame_rate**: 编码帧率
- **bitrate**: 编码比特率
- **thread_num**: 使用线程数
- **zero_copy**: 0: copy host mem,1: nocopy.
- **sophon_idx**: 设备索引

## 示例

```
test_ff_scale_transcode example.mp4 test.ts I420 h264_bm 800 400 25 3000 3 0 0
```

# test_ff_overlay_transcode

此用例主要用于测试 ffmpeg 下视频添加滤镜的功能和性能。此功能通过先解码再编码的过程实现，主要调用了 ff_video_decode, ff_video_encode 中的数据类型和函数。

```
test_ff_overlay_transcode [src_filename] [output_filename] [encoder_name] [zero_copy] [sophon_idx] [overlay_num] [overlay_filepath_1] [x] [y] [overlay_filepath_2] [x] [y]
```

## 参数

- **src_filename**: 输入文件名如 x.mp4 x.ts…
- **output_filename**: 输出文件名如 x.mp4 x.ts…
- **encoder_name**: 编码名如 h264_bm,hevc_bm,h265_bm
- **zero_copy**: 0: copy host mem,1: nocopy.
- **sophon_idx**: 设备索引
- **overlay_num**: 滤镜个数
- **overlay_filepath_1**: 滤镜1输入路径
- **x**: 在源视频上 overlay1 的水平位置
- **y**: 在源视频上 overlay1 的垂直位置
- **overlay_filepath_2**: 滤镜2输入路径
- **x**: 在源视频上 overlay2 的水平位置
- **y**: 在源视频上 overlay2 的垂直位置

## 示例

```
test_ff_overlay_transcode src.mp4 out.ts h264_bm 0 0 2 overlay_1.264 10 10 overlay_2.264 500 500
```

# test_ff_video_encode

此用例主要用于测试 ffmpeg 模块下视频的编码功能。输入的视频限制为 I420 和 NV12 格式。通过调用此用例用户可以得到封装好的视频文件,ffmpeg 支持的视频格式均可。

```
test_ff_video_encode <input file> <output file> <encoder> <width> <height> <roi_enable> <input pixel format> <bitrate(kbps)> <frame rate>
```

## 参数

- **input_file**: 输入视频路径
- **output_file**: 输出视频文件名
- **encoder**: H264 或者 H265, 默认为 H264
- **width**: 视频宽度, 输出与输入需一致,256 <= width <= 8192
- **height**: 视频高度, 输出与输入需一致,128 <= height <= 8192
- **roi_enable**: 是否开启 roi,0 表示不开启,1 表示开启
- **input_pixel_format**: I420(YUV, 默认), NV12.
- **bitrate**: 输出比特率,10 < bitrate <= 100000, 默认为帧率 x 宽 x 高/8
- **framerate**: 输出帧率,10 < framerate <= 60, 默认为 30

## 示例

- `test_ff_video_encode <input file> <output file> H264 width height 0 I420 3000 30`
- `test_ff_video_encode <input file> <output file> H265 width height 0 I420`
- `test_ff_video_encode <input file> <output file> H265 width height 0 NV12`
- `test_ff_video_encode <input file> <output file> H265 width height 0`

# test_ff_video_xcode

此用例主要用于测试 ffmpeg 下视频转码的功能和性能。此功能通过先解码再编码的过程实现, 主要调用了 ff_video_decode,ff_video_encode 中的数据类型和函数。转码后的视频分辨率与原视频一致, 比特率不能超过 10000kbps 或小于 500kbps, 否则会被置为默认值 3000kbps。转码后的视频如比特率与原视频一致, 那么时长也应一致。有一些丢帧属于正常现象。

```
test_ff_video_xcode <input file> <output file> encoder framerate bitrate(kbps) is-dmabuffer
```

## 参数

- **input_file**: 输入文件
- **output_file**: 输出文件
- **encoder**: 编码器 H264 或者 H265.
- **isdmabuffer**: 是否开启内存一致,1 表示不开启,0 表示开启

## 示例

- `test_ff_video_xcode ./file_example_MP4_1920_18MG.mp4 tran5.ts H264 30 3000 1`
- `test_ff_video_xcode ./file_example_MP4_1920_18MG.mp4 tran5.ts H264 30 3000 0`

# test_ff_hw_bmcv_transcode

此用例主要用于测试 ffmpeg 下视频转码的功能和性能。此功能通过先解码再编码的过程实现, 主要调用了 ff_video_decode,ff_video_encode 中的数据类型和函数。

```
test_ff_hw_bmcv_transcode [platform] [src_filename] [output_filename] [codecer_name] [width] [height] [frame_rate] [bitrate] [thread_num] [en_bmx264] [zero_copy] [sophon_idx]
```

## 参数

- **platform**: soc
- **src_filename**: 输入文件
- **output_filename**: 输出文件
- **codecer_name**: 编码器 H264 或者 H265.
- **width**: 编码视频宽度
- **height**: 编码视频高度
- **frame_rate**: 编码帧率
- **bitrate**: 编码比特率
- **thread_num**: 线程数
- **en_bmx264**: soc : 0
- **zero_copy**: soc : 0
- **sophon_idx**: soc : 0

## 示例

- `test_ff_hw_bmcv_transcode soc INPUT.264 out.264 h264_bm 1920 1080 25 3000 0 0 0`

# test_ff_sns_xcode

此用例主要用于测试基于 v4l2与ffmpeg 的视频转码功能和性能, 该功能通过先解码再编码的过程实现,它支持从视频采集设备(如摄像头)直接采集视频流, 经过解码、宽动态WDR、ISP处理、编码等流程,最终输出为指定格式的视频文件。它可以验证转码、编码、基于v4l2的vi与isp驱动的采集、处理等全流程的功能和性能。

```
test_ff_sns_xcode [devnum] [input_dev] [output_file] [wdr_on] ... [encoder] [framerate] [bitrate(kbps)] [use_isp] [v4l2_buf_num] [framenum] [loopflag]
```

## 参数

- **devnum**: 输入设备(通常为摄像头)的数量, 范围为[1,12]
- **input_dev**: 输入文件或设备路径, 如 /dev/video0
- **output_file**: 输出文件
- **wdr_on**: 是否开启宽动态(WDR)功能
- **encoder**: 编码名如 H264 或 H265, 默认为H264
- **framerate**: 编码帧率
- **bitrate(kbps)**: 编码比特率
- **use_isp**: 是否使用ISP硬件处理, 0表示不使用, 1表示使用
- **v4l2_buf_num**: v4l2 缓冲区数量
- **framenum**: 采集帧数
- **loopflag**: 当 loopflag=0 时, 程序会根据设定的帧数(framenum)进行采集、编码和解码, 处理完成后自动结束, 生成有效的视频文件; 当 loopflag=1 时，程序会持续不断地进行采集、编码和解码, 不会根据帧数停止, 也不会生成有效的视频文件, 主要用于持续性能测试或压力测试

## 示例

```
test_ff_sns_xcode 6 /dev/video0 /mnt/video0.264 0 /dev/video1 /mnt/video1.264 0 /dev/video2 /mnt/video2.264 0 /dev/video3 /mnt/video3.264 0 /dev/video4 /mnt/video4.264 0 /dev/video5 /mnt/video5.264 0 H264 30 3000 1 10 901 0
```

**注意**: [input_dev] [output_file] [wdr_on] 这三个参数的数量都要跟[devnum]保持一致, 多输入设备时这三个参数需要连续输入。

# test_ff_resize_transcode

此用例主要用于测试 ffmpeg 下视频转码的功能和性能。此功能通过先解码再编码的过程实现, 主要调用了 ff_video_decode,ff_video_encode 中的数据类型和函数。

```
test_ff_resize_transcode [src_filename] [output_filename] [encode_pixel_format] [codecer_name] [height] [width] [frame_rate] [bitrate] [thread_num] [zero_copy] [sophon_idx]
```

## 参数

- **platform**: soc
- **src_filename**: 输入文件
- **output_filename**: 输出文件
- **encode_pixel_format**: 编码格式如 I420
- **codecer_name**: 编码名如 h264_bm , hevc_bm , h265_bm
- **width**: 编码视频宽度
- **height**: 编码视频高度
- **frame_rate**: 编码帧率
- **bitrate**: 编码比特率
- **thread_num**: 线程数
- **zero_copy**: 0: copy host mem,1: nocopy.
- **sophon_idx**: 设备索引

## 示例

```
test_ff_resize_transcode example.mp4 test.ts I420 h264_bm 800 400 25 3000 3 0 0
```

# test_gst_transcode

此用例主要用于测试 gstreamer 下视频转码的功能。此功能通过先解码再编码的过程实现, 支持 H.264/H.265/JPEG 等格式输入。

```
test_gst_transcode [video_path] [output_path] [dec_type] [enc_type] [bps] [gop] [gop_preset] [cqp] [qp_min] [qp_max] [q_factor]
```

## 参数

- **video_path,(-v)**: 输入文件
- **output_path,(-o)**: 输出文件
- **dec_type,(-d)**: 输入编解码格式, 1 表示 h264, 2 表示 h265, 3 表示 JPEG, 4 表示 decode bin
- **enc_type,(-e)**: 输出编解码格式, 1 表示 h264, 2 表示 h265, 3 表示 JPEG
- **bps,(-b)**: 编码中的目标比特率
- **gop,(-g)**: h26x编码两个 I 帧之间的间隔
- **gop_preset,(-p)**: h26x编码 GOP 结构预设选项 [1-7]
- **cqp,(-q)**: h26x编码器中使用恒定质量模式, 需满足bsp >= 0
- **qp_min,(-m)**: h26x编码过程中允许使用的最小量化参数值
- **qp_max,(-x)**: h26x编码过程中允许使用的最大量化参数值
- **q_factor,(-f)**: JPEG 压缩中的质量参数

## 示例

- h265转码成h264 : `test_gst_transcode -v input.265 -d 2 -e 1 -g 50 -b 2000000 -o output.h264`
- h265转码成h265 : `test_gst_transcode -v input.265 -d 2 -e 2 -g 50 -b 2000000 -o output.h265`
- mp4转码成h264 : `test_gst_transcode -v input.mp4 -d 4 -e 1 -g 50 -b 2000000 -o output.h264`
- mp4转码成h265 : `test_gst_transcode -v input.mp4 -d 4 -e 2 -g 50 -b 2000000 -o output.h265`

**注意**: 当输入文件是mp4这种封装格式时, 需要使用 -d 4 来指定解封装器为 decode bin, 表示由系统去自行识别解码器类型。

# test_gst_bmcv_transcode

此用例主要用于测试 gstreamer 下视频转码的功能。此功能通过先解码再vpss再编码的过程实现, 支持 H.264/H.265/JPEG 等格式输入。

```
test_gst_bmcv_transcode [video_path] [output_path] [dec_type] [enc_type] [vpss_left] [vpss_right] [vpss_top] [vpss_bottom] [out_width] [out_height] [out_format] [save_decoded] [save_vpss]
```

## 参数

- **video_path,(-v)**: 输入文件
- **output_path,(-o)**: 输出文件
- **dec_type,(-d)**: 输入编解码格式, 1 表示 h264, 2 表示 h265, 3 表示 JPEG, 4 表示 decode bin
- **enc_type,(-e)**: 输出编解码格式, 1 表示 h264, 2 表示 h265, 3 表示 JPEG
- **vpss_left,(-l)**: 图像左侧裁剪像素
- **vpss_right,(-r)**: 图像右侧裁剪像素
- **vpss_top,(-t)**: 图像上侧裁剪像素
- **vpss_bottom,(-b)**: 图像下侧裁剪像素
- **out_width,(-w)**: 输出图像宽度
- **out_height,(-h)**: 输出图像高度
- **out_format,(-f)**: 输出图像像素格式（如：I420、NV12、NV16、RGB）
- **save_decoded,(-s)**: 保存解码后的原始 YUV 数据
- **save_vpss,(-S)**: 保存 VPSS 处理后的 YUV 数据

## 示例

```
test_gst_bmcv_transcode -v input.265 -d 2 -e 1 -l 960 -t 540 -r 0 -b 0 -w 960 -h 540 -f I420 -o output.h264
```

**注意**: 当输入文件是mp4这种封装格式时, 需要使用 -d 4 来指定解封装器为 decode bin, 表示由系统去自行识别解码器类型。

# test_gst_vcmulti

此用例主要用来测试编解码帧率，会输出每个通道的帧率。

test_gst_vcmulti [video_path] [codec_type] [is_enc] [num_chl] [disp] [trans_type]

参数：

- **-video_path,(-v)**  
  视频文件路径（进行编码测试的时候，内部使用 videotestsrc 生成1080p的 yuv 测试数据作为输入，不需要特别指定输入文件）

- **-codec_type,(-c)**  
  编解码器类型, 1 表示 h264, 2 表示 h265, 3 表示 JPEG

- **-is_enc,(-e)**  
  0 表示解码, 1 表示编码, 2 表示转码

- **-num_chl,(-n)**  
  编解码通道数

- **-disp,(-d)**  
  1 每个通道实时帧率统计， 0 每秒帧率统计

- **-trans_type,(-t)**  
  当 is_enc 设置为 2 时, 进行转码测试，编码类型: 1 表示 h264, 2 表示 h265, 3 表示 JPEG

示例：

解码：
- 264: test_gst_vcmulti -v input.h264 -c 1 -e 0 -n 16 -d 1
- 265: test_gst_vcmulti -v input.h265 -c 2 -e 0 -n 16 -d 1
- jpeg: test_gst_vcmulti -v input.jpeg -c 3 -e 0 -n 32 -d 1

编码：
- 264: test_gst_vcmulti -c 1 -e 1 -n 16 -d 1
- 265: test_gst_vcmulti -c 2 -e 1 -n 16 -d 1
- jpeg: test_gst_vcmulti -c 3 -e 1 -n 16 -d 1

转码：
- 264->265: test_gst_vcmulti -v input.h264 -c 1 -e 1 -n 12 -d 1 -t 2
- 264->jpeg: test_gst_vcmulti -v input.h264 -c 1 -e 1 -n 12 -d 1 -t 3

注意：转码h26x互转的情况，由于内存开销大，-n需要小于16。

# gst-launch-1.0

## JPEG编码测试

此用例主要用于测试 gstreamer 下jpeg编码的功能和性能。

功能测试：

```shell
gst-launch-1.0 filesrc location=640x480_420p.yuv \
! rawvideoparse format=i420 width=640 height=480 ! bmjpegenc \
! filesink location=case0.jpg
```

性能测试：

```shell
gst-launch-1.0 filesrc location=640x480_420p.yuv \
! rawvideoparse format=i420 width=640 height=480 ! bmjpegenc \
! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **rawvideoparse** - 解析原始视频数据, 指定格式为I420(YUV420p), 宽度为640,高度为480
- **bmjpegenc** - 使用BMJPEG编码器将视频数据编码为JPEG格式
- **filesink** - 将编码后的JPEG数据写入文件中
- **fakesink** - 直接将编码后的数据丢弃, 不写入文件

## JPEG解码测试

此用例主要用于测试 gstreamer 下jpeg解码的功能和性能, 调用了 bmdec 插件实现图像解码的硬件加速。

功能测试：

```shell
gst-launch-1.0 filesrc location=JPEG_1920x1088_yuv420_planar.jpg ! jpegparse \
! bmdec ! filesink location=case12.yuv
```

性能测试：

```shell
gst-launch-1.0 filesrc location=JPEG_1920x1088_yuv420_planar.jpg ! jpegparse \
! bmdec ! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **jpegparse** - 解析JPEG数据
- **bmdec** - 使用BM解码器解码JPEG数据
- **filesink** - 将解码后的YUV数据写入文件中
- **fakesink** - 直接将解码后的数据丢弃, 不写入文件

## H.265视频编码测试

此用例主要用于测试 gstreamer 下H.265视频编码的功能和性能。

功能测试：

```shell
gst-launch-1.0 filesrc location=1080p_nv12.yuv \
! rawvideoparse format=nv12 width=1920 height=1080 \
! bmh265enc gop=50 ! filesink location=case0.h265
```

性能测试：

```shell
gst-launch-1.0 filesrc location=1080p_nv12.yuv \
! rawvideoparse format=nv12 width=1920 height=1080 \
! bmh265enc gop=50 ! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **rawvideoparse** - 解析原始视频数据, 指定格式为NV12, 宽度为1920, 高度为1080
- **bmh265enc** - 使用BM H.265编码器对视频进行H.265编码, 设置GOP为50
- **filesink** - 将编码后的H.265视频数据写入文件中
- **fakesink** - 直接将编码后的数据丢弃, 不写入文件

## H.264视频解码测试

此用例主要用于测试 gstreamer 下H.264视频解码的功能和性能。

功能测试：

```shell
gst-launch-1.0 filesrc location=1920x1080.mp4 ! qtdemux ! h264parse ! bmdec \
! video/x-raw,format=NV12 ! filesink location=case1.nv12
```

性能测试：

```shell
gst-launch-1.0 filesrc location=1920x1080.mp4 ! qtdemux ! h264parse ! bmdec \
! video/x-raw,format=NV12 ! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **qtdemux** - 解封装 QuickTime 格式文件的元素，用于提取其中的音视频流
- **h264parse** - 解析H.264数据
- **bmdec** - 使用BM解码器解码视频数据
- **video/x-raw,format=NV12** - 将解码后的视频数据转换为NV12格式
- **filesink** - 将转换后的NV12视频数据写入文件中
- **fakesink** - 直接将解码后的数据丢弃, 不写入文件

## 视频转码测试

此用例主要用于测试 gstreamer 下视频转码的功能和性能，此功能通过先解码再编码的过程实现。

功能测试：

```shell
gst-launch-1.0 -e filesrc location=1920x1080.mp4 ! qtdemux ! h264parse ! bmdec \
! bmh265enc gop=50 bps=1000000 qp-min=24 qp-max=45 gop-preset=5 \
! filesink location=case4.h265
```

性能测试：

```shell
gst-launch-1.0 -e filesrc location=1920x1080.mp4 ! qtdemux ! h264parse ! bmdec \
! bmh265enc gop=50 bps=1000000 qp-min=24 qp-max=45 gop-preset=5 \
! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **qtdemux** - 解封装 QuickTime 格式文件的元素，用于提取其中的音视频流
- **h264parse** - 解析H.264数据
- **bmdec** - 使用BM解码器解码视频数据
- **bmh265enc** - 使用BM H.265编码器对视频进行H.265编码, 设置GOP为50, 比特率为1000000, 最小量化参数为24, 最大量化参数为45, GOP预设值为5
- **filesink** - 将编码后的H.265视频数据写入文件中
- **fakesink** - 直接将编码后的数据丢弃, 不写入文件

## VPSS色彩转换测试

此用例主要用于测试 gstreamer 下VPSS色彩转换的功能和性能。

功能测试：

```shell
gst-launch-1.0 filesrc location=1920x1080_yuv420p.bin blocksize=3110400 num-buffers=1 \
! video/x-raw, format=I420, width=1920, height=1080, framerate=1/1 ! bmvpss \
! video/x-raw, format=RGB, width=1920, height=1080, framerate=1/1 \
! filesink location=vpss_case01.bin
```

性能测试：

```shell
gst-launch-1.0 filesrc location=1920x1080_yuv420p.bin blocksize=3110400 num-buffers=1 \
! video/x-raw, format=I420, width=1920, height=1080, framerate=1/1 ! bmvpss \
! video/x-raw, format=RGB, width=1920, height=1080, framerate=1/1 \
! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据, 设置了blocksize(读取数据块的大小)和num-buffers(读取数据包数量)
- **video/x-raw, format=I420, width=1920, height=1080, framerate=1/1** - 输入数据为I420格式, 指定了宽度、高度和帧率
- **bmvpss** - 使用BMVPSS插件处理视频流
- **video/x-raw, format=RGB, width=1920, height=1080, framerate=1/1** - 处理后的数据为RGB格式, 指定了宽度、高度和帧率
- **filesink** - 将处理后的RGB格式数据写入文件中
- **fakesink** - 直接将处理后的数据丢弃, 不写入文件

## VPSS缩放测试

此用例主要用于测试 gstreamer 下VPSS缩放的功能和性能。

功能测试：

```shell
gst-launch-1.0 filesrc location=2048x2048_rgb.bin blocksize=12582912 num-buffers=1 \
! video/x-raw, format=RGB, width=2048, height=2048,framerate=1/1 ! bmvpss \
! video/x-raw, format=RGB, width=16, height=16, framerate=1/1 \
! filesink location=vpss_case15.bin
```

性能测试：

```shell
gst-launch-1.0 filesrc location=2048x2048_rgb.bin blocksize=12582912 num-buffers=1 \
! video/x-raw, format=RGB, width=2048, height=2048,framerate=1/1 ! bmvpss \
! video/x-raw, format=RGB, width=16, height=16, framerate=1/1 \
! fakesink
```

管道详细步骤：

- **filesrc** - 从文件中读取数据, 设置了blocksize(读取数据块的大小)和num-buffers(读取数据包数量)
- **video/x-raw, format=RGB, width=2048, height=2048, framerate=1/1** - 数据数据为RGB格式, 指定了宽度、高度和帧率
- **bmvpss** - 使用BMVPSS插件处理视频流
- **video/x-raw, format=RGB, width=16, height=16, framerate=1/1** - 处理后的数据为RGB格式, 指定了宽度、高度和帧率
- **filesink** - 将处理后的RGB格式数据写入文件中
- **fakesink** - 直接将处理后的数据丢弃, 不写入文件

## AUDIO播音测试

此用例主要用于测试 GStreamer 中 AUDIO 的播音功能，其他音频相关的功能可以直接参考公版的用法，均能兼容适配。

功能测试：

```shell
gst-launch-1.0 filesrc location=8k_2chn.wav ! wavparse ! audioconvert \
! audioresample ! audio/x-raw,rate=8000,channels=2 ! alsasink device=hw:1,0
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **wavparse** - 解析WAV音频数据
- **audioconvert** - 转换音频格式，以便与 alsasink 兼容
- **audioresample** - 重采样音频数据，以适应目标设备的采样率
- **audio/x-raw,rate=8000,channels=2** - 设置音频数据的采样率为8000Hz，通道数为2
- **alsasink device=hw:1,0** - 将音频数据输出到指定的 ALSA 设备（在此例中为 hw:1,0）

## HDMI显示测试

此用例借助bmvpss将视频显示到hdmi，直接确认解码正确性，测试覆盖不同分辨率及编码格式。

功能测试：

```shell
gst-launch-1.0 filesrc location= input.avi ! avidemux ! xxxparse ! bmdec \
! bmvpss ! 'video/x-raw, format=(string)I420, width=(int)640, height=(int)480' \
! kmssink driver-name=cvitek plane-id=36 force-modesetting=true
```

管道详细步骤：

- **filesrc** - 从文件中读取数据
- **avidemux** - 解封装 AVI 格式文件的元素，用于提取其中的音视频流
- **xxxparse** - 解析视频数据, xxx 代表具体的编解码格式解析器
- **bmdec** - 使用 BM 解码器解码视频数据
- **bmvpss** - 使用 BM VPSS 插件处理视频流
- **video/x-raw, format=(string)I420, width=(int)640, height=(int)480** - 将处理后的视频数据转换为 I420 格式, 指定宽度和高度
- **kmssink driver-name=cvitek plane-id=36 force-modesetting=true** - 将处理后的视频数据输出到指定的 HDMI 设备

# 多媒体客户常见问题列表

## 4K图片的问题

答：有些客户需要的图片较大如8K等，由于VPP只支持4K大小的图片，所以通过opencv读取图片后，会自动保持比例缩放到一个4K以内的尺寸。

如果客户需要传递原始图片的坐标位置给远端，可以有以下两种做法：

1. imread中设置flag = IMREAD_UNCHANGED_SCALE，此时图片不会真正解码，会在mat.rows/cols中返回图片的原始宽高，然后可根据缩放比例计算得到原图的坐标
2. 传递相对坐标给远端，即坐标x/缩放后的宽， 坐标y/缩放后的高传递到远端。这步相对坐标计算也可以在远端完成，然后可以根据远端知道的原始图像宽高计算得到正确的原图坐标

## Opencv读取图片后，cvMat转为bmimage, 之后，调用bmcv_image_vpp_convert做缩放或者颜色空间转换，得到的图片不一致

原因分析：opencv内部的转换矩阵和bmcv_image_vpp_convert使用的转换矩阵不一致，需要调用bmcv_image_vpp_csc_matrix_covert, 并且指定CSC_YPbPr2RGB_BT601来进行转换才能保持一致。

## Opencv imread读取图片性能问题

原因分析：如果碰到图片小于16x16大小的图片，或者progressive 格式的jpeg，芯片不能实现加速，结果走了CPU的路径，导致客户发现图片解码并没有加速。

## VideoWriter.write性能问题，有些客户反应，存文件慢

解析：就目前来看看采用YUV采集，然后编码10-20ms之间写入一帧数据属于正常现象。

## Ffmpeg的阻塞问题

原因分析：如果没有及时释放avframe，就会导致阻塞，vpu内部是循环buffer。

## 关于什么时候调用uploadMat/downloadMat接口的问题

解析：当创建了一个cv::Mat, 然后调用cv::bmcv里面的接口进行了一些处理后，设备内存的内容改变了，这时候需要downloadMat来同步一下设备内存和系统内存。当调用了cv::resize等opencv原生的接口后，系统内存的内容改变了，需要uploadMat，使设备内存和系统内存同步。

## opencv下如何获取视频帧的timestamp？

答：opencv原生提供了获取timestamp的接口，可以在cap.read()每一帧后获取当前帧的timestamp.

代码如下：

```cpp
Mat frame;
cap.read(frame);
/* 获取timestamp，返回值为double类型 */
int64_t timestamp = (int64_t)cap.getProperty(CAP_PROP_TIMESTAMP);
```

## SA3 opencv下videocapture经常5分钟左右断网的解决方案

# RTSP连接超时问题解决方案

**问题**：在UDP方式下，SA3经常发生RTSP数据连上后3-5分钟就"connection timeout"的问题

**解决方案**：更新最新的路由板软件

**验证方法**：用TCP测试，如果TCP没有问题可以确认是这类问题

## 使用TCP方式

```bash
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"
```

执行应用（如果用sudo执行，需要sudo -E把环境变量带过去）

注意：最新的middleware-soc将使用TCP作为默认协议，对原来客户需要使用UDP传输协议的，需要引导客户按照下面方式进行设置

## 使用UDP方式

```bash
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;udp"
```

执行应用（如果用sudo执行，需要sudo -E把环境变量带过去）

**UDP适用环境**：当网络带宽比较窄，比如4G/3G等移动通信系统，此时用udp比较合适

**TCP适用环境**：网络带宽足够，对视频花屏要求比较高，对延时要求较小的应用场景，适合TCP

# 如何获取RTSP中原来的timestamp

**答**：opencv中默认获取的rtsp时间戳是从0开始的，如果想获取rtsp中的原始时间戳，可以用环境变量进行控制，然后按照问题1进行获取即可

```bash
export OPENCV_FFMPEG_CAPTURE_OPTOINS="keep_rtsp_timestamp;1"
```

注意：外置的options会覆盖内部默认的设置，因此最好按照完整的options来设置

```bash
export OPENCV_FFMPEG_CAPTURE_OPTIONS="keep_rtsp_timestamp;1|buffer_size;1024000|max_delay;500000|stimeout;20000000"
```

# 如何判断视频花屏的原因

**答**：这里提的视频花屏是长时间的花屏，对于偶尔的花屏有可能是网络数据传输错误导致的，此类不属于应用代码可控的方位。如果视频出现长时间的花屏，很大概率是由于视频帧读取不及时，导致内部缓存满以后，socket recv buffer溢出导致的。

1. 将加大rmem_max到2M，如果此时花屏消失，说明应用的数据处理抖动很大，应该要加大buffer queue进行平滑

```bash
echo 2097152 > /proc/sys/net/core/rmem_max
```

2. 用netstat -na，一般是一下格式，找到rtsp的那个端口（udp在应用中会有打印，tcp的话可以看目标rtsp地址），这里的Recv-Q，Send-Q在正常情况应该都是0，或者不满的，如果Recv-Q经常有很大的数，就说明overflow了。一般Send-Q不会出问题，如果这个也很大的话，那么很可能network driver驱动挂死了。

```bash
Proto Recv-Q Send-Q Local Address Foreign Address State
tcp 0 0 0.0.0.0:111 0.0.0.0:* LISTEN
```

# 无法连接RTSP？

**答**：可以通过ffmpeg固有命令来进行连接测试：（url为rtsp连接地址）

```bash
ffmpeg -rtsp_transport tcp -i url -f rawvideo -y /dev/null
或者
ffmpeg -rtsp_transport udp -i url -f rawvideo -y /dev/null
```

若以上无法连接成功，请检查网络。

# 确认解码器是否能正常工作

**答**：（url为文件名或者rtsp连接地址）

```bash
ffmpeg -i url -f rawvideo -y /dev/null
```

# 确认解码器和vpp的OpenCV接口是否正常工作

**答**：

```bash
vidmulti number_of_instances url1 url2
```

# 解码不正确或者无法解码的最终调试手段

**答**：如果经常各种调试后，在现场仍然无法解决问题，可以通过打开环境变量，把问题发生前后的数据dump下来，供后续进行进一步分析

在SOC模式下

```bash
echo "0 0 1000 100" > /proc/vpuinfo
```

(dump第1个core的第1个instance的码流数据)

这个配置会在两个文件之间循环存储1000帧数据，当问题发生的时候，把这两个发生前后的那个1000帧文件拷贝回来就可以。两个文件的存储位置在/data/core_%dinst%d_stream%d.bin。

# 判断RTSP是否正常工作

**答**：

**方法一**：通过vlc播放视频(推荐)，分别设置tcp，udp方式

**方法二**：使用vidmutil测试程序播放，vidmutil默认是 udp方式，通过设置环境变量使用tcp方式。

```bash
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|buffer_size;1024000|max_delay;50000"
sudo -E ./vidmulti thread_num input_video [card] [enc_enable] input_video [card] [enc_enable]...
```

# 播放RTSP流出现断连情况验证

**答**：可以使用vlc播放相同的视频，在相同的时间下，看vlc播放是否有断连的情况，注意设置vlc的缓冲区大小。

# 验证当前RTSP服务输出的视频是否有花屏

**答**：使用vlc播放视频，持续一段时间，看视频是否有花屏

# 查看RTSP服务是否实时推流

**答**：通过rtspserver日志，查看当前播放的文件是否正在发送。

# 对于cvQueryFrame等老的OpenCV接口支持状况

**答**：

有些客户采用旧版opencv的C接口，接口列表如下

```c
void cvReleaseCapture( CvCapture** pcapture )
IplImage* cvQueryFrame( CvCapture* capture )
int cvGrabFrame( CvCapture* capture )
IplImage* cvRetrieveFrame( CvCapture* capture, int idx )
double cvGetCaptureProperty( CvCapture* capture, int id )
int cvSetCaptureProperty( CvCapture* capture, int id, double value )
int cvGetCaptureDomain( CvCapture* capture)
CvCapture * cvCreateCameraCapture (int index)
CvCapture * cvCreateFileCaptureWithPreference (const char * filename, int apiPreference)
CvCapture * cvCreateFileCapture (const char * filename)
```

对于这些接口，大部分都是支持的，只有返回值是iplImage的接口无法支持，这是因为我们硬件底层的ion内存类型是保存在MAT的uMatData类型中的，而iplIMage类型没有uMatData数据结构。

因此对于客户目前使用 cvQueryFrame接口的，建议客户基于cap.read接口封一个返回值为Mat数据的C函数接口，不要直接调用opencv老版的接口。

# 对于VPP硬件不支持的YUV格式转换，采取什么样的软件方式最快？

**答**：

建议采用内部增强版本的libyuv。

相比较原始版本，增加了许多NEON64优化过的格式转换API函数。其中包含许多JPEG YCbCr相关的函数。

位置：/opt/sophon/libsophon-current/lib/

# OpenCV中的BGR格式，在libyuv中对应的那个格式？OpenCV中的RGB格式呢？

**答**：

- OpenCV中的BGR格式，在libyuv中对应的格式为RGB24
- OpenCV中的RGB格式，在libyuv中对应的格式为RAW。

# 若是采用libyuv处理JPEG方面的输出或者输入，需要注意什么事项？

**答**：

若是处理jpeg方面的输出或者输入，需要使用J400，J420，J422，J444等字样的函数，不然输出结果会有色差。

原因是JPEG的格式转换矩阵跟视频的不一样。

# FFMPEG&OpenCV 支持 GB28181 协议

**UDP实时流地址**

```bash
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108
```

34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip：本地ip，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

**UDP回放流地址**

```bash
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713
```

34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype：录像存储累类型
localid：本地20位编码，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localip：本地ip，可选项
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。
begtime：录像起始时间
endtime：录像结束时间

**TCP实时流地址**

```bash
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201
```

34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip：本地ip，是可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置

**TCP回放流地址**

```bash
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713
```

34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype：录像存储累类型
localid：本地20位编码，可选项
localip：本地ip，可选项。不设置会获取 eth0 的ip，如果没有eth0需要手动设置
begtime：录像起始时间
endtime：录像结束时间

**注意事项**：

1. 流媒体传输默认是udp方式，如果使用tcp方式获取实时流或回放流，需要显示的指定。

   Ffmpeg指定tcp方式为接口调用 通过av_dict_set设置 gb28181_transport_rtp 为tcp。

   Opencv指定方式是设置环境变量

   ```bash
   export OPENCV_FFMPEG_CAPTURE_OPTIONS="gb28181_transport_rtp;tcp"
   ```

2. 如果使用udp方式外部无法访问到内部ip/port，localmediaport需要做端口映射，端口映射需要两个 rtp和rtcp。

3. 做端口映射时，使用的端口号尽量不要太大，推荐10000--20000的端口，socket端口号的最大值时65536，但是很情况下，端口号是受很多资源的限制。端口号使用过大可能会出现：[bind failed] 错误打印。

# 现在OpenCV中默认是使用ION内存作为MAT的data空间，如何指定Mat对象基于system memory内存去创建使用？

**答**：

```cpp
using namespace cv;
Mat m; m.allocator = m.getDefaultAllocator();     // get system allocator
```

然后就可以正常调用各种mat函数了，如m.create() m.copyto()，后面就会按照指定的allocator来分配内存了。

```cpp
m.allocator = hal::getDefaultAllocator();  // get ion allocator
```

就又可以恢复使用ION内存分配器来分配内存。

# FFMPEG JPEG 编码与转码应用示例

**调用JPEG编码的ffmpeg命令**

```bash
ffmpeg -c:v jpeg_bm -i src/5.jpg -c:v jpeg_bm -is_dma_buffer 1 -y 5nx.jpg
```

**调用动态JPEG转码的ffmpeg命令**

```bash
ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.avi -c:v jpeg_bm -is_dma_buffer 1 -y test_avi.mov
ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.mov -c:v jpeg_bm -is_dma_buffer 1 -y test_mov.mov
```

# 如何从FFMPEG的输入缓冲区中读取 bitstream?

**答**：

FFMPEG 源码应用示例
/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_reading.c (or http://www.ffmpeg.org/doxygen/trunk/doc_2examples_2avio_reading_8c-example.html)

在这一示例中，libavformat demuxer 通过 **custom AVIOContext read callback** 访问媒体信息，而不是通过在传入FFMPEG中的文件、rstp等协议访问媒体信息的。

以下是middleware-soc中的一个使用avio + jpeg_bm解码静态jpeg图片的例子。
(/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_decode_jpeg.c)

# 从内存读取图片初始化时间过长问题

**问题**：从内存读取图片，用AVIOContext *avio =avio_alloc_context()，以及avformat_open_input()来初始化，发现初始化时间有290ms；但是如果从本地读取图片，只有3ms。为啥初始化时间要这么长？怎样减少初始化时间？

**答**：

```cpp
ret = avformat_open_input(&fmt_ctx, NULL, NULL, NULL);
```

这里是最简单的调用。因此，avformat内部会会读取数据，并遍历所有的数据，来确认avio中的数据格式。

若是避免在这个函数中读取数据、避免做这种匹配工作。在已经知道需要使用的demuxer的前提下，譬如，已知jpeg的demuxer是mjpeg，可将代码改成下面的试试。

```c
AVInputFormat* input_format = av_find_input_format("mjpeg");
ret = avformat_open_input(&fmt_ctx, NULL, input_format, NULL);
```

## 如何查看FFMPEG中支持的分离器的名称?

答：

```
root@linaro-developer:~# ffmpeg -demuxers | grep jpeg
D jpeg_pipe piped jpeg sequence
D jpegls_pipe piped jpegls sequence
D mjpeg raw MJPEG video
D mjpeg_2000 raw MJPEG 2000 video
D mpjpeg MIME multipart JPEG
D smjpeg Loki SDL MJPEG
```

## 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm解码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -decoders | grep _bm
V..... avs_bm bm AVS decoder wrapper (codec avs)
V..... cavs_bm bm CAVS decoder wrapper (codec cavs)
V..... flv1_bm bm FLV1 decoder wrapper (codec flv1)
V..... h263_bm bm H.263 decoder wrapper (codec h263)
V..... h264_bm bm H.264 decoder wrapper (codec h264)
V..... hevc_bm bm HEVC decoder wrapper (codec hevc)
V..... jpeg_bm BM JPEG DECODER (codec mjpeg)
V..... mpeg1_bm bm MPEG1 decoder wrapper (codec mpeg1video)
V..... mpeg2_bm bm MPEG2 decoder wrapper (codec mpeg2video)
V..... mpeg4_bm bm MPEG4 decoder wrapper (codec mpeg4)
V..... mpeg4v3_bm bm MPEG4V3 decoder wrapper (codec msmpeg4v3)
V..... vc1_bm bm VC1 decoder wrapper (codec vc1)
V..... vp3_bm bm VP3 decoder wrapper (codec vp3)
V..... vp8_bm bm VP8 decoder wrapper (codec vp8)
V..... wmv1_bm bm WMV1 decoder wrapper (codec wmv1)
V..... wmv2_bm bm WMV2 decoder wrapper (codec wmv2)
V..... wmv3_bm bm WMV3 decoder wrapper (codec wmv3)
```

## 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h decoder=jpeg_bm
Decoder jpeg_bm [BM JPEG DECODER]:
General capabilities: avoidprobe
Threading capabilities: none
jpeg_bm_decoder AVOptions:
-bs_buffer_size <int> .D.V..... the bitstream buffer size (Kbytes) for bm jpeg decoder (from 0 to INT_MAX) (default 5120)
-chroma_interleave <flags> .D.V..... chroma interleave of output frame for bm jpeg decoder (default 0)
-num_extra_framebuffers <int> .D.V..... the number of extra frame buffer for jpeg decoder (0 for still jpeg, at least 2 for motion jpeg) (from 0 to INT_MAX) (default 0)
```

## 如何在FFMPEG中查看编码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h encoder=jpeg_bm
Encoder jpeg_bm [BM JPEG ENCODER]:
General capabilities: none
Threading capabilities: none
Supported pixel formats: yuvj420p yuvj422p yuvj444p
jpeg_bm_encoder AVOptions:
-is_dma_buffer <flags> E..V..... flag to indicate if the input frame buffer is DMA buffer (default 0)
```

## 调用API实现jpeg编码的应用示例

答：

```c
AVDictionary* dict = NULL;
av_dict_set_int(&dict, "is_dma_buffer", 1, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

## 调用FFMPEG的API实现静态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

```c
AVDictionary* dict = NULL;
/* bm_jpeg 解码器的输出是 chroma-interleaved模式,例如, NV12 */
av_dict_set_int(&dict, "chroma_interleave", 1, 0);
/* The bitstream buffer 为 3100KB(小于 1920x1080x3), 假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 0, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

## 调用FFMPEG的API实现动态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

```c
AVDictionary* dict = NULL;
/* bm_jpeg 解码器输出的是 chroma-separated 模式, 例如, YUVJ420 */
av_dict_set_int(&dict, "chroma_interleave", 0, 0);
/* The bitstream buffer 为 3100KB，假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 2, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

## BM168x解码性能对于H264/H265有差别吗？如果调整码率的话，最多可以解多少路呢？有没有对应的数据参考？

答：

264,265是解码路数相同的。

码率对解码帧率会有影响，这个变化就需要实测，例如我们说的BM1686解码能达到960fps是针对监控码流而言的，这类监控码流没有B帧，场景波动较小，码率基本在2~4Mbps。如果是电影或者其他码率很高的，比如10Mbps，20Mbps甚至更多，是会有明显影响的，具体多大这个需要实测。

分辨率对于解码帧率的影响，是可以按照比例来换算的。我们说的960fps是针对1920x1080 HD分辨率而言的。

## 是否可以通过抽帧来提高BM168x的解码路数

答：

我们opencv中提供的抽帧，是在解码出来的结果中做的，并不是只解I/P帧的抽帧概念。这里的抽帧解码主要是保证出来帧数的均匀，使得后续的分析处理是等间隔的进行，这是为后续模型分析比较复杂的时候，不能达到每帧都检测而设计的解决方案，但并不能达到增加解码路数的效果。

这里顺便解释下，为什么不提供只解I/P帧的抽帧功能。如果只解I、P帧的话，抽帧的间隔就完全取决于码流的编码结构，这样是比较难控制住性能，比如监控码流中的没有B帧，那其实就相当于没有抽帧了。如果客户可以控制编码端，那更切合实际的做法是直接降低编码端的编码帧率，比如降到15fps，那样解码路数就可以直接提升；反之，如果客户没有办法控制编码端，那么同样的，只解IP帧的抽帧方式就也无法达到增加解码路数的效果。

## 是否支持avi, f4v, mov, 3gp, mp4, ts, asf, flv, mkv封装格式的H264/H265视频解析？

答：我们使用ffmpeg对这些封装格式进行支持，ffmpeg支持的我们也支持。经查，这些封装格式ffmpeg都是支持的。但是封装格式对于H265/264的支持，取决于该封装格式的标准定义，比如flv标准中对h265就没有支持，目前国内的都是自己扩展的。

## 是否支持png, jpg, bmp, jpeg等图像格式

答：Jpg/jpeg格式除了有jpeg2000外，自身标准还有很多档次，我们采用软硬结合的方式对其进行支持。对jpeg baseline的除了极少部分外，都用硬件加速支持，其他的jpeg/jpg/bmp/png采用软件加速的方式进行支持。主要的接口有opencv/ffmpeg库。

## Valgrind内存检查为什么有那么多警告，影响到应用的调试了

答：

我们的版本发布每次都会用valgrind检查一遍内存泄漏问题，如果有内存泄露问题我们会检查修正的。之所以没有去掉有些警告，是因为这些警告大部分都是内存没有初始化，如果对这些内存每个都加上初始化，会明显导致速度性能下降，而且我们确认后续操作是在硬件对其赋值后再进行的，对于此类警告，我们就不会去消除。

为了避免警告过多对上层应用调试造成影响，建议使用valgrind的suppression功能，可以通过过滤配置文件，来避免我们模块产生的valgrind警告，从而方便上层应用调试自身的程序。

## 使用opencv的video write编码，提示物理内存(heap2)分配失败

答：

确认heap2 设置的大小，如果heap2 默认大小是几十MB，需要设置heap2 size为1G。目前出厂默认配置是1G。

```
Update_boot_info 可查询heap2 size
update_boot_info –heap2_size=0x40000000 –dev=0x0 设置heap2 size为1G。设置后重装驱动。
```

## Bm_opencv的imread jpeg解码结果和原生opencv的imread jpeg结果不同，有误差

答：是的。原生opencv使用libjpeg-turbo,而bm_opencv采用了bm168x芯片中的jpeg硬件加速单元进行解码。

误差主要来自解码输出YUV转换到BGR的过程中。1）YUV需要上采样到YUV444才能进行BGR转换。这个upsample的做法没有标准强制统一，jpeg-turbo提供了默认Fancy upsample，也提供了快速复制上采样的算法，原生opencv在cvtColor函数中采用了快速复制上采样算法，而在imread和imdecode中沿用了libjpeg-turbo默认的fancy upsample；而BM168x硬件加速单元采用快速复制的算法。2）YUV444到BGR的转换是浮点运算，浮点系数精度的不同会有+/-1的误差。其中1）是误差的主要来源。

这个误差并不是错误，而是双方采用了不同的upsample算法所导致的,即使libjpeg-turbo也同时提供了两种upsample算法。

如果用户非常关注这两者之间的差异，因为这两者之间的数值差异导致了AI模型精度的下降，我们建议有两种解决办法：

1）设置环境变量 export USE_SOFT_JPGDEC=1，可以指定仍然使用libjpeg-turbo进行解码。但是这样会导致cpu的loading上升，不推荐

2）可能过去模型太依赖开源opencv的解码结果了，可以用bm_opencv的解码结果重新训练模型，提高模型参数的适用范围。

可以使用libjpeg-turbo提供的djpeg工具对于测试工具集的数据进行重新处理，然后用处理后的数据对模型进行训练。djpeg的命令如下：

```
./djpeg -nosmooth -bmp -outfile xxxxx.bmp input.jpg
```

然后用重新生成bmp文件作为训练数据集，进行训练即可。

## 如何查看vpu/jpu的内存、使用率等状态

答：

在soc模式下，可以用下面的方法查看：

```
cat /proc/vpuinfo
cat /proc/jpuinfo
```

## 视频支持32路甚至更多的时候，报视频内存不够使用，如何优化内存使用空间

答：

在soc模式下，视频内存的默认配置是2G，正常使用在16路是绰绰有余的，但在32路视频需要在应用层面上仔细设计，不能有任何的浪费。

如果解码使用的是FFMPEG框架，首先保证视频输出格式使用压缩格式，即output_format 101。Opencv框架的话，内部已经默认使用压缩格式了；

其次如果应用在获取到解码输出avFrame后，并不是直接压入队列，而是转换到RGB或者非压缩数据后再缓存的话，可以用av_dict_set extra_frame_buffer_num为1（默认为2）。Opencv内部在最新版本中会默认优化。

最后，如果以上优化过后，仍然不够的话，在soc模式下可以考虑更改dtb设置，给视频挪用分配更多的内存，当然相应的，其他模块就要相应的减少内存。这个要从系统角度去调配。

## Opencv中mat是如何分配设备内存和系统内存的？

答：

因为受设计影响，这个问题细节比较多，主要从三方面能解释。

1. 在soc模式下，设备内存和系统内存是同一份物理内存，通过操作系统的ION内存进行管理，系统内存是ION内存的mmap获得。

2. 在sophon opencv中默认会同时开辟设备内存和系统内存，其中系统内存放在mat.u->data或mat.data中，设备内存放在mat.u->addr中。只有以下几种情况会不开辟设备内存，而仅提供系统内存：

   + 当data由外部开辟并提供给mat的时候。即用以下方式声明的时候：
     ```c
     Mat mat(h, w, type, data); 或 mat.create(h, w, type, data)；
     ```

   + 在soc模式下，当type不属于（CV_8UC3, CV_32FC1, CV_32FC3）其中之一的时候。这里特别注意CV_8UC1是不开辟的，这是为了保证我们的opencv能够通过开源opencv的opencv_test_core的一致性验证检查。

   + 当宽或者高小于16的时候。因为这类宽高，硬件不支持

3. 在BM1686的SOC模式下，mat分配的CV_8UC3类型的设备内存会自动做64对齐，即分配的内存大小一定是64对齐的（注意：仅对soc模式的CV_8UC3而言，且仅对BM1686芯片）。

# ffmpeg中做图像格式/大小变换导致视频播放时回退或者顺序不对的情况处理办法

答：ffmpeg在编码的时候底层维护了一个avframe的队列作为编码器的输入源，编码期间应保证队列中数据有效，如果在解码后需要缩放或者像素格式转换时候需要注意送进编码器的avframe的数据有效和释放问题。

在例子ff_bmcv_transcode中从解码输出src-avframe转换成src-bm_image然后做像素格式转换或者缩放为dst-bm_image最后转回dst-avframe去编码的过程中src-avframe、src-bm_image的设备内存是同一块，dst-avframe、dst-bm_image的设备内存是同一块。在得到dst-bm_image后即可释放src_avframe和src-bm_image的内存（二者释放其中一个即可释放设备内存），作为编码器的输入dts-bm_image在转换成dst-avframe之后其设备内存依然不能被释放（常见的异常情况是函数结束dts-bm_image的引用计数为0导致其被释放），如果dst-bm_image被释放了此时用dst-avframe去编码结果肯定会有问题。

解决方法是dst-bm_image的指针是malloc一块内存，然后将其传给av_buffer_create，这样就保证在函数结束的时候dst-bm_image引用计数不会减1，释放的方法是将malloc的dst-bm_image指针通过av_buffer_create传给释放的回调函数，当dst-avframe引用计数为0的时候会调用回调函数将malloc的指针和dst-bm_image的设备内存一起释放。详见例子ff_bmcv_transcode/ff_avframe_convert.cpp。

# 启动设备首次执行某个函数慢，重启进程再次运行正常

现象：设备上电后第一次执行程序，函数处理时间长，再次执行程序，运行正常。

解决：先做个验证，如果不重启可复现，就说明是文件cache导致的变慢。

1. 上电后第一次执行慢，第二次执行正常，之后进入root用户
2. 清除cache echo 3 > /proc/sys/vm/drop_caches
3. 再次执行程序，运行慢，即可确定是cache导致的。

# Opencv mat创建失败，提示"terminate called after throwing an instance of 'cv::Exception' what(): OpenCV(4.1.0) …… matrix.cpp:452: error: (-215:Assertion failed) u != 0 in function 'creat'"

答：这种错误主要是设备内存分配失败。失败的原因有两种：

1. 句柄数超过系统限制，原因有可能是因为句柄泄漏，或者系统句柄数设置过小，可以用如下方法确认：

   查看系统定义的最大句柄数：

   ```
   ulimit -n
   ```

   查看当前进程所使用的句柄数：

   ```
   lsof -n|awk '{print $2}'|sort|uniq -c|sort -nr|more
   ```

2. 设备内存不够用。可以用如下方法确认：

   - SOC模式下

     ```
     cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary
     ```

   - PCIE模式下，bm-smi工具可以查看设备内存空间

解决方案：在排除代码本身的内存泄漏或者句柄泄漏问题后，可以通过加大系统最大句柄数来解决句柄的限制问题：ulimit -HSn 65536

设备内存不够就需要通过优化程序来减少对设备内存的占用，或者通过修改dts文件中的内存布局来增加对应的设备内存。详细可以参考SM5用户手册中的说明。

# opencv转bm_image的时候，报错"Memory allocated by user, no device memory assigned. Not support BMCV!"

答：这种错误通常发生在soc模式下，所转换的Mat只分配了系统内存，没有分配设备内存，而bm_image要求必须有设备内存，因此转换失败。

而在pcie模式下，接口内部会自动分配设备内存，因此不会报这个错误。

会产生这类问题的Mat通常是由外部分配的data内存attach过去的，即调用Mat(h, w, data) 或者Mat.create(h,w, data)来创建的，而data!=NULL,由外部分配。

对于这种情况，因为bm_image必须要求设备内存，因此解决方案有

1. 新生成个Mat，默认创建设备内存，然后用copyTo()拷贝一次，把数据移到设备内存上，再重新用这个Mat来转成bm_image
2. 直接创建bm_image，然后用bm_image_copy_host_to_device,将Mat.data中的数据拷贝到bm_image的设备内存中。

# Opencv用已有Mat的内存data，宽高去创建新的Mat后，新Mat保存的图像数据错行，显示不正常

答：保存的图像错行，通常是由于Mat中step信息丢失所造成。

一般用已有Mat去生成一个新Mat，并且要求内存复用时，可以直接赋值给新的Mat来简单实现，如 Mat1 = Mat2.

但在某些情况下，比如有些客户受限于架构，函数参数只能用C风格的指针传递，就只能用Mat中的data指针，rows，cols成员来重新恢复这个Mat。
这时候就需要注意step变量的设置，在默认情况下是AUTO_STEP配置，即每行数据没有填充数据。但是在很多种情况下，经过opencv处理后，会导致每行出现填充数据。如，

1. soc模式下，我们的Mat考虑执行效率，在创建Mat内存时每行数据会做64字节对齐，以适配硬件加速的需求（仅在soc模式下）
2. opencv的固有操作，如这个Mat是另一个Mat的子矩阵（即rect的选定区域），或者其他可能导致填充的操作。

因此，按照opencv定义，通用处理方式就是在生成新的Mat的时候必须指定step，如下所示:

```
cv::Mat image_mat = cv::imread(filename,IMREAD_COLOR,0);
cv::Mat image_mat_temp(image_mat.rows,image_mat.cols,CV_8UC3,image_mat.data,image_mat.step[0]);
cv::imwrite("sophgo1.jpg",image_mat_temp);
```

# 在soc模式下客户用ffmpeg解码时拿到AVframe将data[0-3] copy到系统内存发现copy时间是在20ms左右而相同数据量在系统内存两块地址copy只需要1-3ms

答：上述问题的原因是系统在ffmpeg中默认是禁止cache的，因此用cpu copy性能很低，使能cache就能达到系统内存互相copy同样的速度。可以用以下接口使能cache.

```
av_dict_set_int(&opts, "enable_cache", 1, 0);
```

但是这样直接copy数据保存是非常占用内存、带宽和cpu算力的，我们推荐采用零拷贝的方式来实现原始解码数据的保存：

1. 推荐使用 extra_frame_buffer_num 参数指定增大硬件帧缓存数量，可以根据自己的需要选择缓存帧的数量。
   这个方式的弊端，一个是占用解码器内存，可能减少视频解码的路数；另一个是当不及时释放，当缓存帧全部用完时，会造成视频硬件解码堵塞。

   ```
   av_dict_set_int(&opts, "extra_frame_buffer_num", extra_frame_buffer_num, 0);
   ```

2. 推荐使用 output_format参数设置解码器输出压缩格式数据，然后使用vpp处理输出非压缩yuv数据（当需要缩放，crop时，可以同步完成），
   然后直接零拷贝引用非压缩yuv数据。这种方式不会影响到硬件解码性能，并且可以缓存的数据空间也大很多。

   ```
   av_dict_set_int(&opts, "output_format", 101, 0);
   ```

# 在opencv VideoCapture 解码视频时提示: maybe grab ends normally, retry count = 513

上述问题是因为在VideoCapture存在超时检测，如果在一定时间未收到有效的packet则会输出以上log，此时如果视频源是网络码流可以用vlc拉流验证码流是否正常，如果是文件一般是文件播放到末尾需调用VidoeCapture.release后重新VideoCapture.open

# [问题分析]客户反馈碰到如下错误提示信息"VPU_DecRegisterFrameBuffer failed Error code is 0x3", 然后提示Allocate Frame Buffer内存失败。

这个提示信息表示：分配的解码器缓存帧个数，超过了最大允许的解码帧。导致这个问题的原因有可能是：

1. 不支持的视频编码格式，比如场格式，此时可以用FAQ14的方法，把码流数据录下来，提交给我们分析。
2. 设置了过大的extra_frame_buffer_num。理论上，extra_frame_buffer_num不能超过15，超过了以后就有可能不能满足标准所需的最大缓存帧数。因为大部分编码码流并没有用到最大值，所以extra_frame_buffer_num大于15的时候，对大部分码流仍然是可以工作的。

目前发现可能导致这个问题的原因有上述两种，后续有新的案例继续增补

# SOC模式下，opencv在使用8UC1 Mat的时候报错，而当Mat格式为8UC3的时候，同样的程序完全工作正常。

这个问题碰到的客户比较多，这次专门设立一个FAQ以便搜索。其核心内容在FAQ46 "Opencv中mat是如何分配设备内存和系统内存的"有过介绍，可以继续参考FAQ46

在soc模式下，默认创建的8UC1 Mat是不分配设备内存的。因此当需要用到硬件加速的时候，比如推理，bmcv操作等，就会导致各种内存异常错误。

解决方案可以参看FAQ26 "如何指定Mat对象基于system memory内存去创建使用", 指定8UC1 Mat在创建的时候，内部使用ion分配器去分配内存。如下所示。

```
cv::Mat gray_mat;
gray_mat.allocator = hal::getAllocator();
gray_mat.create(h, w, CV_8UC1);
```

# 调用 bmcv_image_vpp_convert_padding 接口时，报缩放比例超过32倍的错："vpp not support: scaling ratio greater than 32"。

bm1686的vpp中硬件限制图片的缩放不能超过32倍（bm1686的vpp中硬件限制图片的缩放不能超过128倍）。即应满足 dst_crop_w <= src_crop_w * 32， src_crop_w <= dst_crop_w * 32， dst_crop_h <= src_crop_h * 32 , src_crop_h <= dst_crop_h * 32。

此问题原因可能是：

1. 输入 crop_rect 中的crop_w, crop_h 与 输出 padding_attr 中的dst_crop_w ，dst_crop_h 缩放比例超过了32倍。
2. crop_rect，padding_attr 值的数量应与 output_num的数量一致。

# [问题分析]程序提示"VPU_DecGetOutputInfo decode fail framdIdx xxx error(0x00000000) reason(0x00400000), reasonExt(0x00000000)"是可能什么问题，这里reason的具体数值可能不同

这个提示通常是由码流错误造成的，提示的含义是第xxx帧解码错误，错误原因为....。这里具体原因对于上层应用来说，不用关心，只需知道这是由码流错误导致的即可。

进一步分析，导致码流错误的原因通常可以分为两类，我们要有针对的进行处理。因为一旦频繁出现这种提示，说明解码出来的数据是不正确的，这时候有可能是各种马赛克或者图像花，对于后续的处理会造成各种异常情况，所以我们必须尽量减少这种情况的发生。

1. 网络情况导致的丢包。这时候可以用我们的测试程序vidmulti验证下，如果vidmulti没有解码错误，那么可以排除这种情况。如果确认网络丢包的话，要分辨下是否网络带宽本身就不够，如果本身带宽不够，那没有办法，只能降低视频码流的码率。如果带宽是够的，要检查下网线。当码流连接数超过20多路的时候，这时候有可能已经超出百兆了，这时网线也必须换到CAT6，与千兆网相匹配
2. 解码性能达到上限造成丢包。这种情况发生在流媒体环境中，对于文件播放是不会发生的。这时也可以用我们的vidmulti跑一下，作为比较。如果vidmulti也发生错误，说明性能确实到了上限了，否则说明应用本身还有优化的空间。

# [问题分析]程序提示"coreIdx 0 InstIdx 0: VPU interrupt wait timeout"，这是怎么回事?

这个提示表示视频解码或者编码中断超时。这个提示只是警告，会再次尝试，因此只要没有连续出现就可以忽略。这种情况一般是由解码数据错误导致或者负荷过重产生的。例如在板卡情况下，由于板卡数据交换过于频繁，造成解码或者编码数据传输堵塞，使得中断超时。

# 采用TCP传输码流的时候如果码流服务器停止推流，ffmpeg阻塞在av_read_frame

这是因为超时时间过长导致的，可以用一下参数设置超时时间减短。

```
av_dict_set(&options, "stimeout", "1000000", 0);
```

# [问题分析]当用ffmpeg jpeg_bm解码超大JPEG图片的时候，有时候会报"ERROR:DMA buffer size(5242880) is less than input data size(xxxxxxx)"，如何解决？

在用FFMPEG的jpeg_bm硬件解码器解码JPEG图片的时候，默认的输入buffer是5120K。在拿到JPEG文件前提前分配好输入缓存，在MJPG文件解码时可以避免频繁地创建和销毁内存。当出现默认输入buffer大小比输入jpeg文件小的时候，可以通过下面的命令来调大输入缓存。

```
av_dict_set_int(&opts, "bs_buffer_size", 8192, 0);   //注意：bs_buffer_size是以Kbyte为单位的
```

# 调用 bmcv_image_vpp_basic 接口时，csc_type_t, csc_type 和 csc_matrix_t* matrix该如何填？

bmcv中vpp在做csc 色彩转换时，默认提供了4组601系数和4组709系数，如csc_type_t所示。

1. csc_type可以填为CSC_MAX_ENUM，matrix填NULL，会默认配置 601 YCbCr与RGB互转系数。
2. csc_type可以填csc_type_t中参数，如YCbCr2RGB_BT709，matrix填NULL，会按照所选类型配置对应系数。
3. csc_type可以填CSC_USER_DEFINED_MATRIX，matrix填自定义系数。会按照自定义系数配置。

csc_matrix_t 中系数参考如下公式：

Y = csc_coe00 * R + csc_coe01 * G + csc_coe02 * B + csc_add0;
U = csc_coe10 * R + csc_coe11 * G + csc_coe12 * B + csc_add1;
V = csc_coe20 * R + csc_coe21 * G + csc_coe22 * B + csc_add2;

由于bm1686 vpp精度为FP32，整数处理。

csc_coe 与 csc_add的计算方法为: csc_coe = round（浮点数 * 1024）后按整数取补码。

csc_coe取低13bit，即 csc_coe = csc_coe & 0x1fff，csc_add取低21bit，即 csc_add = csc_add & 0x1fffff。

举例如下：

floating-point coe matrix => fixed-point coe matrix

0.1826	0.6142	0.0620	16.0000         =>          0x00bb    0x0275   0x003f   0x004000

## [问题分析]不同线程对同一个bm_imag调用 bm_image_destroy 时，程序崩溃

bm_image_destroy(bm_image image) 接口设计时，采用了结构体做形参，内部释放了image.image_private指向的内存，但是对指针image.image_private的修改无法传到函数外，导致第二次调用时出现了野指针问题。

为了使客户代码对于sdk的兼容性达到最好，目前不对接口做修改。
建议使用bm_image_destroy（image）后将 image.image_private = NULL，避免多线程时引发野指针问题。

## 如何跨进程传递Mat信息，使不同进程间零拷贝地共享Mat中的设备内存数据？

跨进程共享Mat的障碍在于虚拟内存和句柄在进程间共享非常困难，因此解决这个问题的本质是：如何由一块设备内存，零拷贝地重构出相同的Mat数据结构。

解决这个问题会用到下面三个接口，其中前两个接口用于重构yuvMat的数据，后一个接口用于重构opencv 标准Mat的数据。

```cpp
cv::av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MMPEG, int id = 0)
cv::Mat(AVFrame *frame, int id)
Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data,unsigned long addr, int fd, int id = 0)
```

```cpp
/* 完整的跨进程共享Mat的代码如下所示。跨进程共享的方法很多，下面的例子目的在于展示如何
   使用上面的函数重构Mat数据，其他的代码仅供参考。其中image为需要被共享的Mat */
    union ipc_mat{
      struct{
          unsigned long long addr;
          int total;
          int type;
          size_t step[2];
          int plane_size[4];
          int plane_step[4];
          int pix_fmt;
          int height;
          int width;
          int color_space;
          int color_range;
          int dev_id;
          int isYuvMat;
      }message;
      unsigned char data[128];
  }signal;
  memset(signal.data, 0, sizeof(signal));

  if (isSender){  // 后面是send的代码
      int fd = open("./ipc_sample", O_WRONLY);
      signal.message.addr = image.u->addr;
      signal.message.height = image.rows;
      signal.message.width = image.cols;
      signal.message.isYuvMat = image.avOK() ? 1 : 0;
      if (signal.message.isYuvMat){  // 处理yuvMat
                              //avAddr(4~6)对应设备内存
          signal.message.plane_size[0] = image.avAddr(5) - image.avAddr(4);
          signal.message.plane_step[0] = image.avStep(4);

          signal.message.pix_fmt = image.avFormat();
          if (signal.message.pix_fmt == AV_PIX_FMT_YUV420P){
              signal.message.plane_size[2] =
              signal.message.plane_size[1] = image.avAddr(6) - image.avAddr(5);
              signal.message.plane_step[1] = image.avStep(5);
              signal.message.plane_step[2] = image.avStep(6);
          } else if (signal.message.pix_fmt == AV_PIX_FMT_NV12){
              signal.message.plane_size[1] = signal.message.plane_size[0] / 2;
              signal.message.plane_step[1] = image.avStep(5);
          }   // 此处仅供展示，更多的色彩格式可以继续扩展

          signal.message.color_space = image.u->frame->colorspace;
          signal.message.color_range = image.u->frame->color_range;

          signal.message.dev_id = image.card;
      } else { // 处理bgrMat
          signal.message.total = image.total();
          signal.message.type = image.type();
          signal.message.step[0] = image.step[0];
          signal.message.step[1] = image.step[1];
      }

      write(fd, signal.data, 128);

      while(1) sleep(1); //此处while(1)仅供举例，要注意实际应用中后面还需要close(fd)
  } else if (!isSender){
      if ((mkfifo("./ipc_example", 0600) == -1) && errno != EEXIST){  // ipc共享仅供举例
          printf("mkfifo failed\n");
          perror("reason");
      }

      int fd = open("./ipc", O_RDONLY);
      Mat f_mat;  // 要重构的共享Mat
      int cnt = 0;

      while (cnt < 128){
          cnt += read(fd, signal.data+cnt, 128-cnt);
      }

      if(signal.message.isYuvMat) { // yuvMat
          AVFrame *f = cv::av::create(signal.message.height,
                                      signal.message.width,
                                      signal.message.pix_fmt,
                                      NULL,
                                      signal.message.addr,
                       /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                                      0,
                                      signal.message.plane_step,
                                      signal.message.plane_size,
                                      signal.message.color_space,
                                      signal.message.color_range,
                                      signal.message.dev_id);
          f_mat.create(f, signal.message.dev_id);
      } else {
          f_mat.create(signal.message.height,
                       signal.message.width,
                       signal.message.total,
                       signal.message.type,
                       signal.message.step,
                       NULL,
                       signal.message.addr,
                      /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                       0,
                       signal.message.dev_id);
          bmcv::downloadMat(f_mat);
                      /* 注意这里需要将设备内存的数据及时同步到系统内存中。因为yuvMat使
                        用中约定设备内存数据永远是最新的，bgrMat使用中约定系统内存数据永远
                        是最新的，这是我们opencv中遵循的设计原则 */
      }
      close(fd);
  }

 /* 以上代码仅供参考，请使用者根据自己实际需要修改定制 */
```

## 申请设备内存失败， 错误返回-24

设备内存每一次申请都会有一个fd，ubuntu上最大1024。如果持续申请且不释放，fd数量超过1024，就会导致申请设备内存失败，错误返回-24。
如果想扩大ubuntu的fd数量，可通过ulimit命令修改限制。如 ulimit -n 10000 可将ubuntu的fd数量扩大至10000。

## bm_image_create、bm_image_alloc_dev_mem、bm_image_attach相关疑问

1. bm_image_create：用于创建bm_image结构体。

2. bm_image_alloc_dev_mem：申请设备内存，且内部会attach上bm_image。

3. bm_image_attach：用于将从opencv等处获取到的设备内存与bm_image_create申请到的bm_image进行绑定。

## bm_image_destroy、bm_image_detach相关疑问

1. bm_image_detach：用于将bm_image关联的设备内存进行解绑， 如果设备内存是内部自动申请的，才会释放这块设备内存；如果bm_image未绑定设备内存，则直接返回。

2. bm_image_destroy：该函数内部嵌套调用bm_image_detach。也就是说，调用该函数，如果bm_image绑定的设备内存是通过bm_image_alloc_dev_mem申请，就会释放；
   如果是通过bm_image_attach绑定的设备内存则不会被释放，此时需要注意该设备内存是否存在内存泄露，如果存在其他模块继续使用，则由相应模块进行释放。

3. 总的来说，设备内存由谁申请则由谁释放，如果是通过attach绑定的设备内存，则不能调用 bm_image_destroy 进行释放，如果确定attach绑定的设备内存不再使用，可通过bm_free_device等接口进行释放。

## 在bmcv::toBMI之前是否需要调用bm_create_image，如果调用，在最后使用bm_image_destroy会不会引起内存泄露？

1. bmcv::toBMI内部嵌套调用bm_image_create， 无需再次调用bm_create_image。

2. 如果在bmcv::toBMI前调用了bm_create_image，会导致内存泄露。

3. 调用bmcv::toBMI后，除了需要调用bm_image_destroy,还需要image.image_private = NULL。

---

文件: /home/zzt/workspace/sex_support_web/docs/get_docs/se9/a2_ws/sophgo-develop-docs/multimedia/source_zh/guide/Multimedia_Guide_zh.rst

# SOPHGO多媒体框架介绍

## 简介

本文档所述多媒体框架的描述对象为算能的算丰BM168x产品系列，目前该产品系列包括BM1682和BM1684两款。其中1）BM1682没有视频编码硬件单元，因此本文中所有关于视频硬件编码的内容均只针对BM1684产品而言；2）本文中提到的PCIE模式，仅针对BM1684产品而言，在BM1682下仅支持soc模式；3）本文中提到的Opencv中的bmcv名字空间下的函数，仅针对BM1684产品而言。

本文档所述多媒体框架的覆盖范围包括BM168x产品系列中的视频解码VPU模块、视频编码VPU模块、图像编码JPU模块、图像解码JPU模块、图像处理模块VPP。这些模块的功能封装到FFMPEG和OPENCV开源框架中，客户可以根据自己的开发习惯，选择FFMPEG API或者OPENCV API。其中图像处理模块，我们还单独提供了算能自有的BMCV API底层接口，这部分接口有专门的文档介绍，可以参考《BMCV User Guide》，本文档不再详细介绍，仅介绍这三套API之间的层级关系及如何互相转换。

OPENCV，FFMPEG和BMCV这三套API在功能上是子集的关系，但有少部分不能全部包含，下面的括号中进行了特别标注。

1）BMCV API包含了所有能用硬件加速的图像处理加速接口（这里图像处理硬件加速，包括硬件图像处理VPP模块加速，以及借用其他硬件模块实现的图像处理功能）

2）FFMPEG API包含了所有硬件加速的视频/图像编解码接口，所有软件支持的视频/图像编解码接口（即所有FFMPEG开源支持的格式），通过bm_scale filter支持的部分硬件加速的图像处理接口（这部分图像处理接口，仅包括用硬件图像处理VPP模块加速的缩放、crop、padding、色彩转换功能）

3）OPENCV API包含了所有FFMPEG支持的硬件及软件视频编解码接口（视频底层通过FFMPEG支持，这部分功能完全覆盖），硬件加速的JPEG编解码接口，软件支持的其他所有图像编解码接口（即所有OPENCV开源支持的图像格式），部分硬件加速的图像处理接口（指用图像处理VPP模块加速的缩放、crop、padding、色彩转换功能），所有软件支持的OPENCV图像处理功能。

这三个框架中，BMCV 专注于图像处理功能，且能用BM168x硬件加速的部分；FFMPEG框架强于图像和视频的编解码，几乎所有格式都可以支持，只是是否能用硬件加速的区别；OPENCV框架强于图像处理，各种图像处理算法最初都先集成到OPENCV框架中，而视频编解码通过底层调用FFMPEG来实现。

因为BMCV仅提供了图像处理接口，因此FFMPEG或者OPENCV框架中，客户一般会选择其中一个作为主框架进行开发。这两个框架，从功能抽象上来说，OPENCV的接口要更加简洁，一个接口就可以实现一次视频编解码操作；从性能上说，这两个的性能是完全一致的，几乎没有差别，在视频编解码上，OPENCV只是对 FFMPEG接口的一层封装；从灵活性上说，FFMPEG的接口更加分离，可插入的操作粒度更细。最重要的，客户还是要根据自己对于某个框架的熟悉程度来做选择，只有深入了解，才能把框架用好。

这三个框架层级关系如图所示

图 1 OPENCV/FFMPEG/BMCV与BMSDK之间的层级调用关系

在很多应用场景下，需要用到某个框架下的特殊功能，因此在第4节中给出了三个框架之间灵活转换的方案。这种转换是不需要发生大量数据拷贝的，对性能几乎没有损失。

## BM1684硬件加速功能

本节给出了多媒体框架中硬件加速模块能支持的功能。其中硬件加速模块包括视频解码VPU模块，视频编码VPU模块，图像编解码JPU模块，图像处理VPP模块。

需要特别注意，这里只列出能够用硬件加速的能力，以及典型场景下的性能估计值。更详细的性能指标参考BM168x产品规格书。

### 视频编解码

BM1684产品支持H264（AVC），HEVC视频格式的硬件解码加速，最高支持到4K视频的实时解码。支持H264(AVC), HEVC视频格式的硬件编码，最高支持到HD(1080p)视频的实时编码。

视频解码的速度与输入视频码流的格式有很大关系，不同复杂度的码流的解码速度有比较大的波动，比如码率、GOP结构，分辨率等，都会影响到具体的测试结果。一般来说，针对视频监控应用场景，BM1684产品单芯片可以支持到32路HD高清实时解码。

视频编码的速度与编码的配置参数有很大关系，不同的编码配置下，即使相同的视频内容，编码速度也不是完全相同的。一般来说，BM1684产品单芯片最高可以支持到2路HD高清实时编码。

### 图像编解码

BM1684产品支持JPEG baseline格式的硬件编/解码加速。注意，仅支持JPEG baseline档次的硬件编解码加速，对于其他图片格式，包括JPEG2000, BMP, PNG以及JPEG标准的progressive, lossless等档次均自动采用软解支持。在opencv框架中，这种兼容支持对于客户是透明的，客户应用开发时无需特别处理。

图像硬件编解码的处理速度和图像的分辨率、图像色彩空间（YUV420/422/444）有比较大的关系，一般而言，对于1920x1080分辨率的图片，色彩空间为YUV420的，单芯片图像硬件编解码可以达到600fps左右。

### 图像处理

BM1684产品有专门的视频处理VPP单元对图像进行硬件加速处理。支持的图像操作有色彩转换、图像缩放、图像切割crop、图像拼接stitch功能。最大支持到4k图像输入。对于VPP不支持的一些常用复杂图像处理功能，如线性变换ax+b，直方图等, 我们在BMCV API接口中，利用其他硬件单元做了特殊的加速处理。

## 硬件内存分类

在后续的讨论中，内存同步问题是应用调试中经常会遇到的，比较隐蔽的问题。我们通常统一用设备内存和系统内存来称呼这两类内存间的同步。根据BM168x产品类型的不同，这两个内存在SOC模式和PCIE模式下分别具有不同的含义。

SOC模式，是指用BM168x芯片中的处理器作为主控CPU，BM168x产品独立运行应用程序。典型的产品有SE5、SM5-soc模组。在这类模式下，采用Linux系统下的ION内存对设备内存进行管理。在SOC模式下，设备内存指ION分配的物理内存，系统内存其实是cache，这里的命名只是为了和PCIE模式保持一致。从系统内存（cache）到设备内存，称为Upload上传（实质是cache flush）；从设备内存到系统内存（cache），称为Download下载（实质是cache invalidation）。在SOC模式下，设备内存和系统内存最终操作的其实是同一块物理内存，大部分时间，操作系统会自动对其进行同步，这也导致内存没有及时同步时的现象更加隐蔽和难以复现。

# PCIE模式

PCIE模式，是指BM168x产品作为PCIE板卡形态插到服务器主机上进行工作，应用程序运行在服务器主机的CPU上。在PCIE模式下，设备内存指PCIE板卡上的物理内存，并不包含在服务器主机内存中；系统内存指服务器主机中的内存。从系统内存到设备内存，称为Upload上传（实质是pcie写数据）；从设备内存到系统内存，称为Download下载（实质是pcie读数据）。在PCIE模式下，设备内存和系统内存是物理上完全独立的两块物理内存，必须通过Download/Upload操作才能保证这两块内存保持同步。

图 2 内存同步模型

FFMPEG和OPENCV两个框架都提供了内存同步操作的函数。而BMCV API只面向设备内存操作，因此不存在内存同步的问题，在调用BMCV API的时候，需要将数据在设备内存准备好。

在OPENCV框架中，部分函数的形参中就提供了update的标志位，当标志位设置true的时候，函数内部会自动进行内存同步操作。这部分可以参考后续的第二章第3节的API介绍。用户也可以通过bmcv::downloadMat() 和 bmcv::uploadMat()两个函数，主动控制内存同步。同步的基本原则是：

a) opencv原生函数中，yuv Mat格式下设备内存中的数据永远是最新的，RGB Mat格式下系统内存中的数据永远是最新的  
b) 当opencv函数向BMCV API切换的时候，根据上一个原则，将最新数据同步到设备内存中；反之，从BMCV API向opencv函数切换的时候，在RGB Mat下将最新数据同步到系统内存中。  
c) 在不发生框架切换的时候，要尽量减少内存同步的操作。频繁的内存同步操作会明显降低性能。

在常规FFMPEG框架中，有两类称之为软（常规）和硬（hwaccel）的codec API和filter API。这两套API的框架都可以支持BM168x的硬件视频编解码和硬件图像filter，从这个角度上说，所谓的软解码和硬解码在底层性能上是完全一样的，只是在使用习惯上的区别。软codec/filter API的使用方式和通常ffmpeg 内置codec完全一致，硬codec/filter API要用-hwaccel来指定使能bmcodec专用硬件设备。

在软codec API和filter API中，通过av_dict_set传入标志参数"is_dma_buffer"或者"zero_copy"，来控制内部codec或filter是否将设备内存数据同步到系统内存中，具体参数使用可以用ffmpeg -h来查看。当后续直接衔接硬件处理的时候，通常不需要将设备内存数据同步到系统内存中。

在hwaccel codec API和filter API中，内存默认只有设备内存，没有分配系统内存。如果需要内存同步，则要通过hwupload和hwdownload filter来完成。

综上所述，OPENCV和FFMPEG框架都对内存同步提供了支持，应用可以根据自己的使用习惯选择相应的框架，对数据同步进行精准控制。BMCV API则始终工作在设备内存上。

## 框架之间转换

在应用开发中，总会碰到一些情况下，某个框架无法完全满足设计需求。这时就需要在各种框架之间快速切换。BM168x多媒体框架对其提供了支持，可以满足这种需求，并且这种切换是不发生数据拷贝的，对于性能几乎没有影响。

### FFMPEG和OPENCV转换

FFMPEG和OPENCV之间的转换，主要是数据格式AVFrame和cv::Mat之间的格式转换。

当需要FFMPEG和OPENCV配合解决的时候，推荐使用常规非HWAccel API的通路，目前OPENCV内部采用是这种方式，验证比较完备。

FFMPEG AVFrame转到OPENCV Mat格式如下：

1. AVFrame * picture；
2. 中间经过ffmpeg API的一系列处理，比如avcodec_decode_video2 或者 avcodec_receive_frame，然后将得到的结果转成Mat
3. card_id 为进行ffmpeg硬件加速解码的设备序号， 在常规codec API中，通过av_dict_set的sophon_idx指定，或者hwaccel API中，在hwaccel设备初始化的时候指定， soc模式下默认为0
4. cv::Mat ocv_frame(picture, card_id)；
5. 或可以通过分步方式进行格式转换
6. cv::Mat ocv_frame;
7. ocv_frame.create(picture, card_id);
8. 然后可以用ocv_frame进行opencv的操作，此时ocv_frame格式为BM168x扩展的yuv mat类型，如果后续想转成opencv标准的bgr mat格式，可以按下列操作。
9. 注意：这里就有内存同步的操作， 如果没有设置，ffmpeg默认是在设备内存中的，如果update=false, 那么转成bgr的数据也一直在设备内存中，系统内存中为无效数据，如果update=true，则设备内存同步到系统内存中。如果后续还是硬件加速处理的话，可以update=false, 这样可以提高效率，当需要用到系统内存数据的时候，显式调用bmcv::downloadMat()来同步即可。
10. cv::Mat bgr_mat;
11. cv::bmcv::toMAT(ocv_frame, bgr_mat, update);
12. 最后AVFrame *picture会被Mat ocv_frame释放，因此不需要对picture进行av_frame_free()操作。如果希望外部调用av_frame_free来释放picture， 则可以加上card_id = card_id | UMatData::AVFRAME_ATTACHED, 该标准表明AVFrame的创建和释放由外部管理
13. ocv_frame.release();
14. picture = nullptr;

OPENCV Mat转成FFMPEG AVFrame的情况比较少见，因为几乎所有需要的FFMPEG操作都在opencv中有对应的封装接口。比如：ffmpeg解码在opencv有videoCapture类，ffmpeg编码在opencv中有videoWriter类，ffmpeg的filter操作对应的图像处理在opencv中有bmcv名字空间下的接口以及丰富的原生图像处理函数。

一般来说，opencv Mat转成FFMPEG AVFrame，指的是yuv Mat。在这种情况下，可以按下进行转换：

1. 创建yuv Mat，如果yuv Mat已经存在，可以忽略此步.card_id为BM168x设备序号，soc模式下默认为0
2. AVFrame * f = cv::av::create(height, width, AV_PIX_FMT_YUV420P,  NULL, 0, -1, NULL, NULL, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, card_id);
3. cv::Mat image(f, card_id);
4. do something in opencv
5. AVFrame * frame = image.u->frame;
6. call FFMPEG API
7. 注意：在ffmpeg调用完成前，必须保证Mat image没有被释放，否则AVFrame会和Mat image一起释放。如果需要将两个的声明周期分离开来，则上面的image声明要改成如下格式。
8. cv::Mat image(f, card_id | UMatData::AVFRAME_ATTACHED);
9. 这样Mat就不会接管AVFrame的内存释放工作

### FFMPEG和BMCV API转换

FFMPEG经常需要和BMCV API搭配使用，因此FFMPEG和BMCV之间的转换是比较频繁的。为此我们专门给了一个例子ff_bmcv_transcode，该例子可以在examples里找到。

ff_bmcv_transcode例子演示了用ffmpeg解码，将解码结果转换到BMCV下进行处理，然后再转换回到ffmpeg进行编码的过程。FFMPEG和BMCV之间的互相转换可以参考ff_avframe_convert.cpp文件中的avframe_to_bm_image()和bm_image_to_avframe()函数。

### OPENCV和BMCV API转换

OPENCV和BMCV API之间的转换，专门在opencv扩展的bmcv名字空间下提供了专门的转换函数。

OPENCV Mat转换到BMCV bm_image格式：

1. cv::Mat m(height, width, CV_8UC3, card_id);
2. opencv 操作
3. bm_image bmcv_image;
4. 这里update用来控制内存同步，是否需要内存同步取决于前面的opencv 操作，如果前面的操作都是用硬件加速完成，设备内存中就是最新数据，就没必要进行内存同步，如果前面的操作调用了opencv函数，没有使用硬件加速（后续opencv章节6.2中提到了哪些函数采用了硬件加速），对于bgr mat格式就需要做内存同步。
5. 也可以在调用下面函数之前，显式的调用cv::bmcv::uploadMat(m)来实现内存同步
6. cv::bmcv::toBMI(m, &bmcv_image, update);
7. 使用bmcv_image就可以进行bmcv api调用，调用期间注意保证Mat m不能被释放，因为bmcv_image使用的是Mat m中分配的内存空间. handle可以通过bm_image_get_handle()获得
8. 释放：必须调用此函数，因为在toBMI中create了bm_image, 否则会有内存泄漏
9. bm_image_destroy(bmcv_image);
10. m.release();

由BMCV bm_image格式转换到OPENCV Mat有两种方式，一种是会发生数据拷贝，这样bm_image和Mat之间相互独立，可以分别释放，但是有性能损失；一种是直接引用bm_image内存，性能没有任何损失。

1. bm_image bmcv_image;
2. 调用bmcv API给bmcv_image分配内存空间，并进行操作
3. Mat m_copy, m_nocopy;
4. 下面接口将发生内存数据拷贝，转换成标准bgr mat格式.
5. update控制内存同步，也可以在调用完这个函数后用bmcv::downloadMat()来控制内存同步
6. csc_type是控制颜色转换系数矩阵，控制不同yuv色彩空间转换到bgr
7. cv::bmcv::toMAT(&bmcv_image, m_copy, update, csc_type);
8. 下面接口接口将直接引用bm_image内存 (nocopy标志位true), update仍然按照之前的描述，
9. 选择是否同步内存。 在后续opencv操作中，必须保证bmcv_image没有释放，因为mat的内存
10. 直接引用自bm_image cv::bmcv::toMAT(&bmcv_image, &m_nocopy, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, NULL, -1, update, true);
11. 进行opencv

# SOPHGO OpenCV使用指南

## OpenCV简介

BM168x系列芯片中的多媒体、BMCV和NPU硬件模块可以加速对图片和视频的处理：

1) 多媒体模块：硬件加速JPEG编码解码 和Video编解码操作。
2) BMCV模块：硬件加速对图片的resize、color conversion、crop、split、linear transform、nms、sort等操作。
3) NPU模块：硬件加速对图片的split、rgb2gray、mean、scale、int8tofloat32操作。

为了方便客户使用芯片上的硬件模块加速图片和视频的处理，提升应用OpenCV软件性能，算能修改了OpenCV库，在其内部调用硬件模块进行Image和Video相关的处理。

算能当前OpenCV的版本为4.1.0，除了以下几个算能自有的API以外，其它的所有API与OpenCV API都是一致的。

BM168x系列芯片有两种应用环境：SOC模式和PCIE卡模式。在SOC模式下，使用BM168x系列内置的ARM A53 core作为主控CPU，直接对芯片内部资源进行控制分配。PCIE模式下，BM168x系列作为PCIE卡插到主机上，由主机CPU通过PCIE接口对资源进行控制分配。SOPHGO OpenCV接口在两种模式下互相兼容，行为基本一致，只有以下微小的差异：

在SOC模式下，由于硬件限制，OpenCV库的Mat对象中，step值会被自动设置为64bytes对齐，不足64bytes的数据用0补齐。而在PCIE模式下，Mat的step不存在64bytes的对齐限制。例如，一张100*100的图片，每个像素的RGB由3个U8值表示，正常的step值为300，但是经过64bytes对齐，step值最终为320。如下图所示，Mat对象的data中，每一个step的数据是连续的320个bytes，其中前300个是真实数据，后面20个是自动填充的0值。

在SOC模式下，由于填充了多余的0值，Mat对象中存储数据的data变量不能直接传递给BMRuntime库的API做推理，否则会降低模型的准确率。请在最后一次BMCV做变换的时候，将stride设置为非对齐方式，多余的0会被自动清除掉。

## 数据结构扩展说明

OpenCV内置标准处理的色彩空间为BGR格式，但是很多情况下，对于视频、图片源，直接在YUV色彩空间上处理，可以节省带宽和避免不必要的YUV和RGB之间的互相转换。因此SOPHGO Opencv对于Mat类进行了扩展。

1) 在Mat.UMatData中，引入了AVFrame成员，扩展支持各种YUV格式。其中AVFrame的格式定义与FFMPEG中的定义兼容
2) 在Mat.UMatData中增加了fd，addr（soc模式下）或hid，mem（pcie模式下）的定义，分别表示对应的内存管理句柄和物理内存地址
3) 在Mat类中增加了fromhardware变量，标识当前的视频、图片解码是由硬件或是软件计算完成的，开发者在程序开发过程中无需考虑该变量的值。

## API扩展说明

### bool VideoCapture::get_resampler(int *den, int *num)

| 函数原型   | bool VideoCapture::get_resampler(int * den, int * num) |
|------------|--------------------------------------------------------|
| 功能       | 获取视频的采样速率。如den=5, num=3表示每5帧中有2帧被丢弃 |
| 输入参数   | int * den – 采样速率的分母<br>int * num – 采样速率的分子 |
| 出输参数   | 无                                                     |
| 返回值     | true - 执行成功<br>false- 执行失败                     |
| 说明       | 此接口将废弃。推荐用3.6接口                            |

### bool VideoCapture::set_resampler(int den, int num)

| 函数原型   | bool VideoCapture::set_resampler(int den, int num)     |
|------------|--------------------------------------------------------|
| 功能       | 设置视频的采样速率。如den=5, num=3表示每5帧中有2帧被丢弃 |
| 输入参数   | int den – 采样速率的分母<br>int num – 采样速率的分子   |
| 出输参数   | 无                                                     |
| 返回值     | true - 执行成功<br>false- 执行失败                     |
| 说明       | 此接口将废弃。推荐用3.5接口                            |

### double VideoCapture::get(CAP_PROP_TIMESTAMP)

| 函数原型   | double VideoCapture::get(CAP_PROP_TIMESTAMP)           |
|------------|--------------------------------------------------------|
| 功能       | 提供当前图片的时间戳，时间基数取决于在流中给出的时间基数 |
| 输入参数   | CAP_PROP_TIMESTAMP – 特定的枚举类型指示获取时间戳,此类型由Sophgo定义 |
| 出输参数   | 无                                                     |
| 返回值     | Convert return value to "int64_t" type before using it.<br>0x8000000000000000L-No AV PTS value |

# VideoCapture::get(CAP_PROP_STATUS)

**函数原型**：`double VideoCapture::get(CAP_PROP_STATUS)`

**功能**：该函数提供了一个接口，用于检查视频抓取的内部运行状态

**输入参数**：CAP_PROP_STATUS – 枚举类型，此类型由Sophgo定义

**输出参数**：无

**返回值**：在使用返回值前请将转换成int类型
- 0：视频抓取停止，暂停或者其他无法运行的状态
- 1：视频抓取正在进行
- 2：视频抓取结束

# VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)

**函数原型**：`double VideoCapture::get(CAP_PROP_OUTPUT_SRC, double resampler)`

**功能**：设置YUV视频的采样速率。如resampler为0.4，表示每5帧中保留2帧，有3帧被丢弃

**输入参数**：
- CAP_PROP_OUTPUT_SRC – 枚举类型，此类型由Sophgo定义
- double resampler – 采样速率

**输出参数**：无

**返回值**：
- true：执行成功
- false：执行失败

# VideoCapture::get(CAP_PROP_OUTPUT_SRC)

**函数原型**：`double VideoCapture::get(CAP_PROP_OUTPUT_SRC)`

**功能**：取视频的采样速率

**输入参数**：CAP_PROP_OUTPUT_SRC – 特定的枚举类型，指视频输出，此类型由SOPHGO定义

**输出参数**：无

**返回值**：采样率数值

# VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)

**函数原型**：`bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)`

**功能**：开或者关闭YUV格式的frame输出。BM168x系列下YUV格式为I420

**输入参数**：
- CAP_PROP_OUTPUT_YUV – 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义
- double enable – 操作码，1表示打开，0表示关闭

**输出参数**：无

**返回值**：
- true：执行成功
- false：执行失败

# VideoCapture::get(CAP_PROP_OUTPUT_YUV)

**函数原型**：`double VideoCapture::get(CAP_PROP_OUTPUT_YUV)`

**功能**：取YUV视频frame输出的状态

**输入参数**：CAP_PROP_OUTPUT_YUV – 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义

**输出参数**：无

**返回值**：YUV视频frame输出的状态。1表示打开，0表示关闭

# bmcv::getCard(int id = 0)

**函数原型**：`bm_handle_t bmcv::getCard(int id = 0)`

**功能**：取SOPHGO OpenCV内部使用的PCIE卡设备句柄。PCIE模式下有效

**输入参数**：int id – PCIE卡序号，SOC下恒定为0

**输出参数**：无

**返回值**：PCIE卡设备句柄

**说明**：通过toBMI接口转换得到bm_image，在调用bmcv API的时候会要求创建bm_image时的句柄，本接口可以支持获取得到该句柄

# bmcv::getId(bm_handle_t handle)

**函数原型**：`int bmcv::getId(bm_handle_t handle)`

**功能**：根据PCIE设备句柄查询卡序号

**输入参数**：Bm_handle_t handle – PCIE设备句柄

**输出参数**：无

**返回值**：PCIE卡的序号

# bmcv::toBMI(Mat &m, bm_image *image, bool update = true)

**函数原型**：`bm_status_t bmcv::toBMI(Mat &m, bm_image*image, bool update = true)`

**功能**：OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不会发生copy操作。本接口仅支持1N模式

**输入参数**：
- Mat& m – Mat对象，可以为扩展YUV格式或者标准OpenCV BGR格式
- bool update – 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存

**输出参数**：bm_image *image – 对应格式的BMCV bm_image数据对象

**返回值**：
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**：当前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换

# bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)

**函数原型**：`bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)`

**功能**：OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不发生copy操作。本接口针对BMCV的4N模式。要求所有Mat的输入图像格式一致

**输入参数**：
- Mat &m – 4N中的第1幅图像，扩展YUV格式或者标准OpenCV BGR格式
- Mat &m1 – 4N中的第2幅图像，扩展YUV格式或者标准OpenCV BGR格式
- Mat &m2 – 4N中的第3幅图像，扩展YUV格式或者标准OpenCV BGR格式
- Mat &m3 – 4N中的第4幅图像，扩展YUV格式或者标准OpenCV BGR格式
- bool update – 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存

**输出参数**：bm_image *image – 对应格式的BMCV bm_image数据对象，其中包含4个图像数据

**返回值**：
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**：当前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换

# bmcv::toMAT(Mat &in, Mat &m0, bool update=true)

**函数原型**：`bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update = true)`

**功能**：输入的MAT对象，可以为各种YUV或BGR格式，转换成BGR packet格式的MAT对象输出

**输入参数**：
- Mat &in - 输入的MAT对象，可以为各种YUV格式或者BGR格式
- bool update – 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存

**输出参数**：Mat &m0 - 输出的MAT对象，转成标准OpenCV的BGR格式

**返回值**：
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**：当前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV420P、BGR separate、BGR packed、CV_8UC1到BGR packed格式转换。在YUV格式下，会自动根据AVFrame结构体中colorspace,color_range信息选择正确的色彩转换矩阵

# toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr = NULL, int fd0 = -1, bool update = true, bool nocopy = true)

**函数原型**：`bm_status_t bmcv::toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr=NULL, int fd0=-1, bool update=true, bool nocopy=true)`

**功能**：输入的bm_image对象，当nocopy为true时，直接复用设备内存转成Mat格式，当nocopy为false时，行为类似3.13otMAT接口，1N模式

**输入参数**：
- bm_image *image - 输入的bm_image对象，可以为各种YUV格式或者BGR格式
- Int color_space – 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义
- Int color_range – 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义
- Void* vaddr – 输出Mat的系统虚拟内存指针，如果已分配，输出Mat直接使用该内存作为Mat的系统内存。如果为NULL，则Mat内部自动分配
- Int fd0 – 输出Mat的物理内存句柄，如果为负，则使用bm_image内的设备内存句柄，否则使用fd0给定的句柄来mmap设备内存
- bool update - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存到系统内存中
- bool nocopy – 如果时true，则直接引用bm_image的设备内存，如果为false，则转换成标准BGR Mat格式

**输出参数**：Mat &m - 输出的MAT对象，当nocopy为true时，输出标准BGR格式或扩展的YUV格式的Mat；当nocopy为false时，转成标准OpenCV的BGR格式

**返回值**：
- BM_SUCCESS(0)：执行成功
- 其他：执行失败

**说明**：
1. no copy方式只支持1N模式，4N模式因为内存排列方式，不能支持引用
2. 在nocopy为false的情况下，会自动根据参数color_space,color_range信息选择正确的色彩转换矩阵进行色彩转换
3. 如果系统内存vaddr来自于外部，那么外部需要来管理这个内存的释放，Mat释放的时候不会释放该内存

# bmcv::toMAT

## 函数原型
```cpp
bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update = true, csc_type_t csc = CSC_MAX_ENUM)
```

## 功能
输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，1N模式

## 输入参数
- `bm_image *image` - 输入的bm_image对象，可以为各种YUV格式或者BGR格式
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存
- `csc_type_t csc` - 色彩转换矩阵，默认为YPbPr2RGB_BT601

## 输出参数
- `Mat &m0` - 输出的MAT对象，转成标准OpenCV的BGR格式

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

---

# bmcv::toMAT (4N模式)

## 函数原型
```cpp
bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update=true, csc_type_t csc=CSC_MAX_ENUM)
```

## 功能
输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，4N模式

## 输入参数
- `bm_image *image` - 输入的4N模式下的bm_image对象，可以为各种YUV格式或者BGR格式
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存
- `csc_type_t csc` - 色彩转换矩阵，默认为YPbPr2RGB_BT601

## 输出参数
- `Mat &m0` - 输出的第一个MAT对象，转成标准OpenCV的BGR格式
- `Mat &m1` - 输出的第二个MAT对象，转成标准OpenCV的BGR格式
- `Mat &m2` - 输出的第三个MAT对象，转成标准OpenCV的BGR格式
- `Mat &m3` - 输出的第四个MAT对象，转成标准OpenCV的BGR格式

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

---

# bmcv::resize

## 函数原型
```cpp
bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation= BMCV_INTER_NEAREST)
```

## 功能
输入的MAT对象，缩放到输出Mat给定的大小，输出格式为输出Mat指定的色彩空间，因为MAT支持扩展的YUV格式，因此本接口支持的色彩空间并不仅局限于BGR packed。

## 输入参数
- `Mat &m` - 输入的Mat对象，可以为标准BGR packed格式或者扩展YUV格式
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存
- `int interpolation` - 缩放算法，可为NEAREST或者LINEAR算法

## 输出参数
- `Mat &out` - 输出的缩放后的Mat对象

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

## 说明
支持Gray、NV12、NV16，YUV444P、YUV420P、BGR separate、BGR packed格式缩放

---

# bmcv::convert

## 函数原型
```cpp
bm_status_t bmcv::convert(Mat &m, Mat &out, bool update=true)
```

## 功能
实现两个mat之间的色彩转换，他与toMat接口的区别在于toMat只能实现各种色彩格式到BGR packed的色彩转换，而本接口可以支持BGR packed或者YUV格式到BGR packed或YUV之间的转换。

## 输入参数
- `Mat &m` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存

## 输出参数
- `Mat &out` - 输出的色彩转换后的Mat对象，可以为BGR packed或者YUV格式。

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

---

# bmcv::convert (多目标转换)

## 函数原型
```cpp
bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update= true, csc_type_t csc=CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix = nullptr, bmcv_resize_algorithm algorithm= BMCV_INTER_LINEAR)
```

## 功能
接口采用内置的VPP硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，给定的多个缩放size，将输入的Mat对象，输出到多个Mat对象中，输出为OpenCV标准的BGR pack格式或扩展YUV格式

## 输入参数
- `Mat &m` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- `std::vector<Rect> &vrt` - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同
- `std::vector<Size> &vsz` - 多个resize大小，与vrt的矩形框一一对应
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存
- `csc_type_t csc` - 色彩转换矩阵，可以根据颜色空间指定合适的色彩转换矩阵
- `csc_matrix_t *matrix` - 当色彩转换矩阵不在列表中时，可以给出外置的用户自定义的转换矩阵
- `bmcv_resize_algorithm algorithm` - 缩放算法，可以为Nearest或者Linear算法

## 输出参数
- `std::vector<Mat> &out` - 输出的缩放、crop以及色彩转换后的标准BGR pack格式或YUV格式的Mat对象。

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

## 说明
接口可以将resize,crop,csc三种操作在一步之内完成，效率最高。在可能的情况下，要尽可能的使用该接口提高效率

---

# bmcv::convert (bm_image输出)

## 函数原型
```cpp
bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update= true)
```

## 功能
接口采用内置的VPP硬件加速单元，集crop,resize和csc于一体。按给定的多个rect框，按照多个bm_image中指定的size，将输入的Mat对象，输出到多个bm_image对象中，输出格式由bm_image初始化值决定。注意，bm_image必须由调用者初始化好，并且个数和vrt一一对应。

## 输入参数
- `Mat &m` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- `std::vector<Rect> &vrt` - 多个rect框，输入Mat中的ROI区域。矩形框个数和resize个数应该相同
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存

## 输出参数
- `bm_image *out` - 输出的缩放、crop以及色彩转换后的bm_image对象，输出色彩格式由bm_image初始化值决定。同时该参数初始化的size、色彩信息也作为输入信息，用于处理。

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

---

# bmcv::uploadMat

## 函数原型
```cpp
void bmcv::uploadMat(Mat &mat)
```

## 功能
cache同步或者设备内存同步接口。当执行此函数时，cache中内容会flush到实际内存中（SOC模式），或者host内存同步到PCIE卡设备内存（PCIE模式）。

## 输入参数
- `Mat &mat` - 输入的需要内存同步的mat对象

## 输出参数
- 无

## 返回值
- 无

## 说明
合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。这在PCIE模式下更为重要，因为每次PCIE设备内存的同步时间耗时较大。

---

# bmcv::downloadMat

## 函数原型
```cpp
void bmcv::downloadMat(Mat &mat)
```

## 功能
cache同步或者设备内存同步接口。当执行此函数时，cache中内容会invalidate（SOC模式），或者PCIE卡设备内存同步到host内存中（PCIE模式）。本接口的内存同步方向与uploadMat接口正好相反

## 输入参数
- `Mat &mat` - 输入的需要内存同步的mat对象

## 输出参数
- 无

## 返回值
- 无

## 说明
合理调用本接口，可以有效控制内存同步的次数，仅在需要的时候调用。这在PCIE模式下更为重要，因为每次PCIE设备内存的同步时间耗时较大。

---

# bmcv::stitch

## 函数原型
```cpp
bm_status_t bmcv::stitch(std::vector<Mat> &in, std::vector<Rect>& srt, std::vector<Rect>& drt, Mat &out, bool update = true, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)
```

## 功能
图像拼接，将输入的多个Mat按照按照给定的位置缩放并拼接到一个Mat中

## 输入参数
- `std::vector<Mat> &in` - 多个输入的Mat对象，可以为扩展的YUV格式或者标准BGR pack格式
- `std::vector<Rect> &src` - 对应每个Mat对象的显示内容框
- `std::vector<Rect> &drt` - 对应每个显示内容在目标Mat中的显示位置
- `bool update` - 是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存
- `bmcv_resize_algorithm algorithm` - 缩放算法，可以为Nearest或者Linear算法

## 输出参数
- `Mat &out` - 输出拼接后的Mat对象，可以为BGR packed或者YUV格式

## 返回值
- `BM_SUCCESS(0)`：执行成功
- 其他：执行失败

---

# bmcv::print (Mat)

## 函数原型
```cpp
void bmcv::print(Mat &m, bool dump = false)
```

## 功能
调试接口，打印输入Mat对象的色彩空间，宽高以及数据。

## 输入参数
- `Mat &m` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- `bool dump` - true的时候打印Mat中的数据值，默认不打印。如果为true，则会在当前目录下生成mat_dump.bin文件

## 输出参数
- 无

## 返回值
- 无

## 说明
当前支持dump OpenCV标准BGR packed或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式数据

---

# bmcv::print (bm_image)

## 函数原型
```cpp
void bmcv::print(bm_image *image, bool dump)
```

## 功能
调试接口，打印输入bm_image对象的色彩空间，宽高以及数据。

## 输入参数
- `bm_image *image` - 输入的bm_image对象
- `bool dump` - true的时候打印Mat中的数据值，默认不打印，如果为true，则会在当前目录下生成BMI-"宽"x"高".bin文件

## 输出参数
- 无

## 返回值
- 无

## 说明
当前支持dump BGR packed, NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式的bm_image数据

---

# bmcv::dumpMat

## 函数原型
```cpp
void bmcv::dumpMat(Mat &image, const String &fname)
```

## 功能
调试接口，专门dump Mat的数据到指定命名的文件。功能同print的dump为true时的功能。

## 输入参数
- `Mat &image` - 输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式
- `const String &fname` - dump的输出文件名

## 输出参数
- 无

## 返回值
- 无

## 说明
当前支持dump OpenCV标准BGR packed或者CV_8UC1数据，以及扩展的NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P和BGR Separate格式数据

# dumpBMImage

## 函数原型
```cpp
void bmcv::dumpBMImage(bm_image *image, const String &fname)
```

## 功能
测试接口，专门dump bm_image的数据到指定命名的文件。功能同3.25的dump为true时的功能。

## 输入参数
- `bm_image *image` - 输入的bm_image对象
- `const String &fname` - dump的输出文件名

## 输出参数
无

## 返回值
无

## 说明
当前支持dump BGR packed, NV12, NV16, YUV420P, YUV422P, GRAY, YUV444P和BGR Separate格式的bm_image数据

# avOK

## 函数原型
```cpp
bool Mat::avOK()
```

## 功能
判断当前Mat是否为扩展的YUV格式

## 输入参数
无

## 输出参数
无

## 返回值
- `true` - 表示当前Mat为扩展的YUV格式
- `false` - 表示当前Mat为标准OpenCV格式

## 说明
接口和接口3.21 3.22 downloadMat、uploadMat结合起来，可以有效地管理内存同步。一般avOK为true的Mat，物理内存或者PCIE卡设备内存是最新的，而avOK为false的Mat，其cache或者host内存中的数据是最新的。可以根据这个信息，决定是调用uploadMat还是downloadMat。如果一直在设备内存中通过硬件加速单元工作，则可以省略内存同步，仅在需要交换到系统内存中时再调用downloadMat。

# avCols

## 函数原型
```cpp
int Mat::avCols()
```

## 功能
获取YUV扩展格式的Y的宽

## 输入参数
无

## 输出参数
无

## 返回值
返回扩展的YUV格式的Y的宽，如果为标准OpenCV Mat格式，返回0

# avRows

## 函数原型
```cpp
int Mat::avRows()
```

## 功能
获取YUV扩展格式的Y的高

## 输入参数
无

## 输出参数
无

## 返回值
返回扩展的YUV格式的Y的高，如果为标准OpenCV Mat格式，返回0

# avFormat

## 函数原型
```cpp
int Mat::avFormat()
```

## 功能
获取YUV格式信息

## 输入参数
无

## 输出参数
无

## 返回值
返回扩展的YUV格式信息，如果为标准OpenCV Mat格式，返回0

# avAddr

## 函数原型
```cpp
int Mat::avAddr(int idx)
```

## 功能
获取YUV各分量的物理地址

## 输入参数
- `int idx` - 指定YUV plane的序号

## 输出参数
无

## 返回值
返回指定的plane的物理首地址，如果为标准OpenCV Mat格式，返回0

# avStep

## 函数原型
```cpp
int Mat::avStep(int idx)
```

## 功能
获取YUV格式中指定plane的line size

## 输入参数
- `int idx` - 指定YUV plane的序号

## 输出参数
无

## 返回值
指定的plane的line size，如果为标准OpenCV Mat格式，返回0

# av::create (完整版本)

## 函数原型
```cpp
AVFrame* av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MMPEG, int id = 0)
```

## 功能
AVFrame的创建接口，允许外部创建系统内存和物理内存，创建的格式与FFMPEG下的AVFrame定义兼容

## 输入参数
- `int height` - 创建图像数据的高
- `int width` - 创建图像数据的宽
- `int color_format` - 创建图像数据的格式，详见FFMPEG pixfmt.h定义
- `void *data` - 系统内存地址，当为null时，表示该接口内部自己创建管理
- `long addr` - 设备内存地址
- `int fd` - 设备内存地址的句柄。如果为-1，表示设备内存由内部分配，反之则由addr参数给出。在pcie模式下，如果设备内存由外部给出，该值可以设为0，在soc模式下，该值应该为ion内存的句柄
- `int* plane_stride` - 图像数据每层的每行stride数组
- `int* plane_size` - 图像数据每层的大小
- `int color_space` - 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义，默认为AVCOL_SPC_BT709
- `int color_range` - 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义，默认为AVCOL_RANGE_MPEG
- `int id` - 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

## 输出参数
无

## 返回值
AVFrame结构体指针

## 说明
1. 本接口支持创建以下图像格式的AVFrame数据结构：AV_PIX_FMT_GRAY8, AV_PIX_FMT_GBRP, AV_PIX_FMT_YUV420P, AV_PIX_FMT_NV12, AV_PIX_FMT_YUV422P horizontal, AV_PIX_FMT_YUV444P, AV_PIX_FMT_NV16
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建失败

# av::create (简易版本)

## 函数原型
```cpp
AVFrame* av::create(int height, int width, int id = 0)
```

## 功能
AVFrame的简易创建接口，所有内存均由内部创建管理，仅支持YUV420P格式

## 输入参数
- `int height` - 创建图像数据的高
- `int width` - 创建图像数据的宽
- `int id` - 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

## 输出参数
无

## 返回值
AVFrame结构体指针

## 说明
本接口仅支持创建YUV420P格式的AVFrame数据结构

# av::copy

## 函数原型
```cpp
int av::copy(AVFrame *src, AVFrame *dst, int id)
```

## 功能
AVFrame的深度copy函数，将src的有效图像数据拷贝到dst中

## 输入参数
- `AVFrame *src` - 输入的AVFrame原始数据指针
- `int id` - 指定设备卡号，详见5.1

## 输出参数
- `AVFrame *dst` - 输出的AVFrame目标数据指针

## 返回值
返回copy的有效图像数据个数，为0则没有发生拷贝

## 说明
1. 本接口仅支持同设备卡号内的图像数据拷贝，即id相同
2. 函数中的id仅需要指定设备卡号，不需要其他标志位

# av::get_scale_and_plane

**函数原型**  
`int av::get_scale_and_plane(int color_format, int wscale[], int hscale[])`

**功能**  
取指定图像格式相对于YUV444P的宽高比例系数

**输入参数**  
- `int color_format` – 指定图像格式，详见FFMPEG pixfmt.h定义

**输出参数**  
- `int wscale[]` – 对应格式相对于YUV444P每一层的宽度比例
- `int hscale[]` – 对应格式相对于YUV444P每一层的高度比例

**返回值**  
返回给定图像格式的plane层数

**说明**  

# cv::Mat(AVFrame *frame, int id)

**函数原型**  
`cv::Mat(AVFrame *frame, int id)`

**功能**  
增的Mat构造接口。根据AVFrame指针信息构造扩展的YUV Mat数据

**输入参数**  
- `AVFrame *frame` – AVFrame数据，可以来自FFMPEG或者cv::av下方法创建
- `int id` – 指定PCIE设备卡号以及AVFRAME_ATTACHED标志，详见5.1

**输出参数**  
构造的扩展Mat数据类型

**返回值**  
无

**说明**  
当AVFRAME_ATTACHED标志位为1时，表示frame由外部创建并释放，不需要Mat来管理；反之则在释放Mat的同时释放frame指向的内存块

# cv::Mat(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, SophonDevice device=SophonDevice())

**函数原型**  
`cv::Mat(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, SophonDevice device=SophonDevice())`

**功能**  
增的Mat构造接口。可以创建opencv 标准格式或扩展的YUV Mat格式，并且系统内存和设备内存都允许通过外部分配给定

**输入参数**  
- `int height` – 输入图像数据的高
- `int width` – 输入图像数据的宽
- `int total` – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小
- `int _type` – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1
- `const size_t *steps` – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP
- `void *_data` – 系统内存指针，如果为null，则内部分配该内存
- `unsigned long addr` – 设备物理内存地址，任意值均被认为有效的物理地址
- `int fd` – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理
- `SophonDevice device` –指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

**输出参数**  
构造的标准BGR或扩展YUV的Mat数据类型

**返回值**  
无

**说明**  
1. SophonDevice是为了避免C++隐含类型匹配造成函数匹配失误而引入的类型，可以用SophonDevice(int id)直接从5.1节的ID转换过来
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存

# Mat::Mat(SophonDevice device)

**函数原型**  
`Mat::Mat(SophonDevice device)`

**功能**  
增的Mat构造接口，指定该Mat的后续操作在给定的device设备上

**输入参数**  
- `SophonDevice device` – 指定设备卡号以及HEAP位置的标志，详见5.1

**输出参数**  
声明Mat数据类型

**返回值**  
无

**说明**  
1. 本构造函数仅初始化Mat内部的设备index，并不实际创建内存
2. 本构造函数的最大作用是对于某些内部create内存的函数，可以通过这个构造函数，提前指定创建内存的设备号和HEAP位置，从而避免将大量的内存分配在默认的设备号0上

# void Mat::create(AVFrame *frame, int id)

**函数原型**  
`void Mat::create(AVFrame *frame, int id)`

**功能**  
at分配内存的接口，根据AVFrame指针信息构造扩展的开辟YUV Mat内存

**输入参数**  
- `AVFrame *frame` – AVFrame数据，可以来自FFMPEG或者cv::av下方法创建
- `int id` – 指定PCIE设备卡号以及AVFRAME_ATTACHED标志，详见5.1

**输出参数**  
无

**返回值**  
无

**说明**  
1. 当AVFRAME_ATTACHED标志位为1时，表示frame由外部创建并释放，不需要Mat来管理；反之则在释放Mat的同时释放frame指向的内存块
2. 当原来的Mat已经分配了内存的话，如果该内存满足AVFrame的要求，则复用该内存，反之则会自动释放原内存，并重新分配

# void Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data, unsigned long addr, int fd, int id = 0)

**函数原型**  
`void Mat::create(int height, int width, int total, int type, const size_t* _steps, void* _data, unsigned long addr, int fd, int id = 0)`

**功能**  
at分配内存接口，该接口系统内存和设备内存都允许通过外部分配给定，也可内部分配。

**输入参数**  
- `int height` – 输入图像数据的高
- `int width` – 输入图像数据的宽
- `int total` – 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小
- `int _type` – Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1
- `const size_t *steps` – 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP
- `void *_data` – 系统内存指针，如果为null，则内部分配该内存
- `unsigned long addr` – 设备物理内存地址，任意值均被认为有效的物理地址
- `int fd` – 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理
- `int id` – 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0

**输出参数**  
无

**返回值**  
无

**说明**  
1. 扩展的内存分配接口，主要改进目的是允许外置指定设备物理内存，当设备或者系统内存由外部创建的时候，则外部必须负责该内存的释放，否则会造成内存泄漏
2. 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存

# void VideoWriter::write(InputArray image, char *data, int *len)

**函数原型**  
`void VideoWriter::write(InputArray image, char *data, int len)`

**功能**  
增的视频编码接口。与OpenCV标准VideoWriter::write接口不同，他提供了将编码视频数据输出到buffer的功能，便于后续处理

**输入参数**  
- `InputArray image` – 输入的图像数据Mat结构

**输出参数**  
- `char *data` – 输出的编码数据缓存
- `int *len` – 输出的编码数据长度

**返回值**  
无

# virtual bool VideoCapture::grab(char *buf, unsigned int len_in, unsigned int *len_out);

**函数原型**  
`bool VideoCapture::grab(char *buf, unsigned int len_in, usigned int *len_out);`

**功能**  
增的收流解码接口。与OpenCV标准VideoWriter::grab接口不同，他提供了将解码前的视频数据输出到buf的功能。

**输入参数**  
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

**输出参数**  
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

**返回值**  
true 表示收流解码成功；false表示收流解码失败

# virtual bool VideoCapture::read_record(OutputArray image, char *buf, unsigned int len_in, unsigned int *len_out);

**函数原型**  
`bool VideoCapture::read_record(OutputArray image, char buf, unsigned int len_in, unsigned int *len_out);`

**功能**  
增的读取码流视频接口。他提供了将解码前的视频数据输出到buf的功能，将解码后的数据输出到image。

**输入参数**  
- `char *buf` – 外部负责分配释放内存
- `unsigned int len_in` – buf空间的大小

**输出参数**  
- `OutputArray image` – 输出解码后的视频数据
- `char *buf` – 输出解码前的视频数据
- `int *len_out` – 输出的buf的实际大小

**返回值**  
true 表示收流解码成功；false表示收流解码失败

# 硬件JPEG解码器的OpenCV 扩展

在BM168x系列芯片中，提供JPEG硬件编码解码模块。为使用这些硬件模块，SDK软件包中，扩展了OpenCV中与JPEG图片处理相关的API函数，如：cv::imread()、 cv::imwrite()、cv::imdecode()、cv::imencode()等。您在使用这些函数做JPEG编解码的时候，函数内部会自动调用底层的硬件加速资源，从而大幅度提高了编解码的效率。如果您想保持这些函数原始的OpenCV API使用习惯，可以略过本节介绍；但如果你还想了解一下我们提供的简单易用的扩展功能，这节可能对您非常有帮助。

## 输出yuv格式的图像数据

OpenCV原生的cv::imread()、cv::imdecode() API函数执行JPEG图片的解码操作，返回一个Mat结构体，该Mat结构体中保存有BGR packed格式的图片数据，算能扩展的API函数功能可以返回JPEG图片解码后的原始的YUV格式数据。用法如下：

当这两个函数的第二个参数flags被设置成cv::IMREAD_AVFRAME时，表示解码后返回的Mat结构体out中保存着YUV格式的数据。具体是什么格式的YUV数据要根据JPEG文件的image格式而定。当flags被设置成其它值或者省略不设置时，表示解码输出OpenCV原生的BGR packed格式的Mat数据。解码器输入输出扩展数据格式说明如下表所示：

| 输入Image格式 | 输入YUV格式 | FFMPEG对应格式 |
|---------------|-------------|----------------|
| I400          | I400        | AV_PIX_FMT_GRAY8 |
| I420          | NV12        | AV_PIX_FMT_NV12 |
| I422          | NV16        | AV_PIX_FMT_NV16 |
| I444          | I444 planar | AV_PIX_FMT_YUV444P |

可以通过Mat::avFormat()扩展函数，得到当前数据所对应的具体的FFmpeg格式。可以通过Mat::avOK()扩展函数，得知cv::imdecode(buf, cv::IMREAD_AVFRAME, &out)解码返回的out，是否是算能扩展的Mat数据格式。

另外在这两个接口中的flags增加cv::IMREAD_RETRY_SOFTDEC标志时会在硬件解码失败的情况下尝试切换软件解码，也可以通过设置环境变量OPENCV_RETRY_SOFTDEC=1实现此功能。

## 支持YUV格式的函数列表

目前算能Opencv已经支持YUV Mat扩展格式的函数接口列表如下：

### 视频解码类接口
- VideoCapture类的成员函数

这类成员函数如read, grab，对于常用的HEVC, H264视频格式都使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

### 视频编码类接口
- VideoWriter类的成员函数

这类成员函数如write，对于常用的HEVC,H264视频格式已经使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

### JPEG编码类接口
### JPEG解码类接口
- Imread
- Imwrite
- Imdecode
- Imencode

以上接口在处理JPEG格式的时候，已经使用了BM168x系列的硬件加速功能，并支持YUV Mat扩展格式。

### 图像处理类接口
- cvtColor
- resize

这两个接口在BM168x系列 SOC模式下支持YUV Mat扩展格式，并使用硬件加速进行了优化。在PCIE模式下，考虑到服务器的CPU性能较强，仍然采用原来的opencv原生处理方式，并不支持YUV扩展格式。

- line
- rectangle
- circle
- putText

以上四个接口均支持YUV扩展格式。注意，这四个接口并没有采用硬件加速，而是使用CPU对YUV Mat扩展格式进行的支持。

### 基本操作类接口
- Mat类部分接口
  - 创建释放接口：create，release，Mat声明接口
  - 内存赋值接口：clone，copyTo， cloneAll，copyAllTo，assignTo, operator =
  - 扩展AV接口：avOK, avComp, avRows, avCols, avFormat, avStep, avAddr

以上接口均支持YUV扩展格式，尤其是copyTo, clone接口都采用硬件进行了加速。

### 扩展类接口
- Bmcv接口: 详见opencv2/core/bmcv.hpp
- AvFrame接口: 详见opencv2/core/av.hpp

以上算能扩展类接口，均支持YUV Mat扩展格式，并均针对硬件加速处理进行了优化。

**注意：支持YUV Mat扩展格式的接口并不等价于使用了硬件加速，部分接口是通过CPU处理来实现。这点需要特别注意。**

# 指定PCIE设备运行硬件加速

本节内容适用于VideoCapture, 图像编解码的Imread, Imwrite等接口。

## ID参数的定义

ID参数为32位整型，它定义了pcie设备卡以及部分内存扩展标志信息，具体定义如下：

| Bit位域 | 描述 |
|---------|------|
| Bit0-7 | 描述了PCIE设备的卡号，宏定义BM_CARD_ID(id)可以获取这信息 |
| Bit8-10 | 描述对应PCIE卡上的HEAP内存位置。Bit8为1表示硬件内存分配在 heap0上；Bit9为1表示硬件内存内存分配在 heap1上；Bit10为1表示硬件内存内存分配在 heap2上；Bit8-10全为0默认分配在 heap1上；Heap0/1/2的内存位置详见BMLIB API手册。宏定义BM_CARD_HEAP(id)可获取该信息 |
| Bit11-20 | 描述了Mat的内存扩展标志。B11-B18为opencv标准定义，见MemoryFlag枚举类型B19-为扩展的DEVICE_MEM_ATTACHED，标志该设备内存为外部管理，不需要Opencv来管理释放 B20-为扩展的AVFRAME_ATTACHED，标志创建YUV Mat的AVFrame为外部管理，不需要Opencv来管理释放。宏定义BM_CARD_MEMFLAG(id)可获取该信息 |
| B21-31 | 扩展保留 |
| 说明: 宏定义BM_MAKEFLAG(attach,heap,card)可用来生成完整的ID定义，其中attach对应B11-20,heap对应B8-10,card对应B0-7 | |

## 利用ID参数指定PCIE设备

在PCIE模式下，多设备情况下需要指定在特定卡上运行硬件加速功能。为了满足这个需要，SOPHGO OpenCV对VideoCapture::Open, imread, imdecode以及mat.create接口进行了扩展，增加了int id参数。

```
bool VideoCapture::open(const String& filename, int apiPreference, int id)

Mat imdecode(InputArray _buf, int flags, int id )

Mat imread(const String& filename, int flags, int id )

void Mat::create(int d, const int* _sizes, int _type, int id)
```

通过指定id，可以指定视频解码、图片解码运行在指定PCIE设备上，并且解码出来的Mat输出记录了该PCIE卡设备的序号。后续的硬件加速操作会继续在该指定PCIE设备上运行。

对于输入是Mat的大部分接口来说，因为Mat在调用create接口分配内存的时候已经指定了设备号，就不需要额外增加参数来指定PCIE卡设备。可以根据Mat内置的设备号在对应的设备上进行加速处理。

## OpenCV与BMCV API的调用原则

BMCV API充分发挥了BM168x系列芯片中的硬件单元的加速能力，能提高数据处理的效率。而OpenCV软件提供了非常丰富的图像图形处理能力，将两者有机的结合起来，使客户开发既能利用OpenCV丰富的函数库，又能在硬件支持的功能上获得加速，是本节的主要目的。

在BMCV API和OpenCV函数以及数据类型的切换过程中，最关键是要尽量避免数据拷贝，使得切换代价最小。因此在调用流程中要遵循以下原则。

1) 由OpenCV Mat到BMCV API的切换，可以利用toBMI()函数，该函数以零拷贝的方式，将Mat中的数据转换成了BMCV API调用所需的bm_image类型。

2) 当BMCV API需要切换到OpenCV Mat的时候，要将最后一步的操作通过OpenCV中的bmcv函数来实现。这样既完成所需的图像处理操作，同时也为后续OpenCV操作完成了数据类型准备。因为一般OpenCV都要求BGR Pack的色彩空间，所以一般用toMat()函数作为切换前的最后一步操作。

3) 一般神经网络处理的数据为不带padding的RGB planar数据，并且对于输入尺寸有特定的要求。因此建议将resize()函数作为调用神经网络NPU接口前的最后一步操作。

4) 当crop、resize、color conversion三个操作是连续的时候，强烈建议客户使用convert()函数，这可以在带宽优化和速度优化方面都获得理想的收益。即使后续可能还需要做一次拷贝，但因为拷贝发生在缩放之后的图像上，这种代价也是值得的。

## OpenCV中GB28181国标接口介绍

SOPHGO复用OpenCV原生的Cap接口，通过对于url定义进行扩展，提供GB28181国标的播放支持。因此客户并不需要重新熟悉接口，只要对扩展的url定义进行理解，即可像播放rtsp视频一样，无缝的播放GB28181视频。

注意：国标中的SIP代理注册步骤，需要客户自己管理。当获取到前端设备列表后，可以直接用url的方式进行播放。

### 国标GB28181支持的一般步骤

- 启动SIP代理（一般客户自己部署或者平台方提供）
- 客户的下级应用平台注册到SIP代理
- 客户应用获取前端设备列表，如下所示。其中，34010000001310000009等为设备20位编码。

```
{"devidelist":
[{"id": "34010000001310000009"}
{"id": "34010000001310000010"}
{"id": "34020000001310101202"}]}
```

- 组织GB28181 url直接调用OpenCV Cap接口进行播放

## GB28181 url格式定义

### UDP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?
deviceid=34010000001310000009#localid=12478792871163624979
#localip=172.10.18.201#localmediaport=20108
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`: 前端设备20位编码
- `localid`: 本地二十位编码，可选项
- `localip`: 本地ip，可选项
- `localmediaport`: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

### UDP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?
deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979
#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000
#endtime=20191026163713
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`: 前端设备20位编码
- `devicetype`: 录像存储类型
- `localid`: 本地二十位编码，可选项
- `localip`: 本地ip，可选项
- `localmediaport`: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。
- `begtime`: 录像起始时间
- `endtime`: 录像结束时间

### TCP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?
deviceid=35018284001310090010#localid=12478792871163624979
#localip=172.10.18.201
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`: 前端设备20位编码
- `localid`: 本地二十位编码，可选项
- `localip`: 本地ip，可选项

### TCP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?
deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979
#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713
```

**注释**

- `34020000002019000001:123456@35.26.240.99:5666`: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
- `deviceid`: 前端设备20位编码
- `devicetype`: 录像存储类型
- `localid`: 本地二十位编码，可选项
- `localip`: 本地ip，可选项
- `begtime`: 录像起始时间
- `endtime`: 录像结束时间

## PCIE模式下BMCPU OPENCV加速

### 概念介绍

Opencv有大量的图像处理函数在host cpu上实现，这样在PCIE环境下，就造成了host和板卡device设备之间交换同步内存的需求，而这种内存同步的速度要远远大于内存cache的同步数据，从而给PCIE环境下的应用开发造成了瓶颈。而我们在的BM168x板卡上的每颗SOC都有强大的ARM Cortex A53处理器资源，目前在PCIE环境下处于闲置状态，因此BMCPU Opencv试图将Host Opencv和Device Opencv之间的功能函数映射起来，将Host Opencv的操作实际用Device Opencv的操作来实现，保证所有的数据都在Device Memory中进行，无需通过PCIE和host发生交换，从而一方面降低对Host CPU的压力，降低CPU处理器的处理性能要求，另一方面提高运行速度，消除PCIE带宽所带来的瓶颈。

BMCPU OPENCV的函数用法与原生OPENCV完全一致，只是为了区别在前面加上"bmcpu_"前缀。

### 使用说明

**说明1. 凡是用BMCPU OPENCV改造过的接口，最新数据都位于device memory中。**

这点与之前的opencv cache管理策略有不同。之前在YUV Mat中，最新数据都位于device memory中，而在RGB Mat中，最新数据都位于host memory中。经过BMCPU OPENCV引入后，后续当函数支持到足够数目的时候，我们将在PCIE模式下，无论RGB Mat还是YUV Mat都以device memory为准，这样所有的pcie opencv操作的内存都移到了device memory上，不占用host memory。

**在达到这个目的之前，为了兼容原有opencv函数的调用，保留原函数，然后统一加上"bmcpu_"前缀的方式，重命名已修改的函数。** 可以查询我们的已完成函数列表来做对应操作。

对于列表中的函数，无论yuv Mat还是RGB Mat最新数据都在device memory中。当客户需要将其同步到host memory中的时候，需要手动调用bmcv::downloadMat()接口，当需要将host memory中的数据同步到device memory中时，需要调用bmcv::uploadMat()接口。

这点尤其重要，在调用改造过的函数前，如果最新数据在host memory中，就需要将其同步到device memory。**这在当Mat采用Scalar::all()，Zeros(), Ones()等函数初始化的时候尤其容易忽略，这时候要记得调用bmcv::uploadMat()将初始化同步到设备内存中。** 反之，当函数结束，后续处理需要在host memory中进行的时候，就需要调用bmcv::downloadMat()下载下来。

当输入输出Mat没有device内存的时候，函数会自动同步到host内存中，并且释放内部开辟的device内存。

**说明2. 参数传递的时候，要求与Mat有关的参数放在最前面。因为Mat的内存结构是提前分配好的，只能修改，不能重新分配。**

**说明3. 已完成函数列表**

| 已完成函数接口 | 修改后函数说明 | 备注 |
|---------------|---------------|------|
| cv::calcOpticalFlowPyrLK() | cv::bmcpu_calcOpticalFlowPyrLK() | 稀疏光流函数，支持标准BGR Mat格式 |
| cv::calcOpticalFlowFarneback() | cv::bmcpu_calcOpticalFlowFarneback() | 稠密光流函数，支持标准BGR Mat格式 |
| cv::gaussianBlur() | cv::bmcpu_gaussianBlur() | 支持BGR Mat格式 |
| cv::bilateralFilter() | cv::bmcpu_bilateralFilter() | 支持BGR Mat格式 |
| cv::boxFilter() | cv::bmcpu_boxFilter() | 支持BGR Mat格式 |
| cv::calcHist() | cv::bmcpu_calcHist() | calcHist函数共有三个函数类型，除了SparseMat不支持外，其他两个均支持 |
| cv::warpAffine() | cv::bmcpu_warpAffine() | 支持BGR Mat格式 |
| cv::sobel() | cv::bmcpu_sobel() | 支持BGR Mat格式 |
| cv::erode() | cv::bmcpu_erode() | 支持BGR Mat格式 |
| cv::dialet() | cv::bmcpu_dialet() | 支持BGR Mat格式 |
| cv::morphologyEx | cv::bmcpu_morphologyEx() | 支持BGR Mat格式 |
| cv::line() | cv::bmcpu_line() | Open cv中的画线函数，可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::putText() | cv::bmcpu_putText() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::rectangle() | cv::bmcpu_rectangle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::circle() | cv::bmcpu_circle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse() | 1,对应opencv中的函数:void ellipse (InputOutput Array _img, Point center, Size axes,double angle,double start_angle,double end_angle,const Scalar & color,int thickness,int line_type,int shift) 2, 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse2() | 1,对应opencv中的函数:void ellipse(InputOutput Array _img, const RotatedRect& box, const Scalar & color,int thickness, int lineType) 2，可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::polylines() | cv::bmcpu_polylines() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| FreeType2::loadFontData() | cv::bmcpu_loadFontData() | 对应FreeType2类加载字库 |
| | cv::bmcpu_unloadFontData() | 释放字库资源，与bmcpu_loadFontData成对调用 |
| FreeType2::setSplitNumber() | cv::bmcpu_setSplitNumber() | Ft2类接口 |
| FreeType2::getTextSize() | cv::bmcpu_getTextSize() | Ft2类接口 |
| FreeType2::putText() | cv::bmcpu_ft2_putText() | 可同时支持YUV和RGB Mat |

## 代码实例

代码实例见examples/multimedia。

# SOPHGO FFMPEG使用指南

## 前言

BM168x系列芯片中，有一个8核的A53处理器，同时还内置有视频、图像相关硬件加速模块。在SOPHGO提供的FFMPEG SDK开发包中，提供了对这些硬件模块的接口。其中，通过这些硬件接口，提供了如下模块：硬件视频解码器、硬件视频编码器、硬件JPEG解码器、硬件JPEG编码器、硬件scale filter、hwupload filter、hwdownload filter。

FFMPEG SDK开发包符合FFMPEG hwaccel编写规范，实现了视频转码硬件加速框架，实现了硬件内存管理、各个硬件处理模块流程的组织等功能。同时FFMPEG SDK也提供了与通常CPU解码器兼容的接口，以匹配部分客户的使用习惯。这两套接口我们称之为HWAccel接口和常规接口，他们底层共享BM168x硬件加速模块，在性能上是相同的。区别仅在于1）HWAccel需要初始化硬件设备; 2）HWAccel接口只面向设备内存，而常规接口同时分配了设备内存和系统内存; 3）他们的参数配置和接口调用上有轻微差别。

下面描述中，如非特殊说明，对常规接口和HWAccel接口都适用。

## 硬件视频解码器

BM168x系列支持H.264和H.265硬件解码。硬件解码器性能详情如下表所述。

| **Standard** | **Profile** | **Level** | **Max Resolution** | **Min Resolution** | **Bit rate** |
|--------------|-------------|-----------|-------------------|-------------------|-------------|
| H.264/AVC | BP/CBP/MP/HP | 4.1 | 8192x8192 | 16x16 | 50Mbps |
| H.265/HEVC | Main/Main10 | L5.1 | 8192x8192 | 16x16 | N/A |

在SophGo的FFMPEG发布包中，H.264硬件视频解码器的名字为*h264_bm*，H.265硬件视频解码器的名字为*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -decoders | grep _bm
```

### 硬件视频解码器支持的选项

FFMPEG中，BM168x系列的硬件解码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h decoder=h264_bm
$ ffmpeg -h decoder=hevc_bm
```

这些选项可以使用av_dict_set API来设置。在设置之前，需要对对这些选项有正确的理解。下面详细解释一下这些选项。

**output_format:**
- 输出数据的格式。
- 设为0，则输出线性排列的未压缩数据；设为101，则输出压缩数据。
- 缺省值为0。
- *推荐设置为101，输出压缩数据。可以节省内存、节省带宽。输出的压缩数据，可以调用后面介绍的scale_bm filter解压缩成正常的YUV数据。具体可参考应用示例中的示例1。*

**cbcr_interleave:**
- 硬件视频解码器解码输出的帧色度数据是否是交织格式。
- 设为1，则输出为semi-planar yuv图像，譬如nv12；设为0，则输出planar yuv图像，譬如yuv420p。
- 缺省值为1。

**extra_frame_buffer_num:**
- 硬件视频解码器额外提供硬件帧缓存数量。
- 缺省值为7。最小值为1。

**skip_non_idr:**
- 跳帧模式。0，关闭；1，跳过Non-RAP帧；2，跳过非参考帧。
- 缺省值为0。

**handle_packet_loss**
- 出错时，对H.264, H.265解码器使能丢包处理。0, 不做丢包处理；1，进行丢包处理。
- 缺省值为0。

**sophon_idx:**
- PCIE模式下的sophon设备的编号。与/dev/bm-sophon的设备编号一致。
- 缺省值为0。

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的系统内存里。1，关闭拷贝；0，使能拷贝。
- 缺省值为1。

## 硬件视频编码器

从BM1684开始首次添加了硬件视频编码器。支持H.264/AVC和H.265/HEVC视频编码。

BM1684硬件编码器设计的能力为: 能够实时编码10路1080P30的视频。具体指标如下：

**H.265编码器:**
- Capable of encoding HEVC Main/Main10/MSP(Main Still Picture) Profile @ L5.1 High-tier

**H.264编码器:**
- Capable of encoding Baseline/Constrained Baseline/Main/High/High 10 Profiles Level @ L5.2

**通用指标**
- 最大分辨率 : 8192x8192
- 最小分辨率 : 256x128
- 编码图像宽度须为8的倍数
- 编码图像高度宽度须为8的倍数

在SophGo的FFMPEG发布包中，H.264硬件视频编码器的名字为*h264_bm*，H.265硬件视频编码器的名字为*h265_bm*或*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -encoders
```

### 硬件视频编码器支持的选项

FFMPEG中，硬件视频编码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h encoder=h264_bm
$ ffmpeg -h encoder=hevc_bm
```

BM1684硬件视频编码器支持如下选项:

**preset:** 预设编码模式。推荐通过enc-params设置。
- 0 - fast, 1 - medium, 2 - slow。
- 缺省值为2。

**gop_preset:** gop预设索引值。推荐通过enc-params设置。
- 1: all I, gopsize 1
- 2: IPP, cyclic gopsize 1
- 3: IBB, cyclic gopsize 1
- 4: IBPBP, cyclic gopsize 2
- 5: IBBBP, cyclic gopsize 4
- 6: IPPPP, cyclic gopsize 4
- 7: IBBBB, cyclic gopsize 4
- 8: random access, IBBBBBBBB, cyclic gopsize 8

**qp:**
- 恒定量化参数的码率控制方法
- 取值范围为0至51

**perf:**
- 用于指示是否需要测试编码器性能
- 取值范围为0或1。

**enc-params:**
- 用于设置视频编码器内部参数。
- 支持的编码参数：preset，gop_preset，qp，bitrate，mb_rc，delta_qp，min_qp，max_qp，bg，nr，deblock，weightp
- 编码参数preset：取值范围为fast, medium, slow或者是0，1，2
- 编码参数gop_preset：gop预设索引值。参考上面已有详细解释。

```
1: all I, gopsize 1
2: IPP, cyclic gopsize 1
3: IBB, cyclic gopsize 1
4: IBPBP, cyclic gopsize 2
5: IBBBP, cyclic gopsize 4
6: IPPPP, cyclic gopsize 4
7: IBBBB, cyclic gopsize 4
8: random access, IBBBBBBBB, cyclic gopsize 8
```

- 编码参数qp：恒定量化参数，取值范围为[0, 51]。当该值有效时，关闭码率控制算法，用固定的量化参数编码。
- 编码参数bitrate：用于编码所指定的码率。单位是Kbps，1Kbps=1000bps。当指定改参数时，请不要设置编码参数qp。
- 编码参数mb_rc：取值范围0或1。当设为1时，开启宏块级码率控制算法；当设为0时，开启帧级码率控制算法。
- 编码参数delta_qp：用于码率控制算法的QP最大差值。该值太大影响视频主观质量。太小影响码率调整的速度。
- 编码参数min_qp和max_qp：码率控制算法中用于控制码率和视频质量的最小量化参数和最大量化参数。取值范围[0, 51]。
- 编码参数bg：是否开启背景检测。取值范围0或1。
- 编码参数nr：是否开启降噪算法。取值范围0或1。
- 编码参数deblock：是否开启环状滤波器。有如下几种用法：
  - 关闭环状滤波器"deblock=0"或"no-deblock"。
  - 简单开启环状滤波器，使用缺省环状滤波器参数"deblock=1"。
  - 开启环状滤波器并设置参数，譬如"deblock=6,6"。
- 编码参数weightp：是否开启P帧、B帧加权预测。取值范围0或1。

**sophon_idx:** 仅适用于PCIE模式
- 用于指出要使用的Sophon设备的编号。与/dev/bm-sophon的编号一致。
- 最小值为0, 最大值为Sophon设备数量减1
- *仅适用于常规接口。*

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在PCIE模式时，值0表示输入的是系统内存虚拟地址；在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

## 硬件JPEG解码器

在BM168x系列芯片中，硬件JPEG解码器提供硬件JPEG图像解码输入能力。这里介绍一下，如何通过FFMPEG来实现硬件JPEG解码。

在FFMPEG中, 硬件JPEG解码器的名称为*jpeg_bm*。可以通过如下命令, 来查看FFMPEG中是否有*jpeg_bm*解码器。

```
$ ffmpeg -decoders | grep jpeg_bm
```

### 硬件JPEG解码器支持的选项

FFMPEG中，可以通过如下命令, 来查看*jpeg_bm*解码器支持的选项

```
$ ffmpeg -h decoder=jpeg_bm
```

解码选项的说明如下。硬件JPEG解码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**bs_buffer_size:** 用于设置硬件JPEG解码器中输入比特流的缓存大小(KBytes)。
- 取值范围(0到INT_MAX)
- 缺省值5120

**cbcr_interleave:** 用于指示JPEG解码器输出的帧数据中色度数据是否为交织的格式。
- 0: 输出的帧数据中色度数据为plannar的格式
- 1: 输出的帧数据中色度数据为interleave的格式
- 缺省值为0

**num_extra_framebuffers:** JPEG解码器需要的额外帧缓存数量
- 对于Still JPEG的输入, 建议该值设为0
- 对于Motion JPEG的输入, 建议该值至少为2
- 取值范围(0到INT_MAX)
- 缺省值为2

**sophon_idx:** 仅适用于PCIE模式。
- 用于指出要使用的Sophon设备的编号。与/dev/bm-sophon的编号一致
- 最小值为0, 最大值为Sophon设备数量减1
- *仅适用于常规接口。*

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的内存里。1，关闭拷贝；0，使能拷贝。
- 缺省值为1。
- *仅适用于旧接口的PCIE模式*。新接口提供hwdownload filter，可以显式地把数据从设备内存下载到系统内存。

## 硬件JPEG编码器

在BM168x系列芯片中，硬件JPEG编码器提供硬件JPEG图像编码输出能力。这里介绍一下，*如何通过FFMPEG来实现硬件JPEG编码*。

在FFMPEG中，硬件JPEG编码器的名称为*jpeg_bm*。可以通过如下命令，来查看FFMPEG中是否有jpeg_bm编码器。

```
$ ffmpeg -encoders | grep jpeg_bm
```

### 硬件JPEG编码器支持的选项

FFMPEG中，可以通过如下命令, 来查看jpeg_bm编码器支持的选项

```
$ ffmpeg -h encoder=jpeg_bm
```

编码选项的说明如下。硬件JPEG编码器中这些选项, 可以使用 av_dict_set() API 函数对其进行重置。

**sophon_idx:** 仅适用于PCIE模式
- 用于指出要使用的Sophon设备的编号。与/dev/bm-sophon的编号一致。
- 最小值为0, 最大值为Sophon设备数量减1
- *仅适用于常规接口。*

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在PCIE模式时，值0表示输入的是系统内存虚拟地址；在SoC模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

## 硬件scale filter

BM168x系列硬件scale filter用于将输入的图像进行"缩放/裁剪/补边"操作。譬如，转码应用。在将1080p的视频解码后，使用硬件scale缩放成720p的，再进行压缩输出。

| *内容* | *最大分辨率* | *最小分辨率* | *放大倍数* |
|--------|-------------|-------------|-----------|
| 硬件限制 | 4096 * 4096 | 8*8 | 32 |

在FFMPEG中，硬件scale filter的名称为*scale_bm*。

```
$ ffmpeg -filters | grep bm
```

### 硬件scale filter支持的选项

FFMPEG中，可以通过如下命令, 来查看scaler_bm编码器支持的选项

```
$ ffmpeg -h filter=scale_bm
```

scale_bm选项的说明如下:

**w:**
- 缩放输出视频的宽度。请参考ffmpeg scale filter的用法。

**h:**
- 缩放输出视频的高度。请参考ffmpeg scale filter的用法。

**format:**
- 缩放输出视频的像素格式。请参考ffmpeg scale filter的用法。
- 输入输出支持的格式详见附表7.1。
- 缺省值"none"。即输出像素格式为系统自动。输入为yuv420p，输出为yuv420p; 输入为yuvj420p，输出为yuvj420p。输入为nv12时，缺省输出为yuv420p。
- 在HWAccel框架下：支持nv12到yuv420p、nv12到yuvj420p、yuv420p到yuvj420p、yuvj422p到yuvj420p、yuvj422p到yuv420p的格式转换。在不启用HWAccel框架的正常模式下支持情况见附表7.1。

| 输入 | 输出 | 是否支持缩放 | 是否支持色彩转换 |
|------|------|-------------|-----------------|
| GRAY8 | GRAY8 | 是 | 是 |
| NV12（压缩） | YUV420P | 是 | 是 |
| NV12（压缩） | YUV422P | 否 | 是 |
| NV12（压缩） | YUV444P | 是 | 是 |
| NV12（压缩） | BGR | 是 | 是 |
| NV12（压缩） | RGB | 是 | 是 |
| NV12（压缩） | RGBP | 是 | 是 |
| NV12（压缩） | BGRP | 是 | 是 |
| NV12（非压缩） | YUV420P | 是 | 是 |
| NV12（非压缩） | YUV422P | 否 | 是 |
| NV12（非压缩） | YUV444P | 是 | 是 |
| NV12（非压缩） | BGR | 是 | 是 |
| NV12（非压缩） | RGB | 是 | 是 |
| NV12（非压缩） | RGBP | 是 | 是 |
| NV12（非压缩） | BGRP | 是 | 是 |
| YUV420P | YUV420P | 是 | 是 |
| YUV420P | YUV422P | 否 | 是 |
| YUV420P | YUV444P | 是 | 是 |
| YUV420P | BGR | 是 | 是 |
| YUV420P | RGB | 是 | 是 |
| YUV420P | RGBP | 是 | 是 |
| YUV420P | BGRP | 是 | 是 |
| YUV422P | YUV420P | 是 | 是 |
| YUV422P | YUV422P | 否 | 否 |
| YUV422P | YUV444P | 否 | 否 |
| YUV422P | BGR | 是 | 是 |
| YUV422P | RGB | 是 | 是 |
| YUV422P | RGBP | 是 | 是 |
| YUV422P | BGRP | 是 | 是 |
| YUV444P | YUV420P | 是 | 是 |
| YUV444P | YUV422P | 否 | 是 |
| YUV444P | YUV444P | 是 | 是 |
| YUV444P | BGR | 是 | 是 |
| YUV444P | RGB | 是 | 是 |
| YUV444P | RGBP | 是 | 是 |
| YUV444P | BGRP | 是 | 是 |
| BGR、RGB | YUV420P | 是 | 是 |
| BGR、RGB | YUV422P | 否 | 是 |
| BGR、RGB | YUV444P | 是 | 是 |
| BGR、RGB | BGR | 是 | 是 |
| BGR、RGB | RGB | 是 | 是 |
| BGR、RGB | RGBP | 是 | 是 |
| BGR、RGB | BGRP | 是 | 是 |
| RGBP、BGRP | YUV420P | 是 | 是 |
| RGBP、BGRP | YUV422P | 否 | 是 |
| RGBP、BGRP | YUV444P | 是 | 是 |
| RGBP、BGRP | BGR | 是 | 是 |
| RGBP、BGRP | RGB | 是 | 是 |
| RGBP、BGRP | RGBP | 是 | 是 |
| RGBP、BGRP | BGRP | 是 | 是 |

图7.1 scale_bm像素格式支持列表

**opt:**
- 缩放操作 (from 0 to 2) (default 0)
- 值0 - 仅支持缩放操作。缺省值。
- 值1 - 支持缩放+自动裁剪操作。命令行参数中可用crop来表示。
- 值2 - 支持缩放+自动补黑边操作。命令行参数中可用pad来表示。

**flags:**
- 缩放方法 (from 0 to 2) (default 2)
- 值0 - bilinear滤波器。命令行参数中，可用bilinear来表示。
- 值1 - nearest滤波器。命令行参数中，可用nearest来表示。
- 值2 - bicubic滤波器。命令行参数中，可用bicubic来表示。

**sophon_idx:**
- 设备ID , 从0开始。

**zero_copy:**
- 值0 - 表示scale_bm的输出AVFrame将同时包含设备内存和主机内存指针，兼容性最好，性能稍有下降。缺省为0
- 值1 - 表示scale_bm的输出到下一级的AVFrame中将只包含有效设备地址，不会对数据进行从设备内存到系统内存的同步。建议对于下一级接使用SOPHGO的编码/filter的情况，可以选择设置为1，其他建议设置为0。
- 缺省为0

## AVFrame特殊定义说明

遵从FFMPEG的规范, 硬件解码器是通过AVFrame来提供输出的，硬件编码器是通过AVFrame来提供输入的。因此，在通过API方式，调用FFMPEG SDK、进行硬件编解码处理时，需要注意到AVFrame的如下特殊规定。AVFrame是线性YUV输出。在AVFrame中，data为数据指针, 用于保存物理地址，linesize为每个平面的线跨度。

### 硬件解码器输出的avframe接口定义

#### 常规接口

**data数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址 |
| 1 | cbcr_interleave=1 时CbCr的虚拟地址; cbcr_interleave=0 时Cb的虚拟地址 |
| 2 | cbcr_interleave=0 时Cr的虚拟地址 |
| 3 | 未使用 |
| 4 | Y的物理地址 |
| 5 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 |
| 6 | cbcr_interleave=0 时Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址的跨度 |
| 1 | cbcr_interleave=1时CbCr的虚拟地址的跨度；cbcr_interleave=0时Cb的虚拟地址的跨度 |
| 2 | cbcr_interleave=0时Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 |
| 6 | cbcr_interleave=0时Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

**data数组的定义**

| **下标** | **未压缩格式说明** | **压缩格式说明** |
|----------|-------------------|-----------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 | 压缩的色度数据的物理地址 |
| 2 | cbcr_interleave=0 时Cr的物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

**linesize数组的定义**

| **下标** | **未压缩格式说明** | **压缩格式说明** |
|----------|-------------------|-----------------|
| 0 | Y的物理地址的跨度 | 亮度数据的跨度 |
| 1 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 | 色度数据的跨度 |
| 2 | cbcr_interleave=0时Cr的物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 色度偏移量表的大小 |

### 硬件编码码器输入的avframe接口定义

#### 常规接口

**data数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

#### HWAccel接口

**data数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的物理地址 |
| 1 | Cb的物理地址 |
| 2 | Cr的物理地址 |
| 3 | 保留 |
| 4 | 保留 |

**linesize数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的物理地址的跨度 |
| 1 | Cb的物理地址的跨度 |
| 2 | Cr的物理地址的跨度 |
| 3 | 未使用 |

### 硬件filter输入输出的AVFrame接口定义

1. 在不启用HWAccel加速功能时，AVFrame接口定义采用常规接口的内存布局。

**data数组的定义**

| **下标** | **说明** |
|----------|----------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

# linesize数组的定义

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

## HWAccel接口下AVFrame接口定义

### data数组的定义

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y的物理地址 压缩的 | 亮度数据的物理地址 |
| 1 | Cb物理地址 压缩 | 色度数据的物理地址 |
| 2 | Cr物理地址 亮度 | 数据的偏移量表的物理地址 |
| 3 | 保留 | 亮度数据的偏移量表的物理地址 |
| 4 | 保留 | 留 |

### linesize数组的定义

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y物理地址的跨度 亮度数据的 | 度 |
| 1 | Cb物理地址的跨度 色度数据的 | 度 |
| 2 | Cr物理地址的跨度 亮度偏移量 | 的大小 |
| 3 | 未使用 色 | 偏移量表的大小 |

# 硬件加速在FFMPEG命令中的应用示例

下面同时给出常规模式和HWAccel模式对应的FFMPEG命令行参数。

为便于理解，这里汇总说明：

- 常规模式下，bm解码器的输出内存是否同步到系统内存上，用zero_copy控制，默认为1。
- 常规模式下，bm编码器的输入内存在系统内容还是设备内存上，用is_dma_buffer控制，默认值为1。
- 常规模式下，bm滤波器会自动判断输入内存的同步，输出内存是否同步到系统内存，用zero_copy控制，默认值为0。
- HWAccel模式下，设备内存和系统内存的同步用hwupload和hwdownload来控制。
- 常规模式下，用sophon_idx来指定设备，默认为0；HWAccel模式下用hwaccel_device来指定。

## 示例 1

使用设备0。解码H.265视频，输出compressed frame buffer，scale_bm解压缩compressed frame buffer并缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale.264
```

## 示例 2

使用设备0。解码H.265视频，按比例缩放并自动裁剪成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=crop" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_crop.264
```

## 示例 3

使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

## 示例 4

演示视频截图功能。使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成jpeg图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:format=yuvj420p:zero_copy=1" \
-c:v jpeg_bm -vframes 1 \
-y wkc_100_cif_scale.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:format=yuvj420p" \
-c:v jpeg_bm -vframes 1 \
-y wkc_100_cif_scale.jpeg
```

## 示例 5

演示视频转码+视频截图功能。使用设备0。硬件解码H.265视频，缩放成CIF，然后编码成H.264码流；同时缩放成720p，然后编码成JPEG图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-filter_complex "[0:v]scale_bm=352:288:zero_copy=1[img1];[0:v]scale_bm=1280:720:format=yuvj420p:zero_copy=1[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-filter_complex "[0:v]scale_bm=352:288[img1];[0:v]scale_bm=1280:720:format=yuvj420p[img2]" \
-map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 \
-map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

## 示例6

演示hwdownload功能。硬件解码H.265视频，然后下载存储成YUV文件。

Filter hwdownload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过codec中指定zero_copy选项来实现，因此不需要hwdownload滤波器。

常规模式：

```
ffmpeg -c:v hevc_bm -cbcr_interleave 0 -zero_copy 0 \
-i src/wkc_100.265 -y test_transfer.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -cbcr_interleave 0 -i src/wkc_100.265 \
-vf "hwdownload,format=yuv420p bmcodec" \
-y test_transfer.yuv
```

## 示例7

演示hwdownload功能。硬件解码H.265视频，缩放成CIF格式，然后下载存储成YUV文件。

在常规模式中， scale_bm会自动根据filter的链条判定是否同步内存，因此不需要hwdownload。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,format=yuv420p" \
-y test_transfer_cif.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288,hwdownload,format=yuv420p bmcodec" \
-y test_transfer_cif.yuv
```

## 示例8

演示hwupload功能。使用设备0。上传YUV视频，然后编码H.264视频。

Filter hwupload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过编码器中指定is_dma_buffer选项来实现，因此不需要hwupload滤波器。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuv420p -i test_transfer.yuv \
-c:v h264_bm -b:v 3M -is_dma_buffer 0 -y test_transfer.264
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:0 \
-s 1920x1080 -i test_transfer.yuv \
-filter_hw_device foo -vf "format=yuv420p bmcodec,hwupload" \
-c:v h264_bm -b:v 3M -y test_transfer.264
```

这里foo为设备0的别名。

## 示例9

演示hwupload功能。使用设备1。上传YUV视频，并缩放成CIF，然后编码H.264视频。

常规模式：

```
ffmpeg -s 1920x1080 -i test_transfer.yuv \
-vf "scale_bm=352:288:sophon_idx=1:zero_copy=1" \
-c:v h264_bm -b:v 256K -sophon_idx 1 \
-y test_transfer_cif.264
```

说明：
1）这里不指定-pix_fmt yuv420p是因为默认输入为yuv420p格式
2）常规模式下,bm_scale filter, decoder，encoder通过参数sophon_idx来指定使用哪个设备

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 \
-s 1920x1080 -i test_transfer.yuv \
-filter_hw_device foo \
-vf "format=yuv420p bmcodec,hwupload,scale_bm=352:288" \
-c:v h264_bm -b:v 256K -y test_transfer_cif.264
```

说明：这里foo为设备1的别名，HWAccel模式下通过init_hw_device来指定使用具体的硬件设备。

## 示例10

演示hwdownload功能。硬件解码YUVJ444P的JPEG视频，然后下载存储成YUV文件。

常规模式：

```
ffmpeg -c:v jpeg_bm -zero_copy 0 -i src/car/1920x1080_yuvj444.jpg \
-y car_1080p_yuvj444_dec.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v jpeg_bm -i src/car/1920x1080_yuvj444.jpg \
-vf "hwdownload,format=yuvj444p bmcodec" \
-y car_1080p_yuvj444_dec.yuv
```

## 示例11

演示hwupload功能。使用设备1。上传YUVJ444P图像数据，然后编码JPEG图片。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-c:v jpeg_bm -sophon_idx 1 -is_dma_buffer 0 \
-y car_1080p_yuvj444_enc.jpg
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 \
-s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv \
-filter_hw_device foo -vf 'format=yuvj444p bmcodec,hwupload' \
-c:v jpeg_bm -y car_1080p_yuvj444_enc.jpg
```

这里foo为设备1的别名。

## 示例12

演示软解码和硬编码混合使用的方法。使用设备2。使用ffmpeg自带的*h264*软解码器，解码H.264视频，上传解码后数据到芯片2，然后编码H.265视频。

常规模式：

```
ffmpeg -c:v h264 -i src/1920_18MG.mp4 \
-c:v h265_bm -is_dma_buffer 0 -sophon_idx 2 -g 256 -b:v 5M \
-y test265.mp4
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:2 \
-c:v h264 -i src/1920_18MG.mp4 \
-filter_hw_device foo -vf 'format=yuv420p bmcodec,hwupload' \
-c:v h265_bm -g 256 -b:v 5M \
-y test265.mp4
```

这里foo为设备2的别名。

## 示例13

演示使用enc-params设置视频编码器的方法。使用设备0。解码H.265视频，缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:zero_copy=1" \
-c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288" \
-c:v h264_bm -g 50 -b:v 32K \
-enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" \
-y wkc_100_cif_scale_ipp_32Kbps.264
```

## 示例14

使用设备0。解码H.265视频，使用bilinear滤波器，按比例缩放成CIF，并自动补黑边，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:flags=bilinear:zero_copy=1" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 \
-c:v hevc_bm -output_format 101 -i src/wkc_100.265 \
-vf "scale_bm=352:288:opt=pad:flags=bilinear" \
-c:v h264_bm -g 256 -b:v 256K \
-y wkc_100_cif_scale_pad.264
```

# 通过调用API方式来使用硬件加速功能

examples/multimedia/ff_bmcv_transcode/例子演示了使用ffmpeg做编解码，用bmcv做图像处理的整个流程。

examples/multimedia/ff_video_decode/例子演示了使用ffmpeg做解码的流程。

examples/multimedia/ff_video_encode/例子演示了使用ffmpeg做编码的流程。

## 硬件编码支持roi编码

参考examples/multimedia/ff_video_encode/例子。设置roi_enable既可启用roi编码。

Roi编码数据通过av_frame side data传递。

Roi数据结构定义为

**字段说明:**

- **QP Map**

  H264下QP以宏块16x16为单位给出。HEVC下QP以sub-ctu（32x32）为单位给出。QP对应的就是video编码中的Qstep，取值范围为0-51。

- **Lamda Map**

  lamda是用来控制和调节IP内部的RC计算公式

  cost = distortion + lamda * rate

  这个调节参数仅在HEVC下有效，允许以32x32 sub-CTU模块为单位控制。

- **Mode Map**

  这个参数用来指定模式选择。0 – 不适用 1 – skip mode 2- intra mode。H264下以宏块16x16为单位控制，HEVC下以CTU 64x64为单位控制。

- **Zero-cut Flag**

  仅在HEVC下有效。将当前CTU 64x64残差系数全部置为0，从而节省出更多的比特给其他更重要的部分。

# SOPHGO LIBYUV使用指南

## 简介

BM168x系列芯片中的各种硬件模块，可以加速对图片和视频的处理。颜色转换方面，采用专用硬件来加速速度很快。

但在有些场合，也会存在一些专用硬件覆盖不到的特殊情况。此时采用经过SIMD加速优化的软件实现，成为专用硬件有力的补充。

SOPHGO增强版**libyuv**，是随同SDK一同发布的一个组件。目的是充分利用BM168x系列芯片提供的8核A53处理器，通过软件手段为硬件的局限性提供补充。

除了libyuv提供的标准函数之外，针对AI的需求，在SOPHGO增强版libyuv中，补充了27个扩展函数。

注意：这里说的是运行在BM168x系列的A53处理器上，而不是host的处理器。这从设备加速的角度是可以理解的。这样可以避免占用host的CPU。

## libyuv扩展说明

新增了如下增强AI应用方面的API。

### fast_memcpy

`void* fast_memcpy(void *dst, const void *src, size_t n)`

| 功能 | CPU SIMD指令实现memcpy功能。从内存区域src拷贝n个字节到内存区域dst。 |
|------|-------------------------------------------------------------------|
| 参数 | src - 内存区域 |
|      | n - 需要拷贝的字节数 |
|      | dst - 目的内存区域 |
| 返回值 | 一个指向dst的指针 |

### RGB24ToI400

`int RGB24ToI400(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, int width, int height);`

| 功能 | 一帧BGR数据转换成BT.601灰度数据 |
|------|--------------------------------|
| 参数 | src_rgb24 - packed BGR图像数据所在的内存虚地址 |
|      | src_stride_rgb24 - 内存中每行BGR图像实际跨度 |
|      | dst_y - 灰度图像虚拟地址 |
|      | dst_stride_y - 内存中每行灰度图像实际跨度 |
|      | width - 每行BGR图像数据中packed BGR的数量 |
|      | height - BGR图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### RAWToI400

`int RAWToI400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);`

| 功能 | 一帧RGB数据转换成BT.601灰度数据 |
|------|--------------------------------|
| 参数 | src_raw - packed RGB图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行RGB图像实际跨度 |
|      | dst_y - 灰度图像虚拟地址 |
|      | dst_stride_y - 内存中每行灰度图像实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束；非0，参数异常。 |

### I400ToRGB24

`int I400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);`

| 功能 | 一帧BT.601灰度数据转换成BGR数据 |
|------|--------------------------------|
| 参数 | src_y - 灰度图像虚拟地址 |
|      | src_stride_y - 内存中每行灰度图像实际跨度 |
|      | dst_rgb24 - packed BGR图像数据所在的内存虚地址 |
|      | dst_stride_rgb24 - 内存中每行BGR图像实际跨度 |
|      | width - 每行BGR图像数据中packed BGR的数量 |
|      | height - BGR图像数据的有效行数 |
| 返回值 | 0 - 正常结束；非0, 参数异常。 |

### I400ToRAW

`int I400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);`

| 功能 | 一帧BT.601灰度数据转换成RGB数据 |
|------|--------------------------------|
| 参数 | src_y - 灰度图像虚拟地址 |
|      | src_stride_y - 内存中每行灰度图像实际跨度 |
|      | dst_raw - packed RGB图像数据所在的内存虚地址 |
|      | dst_stride_raw - 内存中每行RGB图像实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### J400ToRGB24

`int J400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height);`

| 功能 | 一帧BT.601 full range灰度数据转换成BGR数据 |
|------|-------------------------------------------|
| 参数 | src_y - 灰度图像虚拟地址 |
|      | src_stride_y - 内存中每行灰度图像实际跨度 |
|      | dst_rgb24 - packed BGR图像数据所在的内存虚地址 |
|      | dst_stride_rgb24 - 内存中每行BGR图像实际跨度 |
|      | width - 每行BGR图像数据中packed BGR的数量 |
|      | height - BGR图像数据的有效行数 |
| 返回值 | 0 - 正常结束；非0, 参数异常。 |

### RAWToJ400

`int RAWToJ400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height);`

| 功能 | 一帧RGB数据转换成BT.601 full range灰度数据 |
|------|-------------------------------------------|
| 参数 | src_raw - packed RGB图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行RGB图像实际跨度 |
|      | dst_y - 灰度图像虚拟地址 |
|      | dst_stride_y - 内存中每行灰度图像实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束；非0, 参数异常。 |

### J400ToRAW

`int J400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height);`

| 功能 | 一帧BT.601 full range灰度数据转换成RGB数据 |
|------|-------------------------------------------|
| 参数 | src_y - 灰度图像虚拟地址 |
|      | src_stride_y - 内存中每行灰度图像实际跨度 |
|      | dst_raw - packed RGB图像数据所在的内存虚地址 |
|      | dst_stride_raw - 内存中每行RGB图像实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束；非0, 参数异常。 |

### RAWToNV12

`int RAWToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);`

| 功能 | 一帧RGB数据转换成BT.601 limited range的semi-plannar YCbCr 420数据 |
|------|-----------------------------------------------------------------|
| 参数 | src_raw - packed RGB图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行RGB图像实际跨度 |
|      | dst_y - Y分量的虚拟地址 |
|      | dst_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | dst_uv - CbCr分量的虚拟地址 |
|      | dst_stride_uv - 内存中每行CbCr分量数据的实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### RGB24ToNV12

`int RGB24ToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height);`

| 功能 | 一帧BGR数据转换成BT.601 limited range的semi-plannar YCbCr 420数据 |
|------|-----------------------------------------------------------------|
| 参数 | src_raw - packed BGR图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行BGR图像实际跨度 |
|      | dst_y - Y分量的虚拟地址 |
|      | dst_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | dst_uv - CbCr分量的虚拟地址 |
|      | dst_stride_uv - 内存中每行CbCr分量数据的实际跨度 |
|      | width - 每行BGR图像数据中packed BGR的数量 |
|      | height - BGR图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### RAWToJ420

`int RAWToJ420(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);`

| 功能 | 一帧RGB数据转换成BT.601 full range的YCbCr 420数据 |
|------|-------------------------------------------------|
| 参数 | src_raw - packed RGB图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行RGB图像实际跨度 |
|      | dst_y - Y分量的虚拟地址 |
|      | dst_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | dst_u - Cb分量的虚拟地址 |
|      | dst_stride_u - 内存中每行Cb分量数据的实际跨度 |
|      | dst_v - Cr分量的虚拟地址 |
|      | dst_stride_v - 内存中每行Cr分量数据的实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### J420ToRAW

`int J420ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);`

| 功能 | 一帧BT.601 full range的YCbCr 420数据转换成RGB数据 |
|------|-------------------------------------------------|
| 参数 | src_y - Y分量的虚拟地址 |
|      | src_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | src_u - Cb分量的虚拟地址 |
|      | src_stride_u - 内存中每行Cb分量数据的实际跨度 |
|      | src_v - Cr分量的虚拟地址 |
|      | src_stride_v - 内存中每行Cr分量数据的实际跨度 |
|      | dst_raw - packed RGB图像数据所在的内存虚地址 |
|      | dst_stride_raw - 内存中每行RGB图像实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### RAWToJ422

`int RAWToJ422(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);`

| 功能 | 一帧RGB数据转换成BT.601 full range的YCbCr 422数据 |
|------|-------------------------------------------------|
| 参数 | src_raw - packed RGB图像数据所在的内存虚地址 |
|      | src_stride_raw - 内存中每行RGB图像实际跨度 |
|      | dst_y - Y分量的虚拟地址 |
|      | dst_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | dst_u - Cb分量的虚拟地址 |
|      | dst_stride_u - 内存中每行Cb分量数据的实际跨度 |
|      | dst_v - Cr分量的虚拟地址 |
|      | dst_stride_v - 内存中每行Cr分量数据的实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### J422ToRAW

`int J422ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height);`

| 功能 | 一帧BT.601 full range的YCbCr 422数据转换成RGB数据 |
|------|-------------------------------------------------|
| 参数 | src_y - Y分量的虚拟地址 |
|      | src_stride_y - 内存中每行Y分量数据的实际跨度 |
|      | src_u - Cb分量的虚拟地址 |
|      | src_stride_u - 内存中每行Cb分量数据的实际跨度 |
|      | src_v - Cr分量的虚拟地址 |
|      | src_stride_v - 内存中每行Cr分量数据的实际跨度 |
|      | width - 每行RGB图像数据中packed RGB的数量 |
|      | height - RGB图像数据的有效行数 |
|      | dst_raw - packed RGB图像数据所在的内存虚地址 |
|      | dst_stride_raw - 内存中每行RGB图像实际跨度 |
| 返回值 | 0 - 正常结束; 非0, 参数异常。 |

### RGB24ToJ422

`int RGB24ToJ422(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height);`

# RGB24ToJ422

```c
int RGB24ToJ422(const uint8_t* src_rgb24, int src_stride_rgb24,
                uint8_t* dst_y, int dst_stride_y,
                uint8_t* dst_u, int dst_stride_u,
                uint8_t* dst_v, int dst_stride_v,
                int width, int height);
```

## 功能
一帧BGR数据转换成BT.601 full range的YCbCr 422数据

## 参数
| 参数 | 说明 |
|------|------|
| src_rgb24 | packed BGR图像数据所在的内存虚地址 |
| src_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# J422ToRGB24

```c
int J422ToRGB24(const uint8_t* src_y, int src_stride_y,
                const uint8_t* src_u, int src_stride_u,
                const uint8_t* src_v, int src_stride_v,
                uint8_t* dst_rgb24, int dst_stride_rgb24,
                int width, int height);
```

## 功能
一帧BT.601 full range的YCbCr 422数据转换成BGR数据

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行图像实际跨度 |
| width | 每行图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# RAWToJ444

```c
int RAWToJ444(const uint8_t* src_raw, int src_stride_raw,
              uint8_t* dst_y, int dst_stride_y,
              uint8_t* dst_u, int dst_stride_u,
              uint8_t* dst_v, int dst_stride_v,
              int width, int height);
```

## 功能
一帧RGB数据转换成BT.601 full range的YCbCr 444数据

## 参数
| 参数 | 说明 |
|------|------|
| src_raw | packed RGB图像数据所在的内存虚地址 |
| src_stride_raw | 内存中每行RGB图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# J444ToRAW

```c
int J444ToRAW(const uint8_t* src_y, int src_stride_y,
              const uint8_t* src_u, int src_stride_u,
              const uint8_t* src_v, int src_stride_v,
              uint8_t* dst_raw, int dst_stride_raw,
              int width, int height);
```

## 功能
一帧BT.601 full range的YCbCr 444数据转换成RGB数据

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_raw | packed RGB图像数据所在的内存虚地址 |
| dst_stride_raw | 内存中每行RGB图像实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# RGB24ToJ444

```c
int RGB24ToJ444(const uint8_t* src_rgb24, int src_stride_rgb24,
                uint8_t* dst_y, int dst_stride_y,
                uint8_t* dst_u, int dst_stride_u,
                uint8_t* dst_v, int dst_stride_v,
                int width, int height);
```

## 功能
一帧BGR数据转换成BT.601 full range的YCbCr 444数据

## 参数
| 参数 | 说明 |
|------|------|
| src_rgb24 | packed BGR图像数据所在的内存虚地址 |
| src_stride_rgb24 | 内存中每行BGR图像实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# J444ToRGB24

```c
int J444ToRGB24(const uint8_t* src_y, int src_stride_y,
                const uint8_t* src_u, int src_stride_u,
                const uint8_t* src_v, int src_stride_v,
                uint8_t* dst_rgb24, int dst_stride_rgb24,
                int width, int height);
```

## 功能
一帧BT.601 full range的YCbCr 444数据转换成BGR数据

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_rgb24 | packed BGR图像数据所在的内存虚地址 |
| dst_stride_rgb24 | 内存中每行图像实际跨度 |
| width | 每行图像数据中packed BGR的数量 |
| height | BGR图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# H420ToJ420

```c
int H420ToJ420(const uint8_t* src_y, int src_stride_y,
               const uint8_t* src_u, int src_stride_u,
               const uint8_t* src_v, int src_stride_v,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height);
```

## 功能
一帧BT.709 limited range的YCbCr 420数据转换成BT.601 full range的。可以在jpeg编码之前，作预处理函数用。

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# I420ToJ420

```c
int I420ToJ420(const uint8_t* src_y, int src_stride_y,
               const uint8_t* src_u, int src_stride_u,
               const uint8_t* src_v, int src_stride_v,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height);
```

## 功能
一帧BT.601 limited range的YCbCr 420数据转换成BT.601 full range的。可以在jpeg编码之前，作预处理函数用。

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_u | Cb分量的虚拟地址 |
| src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| src_v | Cr分量的虚拟地址 |
| src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# NV12ToJ420

```c
int NV12ToJ420(const uint8_t* src_y, int src_stride_y,
               const uint8_t* src_uv, int src_stride_uv,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height);
```

## 功能
一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的plannar YCbCr 420数据。可以在jpeg编码之前，作预处理函数用。

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_uv | CbCr分量的虚拟地址 |
| src_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# NV21ToJ420

```c
int NV21ToJ420(const uint8_t* src_y, int src_stride_y,
               const uint8_t* src_vu, int src_stride_vu,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height);
```

## 功能
一帧BT.601 limited range的semi-plannar YCbCr 420数据转换成BT.601 full range的。可以在jpeg编码之前，作预处理函数用。

## 参数
| 参数 | 说明 |
|------|------|
| src_y | Y分量的虚拟地址 |
| src_stride_y | 内存中每行Y分量数据的实际跨度 |
| src_vu | CrCb分量的虚拟地址 |
| src_stride_vu | 内存中每行CrCb分量数据的实际跨度 |
| dst_y | Y分量的虚拟地址 |
| dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| dst_u | Cb分量的虚拟地址 |
| dst_stride_u | 内存中每行Cb分量数据的实际跨度 |
| dst_v | Cr分量的虚拟地址 |
| dst_stride_v | 内存中每行Cr分量数据的实际跨度 |
| width | 每行RGB图像数据中packed RGB的数量 |
| height | RGB图像数据的有效行数 |

## 返回值
0: 正常结束; 非0: 参数异常。

# I444ToNV12

```c
int I444ToNV12(const uint8_t* src_y, int src_stride_y,
  const uint8_t* src_u, int src_stride_u,
  const uint8_t* src_v, int src_stride_v,
  uint8_t* dst_y, int dst_stride_y,
  uint8_t* dst_uv, int dst_stride_uv,
  int width, int height);
```

| 功能 | 一帧YCbCr 444图像数据转换成semi-plannar YCbCr 420数据可用于full range，也可以用于limited range的。不涉及颜色空间转换，可灵活使用。 |
|------|---------------------------------------------------------------------------------------------------------------------------------|
| 参数 | rc_y | 图像Y分量的虚拟地址 |
| 参数 | src_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | src_u | 源图像Cb分量的虚拟地址 |
| 参数 | src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| 参数 | src_v | 源图像Cr分量的虚拟地址 |
| 参数 | src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| 参数 | dst_y | 目的图像Y分量的虚拟地址 |
| 参数 | dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | dst_uv | 目的图像CbCr分量的虚拟地址 |
| 参数 | dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| 参数 | width | 每行图像数据中像素的数量 |
| 参数 | height | 图像数据像素的有效行数 |
| 返回值 | 0正常结束；非0，参数异常。 |

# I422ToNV12

```c
int I422ToNV12(const uint8_t* src_y, int src_stride_y,
  const uint8_t* src_u, int src_stride_u,
  const uint8_t* src_v, int src_stride_v,
  uint8_t* dst_y, int dst_stride_y,
  uint8_t* dst_uv, int dst_stride_uv,
  int width, int height);
```

| 功能 | 一帧YCbCr 422图像数据转换成semi-plannar YCbCr 420数据可用于full range，也可以用于limited range的。不涉及颜色空间转换，可灵活使用。 |
|------|---------------------------------------------------------------------------------------------------------------------------------|
| 参数 | rc_y | 图像Y分量的虚拟地址 |
| 参数 | src_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | src_u | 源图像Cb分量的虚拟地址 |
| 参数 | src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| 参数 | src_v | 源图像Cr分量的虚拟地址 |
| 参数 | src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| 参数 | dst_y | 目的图像Y分量的虚拟地址 |
| 参数 | dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | dst_uv | 目的图像CbCr分量的虚拟地址 |
| 参数 | dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| 参数 | width | 每行图像数据中像素的数量 |
| 参数 | height | 图像数据像素的有效行数 |
| 返回值 | 0正常结束；非0，参数异常。 |

# I400ToNV12

```c
int I400ToNV12(const uint8_t* src_y, int src_stride_y,
  const uint8_t* src_u, int src_stride_u,
  const uint8_t* src_v, int src_stride_v,
  uint8_t* dst_y, int dst_stride_y,
  uint8_t* dst_uv, int dst_stride_uv,
  int width, int height);
```

| 功能 | 一帧YCbCr 400图像数据转换成semi-plannar YCbCr 420数据可用于full range，也可以用于limited range的。不涉及颜色空间转换，可灵活使用。 |
|------|---------------------------------------------------------------------------------------------------------------------------------|
| 参数 | rc_y | 图像Y分量的虚拟地址 |
| 参数 | src_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | src_u | 源图像Cb分量的虚拟地址 |
| 参数 | src_stride_u | 内存中每行Cb分量数据的实际跨度 |
| 参数 | src_v | 源图像Cr分量的虚拟地址 |
| 参数 | src_stride_v | 内存中每行Cr分量数据的实际跨度 |
| 参数 | dst_y | 目的图像Y分量的虚拟地址 |
| 参数 | dst_stride_y | 内存中每行Y分量数据的实际跨度 |
| 参数 | dst_uv | 目的图像CbCr分量的虚拟地址 |
| 参数 | dst_stride_uv | 内存中每行CbCr分量数据的实际跨度 |
| 参数 | width | 每行图像数据中像素的数量 |
| 参数 | height | 图像数据像素的有效行数 |
| 返回值 | 0正常结束；非0，参数异常。 |