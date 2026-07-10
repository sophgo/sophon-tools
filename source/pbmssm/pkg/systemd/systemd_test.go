package systemd

import (
	"math"
	"testing"
)

func TestValidateUnitName(t *testing.T) {
	valid := []string{"bmssm.service", "getty@tty1.service", "bm-se7-powerkey-monitor.service", "bmrt_watchdog.service"}
	for _, n := range valid {
		if err := ValidateUnitName(n); err != nil {
			t.Fatalf("expected %q valid, got %v", n, err)
		}
	}
	invalid := []string{"a;rm -rf /", "$(x)", "a b", "", "foo bar.service", "x|y", "*.service", "?.service", "bm*.service"}
	for _, n := range invalid {
		if err := ValidateUnitName(n); err == nil {
			t.Fatalf("expected %q invalid", n)
		}
	}
}

func TestProtectedMatch(t *testing.T) {
	patterns := []string{"bmssm.service", "bm*.service", "getty@*.service", "systemd-*.service"}
	cases := []struct {
		name string
		want bool
	}{
		{"bmssm.service", true},                   // 精确 + bm*
		{"bmrt_watchdog.service", true},           // bm*
		{"bmDeviceDetect.service", true},          // bm*
		{"bm-se7-powerkey-monitor.service", true}, // bm*
		{"getty@tty1.service", true},              // getty@*
		{"systemd-journald.service", true},        // systemd-*
		{"nginx.service", false},
		{"cron.service", false},
		{"ssh.service", false},
	}
	for _, c := range cases {
		if got := ProtectedMatch(c.name, patterns); got != c.want {
			t.Fatalf("ProtectedMatch(%q)=%v want %v", c.name, got, c.want)
		}
	}
}

func TestParseListUnitFiles(t *testing.T) {
	content := `UNIT FILE                    STATE   VENDOR PRESET
acpid.service                enabled enabled
cron.service                 enabled enabled
nginx.service                enabled enabled
fio-ro-test.service          disabled disabled
46 unit files listed.
`
	m := ParseListUnitFiles(content)
	if m["acpid.service"] != "enabled" {
		t.Fatalf("acpid=%q", m["acpid.service"])
	}
	if m["fio-ro-test.service"] != "disabled" {
		t.Fatalf("fio=%q", m["fio-ro-test.service"])
	}
	if _, ok := m["UNIT"]; ok {
		t.Fatal("header leaked into map")
	}
	if len(m) != 4 {
		t.Fatalf("len=%d want 4", len(m))
	}
}

func TestParseBlame(t *testing.T) {
	// 123.000ms 行：TrimSuffix("s") -> "123.000m"，ParseFloat 失败 -> 跳过；notaparse 行同理跳过。
	content := `    8.123s bmrt_setup.service
    2.456s networking.service
  123.000ms foo.service
  notaparse line
`
	items := ParseBlame(content)
	if len(items) != 2 {
		t.Fatalf("len=%d want 2 (ms 行应被跳过)", len(items))
	}
	if items[0].Unit != "bmrt_setup.service" || math.Abs(items[0].Time-8.123) > 1e-9 {
		t.Fatalf("item0=%+v", items[0])
	}
	if items[1].Unit != "networking.service" || math.Abs(items[1].Time-2.456) > 1e-9 {
		t.Fatalf("item1=%+v", items[1])
	}
}

func TestParseListUnits(t *testing.T) {
	content := "  UNIT                                     LOAD      ACTIVE   SUB     DESCRIPTION\n" +
		"  acpid.service                            loaded    active   running ACPI event daemon\n" +
		"  apparmor.service                         loaded    inactive dead    Load AppArmor profiles\n" +
		"123 loaded units listed.\n"
	rows := ParseListUnits(content)
	if len(rows) != 2 {
		t.Fatalf("len=%d want 2 (header+footer skipped)", len(rows))
	}
	if rows[0].Unit != "acpid.service" || rows[0].Load != "loaded" || rows[0].Active != "active" || rows[0].Sub != "running" || rows[0].Description != "ACPI event daemon" {
		t.Fatalf("row0=%+v", rows[0])
	}
	if rows[1].Active != "inactive" || rows[1].Sub != "dead" || rows[1].Description != "Load AppArmor profiles" {
		t.Fatalf("row1=%+v", rows[1])
	}
}

func TestParseAnalyzeTime(t *testing.T) {
	content := "Startup finished in 3.123s (kernel) + 12.456s (userspace) = 15.579s\n"
	k, u, tot := ParseAnalyzeTime(content)
	if math.Abs(k-3.123) > 1e-9 || math.Abs(u-12.456) > 1e-9 || math.Abs(tot-15.579) > 1e-9 {
		t.Fatalf("k=%v u=%v tot=%v", k, u, tot)
	}
}

// TestDefaultProtectedCoversFunctional 验证功能关键服务被默认名单保护
// （docker/containerd/upd72020x-fwload/apparmor/ubuntu-fan）。
func TestDefaultProtectedCoversFunctional(t *testing.T) {
	cases := []string{
		"docker.service", "containerd.service", "upd72020x-fwload.service",
		"apparmor.service", "ubuntu-fan.service",
		// 仍覆盖管理核心 + Sophon 厂商
		"bmssm.service", "bmrt_watchdog.service", "ssh.service",
	}
	for _, name := range cases {
		if !ProtectedMatch(name, DefaultProtectedServices) {
			t.Fatalf("DefaultProtectedServices 未保护 %s", name)
		}
	}
	// 普通服务不应被保护
	for _, name := range []string{"cron.service", "atop.service", "rsyslog.service"} {
		if ProtectedMatch(name, DefaultProtectedServices) {
			t.Fatalf("DefaultProtectedServices 误保护 %s", name)
		}
	}
}
