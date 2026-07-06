package compat

import (
	"encoding/json"
	"os"
	"testing"

	"ssm/config"
	"ssm/global"
)

// ---------------------------------------------------------------
// SsmResult 信封测试
// ---------------------------------------------------------------

func TestSsmOK(t *testing.T) {
	result := map[string]string{"token": "abc123"}
	resp := SsmOK(result)

	if resp.Code != 0 {
		t.Errorf("SsmOK Code = %d, want 0", resp.Code)
	}
	if resp.Msg != "请求成功" {
		t.Errorf("SsmOK Msg = %q, want %q", resp.Msg, "请求成功")
	}
	if resp.Result == nil {
		t.Fatal("SsmOK Result is nil")
	}

	// result 应该是传入的 map
	data, _ := json.Marshal(resp)
	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("unmarshal SsmOK: %v", err)
	}
	if parsed["code"] != float64(0) {
		t.Errorf("parsed code = %v, want 0", parsed["code"])
	}
	tokenObj, ok := parsed["result"].(map[string]interface{})
	if !ok {
		t.Fatal("result is not an object")
	}
	if tokenObj["token"] != "abc123" {
		t.Errorf("result.token = %v, want abc123", tokenObj["token"])
	}
}

func TestSsmErr(t *testing.T) {
	resp := SsmErr("something went wrong")

	if resp.Code != 1 {
		t.Errorf("SsmErr Code = %d, want 1", resp.Code)
	}
	if resp.Msg != "请求失败" {
		t.Errorf("SsmErr Msg = %q, want %q", resp.Msg, "请求失败")
	}
	if resp.ErrorMessage != "something went wrong" {
		t.Errorf("SsmErr ErrorMessage = %q, want %q", resp.ErrorMessage, "something went wrong")
	}

	data, _ := json.Marshal(resp)
	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("unmarshal SsmErr: %v", err)
	}
	if parsed["code"] != float64(1) {
		t.Errorf("parsed code = %v, want 1", parsed["code"])
	}
}

func TestSsmErrCode(t *testing.T) {
	resp := SsmErrCode(403, "forbidden")

	if resp.Code != 1 {
		t.Errorf("Code = %d, want 1", resp.Code)
	}
	if resp.ErrorCode != 403 {
		t.Errorf("ErrorCode = %d, want 403", resp.ErrorCode)
	}
	if resp.ErrorMessage != "forbidden" {
		t.Errorf("ErrorMessage = %q", resp.ErrorMessage)
	}
}

func TestSsmResultEnvelopeRoundTrip(t *testing.T) {
	// sophliteos 期望的 JSON 形状
	okResp := SsmOK(map[string]interface{}{
		"token": "my-jwt-token",
		"role":  "admin",
	})

	data, err := json.Marshal(okResp)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	// 验证 sophliteos 字段都存在
	fields := []string{"code", "msg", "error_code", "error_message", "result"}
	for _, f := range fields {
		if _, ok := parsed[f]; !ok {
			t.Errorf("missing field %q in SsmResult JSON", f)
		}
	}
}

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
	_ = os.Setenv("SSM_CONF", t.TempDir())
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
	if basic.Configure.Basic.DeviceType != "SE7 V1" {
		t.Errorf("Configure.Basic.DeviceType = %q, want %q (DeviceTypeEx, not DeviceType)",
			basic.Configure.Basic.DeviceType, "SE7 V1")
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
	_ = os.Setenv("SSM_CONF", t.TempDir())
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
