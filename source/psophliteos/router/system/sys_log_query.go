package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type LogRouter struct{}

func (s *LogRouter) InitLogRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	logRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.LogApi
	{
		logRouter.GET("alarmRecord/list", api.AlarmLogQuery)
		logRouter.GET("operRecord/list", api.OptLogQuery)
	}

	return logRouter
}
