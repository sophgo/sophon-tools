# SE写卡工具 (sewriter)

给现场/产线用的 **SE 系列设备 TF 卡制作工具**（Windows 单文件，免安装）：选卡 → 选模式 →
二次确认 → 写入/格式化 → 写后回读校验。三种模式：

| 模式 | 做什么 |
|---|---|
| **制作刷机卡** | 把发版文件包 / 目录格式化成 MBR+FAT32 后写入（SE5/SE7/SE9 恢复卡） |
| **写入整盘镜像** | 把 `.img`/`.raw`/`.iso`（或其压缩体）逐字节写到卡上 |
| **只格式化 TF 卡**（默认） | 只把卡做成 MBR+FAT32，不写入任何文件 |

- **平台**：Windows 7 及以上，静态链接、无运行库依赖。默认交付 32 位 `sewriter.exe`（Win7 32/64 位通用），
  另有 64 位 `sewriter-x64.exe`（体积略小、速度略快）。
- **双击即弹 UAC**：manifest 里是 `requireAdministrator` —— 读写物理盘必须管理员权限。
- **内置中文字体**：现场有机器系统字体不全，中文会画成一排豆腐块。exe 里直接带了一份
  Noto Sans CJK SC 子集（SIL OFL 1.1，见 `assets/OFL.txt`），启动时注册进本进程，不落盘、不改系统。
  代价是 exe 大约多 3.4 MiB。字集由 `assets/mkfont.py` 生成，覆盖 GB2312 全部汉字 ——
  极少数生僻字（GB2312 之外）仍可能显示不出来。
- **默认不带内置镜像**：数据源在界面里选（文件包 / 目录 / 整卡镜像）。需要"插卡即烧、不用带镜像文件"
  的版本时，用 `--image` 编一个自带镜像的 exe；也可以让程序自己生成（`repack` / 菜单「工具 →
  导出自带镜像的新程序…」），不需要构建机、不需要 Go 环境。
- **源码**：`source/psewriter/`（Go；GUI 用 lxn/walk，磁盘操作走 Win32 API）。

现场操作步骤、包格式提速建议与常见问题见 [SE写卡工具说明.md](./SE写卡工具说明.md)。

## 数据源与写入方式

| 来源 | 写入方式 |
|---|---|
| 发版文件包 `.zip`（推荐） | 快速格式化为 MBR+FAT32，只写实际文件 |
| 文件包 `.txz` / `.tar.zst` 等顺序压缩流 | 同上，但没有索引 —— 分析/写卡/写后校验各要整条解一遍，慢很多 |
| 目录 | 同上（等价于文件包，省掉打包步骤） |
| 整卡镜像 `.img` / `.raw` / `.iso` 及其 gz/xz/bz2/zst 压缩体 | 逐字节整盘写入（源块与卡上都是全零则整块跳过） |
| 无（**只格式化**模式） | 只建 MBR+FAT32，不写任何文件 |

- 压缩包/目录**多套了一层**（如 `sdbootrecoveryfiles/`）时，按特征文件（`fip.bin` / `boot.scr` /
  `*.itb` / `recovery-ui/`）自动定位刷机包根目录并剥掉外层，保证落到卡根目录的就是刷机包本身；
  多个候选目录时不猜，直接报出来让人判断。
- 默认写后两级校验：回读比对分区表 / 引导扇区 / **FAT 两份副本**，再从卡上挂载 FAT32 逐文件比对
  sha256；另外核对卡根 **8.3 短名**（SE7 的 BL1 关闭了长名支持，只认短名）。任一项不过即判失败。
  只格式化模式没有文件，故只做前一级（结构核对）。

### 只格式化 TF 卡

卡被别的工具格式化成了 exFAT / NTFS / GPT，或者 FAT32 被写坏时，SE7 的 BL1 会认不出来
（它走 FatFs，只认 MBR + FAT32）。这个模式把**整张卡**重做成 MBR + 1×FAT32，不写任何文件 ——
不必重新下一份发版包，格式化完直接用资源管理器往里拷文件即可。

- 分区起始 LBA 2048（1 MiB 对齐）、类型 `0x0C`，与写卡时先建的那种格式完全一样，两种卡可互换。
- 卷标可指定（默认 `SE`）；卷标只给人看，不影响设备引导。
- 卡大于 FAT32 上限（2 TiB）时按上限建分区；小于 64 MiB 时报错。
- 写后回读核对分区表 / BPB / FAT 两份副本（没有文件，故无文件级校验）。

## 命令行（无人值守 / 批处理）

```
sewriter.exe                              图形界面（需管理员权限）
sewriter.exe list [--all]                 列出磁盘
sewriter.exe info                         查看内置数据源与磁盘
sewriter.exe write --disk N [--image <包> | --dir <目录>] [--yes] [--no-verify] [--force]
sewriter.exe format --disk N [--label <卷标>] [--yes] [--no-verify] [--force]
sewriter.exe verify --disk N [--image <包> | --dir <目录>]
sewriter.exe hash [--image <包>]
sewriter.exe repack --image <包> [--out <新程序>] [--skeleton <模板程序>] [--force]
```

```bat
sewriter.exe write --disk 3 --dir D:\se7-card --yes
sewriter.exe write --disk 3 --image se7-recovery-files-1.6.0.zip --yes
sewriter.exe format --disk 3 --yes
sewriter.exe verify --disk 3 --image se7-recovery-files-1.6.0.zip
```

- `--disk` 收磁盘号，也收设备路径。
- 系统盘永不出现在可选列表；SATA/NVMe 等固定盘默认隐藏，需 `--all` 查看 + `--force` 才可写。

## 构建

仓库根目录（Docker 统一镜像内编译，产物汇到 `output/psewriter/`）：

```bash
bash release.sh --project psewriter                 # 默认平台 windows
```

本工具目录（等价接口，需要本机有 Go + mingw windres）：

```bash
bash release.sh                       # 默认 windows（32+64 位），不带内置镜像
bash release.sh all                   # 再附带 Linux CLI（本机自测 / repack 用）
bash release.sh windows 2.1.0         # 显式指定平台与版本（演练）
IMAGE=/path/pkg.zip bash release.sh   # 额外产出自带内置镜像的 sewriter-embedded.exe
```

- 版本号唯一来源是本目录 `VERSION` 文件；统一入口（根 `release.sh`）按规范不传版本号。
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
- **GUI 是 `//go:build windows`**：Linux 上只能交叉编译验语法，布局/交互改完务必在 Windows 实机点一遍。
- **目录源剥前缀后，读内容要按磁盘原始路径**（`ArchiveEntry.SrcName`），不能拿卡上目标名去拼源目录
  —— 压缩包源没这个问题（迭代器读的是容器自己的目录表）。
- `go test ./...` 覆盖打包/建卡/写后校验/刷机包目录定位/只格式化等核心路径，Linux 上即可跑。
