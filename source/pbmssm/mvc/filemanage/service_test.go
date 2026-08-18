package filemanage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestResolvePathSymlinkBypass symlink 指向被禁前缀时读路径也拒绝（blocklist 不可绕过）。
func TestResolvePathSymlinkBypass(t *testing.T) {
	dir := t.TempDir()
	link := filepath.Join(dir, "proc-link")
	if err := os.Symlink("/proc", link); err != nil {
		t.Fatal(err)
	}
	if _, err := ResolvePath(filepath.Join(link, "cpuinfo")); err == nil {
		t.Fatal("expected refusal for symlink into /proc")
	}
}

// TestResolvePathReadAllowed 读操作允许访问关键系统目录（/etc）。
func TestResolvePathReadAllowed(t *testing.T) {
	if !isUnder(filepath.Clean("/etc"), readonlyPrefixes) {
		t.Fatal("/etc not in readonly list?")
	}
	p, err := ResolvePath("/etc/hostname")
	if err != nil {
		t.Fatalf("read /etc should be allowed: %v", err)
	}
	if !strings.HasPrefix(p, "/etc/") {
		t.Fatalf("resolved=%q, want /etc/hostname", p)
	}
}

// TestResolveWritePathReadonly 写操作拒绝关键系统目录。
func TestResolveWritePathReadonly(t *testing.T) {
	for _, p := range readonlyPrefixes {
		// /etc 下文件可能不存在（如 /etc/not-exist），前缀检查在 stat 之前，仍应拒绝
		if _, err := ResolveWritePath(filepath.Join(p, "x")); err == nil {
			t.Errorf("write to %s/x should be refused", p)
		}
		if _, err := ResolveWritePath(p); err == nil {
			t.Errorf("write to %s itself should be refused", p)
		}
	}
	// readonly 前缀下不存在路径的父段解析（/var/log/custom/child 中 /var/log/custom 不存在）
	if _, err := ResolveWritePath("/var/log/custom/child"); err == nil {
		t.Errorf("write to /var/log/custom/child should be refused")
	}
}

// TestResolveWritePathSymlinkBypass 通过 writable 目录下 symlink 指向 /etc 的写路径拒绝。
func TestResolveWritePathSymlinkBypass(t *testing.T) {
	dir := t.TempDir()
	link := filepath.Join(dir, "etc-link")
	if err := os.Symlink("/etc", link); err != nil {
		t.Fatal(err)
	}
	// 删除/etc 内文件：/tmp/x/etc-link/passwd 归一化到 /etc/passwd → 拒绝
	if _, err := ResolveWritePath(filepath.Join(link, "passwd")); err == nil {
		t.Fatal("expected refusal for symlink write into /etc")
	}
}

// TestResolveWritePathNonExistentParent 新建路径（父目录存在）正常解析。
func TestResolveWritePathNonExistentParent(t *testing.T) {
	dir := t.TempDir()
	p, err := ResolveWritePath(filepath.Join(dir, "new", "dir"))
	if err != nil {
		t.Fatalf("new dir under temp dir should be allowed: %v", err)
	}
	if !strings.HasPrefix(p, dir) {
		t.Fatalf("resolved=%q, want prefix %q", p, dir)
	}
}

// isUnder 判断 abs 是否位于 readonly 列表任一前缀下（测试辅助，镜像生产逻辑）。
func isUnder(abs string, list []string) bool {
	for _, p := range list {
		if abs == p || strings.HasPrefix(abs, p+"/") {
			return true
		}
	}
	return false
}
