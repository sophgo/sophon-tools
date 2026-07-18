package firewall

// IntentRequest is the request DTO for adding a firewall intent.
type IntentRequest struct {
	Type    string `json:"type" binding:"required"`
	Params  string `json:"params" binding:"required"`
	Enabled bool   `json:"enabled"`
}

// DockerRuleRequest is the request DTO for adding a docker-user rule.
type DockerRuleRequest struct {
	Scene   string `json:"scene" binding:"required"`
	Params  string `json:"params" binding:"required"`
	Enabled bool   `json:"enabled"`
}

// RawRuleRequest is the request DTO for adding a raw iptables rule.
type RawRuleRequest struct {
	Chain string   `json:"chain" binding:"required"`
	Args  []string `json:"args" binding:"required"`
}

// ApplyRequest is the request DTO for triggering a firewall apply.
type ApplyRequest struct {
	Force bool `json:"force"`
}

// TokenRequest is the request DTO for confirm/rollback operations.
type TokenRequest struct {
	Token string `json:"token" binding:"required"`
}
