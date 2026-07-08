package user

import (
	"errors"

	"github.com/jinzhu/gorm"
	"golang.org/x/crypto/bcrypt"
)

// UserService 封装用户业务逻辑（不依赖 gin）。
type UserService struct {
	db *gorm.DB
}

// NewService 创建 UserService。
func NewService(db *gorm.DB) *UserService {
	return &UserService{db: db}
}

// ListUsers 返回所有用户列表（不包含密码哈希）。
func (s *UserService) ListUsers() ([]UserResponse, error) {
	var users []User
	if err := s.db.Order("id asc").Find(&users).Error; err != nil {
		return nil, err
	}
	resp := make([]UserResponse, len(users))
	for i, u := range users {
		resp[i] = UserResponse{
			ID:        u.ID,
			Username:  u.Username,
			Role:      u.Role,
			CreatedAt: u.CreatedAt,
		}
	}
	return resp, nil
}

// CountUsers 返回用户总数（供初始化判断表是否为空）。
func (s *UserService) CountUsers() (int, error) {
	var count int
	if err := s.db.Model(&User{}).Count(&count).Error; err != nil {
		return 0, err
	}
	return count, nil
}

// CreateUser 创建用户（bcrypt 哈希密码）。
func (s *UserService) CreateUser(username, password, role string) error {
	if role == "" {
		role = "user"
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	user := User{
		Username: username,
		Password: string(hash),
		Role:     role,
	}
	return s.db.Create(&user).Error
}

// DeleteUser 按 username 删除用户（禁止删除 admin）。
func (s *UserService) DeleteUser(username string) error {
	if username == "admin" {
		return errors.New("cannot delete default admin user")
	}
	return s.db.Where("username = ?", username).Delete(&User{}).Error
}

// Login 验证用户名/密码，成功返回 User。
func (s *UserService) Login(username, password string) (*User, error) {
	var user User
	if err := s.db.Where("username = ?", username).First(&user).Error; err != nil {
		if gorm.IsRecordNotFoundError(err) {
			return nil, errors.New("invalid username or password")
		}
		return nil, err
	}
	if err := bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(password)); err != nil {
		return nil, errors.New("invalid username or password")
	}
	return &user, nil
}

// FindUser 按 username 查询用户（不校验密码）。改密成功后用于回读 role 等字段。
func (s *UserService) FindUser(username string) (*User, error) {
	var user User
	if err := s.db.Where("username = ?", username).First(&user).Error; err != nil {
		return nil, err
	}
	return &user, nil
}

// ChangePassword 修改指定用户的密码：用 bcrypt 重新哈希并写回 DB。
// 调用方负责校验旧密码（正式 token）或跳过（临时 token 首次改密）。
func (s *UserService) ChangePassword(username, newPassword string) error {
	hash, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	res := s.db.Model(&User{}).Where("username = ?", username).Update("password_hash", string(hash))
	if res.Error != nil {
		return res.Error
	}
	if res.RowsAffected == 0 {
		return errors.New("user not found")
	}
	return nil
}
