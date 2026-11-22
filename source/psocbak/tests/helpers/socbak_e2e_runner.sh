#!/bin/bash
# 以真实入口跑 socbak.sh，验证「正常参数 -> 成品包」这条链。
# 只在容器里做设备相关的模拟，脚本本身一行不改（这是首次交付漏掉的那一环）。
#
# 用法（由 local_update_layout.sh 的 M 节在容器里调用）：
#   socbak_e2e_runner.sh <image> <socbak_src_dir> <scenario>
# 目前只跑正常包（scenario=ok）；缺脚本/缺块/越界这些失败路径由 local_update_layout.sh
# 的 L 节直接驱动 socbak.sh 的最终检查块来覆盖（那里能精确改包并拿到退出码）。
#
# 为什么必须走真入口：首次交付就是"只测了函数"，而真实入口把 XML 变量改成了
# output/<file>，最终检查又把它拼到包目录下，找的是 output/sdcard/output/<file> ——
# 合法包被拒。只有从 `bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1`
# 一路跑到成品，才会暴露这种变量命名错误。
#
# 环境要求（容器内）：bash coreutils e2fsprogs dosfstools util-linux sgdisk pigz qemu-aarch64
# 以及挂在 /socrepack/sysroot-src 的 glibc sysroot（binTools 里四个动态链接工具需要）。
set -u

# 全程只读宿主准备的普通 boot0 文件。若容器映射不符，在任何写操作前退出。
if [ ! -f /.dockerenv ] || [ ! -f /dev/mmcblk0boot0 ] || [ ! -s /dev/mmcblk0boot0 ]; then
	echo "Expected a container with a regular boot0 fixture" >&2
	exit 2
fi

IMG="$1"
SOCBAK_SRC="$2"
SCENARIO="${3:-ok}"

# ---- 容器内的准备 -----------------------------------------------------------
mkdir -p /proc && mount -t proc proc /proc 2>/dev/null
mount --bind /fakecpuinfo /proc/cpuinfo 2>/dev/null
mkdir -p /dev
# 芯片识别走 CPU part=0xd05 -> cv84x6；all-in-one 链里的 lsblk 只用于找分区名
mkdir -p /bin
mkdir -p /usr/local/bin
cat > /usr/local/bin/lsblk <<'EOF'
#!/bin/sh
# 只模拟 socbak 用到的两件事：mmcblk0 的字节数、以及"哪个分区在 eMMC 上"
if [ "${1:-}" = "-b" ]; then
	echo "mmcblk0      179:0    0 31268536320  0 disk"
	exit 0
fi
cat <<'EOT'
NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
mmcblk0     179:0    0 29.1G  0 disk
mmcblk0p1   179:1    0  128M  0 part /boot
mmcblk0p2   179:2    0  128M  0 part /recovery
mmcblk0p3   179:3    0   10M  0 part
mmcblk0p4   179:4    0    6G  0 part /media/root-ro
mmcblk0p5   179:5    0  5.9G  0 part /media/root-rw
mmcblk0p6   179:6    0   17G  0 part /data
EOT
EOF
chmod +x /usr/local/bin/lsblk
# rootfs 要打整个 /：给一份够小但又"像系统"的内容。
# 这些目录在真机上是独立挂载点，socbak 会用 `df -B1 -l /<part>` 读已用空间。
# 容器里**不要**给它们挂 tmpfs：tar 会恢复目录自身的权限/属主，而挂载点根目录
# 无法 chmod，会让 tar 以 "Cannot change mode" 失败（容器产物，不是被测代码问题）。
# 但普通目录在 df 里与根分区同一条，`grep " /boot$"` 取不到 → `$(( part_use * 3 ))`
# 会退化成 `$(( * 3))` 算术错误。所以用 df 垫片补这几行，其余转给真 df。
for d in boot recovery data media/root-ro media/root-rw; do
	mkdir -p "/$d"
done
cat > /usr/local/bin/df <<'EOF'
#!/bin/sh
# socbak 只需要 `df -B1 -l <path>` 的「已用字节数」；容器里这些目录不单独挂载，
# 真 df 不会给出匹配行，所以这里为它们合成一行（1 MiB 已用，远小于任何分区）。
case "$*" in
	*"-B1 -l /boot"*|*"-B1 -l /recovery"*|*"-B1 -l /data"*|*"-B1 -l /media/root-ro"*|*"-B1 -l /media/root-rw"*)
		p=""
		for a in "$@"; do case "$a" in /*) p="$a" ;; esac; done
		echo "Filesystem 1B-blocks Used Available Use% Mounted on"
		echo "/dev/mock 67108864 1048576 66060288 2% ${p}"
		exit 0
		;;
esac
exec /usr/bin/df "$@"
EOF
chmod +x /usr/local/bin/df
export PATH="/usr/local/bin:${PATH}"
for i in $(seq 1 40); do echo "rootfs file $i" > "/usr/file_$i.txt" 2>/dev/null || :; done
echo "kernel" > /boot/boot.itb
echo "recovery-script" > /recovery/boot.scr
echo "data payload" > /data/payload.txt
echo "ro content" > /media/root-ro/ro.txt
echo "rw content" > /media/root-rw/rw.txt

# 源机 GPT：socbak 只读 SOCBAK_LOCAL_UPDATE_SOURCE。
# 默认是 /dev/mmcblk0；这里直接指向夹具镜像文件 —— 读 GPT 只需要普通文件，
# 而把镜像挂成 loop 会占掉容器里有限的 loop 设备，后面 mount 各个分区镜像就没得用了。
# （真机上 SOCBAK_LOCAL_UPDATE_SOURCE 就是 /dev/mmcblk0，读法完全一致。）
SOCBAK_SRC_IMG="$IMG"

# The read-only source image and ARM64 libraries sit under /socrepack,
# which socbak excludes when archiving the container root.
cp -a "$SOCBAK_SRC"/. /socrepack/ || exit 2
cd /socrepack || exit 2
export QEMU_LD_PREFIX=/socrepack/sysroot-src

export SOC_BAK_LOCAL_UPDATE_LAYOUT=1
export SOC_BAK_ALL_IN_ONE=1
export SOCBAK_LOCAL_UPDATE_SOURCE="$SOCBAK_SRC_IMG"

echo "=== HARNESS: starting socbak.sh ($SCENARIO) ==="
bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1 > /tmp/socbak_run.log 2>&1
RC=$?
echo "=== HARNESS: socbak.sh rc=$RC ==="
if [ "$RC" != 0 ]; then
    tail -n 40 /tmp/socbak_run.log
    exit "$RC"
fi
grep -E 'frozen sizes \(applied|local_update verification:|SOC_BAK_LOCAL_UPDATE_LAYOUT verification passed' /tmp/socbak_run.log
(cd output/sdcard && md5sum --quiet -c md5.txt) || exit 1
echo "--- output dir:"
ls -la /socrepack/output/ 2>&1 | head -20
echo "--- package dir:"
ls -la /socrepack/output/sdcard/ 2>&1 | head -30
# 交付目录与关键证据，交给调用方断言
echo "=== HARNESS: delivery dir ==="
ls -1 /socrepack/output/ 2>&1
echo "=== HARNESS: package files ==="
ls -1 /socrepack/output/sdcard/ 2>&1 | head -40
echo "=== HARNESS: plan ==="
cat /socrepack/local_update_plan.layout 2>/dev/null
echo "=== HARNESS: source layout ==="
cat /socrepack/local_update_source.layout 2>/dev/null
exit "$RC"
