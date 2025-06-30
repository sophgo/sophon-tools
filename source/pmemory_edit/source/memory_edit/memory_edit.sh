#!/bin/bash

DTC_FLAGS='-q'
memory_edit_PWD="$(dirname "$(readlink -f "$0")")"
log_file_path="${memory_edit_PWD}/log_$(date +"%Y_%m_%d_%H_%M_%S").log"
date > $log_file_path
runtime_info_target="noSupport"
runtime_info_boot_file="noSupport"
# MEMORY_EDIT_RAMDISK=0
# MEMORY_EDIT_ITB_FILE=""
# MEMORY_EDIT_CHPI_TYPE=""
#########################################################解包打包函数####################################
# 获取its节点信息，参数一文件名，参数二节点匹配开始字符串，参数三信息匹配字符串
get_info_from_its_data=""
function get_info_from_its(){
	get_info_from_its_dts_file_name=$1
	IFS="|" read -ra dts_start_str_array <<< "$2"
	get_info_from_its_dts_info_str=$3
	get_info_from_its_data=""
	get_info_from_its_flag=0
	match_found=0
	function get_info_from_its_str(){
		for str in "${dts_start_str_array[@]}"; do
			if [[ $1 =~ $str ]]; then
				match_found=1
				break
			fi
		done
	}
	while IFS= read -r line; do
		match_found=0
		get_info_from_its_str "$line"
		if [[ "$match_found" == "1" ]];then
			get_info_from_its_flag=1
		elif [[ $line =~ $get_info_from_its_dts_info_str ]] && [[ $get_info_from_its_flag -eq 1 ]]; then
			get_info_from_its_data="$line"
			get_info_from_its_flag=0
			break
		fi
	done < "$get_info_from_its_dts_file_name"
	echo "Info: find $get_info_from_its_dts_info_str info: $get_info_from_its_data"
	if [ "$get_info_from_its_data" == "" ]; then echo "Error: cannot find $dts_start_str:$get_info_from_its_dts_info_str at $get_info_from_its_dts_file_name"; return -1; fi
}
function de_emmcfile(){
	PATH="${memory_edit_PWD}/bintools:${PATH}"
	OUTPUT_DIR="${memory_edit_PWD}/output"
	sudo rm -rf ${OUTPUT_DIR}
	if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
	mkdir -p ${OUTPUT_DIR}
	if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
	get_info_from_its ${memory_edit_PWD}/multi.its "cvitek kernel|sophon kernel|bitmain kernel" "data" >> $log_file_path
	image_file_name=$(echo "$get_info_from_its_data" | awk -F'"' '{print $2}' | awk -F'/' '{print $2}')
	echo Info: dump Image $image_file_name ...
	${memory_edit_PWD}/bintools/dumpimage -T flat_dt -p 0 -o ${OUTPUT_DIR}/$image_file_name ${memory_edit_PWD}/$runtime_info_boot_file
	if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
	get_info_from_its ${memory_edit_PWD}/multi.its "cvitek ramdisk|sophon ramdisk|bitmain ramdisk" "data" >> $log_file_path
	image_file_name=$(echo "$get_info_from_its_data" | awk -F'"' '{print $2}' | awk -F'/' '{print $2}')
	echo Info: dump ramdisk $image_file_name ...
	${memory_edit_PWD}/bintools/dumpimage -T flat_dt -p 1 -o ${OUTPUT_DIR}/$image_file_name ${memory_edit_PWD}/$runtime_info_boot_file
	if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
	if [[ "$MEMORY_EDIT_RAMDISK" == "1" ]]; then
		echo Info: cpio dump ramdisk $image_file_name ...
		mkdir -p ${OUTPUT_DIR}/ramdisk
		image_file="$image_file_name"
		if [[ $image_file_name == *".gz" ]]; then
			pushd ${OUTPUT_DIR}
			gzip -d $image_file_name
			popd
			image_file=$(echo "$image_file_name" | sed 's/\.gz$//')
		fi
		pushd ${OUTPUT_DIR}/ramdisk
		sudo ${memory_edit_PWD}/bintools/cpio -idmv < ${OUTPUT_DIR}/$image_file
		popd
	fi
	echo Info: dump dtbs ...
	DTB_FILES=""
	dtb_index=0
	DTB_FILES=$(grep 'dtb' ${memory_edit_PWD}/multi.its | grep 'data =' | awk -F'"' '{print $(NF-1)}' | awk -F'/' '{print $(NF)}')
	image_num="$(grep 'data = ' ${memory_edit_PWD}/multi.its | wc -l)"
	dtb_num="$(grep '.dtb"' ${memory_edit_PWD}/multi.its | grep 'data =' | wc -l)"
	dtb_index=$(( $image_num - $dtb_num ))
	if [[ "$DTB_FILES" == "" ]]; then
		echo "Error: cannot read dts info from multi.its"
		return -1
	fi
	ITB_FILE_DTB_NUM=$(${memory_edit_PWD}/bintools/dumpimage -l ${memory_edit_PWD}/$runtime_info_boot_file | grep 'Flat Device Tree' | wc -l)
	MULTI_FILE_DTB_NUM=$(echo "$DTB_FILES" | wc -l)
	if [[ "$ITB_FILE_DTB_NUM" != "$MULTI_FILE_DTB_NUM" ]]; then
		echo "Error: itb file dts num [$ITB_FILE_DTB_NUM] is not multi file dts num [$MULTI_FILE_DTB_NUM], please check files in /boot"
		return -1
	fi
	for DTB_FILE in $DTB_FILES
	do
			echo Info: dump ${dtb_index} : ${DTB_FILE} ...
			${memory_edit_PWD}/bintools/dumpimage -T flat_dt -p ${dtb_index} -o ${OUTPUT_DIR}/${DTB_FILE} ${memory_edit_PWD}/$runtime_info_boot_file
			if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
			${memory_edit_PWD}/bintools/dtc -I dtb -O dts ${OUTPUT_DIR}/${DTB_FILE} > ${OUTPUT_DIR}/$(echo ${DTB_FILE} | sed 's/.dtb/.dts/g') ${DTC_FLAGS}
			if [ "$?" != "0" ]; then echo "Error: de_emmcfile"; return -1; fi
			((dtb_index=$dtb_index+1))
	done
}
function en_emmcfile(){
	PATH="${memory_edit_PWD}/bintools:${PATH}"
	if [ ! -d ${memory_edit_PWD}/output -o ! -e ${memory_edit_PWD}/multi.its ]; then
		echo Error: no output or multi.its
		return -1
	fi
	OUTPUT_DIR="${memory_edit_PWD}/output"
	pushd ${memory_edit_PWD}/output
	if [ "$?" != "0" ]; then return -1; fi
	if [[ "$MEMORY_EDIT_RAMDISK" == "1" ]]; then
		get_info_from_its ${memory_edit_PWD}/multi.its "cvitek ramdisk|sophon ramdisk|bitmain ramdisk" "data" >> $log_file_path
		image_file_name=$(echo "$get_info_from_its_data" | awk -F'"' '{print $2}' | awk -F'/' '{print $2}')
		if [[ $image_file_name == *".gz" ]]; then
			image_file=$(echo "$image_file_name" | sed 's/\.gz$//')
		else
			image_file=$image_file_name
		fi
		echo Info: cpio pack ramdisk $image_file ...
		pushd ${OUTPUT_DIR}/ramdisk
		if [ -f ${OUTPUT_DIR}/$image_file ]; then
			rm -rf ${OUTPUT_DIR}/$image_file
		fi
		find . | ${memory_edit_PWD}/bintools/cpio -o -H newc > ${OUTPUT_DIR}/$image_file
		popd
		if [[ $image_file_name == *".gz" ]]; then
			pushd ${OUTPUT_DIR}
			gzip $image_file
			popd
		fi
	fi
	DTS_FILES=$(find . -name "*.dts")
	DTB_FILES=$(grep 'dtb' ${memory_edit_PWD}/multi.its | grep 'data =' | awk -F'"' '{print $(NF-1)}' | awk -F'/' '{print $(NF)}')
	if [[ "$DTB_FILES" == "" ]]; then
		echo "Error: cannot read dts info from multi.its"
		return -1
	fi
	for DTB_FILE in $DTB_FILES
	do
		DTS_FILE=$(echo ${DTB_FILE} | sed 's/.dtb/.dts/g')
		if test -f "$DTS_FILE"
		then
			echo Info: dts2dtd : $( echo $DTS_FILE | sed 's#.dts$#.dtb#g' )
			${memory_edit_PWD}/bintools/dtc -I dts -O dtb "$DTS_FILE" > "$DTB_FILE" ${DTC_FLAGS}
			if [ "$?" != "0" ]; then echo "Error: en_emmcfile"; return -1; fi
		fi
	done
	cp ${memory_edit_PWD}/multi.its .
	if grep -q "cvitek kernel" ./multi.its; then
		echo "Info: make image added key ..."
		../bintools/mkimage -p 0x2000 -D "-q -I dts -O dtb -p 500" -f ./multi.its $runtime_info_boot_file
	else
		../bintools/mkimage -p 0x2000 -D "-q -I dts -O dtb -p 500" -f ./multi.its $runtime_info_boot_file
	fi
	if [ "$?" != "0" ]; then echo "Error: en_emmcfile"; return -1; fi
	popd
}
function clean_dir(){
	sudo rm -rf ${memory_edit_PWD}/output
	sudo rm -rf ${memory_edit_PWD}/*.log
	sudo rm -rf ${memory_edit_PWD}/*.itb
	sudo rm -rf ${memory_edit_PWD}/multi.its
}
#########################################################解包打包函数####################################
###########################################功能函数区域##################################################
#定义删除函数
function del_text(){
	echo "Info: delete $1 - $2"
	flag=0
	findflag=1
	while IFS= read -r line; do
		if [[ "${line:0:${#1}}" == "$1" ]]; then
			flag=2
			findflag=0
		elif [[ "${line:0:${#2}}" == "$2" ]] && [[ $flag -eq 2 ]]; then
			flag=1
		fi
		if [[ $flag -eq 2 ]]; then
			flag=2
		elif [[ $flag -eq 1 ]]; then
			flag=0
		else
			echo "$line"
		fi
	done < "$3" > "$3.new"
	return $findflag
}
#定义新增ion内存区域函数 参数1文件名 参数2key值 参数3内存标记 参数4内存起始位置 参数5内存大小
function add_ion(){
	echo "Info: add $1 $2 ddr$3 start:$4 size: $5"
	size_s4g=$(printf "0x%x" $(($5 % $SIZE4G)))
	size_b4g=$(printf "0x%x" $(($5 / $SIZE4G)))
	start_s4g=$(printf "0x%x" $(($4 % $SIZE4G)))
	start_b4g=$(printf "0x%x" $(($4 / $SIZE4G)))
	start_index=$(($3 + $start_b4g))
	echo "/ {
	reserved-memory {
		ion_${2}_mem {
			compatible = \"${2}-region\";
			reg = <${start_index} ${start_s4g} ${size_b4g} ${size_s4g}>;
			phandle = <${memory_phandle[$2]}>;
		};
	};
};" >> "$1.new"
}
#定义新增自定义修改预留内存区域函数 参数1文件名 参数2预留节点名 参数3内存标记 参数4内存起始位置 参数5内存大小
function add_edit_map(){
	echo "Info: add $1 $2 ddr$3 start:$4 size: $5"
	s4g=$(printf "0x%x" $(($5 % $SIZE4G)))
	b4g=$(printf "0x%x" $(($5 / $SIZE4G)))
	echo "/ {
	reserved-memory {
		${2} {
			reg = <${3} ${4} ${b4g} ${s4g}>;
		};
	};
};" >> "$1.new"
}
# 获取设备树中的内存配置信息 参数1文件名 参数2节点名 参数3包含内存配置子节点匹配字符串 返回值get_mem_info_data大小 返回值get_mem_info_data_*其他信息
get_mem_info_data=0
get_mem_info_data_start=0
get_mem_info_data_end=0
function get_mem_info(){
	data=()
	get_mem_info_data=""
	while IFS= read -r line; do
		if [[ $line =~ $2 ]];then
			flag=1
		elif [[ $line =~ $3 ]] && [[ $flag -eq 1 ]]; then
			data_str=$(echo "$line" | sed 's/.*<\(.*\)>;/\1/')
			data=(${data_str// / })
			flag=0
		fi
	done < "$1"
	get_mem_info_data=$(($((${data[2]})) * $size_4g + $((${data[3]}))))
	get_mem_info_data_start=$(($((${data[0]})) * $size_4g + $((${data[1]}))))
	get_mem_info_data_end=$((${get_mem_info_data} + ${get_mem_info_data_start}))
	echo "Info: find $2 mem size: $(printf "0x%x" $get_mem_info_data)"
	echo "Info: find $2 mem start: $(printf "0x%x" $get_mem_info_data_start)"
	echo "Info: find $2 mem end: $(printf "0x%x" $get_mem_info_data_end)"
}
get_dts_node_info_data=""
function get_dts_node_info(){
	data=()
	get_dts_node_info_data=""
	while IFS= read -r line; do
		if [[ "$line" =~ "$2" ]];then
			flag=1
		elif [[ "$line" =~ "$3" ]] && [[ $flag -eq 1 ]]; then
			get_dts_node_info_data=$(echo "$line")
			flag=0
		fi
	done < "$1"
	echo "Info: find $2 dts node info: $get_dts_node_info_data"
}
###########################################功能函数区域##################################################
# 判断程序输入参数
print_info=0
radix_markers=0 # 0-十六进制 1-十进制
# 假设三个ion内存全部都需要进行配置
user_mem=("npu" "vpp" "vpu")
del_mem=()
full_mem=("npu" "vpu" "vpp")
SIZE1M="0x100000"
size_1m=$((SIZE1M))
SIZE4M="0x400000"
size_4m=$((SIZE4M))
SIZE4G="0x100000000"
size_4g=$((SIZE4G))
# 内核的占用空间
const_kernel_minimal=$((1024 * 1024 * 1024))
# 储存三个ion内存大小
declare -A user_mem_size
# 储存三个ion内存32位以下大小
declare -A user_mem_size_l4g
# 储存三个ion内存32位以上大小
declare -A user_mem_size_4g
# 储存三个ion内存在bitmain-ion中的索引
declare -A mem_reg_index
mem_reg_index["npu"]="0"
mem_reg_index["vpp"]="1"
mem_reg_index["vpu"]="2"
# 储存三个ion内存在全局的唯一索引
declare -A memory_phandle
# 储存三个ion内存默认内存标记
declare -A memory_ddr_index
memory_ddr_index["npu"]="0x01"
memory_ddr_index["vpp"]="0x04"
memory_ddr_index["vpu"]="0x03"
# 储存三个DDR标记对应的大小
declare -A memory_ddr_size
declare -A ion_mem_start
declare -A ion_mem_end

mem_phandle_name="			phandle"
need_del_vpu=0
need_del_npu=0
need_del_vpp=0
have_ion_vpu_mem=0
have_ion_npu_mem=0
have_ion_vpp_mem=0
have_bmtpu=0
have_bitmain_vdec=0
ddr_data_str=""
ddr_count=0
ddr_data=()
memory_ddr1_size=""
memory_ddr2_size=""
memory_ddr3_size=""
memory_ddr4_size=""
ddr_size=0
ddr1_size=0
ddr2_size=0
ddr3_size=0
ddr4_size=0
echo "INFO: version: 2.12"
if ( [ $# -eq 1 ] || [ $# -eq 2 ] ) && [ "$1" == "-p" ]; then
	# 仅打印信息
	print_info=1
elif [ $# -eq 2 ] && [ "$1" == "-d" ]; then
	# 仅解包
	runtime_info_boot_file=$2
	de_emmcfile
	exit 0
elif [ $# -eq 2 ] && [ "$1" == "-e" ]; then
	# 仅打包
	runtime_info_boot_file=$2
	en_emmcfile
	exit 0
elif [ $# -eq 1 ] && [ "$1" == "--clean" ]; then
	# 清理目录
	clean_dir
	exit 0
elif ( [ $# -eq 7 ] || [ $# -eq 8 ] ) && [ "$1" == "-c" ] && [ "$2" == "-npu" ] && [[ "$3" =~ ^0x[0-9a-fA-F]+$ ]] && [ "$4" == "-vpu" ] && [[ "$5" =~ ^0x[0-9a-fA-F]+$ ]] && [ "$6" == "-vpp" ] && [[ "$7" =~ ^0x[0-9a-fA-F]+$ ]]; then
	# 做内存修改
	print_info=0
	radix_markers=0
elif ( [ $# -eq 7 ] || [ $# -eq 8 ] ) && [ "$1" == "-c" ] && [ "$2" == "-npu" ] && [[ "$3" =~ ^[0-9]+$ ]] && [ "$4" == "-vpu" ] && [[ "$5" =~ ^[0-9]+$ ]] && [ "$6" == "-vpp" ] && [[ "$7" =~ ^[0-9]+$ ]]; then
	# 做内存修改
	print_info=0
	radix_markers=1
else
	echo "Error: Invalid parameters. Please refer to the following example"
	echo "${memory_edit_PWD}/memory_edit.sh -p [dts name] # for print infomation"
	echo "${memory_edit_PWD}/memory_edit.sh -c -npu 0x80000000 -vpu 0x80000000 -vpp 0x80000000 [dts name] # for config mem, The memory size unit is Byte"
	echo "${memory_edit_PWD}/memory_edit.sh -c -npu 2048 -vpu 2048 -vpp 2048 [dts name] # for config mem, The memory size unit is MiB"
	echo "for bm1688, please use \"memory_edit.sh -c -npu 2048 -vpu 0 -vpp 2048\""
	echo "${memory_edit_PWD}/memory_edit.sh -d dtbfile # for de_emmcboot.itb"
	echo "${memory_edit_PWD}/memory_edit.sh -e dtbfile # for en_emmcboot.itb"
	echo "${memory_edit_PWD}/memory_edit.sh --clean # clean this dir"
	exit -1
fi
if [[ "$MEMORY_EDIT_ITB_FILE" != "" ]] && [[ "$MEMORY_EDIT_CHPI_TYPE" != "" ]]; then
	runtime_info_boot_file=$MEMORY_EDIT_ITB_FILE
	runtime_info_target=$MEMORY_EDIT_CHPI_TYPE
elif [ -e "/boot/emmcboot.itb" ]; then
	runtime_info_boot_file="emmcboot.itb"
	runtime_info_target="bm1684"
elif [ -e "/boot/boot.itb" ]; then
	runtime_info_boot_file="boot.itb"
	runtime_info_target="bm1688"
else
	echo "Error: cannot find boot file"
	exit -1
fi
if [[ "$MEMORY_EDIT_ITB_FILE" == "" ]] || [[ "$MEMORY_EDIT_CHPI_TYPE" == "" ]]; then
	cp /boot/$runtime_info_boot_file ${memory_edit_PWD}/
	cp /boot/multi.its ${memory_edit_PWD}/
fi
de_emmcfile >> $log_file_path
# 获取当前使用设备树信息
if [ $# -eq 8 ]; then
	dts_file_name=$8
elif [ $# -eq 2 ]; then
	dts_file_name=$2
else
	if [[ "$runtime_info_target" == "bm1684" ]]; then
		dts_file_name=$(tr -d '\0' </proc/device-tree/info/file-name)
	elif [[ "$runtime_info_target" == "bm1688" ]]; then
		# dts_file_name="athena2_wevb_1686a_emmc.dts"
		sudo dd if=/dev/mmcblk0boot1 of=${memory_edit_PWD}/bm1688_dts_name.log count=32 bs=1 skip=160 2> /dev/null
		dts_file_name=$(tr -d '\0' < ${memory_edit_PWD}/bm1688_dts_name.log)
		get_dts_node_info ${memory_edit_PWD}/multi.its "${dts_file_name} " "fdt =" >> $log_file_path; fdt_node_name=$(echo "$get_dts_node_info_data" | awk -F'"' '{print $2}')
		get_dts_node_info ${memory_edit_PWD}/multi.its "${fdt_node_name} " "data =" >> $log_file_path; dts_file_name=$(echo "$get_dts_node_info_data" | awk -F'"' '{print $2}' | awk -F'/' '{print $2}')
	fi
	fi
if [[ "$dts_file_name" == "" ]]; then
	echo "Error: cannot find used dts file on ${runtime_info_target}"
	exit -1
fi
if [ "$?" != "0" ]; then echo "Error: de_emmcfile" | tee -a $log_file_path; exit -1; fi
converted_dts_file_name="${dts_file_name%.dtb}"
if [[ $converted_dts_file_name != *.dts ]]; then
		dts_file_name="${converted_dts_file_name}.dts"
fi
file_path="${memory_edit_PWD}/output/${dts_file_name}"
echo "Info: use dts file $file_path"
# 判断芯片型号
if [[ $dts_file_name == *"bm1684x"* ]]; then
	soc_name="bm1684x"
elif [[ "$runtime_info_target" == "bm1688" ]]; then
	soc_name="bm1688"
	unset full_mem[1]
	unset user_mem[2]
else
	soc_name="bm1684"
fi
echo "Info: chip is $soc_name" >> $log_file_path
# 获取ddr信息
echo "Info: =======================================================================" | tee -a $log_file_path
echo "Info: get ddr information ..." | tee -a $log_file_path
get_info_from_its "$file_path" "	memory |	memory@" "		reg" >> $log_file_path
ddr_data_str=$(echo "$get_info_from_its_data" | sed 's/.*<\(.*\)>;/\1/')
ddr_count=$(echo "$ddr_data_str" | awk -F " " '{print NF}')
while read -r -d ' ' element; do
	ddr_data+=("$((element))")
done <<< "$ddr_data_str "
echo "Info: ddr_data line $ddr_data_str" >> $log_file_path
echo "Info: ddr_data ${ddr_data[@]}" >> $log_file_path
echo "Info: ddr_data_count $ddr_count" >> $log_file_path
# 16个参数
if [[ $ddr_count -eq 16 ]]; then
	ddr1_size=$((ddr_data[2] * size_4g + ddr_data[6] * size_4g + ddr_data[3] + ddr_data[7]))
	echo "Info: ddr12_size $ddr1_size Byte [$(($ddr1_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr3_size=$((ddr_data[10] * size_4g + ddr_data[11]))
	echo "Info: ddr3_size $ddr3_size Byte [$(($ddr3_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr4_size=$((ddr_data[14] * size_4g + ddr_data[15]))
	echo "Info: ddr4_size $ddr4_size Byte [$(($ddr4_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr_size=$((ddr1_size + ddr3_size + ddr4_size))
	ddr_sizemb=$((ddr_size / 1024 / 1024))
	echo "Info: ddr_size $ddr_sizemb MiB" | tee -a $log_file_path
# 12个参数
elif [[ $ddr_count -eq 12 ]]; then
	ddr1_size=$((ddr_data[2] * size_4g + ddr_data[3]))
	echo "Info: ddr12_size $ddr1_size Byte [$(($ddr1_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr3_size=$((ddr_data[6] * size_4g + ddr_data[7]))
	echo "Info: ddr3_size $ddr3_size Byte [$(($ddr3_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr4_size=$((ddr_data[10] * size_4g + ddr_data[11]))
	echo "Info: ddr4_size $ddr4_size Byte [$(($ddr4_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr_size=$((ddr1_size + ddr3_size + ddr4_size))
	ddr_sizemb=$((ddr_size / 1024 / 1024))
	echo "Info: ddr_size $ddr_sizemb MiB" | tee -a $log_file_path
# 8个参数
elif [[ $ddr_count -eq 8 ]]; then
	echo "Error: cannot support ddr info: ddr_count:${ddr_count}" | tee -a $log_file_path
	exit -1
	ddr1_size=$((ddr_data[2] * size_4g + ddr_data[3]))
	echo "Info: ddr1_size $ddr1_size Byte [$(($ddr1_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr2_size=$((ddr_data[6] * size_4g + ddr_data[7]))
	echo "Info: ddr2_size $ddr2_size Byte [$(($ddr2_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr_size=$((ddr1_size + ddr2_size))
	ddr_sizemb=$((ddr_size / 1024 / 1024))
	echo "Info: ddr_size $ddr_sizemb MiB" | tee -a $log_file_path
# 4个参数
elif [[ $ddr_count -eq 4 ]]; then
	ddr1_size=$((ddr_data[2] * size_4g + ddr_data[3]))
	echo "Info: ddr1_size $ddr1_size Byte [$(($ddr1_size / $size_1m)) MiB]" | tee -a $log_file_path
	ddr_size=$((ddr1_size))
	ddr_sizemb=$((ddr_size / 1024 / 1024))
	echo "Info: ddr_size $ddr_sizemb MiB" | tee -a $log_file_path
else
	echo "Error: cannot support ddr info" | tee -a $log_file_path
	exit -1
fi
if ([[ $ddr1_size -eq 0 ]] || [[ $ddr3_size -eq 0 ]] || [[ $ddr4_size -eq 0 ]]) && [[ $runtime_info_target == "bm1684" ]]; then
	echo "Error: cannot support ddr info ddr1_size:$ddr1_size ddr3_size:$ddr3_size ddr4_size:$ddr4_size" | tee -a $log_file_path
	exit -1
fi
# 获取当前配置的方案情况
get_mem_info "$file_path" "armfw_mem" "reg =" >> $log_file_path; armfw_mem_size=$get_mem_info_data
get_mem_info "$file_path" "arm_mem" "reg =" >> $log_file_path; arm_mem_size=$get_mem_info_data
get_mem_info "$file_path" "smmu_mem" "reg =" >> $log_file_path; smmu_mem_size=$get_mem_info_data
get_mem_info "$file_path" "bl31_mem" "reg =" >> $log_file_path; bl31_mem_size=$get_mem_info_data
get_mem_info "$file_path" "ramoops_mem" "reg =" >> $log_file_path; ramoops_mem_size=$get_mem_info_data; ramoops_mem_start=$get_mem_info_data_start
npu_size_add=0
if [[ $runtime_info_target == "bm1688" ]]; then
	get_mem_info "$file_path" "linux,cma" "alloc-ranges =" >> $log_file_path;
	bm1688_cma_mem_end=$((${get_mem_info_data_end} % ${size_4g}))
	npu_size_add=$((${npu_size_add} + ${bm1688_cma_mem_end} + ${size_1m} * 200))
else
	npu_size_add=$(($armfw_mem_size + $arm_mem_size + $smmu_mem_size))
fi
echo "Info: npu_size_add: $(printf "0x%x" ${npu_size_add})" >> $log_file_path
vpu_mem_size=0x8000000
vpu_mem_size_to512M_flag=0
if [[ $runtime_info_target == "bm1684" ]]; then
	if [[ $ramoops_mem_start -eq $(( "0x314000000" + "0" )) ]]; then
		vpu_mem_size_to512M_flag=1
	fi
	vpu_size_add=0
	echo "Info: vpu_mem_size: $(printf "0x%x" ${vpu_mem_size})" >> $log_file_path
	if [[ $vpu_mem_size_to512M_flag -eq 1 ]]; then
		vpu_size_add=$(($const_kernel_minimal))
		echo "Info: vpu_fir_mem to 512M" >> $log_file_path
	else
		vpu_size_add=$(($vpu_mem_size + $const_kernel_minimal))
	fi
	# BM1684(X)的VPU高位需要预留1MB大小的内存区域
	vpu_size_add=$(($vpu_size_add + $size_1m))
	echo "Info: vpu_size_add: $(printf "0x%x" ${vpu_size_add})" >> $log_file_path
fi
vpp_size_add=0
if [[ $runtime_info_target == "bm1688" ]]; then
	if [[ "$ddr4_size" != "0" ]]; then
		memory_ddr_index["vpp"]="0x04"
	elif [[ "$ddr3_size" != "0" ]]; then
		memory_ddr_index["vpp"]="0x03"
	else
		memory_ddr_index["vpp"]="0x01"
	fi
fi
# 打印最大可能ion内存分配空间
memory_ddr_size["0x01"]=$ddr1_size
memory_ddr_size["0x02"]=$ddr2_size
memory_ddr_size["0x03"]=$ddr3_size
memory_ddr_size["0x04"]=$ddr4_size
echo "Info: =======================================================================" | tee -a $log_file_path
echo "Info: get max memory size ..." | tee -a $log_file_path
if [[ $runtime_info_target == "bm1688" ]]; then
	echo "Info: max npu+vpp size: $(printf "0x%x" $(($ddr_size - $npu_size_add))) [$(printf "%d MiB" "$(($(($ddr_size - $npu_size_add)) / $SIZE1M))")]" | tee -a $log_file_path
	echo "Info: max npu size: $(printf "0x%x" $(($ddr_size - $npu_size_add))) [$(printf "%d MiB" "$(($(($ddr_size - $npu_size_add)) / $SIZE1M))")]" | tee -a $log_file_path
elif [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: max npu size: $(printf "0x%x" $(($ddr1_size - $npu_size_add))) [$(printf "%d MiB" "$(($(($ddr1_size - $npu_size_add)) / $SIZE1M))")]" | tee -a $log_file_path
fi
if [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: max vpu size: $(printf "0x%x" $(($ddr3_size - $vpu_size_add))) [$(printf "%d MiB" "$(($(($ddr3_size - $vpu_size_add)) / $SIZE1M))")]" | tee -a $log_file_path
fi
if [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: max vpp size: $(printf "0x%x" $(($ddr4_size - $vpp_size_add))) [$(printf "%d MiB" "$(($(($ddr4_size - $vpp_size_add)) / $SIZE1M))")]" | tee -a $log_file_path
elif [[ $runtime_info_target == "bm1688" ]]; then
	if [[ "${memory_ddr_index["vpp"]}" == "0x01" ]] && [[ $ddr1_size -eq $size_4g ]]; then
		echo "Info: max vpp size: $(printf "0x%x" $(($size_4g - $vpp_size_add - $npu_size_add))) [$(printf "%d MiB" "$(($(($size_4g - $vpp_size_add - $npu_size_add)) / $SIZE1M))")]"| tee -a $log_file_path
	else
		echo "Info: max vpp size: $(printf "0x%x" $(($size_4g - $vpp_size_add))) [$(printf "%d MiB" "$(($(($size_4g - $vpp_size_add)) / $SIZE1M))")]"| tee -a $log_file_path
	fi
fi
# 解析设备树，获取vpp和npu的ion内存空间的全局唯一索引
flag=0
bmtpu_mem_str=""
bmtpu_mem_count=0
bmtpu_mem=()
while IFS= read -r line; do
	if [[ $line =~ "bitmain,tpu-1684" ]] && [[ $runtime_info_target == "bm1684" ]];then
			flag=1
	elif [[ $line =~ "cvitek,tpu" ]] && [[ $runtime_info_target == "bm1688" ]];then
			flag=1
	fi
	if [[ $line =~ "memory-region" ]] && [[ $flag -eq 1 ]];then
		bmtpu_mem_str=$(echo "$line" | sed 's/.*<\(.*\)>;/\1/')
		bmtpu_mem_count=$(echo "$bmtpu_mem_str" | awk -F " " '{print NF}')
		bmtpu_mem=(${bmtpu_mem_str// / })
		have_bmtpu=1
		if [[ $runtime_info_target == "bm1684" ]]; then
			memory_phandle['npu']=${bmtpu_mem[3]}
			memory_phandle['vpp']=${bmtpu_mem[4]}
		elif [[ $runtime_info_target == "bm1688" ]]; then
			memory_phandle['npu']=${bmtpu_mem[0]}
			memory_phandle['vpp']=${bmtpu_mem[1]}
		fi
		flag=0
	fi
	if [[ $line =~ "bitmain,bitmain-vdec" ]];then
			have_bitmain_vdec=1
	fi
done < "$file_path"
echo "Info: bmtpu_mem_str ${bmtpu_mem_str}" >> $log_file_path
echo "Info: bmtpu_mem_count ${bmtpu_mem_count}" >> $log_file_path
echo "Info: bmtpu_mem ${bmtpu_mem[@]}" >> $log_file_path
if [[ $have_bmtpu -eq 0 ]]; then
	echo "Error: cannot find bmtpu, so cannot support this device" | tee -a $log_file_path
	exit -1
fi
if [[ $have_bitmain_vdec -eq 0 ]] && [[ $runtime_info_target == "bm1684" ]]; then
	echo "Error: cannot find bitmain_vdec, so cannot support this device" | tee -a $log_file_path
	exit -1
fi
# 配置vpu的全局索引
if [[ $runtime_info_target == "bm1684" ]]; then
	phandles=()
	while IFS= read -r line; do
		if [[ $line =~ "vpu-region" ]];then
			flag=1
		fi
		if [[ $line =~ "phandle" ]] && [[ $flag -eq 1 ]];then
			vpu_phandle_str=$(echo "$line" | sed 's/.*<\(.*\)>;/\1/')
			memory_phandle['vpu']="$vpu_phandle_str"
			have_ion_vpu_mem=1
			flag=0
		fi
		if [[ $line =~ "phandle" ]]; then
			temp_phandle=$(echo "$line" | sed 's/.*<\(.*\)>;/\1/')
			phandles+=($((temp_phandle)))
		fi
	done < "$file_path"
	phandles+=($((memory_phandle['npu'])))
	phandles+=($((memory_phandle['vpp'])))
	if [[ $have_ion_vpu_mem -eq 0 ]]; then
		echo "Info: cannot find ion_vpu_mem phandle, need creat a phandle for it" >> $log_file_path
		echo "Info: phandles ${phandles[*]}" >> $log_file_path
		sort_phandelstr=$(echo ${phandles[*]} | tr ' ' '\n' | sort -n)
		sort_phandels=()
		for i in $sort_phandelstr
		do
			sort_phandels+=($i)
		done
		echo "Info: sort_phandels ${sort_phandels[*]}" >> $log_file_path
		for ((i=1;i<${#sort_phandels[@]};i++)) do
			a=${sort_phandels[$i]}
			b=${sort_phandels[$(($i - 1))]}
			if [[ $(($a - $b)) -gt 1 ]]; then
				memory_phandle['vpu']=$(printf "0x%x" $((${sort_phandels[$(($i - 1))]} + 1)))
				echo "Info: creat a new phandle ${memory_phandle['vpu']} for vpu" >> $log_file_path
				break
			fi
			memory_phandle['vpu']=$(printf "0x%x" $((${sort_phandels[${i}]} + 1)))
		done
	fi
fi
echo "Info: memory_phandle:" >> $log_file_path
for key in "${!memory_phandle[@]}"; do
	echo "Info:	 $key : ${memory_phandle[$key]}" >> $log_file_path
done
if [[ $print_info -eq 1 ]]; then
	echo "Info: =======================================================================" | tee -a $log_file_path
	echo "Info: get now memory size ..." | tee -a $log_file_path
	for key in "${full_mem[@]}"; do
		if [[ $runtime_info_target == "bm1684" ]]; then
			sudo cat /sys/kernel/debug/ion/bm_${key}_heap_dump/total_mem &> /dev/null
			if [ "$?" == "0" ];then
				print_info_data=$(printf "0x%x" $(($(sudo cat /sys/kernel/debug/ion/bm_${key}_heap_dump/total_mem 2> /dev/null))))
			else
				print_info_data="0x0"
			fi
		elif [[ $runtime_info_target == "bm1688" ]]; then
			sudo cat /sys/kernel/debug/ion/cvi_${key}_heap_dump/total_mem &> /dev/null
			if [ "$?" == "0" ];then
				print_info_data=$(printf "0x%x" $(($(sudo cat /sys/kernel/debug/ion/cvi_${key}_heap_dump/total_mem 2> /dev/null))))
			else
				print_info_data="0x0"
			fi
		fi
		echo "Info: now ${key} size: $print_info_data [$(printf "%d MiB" "$(($print_info_data / $SIZE1M))")]" | tee -a $log_file_path
	done
	exit 0
fi
# 计算内存需要配置的大小
if [[ $radix_markers -eq 0 ]]; then
	user_mem_size["npu"]=$(printf "0x%x" $(($3)))
	user_mem_size["vpp"]=$(printf "0x%x" $(($7)))
	if [[ $runtime_info_target == "bm1684" ]]; then
		user_mem_size["vpu"]=$(printf "0x%x" $(($5)))
	fi
elif [[ $radix_markers -eq 1 ]]; then
	user_mem_size["npu"]=$(printf "0x%x" $(($3 * $size_1m)))
	user_mem_size["vpp"]=$(printf "0x%x" $(($7 * $size_1m)))
	if [[ $runtime_info_target == "bm1684" ]]; then
		user_mem_size["vpu"]=$(printf "0x%x" $(($5 * $size_1m)))
	fi
else
	echo "Error: memory size radix_markers is error: $radix_markers" | tee -a $log_file_path
	exit -1
fi
if [[ $runtime_info_target == "bm1684" ]]; then
	if [[ $((user_mem_size["vpu"])) -lt $size_1m ]]; then
		need_del_vpu=1
		vpu_mem_size_to512M_flag=0
		unset user_mem[2]
		del_mem+=("vpu")
	fi
fi
if [[ $((user_mem_size["npu"])) -lt $size_1m ]]; then
	need_del_npu=1
	unset user_mem[0]
	del_mem+=("npu")
fi
if [[ $((user_mem_size["vpp"])) -lt $size_1m ]]; then
	need_del_vpp=1
	unset user_mem[1]
	del_mem+=("vpp")
fi
# 判断内存是否足够
# NPU
if [ $((${user_mem_size["npu"]} + npu_size_add)) -gt $ddr1_size ] && [[ $runtime_info_target == "bm1684" ]]; then 
	echo "Error: npu size ${user_mem_size["npu"]} error" | tee -a $log_file_path
	exit -1
elif [ $((${user_mem_size["npu"]} + npu_size_add)) -gt $ddr_size ] && [[ $runtime_info_target == "bm1688" ]]; then
	echo "Error: npu size ${user_mem_size["npu"]} error" | tee -a $log_file_path
	exit -1
fi
# VPU
if [[ $runtime_info_target == "bm1684" ]]; then
	if [[ $((user_mem_size["vpu"])) -gt $size_1m ]]; then
		if [ $((${user_mem_size["vpu"]} + vpu_size_add)) -gt $ddr3_size ]; then 
			echo "Error: vpu size ${user_mem_size["vpu"]} error" | tee -a $log_file_path
			exit -1
		fi
	fi
fi
# VPP
if [[ $runtime_info_target == "bm1684" ]]; then
	if [[ $need_del_vpu -eq 1 ]] && [[ $need_del_vpp -eq 0 ]]; then
		echo "Warning: vpu use vpp mem, so need to reserve 1M of high address space"
		vpp_size_add=$(($vpp_size_add + $size_1m))
	fi
	if [ $((${user_mem_size["vpp"]} + vpp_size_add)) -gt $ddr4_size ]; then 
		echo "Error: vpp size ${user_mem_size["vpp"]} error" | tee -a $log_file_path
		exit -1
	fi
elif [[ $runtime_info_target == "bm1688" ]]; then
	if [ $((${user_mem_size["vpp"]} + vpp_size_add)) -gt $size_4g ]; then 
		echo "Error: vpp size ${user_mem_size["vpp"]} error" | tee -a $log_file_path
		exit -1
	fi
	if [[ $((${user_mem_size["vpp"]} + $vpp_size_add + $npu_size_add + ${user_mem_size["npu"]})) -gt $(($ddr_size)) ]]; then 
		echo "Error: vpp+npu size ${user_mem_size["vpp"]}+${user_mem_size["npu"]} error" | tee -a $log_file_path
		exit -1
	fi
fi
# 开始修改文件
cp "$file_path" "$file_path.bak"
# 编辑 ion
if [[ $runtime_info_target == "bm1684" ]]; then
	del_text "	bitmain-ion" "	}" "$file_path" >> $log_file_path
	echo "/ {
		bitmain-ion {
			compatible = \"bitmain,bitmain-ion\";
	" >> "$file_path.new"
	for key in "${user_mem[@]}"; do
			echo "
			heap_carveout@${mem_reg_index[$key]} {
				compatible = \"bitmain,carveout_${key}\";
				memory-region = <${memory_phandle[$key]}>;
			};" >> "$file_path.new"
	done
		echo "
		};
	};" >> "$file_path.new"
	cp "$file_path.new" "$file_path"
elif [[ $runtime_info_target == "bm1688" ]]; then
	del_text "	cvitek-ion" "	}" "$file_path" >> $log_file_path
	echo "/ {
	cvitek-ion {
			compatible = \"cvitek,cvitek-ion\";
	" >> "$file_path.new"
	for key in "${user_mem[@]}"; do
			echo "
			heap_carveout@${mem_reg_index[$key]} {
				compatible = \"cvitek,carveout_${key}\";
				memory-region = <${memory_phandle[$key]}>;
			};" >> "$file_path.new"
	done
		echo "
		};
	};" >> "$file_path.new"
	cp "$file_path.new" "$file_path"
fi
# 编辑 ion mem
for key in "${del_mem[@]}"; do
	del_text "		ion_${key}_mem" "		}" "$file_path" >> $log_file_path; cp "$file_path.new" "$file_path"
done
for key in "${user_mem[@]}"; do
	del_text "		ion_${key}_mem" "		}" "$file_path" >> $log_file_path; cp "$file_path.new" "$file_path"
	result=$((${memory_ddr_size[${memory_ddr_index[$key]}]} - ${user_mem_size[$key]}))
	hex_result=$(printf "0x%x" "$result")
	if [[ $key == "npu" ]]; then hex_result=$(printf "0x%x" ${npu_size_add}); fi
	# BM1684(X)的VPU最高1M空间需要预留
	if [[ $key == "vpu" ]] && [[ $runtime_info_target == "bm1684" ]]; then 
		hex_result=$(($hex_result - $size_1m)); 
	fi
	if [[ $key == "vpp" ]] && [[ $runtime_info_target == "bm1684" ]] && [[ $need_del_vpu -eq 1 ]] && [[ $need_del_vpp -eq 0 ]]; then 
		hex_result=$(($hex_result - $size_1m)); 
	fi
	ion_mem_start["$key"]=${hex_result}
	ion_mem_end["$key"]=$((${ion_mem_start["$key"]} + ${user_mem_size[$key]} - 1))
	add_ion "$file_path" "$key" "${memory_ddr_index[$key]}" "${ion_mem_start["$key"]}" "${user_mem_size[$key]}" >> $log_file_path
	cp "$file_path.new" "$file_path"
done
# 编辑 vpu_mem
if [[ $runtime_info_target == "bm1684" ]]; then
	vpu_mem_result=0
	vpu_mem_ddr_index='0x03'
	if [[ $need_del_vpu -eq 1 ]]; then
		# 如果配置了vpp则将vpu_mem放在vpp前面，否则不做修改
		if [[ $need_del_vpp -eq 0 ]]; then
			vpu_mem_result=$((${memory_ddr_size['0x04']} - ${user_mem_size['vpp']}))
			if [[ ${vpu_mem_result} -lt ${vpu_mem_size} ]]; then
				vpu_mem_result=$((${memory_ddr_size['0x03']} - ${vpu_mem_size} - $size_1m))
				vpu_mem_ddr_index='0x03'
				echo "Warning: vpu_mem and vpp are placed in different ddr because the vpp area is too large, and the vpu will not be used"
			else
				# VPU和VPP共用内存，则最高位同样需要预留1M
				vpu_mem_result=$((${memory_ddr_size['0x04']} - ${user_mem_size['vpp']} - ${vpu_mem_size} - $size_1m))
				vpu_mem_ddr_index='0x04'
			fi
		else
			vpu_mem_result=$((${memory_ddr_size['0x03']} - ${vpu_mem_size} - $size_1m))
			vpu_mem_ddr_index='0x03'
		fi
	else
		if [[ vpu_mem_size_to512M_flag -eq 1 ]]; then
			vpu_mem_result=$(("0x20000000" + "0"))
		else
			vpu_mem_result=$((${memory_ddr_size['0x03']} - ${user_mem_size['vpu']} - ${vpu_mem_size} - $size_1m))
		fi
		vpu_mem_ddr_index='0x03'
	fi
	vpu_mem_hex_result=$(printf "0x%X" "$vpu_mem_result")
	add_edit_map "$file_path" "vpu_mem" "$vpu_mem_ddr_index" "$vpu_mem_hex_result" "${vpu_mem_size}" >> $log_file_path
fi
cp "$file_path.new" "$file_path"
echo "Info: =======================================================================" | tee -a $log_file_path
echo "Info: output configuration results ..." | tee -a $log_file_path
if [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: vpu mem area(ddr$(($vpu_mem_ddr_index))): ${vpu_mem_size} [$(printf "%d MiB" "$(($vpu_mem_size / $SIZE1M))")] $(printf "0x%x" $(($vpu_mem_hex_result))) -> $(printf "0x%x" $(($vpu_mem_hex_result + $vpu_mem_size - 1)))" | tee -a $log_file_path
fi
echo "Info: ion npu mem area(ddr$((${memory_ddr_index["npu"]}))): ${user_mem_size["npu"]} [$(printf "%d MiB" "$((user_mem_size["npu"] / $SIZE1M))")] $(printf "0x%x" $((${ion_mem_start["npu"]}))) -> $(printf "0x%x" $((${ion_mem_end["npu"]})))" | tee -a $log_file_path
if [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: ion vpu mem area(ddr$((${memory_ddr_index["vpu"]}))): ${user_mem_size["vpu"]} [$(printf "%d MiB" "$((user_mem_size["vpu"] / $SIZE1M))")] $(printf "0x%x" $((${ion_mem_start["vpu"]}))) -> $(printf "0x%x" $((${ion_mem_end["vpu"]})))" | tee -a $log_file_path
fi
echo "Info: ion vpp mem area(ddr$((${memory_ddr_index["vpp"]}))): ${user_mem_size["vpp"]} [$(printf "%d MiB" "$((user_mem_size["vpp"] / $SIZE1M))")] $(printf "0x%x" $((${ion_mem_start["vpp"]}))) -> $(printf "0x%x" $((${ion_mem_end["vpp"]})))" | tee -a $log_file_path
# 校验部分
${memory_edit_PWD}/bintools/dtc -I dts -O dts -o "$file_path.check" "$file_path" $DTC_FLAGS
if [ "$?" != "0" ]; then echo "Error: ${memory_edit_PWD}/dtc" | tee -a $log_file_path; exit -1; fi
get_mem_info "$file_path.check" "ion_npu_mem" "reg =" >> $log_file_path; check_ion_npu_mem=$get_mem_info_data
if [[ $runtime_info_target == "bm1684" ]]; then
	get_mem_info "$file_path.check" "ion_vpu_mem" "reg =" >> $log_file_path; check_ion_vpu_mem=$get_mem_info_data
fi
get_mem_info "$file_path.check" "ion_vpp_mem" "reg =" >> $log_file_path; check_ion_vpp_mem=$get_mem_info_data
echo "Info: =======================================================================" | tee -a $log_file_path
echo "Info: start check memory size ..." | tee -a $log_file_path
echo "Info: check npu size: $(printf "0x%x" $(($check_ion_npu_mem))) [$(printf "%d MiB" "$((check_ion_npu_mem / $SIZE1M))")]" | tee -a $log_file_path
if [[ $runtime_info_target == "bm1684" ]]; then
	echo "Info: check vpu size: $(printf "0x%x" $(($check_ion_vpu_mem))) [$(printf "%d MiB" "$((check_ion_vpu_mem / $SIZE1M))")]" | tee -a $log_file_path
fi
echo "Info: check vpp size: $(printf "0x%x" $(($check_ion_vpp_mem))) [$(printf "%d MiB" "$((check_ion_vpp_mem / $SIZE1M))")]" | tee -a $log_file_path
if [[ $runtime_info_target == "bm1684" ]]; then
	if [[ $check_ion_npu_mem -eq ${user_mem_size['npu']} ]] && [[ $check_ion_vpp_mem -eq ${user_mem_size['vpp']} ]] && [[ $check_ion_vpu_mem -eq ${user_mem_size['vpu']} ]]; then
		echo "Info: check edit size ok" | tee -a $log_file_path
	else
		echo "Error: check edit size fail" | tee -a $log_file_path
		exit -1
	fi
elif [[ $runtime_info_target == "bm1688" ]]; then
	if [[ $check_ion_npu_mem -eq ${user_mem_size['npu']} ]] && [[ $check_ion_vpp_mem -eq ${user_mem_size['vpp']} ]]; then
		echo "Info: check edit size ok" | tee -a $log_file_path
	else
		echo "Error: check edit size fail" | tee -a $log_file_path
		exit -1
	fi
fi
en_emmcfile >> $log_file_path 2>&1
if [ "$?" != "0" ]; then echo "Error: en_emmcfile" | tee -a $log_file_path; exit -1; fi
echo -e "Info: en_emmcfile ok\nPlease reboot the device after running this command for the changes to take effect:\nsudo cp ${memory_edit_PWD}/$runtime_info_boot_file /boot/$runtime_info_boot_file && sync" | tee -a $log_file_path
cp ${memory_edit_PWD}/output/$runtime_info_boot_file ${memory_edit_PWD}/
sudo cp /boot/$runtime_info_boot_file /boot/$runtime_info_boot_file.memeditBak 2> /dev/null
sync

