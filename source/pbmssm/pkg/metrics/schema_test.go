package metrics

import (
	"encoding/binary"
	"testing"
)

func TestArchRecordSizeConsistent(t *testing.T) {
	expected := 4 + binary.Size(ArchRecord{})
	if ArchRecordSize() != expected {
		t.Errorf("ArchRecordSize() = %d, want %d", ArchRecordSize(), expected)
	}
}

func TestArchFieldsCountMatchesRecord(t *testing.T) {
	fields := ArchFields()
	wantFields := 1 + binary.Size(ArchRecord{}) / 4 // 1 timestamp + N float32
	if len(fields) != wantFields {
		t.Errorf("ArchFields() len = %d, want %d (= 1 timestamp + %d float32)",
			len(fields), wantFields, binary.Size(ArchRecord{})/4)
	}
}

func TestArchFieldsNoDuplicates(t *testing.T) {
	fields := ArchFields()
	seen := make(map[string]bool, len(fields))
	for _, f := range fields {
		if seen[f] {
			t.Errorf("duplicate field name: %s", f)
		}
		seen[f] = true
	}
}

func TestArchFieldsFirstIsTimestamp(t *testing.T) {
	if ArchFields()[0] != "timestamp" {
		t.Errorf("ArchFields()[0] = %q, want \"timestamp\"", ArchFields()[0])
	}
}

func TestCurrentVersionPositive(t *testing.T) {
	if CurrentVersion == 0 {
		t.Error("CurrentVersion must be positive")
	}
}

func TestHeaderSizeMultipleOf4(t *testing.T) {
	if headerSize%4 != 0 {
		t.Errorf("headerSize = %d, not multiple of 4 (bad for binary alignment)", headerSize)
	}
}

func TestHeaderSizeEnoughForFields(t *testing.T) {
	namesLen := 0
	for _, f := range ArchFields() {
		namesLen += len(f) + 1 // name + NUL
	}
	// 18 = offset of field_names in file header
	if namesLen+18 > headerSize {
		t.Errorf("field_names total %d bytes + 18 offset > headerSize %d, need bigger header",
			namesLen, headerSize)
	}
}

func TestArchRecordSizeConstant(t *testing.T) {
	// 定长：两次调用应返相同值
	s1 := ArchRecordSize()
	s2 := ArchRecordSize()
	if s1 != s2 {
		t.Errorf("ArchRecordSize is not constant: %d vs %d", s1, s2)
	}
	// 当前 schema: 4B timestamp + sizeof(ArchRecord)
	if s1%4 != 0 {
		t.Errorf("ArchRecordSize %d not multiple of 4", s1)
	}
}
