package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"bmssm/database"
	"bmssm/pkg/response"
)

// RequireAdmin 要求当前请求用户具备 superuser 或 admin 角色。
// 在 Auth() 之后使用；c.Get("user") 由 Auth 中间件写入用户名。
// 角色取自已登录用户对应的 users 行；查询失败或非管理员返回 403。
// 注意：直接查 users 表而非依赖 mvc/user 包，避免中间件层与控制器包形成 import 环。
func RequireAdmin() gin.HandlerFunc {
	return func(c *gin.Context) {
		actor, _ := c.Get("user")
		actorStr, _ := actor.(string)
		if actorStr == "" {
			c.JSON(http.StatusForbidden, response.Fail("admin role required"))
			c.Abort()
			return
		}
		db := database.DB()
		if db == nil {
			c.JSON(http.StatusInternalServerError, response.Fail("database unavailable"))
			c.Abort()
			return
		}
		var roles []string
		if err := db.Table("users").Where("username = ?", actorStr).Pluck("role", &roles).Error; err != nil {
			c.JSON(http.StatusForbidden, response.Fail("admin role required"))
			c.Abort()
			return
		}
		// GORM v1 Pluck 目标是 slice；取第一行角色。
		role := ""
		if len(roles) > 0 {
			role = roles[0]
		}
		if role != "superuser" && role != "admin" {
			c.JSON(http.StatusForbidden, response.Fail("admin role required"))
			c.Abort()
			return
		}
		c.Next()
	}
}
