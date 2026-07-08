package response

import (
	"encoding/json"
	"testing"

	"ssm/global"
)

// TestOK 成功信封构造。
func TestOK(t *testing.T) {
	r := OK("x")
	if r.Code != 0 || r.Msg != "请求成功" || r.Result != "x" {
		t.Fatalf("OK = %+v, want code=0 msg=请求成功 result=x", r)
	}
}

// TestFail 失败信封构造。
func TestFail(t *testing.T) {
	r := Fail("boom")
	if r.Code != 1 || r.Msg != "请求失败" || r.ErrorMessage != "boom" {
		t.Fatalf("Fail = %+v, want code=1 msg=请求失败 error_message=boom", r)
	}
	if r.Result != nil {
		t.Fatalf("Fail result = %v, want nil", r.Result)
	}
}

// TestFailCode 带错误码失败信封构造。
func TestFailCode(t *testing.T) {
	r := FailCode(42, "boom")
	if r.Code != 1 || r.ErrorCode != 42 || r.ErrorMessage != "boom" {
		t.Fatalf("FailCode = %+v, want code=1 error_code=42 error_message=boom", r)
	}
}

// TestResultEnvelopeRoundTrip 信封 JSON 往返 + 字段名对齐 bmssm 契约。
func TestResultEnvelopeRoundTrip(t *testing.T) {
	// 设非空 DeviceSn，否则 omitempty 会省略 deviceSn 字段，无法校验字段名。
	prev := global.DeviceSnEx
	global.DeviceSnEx = "test-sn"
	defer func() { global.DeviceSnEx = prev }()

	r := OK(map[string]int{"a": 1})
	b, err := json.Marshal(r)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var got Result
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if got.Code != 0 || got.Msg != "请求成功" {
		t.Fatalf("round-trip = %+v, want code=0 msg=请求成功", got)
	}
	// 字段名必须与 sophliteos/bmssm 契约一致：snake_case
	var m map[string]json.RawMessage
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("unmarshal to map: %v", err)
	}
	for _, f := range []string{"code", "msg", "error_code", "error_message", "deviceSn", "result"} {
		if _, ok := m[f]; !ok {
			t.Errorf("envelope missing field %q (got keys: %v)", f, keys(m))
		}
	}
}

// TestOKDeviceSn DeviceSn 填充不 panic（依赖 global.DeviceSnEx，测试环境可能为空）。
func TestOKDeviceSn(t *testing.T) {
	_ = OK(nil)
	_ = OK(map[string]string{"k": "v"})
}

// TestFailDeviceSn 失败信封 DeviceSn 填充不 panic。
func TestFailDeviceSn(t *testing.T) {
	_ = Fail("boom")
	_ = FailCode(7, "boom")
}

func keys(m map[string]json.RawMessage) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
