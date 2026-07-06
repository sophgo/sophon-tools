package compat

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/database"
	"ssm/logger"
	"ssm/mvc/hardware"
	"ssm/mvc/software"
	"ssm/mvc/user"
	"ssm/pkg/auth"
	netpkg "ssm/pkg/network"
	"ssm/pkg/ota"
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
	return NewController(
		DefaultCompatService(),
		hardware.NewDefaultService(),
		software.DefaultService(),
		user.NewService(database.DB()),
		ota.DefaultEngine(),
	)
}

// getSecret 从配置获取 JWT secret。
func getSecret() string {
	conf := &config.Conf
	conf.RLock()
	defer conf.RUnlock()
	secret := conf.GetViper().GetString("server.authSecret")
	if secret == "" {
		secret = "ssm-dev-secret"
	}
	return secret
}

// ---------------------------------------------------------------
// Login
// ---------------------------------------------------------------

// Login POST /bitmain/v1/ssm/login
func (ctrl *Controller) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	user, err := ctrl.userSvc.Login(req.UserName, req.Password)
	if err != nil {
		c.JSON(http.StatusUnauthorized, SsmErr(err.Error()))
		return
	}

	tokenStr, _, err := auth.IssueToken(user.Username, getSecret())
	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr("failed to issue token"))
		return
	}

	c.JSON(http.StatusOK, SsmOK(SystemLoginResponse{
		Token: tokenStr,
		Role:  user.Role,
	}))
}

// ---------------------------------------------------------------
// Device Basic
// ---------------------------------------------------------------

// GetCtrlBasic GET /bitmain/v1/ssm/software/device/basic
func (ctrl *Controller) GetCtrlBasic(c *gin.Context) {
	basic, err := ctrl.svc.BuildCtrlBasic()
	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK(basic))
}

// ---------------------------------------------------------------
// Device Resource
// ---------------------------------------------------------------

// GetCtrlResource GET /bitmain/v1/ssm/software/device/resource/list?all=0
func (ctrl *Controller) GetCtrlResource(c *gin.Context) {
	resources := ctrl.svc.BuildCtrlResource()
	c.JSON(http.StatusOK, SsmOK(resources))
}

// ---------------------------------------------------------------
// IP
// ---------------------------------------------------------------

// GetIP GET /bitmain/v1/ssm/hardware/ip
func (ctrl *Controller) GetIP(c *gin.Context) {
	ipList, err := ctrl.svc.BuildIPList()
	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK(ipList))
}

// SetIP POST /bitmain/v1/ssm/hardware/ip
func (ctrl *Controller) SetIP(c *gin.Context) {
	var req IPSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	var err error
	if req.Policy == "dhcp" {
		err = netpkg.SetDynamicIP(req.Device)
	} else {
		err = netpkg.SetStaticIP(req.Device, req.IP, req.Mask, req.Gateway, req.DNS)
	}

	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(nil))
}

// ---------------------------------------------------------------
// NAT
// ---------------------------------------------------------------

// GetNAT GET /bitmain/v1/ssm/hardware/nat
func (ctrl *Controller) GetNAT(c *gin.Context) {
	rules, err := netpkg.GetNATRules()
	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK(rules))
}

// AddNAT POST /bitmain/v1/ssm/hardware/nat
func (ctrl *Controller) AddNAT(c *gin.Context) {
	var req AddTable
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
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
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(nil))
}

// numRe 限定 nat 规则编号为数字（防注入）。
var numRe = regexp.MustCompile(`^[1-9][0-9]*$`)

// DeleteNAT DELETE /bitmain/v1/ssm/hardware/nat/PREROUTING-:num
func (ctrl *Controller) DeleteNAT(c *gin.Context) {
	num := c.Param("num")
	if !numRe.MatchString(num) {
		c.JSON(http.StatusBadRequest, SsmErr("invalid rule number"))
		return
	}

	if err := DeleteNATRule(num); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(nil))
}

// ---------------------------------------------------------------
// 重启 / 关机
// ---------------------------------------------------------------

// Reboot POST /bitmain/v1/ssm/hardware/devices/reset
// 复用 hardware.HardwareService 的 Rebooter（生产用 osRebooter）。
func (ctrl *Controller) Reboot(c *gin.Context) {
	var req CoreOpe
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	if err := ctrl.hwSvc.Reboot(0); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(nil))
}

// Shutdown POST /bitmain/v1/ssm/hardware/devices/down
func (ctrl *Controller) Shutdown(c *gin.Context) {
	var req CoreOpe
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	if err := Shutdown(); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(nil))
}

// ---------------------------------------------------------------
// 告警订阅
// ---------------------------------------------------------------

// SubscribeAlarm POST /bitmain/v1/ssm/software/notify/subscribe
func (ctrl *Controller) SubscribeAlarm(c *gin.Context) {
	var req SubscribeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	ctrl.svc.Subscribe(req)
	c.JSON(http.StatusOK, SsmOK(nil))
}

// UnsubscribeAlarm POST /bitmain/v1/ssm/software/notify/unsubscribe
func (ctrl *Controller) UnsubscribeAlarm(c *gin.Context) {
	var req SubscribeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	ctrl.svc.Unsubscribe(req.Platform)
	c.JSON(http.StatusOK, SsmOK(nil))
}

// GetSubscription GET /bitmain/v1/ssm/software/notify/subscribe/:name
func (ctrl *Controller) GetSubscription(c *gin.Context) {
	name := c.Param("name")
	if name == "" {
		c.JSON(http.StatusBadRequest, SsmErr("missing name"))
		return
	}

	sub, ok := ctrl.svc.GetSubscription(name)
	if !ok {
		c.JSON(http.StatusOK, SsmOK(nil))
		return
	}

	c.JSON(http.StatusOK, SsmOK(sub))
}

// ---------------------------------------------------------------
// 设备配置
// ---------------------------------------------------------------

// SetBasic POST /bitmain/v1/ssm/software/device/configure/basic
func (ctrl *Controller) SetBasic(c *gin.Context) {
	var req BasicSettings
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	// 降级：不做真 hostname 修改，返回成功 SsmResult
	_ = req
	c.JSON(http.StatusOK, SsmOK(nil))
}

// SetAlarm POST /bitmain/v1/ssm/software/device/configure/alarm
// 持久化告警阈值到配置文件，对齐 bmssm WriteAlarmConfig 行为。
func (ctrl *Controller) SetAlarm(c *gin.Context) {
	var req AlarmThreshold
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}

	config.Conf.Lock()
	v := config.Conf.GetViper()
	v.Set("alarmThreshold.boardTemperature", req.BoardTemperature)
	v.Set("alarmThreshold.coreTemperature", req.CoreTemperature)
	v.Set("alarmThreshold.cpuRate", req.CpuRate)
	v.Set("alarmThreshold.diskRate", req.DiskRate)
	v.Set("alarmThreshold.externalHardDiskRate", req.ExternalHardDiskRate)
	v.Set("alarmThreshold.fanSpeed", req.FanSpeed)
	v.Set("alarmThreshold.systemScale", req.SystemScale)
	v.Set("alarmThreshold.totalMemoryScale", req.TotalMemoryScale)
	v.Set("alarmThreshold.tpuRate", req.TpuRate)
	v.Set("alarmThreshold.tpuScale", req.TpuScale)
	v.Set("alarmThreshold.videoScale", req.VideoScale)

	if err := v.WriteConfig(); err != nil {
		// WriteConfig 失败时降级为仅内存更新（例如无配置文件路径）
		config.Conf.Unlock()
		logger.Warn("SetAlarm WriteConfig failed (in-memory only): %v", err)
		c.JSON(http.StatusOK, SsmOK(nil))
		return
	}
	config.Conf.Unlock()

	c.JSON(http.StatusOK, SsmOK(nil))
}

// ---------------------------------------------------------------
// OTA 固件上传
// ---------------------------------------------------------------

// UploadFirmware POST /bitmain/v1/ssm/file/ota
// 接收 multipart .tgz 刷机包，按 module（form 字段，默认 soc）保存到对应目录。
func (ctrl *Controller) UploadFirmware(c *gin.Context) {
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("missing file field"))
		return
	}
	defer file.Close()

	origName := header.Filename
	// 大小限制
	if ctrl.swSvc.GetMaxSize() > 0 && header.Size > ctrl.swSvc.GetMaxSize() {
		c.JSON(http.StatusBadRequest, SsmErr(fmt.Sprintf("file too large: %d bytes (max %d)", header.Size, ctrl.swSvc.GetMaxSize())))
		return
	}

	module := strings.TrimSpace(c.DefaultPostForm("module", "soc"))
	if module == "" {
		module = "soc"
	}

	// 落盘到 OTA 临时路径（复用 SoftwareService 的 otaDir 作暂存）
	savePath := filepath.Join(ctrl.swSvc.GetOTADir(), "tmp_"+filepath.Base(origName))
	if err := c.SaveUploadedFile(header, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr("save file failed"))
		return
	}
	savedPath, err := ctrl.otaEngine.OTAUpload(module, origName, savePath, header.Size)
	_ = os.Remove(savePath) // 清理临时文件
	if err != nil {
		c.JSON(http.StatusBadRequest, SsmErr(err.Error()))
		return
	}

	c.JSON(http.StatusOK, SsmOK(map[string]interface{}{
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
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}
	flow := ota.Workflow{
		Product:    req.Product,
		ModuleName: req.ModuleName,
		FileName:   req.FileName,
		CmdFlag:    req.CmdFlag,
		Version:    req.Version,
		Name:       req.Name,
		Type:       ota.TypeUpgrade,
		FlashData:  req.FlashData,
	}
	if err := ctrl.otaEngine.EnqueueFlow(&flow); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK("add workflow success"))
}

// Rollback POST /bitmain/v1/ssm/workflow/rollback
// 入队 Type=Rollback 的 workflow，立即返 "add workflow success"。
func (ctrl *Controller) Rollback(c *gin.Context) {
	var req OtaVersion
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, SsmErr("invalid request body"))
		return
	}
	flow := ota.Workflow{
		Product:    req.Product,
		ModuleName: req.ModuleName,
		FileName:   req.FileName,
		CmdFlag:    req.CmdFlag,
		Version:    req.Version,
		Name:       req.Name,
		Type:       ota.TypeRollback,
		FlashData:  req.FlashData,
	}
	if err := ctrl.otaEngine.EnqueueFlow(&flow); err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK("add workflow success"))
}

// ListWorkflows GET /bitmain/v1/ssm/workflow/upgrade
// 列出全部 workflow 状态（SsmResult.result=flows）。
func (ctrl *Controller) ListWorkflows(c *gin.Context) {
	flows, err := ctrl.otaEngine.QueryAll()
	if err != nil {
		c.JSON(http.StatusInternalServerError, SsmErr(err.Error()))
		return
	}
	c.JSON(http.StatusOK, SsmOK(flows))
}

// GetWorkflow GET /bitmain/v1/ssm/workflow/upgrade/:id
// 查询单个 workflow 状态。
func (ctrl *Controller) GetWorkflow(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		c.JSON(http.StatusBadRequest, SsmErr("missing workflow id"))
		return
	}
	flow, err := ctrl.otaEngine.Query(id)
	if err != nil {
		c.JSON(http.StatusOK, SsmErr("workflow not found"))
		return
	}
	c.JSON(http.StatusOK, SsmOK(flow))
}

// ---------------------------------------------------------------
// 降级路由（不支持的操作）
// ---------------------------------------------------------------

// SCP POST /bitmain/v1/ssm/hardware/devices/scp
func (ctrl *Controller) SCP(c *gin.Context) {
	c.JSON(http.StatusOK, SsmErr("scp not supported"))
}

// Exec POST /bitmain/v1/ssm/hardware/devices/exec
func (ctrl *Controller) Exec(c *gin.Context) {
	c.JSON(http.StatusOK, SsmErr("exec not supported"))
}
