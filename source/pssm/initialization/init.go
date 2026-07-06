// Package initialization 串联启动流程：配置→日志→设备信息→DB。
package initialization

import (
	"time"

	"ssm/config"
	"ssm/database"
	"ssm/global"
	"ssm/logger"
	mwuser "ssm/mvc/user"
	"ssm/pkg/alarm"
	"ssm/pkg/device"
	"ssm/pkg/ota"
)

// InitBase 启动阶段基础初始化。
func InitBase() {
	config.LoadConfig()

	conf := &config.Conf
	conf.RLock()
	logLevel := conf.GetViper().GetString("log.level")
	logPath := conf.GetViper().GetString("log.path")
	dbPath := conf.GetViper().GetString("db.path")
	authSecret := conf.GetViper().GetString("server.authSecret")
	conf.RUnlock()

	logger.InitLogging(logPath, "ssm.log", logLevel)
	logger.Info("ssm starting, version=%s", global.Version.String())

	if authSecret == "" || authSecret == "ssm-dev-secret" {
		logger.Warn("using default JWT secret, set server.authSecret in production")
	}

	global.Started = time.Now()

	device.GetDeviceInfo()
	global.DeviceType = device.DeviceType
	global.DeviceRole = device.DeviceRole
	global.DeviceTypeEx = device.DeviceTypeEx
	global.DeviceSnEx = device.DeviceSnEx
	global.ChipSn = device.ChipSn
	global.ModuleType = device.ModuleType
	logger.Info("device: type=%s role=%s typeEx=%s sn=%s",
		global.DeviceType, global.DeviceRole, global.DeviceTypeEx, global.DeviceSnEx)

	// DB：失败不阻断启动（无业务依赖时仍可运行）
	if db, err := database.InitDB(dbPath); err == nil {
		if err := database.Migrate(db); err != nil {
			logger.Warn("migrate failed: %v", err)
		}
		// 若 user 表为空，创建默认 admin 用户
		createDefaultAdmin(conf)
		// 启动 OTA workflow 引擎（RegisterModel 由 pkg/ota init() 注册）
		ota.Init()
	} else {
		logger.Warn("db init failed (non-fatal): %v", err)
	}

	// 告警监控引擎：设备信息已就绪即可启动，不依赖 DB（仅 POST 到 compat 订阅 callback）。
	// 每 30s 采集 pkg/metrics 指标→比对 alarmThreshold→超限/恢复 POST AlarmRec。
	alarm.Init()
}

// createDefaultAdmin 在 user 表为空时插入默认 admin 用户。
// 密码以明文传入 CreateUser（由其内部 bcrypt 哈希），避免双重哈希。
func createDefaultAdmin(conf *config.Config) {
	db := database.DB()
	if db == nil {
		return
	}

	conf.RLock()
	password := conf.GetViper().GetString("server.defaultPassword")
	conf.RUnlock()
	if password == "" {
		password = "admin"
	}

	svc := mwuser.NewService(db)

	count, err := svc.CountUsers()
	if err != nil {
		logger.Warn("check user table: %v", err)
		return
	}
	if count > 0 {
		return
	}

	// 明文密码传入；CreateUser 内部负责 bcrypt 哈希
	if err := svc.CreateUser("admin", password, "superuser"); err != nil {
		logger.Error("create default admin: %v", err)
		return
	}
	logger.Info("default admin user created")
}
