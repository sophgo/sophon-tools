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
# 以及挂在 /opt/aarch64-root 的 glibc sysroot（binTools 里四个动态链接工具需要）。
set -u

IMG="$1"
SOCBAK_SRC="$2"
SCENARIO="${3:-ok}"

# ---- 容器内的准备 -----------------------------------------------------------
mkdir -p /proc && mount -t proc proc /proc 2>/dev/null
mount --bind /fakecpuinfo /proc/cpuinfo 2>/dev/null
mkdir -p /dev
# socbak 在 all-in-one 前会 `dd if=/dev/mmcblk0boot0` 取 fip.bin。
# 这里造一个真实（非符号链接）的普通文件当 boot0，并写入非零内容 ——
# 全零时打包链会认为"没取到 fip"而跳过，包是不完整的。
dd if=/dev/urandom of=/dev/mmcblk0boot0 bs=1024 count=1024 status=none
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

# /socrepack：socbak 要求工作目录在这个路径下
# sysroot 的 bind 挂载点是 /socrepack/sysroot-src，必须先建好目录再让 docker 挂上，
# 且必须在 `cp -a "$SOCBAK_SRC"/.` 之前 —— 否则复制会把它盖掉。
mkdir -p /socrepack/sysroot-src
cp -a "$SOCBAK_SRC"/. /socrepack/
cd /socrepack || exit 2

# binTools 里 advcp/advmv/mkfs.fat/fsck.fat 是**动态链接**的 aarch64，
# 需要一份 glibc sysroot 才能在 qemu 下跑（qemu-aarch64-static 由 --privileged 下的 binfmt 接管）。
# sysroot 从 /socrepack/sysroot-src（容器的 bind 挂载点）复制到 /socrepack/.sysroot：
# 挂载点本身就在 /socrepack 下，因为 socbak 打 rootfs 时会排除 ./socrepack；
# 放在 / 的其他位置（/opt、/aarch64-root、/sysroot-src 等）会被打进 rootfs 镜像，
# 把 100 MiB 的 ROOTFS 分区撑爆 —— 那会让回归在本该成功的地方失败。
if [ -d /socrepack/sysroot-src ]; then
	rm -rf /socrepack/.sysroot
	mkdir -p /socrepack/.sysroot
	cp -a /socrepack/sysroot-src/. /socrepack/.sysroot/ 2>/dev/null || :
	export QEMU_LD_PREFIX=/socrepack/.sysroot
	for t in mkfs.fat fsck.fat; do
		if [ -x "/socrepack/sysroot-src/usr/sbin/$t" ]; then
			printf '#!/bin/sh\nexec qemu-aarch64-static -L /socrepack/.sysroot /socrepack/sysroot-src/usr/sbin/%s "$@"\n' "$t" > "/tmp/$t"
			chmod +x "/tmp/$t"
		fi
	done
	export PATH="/tmp:$PATH"
fi

export SOC_BAK_LOCAL_UPDATE_LAYOUT=1
export SOC_BAK_ALL_IN_ONE=1
export SOCBAK_LOCAL_UPDATE_SOURCE="$SOCBAK_SRC_IMG"

echo "=== HARNESS: starting socbak.sh ($SCENARIO) ==="
bash socbak.sh SOC_BAK_ALL_IN_ONE=1 SOC_BAK_LOCAL_UPDATE_LAYOUT=1 > /tmp/socbak_run.log 2>&1
RC=$?
echo "=== HARNESS: socbak.sh rc=$RC ==="
echo "--- last 25 log lines:"
tail -n 25 /tmp/socbak_run.log
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
