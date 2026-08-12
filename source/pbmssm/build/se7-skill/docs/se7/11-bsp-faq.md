---
title: BSP FAQ
description: BSP常见问题
tableOfContents:
  maxHeadingLevel: 3
sidebar:
  hidden: true
---

## 刷机相关问题

### 刷机包在哪里

刷机包在算能官网"服务与支持" -> "开发资料"中。与SDK开发资料一并打包。下载SDK压缩包并解压后，可以在`sophon-img_xxxxxxxx_xxxxxx/`目录下找到名为`sdcard.tgz`的文件，这个文件就是TF卡刷用的刷机包

### 如何使用TF卡进行刷机

* 准备一张TF卡，推荐品牌：闪迪
* 将TF卡设置为MBR分区表，创建一个主分区并格式化为FAT32。卡上需要有且仅有这一个FAT32分区。
* 将需要刷入的刷机包解压，拷贝到卡的根目录下，确保卡根目录可以看到BOOT等文件
* 将SE7断电，把卡插入
* 上电，等待。此时可以通过如下几个方式获取刷机情况（不同型号的SE7刷机状态表示可能不同）
* * SE7外观的LED灯，等待绿色灯稳定闪烁
* * SE7有type-c接口，这个是一个USB串口(uart)。可以连接电脑，配置波特率115200后，查看刷机日志。等待串口打印`Please remove the installation medium`
* 下电，拔卡，再次上电。bm_version可以查看版本信息

### 如何制作一张MBR+FAT32格式的TF卡

* 下载压缩包[sdcard_imgs.zip](https://sophon-file.sophon.cn/sophon-prod-s3/drive/23/11/09/18/sdcard_imgs.zip)，并解压。
* 根据刷机包大小选择合适`img.gz`文件。比如官网刷机包通常1G左右，选择`sdcard.3G.img.gz`。
* 使用[balenaEtcher](https://etcher.balena.io/)将选择的`img.gz`文件写入TF卡

## 系统日常使用

### 默认账户信息

* 默认账户有两个linaro:linaro，admin:admin。推荐使用linaro账户。
* root账户默认没有密码，不可登陆。可以使用`sudo su`命令切换到root账户。

### /data分区所有权复位问题

/data分区在设备每次开机都会自动设置为linaro账户所有。该自动配置在`/usr/sbin/bmrt_setup.sh`文件中实现，可以通过修改该文件来改变默认行为。

### 如何查看系统日志

* 设备systemd日志可以通过`journalctl`命令查看
* 设备内核日志可以通过文件`/var/log/kern.log`查看
* 设备完整日志可以通过文件`/var/log/syslog`查看

### 如何查看CPU、内存等系统资源使用情况

* 访问该[网页](https://github.com/sophgo/sophon-tools/tree/main/source/pget_info)获取系统资源使用情况的工具和使用说明

### 如何建立最小包含sophon runtime的docker镜像

* 创建一个新的Dockerfile，内容如下：

```Dockerfile
# Build linux kernel general dockerfile configuration file
FROM ubuntu:20.04

# Add apt sources
RUN cp -a /etc/apt/sources.list /etc/apt/sources.list.bak
RUN sed -i "s@//ports.ubuntu.com@//mirrors.ustc.edu.cn@g" /etc/apt/sources.list \
&& sed -i 's@//.*archive.ubuntu.com@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list

# add apt software
RUN export DEBIAN_FRONTEND=noninteractive \
&& apt-get update \
&& apt-get upgrade -y \
&& apt-get install -y --no-install-recommends \
procps locales libncurses5 \
&& apt-get autoclean

ENV PYTHONPATH "$PYTHONPATH:/opt/sophon/libsophon-current/lib:/opt/sophon/sophon-opencv-latest/opencv-python/"

# Set the locale
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
```

* 运行命令`docker build -t sophonrun:v1  .​​​` 命令进行image的编译
* 下面的两条启动容器命令二选一，适用于不同的场景
* * 赋予docker主机root权限的启动命令：
```bash
sudo docker run \
-td \
--privileged=true \
-v /opt/sophon:/opt/sophon \
-v /dev:/dev \
-v /etc/profile.d:/etc/profile.d \
-v /etc/profile:/etc/profile \
-v /etc/ld.so.conf.d:/etc/ld.so.conf.d \
--name sophonrun_container sophonrun:v1 /bin/bash
```
* * 不能赋予docker主机root权限的情况
```bash
sudo docker run \
-td \
$(find /dev -name 'bm*' 2>/dev/null -exec echo -n " --device={} " \;) \
$(find /dev -name 'bm-sophon*' 2>/dev/null | grep -q . || echo -n " --device=/dev/ion ") \
-v /opt/sophon:/opt/sophon \
-v /etc/profile.d:/etc/profile.d \
-v /etc/profile:/etc/profile \
-v /etc/ld.so.conf.d:/etc/ld.so.conf.d \
--name sophonrun_container sophonrun:v1 /bin/bash
```
* 进入容器并使能算能SDK环境
``` bash
docker exec -it sophonrun_container bash
ldconfig
source /etc/profile
```
* 导出导入镜像命令
``` bash
docker save sophonrun:v1 | pv | gzip > sophonrun-v1.tar.gz
docker load -i sophonrun-v1.tar.gz
```

### 如何配置一个自定义的开机自启动服务

* 新建文件/etc/systemd/system/user-auto-start.service，内容如下：
```ini
[Unit]
Description=user auto setup
After=network.target bmrt_setup.service

[Service]
User=root
ExecStart=/data/user_auto_setup.sh
Type=simple
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```
* * 配置文件内容解析：
* * * 描述：user auto setup
* * * 启动时间：在network.target和bmrt_setup.service之后，在multi-user.target之前
* * * 命令执行账户：root
* * * 命令：/data/user_auto_setup.sh
* * * 服务类型：simple
* * * 是否自动重启：是，仅在命令执行失败10s后重启
* 配置执行脚本（本文为/data/user_auto_setup.sh），切记需要赋予其运行权限
* 执行命令`sudo systemctl daemon-reload​​​`​重载配置文件
* 执行命令`sudo systemctl status user-auto-start.service`​​​​查看该服务是否配置完成
* 执行命令`sudo systemctl enable user-auto-start.service​​​`​使能其开机自启

> 注意事项：
> * 默认运行的log会存放在/var/log/syslog文件中
> * 该示例只适用于简单的业务，复杂的环境配置等需要参考systemd的说明文档
> * 该示例的服务类型是simple，切记不要在脚本中使其自动放置后台执行，这会导致systemd无法监控前台任务导致直接杀死进程
> * 可以使用命令`sudo systemd-analyze plot > plot.svg`​​生成本次启动的服务清单（svg格式）用于分析服务的启动时间和运行时间

### 如何启动到维护模式

* 制作一张MBA+FAT32的TF卡，步骤同前文"如何制作一张MBR+FAT32格式的TF卡"部分
* 下载[紧急启动包](https://developer-assets.sophon.cn/sophon-developer-prod-s3/thread-attachment/25/07/15/16/sdbootrecoveryfiles.txz)并解压
* 将解压后的文件拷贝到TF卡根目录下，确保卡根目录可以看到`boot.scr`等文件
* 将SE7断电，把卡插入，上电启动，等到指示灯快速闪烁时，成功启动（大部分情况下可以让指示灯闪烁，如果启动后2分钟没有闪烁可以尝试按照下文的信息进行连接）
* 连接方法：
* * SE7有type-c接口，这个是一个USB串口。可以连接电脑，配置波特率115200后，便可以登陆到紧急启动的系统中。默认账户是root，密码为roskty70TT。
* * 对外IP：eth0 192.168.140.1（推荐使用这个网口），eth1 192.168.150.1。可以使用网线直连，然后使用ssh工具登陆。
* 启动后是一个基于busybox的精简linux系统。支持ssh和scp。大部分情况支持usb挂载，用于备份数据与紧急恢复数据（一定程度上替换串口进入恢复模式）

### emmc寿命查询

* 命令cat class/mmc_host/mmc0/mmc0:0001/life_time​​获取寿命信息
* * 两个都代表寿命，0x01 - 0x0a 代表磨损10%-100%，有一个满了就代表emmc寿命不足。
* 命令cat class/mmc_host/mmc0/mmc0:0001/pre_eol_info​​获取保留块信息
* * 表示emmc保留块的消耗程度，信息如下：
* * * 0x01代表正常
* * * 0x02代表消耗了80%的保留块
* * * 0x03代表消耗了90%的保留块

### 如何判断重启原因

* 进入目录`/root/.boot/`，查看里面的文件。每次启动时系统会将上次关机的原因记录在这里。
* 使用xxd命令查看里面文件的内容。
* * 0x00 代表设备突然断电，没有记录关机原因
* * 0x80 代表执行`power off`关机
* * 0x81 代表RESET重启
* * 0x82 代表执行`reboot`重启
* * 0x83 代表超温关机
* * 0x84 代表watchdog重启
* * 0x85 代表MCU超温关机

### SE7 32-EA4-23如何使用wifi

* 环境检查：
* *  检查型号是否为32-EA4-23，其他型号不支持wifi
* * 通过SSH登录至设备，检查nmcli工具是否已安装；如果提示`nmcli: command not found`，则工具未安装；需要使用`sudo apt install network-manager`指令进行安装
* * 检查wlan设备是否被正确识别；使用指令`ifconfig`查看已激活的网卡信息，观察是否有wlan0存在，如未观察到wlan0，则网卡暂未激活；使用指令`ifconfig -a`查看全部网卡信息，观察是否有wlan0存在，如未观察到wlan0，则需要安装驱动
* * 安装驱动：下载[驱动安装包](https://developer-assets.sophon.cn/sophon-developer-prod-s3/thread-attachment/26/01/28/11/se7_wifi_rtl8822xu_rtl8811cu_rtl8821cu_v260127.txz)，在设备上解压后执行`sudo ./install.sh`进行安装。安装完成后重启设备，使用指令`ifconfig`查看已激活的网卡信息，观察是否有wlan0存在，如有wlan0则安装成功。
* WiFi链接
* * 使能WiFi：`nmcli radio wifi on`
* * 查看WiFi是否使能成功：`nmcli radio wifi`，如果显示`enabled`则表示WiFi已成功使能
* * 扫描WiFi：`nmcli device wifi list`，查看周围的WiFi列表，找到需要连接的WiFi名称（SSID）
* * 连接WiFi：`nmcli device wifi connect <SSID> password <password>`，将`<SSID>`替换为需要连接的WiFi名称，`<password>`替换为WiFi密码，执行后等待连接成功的提示
* * 查看连接状态：`nmcli connection show --active`，查看当前已连接的网络信息，确认是否成功连接到目标WiFi
* * 断开WiFi连接：`nmcli connection down <SSID>`，将`<SSID>`替换为已连接的WiFi名称，执行后等待断开成功的提示
* * 关闭WiFi：`nmcli radio wifi off`
* 配置热点
* * 使用nmcli指令配置WiFi热点：`sudo nmcli device wifi hotspot ifname wlan0 con-name MyHostspot ssid MyHostspotSSID band bg channel 11 password 12345678`
* * 参数解析：
* * * con-name：连接名称，这里设置为MyHostspot；
* * * ssid：AP热点名称，这里设置为MyHostspotSSID；
* * * band：WiFi的协议标准，这里使用bg；
* * * channel：AP热点通道，这里定义为11；
* * * password：AP热点密码，这里定义为12345678；
* * 在创建了AP热点后，可以使用以下指令控制WiFi热点打开/关闭：
* * * `sudo nmcli connection up MyHostspot`：打开WiFi热点；
* * * `sudo nmcli connection down MyHostspot`：关闭WiFi热点；
* * 查看已建立热点链接：`sudo nmcli connection show`
* * 删除热点链接：`sudo nmcli connection delete MyHostspot`
* * 查看当前热点账密：`nmcli dev wifi show-password`

### 系统根目录满了怎么办

需要使用du工具进行排查，SE7的/boot、/recovery、/ota、/data分区均不在根目录下，排查时这些部分可以忽略，如下为参考方案：
* 进入目录 `/home`
* 执行 `sudo du -sh ./*` 查看每个文件夹占用空间大小
* 进入占用空间较大的文件夹，继续执行 `sudo du -sh ./*` 进行排查，找到占用空间较大的文件
* 如果确认该文件不需要了，可以执行 `sudo rm -rf <file>` 删除该文件，释放空间
* 进入目录 `/var/log`
* 执行 `sudo du -sh ./*` 查看每个文件夹占用空间大小
* 进入占用空间较大的文件夹，继续执行 `sudo du -sh ./*` 进行排查，找到占用空间较大的文件
* 如果确认该文件不需要了，可以执行 `sudo rm -rf <file>` 删除该文件，释放空间

### 系统根目录只读了怎么办

由于SE7的根目录采用了overlay的方案，而overlay的上层满了之后，根目录会变为只读模式。可以通过以下步骤进行排查和清理：
* 进入目录 `/media/root-rw/overlay`
* 执行 `sudo du -sh ./*` 查看每个文件夹占用空间大小
* 进入占用空间较大的文件夹，继续执行 `sudo du -sh ./*` 进行排查，找到占用空间较大的文件
* 如果确认该文件不需要了，可以执行 `sudo rm -rf <file>` 删除该文件，释放空间
* 推荐只删除出300M左右的文件，删除后执行`sync`命令然后重启设备。

### 设备开不开机了怎么办

* 检查电源是否使用的原装电源
* 检查电源接口是否接触良好，是否插牢
* 检查电源指示灯是否亮起
* 检查HDMI是否有输出（使用HDMI to HDMI直连支持HDMI的显示器）
* 尝试使用网线直连设备的LAN口或者2号网口，配置电脑IP地址为192.168.150.2，此时设备IP为192.168.150.1，尝试SSH登陆
* 检查type-c接口的串口，并将盒子重新上电，查看是否有输出（波特率115200）
* 如果以上方法都不行，可以尝试使用TF卡进入[维护模式](#如何启动到维护模式)，查看是否能成功进入紧急启动系统（如果能进入紧急启动系统，说明设备硬件没有问题，可能是系统问题）

### 设备开机后HDMI没有输出怎么办

* 检查HDMI线是否接触良好，是否插牢
* 使用支持HDMI的屏幕，不要使用HDMI转VGA等转接设备
* 尝试更换HDMI线
* 尝试更换显示器
* 更新系统到最新版本

### SSH无法登陆怎么办

* 检查设备是否开机
* 检查设备IP地址是否正确
* 检查SSH密码是否正确
* 尝试其他账户进行登录，设备默认有linaro和admin两个账户，密码分别是linaro和admin
* 尝试ping设备IP地址，如果可以ping通，说明网络没有问题
* 使用串口登陆设备，如果串口可以登陆，并可以执行命令，free -h检查内存使用情况，如果内存使用率过高，可能会导致SSH无法登陆
* 如果串口也无法登陆，可能是系统问题，可以尝试使用TF卡进入[维护模式](#如何启动到维护模式)，查看是否能成功进入紧急启动系统（如果能进入紧急启动系统，说明设备硬件没有问题，可能是系统问题）

### 如何修改网络

* 使用`bm_set_ip`修改设备网络
* 如果有高级自定义内容，ubuntu版本修改`/etc/netplan/`目录下的配置文件；kylin版本通过nmcli和nmtui工具修改网络

### 设备断电后时间会错误怎么办

* 使用`sudo hwclock -l`命令查看设备的RTC芯片是否正常工作
* 如果RTC芯片正常工作，修正系统时间后，使用`sudo hwclock -w`命令将系统时间写入RTC芯片中
* 如果RTC芯片不正常工作，可能是电池没电了

### hwclock -l报错"hwclock: ioctl(RTC_RD_TIME) to /dev/rtc0 to read the time failed: Invalid argument"

* 该问题可能是由于设备的RTC芯片中的时间设置过早导致的，可以通过以下步骤进行解决：
* 使用`sudo timedatectl set-time '2015-11-20 16:10:40'`命令将系统时间设置为正确的时间
* 使用`sudo hwclock -w`命令将系统时间写入RTC芯片中
* 之后再次使用`sudo hwclock -l`命令查看RTC芯片中的时间，应该可以正常显示了

### 如何控制看门狗

基于BM1684芯片的产品在板上都会有一颗STM32 MCU，它的主要任务是给BM1684芯片上下电，然后顺便承担了其他一些功能，比如这里要介绍的看门狗。BM1684和STM32之间有一条I2C总线连接，BM1684做master，STM32做slave，BM1684通过发送I2C消息来做踢狗的动作。BM1684在每个CPU核上绑定一个线程，只有当所有线程都活着时才会周期性踢狗，即任何一个CPU核挂死都会引起看门狗超时，STM32会复位BM1684。可以通过如下命令来控制这个看门狗：

| 命令 | 说明 |
|------|------|
| `echo 'enable' > /dev/bm-wdt-0` | 启用看门狗功能 |
| `echo 'disable' > /dev/bm-wdt-0` | 禁用看门狗功能 |
| `echo 'auto' > /dev/bm-wdt-0` | 启动内核线程自动周期性踢狗的动作 |
| `echo 'manual' > /dev/bm-wdt-0` | 关闭内核线程自动周期性踢狗的动作 |
| `echo 'kick' > /dev/bm-wdt-0` | 手动触发一次踢狗 |
| `echo 'timeout 30' > /dev/bm-wdt-0` | 设置看门狗超时时间，超过这个时间没有收到踢狗消息，看门狗就复位BM1684 |
| `echo 'interval 20' > /dev/bm-wdt-0` | 设置内核线程自动踢狗的周期 |

### SE7 32-BP1-11/12 5G模组FM650识别不到问题

* 检查5G模组是否插牢
* 使用5G模组前执行 `i2cset -y -f 1 0x6c 0x03 0x08` 命令打开5G模组电源（root权限下）
* 等待30s，使用 `lsusb` 命令检查是否识别到5G模组

> 如果拨号工具使用 [autotelecomm](https://github.com/sophgo/sophon-tools/tree/main/source/pautotelecomm)，可以将该命令写到 `/usr/sbin/bmrt_setup.sh` 文件末尾。工具`autotelecomm`识别到USB设备后会自动触发启动

### 5G模组FM650未识别到串口ttyUSB问题

* 使用 `lsusb` 命令检查是否识别到5G模组
* 执行命令 `echo "2cb7 0a04" > /sys/bus/usb-serial/drivers/option1/new_id`，其中 `"2cb7 0a04"` 替换为lsusb看到的5G模组USB ID，例如 `"2cb7 0a05"`
