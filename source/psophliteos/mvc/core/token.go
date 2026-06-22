package mvc

import (
	"net/http"
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

func Token(request *http.Request) string {
	return request.Header.Get(authorization)
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
