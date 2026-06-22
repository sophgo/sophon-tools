package database

import (
	"time"

	"github.com/jinzhu/gorm"
)

type User struct {
	gorm.Model
	UserID     string    `gorm:"column:user_id;primary_key" json:"userId,omitempty"`
	Status     string    `gorm:"column:status" json:"status,omitempty"`
	UserName   string    `gorm:"column:user_name;not null;unique" json:"userName,omitempty"`
	Password   string    `gorm:"column:password" json:"password,omitempty"`
	Token      string    `gorm:"column:token" json:"token,omitempty"`
	Address    string    `gorm:"column:address" json:"address,omitempty"`
	Role       string    `gorm:"column:role" json:"role,omitempty"`
	LoginTime  time.Time `gorm:"column:login_time" json:"omitempty"`
	LockedTime time.Time `gorm:"column:locked_time" json:"locked_time,omitempty"`
	ExpireTime time.Time `gorm:"column:expire_time" json:"expire_time,omitempty"`
	Label      string    `gorm:"column:label" json:"label,omitempty"`
}

type AlarmRec struct {
	DeviceSn      string `json:"deviceSn"`
	ComponentType int    `json:"componentType"`
	ChipSn        string `json:"chipSn"`
	DiskName      string `json:"diskName"`
	BoardSn       string `json:"boardSn"`
	DateTime      string `json:"dateTime"`
	Code          int    `json:"code"`
	Msg           string `json:"msg"`
}

type Alarm struct {
	ID                  uint      `gorm:"primary_key"`
	CreatedAt           time.Time `gorm:"column:created_at" json:"dataTime"`
	DeviceSn            string    `gorm:"column:device_sn" json:"deviceSn"`
	DeviceIp            string    `gorm:"column:device_ip" json:"deviceIp"`
	ComponentType       string    `gorm:"column:component_type" json:"componentType"`
	ControllerUnitSn    string    `gorm:"column:controller_unit_sn" json:"contorllerUnitSn,omitempty"`
	CoreUnitBoardSn     string    `gorm:"column:core_unit_board_sn" json:"coreUnitBoardSn,omitempty"`
	CoreUnitBoardChipSn string    `gorm:"column:core_unit_board_chip_sn" json:"coreUnitBoardChipSn,omitempty"`
	Code                int       `gorm:"column:code" json:"code"`
	Msg                 string    `gorm:"column:msg" json:"msg"`
}

type OptLog struct {
	Id               int       `gorm:"primary_key" json:"recordId"`
	UserName         string    `gorm:"column:user_name" json:"userName"`
	CreatedTime      time.Time `gorm:"column:created_time" json:"dataTime"`
	OperationType    string    `gorm:"column:operation_type" json:"operationType"`
	OperationContent string    `gorm:"column:operation_content" json:"operationContent"`
	OperationIP      string    `gorm:"column:operation_ip" json:"operationIp"`
	OperationFunc    string    `gorm:"column:operation_func" json:"operationFunc"`
}
