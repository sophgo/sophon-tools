package compat

import (
	"os"
	"testing"

	"bmssm/config"
	"bmssm/global"
)

// ---------------------------------------------------------------
// CIDR 掩码转换测试
// ---------------------------------------------------------------

func TestCidrToMask(t *testing.T) {
	tests := []struct {
		cidr string
		want string
	}{
		{"24", "255.255.255.0"},
		{"16", "255.255.0.0"},
		{"8", "255.0.0.0"},
		{"32", "255.255.255.255"},
		{"0", "0.0.0.0"},
		{"invalid", ""},
		{"-1", ""},
		{"33", ""},
	}

	for _, tt := range tests {
		got := cidrToMask(tt.cidr)
		if got != tt.want {
			t.Errorf("cidrToMask(%q) = %q, want %q", tt.cidr, got, tt.want)
		}
	}
}

// ---------------------------------------------------------------
// 订阅管理测试
// ---------------------------------------------------------------

func TestSubscriptionCRUD(t *testing.T) {
	svc := NewCompatService()

	// 初始为空
	if got := svc.ListSubscriptions(); len(got) != 0 {
		t.Errorf("initial subscriptions = %d, want 0", len(got))
	}

	// 查询不存在的
	if _, ok := svc.GetSubscription("nonexistent"); ok {
		t.Error("GetSubscription should return false for nonexistent")
	}

	// 添加订阅
	req := SubscribeRequest{
		Platform:            "test-platform",
		SubscribeDetailType: []int{1, 2},
		NotificationURL:     "http://127.0.0.1:8080/api/device/alarm",
	}
	svc.Subscribe(req)

	// 查询
	got, ok := svc.GetSubscription("test-platform")
	if !ok {
		t.Fatal("GetSubscription should return true after subscribe")
	}
	if got.Platform != "test-platform" {
		t.Errorf("Platform = %q", got.Platform)
	}
	if got.NotificationURL != req.NotificationURL {
		t.Errorf("NotificationURL = %q", got.NotificationURL)
	}
	if len(got.SubscribeDetailType) != 2 {
		t.Errorf("SubscribeDetailType len = %d, want 2", len(got.SubscribeDetailType))
	}

	// 列表
	list := svc.ListSubscriptions()
	if len(list) != 1 {
		t.Errorf("list len = %d, want 1", len(list))
	}

	// 取消订阅
	svc.Unsubscribe("test-platform")
	if _, ok := svc.GetSubscription("test-platform"); ok {
		t.Error("GetSubscription should return false after unsubscribe")
	}
	if len(svc.ListSubscriptions()) != 0 {
		t.Error("list should be empty after unsubscribe")
	}
}

func TestSubscriptionConcurrent(t *testing.T) {
	svc := NewCompatService()
	done := make(chan bool)

	for i := 0; i < 50; i++ {
		go func(id int) {
			svc.Subscribe(SubscribeRequest{
				Platform:        "p" + formatInt(id),
				NotificationURL: "http://example.com",
			})
			done <- true
		}(i)
	}
	for i := 0; i < 50; i++ {
		<-done
	}

	list := svc.ListSubscriptions()
	if len(list) != 50 {
		t.Errorf("concurrent subscriptions = %d, want 50", len(list))
	}
}

func formatInt(n int) string {
	if n == 0 {
		return "0"
	}
	s := ""
	for n > 0 {
		s = string(rune('0'+n%10)) + s
		n /= 10
	}
	return s
}

// ---------------------------------------------------------------
// NAT 规则编号校验
// ---------------------------------------------------------------

func TestDeleteNATRuleValidation(t *testing.T) {
	// 空字符串
	if err := DeleteNATRule(""); err == nil {
		t.Error("expected error for empty num")
	}

	// 非数字
	if err := DeleteNATRule("abc"); err == nil {
		t.Error("expected error for non-numeric num")
	}

	// 包含特殊字符（注入尝试）
	if err := DeleteNATRule("1; rm -rf /"); err == nil {
		t.Error("expected error for injection attempt")
	}
	if err := DeleteNATRule("1 && echo hacked"); err == nil {
		t.Error("expected error for injection attempt")
	}

	// 0
	if err := DeleteNATRule("0"); err == nil {
		t.Error("expected error for 0")
	}

	// 负号
	if err := DeleteNATRule("-1"); err == nil {
		t.Error("expected error for negative num")
	}
}

// ---------------------------------------------------------------
// numRe 正则测试
// ---------------------------------------------------------------

// ---------------------------------------------------------------
// BuildCtrlBasic ChipSn 字段测试
// ---------------------------------------------------------------

func TestBuildCtrlBasicChipSn(t *testing.T) {
	// 初始化配置（BuildCtrlBasic 需要 config.Conf 读取 deviceName）
	_ = os.Setenv("BMSSM_CONF", t.TempDir())
	config.LoadConfig()

	svc := NewCompatService()

	// 保存原始值，测试结束后恢复
	origChipSn := global.ChipSn
	origDeviceSnEx := global.DeviceSnEx
	origDeviceTypeEx := global.DeviceTypeEx
	origDeviceType := global.DeviceType
	defer func() {
		global.ChipSn = origChipSn
		global.DeviceSnEx = origDeviceSnEx
		global.DeviceTypeEx = origDeviceTypeEx
		global.DeviceType = origDeviceType
	}()

	// 模拟真机数据：ChipSn 是芯片级SN，DeviceSnEx 是设备级SN
	global.ChipSn = "EC712AC0C24120073"
	global.DeviceSnEx = "HQATEVBAIAIAI0001"
	global.DeviceTypeEx = "SE7 V1"
	global.DeviceType = "soc"

	basic, err := svc.BuildCtrlBasic()
	if err != nil {
		t.Fatalf("BuildCtrlBasic failed: %v", err)
	}

	// chipSn 必须是芯片级SN，不是设备级SN
	if basic.ChipSn != "EC712AC0C24120073" {
		t.Errorf("ChipSn = %q, want %q (chip-level SN, not device-level SN)",
			basic.ChipSn, "EC712AC0C24120073")
	}

	// 确认 configure.basic 字段正确 —— bmssm 兼容映射：
	// 	DeviceType 放型号 DeviceTypeEx（"SE7 V1"），让 sophliteos GetDeviceType 截成 "SE7"
	// 	DeviceName 从配置读取，默认 "device_1"
	if basic.Configure.Basic.DeviceName != "device_1" {
		t.Errorf("DeviceName = %q, want %q (configurable, default 'device_1')",
			basic.Configure.Basic.DeviceName, "device_1")
	}
	// Basic.DeviceType 展示用截取后的型号主体（"SE7 V1" → "SE7"），
	// 完整型号在 System.DeviceTypeEx。
	if basic.Configure.Basic.DeviceType != "SE7" {
		t.Errorf("Configure.Basic.DeviceType = %q, want SE7", basic.Configure.Basic.DeviceType)
	}

	// 确认 system 字段
	if basic.System.DeviceType != "soc" {
		t.Errorf("System.DeviceType = %q, want %q", basic.System.DeviceType, "soc")
	}
	if basic.System.DeviceTypeEx != "SE7 V1" {
		t.Errorf("System.DeviceTypeEx = %q, want %q", basic.System.DeviceTypeEx, "SE7 V1")
	}

	// 回退测试：ChipSn 为空时使用 DeviceSnEx
	global.ChipSn = ""
	basic2, err := svc.BuildCtrlBasic()
	if err != nil {
		t.Fatalf("BuildCtrlBasic with empty ChipSn failed: %v", err)
	}
	if basic2.ChipSn != "HQATEVBAIAIAI0001" {
		t.Errorf("ChipSn with empty ChipSn fallback = %q, want %q",
			basic2.ChipSn, "HQATEVBAIAIAI0001")
	}
}

func TestNumRe(t *testing.T) {
	valid := []string{"1", "10", "999", "1234567890"}
	for _, v := range valid {
		if !numRe.MatchString(v) {
			t.Errorf("numRe should match %q", v)
		}
	}

	invalid := []string{"", "0", "01", "abc", "1;", " 1", "1 ", "-1", "1.5"}
	for _, v := range invalid {
		if numRe.MatchString(v) {
			t.Errorf("numRe should NOT match %q", v)
		}
	}
}

// ---------------------------------------------------------------
// BuildCtrlBasic alarmThreshold 测试
// ---------------------------------------------------------------

func TestBuildCtrlBasicAlarmThreshold(t *testing.T) {
	// 初始化配置（空目录，全部使用 SetDefault 默认值）
	_ = os.Setenv("BMSSM_CONF", t.TempDir())
	config.LoadConfig()

	svc := NewCompatService()
	basic, err := svc.BuildCtrlBasic()
	if err != nil {
		t.Fatalf("BuildCtrlBasic failed: %v", err)
	}

	at := basic.Configure.AlarmThreshold

	// 默认值对齐 bmssm deviceConf.json alarmthreshold
	if at.BoardTemperature != 90 {
		t.Errorf("BoardTemperature = %d, want 90", at.BoardTemperature)
	}
	if at.CoreTemperature != 90 {
		t.Errorf("CoreTemperature = %d, want 90", at.CoreTemperature)
	}
	if at.CpuRate != 0.95 {
		t.Errorf("CpuRate = %v, want 0.95", at.CpuRate)
	}
	if at.DiskRate != 0.95 {
		t.Errorf("DiskRate = %v, want 0.95", at.DiskRate)
	}
	if at.ExternalHardDiskRate != 0.95 {
		t.Errorf("ExternalHardDiskRate = %v, want 0.95", at.ExternalHardDiskRate)
	}
	if at.FanSpeed != 9999 {
		t.Errorf("FanSpeed = %d, want 9999", at.FanSpeed)
	}
	if at.SystemScale != 0.95 {
		t.Errorf("SystemScale = %v, want 0.95", at.SystemScale)
	}
	if at.TotalMemoryScale != 0.95 {
		t.Errorf("TotalMemoryScale = %v, want 0.95", at.TotalMemoryScale)
	}
	if at.TpuRate != 0.95 {
		t.Errorf("TpuRate = %v, want 0.95", at.TpuRate)
	}
	if at.TpuScale != 0.95 {
		t.Errorf("TpuScale = %v, want 0.95", at.TpuScale)
	}
	if at.VideoScale != 0.95 {
		t.Errorf("VideoScale = %v, want 0.95", at.VideoScale)
	}
}

func TestDisplayDeviceType(t *testing.T) {
	cases := []struct{ in, want string }{
		{"SE7 V1", "SE7"},
		{"se9 v02", "SE9"},
		{"SE5", "SE5"},
		{"", ""},
		{"  se6 ", "SE6"},
	}
	for _, tt := range cases {
		if got := displayDeviceType(tt.in); got != tt.want {
			t.Errorf("displayDeviceType(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}

func TestBuildDeviceModel(t *testing.T) {
	cases := []struct{ typeEx, mte, want string }{
		{"SE9", "16-BP1-11", "SE9 16-BP1-11"}, // SE9 OEM 分支
		{"SE7 V1", "", "SE7 V1"},              // i2c 分支 ModuleTypeEx 空
		{"", "16-BP1-11", ""},                 // 无 typeEx
		{"SE9", "", "SE9"},
	}
	for _, tt := range cases {
		if got := buildDeviceModel(tt.typeEx, tt.mte); got != tt.want {
			t.Errorf("buildDeviceModel(%q,%q) = %q, want %q", tt.typeEx, tt.mte, got, tt.want)
		}
	}
}
