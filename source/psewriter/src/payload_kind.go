// 内置数据源的"种类"判定与临时落盘 (MYS-1062 十九轮)
//
// 十八轮② 把发版产物从 `.img.gz` 换成了 `.txz` 文件包, 但"程序内置数据源"这条
// 路一直假定载荷就是**整盘镜像**: OpenEmbedded() 直接把它当镜像流写盘。
// 结果: 工具把压缩包字节原样写进了卡 —— 现场表现是"2 秒就写完 83MB, 卡上是垃圾"。
//
// 这里补上判定: 内置的到底是"整盘镜像"还是"压缩包/文件包"; 后者落一个临时副本,
// 交给与"用户手选文件"**完全相同**的那条路径 (probeAny → 归档探测 → 建卡/整盘)。
// 判定用载荷字节本身的魔数 (不看扩展名), 因此对任何工具版本打出来的载荷都成立。
package main

import (
	"bytes"
	"compress/bzip2"
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"

	"github.com/klauspost/compress/zstd"
	"github.com/ulikunitz/xz"
)

// payloadKind 判定内置数据源的种类。
//
//	isPackage=true → 压缩包/文件包 (走归档探测; 需要落临时副本)
//	kind           → 展示用的格式名 (img / gz / tar.xz / zip …)
//
// 判据: 读载荷头 512 字节按魔数识别 (与 ProbeArchive 同一张表);
//   - 裸镜像 (无魔数)            → 整盘镜像, 保持原有流式路径 (不落临时文件)
//   - 单流压缩 (gz/xz/bz2/zst)   → 解压头 512 字节: 是 tar 就是文件包, 否则是整盘镜像
//     (`.img.gz` 解压后是镜像, `.tar.xz` 解压后是 tar —— 只有真正解一小段才知道)
//   - 归档容器 (zip/7z/rar/tar)  → 文件包
func payloadKind(p *Payload) (bool, string, error) {
	f, err := os.Open(p.SelfPath)
	if err != nil {
		return false, "", err
	}
	defer f.Close()
	sr := io.NewSectionReader(f, p.Offset, p.Size)

	head := make([]byte, 512)
	n, _ := io.ReadFull(sr, head)
	head = head[:n]
	format := detectFormat(head)

	switch format {
	case "img":
		return false, "img", nil
	case "gz", "xz", "bz2", "zst":
		// 单流压缩: 解压一小段看是不是 tar (tar 头在偏移 257 处有 "ustar")
		if _, err := sr.Seek(0, io.SeekStart); err != nil {
			return false, "", err
		}
		dhead, derr := decodeStreamHead(sr, format, p.Meta.Compressed)
		if derr != nil {
			// 解不开就不是能当镜像流用的东西, 交给归档探测去报真正的错误
			return true, format, nil
		}
		if isTarHead(dhead) {
			return true, "tar." + format, nil
		}
		return false, format, nil
	default:
		// zip / 7z / rar / tar
		return true, format, nil
	}
}

// decodeStreamHead 解开单流压缩的头 512 字节。
// storedGzip: 载荷本身存的就是 gzip (老 tool 打包 .img.gz 时的存法) —— 这时
// format 已经是 "gz", 二者一致; 参数保留是为了把语义写清楚。
func decodeStreamHead(r io.Reader, format string, storedGzip bool) ([]byte, error) {
	var dec io.Reader
	switch {
	case format == "gz" || storedGzip:
		zr, err := gzip.NewReader(r)
		if err != nil {
			return nil, err
		}
		defer zr.Close()
		dec = zr
	case format == "xz":
		xr, err := xz.NewReader(r)
		if err != nil {
			return nil, err
		}
		dec = xr
	case format == "bz2":
		dec = bzip2.NewReader(r)
	case format == "zst":
		zr, err := zstd.NewReader(r)
		if err != nil {
			return nil, err
		}
		defer zr.Close()
		dec = zr
	default:
		return nil, fmt.Errorf("非单流压缩格式: %s", format)
	}
	head := make([]byte, 512)
	n, err := io.ReadFull(dec, head)
	if err != nil && err != io.ErrUnexpectedEOF && err != io.EOF {
		return nil, err
	}
	if n == 0 {
		return nil, io.ErrUnexpectedEOF
	}
	return head[:n], nil
}

// isTarHead tar 头魔数 ("ustar" @257)
func isTarHead(h []byte) bool {
	return len(h) >= 262 && bytes.Equal(h[257:262], []byte("ustar"))
}

// ---- 临时落盘 (进程内缓存) ----

var (
	embedTmpMu      sync.Mutex
	embedTmpPath    string
	embedTmpCleanup func()
)

// EmbeddedPackageFile 把内置的"压缩包/文件包"落到一个临时文件并返回其路径。
//
// 为什么落盘而不是流式探测: 归档要能被**多次打开** (探测枚举条目 → 写卡时再逐个
// 读内容 → 写后校验再读一遍), 而 exe 尾部的载荷区间只能顺序读。落一份临时副本
// 最省事, 也让内置路径与"用户手选文件"走完全相同的代码。
//
// 结果在进程内缓存: 同一次运行里反复分析/写入不会重复落盘。
// 临时文件留在系统临时目录, 退出时由 CleanupEmbeddedTemp 清掉。
func EmbeddedPackageFile() (string, error) {
	embedTmpMu.Lock()
	defer embedTmpMu.Unlock()
	if embedTmpPath != "" {
		return embedTmpPath, nil
	}
	p, err := OpenSelfPayload()
	if err != nil {
		return "", err
	}
	dst, cleanup, err := materializePayload(p)
	if err != nil {
		return "", err
	}
	embedTmpPath, embedTmpCleanup = dst, cleanup
	return dst, nil
}

// materializePayload 把载荷落到一个临时文件 (返回路径 + 清理函数)。
// 抽出来是为了能在单测里直接喂"假载荷"验证落盘与后续探测。
func materializePayload(p *Payload) (string, func(), error) {
	f, err := os.Open(p.SelfPath)
	if err != nil {
		return "", func() {}, err
	}
	defer f.Close()

	dir, err := os.MkdirTemp("", "sewriter-embedded-")
	if err != nil {
		return "", func() {}, fmt.Errorf("建临时目录失败 (检查系统盘剩余空间): %w", err)
	}
	cleanup := func() { os.RemoveAll(dir) }

	// 文件名保留原名: 卷标、界面展示与"手选同一个包"结果一致
	name := filepath.Base(p.Meta.File)
	if name == "" || name == "." || name == string(filepath.Separator) {
		name = "embedded-package.bin"
	}
	dst := filepath.Join(dir, name)
	out, err := os.Create(dst)
	if err != nil {
		cleanup()
		return "", func() {}, err
	}
	if _, err := io.Copy(out, io.NewSectionReader(f, p.Offset, p.Size)); err != nil {
		out.Close()
		cleanup()
		return "", func() {}, fmt.Errorf("写出内置数据源临时副本失败: %w", err)
	}
	if err := out.Close(); err != nil {
		cleanup()
		return "", func() {}, err
	}
	return dst, cleanup, nil
}

// CleanupEmbeddedTemp 清理内置数据源的临时副本 (程序退出前调用)
func CleanupEmbeddedTemp() {
	embedTmpMu.Lock()
	defer embedTmpMu.Unlock()
	if embedTmpPath == "" {
		return
	}
	if embedTmpCleanup != nil {
		embedTmpCleanup()
	} else {
		os.RemoveAll(filepath.Dir(embedTmpPath))
	}
	embedTmpPath = ""
	embedTmpCleanup = nil
}

// EmbeddedKind 界面/命令行展示用: 内置数据源是文件包还是整盘镜像
// (取不到载荷时返回空串, 由调用方回落到通用文案)
func EmbeddedKind() (isPackage bool, kind string) {
	p, err := OpenSelfPayload()
	if err != nil {
		return false, ""
	}
	pkg, k, err := payloadKind(p)
	if err != nil {
		return false, ""
	}
	return pkg, k
}
