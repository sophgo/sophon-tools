#!/bin/bash

VERSION=1.2.5
rm -rf output
mkdir -p output

cat <<'EOF' > output/autotelecomm_install_${VERSION}.sh
#!/bin/bash

if [ "$(id -u)" != "0" ]; then
    echo "need root run"
    exit 1
fi

TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

offset=$(grep -an "__ARCHIVE_BELOW__" "$0" | tail -n1 | cut -d: -f1)
((offset++))
tail -n +$offset "$0" > "$TMP_DIR/packages.tgz"
tar -xavf "$TMP_DIR/packages.tgz" -C "$TMP_DIR" || exit

systemctl daemon-reload
systemctl stop autotelecomm
systemctl stop ec20

echo "[install rootfs] start ..."
pushd "${TMP_DIR}/rootfs" || exit
cp -r ./* / || exit
popd || exit
sync

echo "[install kernel mod] start ..."
pushd "${TMP_DIR}/kernel" || exit
bash install.sh || exit
popd || exit
sync

if [[ "$(pip list | grep pyserial | wc -l)" == "0" ]]; then
    echo "not find pyserial by python, need install ..."
    python3 -m pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple pyserial
fi

systemctl daemon-reload
systemctl stop lteModemManager
systemctl disable lteModemManager
sync

echo "[install] success, please restart this device"
exit 0
__ARCHIVE_BELOW__
EOF

tar -caf output/packages.tgz rootfs kernel

cat output/packages.tgz >> output/autotelecomm_install_${VERSION}.sh

chmod +x output/autotelecomm_install_${VERSION}.sh
