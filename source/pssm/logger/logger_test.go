package logger

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestInitLoggingCreatesFile(t *testing.T) {
	dir := t.TempDir()
	InitLogging(dir, "ssm.log", "debug")
	Info("hello %s", "world")
	_sync()

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read dir: %v", err)
	}
	if len(entries) == 0 {
		t.Fatal("expected log file created")
	}
	data, _ := os.ReadFile(filepath.Join(dir, "ssm.log"))
	if !strings.Contains(string(data), "hello world") {
		t.Fatalf("log missing message, got: %s", string(data))
	}
}

func TestParseLevel(t *testing.T) {
	if parseLevel("error") != zapErrorLevel {
		t.Fatal("error level mismatch")
	}
	if parseLevel("nonsense") != zapInfoLevel {
		t.Fatal("default should be info")
	}
}