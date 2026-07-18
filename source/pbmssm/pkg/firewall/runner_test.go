package firewall

import (
	"testing"
)

func TestSystemRunnerDelegatesToSystem(t *testing.T) {
	// 用一个一定存在的命令验证委托
	r := SystemRunner{}
	out, _, err := r.Run("echo", "hello")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if out != "hello\n" {
		t.Fatalf("got %q want %q", out, "hello\n")
	}
}

func TestSafeTokenRe(t *testing.T) {
	good := []string{"INPUT", "DOCKER-USER", "tcp", "10.0.0.0/8", "bmssm-fw-intent", "192.168.1.1:8080"}
	for _, s := range good {
		if !safeTokenRe.MatchString(s) {
			t.Errorf("should match %q", s)
		}
	}
	bad := []string{"", "INPUT;rm", "a b", "$(x)", "DROP\n", "a'b"}
	for _, s := range bad {
		if safeTokenRe.MatchString(s) {
			t.Errorf("should NOT match %q", s)
		}
	}
}

func TestFirewallConfigDefaults(t *testing.T) {
	// config 未加载时返默认值，不 panic
	enabled, path, sec, extra := FirewallConfig()
	if !enabled {
		t.Error("default enabled should be true")
	}
	if path != "/etc/iptables/rules.v4" {
		t.Errorf("got %q", path)
	}
	if sec != 300 {
		t.Errorf("got %d", sec)
	}
	if len(extra) != 0 {
		t.Errorf("got %v", extra)
	}
}
