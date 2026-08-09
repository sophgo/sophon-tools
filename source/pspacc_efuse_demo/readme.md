# efuse+spacc加解密Demo

## 说明

本工程用于简要说明如何使用BM1684、BM1684X芯片的efuse+spacc做加解密。

## 适用场景

* 芯片：BM1684 BM1684X

## 使用方式

### 统一构建接口（release.sh）

``` bash
bash release.sh [ARCH]          # ARCH: amd64|arm64|all，默认 amd64
OUTPUT_DIR=xxx bash release.sh all   # env OUTPUT_DIR 指定产物目录
```

产物默认输出到 `<repo>/output/pspacc_efuse_demo/`；单 arch 产物为 `spacc_efuse_demo`，`all` 依次构建双架构并输出 `spacc_efuse_demo_amd64` / `spacc_efuse_demo_arm64`。

### 手工编译

``` bash
gcc spacc_efuse_demo.c -o spacc_efuse_demo
chmod +x spacc_efuse_demo
./spacc_efuse_demo [明文参数]
```
