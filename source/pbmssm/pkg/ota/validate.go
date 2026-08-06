package ota

import (
	"fmt"
	"strings"
)

// allowedCmdPrefixes 白名单命令名，防止通过 CmdFlag 注入任意命令（RCE）。
// 只允许已知升级命令。命令经参数化执行（splitCmdFlag → runner(name, args...)），
// 不经 bash -c，因此即使白名单含 ssh 也不会被解释器展开任意字符串。
var allowedCmdPrefixes = []string{
	"/data/ota/local_update.sh",
	"bm_firmware_update",
	"mk_bootscr.sh",
	"ssh",
}

// validateCmdFlag 校验 CmdFlag 是否合法（供依赖旧 API 的调用方/测试使用）。
// 空串通过（调用方使用默认命令）。非法返回 error。
func validateCmdFlag(cmd string) error {
	if strings.TrimSpace(cmd) == "" {
		return nil
	}
	_, err := splitCmdFlag(cmd)
	return err
}

// isSafeFlagRune 允许 CmdFlag 参数中的字符：字母数字、下划线、点、斜杠、等号、短横线、@（ssh user@host）。
func isSafeFlagRune(r rune) bool {
	return (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
		(r >= '0' && r <= '9') || r == '_' || r == '.' || r == '/' ||
		r == '=' || r == '-' || r == '@'
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
