package system

import (
	"net/http"

	"sophliteos/global"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

type VersionApi struct{}

func (b *VersionApi) Version(c *gin.Context) {
	c.JSON(http.StatusOK, mvc.Success(global.Version))
}
