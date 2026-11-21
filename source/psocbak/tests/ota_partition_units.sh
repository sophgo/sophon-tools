#!/bin/bash
# ota_update 生产预检的分区表单位兼容性回归（MYS-2981 / MYS-2982）
#
# 背景：socbak v1.5.0 起 SE9/SE13 的刷机包改用 sector 分区表；SE7 仍是 KiB。
# ota_update v1.5.8 已按 `size_in_sectors` 识别单位并 ÷2 折算成 KiB，
# 本脚本验证同一份字节布局在两种写法下，**生产预检代码本身**得出相同结论：
#   - 只找到 1 个 partition*xml
#   - 换算后的总容量、分区合计、GPT 末端容量一致（不会出现两倍容量误判）
#   - 保留末分区的匹配 / 不匹配判定正确
#
# 做法：从 source/pota_update/ota.sh 里原样抽出预检块（"check update size check start"
# 到 "check update size check success" 之间），在隔离的假包里执行。抽出的块是产线代码，
# 不在这里重写、不改动，所以测的就是发布出去的那份逻辑。
#
# 用法（仓库根）：
#   bash source/psocbak/tests/ota_partition_units.sh
#
# 依赖：gdisk / sgdisk / bc（x86 主机装 gptfdisk + bc 即可）。
# 边界：不写任何块设备，不触发 OTA 的写盘流程，只跑预检。
set -u

TESTS_SRC_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO_ROOT="$(cd "${TESTS_SRC_DIR}/../../.." && pwd)"
OTA_SH="${REPO_ROOT}/source/pota_update/ota.sh"
PT_SH="${REPO_ROOT}/source/psocbak/socbak/script/partition_table.sh"

[ -f "${OTA_SH}" ] || { echo "ERROR: 找不到 ${OTA_SH}" >&2; exit 2; }
[ -f "${PT_SH}" ] || { echo "ERROR: 找不到 ${PT_SH}" >&2; exit 2; }

for t in gdisk bc python3; do
	command -v "${t}" >/dev/null 2>&1 || { echo "ERROR: 需要 ${t}" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
PASS=0
FAIL=0
FAILED_NAMES=()
ok()  { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); printf '  FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check_eq() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expect [$2] got [$3]"; fi; }

# shellcheck source=/dev/null
source "${PT_SH}"
export TGZ_FILES_PATH="${REPO_ROOT}/source/psocbak/socbak"

# ---------------------------------------------------------------- 抽预检块
START_LINE=$(grep -n 'check update size check start' "${OTA_SH}" | head -n1 | cut -d: -f1)
END_LINE=$(grep -n 'check update size check success' "${OTA_SH}" | head -n1 | cut -d: -f1)
if [ -z "${START_LINE}" ] || [ -z "${END_LINE}" ] || [ "${END_LINE}" -le "${START_LINE}" ]; then
	echo "ERROR: 在 ${OTA_SH} 里定位不到预检块" >&2
	exit 2
fi
# 预检块本身（含起止两行）
sed -n "${START_LINE},${END_LINE}p" "${OTA_SH}" > "${WORK}/precheck_block.sh"
if ! grep -q 'size_in_sectors' "${WORK}/precheck_block.sh"; then
	echo "ERROR: 预检块里没有 size_in_sectors 处理，ota.sh 结构可能已变化" >&2
	exit 2
fi
echo "  预检块：ota.sh:${START_LINE}-${END_LINE}"

# ---------------------------------------------------------------- 假包生成
# 用生产的分区表写出函数造等价的两份 XML，再各自配一份真实的主 GPT。
R="0x00000001"
GPU_ARGS_COMMON=(--total 20971520)

emit_both() { # <tag> <total_kib> <rows...>
	local tag="$1" total="$2"
	shift 2
	socbak_emit_partition_xml "${WORK}/${tag}_kib.xml" 0 "${total}" "$@"
	socbak_emit_partition_xml "${WORK}/${tag}_sector.xml" 1 "${total}" "$@"
}

build_pkg() { # <pkg dir> <xml> [pkg xml 文件名]
	local dir="$1" xml="$2"
	local name="${3:-$(basename "${xml}")}"
	rm -rf "${dir}"; mkdir -p "${dir}"
	# 预检用 find ./ -name "partition*xml" 找唯一分区表，文件名必须符合产物的命名
	case "${name}" in
		partition*xml) ;;
		*) name="partition32G_$(echo "${name}" | tr -c 'a-zA-Z0-9\n' '_').xml" ;;
	esac
	cp "${xml}" "${dir}/${name}"
	if ! socbak_gen_gpt "${xml}" "${dir}/gpt.raw"; then
		return 1
	fi
	gzip -c "${dir}/gpt.raw" > "${dir}/gpt.gz" && rm -f "${dir}/gpt.raw"
	# 预检扫描 *.scr 里的 mmc write 计算最大写偏移；给出一份与 GPT 一致的写入记录
	make_writes "${xml}" > "${dir}/boot_emmc.scr"
	: > "${dir}/md5.txt"
}

# 按 XML 生成与打包链同等规则的 mmc write 行。
# 关键：boot_emmc-*.cmd 里的偏移永远是扇区，与 XML 用什么单位无关 ——
# 打包链会把 XML 的数值换算成扇区。所以这里对 KiB 版要 ×2，
# 这样两个等价布局产出的 .scr 必须完全相同（预检读 .scr 算最大写偏移）。
make_writes() { # <xml>
	local xml="$1"
	local lba=8192 label size ro fmt per_sector
	per_sector=1
	grep -q 'size_in_kb=' "${xml}" && per_sector=2
	while IFS='|' read -r label size ro fmt; do
		[ -n "${label}" ] || continue
		size=$(( size * per_sector ))
		printf 'mmc write ${unzip_addr} 0x%08x 0x%08x\n' "${lba}" "${size}"
		lba=$(( lba + size ))
	done < <(socbak_xml_partition_rows "${xml}")
}

# 假 lsblk：OTA 预检用 `lsblk -b | grep '^mmcblk0' | head -n1` 取整盘字节数。
# 取两台真机的实际容量（SE9 31268536320 B，SE7 61865984000 B），
# 这样「包容量 < emmc 容量」的判定与真机一致，不会因为夹具凑巧相等而误触发容量告警。
mkdir -p "${WORK}/stub"
cat > "${WORK}/stub/lsblk" <<'EOF'
#!/bin/sh
# 只模拟 OTA 预检需要的那一行：mmcblk0 的整盘字节数
if [ "$1" = "-l" ]; then
	echo "mmcblk0"
else
	echo "mmcblk0      179:0    0 ${FAKE_EMMC_BYTES}  0 disk"
fi
EOF
chmod +x "${WORK}/stub/lsblk"

# 假 gdisk：预检用 `gdisk -l /dev/mmcblk0` 取当前设备末分区起点。
# 这里模拟两台板子的真实布局（与真机 gdisk 输出同格式），不接触任何块设备。
cat > "${WORK}/stub/gdisk" <<'EOF'
#!/bin/sh
# 只模拟 `gdisk -l /dev/mmcblk0`：末分区 = DATA，起点取自 FAKE_DEV_DATA_START
if [ "$1" = "-l" ] && [ "$2" = "/dev/mmcblk0" ]; then
	cat <<EOT
Number  Start (sector)    End (sector)  Size       Code  Name
   1            8192          270335   128.0 MiB   0700  BOOT
   5        13135872        25427327   5.9 GiB     0700  ROOTFS_RW
   6        ${FAKE_DEV_DATA_START}        61071326   17.0 GiB    0700  DATA
EOT
	exit 0
fi
# 其余调用（预检里的 OTA_GPT_TEMP_DISK_FILE）走真 gdisk
exec /usr/bin/gdisk "$@"
EOF
chmod +x "${WORK}/stub/gdisk"

# 预检块依赖的外部环境（与 ota.sh 里同名变量/函数保持一致）。
# 生产预检块把 GPT 临时文件固定写成 /dev/shm/ota_gpt 与 /dev/shm/ota_gpt.disk（不改生产代码），
# 直接在本机跑会和同机上其他 socbak/OTA 任务互相覆盖，还会把一份整盘大小的稀疏副本
# 留在共享 /dev/shm 里。所以每次预检都在私有挂载命名空间内执行，并给 /dev/shm 挂一份
# 本次独享的 tmpfs：隔离由内核保证，随命名空间退出自动消失，异常退出也不会碰到别处的文件。
if ! unshare -rm --propagation private true >/dev/null 2>&1; then
	echo "ERROR: 需要 unshare -rm（私有挂载命名空间）来隔离预检块的 /dev/shm/ota_gpt" >&2
	echo "ERROR: 不在共享 /dev/shm 上跑预检，避免覆盖其他任务的临时文件" >&2
	exit 2
fi

cat > "${WORK}/precheck_runner.sh" <<'RUNNER'
#!/bin/bash
# 在私有挂载命名空间里执行抽出的生产预检块
# 参数：<pkg dir> <stub dir> <precheck block> <dev data start> <emmc bytes>
set -u
dir="$1"
STUB_DIR="$2"
BLOCK="$3"
export PATH="${STUB_DIR}:${PATH}"
export FAKE_DEV_DATA_START="$4"
export FAKE_EMMC_BYTES="$5"
cd "${dir}" || exit 1
LOGFILE="${dir}/ota_precheck.log"
EMMC_SECTOR_B=512
LAST_PART_NOT_FLASH=1
panic() { echo "[PANIC] $*"; exit 1; }
file_validate() {
	local f
	f="$(printf '%s\n' "$1" | head -1)"
	[ -r "${f}" ] || { echo "[PANIC] ${f} is not readable"; exit 1; }
}
# shellcheck source=/dev/null
source "${BLOCK}"
RUNNER
chmod +x "${WORK}/precheck_runner.sh"

run_precheck() { # <pkg dir> <dev_data_start> [emmc_bytes]
	local dir="$1" dev_start="$2" emmc_bytes="${3:-31268536320}"
	unshare -rm --propagation private bash -c '
		mount -t tmpfs none /dev/shm || exit 1
		exec bash "$1" "$2" "$3" "$4" "$5" "$6"
	' _ "${WORK}/precheck_runner.sh" "${dir}" "${WORK}/stub" \
		"${WORK}/precheck_block.sh" "${dev_start}" "${emmc_bytes}" 2>/dev/null |
		grep -E '^\[(INFO|PANIC|WARRNING)\]'
}

# ---------------------------------------------------------------- 夹具
ROWS_SE9=(
	"BOOT|131072|false|1"
	"RECOVERY|131072|false|2"
	"MISC|10240|false|0"
	"ROOTFS|3145728|true|2"
	"ROOTFS_RW|9291456|false|2"
	"DATA|4194304|false|2"
)
ROWS_SE7=(
	"BOOT|131072|false|1"
	"RECOVERY|3145728|false|2"
	"MISC|10240|false|0"
	"ROOTFS|2621440|true|2"
	"ROOTFS_RW|6291456|false|2"
	"OPT|2097152|false|2"
	"DATA|4194304|false|2"
)

echo "== A. SE9 等价布局：KiB 包 vs sector 包 =="
emit_both se9 20971520 "${ROWS_SE9[@]}"
# 与设备真实布局对齐的 DATA 起点（SE9 真机为 25427328）
se9_data_start=$(( 8192 + 131072*2 + 131072*2 + 10240*2 + 3145728*2 + 9291456*2 ))
build_pkg "${WORK}/pkg_se9_kib" "${WORK}/se9_kib.xml" || { echo "ERROR: 造包失败" >&2; exit 2; }
build_pkg "${WORK}/pkg_se9_sector" "${WORK}/se9_sector.xml" || { echo "ERROR: 造包失败" >&2; exit 2; }

out_kib="$(run_precheck "${WORK}/pkg_se9_kib" "${se9_data_start}")"
out_sec="$(run_precheck "${WORK}/pkg_se9_sector" "${se9_data_start}")"

echo "  --- KiB 包 ---"; echo "${out_kib}" | sed 's/^/    /'
echo "  --- sector 包 ---"; echo "${out_sec}" | sed 's/^/    /'

for tag in kib sec; do
	eval "o=\${out_${tag}}"
	check_eq "SE9/${tag}: 预检通过（无 PANIC）" "0" "$(echo "${o}" | grep -c '\[PANIC\]')"
	check_eq "SE9/${tag}: 只找到唯一 XML" "1" "$(echo "${o}" | grep -c 'check update size check start')"
done

# 关键数值必须一致：容量换算没有两倍误判
extract() { echo "$1" | grep -F "$2" | head -n1 | sed 's/^\[INFO\] //'; }
for key in "update need size:" "emmc size:" "write all max offset:"; do
	check_eq "SE9: ${key} 两种单位一致" \
		"$(extract "${out_kib}" "${key}")" "$(extract "${out_sec}" "${key}")"
done

check_eq "SE9: 保留末分区判定一致（匹配）" \
	"$(echo "${out_kib}" | grep -c 'LAST_PART_NOT_FLASH mode, check last part start .* = ')1" \
	"$(echo "${out_sec}" | grep -c 'LAST_PART_NOT_FLASH mode, check last part start .* = ')1"

echo "== B. 保留末分区：起点不匹配必须被拦下 =="
out_kib_bad="$(run_precheck "${WORK}/pkg_se9_kib" "$(( se9_data_start + 2048 ))")"
out_sec_bad="$(run_precheck "${WORK}/pkg_se9_sector" "$(( se9_data_start + 2048 ))")"
check_eq "SE9/KiB: 起点不匹配被拦下" "1" \
	"$(echo "${out_kib_bad}" | grep -c 'check last part start .* != ')"
check_eq "SE9/sector: 起点不匹配被拦下" "1" \
	"$(echo "${out_sec_bad}" | grep -c 'check last part start .* != ')"
check_eq "SE9: 不匹配时两种单位报同一个错误" \
	"$(echo "${out_kib_bad}" | grep -o 'check last part start .*' | head -n1)" \
	"$(echo "${out_sec_bad}" | grep -o 'check last part start .*' | head -n1)"

echo "== C. SE7（KiB）等价布局：仍按 KiB 口径 =="
emit_both se7 20971520 "${ROWS_SE7[@]}"
se7_data_start=$(( 8192 + 131072*2 + 3145728*2 + 10240*2 + 2621440*2 + 6291456*2 + 2097152*2 ))
build_pkg "${WORK}/pkg_se7_kib" "${WORK}/se7_kib.xml" || { echo "ERROR: 造包失败" >&2; exit 2; }
build_pkg "${WORK}/pkg_se7_sector" "${WORK}/se7_sector.xml" || { echo "ERROR: 造包失败" >&2; exit 2; }
out7_kib="$(run_precheck "${WORK}/pkg_se7_kib" "${se7_data_start}")"
out7_sec="$(run_precheck "${WORK}/pkg_se7_sector" "${se7_data_start}")"
check_eq "SE7: 两种单位预检结论一致" \
	"$(echo "${out7_kib}" | grep -E 'update need size:|LAST_PART_NOT_FLASH mode, check last part start')" \
	"$(echo "${out7_sec}" | grep -E 'update need size:|LAST_PART_NOT_FLASH mode, check last part start')"

echo "== D. 误用单位必须被识别（不做隐式猜测） =="
# sector 数值写成 KiB 属性：OTA 会当成 2 倍容量，但不会 panic，属于使用方的错误标注，
# 这里只确认脚本确实按属性名判单位，而不是按数值大小猜。
sed 's/size_in_sectors/size_in_kb/g' "${WORK}/se9_sector.xml" > "${WORK}/mislabeled.xml"
build_pkg "${WORK}/pkg_mislabel" "${WORK}/mislabeled.xml" || { echo "ERROR: 造包失败" >&2; exit 2; }
out_mis="$(run_precheck "${WORK}/pkg_mislabel" "${se9_data_start}")"
need_kib="$(extract "${out_kib}" 'update need size:')"
need_mis="$(extract "${out_mis}" 'update need size:')"
if [ "${need_mis}" != "${need_kib}" ]; then
	ok "按属性名判单位：同数值改成 KiB 属性后容量翻倍（不是悄悄兼容）"
else
	bad "按属性名判单位" "两种标注得到相同容量，说明单位判断没生效"
fi

echo "== E. 三份 OTA 脚本一致性 =="
for other in \
	"${REPO_ROOT}/source/pbmssm/pkg/ota/assets/ota.sh" \
	"${REPO_ROOT}/source/psocbak/socbak/script/ota_update/ota_update.sh"; do
	if [ -f "${other}" ]; then
		if cmp -s "${OTA_SH}" "${other}"; then
			ok "与 $(echo "${other}" | sed "s|${REPO_ROOT}/||") 逐字节相同"
		else
			bad "与 $(echo "${other}" | sed "s|${REPO_ROOT}/||") 逐字节相同" "内容不同"
		fi
	else
		bad "$(echo "${other}" | sed "s|${REPO_ROOT}/||") 存在" "文件不存在"
	fi
done

echo
if [ "${FAIL}" -eq 0 ]; then
	echo "PASS ${PASS}/${PASS}"
	exit 0
fi
echo "FAIL ${FAIL}（共 $((PASS + FAIL)) 项）"
for n in "${FAILED_NAMES[@]}"; do echo "  - ${n}"; done
exit 1
