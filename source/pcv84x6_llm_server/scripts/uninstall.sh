#!/usr/bin/env bash
# Remove the service. Keeps the data directory unless --purge is given.
#
#   sudo ./scripts/uninstall.sh [--prefix /opt/sophgo/cv84x6_llm_server]
#        [--data-dir /data/cv84x6_llm_server] [--purge]
#
# --purge only deletes a directory carrying the .cv84x6-data marker this
# service writes, so a mistyped --data-dir cannot take an unrelated tree with it.
set -euo pipefail
PREFIX=/opt/sophgo/cv84x6_llm_server
DATA_DIR=""
PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX=$2; shift 2 ;;
    --data-dir) DATA_DIR=$2; shift 2 ;;
    --purge) PURGE=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

ENV_FILE=$PREFIX/etc/server.env
# Not passed on the command line: ask the configuration file the service itself
# reads, so an install whose data was moved from the console points at the
# right place. Falls back to the default only when there is no file at all.
if [ -z "$DATA_DIR" ] && [ -f "$ENV_FILE" ]; then
  DATA_DIR=$(sed -n 's/^CV84X6_DATA_DIR=//p' "$ENV_FILE" | tail -1)
fi
DATA_DIR=${DATA_DIR:-/data/cv84x6_llm_server}

systemctl disable --now cv84x6-llm 2>/dev/null || true
rm -f /etc/systemd/system/cv84x6-llm.service
systemctl daemon-reload

if [ "$PURGE" = 1 ]; then
  if [ -f "$DATA_DIR/.cv84x6-data" ]; then
    rm -rf "$DATA_DIR"
    echo "removed $DATA_DIR (models, keys, usage, logs)"
  else
    echo "kept $DATA_DIR: no .cv84x6-data marker, so it is not this service's data" >&2
    echo "remove it by hand if you are sure it is safe" >&2
  fi
  rm -rf "$PREFIX"
  echo "removed $PREFIX"
else
  # The program tree, but not the configuration: it records where the data moved
  # to, which is exactly what a reinstall needs to find it again.
  find "$PREFIX" -mindepth 1 -maxdepth 1 ! -name etc -exec rm -rf {} +
  echo "removed the service from $PREFIX; kept $ENV_FILE and $DATA_DIR"
fi
