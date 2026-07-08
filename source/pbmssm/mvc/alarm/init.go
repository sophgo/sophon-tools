package alarm

import "bmssm/database"

func init() {
	database.RegisterModel(&Alarm{})
}
