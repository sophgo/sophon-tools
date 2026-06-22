package types

type LoginRequest struct {
	UserName string `json:"userName"`
	Password string `json:"password"`
}

type LogoutRequest struct {
	Token string `json:"token"`
}

type LoginResponse struct {
	Token     string `json:"token"`
	ChangPass int    `json:"changePass"`
}
