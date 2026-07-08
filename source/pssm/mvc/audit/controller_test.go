package audit

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"ssm/config"
	"ssm/middleware"
	"ssm/pkg/auth"
	"ssm/pkg/response"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func setupAuditController(t *testing.T) (*Controller, func()) {
	t.Helper()
	db := setupTestDB(t)

	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}

	svc := NewService(db)
	ctrl := NewController(svc)
	return ctrl, func() { db.Close() }
}

func TestListAuditLogsWithAuth(t *testing.T) {
	ctrl, cleanup := setupAuditController(t)
	defer cleanup()

	_ = ctrl.svc.Write("admin", "login", "user", "192.168.1.1", "success")
	_ = ctrl.svc.Write("bob", "create_user", "user", "10.0.0.1", "success")

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/audit", ctrl.ListLogs)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/audit?offset=0&limit=10", nil)
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
	raw, _ := json.Marshal(resp.Result)
	var result PaginatedResult
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if result.Total != 2 {
		t.Fatalf("expected 2 logs, got %d", result.Total)
	}
}

func TestListAuditLogsWithoutToken(t *testing.T) {
	ctrl, cleanup := setupAuditController(t)
	defer cleanup()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/audit", ctrl.ListLogs)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/audit", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}
