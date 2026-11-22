#!/bin/bash
# 分区表（partition32G*.xml）策略与主 GPT 生成，供 socbak.sh 与 CV 系打包脚本共用。
#
# 单位约定（与 SDK 保持一致）：
#   size_in_kb      —— BM1684/BM1684X 历史格式，1 KiB = 1024 字节
#   size_in_sectors —— CV 系（BM1688/CV186AH/CV84X6）格式，1 sector = 512 字节
#                      与 CV84X6 SDK 的 scripts/partition32G_sector.xml 同构
# socbak 内部的分区配置、扩容算法、DATA 起点补偿全部仍以 KiB 计，只在写 XML 时换算。
#
# 主 GPT 生成有两种实现，由 XML 的单位决定，对外只有一个入口 socbak_gen_gpt：
#   size_in_kb      —— binTools/mk_gpt（历史行为不变，SE7 输出与此前逐字节一致）
#   size_in_sectors —— 板上 sgdisk 在稀疏文件上建表后截取主 GPT。mk_gpt 只认 KiB，
#                      无法表达奇数扇区，sector 格式必须走这条路径。

SOCBAK_PARTITION_TABLE_SOURCED=1

SOCBAK_PARTITION_FILE_KIB=partition32G.xml
SOCBAK_PARTITION_FILE_SECTOR=partition32G_sector.xml

# CV 系芯片：输出 sector 分区表。SE9 8（CV186AH）在芯片识别阶段归入 bm1688 分支，
# 这里一并列出，方便按芯片名直接判断。
socbak_is_cv_series()
{
	case "$1" in
		bm1688|cv186ah|cv84x6) return 0 ;;
		*) return 1 ;;
	esac
}

# 该芯片应该输出哪个分区表文件名
socbak_partition_file_name()
{
	if socbak_is_cv_series "$1"; then
		echo -n "${SOCBAK_PARTITION_FILE_SECTOR}"
	else
		echo -n "${SOCBAK_PARTITION_FILE_KIB}"
	fi
}

# 该芯片的分区表是否用 sector 为单位
socbak_partition_uses_sector()
{
	socbak_is_cv_series "$1"
}

# 内部 KiB 数值 -> 分区表单位的数值
# $1: KiB 值；$2: 1 表示 XML 用 sector（KiB × 2），0 表示 XML 用 KiB（原样）
socbak_size_in_unit()
{
	if [ "$2" = "1" ]; then
		echo -n "$(( $1 * 2 ))"
	else
		echo -n "$1"
	fi
}

# 当前分区表行的尺寸属性名（与属性值单位严格对应，两个名字不会同时出现）
# $1: 1 表示 sector 单位
socbak_size_attr_name()
{
	if [ "$1" = "1" ]; then
		echo -n "size_in_sectors"
	else
		echo -n "size_in_kb"
	fi
}

# ROOTFS_RW 吸收其他分区扩容/缩容的通用实现，单位由调用方决定（KiB 或扇区，
# 只要 old/new/rw/margin 四者同单位即可）。两条既有/新增模式共用这一份规则，
# 避免 200 MiB 余量在两处各写一遍后漂移。
#   $1 原“除 RW 所在分区组外”的合计（例如固定 DATA 起点模式里除 DATA 外的合计）
#   $2 新“除 RW 所在分区组外”的合计
#   $3 当前 ROOTFS_RW 大小
#   $4 扩容余量（与 $1..$3 同单位）
# 结果通过全局变量返回，不写 stdout —— 必须在调用者所在的 shell 里直接调用，
# 不能写成 X="$(...)"：命令替换是子 shell，失败差额留在子 shell 里，
# 调用方读到的是未定义变量（set -u 下直接 unbound variable），真正的原因会被掩盖。
#   成功：SOCBAK_RW_COMPENSATE_RW = 调整后的 ROOTFS_RW，返回 0
#   失败：SOCBAK_RW_COMPENSATE_DIFF = 需要的差额（含余量），返回 1
socbak_rw_compensate()
{
	local old_size="$1"
	local new_size="$2"
	local rw_size="$3"
	local margin="$4"
	local diff

	SOCBAK_RW_COMPENSATE_RW=""
	SOCBAK_RW_COMPENSATE_DIFF=0
	if [ "${old_size}" -gt "${new_size}" ]; then
		rw_size=$(( rw_size + (old_size - new_size) ))
	elif [ "${old_size}" -lt "${new_size}" ]; then
		diff=$(( new_size - old_size + margin ))
		if [ "${rw_size}" -lt "${diff}" ]; then
			SOCBAK_RW_COMPENSATE_DIFF=${diff}
			return 1
		fi
		rw_size=$(( rw_size - (new_size - old_size) ))
	fi
	SOCBAK_RW_COMPENSATE_RW=${rw_size}
	return 0
}

# SOC_BAK_FIXED_DATA_START：用 ROOTFS_RW 吸收其他分区的扩容/缩容，使最后一个分区
# （DATA）的起始扇区保持不变，OTA 才能在升级时保留 DATA。
#   $1 配置侧“除 DATA 外”的分区合计（KiB）
#   $2 本次打包实际“除 DATA 外”的分区合计（KiB）
#   $3 当前 ROOTFS_RW 大小（KiB）
#   成功：SOCBAK_FIXED_DATA_START_RW_KB = 调整后的 ROOTFS_RW（KiB），返回 0
#   失败：SOCBAK_FIXED_DATA_START_DIFF_KB = 需要的差额（KiB），返回 1
# 与历史实现逐字对应：扩容方向直接把差额还给 ROOTFS_RW；缩容方向要求 ROOTFS_RW 至少比差额
# 多出 200 MiB 余量（RW_BUFFER_SIZE = 200 * 1024 KiB），否则判定打包失败。
socbak_fixed_data_start_rw()
{
	local diff_kb

	SOCBAK_FIXED_DATA_START_RW_KB=""
	SOCBAK_FIXED_DATA_START_DIFF_KB=0
	if ! socbak_rw_compensate "$1" "$2" "$3" $(( 200 * 1024 )); then
		diff_kb=${SOCBAK_RW_COMPENSATE_DIFF}
		SOCBAK_FIXED_DATA_START_DIFF_KB=${diff_kb}
		return 1
	fi
	SOCBAK_FIXED_DATA_START_RW_KB=${SOCBAK_RW_COMPENSATE_RW}
	return 0
}
# ==================== SOC_BAK_LOCAL_UPDATE_LAYOUT（SE9/SE13 local_update） ====================
# SDK 的 local_update 把升级指令写进 MISC(p3) 交给 recovery，写盘前用
# scripts/check_partition_start_sector.sh 逐项比较源机与包内 partition32G_sector.xml 的
# DATA、MISC、ROOTFS 起点，任何一项不同就拒绝升级。所以打包源机上的 GPT 前缀必须原样
# 复制到新包：BOOT/RECOVERY/MISC 的起点与长度、ROOTFS 起点、DATA 起点全部冻结，
# 只允许 ROOTFS 长度、ROOTFS_RW 起点、ROOTFS_RW 长度、DATA 长度这四个数值随内容变化。
# 本节只做「只读读取源表」与「按内容算出新几何」两件事，不碰设备、不写任何文件。

SOCBAK_LU_PART_ORDER=(BOOT RECOVERY MISC ROOTFS ROOTFS_RW DATA)
# 首分区固定 LBA（与 SDK 的 PARTITION_TABLE_OFFSET / BOOT_PART_OFFSET 一致）
SOCBAK_LU_FIRST_LBA=8192
# 末分区之后必须留给备份 GPT 的扇区数（= SDK mk_sector_gpt 的 last_usable_lba = total-34）
SOCBAK_LU_BACKUP_GPT_SECTORS=34
# ROOTFS 增长时 ROOTFS_RW 必须保留的余量，与 SOC_BAK_FIXED_DATA_START 的 200 MiB 同源
SOCBAK_LU_RW_MARGIN_SECTORS=$(( 200 * 1024 * 2 ))

# 只读抓取 sgdisk -p 的表头与分区行，并确认这是一块**已有 GPT** 的盘。
# sgdisk -p 遇到没有 GPT 的文件不会报错，而是打印 "Creating new GPT entries in memory."
# 并给出一个空表 + 按文件大小折算的盘容量；那会把任意普通文件当成合法源表，必须显式拒绝。
# 输出：第 1 行是总扇区数，其余是分区行（Number Start End）。
# $1 设备/镜像路径
socbak_local_update_read_table()
{
	local dev="$1" _sgdisk out

	_sgdisk="$(socbak_sgdisk_bin)" || return 1
	out="$(LC_ALL=C "${_sgdisk}" -p "${dev}" 2>&1)" || {
		echo "ERROR: cannot read the partition table of ${dev} with sgdisk" >&2
		return 1
	}
	if printf '%s\n' "${out}" | grep -q 'Creating new GPT entries in memory'; then
		echo "ERROR: ${dev} has no GPT partition table (sgdisk would create a new one)" >&2
		return 1
	fi
	if ! printf '%s\n' "${out}" | grep -q '^Number  Start'; then
		echo "ERROR: ${dev} has no GPT partition table" >&2
		return 1
	fi
	# "Disk /dev/mmcblk0: 61071360 sectors, 29.1 GiB" -> 61071360。
	# 只认表头里的 "<N> sectors"，不按固定列取（不同 sgdisk 版本的空白与列数不同）；
	# 字段上可能带逗号（"sectors,"），去掉非数字再比。
	printf '%s\n' "${out}" | awk '/^Disk / {
		for (i = 1; i <= NF; i++) {
			f = $i; gsub(/[^a-z]/, "", f)
			if (f == "sectors") { n = $(i - 1); gsub(/[^0-9]/, "", n); print n; exit } } }'
	printf '%s\n' "${out}" |
		awk '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {print $1, $2, $3}'
}

# 只读读取磁盘的 GPT 分区表：分区号、标签、起点、长度（单位 512 B 扇区）。
# 输出每行 "LABEL|PARTNO|START|LEN"，按分区号升序；标签为空时写 "-"。
# 只读：sgdisk -p / -i 都不改写设备内容（块设备与镜像文件同理，已实测镜像 md5 不变）。
# $1 设备/镜像路径
socbak_read_disk_layout()
{
	local dev="$1" _sgdisk table num start end label

	_sgdisk="$(socbak_sgdisk_bin)" || return 1
	# 先取表再逐行读标签：不能用管道把 read_table 的输出交给 sed，
	# 管道会吞掉 read_table 的失败退出码，"没有 GPT" 就会被当成"零个分区"。
	table="$(socbak_local_update_read_table "${dev}")" || return 1
	# Size 列可能是 "512 bytes" / "80.0 KiB" / "17.0 GiB"，按列数取标签会错位，
	# 所以标签一律用 sgdisk -i 单独读（单引号包裹，允许标签含空格）。
	while read -r num start end; do
		[ -n "${num}" ] || continue
		label="$(LC_ALL=C "${_sgdisk}" -i "${num}" "${dev}" 2>/dev/null |
			awk -F"'" '/^Partition name:/ {print $2; exit}')"
		printf '%s|%s|%s|%s\n' "${label:--}" "${num}" "${start}" "$(( end - start + 1 ))"
	done <<< "$(printf '%s\n' "${table}" | sed '1d')"
}

# 只读读取磁盘的总扇区数（来自 GPT 表头）。
# $1 设备/镜像路径
socbak_read_disk_total_sectors()
{
	local table

	table="$(socbak_local_update_read_table "$1")" || return 1
	printf '%s\n' "${table}" | sed -n '1p'
}

# 校验源布局文件本身（形状、标签顺序、首尾相接、冻结区为整 KiB），不涉及本次内容。
# 供 socbak.sh 在备份开始前先跑一遍：布局不对就没必要再备份几个 GB。
#   $1 源布局文件（socbak_read_disk_layout 的输出）
# 成功返回 0，并把冻结区尺寸（KiB）写进全局：
#   SOCBAK_LU_SRC_BOOT_KB / SOCBAK_LU_SRC_RECOVERY_KB / SOCBAK_LU_SRC_MISC_KB
#   SOCBAK_LU_SRC_ROOTFS_START / SOCBAK_LU_SRC_ROOTFS_LEN / SOCBAK_LU_SRC_DATA_START
socbak_local_update_check_source()
{
	local layout="$1"
	local -a labels=() starts=() lens=()
	local label num start len i c

	SOCBAK_LU_SRC_BOOT_KB=""
	SOCBAK_LU_SRC_RECOVERY_KB=""
	SOCBAK_LU_SRC_MISC_KB=""
	SOCBAK_LU_SRC_ROOTFS_START=""
	SOCBAK_LU_SRC_ROOTFS_LEN=""
	SOCBAK_LU_SRC_DATA_START=""

	[ -f "${layout}" ] || { echo "ERROR: source layout file ${layout} not found" >&2; return 1; }
	while IFS='|' read -r label num start len; do
		[ -n "${num}" ] || continue
		labels+=("${label}")
		starts+=("${start}")
		lens+=("${len}")
	done < "${layout}"

	# 用标签与分区号双重辨认：数量、顺序、标签任一不符都说明这不是该 SDK 的布局
	if [ "${#labels[@]}" -ne "${#SOCBAK_LU_PART_ORDER[@]}" ]; then
		echo "ERROR: ${layout}: expected the ${#SOCBAK_LU_PART_ORDER[@]}-partition local_update layout (${SOCBAK_LU_PART_ORDER[*]}), found ${#labels[@]}: ${labels[*]}" >&2
		return 1
	fi
	for i in "${!SOCBAK_LU_PART_ORDER[@]}"; do
		if [ "${labels[$i]}" != "${SOCBAK_LU_PART_ORDER[$i]}" ]; then
			echo "ERROR: ${layout}: partition $(( i + 1 )) is \"${labels[$i]}\", expected \"${SOCBAK_LU_PART_ORDER[$i]}\"" >&2
			return 1
		fi
	done
	for i in "${!labels[@]}"; do
		for c in "${starts[$i]}" "${lens[$i]}"; do
			[[ "${c}" =~ ^[0-9]+$ ]] || {
				echo "ERROR: ${layout}: invalid geometry for ${labels[$i]}: \"${c}\"" >&2
				return 1; }
		done
		[ "${lens[$i]}" -gt 0 ] || {
			echo "ERROR: ${layout}: partition ${labels[$i]} has zero length" >&2
			return 1; }
	done

	# 源表必须从 LBA 8192 起首尾相接：打包链按 XML 行序连续落位，
	# 源表有空洞时无法只靠 XML 复现已冻结的起点，属于「无法精确表达」。
	if [ "${starts[0]}" -ne "${SOCBAK_LU_FIRST_LBA}" ]; then
		echo "ERROR: ${layout}: BOOT starts at LBA ${starts[0]}, expected ${SOCBAK_LU_FIRST_LBA}" >&2
		return 1
	fi
	for i in $(seq 1 $(( ${#labels[@]} - 1 ))); do
		if [ "${starts[$i]}" -ne $(( starts[i - 1] + lens[i - 1] )) ]; then
			echo "ERROR: ${layout}: ${labels[$i]} starts at LBA ${starts[$i]}, but ${labels[$i - 1]} ends at LBA $(( starts[i - 1] + lens[i - 1] - 1 )); a non-contiguous source layout cannot be reproduced from the partition table" >&2
			return 1
		fi
	done

	# 冻结区必须能用整 KiB 表达（socbak 内部以 KiB 计）：
	# 不能悄悄取整，否则冻结项的起点会平移，local_update 的起点检查随即失败。
	for i in 0 1 2; do
		if [ $(( lens[i] % 2 )) -ne 0 ]; then
			echo "ERROR: ${layout}: fixed prefix partition ${labels[$i]} length ${lens[$i]} sectors is odd; socbak stores sizes in KiB and cannot express it exactly" >&2
			return 1
		fi
		if [ $(( starts[i] % 2 )) -ne 0 ]; then
			echo "ERROR: ${layout}: fixed prefix partition ${labels[$i]} starts at odd LBA ${starts[$i]}; socbak stores sizes in KiB and cannot express it exactly" >&2
			return 1
		fi
	done
	# ROOTFS 起点同样被冻结（SDK 的 check_partition_start_sector.sh 直接比较它）
	if [ $(( starts[3] % 2 )) -ne 0 ] || [ $(( starts[5] % 2 )) -ne 0 ]; then
		echo "ERROR: ${layout}: ROOTFS start ${starts[3]} / DATA start ${starts[5]} must be even LBAs; socbak stores sizes in KiB and cannot express odd offsets" >&2
		return 1
	fi

	SOCBAK_LU_SRC_BOOT_KB=$(( lens[0] / 2 ))
	SOCBAK_LU_SRC_RECOVERY_KB=$(( lens[1] / 2 ))
	SOCBAK_LU_SRC_MISC_KB=$(( lens[2] / 2 ))
	SOCBAK_LU_SRC_ROOTFS_START=${starts[3]}
	SOCBAK_LU_SRC_ROOTFS_LEN=${lens[3]}
	SOCBAK_LU_SRC_DATA_START=${starts[5]}
	# 源表原样的几何，规划时除四个自由度外逐项照抄
	SOCBAK_LU_SRC_ROWS=()
	for i in "${!labels[@]}"; do
		SOCBAK_LU_SRC_ROWS+=("${labels[$i]}|${starts[$i]}|${lens[$i]}")
	done
	return 0
}

# 规划 local_update 布局：源表逐项冻结，只按内容改四个数值。
#   $1 源布局文件（socbak_read_disk_layout 的输出）
#   $2 源盘总扇区数
#   $3 新 ROOTFS 长度（扇区）
#   $4 新 DATA 长度（扇区）
#   $5 打包策略给出的总容量（扇区）；DATA 装不下时抬高，上限是源盘
# 结果（全局，单位一律 512 B 扇区）：
#   SOCBAK_LU_ROWS   每行 "LABEL|START|LEN"，顺序 BOOT..DATA，冻结项与源表逐项相同
#   SOCBAK_LU_TOTAL  分区表总容量（偶数扇区）
# 失败：原因写 stderr，返回 1，且不留下 SOCBAK_LU_ROWS / SOCBAK_LU_TOTAL。
#
# 源表本身的形状由 socbak_local_update_check_source 把关（标签顺序、首尾相接、偶数 LBA）；
# 这里只负责「按内容算新几何」和「容量是否装得下」。
socbak_local_update_plan()
{
	local layout="$1"
	local disk_sectors="$2"
	local rootfs_len="$3"
	local data_len="$4"
	local strategy_total="$5"
	local label len needed total rw_len pair
	local r_start r_len_old rw_len_old d_start

	SOCBAK_LU_ROWS=()
	SOCBAK_LU_TOTAL=""

	socbak_local_update_check_source "${layout}" || return 1

	[ -n "${disk_sectors}" ] || { echo "ERROR: source disk sector count is empty" >&2; return 1; }
	[[ "${disk_sectors}" =~ ^[0-9]+$ ]] || {
		echo "ERROR: invalid source disk sector count \"${disk_sectors}\"" >&2; return 1; }

	r_start=${SOCBAK_LU_SRC_ROOTFS_START}
	r_len_old=${SOCBAK_LU_SRC_ROOTFS_LEN}
	d_start=${SOCBAK_LU_SRC_DATA_START}
	rw_len_old=$(( d_start - r_start - r_len_old ))

	# 随内容变化的两个长度也必须能用整 KiB 表达（同样是为了不取整）
	for pair in "ROOTFS:${rootfs_len}" "DATA:${data_len}"; do
		label="${pair%%:*}"
		len="${pair##*:}"
		if ! [[ "${len}" =~ ^[0-9]+$ ]] || [ "${len}" -le 0 ]; then
			echo "ERROR: local_update layout: invalid new ${label} length \"${len}\"" >&2
			return 1
		fi
		if [ $(( len % 2 )) -ne 0 ]; then
			echo "ERROR: local_update layout: new ${label} length ${len} sectors is odd; socbak stores sizes in KiB and cannot express it exactly" >&2
			return 1
		fi
	done

	# ROOTFS 起点冻结、长度随内容；ROOTFS_RW 起点 = R + 新 ROOTFS 长度，
	# 长度 = 原 DATA 起点 - 新 ROOTFS_RW 起点（ROOTFS 增长时保留 200 MiB 余量）。
	# 复用与 SOC_BAK_FIXED_DATA_START 同一个补偿函数，只把单位换成扇区，规则只有一份。
	if ! socbak_rw_compensate "${d_start}" $(( d_start + rootfs_len - r_len_old )) \
		"${rw_len_old}" "${SOCBAK_LU_RW_MARGIN_SECTORS}"; then
		echo "ERROR: local_update layout: ROOTFS grows from ${r_len_old} to ${rootfs_len} sectors, ROOTFS_RW (${rw_len_old} sectors) cannot absorb that and keep the $(( SOCBAK_LU_RW_MARGIN_SECTORS / 2048 )) MiB margin (needs ${SOCBAK_RW_COMPENSATE_DIFF} sectors)" >&2
		return 1
	fi
	rw_len=${SOCBAK_RW_COMPENSATE_RW}
	if [ "${rw_len}" -ne $(( d_start - r_start - rootfs_len )) ]; then
		echo "ERROR: local_update layout: ROOTFS_RW length ${rw_len} != DATA start ${d_start} - ROOTFS end $(( r_start + rootfs_len )); the result is not self-consistent" >&2
		return 1
	fi
	if [ $(( rw_len % 2 )) -ne 0 ]; then
		echo "ERROR: local_update layout: derived ROOTFS_RW length ${rw_len} sectors is odd; socbak stores sizes in KiB and cannot express it exactly" >&2
		return 1
	fi

	# 容量：沿用原打包策略给出的总容量，只在 DATA 需要更多空间时抬到刚好够用；
	# 上限是源盘自身（超过就越过源机备份 GPT 的位置，刷上去必坏表）。
	needed=$(( d_start + data_len + SOCBAK_LU_BACKUP_GPT_SECTORS ))
	[[ "${strategy_total}" =~ ^[0-9]+$ ]] || {
		echo "ERROR: local_update layout: invalid strategy total \"${strategy_total}\"" >&2
		return 1; }
	total=${strategy_total}
	if [ "${total}" -lt "${needed}" ]; then
		total=${needed}
	fi
	if [ "${total}" -gt "${disk_sectors}" ]; then
		echo "ERROR: local_update layout: DATA (start ${d_start}, length ${data_len}) needs the partition table to be ${total} sectors, but the source disk has only ${disk_sectors} sectors; the data does not fit" >&2
		return 1
	fi
	# 总容量按 2 扇区（1 KiB）对齐，保证写进 XML 的总容量与内部 KiB 值一一对应
	if [ $(( total % 2 )) -ne 0 ]; then
		total=$(( total + 1 ))
	fi

	SOCBAK_LU_ROWS=(
		"${SOCBAK_LU_SRC_ROWS[0]}"
		"${SOCBAK_LU_SRC_ROWS[1]}"
		"${SOCBAK_LU_SRC_ROWS[2]}"
		"ROOTFS|${r_start}|${rootfs_len}"
		"ROOTFS_RW|$(( r_start + rootfs_len ))|${rw_len}"
		"DATA|${d_start}|${data_len}"
	)
	SOCBAK_LU_TOTAL=${total}
	return 0
}

# 把一份分区表 XML 换算成 "LABEL|START|LEN" 几何（起点从 LBA 8192 连续累加）。
# 供写盘后与最终 gpt.gz 解码结果交叉验证：包内 XML 与 GPT 不能各说各话。
# $1 分区表 XML
socbak_xml_geometry()
{
	local xml="$1" label size ro fmt lba=8192

	socbak_xml_partition_rows "${xml}" | while IFS='|' read -r label size ro fmt; do
		[ -n "${label}" ] || continue
		printf '%s|%s|%s\n' "${label}" "${lba}" "${size}"
		lba=$(( lba + size ))
	done
}

# 从主 GPT 文件解码 "LABEL|START|LEN" 几何（只读分区项数组，不重算落位）。
# 与 socbak_gen_gpt_sector 的落位规则无关地重算，才能作为独立对照。
#
# 用 `od -An -tx1 -v` 十六进制逐字节读出后在 awk 里拼小端整数：
#   - 板上只有 busybox 的 od，它不支持 -tu8 也不支持 --endian；
#   - 目标机没有 iconv（busybox 未内置），标签只能按 UTF-16LE 自己解。
# 这样同一份代码在 x86 回归主机与板上都跑得动，不依赖 GNU coreutils。
# $1 主 GPT 文件（17408 字节，LBA 0..33）
socbak_gpt_geometry()
{
	local gpt="$1" sig

	[ -s "${gpt}" ] || { echo "ERROR: gpt file ${gpt} is empty" >&2; return 1; }
	sig=$(od -An -tx1 -j 512 -N 8 -v "${gpt}" | tr -d ' \n')
	[ "${sig}" = "4546492050415254" ] || {
		echo "ERROR: ${gpt}: no valid GPT header signature" >&2
		return 1; }

	od -An -tx1 -v "${gpt}" | awk '
		function le(off, n,    v, k) {
			v = 0
			for (k = 0; k < n; k++) v += b[off + k] * (2 ^ (8 * k))
			return v
		}
		function name(off,    k, lo, hi, s, ch) {
			s = ""
			for (k = 0; k < 36; k++) {
				lo = b[off + k * 2]; hi = b[off + k * 2 + 1]
				if (lo == 0 && hi == 0) break
				# 标签是 UTF-16LE；本地化标签里的非 ASCII 字符用 ? 代替，不影响几何比对
				ch = (hi == 0 && lo >= 32 && lo < 127) ? sprintf("%c", lo) : "?"
				s = s ch
			}
			return s
		}
		{ for (i = 1; i <= NF; i++) b[n++] = strtonum("0x" $i) }
		END {
			if (n < 17408) { print "ERROR: short gpt" > "/dev/stderr"; exit 1 }
			num = le(512 + 80, 4)
			esz = le(512 + 84, 4)
			if (esz <= 0) esz = 128
			base = 1024
			for (i = 0; i < num; i++) {
				off = base + i * esz
				start = le(off + 32, 8)
				end = le(off + 40, 8)
				if (start == 0 && end == 0) continue
				nm = name(off + 56)
				if (nm == "") nm = "-"
				printf "%s|%.0f|%.0f\n", nm, start, end - start + 1
			}
		}
	'
}

# 从主 GPT 文件读分区表总容量（扇区数）：主头里的 AlternateLBA + 1。
# $1 主 GPT 文件
socbak_gpt_total_sectors()
{
	od -An -tx1 -j $(( 512 + 32 )) -N 8 -v "$1" | awk '
		{ for (i = 1; i <= NF; i++) b[n++] = strtonum("0x" $i) }
		END { v = 0; for (k = 0; k < n; k++) v += b[k] * (2 ^ (8 * k)); printf "%.0f\n", v + 1 }
	'
}

# 逐项比较两份几何（"LABEL|START|LEN"）。不同则打印差异并返回 1。
# 用于「计划 vs XML」与「计划 vs gpt.gz」两处交叉验证。
#   $1 期望几何文件
#   $2 实际几何文件
#   $3 说明（出现在报错里）
socbak_local_update_match()
{
	local want="$1" got="$2" what="$3"

	if ! diff -u <(sed '/^$/d' "${want}") <(sed '/^$/d' "${got}") >/dev/null 2>&1; then
		echo "ERROR: ${what} does not match the planned local_update layout:" >&2
		diff -u <(sed '/^$/d' "${want}") <(sed '/^$/d' "${got}") >&2
		return 1
	fi
	return 0
}

# checksum 与 socbak.sh 里 SOC_BAK_LOCAL_UPDATE_LAYOUT 的固定区判定共用这一份定义：
# 固定区 = 起点与长度都来自源机 GPT 的分区（BOOT 与 RECOVERY 有内容镜像，MISC 没有）。
# 这些分区的镜像必须正好是源机容量，不能因 shrink 搜索或余量被放大/缩小。
# $1 分区名（小写，与 TGZ_FILES 一致）
socbak_lu_is_frozen_part()
{
	case "$1" in
		boot|recovery) return 0 ;;
		*) return 1 ;;
	esac
}

# 核对一份**将要交付的刷机包**的分区表是否满足 local_update 的冻结要求：
# BOOT/RECOVERY/MISC 的起点与长度、ROOTFS 起点、DATA 起点必须与源机逐项相等，
# 只允许 ROOTFS 长度、ROOTFS_RW 起点/长度、DATA 长度这四个数值与源机不同。
# 这是 SDK check_partition_start_sector.sh 的本地等价物，但更严：SDK 只比三个起点，
# 这里连冻结区的长度一起比，才能挡住「MISC 挪了位置但 DATA 起点没动」这种包
# （旧版 socbak 的固定 DATA 起点模式就产出过这种包，DATA 起点对得上却无法 local_update）。
#   $1 待检查的分区表 XML
#   $2 源布局文件（socbak_read_disk_layout 的输出）
# 通过返回 0；否则打印每一项的差异并返回 1。
socbak_local_update_verify_xml()
{
	local xml="$1"
	local layout="$2"
	local -a want_label=() want_start=() want_len=() got_label=() got_start=() got_len=()
	local label num start len lba=8192 i rc=0

	[ -f "${xml}" ] || { echo "ERROR: partition xml ${xml} not found" >&2; return 1; }
	[ -f "${layout}" ] || { echo "ERROR: source layout ${layout} not found" >&2; return 1; }

	while IFS='|' read -r label num start len; do
		[ -n "${num}" ] || continue
		want_label+=("${label}")
		want_start+=("${start}")
		want_len+=("${len}")
	done < "${layout}"
	while IFS='|' read -r label len _rest; do
		[ -n "${label}" ] || continue
		got_label+=("${label}")
		got_start+=("${lba}")
		got_len+=("${len}")
		lba=$(( lba + len ))
	done <<< "$(socbak_xml_partition_rows "${xml}" | awk -F'|' '{printf "%s|%s\n", $1, $2}')"

	if [ "${#got_label[@]}" -ne "${#want_label[@]}" ]; then
		echo "ERROR: ${xml}: has ${#got_label[@]} partition(s), the source layout has ${#want_label[@]}" >&2
		return 1
	fi
	for i in "${!want_label[@]}"; do
		if [ "${got_label[$i]}" != "${want_label[$i]}" ]; then
			echo "ERROR: ${xml}: partition $(( i + 1 )) is ${got_label[$i]}, expected ${want_label[$i]}" >&2
			rc=1
			continue
		fi
		# 冻结项：起点与长度都必须与源机相同。
		# 逐项列出（而不是只断言"三个起点"或"非 DATA 分区总量"）：漏掉任何一项，
		# 刷进去之后 u-boot 按 XML 写的边界与设备实际分区边界就会对不上。
		case "${want_label[$i]}" in
			BOOT|RECOVERY|MISC)
				if [ "${got_start[$i]}" -ne "${want_start[$i]}" ] || [ "${got_len[$i]}" -ne "${want_len[$i]}" ]; then
					echo "ERROR: ${xml}: ${want_label[$i]} is [start=${got_start[$i]} len=${got_len[$i]}], source device has [start=${want_start[$i]} len=${want_len[$i]}]" >&2
					rc=1
				fi
				;;
			ROOTFS)
				# 起点冻结、长度随内容。前缀三项已核对过，起点理论上已被隐含确定；
				# 这里仍显式比一次，是为了在"前缀长度恰好互相抵消"的输入上给出
				# 直接指向 ROOTFS 的报错（而不是让读者自己去推是哪一项把起点顶偏了）。
				if [ "${got_start[$i]}" -ne "${want_start[$i]}" ]; then
					echo "ERROR: ${xml}: ROOTFS starts at ${got_start[$i]}, source device has ${want_start[$i]}" >&2
					rc=1
				fi
				;;
			ROOTFS_RW)
				# 起点必须紧接新 ROOTFS 末尾（= 四个自由度里的"RW 起点"），
				# 长度必须正好填到 DATA 起点（= "RW 长度"）。两者都由前一项与 DATA 起点推出，
				# 所以改坏任何一项都会同时被这里和 DATA 起点检查抓到；留两份报错是为了
				# 让人一眼看出是"RW 没跟着缩"还是"DATA 被挪了"。
				if [ "${got_start[$i]}" -ne $(( got_start[i - 1] + got_len[i - 1] )) ]; then
					echo "ERROR: ${xml}: ROOTFS_RW starts at ${got_start[$i]}, expected $(( got_start[i - 1] + got_len[i - 1] )) (= ROOTFS end)" >&2
					rc=1
				fi
				if [ "${got_len[$i]}" -ne $(( want_start[i + 1] - got_start[i] )) ]; then
					echo "ERROR: ${xml}: ROOTFS_RW is ${got_len[$i]} sectors, expected $(( want_start[i + 1] - got_start[i] )) to reach DATA start ${want_start[i + 1]}" >&2
					rc=1
				fi
				;;
			DATA)
				if [ "${got_start[$i]}" -ne "${want_start[$i]}" ]; then
					echo "ERROR: ${xml}: DATA starts at ${got_start[$i]}, source device has ${want_start[$i]}" >&2
					rc=1
				fi
				;;
		esac
	done
	return "${rc}"
}

# 按 SDK check_partition_start_sector.sh 的口径逐项核对三个起点（DATA/MISC/ROOTFS），
# 并把源机与包的实值都打印出来 —— 交付证据直接用它，不依赖板上 fdisk。
#   $1 待检查的分区表 XML
#   $2 源布局文件
# 三项全等返回 0，否则打印不匹配项并返回 1。
socbak_local_update_check_starts()
{
	local xml="$1"
	local layout="$2"
	local label cur new rc=0

	for label in DATA MISC ROOTFS; do
		cur="$(awk -F'|' -v l="${label}" '$1==l{print $3; exit}' "${layout}")"
		new="$(socbak_xml_geometry "${xml}" | awk -F'|' -v l="${label}" '$1==l{print $2; exit}')"
		printf '%s: source=%s package=%s' "${label}" "${cur:-?}" "${new:-?}"
		if [ -n "${cur}" ] && [ "${cur}" = "${new}" ]; then
			printf ' OK\n'
		else
			printf ' MISMATCH\n'
			rc=1
		fi
	done
	return "${rc}"
}

# 写分区表 XML —— socbak.sh 里唯一的写分区表入口。
#   $1 输出文件
#   $2 1 表示 sector 单位（size_in_sectors），0 表示 KiB 单位（size_in_kb）
#   $3 总容量（KiB）
#   其余参数：分区行，每行 "LABEL|size_kib|readonly|format"，顺序即 XML 里的分区顺序
#
# 每行模板抄自本次改动前的 socbak.sh（含各列间距），只把尺寸属性名与数值参数化，
# 因此 KiB 单位下产出与旧版本逐字节相同（SE7 的全部产物保持一致）；
# sector 单位只把 size_in_kb 换成 size_in_sectors、数值 KiB×2。
# 属性顺序与 SDK 的 partition32G_sector.xml 一致：label、尺寸、readonly、format。
socbak_emit_partition_xml()
{
	local out="$1"
	local uses_sector="$2"
	local total_kib="$3"
	shift 3
	local attr row label size_kib ro fmt sz

	# 属性名统一由 socbak_size_attr_name 决定：写盘与解析共用同一份单位名逻辑，
	# 避免两处 if/else 各自维护后漂移（测试也只验证这一处）。
	attr="$(socbak_size_attr_name "${uses_sector}")"

	echo "<physical_partition ${attr}=\"$(socbak_size_in_unit "${total_kib}" "${uses_sector}")\">" > "${out}"
	for row in "$@"; do
		IFS='|' read -r label size_kib ro fmt <<< "${row}"
		[ -n "${label}" ] || continue
		sz="$(socbak_size_in_unit "${size_kib}" "${uses_sector}")"
		case "${label}" in
			BOOT)
				echo "  <partition label=\"BOOT\"       ${attr}=\"${sz}\"  readonly=\"${ro}\"  format=\"${fmt}\" />" >> "${out}"
				;;
			RECOVERY)
				echo "  <partition label=\"RECOVERY\"   ${attr}=\"${sz}\"  readonly=\"${ro}\" format=\"${fmt}\" />" >> "${out}"
				;;
			MISC)
				echo "  <partition label=\"MISC\"       ${attr}=\"${sz}\"  readonly=\"${ro}\"   format=\"${fmt}\" />" >> "${out}"
				;;
			ROOTFS)
				echo "  <partition label=\"ROOTFS\"     ${attr}=\"${sz}\" readonly=\"${ro}\"   format=\"${fmt}\" />" >> "${out}"
				;;
			ROOTFS_RW)
				echo "  <partition label=\"ROOTFS_RW\"  ${attr}=\"${sz}\" readonly=\"${ro}\"  format=\"${fmt}\" />" >> "${out}"
				;;
			OPT)
				echo "  <partition label=\"OPT\"       ${attr}=\"${sz}\" readonly=\"${ro}\"  format=\"${fmt}\" />" >> "${out}"
				;;
			SYSTEM)
				echo "  <partition label=\"SYSTEM\"     ${attr}=\"${sz}\" readonly=\"${ro}\"  format=\"${fmt}\" />" >> "${out}"
				;;
			DATA)
				echo "  <partition label=\"DATA\"       ${attr}=\"${sz}\" readonly=\"${ro}\"  format=\"${fmt}\" />" >> "${out}"
				;;
			*)
				echo "  <partition label=\"${label}\"  ${attr}=\"${sz}\"  readonly=\"${ro}\"   format=\"${fmt}\" />" >> "${out}"
				;;
		esac
	done
	echo "</physical_partition>" >> "${out}"
}

# SDK 的分区表是扁平的元素列表。按开始标签分记录，允许属性之间换行或用制表符。
# 截断到标签真正的结尾时必须跳过引号内的 ">"：XML 允许属性值含 ">"，
# 直接 sub(/>.*/, ">") 会把 label="A>B" 截成 label="A，属性一起丢掉。
socbak_xml_tags()
{
	awk -v tag="$2" '
		BEGIN { RS = "<" }
		/^!--/ { comment = 1 }
		comment { if (index($0, "-->")) comment = 0; next }
		$0 ~ ("^" tag "([[:space:]]|/?>)") {
			gsub(/[\r\n]/, " ")
			out = ""
			quote = ""
			for (i = 1; i <= length($0); i++) {
				ch = substr($0, i, 1)
				if (quote != "") {
					if (ch == quote) quote = ""
				} else if (ch == "\"" || ch == "\047") {
					quote = ch
				} else if (ch == ">") {
					out = out ch
					break
				}
				out = out ch
			}
			print out
		}
	' "$1"
}

socbak_xml_attr()
{
	local prefix="[[:space:]]$2[[:space:]]*=[[:space:]]*"
	if [[ $1 =~ ${prefix}\"([^\"]*)\" || $1 =~ ${prefix}\'([^\']*)\' ]]; then
		printf '%s' "${BASH_REMATCH[1]}"
	fi
}

socbak_xml_header()
{
	local root kib sectors unit total
	root="$(socbak_xml_tags "$1" physical_partition)" || return 1
	kib="$(socbak_xml_attr "${root}" size_in_kb)"
	sectors="$(socbak_xml_attr "${root}" size_in_sectors)"
	if [[ -n ${kib} && -z ${sectors} ]]; then
		unit=size_in_kb
		total=${kib}
	elif [[ -n ${sectors} && -z ${kib} ]]; then
		unit=size_in_sectors
		total=${sectors}
	else
		echo "ERROR: $1: expected one size attribute on <physical_partition>" >&2
		return 1
	fi
	if [[ ! ${total} =~ ^0*([1-9][0-9]*)$ ]]; then
		echo "ERROR: $1: invalid disk size \"${total}\"" >&2
		return 1
	fi
	total=${BASH_REMATCH[1]}
	if [[ $2 == unit ]]; then
		printf '%s' "${unit}"
	else
		printf '%s' "${total}"
	fi
}

socbak_xml_unit_attr() { socbak_xml_header "$1" unit; }
socbak_xml_total() { socbak_xml_header "$1" total; }

# 从 XML 取分区记录，行序即分区序。每次调用重新解析整个文件，
# GPT 生成与刷写布局都消费这同一组记录，两者不会因为解析方式不同而错位。
# 输出每行：label|size|readonly|format
#   size 为该 XML 自身单位下的数值
#   readonly 缺省 false、format 缺省 0（与 SDK 的 mk_sector_gpt 一致：属性缺失取 0）
# $1: XML 路径
socbak_xml_partition_rows()
{
	local xml="$1"
	local unit_attr tags line label size ro fmt
	unit_attr="$(socbak_xml_unit_attr "${xml}")" || return 1
	tags="$(socbak_xml_tags "${xml}" partition)" || return 1
	if [[ -z ${tags} ]]; then
		echo "ERROR: ${xml}: no partition found" >&2
		return 1
	fi

	while IFS= read -r line; do
		label="$(socbak_xml_attr "${line}" label)"
		if [[ -z ${label} ]]; then
			echo "ERROR: ${xml}: partition has no label" >&2
			return 1
		fi
		size="$(socbak_xml_attr "${line}" "${unit_attr}")"
		if [[ ! ${size} =~ ^0*([1-9][0-9]*)$ ]]; then
			echo "ERROR: ${xml}: invalid ${unit_attr} for partition ${label}: \"${size}\"" >&2
			return 1
		fi
		size=${BASH_REMATCH[1]}
		ro="$(socbak_xml_attr "${line}" readonly)"
		fmt="$(socbak_xml_attr "${line}" format)"
		printf '%s|%s|%s|%s\n' "${label}" "${size}" "${ro:-false}" "${fmt:-0}"
	done <<< "${tags}"
}

# 主 GPT（LBA 0..33，17408 字节）生成 —— 统一入口。
# $1: 分区表 XML；$2: 输出文件
socbak_gen_gpt()
{
	local xml="$1"
	local out="$2"
	local unit

	[ -f "${xml}" ] || { echo "ERROR: partition xml ${xml} not found" >&2; return 1; }

	unit="$(socbak_xml_unit_attr "${xml}")" || return 1
	if [ "${unit}" = "size_in_sectors" ]; then
		socbak_gen_gpt_sector "${xml}" "${out}"
	else
		socbak_gen_gpt_kib "${xml}" "${out}"
	fi
}

# size_in_kb 格式：沿用 binTools/mk_gpt，输出与历史版本一致。
# SOCBAK_MK_GPT 可指向别的可执行文件（回归脚本在 x86 上用 qemu-aarch64 包装 binTools/mk_gpt）。
socbak_gen_gpt_kib()
{
	local xml="$1"
	local out="$2"
	local tools_dir="${TGZ_FILES_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
	local mk_gpt="${SOCBAK_MK_GPT:-${tools_dir}/binTools/mk_gpt}"

	# 旧 mk_gpt 遇到缺少尺寸的分区也会写出带头签名的文件。
	socbak_xml_partition_rows "${xml}" >/dev/null || return 1
	[ -f "${mk_gpt}" ] || { echo "ERROR: ${mk_gpt} not found" >&2; return 1; }
	[ -x "${mk_gpt}" ] || chmod +x "${mk_gpt}" 2>/dev/null
	rm -f "${out}"

	# mk_gpt 成功时也返回 255（main 里 ret 初值为 -1），只能靠产物校验判定
	"${mk_gpt}" -p "${xml}" -d "${out}" 1 >/dev/null 2>&1 || [ "$?" -eq 255 ] || return 1
	socbak_validate_gpt "${out}"
}

# 定位 sgdisk：优先用分发包自带的 binTools/sgdisk（aarch64 静态链接，随 socbak_md5.txt
# 一起校验，版本与行为可控），没有才回退到系统 PATH 里的 sgdisk。
# 与 binTools 里其它工具一致：自带优先，避免不同批次固件自带的 sgdisk 版本差异
# 改变 last_usable_lba / 对齐语义。找不到时返回非 0。
socbak_sgdisk_bin()
{
	local tools_dir="${TGZ_FILES_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
	local bundled="${tools_dir}/binTools/sgdisk"

	if [ -x "${bundled}" ]; then
		echo -n "${bundled}"
		return 0
	fi
	if command -v sgdisk >/dev/null 2>&1; then
		command -v sgdisk
		return 0
	fi
	return 1
}

# size_in_sectors 格式：板上 sgdisk 建表后截取主 GPT。
# 用稀疏文件承载整盘尺寸，实际只写 MBR + 主 GPT + 备份 GPT，磁盘占用几十 KB。
socbak_gen_gpt_sector()
{
	local xml="$1"
	local out="$2"
	local rows label size ro fmt
	local total=0
	local start=8192
	local end idx=0
	local tmp="" _dir _sgdisk
	local -a sgdisk_args=()

	_sgdisk="$(socbak_sgdisk_bin)" || {
		echo "ERROR: sgdisk not found, it is required to build a sector-unit partition table (${xml})" >&2
		return 1
	}

	total="$(socbak_xml_total "${xml}")" || return 1
	rows="$(socbak_xml_partition_rows "${xml}")" || return 1

	# PARTITION_BASIC_DATA_GUID（与 SDK mk_sector_gpt 一致）：0700 = Microsoft basic data
	# 末分区必须给备份 GPT（LBA total-33..total-1）留出空间：主 GPT 只截取到 LBA 33，
	# 但刷机时落在同一块盘上，分区压到备份区会让 u-boot/内核读表异常。
	# 最后一个合法 LBA 是 total-34（= SDK 的 last_usable_lba），刚好用满必须放行，
	# 越过一个扇区才判错。
	while IFS='|' read -r label size ro fmt; do
		idx=$(( idx + 1 ))
		end=$(( start + size - 1 ))
		if [ "${end}" -gt $(( total - 34 )) ]; then
			echo "ERROR: ${xml}: partition ${label} ends at LBA ${end}, does not leave room for the backup GPT (last usable LBA is $(( total - 34 )), disk has ${total} sectors)" >&2
			return 1
		fi
		sgdisk_args+=(-n "${idx}:${start}:${end}" -t "${idx}:0700" -c "${idx}:${label}")
		# readonly=true -> GPT 属性位 60（与 mk_gpt 的 1<<60 一致）
		if [ "${ro}" = "true" ]; then
			sgdisk_args+=(-A "${idx}:set:60")
		fi
		start=$(( end + 1 ))
	done <<< "${rows}"

	# 承载整盘尺寸的稀疏文件优先放本地临时目录：/socrepack 通常是网络文件系统，
	# 稀疏语义与出错行为取决于服务端，而这张表实际只写几十 KB。
	# 本地不可写时退回输出文件所在目录，避免功能因环境差异失效。
	# 用 mktemp 原子创建：文件名由内核保证本次调用独享（$$ 在同一脚本的并发子 shell 里
	# 是同一个值，靠它拼名字会互相覆盖），清理也只 rm 这一个文件。
	for _dir in "${TMPDIR:-/tmp}" "$(dirname "${out}")"; do
		[ -d "${_dir}" ] && [ -w "${_dir}" ] || continue
		tmp="$(mktemp "${_dir}/.socbak_gpt.XXXXXXXX.img" 2>/dev/null)" || { tmp=""; continue; }
		if truncate -s $(( total * 512 )) "${tmp}" 2>/dev/null; then
			break
		fi
		rm -f "${tmp}"
		tmp=""
	done
	if [ -z "${tmp}" ]; then
		echo "ERROR: cannot create a sparse file to build GPT for ${xml}" >&2
		return 1
	fi
	# 分区起止全部按 XML 精确落位，禁止 sgdisk 做 2048 扇区对齐。
	# sector 格式下 DATA 起点常常不是 2048 的整数倍（BOOT 从 LBA 8192 起、各分区不保证对齐），
	# 一旦让 sgdisk 对齐就会平移 DATA 起点，OTA 保留末分区的检查随之失效。
	# -a 必须排在 -n 之前：sgdisk 按命令行顺序处理，后置的 -a 对已解析的分区不生效。
	sgdisk_args=(-a 1 "${sgdisk_args[@]}")
	if ! "${_sgdisk}" "${sgdisk_args[@]}" "${tmp}" >/dev/null 2>&1; then
		echo "ERROR: sgdisk failed to build GPT for ${xml}" >&2
		rm -f "${tmp}"
		return 1
	fi
	rm -f "${out}"
	if ! dd if="${tmp}" of="${out}" bs=512 count=34 status=none 2>/dev/null; then
		echo "ERROR: cannot extract primary GPT from ${tmp}" >&2
		rm -f "${tmp}" "${out}"
		return 1
	fi
	rm -f "${tmp}"

	socbak_validate_gpt "${out}"
}

# 打包时检查主 GPT 的长度和头签名。
socbak_validate_gpt()
{
	local out="$1"
	local sig
	local size

	[ -s "${out}" ] || { echo "ERROR: gpt file ${out} is empty" >&2; return 1; }
	size=$(stat -c %s "${out}" 2>/dev/null)
	if [ "${size}" != "17408" ]; then
		echo "ERROR: gpt file ${out} size ${size} != 17408" >&2
		return 1
	fi
	sig=$(dd if="${out}" bs=1 skip=512 count=8 status=none 2>/dev/null | od -An -tx1 | tr -d ' \n')
	if [ "${sig}" != "4546492050415254" ]; then
		# 0x5452415020494645 = "EFI PART"，按小端逐字节写出
		echo "ERROR: gpt file ${out} has no valid GPT header signature (got ${sig})" >&2
		return 1
	fi
	return 0
}
