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
# 产物（两个变体，均内嵌 bmssm；REASONIX_BIN 提供时均内嵌 reasonix）：
#   release/bmssm_${VERSION}_${ARCH}_noskill.deb   出厂默认：Reasonix（默认配置，无 SE 系列 skill）
#                                                    + 通用 SE 系列 agent 提示词（不体现具体型号）
#   release/bmssm_${VERSION}_${ARCH}_seskill.deb   带 SE 系列 skill：预载 se-series-knowledge-base
#                                                    多型号知识库（SE7/SE8/SE9）+ SE 系列 agent 提示词
#                                                    + se-rag 检索二进制 + 对应 Reasonix 配置
# SE 系列资源来源：build/se-series-skill/（SKILL.md + docs + Go 索引 + 提示词 + 两套 reasonix 配置）
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

# 构建 se-rag 检索核心二进制（仅 seskill 变体需要；x86/arm64 均静态）
SE_RAG_BIN=""
if [ -d ../se-rag-core ]; then
  SE_RAG_DIR="$(cd ../se-rag-core && pwd)"
  mkdir -p /tmp/se-rag-build
  (cd "$SE_RAG_DIR" && GOOS=linux GOARCH="$ARCH" CGO_ENABLED=0 go build -trimpath -o "/tmp/se-rag-build/se-rag" ./cmd/se-rag)
  SE_RAG_BIN="/tmp/se-rag-build/se-rag"
  echo "✓ 已构建 se-rag ($ARCH): $SE_RAG_BIN"
fi

SE_SRC="$(cd build/se-series-skill && pwd)"   # SE 系列 skill/提示词/索引等资源

# assemble_deb <suffix> <with_seskill: 1|0>
assemble_deb() {
  local suffix="$1" with_seskill="$2"
  local DEBROOT="build/deb/bmssm-root"
  local OUT="release/bmssm_${VERSION}_${ARCH}${suffix}.deb"

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
      echo "  ✓ [$suffix] reasonix strip: ${RX_BEFORE_MB}MB → ${RX_AFTER_MB}MB"
    else
      echo "  WARN: [$suffix] reasonix strip 未执行（无可用 strip 工具），保留原样" >&2
    fi
    sed -i \
      -e 's|^  enabled: false.*|  enabled: true|' \
      -e "s|^  binaryPath: \"\".*|  binaryPath: \"/opt/sophon/reasonix/bin/reasonix\"|" \
      "$DEBROOT/opt/sophon/bmssm/config/bmssm.yaml"
  fi

  # Reasonix 运行主目录（reasionix HOME=/data/sophon/reasonix-home）
  local RXM="$DEBROOT/data/sophon/reasonix-home"
  mkdir -p "$RXM/.reasonix"

  if [ "$with_seskill" = "1" ]; then
    if [ -z "$SE_RAG_BIN" ]; then
      echo "ERROR: [_seskill] 变体需要 se-rag 二进制（source/se-rag-core 缺失或构建失败），中止" >&2
      rm -rf "$DEBROOT"
      exit 1
    fi
    # ===== seskill 变体：预载 SE 系列多型号 skill + agent 提示词 + se-rag =====
    # 1) se-rag 检索二进制
    mkdir -p "$RXM/bin"
    cp "$SE_RAG_BIN" "$RXM/bin/se-rag"
    chmod 0755 "$RXM/bin/se-rag"
    # 2) se-series-knowledge-base skill（SKILL.md + docs/se7,se8,se9 + 三套 Go 索引）
    local SK="$RXM/skills/se-series-knowledge-base"
    mkdir -p "$SK/rag"
    cp "$SE_SRC/SKILL.md" "$SK/SKILL.md"
    cp -r "$SE_SRC/docs/." "$SK/docs/"
    for p in se7 se8 se9; do
      mkdir -p "$SK/rag/data_$p"
      cp -a "$SE_SRC/rag/data_$p/." "$SK/rag/data_$p/"   # 含 .complete 完成标记（Open 依赖）
    done
    # 3) SE 系列 agent 提示词（多型号版）
    mkdir -p "$RXM/prompts"
    cp "$SE_SRC/prompts/system.seskill.md" "$RXM/prompts/system.md"
    # 4) SE 系列 Reasonix 配置（引用 skill + system_prompt_file）
    cp "$SE_SRC/reasonix/config.toml" "$RXM/.reasonix/config.toml"
    echo "  ✓ [$suffix] 已预载 SE 系列 skill（SE7/SE8/SE9）+ agent 提示词 + se-rag"
  else
    # ===== 默认（noskill）变体：Reasonix 默认配置，无 SE 系列 skill；带通用提示词 =====
    mkdir -p "$RXM/prompts"
    cp "$SE_SRC/prompts/system.noskill.md" "$RXM/prompts/system.md"
    cp "$SE_SRC/reasonix/config.noskill.toml" "$RXM/.reasonix/config.toml"
    echo "  ✓ [$suffix] 默认配置（无 SE 系列 skill，通用提示词）"
  fi

  # DEBIAN 控制文件
  sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" \
    build/deb/bmssm.control > "$DEBROOT/DEBIAN/control"
  cp build/deb/postinst "$DEBROOT/DEBIAN/postinst"
  cp build/deb/prerm    "$DEBROOT/DEBIAN/prerm"
  cp build/deb/postrm   "$DEBROOT/DEBIAN/postrm"
  cp build/deb/conffiles "$DEBROOT/DEBIAN/conffiles"
  chmod 0755 "$DEBROOT/DEBIAN/postinst" "$DEBROOT/DEBIAN/prerm" "$DEBROOT/DEBIAN/postrm"
  chmod 0644 "$DEBROOT/DEBIAN/control" "$DEBROOT/DEBIAN/conffiles"

  # md5sums
  ( cd "$DEBROOT" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' | \
    sort -z | xargs -0 md5sum ) > "$DEBROOT/DEBIAN/md5sums"

  dpkg-deb --root-owner-group -b "$DEBROOT" "$OUT"
  rm -rf "$DEBROOT"
  echo "✓ built $OUT"
}

mkdir -p release
assemble_deb "_noskill" 0
assemble_deb "_seskill" 1

echo
echo "=== 产物 ==="
for f in release/bmssm_${VERSION}_${ARCH}*.deb; do
  [ -e "$f" ] && echo "  $f"
done
