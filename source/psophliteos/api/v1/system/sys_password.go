package system

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"

	"sophliteos/database"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/types"

	"github.com/gin-gonic/gin"
)

type PasswordApi struct{}

func (b *PasswordApi) PasswordMod(c *gin.Context) {
	req := types.PasswordModify{}
	body, _ := io.ReadAll(c.Request.Body)
	_ = json.Unmarshal(body, &req)

	err := mvc.Valid(c.Request, req)
	if err != nil {
		errStr := fmt.Sprintf("%v", err)
		logger.Error("error: %s", errStr)
		c.JSON(http.StatusUnprocessableEntity, mvc.FailWithMsg(1, errStr))
		return
	}

	user := mvc.GetUser(mvc.Token(c.Request))
	if user.Password == req.Password {
		user.Password = req.NewPassword
		database.SaveUser(user)
		c.JSON(http.StatusOK, mvc.Ok())
		return
	} else {
		logger.Error("旧密码错误")
		c.JSON(http.StatusOK, mvc.Fail(error2.PwdNotEqErr, "旧密码错误"))
		return
	}

}

func md5Value(str string) string {
	h := md5.New()
	h.Write([]byte(str))
	return hex.EncodeToString(h.Sum(nil))
}

// 长度8-16位，大小写字母，数字，特征字符至少3种
func check(pwd string) error2.Code {
	if len(pwd) < 8 {
		return error2.PwdValidErr
	}
	if len(pwd) > 16 {
		return error2.PwdValidErr
	}
	var level = 0
	patternList := []string{`[0-9]+`, `[a-z]+`, `[A-Z]+`, `[~!@#$%^&*?_-]+`}
	for _, pattern := range patternList {
		match, _ := regexp.MatchString(pattern, pwd)
		if match {
			level++
		}
	}
	if level < 3 {
		return error2.PwdValidErr
	}
	return error2.Ok
}
