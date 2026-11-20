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

# SOC_BAK_FIXED_DATA_START：用 ROOTFS_RW 吸收其他分区的扩容/缩容，使最后一个分区
# （DATA）的起始扇区保持不变，OTA 才能在升级时保留 DATA。
#   $1 配置侧“除 DATA 外”的分区合计（KiB）
#   $2 本次打包实际“除 DATA 外”的分区合计（KiB）
#   $3 当前 ROOTFS_RW 大小（KiB）
# 结果通过全局变量返回，不写 stdout —— 必须在调用者所在的 shell 里直接调用，
# 不能写成 X="$(socbak_fixed_data_start_rw ...)"：命令替换是子 shell，
# 失败差额留在子 shell 里，调用方读到的是未定义变量（set -u 下直接 unbound variable），
# 真正的原因会被 "unbound variable" 掩盖掉。
#   成功：SOCBAK_FIXED_DATA_START_RW_KB = 调整后的 ROOTFS_RW（KiB），返回 0
#   失败：SOCBAK_FIXED_DATA_START_DIFF_KB = 需要的差额（KiB），返回 1
# 与原实现逐字对应：扩容方向直接把差额还给 ROOTFS_RW；缩容方向要求 ROOTFS_RW 至少比差额
# 多出 200 MiB 余量（RW_BUFFER_SIZE = 200 * 1024 KiB），否则判定打包失败。
socbak_fixed_data_start_rw()
{
	local old_kb="$1"
	local new_kb="$2"
	local rw_kb="$3"
	local diff_kb

	SOCBAK_FIXED_DATA_START_RW_KB=""
	SOCBAK_FIXED_DATA_START_DIFF_KB=0
	if [ "${old_kb}" -gt "${new_kb}" ]; then
		rw_kb=$(( rw_kb + (old_kb - new_kb) ))
	elif [ "${old_kb}" -lt "${new_kb}" ]; then
		diff_kb=$(( new_kb - old_kb + 200 * 1024 ))
		if [ "${rw_kb}" -lt "${diff_kb}" ]; then
			SOCBAK_FIXED_DATA_START_DIFF_KB=${diff_kb}
			return 1
		fi
		rw_kb=$(( rw_kb - (new_kb - old_kb) ))
	fi
	SOCBAK_FIXED_DATA_START_RW_KB=${rw_kb}
	return 0
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

	if [ "${uses_sector}" = "1" ]; then
		attr="size_in_sectors"
	else
		attr="size_in_kb"
	fi

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

# 分区表用哪种尺寸单位：size_in_sectors（sector，1 sector = 512 B）或 size_in_kb（KiB）
# $1: XML 路径
socbak_xml_unit_attr()
{
	if grep -q 'size_in_sectors="' "$1" 2>/dev/null; then
		echo -n "size_in_sectors"
	else
		echo -n "size_in_kb"
	fi
}

# 从一行 XML 里取某个属性的值；属性不存在时输出空串。
# 逐属性取值（而不是把同名属性各自 grep 成一个数组）是分区行解析正确性的前提：
# 某一行省略 readonly 时，数组下标会整体前移，把下一行的值错配到本行。
# $1: 一行 XML 文本；$2: 属性名
socbak_xml_attr()
{
	local line="$1"
	local attr="$2"
	if [[ "${line}" =~ [[:space:]]${attr}=\"([^\"]*)\" ]]; then
		echo -n "${BASH_REMATCH[1]}"
	fi
}

# 取 <physical_partition> 的总容量，单位与该 XML 自身一致
# $1: XML 路径
socbak_xml_total()
{
	local xml="$1"
	local root
	root="$(grep -m1 '<physical_partition' "${xml}" 2>/dev/null)"
	socbak_xml_attr "${root}" "$(socbak_xml_unit_attr "${xml}")"
}

# 从 XML 取分区记录，行序即分区序。每次调用重新解析整个文件，
# GPT 生成与刷写布局都消费这同一组记录，两者不会因为解析方式不同而错位。
# 输出每行：label|size|readonly|format
#   size 为该 XML 自身单位下的数值
#   readonly 缺省 false、format 缺省 0（与 SDK 的 mk_sector_gpt 一致：属性缺失取 0）
# $1: XML 路径
socbak_xml_partition_rows()
{
	local xml="$1"
	local unit_attr line label size ro fmt
	local n=0

	unit_attr="$(socbak_xml_unit_attr "${xml}")"

	while IFS= read -r line; do
		case "${line}" in
			*'<partition '*) ;;
			*) continue ;;
		esac
		label="$(socbak_xml_attr "${line}" label)"
		[ -n "${label}" ] || continue
		size="$(socbak_xml_attr "${line}" "${unit_attr}")"
		ro="$(socbak_xml_attr "${line}" readonly)"
		fmt="$(socbak_xml_attr "${line}" format)"
		[ -n "${ro}" ] || ro="false"
		[ -n "${fmt}" ] || fmt="0"
		if [ -z "${size}" ]; then
			echo "ERROR: ${xml}: partition ${label} has no ${unit_attr} attribute" >&2
			return 1
		fi
		echo "${label}|${size}|${ro}|${fmt}"
		n=$(( n + 1 ))
	done < "${xml}"

	if [ "${n}" -eq 0 ]; then
		echo "ERROR: ${xml}: no partition found" >&2
		return 1
	fi
	return 0
}

# 主 GPT（LBA 0..33，17408 字节）生成 —— 统一入口。
# $1: 分区表 XML；$2: 输出文件
socbak_gen_gpt()
{
	local xml="$1"
	local out="$2"

	[ -f "${xml}" ] || { echo "ERROR: partition xml ${xml} not found" >&2; return 1; }

	if [ "$(socbak_xml_unit_attr "${xml}")" = "size_in_sectors" ]; then
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

	[ -f "${mk_gpt}" ] || { echo "ERROR: ${mk_gpt} not found" >&2; return 1; }
	[ -x "${mk_gpt}" ] || chmod +x "${mk_gpt}" 2>/dev/null
	rm -f "${out}"

	# mk_gpt 成功时也返回 255（main 里 ret 初值为 -1），只能靠产物校验判定
	"${mk_gpt}" -p "${xml}" -d "${out}" 1 >/dev/null 2>&1
	socbak_validate_gpt "${out}"
}

# size_in_sectors 格式：板上 sgdisk 建表后截取主 GPT。
# 用稀疏文件承载整盘尺寸，实际只写 MBR + 主 GPT + 备份 GPT，磁盘占用几十 KB。
socbak_gen_gpt_sector()
{
	local xml="$1"
	local out="$2"
	local label size ro fmt
	local total=0
	local start=8192
	local end idx=0
	local tmp="" _dir
	local -a labels=() sizes=() readonlys=() sgdisk_args=()

	command -v sgdisk >/dev/null 2>&1 || {
		echo "ERROR: sgdisk not found, it is required to build a sector-unit partition table (${xml})" >&2
		return 1
	}

	total="$(socbak_xml_total "${xml}")"
	if [ -z "${total}" ] || [ "${total}" -le 0 ] 2>/dev/null; then
		echo "ERROR: ${xml}: cannot read size_in_sectors of <physical_partition>" >&2
		return 1
	fi

	while IFS='|' read -r label size ro fmt; do
		[ -n "${label}" ] || continue
		case "${size}" in
			''|*[!0-9]*)
				echo "ERROR: ${xml}: partition ${label} has invalid size \"${size}\"" >&2
				return 1
				;;
		esac
		if [ "${size}" -le 0 ]; then
			echo "ERROR: ${xml}: partition ${label} has non-positive size ${size}" >&2
			return 1
		fi
		labels+=("${label}")
		sizes+=("${size}")
		readonlys+=("${ro}")
	done < <(socbak_xml_partition_rows "${xml}")

	if [ "${#labels[@]}" -eq 0 ]; then
		echo "ERROR: ${xml}: no partition found" >&2
		return 1
	fi

	# PARTITION_BASIC_DATA_GUID（与 SDK mk_sector_gpt 一致）：0700 = Microsoft basic data
	# 末分区必须给备份 GPT（LBA total-33..total-1）留出空间：主 GPT 只截取到 LBA 33，
	# 但刷机时落在同一块盘上，分区压到备份区会让 u-boot/内核读表异常。
	# 最后一个合法 LBA 是 total-34（= SDK 的 last_usable_lba），刚好用满必须放行，
	# 越过一个扇区才判错。
	for idx in "${!labels[@]}"; do
		end=$(( start + sizes[idx] - 1 ))
		if [ "${end}" -gt $(( total - 34 )) ]; then
			echo "ERROR: ${xml}: partition ${labels[idx]} ends at LBA ${end}, does not leave room for the backup GPT (last usable LBA is $(( total - 34 )), disk has ${total} sectors)" >&2
			return 1
		fi
		sgdisk_args+=(-n "$(( idx + 1 )):${start}:${end}")
		sgdisk_args+=(-t "$(( idx + 1 )):0700")
		sgdisk_args+=(-c "$(( idx + 1 )):${labels[idx]}")
		# readonly=true -> GPT 属性位 60（与 mk_gpt 的 1<<60 一致）
		if [ "${readonlys[idx]}" = "true" ]; then
			sgdisk_args+=(-A "$(( idx + 1 )):set:60")
		fi
		start=$(( end + 1 ))
	done

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
	if ! sgdisk "${sgdisk_args[@]}" "${tmp}" >/dev/null 2>&1; then
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

# 校验产物确实是主 GPT：34 个扇区、GPT 头签名正确、分区项 CRC 可被 gdisk 接受
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
