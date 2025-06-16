
# 4G/5G通用拨号工具

## 适用4G/5G模组

1. NL668
2. FM650
3. EC20

## 安装方式

## 文件描述

工具文件结构如下：

    .
    ├── autotelecomm.service                # 4G/5G通用拨号工具服务文件
    ├── README.md                           # 4G/5G通用拨号工具指导手册
    └── scripts                             # 包含了4G/5G通用拨号工具脚本文件
        ├── fibocom_base.py
        ├── lbs.py
        ├── mobile_communications.py        # 4G/5G通用拨号工具服务启动文件
        ├── model_base.py
        └── redcap_base.py

## 使用方式

1. 如果设备有lteModemManager服务，需要先stop并disable。
2. 如果设备有autotelecomm服务，则可能已经内置了该工具，请检查该服务的内容。
3. 将本目录的`autotelecomm_scripts`目录cp到/usr/sbin/下，并执行`sudo chmod +x /usr/sbin/autotelecomm_scripts/*`
4. 将本目录的`autotelecomm.service`文件cp到`/lib/systemd/system`下，并执行`sudo systemctl daemon-reload;sudo systemctl enable autotelecomm;sudo systemctl start autotelecomm`
5. 通过`sudo journalctl -u autotelecomm`可以查看该服务的log

## 常见问题

1. 拨号使用的SIM卡为物联网卡或白卡，请参考mobile_communications.py文件中描述，联系运营商以获取APN并进行替换。
2. 如使用的4G/5G模组在mobile_communications.py中并未显示适配，请参考mobile_communications.py以及fibocom_base.py文件进行适配，目前在model_base.py中提供了部分已适配的接口，如有需要可参考格式新增接口并选用。


