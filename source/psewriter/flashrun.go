// 统一写入流程 (MYS-1062 九轮 / 十三轮重构) — CLI 与 GUI 共用
//
// 三种来源, 三条写入路径:
//
//	整盘镜像  ① 逐块写入 (源块全零且卡上已是零 → 整块跳过)
//	         ② 落盘 (Windows FlushFileBuffers + 写通句柄 / Linux fsync), 关句柄重开
//	         ③ 回读逐块比对
//
//	文件包    ① 直接把 MBR+FAT32 建在卡上, 归档流式解压出来的字节直接落卡
//	             (没有整卡尺寸的中间镜像, 未用空间一个字节都不碰)
//	         ② 落盘, 关写句柄换只读句柄
//	         ③ 回读元数据区: 分区表 / BPB / FAT 两份副本
//	         ④ 从卡上挂 FAT32, 逐个文件算 sha256 与源压缩包比对 (用户要的"二次校验文件完整性")
//
//	只格式化  ① 同文件包的第 ① 步, 但计划里没有文件 —— 只建 MBR+FAT32
//	         ② 落盘, 关写句柄换只读句柄
//	         ③ 回读元数据区 (没有文件, 所以没有第 ④ 步)
//
// ② 是用户要的"确保文件都真实写入到 TF 卡中": 句柄关掉再重新只读打开, 绕开系统写缓存。
package main

import (
	"fmt"
	"time"
)

// FlashOutcome 一次写入的完整结果
type FlashOutcome struct {
	IsCard      bool
	FormatOnly  bool // 只格式化: 只建 MBR+FAT32, 没有文件级校验
	Card        *CardWriteResult
	Layout      *LayoutVerifyResult
	Image       *FlashResult
	FileVerify  *CardVerifyResult
	FileErr     error // 文件级校验本身出错 (无法挂载等)
	WriteTime   time.Duration
	VerifyTime  time.Duration
	SkippedZero int64
}

// OK 整体是否成功
func (o *FlashOutcome) OK() bool {
	if o == nil {
		return false
	}
	if o.IsCard {
		if o.Card == nil || o.Layout == nil || !o.Layout.OK() {
			return false
		}
		if o.FormatOnly {
			return true // 卡上本来就没有文件, 结构核对通过即算成功
		}
		return o.FileErr == nil && o.FileVerify != nil && o.FileVerify.OK()
	}
	return o.Image != nil && o.Image.VerifyOK
}

// RunFlash 执行完整写入流程 (含锁卷)。logf 可为 nil。
func RunFlash(d *DiskInfo, prep *PreparedSource, verify bool, cb Progress, logf func(string, ...interface{})) (*FlashOutcome, error) {
	log := func(format string, a ...interface{}) {
		if logf != nil {
			logf(format, a...)
		}
	}
	unlock, err := lockVolumes(d.Index, log)
	if err != nil {
		return nil, fmt.Errorf("锁定卷失败: %w", err)
	}
	defer unlock()

	out := &FlashOutcome{IsCard: prep.IsCard(), FormatOnly: prep.IsFormatOnly()}

	// ---- ① 写盘 ----
	dev, err := openDiskDevice(d.Path)
	if err != nil {
		return nil, err
	}
	if out.IsCard {
		res, werr := BuildCardOnDevice(dev, prep.Archive, prep.Plan, cb)
		out.Card = res
		if res != nil {
			out.SkippedZero = res.SkippedBytes
			out.WriteTime = res.Elapsed
		}
		if werr != nil {
			dev.Close()
			return out, werr
		}
		if out.FormatOnly {
			log("只格式化: 卡上建 MBR+FAT32, 实写 %s, 未触碰 %s (不写入任何文件)",
				HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes))
		} else {
			log("卡上直接建 FAT32: 实写 %s, 未触碰 %s (剩余空间不擦除, 快速格式化语义)",
				HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes))
		}
	} else {
		res, werr := Flash(dev, prep.Src, false, cb)
		out.Image = res
		if res != nil {
			out.WriteTime = res.WriteElapsed
			out.SkippedZero = res.SkippedBytes
		}
		if werr != nil {
			dev.Close()
			return out, werr
		}
		if res.SkippedBytes > 0 {
			log("整盘写入: 实写 %s, 全零块跳过 %s (卡上该处本就是零)",
				HumanBytes(res.WrittenBytes), HumanBytes(res.SkippedBytes))
		} else {
			log("整盘写入: %s", HumanBytes(res.WrittenBytes))
		}
	}

	// ---- ② 落盘: 冲刷设备缓存后关闭写句柄 ----
	if err := dev.Sync(); err != nil {
		dev.Close()
		return out, fmt.Errorf("刷盘失败 (数据可能仍在系统缓存里): %w", err)
	}
	// 收尾阶段的非致命告警 (设备不支持某条辅助指令等) 如实写进日志, 不静默吞掉
	if n, ok := dev.(syncNoter); ok {
		if note := n.SyncNote(); note != "" {
			log("提示: %s", note)
		}
	}
	if err := dev.Close(); err != nil {
		return out, fmt.Errorf("关闭设备失败: %w", err)
	}
	if !verify {
		return out, nil
	}

	// ---- ③ + ④ 换新句柄回读校验 ----
	tv := time.Now()
	dev2, err := openDiskDeviceRO(d.Path)
	if err != nil {
		return out, fmt.Errorf("写入已完成, 但重新打开设备校验失败: %w", err)
	}
	defer dev2.Close()

	if out.IsCard {
		lay, lerr := VerifyCardLayout(dev2, prep.Plan, cb)
		out.Layout = lay
		if lerr != nil {
			return out, lerr
		}
		if !lay.OK() {
			return out, fmt.Errorf("卡上文件系统结构核对失败: %v", lay.Problems)
		}
		log("回读校验: %s", lay.Summary())
		// ④ 文件级校验: 直接从卡上挂 FAT32 逐文件比对 (只格式化模式没有文件, 跳过)
		if prep.Archive != nil {
			log("文件级校验: 正在从卡上挂载 FAT32 并逐个文件比对…")
			fv, ferr := VerifyCardFiles(dev2, prep.Archive, 1, cb)
			out.FileVerify, out.FileErr = fv, ferr
			if ferr != nil {
				return out, ferr
			}
		}
	} else {
		if err := VerifyOnly(dev2, prep.Src, cb, out.Image); err != nil {
			return out, err
		}
	}
	out.VerifyTime = time.Since(tv)
	return out, nil
}

// syncNoter 可选接口: 收尾阶段产生了"不影响结果但要知道"的告警 (如设备不支持刷新缓存)
type syncNoter interface{ SyncNote() string }

// phaseName 进度阶段的中文名 (CLI 与 GUI 共用)
func phaseName(p string) string {
	switch p {
	case "verify":
		return "校验"
	case "skeleton":
		return "骨架"
	case "image":
		return "镜像"
	case "files":
		return "写文件"
	case "check":
		return "校验文件"
	case "hash":
		return "计算哈希"
	case "read":
		return "读取"
	case "scan":
		return "解析"
	}
	return "写入"
}
