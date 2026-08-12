# SE7 网络配置

本章说明 SE7 设备的基本网络与连接配置。

## 有线网络

编辑 `/etc/netplan/99-config.yaml`：

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
```

应用配置：

```bash
sudo netplan apply
```

## Wi-Fi 模块（可选）

配套 Wi-Fi 模块（RTL8822 系列）插入后，可接入无线网络：

```bash
nmcli device wifi list
nmcli device wifi connect "SSID" password "密码"
```

> 注意：部分 Wi-Fi 模块需安装对应内核驱动补丁后使用。

## 连通性验证

```bash
ping -c 3 网关IP
curl -I http://www.baidu.com
```

若外网不通，检查 DNS 配置与默认路由：`ip route`。
