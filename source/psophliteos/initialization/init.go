package initialization

import (
	"sophliteos/client/ssm"
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

	// 初始化sqlite
	database.InitDB()

	global.TimeOut, _ = time.ParseDuration("30s")
	global.OtaTimeOut, _ = time.ParseDuration(timeout)
	global.BlockAllRequests = false
	global.Version = services.VersionInit("release_version.txt")

	_, err := ssm.SubscribeAlarm()
	if err != nil {
		logger.Error("SubscribeAlarm error %v", err)
	} else {
		logger.Info("SubscribeAlarm Ok")
	}
}
