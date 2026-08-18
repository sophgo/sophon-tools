package compat

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	"bytes"
	"context"

	"github.com/gin-gonic/gin"

	"bmssm/config"
	"bmssm/database"
	"bmssm/global"
	"bmssm/logger"
	"bmssm/mvc/audit"
	"bmssm/mvc/hardware"
	"bmssm/mvc/software"
	"bmssm/mvc/user"
	"bmssm/pkg/auth"
	"bmssm/pkg/hazard"
	netpkg "bmssm/pkg/network"
	"bmssm/pkg/ota"
	"bmssm/pkg/response"
)

// ---------------------------------------------------------------
// Controller 兼容层 gin handler 集合
// ---------------------------------------------------------------

// Controller 提供 /bitmain/v1/ssm/* 兼容路由处理。
type Controller struct {
	svc       *CompatService
	hwSvc     *hardware.HardwareService
	swSvc     *software.SoftwareService
	userSvc   *user.UserService
	otaEngine *ota.Engine
	aud       *audit.AuditService
}

// NewController 创建兼容控制器。
func NewController(svc *CompatService, hwSvc *hardware.HardwareService, swSvc *software.SoftwareService, userSvc *user.UserService, otaEngine *ota.Engine) *Controller {
	return &Controller{
		svc:       svc,
		hwSvc:     hwSvc,
		swSvc:     swSvc,
		userSvc:   userSvc,
		otaEngine: otaEngine,
	}
}

// DefaultController 构建默认控制器（生产环境依赖注入）。
func DefaultController() *Controller {
	ctrl := NewController(
		DefaultCompatService(),
		hardware.NewDefaultService(),
		software.DefaultService(),
		user.NewService(database.DB()),
		ota.DefaultEngine(),
	)
	ctrl.aud = audit.NewService(database.DB())
	return ctrl
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// requireHazardGuard 校验二次确认码并占用高危互斥锁（MYS-389）。
// 返回 guard 与 bool：false 时已写出错误响应，直接 return。
func (ctrl *Controller) requireHazardGuard(c *gin.Context, holder, action, resource, confirm string) (*hazard.Guard, bool) {
	username, _ := c.Get("user")
	uname, _ := username.(string)
	if !hazard.VerifyConfirmCode(confirm) {
		ctrl.auditWrite(c, uname, action, resource, "confirmation_failed")
		c.JSON(http.StatusForbidden, response.Fail("confirmation required: fetch /api/v1/hazard/challenge first"))
		return nil, false
	}
	guard, err := hazard.HazardOps.TryAcquire(holder)
	if err != nil {
		ctrl.auditWrite(c, uname, action, resource, "blocked")
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return nil, false
	}
	return guard, true
}

// getSecret 从配置获取 JWT secret（TerminalWS query token 校验等使用）。
func getSecret() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	secret := conf.GetViper().GetString("server.authSecret")
	if secret == "" {
		secret = auth.DefaultSecret
	}
	return secret
}

// ---------------------------------------------------------------
// Device Basic
// ---------------------------------------------------------------

// GetCtrlBasic GET /bitmain/v1/ssm/software/device/basic
func (ctrl *Controller) GetCtrlBasic(c *gin.Context) {
	basic, err := ctrl.svc.BuildCtrlBasic()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(basic))
}

// ---------------------------------------------------------------
// Device Resource
// ---------------------------------------------------------------

// GetCtrlResource GET /bitmain/v1/ssm/software/device/resource/list?all=0
func (ctrl *Controller) GetCtrlResource(c *gin.Context) {
	resources := ctrl.svc.BuildCtrlResource()
	c.JSON(http.StatusOK, response.OK(resources))
}

// ---------------------------------------------------------------
// IP
// ---------------------------------------------------------------

// GetIP GET /bitmain/v1/ssm/hardware/ip
func (ctrl *Controller) GetIP(c *gin.Context) {
	ipList, err := ctrl.svc.BuildIPList()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(ipList))
}

// SetIP POST /bitmain/v1/ssm/hardware/ip
func (ctrl *Controller) SetIP(c *gin.Context) {
	var req IPSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	err := netpkg.SetIP(netpkg.IPConfig{
		Device:   req.Device,
		IPType:   req.IPType,
		IP:       req.IP,
		Mask:     req.SubnetMask,
		Gateway:  req.Gateway,
		DNS:      req.DNS,
		IPv6Type: req.IPv6Type,
		IPv6:     req.IPv6,
		Prefix6:  req.Prefix6,
		Gateway6: req.Gateway6,
		DNS6:     req.DNS6,
	})

	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(nil))
}

// ---------------------------------------------------------------
// NAT
// ---------------------------------------------------------------

// GetNAT GET /bitmain/v1/ssm/hardware/nat
func (ctrl *Controller) GetNAT(c *gin.Context) {
	rules, err := netpkg.GetNATRules()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(rules))
}

// AddNAT POST /bitmain/v1/ssm/hardware/nat
func (ctrl *Controller) AddNAT(c *gin.Context) {
	var req AddTable
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// 将 sophliteos AddTable 映射为 netpkg.NatRule
	direction := "out"
	if req.Dirt == "in" {
		direction = "in"
	}
	operation := "append"
	if req.Op == "delete" {
		operation = "delete"
	}

	rule := netpkg.NatRule{
		Direction: direction,
		Operation: operation,
		Src:       req.Src,
		Dst:       req.Dst,
		SrcPort:   req.SrcPort,
		DstPort:   req.DstPort,
		Protocol:  req.Protocol,
	}

	if err := netpkg.AddNATRule(rule); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(nil))
}

// numRe 限定 nat 规则编号为数字（防注入）。
var numRe = regexp.MustCompile(`^[1-9][0-9]*$`)

// DeleteNAT DELETE /bitmain/v1/ssm/hardware/nat/PREROUTING-:num
func (ctrl *Controller) DeleteNAT(c *gin.Context) {
	num := c.Param("num")
	if !numRe.MatchString(num) {
		c.JSON(http.StatusBadRequest, response.Fail("invalid rule number"))
		return
	}

	if err := DeleteNATRule(num); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(nil))
}

// ---------------------------------------------------------------
// 重启 / 关机
// ---------------------------------------------------------------

// 重启走已挂载的 hwCtrl.Reboot（router admin 组 /hardware/reboot，
// 含 MYS-389 二次确认+高危互斥），compat 未挂载的 Reboot 已删除。

// uname 从 gin context 取用户名（middleware.Auth 注入）。
func uname(c *gin.Context) string {
	u, _ := c.Get("user")
	s, _ := u.(string)
	return s
}

// Shutdown POST /bitmain/v1/ssm/hardware/devices/down
func (ctrl *Controller) Shutdown(c *gin.Context) {
	var req struct {
		CoreOpe
		Confirm string `json:"confirm"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// MYS-389：二次确认 + 高危互斥 + 审计
	guard, ok := ctrl.requireHazardGuard(c, "shutdown", "shutdown", "hardware", req.Confirm)
	if !ok {
		return
	}
	defer guard.Release()

	if err := Shutdown(); err != nil {
		ctrl.auditWrite(c, uname(c), "shutdown", "hardware", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, uname(c), "shutdown", "hardware", "success")
	c.JSON(http.StatusOK, response.OK(nil))
}

// ---------------------------------------------------------------
// 告警订阅
// ---------------------------------------------------------------

// SubscribeAlarm POST /bitmain/v1/ssm/software/notify/subscribe
func (ctrl *Controller) SubscribeAlarm(c *gin.Context) {
	var req SubscribeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	ctrl.svc.Subscribe(req)
	c.JSON(http.StatusOK, response.OK(nil))
}

// UnsubscribeAlarm POST /bitmain/v1/ssm/software/notify/unsubscribe
func (ctrl *Controller) UnsubscribeAlarm(c *gin.Context) {
	var req SubscribeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	ctrl.svc.Unsubscribe(req.Platform)
	c.JSON(http.StatusOK, response.OK(nil))
}

// GetSubscription GET /bitmain/v1/ssm/software/notify/subscribe/:name
func (ctrl *Controller) GetSubscription(c *gin.Context) {
	name := c.Param("name")
	if name == "" {
		c.JSON(http.StatusBadRequest, response.Fail("missing name"))
		return
	}

	sub, ok := ctrl.svc.GetSubscription(name)
	if !ok {
		c.JSON(http.StatusOK, response.OK(nil))
		return
	}

	c.JSON(http.StatusOK, response.OK(sub))
}

// ---------------------------------------------------------------
// 设备配置
// ---------------------------------------------------------------

// SetBasic POST /api/v1/device/configure/basic
// 真实实现（MYS-390，不再静默假成功）：
//   - 修改系统 hostname（运行时 + /etc/hostname 持久化），失败如实报 500
//   - 持久化 server.deviceName 到配置（GetCtrlBasic 的 deviceName 读取源）
//
// deviceType 不落盘：设备型号由全局设备信息决定，不允许用户改写。
func (ctrl *Controller) SetBasic(c *gin.Context) {
	var req BasicSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	name := strings.TrimSpace(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, response.Fail("deviceName is required"))
		return
	}
	if !hostnameRe.MatchString(name) {
		c.JSON(http.StatusBadRequest, response.Fail("invalid deviceName: only letters, digits, '-' and '.' allowed"))
		return
	}

	// 1) 系统 hostname（失败如实报错；此时配置未动，保持状态一致）
	if err := hostnameSetter(name); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("set hostname: "+err.Error()))
		return
	}

	// 2) 配置持久化（GetCtrlBasic 的 deviceName 读取源），
	// WriteConfig 失败降级为仅内存更新（与 SetAlarm 同模式：主机名已生效）
	config.Conf.Lock()
	defer config.Conf.Unlock()
	v := config.Conf.GetViper()
	v.Set("server.deviceName", name)
	if err := v.WriteConfig(); err != nil {
		logger.Warn("SetBasic WriteConfig failed (in-memory only): %v", err)
	}
	c.JSON(http.StatusOK, response.OK(nil))
}

// hostnameRe 限定 deviceName 为合法 hostname：字母/数字开头结尾，中间含
// 字母数字、'-'、'.'，最长 63。
var hostnameRe = regexp.MustCompile(`^[A-Za-z0-9]([A-Za-z0-9.-]{0,61}[A-Za-z0-9])?$`)

// hostnameSetter 修改系统 hostname（包级变量，测试注入 fake 替换）。
var hostnameSetter = realSetHostname

// realSetHostname 运行时设置 hostname 并持久化到 /etc/hostname。
func realSetHostname(name string) error {
	if err := syscall.Sethostname([]byte(name)); err != nil {
		return err
	}
	// 持久化失败不阻断：运行时已生效，仅告警
	if err := os.WriteFile("/etc/hostname", []byte(name+"\n"), 0o644); err != nil {
		logger.Warn("SetBasic persist /etc/hostname failed (runtime hostname applied): %v", err)
	}
	return nil
}

// SetAlarm POST /api/v1/device/configure/alarm
// 持久化告警阈值到配置文件，对齐 bmssm WriteAlarmConfig 行为。
func (ctrl *Controller) SetAlarm(c *gin.Context) {
	var req AlarmThreshold
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	config.Conf.Lock()
	v := config.Conf.GetViper()
	v.Set("alarmThreshold.boardTemperature", req.BoardTemperature)
	v.Set("alarmThreshold.coreTemperature", req.CoreTemperature)
	v.Set("alarmThreshold.cpuRate", req.CpuRate)
	v.Set("alarmThreshold.diskRate", req.DiskRate)
	v.Set("alarmThreshold.totalMemoryScale", req.TotalMemoryScale)
	v.Set("alarmThreshold.tpuRate", req.TpuRate)
	v.Set("alarmThreshold.tpuScale", req.TpuScale)

	if err := v.WriteConfig(); err != nil {
		// WriteConfig 失败时降级为仅内存更新（例如无配置文件路径）
		config.Conf.Unlock()
		logger.Warn("SetAlarm WriteConfig failed (in-memory only): %v", err)
		c.JSON(http.StatusOK, response.OK(nil))
		return
	}
	config.Conf.Unlock()

	c.JSON(http.StatusOK, response.OK(nil))
}

// GetAlarm GET /api/v1/device/configure/alarm
// 返回当前告警阈值（与 BuildCtrlBasic 的 alarmThreshold 字段同源）。
func (ctrl *Controller) GetAlarm(c *gin.Context) {
	config.Conf.RLock()
	v := config.Conf.GetViper()
	at := AlarmThreshold{
		BoardTemperature: int(v.GetFloat64("alarmThreshold.boardTemperature")),
		CoreTemperature:  int(v.GetFloat64("alarmThreshold.coreTemperature")),
		CpuRate:          v.GetFloat64("alarmThreshold.cpuRate"),
		DiskRate:         v.GetFloat64("alarmThreshold.diskRate"),
		TotalMemoryScale: v.GetFloat64("alarmThreshold.totalMemoryScale"),
		TpuRate:          v.GetFloat64("alarmThreshold.tpuRate"),
		TpuScale:         v.GetFloat64("alarmThreshold.tpuScale"),
	}
	config.Conf.RUnlock()
	c.JSON(http.StatusOK, response.OK(at))
}

// ---------------------------------------------------------------
// OTA 固件上传
// ---------------------------------------------------------------

// UploadFirmware POST /bitmain/v1/ssm/file/ota
// 接收 multipart .tgz 刷机包，按 module（form 字段，默认 soc）保存到对应目录。
func (ctrl *Controller) UploadFirmware(c *gin.Context) {
	// MYS-389：OTA 上传记审计
	ctrl.auditWrite(c, uname(c), "ota.upload", "ota", "attempted")
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("missing file field"))
		return
	}
	defer file.Close()

	origName := header.Filename
	// 大小限制
	if ctrl.swSvc.GetMaxSize() > 0 && header.Size > ctrl.swSvc.GetMaxSize() {
		c.JSON(http.StatusBadRequest, response.Fail(fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.swSvc.GetMaxSize())))
		return
	}

	module := strings.TrimSpace(c.DefaultPostForm("module", "soc"))
	if module == "" {
		module = "soc"
	}

	// 落盘到 OTA 临时路径（复用 SoftwareService 的 otaDir 作暂存）
	savePath := filepath.Join(ctrl.swSvc.GetOTADir(), "tmp_"+filepath.Base(origName))
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("save file failed"))
		return
	}
	savedPath, err := ctrl.otaEngine.OTAUpload(module, origName, savePath, header.Size)
	_ = os.Remove(savePath) // 清理临时文件
	if err != nil {
		c.JSON(http.StatusBadRequest, response.Fail(err.Error()))
		return
	}

	c.JSON(http.StatusOK, response.OK(map[string]interface{}{
		"fileName": filepath.Base(savedPath),
		"path":     savedPath,
		"module":   module,
		"fileSize": header.Size,
	}))
}

// ---------------------------------------------------------------
// OTA 升级 workflow
// ---------------------------------------------------------------

// ExecuteUpgrade POST /bitmain/v1/ssm/workflow/upgrade
// 解析 OtaVersion body，入队 Type=Upgrade 的 workflow，立即返 "add workflow success"。
func (ctrl *Controller) ExecuteUpgrade(c *gin.Context) {
	var req OtaVersion
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// MYS-389：二次确认 + 高危互斥 + 审计
	guard, ok := ctrl.requireHazardGuard(c, "ota.upgrade", "ota.upgrade", "ota", req.Confirm)
	if !ok {
		return
	}
	defer guard.Release()
	// Product 为空时用设备实际型号兜底（global.DeviceTypeEx 形如 "SE7 V01"），
	// 否则 productClass 识别不到会返回 "ota: path not implemented"。
	product := req.Product
	if strings.TrimSpace(product) == "" {
		product = global.DeviceTypeEx
	}
	flow := ota.Workflow{
		Product:    product,
		ModuleName: req.ModuleName,
		FileName:   req.FileName,
		CmdFlag:    req.CmdFlag,
		Version:    req.Version,
		Name:       req.Name,
		Type:       ota.TypeUpgrade,
		FlashData:  req.FlashData,
	}
	if err := ctrl.otaEngine.EnqueueFlow(&flow); err != nil {
		ctrl.auditWrite(c, uname(c), "ota.upgrade", "ota", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, uname(c), "ota.upgrade", "ota", "success")
	c.JSON(http.StatusOK, response.OK("add workflow success"))
}

// Rollback POST /bitmain/v1/ssm/workflow/rollback
// 入队 Type=Rollback 的 workflow，立即返 "add workflow success"。
func (ctrl *Controller) Rollback(c *gin.Context) {
	var req OtaVersion
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// MYS-389：二次确认 + 高危互斥 + 审计
	guard, ok := ctrl.requireHazardGuard(c, "ota.rollback", "ota.rollback", "ota", req.Confirm)
	if !ok {
		return
	}
	defer guard.Release()

	product := req.Product
	if strings.TrimSpace(product) == "" {
		product = global.DeviceTypeEx
	}
	flow := ota.Workflow{
		Product:    product,
		ModuleName: req.ModuleName,
		FileName:   req.FileName,
		CmdFlag:    req.CmdFlag,
		Version:    req.Version,
		Name:       req.Name,
		Type:       ota.TypeRollback,
		FlashData:  req.FlashData,
	}
	if err := ctrl.otaEngine.EnqueueFlow(&flow); err != nil {
		ctrl.auditWrite(c, uname(c), "ota.rollback", "ota", "failed")
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, uname(c), "ota.rollback", "ota", "success")
	c.JSON(http.StatusOK, response.OK("add workflow success"))
}

// ListWorkflows GET /bitmain/v1/ssm/workflow/upgrade
// 列出全部 workflow 状态（SsmResult.result=flows）。
func (ctrl *Controller) ListWorkflows(c *gin.Context) {
	flows, err := ctrl.otaEngine.QueryAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	c.JSON(http.StatusOK, response.OK(flows))
}

// GetWorkflow GET /bitmain/v1/ssm/workflow/upgrade/:id
// 查询单个 workflow 状态。
func (ctrl *Controller) GetWorkflow(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, response.Fail("missing workflow id"))
		return
	}
	flow, err := ctrl.otaEngine.Query(id)
	if err != nil {
		c.JSON(http.StatusOK, response.Fail("workflow not found"))
		return
	}
	c.JSON(http.StatusOK, response.OK(flow))
}

// ---------------------------------------------------------------
// 降级路由（不支持的操作）
// ---------------------------------------------------------------

// SCP POST /bitmain/v1/ssm/hardware/devices/scp
// 未实现：如实返回 501 Not Implemented，杜绝调用方误以为操作成功（MYS-390）。
func (ctrl *Controller) SCP(c *gin.Context) {
	c.JSON(http.StatusNotImplemented, response.Fail("scp not supported"))
}

// Exec POST /bitmain/v1/ssm/hardware/devices/exec
// 执行单条 shell 命令（sh -c），返回 stdout/stderr/exitCode。
// 超时默认 30s，上限 300s。危险命令在此不拦截——前端仅用于只读诊断，
// 真正的交互式终端走 /api/v1/hardware/terminal（WebSocket pty）。
func (ctrl *Controller) Exec(c *gin.Context) {
	var req struct {
		Command string `json:"command" binding:"required"`
		Timeout int    `json:"timeout"`
	}
	// MYS-389：exec 记审计（保留只读诊断能力，不强制二次确认）
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	timeout := 30
	if req.Timeout > 0 {
		timeout = req.Timeout
	}
	if timeout > 300 {
		timeout = 300
	}
	ctx, cancel := context.WithTimeout(c, time.Duration(timeout)*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "sh", "-c", req.Command)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			exitCode = ee.ExitCode()
		} else {
			exitCode = -1
		}
	}
	res := "success"
	if exitCode != 0 {
		res = "failed"
	}
	ctrl.auditWrite(c, uname(c), "exec", "hardware.exec", res)
	c.JSON(http.StatusOK, response.OK(gin.H{
		"stdout":   stdout.String(),
		"stderr":   stderr.String(),
		"exitCode": exitCode,
	}))
}
