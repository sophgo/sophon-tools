package ports

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseIPv4(t *testing.T) {
	if got := parseIPv4("0100007F"); got != "127.0.0.1" {
		t.Fatalf("got %q want 127.0.0.1", got)
	}
	if got := parseIPv4("00000000"); got != "0.0.0.0" {
		t.Fatalf("got %q want 0.0.0.0", got)
	}
}

func TestParseProcNetTCP(t *testing.T) {
	// 一行 LISTEN(state 0A) inode=12345，一行 ESTABLISHED(state 01) 应被跳过
	content := "  sl  local_address rem_address   st\n" +
		"   0: 0100007F:1A0B 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1\n" +
		"   1: 0100007F:1A0B 0A01010A:0050 01 00000000:00000000 00:00000000 00000000     0        0 99999 1\n"
	socks := parseProcNet(content, "tcp")
	if len(socks) != 1 {
		t.Fatalf("len=%d want 1 (ESTABLISHED 应跳过)", len(socks))
	}
	s := socks[0]
	if s.LocalIP != "127.0.0.1" || s.LocalPort != 0x1A0B || s.Inode != 12345 {
		t.Fatalf("sock=%+v", s)
	}
}

func TestParseProcNetUDP(t *testing.T) {
	content := "  sl  local_address rem_address   st\n" +
		"   0: 00000000:0035 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 777 1\n"
	socks := parseProcNet(content, "udp")
	if len(socks) != 1 {
		t.Fatalf("UDP 应列出全部，len=%d", len(socks))
	}
	if socks[0].Inode != 777 || socks[0].LocalPort != 0x35 {
		t.Fatalf("sock=%+v", socks[0])
	}
}

func TestListListeningAt(t *testing.T) {
	root := t.TempDir()
	// /proc/net/tcp：一个 LISTEN socket，inode 12345
	tcp := "  sl  local_address rem_address   st\n" +
		"   0: 0100007F:1A0B 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1\n"
	if err := os.MkdirAll(filepath.Join(root, "net"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "net", "tcp"), []byte(tcp), 0o644); err != nil {
		t.Fatal(err)
	}
	// /proc/9779/fd/3 -> socket:[12345]
	pidDir := filepath.Join(root, "9779", "fd")
	if err := os.MkdirAll(pidDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("socket:[12345]", filepath.Join(pidDir, "3")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "9779", "comm"), []byte("bmssm\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "9779", "cmdline"), []byte("bmssm\x00--config\x00/opt/x\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	socks, err := ListListeningAt(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(socks) != 1 {
		t.Fatalf("len=%d want 1", len(socks))
	}
	s := socks[0]
	if s.Pid != 9779 || s.Process != "bmssm" || s.Cmdline != "bmssm --config /opt/x" {
		t.Fatalf("sock=%+v", s)
	}
}
