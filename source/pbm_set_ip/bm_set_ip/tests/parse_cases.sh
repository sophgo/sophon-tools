#!/usr/bin/env bash
# bm_set_ip 组模式解析器自动化测试
# 通过 --dry-run 无实施模式驱动,对固定格式输出做断言。
# 用法: bash tests/parse_cases.sh [binary_path]
#   不传 binary_path 则自动 cargo build --release (host) 并使用产物。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -ge 1 ]]; then
  BIN="$1"
else
  echo "[setup] building host release binary..."
  (cd "$CRATE_DIR" && PATH="${PATH}:$HOME/.cargo/bin" cargo build --release 2>/dev/null)
  BIN="$CRATE_DIR/target/release/bm_set_ip"
fi
[[ -x "$BIN" ]] || { echo "[FATAL] binary not found: $BIN"; exit 2; }

PASS=0; FAIL=0
# 每条用例:name|args|期望行(可多行,空行分隔)
run_case() {
  local name="$1"; shift
  local args_str="$1"; shift
  local out
  # 用 eval 让 args_str 中的 '' 占位符经引号去除变成空参数
  out=$(eval "$BIN --dry-run $args_str" 2>&1 || true)
  local expected
  for expected in "$@"; do
    if grep -Fxq "$expected" <<<"$out"; then
      PASS=$((PASS+1))
    else
      FAIL=$((FAIL+1))
      echo "  [FAIL] $name :: expected '$expected'"
      echo "         args: $args_str"
      grep -E '^(net_device|v4\.|v6\.|routes\.|policy\.|family1)' <<<"$out" | sed 's/^/         > /'
    fi
  done
}

echo "===== bm_set_ip parser dry-run tests ====="

# M1 仅 IPv4
run_case "M1 v4 only" "eth1 192.168.140.10 24 192.168.140.1 8.8.8.8" \
  "family1_is_v6=false" "v4.present=true" "v4.addr=192.168.140.10" \
  "v4.netmask=24" "v4.gateway=192.168.140.1" "v4.dns=8.8.8.8" "v4.is_dhcp=false" \
  "v6.present=false" "routes.to="

# M2 仅 IPv6(新增)
run_case "M2 v6 only" "eth1 2001:db8:1::10 64 fe80::1 2001:4860:4860::8888" \
  "family1_is_v6=true" "v4.present=false" "v6.present=true" \
  "v6.addr=2001:db8:1::10" "v6.prefix=64" "v6.gateway=fe80::1" \
  "v6.dns=2001:4860:4860::8888" "v6.is_dhcp=false"

# M3 v4+v6
run_case "M3 v4+v6" "eth1 192.168.140.10 24 192.168.140.1 8.8.8.8 2001:db8:1::10 64 fe80::1" \
  "family1_is_v6=false" "v4.present=true" "v4.addr=192.168.140.10" \
  "v6.present=true" "v6.addr=2001:db8:1::10" "v6.prefix=64" "v6.gateway=fe80::1" \
  "v4.dns=8.8.8.8" "v6.dns="

# M4 v4+v6+路由+策略(v6 在策略之后)
run_case "M4 v4+v6+routes+policy" \
  "eth1 192.168.140.10 24 '' '' 192.168.150.0 24 192.168.140.1 100 192.168.141.0 24 192.168.150.0 24 2001:db8:1::10 64" \
  "v4.addr=192.168.140.10" "v4.gateway=" "v6.present=true" "v6.addr=2001:db8:1::10" \
  "routes.to=192.168.150.0" "routes.to_prefix=24" "routes.via=192.168.140.1" "routes.table=100" \
  "policy.rule_from=192.168.141.0" "policy.rule_from_prefix=24" \
  "policy.rule_to=192.168.150.0" "policy.rule_to_prefix=24"

# M5 v4+路由(gw/dns 用 '' 跳过)
run_case "M5 v4+routes" "eth1 192.168.140.10 24 '' '' 192.168.150.0 24 192.168.140.1 100" \
  "v4.present=true" "v4.gateway=" "v4.dns=" "v6.present=false" \
  "routes.to=192.168.150.0" "routes.to_prefix=24" "routes.via=192.168.140.1" "routes.table=100" \
  "policy.rule_from="

# M6 单 dhcp → v4 dhcp
run_case "M6 v4 dhcp" "eth1 dhcp ''" \
  "family1_is_v6=false" "v4.present=true" "v4.addr=dhcp" "v4.is_dhcp=true" \
  "v4.netmask=" "v6.present=false"

# M7 双 dhcp → v4+v6 dhcp
run_case "M7 dual dhcp" "eth1 dhcp '' '' '' dhcp" \
  "v4.is_dhcp=true" "v6.present=true" "v6.addr=dhcp" "v6.is_dhcp=true"

# 边缘:点分掩码 → routes.to_prefix 转换为前缀
run_case "Edge dotted mask" \
  "eth1 192.168.140.10 255.255.255.0 192.168.140.1 8.8.8.8 192.168.150.0 255.255.255.0 192.168.140.1 100" \
  "v4.netmask=255.255.255.0" "routes.to_prefix=24" "routes.table=100"

# 边缘:v4+gw+dns,无路由,family2 缺省
run_case "Edge v4 gw dns no routes" "eth1 192.168.140.10 24 192.168.140.1 8.8.8.8" \
  "v4.gateway=192.168.140.1" "v4.dns=8.8.8.8" "routes.to=" "v6.present=false"

# 边缘:v6 only + IPv4 路由(family1=v6 后接 IPv4 to)
run_case "Edge v6 + v4 routes" "eth1 2001:db8:1::10 64 fe80::1 '' 192.168.150.0 24 192.168.140.1 100" \
  "family1_is_v6=true" "v6.addr=2001:db8:1::10" "routes.to=192.168.150.0" "routes.table=100"

# 边缘:只给路由表(无 to)→ table 解析但 to 为空
run_case "Edge table only" "eth1 192.168.140.10 24 '' '' '' '' '' 100" \
  "routes.table=100" "routes.to=" "policy.rule_from="

echo "-----"
echo "result: PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]] && echo "ALL PASS" || { echo "SOME FAILED"; exit 1; }
