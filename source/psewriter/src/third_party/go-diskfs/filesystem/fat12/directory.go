package fat12

import (
	"fmt"
	"strings"

	"github.com/diskfs/go-diskfs/util/timestamp"
)

// Directory represents a single directory in a FAT12/FAT16 filesystem
type Directory struct {
	directoryEntry
	entries []*directoryEntry
}

// dirEntriesFromBytes loads the directory entries from the raw bytes
func (d *Directory) entriesFromBytes(b []byte) error {
	entries, err := parseDirEntries(b)
	if err != nil {
		return err
	}
	d.entries = entries
	return nil
}

// entriesToBytes convert our entries to raw bytes, padded to a multiple of bytesPerCluster.
func (d *Directory) entriesToBytes(bytesPerCluster int) ([]byte, error) {
	b := make([]byte, 0)
	for _, de := range d.entries {
		b2, err := de.toBytes()
		if err != nil {
			return nil, err
		}
		b = append(b, b2...)
	}
	remainder := len(b) % bytesPerCluster
	if remainder != 0 {
		zeroes := make([]byte, bytesPerCluster-remainder)
		b = append(b, zeroes...)
	}
	return b, nil
}

// entriesToBytesFixed serialises entries into a fixed-size buffer of exactly fixedSize bytes.
// Used for the FAT12/16 root directory region which has a pre-allocated fixed size.
func (d *Directory) entriesToBytesFixed(fixedSize int) ([]byte, error) {
	b := make([]byte, fixedSize)
	offset := 0
	for _, de := range d.entries {
		b2, err := de.toBytes()
		if err != nil {
			return nil, err
		}
		if offset+len(b2) > fixedSize {
			return nil, fmt.Errorf("root directory is full: exceeds fixed size of %d bytes", fixedSize)
		}
		copy(b[offset:], b2)
		offset += len(b2)
	}
	return b, nil
}

// uniqueShortName finds the lowest available numeric-tail short name for the
// given base stem and extension, scanning the provided entries for conflicts.
//
// stem must already be upper-cased and contain only valid 8.3 characters; it
// will be truncated as needed to make room for the tail.  ext is the 0–3 char
// extension (without the dot), also already upper-cased.
//
// The FAT spec numeric-tail algorithm:
//
//	counter 1–9   → stem truncated to 6 chars + "~N"   (total 8 chars)
//	counter 10–99  → stem truncated to 5 chars + "~NN"
//	counter 100–999 → stem truncated to 4 chars + "~NNN"
//	…and so on.
func uniqueShortName(stem, ext string, entries []*directoryEntry) string {
	// Build a set of the existing short names (already uppercase on disk).
	existing := make(map[string]struct{}, len(entries))
	for _, e := range entries {
		if e.isVolumeLabel {
			continue
		}
		existing[e.filenameShort+e.fileExtension] = struct{}{}
	}

	for counter := 1; counter <= 999999; counter++ {
		suffix := fmt.Sprintf("~%d", counter)
		maxStem := 8 - len(suffix)
		s := stem
		if len(s) > maxStem {
			s = s[:maxStem]
		}
		candidate := s + suffix
		if _, clash := existing[candidate+ext]; !clash {
			return candidate
		}
	}
	// Unreachable in practice.
	return stem[:6] + "~1"
}

// shortNameInUse reports whether the 8.3 pair (stem, ext) is already taken by an
// entry of this directory.  PATCH(setf): used to decide whether a *legal* 8.3
// short name (one that was not mangled, e.g. the "FIP"+"BIN" of "fip.bin") may be
// used as-is or has to fall back to a "~N" tail.  Comparison is ASCII
// case-insensitive and tolerant of the space padding found in entries read back
// from disk.
func shortNameInUse(stem, ext string, entries []*directoryEntry) bool {
	for _, e := range entries {
		if e.isVolumeLabel {
			continue
		}
		if strings.EqualFold(strings.TrimRight(e.filenameShort, " "), stem) &&
			strings.EqualFold(strings.TrimRight(e.fileExtension, " "), ext) {
			return true
		}
	}
	return false
}

// createEntry creates an entry in the given directory and returns a handle to it.
func (d *Directory) createEntry(name string, cluster uint32, dir bool) (*directoryEntry, error) {
	shortName, extension, isLFN, isTruncated, isRewritten := convertLfnSfn(name)

	// When the stem was longer than 8 characters, convertLfnSfn emits "~1" as
	// the numeric tail unconditionally.  We must find the lowest tail value
	// that does not clash with any existing entry in this directory.
	// PATCH(setf): 原实现只在"名字超长被截断"(isTruncated) 时去重。但名字被**改写**过
	// 也(可能)产生冲突 —— 例如 "中文.bin" 与 "英文.bin" 的短名都会被改写成同一串下划线,
	// 不用 ~N 去重就会在同一个目录里出现两个相同的 8.3 短名 (非法目录结构)。
	//
	// PATCH(setf) 第二次修正 —— 短名不能被无条件加 ~N: isLFN 只表示"需要一条 LFN 条目来
	// 保存原始名字", 其中最常见的触发条件仅仅是**大小写不同**("fip.bin" → 短名 "FIP.BIN")。
	// 这类名字的短名本来就是完全合法的 8.3, Windows 也只会写 "FIP.BIN", 不会写 "FIP~1.BIN"。
	// 之前凡是 isLFN 就走 uniqueShortName, 于是所有小写 8.3 文件都拿到了 ~1 退化短名 ——
	// 而 BM1684X 的 BL1 (trusted-firmware-a) 编译时 FF_USE_LFN=0, 只认短名, 它查
	// "0:fip.bin" 时匹配的是 "FIP     BIN", 因此卡上明明有 fip.bin 也会报
	// "fip not found on SD" 并回退到板载 SPI flash。
	// 现在的判据: 只有在短名**确实被改写**(isRewritten) 或与同目录已有条目**真的撞名**时,
	// 才退化成带 ~N 的短名。
	if isTruncated {
		// The base stem is the first 6 characters of the short name returned
		// by convertLfnSfn (which is always stem[:6]+"~1" when truncated).
		stem := shortName[:6]
		shortName = uniqueShortName(stem, extension, d.entries)
		isLFN = true
	} else if isLFN && (isRewritten || shortNameInUse(shortName, extension, d.entries)) {
		stem := shortName
		if len(stem) > 6 {
			stem = stem[:6]
		}
		if stem == "" {
			stem = "_"
		}
		shortName = uniqueShortName(stem, extension, d.entries)
	}

	lfn := ""
	if isLFN {
		lfn = name
	}

	ts := timestamp.GetTime()

	entry := directoryEntry{
		filenameLong:      lfn,
		longFilenameSlots: -1, // will be recalculated
		filenameShort:     shortName,
		fileExtension:     extension,
		fileSize:          0,
		clusterLocation:   cluster,
		filesystem:        d.filesystem,
		createTime:        ts,
		modifyTime:        ts,
		accessTime:        ts,
		isSubdirectory:    dir,
		isNew:             true,
	}
	entry.longFilenameSlots = calculateSlots(entry.filenameLong)
	d.entries = append(d.entries, &entry)
	return &entry, nil
}

// removeEntry removes the entry that matches name (matched by long filename or
// 8.3 short name, case-insensitively) from the directory.
func (d *Directory) removeEntry(name string) error {
	removeEntryIndex := -1
	for i, entry := range d.entries {
		if entry.nameMatches(name) {
			removeEntryIndex = i
			break
		}
	}
	if removeEntryIndex == -1 {
		return fmt.Errorf("cannot find entry for name %s", name)
	}
	d.entries = append(d.entries[:removeEntryIndex], d.entries[removeEntryIndex+1:]...)
	return nil
}

// renameEntry renames the entry that matches oldFileName to newFileName.
// Both names are matched case-insensitively against long and short filenames.
// If newFileName already exists in the directory, that entry is replaced
// (mirroring the behaviour of os.Rename on most operating systems).
// When the new short name must be generated and would conflict with an existing
// entry, a unique numeric tail is assigned — excluding the old entry itself
// from the conflict set, since it is being replaced.
func (d *Directory) renameEntry(oldFileName, newFileName string) error {
	// Build the short name for the new filename before we start mutating entries.
	newShort, newExt, newIsLFN, newIsTruncated, _ := convertLfnSfn(newFileName)
	if newIsTruncated {
		// Exclude the entry being renamed from the conflict scan: after the
		// rename completes its current short name slot will be vacated.
		var filtered []*directoryEntry
		for _, e := range d.entries {
			if !e.nameMatches(oldFileName) {
				filtered = append(filtered, e)
			}
		}
		newShort = uniqueShortName(newShort[:6], newExt, filtered)
		newIsLFN = true
	}
	newLFN := ""
	if newIsLFN {
		newLFN = newFileName
	}

	newEntries := make([]*directoryEntry, 0, len(d.entries))
	isReplaced := false
	for _, entry := range d.entries {
		// Drop any existing entry that has the new name (it is overwritten).
		if entry.nameMatches(newFileName) {
			continue
		}
		if entry.nameMatches(oldFileName) {
			entry.filenameLong = newLFN
			entry.filenameShort = newShort
			entry.fileExtension = newExt
			entry.longFilenameSlots = calculateSlots(newLFN)
			entry.modifyTime = timestamp.GetTime()
			isReplaced = true
		}
		newEntries = append(newEntries, entry)
	}
	if !isReplaced {
		return fmt.Errorf("cannot find file entry for %s", oldFileName)
	}
	d.entries = newEntries
	return nil
}

// createVolumeLabel creates a volume label entry in the directory.
func (d *Directory) createVolumeLabel(name string) (*directoryEntry, error) {
	ts := timestamp.GetTime()
	entry := directoryEntry{
		filenameLong:      "",
		longFilenameSlots: -1,
		filenameShort:     name[:8],
		fileExtension:     name[8:11],
		fileSize:          0,
		clusterLocation:   0,
		filesystem:        d.filesystem,
		createTime:        ts,
		modifyTime:        ts,
		accessTime:        ts,
		isSubdirectory:    false,
		isNew:             true,
		isVolumeLabel:     true,
	}
	d.entries = append(d.entries, &entry)
	return &entry, nil
}
