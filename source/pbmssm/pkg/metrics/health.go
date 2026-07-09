package metrics

// defaultCriticalTemp 健康判定的临界温度（℃）。
const defaultCriticalTemp = 85.0

// HealthStatus 根据温度判定设备健康状态。
// chip 或 board 温度超过 critical 时返回 false。
// 对齐 Rust determine_health_status。
func (c *Collector) HealthStatus(chipTemp, boardTemp float64) bool {
	if chipTemp > defaultCriticalTemp || boardTemp > defaultCriticalTemp {
		return false
	}
	return true
}
