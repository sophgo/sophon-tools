# 网口phy寄存器读写工具 sophon_phytool 

## 说明

本工程用于简要说明如何使用sophon_phytool.sh读写网口phy寄存器

## 适用场景

* 仅支持phy芯片：RTL、YT、MARVEL，因此脚本参数 <ic_name> 可以设置为 RTL、YT、MARVEL

## 使用方式
```bash
./sophon_phytool.sh <read|write> <ic_name> <device> <phy_addr> <page> <reg_addr> [write_data]
```
以RTL为例：读phy寄存器
``` bash
linaro@bm1684:~$ ./sophon_phytool.sh read RTL eth1 0x0 0xd08 0x15
[info]: PHY chip ID: 0x001cc878
[info]: ic page reg: 0x1f
[info]: eth1: page is 0xd08 , reg addr is 0x15, reg value is 0x0811

```

以RTL为例：写phy寄存器
``` bash
linaro@bm1684:~$ ./sophon_phytool.sh write RTL eth1 0x0 0xd08 0x15 0x19
[info]: PHY chip ID: 0x001cc878
[info]: ic page reg: 0x1f
[info]: eth1: page: 0xd08, reg addr: 0x15, write data: 0x19
```

## CV84X2/CV84X6 适用说明

CV84X2（CV84X6）EVB 板载双 Realtek RTL8211F PHY，PHY ID 为 `0x001cc916`，属于脚本 RTL 分支支持范围，无需新增 PHY 分支。真机（EVB，内核 5.10）实测信息：

| 网口 | PHY 型号 | phy_addr | page_reg |
|---|---|---|---|
| eth0 | RTL8211F | 0x0 | 0x1f |
| eth1 | RTL8211F | 0x0 | 0x1f |

CV84X2 上读取示例（已在 EVB 真机验证，含扩展 page 切换）：
``` bash
linaro@sophon:~$ ./sophon_phytool.sh read RTL eth0 0x0 0xd08 0x15
[info]: ic page reg: 0x1f
[info]: PHY chip ID: 0x001cc916
[info]: eth0: page is 0xd08 , reg addr is 0x15, reg value is 0x0019
```

注意事项：

* 硬件探测读取的是用户参数指定的 `<device>/<phy_addr>` 的 PHY ID（历史版本固定读 eth1，多网口且 PHY 型号不一致时会误显示所操作网口的型号）
* `read` 操作内部会对 page 选择寄存器（RTL 为 reg 0x1f）执行「切换 page → 读寄存器 → 恢复 page 0」，属读流程的正常行为
* `write` 操作会直接改写 PHY 寄存器，可能导致网口失联，请在明确风险并确认参数无误后再执行
