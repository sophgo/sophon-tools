package global

import "testing"

func TestVersionString(t *testing.T) {
	bi := BuildInfo{Version: "1.0.0", GitCommit: "abc", BuildTime: "2026-01-01"}
	got := bi.String()
	if got != "1.0.0 (abc @ 2026-01-01)" {
		t.Fatalf("got %q", got)
	}
}

func TestVersionDefaults(t *testing.T) {
	if Version.Version != "dev" {
		t.Fatalf("expected dev, got %q", Version.Version)
	}
}