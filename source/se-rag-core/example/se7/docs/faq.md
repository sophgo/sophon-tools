# SE7 常见问题（FAQ）

## Q1: TPU 内存不够怎么办？

先查看显存占用：

```bash
bm-smi
```

若 TPU 内存耗尽，可修改设备树（DTS）调整显存分配，然后重启生效。

## Q2: OTA 升级失败？

- 确认升级包版本与当前系统匹配
- 使用 `pota_update` 工具按手册步骤操作
- 失败后检查 `/var/log/sophgo/` 相关日志

## Q3: 串口无法连接？

确认 `/boot/emmcboot.itb` 内核镜像配置的 console 参数，调整波特率重新连。

## Q4: Wi-Fi 无法关联？

- 确认驱动补丁已安装
- 检查 AP 频段（5GHz / 2.4GHz）是否支持
