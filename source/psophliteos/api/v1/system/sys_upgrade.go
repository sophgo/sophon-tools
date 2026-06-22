package system

import (
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	"sophliteos/mvc/i18n"
	services "sophliteos/mvc/services/opt"
	"strings"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
)

type UpgradeApi struct{}

var filename string

func init() {
	i18n.SetString(i18n.Zh, "upgrade", "sophliteos 升级")
	i18n.SetString(i18n.En, "upgrade", "sophliteos upgrade")
}

func (b *UpgradeApi) Upgrade(c *gin.Context) {
	var err error

	filename, err = saveFile(c.Request, "/data/sophliteos/")
	if err != nil {
		logger.Error("update failed", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "操作失败"))
		return
	}

	if filename != "sophliteos-linux_arm64.tgz" {
		logger.Error("升级包上传错误")
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级包上传错误"))
		return
	}

	err = upgradeLiteOs()
	if err != nil {
		logger.Error("upgrade failed", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "操作失败"))
		return
	}
	global.BlockAllRequests = true
	services.SaveOptLog(c.Request, i18n.GetString(mvc.GetLang(c.Request), "upgrade"))

	// 重新执行更新后的程序
	go restartUpgradedProgram()
	c.JSON(http.StatusOK, mvc.OkWithMsg("升级成功，LiteOS正在重启，请一分钟后刷新页面重新进入"))
}

func upgradeLiteOs() error {

	/* 	cmd := exec.Command("tar", "-xzf", filename, "-C", "/data/sophliteos/")
	   	cmd.Dir = "/data/sophliteos"

	   	// 执行命令
	   	err := cmd.Run()
	   	if err != nil {
	   		logger.Error("tar failed", err)
	   	}

	   	script := "/data/sophliteos/upgrade.sh"
	   	// 检查脚本文件是否存在
	   	_, err = os.Stat(script)
	   	if err != nil {
	   		logger.Error("Script file not found:", err)
	   		return err
	   	}
	   	cmd = exec.Command("sudo", "/bin/bash", script)
	   	cmd.Dir = "/data/sophliteos"
	   	err = cmd.Run()
	   	if err != nil {
	   		logger.Error("script failed", err)
	   		return err
	   	}
	   	// 读取升级文件
	   	updatePath := "/data/sophliteos/sophliteos"
	   	updateFile, err := os.Open(updatePath)
	   	cmdPath := os.Args[0]
	   	if err != nil {
	   		return err
	   	}
	   	defer updateFile.Close()

	   	// 执行自更新操作
	   	err = update.Apply(updateFile, update.Options{
	   		TargetPath: cmdPath,
	   	})
	   	if err != nil {
	   		if rollbackErr := update.RollbackError(err); rollbackErr != nil {
	   			logger.Error("Failed to rollback from bad update: %v", rollbackErr)
	   		}
	   		return err
	   	}

	   	logger.Info("sophliteos self upgrade successful!") */
	return nil
}

func restartUpgradedProgram() {
	time.Sleep(5 * time.Second)
	// 启动新进程
	if err := syscall.Exec(os.Args[0], os.Args, os.Environ()); err != nil {
		logger.Error("Failed to restart: %v", err)
	}

	cmd := exec.Command("rm", "-f", filename)
	cmd.Dir = "/data/sophliteos"

	// 执行命令
	err := cmd.Run()
	if err != nil {
		logger.Error("tar rm failed", err)
	}

	// 退出当前进程
	os.Exit(0)
}

// 文件上传控制
func saveFile(request *http.Request, dir string) (string, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		logger.Error("Failed to create directory", err)
		return "", err
	}
	os.Chmod(dir, 0755)

	file, handler, err := request.FormFile("file")
	if err != nil {
		return "", err
	}
	defer file.Close()

	if strings.Contains(handler.Filename, "/") || strings.HasPrefix(handler.Filename, ".") {
		logger.Error("file name error:%s", handler.Filename)
		return "", errors.New("file name error")
	}

	f, err := os.OpenFile(dir+handler.Filename, os.O_WRONLY|os.O_CREATE, 0777)
	if err != nil {
		return "", err
	}
	_, err = io.Copy(f, file)
	if err != nil {
		return "", err
	}
	defer func() {
		_ = f.Close()
		_ = os.Remove(handler.Filename)
		_ = request.MultipartForm.RemoveAll()
	}()
	return handler.Filename, err
}
