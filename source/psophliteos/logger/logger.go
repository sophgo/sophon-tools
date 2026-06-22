// Package logger 是系统日志的封装，主要在之上封装了Error，Info两个函数。并提供了跨日期
// 自动分割日志文件的功能。
// 可以在InitLogging 后直接使用logger.Error, logger.Info操作默认的日志对象。
// 也可以用logger.New 创建一个自己的日志对象。
package logger

import (
	"bytes"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/robfig/cron/v3"
)

// logging 是一个默认的日志对象，提供全局的Error, Info函数供使用，必须调用InitLogging
// 函数进行初始化
var logging *Logger

var DEBUG = 0
var INFO = 3
var ERROR = 5

func init() {
	c := cron.New(cron.WithSeconds())
	_, err := c.AddFunc("0 0 0 * * ?", func() {
		DeleteHistoryLog()
	})
	if err != nil {
		fmt.Println("err:", err)
	}
	c.Start()
}

// InitLogging 初始化默认的日志对象，初始化后，就能使用Error，Info函数记录日志
func InitLogging(dir, filename string, level string) {
	var logLevel int
	switch level {
	case "DEBUG":
		logLevel = DEBUG

	case "INFO":
		logLevel = INFO

	case "ERROR":
		logLevel = ERROR

	default:
		logLevel = INFO

	}
	depth := strings.Count(dir, "/")

	logging = New(dir, filename, true, false, logLevel, depth)
}

// Error 默认日志对象方法，记录一条错误日志，需要先初始化
func Error(format string, v ...interface{}) {
	logging.Error(format, v...)
}

// Errorln 默认日志对象方法，记录一条消息日志，需要先初始化
func Errorln(args ...interface{}) {
	logging.Errorln(args...)
}

// Info 默认日志对象方法，记录一条消息日志，需要先初始化
func Info(format string, v ...interface{}) {
	logging.Info(format, v...)
}

// Infoln 默认日志对象方法，记录一条消息日志，需要先初始化
func Infoln(args ...interface{}) {
	logging.Infoln(args...)
}

// IsDebugEnable 日志级别
func IsDebugEnable() bool {
	return logging.level == DEBUG
}

// Debug 默认日志对象方法，记录一条消息日志，需要先初始化
func Debug(format string, v ...interface{}) {
	logging.Debug(format, v...)
}

// Debugln 默认日志对象方法，记录一条调试日志，需要先初始化
func Debugln(args ...interface{}) {
	logging.Debugln(args...)
}

type Logger struct {
	level         int // debug 0 info 3 err 5
	innerLogger   *log.Logger
	curFile       *os.File
	today         string
	filename      string
	runtimeCaller int
	logFilePath   bool
	logFunc       bool
	msgQueue      chan string // 所有的日志先到这来
	closed        bool
}

// New 创建一个自己的日志对象。
// dir: 日录文件目录
// filename: 在logs文件夹下创建的文件名
// logFilePath: 日志中记录文件路径
// logFunc: 日志中记录调用函数
// level: 打印等级。DEBUG, INFO, ERROR
// runtimeCaller: 文件路径深度，设定适当的值，否则文件路径不正确
func New(dir, filename string, logFilePath bool,
	logFunc bool, level int, runtimeCaller int) *Logger {

	result := new(Logger)
	result.msgQueue = make(chan string, 1000)
	result.closed = false

	var multi io.Writer

	if filename != "" {
		logFile, err := os.OpenFile(dir+"/"+filename,
			os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0666)
		if err != nil {
			fmt.Println(err.Error())
		}
		result.curFile = logFile

		multi = io.MultiWriter(logFile, os.Stdout)
	} else {
		result.curFile = nil

		multi = os.Stdout
	}

	result.innerLogger = log.New(multi, "", 0)

	result.filename = filename

	result.runtimeCaller = runtimeCaller
	result.logFilePath = logFilePath
	result.logFunc = logFunc
	result.level = level
	result.today = time.Now().Format("20060102")

	// 启动日志切换
	go result.logWorker()

	return result
}

// Close 关闭这一个日志对象
func (logObj *Logger) Close() error {
	logObj.closed = true
	return nil
}

func (logObj *Logger) getFormat(prefix, format string) string {
	var buf bytes.Buffer

	// 增加时间
	buf.WriteString(time.Now().Format("2006/01/02 15:04:05 "))

	buf.WriteString(prefix)

	// 增加文件和行号
	funcName, file, line, ok := runtime.Caller(logObj.runtimeCaller)
	if ok {
		if logObj.logFilePath {
			buf.WriteString(filepath.Base(file))
			buf.WriteString(":")
			buf.WriteString(strconv.Itoa(line))
			buf.WriteString(" ")
		}
		if logObj.logFunc {
			buf.WriteString(runtime.FuncForPC(funcName).Name())
			buf.WriteString(" ")
		}
		buf.WriteString(format)
		format = buf.String()
	}
	return format
}

// Error 记录一条错误日志
func (logObj *Logger) Error(format string, v ...interface{}) {
	if logging.level > 5 {
		return
	}

	format = logObj.getFormat("ERROR ", format)
	logObj.msgQueue <- fmt.Sprintf(format, v...)
}

// Errorln 打印一行错误日志
func (logObj *Logger) Errorln(args ...interface{}) {
	if logging.level > 5 {
		return
	}

	prefix := logObj.getFormat("ERROR ", "")
	logObj.msgQueue <- fmt.Sprintln(append([]interface{}{prefix}, args...)...)
}

// Info 记录一条消息日志
func (logObj *Logger) Info(format string, v ...interface{}) {
	if logging.level > 3 {
		return
	}

	format = logObj.getFormat("INFO ", format)
	logObj.msgQueue <- fmt.Sprintf(format, v...)
}

// Infoln 打印一行消息日志
func (logObj *Logger) Infoln(args ...interface{}) {
	if logging.level > 3 {
		return
	}

	prefix := logObj.getFormat("INFO ", "")
	logObj.msgQueue <- fmt.Sprintln(append([]interface{}{prefix}, args...)...)
}

// Debug 记录一条消息日志
func (logObj *Logger) Debug(format string, v ...interface{}) {
	if logging.level > 0 {
		return
	}

	format = logObj.getFormat("DEBUG ", format)
	logObj.msgQueue <- fmt.Sprintf(format, v...)
}

// Debugln 打印一行调试日志
func (logObj *Logger) Debugln(args ...interface{}) {
	if logging.level > 0 {
		return
	}

	prefix := logObj.getFormat("DEBUG ", "")
	logObj.msgQueue <- fmt.Sprintln(append([]interface{}{prefix}, args...)...)
}

func (logObj *Logger) logWorker() {
	// 计算下一个执行任务的时间
	nextRotate := calculateNextRotateTime()

	// 创建定时器，每隔一段时间触发一次任务
	ticker := time.NewTicker(time.Hour)

	for !logObj.closed {
		select {
		case msg := <-logObj.msgQueue:
			logObj.innerLogger.Println(msg)
		case <-ticker.C:
			// 每次定时器触发时，也检查是否到达下一个执行任务的时间
			now := time.Now()
			if now.After(nextRotate) {
				logObj.Debug("doRotate run %v", now.Format("20060102"))
				logObj.doRotate()

				// 更新下一个执行任务的时间
				nextRotate = calculateNextRotateTime()
			}
		}
	}
}

func calculateNextRotateTime() time.Time {
	// 获取当前时间
	now := time.Now()

	// 计算下一个执行任务的时间，每天的凌晨0点
	nextRotate := time.Date(now.Year(), now.Month(), now.Day()+1, 0, 0, 0, 0, now.Location())

	return nextRotate
}

func (logObj *Logger) doRotate() {
	// 日志按天切换文件，日志对象记录了程序启动时的时间，当当前时间和程序启动的时间不一致
	// 则会启动到这个函数来改变文件
	// 首先关闭文件句柄，把当前日志改名为昨天，再创建新的文件句柄，将这个文件句柄赋值给log对象
	fmt.Println("doRotate run")

	defer func() {
		rec := recover()
		if rec != nil {
			fmt.Printf("doRotate %v", rec)
		}
	}()

	if logObj.curFile == nil {
		fmt.Println("doRotate curfile nil, return")
		return
	}
	//logObj.curFile
	dir, _ := filepath.Abs(filepath.Dir(logObj.curFile.Name()))
	prefile := logObj.curFile

	_, err := prefile.Stat()
	if err == nil {
		filePath := dir + "/" + logObj.filename

		err := prefile.Close()
		fmt.Printf("doRotate close err %v\n", err)
		nowTime := time.Now()
		time1dAgo := nowTime.Add(-1 * time.Hour * 24)
		err = os.Rename(filePath, filePath+"."+time1dAgo.Format("20060102"))
		fmt.Printf("doRotate rename err %v\n", err)
	}

	if logObj.filename != "" {
		nextfile, err := os.OpenFile(dir+"/"+logObj.filename,
			os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0666)
		if err != nil {
			fmt.Println(err.Error())
		}
		logObj.curFile = nextfile

		fmt.Println("newLogger use MultiWriter")
		multi := io.MultiWriter(nextfile, os.Stdout)
		logObj.innerLogger.SetOutput(multi)
	}

	fmt.Println("doRotate ending")

	// 更新标记，这个标记决定是否会启动文件切换
	nowDate := time.Now().Format("2006/01/02")
	logObj.today = nowDate
}

func DeleteHistoryLog() {
	// 删除15天前的日志
	nowTime := time.Now()
	timeAgo := nowTime.Add(-1 * time.Hour * 24 * 15)

	dir, _ := filepath.Abs(filepath.Dir("/var/log/sophliteos/"))
	// 获取目录下所有文件
	files, err := filepath.Glob(filepath.Join(dir, "sophliteos.log.*"))
	if err != nil {
		fmt.Printf("无法获取文件列表: %v\n", err)
		return
	}

	// 遍历文件，删除小于指定日期的文件
	for _, file := range files {
		// 解析文件名中的日期部分
		fileName := filepath.Base(file)
		dateStr := fileName[len("sophliteos.log."):]
		fileDate, err := time.Parse("20060102", dateStr)
		if err != nil {
			fmt.Printf("无法解析文件日期: %v\n", err)
			continue
		}

		// 删除日期小于指定日期文件
		if fileDate.Before(timeAgo) {
			fmt.Printf("删除文件: %s\n", fileName)
			if err := os.Remove(file); err != nil {
				fmt.Printf("无法删除文件 %s: %v\n", fileName, err)
			}
		}
	}
}
