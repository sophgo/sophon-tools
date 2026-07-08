package alarm

import "ssm/database"

func init() {
	database.RegisterModel(&Alarm{})
}
