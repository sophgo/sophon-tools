package mvc

import (
	"net/http"
	"strings"
	"time"

	"sophliteos/database"

	"github.com/patrickmn/go-cache"
)

const (
	acceptLanguage = "Accept-Language"
	authorization  = "Authorization"
	contentType    = "Content-Type"
	multipart      = "multipart/form-data"
	Pattern        = "2006-01-02 15:04:05"
)

var tokenCache *cache.Cache

func init() {
	tokenCache = cache.New(2*time.Hour, 5*time.Minute)
}

// Token 从 Authorization 头提取归一化后的裸 token：
// 剥离 "Bearer " 前缀并去空白。前端 defHttp 以 `Bearer <jwt>` 发送，
// 而 tokenCache 与会话按裸 jwt 存储/比对；旧实现直接返回完整头部，
// 导致 Token→QueryUserWithToken 永远失配、操作审计静默失效（MYS-382）。
func Token(request *http.Request) string {
	header := request.Header.Get(authorization)
	trimmed := strings.TrimSpace(header)
	if i := strings.Index(trimmed, " "); i > 0 {
		// 仅剥离标准的 "Bearer " 前缀；其他非法形式原样返回（查不到即不归因）。
		if strings.EqualFold(trimmed[:i], "Bearer") {
			trimmed = strings.TrimSpace(trimmed[i:])
		}
	}
	return trimmed
}

func GetUser(token string) *database.User {
	user, found := tokenCache.Get(token)
	if found {
		return user.(*database.User)
	} else {
		user, _ := database.QueryUserWithToken(token)
		return user
	}
}

func SetUser(token string, user *database.User) {
	tokenCache.Set(token, user, 2*time.Hour)
}

func RemoveUser(token string) {
	tokenCache.Delete(token)
}
