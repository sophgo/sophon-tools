#!/bin/bash
# x86 构建（开发机/PCIE 主机定位：宿主 gcc 动态链接，非部署镜像标准；
# 设备端使用 arm64 的 musl 全静态产物 —— build-bmssm-arm64.sh）
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-2.1.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

LDFLAGS="-s -w -X bmssm/global.version=${VERSION} -X bmssm/global.gitCommit=${COMMIT} -X bmssm/global.buildTime=${BUILDTIME}"

CGO_ENABLED=1 go build -trimpath -ldflags "${LDFLAGS}" -o bmssm .

# strip release 冗余：删 .comment（工具链版本注释）与 .note.go.buildid（构建 ID），
# 并 --strip-unneeded 兜底清局部符号；strip 不可用时静默跳过（产物仍带 -s -w）。
for c in strip llvm-strip; do
  if command -v "$c" >/dev/null 2>&1; then
    "$c" --strip-unneeded --remove-section=.comment --remove-section=.note.go.buildid bmssm \
      && echo "strip $c ok" || echo "WARN: strip 失败（跳过）" >&2
    break
  fi
done

mkdir -p release
cp bmssm release/
cp config/bmssm.yaml release/
echo "built release/bmssm (x86)"
