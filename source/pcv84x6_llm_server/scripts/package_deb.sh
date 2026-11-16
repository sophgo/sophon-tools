#!/usr/bin/env bash
# Build the arm64 Debian package from the same release tree as the tarball.
#
#   scripts/package_deb.sh --lib <libcv84x6_llm.so> --config <qwen3.5 config dir> [--out dist/]
#
# Output: dist/cv84x6-llm-server_<version>_arm64.deb and its .sha256.
#
# sophon-tools adaptation: --lib/--config now default to the pinned inputs in
# build/inputs/ (sha256-verified), so a clean checkout builds without personal
# paths or private credentials. Explicit arguments still win when given. See
# build/README.md for provenance. Everything below is byte-identical to the
# upstream script at fdd109c8 apart from that default and the COMMIT note.
#
# Why a deb at all. The tarball asks an operator to fetch an archive, unpack it,
# read a flag list and run install.sh as root. Every step is a chance to get the
# prefix or the data directory wrong, and nothing records what was installed, so
# "is this box on 0.6.8 or 0.6.9" is a question for a README. The deb answers it
# with `dpkg -l`, upgrades with one command, and removes cleanly.
#
# The payload is byte-identical to the tarball's (both come from package.sh), so
# the two cannot drift. What differs is the maintainer scripts: they reuse
# scripts/install.sh --in-place for Python discovery, data seeding, server.env
# and the systemd unit, because a second copy of that logic in postinst would
# eventually disagree with the first.
#
# Version comes from app/__init__.py and nowhere else.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

LIB="" CONFIG="" OUT="$ROOT/dist"
while [ $# -gt 0 ]; do
  case "$1" in
    --lib) LIB=$2; shift 2 ;;
    --config) CONFIG=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
# Default to the pinned build inputs (build/inputs/) when not given explicitly.
# Their sha256 manifest is verified by release.sh before this runs; an explicit
# --lib/--config is trusted as-is, exactly like the upstream invocation.
if [ -z "$LIB" ]; then
  LIB="$ROOT/build/inputs/lib/libcv84x6_llm.so"
fi
if [ -z "$CONFIG" ]; then
  CONFIG="$ROOT/build/inputs/qwen3_5-config"
fi
[ -n "$LIB" ] || { echo "--lib <libcv84x6_llm.so> is required" >&2; exit 2; }
[ -n "$CONFIG" ] || { echo "--config <qwen3.5 config dir> is required" >&2; exit 2; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required" >&2; exit 2; }

VERSION=$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"", open("app/__init__.py").read()).group(1))')
PKG=cv84x6-llm-server
DEB=${PKG}_${VERSION}_arm64.deb
# The paths in the maintainer scripts and the one below must agree: dpkg's file
# list, the systemd unit and scripts/install.sh all name this prefix.
PREFIX=/opt/sophgo/cv84x6_llm_server
RUN_USER=linaro

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# -- payload: exactly what the tarball ships -------------------------------
bash scripts/package.sh --lib "$LIB" --config "$CONFIG" --stage "$WORK/stage"
TREE=$WORK/stage/$(ls "$WORK/stage")

D=$WORK/pkg
mkdir -p "$D/DEBIAN" "$D$PREFIX" "$D/usr/share/doc/$PKG"
# -a keeps ownership out of the picture; dpkg unpacks as root:root and postinst
# hands the tree to the service user, which is the order dpkg expects.
cp -a "$TREE/." "$D$PREFIX/"

# Documentation: the operator-facing part of the package.
cp -a README.md "$D/usr/share/doc/$PKG/README.md"
if [ -f docs/DESIGN.md ]; then
  cp -a docs/DESIGN.md "$D/usr/share/doc/$PKG/DESIGN.md"
fi

# -- DEBIAN files ----------------------------------------------------------
# No conffile is declared anywhere on purpose. etc/server.env is written and
# rewritten by the service (the console edits CV84X6_DATA_DIR when the operator
# moves the data), and dpkg would prompt about a file the software is supposed
# to own. It does not ship in the package at all either: postinst generates it
# on first install and leaves it alone afterwards, which is what makes an
# upgrade keep the operator's port and data location.
cat > "$D/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: arm64
Maintainer: MYSWY <zetao.zhang@sophgo.com>
Section: misc
Priority: optional
Installed-Size: $(du -sk "$D$PREFIX" | cut -f1)
Depends: python3.10 (>= 3.10), systemd, curl, rsync, libjpeg-turbo8, zlib1g, libstdc++6, libc6 (>= 2.35)
Recommends: sophon-soc-libsophon
Description: offline OpenAI-compatible LLM service for CV84X6 (web console)
 Runs Qwen3.5/3.6-35B-A3B (32k and 128k) entirely on the CV84X6 NPU from a
 self-contained bmrt engine: an OpenAI-compatible /v1 API with SSE, function
 calling and prefix caching, a browser console, and one-click install of
 PicoClaw, opencode and OpenClaw against the local model.
 .
 Fully offline: tokenising and image preprocessing are inside the shipped
 engine library, and the web stack is vendored, so the only Python the board
 needs is its own python3.10. Models and agent packages come from the Sophgo
 dfss mirror on demand, never at install time.
 .
 Program files live under $PREFIX; everything that changes
 (models, API keys, usage, agent installs) lives in a data directory
 (/data/cv84x6_llm_server by default) that an upgrade and a removal leave
 untouched.
EOF

chmod 0755 "$D/DEBIAN"

# md5sums is what `dpkg -V` verifies against; dpkg-deb does not generate it.
# The format is `<md5><two spaces><path relative to />` with no leading "./" --
# dpkg looks the path up literally under /, so a stray "./" or an extra space
# makes every entry unverifiable.
(cd "$D" && find . -path ./DEBIAN -prune -o -type f -print0 \
  | sort -z | sed -z 's#^\./##' | xargs -0 md5sum) > "$D/DEBIAN/md5sums"

# -- maintainer scripts ----------------------------------------------------
# Written as templates with @NAME@ placeholders and expanded by sed, the same
# way scripts/install.sh fills in deploy/cv84x6-llm.service. An unquoted heredoc
# would put every maintainer-script variable one typo away from being expanded
# at build time instead of at install time; placeholders cannot.
MKSCRIPTS=$WORK/scripts
mkdir -p "$MKSCRIPTS"

write_script() {  # $1 = name; body on stdin
  sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@PKG@#$PKG#g" -e "s#@RUN_USER@#$RUN_USER#g" \
    > "$MKSCRIPTS/$1"
  chmod 0755 "$MKSCRIPTS/$1"
}

cat <<'PREINST' | write_script preinst
#!/bin/sh
# Nothing to do before unpacking: the program tree is replaced by dpkg, and the
# data directory is not in the package. The service is stopped in prerm (on an
# upgrade too -- dpkg runs the old version's prerm with "upgrade"), and stopping
# it before its files change is what keeps a running worker from executing a
# half-replaced module.
set -e
exit 0
PREINST

cat <<'PRERM' | write_script prerm
#!/bin/sh
# Stop the service before its files change (upgrade) or disappear (remove).
#
# SIGTERM only, never SIGKILL: the model worker holds the NPU heap, and killing
# it mid-load can hang the TPU until the board is rebooted. The unit sets
# KillMode=process (workers are not in systemd's line of fire) and
# TimeoutStopSec=180, so "systemctl stop" is SIGTERM-and-wait -- which is the
# whole implementation.
set -e

if [ -d /run/systemd/system ]; then
  if systemctl is-active --quiet cv84x6-llm 2>/dev/null; then
    echo "@PKG@: stopping cv84x6-llm (SIGTERM, waiting up to 180s)"
    # A failed stop must not abort the package operation: the files still have
    # to go in or out, and dpkg would otherwise leave the package half-removed.
    systemctl stop cv84x6-llm || echo "@PKG@: warning: stop did not complete cleanly"
  fi
fi
exit 0
PRERM

cat <<'POSTINST' | write_script postinst
#!/bin/sh
# Configure the service after dpkg has unpacked the files.
#
# Everything that is not "copy files here" is done by scripts/install.sh
# --in-place: Python discovery, data-directory seeding, server.env and the
# systemd unit. Reusing it is deliberate -- the tarball flow and the deb flow
# must not configure the service differently, and a second implementation in
# postinst would eventually disagree with the first.
#
# dpkg runs this on a fresh install and on an upgrade ("configure
# <old-version>"). It must be idempotent: an upgrade re-runs it against a data
# directory that already holds models, keys and agents, none of which may be
# touched.
set -e

PREFIX=@PREFIX@
PKG=@PKG@
RUN_USER=@RUN_USER@
ENV_FILE="$PREFIX/etc/server.env"
ACTION="$1"   # configure | abort-upgrade | abort-remove | abort-deconfigure

# -- abort paths: dpkg is unwinding, do not start anything ----------------
case "$ACTION" in
  abort-upgrade|abort-remove|abort-deconfigure)
    if [ -d /run/systemd/system ]; then
      systemctl daemon-reload || true
    fi
    exit 0
    ;;
esac

# -- the service user ------------------------------------------------------
# Default to the board's own login user, as every previous release did. If it is
# missing, fail loudly: silently running the agents as root would give every
# downloaded agent root on the board, which is not a decision a postinst gets to
# make for the operator.
if ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "$PKG: user '$RUN_USER' does not exist." >&2
  echo "$PKG: create it, then run 'dpkg --configure -a'." >&2
  echo "$PKG: refusing to fall back to root -- the agents would have root rights." >&2
  exit 1
fi

# -- stale program files from a previous (tarball) install ------------------
# dpkg deletes files it owns that the new version no longer ships, but a
# v0.6.8-or-earlier install was made by scripts/install.sh, not by dpkg: dpkg
# has no record of those files, so on the first deb install they would linger
# beside the new ones. A removed module that is still importable is a real
# defect, not clutter, so they are removed.
#
# Scope, deliberately narrow -- this runs as root on someone's board:
#   * only files under $PREFIX, which is this package's own tree;
#   * never anything under $PREFIX/etc (the operator's server.env lives there
#     and is not in the package);
#   * never __pycache__ (regenerated anyway, and deleting it is churn);
#   * only files dpkg does not list for this package.
#
# One `comm` over two sorted file lists, not a grep per file: the tree holds
# ~700 files and a fork each is minutes on this board.
if command -v dpkg-query >/dev/null 2>&1 && command -v comm >/dev/null 2>&1; then
  OWNED=$(mktemp) && PRESENT=$(mktemp) && STALE=$(mktemp) || {
    OWNED=/dev/null; PRESENT=/dev/null; STALE=/dev/null
  }
  if [ "$OWNED" != /dev/null ]; then
    # LC_ALL=C on both sides: `comm` requires identically collated input, and
    # the two lists come from different programs (dpkg-query and find). A
    # UTF-8 locale would sort paths differently from C and produce a diff that
    # is wrong in the one direction that matters here -- it would list live
    # files as stale.
    dpkg-query -L "$PKG" 2>/dev/null | LC_ALL=C sort -u > "$OWNED" || true
    find "$PREFIX" -mindepth 1 \
         ! -path "$PREFIX/etc" ! -path "$PREFIX/etc/*" \
         ! -name __pycache__ ! -path '*/__pycache__/*' \
         -type f -print 2>/dev/null | LC_ALL=C sort -u > "$PRESENT" || true
    # comm -13: lines only in PRESENT, i.e. present but not owned by the package.
    LC_ALL=C comm -13 "$OWNED" "$PRESENT" > "$STALE" || true
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      if rm -f "$f"; then
        echo "$PKG: removed stale file $f"
      else
        echo "$PKG: warning: could not remove stale file $f" >&2
      fi
    done < "$STALE"
    rm -f "$OWNED" "$PRESENT" "$STALE"
  fi
fi

# -- configure: the shared path with the tarball installer ----------------
# --no-start because the start is handled below, where a failure can be
# reported with the right hint instead of aborting the configure.
#
# No precondition check in front of this. install.sh warns (rather than dying)
# about a missing libsophon in --in-place mode, which is the right split: the
# unit, server.env and the data directory are still worth writing, so that
# installing the vendor runtime later only needs `systemctl start` and not
# another `dpkg --configure`. libsophon is in no apt source, so treating it as
# fatal here would leave dpkg half-configured over something apt cannot fix.
"$PREFIX/scripts/install.sh" --in-place --prefix "$PREFIX" \
    --user "$RUN_USER" --no-start

if [ ! -d /run/systemd/system ]; then
  echo "$PKG: systemd is not running; the unit is installed but not started" >&2
  exit 0
fi

systemctl daemon-reload
systemctl enable cv84x6-llm >/dev/null 2>&1 || true

# -- start and verify -----------------------------------------------------
systemctl start cv84x6-llm || true
PORT=$(sed -n 's/^CV84X6_PORT=//p' "$ENV_FILE" 2>/dev/null | tail -1)
PORT=${PORT:-8000}
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "$PKG: cv84x6-llm is running on port $PORT"
    exit 0
  fi
  i=$((i + 1))
  sleep 1
done

# The files are in place and the unit is configured, so the package IS
# installed; only the start failed. Exiting non-zero here would leave dpkg in
# "half-configured" and block every later apt operation, even though a
# `systemctl start` is all it needs. So report what to look at and finish --
# the state the operator can act from.
echo "$PKG: installed, but cv84x6-llm did not answer on port $PORT within 60s." >&2
echo "$PKG: the package is configured; the service is not running." >&2
echo "$PKG: see what it said:" >&2
echo "$PKG:   journalctl -u cv84x6-llm -n 80 --no-pager" >&2
echo "$PKG: then start it again with: systemctl start cv84x6-llm" >&2
exit 0
POSTINST

cat <<'POSTRM' | write_script postrm
#!/bin/sh
# remove / purge / upgrade / failed-upgrade / abort-install / abort-upgrade.
#
# The rule this script exists to enforce: apt remove must never delete models,
# agent installs, API keys or the operator's server.env. Only purge may remove
# program configuration, and even purge leaves the data directory alone by
# default -- tens of GB of models is not something a package manager should
# throw away because someone typed "apt purge".
set -e

PREFIX=@PREFIX@
PKG=@PKG@
ENV_FILE="$PREFIX/etc/server.env"
ACTION="$1"

reload() {
  if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
  fi
}

case "$ACTION" in
  upgrade|failed-upgrade|abort-install|abort-upgrade)
    # Files are being replaced; the new postinst re-enables and starts. Nothing
    # to disable, and the data directory is out of scope.
    reload
    exit 0
    ;;
esac

# -- remove and purge ------------------------------------------------------
# The unit file goes either way: it must not be re-enabled at the next boot, and
# systemd must forget it.
#
# The rm is NOT inside the systemd guard. install.sh writes the unit whenever it
# can, and it writes it even where systemd is not running (a container, a build
# host, a rescue boot) -- so a remove in that same environment would otherwise
# leave an orphan unit pointing at a prefix that no longer has any program in
# it. The systemctl calls are guarded because they are the part that needs a
# running manager; deleting the file is not.
if [ -d /run/systemd/system ]; then
  systemctl disable cv84x6-llm >/dev/null 2>&1 || true
  systemctl stop cv84x6-llm >/dev/null 2>&1 || true
fi
rm -f /etc/systemd/system/cv84x6-llm.service
rm -f /lib/systemd/system/cv84x6-llm.service
reload

# Where the data went: the operator may have moved it from the console, and
# server.env is the only record. Read it before deciding anything about it.
DATA_DIR=""
if [ -f "$ENV_FILE" ]; then
  DATA_DIR=$(sed -n 's/^CV84X6_DATA_DIR=//p' "$ENV_FILE" 2>/dev/null | tail -1)
fi
DATA_DIR=${DATA_DIR:-/data/cv84x6_llm_server}

if [ "$ACTION" = remove ]; then
  # A remove keeps the configuration: it records the data location, which is
  # exactly what a reinstall needs to find the models again. Everything else
  # the package owns has already been deleted by dpkg.
  echo "$PKG: removed. Kept $ENV_FILE and $DATA_DIR (models, API keys, agents)."
  echo "$PKG: reinstall to use them again, or 'apt purge $PKG' to drop configuration."
  exit 0
fi

if [ "$ACTION" = purge ]; then
  # Configuration is program configuration: it goes.
  rm -f "$ENV_FILE"
  # An empty etc/ is the package's, not the operator's.
  rmdir "$PREFIX/etc" 2>/dev/null || true
  rmdir "$PREFIX" 2>/dev/null || true

  # The data directory is NOT removed. It holds tens of GB of models, the API
  # keys every client is using, the console password hash and the installed
  # agents. A purge that deleted those would be unrecoverable and is not what
  # "remove the program" means. The marker file says whether the tree is ours,
  # so the message can be specific instead of a guess.
  echo "$PKG: purged. The program and its configuration are gone."
  if [ -d "$DATA_DIR" ]; then
    if [ -f "$DATA_DIR/.cv84x6-data" ]; then
      echo "$PKG: kept data in $DATA_DIR (models, API keys, agents, usage, logs)."
      echo "$PKG: to delete it too -- this cannot be undone -- run:"
      echo "$PKG:   sudo rm -rf $DATA_DIR"
    else
      echo "$PKG: kept $DATA_DIR (no .cv84x6-data marker, so it is not ours to delete)."
    fi
  fi
  exit 0
fi

# unknown action: say nothing, do nothing.
exit 0
POSTRM

cp "$MKSCRIPTS"/* "$D/DEBIAN/"

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$D" "$OUT/$DEB" >/dev/null
(cd "$OUT" && sha256sum "$DEB" > "$DEB.sha256")
echo "built $OUT/$DEB ($(du -h "$OUT/$DEB" | cut -f1))"
echo "  version $VERSION, prefix $PREFIX, run user $RUN_USER"
