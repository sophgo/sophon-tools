package firewall

// IntentRequest is the request DTO for adding a firewall intent.
type IntentRequest struct {
	ID      int64  `json:"id"`
	Type    string `json:"type" binding:"required"`
	Params  string `json:"params" binding:"required"`
	Enabled bool   `json:"enabled"`
}
