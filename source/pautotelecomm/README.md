
# 4G/5G通用拨号工具

## 适用设备

1. SE5
2. SE7
3. SE9

## 适配4G/5G模组列表

1. NL668
2. FM650
3. EC20
4. A7600

## 安装方式

> 安装脚本会将 rootfs 文件写入 `/` 目录、注册 systemd 服务并安装内核模块，**必须以 root 权限执行**。

1. 以root权限执行 `sudo bash autotelecomm_install_x.x.x.sh` ，该文件可以通过本仓库的Release页面获取
2. 在弹出 `success, please restart this device` 后将设备关机
3. 将SIM卡插入设备
4. 上电启动设备

## 构建方式

本子项目仅支持 **arm64**（rootfs 内含 aarch64 预编译二进制 quectel-CM/dhclient，amd64 设备无法运行），统一构建接口：

```bash
bash release.sh [ARCH] [VERSION]
#   ARCH:    仅 arm64（默认），传入其他值将报错退出
#   VERSION: 显式版本号（默认 1.2.8），产物为 autotelecomm_install_<VERSION>.sh
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pautotelecomm/）
```

产物为单文件自解包安装脚本 `autotelecomm_install_<VERSION>.sh`，内含 rootfs 与内核模块源码包，在设备上以 root 执行即可安装。

## 设备端内核模块安装依赖

- 内核开发头文件（linux-headers，版本需与设备当前内核 `uname -r` 匹配）。
  缺失时安装脚本会明确报错；也可传入内核头安装脚本：
  `bash install.sh /path/to/linux-headers-install.sh`。
- 内核模块在**设备端**编译安装（不依赖预编译 .ko），编译需 `make`/`gcc`。
- 安装过程不依赖 sudo（脚本需 root 直跑）。

## 常见问题

1. 拨号使用的SIM卡为物联网卡或白卡，请参考 `mobile_communications.py` 文件中描述，联系运营商以获取APN并进行替换。
2. 如使用的4G/5G模组在 `mobile_communications.py` 中并未显示适配，请参考 `mobile_communications.py` 以及 `fibocom_base.py` 文件进行适配，目前在 `model_base.py` 中提供了部分已适配的接口，如有需要可参考格式新增接口并选用。
3. 如果遇到拨号失败、没有IP等问题，请参考如下流程排查：
    1. SIM卡是否识别，可以通过模组的AT指令手册查询
    2. 天线是否插牢，是否有信号，通常信号大于21以上才能正常使用，可以通过模组的AT指令手册查询信号强度
    3. 使用的SIM卡是否是特殊的APN，如果是请参考第一项

## 常见的信息查询AT指令：

* `AT` 返回OK，验证串口交互
* `AT+CPIN?` 判断SIM卡状态
* `AT+COPS?` 展示SIM卡的运营商信息
* `AT+CGREG?` 查看入网状态
* `AT+CSQ` 查看当前信号状态

> 需要根据模组厂家提供的手册分析指令的返回信息

## 适配新设备流程

1. 确定新设备USB ID
2. 修改文件 `rootfs/etc/udev/rules.d/77-autotelecomm.rules` 增加新设备自启动拨号服务
3. 新建文件 `rootfs/usr/sbin/autotelecomm_scripts/xxx.py` 内容参考 `fibocom_base.py` 即可
4. 修改文件 `rootfs/usr/sbin/autotelecomm_scripts/mobile_communications.py` 增加新设备的拨号类
