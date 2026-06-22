package system

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"sophliteos/client/ssm"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	services "sophliteos/mvc/services/opt"

	"github.com/gin-gonic/gin"
)

type information struct {
	Model string `json:"model"`
}

type BasicApi struct{}

func (b *BasicApi) BasicMod(c *gin.Context) {
	req := ssm.BasicSettings{}
	body, _ := io.ReadAll(c.Request.Body)
	json.Unmarshal(body, &req)

	if req.Type == "" {
		req.Type = GetSysDeviceType()
	}

	err := mvc.Valid(c.Request, req)
	if err != nil {
		logger.Error("error: %v", err)
		errStr := fmt.Sprintf("%v", err)
		c.JSON(http.StatusUnprocessableEntity, mvc.FailWithMsg(1, errStr))
		return
	}
	result, err := ssm.SetBasic(req)
	mvc.HandleError(err, error2.SetDeviceInfoErr)
	services.SaveOptLog(c.Request, "基础信息设置")
	c.JSON(http.StatusOK, mvc.Success(mvc.Handle(result, error2.SetDeviceInfoErr)))
}

func GetSysDeviceType() string {
	data, err := os.ReadFile("/sys/bus/i2c/devices/1-0017/information")
	if err != nil {
		logger.Error("读取文件错误:%v", err)
		return ""
	}

	// 解析JSON数据
	var info information
	if err := json.Unmarshal(data, &info); err != nil {
		logger.Error("解析JSON错误:", err)
		return ""
	}

	if strings.Contains(info.Model, "SE5") {
		return "SE5"
	} else if strings.Contains(info.Model, "SE6") {
		return "SE6"
	} else if strings.Contains(info.Model, "BM1684X EVB") {
		return "SE7"
	}
	return ""
}
