package metrics

import (
	"strings"
	"testing"

	"bmssm/pkg/network"
)

// ---------------------------------------------------------------
// Disks — df -Tk 解析 /dev 非 loop 行：diskName/total/free/mountOn(MB) + readOnly
// ---------------------------------------------------------------

func TestDisks(t *testing.T) {
	dfOut := "Filesystem     Type     1K-blocks     Used Available Use% Mounted on\n" +
		"/dev/mmcblk0p7 ext4     96000000  2500000  86000000   3% /data\n" +
		"/dev/sda       ext4     491520000 60000000 389000000  13% /data2\n" +
		"/dev/loop0     squashfs  2000000   2000000  0  100% /snap (skip)\n"
	mounts := "/dev/mmcblk0p7 /data ext4 rw,relatime 0 0\n" +
		"/dev/sda /data2 ext4 ro,relatime 0 0\n"
	fr := &fakeFileReader{files: map[string]string{
		"/proc/mounts": mounts,
	}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"df": {dfOut, nil},
	}}
	c := NewCollector(fr, cmd)
	disks := c.Disks()

	if len(disks) != 2 {
		t.Fatalf("Disks() len = %d, want 2 (loop skipped)", len(disks))
	}
	// /dev/mmcblk0p7 → /data, rw
	// Total = Used+Avail = 2500000+86000000 = 88500000 KB → 88500000/1024 = 86425 MB
	// Free = Avail = 86000000 KB → 86000000/1024 = 83984 MB
	// usage = (1 - Free/Total)*100 ≈ (1 - 83984/86425)*100 ≈ 2.82% → 与 df Use% 3% 一致（非旧口径 10%）
	d0 := disks[0]
	if d0.DiskName != "/dev/mmcblk0" {
		t.Errorf("disk0.DiskName = %q, want /dev/mmcblk0 (aggregated)", d0.DiskName)
	}
	{
		wantTotal := float64((2500000 + 86000000) / 1024) // 86425
		if d0.Total != wantTotal {
			t.Errorf("disk0.Total = %v, want %v (Used+Avail)/1024 MB", d0.Total, wantTotal)
		}
	}
	if d0.Free != 83984 { // 86000000/1024 = 83984.375 → 83984
		t.Errorf("disk0.Free = %v, want 83984 (Avail/1024 MB)", d0.Free)
	}
	{
		usage := (1 - d0.Free/d0.Total) * 100
		if usage < 2.5 || usage > 3.5 {
			t.Errorf("disk0 usage = %.2f%%, want ~2.82%% (df Use%%=3%%)", usage)
		}
	}
	if d0.MountOn != "/data" {
		t.Errorf("disk0.MountOn = %q, want /data", d0.MountOn)
	}
	if d0.ReadOnly != 0 {
		t.Errorf("disk0.ReadOnly = %d, want 0 (rw)", d0.ReadOnly)
	}
	// /dev/sda → /data2, ro
	// Total = Used+Avail = 60000000+389000000 = 449000000 KB → 438476 MB
	// Free = Avail = 389000000 KB → 379882 MB
	// usage = (1 - 379882/438476)*100 ≈ 13.36% → 与 df Use% 13% 一致
	d1 := disks[1]
	if d1.DiskName != "/dev/sda" {
		t.Errorf("disk1.DiskName = %q, want /dev/sda", d1.DiskName)
	}
	{
		wantTotal := float64((60000000 + 389000000) / 1024) // 438476
		if d1.Total != wantTotal {
			t.Errorf("disk1.Total = %v, want %v (Used+Avail)/1024 MB", d1.Total, wantTotal)
		}
	}
	if d1.Free != float64(389000000/1024) { // 379882
		t.Errorf("disk1.Free = %v, want %v (Avail/1024 MB)", d1.Free, float64(389000000/1024))
	}
	{
		usage := (1 - d1.Free/d1.Total) * 100
		if usage < 12.5 || usage > 14.5 {
			t.Errorf("disk1 usage = %.2f%%, want ~13.36%% (df Use%%=13%%)", usage)
		}
	}
	if d1.MountOn != "/data2" {
		t.Errorf("disk1.MountOn = %q, want /data2", d1.MountOn)
	}
	if d1.ReadOnly != 1 {
		t.Errorf("disk1.ReadOnly = %d, want 1 (ro)", d1.ReadOnly)
	}
}

// TestDisksOverlayRoot 锁定 SE9 场景：/ 是 overlay（upperdir 在 /dev/mmcblk0p5 上），
// 整片 eMMC 多分区应聚合为单条 /dev/mmcblk0，MountOn="/" 并排首位；overlay 不单独入表。
// /dev/sda1（外置存储）单独一条。期望"硬盘空间"= 整片 eMMC 而非 overlay 的 8.66GB。
func TestDisksOverlayRoot(t *testing.T) {
	dfOut := "Filesystem     Type    1K-blocks    Used Available Use% Mounted on\n" +
		"overlay        overlay   9079836 1461428   7222796  17% /\n" +
		"/dev/sda1      ext4    967827868   77856 917723468   1% /media/storage-local-sda1\n" +
		"/dev/mmcblk0p1 vfat       130798   20264    110534  16% /boot\n" +
		"/dev/mmcblk0p6 ext4     17476668 1193448  15553672   8% /data\n" +
		"/dev/mmcblk0p4 ext4      3030800 2727684    129448  96% /media/root-ro\n" +
		"/dev/mmcblk0p5 ext4      9079836 1461428   7222796  17% /media/root-rw\n" +
		"/dev/mmcblk0p2 ext4       110576   20940     84940  20% /recovery\n"
	mounts := "overlay / overlay rw,relatime,lowerdir=/media/root-ro,upperdir=/media/root-rw/overlay,workdir=/media/root-rw/overlay-workdir 0 0\n" +
		"/dev/sda1 /media/storage-local-sda1 ext4 rw,relatime 0 0\n" +
		"/dev/mmcblk0p1 /boot vfat rw,relatime 0 0\n" +
		"/dev/mmcblk0p6 /data ext4 rw,relatime 0 0\n" +
		"/dev/mmcblk0p4 /media/root-ro ext4 ro,relatime 0 0\n" +
		"/dev/mmcblk0p5 /media/root-rw ext4 rw,relatime 0 0\n" +
		"/dev/mmcblk0p2 /recovery ext4 rw,relatime 0 0\n"
	fr := &fakeFileReader{files: map[string]string{"/proc/mounts": mounts}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"df": {dfOut, nil}}}
	c := NewCollector(fr, cmd)
	disks := c.Disks()

	// 期望两条：/dev/mmcblk0（聚合 p1/p2/p4/p5/p6，MountOn=/）+ /dev/sda（外置）
	if len(disks) != 2 {
		t.Fatalf("Disks() len = %d, want 2 (overlay 不单独入表)", len(disks))
	}
	root := disks[0]
	if root.DiskName != "/dev/mmcblk0" {
		t.Errorf("disk0.DiskName = %q, want /dev/mmcblk0", root.DiskName)
	}
	if root.MountOn != "/" {
		t.Errorf("disk0.MountOn = %q, want / (根设备)", root.MountOn)
	}
	// 总 = 各 mmcblk0p 分区 (Used+Avail) 之和 /1024（ssm 口径=Used+Avail，不含 ext4 reserved）
	// p1:20264+110534 p6:1193448+15553672 p4:2727684+129448 p5:1461428+7222796 p2:20940+84940
	wantTotalKB := int64(130798 + 16747120 + 2857132 + 8684224 + 105880)
	wantTotal := float64(wantTotalKB / 1024)
	if root.Total != wantTotal {
		t.Errorf("disk0.Total = %v, want %v (整片 eMMC 聚合)", root.Total, wantTotal)
	}
	// 整片 eMMC 应明显大于 overlay 单独的 ~8856MB（9079836KB/1024）
	if root.Total <= 8856 {
		t.Errorf("disk0.Total = %v, 应大于 overlay 单独的 ~8856MB（整片 eMMC）", root.Total)
	}
	// root-ro (p4) 是 ro，但 p5/p6 是 rw → 聚合 ReadOnly=0
	if root.ReadOnly != 0 {
		t.Errorf("disk0.ReadOnly = %d, want 0 (p5/p6 rw → 非 all-ro)", root.ReadOnly)
	}
	sda := disks[1]
	if sda.DiskName != "/dev/sda" {
		t.Errorf("disk1.DiskName = %q, want /dev/sda", sda.DiskName)
	}
}

func TestDisksEmpty(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/mounts": ""}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"df": {"", nil},
	}}
	c := NewCollector(fr, cmd)
	if got := c.Disks(); len(got) != 0 {
		t.Errorf("Disks() len = %d, want 0 when empty", len(got))
	}
}

func TestDisksDfFails(t *testing.T) {
	fr := &fakeFileReader{files: map[string]string{"/proc/mounts": ""}}
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{
		"df": {"", errSome},
	}}
	c := NewCollector(fr, cmd)
	if got := c.Disks(); len(got) != 0 {
		t.Errorf("Disks() len = %d, want 0 when df fails", len(got))
	}
}

// TestDiskLayout 覆盖 eMMC 整体 + 各分区（排除 p3/p4，按分区号升序）。
func TestDiskLayout(t *testing.T) {
	dfOut := "Filesystem     Type    1K-blocks    Used Available Use% Mounted on\n" +
		"overlay        overlay   9079836 1461428   7222796  17% /\n" +
		"/dev/sda1      ext4    967827868   77856 917723468   1% /media/storage-local-sda1\n" +
		"/dev/mmcblk0p1 vfat       130798   20264    110534  16% /boot\n" +
		"/dev/mmcblk0p6 ext4     17476668 1193448  15553672   8% /data\n" +
		"/dev/mmcblk0p4 ext4      3030800 2727684    129448  96% /media/root-ro\n" +
		"/dev/mmcblk0p5 ext4      9079836 1461428   7222796  17% /media/root-rw\n" +
		"/dev/mmcblk0p2 ext4       110576   20940     84940  20% /recovery\n"
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"df": {dfOut, nil}}}
	c := NewCollector(&fakeFileReader{files: map[string]string{}}, cmd)
	lay := c.DiskLayout()

	// eMMC 整体 = p1+p2+p4+p5+p6 的 (used,avail) 之和（含被排除的 p4）
	// usedKB = 20264+20940+2727684+1461428+1193448 = 5423764 → 5296.6 MB
	// totalKB = 5423764 + (110534+84940+129448+7222796+15553672) = 28525154 → 27856.6 MB
	if !approxEqual(lay.EmmcOverall.UsedMB, 5296.6, 1) {
		t.Errorf("EmmcOverall.UsedMB = %v, want ~5296.6", lay.EmmcOverall.UsedMB)
	}
	if !approxEqual(lay.EmmcOverall.TotalMB, 27856.6, 1) {
		t.Errorf("EmmcOverall.TotalMB = %v, want ~27856", lay.EmmcOverall.TotalMB)
	}
	if !approxEqual(lay.EmmcOverall.UsagePct, 19.0, 0.5) {
		t.Errorf("EmmcOverall.UsagePct = %v, want ~19", lay.EmmcOverall.UsagePct)
	}
	// 分区列表：p1/p2/p5/p6（排除 p3/p4，overlay 不入列表），按分区号升序
	if len(lay.Partitions) != 4 {
		t.Fatalf("Partitions len = %d, want 4 (p1/p2/p5/p6)", len(lay.Partitions))
	}
	want := []struct {
		dev, mount  string
		used, total float64
	}{
		{"/dev/mmcblk0p1", "/boot", 19.8, 128.1},
		{"/dev/mmcblk0p2", "/recovery", 20.4, 103.5},
		{"/dev/mmcblk0p5", "/media/root-rw", 1427.2, 8480.7},
		{"/dev/mmcblk0p6", "/data", 1165.5, 16354.6},
	}
	for i, w := range want {
		p := lay.Partitions[i]
		if p.Device != w.dev || p.MountOn != w.mount {
			t.Errorf("part[%d] = %s %s, want %s %s", i, p.Device, p.MountOn, w.dev, w.mount)
		}
		if !approxEqual(p.UsedMB, w.used, 0.5) {
			t.Errorf("part[%s].UsedMB = %v, want ~%v", w.mount, p.UsedMB, w.used)
		}
		if !approxEqual(p.TotalMB, w.total, 0.5) {
			t.Errorf("part[%s].TotalMB = %v, want ~%v", w.mount, p.TotalMB, w.total)
		}
	}
	// 关键：p4(root-ro) 被排除
	for _, p := range lay.Partitions {
		if strings.HasSuffix(p.Device, "p4") || strings.HasSuffix(p.Device, "p3") {
			t.Errorf("p3/p4 不应在分区列表：%s", p.Device)
		}
	}
}

func TestDiskLayoutNoData(t *testing.T) {
	// 无 mmcblk0 分区 → 整体全 0、列表空
	dfOut := "Filesystem Type 1K-blocks Used Available Use% Mounted on\n" +
		"overlay overlay 100 10 90 10% /\n"
	cmd := &fakeCmdRunner{responses: map[string]cmdResp{"df": {dfOut, nil}}}
	c := NewCollector(&fakeFileReader{files: map[string]string{}}, cmd)
	lay := c.DiskLayout()
	if lay.EmmcOverall.TotalMB != 0 || len(lay.Partitions) != 0 {
		t.Errorf("无 eMMC 时应整体 0 + 空列表，got %+v", lay)
	}
}

// ---------------------------------------------------------------
// mapNetCards — network.NetCard + sysfs → metrics.NetCard
// ---------------------------------------------------------------

func TestMapNetCards(t *testing.T) {
	cards := []network.NetCard{
		{Name: "eth0", IPs: []string{"192.168.1.100/24"}, MAC: "00:11:22:33:44:55"},
	}
	fr := &fakeFileReader{files: map[string]string{
		"/sys/class/net/eth0/statistics/tx_bytes": "123456\n",
		"/sys/class/net/eth0/statistics/rx_bytes": "654321\n",
		"/sys/class/net/eth0/speed":               "1000\n",
	}}
	c := NewCollector(fr, nil)
	got := c.mapNetCards(cards)
	if len(got) != 1 {
		t.Fatalf("mapNetCards len = %d, want 1", len(got))
	}
	nc := got[0]
	if nc.Name != "eth0" {
		t.Errorf("Name = %q, want eth0", nc.Name)
	}
	if nc.IP != "192.168.1.100" {
		t.Errorf("IP = %q, want 192.168.1.100 (CIDR stripped)", nc.IP)
	}
	if nc.Mask != "255.255.255.0" {
		t.Errorf("Mask = %q, want 255.255.255.0", nc.Mask)
	}
	if nc.Mac != "00:11:22:33:44:55" {
		t.Errorf("Mac = %q", nc.Mac)
	}
	if nc.Bandwidth != 1000 {
		t.Errorf("Bandwidth = %d, want 1000", nc.Bandwidth)
	}
	if nc.NetTx != 123456 {
		t.Errorf("NetTx = %v, want 123456", nc.NetTx)
	}
	if nc.NetRx != 654321 {
		t.Errorf("NetRx = %v, want 654321", nc.NetRx)
	}
}

func TestMapNetCardsLoopbackSkipped(t *testing.T) {
	cards := []network.NetCard{
		{Name: "lo", IPs: []string{"127.0.0.1/8"}, MAC: "", IsLoopback: true},
		{Name: "eth0", IPs: []string{"10.0.0.1/8"}, MAC: "aa:bb:cc:dd:ee:ff"},
	}
	fr := &fakeFileReader{files: map[string]string{}}
	c := NewCollector(fr, nil)
	got := c.mapNetCards(cards)
	if len(got) != 1 {
		t.Fatalf("mapNetCards len = %d, want 1 (loopback skipped)", len(got))
	}
	if got[0].Name != "eth0" {
		t.Errorf("Name = %q, want eth0", got[0].Name)
	}
}
