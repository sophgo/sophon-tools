#!/bin/bash
# pcv84x6_llm_server 统一构建接口 (对齐 sophon-tools M1 规范)
#
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64（默认）| all（等同 arm64，唯一支持的平台）
#   VERSION: 显式版本号。只用于与源码版本核对：不一致时拒绝构建（不修改源码）。
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pcv84x6_llm_server/）
#
# 产物: cv84x6-llm-server_<ver>_arm64.deb + .sha256
#   - 包名/版本/安装路径与原仓库发布纪律一致：版本唯一来源是 app/__init__.py，
#     不在此处硬编码，不 bump，不覆盖原仓库 release。
#   - 引擎库与 qwen3_5 基础配置取 build/inputs/（SHA256 固定，构建时校验）；
#     Web 控制台从 web/ 源码 + lockfile 现场构建。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
GIVEN_VERSION="${2:-}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pcv84x6_llm_server}"

# ---- ARCH: 只支持 arm64（CV84X6 是 aarch64 SoC）--------------------------
case "$ARCH" in
  arm64|all) ;;
  amd64|x86_64|armhf|armel|riscv64|loongarch64|sw_64|windows)
    echo "ERROR: pcv84x6_llm_server 只支持 arm64（CV84X6 为 aarch64 平台），得到: $ARCH" >&2
    exit 1 ;;
  *)
    echo "ERROR: ARCH 必须是 arm64 或 all，得到: $ARCH" >&2
    exit 1 ;;
esac

# ---- 版本: 唯一来源 app/__init__.py；显式 VERSION 不一致即拒绝 -------------
VERSION="$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"", open("app/__init__.py").read()).group(1))')"
if [ -n "$GIVEN_VERSION" ] && [ "$GIVEN_VERSION" != "$VERSION" ]; then
  echo "ERROR: 显式 VERSION=$GIVEN_VERSION 与源码版本 app/__init__.py=$VERSION 不一致（版本只能来自源码，不允许改源码迁就参数）" >&2
  exit 1
fi

# ---- 固定构建输入校验（摘要不符即失败，杜绝旧库/浮动输入）-------------------
INPUTS="$SCRIPT_DIR/build/inputs"
[ -f "$INPUTS/lib/libcv84x6_llm.so" ] || { echo "ERROR: 缺少固定输入 $INPUTS/lib/libcv84x6_llm.so（见 build/README.md）" >&2; exit 1; }
[ -f "$INPUTS/qwen3_5-config/tokenizer.json" ] || { echo "ERROR: 缺少固定输入 $INPUTS/qwen3_5-config/tokenizer.json（见 build/README.md）" >&2; exit 1; }
( cd "$INPUTS" && sha256sum -c SHA256SUMS --quiet ) || {
  echo "ERROR: build/inputs/SHA256SUMS 校验失败——固定输入被改动或损坏（见 build/README.md）" >&2
  exit 1
}

# ---- 构建 -----------------------------------------------------------------
echo "==> pcv84x6_llm_server build arch=$ARCH version=$VERSION"
echo "    Web 控制台: node $(node --version 2>/dev/null || echo missing) 从 web/ 源码构建"
bash scripts/build_web.sh
echo "    打包（引擎库/基础配置来自 build/inputs，摘要已校验）"
bash scripts/package_deb.sh \
  --lib "$INPUTS/lib/libcv84x6_llm.so" \
  --config "$INPUTS/qwen3_5-config" \
  --out "$OUTPUT_DIR"

DEB="$OUTPUT_DIR/cv84x6-llm-server_${VERSION}_arm64.deb"
[ -f "$DEB" ] || { echo "ERROR: 未找到产物 $DEB" >&2; exit 1; }

echo "==> pcv84x6_llm_server 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
