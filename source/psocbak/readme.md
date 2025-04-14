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

## 打包做包功能

本功能84&4和1688/186平台使用方式完全一致

请在本仓库release页面下载最新的socbak.zip文件

请尽可能关闭正在运行的业务

将外置存储插入目标设备，然后执行如下操作

``` bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

执行如下命令进行打包

``` bash
unzip socbak.zip
cd socbak
export SOC_BAK_ALL_IN_ONE=1
bash socbak.sh
```

等待一段时间

执行成功后会生成如下文件

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

> 注：本功能需要修改socbak脚本内容，每一步都需要慎重操作。防止打包出现问题

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

## 示例视频

### 完整打包做包功能

https://github.com/user-attachments/assets/97f754e1-c575-4859-aaf8-8e9d60daeba9

### 修改emmc分区布局功能

TODO
