# 配网工具

## 编译方式

``` bash
bash build.sh
```

## 使用方式

``` bash
Examples:
  DHCP IPv4:         bm_set_ip eth0 dhcp ''
  DHCP IPv4+IPv6:    bm_set_ip eth0 dhcp '' '' '' dhcp
  Static IPv4:       bm_set_ip eth0 192.168.1.100 24 192.168.1.1
  Static IPv4+IPv6:  bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1

Arguments:
  <NET_DEVICE>    网卡名
  <IP>            IPv4 地址或dhcp
  <NETMASK>       IPv4 掩码或前缀长度
  [GATEWAY]       IPv4 网关，可为空
  [DNS]           IPv4 DNS，可为空
  [IPV6]          IPv6 地址或dhcp，可为空
  [IPV6_PREFIX]   IPv6 前缀长度，可为空
  [IPV6_GATEWAY]  IPv6 网关，可为空
  [IPV6_DNS]      IPv6 DNS，可为空

```

