package firewall

import "testing"

func TestRiskDirectDropProtectPort(t *testing.T) {
	// 一条 DROP tcp dport 22 的 INPUT 规则，protect=[22] → 风险
	r := IptablesRule{Chain: "INPUT", Args: []string{"-p", "tcp", "--dport", "22", "-j", "DROP", "-m", "comment", "--comment", "x"}}
	risks := CheckRisks([]IptablesRule{r}, []int{22})
	if len(risks) != 1 {
		t.Fatalf("got %d want 1", len(risks))
	}
	if risks[0].Mode != "direct_block" {
		t.Errorf("mode=%s", risks[0].Mode)
	}
}

func TestRiskNoRiskForNonProtectPort(t *testing.T) {
	r := IptablesRule{Chain: "INPUT", Args: []string{"-p", "tcp", "--dport", "3306", "-j", "DROP"}}
	if len(CheckRisks([]IptablesRule{r}, []int{22})) != 0 {
		t.Error("should not risk 3306")
	}
}

func TestRiskInputPolicyDropNoAllow(t *testing.T) {
	// INPUT policy DROP 且无放行 22 的 ACCEPT → 风险
	// 用特殊 IptablesRule 表示 policy（Chain="INPUT", Args=["--policy","DROP"]）
	r := IptablesRule{Chain: "INPUT", Args: []string{"--policy", "DROP"}}
	risks := CheckRisks([]IptablesRule{r}, []int{22})
	if len(risks) != 1 || risks[0].Mode != "policy_block" {
		t.Fatalf("got %+v", risks)
	}
}

func TestRiskInputPolicyDropWithAllow(t *testing.T) {
	policy := IptablesRule{Chain: "INPUT", Args: []string{"--policy", "DROP"}}
	allow := IptablesRule{Chain: "INPUT", Args: []string{"-p", "tcp", "--dport", "22", "-j", "ACCEPT"}}
	if len(CheckRisks([]IptablesRule{policy, allow}, []int{22})) != 0 {
		t.Error("allow should clear risk")
	}
}

func TestRiskDockerUserDropProtectPort(t *testing.T) {
	r := IptablesRule{Chain: "DOCKER-USER", Args: []string{"-p", "tcp", "--dport", "22", "-j", "DROP"}}
	risks := CheckRisks([]IptablesRule{r}, []int{22})
	if len(risks) != 1 || risks[0].Mode != "docker_block" {
		t.Fatalf("got %+v", risks)
	}
}
