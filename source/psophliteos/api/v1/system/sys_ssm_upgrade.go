package system

import (
	"encoding/base64"
	"net/http"
	"sophliteos/client/ssm"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	error2 "sophliteos/mvc/error"
	services "sophliteos/mvc/services/opt"
	"sophliteos/mvc/types"

	"github.com/gin-gonic/gin"
)

type SsmUpgradeApi struct{}

var ssmFileName string

func (b *SsmUpgradeApi) SsmList(c *gin.Context) {
	ctrlResource, err := ssm.GetCtrlResource()
	if err == nil {
		global.SSmLists.CtrlSsm.Version = "V" + ctrlResource.CentralProcessingUnit.BmssmVersion + "-" + ctrlResource.CentralProcessingUnit.BuildTime
	}

	var res []types.SsmVersion
	ctrl := global.SSmLists.CtrlSsm
	sv := types.SsmVersion{
		ChipIndex: -1,
		DeviceSn:  ctrl.DeviceSn,
		Ip:        ctrl.Ip,
		Version:   ctrl.Version,
	}
	res = append(res, sv)

	if global.DeviceType == "SE6" || global.DeviceType == "SE8" {
		res = append(res, global.SSmLists.CoreSsm...)
	}

	c.JSON(http.StatusOK, mvc.Success(res))
}

func (b *SsmUpgradeApi) Upgrade(c *gin.Context) {
	var err error
	var sns string
	var pwd, user []byte

	module := c.Request.FormValue("module")
	logger.Info("module:%s\n", module)
	if module != Ctrl && module != Core {
		c.JSON(http.StatusOK, mvc.Fail(error2.UpgradeParamErr, "param error"))
		return
	}

	ssmFileName, err = saveFile(c.Request, "/data/ssm/")
	if err != nil {
		logger.Error("save file failed:%v", err)
		c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "操作失败"))
		return
	}

	if ssmFileName != "bmssm-arm64-v1.2.0.tgz" {
		logger.Error("升级包上传错误")
		c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "升级包上传错误"))
		return
	}

	if module == Core {
		sns = c.Request.FormValue("sns")
		user, _ = base64.StdEncoding.DecodeString(c.Request.FormValue("user"))
		pwd, _ = base64.StdEncoding.DecodeString(c.Request.FormValue("pwd"))

		user, _ = base64.StdEncoding.DecodeString(string(user))
		pwd, _ = base64.StdEncoding.DecodeString(string(pwd))
	}

	logger.Info("file name:%s", ssmFileName)
	logger.Info("sns:%s\n  user:%s\n  pwd:%s\n", sns, string(user), string(pwd))

	global.BlockAllRequests = true

	if module == Ctrl {
		err = installSsmCtrl()
		if err != nil {
			logger.Error("ctrl update ssm failed:%v", err)
			c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "操作失败"))
			global.BlockAllRequests = false
			return
		}
		services.SaveOptLog(c.Request, "控制板SSM升级")
		c.JSON(http.StatusOK, mvc.OkWithMsg("升级成功"))

	} else {
		c.JSON(http.StatusOK, mvc.OkWithMsg("核心板正在升级ssm，预计5分钟升级完成"))
		err = scpInstallSsm(sns, string(user), string(pwd))
		if err != nil {
			logger.Error("core update ssm failed:%v", err)
			c.JSON(http.StatusOK, mvc.FailWithMsg(error2.UpgradeErr, "操作失败"))
			global.BlockAllRequests = false
			return
		}
		services.SaveOptLog(c.Request, "核心板SSM升级")

	}

	global.BlockAllRequests = false

}

func installSsmCtrl() error {
	/* cmd := exec.Command("tar", "-xzf", ssmFileName, "-C", "/data/ssm/")
	cmd.Dir = "/data/ssm"

	fmt.Println("Executing command:", cmd.String())

	// 执行命令
	out, err := cmd.CombinedOutput()
	if err != nil {
		logger.Error("unzip file %s failed:%v  out:%s", ssmFileName, err, out)
	}

	defer func() {
		err = os.RemoveAll("/data/ssm/install")
		if err != nil {
			logger.Info("deleting directory:", err)
		}
	}()

	script := "/data/ssm/install/update-bmssm.sh"
	// 检查脚本文件是否存在
	_, err = os.Stat(script)
	if err != nil {
		logger.Error("Script file not found:%v", err)
		return err
	}
	cmd = exec.Command("sudo", "/bin/bash", script)
	cmd.Dir = "/data/ssm/install"
	err = cmd.Run()
	if err != nil {
		logger.Error("run upgrade script failed:%v", err)
		return err
	}

	logger.Info("ssm upgrade successful!") */
	return nil
}

func scpInstallSsm(sns, user, pwd string) error {

	/* res, err := ssm.ExecCore(ssm.ExecCorex{
		Cmd:   "mkdir -p /data/ssm && sudo chown linaro /data/ssm",
		User:  "linaro",
		Pwd:   "linaro",
		DevId: sns,
	})
	logger.Info("ExecCore:%v, err:%v", res, err)

	res, err = ssm.ScpFile(ssm.Scp2Core{
		SrcCtrl:  "/data/ssm/" + ssmFileName,
		DstCore:  "/data/ssm/",
		CtrlUser: user,
		CtrlPwd:  pwd,
		CoreUser: "linaro",
		CorePwd:  "linaro",
	})

	logger.Info("ScpFile return:%v; err:%v", res, err)
	if err != nil {
		logger.Error("ssm scp file  failed:%v", err)
		return err
	}

	command := fmt.Sprintf("cd /data/ssm && sudo tar -xzvf %s", ssmFileName)

	res, err = ssm.ExecCore(ssm.ExecCorex{
		Cmd:   command,
		User:  "linaro",
		Pwd:   "linaro",
		DevId: sns,
	})
	logger.Info("core boards upgrade ssm:%v\n err:%v", res, err)

	command = "cd /data/ssm/install && sudo ./update-bmssm.sh"

	res, err = ssm.ExecCore(ssm.ExecCorex{
		Cmd:   command,
		User:  "linaro",
		Pwd:   "linaro",
		DevId: sns,
	})
	logger.Info("core boards upgrade ssm:%v\n err:%v", res, err)

	return err*/
	return nil
}
