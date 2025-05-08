#!/bin/bash

BUILD_RET=0

export CMD_7Z=$(command -v 7z)
export CMD_ZIP=$(command -v zip)

echo "build get_info ..."


sudo rm -rf output

mkdir -p output/get_info
cp get_info.sh output/get_info/
cp get_info_log_to_png.* output/get_info/

pushd output
	if [ -f "$CMD_7Z" ]; then
		echo "found 7z"
		$CMD_7Z a -mx9 get_info.zip get_info
		BUILD_RET=$?
	elif [ -f "$CMD_ZIP" ]; then
		echo "found zip"
		$CMD_ZIP -r -9 get_info.zip get_info
		BUILD_RET=$?
	else
		echo "Unsatisfied build dependencies"
		BUILD_RET=-1
	fi
popd

exit $BUILD_RET
