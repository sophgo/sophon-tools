package ota

import (
	_ "embed"
	"os"
	"path/filepath"
)

//go:embed assets/ota.sh
var otaScript []byte

//go:embed assets/arm64_bin/bc
var bcBinary []byte

// WriteAssets writes the embedded ota.sh and arm64_bin/bc into dir, matching the
// layout expected by pota_update (ota.sh at dir root, bc at dir/arm64_bin/bc).
// Both files are written executable (0755). It is a no-op overwrite if the files
// already exist with the same content.
func WriteAssets(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "ota.sh"), otaScript, 0o755); err != nil {
		return err
	}
	bcDir := filepath.Join(dir, "arm64_bin")
	if err := os.MkdirAll(bcDir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(bcDir, "bc"), bcBinary, 0o755)
}
