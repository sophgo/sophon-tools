package network

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"ssm/config"
	"ssm/middleware"
	"ssm/pkg/auth"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func setupNetworkTest(t *testing.T) {
	t.Helper()
	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}
}

func TestGetIPWithAuth(t *testing.T) {
	setupNetworkTest(t)

	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/network/ip", ctrl.GetIP)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/network/ip", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestGetIPWithoutToken(t *testing.T) {
	setupNetworkTest(t)

	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/network/ip", ctrl.GetIP)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/network/ip", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestSetIPWithAuth(t *testing.T) {
	setupNetworkTest(t)

	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.PUT("/network/ip", ctrl.SetIP)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret)

	body, _ := json.Marshal(SetIPRequest{
		Device:  "eth0",
		IP:      "192.168.1.100",
		Mask:    "255.255.255.0",
		Gateway: "192.168.1.1",
		DNS:     "8.8.8.8",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPut, "/api/v1/network/ip", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	// 在无真实网卡环境下可能失败，但 HTTP 层应正确结构
	if w.Code != http.StatusOK && w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 200 or 500, got %d body=%s", w.Code, w.Body.String())
	}
}

func TestAddNATWithAuth(t *testing.T) {
	setupNetworkTest(t)

	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/network/nat", ctrl.AddNAT)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret)

	body, _ := json.Marshal(NatRequest{
		Direction: "in",
		Op:   "append",
		Dst:  "192.168.1.100",
		Src:  "10.0.0.1",
	})
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/network/nat", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	// iptables 在测试环境可能不可用，但 HTTP 层应响应
	if w.Code != http.StatusOK && w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 200 or 500, got %d body=%s", w.Code, w.Body.String())
	}
}
