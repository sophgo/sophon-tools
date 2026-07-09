// Package systemd 封装 systemctl/systemd-analyze 命令与关键服务匹配。
// 全部经 system.RunCommandArgs（argv，不经 shell），unit 名额外白名单校验，杜绝注入。
package systemd

// ServiceInfo 服务列表项。
type ServiceInfo struct {
	Name         string `json:"name"`
	Description  string `json:"description"`
	LoadState    string `json:"load_state"`
	ActiveState  string `json:"active_state"`
	SubState     string `json:"sub_state"`
	EnabledState string `json:"enabled_state"`
	Protected    bool   `json:"protected"`
}

// ServiceDetail 单服务详情。
type ServiceDetail struct {
	Name         string `json:"name"`
	LoadState    string `json:"load_state"`
	ActiveState  string `json:"active_state"`
	SubState     string `json:"sub_state"`
	MainPID      string `json:"main_pid"`
	ExecStart    string `json:"exec_start"`
	FragmentPath string `json:"fragment_path"`
	UnitFile     string `json:"unit_file"`
	StatusText   string `json:"status_text"`
	Protected    bool   `json:"protected"`
}

// BlameItem 启动耗时排行项。
type BlameItem struct {
	Time float64 `json:"time"`
	Unit string  `json:"unit"`
}

// BootReport 本次启动时间分析。
type BootReport struct {
	TotalSeconds     float64     `json:"total_seconds"`
	KernelSeconds    float64     `json:"kernel_seconds"`
	UserspaceSeconds float64     `json:"userspace_seconds"`
	Blame            []BlameItem `json:"blame"`
	CriticalChain    string      `json:"critical_chain"`
}
