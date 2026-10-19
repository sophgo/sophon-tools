package main

// 局域网扫描的 HTTP 接口（Web 版与桌面版共用同一套扫描实现）。

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
)

// handleScanIfaces 列出可用网口及其 IPv4 网段，供前端下拉选择。
func (ws *webServer) handleScanIfaces(w http.ResponseWriter, r *http.Request) {
	type ifaceDTO struct {
		Name    string   `json:"name"`
		Addrs   []string `json:"addrs"`
		CIDRs   []string `json:"cidrs"`
		Default string   `json:"defaultCidr"`
	}
	infos := []ifaceDTO{}
	for _, name := range listScanInterfaces() {
		dto := ifaceDTO{Name: name, Default: guessLocalCIDR(name)}
		if dto.Default != "" {
			dto.CIDRs = append(dto.CIDRs, dto.Default)
		}
		infos = append(infos, dto)
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"interfaces": infos,
		// 无权限时前端要提示用户怎么授权
		"privileged": isPrivilegedForRawSocket(),
	})
}

// handleScan 执行一次扫描。POST，参数：iface / cidr / macPrefix / timeoutSec。
func (ws *webServer) handleScan(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	var body struct {
		Interface  string `json:"iface"`
		CIDR       string `json:"cidr"`
		MACPrefix  string `json:"macPrefix"`
		TimeoutSec int    `json:"timeoutSec"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}
	prefix, err := NormalizeMACPrefix(body.MACPrefix)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	to := body.TimeoutSec
	if to <= 0 {
		to = 4
	}
	if to > 60 {
		to = 60
	}

	res, err := ScanLAN(r.Context(), ScanOptions{
		Interface: body.Interface,
		CIDR:      body.CIDR,
		MACPrefix: prefix,
		Timeout:   secondsDur(to),
	})
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
}

// handleScanAdd 把选中的扫描结果批量加入设备列表。
func (ws *webServer) handleScanAdd(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "只支持 POST")
		return
	}
	if ws.isRunning() {
		writeErr(w, http.StatusConflict, "批量任务执行中，配置已锁定")
		return
	}
	var body struct {
		Hosts    []string `json:"hosts"`
		Port     int      `json:"port"`
		Username string   `json:"username"`
		Password string   `json:"password"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "请求格式错误: "+err.Error())
		return
	}
	if body.Port <= 0 || body.Port > 65535 {
		writeErr(w, http.StatusBadRequest, "SSH 端口必须是 1-65535 的整数")
		return
	}
	if strings.TrimSpace(body.Username) == "" {
		writeErr(w, http.StatusBadRequest, "用户名不能为空")
		return
	}

	existing := map[string]bool{}
	for _, d := range ws.state.Devices() {
		existing[d.Inf.IP] = true
	}
	added, skipped, bad := 0, 0, 0
	for _, h := range body.Hosts {
		h = strings.TrimSpace(h)
		if h == "" {
			continue
		}
		if existing[h] {
			skipped++
			continue
		}
		ws.state.AppendDevice(RemoteInf{
			IP: h, Port: body.Port, Username: body.Username, Password: body.Password,
		})
		existing[h] = true
		added++
	}
	_ = strconv.Itoa(0)

	out := ws.snapshot()
	writeJSON(w, http.StatusOK, map[string]any{
		"added": added, "skipped": skipped, "invalid": bad,
		"state": out,
	})
}
