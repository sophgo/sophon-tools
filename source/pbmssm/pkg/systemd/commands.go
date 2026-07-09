package systemd

import (
	"fmt"
	"strings"

	"bmssm/pkg/system"
)

// ListServices 列举所有 .service 单元，合并 list-units(文本) 与 list-unit-files(enabled 状态)。
func ListServices() ([]ServiceInfo, error) {
	out, _, err := system.RunCommandArgs("systemctl",
		"list-units", "--type=service", "--all", "--no-pager", "--plain")
	if err != nil {
		return nil, fmt.Errorf("list-units: %v: %s", err, out)
	}
	rows := ParseListUnits(out)
	filesOut, _, _ := system.RunCommandArgs("systemctl",
		"list-unit-files", "--type=service", "--no-pager", "--plain")
	enabled := ParseListUnitFiles(filesOut)
	patterns := ProtectedList()
	svcs := make([]ServiceInfo, 0, len(rows))
	for _, r := range rows {
		svcs = append(svcs, ServiceInfo{
			Name:         r.Unit,
			Description:  r.Description,
			LoadState:    r.Load,
			ActiveState:  r.Active,
			SubState:     r.Sub,
			EnabledState: enabled[r.Unit],
			Protected:    ProtectedMatch(r.Unit, patterns),
		})
	}
	return svcs, nil
}

// ShowStatus 单服务详情：systemctl show（结构化）+ cat（unit 文件）+ status（人类可读+日志）。
func ShowStatus(name string) (*ServiceDetail, error) {
	if err := ValidateUnitName(name); err != nil {
		return nil, err
	}
	patterns := ProtectedList()
	showOut, _, err := system.RunCommandArgs("systemctl", "show", name)
	if err != nil {
		return nil, fmt.Errorf("show: %v: %s", err, showOut)
	}
	d := &ServiceDetail{Name: name, Protected: ProtectedMatch(name, patterns)}
	for _, line := range strings.Split(showOut, "\n") {
		idx := strings.Index(line, "=")
		if idx < 0 {
			continue
		}
		k, v := line[:idx], line[idx+1:]
		switch k {
		case "LoadState":
			d.LoadState = v
		case "ActiveState":
			d.ActiveState = v
		case "SubState":
			d.SubState = v
		case "MainPID":
			d.MainPID = v
		case "ExecStart":
			d.ExecStart = v
		case "FragmentPath":
			d.FragmentPath = v
		}
	}
	if catOut, _, _ := system.RunCommandArgs("systemctl", "cat", name); catOut != "" {
		d.UnitFile = catOut
	}
	if stOut, _, _ := system.RunCommandArgs("systemctl", "status", name, "--no-pager", "-l", "-n", "50"); stOut != "" {
		d.StatusText = stOut
	}
	return d, nil
}

// Action 执行 start/stop/restart/reload/enable/disable；关键服务返 ErrProtected。
func Action(name, action string) error {
	if err := ValidateUnitName(name); err != nil {
		return err
	}
	allowed := map[string]bool{
		"start": true, "stop": true, "restart": true,
		"reload": true, "enable": true, "disable": true,
	}
	if !allowed[action] {
		return fmt.Errorf("%w: %q", ErrInvalidAction, action)
	}
	if ProtectedMatch(name, ProtectedList()) {
		return ErrProtected
	}
	out, errStr, err := system.RunCommandArgs("systemctl", action, name)
	if err != nil {
		return fmt.Errorf("%s %s: %v: %s", action, name, err, errStr+out)
	}
	return nil
}

// DaemonReload 全局 systemctl daemon-reload。
func DaemonReload() error {
	_, errStr, err := system.RunCommandArgs("systemctl", "daemon-reload")
	if err != nil {
		return fmt.Errorf("daemon-reload: %v: %s", err, errStr)
	}
	return nil
}

// GetBootReport 本次启动分析：time + blame + critical-chain。
func GetBootReport() (*BootReport, error) {
	timeOut, _, err := system.RunCommandArgs("systemd-analyze", "--no-pager", "time")
	if err != nil {
		return nil, fmt.Errorf("systemd-analyze time: %v: %s", err, timeOut)
	}
	k, u, tot := ParseAnalyzeTime(timeOut)
	blameOut, _, _ := system.RunCommandArgs("systemd-analyze", "--no-pager", "blame")
	chainOut, _, _ := system.RunCommandArgs("systemd-analyze", "--no-pager", "critical-chain")
	return &BootReport{
		TotalSeconds:     tot,
		KernelSeconds:    k,
		UserspaceSeconds: u,
		Blame:            ParseBlame(blameOut),
		CriticalChain:    chainOut,
	}, nil
}

// BootReportSVG 生成 systemd-analyze plot 的 SVG。
func BootReportSVG() ([]byte, error) {
	out, _, err := system.RunCommandArgs("systemd-analyze", "plot")
	if err != nil {
		return nil, fmt.Errorf("plot: %v: %s", err, out)
	}
	return []byte(out), nil
}
