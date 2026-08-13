package main

import (
	"io/fs"
	"time"

	"sophliteos/initialization"
	"sophliteos/logger"
)

func main() {
	initialization.InitBase()
	// 内嵌 FS 根为 dist/（//go:embed dist），取子目录使其暴露在前端期望的服务器根路径
	// （index.html/assets/_app.config.js 均以根路径 / 引用，见 vite base=/）。
	webFS, err := fs.Sub(embeddedWeb, "dist")
	if err != nil {
		logger.Error("fs.Sub(embeddedWeb,\"dist\") failed: %v", err)
		webFS = embeddedWeb
	}
	Router := initialization.Routers(webFS)
	s := initialization.InitServer(Router)

	time.Sleep(10 * time.Microsecond)

	err = s.ListenAndServe()
	if err != nil {
		logger.Error("An error occurred starting HTTP listener %v", err)
	}
}
