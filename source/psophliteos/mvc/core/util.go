package mvc

import (
	"net/http"
	"sophliteos/mvc/i18n"
	"strings"
)

func IsMultiPartRequest(request *http.Request) bool {
	return strings.Contains(request.Header.Get(contentType), multipart)
}

func GetLang(request *http.Request) string {
	var lang = request.Header.Get(acceptLanguage)
	if len(lang) > 0 {
		return lang
	}
	return i18n.Zh
}
