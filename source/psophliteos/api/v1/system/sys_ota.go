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
)

var (
	ctrlFileName string
	coreFileName string
	ctrlFileMd5  string
	coreFileMd5  string
)

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
	}
	if coreFileName != "" {
		fileInfo.CoreName = coreFileName
		fileInfo.CoreMd5 = coreFileMd5
	}
	return fileInfo
}
