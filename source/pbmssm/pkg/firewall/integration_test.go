//go:build integration

package firewall

import (
	"os"
	"strings"
	"testing"

	"bmssm/database"

	"github.com/jinzhu/gorm"
	_ "github.com/mattn/go-sqlite3"
)

// testDBIntegration creates a temporary SQLite database, runs InitDB+Migrate
// (models are registered by persist.go's init()), and returns the handle.
// Cleanup closes the DB on test completion.
func testDBIntegration(t *testing.T) *gorm.DB {
	t.Helper()
	dir := t.TempDir()
	dbPath := dir + "/fwtest.db"
	db, err := database.InitDB(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := database.Migrate(db); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// TestIntegrationApplyRollback is a manual integration test that requires
// root privileges and a working iptables installation.  Run with:
//
//	cd source/pbmssm && sudo go test -tags=integration ./pkg/firewall/ -v -run TestIntegrationApplyRollback
//
// The test verifies the full apply-to-live-iptables-then-rollback cycle.
func TestIntegrationApplyRollback(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("need root")
	}

	db := testDBIntegration(t)
	r := SystemRunner{}

	// Clean up any leftover managed rules from previous runs.
	CleanManaged(r)

	// Verify clean starting state: no bmssm-fw-intent rules in iptables.
	rules, err := ListFilter(r)
	if err != nil {
		t.Fatalf("ListFilter failed: %v", err)
	}
	for _, rule := range rules {
		if strings.Contains(rule.Raw, CommentIntentPrefix) {
			t.Fatalf("pre-existing intent rule found, cannot start clean: %+v", rule)
		}
	}

	// Safety net: ensure no leftover managed rules on test exit.
	defer CleanManaged(r)

	// Create a port_allow intent for tcp/8080.
	it := Intent{Type: IntentPortAllow, Params: `{"proto":"tcp","port":8080}`, Enabled: true}
	if err := SaveIntent(db, &it); err != nil {
		t.Fatal(err)
	}
	defer func() { DeleteIntent(db, it.ID) }()

	// Apply with force=true to bypass risk detection.
	a := NewApplier(db, r)
	res, err := a.Apply(true)
	if err != nil {
		t.Fatalf("Apply failed: %v", err)
	}
	t.Logf("Applied token=%s, rollbackSeconds=%d", res.Token, res.RollbackSeconds)

	// Verify the intent rule exists in live iptables.
	rules, err = ListFilter(r)
	if err != nil {
		t.Fatalf("ListFilter after Apply failed: %v", err)
	}

	found := false
	for _, rule := range rules {
		if strings.Contains(rule.Raw, CommentIntentPrefix) {
			found = true
			t.Logf("Found intent rule: target=%s num=%d raw=%s", rule.Target, rule.Num, rule.Raw)
			break
		}
	}
	if !found {
		t.Error("intent rule not found in live iptables after Apply")
	}

	// Rollback to the snapshot taken before Apply.
	if err := a.Rollback(res.Token); err != nil {
		t.Fatalf("Rollback failed: %v", err)
	}

	// Verify the intent rule is gone after rollback.
	rulesAfter, err := ListFilter(r)
	if err != nil {
		t.Fatalf("ListFilter after rollback failed: %v", err)
	}

	for _, rule := range rulesAfter {
		if strings.Contains(rule.Raw, CommentIntentPrefix) {
			t.Errorf("intent rule still found in live iptables after Rollback: %+v", rule)
			return
		}
	}
	t.Log("integration test PASS: apply -> rule verified -> rollback -> rule absent")
}
