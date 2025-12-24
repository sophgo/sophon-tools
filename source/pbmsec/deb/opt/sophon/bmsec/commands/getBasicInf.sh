#!/bin/bash
###############################################
############zetao.zhang@sophgo.com#############
############shiwei.su@sophgo.com###############
###############################################

unset seNCtrl_SUB_INFOS
declare -a seNCtrl_SUB_INFOS

. ${seNCtrl_PWD}/commands/runCmd.sh all "echo -n getbiNO0:;if [ -e /sys/class/bm-tpu/bm-tpu0/device/npu_usage ]; then cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | grep -oE '[0-9]+' | head -1; else echo "NAN"; fi;\
echo -n getbiNO1:;mpstat -P ALL 1 1 | awk '/Average/ && /all/ {print 100 - \$12}';\
echo -n getbiNO2:;free -m | awk '/Mem/ {printf \"%.2f\", (1 - (\$7/\$2)) * 100}';echo "";\
echo -n getbiNO3:;result=\$(sudo cat /sys/kernel/debug/ion/bm_npu_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
echo -n getbiNO4:;result=\$(sudo cat /sys/kernel/debug/ion/bm_vpu_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
echo -n getbiNO5:;result=\$(sudo cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary 2>/dev/null | sed -n 's/.*rate:\([0-9]*\)%.*/\1/p');if [ -z \"\$result\" ]; then echo NAN; else echo \$result; fi;\
echo -n getbiNO6:;echo \$((\$(cat /sys/class/thermal/thermal_zone0/temp) / 1000))/\$((\$(cat /sys/class/thermal/thermal_zone1/temp) / 1000));\
echo -n getbiNO7:;if [ -e /proc/device-tree/tsdma* ]; then echo "BM1684X"; else echo "BM1684"; fi;\
echo -n getbiNO8:;if [ -e /sbin/bm_version ]; then head -n 3 /sbin/bm_version; else head -n 3 /bm_bin/bm_version; fi | bash;\
echo -n getbiNO9:;result=\$(bm-smi --noloop --file /dev/shm/chip_status.info |grep Fault |wc -l); rm -rf /dev/shm/chip_status.info; if [ \$result -eq 1 ]; then echo "FAULT"; else echo "ACTIVE"; fi;\
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
    seNCtrl_SUB_INFOS[0]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO0:' | sed 's/getbiNO0://')
    seNCtrl_SUB_INFOS[1]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO1:' | sed 's/getbiNO1://')
    seNCtrl_SUB_INFOS[2]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO2:' | sed 's/getbiNO2://')
    seNCtrl_SUB_INFOS[3]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO3:' | sed 's/getbiNO3://')
    seNCtrl_SUB_INFOS[4]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO4:' | sed 's/getbiNO4://')
    seNCtrl_SUB_INFOS[5]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO5:' | sed 's/getbiNO5://')
    seNCtrl_SUB_INFOS[6]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO6:' | sed 's/getbiNO6://')
    seNCtrl_SUB_INFOS[7]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO7:' | sed 's/getbiNO7://')
    seNCtrl_SUB_INFOS[8]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO8:' | sed 's/getbiNO8://')
    seNCtrl_SUB_INFOS[9]=$(echo "${seNCtrl_RUN_LOG[$i]}" | grep 'getbiNO9:' | sed 's/getbiNO9://')
    printf "%-3s%-8s%-15s%-7s%-7s%-7s%-7s%-7s%-7s%-12s%-10s\n" \
           "$(($i + 1))" "${seNCtrl_SUB_INFOS[7]}" "${version_info}" "${seNCtrl_SUB_INFOS[1]}%" "${seNCtrl_SUB_INFOS[0]}%" "${seNCtrl_SUB_INFOS[2]}%" "${seNCtrl_SUB_INFOS[3]}%" "${seNCtrl_SUB_INFOS[4]}%" "${seNCtrl_SUB_INFOS[5]}%" "${seNCtrl_SUB_INFOS[6]}" "${seNCtrl_SUB_INFOS[9]}"

done
