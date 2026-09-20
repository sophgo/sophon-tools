#!/bin/bash
# psewriter (SE写卡工具) 统一构建接口 (sophon-tools M1 规范)
#
# 本目录只放说明文档；Go 代码与构建脚本都在 src/。这个脚本是统一构建入口
# （docker/build-all.sh 固定执行 source/<子项目>/release.sh），转发给 src/release.sh。
#
# 用法与产物见 src/release.sh --help 或 BUILD.md。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec bash "${SCRIPT_DIR}/src/release.sh" "$@"
