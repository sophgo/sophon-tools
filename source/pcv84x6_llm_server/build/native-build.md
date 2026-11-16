# 原生引擎库的构建记录（v0.6.38）

本文件记录 `build/inputs/lib/libcv84x6_llm.so` 这一次**实际是怎么构建出来的**。
它存在的理由很具体：0.6.37 及更早的包用的是私有仓库快照里的预编译库，
`sophgo/sophon-tools` 内没有该库与源码的对应关系。v0.6.38 的库由本仓库源码构建，
所以来源必须可核对，而不是一句"来自官方 release"。

## 结论

| 项 | 值 |
| --- | --- |
| 源码提交（**A**） | `78b5f0125767e4ffdd097ae2dca781660d1fcab2`（本仓库 `sophgo/sophon-tools`） |
| 源码子目录 | `source/pcv84x6_llm_server/native` |
| 源码子树对象 | `66456d0aed0369c0d1ca2e9f1837204681b0a6ee`（`git rev-parse A:source/pcv84x6_llm_server/native`） |
| 库 SHA256 | `26bd2702cf903bd69a1e413be16f93d327f04a0d99679c6408ea46a8694eee09` |
| 库大小 | 921192 bytes |
| 构建主机 | CV84X6 板卡（aarch64），独立构建目录 `/data/mys2914/build-full` |
| 编译器 | `g++ (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0` |
| CMake | `3.22.1` |
| libsophon | `/opt/sophon/libsophon-current`：`libbmrt.so.1.0` SHA256 `3a71347e079690c437e8d5f408bbcfde65197497f239d48e48918348df53b696`，`libbmlib.so.0` SHA256 `cf17bc768920c49fc906133f4213edd2906c653b90c616ee79931318b77fb620` |
| 编译警告 | 0（`-Wall -Wextra`，全量目标） |

## 复现命令

在 CV84X6 板上，从源码提交 A 的干净导出执行：

```bash
cmake -S source/pcv84x6_llm_server/native -B /tmp/cv84x6-native-build \
      -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/cv84x6-native-build -j"$(nproc)"
sha256sum /tmp/cv84x6-native-build/libcv84x6_llm.so
```

**不要求逐字节一致**（编译器版本、路径长度、链接顺序都会影响产物），要求的是
ABI 与行为一致：`readelf -d` 的 `NEEDED`/`RUNPATH` 清单相同，`nm -D` 的导出入口
相同，`tests/native/run_tests.sh` 通过。本次构建的核对结果：

- `NEEDED`：`libbmrt.so.1.0`、`libbmlib.so.0`、`libjpeg.so.8`、`libz.so.1`、
  `libstdc++.so.6`、`libm.so.6`、`libgcc_s.so.1`、`libc.so.6`、`ld-linux-aarch64.so.1`
  —— 与 0.6.37 发行库逐项相同。
- `RUNPATH`：`/opt/sophon/libsophon-current/lib`。
- 导出 `T` 符号 223 个，与 0.6.37 发行库数量相同，且包含**全部**入口族
  （`cv_vle_*`、`cv_embed_*`、`cv_rerank_*`、`cv_asr_*`、`cv_net_*`、`cv_vl_*`），
  不是只含 WeMM 诊断入口的子集库。

## 这次构建包含什么

相对 0.6.37 发行库，`native/src/vl_embed_engine.cpp` 增加了设备拷贝完成序：
`zero()` / `upload()` / `copy()` / `launch()` 在返回前等待 SDK 同步完成并检查
返回码，失败与 launch 失败走同一条致命路径。原因与证据见
[`tools/vl_embed/MYS-2913-wemm-zero-vector.md`](../tools/vl_embed/MYS-2913-wemm-zero-vector.md)
与板端实测记录。

其余引擎（chat / OCR / ASR / rerank / 通用单图）的源码未改动，仍编入同一个库。

## 验收证据

| 项 | 结果 |
| --- | --- |
| 板端 `tests/native/run_tests.sh /opt/sophon/libsophon-current/include` | 761 checks, 0 failures（含延后完成写模型的回归用例） |
| 无模型 A→B→C 拷贝链，加同步 64 轮 | 0 错，逐字节一致 |
| 3 个全新进程 × 100 个有效请求 | 全部有限、非零；同输入向量**跨进程逐位相同** |
| 四个编译档 128/512/1024/2048 | 全部被实际执行 |
| 对固定 FP32 参考 226/233 样本 × 六档 MRL | 最差余弦 0.993148（门槛 ≥0.99） |
| 加载/卸载后 NPU 堆 | 前后均为 `free_bytes=12283027456` |

完整报告（含原始延迟、每档最差样本）随子任务交付附上。
