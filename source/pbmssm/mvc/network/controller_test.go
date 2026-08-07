package network

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	"bmssm/middleware"
	"bmssm/pkg/auth"
	netpkg "bmssm/pkg/network"
	"bmssm/pkg/response"
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

	secret := auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/network/ip", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if resp.Code != 0 {
		t.Fatalf("expected code=0, got %d body=%s", resp.Code, w.Body.String())
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

	secret := auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	body, _ := json.Marshal(SetIPRequest{
		Device:     "eth0",
		IPType:     1,
		IP:         "192.168.1.100",
		SubnetMask: "255.255.255.0",
		Gateway:    "192.168.1.1",
		DNS:        "8.8.8.8",
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

	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if w.Code == http.StatusOK && resp.Code != 0 {
		t.Fatalf("expected code=0, got %d body=%s", resp.Code, w.Body.String())
	}
	if w.Code == http.StatusInternalServerError && resp.Code != 1 {
		t.Fatalf("expected code=1, got %d body=%s", resp.Code, w.Body.String())
	}
}

func TestAddNATWithAuth(t *testing.T) {
	setupNetworkTest(t)

	ctrl := DefaultController()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.POST("/network/nat", ctrl.AddNAT)

	secret := auth.EffectiveSecret(config.Conf.GetViper().GetString("server.authSecret"))
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	body, _ := json.Marshal(NatRequest{
		Direction: "in",
		Op:        "append",
		Dst:       "192.168.1.100",
		Src:       "10.0.0.1",
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

	var resp response.Result
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if w.Code == http.StatusOK && resp.Code != 0 {
		t.Fatalf("expected code=0, got %d body=%s", resp.Code, w.Body.String())
	}
	if w.Code == http.StatusInternalServerError && resp.Code != 1 {
		t.Fatalf("expected code=1, got %d body=%s", resp.Code, w.Body.String())
	}

	// 清理：添加成功时该测试在真实 nat 表里留下了一条规则（iptables 可用时），
	// 必须删除，否则后续依赖 nat 表状态的测试（如 compat 的 DeleteNAT 校验）会被污染。
	if w.Code == http.StatusOK {
		t.Cleanup(func() {
			_ = netpkg.AddNATRule(netpkg.NatRule{Direction: "in", Operation: "delete", Dst: "192.168.1.100", Src: "10.0.0.1"})
		})
	}
}
