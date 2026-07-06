package metrics

import (
	"testing"

	"ssm/pkg/network"
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
	if d0.DiskName != "/dev/mmcblk0p7" {
		t.Errorf("disk0.DiskName = %q, want /dev/mmcblk0p7", d0.DiskName)
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
