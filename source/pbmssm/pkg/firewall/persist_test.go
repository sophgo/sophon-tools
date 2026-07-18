package firewall

import (
	"os"
	"testing"

	"bmssm/database"

	"github.com/jinzhu/gorm"
	_ "github.com/mattn/go-sqlite3"
)

func testDB(t *testing.T) *gorm.DB {
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

func TestIntentCRUD(t *testing.T) {
	db := testDB(t)
	it := Intent{Type: "port_allow", Params: `{"proto":"tcp","port":80}`, Enabled: true}
	if err := SaveIntent(db, &it); err != nil {
		t.Fatal(err)
	}
	if it.ID == 0 {
		t.Error("ID not set")
	}
	list, err := ListIntents(db)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 {
		t.Fatalf("got %d", len(list))
	}
	if err := DeleteIntent(db, it.ID); err != nil {
		t.Fatal(err)
	}
	list, _ = ListIntents(db)
	if len(list) != 0 {
		t.Error("delete failed")
	}
}

func TestDockerRuleCRUD(t *testing.T) {
	db := testDB(t)
	d := DockerRule{Scene: "ext_to_container", Params: `{"container_port":8080,"proto":"tcp","src":"10.0.0.0/8","action":"allow"}`, Enabled: true}
	if err := SaveDockerRule(db, &d); err != nil {
		t.Fatal(err)
	}
	if d.ID == 0 {
		t.Error("ID not set")
	}
	list, err := ListDockerRules(db)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 {
		t.Fatalf("got %d", len(list))
	}
	if err := DeleteDockerRule(db, d.ID); err != nil {
		t.Fatal(err)
	}
	list, _ = ListDockerRules(db)
	if len(list) != 0 {
		t.Error("delete failed")
	}
}

func TestSnapshotRestore(t *testing.T) {
	// fake iptables-save returns fixed output, iptables-restore records the file content
	r := &snapshotFake{}
	snap, err := Snapshot(r)
	if err != nil {
		t.Fatal(err)
	}
	if snap == "" {
		t.Error("empty snapshot")
	}
	// verify Snapshot() called iptables-save with -t filter
	if r.saveCalledWith != "filter" {
		t.Errorf("Snapshot must pass -t filter to iptables-save, got: %q", r.saveCalledWith)
	}
	if err := Restore(r, snap); err != nil {
		t.Fatal(err)
	}
	if r.restored != snap {
		t.Errorf("restore content mismatch: got %q, want %q", r.restored, snap)
	}
}

type snapshotFake struct {
	restored       string
	saveCalledWith string // records the -t <table> arg passed to iptables-save
}

func (s *snapshotFake) Run(name string, args ...string) (string, string, error) {
	if name == "iptables-save" {
		// capture the -t <table> argument
		for i, a := range args {
			if a == "-t" && i+1 < len(args) {
				s.saveCalledWith = args[i+1]
			}
		}
		return "*filter\n:INPUT ACCEPT [0:0]\nCOMMIT\n", "", nil
	}
	if name == "iptables-restore" && len(args) > 0 {
		data, err := os.ReadFile(args[0])
		if err != nil {
			return "", "", err
		}
		s.restored = string(data)
		return "", "", nil
	}
	return "", "", nil
}

func TestIntentUpdatePreservesCreatedAt(t *testing.T) {
	db := testDB(t)

	// Create
	it := Intent{Type: "port_allow", Params: `{"proto":"tcp","port":80}`, Enabled: true}
	if err := SaveIntent(db, &it); err != nil {
		t.Fatal(err)
	}
	if it.ID == 0 {
		t.Fatal("ID not set after create")
	}

	// Fetch the created intent to get its CreatedAt
	var row FirewallIntent
	if err := db.Where("id = ?", it.ID).First(&row).Error; err != nil {
		t.Fatal(err)
	}
	origCreatedAt := row.CreatedAt
	if origCreatedAt.IsZero() {
		t.Fatal("CreatedAt should not be zero after create")
	}

	// Update (same ID)
	it.Params = `{"proto":"tcp","port":443}`
	it.Enabled = false
	if err := SaveIntent(db, &it); err != nil {
		t.Fatal(err)
	}

	// Fetch again, verify CreatedAt is preserved
	if err := db.Where("id = ?", it.ID).First(&row).Error; err != nil {
		t.Fatal(err)
	}
	if row.CreatedAt.IsZero() {
		t.Error("CreatedAt was overwritten to zero time on update")
	}
	if !row.CreatedAt.Equal(origCreatedAt) {
		t.Errorf("CreatedAt changed: was %v, now %v", origCreatedAt, row.CreatedAt)
	}
}

func TestApplyLifecycle(t *testing.T) {
	db := testDB(t)
	if err := SaveApply(db, "tok1", "SNAP"); err != nil {
		t.Fatal(err)
	}
	pending, _ := ListPendingApplies(db)
	if len(pending) != 1 {
		t.Fatalf("got %d pending", len(pending))
	}
	if err := ConfirmApply(db, "tok1"); err != nil {
		t.Fatal(err)
	}
	pending, _ = ListPendingApplies(db)
	if len(pending) != 0 {
		t.Error("confirm should clear pending")
	}
}
