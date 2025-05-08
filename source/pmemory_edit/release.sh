#!/bin/bash

BUILD_RET=0

MEMORY_EDIT_VERSION="2.10"
export CMD_DPKG_DEB=$(command -v dpkg-deb)

echo "build memory_edit ..."

sudo  rm -rf memory_edit*.tar.xz 2>/dev/null
sudo  rm -rf output 2>/dev/null
mkdir output
if [ -f "$CMD_DPKG_DEB" ]; then
	rm -rf *.deb
	rm -rf *.tar.xz
	pushd source
		tar -caf ../memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz memory_edit
		cp ../memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz deb/opt/sophon/memory_edit.tar.xz
		cp deb/DEBIAN/control ./control.bak
		sed -i "s/MEMORY_EDIT_VERSION/$MEMORY_EDIT_VERSION/" deb/DEBIAN/control
		echo "deb build version: v${MEMORY_EDIT_VERSION}"
		$CMD_DPKG_DEB -b deb ../memory_edit_v${MEMORY_EDIT_VERSION}.deb
		mv ./control.bak deb/DEBIAN/control
	popd
else
	echo "Unsatisfied build dependencies"
	BUILD_RET=-1
fi
cp memory_edit*.tar.xz output/
cp memory_edit*.deb output/

exit $BUILD_RET
