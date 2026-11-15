package system

import (
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"

	"github.com/gin-gonic/gin"
)

// UpgradeApi 旧版 sophliteos 自升级接口。
//
// 该端点的自升级实现从未真正可用（下载→解包→自替换整段被注释掉，
// 历史上仍会返回成功、设置全局 503 阻塞并 exec 重启旧程序），且上传流程在校验文件名之前就
// 以 O_TRUNC 打开目标路径，任何持有有效会话的请求都能用任意普通文件名截断
// /data/sophliteos 下的文件（含二进制本体）。
//
// MYS-2882/MYS-2885 决策：本轮不新增自升级能力，也不恢复未经审计的脚本执行。
// 旧端点保留路由与鉴权（未登录仍 401），但明确返回"暂不支持"的非零业务码：
// 不上传、不落盘、不置 BlockAllRequests、不 exec 重启，前端既有的非零 code
// 错误展示会直接显示该提示，无需改视觉层。
type UpgradeApi struct{}

// legacyUpgradeUnsupportedMsg 旧升级接口统一提示：告诉用户正确的升级路径。
const legacyUpgradeUnsupportedMsg = "此升级方式暂不支持，请使用正式发布的软件包"

// rejectLegacyUpgrade 统一拒绝：HTTP 200 + 非零业务码（兼容前端 body.code 判定）。
// 不读取请求体、不解析 multipart —— 因此上传内容既不会落盘也不会进临时目录。
func rejectLegacyUpgrade(c *gin.Context) {
	// 明确丢弃请求体，避免客户端因未读 body 而阻塞在发送阶段（也避免连接复用问题）。
	_, _ = io.Copy(io.Discard, io.LimitReader(c.Request.Body, maxLegacyUpgradeDrain))
	c.JSON(http.StatusOK, mvc.FailWithMsg(error2.NotImplemented, legacyUpgradeUnsupportedMsg))
}

// maxLegacyUpgradeDrain 旧端点最多丢弃的请求体字节数（仅用于让客户端尽快结束发送，
// 超过部分由 net/http 关闭连接处理）。
const maxLegacyUpgradeDrain = 1 << 20

// Upgrade 旧升级流程第一步（上传暂存）：已下线，返回明确失败，无任何副作用。
func (b *UpgradeApi) Upgrade(c *gin.Context) {
	logger.Info("legacy /api/upgrade rejected: 旧升级接口已下线，请使用正式发布的软件包")
	rejectLegacyUpgrade(c)
}

// UpgradeConfirm 旧升级流程第二步（确认执行）：已下线，返回明确失败。
// 旧实现在此置 BlockAllRequests 并 exec 重启旧程序（假成功）；现不做任何状态变更。
func (b *UpgradeApi) UpgradeConfirm(c *gin.Context) {
	logger.Info("legacy /api/upgrade/confirm rejected: 旧升级接口已下线，请使用正式发布的软件包")
	rejectLegacyUpgrade(c)
}

// saveFile 保存 HTTP 上传的文件到 dir，返回保存后的文件名。
//
// 仅 OTA 上传（sys_ota.go）使用；旧自升级流程已下线，不再调用本函数。
// 契约（MYS-2885 加固）：
//   - 文件名先校验后打开：只接受单个普通文件名（不含路径分隔符、不以 '.' 开头、
//     长度有界），因此不可能借 ".." 或绝对路径写到 dir 之外；
//   - 写入失败/Close 失败都清理半成品文件并返回错误，不谎报成功；
//   - 无论成功与否都清理 multipart 临时文件（含校验失败路径，旧实现会泄漏）。
func saveFile(request *http.Request, dir string) (string, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		logger.Error("Failed to create directory: %v", err)
		return "", err
	}
	_ = os.Chmod(dir, 0o755)

	file, handler, err := request.FormFile("file")
	if err != nil {
		cleanupMultipart(request)
		return "", err
	}
	defer file.Close()
	// 上传内容可能已被缓冲到临时文件（大文件）：成功/失败都要清理。
	defer cleanupMultipart(request)

	name := handler.Filename
	if !validSaveFileName(name) {
		logger.Error("file name error: %q", name)
		return "", errors.New("file name error")
	}

	// 目标路径用显式拼接的绝对路径；name 已保证是单层文件名。
	dstPath := filepath.Join(dir, name)
	f, err := os.OpenFile(dstPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(f, file); err != nil {
		_ = f.Close()
		_ = os.Remove(dstPath) // 写入失败：清理半成品，不留下被截断的文件
		return "", err
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(dstPath)
		return "", err
	}
	return name, nil
}

// validSaveFileName 校验上传文件名是"单个普通文件名"：
// 拒绝路径分隔符、目录穿越、隐藏文件和超长名字（与 OTA 的分片文件名校验同口径）。
func validSaveFileName(name string) bool {
	if name == "" || name == "." || name == ".." {
		return false
	}
	if strings.ContainsAny(name, "/\\") || strings.HasPrefix(name, ".") {
		return false
	}
	if len(name) > maxOtaFileNameLen {
		return false
	}
	// 仅接受单层名字：filepath.Base 结果必须与原值一致（防御平台差异）。
	return filepath.Base(name) == name
}

// cleanupMultipart 清理 multipart 解析产生的临时文件（未解析时无操作）。
func cleanupMultipart(request *http.Request) {
	if request.MultipartForm != nil {
		_ = request.MultipartForm.RemoveAll()
	}
}
