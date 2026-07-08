package alarm

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	_ "github.com/jinzhu/gorm/dialects/sqlite"

	"bmssm/config"
	"bmssm/middleware"
	"bmssm/pkg/auth"
	"bmssm/pkg/response"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func setupAlarmController(t *testing.T) (*Controller, func()) {
	t.Helper()
	db := setupTestDB(t)

	if config.Conf.GetViper() == nil {
		config.LoadFromDir(t.TempDir())
	}

	svc := NewService(db)
	ctrl := NewController(svc)
	return ctrl, func() { db.Close() }
}

func TestListAlarmsWithAuth(t *testing.T) {
	ctrl, cleanup := setupAlarmController(t)
	defer cleanup()

	_ = ctrl.svc.SaveAlarm(Alarm{Code: -101001, ComponentType: "cpu", Msg: "cpu高"})
	_ = ctrl.svc.SaveAlarm(Alarm{Code: -201001, ComponentType: "board", Msg: "板温高"})

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/alarms", ctrl.ListAlarms)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alarms?offset=0&limit=10", nil)
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
		t.Fatalf("expected code=0, got %d", resp.Code)
	}
	raw, _ := json.Marshal(resp.Result)
	var result PaginatedResult
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatalf("unmarshal result: %v body=%s", err, w.Body.String())
	}
	if result.Total != 2 {
		t.Fatalf("expected 2 alarms, got %d", result.Total)
	}
}

func TestListAlarmsWithoutToken(t *testing.T) {
	ctrl, cleanup := setupAlarmController(t)
	defer cleanup()

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/alarms", ctrl.ListAlarms)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alarms", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestListAlarmsFilterComponentType(t *testing.T) {
	ctrl, cleanup := setupAlarmController(t)
	defer cleanup()

	_ = ctrl.svc.SaveAlarm(Alarm{Code: -101001, ComponentType: "cpu"})
	_ = ctrl.svc.SaveAlarm(Alarm{Code: -201001, ComponentType: "board"})

	r := gin.New()
	api := r.Group("/api/v1")
	api.Use(middleware.Auth())
	api.GET("/alarms", ctrl.ListAlarms)

	secret := config.Conf.GetViper().GetString("server.authSecret")
	tokenStr, _, _ := auth.IssueToken("admin", secret, false)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alarms?componentType=board", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var resp response.Result
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	raw, _ := json.Marshal(resp.Result)
	var result PaginatedResult
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if result.Total != 1 || result.Items[0].ComponentType != "board" {
		t.Fatalf("expected 1 board alarm, got total=%d", result.Total)
	}
}
