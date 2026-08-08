#!/usr/bin/env bash
# sophon-tools-build 镜像自检（对照 M1 盘点清单逐项验证工具链）
#
# 用法:
#   bash docker/verify.sh                 # 默认镜像 sophon-tools-build:latest
#   bash docker/verify.sh --image <name>  # 指定镜像
#   bash docker/verify.sh --cross         # 额外跑交叉编译实测(arm64 musl 静态 + windows)
#
# 退出码: 0=全部通过, 1=存在失败项
set -u

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
IMAGE="${IMAGE:-sophon-tools-build:latest}"
DO_CROSS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --cross) DO_CROSS=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# 在镜像内执行命令的封装
run() { docker run --rm -i "${IMAGE}" bash -c "$*"; }

FAIL=0
CHECK() {
  local name="$1" cmd="$2"
  if run "${cmd}" >/dev/null 2>&1; then
    echo "  [PASS] ${name}"
  else
    echo "  [FAIL] ${name}  ($cmd)"
    FAIL=1
  fi
}

VERSION() {
  local name="$1" cmd="$2"
  local out
  out="$(run "${cmd}" 2>/dev/null)"
  echo "  [VER ] ${name}: ${out}"
}

echo "== sophon-tools-build 镜像自检 ($IMAGE) =="

echo "--- 基础工具链 ---"
VERSION "gcc (host)"            "gcc --version | head -1"
VERSION "g++ (host)"            "g++ --version | head -1"
VERSION "make"                  "make --version | head -1"
VERSION "cmake"                 "cmake --version | head -1"
VERSION "pkg-config"            "pkg-config --version"
CHECK  "git"                    "git --version"

echo "--- Go 工具链 (pbmssm / psophliteos) ---"
VERSION "go"                    "go version"
CHECK  "go 交叉编译 env"        "go env GOOS GOARCH | grep -q linux"
CHECK  "CGO 可用"               "go env CGO_ENABLED"
CHECK  "GOOS=linux GOARCH=arm64 编译" "cd /tmp && printf 'package main\nimport \"fmt\"\nfunc main(){fmt.Println(\"ok\")}\n' > m.go && GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o /dev/null m.go"

echo "--- Rust 工具链 (pbm_set_ip) ---"
VERSION "rustc"                 "rustc --version"
VERSION "cargo"                 "cargo --version"
CHECK  "aarch64 musl target"    "rustup target list --installed | grep -q aarch64-unknown-linux-musl"
CHECK  "aarch64 gnu target"     "rustup target list --installed | grep -q aarch64-unknown-linux-gnu"
CHECK  "x86_64 musl target"     "rustup target list --installed | grep -q x86_64-unknown-linux-musl"
CHECK  "cargo 链接器配置"       "grep -q aarch64-linux-musl-gcc \${CARGO_HOME:-/opt/cargo}/config.toml"

echo "--- Node.js / 前端 (psophliteos) ---"
VERSION "node"                  "node --version"
VERSION "pnpm"                  "pnpm --version"
VERSION "yarn"                  "yarn --version"

echo "--- musl 交叉工具链 (静态链接) ---"
VERSION "aarch64-linux-musl-gcc" "aarch64-linux-musl-gcc --version | head -1"
VERSION "x86_64-linux-musl-gcc"  "x86_64-linux-musl-gcc --version | head -1"

echo "--- glibc 交叉工具链 (pdfss_cpp 各架构) ---"
VERSION "aarch64-linux-gnu-gcc"   "aarch64-linux-gnu-gcc --version | head -1"
VERSION "arm-linux-gnueabi-gcc"   "arm-linux-gnueabi-gcc --version | head -1"
VERSION "riscv64-linux-gnu-gcc"   "riscv64-linux-gnu-gcc --version | head -1"
VERSION "x86_64-w64-mingw32-gcc"  "x86_64-w64-mingw32-gcc --version | head -1"
VERSION "i686-w64-mingw32-gcc"    "i686-w64-mingw32-gcc --version | head -1"

echo "--- dfss 私有工具链 (sw_64 / loongarch64) ---"
if run "dfss-check" | grep -q "已就绪"; then
  echo "  [PASS] dfss 私有工具链已就绪"
  VERSION "sw_64 gcc"           "/usr/sw/swgcc830_cross_tools/usr/bin/sw_64-sunway-linux-gnu-gcc --version | head -1"
  VERSION "loongarch64 gcc"     "/env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin/loongarch64-linux-gnu-gcc --version | head -1"
else
  echo "  [SKIP] dfss 私有工具链未内置(基础镜像; 用 --with-dfss-toolchains 重建)"
fi

echo "--- 打包 / 文档 / 验证工具 ---"
CHECK  "dpkg-deb"               "dpkg-deb --version"
CHECK  "dpkg-dev"               "dpkg-buildpackage --version | head -1"
CHECK  "fakeroot"               "fakeroot --version"
CHECK  "7z"                     "7z | head -1"
CHECK  "zip"                    "zip -v | head -1"
CHECK  "upx"                    "upx --version | head -1"
CHECK  "patchelf"               "patchelf --version"
CHECK  "pandoc"                 "pandoc --version | head -1"
CHECK  "sudo"                   "sudo --version | head -1"
CHECK  "qemu-aarch64-static"    "qemu-aarch64-static --version | head -1"
CHECK  "qemu-loongarch64"       "qemu-loongarch64 --version | head -1"

# ---- 交叉编译实测 ----
if [[ "${DO_CROSS}" = "1" ]]; then
  echo "--- 交叉编译实测 ---"
  # C: aarch64 musl 静态
  # 用 readelf 判 INTERP 而非 file: ubuntu:20.04 的 file 5.38 无法识别 static-pie
  # (-static 默认 rcrt1.o 产出 ET_DYN static-pie), 会误报为 dynamically linked。
  if run 'printf "int main(){return 0;}\n" > /tmp/c.c && aarch64-linux-musl-gcc -static /tmp/c.c -o /tmp/c.out && ! readelf -l /tmp/c.out | grep -q INTERP'; then
    echo "  [PASS] C aarch64 musl 静态编译"
  else
    echo "  [FAIL] C aarch64 musl 静态编译"
    FAIL=1
  fi
  # Rust: aarch64 musl 静态
  if run 'cd /tmp && cargo new rusttest --bin >/dev/null 2>&1 && cd rusttest && echo "fn main(){println!(\"ok\")}" > src/main.rs && cargo build --release --target aarch64-unknown-linux-musl >/dev/null 2>&1 && file target/aarch64-unknown-linux-musl/release/rusttest | grep -qE "statically linked|static-pie linked"'; then
    echo "  [PASS] Rust aarch64 musl 静态编译"
  else
    echo "  [FAIL] Rust aarch64 musl 静态编译"
    FAIL=1
  fi
  # Windows: mingw64 交叉
  if run 'printf "int main(){return 0;}\n" > /tmp/w.c && x86_64-w64-mingw32-gcc -static /tmp/w.c -o /tmp/w.exe && file /tmp/w.exe | grep -qE "PE32\+.*x86-64"'; then
    echo "  [PASS] Windows x86_64 (mingw64) 交叉编译"
  else
    echo "  [FAIL] Windows x86_64 (mingw64) 交叉编译"
    FAIL=1
  fi
  # Windows: mingw i686 交叉
  if run 'printf "int main(){return 0;}\n" > /tmp/w32.c && i686-w64-mingw32-gcc -static /tmp/w32.c -o /tmp/w32.exe && file /tmp/w32.exe | grep -q "PE32"'; then
    echo "  [PASS] Windows i686 (mingw) 交叉编译"
  else
    echo "  [FAIL] Windows i686 (mingw) 交叉编译"
    FAIL=1
  fi
  # dfss sw_64 交叉(若有)
  if run '[ -x /usr/sw/swgcc830_cross_tools/usr/bin/sw_64-sunway-linux-gnu-gcc ]'; then
    if run 'printf "int main(){return 0;}\n" > /tmp/s.c && /usr/sw/swgcc830_cross_tools/usr/bin/sw_64-sunway-linux-gnu-gcc -static /tmp/s.c -o /tmp/s.out 2>/dev/null && file /tmp/s.out | grep -q "statically linked"'; then
      echo "  [PASS] sw_64 静态交叉编译"
    else
      echo "  [FAIL] sw_64 静态交叉编译"
      FAIL=1
    fi
    if run 'printf "int main(){return 0;}\n" > /tmp/l.c && /env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin/loongarch64-linux-gnu-gcc -static /tmp/l.c -o /tmp/l.out 2>/dev/null && file /tmp/l.out | grep -q "statically linked"'; then
      echo "  [PASS] loongarch64 静态交叉编译"
    else
      echo "  [FAIL] loongarch64 静态交叉编译"
      FAIL=1
    fi
  fi
fi

echo ""
if [[ "${FAIL}" = "0" ]]; then
  echo "== 自检全部通过 =="
else
  echo "== 存在失败项(见上方 [FAIL]) =="
fi
exit "${FAIL}"
