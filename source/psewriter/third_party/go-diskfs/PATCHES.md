# go-diskfs 本地补丁说明

上游: `github.com/diskfs/go-diskfs` v1.9.4 (BSD-2-Clause, 见同目录 `LICENSE`)
本目录是**打了补丁的本地副本**, 通过 `tools/winflash/go.mod` 的
`replace github.com/diskfs/go-diskfs => ./third_party/go-diskfs` 生效。

副本已裁掉 `testdata/`、`*_test.go`、`examples/` 与 CI 配置, 只保留编译所需源码。

## 为什么要打补丁

1. 上游的 FAT32 **写入**路径对非 ASCII 文件名有多个 bug, 导致中文名文件根本写不进卡
   (或写进去后读不回来)。读取路径本身没问题。
2. 上游 `allocateSpace()` 每分配一次簇都调 `WriteFat()`, 而 `WriteFat` 每次把**整张 FAT**
   (含两份副本) 重写一遍。TF 卡的 FAT 有几 MB, 一个 1 GiB 的文件包会因此写出十几 GB ——
   既慢又费卡。补丁 5 让它只回写变化的扇区。

## 补丁清单 (搜索 `PATCH(setf)` 可定位全部改动)

| # | 文件 | 问题 | 修法 |
|---|---|---|---|
| 1 | `filesystem/fat12/directoryentry.go` `uCaseValid()` | 用 `validShortNameCharacters.Contains(byte(val))` 判合法性 —— 把 rune **截断成 8 位**。低字节恰好落在合法集里的汉字会被原样保留 (例: 中 U+4E2D → `byte` 0x2D 是合法的 `-`), 随后 8.3 校验和计算因 "non-ASCII character in name" 失败 → 文件写不进去 | 先要求 `val <= 0x7f` 再查字符集, 非 ASCII 一律按默认分支替换成 `_` |
| 2 | `filesystem/fat12/directory.go` `createEntry()` | 只在"名字超长被截断"时用 `~N` 去重。名字被**改写**过同样会撞车 —— `中文.bin` 与 `英文.bin` 的短名都被改写成同一串下划线, 于是同目录出现两个相同的 8.3 短名 (非法目录结构) | 只要名字被改写过 (`isLFN`) 就调用 `uniqueShortName()` 保证短名唯一 |
| 3 | `filesystem/fat12/directoryentry.go` `calculateSlots()` | 用 `len(s)`(**字节数**)算 LFN 槽数。一个汉字占 3 字节但只占 1 个字符位, 槽数被高估, 多出的槽用 `0xFFFF` 填满 | 改用 `len([]rune(s))` 按字符数计算 |
| 4 | `filesystem/fat12/directoryentry.go` `longFilenameEntryFromBytes()` | 还原 LFN 时只把 `0x0000` 当结束符, 不认 `0xFFFF` 填充 —— 读到上个 bug 产生的填充槽会把 13 个 `U+FFFF` 当成真实字符拼进名字, 于是按名字查文件必然失败 (表现为 "target file ... does not exist") | `0x0000` 与 `0xFFFF` 都视为结束 (与 Windows 行为一致, 也能读别的工具写的卡) |

补丁 3 与 4 是同一条链上的两个环节: 3 让写出的槽数正确, 4 让读取端对历史/第三方数据健壮。

| # | 文件 | 问题 | 修法 |
|---|---|---|---|
| 5 | `filesystem/fat12/fat12.go` `defaultWriteFAT()` + `filesystem/fat32/table.go` | 每分配一次簇就重写整张 FAT 的两份副本。14 GiB 卡的 FAT 约 7.7 MB, 写一个 1 GiB 的文件包会额外写出十几 GB | `table.SetCluster` 记录脏表项区间; `defaultWriteFAT` **首次**整张照写 (清掉卡上残留的旧 FAT 项), 之后只回写变化的扇区; FAT12/16 不实现该接口, 行为不变 |

实测 (200 MiB 卡 / 3.5 MB 内容): 物理写入量 **15.1 MB → 3.96 MB**; 设备写入次数不变 (463 次)。
回归测试 `TestBuildCardOnDeviceWriteAmplification` 卡住这个量级。

### 补丁 6: 让整个副本能用 Go 1.20 编译 (Windows 7 支持)

Go 1.21 起官方最低要求变成 Windows 10, 要产出能在 **Windows 7** 上运行的 exe 只能用
Go <= 1.20。上游 go-diskfs v1.9.4 用了 Go 1.21 才进标准库的东西, 因此在本副本里做了等价替换:

| 文件 | 问题 | 修法 |
|---|---|---|
| `filesystem/fat12/table.go`、`fat16/table.go`、`fat32/table.go` | `slices.Equal` (Go 1.21+) | 换成包内 `equalUint32s()` |
| `filesystem/ext4/groupdescriptors.go` | `slices.SortFunc` + `cmp.Compare` (Go 1.21+) | 换成 `sort.Slice` |
| `filesystem/ext4/minmax_setf.go` (新增) | `min`/`max` 内建函数 (Go 1.21+) | 用泛型补同名函数 (泛型自 Go 1.18 可用) |
| `filesystem/squashfs/compressor.go` | `github.com/anchore/go-lzo` 要求 Go 1.24 | LZO 分支直接返回"不支持" —— 本工具只读 FAT, 用不到 LZO squashfs |
| `filesystem/fat12/directoryentry.go` | `github.com/elliotwutingfeng/asciiset` 新版要求 Go 1.24 | 换成等价的字符集判断 `validShortNameRune()` (注意: 必须先卡 ASCII 再查字符集, 否则 `byte(val)` 截断会让"低字节恰好合法"的汉字蒙混过关 —— 与补丁 1 是同一个坑) |
| `go.mod` | `go 1.25.0` + 若干高版本依赖 | 降到 `go 1.20`, 依赖锁到 1.20 可编译的版本 |

去掉这两个依赖后, 整个依赖图 (sevenzip / rardecode / klauspost-compress / x-sys / x-text …)
都能降到 Go 1.20 可编译的版本, 见 `tools/winflash/go.mod`。
回归测试 `TestSevenZipContainersRoundTrip` 覆盖降级后的 7z 解压路径。

## 验证

- `tools/winflash/archive_test.go`:
  - `TestBuildCardImageAcceptsCJKNames` —— 中/日文文件名与中文目录名建卡后按原名读回
  - `TestBuildCardImageShortNameCollision` —— 两个会被改写成相同短名的中文名互不串内容
  - `TestBuildCardImageRejectsUnrepresentableNames` —— BMP 之外(emoji)与 FAT 非法字符仍被拦下
- 端到端: 含中文名/中文目录的 zip 建卡后**用操作系统挂载**, `ls` 显示中文名、内容正确

## 上游

这几个问题都可以反馈给上游 (lxn 的 go-diskfs 仓库)。若上游修复并发布新版本, 可以删掉本
目录与 `replace`, 直接升级依赖。
