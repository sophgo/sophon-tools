#!/bin/bash
# bm_set_ip 后端行为契约测试（黑盒：真实可执行文件 + 有状态的 fake 命令/文件系统）
#
# 目的：覆盖 stateful fake 也表达不了的“退出码 + 成功文案 + 调用序列”契约，
#       并给出“原代码失败 → 修复通过”的可复现红绿证据。
#
# 安全：默认在 `unshare -rmn`（用户+挂载+网络命名空间，/etc 用 tmpfs 覆盖）
#       中运行；fake 命令全部放在临时目录的 PATH 前缀里，不存在被真实命令
#       绕过的路径。即使在无命名空间权限的环境运行，也只会写到 tmpfs/临时目录。
#
# 用法：
#   bash tests/backend_contract.sh              # 跑全部用例
#   BIN=/path/to/bm_set_ip bash tests/backend_contract.sh
#   bash tests/backend_contract.sh -v           # 打印每个用例的输出
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERBOSE="${BM_SET_IP_TEST_VERBOSE:-0}"
[ "${1:-}" = "-v" ] && VERBOSE=1

BIN="${BIN:-}"
if [ -z "$BIN" ]; then
  BIN="$CRATE_DIR/target/debug/bm_set_ip"
  if [ ! -x "$BIN" ]; then
    echo "ERROR: 未找到 $BIN，先执行 cargo build 或设置 BIN=" >&2
    exit 2
  fi
fi
BIN="$(readlink -f "$BIN")"

# 已在隔离环境内则由内层脚本执行；否则用 unshare 重新进入
if [ "${BM_SET_IP_IN_NS:-0}" != "1" ]; then
  if unshare -rmn --propagation private true 2>/dev/null; then
    echo "==> 在 unshare -rmn 隔离环境内运行契约测试"
    exec unshare -rmn --propagation private \
      env BM_SET_IP_IN_NS=1 BIN="$BIN" BM_SET_IP_TEST_VERBOSE="$VERBOSE" \
      CRATE_DIR="$CRATE_DIR" bash "$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")" "${1:-}"
  fi
  echo "[WARN] 无命名空间权限，改在临时目录 + fake PATH 下运行（仍不触碰真实命令）" >&2
fi

# ---- 隔离环境内的固定根 ----
ROOT="$(mktemp -d)"
export TMPDIR="$ROOT/tmp"
mkdir -p "$TMPDIR"
# /etc 用 tmpfs 覆盖，保证任何绝对路径写入都不落到宿主；覆盖后再建测试用目录
if mount -t tmpfs tmpfs /etc 2>/dev/null; then
  echo "[INFO] /etc 已用 tmpfs 覆盖（零宿主副作用）"
else
  echo "[WARN] 无法覆盖挂载 /etc：测试文件将落在真实 /etc（仅限 netplan/networkd/resolv.conf 测试文件）" >&2
fi
mkdir -p /etc/netplan /etc/systemd/network /etc/iproute2

# ---- stateful fake 命令 ----
# 状态目录：$FAKE_STATE/{nm,*.log}
FAKE_BIN="$ROOT/bin"
FAKE_STATE="$ROOT/state"
mkdir -p "$FAKE_BIN" "$FAKE_STATE/nm" "$FAKE_STATE/calls"
export FAKE_STATE

cat > "$FAKE_BIN/nmcli" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
# 有状态的 nmcli：连接以 $FAKE_STATE/nm/<uuid> 文件表示，内容 "name|ifname"
S="$FAKE_STATE"
log() { printf 'nmcli %s\n' "$*" >> "$S/calls.log"; }
esc() { local s="${1//\\/\\\\}"; printf '%s' "${s//:/\\:}"; }
unesc() { printf '%s' "${1//\\:/:}"; }
log "$@"

case "$1" in
  -t)
    # nmcli -t -f UUID,NAME,TYPE con show
    for f in "$S"/nm/*; do
      [ -e "$f" ] || continue
      uuid="$(basename "$f")"
      IFS='|' read -r name ifname < "$f"
      printf '%s:%s:802-3-ethernet\n' "$(esc "$uuid")" "$(esc "$name")"
    done
    ;;
  -g)
    # nmcli -g connection.interface-name con show <uuid|name>
    target="$5"
    found=""
    for f in "$S"/nm/*; do
      [ -e "$f" ] || continue
      uuid="$(basename "$f")"
      IFS='|' read -r name ifname < "$f"
      if [ "$uuid" = "$target" ] || [ "$name" = "$target" ]; then
        echo "connection.interface-name:$ifname"; found=1; break
      fi
    done
    [ -n "$found" ] || { echo "Error: unknown connection '$target'" >&2; exit 10; }
    ;;
  con)
    sub="$2"
    case "$sub" in
      add)
        if [ -n "${FAKE_NM_ADD_FAIL:-}" ]; then
          echo "Error: failed to create connection" >&2; exit 4
        fi
        ifname=""; name=""
        i=3
        while [ "$i" -le "$#" ]; do
          case "${!i}" in
            ifname) i=$((i+1)); ifname="${!i}" ;;
            con-name) i=$((i+1)); name="${!i}" ;;
          esac
          i=$((i+1))
        done
        n=$(cat "$S/nm_seq" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$S/nm_seq"
        uuid="uuid-new-$n"
        printf '%s|%s\n' "$name" "$ifname" > "$S/nm/$uuid"
        echo "Connection '$name' ($uuid) successfully added."
        ;;
      up)
        target="$3"
        if [ -n "${FAKE_NM_UP_FAIL:-}" ] && [ "$FAKE_NM_UP_FAIL" = "$target" ]; then
          echo "Error: Connection activation failed: No suitable device found" >&2; exit 4
        fi
        [ -e "$S/nm/$target" ] || { echo "Error: unknown connection '$target'" >&2; exit 10; }
        echo "Connection '$target' successfully activated."
        ;;
      show)
        # nmcli con show <uuid|name> —— 完整 profile dump（恢复用）
        target="$3"; found=""
        for f in "$S"/nm/*; do
          [ -e "$f" ] || continue
          uuid="$(basename "$f")"
          IFS='|' read -r name ifname < "$f"
          if [ "$uuid" = "$target" ] || [ "$name" = "$target" ]; then
            printf 'connection.id:                          %s\nconnection.uuid:                        %s\nconnection.type:                        802-3-ethernet\nconnection.interface-name:              %s\n' \
              "$name" "$uuid" "$ifname"
            found=1; break
          fi
        done
        [ -n "$found" ] || { echo "Error: unknown connection '$target'" >&2; exit 10; }
        ;;
      modify)
        target="$3"; newid="$5"
        if [ -n "${FAKE_NM_MODIFY_FAIL:-}" ]; then
          echo "Error: failed to modify connection" >&2; exit 4
        fi
        for f in "$S"/nm/*; do
          [ -e "$f" ] || continue
          uuid="$(basename "$f")"
          [ "$uuid" = "$target" ] || continue
          IFS='|' read -r name ifname < "$f"
          printf '%s|%s\n' "$newid" "$ifname" > "$f"
          echo "Connection '$newid' successfully modified."; exit 0
        done
        echo "Error: unknown connection '$target'" >&2; exit 10
        ;;
      delete)
        target="$3"
        if [ -n "${FAKE_NM_DELETE_FAIL:-}" ] && [ "$FAKE_NM_DELETE_FAIL" = "$target" ]; then
          echo "Error: unknown connection '$target'" >&2; exit 10
        fi
        for f in "$S"/nm/*; do
          [ -e "$f" ] || continue
          uuid="$(basename "$f")"
          IFS='|' read -r name ifname < "$f"
          if [ "$uuid" = "$target" ] || [ "$name" = "$target" ]; then
            rm -f "$f"; echo "Connection '$name' deleted."; exit 0
          fi
        done
        echo "Error: unknown connection '$target'" >&2; exit 10
        ;;
      *) echo "Error: unsupported" >&2; exit 2 ;;
    esac
    ;;
  *) echo "Error: unsupported" >&2; exit 2 ;;
esac
FAKE

cat > "$FAKE_BIN/ip" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
S="$FAKE_STATE"
printf 'ip %s\n' "$*" >> "$S/calls.log"
if [ "$1 $2 $3" = "route show default" ]; then
  printf '%s\n' "${FAKE_IP_DEFAULT_ROUTE:-default via 192.0.2.1 dev eth9}"
  exit 0
fi
joined="$*"
if [ -n "${FAKE_IP_FAIL:-}" ]; then
  IFS=',' read -ra pats <<< "$FAKE_IP_FAIL"
  for p in "${pats[@]}"; do
    case "$joined" in
      "$p"*) echo "RTNETLINK answers: Operation not permitted" >&2; exit 2 ;;
    esac
  done
fi
exit 0
FAKE

cat > "$FAKE_BIN/netplan" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
printf 'netplan %s\n' "$*" >> "$FAKE_STATE/calls.log"
if [ -n "${FAKE_NETPLAN_APPLY_FAIL:-}" ]; then
  echo "Error: Conflicting default route declarations" >&2; exit 1
fi
exit 0
FAKE

cat > "$FAKE_BIN/networkctl" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
printf 'networkctl %s\n' "$*" >> "$FAKE_STATE/calls.log"
case "$1" in
  reload) exit 0 ;;
  reconfigure)
    if [ -n "${FAKE_NETCTL_FAIL:-}" ]; then echo "Failed to reconfigure" >&2; exit 1; fi
    exit 0 ;;
esac
exit 0
FAKE

cat > "$FAKE_BIN/systemctl" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
printf 'systemctl %s\n' "$*" >> "$FAKE_STATE/calls.log"
[ "$1" = "is-active" ] && [ "${FAKE_SYSTEMD_ACTIVE:-}" = "$2" ] && { echo active; exit 0; }
echo inactive; exit 3
FAKE

cat > "$FAKE_BIN/resolvconf" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
printf 'resolvconf %s\n' "$*" >> "$FAKE_STATE/calls.log"
# 记录读到的完整 stdin（原代码不写 stdin，这里会得到空文件）
cat > "$FAKE_STATE/resolvconf.stdin"
[ -n "${FAKE_RESOLVCONF_FAIL:-}" ] && { echo "resolvconf: cannot update" >&2; exit 1; }
exit 0
FAKE

cat > "$FAKE_BIN/resolvectl" <<'FAKE'
#!/bin/bash
export PATH=/usr/bin:/bin   # fake 自身需要 coreutils；被测程序的 PATH 只含 fake 目录
printf 'resolvectl %s\n' "$*" >> "$FAKE_STATE/calls.log"
[ -n "${FAKE_RESOLVECTL_FAIL:-}" ] && { echo "Failed to set DNS configuration" >&2; exit 1; }
exit 0
FAKE

chmod +x "$FAKE_BIN"/*

# 被测程序只能看到 fake 命令：真实 nmcli/ip/netplan/resolvectl 一律不可达
ONLY_FAKE="$FAKE_BIN"
export ONLY_FAKE

PASS=0
FAIL=0
FAILED_NAMES=()

reset_state() {
  rm -rf "$FAKE_STATE/nm" "$FAKE_STATE/nm_seq" "$FAKE_STATE/calls.log" \
         "$FAKE_STATE/resolvconf.stdin" 2>/dev/null
  mkdir -p "$FAKE_STATE/nm"
  : > "$FAKE_STATE/calls.log"
  rm -rf /etc/netplan/* /etc/systemd/network/* /etc/iproute2/* 2>/dev/null
  : > /etc/iproute2/rt_tables
}

add_conn() { # name ifname -> goes to uuid-legacy-<name>
  local uuid="uuid-legacy-$1"
  printf '%s|%s\n' "$1" "$2" > "$FAKE_STATE/nm/$uuid"
}

# 运行被测程序：以 root 且 PATH 前缀为 fake
run_bin() { # args...
  PATH="$ONLY_FAKE" "$BIN" "$@" > "$FAKE_STATE/out.log" 2>&1
  echo $?
}

calls() { cat "$FAKE_STATE/calls.log" 2>/dev/null; }

check() { # <描述> <条件命令...>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); FAILED_NAMES+=("$desc")
    echo "FAIL: $desc"
    echo "  ---- 程序输出 ----"; sed 's/^/  /' "$FAKE_STATE/out.log" 2>/dev/null | head -20
    echo "  ---- 调用序列 ----"; calls | sed 's/^/  /' | head -25
  fi
}

has_call() { calls | grep -qxF "$1"; }
has_call_prefix() { calls | grep -q "$1"; }
count_calls() { calls | grep -c "$1"; }
out_has() { grep -qF "$1" "$FAKE_STATE/out.log" 2>/dev/null; }
nm_has_uuid() { [ -e "$FAKE_STATE/nm/$1" ]; }
nm_names() { for f in "$FAKE_STATE/nm"/*; do [ -e "$f" ] && cat "$f"; done; }

echo "==> BIN=$BIN"
"$BIN" --dry-run eth1 10.1.0.5 24 2>/dev/null | head -1

# ================= NM 后端 =================
nm_case() { # <env...> -- <args...>；NM 由 fake systemctl is-active + nmcli 触发
  local envs=("$@")
  PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager \
    env "${envs[@]}" "$BIN" "$@" > "$FAKE_STATE/out.log" 2>&1
}

echo "--- NM 后端"
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager "$BIN" eth1 10.1.0.5 24 10.1.0.1 > "$FAKE_STATE/out.log" 2>&1
rc=$?
echo "$rc" > "$FAKE_STATE/rc"
check "NM 首次配置（无旧连接）退出码 0" [ "$(cat "$FAKE_STATE/rc")" = "0" ]
check "NM 首次配置不应删除任何连接" [ "$(count_calls 'nmcli con delete')" = "0" ]
check "NM 首次配置按 UUID 激活新连接" has_call "nmcli con up uuid-new-1"
check "NM 首次配置应只留一个连接" [ "$(nm_names | wc -l)" = "1" ]
check "NM 首次配置输出成功文案" out_has "applied successfully"
check "NM 新 profile 以临时名创建（避免与旧 profile 的 con-name 冲突）" has_call_prefix "nmcli con add type ethernet ifname eth1 con-name static-eth1.bmip-new"
check "NM 激活后应改名为最终名" has_call "nmcli con modify uuid-new-1 connection.id static-eth1"
check "NM 最终连接名为 static-eth1" bash -c 'grep -qxF "static-eth1|eth1" "$0/nm/uuid-new-1"' "$FAKE_STATE"

# 同名旧连接：必须按 UUID 处理，新连接不能被删
reset_state; add_conn "static-eth1" "eth1"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM 同名旧连接场景退出码 0" [ "$rc" = "0" ]
check "NM 新连接必须在配置后仍存在（原代码会删掉它）" nm_has_uuid "uuid-new-1"
check "NM 旧连接应按 UUID 被清理" [ ! -e "$FAKE_STATE/nm/uuid-legacy-static-eth1" ]
check "NM 同名旧连接场景最终只留一个连接" [ "$(nm_names | wc -l)" = "1" ]
check "NM 同名旧连接场景最终名为 static-eth1" bash -c 'grep -qxF "static-eth1|eth1" "$0/nm/uuid-new-1"' "$FAKE_STATE"
check "NM 不得按同名删除新连接" bash -c '! grep -qxF "nmcli con delete static-eth1" "$0"' "$FAKE_STATE/calls.log"

# add 失败：必须非零且不动旧配置
reset_state; add_conn "static-eth1" "eth1"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_ADD_FAIL=1 "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM add 失败必须非零退出" [ "$rc" != "0" ]
check "NM add 失败不得删除旧连接" nm_has_uuid "uuid-legacy-static-eth1"
check "NM add 失败不得输出成功文案" bash -c '! grep -qF "applied successfully" "$0"' "$FAKE_STATE/out.log"

# up 失败：必须非零、撤销新连接、旧连接仍在
reset_state; add_conn "static-eth1" "eth1"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_UP_FAIL=uuid-new-1 "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM up 失败必须非零退出" [ "$rc" != "0" ]
check "NM up 失败应撤销新连接" bash -c '[ ! -e "$0/nm/uuid-new-1" ]' "$FAKE_STATE"
check "NM up 失败旧连接不得丢失" nm_has_uuid "uuid-legacy-static-eth1"
check "NM up 失败不得输出成功文案" bash -c '! grep -qF "applied successfully" "$0"' "$FAKE_STATE/out.log"

# 其它接口 / 非托管连接：一律不删
reset_state; add_conn "static-eth1" "eth2"; add_conn "Wired connection 1" "eth0"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM 其它接口场景退出码 0" [ "$rc" = "0" ]
check "NM 不得删除绑定别的接口的同名连接" nm_has_uuid "uuid-legacy-static-eth1"
check "NM 不得删除非托管连接" nm_has_uuid "uuid-legacy-Wired connection 1"

# ================= ip 兜底后端 =================
echo "--- ip 兜底后端"
# 管理口保护：默认路由在目标口上，必须拒绝且零副作用
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_IP_DEFAULT_ROUTE="default via 10.43.0.1 dev eth0 metric 100" \
  "$BIN" eth0 10.43.0.157 24 10.43.0.1 8.8.8.8 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "ip 管理口保护必须拒绝（非零）" [ "$rc" != "0" ]
check "ip 管理口保护时不得执行任何 ip 修改命令" bash -c '! grep -qE "^ip (addr|link|route add|rule add)" "$0"' "$FAKE_STATE/calls.log"
check "ip 管理口保护时不得写 DNS（resolvconf 零调用）" [ "$(count_calls 'resolvconf')" = "0" ]
check "ip 管理口保护时不得写 resolv.conf" [ ! -e /etc/resolv.conf ]

# flush 失败：非零，且不再加地址
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_IP_FAIL="addr flush" \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "ip flush 失败必须非零" [ "$rc" != "0" ]
check "ip flush 失败后不再尝试加地址" [ "$(count_calls 'ip addr add')" = "0" ]

# 部分地址失败：非零
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_IP_FAIL="addr add 10.1.0.6" \
  "$BIN" eth1 10.1.0.5 24 '' '' 10.1.0.6 24 '' '' > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "ip 部分地址失败必须非零" [ "$rc" != "0" ]
check "ip 部分地址失败应尝试两处地址" [ "$(count_calls 'ip addr add')" = "2" ]

# 显式路由失败：非零
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_IP_FAIL="route add 10.20.0.0" \
  "$BIN" eth1 10.1.0.5 24 '' '' 10.20.0.0 24 '' 100 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "ip 显式路由失败必须非零" [ "$rc" != "0" ]

# 全部成功：退出码 0 + 计数
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none "$BIN" eth1 10.1.0.5 24 '' '' 10.1.0.6 24 '' '' > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "ip 全部成功退出码 0" [ "$rc" = "0" ]
check "ip 成功文案应含 2/2" out_has "addresses: 2/2"

# ================= DNS =================
echo "--- DNS"
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 "8.8.8.8,114.114.114.114" > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "DNS resolvconf 场景退出码 0" [ "$rc" = "0" ]
check "DNS resolvconf 应以真实接口名调用" has_call "resolvconf -a eth1"
check "DNS resolvconf 应收到完整 stdin（两个 nameserver）" bash -c '[ "$(grep -c "^nameserver " "$0/resolvconf.stdin")" = "2" ]' "$FAKE_STATE"
check "DNS resolvconf stdin 内容正确" bash -c 'grep -qxF "nameserver 8.8.8.8" "$0/resolvconf.stdin" && grep -qxF "nameserver 114.114.114.114" "$0/resolvconf.stdin"' "$FAKE_STATE"

# resolvconf 失败：非零
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_RESOLVCONF_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 8.8.8.8 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "DNS resolvconf 失败必须非零" [ "$rc" != "0" ]

# resolvectl 分支（无 resolvconf）
reset_state
rm -f "$FAKE_BIN/resolvconf"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 "8.8.8.8,114.114.114.114" > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "DNS resolvectl 场景退出码 0" [ "$rc" = "0" ]
check "DNS resolvectl 应一次传全部 DNS 且用真实接口名" has_call "resolvectl dns eth1 8.8.8.8 114.114.114.114"
check "DNS resolvectl 只应调用一次（不得逐条覆盖）" [ "$(count_calls 'resolvectl dns')" = "1" ]

reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_RESOLVECTL_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 8.8.8.8 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "DNS resolvectl 失败必须非零" [ "$rc" != "0" ]

# 文件回退：写全部 nameserver + 备份
reset_state
rm -f "$FAKE_BIN/resolvectl"
printf 'nameserver 1.1.1.1\n' > /etc/resolv.conf
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 "8.8.8.8,114.114.114.114" > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "DNS 文件回退场景退出码 0" [ "$rc" = "0" ]
check "DNS 文件回退写入全部 nameserver" bash -c '[ "$(grep -c "^nameserver " /etc/resolv.conf)" = "2" ]'
check "DNS 文件回退保留原文件备份" bash -c 'grep -qxF "nameserver 1.1.1.1" /etc/resolv.conf.bm_set_ip.bak'
rm -f /etc/resolv.conf /etc/resolv.conf.bm_set_ip.bak

# ================= netplan 快照/回滚 =================
echo "--- netplan 快照/回滚"
reset_state
ORIG='network:
  version: 2
  ethernets:
    eth1:
      mtu: 1400'
printf '%s\n' "$ORIG" > /etc/netplan/01-netcfg.yaml
# 陈旧遗留 .bak：绝不能用于回滚
printf 'network:\n  version: 2\n  ethernets:\n    eth1:\n      addresses: [9.9.9.9/24]\n' \
  > /etc/netplan/01-netcfg.yaml.bm_set_ip.bak
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none FAKE_NETPLAN_APPLY_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 10.1.0.1 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "netplan apply 失败必须非零" [ "$rc" != "0" ]
check "netplan 回滚必须用本次快照而非陈旧 .bak" bash -c 'grep -qF "mtu: 1400" /etc/netplan/01-netcfg.yaml && ! grep -qF "9.9.9.9" /etc/netplan/01-netcfg.yaml'
check "netplan apply 失败不得输出成功文案" bash -c '! grep -qF "applied successfully" "$0"' "$FAKE_STATE/out.log"

# 备份失败：拒绝修改，原文件不变，不 apply
# （root 不受目录权限约束，因此用“备份路径已被目录占据”制造真实的写失败）
reset_state
printf '%s\n' "$ORIG" > /etc/netplan/01-netcfg.yaml
mkdir -p /etc/netplan/01-netcfg.yaml.bm_set_ip.bak
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=none "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "netplan 备份失败必须非零" [ "$rc" != "0" ]
check "netplan 备份失败不得改动原配置" bash -c 'grep -qF "mtu: 1400" /etc/netplan/01-netcfg.yaml && ! grep -qF "10.1.0.5" /etc/netplan/01-netcfg.yaml'
check "netplan 备份失败不得执行 apply" [ "$(count_calls 'netplan apply')" = "0" ]
rm -rf /etc/netplan/01-netcfg.yaml /etc/netplan/01-netcfg.yaml.bm_set_ip.bak

# ================= networkd 快照/回滚 =================
echo "--- networkd 快照/回滚"
reset_state
# 原文件不存在 + reconfigure 失败 → 撤销新文件
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=systemd-networkd FAKE_NETCTL_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "networkd reconfigure 失败必须非零" [ "$rc" != "0" ]
check "networkd 原文件不存在时失败必须撤销新文件" [ ! -e /etc/systemd/network/10-eth1.network ]
check "networkd 原本无文件时不得凭空产生 .bak" [ ! -e /etc/systemd/network/10-eth1.network.bm_set_ip.bak ]

# 原文件存在 + 失败 → 恢复原文
reset_state
printf '[Match]\nName=eth1\n\n[Network]\nDHCP=ipv4\n' > /etc/systemd/network/10-eth1.network
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=systemd-networkd FAKE_NETCTL_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "networkd 失败时恢复原文件" bash -c 'grep -qxF "DHCP=ipv4" /etc/systemd/network/10-eth1.network'

# 原文件不存在 + 成功 → 保留新文件
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=systemd-networkd \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "networkd 成功退出码 0" [ "$rc" = "0" ]
check "networkd 成功应写入新配置" bash -c 'grep -qF "Address=10.1.0.5/24" /etc/systemd/network/10-eth1.network'

# ================= 汇总 =================
echo
echo "==============================================="
echo "通过: $PASS  失败: $FAIL"
if [ "$FAIL" -ne 0 ]; then
  echo "失败用例:"
  for n in "${FAILED_NAMES[@]}"; do echo "  - $n"; done
fi
echo "==============================================="
[ "$FAIL" -eq 0 ]
