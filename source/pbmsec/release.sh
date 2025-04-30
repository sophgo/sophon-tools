#!/bin/bash

BUILD_RET=0

echo "build bmsec ..."

BMSEC_PACKAGE_VERSION="1.6.2"

export CMD_PANDOC=$(command -v pandoc)
export CMD_DPKG_DEB=$(command -v dpkg-deb)

rm -rf bmsec*.deb 2>/dev/null
rm -rf *.deb* 2>/dev/null
rm -rf output 2>/dev/null
rm -rf ./*.html
mkdir output

if [ -f "$CMD_PANDOC" ] && [ -f "$CMD_DPKG_DEB" ]; then
	echo "found $CMD_PANDOC and $CMD_DPKG_DEB"
	pushd doc
		for file in *.md; do
			if [ -f "$file" ]; then
				echo "Converting $file to HTML ${file%.md}.html ..."
				$CMD_PANDOC "$file" --self-contained -c bootstrap.min.css --metadata title=${file%.md} -o "${file%.md}.html"
			fi
		done
		mkdir -p deb/opt/sophon/bmsec/doc/
		rm -rf deb/opt/sophon/bmsec/doc/*
		cp *.html deb/opt/sophon/bmsec/doc/
		rm -rf bmsec.1
		echo "Converting man Doc file ..."
		cat *.md | $CMD_PANDOC -s --self-contained -c bootstrap.min.css -t man -o bmsec.1
		mkdir -p deb/usr/share/man/man1/
		rm -rf deb/usr/share/man/man1/*
		cp bmsec.1 deb/usr/share/man/man1/
	popd
	rm -rf deb/opt/sophon/bmsec/configs/subNANInfo
	BMSEC_VERSION=${BMSEC_PACKAGE_VERSION}
	cp deb/DEBIAN/control ./control.bak
	sed -i "s/BMSEC_VERSION/$BMSEC_VERSION/" deb/DEBIAN/control
	echo "deb build version: ${BMSEC_VERSION}"
	$CMD_DPKG_DEB -b deb bmsec_v$BMSEC_VERSION.deb
	mv ./control.bak deb/DEBIAN/control
	if [ -f "bmsec_v$BMSEC_VERSION.deb" ]; then
		BUILD_RET=0
	else
		BUILD_RET=-1
	fi
else
	echo "Unsatisfied build dependencies"
	BUILD_RET=-1
fi
cp *.deb output/

exit $BUILD_RET
