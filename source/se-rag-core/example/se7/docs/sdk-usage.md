# SE7 SDK 使用

## SDK 版本与获取

- 版本字段：`sophon-mw-soc-*`
- 主组件：libsophon v23.09-LTS、sophon-sail、tpu-mlir、sophon-img

## 常用命令

```bash
# 查看已安装 SDK 版本
sophon-mw-soc --version

# 系统信息
uname -a
cat /proc/cmdline | grep -o 'console=[^ ]*'   # 确认串口配置
```

## TPU 推理环境

安装了 BM1684X 的 TPU 驱动与 BMRT 运行时后，可加载 bmodel 执行推理。

常见问题排查：

- TPU 内存不足 → 修改设备树（DTS）中的显存分配
- 驱动未加载 → 检查 `bmsophon` 服务状态

## 开发示例

```python
import sail  # sophon-sail
# 加载模型并推理（示例）
```

## 参考文档

- 微服务器 SE7 产品使用手册
- 微服务器 SE7 产品规格书
- BM1684X 开发参考
