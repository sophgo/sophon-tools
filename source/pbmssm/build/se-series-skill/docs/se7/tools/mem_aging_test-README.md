# SoC/PCIe模式设备DDR压测工具

## 简介

1. 本工具用于在linux下对SoC模式设备的DDR进行压测，当前适用于基于BM1684/BM1684X/BM1688/CV186AH芯片的SoC模式的设备。
2. 本工具测试原理是使用memtester+芯片的GDMA同时对DDR的系统内存和设备内存进行压测。

## 使用方式

0. 清空所有占用设备内存的业务或者程序，bm-smi看到设备内存使用为0
1. 获取工具，文件树如下:
    ``` bash
    linaro@sophon:/data/mem_aging_test$ tree .
    .
    ├── clean.sh
    ├── logs_check.sh
    ├── memtest_gdma
    │   ├── Makefile
    │   ├── build.sh
    │   └── memtest_gdma.c
    ├── memtester_dir
    │   └── memtester
    ├── readme.md
    └── start.sh

    2 directories, 8 files
    ```
2. 执行 `start.sh` 脚本，参考命令如下:
    1. `bash start.sh` 启动测试，运行1轮
    2. `bash start.sh 33` 启动测试，运行33轮
    3. `PCIE_DEV_ID=3 bash start.sh 30` 针对PCIe模式启动测试，测试设备3，运行30轮
3. 上一个命令执行生效的参考输出如下:
   ``` bash
   linaro@sophon:/data/mem_aging_test$ bash start.sh
    /data/mem_aging_test/memtest_gdma /data/mem_aging_test
    rm -f memtest_gdma *.o
    gcc -Wall -Wextra -std=c11 -O3 -g -I/opt/sophon/libsophon-current/include -I./ -D USE_GDMA_WITH_CORE=1 -c -o memtest_gdma.o memtest_gdma.c
    ...
    A/ljJRbREAAA" | base64 -d | gzip -d -c -); memtest_s /data/mem_aging_test 1;
                 ├─771265 sleep 5
                 └─771286 ./memtest_gdma 0 [1 16 1024 1024  -1 8
    [MEMTEST INFO] loop: 1
    [MEMTEST INFO] you can use 'systemctl status memtest_s.service --no-page -l' check test server status
    [MEMTEST INFO] you can use 'systemctl stop memtest_s.service' stop test server
    [MEMTEST INFO] you can check test log at: /data/mem_aging_test/logs/
    ```
4. 脚本启动后压测业务会在后台运行，可以通过bm-smi观测到gdma的运行情况，也可以通过路径 `/xxx/mem_aging_test/logs/` 下的log文件了解详细的测试情况
5. 等到服务发布广播（所有登录的终端都可以收到该广播）则压测完毕，可以通过 `logs_check.sh` 脚本检查日志文件是否有错误
    1. 压测完成并没有错误的广播如下:
        ``` bash
        linaro@sophon:/data/mem_aging_test$ 
                                                                               
        Broadcast message from root@sophon (somewhere) (Fri Dec  6 14:30:02 2024):     
                                                                                       
        [MEMTEST INFO] test loop 0 end!!!, please check log file at /data/memtest_a53_g
        dma/logs/
                                                                                       
        linaro@sophon:/data/mem_aging_test$
        ```
    2. 日志检查并没有错误的结果如下:
        ``` bash
        linaro@sophon:/data/mem_aging_test$ bash logs_check.sh 
        [INFO] memtest logs check start...
        [INFO] work dir: /data/mem_aging_test
        [INFO] memtest logs check success, no error!!!
        ```

> 日志文件会有2-3个，如下：
>   1. gdma.log - GDMA压测程序的日志
>   2. memtester.log - memtester压测程序的日志
>   3. error.log - 如果压测失败，则会生成该日志，里面有部分错误信息

> 如果压测有报错，同样会进行广播，广播会以 `[MEMTEST ERROR]` 开头
