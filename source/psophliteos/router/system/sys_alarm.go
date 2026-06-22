package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type AlarmRouter struct{}

func (s *AlarmRouter) InitAlarmRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	alarmRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.AlarmApi
	{
		alarmRouter.GET("configure/alarm", api.AlarmQuery)
		alarmRouter.POST("configure/alarm", api.AlarmSet)

	}

	return alarmRouter
}
