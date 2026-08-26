package metrics

import "strings"

// ChipCapacity returns the calculation capacity (INT8 TOPS) and chip type
// based on the chip model string. The lookup is case-insensitive and aligns
// with the bmssm bmlib Chipid table:
//
//	BM1684X (0x1686)      → 32 TOPS, chipType 2
//	BM1688  (0x1688)      → 16 TOPS, chipType 3
//	CV84X6/CV84X2 (0x1694) → 16 TOPS, chipType 3  (占位，对齐 BM1688 档位；真机确认后修正)
//	BM1684  (non-X)       → 16 TOPS, chipType 1
//	unknown / empty       → 16 TOPS, chipType 1  (bmssm default branch)
//
// This is a pure function with no side effects — safe to call from any goroutine.
func ChipCapacity(chipModel string) (calcCapacity float64, chipType int) {
	upper := strings.ToUpper(chipModel)
	switch {
	case strings.Contains(upper, "84X6"), strings.Contains(upper, "84X2"):
		// CV84X2 与 CV84X6 为同一芯片的不同称呼，同一档位
		return 16, 3
	case strings.Contains(upper, "1686") || strings.Contains(upper, "1684X"):
		return 32, 2
	case strings.Contains(upper, "1688"):
		return 16, 3
	case strings.Contains(upper, "1684"):
		return 16, 1
	default:
		return 16, 1
	}
}
