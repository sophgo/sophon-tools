package main

import (
	"context"
	"net"
	"time"
)

// netDialer 让 Executor 的拨号可替换，便于测试；生产等价于 net.Dialer。
type netDialer struct {
	timeout time.Duration
}

func (d netDialer) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	nd := net.Dialer{Timeout: d.timeout}
	return nd.DialContext(ctx, network, addr)
}
