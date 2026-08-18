package services

import (
	"fmt"
	"net/http"
	"sophliteos/database"
	"sophliteos/middleware"
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

// userNameFor 解析请求的操作人。
//
// 本地无 user 表（鉴权由 bmssm 反代完成，User.Token 从不写入），
// database.QueryUserWithToken 对任何在线请求都查不到记录；若直接依赖 DB，
// 操作日志会全部静默丢弃。因此优先取 SSO 活跃会话（登录成功时前端在
// /api/sso/register 注册的 (username, token)），DB 仅作 legacy 记录兜底
// （MYS-382）。两者都解析不到（无会话/未知 token）返回空串，不落审计。
func userNameFor(request *http.Request) string {
	token := mvc.Token(request)
	if name, ok := middleware.SSOUserByToken(token); ok {
		return name
	}
	if user := mvc.GetUser(token); user != nil {
		return user.UserName
	}
	return ""
}

func SaveOptLog(request *http.Request, operationType string, parameters ...interface{}) {
	operationContent := i18n.GetString(mvc.GetLang(request), operationType)
	if parameters != nil && len(parameters) > 0 {
		operationContent = fmt.Sprintf(operationContent, parameters...)
	}

	ip := clientIP(request.RemoteAddr)
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

	userName := userNameFor(request)
	if userName == "" {
		return
	}
	database.SaveOptLog(database.OptLog{
		UserName:         userName,
		CreatedTime:      time.Now(),
		OperationType:    strings.Split(request.RequestURI, "?")[0],
		OperationContent: operationContent,
		OperationIP:      ip,
		OperationFunc:    operationContent,
	})
}
