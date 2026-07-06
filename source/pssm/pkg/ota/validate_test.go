package ota

import "testing"

func TestValidateCmdFlag(t *testing.T) {
	cases := []struct {
		cmd     string
		wantErr bool
	}{
		// 白名单命令通过
		{"", false},
		{"/data/ota/local_update.sh", false},
		{"/data/ota/local_update.sh md5.txt 0", false},
		{"/data/ota/local_update.sh arg1 arg2", false},
		{"bm_firmware_update", false},
		{"bm_firmware_update --dev=0xff --target=a53", false},
		{"mk_bootscr.sh", false},
		{"ssh root@192.168.1.10 mk_bootscr.sh", false},
		{"bash /data/ota/local_update.sh", false},

		// 注入攻击拒绝
		{"rm -rf /", true},
		{"/data/ota/local_update.sh; rm -rf /", true},
		{"/data/ota/local_update.sh | cat /etc/passwd", true},
		{"/data/ota/local_update.sh & whoami", true},
		{"/data/ota/local_update.sh `id`", true},
		{"/data/ota/local_update.sh $(whoami)", true},
		{"bm_firmware_update; echo hacked", true},
		{"; /data/ota/local_update.sh", true},
		{"| cat /etc/shadow", true},
		{"/bin/sh", true},
		{"/custom/upgrade.sh arg1", true},
		{"echo 'multinode core upgrade'", true},
	}

	for _, tt := range cases {
		err := validateCmdFlag(tt.cmd)
		if (err != nil) != tt.wantErr {
			if tt.wantErr {
				t.Errorf("validateCmdFlag(%q) = nil, want error", tt.cmd)
			} else {
				t.Errorf("validateCmdFlag(%q) = %v, want nil", tt.cmd, err)
			}
		}
	}
}

func TestValidatePCIECmdFlag(t *testing.T) {
	cases := []struct {
		cmd     string
		wantErr bool
	}{
		// 已知 flag 通过
		{"", false},
		{"--full", false},
		{"--target=a53", false},
		{"--target=mcu", false},
		{"--file=/data/ota/fw.bin", false},
		{"--full --target=a53", false},
		{"--target=mcu --full", false},
		{"--full --target=a53 --file=/data/ota/fw.bin", false},

		// 非法 flag 拒绝
		{"--evil", true},
		{"--target=evil", true},
		{"--target=", true},
		{"rm -rf /", true},
		{"--full; rm -rf /", true},
		{"| cat /etc/passwd", true},
		{"--full --evil", true},
	}

	for _, tt := range cases {
		err := validatePCIECmdFlag(tt.cmd)
		if (err != nil) != tt.wantErr {
			if tt.wantErr {
				t.Errorf("validatePCIECmdFlag(%q) = nil, want error", tt.cmd)
			} else {
				t.Errorf("validatePCIECmdFlag(%q) = %v, want nil", tt.cmd, err)
			}
		}
	}
}
