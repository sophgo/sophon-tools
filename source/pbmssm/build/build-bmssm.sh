#!/bin/bash
# x86 构建
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-2.0.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

LDFLAGS="-s -w -X bmssm/global.version=${VERSION} -X bmssm/global.gitCommit=${COMMIT} -X bmssm/global.buildTime=${BUILDTIME}"

CGO_ENABLED=1 go build -trimpath -ldflags "${LDFLAGS}" -o bmssm .

mkdir -p release
cp bmssm release/
cp config/bmssm.yaml release/
echo "built release/bmssm (x86)"
