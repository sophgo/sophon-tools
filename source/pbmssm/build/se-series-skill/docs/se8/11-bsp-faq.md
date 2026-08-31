---
title: BSP FAQ
description: BSP常见问题
tableOfContents:
  maxHeadingLevel: 3
sidebar:
  hidden: true
---

## 网络问题
### 常见问题
#### 业务网线插在了非GE1口，算力节点无法访问业务网络
答：建议将SE8的GE1网口作为业务口，系统默认为经过GE1口的流量做了地址伪装，以及将算力节点22端口映射到GE1口对应的网卡下。或者修改/root/se_ctrl/iptable_setup.sh(有些版本是/root/se6_ctrl/iptable_setup.sh)的wanname，把wanname改为GE2/GE3对应的网卡名称，最后重新执行该脚本。

#### 修改了 GE2/GE3 网口的ip，重启后发现ip被重置了
答：在/root/se_ctrl/se_init.sh（有的版本是/root/se6_ctrl/se6_init.sh），搜`bm_set_ip`,找到 `bm_set_ip ${被重置的网卡名} 172.16.180.200 255.255.255.0 "" ""`并注释，然后重新修改GE2或者GE3网口的ip，下次重启就不会被重置了。

#### 算力节点需要通过 GE2/GE3 口访问网络，如何配置
答：在/root/se_ctrl/iptable_setup.sh(有些版本是/root/se6_ctrl/iptable_setup.sh)的最后一行，加上`iptables -t nat -A POSTROUTING -o $lanname -j MASQUERADE`, 其中 `$lanname` 为网卡名称，如enp4s0f1，注意：建议通过`ifconfig`确认网卡名称。 

#### 如何把算力节点的端口映射到主控节点上
答：假如要将第5个算力节点（172.16.140.15）的80端口映射到主控192.168.1.107的8015端口上，在/root/se_ctrl/iptable_setup.sh(有些版本是/root/se6_ctrl/iptable_setup.sh)的最后一行，加上`iptables -t nat -A PREROUTING -d 192.168.1.107 -p tcp --dport 8015 -j DNAT --to-destination 172.16.140.15:80`，最后重新执行该脚本，建议用`sudo iptables -t nat -nvL`检查下是否映射成功。之后每次开机启动时，会自动执行该脚本，完成端口映射。

#### 在控制节点无法访问算力节点映射到控制节点的端口
答：这种情况下相当于控制板访问控制板的端口，这个过程不走网卡，走的是io，如果必须访问控制板上的端口，就需要用Nginx做正向代理。

#### 现场同一网络下多台SE8做了bonding，SSH无法登陆
答：由于bonding接口默认在某些配置下可能生成相同的MAC地址，导致MAC冲突，需要在netplan配置文件给bonding设置MAC地址。

#### 海光处理器的主控节点执行 `ip a`命令没有网卡打印
答：有可能是误升内核，导致网卡驱动没法用。机器下电后再启动，在grub启动界面选择旧内核启动。

## bmsec 问题
### 常见问题
#### 如何在主控节点批量对算力节点进行操作
答：SE8出厂预装bmsec工具，bmsec支持多种操作，包括批量远程执行短命令、管理远程设备信息、批量文件传输、SSH连接、设备重启、tftp刷机、端口映射等。可以执行命令`bmsec help`获取使用说明，详细介绍文档：https://github.com/sophgo/sophon-tools/blob/main/source/pbmsec/doc/10_UserReferenceDocumentation_zh.md

#### 怎么知道节点id和节点ip的映射关系
答：主控节点执行 `bmsec pconf`，序号即算力节点id，IP地址即算力节点ip。

#### `bmsec pconf`发现无配置信息打印
答：无配置信息打印样例：
```
se6@master:~$ bmsec pconf
config info: 
```
这时候请执行`bmsec rconf`命令。

#### `bmsec pconf`发现22号端口没有映射到控制节点
答： 22端口没有映射到主控的返回样例：
```
se6@master:~$ bmsec pconf
config info: 
1. linaro:linaro@(172.16.140.11):22 -> 
2. linaro:linaro@(172.16.140.12):22 -> 
3. linaro:linaro@(172.16.140.13):22 -> 
4. linaro:linaro@(172.16.140.14):22 -> 
5. linaro:linaro@(172.16.140.15):22 -> 
6. linaro:linaro@(172.16.140.16):22 -> 
10. linaro:linaro@(172.16.150.14):22 -> 
11. linaro:linaro@(172.16.150.15):22 -> 
12. linaro:linaro@(172.16.150.16):22 -> 
```
1. 控制节点执行 `sudo iptables -t nat -nvL` 检查端口映射情况，此时一般无法找到22号端口映射。
2. 控制节点执行 `bash -x /root/se_ctrl/iptables_setup.sh` (有些版本是/root/se6_ctrl/iptables_setup.sh)，查看脚本执行有无报错，则依据log排查，一般是wanname设置错误导致wanip找不到（可参考“业务网线插在了非GE1口，算力节点无法访问业务网络”一节排查），或者是用户自行修改引入的语法错误。
3. 根据log将iptables_setup.sh改对，然后重新执行该脚本。此时执行 `sudo iptables -t nat -nvL` 能找到22号端口映射。

#### 在控制节点使用`bmsec uart 3`命令通过串口访问节点3后，无法退出串口回到控制节点
答：键盘按住ctrl键不放，然后先后按键盘a和x键。

## 固件升级问题
### 常见问题
#### 算力节点固件升级推荐的推荐方式是什么
答：以安装deb包的方式升级sdk，可以先尝试一块算力节点并重启，检查升级是否成功，再批量，如果正向升级时（从低向高），基本上我们能保证，但是反向，需要注意。

#### 通过安装deb包方式升级后，算力节点执行`bm_version`命令查看版本号，SophonSDK version 的版本号没有更新
答：这种升级方式不是刷机，因此只需要关注 `sophon-soc-libsophon` 是否和 `sophon-soc-libsophon_${x.y.z}-LTS_arm64.deb `包名对应的版本号 `${x.y.z}` 一致，关注 `sophon-mw-soc-sophon-ffmpeg` 是否和 `sophon-mw-soc-sophon-ffmpeg_${x.y.z}_arm64.deb` 包名对应的版本号 `${x.y.z}` 一致，关注 `sophon-mw-soc-sophon-opencv` 是否和 `sophon-mw-soc-sophon-opencv_${x.y.z}_arm64.deb` 包名对应的版本号 `${x.y.z}` 一致，如果这三个版本号都和包名保持一致，则升级成功。

#### 算力节点升级失败，通过串口访问算力节点，发现ddr train失败错误
答：串口打印：`Lpddr train failed`

  1. 该问题是通常是由于spi_flash不匹配导致，需要升级对应版本的spi_flash。
  2. 由于已经进入不了uboot，只能通过串口的方式进行升级spi_flash
  3. 升级spi_flash的命令如下：

    1) 打开2个 ssh 连接到控制节点，一个使用串口连接到出错的算力节点，另外一个通过命令reset，bmsec rest 3(错误的算力节点)
    2) 重启后串口可以看到：
        NOTICE: Booting Trusted Firmware
        NOTICE: BLl: bm1684 asic:v1.4(release):g26fd4af
        NOTICE: BLl: Built : 12:00:06，Mar 21 2019
        NOTICE:GPI00:0x2700
        NOTICE:Hit any key to stop autoboot: 1
    3) 串口看到如上提示时，摁jjjjjj 键(1684X按 fff 键) 进入BL1 mode：
    4) 拆分spi_flash文件
        由于现在版本spi_flash文件过大，需要拆分，文件大小不要超过1024K（1684可以稍微大一些到1.3M左右）
        dd if=spi_flash_bm1684x.bin of=spi_flash_bm1684x.bin.part1 bs=1K count=1024
        dd if=spi_flash_bm1684x.bin of=spi_flash_bm1684x.bin.part2 bs=1K skip=1024 count=1024
        dd if=spi_flash_bm1684x.bin of=spi_flash_bm1684x.bin.part3 bs=1K skip=2048 count=1024
        dd if=spi_flash_bm1684x.bin of=spi_flash_bm1684x.bin.part4 bs=1K skip=3072
    5) 串口输入：ymodem 0x10100000
    6) 串口传输文件：依次摁下： Ctrl+A Z S  选择ymodem（空格选中，回车确认）需要传输的spi_flash_bm1684.bin-part*
    7) 传输完成后回车，烧录spi flash：
        spif 0x10100000 0x0 0x100000
        0x0 为偏移量，第一个包从0开始
        0x100000为文件的大小长度
    8) 重复6和7的步骤，注意:烧录spi flash需要加偏移量，以上面拆分的为例：
        第二个包：spif 0x10100000 0x100000 0x100000
        第三个包：spif 0x10100000 0x200000 0x100000
        第四个包：spif 0x10100000 0x300000 0x17D1C
        第四个包的大小是变化的，需要根据实际拆包大小填写
    9) 烧录完成后：reset

#### 在使用tftp给算力节点刷机时，/recovery/tftp空间不足以放tftp刷机包
答：以下操作在控制节点执行：
1. 修改`/etc/default/tftpd-hpa`的`TFTP_DIRECTORY`，如下：
```
se8@999999-host:~$ cat /etc/default/tftpd-hpa 
# /etc/default/tftpd-hpa

TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/home/se8/sophgo/ansible/SE8-416_core_tftp_231124/" # 修改这里
TFTP_ADDRESS=":69"
TFTP_OPTIONS="-v --secure"
```
2. 重启tftpd-hpa服务：`sudo systemctl restart tftpd-hpa`


## 其他问题
### 常见问题
#### 算力节点ntp时间同步失败
答：
1.检查控制节点的ntp服务是否存在，在控制节点执行`sudo systemctl status ntp`，如果不存在则安装下ntp的包 `sudo apt install nfs-kernel-server nfs-common`；
2.检查算力节点根目录是否写满，以及检查 systemd-timesyncd 服务是否正常运行，在算力节点执行`sudo systemctl status systemd-timesyncd`，并检查日志。

#### 系统变成只读模式(算力节点或者主控为BM1684X的控制节点)
答： 首先使用df -h 查看根目录的使用情况，确认是否是根目录满导致的只读模式。
  如果是根目录满了:

    1. cd /media/root-rw/overlay
    2. 使用命令（du . -d 1 -h ）逐层检查每个目录的大小，通常会出问题的是/media/root-rw/overlay/var/log 和 /media/root-rw/overlay/home 目录
    3. 删除比较大的文件，释放空间，例如删除 /media/root-rw/overlay/var/log 目录下的文件
    4. 重启系统

  如果是根目录未满:

    1. 需要连接串口，查看系统启动日志，确认是否是其他原因导致的只读模式。
    2. 通常情况是系统盘有损坏，需要修复系统盘。修复方式如下：
      1) 串口连接，启动设备按回车到U-Boot环境
      2) 输入命令：run recboot， 进入recovery mode
      3) 输入命令：e2fsck /dev/mmcblk0p5
      4) 输入命令：reboot -f

#### SE8-416安全检查不通过，需要升级openssh和nginx 版本等问题
答： 我们提供升级openssh和nginx的脚本，可以联系客户支持获取。

#### 执行`bmsec getbi`发现算力节点掉线了
答：
1. 尝试通过串口访问`bmsec uart core_id`算力节点，如果能访问，在算力节点检查根目录是否写满、检查`/etc/netplan/*.yaml`是否有语法错误、检查/var/log/kern.log*是否有oom的情况；
2. 如果无法访问算力节点，尝试重启该节点的电源`bmsec reset core_id`，或者重启整机`reboot_all`，如果重启后能访问算力节点，则尝试第一条方法。

#### 如何做算力节点的NFS挂载
1. 在主控板检查nfs服务是否为active
```
sudo systemctl status nfs-server
```

2. 在主控板新增nfs配置
```
vim /etc/exports

data *(rw,no_root_squash,no_all_squash,async)
#保存

sudo systemctl restart nfs-server

showmount –e #查看是否有挂载点, 如:/data

```

3. 在算力节点上新增挂载配置
```
# ssh 登录到节点1
bmsec ssh 1
sudo vim /etc/fstab.emmc.ro
#在 fstab选项中加入 nofail,bg,可以避免挂载时，网络还没ready
172.16.140.200:/data    /mnt    nfs     defaults，nofail,bg                   0       0
#保存

vim /root/se_ctrl/se_init.sh
#在bm_set_ip 后新增两行 大约在250行附近，具体根据版本决定，如果已有这两行则无需再新增
systemctl restart remote-fs.target
systemctl restart *.mount
#保存

#将修改同步到其他节点
#通过scp将fstab.emmc.ro和se_init.sh传到主控板
scp /etc/fstab.emmc.ro 主控板
scp /root/se_ctrl/se_init.sh 主控板 

# 回到主控板 ctrl + D
```

4. 把改后的fstab.emmc.ro和se_init.sh分发到所有节点
```
#主控板执行
bmsec pf all fstab.emmc.ro /home/linaro/
bmsec pf all se_init.sh /home/linaro/

bmsec run all "sudo cp fstab.emmc.ro /etc/ "
bmsec run all "sudo cp se_init.sh /root/se_ctrl/ "

#重启
bmsec run all  "sudo reboot now"
#重启后
bmsec run all "df –Th |grep nfs"
#会有所有算力节点的nfs挂载信息打印
```
