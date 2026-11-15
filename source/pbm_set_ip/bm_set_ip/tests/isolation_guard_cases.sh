#!/bin/bash
# 隔离前置条件的负向测试（验收意见 1 要求的三类用例）。
#
# 目的：证明 backend_contract.sh 在「无法建立隔离」时 fail-closed —— 立即非零退出，
#       且**不执行任何绝对路径的 mkdir/rm/write**。
#
# 关键手法：把潜在的危险命令（mkdir/rm/touch/tee/write 重定向）替换成“记录器”，
# 记录所有对 /etc 等绝对路径的写操作，然后断言记录为空。全程不碰宿主真实 /etc。
#
# 用法：bash tests/isolation_guard_cases.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/backend_contract.sh"
[ -f "$TARGET" ] || { echo "ERROR: 缺少 $TARGET" >&2; exit 2; }

# 被测二进制：显式 BIN 优先，否则用 cargo 默认路径
BIN="${BIN:-$SCRIPT_DIR/../target/debug/bm_set_ip}"
BIN="$(readlink -f "$BIN" 2>/dev/null || echo "$BIN")"
[ -x "$BIN" ] || { echo "ERROR: 未找到可执行文件 $BIN，请设置 BIN=" >&2; exit 2; }

PASS=0
FAIL=0
FAILED=()

# 一个必然失败的 unshare 包装：模拟“无命名空间权限”
mk_failing_unshare() {
  local f="$1"
  cat > "$f" <<'EOF'
#!/bin/bash
echo "unshare: unshare failed: Operation not permitted" >&2
exit 1
EOF
  chmod +x "$f"
}

# 一个“unshare 成功但 mount 失败”的包装：mount 被替换为必然失败
mk_failing_mount() {
  local f="$1"
  cat > "$f" <<'EOF'
#!/bin/bash
echo "mount: /etc: permission denied." >&2
exit 32
EOF
  chmod +x "$f"
}

# 危险写操作记录器：替换 root 下的假想写操作，仅记录不执行
mk_danger_recorder() {
  local dir="$1"
  mkdir -p "$dir"
  for c in mkdir rm rmdir touch tee chmod chown install; do
    cat > "$dir/$c" <<EOF
#!/bin/bash
printf '%s %s\n' "$c" "\$*" >> "\$DANGER_LOG"
exit 0
EOF
    chmod +x "$dir/$c"
  done
}

reset_danger_log() { : > "$DANGER_LOG"; }

# 断言：给定条件下目标脚本非零退出、输出含期望关键词、且危险记录器零调用
expect_fail_closed() {
  local desc="$1"; shift
  local expect_msg="$1"; shift
  local -a envs=("$@")

  reset_danger_log
  local out rc
  out="$(env "${envs[@]}" BIN="$BIN" DANGER_LOG="$DANGER_LOG" PATH="$DANGER_BIN:/usr/bin:/bin" \
        bash "$TARGET" 2>&1)"
  rc=$?

  local ok=1 why=""
  [ "$rc" -ne 0 ] || { ok=0; why="退出码为 0（应 fail-closed）"; }
  grep -qF "$expect_msg" <<<"$out" || { ok=0; why="输出缺少 '${expect_msg}'"; }
  # 真正要证明的是「没有动系统配置路径」。脚本自己的 mktemp 暂存目录（$TMPDIR，
  # 位于 /tmp 下）是隔离所需的临时区，且显式排除在外；系统路径一律零调用。
  local sys_ops
  sys_ops="$(grep -E ' /(etc|usr|lib|lib64|boot|bin|sbin|opt|srv|root|var)(/|$)' "$DANGER_LOG" 2>/dev/null || true)"
  if [ -n "$sys_ops" ]; then
    ok=0; why="仍对系统路径执行了写操作: $(tr '\n' ';' <<<"$sys_ops")"
  fi
  # 额外硬保证：绝不能有任何 /etc 写操作
  if grep -qE ' /etc(/|$)' "$DANGER_LOG" 2>/dev/null; then
    ok=0; why="仍对 /etc 执行了写操作: $(grep -E ' /etc(/|$)' "$DANGER_LOG" | tr '\n' ';')"
  fi

  if [ "$ok" = "1" ]; then
    PASS=$((PASS+1))
    echo "PASS: $desc (rc=$rc)"
  else
    FAIL=$((FAIL+1)); FAILED+=("$desc")
    echo "FAIL: $desc — $why"
    echo "  --- 脚本输出 ---"; sed 's/^/  /' <<<"$out" | head -15
    echo "  --- 危险调用 ---"; sed 's/^/  /' "$DANGER_LOG" | head -10
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DANGER_BIN="$TMP/danger"
DANGER_LOG="$TMP/danger.log"
mk_danger_recorder "$DANGER_BIN"
mk_failing_unshare "$TMP/unshare_fail"
mk_failing_mount "$TMP/mount_fail"
: > "$DANGER_LOG"

echo "==> 隔离守卫负向测试"

# 用例 1：unshare 完全不可用（模拟无 CAP_SYS_ADMIN / 禁用 user namespace）
expect_fail_closed \
  "unshare 失败必须立即非零退出且零副作用" \
  "无可用命名空间权限" \
  "BM_SET_IP_UNSHARE_BIN=$TMP/unshare_fail"

# 用例 2：unshare 成功但 tmpfs 挂载 /etc 失败
expect_fail_closed \
  "mount tmpfs /etc 失败必须立即非零退出且零副作用" \
  "mount tmpfs /etc 失败" \
  "BM_SET_IP_MOUNT_BIN=$TMP/mount_fail"

# 用例 3：伪造 BM_SET_IP_ISOLATED=1 直接进入内层（无命名空间、无 tmpfs）
#         必须被 namespace / tmpfs 证据拦下，而不是被环境变量放行。
# 注意：本用例在内层判定，unshare 根本不会被调用。
expect_fail_closed \
  "伪造 BM_SET_IP_ISOLATED=1 必须被隔离证据拦下" \
  "隔离前置条件不满足" \
  "BM_SET_IP_ISOLATED=1"

# 用例 4：伪造 ISOLATED + 伪造一个看似正常的挂载（无 tmpfs）仍必须被拦。
#         用一个“只打印成功、不真的 mount”的包装，验证 mount 后校验（fstype/设备号）生效。
cat > "$TMP/mount_noop" <<'EOF'
#!/bin/bash
exit 0
EOF
chmod +x "$TMP/mount_noop"
expect_fail_closed \
  "mount 假成功（未真正挂载）必须被 fstype/设备号校验拦下" \
  "隔离前置条件不满足" \
  "BM_SET_IP_MOUNT_BIN=$TMP/mount_noop"

echo
echo "==============================================="
echo "通过: $PASS  失败: $FAIL"
if [ "$FAIL" -ne 0 ]; then
  for n in "${FAILED[@]}"; do echo "  - $n"; done
fi
echo "==============================================="
[ "$FAIL" -eq 0 ]
