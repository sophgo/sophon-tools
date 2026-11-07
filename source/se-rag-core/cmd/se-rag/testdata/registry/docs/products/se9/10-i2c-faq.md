# SE9 微服务器 FAQ

## 16-BP1-11 的 I2C 怎么接

SE9 16-BP1-11 通过 40 pin 排针引出 I2C0 与 I2C1：I2C0 为 SCL/SDA 复用 GPIO3/GPIO4，
默认 100kHz，需在设备树里把 `i2c0` 节点的 `clock-frequency` 改为 400000 才能跑高速模式。
