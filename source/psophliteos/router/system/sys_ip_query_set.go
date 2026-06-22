package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type IpQueryRouter struct{}

func (s *IpQueryRouter) InitIpRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	ipQueryRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut*3))
	api := v1.ApiGroupApp.SystemApiGroup.IpApi
	{
		ipQueryRouter.GET("ip", api.IpQuery)
		ipQueryRouter.POST("ip", api.IpSet)
		ipQueryRouter.GET("iptable/get", api.GetTables)
		ipQueryRouter.POST("iptable/add", api.AddTables)
		ipQueryRouter.POST("iptable/delete", api.DeleteTables)
	}

	return ipQueryRouter
}
