#!/bin/bash

function panic() {
    if [ $# -gt 0 ]; then
        echo "" >&1
        echo "[ERROR] $@" >&1
        echo "" >&1
    fi
    exit -1
}

function file_validate() {
    local file
    file=$(eval echo \$1)
    [ -r ${file} ] || panic "$i \"$file\" is not readable"
}

echo "[INFO] memtest logs check start..."
dir_path="$(dirname "$(readlink -f "$0")")"
echo "[INFO] work dir: $dir_path"
pushd $dir_path &>/dev/null
if [ ! -d logs ]; then
    panic "cannot find logs dir!!!"
fi
pushd logs &>/dev/null
file_validate gdma.log
file_validate memtester.log
if [ -f error.log ]; then
    cat error.log
    panic "find error log!!!"
fi
if [[ "$(cat gdma.log | grep 'ERROR' | wc -l)" != "0" ]]; then
    cat gdma.log | grep -a -n10 'ERROR'
    panic "find gdma test error log!!!"
fi
if [[ "$(cat memtester.log | grep -E 'ERROR|FAILURE' | wc -l)" != "0" ]]; then
    cat memtester.log | grep -E -a -n10 'ERROR|FAILURE'
    panic "find memtester test error log!!!"
fi
echo "[INFO] memtest logs check success, no error!!!"
popd &>/dev/null
popd &>/dev/null
