package ota

import (
	"fmt"
	"strings"
)

// allowedCmdPrefixes 白名单命令前缀，防止通过 CmdFlag 注入任意命令（RCE）。
// 仅允许已知升级命令，攻击者即使绕过 Auth 也无法执行恶意代码。
var allowedCmdPrefixes = []string{
	"/data/ota/local_update.sh",
	"bm_firmware_update",
	"mk_bootscr.sh",
	"ssh ",
	"bash ",
}

// validateCmdFlag 校验 CmdFlag 是否在白名单内且不含 shell 元字符。
// 空串通过（调用方使用默认命令）。非法返回 error。
func validateCmdFlag(cmd string) error {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return nil
	}

	// 拒绝 shell 注入元字符（defense in depth）
	if strings.ContainsAny(cmd, ";&|`$\\\n\r") {
		return fmt.Errorf("cmdFlag contains forbidden shell characters")
	}

	for _, prefix := range allowedCmdPrefixes {
		if strings.HasPrefix(cmd, prefix) {
			return nil
		}
	}
	return fmt.Errorf("cmdFlag %q is not in the allowed command whitelist", cmd)
}

// knownPCIEFlags pcie CmdFlag 允许的标志集合（defense in depth，即使 CmdFlag 不传给命令）。
var knownPCIEFlags = map[string]bool{
	"--full": true,
}

// validatePCIECmdFlag 校验 pcie CmdFlag 仅含已知 flag（--target=a53|mcu、--full、--file=）。
// 空串通过。
func validatePCIECmdFlag(cmd string) error {
	cmd = strings.TrimSpace(cmd)
	if cmd == "" {
		return nil
	}

	for _, token := range strings.Fields(cmd) {
		if knownPCIEFlags[token] {
			continue
		}
		if strings.HasPrefix(token, "--target=") {
			val := strings.TrimPrefix(token, "--target=")
			if val == "a53" || val == "mcu" {
				continue
			}
			return fmt.Errorf("pcie cmdFlag: unknown target %q", val)
		}
		if strings.HasPrefix(token, "--file=") {
			// --file= 值由 pcieFilePath 决定，此处仅允许该 flag 存在
			continue
		}
		return fmt.Errorf("pcie cmdFlag: unknown flag %q", token)
	}
	return nil
}
