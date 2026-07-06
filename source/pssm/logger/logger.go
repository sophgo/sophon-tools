// Package logger 封装 zap，提供全局 Info/Warn/Error/Debug。
// console + file（lumberjack 按大小 rotate）双输出。
package logger

import (
	"os"
	"strings"
	"sync/atomic"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
	"gopkg.in/natefinch/lumberjack.v2"
)

const (
	zapDebugLevel = zapcore.DebugLevel
	zapInfoLevel  = zapcore.InfoLevel
	zapWarnLevel  = zapcore.WarnLevel
	zapErrorLevel = zapcore.ErrorLevel
)

var logging atomic.Pointer[zap.Logger]

// InitLogging 初始化全局日志：dir=日志目录，filename=文件名，level=debug/info/warn/error。
func InitLogging(dir, filename, level string) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		panic(err)
	}

	lvl := parseLevel(level)
	encoderCfg := zapcore.EncoderConfig{
		TimeKey:        "ts",
		LevelKey:       "level",
		NameKey:        "logger",
		CallerKey:      "caller",
		MessageKey:     "msg",
		StacktraceKey:  "stacktrace",
		LineEnding:     "\n",
		EncodeLevel:    zapcore.CapitalLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.StringDurationEncoder,
		EncodeCaller:   zapcore.ShortCallerEncoder,
	}

	fileWriter := zapcore.AddSync(&lumberjack.Logger{
		Filename:   dir + "/" + filename,
		MaxSize:    100, // MB
		MaxBackups: 10,
		MaxAge:     30,
	})
	consoleWriter := zapcore.Lock(os.Stdout)

	core := zapcore.NewTee(
		zapcore.NewCore(zapcore.NewConsoleEncoder(encoderCfg), consoleWriter, lvl),
		zapcore.NewCore(zapcore.NewConsoleEncoder(encoderCfg), fileWriter, lvl),
	)
	logging.Store(zap.New(core, zap.AddCaller(), zap.AddCallerSkip(1)))
}

func parseLevel(level string) zapcore.Level {
	switch strings.ToLower(level) {
	case "debug":
		return zapDebugLevel
	case "info":
		return zapInfoLevel
	case "warn", "warning":
		return zapWarnLevel
	case "error":
		return zapErrorLevel
	default:
		return zapInfoLevel
	}
}

func _sync() {
	if l := logging.Load(); l != nil {
		_ = l.Sync()
	}
}

// Debug/Info/Warn/Error 全局快捷函数。
func Debug(format string, args ...interface{}) {
	if l := logging.Load(); l != nil {
		l.Sugar().Debugf(format, args...)
	}
}

func Info(format string, args ...interface{}) {
	if l := logging.Load(); l != nil {
		l.Sugar().Infof(format, args...)
	}
}

func Warn(format string, args ...interface{}) {
	if l := logging.Load(); l != nil {
		l.Sugar().Warnf(format, args...)
	}
}

func Error(format string, args ...interface{}) {
	if l := logging.Load(); l != nil {
		l.Sugar().Errorf(format, args...)
	}
}

// Sync 刷新缓冲，进程退出前调用。
func Sync() { _sync() }