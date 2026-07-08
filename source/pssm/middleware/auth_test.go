package middleware

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"

	"ssm/config"
	"ssm/pkg/auth"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestAuthNoTokenReturns401(t *testing.T) {
	ensureConfig(t)

	r := gin.New()
	r.Use(Auth())
	r.GET("/api/v1/user", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestAuthInvalidTokenReturns401(t *testing.T) {
	ensureConfig(t)

	r := gin.New()
	r.Use(Auth())
	r.GET("/api/v1/user", func(c *gin.Context) { c.Status(http.StatusOK) })

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	req.Header.Set("Authorization", "Bearer garbage-token")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestAuthValidTokenSetsUser(t *testing.T) {
	ensureConfig(t)

	secret := config.Conf.GetViper().GetString("server.authSecret")

	r := gin.New()
	r.Use(Auth())
	r.GET("/api/v1/user", func(c *gin.Context) {
		user, _ := c.Get("user")
		c.JSON(http.StatusOK, gin.H{"user": user})
	})

	tokenStr, _, err := auth.IssueToken("testuser", secret, false)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestAuthWrongSecretTokenReturns401(t *testing.T) {
	ensureConfig(t)

	r := gin.New()
	r.Use(Auth())
	r.GET("/api/v1/user", func(c *gin.Context) { c.Status(http.StatusOK) })

	tokenStr, _, err := auth.IssueToken("testuser", "different-secret", false)
	if err != nil {
		t.Fatalf("IssueToken: %v", err)
	}

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/user", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

// findConfigDir 向上查找包含 ssm.yaml 的 config 目录。
func findConfigDir() string {
	wd, _ := os.Getwd()
	for {
		cfgPath := filepath.Join(wd, "config", "ssm.yaml")
		if _, err := os.Stat(cfgPath); err == nil {
			return filepath.Join(wd, "config")
		}
		parent := filepath.Dir(wd)
		if parent == wd {
			break
		}
		wd = parent
	}
	return ""
}

// ensureConfig 确保 config 已初始化。
func ensureConfig(t *testing.T) {
	t.Helper()
	if config.Conf.GetViper() != nil {
		return
	}
	dir := findConfigDir()
	if dir != "" {
		config.LoadFromDir(dir)
		return
	}
	// 回退：手动 LoadFromDir 不存在的 dir 以触发 SetDefault
	config.LoadFromDir(t.TempDir())
}
