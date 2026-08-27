package metrics

import "testing"

func TestChipCapacity(t *testing.T) {
	tests := []struct {
		name             string
		chipModel        string
		wantCalcCapacity float64
		wantChipType     int
	}{
		{
			name:             "BM1684X from SE7",
			chipModel:        "BM1684X",
			wantCalcCapacity: 32,
			wantChipType:     2,
		},
		{
			name:             "BM1688",
			chipModel:        "BM1688",
			wantCalcCapacity: 16,
			wantChipType:     3,
		},
		{
			name:             "BM1684 non-X",
			chipModel:        "BM1684",
			wantCalcCapacity: 16,
			wantChipType:     1,
		},
		{
			name:             "empty string defaults to 16/1",
			chipModel:        "",
			wantCalcCapacity: 16,
			wantChipType:     1,
		},
		{
			name:             "lowercase bm1684x",
			chipModel:        "bm1684x",
			wantCalcCapacity: 32,
			wantChipType:     2,
		},
		{
			name:             "lowercase bm1688",
			chipModel:        "bm1688",
			wantCalcCapacity: 16,
			wantChipType:     3,
		},
		{
			name:             "lowercase bm1684",
			chipModel:        "bm1684",
			wantCalcCapacity: 16,
			wantChipType:     1,
		},
		{
			name:             "unknown chip defaults to 16/1",
			chipModel:        "SomeUnknownChip",
			wantCalcCapacity: 16,
			wantChipType:     1,
		},
		{
			name:             "substring 1686 match",
			chipModel:        "SOPHON_BM1686_DEV",
			wantCalcCapacity: 32,
			wantChipType:     2,
		},
		{
			name:             "1684X substring in longer name",
			chipModel:        "BM1684X-V2-PROD",
			wantCalcCapacity: 32,
			wantChipType:     2,
		},
		{
			name:             "CV84X6",
			chipModel:        "CV84X6",
			wantCalcCapacity: 64,
			wantChipType:     3,
		},
		{
			name:             "lowercase cv84x6",
			chipModel:        "cv84x6",
			wantCalcCapacity: 64,
			wantChipType:     3,
		},
		{
			name:             "84X6 substring",
			chipModel:        "CV84X6-PROD",
			wantCalcCapacity: 64,
			wantChipType:     3,
		},
		{
			// CV84X2 与 CV84X6 为同一芯片的不同称呼（设备侧命名链输出 CV84X2）
			name:             "CV84X2 (display name)",
			chipModel:        "CV84X2",
			wantCalcCapacity: 64,
			wantChipType:     3,
		},
		{
			name:             "lowercase cv84x2",
			chipModel:        "cv84x2",
			wantCalcCapacity: 64,
			wantChipType:     3,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotCalc, gotType := ChipCapacity(tt.chipModel)
			if gotCalc != tt.wantCalcCapacity {
				t.Errorf("ChipCapacity(%q) calcCapacity = %v, want %v", tt.chipModel, gotCalc, tt.wantCalcCapacity)
			}
			if gotType != tt.wantChipType {
				t.Errorf("ChipCapacity(%q) chipType = %d, want %d", tt.chipModel, gotType, tt.wantChipType)
			}
		})
	}
}

// TestFpCapacityCv84x6 官方规格：cv84x6 FP16=32、FP32=2；其他芯片走 /4 /8 派生。
func TestFpCapacityCv84x6(t *testing.T) {
	if got := Fp16Capacity("cv84x6", 64); got != 32 {
		t.Errorf("Fp16Capacity(cv84x6) = %v, want 32", got)
	}
	if got := Fp32Capacity("cv84x6", 64); got != 2 {
		t.Errorf("Fp32Capacity(cv84x6) = %v, want 2", got)
	}
	if got := Fp16Capacity("BM1684X", 32); got != 8 {
		t.Errorf("Fp16Capacity(BM1684X) = %v, want 8 (历史派生 /4)", got)
	}
	if got := Fp32Capacity("bm1688", 16); got != 2 {
		t.Errorf("Fp32Capacity(bm1688) = %v, want 2 (历史派生 /8)", got)
	}
}
