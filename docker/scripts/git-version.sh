#!/usr/bin/env bash
# 计算编译期版本信息，供容器构建通过 env 传入（MYS-2414）
#
# 背景: 统一构建容器内常常拿不到 .git
#   - docker/scripts/build-dfss-pip.sh 只挂 source/pdfss_cpp 子目录，容器内无 .git；
#   - 即便挂了主 git 目录，worktree 的 gitdir 引用也可能解析失败。
# 而 pdfss_cpp/src/Makefile 用 $(shell git describe --tags) 取版本，失败时静默成空串，
# 编出的二进制打印 "version: (-)[]"。
#
# 因此在宿主机（git 一定可用）算好，经 docker run -e 传进容器。
#
# 用法:
#   source docker/scripts/git-version.sh
#   read -r HASH DATE < <(git_version_info <repo-root>)
#
# 输出: 一行 "<hash> <date>"；两者都拿不到时输出单个空格，由调用方决定是否致命。
#
# 注意: 调用方普遍开着 set -euo pipefail，本函数内部不用任何管道
# （pipefail 下 `git ... | head` 会取到 git 的非零退出码，直接把调用方干掉），
# 每条 git 命令都显式兜底。
git_version_info() {
  local repo="${1:?repo root required}"
  local desc="" sha="" date="" combined=""

  # 轻量标签/无标签仓库都要能出值：describe 失败退到 --always
  desc="$(git -C "$repo" describe --tags 2>/dev/null)" || desc=""
  if [[ -z "$desc" ]]; then
    desc="$(git -C "$repo" describe --tags --always 2>/dev/null)" || desc=""
  fi
  sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || sha=""
  date="$(git -C "$repo" show -s --format=%ci HEAD 2>/dev/null)" || date=""

  if [[ -n "$desc" && -n "$sha" ]]; then
    combined="${desc}-${sha}"
  else
    combined="${sha}"
  fi

  printf '%s %s\n' "$combined" "$date"
}
