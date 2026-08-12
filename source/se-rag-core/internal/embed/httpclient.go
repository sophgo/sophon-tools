package embed

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const maxAttempts = 6

// postJSON POST JSON 到 url，带 Bearer 鉴权。
// 5xx/429/连接错误 → 指数退避重试（最多6次）；4xx → 快速失败不重试。
func postJSON(ctx context.Context, url, key string, payload, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	var lastErr error
	for attempt := 0; attempt < maxAttempts; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(backoff(attempt))
			continue
		}
		if resp.StatusCode == 200 {
			defer resp.Body.Close()
			if out != nil {
				if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
					return err
				}
			}
			return nil
		}
		body400, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		retriable := resp.StatusCode == 408 || resp.StatusCode == 429 || resp.StatusCode >= 500
		if !retriable {
			return fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		}
		lastErr = fmt.Errorf("http %d: %s", resp.StatusCode, string(body400))
		time.Sleep(backoff(attempt))
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no successful response after %d attempts", maxAttempts)
	}
	return fmt.Errorf("postJSON failed: %w", lastErr)
}

func backoff(attempt int) time.Duration {
	d := 100 * time.Millisecond
	for i := 0; i < attempt; i++ {
		d *= 2
		if d > 2*time.Second {
			d = 2 * time.Second
		}
	}
	return d
}
