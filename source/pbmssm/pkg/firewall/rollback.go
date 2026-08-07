package firewall

import (
	"fmt"
	"strconv"
	"strings"

	"bmssm/logger"
)

// cleanChain 删除链上所有带给定前缀注释的规则，从大到小删避免行号移位。
// 列表命令失败返回错误（不再静默判定"已清干净"，防止残留旧规则被重复插入）。
func cleanChain(r CommandRunner, chain string, prefix string) error {
	out, errStr, err := r.Run("iptables", "-t", "filter", "-L", chain, "-n", "--line-numbers")
	if err != nil {
		return fmt.Errorf("list %s: %s: %s", chain, err, errStr)
	}
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

// CleanManaged 删除 INPUT 链上所有受管规则（bmssm-fw-intent / bmssm-fw-protect 注释）。
// rebuild 前清场。INPUT 链列表失败返回错误（不静默判定"已清干净"，防止残留旧规则被重复插入）。
// DOCKER-USER 链（旧版 docker 功能遗留）按 best-effort 清理：该链只存在于安装 Docker 的设备，
// 无 Docker / Docker 未启动时链不存在，若此处硬错误会中止整个 Rebuild——而防火墙必须在
// 无 Docker 设备上独立工作（本 PR 已移除 Docker 防火墙功能）。
func CleanManaged(r CommandRunner) error {
	if err := cleanChain(r, "INPUT", CommentIntentPrefix); err != nil {
		return err
	}
	// 升级兼容：旧版（docker/apply 时代）遗留的受管规则。
	cleanLegacyChain(r, "DOCKER-USER", "bmssm-fw-docker")
	return cleanChain(r, "INPUT", "bmssm-fw-protect")
}

// cleanLegacyChain 清理旧版遗留链上的受管规则。链不存在或列表/删除失败时记警告继续，
// 不中止调用方（遗留清理失败不影响主路径）。
func cleanLegacyChain(r CommandRunner, chain string, prefix string) {
	out, errStr, err := r.Run("iptables", "-t", "filter", "-L", chain, "-n", "--line-numbers")
	if err != nil {
		// 链不存在（无 Docker / Docker 未启动）视为无残留直接跳过。
		logger.Warn("firewall: skip legacy chain %s, list failed: %s: %s", chain, err, errStr)
		return
	}
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
			logger.Warn("firewall: clean legacy %s %d: %s %s", chain, nums[i], err, errStr)
		}
	}
}
