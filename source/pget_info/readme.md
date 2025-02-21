# get_info 算丰设备信息获取脚本

## 文件说明

``` bash

.
├── get_info_log_to_png.py
├── get_info_log_to_png.yaml
├── get_info.sh
├── readme.md
└── release.sh

```

* get_info_log_to_png.py 将get_info记录的log文件可视化的程序
* get_info_log_to_png.yaml 将get_info记录的log文件可视化的程序的配置样例
* get_info.sh 设备信息获取脚本
* readme.md 说明
* release.sh 输出脚本

## 使用说明

### get_info.sh

#### 普通使用方式

``` bash

sudo bash get_info.sh

```

直接获取信息

#### 服务记录方式

``` bash

sudo bash get_info.sh server <log file> <loop time> y

```

自动启动一个后台服务，每隔\<loop time\>时间获取一次信息到文件\<log file\>，使用并配置开机自启的实例视频如下

https://github.com/user-attachments/assets/819bf5cd-c619-41b9-9e88-1c4dcba9c70a

#### 服务记录方式-自动压缩日志模式

``` bash

sudo get_info.sh server_logs_path <log path> <loop time>

```

自动启动一个后台服务，每隔\<loop time\>时间获取一次信息到目录\<log path\>下，每个日志文件超过1M时会自动压缩，整个目录大小超过10M时自动删除旧的记录。这个方案适用于长期记录数据，\<loop time\>推荐给150s，这样10M的空间可以记录3个月左右的数据。

#### 特殊环境变量说明

1. get_info默认不会使用pmbus工具记录PMIC相关信息，如果需要，请确保除了get_info之外没有其他任何程序在操作PMIC，然后配置环境变量`GET_INFO_PMBUS_ENABLE=1`后运行get_info即可

#### 高度裁剪的系统环境

1. 对于一些高度裁剪的系统，该脚本中大部分命令可能找不到。可以从本仓库的release页面下载最新的 staticBinTools_arm64 包，然后使用类似如下的方式进行调用
	``` bash
	root@bm1684:/xxx$ ls
	get_info.sh  staticBinTools_arm64
	root@bm1684:/xxx$ PATH="$(pwd)/staticBinTools_arm64/:$PATH" bash get_info.sh
	BOOT_TIME(s)|5356.50|
	DATE_TIME|2024-12-21 17:35:36 CST|
	WORK_MODE|SOC|
	CPU_MODEL|bm1684x|
	# ...
	```
2. 同时，工具自带的 server 模式在这类系统中通常也无法正常使用。推荐使用如下方式进行循环调用：
	``` bash
	# 如果需要放置到后台，可以将该命令写入一个脚本文件，然后后台启动该脚本文件
	while true; do sleep 1; PATH="$(pwd)/staticBinTools_arm64:$PATH" bash get_info.sh 2>/dev/null 1>> get_info.log; done;
	```

### get_info_log_to_png.py

``` bash

python3 get_info_log_to_png.py --config get_info_log_to_png.yaml --log get_info.log

```

将上述`get_info.sh`生成的log文件输出为图形化的png图表，详细配置可参考文件`get_info_log_to_png.yaml`，生成实例如下

![实例图像](ex_get_info.log.png)

