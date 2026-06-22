package services

import (
	"fmt"
	"net/http"
	"sophliteos/database"
	mvc "sophliteos/mvc/core"
	"sophliteos/mvc/i18n"
	"strings"
	"time"
)

func SaveOptLog(request *http.Request, operationType string, parameters ...interface{}) {
	operationContent := i18n.GetString(mvc.GetLang(request), operationType)
	if parameters != nil && len(parameters) > 0 {
		operationContent = fmt.Sprintf(operationContent, parameters...)
	}

	user := mvc.GetUser(mvc.Token(request))
	if operationContent == "登录" {
		database.SaveOptLog(database.OptLog{
			UserName:         "admin",
			CreatedTime:      time.Now(),
			OperationType:    strings.Split(request.RequestURI, "?")[0],
			OperationContent: operationContent,
			OperationIP:      request.RemoteAddr[0:strings.LastIndex(request.RemoteAddr, ":")],
			OperationFunc:    operationContent,
		})
		return
	}

	if user == nil {
		return
	}
	database.SaveOptLog(database.OptLog{
		UserName:         user.UserName,
		CreatedTime:      time.Now(),
		OperationType:    strings.Split(request.RequestURI, "?")[0],
		OperationContent: operationContent,
		OperationIP:      request.RemoteAddr[0:strings.LastIndex(request.RemoteAddr, ":")],
		OperationFunc:    operationContent,
	})
}
