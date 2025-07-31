#!/bin/bash

# env SOC_BAK_ALL_IN_ONE!="" for socbak allinone
# env SOC_BAK_FIXED_SIZE!="" for socbak fixed size mode
# env SOC_BAK_FIXED_DATA_START!="" for socbak fixed data partition start mode

# 配置日志能力
PWD="$(dirname "$(readlink -f "\$0")")"
TGZ_FILES_PATH=${PWD}
LOGFILE="$(readlink -f "${BASH_SOURCE[0]}").log"
rm -f $LOGFILE*
exec > >(while IFS= read -r line; do echo "[$(date '+%Y-%m-%d %H:%M:%S')] $line"; done | tee -a "$LOGFILE") 2>&1

echo "VERSION: v1.2.1"

export SOC_BAK_ALL_IN_ONE=${SOC_BAK_ALL_IN_ONE:-}
export SOC_BAK_FIXED_SIZE=${SOC_BAK_FIXED_SIZE:-}
export SOC_BAK_FIXED_DATA_START=${SOC_BAK_FIXED_DATA_START:-}

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
    esac
done

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
PART_EXCLUDE_FLAGS["data"]='  '

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
TAR_SIZE=0
SOCBAK_PARTITION_FILE=partition32G.xml
BM1684_SOC_VERSION=0
NEED_BAK_FLASH=1
SOC_NAME=""
PIGZ_GZIP_COM=""
export GZIP=-1
export PIGZ=-1
PARTITIONS_SIZE_NO_DATA_KB=$((0))

if [[ "${SOC_BAK_FIXED_DATA_START}" != "" ]]; then
	echo "INFO: SOC_BAK_FIXED_DATA_START open, some ROOTFS_RW space will be automatically allocated to ROOTFS_RO"
fi

chmod +x ${TGZ_FILES_PATH}/binTools
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

rm /home/*/.bash_history
rm /root/.bash_history

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
	exit 0
}
trap socbak_cleanup EXIT ERR SIGHUP SIGINT SIGQUIT SIGTERM

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
if [[ "${SOC_NAME}" == "" ]]; then
	if [[ "$(grep -ai "bm1688" '/proc/device-tree/model' 2>/dev/null | wc -l)" != "0" ]]; then
		SOC_NAME="bm1688"
	elif [[ "$(grep -ai "athena2" '/proc/device-tree/model' 2>/dev/null | wc -l)" != "0" ]]; then
		SOC_NAME="bm1688"
	fi
fi
if [[ "${SOC_NAME}" == "" ]]; then
	echo "ERROR: cannot get chip id!"
	exit -1
else
	echo "INFO: get chip id success!"
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
elif [[ "$SOC_NAME" == "bm1688" ]]; then
	NEED_BAK_FLASH=1
	ROOTFS_RW_SIZE=${ROOTFS_RW_SIZE_BM1688}
	TGZ_FILES_SIZE["recovery"]=${RECOVERY_SIZE_BM1688}
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
	elif [[ "$SOC_NAME" == "bm1688" ]]; then
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

function socbak_gen_partition_subimg()
{
	declare -g partition_subimg_size_kb
	echo "INFO: gen partition($1) to img file"
	umount ./sparse-path* &>/dev/null
	rm ./sparse-file* &>/dev/null
	rm ./sparse-path* -rf &>/dev/null
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
	case $1 in
		"rootfs")
			pushd /
			systemctl enable resize-helper.service
			tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read --numeric-owner -cpSf - ${ROOTFS_EXCLUDE_FLAGS} "./" | tar -xpSf - -C "$TGZ_FILES_PATH/sparse-path-$1"
			if [[ "$?" != "0" ]]; then echo "ERROR: cp files $1 error, exit."; socbak_cleanup; fi
			echo "INFO: add ext include files to rootfs..."
			tar --ignore-failed-read --numeric-owner -cvpSf - ${ROOTFS_INCLUDE_PATHS} | tar -xpSf - -C "$TGZ_FILES_PATH/sparse-path-$1"
			systemctl disable resize-helper.service
			popd
		;;
		*)
			pushd /$1
			set +u
			EXT_FLAG="${PART_EXCLUDE_FLAGS["$1"]}"
			set -u
			tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' --ignore-failed-read --numeric-owner -cpSf - ${EXT_FLAG} "./" | tar -xpSf - -C "$TGZ_FILES_PATH/sparse-path-$1"
			if [[ "$?" != "0" ]]; then echo "ERROR: cp files $1 error, exit."; socbak_cleanup; fi
			popd
		;;
	esac
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
		partition_format="ext4"
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
				tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' -capSf $TGZ_FILES_PATH/$TGZ_FILE.tar --numeric-owner $ROOTFS_EXCLUDE_FLAGS "./"
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
				tar --checkpoint=500 --checkpoint-action=ttyout='[%d sec]: C%u, %T%*\r' -I ${PIGZ_GZIP_COM} -cpSf $TGZ_FILES_PATH/$TGZ_FILE.tgz --numeric-owner ${EXT_FLAG} "./"
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
echo "<physical_partition size_in_kb=\"$EMMC_ALL_SIZE\">" > $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
# boot data opt system recovery rootfs
if [[ " ${TGZ_FILES[@]} " =~ " boot " ]]; then
	echo "  <partition label=\"BOOT\"       size_in_kb=\"${TGZ_FILES_SIZE[boot]}\"  readonly=\"false\"  format=\"1\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " recovery " ]]; then
	echo "  <partition label=\"RECOVERY\"   size_in_kb=\"${TGZ_FILES_SIZE[recovery]}\"  readonly=\"false\" format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "  <partition label=\"MISC\"       size_in_kb=\"10240\"  readonly=\"false\"   format=\"0\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
if [[ " ${TGZ_FILES[@]} " =~ " rootfs " ]]; then
	echo "  <partition label=\"ROOTFS\"     size_in_kb=\"${TGZ_FILES_SIZE[rootfs]}\" readonly=\"true\"   format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "  <partition label=\"ROOTFS_RW\"  size_in_kb=\"${ROOTFS_RW_SIZE}\" readonly=\"false\"  format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
if [[ " ${TGZ_FILES[@]} " =~ " opt " ]]; then
	echo "  <partition label=\"OPT\"       size_in_kb=\"${TGZ_FILES_SIZE[opt]}\" readonly=\"false\"  format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " system " ]]; then
	echo "  <partition label=\"SYSTEM\"     size_in_kb=\"${TGZ_FILES_SIZE[system]}\" readonly=\"false\"  format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
if [[ " ${TGZ_FILES[@]} " =~ " data " ]]; then
	echo "  <partition label=\"DATA\"       size_in_kb=\"${TGZ_FILES_SIZE[data]}\" readonly=\"false\"  format=\"2\" />" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
fi
echo "</physical_partition>" >> $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE
cat $TGZ_FILES_PATH/$SOCBAK_PARTITION_FILE

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
		exit 1
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
					mkfs.ext4 -b 4096 -i 16384 $RECOVERY_DIR/$1
				fi
				have_flag=0
			else
				advmv -g "sparse-file-$1" $RECOVERY_DIR/$1
			fi
			if [[ "$3" == "2" ]]; then
				e2fsck -f -p $RECOVERY_DIR/$1
				resize2fs -M $RECOVERY_DIR/$1
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
