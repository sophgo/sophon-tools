package global

import (
	services "sophliteos/mvc/services/version"
	"sophliteos/mvc/types"
	"time"
)

var (
	TimeOut          time.Duration
	OtaTimeOut       time.Duration
	Version          services.BuildInfo
	BlockAllRequests bool
	DeviceType       string
	SSmLists         types.SsmList
	SdkVersion       string
	Resource         types.Resource
	LoginError       int
)
