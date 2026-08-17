package initialization

import (
	"sophliteos/config"
	"sophliteos/database"
	"sophliteos/global"
	"sophliteos/logger"
	services "sophliteos/mvc/services/version"
	"time"
)

func InitBase() {
	// 加载配置
	config.LoadConfig()

	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	logLevel := v.GetString("log.level")
	logPath := v.GetString("log.path")
	readTimeout := v.GetString("server.read-timeout")
	readHeaderTimeout := v.GetString("server.read-header-timeout")
	// ota-timeout 优先；旧配置键 server.timeout 自动兼容（存量部署保留 12m 语义）
	otaTimeout := v.GetString("server.ota-timeout")
	if otaTimeout == "" {
		otaTimeout = v.GetString("server.timeout")
	}
	conf.Unlock()

	// 日志处理
	logger.InitLogging(logPath, config.Conf.GetName()+".log", logLevel)

	// 初始化sqlite（保留 OptLog/Alarm 本地记录）
	database.InitDB()

	// 常规与 OTA/升级超时分离（MYS-382）：常规 30s（可配置），
	// OTA/升级 12m（大分片上传/固件升级需更长窗口）；请求头 10s 防慢连接攻击。
	global.TimeOut = parseDurationOr(readTimeout, "30s")
	global.OtaTimeOut = parseDurationOr(otaTimeout, "12m")
	global.ReadHeaderTimeOut = parseDurationOr(readHeaderTimeout, "10s")
	global.BlockAllRequests = false
	global.Version = services.VersionInit("release_version.txt")

	// ssm SubscribeAlarm 已移除：告警由 ssm /api/v1/* 直接提供，sophliteos 不再订阅。
	logger.Info("InitBase done (ssm proxy mode), timeouts: read=%s header=%s ota=%s ctx=%s",
		global.TimeOut, global.ReadHeaderTimeOut, global.OtaTimeOut, global.TimeOut)
}

// parseDurationOr 解析时长配置；非法值回退默认并告警，避免超时配置被意外置零（0=不限时）。
func parseDurationOr(v, def string) time.Duration {
	raw := v
	if raw == "" {
		raw = def
	}
	d, err := time.ParseDuration(raw)
	if err != nil {
		logger.Error("invalid duration %q, fallback to %s: %v", v, def, err)
		d, _ = time.ParseDuration(def)
	}
	return d
}
