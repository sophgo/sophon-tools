package system

import (
	"io"
	"net/http"
	"strings"

	"sophliteos/client/ssm"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	services "sophliteos/mvc/services/opt"

	"github.com/gin-gonic/gin"
)

type AlarmApi struct{}

func (b *AlarmApi) AlarmQuery(c *gin.Context) {
	ctrl, _, err := ssm.GetCtrlBasic()
	mvc.HandleError(err)
	c.JSON(http.StatusOK, mvc.Success(ctrl.Configure.AlarmThreshold))
}

func (b *AlarmApi) AlarmSet(c *gin.Context) {

	data, _ := io.ReadAll(c.Request.Body)

	var err error
	if strings.Contains(global.DeviceType, "SE5") || strings.Contains(global.DeviceType, "SE7") || strings.Contains(global.DeviceType, "SE9") {
		_, err = ssm.SetAlarmSe5(data)
	} else {
		_, err = ssm.SetAlarm(data)
	}
	if err != nil {
		logger.Error("设置告警失败：%v", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "设置告警失败"))
		return
	}

	ssmResult, err := ssm.SubscribeAlarm()
	if err != nil {
		logger.Error("设置告警失败：%v", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "设置告警失败"))
		return
	}
	services.SaveOptLog(c.Request, "设置告警")
	c.JSON(http.StatusOK, mvc.Handle(ssmResult, error2.SetAlarmErr))
}
