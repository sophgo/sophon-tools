#!/bin/bash
# pautotelecomm 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    仅 arm64（默认，设备 SE5/7/9）。rootfs 内 quectel-CM/dhclient 为
#            aarch64 预编译二进制，本子项目不支持 amd64，传入其他值将报错退出。
#   VERSION: 显式版本号（默认 1.2.8）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pautotelecomm/）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR" || exit 1   # 打包源/产物路径全部以本脚本目录为基准，消除对调用方 cwd 的依赖
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
VERSION="${2:-1.2.8}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pautotelecomm}"

# 本子项目仅支持 arm64（rootfs 内为 aarch64 预编译二进制），明确拒绝其他架构
case "$ARCH" in
  arm64) ;;
  *) echo "ERROR: pautotelecomm 仅支持 arm64（rootfs 内含 aarch64 预编译二进制 quectel-CM/dhclient），不支持 ARCH=$ARCH" >&2; exit 1 ;;
esac

# 版本号校验：必须为纯数字版本，防止含 / 或空值污染文件名
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: VERSION 非法（应为数字版本号，如 1.2.8），得到: '$VERSION'" >&2
    exit 1
fi

INSTALL_SCRIPT="$SCRIPT_DIR/output/autotelecomm_install_${VERSION}.sh"
TARBALL="$SCRIPT_DIR/output/packages.tgz"

echo "==> pautotelecomm build arch=$ARCH version=$VERSION"

rm -rf "$SCRIPT_DIR/output"
mkdir -p "$SCRIPT_DIR/output"

cat <<EOF > "$INSTALL_SCRIPT"
#!/bin/bash
# autotelecomm 一键安装脚本（由 release.sh 生成，VERSION=${VERSION}）
# 产物自带解包+安装逻辑：后半部分拼接 packages.tgz（见末尾 __ARCHIVE_BELOW__）

if [ "\$(id -u)" != "0" ]; then
    echo "ERROR: 需要 root 权限执行（安装将写入 / 目录、注册 systemd 服务、安装内核模块并调用 pip 安装系统包）"
    echo "       请以 root 身份执行: sudo bash \$0"
    exit 1
fi

TMP_DIR=\$(mktemp -d)
trap "rm -rf \$TMP_DIR" EXIT

offset=\$(grep -an "__ARCHIVE_BELOW__" "\$0" | tail -n1 | cut -d: -f1)
((offset++))
tail -n +\$offset "\$0" > "\$TMP_DIR/packages.tgz"
tar -xavf "\$TMP_DIR/packages.tgz" -C "\$TMP_DIR" || exit

systemctl daemon-reload
systemctl stop autotelecomm
systemctl stop ec20

echo "[install rootfs] start ..."
pushd "\${TMP_DIR}/rootfs" || exit
# rootfs 目录即安装载荷（含 etc/usr 目标路径），整体平铺拷贝到根目录
cp -r ./* / || exit
popd || exit
sync

echo "[install kernel mod] start ..."
pushd "\${TMP_DIR}/kernel" || exit
bash install.sh || exit
popd || exit
sync

if [[ "\$(python3 -m pip list | grep pyserial | wc -l)" == "0" ]]; then
    echo "not find pyserial by python, need install ..."
    python3 -m pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple pyserial
fi

systemctl daemon-reload
systemctl stop lteModemManager
systemctl disable lteModemManager
sync

echo "[install] success, please restart this device"
exit 0
__ARCHIVE_BELOW__
EOF

tar -caf "$TARBALL" rootfs kernel

cat "$TARBALL" >> "$INSTALL_SCRIPT"

chmod +x "$INSTALL_SCRIPT"

mkdir -p "$OUTPUT_DIR"
cp "$INSTALL_SCRIPT" "$OUTPUT_DIR/"
echo "==> pautotelecomm 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
