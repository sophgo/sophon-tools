package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

type blockedSSEFlush struct {
	*httptest.ResponseRecorder
	entered chan struct{}
	release chan struct{}
}

func (w *blockedSSEFlush) Flush() {
	select {
	case w.entered <- struct{}{}:
	default:
	}
	<-w.release
}

func TestSSOCapacityRetainedUntilHandlerExit(t *testing.T) {
	resetSSOState()
	old := sseMaxClientsGlobal
	sseMaxClientsGlobal = 1
	defer func() { sseMaxClientsGlobal = old; resetSSOState() }()
	SSORegister("a", "a")
	w := &blockedSSEFlush{httptest.NewRecorder(), make(chan struct{}, 1), make(chan struct{})}
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest("GET", "/api/sso/events", nil)
	c.Request.Header.Set("Authorization", "Bearer a")
	done := make(chan struct{})
	go func() { SSOEvents(c); close(done) }()
	var releaseOnce sync.Once
	release := func() {
		releaseOnce.Do(func() { close(w.release) })
		select {
		case <-done:
		case <-time.After(time.Second):
			t.Error("handler failed to exit")
		}
	}
	defer release()
	select {
	case <-w.entered:
	case <-time.After(time.Second):
		t.Fatal("handler did not reach flush")
	}
	SSORegister("b", "b")
	SSORegister("a", "a")
	SSORegister("b", "b") // Repeated transitions must not send on the closed old channel.
	select {
	case <-done:
		t.Fatal("blocked handler unexpectedly exited")
	default:
	}
	if got := ssoConnCount(); got != 1 {
		t.Errorf("old handler still blocked: tracked=%d want=1", got)
	}
	cl, status := sseRegisterClient("b", "second-ip")
	if cl != nil {
		defer sseUnregisterClient("b", cl)
	}
	if status != http.StatusTooManyRequests {
		t.Errorf("new subscription admitted while real cap reached: status=%d want=429", status)
	}
	release()
	if got := ssoConnCount(); got != 0 {
		t.Fatalf("handler exited: tracked=%d want=0", got)
	}
	cl, status = sseRegisterClient("b", "third-ip")
	if cl != nil {
		defer sseUnregisterClient("b", cl)
	}
	if status != http.StatusOK {
		t.Fatalf("released slot not reusable: status=%d", status)
	}
}
