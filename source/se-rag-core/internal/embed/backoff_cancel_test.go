package embed

import (
	"context"
	"errors"
	"io"
	"net/http"
	"se-rag-core/internal/config"
	"strings"
	"testing"
	"time"
)

type cancelTransport func(*http.Request) (*http.Response, error)

func (f cancelTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestCancellationDuringBackoff(t *testing.T) {
	t.Setenv("SE_RAG_STATE_DIR", t.TempDir())
	breaker.reset()
	defer breaker.reset()
	old := httpClient
	defer func() { httpClient = old }()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	httpClient = &http.Client{Transport: cancelTransport(func(r *http.Request) (*http.Response, error) {
		time.AfterFunc(20*time.Millisecond, cancel)
		return &http.Response{StatusCode: 503, Body: io.NopCloser(strings.NewReader("")), Header: make(http.Header), Request: r}, nil
	})}
	var out map[string]any
	_, err := postJSONWithPolicy(ctx, []string{"https://review.invalid/v1"}, "fake", map[string]any{}, &out, config.DefaultConfig().Gateway)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancel during retry sleep must return context.Canceled; got %v", err)
	}
}
