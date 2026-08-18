package agentproxy

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"bmssm/logger"
	"bmssm/mvc/llmproxy"
)

// 上下文预算（需求：LLM ApiBase = sophnet 云端 → 200K；本地模型 → 20K）。
const (
	contextWindowSophnet = 200000
	contextWindowLocal   = 20000
)

var contextWindowRe = regexp.MustCompile(`(?m)^(\s*context_window\s*=\s*)\d+(\s*$)`)

// ApplyReasonixContextWindow 依据 LLM 上游 API Base 重写 reasonix config.toml 的
// context_window，并重启 reasonix 使新上下文预算生效（reasonix 仅启动时读 config）。
// 通过 llmproxy.RegisterContextWindowApplier 注册；llm-proxy 每次保存配置时回调。
func ApplyReasonixContextWindow(apiBase string) error {
	globalMu.Lock()
	m := globalMod
	globalMu.Unlock()

	cfgPath := filepath.Join(reasonixHomeDir(), ".reasonix", "config.toml")
	raw, err := os.ReadFile(cfgPath)
	if err != nil {
		// config 文件缺失（reasonix 尚未铺数据）不视为错误：保持默认模板值即可。
		logger.Info("agentproxy: reasonix config.toml not present (%v), skip context rewrite", err)
		return nil
	}
	window := contextWindowFor(apiBase)
	replaced, changed, err := rewriteContextWindow(raw, window)
	if err != nil {
		return err
	}
	if !changed {
		return nil
	}
	if err := os.WriteFile(cfgPath, replaced, 0o644); err != nil {
		return err
	}
	logger.Info("agentproxy: reasonix context_window -> %d (%s), %s", window, modeLabel(window), cfgPath)
	// 重启 reasonix 使其重新读取 config（仅在进程正在运行时）。
	if m != nil && m.pm != nil && m.pm.Alive() {
		m.pm.restart()
	}
	return nil
}

// contextWindowFor 按 LLM 上游分流上下文预算：sophnet 云端 → 200K，本地 → 20K。
func contextWindowFor(apiBase string) int {
	if strings.TrimSpace(apiBase) == llmproxy.SophnetApiBase {
		return contextWindowSophnet
	}
	return contextWindowLocal
}

func modeLabel(w int) string {
	if w == contextWindowSophnet {
		return "sophnet"
	}
	return "local"
}

// rewriteContextWindow 把 config.toml 里首个 context_window 替换为指定值。
// 返回替换后的字节、是否发生变更；文件无该键则报错。
func rewriteContextWindow(raw []byte, window int) ([]byte, bool, error) {
	if !contextWindowRe.Match(raw) {
		return nil, false, errors.New("no context_window key in config.toml")
	}
	replaced := contextWindowRe.ReplaceAll(raw, []byte("${1}"+strconv.Itoa(window)))
	if bytes.Equal(replaced, raw) {
		return raw, false, nil
	}
	return replaced, true, nil
}

// reasonixHomeDir 复用 process manager 的主目录探测逻辑（SOPHON_REASONIX_HOME 优先）。
func reasonixHomeDir() string {
	if h := os.Getenv("SOPHON_REASONIX_HOME"); h != "" {
		return h
	}
	return DefaultReasonixHome
}
