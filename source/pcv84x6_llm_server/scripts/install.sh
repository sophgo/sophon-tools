#!/usr/bin/env bash
# Install or upgrade the CV84X6 LLM service from an unpacked release.
#
#   sudo ./scripts/install.sh [--prefix /opt/sophgo/cv84x6_llm_server]
#        [--data-dir /data/cv84x6_llm_server] [--port 8000]
#        [--python /data/venv/bin/python] [--user linaro]
#        [--no-start] [--check-only] [--in-place]
#
# Two trees, on purpose:
#   --prefix    program only (app/ lib/ vendor/ web/ tools/ model-config/
#               scripts/ VERSION). Replaced wholesale on upgrade.
#   --data-dir  everything that changes: models/, state/ (keys, usage, logs),
#               agents/, downloads/. Never touched by an install.
# The data directory's location lives in <prefix>/etc/server.env, which the
# systemd unit reads through EnvironmentFile=; the console can move the data
# later and rewrites that one line.
#
# --in-place is what the .deb's postinst uses: dpkg has already unpacked this
# release into --prefix, so there is nothing to copy. Everything else (Python
# discovery, data-directory seeding, server.env, the systemd unit) is the same
# code path, which is the point -- the deb and the tarball cannot configure the
# service differently. Without it, the source tree is copied into --prefix (the
# tarball flow).
#
# Offline: nothing is downloaded and no system package is touched. The web
# stack comes from vendor/; tokenising and image preprocessing are inside
# lib/libcv84x6_llm.so, so the Python interpreter only has to run the service.
# The library links the board's existing libjpeg/libz; no -dev package is needed
# (matching headers are vendored under native/include/jpeg/).
set -euo pipefail
SRC=$(cd "$(dirname "$0")/.." && pwd)

PREFIX=/opt/sophgo/cv84x6_llm_server
DATA_DIR=/data/cv84x6_llm_server
PORT=8000
HOST=0.0.0.0
PY=""
RUN_USER=${SUDO_USER:-linaro}
START=1
CHECK_ONLY=0
IN_PLACE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX=$2; shift 2 ;;
    --data-dir) DATA_DIR=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --host) HOST=$2; shift 2 ;;
    --python) PY=$2; shift 2 ;;
    --user) RUN_USER=$2; shift 2 ;;
    --no-start) START=0; shift ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --in-place) IN_PLACE=1; shift ;;
    -h|--help) sed -n 2,28p "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
# Absolute, canonical: the marker and the env file must agree with what the
# service resolves at runtime, or a move would look like it targets itself.
case "$DATA_DIR" in
  /*) DATA_DIR=$(realpath -m "$DATA_DIR") ;;
  *) echo "[install] ERROR: --data-dir must be an absolute path" >&2; exit 2 ;;
esac
ENV_FILE=$PREFIX/etc/server.env
# Where versions before this one kept their data. Same filesystem as the new
# default in a normal install, so the upgrade is a rename, not a copy.
LEGACY_PREFIX=/data/cv84x6-llm

say() { printf '[install] %s\n' "$*"; }
die() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

id "$RUN_USER" >/dev/null 2>&1 || { echo "[install] ERROR: user $RUN_USER does not exist" >&2; exit 1; }

[ -f "$SRC/VERSION" ] || die "run this from an unpacked release (VERSION missing)"
VERSION=$(cat "$SRC/VERSION")
[ "$(uname -m)" = "aarch64" ] || die "this release is for aarch64 (CV84X6), not $(uname -m)"
[ -e /dev/bm-tpu0 ] || [ -e /dev/bmdev-ctl ] || say "warning: no bm-tpu device node found"
# A tarball install on a board without libsophon is a mistake worth stopping
# for. A package install is not the same situation: dpkg must finish configuring
# (an unconfigured package blocks every later apt operation), and its postinst
# already reports this with the exact recovery step. So in-place warns, while
# the tarball flow still refuses.
if [ ! -d /opt/sophon/libsophon-current/lib ]; then
  if [ "$IN_PLACE" = 1 ]; then
    say "warning: libsophon not found at /opt/sophon/libsophon-current"
    say "warning: the service will not start until the Sophgo runtime is installed"
  else
    die "libsophon not found at /opt/sophon/libsophon-current"
  fi
fi

# Python checks run as the service user: packages are often in that user's
# ~/.local (pip --user), which root does not see.
#
# runuser first, sudo only as a fallback. Both switch user, but runuser is part
# of util-linux (always present) while sudo is not -- and the .deb's postinst
# runs as root already, so making a package depend on sudo purely to drop
# privileges would be an odd dependency to impose. The last branch covers a
# minimal image with neither.
as_user() {
  if [ "$(id -u)" = 0 ] && [ "$RUN_USER" != root ]; then
    if [ -x /usr/sbin/runuser ] || command -v runuser >/dev/null 2>&1; then
      runuser -u "$RUN_USER" -- env "$@"
    elif command -v sudo >/dev/null 2>&1; then
      sudo -u "$RUN_USER" -H env "$@"
    else
      # No way to switch user. Enumeration still works (the interpreter exists,
      # it is the packages that may be in the wrong home), so try it directly
      # rather than failing the whole install over a missing helper.
      env "$@"
    fi
  else
    env "$@"
  fi
}

# -- pick a Python interpreter ---------------------------------------------
# Tokenising and image preprocessing are in the engine library
# (lib/libcv84x6_llm.so), so the interpreter only has to run the service itself:
# any Python 3.10 works, and the web stack ships in vendor/. Previous versions
# also demanded numpy and tokenizers (and, for images,
# torch/transformers/pillow/qwen_vl_utils); none of that is needed any more.
EXTRA_PP=""
try_py() {  # $1 = interpreter; sets PY/EXTRA_PP on success
  local py=$1 sp
  [ -x "$py" ] || return 1
  as_user "$py" -c 'import sys; assert sys.version_info[:2] == (3, 10)' 2>/dev/null || return 1
  PY=$py; EXTRA_PP=""; return 0
}
if [ -n "$PY" ]; then
  try_py "$PY" || die "$PY is not a Python 3.10"
else
  for cand in /usr/bin/python3.10 /usr/bin/python3; do
    try_py "$cand" && break
  done
  [ -n "$PY" ] || die "no Python 3.10 found; pass --python"
fi
PP="$PREFIX/vendor${EXTRA_PP:+:$EXTRA_PP}"
say "python: $PY${EXTRA_PP:+ (PYTHONPATH +$EXTRA_PP)}"
as_user PYTHONPATH="$SRC/vendor${EXTRA_PP:+:$EXTRA_PP}" "$PY" -c 'import fastapi, uvicorn, pydantic' \
  || die "vendored web stack does not import with $PY"
if [ "$CHECK_ONLY" = 1 ]; then say "check only: all required pieces present"; exit 0; fi

[ "$(id -u)" = 0 ] || die "run with sudo (writes $PREFIX and the systemd unit)"
GROUP=$(id -gn "$RUN_USER")

# -- data directory: create it, or adopt the old layout ---------------------
# Manageable by the service user, and marked so a later move/purge knows the
# tree is ours (scripts/uninstall.sh --purge looks for the same marker).
seed_data_dir() {
  local dir=$1
  mkdir -p "$dir"/{models,state,agents,downloads}
  [ -f "$dir/.cv84x6-data" ] || printf '{"version": 1}' > "$dir/.cv84x6-data"
  chown -R "$RUN_USER:$GROUP" "$dir"
}

if [ -d "$LEGACY_PREFIX/data" ] || [ -d "$LEGACY_PREFIX/models" ]; then
  if [ -e "$DATA_DIR/state/state.json" ] || [ -n "$(ls -A "$DATA_DIR/models" 2>/dev/null || true)" ]; then
    say "old layout found at $LEGACY_PREFIX, but $DATA_DIR already has data -- leaving both alone"
    say "  move what you need by hand, then re-run; the old tree is not touched again"
  else
    mkdir -p "$DATA_DIR"
    say "migrating the old layout $LEGACY_PREFIX -> $DATA_DIR"
    # mv, not cp: /data/cv84x6-llm and /data/cv84x6_llm_server are normally on the
    # same filesystem, so this is a rename and a 20 GB model is not rewritten.
    if [ -d "$LEGACY_PREFIX/data" ]; then
      [ -e "$DATA_DIR/state" ] && rmdir "$DATA_DIR/state" 2>/dev/null || true
      mv "$LEGACY_PREFIX/data" "$DATA_DIR/state" && say "  moved data/ -> state/ (keys, usage, logs kept)"
    fi
    if [ -d "$LEGACY_PREFIX/models" ]; then
      [ -e "$DATA_DIR/models" ] && rmdir "$DATA_DIR/models" 2>/dev/null || true
      mv "$LEGACY_PREFIX/models" "$DATA_DIR/models" && say "  moved models/ -> models/"
    fi
    # The old prefix also held the program; only declare it empty if it is.
    rmdir "$LEGACY_PREFIX" 2>/dev/null && say "  removed the now-empty $LEGACY_PREFIX" || true
  fi
fi
seed_data_dir "$DATA_DIR"
say "data directory: $DATA_DIR"

# -- program tree ----------------------------------------------------------
if systemctl is-active --quiet cv84x6-llm 2>/dev/null; then
  say "stopping running service"
  systemctl stop cv84x6-llm
fi
# The install tree is code only, and an upgrade replaces it wholesale: --delete
# also removes files a previous version shipped and this one does not, which is
# the whole point of keeping data elsewhere. etc/ (the configuration: port,
# interpreter, where the data moved to) is the one thing that survives.
#
# --in-place means dpkg already put this release in $PREFIX, so the source *is*
# the destination. Copying would be a recursive self-copy; upgrading is dpkg's
# job there, and it removes files this version does not ship on its own. What
# must still happen here is the ownership fix-up: dpkg unpacks as root:root,
# while the service runs as $RUN_USER.
mkdir -p "$PREFIX" "$PREFIX/etc"
if [ "$IN_PLACE" = 1 ]; then
  [ "$(cd "$SRC" && pwd -P)" = "$(cd "$PREFIX" && pwd -P)" ] \
    || die "--in-place expects to run from $PREFIX (it is running from $SRC)"
  say "installing in place: dpkg unpacked this release into $PREFIX"
  # The unit's ExecStart reads these from $PREFIX, and the service runs as
  # $RUN_USER: a root-owned tree would break the console's own log rotation and
  # agent installs.
  if ! chown -R "$RUN_USER:$GROUP" "$PREFIX" 2>/dev/null; then
    die "could not give $PREFIX to $RUN_USER:$GROUP"
  fi
else
  rsync -a --delete --exclude '/etc/' "$SRC/" "$PREFIX/"
  chown -R "$RUN_USER:$GROUP" "$PREFIX"
fi

# -- configuration file: the one source of truth for the data location -----
# Written once. An upgrade keeps the recorded location, so moving the data
# from the console and then reinstalling does not silently undo the move.
if [ -f "$ENV_FILE" ]; then
  say "keeping the existing $ENV_FILE"
  # Upgrade from an install that had no env file: add the keys it lacks so the
  # unit's EnvironmentFile= is complete.
  grep -q '^CV84X6_DATA_DIR=' "$ENV_FILE" || echo "CV84X6_DATA_DIR=$DATA_DIR" >> "$ENV_FILE"
  grep -q '^CV84X6_PYTHON=' "$ENV_FILE" || echo "CV84X6_PYTHON=$PY" >> "$ENV_FILE"
  grep -q '^CV84X6_PORT=' "$ENV_FILE" || echo "CV84X6_PORT=$PORT" >> "$ENV_FILE"
  grep -q '^CV84X6_HOST=' "$ENV_FILE" || echo "CV84X6_HOST=$HOST" >> "$ENV_FILE"
  DATA_DIR=$(sed -n 's/^CV84X6_DATA_DIR=//p' "$ENV_FILE" | tail -1)
  PORT=$(sed -n 's/^CV84X6_PORT=//p' "$ENV_FILE" | tail -1)
  HOST=$(sed -n 's/^CV84X6_HOST=//p' "$ENV_FILE" | tail -1)
  PY=$(sed -n 's/^CV84X6_PYTHON=//p' "$ENV_FILE" | tail -1)
else
  cat > "$ENV_FILE" <<EOF
# CV84X6 LLM service configuration, read by systemd through EnvironmentFile=.
# A data directory move from the console rewrites CV84X6_DATA_DIR; everything
# else here is set by scripts/install.sh.
CV84X6_DATA_DIR=$DATA_DIR
CV84X6_PORT=$PORT
CV84X6_HOST=$HOST
CV84X6_PYTHON=$PY
EOF
  say "wrote $ENV_FILE"
fi
chown "$RUN_USER:$GROUP" "$ENV_FILE"
chmod 0644 "$ENV_FILE"
seed_data_dir "$DATA_DIR"

# -- systemd unit -------------------------------------------------------------
sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@PYTHON@#$PY#g" -e "s#@PYTHONPATH@#$PP#g" \
    -e "s#@ENV_FILE@#$ENV_FILE#g" -e "s#@PORT@#$PORT#g" \
    -e "s#@USER@#$RUN_USER#g" -e "s#@GROUP@#$GROUP#g" \
    "$PREFIX/deploy/cv84x6-llm.service" > /etc/systemd/system/cv84x6-llm.service
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  systemctl enable cv84x6-llm >/dev/null 2>&1
else
  # The unit file is written, but there is no systemd to load it into (a build
  # host, a container, a rescue boot). Say so instead of letting `systemctl`
  # fail under `set -e`; the package is still configured.
  say "warning: systemd is not running; unit written but not enabled"
fi
say "installed $VERSION to $PREFIX (data: $DATA_DIR)"

if [ "$START" = 1 ] && [ ! -d /run/systemd/system ]; then
  say "not started: systemd is not running"
  exit 0
fi

if [ "$START" = 1 ]; then
  systemctl start cv84x6-llm
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
      say "running: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT  (console password: admin -- change it)"
      exit 0
    fi
    sleep 1
  done
  die "service did not answer on :$PORT; see: journalctl -u cv84x6-llm -n 50"
fi
say "not started (--no-start); start with: sudo systemctl start cv84x6-llm"
