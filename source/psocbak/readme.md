# socbak工具

## 适用场景

* 芯片：BM1684 BM1684X BM1688 CV186AH CV84X6
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

## 刷机包的分区表格式（V1.5.0 起）

不同芯片产出的分区表单位不同，工具会自动选择，不需要手工切换：

| 芯片 | 分区表文件 | 尺寸单位 | 说明 |
| --- | --- | --- | --- |
| BM1688 / CV186AH（SE9 16 / SE9 8） | `partition32G_sector.xml` | `size_in_sectors` | 与 CV84×6 SDK 的 `scripts/partition32G_sector.xml` 同构，1 sector = 512 B |
| CV84X6（SE13） | `partition32G_sector.xml` | `size_in_sectors` | 同上 |
| BM1684X（SE7/SE8）/ BM1684 | `partition32G.xml` | `size_in_kb` | 与历史版本逐字节相同 |

要点：

* `socbak.sh` 里所有分区大小配置（`TGZ_FILES_SIZE*`、`ROOTFS_RW_SIZE*`）仍然是 **KiB**，
  写分区表时按 ×2 换算成扇区。已有的布局调整方法不受影响。
* 每个刷机包内只有一份 `partition*xml`，与单位的切换无关。
* 首个分区（BOOT）仍从 LBA 8192 开始，分区顺序、字节容量、只读位、文件系统都与原布局一致。
* sector 格式的分区表由 `sgdisk` 生成主 GPT（`binTools/mk_gpt` 只认 KiB，无法表达奇数扇区）。
  分发包已自带 `binTools/sgdisk`（aarch64 静态链接，无动态库依赖，与其它 binTools 一起进
  `socbak_md5.txt` 校验），优先使用它；找不到时才回退到系统 PATH 里的 `sgdisk`。
  v1.5.1 起在芯片识别后立即检查该工具，缺失时立刻报错退出，不会等到备份跑完才失败。
  末分区可以一直用到 `total-34`（与 SDK `mk_sector_gpt` 的 `last_usable_lba` 相同），
  最后 33 个扇区留给备份 GPT；再往后一个扇区就判打包失败。
* 已用 `ota_update` v1.5.8 验证两种单位的容量换算与 DATA 起点检查，OTA 沿用现有配置。

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
   # for cv84x6（CV84X2，SDK 标识 cv84x6），与 bm1688/cv186ah 同属 CV 系，默认对齐
   ROOTFS_RW_SIZE_CV84X6=$((9291456))
   RECOVERY_SIZE_CV84X6=$((131072))
   TGZ_ALL_SIZE=$((100*1024))
   EMMC_ALL_SIZE=20971520
   EMMC_MAX_SIZE=30000000
   ```
3. 需要关注的变量如下：
   1. `TGZ_FILES_SIZE`: 默认配置各个分区的期望大小（socbak工具执行时会自动检测当前设备分区使用率，如果当前设备使用的空间大于期望大小，则自动扩大期望分区大小）
   2. `ROOTFS_RW_SIZE`: 根目录RW分区期望大小
   3. `ROOTFS_RW_SIZE_BM1688`: 对于BM1688/CV186AH平台根目录RW分区期望大小
   4. `TGZ_FILES_SIZE_BM1688`: 对于BM1688/CV186AH平台其余分区的期望大小
   5. `ROOTFS_RW_SIZE_CV84X6`/`TGZ_FILES_SIZE_CV84X6`/`RECOVERY_SIZE_CV84X6`: 对于CV84X6平台根目录RW、其余分区、recovery 分区的期望大小（默认对齐 BM1688）
4. 修改方式：
   1. 如果是BM1684/BM1684X平台，修改`TGZ_FILES_SIZE`或者`ROOTFS_RW_SIZE`即可
   2. 如果是BM1688/CV186AH平台，修改`TGZ_FILES_SIZE`、`ROOTFS_RW_SIZE_BM1688`或者`TGZ_FILES_SIZE_BM1688`即可
   3. 如果是CV84X6平台，修改`TGZ_FILES_SIZE`、`ROOTFS_RW_SIZE_CV84X6`或者`TGZ_FILES_SIZE_CV84X6`即可
   4. 修改后的总大小不得大于emmc大小，工具会自动检测，如果遇到`ERROR: bakpack size(XXX) > emmc size(XXX), please del some file and rework.`的报错，请检查文件是否太多了，或者自定义修改的分区期望大小太大了
   5. 上表的数值单位统一是 **KiB**。BM1688/CV186AH/CV84X6 的刷机包分区表按 sector 输出，换算由工具完成，配置侧不需要改成扇区数
5. 保存`socbak.sh`文件，继续执行`bash socbak.sh`命令，开始打包

### 固定分区大小功能

> 注意：此功能会固定预分配的分区大小，可能会导致打包失败。

1. 参考上一小节 `修改emmc分区布局功能` ，修改 `socbak.sh` 脚本文件，指定各个分区的大小
2. 在执行 `bash socbak.sh` 时，增加 `SOC_BAK_FIXED_SIZE=1` 参数，例如: `bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_SIZE=1`。

### 对ota_update工具的兼容性说明

#### OTA时不需要保留最后一个分区

在不需要保留最后一个分区的情况下，配置 `SOC_BAK_ALL_IN_ONE=1` 即可。

#### OTA时需要保留最后一个分区（V1.2.0开始支持）

需要额外配置 `SOC_BAK_FIXED_DATA_START=1` 示例： `bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_DATA_START=1` ，这样可以固定最后一个分区的起始位置。

原理说明：socbak打包时会自动用ROOTFS_RW的空间去弥补其他分区扩大的空间，确保最后一个分区的起始点不动。从而确保二次打包后的刷机包在使用ota_update做OTA升级时可以保留最后一个分区。

注意事项：

1. `SOC_BAK_FIXED_DATA_START`模式会确保如下两个配置相同，所以在配置不变的情况下，只要顺利打包成功，则生成的所有刷机包DATA分区起始点都一致：
   1. socbak脚本中配置的分区参数所生成的DATA分区起始点
   2. socbak脚本更具当前设备内容重新生成的刷机包的DATA分区起始点
2. 工具会在新的刷机包完整分区表生成后检查其与当前设备的DATA分区起始点是否相同，如果不同，会报警`WARRNING: SOC_BAK_FIXED_DATA_START mode, check last part start [NEW: XXX] != [DEV: XXX]`，但是不会中断打包过程。如果看到这个报警，代表当前生成的刷机包无法通过ota_update做OTA升级时保留最后一个分区。请使用者重点关注一下打包的设备是否与socbak脚本中设置的分区参数对齐。


## 示例视频

### 完整打包做包功能

https://github.com/user-attachments/assets/97f754e1-c575-4859-aaf8-8e9d60daeba9

### 修改emmc分区布局功能

https://github.com/user-attachments/assets/9791409c-a57e-4c87-96c4-7c11da022e0a
