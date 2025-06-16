#!/bin/bash

if [[ "$(modinfo cdc-wdm | wc -l)" != "0" ]] && [[ "$(modinfo qmi_wwan | wc -l)" != "0" ]] && [[ "$(modinfo qmi_wwan_q | wc -l)" != "0" ]]; then
    echo "cdc-wdm, qmi_wwan, qmi_wwan_q installed"
    exit 0
fi

export KSRC=/lib/modules/$(uname -r)/build
export ARCH=arm64
export USER_EXTRA_CFLAGS="-I$(pwd)/include -I$(pwd)/platform"
if [ ! -d "$KSRC" ]; then
    /home/linaro/bsp-debs/linux-headers-install.sh
fi
if [ ! -d "$KSRC" ]; then
    echo "cannot find kernel headers $KSRC"
    exit 1
fi

pushd cdc_wdm

sudo make clean
make
sudo make install
sudo make clean

popd

modprobe cdc-wdm

pushd qmi_wwan

make clean
make
sudo make install
sudo make clean

popd
