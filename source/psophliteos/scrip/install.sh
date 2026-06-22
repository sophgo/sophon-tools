#!/bin/bash

set -e

case $(arch) in
  "x86_64")
    dir="linux_amd64"
  ;;
  "aarch64")
    dir="linux_arm64"
  ;;
  *)
  echo "unsupported arch"
  exit
  ;;
esac
if [[ -d "release/${dir}" ]]; then
  dir="release/${dir}/"
else
  dir=""
fi

if [[ -f /etc/systemd/system/sophliteos.service ]]; then
  systemctl stop sophliteos.service || true
  systemctl disable sophliteos.service || true
fi
mkdir -p /etc/sophliteos/config /var/log/sophliteos /var/lib/sophliteos/db /data/sophliteos
rm -rf /var/lib/sophliteos/dist

cp -r dist /var/lib/sophliteos/
cp "${dir}"sophliteos /bin
cp config/sophliteos.yaml /etc/sophliteos/config
# 仅在目标 DB 不存在时拷入模板，避免覆盖已有用户/告警数据
[ -f /var/lib/sophliteos/db/sophliteos.db ] || cp database/sophliteos.db /var/lib/sophliteos/db/sophliteos.db
cp sophliteos.service /etc/systemd/system/
cp release_version.txt /var/lib/sophliteos

systemctl daemon-reload
systemctl enable sophliteos.service
systemctl start sophliteos.service