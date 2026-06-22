package system

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"sophliteos/client/ssm"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	"sophliteos/mvc/i18n"
	services "sophliteos/mvc/services/opt"

	"github.com/gin-gonic/gin"
	"github.com/mitchellh/mapstructure"
)

type OtaApi struct{}

const (
	Ctrl = "ctrl"
	Core = "core"
)

var (
	ctrlFileName string
	coreFileName string
	ctrlFileMd5  string
	coreFileMd5  string
)

func init() {
	i18n.SetString(i18n.Zh, Ctrl, "控制板")
	i18n.SetString(i18n.En, Ctrl, "Ctrl")
	i18n.SetString(i18n.Zh, Core, "核心板")
	i18n.SetString(i18n.En, Core, "Core")
}

func (b *OtaApi) OtaFileChunked(c *gin.Context) {
	chunkIndex := c.Request.FormValue("chunkIndex") // 分片的索引
	totalChunks := c.Request.FormValue("totalChunks")
	ctrlFileName = c.Request.FormValue("fileName")
	md5Value := strings.ToLower(c.Request.FormValue("md5"))

	index, _ := strconv.Atoi(chunkIndex)
	total, _ := strconv.Atoi(totalChunks)

	if strings.Contains(ctrlFileName, "/") || strings.HasPrefix(ctrlFileName, ".") {
		logger.Error("file name error:%s", ctrlFileName)
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "file error"))
		return
	}

	// 创建存储分片的目录
	chunksDir := filepath.Join("/data/sophliteos", "upload")
	os.MkdirAll(chunksDir, os.ModePerm)

	file, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "file error"))
		return
	}
	// 分片文件的存储路径
	chunkFilePath := filepath.Join(chunksDir, ctrlFileName+"-"+chunkIndex)

	// 保存分片文件
	if err := c.SaveUploadedFile(file, chunkFilePath); err != nil {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "SaveUploadedFile error"))
		return
	}

	if total == index+1 {
		ctrlFileMd5, err = MergeChunked(total, md5Value)
		if err != nil {
			c.JSON(http.StatusOK, mvc.Fail(-1, "文件上传失败"))
			return
		}
		services.SaveOptLog(c.Request, "升级包上传")
		c.JSON(http.StatusOK, mvc.Success(ctrlFileMd5))
	} else {
		c.JSON(http.StatusOK, mvc.Ok())
	}

}

func MergeChunked(total int, md5Value string) (string, error) {

	err := os.RemoveAll("/data/ota")
	if err != nil {
		logger.Error("rm failed %v", err)
	}

	// 最终文件的路径
	finalFilePath := filepath.Join("/data/ota/", ctrlFileName)
	os.MkdirAll(filepath.Dir(finalFilePath), os.ModePerm)

	// 创建最终文件
	finalFile, err := os.Create(finalFilePath)
	if err != nil {
		logger.Error("创建最终文件失败： %v", err)
		return "", err
	}
	defer finalFile.Close()

	// 合并所有分片
	for i := 0; i < total; i++ {
		chunkFilePath := filepath.Join("/data/sophliteos/upload", ctrlFileName) + "-" + strconv.Itoa(i)
		chunkFile, err := os.Open(chunkFilePath)
		if err != nil {
			logger.Error("合并分片失败： %v", err)
			return "", err
		}

		// 将分片内容写入最终文件
		if _, err := io.Copy(finalFile, chunkFile); err != nil {
			chunkFile.Close()
			logger.Error("分片内容写入最终文件失败： %v", err)
			return "", err
		}
		chunkFile.Close()

		// 删除已经合并的分片文件
		os.Remove(chunkFilePath)
	}

	md5String, err := calculateFileMD5("/data/ota/" + ctrlFileName)
	if err != nil {
		logger.Error("md5计算失败： %v", err)
		return "", err
	}
	if md5String == md5Value {
		return md5String, nil
	} else {
		logger.Error("md5值不一致")
		return "", errors.New("md5 error")
	}

}

func (b *OtaApi) OtaFile(c *gin.Context) {
	// 参数判断
	md5Value := strings.ToLower(c.Request.FormValue("md5"))
	module := c.Request.FormValue("module")
	if module != Ctrl && module != Core {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "param error"))
		return
	}

	err := os.RemoveAll("/data/ota")
	if err != nil {
		logger.Error("rm failed %v", err)
	}

	var otaFile string
	switch module {
	case Ctrl:
		otaFile, err = saveFile(c.Request, "/data/ota/")
		// otaFile, err = saveFile(c.Request, "/data/ota/")
		if err != nil {
			logger.Error("update failed %v", err)
			c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "文件上传失败"))
			return
		}
		ctrlFileName = otaFile
	case Core:
		otaFile, err = saveFile(c.Request, "/data/ota/")
		if err != nil {
			logger.Error("update failed %v", err)
			c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "文件上传失败"))
			return
		}
		coreFileName = otaFile
	}

	md5String, err := calculateFileMD5("/data/ota/" + otaFile)
	if err != nil {
		c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "文件上传失败"))
		return
	}

	logger.Info("文件名:%s", otaFile)
	logger.Info("初始文件MD5值:%s", md5Value)
	logger.Info("接受文件MD5值:%s", md5String)

	if md5String != md5Value {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "文件上传失败:MD5值不一致"))
		coreFileName = ""
		ctrlFileName = ""
		return
	}
	switch module {
	case Core:
		coreFileMd5 = md5String
	case Ctrl:
		ctrlFileMd5 = md5String
	}
	services.SaveOptLog(c.Request, "升级包上传")

	c.JSON(http.StatusOK, mvc.Success(md5String))

}

func (b *OtaApi) OtaFileList(c *gin.Context) {
	fileInfo := getFileName()
	c.JSON(http.StatusOK, mvc.Success(fileInfo))

}

func (b *OtaApi) OtaUpgrate(c *gin.Context) {

	// 参数判断
	module := c.Request.FormValue("module")
	if module != Ctrl && module != Core {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "param error"))
		return
	}

	getFileName()

	var otaName string
	switch module {
	case Ctrl:
		otaName = ctrlFileName
		if !strings.Contains(otaName, "sdcard") {
			logger.Error("文件错误")
			c.JSON(http.StatusOK,  mvc.Fail(error2.UpgradeParamErr, "升级文件上传错误，请上传名称为sdcard.tgz的卡刷包"))
			return
		}

	case Core:
		otaName = coreFileName
		if !strings.Contains(otaName, "tftp") {
			logger.Error("文件错误")
			c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "升级文件上传错误，请上传名称为tftp.tgz的卡刷包"))
			return
		}
	}

	cmdFlag := "--target="
	ip := c.Request.FormValue("ip")
	if len(ip) > 0 {
		cmdFlag = cmdFlag + ip
	} else {
		cmdFlag = cmdFlag + "all"
	}

	if module == Ctrl {
		cmdFlag = "/data/ota/local_update.sh md5.txt 1"
	}

	if global.DeviceType == "" {
		ctrlBasic, _, err := ssm.GetCtrlBasic()
		if err == nil {
			global.DeviceType = GetDeviceType(ctrlBasic.Configure.Basic.DeviceType)
		}

		if global.DeviceType == "" {
			logger.Error("设备类型获取异常")
			c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "设备类型获取异常"))
			return
		}		
	}

	otaInfo := ssm.OtaVersion{
		Name:       strings.ToLower(global.DeviceType) + "_" + module + "_upgrade_" + time.Now().Format("20060102150405"),
		Product:    strings.ToUpper(global.DeviceType),
		FileName:   otaName,
		ModuleName: module,
		CmdFlag:    cmdFlag,
	}
	logger.Info("OTA info is :%v", otaInfo)

	_, err := ssm.OtaUpgrade(otaInfo)
	if err != nil {
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级失败"))
		return
	}

	services.SaveOptLog(c.Request, "%sOTA升级", i18n.GetString(mvc.GetLang(c.Request), module))

	c.JSON(http.StatusOK, mvc.OkWithMsg("系统开始升级，预计需要5分钟"))
}

func (b *OtaApi) OtaUpgradeList(c *gin.Context) {

	result, err := ssm.OtaUpgradeList()
	mvc.HandleError(err)
	var otaTasks []ssm.OtaTask
	res, _ := json.Marshal(result.Result)
	_ = json.Unmarshal(res, &otaTasks)
	c.JSON(http.StatusOK, mvc.Success(otaTasks))

}

func (b *OtaApi) OtaRollback(c *gin.Context) {

	var task ssm.OtaTask
	data, _ := io.ReadAll(c.Request.Body)
	mapstructure.Decode(task, data)
	result, err := ssm.OtaUpgradeList()
	mvc.HandleError(err)
	var tasks []ssm.OtaTask
	mapstructure.Decode(tasks, result.Result)
	var version ssm.OtaVersion
	for _, t := range tasks {
		if t.WorkflowID == task.WorkflowID {
			version.Name = t.Name
			version.CmdFlag = t.CmdFlag
			version.FileName = t.FileName
			version.ModuleName = t.ModuleName
			version.Product = t.Product
			break
		}
	}
	if len(version.Name) <= 0 {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeTaskNotFound, "Upgrade Task Not Found"))
		return
	}
	result, err = ssm.OtaRollback(version)
	mvc.HandleError(err, error2.RollbackErr)
	services.SaveOptLog(c.Request, "OTA回滚")
	c.JSON(http.StatusOK, mvc.OkWithMsg("请求成功"))
}

// 文件上传控制
func handleFile(request *http.Request, module string) string {
	file, handler, err := request.FormFile("file")
	if err != nil {
		if module == Ctrl {
			panic(err)
		} else {
			return ""
		}
	}
	defer file.Close()

	dir := "/data/ota/"
	if module == Core {
		dir = "/recovery/tftp/"
	}

	f, err := os.OpenFile(dir+handler.Filename, os.O_WRONLY|os.O_CREATE, 0777)
	if err != nil {
		panic(err)
	}
	_, err = io.Copy(f, file)
	if err != nil {
		panic(err)
	}
	defer func() {
		_ = f.Close()
		_ = os.Remove(handler.Filename)
		_ = request.MultipartForm.RemoveAll()
	}()
	return handler.Filename
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

func getFileName() OtaFileInfo {
	var fileInfo OtaFileInfo
	if ctrlFileName != "" {
		fileInfo.CtrlName = ctrlFileName
		fileInfo.CtrlMd5 = ctrlFileMd5
	} else {
		// if _, err := os.Stat("/data/ota/sdcard.tgz"); !os.IsNotExist(err) {
		// 	fileInfo.CtrlName = "sdcard.tgz"
		// 	fileInfo.CtrlMd5, _ = calculateFileMD5("/data/ota/sdcard.tgz")
		// 	ctrlFileName = "sdcard.tgz"
		// 	ctrlFileMd5 = fileInfo.CtrlMd5
		// }
	}
	if coreFileName != "" {
		fileInfo.CoreName = coreFileName
		fileInfo.CoreMd5 = coreFileMd5
	} else {
		// if _, err := os.Stat("/data/ota/tftp.tgz"); !os.IsNotExist(err) {
		// 	fileInfo.CoreName = "tftp.tgz"
		// 	fileInfo.CoreMd5, _ = calculateFileMD5("/data/ota/tftp.tgz")
		// 	coreFileName = "tftp.tgz"
		// 	coreFileMd5 = fileInfo.CoreMd5
		// }
	}
	return fileInfo
}
