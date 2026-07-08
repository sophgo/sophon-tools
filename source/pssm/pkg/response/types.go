// Package response 提供 ssm 统一 HTTP 响应信封。
//
// 信封原定义在 mvc/compat（SsmResult/SsmOK/SsmErr/SsmErrCode），用于 /bitmain/v1/ssm/*
// 兼容路由。抽出为独立包后，/api/v1/* 正路路由与 compat 兼容路由共用同一信封，
// 避免类型重复，sophliteos 前端只需对齐一份契约。
//
// 成功：Code=0, Msg="请求成功", Result=数据
// 失败：Code=1, Msg="请求失败", ErrorMessage=错误信息
package response

import "ssm/global"

// Result 统一响应信封（原 mvc/compat.SsmResult）。
type Result struct {
	Code         int         `json:"code"`
	Msg          string      `json:"msg"`
	ErrorCode    int         `json:"error_code"`
	ErrorMessage string      `json:"error_message"`
	DeviceSn     string      `json:"deviceSn,omitempty"`
	Result       interface{} `json:"result,omitempty"`
}

// OK 构造成功信封。DeviceSn 取 global.DeviceSnEx
// （sophliteos GetCtrlBasic/GetCtrlResource 从信封取 DeviceSn）。
func OK(result interface{}) Result {
	return Result{
		Code:     0,
		Msg:      "请求成功",
		DeviceSn: global.DeviceSnEx,
		Result:   result,
	}
}

// Fail 构造失败信封。
func Fail(msg string) Result {
	return Result{
		Code:         1,
		Msg:          "请求失败",
		ErrorMessage: msg,
		DeviceSn:     global.DeviceSnEx,
	}
}

// FailCode 构造带错误码的失败信封。
func FailCode(code int, msg string) Result {
	return Result{
		Code:         1,
		Msg:          "请求失败",
		ErrorCode:    code,
		ErrorMessage: msg,
		DeviceSn:     global.DeviceSnEx,
	}
}
