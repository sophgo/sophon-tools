package initialization

import (
	"fmt"
	"os"

	"github.com/jinzhu/gorm"
	_ "github.com/jinzhu/gorm/dialects/sqlite"
	_ "github.com/mattn/go-sqlite3"

	"bmssm/config"
	"bmssm/database"
	mwuser "bmssm/mvc/user"
)

// RunResetPassword 把指定用户的密码重置为配置中的默认密码（server.defaultPassword）。
// 在服务运行期间也可安全执行：以独立连接打开同一 sqlite 文件，DSN 设 _busy_timeout
// 避让在途写事务、_txlock=immediate 尽早取写锁；用户存在则改密，不存在则仅 admin
// 重建（非 admin 用户缺失时报错，避免误建普通账号）。返回进程退出码。
func RunResetPassword(username string) int {
	if username == "" {
		username = "admin"
	}

	config.LoadConfig()
	conf := &config.Conf
	conf.RLock()
	dbPath := conf.GetViper().GetString("db.path")
	defaultPassword := conf.GetViper().GetString("server.defaultPassword")
	conf.RUnlock()
	if defaultPassword == "" {
		defaultPassword = "admin"
	}

	// 独立连接：busy_timeout 让与服务在途写事务撞上时等待而非立即 locked。
	dsn := dbPath + "?_busy_timeout=10000&_txlock=immediate"
	db, err := gorm.Open("sqlite3", dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open db %s failed: %v\n", dbPath, err)
		return 1
	}
	defer db.Close()

	// 确保表存在（仅迁移已注册模型，无副作用）。
	if err := database.Migrate(db); err != nil {
		fmt.Fprintf(os.Stderr, "migrate failed: %v\n", err)
		return 1
	}

	svc := mwuser.NewService(db)
	if _, err := svc.FindUser(username); err == nil {
		if err := svc.ChangePassword(username, defaultPassword); err != nil {
			fmt.Fprintf(os.Stderr, "reset password for %s failed: %v\n", username, err)
			return 1
		}
		fmt.Printf("password of '%s' has been reset to the configured default.\n", username)
		return 0
	} else if gorm.IsRecordNotFoundError(err) {
		if username != "admin" {
			fmt.Fprintf(os.Stderr, "user '%s' not found; only 'admin' can be (re)created on reset\n", username)
			return 1
		}
		if err := svc.CreateUser("admin", defaultPassword, "superuser"); err != nil {
			fmt.Fprintf(os.Stderr, "create default admin failed: %v\n", err)
			return 1
		}
		fmt.Printf("default admin user created with the configured default password.\n")
		return 0
	} else {
		fmt.Fprintf(os.Stderr, "query user %s failed: %v\n", username, err)
		return 1
	}
}
