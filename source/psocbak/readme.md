# socbak工具

## 适用场景

* 芯片：BM1684 BM1684X BM1688 CV186AH
* SDK版本：
  * 84&X 3.0.0以及之前版本（适配只打包功能）
  * 84&X 3.0.0之后版本（适配只打包功能和打包做包功能）
  * 1688/186 V1.3以及之后版本（适配只打包功能和打包做包功能）
* 环境需求：
  * 外置存储：
    * 存储分区格式尽量保证ext4，防止特殊分区限制导致做包失败
    * 只打包功能要求外置存储至少是当前emmc使用总量的1.5倍以上
    * 打包做包功能要求外置存储至少是当前emmc使用总量的2.5倍以上
  * 设备需求：
    * 只打包功能要求除去打包设备外需要有一个ubuntu18/20的X86主机
    * 做包功能只要求有一个打包做包的设备
* SOCBAK做的刷机包目前不支持和官网的刷机包互相做ota升级

## 打包做包功能

1. 本功能84&4和1688/186平台使用方式完全一致，下方有该功能的完整示例视频。
2. 请在本仓库release页面下载最新的socbak.zip文件
3. 请尽可能关闭正在运行的业务，正在运行的docker容器必须关闭
4. 将外置存储插入目标设备，然后执行如下操作
   ``` bash
   sudo su
   cd /
   mkdir socrepack
   # 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
   mount /dev/sda1 /socrepack
   chmod 777 /socrepack
   cd /socrepack
   ```
5. 然后将之前下载的socbak.zip传输到/socrepack目录下，执行如下命令进行打包
   ``` bash
   unzip socbak.zip
   cd socbak
   bash socbak.sh SOC_BAK_ALL_IN_ONE=1
   ```
6. 等待一段时间，执行成功后会生成如下文件
   ``` bash
   root@sophon:/socrepack/socbak# tree -L 1
   .
   ├── binTools
   ├── output
   ├── script
   ├── socbak.sh
   ├── socbak_log.log
   └── socbak_md5.txt
   
   3 directories, 3 files
   ```
   其中socbak_log.log文件是执行的信息记录，刷机包在output/sdcard/路径下

### 修改emmc分区布局功能

> 注：本功能需要修改socbak脚本内容，每一步都需要慎重操作。防止打包出现问题。下方有该功能的完整示例视频。

功能介绍：可以通过socbak工具打包时调整目标刷机包的emmc分区布局，从而做到新的刷机包刷入设备后修改某个分区的大小。

修改方式：
1. 在执行`bash socbak.sh`前，需要修改文件`socbak.sh`
2. 打开文件`socbak.sh`，找到类似如下的一段内容
   ``` bash
   # These parameters define several generated files and
   # their default sizes for repackaging. Users can modify
   # them according to their device specifications.
   TGZ_FILES=(boot data opt system recovery rootfs)
   # Here are the default sizes for each partition
   declare -A -g TGZ_FILES_SIZE
   TGZ_FILES_SIZE=(["boot"]=131072 ["recovery"]=3145728 ["rootfs"]=2621440 ["opt"]=2097152 ["system"]=2097152 ["data"]=4194304)
   # The increased size of each partition compared to the original partition table
   ROOTFS_RW_SIZE=$((6291456))
   # for bm1688 or cv186ah
   ROOTFS_RW_SIZE_BM1688=$((9291456))
   RECOVERY_SIZE_BM1688=$((131072))
   TGZ_ALL_SIZE=$((100*1024))
   EMMC_ALL_SIZE=20971520
   EMMC_MAX_SIZE=30000000
   ```
3. 需要关注的变量如下：
   1. `TGZ_FILES_SIZE`: 默认配置各个分区的期望大小（socbak工具执行时会自动检测当前设备分区使用率，如果当前设备使用的空间大于期望大小，则自动扩大期望分区大小）
   2. `ROOTFS_RW_SIZE`: 根目录RW分区期望大小
   3. `ROOTFS_RW_SIZE_BM1688`: 对于BM1688/CV186AH平台根目录RW分区期望大小
   4. `RECOVERY_SIZE_BM1688`: 对于BM1688/CV186AH平台recovery分区期望大小
4. 修改方式：
   1. 如果是BM1684/BM1684X平台，修改`TGZ_FILES_SIZE`或者`ROOTFS_RW_SIZE`即可
   2. 如果是BM1688/CV186AH平台，修改`TGZ_FILES_SIZE`、`ROOTFS_RW_SIZE_BM1688`或者`RECOVERY_SIZE_BM1688`即可
   3. 修改后的总大小不得大于emmc大小，工具会自动检测，如果遇到`ERROR: bakpack size(XXX) > emmc size(XXX), please del some file and rework.`的报错，请检查文件是否太多了，或者自定义修改的分区期望大小太大了
5. 保存`socbak.sh`文件，继续执行`bash socbak.sh`命令，开始打包

### 固定分区大小功能

> 注意：此功能会固定预分配的分区大小，可能会导致打包失败。

1. 参考上一小节 `修改emmc分区布局功能` ，修改 `socbak.sh` 脚本文件，指定各个分区的大小
2. 在执行 `bash socbak.sh` 时，增加 `SOC_BAK_FIXED_SIZE=1` 参数，例如: `bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_SIZE=1`。

### 支持后续多次OTA的方案

1. 由于socbak默认会自动判断所需要的分区大小，导致多次打包的分区表布局不同，极大可能导致 `ota_update` 工具无法在保留最后一个分区的前提下完成刷机。
2. 如果需要socbak做升级刷机包，且需要 `ota_update` 去做ota升级并且还需要保留最后一个分区。则可以参考如下操作：
   1. socbak配置为固定分区大小，并且修改RO分区的大小，预留出日后更新的所需空间，比如3GB左右。
   2. 保存这个配置，后续所有出包均需要按照这个固定分区的模式出。
   3. 所有发到现场的设备都需要预先刷好这个配置出的刷机包，以确保 `ota_update` 可以保留最后一个分区的前提下完成刷机

## 示例视频

### 完整打包做包功能

https://github.com/user-attachments/assets/97f754e1-c575-4859-aaf8-8e9d60daeba9

### 修改emmc分区布局功能

https://github.com/user-attachments/assets/9791409c-a57e-4c87-96c4-7c11da022e0a
