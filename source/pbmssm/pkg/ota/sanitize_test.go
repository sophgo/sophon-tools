package ota

import "testing"

func TestSanitizeFileName(t *testing.T) {
	cases := []struct {
		name string
		want string
	}{
		// 合法文件名
		{"fw.bin", "fw.bin"},
		{"fw.tgz", "fw.tgz"},
		{"firmware.tar.gz", "firmware.tar.gz"},
		{"a53_firmware_v2.0.bin", "a53_firmware_v2.0.bin"},
		{"a", "a"},
		{"A-B_C.0-9", "A-B_C.0-9"},

		// 路径穿越拒绝（含路径分隔符）
		{"../../etc/passwd", ""},
		{"../bootrom/fw.bin", ""},
		{"/etc/shadow", ""},
		{"./fw.bin", ""},
		{"fw.bin/../secret", ""},
		{"..", ""},
		{".", ""},

		// 特殊字符拒绝
		{"fw;rm -rf", ""},
		{"fw|cat /etc/passwd", ""},
		{"fw&whoami", ""},
		{"fw`id`", ""},
		{"fw$(id)", ""},
		{"fw\n.bin", ""},

		// 边界
		{"", ""},
		{"fw space.bin", ""}, // 空格非法
		{"fw\t.bin", ""},     // tab 非法
	}

	for _, tt := range cases {
		got := sanitizeFileName(tt.name)
		if got != tt.want {
			t.Errorf("sanitizeFileName(%q) = %q, want %q", tt.name, got, tt.want)
		}
	}
}

func TestSanitizeFileNameLength(t *testing.T) {
	// 超过 255 字符应返回空
	long := ""
	for i := 0; i < 260; i++ {
		long += "a"
	}
	if got := sanitizeFileName(long); got != "" {
		t.Errorf("sanitizeFileName(long) = %q, want empty", got)
	}
	// 刚好 255 应通过
	ok := ""
	for i := 0; i < 255; i++ {
		ok += "a"
	}
	if got := sanitizeFileName(ok); got == "" {
		t.Errorf("sanitizeFileName(255) = empty, want non-empty")
	}
}
