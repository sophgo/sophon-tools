# 配网工具

## 编译方式

``` bash
bash build.sh
```

## 使用方式

``` bash
linaro@sophon:~$ ./bm_set_ip --help
配置网卡的 IPv4/IPv6 参数（支持 netplan 和 NetworkManager）

使用示例：
  配置静态 IPv4 地址（无网关）:
    bm_set_ip eth1 192.168.150.1 255.255.255.0

  配置 DHCP:
    bm_set_ip eth0 dhcp ''

  配置静态 IPv4 和 IPv6 地址（有网关）:
    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1 240e:8::8


Usage: bm_set_ip <NET_DEVICE> <IP> <NETMASK> [GATEWAY] [DNS] [IPV6] [IPV6_PREFIX] [IPV6_GATEWAY] [IPV6_DNS]

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

Options:
  -h, --help     Print help
  -V, --version  Print version
```

