package global

// 构建时由 ldflags 注入（-X 仅支持包级 string 变量）：
//
//	-X ssm/global.version=... -X ssm/global.gitCommit=... -X ssm/global.buildTime=...
var (
	version   = "dev"
	gitCommit = "unknown"
	buildTime = "unknown"
)

// Version 由 ldflags 注入的 string 变量初始化。
var Version = BuildInfo{
	Version:   version,
	GitCommit: gitCommit,
	BuildTime: buildTime,
}