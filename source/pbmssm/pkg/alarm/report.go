package alarm

import (
	"bytes"
	"fmt"
	"net/http"
	"strconv"
	"time"
)

// ---------------------------------------------------------------
// code → 文案 / ComponentType（对齐 bmssm parseAlarmCode / ExternAlarmReport）
// ---------------------------------------------------------------

// parseAlarmCode 按 bmssm 模板生成中文描述。value 为超限值（恢复时 -1）。
func parseAlarmCode(code, value int) string {
	switch code {
	case CodeCPURateAlarm:
		return fmt.Sprintf("cpu使用率过高,值为:%s%%", strconv.Itoa(value))
	case CodeCPURateRecover:
		return "cpu使用率过高恢复"
	case CodeMemRateAlarm:
		return fmt.Sprintf("内存使用率过高,值为:%s%%", strconv.Itoa(value))
	case CodeMemRateRecover:
		return "内存使用率过高恢复"
	case CodeDiskRateAlarm:
		return fmt.Sprintf("磁盘使用率过高,值为:%s%%", strconv.Itoa(value))
	case CodeDiskRateRecover:
		return "磁盘使用率过高恢复"
	case CodeBoardTempAlarm:
		return fmt.Sprintf("板卡温度过高,值为:%sC", strconv.Itoa(value))
	case CodeBoardTempRecover:
		return "板卡温度过高恢复"
	case CodeChipTempAlarm:
		return fmt.Sprintf("芯片温度过高,值为:%sC", strconv.Itoa(value))
	case CodeChipTempRecover:
		return "芯片温度过高恢复"
	case CodeTPURateAlarm:
		return fmt.Sprintf("tpu使用率过高,值为:%s%%", strconv.Itoa(value))
	case CodeTPURateRecover:
		return "tpu使用率过高恢复"
	default:
		return "未知代码: " + strconv.Itoa(code)
	}
}

// componentType 按 bmssm ExternAlarmReport：Abs(code/100000)。
// 101xxx/102xxx/103xxx → 1（中央处理单元），201xxx/202xxx → 2（核心计算单元）。
func componentType(code int) int {
	c := code / 100000
	if c < 0 {
		c = -c
	}
	return c
}

// buildPayload 构造 AlarmRec。
//   - 主控指标（CPU/内存/磁盘/板温）boardSn=deviceSn，chipSn 空
//   - 芯片指标（芯片温/TPU）boardSn=boardSnArg，chipSn=chipSnArg
//   - 恢复事件 boardSn/chipSn/diskName 全空，value=-1（对齐 bmssm AlarmReport 正 code 分支）
func buildPayload(code, value int, deviceSn, boardSn, chipSn, diskName string, now time.Time) AlarmRec {
	rec := AlarmRec{
		DeviceSn:      deviceSn,
		ComponentType: componentType(code),
		Code:          code,
		Msg:           parseAlarmCode(code, value),
		DateTime:      now.Format("2006-01-02 15:04:05"),
	}
	if code > 0 {
		// 恢复事件：bmssm 对正 code 传空 boardSn/chipIdx/diskName、value=-1
		return rec
	}
	// 告警事件：填充定位字段
	switch code {
	case CodeCPURateAlarm, CodeMemRateAlarm:
		rec.BoardSn = boardSn // SOC 单板 boardSn=主控
	case CodeDiskRateAlarm:
		rec.BoardSn = boardSn
		rec.DiskName = diskName
	case CodeBoardTempAlarm:
		rec.BoardSn = boardSn // 板温定位到板卡
	case CodeChipTempAlarm, CodeTPURateAlarm:
		rec.BoardSn = boardSn
		rec.ChipSn = chipSn
	}
	return rec
}

// ---------------------------------------------------------------
// HTTP Poster 生产实现
// ---------------------------------------------------------------

// httpPoster 用 http.Client POST JSON，超时 5s，失败仅返错不阻断。
type httpPoster struct {
	client *http.Client
}

// NewHTTPPoster 创建生产 HTTP poster。
func NewHTTPPoster() Poster {
	return &httpPoster{client: &http.Client{Timeout: 5 * time.Second}}
}

func (p *httpPoster) Post(url string, payload []byte) error {
	resp, err := p.client.Post(url, "application/json", bytes.NewReader(payload))
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	// sophliteos AlarmListen 始终返 200，非 2xx 视为异常
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("alarm post %s: status %d", url, resp.StatusCode)
	}
	return nil
}
