package compat

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
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
	"bmssm/mvc/ops"
	"bmssm/mvc/software"
	"bmssm/mvc/user"
	"bmssm/pkg/auth"
	netpkg "bmssm/pkg/network"
	"bmssm/pkg/oplock"
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
	// aud 审计服务（nil 安全）：shutdown/exec/OTA 等危险操作记入 audit_logs（MYS-389）。
	aud *audit.AuditService
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

// NewControllerWithAudit 创建兼容控制器（带审计服务）。
func NewControllerWithAudit(svc *CompatService, hwSvc *hardware.HardwareService, swSvc *software.SoftwareService, userSvc *user.UserService, otaEngine *ota.Engine, aud *audit.AuditService) *Controller {
	ctrl := NewController(svc, hwSvc, swSvc, userSvc, otaEngine)
	ctrl.aud = aud
	return ctrl
}

// DefaultController 构建默认控制器（生产环境依赖注入）。
func DefaultController() *Controller {
	return NewControllerWithAudit(
		DefaultCompatService(),
		hardware.NewDefaultService(),
		software.DefaultService(),
		user.NewService(database.DB()),
		ota.DefaultEngine(),
		audit.NewService(database.DB()),
	)
}

// auditWrite 写入审计日志（忽略错误，不阻塞主流程）。
func (ctrl *Controller) auditWrite(c *gin.Context, username, action, resource, result string) {
	if ctrl.aud == nil {
		return
	}
	_ = ctrl.aud.Write(username, action, resource, c.ClientIP(), result)
}

// currentUser 从 gin context 读取当前用户名（Auth 中间件写入）。
func currentUser(c *gin.Context) string {
	username, _ := c.Get("user")
	name, _ := username.(string)
	return name
}

// getSecret 从配置获取 JWT secret。
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
// Login
// ---------------------------------------------------------------

// Login POST /api/v1/login（compat 形态）
// 与 user.Controller.Login 一致：默认密码登录返回临时 token + changePass=true。
func (ctrl *Controller) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	user, err := ctrl.userSvc.Login(req.UserName, req.Password)
	if err != nil {
		c.JSON(http.StatusUnauthorized, response.Fail(err.Error()))
		return
	}

	temp := req.Password == getDefaultPassword()
	tokenStr, _, err := auth.IssueToken(user.Username, getSecret(), temp)
	if err != nil {
		c.JSON(http.StatusInternalServerError, response.Fail("failed to issue token"))
		return
	}

	c.JSON(http.StatusOK, response.OK(SystemLoginResponse{
		Token:      tokenStr,
		Role:       user.Role,
		ChangePass: temp,
	}))
}

// getDefaultPassword 从配置读取默认密码（用于判定是否需强制改密）。
func getDefaultPassword() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	p := conf.GetViper().GetString("server.defaultPassword")
	if p == "" {
		p = "admin"
	}
	return p
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

// Reboot POST /bitmain/v1/ssm/hardware/devices/reset
// 复用 hardware.HardwareService 的 Rebooter（生产用 osRebooter）。
// 高危操作防护（MYS-389）：确认码 + 危险操作互斥锁 + 审计。
func (ctrl *Controller) Reboot(c *gin.Context) {
	var req CoreOpe
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	name := currentUser(c)
	if !ops.Verify(c, "reboot", req.ConfirmCode) {
		ctrl.auditWrite(c, name, "reboot", "hardware", "blocked: missing/invalid confirm code")
		return
	}
	release, err := oplock.Global().Acquire("reboot")
	if err != nil {
		ctrl.auditWrite(c, name, "reboot", "hardware", "blocked: "+err.Error())
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	defer release()

	if err := ctrl.hwSvc.Reboot(0); err != nil {
		ctrl.auditWrite(c, name, "reboot", "hardware", "failed: "+err.Error())
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	ctrl.auditWrite(c, name, "reboot", "hardware", "success")
	c.JSON(http.StatusOK, response.OK(nil))
}

// Shutdown POST /bitmain/v1/ssm/hardware/devices/down
// 高危操作防护（MYS-389）：确认码 + 危险操作互斥锁 + 审计。
func (ctrl *Controller) Shutdown(c *gin.Context) {
	var req CoreOpe
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	name := currentUser(c)
	if !ops.Verify(c, "shutdown", req.ConfirmCode) {
		ctrl.auditWrite(c, name, "shutdown", "hardware", "blocked: missing/invalid confirm code")
		return
	}
	release, err := oplock.Global().Acquire("shutdown")
	if err != nil {
		ctrl.auditWrite(c, name, "shutdown", "hardware", "blocked: "+err.Error())
		c.JSON(http.StatusConflict, response.Fail(err.Error()))
		return
	}
	defer release()

	if err := Shutdown(); err != nil {
		ctrl.auditWrite(c, name, "shutdown", "hardware", "failed: "+err.Error())
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}

	ctrl.auditWrite(c, name, "shutdown", "hardware", "success")
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

// SetBasic POST /bitmain/v1/ssm/software/device/configure/basic
func (ctrl *Controller) SetBasic(c *gin.Context) {
	var req BasicSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	// 降级：不做真 hostname 修改，返回成功 SsmResult
	_ = req
	c.JSON(http.StatusOK, response.OK(nil))
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
// 高危操作防护（MYS-389）：先校验 /ops/confirm 签发的一次性确认码，再记审计；
// 实际刷机持锁（见 pkg/ota handleFlash），入队即确认放行。
func (ctrl *Controller) ExecuteUpgrade(c *gin.Context) {
	var req OtaVersion
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	name := currentUser(c)
	if !ops.Verify(c, "ota_upgrade", req.ConfirmCode) {
		ctrl.auditWrite(c, name, "ota_upgrade", "ota", "blocked: missing/invalid confirm code")
		return
	}

	// Product 为空时用设备实际型号兜底（global.DeviceTypeEx 形如 "SE7 V01"），
	// 否则 productClass 识别不到会返回 "ota: path not implemented"。
	product := req.Product
	if strings.TrimSpace(product) == "" {
		product = global.DeviceTypeEx
	}
	flow := ota.Workflow{
		UserID:     name, // 落库 + 引擎审计（MYS-389）
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
		ctrl.auditWrite(c, name, "ota_upgrade", "ota:"+product+":"+req.FileName, "failed: "+err.Error())
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, name, "ota_upgrade", "ota:"+product+":"+req.FileName, "success")
	c.JSON(http.StatusOK, response.OK("add workflow success"))
}

// Rollback POST /bitmain/v1/ssm/workflow/rollback
// 入队 Type=Rollback 的 workflow，立即返 "add workflow success"。
// 高危操作防护（MYS-389）：确认码 + 审计。
func (ctrl *Controller) Rollback(c *gin.Context) {
	var req OtaVersion
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}

	name := currentUser(c)
	if !ops.Verify(c, "ota_rollback", req.ConfirmCode) {
		ctrl.auditWrite(c, name, "ota_rollback", "ota", "blocked: missing/invalid confirm code")
		return
	}

	product := req.Product
	if strings.TrimSpace(product) == "" {
		product = global.DeviceTypeEx
	}
	flow := ota.Workflow{
		UserID:     name,
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
		ctrl.auditWrite(c, name, "ota_rollback", "ota:"+product+":"+req.FileName, "failed: "+err.Error())
		c.JSON(http.StatusInternalServerError, response.Fail(err.Error()))
		return
	}
	ctrl.auditWrite(c, name, "ota_rollback", "ota:"+product+":"+req.FileName, "success")
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
func (ctrl *Controller) SCP(c *gin.Context) {
	c.JSON(http.StatusOK, response.Fail("scp not supported"))
}

// Exec POST /bitmain/v1/ssm/hardware/devices/exec
// 执行单条 shell 命令（sh -c），返回 stdout/stderr/exitCode。
// 超时默认 30s，上限 300s。高危命令在此不拦截——前端仅用于只读诊断，
// 真正的交互式终端走 /api/v1/hardware/terminal（WebSocket pty）。
// 审计（MYS-389）：exec 属高危命令执行，每次执行记录用户/IP/命令（不记输出）。
func (ctrl *Controller) Exec(c *gin.Context) {
	var req struct {
		Command string `json:"command" binding:"required"`
		Timeout int    `json:"timeout"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, response.Fail("invalid request body"))
		return
	}
	name := currentUser(c)
	ctrl.auditWrite(c, name, "exec", "hardware", "exec: "+req.Command)

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
	c.JSON(http.StatusOK, response.OK(gin.H{
		"stdout":   stdout.String(),
		"stderr":   stderr.String(),
		"exitCode": exitCode,
	}))
}
