package firewall

import (
	"fmt"
	"strconv"
	"strings"
)

// cleanChain 删除链上所有带给定前缀注释的规则，从大到小删避免行号移位。
func cleanChain(r CommandRunner, chain string, prefix string) error {
	out, _, _ := r.Run("iptables", "-t", "filter", "-L", chain, "-n", "--line-numbers")
	var nums []int
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, prefix) {
			fields := strings.Fields(line)
			if len(fields) > 0 {
				if n, err := strconv.Atoi(fields[0]); err == nil {
					nums = append(nums, n)
				}
			}
		}
	}
	for i := len(nums) - 1; i >= 0; i-- {
		if _, errStr, err := r.Run("iptables", "-D", chain, strconv.Itoa(nums[i])); err != nil {
			return fmt.Errorf("clean %s %d: %s: %s", chain, nums[i], err, errStr)
		}
	}
	return nil
}

// CleanManaged 删除 INPUT 链上所有受管规则（bmssm-fw-intent 注释）。rebuild 前清场。
// 同时清理旧版遗留的 DOCKER-USER 链 docker 注释与 INPUT 链 protect 临时放行，
// 避免升级后残留。任一 -D 失败返回错误（调用方中止 Rebuild 并回滚）。
func CleanManaged(r CommandRunner) error {
	if err := cleanChain(r, "INPUT", CommentIntentPrefix); err != nil {
		return err
	}
	// 升级兼容：旧版（docker/apply 时代）遗留的受管规则。
	if err := cleanChain(r, "DOCKER-USER", "bmssm-fw-docker"); err != nil {
		return err
	}
	return cleanChain(r, "INPUT", "bmssm-fw-protect")
}
