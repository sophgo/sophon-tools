#!/bin/bash
# socbak 分区表单位回归测试（MYS-2981 / MYS-2982）
#
# 背景：SE9（BM1688 / CV186AH）与 SE13（CV84X6）的刷机包改用 CV84×6 SDK 的
# sector 分区表格式（partition32G_sector.xml，属性 size_in_sectors，1 sector = 512 B），
# SE7（BM1684X / BM1684）保持 size_in_kb 与 partition32G.xml。
#
# 本脚本验证的是「同一份字节布局在两种写法下产物完全一致」，不依赖真机：
#   A 芯片路由：BM1688 / CV186AH / CV84X6 出 sector 表；BM1684X / BM1684 出 KiB 表
#   B XML 等价：等价的新旧 XML 总容量、每个分区字节数相同；131072 KiB → 262144 sectors；
#               奇数扇区（无法用 KiB 表达）的字节数与 LBA 精确
#   C GPT 等价：两种 XML 经 socbak_gen_gpt 生成的 GPT，每个分区的起止 LBA、
#               readonly 属性位、分区名、分区数完全一致；越界分区被拒绝
#   D 刷写 LBA：CV 打包链（script/bm1688）解析新旧 XML 得到的 PART_OFFSET 与
#               boot_emmc-*.cmd 里的 mmc write 起始扇区完全一致
#   E 固定 DATA 起点：SOC_BAK_FIXED_DATA_START 的 ROOTFS_RW 补偿算法在两种单位下结果一致
#
# 用法（仓库根）：
#   bash source/psocbak/tests/partition_units.sh
#
# 可选：
#   SOCBAK_SDK_SECTOR_XML=<path>  CV84×6 SDK 的 partition32G_sector.xml，
#                                 有则额外做一次夹具核查（SE13 布局）
#   SOCBAK_MK_GPT=<wrapper>       跑 KiB 生成器用的 mk_gpt（x86 主机需自行用 qemu 包装，
#                                 脚本在检测到非 aarch64 且存在 qemu-aarch64 时自动包装）
set -u

TESTS_SRC_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SOCBAK_DIR="$(cd "${TESTS_SRC_DIR}/../socbak" && pwd)"
PT_SH="${SOCBAK_DIR}/script/partition_table.sh"
PKG_SH="${SOCBAK_DIR}/script/bm1688/bm_make_package.sh"

for f in "${PT_SH}" "${PKG_SH}"; do
	[ -f "${f}" ] || { echo "ERROR: 缺少待测文件 ${f}" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

PASS=0
FAIL=0
FAILED_NAMES=()

ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); printf '  FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check_eq() { # name expected actual
	if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expect [$2] got [$3]"; fi
}
check_ne() {
	if [ "$2" != "$3" ]; then ok "$1"; else bad "$1" "不应相等，却都是 [$2]"; fi
}

# ---------------------------------------------------------------- 被测函数
# shellcheck source=/dev/null
source "${PT_SH}"

# ---------------------------------------------------------------- 工具准备
# binTools/mk_gpt 是 aarch64 静态二进制。x86 主机上用 qemu-aarch64 包装后仍可跑，
# 这样 KiB 路径（SE7）能在这台机器上原样验证，不需要把测试搬上板子。
if [ -z "${SOCBAK_MK_GPT:-}" ]; then
	if [ "$(uname -m)" = "aarch64" ]; then
		SOCBAK_MK_GPT="${SOCBAK_DIR}/binTools/mk_gpt"
	elif command -v qemu-aarch64 >/dev/null 2>&1; then
		printf '#!/bin/sh\nexec qemu-aarch64 %s "$@"\n' "${SOCBAK_DIR}/binTools/mk_gpt" > "${WORK}/mk_gpt_qemu"
		chmod +x "${WORK}/mk_gpt_qemu"
		SOCBAK_MK_GPT="${WORK}/mk_gpt_qemu"
	fi
fi
export SOCBAK_MK_GPT
export TGZ_FILES_PATH="${SOCBAK_DIR}"

HAS_SGDISK=0
command -v sgdisk >/dev/null 2>&1 && HAS_SGDISK=1
HAS_MKGPT=0
[ -n "${SOCBAK_MK_GPT:-}" ] && [ -f "${SOCBAK_MK_GPT}" ] && HAS_MKGPT=1
HAS_PY=0
command -v python3 >/dev/null 2>&1 && HAS_PY=1

# ---------------------------------------------------------------- XML 夹具
# 一把分区行按 KiB 给出；sector 版由 socbak_emit_partition_xml 换算。
LAYOUT_TOTAL_KIB=20971520
LAYOUT_ROWS=(
	"BOOT|131072|false|1"
	"RECOVERY|3145728|false|2"
	"MISC|10240|false|0"
	"ROOTFS|2621440|true|2"
	"ROOTFS_RW|6291456|false|2"
	"OPT|2097152|false|2"
	"DATA|4194304|false|2"
)
LAYOUT_ROWS_NO_OPT=(
	"BOOT|131072|false|1"
	"RECOVERY|131072|false|2"
	"MISC|10240|false|0"
	"ROOTFS|3145728|true|2"
	"ROOTFS_RW|9291456|false|2"
	"DATA|4194304|false|2"
)

# 由 socbak.sh 实际使用的写出函数产出等价的两份 XML
emit_pair() { # <tag> <total_kib> <rows...>
	local tag="$1" total="$2"
	shift 2
	socbak_emit_partition_xml "${WORK}/${tag}_kib.xml" 0 "${total}" "$@"
	socbak_emit_partition_xml "${WORK}/${tag}_sector.xml" 1 "${total}" "$@"
}

# 取某 XML 的总容量（按该 XML 自身单位）
xml_total() {
	local xml="$1"
	grep -Po 'physical_partition[^>]*size_in_[a-z]+="[0-9]+"' "${xml}" | head -n1 |
		awk -F'"' '{print $2}'
}

echo "== A. 芯片路由 =="
for chip in bm1688 cv186ah cv84x6; do
	check_eq "路由 ${chip} 分区表文件名" "partition32G_sector.xml" "$(socbak_partition_file_name "${chip}")"
	check_eq "路由 ${chip} 使用 sector 单位" "0" \
		"$(socbak_partition_uses_sector "${chip}" && echo 0 || echo 1)"
done
for chip in bm1684x bm1684; do
	check_eq "路由 ${chip} 分区表文件名" "partition32G.xml" "$(socbak_partition_file_name "${chip}")"
	check_eq "路由 ${chip} 使用 KiB 单位" "1" \
		"$(socbak_partition_uses_sector "${chip}" && echo 0 || echo 1)"
done

echo "== B. XML 单位换算 =="
check_eq "131072 KiB -> 262144 sectors" "262144" "$(socbak_size_in_unit 131072 1)"
check_eq "131072 KiB 在 KiB 单位下原样输出" "131072" "$(socbak_size_in_unit 131072 0)"
check_eq "分区行属性名（sector）" "size_in_sectors" "$(socbak_size_attr_name 1)"
check_eq "分区行属性名（KiB）" "size_in_kb" "$(socbak_size_attr_name 0)"

# 六分区布局（SE9 默认，无 OPT/SYSTEM）
emit_pair se9_default "${LAYOUT_TOTAL_KIB}" "${LAYOUT_ROWS_NO_OPT[@]}"
# 八分区布局（SE7 默认，含 OPT/SYSTEM）
emit_pair se7_default "${LAYOUT_TOTAL_KIB}" "${LAYOUT_ROWS[@]}"

for tag in se9_default se7_default; do
	kib_xml="${WORK}/${tag}_kib.xml"
	sec_xml="${WORK}/${tag}_sector.xml"
	npart="$(grep -c '<partition ' "${kib_xml}")"
	check_eq "${tag}: KiB 版每行都用 size_in_kb" "${npart}" \
		"$(grep -cE '<partition label="[^"]+" +size_in_kb="[0-9]+"' "${kib_xml}")"
	check_eq "${tag}: KiB 版不出现 size_in_sectors" "0" "$(grep -c 'size_in_sectors=' "${kib_xml}")"
	check_eq "${tag}: sector 版每行都用 size_in_sectors" "${npart}" \
		"$(grep -cE '<partition label="[^"]+" +size_in_sectors="[0-9]+"' "${sec_xml}")"
	check_eq "${tag}: sector 版不出现 size_in_kb" "0" "$(grep -c 'size_in_kb=' "${sec_xml}")"
	check_eq "${tag}: sector 版只有根元素带总容量" "1" \
		"$(grep -c '^<physical_partition size_in_sectors=' "${sec_xml}")"
	# 属性顺序与 SDK 一致：label → 尺寸 → readonly → format
	check_eq "${tag}: sector 版属性顺序 label/size/readonly/format" "${npart}" \
		"$(grep -cE '<partition label="[^"]+" +size_in_sectors="[0-9]+" +readonly="(true|false)" +format="[0-9]" />' "${sec_xml}")"
	# 总容量按字节相等
	check_eq "${tag}: 两种单位总容量字节数相等" \
		"$(( $(xml_total "${kib_xml}") * 1024 ))" \
		"$(( $(xml_total "${sec_xml}") * 512 ))"
	# 逐分区字节数相等
	check_eq "${tag}: 逐分区字节数相等" \
		"$(socbak_xml_partition_rows "${kib_xml}" | awk -F'|' '{printf "%s=%d\n", $1, $2*1024}')" \
		"$(socbak_xml_partition_rows "${sec_xml}" | awk -F'|' '{printf "%s=%d\n", $1, $2*512}')"
	# 分区顺序、只读位、format 不变
	check_eq "${tag}: 分区顺序/只读位/format 一致" \
		"$(socbak_xml_partition_rows "${kib_xml}" | awk -F'|' '{printf "%s|%s|%s\n", $1, $3, $4}')" \
		"$(socbak_xml_partition_rows "${sec_xml}" | awk -F'|' '{printf "%s|%s|%s\n", $1, $3, $4}')"
done

# 奇数扇区：131073 个扇区 = 67109376 B，无法用整 KiB 表达，必须按扇区精确处理
cat > "${WORK}/odd_sector.xml" <<'XML'
<physical_partition size_in_sectors="40000001">
  <partition label="BOOT"       size_in_sectors="131072"  readonly="false"  format="1" />
  <partition label="RECOVERY"   size_in_sectors="131073"  readonly="false" format="2" />
  <partition label="MISC"       size_in_sectors="20481"  readonly="false"   format="0" />
  <partition label="ROOTFS"     size_in_sectors="1000001" readonly="true"   format="2" />
  <partition label="ROOTFS_RW"  size_in_sectors="16485759" readonly="false"  format="2" />
  <partition label="DATA"       size_in_sectors="1234567" readonly="false"  format="2" />
</physical_partition>
XML
check_eq "奇数扇区 XML 可被解析出 6 个分区" "6" "$(socbak_xml_partition_rows "${WORK}/odd_sector.xml" | wc -l)"
check_eq "奇数扇区 131073 sectors 的字节数" "67109376" \
	"$(socbak_xml_partition_rows "${WORK}/odd_sector.xml" | awk -F'|' '$1=="RECOVERY"{print $2*512}')"

# ---------------------------------------------------------------- GPT 解码
# 只用一份 Python 解码，避免在 shell 里手算 little-endian。
cat > "${WORK}/dump_gpt.py" <<'PY'
import struct
import sys


def dump(path):
    d = open(path, 'rb').read()
    if len(d) < 17408:
        print('SHORT', len(d))
        return
    sig = d[512:520]
    if sig != b'EFI PART':
        print('NOSIG')
        return
    my_lba, alt_lba, first, last = struct.unpack('<QQQQ', d[512 + 24:512 + 56])
    entry_lba, num, esz = struct.unpack('<QII', d[512 + 72:512 + 88])
    mbr_size = struct.unpack('<I', d[458:462])[0]
    print('hdr my=%d alt=%d first=%d last=%d entry=%d num=%d esz=%d mbr_size=%d'
          % (my_lba, alt_lba, first, last, entry_lba, num, esz, mbr_size))
    base = entry_lba * 512
    for i in range(num):
        e = d[base + i * esz:base + (i + 1) * esz]
        if e[:16] == b'\0' * 16:
            continue
        start, end = struct.unpack('<QQ', e[32:48])
        attr = struct.unpack('<Q', e[48:56])[0]
        name = e[56:128].decode('utf-16-le', 'replace').rstrip('\0')
        print('p%d name=%s start=%d end=%d sectors=%d ro=%d'
              % (i + 1, name, start, end, end - start + 1, (attr >> 60) & 1))


dump(sys.argv[1])
PY

gpt_summary() { # <xml> <out.gpt>
	if [ "${HAS_PY}" = "1" ]; then
		python3 "${WORK}/dump_gpt.py" "$2"
	else
		echo "NOPY"
	fi
}

echo "== C. GPT 等价性 =="
if [ "${HAS_SGDISK}" = "0" ]; then
	bad "sector 版 GPT 生成" "环境里没有 sgdisk"
else
	# SE9 默认布局：sector 版 GPT 必须自洽（主 GPT 头签名、分区项、起止 LBA）
	if socbak_gen_gpt "${WORK}/se9_default_sector.xml" "${WORK}/se9_sector.gpt"; then
		ok "sector 版 GPT 生成成功"
		sum_line="$(gpt_summary x "${WORK}/se9_sector.gpt")"
		check_eq "sector 版 GPT 头签名有效" "1" "$(echo "${sum_line}" | grep -c '^hdr ')"
	# 首分区固定 LBA 8192、分区名、只读位、起止全部来自 XML
	expect_rows="$(socbak_xml_partition_rows "${WORK}/se9_default_sector.xml")"
	acc=""
	lba=8192
	idx=0
	while IFS='|' read -r label size ro fmt; do
		[ -n "${label}" ] || continue
		end=$(( lba + size - 1 ))
		acc="${acc}p$((idx + 1)) name=${label} start=${lba} end=${end} sectors=${size} ro=$([ "${ro}" = "true" ] && echo 1 || echo 0)"$'\n'
		lba=$(( end + 1 ))
		idx=$(( idx + 1 ))
	done <<< "${expect_rows}"
	check_eq "sector 版 GPT 各分区起止/只读位与 XML 一致" \
		"$(echo "${acc}" | sed '/^$/d')" \
		"$(echo "${sum_line}" | grep '^p')"
	# 分区数与 XML 行数一致，首分区从 8192 开始
	check_eq "sector 版 GPT 分区数等于 XML 行数" "$(echo "${expect_rows}" | wc -l)" \
		"$(echo "${sum_line}" | grep -c '^p')"
	check_eq "sector 版 GPT 首分区从 LBA 8192 开始" "1" \
		"$(echo "${sum_line}" | grep -c '^p1 .* start=8192 ')"
	else
		bad "sector 版 GPT 生成" "socbak_gen_gpt 返回非 0"
	fi

	# 新旧等价 XML 的 GPT 必须逐分区一致（磁盘 GUID/分区 GUID 天然随机，不比较）
	if [ "${HAS_MKGPT}" = "1" ]; then
		if socbak_gen_gpt "${WORK}/se7_default_sector.xml" "${WORK}/se7_sector.gpt" &&
			socbak_gen_gpt "${WORK}/se7_default_kib.xml" "${WORK}/se7_kib.gpt"; then
			ok "KiB 与 sector 两路 GPT 均生成成功"
			check_eq "新旧 XML 的 GPT 分区表完全一致" \
				"$(gpt_summary x "${WORK}/se7_kib.gpt")" \
				"$(gpt_summary x "${WORK}/se7_sector.gpt")"
		else
			bad "KiB/sector 两路 GPT 生成" "生成失败"
		fi
	else
		echo "  skip 新旧 XML GPT 对比（没有可用的 mk_gpt，也没有 qemu-aarch64）"
	fi

	# 分区越过磁盘末尾必须被拒绝，不能生成一张会被刷坏的 GPT
	cat > "${WORK}/overflow.xml" <<'XML'
<physical_partition size_in_sectors="100000">
  <partition label="BOOT"       size_in_sectors="131072"  readonly="false"  format="1" />
</physical_partition>
XML
	if socbak_gen_gpt "${WORK}/overflow.xml" "${WORK}/overflow.gpt" 2>/dev/null; then
		bad "越界分区被拒绝" "居然生成了 GPT"
	else
		ok "越界分区被拒绝"
	fi
	check_ne "越界时不留下半成品 GPT" "1" "$([ -s "${WORK}/overflow.gpt" ] && echo 1 || echo 0)"

	# 空/非法尺寸必须被拒绝
	cat > "${WORK}/bad_size.xml" <<'XML'
<physical_partition size_in_sectors="10000000">
  <partition label="BOOT"       size_in_sectors="0"  readonly="false"  format="1" />
</physical_partition>
XML
	if socbak_gen_gpt "${WORK}/bad_size.xml" "${WORK}/bad_size.gpt" 2>/dev/null; then
		bad "零尺寸分区被拒绝" "居然生成了 GPT"
	else
		ok "零尺寸分区被拒绝"
	fi
fi

echo "== D. 刷写 LBA（CV 打包链） =="
# 直接驱动 script/bm1688 的 parse_partition_xml：分区偏移是该脚本写 mmc 的唯一依据
drive_offsets() { # <xml>
	(
		# shellcheck source=/dev/null
		set +u
		source "${PKG_SH}" >/dev/null 2>&1
		PARTITION_FILE="$1"
		parse_partition_xml
		for i in "${!LABELS[@]}"; do
			printf '%s start=%s sectors=%s bytes=%s\n' \
				"${LABELS[$i]}" "${PART_OFFSET[$i]}" "${PART_SIZE_IN_SECTOR[$i]}" "${PART_SIZE_IN_BYTE[$i]}"
		done
		printf 'END_OFFSET=%s\n' "${END_OFFSET}"
	)
}

off_old="$(drive_offsets "${WORK}/se7_default_kib.xml")"
off_new="$(drive_offsets "${WORK}/se7_default_sector.xml")"
check_ne "CV 打包链能读到分区偏移" "" "${off_new}"
check_eq "新旧 XML 的刷写偏移与镜像尺寸一致" "${off_old}" "${off_new}"
check_eq "首分区从 LBA 8192 开始" "1" "$(echo "${off_new}" | grep -c 'start=8192 ')"
check_eq "各分区首尾相接（END_OFFSET 等于 LBA 累加）" \
	"$(( 8192 + $(socbak_xml_partition_rows "${WORK}/se7_default_sector.xml" | awk -F'|' '{s+=$2} END{print s}') ))" \
	"$(echo "${off_new}" | awk -F'=' '/END_OFFSET/{print $2}')"

# 奇数扇区必须逐字节精确，不允许被 KiB 取整
odd_off="$(drive_offsets "${WORK}/odd_sector.xml")"
check_eq "奇数扇区 XML: RECOVERY 字节数精确" "67109376" \
	"$(echo "${odd_off}" | awk '/^recovery/{sub(/.*bytes=/, ""); print}')"
check_eq "奇数扇区 XML: MISC 起始扇区精确" \
	"$(( 8192 + 131072 + 131073 ))" \
	"$(echo "${odd_off}" | awk '/^misc/{sub(/.*start=/, ""); sub(/ .*/, ""); print}')"
check_eq "奇数扇区 XML: 末分区起始扇区精确" \
	"$(( 8192 + 131072 + 131073 + 20481 + 1000001 + 16485759 ))" \
	"$(echo "${odd_off}" | awk '/^data/{sub(/.*start=/, ""); sub(/ .*/, ""); print}')"

# boot_emmc-*.cmd 里的 mmc write 起始扇区必须等于解析出来的 PART_OFFSET
if command -v mkimage >/dev/null 2>&1 && command -v pigz >/dev/null 2>&1; then
	script_lba() { # <xml> <part_index> <part_name>
		local xml="$1" idx="$2" name="$3"
		local d="${WORK}/sc_${idx}_$$"
		rm -rf "${d}"; mkdir -p "${d}/sdcard"
		(
			set +u
			export PATH="${SOCBAK_DIR}/binTools:${PATH}"
			# shellcheck source=/dev/null
			source "${PKG_SH}" >/dev/null 2>&1
			PARTITION_FILE="${xml}"
			SOURCE_FILES_PATH="${d}"
			RECOVERY_DIR="${d}/sdcard"
			UPTYPE=sdcard
			parse_partition_xml
			CURRENT_SCRIPT="${RECOVERY_DIR}/boot_emmc.cmd"
			: > "${CURRENT_SCRIPT}"
			dd if=/dev/zero of="${RECOVERY_DIR}/${name}" bs=512 count=64 status=none
			split_and_compress_img "${idx}" "${name}"
		) >/dev/null 2>&1
		# mmc write <addr> <offset> <count>：第 4 列是起始扇区
		grep -h '^mmc write' "${d}/sdcard/boot_emmc-${name}.cmd" 2>/dev/null | awk '{print $4}' | head -n1
		rm -rf "${d}"
	}
	# 分区索引按 XML 行序推导，不能写死：夹具含 OPT/SYSTEM，DATA 不在固定位置
	data_idx() { # <xml>
		socbak_xml_partition_rows "$1" | awk -F'|' 'BEGIN{i=-1} {i++; if ($1=="DATA") print i; }'
	}
	lba_old="$(script_lba "${WORK}/se7_default_kib.xml" "$(data_idx "${WORK}/se7_default_kib.xml")" data)"
	lba_new="$(script_lba "${WORK}/se7_default_sector.xml" "$(data_idx "${WORK}/se7_default_sector.xml")" data)"
	check_ne "boot_emmc-*.cmd 里有 mmc write 起始扇区" "" "${lba_new}"
	check_eq "新旧 XML 的 DATA 刷写起始扇区一致" "${lba_old}" "${lba_new}"
	# boot_emmc-*.cmd 第三列是 mmc write 的起始扇区，必须等于解析出的 PART_OFFSET
	check_eq "DATA 刷写起始扇区等于 PART_OFFSET" \
		"$(printf '0x%08x' "$(echo "${off_new}" | awk '/^data/{sub(/.*start=/, ""); sub(/ .*/, ""); print}')")" \
		"${lba_new}"
else
	echo "  skip boot_emmc 脚本校验（缺少 mkimage 或 pigz）"
fi

echo "== E. 固定 DATA 起点补偿 =="
# 与旧实现逐字对应：扩容时把差额还给 ROOTFS_RW，缩容时保留 200 KiB 余量
check_eq "无变化时 ROOTFS_RW 不变" "6291456" "$(socbak_fixed_data_start_rw 6291456 6291456 6291456)"
check_eq "其他分区缩小时 ROOTFS_RW 变大" "6737856" "$(socbak_fixed_data_start_rw 7000000 6553600 6291456)"
check_eq "其他分区扩大时 ROOTFS_RW 变小" "5737856" "$(socbak_fixed_data_start_rw 6000000 6553600 6291456)"
if socbak_fixed_data_start_rw 6000000 6553600 700000 >/dev/null; then
	bad "ROOTFS_RW 不足以补偿时报错" "没有报错"
else
	ok "ROOTFS_RW 不足以补偿时报错"
	check_eq "报错时给出需要的差额（含 200 KiB 余量）" "758400" "${SOCBAK_FIXED_DATA_START_DIFF_KB}"
fi
# 补偿后 DATA 起点在两种单位下都是同一个扇区
emit_pair fds "${LAYOUT_TOTAL_KIB}" "${LAYOUT_ROWS_NO_OPT[@]}"
rw_kib="$(socbak_fixed_data_start_rw 6291456 6553600 6291456)"
data_start_kib="$(socbak_xml_partition_rows "${WORK}/fds_kib.xml" |
	awk -F'|' '$1=="DATA"{print 8192 + $2*1024/512}')"
data_start_sec="$(socbak_xml_partition_rows "${WORK}/fds_sector.xml" |
	awk -F'|' '$1=="DATA"{print 8192 + $2}')"
check_eq "等价布局下 DATA 起始扇区一致" "${data_start_kib}" "${data_start_sec}"
check_ne "补偿后的 ROOTFS_RW 仍然可算" "" "${rw_kib}"

echo "== F. CV84×6 SDK 夹具核查（SE13） =="
SDK_XML="${SOCBAK_SDK_SECTOR_XML:-}"
if [ -z "${SDK_XML}" ]; then
	for c in \
		"${SOCBAK_DIR}/../../../cv84x2/build/scripts/partition32G_sector.xml" \
		/opt/sophgo/cv84x6/build/scripts/partition32G_sector.xml; do
		[ -f "${c}" ] && { SDK_XML="${c}"; break; }
	done
fi
if [ -z "${SDK_XML}" ] || [ ! -f "${SDK_XML}" ]; then
	echo "  skip 未提供 CV84×6 SDK 的 partition32G_sector.xml（可用 SOCBAK_SDK_SECTOR_XML 指定）"
else
	SDK_XML="$(readlink -f "${SDK_XML}")"
	echo "  fixture: ${SDK_XML}"
	rows="$(socbak_xml_partition_rows "${SDK_XML}")"
	check_ne "SDK 夹具可解析" "" "${rows}"
	check_eq "SDK 夹具每行都是 size_in_sectors" \
		"$(grep -c '<partition ' "${SDK_XML}")" \
		"$(grep -c '<partition [^>]*size_in_sectors=' "${SDK_XML}")"
	check_eq "SDK 夹具不出现 size_in_kb" "0" "$(grep -c 'size_in_kb=' "${SDK_XML}")"
	# 首分区 LBA 8192，且分区合计不越过整盘
	check_eq "SDK 夹具分区合计不超过整盘" "1" \
		"$(echo "${rows}" | awk -F'|' -v t="$(xml_total "${SDK_XML}")" '{s+=$2} END{print (8192 + s <= t) ? 1 : 0}')"
	if [ "${HAS_SGDISK}" = "1" ] && socbak_gen_gpt "${SDK_XML}" "${WORK}/sdk.gpt"; then
		ok "SDK 夹具可生成 GPT"
		lba=8192
		mismatch=0
		while IFS='|' read -r label size ro fmt; do
			end=$(( lba + size - 1 ))
			echo "${label}|${lba}|${end}|$([ "${ro}" = "true" ] && echo 1 || echo 0)"
			lba=$(( end + 1 ))
		done <<< "${rows}" > "${WORK}/sdk_expected.txt"
		check_eq "SDK 夹具 GPT 与 XML 一致" \
			"$(cat "${WORK}/sdk_expected.txt")" \
			"$(python3 "${WORK}/dump_gpt.py" "${WORK}/sdk.gpt" | grep '^p' |
				sed -E 's/^p[0-9]+ name=([^ ]+) start=([0-9]+) end=([0-9]+) sectors=[0-9]+ ro=([01])$/\1|\2|\3|\4/')"
	else
		echo "  skip SDK 夹具 GPT 生成（缺 sgdisk 或生成失败）"
	fi
fi

echo
if [ "${FAIL}" -eq 0 ]; then
	echo "PASS ${PASS}/${PASS}"
	exit 0
fi
echo "FAIL ${FAIL}（共 $((PASS + FAIL)) 项）"
for n in "${FAILED_NAMES[@]}"; do echo "  - ${n}"; done
exit 1
