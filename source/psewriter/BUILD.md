# SE写卡工具 — 开发与构建

面向开发者。用户向的使用说明见 [README.md](./README.md)。

## 目录结构

```
source/psewriter/
├── README.md            用户向说明（含完整流程图）
├── BUILD.md             本文件
├── release.sh           M1 统一构建入口（薄壳，转发到 src/release.sh）
├── docs/images/         README 用图
└── src/                 Go 源码与构建脚本
    ├── *.go             主程序与单元测试
    ├── go.mod / go.sum
    ├── build.sh         实际构建逻辑
    ├── release.sh       统一接口实现
    ├── VERSION          版本号唯一来源
    ├── check_exe.py     PE 结构自检（位宽 / Win7 子系统版本 / manifest）
    ├── sewriter.rc / sewriter.manifest / rsrc_windows_*.syso
    ├── assets/          内置字体（go:embed）+ mkfont.py + OFL.txt
    └── third_party/     go-diskfs 本地打补丁副本（go.mod replace 指向这里）
```

## 构建

仓库根目录（Docker 统一镜像内编译，产物汇到 `output/psewriter/`）：

```bash
bash release.sh --project psewriter                 # 默认平台 windows
```

本工具目录（等价接口，需要本机有 Go + mingw windres）：

```bash
cd src
bash release.sh                       # 默认 windows（32+64 位），不带内置镜像
bash release.sh all                   # 再附带 Linux CLI（本机自测 / repack 用）
bash release.sh windows 2.1.0         # 显式指定平台与版本（演练）
IMAGE=/path/pkg.zip bash release.sh   # 额外产出自带内置镜像的 sewriter-embedded.exe
```

- 版本号唯一来源是 `src/VERSION`；统一入口（根 `release.sh`）按规范不传版本号。
- Windows 侧用 **Go 1.20.x** 编译（脚本用 `GOTOOLCHAIN`，默认 `go1.20.14` 自动拉取）——
  Go 1.21 起官方最低要求 Windows 10，要支持 Win7 只能锁 1.20；首次构建需要能访问模块代理，
  离线环境用 `bash build.sh --win7-go <版本>` 指定预热好的工具链。
- 产物：`sewriter.exe`（32 位，默认交付物）、`sewriter-x64.exe`、`sewriter-linux`（`all` 时）、
  `sewriter-embedded.exe`（设了 `IMAGE` 时）。

## 开发注意

- **改 GUI 相关代码前务必先读 manifest**：exe 必须嵌入应用程序 manifest
  （`sewriter.manifest` → `sewriter.rc` → `rsrc_windows_<arch>.syso`），否则 Windows 只加载
  comctl32 v5，而 lxn/walk 是 Unicode 程序 → 启动即报 `TTM_ADDTOOL failed` 退出。
  `build.sh` 每次构建都用 `windres` 重新生成（无 windres 时沿用仓库内那份），改完用
  `python3 check_exe.py <exe>` 验位宽 / PE 子系统 ≤ 6.01（Win7）/ manifest 含 `requireAdministrator`。
- **GUI 是 `//go:build windows`**：Linux 上只能交叉编译验语法，布局 / 交互改完务必在 Windows 实机点一遍。
- **目录源剥前缀后，读内容要按磁盘原始路径**（`ArchiveEntry.SrcName`），不能拿卡上目标名去拼源目录
  —— 压缩包源没这个问题（迭代器读的是容器自己的目录表）。
- `go test ./...` 覆盖打包 / 建卡 / 写后校验 / 刷机包目录定位 / 只格式化等核心路径，Linux 上即可跑。
- 字体子集改动后跑 `python3 assets/mkfont.py --check` 自查界面源码里有没有缺字。

## 历史修复（回归测试保护）

- **2.0.4 卡根 8.3 短名**：短名曾被写成 `FIP~1.BIN`，而 BL1 只认 `FIP.BIN`。修复见
  `bl1check.go`，回归测试覆盖卡根短名核对。
- **2.0.5 / 2.0.6 目录源多层包裹**：选中多套了一层刷机包目录、或存在「与刷机包目录同名的嵌套层」
  （如 `pkg/pkg/pkg/boot.scr`）时写错路径。修复见 `bootroot.go` / `dirsource.go`。
- **2.1.0 大卡 FAT32 几何**：算「FAT 表要多少扇区」时用了 32 位整数、结果又窄化成 16 位、还漏了一项。
  14/15/30/60 GB 等档位 FAT 表少算 1~2 个表项；384 GB ~ 512 GB 表远小于卷所需（384 GB 算出
  32744，实际需要 98280），卡**看着格式化成功**却挂载失败或一写就坏；≥ 512 GB 直接 panic。
  回归测试 `TestFAT32GeometryOnLargeCards` 逐 GB 扫 8~48 GB 再补 256/384/512/1024 GB，
  每档都卡住「FAT 表必须能寻址卷里每一个数据簇」这个不变量。
- **2.1.1 启动失败**：部分机器一开就弹 `启动失败 / LVM_SETCOLUMNWIDTH failed`（末列自适应所致）。
- **2.1.2 / 2.1.3 内置字体与默认模式**：内置中文字体；「只格式化 TF 卡」调到第一顺位并设为默认。
