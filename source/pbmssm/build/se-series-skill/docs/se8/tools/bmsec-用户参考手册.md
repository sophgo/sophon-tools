# 用户使用手册

## 使用流程说明

### 启动SE6/8设备

上电、等待机器完全启动(该工具默认配置支持算力核心SSH账密端口均默认的情况，如果有算力核心修改了这些信息，需要在安装后修改文件/opt/sophon/bmsec/configs/sub/subInfo.12中的对应信息，然后执行`bmsec rconf`命令重新生成配置)

### 安装本工具

将本工具安装包`bmsec_*.deb`拷贝到控制板上

使用`sudo dpkg -i bmsec_*.deb`命令进行安装

然后等待安装完成,安装完成后执行一次`bmsec pconf`进行算力核心的自动探测和打印配置

正常结果是自动检测一次配置并将打印当前算力核心上电情况和其22端口的对外映射情况

类似于下方的信息:

``` bash
config info: 
7. linaro:linaro@(172.16.150.11):22 -> 20021
8. linaro:linaro@(172.16.150.12):22 -> 20022
9. linaro:linaro@(172.16.150.13):22 -> 20023
10. linaro:linaro@(172.16.150.14):22 -> 20024
11. linaro:linaro@(172.16.150.15):22 -> 20025
12. linaro:linaro@(172.16.150.16):22 -> 20026
```

以`7. linaro:linaro@(172.16.150.11):22 -> 20021`这一行为例,解析其中的内容:

* 该算力核心编号是7号
* 该算力核心的账户密码是linaro linaro
* 该算力核心的IP是172.16.150.11
* 该算力核心的SSH端口是22
* 该算力核心的SSH端口对SE6/8设备外部的端口映射是20021

### 本工具功能详细介绍

本工具的所有功能均有命令行和交互式两种模式,其中命令行是一条命令执行一个功能的方式进行操作,交互式是用户根据工具的提示输入足够的信息后进行操作.

本工具部分功能支持所有算力核心批量执行，支持该功能时会在参数说明时标注

1. **打印帮助文档 [help]**
    - 参数：无参数
    - 说明：该功能用于打印应用程序的简易帮助文档，以帮助用户了解可用的命令和选项。
    - 命令行模式示例：`bmsec help`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号1
    - 输出示例:

        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec help
        bmsec version: 1.1.8
        help:
        The tool has two usage modes. The first usage mode is the command-line mode, which uses command-line arguments as parameters for each subfunction.
        usage: bmsec [run <id> <args>]
        The second one is interactive command mode.
        List of parameters [Enter the number]: 
        1. Print help documentation [help] 
        2. Print configuration information [pconf] 
        3. Execute remote commands [run <id> <cmd>] 
        4. Get basic information for all remote devices [getbi] 
        5. Upload files [pf <id> <localFile> <remoteFile>] 
        6. Download files [df <id> <remoteFile> <localFile>] 
        7. Connect to a specified ID with SSH [ssh <id>] 
        8. Restart the power of core [reset <id>] 
        9. Connect to the debugging UART of core use picocom [uart <id>] 
        10. Print the debugging UART of core [puart <id>] 
        11. Upgrade a core using /recovery/tftp [update <id>] 
        12. Check the upgrade progress [tftpc] 
        13. Share /data/bmsecNfsShare to specific compute node with nfs [nfs <localPath> <remotePath>] 
        14. Configure core memory [cmem <id> {<p> / < <c> <npuSize> <vpuSize> <vppSize> >} [dtsFile]] 
        15. reset cores config [rconf]
        ```

2. **打印配置信息 [pconf]**
    - 参数：无参数
    - 说明：此功能用于打印应用程序的配置信息，包括算力核心节点域名和其他相关配置。此处打印的信息与安装后第一次检测配置时打印的信息一致
    - 命令行模式示例：`bmsec pconf`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号2
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pconf
        config info: 
        7. linaro:linaro@(172.16.150.11):22 -> 20021
        8. linaro:linaro@(172.16.150.12):22 -> 20022
        9. linaro:linaro@(172.16.150.13):22 -> 20023
        10. linaro:linaro@(172.16.150.14):22 -> 20024
        11. linaro:linaro@(172.16.150.15):22 -> 20025
        12. linaro:linaro@(172.16.150.16):22 -> 20026
        ```

3. **远程执行命令 [run \<id> \<cmd>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心，该id如果为all则可以在所有算力核心上批量执行命令，如果id为类似于1+4+7则可以在1 4 7三个算力节点执行。
        - `<cmd>`：需要在目标算力核心上执行的命令。
    - 说明：通过此功能，用户可以在远程的算力核心上执行特定的命令。
    - 命令行模式示例：`bmsec run 12 ls`
    - 交互式模式示例：输入`bmsec`后输入该功能编号`3`,然后输入需要执行的算力核心编号`12`然后输入需要执行的命令`ls`
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec run 12 ls
        Core Id: 12, Cmd: ls
        bsp-debs
        script
        spi_flash.bin
        tftp_update
        ```

4. **获取所有远程设备信息 [getbi]**
    - 参数：无参数
    - 说明：该功能用于获取所有远程设备的相关信息，以帮助用户了解远程设备的状态。从做到右的信息如下:
       - 算力核心编号
       - 算力核心芯片型号
       - 算力核心SDK版本
       - 算力核心当前CPU使用率
       - 算力核心当前TPU使用率
       - 算力核心当前系统内存使用率
       - 算力核心当前TPU内存使用率
       - 算力核心当前VPU内存使用率
       - 算力核心当前VPP内存使用率
       - 算力核心当前温度 芯片温度/板卡温度
    - 命令行模式示例：`bmsec getbi`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号4
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec getbi
        ID CHIPID  SDK       CPU    TPU    SYSMEM TPUMEM VPUMEM VPPMEM TEMP(C/B)          
        7  BM1684  V23.03.01 1.08%  0%     35.37% 0%     0%     0%     48°C/41°C          
        8  BM1684  V22.12.01 0.88%  0%     18.44% 0%     0%     0%     56°C/51°C          
        9  BM1684  V22.12.01 1.1%   0%     34.74% 0%     0%     0%     58°C/52°C          
        10 BM1684  2.7.0     0.14%  0%     39.41% 0%     NAN%   0%     59°C/57°C          
        11 BM1684  2.7.0     0.98%  0%     93.68% 0%     NAN%   0%     56°C/54°C          
        12 BM1684  V22.12.01 0.89%  NAN%   11.61% NAN%   NAN%   NAN%   53°C/46°C 
        ```

5. **上传文件 [pf \<id> \<localFile> \<remoteFile>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心，该id如果为all则可以将本地文件上传到所有算力核心，如果id为类似于1+4+7则可以在1 4 7三个算力节点执行。
        - `<localFile>`：本地文件地址，指定要上传的本地文件路径。
        - `<remoteFile>`：远程目标地址，指定上传文件的目标路径，注：该位置需要linaro用户有写入权限。
    - 说明：通过此功能，用户可以将本地文件上传到远程算力核心。
    - 命令行模式示例：`bmsec pf all /factory/OEMconfig.ini /data`
    - 交互式模式示例：输入`bmsec`后输入该功能编号`5`,然后输入需要执行的算力核心编号,然后输入上传的控制板的本地文件路径,然后输入上传到算力核心后的文件位置
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pf all /factory/OEMconfig.ini /data
        Core Id: all, Local:/factory/OEMconfig.ini -> Remote:/data
        =============core7 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  295.33 bytes/sec
        total size is 309  speedup is 0.70
        =============core8 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  886.00 bytes/sec
        total size is 309  speedup is 0.70
        =============core9 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  886.00 bytes/sec
        total size is 309  speedup is 0.70
        =============core10 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  295.33 bytes/sec
        total size is 309  speedup is 0.70
        =============core11 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  886.00 bytes/sec
        total size is 309  speedup is 0.70
        =============core12 to /data===============
        sending incremental file list
        OEMconfig.ini
                    309 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 408 bytes  received 35 bytes  295.33 bytes/sec
        total size is 309  speedup is 0.70
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec run all "ls /data/OEM*"
        Core Id: all, Cmd: ls /data/OEM*
        ********core 7 run log************
        /data/OEMconfig.ini
        ********core 8 run log************
        /data/OEMconfig.ini
        ********core 9 run log************
        /data/OEMconfig.ini
        ********core 10 run log************
        /data/OEMconfig.ini
        ********core 11 run log************
        /data/OEMconfig.ini
        ********core 12 run log************
        /data/OEMconfig.ini
        ```

6. **下载文件 [df \<id> \<remoteFile> \<localFile>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心，该id如果为all则可以将所有算力核心文件下载到本地，以算力核心编号为前缀，如果id为类似于1+4+7则可以在1 4 7三个算力节点执行。
        - `<remoteFile>`：远程目标地址，指定要下载的远程文件路径。
        - `<localFile>`：本地文件地址，指定下载文件的保存路径，注：在`<id>`为all时需要需要指定下载位置到文件，不可以指定到目录。
    - 说明：通过此功能，用户可以从远程算力核心下载文件到本地计算机。
    - 命令行模式示例：`bmsec df all /factory/OEMconfig.ini /data/SubOEMconfig.ini`
    - 交互式模式示例：输入`bmsec`后输入该功能编号`6`,然后输入需要执行的算力核心编号,然后输入需要下载的算力核心的远程文件路径,然后输入下载到控制板后的本地文件位置
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec df all /factory/OEMconfig.ini /data/SubOEMconfig.ini
        Core Id: all, Remote:/factory/OEMconfig.ini -> Local:/data/SubOEMconfig.ini
        =============core7 to /data/6_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 408 bytes  902.00 bytes/sec
        total size is 309  speedup is 0.69
        =============core8 to /data/7_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 407 bytes  900.00 bytes/sec
        total size is 309  speedup is 0.69
        =============core9 to /data/8_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 408 bytes  300.67 bytes/sec
        total size is 309  speedup is 0.69
        =============core10 to /data/9_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 408 bytes  300.67 bytes/sec
        total size is 309  speedup is 0.69
        =============core11 to /data/10_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 408 bytes  300.67 bytes/sec
        total size is 309  speedup is 0.69
        =============core12 to /data/11_SubOEMconfig.ini===============
        receiving incremental file list
        OEMconfig.ini
                    309 100%  301.76kB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 43 bytes  received 407 bytes  300.00 bytes/sec
        total size is 309  speedup is 0.69
        linaro@AE0026-host:/data/zztTemp/bmsec$ ls /data
        10_SubOEMconfig.ini  11_SubOEMconfig.ini  6_SubOEMconfig.ini  7_SubOEMconfig.ini  8_SubOEMconfig.ini  9_SubOEMconfig.ini
        ```

7. **链接指定SSH [ssh \<id>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心，该id如果为all则可以将所有算力核心的电源重启，如果id为类似于1+4+7则可以在1 4 7三个算力节点执行。
    - 说明：该功能用于建立SSH连接到指定的算力核心。
    - 命令行模式示例：`bmsec ssh 12`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号7,然后输入需要ssh链接的算力核心编号
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec ssh 12
        Ssh To Core Id: 12
        Welcome to Ubuntu 20.04 LTS (GNU/Linux 5.4.217-bm1684-g1d0bad24641c aarch64)

        * Documentation:  https://help.ubuntu.com
        * Management:     https://landscape.canonical.com
        * Support:        https://ubuntu.com/advantage

        * Strictly confined Kubernetes makes edge and IoT secure. Learn how MicroK8s
        just raised the bar for easy, resilient and secure K8s cluster deployment.

        https://ubuntu.com/engage/secure-kubernetes-at-the-edge
        overlay / overlay rw,relatime,lowerdir=/media/root-ro,upperdir=/media/root-rw/overlay,workdir=/media/root-rw/overlay-workdir 0 0
        /dev/mmcblk0p5 /media/root-rw ext4 rw,relatime 0 0
        /dev/mmcblk0p4 /media/root-ro ext4 ro,relatime 0 0

        Last login: Sat Sep  9 17:52:27 2023 from 172.16.150.200
        linaro@AE0026-12:~$ 
        ```

8. **重启某个算力节点电源 [reset \<id>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心。
    - 说明：此功能可用于远程重启指定算力核心的电源。
    - 命令行模式示例：`bmsec reset 12`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号8,然后输入需要重启电源的算力核心编号
    - 输出示例(由于SE6/8底层实现不同，所以这个命令执行的输出并不一致，需要使用puart功能查看算力核心的调试串口打印来确定算力核心是否成果重启电源):
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec reset 12
        Reset Core Id: 12
        SE6_INF: se6ctr_switch_cpld CPLD1
        SE6_DBG: se6ctr_i2c_switch_mux in ch2
        0
        0
        ```

9. **链接指定算力节点调试串口 [uart \<id>]**
    - 参数：
        - `<id>`：算力核心id，用于指定目标算力核心。
    - 说明：该功能使用picocom工具建立与指定算力核心调试串口的链接。
    - 命令行模式示例：`bmsec uart 12`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号9,然后输入需要链接调试串口的算力核心编号
    - 输出示例
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec uart 12
        Uart To Core Id: 12
        SE6_INF: se6ctr_switch_cpld CPLD1
        SE6_DBG: se6ctr_i2c_switch_mux in ch2
        SE6_INF: se6ctr_switch_uart (0x0x56)6
        0
        /opt/sophon/bmsec/commands/uartRemote.sh: line 27: 167864 Killed                  ${seNCtrl_PWD}/binTools/killPros ${seNCtrl_DEBUG_UART} &> /dev/null
        picocom v3.1

        port is        : /dev/ttyS2
        flowcontrol    : none
        baudrate is    : 115200
        parity is      : none
        databits are   : 8
        stopbits are   : 1
        escape is      : C-a
        local echo is  : no
        noinit is      : no
        noreset is     : no
        hangup is      : no
        nolock is      : no
        send_cmd is    : sb -vv --ymodem
        receive_cmd is : rb -vv --ymodem -E
        imap is        : 
        omap is        : 
        emap is        : crcrlf,delbs,
        logfile is     : none
        initstring     : none
        exit_after is  : not set
        exit is        : no

        Type [C-a] [C-h] to see available commands
        Terminal ready

        AE0026-12 login: 
        AE0026-12 login: 
        ```

10. **打印指定算力节点调试串口 [puart \<id>]**
    - 参数：
       - `<id>`：算力核心id，用于指定目标算力核心。
    - 说明：通过此功能，用户可以在终端上打印指定算力核心的调试信息。
    - 命令行模式示例：`bmsec puart 12`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号10,然后输入需要打印调试串口信息的
    - 输出示例(由于该功能只有打印，所以可以在算力核心重启时查看调试信息，正常运行时该命令没有输出调试信息):
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec puart 12
        Uart To Core Id: 12
        SE6_INF: se6ctr_switch_cpld CPLD1
        SE6_DBG: se6ctr_i2c_switch_mux in ch2
        SE6_INF: se6ctr_switch_uart (0x0x56)6
        0
        /opt/sophon/bmsec/commands/puartRemote.sh: line 28: 164437 Killed                  ${seNCtrl_PWD}/binTools/killPros ${seNCtrl_DEBUG_UART} &> /dev/null
        e2fsck: Bad magic number in super-block while trying to open /dev/mmcblk0p3
        /dev/mmcblk0p3: 
        The superblock could not be read or does not describe a valid ext2/ext3/ext4
        filesystem.  If the device is valid and it really contains an ext2/ext3/ext4
        filesystem (and not swap or ufs or something else), then the superblock
        is corrupt, and you might try running e2fsck with an alternate superblock:
            e2fsck -b 8193 <device>
        or
            e2fsck -b 32768 <device>

        /dev/mmcblk0p5: recovering journal
        /dev/mmcblk0p5: clean, 731/393216 files, 410555/1572864 blocks
        /dev/mmcblk0p6: recovering journal
        /dev/mmcblk0p6: clean, 441/131072 files, 83792/524288 blocks
        /dev/mmcblk0p7: recovering journal
        /dev/mmcblk0p7: clean, 65/1015808 files, 108190/4058619 blocks
        mount: mounting /dev/mmcblk0p3 on /mnt failed: Invalid argument
        /dev/mmcblk0p[    3.861737] EXT4-fs (mmcblk0p4): mounted filesystem with ordered data mode. Opts: (null)
        4: clean, 63706/163840 files, 609377/655360 blocks
        [    3.875595] EXT4-fs (mmcblk0p5): mounted filesystem with ordered data mode. Opts: (null)
        [    4.108314] systemd[1]: System time before build time, advancing clock.
        [    4.125701] systemd[1]: Failed to find module 'autofs4'
        [    4.137927] systemd[1]: systemd 245.4-4ubuntu3 running in system mode. (+PAM +AUDIT +SELINUX +IMA +APPARMOR +SMACK +SYSVINIT +UTMP +LIBCRYPTSETUP +GCRYPT +GNUTLS +ACL +XZ +LZ4 +SECCOMP +BLKID +ELFUTILS +KMOD +IDN2 -IDN +PCRE2 default-hierarchy=hybrid)
        [    4.160502] systemd[1]: Detected architecture arm64.

        Welcome to Ubuntu 20.04 LTS!
        ```

11. **使用控制板自带刷机包升级指定算力核心 [update \<id>]**
    - 参数：
         - `<id>`：算力核心id，用于指定目标算力核心，该id如果为all则可以将所有算力核心刷机，如果id为类似于1+4+7则可以在1 4 7三个算力节点执行。
    - 说明：该功能用于升级指定算力核心的固件，使用控制板自带的刷机包，位置在`/recovery/tftp`,如果修改了刷机包，在升级算力核心前需要使用`sudo systemctl restart tftpd-hpa`命令，支持跨3.0.0版本升级，升级log推荐通过`puart`功能查看，防止`uart`查看时误操作将升级过程破坏。
    - 命令行模式示例：`bmsec update 12`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号11,然后输入需要升级的算力核心编号
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec update 12
        update Id: 12
        Core Id: 12, Local:/recovery/tftp/spi_flash.bin -> Remote:/data/spi_flash.bin
        sending incremental file list
        spi_flash.bin
            1,122,404 100%  129.89MB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 1,122,782 bytes  received 35 bytes  2,245,634.00 bytes/sec
        total size is 1,122,404  speedup is 1.00
        Core Id: 12, Local:/opt/sophon/bmsec/binTools/flash_update -> Remote:/data/flash_update
        sending incremental file list
        flash_update
                541,688 100%  161.78MB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 541,921 bytes  received 35 bytes  1,083,912.00 bytes/sec
        total size is 541,688  speedup is 1.00
        Core Id: 12, Cmd: sudo chmod +x /usr/sbin/flash_update;sudo /data/flash_update -f /data/spi_flash.bin -b 0x6000000
        input file is: /data/spi_flash.bin
        write 0x112064 bytes to flash @ 0x6000000 + 0x0
        0x6000000 mapped at address 0x7fa266b000
        INFO:  Start erasing 18 sectors, each 65536 bytes...
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        erasing one sector.....
        read flash:
        0  ff ff ff ff ff ff ff ff                          ........
        INFO:  --program boot fw, page size 256
        progress: 100%
        INFO:  --program boot fw success
        read flash:
        0  e0 3 1f aa e1 3 1f aa                          ........
        unmapped 0x7fa266b000
        Core Id: 12, Cmd: /home/linaro/tftp_update/mk_bootscr.sh;sudo sync
        Image Name:   Distro Boot Script
        Created:      Wed Sep 13 15:49:12 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    140 Bytes = 0.14 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 132 Bytes = 0.13 KiB = 0.00 MiB
        ```

12. **检查当前TFTP升级进度 [tftpc]**
    - 参数：无参数
    - 说明：该功能用于检查当前的TFTP升级进度，以确定升级是否正在进行中。
    - 命令行模式示例：`bmsec tftpc`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号12
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec tftpc
        ID      IP                      INFO
        7       172.16.150.11
        8       172.16.150.12
        9       172.16.150.13
        10      172.16.150.14
        11      172.16.150.15
        12      172.16.150.16   [15:51:38] system -> 6%
        Image 0: 132 Bytes = 0.13 KiB = 0.00 MiB
        ```

13. **启动NFS服务并共享到算力核心 [nfs \<localFile> \<remoteFile>]**
    - 参数：
         - `<localFile>`：本地文件地址，指定要共享到算力核心的本地文件或目录路径。
         - `<remoteFile>`：远程目标地址，指定远程算力核心上的目标路径。
    - 说明：通过此功能，用户可以启动NFS服务，并将本地文件或目录共享到远程算力核心。注：如果有自行的NFS配置，请不要使用该功能，以防NFS配置冲突。3.0.0之前的SDK版本的算力核心无法支持nfs挂载，需要安装nfs-common包
    - 命令行模式示例：`bmsec nfs /data/ /data/nfs`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号`13`，然后输入需要共享的控制板的本地路径，然后输入共享到算力核心的路径
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec nfs /data/ /data/nfs
        Core Id: all, Cmd: sudo umount /data/nfs
        umount: /data/nfs: not mounted.
        umount: /data/nfs: not mounted.
        umount: /data/nfs: not mounted.
        umount: /data/nfs: not mounted.
        umount: /data/nfs: not mounted.
        umount: /data/nfs: no mount point specified.
        ********core 7 run log************

        ********core 8 run log************

        ********core 9 run log************

        ********core 10 run log************

        ********core 11 run log************

        ********core 12 run log************

        Core Id: all, Cmd: mkdir -p /data/nfs
        ********core 7 run log************

        ********core 8 run log************

        ********core 9 run log************

        ********core 10 run log************

        ********core 11 run log************

        ********core 12 run log************

        Core Id: all, Cmd: sudo chmod 777 /data/nfs
        ********core 7 run log************

        ********core 8 run log************

        ********core 9 run log************

        ********core 10 run log************

        ********core 11 run log************

        ********core 12 run log************

        Core Id: all, Cmd: sudo mount -t nfs $(netstat -nr | grep '^0.0.0.0' | awk '{print $2}'):/data/ /data/nfs
        mount: /data/nfs: bad option; for several filesystems (e.g. nfs, cifs) you might need a /sbin/mount.<type> helper program.
        mount: /data/nfs: bad option; for several filesystems (e.g. nfs, cifs) you might need a /sbin/mount.<type> helper program.
        mount: /data/nfs: bad option; for several filesystems (e.g. nfs, cifs) you might need a /sbin/mount.<type> helper program.
        ********core 7 run log************

        ********core 8 run log************

        ********core 9 run log************

        ********core 10 run log************

        ********core 11 run log************

        ********core 12 run log************

        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec getbi
        ID CHIPID  SDK       CPU    TPU    SYSMEM TPUMEM VPUMEM VPPMEM TEMP(C/B)          
        7  BM1684  V23.03.01 1.08%  0%     7.42%  0%     0%     0%     49°C/42°C          
        8  BM1684  V22.12.01 1.02%  0%     8.44%  0%     0%     0%     57°C/52°C          
        9  BM1684  V22.12.01 1.08%  0%     7.81%  0%     0%     0%     59°C/53°C          
        10 BM1684  2.7.0     0.21%  0%     13.88% 0%     NAN%   0%     60°C/58°C          
        11 BM1684  2.7.0     1.12%  0%     19.65% 0%     NAN%   0%     57°C/55°C          
        12 BM1684  2.7.0     0.38%  0%     26.95% 0%     NAN%   0%     49°C/47°C  
        ```

14. **批量修改内存布局 [cmem \<id> {\<p> / < \<c> \<npuSize> \<vpuSize> \<vppSize> >} [dtsFile]]**
    - 参数：
         - `<id>`：算力核心id，用于指定目标算力核心，如果是all将对所有算力核心进行操作。
         - `{<p> / <c> <npuSize> <vpuSize> <vppSize> >}`：内存布局的修改参数。
            - p参数表示打印算力核心的内存布局情况
            - c参数表示配置算力核心的内存布局情况
         - `[dtsFile]`：可选参数，用于指定DTS文件的名称，仅在算力核心3.0.0版本或更早时需要使用。
    - 说明：通过此功能，用户可以批量修改算力核心的内存布局配置。
    - 命令行模式示例：`bmsec cmem 7 {p / c 2048 1024 1024} [/path/to/dtsfile]`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号`14`，然后输入需要操作的算力核心编号，然后输入p参数或c参数执行不同的操作。输入p操作后再输入DTS文件名（为空默认）将直接打印信息；输入c参数后需要输入三个部分的内存大小，然后输入DTS文件名（为空默认）。之后将进行内存布局修改
    - 输出示例:

    
        ``` bash

        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec cmem 7 p
        Core Id: 7, option:p -> npuSize: vpuSize: vppSize: dtsFile:
        Core Id: 7, Local:/opt/sophon/bmsec/binTools/memory_edit*.tar.xz -> Remote:/data/.memEdit/memory_edit.tar.xz
        sending incremental file list
        memory_edit_v1.6.tar.xz
                270,176 100%  226.41MB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 270,356 bytes  received 35 bytes  540,782.00 bytes/sec
        total size is 270,176  speedup is 1.00
        Core Id: 7, Cmd: if [[ -e /bin/memory_edit.sh || -L /bin/memory_edit.sh && -e /usr/bin/memory_edit.sh ]]; then MEMEDITSHELL=/bin/memory_edit.sh; else MEMEDITSHELL=./memory_edit.sh; fi; pushd /data/.memEdit/memory_edit; $MEMEDITSHELL -p ; popd; sudo rm -rf /data/.memEdit
        /data/.memEdit/memory_edit ~
        Info: use dts file /data/.memEdit/memory_edit/output/bm1684_sm5m_v0.1_rb_mm0.dts
        Info: chip is bm1684
        Info: =======================================================================
        Info: get ddr information ...
        Info: ddr12_size 4294967296 Byte [4096 MiB]
        Info: ddr3_size 4294967296 Byte [4096 MiB]
        Info: ddr4_size 4294967296 Byte [4096 MiB]
        Info: ddr_size 12288 MiB
        Info: =======================================================================
        Info: get max memory size ...
        Info: max npu size: 0xfaf00000 [4015 MiB]
        Info: max vpu size: 0xb8000000 [2944 MiB]
        Info: max vpp size: 0x100000000 [4096 MiB]
        Info: =======================================================================
        Info: get now memory size ...
        Info: now npu size: 0x80000000 [2048 MiB]
        Info: now vpu size: 0x40000000 [1024 MiB]
        Info: now vpp size: 0x40000000 [1024 MiB]
        ~
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec cmem 7 c 1024 512 512
        Core Id: 7, option:c -> npuSize:1024 vpuSize:512 vppSize:512 dtsFile:
        Core Id: 7, Local:/opt/sophon/bmsec/binTools/memory_edit*.tar.xz -> Remote:/data/.memEdit/memory_edit.tar.xz
        sending incremental file list
        memory_edit_v1.6.tar.xz
                270,176 100%  226.41MB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 270,356 bytes  received 35 bytes  540,782.00 bytes/sec
        total size is 270,176  speedup is 1.00
        Core Id: 7, Cmd: pushd /data/.memEdit/memory_edit; ./memory_edit.sh -c -npu 1024 -vpu 512 -vpp 512 ; popd
        /data/.memEdit/memory_edit ~
        Info: use dts file /data/.memEdit/memory_edit/output/bm1684_sm5m_v0.1_rb_mm0.dts
        Info: chip is bm1684
        Info: =======================================================================
        Info: get ddr information ...
        Info: ddr12_size 4294967296 Byte [4096 MiB]
        Info: ddr3_size 4294967296 Byte [4096 MiB]
        Info: ddr4_size 4294967296 Byte [4096 MiB]
        Info: ddr_size 12288 MiB
        Info: =======================================================================
        Info: get max memory size ...
        Info: max npu size: 0xfaf00000 [4015 MiB]
        Info: max vpu size: 0xb8000000 [2944 MiB]
        Info: max vpp size: 0x100000000 [4096 MiB]
        Info: =======================================================================
        Info: output configuration results ...
        Info: vpu mem area(ddr3): 0x8000000 [128 MiB] 0xd8000000 -> 0xdfffffff
        Info: ion npu mem area(ddr1): 0x40000000 [1024 MiB] 0x5100000 -> 0x450fffff
        Info: ion vpu mem area(ddr3): 0x20000000 [512 MiB] 0xe0000000 -> 0xffffffff
        Info: ion vpp mem area(ddr4): 0x20000000 [512 MiB] 0xe0000000 -> 0xffffffff
        Info: =======================================================================
        Info: start check memory size ...
        Info: check npu size: 0x40000000 [1024 MiB]
        Info: check vpu size: 0x20000000 [512 MiB]
        Info: check vpp size: 0x20000000 [512 MiB]
        Info: check edit size ok
        Info: en_emmcfile ok, please run cmd and reboot system:
        sudo cp /data/.memEdit/memory_edit/emmcboot.itb /boot/emmcboot.itb && sync
        ~
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec cmem 7 p
        Core Id: 7, option:p -> npuSize: vpuSize: vppSize: dtsFile:
        Core Id: 7, Local:/opt/sophon/bmsec/binTools/memory_edit*.tar.xz -> Remote:/data/.memEdit/memory_edit.tar.xz
        sending incremental file list
        memory_edit_v1.6.tar.xz
                270,176 100%  226.41MB/s    0:00:00 (xfr#1, to-chk=0/1)

        sent 270,356 bytes  received 35 bytes  540,782.00 bytes/sec
        total size is 270,176  speedup is 1.00
        Core Id: 7, Cmd: if [[ -e /bin/memory_edit.sh || -L /bin/memory_edit.sh && -e /usr/bin/memory_edit.sh ]]; then MEMEDITSHELL=/bin/memory_edit.sh; else MEMEDITSHELL=./memory_edit.sh; fi; pushd /data/.memEdit/memory_edit; $MEMEDITSHELL -p ; popd; sudo rm -rf /data/.memEdit
        /data/.memEdit/memory_edit ~
        Info: use dts file /data/.memEdit/memory_edit/output/bm1684_sm5m_v0.1_rb_mm0.dts
        Info: chip is bm1684
        Info: =======================================================================
        Info: get ddr information ...
        Info: ddr12_size 4294967296 Byte [4096 MiB]
        Info: ddr3_size 4294967296 Byte [4096 MiB]
        Info: ddr4_size 4294967296 Byte [4096 MiB]
        Info: ddr_size 12288 MiB
        Info: =======================================================================
        Info: get max memory size ...
        Info: max npu size: 0xfaf00000 [4015 MiB]
        Info: max vpu size: 0xb8000000 [2944 MiB]
        Info: max vpp size: 0x100000000 [4096 MiB]
        Info: =======================================================================
        Info: get now memory size ...
        Info: now npu size: 0x40000000 [1024 MiB]
        Info: now vpu size: 0x20000000 [512 MiB]
        Info: now vpp size: 0x20000000 [512 MiB]
        ~

        ```

15. **重新生成算力核心配置信息 [rconf]**
    - 参数：无参数
    - 说明：该功能根据当前上电成功的算力核心重新生成算力核心配置信息，并自动配置算力核心节点的域名。
    - 命令行模式示例：`bmsec rconf`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号`15`
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec rconf
        init info not, make it...
        core 1 is not power good
        core 2 is not power good
        core 3 is not power good
        core 4 is not power good
        core 5 is not power good
        core 6 is not power good
        core 7 is power good
        core 8 is power good
        core 9 is power good
        core 10 is power good
        core 11 is power good
        core 12 is power good
        config info: 
        7. linaro:linaro@(172.16.150.11):22 -> 20021
        8. linaro:linaro@(172.16.150.12):22 -> 20022
        9. linaro:linaro@(172.16.150.13):22 -> 20023
        10. linaro:linaro@(172.16.150.14):22 -> 20024
        11. linaro:linaro@(172.16.150.15):22 -> 20025
        12. linaro:linaro@(172.16.150.16):22 -> 20026
        ```

16. **将指定算力核心的环境进行打包，可选生成tftp刷机包和仅打半成品包 [sysbak \<id> \<localPath> [onlyBak]]**
    - 参数：
         - `<id>`：算力核心id，用于指定需要打包的算力核心
         - `<localPath>`：打包存放在控制板的路径，需要有充足的空间（推荐大于等于需要打包的算力核心空间的1.5倍左右）
         - `[onlyBak]`：可选参数，当该参数为`onlyBak`时用于指定只打包模式（降低对控制板资源耗用）
    - 说明：通过此功能，用户可以批量修改算力核心的内存布局配置。
    - 命令行模式示例：`bmsec sysbak 7 /data/nfsBak/`
    - 交互式模式示例：输入`bmsec`后输入该功能的编号`16`，然后输入需要操作的算力核心编号，然后输入打包存放在控制板的路径。然后可选输入`onlyBak`字符串开启只打包模式
    - 注意事项：
        - 默认使用打包`tftp`刷机包的模式，打包后的结果存放在指定路径下的`tftp`目录下，可替换`/recovery/tftp`后，重启`tftpd-hpa`服务，即可使用`update`功能刷机指定算力核心
        - 而只打包模式可以节约控制板资源的占用（消耗与`socBak`工具相同）。打包出的文件需要经过`socBak`工具从**在X86机器上制作定制的系统包**这一步之后的操作才能重打包为tftp刷机包
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec sysbak 7 /data/nfsBak/
        Core Id: 7, Cmd: [ -e /system/data/buildinfo.txt ] && exit 1 || exit 0
        Core Id: 7, Cmd: for mount_point in $(mount | grep nfs | awk '{print $3}'); do sudo umount "$mount_point"; done
        Core Id: 7, Cmd: sudo mkdir -p /socrepack
        Core Id: 7, Cmd: sudo chmod 777 /socrepack
        Core Id: 7, Cmd: sudo mount -t nfs $(netstat -nr | grep '^0.0.0.0' | awk '{print $2}'):/data/nfsBak/ /socrepack
        Core Id: 7, Cmd: [ -e /socrepack/socBak.sh ] && sudo chmod +x /socrepack/socBak.sh || exit 1
        Core Id: 7, Cmd: pushd /socrepack && sudo bash ./socBak.sh
        /socrepack ~
        The current path is "/socrepack"
        find /opt dir, the version is V22.09.02 or higher
        bakpack spi_flash start
        soc is bm1684
        output file is: fip.bin
        read 0x160000 bytes from flash @ 0x6000000 + 0x40000
        0x6000000 mapped at address 0x7fa1742000
        unmapped 0x7fa1742000
        output file is: spi_flash_bm1684.bin
        read 0x200000 bytes from flash @ 0x6000000 + 0x0
        0x6000000 mapped at address 0x7f97d3e000
        unmapped 0x7f97d3e000
        0+1 records in
        0+1 records out
        2097152 bytes (2.1 MB, 2.0 MiB) copied, 0.0618801 s, 33.9 MB/s
        bakpack spi_flash end
        /boot /socrepack
        tar boot ...
        /socrepack
        /socrepack/boot.tgz : 173386 KB
        need to expand boot from 131072 KB to 173386 KB
        /data /socrepack
        tar data ...
        /socrepack
        /socrepack/data.tgz : 194132 KB
        /opt /socrepack
        tar opt ...
        /socrepack
        /socrepack/opt.tgz : 600640 KB
        /recovery /socrepack
        tar recovery ...
        /socrepack
        /socrepack/recovery.tgz : 155224 KB
        / /socrepack
        tar rootfs flags : --exclude=./var/log/* --exclude=./boot/* --exclude=./recovery/* --exclude=./data/* --exclude=./media/* --exclude=./sys/* --exclude=./proc/* --exclude=./dev/* --exclude=./factory --exclude=./run/udev/* --exclude=./run/user/* --exclude=./socrepack --exclude=./opt/* ...
        /etc/systemd/system/basic.target.wants / /socrepack
        / /socrepack
        tar: ./run/rpcbind.sock: socket ignored
        tar: ./run/docker/libnetwork/40d9afc9140c.sock: socket ignored
        tar: ./run/docker/metrics.sock: socket ignored
        tar: ./run/docker.sock: socket ignored
        tar: ./run/containerd/containerd.sock: socket ignored
        tar: ./run/containerd/containerd.sock.ttrpc: socket ignored
        tar: ./run/irqbalance/irqbalance383.sock: socket ignored
        tar: ./run/dbus/system_bus_socket: socket ignored
        tar: ./run/avahi-daemon/socket: socket ignored
        tar: ./run/acpid.socket: socket ignored
        tar: ./run/systemd/journal/io.systemd.journal: socket ignored
        tar: ./run/systemd/journal/socket: socket ignored
        tar: ./run/systemd/journal/stdout: socket ignored
        tar: ./run/systemd/journal/dev-log: socket ignored
        tar: ./run/systemd/journal/syslog: socket ignored
        tar: ./run/systemd/userdb/io.systemd.DynamicUser: socket ignored
        tar: ./run/systemd/private: socket ignored
        tar: ./run/systemd/notify: socket ignored
        tar: ./run/systemd/inaccessible/sock: socket ignored
        tar: ./tmp/perfetto-consumer: socket ignored
        tar: ./tmp/perfetto-producer: socket ignored
        /socrepack
        /socrepack/rootfs.tgz : 2937924 KB
        need to expand rootfs from 2621440 KB to 2937924 KB
        partition table size : 12650894 KB
        The generated file partition32G.xml can replace file bootloader-arm64/scripts/partition32G.xml in VXX
        or replace some information for 3.0.0
        <physical_partition size_in_kb="20971520">
                <partition label="BOOT"       size_in_kb="173386"  readonly="false"  format="1" />
                <partition label="RECOVERY"   size_in_kb="3145728"  readonly="false" format="2" />
                <partition label="MISC"       size_in_kb="10240"  readonly="false"   format="0" />
                <partition label="ROOTFS"     size_in_kb="2937924" readonly="true"   format="2" />
                <partition label="ROOTFS_RW"  size_in_kb="6291456" readonly="false"  format="2" />
                <partition label="OPT"        size_in_kb="2097152" readonly="false"  format="2" />
                <partition label="DATA"       size_in_kb="4194304" readonly="false"  format="2" />
        </physical_partition>
        /data/nfsBak /data/zztTemp/bmsec
        start building ...

        To continue, superuser credentials are required.
        generating update files
        Image Name:   boot
        Created:      Mon Oct  9 18:24:29 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    742 Bytes = 0.72 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 734 Bytes = 0.72 KiB = 0.00 MiB
        Image Name:   boot_spif
        Created:      Mon Oct  9 18:24:29 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    642 Bytes = 0.63 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 634 Bytes = 0.62 KiB = 0.00 MiB
        expr: non-integer argument
        Image Name:   boot_emmc-gpt
        Created:      Mon Oct  9 18:24:29 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    710 Bytes = 0.69 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 702 Bytes = 0.69 KiB = 0.00 MiB
        mkfs.fat 4.1 (2017-01-24)
        mke2fs 1.45.5 (07-Jan-2020)
        Discarding device blocks: done                            
        Creating filesystem with 786432 4k blocks and 196608 inodes
        Filesystem UUID: 93cc04d8-bbeb-423e-9424-c360f52158a7
        Superblock backups stored on blocks: 
                32768, 98304, 163840, 229376, 294912

        Allocating group tables: done                            
        Writing inode tables: done                            
        Creating journal (16384 blocks): done
        Writing superblocks and filesystem accounting information: done 

        /data/nfsBak/tftp/recovery: 13/196608 files (7.7% non-contiguous), 44237/786432 blocks
        resize2fs 1.45.5 (07-Jan-2020)
        Resizing the filesystem on /data/nfsBak/tftp/recovery to 43440 (4k) blocks.
        The filesystem on /data/nfsBak/tftp/recovery is now 43440 (4k) blocks long.

        misc partition has no filesystem
        mke2fs 1.45.5 (07-Jan-2020)
        Discarding device blocks: done                            
        Creating filesystem with 734481 4k blocks and 183632 inodes
        Filesystem UUID: 06dc88fc-afeb-4020-ab2a-e6529a26e651
        Superblock backups stored on blocks: 
                32768, 98304, 163840, 229376, 294912

        Allocating group tables: done                            
        Writing inode tables: done                            
        Creating journal (16384 blocks): done
        Writing superblocks and filesystem accounting information: done 

        /data/nfsBak/tftp/rootfs: 64949/183632 files (0.1% non-contiguous), 633536/734481 blocks
        resize2fs 1.45.5 (07-Jan-2020)
        The filesystem is already 734481 (4k) blocks long.  Nothing to do!

        mke2fs 1.45.5 (07-Jan-2020)
        Discarding device blocks: done                            
        Creating filesystem with 1572864 4k blocks and 393216 inodes
        Filesystem UUID: b0e9fc1e-b1dd-41b6-9d83-63a3fc26cf26
        Superblock backups stored on blocks: 
                32768, 98304, 163840, 229376, 294912, 819200, 884736

        Allocating group tables: done                            
        Writing inode tables: done                            
        Creating journal (16384 blocks): done
        Writing superblocks and filesystem accounting information: done 

        rootfs_rw may be an empty parition.
        /data/nfsBak/tftp/rootfs_rw: 11/393216 files (0.0% non-contiguous), 47214/1572864 blocks
        resize2fs 1.45.5 (07-Jan-2020)
        Resizing the filesystem on /data/nfsBak/tftp/rootfs_rw to 29277 (4k) blocks.
        The filesystem on /data/nfsBak/tftp/rootfs_rw is now 29277 (4k) blocks long.

        mke2fs 1.45.5 (07-Jan-2020)
        Discarding device blocks: done                            
        Creating filesystem with 524288 4k blocks and 131072 inodes
        Filesystem UUID: 51293ee9-e4c8-4246-ad9c-b48a50bf447f
        Superblock backups stored on blocks: 
                32768, 98304, 163840, 229376, 294912

        Allocating group tables: done                            
        Writing inode tables: done                            
        Creating journal (16384 blocks): done
        Writing superblocks and filesystem accounting information: done 

        /data/nfsBak/tftp/opt: 915/131072 files (0.4% non-contiguous), 150710/524288 blocks
        resize2fs 1.45.5 (07-Jan-2020)
        Resizing the filesystem on /data/nfsBak/tftp/opt to 250334 (4k) blocks.
        The filesystem on /data/nfsBak/tftp/opt is now 250334 (4k) blocks long.

        mke2fs 1.45.5 (07-Jan-2020)
        Discarding device blocks: done                            
        Creating filesystem with 1048576 4k blocks and 262144 inodes
        Filesystem UUID: 62769a42-099c-4955-a801-89f11a7ba6b4
        Superblock backups stored on blocks: 
                32768, 98304, 163840, 229376, 294912, 819200, 884736

        Allocating group tables: done                            
        Writing inode tables: done                            
        Creating journal (16384 blocks): done
        Writing superblocks and filesystem accounting information: done 

        /data/nfsBak/tftp/data: 63/262144 files (1.6% non-contiguous), 59874/1048576 blocks
        resize2fs 1.45.5 (07-Jan-2020)
        Resizing the filesystem on /data/nfsBak/tftp/data to 51767 (4k) blocks.
        The filesystem on /data/nfsBak/tftp/data is now 51767 (4k) blocks long.

        Image Name:   boot_emmc-boot
        Created:      Mon Oct  9 18:26:08 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    1374 Bytes = 1.34 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 1366 Bytes = 1.33 KiB = 0.00 MiB
        Image Name:   boot_emmc-recovery
        Created:      Mon Oct  9 18:26:22 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    1386 Bytes = 1.35 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 1378 Bytes = 1.35 KiB = 0.00 MiB
        Image Name:   boot_emmc-misc
        Created:      Mon Oct  9 18:26:22 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    764 Bytes = 0.75 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 756 Bytes = 0.74 KiB = 0.00 MiB
        Image Name:   boot_emmc-rootfs
        Created:      Mon Oct  9 18:31:47 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    18592 Bytes = 18.16 KiB = 0.02 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 18584 Bytes = 18.15 KiB = 0.02 MiB
        Image Name:   boot_emmc-rootfs_rw
        Created:      Mon Oct  9 18:31:51 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    1414 Bytes = 1.38 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 1406 Bytes = 1.37 KiB = 0.00 MiB
        Image Name:   boot_emmc-opt
        Created:      Mon Oct  9 18:33:22 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    6279 Bytes = 6.13 KiB = 0.01 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 6271 Bytes = 6.12 KiB = 0.01 MiB
        Image Name:   boot_emmc-data
        Created:      Mon Oct  9 18:33:38 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    2009 Bytes = 1.96 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 2001 Bytes = 1.95 KiB = 0.00 MiB
        Image Name:   boot_emmc
        Created:      Mon Oct  9 18:33:38 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    1151 Bytes = 1.12 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 1143 Bytes = 1.12 KiB = 0.00 MiB
        awk: warning: regexp escape sequence `\:' is not a known regexp operator
        awk: warning: regexp escape sequence `\,' is not a known regexp operator
        awk: warning: regexp escape sequence `\:' is not a known regexp operator
        awk: warning: regexp escape sequence `\,' is not a known regexp operator
        Image Name:   /data/nfsBak/tftp/boot_emmc.cmd
        Created:      Mon Oct  9 18:33:38 2023
        Image Type:   AArch64 Linux Script (uncompressed)
        Data Size:    1153 Bytes = 1.13 KiB = 0.00 MiB
        Load Address: 00000000
        Entry Point:  00000000
        Contents:
        Image 0: 1145 Bytes = 1.12 KiB = 0.00 MiB
        build success.

        Received a kill signal. Cleaning up...
        Core Id: all, Cmd: sudo umount /socrepack
        umount: /socrepack: no mount point specified.
        umount: /socrepack: no mount point specified.
        umount: /socrepack: no mount point specified.
        umount: /socrepack: no mount point specified.
        umount: /socrepack: no mount point specified.
        ********core 7 run log************

        ********core 8 run log************

        ********core 9 run log************

        ********core 10 run log************

        ********core 11 run log************

        ********core 12 run log************

        bakpack files in /data/nfsBak/:
        total 1.2G
        drwxrwxrwx  3 linaro linaro 4.0K Oct  9 18:24 .
        drwxrwxrwx 14 linaro linaro 4.0K Oct  9 13:42 ..
        -rwxr-xr-x  1 root   root    16K Oct  9 18:24 bm_make_package.sh
        -rw-r--r--  1 root   root    26M Oct  9 18:16 boot.tgz
        -rw-r--r--  1 root   root    35M Oct  9 18:17 data.tgz
        -rw-r--r--  1 root   root   1.4M Oct  9 18:16 fip.bin
        -rwxr-xr-x  1 root   root    19K Oct  9 18:24 mk_gpt
        -rw-r--r--  1 root   root   160M Oct  9 18:18 opt.tgz
        -rw-r--r--  1 root   root    660 Oct  9 18:24 partition32G.xml
        -rw-r--r--  1 root   root    23M Oct  9 18:18 recovery.tgz
        -rw-r--r--  1 root   root   918M Oct  9 18:24 rootfs.tgz
        -rwxr-xr-x  1 root   root   6.6K Oct  9 18:16 socBak.sh
        -rwxr-xr-x  1 root   root   6.0M Oct  9 18:16 spi_flash.bin
        -rw-r--r--  1 root   root   2.0M Oct  9 18:16 spi_flash_bm1684.bin
        drwxr-xr-x  2 root   root   4.0K Oct  9 18:33 tftp
        ```
17. **添加控制板到算力核心的端口映射 [pt \<opt> [\<hostIp> \<id> \<host-port> \<core-port> \<protocol>]]**
    - 注：该功能只能配置与算力节点相关的端口映射
    - 参数：
        - `<opt>`：选项
            - add 添加一个临时规则
            - del 删除一个临时规则
            - edit 编辑配置文件
            - run 执行配置文件
            - ls 展示当前映射表
        - `<hostIp>`：添加/删除规则的目的ip，适用于add/del。
        - `<id>`：算力核心id，用于指定目标算力核心，唯一，适用于add/del。
        - `<host-port>`：控制板端口，适用于add/del。
        - `<core-port>`：算力板端口，适用于add/del。
        - `<protocol>`：使用协议udp/tcp，适用于add/del。

    - 说明：通过此功能，用户可以添加端口映射。
    - 命令行模式示例：
        - `bmsec pt add 172.26.166.66 8 10000 22 tcp` 添加算力节点8的22到控制板172.26.166.66:10000的映射
        - `bmsec pt ls` 查看当前控制板的端口映射情况
        - `bmsec pt del 172.26.166.66 8 9022 22 tcp` 删除算力节点8的22到控制板172.26.166.66:9022的映射
    - 交互式模式示例：输入`bmsec`后输入该功能编号`17`,然后输入需要执行的命令`ls`
    - 输出示例:
    
        ``` bash
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pt add 172.26.166.66 8 10000 22 tcp
        Opt : add, Core Id: 8, Remote:22 -> Local:10000
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pt ls
        TYPE HOST-IP          HOST-PORT    (CORE-IP ID)          CORE-PORT    
        tcp  172.26.166.66    20021        (172.16.150.11 7)  22           
        udp  172.26.166.66    21081:21082  (172.16.150.11 7)  21081-21082  
        tcp  172.26.166.66    20022        (172.16.150.12 8)  22           
        udp  172.26.166.66    22081:22082  (172.16.150.12 8)  22081-22082  
        tcp  172.26.166.66    20023        (172.16.150.13 9)  22           
        udp  172.26.166.66    23081:23082  (172.16.150.13 9)  23081-23082  
        tcp  172.26.166.66    20024        (172.16.150.14 10) 22           
        udp  172.26.166.66    24081:24082  (172.16.150.14 10) 24081-24082  
        tcp  172.26.166.66    20025        (172.16.150.15 11) 22           
        udp  172.26.166.66    25081:25082  (172.16.150.15 11) 25081-25082  
        tcp  172.26.166.66    20026        (172.16.150.16 12) 22           
        udp  172.26.166.66    26081:26082  (172.16.150.16 12) 26081-26082  
        tcp  172.26.166.66    9000         (172.16.150.12 8)  22           
        tcp  172.26.166.66    9022         (172.16.150.12 8)  22           
        tcp  172.26.166.66    9022         (172.16.150.12 8)  22           
        tcp  172.26.166.66    10000        (172.16.150.12 8)  22           
        tcp  172.26.166.66    9022         (172.16.150.12 8)  22           
        tcp  172.26.166.66    10000        (172.16.150.12 8)  22           

        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pt del 172.26.166.66 8 9022 22 tcp
        Opt : del, Core Id: 8, Remote:22 -> Local:9022
        linaro@AE0026-host:/data/zztTemp/bmsec$ bmsec pt ls
        TYPE HOST-IP          HOST-PORT    (CORE-IP ID)          CORE-PORT    
        tcp  172.26.166.66    20021        (172.16.150.11 7)  22           
        udp  172.26.166.66    21081:21082  (172.16.150.11 7)  21081-21082  
        tcp  172.26.166.66    20022        (172.16.150.12 8)  22           
        udp  172.26.166.66    22081:22082  (172.16.150.12 8)  22081-22082  
        tcp  172.26.166.66    20023        (172.16.150.13 9)  22           
        udp  172.26.166.66    23081:23082  (172.16.150.13 9)  23081-23082  
        tcp  172.26.166.66    20024        (172.16.150.14 10) 22           
        udp  172.26.166.66    24081:24082  (172.16.150.14 10) 24081-24082  
        tcp  172.26.166.66    20025        (172.16.150.15 11) 22           
        udp  172.26.166.66    25081:25082  (172.16.150.15 11) 25081-25082  
        tcp  172.26.166.66    20026        (172.16.150.16 12) 22           
        udp  172.26.166.66    26081:26082  (172.16.150.16 12) 26081-26082  
        tcp  172.26.166.66    9000         (172.16.150.12 8)  22           
        tcp  172.26.166.66    9022         (172.16.150.12 8)  22           
        tcp  172.26.166.66    10000        (172.16.150.12 8)  22           
        tcp  172.26.166.66    9022         (172.16.150.12 8)  22           
        tcp  172.26.166.66    10000        (172.16.150.12 8)  22       
        linaro@BB0043-host:~$ bmsec pt edit
        # 算力节点ID 算力节点端口 对外端口 协议 网口
        # Computing_Node_ID Computing_Node_Port External_Port Protocol Network_Interface
        #1 23444 13322 tcp enp3s0
        #2 44534 12314 udp enp3s0
        8 22 8022 tcp enp3s0
        linaro@BB0043-host:~$ bmsec pt run
        Opt : run
        core id: 7, core port: 22 -> local port: 8022
        linaro@BB0043-host:~$ bmsec pt ls
        TYPE HOST-IP          HOST-PORT    (CORE-IP ID)          CORE-PORT    
        tcp  172.26.166.158   20021        (172.16.150.11 7)  22           
        udp  172.26.166.158   21081:21082  (172.16.150.11 7)  21081-21082  
        tcp  172.26.166.158   10021        (172.16.140.11 1)  22           
        udp  172.26.166.158   11081:11082  (172.16.140.11 1)  11081-11082  
        tcp  172.26.166.158   20022        (172.16.150.12 8)  22           
        udp  172.26.166.158   22081:22082  (172.16.150.12 8)  22081-22082  
        tcp  172.26.166.158   10022        (172.16.140.12 2)  22           
        udp  172.26.166.158   12081:12082  (172.16.140.12 2)  12081-12082  
        tcp  172.26.166.158   20023        (172.16.150.13 9)  22           
        udp  172.26.166.158   23081:23082  (172.16.150.13 9)  23081-23082  
        tcp  172.26.166.158   10023        (172.16.140.13 3)  22           
        udp  172.26.166.158   13081:13082  (172.16.140.13 3)  13081-13082  
        tcp  172.26.166.158   20024        (172.16.150.14 10) 22           
        udp  172.26.166.158   24081:24082  (172.16.150.14 10) 24081-24082  
        tcp  172.26.166.158   10024        (172.16.140.14 4)  22           
        udp  172.26.166.158   14081:14082  (172.16.140.14 4)  14081-14082  
        tcp  172.26.166.158   20025        (172.16.150.15 11) 22           
        udp  172.26.166.158   25081:25082  (172.16.150.15 11) 25081-25082  
        tcp  172.26.166.158   10025        (172.16.140.15 5)  22           
        udp  172.26.166.158   15081:15082  (172.16.140.15 5)  15081-15082  
        tcp  172.26.166.158   20026        (172.16.150.16 12) 22           
        udp  172.26.166.158   26081:26082  (172.16.150.16 12) 26081-26082  
        tcp  172.26.166.158   10026        (172.16.140.16 6)  22           
        udp  172.26.166.158   16081:16082  (172.16.140.16 6)  16081-16082  
        udp  172.26.166.158   8554:8555    (172.16.140.11 1)  8554-8555    
        tcp  172.26.166.158   8022         (172.16.150.12 8)  22          
        ```
18. **设置网络模式 [netconf \<opt>]**
    - 注：该功能可以在控制板设置4种网络模式，详情请参考参数\<opt>的描述。如果从模式1、2、3切换至其他模式，您需先执行`bmsec netconf 0`切换至模式0，然后重启，再切换到其他模式。当设备处于模式1/3时，如果重启了设备，请在开机5分钟后重新执行`bmsec netconf <opt>`命令，设置网络模式为1/3。
    - 参数：
        - `<opt>`：选项
            - 0 : 模式0，DHCP4端口转发模式，本模式为默认模式
            - 1 : 模式1，网桥模式
            - 2 : 模式2，GE1、GE2网口聚合模式
            - 3 : 模式3，网桥 ＋ GE1、GE2网口聚合模式

    - 说明：通过此功能，用户可以配置网络模式。
    - 命令行模式示例：
        - 模式0: `bmsec netconf 0`   
        - 模式1: `bmsec netconf 1`   
        - 模式2: `bmsec netconf 2`   
        - 模式3: `bmsec netconf 3`   
    - 输出示例:

        模式1：网桥模式

        ```bash
        se6@se6-desktop:~$ bmsec netconf 1
        [info] config bridges...
        [info] Mode is set to 1
        [info] set all cores as DHCP MODE!
        [info] setting bridges in netplan yaml file...
        [info] backup /etc/netplan/01-network-manager-all.yaml
        [info] config netplan...
        [info] Update completed: 'wanname=br0' added.
        ```

        模式2：GE1、GE2网口聚合模式

        ```bash
        se6@se6-desktop:~$ bmsec netconf 2
        [sudo] password for se6: 
        [info] config bonding...
        [info] Mode is set to 2
        [info] Bonding mode!
        [info] config netplan...
        # Let NetworkManager manage all devices on this system
        network:
            version: 2
            renderer: NetworkManager
            bonds:
                            bond0:
                                    interfaces: [eno5,eno6]
                                    dhcp4: yes
                                    addresses: [172.26.166.141/24]
                                    nameservers:
                                            addresses: [8.8.8.8]
                                    parameters:
                                            mode: balance-rr
        [info] Update completed:'wanname=bond0' added.
        ```

        模式3：网桥 ＋ GE1、GE2网口聚合模式

        ```bash
        se6@se6-desktop:~$ bmsec netconf 3
        [sudo] password for se6:
        [info] config bridges and bonding...
        [info] mode is 3
        [info] set all cores as DHCP MODE!
        [info] setting bridges in netplan yaml file...
        [info] backup /etc/netplan/01-network-manager-all.yaml
        [info] Bonding and Bridge mode!
        [info] config netplan...
        # Let NetworkManager manage all devices on this system
        network:
            version: 2
            renderer: NetworkManager
            bonds:
                        bond0:
                                interfaces: [eno5,eno6]
                                dhcp4: no
                                addresses:[]
                                nameservers:
                                        addresses: []
                                parameters:
                                        mode: balance.rr
            bridges:
                        br0:
                                interfaces: [bond0, eno1, eno3]
                                dhcp4: yes
                                addresses:[172,26,166,141/24, 198,54.140.200/24, 198.54.150.200/24]
                                nameservers:
                                        addresses: [8.8.8.8]
        [info] Update completed:'wanname=br0' added.
        ```
    
        模式0：DHCP4端口转发模式

        ```bash
        se6@se6-desktop:~$ bmsec netconf 0
        [info] default config...
        [info] Mode is set to 0
        [info] reset network config of all cores
        [info] bridge flag is 0
        [info] reset host netplan config...
        [info] config bond0 down and remove bonding! 
        [info] please reboot!   
        ```