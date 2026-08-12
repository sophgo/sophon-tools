package initialization

import (
	"io/fs"
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/fstest"

	"sophliteos/config"
)

// 验证内嵌前端（go:embed dist）经 Routers 的 NoRoute + http.FileServer 正确对外服务，
// 覆盖入口页、config、favicon 与静态子路径，并确认非 GET 未被兜底误放行。
func testEmbeddedFS(t *testing.T) fs.FS {
	t.Helper()
	return fstest.MapFS{
		"index.html":     {Data: []byte("<!doctype html><html>sophliteos</html>")},
		"_app.config.js": {Data: []byte("window.__APP_CONFIG__={}")},
		"favicon.ico":    {Data: []byte("favicon")},
		"assets/app.js":  {Data: []byte("console.log(1)")},
		"resource/a.txt": {Data: []byte("resource")},
	}
}

func TestRoutersServesEmbeddedFrontend(t *testing.T) {
	// 生产路径为 main → InitBase() → config.LoadConfig() 后再 Routers();
	// 测试先 LoadConfig 拿到有效 viper（读不到配置文件时优雅降级为空配置）。
	config.LoadConfig()
	router := Routers(testEmbeddedFS(t))

	cases := []struct {
		name   string
		method string
		path   string
		want   int
	}{
		{"/ index", "GET", "/", http.StatusOK},
		{"/assets", "GET", "/assets/app.js", http.StatusOK},
		{"/resource", "GET", "/resource/a.txt", http.StatusOK},
		{"/config", "GET", "/_app.config.js", http.StatusOK},
		{"/favicon", "GET", "/favicon.ico", http.StatusOK},
		{"/unknown 404", "GET", "/no/such/file.js", http.StatusNotFound},
		{"/POST not static", "POST", "/", http.StatusNotFound},
	}

	for _, tc := range cases {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(tc.method, tc.path, nil)
		router.ServeHTTP(w, req)
		if w.Code != tc.want {
			t.Errorf("%s: status = %d, want %d (body=%q)", tc.name, w.Code, tc.want, w.Body.String())
		}
	}
}

func TestEmbeddedFrontendContent(t *testing.T) {
	config.LoadConfig()
	router := Routers(testEmbeddedFS(t))

	for _, p := range []string{"/", "/assets/app.js", "/resource/a.txt"} {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, p, nil)
		router.ServeHTTP(w, req)
		if w.Code != http.StatusOK || w.Body.Len() == 0 {
			t.Errorf("%s: status=%d body=%q", p, w.Code, w.Body.String())
		}
	}
}
