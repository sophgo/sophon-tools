package system

import (
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	"sophliteos/mvc/i18n"
	services "sophliteos/mvc/services/opt"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
)

type UpgradeApi struct{}

func init() {
	i18n.SetString(i18n.Zh, "upgrade", "sophliteos 升级")
	i18n.SetString(i18n.En, "upgrade", "sophliteos upgrade")
}

// 升级采用两段式流程（上传暂存 → 确认执行），并做并发互斥：
//   - pendingUpgrade/pendingFileName：升级包先暂存，由用户再次确认后才真正执行升级/重启，
//     持令牌一次请求无法直接触发"上传+重启"；
//   - upgradeInFlight：升级/重启进行中，拒绝并发的上传/确认，避免双浏览器/重复请求误触，
//     保证升级只执行一次（幂等）。
//
// 上述状态均受 upgradeMu 保护；与 OTA 上传（otaMu）相互独立。
var (
	upgradeMu       sync.Mutex
	pendingUpgrade  bool   // 已暂存待确认的升级包
	pendingFileName string // 暂存的升级包文件名
	upgradeInFlight bool   // 升级/重启进行中
)

// 重启流程的注入点：生产环境 sleep 5 秒后以 syscall.Exec 替换进程映像；
// 测试中注入短延迟/安全函数，避免真实 sleep 与进程替换。
var (
	restartDelay = 5 * time.Second
	execSelf     = func() error { return syscall.Exec(os.Args[0], os.Args, os.Environ()) }
)

// Upgrade 升级流程第一步：上传并暂存升级包（不执行升级）。
// 幂等：重复上传会覆盖暂存包；升级进行中时拒绝上传。
func (b *UpgradeApi) Upgrade(c *gin.Context) {
	upgradeMu.Lock()
	defer upgradeMu.Unlock()

	if upgradeInFlight {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级正在进行中，请等待升级完成后重试"))
		return
	}

	// filename 保存为局部变量：全局变量在并发请求下会被覆盖，导致校验/清理错乱。
	savedName, err := saveFile(c.Request, "/data/sophliteos/")
	if err != nil {
		logger.Error("update failed", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "操作失败"))
		return
	}

	if savedName != "sophliteos-linux_arm64.tgz" {
		logger.Error("升级包上传错误")
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级包上传错误"))
		return
	}

	pendingUpgrade = true
	pendingFileName = savedName
	services.SaveOptLog(c.Request, "升级包上传")
	c.JSON(http.StatusOK, mvc.OkWithMsg("升级包已暂存，请点击「确认升级」执行升级"))
}

// UpgradeConfirm 升级流程第二步：确认执行已暂存的升级包。
// 无暂存包或升级进行中时返回明确错误，避免误操作。
func (b *UpgradeApi) UpgradeConfirm(c *gin.Context) {
	upgradeMu.Lock()
	defer upgradeMu.Unlock()

	if upgradeInFlight {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级正在进行中，请等待升级完成后重试"))
		return
	}
	if !pendingUpgrade {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "没有待升级的升级包，请先上传升级包"))
		return
	}

	// 先复位暂存并置为进行中：后续并发请求（上传/确认）都会被拒绝，升级只会执行一次。
	name := pendingFileName
	pendingUpgrade = false
	upgradeInFlight = true

	err := upgradeLiteOs()
	if err != nil {
		upgradeInFlight = false
		logger.Error("upgrade failed", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "操作失败"))
		return
	}
	global.BlockAllRequests = true
	services.SaveOptLog(c.Request, i18n.GetString(mvc.GetLang(c.Request), "upgrade"))

	// 重新执行更新后的程序；Exec 失败时会回滚 BlockAllRequests（见 restartUpgradedProgram）
	go restartUpgradedProgram(name)
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

func restartUpgradedProgram(savedName string) {
	time.Sleep(restartDelay)
	// 启动新进程；Exec 成功时进程映像即被新程序替换，此后的代码不再执行。
	if err := execSelf(); err != nil {
		// Exec 失败（二进制被替换/删除、无权限等）：进程并未重启。必须回滚阻塞标记，
		// 否则整个平台将一直 503；同时记录告警日志，并复位 in-flight 允许重新升级。
		logger.Error("升级重启失败: %v，回滚 BlockAllRequests，平台继续提供服务", err)
		upgradeMu.Lock()
		global.BlockAllRequests = false
		upgradeInFlight = false
		upgradeMu.Unlock()
	}

	// 清理上传的升级包（Exec 成功时进程已替换，此段不可达）
	removeUpgradePackage(savedName)
}

// removeUpgradePackage 删除暂存的升级包；用完整路径清理，避免相对路径（进程 CWD）删错文件。
func removeUpgradePackage(savedName string) {
	if savedName == "" {
		return
	}
	cmd := exec.Command("rm", "-f", filepath.Join("/data/sophliteos", savedName))
	cmd.Dir = "/data/sophliteos"

	// 执行命令
	if err := cmd.Run(); err != nil {
		logger.Error("tar rm failed", err)
	}
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

	// 保存路径用绝对路径；清理时删除同一路径，避免相对路径（进程 CWD）删错文件。
	dstPath := dir + handler.Filename
	f, err := os.OpenFile(dstPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
	if err != nil {
		return "", err
	}
	_, err = io.Copy(f, file)
	if err != nil {
		_ = f.Close()
		// 写入失败：清理半成品文件后返回
		_ = os.Remove(dstPath)
		return "", err
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(dstPath)
		return "", err
	}

	// 注意：上传文件保留在磁盘（升级暂存/OtaFile 后续 MD5 校验都需要），
	// 由调用方负责清理；不再在返回时无条件删除。
	_ = request.MultipartForm.RemoveAll()
	return handler.Filename, nil
}
