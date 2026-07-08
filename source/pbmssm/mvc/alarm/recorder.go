package alarm

import (
	"time"

	pkgalarm "bmssm/pkg/alarm"
)

// RecorderAdapter 把 pkg/alarm.AlarmRec 适配为 mvc/alarm.Alarm 并落库。
// 实现 pkg/alarm.Recorder 接口（依赖注入；pkg/alarm 不依赖本包，避免循环依赖）。
type RecorderAdapter struct {
	svc *AlarmService
	now func() time.Time
}

// NewRecorderAdapter 创建落库适配器。svc 为 nil 时 Record 返 nil（不落库）。
func NewRecorderAdapter(svc *AlarmService) *RecorderAdapter {
	return &RecorderAdapter{svc: svc, now: time.Now}
}

// Record 将告警 payload 转为 Alarm 行并写入 DB（best-effort，错误返给引擎记日志）。
func (r *RecorderAdapter) Record(rec pkgalarm.AlarmRec) error {
	if r.svc == nil {
		return nil
	}
	// DateTime 由引擎格式化为 "2006-01-02 15:04:05"；解析失败则用当前时间。
	var ts time.Time
	if t, err := time.ParseInLocation("2006-01-02 15:04:05", rec.DateTime, time.Local); err == nil {
		ts = t
	} else {
		ts = r.now()
	}
	a := Alarm{
		Code:            rec.Code,
		CoreUnitBoardSn: rec.BoardSn,
		ComponentType:   codeToComponentType(rec.Code),
		Msg:             rec.Msg,
		CreatedAt:       ts,
	}
	return r.svc.SaveAlarm(a)
}

// codeToComponentType 将告警 code 映射为前端 i18n key（cpu/memory/disk/board/chip）。
// 基于 code 而非 AlarmRec.ComponentType（int 1/2 粒度太粗，无法区分 cpu/mem/disk）。
func codeToComponentType(code int) string {
	switch code {
	case pkgalarm.CodeCPURateAlarm, pkgalarm.CodeCPURateRecover:
		return "cpu"
	case pkgalarm.CodeMemRateAlarm, pkgalarm.CodeMemRateRecover:
		return "memory"
	case pkgalarm.CodeDiskRateAlarm, pkgalarm.CodeDiskRateRecover:
		return "disk"
	case pkgalarm.CodeBoardTempAlarm, pkgalarm.CodeBoardTempRecover:
		return "board"
	case pkgalarm.CodeChipTempAlarm, pkgalarm.CodeChipTempRecover,
		pkgalarm.CodeTPURateAlarm, pkgalarm.CodeTPURateRecover:
		return "chip"
	default:
		c := code / 100000
		if c < 0 {
			c = -c
		}
		if c == 2 {
			return "chip"
		}
		return "cpu"
	}
}
