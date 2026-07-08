package router

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"bmssm/global"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestHealthz(t *testing.T) {
	global.DeviceType = "soc"
	global.DeviceRole = "SE"
	global.DeviceTypeEx = "SE8"
	global.DeviceSnEx = "DEVSN456"
	global.Version = global.BuildInfo{Version: "1.0.0", GitCommit: "abc", BuildTime: "2026-01-01"}

	r := gin.New()
	Register(r)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if body["status"] != "ok" {
		t.Fatalf("status=%s", body["status"])
	}
	if body["deviceType"] != "soc" {
		t.Fatalf("deviceType=%s", body["deviceType"])
	}
	if body["role"] != "SE" {
		t.Fatalf("role=%s", body["role"])
	}
	if body["deviceTypeEx"] != "SE8" {
		t.Fatalf("deviceTypeEx=%s", body["deviceTypeEx"])
	}
	if body["sn"] != "DEVSN456" {
		t.Fatalf("sn=%s", body["sn"])
	}
	if body["version"] != "1.0.0" {
		t.Fatalf("version=%s", body["version"])
	}
	if body["uptime"] == "" {
		t.Fatalf("uptime empty")
	}
}
