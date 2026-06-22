package system

type RouterGroup struct {
	BaseRouter
	ResourceRouter
	BasicRouter
	PasswordRouter
	IpQueryRouter
	AlarmRouter
	LogRouter
	OtaRouter
	VersionRouter
	UpgradeRouter
	SsmUpgradeRouter
	DownRouter
}
