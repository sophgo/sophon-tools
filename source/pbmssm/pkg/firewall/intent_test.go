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

// --- S4/S5：互补 CIDR 绕过守卫 ---

func TestIsBroadMatchSlash1(t *testing.T) {
	// /1 前缀覆盖半个 IPv4 空间，视为危险（互补 /1 对可联合覆盖全网段）
	if !isBroadMatch("0.0.0.0/1") {
		t.Error("0.0.0.0/1 should be broad (covers half of IPv4)")
	}
	if !isBroadMatch("128.0.0.0/1") {
		t.Error("128.0.0.0/1 should be broad (covers half of IPv4)")
	}
	// /8 仍允许（特定源 deny 合法）
	if isBroadMatch("10.0.0.0/8") {
		t.Error("10.0.0.0/8 should NOT be broad")
	}
}

func TestCheckProtectDenyPortDenySlash1Src(t *testing.T) {
	// port_deny src 0.0.0.0/1 命中保护端口 → 拒绝（互补绕过失效）
	it := Intent{ID: 20, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "0.0.0.0/1"})}
	if err := CheckProtectDeny(&it, []int{22}); err == nil {
		t.Error("want block for 0.0.0.0/1 deny on protect port")
	}
}

func TestCheckProtectDenyPortDenySpecificSrcStillAllowed(t *testing.T) {
	// 特定源 /8 deny 保护端口仍允许（合法运维场景）
	it := Intent{ID: 21, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22, "src": "10.0.0.0/8"})}
	if err := CheckProtectDeny(&it, []int{22}); err != nil {
		t.Errorf("want allow for specific /8 src, got %v", err)
	}
}

// --- F1：IPv4-mapped IPv6 绕过守卫 ---

func TestParseIPv4CIDRRejectsMappedIPv6(t *testing.T) {
	// ::ffff:x.x.x.x/x 的 To4() 非 nil 但语义是 IPv6，必须拒绝（F1 绕过）
	if _, err := parseIPv4CIDR("::ffff:0.0.0.0/0"); err == nil {
		t.Error("want error for IPv4-mapped IPv6 cidr")
	}
	if _, err := parseIPv4CIDR("::ffff:192.0.2.0/120"); err == nil {
		t.Error("want error for IPv4-mapped IPv6 cidr")
	}
}

func TestCheckProtectDenyMappedIPv6Blacklist(t *testing.T) {
	// ip_blacklist cidr 为 mapped IPv6 → Validate 拒绝，守卫无绕过
	it := Intent{Type: "ip_blacklist", Params: mustParams(t, map[string]interface{}{"cidr": "::ffff:0.0.0.0/0"})}
	if err := it.Validate(); err == nil {
		t.Error("want Validate error for mapped IPv6 blacklist cidr")
	}
}

// --- S6：Enabled=false 关闭不应被守卫拦阻 ---

func TestCheckProtectDenyIgnoresEnabled(t *testing.T) {
	// 守卫本身不读 it.Enabled（由 Service.AddIntent 仅在 req.Enabled 时调用）；
	// 此处验证 CheckProtectDeny 对关闭操作（Enabled=false）同样返回 nil 语义由上层保证。
	it := Intent{ID: 22, Type: "port_deny", Params: mustParams(t, map[string]interface{}{"proto": "tcp", "port": 22}), Enabled: false}
	// Enabled=false 时即使守卫仍拦截（port 22 全网段），Service 层不调用守卫，
	// 因此关闭操作可通过。这里仅验证 Validate 不因 Enabled=false 报错。
	if err := it.Validate(); err != nil {
		t.Errorf("Validate should pass regardless of Enabled, got %v", err)
	}
}
