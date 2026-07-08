package config

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/spf13/viper"
)

func TestLoadConfigFromDir(t *testing.T) {
	dir := t.TempDir()
	yaml := []byte("server:\n  port: 9999\n  auth: false\nlog:\n  level: debug\n  path: /tmp/log\ndb:\n  driver: sqlite3\n  path: /tmp/x.db\n")
	if err := os.WriteFile(filepath.Join(dir, "bmssm.yaml"), yaml, 0o644); err != nil {
		t.Fatal(err)
	}
	LoadFromDir(dir)

	v := Conf.GetViper()
	if v.GetString("server.port") != "9999" {
		t.Fatalf("port=%s", v.GetString("server.port"))
	}
	if v.GetBool("server.auth") != false {
		t.Fatal("auth should be false")
	}
	if v.GetString("log.level") != "debug" {
		t.Fatalf("level=%s", v.GetString("log.level"))
	}
}

func TestDefaultsWhenMissing(t *testing.T) {
	dir := t.TempDir() // 空目录，无 bmssm.yaml
	ok := LoadFromDir(dir)
	if ok {
		t.Fatal("expected LoadFromDir to report no config loaded for empty dir")
	}
	v := Conf.GetViper()
	if v.GetString("server.port") != "9779" {
		t.Fatalf("default port expected, got %s", v.GetString("server.port"))
	}
	if v.GetBool("server.auth") != true {
		t.Fatal("default auth should be true")
	}
}

// TestLoadRealRepoConfig 覆盖本地 ./config/bmssm.yaml 回退路径：
// 显式从仓库内置的 config 目录加载，验证 port=9779 auth=true。
func TestLoadRealRepoConfig(t *testing.T) {
	ok := LoadFromDir(".")
	if !ok {
		t.Skip("no bmssm.yaml in CWD; skip real-config path test")
	}
	v := Conf.GetViper()
	if v.GetString("server.port") != "9779" {
		t.Fatalf("expected default port 9779 from repo bmssm.yaml, got %s", v.GetString("server.port"))
	}
	if v.GetBool("server.auth") != true {
		t.Fatal("expected auth=true from repo bmssm.yaml")
	}
}

// TestLoadConfigSSMConfEnv 覆盖 BMSSM_CONF 环境变量优先回退路径：
// 设置 BMSSM_CONF 指向自定义目录，调用 LoadConfig()，验证 port 为自定义值。
func TestLoadConfigSSMConfEnv(t *testing.T) {
	dir := t.TempDir()
	// 用独立 port 值避免与其它测试的全局 Conf 状态污染
	yaml := []byte("server:\n  port: \"7777\"\nlog:\n  level: debug\n  path: /tmp/bmssm-env\n")
	if err := os.WriteFile(filepath.Join(dir, "bmssm.yaml"), yaml, 0o644); err != nil {
		t.Fatal(err)
	}

	os.Setenv("BMSSM_CONF", dir)
	defer os.Unsetenv("BMSSM_CONF")

	LoadConfig()
	v := Conf.GetViper()
	if v.GetString("server.port") != "7777" {
		t.Fatalf("expected port 7777 from BMSSM_CONF dir, got %s", v.GetString("server.port"))
	}
}

// ---------------------------------------------------------------
// alarmThreshold 默认值测试（对齐 bmssm deviceConf.json）
// ---------------------------------------------------------------

func TestAlarmThresholdDefaults(t *testing.T) {
	dir := t.TempDir()
	ok := LoadFromDir(dir) // 空目录，全用 SetDefault
	if ok {
		t.Fatal("expected LoadFromDir to report no config for empty dir")
	}
	v := Conf.GetViper()

	tests := []struct {
		key   string
		want  float64
		isInt bool
		wantInt int
	}{
		{"alarmThreshold.boardTemperature", 90, true, 90},
		{"alarmThreshold.coreTemperature", 90, true, 90},
		{"alarmThreshold.cpuRate", 0.95, false, 0},
		{"alarmThreshold.diskRate", 0.95, false, 0},
		{"alarmThreshold.externalHardDiskRate", 0.95, false, 0},
		{"alarmThreshold.fanSpeed", 9999, true, 9999},
		{"alarmThreshold.systemScale", 0.95, false, 0},
		{"alarmThreshold.totalMemoryScale", 0.95, false, 0},
		{"alarmThreshold.tpuRate", 0.95, false, 0},
		{"alarmThreshold.tpuScale", 0.95, false, 0},
		{"alarmThreshold.videoScale", 0.95, false, 0},
	}

	for _, tt := range tests {
		if tt.isInt {
			got := v.GetInt(tt.key)
			if got != tt.wantInt {
				t.Errorf("%s = %d, want %d", tt.key, got, tt.wantInt)
			}
		} else {
			got := v.GetFloat64(tt.key)
			if got != tt.want {
				t.Errorf("%s = %v, want %v", tt.key, got, tt.want)
			}
		}
	}
}

// TestAlarmThresholdFromYaml 验证从 bmssm.yaml 读取 alarmThreshold 覆盖默认值。
func TestAlarmThresholdFromYaml(t *testing.T) {
	dir := t.TempDir()
	yaml := []byte(`server:
  port: "9999"
alarmThreshold:
  boardTemperature: 85
  coreTemperature: 80
  cpuRate: 0.80
`)
	if err := os.WriteFile(filepath.Join(dir, "bmssm.yaml"), yaml, 0o644); err != nil {
		t.Fatal(err)
	}
	LoadFromDir(dir)

	v := Conf.GetViper()
	if v.GetFloat64("alarmThreshold.boardTemperature") != 85 {
		t.Errorf("boardTemperature = %v, want 85", v.GetFloat64("alarmThreshold.boardTemperature"))
	}
	if v.GetFloat64("alarmThreshold.coreTemperature") != 80 {
		t.Errorf("coreTemperature = %v, want 80", v.GetFloat64("alarmThreshold.coreTemperature"))
	}
	if v.GetFloat64("alarmThreshold.cpuRate") != 0.80 {
		t.Errorf("cpuRate = %v, want 0.80", v.GetFloat64("alarmThreshold.cpuRate"))
	}
	// 未在 yaml 中的 key 应回落默认值
	if v.GetFloat64("alarmThreshold.diskRate") != 0.95 {
		t.Errorf("diskRate default = %v, want 0.95", v.GetFloat64("alarmThreshold.diskRate"))
	}
}

// TestAlarmThresholdPersistence Set+WriteConfig 持久化测试。
// 不与 WatchConfig 共用同个 viper，避免 viper 内部 data race。
func TestAlarmThresholdPersistence(t *testing.T) {
	dir := t.TempDir()
	yamlPath := filepath.Join(dir, "bmssm.yaml")
	yaml := []byte(`server:
  port: "7777"
alarmThreshold:
  boardTemperature: 90
`)
	if err := os.WriteFile(yamlPath, yaml, 0o644); err != nil {
		t.Fatal(err)
	}

	// 用独立 viper（无 WatchConfig），避免 viper 内部 WriteConfig 与 WatchConfig 竞态
	v := viper.New()
	v.SetConfigFile(yamlPath)
	if err := v.ReadInConfig(); err != nil {
		t.Fatalf("ReadInConfig: %v", err)
	}
	if got := v.GetFloat64("alarmThreshold.boardTemperature"); got != 90 {
		t.Fatalf("initial boardTemperature = %v, want 90", got)
	}

	// 修改并持久化
	v.Set("alarmThreshold.boardTemperature", 70)
	if err := v.WriteConfig(); err != nil {
		t.Fatalf("WriteConfig failed: %v", err)
	}

	// 重新加载验证持久化
	v2 := viper.New()
	v2.SetConfigFile(yamlPath)
	if err := v2.ReadInConfig(); err != nil {
		t.Fatalf("re-read: %v", err)
	}
	if got := v2.GetFloat64("alarmThreshold.boardTemperature"); got != 70 {
		t.Errorf("after persist+reload: boardTemperature = %v, want 70", got)
	}

	// 验证文件内容包含更新值
	raw, err := os.ReadFile(yamlPath)
	if err != nil {
		t.Fatalf("re-read yaml: %v", err)
	}
	if !bytes.Contains(raw, []byte("70")) {
		t.Errorf("yaml file does not contain updated value 70:\n%s", string(raw))
	}
}