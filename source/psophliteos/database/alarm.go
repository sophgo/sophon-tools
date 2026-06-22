package database

import (
	"sophliteos/mvc/types"
	"time"
)

// 保存告警
func SaveAlarm(alarm Alarm) error {
	db := DB.Model(&Alarm{}).Save(&alarm)
	if err := db.Error; err != nil {
		return err
	}
	return nil
}

// 查询告警
func QueryAlarms(alarm *Alarm, pageNo, pageSize int, startTime, endTime *time.Time) types.Page {
	alarms := make([]Alarm, 0)
	db := DB.Model(&Alarm{})
	var vars []interface{}
	var query = ""
	if alarm.Code != 0 {
		query = query + " and code = ? "
		vars = append(vars, alarm.Code)
	}
	if len(alarm.Msg) > 0 {
		query = query + " and msg like ? "
		vars = append(vars, "%"+alarm.Msg+"%")
	}
	if len(alarm.DeviceSn) > 0 {
		query = query + " and device_sn = ? "
		vars = append(vars, alarm.DeviceSn)
	}
	if len(alarm.ComponentType) > 0 {
		query = query + " and component_type = ? "
		vars = append(vars, alarm.ComponentType)
	}
	if len(alarm.ControllerUnitSn) > 0 {
		query = query + " and controller_unit_sn = ? "
		vars = append(vars, alarm.ControllerUnitSn)
	}
	if len(alarm.CoreUnitBoardSn) > 0 {
		query = query + " and core_unit_board_sn = ? "
		vars = append(vars, alarm.CoreUnitBoardSn)
	}
	if len(alarm.CoreUnitBoardChipSn) > 0 {
		query = query + " and core_unit_board_chip_sn = ? "
		vars = append(vars, alarm.CoreUnitBoardChipSn)
	}
	if startTime != nil {
		query = query + " and created_at >= ?  "
		vars = append(vars, &startTime)
	}
	if endTime != nil {
		query = query + " and created_at <= ?  "
		vars = append(vars, &endTime)
	}
	var total int
	if len(query) > 0 {
		db.Where(query[4:], vars...).Count(&total)
		db.Where(query[4:], vars...).Offset((pageNo - 1) * pageSize).Limit(pageSize).Order("created_at desc").Find(&alarms)
	} else {
		db.Count(&total)
		db.Offset((pageNo - 1) * pageSize).Limit(pageSize).Order("created_at desc").Find(&alarms)
	}

	return types.Page{
		PageCount: (total + pageSize - 1) / pageSize,
		PageNo:    pageNo,
		PageSize:  pageSize,
		Total:     total,
		Items:     alarms,
	}
}

// 删除日期前数据
func DeleteAlarmByCreatedAt(createdAt time.Time) error {
	db := DB.Model(&Alarm{}).Debug().Where(" created_time <= ? ", createdAt).Delete(&Alarm{})
	if err := db.Error; err != nil {
		return err
	}
	return nil
}
