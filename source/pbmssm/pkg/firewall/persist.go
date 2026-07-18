package firewall

import (
	"fmt"
	"os"
	"time"

	"bmssm/database"
	"bmssm/logger"

	"github.com/jinzhu/gorm"
)

func init() {
	database.RegisterModel(&FirewallIntent{}, &FirewallDockerRule{}, &FirewallApply{})
}

// GORM models (v1 jinzhu)

type FirewallIntent struct {
	ID        int64     `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	Type      string    `gorm:"column:type;not null" json:"type"`
	Params    string    `gorm:"column:params;not null" json:"params"`
	Enabled   int       `gorm:"column:enabled;default:1" json:"enabled"`
	CreatedAt time.Time `gorm:"column:created_at" json:"createdAt"`
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

func (FirewallIntent) TableName() string { return "firewall_intents" }

type FirewallDockerRule struct {
	ID        int64     `gorm:"column:id;primary_key;AUTO_INCREMENT" json:"id"`
	Scene     string    `gorm:"column:scene;not null" json:"scene"`
	Params    string    `gorm:"column:params;not null" json:"params"`
	Enabled   int       `gorm:"column:enabled;default:1" json:"enabled"`
	CreatedAt time.Time `gorm:"column:created_at" json:"createdAt"`
	UpdatedAt time.Time `gorm:"column:updated_at" json:"updatedAt"`
}

func (FirewallDockerRule) TableName() string { return "firewall_docker_rules" }

type FirewallApply struct {
	Token      string    `gorm:"column:token;primary_key" json:"token"`
	AppliedAt  time.Time `gorm:"column:applied_at" json:"appliedAt"`
	RollbackAt time.Time `gorm:"column:rollback_at" json:"rollbackAt"`
	Confirmed  int       `gorm:"column:confirmed;default:0" json:"confirmed"`
	Snapshot   string    `gorm:"column:rule_snapshot" json:"-"`
}

func (FirewallApply) TableName() string { return "firewall_applies" }

// Intent CRUD

func ListIntents(db *gorm.DB) ([]Intent, error) {
	var rows []FirewallIntent
	if err := db.Find(&rows).Error; err != nil {
		return nil, err
	}
	out := make([]Intent, 0, len(rows))
	for _, r := range rows {
		out = append(out, Intent{ID: r.ID, Type: IntentType(r.Type), Params: r.Params, Enabled: r.Enabled == 1})
	}
	return out, nil
}

func SaveIntent(db *gorm.DB, it *Intent) error {
	row := FirewallIntent{ID: it.ID, Type: string(it.Type), Params: it.Params, Enabled: boolToInt(it.Enabled)}
	if it.ID == 0 {
		row.CreatedAt = time.Now()
		row.UpdatedAt = time.Now()
		if err := db.Create(&row).Error; err != nil {
			return err
		}
		it.ID = row.ID
		return nil
	}
	row.UpdatedAt = time.Now()
	// Use Updates with a map to avoid overwriting zero-value CreatedAt (GORM v1 Save writes all columns).
	return db.Model(&FirewallIntent{}).Where("id = ?", it.ID).Updates(map[string]interface{}{
		"type":       row.Type,
		"params":     row.Params,
		"enabled":    row.Enabled,
		"updated_at": row.UpdatedAt,
	}).Error
}

func DeleteIntent(db *gorm.DB, id int64) error {
	return db.Where("id = ?", id).Delete(FirewallIntent{}).Error
}

// DockerRule CRUD

func ListDockerRules(db *gorm.DB) ([]DockerRule, error) {
	var rows []FirewallDockerRule
	if err := db.Find(&rows).Error; err != nil {
		return nil, err
	}
	out := make([]DockerRule, 0, len(rows))
	for _, r := range rows {
		out = append(out, DockerRule{ID: r.ID, Scene: DockerScene(r.Scene), Params: r.Params, Enabled: r.Enabled == 1})
	}
	return out, nil
}

func SaveDockerRule(db *gorm.DB, d *DockerRule) error {
	row := FirewallDockerRule{ID: d.ID, Scene: string(d.Scene), Params: d.Params, Enabled: boolToInt(d.Enabled)}
	if d.ID == 0 {
		row.CreatedAt = time.Now()
		row.UpdatedAt = time.Now()
		if err := db.Create(&row).Error; err != nil {
			return err
		}
		d.ID = row.ID
		return nil
	}
	row.UpdatedAt = time.Now()
	return db.Model(&FirewallDockerRule{}).Where("id = ?", d.ID).Updates(map[string]interface{}{
		"scene":      row.Scene,
		"params":     row.Params,
		"enabled":    row.Enabled,
		"updated_at": row.UpdatedAt,
	}).Error
}

func DeleteDockerRule(db *gorm.DB, id int64) error {
	return db.Where("id = ?", id).Delete(FirewallDockerRule{}).Error
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// Snapshot 用 iptables-save 抓 filter 表（含 DOCKER-USER 链）。
func Snapshot(r CommandRunner) (string, error) {
	out, errStr, err := r.Run("iptables-save", "-t", "filter")
	if err != nil {
		return "", fmt.Errorf("iptables-save: %s: %s", err, errStr)
	}
	return out, nil
}

// Restore 写临时文件 + iptables-restore。用于原子性回滚。
func Restore(r CommandRunner, snapshot string) error {
	f, err := os.CreateTemp("", "fw-restore-*.rules")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err := f.WriteString(snapshot); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Chmod(f.Name(), 0600); err != nil {
		return err
	}
	_, errStr, err := r.Run("iptables-restore", f.Name())
	if err != nil {
		return fmt.Errorf("iptables-restore: %s: %s", err, errStr)
	}
	return nil
}

// Apply lifecycle

func SaveApply(db *gorm.DB, token, snapshot string) error {
	_, _, sec, _ := FirewallConfig()
	row := FirewallApply{
		Token:      token,
		AppliedAt:  time.Now(),
		RollbackAt: time.Now().Add(time.Duration(sec) * time.Second),
		Confirmed:  0,
		Snapshot:   snapshot,
	}
	return db.Save(&row).Error
}

func GetApply(db *gorm.DB, token string) (*FirewallApply, error) {
	var row FirewallApply
	if err := db.Where("token = ?", token).First(&row).Error; err != nil {
		return nil, err
	}
	return &row, nil
}

func ListPendingApplies(db *gorm.DB) ([]FirewallApply, error) {
	var rows []FirewallApply
	if err := db.Where("confirmed = 0").Find(&rows).Error; err != nil {
		return nil, err
	}
	return rows, nil
}

func ConfirmApply(db *gorm.DB, token string) error {
	return db.Model(FirewallApply{}).Where("token = ?", token).Update("confirmed", 1).Error
}

func DeleteApply(db *gorm.DB, token string) error {
	return db.Where("token = ?", token).Delete(FirewallApply{}).Error
}

// PersistRules 把当前 live 规则存到 rules.v4（重启后 iptables-persistent 自动 restore）。
func PersistRules(r CommandRunner, path string) error {
	out, errStr, err := r.Run("iptables-save")
	if err != nil {
		return fmt.Errorf("iptables-save: %s: %s", err, errStr)
	}
	if err := os.WriteFile(path, []byte(out), 0644); err != nil {
		return err
	}
	logger.Info("firewall rules persisted to %s", path)
	return nil
}

// DB 取全局 db（service 层用）。
func DB() *gorm.DB { return database.DB() }
