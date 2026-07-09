package metrics

import (
	"testing"
)

func TestCalcCPUFullDelta(t *testing.T) {
	// 模拟 /proc/stat 双采样：1 核 + aggregate
	t0 := "cpu  100 10 50 200 5 2 1 0 0 0\ncpu0 100 10 50 200 5 2 1 0 0 0\n"
	t1 := "cpu  200 20 100 400 10 4 2 0 0 0\ncpu0 200 20 100 400 10 4 2 0 0 0\n"

	usage, perCPU := calcCPUFullDelta(t0, t1)
	// total fields: user+nice+sys+idle+iowait+irq+softirq
	// t0 tot=100+10+50+200+5+2+1=368, idle=200
	// t1 tot=200+20+100+400+10+4+2=736, idle=400
	// dt=368, di=200, usage=(368-200)/368*100=45.65%
	if usage < 45.0 || usage > 46.0 {
		t.Errorf("CPU usage = %f, want ~45.65", usage)
	}
	if len(perCPU) != 1 {
		t.Fatalf("perCPU len = %d, want 1", len(perCPU))
	}
	if perCPU[0].Usage < 45.0 || perCPU[0].Usage > 46.0 {
		t.Errorf("CPU0 usage = %f, want ~45.65", perCPU[0].Usage)
	}
}

func TestCalcNetDelta(t *testing.T) {
	// 不需要真 /sys/class/net 设备，用 lo（会跳过，结果为空）
	t0 := " lo: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
	t1 := " lo: 2000 0 0 0 0 0 0 0 4000 0 0 0 0 0 0 0\n"

	out := calcNetDelta(t0, t1)
	// lo is excluded by device check (skip loopback), so result should be empty
	if len(out) > 0 {
		t.Errorf("expected empty net delta (lo excluded), got %d entries", len(out))
	}
}

func TestCalcDiskDelta(t *testing.T) {
	// 用 fake disk name
	t0 := "1 0 mmcblk0 0 0 0 1000 0 0 0 2000 0 0 0 0 0 0\n"
	t1 := "1 0 mmcblk0 0 0 0 2000 0 0 0 4000 0 0 0 0 0 0\n"

	out := calcDiskDelta(t0, t1)
	// mmcblk0 may not exist in test env → result likely empty
	// 只验证无 panic
	_ = out
}

func TestParseStatLines(t *testing.T) {
	content := "cpu  1 2 3 4 5 6 7 0 0 0\ncpu0 1 2 3 4 5 6 7 0 0 0\n"
	m := parseStatLines(content)
	if m["cpu"].total != 1+2+3+4+5+6+7 {
		t.Errorf("cpu total = %d, want %d", m["cpu"].total, 28)
	}
	if m["cpu"].idle != 4 {
		t.Errorf("cpu idle = %d, want 4", m["cpu"].idle)
	}
	if len(m) != 2 {
		t.Errorf("len = %d, want 2", len(m))
	}
}

func TestParseNetDev(t *testing.T) {
	content := "eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
	m := parseNetDev(content)
	if m["eth0"].rx != 1000 {
		t.Errorf("rx = %d, want 1000", m["eth0"].rx)
	}
	if m["eth0"].tx != 2000 {
		t.Errorf("tx = %d, want 2000", m["eth0"].tx)
	}
}
