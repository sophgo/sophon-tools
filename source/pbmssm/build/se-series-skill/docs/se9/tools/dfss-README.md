# dfss cpp 重构

## 使用方式

### dfss url

使用 --url=open@sophgo.com:/文件路径 可以从open账户中下载指定文件

### dfss dflag

使用 --dflag=文件标记 可以从open账户中下载指定文件（被标记的文件）

### dfss user

使用 --user=用户名 可以自动登陆SDK账号和HDK账号

### dfss insall

dfss的install功能可以方便地下载和安装软件包。

使用方式：`python3 -m dfss --install [package]`

例如：`python3 -m dfss --install sail`

目前支持的package：

- sail

### dfss list / force_server

1. 使用 --list 可以列出当前已经配置的服务器链路
2. 使用 --force_server ID 可以强制dfss从某个ID的服务器链路下载文件

## 编译方式

1. host模式默认主机X86_64
2. 交叉编译要求主机必须X86_64
3. linux_release.sh参数两个，第一个是架构名，第二个是lib(标记库一起编译)
4. 最终生成的程序在output下，同目录的json文件是服务配置文件，需要和程序安装在同一目录下

### 支持架构

* amd64 linux
* amd64 win
* i686 win
* arm64 linux
* loongarch64 linux
* riscv64 linux
* armbi linux
* sw_64 linux

### 示例

``` bash
./linux_release.sh host lib;
./linux_release.sh aarch64 lib;
./linux_release.sh loongarch64 lib;
./linux_release.sh sw_64 lib;
./linux_release.sh armbi lib;
./linux_release.sh riscv64 lib;
./linux_release.sh mingw lib;
./linux_release.sh mingw64 lib;
```

### 默认编译器版本

* amd64 linux gcc9.4(ubuntu20) static
* amd64 win gcc9.3(ubuntu20) static
* i686 win gcc9.3(ubuntu20) static
* arm64 linux gcc9.4(ubuntu20) static
* loongarch64 linux gcc14.2(ubuntu20) static
* riscv64 linux gcc9.4(ubuntu20) static
* armbi linux gcc9.4(ubuntu20)
* sw_64 linux gcc8.3(ubuntu20) static

### 发布方式

使用当前目录的CPP源码编译出各个架构的运行程序，然后使用dfss_pip目录下的python工程将工具发布到pip上
