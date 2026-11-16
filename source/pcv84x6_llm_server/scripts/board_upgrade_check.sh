#!/bin/bash
# Upgrade the test board from the v0.6.8 tarball install to the v0.6.9 .deb,
# keeping every piece of state the operator would notice losing.
#
#   scripts/board_upgrade_check.sh dist/cv84x6-llm-server_0.6.9_arm64.deb
#
# Board: 10.42.0.242 only. Run this from 13.24 over ssh.
#
# What is captured before, and compared after:
#   * etc/server.env, byte for byte (port, data dir, interpreter)
#   * state.json's settings (admin password hash, concurrency, cache config)
#     and its API key list
#   * agents/agents.json (per-agent secrets, model, port, thinking)
#   * the models directory (names and sizes)
# The point is not "does it install" -- the container test covers that -- but
# "does an upgrade keep this operator's board exactly as they left it".
#
# It deliberately does NOT uninstall anything first: real upgrades go over a
# live install, and that is the case that has to work.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

DEB=${1:?usage: board_upgrade_check.sh <deb>}
case "$DEB" in /*) ;; *) DEB=$ROOT/$DEB ;; esac
[ -f "$DEB" ] || { echo "no such deb: $DEB" >&2; exit 2; }

HOST=linaro@10.42.0.242
SSH=(sshpass -p linaro ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$HOST")
SCP=(sshpass -p linaro scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
PREFIX=/opt/sophgo/cv84x6_llm_server
DATA=/data/cv84x6_llm_server

FAIL=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }
remote() { "${SSH[@]}" "$1"; }
# sudo needs a password on this board, so root-only commands feed it on stdin
# (`echo linaro | sudo -S`). dpkg itself runs the maintainer scripts as root;
# this is only for the apt call and dmesg.

echo "=== 0. board reachable, and it is the right board ==="
remote 'uname -m' | grep -qx aarch64 && pass "board is aarch64" || fail "board is not aarch64"
remote "cat $PREFIX/VERSION" > /tmp/board-version-before.txt 2>/dev/null
BEFORE_VERSION=$(cat /tmp/board-version-before.txt)
echo "   current version: $BEFORE_VERSION"
[ "$BEFORE_VERSION" = "0.6.8" ] || echo "   note: not upgrading from 0.6.8 ($BEFORE_VERSION)"

echo
echo "=== 1. capture the state that must survive ==="
remote "cat $PREFIX/etc/server.env" > /tmp/board-env-before.txt 2>/dev/null
[ -s /tmp/board-env-before.txt ] && pass "captured server.env" || fail "no server.env on the board"
ENV_SUM=$(sha256sum /tmp/board-env-before.txt | cut -d' ' -f1)

remote "cat $DATA/state/state.json" > /tmp/board-state-before.json 2>/dev/null
python3 - <<'PY' || fail "could not read state.json"
import json
d = json.load(open("/tmp/board-state-before.json"))
s = d["settings"]
print("   admin_password_hash (first 16):", s["admin_password_hash"][:16])
print("   max_concurrent_per_model:", s.get("max_concurrent_per_model"))
print("   api keys:", len(d["keys"]), "->", sorted(k["name"] for k in d["keys"])[:6])
json.dump({"settings": s, "keys": sorted((k["id"], k["name"], k["key_hash"]) for k in d["keys"])},
          open("/tmp/board-state-before.norm.json", "w"))
PY
pass "captured state.json"

remote "cat $DATA/agents/agents.json" > /tmp/board-agents-before.json 2>/dev/null
python3 - <<'PY' || fail "could not read agents.json"
import json
d = json.load(open("/tmp/board-agents-before.json"))
for a, v in sorted(d.items()):
    print("  ", a, "port", v.get("port"), "model", v.get("default_model"),
          "secret", (v.get("secret") or "")[:6] + "...")
json.dump({a: {k: v.get(k) for k in ("port", "secret", "default_model", "thinking", "key_id")}
           for a, v in d.items()}, open("/tmp/board-agents-before.norm.json", "w"))
PY
pass "captured agents.json"

remote "ls -la $DATA/models/ | tail -n +2" > /tmp/board-models-before.txt 2>/dev/null
MODEL_COUNT=$(remote "find $DATA/models -name '*.bmodel' | wc -l")
echo "   model files: $MODEL_COUNT"

echo
echo "=== 2. what is running now ==="
remote "systemctl is-enabled cv84x6-llm; systemctl is-active cv84x6-llm" > /tmp/board-svc-before.txt 2>/dev/null
cat /tmp/board-svc-before.txt | sed 's/^/   /'
remote 'curl -s http://127.0.0.1:8000/healthz' | grep -q '"ok":true' \
  && pass "service healthy before the upgrade" || fail "service not healthy before the upgrade"
LOADED_BEFORE=$(remote 'curl -s http://127.0.0.1:8000/healthz | python3 -c "import json,sys;print(json.load(sys.stdin)[\"loaded\"])"')
echo "   models loaded: $LOADED_BEFORE"

echo
echo "=== 3. copy the deb and install it ==="
"${SCP[@]}" "$DEB" "$HOST:/tmp/$(basename "$DEB")" && pass "deb copied to the board" || fail "could not copy the deb"
remote "sha256sum /tmp/$(basename "$DEB")" > /tmp/board-deb-sha.txt 2>/dev/null
LOCAL_SHA=$(sha256sum "$DEB" | cut -d' ' -f1)
grep -q "$LOCAL_SHA" /tmp/board-deb-sha.txt && pass "deb sha256 matches after transfer" \
  || fail "deb sha256 differs after transfer"

remote "echo linaro | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/$(basename "$DEB")" \
  > /tmp/board-install.log 2>&1
INSTALL_RC=$?
echo "   apt install exit=$INSTALL_RC"
if [ "$INSTALL_RC" -eq 0 ]; then
  pass "apt install succeeded"
else
  fail "apt install failed"
  tail -30 /tmp/board-install.log | sed 's/^/   /'
fi

echo
echo "=== 4. version, unit, service ==="
# `dpkg -s | sed` rather than `dpkg-query -W -f=...`: the format string's
# ${Version} has to survive two shells' worth of expansion, and getting that
# wrong reads as "the package is not 0.6.9" when it is.
check "dpkg reports 0.6.9" \
  "remote 'dpkg -s cv84x6-llm-server | sed -n \"s/^Version: //p\"' | grep -qx 0.6.9"
check "VERSION file is 0.6.9" "remote 'cat $PREFIX/VERSION' | grep -qx 0.6.9"
check "unit is enabled" "remote 'systemctl is-enabled cv84x6-llm' | grep -qx enabled"
check "unit is active" "remote 'systemctl is-active cv84x6-llm' | grep -qx active"
check "page answers HTTP 200" "[ \"\$(remote 'curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/')\" = 200 ]"
check "healthz reports 0.6.9" "remote 'curl -s http://127.0.0.1:8000/healthz' | grep -q '\"version\":\"0.6.9\"'"

echo
echo "=== 5. nothing the operator set was reset ==="
remote "cat $PREFIX/etc/server.env" > /tmp/board-env-after.txt 2>/dev/null
check "server.env byte-for-byte identical" \
  "[ \"\$(sha256sum /tmp/board-env-after.txt | cut -d' ' -f1)\" = '$ENV_SUM' ]"

remote "cat $DATA/state/state.json" > /tmp/board-state-after.json 2>/dev/null
python3 - <<'PY' || fail "state.json changed in a way it should not have"
import json
before = json.load(open("/tmp/board-state-before.norm.json"))
after = json.load(open("/tmp/board-state-after.json"))
problems = []
if after["settings"]["admin_password_hash"] != before["settings"]["admin_password_hash"]:
    problems.append("admin password hash changed")
for k in ("max_concurrent_per_model", "prefix_cache_max_mb", "prefix_cache_ttl_min",
          "require_api_key", "max_queue"):
    if after["settings"].get(k) != before["settings"].get(k):
        problems.append(f"{k}: {before['settings'].get(k)} -> {after['settings'].get(k)}")
after_keys = sorted((k["id"], k["name"], k["key_hash"]) for k in after["keys"])
if after_keys != [tuple(x) for x in before["keys"]]:
    problems.append("API keys changed")
if problems:
    print("   " + "\n   ".join(problems))
    raise SystemExit(1)
print("   settings, admin password hash and all API keys identical")
PY

remote "cat $DATA/agents/agents.json" > /tmp/board-agents-after.json 2>/dev/null
python3 - <<'PY' || fail "agents.json changed in a way it should not have"
import json
before = json.load(open("/tmp/board-agents-before.norm.json"))
after = json.load(open("/tmp/board-agents-after.json"))
problems = []
for a, v in before.items():
    if a not in after:
        problems.append(f"{a} disappeared"); continue
    for k, val in v.items():
        if after[a].get(k) != val:
            problems.append(f"{a}.{k}: {val} -> {after[a].get(k)}")
if problems:
    print("   " + "\n   ".join(problems))
    raise SystemExit(1)
print("   every agent keeps its port, secret, model and thinking setting")
PY

MODEL_COUNT_AFTER=$(remote "find $DATA/models -name '*.bmodel' | wc -l")
check "model files unchanged ($MODEL_COUNT)" "[ '$MODEL_COUNT_AFTER' = '$MODEL_COUNT' ]"
check "data directory marker still there" "remote 'test -f $DATA/.cv84x6-data'"

echo
echo "=== 6. the NPU worker was stopped, not killed ==="
# A SIGKILL mid-load can hang the TPU; the unit asks for SIGTERM and 60 s.
grep -qiE "SIGKILL|killed" /tmp/board-install.log \
  && fail "install log mentions a kill" || pass "no kill in the install log"
NEW_OOPS=$(remote "echo linaro | sudo -S dmesg | tail -200 | grep -ciE 'oops|BUG:|driver.*timeout|Out of memory'")
[ "${NEW_OOPS:-99}" = "0" ] && pass "no oops/OOM/driver timeout in recent dmesg" \
  || fail "dmesg has $NEW_OOPS recent oops/OOM/timeout line(s)"

echo
echo "=== 7. console copy, as served ==="
ASSET=$(remote "ls $PREFIX/web/dist/assets/*.js | head -1")
remote "cat $ASSET" > /tmp/board-app.js 2>/dev/null
python3 - <<'PY'
text = open("/tmp/board-app.js", encoding="utf-8", errors="replace").read()
bad = [s for s in ("2.6 GB", "板卡共", "不能与", "无法同时运行", "下载约 78 MB") if s in text]
good = [s for s in ("预估内存", "MemAvailable", "apt purge") if s in text]
print("   removed claims still present:", bad or "none")
print("   required copy present:", good)
raise SystemExit(1 if bad or len(good) < 3 else 0)
PY
[ $? -eq 0 ] && pass "served console has the new copy and no capacity claims" \
  || fail "served console copy is wrong"

echo
if [ "$FAIL" -eq 0 ]; then echo "ALL PASS"; else echo "$FAIL FAILURE(S)"; fi
exit "$FAIL"
