package system

import (
	//v1 "sophliteos/api/v1"
	"sophliteos/global"
	"sophliteos/middleware"

	"github.com/gin-gonic/gin"
)

type DownRouter struct{}

func (s *DownRouter) InitDownRouter(Router *gin.RouterGroup) (R gin.IRoutes) {

	router := Router.Group("api/down", middleware.TimeoutMiddleware(global.OtaTimeOut*5))
	/*api := v1.ApiGroupApp.SystemApiGroup.DownApi
	{
		router.GET("log", api.LogDown)
	}*/

	return router
}
