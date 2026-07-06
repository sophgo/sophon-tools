#!/bin/bash
# x86 构建
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-1.0.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

LDFLAGS="-s -w -X ssm/global.version=${VERSION} -X ssm/global.gitCommit=${COMMIT} -X ssm/global.buildTime=${BUILDTIME}"

CGO_ENABLED=1 go build -trimpath -ldflags "${LDFLAGS}" -o ssm .

mkdir -p release
cp ssm release/
cp config/ssm.yaml release/
echo "built release/ssm (x86)"
