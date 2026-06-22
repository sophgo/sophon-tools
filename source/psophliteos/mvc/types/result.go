package types

type Result struct {
	Code   int         `json:"code"`
	Msg    string      `json:"msg"`
	Result interface{} `json:"result,omitempty"`
}

type Page struct {
	PageCount int         `json:"pageCount"`
	PageNo    int         `json:"pageNo"`
	PageSize  int         `json:"pageSize"`
	Total     int         `json:"total"`
	Items     interface{} `json:"items"`
}

type NetIp struct {
	NetCardName string  `json:"netCardName"`
	Bandwidth   int     `json:"bandwidth"`
	DeltaRx     int     `json:"deltaRx"`
	DeltaTx     int     `json:"deltaTx"`
	DNS         string  `json:"dns"`
	Dynamic     int     `json:"dynamic"`
	Gateway     string  `json:"gateway"`
	IP          string  `json:"ip"`
	Mac         string  `json:"mac"`
	Name        string  `json:"name"`
	NetMask     string  `json:"netMask"`
	NetRx       float64 `json:"netRx"`
	NetTx       float64 `json:"netTx"`
	Rate        int     `json:"rate"`
}
