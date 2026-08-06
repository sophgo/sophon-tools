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

// clientIP 从 RemoteAddr 提取客户端 IP（忽略端口）。空值/非法时返回空串，避免 panic。
// RemoteAddr 形如 "192.168.1.1:8080" 或 "[::1]:8080"。
func clientIP(remoteAddr string) string {
	if remoteAddr == "" {
		return ""
	}
	// 优先找最后一个 ":"（IPv6 带括号时端口分隔符也是最后一个冒号）
	if idx := strings.LastIndex(remoteAddr, ":"); idx > 0 {
		host := remoteAddr[:idx]
		// 去掉 IPv6 括号
		host = strings.TrimPrefix(host, "[")
		host = strings.TrimSuffix(host, "]")
		return host
	}
	return remoteAddr
}

func SaveOptLog(request *http.Request, operationType string, parameters ...interface{}) {
	operationContent := i18n.GetString(mvc.GetLang(request), operationType)
	if parameters != nil && len(parameters) > 0 {
		operationContent = fmt.Sprintf(operationContent, parameters...)
	}

	ip := clientIP(request.RemoteAddr)
	user := mvc.GetUser(mvc.Token(request))
	if operationContent == "登录" {
		database.SaveOptLog(database.OptLog{
			UserName:         "admin",
			CreatedTime:      time.Now(),
			OperationType:    strings.Split(request.RequestURI, "?")[0],
			OperationContent: operationContent,
			OperationIP:      ip,
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
		OperationIP:      ip,
		OperationFunc:    operationContent,
	})
}
