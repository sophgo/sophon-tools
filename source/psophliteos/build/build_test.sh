#!/bin/sh
set -e

current_directory=${PWD##*/}

# 检查当前目录是否为"build"
if [ "$current_directory" != "build" ]; then
  echo "错误：该脚本必须在build目录中执行。"
  exit 1
fi

sh version.sh "V2.0.0"
mv release_version.txt ../

cp -r ../frontend/dist ../

cd ..
sh ./scrip/package.sh

cd build

mv ../sophliteos-linux_arm64.tgz ../sophliteos-linux_amd64.tgz  ../release

rm -rf ../dist tmp ../release_version.txt ../sophliteos 