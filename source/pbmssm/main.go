package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"bmssm/initialization"
	"bmssm/logger"
)

func main() {
	// 子命令：bmssm reset-password [username] —— 把指定用户（默认 admin）密码
	// 重置为配置的默认密码。服务运行期间也可执行，无需停服重启。
	if len(os.Args) >= 2 && os.Args[1] == "reset-password" {
		username := ""
		if len(os.Args) >= 3 {
			username = os.Args[2]
		}
		os.Exit(initialization.RunResetPassword(username))
	}

	initialization.InitBase()
	r := initialization.Routers()
	s := initialization.InitServer(r)

	go func() {
		if err := s.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("listen failed: %v", err)
			logger.Sync()
			os.Exit(1)
		}
	}()

	logger.Info("ssm ready")

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGHUP, syscall.SIGINT, syscall.SIGTERM, syscall.SIGQUIT)
	sg := <-sig
	logger.Info("signal %v received, shutting down", sg)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		logger.Error("graceful shutdown failed: %v", err)
	}
	logger.Sync()
}
