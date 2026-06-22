package error

// 错误码定义
const (
	Ok             Code = 0   // 成功
	Err            Code = 500 // 失败
	NotImplemented      = 501 // 不支持请求

	// alarm	告警 100***
	SetAlarmErr Code = 100001 // 设置告警错误

	// device	设备 200***
	SetIpErr            Code = 200001 // 设置IP错误
	SetDeviceInfoErr    Code = 200002 // 设置设备基础信息错误
	PolicyNotSupport    Code = 200003 // IP策略不支持
	LanPolicyMustStatic Code = 200004 // Lan口IP必须为静态类型
	UnknownDeviceType   Code = 200005 // 未知的端口类型
	DeviceOperationErr  Code = 200006 // 核心板操作异常
	PwdNotEqErr         Code = 200007 // 原密码异常
	PwdValidErr         Code = 200008 // 密码校验失败

	// login	会话 300***
	InvalidUsernameOrPassword Code = 300001 // 无效的用户名密码
	InvalidToken              Code = 300002 // 无效的token

	// opt		日志 400***

	// ota		OTA 500***
	UpgradeParamErr     Code = 500000 // 升级错误
	UpgradeErr          Code = 500001 // 升级错误
	UpgradeTaskNotFound Code = 500002 // 升级任务不存在
	RollbackErr         Code = 500003 // 回滚错误

	Upgradeing Code = 500004 // 升级错误
)

type Code = int
