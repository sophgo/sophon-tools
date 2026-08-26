package ota

import "strings"

// productClass 按 Product 名称映射设备模式。
//
//	SE5/SE7/SE9/SE13（及小写、含后缀如 "SE7 V01"）→ SOC
//	SC5/SC7（及小写、含后缀）            → PCIE
//	SE6/SE8（及小写、含后缀）             → MultiNode
//
// 用前缀匹配而非精确匹配，兼容 global.DeviceTypeEx 形如 "SE7 V01" 的完整型号串。
// SE13（CV84X2 单板）为 SOC 设备；刷机走通用 pota_update .tgz + ota.sh 流程，
// 刷机包由 pota_update 侧按芯片打包，bmssm 层芯片无关（真机刷机未在本任务验证）。
func productClass(product string) ProductClass {
	p := strings.ToLower(strings.TrimSpace(product))
	switch {
	case strings.HasPrefix(p, "se5"), strings.HasPrefix(p, "se7"), strings.HasPrefix(p, "se9"), strings.HasPrefix(p, "se13"):
		return ClassSOC
	case strings.HasPrefix(p, "sc5"), strings.HasPrefix(p, "sc7"):
		return ClassPCIE
	case strings.HasPrefix(p, "se6"), strings.HasPrefix(p, "se8"):
		return ClassMultiNode
	}
	return ClassUnknown
}

// runCmd 按 Product 分发到对应刷机实现。
func (e *Engine) runCmd(flow Workflow) error {
	switch productClass(flow.Product) {
	case ClassSOC:
		return e.runSOC(flow)
	case ClassPCIE:
		return e.runPCIE(flow)
	case ClassMultiNode:
		return e.runMultiNode(flow)
	default:
		return errNotImplemented
	}
}
