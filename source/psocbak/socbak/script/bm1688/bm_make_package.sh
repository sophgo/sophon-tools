#!/bin/bash

PROGNAME=$(basename $0)

set -e

EMMC_DEV_NUM=0
SDCARD_DEV_NUM=1
LOAD_PARTITION_NUM=1


LOAD_COMMAND=fatload

SECTOR_BYTES=512
CHUNK_SIZE=200704

BOOT_PART_OFFSET=8192
SCRIPT_ADDR="\${scriptaddr}"
IN_ADDR="\${ramdisk_addr_r}"
IN_ADDR_B="\${ramdisk_addr_b}"
OUT_ADDR="\${unzip_addr}"

RECOVERY_DIR=recovery_files
PARTITION_FILE=partition32G.xml
BOOTCMD_SCRIPT=boot_emmc
SPIFCMD_SCRIPT=boot_spif
FIPCMD_SCRIPT=boot_fip
TOP_SCRIPT=boot
MOUNT_DIR=tmp

OTA_PATH='/$ota_path/'
ERASE_PARTITION=false

SOURCE_FILES_PATH=



# help function
function usage()
{
	echo >&2
	echo "${PROGNAME}: $@" >&2
	echo >&2
	echo "Usage: ${PROGNAME} <type> <partition file> <source tgz files path>" >&2
	echo >&2
	echo "	type:" >&2
	echo "	sdcard		build sdcard update img" >&2
	echo "	tftp		build tftp update img" >&2
	echo >&2
	echo "	partition file:" >&2
	echo "	specified a partition file" >&2
	echo >&2
	echo >&2
	echo "	source tgz files path:" >&2
	echo "	specified your .tgz files path" >&2
	echo >&2
	exit 1
}

function cleanup()
{
	for i in $(seq 0 $[${#LABELS[@]}-1]); do
		if [ -f $RECOVERY_DIR/${LABELS[$i]} ]; then
			rm -f $RECOVERY_DIR/${LABELS[$i]}
		fi
		if mountpoint -q $RECOVERY_DIR/$MOUNT_DIR-$i; then
			sudo umount $RECOVERY_DIR/$MOUNT_DIR-$i
		fi
		rm -rf $RECOVERY_DIR/$MOUNT_DIR-*
	done
}

trap cleanup EXIT ERR SIGHUP SIGINT SIGQUIT SIGTERM

function panic()
{
	if [ $# -gt 0 ]; then
		echo "" >&2
		echo "${PROGNAME}: $@" >&2
		echo "" >&2
	fi

	echo build error, bye.

	exit 1
}

function file_validate()
{
	local file

	file=$(eval echo \$1)
	[ -f ${file} ] || panic "$i file \"$file\" does not exist"
	[ -r ${file} ] || panic "$i \"$file\" is not readable"
	[ -s ${file} ] || panic "$i \"$file\" is empty"
}

function suser() {
	echo
	echo To continue, superuser credentials are required.
	sudo -k || panic "failed to kill superuser privilege"
	sudo -v || panic "failed to get superuser privilege"
}

function compute_round_quotient()
{
	local total_size=$1
	local unit_size=$2

	[ ${unit_size} -gt 0 ] || panic "bad unit_size ${unit_size} in compute_round_quotient()"
	expr \( ${total_size} + ${unit_size} - 1 \) / ${unit_size}
}

function file_bytes() {
	local filename=$1

	stat --dereference --format="%s" ${filename} ||
	panic "unable to stat \"${filename}\""
}

function script_update()
{
	echo "$@" >> ${CURRENT_SCRIPT}
}

function get_current_path()
{
	echo $(cd "$(dirname "$1")" && pwd)
}

function parseargs()
{
	[ $# -lt 1 ] && usage "no update type specified"

	UPTYPE=$1

	if [ "${UPTYPE}" = sdcard -o "${UPTYPE}" = ota ]; then
		LOAD_COMMAND="load \${devtype} \${devnum}:\${distro_bootpart}"
	elif [ "${UPTYPE}" = tftp ]; then
		LOAD_COMMAND=tftp
	elif [ "${UPTYPE}" = usb ]; then
		LOAD_COMMAND=cvi_utask
	else
		usage "no valid update type specified"
	fi

	shift
	file_validate $1
	PARTITION_FILE=$1

	shift
	SOURCE_FILES_PATH=$(get_current_path $1)/$(basename $1)
	RECOVERY_DIR=${SOURCE_FILES_PATH}/${UPTYPE}
}

function parse_partition_xml()
{
	local offset=${BOOT_PART_OFFSET}

	#find total disk size in kb
	TOTAL_SIZE=($(grep -Po "physical_partition size_in_kb=\".+\"" ${PARTITION_FILE} | awk -F\" '{print $2}'))

	#find partions label size, and flag
	LABELS=($( grep -Po "label=\".+\"" ${PARTITION_FILE} | awk -F\" '{print tolower($2)}'))

	PART_SIZE_IN_KB=($(grep -Po "size_in_kb=\".+\"" ${PARTITION_FILE} | awk -F\" '{print $2}'))
	PART_SIZE_IN_KB=(${PART_SIZE_IN_KB[@]:1})

	for i in ${!PART_SIZE_IN_KB[*]}; do
		PART_SIZE_IN_SECTOR[$i]=$(expr ${PART_SIZE_IN_KB[$i]} \* 1024 / ${SECTOR_BYTES})
		PART_SIZE_IN_BYTE[$i]=$(expr ${PART_SIZE_IN_KB[$i]} \* 1024)
	done

	P_FLAG=($(grep -Po "readonly=\".+\"" ${PARTITION_FILE} | awk -F\" '{print $2}'))
	PART_FORMAT=($(grep -Po "format=\".+\"" ${PARTITION_FILE} | awk -F\" '{print $2}'))

	for i in $(seq 0 $[${#LABELS[@]}-1]); do
		PART_OFFSET[$i]=$offset
		offset=$(expr ${offset} + ${PART_SIZE_IN_SECTOR[$i]})
	done

	END_OFFSET=$offset

	for i in $(seq 0 $[${#LABELS[@]}-1]); do
		PART_COMPRESS_FILE_NAME[$i]=${SOURCE_FILES_PATH}/${LABELS[$i]}.tgz
		PART_IMAGE_FILE_NAME[$i]=${SOURCE_FILES_PATH}/${LABELS[$i]}.img
	done
}

function compile_script() {
	local scr_name=$1
	local description="$1"

	mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "${description}" \
		-d ${CURRENT_SCRIPT} ${RECOVERY_DIR}/$scr_name.scr ||
	panic "failed to compile image for \"${CURRENT_SCRIPT}\""
}

function create_partition_script_done() {
	compile_script $(basename ${CURRENT_SCRIPT} .cmd)
	CURRENT_SCRIPT=${RECOVERY_DIR}/${BOOTCMD_SCRIPT}.cmd
}

function compress_and_update_partition_script()
{
	local filename=$1;
	local hex_disk_offset=$(printf "0x%08x" $2)
	local bytes=$(file_bytes ${filename});
	local hex_bytes=$(printf "0x%08x" ${bytes})
	local size=$(compute_round_quotient ${bytes} ${SECTOR_BYTES})
	local hex_size=$(printf "0x%08x" ${size})

	pigz -v ${filename}
	if [[ $filename == *"usb"* ]]; then
		echo "raw to cimg: $filename"
		SCRIPT_DIR=$(cd $(dirname ${BASH_SOURCE[0]}); pwd)
		python3 $SCRIPT_DIR/raw2cimg_edge.py $filename.gz
		mv $filename.gz.head $filename.gz
	fi

	script_update "${LOAD_COMMAND} ${IN_ADDR} ${OTA_PATH}$(basename ${filename}.gz)"
	script_update "if test \$? -ne 0; then"
	script_update "led status off"
	script_update "led error off"
	if [ "${LOAD_COMMAND}" = tftp ]; then
		script_update "while true; do; echo \"ERROR: load package failed\"; echo \"ERROR: will auto reset \"; reset; sleep 0.5; done; fi;"
	else
		script_update "while true; do; echo \"ERROR: load package failed\"; sleep 0.5; done; fi;"
	fi
	script_update "echo"
	script_update ""
	script_update "unzip ${IN_ADDR} ${OUT_ADDR} ${hex_bytes}"
	script_update "if test \$? -ne 0; then"
	script_update "led status off"
	script_update "led error off"
	if [ "${LOAD_COMMAND}" = tftp ]; then
		script_update "while true; do; echo \"ERROR: load package failed\"; echo \"ERROR: will auto reset \"; reset; sleep 0.5; done; fi;"
	else
		script_update "while true; do; echo \"ERROR: load package failed\"; sleep 0.5; done; fi;"
	fi
	script_update "echo"
	script_update ""
	script_update "mmc write ${OUT_ADDR} ${hex_disk_offset} ${hex_size}"
	script_update "if test \$? -ne 0; then"
	script_update "led status off"
	script_update "led error off"
	script_update "while true; do; echo \"ERROR: eMMC write failed\"; sleep 0.5; done; fi;"
	script_update "echo"
	script_update ""
}

function create_partition_script()
{
	local sub=$1; shift
	local description="$@"
	local sub_script=${RECOVERY_DIR}/${BOOTCMD_SCRIPT}-$(echo ${sub,,}).cmd

	# Add commands to the top-level script
	script_update "# ${description}"
	script_update "${LOAD_COMMAND} ${SCRIPT_ADDR} ${OTA_PATH}$(basename ${sub_script} .cmd).scr"
	script_update "source ${SCRIPT_ADDR}"
	script_update ""

	# Switch to the sub-script file
	local savelog=$(echo ${description} | awk '{print $2}')
	CURRENT_SCRIPT=${sub_script}
	cp /dev/null ${CURRENT_SCRIPT}
	script_update "# ${description}"
	if [ "$savelog" != "gpt" ]; then
		if [ $savelog -gt 2 ]; then
			script_update "bm_savelog mmc 0:1 ${savelog}.log"
		fi
	fi
	script_update ""

	local part_num=$(expr $(echo ${description} | awk '{print $2}') + 1)
	if [ "$part_num" = "" ]; then
		script_update "if test -n \$load_partition; then echo \"skip empty part_num partition \";  exit; fi;"
		script_update ""
	else
		script_update "if test -n \$load_partition; then if test \$load_partition -eq $part_num; then echo \"skip partition \$load_partition\";  exit; fi; fi;"
		script_update ""
	fi
}

function create_top_script()
{
	CURRENT_SCRIPT=${RECOVERY_DIR}/${TOP_SCRIPT}.cmd
	cp /dev/null ${CURRENT_SCRIPT}

	script_update "# Bitmain ${UPTYPE} recovery U-Boot script"
	script_update "# Created $(date)"
	script_update ""
	script_update "# disable MCU watchdog"
	script_update "i2c dev 1; i2c mw 0x69 1 0"
	script_update ""
	script_update "setenv update_all 1"
	script_update "led status off"
	script_update "led error on"
	script_update ""
	script_update "if test -n \$load_partition; then setenv distro_bootpart \$load_partition; setenv reset_after 1; fi;"
	script_update ""
	script_update "echo update fip flash"
	script_update "${LOAD_COMMAND} ${SCRIPT_ADDR} ${OTA_PATH}$(basename ${FIPCMD_SCRIPT} .cmd).scr"
	if [ "${UPTYPE}" != usb ]; then
		script_update "if test \$? -ne 0; then"
		script_update "echo sd not found partition, set distro bootpart null"
		script_update "setenv distro_bootpart  ; ${LOAD_COMMAND} ${SCRIPT_ADDR} \
			${OTA_PATH}$(basename ${FIPCMD_SCRIPT} .cmd).scr; fi"
	fi
	script_update "source ${SCRIPT_ADDR}"
	script_update ""
	script_update "echo update eMMC"
	script_update "${LOAD_COMMAND} ${SCRIPT_ADDR} ${OTA_PATH}$(basename ${BOOTCMD_SCRIPT} .cmd).scr"
	script_update "source ${SCRIPT_ADDR}"
	script_update ""
	script_update "echo all done"
	script_update ""
	script_update "led status on"
	script_update "led error off"
	script_update "setenv light 1"
	script_update ""
	script_update "#for SE9BX direct to ubuntu"
	script_update "cmp.b 0x05207f82 0x05207f83 1"
	script_update "if test \$? -eq 1; then setenv consoledev ttyS2; setenv DTS_TYPE config-cv186ah_sm9v1_4G; load mmc 0:1 \${scriptaddr} boot.scr.emmc; source \${scriptaddr}; fi;"
	script_update ""
	script_update "if test \"\$reset_after\" = \"1\"; then reset; fi;"
	script_update ""
	if [ "${UPTYPE}" != usb ]; then
		script_update "while true; do"
		script_update "if test \$light = \"0\"; then led status off; setenv light 1; \
			else led status on; setenv light 0; fi;"
		script_update "echo \"Please remove the installation medium, then reboot\"; sleep 0.5; done;"
	fi

	compile_script $(basename ${CURRENT_SCRIPT} .cmd)
}

function create_spif_script()
{
	CURRENT_SCRIPT=${RECOVERY_DIR}/${SPIFCMD_SCRIPT}.cmd
	cp /dev/null ${CURRENT_SCRIPT}

	cp ${SOURCE_FILES_PATH}/fip*.bin ${RECOVERY_DIR}
	touch ${RECOVERY_DIR}/BOOT


	if [ ! -e ${SOURCE_FILES_PATH}/spi_flash.bin ]; then
		echo "no SPI flash image"
	else
		cp ${SOURCE_FILES_PATH}/spi_flash*.bin ${RECOVERY_DIR}

		script_update "# SPI flash image"
		script_update ""
		script_update "${LOAD_COMMAND} ${IN_ADDR} ${OTA_PATH}spi_flash.bin"
		script_update "if test \$? -eq 0; then"
		script_update "sf probe"
		script_update "if test \$? -ne 0; then"
		script_update "led status off"
		script_update "led error off"
		script_update "while true; do; echo \"ERROR: SPI flash not exist\"; sleep 0.5; done; fi;"
		script_update "print chip_type"
		script_update "if test \"\$chip_type\" = \"bm1684\"; then sf update ${IN_ADDR_B} 0x0 0x200000; else sf update ${IN_ADDR} 0x0 0x200000; fi"
		script_update "else"
		script_update "echo skip SPI flash update."
		script_update "fi"
		script_update ""
		script_update "echo SPI flash update done"
		script_update "if test \"\$update_all\" != \"1\" -a \"\$reset_after\" = \"1\"; then reset; fi;"
		script_update "if test \"\$update_all\" != \"1\"; then while true; do; echo \"Please remove the installation medium, then reboot\"; sleep 0.5; done; fi;"
	fi

	compile_script $(basename ${CURRENT_SCRIPT} .cmd)
}
function create_fip_script()
{
	CURRENT_SCRIPT=${RECOVERY_DIR}/${FIPCMD_SCRIPT}.cmd
	cp /dev/null ${CURRENT_SCRIPT}

	if [ ! -e ${SOURCE_FILES_PATH}/fip.bin ]; then
		echo "no fip.bin"
	else
		cp ${SOURCE_FILES_PATH}/fip.bin ${RECOVERY_DIR}
		touch ${RECOVERY_DIR}/BOOT

		script_update "# fip flash image"
		script_update ""
		script_update "${LOAD_COMMAND} ${IN_ADDR} ${OTA_PATH}fip.bin"
		script_update "if test \$? -eq 0; then"
		script_update ""
		script_update "mmc dev 0 1"
		script_update "if test \$? -ne 0; then"
		script_update "led status off"
		script_update "led error off"
		script_update "while true; do; echo \"ERROR: switch to mmc0(part1) fail\"; sleep 0.5; done; fi;"
		script_update ""
		script_update "mmc write ${IN_ADDR} 0x0 0x800"
		script_update "mmc write ${IN_ADDR} 0x800 0x800"
		script_update ""
		script_update "else"
		script_update ""
		script_update "echo skip fip flash."
		script_update "fi"
		script_update ""
		script_update "echo Program fip.bin done"
		script_update "mmc dev 0"

	fi

	compile_script $(basename ${CURRENT_SCRIPT} .cmd)

}


function create_emmc_script()
{
	CURRENT_SCRIPT=${RECOVERY_DIR}/${BOOTCMD_SCRIPT}.cmd
	cp /dev/null ${CURRENT_SCRIPT}

	script_update "# eMMC image"
	script_update ""
	script_update "mmc dev $EMMC_DEV_NUM"
	script_update "if test \$? -ne 0; then"
	script_update "led status off"
	script_update "led error off"
	script_update "while true; do; echo \"ERROR: eMMC not exist\"; sleep 0.5; done; fi;"
	script_update ""
	if [  ERASE_PARTITION = true ]; then
		script_update "echo erase mmc chip"
		script_update "mmc erase 0# $(echo "obase=16;${END_OFFSET}" | bc)"
		script_update ""
	fi
}

function split_and_compress_img()
{
	local part_number=$1
	local part_name=${RECOVERY_DIR}/$2
	local part_offset=${PART_OFFSET[${part_number}]}
	local offset=0
	local size
	local chunk_size=${CHUNK_SIZE}
	local count=1;
	local limit
	local desc="Partition ${part_number} (${LABELS[${part_number}]})"

	if [ ! -e "${part_name}" ]; then
		echo "Skipping partition ${part_number}"
		return
	fi

	size=$(du -b ${part_name} | awk '{print $1}')
	size=$(expr \( ${size} + ${SECTOR_BYTES} - 1 \) / ${SECTOR_BYTES})
	limit=$(compute_round_quotient ${size} ${chunk_size})

	create_partition_script $(basename ${part_name}) "${desc}"

	while true; do
		local filename=${part_name}.${count}-of-${limit};
		local disk_offset=$(expr ${part_offset} + ${offset})

		if [ ${size} -lt ${chunk_size} ]; then
			chunk_size=${size}
		fi

		dd status=none if=${part_name} of=${filename} \
			bs=${SECTOR_BYTES} skip=${offset} count=${chunk_size}

		compress_and_update_partition_script ${filename} ${disk_offset}

		count=$(expr ${count} + 1)
		offset=$(expr ${offset} + ${chunk_size})

		size=$(expr ${size} - ${chunk_size}) || break
	done

	create_partition_script_done
}

# arguments:
# $3: file system type: 0 for raw partition; 1 for FAT32; 2 for ext4
# $4: shrink file system for not
#
# if there is a xxx.img file and the size is legal, used it; if not, use xxx.tgz instead.
# and this rule only applies to read-only partion.
function do_gen_partition_subimg()
{
	local part_image_exists=0


	dd if=/dev/zero of=$RECOVERY_DIR/$1 bs=${SECTOR_BYTES} count=${PART_SIZE_IN_SECTOR[$2]}

	if [ $3 -eq 1 ]; then
		mkfs.fat $RECOVERY_DIR/$1
	elif [ $3 -eq 2 ]; then
		mkfs.ext4 $RECOVERY_DIR/$1
	else
		echo $1 partition has no filesystem
		if [ -f ${PART_IMAGE_FILE_NAME[$2]} ]; then
			cp ${PART_IMAGE_FILE_NAME[$2]} $RECOVERY_DIR/$1
		fi
	fi

	if [ $3 -eq 1 -o $3 -eq 2 ]; then
		if [ -f ${PART_IMAGE_FILE_NAME[$2]} -a "${P_FLAG[$2]}" == "true" ]; then
			if [ $(ls -l ${PART_IMAGE_FILE_NAME[$2]} | awk '{print $5}') == ${PART_SIZE_IN_BYTE[$2]} ]; then
				echo "${PART_IMAGE_FILE_NAME[$2]} exists, replace $RECOVERY_DIR/$1"
				cp ${PART_IMAGE_FILE_NAME[$2]} $RECOVERY_DIR/$1
				part_image_exists=1
			else
				panic "$1 size mismatch: $(ls -l ${PART_IMAGE_FILE_NAME[$2]} | awk '{print $5}') against ${PART_SIZE_IN_BYTE[$2]}"
			fi
		else
			if [ -f ${PART_COMPRESS_FILE_NAME[$2]} ]; then
				mkdir -p $RECOVERY_DIR/$MOUNT_DIR-$2
				sudo mount $RECOVERY_DIR/$1 $RECOVERY_DIR/$MOUNT_DIR-$2
				if [ $3 -eq 1 ]; then
					sudo tar -xzf ${PART_COMPRESS_FILE_NAME[$2]} --no-same-owner -C $RECOVERY_DIR/$MOUNT_DIR-$2
				else
					sudo tar -xzf ${PART_COMPRESS_FILE_NAME[$2]} -C $RECOVERY_DIR/$MOUNT_DIR-$2
				fi
				sync
				sleep 1 # wait for sync
				sudo umount $RECOVERY_DIR/$MOUNT_DIR-$2
			else
				echo $1 may be an empty parition.
			fi
		fi
	fi

	if [ $part_image_exists -ne 1 -a $4 -eq 1 ]; then
		e2fsck -f -p $RECOVERY_DIR/$1
		resize2fs -M $RECOVERY_DIR/$1
	fi
}

function gen_partition_img()
{
	local part_number=$1
	local part_name=$2
	local part_format=$3

	if [ "$part_format" = "2"  ]; then
		local resize_flag="1"
	else
		local resize_flag="0"
	fi
	do_gen_partition_subimg $part_name $part_number $part_format $resize_flag
}

function make_partition_imgs()
{
	for i in $(seq 0 $[${#LABELS[@]}-1]); do (
		gen_partition_img $i ${LABELS[$i]} ${PART_FORMAT[$i]}
	) done

	for i in $(seq 0 $[${#LABELS[@]}-1]); do (
		split_and_compress_img $i ${LABELS[$i]}
	) done

	wait
}

function make_gpt_img()
{

	local disk_offset=0
	local filename=${RECOVERY_DIR}/gpt
	local desc="mmc gpt file"

	./mk_gpt -p ${PARTITION_FILE} -d ${filename} 1 >/dev/null || true

	create_partition_script $(basename ${filename}) "${desc}"

	compress_and_update_partition_script ${filename} ${disk_offset}
	create_partition_script_done
}

function emmc_done()
{


	script_update "echo eMMC update done"
	script_update "bm_savelog mmc 0:1 end.log"
	script_update "if test \"\$update_all\" != \"1\" -a \"\$reset_after\" = \"1\"; then reset; fi;"
	script_update "if test \"\$update_all\" != \"1\"; then while true; do; echo \"Please remove the installation medium, then reboot\"; sleep 0.5; done; fi;"
	compile_script $(basename ${CURRENT_SCRIPT} .cmd)

	#move boot partition to final update for tftp upgrade.
	if [ "${LOAD_COMMAND}" = tftp ]; then

		BOOTCMD="${RECOVERY_DIR}/boot_emmc.cmd"
		BOOTSCR="${RECOVERY_DIR}/boot_emmc.scr"


		row_no=$(grep -n "Partition 0" $BOOTCMD | awk -F '[\\: \\,]' '{print $1}')
		replace_no=$(grep -n "echo eMMC update done" $BOOTCMD | awk -F '[\\: \\,]' '{print $1}')

		str1=$(awk "NR==${row_no}{print}" $BOOTCMD)
		sed -i "$replace_no"'i\'"${str1}" $BOOTCMD
		sed -i $row_no'd' $BOOTCMD

		str1=$(awk "NR==${row_no}{print}" $BOOTCMD)
		sed -i "$replace_no"'i\'"${str1}" $BOOTCMD
		sed -i $row_no'd' $BOOTCMD


		str1=$(awk "NR==${row_no}{print}" $BOOTCMD)
		sed -i "$replace_no"'i\'"${str1}" $BOOTCMD
		sed -i $row_no'd' $BOOTCMD


		str1=$(awk "NR==${row_no}{print}" $BOOTCMD)
		sed -i "$replace_no"'i\  ' $BOOTCMD
		sed -i $row_no'd' $BOOTCMD

		rm $BOOTSCR

		mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "${BOOTCMD}" -d ${BOOTCMD} $BOOTSCR \
		|| panic "failed to compile image for \"${BOOTCMD}\""


	fi
	echo build success.
}

function init()
{
	echo generating update files

	if [ -d ${RECOVERY_DIR} ];then
		rm -rf ${RECOVERY_DIR}

	fi

	mkdir -p ${RECOVERY_DIR} || panic "unable to create \"${RECOVERY_DIR}\""
	cp ${PARTITION_FILE} ${RECOVERY_DIR}/

	parse_partition_xml
	create_top_script
	create_fip_script
	create_emmc_script
}

#parseargs "$@"

#echo start building ...
#suser
#init
# continue to add more command to emmc script
#make_gpt_img
#make_partition_imgs
#emmc_done
