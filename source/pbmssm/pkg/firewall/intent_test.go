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
	if rules[0].Args[3] != "ACCEPT" {
		t.Errorf("want ACCEPT got %s", rules[0].Args[3])
	}
	it2 := Intent{ID: 7, Type: "icmp", Params: mustParams(t, map[string]interface{}{"allow": false}), Enabled: true}
	rules2, _ := it2.Translate()
	if rules2[0].Args[3] != "DROP" {
		t.Errorf("want DROP got %s", rules2[0].Args[3])
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
