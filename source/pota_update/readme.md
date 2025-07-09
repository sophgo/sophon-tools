# OTA远程刷机工具

## 简介

本工具用于对SoC模式的SOPHON设备进行OTA远程刷机

## 文件内容

1. ota_update.sh OTA远程刷机工具
2. arm64_bin 该目录下会存放一些ota_update.sh依赖的二进制文件

## 适用范围

1. 针对BM1684平台，适用于2.7.0-最新release版本的OTA升级
2. 针对BM1684X平台，适用于V23.03.01-最新release版本的OTA升级
3. 针对BM1688和CV186AH平台，适用于1.5-最新release版本（边侧）的OTA升级

## 使用条件

1. 准备sd卡卡刷包，且sd卡卡刷包可以正常刷机并启动新的系统
2. 在执行刷机脚本前，emmc上最后一个分区（通常是data分区）需要有（刷机包大小+100MB）的空闲空间
3. 系统中需要有如下命令："systemd" "systemd-run" "tee" "exec" "echo" "bc" "gdisk" "mkimage" "awk" "sed" "tr" "gzip" "dd" "sgdisk" "fdisk"

## 使用方式

1. 将sd卡卡刷包拷贝到设备上并解压到sdcard文件夹下
2. 将ota_update.sh脚本cp到sdcard文件夹外，与sdcard文件夹同目录
3. 检查目录格式是否类似这个

    ```bash
    linaro@bm1684:/xxxxx$ ls
    ota_update.sh  sdcard
    linaro@bm1684:/xxxxx$ ls sdcard/
    BOOT                boot_emmc-opt.scr        data.12-of-58.gz  data.25-of-58.gz  data.38-of-58.gz  data.50-of-58.gz  gpt.gz              rootfs.12-of-32.gz  rootfs.25-of-32.gz  rootfs.9-of-32.gz
    boot.1-of-2.gz      boot_emmc-recovery.cmd   data.13-of-58.gz  data.26-of-58.gz  data.39-of-58.gz  data.51-of-58.gz  md5.txt             rootfs.13-of-32.gz  rootfs.26-of-32.gz  rootfs_rw.1-of-2.gz
    boot.2-of-2.gz      boot_emmc-recovery.scr   data.14-of-58.gz  data.27-of-58.gz  data.4-of-58.gz   data.52-of-58.gz  misc.1-of-1.gz      rootfs.14-of-32.gz  rootfs.27-of-32.gz  rootfs_rw.2-of-2.gz
    ...
    ```
4. 尽可能得关闭业务，尤其是占用最后一个分区的业务或服务。
5. 以root账户身份执行ota_update.sh脚本，比如命令`sudo bash ota_update.sh`，默认情况下OTA服务会保留最后一个分区（data分区）不烧录，如果当前设备和刷机包不满足这个条件，会报错 `[OTA PANIC] LAST_PART_NOT_FLASH mode, check last part start XXX != XXX`。如果需要烧录data分区,需要增加一个参数，示例：`sudo bash ota_update.sh LAST_PART_NOT_FLASH=0`

    ```bash
    linaro@bm1684:/xxxxx$ sudo bash ota_update.sh 
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
6. 等待文件`/dev/shm/ota_success_flag`或`/dev/shm/ota_error_flag`的创建，或者等待全局终端的广播`[OTA] Upgrade preparation is complete. Please restart the device to begin the upgrade.`。

    1. OTA服务的日志会存放到`/dev/shm/ota_shell.sh.log`中，日志文件会有所有的log，可以用命令`sudo tail -f /dev/shm/ota_shell.sh.log`监控该文件的最新变更
    2. OTA服务会停止docker服务
    3. OTA服务会杀死所有依赖最后一个分区的进程，所以当前终端被杀死是有概率发生的

7. 如果文件`/dev/shm/ota_success_flag`被创建，则手动重启设备即可开始刷机，刷机完成后设备会自动重启。
8. 如果文件`/dev/shm/ota_error_flag`被创建，需要检查emmc上分区表和最后一个分区的数据是否完整。然后检查`/dev/shm/ota_shell.sh.log`文件中的报错信息。
9. 刷机期间会ota程序会尝试驱动bootloader阶段注册的led灯，功能如下：

    1. 正常刷机状态下为status灯灭，error灯亮
    2. 正常刷机状态下每烧录一个包，error灯会快速地连续闪烁3次
    3. 刷机过程全部完成后status灯亮，error灯灭
    4. 刷机出现错误后会按照如下顺序报错：两个灯都灭2s，status灯闪烁一次，error灯闪烁n次，status灯闪烁一次。如果error灯闪烁n次，则对应了如下的错误：
        1. n=1 从emmc加载刷机脚本错误
        2. n=2 从emmc加载刷机脚本的格式校验错误
        3. n=3 fip文件烧录错误
        4. n=4 从emmc加载刷机包数据错误
        5. n=5 将数据包解压错误
        6. n=6 将解压后的数据写入emmc中错误

> 注：如果需要保留最后一个分区，操作如下：
>
> 0. 警告：此方案依赖刷机前后分区表中对于最后一个分区的描述完全一致。风险较大，使用前请测试完毕并备份数据。
> 1. 需要确保新旧分区表关于最后一个分区的起始扇区完全一致
> 2. 在上述操作的第5步前，执行`export LAST_PART_NOT_FLASH=LAST_PART_NOT_FLASH`
> 3. 按照上述操作继续执行，等到OTA升级完成，第一次启动后如果发现emmc上最后一个分区挂载失败则需要执行一次`mount -a`

## 自动重启配置方式

修改脚本末尾几行，将注释掉的 `reboot -f` 取消注释即可

## 准备阶段常见报错处理方式

### \[PANIC\] umount /dev/mmcblk0px error!!!

没有自动关闭掉占用最后一个分区的进程，需要手动使用 `sudo fuser -m mmc0最后一个分区的挂载点` 看一下哪个进程在一直占用这个分区。mmc0最后一个分区通常会挂载到 `/data`

## ota准备过程资源消耗

![屏幕截图_20241220_115824](https://github.com/user-attachments/assets/79346334-6e4a-4104-806f-26eee6b5b89e)

## 使用视频

TODO
