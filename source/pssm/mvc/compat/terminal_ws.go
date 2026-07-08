package compat

import (
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"sync"
	"time"

	"github.com/creack/pty"
	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"ssm/pkg/auth"
	"ssm/pkg/response"
)

// wsUpgrader 升级 WebSocket 连接。CheckOrigin 全放行——JWT 已在 handler 内校验，
// 前端经 sophliteos 反代同源访问，无需再校验 Origin。
var wsUpgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

// 控制消息协议（前端 → ssm，BinaryMessage）：
//   首字节 0x01 = resize，后跟 cols(uint16 LE) + rows(uint16 LE)，共 5 字节。
// 其余 BinaryMessage 与所有 TextMessage 视为终端原始输入，直接写入 pty。
const wsCtrlResize = 0x01

// wsIdleTimeout 30 分钟无任何 WebSocket 消息即关闭会话。
const wsIdleTimeout = 30 * time.Minute

// TerminalWS GET /api/v1/hardware/terminal?token=<jwt>
// 实时交互终端：WebSocket 升级后启动 shell pty，双向 pump。
// 鉴权：浏览器无法加 Authorization header，token 从 query ?token= 取，
// handler 内手动 auth.ParseToken 校验，失败 401。
func (ctrl *Controller) TerminalWS(c *gin.Context) {
	// 1) JWT 校验（query token，不走 Auth 中间件）
	// 与 Auth 中间件一致：临时 token（temp=true，默认密码登录态）拒绝，需先改密，
	// 避免默认密码态开 root 交互终端。
	tokenStr := c.Query("token")
	if tokenStr == "" {
		c.JSON(http.StatusUnauthorized, response.Fail("missing token"))
		return
	}
	_, temp, err := auth.ParseToken(tokenStr, getSecret())
	if err != nil {
		c.JSON(http.StatusUnauthorized, response.Fail("invalid token"))
		return
	}
	if temp {
		c.JSON(http.StatusForbidden, response.Fail("must change password first"))
		return
	}

	// 2) WebSocket 升级
	wsConn, err := wsUpgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer wsConn.Close()

	// 3) 启动 shell pty：优先 bash，没有则 sh；默认账户家目录
	shell := "sh"
	if p, lerr := exec.LookPath("bash"); lerr == nil {
		shell = p
	}
	cmd := exec.Command(shell)
	// os/user.Current() 读 /etc/passwd 取家目录，不依赖 $HOME —— ssm 以 systemd root 运行，
	// 服务环境默认无 HOME 变量。兜底 /root。
	homeDir := "/root"
	if u, uerr := user.Current(); uerr == nil && u.HomeDir != "" {
		homeDir = u.HomeDir
	}
	if st, serr := os.Stat(homeDir); serr == nil && st.IsDir() {
		cmd.Dir = homeDir
	}
	cmd.Env = append(os.Environ(), "TERM=xterm-256color", "HOME="+homeDir)
	ptmx, err := pty.StartWithSize(cmd, &pty.Winsize{Rows: 24, Cols: 80})
	if err != nil {
		_ = wsConn.WriteMessage(websocket.TextMessage,
			[]byte("\r\n*** failed to start shell: "+err.Error()+" ***\r\n"))
		return
	}

	// 4) 清理
	var once sync.Once
	cleanup := func() {
		once.Do(func() {
			_ = ptmx.Close()
			if cmd.Process != nil {
				_ = cmd.Process.Kill()
			}
		})
	}
	defer cleanup()

	// pump: sh 输出 → 前端
	go func() {
		buf := make([]byte, 4096)
		for {
			n, err := ptmx.Read(buf)
			if n > 0 {
				if werr := wsConn.WriteMessage(websocket.BinaryMessage, buf[:n]); werr != nil {
					cleanup()
					return
				}
			}
			if err != nil {
				_ = wsConn.WriteMessage(
					websocket.CloseMessage,
					websocket.FormatCloseMessage(websocket.CloseNormalClosure, "shell exited"),
				)
				cleanup()
				return
			}
		}
	}()

	// pump: 前端输入 → sh（主循环，含 resize 控制与 30min 空闲超时）
	for {
		_ = wsConn.SetReadDeadline(time.Now().Add(wsIdleTimeout))
		msgType, payload, err := wsConn.ReadMessage()
		if err != nil {
			cleanup()
			return
		}
		switch msgType {
		case websocket.TextMessage:
			_, _ = ptmx.Write(payload)
		case websocket.BinaryMessage:
			if len(payload) >= 5 && payload[0] == wsCtrlResize {
				cols := uint16(payload[1]) | uint16(payload[2])<<8
				rows := uint16(payload[3]) | uint16(payload[4])<<8
				if cols > 0 && rows > 0 {
					_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
				}
				continue
			}
			_, _ = ptmx.Write(payload)
		case websocket.PingMessage, websocket.PongMessage:
		}
	}
}
