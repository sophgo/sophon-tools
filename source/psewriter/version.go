package main

// 构建时由 build.sh 注入:
//
//	-X main.toolVersion=<tools/winflash/VERSION>
//	-X main.buildVersion=<build/VERSION>   (固件版本, 用于默认输出命名)
var (
	toolVersion  = "dev"
	buildVersion = ""
)
