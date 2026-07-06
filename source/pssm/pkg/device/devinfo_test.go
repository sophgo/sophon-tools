package device

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseOEMConfig(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("testdata", "OEMconfig.ini"))
	if err != nil {
		t.Fatal(err)
	}
	ti, cs, ds, mt := ParseOEMConfig(string(data))
	if ti != "SE8" {
		t.Fatalf("typeEx=%q", ti)
	}
	if cs != "CHIPSN123" {
		t.Fatalf("chipSn=%q", cs)
	}
	if ds != "DEVSN456" {
		t.Fatalf("deviceSn=%q", ds)
	}
	if mt != "BM1684" {
		t.Fatalf("moduleType=%q", mt)
	}
}

func TestParseOEMConfigEmpty(t *testing.T) {
	ti, cs, ds, mt := ParseOEMConfig("")
	if ti != "" || cs != "" || ds != "" || mt != "" {
		t.Fatalf("expected all empty: %q %q %q %q", ti, cs, ds, mt)
	}
}

func TestLoadFromOEMSetsGlobals(t *testing.T) {
	LoadFromOEM(filepath.Join("testdata", "OEMconfig.ini"))
	if DeviceType != "soc" {
		t.Fatalf("DeviceType=%q", DeviceType)
	}
	if DeviceRole != "SE" {
		t.Fatalf("DeviceRole=%q", DeviceRole)
	}
	if DeviceTypeEx != "SE8" {
		t.Fatalf("DeviceTypeEx=%q", DeviceTypeEx)
	}
	if ChipSn != "CHIPSN123" {
		t.Fatalf("ChipSn=%q", ChipSn)
	}
}

// TestParseJSONLoose 表驱动覆盖 parseJSONLoose：纯 string JSON、混合类型（非 string 跳过）、
// 空 JSON 对象、非法 JSON（返回 error）。
func TestParseJSONLoose(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		want    map[string]string
		wantErr bool
	}{
		{
			name:  "all-string",
			input: `{"model":"SE8","product sn":"ABC123"}`,
			want:  map[string]string{"model": "SE8", "product sn": "ABC123"},
		},
		{
			name: "mixed-types-non-string-skipped",
			// 数字 / 布尔 / 嵌套对象均非 string，应被跳过；仅 string 字段保留
			input: `{"model":"SE8","count":3,"ok":true,"nested":{"a":1},"product sn":"Z"}`,
			want:  map[string]string{"model": "SE8", "product sn": "Z"},
		},
		{
			name:  "empty-object",
			input: `{}`,
			want:  map[string]string{},
		},
		{
			name:    "invalid-json",
			input:   `{not json`,
			wantErr: true,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var got map[string]string
			err := parseJSONLoose([]byte(tc.input), &got)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil; result=%v", got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(got) != len(tc.want) {
				t.Fatalf("size mismatch: got=%v want=%v", got, tc.want)
			}
			for k, v := range tc.want {
				if got[k] != v {
					t.Fatalf("key %q: got=%q want=%q", k, got[k], v)
				}
			}
		})
	}
}

// TestGetDeviceInfoI2CFirst 验证 i2c 优先顺序：i2c 存在时走 i2c 分支（SOC_DEV），
// 并从 OEM 补充 DEVICE_SN。
func TestGetDeviceInfoI2CFirst(t *testing.T) {
	dir := t.TempDir()

	// 模拟 SE7 i2c information
	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE7 V1","chip":"BM1684X","mcu":"STM32","product sn":"EC712AC0C24120073","board type":"0x33"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	// 模拟 OEMconfig.ini（含 DEVICE_SN，但 PRODUCT 为空，模拟 SE7 真机）
	oemPath := filepath.Join(dir, "OEMconfig.ini")
	oemINI := "PRODUCT =\nSN = EC712AC0C24120073\nDEVICE_SN = HQATEVBAIAIAI0001\nCHIP = BM1684X\n"
	if err := os.WriteFile(oemPath, []byte(oemINI), 0644); err != nil {
		t.Fatal(err)
	}

	// 重置全局状态再调用
	DeviceType = ""
	DeviceRole = ""
	DeviceTypeEx = ""
	DeviceSnEx = ""
	ChipSn = ""
	ModuleType = ""
	getDeviceInfo(i2cPath, oemPath, filepath.Join(dir, "board-ip"))

	if DeviceType != "soc" {
		t.Fatalf("DeviceType: got=%q want=soc", DeviceType)
	}
	if DeviceRole != "SE" {
		t.Fatalf("DeviceRole: got=%q want=SE", DeviceRole)
	}
	if DeviceTypeEx != "SE7 V1" {
		t.Fatalf("DeviceTypeEx: got=%q want=SE7 V1", DeviceTypeEx)
	}
	if ChipSn != "EC712AC0C24120073" {
		t.Fatalf("ChipSn: got=%q want=EC712AC0C24120073", ChipSn)
	}
	if DeviceSnEx != "HQATEVBAIAIAI0001" {
		t.Fatalf("DeviceSnEx: got=%q want=HQATEVBAIAIAI0001", DeviceSnEx)
	}
	if ModuleType != "BM1684X" {
		t.Fatalf("ModuleType: got=%q want=BM1684X", ModuleType)
	}
}

// TestGetDeviceInfoOEMFallback 验证 i2c 不存在时回退到 OEM 路径。
func TestGetDeviceInfoOEMFallback(t *testing.T) {
	dir := t.TempDir()

	// 仅 OEM 文件存在，无 i2c
	oemPath := filepath.Join(dir, "OEMconfig.ini")
	oemINI := "PRODUCT = SE8\nSN = CHIPSN123\nSN = DEVSN456\nCHIP = BM1684\n"
	if err := os.WriteFile(oemPath, []byte(oemINI), 0644); err != nil {
		t.Fatal(err)
	}
	i2cPath := filepath.Join(dir, "no-such-i2c")

	// 重置全局状态
	DeviceType = ""
	DeviceRole = ""
	DeviceTypeEx = ""
	DeviceSnEx = ""
	ChipSn = ""
	ModuleType = ""
	getDeviceInfo(i2cPath, oemPath, filepath.Join(dir, "board-ip"))

	if DeviceType != "soc" {
		t.Fatalf("DeviceType: got=%q want=soc", DeviceType)
	}
	if DeviceRole != "SE" {
		t.Fatalf("DeviceRole: got=%q want=SE", DeviceRole)
	}
	if DeviceTypeEx != "SE8" {
		t.Fatalf("DeviceTypeEx: got=%q want=SE8", DeviceTypeEx)
	}
}

// TestReadDeviceSnFromOEM 验证 DEVICE_SN 字段读取。
func TestReadDeviceSnFromOEM(t *testing.T) {
	dir := t.TempDir()

	t.Run("has DEVICE_SN", func(t *testing.T) {
		p := filepath.Join(dir, "with_sn.ini")
		if err := os.WriteFile(p, []byte("DEVICE_SN = HQATEVBAIAIAI0001\n"), 0644); err != nil {
			t.Fatal(err)
		}
		if got := readDeviceSnFromOEM(p); got != "HQATEVBAIAIAI0001" {
			t.Fatalf("got=%q", got)
		}
	})

	t.Run("no DEVICE_SN", func(t *testing.T) {
		p := filepath.Join(dir, "no_sn.ini")
		if err := os.WriteFile(p, []byte("SN = ABC\nPRODUCT = SE8\n"), 0644); err != nil {
			t.Fatal(err)
		}
		if got := readDeviceSnFromOEM(p); got != "" {
			t.Fatalf("expected empty, got=%q", got)
		}
	})

	t.Run("file not exist", func(t *testing.T) {
		if got := readDeviceSnFromOEM(filepath.Join(dir, "nonexistent.ini")); got != "" {
			t.Fatalf("expected empty, got=%q", got)
		}
	})
}

// TestGetDeviceInfoI2CDefaultSE6Core 默认分支 + board-ip 非空 → SE6_CORE，DeviceSnEx=ChipSn。
func TestGetDeviceInfoI2CDefaultSE6Core(t *testing.T) {
	dir := t.TempDir()

	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE6","chip":"BM1684","product sn":"CHIPSN456"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	boardIPPath := filepath.Join(dir, "board-ip")
	if err := os.WriteFile(boardIPPath, []byte("brdip:0.0.0.0"), 0644); err != nil {
		t.Fatal(err)
	}

	oemPath := filepath.Join(dir, "OEMconfig.ini")

	resetGlobals()
	getDeviceInfo(i2cPath, oemPath, boardIPPath)

	if DeviceType != "soc" {
		t.Fatalf("DeviceType: got=%q want=soc", DeviceType)
	}
	if DeviceRole != SE6_CORE {
		t.Fatalf("DeviceRole: got=%q want=%s", DeviceRole, SE6_CORE)
	}
	if DeviceTypeEx != "SE6" {
		t.Fatalf("DeviceTypeEx: got=%q want=SE6", DeviceTypeEx)
	}
	if ChipSn != "CHIPSN456" {
		t.Fatalf("ChipSn: got=%q want=CHIPSN456", ChipSn)
	}
	if DeviceSnEx != "CHIPSN456" {
		t.Fatalf("DeviceSnEx: got=%q want=CHIPSN456 (equals ChipSn)", DeviceSnEx)
	}
}

// TestGetDeviceInfoI2CDefaultSE5NoBoardIP 默认分支 + board-ip 不存在 → SE5。
func TestGetDeviceInfoI2CDefaultSE5NoBoardIP(t *testing.T) {
	dir := t.TempDir()

	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE6","chip":"BM1684","product sn":"CHIPSN456"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	boardIPPath := filepath.Join(dir, "no-such-board-ip")
	oemPath := filepath.Join(dir, "OEMconfig.ini")

	resetGlobals()
	getDeviceInfo(i2cPath, oemPath, boardIPPath)

	if DeviceRole != SE5 {
		t.Fatalf("DeviceRole: got=%q want=%s", DeviceRole, SE5)
	}
}

// TestGetDeviceInfoI2CDefaultSE5EmptyBoardIP 默认分支 + board-ip 内容空 → SE5。
func TestGetDeviceInfoI2CDefaultSE5EmptyBoardIP(t *testing.T) {
	dir := t.TempDir()

	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE6","chip":"BM1684","product sn":"CHIPSN456"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	boardIPPath := filepath.Join(dir, "board-ip")
	if err := os.WriteFile(boardIPPath, []byte(""), 0644); err != nil {
		t.Fatal(err)
	}

	oemPath := filepath.Join(dir, "OEMconfig.ini")

	resetGlobals()
	getDeviceInfo(i2cPath, oemPath, boardIPPath)

	if DeviceRole != SE5 {
		t.Fatalf("DeviceRole: got=%q want=%s", DeviceRole, SE5)
	}
}

// TestGetDeviceInfoI2CSE6Ctrl model 精确匹配 SE6-CTRL → SE6_CTRL。
func TestGetDeviceInfoI2CSE6Ctrl(t *testing.T) {
	dir := t.TempDir()

	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE6-CTRL","chip":"BM1684","product sn":"CHIPSN789"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	boardIPPath := filepath.Join(dir, "no-such-board-ip")
	oemPath := filepath.Join(dir, "OEMconfig.ini")
	if err := os.WriteFile(oemPath, []byte("DEVICE_SN = DEVSN999\n"), 0644); err != nil {
		t.Fatal(err)
	}

	resetGlobals()
	getDeviceInfo(i2cPath, oemPath, boardIPPath)

	if DeviceRole != SE6_CTRL {
		t.Fatalf("DeviceRole: got=%q want=%s", DeviceRole, SE6_CTRL)
	}
	if DeviceTypeEx != "SE6-CTRL" {
		t.Fatalf("DeviceTypeEx: got=%q want=SE6-CTRL", DeviceTypeEx)
	}
	if ChipSn != "CHIPSN789" {
		t.Fatalf("ChipSn: got=%q want=CHIPSN789", ChipSn)
	}
	// SE6_CTRL 应从 OEM 读 DEVICE_SN
	if DeviceSnEx != "DEVSN999" {
		t.Fatalf("DeviceSnEx: got=%q want=DEVSN999", DeviceSnEx)
	}
}

// TestGetDeviceInfoI2CSE7 model 含 SE7 → SE5。
func TestGetDeviceInfoI2CSE7(t *testing.T) {
	dir := t.TempDir()

	i2cPath := filepath.Join(dir, "information")
	i2cJSON := `{"model":"SE7 V1","chip":"BM1684X","product sn":"EC712AC0C24120073"}`
	if err := os.WriteFile(i2cPath, []byte(i2cJSON), 0644); err != nil {
		t.Fatal(err)
	}

	boardIPPath := filepath.Join(dir, "no-such-board-ip")
	oemPath := filepath.Join(dir, "OEMconfig.ini")
	if err := os.WriteFile(oemPath, []byte("DEVICE_SN = HQATEVBAIAIAI0001\n"), 0644); err != nil {
		t.Fatal(err)
	}

	resetGlobals()
	getDeviceInfo(i2cPath, oemPath, boardIPPath)

	if DeviceRole != SE5 {
		t.Fatalf("DeviceRole: got=%q want=%s", DeviceRole, SE5)
	}
	if DeviceTypeEx != "SE7 V1" {
		t.Fatalf("DeviceTypeEx: got=%q want=SE7 V1", DeviceTypeEx)
	}
	if ChipSn != "EC712AC0C24120073" {
		t.Fatalf("ChipSn: got=%q want=EC712AC0C24120073", ChipSn)
	}
	if DeviceSnEx != "HQATEVBAIAIAI0001" {
		t.Fatalf("DeviceSnEx: got=%q want=HQATEVBAIAIAI0001", DeviceSnEx)
	}
}

// resetGlobals 重置包级变量为初始值。
func resetGlobals() {
	DeviceType = ""
	DeviceRole = ""
	DeviceTypeEx = ""
	DeviceSnEx = ""
	ChipSn = ""
	ModuleType = ""
}
