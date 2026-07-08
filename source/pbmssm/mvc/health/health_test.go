package health

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"bmssm/global"
)

func init() { gin.SetMode(gin.ReleaseMode) }

func TestHealthz(t *testing.T) {
	// 保存原始值，测试结束后恢复
	origChipSn := global.ChipSn
	origModuleType := global.ModuleType
	origDeviceTypeEx := global.DeviceTypeEx
	origDeviceSnEx := global.DeviceSnEx
	origDeviceType := global.DeviceType
	origDeviceRole := global.DeviceRole
	origVersion := global.Version
	defer func() {
		global.ChipSn = origChipSn
		global.ModuleType = origModuleType
		global.DeviceTypeEx = origDeviceTypeEx
		global.DeviceSnEx = origDeviceSnEx
		global.DeviceType = origDeviceType
		global.DeviceRole = origDeviceRole
		global.Version = origVersion
	}()

	// 模拟真机数据
	global.ChipSn = "EC712AC0C24120073"
	global.ModuleType = "BM1684X"
	global.DeviceTypeEx = "SE7 V1"
	global.DeviceSnEx = "HQATEVBAIAIAI0001"
	global.DeviceType = "soc"
	global.DeviceRole = "SE"
	global.Version = global.BuildInfo{Version: "1.0.0-test"}

	r := gin.New()
	r.GET("/healthz", Health)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("healthz: expected 200, got %d body=%s", w.Code, w.Body.String())
	}

	var resp response
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("healthz: unmarshal failed: %v, body=%s", err, w.Body.String())
	}

	if resp.Status != "ok" {
		t.Errorf("Status = %q, want %q", resp.Status, "ok")
	}
	if resp.DeviceType != "soc" {
		t.Errorf("DeviceType = %q, want %q", resp.DeviceType, "soc")
	}
	if resp.DeviceTypeEx != "SE7 V1" {
		t.Errorf("DeviceTypeEx = %q, want %q", resp.DeviceTypeEx, "SE7 V1")
	}
	if resp.SN != "HQATEVBAIAIAI0001" {
		t.Errorf("SN = %q, want %q", resp.SN, "HQATEVBAIAIAI0001")
	}
	if resp.ChipSn != "EC712AC0C24120073" {
		t.Errorf("ChipSn = %q, want %q", resp.ChipSn, "EC712AC0C24120073")
	}
	if resp.ModuleType != "BM1684X" {
		t.Errorf("ModuleType = %q, want %q", resp.ModuleType, "BM1684X")
	}
	if resp.Version != "1.0.0-test" {
		t.Errorf("Version = %q, want %q", resp.Version, "1.0.0-test")
	}
	if resp.Uptime == "" {
		t.Error("Uptime should not be empty")
	}
}
