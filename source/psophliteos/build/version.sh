#!/bin/bash

# DEFAULT_VERSION 是 sophliteos 版本号的唯一权威定义；release.sh / build-deb
# 从此处提取默认值（规范：版本号在工具代码中更新，仓库根 release 禁止传版本号进来）。
DEFAULT_VERSION="2.2.9"

# 生成 release_version.txt：module/commit/buildname/buildtime。
# commit/branch 全部来自 git 实时读取，不再写入硬编码残留。

# 设置Git项目路径（monorepo 仓库根，自动探测，避免硬编码相对层级）
project_path=$(git rev-parse --show-toplevel)
# 获取项目分支
branch=$(git --git-dir="$project_path/.git" rev-parse --abbrev-ref HEAD)
printf "module:sophliteos(%s)\n" "$branch" > release_version.txt
# 获取Commit
commit=$(git --git-dir="$project_path/.git" rev-parse HEAD)
printf "commit %s\n\n" "$commit" >> release_version.txt

# 格式化输出buildname
echo "buildname:$1_$(date "+%Y%m%d_%H%M%S")"  >> release_version.txt
# 格式化输出buildtime
formatted_time=$(date "+%Y%m%d_%H%M%S")
echo "buildtime:${formatted_time}" >> release_version.txt