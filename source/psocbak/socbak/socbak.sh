#!/bin/bash

# env SOC_BAK_ALL_IN_ONE!="" for socbak allinone
# env SOC_BAK_FIXED_SIZE!="" for socbak fixed size mode
# env SOC_BAK_FIXED_DATA_START!="" for socbak fixed data partition start mode
# env SOC_BAK_FSTYPE=ext4|f2fs for the filesystem of the generated images (default ext4)

# 配置日志能力
PWD="$(dirname "$(readlink -f "$0")")"
TGZ_FILES_PATH=${PWD}
LOGFILE="$(readlink -f "${BASH_SOURCE[0]}").log"
rm -f $LOGFILE*
exec > >(tee -a "$LOGFILE") 2>&1

echo "VERSION: v1.3.3"
date '+%Y-%m-%d %H:%M:%S'

export SOC_BAK_ALL_IN_ONE=${SOC_BAK_ALL_IN_ONE:-}
export SOC_BAK_FIXED_SIZE=${SOC_BAK_FIXED_SIZE:-}
export SOC_BAK_FIXED_DATA_START=${SOC_BAK_FIXED_DATA_START:-}
export SOC_BAK_FSTYPE=${SOC_BAK_FSTYPE:-ext4}

for arg in "$@"; do
    case $arg in
        SOC_BAK_ALL_IN_ONE=*)
            export SOC_BAK_ALL_IN_ONE="${arg#*=}"
            shift
            ;;
		SOC_BAK_FIXED_SIZE=*)
            export SOC_BAK_FIXED_SIZE="${arg#*=}"
            shift
            ;;
		SOC_BAK_FIXED_DATA_START=*)
            export SOC_BAK_FIXED_DATA_START="${arg#*=}"
            shift
            ;;
		SOC_BAK_FSTYPE=*)
            export SOC_BAK_FSTYPE="${arg#*=}"
            shift
            ;;
    esac
done

case "${SOC_BAK_FSTYPE}" in
	ext4|f2fs) ;;
	*)
		echo "ERROR: SOC_BAK_FSTYPE=${SOC_BAK_FSTYPE} is not supported (expect ext4 or f2fs)"
		exit 1
		;;
esac

if [[ "${SOC_BAK_FIXED_SIZE}" != "" ]] && [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	echo "ERROR: SOC_BAK_FIXED_SIZE and SOC_BAK_FIXED_DATA_START cannot be enabled at the same time"
	exit 1
fi
if [[ "${SOC_BAK_ALL_IN_ONE}" == "" ]] && [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	echo "ERROR: SOC_BAK_ALL_IN_ONE cannot be closed after SOC_BAK_FIXED_DATA_START is opened"
	exit 1
fi

# These parameters are used to exclude irrelevant files
# and directories in the context of repackaging mode.
# Users can add custom irrelevant files and directories
# in the format of ROOTFS_EXCLUDE_FLAGS_INT to the
# ROOTFS_EXCLUDE_FLAGS_USER parameter.
ROOTFS_EXCLUDE_FLAGS_INT=' --exclude=./var/log/* --exclude=./media/* --exclude=./sys/* --exclude=./proc/* --exclude=./dev/* --exclude=./factory/* --exclude=./run/udev/* --exclude=./run/user/* --exclude=./socrepack --exclude=./root/.boot/*'
ROOTFS_EXCLUDE_FLAGS_USER='  '
ROOTFS_EXCLUDE_FLAGS_RUN=" ${ROOTFS_EXCLUDE_FLAGS_INT} ${ROOTFS_EXCLUDE_FLAGS_USER} "
ROOTFS_EXCLUDE_FLAGS=' '
ROOTFS_INCLUDE_PATHS=' ./var/log/nginx ./var/log/redis ./var/log/mosquitto ./var/log/mysql'

declare -A -g PART_EXCLUDE_FLAGS
PART_EXCLUDE_FLAGS["boot"]=' --exclude=./spi_flash.bin.socBakNew --exclude=./u-boot.env '
# socrepack 为 socbak 自身产物目录：当外置存储缺省、产物直接落在 /data/socrepack 时，
# 若不排除会把正在生成的 *.tgz 打进 data 包（自包含递归）。rootfs 侧已有同样排除。
PART_EXCLUDE_FLAGS["data"]=' --exclude=./socrepack '
# /opt/applications 常为外置数据盘(NVMe/SATA/USB)挂载点，不属于母盘环境。
# 不排除时 tar 递归进入挂载点，会把数据盘内容打进 opt 分区镜像导致 sparse 空间写满
# （与 rootfs 排除 ./media/* 同理）。
PART_EXCLUDE_FLAGS["opt"]=' --exclude=./applications/* '

# These parameters define several generated files and
# their default sizes for repackaging. Users can modify
# them according to their device specifications.
TGZ_FILES=(boot data opt system recovery rootfs)
# Here are the default sizes for each partition
declare -A -g TGZ_FILES_SIZE
TGZ_FILES_SIZE=(["boot"]=131072 ["recovery"]=3145728 ["rootfs"]=2621440 ["opt"]=2097152 ["system"]=2097152 ["data"]=4194304)
declare -A -g TGZ_FILES_SIZE_BM1688
TGZ_FILES_SIZE_BM1688=(["boot"]=131072 ["recovery"]=131072 ["rootfs"]=3145728 ["data"]=4194304)
# for cv84x6（CV84X2，SDK 标识 cv84x6），与 bm1688/cv186ah 同属 CV 系共用 eMMC 布局，
# 分区大小默认对齐 bm1688，独立常量便于按 CV84X2 真机实测微调。
declare -A -g TGZ_FILES_SIZE_CV84X6
TGZ_FILES_SIZE_CV84X6=(["boot"]=131072 ["recovery"]=131072 ["rootfs"]=3145728 ["data"]=4194304)
# The increased size of each partition compared to the original partition table
ROOTFS_RW_SIZE=$((6291456))
ROOTFS_RW_SIZE_BM1688=$((9291456))
ROOTFS_RW_SIZE_CV84X6=$((9291456))
TGZ_ALL_SIZE=$((100*1024))
EMMC_ALL_SIZE=20971520
EMMC_MAX_SIZE=30000000
TAR_SIZE=0
SOCBAK_PARTITION_FILE=partition32G.xml
BM1684_SOC_VERSION=0
NEED_BAK_FLASH=1
SOC_NAME=""
PIGZ_GZIP_COM=""
export GZIP=-1
export PIGZ=-1
PARTITIONS_SIZE_NO_DATA_KB=$((0))

# SOC_BAK_FSTYPE=f2fs 时 format="2" 分区（RECOVERY/ROOTFS/ROOTFS_RW/OPT/SYSTEM/DATA）
# 生成 f2fs 镜像；缺省 ext4，与历史版本行为一致。BOOT(FAT32) 与 MISC(raw) 不受影响。
# f2fs mkfs 特性与 SDK 打包链（bm_make_package_sectors.sh）保持一致：面向异常断电 +
# 可能跑 MySQL 等重型数据库的边缘场景，开 extra_attr(前置) / inode_checksum(撕裂 inode 可检测)
# / sb_checksum(撕裂超级块可检测) / lost_found(孤立 inode 收进 lost+found 而非丢弃) /
# inode_crtime(掉电取证)。内核未编译的特性（compression/encrypt/verity/casefold）不开。
F2FS_MKFS_FEATURES="extra_attr,inode_checksum,sb_checksum,lost_found,inode_crtime"
F2FS_MKFS_OPTS="-O ${F2FS_MKFS_FEATURES}"
# f2fs 尺寸只能在 mkfs 时一次定死（不能在线扩、也没有 resize2fs -M 那样的离线收缩），
# 所以先按内容实算一个起点，再用探测到的真实可写容量校正，不够就按段倍增。
F2FS_SEG_KB=2048
F2FS_MKFS_MIN_KB=65536
F2FS_SIZE_SLACK_PCT=115
F2FS_EST_USABLE_PCT=75
KB_BYTES=1024

if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	echo "INFO: SOC_BAK_FIXED_DATA_START open, some ROOTFS_RW space will be automatically allocated to ROOTFS_RO"
fi

chmod -R +x ${TGZ_FILES_PATH}/binTools
export PATH="${TGZ_FILES_PATH}/binTools":$PATH
# find ./ -type f | grep -vE "md5.txt|\.log|output|sparse|\.bin|\.tgz|socbak.sh" | xargs md5sum > socbak_md5.txt
pushd "${TGZ_FILES_PATH}"
md5sum -c "${TGZ_FILES_PATH}/socbak_md5.txt"
if [[ "$?" != "0" ]]; then
	echo "ERROR: file md5 check error!"
	exit -1
fi
rm -rf ./*.xml ./*.bin ./*.tar ./*.tgz ./*.gz output sparse-*
popd

ALL_IN_ONE_FLAG=""
ALL_IN_ONE_SCRIPT=""
if [[ "$SOC_BAK_ALL_IN_ONE" != "" ]]; then
	ALL_IN_ONE_FLAG="1"
	echo "INFO: open all in one mode for ${ALL_IN_ONE_FLAG}"
fi

rm -f /home/*/.bash_history 2>/dev/null
rm -f /root/.bash_history 2>/dev/null

if type pigz >/dev/null 2>&1 ; then
	PIGZ_GZIP_COM="pigz"
	echo "INFO: find pigz"
else
	PIGZ_GZIP_COM="gzip"
	echo "INFO: not find pigz, multi-thread acceleration cannot be used, please install pigz and try again or continue to use gzip"
fi
echo "INFO: PIGZ_GZIP_COM:${PIGZ_GZIP_COM}"

socbak_cleanup() {
	echo -e "\nINFO: Received a kill signal. Cleaning up..."
	systemctl disable resize-helper.service
	umount ${TGZ_FILES_PATH}/sparse-path* &>/dev/null
}
# 注意：不能挂 ERR。tar 打包运行中的根文件系统时，"File removed before we read it"
# 等瞬态警告会使 tar 以 1 退出（属预期、可容忍，追加 pass 本就带 --ignore-failed-read），
# ERR trap 会把这类警告当成致命错误：cleanup 提前退出且 exit 0，备份被静默截断还报成功
# （CV84X2 真机实测踩坑）。关键步骤失败由各处的 "$?" 显式检查处理。
# 退出码规范（P2-5）：cleanup 本身不 exit 0（原实现会吞掉脚本失败退出码）；
# 信号 trap 单独显式 exit 130 结束，正常/失败路径退出码由 EXIT trap 原样保留。
trap 'socbak_cleanup; exit 130' SIGHUP SIGINT SIGQUIT SIGTERM
trap socbak_cleanup EXIT

SOCBAK_GET_TAR_SIZE_KB=0
socbak_get_tar_size() {
	echo "INFO: get tar $1 files size..."
	pushd ${TGZ_FILES_PATH}
	SOCBAK_GET_TAR_SIZE_KB=$(tar -I ${PIGZ_GZIP_COM} -tvf $1 --totals 2>&1 | tail -n 1 | awk -F':' '{printf $2}' | awk -F' ' '{printf "%.0f\n", $1/1024}')
	echo "WARNING: $1 files size is ${SOCBAK_GET_TAR_SIZE_KB}"
	popd
}

if ! [[ "$TGZ_FILES_PATH" =~ "/socrepack" ]]; then
	echo "ERROR: The current path($TGZ_FILES_PATH) is not \"/socrepack\", please check it"
	exit 1
fi
echo "INFO: The current path is \"/socrepack\""

FILESYSTEM=$(df -T . | tail -n 1 | awk '{print $2}')
if [[ "${FILESYSTEM}" != "ext4" ]]; then
	echo "WARNING: The current directory's file system ${FILESYSTEM} is not ext4, there may be some issues."
	echo "You can format the external storage to ext4 format according to the content at https://developer.sophgo.com/thread/758.html."
fi

if [[ "${FILESYSTEM}" == "vfat" ]] || [[ "${FILESYSTEM}" == "fat" ]]; then
    echo "ERROR: filesystem ${FILESYSTEM} is not supported to use socbak, please look at infomation above!"
    exit -1
fi

echo "INFO: get chip id ..."
if [[ "$(busybox devmem 0x50010000 2>/dev/null)" == "0x16860000" ]]; then
	SOC_NAME="bm1684x"
elif [[ "$(busybox devmem 0x50010000 2>/dev/null)" == "0x16840000" ]]; then
	SOC_NAME="bm1684"
fi
# cv84x6（CV84X2，SDK 标识 cv84x6）识别：/proc/device-tree/model 根 compatible 可能为通用
# "linux,dummy-virt"（或缺失），不能直接判。与 get_info 一致采用两级信号：
# 1) 首选 CPU part（MIDR 硬件直读）：Cortex-A55(0xd05) 仅 cv84x6（CV84X2），其余 SDK 芯片
#    （bm1684x/bm1684/bm1688/cv186ah）均为 Cortex-A53(0xd03)，天然分开；
# 2) 兜底 dts 信号：内核 dts 递归含 "cvitek,cv84x6-*" compatible。注意 /proc/device-tree 是
#    指向 /sys/firmware/devicetree/base 的符号链接，find 必须加 -L 才会遍历（真机踩坑，
#    不加 -L 时 find 返回空导致 CV84X2 真机识别失败退出）。
# 检测到即按 CV 系（bm1688/cv186ah/cv84x6）路径打包。
CPU_PART=$(awk -F': ' '/CPU part/{print $2; exit}' /proc/cpuinfo 2>/dev/null)
if [[ "${SOC_NAME}" == "" ]] && [[ "${CPU_PART}" == "0xd05" || "${CPU_PART}" == "d05" ]]; then
	SOC_NAME="cv84x6"
fi
if [[ "${SOC_NAME}" == "" ]]; then
	if [[ "$(grep -ai "bm1688" '/proc/device-tree/model' 2>/dev/null | wc -l)" != "0" ]]; then
		SOC_NAME="bm1688"
	elif [[ "$(grep -ai "athena2" '/proc/device-tree/model' 2>/dev/null | wc -l)" != "0" ]]; then
		SOC_NAME="bm1688"
	fi
fi
if [[ "${SOC_NAME}" == "" ]] && [ -d /proc/device-tree ]; then
	if [ -n "$(find -L /proc/device-tree -name compatible -type f \
		-exec grep -laE "cvitek,cv84x6-" {} + 2>/dev/null)" ]; then
		SOC_NAME="cv84x6"
	fi
fi
if [[ "${SOC_NAME}" == "" ]]; then
	echo "ERROR: cannot get chip id!"
	exit -1
else
	echo "INFO: get chip id success!"
fi

# f2fs 镜像只在 CV 系（bm1688/cv186ah/cv84x6）打包脚本 script/bm1688/bm_make_package.sh 里
# 做了分派；bm1684/bm1684x 用的是另一份脚本，明确拒绝而不是产出一个"xml 写着 f2fs、
# 镜像其实是 ext4"的半成品。
if [[ "${SOC_BAK_FSTYPE}" == "f2fs" ]]; then
	if [[ "$SOC_NAME" == "bm1684x" ]] || [[ "$SOC_NAME" == "bm1684" ]]; then
		echo "ERROR: SOC_BAK_FSTYPE=f2fs is not supported on ${SOC_NAME}"
		exit 1
	fi
	# 工具来自 binTools（aarch64 全静态 f2fs-tools 1.16.0）。缺了就在这里报错，
	# 否则会等到生成镜像阶段才以 "command not found" 的形式炸掉，前面几十分钟的备份白做。
	for _f2fs_tool in mkfs.f2fs sload.f2fs fsck.f2fs dump.f2fs; do
		if ! command -v "${_f2fs_tool}" >/dev/null 2>&1; then
			echo "ERROR: SOC_BAK_FSTYPE=f2fs needs ${_f2fs_tool} (expected in ${TGZ_FILES_PATH}/binTools)"
			exit 1
		fi
	done
	# sload.f2fs 的 -P（preserve owner）是 1.15 才有的：没有它时属主只写根目录，
	# 其余条目全变成 root，备份出来就不是原系统了。
	if sload.f2fs -P 2>&1 | grep -q "invalid option"; then
		echo "ERROR: sload.f2fs $(command -v sload.f2fs) lacks -P (preserve owner), requires f2fs-tools >= 1.15"
		exit 1
	fi
fi

ROOTFS_EXCLUDE_FLAGS="${ROOTFS_EXCLUDE_FLAGS_RUN}"
for TGZ_FILE in "${TGZ_FILES[@]}"
do
	if [[ "$(lsblk | grep mmcblk0p | grep ${TGZ_FILE} | wc -l)" != "0" ]]; then
		echo "INFO: find ${TGZ_FILE} on emmc."
		ROOTFS_EXCLUDE_FLAGS="${ROOTFS_EXCLUDE_FLAGS} --exclude=./${TGZ_FILE}/* "
	elif [[ "${TGZ_FILE}" == "rootfs" ]] || [[ "${TGZ_FILE}" == "rootfs_rw" ]]; then
		echo "INFO: must bak ${TGZ_FILE} on emmc."
	else
		echo "INFO: not find ${TGZ_FILE} on emmc."
		unset TGZ_FILES_SIZE["${TGZ_FILE}"]
		TGZ_FILES=( ${TGZ_FILES[@]/${TGZ_FILE}} )
	fi
done
if [[ "$SOC_NAME" == "bm1684x" ]] || [[ "$SOC_NAME" == "bm1684" ]]; then
	have_system_of_mmc0=$(lsblk | grep mmcblk0p | grep system | wc -l)
	if [[ "$have_system_of_mmc0" == "1" ]]; then
		BM1684_SOC_VERSION=0
		NEED_BAK_FLASH=0
		ALL_IN_ONE_FLAG=""
		ALL_IN_ONE_SCRIPT=""
		echo "INFO: find /system dir, the version is 3.0.0 or lower, cannot suppot bakpack spi_flash and all in one mode"
		if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
			echo "ERROR: SOC_BAK_FIXED_DATA_START mode not support 3.0.0 or lower"
		fi
	elif [ -d "/opt" ]; then
		BM1684_SOC_VERSION=1
		NEED_BAK_FLASH=1
		ALL_IN_ONE_SCRIPT="${TGZ_FILES_PATH}/script/bm1684/"
		echo "INFO: find /opt dir, the version is V22.09.02 or higher"
	fi
elif [[ "$SOC_NAME" == "bm1688" ]] || [[ "$SOC_NAME" == "cv84x6" ]]; then
	NEED_BAK_FLASH=1
	if [[ "$SOC_NAME" == "cv84x6" ]]; then
		ROOTFS_RW_SIZE=${ROOTFS_RW_SIZE_CV84X6}
		TGZ_FILES_SIZE["boot"]=${TGZ_FILES_SIZE_CV84X6["boot"]}
		TGZ_FILES_SIZE["recovery"]=${TGZ_FILES_SIZE_CV84X6["recovery"]}
		TGZ_FILES_SIZE["rootfs"]=${TGZ_FILES_SIZE_CV84X6["rootfs"]}
		TGZ_FILES_SIZE["data"]=${TGZ_FILES_SIZE_CV84X6["data"]}
	else
		ROOTFS_RW_SIZE=${ROOTFS_RW_SIZE_BM1688}
		TGZ_FILES_SIZE["boot"]=${TGZ_FILES_SIZE_BM1688["boot"]}
		TGZ_FILES_SIZE["recovery"]=${TGZ_FILES_SIZE_BM1688["recovery"]}
		TGZ_FILES_SIZE["rootfs"]=${TGZ_FILES_SIZE_BM1688["rootfs"]}
		TGZ_FILES_SIZE["data"]=${TGZ_FILES_SIZE_BM1688["data"]}
	fi
	# bm1688/cv186ah/cv84x6 同属 CV 系，共用此打包脚本（含 cvitek raw2cimg 打包路径）
	ALL_IN_ONE_SCRIPT="${TGZ_FILES_PATH}/script/bm1688/"
fi

if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	for TGZ_FILE in "${TGZ_FILES[@]}"
	do
		if [[ "${TGZ_FILE}" != "data" ]]; then
			PARTITIONS_SIZE_NO_DATA_KB=$((${PARTITIONS_SIZE_NO_DATA_KB} + ${TGZ_FILES_SIZE["${TGZ_FILE}"]}))
		fi
	done
	PARTITIONS_SIZE_NO_DATA_KB=$((${PARTITIONS_SIZE_NO_DATA_KB} + ${ROOTFS_RW_SIZE}))
	echo "INFO: PARTITIONS_SIZE_NO_DATA_KB: ${PARTITIONS_SIZE_NO_DATA_KB} KiB"
fi

if [ "$NEED_BAK_FLASH" -eq 1 ]; then
	echo "INFO: bakpack spi_flash start"
	if [[ "$SOC_NAME" == "bm1684x" ]] || [[ "$SOC_NAME" == "bm1684" ]] || [ -f /boot/spi_flash.bin ]; then
		cp /boot/spi_flash.bin spi_flash.bin
		rm -rf fip.bin
		FLASH_OFFSET=0
		if [[ "$SOC_NAME" == "bm1684x" ]]; then
			echo "INFO: soc is bm1684x"
			FLASH_OFFSET=0
			if [[ "$(flash_update -d fip.bin -b 0x6000000 -o 0x30000 -l 0x170000 | grep "^read" | wc -l)" == "0" ]]; then
				echo "WARNING: bak fip.bin cannot read data"
				rm -rf fip.bin
			fi
		elif [[ "$SOC_NAME" == "bm1684" ]]; then
			echo "INFO: soc is bm1684"
			FLASH_OFFSET=1
			if [[ "$(flash_update -d fip.bin -b 0x6000000 -o 0x40000 -l 0x160000 | grep "^read" | wc -l)" == "0" ]]; then
				echo "WARNING: bak fip.bin cannot read data"
				rm -rf fip.bin
			fi
		else
			echo "ERROR: cannot support reg 0x50010000: ${chip_reg_flag}"
			exit 1
		fi
		rm -rf spi_flash_$SOC_NAME.bin
		if [[ "$(flash_update -d spi_flash_$SOC_NAME.bin -b 0x6000000 -o 0 -l 0x200000 | grep "^read" | wc -l)" == "0" ]]; then
			echo "WARNING: bak spi_flash_$SOC_NAME.bin cannot read data"
			rm -rf spi_flash_$SOC_NAME.bin
			rm -rf spi_flash.bin
		else
			dd if=spi_flash_$SOC_NAME.bin of=spi_flash.bin seek=$FLASH_OFFSET bs=4194304 conv=notrunc
			if [[ "$SOC_NAME" == "bm1684" ]]; then
				rm -rf spi_flash_bm1684x.bin
				dd if=spi_flash.bin of=spi_flash_bm1684x.bin skip=0 bs=4194304 count=1
			else
				rm -rf spi_flash_bm1684.bin
				dd if=spi_flash.bin of=spi_flash_bm1684.bin skip=1 bs=4194304 count=1
			fi
			cp spi_flash.bin /boot/spi_flash.bin.socBakNew
		fi
	elif [[ "$SOC_NAME" == "bm1688" ]] || [[ "$SOC_NAME" == "cv84x6" ]]; then
		dd if=/dev/mmcblk0boot0 of=${TGZ_FILES_PATH}/fip.bin bs=512 count=2048
		if [[ "$?" != "0" ]]; then
			echo "WARNING: bak fip.bin cannot read data"
			rm -rf fip.bin
		fi
	fi
	echo "INFO: bakpack spi_flash end"
fi

socbak_resize_min_size_kb="0"
function resize_min_size()
{
	declare -g socbak_resize_min_size_kb
	echo "INFO: resize img file($1) start at ${2}M, step is ${3}M, max count is $4"
	part_size_M=$(($2))
	count=0
	while true
	do
		part_size_M=$(($part_size_M + $3))
		echo "INFO: attempt partition($1) size ${part_size_M}M ..."
		run_log=$(resize2fs $1 "${part_size_M}M" -f &>/dev/stdout)
		e2fsck -fy $1 1>/dev/null
		if [[ "$(echo $run_log | grep -E "No space left on device|Not enough space to build proposed filesystem" | wc -l)" == "0" ]]; then
			break
		fi
		count=$(($count + 1))
		if [ $count -gt $4 ]; then
			echo "ERROR: cannot find min size, count($count). resize2fs ret: "
			echo "$run_log"
			socbak_cleanup
		fi
	done
	echo "INFO: partition($1) size ${part_size_M} M"
	socbak_resize_min_size_kb=$(($part_size_M * 1024))
	echo "INFO: partition $1 size $socbak_resize_min_size_kb KB"
}

# 把分区 $1 的内容 tar 到目录 $2：ext4 路径灌进镜像的挂载点，f2fs 路径灌进普通目录
# （f2fs 没有 mkfs.ext4 -d 的等价物，sload.f2fs 只从目录树填充）。
function socbak_spool_partition_content()
{
	local part="$1"
	local dest="$2"
	case $part in
		"rootfs")
			pushd /
			systemctl enable resize-helper.service
			tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read --numeric-owner -cpSf - ${ROOTFS_EXCLUDE_FLAGS} "./" | tar -xpSf - -C "$dest"
			if [[ "$?" != "0" ]]; then echo "ERROR: cp files $part error, exit."; socbak_cleanup; fi
			echo "INFO: add ext include files to rootfs..."
			tar --ignore-failed-read --numeric-owner -cvpSf - ${ROOTFS_INCLUDE_PATHS} | tar -xpSf - -C "$dest"
			systemctl disable resize-helper.service
			popd
		;;
		*)
			pushd /$part
			set +u
			EXT_FLAG="${PART_EXCLUDE_FLAGS["$part"]}"
			set -u
			tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read --numeric-owner -cpSf - ${EXT_FLAG} "./" | tar -xpSf - -C "$dest"
			if [[ "$?" != "0" ]]; then echo "ERROR: cp files $part error, exit."; socbak_cleanup; fi
			popd
		;;
	esac
}

# f2fs 镜像必须容纳的 4K 块：文件数据块 + 每个文件/目录/符号链接占 1 个 node 块
# （inode 本身就是一整块）+ 大文件要的间接 node，末尾再留 2048 块兜底。
function socbak_f2fs_content_kb()
{
	local spool="$1"
	local data_blocks node_entries indirect_blocks

	data_blocks=$(find "$spool" -type f -printf '%s\n' 2>/dev/null |
		awk '{s+=int(($1+4095)/4096)} END{print s+0}')
	node_entries=$(find "$spool" \( -type f -o -type d -o -type l \) 2>/dev/null | wc -l)
	indirect_blocks=$(( data_blocks / 1012 ))
	echo $(( (data_blocks + node_entries + indirect_blocks + 2048) * 4 ))
}

# 探测给定尺寸的 f2fs 镜像实际能写进多少 KB。用稀疏临时镜像：mkfs.f2fs 只写超级块与
# 元数据，探测开销可忽略。free_segment_count 里含 GC 保留段（rsvd_segment_count），
# sload 只能用两者的差值。
function socbak_f2fs_fillable_kb()
{
	local size_kb="$1"
	local probe_img="$TGZ_FILES_PATH/f2fs-probe-$$"
	local free_segs rsvd_segs

	rm -f "$probe_img"
	truncate -s $(( size_kb * KB_BYTES )) "$probe_img" || return 1
	mkfs.f2fs ${F2FS_MKFS_OPTS} -f "$probe_img" >/dev/null 2>&1 || return 1

	free_segs=$(dump.f2fs -d 1 "$probe_img" 2>/dev/null |
		awk '$1 == "free_segment_count" {print $NF}' | tr -d ']')
	rsvd_segs=$(dump.f2fs -d 1 "$probe_img" 2>/dev/null |
		awk '$1 == "rsvd_segment_count" {print $NF}' | tr -d ']')
	rm -f "$probe_img"

	case "${free_segs}" in ''|*[!0-9]*) return 1 ;; esac
	case "${rsvd_segs}" in ''|*[!0-9]*) return 1 ;; esac
	[ "${free_segs}" -gt "${rsvd_segs}" ] || return 1
	echo $(( (free_segs - rsvd_segs) * F2FS_SEG_KB ))
}

# f2fs 尺寸只能一次定死（不能在线扩、也没有离线收缩工具），所以按内容量给起点，
# 再用探测到的真实可写容量校正，不够就按段倍增，上限为该分区能给到的尺寸。
function socbak_f2fs_size_kb()
{
	local spool="$1" max_kb="$2"
	local need_kb size_kb fillable_kb

	need_kb=$(socbak_f2fs_content_kb "$spool")
	need_kb=$(( need_kb * F2FS_SIZE_SLACK_PCT / 100 ))

	size_kb=$(( need_kb * 100 / F2FS_EST_USABLE_PCT ))
	size_kb=$(( (size_kb + F2FS_SEG_KB - 1) / F2FS_SEG_KB * F2FS_SEG_KB ))
	if [ "${size_kb}" -lt "${F2FS_MKFS_MIN_KB}" ]; then
		size_kb=${F2FS_MKFS_MIN_KB}
	fi
	if [ "${size_kb}" -gt "${max_kb}" ]; then
		size_kb=${max_kb}
	fi

	# 向上：探测说这个尺寸装不下就按段倍增（起点估小的情况）
	while true; do
		fillable_kb=$(socbak_f2fs_fillable_kb "${size_kb}") || fillable_kb=""
		if [ -n "${fillable_kb}" ] && [ "${fillable_kb}" -ge "${need_kb}" ]; then
			break
		fi
		if [ "${size_kb}" -ge "${max_kb}" ]; then
			break
		fi
		size_kb=$(( size_kb * 2 ))
		if [ "${size_kb}" -gt "${max_kb}" ]; then
			size_kb=${max_kb}
		fi
	done

	# 向下：上面那个起点偏保守（宁可大不可小），而 f2fs 又不能收缩，多出来的部分就是
	# 实打实多写的 flash。探测给出的可写容量是准的，二分逼近仍然装得下的最小尺寸，
	# 让它贴近 ext4 路径 resize2fs -M 的效果。下限按 f2fs 元数据开销留 2% 余量。
	lo=$(( need_kb * 100 / 98 ))
	lo=$(( (lo + F2FS_SEG_KB - 1) / F2FS_SEG_KB * F2FS_SEG_KB ))
	if [ "${lo}" -lt "${F2FS_MKFS_MIN_KB}" ]; then
		lo=${F2FS_MKFS_MIN_KB}
	fi
	while [ "${lo}" -lt "${size_kb}" ]; do
		mid=$(( (lo + size_kb) / 2 ))
		mid=$(( (mid + F2FS_SEG_KB - 1) / F2FS_SEG_KB * F2FS_SEG_KB ))
		if [ "${mid}" -ge "${size_kb}" ]; then
			break
		fi
		fillable_kb=$(socbak_f2fs_fillable_kb "${mid}") || fillable_kb=""
		if [ -n "${fillable_kb}" ] && [ "${fillable_kb}" -ge "${need_kb}" ]; then
			size_kb=${mid}
		else
			lo=$(( mid + F2FS_SEG_KB ))
		fi
	done

	echo "INFO: f2fs content need ${need_kb} KB, image size ${size_kb} KB (max ${max_kb} KB)" >&2
	echo "${size_kb}"
}

# f2fs 版的分区镜像生成：内容先落到普通目录，再 mkfs.f2fs + sload.f2fs 灌进镜像。
# 尺寸算小了只能整个重建（翻倍重试），所以先探测再落盘；sload 也会在写不下时失败。
function socbak_gen_partition_subimg_f2fs()
{
	local part="$1"
	local size_max_bytes="$2"
	local spool="$TGZ_FILES_PATH/sparse-path-$part"
	local img="sparse-file-$part"
	local size_max_kb=$(( size_max_bytes / KB_BYTES ))
	local size_kb _sload_log _sload_rc _img_ok

	echo "INFO: gen partition($part) f2fs img file, max $(( size_max_bytes )) B"
	rm -rf "$spool"
	mkdir -p "$spool"
	socbak_spool_partition_content "$part" "$spool"

	# sload.f2fs 1.16.0 不还原特殊文件（设备节点/FIFO/socket），ext4 路径的 tar -p 是还原的。
	# 静默丢弃等于备份悄悄少了东西，这里必须显式告警。
	local _special_files
	_special_files=$(find "$spool" \( -type b -o -type c -o -type p -o -type s \) 2>/dev/null | wc -l)
	if [ "${_special_files}" != "0" ]; then
		echo "WARNING: $part has ${_special_files} special file(s) (device node/FIFO/socket)."
		echo "WARNING: sload.f2fs does not restore them, so they will be MISSING from the f2fs image (ext4 mode keeps them)."
		find "$spool" \( -type b -o -type c -o -type p -o -type s \) 2>/dev/null | head -10 | sed 's/^/WARNING:   /'
	fi

	size_kb=$(socbak_f2fs_size_kb "$spool" "$size_max_kb")

	while true; do
		rm -f "$img"
		truncate -s $(( size_kb * KB_BYTES )) "$img"
		if ! mkfs.f2fs ${F2FS_MKFS_OPTS} -f "$img"; then
			echo "ERROR: mkfs.f2fs $part error, exit."
			rm -f "$img"
			socbak_cleanup
			exit 1
		fi
		_sload_log="$TGZ_FILES_PATH/f2fs-sload-$part.log"
		_sload_rc=1
		sload.f2fs -P -f "$spool" "$img" >"$_sload_log" 2>&1; _sload_rc=$?
		_img_ok=0
		if [ "${_sload_rc}" = "0" ]; then
			_img_ok=1
		elif [ "${_sload_rc}" = "1" ] && ! grep -q "Can't find free block" "$_sload_log"; then
			# sload.f2fs 1.16.0 在 inode_checksum 下算错 inode 校验和：它收尾自带的 [FSCK]
			# 检查会报 "other corrupted bugs [Fail]" 并返回 1，但文件数据已完整写入。
			# 跑 fsck.f2fs -f 修正校验和即可（判据：连跑两次都干净）。
			# 真正的失败（镜像放不下）返回 255 且日志含 "Can't find free block"，不会被这里吞掉。
			fsck.f2fs -f "$img" >/dev/null 2>&1
			if fsck.f2fs -f "$img" >/dev/null 2>&1; then
				_img_ok=1
			fi
		fi
		if [ "${_img_ok}" = "1" ]; then
			break
		fi
		if [ "${size_kb}" -ge "${size_max_kb}" ]; then
			echo "ERROR: f2fs image for $part does not fit in ${size_max_kb} KB (sload rc=${_sload_rc})"
			# sload 的进度条会刷屏，只留真正的错误行
			grep -v "Free segments" "$_sload_log" | tail -n 10
			rm -f "$img"
			socbak_cleanup
			exit 1
		fi
		size_kb=$(( size_kb * 2 ))
		if [ "${size_kb}" -gt "${size_max_kb}" ]; then
			size_kb=${size_max_kb}
		fi
		echo "WARNING: f2fs image for $part too small, retry with ${size_kb} KB"
	done
	rm -f "$_sload_log"

	# 交付前定稿：修一遍再验一遍，两次都干净才算数（fsck.f2fs 的退出码即结论）。
	fsck.f2fs -f "$img" >/dev/null 2>&1
	if ! fsck.f2fs -f "$img" >/dev/null 2>&1; then
		echo "ERROR: fsck.f2fs on $part image failed, exit."
		rm -f "$img"
		socbak_cleanup
		exit 1
	fi

	rm -rf "$spool"
	TGZ_FILES_SIZE["$part"]=$size_kb
	echo "INFO: partition $part size is : ${TGZ_FILES_SIZE["$part"]} KB"
}

function socbak_gen_partition_subimg()
{
	declare -g partition_subimg_size_kb
	echo "INFO: gen partition($1) to img file"
	umount ./sparse-path* &>/dev/null
	rm ./sparse-file* &>/dev/null
	rm ./sparse-path* -rf &>/dev/null
	if [[ "$3" == "f2fs" ]]; then
		socbak_gen_partition_subimg_f2fs "$1" "$2"
		return
	fi
	echo "INFO: creat partition($1) size: $((${2})) B ..."
	dd if=/dev/zero of="sparse-file-$1" bs=$((1024 * 4)) count=$(($2 / 1024 / 4)) conv=notrunc status=progress
	if [[ "$?" != "0" ]]; then echo "ERROR: dd $1 error, exit."; socbak_cleanup; fi
	if [[ "$3" == "fat" ]]; then
		mkfs.fat "sparse-file-$1"
		if [[ "$?" != "0" ]]; then echo "ERROR: mkfs.fat $1 error, exit."; socbak_cleanup; fi
	else
		mkfs.ext4 -b 4096 -i 16384 "sparse-file-$1"
		if [[ "$?" != "0" ]]; then echo "ERROR: mkfs.ext4 $1 error, exit."; socbak_cleanup; fi
	fi
	mkdir "sparse-path-$1"
	mount "sparse-file-$1" "sparse-path-$1"
	if [[ "$?" != "0" ]]; then echo "ERROR: mount(1) $1 error, exit."; socbak_cleanup; fi
	socbak_spool_partition_content "$1" "$TGZ_FILES_PATH/sparse-path-$1"
	#e4defrag "sparse-path-$1"
	#if [[ "$?" != "0" ]]; then echo "ERROR: e4defrag $1 error, exit."; socbak_cleanup; fi
	umount "sparse-path-$1"
	if [[ "$?" != "0" ]]; then echo "ERROR: umount $1 error, exit."; socbak_cleanup; fi
	size_kb="0"
	if [[ "$3" == "ext4" ]]; then
		e2fsck -fy "sparse-file-$1"
		if [[ "$?" != "0" ]]; then echo "ERROR: e2fsck $1 error, exit."; socbak_cleanup; fi
		resize2fs "sparse-file-$1"
		if [[ "$?" != "0" ]]; then echo "ERROR: resize2fs $1 error, exit."; socbak_cleanup; fi
		size_step=$(($2 / 1024 / 1024 / 20))
		step_num=20
		if [ $size_step -lt 10 ]; then
			size_step=10
		fi
		if [ $size_step -gt 1000 ]; then
			size_step=1000
			step_num=$(($2 / 1024 / 1024 / $size_step))
		fi
		if [[ "$SOC_BAK_FIXED_SIZE" != "" ]]; then
			echo "INFO: fixed size"
			size_step=0
			step_num=0
		fi
		resize_min_size "$TGZ_FILES_PATH/sparse-file-$1" $((${TGZ_FILES_SIZE["${1}"]} / 1024)) ${size_step} ${step_num}
		TGZ_FILES_SIZE["${1}"]=$socbak_resize_min_size_kb
	elif [[ "$3" == "fat" ]]; then
		TGZ_FILES_SIZE["${1}"]=$(( $2 / 1024 ))
	fi
	echo "INFO: partition $1 size is : ${TGZ_FILES_SIZE["${1}"]} KB"
	tune2fs -l "sparse-file-$1"
	mount "sparse-file-$1" "sparse-path-$1"
	if [[ "$?" != "0" ]]; then echo "ERROR: mount(2) $1 error, exit."; socbak_cleanup; fi
	echo "INFO: print sparse-file-$1 files:"
	ls "sparse-path-$1" -lah
	umount "sparse-path-$1"
	if [[ "$3" == "ext4" ]]; then
		e2fsck -fy "sparse-file-$1"
	fi
	rm -rf "sparse-path-$1"
}

if [[ "${SOC_BAK_NOT_TGZ}" == "1" ]]; then
	exit 0
fi

if [[ "${ALL_IN_ONE_FLAG}" != "" ]] && [[ "${ALL_IN_ONE_SCRIPT}" != "" ]]; then
	pushd $TGZ_FILES_PATH
	echo "INFO: start all in one, use script path: ${ALL_IN_ONE_SCRIPT}"
	rm output -rf &>/dev/null
	mkdir output
	for TGZ_FILE in "${TGZ_FILES[@]}"
	do
		part_size_max=0
		# BOOT 是 FAT32（下面的 "boot" 分支覆盖），其余分区按 SOC_BAK_FSTYPE 走 ext4/f2fs
		partition_format="${SOC_BAK_FSTYPE}"
		ext_part=""
		case $TGZ_FILE in
			"rootfs")
				ext_part=$(echo "${ROOTFS_EXCLUDE_FLAGS}" | sed 's|=./|=/|g')
				part_size_max="$(du -sb / ${ext_part} | awk '{print $1}')"
				part_size_max=$(($part_size_max * 2))
				part_use_rw=$(df -B1 -l /media/root-rw | grep " /media/root-rw\$" | awk -F' ' '{print $3}')
				part_use_ro=$(df -B1 -l /media/root-ro | grep " /media/root-ro\$" | awk -F' ' '{print $3}')
				part_use=$(($part_use_rw + $part_use_ro))
			;;
			"boot")
				part_size_max=$((${TGZ_FILES_SIZE["${TGZ_FILE}"]} * 1024))
				partition_format="fat"
				part_use=$(df -B1 -l /${TGZ_FILE} | grep " /${TGZ_FILE}\$" | awk -F' ' '{print $3}')
				if [[ "$SOC_BAK_FIXED_SIZE" != "" ]]; then
					# When the partition size is fixed, non-ext4 partitions are considered to have no used space
					part_use=$((0))
				fi
			;;
			*)
				set +u
				ext_part=$(echo "${PART_EXCLUDE_FLAGS["$TGZ_FILE"]}" | sed "s|=./|=/${TGZ_FILE}/|g")
				set -u
				part_size_max="$(du -sb /${TGZ_FILE} ${ext_part} | awk '{print $1}')"
				part_size_max=$(($part_size_max * 2))
				part_use=$(df -B1 -l /${TGZ_FILE} | grep " /${TGZ_FILE}\$" | awk -F' ' '{print $3}')
			;;
		esac
		part_use=$(($part_use * 3))
		if [ $part_size_max -gt $part_use ]; then
			part_size_max=${part_use}
		fi
		fixsize=$(( ${TGZ_FILES_SIZE[$TGZ_FILE]} * 1024))
		if [ $part_size_max -lt $fixsize ]; then
			part_size_max=${fixsize}
		fi
		socbak_gen_partition_subimg "$TGZ_FILE" "$part_size_max" "$partition_format" 
		advmv -g "sparse-file-$TGZ_FILE" output
	done
	popd
else
	for TGZ_FILE in "${TGZ_FILES[@]}"
	do
		case $TGZ_FILE in
			"rootfs")
				pushd /
				echo "INFO: tar $TGZ_FILE flags : $ROOTFS_EXCLUDE_FLAGS ..."
				systemctl enable resize-helper.service
				rm -rf $TGZ_FILES_PATH/$TGZ_FILE.tar
				tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read --numeric-owner -capSf $TGZ_FILES_PATH/$TGZ_FILE.tar $ROOTFS_EXCLUDE_FLAGS "./"
				tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read -rapSf $TGZ_FILES_PATH/$TGZ_FILE.tar --numeric-owner $ROOTFS_INCLUDE_PATHS
				systemctl disable resize-helper.service
				echo "INFO: gzip tar file..."
				${PIGZ_GZIP_COM} -1 -c $TGZ_FILES_PATH/$TGZ_FILE.tar | dd of=$TGZ_FILES_PATH/$TGZ_FILE.tgz bs=4M status=progress
				rm -rf $TGZ_FILES_PATH/$TGZ_FILE.tar
				TAR_SIZE=$((512*1024))
				popd
				;;
			*)
				pushd /$TGZ_FILE
				echo "INFO: tar $TGZ_FILE ..."
				set +u
				EXT_FLAG="${PART_EXCLUDE_FLAGS["$TGZ_FILE"]}"
				set -u
				tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read -I ${PIGZ_GZIP_COM} -cpSf $TGZ_FILES_PATH/$TGZ_FILE.tgz --numeric-owner ${EXT_FLAG} "./"
				if [ $TGZ_FILE == "data" ]; then
					TAR_SIZE=$((512*1024))
				else
					TAR_SIZE=$((100*1024))
				fi
				popd
				;;
		esac
		if [[ "$SOC_BAK_FIXED_SIZE" != "" ]]; then
			echo "INFO: fixed size"
		else
			socbak_get_tar_size ${TGZ_FILE}.tgz
			TAR_SIZE_AUTO=$(( ${SOCBAK_GET_TAR_SIZE_KB} / 8 ))
			if [ $TAR_SIZE_AUTO -gt $TAR_SIZE ]; then
				TAR_SIZE=$(($TAR_SIZE_AUTO))
			fi
			TAR_SIZE=$((${SOCBAK_GET_TAR_SIZE_KB}+${TAR_SIZE}))
			echo "INFO: $TGZ_FILE : $TAR_SIZE KB"
			if [ $TAR_SIZE -gt ${TGZ_FILES_SIZE["$TGZ_FILE"]} ];
			then
				echo "INFO: need to expand $TGZ_FILE from ${TGZ_FILES_SIZE[$TGZ_FILE]} KB to $TAR_SIZE KB"
				TGZ_FILES_SIZE[$TGZ_FILE]=$TAR_SIZE
			fi
		fi
	done
fi

PARTITIONS_SIZE_NO_DATA_NEW_KB=$((0))
if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	echo "INFO: SOC_BAK_FIXED_DATA_START open, start change rootfs_rw size"
	for TGZ_FILE in "${TGZ_FILES[@]}"
	do
		if [[ "${TGZ_FILE}" != "data" ]]; then
			PARTITIONS_SIZE_NO_DATA_NEW_KB=$((${PARTITIONS_SIZE_NO_DATA_NEW_KB} + ${TGZ_FILES_SIZE["${TGZ_FILE}"]}))
		fi
	done
	PARTITIONS_SIZE_NO_DATA_NEW_KB=$((${PARTITIONS_SIZE_NO_DATA_NEW_KB} + ${ROOTFS_RW_SIZE}))
	echo "INFO: PARTITIONS_SIZE_NO_DATA_KB -> PARTITIONS_SIZE_NO_DATA_NEW_KB: ${PARTITIONS_SIZE_NO_DATA_KB} -> ${PARTITIONS_SIZE_NO_DATA_NEW_KB}"
	if [ $PARTITIONS_SIZE_NO_DATA_KB -gt $PARTITIONS_SIZE_NO_DATA_NEW_KB ]; then
		ROOTFS_RW_SIZE=$((${ROOTFS_RW_SIZE} + (${PARTITIONS_SIZE_NO_DATA_KB} - ${PARTITIONS_SIZE_NO_DATA_NEW_KB})))
	elif [ $PARTITIONS_SIZE_NO_DATA_KB -lt $PARTITIONS_SIZE_NO_DATA_NEW_KB ]; then
		RW_BUFFER_SIZE=$((200 * 1024))
		DIFF_SIZE=$((${PARTITIONS_SIZE_NO_DATA_NEW_KB} - ${PARTITIONS_SIZE_NO_DATA_KB} + ${RW_BUFFER_SIZE}))
		if [ $ROOTFS_RW_SIZE -lt $DIFF_SIZE ]; then
			echo "ERROR: Insufficient space in rootfs_rw to compensate for the expansion of other partitions, causing packaging failure in SOC_BAK_FIXED_DATA_START mode. ROOTFS_RW_SIZE:${ROOTFS_RW_SIZE} DIFF_SIZE:${DIFF_SIZE}"
			exit 1
		fi
		ROOTFS_RW_SIZE=$((${ROOTFS_RW_SIZE} - (${PARTITIONS_SIZE_NO_DATA_NEW_KB} - ${PARTITIONS_SIZE_NO_DATA_KB})))
	fi
	echo "INFO: rootfs_rw size change to ${ROOTFS_RW_SIZE} KiB"
fi

TGZ_ALL_SIZE=$(($TGZ_ALL_SIZE+${ROOTFS_RW_SIZE}))
for TGZ_FILE in "${TGZ_FILES[@]}"
do
	TGZ_ALL_SIZE=$(($TGZ_ALL_SIZE+${TGZ_FILES_SIZE["$TGZ_FILE"]}))
done
echo partition table size : $TGZ_ALL_SIZE KB

if [ $TGZ_ALL_SIZE -gt $EMMC_ALL_SIZE ]; then
		echo "INFO: partition table size changed, from $EMMC_ALL_SIZE KB to $TGZ_ALL_SIZE KB"
		EMMC_ALL_SIZE=$TGZ_ALL_SIZE
fi

SOCBAK_EMMC_SIZE_ALL=$(lsblk -b | grep '^mmcblk0 ' | awk '{print $4}')
SOCBAK_EMMC_SIZE_ALL=$(( $SOCBAK_EMMC_SIZE_ALL / 1024 - 102400))
if [ $EMMC_ALL_SIZE -gt $SOCBAK_EMMC_SIZE_ALL ]; then
	echo "ERROR: bakpack size($EMMC_ALL_SIZE) > emmc size($SOCBAK_EMMC_SIZE_ALL), please del some file and rework."
	socbak_cleanup
fi

if [[ "${ALL_IN_ONE_FLAG}" != "" ]] && [[ "${ALL_IN_ONE_SCRIPT}" != "" ]]; then
	SOCBAK_PARTITION_FILE="output/$SOCBAK_PARTITION_FILE"
fi

if [[ "$SOC_NAME" == "bm1684x" ]] || [[ "$SOC_NAME" == "bm1684" ]]; then
	echo "INFO: FORE BM1684/X The generated file partition32G.xml can replace file bootloader-arm64/scripts/partition32G.xml in VXX or replace some information for 3.0.0"
fi
# f2fs 模式下给 format="2" 的分区带上 fstype 属性；ext4 时为空串，
# 保证不传开关时生成的 xml 与历史版本逐字节一致。
FSTYPE_ATTR=""
if [[ "${SOC_BAK_FSTYPE}" == "f2fs" ]]; then
	FSTYPE_ATTR=' fstype="f2fs"'
fi
echo "<physical_partition size_in_kb=\"$EMMC_ALL_SIZE\">" > $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
# boot data opt system recovery rootfs
if [[ " ${TGZ_FILES[@]} " =~ " boot " ]]; then
	echo "  <partition label=\"BOOT\"       size_in_kb=\"${TGZ_FILES_SIZE[boot]}\"  readonly=\"false\"  format=\"1\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " recovery " ]]; then
	echo "  <partition label=\"RECOVERY\"   size_in_kb=\"${TGZ_FILES_SIZE[recovery]}\"  readonly=\"false\" format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "  <partition label=\"MISC\"       size_in_kb=\"10240\"  readonly=\"false\"   format=\"0\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
if [[ " ${TGZ_FILES[@]} " =~ " rootfs " ]]; then
	echo "  <partition label=\"ROOTFS\"     size_in_kb=\"${TGZ_FILES_SIZE[rootfs]}\" readonly=\"true\"   format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "  <partition label=\"ROOTFS_RW\"  size_in_kb=\"${ROOTFS_RW_SIZE}\" readonly=\"false\"  format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
if [[ " ${TGZ_FILES[@]} " =~ " opt " ]]; then
	echo "  <partition label=\"OPT\"       size_in_kb=\"${TGZ_FILES_SIZE[opt]}\" readonly=\"false\"  format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " system " ]]; then
	echo "  <partition label=\"SYSTEM\"     size_in_kb=\"${TGZ_FILES_SIZE[system]}\" readonly=\"false\"  format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " data " ]]; then
	echo "  <partition label=\"DATA\"       size_in_kb=\"${TGZ_FILES_SIZE[data]}\" readonly=\"false\"  format=\"2\"${FSTYPE_ATTR} />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "</physical_partition>" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
cat $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE

# output 目录仅在 all-in-one 模式下提前创建，tgz-only 模式走到这里不存在，
# 直接 pushd 会报 "No such file or directory"（CV84X2 真机实测踩坑，不影响产物）
mkdir -p $TGZ_FILES_PATH/output
pushd $TGZ_FILES_PATH/output
if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	advcp -g  ${TGZ_FILES_PATH}/binTools/mk_gpt .
	./mk_gpt -p "$TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE" -d "$TGZ_FILES_PATH/output/gpt.test" 1 >/dev/null || true
	dd if="$TGZ_FILES_PATH/output/gpt.test" of="$TGZ_FILES_PATH/output/gpt.test.disk"
	EMMC_SIZE_B=$(lsblk -b | grep '^mmcblk0' | head -n1 | awk -F' ' '{print $4}')
	dd if=/dev/null of="$TGZ_FILES_PATH/output/gpt.test.disk" bs=1 count=1 seek=${EMMC_SIZE_B}
	NEW_GPT_END_PART_START=$(gdisk -l "$TGZ_FILES_PATH/output/gpt.test.disk" 2>&1 | tail -n1 | awk -F' ' '{print $2}')
	OLD_GPT_END_PART_START=$(gdisk -l /dev/mmcblk0 2>&1 | tail -n 1 | awk '{print $2}')
	if [[ "$OLD_GPT_END_PART_START" != "$NEW_GPT_END_PART_START" ]] || [[ "$NEW_GPT_END_PART_START" == "" ]]; then
		echo "WARRNING: SOC_BAK_FIXED_DATA_START mode, check last part start [NEW: $NEW_GPT_END_PART_START] != [DEV: $OLD_GPT_END_PART_START]"
	fi
		echo "INFO: SOC_BAK_FIXED_DATA_START mode, check last part start [NEW: $NEW_GPT_END_PART_START] = [DEV: $OLD_GPT_END_PART_START]"
fi
popd

function socbak_allinone_pack()
{
	if [[ "${ALL_IN_ONE_FLAG}" != "" ]] && [[ "${ALL_IN_ONE_SCRIPT}" != "" ]]; then
		advmv -g ${TGZ_FILES_PATH}/*.bin output &>/dev/null
		advcp -g  ${TGZ_FILES_PATH}/binTools/mk_gpt output
		pushd $TGZ_FILES_PATH/output
		echo "INFO: start pack image mode($1)"
		source "${ALL_IN_ONE_SCRIPT}/bm_make_package.sh"
		parseargs $1 "$TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE" "$TGZ_FILES_PATH/output"
		init
		make_gpt_img
		unset -f do_gen_partition_subimg
		function do_gen_partition_subimg()
		{
			echo "INFO: part_name:$1 part_number:$2 part_format:$3 resize_flag:$4 RECOVERY_DIR:$RECOVERY_DIR"
			have_flag=0
			if [ ! -f sparse-file-$1 ]; then
				dd if=/dev/zero of=$RECOVERY_DIR/$1 bs=${SECTOR_BYTES} count=${PART_SIZE_IN_SECTOR[$2]} conv=notrunc status=progress
				if [ $3 -eq 1 ]; then
					mkfs.fat $RECOVERY_DIR/$1
				elif [ $3 -eq 2 ]; then
					# 没有预生成镜像的分区（如 ROOTFS_RW）在这里现造。f2fs 的镜像尺寸
					# 由 socbak_gen_partition_subimg 按内容定，这里只能按分区满尺寸建。
					if [ "${PART_FSTYPE[$2]}" = "f2fs" ]; then
						mkfs.f2fs ${F2FS_MKFS_OPTS} -f $RECOVERY_DIR/$1
					else
						mkfs.ext4 -b 4096 -i 16384 $RECOVERY_DIR/$1
					fi
				fi
				have_flag=0
			else
				advmv -g "sparse-file-$1" $RECOVERY_DIR/$1
			fi
			if [[ "$3" == "2" ]]; then
				if [ "${PART_FSTYPE[$2]}" = "f2fs" ]; then
					# f2fs 镜像在 socbak_gen_partition_subimg 里已经定稿（尺寸定死 + fsck 干净），
					# 这里只确认一遍；resize2fs -M 对 f2fs 无意义且会直接报错。
					fsck.f2fs -f $RECOVERY_DIR/$1 ||
						{ echo "ERROR: fsck.f2fs $1 error, exit."; socbak_cleanup; }
				else
					e2fsck -f -p $RECOVERY_DIR/$1
					resize2fs -M $RECOVERY_DIR/$1
				fi
			elif [[ "$3" == "1" ]]; then
				fsck.fat -f $RECOVERY_DIR/$1
			fi
		}
		make_partition_imgs
		emmc_done
		popd
		cleanup
		advcp ${TGZ_FILES_PATH}/script/ota_update/ota_update.sh $RECOVERY_DIR/
		pushd $RECOVERY_DIR
			md5sum ./* > md5.txt
		popd
	fi
}
if [[ "${ALL_IN_ONE_FLAG}" != "" ]] && [[ "${ALL_IN_ONE_SCRIPT}" != "" ]]; then
	if [[ "${SOC_BAK_ALL_IN_ONE}" =~ "sdcard" ]]; then
		socbak_allinone_pack sdcard
	elif [[ "${SOC_BAK_ALL_IN_ONE}" =~ "tftp" ]]; then
		socbak_allinone_pack tftp
	elif [[ "${SOC_BAK_ALL_IN_ONE}" =~ "usb" ]]; then
		socbak_allinone_pack usb
	else
		socbak_allinone_pack sdcard
	fi
fi
echo "INFO: pack success, wait sync..."
sync
