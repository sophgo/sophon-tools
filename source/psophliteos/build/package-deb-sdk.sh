#!/bin/bash

set -e

TOP=$(dirname "$0")
LITEOS_DIR=$TOP/sophliteos
LITEOS_DATA=$LITEOS_DIR/data
LITEOS_CTRL=$LITEOS_DIR/DEBIAN
PRODUCT=$1

function clean(){
  rm -rf $LITEOS_DATA
}

clean

#build a run-time monkey dir
mkdir -p $LITEOS_DATA $LITEOS_DATA/sophliteos

#copy files from source
cp -r $TOP/tmp/* $LITEOS_DATA/sophliteos/
cp ../scrip/install.sh.bak $LITEOS_DATA/sophliteos/install.sh

#sed Architecture info to control file
cp $LITEOS_CTRL/control.bak $LITEOS_CTRL/control
version=$(echo $(cat $LITEOS_CTRL/control | grep Version) | cut -d ' ' -f 2)
if [[ "soc"=="$1" ]];then
  sed -i '$a Architecture: arm64' $LITEOS_CTRL/control
else
  PRODUCT=pcie
  sed -i '$a Architecture: amd64' $LITEOS_CTRL/control
fi
#build deb
dpkg-deb -b $LITEOS_DIR  $TOP/sophliteos_${PRODUCT}_${version}_sdk.deb

rm -rf $LITEOS_DATA/sophliteos