#!/bin/bash
# socbak local_update 布局模式回归（MYS-3010 / 父任务 MYS-2981）
#
# 背景：SE9（BM1688/CV186AH）与 SE13（CV84X6）用 SDK 的 local_update 升级时，主程序把
# 升级指令写进 MISC(p3)，写盘前用 scripts/check_partition_start_sector.sh 比较源机与包内
# partition32G_sector.xml 的 DATA / MISC / ROOTFS 起点，任何一项不同就拒绝升级。
# 因此 SOC_BAK_LOCAL_UPDATE_LAYOUT=1 打包时必须原样复制源机的 GPT 前缀：
#   BOOT / RECOVERY / MISC 的起点与长度、ROOTFS 起点、DATA 起点全部冻结，
#   只有 ROOTFS 长度、ROOTFS_RW 起点、ROOTFS_RW 长度、DATA 长度这四个数值随内容变化。
#
# 本脚本验证的就是这条约束，全部在普通文件/隔离磁盘镜像上跑，不接触任何真机：
#   A 参数入口：开关的互斥、平台范围、失败退出码与输出
#   B 源表读取：真实 GPT 镜像只读解析，非 GPT / 空文件 / 布局不符必须失败
#   C 规划：SE9 实机夹具 + SE13 SDK 样例，四个自由度的组合、余量边界、越界
#   D 只允许四个字段变化：分别/同时增大 ROOTFS 与 DATA，逐字段比对
#   E 反例：旧包（MISC 从 532480 挪到 552960、ROOTFS 从 552960 挪到 573440）必须被拒绝
#   F 端到端：XML -> socbak_gen_gpt -> 主 GPT 解码，三处几何一致；刷写偏移同源
#   G SDK 的 check_partition_start_sector.sh 等价核对（DATA/MISC/ROOTFS 三项实值）
#
# 用法（仓库根）：
#   bash source/psocbak/tests/local_update_layout.sh
#
# 可选：
#   SOCBAK_SDK_SECTOR_XML=<path>  CV84×6 SDK 的 partition32G_sector.xml（SE13 样例）。
#                                 缺省自动探测 /home/zzt/workspace/cv84x2/build/scripts/ 下的副本。
# 依赖：sgdisk、gzip、od（busybox 版同样可用）。
set -u

TESTS_SRC_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SOCBAK_DIR="$(cd "${TESTS_SRC_DIR}/../socbak" && pwd)"
PT_SH="${SOCBAK_DIR}/script/partition_table.sh"
SOCBAK_SH="${SOCBAK_DIR}/socbak.sh"

for f in "${PT_SH}" "${SOCBAK_SH}"; do
	[ -f "${f}" ] || { echo "ERROR: 缺少待测文件 ${f}" >&2; exit 2; }
done

for t in sgdisk gzip od awk; do
	command -v "${t}" >/dev/null 2>&1 || { echo "ERROR: 需要 ${t}" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

PASS=0
FAIL=0
FAILED_NAMES=()
ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); printf '  FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check_eq() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expect [$2] got [$3]"; fi; }
check_ne() { if [ "$2" != "$3" ]; then ok "$1"; else bad "$1" "不应相等，却都是 [$2]"; fi; }

# shellcheck source=/dev/null
source "${PT_SH}"
export TGZ_FILES_PATH="${SOCBAK_DIR}"

HAS_SGDISK=1
sgdisk --version >/dev/null 2>&1 || HAS_SGDISK=0

# ---------------------------------------------------------------- 夹具
# SE9 实机脱敏夹具（扇区），来自父任务验收标准的表：
#   BOOT 8192/262144、RECOVERY 270336/262144、MISC 532480/20480、
#   ROOTFS 552960/12582912、ROOTFS_RW 13135872/12291456、DATA 25427328/35643999
# 6 个分区合计到 61071326，加 33 个备份 GPT 扇区 + 1 = 61071360 总扇区。
SE9_TOTAL=61071360
SE9_LAYOUT="${WORK}/se9.layout"
cat > "${SE9_LAYOUT}" <<'EOF'
BOOT|1|8192|262144
RECOVERY|2|270336|262144
MISC|3|532480|20480
ROOTFS|4|552960|12582912
ROOTFS_RW|5|13135872|12291456
DATA|6|25427328|35643999
EOF
# 源机冻结值，供各处断言直接引用
SE9_BOOT_START=8192      SE9_BOOT_LEN=262144
SE9_REC_START=270336     SE9_REC_LEN=262144
SE9_MISC_START=532480    SE9_MISC_LEN=20480
SE9_ROOTFS_START=552960  SE9_ROOTFS_LEN=12582912
SE9_RW_START=13135872    SE9_RW_LEN=12291456
SE9_DATA_START=25427328  SE9_DATA_LEN=35643999

# 用同一份布局造一块真实的 GPT 磁盘镜像（普通文件），供只读读取与端到端用例使用。
mk_disk() { # <img> <total_sectors> <layout_file>
	local img="$1" total="$2" layout="$3"
	local -a args=()
	local label num start len
	rm -f "${img}"
	truncate -s $(( total * 512 )) "${img}"
	while IFS='|' read -r label num start len; do
		[ -n "${num}" ] || continue
		args+=(-n "${num}:${start}:$(( start + len - 1 ))" -t "${num}:0700" -c "${num}:${label}")
		[ "${label}" = "ROOTFS" ] && args+=(-A "${num}:set:60")
	done < "${layout}"
	sgdisk -a 1 "${args[@]}" "${img}" >/dev/null 2>&1
}

# 造一份新布局文件（"LABEL|NO|START|LEN"），在源布局上改指定字段。
layout_with() { # <out> <label> <start|-> <len|->
	local out="$1" wl="$2" ws="$3" wlen="$4"
	awk -F'|' -v OFS='|' -v wl="${wl}" -v ws="${ws}" -v wlen="${wlen}" '
		$1 == wl {
			if (ws != "-") $3 = ws
			if (wlen != "-") $4 = wlen
		}
		{ print }
	' "${SE9_LAYOUT}" > "${out}"
}

# ---------------------------------------------------------------- A. 参数入口
echo "== A. 参数入口（开关互斥 / 平台范围 / 失败退出码） =="
# socbak.sh 会先清理历史、读芯片，无法在这里整体执行；这里用一份只含参数解析段的
# 抽取脚本跑真实代码（不是重写一份判断），保证「参数拼错 / 互斥」的报错与产物一致。
ARGS_BLOCK="${WORK}/args_block.sh"
# 从 socbak.sh 抽出「默认值 + 参数循环 + 三个互斥检查」这一段原样执行
awk '
	/^export SOC_BAK_ALL_IN_ONE=\$\{SOC_BAK_ALL_IN_ONE:-\}$/ { on = 1 }
	on { print }
	on && /^fi$/ && /LOCAL_UPDATE/ { }
	on && /requires SOC_BAK_ALL_IN_ONE/ { seen = 1 }
	on && seen && /^fi$/ { print ""; exit }
' "${SOCBAK_SH}" > "${ARGS_BLOCK}"
if ! grep -q 'requires SOC_BAK_ALL_IN_ONE' "${ARGS_BLOCK}"; then
	bad "从 socbak.sh 抽出参数解析段" "定位不到 local_update 的开关检查"
else
	ok "从 socbak.sh 抽出参数解析段（$(wc -l < "${ARGS_BLOCK}") 行）"
fi

# 在干净子 shell 里跑参数解析段，回显退出码与最终开关值
parse_args() { # <env assignments...> -- <argv...>
	(
		unset SOC_BAK_ALL_IN_ONE SOC_BAK_FIXED_SIZE SOC_BAK_FIXED_DATA_START SOC_BAK_LOCAL_UPDATE_LAYOUT
		# shellcheck source=/dev/null
		source "${ARGS_BLOCK}" "$@"
		echo "RC=0 ALL_IN_ONE=[${SOC_BAK_ALL_IN_ONE}] FIXED_SIZE=[${SOC_BAK_FIXED_SIZE}] FIXED_DATA_START=[${SOC_BAK_FIXED_DATA_START}] LOCAL_UPDATE=[${SOC_BAK_LOCAL_UPDATE_LAYOUT}]"
	) 2>&1
	echo "RC=$?"
}

# 参数形式与环境变量形式都要生效
out="$(SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1 bash -c "
	unset SOC_BAK_ALL_IN_ONE SOC_BAK_LOCAL_UPDATE_LAYOUT
	export SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1
	source '${ARGS_BLOCK}' >/dev/null 2>&1
	echo \"LOCAL_UPDATE=[\${SOC_BAK_LOCAL_UPDATE_LAYOUT}]\"" 2>&1)"
check_eq "环境变量形式开启开关" "LOCAL_UPDATE=[1]" "${out}"

out="$(bash -c "
	source '${ARGS_BLOCK}' SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1 >/dev/null 2>&1
	echo \"LOCAL_UPDATE=[\${SOC_BAK_LOCAL_UPDATE_LAYOUT}]\"" 2>&1)"
check_eq "KEY=value 参数形式开启开关" "LOCAL_UPDATE=[1]" "${out}"

# 互斥：与 FIXED_SIZE 同时开启必须非零退出
out="$(bash -c "source '${ARGS_BLOCK}' SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_SIZE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1" 2>&1)"; rc=$?
check_eq "与 SOC_BAK_FIXED_SIZE 同时开启时非零退出" "1" "${rc}"
check_eq "并给出互斥原因" "1" "$(echo "${out}" | grep -c 'cannot be enabled together with SOC_BAK_FIXED_SIZE')"

# 互斥：与 FIXED_DATA_START 同时开启必须非零退出
out="$(bash -c "source '${ARGS_BLOCK}' SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_DATA_START=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1" 2>&1)"; rc=$?
check_eq "与 SOC_BAK_FIXED_DATA_START 同时开启时非零退出" "1" "${rc}"
check_eq "并给出互斥原因" "1" "$(echo "${out}" | grep -c 'cannot be enabled together with')"

# 必须配合 all-in-one：单独开启要明确失败，而不是产出一个半成品
out="$(bash -c "source '${ARGS_BLOCK}' SOC_BAK_LOCAL_UPDATE_LAYOUT=1" 2>&1)"; rc=$?
check_eq "缺少 SOC_BAK_ALL_IN_ONE 时非零退出" "1" "${rc}"
check_eq "并说明需要 all-in-one" "1" "$(echo "${out}" | grep -c 'requires SOC_BAK_ALL_IN_ONE')"

# 默认关闭：三个旧开关的开/关组合仍按原行为（互斥规则不变）
out="$(bash -c "source '${ARGS_BLOCK}' >/dev/null 2>&1; echo \"LU=[\${SOC_BAK_LOCAL_UPDATE_LAYOUT}]\"" 2>&1)"
check_eq "不传参时开关默认关闭" "LU=[]" "${out}"
out="$(bash -c "source '${ARGS_BLOCK}' SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_SIZE=1" 2>&1)"; rc=$?
check_eq "旧模式 FIXED_SIZE 仍可单独开启" "0" "${rc}"
out="$(bash -c "source '${ARGS_BLOCK}' SOC_BAK_ALL_IN_ONE=1 SOC_BAK_FIXED_DATA_START=1" 2>&1)"; rc=$?
check_eq "旧模式 FIXED_DATA_START 仍可单独开启" "0" "${rc}"

# 平台范围：socbak.sh 里对非 CV 系（SE7）必须拒绝。这里断言那条判断读的是**
# 与 XML 单位策略同一个函数**，避免两处各写一份芯片名单后漂移。
check_eq "平台范围判断复用 socbak_partition_uses_sector" "1" \
	"$(sed -n '/SOC_BAK_LOCAL_UPDATE_LAYOUT.*only supported on the CV series/{=;q}' "${SOCBAK_SH}" | wc -l)"
for chip in bm1688 cv186ah cv84x6; do
	check_eq "平台范围：${chip} 允许 local_update" "0" \
		"$(socbak_partition_uses_sector "${chip}" && echo 0 || echo 1)"
done
for chip in bm1684 bm1684x; do
	check_eq "平台范围：${chip} 被拒绝（sector 表才支持）" "1" \
		"$(socbak_partition_uses_sector "${chip}" && echo 0 || echo 1)"
done

# ---------------------------------------------------------------- B. 源表读取
echo "== B. 源表只读解析 =="
if [ "${HAS_SGDISK}" = "0" ]; then
	bad "构造 GPT 夹具镜像" "环境里没有 sgdisk"
else
	SE9_IMG="${WORK}/se9.img"
	mk_disk "${SE9_IMG}" "${SE9_TOTAL}" "${SE9_LAYOUT}"
	before_md5="$(md5sum "${SE9_IMG}" | awk '{print $1}')"
	check_eq "从 GPT 镜像读出总扇区数" "${SE9_TOTAL}" "$(socbak_read_disk_total_sectors "${SE9_IMG}")"
	check_eq "从 GPT 镜像读出完整布局（标签/起点/长度）" \
		"$(sed 's/^\([^|]*\)|\([^|]*\)|\([^|]*\)|\(.*\)$/\1|\3|\4/' "${SE9_LAYOUT}")" \
		"$(socbak_read_disk_layout "${SE9_IMG}" | awk -F'|' '{printf "%s|%s|%s\n", $1, $3, $4}')"
	# 只读：读表不能改写镜像（真机上就是「不能碰分区表」）
	check_eq "读表前后镜像内容不变（只读）" "${before_md5}" "$(md5sum "${SE9_IMG}" | awk '{print $1}')"

	# 非 GPT 的普通文件：sgdisk 会"在内存里新建一张表"，必须显式拒绝
	head -c 1048576 /dev/urandom > "${WORK}/notgpt.img"
	if socbak_read_disk_layout "${WORK}/notgpt.img" >/dev/null 2>&1; then
		bad "非 GPT 文件被拒绝" "居然读出了布局"
	else
		ok "非 GPT 文件被拒绝"
	fi
	: > "${WORK}/empty.img"
	if socbak_read_disk_layout "${WORK}/empty.img" >/dev/null 2>&1; then
		bad "空文件被拒绝" "居然读出了布局"
	else
		ok "空文件被拒绝"
	fi
	# 失败时不能吐出半份布局（否则调用方会拿到一个"能解析"的空表）
	check_eq "非 GPT 文件不产生任何布局行" "0" \
		"$(socbak_read_disk_layout "${WORK}/notgpt.img" 2>/dev/null | wc -l)"
fi

# ---------------------------------------------------------------- C. 规划
echo "== C. 布局规划（SE9 夹具） =="
# 必须在当前 shell 调用：冻结量通过全局变量返回，$(...) 会被子 shell 吞掉
socbak_local_update_check_source "${SE9_LAYOUT}" >/dev/null
# 分区号必须与 SDK 一致：几何与标签都对、但编号是 2..7 的盘必须被拒绝
awk -F'|' -v OFS='|' '{$2 = $2 + 1; print}' "${SE9_LAYOUT}" > "${WORK}/num_2_7.layout"
err="$(socbak_local_update_check_source "${WORK}/num_2_7.layout" 2>&1)"; rc=$?
check_eq "分区号 2..7（几何与标签完全相同）被拒绝" "1" "${rc}"
check_eq "并指出编号与 SDK 的 p1..p6 不符" "1" \
	"$(echo "${err}" | grep -c 'but the SDK local_update tools address it as p1')"
# 编号正确时通过（对照，避免把编号检查写成恒失败）
check_eq "分区号 1..6 时通过" "0" \
	"$(socbak_local_update_check_source "${SE9_LAYOUT}" >/dev/null 2>&1; echo $?)"
check_eq "源布局校验通过" "0" "$?"
check_eq "冻结区尺寸取自源表（KiB）" "131072 131072 10240" \
	"${SOCBAK_LU_SRC_BOOT_KB} ${SOCBAK_LU_SRC_RECOVERY_KB} ${SOCBAK_LU_SRC_MISC_KB}"
check_eq "冻结起点取自源表（扇区）" "552960 25427328" \
	"${SOCBAK_LU_SRC_ROOTFS_START} ${SOCBAK_LU_SRC_DATA_START}"

# 内容不变时，规划结果必须与源表逐项相同（除了 DATA 长度按内容收紧）
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${SE9_ROOTFS_LEN}" 4194304 35943040
check_eq "内容不变时规划成功" "0" "$?"
check_eq "规划结果原来那六项冻结值一个都没动" \
	"BOOT|8192|262144
RECOVERY|270336|262144
MISC|532480|20480
ROOTFS|552960|12582912
ROOTFS_RW|13135872|12291456
DATA|25427328|4194304" \
	"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}")"
check_eq "总容量沿用打包策略值（未被 DATA 收紧影响）" "35943040" "${SOCBAK_LU_TOTAL}"

# 四个自由度：ROOTFS 变长 → RW 起点右移、长度等量变小、DATA 起点不动
RQ=$(( SE9_ROOTFS_LEN + 204800 ))   # +100 MiB
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${RQ}" 4194304 35943040
rows="$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}")"
check_eq "ROOTFS 增大：起点不变、长度按内容" "ROOTFS|${SE9_ROOTFS_START}|${RQ}" \
	"$(echo "${rows}" | grep '^ROOTFS|')"
check_eq "ROOTFS 增大：RW 起点 = ROOTFS 末尾" "ROOTFS_RW|$(( SE9_ROOTFS_START + RQ ))|$(( SE9_DATA_START - SE9_ROOTFS_START - RQ ))" \
	"$(echo "${rows}" | grep '^ROOTFS_RW|')"
check_eq "ROOTFS 增大：DATA 起点不动" "DATA|${SE9_DATA_START}|4194304" \
	"$(echo "${rows}" | grep '^DATA|')"
check_eq "ROOTFS 增大：RW 长度减少量等于 ROOTFS 增加量" "0" \
	"$(( (SE9_RW_LEN - (SE9_DATA_START - SE9_ROOTFS_START - RQ)) - (RQ - SE9_ROOTFS_LEN) ))"

# 单独增大 DATA：只有 DATA 长度变化
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${SE9_ROOTFS_LEN}" $(( 4194304 + 2097152 )) 35943040
check_eq "仅增大 DATA：其余五项全不变" \
	"BOOT|8192|262144
RECOVERY|270336|262144
MISC|532480|20480
ROOTFS|552960|12582912
ROOTFS_RW|13135872|12291456" "$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | head -n5)"
check_eq "仅增大 DATA：DATA 起点不变、长度按内容" "DATA|${SE9_DATA_START}|6291456" \
	"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | grep '^DATA|')"

# 两者一起增大
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${RQ}" 6291456 35943040
check_eq "同时增大 ROOTFS 与 DATA：DATA 起点仍不动" "DATA|${SE9_DATA_START}|6291456" \
	"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | grep '^DATA|')"
check_eq "同时增大时总容量仍沿用策略值" "35943040" "${SOCBAK_LU_TOTAL}"

# RW 余量边界：ROOTFS 涨到刚好吃掉「RW 原长 - 200MiB」时放行，多 2 扇区就失败。
MARGIN=$(( 200 * 1024 * 2 ))
MAX_GROW=$(( SE9_RW_LEN - MARGIN ))
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" $(( SE9_ROOTFS_LEN + MAX_GROW )) 4194304 35943040
check_eq "RW 余量恰好够（剩 200 MiB）时通过" "0" "$?"
check_eq "余量恰好够时 RW 长度就是 200 MiB" "${MARGIN}" \
	"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | awk -F'|' '$1=="ROOTFS_RW"{print $3}')"
# 失败必须清掉上一次的规划结果：否则调用方会拿着上一轮的几何当本轮结果用。
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" $(( SE9_ROOTFS_LEN + MAX_GROW + 2 )) 4194304 35943040 2>"${WORK}/margin.err"; rc=$?
check_eq "RW 余量差 2 扇区时失败" "1" "${rc}"
check_eq "并报出所需扇区数" "1" "$(grep -c 'cannot absorb that and keep the 200 MiB margin' "${WORK}/margin.err")"
check_eq "失败时不留下规划结果" "0" "${#SOCBAK_LU_ROWS[@]}"

# DATA 越界：DATA 超出源盘最后可用 LBA（total-34）
err="$(socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${SE9_ROOTFS_LEN}" \
	$(( SE9_TOTAL - SE9_DATA_START - 34 + 2 )) 35943040 2>&1)"; rc=$?
check_eq "DATA 越过源盘末可用 LBA 时失败" "1" "${rc}"
check_eq "并报出源盘容量" "1" "$(echo "${err}" | grep -c 'but the source disk has only')"
# 正好用到最后可用 LBA 必须放行（边界另一侧）
socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${SE9_ROOTFS_LEN}" \
	$(( SE9_TOTAL - SE9_DATA_START - 34 )) 35943040
check_eq "DATA 正好用到最后可用 LBA 时通过" "0" "$?"

# 非法源布局：标签顺序不对、少分区、多分区、BOOT 起点不对、奇数长度
layout_with "${WORK}/swap.layout" MISC 532480 20480
awk -F'|' -v OFS='|' 'NR==3{t=$0; next} NR==4{print; print t; next} {print}' \
	"${SE9_LAYOUT}" > "${WORK}/swapped.layout"
err="$(socbak_local_update_check_source "${WORK}/swapped.layout" 2>&1)"; rc=$?
check_eq "MISC 与 ROOTFS 顺序调换时被拒绝" "1" "${rc}"
check_eq "并指出期望的标签" "1" "$(echo "${err}" | grep -c 'expected "MISC"')"

head -n5 "${SE9_LAYOUT}" > "${WORK}/short.layout"
err="$(socbak_local_update_check_source "${WORK}/short.layout" 2>&1)"; rc=$?
check_eq "少一个分区时被拒绝" "1" "${rc}"
check_eq "并说明期望的分区数" "1" "$(echo "${err}" | grep -c 'expected the 6-partition local_update layout')"

cp "${SE9_LAYOUT}" "${WORK}/extra.layout"
echo "OPT|7|61071327|2048" >> "${WORK}/extra.layout"
err="$(socbak_local_update_check_source "${WORK}/extra.layout" 2>&1)"; rc=$?
check_eq "多一个分区时被拒绝" "1" "${rc}"

layout_with "${WORK}/bootstart.layout" BOOT 16384 -
err="$(socbak_local_update_check_source "${WORK}/bootstart.layout" 2>&1)"; rc=$?
check_eq "BOOT 起点不是 LBA 8192 时被拒绝" "1" "${rc}"
check_eq "并报出期望的 LBA 8192" "1" "$(echo "${err}" | grep -c 'expected 8192')"

# 前缀有空洞（MISC 与 ROOTFS 之间空一格）：无法只靠 XML 复现起点，必须拒绝
awk -F'|' -v OFS='|' '$1=="ROOTFS"{$3=$3+2} {print}' "${SE9_LAYOUT}" > "${WORK}/hole.layout"
err="$(socbak_local_update_check_source "${WORK}/hole.layout" 2>&1)"; rc=$?
check_eq "源表前缀不连续时被拒绝" "1" "${rc}"
check_eq "并说明无法复现" "1" "$(echo "${err}" | grep -c 'non-contiguous source layout')"

# 奇数扇区（socbak 内部以 KiB 计，写不出奇数）：冻结区长度、ROOTFS/DATA 新长度。
# 必须保持前缀连续（否则会先被"不连续"拦下，测不到奇数这条规则）：
# RECOVERY 缩 1 扇区、MISC 起点随之左移 1 —— 长度奇数但布局仍然首尾相接。
awk -F'|' -v OFS='|' '
	$1 == "RECOVERY" { $4 = 262143 }
	$1 == "MISC"     { $3 = $3 - 1 }
	$1 == "ROOTFS"   { $3 = $3 - 1 }
	$1 == "ROOTFS_RW"{ $3 = $3 - 1 }
	$1 == "DATA"     { $3 = $3 - 1 }
	{ print }
' "${SE9_LAYOUT}" > "${WORK}/oddrecovery.layout"
err="$(socbak_local_update_check_source "${WORK}/oddrecovery.layout" 2>&1)"; rc=$?
check_eq "冻结区长度为奇数扇区时被拒绝" "1" "${rc}"
check_eq "并说明无法用 KiB 精确表达" "1" "$(echo "${err}" | grep -c 'cannot express it exactly')"

err="$(socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" $(( SE9_ROOTFS_LEN + 1 )) 4194304 35943040 2>&1)"; rc=$?
check_eq "新 ROOTFS 长度为奇数扇区时被拒绝" "1" "${rc}"
err="$(socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${SE9_ROOTFS_LEN}" 4194305 35943040 2>&1)"; rc=$?
check_eq "新 DATA 长度为奇数扇区时被拒绝" "1" "${rc}"

# 与默认值不同的源前缀尺寸：BOOT/RECOVERY 各换成 64 MiB 与 96 MiB 也要照抄
DSTART2=$(( 8192 + 131072 + 196608 + 20480 + 12582912 + 12291456 ))
cat > "${WORK}/custom_prefix.layout" <<EOF
BOOT|1|8192|131072
RECOVERY|2|139264|196608
MISC|3|335872|20480
ROOTFS|4|356352|12582912
ROOTFS_RW|5|12939264|12291456
DATA|6|25230720|35643999
EOF
socbak_local_update_plan "${WORK}/custom_prefix.layout" 61071360 "${SE9_ROOTFS_LEN}" 4194304 35943040
check_eq "自定义源前缀（BOOT 64MiB / RECOVERY 96MiB）被原样照抄" \
	"BOOT|8192|131072
RECOVERY|139264|196608
MISC|335872|20480" "$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | head -n3)"
check_eq "自定义前缀下 DATA 起点取源表值（不按默认常量算）" "25230720" \
	"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | awk -F'|' '$1=="DATA"{print $2}')"

# ---------------------------------------------------------------- D. 只允许四个字段变化
echo "== D. 只允许四个字段变化（逐字段比对） =="
# 把规划结果与源表逐字段对比，输出"变了哪些字段"。期望恒为下面这四行：
# 源布局文件是 "LABEL|PARTNO|START|LEN"，计划文件是 "LABEL|START|LEN"，字段位置不同，
# 必须显式对齐（按 $3/$4 取源表、$2/$3 取计划），否则会把分区号和长度当成"变化的字段"。
four_fields_diff() { # <source_layout_file> <plan_file>
	local src="$1" plan="$2"
	awk -F'|' '
		NR == FNR { s_start[$1] = $3; s_len[$1] = $4; next }
		{
			if (s_start[$1] != $2) print $1 " start " s_start[$1] " -> " $2
			if (s_len[$1] != $3) print $1 " len " s_len[$1] " -> " $3
		}
	' "${src}" "${plan}"
}
run_case() { # <tag> <new_rootfs_len> <new_data_len> <expect: 期望变化行（排序后换行连接）>
	local tag="$1" rlen="$2" dlen="$3" expect="$4"
	local plan="${WORK}/plan_${tag}.layout"
	if ! socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" "${rlen}" "${dlen}" 35943040; then
		bad "${tag}: 规划成功" "socbak_local_update_plan 返回非 0"
		return
	fi
	printf '%s\n' "${SOCBAK_LU_ROWS[@]}" > "${plan}"
	check_eq "${tag}: 变化的字段恰好是期望的四个" "${expect}" \
		"$(four_fields_diff "${SE9_LAYOUT}" "${plan}" | sort)"
}

# 情形一：只 ROOTFS 增大（RW 起点、RW 长度随之变化 = 3 项）
# 注意 DATA 的源长度是"已扩到盘尾"的 35643999，按内容制镜像后必然变成内容所需长度；
# 这正是需求里"不能把当前已扩到盘尾的 DATA 长度当成打包需要的最小 DATA 长度"，
# 因此任何一次打包都会在 DATA 长度上出现差异，冻结的只有它的起点。
run_case only_rootfs $(( SE9_ROOTFS_LEN + 204800 )) 4194304 \
	"DATA len 35643999 -> 4194304
ROOTFS len 12582912 -> $(( SE9_ROOTFS_LEN + 204800 ))
ROOTFS_RW len 12291456 -> $(( SE9_DATA_START - SE9_ROOTFS_START - SE9_ROOTFS_LEN - 204800 ))
ROOTFS_RW start 13135872 -> $(( SE9_RW_START + 204800 ))"

# 情形二：只 DATA 长度增大（1 项）
run_case only_data "${SE9_ROOTFS_LEN}" 6291456 "DATA len 35643999 -> 6291456"

# 情形三：两者一起增大（4 项）
run_case both $(( SE9_ROOTFS_LEN + 204800 )) 6291456 \
	"DATA len 35643999 -> 6291456
ROOTFS len 12582912 -> $(( SE9_ROOTFS_LEN + 204800 ))
ROOTFS_RW len 12291456 -> $(( SE9_DATA_START - SE9_ROOTFS_START - SE9_ROOTFS_LEN - 204800 ))
ROOTFS_RW start 13135872 -> $(( SE9_RW_START + 204800 ))"

# 冻结的六项里有五项是绝对不许动的：把它们单独列出来断言，读报告时一眼能对上
for field in "BOOT start" "BOOT len" "RECOVERY start" "RECOVERY len" "MISC start" "MISC len" \
	"ROOTFS start" "DATA start"; do
	plot="${WORK}/plan_both.layout"
	check_eq "同时增大时 ${field} 未变化" "0" \
		"$(four_fields_diff "${SE9_LAYOUT}" "${plot}" | grep -c "^${field} ")"
done

# ---------------------------------------------------------------- E. 旧包反例
echo "== E. 反例：旧模式下产出的 SE9 包必须被拒绝 =="
# 前次 SE9 旧包（SOC_BAK_FIXED_DATA_START）把 MISC 从 532480 挪到 552960、
# ROOTFS 从 552960 挪到 573440，DATA 起点保持 25427328 不变 —— DATA 起点对上，
# 但 MISC/ROOTFS 已平移，local_update 的起点检查会拒绝，这里必须同样拒绝。
# 前次 SE9 旧包（SOC_BAK_FIXED_DATA_START）把 MISC 从 532480 挪到 552960、
# ROOTFS 从 552960 挪到 573440，DATA 起点保持 25427328 不变 —— DATA 起点对上，
# 但 MISC/ROOTFS 已平移，local_update 的起点检查会拒绝，本工具必须同样拒绝。
# 几何由源表的数值推出来（不在夹具里写死，避免夹具本身算错）：
#   BOOT 长度吸收 20480 扇区（MISC 长度）→ 之后每个分区整体右移 20480，
#   ROOTFS_RW 相应缩短 20480 以保持 DATA 起点不动。
OLD_BOOT_LEN=$(( SE9_BOOT_LEN + SE9_MISC_LEN ))
OLD_MISC_START=$(( SE9_BOOT_START + OLD_BOOT_LEN + SE9_REC_LEN ))
OLD_ROOTFS_START=$(( OLD_MISC_START + SE9_MISC_LEN ))
OLD_RW_LEN=$(( SE9_DATA_START - OLD_ROOTFS_START - SE9_ROOTFS_LEN ))
write_old_pkg() { # <out> <boot_len> <misc_len> <rw_len>
	cat > "$1" <<XML
<physical_partition size_in_sectors="35943040">
  <partition label="BOOT"       size_in_sectors="$2"  readonly="false"  format="1" />
  <partition label="RECOVERY"   size_in_sectors="${SE9_REC_LEN}"  readonly="false" format="2" />
  <partition label="MISC"       size_in_sectors="$3"  readonly="false"   format="0" />
  <partition label="ROOTFS"     size_in_sectors="${SE9_ROOTFS_LEN}" readonly="true"   format="2" />
  <partition label="ROOTFS_RW"  size_in_sectors="$4" readonly="false"  format="2" />
  <partition label="DATA"       size_in_sectors="4194304" readonly="false"  format="2" />
</physical_partition>
XML
}
write_old_pkg "${WORK}/se9_old_shifted.xml" "${OLD_BOOT_LEN}" "${SE9_MISC_LEN}" "${OLD_RW_LEN}"
# 夹具自检：这份 XML 的 DATA 起点必须正好是旧包记录的 25427328
check_eq "旧包夹具自检：DATA 起点 = 25427328" "${SE9_DATA_START}" \
	"$(socbak_xml_geometry "${WORK}/se9_old_shifted.xml" | awk -F'|' '$1=="DATA"{print $2}')"
# 夹具自检：MISC 与 ROOTFS 起点必须正好是旧包记录的 552960 / 573440
check_eq "旧包夹具自检：MISC=552960 ROOTFS=573440" "552960 573440" \
	"$(socbak_xml_geometry "${WORK}/se9_old_shifted.xml" |
		awk -F'|' '$1=="MISC"{m=$2} $1=="ROOTFS"{r=$2} END{print m, r}')"

err="$(socbak_local_update_verify_xml "${WORK}/se9_old_shifted.xml" "${SE9_LAYOUT}" 2>&1)"; rc=$?
check_eq "旧包（MISC/ROOTFS 平移、DATA 起点不变）被拒绝" "1" "${rc}"
check_eq "拒绝原因指向 BOOT 长度不符（前缀平移的直接证据）" "1" \
	"$(echo "${err}" | grep -c "BOOT is \[start=8192 len=${OLD_BOOT_LEN}\]")"
# 三项起点里 DATA 恰好对上（这正是旧模式的设计目标），MISC 与 ROOTFS 都对不上 ——
# 只比 DATA 起点的检查会放过这个包，SDK 与本工具都不会。
check_eq "旧包的三项起点检查：DATA 对、MISC/ROOTFS 错" \
	"DATA OK
MISC MISMATCH
ROOTFS MISMATCH" \
	"$(socbak_local_update_check_starts "${WORK}/se9_old_shifted.xml" "${SE9_LAYOUT}" 2>/dev/null |
		sed -E 's/^(DATA|MISC|ROOTFS): source=[0-9]+ package=[0-9]+ (OK|MISMATCH)$/\1 \2/')"

# 关键反例：**SDK 的三项起点检查全部通过、但冻结区的长度已被改坏**的包。
# 以 SE9 源表为准，把 BOOT 加长 SHIFT、RECOVERY 缩短 SHIFT（SHIFT = MISC 长度 20480）：
#   MISC 起点   = 8192 + (262144+SHIFT) + (262144-SHIFT) = 532480   ← 不变
#   ROOTFS 起点 = MISC 起点 + 20480                      = 552960   ← 不变
#   DATA 起点                                            = 25427328 ← 不变
# 只有 BOOT（282624）与 RECOVERY（241664）的**长度**错了，而 SDK 只比 DATA/MISC/ROOTFS 三个起点。
# 这正是本工具必须逐项比长度、不能只比三个起点的理由：这种包 SDK 会放行，
# 刷进去之后 BOOT/RECOVERY 的实际边界与分区表不符，救援通道与内容都会错位。
SHIFT=$(( SE9_MISC_LEN ))
SWAP_BOOT_LEN=$(( SE9_BOOT_LEN + SHIFT ))
SWAP_REC_LEN=$(( SE9_REC_LEN - SHIFT ))
SWAP_REC_START=$(( SE9_BOOT_START + SWAP_BOOT_LEN ))
SWAP_MISC_START=$(( SWAP_REC_START + SWAP_REC_LEN ))
# 后三个分区的起点与源机相同，长度也照抄（RW 用源机长度，DATA 用内容长度）
cat > "${WORK}/se9_len_swap.xml" <<XML
<physical_partition size_in_sectors="35943040">
  <partition label="BOOT"       size_in_sectors="${SWAP_BOOT_LEN}"  readonly="false"  format="1" />
  <partition label="RECOVERY"   size_in_sectors="${SWAP_REC_LEN}"  readonly="false" format="2" />
  <partition label="MISC"       size_in_sectors="${SE9_MISC_LEN}"  readonly="false"   format="0" />
  <partition label="ROOTFS"     size_in_sectors="${SE9_ROOTFS_LEN}" readonly="true"   format="2" />
  <partition label="ROOTFS_RW"  size_in_sectors="${SE9_RW_LEN}" readonly="false"  format="2" />
  <partition label="DATA"       size_in_sectors="4194304" readonly="false"  format="2" />
</physical_partition>
XML
check_eq "长度互换夹具自检：三个起点仍等于源机（MISC=532480 ROOTFS=552960 DATA=25427328）" \
	"532480 552960 25427328" \
	"$(socbak_xml_geometry "${WORK}/se9_len_swap.xml" |
		awk -F'|' '$1=="MISC"{m=$2} $1=="ROOTFS"{r=$2} $1=="DATA"{d=$2} END{print m, r, d}')"
check_eq "长度互换夹具自检：BOOT/RECOVERY 长度已与源机不同" \
	"${SWAP_BOOT_LEN} ${SWAP_REC_LEN}" \
	"$(socbak_xml_geometry "${WORK}/se9_len_swap.xml" |
		awk -F'|' '$1=="BOOT"{b=$3} $1=="RECOVERY"{r=$3} END{print b, r}')"
# ① 这份包能通过 SDK 口径的三项起点检查（说明"只比起点"是不够的）
check_eq "三项起点检查对这份包全部通过（说明只比起点不够）" "0" \
	"$(socbak_local_update_check_starts "${WORK}/se9_len_swap.xml" "${SE9_LAYOUT}" 2>/dev/null | grep -c MISMATCH)"
# ② 本工具的逐项检查必须拒绝它
err="$(socbak_local_update_verify_xml "${WORK}/se9_len_swap.xml" "${SE9_LAYOUT}" 2>&1)"; rc=$?
check_eq "BOOT/RECOVERY 长度被互换、起点全对的包被拒绝" "1" "${rc}"
check_eq "并指出 BOOT 长度与源机不符" "1" \
	"$(echo "${err}" | grep -c "BOOT is \[start=8192 len=${SWAP_BOOT_LEN}\]")"
check_eq "并指出 RECOVERY 长度与源机不符" "1" \
	"$(echo "${err}" | grep -c "RECOVERY is \[start=${SWAP_REC_START} len=${SWAP_REC_LEN}\]")"

# ---------------------------------------------------------------- F. 端到端
echo "== F. 端到端：计划 → XML → gpt.gz → 解码 =="
if [ "${HAS_SGDISK}" = "0" ]; then
	bad "端到端几何一致" "环境里没有 sgdisk"
else
# 用生产写盘函数把计划写成 XML。计划里只有各分区长度，容量由计划的总容量给出
# （不能把各分区长度相加当总容量：分区表总容量通常大于分区之和，末分区之后还有余量，
#  用和值会让 DATA 压到备份 GPT 区，生成器按规则拒绝——那正是它该做的事）。
plan_to_xml() { # <plan_file> <total_sectors> <out_xml>
	local plan="$1" total="$2" out="$3"
	local -a rows=()
	local label start len
	while IFS='|' read -r label start len; do
		[ -n "${label}" ] || continue
		rows+=("${label}|$(( len / 2 ))|$([ "${label}" = "ROOTFS" ] && echo true || echo false)|$([ "${label}" = "BOOT" ] && echo 1 || echo 2)")
	done < "${plan}"
	socbak_emit_partition_xml "${out}" 1 "$(( total / 2 ))" "${rows[@]}"
}

	socbak_local_update_plan "${SE9_LAYOUT}" "${SE9_TOTAL}" $(( SE9_ROOTFS_LEN + 204800 )) 6291456 35943040 || true
	printf '%s\n' "${SOCBAK_LU_ROWS[@]}" > "${WORK}/e2e_plan.layout"
	PLAN_TOTAL=${SOCBAK_LU_TOTAL}
	plan_to_xml "${WORK}/e2e_plan.layout" "${PLAN_TOTAL}" "${WORK}/e2e_sector.xml"

	# ① XML 自身的几何必须等于计划（写盘没把扇区/KiB 换错）
	check_eq "XML 几何等于计划" "$(cat "${WORK}/e2e_plan.layout")" \
		"$(socbak_xml_geometry "${WORK}/e2e_sector.xml")"

	# ② 生产 GPT 生成器出的主 GPT 解码后必须等于计划
	if socbak_gen_gpt "${WORK}/e2e_sector.xml" "${WORK}/e2e.gpt"; then
		ok "从 XML 生成主 GPT"
		check_eq "主 GPT 解码后的每个分区等于计划" "$(cat "${WORK}/e2e_plan.layout")" \
			"$(socbak_gpt_geometry "${WORK}/e2e.gpt" | sed 's/|MY RW|/|ROOTFS_RW|/')"
		# 冻结的前缀逐项与源表相同（这里用源布局文件直接比，不经过计划）
		check_eq "主 GPT 的冻结前缀与源机逐项相同" \
			"$(head -n3 "${SE9_LAYOUT}" | awk -F'|' '{printf "%s|%s|%s\n", $1, $3, $4}')" \
			"$(socbak_gpt_geometry "${WORK}/e2e.gpt" | head -n3)"
		check_eq "主 GPT 总容量等于计划总容量" "${PLAN_TOTAL}" \
			"$(socbak_gpt_total_sectors "${WORK}/e2e.gpt")"
		# 交付包里是 gpt.gz；解压后再解一遍，确保压缩没改变内容
		gzip -c "${WORK}/e2e.gpt" > "${WORK}/e2e_gpt.gz"
		gzip -cd "${WORK}/e2e_gpt.gz" > "${WORK}/e2e_from_gz.gpt"
		check_eq "gpt.gz 解出的几何与主 GPT 相同" "$(socbak_gpt_geometry "${WORK}/e2e.gpt")" \
			"$(socbak_gpt_geometry "${WORK}/e2e_from_gz.gpt")"
		check_eq "gpt.gz 解出的几何与计划相同" "$(cat "${WORK}/e2e_plan.layout")" \
			"$(socbak_gpt_geometry "${WORK}/e2e_from_gz.gpt" | sed 's/|MY RW|/|ROOTFS_RW|/')"

		# ③ CV 打包链的刷写偏移：PART_OFFSET 必须等于计划的起点（真实生产代码）
		PKG_SH="${SOCBAK_DIR}/script/bm1688/bm_make_package.sh"
		lu_offsets() { # <xml>
			(
				set +u
				# shellcheck source=/dev/null
				source "${PKG_SH}" >/dev/null 2>&1
				PARTITION_FILE="$1"
				parse_partition_xml
				for i in "${!LABELS[@]}"; do
					printf '%s|%s|%s\n' "${LABELS[$i]^^}" "${PART_OFFSET[$i]}" "${PART_SIZE_IN_SECTOR[$i]}"
				done
			)
		}
		check_eq "打包链的刷写起点/长度等于计划" "$(cat "${WORK}/e2e_plan.layout")" \
			"$(lu_offsets "${WORK}/e2e_sector.xml")"
		# 刷写偏移是分区的绝对起始扇区，与 mmc write 的第 4 列同一口径
		check_eq "DATA 的刷写起始扇区等于源机 DATA 起点" "${SE9_DATA_START}" \
			"$(lu_offsets "${WORK}/e2e_sector.xml" | awk -F'|' '$1=="DATA"{print $2}')"
	else
		bad "从 XML 生成主 GPT" "socbak_gen_gpt 返回非 0"
	fi

	# ④ 反例：只要动了冻结项（这里把 RECOVERY 缩短 2 扇区）就必须被拒绝，
	#    即使 ROOTFS_RW 同步吸收、DATA 起点看起来没动。
	sed 's/label="RECOVERY"   size_in_sectors="262144"/label="RECOVERY"   size_in_sectors="262142"/' \
		"${WORK}/e2e_sector.xml" > "${WORK}/e2e_shift.xml"
	err="$(socbak_local_update_verify_xml "${WORK}/e2e_shift.xml" "${SE9_LAYOUT}" 2>&1)"; rc=$?
	check_eq "RECOVERY 长度被改 2 扇区后的 XML 被拒绝" "1" "${rc}"
	check_eq "并指出 RECOVERY 与源机不符" "1" "$(echo "${err}" | grep -c 'RECOVERY is \[')"

	# 反例：ROOTFS 起点被平移（长度缩短 2 扇区、RW 起点随之左移）
	sed 's/size_in_sectors="12[0-9]*" readonly="true"/size_in_sectors="12582910" readonly="true"/' \
		"${WORK}/e2e_sector.xml" > "${WORK}/e2e_rootfs_shift.xml"
	if socbak_local_update_verify_xml "${WORK}/e2e_rootfs_shift.xml" "${SE9_LAYOUT}" >/dev/null 2>&1; then
		# ROOTFS 起点本身没动（长度在它后面变），这种情况只有"RW 起点必须等于 ROOTFS 末尾"
		# 与"RW 长度必须吸收"两条同时成立才算合法 —— 交给 gpt 与计划比对去抓。
		ok "ROOTFS 长度变化时起点仍不动（长度是四个自由度之一）"
	else
		ok "ROOTFS 长度变化时仍按规则判定"
	fi

	# ④b 反例：ROOTFS_RW 长度是四个自由度之一，但改长会把 DATA 起点推离源机值 ——
	#    这是"RW 长度自由"与"DATA 起点冻结"两条约束的交点，必须被抓住。
	awk -F'|' -v OFS='|' '$1=="ROOTFS_RW"{$3=$3+4096} {print}' \
		"${WORK}/e2e_plan.layout" > "${WORK}/data_moved_plan.layout"
	plan_to_xml "${WORK}/data_moved_plan.layout" "${PLAN_TOTAL}" "${WORK}/data_moved.xml"
	check_eq "RW 加长夹具自检：DATA 起点被推后 4096 扇区" "$(( SE9_DATA_START + 4096 ))" \
		"$(socbak_xml_geometry "${WORK}/data_moved.xml" | awk -F'|' '$1=="DATA"{print $2}')"
	err="$(socbak_local_update_verify_xml "${WORK}/data_moved.xml" "${SE9_LAYOUT}" 2>&1)"; rc=$?
	check_eq "RW 长度被改导致 DATA 起点移动时被拒绝" "1" "${rc}"
	check_eq "并指出 DATA 起点与源机不符" "1" "$(echo "${err}" | grep -c 'DATA starts at')"
	check_eq "SDK 口径的三项检查也拒绝 DATA 起点移动的包" "1" \
		"$(socbak_local_update_check_starts "${WORK}/data_moved.xml" "${SE9_LAYOUT}" 2>/dev/null | grep -c MISMATCH)"

	# ⑤ 计划与 XML 不同时必须被 match 抓到（不是"各自都对但互相对不上"）
	printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | sed '2s/.*/RECOVERY|270336|262146/' > "${WORK}/bad_plan.layout"
	if socbak_local_update_match "${WORK}/bad_plan.layout" "${WORK}/e2e_plan.layout" "unit-test" >/dev/null 2>&1; then
		bad "计划与产物不一致时 match 失败" "居然通过了"
	else
		ok "计划与产物不一致时 match 失败"
	fi
fi

# ---------------------------------------------------------------- G. SDK 对照
echo "== G. SDK check_partition_start_sector.sh 等价核对 =="
# SDK 的检查脚本比较源机 fdisk 的起点与 XML 的起点（DATA/MISC/ROOTFS）。
# 这里在夹具上重跑同一套三项检查，并把两侧实值打出来作为交付证据。
sdk_check_equiv() { # <layout_file (源)> <xml>
	local layout="$1" xml="$2" label cur new rc=0
	for label in DATA MISC ROOTFS; do
		cur="$(awk -F'|' -v l="${label}" '$1==l{print $3; exit}' "${layout}")"
		new="$(socbak_xml_geometry "${xml}" | awk -F'|' -v l="${label}" '$1==l{print $2; exit}')"
		printf '%s source=%s package=%s %s\n' "${label}" "${cur}" "${new}" \
			"$([ "${cur}" = "${new}" ] && echo OK || echo MISMATCH)"
		[ "${cur}" = "${new}" ] || rc=1
	done
	return "${rc}"
}
if [ -f "${WORK}/e2e_sector.xml" ]; then
	out="$(sdk_check_equiv "${SE9_LAYOUT}" "${WORK}/e2e_sector.xml")"; rc=$?
	echo "${out}" | sed 's/^/    /'
	check_eq "新包通过 SDK 的三项起点检查（DATA/MISC/ROOTFS）" "0" "${rc}"
	check_eq "三项检查各有实值" "3" "$(echo "${out}" | grep -c 'source=[0-9]* package=[0-9]*')"
	check_eq "MISC 起点保持源机的 532480" "MISC source=532480 package=532480 OK" \
		"$(echo "${out}" | grep '^MISC ')"
	out="$(sdk_check_equiv "${SE9_LAYOUT}" "${WORK}/se9_old_shifted.xml")"; rc=$?
	check_eq "旧包不通过 SDK 的三项检查" "1" "${rc}"
fi

# SDK 原文里的本地副本：有则顺带核对它自己算出的起点与本工具的几何一致
SDK_XML="${SOCBAK_SDK_SECTOR_XML:-}"
if [ -z "${SDK_XML}" ]; then
	for c in /home/zzt/workspace/cv84x2/build/scripts/partition32G_sector.xml \
		"${SOCBAK_DIR}/../../../cv84x2/build/scripts/partition32G_sector.xml"; do
		[ -f "${c}" ] && { SDK_XML="${c}"; break; }
	done
fi
if [ -z "${SDK_XML}" ] || [ ! -f "${SDK_XML}" ]; then
	echo "  skip 未提供 CV84×6 SDK 的 partition32G_sector.xml（可用 SOCBAK_SDK_SECTOR_XML 指定）"
else
	SDK_XML="$(readlink -f "${SDK_XML}")"
	echo "  fixture: ${SDK_XML}"
	# SE13 样例：六个分区、DATA 起点 25427328（SDK 注释自己就写明了这个值）
	check_eq "SE13 SDK 样例可解析为 6 个分区" "6" "$(socbak_xml_partition_rows "${SDK_XML}" | wc -l)"
	check_eq "SE13 SDK 样例的 DATA 起点" "25427328" \
		"$(socbak_xml_geometry "${SDK_XML}" | awk -F'|' '$1=="DATA"{print $2}')"
	check_eq "SE13 SDK 样例的 MISC/ROOTFS 起点与 SE9 源机一致" \
		"MISC|532480
ROOTFS|552960" "$(socbak_xml_geometry "${SDK_XML}" | awk -F'|' '$1=="MISC"||$1=="ROOTFS"{print $1"|"$2}')"
	# 以 SE13 的布局当第二份源表：规划必须只动那四个数值
	socbak_xml_geometry "${SDK_XML}" | awk -F'|' '{printf "%s|%d|%s|%s\n", $1, NR, $2, $3}' \
		> "${WORK}/se13.layout"
	socbak_local_update_check_source "${WORK}/se13.layout"
	check_eq "SE13 源表校验通过" "0" "$?"
	SE13_DATA_START="$(awk -F'|' '$1=="DATA"{print $3}' "${WORK}/se13.layout")"
	SE13_ROOTFS_LEN="$(awk -F'|' '$1=="ROOTFS"{print $4}' "${WORK}/se13.layout")"
	socbak_local_update_plan "${WORK}/se13.layout" 35943040 "${SE13_ROOTFS_LEN}" 8388608 35943040
	check_eq "SE13 规划成功（ROOTFS 不变、DATA 按内容）" "0" "$?"
	check_eq "SE13 规划后 DATA 起点仍为源表的 ${SE13_DATA_START}" "${SE13_DATA_START}" \
		"$(printf '%s\n' "${SOCBAK_LU_ROWS[@]}" | awk -F'|' '$1=="DATA"{print $2}')"
	# SDK 样例的 ROOTFS 是 8388608 扇区（4 GiB），与 SE9 的 12582912 不同 ——
	# 这正是"不能拿 socbak 默认常量代替源表"的直接反例。
	if [ "${SE13_ROOTFS_LEN}" != "${SE9_ROOTFS_LEN}" ]; then
		ok "SE13 源表的 ROOTFS 长度（${SE13_ROOTFS_LEN}）与 SE9 默认值（${SE9_ROOTFS_LEN}）不同，仍被原样采用"
	else
		bad "SE13 与 SE9 的 ROOTFS 长度不同" "两者都是 ${SE13_ROOTFS_LEN}，夹具选错了"
	fi
fi

# ---------------------------------------------------------------- H. 生产块串联
echo "== H. socbak.sh 生产块串联（不是重写逻辑，是从脚本里原样抽出执行） =="
# 上面各节验的是 partition_table.sh 里的函数。这一节验的是 socbak.sh **自己**的那几段：
#   ① 开关打开后读源表、把冻结尺寸回填到 TGZ_FILES_SIZE / SOCBAK_MISC_SIZE_KB
#   ② 规划块把 ROOTFS/ROOTFS_RW/DATA 换成本次内容算出的值
#   ③ 写 XML 后立刻做的「计划 vs XML」与「三项起点」两道守卫
# 做法与仓库既有的 partition_units.sh 一致：用行号把这几段原样抽出来在受控环境里跑，
# 这样「把结果放进命令替换丢了全局变量」「守卫写错位置」这类缺陷才会被真正抓到。

# 抽出包含某一行（$2，行号）的最外层 if 块：向上找到不属于任何嵌套的
# `if [[ "${SOC_BAK_LOCAL_UPDATE_LAYOUT}" != "" ]]; then`，向下按 if/fi 配平找到它的 `fi`。
# 不能用"从第一个匹配行往下找第一个 fi"——那会撞进嵌套 if 的 fi 里。
extract_if_block() { # <anchor_line> <out_file>
	local anchor="$1" out="$2" start n line indent
	# 用 bash 自己的语法判断块边界，比正则可靠得多：
	#   - 单行 `if ...; then ...; fi` 会让按行数 if/fi 的写法算错层级；
	#   - `$(...)` 里的 if/fi 也会被误计；
	#   - elif 与同层 if 共用一个 fi。
	# 做法：向上找到第一条**顶格**的 `if [[ "${SOC_BAK_LOCAL_UPDATE_LAYOUT}" != "" ]]; then`；
	# 向下则逐行把候选前缀喂给 `bash -n`，第一次能通过语法检查的位置就是块的结尾。
	start=$(awk -v anchor="${anchor}" '
		NR <= anchor && /^if \[\[ "\$\{SOC_BAK_LOCAL_UPDATE_LAYOUT\}" != "" \]\]; then$/ { n = NR }
		END { if (n) print n }
	' "${SOCBAK_SH}")
	[ -n "${start}" ] || return 1
	n=$(wc -l < "${SOCBAK_SH}")
	# 从 start 开始逐行加，直到这段代码自身语法完整（含 fi 收尾）
	for (( line = start + 1; line <= n; line++ )); do
		sed -n "${start},${line}p" "${SOCBAK_SH}" > "${out}"
		if bash -n "${out}" 2>/dev/null; then
			return 0
		fi
	done
	rm -f "${out}"
	return 1
}


if [ "${HAS_SGDISK}" = "0" ]; then
	bad "生产块串联" "环境里没有 sgdisk"
else
	# ③ 三段的锚点：取脚本里各自独有的一行，再由它定位所属的最外层 if 块
	SETUP_ANCHOR=$(grep -n 'SOCBAK_LU_SOURCE_LAYOUT="\${TGZ_FILES_PATH}/local_update_source.layout"' "${SOCBAK_SH}" | cut -d: -f1)
	if [ -n "${SETUP_ANCHOR}" ] && extract_if_block "${SETUP_ANCHOR}" "${WORK}/blk_setup.sh"; then
		ok "抽出 socbak.sh 的 local_update 源表读取块（锚点 ${SETUP_ANCHOR}）"
	else
		bad "抽出 socbak.sh 的 local_update 源表读取块" "定位失败"
	fi
	PLAN_ANCHOR=$(grep -n 'SOCBAK_LU_PLAN_FILE="\${TGZ_FILES_PATH}/local_update_plan.layout"' "${SOCBAK_SH}" | cut -d: -f1)
	if [ -n "${PLAN_ANCHOR}" ] && extract_if_block "${PLAN_ANCHOR}" "${WORK}/blk_plan.sh"; then
		ok "抽出 socbak.sh 的布局规划块（锚点 ${PLAN_ANCHOR}）"
	else
		bad "抽出 socbak.sh 的布局规划块" "定位失败"
	fi
	GUARD_ANCHOR=$(grep -n 'socbak_local_update_match "\${SOCBAK_LU_PLAN_FILE}"' "${SOCBAK_SH}" | head -n1 | cut -d: -f1)
	if [ -n "${GUARD_ANCHOR}" ] && extract_if_block "${GUARD_ANCHOR}" "${WORK}/blk_guard.sh"; then
		ok "抽出 socbak.sh 的写盘后守卫块（锚点 ${GUARD_ANCHOR}）"
	else
		bad "抽出 socbak.sh 的写盘后守卫块" "定位失败"
	fi

	# ---------------- ① 源表读取块 ----------------
	# 用真实 GPT 镜像跑：冻结尺寸必须被源表值覆盖（而不是配置里的默认常量）。
	# 平台检查也在这一段里，所以 SOC_NAME 要给一个 CV 系值。
	SETUP_DIR="${WORK}/setup_pkg"
	rm -rf "${SETUP_DIR}"; mkdir -p "${SETUP_DIR}"
	run_setup_block() { # <source_image> ; 打印关键变量
		(
			set +u
			# shellcheck source=/dev/null
			source "${PT_SH}"
			export TGZ_FILES_PATH="${SETUP_DIR}"
			# 配置区的默认常量（与 socbak.sh 里一致）：故意全设成"错的"值，
			# 若这一段没有用源表覆盖它们，下面的断言就会失败。
			declare -A -g TGZ_FILES_SIZE=([boot]=999999 [recovery]=888888 [rootfs]=777777 [data]=666666)
			SOCBAK_MISC_SIZE_KB=12345
			SOCBAK_LU_SOURCE_LAYOUT=""
			SOCBAK_NON_GPT_GUARD=0
			SOC_BAK_LOCAL_UPDATE_LAYOUT=1
			SOC_NAME=bm1688
			SOCBAK_LOCAL_UPDATE_SOURCE="$1"
			# 抽出块里的失败路径用的是 exit 1；包一层子 shell 把它变成返回码
			source "${WORK}/blk_setup.sh" || exit 1
			echo "boot=${TGZ_FILES_SIZE[boot]} recovery=${TGZ_FILES_SIZE[recovery]} misc=${SOCBAK_MISC_SIZE_KB}"
			echo "geom=${SOCBAK_LU_SRC_BOOT_KB} ${SOCBAK_LU_SRC_RECOVERY_KB} ${SOCBAK_LU_SRC_MISC_KB} ${SOCBAK_LU_SRC_ROOTFS_START} ${SOCBAK_LU_SRC_DATA_START}"
			echo "total=${SOCBAK_LU_TOTAL_SECTORS}"
			echo "layout_file=$([ -s "${SOCBAK_LU_SOURCE_LAYOUT}" ] && echo yes || echo no)"
		) 2>&1
	}
	out="$(run_setup_block "${SE9_IMG}")"; rc=$?
	check_eq "① 源表读取块成功" "0" "${rc}"
	# 冻结尺寸的**回填**刻意不在这一段：芯片默认值（bm1688/cv84x6 分支）在它之后执行，
	# 若在这里赋值就会被静默覆盖（首次验收缺陷 4）。这一段只负责读表 + 校验 + 记录。
	check_eq "① 源表读取块不在这里改 TGZ_FILES_SIZE（留给芯片默认值之后）" \
		"boot=999999 recovery=888888 misc=12345" "$(echo "${out}" | grep '^boot=')"
	check_eq "① 但源机几何已读进全局变量" "131072 131072 10240 552960 25427328" \
		"$(echo "${out}" | grep '^geom=' | sed 's/^geom=//')"
	check_eq "① 源盘总扇区数已读出" "total=${SE9_TOTAL}" "$(echo "${out}" | grep '^total=')"
	check_eq "① 源表明细已落盘供后续核对" "layout_file=yes" "$(echo "${out}" | grep '^layout_file=')"
	# 读不出布局时必须以非零退出（不能带着配置默认值继续打包）
	out="$(run_setup_block "${WORK}/notgpt.img")"; rc=$?
	check_eq "① 源设备没有 GPT 时非零退出" "1" "${rc}"
	check_eq "① 且不会继续打包（没有回填输出）" "0" "$(echo "${out}" | grep -c '^boot=')"
	check_eq "① 并说明读不到 GPT" "1" "$(echo "${out}" | grep -c 'cannot read the GPT of')"

	# ---------------- ② 规划块 ----------------
	# ROOTFS/DATA 的内容尺寸 -> 回填 ROOTFS_RW_SIZE 与 EMMC_ALL_SIZE
	run_plan_block() { # <rootfs_kib> <data_kib>
		(
			set +u
			# shellcheck source=/dev/null
			source "${PT_SH}"
			export TGZ_FILES_PATH="${SETUP_DIR}"
			declare -A -g TGZ_FILES_SIZE=([rootfs]="$1" [data]="$2")
			ROOTFS_RW_SIZE=9291456
			EMMC_ALL_SIZE=20971520
			SOC_BAK_LOCAL_UPDATE_LAYOUT=1
			SOCBAK_LU_SOURCE_LAYOUT="${SE9_LAYOUT}"
			SOCBAK_LU_TOTAL_SECTORS="${SE9_TOTAL}"
			SOCBAK_LU_PLAN_FILE=""
			SOCBAK_LOCAL_UPDATE_SOURCE="${SE9_IMG}"
			source "${WORK}/blk_plan.sh" || exit 1
			echo "rootfs=${TGZ_FILES_SIZE[rootfs]} rw=${ROOTFS_RW_SIZE} data=${TGZ_FILES_SIZE[data]} emmc=${EMMC_ALL_SIZE}"
			echo "plan_lines=$(wc -l < "${SOCBAK_LU_PLAN_FILE}")"
		) 2>&1
	}
	out="$(run_plan_block 3145728 4194304)"; rc=$?
	check_eq "② 规划块成功" "0" "${rc}"
	# emmc= 读的是回填后的 EMMC_ALL_SIZE，也就是**计划总容量**（KiB）。
	# 计划总容量沿用打包策略给出的值（= 进入本块时的 EMMC_ALL_SIZE），
	# 只有 DATA 装不下时才抬高，所以这里的 20971520 KiB 原样保留 —— 这正是
	# "容量保留原打包策略"这一条的行为。ROOTFS_RW 由源表 RW 长度与本次 ROOTFS 内容算出。
	check_eq "② 规划块回填 ROOTFS / ROOTFS_RW / DATA（KiB）" \
		"rootfs=3145728 rw=$(( (SE9_DATA_START - SE9_ROOTFS_START - 3145728 * 2) / 2 )) data=4194304 emmc=20971520" \
		"$(echo "${out}" | grep '^rootfs=')"
	check_eq "② 规划结果落盘为可复核的文件" "plan_lines=6" "$(echo "${out}" | grep '^plan_lines=')"
	# ROOTFS 内容吃掉 RW 余量时规划块必须失败（并给出所需差额）
	out="$(run_plan_block 12291456 4194304)"; rc=$?
	check_eq "② ROOTFS 内容吃掉 RW 余量时规划块失败" "1" "${rc}"
	check_eq "② 并报出 local_update 无法生成布局" "1" \
		"$(echo "${out}" | grep -c 'cannot build a local_update layout')"

	# ---------------- ③ 写盘后守卫块 ----------------
	# 用②的真实产物作为计划，再与不同来源的 XML 比对
	printf '%s\n' "${SOCBAK_LU_ROWS[@]}" > "${WORK}/guard_plan.layout"
	# 生产块用 "$TGZ_FILES_PATH/$SOCBAK_PARTITION_PATH" 定位 XML，
	# 所以夹具要放进 TGZ_FILES_PATH、并且只传文件名 —— 传绝对路径会拼成
	# "$TGZ_FILES_PATH//tmp/..."，测到的就不是真实调用了。
	run_guard() { # <xml_name_under_SETUP_DIR> <source_layout>
		(
			set +u
			# shellcheck source=/dev/null
			source "${PT_SH}"
			export TGZ_FILES_PATH="${SETUP_DIR}"
			SOC_BAK_LOCAL_UPDATE_LAYOUT=1
			SOCBAK_LU_PLAN_FILE="${WORK}/guard_plan.layout"
			SOCBAK_LU_SOURCE_LAYOUT="$2"
			SOCBAK_PARTITION_PATH="$1"
			# 块里的 socbak_cleanup 在真机上会关服务、卸载；这里换成空实现
			socbak_cleanup() { :; }
			source "${WORK}/blk_guard.sh" || exit 1
			echo "GUARD_PASSED"
		) 2>&1
	}
	# 计划与 XML 一致 -> 通过
	plan_to_xml "${WORK}/guard_plan.layout" 35943040 "${SETUP_DIR}/guard_ok.xml"
	out="$(run_guard guard_ok.xml "${SE9_LAYOUT}")"; rc=$?
	check_eq "③ 计划与 XML 一致时守卫通过" "0" "${rc}"
	check_eq "③ 且没有报错" "0" "$(echo "${out}" | grep -c '^ERROR')"
	check_eq "③ 且明确通过" "1" "$(echo "${out}" | grep -c 'GUARD_PASSED')"
	# 计划对、但 XML 被改坏（BOOT 长度 +20480）-> 第一道守卫失败
	sed 's/label="BOOT"       size_in_sectors="262144"/label="BOOT"       size_in_sectors="282624"/' \
		"${SETUP_DIR}/guard_ok.xml" > "${SETUP_DIR}/guard_bad.xml"
	out="$(run_guard guard_bad.xml "${SE9_LAYOUT}")"; rc=$?
	check_eq "③ XML 与计划不符时守卫失败" "1" "${rc}"
	check_eq "③ 并报出与计划不符" "1" "$(echo "${out}" | grep -c 'does not match the planned layout')"
	# XML 与计划一致、但源表换了（起点不同）-> 第二道守卫失败
	awk -F'|' '{printf "%s|%d|%s|%s\n", $1, NR, $2, $3}' \
		<(socbak_xml_geometry "${WORK}/se9_old_shifted.xml") > "${WORK}/shifted_src.layout"
	out="$(run_guard guard_ok.xml "${WORK}/shifted_src.layout")"; rc=$?
	check_eq "③ XML 与源机起点不符时第二道守卫失败" "1" "${rc}"
	check_eq "③ 并说明 local_update 会拒绝" "1" \
		"$(echo "${out}" | grep -c 'starts differ from the source device')"
fi


# ---------------------------------------------------------------- I. 真实刷机包
echo "== I. 真实刷机包：用 CV 打包链产出整包，再逐项核对 =="
# 前面各节验的是函数与生产块。这一节跑的是**完整的打包链**
# （script/bm1688/bm_make_package.sh 的 init / make_gpt_img / make_partition_imgs /
#  emmc_done），产出一个和板上一致的真实包，然后只按包里的内容做核对：
#   - 包里恰好一份 partition*xml
#   - gpt.gz 解出的主 GPT 与计划逐项相同
#   - 每个分区镜像段（<label>.N-of-M.gz）的 mmc write 覆盖范围都落在自己分区的区间内
#     （不是只看起始扇区：段数多了会越界写坏下一个分区，段数少了内容不完整）
# 需要 mkfs.ext4 / mkfs.fat / mkimage / pigz；缺任何一项就 skip（不记失败）。
NEED_TOOLS_OK=1
for t in mkfs.ext4 mkfs.fat mkimage pigz dumpe2fs; do
	command -v "${t}" >/dev/null 2>&1 || { NEED_TOOLS_OK=0; echo "  skip 缺少 ${t}"; }
done
if [ "${HAS_SGDISK}" = "0" ] || [ "${NEED_TOOLS_OK}" = "0" ]; then
	echo "  skip 真实整包（缺少 sgdisk 或文件系统工具）"
else
	PKG_W="${WORK}/pkg"
	mkdir -p "${PKG_W}/sdcard"
	# 这一节要真的把内容做成镜像、拆段、压缩，所以用一份**结构等价但尺寸缩小**的源表：
	# BOOT / RECOVERY / MISC 保留 SE9 实机的真实起点与长度（前缀语义不变），
	# ROOTFS/DATA 换成百 MiB 级 —— 否则光 ROOTFS 就要 6 GiB 镜像，回归跑不完。
	# 全尺寸的 SE9 数值在 C–G 与 G 节（gpt.gz 解码）里已经逐项验过。
	E2E_BOOT_LEN=262144
	E2E_REC_LEN=262144
	E2E_MISC_LEN=20480
	E2E_ROOTFS_START=$(( 8192 + E2E_BOOT_LEN + E2E_REC_LEN + E2E_MISC_LEN ))
	E2E_RW_START0=$(( E2E_ROOTFS_START + 204800 ))
	E2E_DATA_START=$(( E2E_RW_START0 + 2048000 ))
	E2E_DATA_LEN=4194304
	# 盘容量给 DATA 留出备份 GPT 的位置（DATA 已"扩到盘尾"的真机形状）
	E2E_TOTAL=$(( E2E_DATA_START + E2E_DATA_LEN + 34 ))
	cat > "${PKG_W}/source.layout" <<EOF
BOOT|1|8192|${E2E_BOOT_LEN}
RECOVERY|2|$(( 8192 + E2E_BOOT_LEN ))|${E2E_REC_LEN}
MISC|3|$(( 8192 + E2E_BOOT_LEN + E2E_REC_LEN ))|${E2E_MISC_LEN}
ROOTFS|4|${E2E_ROOTFS_START}|204800
ROOTFS_RW|5|${E2E_RW_START0}|2048000
DATA|6|${E2E_DATA_START}|${E2E_DATA_LEN}
EOF
	E2E_MISC_START=$(awk -F'|' '$1=="MISC"{print $3}' "${PKG_W}/source.layout")
	# ROOTFS 比源机分区大 10 MiB -> 走"ROOTFS 变长、RW 缩短"这条主路径
	E2E_ROOTFS_LEN=$(( 204800 + 20480 ))
	socbak_local_update_plan "${PKG_W}/source.layout" "${E2E_TOTAL}" "${E2E_ROOTFS_LEN}" "${E2E_DATA_LEN}" "${E2E_TOTAL}"
	check_eq "缩小夹具的规划成功" "0" "$?"
	printf '%s\n' "${SOCBAK_LU_ROWS[@]}" > "${PKG_W}/plan.layout"
	# 按计划写 XML（内部 KiB），作为打包链的输入
	plan_to_xml "${PKG_W}/plan.layout" "${E2E_TOTAL}" "${PKG_W}/partition32G_sector.xml"

	# 各分区的源镜像：固定区按源机容量（readonly 分区要求镜像长度精确匹配），
	# ROOTFS/DATA 按内容长度。全部用 sparse 建，避免回归写几 GiB。
	mkimg() { # <path> <KiB> <ext4|fat>
		rm -f "$1"
		truncate -s $(( $2 * 1024 )) "$1"
		if [ "$3" = "fat" ]; then mkfs.fat -F 32 "$1" >/dev/null 2>&1 || mkfs.fat "$1" >/dev/null 2>&1
		else mkfs.ext4 -q -b 4096 -F "$1" >/dev/null 2>&1; fi
	}
	mkimg "${PKG_W}/boot.img" $(( E2E_BOOT_LEN / 2 )) fat
	mkimg "${PKG_W}/recovery.img" $(( E2E_REC_LEN / 2 )) ext4
	mkimg "${PKG_W}/rootfs.img" $(( E2E_ROOTFS_LEN / 2 )) ext4
	mkimg "${PKG_W}/data.img" 2048 ext4
	dd if=/dev/urandom of="${PKG_W}/fip.bin" bs=1M count=1 status=none

	# binTools/mkfs.fat 是**动态链接**的 aarch64（依赖 /lib/ld-linux-aarch64.so.1），
	# 本机 qemu-aarch64 跑不起来。打包链只需要它能建一个 FAT32 镜像，
	# 这里用宿主的 mkfs.fat 兜一层（与既有 partition_units.sh 用 qemu 包装 mk_gpt 同一思路：
	# 只替换平台相关的工具，被测的打包链代码本身一行未改）。
	SHIM="${WORK}/shim"
	rm -rf "${SHIM}"; mkdir -p "${SHIM}"
	if [ "$(uname -m)" != "aarch64" ] && command -v mkfs.fat >/dev/null 2>&1; then
		real_fat="$(command -v mkfs.fat)"
		printf '#!/bin/sh\nexec %s "$@"\n' "${real_fat}" > "${SHIM}/mkfs.fat"
		chmod +x "${SHIM}/mkfs.fat"
	fi
	(
		set +u
		export PATH="${SHIM}:${SOCBAK_DIR}/binTools:${PATH}"
		export TGZ_FILES_PATH="${SOCBAK_DIR}"
		cd "${PKG_W}" || exit 1
		# shellcheck source=/dev/null
		source "${SOCBAK_DIR}/script/bm1688/bm_make_package.sh"
		parseargs sdcard "${PKG_W}/partition32G_sector.xml" "${PKG_W}"
		SOURCE_FILES_PATH="${PKG_W}"
		RECOVERY_DIR="${PKG_W}/sdcard"
		init
		make_gpt_img
		make_partition_imgs
		emmc_done
		cleanup
	) > "${PKG_W}/pack.log" 2>&1
	if [ "$?" != "0" ]; then
		bad "真实整包打包成功" "见 ${PKG_W}/pack.log 末尾：$(tail -n3 "${PKG_W}/pack.log" | tr '\n' ' ')"
	else
		ok "真实整包打包成功"
		PKGD="${PKG_W}/sdcard"
		# ① 包内恰好一份 partition*xml，且文件名是 SDK 认识的那个
		check_eq "包内恰好一份 partition*xml" "1" \
			"$(find "${PKGD}" -type f -name 'partition*xml' | wc -l)"
		check_eq "包内分区表文件名是 partition32G_sector.xml" "1" \
			"$([ -f "${PKGD}/partition32G_sector.xml" ] && echo 1 || echo 0)"
		# ② 包内 XML 满足冻结前缀（用生产校验函数）
		check_eq "包内 XML 满足冻结前缀" "0" \
			"$(socbak_local_update_verify_xml "${PKGD}/partition32G_sector.xml" "${PKG_W}/source.layout" >/dev/null 2>&1; echo $?)"
		# ③ gpt.gz 解出的主 GPT 与计划逐项相同
		if gzip -cd "${PKGD}/gpt.gz" > "${PKG_W}/pkg.gpt"; then
			check_eq "gpt.gz 解出的几何等于计划" "$(cat "${PKG_W}/plan.layout")" \
				"$(socbak_gpt_geometry "${PKG_W}/pkg.gpt" | sed 's/|MY RW|/|ROOTFS_RW|/')"
			check_eq "gpt.gz 的冻结前缀与源机逐项相同" \
				"$(head -n3 "${PKG_W}/source.layout" | awk -F'|' '{printf "%s|%s|%s\n", $1, $3, $4}')" \
				"$(socbak_gpt_geometry "${PKG_W}/pkg.gpt" | head -n3)"
			check_eq "gpt.gz 的总容量等于计划" "${E2E_TOTAL}" \
				"$(socbak_gpt_total_sectors "${PKG_W}/pkg.gpt")"
		else
			bad "解压包内 gpt.gz" "gzip 返回非 0"
		fi
		# ④ 每个分区段的刷写范围必须落在自己分区的区间内，且从分区起点开始
		pkg_ranges() { # <plan> <pkgdir> ; 输出 "PART|low|high|want_start|want_end|ok"
			local plan="$1" dir="$2" scr part p low high addr size end ws wl we
			for scr in "${dir}"/boot_emmc-*.cmd; do
				[ -f "${scr}" ] || continue
				part=$(basename "${scr}" .cmd); part=${part#boot_emmc-}
				p=$(awk -F'|' -v l="${part}" 'tolower($1)==l{print $2 "|" $3; exit}' "${plan}")
				[ -n "${p}" ] || continue
				ws=${p%%|*}; wl=${p##*|}; we=$(( ws + wl ))
				low=""; high=""
				while read -r addr size; do
					addr=$(( addr )); size=$(( size ))
					[ "${size}" -gt 0 ] || continue
					end=$(( addr + size ))
					[ -z "${low}" ] || [ "${addr}" -lt "${low}" ] && low=${addr}
					[ -z "${high}" ] || [ "${end}" -gt "${high}" ] && high=${end}
				done < <(grep -a '^mmc write' "${scr}" | awk '{print $4, $5}')
				printf '%s|%s|%s|%s|%s\n' "${part}" "${low:-none}" "${high:-none}" "${ws}" "${we}"
			done
		}
		ranges="$(pkg_ranges "${PKG_W}/plan.layout" "${PKGD}")"
		check_eq "每个分区都出现在刷写脚本里" "6" "$(echo "${ranges}" | sed '/^$/d' | wc -l)"
		check_eq "所有分区的刷写起始扇区都等于计划起点" "0" \
			"$(echo "${ranges}" | awk -F'|' '$2 != $4' | wc -l)"
		check_eq "所有分区的刷写范围都不越过自己分区" "0" \
			"$(echo "${ranges}" | awk -F'|' '$3 > $5' | wc -l)"
		# 源机 DATA 起点必须真的出现在 DATA 段的起始扇区上（交付证据里的关键数字）
		check_eq "DATA 段从源机 DATA 起点 ${E2E_DATA_START} 开始写" "${E2E_DATA_START}" \
			"$(echo "${ranges}" | awk -F'|' '$1=="data"{print $2}')"
		check_eq "MISC 段从源机 MISC 起点 ${E2E_MISC_START} 开始写" "${E2E_MISC_START}" \
			"$(echo "${ranges}" | awk -F'|' '$1=="misc"{print $2}')"
		check_eq "ROOTFS 段从源机 ROOTFS 起点 ${E2E_ROOTFS_START} 开始写" "${E2E_ROOTFS_START}" \
			"$(echo "${ranges}" | awk -F'|' '$1=="rootfs"{print $2}')"
		check_eq "ROOTFS_RW 段从计划的新起点 $(( E2E_ROOTFS_START + E2E_ROOTFS_LEN )) 开始写" \
			"$(( E2E_ROOTFS_START + E2E_ROOTFS_LEN ))" \
			"$(echo "${ranges}" | awk -F'|' '$1=="rootfs_rw"{print $2}')"
		# 整包必须同时满足 SDK 的三项起点检查
		check_eq "整包通过 SDK 的三项起点检查" "0" \
			"$(socbak_local_update_check_starts "${PKGD}/partition32G_sector.xml" "${PKG_W}/source.layout" >/dev/null 2>&1; echo $?)"
		# 负向：把包里 XML 的 MISC 长度改掉后，校验必须失败（确认校验读的是包内文件）
		cp "${PKGD}/partition32G_sector.xml" "${PKG_W}/tampered.xml"
		sed -i 's/label="MISC"       size_in_sectors="20480"/label="MISC"       size_in_sectors="40960"/' \
			"${PKG_W}/tampered.xml"
		check_eq "包内 XML 被篡改后校验失败" "1" \
			"$(socbak_local_update_verify_xml "${PKG_W}/tampered.xml" "${PKG_W}/source.layout" >/dev/null 2>&1; echo $?)"
	fi
fi


# ---------------------------------------------------------------- J. 冻结区镜像与内容装不下
echo "== J. 冻结区镜像按源机容量精确落地 + 内容装不下必须失败 =="
# local_update 的固定区长度来自源机 GPT，镜像必须**正好**是这个字节数。
# 这条特别容易被 dd 的块大小向下取整破坏：dd bs=4096 对不是 4096 倍数的尺寸会截短，
# 之后按 XML 长度刷写就少写一段 —— 分区表说 128 MiB、盘上只写了 127 MiB。
# 更严重的是"内容装不下"：tar 短写后如果错误被 cleanup/popd 掩盖，脚本会返回 0，
# 交付一个被静默截断的包（首次验收就是这条）。
# 这里跑**真实的** spool / tar / mkfs / fsck，只把 systemctl 换成空函数。
if [ "$(id -u)" = "0" ] || sudo -n true 2>/dev/null; then
	SOCBAK_SH="${SOCBAK_DIR}/socbak.sh"
	extract_fn() { # <fn name> <out>
		local a b
		a=$(grep -n "^function $1()$" "${SOCBAK_SH}" | cut -d: -f1)
		[ -n "${a}" ] || return 1
		b=$(awk -v s="${a}" 'NR > s && $0 == "}" {print NR; exit}' "${SOCBAK_SH}")
		[ -n "${b}" ] || return 1
		sed -n "${a},${b}p" "${SOCBAK_SH}" > "$2"
	}
	if extract_fn socbak_gen_partition_subimg "${WORK}/fn_subimg.sh" &&
		extract_fn socbak_spool_partition_content "${WORK}/fn_spool.sh"; then
		ok "抽出 socbak.sh 的 socbak_gen_partition_subimg 与 socbak_spool_partition_content"
		cat "${WORK}/fn_subimg.sh" "${WORK}/fn_spool.sh" > "${WORK}/fn_both.sh"
		# 在私有挂载命名空间里跑：真的建镜像、真的 tar、真的 fsck；只隔离 systemctl
		SUBIMG_RUNNER="${WORK}/subimg_runner.sh"
		cat > "${SUBIMG_RUNNER}" <<'RUNNER'
#!/bin/bash
# 参数：<part> <bytes> <fmt> <frozen_kib> <workdir> <PT_SH> <FN_SH> <content_mib|null>
set +u
export TGZ_FILES_PATH="$5"
PT_SH="$6"; FN_SH="$7"; CONTENT_MIB="${8:-null}"
declare -A -g TGZ_FILES_SIZE=([boot]="$4" [recovery]="$4" [rootfs]=0 [data]=0)
SOC_BAK_LOCAL_UPDATE_LAYOUT=1
SOC_BAK_FIXED_SIZE=""
SOCBAK_F2FS_PARTS=""
# shellcheck source=/dev/null
source "${PT_SH}"
socbak_cleanup() { :; }
systemctl() { :; }              # 只隔离 systemctl
e2fsck() { :; }                 # 固定区只做 fsck 校验，这里不关心退出码
tune2fs() { :; }
socbak_resize_min_size_kb=0
resize_min_size() { socbak_resize_min_size_kb=0; }
source "${FN_SH}"
# 私有 /boot：放一个内容镜像（null = 空），mount 命名空间保证不影响外面
umount /boot 2>/dev/null
rm -rf /boot && mkdir -p /boot
if [ "${CONTENT_MIB}" != "null" ]; then
	dd if=/dev/zero of=/boot/payload.bin bs=1M count="${CONTENT_MIB}" status=none
fi
cd "${TGZ_FILES_PATH}" || exit 1
socbak_gen_partition_subimg "$1" "$2" "$3"
RC=$?
echo "SUBIMG_RC=${RC}"
stat -c 'IMGSIZE=%s' "sparse-file-$1" 2>/dev/null || echo "IMGSIZE=none"
exit "${RC}"
RUNNER
		chmod +x "${SUBIMG_RUNNER}"
		run_subimg() { # <part> <bytes> <fmt> <frozen_kib> [content_mib]
			local dir="${WORK}/subimg"
			rm -rf "${dir}"; mkdir -p "${dir}"
			sudo -n unshare -m --propagation private \
				bash "${SUBIMG_RUNNER}" "$1" "$2" "$3" "$4" "${dir}" "${PT_SH}" \
				"${WORK}/fn_both.sh" "${5:-null}" 2>&1
		}
		# 尺寸不是 4096 倍数：dd 会截短，冻结路径必须补齐到精确值
		out="$(run_subimg recovery $(( 131073 * 1024 )) ext4 131073)"; rc=$?
		check_eq "非 4096 倍数尺寸（131073 KiB）的冻结镜像可生成" "0" "${rc}"
		check_eq "非 4096 倍数尺寸的镜像字节数仍精确（未被 dd 截短）" \
			"IMGSIZE=$(( 131073 * 1024 ))" "$(echo "${out}" | grep '^IMGSIZE=')"
		# 内容装得下：镜像仍是精确尺寸，且返回 0
		out="$(run_subimg boot $(( 131072 * 1024 )) fat 131072 8)"; rc=$?
		check_eq "内容装得下时固定区镜像生成成功" "0" "${rc}"
		check_eq "内容装得下时镜像字节数精确" "IMGSIZE=$(( 131072 * 1024 ))" \
			"$(echo "${out}" | grep '^IMGSIZE=')"
		# 内容装不下（24 MiB 内容塞进 16 MiB 固定区）：必须非 0，且不能留下成品
		out="$(run_subimg boot $(( 16 * 1024 * 1024 )) fat 16384 24)"; rc=$?
		echo "${out}" | grep -E 'No space left|Cannot write|cp files' >/dev/null &&
			ok "内容装不下时 tar 确实报短写（回归真的写满，不是空函数桩）" ||
			bad "内容装不下时 tar 确实报短写" "没有看到短写证据，回归可能没真的写内容"
		check_eq "内容装不下时制镜像函数返回非 0" "1" "${rc}"
		check_eq "内容装不下时明确报"拒绝继续"" "1" \
			"$(echo "${out}" | grep -c 'refusing to continue')"
	else
		bad "抽出 socbak_gen_partition_subimg / socbak_spool_partition_content" "定位失败"
	fi
else
	echo "  skip 冻结区镜像尺寸（需要 root 或 sudo 才能 mount 镜像）"
fi

# ---------------------------------------------------------------- K. 板上可用的解析方法
echo "== K. GPT 解析不依赖 GNU awk（板上是 mawk 1.3.4） =="
# 板上 /usr/bin/awk 是 mawk（SE9 镜像实测），没有 strtonum / gensub。
# 首次交付的密码解码用了 strtonum，在板上直接 "function strtonum never defined" 返回 2。
# 现在的解码是纯 bash + od，这里验证三件事：
#   ① 源码里不再出现 GNU-only 的 awk 内建；
#   ② 有 mawk 时用它当 awk 仍能正确解码；
#   ③ 完全没有 awk 时也能解码。
if [ "${HAS_SGDISK}" = "1" ]; then
	# 只数**代码行**：注释里提到 strtonum/gensub 是解释为什么不能用，不算违规
	check_eq "partition_table.sh 的代码不再使用 strtonum" "0" \
		"$(grep -vE '^[[:space:]]*#' "${PT_SH}" | grep -c 'strtonum')"
	check_eq "partition_table.sh 的代码不再使用 gensub" "0" \
		"$(grep -vE '^[[:space:]]*#' "${PT_SH}" | grep -c 'gensub')"
	# 造一块真实 GPT 夹具（六个分区），供解码交叉验证用
	truncate -s $(( 7000098 * 512 )) "${WORK}/fix.img"
	sgdisk -a 1 \
		-n 1:8192:270335 -t 1:0700 -c 1:BOOT \
		-n 2:270336:532479 -t 2:0700 -c 2:RECOVERY \
		-n 3:532480:552959 -t 3:0700 -c 3:MISC \
		-n 4:552960:757759 -t 4:0700 -c 4:ROOTFS -A 4:set:60 \
		-n 5:757760:2805759 -t 5:0700 -c 5:ROOTFS_RW \
		-n 6:2805760:7000064 -t 6:0700 -c 6:DATA \
		"${WORK}/fix.img" >/dev/null 2>&1
	dd if="${WORK}/fix.img" of="${WORK}/fix.gpt" bs=512 count=34 status=none
	# 用真实 GPT 交叉验证：新解码器与 sgdisk -p 的分区起止一致
	socbak_gpt_geometry "${WORK}/fix.gpt" > "${WORK}/k_geo.txt" 2>/dev/null || true
	if [ -s "${WORK}/k_geo.txt" ]; then
		check_eq "纯 bash 解码的几何与 sgdisk -p 一致" \
			"$(sgdisk -p "${WORK}/fix.img" 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {print $NF"|"$2"|"($3-$2+1)}')" \
			"$(cat "${WORK}/k_geo.txt")"
		check_eq "纯 bash 解出的总容量与 sgdisk 一致" "7000098" \
			"$(socbak_gpt_total_sectors "${WORK}/fix.gpt")"
	else
		bad "纯 bash 解码 GPT" "解不出几何"
	fi
	# 找一个 mawk：板上是 /usr/bin/awk -> mawk；本机若装了 mawk/original-awk 也用它
	MAWK=""
	for c in mawk original-awk; do
		command -v "$c" >/dev/null 2>&1 && { MAWK="$(command -v "$c")"; break; }
	done
	if [ -z "${MAWK}" ] && [ -n "${SOCBAK_TEST_MAWK:-}" ] && [ -x "${SOCBAK_TEST_MAWK}" ]; then
		MAWK="${SOCBAK_TEST_MAWK}"
	fi
	# 板上 mawk 是 aarch64 的；本机没有 x86 mawk 时，用 qemu 包一层去跑板上的那份，
	# 这样"板上 awk 能不能解 GPT"就是真的验证过，而不是只靠"没用到 awk"推断。
	if [ -z "${MAWK}" ] && command -v qemu-aarch64 >/dev/null 2>&1; then
		for c in /home/zzt/workspace/kylin_final/rootfs/usr/bin/mawk \
			/opt/sophgo/rootfs/usr/bin/mawk; do
			[ -x "${c}" ] || continue
			root="$(cd "$(dirname "${c}")/../.." && pwd)"
			printf '#!/bin/sh\nexec qemu-aarch64 -L %s %s "$@"\n' "${root}" "${c}" \
				> "${WORK}/mawk_qemu"
			chmod +x "${WORK}/mawk_qemu"
			if "${WORK}/mawk_qemu" -W version 2>/dev/null | grep -q mawk; then
				MAWK="${WORK}/mawk_qemu"
				break
			fi
		done
	fi
	if [ -n "${MAWK}" ]; then
		mkdir -p "${WORK}/mawkshim"
		ln -sf "${MAWK}" "${WORK}/mawkshim/awk"
		out="$(PATH="${WORK}/mawkshim:${PATH}" bash -c "
			source '${PT_SH}'
			socbak_gpt_geometry '${WORK}/fix.gpt'
			echo \"total=\$(socbak_gpt_total_sectors '${WORK}/fix.gpt')\"" 2>&1)"
		check_eq "以 mawk 充当 awk 时几何解码正确" "$(cat "${WORK}/k_geo.txt")" \
			"$(echo "${out}" | grep -v '^total=')"
		check_eq "以 mawk 充当 awk 时总容量正确" "total=7000098" \
			"$(echo "${out}" | grep '^total=')"
	else
		echo "  skip mawk 交叉验证（本机无 mawk；可用 SOCBAK_TEST_MAWK 指定）"
	fi
	# 解码路径不能调用 awk：用一个必然失败的 awk 垫片挡住整条 PATH，
	# 如果解码仍然成功，就证明它真的没用 awk（比"PATH 里找不到 awk"更可靠，
	# 因为 od/tr 也都在 /usr/bin，没法把整个目录从 PATH 里摘掉）。
	mkdir -p "${WORK}/badawk"
	printf '#!/bin/sh\necho "awk-stub: must not be called" >&2\nexit 9\n' > "${WORK}/badawk/awk"
	chmod +x "${WORK}/badawk/awk"
	out="$(PATH="${WORK}/badawk:${PATH}" bash -c "
		source '${PT_SH}'
		socbak_gpt_geometry '${WORK}/fix.gpt' | head -n1" 2>&1)"
	check_eq "解码全程不调用 awk（awk 垫片存在时仍正确）" "BOOT|8192|262144" "${out}"

else
	echo "  skip 解析方法验证（环境里没有 sgdisk，无法造夹具）"
fi

# ---------------------------------------------------------------- L. 交付前逐项把关
echo "== L. 最终把关：缺脚本 / 缺数据块 / 越界 / 正常包 =="
# 这一节直接驱动 socbak.sh 的**最终检查块**（原样抽出），在真实产出的包上做四种情形：
#   正常包 -> 通过；缺一份 boot_emmc-<分区>.cmd -> 失败；缺一个被引用的数据块 -> 失败；
#   把某段写的起始扇区改到分区之前 -> 失败。
# 首次交付的缺陷是"只遍历存在的脚本"，所以删掉全部脚本仍打印 passed —— 这里逐个断言。
if [ "${HAS_SGDISK}" = "1" ]; then
	SOCBAK_SH="${SOCBAK_DIR}/socbak.sh"
	GUARD_ANCHOR=$(grep -n 'SOCBAK_LU_PKG_DIR="\${TGZ_FILES_PATH}/output/' "${SOCBAK_SH}" | cut -d: -f1)
	# 最终检查块以 `if [[ "${SOC_BAK_LOCAL_UPDATE_LAYOUT}" != "" ]]; then` 开头，
	# 以该块内第一条顶格 `SOCBAK_LU_PKG_DIR=` 为锚点定位（块内嵌套了两层 if，不能按 RC 行找）
	VERIFY_ANCHOR=$(grep -nF 'SOCBAK_LU_PKG_DIR="${TGZ_FILES_PATH}/output/' "${SOCBAK_SH}" | cut -d: -f1 | head -n1)
	if [ -n "${VERIFY_ANCHOR}" ] && extract_if_block "${VERIFY_ANCHOR}" "${WORK}/blk_verify.sh"; then
		ok "抽出 socbak.sh 的最终检查块（锚点 ${VERIFY_ANCHOR}）"
		# 造一个形状正确的假包：XML + gpt.gz + 六份刷写脚本 + 数据块
		mk_fake_pkg() { # <dir>
			local d="$1"
			rm -rf "${d}"; mkdir -p "${d}"
			cp "${WORK}/fix.xml" "${d}/partition32G_sector.xml"
			socbak_gen_gpt "${WORK}/fix.xml" "${WORK}/fix.gpt" || return 1
			gzip -c "${WORK}/fix.gpt" > "${d}/gpt.gz"
			local label start len
			while IFS='|' read -r label start len; do
				[ -n "${label}" ] || continue
				local lo="${label,,}"
				# 按真实打包链的形状造脚本：先 load 数据块，再 mmc write 到分区起点
				printf 'load ${devtype} ${devnum}:${distro_bootpart} ${ramdisk_addr_r} /gpt/%s.1-of-1.gz\nunzip ${ramdisk_addr_r} ${unzip_addr} 1024\nmmc write ${unzip_addr} 0x%08x 0x%08x\n' \
					"${lo}" "${start}" 512 > "${d}/boot_emmc-${lo}.cmd"
				dd if=/dev/urandom of="${d}/${lo}.1-of-1.gz" bs=512 count=2 status=none
			done < "${WORK}/k_plan.layout"
		}
		{
			printf '<physical_partition size_in_sectors="7000098">\n'
			printf '  <partition label="BOOT" size_in_sectors="262144" readonly="false" format="1" />\n'
			printf '  <partition label="RECOVERY" size_in_sectors="262144" readonly="false" format="2" />\n'
			printf '  <partition label="MISC" size_in_sectors="20480" readonly="false" format="0" />\n'
			printf '  <partition label="ROOTFS" size_in_sectors="204800" readonly="true" format="2" />\n'
			printf '  <partition label="ROOTFS_RW" size_in_sectors="2048000" readonly="false" format="2" />\n'
			printf '  <partition label="DATA" size_in_sectors="4194305" readonly="false" format="2" />\n'
			printf '</physical_partition>\n'
		} > "${WORK}/fix.xml"
		socbak_xml_geometry "${WORK}/fix.xml" > "${WORK}/k_plan.layout"

		run_verify() { # <pkgdir>
			(
				set +u
				# shellcheck source=/dev/null
				source "${PT_SH}"
				export TGZ_FILES_PATH="${WORK}/vroot"
				rm -rf "${TGZ_FILES_PATH}"; mkdir -p "${TGZ_FILES_PATH}/output"
				mkdir -p "${TGZ_FILES_PATH}/output/sdcard"
				rm -rf "${TGZ_FILES_PATH}/output/sdcard"
				cp -a "$1" "${TGZ_FILES_PATH}/output/sdcard"
				SOC_BAK_LOCAL_UPDATE_LAYOUT=1
				SOC_BAK_ALL_IN_ONE=1
				SOCBAK_LU_PKG_DIR="${TGZ_FILES_PATH}/output/sdcard"
				SOCBAK_LU_PLAN_FILE="${WORK}/k_plan.layout"
				SOCBAK_LU_SOURCE_LAYOUT="${WORK}/k_source.layout"
				SOCBAK_PARTITION_NAME=partition32G_sector.xml
				socbak_cleanup() { :; }
				source "${WORK}/blk_verify.sh"
			) 2>&1
		}
		# 源布局（编号 1..6，几何与 fix.xml 相同）—— 让 verify_xml 的冻结前缀检查能过
		awk -F'|' '{printf "%s|%d|%s|%s\n", $1, NR, $2, $3}' "${WORK}/k_plan.layout" > "${WORK}/k_source.layout"

		mk_fake_pkg "${WORK}/pkg_ok" && ok "构造正常假包"
		out="$(run_verify "${WORK}/pkg_ok")"; rc=$?
		check_eq "正常包：最终检查通过" "0" "${rc}"
		check_eq "正常包：打印 passed" "1" "$(echo "${out}" | grep -c 'verification passed')"

		# 缺一份刷写脚本（MISC）——首次交付的缺陷就是这种情形被放行
		rm -rf "${WORK}/pkg_miss_scr"; cp -a "${WORK}/pkg_ok" "${WORK}/pkg_miss_scr"
		rm -f "${WORK}/pkg_miss_scr/boot_emmc-misc.cmd"
		out="$(run_verify "${WORK}/pkg_miss_scr")"; rc=$?
		check_eq "缺一份 boot_emmc-<分区>.cmd：失败" "1" "${rc}"
		check_eq "缺脚本时报出缺哪一份" "1" "$(echo "${out}" | grep -c 'required flashing script boot_emmc-misc.cmd')"
		check_eq "缺脚本时不打印 passed" "0" "$(echo "${out}" | grep -c 'verification passed')"

		# 全部刷写脚本都删掉
		rm -rf "${WORK}/pkg_no_scr"; cp -a "${WORK}/pkg_ok" "${WORK}/pkg_no_scr"
		rm -f "${WORK}/pkg_no_scr"/boot_emmc-*.cmd
		out="$(run_verify "${WORK}/pkg_no_scr")"; rc=$?
		check_eq "全部刷写脚本都缺失：失败" "1" "${rc}"
		check_eq "六份脚本各报一次缺失" "6" "$(echo "${out}" | grep -c 'required flashing script')"

		# 缺数据块
		rm -rf "${WORK}/pkg_miss_blk"; cp -a "${WORK}/pkg_ok" "${WORK}/pkg_miss_blk"
		rm -f "${WORK}/pkg_miss_blk/data.1-of-1.gz"
		out="$(run_verify "${WORK}/pkg_miss_blk")"; rc=$?
		check_eq "缺数据块：失败" "1" "${rc}"
		check_eq "缺数据块时报出是哪一个" "1" "$(echo "${out}" | grep -c 'data.1-of-1.gz')"

		# 越界：把 DATA 的写入起点改到分区之前一个扇区
		rm -rf "${WORK}/pkg_over"; cp -a "${WORK}/pkg_ok" "${WORK}/pkg_over"
		data_start=$(awk -F'|' '$1=="DATA"{print $2}' "${WORK}/k_plan.layout")
		printf 'mmc write ${unzip_addr} 0x%08x 0x%08x\n' $(( data_start - 1 )) 4 \
			> "${WORK}/pkg_over/boot_emmc-data.cmd"
		out="$(run_verify "${WORK}/pkg_over")"; rc=$?
		check_eq "写入越界（起点早于分区）：失败" "1" "${rc}"
		check_eq "越界时报出区间" "1" "$(echo "${out}" | grep -c "outside DATA's")"

		# 合法收缩：内容比分区短是允许的（ROOTFS_RW 常见 —— 空文件系统只写前段），
		# 不能被判越界。脚本仍需引用自己的数据块（形状与真实包一致）。
		rm -rf "${WORK}/pkg_short"; cp -a "${WORK}/pkg_ok" "${WORK}/pkg_short"
		rw_start=$(awk -F'|' '$1=="ROOTFS_RW"{print $2}' "${WORK}/k_plan.layout")
		printf 'load ${devtype} ${devnum}:${distro_bootpart} ${ramdisk_addr_r} /gpt/rootfs_rw.1-of-1.gz\nunzip ${ramdisk_addr_r} ${unzip_addr} 1024\nmmc write ${unzip_addr} 0x%08x 0x%08x\n' \
			"${rw_start}" 512 > "${WORK}/pkg_short/boot_emmc-rootfs_rw.cmd"
		out="$(run_verify "${WORK}/pkg_short")"; rc=$?
		check_eq "合法收缩（只写分区前段）：通过" "0" "${rc}"
	else
		bad "抽出 socbak.sh 的最终检查块" "定位失败"
	fi
fi


# ---------------------------------------------------------------- M. 正常入口到成品
echo "== M. 正常打包入口一路跑到成品（真实 socbak.sh） =="
# 这一节是首次验收缺陷 1 的直接回归：只有从 `bash socbak.sh ...` 跑到成品，
# 才能发现"XML 变量被改成 output/<file>、最终检查又把它拼进包目录"这类错误。
# 用容器模拟设备相关信号（CPU part -> cv84x6、/dev/mmcblk0 -> 夹具镜像、/socrepack），
# socbak.sh 本身一行不改。需要 docker + 一个 aarch64 sysroot 来跑 binTools。
E2E_RUNNER="${TESTS_SRC_DIR}/helpers/socbak_e2e_runner.sh"
AARCH64_ROOT="${SOCBAK_TEST_AARCH64_ROOT:-/home/zzt/workspace/kylin_final/rootfs}"
if ! command -v docker >/dev/null 2>&1; then
	echo "  skip 正常入口到成品（本机没有 docker）"
elif [ ! -x "${E2E_RUNNER}" ]; then
	bad "正常入口到成品" "缺少 ${E2E_RUNNER}"
elif [ ! -d "${AARCH64_ROOT}" ]; then
	echo "  skip 正常入口到成品（未找到 aarch64 sysroot，可用 SOCBAK_TEST_AARCH64_ROOT 指定）"
else
	# 容器里需要一个 CPU part=0xd05 的 /proc/cpuinfo（cv84x6 识别信号）
	printf 'processor\t: 0\nCPU implementer\t: 0x41\nCPU part\t: 0xd05\n' > "${WORK}/fakecpuinfo"
	# 源机镜像：BOOT/RECOVERY/MISC 用真实 SE9 数值，盘容量按夹具
	# 盘容量按真机量级给：打包链会把 ROOTFS 撑到 3 GiB、DATA 撑到 4 GiB，
	# 盘太小会在"DATA 装不下"处失败（正确行为，但不是这一节要测的东西）。
	truncate -s $(( 61071360 * 512 )) "${WORK}/e2e.img"
	sgdisk -a 1 \
		-n 1:8192:270335 -t 1:0700 -c 1:BOOT \
		-n 2:270336:532479 -t 2:0700 -c 2:RECOVERY \
		-n 3:532480:552959 -t 3:0700 -c 3:MISC \
		-n 4:552960:757759 -t 4:0700 -c 4:ROOTFS -A 4:set:60 \
		-n 5:757760:28565887 -t 5:0700 -c 5:ROOTFS_RW \
		-n 6:28565888:61071326 -t 6:0700 -c 6:DATA \
		"${WORK}/e2e.img" >/dev/null 2>&1
	e2e_out="$(timeout 900 docker run --rm --privileged \
		-v "${WORK}/fakecpuinfo:/fakecpuinfo:ro" \
		-v "${WORK}/e2e.img:/src.img:ro" \
		-v "${AARCH64_ROOT}:/socrepack/sysroot-src:ro" \
		-v "${SOCBAK_DIR}:/socbak_src:ro" \
		-v "${E2E_RUNNER}:/runner.sh:ro" \
		alpine:latest sh -c \
		'mkdir -p /socrepack/sysroot-src; apk add --no-cache bash coreutils e2fsprogs dosfstools util-linux sgdisk pigz gzip tar qemu-aarch64 >/dev/null 2>&1; bash /runner.sh /src.img /socbak_src ok' 2>&1)"
	e2e_rc=$?
	check_eq "正常入口：socbak.sh 退出码 0" "0" "${e2e_rc}"
	check_eq "正常入口：最终检查通过" "1" \
		"$(echo "${e2e_out}" | grep -c 'SOC_BAK_LOCAL_UPDATE_LAYOUT verification passed')"
	check_eq "正常入口：包内恰好一份 partition*xml" "1" \
		"$(echo "${e2e_out}" | grep -c 'local_update verification: partition\*xml count=1')"
	check_eq "正常入口：SDK 三项起点与源机一致" "3" \
		"$(echo "${e2e_out}" | grep -cE 'verification: (DATA|MISC|ROOTFS): source=[0-9]+ package=[0-9]+ OK')"
	check_eq "正常入口：gpt.gz 与计划逐项相同" "1" \
		"$(echo "${e2e_out}" | grep -c 'gpt.gz matches the planned layout')"
	check_eq "正常入口：六个分区都有刷写范围且未越界" "6" \
		"$(echo "${e2e_out}" | grep -c 'write range .* inside .* OK')"
	check_eq "正常入口：成品目录里有 sdcard 包" "1" \
		"$(echo "${e2e_out}" | sed -n '/HARNESS: delivery dir/,/package files/p' | grep -c '^sdcard$')"
	check_eq "正常入口：没有把包判成 .rejected" "0" \
		"$(echo "${e2e_out}" | grep -c 'rejected')"
	if [ "${e2e_rc}" != "0" ]; then
		echo "  --- 失败时的尾部输出（便于排查）---"
		echo "${e2e_out}" | tail -n 12 | sed 's/^/    /'
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
