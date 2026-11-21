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

# SDK 表的空白和注释不影响布局。把同一份表重排，并在注释中放一个不同单位的示例。
for unit in kib sector; do
	awk '
		/<physical_partition / {
			print "<!-- example: <partition label=\"IGNORED\" size_in_sectors=\"99\" /> -->"
			sub(/<physical_partition /, "<physical_partition\n\t")
		}
		/<partition label="DATA"/ {sub(/<partition /, "<partition\n\t")}
		/<partition label="BOOT"/ {sub(/<partition /, "<partition\t")}
		{print}
	' "${WORK}/se7_default_${unit}.xml" > "${WORK}/wrapped_${unit}.xml"
	check_eq "${unit} 表按根元素识别单位" "$(socbak_xml_unit_attr "${WORK}/se7_default_${unit}.xml")" \
		"$(socbak_xml_unit_attr "${WORK}/wrapped_${unit}.xml")"
	check_eq "${unit} 表跨行读取总容量" "$(socbak_xml_total "${WORK}/se7_default_${unit}.xml")" \
		"$(socbak_xml_total "${WORK}/wrapped_${unit}.xml")"
	check_eq "${unit} 表换行、制表和注释不改变分区记录" "$(socbak_xml_partition_rows "${WORK}/se7_default_${unit}.xml")" \
		"$(socbak_xml_partition_rows "${WORK}/wrapped_${unit}.xml")"
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

	cat > "${WORK}/incomplete.xml" <<'XML'
<physical_partition size_in_sectors="32768">
  <partition label="BOOT" size_in_sectors="4096" format="1" />
  <partition label="DATA" format="2" />
</physical_partition>
XML
	if socbak_gen_gpt "${WORK}/incomplete.xml" "${WORK}/incomplete.gpt" 2>/dev/null; then
		bad "后续分区缺少尺寸时 GPT 生成失败"
	else
		ok "后续分区缺少尺寸时 GPT 生成失败"
	fi
	check_eq "后续分区解析失败时不写出部分 GPT" "0" "$([ -e "${WORK}/incomplete.gpt" ] && echo 1 || echo 0)"
	if [ "${HAS_MKGPT}" = 1 ]; then
		sed 's/size_in_sectors/size_in_kb/g' "${WORK}/incomplete.xml" > "${WORK}/incomplete_kib.xml"
		if socbak_gen_gpt "${WORK}/incomplete_kib.xml" "${WORK}/incomplete_kib.gpt" 2>/dev/null; then
			bad "KiB 分区缺少尺寸时在调用旧生成器前报错"
		else
			ok "KiB 分区缺少尺寸时在调用旧生成器前报错"
		fi
		check_eq "KiB 表解析失败时不写出部分 GPT" "0" "$([ -e "${WORK}/incomplete_kib.gpt" ] && echo 1 || echo 0)"
	fi

	# 最后可用的 LBA 是 total-34（= SDK mk_sector_gpt 的 last_usable_lba，
	# 之后 total-33..total-1 是备份 GPT 与备份分区项数组）。刚好用满必须放行，
	# 再多一个扇区（压到备份 GPT）必须拒绝 —— 两个方向都测，避免把合法边界判错。
	# 用例取自验收复现：32768 扇区的盘，首分区从 8192 起、长 24543 扇区 → 末 LBA 32734。
	mk_last_lba_xml() { # <out> <total> <size>
		cat > "$1" <<XML
<physical_partition size_in_sectors="$2">
  <partition label="BOOT"       size_in_sectors="$3"  readonly="false"  format="1" />
</physical_partition>
XML
	}
	mk_last_lba_xml "${WORK}/last_lba_ok.xml" 32768 24543
	if socbak_gen_gpt "${WORK}/last_lba_ok.xml" "${WORK}/last_lba_ok.gpt" 2>/dev/null; then
		ok "刚好用满最后合法 LBA（end=total-34）被接受"
		check_eq "刚好用满时末分区结束 LBA 为 32734" "1" \
			"$(gpt_summary x "${WORK}/last_lba_ok.gpt" | grep -c '^p1 .* start=8192 end=32734 ')"
	else
		bad "刚好用满最后合法 LBA（end=total-34）被接受" "候选代码返回非 0"
	fi
	# 再大一扇区：8192..32735 压到备份 GPT 区，必须拒绝
	mk_last_lba_xml "${WORK}/last_lba_bad.xml" 32768 24544
	if socbak_gen_gpt "${WORK}/last_lba_bad.xml" "${WORK}/last_lba_bad.gpt" 2>/dev/null; then
		bad "多占一个扇区（end=total-33）被拒绝" "居然生成了 GPT"
	else
		ok "多占一个扇区（end=total-33）被拒绝"
	fi
	check_ne "越界到备份 GPT 时不留下半成品 GPT" "1" \
		"$([ -s "${WORK}/last_lba_bad.gpt" ] && echo 1 || echo 0)"

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

	# 属性是按分区行读的：某行省略 readonly/format 不能让后面的值整体前移。
	# 用例取自验收复现：BOOT 省略 readonly、ROOTFS 写 readonly="true"，
	# 按数组各取一次的写法会得到 BOOT=true / ROOTFS=false（SDK 的缺省值是 false）。
	cat > "${WORK}/sparse_attr.xml" <<'XML'
<physical_partition size_in_sectors="35943040">
  <partition label="BOOT"       size_in_sectors="262144"  format="1" />
  <partition label="RECOVERY"   size_in_sectors="262144"  readonly="false" format="2" />
  <partition label="MISC"       size_in_sectors="20480"  readonly="false"   format="0" />
  <partition label="ROOTFS"     size_in_sectors="6291456" readonly="true"   format="2" />
  <partition label="ROOTFS_RW"  size_in_sectors="18582912" readonly="false"  format="2" />
  <partition label="DATA"       size_in_sectors="4194304" readonly="false"  format="2" />
</physical_partition>
XML
	check_eq "省略属性时按行取值（BOOT 缺省 false、ROOTFS true、format 缺省 0）" \
		"BOOT=false=1|RECOVERY=false=2|MISC=false=0|ROOTFS=true=2|ROOTFS_RW=false=2|DATA=false=2" \
		"$(socbak_xml_partition_rows "${WORK}/sparse_attr.xml" |
			awk -F'|' '{printf "%s%s%s%s%s\n", $1, "=", $3, "=", $4}' | paste -sd'|' -)"
	if socbak_gen_gpt "${WORK}/sparse_attr.xml" "${WORK}/sparse_attr.gpt" 2>/dev/null; then
		ok "省略属性的 XML 可生成 GPT"
		check_eq "原始 GPT 的只读位与按行解析一致（只有 ROOTFS 置位）" \
			"BOOT=0 RECOVERY=0 MISC=0 ROOTFS=1 ROOTFS_RW=0 DATA=0" \
			"$(gpt_summary x "${WORK}/sparse_attr.gpt" | grep '^p' |
				sed -E 's/^p[0-9]+ name=([^ ]+) .* ro=([01])$/\1=\2/' | paste -sd' ' -)"
	else
		bad "省略属性的 XML 可生成 GPT" "socbak_gen_gpt 返回非 0"
	fi
	# 刷写布局与 GPT 必须来自同一组解析结果：打包链的 P_FLAG 也要逐分区对上
	sparse_flags="$(
		set +u
		# shellcheck source=/dev/null
		source "${PKG_SH}" >/dev/null 2>&1
		PARTITION_FILE="${WORK}/sparse_attr.xml"
		parse_partition_xml 2>/dev/null
		for i in "${!LABELS[@]}"; do printf '%s=%s ' "${LABELS[$i]}" "${P_FLAG[$i]}"; done
	)"
	check_eq "打包链的只读位同样按行对上" \
		"boot=false recovery=false misc=false rootfs=true rootfs_rw=false data=false " \
		"${sparse_flags}"
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
check_eq "CV 打包链读取跨行 sector 表的全部偏移" "${off_new}" "$(drive_offsets "${WORK}/wrapped_sector.xml")"
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

echo "== D2. SE7 KiB 打包链（script/bm1684） =="
# SE7 用的是另一条打包链：script/bm1684/bm_make_package.sh，只认 size_in_kb。
# 它的分区解析同样按行读属性，且属性缺失时不能错位到相邻分区（老包兼容）。
PKG1684_SH="${SOCBAK_DIR}/script/bm1684/bm_make_package.sh"
drive_offsets_1684() { # <xml>
	(
		set +u
		# shellcheck source=/dev/null
		source "${PKG1684_SH}" >/dev/null 2>&1
		PARTITION_FILE="$1"
		parse_partition_xml
		for i in "${!LABELS[@]}"; do
			printf '%s start=%s sectors=%s bytes=%s ro=%s fmt=%s\n' \
				"${LABELS[$i]}" "${PART_OFFSET[$i]}" "${PART_SIZE_IN_SECTOR[$i]}" \
				"${PART_SIZE_IN_BYTE[$i]}" "${P_FLAG[$i]}" "${PART_FORMAT[$i]}"
		done
	)
}
off7_1684="$(drive_offsets_1684 "${WORK}/se7_default_kib.xml")"
check_eq "SE7 打包链读取跨行 KiB 表的全部偏移" "${off7_1684}" "$(drive_offsets_1684 "${WORK}/wrapped_kib.xml")"
check_ne "SE7 KiB 打包链能读到分区偏移" "" "${off7_1684}"
# 与 KiB XML 自身的期望值逐分区对照（起止 LBA、字节数、只读位、format）
check_eq "SE7 KiB 打包链的起止/字节/只读位/format 与 XML 一致" \
	"$(socbak_xml_partition_rows "${WORK}/se7_default_kib.xml" |
		awk -F'|' 'BEGIN{o=8192}
			{printf "%s start=%d sectors=%d bytes=%d ro=%s fmt=%s\n",
				tolower($1), o, $2*1024/512, $2*1024, $3, $4; o += $2*1024/512}')" \
	"${off7_1684}"
# 老包兼容：省略 readonly 的 KiB 行不能让只读位错位到相邻分区
cat > "${WORK}/se7_sparse_attr_kib.xml" <<'XML'
<physical_partition size_in_kb="20971520">
  <partition label="BOOT"       size_in_kb="131072"  format="1" />
  <partition label="RECOVERY"   size_in_kb="3145728"  readonly="false" format="2" />
  <partition label="MISC"       size_in_kb="10240"  readonly="false"   format="0" />
  <partition label="ROOTFS"     size_in_kb="2621440" readonly="true"   format="2" />
  <partition label="ROOTFS_RW"  size_in_kb="6291456" readonly="false"  format="2" />
  <partition label="OPT"        size_in_kb="2097152" readonly="false"  format="2" />
  <partition label="DATA"       size_in_kb="4194304" readonly="false"  format="2" />
</physical_partition>
XML
check_eq "老 KiB 表省略 readonly 时只读位不错位" \
	"boot=false recovery=false misc=false rootfs=true rootfs_rw=false opt=false data=false" \
	"$(drive_offsets_1684 "${WORK}/se7_sparse_attr_kib.xml" |
		sed -E 's/^([^ ]+) .* ro=([a-z]+) fmt=.*$/\1=\2/' | paste -sd' ' -)"
check_eq "省略 readonly 的 KiB 表偏移与完整表一致" \
	"$(drive_offsets_1684 "${WORK}/se7_default_kib.xml" | sed -E 's/ ro=.*//')" \
	"$(drive_offsets_1684 "${WORK}/se7_sparse_attr_kib.xml" | sed -E 's/ ro=.*//')"

echo "== E. 固定 DATA 起点补偿 =="
# 与旧实现逐字对应：扩容时把差额还给 ROOTFS_RW，缩容时保留 200 MiB 余量。
# 结果通过全局变量返回（不是 stdout）——调用方必须在同一 shell 里取，
# 写成 X="$(...)" 会让失败差额留在子 shell 里。这里显式校验接口，
# 结果变量缺失（仍是旧的 stdout 契约）就报出来，不能静默放过。
fds_rw() {
	socbak_fixed_data_start_rw "$1" "$2" "$3" || return 1
	echo -n "${SOCBAK_FIXED_DATA_START_RW_KB:-<接口缺失:未设置结果变量>}"
}
check_eq "无变化时 ROOTFS_RW 不变" "6291456" "$(fds_rw 6291456 6291456 6291456)"
check_eq "其他分区缩小时 ROOTFS_RW 变大" "6737856" "$(fds_rw 7000000 6553600 6291456)"
check_eq "其他分区扩大时 ROOTFS_RW 变小" "5737856" "$(fds_rw 6000000 6553600 6291456)"
if fds_rw 6000000 6553600 700000 >/dev/null; then
	bad "ROOTFS_RW 不足以补偿时报错" "没有报错"
else
	ok "ROOTFS_RW 不足以补偿时报错"
	check_eq "报错时给出需要的差额（含 200 MiB 余量）" "758400" "${SOCBAK_FIXED_DATA_START_DIFF_KB}"
fi

# 按 socbak.sh 的实际调用方式复现：从 socbak.sh 里原样抽出 SOC_BAK_FIXED_DATA_START
# 的补偿块执行（不是在这里重写一份），这样「把结果放进命令替换再读差额」这类写法会被真实抓到。
# 旧实现写成 X="$(socbak_fixed_data_start_rw ...)"：失败差额留在子 shell，
# set -u 下父 shell 只报 unbound variable，真正的原因（差 758400 KiB）丢失。
SOCBAK_SH="${SOCBAK_DIR}/socbak.sh"
FDS_START_LINE=$(grep -n '^if \[\[ "${SOC_BAK_FIXED_DATA_START}" != "" \]\]; then$' "${SOCBAK_SH}" |
	awk -F: '$1 > 700 {print $1; exit}')
FDS_END_LINE=$(grep -n 'INFO: rootfs_rw size change to' "${SOCBAK_SH}" | awk -F: '$1 > 700 {print $1; exit}')
# 补偿块以 if 开始，其后第一个顶格 fi 结束（echo 之后还有一行 fi）
if [ -n "${FDS_END_LINE}" ]; then
	FDS_END_LINE=$(awk -v s="${FDS_END_LINE}" 'NR >= s && $0 == "fi" {print NR; exit}' "${SOCBAK_SH}")
fi
if [ -z "${FDS_START_LINE}" ] || [ -z "${FDS_END_LINE}" ] || [ "${FDS_END_LINE}" -le "${FDS_START_LINE}" ]; then
	bad "从 socbak.sh 抽出固定 DATA 起点补偿块" "定位不到 ${SOCBAK_SH} 里的补偿块"
else
	sed -n "${FDS_START_LINE},${FDS_END_LINE}p" "${SOCBAK_SH}" > "${WORK}/fds_block.sh"
	ok "从 socbak.sh 抽出固定 DATA 起点补偿块（${FDS_START_LINE}-${FDS_END_LINE}）"
	# 用真实生产块跑：set -u 与 socbak.sh 的运行方式一致；参数取自验收复现值。
	# 每个用例都在干净的子 shell 里跑，并先清掉补偿函数的全局结果变量 ——
	# 否则上面用同一函数跑出来的差额会留在环境里，把「父 shell 读不到差额」这个缺陷掩盖掉。
	run_fds_block() { # <no_data_kb> <no_data_new_kb> <rootfs_rw_kb>
		(
			set -u
			# shellcheck source=/dev/null
			source "${PT_SH}"
			unset SOCBAK_FIXED_DATA_START_DIFF_KB SOCBAK_FIXED_DATA_START_RW_KB
			SOC_BAK_FIXED_DATA_START=1
			PARTITIONS_SIZE_NO_DATA_KB="$1"
			# socbak.sh 进入补偿块前把累计变量清零，这里补上同一初值
			PARTITIONS_SIZE_NO_DATA_NEW_KB=0
			ROOTFS_RW_SIZE="$3"
			# 块内用 TGZ_FILES 累加其它分区：这里把差额放进 data 之外的一个分区，
			# 使 PARTITIONS_SIZE_NO_DATA_NEW_KB 与块外一致地等于 $2
			TGZ_FILES=(boot recovery rootfs opt system data)
			declare -A TGZ_FILES_SIZE=(
				[boot]=0 [recovery]=0 [rootfs]=0 [opt]=0 [system]=0 [data]=0)
			TGZ_FILES_SIZE["opt"]=$(( $2 - $3 ))
			# shellcheck source=/dev/null
			source "${WORK}/fds_block.sh"
			echo "RESULT:${ROOTFS_RW_SIZE}"
		) 2>&1
	}
	fds_bad_out="$(run_fds_block 6000000 6553600 700000)"
	fds_bad_rc=$?
	check_eq "生产块：空间不足时非零退出" "1" "${fds_bad_rc}"
	check_eq "生产块：报差错因为空间不足（不是 unbound variable）" "1" \
		"$(echo "${fds_bad_out}" | grep -c 'Insufficient space in rootfs_rw')"
	check_eq "生产块：报出差额 758400 KiB" "1" \
		"$(echo "${fds_bad_out}" | grep -c 'DIFF_SIZE:758400')"
	check_eq "生产块：不出现 unbound variable" "0" \
		"$(echo "${fds_bad_out}" | grep -ci 'unbound variable')"
	# 余量足够时必须走通：差值 553600 < ROOTFS_RW 6291456，结果 5737856
	fds_ok_out="$(run_fds_block 6000000 6553600 6291456)"
	fds_ok_rc=$?
	check_eq "生产块：余量足够时正常结束" "0" "${fds_ok_rc}"
	check_eq "生产块：余量足够时 ROOTFS_RW 调为 5737856 KiB" "1" \
		"$(echo "${fds_ok_out}" | grep -c 'INFO: rootfs_rw size change to 5737856 KiB')"
fi

# 补偿后 DATA 起点在两种单位下都是同一个扇区。
# DATA 起点 = 8192 + DATA **之前所有分区** 的长度之和（不能用 DATA 自己的长度算）。
data_start_before() { # <xml> <per_kib_sectors>
	local xml="$1" per="$2"
	socbak_xml_partition_rows "${xml}" |
		awk -F'|' -v per="${per}" 'BEGIN{s=8192}
			$1=="DATA"{print s; exit}
			{s += $2 * per}'
}
emit_pair fds "${LAYOUT_TOTAL_KIB}" "${LAYOUT_ROWS_NO_OPT[@]}"
rw_kib="$(fds_rw 6291456 6553600 6291456)"
check_ne "补偿后的 ROOTFS_RW 仍然可算" "" "${rw_kib}"
data_start_kib="$(data_start_before "${WORK}/fds_kib.xml" 2)"
data_start_sec="$(data_start_before "${WORK}/fds_sector.xml" 1)"
check_eq "等价布局下 DATA 起始扇区一致" "${data_start_kib}" "${data_start_sec}"
# 夹具交叉核对：六分区布局的 DATA 起点必须是 8192 + 前五个分区（不是 DATA 自身长度）
check_eq "DATA 起点按 DATA 之前所有分区计算" \
	"$(( 8192 + (131072 + 131072 + 10240 + 3145728 + 9291456) * 2 ))" \
	"${data_start_sec}"

echo "== G. 分发包完整性校验的加载顺序 =="
# socbak_md5.txt 覆盖的脚本不能在 md5 校验通过之前被 source：
# 先 source 后校验等于对分发包里的脚本不做校验（校验的正是它自己）。
# 这里对 socbak.sh 里的行号顺序做静态断言，因为顺序本身就是契约；
# 另跑一次篡改分发包的负向用例，确认校验确实能拦住被改过的 partition_table.sh。
MD5_LINE=$(grep -n 'md5sum -c "${TGZ_FILES_PATH}/socbak_md5.txt"' "${SOCBAK_SH}" | cut -d: -f1)
SRC_LINE=$(grep -n '^source "${TGZ_FILES_PATH}/script/partition_table.sh"' "${SOCBAK_SH}" | cut -d: -f1)
check_ne "socbak.sh 里有 md5 校验" "" "${MD5_LINE}"
check_ne "socbak.sh 里有对 partition_table.sh 的 source" "" "${SRC_LINE}"
if [ -n "${MD5_LINE}" ] && [ -n "${SRC_LINE}" ] && [ "${MD5_LINE}" -lt "${SRC_LINE}" ]; then
	ok "md5 校验在 source partition_table.sh 之前（${MD5_LINE} < ${SRC_LINE}）"
else
	bad "md5 校验在 source partition_table.sh 之前" "md5=${MD5_LINE} source=${SRC_LINE}"
fi
# 被 source 的脚本必须在清单里，否则「校验通过」不代表它被校验过
check_eq "socbak_md5.txt 收录了 partition_table.sh" "1" \
	"$(grep -c 'script/partition_table.sh' "${SOCBAK_DIR}/socbak_md5.txt")"

echo "== H. GPT 临时文件独享 =="
# sector GPT 要在一份整盘大小的稀疏文件上建表，再用临时文件截取主 GPT。
# 这个临时文件必须每次调用独享：用 $$ 拼名字时同一脚本的并发调用会互相覆盖
# （一个调用正在读，另一个已经 rm/truncate），异常清理也会误删别的调用的文件。
# 这里并发跑 12 次（两种布局交替），要求每个产物都是合法 GPT，且 TEMPDIR 里不留残留。
if [ "${HAS_SGDISK}" = "1" ]; then
	CONC_TMP="${WORK}/conctmp"
	rm -rf "${CONC_TMP}"; mkdir -p "${CONC_TMP}"
	cat > "${WORK}/conc.xml.a" <<'XML'
<physical_partition size_in_sectors="35943040">
  <partition label="BOOT"       size_in_sectors="262144"  readonly="false"  format="1" />
  <partition label="DATA"       size_in_sectors="8388608" readonly="false"  format="2" />
</physical_partition>
XML
	cat > "${WORK}/conc.xml.b" <<'XML'
<physical_partition size_in_sectors="35943040">
  <partition label="BOOT"       size_in_sectors="262144"  readonly="false"  format="1" />
  <partition label="DATA"       size_in_sectors="4194304" readonly="false"  format="2" />
</physical_partition>
XML
	(
		export TMPDIR="${CONC_TMP}"
		pids=()
		for i in $(seq 1 12); do
			if [ $(( i % 2 )) -eq 0 ]; then
				socbak_gen_gpt "${WORK}/conc.xml.a" "${WORK}/conc_$i.gpt" >/dev/null 2>&1 &
			else
				socbak_gen_gpt "${WORK}/conc.xml.b" "${WORK}/conc_$i.gpt" >/dev/null 2>&1 &
			fi
			pids+=($!)
		done
		conc_fail=0
		for p in "${pids[@]}"; do wait "${p}" || conc_fail=$(( conc_fail + 1 )); done
		echo "${conc_fail}" > "${WORK}/conc_fail"
	)
	check_eq "并发 12 次 GPT 生成全部成功" "0" "$(cat "${WORK}/conc_fail")"
	# 每份产物都必须是完整的主 GPT：头签名有效、末分区结束 LBA 与本布局一致
	check_eq "并发 12 份产物都是合法主 GPT" "12" \
		"$(for f in "${WORK}"/conc_*.gpt; do
			gpt_summary x "${f}" | grep -q '^hdr ' && printf 'ok\n'
		done | wc -l)"
	check_eq "并发调用不留临时文件" "0" "$(ls -A "${CONC_TMP}" | wc -l)"
else
	echo "  skip GPT 临时文件并发隔离（环境里没有 sgdisk）"
fi

echo "== F. CV84×6 SDK 夹具核查（SE13） =="
SDK_XML="${SOCBAK_SDK_SECTOR_XML:-}"
if [ -z "${SDK_XML}" ]; then
	for c in \
		"${SOCBAK_DIR}/../../../cv84x2/build/scripts/partition32G_sector.xml" \
		/opt/sophgo/cv84x6/build/scripts/partition32G_sector.xml; do
		[ -f "${c}" ] && { SDK_XML="${c}"; break; }
	done
fi
if [ -z "${SDK_XML}" ]; then
	echo "  skip 未提供 CV84×6 SDK 的 partition32G_sector.xml（可用 SOCBAK_SDK_SECTOR_XML 指定）"
elif [ ! -f "${SDK_XML}" ]; then
	bad "读取指定的 CV84×6 SDK 夹具" "${SDK_XML} 文件不存在"
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
	# 明确提供了 SDK 夹具（SOCBAK_SDK_SECTOR_XML 或自动探测到）就必须真的验完：
	# 缺 sgdisk 或生成失败都要记失败，不能悄悄 skip 掉 —— 那是唯一覆盖 SE13 真布局的项。
	if [ "${HAS_SGDISK}" = "0" ]; then
		bad "SDK 夹具可生成 GPT" "环境里没有 sgdisk"
	elif socbak_gen_gpt "${SDK_XML}" "${WORK}/sdk.gpt"; then
		ok "SDK 夹具可生成 GPT"
		lba=8192
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
		bad "SDK 夹具可生成 GPT" "socbak_gen_gpt 对 ${SDK_XML} 返回非 0"
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
