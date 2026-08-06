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
	database.RegisterModel(&FirewallIntent{})
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

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
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

// Snapshot 抓 filter 表完整规则，供 Rebuild 失败时原子回滚。
func Snapshot(r CommandRunner) (string, error) {
	out, errStr, err := r.Run("iptables-save", "-t", "filter")
	if err != nil {
		return "", fmt.Errorf("iptables-save: %s: %s", err, errStr)
	}
	return out, nil
}

// Restore 用 iptables-restore 恢复快照（写临时文件，原子替换 live 规则）。
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

// DB 取全局 db（service 层用）。
func DB() *gorm.DB { return database.DB() }
