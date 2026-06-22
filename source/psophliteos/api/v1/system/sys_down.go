package system

import (
	"net/http"
	"os"
	"os/exec"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"

	"github.com/gin-gonic/gin"
)

type DownApi struct{}

func (b *DownApi) LogDown(c *gin.Context) {

	cmd := exec.Command("tar", "-czf", "log.tgz", "-C", "/var/log", "auth.log", "btmp", "dpkg.log", "kern.log", "syslog", "sophliteos", "ssm")
	cmd.Dir = "/data/"

	// 执行命令
	err := cmd.Run()
	if err != nil {
		logger.Error("tar file failed:%v", err)
	}

	// 文件路径
	filePath := "/data/log.tgz"

	if !fileExists(filePath) {
		logger.Error("tar failed")
		c.JSON(http.StatusInternalServerError, mvc.FailWithMsg(-1, "tar log failed"))
		return
	}

	// 打开文件
	file, err := os.Open(filePath)
	if err != nil {
		logger.Error("Failed to open file: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to open file"})
		return
	}
	defer file.Close()

	defer func() {
		err = os.Remove("/data/log.tgz")
		if err != nil {
			logger.Info("deleting directory:%v", err)
		}
	}()

	logger.Info("下载系统日志")
	// 设置响应头，指定文件名
	c.Header("Content-Disposition", "attachment; filename=log.tgz")

	// 发送文件
	c.FileAttachment(filePath, "log.tgz")

}

func fileExists(filename string) bool {
	_, err := os.Stat(filename)
	if os.IsNotExist(err) {
		return false
	}
	return true
}
