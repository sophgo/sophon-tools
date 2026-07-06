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
