#!/usr/bin/env bash
# dfss 阶段 1 冒烟测试
#
# 用法: bash stage1_smoke.sh <dfss-cpp 二进制路径>
#
# 逐条输出 PASS/FAIL，全部通过时退出码为 0，否则为 1。
# 依赖: 外网可达 sophgo SFTP 服务器（106.38.208.114 等，见 dfss-config.json）。
# 每个用例在独立临时目录中运行，避免互相污染。
set -uo pipefail

BIN_INPUT="${1:-}"
if [[ -z "${BIN_INPUT}" ]]; then
  echo "usage: bash $0 <path-to-dfss-cpp-binary>" >&2
  exit 2
fi
if [[ ! -f "${BIN_INPUT}" ]]; then
  echo "ERROR: binary not found: ${BIN_INPUT}" >&2
  exit 2
fi
BIN="$(readlink -f "${BIN_INPUT}")"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_PDFSS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BASE_CONFIG="${REPO_PDFSS_DIR}/src/dfss-config.json"

if [[ ! -f "${BASE_CONFIG}" ]]; then
  echo "ERROR: config not found: ${BASE_CONFIG}" >&2
  exit 2
fi

WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dfss-stage1.XXXXXX")"
trap 'rm -rf "${WORK_ROOT}"' EXIT

PASS=0
FAIL=0
FAILED_CASES=()

# run_case <名称> <函数>
run_case() {
  local name="$1"
  local fn="$2"
  local out
  echo "---- ${name}"
  if out="$("${fn}" 2>&1)"; then
    echo "${out}" | sed 's/^/     /'
    echo "PASS ${name}"
    PASS=$((PASS + 1))
  else
    local rc=$?
    echo "${out}" | sed 's/^/     /'
    echo "FAIL ${name} (rc=${rc})"
    FAIL=$((FAIL + 1))
    FAILED_CASES+=("${name}")
  fi
}

# 建一个独立工作目录，放入二进制和指定配置
prepare_dir() {
  local dir="$1"
  local config_src="${2:-${BASE_CONFIG}}"
  mkdir -p "${dir}"
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  cp "${config_src}" "${dir}/dfss-config.json"
}

# 从 /.dfss_flags 里挑一个小文件的 flag（bmodel 的 .md5 只有 102 字节）
find_small_flag() {
  local dir="$1"
  local flags_json="${dir}/.dfss_flags.dump"
  # 用 dfss 自己下载索引：--dflag 会先取 /.dfss_flags
  # 这里直接复用 python 解析远端索引不可行（无 paramiko），改用 dfss 下载的 JSON。
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url=open@sophgo.com:/.dfss_flags >/dev/null 2>&1
  popd >/dev/null || return 1
  [[ -f "${dir}/.dfss_flags" ]] || return 1
  mv "${dir}/.dfss_flags" "${flags_json}"
  python3 - "${flags_json}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
# 已知的小文件：cv84x6_llm_* 的 .md5（100 字节级）；没有就退回任意 .md5
for key in data:
    if key.endswith('.md5'):
        print(key)
        break
else:
    for key in data:
        print(key)
        break
PY
}

# ---------------------------------------------------------------- 用例
# 1. 正常 url 下载：退出码 0，大小 33554432
case_url_download() {
  local dir="${WORK_ROOT}/url"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url=open@sophgo.com:/.sophgo_speed >dl.log 2>&1
  local rc=$?
  local size=0
  [[ -f .sophgo_speed ]] && size="$(stat -c %s .sophgo_speed)"
  popd >/dev/null
  echo "exit=${rc} size=${size}"
  [[ ${rc} -eq 0 && "${size}" -eq 33554432 ]]
}

# 2. 有效 dflag：退出码 0 且文件落地
case_dflag_ok() {
  local dir="${WORK_ROOT}/dflag_ok"
  prepare_dir "${dir}"
  local flag
  flag="$(find_small_flag "${dir}")"
  [[ -n "${flag}" ]] || { echo "cannot determine a dflag"; return 1; }
  echo "dflag=${flag}"
  pushd "${dir}" >/dev/null || return 1
  local before=0 after=0
  before="$(find . -maxdepth 1 -type f ! -name 'dfss-cpp' ! -name 'dfss-config.json' ! -name '.dfss_flags*' ! -name '*.log' | wc -l)"
  ./dfss-cpp --dflag="${flag}" >dflag.log 2>&1
  local rc=$?
  after="$(find . -maxdepth 1 -type f ! -name 'dfss-cpp' ! -name 'dfss-config.json' ! -name '.dfss_flags*' ! -name '*.log' | wc -l)"
  popd >/dev/null
  echo "exit=${rc} files_before=${before} files_after=${after}"
  [[ ${rc} -eq 0 && ${after} -gt ${before} ]]
}

# 3. 不存在的 dflag：返回非 0
case_dflag_missing() {
  local dir="${WORK_ROOT}/dflag_missing"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --dflag=__no_such_flag__ >dflag.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  [[ ${rc} -ne 0 ]]
}

# 4. 黑洞地址 + 3s 超时：--dflag 与 --url 都必须非 0（回归假成功 bug）
case_blackhole() {
  local dir="${WORK_ROOT}/blackhole"
  mkdir -p "${dir}"
  cat >"${dir}/dfss-config.json" <<'JSON'
{
	"connect_timeout": 3,
	"sdk": [
		{ "id": 99, "host": "10.255.255.1", "port": 32022, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  local flag
  flag="$(find_small_flag "${WORK_ROOT}/dflag_ok")"
  [[ -n "${flag}" ]] || { echo "cannot determine a dflag"; return 1; }
  pushd "${dir}" >/dev/null || return 1
  cp "${BIN}" ./dfss-cpp && chmod +x ./dfss-cpp
  local t0 t1 dflag_rc url_rc dflag_ms url_ms
  t0="$(date +%s%3N)"
  ./dfss-cpp --dflag="${flag}" >dflag.log 2>&1
  dflag_rc=$?
  t1="$(date +%s%3N)"
  dflag_ms=$((t1 - t0))
  t0="$(date +%s%3N)"
  ./dfss-cpp --url=open@sophgo.com:/.sophgo_speed >url.log 2>&1
  url_rc=$?
  t1="$(date +%s%3N)"
  url_ms=$((t1 - t0))
  popd >/dev/null
  echo "dflag exit=${dflag_rc} elapsed=${dflag_ms}ms"
  echo "url   exit=${url_rc} elapsed=${url_ms}ms"
  # 每轮连接应接近 3s 超时（3 轮重试 ≈ 9-15s）；只要不是秒回即为真实等待
  if [[ ${dflag_rc} -eq 0 || ${url_rc} -eq 0 ]]; then
    echo "FAIL: blackhole address reported success (fake success bug)"
    return 1
  fi
  if [[ ${dflag_ms} -lt 2500 || ${url_ms} -lt 2500 ]]; then
    echo "FAIL: returned too fast, timeout not honored"
    return 1
  fi
  return 0
}

# 5. 配置 host 用主机名（端口不可达）：能正常报错退出
case_hostname() {
  local dir="${WORK_ROOT}/hostname"
  mkdir -p "${dir}"
  cat >"${dir}/dfss-config.json" <<'JSON'
{
	"connect_timeout": 3,
	"sdk": [
		{ "id": 99, "host": "localhost", "port": 39999, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  cp "${BIN}" "${dir}/dfss-cpp" && chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --dflag=x >run.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  # 必须非 0，且不能是被信号杀掉（段错误 139）
  [[ ${rc} -ne 0 && ${rc} -ne 139 ]]
}

# 6. 配置缺 connect_timeout 键：不崩溃，正常列出服务器
case_config_missing_key() {
  local dir="${WORK_ROOT}/missing_key"
  mkdir -p "${dir}"
  cat >"${dir}/dfss-config.json" <<'JSON'
{
	"sdk": [
		{ "id": 4, "host": "106.38.208.114", "port": 32022, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  cp "${BIN}" "${dir}/dfss-cpp" && chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --list >run.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  [[ ${rc} -eq 0 ]] && grep -q "106.38.208.114" "${dir}/run.log"
}

# 7. 配置 JSON 损坏：不崩溃，有 warn 日志并回退到内置列表
case_config_broken() {
  local dir="${WORK_ROOT}/broken_json"
  mkdir -p "${dir}"
  printf '{ "connect_timeout": 3, "sdk": [ {"id": 1, ' >"${dir}/dfss-config.json"
  cp "${BIN}" "${dir}/dfss-cpp" && chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --list --debug >run.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  grep -q "WARN.*config json invalid" "${dir}/run.log" || {
    echo "missing warn log"
    return 1
  }
  # 回退到内置列表：应能看到内置的 172.26.175.10
  grep -q "172.26.175.10" "${dir}/run.log" && [[ ${rc} -eq 0 ]]
}

# 8. --enable_http 已删除：非 0、输出 unknown option 与帮助、无 core
case_enable_http_removed() {
  local dir="${WORK_ROOT}/enable_http"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ulimit -c 0
  ./dfss-cpp --enable_http --url=open@sophgo.com:/.sophgo_speed >run.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  grep -qi "does not exist" "${dir}/run.log" || {
    echo "missing unknown-option message"
    return 1
  }
  grep -q "Usage:" "${dir}/run.log" || { echo "missing help output"; return 1; }
  [[ ${rc} -ne 0 && ${rc} -lt 128 ]]
}

# 9. --list 行为不变：退出码 0 且列出配置中的服务器
case_list() {
  local dir="${WORK_ROOT}/list"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --list >run.log 2>&1
  local rc=$?
  popd >/dev/null
  echo "exit=${rc}"
  [[ ${rc} -eq 0 ]] && grep -q "106.38.208.114" "${dir}/run.log"
}

# 10. --force_server 4 下载：退出码 0，大小正确
case_force_server() {
  local dir="${WORK_ROOT}/force_server"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --force_server 4 --url=open@sophgo.com:/.sophgo_speed >run.log 2>&1
  local rc=$?
  local size=0
  [[ -f .sophgo_speed ]] && size="$(stat -c %s .sophgo_speed)"
  popd >/dev/null
  echo "exit=${rc} size=${size}"
  [[ ${rc} -eq 0 && "${size}" -eq 33554432 ]]
}

# 11. 源码中不再残留 HTTP 能力
#
# 注意：
#  - 模式用字符串拼接构造，避免本脚本自身命中「源码里不该出现的字面量」
#    这条验收（否则 -- 就算实现已经删干净 -- 测试也会自己把自己判失败）。
#  - 只扫 git 跟踪的文件，跳过 dfss_pip/build/ 等构建产物。
case_no_http_traces() {
  local p1="http""lib"
  local p2="enable""_http"
  local p3="http_""get_file"
  local p4="http_""test_speed"
  local repo_root
  repo_root="$(cd "${REPO_PDFSS_DIR}/../.." && pwd)"
  local hits
  hits="$(cd "${repo_root}" && git ls-files -z -- source/pdfss_cpp \
    | xargs -0 grep -n -i -e "${p1}" -e "${p2}" -e "${p3}" -e "${p4}" 2>/dev/null \
    | grep -v '^source/pdfss_cpp/tests/stage1_smoke.sh:')"
  if [[ -n "${hits}" ]]; then
    echo "${hits}"
    return 1
  fi
  echo "no http traces in tracked files under source/pdfss_cpp"
  return 0
}

echo "== dfss stage1 smoke test =="
echo "binary: ${BIN}"
echo "config: ${BASE_CONFIG}"
echo

run_case "url download" case_url_download
run_case "dflag ok" case_dflag_ok
run_case "dflag missing" case_dflag_missing
run_case "blackhole timeout + no fake success" case_blackhole
run_case "hostname resolution" case_hostname
run_case "config missing connect_timeout" case_config_missing_key
run_case "config broken json" case_config_broken
run_case "enable_http removed" case_enable_http_removed
run_case "list" case_list
run_case "force_server 4" case_force_server
run_case "no http traces in source" case_no_http_traces

echo
echo "== summary: PASS ${PASS} / FAIL ${FAIL} =="
if [[ ${FAIL} -gt 0 ]]; then
  printf 'failed: %s\n' "${FAILED_CASES[*]}"
  exit 1
fi
exit 0
