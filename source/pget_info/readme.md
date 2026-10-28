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

自动启动一个后台服务，每隔\<loop time\>时间获取一次信息到目录\<log path\>下，每个日志文件超过1M时会自动压缩，整个目录大小超过10M时自动删除旧的记录。这个方案适用于长期记录数据，\<loop time\>推荐给150s，这样10M的空间可以记录4-6个月左右的数据。

可以使用如下命令对多个gz日志文件进行拼接

``` bash

ls *get_info.log.gz | sort -n | xargs -I{} zcat {} 1>>/data/get_info.log

```

#### 特殊环境变量说明

1. get_info默认不会使用pmbus工具记录PMIC相关信息，如果需要，请确保除了get_info之外没有其他任何程序在操作PMIC，然后配置环境变量`GET_INFO_PMBUS_ENABLE=1`后运行get_info即可

#### CV84X6 电压采集说明

CV84X6（CV84X2）没有 bm1684 那类 pmbus 电源监控器件，但主芯片电压由 `cv84x2-dvfs-pmbus` 驱动通过 PMBus 控制 JWH63782 PMIC，因此 `VDDC_VOLTAGE(mV)` 可以采集到实时值：

* **首选路径**：读 `/sys/devices/platform/cv84x2-dvfs/cpu_volt_mv`（驱动 probe 成功后存在，驱动内部已完成 PMBus 换算）。不依赖 `GET_INFO_PMBUS_ENABLE`。
* **回退路径**：驱动未就绪（如 dtb 缺 `pmic-addr` 属性导致 probe 失败）时，按 `5036000.i2c` 控制器反查总线号，在 `0x00` / `0x20` 两个候选地址上按 `MFR_ID=0x5702` 探测，按 `V=(VID+49)×10` 换算。
* **`VTPU_VOLTAGE(mV)` 恒为空**：该芯片 CPU 与 TPU 共用同一路供电（single rail, shared），page1 从未使能，物理上不存在独立的 TPU 电压，故不采集、也不用 CPU 值冒充。
* **读不到时留空**：不填 0、不做估算，空值表示"该板不可测"。

``` bash
root@cv84x6:~$ sudo bash get_info.sh | grep -E "CPU_MODEL|VDDC_VOLTAGE"
CPU_MODEL|cv84x6|
VDDC_VOLTAGE(mV)|980|
```

#### CV84X6 TPU 运行态采集说明

CV84X6 的 `TPU_USAGE(%)` 是内核采样出的利用率，只说明"有多忙"，不说明"还活着没有"：
利用率 0% 既可能是真空闲，也可能是 TPU 固件崩了、或某次 kernel 卡住不返回。
`/proc/bmtpu/` 提供的就是后者，脚本在 `TPU_USAGE` 之后输出以下字段（仅 CV84X6）：

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `TPU_FW_VERSION` | TPU 固件版本（多核同版本只输出一次；版本不一致时会全部列出，提示核间镜像不同） | `scaler_info` 每核 `FIRMWARE_VERSION` |
| `TPU_FW_BUILD_TIME` | 每核固件编译时间，逗号分隔（各核本就是分别编译的镜像，正常就不同） | `scaler_info` 每核 `BUILD_TIME` |
| `TPU_CORE_STATE` | 每核状态：`BUSY` / `IDLE` / `INIT` / `RUN` / `EXITED` / `CRASH<n>`（n 为信号号）/ `UNKNOWN` | `scaler_info` 的 `running_flag` + `using_flag` |
| `TPU_TASK_RATE(tasks/s)` | 最近 1s 固件收到的任务数 | `scaler_info` 的 `recvmsg_cnt` 两次采样差值 |
| `TPU_QUEUE_DEPTH` | 已下发但固件尚未消费的 api 数（Σ pushed − done） | `kernel_info` 各 HWQ |
| `TPU_HWQ_FREE_MIN` | 8 个硬件队列里最小的空闲槽位；见底说明下发侧即将进入背压等待 | `kernel_info` 各 HWQ |

状态判定要点：

* `BUSY` 取自 `using_flag==0xa5a5`（固件正在处理自己负责的 packet），是**最权威的忙闲标志**；
  `BUSY` 且 `TPU_TASK_RATE` 长时间为 `0.00` 是**卡死**特征，不是空闲。
  实测（2026-10-28，10.42.0.242）：一次 `bmrt_test` 触发了已知的 kernel 挂起，
  此时 4 核全为 `BUSY,BUSY,BUSY,BUSY`、rate `0.00`、queue depth 冻结不动，
  而 `npu_usage` 仍报 100 —— 只看利用率无法分辨这种情况。
* `EXITED`（`running_flag=0xAA55DEAD`）表示固件主循环意外退出，正常设备永不出现。
* `CRASH<n>` 是固件崩溃处理函数把信号号写进 `running_flag` 的 bit16-23
  （覆盖 magic 里的 `0x55`），`n` 为信号号，如 `CRASH11` = SIGSEGV。

只读保证：脚本只 `cat` `scaler_info` 与 `kernel_info` 两个文件，不写任何
`/proc/bmtpu` 节点。**绝不能读 `bmdi_api_info`** —— 该 proc_show 会走
`bm1688_base_get_core_num()` → `otp_reg_read(bmdi, 0x2014)`，而 84x6 的 BAR 不覆盖
`0x27100000`（dmesg: `bm_get_bar_offset invalid address = 0x27100000`），
OTP 映射基址为 NULL，读一次就内核 Oops 一次（`Unable to handle kernel paging request
at virtual address 0000000000002014`，实测复现两次）。`shmpacket` / `txpsys` /
`wakeup_control` 需要先写入才输出，写会改全局调试状态，同样一律不碰。

`GET_INFO_BMTPU_INTERVAL` 可覆盖速率采样窗口（默认 `1.0` 秒，单位秒）。
窗口太短会在突发式推理的两批之间读出 0，容易被误判成 TPU 停了。

``` bash
root@cv84x6:~$ sudo bash get_info.sh | grep -E "^TPU_"
TPU_MEM(MiB)|26320|
TPU_MEM_USAGE(%)|86.00|
TPU_CLK(Hz)|1000000000|
TPU_USAGE(%)|0 0 0 0 0|
TPU_FW_VERSION|fd3aca2|
TPU_FW_BUILD_TIME|2026-08-14_00:23:55,2026-08-14_00:25:22,2026-08-14_00:26:40,2026-08-14_00:27:43|
TPU_CORE_STATE|IDLE,IDLE,IDLE,IDLE|
TPU_TASK_RATE(tasks/s)|0.00|
TPU_QUEUE_DEPTH|0|
TPU_HWQ_FREE_MIN|16|
```

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

### 数据可视化

#### 在线网站

可以在网站 [https://zfsopv.github.io/getinfo2png/](https://zfsopv.github.io/getinfo2png/) 进行数据的可视化。

#### get_info_log_to_png.py

也可以使用本仓库的转换脚本进行转换：

``` bash

python3 get_info_log_to_png.py --config get_info_log_to_png.yaml --log get_info.log

```

将上述`get_info.sh`生成的log文件输出为图形化的png图表，详细配置可参考文件`get_info_log_to_png.yaml`，生成实例如下

![实例图像](ex_get_info.log.png)

