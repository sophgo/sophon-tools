// Package auth 提供 JWT token 签发与解析。
package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// TokenTTL 为 JWT 默认有效期 12 小时。
const TokenTTL = 12 * time.Hour

// IssueToken 用 HS256 签发 JWT，payload 含 username 与 exp。
func IssueToken(username string, secret string) (tokenString string, expiresAt time.Time, err error) {
	now := time.Now()
	expiresAt = now.Add(TokenTTL)
	claims := jwt.MapClaims{
		"sub": username,
		"iat": now.Unix(),
		"exp": expiresAt.Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err = token.SignedString([]byte(secret))
	return
}

// ParseToken 解析并验证 JWT，成功返回 username。
func ParseToken(tokenString string, secret string) (string, error) {
	token, err := jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(secret), nil
	})
	if err != nil {
		return "", err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || !token.Valid {
		return "", errors.New("invalid token")
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		return "", errors.New("token missing subject")
	}
	return sub, nil
}
