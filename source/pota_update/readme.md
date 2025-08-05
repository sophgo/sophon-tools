# OTA远程刷机工具

## 简介

本工具用于对SoC模式的SOPHON设备进行OTA远程刷机

## 文件内容

1. ota.sh OTA远程刷机工具
2. arm64_bin 该目录下会存放一些ota.sh依赖的二进制文件

## 适用范围

1. 针对BM1684平台，适用于2.7.0-最新release版本的OTA升级
2. 针对BM1684X平台，适用于V23.03.01-最新release版本的OTA升级
3. 针对BM1688和CV186AH平台，适用于1.5-最新release版本（边侧）的OTA升级

## 使用条件

1. 准备sd卡卡刷包，且sd卡卡刷包可以正常刷机并启动新的系统
2. 在执行刷机脚本前，emmc上最后一个分区（通常是data分区）需要有（刷机包大小+100MB）的空闲空间
3. 系统中需要有如下命令："systemd" "systemd-run" "tee" "exec" "echo" "bc" "gdisk" "mkimage" "awk" "sed" "tr" "gzip" "dd" "sgdisk" "fdisk"

## 使用方式

1. 将sd卡卡刷包拷贝到设备上并解压
2. 将ota.sh脚本内容cp到刷机包内，文件名自定义，不要和刷机包中已有文件冲突，与BOOT文件同目录
3. 检查目录格式是否类似这个

    ```bash
    linaro@bm1684:/xxxxx$ ls
    BOOT                boot_emmc-opt.scr        data.12-of-58.gz  data.25-of-58.gz  data.38-of-58.gz  data.50-of-58.gz  gpt.gz              rootfs.12-of-32.gz  rootfs.25-of-32.gz  rootfs.9-of-32.gz
    boot.1-of-2.gz      boot_emmc-recovery.cmd   data.13-of-58.gz  data.26-of-58.gz  data.39-of-58.gz  data.51-of-58.gz  md5.txt             rootfs.13-of-32.gz  rootfs.26-of-32.gz  rootfs_rw.1-of-2.gz
    boot.2-of-2.gz      boot_emmc-recovery.scr   data.14-of-58.gz  data.27-of-58.gz  data.4-of-58.gz   data.52-of-58.gz  misc.1-of-1.gz      rootfs.14-of-32.gz  rootfs.27-of-32.gz  rootfs_rw.2-of-2.gz
    <ota_shell_file>       ...
    ```
4. 尽可能得关闭业务，尤其是占用最后一个分区的业务或服务。并保存工作文件，OTA服务准备完成后会自动重启设备。
5. 以root账户身份执行<ota_shell_file>脚本，比如命令`sudo bash <ota_shell_file>`，默认情况下OTA服务会保留最后一个分区（data分区）不烧录，如果当前设备和刷机包不满足这个条件，会报错 `[OTA PANIC] LAST_PART_NOT_FLASH mode, check last part start XXX != XXX`。如果**需要烧录data分区**，需要增加**一个参数说明不需要保留最后一个分区**：`sudo bash <ota_shell_file> LAST_PART_NOT_FLASH=0`

    ```bash
    linaro@bm1684:/xxxxx$ sudo bash <ota_shell_file>
    Running as unit: sophon-ota-update.service
    Unit sophon-ota-update.service could not be found.
    [INFO] ota server started, check status use: "systemctl status sophon-ota-update.service --no-page -l"
    [INFO] server log file: /dev/shm/ota_shell.sh.log
    [INFO] if ota success, file /dev/shm/ota_success_flag will be created
    [INFO] else if ota error, file /dev/shm/ota_error_flag will be created
    [INFO] please wait file /dev/shm/ota_success_flag or /dev/shm/ota_error_flag
    [WARRNING] ota server will resize last partition on emmc, if error, please check emmc partitions
    [WARRNING] ota server will stop docker server and all program on last partition
    ```
6. 第五步执行完毕后会直接退出，此时后台会自动启动OTA准备服务。如果OTA准备服务完成，则设备会自动重启。如果文件 `/dev/shm/ota_error_flag` 被创建或者有 `[OTA PANIC]` 相关的全局广播，则代表发生错误。如下是OTA服务准备过程中的一些信息：

    1. OTA服务的日志会存放到`/dev/shm/ota_shell.sh.log`中，日志文件会有所有的log，可以用命令`sudo tail -f /dev/shm/ota_shell.sh.log`监控该文件的最新变更
    2. OTA服务会停止docker服务
    3. OTA服务会杀死所有依赖最后一个分区的进程，所以当前终端被杀死是有概率发生的
    4. 如果文件`/dev/shm/ota_error_flag`被创建或者有 `[OTA PANIC]` 相关的全局广播，需要检查emmc上分区表和最后一个分区的数据是否完整。然后检查`/dev/shm/ota_shell.sh.log`文件中的报错信息。
    5. 如果想要中断OTA准备服务，需要执行 `sudo systemctl stop sophon-ota-update.service`
    6. OTA准备服务可能会修改刷机包中的 `gpt.gz` 文件，用于与设备对齐末尾分区偏移和大小，服务在准备完毕后会自动恢复该文件

7. 设备重启后会开始OTA刷机过程，刷机期间会ota程序会尝试驱动bootloader阶段注册的led灯（status灯和error灯），功能如下：

    1. 在SE5/7上，status灯大多数情况是绿色的，error灯则是其他颜色。并且系统正常启动后长亮的那个是status灯，可以根据这个确定灯的名称
    2. 正常刷机状态下为status灯灭，error灯亮
    3. 正常刷机状态下每烧录一个包，error灯会快速地连续闪烁3次
    4. 刷机过程全部完成后status灯亮，error灯灭
    5. 刷机出现错误后会按照如下顺序报错：两个灯都灭2s，status灯闪烁一次，error灯闪烁n次，status灯闪烁一次。如果error灯闪烁n次，则对应了如下的错误：
        1. n=1 从emmc加载刷机脚本错误
        2. n=2 从emmc加载刷机脚本的格式校验错误
        3. n=3 fip文件烧录错误
        4. n=4 从emmc加载刷机包数据错误
        5. n=5 将数据包解压错误
        6. n=6 将解压后的数据写入emmc中错误

8. 刷机完成后设备会再次自动重启，重启后即进入刷机后第一次正常启动的状态。

## 禁止OTA准备服务自动重启配置方式

修改脚本末尾几行，注释掉的 `reboot -f` 即可

## 准备阶段常见报错处理方式

### \[PANIC\] umount /dev/mmcblk0px error!!!

没有自动关闭掉占用最后一个分区的进程，需要手动使用 `sudo fuser -m mmc0最后一个分区的挂载点` 看一下哪个进程在一直占用这个分区。mmc0最后一个分区通常会挂载到 `/data`

### \[OTA PANIC\] LAST_PART_NOT_FLASH mode, check last part start XXX != XXX

当前刷机包中最后一个分区的偏移和当前设备最后一个分区的偏移不一致。如果需要保留最后一个分区的内容，需要校对刷机包是否正确;如果不需要保留最后一个分区的内容，执行时增加`LAST_PART_NOT_FLASH=0`参数即可

### \[OTA PANIC\] resize2fs /dev/mmcblk0p7 -> 10820655K, please check if your eMMC partition is healthy

缩小最后一个分区大小失败，执行如下操作做检查：

1. `mount -a` 然后查看最后一个分区是否挂载完毕
2. 使用 `fsck` 工具尝试修复最后一个分区
3. `resize-helper` 整理最后一个分区
4. 清理mmc0最后一个分区的的内容

然后再尝试

## ota准备过程资源消耗

![屏幕截图_20241220_115824](https://github.com/user-attachments/assets/79346334-6e4a-4104-806f-26eee6b5b89e)

## 使用视频

### 不烧录最后一个分区（默认）

https://github.com/user-attachments/assets/9362c671-0a5e-4be2-aaec-6411704c39b4

1. 拷贝刷机包到/data分区
2. 不带参数直接执行刷机包中的 `<ota_shell_file>`
3. ssh终端由于在/data下，所以被kill掉了。重新连接，查看OTA准备服务的日志
4. 准备完成后设备自动重启，查看串口log
5. 刷机到root-ro分区的第13个包时设备断电然后重新上电，模拟OTA刷机时电压不稳。设备重新上电后基于之前的刷机进度继续刷机
6. 刷机完成后自动重启（文件大小原因这部分跳过）
7. 启动后查看/data分区，发现该分区文件被保留

### 烧录最后一个分区

https://github.com/user-attachments/assets/ea21d468-b1d3-4b13-bd3e-d2fbd4852d46

1. 拷贝刷机包到家目录
2. 带 `LAST_PART_NOT_FLASH=0` 参数直接执行刷机包中的 `<ota_shell_file>`，查看OTA准备服务的日志，期间在/data分区创建了文件testfile
3. 准备完成后设备自动重启，查看串口log
5. 刷机完成后自动重启
6. 启动后查看/data分区，发现创建的testfile文件被删除
