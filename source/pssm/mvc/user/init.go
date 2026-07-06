package user

import "ssm/database"

func init() {
	database.RegisterModel(&User{})
}
