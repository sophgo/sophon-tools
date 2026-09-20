#!/bin/bash
# ============================================================
# SE写卡工具 (sewriter) — 构建
#   在 Linux 上用 Go 交叉编译出 Windows 单文件 exe, 零运行时依赖 (静态链接),
#   不需要 Windows 构建环境。
#
# 默认形态 (MYSWY 2026-09-15): **Windows + 不带内置镜像**
#   · 默认只出 Windows (32 位 + 64 位); 其余平台后续按需再加 (--linux 可出本机 CLI)
#   · 默认**不**把镜像打进 exe —— 数据源在程序里手选 (文件包/目录/整卡镜像)
#     需要"自带镜像"版时用 --image <文件包>, 或用程序内的 repack /
#     「工具 → 导出自带镜像的新程序…」
#
# 目标平台:
#   · 32 位为主产物 —— Windows 7 32/64 位都能跑
#   · 用 Go 1.20 编译: Go 1.21 起官方最低要求变成 Windows 10, 要支持 Win7 只能用
#     <= 1.20 的工具链 (依赖也相应锁在 1.20 可编译的版本, 见 go.mod)。
#     工具链由 GOTOOLCHAIN 自动拉取 (首次 ~100MB); 离线环境用 --win7-go 指定本地版本
#   · manifest 里 requireAdministrator —— 双击即弹 UAC 索要管理员权限
#
# 用法:
#   bash build.sh                      # 默认: Windows 32/64 位, 不带内置镜像
#   bash build.sh --image <文件包>      # 额外产出"自带该镜像"的 exe
#   bash build.sh --linux              # 附带 Linux CLI (本机自测 / repack 用)
#   bash build.sh --test               # 附跑 go test
#   bash build.sh --win7-go <版本>      # 覆盖 Win7 用的 Go 工具链 (默认 go1.20.14)
#   env OUT=<目录>                     # 覆盖产物目录 (默认 ./output)
#
# 产物:
#   <OUT>/sewriter.exe            32 位, 默认交付物 (Win7+ 通用)
#   <OUT>/sewriter-x64.exe        64 位
#   <OUT>/sewriter-linux          仅 --linux 时出 (本机自测用)
#   <OUT>/sewriter-embedded.exe   仅 --image 时出
# ============================================================
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-${DIR}/output}"
BUILD="${OUT}/.build"
IMG=""
EMBED=0
LINUX=0
TEST=0

# Win7 支持: Go 1.21 起最低要求 Windows 10。这里锁 1.20.x。
# 首次运行会从模块代理下载该工具链 (~100 MB, 之后走本机缓存)。
WIN7_GO="${WIN7_GO:-go1.20.14}"

while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMG="${2:-}"; shift 2 ;;
        --linux) LINUX=1; shift ;;
        --test) TEST=1; shift ;;
        --win7-go) WIN7_GO="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1 (见 --help)" >&2; exit 2 ;;
    esac
done

mkdir -p "${OUT}" "${BUILD}"
cd "${DIR}"

TOOL_VER="$(sed -n '1p' "${DIR}/VERSION" 2>/dev/null | tr -d '[:space:]')"
[ -n "${TOOL_VER}" ] || TOOL_VER="0.0.0-dev"
LDFLAGS="-s -w -X main.toolVersion=${TOOL_VER}"

echo "==> [1/4] 工具链"
echo "    本机 Go      : $(go version)"
echo "    Win7 构建 Go : ${WIN7_GO}"
echo "    工具版本     : ${TOOL_VER}"

echo "==> [2/4] Windows 资源 (manifest)"
# manifest 里 comctl32 v6 是 lxn/walk 的硬要求 (缺了启动即报 TTM_ADDTOOL failed);
# requireAdministrator 让程序启动就弹 UAC 索要管理员权限 (读写物理盘必需)。
# rsrc_windows_<arch>.syso 由 Go 按 GOARCH 自动选用。
gen_syso() { # $1=arch(amd64|386) $2=windres
    local arch="$1" wr="$2"
    local out="rsrc_windows_${arch}.syso"
    if command -v "${wr}" >/dev/null 2>&1; then
        "${wr}" -i "${DIR}/sewriter.rc" -o "${DIR}/${out}" -O coff
        echo "    ${out} ← ${wr} ($(stat -c %s "${DIR}/${out}") 字节)"
    elif [ -f "${DIR}/${out}" ]; then
        echo "    未找到 ${wr}, 沿用仓库中的 ${out}"
    else
        echo "缺少 ${out} 且无 ${wr} — 该架构会因缺 manifest 启动失败" >&2
        exit 1
    fi
}
gen_syso amd64 x86_64-w64-mingw32-windres
gen_syso 386   i686-w64-mingw32-windres

echo "==> [3/4] 编译 Windows exe (32 位 + 64 位)"
build_win() { # $1=GOARCH $2=输出名
    GOOS=windows GOARCH="$1" CGO_ENABLED=0 GOTOOLCHAIN="${WIN7_GO}" \
        go build -trimpath -ldflags="-H windowsgui ${LDFLAGS}" -o "${OUT}/$2" .
}
build_win 386   sewriter.exe
build_win amd64 sewriter-x64.exe

# 平台底线自检 (用 check_exe.py 从 PE 结构里直接验):
#   位宽对不对 / PE 子系统版本是否 <= 6.01 (Win7) / manifest 是否 requireAdministrator
echo "    平台底线 (位宽 / Win7 6.01 / 必须管理员):"
python3 "${DIR}/check_exe.py" --want arch=32 "${OUT}/sewriter.exe"
python3 "${DIR}/check_exe.py" --want arch=64 "${OUT}/sewriter-x64.exe"

if [ "${LINUX}" -eq 1 ]; then
    echo "==> [3.5/4] 编译 Linux CLI (本机自测 / repack 用)"
    GOOS=linux GOARCH=amd64 CGO_ENABLED=0 \
        go build -trimpath -ldflags="${LDFLAGS}" -o "${OUT}/sewriter-linux" .
fi

echo "==> [4/4] 内置镜像"
if [ "${EMBED}" -eq 1 ] || [ -n "${IMG}" ]; then
    [ -n "${IMG}" ] && [ -f "${IMG}" ] || {
        echo "内置镜像需要 --image <文件包|整卡镜像>: 例如" >&2
        echo "    bash build.sh --image /path/to/se7-recovery-files-<版本>.zip" >&2
        exit 1; }
    IMG="$(readlink -f "${IMG}")"
    echo "  镜像: ${IMG} ($(du -h "${IMG}" | cut -f1))"
    # repack 走的是与程序内「导出自带镜像的新程序」完全相同的代码路径;
    # 需要一个同架构的骨架当模板 —— 这里用刚编出来的 32 位 exe。
    "${OUT}/sewriter.exe" --version >/dev/null 2>&1 || true
    if [ ! -f "${OUT}/sewriter-linux" ]; then
        echo "  需要 Linux CLI 做 repack, 自动补编…"
        GOOS=linux GOARCH=amd64 CGO_ENABLED=0 \
            go build -trimpath -ldflags="${LDFLAGS}" -o "${OUT}/sewriter-linux" .
    fi
    rm -f "${OUT}/sewriter-embedded.exe"
    "${OUT}/sewriter-linux" repack --image "${IMG}" \
        --skeleton "${OUT}/sewriter.exe" --out "${OUT}/sewriter-embedded.exe"
    python3 "${DIR}/check_exe.py" --want arch=32 "${OUT}/sewriter-embedded.exe"
else
    echo "  跳过 (默认不带内置镜像; 需要时用 --image <文件包>)"
fi

if [ "${TEST}" -eq 1 ]; then
    echo "==> 附: 单元测试"; GOTOOLCHAIN="${WIN7_GO}" go test ./...
fi

echo
echo "完成 (工具 ${TOOL_VER}):"
ls -la "${OUT}"/sewriter*.exe 2>/dev/null || true
echo "  sewriter.exe ← 拷到 Windows 双击运行 (会弹 UAC 索要管理员权限)"
exit 0
