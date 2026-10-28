#!/bin/bash

GET_INFO_VERSION="1.7.0"

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

# VPSS 各部件使用率（%），按 vppinfo 中的 id 升序、逗号分隔（形如 `0,0,0`），
# 与同段的 VPU_USAGE 一致。
# 路径随平台而异，两处依次尝试：CV 系（bm1688/cv186ah）为 /proc/soph/vppinfo，
# CV84X2（cv84x6）与 bm1684x/bm1684 为 /proc/vppinfo。
# usage 行每部件输出 instant|long（bm1684x 为 short|long）两个值，只取冒号后第一个，
# 即 usage(instant|long) 中 `:` 之后、`|` 之前的那个数：
#   {"id":0, "usage(instant|long)":   12%|   34%   （CV 系，冒号后有空格）
#   [{"id":0, "usage(short|long)":0%|0%}, "intcnt":0]（bm1684x，冒号后无空格）
function get_vpp_usage() {
    local f usage
    for f in /proc/soph/vppinfo /proc/vppinfo; do
        [ -r "${f}" ] || continue
        usage=$(grep -a 'usage(' "${f}" 2>/dev/null \
            | grep -aoE ':[[:space:]]*[0-9]+%' \
            | tr -d ': %' | tr '\n' ',' | sed 's/,$//')
        if [ -n "${usage}" ]; then
            echo "${usage}"
            return
        fi
    done
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

function get_network_data() {
    old_ifs=${IFS}
    IFS=$'\n'
    for net_info in $(awk '/:/ && $1 != "lo:" {gsub(":", "", $1); print $1, $2, $10}' /proc/net/dev 2>/dev/null); do
        dev_name=$(echo "${net_info}" | awk -F' ' '{print $1}' 2>/dev/null)
        if [ -d /sys/class/net/${dev_name}/device ]; then
            echo "${net_info}"
        fi
    done
    IFS=${old_ifs}
}

function get_block_devices() {
    lsblk -dn -o NAME,TYPE | awk '$2=="disk" && !/^mmcblk.*boot.*/ {print $1}'
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

# ---------------------------------------------------------------------------
# /proc/bmtpu —— CV84X6（CV84X2）TPU 运行时状态
#
# /proc/bmtpu 由 libsophon 的 bmtpu 驱动在 84x6 的 chip_specific_init 里建
# （driver/84x6/84x6_debug.c bmdev_test_proc_init / bmdev_scaler_log_init），
# 只有 84x6、且无论 SOC 还是 PCIE 模式都会建。各文件性质（2026-10-28 于
# 10.42.0.242 真机 + libsophon 0x4.15 源码逐项核实）：
#
#   scaler_info      0666  固件侧（C906 bmcpu）每核一份共享内存统计的只读快照：
#                          固件版本/编译时间、running_flag（当前执行到哪一步）、
#                          using_flag、recvmsg/procmsg 计数、当前 api 与 result。
#                          这是唯一能反映 TPU 固件"活着还是死了"的接口。
#   kernel_info      0444  内核侧 TSH 队列快照：8 个 HWQ 的 free_slots /
#                          pushed_cnt / total done，以及 irq_handle_cnt /
#                          irq_fallback_cnt。pushed-done 即积压深度。
#   kernel_fifo      0444  最近 64 条 api 下发记录（环形缓冲），带 age/api/mode。
#   bmdi_base_info   0664  驱动侧基本信息（libsophon git version / status / timeout）。
#   bmdi_lib_info    0664  已加载的 TPU 算子库及 refcount。
#   bmdi_api_info    0664  **禁止读取**：见下。
#   shmpacket        0666  需先 `echo <addr>` 写入才输出，写操作会改全局调试状态。
#   txpsys           0666  同上，还需按 coreID 触发寄存器 dump。
#   wakeup_control   0666  能 start/stop 一个内核测试线程，绝不能碰。
#
# ⚠ bmdi_api_info 读一次就让内核 Oops 一次（本板实测两次，dmesg 有两条
#   `Unable to handle kernel paging request at virtual address 0000000000002014`）：
#   它的 proc_show 调 bm1688_base_get_core_num() → otp_reg_read(bmdi, 0x2014)，
#   而 84x6 的 bm_reg_bm84x6.otp_base_addr = 0x27100000 并不在 platform BAR 覆盖
#   范围内（dmesg: bm_get_bar_offset invalid address = 0x27100000），
#   bm_reg_init_vaddr 因此把 otp_bar_vaddr 置成 NULL，ioread32 直接解引用空指针。
#   崩溃发生在内核态，任何用户态工具都无法规避，只能不读。
#
# 本脚本只读上面标 0444/0666 的白名单文件，并且只用读、绝不写。

# 单调时钟纳秒；不可用时返回空（速率段退化为 0，不臆造数值）
function _bmtpu_now_ns() {
    local t
    t=$(date +%s%N 2>/dev/null)
    case "${t}" in
        ''|*[!0-9]*) echo "" ;;
        *) echo "${t}" ;;
    esac
}

# [running_flag 十六进制] [using_flag 十六进制] -> 单核状态词
# running_flag 取值语义来自 bmcpu/app/bmcpu/{bmcpu.c,cv84x6_process.c}：
#   0xAA550001            初始化完成，等第一条 tshfifo
#   0xAA550013/14 等      msgfifo_process 里按 api 分支设的阶段标记
#   0xAA550004|api<<8     本次 api 处理结束（低字节固定 0x04），回到轮询
#   0xAA55DEAD            主循环意外退出（正常永不出现）
#   崩溃：信号处理函数把信号号写进 bit16-23，覆盖掉 magic 里的 0x55
# using_flag == 0xa5a5 表示该核正在处理自己负责的 packet，是最权威的忙闲标志
function _bmtpu_decode_core_state() {
    local rf using top sig low
    rf=$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z')
    using=$(printf '%s' "${2:-}" | tr 'A-Z' 'a-z')
    case "${rf}" in
        ''|*[!0-9a-f]*) echo "UNKNOWN"; return ;;
    esac
    while [ ${#rf} -lt 8 ]; do rf="0${rf}"; done
    rf=${rf: -8}
    # 先判 DEAD：它 magic 完好（bit16-23 仍是 0x55），但低 16 位是 0xDEAD
    if [ "${rf}" = "aa55dead" ]; then
        echo "EXITED"
        return
    fi
    top=${rf:0:2}     # bit24-31，magic 高位 0xAA
    sig=${rf:2:2}     # bit16-23，正常是 0x55，崩溃后被信号号覆盖
    low=${rf:6:2}     # bit0-7
    if [ "${top}" != "aa" ]; then
        echo "UNKNOWN"
        return
    fi
    if [ "${sig}" != "55" ]; then
        echo "CRASH$((16#${sig}))"
        return
    fi
    if [ "${using}" = "a5a5" ]; then
        echo "BUSY"
        return
    fi
    case "${low}" in
        04) echo "IDLE" ;;   # 上次 api 已处理完，在轮询 tshfifo
        01) echo "INIT" ;;   # 固件起来了但还没等到第一条消息
        *)  echo "RUN"  ;;   # 正在派发 api（瞬时态）
    esac
}

# [scaler_info 路径] -> 每核一行 "核号|固件版本|编译时间|running_flag|using_flag|recvmsg|procmsg"
# 字段缺失（核没起来 / 固件没填）就留空，不补 0。
function parse_bmtpu_scaler_info() {
    local f="${1:-}"
    [ -r "${f}" ] || return 0
    awk '
        function emit() {
            if (idx == "") return
            gsub(/ /, "_", build)          # 值里不能出现空格，否则破坏 KEY|VALUE| 的行格式
            printf "%s|%s|%s|%s|%s|%s|%s\n", idx, fw, build, rf, uf, recv, proc
        }
        /^Core [0-9]+:$/ {
            emit()
            idx = $2; sub(/:/, "", idx)
            fw = ""; build = ""; rf = ""; uf = ""; recv = ""; proc = ""
            next
        }
        /FIRMWARE_VERSION=/ {
            v = $0; sub(/.*FIRMWARE_VERSION=/, "", v); gsub(/[ \t\r]/, "", v); fw = v; next
        }
        /^[ \t]*BUILD_TIME=/ {
            v = $0; sub(/^[ \t]*BUILD_TIME=/, "", v)
            gsub(/\r/, "", v); gsub(/^[ \t]+|[ \t]+$/, "", v); build = v; next
        }
        /^[ \t]*recvmsg_cnt:/ { recv = $2; next }
        /^[ \t]*procmsg_cnt:/ { proc = $2; next }
        /^[ \t]*running_flag:/ { rf = $2; next }
        /^[ \t]*using_flag:/   { uf = $2; next }
        END { emit() }
    ' "${f}" 2>/dev/null
}

# [kernel_info 路径] -> "积压总数|最小空闲槽位"
# 积压 = Σ(pushed_cnt - total done)，是 TSH 队列里还没被固件消费掉的 api 数；
# free_slots 见底说明下发侧即将进入背压等待。任一 HWQ 缺字段就跳过该 HWQ。
function parse_bmtpu_kernel_info() {
    local f="${1:-}"
    [ -r "${f}" ] || return 0
    awk '
        /^[ \t]*free_slots:/  { fs = $2; if (minfs == "" || fs + 0 < minfs + 0) minfs = fs; next }
        /^[ \t]*pushed_cnt:/  { p = $2; next }
        /^[ \t]*total done:/  {
            if (p != "") { depth += (p + 0) - ($3 + 0); p = "" }
            next
        }
        END {
            if (minfs != "") {
                if (depth < 0) depth = 0
                printf "%d|%d\n", depth, minfs
            }
        }
    ' "${f}" 2>/dev/null
}

# 汇总成 KEY|VALUE| 行。目录可用 GET_INFO_BMTPU_DIR 覆盖（测试用），
# 采样窗口用 GET_INFO_BMTPU_INTERVAL 覆盖。
#
# 速率窗口默认 1.0s：LLM 推理单次 launch 约 90ms 且成批出现（真机 bmrt_test 实测），
# 窗口太短会频繁落在两批之间的空档里读出 0，让人误判成 TPU 停了。1s 能覆盖约 10 次
# launch，读数稳定；相对 get_info 自身的耗时（CPU 采样已占 0.5s）也可接受。
function collect_bmtpu_metrics() {
    local dir interval rows rows2 sum1 sum2 st line idx _f _b rf uf _r _p rate q t1 t2
    dir="${GET_INFO_BMTPU_DIR:-/proc/bmtpu}"
    interval="${GET_INFO_BMTPU_INTERVAL:-1.0}"

    rows=$(parse_bmtpu_scaler_info "${dir}/scaler_info")
    [ -n "${rows}" ] || return 0

    # 固件版本：多核同版本只报一次；出现多个版本说明核间镜像不一致，必须全列出来
    printf '%s\n' "${rows}" | awk -F'|' '
        $2 != "" && !seen[$2]++ { s = (s == "" ? $2 : s "," $2) }
        END { if (s != "") printf "TPU_FW_VERSION|%s|\n", s }'

    # 编译时间：各核本就是分别编译的镜像，正常就不同，故逐核列出才可比对
    printf '%s\n' "${rows}" | awk -F'|' '
        $3 != "" { t = (t == "" ? $3 : t "," $3) }
        END { if (t != "") printf "TPU_FW_BUILD_TIME|%s|\n", t }'

    st=""
    while IFS='|' read -r idx _f _b rf uf _r _p; do
        [ -n "${idx}" ] || continue
        st="${st:+${st},}$(_bmtpu_decode_core_state "${rf}" "${uf}")"
    done <<< "${rows}"
    if [ -n "${st}" ]; then
        printf 'TPU_CORE_STATE|%s|\n' "${st}"
    fi

    # 任务速率：两次采样 recvmsg_cnt 求和做差。计数器是 u32 且固件重启会归零，
    # 差值为负按 0 处理，不输出负数。用单调时钟实测窗口而非假定 sleep 精确到毫秒。
    sum1=$(printf '%s\n' "${rows}" | awk -F'|' '{ s += $6 } END { printf "%d", s + 0 }')
    t1=$(_bmtpu_now_ns)
    sleep "${interval}"
    t2=$(_bmtpu_now_ns)
    rows2=$(parse_bmtpu_scaler_info "${dir}/scaler_info")
    sum2=$(printf '%s\n' "${rows2}" | awk -F'|' '{ s += $6 } END { printf "%d", s + 0 }')
    rate=$(awk -v a="${sum1}" -v b="${sum2}" -v t="${interval}" -v n1="${t1}" -v n2="${t2}" 'BEGIN {
        # 时钟可用就用实测经过时间，否则退回 interval 标称值
        t_real = (n1 != "" && n2 != "" && n2 > n1) ? (n2 - n1) / 1e9 : t + 0
        if (t_real <= 0) { printf "0.00"; exit }
        d = b - a
        if (d < 0) d = 0
        printf "%.2f", d / t_real
    }')
    printf 'TPU_TASK_RATE(tasks/s)|%s|\n' "${rate}"

    q=$(parse_bmtpu_kernel_info "${dir}/kernel_info")
    if [ -n "${q}" ]; then
        printf 'TPU_QUEUE_DEPTH|%s|\n'      "${q%%|*}"
        printf 'TPU_HWQ_FREE_MIN|%s|\n'     "${q##*|}"
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
                echo "INFO: DIR SIZE: [${DIR_SIZE_KB}] > MAX SIZE: [${DIR_SIZE_MAX_KB}]"
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

function get_ddr_info() {
    echo 1 > /sys/bus/iio/devices/iio:device0/in_voltage3_raw
    adc_val_ddr=$(cat /sys/bus/iio/devices/iio:device0/in_voltage3_raw)
    chip_value=$(busybox devmem 0x27102014)
    vol_val_ddr=$(($adc_val_ddr*1500/4096))
    gpio117_val=$(busybox devmem 0x27013050)
    if [ "$chip_value" = "0x00000011" ];then
        if [ "$((gpio117_val & 1))" -eq 0 ]; then
            if [ $vol_val_ddr -ge 0 ] && [ $vol_val_ddr -le 105 ];then
                echo "LP4 2R 1S"
            elif [ $vol_val_ddr -ge 195 ] && [ $vol_val_ddr -le 405 ];then
                echo "LP4 1R 2S"
            elif [ $vol_val_ddr -ge 495 ] && [ $vol_val_ddr -le 705 ];then
                echo "LP4 2R 2S"
            elif [ $vol_val_ddr -ge 795 ] && [ $vol_val_ddr -le 1005 ];then
                echo "LP4 1R 1S"
            elif [ $vol_val_ddr -ge 1095 ] && [ $vol_val_ddr -le 1305 ];then
                echo "LP4X 2R 2S"
            elif [ $vol_val_ddr -ge 1395 ] && [ $vol_val_ddr -le 1500 ];then
                echo "LP4X 1R 2S"
            fi
        else
            if [ $vol_val_ddr -ge 0 ] && [ $vol_val_ddr -le 105 ];then
                echo "DDR4 1R 2S"
            elif [ $vol_val_ddr -ge 195 ] && [ $vol_val_ddr -le 405 ];then
                echo "LP4X 1R 1S"
            elif [ $vol_val_ddr -ge 495 ] && [ $vol_val_ddr -le 705 ];then
                echo "DDR4 1R 1S"
            elif [ $vol_val_ddr -ge 795 ] && [ $vol_val_ddr -le 1005 ];then
                echo "LP4X 2R 1S"
            fi
        fi
    else
        if [ "$((gpio117_val & 1))" -eq 0 ];then
            if [ $vol_val_ddr -ge 0 ] && [ $vol_val_ddr -le 105 ];then
                echo "LP4 2R 2S"
            elif [ $vol_val_ddr -ge 195 ] && [ $vol_val_ddr -le 405 ];then
                echo "LP4 1R 2S"
            elif [ $vol_val_ddr -ge 495 ] && [ $vol_val_ddr -le 705 ];then
                echo "LP4 2R 1S"
            elif [ $vol_val_ddr -ge 795 ] && [ $vol_val_ddr -le 1005 ];then
                echo "LP4 1R 1S"
            elif [ $vol_val_ddr -ge 1095 ] && [ $vol_val_ddr -le 1305 ];then
                echo "LP4X 2R 2S"
            elif [ $vol_val_ddr -ge 1395 ] && [ $vol_val_ddr -le 1500 ];then
                echo "LP4X 1R 2S"
            fi
        else
            if [ $vol_val_ddr -ge 0 ] && [ $vol_val_ddr -le 105 ];then
                echo "DDR4 1R 2S"
            elif [ $vol_val_ddr -ge 195 ] && [ $vol_val_ddr -le 405 ];then
                echo "LP4X 1R 1S"
            elif [ $vol_val_ddr -ge 495 ] && [ $vol_val_ddr -le 705 ];then
                echo "DDR4 1R 1S"
            elif [ $vol_val_ddr -ge 795 ] && [ $vol_val_ddr -le 1005 ];then
                echo "LP4X 2R 1S"
            fi
        fi
    fi
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

# CV84X2（SDK 标识 cv84x6）识别：model name 并不可靠——内核 cpuinfo.c 仅在 32-bit compat 模式下
# 打印此行，且取 CHIP_INFO(0x27102014)&0x7 判定：CV84X2 上可能输出 null/缺行/cv186ah/bm1688。
# 采用硬件/设备树两级识别，两级都不依赖 model name 的准确值：
# 1) 首选 CPU part（MIDR 硬件直读，无条件打印）：Cortex-A55(0xd05) 仅 CV84X2/CV84X6，
#    其余 SDK 芯片（bm1684x/bm1684/bm1688/cv186ah）均为 Cortex-A53(0xd03)，天然分开。
# 2) 兜底 dts 信号：CV84X2 内核 dts 递归含 "cvitek,cv84x6-*" compatible（如 cvitek,cv84x6-clk/
#    cv84x6-emmc/cv84x6-thermal），而真实 bm1688/cv186ah 的 dts 不含（根 compatible 同为
#    "linux,dummy-virt" 不能直接判）。命中即升级为 cv84x6。
CPU_PART=$(awk -F': ' '/CPU part/{print $2; exit}' /proc/cpuinfo)
case "${CPU_PART}" in
    *d05*|*D05*) CPU_MODEL="cv84x6" ;;
esac
if [[ "${CPU_MODEL}" != "cv84x6" ]] && [ -d /proc/device-tree ]; then
    # -L：/proc/device-tree 是指向 /sys/firmware/devicetree/base 的符号链接，
    # 不跟随则恒返回空（真机实测 0 vs 147 条），兜底形同虚设（psocbak PR #146 同款问题）。
    _cv_match=$(find -L /proc/device-tree -name compatible -type f \
        -exec grep -laE "cvitek,cv84x6-" {} + 2>/dev/null)
    if [ -n "${_cv_match}" ]; then
        CPU_MODEL="cv84x6"
    fi
    unset _cv_match
fi

# WORK MODE
SOC_MODE_CPU_MODEL=("bm1684x" "bm1684" "bm1688" "cv186ah" "cv84x6")
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

# SOC_FAMILY：归一化芯片家族，减少逐芯片双分支判断。
# bm1688/cv186ah/cv84x6 同属 CV 系（C906），共享 dts 名/ION heap/vpuinfo/TPU_USAGE/SDK 版本路径。
SOC_FAMILY=""
case "${CPU_MODEL}" in
    bm1684x|bm1684) SOC_FAMILY="bm1684" ;;
    bm1688|cv186ah|cv84x6) SOC_FAMILY="cv" ;;
    *) SOC_FAMILY="${CPU_MODEL}" ;;
esac

# SHUTDOWN_REASON
# CV84X2 不可抗说明（真机 + SDK 源码双证据，2026-08-26）：
# /root/.boot/*.txt 机制是 bm1684x/bm1684 的 ramdisk 开机脚本功能（MCU 记录关机原因、
# 开机转储成 txt）；CV 系（含 cv84x6）ramdisk/rootfs 无任何 .boot 相关脚本，真机
# /root/.boot 不存在；内核无 reset-reason 驱动，EVB MCU（I2C0x17）cmd 空间（0x00-0x5F
# 只读扫描）无关机原因寄存器。CV 系保持留空。
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
        SHUTDOWN_REASON_HEX_MAP["00000085"]="OVER_HEAT_MCU"
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
DDR_TYPE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        DTS_MEM_FILE="/proc/device-tree/memory*/reg"
        # get_ddr_info 依赖 bm1684 家族的 iio:device0 ADC 与 devmem 0x27102014/0x27013050：
        # CV84X2 dts 无 iio/adc 节点（真机 /sys/bus/iio/devices 为空），且 0x27013050 未定义。
        # ADC 读空会让 vol_val_ddr 的算术展开失败、各电压区间判断全部落空（此前输出为空属侥幸行为）；
        # 在装有 busybox devmem 的系统上 gpio117_val 还可能读到任意值，落入错误分支输出伪 DDR 类型。
        # 显式跳过。CV84X2 的 DDR_TYPE 无运行时来源（不可抗，2026-08-26 真机+源码核实）：
        # - DDR 类型为 FSBL 编译期选定（EVB defconfig：CONFIG_DDR_CFG_lp5x_2r_8533，
        #   build/boards/84x6/edge_84x6_wevb_emmc/），fip.bin 固化后不再暴露；
        # - fsbl ddr_pkg_info.c 的 ddr_info_save()（写 PM_SRAM 供 u-boot 读）整函数被注释；
        # - eMMC boot1 OEM 布局（u-boot cmd/84x6-oem.c oem_fields）无 DDR_TYPE 字段，
        #   read_oem.sh 的 DDR_TYPE 段亦被注释；
        # - ddr_auto（ADC 分压识别）对 cv84x6 无实现。DDR_TYPE 保持留空。
        if [[ "${CPU_MODEL}" != "cv84x6" ]]; then
            DDR_TYPE=$(get_ddr_info 2>/dev/null)
        fi
    else
        DTS_MEM_FILE="/proc/device-tree/memory/reg"
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
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # CV84X2 ion heap 由 dts 保留内存节点决定（内核 cvitek_ion.c cvi_ion_heap_list 按
        # "cvitek,carveout_npu/vpu/vpp" compatible 建 heap）：真机 dts reserved-memory 仅有
        # ion_npu_mem / ion_vpp_mem，无 carveout_vpu → 无 vpu heap，VPU 显存走 system/cma。
        # 故 VPU_MEM/VPU_MEM_USAGE 恒 0 属硬件内存布局使然（不可抗），非读取失败；
        # TPU_MEM/VPP_MEM 在 sudo 下可读（debugfs root-only，非 sudo 恒 0）。
        TPU_MEM=$(cat /sys/kernel/debug/ion/cvi_npu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPP_MEM=$(cat /sys/kernel/debug/ion/cvi_vpp_heap_dump/total_mem 2>/dev/null | tr -d '\0')
    else
        TPU_MEM=$(cat /sys/kernel/debug/ion/bm_npu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPU_MEM=$(cat /sys/kernel/debug/ion/bm_vpu_heap_dump/total_mem 2>/dev/null | tr -d '\0')
        VPP_MEM=$(cat /sys/kernel/debug/ion/bm_vpp_heap_dump/total_mem 2>/dev/null | tr -d '\0')
    fi
    SYSTEM_MEM=$(( SYSTEM_MEM / 1024 ))
    TPU_MEM=$(( TPU_MEM / 1024 / 1024 ))
    VPU_MEM=$(( VPU_MEM / 1024 / 1024 ))
    VPP_MEM=$(( VPP_MEM / 1024 / 1024 ))
fi

# SYSTEM_MEM_USAGE
SYSTEM_MEM_USAGE=$(free -k | head -n2 | tail -n1 | awk '{free=$7; total=$2; printf "%.2f\n", ((total-free)/total)*100}' 2>/dev/null)

# CPU_ALL_USAGE
unset CPU_ALL_USAGE
unset CPUS_USAGE
CPU_ALL_USAGE=""
CPUS_USAGE=""
NET_SPEED_UPLOAD=""
NET_SPEED_DOWNLOAD=""
DISK_SPEED_READ=""
DISK_SPEED_WRITE=""
function get_cpu_all() {
    interval=0.5
    cpu_num=$(cat /proc/stat 2>/dev/null | grep "^cpu" 2>/dev/null | wc -l)
    cpu_count=$((cpu_num - 1))
    net_date1=$(get_network_data | sort -k1 -n)
    blk_data1=$(cat /proc/diskstats)
    proc_stat1=$(cat /proc/stat)
    sleep ${interval}
    proc_stat2=$(cat /proc/stat)
    net_date2=$(get_network_data | sort -k1 -n)
    blk_data2=$(cat /proc/diskstats)
    net_dev_count=$(echo "${net_date1}" | wc -l)
    for ((i=1; i<=net_dev_count; i++)); do
        dev=$(echo "$net_date1" | awk "NR==$i" | awk '{print $1}' 2>/dev/null)
        recv1=$(echo "$net_date1" | awk "NR==$i" | awk '{print $2}' 2>/dev/null)
        recv2=$(echo "$net_date2" | awk "NR==$i" | awk '{print $2}' 2>/dev/null)
        recvc=$(echo "scale=2; (${recv2} - ${recv1}) / 1024 / ${interval}" | bc 2>/dev/null)
        printf "%s,%.2f " ${dev} ${recvc}
    done
    printf "|"
    for ((i=1; i<=net_dev_count; i++)); do
        dev=$(echo "$net_date1" | awk "NR==$i" | awk '{print $1}' 2>/dev/null)
        send1=$(echo "$net_date1" | awk "NR==$i" | awk '{print $3}' 2>/dev/null)
        send2=$(echo "$net_date2" | awk "NR==$i" | awk '{print $3}' 2>/dev/null)
        sendc=$(echo "scale=2; (${send2} - ${send1}) / 1024 / ${interval}" | bc 2>/dev/null)
        printf "%s,%.2f " ${dev} ${sendc}
    done
    printf "|"
    for blk_dev in $(get_block_devices); do
        blk_sector_size=$(blockdev --getss /dev/${blk_dev})
        blk_read1=$(echo "${blk_data1}" | grep -a "${blk_dev} " | awk -F' ' '{print $6}' 2>/dev/null)
        blk_read2=$(echo "${blk_data2}" | grep -a "${blk_dev} " | awk -F' ' '{print $6}' 2>/dev/null)
        read_speed=$(echo "scale=2; ($blk_read2 - $blk_read1) * ${blk_sector_size} / 1024 / ${interval}" | bc 2>/dev/null)
        printf "%s,%.2f " ${blk_dev} ${read_speed}
    done
    printf "|"
    for blk_dev in $(get_block_devices); do
        blk_sector_size=$(blockdev --getss /dev/${blk_dev})
        blk_write1=$(echo "${blk_data1}" | grep -a "${blk_dev} " | awk -F' ' '{print $10}' 2>/dev/null)
        blk_write2=$(echo "${blk_data2}" | grep -a "${blk_dev} " | awk -F' ' '{print $10}' 2>/dev/null)
        write_speed=$(echo "scale=2; ($blk_write2 - $blk_write1) * ${blk_sector_size} / 1024 / ${interval}" | bc 2>/dev/null)
        printf "%s,%.2f " ${blk_dev} ${write_speed}
    done
    printf "|"
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
        printf "%.2f,%.2f,%.2f,%.2f,%.2f|", usage, user_u, ker_u, io_u, irq_u;
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
    echo "|"
}
{ IFS='|' read -r NET_SPEED_UPLOAD NET_SPEED_DOWNLOAD DISK_SPEED_READ DISK_SPEED_WRITE CPU_ALL_USAGE CPUS_USAGE; } <<< "$(get_cpu_all)"

# DTS_NAME
DTS_NAME=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # 首选 eMMC boot1 OEM 区 0xA0（u-boot cmd/84x6-oem.c oem_fields 的 DTS_TYPE 偏移）。
        # EVB 出厂未烧写 OEM（boot1 前 4KB 全零）→ 恒空，此时回退读 u-boot env：
        # u-boot board/cvitek/cv84x6/board.c setup_sophgo_dts() 在 OEM 为空时会用编译期
        # 默认值（config-<chip>_<board>）填充 env 的 DTS_TYPE（本机即 bootcmd 引用的
        # config-cv84x6_wevb_emmc）；量产烧写 OEM 后该 env 同样承载烧写值。
        # /boot/u-boot.env 为 vfat 分区上的 world-readable 文件（4 字节头 + \0 分隔的
        # key=value），无需 sudo 即可解析。
        DTS_NAME=$(od_read_char 160 32 "/dev/mmcblk0boot1")
        if [[ -z "${DTS_NAME}" ]] && [[ -r /boot/u-boot.env ]]; then
            DTS_NAME=$(tr '\0' '\n' < /boot/u-boot.env 2>/dev/null \
                | grep -m1 '^DTS_TYPE=' | cut -d'=' -f2-)
        fi
    else
        DTS_NAME=$(cat /proc/device-tree/info/file-name 2>/dev/null | tr -d '\0')
    fi
fi

# DEVICE_MODEL
DEVICE_MODEL=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # boot1 OEM 区 product(0xD0) + module type(0x70)。CV84X2 EVB 不可抗说明
        # （2026-08-26 真机核实）：boot1 前 4KB 全零（OEM 未烧写），开机转储的
        # /factory/OEMconfig.ini（read_oem.sh 从 boot1 生成）PRODUCT/MODULE_TYPE
        # 同为空 → 输出留空。量产烧写 OEM 后此处自然取到值。
        DEVICE_MODEL_PRODUCT=$(od_read_char 208 16 "/dev/mmcblk0boot1")
        DEVICE_MODEL_MODULE_TYPE=$(od_read_char 112 16 "/dev/mmcblk0boot1")
        DEVICE_MODEL="${DEVICE_MODEL_PRODUCT} ${DEVICE_MODEL_MODULE_TYPE}"
        # 两者皆空时避免输出单个空格
        DEVICE_MODEL=$(echo "${DEVICE_MODEL}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    else
        DEVICE_MODEL=$(grep "model" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}')
    fi
fi

# CLKs
CPU_CLK=""
TPU_CLK=""
VPU_CLK=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "cv84x6" ]]; then
        # CV84X6 时钟（drivers/clk/cvitek/clk-cv84x6.c）：
        #   CPU 为 Cortex-A55 → clk_ap_ca55；TPU → clk_tpu_ip；
        #   VPU 无独立 PLL，编解码走 clk_ve_axi（AXI 总线时钟，语义与 bm1688 的 clk_cam0pll PLL 不同，不 ÷2）
        CPU_CLK=$(cat /sys/kernel/debug/clk/clk_ap_ca55/clk_rate 2>/dev/null| tr -d '\0')
        TPU_CLK=$(cat /sys/kernel/debug/clk/clk_tpu_ip/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(cat /sys/kernel/debug/clk/clk_ve_axi/clk_rate 2>/dev/null| tr -d '\0')
    elif [[ "${SOC_FAMILY}" == "cv" ]]; then
        CPU_CLK=$(cat /sys/kernel/debug/clk/clk_a53pll/clk_rate 2>/dev/null| tr -d '\0')
        TPU_CLK=$(cat /sys/kernel/debug/clk/clk_tpll/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(cat /sys/kernel/debug/clk/clk_cam0pll/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(( VPU_CLK / 2 ))
    else
        CPU_CLK=$(cat /sys/kernel/debug/clk/clk_div_a53_1/clk_rate 2>/dev/null| tr -d '\0')
        TPU_CLK=$(cat /sys/kernel/debug/clk/tpll_clock/clk_rate 2>/dev/null| tr -d '\0')
        VPU_CLK=$(cat /sys/kernel/debug/clk/clk_gate_axi10/clk_rate 2>/dev/null| tr -d '\0')
    fi
fi

# SN
CHIP_SN=""
DEVICE_SN=""
# 从 /factory/OEMconfig.ini 读指定字段（值去引号/空白/CR；字段缺失或文件不存在返回空）
function get_oem_ini_value() {
    grep -m1 "^${1} *=" "${2}" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # BM1688 方案优先（SE 系列官方查询方式，SE9 用户手册 FAQ「查看 SN：cat
        # /factory/OEMconfig.ini」）：read_oem.sh 开机将 boot1 OEM 区转储为
        # /factory/OEMconfig.ini（SN=SN0 chip sn、DEVICE_SN=SN1 整机 sn）。该文件
        # world-readable，非 sudo 也可取到值（boot1 直读需 root）。
        # ini 缺失或字段为空时回退直读 boot1 0x00/0x20（bm1688/cv186ah 原路径，
        # SE9 OEM 布局 SN0=0x00/SN1=0x20 与 CV84X2 一致）。
        # CV84X2 EVB 真机（2026-08-26）：boot1 OEM 区全零（出厂未烧写），ini 的
        # SN/DEVICE_SN 同为空 → 留空；量产烧写 OEM 后两路均自然取到值。
        CHIP_SN=$(get_oem_ini_value "SN" "/factory/OEMconfig.ini")
        DEVICE_SN=$(get_oem_ini_value "DEVICE_SN" "/factory/OEMconfig.ini")
        if [[ -z "${CHIP_SN}" ]]; then
            CHIP_SN=$(od_read_char 0 32 "/dev/mmcblk0boot1")
        fi
        if [[ -z "${DEVICE_SN}" ]]; then
            DEVICE_SN=$(od_read_char 32 32 "/dev/mmcblk0boot1")
        fi
    else
        # CHIP_SN=$(grep "product sn" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}')
        CHIP_SN=$(od_read_char 0 32 "/sys/bus/nvmem/devices/1-006a0/nvmem")
        DEVICE_SN=$(od_read_char 512 32 "/sys/bus/nvmem/devices/1-006a0/nvmem")
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
        # CV84X2 不可抗说明（2026-08-26 真机核实）：无独立板温传感器。
        # - 真机 /sys/class/thermal 仅 thermal_zone0/1/2，dts 对应 soc_thermal_0/1/2
        #   （cv84x6_wevb_emmc.dts），全部是 SoC 片内传感器，非板温；借读 zone1 会输出伪值。
        # - /sys/class/hwmon 为空；EVB MCU（i2c10@0x17）按 bm1684 协议 cmd 0x04/0x05
        #   （chip/board temp，bm_attr.c bm_read_mcu_temp）读回 0x01/0x00（1°C/0°C），
        #   8 核满载 45s 压测中冻结不变，为无意义寄存器而非温度。
        # 故 CV84X2 板温保持 0。
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
        # CV84X2 不可抗说明（2026-08-26 真机核实）：EVB 无风扇转速采集链路。
        # - 内核无 bm-tach 驱动（/sys/class/bm-tach 不存在），/sys/class/pwm、
        #   /sys/class/hwmon 均为空；
        # - dts 无任何 fan 节点；u-boot board.c 中 FAN0/FAN1 引脚复用为 GPIO79/80，
        #   风扇 PWM 走 PWM11，均无 tach 输入；
        # - EVB MCU（i2c10@0x17）cmd 0x00-0x7F 只读全扫描（0x24/0x25 为 bm1684 协议
        #   的 12V 功率寄存器）无风扇相关寄存器（除 0x00/0x01/0x02 外仅 0x04/0x05/
        #   0x18/0x30/0x31/0x7C-0x7F 有非 0xFF 值，无连续变化的转速值）。
        # 故 CV84X2 FAN_FREQUENCY/FAN_RPM 保持 0。
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
    elif [[ "${CPU_MODEL}" == "cv84x6" ]]; then
        # CV84X2/CV84X6 dts 的 thermal-zones 为 soc_thermal_0..N（真机 EVB 共 3 个 zone，
        # 各含 1 个 soc_thermal_crtical_N trip，125000m°C=125°C）。zone 数量与 trip 名
        # 随 dts 配置变化，遍历所有 zone 的 trip 点读取，输出顺序与 zone 号一致。
        for _tz in /proc/device-tree/thermal-zones/soc_thermal_*; do
            [ -d "${_tz}" ] || continue
            for _trip in "${_tz}"/trips/*/; do
                [ -d "${_trip}" ] || continue
                temp=$(od_read_dec_big 0 4 "${_trip}temperature")
                if [ "${temp}" -gt 0 ] 2>/dev/null; then
                    temp=$(( temp / 1000 ))
                    if [ -n "${DTS_THERMAL_TEMP}" ]; then
                        DTS_THERMAL_TEMP="${DTS_THERMAL_TEMP} ${temp}"
                    else
                        DTS_THERMAL_TEMP="${temp}"
                    fi
                fi
            done
        done
        unset _tz _trip temp
    fi
fi

# VTPU_POWER
VTPU_POWER=""
VTPU_VOLTAGE=""
VDDC_POWER=""
VDDC_VOLTAGE=""
# CV84X2 不可抗说明（2026-08-26 真机核实）：EVB 无电源监控通道，VTPU/VDDC 功率电压
# 及 V12_POWER 均保持留空。
# - 无 pmbus 设备：真机 11 条 i2c 总线扫描，bus0/1 的 0x50/0x55（bm1684 的 PMBUS
#   电源监控地址）均无响应；dts 全部 i2c 节点无 pmbus/power-monitor 子节点。
# - EVB MCU（i2c10@0x17，board_type=0xb7）cmd 0x24-0x27（bm1684 协议 12V 功率/
#   电压寄存器，bm_attr.c bm_read_mcu_current/bm_read_mcu_voltage）全部读回 0xFF，
#   该固件不实现电源监控；cmd 0x00-0x7F 只读全扫描无其他连续变化寄存器。
# - /sys/class/hwmon 为空，无 in/power 类传感器节点。
# 整机形态（SE13 等）带电源监控 MCU 后可复用 pmbus/MCU 路径，届时再适配。
#
# CV84X6 补充（2026-10-28 双板实测）：CV84X6 不带 bm1684 那种 pmbus 电源监控器件，
# 但主芯片电压由 cv84x2-dvfs-pmbus 驱动（platform driver，直连 PMBUS0 控制器
# 5036000.i2c，绕过 i2c 子系统）通过 PMBus 控制 JWH63782 PMIC。驱动 probe 成功后
# 会导出 cpu_volt_mv，直接读该属性即可拿到实时电压。
# 关键约束（源码 + 真机双证）：
# - 只有 page0(CPU) 这一路活轨；page1(TPU) 实测 VOUT_COMMAND/READ_VOUT 恒 0 且
#   STATUS_WORD=0x0841 挂故障位，从未使能。驱动 volt_read_mv() 也硬编码 cpu_rail_page，
#   tpu_rail_page 仅用于 info 打印。故 TPU 与 CPU 物理同轨，不存在独立的 TPU 电压，
#   VTPU_VOLTAGE 保留空、不拿 CPU 值冒充。
# - 该驱动在本板 dtb 缺 pmic-addr 属性时会 probe 失败（PMIC 实际在 0x00 而驱动回退
#   硬编码 0x20），此时属性不存在。已额外提供 i2c 直读回退，见下方 CV84X6 分支。
# - i2c 直读需自行换算：V(mV) = (VID+49) * step * GRS，本板 step=10mV、GRS=1.0；
#   VOUT_COMMAND(0x21) 为设定值，READ_VOUT(0x8B) 为实测值（恒低 1~2 LSB 属正常）。
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

# VDDC_VOLTAGE —— CV84X6 主芯片（CPU/TPU 同轨）实时电压
# 两条路径按优先级尝试，前者为正常路径，后者兜住 dtb/驱动不匹配的设备：
#   1) sysfs：驱动 probe 成功时 /sys/devices/platform/cv84x2-dvfs/cpu_volt_mv 可读，
#      内容形如 "980 mV (pmic=JWH63782)"，驱动内部已完成 PMBus 换算，最准最省事。
#   2) i2c 直读：驱动未就绪时回退。按控制器 5036000 反查总线号（dts 无 i2c aliases，
#      总线号按 probe 顺序分配、不固定），PMIC 地址按 MFR_ID(0x99)=0x5702 在 0x00/0x20
#      两个候选上探测（实测 SE13 板在 0x00，wevb 板在 0x20）。
# 读不到就保持空，绝不填 0 或估算值 —— 空表示"该板不可测"，0 会被下游误当成真实读数。
if [[ "${WORK_MODE}" == "SOC" ]] && [[ "${CPU_MODEL}" == "cv84x6" ]]; then
    _cv_dvfs_dir="/sys/devices/platform/cv84x2-dvfs"
    if [ -r "${_cv_dvfs_dir}/cpu_volt_mv" ]; then
        _cv_mv=$(awk '{print $1}' "${_cv_dvfs_dir}/cpu_volt_mv" 2>/dev/null)
        case "${_cv_mv}" in
            ''|*[!0-9]*) _cv_mv="" ;;
        esac
        VDDC_VOLTAGE="${_cv_mv}"
    fi
    if [[ -z "${VDDC_VOLTAGE}" ]] && [[ "$(cmd_validate i2cget)" == "1" ]]; then
        # 反查 PMBUS0（5036000.i2c）对应的 /dev/i2c-N
        _cv_bus=""
        for _cv_dev in /sys/class/i2c-dev/i2c-*; do
            case "$(readlink -f "${_cv_dev}/device" 2>/dev/null)" in
                *5036000*) _cv_bus="${_cv_dev##*-}"; break ;;
            esac
        done
        if [[ -n "${_cv_bus}" ]]; then
            for _cv_addr in 0x00 0x20; do
                # -a：i2cget/i2cset 默认拒绝 0x08 以下地址，0x00 必须加 -a 才可访问
                _cv_id=$(i2cget -a -f -y "${_cv_bus}" "${_cv_addr}" 0x99 w 2>/dev/null)
                if [[ "${_cv_id}" == "0x5702" ]]; then
                    # 确保读的是 page0（CPU rail），否则 READ_VOUT 取到的是别的 page
                    i2cset -a -f -y "${_cv_bus}" "${_cv_addr}" 0x00 0x00 b 2>/dev/null
                    _cv_vid=$(i2cget -a -f -y "${_cv_bus}" "${_cv_addr}" 0x8b w 2>/dev/null)
                    case "${_cv_vid}" in
                        0x*)
                            # step=10mV、GRS=1.0（本芯片实测确定，见 BSP 笔记 §87.22）
                            VDDC_VOLTAGE=$(( (${_cv_vid} + 49) * 10 ))
                            ;;
                    esac
                    break
                fi
            done
        fi
        unset _cv_bus _cv_addr _cv_id _cv_vid
    fi
    unset _cv_dvfs_dir _cv_mv _cv_dev
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

# TPU_RUNTIME —— 来自 /proc/bmtpu（仅 CV84X6）
# 上面 TPU_USAGE 是内核采样出来的利用率百分比，反映"有多忙"；这一段补的是
# "TPU 到底在不在正常工作"：固件版本、每核跑到了哪一步、下发队列有没有积压。
# 两者互补：利用率 0% 既可能是真空闲，也可能是固件崩了/卡死，只有这段能区分。
# 输出条目不固定（4 核机型 4 条、异常时才出现的 key 不输出到空行），故单独成段。
TPU_BMTPU_LINES=""
if [[ "${WORK_MODE}" == "SOC" ]] && [[ "${CPU_MODEL}" == "cv84x6" ]]; then
    # /proc/bmtpu 及其下 0444/0666 文件非 root 也可读（实测 linaro 用户可读），
    # 但驱动没起来时整个目录不存在 —— collect 内部判空后返回空，不报错。
    if [ -d /proc/bmtpu ]; then
        TPU_BMTPU_LINES=$(collect_bmtpu_metrics)
    fi
fi

# TPU_USAGE
TPU_USAGE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "cv84x6" ]]; then
        # CV84X6 的 npu_usage 被 driver 的 timer_on 门控（libsophon bm_attr.c npu_usage_show：
        # timer_on==0 时输出 "Please, set [Usage enable] to 1"，默认 0）→ 直接读恒为空。
        # 监测线程 bm_monitor 一直在后台采样（约 10ms/次），使能后立即可读：
        #   echo 1 > /sys/class/bm-tpu/bm-tpu0/device/npu_usage_enable
        write_to_file /sys/class/bm-tpu/bm-tpu0/device/npu_usage_enable 1
    fi
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        TPU_USAGE=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage 2>/dev/null| awk -F':' '{print $2}' | awk '{print $1}' | tr '\n' ' ' | sed 's/ *$//')
    else
        TPU_USAGE=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage 2>/dev/null| awk -F':' '{print $2}' | awk '{print $1}')
    fi
fi

# VPU_USAGE
VPU_USAGE=""
VPP_USAGE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "cv84x6" ]] || [[ "${SOC_FAMILY}" == "cv" ]]; then
        # CV 系（bm1688/cv186ah/cv84x6）VPU 走 /proc/soph/vpuinfo（vc_drv_proc.h，PLATFORM_SOC）。
        VPU_USAGE=$(cat /proc/soph/vpuinfo 2>/dev/null| tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/ $//' | sed 's/,$//')
    else
        VPU_USAGE=$(cat /proc/vpuinfo 2>/dev/null| tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/ $//' | sed 's/,$//')
    fi
    # VPP 路径与 VPU 不同（osdrv vpss_proc.c）：CV 系在 /proc/soph/vppinfo，
    # CV84X2/bm1684x 在 /proc/vppinfo，见 get_vpp_usage 注释。
    VPP_USAGE=$(get_vpp_usage)
fi

# DEVICE_MEM_USAGE
TPU_MEM_USAGE="0"
VPU_MEM_USAGE="0"
VPP_MEM_USAGE="0"
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # CV84X2：使用率=ion heap 的 alloc_mem/total_mem（debugfs root-only，sudo 下可读，
        # 非 sudo 恒 0）。真机 EVB 无负载时 alloc_mem=0 → 0% 为真实值而非读取失败；
        # VPU_MEM_USAGE 恒 0 因 dts 无 carveout_vpu 保留内存节点、无 vpu heap（见
        # MEM_INFO 段注释），属硬件内存布局使然。
        TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_npu_heap_dump")
        VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_vpp_heap_dump")
    else
        TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_npu_heap_dump")
        VPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpu_heap_dump")
        VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpp_heap_dump")
    fi
fi

# BOARD_TYPE
BOARD_TYPE=""
MCU_VERSION=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${CPU_MODEL}" == "cv84x6" ]]; then
        # CV84X6 MCU 在 I2C 控制器1 地址 0x17，版本走 I2C 命令字节协议（libsophon 驱动
        # 84x6_card.c bm84x6_get_board_version_from_mcu：bm_i2c_read_byte(i2c_index=1, cmd)，
        # cmd 0x00/0x01/0x02 分别读 board_type / mcu_sw_version / hw_version）。
        # 驱动为 DesignWare I2C「写命令字节→读字节」，等价 i2cget 的 read-byte-data：
        #   i2cget -f -y <bus> 0x17 <cmd>
        # 总线号无法静态确定（dts 无 i2c aliases，Linux 按 probe 顺序编号）：扫描 /dev/i2c-*，
        # 直接对 0x17 发 3 个命令字节读取（无设备的总线 NACK 返回空，自动跳过）；三个均为
        # 合法字节值且非 0xFF（空总线读回值）才输出，否则留空（避免读到垃圾值）。
        # 真机协议与值域仍需复核。
        if [[ "$(cmd_validate i2cget)" == "1" ]]; then
            for _bus in /dev/i2c-*; do
                [ -e "$_bus" ] || continue
                _b=${_bus#/dev/i2c-}
                _mcubt=$(i2cget -f -y "$_b" 0x17 0x00 2>/dev/null)
                _mcusw=$(i2cget -f -y "$_b" 0x17 0x01 2>/dev/null)
                _mcuhw=$(i2cget -f -y "$_b" 0x17 0x02 2>/dev/null)
                if [[ "$_mcubt" =~ ^0x[0-9a-fA-F]{2}$ ]] && [[ "$_mcusw" =~ ^0x[0-9a-fA-F]{2}$ ]] \
                    && [[ "$_mcuhw" =~ ^0x[0-9a-fA-F]{2}$ ]]; then
                    _bt=$(( _mcubt ))
                    _sw=$(( _mcusw ))
                    if [ "$_bt" -ne 255 ] && [ "$_sw" -ne 255 ]; then
                        if [ "$_bt" -eq 0 ]; then
                            BOARD_TYPE="EVB"   # BOARD_TYPE_EVB=0x0（libsophon bm_pcie.h）
                        else
                            BOARD_TYPE=$_mcubt
                        fi
                        MCU_VERSION=$_sw
                        break
                    fi
                fi
            done
            unset _bus _b _mcubt _mcusw _mcuhw _bt _sw
        fi
    elif [[ "${SOC_FAMILY}" == "cv" ]]; then
        mcu_reg=$(busybox devmem 0x05026024 2>/dev/null)
        mcu_1=$(( (mcu_reg & 0xFF0000) >> 16 ))
        mcu_2=$(( (mcu_reg & 0xFF00) >> 8 ))
        mcu_3=$(( (mcu_reg & 0xFF) >> 0 ))
        MCU_VERSION="$mcu_1"."$mcu_2"."$mcu_3"
    else
        BOARD_TYPE=$(grep "board type" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}' 2>/dev/null)
        MCU_VERSION=$(grep "mcu version" /sys/class/i2c-dev/i2c-1/device/1-0017/information 2>/dev/null | awk -F'"' '{print $4}' 2>/dev/null)
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
MMC0_CID=""
MMC0_LIFE_TIME=""
MMC0_PRE_EOL_LIFE=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    MMC0_CID=$(cat /sys/class/mmc_host/mmc0/mmc0\:0001/cid 2>/dev/null | sed 's| \\n||g')
    MMC0_LIFE_TIME=$(cat /sys/class/mmc_host/mmc0/mmc0\:0001/life_time)
    MMC0_PRE_EOL_LIFE=$(cat /sys/class/mmc_host/mmc0/mmc0\:0001/pre_eol_info)
fi

# DISK_INFO
DISK_INFO=$(df -T 2>/dev/null | grep ^/dev | awk '{printf "%s%s:%s", (NR==1 ? "" : " "), $7, $6} END {print ""}')

# SDK_VERSION
SDK_VERSION=""
LIBSOPHON_VERSION=""
SOPHON_MEDIA_VERSION=""
if [[ "${WORK_MODE}" == "SOC" ]]; then
    if [[ "${SOC_FAMILY}" == "cv" ]]; then
        # 新格式 bm_version 首行 "SophonSDK(<chip>) 2.1" → 取 ')' 之后的版本；
        # 旧格式 "Gemini_SDK: x.y" 行次之。两者都缺失则 SDK_VERSION 留空。
        # CV84X6 的 bm_version 首行即 "SophonSDK(cv84x6) 2.x"，该正则已覆盖。
        SDK_VERSION=$(/usr/sbin/bm_version 2>/dev/null | grep -E "^SophonSDK\(" | sed -E 's|^SophonSDK\([^)]*\)[[:space:]]*||g')
        if [[ -z "${SDK_VERSION}" ]]; then
            SDK_VERSION=$(/usr/sbin/bm_version 2>/dev/null | grep "Gemini_SDK" | sed 's|Gemini_SDK: ||g')
        fi
        LIBSOPHON_VERSION=$(readlink /opt/sophon/libsophon-current 2>/dev/null | awk -F'-' '{print $2}')
        SOPHON_MEDIA_VERSION=$(readlink /opt/sophon/sophon-ffmpeg-latest 2>/dev/null | awk -F'_' '{print $2}')
    elif [[ "${KERNEL_VERSION}" == "5.4."* ]]; then
        SDK_VERSION=$(/usr/sbin/bm_version 2>/dev/null | grep "SophonSDK version" | sed 's|SophonSDK version: ||g')
        LIBSOPHON_VERSION=$(readlink /opt/sophon/libsophon-current 2>/dev/null | awk -F'-' '{print $2}')
        SOPHON_MEDIA_VERSION=$(readlink /opt/sophon/sophon-ffmpeg-latest 2>/dev/null | awk -F'_' '{print $2}')
    elif [[ "${KERNEL_VERSION}" == "4.9."* ]]; then
        SDK_VERSION=$(grep "VERSION" /system/data/buildinfo.txt 2>/dev/null | awk '{print $2}')
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
    # 用关联数组取代动态变量名 + eval，消除 /proc 文件内容被当作代码执行的注入面
    declare -A CARD_DATA
    for i in $(seq 0 $((CARD_NUM - 1))); do
        CARD_DATA["${i}_TYPE"]="$(cat /proc/bmsophon/card${i}/board_type)"
        CARD_DATA["${i}_CHIP_ID"]="$(cat /proc/bmsophon/card${i}/bmsophon*/tpuid | sort -n | tr '\n' ' ' | sed 's/ *$//')"
        CARD_DATA["${i}_CHIP_NUM"]="$(cat /proc/bmsophon/card${i}/chip_num_on_card)"
        CARD_DATA["${i}_CHIP_TYPE"]="$(cat /proc/bmsophon/card${i}/chipid)"
        CARD_DATA["${i}_SN"]="$(cat /proc/bmsophon/card${i}/sn)"
        CARD_DATA["${i}_POWER"]="$(cat /proc/bmsophon/card${i}/board_power | awk '{print $1}')"
        CARD_DATA["${i}_TEMP"]="$(cat /proc/bmsophon/card${i}/board_temp | awk '{print $1}')"
        CARD_DATA["${i}_BOARD_VERSION"]="$(cat /proc/bmsophon/card${i}/board_version)"
        CARD_CHIP_ID="${CARD_DATA["${i}_CHIP_ID"]}"
        CARD_DATA["${i}_CHIP_DDR_SIZE"]=""
        CARD_DATA["${i}_CHIP_POWER"]=""
        CARD_DATA["${i}_CHIP_TEMP"]=""
        CARD_DATA["${i}_TPU_FREQ"]=""
        CARD_DATA["${i}_TPU_USAGE"]=""
        CARD_DATA["${i}_VPU_USAGE"]=""
        for k in ${CARD_CHIP_ID}; do
            CARD_DATA["${i}_CHIP_DDR_SIZE"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/ddr_capacity | tr -d 'g' | awk '{print $NF}') "
            CARD_DATA["${i}_CHIP_HEAP_SIZE"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/heap | awk '{print $4}' | tr -d ',' | while read -r hex; do decimal=$(printf "%d" $hex); echo "scale=0; $decimal / 1024 / 1024" | bc; done | tr '\n' ',' | sed 's/,$//') "
            CARD_DATA["${i}_CHIP_POWER"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/chip_power | awk '{print $1}') "
            CARD_DATA["${i}_CHIP_TEMP"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/chip_temp | awk '{print $1}') "
            CARD_DATA["${i}_TPU_FREQ"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^tpu: | awk '{print $2}') "
            CARD_DATA["${i}_VPU_FREQ"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^vpu: | awk '{print $2}') "
            CARD_DATA["${i}_DDR_FREQ"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/clk | grep ^ddr: | awk '{print $2}') "
            CARD_DATA["${i}_TPU_USAGE"]+="$(cat /sys/class/bm-sophon/bm-sophon${k}/device/npu_usage | awk -F':' '{print $2}' | awk '{print $1}') "
            CARD_DATA["${i}_VPU_USAGE"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/media | tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/,$//'; echo ' ')"
            CARD_DATA["${i}_JPU_USAGE"]+="$(cat /proc/bmsophon/card${i}/bmsophon${k}/jpu | tr -d '\n' | grep -ao ':[0-9]*%' | tr -d ':' | tr '\n' ',' | tr -d '%' | sed 's/,$//'; echo ' ')"
        done
        CARD_DATA["${i}_CHIP_DDR_SIZE"]="$(echo "${CARD_DATA["${i}_CHIP_DDR_SIZE"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_CHIP_HEAP_SIZE"]="$(echo "${CARD_DATA["${i}_CHIP_HEAP_SIZE"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_CHIP_POWER"]="$(echo "${CARD_DATA["${i}_CHIP_POWER"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_CHIP_TEMP"]="$(echo "${CARD_DATA["${i}_CHIP_TEMP"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_TPU_FREQ"]="$(echo "${CARD_DATA["${i}_TPU_FREQ"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_VPU_FREQ"]="$(echo "${CARD_DATA["${i}_VPU_FREQ"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_DDR_FREQ"]="$(echo "${CARD_DATA["${i}_DDR_FREQ"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_TPU_USAGE"]="$(echo "${CARD_DATA["${i}_TPU_USAGE"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_VPU_USAGE"]="$(echo "${CARD_DATA["${i}_VPU_USAGE"]}" | sed 's/ *$//')"
        CARD_DATA["${i}_JPU_USAGE"]="$(echo "${CARD_DATA["${i}_JPU_USAGE"]}" | sed 's/ *$//')"
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
    echo "DDR_TYPE|${DDR_TYPE}|"
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
    echo "NET_SPEED_UPLOAD(KiB/s)|${NET_SPEED_UPLOAD}|"
    echo "NET_SPEED_DOWNLOAD(KiB/s)|${NET_SPEED_DOWNLOAD}|"
    echo "DISK_SPEED_READ(KiB/s)|${DISK_SPEED_READ}|"
    echo "DISK_SPEED_WRITE(KiB/s)|${DISK_SPEED_WRITE}|"
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
    # CV84X6 才有（/proc/bmtpu）；其他芯片此处为空，不额外占行
    if [ -n "${TPU_BMTPU_LINES}" ]; then
        echo "${TPU_BMTPU_LINES}"
    fi
    echo "BOARD_TYPE|${BOARD_TYPE}|"
    echo "MCU_VERSION|${MCU_VERSION}|"
    echo "KERNEL_VERSION|${KERNEL_VERSION}|"
    echo "KERNEL_BUILD_TIME|${KERNEL_BUILD_TIME}|"
    echo "SYSTEM_TYPE|${SYSTEM_TYPE}|"
    echo "DOCKER_VERSION|${DOCKER_VERSION}|"
    echo "MMC0_CID|${MMC0_CID}|"
    echo "MMC0_LIFE_TIME|${MMC0_LIFE_TIME}|"
    echo "MMC0_PRE_EOL_LIFE|${MMC0_PRE_EOL_LIFE}|"
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
        echo "CARD${i}_TYPE|${CARD_DATA["${i}_TYPE"]}|"
        echo "CARD${i}_CHIP_ID|${CARD_DATA["${i}_CHIP_ID"]}|"
        echo "CARD${i}_CHIP_NUM|${CARD_DATA["${i}_CHIP_NUM"]}|"
        echo "CARD${i}_CHIP_TYPE|${CARD_DATA["${i}_CHIP_TYPE"]}|"
        echo "CARD${i}_SN|${CARD_DATA["${i}_SN"]}|"
        echo "CARD${i}_POWER(W)|${CARD_DATA["${i}_POWER"]}|"
        echo "CARD${i}_TEMP(degree Celsius)|${CARD_DATA["${i}_TEMP"]}|"
        echo "CARD${i}_CHIP_DDR_SIZE(GiB)|${CARD_DATA["${i}_CHIP_DDR_SIZE"]}|"
        echo "CARD${i}_CHIP_HEAP_SIZE(MiB)|${CARD_DATA["${i}_CHIP_HEAP_SIZE"]}|"
        echo "CARD${i}_CHIP_POWER(W)|${CARD_DATA["${i}_CHIP_POWER"]}|"
        echo "CARD${i}_CHIP_TEMP(degree Celsius)|${CARD_DATA["${i}_CHIP_TEMP"]}|"
        echo "CARD${i}_TPU_FREQ(MHz)|${CARD_DATA["${i}_TPU_FREQ"]}|"
        echo "CARD${i}_VPU_FREQ(MHz)|${CARD_DATA["${i}_VPU_FREQ"]}|"
        echo "CARD${i}_DDR_FREQ(MHz)|${CARD_DATA["${i}_DDR_FREQ"]}|"
        echo "CARD${i}_TPU_USAGE(%)|${CARD_DATA["${i}_TPU_USAGE"]}|"
        echo "CARD${i}_VPU_USAGE(%)|${CARD_DATA["${i}_VPU_USAGE"]}|"
        echo "CARD${i}_JPU_USAGE(%)|${CARD_DATA["${i}_JPU_USAGE"]}|"
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
