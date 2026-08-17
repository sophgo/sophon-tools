package compat

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"bmssm/database"
	"bmssm/mvc/user"
	"bmssm/pkg/auth"
)

// ---------------------------------------------------------------
// TerminalWS 越权修复测试（MYS-384）
//
// 交互终端以 root 运行，仅 superuser/admin 角色可用。
// 所有握手走真实 WebSocket Dial（与浏览器攻击路径一致），
// 失败路径断言 HTTP 状态码，成功路径验证 pty 有输出。
// ---------------------------------------------------------------

// issueUserToken 直接签发测试 JWT（secret=auth.DefaultSecret，与未加载配置时 getSecret 一致）。
func issueUserToken(t *testing.T, username, secret string, temp bool) string {
	t.Helper()
	tok, _, err := auth.IssueToken(username, secret, temp)
	if err != nil {
		t.Fatalf("IssueToken(%s): %v", username, err)
	}
	return tok
}

// wsHandshake 以 token 发起终端 WebSocket 握手，返回 (conn, HTTP 状态码)。
// 失败时 conn 为 nil；调用方负责关闭 conn。
func wsHandshake(t *testing.T, srv *httptest.Server, token string) (*websocket.Conn, int) {
	t.Helper()
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/api/v1/hardware/terminal?token=" + token
	conn, resp, err := websocket.DefaultDialer.Dial(url, nil)
	if resp != nil {
		defer resp.Body.Close()
	}
	if err != nil {
		if conn != nil {
			conn.Close()
		}
		if resp == nil {
			t.Fatalf("dial %s: %v (no response)", url, err)
		}
		return nil, resp.StatusCode
	}
	return conn, resp.StatusCode
}

// readUntilShellMarker 读 pty 输出直到看到 marker，超时 5s。
func readUntilShellMarker(t *testing.T, conn *websocket.Conn, marker string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	buf := make([]byte, 0, 256)
	for time.Now().Before(deadline) {
		_ = conn.SetReadDeadline(deadline)
		_, msg, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read shell output: %v (got %q, marker %q)", err, string(buf), marker)
		}
		buf = append(buf, msg...)
		if strings.Contains(string(buf), marker) {
			return
		}
	}
	t.Fatalf("shell marker %q not seen within 5s, got %q", marker, string(buf))
}

// TestTerminalWSAuthFailures 无 token / 非法 token / 错误 secret → 401。
func TestTerminalWSAuthFailures(t *testing.T) {
	r := setupCompatTest(t)
	srv := httptest.NewServer(r)
	defer srv.Close()

	cases := []struct {
		name  string
		token string
	}{
		{"missing token", ""},
		{"invalid jwt", "not-a-jwt"},
		{"wrong secret", issueUserToken(t, "admin", "wrong-secret", false)},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, code := wsHandshake(t, srv, tc.token); code != http.StatusUnauthorized {
				t.Errorf("status=%d, want 401", code)
			}
		})
	}
}

// TestTerminalWSTempTokenRejected 临时 token（默认密码登录态）→ 403。
func TestTerminalWSTempTokenRejected(t *testing.T) {
	r := setupCompatTest(t)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := issueUserToken(t, "admin", auth.DefaultSecret, true)
	if _, code := wsHandshake(t, srv, token); code != http.StatusForbidden {
		t.Errorf("status=%d, want 403", code)
	}
}

// TestTerminalWSUserRoleForbidden 普通 user 角色的正式 token → 403（越权回归用例）。
// 修复前：角色不被检查，普通 user 可升级 WebSocket 开 root shell。
func TestTerminalWSUserRoleForbidden(t *testing.T) {
	r := setupCompatTest(t)
	if err := user.NewService(database.DB()).CreateUser("alice", "realpass", "user"); err != nil {
		t.Fatalf("create alice: %v", err)
	}
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := issueUserToken(t, "alice", auth.DefaultSecret, false)
	if _, code := wsHandshake(t, srv, token); code != http.StatusForbidden {
		t.Errorf("status=%d, want 403 (user role must not open terminal)", code)
	}
}

// TestTerminalWSUnknownUserForbidden 用户已被删除（token 仍有效）→ 403（fail-closed）。
func TestTerminalWSUnknownUserForbidden(t *testing.T) {
	r := setupCompatTest(t)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := issueUserToken(t, "ghost", auth.DefaultSecret, false)
	if _, code := wsHandshake(t, srv, token); code != http.StatusForbidden {
		t.Errorf("status=%d, want 403 (deleted user must not open terminal)", code)
	}
}

// TestTerminalWSAdminRoleAllowed admin 角色 → 升级成功，pty 输出可见。
func TestTerminalWSAdminRoleAllowed(t *testing.T) {
	r := setupCompatTest(t)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := issueUserToken(t, "admin", auth.DefaultSecret, false) // setupCompatTest 创建 role=admin
	conn, code := wsHandshake(t, srv, token)
	if code != http.StatusSwitchingProtocols {
		t.Fatalf("status=%d, want 101 (admin should get WebSocket)", code)
	}
	defer conn.Close()

	if err := conn.WriteMessage(websocket.TextMessage, []byte("echo TWS-ADMIN-OK\nexit\n")); err != nil {
		t.Fatalf("write: %v", err)
	}
	readUntilShellMarker(t, conn, "TWS-ADMIN-OK")
}

// TestTerminalWSSuperuserRoleAllowed superuser 角色 → 升级成功，pty 输出可见。
func TestTerminalWSSuperuserRoleAllowed(t *testing.T) {
	r := setupCompatTest(t)
	if err := user.NewService(database.DB()).CreateUser("boss", "realpass", "superuser"); err != nil {
		t.Fatalf("create boss: %v", err)
	}
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := issueUserToken(t, "boss", auth.DefaultSecret, false)
	conn, code := wsHandshake(t, srv, token)
	if code != http.StatusSwitchingProtocols {
		t.Fatalf("status=%d, want 101 (superuser should get WebSocket)", code)
	}
	defer conn.Close()

	if err := conn.WriteMessage(websocket.TextMessage, []byte("echo TWS-SU-OK\nexit\n")); err != nil {
		t.Fatalf("write: %v", err)
	}
	readUntilShellMarker(t, conn, "TWS-SU-OK")
}