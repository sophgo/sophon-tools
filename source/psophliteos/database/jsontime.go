package database

import (
	"encoding/json"
	"time"
)

const (
	TimeFormat = "2006-01-02 15:04:05"
)

type Time time.Time

func (u *OptLog) MarshalJSON() ([]byte, error) {
	type Alias OptLog
	user := &struct {
		CreatedTime Time `json:"dataTime"`
		*Alias
	}{Time(u.CreatedTime), (*Alias)(u)}

	return json.Marshal(user)
}

func (u *Alarm) MarshalJSON() ([]byte, error) {
	type Alias Alarm
	user := &struct {
		CreatedAt Time `json:"dataTime"`
		*Alias
	}{Time(u.CreatedAt), (*Alias)(u)}

	return json.Marshal(user)
}

func (u *User) MarshalJSON() ([]byte, error) {
	type Alias User
	user := &struct {
		CreatedAt  Time `json:"created_at"`
		ExpireTime Time `json:"expire_time"`
		*Alias
	}{Time(u.CreatedAt), Time(u.ExpireTime), (*Alias)(u)}

	return json.Marshal(user)
}

func (u *User) UnmarshalJSON(data []byte) (err error) {
	type Alias User
	user := &struct {
		CreatedAt  Time `json:"created_at"`
		ExpireTime Time `json:"expire_time"`
		*Alias
	}{Time(u.CreatedAt), Time(u.ExpireTime), (*Alias)(u)}
	err = json.Unmarshal(data, user)
	if err != nil {
		return err
	}

	user.Alias.CreatedAt = time.Time(user.CreatedAt)
	user.Alias.ExpireTime = time.Time(user.ExpireTime)
	*u = User(*user.Alias)
	return nil
}

func (t *Time) UnmarshalJSON(data []byte) (err error) {
	now, err := time.ParseInLocation(`"`+TimeFormat+`"`, string(data), time.Local)
	*t = Time(now)
	return
}

func (t Time) MarshalJSON() ([]byte, error) {
	b := make([]byte, 0, len(TimeFormat)+2)
	b = append(b, '"')
	b = time.Time(t).AppendFormat(b, TimeFormat)
	b = append(b, '"')
	return b, nil
}

func (t Time) String() string {
	return time.Time(t).Format(TimeFormat)
}
