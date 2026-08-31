# 不能用于启动业务程序（可启动systemd服务），仅用于SE6/8运维工具
## se6/se8易用性工具
此应用针对se6/se8的易用性工具，共有两种运行方式: 

1. 交互运行方式直接运行 `bmsec`
2. 命令行直接运行

### 命令行运行指示:

#### 参数含义

* `<localFile>`：本地文件地址
* `<remoteFile>`：远程目标地址
* `<id>`：算力板id
* `<cmd>`：需要在目标算力板上执行的命令

#### 运行实例

* 远程运行一条命令
  * bmsec run all ls
  * 在所有算力板上执行ls
* 上传一个文件
  * bmsec pf all /data/example.txt /data
  * 例如将控制板上的`data/example.txt`文件传至所有算力板的`/data`目录：
* 算力核心内存布局操作
  * bmsec cmem all p
  * 打印所有算力核心内存布局
  * bmsec cmem 1 c 2048 1024 1024
  * 将算力核心1的内存布局修改为NPU:2048MiB VPU:1024MiB VPP:1024MiB

### 功能列表

1. 打印帮助文档 [help]
2. 打印配置信息 [pconf] 
3. 远程执行命令 [run \<id> \<cmd>]
4. 获取所有远程设备信息 [getbi]  
5. 上传文件 [pf \<id> \<localFile> \<remoteFile>]
6. 下载文件 [df \<id> \<remoteFile> \<localFile>]
7. 链接指定ssh [ssh \<id>]
8. 重启某个算力节点电源 [reset \<id>]
9.  链接指定算力节点调试串口 [uart \<id>]
10. 打印指定算力节点调试串口 [puart \<id>]
11. 使用控制板自带刷机包升级指定算力板 [update \<id>]
12. 检查当前tftp升级进度 [tftpc]
13. 启动NFS服务并共享到算力板 [nfs \<localFile> \<remoteFile>]
14. 批量修改内存布局 [cmem \<id> {\<p> / < \<c> \<npuSize> \<vpuSize> \<vppSize> >} [dtsFile]]
15. 重新生成算力核心配置信息 [rconf]
16. 将指定算力核心的环境进行打包，可选生成tftp刷机包和仅打半成品包 [sysbak \<id> \<localPath>]
17. 通过此功能，用户可以编辑端口映射 [pt \<opt> [\<hostIp> \<id> \<host-port> \<core-port> \<protocol>]]
[onlyBak]]

## 注意事项

在进行配置后(第一次运行自动配置，可以通过rconf命令重置)

如果修改了算力核心的SSH端口和密码等参数，需要修改安装目录的configs/sub/subInfo.12文件中对应的参数

## 更新方式

在我们的SFTP服务器106.37.111.18:32022上，公开账密为open:open，位置在/tools/bmsec下，下载deb包后使用`dpkg -i`安装即可
