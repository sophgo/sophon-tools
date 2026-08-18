package system

import (
	"crypto/md5"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	services "sophliteos/mvc/services/opt"

	"github.com/gin-gonic/gin"
)

type OtaApi struct{}

const (
	Ctrl = "ctrl"
	Core = "core"

	// maxOtaFileNameLen 升级包文件名字节数上限（限制会话状态/目录项长度）。
	maxOtaFileNameLen = 128
	md5HexLen         = 32 // md5 参数长度（小写十六进制）
)

// OTA 上传限额（MYS-380 加固）。以可变量维护便于测试覆盖，生产取值依据：
// 前端按 50MiB 分片，单片上限 64MiB 兼容前端并留余量；整包上限 4GiB 覆盖
// 当前（≤2GiB）及未来固件包。配合会话机制，任何时刻 /data/sophliteos/upload
// 最多积累一个会话的分片（≤4GiB），恶意请求无法借助分片上传耗尽磁盘。
var (
	maxChunkSize    int64 = 64 << 20 // 单片大小上限：64MiB
	maxTotalChunks        = 128      // 分片数量上限（4GiB/64MiB=64 片仍留 2 倍余量）
	maxOtaTotalSize int64 = 4 << 30  // 会话累计总量上限：4GiB
)

// otaMu 串行化 OTA 上传/合并流程：全局状态（已上传文件名/会话）非并发安全，
// 并发上传（ctrl/core 同时或双浏览器）会互相覆盖导致分片串扰。
var otaMu sync.Mutex

// 已上传成功的升级包状态（"已上传"= 合并校验通过、磁盘真实存在）。
// 仅在校验通过后置位；失败路径清空，保证 OtaFileList 与磁盘一致。
var (
	ctrlFileName string
	coreFileName string
	ctrlFileMd5  string
	coreFileMd5  string
)

// 分片上传会话状态（otaMu 串行保护）。会话与"已上传"状态分离：
// 会话期间 OtaFileList 不展示任何文件；全部校验通过后才写 ctrlFileName 等。
var (
	sessFileName    string // 会话文件名（upload/<name>-<i> 分片前缀）
	sessFileMd5     string // 期望合并 MD5（32 位小写十六进制）
	sessTotalChunks int    // 声明总片数（1..maxTotalChunks）
	sessTotalSize   int64  // 会话已落盘分片累计字节
)

// 分片目录/合并目录（变量便于测试注入临时目录；生产为 /data 下固定路径）。
var (
	otaUploadDir = "/data/sophliteos/upload"
	otaFinalDir  = "/data/ota"
)

func (b *OtaApi) OtaFileChunked(c *gin.Context) {
	// 串行化分片上传（防并发上传覆盖全局文件名/分片交叉）
	otaMu.Lock()
	defer otaMu.Unlock()

	// 限制请求体大小（file 分片 + 表单字段）：必须在首次解析 multipart 之前安装，
	// 过大的分片在解析阶段即被拒绝，避免恶意分片先落盘再被检查。
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxChunkSize+(1<<20))

	chunkIndex := c.Request.FormValue("chunkIndex") // 分片的索引
	totalChunks := c.Request.FormValue("totalChunks")
	fileName := c.Request.FormValue("fileName")
	md5Value := strings.ToLower(c.Request.FormValue("md5"))

	index, total, ok := parseChunkParams(chunkIndex, totalChunks)
	if !ok || !validUploadFileName(fileName) || !validMd5Hex(md5Value) {
		// 非法分片参数：拒绝并终止当前会话（可能正被恶意探测/攻击），清理已落盘残留
		logger.Error("ota chunk invalid params: index=%q total=%q name=%q md5=%q", chunkIndex, totalChunks, fileName, md5Value)
		rejectChunk(c, http.StatusBadRequest, "分片参数错误")
		return
	}

	file, err := c.FormFile("file")
	if err != nil {
		logger.Error("ota chunk form file error: %v", err)
		rejectChunk(c, http.StatusBadRequest, "file error")
		return
	}
	if file.Size > maxChunkSize {
		logger.Error("ota chunk too large: name=%s size=%d", fileName, file.Size)
		rejectChunk(c, http.StatusBadRequest, "分片大小超限")
		return
	}

	// 会话一致性：无会话则开新会话（先清理上一会话残留）；
	// 会话进行中参数不一致视为新上传抢占，终止旧会话并清理其残留分片。
	if sessFileName == "" {
		cleanupUploadDir()
		sessFileName = fileName
		sessFileMd5 = md5Value
		sessTotalChunks = total
		sessTotalSize = 0
	} else if !sessionMatches(fileName, md5Value, total) {
		logger.Error("ota chunk session mismatch: %s/%s/%d -> %s/%s/%d",
			sessFileName, sessFileMd5, sessTotalChunks, fileName, md5Value, total)
		rejectChunk(c, http.StatusBadRequest, "分片参数错误")
		return
	}

	// 会话累计总量上限（防分片合法但大量填充磁盘）。
	// 重放/覆盖分片（同序号重新上传）先扣掉被覆盖分片的旧字节再判定，
	// 会话总量始终等于实际落盘字节，重试/重放不会导致配额虚增。
	chunkFilePath := filepath.Join(otaUploadDir, fileName+"-"+strconv.Itoa(index))
	replaySize := int64(0)
	if fi, err := os.Stat(chunkFilePath); err == nil {
		replaySize = fi.Size()
	}
	if sessTotalSize-replaySize+file.Size > maxOtaTotalSize {
		logger.Error("ota upload total size over limit: name=%s total=%d", fileName, sessTotalSize-replaySize+file.Size)
		rejectChunk(c, http.StatusBadRequest, "升级包总量超限")
		return
	}

	// 保存分片（覆盖式，客户端重试同参数分片安全）
	if err := os.MkdirAll(otaUploadDir, os.ModePerm); err != nil {
		logger.Error("MkdirAll upload dir failed: %v", err)
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "SaveUploadedFile error"))
		return
	}
	if err := c.SaveUploadedFile(file, chunkFilePath); err != nil {
		// 磁盘/传输错误：保留会话状态，客户端重试即可
		logger.Error("SaveUploadedFile error: %v", err)
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "SaveUploadedFile error"))
		return
	}
	sessTotalSize += file.Size - replaySize

	if index == total-1 {
		mergedMd5, err := mergeChunked(fileName, md5Value, total)
		if err != nil {
			logger.Error("merge chunked failed: %v", err)
			// 合并失败：清理会话残留分片与状态；/data/ota 未被触碰（见 mergeChunked）。
			// 返回 4xx（前端把 4xx 视为上传失败；200+失败码会被前端误判为成功）。
			endSession()
			c.JSON(http.StatusBadRequest, mvc.Fail(-1, "文件上传失败"))
			return
		}
		// 合并并校验成功：置"已上传"状态，收尾会话
		removeSessionChunks(fileName) // 清理 index >= total 的异常分片
		resetSession()
		ctrlFileName = fileName
		ctrlFileMd5 = mergedMd5
		if mvc.Token(c.Request) != "" { // 无登录态不记操作日志（也避免测试环境依赖 DB）
			services.SaveOptLog(c.Request, "升级包上传")
		}
		c.JSON(http.StatusOK, mvc.Success(ctrlFileMd5))
		return
	}

	c.JSON(http.StatusOK, mvc.Ok())
}

// rejectChunk 分片请求拒绝：终止当前会话（含已落盘残留）并返回 4xx。
func rejectChunk(c *gin.Context, status int, msg string) {
	if sessFileName != "" {
		endSession()
	}
	c.JSON(status, mvc.Fail(error2.UpgradeParamErr, msg))
}

// parseChunkParams 解析分片参数：索引与总数须为整数，索引 >= 0、总数 >= 1、
// 索引 < 总数且总数不超过 maxTotalChunks。
func parseChunkParams(chunkIndex, totalChunks string) (index, total int, ok bool) {
	index, err := strconv.Atoi(chunkIndex)
	total, errTotal := strconv.Atoi(totalChunks)
	if err != nil || errTotal != nil || index < 0 || total < 1 || index >= total || total > maxTotalChunks {
		return 0, 0, false
	}
	return index, total, true
}

// validUploadFileName 校验升级包文件名：仅接受无路径分隔（/ 与 \）、无前导点、
// 长度受限的普通文件名。
func validUploadFileName(name string) bool {
	if name == "" || strings.ContainsAny(name, "/\\") || strings.HasPrefix(name, ".") || len(name) > maxOtaFileNameLen {
		return false
	}
	return true
}

// validMd5Hex 校验 md5 参数为 32 位小写十六进制字符串。
func validMd5Hex(md5Value string) bool {
	if len(md5Value) != md5HexLen {
		return false
	}
	for _, r := range md5Value {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}

// sessionMatches 判断分片参数是否与当前会话一致。
func sessionMatches(fileName, md5Value string, total int) bool {
	return sessFileName == fileName && sessFileMd5 == md5Value && sessTotalChunks == total
}

// endSession 合并失败/参数非法时收尾：清理本会话已落盘分片并复位会话状态。
func endSession() {
	removeSessionChunks(sessFileName)
	resetSession()
}

func resetSession() {
	sessFileName = ""
	sessFileMd5 = ""
	sessTotalChunks = 0
	sessTotalSize = 0
}

// cleanupUploadDir 清空分片目录残留（仅普通文件）。仅在新会话开始时调用：
// 目录中只应存在上一会话的分片/合并临时文件，全部删除是安全的。
func cleanupUploadDir() error {
	entries, err := os.ReadDir(otaUploadDir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		os.Remove(filepath.Join(otaUploadDir, e.Name()))
	}
	return nil
}

// removeSessionChunks 删除会话名下所有分片（name-<序号>）与合并临时文件（name-merge.tmp）。
func removeSessionChunks(name string) {
	if name == "" {
		return
	}
	prefix := name + "-"
	entries, err := os.ReadDir(otaUploadDir)
	if os.IsNotExist(err) {
		return
	}
	if err != nil {
		logger.Error("removeSessionChunks read dir failed: %v", err)
		return
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if _, ok := chunkFileNameToIndex(name, e.Name()); ok || strings.HasPrefix(e.Name(), prefix) {
			os.Remove(filepath.Join(otaUploadDir, e.Name()))
		}
	}
}

// chunkFileNameToIndex 解析分片文件名（<name>-<非负整数>）；非本会话分片返回 ok=false。
// 限制数字后缀，避免清理时误删不属于本会话的条目。
func chunkFileNameToIndex(name, entry string) (index int, ok bool) {
	if !strings.HasPrefix(entry, name+"-") {
		return 0, false
	}
	index, err := strconv.Atoi(strings.TrimPrefix(entry, name+"-"))
	if err != nil || index < 0 {
		return 0, false
	}
	return index, true
}

// validateSessionChunks 合并前校验待合并分片的归属与完整性（MYS-380）：
// 0..total-1 分片必须全部存在且为普通文件，目录中不存在序号 >= total 的多余分片。
// （非数字后缀的条目不属于任何会话分片，忽略即可；合并只读精确数字名，md5 兜底内容。）
// 校验不通过时未触碰 /data/ota。
func validateSessionChunks(name string, total int) error {
	if total < 1 || total > maxTotalChunks {
		return errors.New("invalid total chunks")
	}
	entries, err := os.ReadDir(otaUploadDir)
	if err != nil {
		return err
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if idx, ok := chunkFileNameToIndex(name, e.Name()); ok && idx >= total {
			return errors.New("unexpected chunk: " + e.Name())
		}
	}
	for i := 0; i < total; i++ {
		p := filepath.Join(otaUploadDir, name+"-"+strconv.Itoa(i))
		fi, err := os.Stat(p)
		if err != nil {
			return errors.New("chunk " + strconv.Itoa(i) + " missing")
		}
		if !fi.Mode().IsRegular() {
			return errors.New("chunk " + strconv.Itoa(i) + " not a regular file")
		}
	}
	return nil
}

// mergeChunked 合并分片并校验 MD5。原子化流程（MYS-380）：
//  1. 先在分片目录内校验分片完整性（validateSessionChunks），此时不触碰 /data/ota；
//  2. 组装到分片目录内的临时文件并 fsync；
//  3. MD5 校验通过后，os.Rename 原子替换 /data/ota 下的旧同名包；
//  4. 任一步失败仅清临时文件/已合并分片，不删除 /data/ota 其余暂存包。
func mergeChunked(name, md5Value string, total int) (string, error) {
	os.MkdirAll(otaUploadDir, os.ModePerm)
	if err := validateSessionChunks(name, total); err != nil {
		return "", err
	}

	tmpPath := filepath.Join(otaUploadDir, name+"-merge.tmp")
	os.Remove(tmpPath)
	finalFile, err := os.Create(tmpPath)
	if err != nil {
		return "", err
	}
	cleanup := func() {
		finalFile.Close()
		os.Remove(tmpPath)
	}

	// 按序合并分片，已合并分片即删
	for i := 0; i < total; i++ {
		chunkFilePath := filepath.Join(otaUploadDir, name+"-"+strconv.Itoa(i))
		chunkFile, err := os.Open(chunkFilePath)
		if err != nil {
			cleanup()
			return "", err
		}
		_, err = io.Copy(finalFile, chunkFile)
		chunkFile.Close()
		os.Remove(chunkFilePath)
		if err != nil {
			cleanup()
			return "", err
		}
	}
	if err := finalFile.Sync(); err != nil {
		cleanup()
		return "", err
	}
	if err := finalFile.Close(); err != nil {
		os.Remove(tmpPath)
		return "", err
	}

	md5String, err := calculateFileMD5(tmpPath)
	if err != nil {
		os.Remove(tmpPath)
		return "", err
	}
	if md5String != md5Value {
		os.Remove(tmpPath)
		return "", errors.New("md5 error")
	}

	// 校验通过：此时才允许触碰 /data/ota —— os.Rename 原子同名替换，其他暂存包不动
	if err := os.MkdirAll(otaFinalDir, os.ModePerm); err != nil {
		os.Remove(tmpPath)
		return "", err
	}
	finalFilePath := filepath.Join(otaFinalDir, name)
	if err := os.Rename(tmpPath, finalFilePath); err != nil {
		os.Remove(tmpPath)
		return "", err
	}
	return md5String, nil
}

func (b *OtaApi) OtaFile(c *gin.Context) {
	// 串行化上传（防并发覆盖全局文件名）
	otaMu.Lock()
	defer otaMu.Unlock()

	// 整包上限与分片累计上限一致（4GiB），超限请求体在解析阶段即被拒绝
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxOtaTotalSize+(1<<20))

	// 参数判断
	md5Value := strings.ToLower(c.Request.FormValue("md5"))
	module := c.Request.FormValue("module")
	if module != Ctrl && module != Core {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "param error"))
		return
	}

	// 不再无条件清空 /data/ota（会误删另一模块已暂存的合法升级包）。
	// "已上传"状态仅在保存成功且校验通过后置位；失败路径不动既有状态与磁盘，
	// 保证 OtaFileList 与磁盘一致。
	otaFile, err := saveFile(c.Request, otaFinalDir+"/")
	if err != nil {
		logger.Error("update failed %v", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "文件上传失败"))
		return
	}

	md5String, err := calculateFileMD5(filepath.Join(otaFinalDir, otaFile))
	if err != nil {
		logger.Error("update failed %v", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "文件上传失败"))
		return
	}

	logger.Info("文件名:%s", otaFile)
	logger.Info("初始文件MD5值:%s", md5Value)
	logger.Info("接受文件MD5值:%s", md5String)

	if md5String != md5Value {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "文件上传失败:MD5值不一致"))
		return
	}
	switch module {
	case Core:
		coreFileName = otaFile
		coreFileMd5 = md5String
	case Ctrl:
		ctrlFileName = otaFile
		ctrlFileMd5 = md5String
	}
	if mvc.Token(c.Request) != "" { // 无登录态不记操作日志（也避免测试环境依赖 DB）
		services.SaveOptLog(c.Request, "升级包上传")
	}

	c.JSON(http.StatusOK, mvc.Success(md5String))

}

func (b *OtaApi) OtaFileList(c *gin.Context) {
	otaMu.Lock()
	defer otaMu.Unlock()
	fileInfo := getFileName()
	c.JSON(http.StatusOK, mvc.Success(fileInfo))

}

type OtaFileInfo struct {
	CtrlName string `json:"ctrlName"`
	CtrlMd5  string `json:"ctrlMd5"`
	CoreName string `json:"coreName"`
	CoreMd5  string `json:"coreMd5"`
}

func calculateFileMD5(filePath string) (string, error) {

	file, err := os.Open(filePath)
	if err != nil {
		logger.Error("无法打开文件: %v", err)
		return "", err
	}
	defer file.Close()

	hash := md5.New()
	if _, err := io.Copy(hash, file); err != nil {
		logger.Error("无法读取文件: %v", err)
		return "", err
	}

	hashInBytes := hash.Sum(nil)
	md5String := hex.EncodeToString(hashInBytes)

	return md5String, nil
}

// getFileName 组装已上传文件列表；仅展示磁盘真实存在的文件（宕机/旧残留兜底），
// 幽灵状态（状态在而文件不在）就地清掉，保证展示与磁盘一致。
func getFileName() OtaFileInfo {
	var fileInfo OtaFileInfo
	if ctrlFileName != "" {
		if _, err := os.Stat(filepath.Join(otaFinalDir, ctrlFileName)); err == nil {
			fileInfo.CtrlName = ctrlFileName
			fileInfo.CtrlMd5 = ctrlFileMd5
		} else {
			ctrlFileName = ""
			ctrlFileMd5 = ""
		}
	}
	if coreFileName != "" {
		if _, err := os.Stat(filepath.Join(otaFinalDir, coreFileName)); err == nil {
			fileInfo.CoreName = coreFileName
			fileInfo.CoreMd5 = coreFileMd5
		} else {
			coreFileName = ""
			coreFileMd5 = ""
		}
	}
	return fileInfo
}
