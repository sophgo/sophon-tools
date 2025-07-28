#!/bin/bash

PATH=${PATH}:~/.cargo/bin/
CROSS=$(which cross)

rm -rf target
cargo install cross cargo-bloat
echo "$(git describe --tags --abbrev=0)-$(git rev-parse HEAD)-$(date -u "+%Y%m%d_%H%M%S")" > .git_version
${CROSS} build --target aarch64-unknown-linux-musl --release
upx -9 --best --nrv2b --no-color target/aarch64-unknown-linux-musl/release/bm_set_ip
