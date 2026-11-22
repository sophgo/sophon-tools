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

### SE9 / SE13 的 local_update 打包模式（V1.6.0 起）

> 仅适用于 CV 系（BM1688 / CV186AH / CV84X6，即 SE9 16 / SE9 8 / SE13）的 all-in-one 包。

``` bash
bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1
```

适用场景：目标设备用 SDK 自带的 `local_update.sh` 做远程/本地升级。该程序把升级指令写进
MISC（p3），写盘前调用 `scripts/check_partition_start_sector.sh` 逐项比较源机与包内
`partition32G_sector.xml` 的 **DATA、MISC、ROOTFS 起点**，任何一项不同就拒绝升级
（`OTA upgrade rejected to prevent data corruption`）。所以打包时必须把源机的 GPT 前缀原样搬进新包。

这个模式冻结的与允许变化的分区字段：

| 分区 | 起点 | 长度 |
| --- | --- | --- |
| BOOT / RECOVERY / MISC | 冻结（= 源机） | 冻结（= 源机） |
| ROOTFS | 冻结（= 源机） | **随内容变化** |
| ROOTFS_RW | **= 新 ROOTFS 末尾** | **= DATA 起点 − 新 ROOTFS_RW 起点** |
| DATA | 冻结（= 源机） | **随内容变化** |

也就是说，整个包里只有四个数值会随内容变化：ROOTFS 长度、ROOTFS_RW 起点、ROOTFS_RW 长度、
DATA 长度。其余全部照抄源机 GPT。

要点：

* 源机 GPT 是**只读**读出来的（`binTools/sgdisk` 的 `-p` / `-i`，不改写设备），
  逐项取分区号、标签、起点、长度，单位为 512 B 扇区。开关打开后立即读取并校验，
  布局不对就当场退出，不会等到备份几十分钟之后才失败。
* 用标签**和**分区号双重辨认，要求恰好是
  `BOOT / RECOVERY / MISC / ROOTFS / ROOTFS_RW / DATA` 这六个分区、编号为 **p1–p6**、
  从 LBA 8192 起首尾相接。编号是硬约束：`local_update.sh` 把升级指令 `dd` 到
  `/dev/mmcblk0p3`（MISC），SDK 的检查脚本也按 p1–p6 映射设备节点，编号错位就会写错分区。
  SE7（BM1684/BM1684X）或没有 MISC/ROOTFS_RW 的布局直接拒绝。
* 不支持 **USB** 包：CV 的 USB 打包分支会给每个 `.gz`（含 `gpt.gz`）套一层 64 字节
  CIMG 头，而 SDK 的 `local_update` / `ota_update` 都是直接 `gzip -cd gpt.gz`，读不了。
  开关与 USB 同时使用时在动手前就报错退出，请用 `sdcard` 或 `tftp`。
* 源机当前的 DATA 长度通常已经扩到盘尾，**不**作为打包需要的最小 DATA 镜像长度；
  DATA 长度按内容重新计算，容量沿用原打包策略，只在其装不下时抬高到刚好够用，上限是源盘。
* ROOTFS 变长时 ROOTFS_RW 要同时缩短，并保留原有的 **200 MiB** 余量
  （与 `SOC_BAK_FIXED_DATA_START` 同一套补偿规则）。余量不够就非零退出。
* 固定区（BOOT / RECOVERY）的镜像按源机容量**精确**制做（长度不是 4 KiB 倍数时也补齐），
  内容装不下也非零退出 —— 不会只把 XML 里的数字改小、也不会静默截断镜像。
  灌内容失败（tar 短写）会直接中断打包，不会留下"尺寸对、内容残缺"的包。
* 与 `SOC_BAK_FIXED_SIZE` / `SOC_BAK_FIXED_DATA_START` 互斥，并且要求同时开启
  `SOC_BAK_ALL_IN_ONE`；任一条件不满足都明确报错退出。
* 打包结束前会做四项交叉核对，任一项不符就非零退出、并把包移出成品目录
  （改名为 `<包>.rejected`，便于排查但不会被误当成交付物）：
  ① 分区表 XML 与规划逐项相同；② `gpt.gz` 解出的主 GPT 与规划逐项相同；
  ③ **逐个计划分区**检查 `boot_emmc-<分区>.cmd` 是否存在、`mmc write` 的起点是否等于
  分区起点、写入范围是否都在本分区内、引用的数据块是否存在且非空
  （镜像比分区短是合法的缩小文件系统，允许）；
  ④ DATA/MISC/ROOTFS 起点与源机一致。
* 逐项核对比 SDK 更严：SDK 只比 DATA/MISC/ROOTFS 三个起点，本模式连 BOOT/RECOVERY/MISC 的
  **长度**一起比，所以「起点全对但冻结区长度被改坏」的包会被拦住（前次 SE9 旧包就是
  MISC 从 532480 挪到 552960、ROOTFS 从 552960 挪到 573440，会被拒绝）。
* GPT 解析用 bash 内置算术 + `od`，**不依赖 awk**：板上 `/usr/bin/awk` 是 mawk 1.3.4，
  没有 GNU awk 的 `strtonum`。
* 可复跑的回归：`bash source/psocbak/tests/local_update_layout.sh`（仓库根目录），
  覆盖参数入口、源表只读解析、GPT 解析在 mawk 下的可用性、四个自由度的组合、余量边界、
  DATA 越界、非法源布局、旧包反例、冻结区镜像尺寸与"内容装不下"、缺脚本/缺数据块/越界等
  最终把关用例，以及**从正常打包入口一路跑到成品**（真实 `socbak.sh`，容器内模拟设备信号）；
  后者是唯一能发现"变量名把生成路径和包内文件名搞混"这类问题的用例。
  正常入口测试使用 Docker 的 `ubuntu:22.04` 镜像。用 `SOCBAK_TEST_AARCH64_ROOT` 指定带 glibc 的 ARM64 sysroot；在 x86 主机上需已注册 ARM64 用户态模拟器。缺少 Docker 或未提供 sysroot 时跳过该节。

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
