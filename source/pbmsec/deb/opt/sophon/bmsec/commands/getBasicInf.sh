#!/bin/bash
###############################################
############zetao.zhang@sophgo.com#############
############shiwei.su@sophgo.com###############
###############################################

unset seNCtrl_SUB_INFOS
declare -a seNCtrl_SUB_INFOS

. ${seNCtrl_PWD}/commands/runCmd.sh all "if [ -e /sys/class/bm-tpu/bm-tpu0/device/npu_usage ]; then cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | grep -oE '[0-9]+' | head -1; else echo "NAN"; fi;\
mpstat -P ALL 1 1 | awk '/Average/ && /all/ {print 100 - \$12}';\
free -m | awk '/Mem/ {printf \"%.2f\", (1 - (\$7/\$2)) * 100}';echo "";\
result=\$(sudo cat /sys/kernel/debug/ion/bm_npu_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
result=\$(sudo cat /sys/kernel/debug/ion/bm_vpu_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
result=\$(sudo cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
echo \$((\$(cat /sys/class/thermal/thermal_zone0/temp) / 1000))/\$((\$(cat /sys/class/thermal/thermal_zone1/temp) / 1000));\
if [ -e /proc/device-tree/tsdma* ]; then echo "BM1684X"; else echo "BM1684"; fi;\
if [ -e /sbin/bm_version ]; then head -n 3 /sbin/bm_version; else head -n 3 /bm_bin/bm_version; fi | bash;\
result=\$(bm-smi --noloop --file /home/linaro/chip_status.info |grep Fault |wc -l); rm -rf /home/linaro/chip_status.info; if [ \$result -eq 1 ]; then echo "FAULT"; else echo "ACTIVE"; fi;\
" &> /dev/null

printf "%-3s%-8s%-15s%-7s%-7s%-7s%-7s%-7s%-7s%-12s%-12s\n" \
       "ID" "CHIPID" "SDK" "CPU" "TPU" "SYSMEM" "TPUMEM" "VPUMEM" "VPPMEM" "TEMP(C/B)" "CHIP_STATUS"
for ((i = 0; i < $seNCtrl_ALL_SUB_NUM; i++)); do
    if [[ "${seNCtrl_ALL_SUB_IP[$i]}" == "NAN" ]]; then continue; fi
    version_info=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep -m 1 'VERSION:' | awk '{print $2}')
    if [[ "$version_info" == "" ]]; then
        version_info_s=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep -m 1 "SophonSDK version:\|sophon-soc-libsophon :" | awk -F ": " '{print $2}')
        if [[ "$version_info_s" != "v"* ]] && [[ "$version_info_s" != "V"* ]] && [[ "$version_info_s" != "" ]]; then
            version_info="${seNCtrl_LIBSOPHON_SDK_VERSION[${version_info_s}]}"
            if [[ "$version_info" == "" ]]; then
                version_info="v$version_info_s"
            fi
        else
            version_info="$version_info_s"
        fi
    fi
    mapfile -t seNCtrl_SUB_INFOS < <(echo "${seNCtrl_RUN_LOG[$i]}")
    printf "%-3s%-8s%-15s%-7s%-7s%-7s%-7s%-7s%-7s%-12s%-10s\n" \
           "$(($i + 1))" "${seNCtrl_SUB_INFOS[7]}" "${version_info}" "${seNCtrl_SUB_INFOS[1]}%" "${seNCtrl_SUB_INFOS[0]}%" "${seNCtrl_SUB_INFOS[2]}%" "${seNCtrl_SUB_INFOS[3]}%" "${seNCtrl_SUB_INFOS[4]}%" "${seNCtrl_SUB_INFOS[5]}%" "${seNCtrl_SUB_INFOS[6]}" "${seNCtrl_SUB_INFOS[9]}"

done
