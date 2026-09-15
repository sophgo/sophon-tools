// 换镜像生成新程序 (MYS-1062 五轮)
//
// 程序自身即可完成: 剥离自己的 payload 得到纯净骨架 → 追加新镜像 → 产出第二个自带镜像的程序。
// 不需要构建机、不需要 Go 环境; 生成的新程序同样可以再次换镜像, 链式进行。
package main

import (
	"compress/gzip"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// PackResult repack 结果 (CLI/GUI 展示)
type PackResult struct {
	OutPath       string
	OutBytes      int64
	OutSHA256     string
	SkeletonBytes int64
	SkeletonSHA   string
	Image         PayloadMeta
	Verified      bool // 生成后已回读校验 payload 内容
}

// DefaultOutPath 依据骨架与镜像版本推导默认输出路径
func DefaultOutPath(skeletonPath string, img *ImageSource) string {
	dir := filepath.Dir(skeletonPath)
	ext := filepath.Ext(skeletonPath)
	base := strings.TrimSuffix(filepath.Base(skeletonPath), ext)
	ver := imgVersion(img)
	if ver == "" {
		ver = "repacked"
	}
	return filepath.Join(dir, fmt.Sprintf("%s-%s%s", base, ver, ext))
}

// imgVersion 从镜像名里提取版本号 (形如 se7-recovery-1.5.1-2026-09-14-noaging.img.gz → 1.5.1)
func imgVersion(img *ImageSource) string {
	if img == nil {
		return ""
	}
	name := img.Display()
	for _, ext := range []string{".gz", ".xz", ".zst", ".img"} {
		name = strings.TrimSuffix(name, ext)
	}
	for _, f := range strings.FieldsFunc(name, func(r rune) bool { return r == '-' || r == '_' }) {
		if isVersion(f) {
			return f
		}
	}
	return ""
}

// isVersion 形如 1.5.1 / 2.0 的纯数字点分版本号
func isVersion(s string) bool {
	parts := strings.Split(s, ".")
	if len(parts) < 2 {
		return false
	}
	for _, p := range parts {
		if p == "" {
			return false
		}
		for _, r := range p {
			if r < '0' || r > '9' {
				return false
			}
		}
	}
	return true
}

// Repack 用 skeletonPath 的骨架 + imgPath 的镜像, 生成 outPath 新程序。
//   - skeletonPath 为空 = 当前程序自身
//   - outPath 为空 = 按镜像版本自动命名 (与骨架同目录)
//   - force = 允许覆盖已存在的 outPath
func Repack(imgPath, outPath, skeletonPath string, force bool, cb Progress) (*PackResult, error) {
	if strings.TrimSpace(imgPath) == "" {
		return nil, errors.New("未指定镜像文件")
	}
	if skeletonPath == "" {
		skeletonPath = SelfExePath()
	}
	if skeletonPath == "" {
		return nil, errors.New("无法定位当前程序路径")
	}
	self := SelfExePath()
	if samePath(skeletonPath, self) {
		// 骨架就是自己: 允许 (只读自身), 但输出不能是自己
	}

	// 1) 解析骨架 (有 payload 则剥离)
	skel, err := os.Open(skeletonPath)
	if err != nil {
		return nil, err
	}
	st, err := skel.Stat()
	if err != nil {
		skel.Close()
		return nil, err
	}
	skelSize := st.Size()
	if p, perr := ReadPayloadFrom(skel, skelSize); perr == nil {
		skelSize = p.Offset // 剥离旧 payload, 复用纯净骨架
	} else if !errors.Is(perr, ErrNoPayload) {
		skel.Close()
		return nil, fmt.Errorf("读取骨架失败: %w", perr)
	}

	// 2) 解析镜像
	img, err := OpenImage(imgPath)
	if err != nil {
		skel.Close()
		return nil, err
	}
	if outPath == "" {
		outPath = DefaultOutPath(skeletonPath, img)
	}
	outPath, _ = filepath.Abs(outPath)
	if samePath(outPath, skeletonPath) || samePath(outPath, self) {
		skel.Close()
		return nil, fmt.Errorf("输出路径不能是程序自身 (%s) — 请另起文件名", outPath)
	}
	if !force {
		if _, err := os.Stat(outPath); err == nil {
			skel.Close()
			return nil, fmt.Errorf("输出文件已存在: %s (加 --force 覆盖)", outPath)
		}
	}

	// 3) 骨架 sha256 (留证 + 交叉校验)
	skelHash := sha256.New()
	if _, err := copyWithProgress(skelHash, io.NewSectionReader(skel, 0, skelSize), skelSize, "skeleton", cb); err != nil {
		skel.Close()
		return nil, err
	}
	skelSHA := fmt.Sprintf("%x", skelHash.Sum(nil))

	// 4) 写出新程序
	out, err := os.Create(outPath)
	if err != nil {
		skel.Close()
		return nil, err
	}
	defer out.Close()
	if _, err := copyWithProgress(out, io.NewSectionReader(skel, 0, skelSize), skelSize, "skeleton", cb); err != nil {
		skel.Close()
		return nil, err
	}
	skel.Close()

	meta, err := writeImagePayload(out, imgPath, img, skelSize, skelSHA, cb)
	if err != nil {
		out.Close()
		os.Remove(outPath)
		return nil, err
	}
	if err := writeFooter(out, *meta); err != nil {
		out.Close()
		os.Remove(outPath)
		return nil, err
	}
	if err := out.Sync(); err != nil {
		out.Close()
		os.Remove(outPath)
		return nil, err
	}
	if err := out.Close(); err != nil {
		os.Remove(outPath)
		return nil, err
	}
	// 新程序继承骨架的权限位 (Linux 上生成的可执行文件需保持可执行)
	_ = os.Chmod(outPath, st.Mode().Perm())

	// 5) 回读校验新程序 (结构 + payload 内容)
	res := &PackResult{OutPath: outPath, SkeletonBytes: skelSize, SkeletonSHA: skelSHA, Image: *meta}
	if err := verifyPacked(res); err != nil {
		os.Remove(outPath)
		return nil, fmt.Errorf("生成的新程序自检失败, 已删除: %w", err)
	}
	return res, nil
}

// writeImagePayload 把镜像数据流式追加到 w, 返回写入的 meta
func writeImagePayload(w io.Writer, imgPath string, img *ImageSource, skelSize int64, skelSHA string, cb Progress) (*PayloadMeta, error) {
	src, err := os.Open(imgPath)
	if err != nil {
		return nil, err
	}
	defer src.Close()
	st, err := src.Stat()
	if err != nil {
		return nil, err
	}
	h := sha256.New()
	n, err := copyWithProgress(io.MultiWriter(w, h), src, st.Size(), "image", cb)
	if err != nil {
		return nil, err
	}
	if n != st.Size() {
		return nil, fmt.Errorf("镜像读取不完整: %d / %d", n, st.Size())
	}
	meta := &PayloadMeta{
		File:          filepath.Base(imgPath),
		Bytes:         img.Size(),
		StoredBytes:   n,
		StoredSHA256:  fmt.Sprintf("%x", h.Sum(nil)),
		Compressed:    img.gzip,
		PackedAt:      time.Now().Format(time.RFC3339),
		SourcePath:    imgPath,
		ToolVersion:   toolVersion,
		Origin:        "repack",
		SkeletonBytes: skelSize,
		SkeletonSHA:   skelSHA,
	}
	if meta.Bytes <= 0 {
		meta.Bytes = n // 解压大小未知时按内置数据大小 (未压缩镜像)
	}
	// 镜像版本: 优先取源文件名解析, 回退构建版本常量
	meta.BuildVer = imgVersion(img)
	if meta.BuildVer == "" {
		meta.BuildVer = buildVersion
	}
	// 解压后内容 sha256
	if !img.gzip {
		meta.SHA256 = meta.StoredSHA256
	} else if sc := sidecarSHA256(imgPath); sc != "" {
		meta.SHA256 = sc
	} else {
		sum, err := decodedSHA256(imgPath)
		if err != nil {
			return nil, fmt.Errorf("计算镜像解压 sha256 失败: %w", err)
		}
		meta.SHA256 = sum
	}
	return meta, nil
}

// decodedSHA256 流式解压后计算 sha256 (不需要与镜像等大的临时空间)
func decodedSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	zr, err := gzip.NewReader(f)
	if err != nil {
		return "", err
	}
	defer zr.Close()
	h := sha256.New()
	if _, err := io.Copy(h, zr); err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", h.Sum(nil)), nil
}

// sidecarSHA256 读发版包随附的 <镜像>.info 里的 sha256 (有则免去解压重算)
func sidecarSHA256(path string) string {
	b, err := os.ReadFile(path + ".info")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "sha256=") {
			return strings.TrimSpace(strings.TrimPrefix(line, "sha256="))
		}
	}
	return ""
}

// verifyPacked 回读新程序: 结构可解析 + 骨架一致 + payload 内容 sha256 与 meta 一致
func verifyPacked(res *PackResult) error {
	st, err := os.Stat(res.OutPath)
	if err != nil {
		return err
	}
	res.OutBytes = st.Size()
	p, err := OpenPayloadFile(res.OutPath)
	if err != nil {
		return fmt.Errorf("新程序尾部结构不可解析: %w", err)
	}
	if p.Offset != res.SkeletonBytes || p.Meta.SkeletonSHA != res.SkeletonSHA {
		return errors.New("骨架信息与写入不符")
	}
	if p.Meta.StoredBytes != res.Image.StoredBytes || p.Meta.SHA256 != res.Image.SHA256 {
		return errors.New("镜像元信息与写入不符")
	}
	f, err := os.Open(res.OutPath)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, io.NewSectionReader(f, p.Offset, p.Size)); err != nil {
		return err
	}
	if got := fmt.Sprintf("%x", h.Sum(nil)); got != p.Meta.StoredSHA256 {
		return fmt.Errorf("内置数据校验失败: %s ≠ %s", shortHash(got), shortHash(p.Meta.StoredSHA256))
	}
	// 骨架字节与源骨架一致
	sh := sha256.New()
	if _, err := io.Copy(sh, io.NewSectionReader(f, 0, p.Offset)); err != nil {
		return err
	}
	if got := fmt.Sprintf("%x", sh.Sum(nil)); got != res.SkeletonSHA {
		return errors.New("骨架字节与源不一致")
	}
	oh := sha256.New()
	if _, err := io.Copy(oh, f); err != nil {
		return err
	}
	res.OutSHA256 = fmt.Sprintf("%x", oh.Sum(nil))
	res.Verified = true
	return nil
}

// samePath 两个路径是否指向同一文件 (含符号链接/相对路径)
func samePath(a, b string) bool {
	if a == "" || b == "" {
		return false
	}
	aa, err1 := filepath.Abs(a)
	bb, err2 := filepath.Abs(b)
	if err1 != nil || err2 != nil {
		return a == b
	}
	if aa == bb {
		return true
	}
	ra, err1 := filepath.EvalSymlinks(aa)
	rb, err2 := filepath.EvalSymlinks(bb)
	if err1 == nil && err2 == nil && ra == rb {
		return true
	}
	sa, err1 := os.Stat(aa)
	sb, err2 := os.Stat(bb)
	return err1 == nil && err2 == nil && os.SameFile(sa, sb)
}

// copyWithProgress 带进度回调的拷贝 (cb 为 nil 时退化为 io.Copy)
func copyWithProgress(dst io.Writer, src io.Reader, total int64, phase string, cb Progress) (int64, error) {
	if cb == nil {
		return io.Copy(dst, src)
	}
	buf := make([]byte, 1<<20)
	var done int64
	last := time.Now()
	var lastBytes int64
	for {
		n, rerr := src.Read(buf)
		if n > 0 {
			if _, werr := dst.Write(buf[:n]); werr != nil {
				return done, werr
			}
			done += int64(n)
			now := time.Now()
			if now.Sub(last) >= 200*time.Millisecond {
				cb(phase, done, total, float64(done-lastBytes)/now.Sub(last).Seconds())
				last, lastBytes = now, done
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return done, rerr
		}
	}
	cb(phase, done, total, 0)
	return done, nil
}
