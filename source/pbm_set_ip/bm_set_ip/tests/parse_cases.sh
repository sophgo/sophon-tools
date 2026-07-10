#!/usr/bin/env bash
# bm_set_ip 组模式解析器自动化测试(薄包装)。
# 实际用例已融入 cargo test(tests/parse_cases.rs),经 --dry-run 无实施模式驱动。
# 用法:
#   bash tests/parse_cases.sh              # 等价 cargo test --test parse_cases
#   bash tests/parse_cases.sh --no-fail-fast
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$CRATE_DIR"
export PATH="${PATH}:$HOME/.cargo/bin"
exec cargo test --test parse_cases "$@"
