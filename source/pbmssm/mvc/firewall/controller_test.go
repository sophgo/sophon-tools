package firewall

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestStatusEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	ctrl := DefaultController()
	r.GET("/firewall/status", ctrl.Status)
	req, _ := http.NewRequest("GET", "/firewall/status", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("got %d", w.Code)
	}
}
