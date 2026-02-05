#!/bin/bash

CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
SOC_MODE_CPU_MODEL=("bm1684x" "bm1684" "bm1688" "cv186ah")
WORK_MODE="PCIE"
for element in "${SOC_MODE_CPU_MODEL[@]}"; do
    if [ "$element" == "$CPU_MODEL" ]; then
        WORK_MODE="SOC"
        break
    fi
done

make clean

if [[ "${WORK_MODE}" == "SOC" ]]; then
	if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
		make USE_GDMA_WITH_CORE=0
	elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
		make USE_GDMA_WITH_CORE=1
	fi
else
	make USE_GDMA_WITH_CORE=0
fi
