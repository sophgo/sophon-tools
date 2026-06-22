package system

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"sophliteos/client/ssm"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/i18n"
	services "sophliteos/mvc/services/opt"

	"github.com/gin-gonic/gin"
)

type CoreOperationApi struct{}

func init() {
	i18n.SetString(i18n.Zh, getCode(ssm.Reboot), "重启")
	i18n.SetString(i18n.En, getCode(ssm.Reboot), "Reboot")
	i18n.SetString(i18n.Zh, getCode(ssm.Shutdown), "关机")
	i18n.SetString(i18n.En, getCode(ssm.Shutdown), "Shutdown")
}

func getCode(code int) string {
	return fmt.Sprintf("CoreOperation:%v", code)
}

func (b *CoreOperationApi) GetOperation(c *gin.Context) {
	c.JSON(http.StatusOK, mvc.Ok())
}

func (b *CoreOperationApi) PostOperation(c *gin.Context) {

	ope := ssm.CoreOperation{}
	data, _ := io.ReadAll(c.Request.Body)
	_ = json.Unmarshal(data, &ope)
	result, err := ssm.CoreOperate(ope.Number, ope.Type)
	operation := i18n.GetString(mvc.GetLang(c.Request), getCode(ope.Type))
	mvc.HandleResult(result, err, error2.DeviceOperationErr)
	services.SaveOptLog(c.Request, "核心板操作：%s", operation)
	c.JSON(http.StatusOK, mvc.Success(nil))
}
