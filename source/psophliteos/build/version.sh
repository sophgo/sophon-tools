#!/bin/bash

project_path="."



printf  "module:sophliteos-build(master)\n" > release_version.txt
printf  "commit b74ff743953a8b17622ba382e9cedfd659d63e10\n\n" >> release_version.txt

# 设置Git项目路径（monorepo 仓库根，自动探测，避免硬编码相对层级）
project_path=$(git rev-parse --show-toplevel)
# 获取项目分支
branch=$(git --git-dir="$project_path/.git" rev-parse --abbrev-ref HEAD)
printf "module:sophliteos(%s)\n" "$branch" >> release_version.txt
# 获取Commit
commit=$(git --git-dir="$project_path/.git" rev-parse HEAD)
printf "commit %s\n\n" "$commit" >> release_version.txt

# 格式化输出buildname
echo "buildname:$1_$(date "+%Y%m%d_%H%M%S")"  >> release_version.txt
# 格式化输出buildtime
formatted_time=$(date "+%Y%m%d_%H%M%S")
echo "buildtime:${formatted_time}" >> release_version.txt