#!/bin/bash
# bmssm .deb 打包：交叉编译 arm64 静态二进制 + 组装 deb 数据树 + dpkg-deb。
# 用法: bash build/build-deb-bmssm.sh [VERSION] [ARCH] [REASONIX_BIN]
#   VERSION      默认从 version.sh DEFAULT_VERSION 提取
#   ARCH         默认 arm64（设备）；amd64 用于 PCIE/开发机
#   REASONIX_BIN 可选：reasonix arm64 二进制路径。提供则把 Reasonix 一并嵌入 deb，
#               安装到 /opt/sophon/reasonix/bin/reasonix（嵌入前自动 strip 去
#               debug 信息减体积，MYSWY 要求 2026-08-27），并在 bmssm.yaml 里把
#               agentproxy.binaryPath 指向它（出厂即带 AI Agent 后端）。
#               省略则只打 bmssm（Reasonix 需后续单独部署）。
#
# 产物（单一变体，内嵌 bmssm；REASONIX_BIN 提供时一并内嵌 reasonix）：
#   release/bmssm_${VERSION}_${ARCH}.deb   出厂默认：Reasonix（默认配置，不预载任何 skill）
#                                          + 通用 agent 提示词（不体现具体型号）
# 提示词与 Reasonix 配置来源：build/reasonix/（prompts/system.md + config.toml）。
set -e

cd "$(dirname "$0")/.."
# 版本默认值从 version.sh 的 DEFAULT_VERSION（唯一权威）提取，禁止在此硬编码
VERSION="${1:-$(grep -oE '^DEFAULT_VERSION="[^"]+"' "$(dirname "$0")/version.sh" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
VERSION="${VERSION//\//-}"
ARCH="${2:-arm64}"
REASONIX_BIN="${3:-${REASONIX_BIN:-}}"

# 构建 bmssm 二进制（arm64 走 musl 静态；amd64 用宿主 gcc）
if [ "$ARCH" = "arm64" ]; then
  bash build/build-bmssm-arm64.sh "$VERSION"
else
  bash build/build-bmssm.sh "$VERSION"
fi

RX_SRC="$(cd build/reasonix && pwd)"   # Reasonix 提示词 / 配置资源

# assemble_deb
assemble_deb() {
  local DEBROOT="build/deb/bmssm-root"
  local OUT="release/bmssm_${VERSION}_${ARCH}.deb"

  rm -rf "$DEBROOT"
  mkdir -p "$DEBROOT/DEBIAN" \
           "$DEBROOT/opt/sophon/bmssm/bin" \
           "$DEBROOT/opt/sophon/bmssm/config" \
           "$DEBROOT/usr/lib/systemd/system"

  cp release/bmssm "$DEBROOT/opt/sophon/bmssm/bin/bmssm"
  chmod 0755 "$DEBROOT/opt/sophon/bmssm/bin/bmssm"
  cp release/bmssm.yaml "$DEBROOT/opt/sophon/bmssm/config/bmssm.yaml"
  cp build/bmssm.service "$DEBROOT/usr/lib/systemd/system/bmssm.service"

  # 嵌入 Reasonix（若指定）：铺二进制 + 启用 agentproxy
  if [ -n "$REASONIX_BIN" ]; then
    mkdir -p "$DEBROOT/opt/sophon/reasonix/bin"
    cp "$REASONIX_BIN" "$DEBROOT/opt/sophon/reasonix/bin/reasonix"
    chmod 0755 "$DEBROOT/opt/sophon/reasonix/bin/reasonix"
    # 去 debug 信息减体积（MYSWY 要求，2026-08-27）：对 deb 树内副本 strip，
    # 不动源文件（可能是 git 跟踪的内置二进制）；已 stripped 的输入幂等无害。
    # 与 build-bmssm-arm64.sh 同款风格：交叉 strip 优先，失败降级警告不阻断。
    strip_reasonix() {
      local dest="$DEBROOT/opt/sophon/reasonix/bin/reasonix"
      case "$ARCH" in
        arm64) for c in aarch64-linux-musl-strip aarch64-linux-gnu-strip; do
                 command -v "$c" >/dev/null 2>&1 && "$c" --strip-unneeded \
                   --remove-section=.comment --remove-section=.note.go.buildid "$dest" \
                   && return 0
               done ;;
        amd64) for c in x86_64-linux-gnu-strip strip llvm-strip; do
                 command -v "$c" >/dev/null 2>&1 && "$c" --strip-unneeded \
                   --remove-section=.comment --remove-section=.note.go.buildid "$dest" \
                   && return 0
               done ;;
      esac
      return 1
    }
    if [ -n "$REASONIX_BIN" ]; then RX_BEFORE_MB=$(( $(stat -c%s "$DEBROOT/opt/sophon/reasonix/bin/reasonix") / 1024 / 1024 )); fi
    if strip_reasonix; then
      RX_AFTER_MB=$(( $(stat -c%s "$DEBROOT/opt/sophon/reasonix/bin/reasonix") / 1024 / 1024 ))
      echo "  ✓ reasonix strip: ${RX_BEFORE_MB}MB → ${RX_AFTER_MB}MB"
    else
      echo "  WARN: reasonix strip 未执行（无可用 strip 工具），保留原样" >&2
    fi
    sed -i \
      -e 's|^  enabled: false.*|  enabled: true|' \
      -e "s|^  binaryPath: \"\".*|  binaryPath: \"/opt/sophon/reasonix/bin/reasonix\"|" \
      "$DEBROOT/opt/sophon/bmssm/config/bmssm.yaml"
  fi

  # Reasonix 运行主目录（reasionix HOME=/data/sophon/reasonix-home）
  local RXM="$DEBROOT/data/sophon/reasonix-home"
  mkdir -p "$RXM/.reasonix" "$RXM/prompts"

  # 出厂默认配置：不预载任何 skill，带通用 agent 提示词
  cp "$RX_SRC/prompts/system.md" "$RXM/prompts/system.md"
  cp "$RX_SRC/config.toml" "$RXM/.reasonix/config.toml"
  echo "  ✓ 默认配置（不预载 skill，通用提示词）"

  # DEBIAN 控制文件
  sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" \
    build/deb/bmssm.control > "$DEBROOT/DEBIAN/control"
  cp build/deb/postinst "$DEBROOT/DEBIAN/postinst"
  cp build/deb/prerm    "$DEBROOT/DEBIAN/prerm"
  cp build/deb/postrm   "$DEBROOT/DEBIAN/postrm"
  # 空 preinst：新旧包都带同名维护脚本，避免 dpkg 升级时触发
  # "unable to remove obsolete info file '...preinst'" 报错中断解包
  cp build/deb/preinst  "$DEBROOT/DEBIAN/preinst"
  # 全量可选控制成员：同理由，保证新旧包 info 成员集合一致，dpkg 升级直接覆盖
  # 而非走"删除 obsolete info"分支（overlayfs 重装环境下该分支会因 whiteout
  # 条目报 ENOENT 中断解包，bmssm/sophliteos 发版实测）
  cp build/deb/changelog "$DEBROOT/DEBIAN/changelog"
  cp build/deb/triggers  "$DEBROOT/DEBIAN/triggers"
  cp build/deb/templates "$DEBROOT/DEBIAN/templates"
  cp build/deb/config    "$DEBROOT/DEBIAN/config"
  cp build/deb/conffiles "$DEBROOT/DEBIAN/conffiles"
  chmod 0755 "$DEBROOT/DEBIAN/postinst" "$DEBROOT/DEBIAN/prerm" "$DEBROOT/DEBIAN/postrm" "$DEBROOT/DEBIAN/preinst" "$DEBROOT/DEBIAN/config"
  chmod 0644 "$DEBROOT/DEBIAN/changelog" "$DEBROOT/DEBIAN/triggers" "$DEBROOT/DEBIAN/templates"
  chmod 0644 "$DEBROOT/DEBIAN/control" "$DEBROOT/DEBIAN/conffiles"

  # md5sums
  ( cd "$DEBROOT" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' | \
    sort -z | xargs -0 md5sum ) > "$DEBROOT/DEBIAN/md5sums"

  dpkg-deb --root-owner-group -b "$DEBROOT" "$OUT"
  rm -rf "$DEBROOT"
  echo "✓ built $OUT"
}

mkdir -p release
assemble_deb

echo
echo "=== 产物 ==="
for f in release/bmssm_${VERSION}_${ARCH}*.deb; do
  [ -e "$f" ] && echo "  $f"
done
