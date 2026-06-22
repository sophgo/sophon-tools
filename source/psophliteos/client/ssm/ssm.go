package ssm

import (
	"encoding/json"
	"net/http"
	"time"

	http2 "sophliteos/client/httpclient"
	"sophliteos/config"
	"sophliteos/logger"
	"sophliteos/mvc/types"

	"github.com/mitchellh/mapstructure"
	"github.com/patrickmn/go-cache"
)

const (
	ssmPrefix = "/bitmain/v1/ssm"

	ssmDevicePrefix = ssmPrefix + "/software/device"
	// SSM系统登录接口
	ssmSystemLoginUri = ssmPrefix + "/login"
	// SSM设备登录接口
	ssmDeviceLoginUri = ssmDevicePrefix + "/login"
	// 查询算力设备算力信息
	ssmDeviceResourceUri = ssmDevicePrefix + "/resource/list?all=0"
	// 查询算力设备基础信息
	ssmDeviceBasicUri = ssmDevicePrefix + "/basic"
	// IP查询
	ssmIpList = ssmPrefix + "/hardware/ip"
	// IP修改
	ssmIpSetUri = ssmPrefix + "/hardware/ip"
	// Name修改
	ssmBasicSetUri = ssmDevicePrefix + "/configure/basic"
	// 阈值告警
	ssmAlarmUri = ssmDevicePrefix + "/configure/alarm"

	ssmSubscribePrefix = ssmPrefix + "/software/notify"
	// 查询告警，订阅告警
	ssmAlarmSubscribeUri = ssmSubscribePrefix + "/subscribe"
	// 取消告警订阅
	ssmAlarmUnSubscribeUri = ssmSubscribePrefix + "/unsubscribe"
	// 回调地址
	ssmAlarmCallbackUri = "/api/device/alarm"
	// 上传ota
	ssmUploadUri = ssmPrefix + "/file/ota"
	// 升级Uri
	ssmUpgradeUri = ssmPrefix + "/workflow/upgrade"
	// 回滚uri
	ssmRollbackUri = ssmPrefix + "/workflow/rollback"
	// 关机
	ssmCoreBoardShutdownUri = ssmPrefix + "/hardware/devices/down"
	// 重启
	ssmCoreBoardRebootUri = ssmPrefix + "/hardware/devices/reset"
	// scp文件传输
	ssmCoreBoardScpUri = ssmPrefix + "/hardware/devices/scp"
	// 执行命令
	ssmCoreBoardExecUri = ssmPrefix + "/hardware/devices/exec"
	// 执行命令
	ssmIpTablesUri = ssmPrefix + "/hardware/nat"
)

var tokenCache *cache.Cache

func init() {
	tokenCache = cache.New(2*time.Hour, 5*time.Minute)
}

func getUrlHeader(uri string) (string, map[string]string, error) {

	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	server := v.GetString("ssm.server")
	// username := v.GetString("ssm.username")
	// password := v.GetString("ssm.password")
	conf.Unlock()

	header := make(map[string]string)
	// cache, found := tokenCache.Get(username)
	// if found {
	// 	header["Authorization"] = "Bearer " + cache.(string)
	// } else {
	// 	conf.Lock()
	// 	token, err := SystemLogin(server, username, password)
	// 	conf.Unlock()
	// 	if err != nil {
	// 		return "", map[string]string{}, err
	// 	} else {
	// 		tokenCache.Set(username, token, 2*time.Hour)
	// 	}
	// 	header["Authorization"] = "Bearer " + token
	// }

	return server + uri, header, nil
}

// 系统登录
func SystemLogin(ssmServer, username, password string) (string, error) {
	login, _ := json.Marshal(types.LoginRequest{
		UserName: username,
		Password: password,
	})
	result, err := NewSsmRequestWithHeaders(ssmServer+ssmSystemLoginUri, http.MethodPost, map[string]string{}, login)
	if err != nil {
		return "", err
	}
	var res SystemLoginResponse
	_ = mapstructure.Decode(result.Result, &res)
	return res.Token, nil
}

// 查询控制板算力信息
func GetCtrlResource() (CtrlResource, error) {
	var err error
	result, err := NewSsmRequest(ssmDeviceResourceUri, http.MethodGet, []byte{})
	if err != nil {
		return CtrlResource{}, err
	}
	var resource CtrlResource
	// logger.Info("%v", result.Result.([]interface{})[0].(map[string]interface{}))
	jsonData, _ := json.Marshal(result.Result.([]interface{})[0])

	if err = json.Unmarshal(jsonData, &resource); err != nil {
		err = mapstructure.Decode(result.Result, &resource)
	}
	return resource, err
}

// 查询算力控制板基础信息
func GetCtrlBasic() (CtrlBasic, string, error) {
	var ctrl CtrlBasic
	var res SsmResult
	result, err := NewSsmRequest(ssmDeviceBasicUri, http.MethodGet, []byte{})
	if err != nil {
		return ctrl, "", err
	}
	err = mapstructure.Decode(result.Result, &ctrl)
	mapstructure.Decode(result, &res)
	return ctrl, res.DeviceSn, err
}

// ipTables
func GetIpTables() ([]string, error) {
	var list []string
	result, err := NewSsmRequest(ssmIpTablesUri, http.MethodGet, []byte{})
	err = mapstructure.Decode(result.Result, &list)
	return list, err
}

// ipTables增加
func AddIpTable(table AddTable) (SsmResult, error) {
	data, _ := json.Marshal(table)
	return NewSsmRequest(ssmIpTablesUri, http.MethodPost, data)
}

// ipTables删除
func DeleteIpTable(num string) (SsmResult, error) {
	return NewSsmRequest(ssmIpTablesUri+"/PREROUTING-"+num, http.MethodDelete, []byte{})
}

// IP修改
func SetIP(ip IPSettings) (SsmResult, error) {
	data, _ := json.Marshal(ip)
	return NewSsmRequest(ssmIpSetUri, http.MethodPost, data)
}

// 基本信息修改
func SetBasic(name BasicSettings) (SsmResult, error) {
	data, _ := json.Marshal(name)
	return NewSsmRequest(ssmBasicSetUri, http.MethodPost, data)
}

// IP查询
func GetIP() (SsmResult, error) {
	return NewSsmRequest(ssmIpList, http.MethodGet, []byte{})
}

// 告警设置
func SetAlarm(alarmThreshold []byte) ([]SsmResult, error) {
	var result []SsmResult
	// 设置核心板
	err := NewRequest(ssmAlarmUri+"?devices=cores", http.MethodPost, alarmThreshold, &result)
	if err != nil {
		return nil, err
	}
	// 设置控制板
	var cr SsmResult
	err = NewRequest(ssmAlarmUri, http.MethodPost, alarmThreshold, &cr)
	if err != nil {
		return nil, err
	}
	return result, nil
}

// 告警设置
func SetAlarmSe5(alarmThreshold []byte) (SsmResult, error) {
	var result SsmResult
	// 设置核心板
	err := NewRequest(ssmAlarmUri+"?devices=cores", http.MethodPost, alarmThreshold, &result)
	if err != nil {
		return SsmResult{}, err
	}
	// 设置控制板
	var cr SsmResult
	err = NewRequest(ssmAlarmUri, http.MethodPost, alarmThreshold, &cr)
	if err != nil {
		return SsmResult{}, err
	}
	return result, nil
}

// 查询订阅
func GetAlarm() (SsmResult, error) {
	return NewSsmRequest(ssmAlarmSubscribeUri+"/"+config.Conf.GetName(), http.MethodGet, []byte{})
}

// 订阅通知
func SubscribeAlarm() (SsmResult, error) {
	subscribe := getSubscribeAlarm()
	return NewSsmRequest(ssmAlarmSubscribeUri, http.MethodPost, subscribe)
}

// 全局订阅对象
func getSubscribeAlarm() []byte {
	conf := &config.Conf
	conf.Lock()
	v := conf.GetViper()
	port := v.GetString("server.port")
	conf.Unlock()
	data, _ := json.Marshal(&AlarmSubscribe{
		Platform:            config.Conf.GetName(),
		SubscribeDetailType: []int{1, 2},
		NotificationURL:     "http://127.0.0.1:" + port + ssmAlarmCallbackUri,
	})
	return data
}

// 取消订阅
func UnSubscribeAlarm() (SsmResult, error) {
	return NewSsmRequest(ssmAlarmUnSubscribeUri, http.MethodPost, getSubscribeAlarm())
}

// 上传OTA升级包
func OtaUpload(otaFile OtaFile) (SsmResult, error) {
	logger.Info("上传%s文件", otaFile.Module)
	result, err := NewSsmMultiFileRequest(ssmUploadUri, http.MethodPost,
		map[string]string{
			"module": otaFile.Module,
		}, otaFile.Filename, otaFile.Body)
	return result, err
}

// 传输文件到核心板
func ScpFile(upgrade Scp2Core) (SsmResult, error) {
	data, _ := json.Marshal(upgrade)
	return NewSsmRequest(ssmCoreBoardScpUri, http.MethodPost, data)
}

// 核心板执行命令或脚本
func ExecCore(exec ExecCorex) (SsmResult, error) {
	data, _ := json.Marshal(exec)
	return NewSsmRequest(ssmCoreBoardExecUri, http.MethodPost, data)
}

// 查看升级文件
func OtaUploadList() (SsmResult, error) {
	return NewSsmRequest(ssmUploadUri, http.MethodGet, []byte{})
}

// OTA升级
func OtaUpgrade(upgrade OtaVersion) (SsmResult, error) {
	data, _ := json.Marshal(upgrade)
	return NewSsmRequest(ssmUpgradeUri, http.MethodPost, data)
}

// OTA升级列表
func OtaUpgradeList() (SsmResult, error) {
	return NewSsmRequest(ssmUpgradeUri, http.MethodGet, []byte{})
}

// OTA升级回滚
func OtaRollback(upgrade OtaVersion) (SsmResult, error) {
	data, _ := json.Marshal(upgrade)
	return NewSsmRequest(ssmRollbackUri, http.MethodPost, data)
}

// 核心板关机重启操作
func CoreOperate(number, operationType int) (SsmResult, error) {
	uri := ""
	if operationType == Reboot {
		uri = ssmCoreBoardRebootUri
	} else if operationType == Shutdown {
		uri = ssmCoreBoardShutdownUri
	} else {
		return SsmResult{
			ErrorCode:    0,
			ErrorMessage: "",
		}, nil
	}
	data, _ := json.Marshal(CoreOpe{
		Id: number,
	})
	return NewSsmRequest(uri, http.MethodPost, data)
}

// 请求验证
func NewSsmRequest(uri string, method string, bytes []byte) (SsmResult, error) {
	url, header, err := getUrlHeader(uri)
	if err != nil {
		var res SsmResult
		return res, err
	}
	return NewSsmRequestWithHeaders(url, method, header, bytes)
}

// 请求验证
func NewSsmMultiFileRequest(uri string, method string, params map[string]string, filename string, bytes []byte) (SsmResult, error) {
	var result SsmResult
	url, header, err := getUrlHeader(uri)
	if err != nil {
		return result, err
	}
	data, err := http2.NewMultiFileRequest(url, method, header, params, filename, bytes)
	if err != nil {
		return result, err
	}
	err = json.Unmarshal(data, &result)
	if err != nil {
		return result, err
	}
	return result, nil
}

func NewSsmRequestWithHeaders(url string, method string, header map[string]string, bytes []byte) (SsmResult, error) {
	var result SsmResult
	err := NewRequestWithHeaders(url, method, header, bytes, &result)
	if err != nil {
		return result, err
	}
	return result, nil
}

// 请求验证
func NewRequestWithHeaders(url string, method string, header map[string]string, bytes []byte, v interface{}) error {
	// 远程调用
	data, err := http2.NewRequest(url, method, header, bytes)
	logger.Debug("url %s method %s header %v request %v",
		url, method, header, string(bytes))
	if err != nil {
		return err
	}
	return json.Unmarshal(data, v)
}

func NewRequest(uri string, method string, bytes []byte, v interface{}) error {
	// 远程调用
	url, header, err := getUrlHeader(uri)
	if err != nil {
		return nil
	}
	return NewRequestWithHeaders(url, method, header, bytes, v)
}
