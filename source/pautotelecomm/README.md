
# 4G/5G通用拨号工具

## 适用设备

1. SE5
2. SE7
3. SE9

## 适配4G/5G模组列表

1. NL668
2. FM650
3. EC20

## 安装方式

1. 以root权限执行 `bash autotelecomm_install_x.x.x.sh` ，该文件可以通过本仓库的Release页面获取
2. 在弹出 `success, please restart this device` 后将设备关机
3. 将SIM卡插入设备
4. 上电启动设备

## 常见问题

1. 拨号使用的SIM卡为物联网卡或白卡，请参考 `mobile_communications.py` 文件中描述，联系运营商以获取APN并进行替换。
2. 如使用的4G/5G模组在 `mobile_communications.py` 中并未显示适配，请参考 `mobile_communications.py` 以及 `fibocom_base.py` 文件进行适配，目前在 `model_base.py` 中提供了部分已适配的接口，如有需要可参考格式新增接口并选用。
3. 如果遇到拨号失败、没有IP等问题，请参考如下流程排查：
    1. SIM卡是否识别，可以通过模组的AT指令手册查询
    2. 天线是否插牢，是否有信号，通常信号大于21以上才能正常使用，可以通过模组的AT指令手册查询信号强度
    3. 使用的SIM卡是否是特殊的APN，如果是请参考第一项
