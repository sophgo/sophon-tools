package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"ssm/initialization"
)

func TestServerHealthzEndToEnd(t *testing.T) {
	r := initialization.Routers()
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	// 与 router 包的 TestHealthz 互补：此处走完整中间件链（Recovery/AccessLog/RateLimit）
	var body map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, w.Body.String())
	}
	if body["status"] != "ok" {
		t.Fatalf("status=%s body=%s", body["status"], w.Body.String())
	}
}
