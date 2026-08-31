---
title: BSP FAQ
description: BSP常见问题
tableOfContents:
  maxHeadingLevel: 3
sidebar:
  hidden: true
---

## 目录

1 声明

2 前言
2.1 文档概述
2.2 读者对象
2.3 约定的符号、标志、专用语解释
2.4 声明

3 外设常见问题
3.1 iic-常见问题
3.1.1 客户量不到波形，客户读不到数据
3.1.2 i2ctool 工具使用方法
3.1.3 波形示例
3.1.4 I2C 子节点实现
3.1.5 模拟 I2C 实现
3.2 pwm-常见问题
3.2.1 PWM 引脚无波形输出
3.3 uart-常见问题
3.3.1 SM9&SE9 设备串口无打印
3.3.2 收发不到数据常见调试方式
3.4 spi-常见问题
3.4.1 SPI CS 管脚控制问题
3.5 can-常见问题
3.5.1 CAN_ID 混乱
3.5.2 高速传输时出现帧混乱
3.5.3 sata-常见问题
3.5.4 sata-phy 硬件检查
3.6 spacc-常见问题
3.6.1 spacc 驱动的使用
3.6.2 对称加解密算法运算结果有问题
3.7 eth-网络常见问题
3.7.1 ethtool 使用
3.7.2 phytool 使用
3.7.3 iperf3 使用
3.7.4 bm_set_ip 使用
3.7.5 ping 域名不通
3.7.6 修改 mtu 大小报错
3.7.7 客户验证网桥功能时遇到问题
3.7.8 小数据包吞吐量不足导致丢包
3.7.9 SE9 不支持并行检测
3.8 usb-常见问题
3.8.1 切换 usb 的角色
3.8.2 usb device 配置为指定功能
3.8.3 device 作为存储设备的操作指南
3.8.4 Device 作为 RNDIS 设备的操作指南
3.8.5 Device 作为 UVC 设备的操作指南
3.8.6 报错原因分析
3.9 pcie-常见问题
3.9.1 rc 问题
3.9.2 EP 问题
3.10 nvme-常见问题
3.11 sd-常见问题
3.11.1 sd-uhs 模式切换问题
3.12 内置 mcu-常见问题
3.12.1 mcu-启动流程
3.12.2 mcu 的代码设计
3.13 gpio 和 pinmux-常见问题
3.13.1 选择 GPIO 方法
3.13.2 write error: Device or resource busy
3.13.3 uboot 下怎么使用 gpio
3.14 代码操作 GPIO
3.14.1 pinmux 怎么查看表格，查看寄存器
3.15 RS485-常见问题
3.15.1 RS485 通信异常问题
3.16 wifi&bt-常见问题
3.17 4/5G-常见问题
3.17.1 故障排查常用 AT 命令
3.17.2 无法识别 SIM 卡
3.17.3 4G/5G 模组不支持 SIM 卡热拔插
3.17.4 专网拨号
3.17.5 双模组支持
3.18 watchdog-常见问题
3.18.1 看门狗驱动编译开启
3.19 Athena2 watchdog 开启时间
3.19.1 如何喂狗
3.19.2 如何关闭看门狗
3.20 固件升级常见问题
3.20.1 通过 SD 卡升级失败：
3.20.2 通过 OTA 升级失败：
3.20.3 USB 升级常见问题
TPU 常见问题
4.1 常用命令介绍
4.2 tpu hang 常见问题
4.3 bm-smi 常见问题
5 内存常见问题
5.1 内存大小
5.2 内存调整
5.3 ION 查看
6 休眠唤醒常见问题
7 recovery 常见问题
7.1 进入 recovery
7.2 recovery 模式问题排查
8 OEM 常见问题
9 OS 常见问题汇总
9.1 目前 1688&CV186AH 支持的 OS 如下所示
9.2 算能麒麟二次开发定制指南
9.3 麒麟版本
9.4 定制 ftp.bin
9.5 定制内核 kernel
9.6 导出二次开发麒麟包

## 声明

# SOPHON

### 法律声明

版权所有 © 算能 2022. 保留一切权利。

非经本公司书面许可，任何单位和个人不得擅自摘抄、复制本文档内容的部分或全部，并不得以任何形式传播。

### 注意

您购买的产品、服务或特性等应受算能商业合同和条款的约束，本文档中描述的全部或部分产品、服务或特性可能不在您的购买或使用范围之内。除非合同另有约定，算能对本文档内容不做任何明示或默示的声明或保证。由于产品版本升级或其他原因，本文档内容会不定期进行更新。除非另有约定，本文档仅作为使用指导，本文档中的所有陈述、信息和建议不构成任何明示或暗示的担保。

## 技术支持

地址

北京市海淀区丰豪东路9号院中关村集成电路设计园（ICPARK）1号楼

邮编

100094

网址

https://www.sophgo.com/

邮箱

sales@sophgo.com

电话

+86-10-57590723 +86-10-57590724

## 前言

### 2.1 文档概述

本文档详细介绍了 BM1688 系列 AI 计算模组（含开发板）的外观特点、应用场景、设备参数、电气特性、配套软件、使用环境等，使得该设备的用户及开发者对 BM1688 系列 AI 计算模组（含开发板）有比较全面深入的了解。设备用户及开发者可依据此手册，开展对该设备的安装、调试、部署、维护等一系列工作。

### 2.2 读者对象

本文档主要适用于如下人员：

算丰 FAE 工程师、售前工程师

生态合作伙伴的开发人员

- 用户企业研发工程师、售前工程师

### 2.3 约定的符号、标志、专用语解释

在本文中可能出现如下符号、标志，它们所代表的含义如下：

表 2.1: 符号、标志、专用语解释

| | | |
| --- | --- | --- |
| 危险 | 表示有高度危险，如果不能避免，可能导致人员伤亡或严重伤害 |
| 警告 | 表示有中度或低度潜在危险，如果不能避免，可能导致人员轻微或中等伤害 |
| 注意 | 表示有潜在风险，如果忽视这部分文本，可能导致设备损坏、数据丢失、设备性能降低或不可预知的结果 |
| A | 防静电 | 防静电标识，表示静电敏感的设备或操作 |
| A | 当心触电 | 电击防护标识，标识高压危险，需做好防护 |
| A | 窍门 | 表示能帮助您解决某个问题或节省您的时间 |
| A | 说明 | 表示是正文的附加信息，是对正文的强调和补充 |

表 2.2: 缩略语表

| 缩写 | 英文全称 | 中文释义 |
| --- | --- | --- |
| TPU | Tensor Processing Unit | 张量处理单元 |
| OEM | Original Equipment Manufacturer | 原始设备制造商 |
| ION | Input/Output Navigator | 输入输出导航器 |

表 2.3: 修改记录

| 文档版本 | 发布日期 | 修订说明 | 对应硬件版本 | 对应软件版本 |
| --- | --- | --- | --- | --- |
| V0.1 | 2025-6-25 | 首次正式发布 | BM1688 EVB:V1.5 | v2.0 |

### 2.4 声明

Copyright © 2022 北京算能科技有限公司。

我们对本产品手册及其中的内容具有全部的知识产权。除非特别授权，禁止复制或向第三方分发。凡侵犯本公司版权等知识产权权益的行为，本公司保留依法追究其法律责任的权利。

本产品系列将有不断地更新迭代，我们将定期检查本产品手册中的内容，在后续的版本中将出现不可避免的修正、删减、补充。

我们保留在不事先通知的情况下进行技术改进、文档变更、产品改进升级、增加或减少产品型号和功能的权利。

## 外设常见问题

### 3.1 iic-常见问题

#### 3.1.1 客户量不到波形，客户读不到数据

a. 未 pinmux，会在 i2c detect 或者通信时出现 i2c_designware 4000000.i2c: controller timed out。

b. pinux 方法：cvi_pinux -w &lt;function&gt;/&lt;target&gt;

c. 被外部拉低，lost arbitration（也有可能是硬件问题）。

d. 把从设备都去掉，量 SDA，SCL 电压是否为高，或者直接测波形

e. iic 能 detect 到设备地址，但是读写寄存器信息都失败（读数据返回都是 0）

f. iic 控制器没问题，大概率是从设备时序不匹配，检查硬件

#### 3.1.2 i2ctool 工具使用方法

以下是在 Linux 终端中使用 i2c-tools 工具进行总线检测和设备读写的常用命令：

a. 检测 I2C 总线 i2cdetect -l # 列出系统中的 I2C 总线（cv184x 平台常见总线：i2c-0 至 i2c-4）

b. 扫描总线设备 i2cdetect -y -r N # 扫描 i2c-N 总线上的设备地址

c. 寄存器批量读取 i2cdump -f -y N M # 读取 i2c-N 总线地址 M 设备的所有寄存器，N: 总线编号，M: 16 进制设备地址 (0x 前缀可省略)

d. 单寄存器读取 i2cget -f -y 0 0x3c 0x00 # 读取 i2c-0 总线 0x3c 设备的 0x00 寄存器

e. 寄存器写入 i2cset -f -y 0 0x3c 0x40 0x12 # 向 i2c-0 总线 0x3c 设备的 0x40 寄存器写入 0x12

#### 3.1.3 波形示例

0x3d 是设备 addr，读取 0x00 地址 0x01 个字节大小数据，读出 10

写到 0x3d 地址，data：0x03

#### 3.1.4 I2C 子节点实现

如果要增加子节点，需要获取如下信息：

a. 设备在哪个 I2C 总线（如 i2c1）。

b. 设备的地址（如 0x48）。

c. 应该加载哪个驱动（如 national, lm75）。

#### 3.1.5 模拟 I2C 实现

a. 在对应 dts 添加节点，以 i2c11 为例;

b. 通过 menuconfig_kernel 配置 kernel 启用 i2c-gpio, 配置 CONFIG_I2C_GPIO = y, 然后执行 build_kernel, 编译 kernel, 最后替换 boot.itb

c. 此时通过 i2c detect -1，可观察到：

| i2c-0 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| i2c-1 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-2 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-3 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-4 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-5 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-6 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |
| i2c-7 | i2c | Synopsys | DesignWare | I2C | adapter | I2C | adapter | | | |

## pwm-常见问题

### PWM 引脚无波形输出

#### 未 pinmux
无波形输出。

#### 未按步骤使能 PWM
正确步骤（以 pwm1 为例，设置 50% 占空比，周期 1000000 * 10ns）：

```bash
echo 1 > /sys/class/pwm/pwmchip0/export
echo 1000000 > /sys/class/pwm/pwmchip0/pwm1/period
echo 500000 > /sys/class/pwm/pwmchip0/pwm1/duty_cycle
echo 1 > /sys/class/pwm/pwmchip0/pwm1/enable
```

#### 不明确 pwm 参数，致使操控不合预期
pwm 需要注意的参数：总共 4 个 pwmchip，每个有 4 路，为 pwm0~pwm15。pwm 时钟为 100M，精度为 10ns。最大可调节周期为 $ 2^{30} \times 10 $ ns 约为 10s。

#### pwm-fan 相关
pwm-fan 是 thermal 模块通过检测温度变化来控制 PWM 波调节 fan 风扇的。

#### 查看 pwm 通道占用状态
已经导出的 pwm 通道，可通过 cat /sys/kernel/debug/pwm 查看状态。

```bash
root@sophon:~# echo 70000 > /sys/class/thermal/thermal_zone0/emul_temp
root@sophon:~# cat /sys/kernel/debug/pwm
platform/27054000.pwm, 4 PWM devices
pwm-0 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-1 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-2 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-3 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
platform/27053000.pwm, 4 PWM devices
pwm-0 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-1 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-2 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-3 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
platform/27052000.pwm, 4 PWM devices
pwm-0 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-1 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-2 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-3 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
platform/27051000.pwm, 4 PWM devices
pwm-0 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-1 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-2 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-3 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
platform/27050000.pwm, 4 PWM devices
pwm-0 (pwm-fan)  ): requested enabled period: 1000000 ns duty: 666666 ns polarity: normal
pwm-1 (sysfs)  ): requested period: 0 ns duty: 0 ns polarity: normal
pwm-2 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
pwm-3 ((null))  ): period: 0 ns duty: 0 ns polarity: normal
```

## uart-常见问题

### SM9&SE9 设备串口无打印

- 设备升级到 1.8 版本以上，出现串口无打印现象。原因：SM9 老设备 SDK 版本升级至 1.8 以上需要更改 oem，https://developer.sophgo.com/thread/782.html。因为调试串口从 uart0 转到了 uart2。
- uart 设置为不常见波特率可能会出现设置波特率和实际波特率不一致的现象，最好示波器确认一下，以及查看寄存器实际分频系数。原因是 uart 设置 API 只支持设置标准波特率表内波特率。还有如果波特率如果设置过大，因为咱们常用串口板最大支持输出 3M 波特率，因此会出现波特率不匹配。
- 未 pinmux。
- dts 需要使能 UART，将需要测试的设备树节点 status 改为 "okay";

### 收发不到数据常见调试方式
有串口板的情况，发送或接收数据，看串口板灯闪是否符合收发数据的时机。没有的话看看 tx, rx 是否接反；uart 的 ttySx 是否存在；dmesg 是否有相应 ttySx 内容打印，是否正确 pinmux 看波形是否符合，波特率、数据格式是否对应，数据长度，停止位长度，奇偶校验位。查看 UART Tx，RX 中断的方法 cat /proc/interrupts | grep tty，看 UART 是否有中断。

## spi-常见问题

### SPI CS 管脚控制问题
建议使用 SPI 的时候 CS 管脚切换成 gpio 模式，在应用层做控制，如果使用 ip 本身的 CS 控制逻辑，每个传输周期结束就会拉高，部分 SPI 外设可能不兼容。

## can-常见问题

### CAN ID 混乱
芯片内部的 can IP 不能将标准帧和拓展帧混在一起收发，必须手动切换到对应模式。默认情况下 can IP 处于拓展帧模式。切换方法如下：

```bash
# 切换模式前先关闭 CAN
canconfig can0 stop 或者 ifconfig can0 down

# 切换到仅接收标准帧模式
canconfig can0 ctrlmode STD on
# 切换到仅接收拓展帧模式
canconfig can0 ctrlmode STD off
# 打开 CAN
canconfig can0 start 或者 ifconfig can0 up
```

切换模式是通过内核中的 ctrlmode 新增 CAN_CTRLMODE_STD 实现的。

```c
#define CAN_CTRLMODE_STD 0x100

sdtv_can_dev->can.ctrlmode_supported = CAN_CTRLMODE_LOOPBACK \
CAN_CTRLMODE_LISTENONLY \
CAN_CTRLMODE_BERR_REPORTING \
CAN_CTRLMODE_FD \
CAN_CTRLMODE_ONE_SHOT \
CAN_CTRLMODE_STD;
```

### 高速传输时出现帧混乱
一般是硬件连接阻抗不匹配导致的，请检查 can 总线两端是否并联了 $ 120 \Omega $ 电阻。检查 soc 与 can 转换器，can 转换器与总线的连接是否稳定。

## sata-常见问题

### sata-phy 硬件检查
因为 SATA 和 PCIE0 共用一个 phy，所以 SATA 的工作条件需要 PCIE0_CLK_P/N 有时钟信号输入。

| 信号名称 | 引脚 | 功能 | 备注 |
|---------|------|------|------|
| PCIE0_CLK_P | AE2 | PCIE0_CLK_P | [31] |
| PCIE0_CLK_N | AE1 | PCIE0_CLK_N | [31] |
| PCIE0_RX0_P | AH3 | PCIE0_RX0_P | [22] |
| PCIE0_RX0_N | AH2 | PCIE0_RX0_N | [22] |
| PCIE0_RX1_P | AF3 | PCIE0_RX1_P | [22] |
| PCIE0_RX1_N | AF2 | PCIE0_RX1_N | [22] |
| PCIE0_TX0_P | AG2 | PCIE0_TX0_P | [22] |
| PCIE0_TX0_N | AG1 | PCIE0_TX0_N | [22] |
| PCIE0_TX1_P | AJ2 | PCIE0_TX1_P | [22] |
| PCIE0_TX1_N | AJ1 | PCIE0_TX1_N | [22] |
| R1200 | AG6 | 200R 1% | [22] |
| PCIE0_RESREF | | | |

### 3.6 spacc-常见问题

#### 3.6.1 spacc 驱动的使用

a. 查看驱动是否成功加载：

ls /dev/spacc 是否存在。

b. 仿照驱动测试用例进行驱动的使用，可以参考源码目录：osdrv/osdrv_test/spacc

#### 3.6.2 对称加解密算法运算结果有问题

a. 先确定加解密数据源的地址和数据大小是否为 16B 对齐。使用 spacc 对称加解密的数据源大小必须按照 16B 对齐。如果不是使用驱动管理的内存池时，传入的物理地址需要 16B 对齐。

b. 使用驱动管理的内存池接口进行加解密时，需要注意一次加密数据量不应超过当前可用的空闲内存块的最大块。

c. 使用 cat /proc/buddyinfo 命令可以看看可用的内存块。

d. 将数据源拆成多块进行加解密时，需要自行计算每个分组的 IV 值，详情可参考驱动测试用例进行修改。

### 3.7 eth-网络常见问题

#### 3.7.1 ethtool 使用

a. sudo ethtool eth1 # 查询 eth1 网络接口的设置和状态，设置网络接口 eth1 开启自动协商、100M 速率、全双工模式

b. sudo ethtool -s eth1 autoneg on speed 100 duplex half

#### 3.7.2 phytool 使用

sudo phytool write eth0/0/0x1f 0xd08 #需要先切换页，这里是切换到0xd08页
sudo phytool read eth0/0/0x15 #读页0xd08的0x15寄存器的值
sudo phytool write eth0/0/0x15 xxx #往页0xd08的0x15寄存器写入xxx值
sudo phytool write eth0/0/0x1f 0 #读写操作结束，最后需要切换回去页0

#### 3.7.3 iperf3 使用

a. Test TCP performance

iperf3 -s #服务端
iperf3 -c 192.168.150.10 -t 100 #客户端

b. Test UDP performance

iperf3 -s #服务端
iperf3 -c 192.168.150.10 -t 100 -u -b 1000M -l 1460

参数说明：
-s：启动服务器模式，等待客户端连接。
-c <server_ip>：指定要连接的服务器的 IP 地址。
-p <port>：指定要连接的服务器端口，默认为 5001。
-t <time>：指定测试持续时间（以秒为单位），默认是 10 秒。
-u：使用 UDP 协议进行测试，默认是 TCP。
-b <bandwidth>：在使用 UDP 时，指定目标带宽。例如，-b 1000M 表示目标带宽为 1000 Mbps。
-l <length>：指定每个发送数据包的大小，上面指定数据包大小为 1460 byte。

#### 3.7.4 bm_set_ip 使用

问题：客户对 bm_set_ip 命令使用不熟悉；需要增加路由规则。

a. 恢复默认配置

bm_set_ip default

b. 设置 ip 和路由规则

通过 bm_set_ip 命令来设置路由规则：

bm_set_ip net_device ip netmask gateway dns to to_netmask via

参数解析：
net device: 指定网络接口，比如 eth1
ip: 指定的静态ip地址；netmask: 子网掩码；
gateway: 默认网关；dns: 域名服务器地址
to/to_netmask: 组成目标网络
via: 下一跳地址（网关）

示例：bm_set_ip eth1 192.168.150.10 255.255.255.0 "" "" 192.168.2.0 255.255.255.0 192.168.150.5

c. 使用 routes 来代替 gateway4，在较新的 netplan 版本中，gateway4 和 gateway6 已被弃用，官方推荐使用 routes 来代替它们。

d. 手动修改 netplan 配置

修改/etc/netplan/01-netcfg.yaml 文件，然后执行命令：sudo netplan apply

#### 3.7.5 ping 域名不通

问题描述：ping www.baidu.com不通，但是可以 ping 通外网 ip。

方法：修改 /etc/resolv.conf 文件，添加 DNS，添加 nameserver 8.8.8.8 后可以 ping 通域名了。

#### 3.7.6 修改 mtu 大小报错

问题描述：通过命令行修改 MTU size 报错

原因：没有先 down 掉网口会导致修改 mtu 失败

解决方法：

1. ip link set eth1 down //需要先down掉网口
2. ip link set eth1 mtu 2000 //再修改mtu大小，这里是修改mtu大小为2000
3. ip link set eth1 up //最后up网口

#### 3.7.7 客户验证网桥功能时遇到问题

问题：客户自己验证桥接的部分发现，经过验证这样的配置能让两个网口共享一个 IP，但是也只能是动态获取的 IP，静态 IP 不支持，也不支持多 IP。

解决方法：经过自己验证，发现是客户配置有问题，我们的产品是支持网桥功能的，直接修改 /etc/netplan/01-netcfg.yaml 文件即可。

1. 指定多个静态 ip
2. 指定动态 ip
3. 指定不同子网的的 ip

配置示例：

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: no
      addresses: []
      optional: yes
      dhcp-identifier: mac
    eth1:
      dhcp4: no
      addresses: []
      optional: yes
  bridges:
    br0:
      interfaces: [eth0, eth1]
      addresses: [192.168.2.108/24, 172.16.140.200/24]
      gateway4: 192.168.2.1
      nameservers:
        addresses: [192.168.2.1]
      dhcp4: no
```

#### 3.7.8 小数据包吞吐量不足导致丢包

问题描述：当设置数据包长度接近 MTU size 时候吞吐量不足 900M 导致丢包，MTU size 大小为 1500，指定数据包大小为 1460。

解决方法一：关闭 netfilter + 配置接收端负载均衡 RPS

a. 编译内核时候关闭 netfilter, netfilter 会影响性能, 执行：menuconfig kernel 关闭 netfilter

b. 配置 RPS

```bash
echo f > /sys/class/net/eth0/queues/rx-0/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-1/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-2/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-3/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-4/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-5/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-6/rps_cpus
echo f > /sys/class/net/eth0/queues/rx-7/rps_cpus

echo 2048 > /sys/class/net/eth0/queues/rx-0/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-1/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-2/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-3/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-4/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-5/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-6/rps_flow_cnt
echo 2048 > /sys/class/net/eth0/queues/rx-7/rps_flow_cnt
```

解决方法二：通过-P 参数设置多条流传输 + 配置 RPS

a. 配置 RPS 还是如上

b. 通过-P 参数设置多条流例子如下

udp tx
PC: iperf3 -s

板端：

iperf3 -c 192.168.1.11 -b 250M -u -t 100 -l 1460 -P4

#### 3.7.9 SE9 不支持并行检测

问题描述：客户交换机设置网络端口为关闭自协商，FIX 速率为 100M 全双工时候，与我们 SE9 的原型机相连，SE9 打开自协商，无法 linkup。

原因：交换机在关闭自协商后，不会再对外发送自协商 flp 波形而是发送 mlt3 idle 码，这就需要对端设备也就是我们 SE9 支持并行检测功能，但是由于并行检测只能协商到速率无法协商到双工模式，所以我们 PHY 的特性是当并行检测检测到 mlt3 空码时候，正常要 link 到 100M 半双工。但是由于 MAC 只支持全双工模式，所以驱动会对 phy 寄存器 0x4 配置不支持半双工，导致在并行检测时候 phy 无法 linkup。

解决办法：SE9 也强制设置速率，就能正常通信

设置网络接口 eth1 关闭自动协商、100M 速率、全双工模式

sudo ethtool -s eth1 autoneg off speed 100 duplex full

### 3.8 usb-常见问题

#### 3.8.1 切换 usb 的角色

```bash
# usb0 切为 host
echo host > /sys/kernel/debug/usb/39010000.usb/mode

# usb0 切为 device
echo device > /sys/kernel/debug/usb/39010000.usb/mode

# usb1 切为 host
echo host > /sys/kernel/debug/usb/39110000.usb/mode

# usb1 切为 device
echo device > /sys/kernel/debug/usb/39110000.usb/mode
```

#### 3.8.2 usb device 配置为指定功能

#### 3.8.3 device 作为存储设备的操作指南

a. 切换为 device mode

参考《3.8.1 切换 usb 的角色》

b. 运行脚本 run_usb.sh（bm1688 的路径为 /usr/sbin/run_usb.sh）

```bash
/etc/run_usb.sh probe msc /dev/mmcblkXY
/etc/run_usb.sh start
```

其中 mmcblkXY 为第 X 个磁盘的 eMMC 或 SD 中第 Y 个分区，请用户根据具体情况选择。

#### 3.8.4 Device 作为 RNDIS 设备的操作指南

a. 切换为 device mode

参考《3.8.1 切换 usb 的角色》

b. 运行脚本 run_usb.sh（bm1688 的路径为 /usr/sbin/run_usb.sh）

```bash
/etc/run_usb.sh probe rndis
/etc/run_usb.sh start
ifconfig usb0 192.168.3.101 up
```

c. 配置 windows 驱动

还要配置一下设备管理器，步骤如下：

1. 在设备管理器中找到 RNDIS 设备
2. 更新驱动程序
3. 选择"浏览我的计算机以查找驱动程序软件"
4. 指定驱动程序路径：C:\Program Files (x86)\BitmainDL\driver\30B1_1003
5. 选择"网络适配器"类型
6. 安装"Remote NDIS Compatible Device"驱动

#### 3.8.5 Device 作为 UVC 设备的操作指南

a. 切换为 device mode

参考《3.8.1 切换 usb 的角色》

b. 配置 sensor_cfg.ini

把板子和媒体对应的 sensor_cfg.ini 放到板子/mnt/data 目录。

c. 运行脚本 run_usb.sh（bm1688 的路径为 /usr/sbin/run_usb.sh）

脚本 run_usb.sh、ConfigUVC.sh 在板子的 /etc 目录下，sample_uvc 是一个应用程序，需要编译 middle/v2/sample/uvcsample 得到

```bash
/etc/run_usb.sh probe uvc
./ConfigUVC.sh
/etc/run_usb.sh start
./sample_uvc
```

d. 使用 potplayer 拉流

1. alt + d 快捷键打开 PotPlayer 的设备设置
2. 选中摄像头，配置设备为 UVC Camera，配置格式为 1080P，最后打开设备

#### 3.8.6 报错原因分析

a. 报错 probe of xhci-hcd.0.auto: can't setup: -110

说明 usb ip 没有时钟，检查 usb_clkp、usb_clkn 是否有 24MHz 的时钟输入

b. 报错 log 为 device descriptor read/64, error -61

基本上都是硬件问题，需要检查 soc usb 的外围电路，包括 usb ip 引脚和 hub 相关的电路

### 3.9 pcie-常见问题

#### 3.9.1 rc 问题

a. controller 初始化失败

检查 pinmux，以及初始化时是否正常拉高 pcie_l0_reset_x

状态异常打印：

```
[5.161706] cv186x_pcie 20400000.pcie: CV186X PCIe success
[5.496286] cv186x_pcie 20800000.pcie: pcie remote[0x18] = 0xc0000000
[5.502768] cv186x_pcie 20800000.pcie: pcie remote[0x1c] = 0xffffcfff
[5.610286] cv186x_pcie 20800000.pcie: polling core reset failed
[5.616354] cv186x_pcie: probe of 20800000.pcie failed with error -1
```

正常情况下，pcie controller 对应的管脚 pinmux config 如下：

```
root@sophon:/home/linaro# cvi_pinmux -r PCIE0_LO_RESET_X
pinctrl reg: 0x28104500
PCIE0_LO_RESET_X function:
[v] PCIE0_LO_RESET_X
[] GPIO40
value: 0

root@sophon:/home/linaro# cvi_pinmux -r PCIE1_LO_RESET_X
pinctrl reg: 0x2810450C
PCIE1_LO_RESET_X function:
[v] PCIE1_LO_RESET_X
[] GPIO43
[] CAN1_TX
[] UART2_TX
```

## 外设常见问题

### PCIe 问题

#### RC 问题

**枚举设备失败，lspci 无设备**

a. reset 管脚在初始化时，会拉低 300ms 再拉高；要确认对应设备树属性配置正常；reset-gpio 对应 pinmux 配置为 gpio

b. pipe mode：pcie0 跟 sata 共用同一个 phy，因此 pcie0 使用时，DTS 配置：pcie@20800000 和 pcie@20400000 两个设备节点的 pipe-mode 都要确保设置为 0；sata 节点需要 disable

c. 排查硬件连接以及时序是否符合 spec 要求

设备树配置示例：

```dts
pcie1:pcie@20400000 {
    pipe-mode = <0>; //b'00 x2&&x2; b'10 sata&&x2
    reset-gpio = <&portc 28 GPIO_ACTIVE_HIGH>; //gpio 92
};
pcie0:pcie@20800000 {
    pipe-mode = <0x0>; //b'00 x2&&x2
    reset-gpio = <&portc 27 GPIO_ACTIVE_HIGH>; //gpio 91
};
```

#### EP 问题

**a. 枚举失败**

驱动一直停在 perst polling，perst 信号没有正常拉高导致

**b. lspci 属性不对**

EP 端 a53 需要跟 pcie 同时被 reset，以保证 pcie 属性正常完成初始化

异常时会识别到一个 class 为 0000 的多 function 设备：

```bash
[root@cvitek] ~# lspci -m
00:00.0 "Class 0604" "1f1c" "1688" "0000" "0000"
01:00.0 "Class 0000" "1f1c" "1686" "0000" "a200"
01:00.1 "Class 0000" "1f1c" "1686" "0000" "a200"
```

正常情况下，是 class 0x1200：

```bash
[root@cvitek] ~# lspci -m
00:00.0 "Class 0604" "1f1c" "1688" "0000" "0000"
01:00.0 "Class 1200" "1f1c" "1686" "0000" "a200"
```

**c. EP 时，a53 发起 pcie 读写请求**

1. 配置 PCIE remote 空间
2. outbound 映射 remote 空间到 RC 端地址
3. a53 通过 remote 地址访问 RC 端

寄存器地址范围：

- pcie1@20400000
  - 20be000c reg_pcie2_remote_start_addr valid range is 0x8000_0000 ~ 0xFFFF_CFFF
  - 20be0010 reg_pcie2_remote_end_addr valid range is 0x8000_0000 ~ 0xFFFF_CFFF
- PCIe0@20800000
  - 20be0018 reg_pcie4_remote_start_addr valid range is 0x8000_0000 ~ 0xFFFF_CFFF
  - 20be001c reg_pcie4_remote_end_addr valid range is 0x8000_0000 ~ 0xFFFF_CFFF

参考示例：

1) config pcie remote space

```bash
mw 0x20be000c 0x80000000
mw 0x20be0010 0xbfffffff
```

2) outbound setting

```bash
mw 0x20700200 0x2000
mw 0x20700208 0x80000000 // base
mw 0x2070020c 0x0
mw 0x20700210 0xbfffffff // limit
mw 0x20700220 0
mw 0x20700214 0x00000000 // target ddr address
mw 0x20700218 0x1
mw 0x20700204 0x80000000
```

3) EP 端 a53 即可通过 0x80000000~0xbfffffff 访问 RC 端 0x100000000 开始的地址空间

### NVMe 常见问题

NVMe 无法识别问题主要是 PCIE RC RESET 是否配置正确

### SD 常见问题

#### SD UHS 模式切换问题

SD 的 IO 电压本身是支持 1.8/3.3V 切换的，当需要切换到 UHS 模式时，驱动会控制电压切换电路（前提是硬件有设计）切换至 1.8V，后续才能正常识别

DTS 配置：

```dts
sd:cv-sd@29310000 {
    // voltage switch control gpio config
    pwr-gpios = <&porte 5 GPIO_ACTIVE_HIGH>;
}
```

### 内置 MCU 常见问题

#### MCU 启动流程

MCU 位于芯片内部的 RTC_SYS 中，是一个 8051 处理器。理论上内置 MCU 可以通过特殊的总线设计访问芯片上所有的寄存器。可以通过配置 RTC_DOMAIN 的 MCU boot 寄存器来更改 MCU 的 boot 地址。

目前在边侧产品中，MCU 的固件会提前编译好，放置在 FSBL 仓库的这个位置：fsbl/plat/cvitek/cv186x/common/prebuilt/cv186x_MCU_FW.bin。在 BL2 阶段，MCU 固件将从 emmc 加载到 RTC_AHB_SRAM 中。在解开 MCU 复位后，MCU 从 RTC_AHB_SRAM 启动。

#### MCU 的代码设计

**a. DDR retrain**

MCU 代码包含了 DDR2 retrain 的内容。当系统需要 MCU 执行 DDR2 retrain 相关代码时，要先向 MCU 发送软件中断，MCU 随即执行中断函数中的 TRAIN 代码。因此，MCU 代码中被限制只能使用这一种中断，如果使用了多个中断有可能拖慢 DDR2 retrain 速度，进而导致其他 bug。

**b. 按键与上下电设计**

MCU 代码为 SE9、SM9 等产品实现了按键上下电与按键复位、回复出厂设置等设计。一般除了客户定制的 MCU 需求外，MCU 在不同产品上运行的是同一个固件。MCU 通过 OEM 来判断当前产品需要执行什么逻辑。BL2 阶段会将 OEM 从 EMMC 读到 SRAM，方便 MCU 从 SRAM 读取 OEM 中的 product 信息。

### GPIO 和 Pinmux 常见问题

#### 选择 GPIO 方法

`echo N > /sys/class/gpio/export`，N 为待操作的 GPIO 编号

GPIO 编号 = GPIO 组号值 + 偏移值

以原理图中 GPIO_num 管脚为例，num % 32 = base ...off，对应的组号为 base，偏移值为 off

例如 GPIO32，32 % 32 = 1 ...0，则其组号为 1，偏移值为 0，组号 1 对应的组号值为 448，因此 GPIO 编号 N 为 448 + 0 = 448

组号值对应：

- 组号 0 对应 linux 组号值为 480
- 组号 1 对应 linux 组号值为 448
- 组号 2 对应 linux 组号值为 416
- 组号 3 对应 linux 组号值为 384
- 组号 4 对应 linux 组号值为 352
- 组号 5 对应 linux 组号值为 320
- pwr_gpio 对应 linux 组号值为 288

`echo N > /sys/class/gpio/export` 之后，生成 `/sys/class/gpio/gpioN` 目录

#### Write error: Device or resource busy

通过 `cat /sys/kernel/debug/gpio` 检查 gpio 占用。检查一下 DTS。

#### UBoot 下怎么使用 GPIO

在使用 gpio 命令之前，需要确保 U-Boot 已启用了 GPIO 命令支持

U-Boot 的配置文件中检查以下选项是否启用：

- `CONFIG_CMD_GPIO=y`：启用 gpio 命令
- `CONFIG DM GPIO=y`：启用设备模型（DM）的 GPIO 驱动支持
- `CONFIG_DWAPB_GPIO=y`：启用实际 gpio 控制器的驱动

**UBoot 下 gpio 命令**

- status：显示所有 GPIO 引脚的状态
- input：将指定的 GPIO 引脚配置为输入模式并读取其值
- set：将指定的 GPIO 引脚设置为高电平（输出模式）
- clear：将指定的 GPIO 引脚设置为低电平（输出模式）

**设置 GPIO 为输入：**

1. 将引脚接地
   输入命令：`gpio input 29`；输出结果是 0
2. 将引脚接 VCC
   输入命令：`gpio input 29`；输出结果是 1

**设置 GPIO 为输出：**

3. 输出高电平
   输入命令：`gpio set 29`，万用表测量引脚电平为 1.8V 左右
4. 输出低电平
   输入命令：`gpio clear 29`，万用表测量引脚电平为 0V 左右

#### 代码操作 GPIO

**Pinmux 怎么查看表格，查看寄存器**

**a. UBoot 下 Pinmux 设置**

U-Boot 下 pinmux 头文件 u-boot-2021.10/board/cvitek/cv186x/pinmux 目录下，要在 UBoot 下配置 pinmux，需要包含 cv186x_pinmux.h

其中：`PINMUX_CONFIG(PIN_NAME, FUNC_NAME, GROUP)`

- PIN_NAME：引脚名，对应 pinlist 文档中第一列的 Signal Name
- FUNC_NAME：功能名，对应 pinlist 文档中要切换的功能
- GROUP：该功能所在 group，对应 pinlist 文档中 group 列

例如，要将 PWR_WAKEUP0 引脚的功能切为 PWR_IRRX0：

首先，去 pinlist 中找到 PWR_WAKEUP0 引脚所在行，并找到 group(7) 和目标 function(PWR_IRRX0)

在代码中通过 `PINMUX_CONFIG(PWR_WAKEUP0, PWR_IRRX0, G7)` 设置好 pinmux

重新编译 U-Boot，烧录固件重启

**b. Kernel 下 Pinmux 设置**

Kernel 下 pinmux 头文件位于 linux_5.10/drivers/pinctrl/cvitek/pinctrl-cv186x.h，使用同 U-Boot

**c. Userspace 下 Pinmux 设置**

Userspace 下提供了 cvi_pinmux 工具，支持设置 pinmux、内部上下拉以及驱动能力

使用方法：

- `./cvi_pinmux -p`：List all pins
- `./cvi_pinmux -l`：List all pins and its func
- `./cvi_pinmux -r pin`：Get func from pin
- `./cvi_pinmux -w pin/func`：Set func to pin
- `./cvi_pinmux -c <pin name>,<0 or 1 or 2>`：Set pin pull up/down (0:pull down; 1:pull up; 2:pull off)
- `./cvi_pinmux -d <pin name>,<0 ~ 15>`：Set pin driving

例如，要设置 PWR_WAKEUP0 引脚为 PWR_IRRX0 功能，并设置其内部上拉，驱动能力设置为 15（0~15 数值越大驱动能力越强）：

```bash
cvi_pinmux -w PWR_WAKEUP0/PWR_IRRX0
cvi_pinmux -c PWR_WAKEUP0,1
cvi_pinmux -d PWR_WAKEUP0,15
```

另外，可以通过 `cvi_pinmux -l` 列出 soc 上所有 pin 和其 functions，或通过 `cvi_pinmux -r pin name`，读取对应 pin 所包含的功能

### RS485 常见问题

#### RS485 通信异常问题

RS485 设计是 UART 经过一个 485 芯片，半双工工作，只能发或者收，无法做到同时发和送，如果有异常，先确认 UART 是否可以正常收发，另外 485 芯片可能不支持自动方向切换，需要控制一个 gpio 切换收发模式

### WiFi & BT 常见问题

蓝牙目前只支持 5.2 版本以下的协议

用户测试蓝牙连接时，安卓手机会只连接不配对。如果需要测试安卓设备的蓝牙连接，可安装 pulseaudio-module-bluetooth，执行如下命令：

```bash
sudo apt-get install pulseaudio-module-bluetooth
pulseaudio --start --log-target=journal
sudo systemctl restart bluetooth
```

### 4/5G 常见问题

#### 故障排查常用 AT 命令

- `AT+CPIN?`：检查模组是否识别到 SIM 卡
- `AT+COPS?`：显示运行商接入点 APN，要保证信号良好，否则返回 0
- `AT+CESQ`：查看信号
- `AT+CFUN=15`：重启模组
- `ATI`：查看固件版本
- `AT+GTIPPASS=1`：默认为 0，模组会启用 DHCP 服务；设置为 1 时，可从模组直接获取运营商分配的 IP

#### 无法识别 SIM 卡

#### 4G/5G 模组不支持 SIM 卡热拔插

#### 专网拨号

修改 `/usr/sbin/lteModem.py`，添加专网拨号命令：

```
AT+CGDCONT=1,"IP","xxx.vpdn"
AT+MGAUTH=1,"username","password"
```

#### 双模组支持

启用两个 lteModemManager 服务，只需修改 `/usr/sbin/lteModem.py` 中使用的串口和端口，确保两个服务使用的串口和端口不同

### Watchdog 常见问题

#### 看门狗驱动编译开启

在 linux 配置中打开这 3 个宏开关：

- `CONFIG_WATCHDOG=y`
- `CONFIG_WATCHDOG_CORE=y`
- `CONFIG_DW_WATCHDOG=y`

#### Athena2 watchdog 开启时间

Athena2 在 bl2 阶段就已经使能看门狗，在 kernel 启动后，内核会自动喂狗，保证系统不会重启

#### 如何喂狗

使用 busybox 命令设置看门狗喂狗时间以及超时时间：

```bash
watchdog -t 3 -T 20 /dev/watchdog0
```

- `-t` 参数设置喂狗周期，单位为秒
- `-T` 参数设置看门狗计数最长时间，单位为秒，在这个时间内没喂狗将直接 reboot

使用 `watchdog -t 3 -T 20 /dev/watchdog0` 设置后，会有应用程序自动喂狗

关闭喂狗：kill 掉 watchdog 进程就可以关闭喂狗，过一段时间会重启

#### 如何关闭看门狗

关闭看门狗首先需要向 `/dev/watchdog` 写入一个魔幻数 "V"，如 `echo V > /dev/watchdog`，才能够使能关闭看门狗命令

### 固件升级常见问题

#### 通过 SD 卡升级失败

检查 SD 卡格式是否为 FAT32 格式，并且表头为 MRB 格式，如果不是上述要求，在上电初始会有 SD mount 失败的打印

#### 通过 OTA 升级失败

OTA 升级失败，一般为升级的 OTA 包和原 SDK 固件的分区表不一致导致，OTA 升级脚本可以参考 sophon-tools/source/pota_update at main · sophgo/sophon-tools · GitHub

#### USB 升级常见问题

**a. 板子没有烧录，而是直接开机检查**

1. 不能插入 SD 卡
2. USB 数据线要支持数据需要
3. 使用 CviUsbInstallDriver.exe 安装 USB 驱动

**b. PC 工具打印 USB device not found**

需要检查接线是否正常

**c. 反复打印 Waiting for 和 found usb**

```
E:\yh\ai>usb_dl.exe -c cv186x -i fw/
[INFO] Using libusb v1.0.26.11724
[INFO] usb_dl build date: Oct 24 2024
[INFO] detect os type: ubuntu
[INFO] Waiting for USB device connection: |
[INFO] found usb device vid=0x3346 pid=0x1000
[INFO] Waiting for USB device connection: /
[INFO] found usb device vid=0x3346 pid=0x1000
[INFO] Waiting for USB device connection: /
[INFO] found usb device vid=0x3346 pid=0x1000
[INFO] Waiting for USB device connection: ---
```

# 外设常见问题

没有安装驱动需要执行 CviUsbInstallDriver.exe 进行安装

# TPU 常见问题

## 常用命令介绍

a. cat /proc/bmtpu/bmdi_base_info # 查看 libsophon git 版本及内部代码信息

b. cat /proc/bmtpu/bmdi_api_info # 查看当前 fifo 中的 api 信息

c. cat /proc/bmtpu/bmdi_lib_info # 查看当前加载的动态库信息

d. echo 2/1/0 > /sys/module/bmtpu/parameters/tpu_log_lv #tpu log 开关 1 为 debug 等级，2 为 info 等级

e. busybox devmem 0x28102170 # 查看 ddr clk 状态

f. busybox devmem 0x28102168 # 查看 tpu sys clk 状态

## tpu hang 常见问题

a. 随时根据问题情况补充 4.1 命令中的信息和 log，方便后续问题的快速定位

b. 此处 TPU hang 是指客户使用 TPU 过程中，发送 api 后 TPU 无法处理的问题。表现如下：通过 bm-smi 看到 TPU 的 Status 为 Fault。

红色框 Status 对应的状态如果为 Fault，则此时认为 TPU hang 了。正常状态应为 Active。通过 dmesg 或 kern.log 发现有 "TPU SYS hang" 的输出。

注意：这里所讲的 TPU hang，并不是硬件认为的 IP 没有响应 CPU 的请求，而是专门针对 API 没有在规定时间返回，导致超时的描述。既有可能是驱动程序异常，也有可能是 TPU scalar 处理异常，也有可能是 TPU 接收到的指令异常导致无法返回执行结果。发生 hang 时会看到 "TPU SYS hang"，但这通常不是第一现场。驱动中会标记 TPU 的当前状态，当某个 API 发生 hang 时该状态会置为 Fault，后续发送的 API 检测到该状态后会报 "TPU SYS hang"。因此排查此类问题首先要找到第一现场，即第一句 "TPU SYS hang" 附近的报错 log。

c. 当发生 hang 时，驱动会自动进行 debug，包括如下两项：

1. TPU scalar 状态确认：读取 TPU scalar pc 寄存器并与前一次结果进行对比，若值不同则说明 TPU scalar 仍在工作，若值相同说明 TPU scalar hang 死，打印 "TPU0/1 C906 hang"。

2. 软件状态确认：驱动中为 scalar 划分了一个 gp 寄存器（status）用于追踪软件状态，其值反映了守护进程的执行状态。常见的异常状态有如下几种：

i. "polling engine done"

打印该 log 说明 TPU hang 死在算子计算过程中，需要检查算子设计是否合理，可在出现 hang 之后运行如下脚本获取 TPU 寄存器值，交给工具链同事进一步分析。

ii. "C906 hang. TPUx C906 current status: 0xaaa"

守护进程会在开始执行 API 之前将 API id 写入 status 寄存器，等待 API 执行结束之后写入 0xaaa，如此反复。当 TPU hang 之后读到 0xaaa 说明 API 已执行完毕，但没有同步到 AP，这可能是由于使用了旧版 tpu-mlir 导致，需要重新编译 bmodel；另一种情况是在推送了很多条 API 之后调用 sync 导致超时，需要提高 sync 的频率或者增加超时时间。

d. 取 log 的方法

```
sudo tar -zxvflog.tgz /var/log/kern.log\ * /var/log/syslog
sudo chown linaro:linaro log.tgz
```

## bm-smi 常见问题

### bm-smi 各项参数含义

Mon Dec 5 19:27:14 2024: 执行 bm-smi时的时间日期

SDK Version: x.x.x: sdk的版本号

Driver Version: x.x.x.: 驱动的版本号

card:card id

name:芯片名称

Status:板卡状态，Active为活动状态，Fault为故障状态

BoardT:板级温度

chipT:芯片温度

boardP:板级功耗

TPU_P:TPU模块功耗

TPU_V:tpu模块的工作电压

12V_ATX: 板级 12V供电电流

ECC: DDR ECC是否使能

CorrectN:若 DDR使能，纠正错误的次数

SN:板卡序列号（共17位）

Bus-ID:PCIE模式先 domain:b:d.f

Mode:PCIE or SOC mode

Minclk:tpu最小工作频率

Maxclk:tpu最大工作频率

Curclk:tpu当前工作频率

MaxP:板卡最大功耗

TPU_C: tpu模块的工作电流

Memory-Usage:gmem总数和已使用数量

Tpu-Util:tpu的瞬时利用率

Fan:风扇转速

下面显示的是每个设备上每个进程（或者线程）占用的 gmem 的数量。

Processes: TPU Memory

TPU-ID PID Process name Usage

其它问题

在加载ko过程中重启，log如下

排查ddr clk是否打开busybox devmem 0x28102170，bit 28

# 内存常见问题

## 内存大小

进系统后查看命令

a. dmesg | grep Memory #### 查看总大小

b. cat /proc/meminfo #### 查看系统内存信息，与总大小的差值为预留

c. free -h

d. bm-smi

## 内存调整

动态调整内存工具参考：

https://doc.sophgo.com/bm1688_sdk-docs/v1.9/docs_latest_release/docs/BM1688_CV186AH_SophonSDK_doc/Appendix/2_mem_edit_tools.html

## ION 查看

ION 共分为 NPU 与 VPP 2 块，大小需要根据初始配置调整，查看 Ion 的大小的命令如下：

```
cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/summary
cat /sys/kernel/debug/ion/cvi_npu_heap_dump/summary
```

# 休眠唤醒常见问题

休眠唤醒通常情况下 console_suspend 之后就没有日志打印, 可以通过以下命令打开休眠时日志打印定位问题:

```
dmesg -n 8
echo N > /sys/module/printk/parameters/console_suspend
echo 1 > /sys/power/pm_debug_messages
```

# recovery 常见问题

## 进入 recovery

系统在上电启动或者重启过程中出现 mount 分区失败，无法正常进入命令行的情况，整机会出现循环重启的情况，这个时候可以进入 recovery 模式，进行修复或者查看异常原因，recovery 模式的原理是启动 ramdisk 文件系统，是在 DDR 上运行一个临时的文件系统，和 EMMC 没有关联，这样可以避免因为 EMMC 分区异常，导致无法进入命令行。

在 uboot 阶段，执行 CTRL + C 的操作，可以停留在 uboot 的命令行，然后执行 run recboot 命令，进入 recovery 模式。

## recovery 模式问题排查

进入到 recovery 模式后，只会有简单的文件系统，EMMC 的分区不会进行挂载，如果要进到 EMMC 分区查看内容，可以先做分区挂载。

如果要使用 SD 卡拷贝文件，可以先执行 mdev -s，才会生成设备节点才可以挂载，拷贝出对应的 log 信息后，才可以对问题进行分析。

# OEM 常见问题

查看 oem 信息方法：cat /factory/OEMconfig.ini

OEM 中最重要的参数就是 DTS_TYPE，这个决定全生命周期的 DTS 的选择，如果配置错误的 DTS，会出现 CPU 启动核数错误，内核 core dump 的情况。

# OS 常见问题汇总

## 目前 1688&CV186AH 支持的 OS 如下所示

| 操作系统 | BM1688&CV186AH | BM1684× | 使用场景 |
|---------|---------------|---------|---------|
| ubuntu20.04 | SDK1.8 及其之前版本都支持 | 支持 | SDK1.8 gcc 版本是 9.4，SDK1.7 及其之前 gcc 版本 6.3，在版本适配的时候需要注意 |
| ubuntu22.04 | SDK1.9 及其之后都支持 | 支持 | gcc 版本 11.4，安全性兼容性更好 |
| 麒麟 银河 V10 | 支持 | 支持 | 适用于国产化项目，可以提供测试包，商用化需要购买 license |
| Debian 12 | 支持 | 不支持 | 目前不跟随 SDK 版本走，只有提货量较大，才可以重新适配最新 SDK |
| 统信 OS | 正在适配 | 支持 | bm1688 积极适配中，但是还未发布 |
| 鸿蒙 | 不支持 | 不支持 | 工作量较大，需求少没有投入 |
| 翼辉 OS | 支持 | 不支持 | 国产化实时性操作系统，需要 license |

## 算能麒麟二次开发定制指南

背景：麒麟 OS 本身并不开源，所有使用麒麟 OS 的设备，都需要麒麟授权，算能并没有麒麟 OS 的源码，只有麒麟提供的烧录固件包，所以基于此现状，为了满足部分客户的定制需求，我们给出麒麟二次开发的方案，即使是二次开发的麒麟包，也需要麒麟正式授权。

## 麒麟版本

| 麒麟版本 | GCC 版本 | glibc 版本 | 补充说明 |
|---------|---------|-----------|---------|
| SDK1.8 | 9.4 | 2.31 | 可直接兼容算能 SDK1.8 |
| SDK1.9 | 9.4 | 2.31 | 算能 SDK1.9 要求：GCC 11.4, glibc 2.34 |

因为麒麟银河 OS 现在最高的 gcc 版本是 9.4，glibc 版本是 2.31，无法往上提升，所以才会和算能的 SDK1.9 的 gcc 和 glibc 会有差异。

### 定制 fip.bin

如果你们的 BL2、BL31、BL32、u-boot 有定制需求，直接修改其中的 code，然后进行编译，生成 fip.bin，替换掉麒麟固件包中的 fip.bin 即可。如果你使用的是算能的 SDK1.9 的源码，需要修改编译的工具链，如下目录文件的内容 build/boards/sophon/edge_wevb_emmc/edge_wevb_emmc_defconfig

上面文件做以下修改 CONFIG_TOOLCHAIN_GLIBC_ARM64_V1131=y 改成 CONFIG_TOOLCHAIN_GLIBC_ARM64_V930=y。

如果要做远程 OTA 升级，需要修改固件包里面 md5 文件中 fip.bin 的 md5 值。

### 定制内核 kernel

如果你们要修改 DTS 里面的内容，或者增加 kernel 中的驱动，那需要拿到对应 SDK 版本算能提供的源码，修改完成后，build_kernel 命令后，生成 boot.itb，其中包含 kernel 和 dts 的固件，以 SDK1.8 为例，boot.itb 在 ramdisk/build/bm1688_wevb_emmc/workspace 目录，将其替换到盒子的/boot 目录下，然后重启。

```
warranty; not even to merchantability of fitness for a particular purpose.
root@sophon:/mnt/system/ko# cd /boot/
root@sophon:/boot# ls
3.log 5.log boot.scr.emmc ftp.bin multi.its
4.log boot.itb end.log hdcp_key.bin soph_logo.bmp
root@sophon:/boot#
```

当然也有可能会出现重启后，启动失败的情况，这个主要原因是加载 KO 时候出现失败的。

所以保险起见，还是将设备的/mnt/system/ko 中的驱动 KO 全部替换成你重新编译的。

### 导出二次开发麒麟包

打开网址，下载工具 https://github.com/sophgo/sophon-tools/tree/main/source/psocbak

下载的文件是一个 socbak.zip 文件

将外置存储插入目标设备，然后执行如下操作

```
sudó su
cd /
mkdir socrepack
# /socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的 socbak.zip 传输到 /socrepack 目录下

执行如下命令进行打包

```
unzip socbak.zip
cd socbak
export SOC_BAK_ALL_IN_ONE=1
bash socbak.sh
```

等待一段时间

执行成功后会生成如下文件

```
root@sophon:/socrepack/socbak# tree -L 1
binTools
output
script
socbak.sh
socbak_log.log
socbak_md5.txt
3 directories, 3 files
```

其中 socbak_log.log 文件是执行的信息记录，刷机包在 output/sdcard/路径下。
