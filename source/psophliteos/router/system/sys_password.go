package system

import (
	v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type PasswordRouter struct{}

func (s *PasswordRouter) InitPasswordRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	passwordRouter := Router.Group("api/device", middleware.TimeoutMiddleware(global.TimeOut))
	api := v1.ApiGroupApp.SystemApiGroup.PasswordApi
	{
		passwordRouter.POST("password", api.PasswordMod)
	}

	return passwordRouter
}
