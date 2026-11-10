#!/usr/bin/env bash
# dfss 阶段 2 e2e 测试：多通道探测、断点续传、失败切换
#
# 用法: bash e2e_probe_resume.sh <dfss-cpp 二进制路径>
#
# 逐条输出 PASS/FAIL，全部通过时退出码为 0，否则为 1。
# 依赖: 外网可达 sophgo SFTP 服务器（106.38.208.114 / 172.26.166.163 等）、
#       python3（tests/cut_proxy.py）、timeout/coreutils。
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
CUT_PROXY="${SCRIPT_DIR}/cut_proxy.py"

if [[ ! -f "${BASE_CONFIG}" ]]; then
  echo "ERROR: config not found: ${BASE_CONFIG}" >&2
  exit 2
fi
if [[ ! -f "${CUT_PROXY}" ]]; then
  echo "ERROR: cut_proxy.py not found: ${CUT_PROXY}" >&2
  exit 2
fi

# 测试用的真实服务器（内网/公网镜像）
FAST_HOST="172.26.166.163"
SLOW_HOST="106.38.208.114"
SLOW_PORT=32022
REMOTE_FILE=".sophgo_speed"
REMOTE_SIZE=33554432
URL="open@sophgo.com:/${REMOTE_FILE}"

WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dfss-stage2.XXXXXX")"
PROXY_PIDS=()
cleanup() {
  for pid in "${PROXY_PIDS[@]:-}"; do
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null
  done
  rm -rf "${WORK_ROOT}"
}
trap cleanup EXIT

PASS=0
FAIL=0
FAILED_CASES=()

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

# 建独立工作目录：二进制 + 指定配置
prepare_dir() {
  local dir="$1"
  local config_src="${2:-${BASE_CONFIG}}"
  mkdir -p "${dir}"
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  cp "${config_src}" "${dir}/dfss-config.json"
}

# 单台服务器的配置
write_single_config() {
  local dir="$1"
  local host="$2"
  local port="${3:-${SLOW_PORT}}"
  local probe_timeout="${4:-5}"
  cat >"${dir}/dfss-config.json" <<JSON
{
	"connect_timeout": 60,
	"probe_timeout": ${probe_timeout},
	"sdk": [
		{ "id": 4, "host": "${host}", "port": ${port}, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
}

# 等 part 或最终文件出现（= 下载真正开始），返回耗时毫秒，超时返回 255
wait_download_start() {
  local dir="$1"
  local limit_ms="$2"
  local t0 t1
  t0="$(date +%s%3N)"
  while true; do
    t1="$(date +%s%3N)"
    if [[ -e "${dir}/${REMOTE_FILE}.dfss.part" || -e "${dir}/${REMOTE_FILE}" ]]; then
      echo $((t1 - t0))
      return 0
    fi
    if [[ $((t1 - t0)) -ge ${limit_ms} ]]; then
      echo $((t1 - t0))
      return 255
    fi
    sleep 0.05
  done
}

sha_of() {
  [[ -f "$1" ]] && sha256sum "$1" | cut -d' ' -f1 || echo ""
}

# 启动 cut_proxy，回显其监听端口
start_proxy() {
  local target_host="$1"
  local target_port="$2"
  local budget="$3"
  local mode="$4"   # all | first
  local dir="$5"
  local ready="${dir}/proxy.ready"
  rm -f "${ready}"
  python3 "${CUT_PROXY}" \
    --listen "127.0.0.1:0" \
    --target "${target_host}:${target_port}" \
    --budget "${budget}" \
    --mode "${mode}" \
    --ready-file "${ready}" \
    >"${dir}/proxy.log" 2>&1 &
  PROXY_PIDS+=("$!")
  for _ in $(seq 1 100); do
    [[ -s "${ready}" ]] && break
    sleep 0.05
  done
  if [[ ! -s "${ready}" ]]; then
    echo "ERROR: cut_proxy did not start" >&2
    cat "${dir}/proxy.log" >&2
    return 1
  fi
  head -1 "${ready}"
}

BASELINE_SHA_FILE="${WORK_ROOT}/baseline.sha"

# 后续用例读基线 sha256：run_case 在命令替换（子 shell）里跑用例函数，函数内的
# 变量赋值传不回来，因此基线用文件共享。
baseline_sha() {
  [[ -f "${BASELINE_SHA_FILE}" ]] && cat "${BASELINE_SHA_FILE}" || echo ""
}

# ---------------------------------------------------------------- 用例
# 1. 基线下载：退出码 0，sha256 记录，下载完不残留 part/meta
case_baseline() {
  local dir="${WORK_ROOT}/baseline"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url="${URL}" >dl.log 2>&1
  local rc=$?
  popd >/dev/null
  local size=0
  [[ -f "${dir}/${REMOTE_FILE}" ]] && size="$(stat -c %s "${dir}/${REMOTE_FILE}")"
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  echo "${sha}" >"${BASELINE_SHA_FILE}"
  local leftovers
  leftovers="$(find "${dir}" -maxdepth 1 -name '*.dfss.part' -o -maxdepth 1 -name '*.dfss.meta' | wc -l)"
  echo "exit=${rc} size=${size} sha256=${sha} leftovers=${leftovers}"
  [[ ${rc} -eq 0 && "${size}" -eq "${REMOTE_SIZE}" && -n "${sha}" && ${leftovers} -eq 0 ]]
}

# 2. 中断续传：timeout -s INT 3 中断，part > 0；再次运行日志出现 resume from <off>，
#    off > 0，最终 sha256 与基线一致
case_resume_after_interrupt() {
  local dir="${WORK_ROOT}/resume"
  prepare_dir "${dir}"
  # 慢速镜像（约 1.6MiB/s）：32MiB 需 20s，3s 时必定仍在下载中
  write_single_config "${dir}" "${SLOW_HOST}"
  pushd "${dir}" >/dev/null || return 1
  timeout -s INT 3 ./dfss-cpp --url="${URL}" >dl1.log 2>&1
  local rc1=$?
  local part="${dir}/${REMOTE_FILE}.dfss.part"
  local part_size=0
  [[ -f "${part}" ]] && part_size="$(stat -c %s "${part}")"
  echo "first run exit=${rc1} part=${part_size}"
  ./dfss-cpp --url="${URL}" >dl2.log 2>&1
  local rc2=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local off
  off="$(grep -o 'resume from [0-9]*' "${dir}/dl2.log" | head -1 | awk '{print $3}')"
  local leftovers
  leftovers="$(find "${dir}" -maxdepth 1 -name '*.dfss.part' -o -maxdepth 1 -name '*.dfss.meta' | wc -l)"
  echo "second run exit=${rc2} resume_off=${off:-<none>} sha256=${sha} leftovers=${leftovers}"
  [[ ${part_size} -gt 0 ]] || { echo "FAIL: part file empty after interrupt"; return 1; }
  [[ ${rc2} -eq 0 ]] || { echo "FAIL: resumed download exit ${rc2}"; return 1; }
  [[ -n "${off}" && "${off}" -gt 0 ]] || { echo "FAIL: no 'resume from <off>' with off>0"; return 1; }
  [[ "${sha}" == "$(baseline_sha)" ]] || { echo "FAIL: sha256 mismatch"; return 1; }
  [[ ${leftovers} -eq 0 ]] || { echo "FAIL: part/meta left behind"; return 1; }
  return 0
}

# 3. 元数据不一致时重下：篡改 meta 的 size 后从 0 开始，sha256 一致
case_meta_mismatch() {
  local dir="${WORK_ROOT}/meta"
  prepare_dir "${dir}"
  write_single_config "${dir}" "${SLOW_HOST}"
  pushd "${dir}" >/dev/null || return 1
  timeout -s INT 3 ./dfss-cpp --url="${URL}" >dl1.log 2>&1
  popd >/dev/null
  local part="${dir}/${REMOTE_FILE}.dfss.part"
  local meta="${dir}/${REMOTE_FILE}.dfss.meta"
  [[ -f "${part}" && -f "${meta}" ]] || {
    echo "FAIL: interrupt did not leave part+meta"
    return 1
  }
  python3 - "${meta}" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["size"] = int(d["size"]) + 1        # 与远端 size 不一致
json.dump(d, open(p, "w"))
PY
  echo "tampered meta: $(cat "${meta}")"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url="${URL}" >dl2.log 2>&1
  local rc=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local resumed
  resumed="$(grep -c 'resume from' "${dir}/dl2.log")"
  local from_zero
  from_zero="$(grep -c 'download from 0/' "${dir}/dl2.log")"
  echo "exit=${rc} from_zero_log=${from_zero} resume_log=${resumed} sha256=${sha}"
  [[ ${rc} -eq 0 ]] || return 1
  [[ ${from_zero} -ge 1 && ${resumed} -eq 0 ]] || {
    echo "FAIL: expected restart from 0, got resume"
    return 1
  }
  [[ "${sha}" == "$(baseline_sha)" ]]
}

# 4. --no_resume：part 存在也从 0 开始，sha256 一致
case_no_resume() {
  local dir="${WORK_ROOT}/no_resume"
  prepare_dir "${dir}"
  write_single_config "${dir}" "${SLOW_HOST}"
  pushd "${dir}" >/dev/null || return 1
  timeout -s INT 3 ./dfss-cpp --url="${URL}" >dl1.log 2>&1
  popd >/dev/null
  local part="${dir}/${REMOTE_FILE}.dfss.part"
  local part_size=0
  [[ -f "${part}" ]] && part_size="$(stat -c %s "${part}")"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --no_resume --url="${URL}" >dl2.log 2>&1
  local rc=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local resumed
  resumed="$(grep -c 'resume from' "${dir}/dl2.log")"
  local from_zero
  from_zero="$(grep -c 'download from 0/' "${dir}/dl2.log")"
  echo "part_before=${part_size} exit=${rc} from_zero_log=${from_zero} resume_log=${resumed} sha256=${sha}"
  [[ ${part_size} -gt 0 ]] || { echo "FAIL: no part to ignore"; return 1; }
  [[ ${rc} -eq 0 && ${from_zero} -ge 1 && ${resumed} -eq 0 ]] || {
    echo "FAIL: --no_resume did not restart from 0"
    return 1
  }
  [[ "${sha}" == "$(baseline_sha)" ]]
}

# 5. 跨服务器切换续传：cut_proxy（本机端口 -> 快速镜像，累计 10MiB 后断开）
#    排在候选 #1；下载中途被断，切到真实服务器并从 off > 0 续传。
#
# 为什么上游用 172.26.166.163 而不是 106.38.208.114：测速上限是 2s/8MiB，
# 代理和它上游的镜像带宽接近，用慢速镜像会让两者测速值在同一量级，排名
# 不确定（测试会随机变成「首选直接成功、没有切换」）。用快速镜像时代理
# 能在 2s 内读满 8MiB 并达到提前结束阈值，稳定排在 #1。
case_cross_server_resume() {
  local dir="${WORK_ROOT}/cross"
  mkdir -p "${dir}"
  local port
  port="$(start_proxy "${FAST_HOST}" 32022 10485760 all "${dir}")" || return 1
  cat >"${dir}/dfss-config.json" <<JSON
{
	"connect_timeout": 60,
	"probe_timeout": 5,
	"sdk": [
		{ "id": 90, "host": "127.0.0.1", "port": ${port}, "user": "open", "pass": "open", "only_open": false },
		{ "id": 4, "host": "${SLOW_HOST}", "port": ${SLOW_PORT}, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url="${URL}" >dl.log 2>&1
  local rc=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local switched
  switched="$(grep -c "download from 127.0.0.1:${port} failed, switching to next server" "${dir}/dl.log")"
  local off
  off="$(grep -o 'resume from [0-9]*' "${dir}/dl.log" | head -1 | awk '{print $3}')"
  local first_rank
  first_rank="$(grep -m1 'candidate #1:' "${dir}/dl.log")"
  echo "proxy_port=${port} exit=${rc} switched=${switched} resume_off=${off:-<none>} sha256=${sha}"
  echo "candidate #1: ${first_rank}"
  [[ ${rc} -eq 0 ]] || { echo "FAIL: download exit ${rc}"; return 1; }
  [[ ${switched} -ge 1 ]] || { echo "FAIL: no switch to the next server"; return 1; }
  [[ -n "${off}" && "${off}" -gt 0 ]] || { echo "FAIL: resume offset not > 0"; return 1; }
  [[ "${sha}" == "$(baseline_sha)" ]] || { echo "FAIL: sha256 mismatch"; return 1; }
  return 0
}

# 6. 探测时间有上界：3 个黑洞 IP + 1 台真实服务器，probe_timeout=3。
#    从启动到开始下载 <= 3s（探测）+ 2s（测速上限）+ 2s（余量）= 7s，且下载成功。
case_probe_time_bound() {
  local dir="${WORK_ROOT}/timebound"
  mkdir -p "${dir}"
  cat >"${dir}/dfss-config.json" <<JSON
{
	"connect_timeout": 60,
	"probe_timeout": 3,
	"sdk": [
		{ "id": 91, "host": "10.255.255.1", "port": 32022, "user": "open", "pass": "open", "only_open": false },
		{ "id": 92, "host": "10.255.255.2", "port": 32022, "user": "open", "pass": "open", "only_open": false },
		{ "id": 93, "host": "10.255.255.3", "port": 32022, "user": "open", "pass": "open", "only_open": false },
		{ "id": 3, "host": "${FAST_HOST}", "port": 32022, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url="${URL}" >dl.log 2>&1 &
  local pid=$!
  local start_ms
  start_ms="$(wait_download_start "${dir}" 20000)"
  local started=$?
  wait ${pid}
  local rc=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local budget_ms=$((3 * 1000 + 2000 + 2000))
  echo "start_to_download=${start_ms}ms budget=${budget_ms}ms exit=${rc} sha256=${sha}"
  grep -E 'unreachable|candidate #1:' "${dir}/dl.log" | sed 's/^/     /'
  [[ ${started} -eq 0 ]] || { echo "FAIL: download never started"; return 1; }
  [[ ${start_ms} -le ${budget_ms} ]] || { echo "FAIL: probe exceeded the time bound"; return 1; }
  [[ ${rc} -eq 0 ]] || { echo "FAIL: download exit ${rc}"; return 1; }
  [[ "${sha}" == "$(baseline_sha)" ]]
}

# 7. 全部不可达：只配置黑洞 IP，退出码非 0，总耗时 <= 3 轮 x (probe_timeout + 2s)
case_all_unreachable() {
  local dir="${WORK_ROOT}/unreachable"
  mkdir -p "${dir}"
  cat >"${dir}/dfss-config.json" <<'JSON'
{
	"connect_timeout": 60,
	"probe_timeout": 3,
	"sdk": [
		{ "id": 91, "host": "10.255.255.1", "port": 32022, "user": "open", "pass": "open", "only_open": false },
		{ "id": 92, "host": "10.255.255.2", "port": 32022, "user": "open", "pass": "open", "only_open": false }
	],
	"hdk": []
}
JSON
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  local t0 t1
  t0="$(date +%s%3N)"
  ./dfss-cpp --url="${URL}" >dl.log 2>&1
  local rc=$?
  t1="$(date +%s%3N)"
  popd >/dev/null
  local elapsed=$((t1 - t0))
  local budget_ms=$((3 * (3000 + 2000)))
  local rounds
  rounds="$(grep -c 'no candidate server available in round' "${dir}/dl.log")"
  echo "exit=${rc} elapsed=${elapsed}ms budget=${budget_ms}ms rounds_logged=${rounds}"
  [[ ${rc} -ne 0 ]] || { echo "FAIL: all-unreachable reported success"; return 1; }
  [[ ${elapsed} -le ${budget_ms} ]] || { echo "FAIL: exceeded 3 rounds x (probe_timeout+2s)"; return 1; }
  return 0
}

# 8. 测速文件读取失败不淘汰服务器：cut_proxy 只切断第一条连接（测速），
#    之后的连接（下载）正常转发，最终仍能下载成功。
case_speed_failure_keeps_server() {
  local dir="${WORK_ROOT}/speedfail"
  mkdir -p "${dir}"
  local port
  port="$(start_proxy "${FAST_HOST}" 32022 1048576 first "${dir}")" || return 1
  write_single_config "${dir}" "127.0.0.1" "${port}"
  cp "${BIN}" "${dir}/dfss-cpp"
  chmod +x "${dir}/dfss-cpp"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --url="${URL}" >dl.log 2>&1
  local rc=$?
  popd >/dev/null
  local sha
  sha="$(sha_of "${dir}/${REMOTE_FILE}")"
  local speed_failed
  speed_failed="$(grep -cE 'speed test on .* failed|speed test on .* read error' "${dir}/dl.log")"
  local kept
  kept="$(grep -c 'server kept as candidate' "${dir}/dl.log")"
  echo "exit=${rc} speed_failed=${speed_failed} kept_as_candidate=${kept} sha256=${sha}"
  [[ ${speed_failed} -ge 1 && ${kept} -ge 1 ]] || {
    echo "FAIL: speed test did not fail in the expected way"
    return 1
  }
  [[ ${rc} -eq 0 ]] || { echo "FAIL: server was dropped, download exit ${rc}"; return 1; }
  [[ "${sha}" == "$(baseline_sha)" ]]
}

# 9. --probe：打印表头与排名行，退出码 0
case_probe_table() {
  local dir="${WORK_ROOT}/probe"
  prepare_dir "${dir}"
  pushd "${dir}" >/dev/null || return 1
  ./dfss-cpp --probe >probe.log 2>&1
  local rc=$?
  popd >/dev/null
  grep -E 'rank id|^[0-9-] ' "${dir}/probe.log" | sed 's/^/     /'
  [[ ${rc} -eq 0 ]] || { echo "FAIL: --probe exit ${rc}"; return 1; }
  grep -q '\[SDK\] server probe result' "${dir}/probe.log" || {
    echo "FAIL: missing SDK report header"
    return 1
  }
  grep -q '\[HDK\] server probe result' "${dir}/probe.log" || {
    echo "FAIL: missing HDK report header"
    return 1
  }
  grep -qE '^1 +[0-9]+ +[0-9.]+:[0-9]+ +ok ' "${dir}/probe.log" || {
    echo "FAIL: no ranked ok row"
    return 1
  }
  return 0
}

# 10. 并发冒烟：8 个进程在独立目录并发下载，全部退出码 0 且 sha256 一致
case_concurrent_smoke() {
  local root="${WORK_ROOT}/concurrent"
  mkdir -p "${root}"
  local pids=()
  local i
  for i in $(seq 1 8); do
    local dir="${root}/p${i}"
    prepare_dir "${dir}"
    # 每个进程只保留一台服务器，避免探测阶段的并发压力集中在同一台机器上
    write_single_config "${dir}" "${FAST_HOST}"
    (
      cd "${dir}" && ./dfss-cpp --url="${URL}" >dl.log 2>&1
      echo $? >"${dir}/exit.rc"
    ) &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do wait "${pid}"; done
  local bad=0
  local sha_list=""
  for i in $(seq 1 8); do
    local dir="${root}/p${i}"
    local rc="?"
    [[ -f "${dir}/exit.rc" ]] && rc="$(cat "${dir}/exit.rc")"
    local sha
    sha="$(sha_of "${dir}/${REMOTE_FILE}")"
    echo "p${i}: exit=${rc} sha256=${sha}"
    [[ "${rc}" == "0" ]] || bad=$((bad + 1))
    [[ "${sha}" == "$(baseline_sha)" ]] || bad=$((bad + 1))
    sha_list="${sha_list}${sha}\n"
  done
  [[ ${bad} -eq 0 ]] || { echo "FAIL: ${bad} process(es) failed"; return 1; }
  return 0
}

echo "== dfss stage2 e2e (probe / resume / failover) =="
echo "binary: ${BIN}"
echo "config: ${BASE_CONFIG}"
echo "work:   ${WORK_ROOT}"
echo

run_case "baseline download" case_baseline
if [[ -z "$(baseline_sha)" ]]; then
  echo "ERROR: baseline sha256 missing, aborting (network/server problem?)" >&2
  echo "== summary: PASS ${PASS} / FAIL $((FAIL + 1)) =="
  exit 1
fi
run_case "resume after interrupt" case_resume_after_interrupt
run_case "meta mismatch restarts" case_meta_mismatch
run_case "--no_resume restarts" case_no_resume
run_case "cross-server resume via cut_proxy" case_cross_server_resume
run_case "probe time bound (3 blackholes)" case_probe_time_bound
run_case "all servers unreachable" case_all_unreachable
run_case "speed test failure keeps server" case_speed_failure_keeps_server
run_case "--probe table" case_probe_table
run_case "8-process concurrency smoke" case_concurrent_smoke

echo
echo "== summary: PASS ${PASS} / FAIL ${FAIL} =="
if [[ ${FAIL} -gt 0 ]]; then
  printf 'failed: %s\n' "${FAILED_CASES[*]}"
  exit 1
fi
exit 0
