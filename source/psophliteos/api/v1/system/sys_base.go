package system

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"sophliteos/config"
	"sophliteos/database"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	services "sophliteos/mvc/services/opt"

	"sophliteos/mvc/types"

	"github.com/google/uuid"

	"github.com/gin-gonic/gin"
)

type BaseApi struct{}

// Login
func (b *BaseApi) Login(c *gin.Context) {
	req := types.LoginRequest{}
	body, _ := io.ReadAll(c.Request.Body)
	json.Unmarshal(body, &req)

	userName := req.UserName
	password := req.Password

	now := time.Now()
	user, _ := database.QueryUserWithName(userName)
	var token string
	if user == nil {
		c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "用户名不存在"))
		return
	}

	if global.LoginError >= 3 {
		if now.After(user.LockedTime) {
			global.LoginError = 0
		} else {
			c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "用户锁定,请稍后再试"))
			return
		}
	}

	if user.Password != password {
		global.LoginError += 1

		if global.LoginError >= 3 {
			user.LockedTime = now.Add(time.Minute * 1)
			database.UpdateUser(user)
			c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "多次密码错误,请稍后再试"))
		} else {
			c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "密码错误"))
		}

		return
	} else {
		global.LoginError = 0
	}

	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	dfPass := v.GetString("server.admin-password")
	conf.Unlock()

	changPass := 0
	if password == dfPass {
		changPass = 1
	}

	if now.After(user.ExpireTime) {
		token = strings.ReplaceAll(uuid.New().String(), "-", "")
		user.Token = token
		user.LoginTime = now
		user.ExpireTime = now.Add(time.Hour * 2)
		database.UpdateUser(user)
	} else {
		token = user.Token
	}

	mvc.SetUser(token, user)

	services.SaveOptLog(c.Request, "登录")

	c.JSON(http.StatusOK, mvc.Success(types.LoginResponse{
		Token:     token,
		ChangPass: changPass,
	}))
}

func (b *BaseApi) Logout(c *gin.Context) {
	req := types.LogoutRequest{}
	body, _ := io.ReadAll(c.Request.Body)
	json.Unmarshal(body, &req)

	if req.Token != "" {
		user, err := database.QueryUserWithToken(req.Token)
		if err == nil && user != nil {
			user.Token = ""
			user.ExpireTime = time.Now()
			database.UpdateUser(user)
			services.SaveOptLog(c.Request, "注销登录")
			mvc.RemoveUser(req.Token)
			c.JSON(http.StatusOK, mvc.Success(nil))

		} else {
			c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "Invalid Token"))
			return
		}
	} else {
		c.JSON(http.StatusOK, mvc.Fail(error2.InvalidUsernameOrPassword, "Invalid Token"))
	}
}

func (b *BaseApi) AlarmListen(c *gin.Context) {
	var alarmRec database.AlarmRec
	data, _ := io.ReadAll(c.Request.Body)
	_ = json.Unmarshal(data, &alarmRec)

	/*if alarmRec.DiskName == "/dev/mmcblk0p4" || alarmRec.DiskName == "/dev/mmcblk0p2" || alarmRec.DiskName == "/dev/mmcblk0p5" {
		c.JSON(http.StatusOK, mvc.Ok())
		return
	}*/

	logger.Debug("recive alarm:%s", string(data))

	if global.DeviceType == "" {
		GetArmResource(c)
	}

	var alarm database.Alarm
	switch global.DeviceType {
	case "SE5", "SE7", "SE9":
		alarm = database.Alarm{
			DeviceSn:      global.Resource.DeviceSn,
			DeviceIp:      "",
			CreatedAt:     time.Now(),
			ComponentType: getType(alarmRec.Code),
			Code:          alarmRec.Code,
			Msg:           alarmRec.Msg,
		}
		alarm.CoreUnitBoardSn = global.Resource.DeviceSn

	default:
		alarm = database.Alarm{
			DeviceSn:      alarmRec.DeviceSn,
			DeviceIp:      "",
			CreatedAt:     time.Now(),
			ComponentType: getType(alarmRec.Code),
			Code:          alarmRec.Code,
			Msg:           alarmRec.Msg,
		}

		alarm.CoreUnitBoardSn = alarmRec.BoardSn
		if alarm.CoreUnitBoardSn == "" {
			alarm.CoreUnitBoardSn = alarmRec.DeviceSn
		}
	}
	if alarm.ComponentType == "disk" && alarmRec.Code < 0 {
		alarm.Msg = "磁盘" + alarmRec.DiskName + ":  " + alarmRec.Msg
	}

	err := database.SaveAlarm(alarm)
	mvc.HandleError(err)
	c.JSON(http.StatusOK, mvc.Ok())
}

func getType(code int) string {
	if code < 0 {
		code = -code
	}
	code = code / 1000
	var res string

	switch code {
	case 101:
		res = "cpu"
	case 102:
		res = "memory"
	case 103:
		res = "disk"
	case 104:
		res = "netCard"
	case 201:
		res = "board"
	case 202:
		res = "chip"
	default:
		res = ""
	}
	return res
}
