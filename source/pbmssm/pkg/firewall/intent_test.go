package firewall

import (
	"encoding/json"
	"reflect"
	"testing"
)

func mustParams(t *testing.T, m map[string]interface{}) string {
	t.Helper()
	b, _ := json.Marshal(m)
	return string(b)
}

func TestIntentPortAllow(t *testing.T) {
	it := Intent{ID: 1, Type: "port_allow", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 8080, "src": "10.0.0.0/8"}), Enabled: true}
	if err := it.Validate(); err != nil {
		t.Fatal(err)
	}
	rules, err := it.Translate()
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 {
		t.Fatalf("got %d rules", len(rules))
	}
	want := IptablesRule{Table: "filter", Chain: "INPUT", Args: []string{"-p", "tcp", "-s", "10.0.0.0/8", "--dport", "8080", "-j", "ACCEPT", "-m", "comment", "--comment", "bmssm-fw-intent 1"}, Comment: "bmssm-fw-intent 1"}
	if !reflect.DeepEqual(rules[0], want) {
		t.Fatalf("got %+v\nwant %+v", rules[0], want)
	}
}

func TestIntentPortDeny(t *testing.T) {
	it := Intent{ID: 2, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 3306}), Enabled: true}
	rules, _ := it.Translate()
	if rules[0].Args[5] != "DROP" {
		t.Errorf("want DROP, got %s", rules[0].Args[5])
	}
}

func TestIntentRateLimit(t *testing.T) {
	it := Intent{ID: 3, Type: "rate_limit", Params: mustParams(t, map[string]interface{}{"port": 22, "rate": 5, "per": "second"}), Enabled: true}
	rules, err := it.Translate()
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 2 {
		t.Fatalf("rate_limit should produce 2 rules (set+update), got %d", len(rules))
	}
	// 第一条 --set，第二条 --update --hitcount
	hasSet, hasUpdate := false, false
	for _, r := range rules {
		for i, a := range r.Args {
			if a == "--set" {
				hasSet = true
			}
			if a == "--update" && i+4 < len(r.Args) && r.Args[i+4] == "6" {
				hasUpdate = true
			}
		}
	}
	if !hasSet || !hasUpdate {
		t.Errorf("missing set/update: %v", rules)
	}
}

func TestIntentIPWhitelist(t *testing.T) {
	it := Intent{ID: 4, Type: "ip_whitelist", Params: mustParams(t, map[string]interface{}{"cidr": "10.0.0.0/8"}), Enabled: true}
	rules, _ := it.Translate()
	want := []string{"-s", "10.0.0.0/8", "-j", "ACCEPT"}
	if !reflect.DeepEqual(rules[0].Args[0:4], want) {
		t.Fatalf("got %v", rules[0].Args)
	}
}

func TestIntentIPBlacklist(t *testing.T) {
	it := Intent{ID: 5, Type: "ip_blacklist", Params: mustParams(t, map[string]interface{}{"cidr": "1.2.3.4/32"}), Enabled: true}
	rules, _ := it.Translate()
	if rules[0].Args[3] != "DROP" {
		t.Errorf("want DROP got %s", rules[0].Args[3])
	}
}

func TestIntentICMP(t *testing.T) {
	it := Intent{ID: 6, Type: "icmp", Params: mustParams(t, map[string]interface{}{"allow": true}), Enabled: true}
	rules, _ := it.Translate()
	// args: -p icmp --icmp-type 8 -j ACCEPT -m comment --comment ...
	if len(rules) != 1 {
		t.Fatalf("want 1 rule got %d", len(rules))
	}
	want := []string{"-p", "icmp", "--icmp-type", "8", "-j", "ACCEPT"}
	if !reflect.DeepEqual(rules[0].Args[0:6], want) {
		t.Fatalf("got %v want %v", rules[0].Args[0:6], want)
	}
	it2 := Intent{ID: 7, Type: "icmp", Params: mustParams(t, map[string]interface{}{"allow": false}), Enabled: true}
	rules2, _ := it2.Translate()
	if rules2[0].Args[5] != "DROP" {
		t.Errorf("want DROP got %s", rules2[0].Args[5])
	}
}

func TestIntentValidateBadType(t *testing.T) {
	it := Intent{Type: "bogus", Params: "{}"}
	if err := it.Validate(); err == nil {
		t.Error("want error for bad type")
	}
}

func TestIntentValidateBadPort(t *testing.T) {
	it := Intent{Type: "port_allow", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 99999})}
	if err := it.Validate(); err == nil {
		t.Error("want error for port > 65535")
	}
}

func TestIntentValidateBadCIDR(t *testing.T) {
	it := Intent{Type: "ip_whitelist", Params: mustParams(t, map[string]interface{}{"cidr": "not-a-cidr"})}
	if err := it.Validate(); err == nil {
		t.Error("want error for bad cidr")
	}
}

// --- CheckProtectDeny 守卫 ---

func TestCheckProtectDenyPortDenyZeroSrc(t *testing.T) {
	// 0.0.0.0/0 明确拒绝保护端口
	it := Intent{ID: 8, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "0.0.0.0/0"})}
	if err := CheckProtectDeny(&it, []int{22}); err == nil {
		t.Error("want block for 0.0.0.0/0 deny on protect port")
	}
}

func TestCheckProtectDenyPortDenyEmptySrc(t *testing.T) {
	// 空 src（缺省）→ Translate 无 -s = 全网段，必须拦截
	it := Intent{ID: 9, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22})}
	if err := CheckProtectDeny(&it, []int{22}); err == nil {
		t.Error("want block for empty src deny on protect port")
	}
}

func TestCheckProtectDenyPortDenySpecificSrc(t *testing.T) {
	// 特定源 CIDR 允许拒绝
	it := Intent{ID: 10, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "10.0.0.0/8"})}
	if err := CheckProtectDeny(&it, []int{22}); err != nil {
		t.Errorf("want allow for specific src, got %v", err)
	}
}

func TestCheckProtectDenyPortDenyNonProtect(t *testing.T) {
	// 非保护端口 0.0.0.0/0 允许
	it := Intent{ID: 11, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 9999, "src": "0.0.0.0/0"})}
	if err := CheckProtectDeny(&it, []int{22}); err != nil {
		t.Errorf("want allow for non-protect port, got %v", err)
	}
}

func TestCheckProtectDenyIPBlacklistBroad(t *testing.T) {
	// ip_blacklist 0.0.0.0/0 必须拦截（全内网封禁 = 锁死保护主机）
	it := Intent{ID: 12, Type: "ip_blacklist", Params: mustParams(t, map[string]interface{}{"cidr": "0.0.0.0/0"})}
	if err := CheckProtectDeny(&it, []int{22}); err == nil {
		t.Error("want block for ip_blacklist 0.0.0.0/0")
	}
}

func TestCheckProtectDenyIPBlacklistSpecific(t *testing.T) {
	// 特定 IP 黑名单允许
	it := Intent{ID: 13, Type: "ip_blacklist", Params: mustParams(t, map[string]interface{}{"cidr": "6.6.6.6/32"})}
	if err := CheckProtectDeny(&it, []int{22}); err != nil {
		t.Errorf("want allow for specific ip blacklist, got %v", err)
	}
}

func TestCheckProtectDenyRateLimitProtectPort(t *testing.T) {
	// rate_limit 作用于保护端口必须拦截（recent+DROP 超限丢包）
	it := Intent{ID: 14, Type: "rate_limit", Params: mustParams(t, map[string]interface{}{"port": 22, "rate": 1, "per": "second"})}
	if err := CheckProtectDeny(&it, []int{22}); err == nil {
		t.Error("want block for rate_limit on protect port")
	}
}

func TestCheckProtectDenyAllowType(t *testing.T) {
	// port_allow 保护端口允许（放行不构成风险）
	it := Intent{ID: 15, Type: "port_allow", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "0.0.0.0/0"})}
	if err := CheckProtectDeny(&it, []int{22}); err != nil {
		t.Errorf("want allow for port_allow, got %v", err)
	}
}

func TestCheckProtectDenyIPv6SrcValidate(t *testing.T) {
	// port_deny 带 IPv6 src 必须在 Validate 阶段拒绝（parseIPv4CIDR 强制 IPv4）
	it := Intent{Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "2001:db8::/32"})}
	if err := it.Validate(); err == nil {
		t.Error("want error for IPv6 src in port rule")
	}
}
