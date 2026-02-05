#!/bin/bash

BUILD_RET=0

export CMD_7Z=$(command -v 7z)
export CMD_ZIP=$(command -v zip)

VERSION=$(grep -r "MEMTEST VERSION:" memtest_a53_gdma/start.sh | awk '{print $(NF)}' | tr -d '"')

echo "build memtest_a53_gdma ${VERSION} ..."


sudo rm -rf output

mkdir -p output
cp -r memtest_a53_gdma output/mem_aging_test_${VERSION}
cp *.md output

pushd output
	if [ -f "$CMD_7Z" ]; then
		echo "found 7z"
		$CMD_7Z a -mx9 mem_aging_test_${VERSION}.zip mem_aging_test_${VERSION}
		BUILD_RET=$?
	elif [ -f "$CMD_ZIP" ]; then
		echo "found zip"
		$CMD_ZIP -r -9 mem_aging_test_${VERSION}.zip mem_aging_test_${VERSION}
		BUILD_RET=$?
	else
		echo "Unsatisfied build dependencies"
		BUILD_RET=-1
	fi
popd

exit $BUILD_RET
