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
	timeout := v.GetString("server.timeout")
	conf.Unlock()

	// 日志处理
	logger.InitLogging(logPath, config.Conf.GetName()+".log", logLevel)

	// 初始化sqlite（保留 OptLog/Alarm 本地记录）
	database.InitDB()

	global.TimeOut, _ = time.ParseDuration("30s")
	global.OtaTimeOut, _ = time.ParseDuration(timeout)
	global.BlockAllRequests = false
	global.Version = services.VersionInit("release_version.txt")

	// ssm SubscribeAlarm 已移除：告警由 ssm /api/v1/* 直接提供，sophliteos 不再订阅。
	logger.Info("InitBase done (ssm proxy mode)")
}
