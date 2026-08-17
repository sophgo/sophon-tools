package mvc

import (
	"net/http/httptest"
	"testing"
)

// Token 必须返回归一化后的裸 token：
//   - 剥离 "Bearer " 前缀（前端 defHttp 以 `Bearer <jwt>` 发送）
//   - 容忍头尾空白与大小写变体（HTTP 头值不要求严格格式）
//
// 归一化前的旧行为返回完整 Authorization 头（含前缀），导致
// database.QueryUserWithToken / tokenCache 永远查不到裸 token 记录，
// 操作审计静默失效（MYS-382）。
func TestTokenNormalized(t *testing.T) {
	cases := []struct {
		name   string
		header string
		want   string
	}{
		{name: "bearer prefix stripped", header: "Bearer abc.def.ghi", want: "abc.def.ghi"},
		{name: "bare token passthrough", header: "abc.def.ghi", want: "abc.def.ghi"},
		{name: "lowercase bearer", header: "bearer abc.def.ghi", want: "abc.def.ghi"},
		{name: "leading spaces trimmed", header: "   Bearer abc.def.ghi   ", want: "abc.def.ghi"},
		{name: "multiple spaces after bearer", header: "Bearer   abc.def.ghi", want: "abc.def.ghi"},
		{name: "empty header", header: "", want: ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req := httptest.NewRequest("GET", "/api/device/ota/list", nil)
			if c.header != "" {
				req.Header.Set(authorization, c.header)
			}
			if got := Token(req); got != c.want {
				t.Fatalf("Token(%q) = %q, want %q", c.header, got, c.want)
			}
		})
	}
}
