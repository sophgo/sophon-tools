package agentproxy

import (
	"bmssm/database"
)

func init() {
	database.RegisterModel(&WebchatSession{})
	database.RegisterModel(&ConfigRecord{})
}
