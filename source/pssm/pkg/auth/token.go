// Package auth 提供 JWT token 签发与解析。
package auth

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// TokenTTL 为 JWT 默认有效期 12 小时。
const TokenTTL = 12 * time.Hour

// DefaultSecret 是配置占位用的开发默认 secret。
// 配置里 server.authSecret 留空或为此值时，启动会生成随机 secret 持久化使用。
const DefaultSecret = "ssm-dev-secret"

// secretFilePath 持久化随机 secret 的文件路径。
var secretFilePath = "/var/lib/ssm/jwt_secret"

// SecretFilePath 返回当前持久化 secret 文件路径（测试可覆盖）。
func SecretFilePath() string { return secretFilePath }

// SetSecretFilePath 覆盖持久化 secret 文件路径（仅测试使用）。
func SetSecretFilePath(p string) { secretFilePath = p }

// EnsureSecret 返回生效的 JWT secret。
//   - configured 非空且非 DefaultSecret：视为用户显式配置，直接返回，usedRandom=false。
//   - 否则尝试读取持久化文件；存在则复用，避免重启后 token 全部失效。
//   - 文件不存在则生成 32 字节随机 secret（crypto/rand，hex 编码）写入文件 0600。
//
// 返回 (secret, usedRandom, err)。usedRandom=true 时调用方应 WARN 日志提示。
func EnsureSecret(configured string) (secret string, usedRandom bool, err error) {
	if configured != "" && configured != DefaultSecret {
		return configured, false, nil
	}
	// 复用持久化 secret
	if data, rerr := os.ReadFile(secretFilePath); rerr == nil {
		s := strings.TrimSpace(string(data))
		if s != "" {
			return s, true, nil
		}
	} else if !os.IsNotExist(rerr) {
		// 读得到但权限/IO 错误，按错误返回，避免误生成新 secret
		return "", false, fmt.Errorf("read secret file %s: %w", secretFilePath, rerr)
	}
	// 生成新随机 secret
	b := make([]byte, 32)
	if _, cerr := rand.Read(b); cerr != nil {
		return "", false, fmt.Errorf("generate random secret: %w", cerr)
	}
	s := hex.EncodeToString(b)
	if err := os.MkdirAll(filepath.Dir(secretFilePath), 0o700); err != nil {
		return "", false, fmt.Errorf("mkdir for secret file: %w", err)
	}
	if err := os.WriteFile(secretFilePath, []byte(s), 0o600); err != nil {
		return "", false, fmt.Errorf("write secret file %s: %w", secretFilePath, err)
	}
	return s, true, nil
}

// IssueToken 用 HS256 签发 JWT，payload 含 username、exp，temp=true 时为临时 token。
// 临时 token 仅允许调用 /api/v1/password 改密码，其余端点由 Auth 中间件 403 拒绝。
func IssueToken(username string, secret string, temp bool) (tokenString string, expiresAt time.Time, err error) {
	now := time.Now()
	expiresAt = now.Add(TokenTTL)
	claims := jwt.MapClaims{
		"sub": username,
		"iat": now.Unix(),
		"exp": expiresAt.Unix(),
	}
	if temp {
		claims["temp"] = true
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err = token.SignedString([]byte(secret))
	return
}

// ParseToken 解析并验证 JWT，成功返回 username 与 temp 标志。
func ParseToken(tokenString string, secret string) (username string, temp bool, err error) {
	token, err := jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return "", false, err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || !token.Valid {
		return "", false, errors.New("invalid token")
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", false, errors.New("token missing subject")
	}
	if t, ok := claims["temp"].(bool); ok {
		temp = t
	}
	return sub, temp, nil
}
