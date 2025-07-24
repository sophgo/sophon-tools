#!/bin/bash

PATH=${PATH}:~/.cargo/bin/
CROSS=$(which cross)

rm -rf target
cargo install cross
echo "$(git describe --tags --abbrev=0)-$(git rev-parse HEAD)" > .git_version
${CROSS} build --target aarch64-unknown-linux-musl --release
aarch64-linux-gnu-strip -s -v target/aarch64-unknown-linux-musl/release/bm_set_ip
