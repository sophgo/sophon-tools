// Package user 提供用户管理 MVC 模块：CRUD + 登录/注销。
package user

import (
	"time"
)

// User 用户数据库模型。
type User struct {
	ID        uint      `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	Username  string    `gorm:"column:username;not null;uniqueIndex" json:"username"`
	Password  string    `gorm:"column:password_hash;not null" json:"-"` // bcrypt 哈希，JSON 不输出
	Role      string    `gorm:"column:role;default:'user'" json:"role"`
	CreatedAt time.Time `gorm:"column:created_at" json:"createdAt"`
}

// TableName 自定义表名。
func (User) TableName() string { return "users" }

// CreateUserRequest 创建用户请求体。
type CreateUserRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
	Role     string `json:"role"`
}

// LoginRequest 登录请求体。
type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// LoginResponse 登录响应体。ChangePass=true 表示密码仍是默认密码，前端应引导改密。
type LoginResponse struct {
	Token       string    `json:"token"`
	ExpiresAt   time.Time `json:"expiresAt"`
	Role        string    `json:"role"`
	ChangePass  bool      `json:"changePass,omitempty"`
}

// ChangePasswordRequest 改密请求体（明文，不 md5）。
type ChangePasswordRequest struct {
	OldPassword string `json:"oldPassword"`
	NewPassword string `json:"newPassword" binding:"required"`
}

// ChangePasswordResponse 改密成功后返回新正式 token。
type ChangePasswordResponse struct {
	Token     string    `json:"token"`
	ExpiresAt time.Time `json:"expiresAt"`
	Role      string    `json:"role"`
}

// UserResponse 用户信息响应（不含密码）。
type UserResponse struct {
	ID        uint      `json:"id"`
	Username  string    `json:"username"`
	Role      string    `json:"role"`
	CreatedAt time.Time `json:"createdAt"`
}

// ErrorResponse 统一错误响应。
type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}
