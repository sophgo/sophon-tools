# socbak工具

## 适用场景

* 芯片：BM1684 BM1684X BM1688 CV186AH
* SDK版本：
  * 84&X 3.0.0以及之前版本（适配只打包功能）
  * 84&X 3.0.0之后版本（适配只打包功能和打包做包功能）
  * 1688/186 V1.3以及之后版本（适配只打包功能和打包做包功能）
* 环境需求：
  * 外置存储： 
    * 存储分区格式尽量保证ext4，防止特殊分区限制导致做包失败
    * 只打包功能要求外置存储至少是当前emmc使用总量的1.5倍以上
    * 打包做包功能要求外置存储至少是当前emmc使用总量的2.5倍以上
  * 设备需求：
    * 只打包功能要求除去打包设备外需要有一个ubuntu18/20的X86主机
    * 做包功能只要求有一个打包做包的设备

## 打包做包功能

本功能84&4和1688/186平台使用方式完全一致

请在本仓库release页面下载最新的socbak.zip文件

请尽可能关闭正在运行的业务

将外置存储插入目标设备，然后执行如下操作

``` bash
sudo su
cd /
mkdir socrepack
# 这一步需要根据你的外置存储选择挂载设备路径，但是目标路径必须是/socrepack
mount /dev/sda1 /socrepack
chmod 777 /socrepack
cd /socrepack
```

然后将之前下载的socbak.zip传输到/socrepack目录下

执行如下命令进行打包

``` bash
unzip socbak.zip
cd socbak
export SOC_BAK_ALL_IN_ONE=1
bash socbak.sh
```

等待一段时间

执行成功后会生成如下文件

``` bash
root@sophon:/socrepack/socbak# tree -L 1
.
├── binTools
├── output
├── script
├── socbak.sh
├── socbak_log.log
└── socbak_md5.txt
 
3 directories, 3 files
```

其中socbak_log.log文件是执行的信息记录，刷机包在output/sdcard/路径下

## 实例视频

https://github.com/user-attachments/assets/97f754e1-c575-4859-aaf8-8e9d60daeba9
