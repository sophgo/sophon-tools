package user

import "bmssm/database"

func init() {
	database.RegisterModel(&User{})
}
