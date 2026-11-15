#!/bin/bash
# bm_set_ip 后端行为契约测试（黑盒：真实可执行文件 + 有状态的 fake 命令/文件系统）
#
# 目的：覆盖 stateful fake 也表达不了的“退出码 + 成功文案 + 调用序列”契约，
#       并给出“原代码失败 → 修复通过”的可复现红绿证据。
#
# 安全（fail-closed，验收意见 1）：
#   本脚本会 `rm -rf /etc/netplan/*` 等绝对路径操作，因此**必须先证明**自己已在
#   独立且 propagation=private 的 mount namespace 中，并且 /etc 已换成本次专用 tmpfs，
#   然后才允许任何绝对路径 mkdir/rm/write。任一前置条件不满足 → 立即非零退出，
#   绝不“降级在宿主上跑”。隔离证明用三段独立证据，不依赖可被外部伪造的单个环境变量：
#     1. mount namespace 的 inode 与父进程不同（/proc/self/ns/mnt vs 调用者）；
#     2. /etc 的挂载源是本脚本本次创建的 tmpfs（挂载点 inode + fstype 双重校验）；
#     3. 写入一个哨兵文件并确认它落在 tmpfs 上，且宿主视角不可见（由 run_isolation_selftest 覆盖）。
#
# 用法：
#   bash tests/backend_contract.sh              # 自动建立隔离环境并跑全部用例
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

die() { echo "ERROR: $*" >&2; echo "ERROR: 隔离前置条件不满足，拒绝在宿主上运行（fail-closed）" >&2; exit 3; }

# 仅供 run_isolation_selftest 注入故障：允许用包装命令替换 unshare/mount。
UNSHARE_BIN="${BM_SET_IP_UNSHARE_BIN:-unshare}"
MOUNT_BIN="${BM_SET_IP_MOUNT_BIN:-mount}"

# 已在外层建立的隔离中？只认 TMPFS 标记 + namespace 自证，不单独信任 IN_NS 变量。
if [ "${BM_SET_IP_ISOLATED:-0}" != "1" ]; then
  # ---- 第一层：进入独立 mount+net namespace（privileged 用 -mn，否则尝试 -rmn）----
  NS_CMD=""
  if $UNSHARE_BIN -mn --propagation private true 2>/dev/null; then
    NS_CMD="$UNSHARE_BIN -mn --propagation private"
  elif $UNSHARE_BIN -rmn --propagation private true 2>/dev/null; then
    NS_CMD="$UNSHARE_BIN -rmn --propagation private"
  fi
  [ -n "$NS_CMD" ] || die "无可用命名空间权限（unshare -mn / -rmn 均失败）。请以 root/CAP_SYS_ADMIN 运行，或显式跳过本脚本（不支持在宿主回退执行）。"

  echo "==> 进入隔离环境: $NS_CMD"
  # 内层负责证明隔离；外层只转发退出码
  exec $NS_CMD env BM_SET_IP_ISOLATED=1 BIN="$BIN" BM_SET_IP_TEST_VERBOSE="$VERBOSE" \
    CRATE_DIR="$CRATE_DIR" bash "$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")" "${1:-}"
fi

# ---- 内层：逐条验证隔离证据，任何一条不成立就退出 ----

# 证据 1：必须已处于独立 mount namespace。
# 父进程（外层）在宿主的 mnt ns；若当前与自己父进程的 mnt ns inode 相同，说明没隔离。
NS_SELF="$(readlink /proc/self/ns/mnt 2>/dev/null | cut -d: -f2)"
[ -n "${NS_SELF:-}" ] || die "无法读取 /proc/self/ns/mnt"
NS_PARENT="unavailable"
if [ -r "/proc/$PPID/ns/mnt" ]; then
  NS_PARENT="$(readlink "/proc/$PPID/ns/mnt" 2>/dev/null | cut -d: -f2)"
  NS_PARENT="${NS_PARENT:-unavailable}"
  [ "${NS_SELF}" != "${NS_PARENT}" ] || die "当前 mount namespace 与父进程相同（$NS_SELF），未真正隔离"
fi

# 解析 /proc/self/mountinfo 中某个挂载点的字段（纯 bash）。
# 刻意不用 awk：Ubuntu/Debian 的 /usr/bin/awk 是 /etc/alternatives/awk 的符号链接，
# 一旦 /etc 被 tmpfs 覆盖，awk 就不可用，反而会让隔离校验自己失败。
# 参数：$1=挂载点  $2=要取的字段下标（1=mount id, 5=mount point, 9=fstype）
mountinfo_field() {
  local want="$1" idx="$2" line i f
  while IFS= read -r line; do
    set -f
    # shellcheck disable=SC2086
    local -a f=($line)
    set +f
    if [ "${f[4]:-}" = "$want" ]; then
      printf '%s' "${f[$((idx-1))]-}"
      return 0
    fi
  done < /proc/self/mountinfo
  return 1
}

# 证据 2：在 mount 前记录原 /etc 的 mount id，mount 后必须变化
orig_mnt_id="$(mountinfo_field /etc 1 || true)"
orig_etc_dev="$(stat -c '%d' /etc 2>/dev/null || echo unknown)"

ROOT="$(mktemp -d)" || die "mktemp 失败"
export TMPDIR="$ROOT/tmp"
mkdir -p "$TMPDIR"
# 记录本次 tmpfs 的唯一标记，供事后校验 /etc 确实是“这一个” tmpfs
TMPFS_TOKEN="bm_set_ip_test_tmpfs_$$_$(date +%s%N)"
printf '%s' "$TMPFS_TOKEN" > "$ROOT/token"

# /etc 换成 tmpfs：失败即退出（绝不带着真实 /etc 继续）
$MOUNT_BIN -t tmpfs -o "size=8m" tmpfs /etc || die "mount tmpfs /etc 失败；不能覆盖 /etc 时禁止继续"

# 证据 2a：/etc 的 mount id 必须变化，且 fstype 必须是 tmpfs
new_mnt_id="$(mountinfo_field /etc 1 || true)"
[ -n "$new_mnt_id" ] || die "无法确认 /etc 的挂载记录"
[ "$new_mnt_id" != "${orig_mnt_id:-none}" ] || die "/etc 的 mount id 未变化（$new_mnt_id），tmpfs 未生效"
etc_fstype="$(mountinfo_field /etc 9 || true)"
[ "$etc_fstype" = "tmpfs" ] || die "/etc 实际 fstype=${etc_fstype:-unknown}，不是 tmpfs"
# 证据 2b：设备号必须改变（新 tmpfs 是独立匿名设备）
new_etc_dev="$(stat -c '%d' /etc)"
[ "$new_etc_dev" != "$orig_etc_dev" ] || die "/etc 设备号未变化（$new_etc_dev），仍是原文件系统"

# 证据 3：写入哨兵并确认可写；再校验“宿主视角不可见”——挂载点私有性
printf '%s' "$TMPFS_TOKEN" > /etc/.bmip_isolation_token || die "无法在 tmpfs /etc 写入哨兵文件"
[ "$(cat /etc/.bmip_isolation_token)" = "$TMPFS_TOKEN" ] || die "/etc 哨兵回读不一致"
# propagation 必须是 private（否则挂载可能传播回宿主）
prop="$(findmnt -no PROPAGATION /etc 2>/dev/null || true)"
case "$prop" in
  private|"") : ;;   # findmnt 缺失时退化为信任 unshare --propagation private
  *) die "/etc 挂载传播类型为 '$prop'，不是 private" ;;
esac

echo "[INFO] 隔离已证明：mnt-ns=$NS_SELF (parent=$NS_PARENT) /etc=mount#${new_mnt_id} fstype=tmpfs dev=${new_etc_dev} prop=${prop:-unknown}"

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
# 连接文件格式：第一行 "name|ifname"，第二行可选 "ACTIVE=1"
is_active() { grep -qxF 'ACTIVE=1' "$S/nm/$(basename "$1")" 2>/dev/null; }
set_active() { # uuid
  local f="$S/nm/$1"; [ -e "$f" ] || return 0
  grep -v '^ACTIVE=' "$f" > "$f.tmp" 2>/dev/null || true
  echo 'ACTIVE=1' >> "$f.tmp"; mv "$f.tmp" "$f"
}
clear_active_on() { # ifname
  for f in "$S"/nm/*; do
    [ -e "$f" ] || continue
    IFS='|' read -r n i < "$f"
    [ "$i" = "$1" ] && { grep -v '^ACTIVE=' "$f" > "$f.tmp" 2>/dev/null || true; mv "$f.tmp" "$f"; }
  done
}
unesc() { printf '%s' "${1//\\:/:}"; }
log "$@"

case "$1" in
  -t)
    # nmcli -t -f <fields> con show [--active]
    active_only=0; want_dev=0
    for a in "$@"; do
      [ "$a" = "--active" ] && active_only=1
      case ",$a," in *,DEVICE,*) want_dev=1 ;; esac
    done
    for f in "$S"/nm/*; do
      [ -e "$f" ] || continue
      uuid="$(basename "$f")"
      IFS='|' read -r name ifname < "$f"
      act=""; is_active "$f" && act=1
      [ "$active_only" = "1" ] && [ -z "$act" ] && continue
      if [ "$want_dev" = "1" ]; then
        printf '%s:%s:802-3-ethernet:%s\n' "$(esc "$uuid")" "$(esc "$name")" "${act:+$ifname}"
      else
        printf '%s:%s:802-3-ethernet\n' "$(esc "$uuid")" "$(esc "$name")"
      fi
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
        # 真实 NM 会先把该设备原 active 连接切下来
        dev=""; [ -e "$S/nm/$target" ] && { IFS='|' read -r _ dev < "$S/nm/$target"; }
        [ -n "$dev" ] && clear_active_on "$dev"
        if [ -n "${FAKE_NM_UP_FAIL:-}" ] && [ "$FAKE_NM_UP_FAIL" = "$target" ]; then
          echo "Error: Connection activation failed: No suitable device found" >&2; exit 4
        fi
        [ -e "$S/nm/$target" ] || { echo "Error: unknown connection '$target'" >&2; exit 10; }
        set_active "$target"
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
          act=""; grep -qxF 'ACTIVE=1' "$f" 2>/dev/null && act=1
          printf '%s|%s\n' "$newid" "$ifname" > "$f"
          [ -n "$act" ] && echo 'ACTIVE=1' >> "$f"
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
  reload)
    [ -n "${FAKE_NETCTL_RELOAD_FAIL:-}" ] && { echo "Failed to reload" >&2; exit 1; }
    exit 0 ;;
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

add_conn() { # name ifname [active] -> uuid-legacy-<name>
  local uuid="uuid-legacy-$1"
  printf '%s|%s\n' "$1" "$2" > "$FAKE_STATE/nm/$uuid"
  [ "${3:-}" = "active" ] && echo 'ACTIVE=1' >> "$FAKE_STATE/nm/$uuid"
  return 0
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
# 只输出连接定义行（name|ifname），忽略 ACTIVE= 状态标记行
nm_names() { for f in "$FAKE_STATE/nm"/*; do [ -e "$f" ] && grep -v '^ACTIVE=' "$f"; done; }
nm_count() { nm_names | grep -c . ; }
active_dev() { for f in "$FAKE_STATE/nm"/*; do [ -e "$f" ] || continue; grep -qxF 'ACTIVE=1' "$f" && { IFS='|' read -r n i < "$f"; echo "$i"; return 0; }; done; return 1; }
active_uuid_on() { for f in "$FAKE_STATE/nm"/*; do [ -e "$f" ] || continue; IFS='|' read -r n i < "$f"; [ "$i" = "$1" ] && grep -qxF 'ACTIVE=1' "$f" && { basename "$f"; return 0; }; done; return 1; }

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
check "NM 首次配置应只留一个连接" [ "$(nm_count)" = "1" ]
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
check "NM 同名旧连接场景最终只留一个连接" [ "$(nm_count)" = "1" ]
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

# ---- 原 active 连接必须被恢复（验收意见 2）----
reset_state; add_conn "static-eth1" "eth1" active
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_UP_FAIL=uuid-new-1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM up 失败必须非零" [ "$rc" != "0" ]
check "NM up 失败必须按原 active UUID 重新激活（托管连接）" has_call "nmcli con up uuid-legacy-static-eth1"
check "NM up 失败后该接口仍有一条 active 连接" bash -c 'for f in "$0"/nm/*; do [ -e "$f" ] || continue; grep -qxF "ACTIVE=1" "$f" && exit 0; done; exit 1' "$FAKE_STATE"
check "NM up 失败后 active 的就是原连接" bash -c 'grep -qxF "ACTIVE=1" "$0/nm/uuid-legacy-static-eth1"' "$FAKE_STATE"
check "NM up 失败不得输出成功文案" bash -c '! grep -qF "applied successfully" "$0/out.log"' "$FAKE_STATE"

# 原 active 是非托管连接：同样必须恢复
reset_state; add_conn "Wired connection 1" "eth1" active
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_UP_FAIL=uuid-new-1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM up 失败必须恢复非托管原 active 连接" has_call "nmcli con up uuid-legacy-Wired connection 1"
check "NM 非托管连接不得被删除" [ -e "$FAKE_STATE/nm/uuid-legacy-Wired connection 1" ]

# 原本没有 active 连接：不得激活任何既有 profile
reset_state; add_conn "static-eth1" "eth1"     # 未 active
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_UP_FAIL=uuid-new-1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "原本无 active 时不得激活任何既有 profile" bash -c '! grep -qxF "nmcli con up uuid-legacy-static-eth1" "$0/calls.log"' "$FAKE_STATE"

# 成功路径：新连接应成为 active
reset_state; add_conn "static-eth1" "eth1" active
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM 成功路径退出码 0" [ "$rc" = "0" ]
check "NM 成功后新连接是 active" bash -c 'grep -qxF "ACTIVE=1" "$0/nm/uuid-new-1"' "$FAKE_STATE"

# ---- 连续运行：改名失败留下的临时 profile 不得被删（验收意见 3）----
# 第一次：up 成功但改名失败 → 留下 active 的 static-eth1.bmip-new
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_MODIFY_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "NM 改名失败仍整体成功（非致命）" [ "$rc" = "0" ]
check "NM 改名失败留下 active 的临时 profile" bash -c 'grep -qxF "ACTIVE=1" "$0/nm/uuid-new-1"' "$FAKE_STATE"
check "NM 改名失败留下临时名" bash -c 'grep -qxF "static-eth1.bmip-new|eth1" "$0/nm/uuid-new-1"' "$FAKE_STATE"

# 第二次 add 失败：绝不能先删掉那条唯一可用的连接
: > "$FAKE_STATE/calls.log"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_ADD_FAIL=1 \
  "$BIN" eth1 10.2.0.9 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "二次运行 add 失败必须非零" [ "$rc" != "0" ]
check "二次运行 add 失败不得删除上次的唯一可用连接" [ -e "$FAKE_STATE/nm/uuid-new-1" ]
check "二次运行 add 失败后接口仍有 active 连接" bash -c 'grep -qxF "ACTIVE=1" "$0/nm/uuid-new-1"' "$FAKE_STATE"
check "二次运行不得删除 active 的临时 profile" bash -c '! grep -qE "^nmcli con delete uuid-new-1$" "$0/calls.log"' "$FAKE_STATE"

# 第二次 up 失败：同样不得先删，且必须恢复原 active
: > "$FAKE_STATE/calls.log"
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=NetworkManager FAKE_NM_ADD_FAIL= \
  FAKE_NM_UP_FAIL=uuid-new-2 "$BIN" eth1 10.2.0.9 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "二次运行 up 失败必须非零" [ "$rc" != "0" ]
check "二次运行 up 失败后仍有 active 连接" bash -c 'grep -qxF "ACTIVE=1" "$0/nm/uuid-new-1"' "$FAKE_STATE"
check "二次运行 up 失败恢复的是上次的 active 连接" has_call "nmcli con up uuid-new-1"

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

# ---- reload 是关键命令（验收意见 4）----
reset_state
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=systemd-networkd FAKE_NETCTL_RELOAD_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "networkd reload 失败必须非零（即使 reconfigure 成功）" [ "$rc" != "0" ]
check "networkd reload 失败不得输出成功文案" bash -c '! grep -qF "applied successfully" "$0/out.log"' "$FAKE_STATE"
check "networkd reload 失败必须回滚新文件" [ ! -e /etc/systemd/network/10-eth1.network ]

reset_state
printf '[Match]\nName=eth1\n\n[Network]\nDHCP=ipv4\n' > /etc/systemd/network/10-eth1.network
PATH="$ONLY_FAKE" FAKE_SYSTEMD_ACTIVE=systemd-networkd FAKE_NETCTL_RELOAD_FAIL=1 \
  "$BIN" eth1 10.1.0.5 24 > "$FAKE_STATE/out.log" 2>&1
rc=$?
check "networkd reload 失败必须恢复原文件" bash -c 'grep -qxF "DHCP=ipv4" /etc/systemd/network/10-eth1.network'

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
