// 卡根目录的 BL1 可读性检查 (MYS-1062 二十三轮)
//
// 现场事故: 用本工具写的卡插进 SE7 上电, 串口里 BL1 打印
//
//	NOTICE:  SD initializing 100000000Hz
//	...
//	NOTICE:  fip not found on SD
//	INFO:    BL1: Loading BL2
//	NOTICE:  Locate FIP in SPI flash (DMMR)
//
// 即 BL1 认为卡上没有 fip.bin, 直接回退到板载 SPI flash。
//
// 根因不在"卡的格式": BM1684X 的 BL1 (trusted-firmware-a) 找 fip 走的是 FatFs
// (plat/sophgo/bm1686/bm_io_storage.c: f_mount("0:") + f_open("0:fip.bin")), 其
// ffconf.h 里 **FF_USE_LFN = 0** —— 也就是**只认 8.3 短名, 不解析长文件名条目**。
// 它按 "fip.bin" 去找时, 实际匹配的是短名 "FIP     BIN"。
//
// 而 go-diskfs 生成短名时, 只要文件名需要一条 LFN 保存原样 (哪怕触发条件仅仅是
// **大小写不同**), 就无条件把短名替换成 "~N" 退化名。于是卡上 fip.bin 的短名被写成
// "FIP~1.BIN", BL1 查 "FIP     BIN" 自然查不到 —— 卡上明明有 fip.bin。
//
// 修复见 third_party/go-diskfs/filesystem/fat12/directory.go 的 createEntry。
// 本文件是配套的**写后自检**: 直接按原始目录项核对卡上短名, 让这类"卡看起来没
// 问题、设备却起不来"的坑在写卡当下就暴露, 而不是等到插卡上电看串口。
package main

import (
	"encoding/binary"
	"fmt"
	"strings"
)

// cardDirEntry 卡上一条目录项 (挑出我们关心的两个名字)
type cardDirEntry struct {
	Short string // 8+3 短名, 原样保留空格 ("FIP     BIN")
	Long  string // 长名 (无 LFN 时为空)
	Dir   bool
}

// DisplayName 人读名字: 优先长名
func (e cardDirEntry) DisplayName() string {
	if e.Long != "" {
		return e.Long
	}
	return shortToDotted(e.Short)
}

// CardBL1Check 卡根目录的 BL1 可读性核对结果
type CardBL1Check struct {
	Entries    []cardDirEntry
	RootOffset int64
	// FIPShort 卡上 fip.bin 的短名; 空 = 卡上压根没有 fip.bin (不判错)
	FIPShort string
	// Degraded 名字本身是完全合法的 8.3、短名却被写成 ~N 的条目 (提示用)
	Degraded []string
}

// OK 卡能被 BL1 加载 (没有 fip.bin 时不判错 —— 那不是恢复卡, 与本检查无关)
func (c *CardBL1Check) OK() bool { return c == nil || c.FIPShort == "" || c.FIPShort == "FIP     BIN" }

// Note 一行结论
func (c *CardBL1Check) Note() string {
	switch {
	case c == nil:
		return ""
	case c.FIPShort == "FIP     BIN":
		s := "卡根 fip.bin 短名 FIP.BIN (BL1 可识别)"
		if len(c.Degraded) > 0 {
			s += fmt.Sprintf("; 另有 %d 个本可无损的 8.3 名被写成了 ~N (不影响 BL1): %s",
				len(c.Degraded), strings.Join(c.Degraded, ", "))
		}
		return s
	case c.FIPShort == "":
		return "卡根没有 fip.bin (非恢复卡, 跳过 BL1 检查)"
	default:
		return fmt.Sprintf("卡根 fip.bin 的短名是 %q, 不是 FIP.BIN —— "+
			"BM1684X 的 BL1 只认 8.3 短名, 会上电后打印 \"fip not found on SD\" 并回退 SPI flash",
			shortToDotted(c.FIPShort))
	}
}

// CheckCardBL1 解析卡上 FAT32 根目录, 核对 BL1 关心的短名。
//
// 只做只读解析 (MBR → BPB → 根目录簇链), 不依赖 go-diskfs, 因此它核对的是
// **卡上的原始字节**, 而不是文件系统库"以为"写下去的东西 —— 后者正是这次漏检的原因。
func CheckCardBL1(dev DiskDevice) (*CardBL1Check, error) {
	if dev == nil {
		return nil, fmt.Errorf("没有设备")
	}
	// 设备 I/O 一律走对齐层: Windows 物理盘要求偏移/长度都是扇区整数倍,
	// 而本函数是按"字节精确"读的 (读 512B 首扇区、读 4B FAT 项), 不套层会在
	// 真机上直接吃 ERROR_INVALID_PARAMETER。
	dev = newAlignedDevice(dev, nil)
	mbr := make([]byte, 512)
	if _, err := dev.ReadAt(mbr, 0); err != nil {
		return nil, fmt.Errorf("读卡首扇区失败: %w", err)
	}
	if mbr[510] != 0x55 || mbr[511] != 0xAA {
		return nil, fmt.Errorf("卡首扇区不是分区表 (无 55AA 签名)")
	}
	// 第一个非空分区项 (MBR 分区表在偏移 446, 每项 16 字节, 起始 LBA 在 +8)
	partLBA := int64(0)
	for i := 0; i < 4; i++ {
		e := mbr[446+i*16 : 446+(i+1)*16]
		if e[4] == 0 {
			continue
		}
		partLBA = int64(binary.LittleEndian.Uint32(e[8:12]))
		break
	}
	if partLBA == 0 {
		return nil, fmt.Errorf("卡上没有分区 (BL1 走 FatFs, 不认 superfloppy 以外的无分区布局)")
	}
	part := partLBA * 512

	// BPB
	bpb := make([]byte, 512)
	if _, err := dev.ReadAt(bpb, part); err != nil {
		return nil, fmt.Errorf("读分区引导扇区失败: %w", err)
	}
	bps := int64(binary.LittleEndian.Uint16(bpb[11:13]))
	if bps == 0 {
		bps = 512
	}
	spc := int64(bpb[13])
	rsvd := int64(binary.LittleEndian.Uint16(bpb[14:16]))
	nfat := int64(bpb[16])
	fatSz := int64(binary.LittleEndian.Uint32(bpb[36:40]))
	rootClus := int64(binary.LittleEndian.Uint32(bpb[44:48]))
	if spc == 0 || rootClus < 2 {
		return nil, fmt.Errorf("分区不是 FAT32 (簇大小 %d, 根目录簇 %d)", spc, rootClus)
	}
	clusBytes := spc * bps
	dataStart := part + (rsvd+nfat*fatSz)*bps
	fatStart := part + rsvd*bps

	// 沿 FAT 链走根目录 (恢复卡条目很少, 一簇就够, 但链走满更稳妥)
	res := &CardBL1Check{RootOffset: dataStart + (rootClus-2)*clusBytes}
	var pendingLFN []string
	clus := rootClus
	for n := 0; n < 128 && clus >= 2 && clus < 0x0FFFFFF8; n++ {
		buf := make([]byte, clusBytes)
		if _, err := dev.ReadAt(buf, dataStart+(clus-2)*clusBytes); err != nil {
			return nil, fmt.Errorf("读根目录簇 %d 失败: %w", clus, err)
		}
		end := false
		for off := 0; off+32 <= len(buf); off += 32 {
			e := buf[off : off+32]
			if e[0] == 0x00 {
				end = true
				break
			}
			if e[0] == 0xE5 { // 已删除
				pendingLFN = nil
				continue
			}
			switch {
			case e[11]&0x0F == 0x0F: // LFN 条目
				pendingLFN = append(pendingLFN, lfnChunk(e))
				continue
			case e[11]&0x08 != 0: // 卷标
				pendingLFN = nil
				continue
			}
			short := string(e[0:8]) + string(e[8:11])
			long := strings.Join(pendingLFN, "")
			pendingLFN = nil
			res.Entries = append(res.Entries, cardDirEntry{
				Short: short,
				Long:  long,
				Dir:   e[11]&0x10 != 0,
			})
			// fip.bin: 长名大小写不敏感地等于 fip.bin, 或短名本身就是 FIP.BIN
			if strings.EqualFold(long, "fip.bin") || short == "FIP     BIN" {
				res.FIPShort = short
			}
			// 退化提示: 长名本身是完全合法的 8.3, 短名却是 ~N
			if long != "" && !strings.EqualFold(shortToDotted(short), long) {
				if stem, ext, ok := lossless83(long); ok {
					if !strings.EqualFold(short, stem+ext) && strings.ContainsRune(short, '~') {
						res.Degraded = append(res.Degraded, fmt.Sprintf("%s → %s", long, shortToDotted(short)))
					}
				}
			}
		}
		if end {
			break
		}
		// 下一个簇号 (FAT32: 每项 4 字节, 取低 28 位)
		fe := make([]byte, 4)
		if _, err := dev.ReadAt(fe, fatStart+clus*4); err != nil {
			return nil, fmt.Errorf("读 FAT 表失败: %w", err)
		}
		clus = int64(binary.LittleEndian.Uint32(fe) & 0x0FFFFFFF)
	}
	return res, nil
}

// lfnChunk 取一条 LFN 目录项里的 13 个 UTF-16 码元 (遇到 0x0000/0xFFFF 截断)
func lfnChunk(e []byte) string {
	var sb strings.Builder
	for _, p := range [][2]int{{1, 11}, {14, 26}, {28, 32}} {
		for i := p[0]; i+1 < p[1]; i += 2 {
			u := binary.LittleEndian.Uint16(e[i : i+2])
			if u == 0x0000 || u == 0xFFFF {
				return sb.String()
			}
			sb.WriteRune(rune(u))
		}
	}
	return sb.String()
}

// shortToDotted "FIP     BIN" → "FIP.BIN"; 无扩展名时不加点
func shortToDotted(short string) string {
	if len(short) != 11 {
		return strings.TrimRight(short, " ")
	}
	stem := strings.TrimRight(short[0:8], " ")
	ext := strings.TrimRight(short[8:11], " ")
	if ext == "" {
		return stem
	}
	return stem + "." + ext
}

// lossless83 判断一个名字能否**无损**地写成 8.3 短名; 能则返回其大写 stem/ext。
//
// 只认最保守的字符集 (字母/数字/下划线/连字符): 判错的方向是"漏报"而不是"误报",
// 免得把 "中文名.txt" 这类本来就必须退化的名字错报成问题。
func lossless83(name string) (stem, ext string, ok bool) {
	base := name
	if i := strings.LastIndex(name, "."); i >= 0 {
		base, ext = name[:i], name[i+1:]
	}
	if base == "" || len(base) > 8 || len(ext) > 3 {
		return "", "", false
	}
	if !plain83(base) || (ext != "" && !plain83(ext)) {
		return "", "", false
	}
	return strings.ToUpper(base), strings.ToUpper(ext), true
}

func plain83(s string) bool {
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '_', r == '-':
		default:
			return false
		}
	}
	return true
}
