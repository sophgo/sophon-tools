package database

import (
	"sophliteos/mvc/types"
	"time"
)

// 保存告警
func SaveOptLog(optLog OptLog) error {
	db := DB.Model(&OptLog{}).Save(&optLog)
	if err := db.Error; err != nil {
		return err
	}
	return nil
}

// 查询告警
func QueryOptLogs(optLog *OptLog, pageNo, pageSize int, startTime, endTime *time.Time) types.Page {
	rows := make([]OptLog, 0)
	db := DB.Model(&OptLog{})
	var vars []interface{}
	var query = ""
	if len(optLog.OperationType) > 0 {
		query = query + " and operation_type = ? "
		vars = append(vars, optLog.OperationType)
	}
	if len(optLog.OperationIP) > 0 {
		query = query + " and operation_ip like ? "
		vars = append(vars, "%"+optLog.OperationIP+"%")
	}
	if len(optLog.OperationContent) > 0 {
		query = query + " and operation_content like ? "
		vars = append(vars, "%"+optLog.OperationContent+"%")
	}
	if len(optLog.UserName) > 0 {
		query = query + " and user_name = ? "
		vars = append(vars, optLog.UserName)
	}
	if startTime != nil {
		query = query + " and created_time >= ?  "
		vars = append(vars, &startTime)
	}
	if endTime != nil {
		query = query + " and created_time <= ?  "
		vars = append(vars, &endTime)
	}
	var total int
	if len(query) > 0 {
		db.Where(query[4:], vars...).Count(&total)
		db.Where(query[4:], vars...).Offset((pageNo - 1) * pageSize).Limit(pageSize).Order("created_time desc").Find(&rows)
	} else {
		db.Count(&total)
		db.Offset((pageNo - 1) * pageSize).Limit(pageSize).Order("created_time desc").Find(&rows)
	}
	return types.Page{
		PageCount: (total + pageSize - 1) / pageSize,
		PageNo:    pageNo,
		PageSize:  pageSize,
		Total:     total,
		Items:     rows,
	}
}

// 删除日期前数据
func DeleteOptLogByCreatedAt(createdAt time.Time) error {
	db := DB.Model(&OptLog{}).Debug().Where(" created_time <= ? ", createdAt).Delete(&OptLog{})
	if err := db.Error; err != nil {
		return err
	}
	return nil
}
