package network

import (
	"testing"
)

func TestNatRuleValidateOK(t *testing.T) {
	cases := []NatRule{
		{Direction: "in", Operation: "append", Dst: "192.168.1.1", Src: "10.0.0.1", Protocol: "tcp", DstPort: "80", SrcPort: "8080"},
		{Direction: "out", Operation: "delete", Dst: "10.0.0.1"},
		{Direction: "in", Operation: "append", Protocol: "udp", DstPort: "53"},
		{Direction: "in", Operation: "append", Protocol: "icmp"},
		{Direction: "in", Operation: "append", Flags: "-n"},
	}
	for i, rule := range cases {
		if err := rule.Validate(); err != nil {
			t.Fatalf("case #%d: unexpected error: %v", i, err)
		}
	}
}

func TestNatRuleValidateRejects(t *testing.T) {
	cases := []struct {
		name string
		rule NatRule
	}{
		{"bad direction", NatRule{Direction: "sideways", Operation: "append"}},
		{"bad operation", NatRule{Direction: "in", Operation: "modify"}},
		{"injection src", NatRule{Direction: "in", Operation: "append", Src: "1.2.3.4; rm -rf /"}},
		{"injection dst", NatRule{Direction: "in", Operation: "append", Dst: "$(whoami)"}},
		{"bad srcPort non-number", NatRule{Direction: "in", Operation: "append", SrcPort: "abc"}},
		{"bad dstPort range", NatRule{Direction: "in", Operation: "append", DstPort: "99999"}},
		{"bad protocol injection", NatRule{Direction: "in", Operation: "append", Protocol: "tcp; rm -rf /"}},
		{"bad flags injection", NatRule{Direction: "in", Operation: "append", Flags: "-A && rm -rf /"}},
		{"empty direction", NatRule{Operation: "append"}},
		{"empty operation", NatRule{Direction: "in"}},
	}
	for _, tc := range cases {
		if err := tc.rule.Validate(); err == nil {
			t.Fatalf("case %q: expected error, got nil", tc.name)
		}
	}
}

func TestNatRuleBuildArgs(t *testing.T) {
	rule := NatRule{
		Direction: "in",
		Operation: "append",
		Dst:       "192.168.1.1",
		Protocol:  "tcp",
		DstPort:   "80",
		Src:       "10.0.0.1",
		SrcPort:   "8080",
	}
	args := rule.buildArgs()

	// 期望：-t nat -A PREROUTING -d 192.168.1.1 -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:8080
	want := []string{"-t", "nat", "-A", "PREROUTING", "-d", "192.168.1.1", "-p", "tcp", "--dport", "80", "-j", "DNAT", "--to-destination", "10.0.0.1:8080"}
	if len(args) != len(want) {
		t.Fatalf("expected %d args, got %d: %v", len(want), len(args), args)
	}
	for i, w := range want {
		if args[i] != w {
			t.Fatalf("arg[%d]: expected %q, got %q (full: %v)", i, w, args[i], args)
		}
	}
}

func TestNatRuleBuildArgsPostRouting(t *testing.T) {
	rule := NatRule{
		Direction: "out",
		Operation: "delete",
		Dst:       "10.0.0.1",
	}
	args := rule.buildArgs()

	want := []string{"-t", "nat", "-D", "POSTROUTING", "-d", "10.0.0.1"}
	if len(args) != len(want) {
		t.Fatalf("expected %d args, got %d: %v", len(want), len(args), args)
	}
	for i, w := range want {
		if args[i] != w {
			t.Fatalf("arg[%d]: expected %q, got %q", i, w, args[i])
		}
	}
}

func TestValidatePort(t *testing.T) {
	cases := []struct {
		s    string
		want bool
	}{
		{"80", true},
		{"1", true},
		{"65535", true},
		{"0", false},
		{"65536", false},
		{"abc", false},
		{"", false}, // empty -> Atoi fails
		{"-1", false},
	}
	for _, tc := range cases {
		err := validatePort(tc.s)
		got := err == nil
		if got != tc.want {
			t.Errorf("validatePort(%q) = %v, want %v", tc.s, got, tc.want)
		}
	}
}

// TestAddNATRuleRejectsInjection 集成校验：恶意输入在执行前被拒。
func TestAddNATRuleRejectsInjection(t *testing.T) {
	rule := NatRule{
		Direction: "in",
		Operation: "append",
		Src:       "1.2.3.4; rm -rf /",
	}
	if err := AddNATRule(rule); err == nil {
		t.Fatal("expected error for injection attempt")
	}
}
