package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ssm/initialization"
	"ssm/logger"
)

func main() {
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
