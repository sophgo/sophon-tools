package main

import (
	"archive/zip"
	"bytes"
	"compress/gzip"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const operatorTestTarget int64 = 256 << 20

func operatorTestFile(t *testing.T, dir, name string, payload []byte) string {
	t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, payload, 0600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestOperatorModeDoesNotSwitch(t *testing.T) {
	imgDir, cardDir := t.TempDir(), t.TempDir()
	img := operatorTestFile(t, imgDir, "demo.img", make([]byte, 4096))
	operatorTestFile(t, cardDir, "sdboot/boot.scr", []byte("demo"))
	for _, tc := range []struct {
		mode     taskMode
		input    string
		ok, card bool
	}{
		{modeMakeCard, img, false, false}, {modeMakeCard, imgDir, false, false},
		{modeWriteImage, cardDir, false, false}, {modeWriteImage, imgDir, false, false},
		{modeWriteImage, img, true, false}, {modeMakeCard, cardDir, true, true},
	} {
		got, err := prepareOperatorSource(tc.mode, tc.input, operatorTestTarget, true, "", nil)
		if (err == nil) != tc.ok || (err == nil && got.IsCard() != tc.card) {
			t.Errorf("mode %d, %s: %+v %v", tc.mode, tc.input, got, err)
		}
	}
	p, err := prepareOperatorSource(modeFormatOnly, "ignored.zip", operatorTestTarget, false, "my.card", nil)
	if err != nil || !p.IsFormatOnly() || p.Plan.Label != "MY-CARD" || !strings.Contains(operatorPlanText(&DiskInfo{Size: operatorTestTarget}, p), "MY-CARD") {
		t.Fatalf("format plan: %+v %v", p, err)
	}
	if _, err := prepareOperatorSource(modeFormatOnly, "", 0, false, "", nil); err == nil {
		t.Fatal("unselected target must fail")
	}
}

func TestOperatorBlocksAmbiguousOrMarkerlessCard(t *testing.T) {
	for _, names := range [][]string{{"notes.txt"}, {"a/fip.bin", "b/fip.bin"}, {"recovery-ui/notes.txt"}} {
		dir := t.TempDir()
		for _, n := range names {
			operatorTestFile(t, dir, n, []byte("demo"))
		}
		if p, err := prepareOperatorSource(modeMakeCard, dir, operatorTestTarget, true, "", nil); err == nil {
			t.Errorf("accepted %v: %+v", names, p)
		}
	}
}

func TestOperatorCountsActualCompressedBytes(t *testing.T) {
	var data bytes.Buffer
	for _, n := range []int{1800, 2100} {
		gz := gzip.NewWriter(&data)
		if _, err := gz.Write(make([]byte, n)); err != nil {
			t.Fatal(err)
		}
		if err := gz.Close(); err != nil {
			t.Fatal(err)
		}
	}
	img := operatorTestFile(t, t.TempDir(), "sample.img.gz", data.Bytes())
	p, err := prepareOperatorSource(modeWriteImage, img, 3900, false, "", nil)
	if err != nil || p.TotalSize() != 3900 {
		t.Fatalf("actual gzip size mismatch: %+v %v", p, err)
	}
	if _, err := prepareOperatorSource(modeWriteImage, img, 3899, false, "", nil); err == nil {
		t.Fatal("over-capacity gzip approved")
	}
	nestedTarget := t.TempDir()
	var archive bytes.Buffer
	z := zip.NewWriter(&archive)
	w, err := z.Create("sample.img.gz")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = w.Write(data.Bytes()); err != nil {
		t.Fatal(err)
	}
	if err = z.Close(); err != nil {
		t.Fatal(err)
	}
	nested := operatorTestFile(t, nestedTarget, "nested.zip", archive.Bytes())
	if _, err := prepareOperatorSource(modeWriteImage, nested, 4096, false, "", nil); err == nil {
		t.Fatal("nested compressed entry approved as raw")
	}
}

func TestOperatorSourceBindingUsesOriginalPaths(t *testing.T) {
	dir := t.TempDir()
	real := operatorTestFile(t, dir, "nested/fip.bin", []byte("1234"))
	p, err := prepareOperatorSource(modeMakeCard, dir, operatorTestTarget, true, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	refused := errors.New("on target volume")
	check := func(s string) error {
		if s == real {
			return refused
		}
		return nil
	}
	if _, err := operatorSourceStamps(dir, p, check, nil); !errors.Is(err, refused) {
		t.Fatalf("path check must include original file, got %v", err)
	}
	good := func(string) error { return nil }
	stamps, err := operatorSourceStamps(dir, p, good, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := operatorStampsCurrent(stamps, good); err != nil {
		t.Fatal(err)
	}
	original, err := os.Stat(real)
	if err != nil {
		t.Fatal(err)
	}
	other := operatorTestFile(t, dir, "replacement.tmp", []byte("5678"))
	if err = os.Chtimes(other, time.Now(), original.ModTime()); err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(real); err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(other, real); err != nil {
		t.Fatal(err)
	}
	if err := operatorStampsCurrent(stamps, good); err == nil {
		t.Fatal("same length and timestamp replacement approved")
	}
}

func TestRunFlashDoesNotWriteBeforeGuards(t *testing.T) {
	d := &DiskInfo{Size: operatorTestTarget}
	p, err := PrepareFormat(d.Size, "SE")
	if err != nil {
		t.Fatal(err)
	}
	stop := errors.New("target changed")
	for _, name := range []string{"lock", "open", "readback", "success"} {
		t.Run(name, func(t *testing.T) {
			buf := newFileDisk(t, operatorTestTarget)
			defer buf.Close()
			sentinel := []byte("must-not-write-before-confirmed")
			if _, err := buf.WriteAt(sentinel, 0); err != nil {
				t.Fatal(err)
			}
			writes, unlocked, readback := false, false, false
			policy := flashAccess{
				lock: func(func(string, ...interface{})) (func(), error) {
					if name == "lock" {
						return nil, stop
					}
					return func() { unlocked = true }, nil
				},
				write: func() (DiskDevice, error) {
					if name == "open" {
						return nil, stop
					}
					return buf, nil
				},
				read: func() (DiskDevice, error) {
					readback = true
					if name == "readback" {
						return nil, stop
					}
					f, e := os.Open(buf.Path())
					if e != nil {
						return nil, e
					}
					return &fileDisk{f: f, size: operatorTestTarget}, nil
				},
				beforeWrite: func() { writes = true },
			}
			result, err := runFlash(d, p, true, nil, nil, policy)
			if name == "success" {
				if err != nil || !result.OK() || !writes || !readback || !unlocked {
					t.Fatalf("successful write/verify/release order: %v %v %v %v", err, writes, readback, unlocked)
				}
				return
			}
			if name == "lock" || name == "open" {
				before := make([]byte, len(sentinel))
				if _, err := buf.ReadAt(before, 0); err != nil || !bytes.Equal(before, sentinel) {
					t.Fatal("guard failure modified disk")
				}
			}
			if !errors.Is(err, stop) || writes != (name == "readback") || readback != (name == "readback") || unlocked != (name != "lock") {
				t.Fatalf("guard ordering: %v %v %v %v", err, writes, readback, unlocked)
			}
		})
	}
}
