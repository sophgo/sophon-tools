package firewall

import (
	"strconv"
)

type Risk struct {
	Mode        string       `json:"mode"`        // direct_block / policy_block / docker_block
	Description string       `json:"description"`
	Rule        IptablesRule `json:"rule"`
}

// CheckRisks 检测规则集是否会屏蔽 protect 端口。纯逻辑。
func CheckRisks(rules []IptablesRule, protectPorts []int) []Risk {
	protectSet := map[int]bool{}
	for _, p := range protectPorts {
		protectSet[p] = true
	}
	var risks []Risk

	// 先扫直接屏蔽 + 收集 INPUT policy + 放行的 protect 端口
	inputPolicyDrop := false
	allowedProtect := map[int]bool{}
	for _, r := range rules {
		// policy 表示：Args 含 "--policy"
		if hasArg(r.Args, "--policy") {
			if r.Chain == "INPUT" && hasArg(r.Args, "DROP") {
				inputPolicyDrop = true
			}
			continue
		}
		isDropOrReject := hasArg(r.Args, "DROP") || hasArg(r.Args, "REJECT")
		isAccept := hasArg(r.Args, "ACCEPT")
		dport := dportOf(r.Args)
		// 直接屏蔽：INPUT/FORWARD 入向 DROP protect 端口
		if isDropOrReject && dport > 0 && protectSet[dport] && (r.Chain == "INPUT" || r.Chain == "FORWARD") {
			risks = append(risks, Risk{Mode: "direct_block", Description: "规则 DROP/REJECT 了保护端口 " + strconv.Itoa(dport), Rule: r})
		}
		// DOCKER-USER 屏蔽 protect 端口
		if isDropOrReject && dport > 0 && protectSet[dport] && r.Chain == "DOCKER-USER" {
			risks = append(risks, Risk{Mode: "docker_block", Description: "DOCKER-USER 规则 DROP 了保护端口 " + strconv.Itoa(dport), Rule: r})
		}
		// 收集放行
		if isAccept && dport > 0 && r.Chain == "INPUT" && protectSet[dport] {
			allowedProtect[dport] = true
		}
	}
	// 默认 policy 屏蔽：INPUT policy DROP 且有 protect 端口未被放行
	if inputPolicyDrop {
		for p := range protectSet {
			if !allowedProtect[p] {
				risks = append(risks, Risk{Mode: "policy_block", Description: "INPUT 默认策略 DROP 且未放行保护端口 " + strconv.Itoa(p), Rule: IptablesRule{Chain: "INPUT", Args: []string{"--policy", "DROP"}}})
			}
		}
	}
	return risks
}

func hasArg(args []string, s string) bool {
	for _, a := range args {
		if a == s {
			return true
		}
	}
	return false
}

func dportOf(args []string) int {
	for i, a := range args {
		if a == "--dport" && i+1 < len(args) {
			p, err := strconv.Atoi(args[i+1])
			if err == nil {
				return p
			}
		}
	}
	return 0
}
