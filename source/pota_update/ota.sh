#!/bin/bash
# 参考链接：https://github.com/sophgo/sophon-tools/tree/main/source/pota_update

# 配置区域
EMMC_SECTOR_B=512
original_ifs=$IFS
# LED灯报错方案
led_env_str="
setenv led_ota_flash_run 'led status off;led error on;sleep 2';
setenv led_ota_flash_run_flash 'led status off;led error on;sleep 0.1;\
led error off;sleep 0.1;led error on;sleep 0.1;led error off;sleep 0.1;\
led error on;sleep 0.1;led error off;sleep 0.1;\
led error on;sleep 0.1;led error off;sleep 0.1;led error on;'
setenv led_ota_flash_ok 'led status on;led error off;sleep 2';
setenv LED_OTA_ERROR_FLAG 0
setenv led_ota_flash_error 'setenv ledei 0;led status off;led error off;sleep 2;\
led status on; sleep 0.5; led status off;sleep 0.5;\
while test \$ledei -lt \$LED_OTA_ERROR_FLAG;do \
led error on;sleep 0.5;led error off;sleep 0.5;setexpr ledei \$ledei + 1;done;\
led status on; sleep 0.5; led status off;sleep 2';
"
# 刷机环境准备
flash_pre_str='
i2c dev 1; i2c mw 0x69 1 0
run led_ota_flash_run
'
# 刷机完成后执行
flash_post_str='
echo OTA UPDATE DONE
run led_ota_flash_ok
if test -z $UBOOT_ENV_SUPPORT_OTA_ENABLE || test $UBOOT_ENV_SUPPORT_OTA_ENABLE != 1; then
echo "UBOOT ENV SUPPORT OTA DISABLED!!!"
else
echo "UBOOT ENV SUPPORT OTA ENABLED!!!"
env default -a
saveenv
fi
reset
'

rm -rf /dev/shm/ota_success_flag
rm -rf /dev/shm/ota_error_flag

function panic() {
    set >>"$LOGFILE"
    if [ $# -gt 0 ]; then
        echo "" >&1
        echo "[PANIC] $@" >&1
        echo "" >&1
    fi
    if [[ "$LAST_PART_NOT_FLASH" == "1" ]] || [[ "$LAST_PART_NOT_FLASH" == "LAST_PART_NOT_FLASH" \
]]; then
        if [ -f $WORK_DIR/gpt.gz.ota_update_bak ]; then
            mv $WORK_DIR/gpt.gz.ota_update_bak $WORK_DIR/gpt.gz
        fi
    fi
    popd &>/dev/null
    touch /dev/shm/ota_error_flag
    wall "[OTA PANIC] $@"
    exit 1
}

function file_validate() {
    local file
    file=$(eval echo \$1)
    [ -r ${file} ] || panic "$i \"$file\" is not readable"
}

# 必须是root账户
if [ ! "$(id -u)" -eq 0 ]; then
    panic "must use root"
fi

# 检查的工具
need_tools=("systemd" "systemd-run" "tee" "exec" "echo" "bc" "gdisk" "mkimage" "awk" "sed" "tr" \
"gzip" "dd" "sgdisk" "fdisk" "fuser" "wall" "head")
for tool in "${need_tools[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        panic "$tool: cannot find"
    fi
done

CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
! [[ "$CPU_MODEL" == "" ]] || panic "cannot get cpu model from /proc/cpuinfo"
SOC_MODE_CPU_MODEL=("bm1684x" "bm1684" "bm1688" "cv186ah")
WORK_MODE="ERROR"
for element in "${SOC_MODE_CPU_MODEL[@]}"; do
    if [ "$element" == "$CPU_MODEL" ]; then
        WORK_MODE="SOC"
        break
    fi
done
if [[ "$WORK_MODE" == "ERROR" ]]; then
    panic "chip type [$CPU_MODEL] not support"
fi

# 刷机用环境变量
if [[ "${CPU_MODEL}" == "bm1684" ]]; then
    # v3.0.0 uboot
otaenvsetup_str="setenv otaenvset 'if test -n \${unzip_addr};then echo \"new version uboot\"; \
else setenv ramdisk_addr_b 0x310400000; \
setenv ramdisk_addr_r 0x310000000; \
setenv scriptaddr 0x300040000; \
setenv chip_type bm1684; \
setenv unzip_addr 0x320000000; \
fi'
"
else
otaenvsetup_str="setenv otaenvset  ';'
"
fi

# 检查参数
LAST_PART_NOT_FLASH=1
SHELL_NEED_AUTOBOOT_ONCE=""
SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR=""
RUN_WORK_DIR=""
for arg in "$@"; do
    case $arg in
        RUN_WORK_DIR=*)
            RUN_WORK_DIR="${arg#*=}"
            shift
            ;;
        LAST_PART_NOT_FLASH=*)
            LAST_PART_NOT_FLASH="${arg#*=}"
            shift
            ;;
        SHELL_NEED_AUTOBOOT_ONCE=*)
            SHELL_NEED_AUTOBOOT_ONCE="${arg#*=}"
            SHELL_NEED_AUTOBOOT_ONCE="$(readlink -f ${SHELL_NEED_AUTOBOOT_ONCE})"
            shift
            ;;
        SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR=*)
            SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR="${arg#*=}"
            SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR="$(readlink -f ${SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR})"
            shift
            ;;
    esac
done

# 启动后台服务，依赖systemd
DDR_SHELL_FILE="/dev/shm/ota_shell.sh"
SHELL_FILE="$(readlink -f "${BASH_SOURCE[0]}")"
if [[ "$SHELL_FILE" != "${DDR_SHELL_FILE}" ]]; then
    rm -f "${DDR_SHELL_FILE}"
    cp "$SHELL_FILE" "${DDR_SHELL_FILE}"
    chmod +x "${DDR_SHELL_FILE}"
    cd /
    sudo systemctl stop sophon-ota-update.service 2>/dev/null
    sudo systemctl reset-failed sophon-ota-update.service 2>/dev/null
    sudo rm /run/systemd/transient/sophon-ota-update.service 2>/dev/null
    sudo systemctl daemon-reload 2>/dev/null
    systemd-run --unit=sophon-ota-update.service --collect bash -c "${DDR_SHELL_FILE} RUN_WORK_DIR=$(dirname \
$SHELL_FILE) LAST_PART_NOT_FLASH=${LAST_PART_NOT_FLASH} SHELL_NEED_AUTOBOOT_ONCE=${SHELL_NEED_AUTOBOOT_ONCE} \
SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR=${SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR}"
    if [[ "$?" != "0" ]]; then
        systemd-run --unit=sophon-ota-update.service bash -c "${DDR_SHELL_FILE} RUN_WORK_DIR=$(dirname \
$SHELL_FILE) LAST_PART_NOT_FLASH=${LAST_PART_NOT_FLASH} SHELL_NEED_AUTOBOOT_ONCE=${SHELL_NEED_AUTOBOOT_ONCE} \
SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR=${SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR}"
    fi
    systemctl status sophon-ota-update.service --no-page -l
    echo "[INFO] ota server started, check status use: \"systemctl status sophon-ota-update.service \
--no-page -l\""
    echo '[INFO] server log file: /dev/shm/ota_shell.sh.log'
    echo '[INFO] if ota success, file /dev/shm/ota_success_flag will be created'
    echo '[INFO] else if ota error, file /dev/shm/ota_error_flag will be created'
    echo '[INFO] please wait file /dev/shm/ota_success_flag or /dev/shm/ota_error_flag'
    echo "[WARRNING] ota server will resize last partition on emmc, if error, please check emmc \
partitions"
    echo '[WARRNING] ota server will stop docker server and all program on last partition'
    exit 0
fi

# 配置日志能力
LOGFILE="$(readlink -f "${BASH_SOURCE[0]}").log"
rm -f $LOGFILE*
exec > >(tee -a "$LOGFILE") 2>&1

echo "[INFO] ota update tool, version: v1.4.0"

WORK_DIR=""
if [ ! -d ${RUN_WORK_DIR}/sdcard ]; then
    echo "[INFO] cannot find sdcard, maybe in sdcard ..."
    md5file=$(find ${RUN_WORK_DIR} -type f -name "*md5*")
    file_validate ${md5file}
    file_validate ${RUN_WORK_DIR}/BOOT
    file_validate ${RUN_WORK_DIR}/boot.scr
    WORK_DIR=$(realpath ${RUN_WORK_DIR})
else
    WORK_DIR="$RUN_WORK_DIR"/sdcard
fi
echo "[INFO] work dir: $WORK_DIR"
WORD_DIR_ROOTFS_RW_REPACK="${SHELL_NEED_AUTOBOOT_ONCE_TEMP_DIR}/ota_update_rootfs_rw_repack_temp"
echo "[INFO] work dir rootfs rw repack: $WORD_DIR_ROOTFS_RW_REPACK"
pushd $WORK_DIR || panic "cannot pushd $WORK_DIR, please check files healthy"

if [[ "$LAST_PART_NOT_FLASH" == "0" ]]; then
    LAST_PART_NOT_FLASH="0"
    echo "[INFO] LAST_PART_NOT_FLASH mode disable"
else
    LAST_PART_NOT_FLASH="1"
    echo "[INFO] LAST_PART_NOT_FLASH mode enable"
fi

if [[ "$SHELL_NEED_AUTOBOOT_ONCE" != "" ]]; then
    echo "[INFO] SHELL_NEED_AUTOBOOT_ONCE is $SHELL_NEED_AUTOBOOT_ONCE"
    file_validate "${SHELL_NEED_AUTOBOOT_ONCE}"
fi

# 记录系统信息
echo "-----------------------------------------------------------"
echo "$(date)" >>"$LOGFILE"
echo "Info:" >>"$LOGFILE"
bm_version >>"$LOGFILE"
bm_get_basic_info >>"$LOGFILE"
cat /factory/OEMconfig.ini >>"$LOGFILE"
lsblk -f >>"$LOGFILE"
df -h >>"$LOGFILE"
lsusb >>"$LOGFILE"
lspci >>"$LOGFILE"
top -n1 >>"$LOGFILE"

# 使用MD5文件进行刷机包校验
echo "[INFO] md5 check start"
md5file=$(find . -type f -name "*md5*")
file_validate ${md5file}
md5sum -c ${md5file} &>>"$LOGFILE" || panic "md5 check error!!!"
echo "[INFO] md5 check success"

ota_cleanup() {
    wall "[OTA INFO] clean ..."
    echo "[INFO] clean ..."
	if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
        if [ -f $WORK_DIR/gpt.gz.ota_update_bak ]; then
            mv $WORK_DIR/gpt.gz.ota_update_bak $WORK_DIR/gpt.gz
        fi
    fi
    if [[ "$SHELL_NEED_AUTOBOOT_ONCE" != "" ]]; then
        if [[ -d "${WORD_DIR_ROOTFS_RW_REPACK}" ]]; then
            umount ${WORD_DIR_ROOTFS_RW_REPACK}/rootfs_rw_part_dir 2>/dev/null
            if [[ "$(ls $WORK_DIR/rootfs_rw.*-of-*.gz.bak 2>/dev/null | wc -l)" != "0" ]]; then
                pushd ${WORK_DIR}
                    rm -f rootfs_rw.*-of-*.gz
                    for f in rootfs_rw.*-of-*.gz.bak; do mv "$f" "${f%.bak}"; done
                popd
            fi
        fi
    fi
    mount -a
	exit 0
}
trap ota_cleanup EXIT SIGHUP SIGINT SIGQUIT SIGTERM

# 配置RW分区中的自动启动脚本
if [[ "$SHELL_NEED_AUTOBOOT_ONCE" != "" ]]; then
    echo "[INFO] configure rootfs_rw partition auto rootfs_rw once script start"
    if [[ "${WORD_DIR_ROOTFS_RW_REPACK}" == "" ]]; then
        panic "work dir rootfs rw repack not set"
    fi
    RANDOM_STR="$(openssl rand -hex 8)"
    umount ${WORD_DIR_ROOTFS_RW_REPACK}/rootfs_rw_part_dir 2>/dev/null
    rm -rf ${WORD_DIR_ROOTFS_RW_REPACK}
    mkdir -p ${WORD_DIR_ROOTFS_RW_REPACK}
    # 需要RW分区X2大小的内存空间
    cp ${WORK_DIR}/rootfs_rw.*-of-*.gz ${WORD_DIR_ROOTFS_RW_REPACK}/
    pushd ${WORD_DIR_ROOTFS_RW_REPACK}/
        echo "[INFO] dec rootfs_rw partition start"
        ls rootfs_rw.*-of-*.gz | sort -V | xargs cat | \
gunzip -c > rootfs_rw.part || panic "dec rootfs_rw partition error"
        mkdir rootfs_rw_part_dir
        mount rootfs_rw.part rootfs_rw_part_dir || panic "mount rootfs_rw partition error"
        mkdir -p rootfs_rw_part_dir/overlay/etc/systemd/system/
        mkdir -p rootfs_rw_part_dir/overlay/etc/systemd/system/multi-user.target.wants/
        mkdir -p rootfs_rw_part_dir/overlay/usr/sbin/
        echo "[Unit]
Description=autoboot after ota update, server id is ${RANDOM_STR}
After=network.target bmrt_setup.service bmrt_loadko.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c /usr/sbin/ota_autoboot_once_${RANDOM_STR}.sh
ExecStartPost=/bin/systemctl disable ota_autoboot_once_${RANDOM_STR}.service

[Install]
WantedBy=multi-user.target" > \
rootfs_rw_part_dir/overlay/etc/systemd/system/ota_autoboot_once_${RANDOM_STR}.service
        cp ${SHELL_NEED_AUTOBOOT_ONCE} rootfs_rw_part_dir/overlay/usr/sbin/ota_autoboot_once_${RANDOM_STR}.sh \
|| panic "copy ota_autoboot_once script error"
        chmod +x rootfs_rw_part_dir/overlay/usr/sbin/ota_autoboot_once_${RANDOM_STR}.sh
        pushd rootfs_rw_part_dir/overlay/etc/systemd/system/multi-user.target.wants/
            ln -s ../ota_autoboot_once_${RANDOM_STR}.service ota_autoboot_once_${RANDOM_STR}.service
        popd
        echo "[INFO] creat ota_autoboot_once_${RANDOM_STR}.service success"
        sync
        umount rootfs_rw_part_dir || panic "umount rootfs_rw partition error"
        sync
        rm -rf rootfs_rw.*-of-*.gz
        rm -rf rootfs_rw_part_dir
        SECTOR_BYTES=512
        chunk_size=200704
        count=1
        offset=0
        part_name="rootfs_rw"
        size=$(du -b rootfs_rw.part | awk '{print $1}')
        size=$(expr \( ${size} + ${SECTOR_BYTES} - 1 \) / ${SECTOR_BYTES})
        function compute_round_quotient()
        {
            local total_size=$1
            local unit_size=$2
            [ ${unit_size} -gt 0 ] || panic "bad unit_size ${unit_size} in compute_round_quotient()"
            expr \( ${total_size} + ${unit_size} - 1 \) / ${unit_size}
        }
        limit=$(compute_round_quotient ${size} ${chunk_size})
        while true; do
            filename=${part_name}.${count}-of-${limit};
            if [ ${size} -lt ${chunk_size} ]; then
                chunk_size=${size}
            fi
            dd status=none if=rootfs_rw.part of=${filename} bs=${SECTOR_BYTES} \
skip=${offset} count=${chunk_size} || panic "dd create part ${filename} from rootfs_rw.part error"
            pigz -v ${filename} || panic "gzip part ${filename} error"
            count=$(expr ${count} + 1)
            offset=$(expr ${offset} + ${chunk_size})
            echo "[INFO] create part ${filename} success, size: ${chunk_size} sectors, offset: ${offset} sectors"
            size=$(expr ${size} - ${chunk_size}) || break
        done
        rm -f rootfs_rw.part
        md5sum rootfs_rw.*-of-*.gz > rootfs_rw.md5
    popd
    pushd ${WORK_DIR}
        ls rootfs_rw.*-of-*.gz | sort -V | xargs -I{} mv {} {}.bak
        cp ${WORD_DIR_ROOTFS_RW_REPACK}/rootfs_rw.*-of-*.gz ./
    popd
fi

# 确定刷机包大小和刷机后占空空间
echo "[INFO] check update size check start"
set >>"$LOGFILE"
if [[ "$(find . -type f -name "partition*xml" | wc -l)" != "1" ]]; then
    panic "Unable to find one and only one partition.xml file."
fi
xmlfile=$(find . -type f -name "partition*xml")
file_validate ${xmlfile}
OTA_NEW_PACKAGE_GPT_PART_SIZE_KB=$(cat ${xmlfile} | grep "<physical_partition " | awk -F'"' '{print \
$2}')
OTA_NEW_ALL_PART_SIZE_KB=$(cat ${xmlfile} | grep "<partition " | awk -F'"' '{print $4}' | paste \
-sd+ - | bc)
OTA_NEW_LAST_PACK_NAME=$(cat ${xmlfile} | grep "<partition " | tail -n1 | awk -F'"' '{print $2}' | \
tr '[:upper:]' '[:lower:]')
OTA_EMMC_SIZE_KB=$(echo "$(lsblk -b | grep '^mmcblk0' | head -n1 | awk -F' ' '{print $4}') / 1024" \
| bc)
OTA_EMMC_SIZE_B=$(lsblk -b | grep '^mmcblk0' | head -n1 | awk -F' ' '{print $4}')
OTA_GPT_TEMP_FILE="/dev/shm/ota_gpt"
rm -f ${OTA_GPT_TEMP_FILE}
rm -f ${OTA_GPT_TEMP_DISK_FILE}
gzip -cd gpt.gz >${OTA_GPT_TEMP_FILE}
OTA_GPT_TEMP_DISK_FILE=${OTA_GPT_TEMP_FILE}.disk
dd if=${OTA_GPT_TEMP_FILE} of=${OTA_GPT_TEMP_DISK_FILE} || panic "dd write ota info to file \
${OTA_GPT_TEMP_DISK_FILE} error"
dd if=/dev/null of=${OTA_GPT_TEMP_DISK_FILE} bs=1 count=1 seek=${OTA_EMMC_SIZE_B} || panic "dd \
sparse file ${OTA_GPT_TEMP_DISK_FILE} error"
gdisk -l ${OTA_GPT_TEMP_DISK_FILE} 2>&1 >>"$LOGFILE"
# 获取emmc扇区大小
OTA_NEW_SECTOR_SIZE=$(gdisk -l ${OTA_GPT_TEMP_DISK_FILE} 2>&1 | grep "ector size" | awk -F' ' \
'{print $4}' | awk -F'/' '{print $1}')
if [[ "$EMMC_SECTOR_B" != "$OTA_NEW_SECTOR_SIZE" ]]; then
    panic "get emmc sector size [$OTA_NEW_SECTOR_SIZE] not is default size [$EMMC_SECTOR_B], please \
check emmc and gdisk tool"
fi
OTA_NEW_GPT_END_SECTOR=$(gdisk -l ${OTA_GPT_TEMP_DISK_FILE} 2>&1 | tail -n1 | awk -F' ' '{print \
$3}')
OTA_NEW_GPT_END_PART_START=$(gdisk -l ${OTA_GPT_TEMP_DISK_FILE} 2>&1 | tail -n1 | awk -F' ' '{print \
$2}')
OTA_NEW_GPT_END_SIZE_KB=$(echo "$OTA_NEW_SECTOR_SIZE * $OTA_NEW_GPT_END_SECTOR / 1024" | bc)
OTA_NEW_MAX_SIZE_KB=0
# 获取需要写入的范围
OTA_NEW_ALL_WRITE_OFFSET=0
EMMC_SECTOR_B=512
mapfile -t lines < <(grep "^mmc write" -a *.scr)
for line in "${lines[@]}"; do
    new_offset=0
    address="$(echo "$line" | awk -F' ' '{print $(NF-1)}')"
    size="$(echo "$line" | awk -F' ' '{print $(NF)}')"
    address=$(($address))
    size=$(($size))
    new_offset=$(echo "($address + $size) * $EMMC_SECTOR_B / 1024" | bc)
    if [ $OTA_NEW_ALL_WRITE_OFFSET -lt $new_offset ]; then
        OTA_NEW_ALL_WRITE_OFFSET=$new_offset
    fi
done
echo "[INFO] write all max offset: $OTA_NEW_ALL_WRITE_OFFSET KB"
if [ $OTA_NEW_MAX_SIZE_KB -lt $OTA_NEW_PACKAGE_GPT_PART_SIZE_KB ]; then
    OTA_NEW_MAX_SIZE_KB=$OTA_NEW_PACKAGE_GPT_PART_SIZE_KB
fi
if [ $OTA_NEW_MAX_SIZE_KB -lt $OTA_NEW_ALL_PART_SIZE_KB ]; then
    OTA_NEW_MAX_SIZE_KB=$OTA_NEW_ALL_PART_SIZE_KB
fi
if [ $OTA_NEW_MAX_SIZE_KB -lt $OTA_NEW_GPT_END_SIZE_KB ]; then
    OTA_NEW_MAX_SIZE_KB=$OTA_NEW_GPT_END_SIZE_KB
fi
if [ $OTA_NEW_MAX_SIZE_KB -lt $OTA_NEW_ALL_WRITE_OFFSET ]; then
    OTA_NEW_MAX_SIZE_KB=$OTA_NEW_ALL_WRITE_OFFSET
fi
OTA_PACK_SIZE_KB=$(ls -l --block-size=K | awk -F' ' '{print $5}' | tr -d 'K' | sed '/^$/d' | paste \
-sd+ - | bc)
# 如果需要保留最后一个分区，则判断新旧分区表最后一个分区的起始点是否相同
if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
    OTA_OLD_GPT_END_PART_START=$(gdisk -l /dev/mmcblk0 2>&1 | tail -n 1 | awk '{print $2}')
    if [[ "$OTA_OLD_GPT_END_PART_START" != "$OTA_NEW_GPT_END_PART_START" ]] || [[ \
"$OTA_NEW_GPT_END_PART_START" == "" ]]; then
        panic "LAST_PART_NOT_FLASH mode, check last part start [$OTA_NEW_GPT_END_PART_START] != \
[$OTA_OLD_GPT_END_PART_START]"
    fi
    echo "[INFO] LAST_PART_NOT_FLASH mode, check last part start [$OTA_NEW_GPT_END_PART_START] = \
[$OTA_OLD_GPT_END_PART_START]"
fi
# 保留最后一个分区的情况下，最后分区的刷机包不计大小
if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
    OTA_PACK_SIZE_KB=$(ls -l --block-size=K | grep -v "${OTA_NEW_LAST_PACK_NAME}." | awk -F' ' \
'{print $5}' | tr -d 'K' | sed '/^$/d' | paste -sd+ - | bc)
fi
OTA_NEED_SIZE_KB=$OTA_NEW_MAX_SIZE_KB
echo "[INFO] update need size: $OTA_NEED_SIZE_KB KB"
echo "[INFO] emmc size: $OTA_EMMC_SIZE_KB KB"
if [ $OTA_EMMC_SIZE_KB -le $OTA_NEED_SIZE_KB ]; then
    panic "check update size error!!!"
fi
# 判断最后一个分区是否已经扩容
OTA_EMMC_PART_SIZE=$(lsblk -b /dev/mmcblk0 | grep -v "^mmcblk0" | grep "mmcblk0" | awk -F' ' \
'{print $4}' | paste -sd+ - | bc)
OTA_EMMC_PART_SIZE=$(($OTA_EMMC_PART_SIZE + $OTA_EMMC_PART_SIZE / 10))
if [ $OTA_EMMC_SIZE_KB -gt $OTA_EMMC_PART_SIZE ]; then
    panic "check update size error, all partitions less than 90% of the emmc space!!!"
fi
echo "[INFO] check update size check success"

# 判断fip是否和芯片相配合
file_validate boot.cmd
file_validate boot_emmc.cmd
OTA_PACK_READ_FILE_CMD="load"
if [[ "$(cat boot.cmd | grep -a ^tftp | wc -l)" != "0" ]]; then
    OTA_PACK_READ_FILE_CMD="tftp"
elif [[ "$(cat boot.cmd | grep -a ^cvi_utask | wc -l)" != "0" ]]; then
    OTA_PACK_READ_FILE_CMD="cvi_utask"
elif [[ "$(cat boot.cmd | grep -a ^load | wc -l)" != "0" ]]; then
    OTA_PACK_READ_FILE_CMD="load"
else
    panic "cannot get update pack type"
fi
OTA_EMMC_UPDATE_CMD_FILE=$(cat boot_emmc.cmd | grep -a "^${OTA_PACK_READ_FILE_CMD}" | \
grep boot_emmc | awk -F' ' '{print $NF}' | awk -F'/' '{print $NF}')
OTA_FIP_UPDATE_CMD_FILE=$(cat boot.cmd | grep -a "^${OTA_PACK_READ_FILE_CMD}" | \
head -n1 | awk -F' ' '{print $NF}' | awk -F'/' '{print $NF}')
file_validate ${OTA_FIP_UPDATE_CMD_FILE}
OTA_FIP_FILE=$(cat $OTA_FIP_UPDATE_CMD_FILE | grep -a "^${OTA_PACK_READ_FILE_CMD}" | \
awk -F' ' '{print $NF}' | awk -F'/' '{print $NF}')
if [[ "$OTA_FIP_UPDATE_CMD_FILE" == "" ]]; then
    panic "cannot find fip update cmd file"
fi
if [[ "$OTA_FIP_FILE" == "" ]]; then
    panic "cannot find fip file"
fi
echo "[INFO] Check fip file and chip type start"
if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
    if [[ "$(grep -ra ${CPU_MODEL}- ${OTA_FIP_FILE} | wc -l)" == "0" ]]; then
        panic "chip is ${CPU_MODEL}, but fip file not have info about it"
    fi
elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
    if [[ "$(grep -ra CVBL01 ${OTA_FIP_FILE} | wc -l)" == "0" ]] || \
[[ "$(grep -ra CVLD02 ${OTA_FIP_FILE} | wc -l)" == "0" ]]; then
        panic "chip is ${CPU_MODEL}, but fip file not have info about it"
    fi
fi
echo "[INFO] Check fip file and chip type success"

# 缩小最后一个分区，空出刷机包大小的空间
echo "[INFO] resize last part to write update pack start"
set >>"$LOGFILE"
OTA_LAST_DEVICE=/dev/$(lsblk -l -o NAME /dev/mmcblk0 | tail -n1)
OTA_LAST_DEVICE_MOUNT_POINT=$(df | grep "${OTA_LAST_DEVICE}" | awk -F' ' '{print $6}')
OTA_LAST_DEVICE_SIZE_KB=$(echo "$(lsblk -b ${OTA_LAST_DEVICE} | tail -n1 | awk -F' ' '{print $4}') \
/ 1024" | bc)
OTA_PACK_NUM=$(ls -l ./ | wc -l)
# 最后一个分区后预留100MB空间，并且每一个包开始都是一个扇区对齐
## 100MB空间=末尾20MB预留不写入+80MB写入升级脚本
OTA_LAST_DEVICE_NEW_SIZE_KB=$(echo "$OTA_LAST_DEVICE_SIZE_KB - $OTA_PACK_SIZE_KB - ($OTA_PACK_NUM) \
- (10 * 1024) - (100 * 1024)" | bc)
OTA_PACK_WRITE_START_SECTOR=$(echo "($OTA_EMMC_SIZE_KB - $OTA_PACK_SIZE_KB - ($OTA_PACK_NUM) - (100 \
* 1024)) * (1024 / $EMMC_SECTOR_B)" | bc)
echo "[INFO] last device $OTA_LAST_DEVICE need resize $OTA_LAST_DEVICE_SIZE_KB KB -> \
$OTA_LAST_DEVICE_NEW_SIZE_KB KB"
cd /
echo "[INFO] kill process of ${OTA_LAST_DEVICE_MOUNT_POINT} start"
systemctl stop docker
echo "[INFO] fuser find need kill: "
fuser -mk "${OTA_LAST_DEVICE}"
fuser -mk "${OTA_LAST_DEVICE}"
fuser -mk "${OTA_LAST_DEVICE}"
fuser -mk "${OTA_LAST_DEVICE}"
fuser -mk "${OTA_LAST_DEVICE}"
echo "[INFO] kill process of ${OTA_LAST_DEVICE_MOUNT_POINT} success"
for i in {1..50}; do
    fuser -mk "${OTA_LAST_DEVICE}"
    umount -f "${OTA_LAST_DEVICE}"
    df | grep "${OTA_LAST_DEVICE}"
done
if [[ "$(df | grep ${OTA_LAST_DEVICE} | wc -l)" != "0" ]]; then
    panic "umount ${OTA_LAST_DEVICE} error!!!"
fi
e2fsck -yf ${OTA_LAST_DEVICE}
resize2fs -f ${OTA_LAST_DEVICE} ${OTA_LAST_DEVICE_NEW_SIZE_KB}K
if [[ "$?" != "0" ]]; then
    panic "resize2fs ${OTA_LAST_DEVICE} -> ${OTA_LAST_DEVICE_NEW_SIZE_KB}K, please check if your \
eMMC partition is healthy"
fi
mount -a
cd $WORK_DIR
if [[ "$?" != "0" ]]; then
    panic "cannot cd $WORK_DIR, please check files healthy"
fi
echo "[INFO] resize last part to write update pack success"

# 保留最后一个分区的情况下，拷贝当前emmc分区表最后一个分区的配置到新的
# 分区表文件中
if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
    echo "[INFO] LAST_PART_NOT_FLASH mode, need change gpt info"
    sgdisk -e ${OTA_GPT_TEMP_DISK_FILE} || panic "sgdisk change file ${OTA_GPT_TEMP_DISK_FILE} \
error"
    OTA_GPT_PART_NUM=$(fdisk -l ${OTA_GPT_TEMP_DISK_FILE} 2>&1 | grep "^${OTA_GPT_TEMP_DISK_FILE}" \
| wc -l)
    OTA_OLD_GPT_END_PART_END=$(($OTA_OLD_GPT_END_PART_START + $OTA_LAST_DEVICE_NEW_SIZE_KB * 1024 / \
$EMMC_SECTOR_B))
    echo -e \
"d\n${OTA_GPT_PART_NUM}\nn\n${OTA_GPT_PART_NUM}\n${OTA_OLD_GPT_END_PART_START}\n${OTA_OLD_GPT_END_PA\
RT_END}\n0700\nw\nY\n" | gdisk ${OTA_GPT_TEMP_DISK_FILE}
    gdisk -l ${OTA_GPT_TEMP_DISK_FILE}
    dd if=${OTA_GPT_TEMP_DISK_FILE} of=${OTA_GPT_TEMP_FILE} bs=1 count=17408 || panic "dd sparse \
file new info ${OTA_GPT_TEMP_DISK_FILE} to gpt file ${OTA_GPT_TEMP_FILE} error"
    mv gpt.gz gpt.gz.ota_update_bak
    gzip -c ${OTA_GPT_TEMP_FILE} >gpt.gz || panic "gzip file ${OTA_GPT_TEMP_FILE} to gpt.gz error"
    sync
fi

# 生成刷机文件emmc中存储位置表
echo "[INFO] Generate Upgrade Package File Address Data Table start"
set >>"$LOGFILE"
OTA_FIP_FLASH_OFFSET=()
OTA_FIP_FLASH_SIZE=()
IFS=$'\n'
for item in $(cat $OTA_FIP_UPDATE_CMD_FILE | grep -a ^mmc | grep write); do
    if [[ -z "$item" ]]; then
        continue
    fi
    OTA_FIP_FLASH_OFFSET+=("$(echo "$item" | awk -F' ' '{print $(NF-1)}')")
    OTA_FIP_FLASH_SIZE+=("$(echo "$item" | awk -F' ' '{print $NF}')")
done
IFS=$original_ifs
echo "[INFO] fip file: $OTA_FIP_FILE"
for ((item = 0; item < ${#OTA_FIP_FLASH_OFFSET[@]}; item++)); do
    echo "[INFO] fip file flash to emmcboot1 ${OTA_FIP_FLASH_OFFSET[$item]}, size: \
${OTA_FIP_FLASH_SIZE[$item]}"
done
offset=$(echo "$OTA_PACK_WRITE_START_SECTOR + 0" | bc)
size=$(echo "scale=0; $(stat -c %s $OTA_FIP_FILE) / $EMMC_SECTOR_B + 1" | bc)
OTA_FIP_WRITE_OFFSET=$(printf '0x%X' $offset)
OTA_FIP_WRITE_SIZE=$(printf '0x%X' $size)
OTA_UPDATE_PACK_WRITE_OFFSET=$(($OTA_FIP_WRITE_OFFSET + $OTA_FIP_WRITE_SIZE))
echo "[INFO] fip file write to emmc offset: $OTA_FIP_WRITE_OFFSET, size: $OTA_FIP_WRITE_SIZE"
unset OTA_EMMC_FLASH_OFFSET
unset OTA_EMMC_FLASH_SIZE
unset OTA_EMMC_FLASH_UNZIP_SIZE
unset OTA_EMMC_WRITE_OFFSET
unset OTA_EMMC_WRITE_SIZE
unset OTA_EMMC_MD5SUM
declare -A OTA_EMMC_FLASH_OFFSET
declare -A OTA_EMMC_FLASH_SIZE
declare -A OTA_EMMC_FLASH_UNZIP_SIZE
declare -A OTA_EMMC_WRITE_OFFSET
declare -A OTA_EMMC_WRITE_SIZE
declare -A OTA_EMMC_MD5SUM
OTA_EMMC_FILES=()
IFS=$'\n'
for emmc_boot_file in $(echo "${OTA_EMMC_UPDATE_CMD_FILE}"); do
    if [[ -z "$emmc_boot_file" ]]; then
        continue
    fi
    # 在保留最后分区时需要跳过最后一个分区的记录
    if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
        if [[ "$emmc_boot_file" == *"$OTA_NEW_LAST_PACK_NAME"* ]]; then
            echo "[INFO] skip cmd file $emmc_boot_file because LAST_PART_NOT_FLASH mode"
            continue
        fi
    fi
    for item in $(cat $emmc_boot_file | grep -aE "^${OTA_PACK_READ_FILE_CMD} |^unzip |^mmc write"); do
        if [[ -z "$item" ]]; then
            continue
        fi
        if [[ "$item" == "${OTA_PACK_READ_FILE_CMD} "* ]]; then
            filename="$(echo "$item" | awk -F' ' '{print $NF}' | awk -F'/' '{print $NF}')"
            size=$(echo "scale=0; $(stat -c %s $filename) / $EMMC_SECTOR_B + 1" | bc)
            OTA_EMMC_FILES+=($filename)
            OTA_EMMC_WRITE_OFFSET["$filename"]=$(printf '0x%X' $OTA_UPDATE_PACK_WRITE_OFFSET)
            OTA_EMMC_WRITE_SIZE["$filename"]=$(printf '0x%X' $size)
            OTA_UPDATE_PACK_WRITE_OFFSET=$(($OTA_UPDATE_PACK_WRITE_OFFSET + $size))
        elif [[ "$item" == "unzip "* ]]; then
            OTA_EMMC_FLASH_UNZIP_SIZE["${OTA_EMMC_FILES[-1]}"]=$(echo "$item" | awk -F' ' '{print \
$(NF)}')
        elif [[ "$item" == "mmc write"* ]]; then
            OTA_EMMC_FLASH_OFFSET["${OTA_EMMC_FILES[-1]}"]=$(echo "$item" | awk -F' ' '{print \
$(NF-1)}')
            OTA_EMMC_FLASH_SIZE["${OTA_EMMC_FILES[-1]}"]=$(echo "$item" | awk -F' ' '{print $(NF)}')
        fi
    done
done
IFS=$original_ifs
for ((item = 0; item < ${#OTA_EMMC_FILES[@]}; item++)); do
    filename=${OTA_EMMC_FILES[$item]}
    echo -e "[INFO] file $filename
\t flash emmc offset: ${OTA_EMMC_FLASH_OFFSET["$filename"]},
\t size: ${OTA_EMMC_FLASH_SIZE["$filename"]},
\t unzip size: ${OTA_EMMC_FLASH_UNZIP_SIZE["$filename"]},
\t write to emmc offset: ${OTA_EMMC_WRITE_OFFSET["$filename"]},
\t size: ${OTA_EMMC_WRITE_SIZE["$filename"]}"
done
echo "[INFO] Generate Upgrade Package File Address Data Table success"

# 生成刷机文件
echo "[INFO] Generate Upgrade Script start"
set >>"$LOGFILE"
OTA_UPDATE_SCRIPT_FILE=$LOGFILE.update.cmd
random_string=$(< /dev/urandom tr -dc 'A-Za-z0-9' | head -c 10)
echo "$led_env_str" >>$OTA_UPDATE_SCRIPT_FILE
flash_pre_str+="
# random str: $random_string
$otaenvsetup_str
run otaenvset;
setenv ota_uf_add 'setenv OTA_UPDATE_FLAG \${OTA_UPDATE_FLAG}.'
setenv ota_uf_clear 'setenv OTA_UPDATE_FLAG .'
if test -z \"\$OTA_UPDATE_FLAG\"; then
run ota_uf_clear
fi
setenv ota_update_flag_add1 ';\
run ota_uf_add;\
if test \${UBOOT_ENV_SUPPORT_OTA_ENABLE} = 1; then \
saveenv;fi;echo update flag: \${OTA_UPDATE_FLAG};\
'
echo \"OTA UPDATE START...[flag: \${OTA_UPDATE_FLAG}]\";
"
echo "$flash_pre_str" >>$OTA_UPDATE_SCRIPT_FILE

echo "if test \${OTA_UPDATE_FLAG} = .; then" >>$OTA_UPDATE_SCRIPT_FILE
if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
    echo "echo Program $OTA_FIP_FILE start
mmc dev 0
mmc read \${ramdisk_addr_r} ${OTA_FIP_WRITE_OFFSET} ${OTA_FIP_WRITE_SIZE}
if test \$? -eq 0; then
sf probe
if test \$? -ne 0; then
setenv LED_OTA_ERROR_FLAG 3
run led_ota_flash_error
run led_ota_flash_error
run led_ota_flash_error
reset
fi
print chip_type
" >>$OTA_UPDATE_SCRIPT_FILE
    if [[ " ${OTA_EMMC_FILES[@]} " == *"system."* ]]; then
        flash_update_cmd="sf update \${ramdisk_addr_r} 0x0 0x120000"
    else
        flash_update_cmd="if test \"\$chip_type\" = \"bm1684\"; then sf update \${ramdisk_addr_b} 0x0 \
0x200000; else sf update \${ramdisk_addr_r} 0x0 0x200000; fi; \
echo update section A done; \
if test \"\$chip_type\" = \"bm1684\"; then sf update \${ramdisk_addr_b} 0x200000 \
0x200000; else sf update \${ramdisk_addr_r} 0x200000 0x200000; fi;
echo update section B done;"
    fi
    echo "$flash_update_cmd" >>$OTA_UPDATE_SCRIPT_FILE
    echo "else
echo skip SPI flash update.
fi
echo Program fip.bin done
" >>$OTA_UPDATE_SCRIPT_FILE
elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
    echo "
cmp.b 0x05207f82 0x05207f83 1; if test \$? -eq 1; then setenv consoledev ttyS2; fi
echo Program $OTA_FIP_FILE start
mmc dev 0
mmc read \${ramdisk_addr_r} ${OTA_FIP_WRITE_OFFSET} ${OTA_FIP_WRITE_SIZE}
if test \$? -eq 0; then
mmc dev 0 1
if test \$? -ne 0; then
setenv LED_OTA_ERROR_FLAG 3
run led_ota_flash_error
run led_ota_flash_error
run led_ota_flash_error
reset
fi
" >>$OTA_UPDATE_SCRIPT_FILE
    for ((item = 0; item < ${#OTA_FIP_FLASH_OFFSET[@]}; item++)); do
        echo "mmc write \${ramdisk_addr_r} ${OTA_FIP_FLASH_OFFSET[$item]} \
${OTA_FIP_FLASH_SIZE[$item]}" >>$OTA_UPDATE_SCRIPT_FILE
    done
    echo "
else
echo skip fip flash.
fi
echo Program fip.bin done
" >>$OTA_UPDATE_SCRIPT_FILE
fi

echo "
run led_ota_flash_run_flash;
run ota_update_flag_add1;
fi
" >>$OTA_UPDATE_SCRIPT_FILE

for ((item = 0; item < ${#OTA_EMMC_FILES[@]}; item++)); do
    filename=${OTA_EMMC_FILES[$item]}
    item2=$((item + 2))
    echo "if test \${OTA_UPDATE_FLAG} = $(printf "%${item2}s" | tr ' ' '.'); then
echo Program $filename start
mmc dev 0
mmc read \${ramdisk_addr_r} ${OTA_EMMC_WRITE_OFFSET["$filename"]} \
${OTA_EMMC_WRITE_SIZE["$filename"]}
if test \$? -ne 0; then
setenv LED_OTA_ERROR_FLAG 4
run led_ota_flash_error
run led_ota_flash_error
run led_ota_flash_error
reset;fi;
echo
unzip \${ramdisk_addr_r} \${unzip_addr} ${OTA_EMMC_FLASH_UNZIP_SIZE["$filename"]}
if test \$? -ne 0; then
setenv LED_OTA_ERROR_FLAG 5
run led_ota_flash_error
run led_ota_flash_error
run led_ota_flash_error
reset; fi;
echo
mmc write \${unzip_addr} ${OTA_EMMC_FLASH_OFFSET["$filename"]} ${OTA_EMMC_FLASH_SIZE["$filename"]}
if test \$? -ne 0; then
setenv LED_OTA_ERROR_FLAG 6
run led_ota_flash_error
run led_ota_flash_error
run led_ota_flash_error
reset; fi;
echo
echo Program $filename done
" >>$OTA_UPDATE_SCRIPT_FILE

    echo "
run led_ota_flash_run_flash;
run ota_update_flag_add1;
fi
" >>$OTA_UPDATE_SCRIPT_FILE

    if [[ "$(($item % 10))" == "0" ]]; then
        echo "
bm_savelog mmc 0:1 ota_update_$(($item / 10)).log" >>$OTA_UPDATE_SCRIPT_FILE
    fi
done

echo "$flash_post_str" >>$OTA_UPDATE_SCRIPT_FILE

mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "boot.scr" -d $OTA_UPDATE_SCRIPT_FILE \
$OTA_UPDATE_SCRIPT_FILE.scr
if [[ "$?" != "0" ]]; then
    panic "mkimage error!!!"
fi
OTA_UPDATE_SCRIPT_FILE_MD5=$(md5sum $OTA_UPDATE_SCRIPT_FILE.scr | awk -F' ' '{print $1}' | tr -d '\n')
OTA_UPDATE_SCRIPT_FILE_OFFSET=$(($OTA_UPDATE_PACK_WRITE_OFFSET))
OTA_UPDATE_SCRIPT_FILE_SIZE=$(echo "scale=0; $(stat -c %s $OTA_UPDATE_SCRIPT_FILE.scr) / $EMMC_SECTOR_B + 1" | bc)
OTA_UPDATE_PACK_WRITE_OFFSET=$(($OTA_UPDATE_SCRIPT_FILE_OFFSET + $OTA_UPDATE_SCRIPT_FILE_SIZE))
echo "[INFO] Generate Upgrade Script success"

# 生成刷机启动文件
echo "[INFO] Generate Upgrade boot Script start"
set >>"$LOGFILE"
OTA_UPDATE_BOOT_SCRIPT_FILE=$LOGFILE.boot.cmd

echo "$led_env_str" >>$OTA_UPDATE_BOOT_SCRIPT_FILE

echo "$otaenvsetup_str" >>$OTA_UPDATE_BOOT_SCRIPT_FILE

echo "
setenv otacmd 'run otaenvset;mmc dev 0;\
mmc read \${scriptaddr} $(printf '0x%X' $OTA_UPDATE_SCRIPT_FILE_OFFSET) \
$(printf '0x%X' $OTA_UPDATE_SCRIPT_FILE_SIZE);\
if test \$? -ne 0; then setenv LED_OTA_ERROR_FLAG 1;run led_ota_flash_error;\
run led_ota_flash_error;run led_ota_flash_error;reset;fi;\
source \${scriptaddr};\
if test \$? -ne 0; then setenv LED_OTA_ERROR_FLAG 2;run led_ota_flash_error;\
run led_ota_flash_error;run led_ota_flash_error;reset;fi;\
'" >>$OTA_UPDATE_BOOT_SCRIPT_FILE

echo '
echo OTA update boot start
if test -z $UBOOT_ENV_SUPPORT_OTA_ENABLE || test $UBOOT_ENV_SUPPORT_OTA_ENABLE != 1; then
echo "UBOOT ENV SUPPORT OTA DISABLED!!!"
setenv UBOOT_ENV_SUPPORT_OTA_ENABLE 0
else
echo "UBOOT ENV SUPPORT OTA ENABLED!!!"
setenv bootcmd_otabak "${bootcmd}"
setenv bootcmd "cvi_update || run otacmd"
run ota_uf_clear
saveenv
fi
run otacmd
reset
' >>$OTA_UPDATE_BOOT_SCRIPT_FILE

mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "boot.scr" -d $OTA_UPDATE_BOOT_SCRIPT_FILE \
$OTA_UPDATE_BOOT_SCRIPT_FILE.scr
if [[ "$?" != "0" ]]; then
    panic "mkimage error!!!"
fi
echo "[INFO] Generate Upgrade boot Script success"

# 将包写入emmc
echo "[INFO] Write packs to emmc start"
set >>"$LOGFILE"
dd if="$OTA_FIP_FILE" of=/dev/mmcblk0 bs=$EMMC_SECTOR_B seek=$((${OTA_FIP_WRITE_OFFSET} + 0)) \
count=$((${OTA_FIP_WRITE_SIZE} + 0)) status=progress
if [[ "$?" != "0" ]]; then
    panic "Write file $OTA_FIP_FILE to emmc error!!!"
fi
for ((item = 0; item < ${#OTA_EMMC_FILES[@]}; item++)); do
    filename=${OTA_EMMC_FILES[$item]}
    echo -e "[INFO] write file $filename
    \t to emmc offset: ${OTA_EMMC_WRITE_OFFSET["$filename"]},
    \t size: ${OTA_EMMC_WRITE_SIZE["$filename"]}"
    file_validate $filename
    dd if=$filename of=/dev/mmcblk0 bs=$EMMC_SECTOR_B \
seek=$((${OTA_EMMC_WRITE_OFFSET["$filename"]})) count=$((${OTA_EMMC_WRITE_SIZE["$filename"]})) \
status=progress
    if [[ "$?" != "0" ]]; then
        panic "Write file $filename to emmc error!!!"
    fi
done
dd if=/dev/zero of=/dev/mmcblk0 bs=$EMMC_SECTOR_B \
seek=${OTA_UPDATE_SCRIPT_FILE_OFFSET} count=$(($OTA_UPDATE_SCRIPT_FILE_SIZE + 1)) status=progress
dd if=$OTA_UPDATE_SCRIPT_FILE.scr of=/dev/mmcblk0 bs=$EMMC_SECTOR_B \
seek=${OTA_UPDATE_SCRIPT_FILE_OFFSET} count=${OTA_UPDATE_SCRIPT_FILE_SIZE} status=progress
if [[ "$?" != "0" ]]; then
    panic "Write file $OTA_UPDATE_SCRIPT_FILE.scr to emmc error!!!"
fi
sync
echo "[INFO] Write packs to emmc success"

echo "[INFO] Write update script to boot start"
set >>"$LOGFILE"
if [ ! -f boot.scr.emmc.otabak ]; then
    cp /boot/boot.scr.emmc /boot/boot.scr.emmc.otabak
    if [[ "$?" != "0" ]]; then
        panic "cp /boot/boot.scr.emmc error!!!"
    fi
fi
cp $OTA_UPDATE_BOOT_SCRIPT_FILE.scr /boot/boot.scr.emmc
if [[ "$?" != "0" ]]; then
    panic "cp $OTA_UPDATE_BOOT_SCRIPT_FILE.scr error!!!"
fi
echo "[INFO] Write update script to boot success"

echo "[INFO] wait sync ..."
sync
echo 1 >/proc/sys/vm/drop_caches
echo 2 >/proc/sys/vm/drop_caches
echo 3 >/proc/sys/vm/drop_caches
sync

echo "[INFO] chack pack md5sum on emmc start ..."
set >>"$LOGFILE"
OTA_FIP_MD5SUM_EMMC=$(dd if=/dev/mmcblk0 bs=${EMMC_SECTOR_B} \
skip=$((${OTA_FIP_WRITE_OFFSET})) count=$((${OTA_FIP_WRITE_SIZE})) | \
head -c $(stat -c %s $OTA_FIP_FILE) | md5sum)
OTA_FIP_MD5SUM_FILE=$(dd if=${OTA_FIP_FILE} | md5sum)
if [[ "$OTA_FIP_MD5SUM_EMMC" != "$OTA_FIP_MD5SUM_FILE" ]]; then
    panic "check fip md5sum for emmc [$OTA_FIP_MD5SUM_EMMC] and file [$OTA_FIP_MD5SUM_FILE]"
fi
echo "[INFO] check fip md5sum: $OTA_FIP_MD5SUM_EMMC"
for ((item = 0; item < ${#OTA_EMMC_FILES[@]}; item++)); do
    filename=${OTA_EMMC_FILES[$item]}
    OTA_EMMC_MD5SUM["$filename"]=$(dd if=/dev/mmcblk0 bs=$EMMC_SECTOR_B \
skip=$((${OTA_EMMC_WRITE_OFFSET["$filename"]})) \
count=$((${OTA_EMMC_WRITE_SIZE["$filename"]})) | head -c $(stat -c %s $filename) | md5sum)
    OTA_EMMC_MD5SUM_FILE=$(dd if=${filename} | md5sum)
    if [[ "${OTA_EMMC_MD5SUM["$filename"]}" != "$OTA_EMMC_MD5SUM_FILE" ]]; then
        panic "check file $filename md5sum for emmc [${OTA_EMMC_MD5SUM["$filename"]}] \
and file [$OTA_EMMC_MD5SUM_FILE]"
    fi
    echo "[INFO] check file $filename md5sum: ${OTA_EMMC_MD5SUM["$filename"]}"
done
OTA_UPDATE_CMD_MD5=$(dd if=/dev/mmcblk0 bs=$EMMC_SECTOR_B \
skip=${OTA_UPDATE_SCRIPT_FILE_OFFSET} \
count=${OTA_UPDATE_SCRIPT_FILE_SIZE} \
| head -c $(stat -c %s $OTA_UPDATE_SCRIPT_FILE.scr) | md5sum | awk -F' ' '{print $1}')
if [[ "$OTA_UPDATE_SCRIPT_FILE_MD5" != "$OTA_UPDATE_CMD_MD5" ]]; then
    panic "check file $OTA_UPDATE_SCRIPT_FILE.scr md5sum for emmc [${OTA_UPDATE_SCRIPT_FILE_MD5}] \
and file [$OTA_UPDATE_CMD_MD5]"
fi
echo "[INFO] check file $OTA_UPDATE_SCRIPT_FILE.scr md5sum: ${OTA_UPDATE_CMD_MD5}"
echo "[INFO] chack pack md5sum on emmc success"

set >>"$LOGFILE"
if [[ "$LAST_PART_NOT_FLASH" == "1" ]]; then
    if [ -f gpt.gz.ota_update_bak ]; then
        mv gpt.gz.ota_update_bak gpt.gz
    fi
fi
if [[ "$SHELL_NEED_AUTOBOOT_ONCE" != "" ]]; then
    if [[ -d "${WORD_DIR_ROOTFS_RW_REPACK}" ]]; then
        umount ${WORD_DIR_ROOTFS_RW_REPACK}/rootfs_rw_part_dir 2>/dev/null
        if [[ "$(ls $WORK_DIR/rootfs_rw.*-of-*.gz.bak | wc -l)" != "0" ]]; then
            pushd ${WORK_DIR}
                rm -f rootfs_rw.*-of-*.gz
                for f in rootfs_rw.*-of-*.gz.bak; do mv "$f" "${f%.bak}"; done
            popd
        fi
    fi
fi
popd #sdcard
sync
echo "[INFO] Upgrade preparation is complete. Please restart the device to begin the upgrade."
touch /dev/shm/ota_success_flag
sync
# You can uncomment the line below to automatically reboot after the OTA preparation is complete.
reboot -f
while true; do
    wall "[OTA] Upgrade preparation is complete. Please restart the device to begin the upgrade."
    sleep 5
done
