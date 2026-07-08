package system

import (
	"os"
	"testing"
)

func TestPathExistsTrue(t *testing.T) {
	f, _ := os.CreateTemp("", "ex")
	defer os.Remove(f.Name())
	ok, err := PathExists(f.Name())
	if err != nil || !ok {
		t.Fatalf("expected exist, ok=%v err=%v", ok, err)
	}
}

func TestPathExistsFalse(t *testing.T) {
	ok, err := PathExists("/no/such/path/zzz")
	if err != nil || ok {
		t.Fatalf("expected not exist, ok=%v err=%v", ok, err)
	}
}

func TestRunCommand(t *testing.T) {
	out, errStr, err := RunCommand("echo hello")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if out != "hello\n" {
		t.Fatalf("unexpected out: %q", out)
	}
	if errStr != "" {
		t.Fatalf("unexpected errStr: %q", errStr)
	}
}