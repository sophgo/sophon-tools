#!/bin/bash

function memtest_s() {

	# 清空缓存
	function clear_mc() {
		sync
		echo 1 >/proc/sys/vm/drop_caches
		echo 2 >/proc/sys/vm/drop_caches
		echo 3 >/proc/sys/vm/drop_caches
		sync
	}

	# 报错终止
	function panic() {
		if [ $# -gt 0 ]; then
			echo "" >&1
			echo "[MEMTEST ERROR] $@" >&1
			echo "" >&1
			echo "[MEMTEST ERROR] $@" >&1 >>"$MEMTEST_ERROR_LOG"
			wall "[MEMTEST ERROR] $@"
		fi
		systemctl stop memtest_s.service
	}

	function file_validate() {
		local file
		file=$(eval echo \$1)
		[ -r ${file} ] || panic "$i \"$file\" is not readable"
	}

	# 获取ion使用率
	function get_ion_usage() {
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

	# memtester进程
	function memtester_fun() {
		echo "[MEMTEST INFO] memtester work_dir:$work_dir/memtester_dir"
		pushd "$work_dir/memtester_dir"
		loop=$1
		echo "[MEMTEST INFO] memtester a53 test loop: $loop"
		chmod +x memtester
		while true; do
			if [[ "$loop" == "0" ]]; then
				break
			fi
			# 预留300M的空间
			freeMemMB=$(free -m | grep ^Mem | awk '{print $NF - 300}')
			./memtester ${freeMemMB}M 1
			if [[ "$?" != "0" ]]; then
				panic "memtester error"
			fi
			if [[ "$loop" != "-"* ]]; then
				loop=$(($loop - 1))
			fi
			sleep 0.2
		done
		popd
		echo "[MEMTEST INFO] memtester a53 done!!!"
	}

	# GDMA进程
	function gdma_fun() {
		LOOP_NUM=${1}
		DEV_ID=0
		if [[ "${LOOP_NUM}" == "" ]]; then
			LOOP_NUM=-1
		fi
		echo "[MEMTEST INFO] work_dir:$work_dir"
		pushd "$work_dir/memtest_gdma"
		t_num=4
		if [[ "${CPU_MODEL}" == "bm1684x" ]] || [[ "${CPU_MODEL}" == "bm1684" ]]; then
			TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_npu_heap_dump")
			VPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpu_heap_dump")
			VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/bm_vpp_heap_dump")
			t_num=4
		elif [[ "${CPU_MODEL}" == "bm1688" ]] || [[ "${CPU_MODEL}" == "cv186ah" ]]; then
			TPU_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_npu_heap_dump")
			VPP_MEM_USAGE=$(get_ion_usage "/sys/kernel/debug/ion/cvi_vpp_heap_dump")
			VPU_MEM_USAGE="0"
			t_num=4
		elif [[ "${WORK_MODE}" == "PCIE" ]]; then
			t_num=8
			DEV_ID=${TEST_DEV_ID}
		fi
		if [[ "${WORK_MODE}" == "SOC" ]]; then
			if [[ "$TPU_MEM_USAGE" != "0" ]] ||
				[[ "$VPU_MEM_USAGE" != "0" ]] ||
				[[ "$VPP_MEM_USAGE" != "0" ]]; then
				panic "device mem usage not 0"
			fi
		fi
		rm -f ./*.txt
		chmod +x memtest_gdma
		./memtest_gdma ${DEV_ID} '[1,16,1024,1024]' ${LOOP_NUM} ${t_num}
		if [[ "$?" != "0" ]]; then
			panic "memtest_gdma error"
		fi
		popd
	}

	work_dir="$1"
	inloop="$2"
	rm -rf "$work_dir/logs"
	mkdir -p "$work_dir/logs"
	MEMTEST_GDMA_LOG="$work_dir/logs/gdma.log"
	MEMTEST_A53_LOG="$work_dir/logs/memtester.log"
	MEMTEST_ERROR_LOG="$work_dir/logs/error.log"
	MEMTEST_DMESG_LOG="$work_dir/logs/dmesg.log"

	touch "$MEMTEST_DMESG_LOG"
	touch "$MEMTEST_A53_LOG"

	file_validate /proc/cpuinfo
	# CPU NAME
	CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
	# WORK MODE
	SOC_MODE_CPU_MODEL=("bm1684x" "bm1684" "bm1688" "cv186ah")
	# TEST CORE ID (only for PCIE MODE)
	if [[ "${PCIE_DEV_ID}" != "" ]]; then
		TEST_DEV_ID=${PCIE_DEV_ID}
	else
		TEST_DEV_ID=0
	fi
	WORK_MODE="PCIE"
	for element in "${SOC_MODE_CPU_MODEL[@]}"; do
		if [ "$element" == "$CPU_MODEL" ]; then
			WORK_MODE="SOC"
			break
		fi
	done
	if [[ "${WORK_MODE}" == "PCIE" ]]; then
		echo "[MEMTEST INFO] Get cpu name: $CPU_MODEL, PCIe EP mode"
		gdma_fun "$inloop" &>$MEMTEST_GDMA_LOG
		# not run memtester
		wall "[MEMTEST INFO] test loop $inloop end!!!, please check log file at $work_dir/logs/"
		dmesg >$MEMTEST_DMESG_LOG
		sleep 3
		dmesg -T >>$MEMTEST_DMESG_LOG
	else
		gdma_fun &>$MEMTEST_GDMA_LOG &
		# wait gdma test malloc success
		sleep 30
		memtester_fun "$inloop" &>$MEMTEST_A53_LOG
		wall "[MEMTEST INFO] test loop $inloop end!!!, please check log file at $work_dir/logs/"
		dmesg >$MEMTEST_DMESG_LOG
		sleep 3
		dmesg -T >>$MEMTEST_DMESG_LOG
	fi
}

echo "MEMTEST VERSION: V1.4.0"

# prepare memtest_gdma
dir_path="$(dirname "$(readlink -f "$0")")"
pushd $dir_path/memtest_gdma
sudo bash build.sh || echo "[MEMTEST ERROR] build memtest gdma error"
popd

inloop=$1
if [[ "$inloop" == "" ]]; then
	inloop=1
fi

fun_str=$(declare -f memtest_s | gzip -c - | base64)

sudo systemctl stop memtest_s.service 2>/dev/null
sudo systemctl reset-failed memtest_s.service 2>/dev/null
sudo rm -f /run/systemd/transient/memtest_s.service 2>/dev/null
sudo systemctl daemon-reload

sudo systemd-run --unit=memtest_s bash -c \
	"source /dev/stdin <<< \$(echo \"$fun_str\" | base64 -d | gzip -d -c -); export \
PCIE_DEV_ID=${PCIE_DEV_ID}; memtest_s $dir_path $inloop;"
sleep 3
sudo systemctl status memtest_s.service --no-page -l
if [[ "$(systemctl is-active memtest_s.service)" != "active" ]]; then
	wall "[MEMTEST ERROR] memtest_s.service start failed, please check runtime and logs at: $dir_path/logs/"
fi

echo "[MEMTEST INFO] loop: $inloop"
echo "[MEMTEST INFO] you can use 'systemctl status memtest_s.service --no-page -l' check test server status"
echo "[MEMTEST INFO] you can use 'systemctl stop memtest_s.service' stop test server"
echo "[MEMTEST INFO] you can check test log at: $dir_path/logs/"
