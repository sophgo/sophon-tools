### 1 [0.033] `network.md:3-6`
【SE9 网络配置】
## 双网口绑定

SE9 的两个千兆网口用 netplan 配 bond，模式 802.3ad，上游需开 LACP。

### 2 [0.032] `i2c-faq.md:3-6`
【SE9 I2C】
## 16-BP1-11 的 I2C 怎么接

I2C0 复用 GPIO3/GPIO4，默认 100kHz，设备树 clock-frequency 改 400000 可跑高速。

### 3 [0.016] `sdk.md:3-10`
【BM1688 SDK】
## tpu-mlir 编译模型

```bash
model_deploy.py --chip bm1688
```

先用 model_transform.py 转 MLIR，再生成 bmodel。

---
*3 results | mode=hybrid | total <MS>ms*
