package global

import (
	services "sophliteos/mvc/services/version"
	"sophliteos/mvc/types"
	"time"
)

var (
	TimeOut           time.Duration // 常规 HTTP 读/写超时 + 常规路由 ctx 超时（server.read-timeout）
	OtaTimeOut        time.Duration // OTA/升级长超时（server.ota-timeout，兼容旧 server.timeout）
	ReadHeaderTimeOut time.Duration // 请求头读取超时（server.read-header-timeout）
	Version           services.BuildInfo
	BlockAllRequests  bool
	DeviceType        string
	SSmLists          types.SsmList
	SdkVersion        string
	Resource          types.Resource
	LoginError        int
)
