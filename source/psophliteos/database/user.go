package database

func QueryUserWithName(username string) (*User, error) {
	var user User

	db := DB.Model(&User{}).Where("user_name = ?", &username).First(&user)
	if err := db.Error; err != nil {
		return nil, err
	}

	return &user, nil
}

func QueryUserWithToken(token string) (*User, error) {
	var user User
	db := DB.Model(&User{}).Where("token = ?", &token).First(&user)
	if err := db.Error; err != nil {
		return nil, err
	}

	return &user, nil
}

func UpdateUser(user *User) {
	values := map[string]interface{}{
		"token":       user.Token,
		"expire_time": user.ExpireTime,
		"locked_time": user.LockedTime,
	}
	DB.Model(&User{}).Where("id = ?", user.ID).Update(values)
}

func SaveUser(user *User) {
	DB.Model(&User{}).Save(user)
}
