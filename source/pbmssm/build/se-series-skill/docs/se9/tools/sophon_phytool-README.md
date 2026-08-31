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
