package firewall

import "testing"

func TestRawValidateOK(t *testing.T) {
	r := RawRule{Chain: "INPUT", Args: []string{"-p", "tcp", "--dport", "80", "-j", "ACCEPT"}}
	if err := r.Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestRawValidateBadChain(t *testing.T) {
	r := RawRule{Chain: "INPUT;rm -rf", Args: []string{"-j", "ACCEPT"}}
	if err := r.Validate(); err == nil {
		t.Error("want error for bad chain")
	}
}

func TestRawValidateBadArg(t *testing.T) {
	r := RawRule{Chain: "INPUT", Args: []string{"-j", "ACCEPT;rm"}}
	if err := r.Validate(); err == nil {
		t.Error("want error for bad arg")
	}
}

func TestParseFilterOutput(t *testing.T) {
	out := `Chain INPUT (policy ACCEPT 100 packets, 200 bytes)
num   pkts bytes target prot opt in  out  source   destination
1       10  1000 ACCEPT tcp  --  *   *   0.0.0.0/0  0.0.0.0/0  tcp dpt:22
2        5   500 DROP   all  --  *   *   1.2.3.4/32 0.0.0.0/0`
	rules := parseFilterList(out)
	if len(rules) != 2 {
		t.Fatalf("got %d want 2", len(rules))
	}
	if rules[0].Num != 1 || rules[0].Target != "ACCEPT" || rules[0].Prot != "tcp" || rules[0].Chain != "INPUT" {
		t.Errorf("rule0: %+v", rules[0])
	}
	if rules[1].Src != "1.2.3.4/32" || rules[1].Chain != "INPUT" {
		t.Errorf("rule1: %+v", rules[1])
	}
}
