# SE7 微服务器手册

## 网络配置

SE7 使用 netplan 配置 eth0 的 dhcp4，改完执行 `netplan apply` 生效。

## 远程升级

SE7 通过 OTA 升级系统镜像，升级前先备份 `/etc` 与 `/opt/sophon`。
