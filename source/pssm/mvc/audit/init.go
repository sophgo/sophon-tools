package audit

import "ssm/database"

func init() {
	database.RegisterModel(&AuditLog{})
}
