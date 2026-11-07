package ident

import (
	"reflect"
	"testing"
)

// 正反例：含下划线且去下划线后 ≥ 4 字符才算标识符。
func TestIdentifiers(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want []string
	}{
		// ---- 正例 ----
		{"寄存器名", "rtc_ctrl_status1", []string{"rtc_ctrl_status1"}},
		{"命令名", "build_kernel", []string{"build_kernel"}},
		{"大写转小写", "WDT_STAT", []string{"wdt_stat"}},
		{"混在中文里", "WDT_STAT 寄存器怎么读", []string{"wdt_stat"}},
		{"多个标识符", "rtc_ctrl_status1 和 wdt_stat 的区别", []string{"rtc_ctrl_status1", "wdt_stat"}},
		{"命令加报错", "build_kernel 报错", []string{"build_kernel"}},
		{"数字下划线混合", "gpio_0_7", []string{"gpio_0_7"}},
		{"去重保序", "wdt_stat 然后 rtc_ctrl_status1 再 wdt_stat", []string{"wdt_stat", "rtc_ctrl_status1"}},

		// ---- 反例：都不该被当成标识符 ----
		{"无下划线英文词", "I2C", nil},
		{"分辨率", "1080p", nil},
		{"纯中文", "寄存器", nil},
		{"连字符不是下划线", "sophon-sail", nil},
		{"下划线太短", "rtc_", nil},                   // rtc → 3 < 4
		{"仅下划线", "__", nil},                      // 去掉后为空
		{"下划线加短词", "a_b", nil},                   // ab → 2 < 4
		{"去下划线恰好 3", "a_bc", nil},                // abc → 3 < 4
		{"去下划线恰好 4", "a_bcd", []string{"a_bcd"}}, // abcd → 4，通过
		{"空串", "", nil},
		{"纯空格", "   ", nil},
		{"中文加无下划线英文", "SE9 微服务器", nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := Identifiers(c.in)
			if len(got) == 0 && len(c.want) == 0 {
				return
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("Identifiers(%q) = %v, want %v", c.in, got, c.want)
			}
		})
	}
}

// 标识符提取对大小写不敏感。
func TestIdentifiersCaseInsensitive(t *testing.T) {
	for _, in := range []string{"RTC_CTRL_STATUS1", "rtc_ctrl_status1", "Rtc_Ctrl_Status1"} {
		got := Identifiers(in)
		if len(got) != 1 || got[0] != "rtc_ctrl_status1" {
			t.Errorf("Identifiers(%q) = %v, want [rtc_ctrl_status1]", in, got)
		}
	}
}

// 下划线连写（如 `__init__`）去下划线后仍够长，算标识符；这里锁定该行为不被误判为无意义。
func TestIdentifiersDunder(t *testing.T) {
	got := Identifiers("调用 __init__ 初始化")
	if len(got) != 1 || got[0] != "__init__" {
		t.Errorf("Identifiers = %v, want [__init__]", got)
	}
}
