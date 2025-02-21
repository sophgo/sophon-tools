#!/bin/bash

GET_INFO_VERSION="1.1.0"

shopt -s compat31

function panic()
{
    if [ $# -gt 0 ]; then
        echo "" >&1
        echo "ERROR: $@" >&1
        echo "" >&1
    fi
    exit 1
}

function cmd_validate()
{
    if command -v "$1" >/dev/null 2>&1; then
        echo "1"
    else
        echo "0"
    fi
}

function file_validate()
{
    local file
    file=$(eval echo \$1)
    [ -r ${file} ] || panic "$i \"$file\" is not readable"
}

# [jump byte] [size] [file]
function od_read_char() {
    od -An -v -j ${1} -N ${2} -t c -w${2} ${3} 2>/dev/null | sed 's| \\0| |g' | sed 's| \\n| |g' | sed 's| \\r| |g' | tr -d ' '
}

function od_read_hex() {
    od -An -v -j ${1} -N ${2} -t x -w${2} ${3} 2>/dev/null | sed 's| \\0| |g' | sed 's| \\n| |g' | sed 's| \\r| |g' | tr -d ' '
}

function od_read_dec_big() {
    info=$(od -An --endian=big -v -j ${1} -N ${2} -t u -w${2} ${3} 2>/dev/null | sed 's| \\0| |g' | sed 's| \\n| |g' | sed 's| \\r| |g' | tr -d ' ')
    if [[ "$info" == "" ]]; then
        echo "0"
    else
        echo "$info"
    fi
}

function write_to_file() {
    echo "$2" | tee "$1" &>/dev/null
}

# [i2c bus] [i2c addr(HEX)]
function get_i2c_dev_ok() {
    if [[ "$(cmd_validate i2cdetect)" == "0" ]]; then
        echo "err"
    fi
    i2c_bus=$1
    i2c_add=$2
    info=$(i2cdetect -y -r ${i2c_bus} 0x${i2c_add} 0x${i2c_add} 2>/dev/null | grep ${i2c_add} | tr -d ' ' | sed 's/.*://')
    if [[ "$info" == "$i2c_add" ]]; then
        echo "ok"
    else
        echo "err"
    fi
}

# [ion path]
function get_ion_usage()
{
    local path
    path=$(eval echo \$1)
    if [ -f "$path"/total_mem ]; then
        total=$(cat "$path"/total_mem 2>/dev/null)
        alloc=$(cat "$path"/alloc_mem 2>/dev/null)
        usage=$(echo "scale=2; ($alloc / $total) * 100" | bc)
        echo "$usage"
    else
        echo "0"
    fi
}

function jsonq() {
    json=$(cat)
    awk -v json="$json" -v json_orgi="$json" -v key="$1" '
    function strlastchar(s) {
        return substr(s, length(s), 1)
    }
    function startwith(s, c) {
        start = substr(s, 1, 1)
        return start == c
    }
    function endwith(s, c) {
        return strlastchar(s) == c
    }
    function innerstr(s) { # 取出括号/引号内的内容
        return substr(s, 2, length(s)-2)
    }
    function strindex(s, n) { # 字符串通过下标取值，索引是从1开始的
        return substr(s, n, 1)
    }
    function trim(s) {
        sub("^[ \n]*", "", s);
        sub("[ \n]*$", "", s);
        return s
    }
    function findValueByKey(s, k) {
        if ("\""k"\"" != substr(s, 1, length(k)+2)) {exit 0}
        s = trim(s)
        start = 0; stop = 0; layer = 0
        for (i = 2 + length(k) + 1; i <= length(s); ++i) {
            lastChar = substr(s, i - 1, 1)
            currChar = substr(s, i, 1)
            if (start <= 0) {
                if (lastChar == ":") {
                    start = currChar == " " ? i + 1: i
                    if (currChar == "{" || currChar == "[") {
                        layer = 1
                    }
                }
            } else {
                if (currChar == "{" || currChar == "[") {
                    ++layer
                }
                if (currChar == "}" || currChar == "]") {
                    --layer
                }
                if ((currChar == "," || currChar == "}" || currChar == "]") && layer <= 0) {
                    stop = currChar == "," ? i : i + 1 + layer
                    break
                }
            }
        }
        if (start <= 0 || stop <= 0 || start > length(s) || stop > length(s) || start >= stop) {
            exit 0
        } else {
            return trim(substr(s, start, stop - start))
        }
    }
    function unquote(s) {
        if (startwith(s, "\"")) {
            s = substr(s, 2, length(s)-1)
        }
        if (endwith(s, "\"")) {
            s = substr(s, 1, length(s)-1)
        }
        return s
    }
    BEGIN{
        if (match(key, /^\./) == 0) {exit 0;}
        sub(/\][ ]*\[/,"].[", key)
        split(key, ks, ".")
        if (length(ks) == 1) {print json; exit 0}
        for (j = 2; j <= length(ks); j++) {
            k = ks[j]
            if (startwith(k, "[") && endwith(k, "]") == 1) { # [n]
                idx = innerstr(k)
                currentIdx = -1
                # 找匹配对
                pairs = ""
                json = trim(json)
                if (startwith(json, "[") == 0) {
                    exit 0
                }
                start = 2
                cursor = 2
                for (; cursor <= length(json); cursor++) {
                    current = strindex(json, cursor)
                    if (current == " " || current == "\n") {continue} # 忽略空白
                    if (current == "[" || current == "{") {
                        if (length(pairs) == 0) {start = cursor}
                        pairs = pairs""current
                    }
                    if (current == "]" || current == "}") {
                        if ((strlastchar(pairs) == "[" && current == "]") || (strlastchar(pairs) == "{" && current == "}")) {
                            pairs = substr(pairs, 1, length(pairs)-1) # 删掉最后一个字符
                            if (pairs == "") { # 匹配到了所有的左括号
                                currentIdx++
                                if (currentIdx == idx) {
                                    json = substr(json, start, cursor-start+1)
                                    break
                                }
                            }
                        } else {
                            pairs = pairs""current
                        }
                    }
                }
            } else {
                # 到这里，就只能是{"key": "value"}或{"key":{}}或{"key":[{}]}
                pairs = ""
                json = trim(json)
                if (startwith(json, "[")) {exit 0}
                #if (!startwith(json, "\"") || !startwith(json, "{")) {json="\""json}
                # 找匹配的键
                start = 2
                cursor = 2
                noMatch = 0
                for (; cursor <= length(json); cursor++) {
                    current = strindex(json, cursor)
                    if (current == " " || current == "\n" || current == ",") {continue} # 忽略空白和逗号
                    if (substr(json, cursor, length(k)+2) == "\""k"\"") {
                        json = findValueByKey(substr(json, cursor, length(json)-cursor+1), k)
                        break
                    } else {
                        noMatch = 1
                    }
                    if (noMatch) {
                        pos = match(substr(json, cursor+1, length(json)-cursor), /[^(\\")]"/)
                        ck = substr(substr(json, cursor+1, length(json)-cursor), 1, pos)
                        t = findValueByKey(substr(json, cursor, length(json)-cursor+1), ck)
                        tLen = length(t)
                        sub(/\\/, "\\\\", t)
                        pos = match(substr(json, cursor+1, length(json)-cursor), t)
                        if (pos != 0) {
                            cursor = cursor + pos + tLen
                        }
                        noMatch = 0
                        continue
                    }
                }
            }
        }
        if (json_orgi == json) { print;exit 0 }
        print unquote(json)
    }'
}

function logs_path_mode() {
    # 日志目录最大占用空间
    DIR_SIZE_MAX_KB=$((10 * 1024))
    # 单个未压缩的日志文件最大占用空间
    LOG_FILE_SIZE_MAX_B=$((1 * 1024 * 1024))
    # 日志目录
    GET_INFO_LOGS_DIR="${1}"
    # 临时存储目录
    TEMP_FILE=/dev/shm/get_info_log.tmp
    # 日志记录命令
    LOG_CMD="${2}"
    # 每次记录间隔时间
    SLEEP_TIME=${3}

    rm -f ${TEMP_FILE}
    if [ ! -d $GET_INFO_LOGS_DIR ]; then
        mkdir -p $GET_INFO_LOGS_DIR
    fi

    # 获取最后一个文件
    function get_last_file()
    {
        last_num=$(ls *_get_info.lo* 2>/dev/null | cut -d'_' -f1 | sort -n | tail -n1)
        ls ${last_num}_*_get_info.lo* 2>/dev/null
    }

    # 获取合适的日志文件路径
    function get_log_file()
    {
        name_date=$(date +%m-%d-%H-%M-%S)
        last_file=$(get_last_file)
        if [[ "${last_file}" != "" ]]; then
            last_id=$(echo $last_file | cut -d'_' -f1)
        else
            last_id=0
            touch ${last_id}_${name_date}_get_info.log &>/dev/null
            sync
            last_file="${last_id}_${name_date}_get_info.log"
        fi
        if [[ "$last_file" == *".gz" ]]; then
            # 最后一个日志已经被压缩，新建新的日志文件
            last_id=$(( ${last_id} + 1 ))
            touch ${last_id}_${name_date}_get_info.log &>/dev/null
            sync
            last_file="${last_id}_${name_date}_get_info.log"
        else
            file_size_b=$(stat -c %s ${last_file})
            if [ ${file_size_b} -gt ${LOG_FILE_SIZE_MAX_B} ]; then
                # 当前文件大于1M，进行压缩
                gzip -9 -c ${last_file} > ${last_file}.gz
                sync
                rm -f ${last_file} &>/dev/null
                sync
                last_id=$(( ${last_id} + 1 ))
                touch ${last_id}_${name_date}_get_info.log &>/dev/null
                sync
                last_file="${last_id}_${name_date}_get_info.log"
            fi
        fi
        echo "${last_file}"
    }

    # 获取最早的一个文件
    function get_first_file()
    {
        first_num=$(ls *_get_info.lo* 2>/dev/null | cut -d'_' -f1 | sort -n | head -n1)
        ls ${first_num}_*_get_info.lo* 2>/dev/null
    }

    # 删除最早的一个文件
    function rm_first_file()
    {
        first_file=$(get_first_file)
        if [ -f $first_file ]; then
            rm -f $first_file
            sync
            echo "INFO: rm first file [$first_file]"
        else
            echo "ERROR: first file [$first_file]"
        fi
    }

    pushd $GET_INFO_LOGS_DIR
    while true; do
        sleep ${SLEEP_TIME}
        while true; do
            # 判断当前目录是否已经大于最大大小，大于的话删除最早的一个文件
            DIR_SIZE_KB=$(du . -s | awk -F' ' '{print $1}')
            if [ "$DIR_SIZE_KB" == "" ]; then
                echo "ERROR: DIR_SIZE_KB: [${DIR_SIZE_KB}]KB"
            fi
            if [ ${DIR_SIZE_KB} -gt ${DIR_SIZE_MAX_KB} ]; then
                echo "INFO: DRI SIZE: [${DIR_SIZE_KB}] > MAX SIZE: [${DIR_SIZE_MAX_KB}]"
                rm_first_file
            else
                break
            fi
            sleep 0.5
        done
        LOG_FILE_PATH=$(get_log_file)
        echo "INFO: write info to file [${LOG_FILE_PATH}] at $(date +%m-%d-%H-%M-%S)"
        eval $LOG_CMD > ${TEMP_FILE}
        cat ${TEMP_FILE} >> ${LOG_FILE_PATH}
        sync
    done
    popd #GET_INFO_LOGS_DIR
}

file_validate /proc/cpuinfo
file_validate /proc/stat

if [[ "$1" == "server" ]] && [[ ! "$2" == "" ]] && [[ ! "$3" == "" ]]; then
    if [[ "$(cmd_validate systemd-run)" == "0" ]] || [[ "$(cmd_validate systemctl)" == "0" ]]; then
        echo "cannot find systemd at systemd, cannot run as server mode!!!";
        exit -1
    fi
    log_file="$(readlink -f "$2")"
    loop_wait_time="$3"
    get_info_pwd="$(readlink -f "$0")"
    echo "log write to file:${log_file}"
    echo "wait time in loop(s):${loop_wait_time}"
    echo "get_info pwd:${get_info_pwd}"
    if [[ "$4" == "y" ]]; then
            systemctl stop sophon-get-info-server.service
            systemctl reset-failed sophon-get-info-server.service
            systemd-run --unit=sophon-get-info-server /usr/bin/bash -c "export GET_INFO_PMBUS_ENABLE=${GET_INFO_PMBUS_ENABLE}; source /etc/profile; ldconfig; while true; do sleep ${loop_wait_time}; bash ${get_info_pwd} 2>/dev/null 1>> ${log_file}; done;"
            sleep 3
            systemctl status sophon-get-info-server.service --no-page -l
            exit 0
    fi
    read -p "Do you acknowledge the information above? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]
    then
            systemctl stop sophon-get-info-server.service
            systemctl reset-failed sophon-get-info-server.service
            systemd-run --unit=sophon-get-info-server /usr/bin/bash -c "export GET_INFO_PMBUS_ENABLE=${GET_INFO_PMBUS_ENABLE}; source /etc/profile; ldconfig; while true; do sleep ${loop_wait_time}; bash ${get_info_pwd} 2>/dev/null 1>> ${log_file}; done;"
            sleep 3
            systemctl status sophon-get-info-server.service --no-page -l
            exit 0
    else
            exit -1
    fi
elif [[ "$1" == "server_logs_path" ]] && [[ ! "$2" == "" ]] && [[ ! "$3" == "" ]]; then
    logs_path="$(readlink -f "$2")"
    loop_wait_time="$3"
    get_info_pwd="/usr/bin/bash $(readlink -f "$0")"
    systemctl stop sophon-get-info-server-logs-path.service
    systemctl reset-failed sophon-get-info-server-logs-path.service
    fun_str=$(declare -f logs_path_mode | gzip -c - | base64)
    systemd-run --unit=sophon-get-info-server-logs-path /usr/bin/bash -c "export GET_INFO_PMBUS_ENABLE=${GET_INFO_PMBUS_ENABLE}; source /etc/profile; ldconfig; source /dev/stdin <<< \$(echo \"$fun_str\" | base64 -d | gzip -d -c -);logs_path_mode \"${logs_path}\" \"${get_info_pwd}\" ${loop_wait_time};"
    sleep 3
    systemctl status sophon-get-info-server-logs-path.service --no-page -l
    exit 0
fi

# BOOT_TIME(S)
BOOT_TIME=0
BOOT_TIME=$(cat /proc/uptime 2>/dev/null | awk '{print $1}')

# DATE_TIME
DATE_TIME=$(date +"%Y-%m-%d %H:%M:%S %Z")

# CPU NAME
CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
# ! [[ "$CPU_MODEL" == "" ]] || panic "cannot get cpu model from /proc/cpuinfo"

# WORK MODE
SOC_MODE_CPU_MODEL=("bm1684x" "bm1684" "bm1688" "cv186ah")
WORK_MODE="PCIE"
for element in "${SOC_MODE_CPU_MODEL[@]}"; do
    if [ "$element" == "$CPU_MODEL" ]; then
        WORK_MODE="SOC"
        break
    fi
done
if [[ "${WORK_MODE}" == "PCIE" ]]; then
    file_validate /dev/bmdev-ctl
fi

# SHUTDOWN_REASON
SHUTDOWN_REASON=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    declare -A SHUTDOWN_REASON_HEX_MAP
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        SHUTDOWN_REASON_HEX_MAP["00000000"]="NO_INFO"
        SHUTDOWN_REASON_HEX_MAP["00000080"]="POWER_OFF"
        SHUTDOWN_REASON_HEX_MAP["00000081"]="RESET"
        SHUTDOWN_REASON_HEX_MAP["00000082"]="REBOOT"
        SHUTDOWN_REASON_HEX_MAP["00000083"]="OVER_HEAT"
        SHUTDOWN_REASON_HEX_MAP["00000084"]="WATCHDOG"
        for bootfile in $(ls /root/.boot/ 2>/dev/null); do
            S_INFO=$(od_read_hex 0 4 /root/.boot/$bootfile)
            F_INFO=$(echo $bootfile | sed 's|.txt||g')
            REASON="${SHUTDOWN_REASON_HEX_MAP["$S_INFO"]}"
            if [[ "$REASON" == "" ]]; then
                REASON="$F_INFO"
            fi
            SHUTDOWN_REASON+="$F_INFO,$REASON " 2>/dev/null
        done
        SHUTDOWN_REASON=$(echo -n $SHUTDOWN_REASON | sed 's/ \+$//')
    fi
fi

# DDR INFO
DDR_SIZE=0
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        DTS_MEM_FILE="/proc/device-tree/memory/reg"
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        DTS_MEM_FILE="/proc/device-tree/memory*/reg"
    fi
    DDR_SIZE=0
    IFS=$'\n'
    for line in $(od --endian=big -An -v -t u4 -w16 ${DTS_MEM_FILE}); do
        size1=$(echo "$line" | awk '{print $3}')
        size2=$(echo "$line" | awk '{print $4}')
        ddr_s=$(( size1 * 1024 * 1024 * 1024 * 4 + size2 ))
        DDR_SIZE=$((DDR_SIZE + ddr_s))
    done
    IFS=$' \t\n'
    DDR_SIZE=$(( DDR_SIZE / 1024 / 1024 ))
fi

# EMMC_SIZE
EMMC_SIZE=0
if [[ "${WORK_MODE}" == "SOC" ]]; then
    EMMC_SIZE_BYTE=$(lsblk -b 2>/dev/null | grep "^mmcblk0 " | awk '{print $4}')
    EMMC_SIZE=$(( EMMC_SIZE_BYTE / 1024 / 1024 ))
fi

# MEM_INFO
SYSTEM_MEM="0"
TPU_MEM="0"
VPU_MEM="0"
VPP_MEM="0"
if [[ "${WORK_MODE}" == "SOC" ]]; then
    SYSTEM_MEM=$(vmstat -s 2>/dev/null | grep "total memory" | awk '{print $1}')
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        TPU_MEM=$(cat /sys/kernel/debug/ion/bm_npu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPU_MEM=$(cat /sys/kernel/debug/ion/bm_vpu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPP_MEM=$(cat /sys/kernel/debug/ion/bm_vpp_heap_dump/total_mem 2>/dev/null | tr -d '\0')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        TPU_MEM=$(cat /sys/kernel/debug/ion/cvi_npu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPP_MEM=$(cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/total_mem 2>/dev/null | tr -d '\0')
    fi
    SYSTEM_MEM=$(( SYSTEM_MEM / 1024 ))
    TPU_MEM=$(( TPU_MEM / 1024 / 1024 ))
    VPU_MEM=$(( VPU_MEM / 1024 / 1024 ))
    VPP_MEM=$(( VPP_MEM / 1024 / 1024 ))
fi

# SYSTEM_MEM_USAGE
SYSTEM_MEM_USAGE=$(free -k | grep '^Mem: ' | awk '{free=$7; total=$2; printf "%.2f\n", ((total-free)/total)*100}' 2>/dev/null)

# CPU_ALL_USAGE
unset CPU_ALL_USAGE
unset CPUS_USAGE
CPU_ALL_USAGE=""
CPUS_USAGE=""
function get_cpu_all() {
    cpu_num=$(cat /proc/stat 2>/dev/null | grep "^cpu" 2>/dev/null | wc -l)
    cpu_count=$((cpu_num - 1))
    proc_stat1=$(cat /proc/stat)
    sleep 0.5
    proc_stat2=$(cat /proc/stat)
    awk -v proc_stat1="$(echo "$proc_stat1" | grep '^cpu ')" -v proc_stat2="$(echo "$proc_stat2" | grep '^cpu ')" '
    BEGIN {
        split(proc_stat1, a);
        split(proc_stat2, b);
        total1 = a[2] + a[3] + a[4] + a[5] + a[6] + a[7] + a[8];
        total2 = b[2] + b[3] + b[4] + b[5] + b[6] + b[7] + b[8];
        total = total2 - total1;
        user = (b[2] + b[3]) - (a[2] + a[3])
        kernel = b[4] - a[4];
        io_wait = b[6] - a[6];
        irq = (b[7] + b[8]) - (a[7] + a[8])
        idle = b[5] - a[5];
        usage = (total - idle) / total * 100;
        user_u = user / total * 100;
        ker_u = kernel / total * 100;
        irq_u = irq / total * 100;
        io_u = io_wait / total * 100;
        printf "%.2f,%.2f,%.2f,%.2f,%.2f ", usage, user_u, ker_u, io_u, irq_u;
    }' 2>/dev/null
    for ((i=0; i<cpu_count; i++)); do
        awk -v proc_stat1="$(echo "$proc_stat1" | grep "^cpu$i ")" -v proc_stat2="$(echo "$proc_stat2" | grep "^cpu$i ")" '
        BEGIN {
            split(proc_stat1, a);
            split(proc_stat2, b);
            total1 = a[2] + a[3] + a[4] + a[5] + a[6] + a[7] + a[8];
            total2 = b[2] + b[3] + b[4] + b[5] + b[6] + b[7] + b[8];
            total = total2 - total1;
            user = (b[2] + b[3]) - (a[2] + a[3])
            kernel = b[4] - a[4];
            io_wait = b[6] - a[6];
            irq = (b[7] + b[8]) - (a[7] + a[8])
            idle = b[5] - a[5];
            usage = (total - idle) / total * 100;
            user_u = user / total * 100;
            ker_u = kernel / total * 100;
            irq_u = irq / total * 100;
            io_u = io_wait / total * 100;
            printf "%.2f,%.2f,%.2f,%.2f,%.2f ", usage, user_u, ker_u, io_u, irq_u;
        }' 2>/dev/null
    done
    echo ""
}
{ read -r CPU_ALL_USAGE CPUS_USAGE; } <<< "$(get_cpu_all)"

# DTS_NAME
DTS_NAME=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        DTS_NAME=$(cat /proc/device-tree/info/file-name 2>/dev/null | tr -d '\0')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        DTS_NAME=$(od_read_char 160 32 "/dev/mmcblk0boot1")
    fi
fi

# DEVICE_MODEL
DEVICE_MODEL=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        DEVICE_MODEL=$(grep "model" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        DEVICE_MODEL_PRODUCT=$(od_read_char 208 16 "/dev/mmcblk0boot1")
        DEVICE_MODEL_MODULE_TYPE=$(od_read_char 112 16 "/dev/mmcblk0boot1")
        DEVICE_MODEL="${DEVICE_MODEL_PRODUCT} ${DEVICE_MODEL_MODULE_TYPE}"
    fi
fi

# CLKs
CPU_CLK=""
TPU_CLK=""
VPU_CLK=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        CPU_CLK=$(cat /sys/kernel/debug/clk/clk_div_a53_1/clk_rate 2>/dev/null| tr -d '\0')
        TPU_CLK=$(cat /sys/kernel/debug/clk/tpll_clock/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(cat /sys/kernel/debug/clk/clk_gate_axi10/clk_rate 2>/dev/null| tr -d '\0')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        CPU_CLK=$(cat /sys/kernel/debug/clk/clk_a53pll/clk_rate 2>/dev/null| tr -d '\0')
        TPU_CLK=$(cat /sys/kernel/debug/clk/clk_tpll/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(cat /sys/kernel/debug/clk/clk_cam0pll/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(( VPU_CLK / 2 ))
    fi
fi

# SN
CHIP_SN=""
DEVICE_SN=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        # CHIP_SN=$(grep "product sn" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}')
        CHIP_SN=$(od_read_char 0 32 "/sys/bus/nvmem/devices/1-006a0/nvmem")
        DEVICE_SN=$(od_read_char 512 32 "/sys/bus/nvmem/devices/1-006a0/nvmem")
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        CHIP_SN=$(od_read_char 0 32 "/dev/mmcblk0boot1")
        DEVICE_SN=$(od_read_char 32 32 "/dev/mmcblk0boot1")
    fi
fi

# MAC
ETH0_MAC=""
ETH1_MAC=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    ETH0_MAC=$(ip link show eth0 2>/dev/null | grep ether | awk '{print $2}')
    ETH1_MAC=$(ip link show eth1 2>/dev/null | grep ether | awk '{print $2}')
fi

# CHIP_TEMP
declare -i CHIP_TEMP=0
if [[ "${WORK_MODE}" == "SOC" ]]; then
    CHIP_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null| tr -d '\0')
    CHIP_TEMP=$(( CHIP_TEMP / 1000 ))
fi

# BOARD_TEMP
declare -i BOARD_TEMP=0
if [[ "${WORK_MODE}" == "SOC" ]]; then
        if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
                BOARD_TEMP=$(cat /sys/class/thermal/thermal_zone1/temp 2>/dev/null| tr -d '\0')
                BOARD_TEMP=$(( BOARD_TEMP / 1000 ))
        fi
fi

# FAN_FREQUENCY
declare -i FAN_FREQUENCY=0
declare -i FAN_RPM=0
if [[ "${WORK_MODE}" == "SOC" ]]; then
        if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
                write_to_file /sys/class/bm-tach/bm-tach-0/enable 1
                FAN_FREQUENCY=$(cat /sys/class/bm-tach/bm-tach-0/fan_speed 2>/dev/null| sed 's|fan_speed:||g')
                if [[ "$FAN_FREQUENCY" != "0" ]]; then
                        FAN_RPM=$(echo | awk "{printf \"%.0f\n\", 60 / (1 / $FAN_FREQUENCY * 2) }" 2>/dev/null)
                else
                        FAN_RPM=0
                fi
        fi
fi

# DTS_THERMAL_TEMP
DTS_THERMAL_TEMP=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        declare -i temp
        temp=$(od_read_dec_big 0 32 /proc/device-tree/thermal-zones/soc/trips/soc_tpuclk440m_trip/temperature)
        temp=$(($temp / 1000))
        DTS_THERMAL_TEMP="$temp"
        temp=$(od_read_dec_big 0 32 /proc/device-tree/thermal-zones/soc/trips/soc_tpuclk75m_trip/temperature)
        temp=$(($temp / 1000))
        DTS_THERMAL_TEMP="$DTS_THERMAL_TEMP $temp"
        temp=$(od_read_dec_big 0 32 /proc/device-tree/thermal-zones/soc/trips/soc_crit_trip/temperature)
        temp=$(($temp / 1000))
        DTS_THERMAL_TEMP="$DTS_THERMAL_TEMP $temp"
    fi
fi

# VTPU_POWER
VTPU_POWER=""
VTPU_VOLTAGE=""
VDDC_POWER=""
VDDC_VOLTAGE=""
if [[ "$GET_INFO_PMBUS_ENABLE" == "1" ]]; then
    if [[ "${WORK_MODE}" == "SOC" ]]; then
            if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
            PMBUS_INFO=""
            if [[ "$(get_i2c_dev_ok 0 50)" == "ok" ]]; then
                PMBUS_INFO=$(pmbus -d 0 -s 0x50 -i 2>/dev/null)
            elif [[ "$(get_i2c_dev_ok 0 55)" == "ok" ]]; then
                PMBUS_INFO=$(pmbus -d 0 -s 0x55 -i 2>/dev/null)
            fi
            VTPU_POWER=$(echo "$PMBUS_INFO" | grep " output power:" | awk 'NR % 2 == 1' | awk '{print $4}' | tr -d 'W')
            VTPU_VOLTAGE=$(echo "$PMBUS_INFO" | grep " output voltage:" | awk 'NR % 2 == 1' | awk '{print $4}' | tr -d 'm' | tr -d 'V')
            VDDC_POWER=$(echo "$PMBUS_INFO" | grep " output power:" | awk 'NR % 2 == 0' | awk '{print $4}' | tr -d 'W')
            VDDC_VOLTAGE=$(echo "$PMBUS_INFO" | grep " output voltage:" | awk 'NR % 2 == 0' | awk '{print $4}' | tr -d 'm' | tr -d 'V')
            fi
    fi
fi

# V12_POWER
V12_POWER=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
        if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
            if [[ "$(cmd_validate i2cget)" == "1" ]]; then
                pw_h=$(i2cget -f -y 1 0x17 0x25 2>/dev/null)
                pw_l=$(i2cget -f -y 1 0x17 0x24 2>/dev/null)
                pw_dh=$((pw_h))
                pw_dl=$((pw_l))
                pw_dh_256=$(($pw_dh * 256))
                V12_POWER=$(($pw_dh_256 + $pw_dl))
            fi
        fi
fi

# TPU_USAGE
TPU_USAGE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        TPU_USAGE=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage 2>/dev/null| awk -F':' '{print $2}' | awk '{print $1}')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        TPU_USAGE=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage 2>/dev/null| awk -F':' '{print $2}' | awk '{print $1}' | tr '\n' ' ' | sed 's/ *$//')
    fi
fi

# VPU_USAGE
VPU_USAGE=""
VPP_USAGE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        VPU_USAGE=$(cat /proc/vpuinfo 2>/dev/null| tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/ $//' | sed 's/,$//')
        VPP_USAGE=$(cat /proc/vppinfo 2>/dev/null| tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/ $//' | sed 's/,$//')
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        VPU_USAGE=$(cat /proc/soph/vpuinfo 2>/dev/null| tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/ $//' | sed 's/,$//')
    fi
fi

# DEVICE_MEM_USAGE
TPU_MEM_USAGE="0"
VPU_MEM_USAGE="0"
VPP_MEM_USAGE="0"
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_npu_heap_dump")
        VPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpu_heap_dump")
        VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpp_heap_dump")
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_npu_heap_dump")
        VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_vpp_heap_dump")
    fi
fi

# BOARD_TYPE
BOARD_TYPE=""
MCU_VERSION=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        BOARD_TYPE=$(grep "board type" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}' 2>/dev/null)
        MCU_VERSION=$(grep "mcu version" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}' 2>/dev/null)
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        mcu_reg=$(busybox devmem 0x05026024 2>/dev/null)
        mcu_1=$(( (mcu_reg & 0xFF0000) >> 16 ))
        mcu_2=$(( (mcu_reg & 0xFF00) >> 8 ))
        mcu_3=$(( (mcu_reg & 0xFF) >> 0 ))
        MCU_VERSION="$mcu_1"."$mcu_2"."$mcu_3"
    fi
fi

# KERNEL_VERSION
KERNEL_VERSION="$(uname -r)"
KERNEL_BUILD_TIME="$(uname -v)"

# SYSTEM_TYPE
SYSTEM_TYPE=$(head -n 1 /etc/issue 2>/dev/null | sed 's| \\n||g' | sed 's| \\l||g')

# DOCKER_VERSION
DOCKER_VERSION=""
if [[ "$(cmd_validate docker)" == "1" ]]; then
    DOCKER_VERSION=$(docker --version 2>/dev/null | sed 's| \\n||g')
fi

# MMC0_CID
if [[ "${WORK_MODE}" == "SOC" ]]; then
    MMC0_CID=$(cat /sys/class/mmc_host/mmc0/mmc0\:0001/cid 2>/dev/null | sed 's| \\n||g')
fi

# DISK_INFO
DISK_INFO=$(df -T 2>/dev/null | grep ^/dev | awk '{printf "%s%s:%s", (NR==1 ? "" : " "), $7, $6} END {print ""}')

# SDK_VERSION
SDK_VERSION=""
LIBSOPHON_VERSION=""
SOPHON_MEDIA_VERSION=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
        if [[ "${KERNEL_VERSION}" == "5.4."* ]]; then
            SDK_VERSION=$(/usr/sbin/bm_version 2>/dev/null | grep "SophonSDK version" | sed 's|SophonSDK version: ||g')
            LIBSOPHON_VERSION=$(readlink /opt/sophon/libsophon-current 2>/dev/null | awk -F'-' '{print $2}')
            SOPHON_MEDIA_VERSION=$(readlink /opt/sophon/sophon-ffmpeg-latest 2>/dev/null | awk -F'_' '{print $2}')
        elif [[ "${KERNEL_VERSION}" == "4.9."* ]]; then
            SDK_VERSION=$(grep "VERSION" /system/data/buildinfo.txt 2>/dev/null | awk '{print $2}')
        fi
    elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
        SDK_VERSION=$(/usr/sbin/bm_version 2>/dev/null | grep "Gemini_SDK" | sed 's|Gemini_SDK: ||g')
        LIBSOPHON_VERSION=$(readlink /opt/sophon/libsophon-current 2>/dev/null | awk -F'-' '{print $2}')
        SOPHON_MEDIA_VERSION=$(readlink /opt/sophon/sophon-ffmpeg-latest 2>/dev/null | awk -F'_' '{print $2}')
    fi
else
    DRIVER_RELEASE_VERSION=$(cat /proc/bmsophon/driver_version 2>/dev/null | awk -F':' '{print $2}' | awk '{print $1}')
    DRIVER_RELEASE_TIME=$(cat /proc/bmsophon/driver_version 2>/dev/null | awk -F':' '{print $3}' | awk '{print $1}')
    LIBSOPHON_VERSION=$(readlink /opt/sophon/libsophon-current 2>/dev/null | awk -F'-' '{print $2}')
    SOPHON_MEDIA_VERSION=$(readlink /opt/sophon/sophon-ffmpeg-latest 2>/dev/null | awk -F'_' '{print $2}')
fi

# PCIE_INFO
CARD_NUM=""
CHIP_NUM=""
if [[ "${WORK_MODE}" == "PCIE" ]]; then
    CARD_NUM=$(cat /proc/bmsophon/card_num)
    CHIP_NUM=$(cat /proc/bmsophon/chip_num)
    for i in $(seq 0 $((CARD_NUM - 1))); do
        eval "CARD${i}_TYPE='$(cat /proc/bmsophon/card${i}/board_type)'"
        eval "CARD${i}_CHIP_ID='$(cat /proc/bmsophon/card${i}/bmsophon*/tpuid | sort -n | tr '\n' ' ' | sed 's/ *$//')'"
        eval "CARD${i}_CHIP_NUM='$(cat /proc/bmsophon/card${i}/chip_num_on_card)'"
        eval "CARD${i}_CHIP_TYPE='$(cat /proc/bmsophon/card${i}/chipid)'"
        eval "CARD${i}_SN='$(cat /proc/bmsophon/card${i}/sn)'"
        eval "CARD${i}_POWER='$(cat /proc/bmsophon/card${i}/board_power | awk '{print $1}')'"
        eval "CARD${i}_TEMP='$(cat /proc/bmsophon/card${i}/board_temp | awk '{print $1}')'"
        eval "CARD${i}_BOARD_VERSION='$(cat /proc/bmsophon/card${i}/board_version)'"
        eval "CARD_CHIP_ID=$(echo \"\$CARD${i}_CHIP_ID\")"
        eval "CARD${i}_CHIP_DDR_SIZE=''"
        eval "CARD${i}_CHIP_POWER=''"
        eval "CARD${i}_CHIP_TEMP=''"
        eval "CARD${i}_TPU_FREQ=''"
        eval "CARD${i}_TPU_USAGE=''"
        eval "CARD${i}_VPU_USAGE=''"
        for k in ${CARD_CHIP_ID}; do
            eval "CARD${i}_CHIP_DDR_SIZE+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/ddr_capacity | tr -d 'g' | awk '{print $NF}') '"
            eval "CARD${i}_CHIP_HEAP_SIZE+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/heap | awk '{print $4}' | tr -d ',' | while read -r hex; do decimal=$(printf "%d" $hex); echo "scale=0; $decimal / 1024 / 1024" | bc; done | tr '\n' ',' | sed 's/,$//') '"
            eval "CARD${i}_CHIP_POWER+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/chip_power | awk '{print $1}') '"
            eval "CARD${i}_CHIP_TEMP+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/chip_temp | awk '{print $1}') '"
            eval "CARD${i}_TPU_FREQ+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^tpu: | awk '{print $2}') '"
            eval "CARD${i}_VPU_FREQ+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^vpu: | awk '{print $2}') '"
            eval "CARD${i}_DDR_FREQ+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^ddr: | awk '{print $2}') '"
            eval "CARD${i}_TPU_USAGE+='$(cat /sys/class/bm-sophon/bm-sophon${k}/device/npu_usage | awk -F':' '{print $2}' | awk '{print $1}') '"
            eval "CARD${i}_VPU_USAGE+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/media | tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/,$//'; echo ' ')'"
            eval "CARD${i}_JPU_USAGE+='$(cat /proc/bmsophon/card${i}/bmsophon${k}/jpu | tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/,$//'; echo ' ')'"
        done
        eval "CARD${i}_CHIP_DDR_SIZE=\$(echo \$CARD${i}_CHIP_DDR_SIZE | sed 's/ *$//')"
        eval "CARD${i}_CHIP_HEAP_SIZE=\$(echo \$CARD${i}_CHIP_HEAP_SIZE | sed 's/ *$//')"
        eval "CARD${i}_CHIP_POWER=\$(echo \$CARD${i}_CHIP_POWER | sed 's/ *$//')"
        eval "CARD${i}_CHIP_TEMP=\$(echo \$CARD${i}_CHIP_TEMP | sed 's/ *$//')"
        eval "CARD${i}_TPU_FREQ=\$(echo \$CARD${i}_TPU_FREQ | sed 's/ *$//')"
        eval "CARD${i}_VPU_FREQ=\$(echo \$CARD${i}_VPU_FREQ | sed 's/ *$//')"
        eval "CARD${i}_DDR_FREQ=\$(echo \$CARD${i}_DDR_FREQ | sed 's/ *$//')"
        eval "CARD${i}_TPU_USAGE=\$(echo \$CARD${i}_TPU_USAGE | sed 's/ *$//')"
        eval "CARD${i}_VPU_USAGE=\$(echo \$CARD${i}_VPU_USAGE | sed 's/ *$//')"
        eval "CARD${i}_JPU_USAGE=\$(echo \$CARD${i}_JPU_USAGE | sed 's/ *$//')"
    done
fi

# VIEW INFO
if [[ "${WORK_MODE}" == "SOC" ]]; then
    echo "BOOT_TIME(s)|${BOOT_TIME}|"
    echo "DATE_TIME|${DATE_TIME}|"
    echo "WORK_MODE|${WORK_MODE}|"
    echo "CPU_MODEL|${CPU_MODEL}|"
    echo "SHUTDOWN_REASON|${SHUTDOWN_REASON}|"
    echo "DDR_SIZE(MiB)|${DDR_SIZE}|"
    echo "EMMC_SIZE(MiB)|${EMMC_SIZE}|"
    echo "SYSTEM_MEM(MiB)|${SYSTEM_MEM}|"
    echo "TPU_MEM(MiB)|${TPU_MEM}|"
    echo "VPU_MEM(MiB)|${VPU_MEM}|"
    echo "VPP_MEM(MiB)|${VPP_MEM}|"
    echo "TPU_MEM_USAGE(%)|${TPU_MEM_USAGE}|"
    echo "VPU_MEM_USAGE(%)|${VPU_MEM_USAGE}|"
    echo "VPP_MEM_USAGE(%)|${VPP_MEM_USAGE}|"
    echo "CPU_ALL_USAGE(%)|${CPU_ALL_USAGE}|"
    echo "CPUS_USAGE(%)|${CPUS_USAGE}|"
    echo "VPU_USAGE(%)|${VPU_USAGE}|"
    echo "VPP_USAGE(%)|${VPP_USAGE}|"
    echo "SYSTEM_MEM_USAGE(%)|${SYSTEM_MEM_USAGE}|"
    echo "DTS_NAME|${DTS_NAME}|"
    echo "DEVICE_MODEL|${DEVICE_MODEL}|"
    echo "CPU_CLK(Hz)|${CPU_CLK}|"
    echo "TPU_CLK(Hz)|${TPU_CLK}|"
    echo "VPU_CLK(Hz)|${VPU_CLK}|"
    echo "CHIP_SN|${CHIP_SN}|"
    echo "DEVICE_SN|${DEVICE_SN}|"
    echo "ETH0_MAC|${ETH0_MAC}|"
    echo "ETH1_MAC|${ETH1_MAC}|"
    echo "CHIP_TEMP(degree Celsius)|${CHIP_TEMP}|"
    echo "BOARD_TEMP(degree Celsius)|${BOARD_TEMP}|"
    echo "FAN_FREQUENCY(Hz)|${FAN_FREQUENCY}|"
    echo "FAN_RPM(rpm)|${FAN_RPM}|"
    echo "DTS_THERMAL_TEMP(degree Celsius)|${DTS_THERMAL_TEMP}|"
    echo "VTPU_POWER(W)|${VTPU_POWER}|"
    echo "VTPU_VOLTAGE(mV)|${VTPU_VOLTAGE}|"
    echo "VDDC_POWER(W)|${VDDC_POWER}|"
    echo "VDDC_VOLTAGE(mV)|${VDDC_VOLTAGE}|"
    echo "V12_POWER(mW)|${V12_POWER}|"
    echo "TPU_USAGE(%)|${TPU_USAGE}|"
    echo "BOARD_TYPE|${BOARD_TYPE}|"
    echo "MCU_VERSION|${MCU_VERSION}|"
    echo "KERNEL_VERSION|${KERNEL_VERSION}|"
    echo "KERNEL_BUILD_TIME|${KERNEL_BUILD_TIME}|"
    echo "SYSTEM_TYPE|${SYSTEM_TYPE}|"
    echo "DOCKER_VERSION|${DOCKER_VERSION}|"
    echo "MMC0_CID|${MMC0_CID}|"
    echo "DISK_INFO|${DISK_INFO}|"
    echo "SDK_VERSION|${SDK_VERSION}|"
    echo "LIBSOPHON_VERSION|${LIBSOPHON_VERSION}|"
    echo "SOPHON_MEDIA_VERSION|${SOPHON_MEDIA_VERSION}|"
else
    echo "BOOT_TIME(s)|${BOOT_TIME}|"
    echo "DATE_TIME|${DATE_TIME}|"
    echo "WORK_MODE|${WORK_MODE}|"
    echo "CARD_NUM|${CARD_NUM}|"
    echo "CHIP_NUM|${CHIP_NUM}|"
    for i in $(seq 0 $((CARD_NUM - 1))); do
        eval "echo \"CARD${i}_TYPE|\$CARD${i}_TYPE|\""
        eval "echo \"CARD${i}_CHIP_ID|\$CARD${i}_CHIP_ID|\""
        eval "echo \"CARD${i}_CHIP_NUM|\$CARD${i}_CHIP_NUM|\""
        eval "echo \"CARD${i}_CHIP_TYPE|\$CARD${i}_CHIP_TYPE|\""
        eval "echo \"CARD${i}_SN|\$CARD${i}_SN|\""
        eval "echo \"CARD${i}_POWER(W)|\$CARD${i}_POWER|\""
        eval "echo \"CARD${i}_TEMP(degree Celsius)|\$CARD${i}_TEMP|\""
        eval "echo \"CARD${i}_CHIP_DDR_SIZE(GiB)|\$CARD${i}_CHIP_DDR_SIZE|\""
        eval "echo \"CARD${i}_CHIP_HEAP_SIZE(MiB)|\$CARD${i}_CHIP_HEAP_SIZE|\""
        eval "echo \"CARD${i}_CHIP_POWER(W)|\$CARD${i}_CHIP_POWER|\""
        eval "echo \"CARD${i}_CHIP_TEMP(degree Celsius)|\$CARD${i}_CHIP_TEMP|\""
        eval "echo \"CARD${i}_TPU_FREQ(MHz)|\$CARD${i}_TPU_FREQ|\""
        eval "echo \"CARD${i}_VPU_FREQ(MHz)|\$CARD${i}_VPU_FREQ|\""
        eval "echo \"CARD${i}_DDR_FREQ(MHz)|\$CARD${i}_DDR_FREQ|\""
        eval "echo \"CARD${i}_TPU_USAGE(%)|\$CARD${i}_TPU_USAGE|\""
        eval "echo \"CARD${i}_VPU_USAGE(%)|\$CARD${i}_VPU_USAGE|\""
                eval "echo \"CARD${i}_JPU_USAGE(%)|\$CARD${i}_JPU_USAGE|\""
    done
    echo "DRIVER_RELEASE_VERSION|${DRIVER_RELEASE_VERSION}|"
    echo "DRIVER_RELEASE_TIME|${DRIVER_RELEASE_TIME}|"
    echo "LIBSOPHON_VERSION|${LIBSOPHON_VERSION}|"
    echo "SOPHON_MEDIA_VERSION|${SOPHON_MEDIA_VERSION}|"
    echo "KERNEL_BUILD_TIME|${KERNEL_BUILD_TIME}|"
    echo "SYSTEM_TYPE|${SYSTEM_TYPE}|"
    echo "DISK_INFO|${DISK_INFO}|"
    echo "CPU_ALL_USAGE(%)|${CPU_ALL_USAGE}|"
    echo "CPUS_USAGE(%)|${CPUS_USAGE}|"
    echo "SYSTEM_MEM_USAGE(%)|${SYSTEM_MEM_USAGE}|"
fi
