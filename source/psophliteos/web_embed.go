package main

import "embed"

// embeddedWeb 内嵌前端构建产物（packaged dist/）。
// 构建流程（build/build-deb-sophliteos.sh）先把 frontend/dist 合入 dist/，再 go build，
// 使单文件二进制自带整套静态前端。发布物为单文件，无需再随包携带/部署 web 静态目录。
//
//go:embed dist
var embeddedWeb embed.FS
