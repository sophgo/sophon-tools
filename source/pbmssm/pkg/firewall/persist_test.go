package firewall

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSnapshot(t *testing.T) {
	r := &fakeRunner{outs: map[string]string{"iptables-save -t filter": "*filter\n-A INPUT -j ACCEPT\nCOMMIT\n"}}
	snap, err := Snapshot(r)
	if err != nil {
		t.Fatalf("Snapshot: %v", err)
	}
	if !strings.Contains(snap, "COMMIT") {
		t.Errorf("snapshot content: %q", snap)
	}
}

func TestSnapshotError(t *testing.T) {
	r := &fakeRunner{errs: map[string]error{"iptables-save -t filter": errors.New("boom")}}
	if _, err := Snapshot(r); err == nil {
		t.Fatal("want error when iptables-save fails")
	}
}

func TestRestore(t *testing.T) {
	var gotPath string
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		if name == "iptables-restore" {
			gotPath = args[0]
			data, err := os.ReadFile(gotPath)
			if err != nil {
				t.Errorf("restore file unreadable: %v", err)
			}
			if string(data) != "*filter\nCOMMIT\n" {
				t.Errorf("restore content: %q", string(data))
			}
			return "", "", nil
		}
		return "", "", nil
	}
	if err := Restore(r, "*filter\nCOMMIT\n"); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	if gotPath == "" {
		t.Fatal("iptables-restore was not invoked")
	}
	if _, err := os.Stat(gotPath); !os.IsNotExist(err) {
		t.Error("restore temp file should be removed after use")
	}
}

func TestRestoreFailure(t *testing.T) {
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		if name == "iptables-restore" {
			return "", "iptables-restore: line 1 failed", errors.New("exit status 2")
		}
		return "", "", nil
	}
	if err := Restore(r, "*filter\nCOMMIT\n"); err == nil {
		t.Fatal("want error when iptables-restore fails")
	}
}

func TestPersistRules(t *testing.T) {
	r := &fakeRunner{outs: map[string]string{"iptables-save ": "*filter\nCOMMIT\n"}}
	path := filepath.Join(t.TempDir(), "rules.v4")
	if err := PersistRules(r, path); err != nil {
		t.Fatalf("PersistRules: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read persisted: %v", err)
	}
	if string(data) != "*filter\nCOMMIT\n" {
		t.Errorf("persisted content: %q", string(data))
	}
}

func TestPersistRulesError(t *testing.T) {
	r := &fakeRunner{errs: map[string]error{"iptables-save ": errors.New("boom")}}
	if err := PersistRules(r, filepath.Join(t.TempDir(), "rules.v4")); err == nil {
		t.Fatal("want error when iptables-save fails")
	}
}
