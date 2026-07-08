package alarm

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"bmssm/pkg/metrics"
)

// ---------------------------------------------------------------
// 测试夹具：fake metrics / subs / poster
// ---------------------------------------------------------------

type fakeMetrics struct {
	cpu       metrics.CPU
	mem       metrics.Memory
	disks     []metrics.Disk
	chipTemp  int
	boardTemp int
	tpuUsage  int
}

func (f *fakeMetrics) CPUInfo() metrics.CPU          { return f.cpu }
func (f *fakeMetrics) Memory() metrics.Memory        { return f.mem }
func (f *fakeMetrics) Disks() []metrics.Disk         { return f.disks }
func (f *fakeMetrics) ChipTemp() int                 { return f.chipTemp }
func (f *fakeMetrics) BoardTemp() int                { return f.boardTemp }
func (f *fakeMetrics) TPUUsage() int                 { return f.tpuUsage }

type fakeSubs struct {
	urls []string
}

func (f *fakeSubs) CallbackURLs() []string { return f.urls }

type recordedPost struct {
	url     string
	payload AlarmRec
}

type fakePoster struct {
	posts []recordedPost
	err   error
}

func (f *fakePoster) Post(url string, payload []byte) error {
	if f.err != nil {
		return f.err
	}
	var rec AlarmRec
	_ = json.Unmarshal(payload, &rec)
	f.posts = append(f.posts, recordedPost{url: url, payload: rec})
	return nil
}

func baseThresholds() Thresholds {
	return Thresholds{
		CpuRate:          95,
		TotalMemoryScale: 95,
		DiskRate:         95,
		BoardTemperature: 90,
		CoreTemperature:  90,
		TpuRate:          95,
	}
}

func newTestEngine(m MetricsReader, urls []string, p Poster) (*Engine, *fakePoster) {
	fp := &fakePoster{}
	if p != nil {
		fp = p.(*fakePoster)
	}
	e := NewEngine(m, &fakeSubs{urls: urls}, fp, baseThresholds(),
		"DEV-SN-001", "BOARD-SN-001", "CHIP-SN-001")
	e.now = func() time.Time { return time.Date(2026, 7, 3, 10, 0, 0, 0, time.UTC) }
	return e, fp
}

// ---------------------------------------------------------------
// 测试用例
// ---------------------------------------------------------------

// TestTick_CPUOverThreshold_PostsNegativeCode：CPU 超限 → 发负 code、ComponentType=1。
func TestTick_CPUOverThreshold_PostsNegativeCode(t *testing.T) {
	m := &fakeMetrics{cpu: metrics.CPU{UtilizationRate: 99}}
	e, fp := newTestEngine(m, []string{"http://callback/alarm"}, nil)

	e.Tick()

	if len(fp.posts) != 1 {
		t.Fatalf("expect 1 post, got %d", len(fp.posts))
	}
	p := fp.posts[0]
	if p.url != "http://callback/alarm" {
		t.Errorf("url mismatch: %s", p.url)
	}
	if p.payload.Code != CodeCPURateAlarm {
		t.Errorf("code: got %d want %d", p.payload.Code, CodeCPURateAlarm)
	}
	if p.payload.ComponentType != 1 {
		t.Errorf("componentType: got %d want 1", p.payload.ComponentType)
	}
	if p.payload.DeviceSn != "DEV-SN-001" {
		t.Errorf("deviceSn: %s", p.payload.DeviceSn)
	}
	if p.payload.BoardSn != "BOARD-SN-001" {
		t.Errorf("boardSn: %s", p.payload.BoardSn)
	}
	if !strings.Contains(p.payload.Msg, "cpu使用率过高") {
		t.Errorf("msg: %s", p.payload.Msg)
	}
	if !strings.Contains(p.payload.Msg, "99") {
		t.Errorf("msg should contain value 99: %s", p.payload.Msg)
	}
	if p.payload.DateTime != "2026-07-03 10:00:00" {
		t.Errorf("dateTime: %s", p.payload.DateTime)
	}
	// CPU 告警不带 chipSn/diskName
	if p.payload.ChipSn != "" || p.payload.DiskName != "" {
		t.Errorf("cpu alarm should have empty chipSn/diskName: chip=%s disk=%s", p.payload.ChipSn, p.payload.DiskName)
	}
}

// TestTick_NoBreach_NoPost：所有指标正常 → 不 POST。
func TestTick_NoBreach_NoPost(t *testing.T) {
	m := &fakeMetrics{
		cpu:       metrics.CPU{UtilizationRate: 30},
		mem:       metrics.Memory{Total: 1000, Available: 800},
		disks:     []metrics.Disk{{DiskName: "/dev/sda1", Total: 1000, Free: 800, MountOn: "/"}},
		chipTemp:  50,
		boardTemp: 50,
		tpuUsage:  30,
	}
	e, fp := newTestEngine(m, []string{"http://callback/alarm"}, nil)

	e.Tick()

	if len(fp.posts) != 0 {
		t.Fatalf("expect 0 posts, got %d: %+v", len(fp.posts), fp.posts)
	}
}

// TestTick_Recovery_PostsPositiveCode：先超限发负 code，恢复后发正 code（value=-1, boardSn 空）。
func TestTick_Recovery_PostsPositiveCode(t *testing.T) {
	m := &fakeMetrics{cpu: metrics.CPU{UtilizationRate: 99}}
	e, fp := newTestEngine(m, []string{"http://cb/alarm"}, nil)

	e.Tick() // 超限 → -101001
	if len(fp.posts) != 1 || fp.posts[0].payload.Code != CodeCPURateAlarm {
		t.Fatalf("first tick should post alarm: %+v", fp.posts)
	}

	// 恢复
	m.cpu.UtilizationRate = 30
	e.Tick()

	// 第二次应有恢复事件
	var recovery *recordedPost
	for i := range fp.posts {
		if fp.posts[i].payload.Code == CodeCPURateRecover {
			recovery = &fp.posts[i]
			break
		}
	}
	if recovery == nil {
		t.Fatalf("expect recovery post, got: %+v", fp.posts)
	}
	if recovery.payload.BoardSn != "" || recovery.payload.ChipSn != "" || recovery.payload.DiskName != "" {
		t.Errorf("recovery should have empty boardSn/chipSn/diskName: %+v", recovery.payload)
	}
	if !strings.Contains(recovery.payload.Msg, "恢复") {
		t.Errorf("recovery msg: %s", recovery.payload.Msg)
	}
}

// TestTick_NoSubscriptions_NoPost：无订阅即使超限也不 POST（不报错）。
func TestTick_NoSubscriptions_NoPost(t *testing.T) {
	m := &fakeMetrics{cpu: metrics.CPU{UtilizationRate: 99}}
	e, fp := newTestEngine(m, nil, nil)

	e.Tick()

	if len(fp.posts) != 0 {
		t.Fatalf("expect 0 posts with no subs, got %d", len(fp.posts))
	}
}

// TestTick_DiskOverThreshold_PostsWithDiskName_SkipsBootAndReadOnly：
// 磁盘超限带 diskName；/boot 与 ReadOnly 跳过。
func TestTick_DiskOverThreshold_PostsWithDiskName_SkipsBootAndReadOnly(t *testing.T) {
	m := &fakeMetrics{
		disks: []metrics.Disk{
			{DiskName: "/dev/sda1", Total: 1000, Free: 10, MountOn: "/"},          // 99% → 告警
			{DiskName: "/dev/sda2", Total: 1000, Free: 10, MountOn: "/boot"},      // 跳过
			{DiskName: "/dev/sda3", Total: 1000, Free: 10, MountOn: "/recovery"},  // 跳过
			{DiskName: "/dev/sda4", Total: 1000, Free: 10, MountOn: "/data", ReadOnly: 1}, // 跳过
		},
	}
	e, fp := newTestEngine(m, []string{"http://cb/alarm"}, nil)

	e.Tick()

	if len(fp.posts) != 1 {
		t.Fatalf("expect 1 post (only /), got %d: %+v", len(fp.posts), fp.posts)
	}
	p := fp.posts[0]
	if p.payload.Code != CodeDiskRateAlarm {
		t.Errorf("code: %d", p.payload.Code)
	}
	if p.payload.DiskName != "/dev/sda1" {
		t.Errorf("diskName: %s", p.payload.DiskName)
	}
	if p.payload.ComponentType != 1 {
		t.Errorf("componentType: %d", p.payload.ComponentType)
	}
}

// TestTick_TemperaturesAndTPU_PostsComponentType2：板温/芯片温/TPU 超限 → ComponentType=2。
func TestTick_TemperaturesAndTPU_PostsComponentType2(t *testing.T) {
	m := &fakeMetrics{
		boardTemp: 95,
		chipTemp:  95,
		tpuUsage:  99,
	}
	e, fp := newTestEngine(m, []string{"http://cb/alarm"}, nil)

	e.Tick()

	if len(fp.posts) != 3 {
		t.Fatalf("expect 3 posts (board/chip/tpu), got %d: %+v", len(fp.posts), fp.posts)
	}
	seen := map[int]bool{}
	for _, p := range fp.posts {
		if p.payload.ComponentType != 2 {
			t.Errorf("componentType: got %d want 2", p.payload.ComponentType)
		}
		// 芯片类告警（芯片温/TPU）带 chipSn；板温告警 chipSn 空（对齐 bmssm）
		switch p.payload.Code {
		case CodeChipTempAlarm, CodeTPURateAlarm:
			if p.payload.ChipSn != "CHIP-SN-001" {
				t.Errorf("chip alarm should have chipSn: %s", p.payload.ChipSn)
			}
		case CodeBoardTempAlarm:
			if p.payload.ChipSn != "" {
				t.Errorf("board temp alarm should have empty chipSn: %s", p.payload.ChipSn)
			}
		}
		seen[p.payload.Code] = true
	}
	if !seen[CodeBoardTempAlarm] || !seen[CodeChipTempAlarm] || !seen[CodeTPURateAlarm] {
		t.Errorf("missing expected codes, seen: %v", seen)
	}
}

// TestTick_MemoryOverThreshold：内存超限 → -102001。
func TestTick_MemoryOverThreshold(t *testing.T) {
	// Avail=10, Total=1000 → usage = 99% > 95
	m := &fakeMetrics{mem: metrics.Memory{Total: 1000, Available: 10}}
	e, fp := newTestEngine(m, []string{"http://cb/alarm"}, nil)

	e.Tick()

	if len(fp.posts) != 1 {
		t.Fatalf("expect 1 post, got %d", len(fp.posts))
	}
	if fp.posts[0].payload.Code != CodeMemRateAlarm {
		t.Errorf("code: got %d want %d", fp.posts[0].payload.Code, CodeMemRateAlarm)
	}
	if fp.posts[0].payload.ComponentType != 1 {
		t.Errorf("componentType: %d", fp.posts[0].payload.ComponentType)
	}
}

// TestTick_PostErrorDoesNotBlock：Poster 返回错误时不 panic、不阻断后续。
func TestTick_PostErrorDoesNotBlock(t *testing.T) {
	m := &fakeMetrics{cpu: metrics.CPU{UtilizationRate: 99}}
	fp := &fakePoster{err: errPostFailed}
	e := NewEngine(m, &fakeSubs{urls: []string{"http://cb/alarm", "http://cb2/alarm"}}, fp,
		baseThresholds(), "DEV", "BOARD", "CHIP")
	e.now = func() time.Time { return time.Now() }

	e.Tick() // 不应 panic
}

// TestPayload_AlarmRecJSONContract：序列化后的 JSON 字段与 sophliteos AlarmListen 契约一致。
func TestPayload_AlarmRecJSONContract(t *testing.T) {
	rec := AlarmRec{
		DeviceSn:      "DEV-SN-001",
		ComponentType: 1,
		ChipSn:        "CHIP-SN-001",
		DiskName:      "/dev/sda1",
		BoardSn:       "BOARD-SN-001",
		DateTime:      "2026-07-03 10:00:00",
		Code:          CodeDiskRateAlarm,
		Msg:           "磁盘使用率过高,值为:99%",
	}
	data, err := json.Marshal(rec)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	s := string(data)
	// 必须用 sophliteos AlarmRec 期望的 json key
	for _, key := range []string{`"deviceSn"`, `"componentType"`, `"chipSn"`, `"diskName"`, `"boardSn"`, `"dateTime"`, `"code"`, `"msg"`} {
		if !strings.Contains(s, key) {
			t.Errorf("payload missing %s: %s", key, s)
		}
	}
}

// ---------------------------------------------------------------
// rateToPercent 阈值归一化
// ---------------------------------------------------------------

func TestRateToPercent(t *testing.T) {
	cases := []struct {
		in   float64
		want int
	}{
		{0.95, 95},  // 0-1 小数（旧默认值 / *Scale 字段）
		{0, 0},
		{1, 100},    // 边界：视为 100%
		{90, 90},    // 前端 threshold 页直接发 0-100 百分比
		{10, 10},
		{0.05, 5},
	}
	for _, tt := range cases {
		got := rateToPercent(tt.in)
		if got != tt.want {
			t.Errorf("rateToPercent(%v) = %d, want %d", tt.in, got, tt.want)
		}
	}
}

// 阈值加载器注入后 evaluate 每 tick 重读，保证 SetAlarm 改阈值无需重启即生效。
func TestEngineThresholdsLoaderReload(t *testing.T) {
	m := &fakeMetrics{cpu: metrics.CPU{UtilizationRate: 50}}
	eng := NewEngine(m, &fakeSubs{}, &fakePoster{}, Thresholds{CpuRate: 95},
		"DEV", "BOARD", "CHIP")
	// 初始阈值 95：cpuUtil=50 不告警
	if alarms := eng.evaluate(); len(alarms) != 0 {
		t.Fatalf("expected no alarm at 50%%<95%%, got %d", len(alarms))
	}
	// 注入加载器返回更低的阈值，模拟 SetAlarm 调低后实时生效
	eng.SetThresholdsLoader(func() Thresholds { return Thresholds{CpuRate: 40} })
	// 同一进程、不重启，下一 tick 即用新阈值：50%%>40%% → CPU 告警
	alarms := eng.evaluate()
	found := false
	for _, a := range alarms {
		if a.Code == CodeCPURateAlarm {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected CPU alarm after lowering threshold to 40%% (cpu=50%%), got %v", alarms)
	}
}
