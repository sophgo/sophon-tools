package services

import (
	"database/sql"
	"net/http/httptest"
	"testing"

	"sophliteos/database"
	"sophliteos/middleware"

	"github.com/jinzhu/gorm"
)

// initTestDB 打开一个空的 sqlite 内存库，避免 SSO 未命中时
// database.QueryUserWithToken 因全局 DB 为 nil 而 panic。
func initTestDB(t *testing.T) {
	t.Helper()
	sqlDb, err := sql.Open("sqlite3_with_go_func", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	db, err := gorm.Open("sqlite3", sqlDb)
	if err != nil {
		t.Fatal(err)
	}
	database.DB = db
}

// 操作审计的用户名解析（MYS-382）：
// 前端以 `Authorization: Bearer <jwt>` 发请求，SSO 会话按裸 token 注册。
// 解析顺序：SSO 活跃会话（本地无 user 表，鉴权在 bmssm）→ DB legacy 记录兜底。
// 这里只测不依赖 DB 的路径：Bearer 头→SSO 会话解析为用户名。
func TestUserNameFor(t *testing.T) {
	initTestDB(t)
	cases := []struct {
		name         string
		registerUser string // 空表示不注册会话
		registerTok  string
		authHeader   string
		want         string
	}{
		{
			name:         "bearer header matches active session",
			registerUser: "tester",
			registerTok:  "tok-alice",
			authHeader:   "Bearer tok-alice",
			want:         "tester",
		},
		{
			name:         "bare header matches active session",
			registerUser: "tester2",
			registerTok:  "tok-bob",
			authHeader:   "tok-bob",
			want:         "tester2",
		},
		{
			name:         "unknown token cannot be attributed",
			registerUser: "tester",
			registerTok:  "tok-alice",
			authHeader:   "Bearer tok-other",
			want:         "",
		},
		{
			name:         "no registered session cannot be attributed",
			registerUser: "",
			registerTok:  "",
			authHeader:   "Bearer tok-whatever",
			want:         "",
		},
		{
			name:         "no auth header cannot be attributed",
			registerUser: "tester",
			registerTok:  "tok-alice",
			authHeader:   "",
			want:         "",
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			// 复位会话状态到本用例前提
			resetSSOSession()
			if c.registerUser != "" {
				middleware.SSORegister(c.registerUser, c.registerTok)
			}

			req := httptest.NewRequest("GET", "/api/upgrade", nil)
			if c.authHeader != "" {
				req.Header.Set("Authorization", c.authHeader)
			}
			if got := userNameFor(req); got != c.want {
				t.Fatalf("userNameFor = %q, want %q", got, c.want)
			}
		})
	}

	resetSSOSession()
}

func resetSSOSession() {
	middleware.SSORegister("", "reset-token")
	middleware.SSOLogout("reset-token")
}
