package system

type ApiGroup struct {
	BaseApi
	ResourceApi
	BasicApi
	PasswordApi
	IpApi
	AlarmApi
	LogApi
	OtaApi
	VersionApi
	UpgradeApi
	SsmUpgradeApi
	DownApi
}
