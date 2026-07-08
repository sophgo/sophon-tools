package audit

import "bmssm/database"

func init() {
	database.RegisterModel(&AuditLog{})
}
