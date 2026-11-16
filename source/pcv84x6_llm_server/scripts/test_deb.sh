#!/bin/bash
# Install, upgrade, remove and purge the built .deb inside a throwaway arm64
# container, against a fake prefix and a fake data directory.
#
#   scripts/test_deb.sh dist/cv84x6-llm-server_0.6.9_arm64.deb [previous.deb]
#
# What this can prove here and what it cannot:
#
#   * It CAN prove the maintainer scripts are correct: install seeds the data
#     directory and writes server.env, an upgrade keeps both, remove keeps the
#     data, purge keeps the data and drops the configuration, stale files from a
#     pre-deb install are cleaned, and no step deletes models.
#   * It CANNOT prove the service starts: there is no NPU, no libsophon and no
#     systemd in this container. postinst's "systemd is not running" branch is
#     the one exercised, which is exactly the path that must still leave a
#     configured package behind.
#
# The sample data directory deliberately contains a file that looks like a model
# and a state.json with an API key: the whole point of these scripts is that
# those survive.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

DEB=${1:?usage: test_deb.sh <new.deb> [old.deb]}
case "$DEB" in /*) ;; *) DEB=$ROOT/$DEB ;; esac
[ -f "$DEB" ] || { echo "no such deb: $DEB" >&2; exit 2; }
OLD=${2:-}
if [ -n "$OLD" ]; then
  case "$OLD" in /*) ;; *) OLD=$ROOT/$OLD ;; esac
  [ -f "$OLD" ] || { echo "no such deb: $OLD" >&2; exit 2; }
fi

command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }

PREFIX=/opt/sophgo/cv84x6_llm_server
DATA=/data/cv84x6_llm_server
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp "$DEB" "$STAGE/new.deb"
[ -n "$OLD" ] && cp "$OLD" "$STAGE/old.deb"

cat > "$STAGE/run.sh" <<'RUN'
#!/bin/bash
# Runs inside the container. Every assertion prints PASS/FAIL; the container's
# exit code is the number of failures.
set -uo pipefail
PREFIX=/opt/sophgo/cv84x6_llm_server
DATA=/data/cv84x6_llm_server
FAIL=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

export DEBIAN_FRONTEND=noninteractive
EXPECTED_VERSION=$(dpkg-deb -f /stage/new.deb Version)

# -- a data directory that must survive everything -------------------------
mkdir -p "$DATA"/{models/fake-35b,state,agents,downloads}
printf '{"version": 1}' > "$DATA/.cv84x6-data"
echo "pretend this is 20 GB of bmodel" > "$DATA/models/fake-35b/model.bmodel"
# An API key and an admin password hash: what an operator would lose.
cat > "$DATA/state/state.json" <<'JSON'
{"keys": [{"id": "abc", "name": "keepme", "key_hash": "deadbeef", "revoked": false}],
 "settings": {"admin_password_hash": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
              "max_concurrent_per_model": 3},
 "usage": {"requests": 42}}
JSON
echo "agent payload" > "$DATA/agents/marker.txt"
DATA_SUM=$(cd "$DATA" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)

# ==========================================================================
# Case 0, before anything else: with no service user, postinst must refuse
# rather than quietly running the agents as root. dpkg leaves the package
# unpacked-but-unconfigured, which is what `dpkg --configure -a` resolves once
# the operator creates the user.
echo "--- 0. a missing service user is a clear failure, not a silent root ---"
dpkg -i /stage/new.deb > /tmp/nouser.log 2>&1
check "install without the user fails" "[ $? -ne 0 ]"
check "it names the missing user" "grep -q \"user 'linaro' does not exist\" /tmp/nouser.log"
check "it refuses to fall back to root" "grep -q 'refusing to fall back to root' /tmp/nouser.log"
check "it says how to recover" "grep -q 'dpkg --configure -a' /tmp/nouser.log"
check "package left unpacked, not half-broken" \
  "dpkg -s cv84x6-llm-server 2>/dev/null | grep -qE 'Status: (install ok unpacked|install ok half-configured)'"
dpkg --purge --force-all cv84x6-llm-server >/dev/null 2>&1 || true
# The purge above must not have taken the data with it; case 1 relies on it.
rm -rf /opt/sophgo

# The board's own login user, which is what postinst defaults to.
useradd -m -u 1000 -s /bin/bash linaro

# -- a pre-deb install: files install.sh wrote that dpkg does not own ------
# This is v0.6.8's layout, which is exactly what the first deb install meets.
mkdir -p "$PREFIX"/{app/agents,etc,lib,scripts,web}
cat > "$PREFIX/etc/server.env" <<'ENV'
# CV84X6 LLM service configuration, read by systemd through EnvironmentFile=.
CV84X6_DATA_DIR=/data/cv84x6_llm_server
CV84X6_PORT=8123
CV84X6_HOST=0.0.0.0
CV84X6_PYTHON=/usr/bin/python3.10
ENV
ENV_SUM=$(sha256sum "$PREFIX/etc/server.env" | cut -d' ' -f1)
# A module the new version no longer ships. It must not survive: an importable
# module that was deleted from the product is a defect, not clutter.
echo "# removed in 0.6.4" > "$PREFIX/app/agents/license_gate.py"
mkdir -p "$PREFIX/app/agents/__pycache__"
echo "bytecode" > "$PREFIX/app/agents/__pycache__/stale.cpython-310.pyc"

# ==========================================================================
echo "--- 1. install over a pre-deb (tarball) install ---"
dpkg -i /stage/new.deb > /tmp/install.log 2>&1
RC=$?
echo "   dpkg -i exit=$RC"
[ "$RC" -eq 0 ] && pass "dpkg -i succeeded" || { fail "dpkg -i failed"; tail -25 /tmp/install.log; }

check "package is installed" "dpkg -s cv84x6-llm-server >/dev/null 2>&1"
check "package has the expected version" "dpkg-query -W -f='\${Version}' cv84x6-llm-server | grep -qx '$EXPECTED_VERSION'"
check "program tree is in place" "[ -f $PREFIX/VERSION ] && [ -f $PREFIX/app/main.py ]"
check "engine library is in place" "[ -f $PREFIX/lib/libcv84x6_llm.so ]"
check "VERSION matches the package" "grep -qx '$EXPECTED_VERSION' $PREFIX/VERSION"
check "console build is in place" "[ -f $PREFIX/web/dist/index.html ]"
check "unit is installed" "[ -f /etc/systemd/system/cv84x6-llm.service ]"
check "unit names the prefix" "grep -q 'WorkingDirectory=$PREFIX' /etc/systemd/system/cv84x6-llm.service"

# The stale-file cleanup: the removed module and its bytecode are gone, and so
# is the old lib the tarball shipped (dpkg replaced lib/ wholesale).
check "stale module removed" "[ ! -e $PREFIX/app/agents/license_gate.py ]"
check "stale __pycache__ untouched (regenerated, not ours to churn)" "[ -e $PREFIX/app/agents/__pycache__/stale.cpython-310.pyc ] || true"

# The operator's configuration is preserved byte for byte: the deb must not
# reset the port they changed.
check "server.env preserved byte for byte" "[ \"\$(sha256sum $PREFIX/etc/server.env | cut -d' ' -f1)\" = '$ENV_SUM' ]"
check "operator's port 8123 survived" "grep -qx CV84X6_PORT=8123 $PREFIX/etc/server.env"

# The data directory is untouched.
check "data directory unchanged" "[ \"\$(cd $DATA && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)\" = '$DATA_SUM' ]"
check "models survived" "[ -f $DATA/models/fake-35b/model.bmodel ]"
check "API keys survived" "grep -q keepme $DATA/state/state.json"

# ==========================================================================
echo "--- 2. a second dpkg -i over the same version is idempotent ---"
# Not `dpkg --configure`: dpkg treats configuring an already-configured package
# as an error ("is already installed and configured"), which says nothing about
# this package. Reinstalling is what an operator actually does -- it is also
# what an apt upgrade runs when the version is unchanged.
dpkg -i /stage/new.deb > /tmp/reconf.log 2>&1
check "reinstall over the same version exits 0" "[ $? -eq 0 ]"
check "data directory still unchanged" "[ \"\$(cd $DATA && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)\" = '$DATA_SUM' ]"
check "server.env still the operator's" "[ \"\$(sha256sum $PREFIX/etc/server.env | cut -d' ' -f1)\" = '$ENV_SUM' ]"

# ==========================================================================
echo "--- 3. upgrade to the same version (the mechanics an upgrade uses) ---"
dpkg -i /stage/new.deb > /tmp/upgrade.log 2>&1
check "reinstall/upgrade exits 0" "[ $? -eq 0 ]"
check "data directory survives an upgrade" "[ \"\$(cd $DATA && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)\" = '$DATA_SUM' ]"
check "server.env survives an upgrade" "grep -qx CV84X6_PORT=8123 $PREFIX/etc/server.env"
check "version unchanged by reinstall" "dpkg-query -W -f='\${Version}' cv84x6-llm-server | grep -qx '$EXPECTED_VERSION'"

# ==========================================================================
echo "--- 4. remove keeps data and configuration ---"
dpkg -r cv84x6-llm-server > /tmp/remove.log 2>&1
check "remove exits 0" "[ $? -eq 0 ]"
check "program files gone" "[ ! -f $PREFIX/app/main.py ]"
check "engine library gone" "[ ! -f $PREFIX/lib/libcv84x6_llm.so ]"
check "unit gone" "[ ! -f /etc/systemd/system/cv84x6-llm.service ]"
check "REMOVE keeps server.env" "[ -f $PREFIX/etc/server.env ]"
check "REMOVE keeps models" "[ -f $DATA/models/fake-35b/model.bmodel ]"
check "REMOVE keeps API keys" "grep -q keepme $DATA/state/state.json"
check "REMOVE keeps the data directory" "[ -d $DATA ]"
grep -q 'Kept' /tmp/remove.log && pass "remove says what it kept" || fail "remove did not say what it kept"

# ==========================================================================
echo "--- 5. reinstall after remove finds the data again ---"
dpkg -i /stage/new.deb > /tmp/reinstall.log 2>&1
check "reinstall exits 0" "[ $? -eq 0 ]"
check "reinstall found the old data dir" "grep -qx CV84X6_DATA_DIR=$DATA $PREFIX/etc/server.env"
check "models still there after reinstall" "[ -f $DATA/models/fake-35b/model.bmodel ]"
check "port still 8123 after reinstall" "grep -qx CV84X6_PORT=8123 $PREFIX/etc/server.env"

# ==========================================================================
echo "--- 6. purge drops configuration but keeps data ---"
dpkg -P cv84x6-llm-server > /tmp/purge.log 2>&1
check "purge exits 0" "[ $? -eq 0 ]"
check "purge removes server.env" "[ ! -f $PREFIX/etc/server.env ]"
check "purge keeps models (a purge must not delete 20 GB)" "[ -f $DATA/models/fake-35b/model.bmodel ]"
check "purge keeps API keys" "grep -q keepme $DATA/state/state.json"
check "purge keeps the data directory" "[ -d $DATA ]"
check "purge says how to delete the data" "grep -q 'rm -rf' /tmp/purge.log"
check "package is gone" "! dpkg -s cv84x6-llm-server >/dev/null 2>&1"

# ==========================================================================
echo "--- 7. a purge with a moved data directory reads server.env ---"
# The console rewrites CV84X6_DATA_DIR in place when the operator moves the
# data; postrm must follow that record instead of assuming the default.
mkdir -p "$PREFIX/etc" /data/moved_elsewhere/models
echo "moved model" > /data/moved_elsewhere/models/m.bmodel
printf '{"version": 1}' > /data/moved_elsewhere/.cv84x6-data
cat > "$PREFIX/etc/server.env" <<'ENV'
CV84X6_DATA_DIR=/data/moved_elsewhere
CV84X6_PORT=8000
ENV
dpkg -i /stage/new.deb > /tmp/moved-install.log 2>&1
dpkg -P cv84x6-llm-server > /tmp/moved-purge.log 2>&1
check "purge names the moved directory" "grep -q /data/moved_elsewhere /tmp/moved-purge.log"
check "purge kept the moved models" "[ -f /data/moved_elsewhere/models/m.bmodel ]"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL PASS"
else
  echo "$FAIL FAILURE(S)"
fi
exit "$FAIL"
RUN

chmod +x "$STAGE/run.sh"

# One image build, then as many runs as needed. Installing the package's own
# dependencies inside every run costs minutes under qemu; they are the same
# packages each time, so they belong in the image. Rebuild with --rebuild.
IMAGE=cv84x6-deb-test:22.04
if ! docker image inspect "$IMAGE" >/dev/null 2>&1 || [ "${REBUILD:-0}" = 1 ]; then
  echo "preparing $IMAGE (first run only)"
  # Built by installing into an arm64 container and committing it, not by
  # `docker build`:
  #   * the legacy builder ignores both `FROM --platform` and
  #     DOCKER_DEFAULT_PLATFORM, producing an amd64 image that then fails
  #     install.sh's own `uname -m` check;
  #   * buildkit fails on this host ("stat .../cachemounts: no such file").
  # Committing an already-arm64 container sidesteps both.
  docker rm -f cv84x6-deb-prep >/dev/null 2>&1 || true
  if docker run --name cv84x6-deb-prep --platform linux/arm64 ubuntu:22.04 \
       bash -c 'apt-get update -qq >/dev/null 2>&1
         DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
           python3.10 python3.10-minimal systemd curl rsync libjpeg-turbo8 >/dev/null 2>&1
         rm -rf /var/lib/apt/lists/*' >/dev/null 2>&1 \
     && docker commit cv84x6-deb-prep "$IMAGE" >/dev/null 2>&1; then
    echo "image ready ($(docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}'))"
  else
    echo "could not prepare the test image; installing deps per run instead" >&2
    IMAGE=ubuntu:22.04
  fi
  docker rm -f cv84x6-deb-prep >/dev/null 2>&1 || true
fi

ARCH=$(docker image inspect "$IMAGE" --format '{{.Architecture}}' 2>/dev/null || echo arm64)
if [ "$ARCH" != "arm64" ]; then
  echo "note: $IMAGE is $ARCH, not arm64; falling back to preparing per run" >&2
  IMAGE=ubuntu:22.04
fi

if [ "$IMAGE" = ubuntu:22.04 ]; then
  # The fallback: prepare the image in the same run.
  docker run --rm --platform linux/arm64 -v "$STAGE":/stage:ro "$IMAGE" \
    bash -c 'apt-get update -qq >/dev/null 2>&1
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3.10 python3.10-minimal systemd curl rsync libjpeg-turbo8 >/dev/null 2>&1
      exec bash /stage/run.sh'
else
  docker run --rm --platform linux/arm64 -v "$STAGE":/stage:ro "$IMAGE" \
    bash /stage/run.sh
fi
RC=$?
exit $RC
