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

// integrationDB creates a temp sqlite DB for integration tests (real iptables, root only).
func integrationDB(t *testing.T) *gorm.DB {
	f, err := os.CreateTemp("", "fwint-*.db")
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	os.Remove(f.Name())
	db, err := database.InitDB(f.Name())
	if err != nil {
		t.Fatal(err)
	}
	if err := database.Migrate(db); err != nil {
		t.Fatal(err)
	}
	return db
}

// rulePresent checks live iptables <chain> for a line containing all substrings.
func rulePresent(t *testing.T, r CommandRunner, chain string, subs ...string) bool {
	out, _, err := r.Run("iptables", "-t", "filter", "-L", chain, "-n", "--line-numbers")
	if err != nil {
		t.Logf("list %s: %v", chain, err)
		return false
	}
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "Chain ") || strings.Contains(line, "num ") {
			continue
		}
		ok := true
		for _, s := range subs {
			if !strings.Contains(line, s) {
				ok = false
				break
			}
		}
		if ok {
			return true
		}
	}
	return false
}

// TestIntegrationMatrix exercises all device scenarios against real iptables (root).
// Each apply is immediately rolled back; SSH-protect is verified on the --force self-lock test.
func TestIntegrationMatrix(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("needs root + real iptables")
	}
	r := SystemRunner{}
	db := integrationDB(t)
	defer database.DB().Close()
	a := NewApplier(db, r)
	defer CleanManaged(r) // safety net: no leftover managed rules

	// ---- 1. Six intent presets (non-SSH ports, safe) ----
	cases := []struct {
		name   string
		intent Intent
		chain  string
		subs   []string
	}{
		{"port_allow", Intent{Type: IntentPortAllow, Params: `{"proto":"tcp","port":8080,"src":"10.0.0.0/8"}`, Enabled: true}, "INPUT", []string{"ACCEPT", "dpt:8080", "10.0.0.0/8"}},
		{"port_deny", Intent{Type: IntentPortDeny, Params: `{"proto":"tcp","port":3306}`, Enabled: true}, "INPUT", []string{"DROP", "dpt:3306"}},
		{"rate_limit", Intent{Type: IntentRateLimit, Params: `{"port":8443,"rate":5,"per":"second","burst":10}`, Enabled: true}, "INPUT", []string{"recent", "dpt:8443"}},
		{"ip_whitelist", Intent{Type: IntentIPWhitelist, Params: `{"cidr":"10.20.0.0/16"}`, Enabled: true}, "INPUT", []string{"ACCEPT", "10.20.0.0/16"}},
		{"ip_blacklist", Intent{Type: IntentIPBlacklist, Params: `{"cidr":"6.6.6.6/32"}`, Enabled: true}, "INPUT", []string{"DROP", "6.6.6.6"}},
		{"icmp_allow", Intent{Type: IntentICMP, Params: `{"allow":true}`, Enabled: true}, "INPUT", []string{"ACCEPT", "icmp"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			c.intent.ID = 0
			if err := SaveIntent(db, &c.intent); err != nil {
				t.Fatal(err)
			}
			res, err := a.Apply(true)
			if err != nil {
				DeleteIntent(db, c.intent.ID)
				t.Fatalf("apply %s: %v", c.name, err)
			}
			if !rulePresent(t, r, c.chain, c.subs...) {
				t.Errorf("%s: rule not found in %s with %v", c.name, c.chain, c.subs)
			}
			if err := a.Rollback(res.Token); err != nil {
				t.Logf("rollback %s: %v (continuing)", c.name, err)
			}
			DeleteIntent(db, c.intent.ID)
		})
	}

	// ---- 2. DOCKER-USER two scenes ----
	t.Run("docker_ext_to_container", func(t *testing.T) {
		d := DockerRule{Scene: DockerExtToContainer, Params: `{"container_port":9999,"proto":"tcp","src":"10.30.0.0/16","action":"allow"}`, Enabled: true}
		if err := SaveDockerRule(db, &d); err != nil {
			t.Fatal(err)
		}
		res, err := a.Apply(true)
		if err != nil {
			DeleteDockerRule(db, d.ID)
			t.Fatal(err)
		}
		if !rulePresent(t, r, "DOCKER-USER", "dpt:9999", "10.30.0.0/16") {
			t.Error("ext_to_container RETURN rule not in DOCKER-USER")
		}
		a.Rollback(res.Token)
		DeleteDockerRule(db, d.ID)
	})
	t.Run("docker_container_to_ext", func(t *testing.T) {
		d := DockerRule{Scene: DockerContainerToExt, Params: `{"container_cidr":"172.18.0.0/16","dst_except":"10.0.0.0/8","action":"deny"}`, Enabled: true}
		if err := SaveDockerRule(db, &d); err != nil {
			t.Fatal(err)
		}
		res, err := a.Apply(true)
		if err != nil {
			DeleteDockerRule(db, d.ID)
			t.Fatal(err)
		}
		if !rulePresent(t, r, "DOCKER-USER", "172.18.0.0/16", "DROP") {
			t.Error("container_to_ext DROP rule not in DOCKER-USER")
		}
		a.Rollback(res.Token)
		DeleteDockerRule(db, d.ID)
	})

	// ---- 3. Static detection (no apply, safe): DROP on protect port -> risk ----
	t.Run("static_detection_ssh_drop", func(t *testing.T) {
		ssh := DetectSSHPorts(r)
		if len(ssh) == 0 {
			t.Skip("no sshd ports detected (can't test protect)")
		}
		port := ssh[0]
		it := Intent{Type: IntentPortDeny, Params: `{"proto":"tcp","port":` + itoa(port) + `}`, Enabled: true}
		if err := it.Validate(); err != nil {
			t.Fatal(err)
		}
		rules, _ := it.Translate()
		risks := CheckRisks(rules, ssh)
		found := false
		for _, rk := range risks {
			if rk.Mode == "direct_block" {
				found = true
			}
		}
		if !found {
			t.Errorf("expected direct_block risk for SSH port %d, got %+v", port, risks)
		}
	})

	// ---- 4. Anti-self-lock --force on real SSH port (immediate rollback) ----
	t.Run("force_self_lock_ssh_protect", func(t *testing.T) {
		ssh := DetectSSHPorts(r)
		if len(ssh) == 0 {
			t.Skip("no sshd ports detected")
		}
		port := ssh[0]
		it := Intent{Type: IntentPortDeny, Params: `{"proto":"tcp","port":` + itoa(port) + `}`, Enabled: true}
		SaveIntent(db, &it)
		// force: bypasses static check, but InsertProtect + timer still run.
		res, err := a.Apply(true)
		if err != nil {
			DeleteIntent(db, it.ID)
			t.Fatalf("force apply SSH deny: %v", err)
		}
		// SSH protect rule must be in INPUT (ACCEPT before the DROP)
		if !rulePresent(t, r, "INPUT", "ACCEPT", "dpt:"+itoa(port), "bmssm-fw-protect") {
			t.Errorf("SSH protect ACCEPT not found in INPUT (port %d) — self-lock guard failed", port)
		}
		// The DROP rule also present (the intent)
		if !rulePresent(t, r, "INPUT", "DROP", "dpt:"+itoa(port), "bmssm-fw-intent") {
			t.Errorf("SSH deny DROP not found in INPUT (port %d)", port)
		}
		// Immediately rollback (don't wait 5min timer) — restores pre-apply snapshot.
		if err := a.Rollback(res.Token); err != nil {
			t.Logf("rollback: %v", err)
		}
		DeleteIntent(db, it.ID)
		// Verify protect + deny both gone
		if rulePresent(t, r, "INPUT", "dpt:"+itoa(port), "bmssm-fw") {
			t.Errorf("leftover bmssm-fw rule for SSH port %d after rollback", port)
		}
	})

	// ---- 5. Persistence: apply -> rules.v4 contains the rule -> rollback -> gone ----
	t.Run("persistence_rules_v4", func(t *testing.T) {
		it := Intent{Type: IntentPortAllow, Params: `{"proto":"tcp","port":7777}`, Enabled: true}
		SaveIntent(db, &it)
		res, err := a.Apply(true)
		if err != nil {
			DeleteIntent(db, it.ID)
			t.Fatal(err)
		}
		data, err := os.ReadFile("/etc/iptables/rules.v4")
		if err != nil {
			t.Skip("no rules.v4")
		}
		if !strings.Contains(string(data), "dpt:7777") && !strings.Contains(string(data), "--dport 7777") {
			t.Errorf("rules.v4 does not contain applied rule 7777 after apply+persist")
		}
		a.Rollback(res.Token)
		DeleteIntent(db, it.ID)
	})

	// ---- 6. Crash recovery: apply -> mark rollback_at past -> CrashRecover -> restored + record gone ----
	t.Run("crash_recover_expired", func(t *testing.T) {
		it := Intent{Type: IntentPortAllow, Params: `{"proto":"tcp","port":6666}`, Enabled: true}
		SaveIntent(db, &it)
		res, err := a.Apply(true)
		if err != nil {
			DeleteIntent(db, it.ID)
			t.Fatal(err)
		}
		// rule present post-apply
		if !rulePresent(t, r, "INPUT", "dpt:6666", "bmssm-fw-intent") {
			DeleteIntent(db, it.ID)
			t.Fatal("rule 6666 not present after apply")
		}
		// simulate a crash + restart after rollback_at expired: mark the row's rollback_at in the past.
		if err := db.Exec("UPDATE firewall_applies SET rollback_at = ? WHERE token = ?", "2020-01-01 00:00:00", res.Token).Error; err != nil {
			t.Logf("mark past: %v", err)
		}
		// CrashRecover (startup path) — should restore snapshot + clean protect + delete apply.
		CrashRecover(a)
		// rule must be gone (snapshot restored to pre-apply which had no 6666 rule)
		if rulePresent(t, r, "INPUT", "dpt:6666", "bmssm-fw-intent") {
			t.Errorf("rule 6666 still present after CrashRecover (snapshot not restored)")
		}
		// apply record must be deleted
		pending, _ := ListPendingApplies(db)
		for _, p := range pending {
			if p.Token == res.Token {
				t.Errorf("apply %s still pending after CrashRecover", res.Token)
			}
		}
		DeleteIntent(db, it.ID)
	})
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b []byte
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	return string(b)
}
