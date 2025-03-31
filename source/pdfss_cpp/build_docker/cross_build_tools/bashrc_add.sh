# add by cross_build_sophon

function add_path()
{
        export PATH="${1}:$PATH"
}

add_path /usr/sw/swgcc830_cross_tools/usr/bin
add_path /env/loongarch64-cross-tools-gcc_14.2.0/bin

cd /workspace

ulimit -n 8192
git config --global --add safe.directory "*"

TOOLS=("gcc" "g++")

TOOLCHAIN_REGEX="^(arm|aarch64|mips|mipsel|riscv|riscv64|powerpc|sparc|x86_64|i686|sw_64|loongarch64)-.*-"

echo "find all gcc/g++ compilation toolchains:"
IFS=":" read -r -a PATH_DIRS <<< "$PATH"
for DIR in "${PATH_DIRS[@]}"; do
    if [ -d "$DIR" ]; then
        for FILE in "$DIR"/*; do
            BASENAME=$(basename "$FILE")
            if [[ "$BASENAME" =~ $TOOLCHAIN_REGEX ]]; then
                for TOOL in "${TOOLS[@]}"; do
                    if [[ "$BASENAME" == *"$TOOL" ]]; then
                        echo -n "$BASENAME ($FILE): "
                        "$FILE" --version 2>/dev/null | head -n 1 || echo "无法获取版本信息"
                    fi
                done
            fi
        done
    fi
done

