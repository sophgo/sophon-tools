package ota

import "strings"

// productClass 按 Product 名称映射设备模式。
//
//	SE5/SE7/SE9（及小写）→ SOC
//	SC5/SC7（及小写）   → PCIE
//	SE6/SE8（及小写）   → MultiNode
func productClass(product string) ProductClass {
	p := strings.ToLower(strings.TrimSpace(product))
	switch p {
	case "se5", "se7", "se9":
		return ClassSOC
	case "sc5", "sc7":
		return ClassPCIE
	case "se6", "se8":
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
