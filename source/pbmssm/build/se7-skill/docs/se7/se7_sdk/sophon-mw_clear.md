# 视频解码

## 常见问题

### 如何判断视频花屏的原因

答：这里提的视频花屏是长时间的花屏，对于偶尔的花屏有可能是网络数据传输错误导致的，此类不属于应用代码可控的方位。如果视频出现长时间的花屏，很大概率是由于视频帧读取不及时，导致内部缓存满以后，socket recv buffer溢出导致的。

1. 将加大rmem_max到2M，如果此时花屏消失，说明应用的数据处理抖动很大，应该要加大buffer queue进行平滑

   ```
   echo 2097152 > /proc/sys/net/core/rmem_max
   ```

2. 用netstat -na, 一般是一下格式，找到rtsp的那个端口（udp在应用中会有打印，tcp的话可以看目标rtsp地址），这里的Recv-Q, Send-Q在正常情况应该都是0，或者不满的，如果Recv-Q经常有很大的数，就说明overflow了。一般Send-Q不会出问题，如果这个也很大的话，那么很可能network driver驱动挂死了。

   ```
   Proto Recv-Q Send-Q Local Address Foreign Address State
   tcp 0 0 0.0.0.0:111 0.0.0.0:* LISTEN
   ```

### 解码不正确或者无法解码的最终调试手段

答：如果经常各种调试后，在现场仍然无法解决问题，可以通过打开环境变量，把问题发生前后的数据dump下来，供后续进行进一步分析

在PCIE模式下

```
export BMVID_PCIE_DUMP_STREAM_NUM=1000
```

dump的数据在/data/下（需要创建该文件夹并且有写权限），dump的数据根据core index和instance index存储。

在SOC模式下

```
echo "0  0 1000 100" > /proc/vpuinfo
echo "0  1 1000 100" > /proc/vpuinfo
......
echo "0 31 1000 100" > /proc/vpuinfo

echo "1  0 1000 100" > /proc/vpuinfo
echo "1  1 1000 100" > /proc/vpuinfo
......
echo "1 31 1000 100" > /proc/vpuinfo
```

(dump第1个core的第1个instance的码流数据)

这个配置会在两个文件之间循环存储1000帧数据，当问题发生的时候，把这两个发生前后的那个1000帧文件拷贝回来就可以。两个文件的存储位置在/data/core_%dinst%d_stream%d.bin.

停止保存码流

```
echo "0  0 0 0" > /proc/vpuinfo
echo "0  1 0 0" > /proc/vpuinfo
......
echo "0 31 0 0" > /proc/vpuinfo

echo "1  0 0 0" > /proc/vpuinfo
echo "1  1 0 0" > /proc/vpuinfo
......
echo "1 31 0 0" > /proc/vpuinfo
```

（注意：PCIE需要提前准备/data/目录的写权限）

### 判断rtsp是否正常工作

答：

方法一：通过vlc播放视频(推荐)，分别设置tcp，udp方式

方法二：使用vidmutil测试程序播放，vidmutil默认是 udp方式，通过设置环境变量使用tcp方式。

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|buffer_size;1024000|max_delay;50000"
sudo -E ./vidmulti thread_num input_video [card] [enc_enable] input_video [card] [enc_enable]...
```

### 播放rtsp流出现断连情况验证

答：可以使用vlc播放相同的视频，在相同的时间下，看vlc播放是否有断连的情况，注意设置vlc的缓冲区大小。

### 验证当前rtsp服务输出的视频是否有花屏

答：使用vlc播放视频，持续一段时间，看视频是否有花屏

### 查看rtsp服务是否实时推流

答：通过rtspserver日志，查看当前播放的文件是否正在发送。

### ffmpeg&opencv 支持 gb28181 协议，传入的url地址形式如下

答：

**udp实时流地址**

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip：本地ip，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同.同一个核心板端口不可重复。
```

**udp回放流地址**

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=\35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype：录像存储累类型
localid：本地20位编码，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
localip：本地ip，可选项
localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同.同一个核心板端口不可重复。
begtime：录像起始时间
endtime：录像结束时间
```

**tcp实时流地址**

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
localid：本地20位编码，可选项
localip: 本地ip，是可选项.不设置会获取 eth0 的ip，如果没有eth0需要手动设置
```

**tcp回放流地址**

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713
34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
deviceid：前段设备20位编码
devicetype :录像存储累类型
localid :本地20位编码，可选项
localip :本地ip，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
begtime :录像起始时间
endtime :录像结束时间
```

**注意**

1. 流媒体传输默认是udp方式，如果使用tcp方式获取实时流或回放流，需要显示的指定。

   Ffmpeg指定tcp方式为接口调用 通过av_dict_set设置 gb28181_transport_rtp 为tcp。

   Opencv指定方式是设置环境变量

   ```
   export OPENCV_FFMPEG_CAPTURE_OPTIONS="gb28181_transport_rtp;tcp"
   ```

2. 如果使用udp方式外部无法访问到内部ip/port，localmediaport需要做端口映射，端口映射需要两个 rtp和rtcp。

3. 做端口映射时，使用的端口号尽量不要太大，推荐10000--20000的端口，socket端口号的最大值时65536，但是很情况下，端口号是受很多资源的限制。端口号使用过大可能会出现：[bind failed] 错误打印。

### BM168x解码性能对于H264/H265有差别吗？如果调整码率的话，最多可以解多少路呢？有没有对应的数据参考？

答：

264,265是解码路数相同的。

码率对解码帧率会有影响，这个变化就需要实测，例如我们说的BM1684解码能达到960fps是针对监控码流而言的，这类监控码流没有B帧，场景波动较小，码率基本在2~4Mbps。如果是电影或者其他码率很高的，比如10Mbps，20Mbps甚至更多，是会有明显影响的，具体多大这个需要实测。

分辨率对于解码帧率的影响，是可以按照比例来换算的。我们说的960fps是针对1920x1080 HD分辨率而言的。

### 是否可以通过抽帧来提高BM168x的解码路数

答：

我们opencv中提供的抽帧，是在解码出来的结果中做的，并不是只解I/P帧的抽帧概念。这里的抽帧解码主要是保证出来帧数的均匀，使得后续的分析处理是等间隔的进行，这是为后续模型分析比较复杂的时候，不能达到每帧都检测而设计的解决方案，但并不能达到增加解码路数的效果。

这里顺便解释下，为什么不提供只解I/P帧的抽帧功能。如果只解I、P帧的话，抽帧的间隔就完全取决于码流的编码结构，这样是比较难控制住性能，比如监控码流中的没有B帧，那其实就相当于没有抽帧了。如果客户可以控制编码端，那更切合实际的做法是直接降低编码端的编码帧率，比如降到15fps，那样解码路数就可以直接提升；反之，如果客户没有办法控制编码端，那么同样的，只解IP帧的抽帧方式就也无法达到增加解码路数的效果。

### Valgrind内存检查为什么有那么多警告，影响到应用的调试了

答：

我们的版本发布每次都会用valgrind检查一遍内存泄漏问题，如果有内存泄露问题我们会检查修正的。之所以没有去掉有些警告，是因为这些警告大部分都是内存没有初始化，如果对这些内存每个都加上初始化，会明显导致速度性能下降，而且我们确认后续操作是在硬件对其赋值后再进行的，对于此类警告，我们就不会去消除。

为了避免警告过多对上层应用调试造成影响，建议使用valgrind的suppression功能，可以通过过滤配置文件，来避免我们模块产生的valgrind警告，从而方便上层应用调试自身的程序。

### 如何查看vpu/jpu的内存、使用率等状态

答：

在pcie模式下，可以用下面的方法查看：

```
cat /proc/bmsophon/card0/bmsophon0/media

cat /proc/bmsophon/card0/bmsophon0/jpu
```

在soc模式下，可以用下面的方法查看：

```
cat /proc/vpuinfo

cat /proc/jpuinfo
```

**vpuinfo 说明:**

```
"total_mem_size" : 178257920, "used_mem_size" : 153092096, "free_mem_size" : 25165824,
{"vdec_coreid":0, "link_num":1, "usage(instant|long)":8%|0%}
        {"channel" : "0", "res" : 1920x1088, "fps" : 50(25), "time" : 175127920, "in_frames" : 402, "out_frames" : 402,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 6},
{"vdec_coreid":1, "link_num":1, "usage(instant|long)":8%|0%}
        {"channel" : "0", "res" : 1920x1088, "fps" : 50(25), "time" : 175127946, "in_frames" : 373, "out_frames" : 373,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 6},
{"vdec_coreid":2, "link_num":1, "usage(instant|long)":6%|0%}
        {"channel" : "0", "res" : 1920x1088, "fps" : 50(25), "time" : 175127930, "in_frames" : 343, "out_frames" : 343,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 6},
{"vdec_coreid":3, "link_num":1, "usage(instant|long)":7%|0%}
        {"channel" : "0", "res" : 1920x1088, "fps" : 50(25), "time" : 175127950, "in_frames" : 314, "out_frames" : 314,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 6},
{"venc_coreid":4, "link_num":4, "usage(instant|long)":16%|0%}
        {"channel" : "0", "res" : 352x288, "fps" : 25(25), "time" : 175127922, "in_frames" : 401, "out_frames" : 401,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 1},
        {"channel" : "1", "res" : 352x288, "fps" : 25(25), "time" : 175127948, "in_frames" : 372, "out_frames" : 372,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 1},
        {"channel" : "2", "res" : 352x288, "fps" : 25(25), "time" : 175127932, "in_frames" : 342, "out_frames" : 342,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 1},
        {"channel" : "3", "res" : 352x288, "fps" : 25(25), "time" : 175127952, "in_frames" : 313, "out_frames" : 313,  "fail_frames" : 0,  "success_not_get" : 0,  "status" : 1},
```

参数说明:
- total_mem_size: 总的物理内存大小
- used_mem_size: 已使用的物理内存大小
- free_mem_size: 剩余可用的物理内存大小
- {"vdec_coreid":0, "link_num":1, "usage(instant|long)":8%|0%}: 显示这颗芯片上每个编解码和的占用情况
  - vdec_coreid: 1684有2个解码核，1个编码核
  - link_num: 在这个核上打开的总路数
  - usage(instant|long): instant显示当前解码核的利用率 long显示开机依赖解码核的利用率
- channel信息 显示每一路编解码的详细信息
  - channel: 通道号
  - res: 正在编解码视频的分辨率
  - fps: 帧率信息，前一个是视频本身的帧率，括号内的是实际编解码帧率
  - in_frames: 已经送入编解码器的帧数.可以通过设置环境变量修改更新频率"set VPUINFO_UPDATE_TIMES_MS=300" 表示每隔300ms更新一次;设置为0，表示实时更新;默认1秒更新一次
  - out_frames: 编解码器输出的帧数.可以通过设置环境变量修改更新频率"set VPUINFO_UPDATE_TIMES_MS=300" 表示每隔300ms更新一次;设置为0，表示实时更新;默认1秒更新一次
  - fail_frames: 编解码失败的帧数
  - success_not_get: 编解码成功尚未取走的帧数
  - status: 编解码器的状态

解码器状态如下：
- 0: 当前通道未被使用
- 1: 通道已创建但尚未加载完成
- 2: 通道已创建但未初始化
- 3: 通道正在初始化
- 4: 解码的分辨率不支持
- 5: 设置的framebuff数量过少
- 6: 正在解码中
- 7: framebuf 已满
- 8: 解码结束
- 9: 解码器停止工作
- 10: 解码器HUNG
- 11: 解码器关闭

编码器状态如下：
- 0: 当前通道未被使用
- 1: 正在编码

**jpuinfo 说明:**

```
JPU load balance:
JPU0 = 0
JPU1 = 0
{"core id":0, "open_status":0, "usage(short|long)":0%|0%},
{"instance":0, "status":2, "res":"1280*720", "decoded":243, "dec_errors":0, "last_dec_err":0, "encoded":255, "enc_errors":0, "last_enc_err":0, "fps":480}
{"core id":1, "open_status":0, "usage(short|long)":0%|0%},
{"instance":1, "status":2, "res":"1280*720", "decoded":263, "dec_errors":0, "last_dec_err":0, "encoded":250, "enc_errors":0, "last_enc_err":0, "fps":494}
```

参数说明:
- JPU load balance: 显示JPU的负载均衡情况
- JPU0 = 0 表示core0的完成的编解码任务数(cat /proc/jpuinfo 后重新计数)

# JPU信息说明

JPU1 = 0 表示core1的完成的编解码任务数(cat /proc/jpuinfo 后重新计数)

- `{"core id":0, "open_status":0, "usage(short|long)":0%|0%}` 表示当前core的工作状态
  - open_status: 0表示当前core未被使用，1表示当前core正在工作
  - usage(short|long): short表示当前core的瞬时利用率

- `{"instance":0, "status":2, "res":"1280*720", "decoded":243, "dec_errors":0, "last_dec_err":0, "encoded":255, "enc_errors":0, "last_enc_err":0, "fps":480}` 表示JPU0的编解码情况
  - instance: 表示当前core的实例编号
  - status: 表示当前core的编解码状态(1: 解码, 2: 编码)
  - res: 表示当前core的编解码分辨率
  - decoded: 表示当前core的解码帧数
  - dec_errors: 表示当前core的解码错误帧数
  - last_dec_err: 表示当前core的最后一次解码错误状态
    - INT_JPU_TIMEOUT = -1
    - INT_JPU_ERROR = 1
    - INT_JPU_BIT_BUF_EMPTY = 2
    - INT_JPU_PARIAL_OVERFLOW = 3
    - INT_JPU_BIT_BUF_STOP = 8
  - encoded: 表示当前core的编码帧数
  - enc_errors: 表示当前core的编码错误帧数
  - last_enc_err: 表示当前core的最后一次编码错误状态
    - INT_JPU_TIMEOUT = -1
    - INT_JPU_ERROR = 1
    - INT_JPU_BIT_BUF_FULL = 2
    - INT_JPU_PARIAL_OVERFLOW = 3
    - INT_JPU_BIT_BUF_STOP = 8
  - fps: 表示当前core的编解码帧率

## 视频支持32路甚至更多的时候，报视频内存不够使用，如何优化内存使用空间

**答：**

在PCIE板卡下，视频内存有3G，一般来说支持32路甚至更多的路数都绰绰有余。但在soc模式下，视频内存的默认配置是2G，正常使用在16路是绰绰有余的，但在32路视频需要在应用层面上仔细设计，不能有任何的浪费。

如果解码使用的是FFMPEG框架，首先保证视频输出格式使用压缩格式，即output_format 101。Opencv框架的话，内部已经默认使用压缩格式了；

其次如果应用在获取到解码输出avFrame后，并不是直接压入队列，而是转换到RGB或者非压缩数据后再缓存的话，可以用av_dict_set extra_frame_buffer_num为1（默认为2）。Opencv内部在最新版本中会默认优化。

最后，如果以上优化过后，仍然不够的话，在soc模式下可以考虑更改dtb设置，给视频挪用分配更多的内存，当然相应的，其他模块就要相应的减少内存。这个要从系统角度去调配。

## 启动设备首次执行某个函数慢，重启进程再次运行正常

**现象：** 设备上电后第一次执行程序，函数处理时间长，再次执行程序，运行正常。

**解决：** 先做个验证，如果不重启可复现，就说明是文件cache导致的变慢。

1. 上电后第一次执行慢，第二次执行正常，之后进入root用户
2. 清除cache echo 3 > /proc/sys/vm/drop_caches
3. 再次执行程序，运行慢，即可确定是cache导致的。

## [问题分析]程序提示"VPU_DecGetOutputInfo decode fail framdIdx xxx error(0x00000000) reason(0x00400000), reasonExt(0x00000000)"是可能什么问题，这里reason的具体数值可能不同

这个提示通常是由码流错误造成的，提示的含义是第xxx帧解码错误，错误原因为....。这里具体原因对于上层应用来说，不用关心，只需知道这是由码流错误导致的即可。

进一步分析，导致码流错误的原因通常可以分为两类，我们要有针对的进行处理。因为一旦频繁出现这种提示，说明解码出来的数据是不正确的，这时候有可能是各种马赛克或者图像花，对于后续的处理会造成各种异常情况，所以我们必须尽量减少这种情况的发生。

1. 网络情况导致的丢包。这时候可以用我们的测试程序vidmulti验证下，如果vidmulti没有解码错误，那么可以排除这种情况。如果确认网络丢包的话，要分辨下是否网络带宽本身就不够，如果本身带宽不够，那没有办法，只能降低视频码流的码率。如果带宽是够的，要检查下网线。当码流连接数超过20多路的时候，这时候有可能已经超出百兆了，这时网线也必须换到CAT6，与千兆网相匹配

2. 解码性能达到上限造成丢包。这种情况发生在流媒体环境中，对于文件播放是不会发生的。这时也可以用我们的vidmulti跑一下，作为比较。如果vidmulti也发生错误，说明性能确实到了上限了，否则说明应用本身还有优化的空间。

## [问题分析]程序提示"coreIdx 0 InstIdx 0: VPU interrupt wait timeout"，这是怎么回事?

这个提示表示视频解码或者编码中断超时。这个提示只是警告，会再次尝试，因此只要没有连续出现就可以忽略。这种情况一般是由解码数据错误导致或者负荷过重产生的。例如在板卡情况下，由于板卡数据交换过于频繁，造成解码或者编码数据传输堵塞，使得中断超时。

当这个报错连续出现时，可能代表解码器硬件已经挂死，可以通过以下两种方式获取解码器的状态：

1. 使用 bmvpu_dec_get_status 接口来获取解码器状态。若返回值为 BMDEC_HUNG（10），则表示解码器已经挂死；
2. 送流时报错。
   - (1) BmApi：bmvpu_dec_decode 报错 BM_ERR_VDEC_ERR_HUNG（-2）；
   - (2) FFmpeg：avcodec_send_packet 报错 AVERROR_EXTERNAL;
   - (3) OpenCV：cv::VideoCapture->get(cv::CAP_PROP_STATUS) == 2；

出现以上三种情况时，需要重置解码器来做复位。

## 申请设备内存失败，错误返回-24

设备内存每一次申请都会有一个fd，ubuntu上最大1024。如果持续申请且不释放，fd数量超过1024，就会导致申请设备内存失败，错误返回-24。
如果想扩大ubuntu的fd数量，可通过ulimit命令修改限制。如 ulimit -n 10000 可将ubuntu的fd数量扩大至10000。

## URL特殊字符对照表

有些符号在URL中是不能直接传递的，如果要在URL中传递这些特殊符号，需要使用其编码值。

编码的格式为：%加字符的ASCII码。

| 字符 | 编码值 |
|------|--------|
| 空格 | %20    |
| "    | %22    |
| #    | %23    |
| &    | %26    |
| (    | %28    |
| )    | %29    |
| +    | %2B    |
| ,    | %2C    |
| /    | %2F    |
| :    | %3A    |
| ;    | %3B    |
| <    | %3C    |
| =    | %3D    |
| >    | %3E    |
| ?    | %3F    |
| @    | %40    |
| \\   | %5C    |
| \|   | %7C    |

# bm_ffmpeg问题

## Ffmpeg的阻塞问题

**原因分析：** 如果没有及时释放avframe，就会导致阻塞，vpu内部是循环buffer。

## 无法连接rtsp？

**答：** 可以通过ffmpeg固有命令来进行连接测试：（url为rtsp连接地址）

```
ffmpeg -rtsp_transport tcp -i url -f rawvideo -y /dev/null
```

或者

```
ffmpeg -rtsp_transport udp -i url -f rawvideo -y /dev/null
```

若以上无法连接成功，请检查网络。

## 确认解码器是否能正常工作：（url为文件名或者rtsp连接地址）

**答：**

```
ffmpeg -i url -f rawvideo -y /dev/null
```

## FFMPEG JPEG 编码与转码应用示例

**答：**

- **调用JPEG编码的ffmpeg命令**

  ```
  ffmpeg -c:v jpeg_bm -i src/5.jpg -c:v jpeg_bm -is_dma_buffer 1 -y 5nx.jpg
  ```

- **调用动态JPEG转码的ffmpeg命令**

  ```
  ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.avi -c:v jpeg_bm -is_dma_buffer 1 -y test_avi.mov
  
  ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.mov -c:v jpeg_bm -is_dma_buffer 1 -y test_mov.mov
  ```

## 如何从FFMPEG的输入缓冲区中读取 bitstream?

**答：**

FFMPEG 源码应用示例
/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_reading.c (or http://www.ffmpeg.org/doxygen/trunk/doc_2examples_2avio_reading_8c-example.html)

在这一示例中，libavformat demuxer 通过 **custom AVIOContext read callback** 访问媒体信息，而不是通过在传入FFMPEG中的文件、rstp等协议访问媒体信息的。

以下是middleware-soc中的一个使用avio + jpeg_bm解码静态jpeg图片的例子。
(/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_decode_jpeg.c)

## 在soc模式下客户用ffmpeg解码时拿到AVframe将data[0-3] copy到系统内存发现copy时间是在20ms左右而相同数据量在系统内存两块地址copy只需要1-3ms

**答：** 上述问题的原因是系统在ffmpeg中默认是禁止cache的，因此用处理器 copy性能很低，使能cache就能达到系统内存互相copy同样的速度。

**方法1：** 可以用以下接口使能cache.

```
av_dict_set_int(&opts, "enable_cache", 1, 0);
```

**方法2：** 上述方法直接copy数据保存是非常占用内存、带宽和处理器算力。我们推荐采用以下两种零拷贝的方式来实现原始解码数据的保存：

1. 推荐使用 extra_frame_buffer_num 参数指定增大硬件帧缓存数量，可以根据自己的需要选择缓存帧的数量。
   这个方式的弊端，一个是占用解码器内存，可能减少视频解码的路数；另一个是当不及时释放，当缓存帧全部用完时，会造成视频硬件解码堵塞。

   ```
   av_dict_set_int(&opts, "extra_frame_buffer_num", extra_frame_buffer_num, 0);
   ```

2. 推荐使用 output_format参数设置解码器输出压缩格式数据，然后使用vpp处理输出非压缩yuv数据（当需要缩放，crop时，可以同步完成），
   然后直接零拷贝引用非压缩yuv数据。这种方式不会影响到硬件解码性能，并且可以缓存的数据空间也大很多。

   ```
   av_dict_set_int(&opts, "output_format", 101, 0);
   ```

## [问题分析]客户反馈碰到如下错误提示信息"VPU_DecRegisterFrameBuffer failed Error code is 0x3", 然后提示Allocate Frame Buffer内存失败

这个提示信息表示：分配的解码器缓存帧个数，超过了最大允许的解码帧。导致这个问题的原因有可能是：

1. 不支持的视频编码格式，比如场格式，此时可以用FAQ3.1.1.2的方法，把码流数据录下来，提交给我们分析。
2. 设置了过大的extra_frame_buffer_num。理论上，extra_frame_buffer_num不能超过15，超过了以后就有可能不能满足标准所需的最大缓存帧数。因为大部分编码码流并没有用到最大值，所以extra_frame_buffer_num大于15的时候，对大部分码流仍然是可以工作的。

目前发现可能导致这个问题的原因有上述两种，后续有新的案例继续增补

## 采用TCP传输码流的时候如果码流服务器停止推流，ffmpeg阻塞在av_read_frame

这是因为超时时间过长导致的，可以用一下参数设置超时时间减短。

```
av_dict_set(&options, "stimeout", "1000000", 0);
```

## 将 output_format 设置为101后，发现解压缩后的yuv花屏

这是因为输入码流的编码分辨率和显示分辨率存在差异导致的，avFrame中保存的是yuv的显示分辨率，而vpp解压缩需要使用编码分辨率。

解决方案是使用 AVCodecContext 中的 coded_width 和 coded_height 来作为宽高信息传递给vpp做解压缩。

## 解码器报错"lost a non key frame in first serveral packet..."

错误信息的含义是：送入的码流数据还未检测到第一个关键帧，无法开始解码。
造成这个问题的原因一般有两种情况：

1. 使用rtsp拉流，因为拉流的时间有随机性，无法保证拉取到的码流都是从I帧开始。这种情况可以忽略该报错，当第一个I帧到来后，就能够正常启动解码。
2. 用户自定义填充的avPacket（不使用av_read_frame来获取avPacket）。这种情况下一般是由于没有填充avPacket->flags造成的，需要根据帧类型正确填充avPacket->flags。
   关键帧应该将avPacket->flags赋值为AV_PKT_FLAG_KEY。

## 使用ffmpeg命令 "ffmpeg -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4" 进行转码时，程序卡死

提示如下错误信息：

```
[h264_bm @ 0x481190] bmvpu_dec_get_output timeout. dec_status:6 endof_flag=0 pkg:1
```

原因是默认的解码输出缓冲区配置较小，编码需要的参考帧较多，导致输出缓冲区不够用，解码器被block住。
解码器默认的输出缓冲区配置的比较小是考虑到设备内存的资源占用，并非所有使用场景都需要较大的输出缓冲区。

可以通过配置 "extra_frame_buffer_num" 参数来增加解码缓冲区。

例如采用以下命令：

```
ffmpeg -extra_frame_buffer_num 10 -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4
```

程序运行日志中会通过以下信息提示所需配置的解码缓冲区的大小，可以参考该信息进行配置。

```
[h264_bm @ 0x491500] Minimum number of input frame buffers for BM video encoder: 8
```

# bm_opencv问题

## opencv下如何获取视频帧的timestamp？

**答：** opencv原生提供了获取timestamp的接口，可以在cap.read()每一帧后获取当前帧的timestamp.

代码如下：

```
Mat frame;
cap.read(frame);
/* 获取timestamp，返回值为double类型 */
int64_t timestamp = (int64_t)cap.getProperty(CAP_PROP_TIMESTAMP);
```

## SA3 opencv下videocapture经常5分钟左右断网的解决方案

**答：** 在udp方式下,SA3经常发生RTSP数据连上后3-5分钟就"connection timeout"的问题，这个问题最终解决方案是更新最新的路由板软件。验证方法可以用TCP测试下，如果TCP没有问题可以确认是这类问题。

使用TCP的方式见下面：

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"
```

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）
注意：最新的middleware-soc将使用TCP作为默认协议，对原来客户需要使用UDP传输协议的，需要引导客户按照下面方式进行设置

使用UDP方式：

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;udp"
```

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）

UDP适用的环境：当网络带宽比较窄，比如4G/3G等移动通信系统，此时用udp比较合适
TCP适用的环境：网络带宽足够，对视频花屏要求比较高，对延时要求较小的应用场景，适合TCP

## 如何获取rtsp中原来的timestamp

**答：** opencv中默认获取的rtsp时间戳是从0开始的，如果想获取rtsp中的原始时间戳，可以用环境变量进行控制, 然后按照问题1进行获取即可

```
export OPENCV_FFMPEG_CAPTURE_OPTOINS="keep_rtsp_timestamp;1"
```

注意:外置的options会覆盖内部默认的设置，因此最好按照完整的options来设置

```
export OPENCV_FFMPEG_CAPTURE_OPTIONS="keep_rtsp_timestamp;1|buffer_size;1024000|max_delay;500000|stimeout;20000000"
```

## 确认解码器和vpp的OpenCV接口是否正常工作：

**答：**

```
vidmulti number_of_instances url1 url2
```

## 对于cvQueryFrame等老的opencv接口支持状况

**答：**

有些客户采用旧版opencv的C接口，接口列表如下

```
void cvReleaseCapture( CvCapture** pcapture )

IplImage* cvQueryFrame( CvCapture* capture )

int cvGrabFrame( CvCapture* capture )

IplImage* cvRetrieveFrame( CvCapture* capture, int idx )

double cvGetCaptureProperty( CvCapture* capture, int id )

int cvSetCaptureProperty( CvCapture* capture, int id, double value )

int cvGetCaptureDomain( CvCapture* capture)

CvCapture * cvCreateCameraCapture (int index)

CvCapture * cvCreateFileCaptureWithPreference (const char * filename, int apiPreference)

CvCapture
```

# cvCreateFileCapture (const char * filename)

对于这些接口，大部分都是支持的，只有返回值是iplImage的接口无法支持，这是因为我们硬件底层的ion内存类型是保存在MAT的uMatData类型中的，而iplIMage类型没有uMatData数据结构。

因此对于客户目前使用 cvQueryFrame接口的，建议客户基于cap.read接口封一个返回值为Mat数据的C函数接口，不要直接调用opencv老版的接口。

## Opencv中mat是如何分配设备内存和系统内存的？

答：

因为受设计影响，这个问题细节比较多，主要从三方面能解释。

1. 在soc模式下，设备内存和系统内存是同一份物理内存，通过操作系统的ION内存进行管理，系统内存是ION内存的mmap获得。在pcie模式下，设备内存和系统内存是两份物理内存，设备内存指BM168x卡上的内存，系统内存指服务器上操作系统内存。如果用户想只开辟系统内存，和开源opencv保持一致，可以参见FAQ3.4.3.5的回答。

2. 在sophon opencv中默认会同时开辟设备内存和系统内存，其中系统内存放在mat.u->data或mat.data中，设备内存放在mat.u->addr中。只有以下几种情况会不开辟设备内存，而仅提供系统内存：

   - 当data由外部开辟并提供给mat的时候。即用以下方式声明的时候：
     ```
     Mat mat(h, w, type, data); 或 mat.create(h, w, type, data)；
     ```

   - 在soc模式下，当type不属于（CV_8UC3, CV_32FC1, CV_32FC3）其中之一的时候。这里特别注意CV_8UC1是不开辟的，这是为了保证我们的opencv能够通过开源opencv的opencv_test_core的一致性验证检查。

   - 当宽或者高小于16的时候。因为这类宽高，硬件不支持

3. 在BM1682、BM1684和BM1684x的SOC模式下，mat分配的CV_8UC3类型的设备内存会自动做64对齐，即分配的内存大小一定是64对齐的（注意：仅对soc模式的CV_8UC3而言，且仅对BM1684、BM1684x和BM1682）。在PCIE模式下，分配的内存是byte对齐的。

## Opencv mat创建失败，提示"terminate called after throwing an instance of 'cv::Exception' what(): OpenCV(4.1.0) …… matrix.cpp:452: error: (-215:Assertion failed) u != 0 in function 'creat'"

答：

这种错误主要是设备内存分配失败。失败的原因有两种：

1. 句柄数超过系统限制，原因有可能是因为句柄泄漏，或者系统句柄数设置过小，可以用如下方法确认：

   查看系统定义的最大句柄数：
   ```
   ulimit -n
   ```

   查看当前进程所使用的句柄数：
   ```
   lsof -n|awk '{print $2}'|sort|uniq -c|sort -nr|more
   ```

2. 设备内存不够用。可以用如下方法确认：

   - SOC模式下
     ```
     cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary
     ```

   - PCIE模式下， bm-smi工具可以查看设备内存空间

解决方案：在排除代码本身的内存泄漏或者句柄泄漏问题后，可以通过加大系统最大句柄数来解决句柄的限制问题：ulimit -HSn 65536

设备内存不够就需要通过优化程序来减少对设备内存的占用，或者通过修改dts文件中的内存布局来增加对应的设备内存。详细可以参考SM5用户手册中的说明。

## Opencv用已有Mat的内存data，宽高去创建新的Mat后，新Mat保存的图像数据错行，显示不正常

答：保存的图像错行，通常是由于Mat中step信息丢失所造成。

一般用已有Mat去生成一个新Mat，并且要求内存复用时，可以直接赋值给新的Mat来简单实现，如 Mat1 = Mat2.

但在某些情况下，比如有些客户受限于架构，函数参数只能用C风格的指针传递，就只能用Mat中的data指针，rows，cols成员来重新恢复这个Mat。
这时候就需要注意step变量的设置，在默认情况下是AUTO_STEP配置，即每行数据没有填充数据。但是在很多种情况下，经过opencv处理后，会导致每行出现填充数据。如，

1. soc模式下，我们的Mat考虑执行效率，在创建Mat内存时每行数据会做64字节对齐，以适配硬件加速的需求（仅在soc模式下）
2. opencv的固有操作，如这个Mat是另一个Mat的子矩阵（即rect的选定区域），或者其他可能导致填充的操作。

因此，按照opencv定义，通用处理方式就是在生成新的Mat的时候必须指定step，如下所示:

```
cv::Mat image_mat = cv::imread(filename,IMREAD_COLOR,0);
cv::Mat image_mat_temp(image_mat.rows,image_mat.cols,CV_8UC3,image_mat.data,image_mat.step[0]);
cv::imwrite("sophgo1.jpg",image_mat_temp);
```

## 在opencv VideoCapture 解码视频时提示: maybe grab ends normally, retry count = 513

上述问题是因为在VideoCapture存在超时检测，如果在一定时间未收到有效的packet则会输出以上log，此时如果视频源是网络码流可以用vlc拉流验证码流是否正常，如果是文件一般是文件播放到末尾需调用VidoeCapture.release后重新VideoCapture.open

## SOC模式下，opencv在使用8UC1 Mat的时候报错，而当Mat格式为8UC3的时候，同样的程序完全工作正常。

这个问题碰到的客户比较多，这次专门设立一个FAQ以便搜索。其核心内容在FAQ3.1.3.6 "Opencv中mat是如何分配设备内存和系统内存的"有过介绍，可以继续参考FAQ3.1.3.6

在soc模式下，默认创建的8UC1 Mat是不分配设备内存的。因此当需要用到硬件加速的时候，比如推理，bmcv操作等，就会导致各种内存异常错误。

解决方案可以参看FAQ3.4.3.5 "如何指定Mat对象基于system memory内存去创建使用", 指定8UC1 Mat在创建的时候，内部使用ion分配器去分配内存。如下所示。

```
cv::Mat gray_mat;
gray_mat.allocator = hal::getAllocator();
gray_mat.create(h, w, CV_8UC1);
```

## 如何跨进程传递Mat信息，使不同进程间零拷贝地共享Mat中的设备内存数据？

跨进程共享Mat的障碍在于虚拟内存和句柄在进程间共享非常困难，因此解决这个问题的本质是：如何由一块设备内存，零拷贝地重构出相同的Mat数据结构。

解决这个问题会用到下面三个接口，其中前两个接口用于重构yuvMat的数据，后一个接口用于重构opencv 标准Mat的数据。

```cpp
cv::av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MMPEG, int id = 0)
cv::Mat(AVFrame *frame, int id)
Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data,unsigned long addr, int fd, int id = 0)
```

```cpp
/* 完整的跨进程共享Mat的代码如下所示。跨进程共享的方法很多，下面的例子目的在于展示如何
   使用上面的函数重构Mat数据，其他的代码仅供参考。其中image为需要被共享的Mat */
union ipc_mat{
    struct{
        unsigned long long addr;
        int total;
        int type;
        size_t step[2];
        int plane_size[4];
        int plane_step[4];
        int pix_fmt;
        int height;
        int width;
        int color_space;
        int color_range;
        int dev_id;
        int isYuvMat;
    }message;
    unsigned char data[128];
}signal;
memset(signal.data, 0, sizeof(signal));

if (isSender){  // 后面是send的代码
    int fd = open("./ipc_sample", O_WRONLY);
    signal.message.addr = image.u->addr;
    signal.message.height = image.rows;
    signal.message.width = image.cols;
    signal.message.isYuvMat = image.avOK() ? 1 : 0;
    if (signal.message.isYuvMat){  // 处理yuvMat
                            //avAddr(4~6)对应设备内存
        signal.message.plane_size[0] = image.avAddr(5) - image.avAddr(4);
        signal.message.plane_step[0] = image.avStep(4);

        signal.message.pix_fmt = image.avFormat();
        if (signal.message.pix_fmt == AV_PIX_FMT_YUV420P){
            signal.message.plane_size[2] =
            signal.message.plane_size[1] = image.avAddr(6) - image.avAddr(5);
            signal.message.plane_step[1] = image.avStep(5);
            signal.message.plane_step[2] = image.avStep(6);
        } else if (signal.message.pix_fmt == AV_PIX_FMT_NV12){
            signal.message.plane_size[1] = signal.message.plane_size[0] / 2;
            signal.message.plane_step[1] = image.avStep(5);
        }   // 此处仅供展示，更多的色彩格式可以继续扩展

        signal.message.color_space = image.u->frame->colorspace;
        signal.message.color_range = image.u->frame->color_range;

        signal.message.dev_id = image.card;
    } else { // 处理bgrMat
        signal.message.total = image.total();
        signal.message.type = image.type();
        signal.message.step[0] = image.step[0];
        signal.message.step[1] = image.step[1];
    }

    write(fd, signal.data, 128);

    while(1) sleep(1); //此处while(1)仅供举例，要注意实际应用中后面还需要close(fd)
} else if (!isSender){
    if ((mkfifo("./ipc_example", 0600) == -1) && errno != EEXIST){  // ipc共享仅供举例
        printf("mkfifo failed\n");
        perror("reason");
    }
    int fd = open("./ipc", O_RDONLY);
    Mat f_mat;  // 要重构的共享Mat
    int cnt = 0;

    while (cnt < 128){
        cnt += read(fd, signal.data+cnt, 128-cnt);
    }

    if(signal.message.isYuvMat) { // yuvMat
        AVFrame *f = cv::av::create(signal.message.height,
                                    signal.message.width,
                                    signal.message.pix_fmt,
                                    NULL,
                                    signal.message.addr,
                     /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                                    0,
                                    signal.message.plane_step,
                                    signal.message.plane_size,
                                    signal.message.color_space,
                                    signal.message.color_range,
                                    signal.message.dev_id);
        f_mat.create(f, signal.message.dev_id);
    } else {
        f_mat.create(signal.message.height,
                     signal.message.width,
                     signal.message.total,
                     signal.message.type,
                     signal.message.step,
                     NULL,
                     signal.message.addr,
                    /* 这里fd直接给0即可，其作用仅表示存在外部给的设备内存地址addr */
                     0,
                     signal.message.dev_id);
        bmcv::downloadMat(f_mat);
                    /* 注意这里需要将设备内存的数据及时同步到系统内存中。因为yuvMat使
                      用中约定设备内存数据永远是最新的，bgrMat使用中约定系统内存数据永远
                      是最新的，这是我们opencv中遵循的设计原则 */
    }
    close(fd);
}

/* 以上代码仅供参考，请使用者根据自己实际需要修改定制 */
```

# 视频编码

## 常见问题

### bm_ffmpeg问题

使用ffmpeg在pcie模式下进行编解码使用过滤器要注意指定sophon_idx。

1. 解码，编码，过滤器默认的sophon_idx都是0
2. HWAccel模式下：通过hwaccel_device指定卡id，示例：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 1 -c:v hevc_bm -output_format 0
       -i video.265 -vf "scale_bm=352:288:sophon_idx=1"
       -c:v h264_bm -g 256 -b:v 256K -sophon_idx 1 -y out.264
```

3. 常规模式下：通过sophon_idx指定卡id，示例：

```
ffmpeg -c:v hevc_bm  -sophon_idx 1 -i video.265
       -vf "scale_bm=2560:1440:opt=crop:zero_copy=1:sophon_idx=1"
       -c:v h264_bm -g 256 -b:v 8M -sophon_idx 1 -y out.264
```

### bm_opencv问题

VideoWriter.write性能问题，有些客户反应，存文件慢。

解析：就目前来看看采用YUV采集，然后编码10-20ms之间写入一帧数据属于正常现象。

使用opencv的video write编码，提示物理内存(heap2)分配失败

答：确认heap2设置的大小，如果heap2默认大小是几十MB，需要设置heap2 size为1G。目前出厂默认配置是1G。

```
Update_boot_info 可查询heap2 size
update_boot_info –heap2_size=0x40000000 –dev=0x0 设置heap2 size为1G。设置后重装驱动。
```

# 图片编解码

## 常见问题

是否支持avi, f4v, mov, 3gp, mp4, ts, asf, flv, mkv封装格式的H264/H265视频解析？

答：我们使用ffmpeg对这些封装格式进行支持，ffmpeg支持的我们也支持。经查，这些封装格式ffmpeg都是支持的。但是封装格式对于H265/264的支持，取决于该封装格式的标准定义，比如flv标准中对h265就没有支持，目前国内的都是自己扩展的。

是否支持png, jpg, bmp, jpeg等图像格式

答：Jpg/jpeg格式除了有jpeg2000外，自身标准还有很多档次，我们采用软硬结合的方式对其进行支持。对jpeg baseline的除了极少部分外，都用硬件加速支持，其他的jpeg/jpg/bmp/png采用软件加速的方式进行支持。主要的接口有opencv/ffmpeg库。

## bm_ffmpeg问题

从内存读取图片，用AVIOContext *avio =avio_alloc_context()，以及avformat_open_input()来初始化，发现初始化时间有290ms；但是如果从本地读取图片，只有3ms。为啥初始化时间要这么长？怎样减少初始化时间？

答：

```
ret = avformat_open_input(&fmt_ctx, NULL, NULL, NULL);
```

这里是最简单的调用。因此，avformat内部会会读取数据，并遍历所有的数据，来确认avio中的数据格式。

若是避免在这个函数中读取数据、避免做这种匹配工作。在已经知道需要使用的demuxer的前提下，譬如，已知jpeg的demuxer是mjpeg，可将代码改成下面的试试。

```
AVInputFormat* input_format = av_find_input_format("mjpeg");
ret = avformat_open_input(&fmt_ctx, NULL, input_format, NULL);
```

如何查看FFMPEG中支持的分离器的名称?

答：

```
root@linaro-developer:~# ffmpeg -demuxers | grep jpeg
D jpeg_pipe piped jpeg sequence
D jpegls_pipe piped jpegls sequence
D mjpeg raw MJPEG video
D mjpeg_2000 raw MJPEG 2000 video
D mpjpeg MIME multipart JPEG
D smjpeg Loki SDL MJPEG
```

如何在FFMPEG中查看解码器信息，例如查看jpeg_bm解码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -decoders | grep _bm
V..... avs_bm bm AVS decoder wrapper (codec avs)
V..... cavs_bm bm CAVS decoder wrapper (codec cavs)
V..... flv1_bm bm FLV1 decoder wrapper (codec flv1)
V..... h263_bm bm H.263 decoder wrapper (codec h263)
V..... h264_bm bm H.264 decoder wrapper (codec h264)
V..... hevc_bm bm HEVC decoder wrapper (codec hevc)
V..... jpeg_bm BM JPEG DECODER (codec mjpeg)
V..... mpeg1_bm bm MPEG1 decoder wrapper (codec mpeg1video)
V..... mpeg2_bm bm MPEG2 decoder wrapper (codec mpeg2video)
V..... mpeg4_bm bm MPEG4 decoder wrapper (codec mpeg4)
V..... mpeg4v3_bm bm MPEG4V3 decoder wrapper (codec msmpeg4v3)
V..... vc1_bm bm VC1 decoder wrapper (codec vc1)
V..... vp3_bm bm VP3 decoder wrapper (codec vp3)
V..... vp8_bm bm VP8 decoder wrapper (codec vp8)
V..... wmv1_bm bm WMV1 decoder wrapper (codec wmv1)
V..... wmv2_bm bm WMV2 decoder wrapper (codec wmv2)
V..... wmv3_bm bm WMV3 decoder wrapper (codec wmv3)
```

如何在FFMPEG中查看解码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h decoder=jpeg_bm
Decoder jpeg_bm [BM JPEG DECODER]:
General capabilities: avoidprobe
Threading capabilities: none
jpeg_bm_decoder AVOptions:
-bs_buffer_size <int> .D.V..... the bitstream buffer size (Kbytes) for bm jpeg decoder (from 0 to INT_MAX) (default 5120)
-chroma_interleave <flags> .D.V..... chroma interleave of output frame for bm jpeg decoder (default 0)
-num_extra_framebuffers <int> .D.V..... the number of extra frame buffer for jpeg decoder (0 for still jpeg, at least 2 for motion jpeg) (from 0 to INT_MAX) (default 0)
```

如何在FFMPEG中查看编码器信息，例如查看jpeg_bm编码器信息?

答：

```
root@linaro-developer:/home/sophgo/test# ffmpeg -h encoder=jpeg_bm
Encoder jpeg_bm [BM JPEG ENCODER]:
General capabilities: none
Threading capabilities: none
Supported pixel formats: yuvj420p yuvj422p yuvj444p
jpeg_bm_encoder AVOptions:
-is_dma_buffer <flags> E..V..... flag to indicate if the input frame buffer is DMA buffer (default 0)
```

调用API实现jpeg编码的应用示例

答：

```
AVDictionary* dict = NULL;
av_dict_set_int(&dict, "is_dma_buffer", 1, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

调用FFMPEG的API实现静态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

```
AVDictionary* dict = NULL;
/* bm_jpeg 解码器的输出是 chroma-interleaved模式,例如, NV12 */
av_dict_set_int(&dict, "chroma_interleave", 1, 0);
/* The bitstream buffer 为 3100KB(小于 1920x1080x3), 假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 0, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

调用FFMPEG的API实现动态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

```
AVDictionary* dict = NULL;
/* bm_jpeg 解码器输出的是 chroma-separated 模式, 例如, YUVJ420 */
av_dict_set_int(&dict, "chroma_interleave", 0, 0);
/* The bitstream buffer 为 3100KB */
/* 假设最大分辨率为 1920x1080 */
av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
/* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
av_dict_set_int(&dict, "num_extra_framebuffers", 2, 0);
ret = avcodec_open2(pCodecContext, pCodec, &dict);
```

[问题分析]当用ffmpeg jpeg_bm解码超大JPEG图片的时候，有时候会报"ERROR:DMA buffer size(5242880) is less than input data size(xxxxxxx)"，如何解决？

# 在用FFMPEG的jpeg_bm硬件解码器解码JPEG图片的时候，默认的输入buffer是5120K。在拿到JPEG文件前提前分配好输入缓存，在MJPG文件解码时可以避免频繁地创建和销毁内存。当出现默认输入buffer大小比输入jpeg文件小的时候，可以通过下面的命令来调大输入缓存。

| av_dict_set_int(&opts, "bs_buffer_size", 8192, 0);   //注意： bs_buffer_size是以Kbyte为单位的

## bm_opencv问题

### 4K图片的问题

答：有些客户需要的图片较大如8K等，由于VPP只支持4K大小的图片，所以通过opencv读取图片后，会自动保持比例缩放到一个4K以内的尺寸。

如果客户需要传递原始图片的坐标位置给远端，可以有以下两种做法：

1. imread中设置flag = IMREAD_UNCHANGED_SCALE，此时图片不会真正解码，会在mat.rows/cols中返回图片的原始宽高，然后可根据缩放比例计算得到原图的坐标
2. 传递相对坐标给远端，即坐标x/缩放后的宽， 坐标y/缩放后的高传递到远端。这步相对坐标计算也可以在远端完成，然后可以根据远端知道的原始图像宽高计算得到正确的原图坐标

### Opencv imread读取图片性能问题

原因分析：如果读取尺寸小于16x16的图片，或者progressive 格式的jpeg，不能实现硬件加速，需要软件解码，导致客户发现图片解码并没有加速。

### 若是采用libyuv处理JPEG方面的输出或者输入，需要注意什么事项？

答：若是处理jpeg方面的输出或者输入，需要使用J400，J420，J422，J444等字样的函数，不然输出结果会有色差。

原因是JPEG的格式转换矩阵跟视频的不一样。

### Bm_opencv的imread jpeg解码结果和原生opencv的imread jpeg结果不同，有误差

答：是的。原生opencv使用libjpeg-turbo,而bm_opencv采用了bm168x中的jpeg硬件加速单元进行解码。

误差主要来自解码输出YUV转换到BGR的过程中。1）YUV需要上采样到YUV444才能进行BGR转换。这个upsample的做法没有标准强制统一，jpeg-turbo提供了默认Fancy upsample，也提供了快速复制上采样的算法，原生opencv在cvtColor函数中采用了快速复制上采样算法，而在imread和imdecode中沿用了libjpeg-turbo默认的fancy upsample；而BM168x硬件加速单元采用快速复制的算法。2）YUV444到BGR的转换是浮点运算，浮点系数精度的不同会有+/-1的误差。其中1）是误差的主要来源。

这个误差并不是错误，而是双方采用了不同的upsample算法所导致的,即使libjpeg-turbo也同时提供了两种upsample算法。

如果用户非常关注这两者之间的差异，因为这两者之间的数值差异导致了AI模型精度的下降，我们建议有两种解决办法：

1. 设置环境变量 export USE_SOFT_JPGDEC=1，可以指定仍然使用libjpeg-turbo进行解码。但是这样会导致处理器的loading上升，不推荐
2. 可能过去模型太依赖开源opencv的解码结果了，可以用bm_opencv的解码结果重新训练模型，提高模型参数的适用范围。

可以使用libjpeg-turbo提供的djpeg工具对于测试工具集的数据进行重新处理，然后用处理后的数据对模型进行训练。djpeg的命令如下：

| ./djpeg -nosmooth -bmp -outfile xxxxx.bmp input.jpg

然后用重新生成bmp文件作为训练数据集，进行训练即可。

### 使用opencv的imwrite编码的结果和使用bmcv_image_jpeg_enc编码的结果有质量差异（色彩饱和度）

1. opencv下的imwrite里面有csc convert操作，色彩图像csc type设定的是CSC_RGB2YPbPr_BT601，灰度图是CSC_MAX_ENUM
2. 在bmcv_image_jepg_enc的时候，前面调用一下bmcv_image_vpp_csc_matrix_convert接口，同时指定csc type的类型，对齐imwrite里面的csc类型，这样不会有质量差异了

```c
bm_status_t bmcv_image_vpp_csc_matrix_convert(
      bm_handle_t           handle,
      int                   output_num,
      bm_image              input,
      bm_image*             output,
      csc_type_t            csc,
      csc_matrix_t*         matrix,
      bmcv_resize_algorithm algorithm,
      bmcv_rect_t *         crop_rect )
```

## 图像处理

### 常见问题

#### bm_image_create、bm_image_alloc_dev_mem、bm_image_attach相关疑问

1. bm_image_create：用于创建bm_image结构体。
2. bm_image_alloc_dev_mem：申请设备内存，且内部会attach上bm_image。
3. bm_image_attach：用于将从opencv等处获取到的设备内存与bm_image_create申请到的bm_image进行绑定。

#### bm_image_destroy、bm_image_detach相关疑问

1. bm_image_detach：用于将bm_image关联的设备内存进行解绑， 如果设备内存是内部自动申请的，才会释放这块设备内存；如果bm_image未绑定设备内存，则直接返回。
2. bm_image_destroy：该函数内部嵌套调用bm_image_detach。也就是说，调用该函数，如果bm_image绑定的设备内存是通过bm_image_alloc_dev_mem申请，就会释放；如果是通过bm_image_attach绑定的设备内存则不会被释放，此时需要注意该设备内存是否存在内存泄露，如果存在其他模块继续使用，则由相应模块进行释放。
3. 总的来说，设备内存由谁申请则由谁释放，如果是通过attach绑定的设备内存，则不能调用 bm_image_destroy 进行释放，如果确定attach绑定的设备内存不再使用，可通过bm_free_device等接口进行释放。

## bm_ffmpeg问题

### ffmpeg中做图像格式/大小变换导致视频播放时回退或者顺序不对的情况处理办法

答：ffmpeg在编码的时候底层维护了一个avframe的队列作为编码器的输入源，编码期间应保证队列中数据有效，如果在解码后需要缩放或者像素格式转换时候需要注意送进编码器的avframe的数据有效和释放问题。

在例子ff_bmcv_transcode中从解码输出src-avframe转换成src-bm_image然后做像素格式转换或者缩放为dst-bm_image最后转回dst-avframe去编码的过程中src-avframe、src-bm_image的设备内存是同一块，dst-avframe、dst-bm_image的设备内存是同一块。在得到dst-bm_image后即可释放src_avframe和src-bm_image的内存（二者释放其中一个即可释放设备内存），作为编码器的输入dts-bm_image在转换成dst-avframe之后其设备内存依然不能被释放（常见的异常情况是函数结束dts-bm_image的引用计数为0导致其被释放），如果dst-bm_image被释放了此时用dst-avframe去编码结果肯定会有问题。

解决方法是dst-bm_image的指针是malloc一块内存，然后将其传给av_buffer_create，这样就保证在函数结束的时候dst-bm_image引用计数不会减1，释放的方法是将malloc的dst-bm_image指针通过av_buffer_create传给释放的回调函数，当dst-avframe引用计数为0的时候会调用回调函数将malloc的指针和dst-bm_image的设备内存一起释放。详见例子ff_bmcv_transcode/ff_avframe_convert.cpp。

## bm_opencv问题

### Opencv读取图片后，cvMat转为bmimage, 之后，调用bmcv_image_vpp_convert做缩放或者颜色空间转换，得到的图片不一致

原因分析：opencv内部的转换矩阵和bmcv_image_vpp_convert使用的转换矩阵不一致，需要调用bmcv_image_vpp_csc_matrix_covert, 并且指定CSC_YPbPr2RGB_BT601来进行转换才能保持一致。

### 关于什么时候调用uploadMat/downloadMat接口的问题

解析：当创建了一个cv::Mat, 然后调用cv::bmcv里面的接口进行了一些处理后，设备内存的内容改变了，这时候需要downloadMat来同步一下设备内存和系统内存。当调用了cv::resize等opencv原生的接口后，系统内存的内容改变了，需要uploadMat，使设备内存和系统内存同步。

### 对于VPP硬件不支持的YUV格式转换，采取什么样的软件方式最快？

答：建议采用内部增强版本的libyuv。

相比较原始版本，增加了许多NEON64优化过的格式转换API函数。其中包含许多JPEG YCbCr相关的函数。

位置：/opt/sophon/libsophon-current/lib/

### OpenCV中的BGR格式，在libyuv中对应的那个格式？OpenCV中的RGB格式呢？

答：

+ OpenCV中的BGR格式，在libyuv中对应的格式为RGB24
+ OpenCV中的RGB格式，在libyuv中对应的格式为RAW。

### 现在opencv中默认是使用ION内存作为MAT的data空间，如何指定Mat对象基于system memory内存去创建使用？

答：

```cpp
using namespace cv；
Mat m; m.allocator = m.getDefaultAllocator();     // get system allocator
```

然后就可以正常调用各种mat函数了，如m.create() m.copyto()，后面就会按照指定的allocator来分配内存了。

```cpp
m.allocator = hal::getDefaultAllocator();  // get ion allocator
```

就又可以恢复使用ION内存分配器来分配内存。

### opencv转bm_image的时候，报错"Memory allocated by user, no device memory assigned. Not support BMCV!"

答：这种错误通常发生在soc模式下，所转换的Mat只分配了系统内存，没有分配设备内存，而bm_image要求必须有设备内存，因此转换失败。而在pcie模式下，接口内部会自动分配设备内存，因此不会报这个错误。

会产生这类问题的Mat通常是由外部分配的data内存attach过去的，即调用Mat(h, w, data) 或者Mat.create(h,w, data)来创建的，而data!=NULL,由外部分配。

对于这种情况，因为bm_image必须要求设备内存，因此解决方案有

1. 新生成个Mat，默认创建设备内存，然后用copyTo()拷贝一次，把数据移到设备内存上，再重新用这个Mat来转成bm_image
2. 直接创建bm_image，然后用bm_image_copy_host_to_device,将Mat.data中的数据拷贝到bm_image的设备内存中。

### 调用 bmcv_image_vpp_convert_padding 接口时，报缩放比例超过32倍的错："vpp not support: scaling ratio greater than 32"

bm1684的vpp中硬件限制图片的缩放不能超过32倍（bm1684x的vpp中硬件限制图片的缩放不能超过128倍）。即应满足 dst_crop_w <= src_crop_w * 32，  src_crop_w <= dst_crop_w * 32， dst_crop_h <= src_crop_h * 32 , src_crop_h <= dst_crop_h * 32。

此问题原因可能是：

1. 输入 crop_rect 中的crop_w, crop_h 与 输出 padding_attr 中的dst_crop_w ，dst_crop_h 缩放比例超过了32倍。
2. crop_rect，padding_attr 值的数量应与 output_num的数量一致。

### 调用 bmcv_image_vpp_basic 接口时，csc_type_t, csc_type 和 csc_matrix_t* matrix该如何填？

bmcv中vpp在做csc 色彩转换时，默认提供了4组601系数和4组709系数， 如csc_type_t所示。

1. csc_type可以填为CSC_MAX_ENUM， matrix填NULL，会默认配置 601 YCbCr与RGB互转系数。
2. csc_type可以填csc_type_t中参数，如YCbCr2RGB_BT709，matrix填NULL，会按照所选类型配置对应系数。
3. csc_type可以填CSC_USER_DEFINED_MATRIX，matrix填自定义系数。会按照自定义系数配置。

csc_matrix_t 中系数参考如下公式：

Y = csc_coe00 * R + csc_coe01 * G + csc_coe02 * B + csc_add0;
U = csc_coe10 * R + csc_coe11 * G + csc_coe12 * B + csc_add1;
V = csc_coe20 * R + csc_coe21 * G + csc_coe22 * B + csc_add2;

由于1684 vpp精度为10位（bm1684x vpp精度为FP32），整数处理。

csc_coe 与 csc_add的计算方法为: csc_coe = round（浮点数 * 1024）后按整数取补码。

csc_coe取低13bit，即 csc_coe = csc_coe & 0x1fff，csc_add取低21bit，即 csc_add = csc_add & 0x1fffff。

举例如下：

floating-point coe matrix               =>          fixed-point coe matrix
0.1826	0.6142	0.0620	16.0000         =>          0x00bb    0x0275   0x003f   0x004000

### [问题分析]不同线程对同一个bm_imag调用 bm_image_destroy 时，程序崩溃

bm_image_destroy(bm_image image) 接口设计时，采用了结构体做形参，内部释放了image.image_private指向的内存，但是对指针image.image_private的修改无法传到函数外，导致第二次调用时出现了野指针问题。

为了使客户代码对于sdk的兼容性达到最好，目前不对接口做修改。
建议使用bm_image_destroy（image）后将 image.image_private = NULL，避免多线程时引发野指针问题。

### 在bmcv::toBMI之前是否需要调用bm_create_image，如果调用，在最后使用bm_image_destroy会不会引起内存泄露？

1. bmcv::toBMI内部嵌套调用bm_image_create， 无需再次调用bm_create_image。
2. 如果在bmcv::toBMI前调用了bm_create_image，会导致内存泄露。
3. 调用bmcv::toBMI后，除了需要调用bm_image_destroy,还需要image.image_private = NULL。

# SOPHGO多媒体框架介绍

## 简介

本文档所述多媒体框架的描述对象为算能的算丰BM168x产品系列，目前该产品系列包括BM1682、BM1684、BM1684X三款。其中1）BM1682没有视频编码硬件单元，因此本文中所有关于视频硬件编码的内容均只针对BM1684/BM1684X产品而言；2）本文中提到的PCIE模式，仅针对BM1684/BM1684X产品而言，在BM1682下仅支持soc模式；3）本文中提到的Opencv中的bmcv名字空间下的函数，仅针对BM1684产品而言。

本文档所述多媒体框架的覆盖范围包括BM168x产品系列中的视频解码VPU模块、视频编码VPU模块、图像编码JPU模块、图像解码JPU模块、图像处理模块VPP。这些模块的功能封装到FFMPEG和OPENCV开源框架中，客户可以根据自己的开发习惯，选择FFMPEG API或者OPENCV API。其中图像处理模块，我们还单独提供了算能自有的BMCV API底层接口，这部分接口有专门的文档介绍，可以参考《BMCV User Guide》，本文档不再详细介绍，仅介绍这三套API之间的层级关系及如何互相转换。

OPENCV，FFMPEG和BMCV这三套API在功能上是子集的关系，但有少部分不能全部包含，下面的括号中进行了特别标注。

1. BMCV API包含了所有能用硬件加速的图像处理加速接口（这里图像处理硬件加速，包括硬件图像处理VPP模块加速，以及借用其他硬件模块实现的图像处理功能）。
2. FFMPEG API包含了所有硬件加速的视频/图像编解码接口，所有软件支持的视频/图像编解码接口（即所有FFMPEG开源支持的格式），通过bm_scale filter支持的部分硬件加速的图像处理接口（这部分图像处理接口，仅包括用硬件图像处理VPP模块加速的缩放、crop、padding、色彩转换功能）。

SOPHGO FFMPEG 开源仓库 ：https://github.com/sophgo/sophon_ffmpeg

3. OPENCV API包含了所有FFMPEG支持的硬件及软件视频编解码接口（视频底层通过FFMPEG支持，这部分功能完全覆盖），硬件加速的JPEG编解码接口，软件支持的其他所有图像编解码接口（即所有OPENCV开源支持的图像格式），部分硬件加速的图像处理接口（指用图像处理VPP模块加速的缩放、crop、padding、色彩转换功能），所有软件支持的OPENCV图像处理功能。

SOPHGO OPENCV 开源仓库 ：https://github.com/sophgo/sophon_opencv

# 三个框架比较

这三个框架中，BMCV 专注于图像处理功能，且能用BM168x硬件加速的部分；FFMPEG框架强于图像和视频的编解码，几乎所有格式都可以支持，只是是否能用硬件加速的区别；OPENCV框架强于图像处理，各种图像处理算法最初都先集成到OPENCV框架中，而视频编解码通过底层调用FFMPEG来实现。

因为BMCV仅提供了图像处理接口，因此FFMPEG或者OPENCV框架中，客户一般会选择其中一个作为主框架进行开发。这两个框架，从功能抽象上来说，OPENCV的接口要更加简洁，一个接口就可以实现一次视频编解码操作；从性能上说，这两个的性能是完全一致的，几乎没有差别，在视频编解码上，OPENCV只是对FFMPEG接口的一层封装；从灵活性上说，FFMPEG的接口更加分离，可插入的操作粒度更细。最重要的，客户还是要根据自己对于某个框架的熟悉程度来做选择，只有深入了解，才能把框架用好。

图 1 OPENCV/FFMPEG/BMCV与BMSDK之间的层级调用关系

在很多应用场景下，需要用到某个框架下的特殊功能，因此在第4节中给出了三个框架之间灵活转换的方案。这种转换是不需要发生大量数据拷贝的，对性能几乎没有损失。

## BM1684硬件加速功能

本节给出了多媒体框架中硬件加速模块能支持的功能。其中硬件加速模块包括视频解码VPU模块，视频编码VPU模块，图像编解码JPU模块，图像处理VPP模块。

需要特别注意，这里只列出能够用硬件加速的能力，以及典型场景下的性能估计值。更详细的性能指标参考BM168x产品规格书。

### 视频编解码

BM1684产品支持H264（AVC），HEVC视频格式的硬件解码加速，最高支持到4K视频的实时解码。支持H264(AVC), HEVC视频格式的硬件编码，最高支持到HD(1080p)视频的实时编码。

视频解码的速度与输入视频码流的格式有很大关系，不同复杂度的码流的解码速度有比较大的波动，比如码率、GOP结构，分辨率等，都会影响到具体的测试结果。一般来说，针对视频监控应用场景，BM1684产品单处理器可以支持到32路HD高清实时解码。

视频编码的速度与编码的配置参数有很大关系，不同的编码配置下，即使相同的视频内容，编码速度也不是完全相同的。一般来说，BM1684产品单处理器最高可以支持到2路HD高清实时编码。

### 图像编解码

BM1684产品支持JPEG baseline格式的硬件编/解码加速。注意，仅支持JPEG baseline档次的硬件编解码加速，对于其他图片格式，包括JPEG2000, BMP, PNG以及JPEG标准的progressive, lossless等档次均自动采用软解支持。在opencv框架中，这种兼容支持对于客户是透明的，客户应用开发时无需特别处理。

图像硬件编解码的处理速度和图像的分辨率、图像色彩空间（YUV420/422/444）有比较大的关系，一般而言，对于1920x1080分辨率的图片，色彩空间为YUV420的，单处理器图像硬件编解码可以达到600fps左右。

### 图像处理

BM1684产品有专门的视频处理VPP单元对图像进行硬件加速处理。支持的图像操作有色彩转换、图像缩放、图像切割crop、图像拼接stitch功能。最大支持到4k图像输入。对于VPP不支持的一些常用复杂图像处理功能，如线性变换ax+b，直方图等, 我们在BMCV API接口中，利用其他硬件单元做了特殊的加速处理。

## 硬件内存分类

在后续的讨论中，内存同步问题是应用调试中经常会遇到的，比较隐蔽的问题。我们通常统一用设备内存和系统内存来称呼这两类内存间的同步。根据BM168x产品类型的不同，这两个内存在SOC模式和PCIE模式下分别具有不同的含义。

SOC模式，是指用BM168x中的处理器作为主控处理器，BM168x产品独立运行应用程序。典型的产品有SE5、SM5-soc模组。在这类模式下，采用Linux系统下的ION内存对设备内存进行管理。在SOC模式下，设备内存指ION分配的物理内存，系统内存其实是cache，这里的命名只是为了和PCI E模式保持一致。从系统内存（cache）到设备内存，称为Upload上传（实质是cache flush）；从设备内存到系统内存（cache），称为Download下载（实质是cache invalidation）。在SOC模式下，设备内存和系统内存最终操作的其实是同一块物理内存，大部分时间，操作系统会自动对其进行同步，这也导致内存没有及时同步时的现象更加隐蔽和难以复现。

PCIE模式，是指BM168x产品作为PCIE板卡形态插到服务器主机上进行工作，应用程序运行在服务器主机的处理器上。在PCIE模式下，设备内存指PCIE板卡上的物理内存，并不包含在服务器主机内存中；系统内存指服务器主机中的内存。从系统内存到设备内存，称为Upload上传（实质是pcie写数据）；从设备内存到系统内存，称为Download下载（实质是pcie读数据）。在PCIE模式下，设备内存和系统内存是物理上完全独立的两块物理内存，必须通过Download/Upload操作才能保证这两块内存保持同步。

图 2 内存同步模型

FFMPEG和OPENCV两个框架都提供了内存同步操作的函数。而BMCV API只面向设备内存操作，因此不存在内存同步的问题，在调用BMCV API的时候，需要将数据在设备内存准备好。

在OPENCV框架中，部分函数的形参中就提供了update的标志位，当标志位设置true的时候，函数内部会自动进行内存同步操作。这部分可以参考后续的第二章第3节的API介绍。用户也可以通过bmcv::downloadMat() 和 bmcv::uploadMat()两个函数，主动控制内存同步。同步的基本原则是：
a) opencv原生函数中，yuv Mat格式下设备内存中的数据永远是最新的，RGB Mat格式下系统内存中的数据永远是最新的
b) 当opencv函数向BMCV API切换的时候，根据上一个原则，将最新数据同步到设备内存中；反之，从BMCV API向opencv函数切换的时候，在RGB Mat下将最新数据同步到系统内存中。
c) 在不发生框架切换的时候，要尽量减少内存同步的操作。频繁的内存同步操作会明显降低性能。

在常规FFMPEG框架中，有两类称之为软（常规）和硬（hwaccel）的codec API和filter API。这两套API的框架都可以支持BM168x的硬件视频编解码和硬件图像filter，从这个角度上说，所谓的软解码和硬解码在底层性能上是完全一样的，只是在使用习惯上的区别。软codec/filter API的使用方式和通常ffmpeg 内置codec完全一致，硬codec/filter API要用-hwaccel来指定使能bmcodec专用硬件设备。当在软codec API和filter API中，通过av_dict_set传入标志参数"is_dma_buffer"或者"zero_copy"，来控制内部codec或filter是否将设备内存数据同步到系统内存中，具体参数使用可以用ffmpeg -h来查看。当后续直接衔接硬件处理的时候，通常不需要将设备内存数据同步到系统内存中。

在hwaccel codec API和filter API中，内存默认只有设备内存，没有分配系统内存。如果需要内存同步，则要通过hwupload和hwdownload filter来完成。

综上所述，OPENCV和FFMPEG框架都对内存同步提供了支持，应用可以根据自己的使用习惯选择相应的框架，对数据同步进行精准控制。BMCV API则始终工作在设备内存上。

## 框架之间转换

在应用开发中，总会碰到一些情况下，某个框架无法完全满足设计需求。这时就需要在各种框架之间快速切换。BM168x多媒体框架对其提供了支持，可以满足这种需求，并且这种切换是不发生数据拷贝的，对于性能几乎没有影响。

### FFMPEG和OPENCV转换

FFMPEG和OPENCV之间的转换，主要是数据格式AVFrame和cv::Mat之间的格式转换。

当需要FFMPEG和OPENCV配合解决的时候，推荐使用常规非HWAccel API的通路，目前OPENCV内部采用是这种方式，验证比较完备。

FFMPEG AVFrame转到OPENCV Mat格式如下：

1. `AVFrame * picture；`
2. 中间经过ffmpeg API的一系列处理，比如avcodec_decode_video2 或者 avcodec_receive_frame，然后将得到的结果转成Mat
3. card_id 为进行ffmpeg硬件加速解码的设备序号， 在常规codec API中，通过av_dict_set的sophon_idx指定，或者hwaccel API中，在hwaccel设备初始化的时候指定， soc模式下默认为0
4. `cv::Mat ocv_frame(picture, card_id)；`
5. 或可以通过分步方式进行格式转换
6. `cv::Mat ocv_frame;`
7. `ocv_frame.create(picture, card_id);`
8. 然后可以用ocv_frame进行opencv的操作，此时ocv_frame格式为BM168x扩展的yuv mat类型，如果后续想转成opencv标准的bgr mat格式，可以按下列操作。
9. 注意：这里就有内存同步的操作， 如果没有设置，ffmpeg默认是在设备内存中的，如果update=false, 那么转成bgr的数据也一直在设备内存中，系统内存中为无效数据，如果update=true，则设备内存同步到系统内存中。如果后续还是硬件加速处理的话，可以update=false, 这样可以提高效率，当需要用到系统内存数据的时候，显式调用bmcv::downloadMat()来同步即可。
10. `cv::Mat bgr_mat;`
11. `cv::bmcv::toMAT(ocv_frame, bgr_mat, update);`
12. 最后AVFrame *picture会被Mat ocv_frame释放，因此不需要对picture进行av_frame_free()操作。如果希望外部调用av_frame_free来释放picture， 则可以加上card_id = card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED,0,0), 该标准表明AVFrame的创建和释放由外部管理
13. `ocv_frame.release();`
14. `picture = nullptr;`

OPENCV Mat转成FFMPEG AVFrame的情况比较少见，因为几乎所有需要的FFMPEG操作都在opencv中有对应的封装接口。比如：ffmpeg解码在opencv有videoCapture类，ffmpeg编码在opencv中有videoWriter类，ffmpeg的filter操作对应的图像处理在opencv中有bmcv名字空间下的接口以及丰富的原生图像处理函数。

一般来说，opencv Mat转成FFMPEG AVFrame，指的是yuv Mat。在这种情况下，可以按下进行转换：

1. 创建yuv Mat，如果yuv Mat已经存在，可以忽略此步.card_id为BM168x设备序号，soc模式下默认为0
2. `AVFrame * f = cv::av::create(height, width, AV_PIX_FMT_YUV420P,  NULL, 0, -1, NULL, NULL, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, card_id);`
3. `cv::Mat image(f, card_id);`
4. do something in opencv
5. `AVFrame * frame = image.u->frame;`
6. call FFMPEG API
7. 注意：在ffmpeg调用完成前，必须保证Mat image没有被释放，否则AVFrame会和Mat image一起释放。如果需要将两个的声明周期分离开来，则上面的image声明要改成如下格式。
8. `cv::Mat image(f, card_id | BM_MAKEFLAG(UMatData::AVFRAME_ATTACHED, 0, 0));`
9. 这样Mat就不会接管AVFrame的内存释放工作

### FFMPEG和BMCV API转换

FFMPEG经常需要和BMCV API搭配使用，因此FFMPEG和BMCV之间的转换是比较频繁的。为此我们专门给了一个例子ff_bmcv_transcode，该例子可以在bmnnsdk2发布包里找到。

ff_bmcv_transcode例子演示了用ffmpeg解码，将解码结果转换到BMCV下进行处理，然后再转换回到ffmpeg进行编码的过程。FFMPEG和BMCV之间的互相转换可以参考ff_avframe_convert.cpp文件中的avframe_to_bm_image()和bm_image_to_avframe()函数。

### OPENCV和BMCV API转换

OPENCV和BMCV API之间的转换，专门在opencv扩展的bmcv名字空间下提供了专门的转换函数。

OPENCV Mat转换到BMCV bm_image格式：

1. `cv::Mat m(height, width, CV_8UC3, card_id);`
2. opencv 操作
3. `bm_image bmcv_image;`
4. 这里update用来控制内存同步，是否需要内存同步取决于前面的opencv 操作，如果前面的操作都是用硬件加速完成，设备内存中就是最新数据，就没必要进行内存同步，如果前面的操作调用了opencv函数，没有使用硬件加速（后续opencv章节6.2中提到了哪些函数采用了硬件加速），对于bgr mat格式就需要做内存同步。
5. 也可以在调用下面函数之前，显式的调用cv::bmcv::uploadMat(m)来实现内存同步
6. `cv::bmcv::toBMI(m, &bmcv_image, update);`
7. 使用bmcv_image就可以进行bmcv api调用，调用期间注意保证Mat m不能被释放，因为bmcv_image使用的是Mat m中分配的内存空间. handle可以通过bm_image_get_handle()获得
8. 释放：必须调用此函数，因为在toBMI中create了bm_image, 否则会有内存泄漏
9. `bm_image_destroy(bmcv_image);`
10. `m.release();`

由BMCV bm_image格式转换到OPENCV Mat有两种方式，一种是会发生数据拷贝，这样bm_image和Mat之间相互独立，可以分别释放，但是有性能损失；一种是直接引用bm_image内存，性能没有任何损失。

1. `bm_image bmcv_image;`
2. 调用bmcv API给bmcv_image分配内存空间，并进行操作
3. `Mat m_copy, m_nocopy;`
4. 下面接口将发生内存数据拷贝，转换成标准bgr mat格式.
5. update控制内存同步，也可以在调用完这个函数后用bmcv::downloadMat()来控制内存同步
6. csc_type是控制颜色转换系数矩阵，控制不同yuv色彩空间转换到bgr
7. `cv::bmcv::toMAT(&bmcv_image, m_copy, update, csc_type);`
8. 下面接口接口将直接引用bm_image内存 (nocopy标志位true), update仍然按照之前的描述，
9. 选择是否同步内存。 在后续opencv操作中，必须保证bmcv_image没有释放，因为mat的内存
10. 直接引用自bm_image `cv::bmcv::toMAT(&bmcv_image, &m_nocopy, AVCOL_SPC_BT709, AVCOL_RANGE_MPEG, NULL, -1, update, true);`
11. 进行opencv

# SOPHGO OpenCV使用指南

## OpenCV简介

BM168x系列中的多媒体、BMCV和NPU硬件模块可以加速对图片和视频的处理：

1) 多媒体模块：硬件加速JPEG编码解码 和Video编解码操作。
2) BMCV模块：硬件加速对图片的resize、color conversion、crop、split、linear transform、nms、sort等操作。
3) NPU模块：硬件加速对图片的split、rgb2gray、mean、scale、int8tofloat32操作。

为了方便客户使用硬件模块加速图片和视频的处理，提升应用OpenCV软件性能，算能修改了OpenCV库，在其内部调用硬件模块进行Image和Video相关的处理。

算能当前OpenCV的版本为4.1.0，除了以下几个算能自有的API以外，其它的所有API与OpenCV API都是一致的。

BM168x系列有两种应用环境：SOC模式和PCIE卡模式。在SOC模式下，使用BM168x系列内置的ARM A53 core作为主控处理器，直接对处理器内部资源进行控制分配。PCIE模式下，BM168x系列作为PCIE卡插到主机上，由主机处理器通过PCIE接口对资源进行控制分配。SOPHGO OpenCV接口在两种模式下互相兼容，行为基本一致，只有以下微小的差异：

在SOC模式下，由于硬件限制，OpenCV库的Mat对象中，step值会被自动设置为64bytes对齐，不足64bytes的数据用随机数补齐。而在PCIE模式下，Mat的step不存在64bytes的对齐限制。例如，一张100*100的图片，每个像素的RGB由3个U8值表示，正常的step值为300，但是经过64bytes对齐，step值最终为320。如下图所示，Mat对象的data中，每一个step的数据是连续的320个bytes，其中前300个是真实数据，后面20个是自动填充的随机数。

图3 对齐填充

在SOC模式下，由于填充了多余的随机值，Mat对象中存储数据的data变量不能直接传递给BMRuntime库的API做推理，否则会降低模型的准确率。请在最后一次BMCV做变换的时候，将stride设置为非对齐方式，多余的随机填充数据会被自动清除掉。

## 数据结构扩展说明

OpenCV内置标准处理的色彩空间为BGR格式，但是很多情况下，对于视频、图片源，直接在YUV色彩空间上处理，可以节省带宽和避免不必要的YUV和RGB之间的互相转换。因此SOPHGO Opencv对于Mat类进行了扩展。

1) 在Mat.UMatData中，引入了AVFrame成员，扩展支持各种YUV格式。其中AVFrame的格式定义与FFMPEG中的定义兼容。
2) 在Mat.UMatData中增加了fd，addr（soc模式下）或hid，mem（pcie模式下）的定义，分别表示对应的内存管理句柄和物理内存地址。
3) 在Mat类中增加了fromhardware变量，标识当前的视频、图片解码是由硬件或是软件计算完成的，开发者在程序开发过程中无需考虑该变量的值。

## API扩展说明

### VideoCapture::get_resampler

**[功能和说明]**

* 取视频的采样速率。如den=5, num=3表示每5帧中有2帧被丢弃。
* 此接口将废弃。推荐用double VideoCapture::get(CAP_PROP_OUTPUT_SRC)接口。

**[函数名]**

`bool VideoCapture::get_resampler(int *den, int *num)`

**[参数说明]**

* `int *den` 采样速率的分母。
* `int *num` 采样速率的分子。

**[返回值]**

* `true` 执行成功。
* `false` 执行失败。

### VideoCapture::set_resampler

**[功能和说明]**

* 置视频的采样速率。如den=5, num=3，表示每5帧中有2帧被丢弃。
* 此接口将废弃。推荐用bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)接口。

**[函数名]**

`bool VideoCapture::set_resampler(int den, int num)`

**[参数说明]**

* `int den` 采样速率的分母。
* `int num` 采样速率的分子。

**[返回值]**

* `true` 执行成功。
* `false` 执行失败。

### VideoCapture::get(CAP_PROP_TIMESTAMP)

**[功能和说明]**

* 提供当前图片的时间戳，时间基数取决于在流中给出的时间基数。

**[函数名]**

`double VideoCapture::get(CAP_PROP_TIMESTAMP)`

**[参数说明]**

* `CAP_PROP_TIMESTAMP` 特定的枚举类型指示获取时间戳，此类型由SOPHGO定义。

**[返回值]**

* 在使用前先将返回值转成 `unsigned int64` 数据类型。
* `0x8000000000000000L` 没有 AV PTS 值。
* 其他 AV PTS 值。

### VideoCapture::get(CAP_PROP_STATUS)

**[功能和说明]**

* 该函数提供了一个接口，用于检查视频抓取的内部运行状态。

**[函数名]**

`double VideoCapture::get(CAP_PROP_STATUS)`

**[参数说明]**

* `CAP_PROP_STATUS` 枚举类型，此类型由SOPHGO定义。

**[返回值]**

* 在使用返回值前请将转换成 `int` 类型。
* `0` 视频抓取停止，暂停或者其他无法运行的状态。
* `1` 视频抓取正在进行。
* `2` 视频抓取结束。

### VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)

**[功能和说明]**

* 设置YUV视频的采样速率。如resampler为0.4，表示每5帧中保留2帧，有3帧被丢弃。

**[函数名]**

`bool VideoCapture::set(CAP_PROP_OUTPUT_SRC, double resampler)`

**[参数说明]**

* `CAP_PROP_OUTPUT_SRC` 枚举类型，此类型由SOPHGO定义。
* `double resampler` 采样速率。

**[返回值]**

* `true` 执行成功。
* `false` 执行失败。

### VideoCapture::get(CAP_PROP_OUTPUT_SRC)

**[功能和说明]**

* 取视频的采样速率。

**[函数名]**

`double VideoCapture::get(CAP_PROP_OUTPUT_SRC)`

**[参数说明]**

* `CAP_PROP_OUTPUT_SRC` 特定的枚举类型，指视频输出，此类型由SOPHGO定义。

**[返回值]**

* 采样率数值。

### VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)

**[功能和说明]**

* 开或者关闭YUV格式的frame输出。BM168x系列下YUV格式为I420。

**[函数名]**

`bool VideoCapture::set(CAP_PROP_OUTPUT_YUV, double enable)`

**[参数说明]**

* `CAP_PROP_OUTPUT_YUV` 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义。
* `double enable` 操作码，1表示打开，0表示关闭。

**[返回值]**

* `true` 执行成功。

# VideoCapture::get(CAP_PROP_OUTPUT_YUV)

## 功能和说明
* 取YUV视频frame输出的状态。

## 函数名
`double VideoCapture::get(CAP_PROP_OUTPUT_YUV)`

## 参数说明
* `CAP_PROP_OUTPUT_YUV` 特定的枚举类型，指YUV格式的视频frame输出，此类型由SOPHGO定义。

## 返回值
* YUV视频frame输出的状态。
* `1` 表示打开。
* `0` 表示关闭。

# bmcv::getCard

## 功能和说明
* 取SOPHGO OpenCV内部使用的PCIE卡设备句柄。PCIE模式下有效。

## 函数名
`bm_handle_t bmcv::getCard(int id = 0)`

## 参数说明
* `int id` PCIE卡序号，SOC下恒定为0。

## 返回值
* PCIE卡设备句柄。

# bmcv::getId

## 功能和说明
* 据PCIE设备句柄查询卡序号。

## 函数名
`int bmcv::getId(bm_handle_t handle)`

## 参数说明
* `bm_handle_t handle` PCIE设备句柄。

## 返回值
* PCIE卡的序号。

# bmcv::toBMI(Mat &m, bm_image *image, bool update = true)

## 功能和说明
* OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不会发生copy操作。
* 本接口仅支持1N模式。
* 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换。

## 函数名
`bm_status_t bmcv::toBMI(Mat &m, bm_image *image, bool update = true)`

## 参数说明
* `Mat &m` 输入参数，Mat对象，可以为扩展YUV格式或者标准OpenCV BGR格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `bm_image *image` 输出参数，对应格式的BMCV bm_image数据对象。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)

## 功能和说明
* OpenCV Mat对象转换成BMCV接口中对应格式的bm_image数据对象，本接口直接引用Mat的数据指针，不发生copy操作。
* 本接口针对BMCV的4N模式。要求所有Mat的输入图像格式一致，仅对BM1684有效。
* 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1的格式转换。

## 函数名
`bm_status_t bmcv::toBMI(Mat &m, Mat &m1, Mat &m2, Mat &m3, bm_image *image, bool update = true)`

## 参数说明
* `Mat &m` 输入参数，4N中的第1幅图像，扩展YUV格式或者标准OpenCV BGR格式。
* `Mat &m1` 输入参数，4N中的第2幅图像，扩展YUV格式或者标准OpenCV BGR格式。
* `Mat &m2` 输入参数，4N中的第3幅图像，扩展YUV格式或者标准OpenCV BGR格式。
* `Mat &m3` 输入参数，4N中的第4幅图像，扩展YUV格式或者标准OpenCV BGR格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `bm_image *image` 输出参数，对应格式的BMCV bm_image数据对象，其中包含4个图像数据。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::toMAT(Mat &in, Mat &m0, bool update=true)

## 功能和说明
* 输入的MAT对象，可以为各种YUV或BGR格式，转换成BGR packed格式的MAT对象输出。
* 目前支持压缩格式、Gray、NV12、NV16，YUV444P、YUV422P、YUV420P、BGR separate、BGR packed、CV_8UC1到BGR packed格式转换。
* 在YUV格式下，会自动根据AVFrame结构体中colorspace和color_range信息选择正确的色彩转换矩阵。

## 函数名
`bm_status_t bmcv::toMAT(Mat &in, Mat &m0, bool update = true)`

## 参数说明
* `Mat &in` 输入参数，输入的MAT对象，可以为各种YUV格式或者BGR格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `Mat &m0` 输出参数，输出的MAT对象，转成标准OpenCV的BGR格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr = NULL, int fd0 = -1, bool update = true, bool nocopy = true)

## 功能和说明
* 输入的bm_image对象，当nocopy为true时，直接复用设备内存转成Mat格式，当nocopy为false时，行为类似3.13toMAT接口，1N模式。
* nocopy方式只支持1N模式，4N模式因为内存排列方式，不能支持引用。
* 在nocopy为false的情况下，会自动根据参数color_space、color_range信息选择正确的色彩转换矩阵进行色彩转换。
* 如果系统内存vaddr来自于外部，那么外部需要来管理这个内存的释放，Mat释放的时候不会释放该内存。

## 函数名
`bm_status_t bmcv::toMAT(bm_image *image, Mat &m, int color_space, int color_range, void* vaddr = NULL, int fd0 = -1, bool update = true, bool nocopy = true)`

## 参数说明
* `bm_image *image` 输入参数，输入的bm_image对象，可以为各种YUV格式或者BGR格式。
* `int color_space` 输入参数，输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义。
* `int color_range` 输入参数，输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义。
* `void* vaddr` 输入参数，输出Mat的系统虚拟内存指针，如果已分配，输出Mat直接使用该内存作为Mat的系统内存。如果为NULL，则Mat内部自动分配。
* `int fd0` 输入参数，输出Mat的物理内存句柄，如果为负，则使用bm_image内的设备内存句柄，否则使用fd0给定的句柄来mmap设备内存。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存到系统内存中。
* `bool nocopy` 输入参数，如果是true，则直接引用bm_image的设备内存，如果为false，则转换成标准BGR Mat格式。

## 输出参数
* `Mat &m` 输出参数，输出的MAT对象，当nocopy为true时，输出标准BGR格式或扩展的YUV格式的Mat；当nocopy为false时，转成标准OpenCV的BGR格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::toMAT(bm_image *image, Mat &m0, bool update = true, csc_type_t csc = CSC_MAX_ENUM)

## 功能和说明
* 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，1N模式。

## 函数名
`bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, bool update = true, csc_type_t csc = CSC_MAX_ENUM)`

## 参数说明
* `bm_image *image` 输入参数，输入的bm_image对象，可以为各种YUV格式或者BGR格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `csc_type_t csc` 输入参数，色彩转换矩阵，默认为YPbPr2RGB_BT601。

## 输出参数
* `Mat &m0` 输出参数，输出的MAT对象，转成标准OpenCV的BGR格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update = true, csc_type_t csc = CSC_MAX_ENUM)

## 功能和说明
* 输入的bm_image对象，可以为各种YUV或BGR格式，转换成BGR格式的MAT对象输出，4N模式，仅在BM1684下有效。

## 函数名
`bm_status_t bmcv::toMAT(bm_image *image, Mat &m0, Mat &m1, Mat &m2, Mat &m3, bool update = true, csc_type_t csc = CSC_MAX_ENUM)`

## 参数说明
* `bm_image *image` 输入参数，输入的4N模式下的bm_image对象，可以为各种YUV格式或者BGR格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `csc_type_t csc` 输入参数，色彩转换矩阵，默认为YPbPr2RGB_BT601。
* `Mat &m0` 输出参数，输出的第一个MAT对象，转成标准OpenCV的BGR格式。
* `Mat &m1` 输出参数，输出的第二个MAT对象，转成标准OpenCV的BGR格式。
* `Mat &m2` 输出参数，输出的第三个MAT对象，转成标准OpenCV的BGR格式。
* `Mat &m3` 输出参数，输出的第四个MAT对象，转成标准OpenCV的BGR格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::resize

## 功能和说明
* 输入的MAT对象，缩放到输出Mat给定的大小，输出格式为输出Mat指定的色彩空间，因为MAT支持扩展的YUV格式，因此本接口支持的色彩空间并不仅局限于BGR packed。
* 支持Gray、YUV444P、YUV420P、BGR/RGB separate、BGR/RGB packed、ARGB packed格式缩放。

## 函数名
`bm_status_t bmcv::resize(Mat &m, Mat &out, bool update = true, int interpolation = BMCV_INTER_NEAREST)`

## 参数说明
* `Mat &m` 输入参数，输入的Mat对象，可以为标准BGR packed格式或者扩展YUV格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `int interpolation` 输入参数，缩放算法，可为NEAREST或者LINEAR算法。
* `Mat &out` 输出参数，输出的缩放后的Mat对象。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::convert(Mat &m, Mat &out, bool update = true)

## 功能和说明
* 实现两个mat之间的色彩转换，它与toMat接口的区别在于toMat只能实现各种色彩格式到BGR packed的色彩转换，而本接口可以支持BGR packed或者YUV格式到BGR packed或YUV之间的转换。

## 函数名
`bm_status_t bmcv::convert(Mat &m, Mat &out, bool update = true)`

## 参数说明
* `Mat &m` 输入参数，输入的Mat对象，可以为扩展的YUV格式或者标准BGR packed格式。
* `bool update` 输入参数，是否需要同步cache或内存。如果为true，则转换完成后同步cache或者PCIE卡设备内存。
* `Mat &out` 输出参数，输出的色彩转换后的Mat对象，可以为BGR packed或者YUV格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update = true, csc_type_t csc = CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix = nullptr, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)

## 功能和说明
* 接口采用内置的VPP硬件加速单元，集 crop、resize 和 csc 于一体。按给定的多个 rect 框和多个缩放 size，将输入的 Mat 对象输出到多个 Mat 对象中，输出为 OpenCV 标准的 BGR pack 格式或扩展 YUV 格式。
* 接口可以在一步操作内完成 resize、crop、csc 三种功能，提高效率，建议在可能的情况下尽量使用该接口。

## 函数名
`bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, std::vector<Size> &vsz, std::vector<Mat> &out, bool update = true, csc_type_t csc = CSC_YCbCr2RGB_BT601, csc_matrix_t *matrix = nullptr, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)`

## 参数说明
* `Mat &m` 输入参数，输入的 Mat 对象，可以为扩展的 YUV 格式或者标准 BGR packed 格式。
* `std::vector<Rect> &vrt` 输入参数，多个 rect 框，表示输入 Mat 中的 ROI 区域，矩形框个数应与 resize 个数相同。
* `std::vector<Size> &vsz` 输入参数，多个 resize 大小，与 `vrt` 的矩形框一一对应。
* `bool update` 输入参数，是否需要同步 cache 或内存。如果为 true，则转换完成后同步 cache 或者 PCIE 卡设备内存。
* `csc_type_t csc` 输入参数，色彩转换矩阵，可以根据颜色空间指定合适的色彩转换矩阵。
* `csc_matrix_t *matrix` 输入参数，当色彩转换矩阵不在列表中时，可提供外部用户自定义转换矩阵。
* `bmcv_resize_algorithm algorithm` 输入参数，缩放算法，可选择 Nearest 或 Linear 算法。
* `std::vector<Mat> &out` 输出参数，存放缩放、crop 以及色彩转换后的 Mat 对象，格式为标准 BGR pack 或扩展 YUV 格式。

## 返回值
* `BM_SUCCESS(0)` 执行成功。
* 其他：执行失败。

# bmcv::convert

## 函数定义
```cpp
bm_status_t bmcv::convert(Mat &m, std::vector<Rect> &vrt, bm_image *out, bool update = true)
```

## 功能和说明
- 接口采用内置的 VPP 硬件加速单元，集 crop、resize 和 csc 于一体。按给定的多个 rect 框，按照多个 bm_image 指定的 size，将输入的 Mat 对象输出到多个 bm_image 对象中，输出格式由 bm_image 初始化值决定。
- 需要注意的是，bm_image 必须由调用者初始化，并且其个数需与 `vrt` 一一对应。

## 参数说明
- `Mat &m` 输入参数，输入的 Mat 对象，可以为扩展的 YUV 格式或者标准 BGR packed 格式。
- `std::vector<Rect> &vrt` 输入参数，多个 rect 框，表示输入 Mat 中的 ROI 区域，矩形框个数应与 `bm_image` 个数相同。
- `bool update` 输入参数，是否需要同步 cache 或内存。如果为 true，则转换完成后同步 cache 或者 PCIE 卡设备内存。
- `bm_image *out` 输出参数，存放缩放、crop 以及色彩转换后的 bm_image 对象，输出色彩格式由 bm_image 初始化值决定。同时，该 `bm_image` 参数包含的初始化的 size、色彩信息也作为输入信息，用于处理。

## 返回值
- `BM_SUCCESS(0)` 执行成功。
- 其他：执行失败。

# bmcv::uploadMat

## 函数定义
```cpp
void bmcv::uploadMat(Mat &mat)
```

## 功能和说明
- cache 同步或者设备内存同步接口。当执行此函数时，cache 中内容会 flush 到实际内存中（SOC 模式），或者 host 内存同步到 PCIE 卡设备内存（PCIE 模式）。
- 合理调用本接口，可以有效控制内存同步的次数，仅在需要时调用。在 PCIE 模式下尤为重要，因为每次 PCIE 设备内存的同步时间较长。

## 参数说明
- `Mat &mat` 输入参数，需要进行内存同步的 Mat 对象。

## 返回值
- 无。

# bmcv::downloadMat

## 函数定义
```cpp
void bmcv::downloadMat(Mat &mat)
```

## 功能和说明
- cache 同步或者设备内存同步接口。当执行此函数时，cache 中内容会 invalidate（SOC 模式），或者 PCIE 卡设备内存同步到 host 内存（PCIE 模式）。
- 本接口的内存同步方向与 `uploadMat` 接口相反。
- 合理调用本接口，可以有效控制内存同步的次数，仅在需要时调用。在 PCIE 模式下尤为重要，因为每次 PCIE 设备内存的同步时间较长。

## 参数说明
- `Mat &mat` 输入参数，需要进行内存同步的 Mat 对象。

## 返回值
- 无。

# bmcv::stitch

## 函数定义
```cpp
bm_status_t bmcv::stitch(std::vector<Mat> &in, std::vector<Rect> &src, std::vector<Rect> &drt, Mat &out, bool update = true, bmcv_resize_algorithm algorithm = BMCV_INTER_LINEAR)
```

## 功能和说明
- 图像拼接，将输入的多个 Mat 按照给定的位置缩放并拼接到一个 Mat 中。
- 对于 bm1684，输入和输出的 Mat 仅支持 64 对齐的 stride。

## 参数说明
- `std::vector<Mat> &in` 输入参数，多个输入的 Mat 对象，可以为扩展的 YUV 格式或者标准 BGR pack 格式。
- `std::vector<Rect> &src` 输入参数，对应每个 Mat 对象的显示内容框。
- `std::vector<Rect> &drt` 输入参数，对应每个显示内容在目标 Mat 中的显示位置。
- `bool update` 输入参数，是否需要同步 cache 或内存。如果为 true，则转换完成后同步 cache 或者 PCIE 卡设备内存。
- `bmcv_resize_algorithm algorithm` 输入参数，缩放算法，可以为 Nearest 或者 Linear 算法。
- `Mat &out` 输出参数，拼接后的 Mat 对象，可以为 BGR packed 或者 YUV 格式。

## 返回值
- `BM_SUCCESS(0)` 执行成功。
- 其他：执行失败。

# bmcv::print(Mat &m, bool dump = false)

## 函数定义
```cpp
void bmcv::print(Mat &m, bool dump = false)
```

## 功能和说明
- 调试接口，打印输入 Mat 对象的色彩空间、宽高以及数据。
- 当前支持 dump OpenCV 标准 BGR packed 或者 CV_8UC1 数据，以及扩展的 NV12、NV16、YUV420P、YUV422P、GRAY、YUV444P 和 BGR Separate 格式数据。

## 参数说明
- `Mat &m` 输入参数，输入的 Mat 对象，可以为扩展的 YUV 格式或者标准 BGR packed 格式。
- `bool dump` 输入参数，是否打印 Mat 中的数据值，默认不打印。如果为 true，则会在当前目录下生成 mat_dump.bin 文件。

## 返回值
- 无。

# bmcv::print

## 函数定义
```cpp
void bmcv::print(bm_image *image, bool dump)
```

## 功能和说明
- 调试接口，打印输入 bm_image 对象的色彩空间，宽高以及数据。
- 当前支持 dump BGR packed,NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P 和 BGR Separate 格式的 bm_image 数据。

## 参数说明
- `bm_image *image` 输入的 bm_image 对象。
- `bool dump` true 的时候打印 Mat 中的数据值，默认不打印。如果为 true，则会在当前目录下生成 BMI-"宽"x"高".bin 文件。

## 返回值
- 无。

# bmcv::dumpMat

## 函数定义
```cpp
void bmcv::dumpMat(Mat &image, const String &fname)
```

## 功能和说明
- 调试接口，专门 dump Mat 的数据到指定命名的文件。功能同 3.23 的 dump 为 true 时的功能。
- 当前支持 dump OpenCV 标准 BGR packed 或者 CV_8UC1 数据，以及扩展的 NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P 和 BGR Separate 格式数据。

## 参数说明
- `Mat &image` 输入的 Mat 对象, 可以为扩展的 YUV 格式或者标准 BGR packed 格式。
- `const String &fname` dump 的输出文件名。

## 返回值
- 无。

# bmcv::dumpBMImage

## 函数定义
```cpp
void bmcv::dumpBMImage(bm_image *image, const String &fname)
```

## 功能和说明
- 调试接口，专门 dump bm_image 的数据到指定命名的文件。功能同 3.25 的 dump 为 true 时的功能。
- 当前支持 dump BGR packed, NV12,NV16,YUV420P,YUV422P,GRAY,YUV444P 和 BGR Separate 格式的 bm_image 数据。

## 参数说明
- `bm_image *image` 输入的 bm_image 对象。
- `const String &fname` dump 的输出文件名。

## 返回值
- 无。

# Mat::avOK

## 函数定义
```cpp
bool Mat::avOK()
```

## 功能和说明
- 判断当前 Mat 是否为扩展的 YUV 格式。
- 接口和接口 3.21 3.22 downloadMat、uploadMat 结合起来，可以有效地管理内存同步。
- 一般 avOK 为 true 的 Mat，物理内存或者 PCIE 卡设备内存是最新的，而 avOK 为 false 的 Mat，其 cache 或者 host 内存中的数据是最新的。可以根据这个信息，决定是调用 uploadMat 还是 downloadMat。
- 如果一直在设备内存中通过硬件加速单元工作，则可以省略内存同步，仅在需要交换到系统内存中时再调用 downloadMat。

## 参数说明
- 无。

## 返回值
- `true` 表示当前 Mat 为扩展的 YUV 格式。
- `false` 表示当前 Mat 为标准 OpenCV 格式。

# Mat::avCols

## 函数定义
```cpp
int Mat::avCols()
```

## 功能和说明
- 获取 YUV 扩展格式的 Y 的宽。

## 参数说明
- 无。

## 返回值
- 返回扩展的 YUV 格式的 Y 的宽，如果为标准 OpenCV Mat 格式，返回 0。

# Mat::avRows

## 函数定义
```cpp
int Mat::avRows()
```

## 功能和说明
- 获取 YUV 扩展格式的 Y 的高。

## 参数说明
- 无。

## 返回值
- 返回扩展的 YUV 格式的 Y 的高，如果为标准 OpenCV Mat 格式，返回 0。

# Mat::avFormat

## 函数定义
```cpp
int Mat::avFormat()
```

## 功能和说明
- 获取 YUV 格式信息。

## 参数说明
- 无。

## 返回值
- 返回扩展的 YUV 格式信息，如果为标准 OpenCV Mat 格式，返回 0。

# Mat::avAddr

## 函数定义
```cpp
int Mat::avAddr(int idx)
```

## 功能和说明
- 获取 YUV 各分量的物理地址。

## 参数说明
- `int idx` 指定 YUV plane 的序号。

## 返回值
- 返回指定的 plane 的物理首地址，如果为标准 OpenCV Mat 格式，返回 0。

# Mat::avStep

## 函数定义
```cpp
int Mat::avStep(int idx)
```

## 功能和说明
- 获取YUV格式中指定plane的line size。
- 如果为标准OpenCV Mat格式，返回0。

## 参数说明
- `int idx` 指定YUV plane的序号。

## 返回值
- 返回指定的plane的line size，如果为标准OpenCV Mat格式，返回0。

# av::create

## 函数定义
```cpp
AVFrame* av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MPEG, int id = 0)
```

## 功能和说明
- AVFrame的创建接口，允许外部创建系统内存和物理内存，创建的格式与FFMPEG下的AVFrame定义兼容。
- 本接口支持创建以下图像格式的AVFrame数据结构：AV_PIX_FMT_GRAY8, AV_PIX_FMT_GBRP, AV_PIX_FMT_YUV420P, AV_PIX_FMT_NV12, AV_PIX_FMT_YUV422P horizontal, AV_PIX_FMT_YUV444P, AV_PIX_FMT_NV16。
- 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建失败。

## 参数说明
- `int height` 创建图像数据的高。
- `int width` 创建图像数据的宽。
- `int color_format` 创建图像数据的格式，详见FFMPEG pixfmt.h定义。
- `void *data` 系统内存地址，当为null时，表示该接口内部自己创建管理。
- `long addr` 设备内存地址。
- `int fd` 设备内存地址的句柄。如果为-1，表示设备内存由内部分配，反之则由addr参数给出。在pcie模式下，如果设备内存由外部给出，该值可以设为0，在soc模式下，该值应该为ion内存的句柄。
- `int* plane_stride` 图像数据每层的每行stride数组。
- `int* plane_size` 图像数据每层的大小。
- `int color_space` 输入image的色彩空间，可以为AVCOL_SPC_BT709或AVCOL_SPC_BT470，详见FFMPEG pixfmt.h定义, 默认为AVCOL_SPC_BT709。
- `int color_range` 输入image的色彩动态范围，可以为AVCOL_RANGE_MPEG或AVCOL_RANGE_JPEG，详见FFMPEG pixfmt.h定义，默认为AVCOL_RANGE_MPEG。
- `int id` 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0。

## 返回值
- 返回AVFrame结构体指针。

# av::create

## 函数定义
```cpp
AVFrame* av::create(int height, int width, int id = 0)
```

## 功能和说明
- AVFrame的简易创建接口，所有内存均由内部创建管理，仅支持YUV420P格式。
- 本接口仅支持创建YUV420P格式的AVFrame数据结构。

## 参数说明
- `int height` 创建图像数据的高。
- `int width` 创建图像数据的宽。
- `int id` 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0。

## 返回值
- 返回AVFrame结构体指针。

# av::copy

## 函数定义
```cpp
int av::copy(AVFrame *src, AVFrame *dst, int id)
```

## 功能和说明
- AVFrame的深度copy函数，将src的有效图像数据拷贝到dst中。
- 本接口仅支持同设备卡号内的图像数据拷贝，即id相同。
- 函数中的id仅需要指定设备卡号，不需要其他标志位。

## 参数说明
- `AVFrame *src` 输入的AVFrame原始数据指针。
- `AVFrame *dst` 输出的AVFrame目标数据指针。
- `int id` 指定设备卡号，详见5.1。

## 返回值
- 返回copy的有效图像数据个数，为0则没有发生拷贝。

# av::get_scale_and_plane

## 函数定义
```cpp
int av::get_scale_and_plane(int color_format, int wscale[], int hscale[])
```

## 功能和说明
- 获取指定图像格式相对于YUV444P的宽高比例系数。

## 参数说明
- `int color_format` 输入参数，指定图像格式，详见FFMPEG pixfmt.h定义。
- `int wscale[]` 输出参数，对应格式相对于YUV444P每一层的宽度比例。
- `int hscale[]` 输出参数，对应格式相对于YUV444P每一层的高度比例。

## 返回值
- 返回给定图像格式的plane层数。

# cv::Mat(AVFrame *frame, int id)

## 函数定义
```cpp
cv::Mat(AVFrame *frame, int id)
```

## 功能和说明
- 新增的Mat构造接口。根据AVFrame指针信息构造扩展的YUV Mat数据。
- 当AVFRAME_ATTACHED标志位为1时，表示frame由外部创建并释放，不需要Mat来管理；反之则在释放Mat的同时释放frame指向的内存块。

## 参数说明
- `AVFrame *frame` 输入参数，AVFrame数据，可以来自FFMPEG或者cv::av下方法创建。
- `int id` 输入参数，指定PCIE设备卡号以及AVFRAME_ATTACHED标志，详见5.1。

## 返回值
- 构造的扩展Mat数据类型。

# cv::Mat

## 函数定义
```cpp
cv::Mat(int height, int width, int total, int type, const size_t* steps, void* data, unsigned long addr, int fd, SophonDevice device=SophonDevice())
```

## 功能和说明
- 新增的Mat构造接口。可以创建opencv标准格式或扩展的YUV Mat格式，并且系统内存和设备内存都允许通过外部分配给定。
- SophonDevice是为了避免C++隐含类型匹配造成函数匹配失误而引入的类型，可以用SophonDevice(int id)直接从5.1节的ID转换过来。
- 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存。

## 参数说明
- `int height` 输入参数，输入图像数据的高。
- `int width` 输入参数，输入图像数据的宽。
- `int total` 输入参数，内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小。
- `int type` 输入参数，Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1。
- `const size_t* steps` 输入参数，所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP。
- `void* data` 输入参数，系统内存指针，如果为null，则内部分配该内存。
- `unsigned long addr` 输入参数，设备物理内存地址，任意值均被认为有效的物理地址。
- `int fd` 输入参数，设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理。
- `SophonDevice device` 输入参数，指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0。

## 返回值
- 构造的标准BGR或扩展YUV的Mat数据类型。

# Mat::Mat(SophonDevice device)

## 功能和说明

* 新增的Mat构造接口，指定该Mat的后续操作在给定的device设备上。
* 本构造函数仅初始化Mat内部的设备index，并不实际创建内存。
* 本构造函数的最大作用是对于某些内部create内存的函数，可以通过这个构造函数，提前指定创建内存的设备号和HEAP位置，从而避免将大量的内存分配在默认的设备号0上。

## 函数名

`Mat::Mat(SophonDevice device)`

## 参数说明

* `SophonDevice device` 输入参数，指定设备卡号以及HEAP位置的标志，详见5.1。

## 返回值

* 声明Mat数据类型。

# Mat::create(AVFrame *frame, int id)

## 功能和说明

* Mat分配内存的接口，根据AVFrame指针信息构造扩展的开辟YUV Mat内存。
* 1. 当AVFRAME_ATTACHED标志位为1时，表示frame由外部创建并释放，不需要Mat来管理；反之则在释放Mat的同时释放frame指向的内存块。
* 2. 当原来的Mat已经分配了内存的话，如果该内存满足AVFrame的要求，则复用该内存，反之则会自动释放原内存，并重新分配。

## 函数名

`Mat::create(AVFrame *frame, int id)`

## 参数说明

* `AVFrame *frame` 输入参数，AVFrame数据，可以来自FFMPEG或者cv::av下方法创建。
* `int id` 输入参数，指定PCIE设备卡号以及AVFRAME_ATTACHED标志，详见5.1。

## 返回值

* 无。

# Mat::create(int height, int width, int total, int type, const size_t* steps, void* data, unsigned long addr, int fd, int id = 0)

## 功能和说明

* Mat分配内存接口，该接口系统内存和设备内存都允许通过外部分配给定，也可内部分配。
* 扩展的内存分配接口，主要改进目的是允许外置指定设备物理内存，当设备或者系统内存由外部创建的时候，则外部必须负责该内存的释放，否则会造成内存泄漏。
* 当设备内存和系统内存均有外部给出时，在soc模式下外部要保证两者地址的匹配，即系统内存是设备内存映射出来的虚拟地址；当设备内存由外部给出，系统内存为null时，该接口内部会自动创建系统内存；当设备内存没有给出，系统内存也为null时，本接口内部会自动创建；当设备内存没有给出，系统内存由外部给出时，本接口创建的Mat在soc模式下只有系统内存，在pcie模式下会自动创建设备内存。

## 函数名

`Mat::create(int height, int width, int total, int type, const size_t* steps, void* data, unsigned long addr, int fd, int id = 0)`

## 参数说明

* `int height` 输入图像数据的高。
* `int width` 输入图像数据的宽。
* `int total` 内存大小，该内存可以为内部待分配的内存，或外部已分配内存的大小。
* `int type` Mat类型，本接口只支持CV_8UC1或CV_8UC3，扩展的YUV Mat的格式_type类型一律为CV_8UC1。
* `const size_t* steps` 所创建的图像数据的step信息，如果该指针为null,则为AUTO_STEP。
* `void* data` 系统内存指针，如果为null，则内部分配该内存。
* `unsigned long addr` 设备物理内存地址，任意值均被认为有效的物理地址。
* `int fd` 设备物理内存对应的句柄。如果为负，则设备物理内存在内部分配管理。
* `int id` 指定设备卡号以及HEAP位置的标志，详见5.1，该参数默认为0。

## 返回值

* 无

# VideoWriter::write(InputArray image, char* data, int* len)

## 功能和说明

* 新增的视频编码接口。与OpenCV标准VideoWriter::write接口不同，他提供了将编码视频数据输出到buffer的功能，便于后续处理。

## 函数名

`void VideoWriter::write(InputArray image, char* data, int* len)`

## 参数说明

* `InputArray image` 输入参数，输入的图像数据Mat结构。
* `char* data` 输出参数，输出的编码数据缓存。
* `int* len` 输出参数，输出的编码数据长度。

## 返回值

* 无

# VideoCapture::grab(char* buf, unsigned int len_in, unsigned int* len_out)

## 功能和说明

* 新增的收流解码接口。与OpenCV标准VideoCapture::grab接口不同，他提供了将解码前的视频数据输出到buf的功能。

## 函数名

`bool VideoCapture::grab(char* buf, unsigned int len_in, unsigned int* len_out)`

## 参数说明

* `char* buf` 存储抓取到的视频帧数据的缓冲区，外部负责分配释放内存。
* `unsigned int len_in` 输入buf空间的大小。
* `unsigned int* len_out` 输出的buf的实际大小。

## 返回值

* `true` 表示收流解码成功。
* `false` 表示收流解码失败。

# VideoCapture::read_record(OutputArray image, char* buf, unsigned int len_in, unsigned int* len_out)

## 功能和说明

* 新增的读取码流视频接口。他提供了将解码前的视频数据输出到buf的功能，将解码后的数据输出到image。

## 函数名

`bool VideoCapture::read_record(OutputArray image, char* buf, unsigned int len_in, unsigned int* len_out)`

## 参数说明

* `char* buf` 输入参数，外部负责分配释放内存。
* `unsigned int len_in` 输入参数，buf空间的大小。
* `OutputArray image` 输出参数，输出解码后的视频数据。
* `char* buf` 输出参数，输出解码前的视频数据。
* `int* len_out` 输出参数，输出的buf的实际大小。

## 返回值

* `true` 表示收流解码成功。
* `false` 表示收流解码失败。

# 硬件JPEG解码器的OpenCV 扩展

在BM168x系列中，提供JPEG硬件编码解码模块。为使用这些硬件模块，SDK软件包中，扩展了OpenCV中与JPEG图片处理相关的API函数，如：cv::imread()、 cv::imwrite()、cv::imdecode()、cv::imencode()等。您在使用这些函数做JPEG编解码的时候，函数内部会自动调用底层的硬件加速资源，从而大幅度提高了编解码的效率。如果您想保持这些函数原始的OpenCV API使用习惯，可以略过本节介绍；但如果你还想了解一下我们提供的简单易用的扩展功能，这节可能对您非常有帮助。

## 输出yuv格式的图像数据

OpenCV原生的cv::imread()、cv::imdecode() API函数执行JPEG图片的解码操作，返回一个Mat结构体，该Mat结构体中保存有BGR packed格式的图片数据，算能扩展的API函数功能可以返回JPEG图片解码后的原始的YUV格式数据。用法如下：

当这两个函数的第二个参数flags被设置成cv::IMREAD_AVFRAME时，表示解码后返回的Mat结构体out中保存着YUV格式的数据。具体是什么格式的YUV数据要根据JPEG文件的image格式而定。当flags被设置成其它值或者省略不设置时，表示解码输出OpenCV原生的BGR packed格式的Mat数据。解码器输入输出扩展数据格式说明如下表所示：

| 输入Image格式 | 输入YUV格式 | FFMPEG对应格式 |
|--------------|------------|---------------|
| I400         | I400       | AV_PIX_FMT_GRAY8 |
| I420         | NV12       | AV_PIX_FMT_NV12 |
| I422         | NV16       | AV_PIX_FMT_NV16 |
| I444         | I444 planar | AV_PIX_FMT_YUV444P |

可以通过Mat::avFormat()扩展函数，得到当前数据所对应的具体的FFmpeg格式。可以通过Mat::avOK()扩展函数，得知cv::imdecode(buf, cv::IMREAD_AVFRAME, &out)解码返回的out，是否是算能扩展的Mat数据格式。

另外在这两个接口中的flags增加cv::IMREAD_RETRY_SOFTDEC标志时会在硬件解码失败的情况下尝试切换软件解码，也可以通过设置环境变量OPENCV_RETRY_SOFTDEC=1实现此功能。

## 支持YUV格式的函数列表

目前算能Opencv已经支持YUV Mat扩展格式的函数接口列表如下：

- 视频解码类接口
  - VideoCapture类的成员函数

这类成员函数如read, grab，对于常用的HEVC, H264视频格式都使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

- 视频编码类接口
  - VideoWriter类的成员函数

这类成员函数如write，对于常用的HEVC,H264视频格式已经使用了BM168x系列的硬件加速，并支持YUV Mat扩展格式。

- JPEG编码类接口
- JPEG解码类接口
  - Imread
  - Imwrite
  - Imdecode
  - Imencode

以上接口在处理JPEG格式的时候，已经使用了BM168x系列的硬件加速功能，并支持YUV Mat扩展格式。

- 图像处理类接口
  - cvtColor
  - resize

这两个接口在BM168x系列 SOC模式下支持YUV Mat扩展格式，并使用硬件加速进行了优化。

**尤其需要注意的是cvtColor接口，只在YUV转换成BGR或者GRAY输出的时候支持硬件加速和YUV Mat的格式，即只支持输入为YUV Mat格式，并进行了硬件加速，输出不支持YUV Mat格式。**

在PCIE模式下，考虑到服务器的处理器性能较强，仍然采用原来的opencv原生处理方式，并不支持YUV扩展格式。

- line
- rectangle
- circle
- putText

以上四个接口均支持YUV扩展格式。注意，这四个接口并没有采用硬件加速，而是使用处理器对YUV Mat扩展格式进行的支持。

- 基本操作类接口
  - Mat类部分接口
    - 创建释放接口：create，release，Mat声明接口
    - 内存赋值接口：clone，copyTo， cloneAll，copyAllTo，assignTo, operator =
    - 扩展AV接口：avOK, avComp, avRows, avCols, avFormat, avStep, avAddr

以上接口均支持YUV扩展格式，尤其是copyTo, clone接口都采用硬件进行了加速。

- 扩展类接口
  - Bmcv接口: 详见opencv2/core/bmcv.hpp
  - AvFrame接口: 详见opencv2/core/av.hpp

以上算能扩展类接口，均支持YUV Mat扩展格式，并均针对硬件加速处理进行了优化。

**注意：支持YUV Mat扩展格式的接口并不等价于使用了硬件加速，部分接口是通过处理器处理来实现。这点需要特别注意。**

# 在指定设备运行硬件加速

本节内容适用于VideoCapture, 图像编解码的Imread, Imwrite等接口。

## PCIE ID参数的定义

ID参数为32位整型，它定义了pcie设备卡以及部分内存扩展标志信息，具体定义如下：

| Bit位域 | 描述 |
|---------|------|
| Bit0-7 | 描述了PCIE设备的卡号，宏定义BM_CARD_ID(id)可以获取这信息 |
| Bit8-10 | 描述对应PCIE卡上的HEAP内存位置。Bit8为1表示硬件内存分配在 heap0上；Bit9为1表示硬件内存内存分配在 heap1上；Bit10为1表示硬件内存内存分配在 heap2上；Bit8-10全为0默认分配在 heap1上；Heap0/1/2的内存位置详见BMLIB API手册。宏定义BM_CARD_HEAP(id)可获取该信息 |
| Bit11-20 | 描述了Mat的内存扩展标志。B11-B18为opencv标准定义，见MemoryFlag枚举类型B19-为扩展的DEVICE_MEM_ATTACHED，标志该设备内存为外部管理，不需要Opencv来管理释放B20-为扩展的AVFRAME_ATTACHED，标志创建YUV Mat的AVFrame为外部管理，不需要Opencv来管理释放。宏定义BM_CARD_MEMFLAG(id)可获取该信息 |
| B21-31 | 扩展保留 |
| 说明: | 宏定义BM_MAKEFLAG(attach,heap,card)可用来生成完整的ID定义，其中attach对应B11-20,heap对应 B8-10,card对应B0-7 |

## 利用ID参数指定PCIE设备

在PCIE模式下，多设备情况下需要指定在特定卡上运行硬件加速功能。为了满足这个需要，SOPHGO OpenCV对VideoCapture::Open, imread, imdecode以及mat.create接口进行了扩展，增加了int id参数。

```
bool VideoCapture::open(const String& filename, int apiPreference, int id)
Mat imdecode(InputArray _buf, int flags, int id )
Mat imread(const String& filename, int flags, int id )
void Mat::create(int d, const int* _sizes, int _type, int id)
```

通过指定id，可以指定视频解码、图片解码运行在指定PCIE设备上，并且解码出来的Mat输出记录了该PCIE卡设备的序号。后续的硬件加速操作会继续在该指定PCIE设备上运行。

对于输入是Mat的大部分接口来说，因为Mat在调用create接口分配内存的时候已经指定了设备号，就不需要额外增加参数来指定PCIE卡设备。可以根据Mat内置的设备号在对应的设备上进行加速处理。

## SOC ID参数的定义

soc 下id的含义，可以参考pcie，在id使用上可以将soc看做是pcie设备的卡号0(Bit0-7)，其他字段含义相同

# OpenCV与BMCV API的调用原则

BMCV API充分发挥了BM168x系列中的硬件单元的加速能力，能提高数据处理的效率。而OpenCV软件提供了非常丰富的图像图形处理能力，将两者有机的结合起来，使客户开发既能利用OpenCV丰富的函数库，又能在硬件支持的功能上获得加速，是本节的主要目的。

在BMCV API和OpenCV函数以及数据类型的切换过程中，最关键是要尽量避免数据拷贝，使得切换代价最小。因此在调用流程中要遵循以下原则。

1. 由OpenCV Mat到BMCV API的切换，可以利用toBMI()函数，该函数以零拷贝的方式，将Mat中的数据转换成了BMCV API调用所需的bm_image类型。

2. 当BMCV API需要切换到OpenCV Mat的时候，要将最后一步的操作通过OpenCV中的bmcv函数来实现。这样既完成所需的图像处理操作，同时也为后续OpenCV操作完成了数据类型准备。因为一般OpenCV都要求BGR Pack的色彩空间，所以一般用toMat()函数作为切换前的最后一步操作。

3. 一般神经网络处理的数据为不带padding的RGB planar数据，并且对于输入尺寸有特定的要求。因此建议将resize()函数作为调用神经网络NPU接口前的最后一步操作。

4. 当crop、resize、color conversion三个操作是连续的时候，强烈建议客户使用convert()函数，这可以在带宽优化和速度优化方面都获得理想的收益。即使后续可能还需要做一次拷贝，但因为拷贝发生在缩放之后的图像上，这种代价也是值得的。

# OpenCV中GB28181国标接口介绍

SOPHGO复用OpenCV原生的Cap接口，通过对于url定义进行扩展，提供GB28181国标的播放支持。因此客户并不需要重新熟悉接口，只要对扩展的url定义进行理解，即可像播放rtsp视频一样，无缝的播放GB28181视频。

注意：国标中的SIP代理注册步骤，需要客户自己管理。当获取到前端设备列表后，可以直接用url的方式进行播放。

## 国标GB28181支持的一般步骤

- 启动SIP代理（一般客户自己部署或者平台方提供）
- 客户的下级应用平台注册到SIP代理
- 客户应用获取前端设备列表，如下所示。其中，34010000001310000009等为设备20位编码。

```
{"devidelist":
[{"id": "34010000001310000009"}
{"id": "34010000001310000010"}
{"id": "34020000001310101202"}]}
```

- 组织GB28181 url直接调用OpenCV Cap接口进行播放

## GB28181 url格式定义

### UDP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=34010000001310000009#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108:
```

**注释**

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

localmediaport: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

### UDP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713:
```

**注释**

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

devicetype: 录像存储类型

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

localmediaport: 媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801, rtcp:11802)，两个端口映射的in和out要相同。同一个核心板端口不可重复。

begtime: 录像起始时间

endtime: 录像结束时间

### TCP实时流地址定义

```
gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201:
```

**注释**

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

### TCP回放流地址定义

```
gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713:
```

**注释**

34020000002019000001:123456@35.26.240.99:5666: sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port

deviceid: 前端设备20位编码

devicetype: 录像存储类型

localid: 本地二十位编码，可选项

localip: 本地ip，可选项

begtime: 录像起始时间

endtime: 录像结束时间

# PCIE模式下BMCPU OPENCV加速

## 概念介绍

Opencv有大量的图像处理函数在host处理器上实现，这样在PCIE环境下，就造成了host和板卡device设备之间交换同步内存的需求，而这种内存同步的速度要远远慢于内存cache的数据同步速度，从而给PCIE环境下的应用开发造成了瓶颈。而我们在的BM168x板卡上的每颗SOC都有强大的ARM Cortex A53处理器资源，目前在PCIE环境下处于闲置状态，因此BMCPU Opencv试图将Host Opencv和Device Opencv之间的功能函数映射起来，将Host Opencv的操作实际用Device Opencv的操作来实现，保证所有的数据都在Device Memory中进行，无需通过PCIE和host发生交换，从而一方面降低对Host处理器的压力，降低处理器的处理性能要求，另一方面提高运行速度，消除PCIE带宽所带来的瓶颈。

BMCPU OPENCV的函数用法与原生OPENCV完全一致，只是为了区别在前面加上"bmcpu_"前缀。

## 使用说明

**说明1.凡是用BMCPU OPENCV改造过的接口，最新数据都位于device memory中。**

这点与之前的opencv cache管理策略有不同。之前在YUV Mat中，最新数据都位于device memory中，而在RGB Mat中，最新数据都位于host memory中。经过BMCPU OPENCV引入后，后续当函数支持到足够数目的时候，我们将在PCIE模式下，无论RGB Mat还是YUV Mat都以device memory为准，这样所有的pcie opencv操作的内存都移到了device memory上，不占用host memory。

**在达到这个目的之前，为了兼容原有opencv函数的调用，保留原函数，然后统一加上"bmcpu_"前缀的方式，重命名已修改的函数。**可以查询我们的已完成函数列表来做对应操作。

对于列表中的函数，无论yuv Mat还是RGB Mat最新数据都在device memory中。当客户需要将其同步到host memory中的时候，需要手动调用bmcv::downloadMat()接口，当需要将host memory中的数据同步到device memory中时，需要调用bmcv::uploadMat()接口。

这点尤其重要，在调用改造过的函数前，如果最新数据在host memory中，就需要将其同步到device memory。**这在当Mat采用Scalar::all()，Zeros(), Ones()等函数初始化的时候尤其容易忽略，这时候要记得调用bmcv::uploadMat()将初始化同步到设备内存中。**反之，当函数结束，后续处理需要在host memory中进行的时候，就需要调用bmcv::downloadMat()下载下来。

当输入输出Mat没有device内存的时候，函数会自动同步到host内存中，并且释放内部开辟的device内存。

**说明2. 参数传递的时候，要求与Mat有关的参数放在最前面。因为Mat的内存结构是提前分配好的，只能修改，不能重新分配。**

**说明3. 已完成函数列表**

| 已完成函数接口 | 修改后函数 | 说明 |
|---------------|------------|------|
| cv::calcOpticalFlowPyrLK() | cv::bmcpu_calcOpticalFlowPyrLK() | 稀疏光流函数，支持标准BGR Mat格式 |
| cv::calcOpticalFlowFarneback() | cv::bmcpu_calcOpticalFlowFarneback() | 稠密光流函数，支持标准BGR Mat格式 |
| cv::gaussianBlur() | cv::bmcpu_gaussianBlur() | 支持BGR Mat格式 |
| cv::bilateralFilter() | cv::bmcpu_bilateralFilter() | 支持BGR Mat格式 |
| cv::boxFilter() | cv::bmcpu_boxFilter() | 支持BGR Mat格式 |
| cv::calcHist() | cv::bmcpu_calcHist() | calcHist函数共有三个函数类型，除了SparseMat不支持外，其他两个均支持 |
| cv::warpAffine() | cv::bmcpu_warpAffine() | 支持BGR Mat格式 |
| cv::sobel() | cv::bmcpu_sobel() | 支持BGR Mat格式 |
| cv::erode() | cv::bmcpu_erode() | 支持BGR Mat格式 |
| cv::dialet() | cv::bmcpu_dialet() | 支持BGR Mat格式 |
| cv::morphologyEx | cv::bmcpu_morphologyEx() | 支持BGR Mat格式 |
| cv::line() | cv::bmcpu_line() | Opencv中的画线函数，可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::putText() | cv::bmcpu_putText() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::rectangle() | cv::bmcpu_rectangle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::circle() | cv::bmcpu_circle() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse() | 1.对应opencv中的函数:void ellipse(InputOutput Array _img, Point center, Size axes,double angle,double start_angle,double end_angle,const Scalar & color,int thickness,int line_type,int shift)<br>2.可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::ellipse() | cv::bmcpu_ellipse2() | 1.对应opencv中的函数:void ellipse(InputOutput Array _img, const RotatedRect& box, const Scalar & color,int thickness, int lineType)<br>2.可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| cv::polylines() | cv::bmcpu_polylines() | 可同时支持YUV和RGB Mat两种类型。YUV支持YUV420P格式 |
| FreeType2::loadFontData() | cv::bmcpu_loadFontData() | 对应FreeType2类加载字库 |
| - | cv::bmcpu_unloadFontData() | 释放字库资源，与bmcpu_loadFontData成对调用 |
| FreeType2::setSplitNumber() | cv::bmcpu_setSplitNumber() | Ft2类接口 |
| FreeType2::getTextSize() | cv::bmcpu_getTextSize() | Ft2类接口 |
| FreeType2::putText() | cv::bmcpu_ft2_putText() | 可同时支持YUV和RGB Mat |

## 代码实例

代码实例见bmnnsdk2软件包中的examples/multimedia。

# SOPHGO FFMPEG使用指南

## 前言

BM168x系列中，有一个8核的A53处理器，同时还内置有视频、图像相关硬件加速模块。在SOPHGO提供的FFMPEG SDK开发包中，提供了对这些硬件模块的接口。其中，通过这些硬件接口，提供了如下模块：硬件视频解码器、硬件视频编码器、硬件JPEG解码器、硬件JPEG编码器、硬件scale filter、hwupload filter、hwdownload filter。

FFMPEG SDK开发包符合FFMPEG hwaccel编写规范，实现了视频转码硬件加速框架，实现了硬件内存管理、各个硬件处理模块流程的组织等功能。同时FFMPEG SDK也提供了与通常处理器解码器兼容的接口，以匹配部分客户的使用习惯。这两套接口我们称之为HWAccel接口和常规接口，他们底层共享BM168x硬件加速模块，在性能上是相同的。区别仅在于1）HWAccel需要初始化硬件设备 2）HWAccel接口只面向设备内存，而常规接口同时分配了设备内存和系统内存 3）他们的参数配置和接口调用上有轻微差别。

下面描述中，如非特殊说明，对常规接口和HWAccel接口都适用。

## 硬件视频解码器

BM168x系列支持H.264和H.265硬件解码。硬件解码器性能详情如下表所述。

| **Standard** | **Profile** | **Level** | **Max Resolution** | **Min Resolution** | **Bit rate** |
|-------------|-------------|-----------|-------------------|-------------------|-------------|
| H.264/AVC | BP/CBP/MP/HP | 4.1 | 8192x4096 | 16x16 | 50Mbps |
| H.265/HEVC | Main/Main10 | L5.1 | 8192x4096 | 16x16 | N/A |

在SOPHGO的FFMPEG发布包中，H.264硬件视频解码器的名字为*h264_bm*，H.265硬件视频解码器的名字为*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -decoders | grep _bm
```

### 硬件视频解码器支持的选项

FFMPEG中，BM168x系列的硬件解码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h decoder=h264_bm
$ ffmpeg -h decoder=hevc_bm
```

这些选项可以使用av_dict_set API来设置。在设置之前，需要对对这些选项有正确的理解。下面详细解释一下这些选项。

**output_format:**
- 输出数据的格式
- 设为0，则输出线性排列的未压缩数据；设为101，则输出压缩数据
- 缺省值为0
- *推荐设置为101，输出压缩数据。可以节省内存、节省带宽。输出的压缩数据，可以调用后面介绍的scale_bm filter解压缩成正常的YUV数据。具体可参考应用示例中的示例1*

**cbcr_interleave:**
- 硬件视频解码器解码输出的帧色度数据是否是交织格式
- 设为1，则输出为semi-planar yuv图像，譬如nv12；设为0，则输出planar yuv图像，譬如yuv420p
- 缺省值为1

**extra_frame_buffer_num:**
- 硬件视频解码器额外提供硬件帧缓存数量
- 缺省值为2。最小值为1

**skip_non_idr:**
- 跳帧模式。0，关闭；1，跳过Non-RAP帧；2，跳过非参考帧
- 缺省值为0

**handle_packet_loss**
- 出错时，对H.264, H.265解码器使能丢包处理。0, 不做丢包处理；1，进行丢包处理
- 缺省值为0

**sophon_idx:**
- PCIE模式下的SOPHON设备的编号。与/dev/bm-sophon的设备编号一致
- 缺省值为0

**zero_copy:**
- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的系统内存里。1，关闭拷贝；0，使能拷贝
- 缺省值为1

## 硬件视频编码器

从BM1684开始首次添加了硬件视频编码器。支持H.264/AVC和H.265/HEVC视频编码。

BM1684硬件编码器设计的能力为: 能够实时编码一路1080P30的视频。具体指标如下：

**H.265编码器:**
- Capable of encoding HEVC Main/Main10/MSP(Main Still Picture) Profile @ L5.1 High-tier

**H.264编码器:**
- Capable of encoding Baseline/Constrained Baseline/Main/High/High 10 Profiles Level @ L5.2

**通用指标**
- 最大分辨率 : 8192x8192
- 最小分辨率 : 256x128
- 编码图像宽度须为8的倍数
- 编码图像高度宽度须为8的倍数

在SOPHGO的FFMPEG发布包中，H.264硬件视频编码器的名字为*h264_bm*，H.265硬件视频编码器的名字为*h265_bm*或*hevc_bm*。可通过如下命令, 来查询FFMPEG支持的编码器。

```
$ ffmpeg -encoders
```

### 硬件视频编码器支持的选项

FFMPEG中，硬件视频编码器提供了一些额外选项，可以通过如下命令查询。

```
$ ffmpeg -h encoder=h264_bm
$ ffmpeg -h encoder=hevc_bm
```

BM1684硬件视频编码器支持如下选项:

**preset:** 预设编码模式。推荐通过enc-params设置
- 0 - fast, 1 - medium, 2 - slow
- 缺省值为2

**gop_preset:** gop预设索引值。推荐通过enc-params设置
- 1: all I, gopsize 1
- 2: IPP, cyclic gopsize 1
- 3: IBB, cyclic gopsize 1
- 4: IBPBP, cyclic gopsize 2
- 5: IBBBP, cyclic gopsize 4
- 6: IPPPP, cyclic gopsize 4
- 7: IBBBB, cyclic gopsize 4
- 8: random access, IBBBBBBBB, cyclic gopsize 8

**qp:**
- 恒定量化参数的码率控制方法
- 取值范围为0至51

**perf:**
- 用于指示是否需要测试编码器性能
- 取值范围为0或1

**enc-params:**
- 用于设置视频编码器内部参数
- 支持的编码参数：preset，gop_preset，qp，bitrate，mb_rc，delta_qp，min_qp，max_qp
- 编码参数preset：取值范围为fast, medium, slow或者是0，1，2
- 编码参数gop_preset：gop预设索引值。参考上面已有详细解释
    - 1: all I, gopsize 1
    - 2: IPP, cyclic gopsize 1
    - 3: IBB, cyclic gopsize 1
    - 4: IBPBP, cyclic gopsize 2
    - 5: IBBBP, cyclic gopsize 4
    - 6: IPPPP, cyclic gopsize 4
    - 7: IBBBB, cyclic gopsize 4
    - 8: random access, IBBBBBBBB, cyclic gopsize 8
- 编码参数qp：恒定量化参数，取值范围为[0, 51]。当该值有效时，关闭码率控制算法，用固定的量化参数编码
- 编码参数bitrate：用于编码所指定的码率。单位是Kbps，1Kbps=1000bps。当指定改参数时，请不要设置编码参数qp
- 编码参数mb_rc：取值范围0或1。当设为1时，开启宏块级码率控制算法；当设为0时，开启帧级码率控制算法
- 编码参数delta_qp：用于码率控制算法的QP最大差值。该值太大影响视频主观质量。太小影响码率调整的速度
- 编码参数min_qp和max_qp：码率控制算法中用于控制码率和视频质量的最小量化参数和最大量化参数。取值范围[0, 51]

**sophon_idx:** 仅适用于PCIE模式
- 用于指出要使用的SOPHON设备的编号。与/dev/bm-sophon的编号一致
- 最小值为0, 最大值为SOPHON设备数量减1
- *仅适用于常规接口*

**is_dma_buffer:**
- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址
- 在PCIE模式时，值0表示输入的是系统内存虚拟地址；在soc模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址
- 缺省值为1
- *仅适用于常规接口*

## 硬件JPEG解码器

# 硬件JPEG解码器

在BM168x系列中，硬件JPEG解码器提供硬件JPEG图像解码输入能力。这里介绍一下，如何通过FFMPEG来实现硬件JPEG解码。

在FFMPEG中，硬件JPEG解码器的名称为*jpeg_bm*。可以通过如下命令，来查看FFMPEG中是否有*jpeg_bm*解码器。

```
ffmpeg -decoders | grep jpeg_bm
```

## 硬件JPEG解码器支持的选项

FFMPEG中，可以通过如下命令，来查看*jpeg_bm*解码器支持的选项

```
ffmpeg -h decoder=jpeg_bm
```

解码选项的说明如下。硬件JPEG解码器中这些选项，可以使用 av_dict_set() API 函数对其进行重置。

**bs_buffer_size**: 用于设置硬件JPEG解码器中输入比特流的缓存大小(KBytes)。

- 取值范围(0到INT_MAX)
- 缺省值5120

**cbcr_interleave**: 用于指示JPEG解码器输出的帧数据中色度数据是否为交织的格式。

- 0: 输出的帧数据中色度数据为plannar的格式
- 1: 输出的帧数据中色度数据为interleave的格式
- 缺省值为0

**num_extra_framebuffers**: JPEG解码器需要的额外帧缓存数量

- 对于Still JPEG的输入，建议该值设为0
- 对于Motion JPEG的输入，建议该值至少为2
- 取值范围(0到INT_MAX)
- 缺省值为2

**sophon_idx**: 仅适用于PCIE模式。

- 用于指出要使用的SOPHON设备的编号。与/dev/bm-sophon的编号一致
- 最小值为0，最大值为SOPHON设备数量减1
- *仅适用于常规接口。*

**zero_copy**:

- 将设备上的帧数据直接拷贝到AVFrame的data[0]-data[3]所自动申请的内存里。1，关闭拷贝；0，使能拷贝。
- 缺省值为1。
- *仅适用于旧接口的PCIE模式*。新接口提供hwdownload filter，可以显式地把数据从设备内存下载到系统内存。

# 硬件JPEG编码器

在BM168x系列中，硬件JPEG编码器提供硬件JPEG图像编码输出能力。这里介绍一下，*如何通过FFMPEG来实现硬件JPEG编码*。

在FFMPEG中，硬件JPEG编码器的名称为*jpeg_bm*。可以通过如下命令，来查看FFMPEG中是否有jpeg_bm编码器。

```
ffmpeg -encoders | grep jpeg_bm
```

## 硬件JPEG编码器支持的选项

FFMPEG中，可以通过如下命令，来查看jpeg_bm编码器支持的选项

```
ffmpeg -h encoder=jpeg_bm
```

编码选项的说明如下。硬件JPEG编码器中这些选项，可以使用 av_dict_set() API 函数对其进行重置。

**sophon_idx**: 仅适用于PCIE模式

- 用于指出要使用的SOPHON设备的编号。与/dev/bm-sophon的编号一致。
- 最小值为0，最大值为SOPHON设备数量减1
- *仅适用于常规接口。*

**is_dma_buffer**:

- 用于提示编码器，输入的帧缓存是否为设备上的连续物理内存地址。
- 在PCIE模式时，值0表示输入的是系统内存虚拟地址；在soc模式，值0表示输入的是设备内存的虚拟地址。值1表示，输入的是设备上的连续物理地址。
- 缺省值为1。
- *仅适用于常规接口。*

# 硬件scale filter

BM168x系列硬件scale filter用于将输入的图像进行"缩放/裁剪/补边"操作。譬如，转码应用。在将1080p的视频解码后，使用硬件scale缩放成720p的，再进行压缩输出。

| 内容 | 最大分辨率 | 最小分辨率 | 放大倍数 |
|------|------------|------------|----------|
| 硬件限制 | 4096 * 4096 | 8*8 | 32 |

在FFMPEG中，硬件scale filter的名称为*scale_bm*。

```
ffmpeg -filters | grep bm
```

## 硬件scale filter支持的选项

FFMPEG中，可以通过如下命令，来查看scaler_bm编码器支持的选项

```
ffmpeg -h filter=scale_bm
```

scale_bm选项的说明如下:

**w**:

- 缩放输出视频的宽度。请参考ffmpeg scale filter的用法。

**h**:

- 缩放输出视频的高度。请参考ffmpeg scale filter的用法。

**format**:

- 缩放输出视频的像素格式。请参考ffmpeg scale filter的用法。
- 输入输出支持的格式详见附表7.1。
- 缺省值"none"。即输出像素格式为系统自动。输入为yuv420p，输出为yuv420p; 输入为yuvj420p，输出为yuvj420p。输入为nv12时，缺省输出为yuv420p。
- 在HWAccel框架下：支持nv12到yuv420p、nv12到yuvj420p、yuv420p到yuvj420p、yuvj422p到yuvj420p、yuvj422p到yuv420p的格式转换。在不启用HWAccel框架的正常模式下支持情况见附表7.1。

| 输入 | 输出 | 是否持缩放 | 是否支持颜色转换 |
|------|------|------------|------------------|
| GRAY8 | GRAY8 | 是 | 是 |
| NV12（压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| NV12（非压缩） | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV420P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV422P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 否 |
|  | YUV444P | 否 | 否 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| YUV444P | YUV420P | 是 | 是 |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| BGR、RGB | YUV420P | 是 |  |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |
| RGBP、BGRP | YUV420P | 是 |  |
|  | YUV422P | 否 | 是 |
|  | YUV444P | 是 | 是 |
|  | BGR | 是 | 是 |
|  | RGB | 是 | 是 |
|  | RGBP | 是 | 是 |
|  | BGRP | 是 | 是 |

表7.1 scale_bm像素格式支持列表

**opt**:

- 缩放操作 (from 0 to 2) (default 0)
- 值0 - 仅支持缩放操作。缺省值。
- 值1 - 支持缩放+自动裁剪操作。命令行参数中可用crop来表示。
- 值2 - 支持缩放+自动补黑边操作。命令行参数中可用pad来表示。

**flags**:

- 缩放方法 (from 0 to 2) (default 1)
- 值0 - nearest滤波器。命令行参数中，可用nearest来表示。
- 值1 - bilinear滤波器。命令行参数中，可用bilinear来表示。
- 值2 - bicubic滤波器。命令行参数中，可用bicubic来表示。

**sophon_idx**:

- 设备ID，从0开始。

**zero_copy**:

- 值0 - 表示scale_bm的输出AVFrame将同时包含设备内存和主机内存指针，兼容性最好，性能稍有下降。缺省为0
- 值1 - 表示scale_bm的输出到下一级的AVFrame中将只包含有效设备地址，不会对数据进行从设备内存到系统内存的同步。建议对于下一级接使用SOPHGO的编码/filter的情况，可以选择设置为1，其他建议设置为0。
- 缺省为0

# AVFrame特殊定义说明

遵从FFMPEG的规范，硬件解码器是通过AVFrame来提供输出的，硬件编码器是通过AVFrame来提供输入的。因此，在通过API方式，调用FFMPEG SDK、进行硬件编解码处理时，需要注意到AVFrame的如下特殊规定。AVFrame是线性YUV输出。在AVFrame中，data为数据指针，用于保存物理地址，linesize为每个平面的线跨度。

## 硬件解码器输出的avframe接口定义

### 常规接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | cbcr_interleave=1 时CbCr的虚拟地址; cbcr_interleave=0 时Cb的虚拟地址 |
| 2 | cbcr_interleave=0 时Cr的虚拟地址 |
| 3 | 未使用 |
| 4 | Y的物理地址 |
| 5 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 |
| 6 | cbcr_interleave=0 时Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | cbcr_interleave=1时CbCr的虚拟地址的跨度；cbcr_interleave=0时Cb的虚拟地址的跨度 |
| 2 | cbcr_interleave=0时Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_interleave=0时Cb的物理地址的跨度 |
| 6 | cbcr_interleave=0时Cr的物理地址的跨度 |
| 7 | 未使用 |

### HWAccel接口

**data数组的定义**

| 下标 | 未压缩格式说明 | 压缩格式明 |
|------|----------------|------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | cbcr_interleave=1 时CbCr的物理地址; cbcr_interleave=0 时Cb的物理地址 | 压缩的色度数据的物理地址 |
| 2 | cbcr_interleave=0 时Cr的物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

**linesize数组的定义**

| 下标 | 未压缩格式说明 | 压缩格式说明 |
|------|----------------|--------------|
| 0 | Y的物理地址的跨度 | 亮度数据的跨度 |
| 1 | cbcr_interleave=1时CbCr的物理地址的跨度；cbcr_int erleave=0时Cb的物理地址的跨度 | 色度数据的跨度 |
| 2 | cbcr_interleave=0时Cr的物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 偏移量表的大小 |

## 硬件编码码器输入的avframe接口定义

### 常规接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

### HWAccel接口

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的物理地址 |
| 1 | Cb的物理地址 |
| 2 | Cr的物理地址 |
| 3 | 保留 |
| 4 | 保留 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的物理地址的跨度 |
| 1 | Cb的物理地址的跨度 |
| 2 | Cr的物理地址的跨度 |
| 3 | 未使用 |

## 硬件filter输入输出的AVFrame接口定义

1.在不启用HWAccel加速功能时，AVFrame接口定义采用常规接口的内存布局。

**data数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址 |
| 1 | Cb的虚拟地址 |
| 2 | Cr的虚拟地址 |
| 3 | 保留 |
| 4 | Y的物理地址 |
| 5 | Cb的物理地址 |
| 6 | Cr的物理地址 |
| 7 | 未使用 |

**linesize数组的定义**

| 下标 | 说明 |
|------|------|
| 0 | Y的虚拟地址的跨度 |
| 1 | Cb的虚拟地址的跨度 |
| 2 | Cr的虚拟地址的跨度 |
| 3 | 未使用 |
| 4 | Y的物理地址的跨度 |
| 5 | Cb的物理地址的跨度 |
| 6 | Cr的物理地址的跨度 |
| 7 | 未使用 |

2.HWAccel接口下AVFrame接口定义

**data数组的定义**

| 下标 | 说明 | 压缩格式的输入接口 |
|------|------|---------------------|
| 0 | Y的物理地址 | 压缩的亮度数据的物理地址 |
| 1 | Cb物理地址 | 压缩的色度数据的物理地址 |
| 2 | Cr物理地址 | 亮度数据的偏移量表的物理地址 |
| 3 | 保留 | 色度数据的偏移量表的物理地址 |
| 4 | 保留 | 保留 |

**linesize数组的定义**

| 下标 | 说明 | 缩格式的输入接口 |
|------|------|-------------------|
| 0 | Y物理地址的跨度 | 亮度数据的跨度 |
| 1 | Cb物理地址的跨度 | 色度数据的跨度 |
| 2 | Cr物理地址的跨度 | 亮度偏移量表的大小 |
| 3 | 未使用 | 色度偏移量表的大小 |

# 硬件加速在FFMPEG命令中的应用示例

下面同时给出常规模式和HWAccel模式对应的FFMPEG命令行参数。

为便于理解，这里汇总说明：

- 常规模式下，bm解码器的输出内存是否同步到系统内存上，用zero_copy控制，默认为1。
- 常规模式下，bm编码器的输入内存在系统内容还是设备内存上，用is_dma_buffer控制，默认值为1。
- 常规模式下，bm滤波器会自动判断输入内存的同步，输出内存是否同步到系统内存，用zero_copy控制，默认值为0。
- HWAccel模式下，设备内存和系统内存的同步用hwupload和hwdownload来控制。
- 常规模式下，用sophon_idx来指定设备，默认为0；HWAccel模式下用hwaccel_device来指定。

## 示例 1

使用设备0。解码H.265视频，输出compressed frame buffer，scale_bm解压缩compressed frame buffer并缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:zero_copy=1" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale.264
```

## 示例 2

使用设备0。解码H.265视频，按比例缩放并自动裁剪成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=crop:zero_copy=1" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_crop.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=crop" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_crop.264
```

## 示例 3

使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:zero_copy=1" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_pad.264
```

## 示例 4

演示视频截图功能。使用设备0。解码H.265视频，按比例缩放并自动补黑边成CIF，然后编码成jpeg图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:format=yuvj420p:zero_copy=1" -c:v jpeg_bm -vframes 1 -y wkc_100_cif_scale.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:format=yuvj420p" -c:v jpeg_bm -vframes 1 -y wkc_100_cif_scale.jpeg
```

## 示例 5

演示视频转码+视频截图功能。使用设备0。硬件解码H.265视频，缩放成CIF，然后编码成H.264码流；同时缩放成720p，然后编码成JPEG图片。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -filter_complex "[0:v]scale_bm=352:288:zero_copy=1[img1];[0:v]scale_bm=1280:720:format= yuvj420p:zero_copy=1[img2]" -map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 -map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -filter_complex "[0:v]scale_bm=352:288[img1];[0:v]scale_bm=1280:720:format=yuvj420p[img2]" -map '[img1]' -c:v h264_bm -b:v 256K -y img1.264 -map '[img2]' -c:v jpeg_bm -vframes 1 -y img2.jpeg
```

## 示例6

演示hwdownload功能。硬件解码H.265视频，然后下载存储成YUV文件。

Filter hwdownload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过codec中指定zero_copy选项来实现，因此不需要hwdownload滤波器。

常规模式：

```
ffmpeg -c:v hevc_bm -cbcr_interleave 0 -zero_copy 0 -i src/wkc_100.265 -y test_transfer.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -cbcr_interleave 0 -i src/wkc_100.265 -vf "hwdownload,format=yuv420p|bmcodec" -y test_transfer.yuv
```

## 示例7

演示hwdownload功能。硬件解码H.265视频，缩放成CIF格式，然后下载存储成YUV文件。

在常规模式中， scale_bm会自动根据filter的链条判定是否同步内存，因此不需要hwdownload。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288,format=yuv420p" -y test_transfer_cif.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288,hwdownload,format=yuv420p|bmcodec" -y test_transfer_cif.yuv
```

## 示例8

演示hwupload功能。使用设备0。上传YUV视频，然后编码H.264视频。

Filter hwupload专门为HWAccel接口服务，用于设备内存和系统内存的同步。在常规模式中，这步可以通过编码器中指定is_dma_buffer选项来实现，因此不需要hwupload滤波器。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuv420p -i test_transfer.yuv -c:v h264_bm -b:v 3M -is_dma_buffer 0 -y test_transfer.264
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:0 -s 1920x1080 -i test_transfer.yuv -filter_hw_device foo -vf "format=yuv420p|bmcodec,hwupload" -c:v h264_bm -b:v 3M -y test_transfer.264
```

这里foo为设备0的别名。

## 示例9

演示hwupload功能。使用设备1。上传YUV视频，并缩放成CIF，然后编码H.264视频。

常规模式：

```
ffmpeg -s 1920x1080 -i test_transfer.yuv -vf "scale_bm=352:288:sophon_idx=1:zero_copy=1" -c:v h264_bm -b:v 256K -sophon_idx 1 -y test_transfer_cif.264
```

说明：1）这里不指定-pix_fmt yuv420p是因为默认输入为yuv420p格式

2）常规模式下,bm_scale filter, decoder，encoder通过参数sophon_idx来指定使用哪个设备

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 -s 1920x1080 -i test_transfer.yuv -filter_hw_device foo -vf "format=yuv420p|bmcodec,hwupload,scale_bm=352:288" -c:v h264_bm -b:v 256K -y test_transfer_cif.264
```

说明：这里foo为设备1的别名，HWAccel模式下通过init_hw_device来指定使用具体的硬件设备。

## 示例10

演示hwdownload功能。硬件解码YUVJ444P的JPEG视频，然后下载存储成YUV文件。

常规模式：

```
ffmpeg -c:v jpeg_bm -zero_copy 0 -i src/car/1920x1080_yuvj444.jpg -y car_1080p_yuvj444_dec.yuv
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v jpeg_bm -i src/car/1920x1080_yuvj444.jpg -vf "hwdownload,format=yuvj444p|bmcodec" -y car_1080p_yuvj444_dec.yuv
```

## 示例11

演示hwupload功能。使用设备1。上传YUVJ444P图像数据，然后编码JPEG图片。

常规模式：

```
ffmpeg -s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv -c:v jpeg_bm -sophon_idx 1 -is_dma_buffer 0 -y car_1080p_yuvj444_enc.jpg
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:1 -s 1920x1080 -pix_fmt yuvj444p -i car_1080p_yuvj444.yuv -filter_hw_device foo -vf 'format=yuvj444p|bmcodec,hwupload' -c:v jpeg_bm -y car_1080p_yuvj444_enc.jpg
```

这里foo为设备1的别名。

## 示例12

演示软解码和硬编码混合使用的方法。使用设备2。使用ffmpeg自带的*h264*软解码器，解码H.264视频，上传解码后数据到处理器2，然后编码H.265视频。

常规模式：

```
ffmpeg -c:v h264 -i src/1920_18MG.mp4 -c:v h265_bm -is_dma_buffer 0 -sophon_idx 2 -g 256 -b:v 5M -y test265.mp4
```

HWAccel模式：

```
ffmpeg -init_hw_device bmcodec=foo:2 -c:v h264 -i src/1920_18MG.mp4 -filter_hw_device foo -vf 'format=yuv420p|bmcodec,hwupload' -c:v h265_bm -g 256 -b:v 5M -y test265.mp4
```

这里foo为设备2的别名。

## 示例13

演示使用enc-params设置视频编码器的方法。使用设备0。解码H.265视频，缩放成CIF，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:zero_copy=1" -c:v h264_bm -g 50 -b:v 32K -enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" -y wkc_100_cif_scale_ipp_32Kbps.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288" -c:v h264_bm -g 50 -b:v 32K -enc-params "gop_preset=2:mb_rc=1:delta_qp=3:min_qp=20:max_qp=40" -y wkc_100_cif_scale_ipp_32Kbps.264
```

## 示例14

使用设备0。解码H.265视频，使用bilinear滤波器，按比例缩放成CIF，并自动补黑边，然后编码成H.264码流。

常规模式：

```
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:flags=bilinear:zero_copy=1" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_pad.264
```

HWAccel模式：

```
ffmpeg -hwaccel bmcodec -hwaccel_device 0 -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=352:288:opt=pad:flags=bilinear" -c:v h264_bm -g 256 -b:v 256K -y wkc_100_cif_scale_pad.264
```

## 通过调用API方式来使用硬件加速功能

examples/multimedia/ff_bmcv_transcode/例子演示了使用ffmpeg做编解码，用bmcv做图像处理的整个流程。

examples/multimedia/ff_video_decode/例子演示了使用ffmpeg做解码的流程。

examples/multimedia/ff_video_encode/例子演示了使用ffmpeg做编码的流程。

## 硬件编码支持roi编码

参考examples/multimedia/ff_video_encode/例子。设置roi_enable既可启用roi编码。

Roi编码数据通过av_frame side data传递。

Roi数据结构定义为

**字段说明:**

- QP Map

H264下QP以宏块16x16为单位给出。HEVC下QP以sub-ctu（32x32）为单位给出。QP对应的就是video编码中的Qstep，取值范围为0-51.

- Lamda Map

lamda是用来控制和调节IP内部的RC计算公式

cost = distortion + lamda * rate

这个调节参数仅在HEVC下有效，允许以32x32 sub-CTU模块为单位控制。

- Mode Map

这个参数用来指定模式选择。 0 – 不适用 1 – skip mode 2- intra mode。H264下以宏块16x16为单位控制，HEVC下以CTU 64x64为单位控制。

- Zero-cut Flag

仅在HEVC下有效。将当前CTU 64x64残差系数全部置为0，从而节省出更多的比特给其他更重要的部分。

# SOPHGO BMAPI使用指南

## 简介

无。

## bm_video Decode 数据结构

- BmVpuDecStreamFormat
- BmVpuDecSkipMode
- BmVpuDecDMABuffer
- BmVpuDecOutputMapType
- BmVpuDecBitStreamMode
- BmVpuDecPixFormat
- BMVidDecParam
- BMDecStatus
- BMDecOutputMapType
- BMVidStream
- BMVidFrame
- BMVidStreamInfo
- BmVpuDecPicType

### BmVpuDecStreamFormat

设置输入码流的格式。

- BMDEC_AVC 表示输入码流满足 AVC 编码标准。
- BMDEC_HEVC 表示输入码流满足 HEVC 编码标准。

### BmVpuDecSkipMode

设置跳帧模式。

| 成员变量 | 描述 |
|---------|------|
| BMDEC_FRAME_SKIP_MODE | 不开启跳帧模式 |
| BMDEC_SKIP_NON_REF_NON_I | 开启跳帧模式，跳过除参考帧和I帧外的视频帧 |
| BMDEC_SKIP_NON_I | 开启跳帧模式，跳过除I帧外的视频帧 |

### BmVpuDecDMABuffer

保存 VPU 缓冲区的信息。

| 成员变量 | 描述 |
|---------|------|
| size | 缓冲区的大小 |
| phys_addr | 缓冲区的物理地址 |
| virt_addr | 缓冲区的虚拟地址 |

### BmVpuDecOutputMapType

设置输出数据的类型。

- BMDEC_OUTPUT_UNMAP 输出 yuv 数据。
- BMDEC_OUTPUT_COMPRESSED 输出压缩模式数据。

### BmVpuDecBitStreamMode

设置 VPU 解码方式。

- BMDEC_BS_MODE_INTERRUPT 采用流模式解码，当输入缓冲区填满后送入解码器。
- BMDEC_BS_MODE_PIC_END 采用帧模式解码，获取到一帧数据就送入解码器。

### BmVpuDecPixFormat

设置输出数据的格式。

| 成员变量 | 描述 |
|---------|------|
| BM_VPU_DEC_PIX_FORMAT_YUV420P | 输出 YUV420P 数据 |
| BM_VPU_DEC_PIX_FORMAT_YUV422P | 输出 YUV422P 数据，BM1684 不支持 |
| BM_VPU_DEC_PIX_FORMAT_YUV444P | 输出 YUV444P 数据，BM1684 不支持 |
| BM_VPU_DEC_PIX_FORMAT_YUV400 | 输出 YUV400 数据，BM1684 不支持 |
| BM_VPU_DEC_PIX_FORMAT_NV12 | 输出 NV12 数据 |
| BM_VPU_DEC_PIX_FORMAT_NV21 | 输出 NV21 数据 |
| BM_VPU_DEC_PIX_FORMAT_NV16 | 输出 NV16 数据，BM1684 不支持 |
| BM_VPU_DEC_PIX_FORMAT_NV24 | 输出 NV24 数据，BM1684 不支持 |
| BM_VPU_DEC_PIX_FORMAT_COMPRESSED | 输出压缩格式数据 |
| BM_VPU_DEC_PIX_FORMAT_COMPRESSED_10BITS | 输出10bits压缩格式数据，BM1684 不支持 |

# BMVidDecRetStatus

解码器接口返回的错误码类型。

| 成员变量 | 描述 |
|---------|------|
| BM_ERR_VDEC_INVALID_CHNID | 无效的解码channel id |
| BM_ERR_VDEC_ILLEGAL_PARAM | 非法参数 |
| BM_ERR_VDEC_EXIST | 解码channel已存在 |
| BM_ERR_VDEC_UNEXIST | 解码channel不存在 |
| BM_ERR_VDEC_NULL_PTR | 空指针 |
| BM_ERR_VDEC_NOT_CONFIG | 解码器未配置 |
| BM_ERR_VDEC_NOT_SUPPORT | 不支持的解码业务 |
| BM_ERR_VDEC_NOT_PERM | 参数异常 |
| BM_ERR_VDEC_INVALID_PIPEID | 非法的PIPEID |
| BM_ERR_VDEC_INVALID_GRPID | 非法的GRPID |
| BM_ERR_VDEC_NOMEM | 存储空间异常 |
| BM_ERR_VDEC_NOBUF | 缓冲区异常 |
| BM_ERR_VDEC_BUF_EMPTY | 缓冲区空 |
| BM_ERR_VDEC_BUF_FULL | 缓冲区满 |
| BM_ERR_VDEC_SYS_NOTREADY | 解码器未准备就绪 |
| BM_ERR_VDEC_BADADDR | 错误地址 |
| BM_ERR_VDEC_BUSY | 解码器忙 |
| BM_ERR_VDEC_SIZE_NOT_ENOUGH | 空间不足 |
| BM_ERR_VDEC_INVALID_VB | 无效的VB |
| BM_ERR_VDEC_ERR_INIT | 解码器初始化错误 |
| BM_ERR_VDEC_ERR_INVALID_RET | 无效返回值 |
| BM_ERR_VDEC_ERR_SEQ_OPER | 队列处理异常 |
| BM_ERR_VDEC_ERR_VDEC_MUTEX | 信号量异常 |
| BM_ERR_VDEC_ERR_SEND_FAILED | 发送失败 |
| BM_ERR_VDEC_ERR_GET_FAILED | 获取失败 |
| BM_ERR_VDEC_ERR_HUNG | 解码器挂起 |

# BMVidDecParam

BMVidDecParam 用于设置解码器的初始化参数，在调用接口 bmvpu_dec_create 前需要创建 BMVidDecParam 对象，并对其进行初始化。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| streamFormat | BmVpuDecStreamFormat | 设置输入码流类型，BMDEC_AVC 为 H.264(AVC)，BMDEC_HEVC 为 H.265(HEVC) |
| wtlFormat | BmVpuDecOutputMapType | 设置输出数据格式 |
| skip_mode | BmVpuDecSkipMode | 设置跳帧模式 |
| bsMode | BmVpuDecBitStreamMode | 设置解码器工作方式。0 以 INTERRPUT 模式工作；2 以 PIC_END 模式工作 |
| enableCrop | int | 是否启用裁剪选项，此参数无效 |
| pixel_format | BmVpuDecPixFormat | 输出图像格式 |
| secondaryAXI | int | 是否开启 secondary AXI。SDK 中会根据码流类型，自动选择，不需要手动开启 |
| mp4class | int | MPEG_4，此参数无效 |
| frameDelay | int | 帧延迟输出，大于0时，在解码frameDelay帧后输出显示帧，此参数无效 |
| pcie_board_id | int | PCIE板卡的设备id |
| pcie_no_copyback | int | pcie模式，解码输出数据不拷贝回host端 |
| enable_cache | int | 启用缓存，提高内存拷贝速度，但会增加算力、带宽等的消耗 |
| perf | int | 性能监测功能 |
| core_idx | int | 解码核选择。1684x core_idx 可以配置为 0，1，-1；配置为-1时，会根据解码器负载自动选择解码核 |
| timeout | int | 解码超时时间，默认为3000ms（即VPU_WAIT_TIME_OUT） |
| timeout_count | int | 解码超时重试次数，默认为5 |
| extraFrameBufferNum | int | 除去vpu所必要的Frame Buffer 外，用户额外需要的 Frame Buffer 的数量 |
| min_framebuf_cnt | int | 输入码流所需要的最小的 Frame Buffer 的数量 |
| framebuf_delay | int | 解码延迟出帧所需要的 Frame Buffer 的数量 |
| streamBufferSize | int | 设置输入码流的缓冲区大小。若设置为 0，则默认缓冲区大小为 0x700000 |
| bitstream_buffer | BmVpuDecDMABuffer | 输入码流缓冲区信息 |
| frame_buffer | BmVpuDecDMABuffer | Frame Buffer 信息 |
| Ytable_buffer | BmVpuDecDMABuffer | 压缩模式 Y table 缓冲区信息 |
| Ctable_buffer | BmVpuDecDMABuffer | 压缩模式 C table 缓冲区信息 |

备注：

* 解码器支持用户自行分配Bitstream Buffer和Frame Buffer。当外部分配内存时，extraFrameBufferNum、min_framebuf_cnt、framebuf_delay、streamBufferSize、bitstream_buffer、frame_buffer、Ytable_buffer、Ctable_buffer必须配置。
* Frame Buffer的计算参考（Frame Buffer 计算方法）。

# BMDecStatus

枚举类型，用于指示解码器的状态。

| 状态 | 含义 |
|------|------|
| BMDEC_UNCREATE | 解码器未创建(用户无需处理) |
| BMDEC_UNLOADING | 解码器未加载(用户无需处理) |
| BMDEC_UNINIT | 解码器未初始化 |
| BMDEC_WRONG_RESOLUTION | 设置的分辨率不匹配 |
| BMDEC_FRAMEBUFFER_NOTENOUGH | 分配的 Frame Buffer 不足 |
| BMDEC_DECODING | 解码器正在解码 |
| BMDEC_ENDOF | 解码器送帧结束 |
| BMDEC_STOP | 解码器停止解码 |
| BMDEC_HUNG | 解码器⽆响应 |
| BMDEC_CLOSE | 关闭解码器，表示可以开始关闭解码器 |
| BMDEC_CLOSED | 解码器关闭状态 |

# BMDecOutputMapType

枚举类型，用于定义编码器输出的YUV格式。

| 状态 | 含义 |
|------|------|
| BMDEC_OUTPUT_UNMAP | 原始YUV数据 |
| BMDEC_OUTPUT_TILED | TILED YUV数据(已弃用) |
| BMDEC_OUTPUT_COMPRESSED | 压缩格式YUV数据 |

# BMVidStream

保用于表示视频流的实际数据，包括像素值、时间戳等。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| buf | unsigned char* | 码流信息存储地址 |
| length | unsigned int | 码流信息大小 |
| header_buf | unsigned char* | 码流头信息存储地址 |
| header_size | unsigned int | 码流头信息大小 |
| extradata | unsigned char* | 已弃用：不再接受 extradata 数据 |
| extradata_size | unsigned int | 已弃用：不再接受 extradata 数据 |
| pts | unsigned long | 显示时间戳 |
| dts | unsigned long | 解码时间戳 |

# BMVidFrame

保存解码器输出的视频帧信息。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| picType | BmVpuDecPicType | 图片类型 |
| buf[8] | unsigned char* | 存放输出数据的地址。前四个通道存储YUV的虚拟地址，后四通道存储YUV的物理地址。0：Y虚拟地址，1：Cb虚拟地址，2：Cr虚拟地址。4：Y物理地址，5：Cb物理地址，6：Cr物理地址。3和7为特殊格式数据的存储通道（如存放透明度数据） |
| stride[8] | int | 和 buf 对应，存放对应通道的步长。对于 FBC 数据，stride 存放的数据稍有不同。channel 0 和 4，存放 Y 分量的宽度；channel 1 和 5，存放 Cb 分量的宽度；channel 2 和 6，存放 Y table 的长度；channel 3 和 7，存放 Cb table 的长度 |
| width | unsigned int | 存放 Frame 的宽度 |
| height | unsigned int | 存放 Frame 的高度 |
| frameFormat | int | 输出 yuv的格式。frameFormat为0 ：输出为yuv，需要和cbcrinterleve 结合使用。frameFormat为0，cbcrInterleave为 0 输出:yuv420p。frameFormat为0 cbcrInterleave为1 输出:nv12。frameFormat为116：压缩数据需要调用vpp解压缩 |
| interlacedFrame | BmVpuDecLaceFrame | 图像扫描方式。0 为逐行扫描模式，1为隔行扫描模式 |
| lumaBitDepth | int | 亮度数据的深度 |
| chromaBitDepth | int | 色度数据的深度 |
| pixel_format | BmVpuDecPixFormat | 图像格式 |
| endian | int | 表示帧缓冲区的段序。endian=0，以小端模式存储；endian=1，以大端模式存储；endian=2，以 32 位小端模式存储；endian=3，以 32 位大端模式存储 |
| sequenceNo | int | 表示码流序列的状态。当码流序列改变时，sequenceNo 的值会进行累加 |
| frameIdx | int | 图像帧缓冲区的索引。用于表示该帧缓冲区在解码器中位置 |
| pts | unsigned long | 显示时间戳戳 |
| dst | unsigned long | 解码时间戳戳 |
| size | int | 帧缓冲区的大小 |
| colorPrimaries | int | 指定视频使用的色彩原色标准，影响颜色再现方式 |
| colorTransferCharacteristic | int | 定义了颜色从原色到可显示色彩的转换特性或曲线 |
| colorSpace | int | 表明视频色彩的编码空间，如RGB、YCbCr等 |
| colorRange | int | 指明色彩的动态范围，如广色域或有限色域（全范围或限定范围） |
| chromaLocation | int | 定义色度样本相对于亮度样本的位置 |
| coded_width | unsigned int | 用于编码的图片宽度 |
| coded_height | unsigned int | 用于编码的图片高度 |

# BMVidStreamInfo

用于描述视频流的基本信息，例如图像大小、帧率、编码标准等。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| picWidth | int | 图片的水平像素大小 |
| picHeight | int | 图片的垂直像素大小 |
| fRateNumerator | int | 帧率分数的分子 |
| fRateDenominator | int | 帧率分数的分母 |
| picCropRect | CropRect | 图片裁剪矩形信息（仅适用于H.264/HEVC解码器） |
| mp4DataPartitionEnable | int | MPEG4 VOL头中的 data_partitioned 标志位 |
| mp4ReversibleVlcEnable | int | MPEG4 VOL头中的 reversible_vlc 标志位 |
| mp4ShortVideoHeader | int | 0：非H.263流。1：H.263流（mpeg4 short video header） |
| h263AnnexJEnable | int | 0：禁用Annex J，1：启用Annex J（可选的解块滤波器模式） |
| minFrameBufferCount | int | 解码所需的最小帧缓冲区数量 |
| frameBufDelay | int | 最大显示帧缓冲区延迟 |
| normalSliceSize | int | 正常情况下保存切片的推荐缓冲区大小（仅适用于H.264） |
| worstSliceSize | int | 最坏情况下保存切片的推荐缓冲区大小（仅适用于H.264） |
| maxSubLayers | int | H.265/HEVC的子层数量 |
| profile | int | 不同视频编码标准的配置文件信息 |
| level | int | 不同视频编码标准的级别信息 |
| tier | int | 层次指示器（0：主层，1：高层） |
| interlace | int | Indication of interlaced or progressive frame |
| constraint_set_flag | int[4] | H.264/AVC SPS中的 constraint_set0_flag 至 constraint_set3_flag。指定了视频编码的一些约束集，每个元素对应一个约束集的标志 |
| direct8x8Flag | int | 标志指定了解码器在进行运动估计时是否使用直接模式进行 8x8 推导。1表示启用了直接模式;0表示禁用 |
| vc1Psf | int | VC1序列层中的渐进分段帧（PSF）标志 |
| isExtSAR | int | H.264中的SAR（Sample Aspect Ratio,样本宽高比）扩展标志 |
| maxNumRefFrmFlag | int | H.264 中的 max_num_ref_frames 的标志位。0表示 max_num_ref_frames 为 0；1表示 max_num_ref_frames 不为 0 |
| maxNumRefFrm | int | H.264 中的 max_num_ref_frames 的具体数值，仅在maxNumRefFrmFlag==1时有效 |
| aspectRateInfo | int | 图像的宽高比信息 |
| bitRate | int | 码流写入时的比特率 |
| mp2LowDelay | int | MPEG2规范中sequence extension的low_delay语法 |
| mp2DispVerSize | int | MPEG2规范中sequence display extension的display_vertical_size语法 |
| mp2DispHorSize | int | MPEG2规范中sequence display extension的display_horizontal_size语法 |
| userDataHeader | Uint32 | 用户数据头 |
| userDataNum | Uint32 | 用户数据的数量 |
| userDataSize | Uint32 | 用户数据的大小 |
| userDataBufFull | Uint32 | 当 userDataEnable 启用时，解码器将帧缓冲区状态报告到 userDataBufAddr 和以字节为单位的 userDataSize 中。当用户数据报告模式为1且用户数据大小大于用户数据缓冲区大小时，VPU将报告与缓冲区大小一样多的用户数据，跳过剩余部分并设置 serDataBufFull |
| chromaFormatIDC | int | 色度格式指示器 |
| lumaBitdepth | int | 亮度样本的位深度 |
| chromaBitdepth | int | 色度样本的位深度 |
| seqInitErrReason | int | 序列头解码错误原因 |
| warnInfo | int | 警告信息 |
| sequenceNo | unsigned int | 序列信息的序号，增加1表示检测到序列变化 |

# BmVpuDecPicType

枚举类型，表示图片类型。

- 0 表示I帧
- 1 表示P帧
- 2 表示B帧
- 5表示IDR帧

# bm_video Decode API说明

- bmvpu_dec_create
- bmvpu_dec_get_status
- bmvpu_dec_decode
- bmvpu_dec_get_caps
- bmvpu_dec_get_output
- bmvpu_dec_clear_output
- bmvpu_dec_flush
- bmvpu_dec_delete
- bmvpu_dec_get_stream_buffer_empty_size
- bmvpu_dec_get_all_frame_in_buffer
- bmvpu_dec_get_empty_input_buf_cnt
- bmvpu_dec_get_pkt_in_buf_count
- bmvpu_dec_vpu_reset
- bmvpu_dec_get_core_idx
- bmvpu_dec_dump_stream
- bmvpu_get_inst_idx
- bmvpu_dec_get_stream_info
- bmvpu_dec_set_logging_threshold

## bmvpu_dec_create

**功能和说明**

- 用于创建视频解码器的实例，返回创建的视频解码器实例句柄。
- 初始化一些变量和数据结构，申请解码器实例所需要的内存。将创建的解码器实例的句柄返回给用户，用户通过句柄来操作解码器。

**函数名**

`BMVidDecRetStatus bmvpu_dec_create(BMVidCodHandle* pVidCodHandle, BMVidDecParam decParam)`

**参数说明**

- `BMVidCodHandle *pVidCodHandle` 存储创建的视频解码器实例的句柄。
- `BMVidDecParam decParam` 视频解码器的配置参数。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_get_status

**功能和说明**

- 获取当前视频解码器的状态。
- 该函数接受一个视频编码器句柄 BMVidCodHandle，并返回该句柄对应视频解码器的状态 BMDecStatus。
- 如果句柄有效，函数返回解码器的当前状态；否则，返回 BMDEC_CLOSED 表示句柄错误。

**函数名**

`BMDecStatus bmvpu_dec_get_status(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle`：视频编码器句柄。

**返回值**

- 解码器的状态。

## bmvpu_dec_decode

**功能和说明**

- 解码视频流并将解码后的帧放入输出队列。
- 该函数接受一个视频编码器句柄 BMVidCodHandle 和一个包含视频流信息的结构体 BMVidStream。
- 函数首先检查输入参数的有效性，包括输入队列是否已满、解码器是否处于正确状态等。
- 若满足调用条件，函数将视频流数据填充到环形缓冲区，并触发解码器开始解码。

**函数名**

`BMVidDecRetStatus bmvpu_dec_decode(BMVidCodHandle vidCodHandle, BMVidStream vidStream)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编码器句柄。
- `BMVidStream vidStream` 包含视频流信息的结构体，包括帧数据、长度、时间戳等。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_get_caps

**功能和说明**

- 获取视频编码器和码流的相关信息。
- 该函数接受一个视频编码器句柄 BMVidCodHandle 和一个用于存储信息的结构体指针 BMVidStreamInfo。
- 若满足调用条件，函数从视频编码器实例中提取初始信息，填充到给定的 BMVidStreamInfo 结构体中。

**函数名**

`BMVidDecRetStatus bmvpu_dec_get_caps(BMVidCodHandle vidCodHandle, BMVidStreamInfo* streamInfo)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编码器句柄。
- `BMVidStreamInfo* streamInfo` 用于存储视频解码器信息的结构体指针。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_get_output

**功能和说明**

- 从视频解码器获取输出帧信息。
- 该函数接受一个视频编码器句柄 BMVidCodHandle，并返回一个指向 BMVidFrame 结构的指针，该结构包含解码器输出的帧信息。

**函数名**

`BMVidDecRetStatus bmvpu_dec_get_output(BMVidCodHandle vidCodHandle, BMVidFrame* frame)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编码器句柄。

**返回值**

- 如果成功获取输出帧信息，则返回指向 BMVidFrame 结构的指针，其中包含帧的详细信息。
- 如果未成功获取输出帧信息，返回 NULL。
- 此函数的返回值可能为 NULL，因此在使用返回值前建议进行有效性检查。

## bmvpu_dec_clear_output

**功能和说明**

释放指定的视频帧所占用的缓冲区资源，供后续输出视频帧使用。

**函数名**

`BMVidDecRetStatus bmvpu_dec_clear_output(BMVidCodHandle vidCodHandle, BMVidFrame* frame)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器的句柄，用于标识特定的视频解码器实例。
- `BMVidFrame *frame` 要清除的输出帧。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_flush

**功能和说明**

- 刷新（Flush）视频解码器输出缓冲区。
- 该函数用于刷新视频解码器，应在关闭解码器之前调用，确保获取到所有的解码输出数据。
- 解码器解码通常会存在延迟出帧的情况，当输入数据全部送入解码器后，并不能得到所有输出数据。需要调用 bmvpu_dec_flush 告诉解码器当前输入文件已经结束，刷新解码器中的数据，并更新解码器状态。
- 如果不调用 bmvpu_dec_flush，可能会存在丢帧问题。

**函数名**

`BMVidDecRetStatus bmvpu_dec_flush(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器的句柄，用于标识特定的视频解码器实例。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_delete

**功能和说明**

调用 bmvpu_dec_delete 用于关闭解码器实例，并释放资源。

**函数名**

`BMVidDecRetStatus bmvpu_dec_delete(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器的句柄，用于标识特定的视频解码器实例。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_get_stream_buffer_empty_size

**功能和说明**

- 获取视频解码器的比特流缓冲的可用空间大小。
- INTERRUPT MODE: 返回比特流缓冲区的剩余空间大小。
- PIC_END MODE：返回比特流缓冲区当前能够存储的压缩帧数据的最大容量。该容量并不一定等于比特流缓冲区的剩余空间大小。
- 返回比特流缓冲的可用空间大小或错误码。

**函数名**

`int bmvpu_dec_get_stream_buffer_empty_size(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器实例的句柄。

**返回值**

- 返回值为比特流缓冲的剩余空间大小，如果出现错误，返回对应错误码。

## bmvpu_dec_get_all_frame_in_buffer

**功能和说明**

- 刷新视频解码器输出缓冲区。
- 通过句柄获取解码器实例相关信息。
- 作用和 bmvpu_dec_flush 一样，用于刷新解码器中剩余的帧数据。

**函数名**

`int bmvpu_dec_get_all_frame_in_buffer(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器实例的句柄。

**返回值**

- 返回值为0表示成功通知视频解码器获取所有剩余帧并放入缓冲区。

## bmvpu_dec_get_empty_input_buf_cnt

**功能和说明**

- 该函数用于获取视频解码器当前空闲输入缓冲区的数量。
- 通过句柄获取解码器实例相关信息。
- 检查vidHandle是否为空或者解码器状态是否已关闭。如果是，返回0表示没有空闲输入缓冲区。
- 返回计算得到的空闲输入缓冲区的数量。
- 函数返回表示空闲输入缓冲区数量的整数值。

**函数名**

`int bmvpu_dec_get_empty_input_buf_cnt(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器实例的句柄。

**返回值**

- 返回值表示空闲输入缓冲区的数量。

## bmvpu_dec_get_pkt_in_buf_count

**功能和说明**

- 获取视频解码器输入缓冲区中数据包数量。
- 检查vidHandle是否为空或者解码器状态是否已关闭。如果是，返回0表示没有已有数据包。
- 获取队列中的元素个数，该数量表示还未进行解码的数据包的个数。
- 函数返回获取到的数据包的数量。

**函数名**

`int bmvpu_dec_get_pkt_in_buf_count(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频解码器实例的句柄。

**返回值**

- 返回值为0表示成功，其他值表示失败。

## bmvpu_dec_vpu_reset

**功能和说明**

- 对Sophon设备的VPU进行硬件复位（reset）。
- 该函数可用于复位指定设备上的所有VPU核心，或者只复位设备上的特定VPU核心。

**函数名**

`BMVidDecRetStatus bmvpu_dec_reset(int devIdx, int coreIdx);`

**参数说明**

- `int devIdx` Sophon设备的索引，范围为[0, MAX_PCIE_BOARD_NUM-1]。
- `int coreIdx` VPU核心的索引，范围为[-1, MAX_NUM_VPU_CORE_CHIP-1]。若为-1，表示复位设备上的所有VPU核心。

**返回值**

- 返回值为0表示复位成功，其他值表示复位失败。

## bmvpu_dec_get_core_idx

**功能和说明**

- 获取视频编码器实例的 VPU 核心索引。
- 该函数接受一个视频编码器句柄 BMVidCodHandle 作为参数。
- 通过将输入句柄强制类型转换为 BMVidHandle，然后获取其 codecInst，最终取得 coreIdx。
- 返回 VPU 核心索引。

**函数名**

`int bmvpu_dec_get_core_idx(BMVidCodHandle handle)`

**返回值**

- 返回VPU核心索引。

## bmvpu_get_inst_idx

**功能和说明**

用于获取与Sophon设备中的VPU关联的视频编解码器的实例索引。

**函数名**

`int bmvpu_get_inst_idx(BMVidCodHandle vidCodHandle)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编解码器句柄，表示与Sophon设备中的VPU关联的视频编解码器。

**返回值**

- 返回值表示与Sophon设备中的VPU关联的视频编解码器的实例索引。

## bmvpu_dec_dump_stream

**功能和说明**

- 用于将解码器的输入缓冲区进行映射，用于转储位本地文件。
- 若出现错误，将会返回0。

**函数名**

`int bmvpu_dec_dump_stream(BMVidCodHandle vidCodHandle, unsigned char *p_stream, int size)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编解码器句柄，表示与Sophon设备中的VPU关联的视频编解码器。
- `unsigned char *p_stream` 用于存储解码器输入比特流的本地内存缓冲区的指针。
- `int size` 缓冲区的大小，表示用户提供的本地内存缓冲区的长度。

**返回值**

- 返回值表示成功转储到本地内存的比特流的长度。如果发生错误，返回值为0。

## bmvpu_dec_get_stream_info

**功能和说明**

- 该接口用于外部分配内存时查询码流信息。
- 调用该接口可以获取码流的宽高和缓冲区数量信息。
- 当用户申请的内存和解码器所需要的内存不匹配时，会返回错误。可以通过该接口获取正确的信息。

**函数名**

`BMVidDecRetStatus bmvpu_dec_get_stream_info(BMVidCodHandle vidCodHandle, int* width, int* height, int* mini_fb, int* frame_delay)`

**参数说明**

- `BMVidCodHandle vidCodHandle` 视频编解码器句柄。
- `int* width` 存储码流宽度。
- `int* height` 存储码流高度。
- `int* mini_fb` 存储解码所需的最小缓冲区数量。
- `int* frame_delay` 存储延迟出帧所需的缓冲区数量。

**返回值**

- 返回值表示接口执行的状态。

## bmvpu_dec_set_logging_threshold

**功能和说明**

- 该接口用于设置 SDK 调试信息的打印等级。

**函数名**

`void bmvpu_dec_set_logging_threshold(BmVpuDecLogLevel log_level)`

**参数说明**

- `BmVpuDecLogLevel log_level` 设置打印等级。
- `BmVpuDecLogLevel` 为枚举类型，定义如下：

| **类型** | **含义** |
|----------|----------|
| BMVPU_DEC_LOG_LEVEL_NONE | 不打印任何调试信息 |
| BMVPU_DEC_LOG_LEVEL_ERR | 打印 ERR 类调试信息 |
| BMVPU_DEC_LOG_LEVEL_WARN | 打印 ERR 和 WARN 类调试信息 |
| BMVPU_DEC_LOG_LEVEL_INFO | 打印 ERR、WARN 和 INFO 类调试信息 |
| BMVPU_DEC_LOG_LEVEL_TRACE | 打印 ERR、WARN、INFO 和 TRACE 类调试信息 |
| BMVPU_DEC_LOG_LEVEL_MAX_LOG_LEVEL | 打印所有调试信息 |

# Frame Buffer 计算方法

## compress frame data

(1) buffer countcompress frame 的 count 由 minFrameBufferCount 和 extraFrameBufferCount 来决定。

`compressedFbCount = minFrameBufferCount + extraFrameBufferCount`

其中 extraFrameBufferCount 由用户指定，数量必须大于0。

- Frame Buffer 通过 sdk 内部分配，此参数有默认值为 5，若用户不指定该参数，则按照默认参数来分配。
- Frame Buffer 由用户在外部分配，此参数必须设置，不设置则会报错。

minFrameBufferCount 因码流而异，是 VPU 解码需要的 Frame Buffer 最小值。此参数可以通过 VPU 分析码流得到，但如需要外部分配内存，则需要用户自己计算。

- 对于 HEVC 码流， minFrameBufferCount 由 VPS 参数中的 vps_max_dec_pic_buffering_minus1 参数决定，minFrameBufferCount = vps_max_dec_pic_buffering_minus1 + 2。
- 对于 AVC 码流，minFrameBufferCount 由 max_dec_frame_buffering 参数决定，minFrameBufferCount = max_dec_frame_buffering + 2。

(2) buffer size定义 ALIGN_xx（）表示进行 xx 字节对齐。如 ALIGN_16（）表示进行 16字节对齐。compress frame 的 size 由 图像的宽高决定，具体计算方法如下：

`stride = ALIGN_32(width)`

`height = ALIGN_32(height)`

`LumaSize = stride * height`

`ChromaSize = ALIGN_16(stride / 2) * height`

`FramebufSize = LumaSize + ChromaSize`

## compress frame table

(1) buffer counttable 的数量和 compress frame 匹配，计算方法参考 compress frame data。

(2) buffer size

`YtableBufferSize = ALIGN_16(height) * ALIGN_256(width) / 32`

`YtableBufferSize = ALIGN_4096(YtableBufferSize) + 4096`

`CtableBufferSize = ALIGN_16(height) * ALIGN_256(width / 2) / 32`

`CtableBufferSize = ALIGN_4096(CtableBufferSize) + 4096`

## linear frame buffer

(1) buffer countlinear frame 的 count 由 frameBufDelay 和 extraFrameBufferCount 决定。

`linearFbCount = frameBufDelay + extraFrameBufferCount + 1`

- 对于 HEVC 码流， frameBufDelay 由 VPS 参数中的 num_reorder_pics参数决定， frameBufDelay = vps_max_num_reorder_pics + 2。
- 对于 AVC 码流，frameBufDelay 由 num_reorder_frames 参数决定， frameBufDelay = num_reorder_frames + 2。

(2) buffer sizestride 的对齐方式和 compress frame 一致, height 不进行对齐。

`LumaSize = stride * height`

`ChromaSize = (stride / 2) * (height / 2)`

`FramebufSize = LumaSize + ChromaSize * 2`

# bm_video Encode 枚举类型

- BmVpuEncReturnCodes
- BmVpuEncOutputCodes
- BmVpuEncHeaderDataTypes
- BmVpuCodecFormat
- BmVpuEncPixFormat
- BMVpuEncGopPreset
- BMVpuEncMode
- BmVpuMappingFlags

## BmVpuEncReturnCodes

编码器返回值代码。除了BM_VPU_ENC_RETURN_CODE_OK，其他的返回值应该被视为发生错误，此时编码器应该被关闭。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_ENC_RETURN_CODE_OK | 0 | 操作成功完成 |
| BM_VPU_ENC_RETURN_CODE_ERROR | 1 | 通用错误代码，用作其他错误返回代码不匹配时的通用错误 |
| BM_VPU_ENC_RETURN_CODE_INVALID_PARAMS | 2 | 输入参数无效 |
| BM_VPU_ENC_RETURN_CODE_INVALID_HANDLE | 3 | VPU 编码器句柄无效，内部错误，可能是库中的错误，请报告此类错误 |
| BM_VPU_ENC_RETURN_CODE_INVALID_FRAMEBUFFER | 4 | 帧缓冲区信息无效，通常发生在将包含无效值的 BmVpuFramebuffer 结构传递给 bmvpu_enc_register_framebuffers() 函数时 |
| BM_VPU_ENC_RETURN_CODE_INSUFFICIENT_FRAMEBUFFERS | 5 | 注册用于编码的帧缓冲区失败，因为未提供足够的帧缓冲区给 bmvpu_enc_register_framebuffers() 函数 |
| BM_VPU_ENC_RETURN_CODE_INVALID_STRIDE | 6 | 步幅值无效，例如帧缓冲区的一个步幅值无效 |
| BM_VPU_ENC_RETURN_CODE_WRONG_CALL_SEQUENCE | 7 | 在不适当的时间调用函数 |
| BM_VPU_ENC_RETURN_CODE_TIMEOUT | 8 | 操作超时 |
| BM_VPU_ENC_RETURN_CODE_RESEND_FRAME | 9 | 重复送帧 |
| BM_VPU_ENC_RETURN_CODE_ENC_END | 10 | 编码结束 |
| BM_VPU_ENC_RETURN_CODE_END | 11 | 编码结束 |

## BmVpuEncOutputCodes

编码器内部输出代码。这些代码可以通过按位 OR 进行组合，通过使用按位 AND 检查 `bmvpu_enc_encode()` 返回的 `output_codes` 位掩码，来确认编码器状态。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_ENC_OUTPUT_CODE_INPUT_USED | 1 << 0 | 表示输入数据已被使用。如果未设置该标志位，则编码器尚未使用输入数据，因此请将其再次输入给编码器，直到此标志位被设置或返回错误 |
| BM_VPU_ENC_OUTPUT_CODE_ENCODED_FRAME_AVAILABLE | 1 << 1 | 表示现在有一个完全编码的帧可用。传递给 `bmvpu_enc_encode()` 的 `encoded_frame` 参数包含有关此帧的信息 |
| BM_VPU_ENC_OUTPUT_CODE_CONTAINS_HEADER | 1 << 2 | 表示编码帧中的数据还包含头信息，如 H.264 的 SPS/PSS。头信息始终放置在编码数据的开头，如果未设置 `BM_VPU_ENC_OUTPUT_CODE_ENCODED_FRAME_AVAILABLE`，则该标志位不会被设置 |

## BmVpuEncHeaderDataTypes

定义了编码器头部数据的不同类型。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_ENC_HEADER_DATA_TYPE_VPS_RBSP | 0 | 视频参数集 (VPS) 的 RBSP（Raw Byte Sequence Payload）数据类型 |
| BM_VPU_ENC_HEADER_DATA_TYPE_SPS_RBSP | 1 | 序列参数集 (SPS) 的 RBSP 数据类型 |
| BM_VPU_ENC_HEADER_DATA_TYPE_PPS_RBSP | 2 | 图像参数集 (PPS) 的 RBSP 数据类型 |

## BmVpuCodecFormat

编码器支持的编码格式。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_CODEC_FORMAT_H264 | 0 | 编码类型 H.264 |
| BM_VPU_CODEC_FORMAT_H265 | 1 | 编码类型 H.265 |

## BmVpuEncPixFormat

编码器输入 yuv 格式。
目前仅支持 nv12，nv21，yuv420p。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_ENC_PIX_FORMAT_YUV420P | 0 | planar 4:2:0 |
| BM_VPU_ENC_PIX_FORMAT_YUV422P | 1 | planar 4:2:2 |
| BM_VPU_ENC_PIX_FORMAT_YUV444P | 3 | planar 4:4:4 |
| BM_VPU_ENC_PIX_FORMAT_YUV400 | 4 | 8 位灰度图像 |
| BM_VPU_ENC_PIX_FORMAT_NV12 | 5 | semi-planar 4:2:0 |
| BM_VPU_ENC_PIX_FORMAT_NV16 | 6 | semi-planar 4:2:2 |
| BM_VPU_ENC_PIX_FORMAT_NV24 | 7 | semi-planar 4:4:4 |

## BMVpuEncGopPreset

编码器输入 gop_preset设置。

| **枚举值** | **返回值** | **描述** |
|------------|------------|----------|
| BM_VPU_ENC_GOP_PRESET_ALL_I | 1 | 全 I 帧模式，gopsize=1 |
| BM_VPU_ENC_GOP_PRESET_IPP | 2 | 全 IP 帧模式，gopsize=1 |
| BM_VPU_ENC_GOP_PRESET_IBBB | 3 | 全 IB 帧模式，gopsize=1 |
| BM_VPU_ENC_GOP_PRESET_IBPBP | 4 | 全 IBP 帧模式，gopsize=2 |

# BM_VPU_ENC_GOP_PRESET_IBBBP
- 5
- 全 IBP 帧模式，gopsize=4

# BM_VPU_ENC_GOP_PRESET_IPPPP
- 6
- 全 IP 帧模式，gopsize=4

# BM_VPU_ENC_GOP_PRESET_IBBBB
- 7
- 全 IB 帧模式，gopsize=4

# BM_VPU_ENC_GOP_PRESET_RA_IB
- 8
- Random IB 帧模式，gopsize=8

# BMVpuEncMode
编码器输入编码模式。

| 枚举值 | 返回值 | 描述 |
|--------|--------|------|
| BM_VPU_ENC_CUSTOM_MODE | 0 | 自定义模式 |
| BM_VPU_ENC_RECOMMENDED_MODE | 1 | 推荐模式（慢编码速度，最高画质） |
| BM_VPU_ENC_BOOST_MODE | 2 | 提升模式（正常编码速度，正常画质） |
| BM_VPU_ENC_FAST_MODE | 3 | 快速模式（高编码速度，低画质） |

# BmVpuMappingFlags
用于使用vpu_EncMmap()函数时指定映射类型。

| 枚举值 | 返回值 | 描述 |
|--------|--------|------|
| BM_VPU_MAPPING_FLAG_WRITE | 1 << 0 | 可写权限标志 |
| BM_VPU_MAPPING_FLAG_READ | 1 << 1 | 可读权限标志 |

# bm_video Encode 数据结构
- BmVpuEncH264Params
- BmVpuEncH265Params
- BmVpuEncOpenParams
- BmVpuEncInitialInfo
- BmCustomMapOpt
- BmVpuEncParams
- BmVpuEncoder
- BmVpuFbInfo
- BmVpuEncodedFrame
- BmVpuEncDMABuffer
- BmVpuRawFrame
- BmVpuFramebuffer

# BmVpuEncH264Params
定义了新的 H.264 编码器实例的参数。

| 成员变量 | 类型 | 描述 |
|----------|------|------|
| enable_transform8x8 | int | 启用 8x8 帧内预测和 8x8 变换。默认值为 1 |

# BmVpuEncH265Params
定义了新的 H.265 编码器实例的参数。

| 成员变量 | 类型 | 描述 |
|----------|------|------|
| enable_tmvp | int | 启用时域运动矢量预测。默认值为 1 |
| enable_wpp | int | 启用线性缓冲区模式的波前并行处理。默认值为 0 |
| enable_sao | int | 如果设置为 1，则启用 SAO；如果设置为 0，则禁用。默认值为 1 |
| enable_strong_intra_smoothing | int | 启用对带有少量 AC 系数的区域进行强烈的帧内平滑，以防止伪影。默认值为 1 |
| enable_intra_trans_skip | int | 启用帧内 CU 的变换跳过。默认值为 0 |
| enable_intraNxN | int | 启用帧内 NxN PUs。默认值为 1 |

# BmVpuEncOpenParams
用于初始化编码器的全局参数，设置编码器的基本属性和编码器类型等。

| 成员变量 | 类型 | 描述 |
|----------|------|------|
| codec_format | BmVpuCodecFormat | 指定要生成的编码数据的编码格式 |
| pix_format | BmVpuEncPixFormat | 指定传入帧使用的图像格式 |
| frame_width | uint32_t | 传入帧的宽度（以像素为单位），无需对齐 |
| frame_height | uint32_t | 传入帧的高度（以像素为单位），无需对齐 |
| timebase_num | uint32_t | 时间基数，以分数形式给出 |
| timebase_den | uint32_t | 时间分母，以分数形式给出 |
| fps_num | uint32_t | 帧率，以分数形式给出 |
| fps_den | uint32_t | 帧率分母，以分数形式给出 |
| bitrate | int64_t | 比特率（以 bps 为单位）。如果设置为 0，则禁用码率控制，而使用常量质量模式。默认值为 100000 |
| vbv_buffer_size | uint64_t | vbv 缓冲区的大小，以 bit 为单位。仅在启用码率控制时（*BmVpuEncOpenParams* 中的 *bitrate* 非零）使用。0 表示不检查缓冲区大小约束。默认值为 0 |
| cqp | int | 常量质量模式的量化参数 |
| enc_mode | BMVpuEncMode | 编码模式：0 自定义模式，1 推荐的编码器参数（慢编码速度，最高画质），2 提升模式（正常编码速度，正常画质），3 快速模式（高编码速度，低画质）。默认值为 2 |
| max_num_merge | int | RDO 中的合并候选数（1 或 2）。1：提高编码性能，2：提高编码图像的质量。默认值为 2 |
| enable_constrained_intra_prediction | int | 启用受限帧内预测。如果设置为 1，则启用；如果设置为 0，则禁用。默认值为 0 |
| enable_wp | int | 启用加权预测。默认值为 1 |
| disable_deblocking | int | 如果设置为 1，则禁用去块滤波器。如果设置为 0，则保持启用。默认值为 0 |
| offset_tc | int | deblocking 滤波器的 Alpha/Tc 偏移。默认值为 0 |
| offset_beta | int | deblocking 滤波器的 Beta 偏移。默认值为 0 |
| enable_cross_slice_boundary | int | 启用帧内循环滤波中的跨切片边界滤波。默认值为 0 |
| enable_nr | int | 启用降噪。默认值为 1 |
| h264_params | BmVpuEncH264Params | H.264 编码器参数。（union，从 *h264_params* 和 *h265_params* 中选择一个） |
| h265_params | BmVpuEncH265Params | H.265 编码器参数。（union，从 *h264_params* 和 *h265_params* 中选择一个） |
| soc_idx | int | 仅用于 PCIe 模式。对于 SOC 模式，此值必须为 0。默认值为 0 |
| gop_preset | BMVpuEncGopPreset | GOP 结构预设选项。1：全部为 I帧，gopsize = 1；2：I-P-P，连续 P，循环 gopsize = 1；3：I-B-B-B，连续 B，循环 gopsize = 1；4：I-B-P-B-P，gopsize = 2；5：I-B-B-B-P，gopsize = 4；6：I-P-P-P-P，连续 P，循环 gopsize = 4；7：I-B-B-B-B，连续 B，循环 gopsize = 4；8：随机访问，I-B-B-B-B-B-B-B-B，循环 gopsize = 8 低延迟情况为 1、2、3、6、7。默认值为 5 |
| intra_period | int | GOP 大小内的帧内图片周期。默认值为 28 |
| bg_detection | int | 启用背景检测。默认值为 0 |
| mb_rc | int | 启用 MB 级/CU 级码率控制。默认值为 1 |
| delta_qp | int | 码率控制的最大 delta QP。默认值为 5 |
| min_qp | int | 码率控制的最小 QP。默认值为 8 |
| max_qp | int | 码率控制的最大 QP。默认值为 51 |
| roi_enable | int | ROI 编码标志。默认值为 0 |
| cmd_queue_depth | int | 设置命令队列深度，默认值为 4，取值范围 [1, 4] |
| timeout | int | 编码超时时间，默认为 1000ms（即 VPU_WAIT_TIMEOUT） |
| timeout_count | int | 编码超时重试次数，默认为 40（即 VPU_MAX_TIMEOUT_COUNTS） |
| buffer_alloc_func | BmVpuEncBufferAllocFunc | 缓冲区内存分配函数接口 |
| buffer_free_func | BmVpuEncBufferFreeFunc | 缓冲区内存释放函数接口 |
| buffer_context | void* | 缓冲区上下文信息 |

# BmVpuEncInitialInfo
初始编码信息，由编码器生成。这个结构体对于实际开始编码至关重要，因为它包含了创建和注册足够的帧缓冲区所需的所有信息。

| 成员变量 | 类型 | 描述 |
|----------|------|------|
| min_num_rec_fb | uint32_t | 最小推荐帧缓冲区数量，分配少于此数量可能会影响编码质量 |
| min_num_src_fb | uint32_t | 输入 YUV 数据帧的最小数量，分配少于此数量可能会影响编码 |
| framebuffer_alignment | uint32_t | 物理帧缓冲区地址的对齐要求 |
| rec_fb | BmVpuFbInfo | 用于重建的帧缓冲区大小信息。包括宽度、高度等信息 |
| src_fb | BmVpuFbInfo | 输入 YUV 数据的宽高信息 |

# BmCustomMapOpt
自定义映射选项（H.265编码器）。

| 成员变量 | 类型 | 描述 |
|----------|------|------|
| roiAvgQp | int | ROI 映射的平均 QP |
| customRoiMapEnable | int | 是否开启 ROI 映射 |
| customLambdaMapEnable | int | 是否开启 Lambda 映射 |
| customModeMapEnable | int | 是否指定 CTU 使用帧间编码，否则跳过 |
| customCoefDropEnable | int | 对于每个 CTU，是否设置 TQ 系数为全0，系数全0的 CTU 将被丢弃 |
| addrCustomMap | bmvpu_phys_addr_t | 自定义映射缓冲区的起始地址 |

# BmVpuEncParams

用于配置编码器的运行时参数，影响每次编码操作的具体行为。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| skip_frame | int | 默认值为 0,禁用跳帧生成。如果设置为 1，则 VPU 忽略给定的原始帧，而生成一个"跳帧"，它是前一帧的复制。这个跳帧被编码为 P 帧 |
| forcePicTypeEnable | int | 是否强制指定编码帧类型 |
| forcePicType | int | 强制指定的编码帧类型（I帧、P帧、B帧、IDR帧、CRA帧），只有当 *forcePicTypeEnable* 为 1 时有效 |
| acquire_output_buffer | BmVpuEncAcquireOutputBuffer | 用于获取输出缓冲区的函数 |
| finish_output_buffer | BmVpuEncFinishOutputBuffer | 用于释放输出缓冲区的函数 |
| output_buffer_context | void* | 传递给上述函数的用户提供的值 |
| customMapOpt | BmCustomMapOpt* | 指向自定义映射选项的指针 |

# BmVpuEncoder

具体的编码器实例，会接收BmVpuEncOpenParams的参数信息。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| handle | void* | 编码器句柄 |
| soc_idx | int | Sophon SoC 的索引。对于 PCIE 模式，请参考 /dev/bm-sophonxx 中的编号。对于 SOC 模式，请将其设置为零 |
| core_idx | int | 所有 Sophon SoC 中 VPU 编码器core的统一索引 |
| codec_format | BmVpuCodecFormat | 编码器使用的视频编解码格式 |
| color_format | BmVpuEncPixFormat | 传入帧使用的图像格式 |
| frame_width | uint32_t | 传入帧的宽度（以像素为单位） |
| frame_height | uint32_t | 传入帧的高度（以像素为单位） |
| fps_n | uint32_t | 帧率的分子 |
| fps_d | uint32_t | 帧率的分母 |
| first_frame | int | 是否为第一帧 |
| rc_enable | int | 是否启用码率控制 |
| cqp | int | 在禁用码率控制时，使用恒定的量化参数 QP |
| work_dmabuffer | BmVpuEncDMABuffer* | 用于编码器工作的 DMA 缓冲区 |
| bs_dmabuffer | BmVpuEncDMABuffer* | 用于存储码流的 DMA 缓冲区 |
| bs_virt_addr | unsigned long long | 码流的虚拟地址 |
| bs_phys_addr | bmvpu_phys_addr_t | 码流的物理地址 |
| num_framebuffers | uint32_t | 帧缓冲区的数量 |
| internal_framebuffers | void* | 编码器内部的帧缓冲区 |
| framebuffers | BmVpuFramebuffer* | 帧缓冲区 |
| buffer_mv | BmVpuEncDMABuffer* | 用于存储运动矢量的 DMA 缓冲区 |
| buffer_fbc_y_tbl | BmVpuEncDMABuffer* | 用于存储 FBC 亮度表的 DMA 缓冲区 |
| buffer_fbc_c_tbl | BmVpuEncDMABuffer* | 用于存储 FBC 色度表的 DMA 缓冲区 |
| buffer_sub_sam | BmVpuEncDMABuffer* | 用于 ME 的子采样 DMA 缓冲区 |
| headers_rbsp | uint8_t* | 帧头 RBSP 数据 |
| headers_rbsp_size | size_t | 帧头 RBSP 数据的大小 |
| initial_info | BmVpuEncInitialInfo | 编码器的初始信息 |
| timeout | int | 编码超时时间，默认为1000ms（即 VPU_WAIT_TIMEOUT） |
| timeout_count | int | 编码超时重试次数，默认为40（即 VPU_MAX_TIMEOUT_COUNTS） |
| video_enc_ctx | void* | 编码上下文信息，内部使用 |

# BmVpuFbInfo

与 `bmvpu_calc_framebuffer_sizes()` 一起使用，用于计算帧缓冲区的大小。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| width | int | 帧的宽度，按照 VPU 要求的 16 像素边界对齐 |
| height | int | 帧的高度，按照 VPU 要求的 16 像素边界对齐 |
| y_stride | int | 对齐后的 Y 分量的跨距大小，以字节为单位 |
| c_stride | int | 对齐后的 Cb 和 Cr 分量的跨距大小，以字节为单位（可选） |
| y_size | int | Y 分量的 DMA 缓冲区大小，以字节为单位 |
| c_size | int | Cb 和 Cr 分量的 DMA 缓冲区大小，以字节为单位 |
| size | int | 帧缓冲区 DMA 缓冲区的总大小，以字节为单位。这个值包括所有通道的大小 |

# BmVpuEncodedFrame

编码帧的详细信息。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| data | uint8_t* | 在解码时，data 必须指向包含码流数据的内存块，编码器不使用 |
| data_size | size_t | 编码数据的大小。在编码时，由编码器设置，表示获取的输出块的大小，以字节为单位 |
| frame_type | BmVpuEncFrameType | 编码帧的帧类型（I、P、B 等）。由编码器填充。仅由编码器使用 |
| acquired_handle | void* | 在编码时由用户定义的 **acquire_output_buffer** 函数生成的句柄。仅由编码器使用 |
| context | void* | 用户定义的指针。编码器不会更改此值。这个指针和相应原始帧的指针将具有相同的值，在编码器中传递 |
| pts | uint64_t | 用户定义的显示时间戳（Presentation Timestamp）。与 *context* 指针一样，编码器只是将其传递到关联的原始帧，并不实际更改其值 |
| dts | uint64_t | 用户定义的解码时间戳（Decoding Timestamp）。与 *pts* 指针一样，编码器只是将其传递到关联的原始帧，并不实际更改其值 |
| src_idx | int | 原始帧的索引 |
| u64CustomMapPhyAddr | bmvpu_phys_addr_t | 用户自定义映射选项的起始地址 |
| avg_ctu_qp | int | 平均 CTU QP（Quantization Parameter） |

# BmVpuEncDMABuffer

保存 YUV 数据的物理内存。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| size | unsigned int | 物理内存的大小 |
| phys_addr | uint64_t | 物理内存的地址 |
| virt_addr | uint64_t | 物理内存mmap后的虚拟地址 |
| enable_cache | int | 是否开启cache |

# BmVpuRawFrame

结构体包含了关于原始、未压缩帧的详细信息。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| framebuffer | BmVpuFramebuffer* | 原始帧的帧缓冲区 |
| context | void* | 用户定义的指针。编码器不会更改此值。这个指针和相应编码帧的指针将具有相同的值，在编码器中传递 |
| pts | uint64_t | 用户定义的显示时间戳（Presentation Timestamp）。与 *context* 指针一样，编码器只是将其传递到关联的编码帧，并不实际更改其值 |
| dts | uint64_t | 用户定义的解码时间戳（Decoding Timestamp）。与 *pts* 指针一样，编码器只是将其传递到关联的编码帧，并不实际更改其值 |

# BmVpuFramebuffer

帧缓冲区的相关信息，用于容纳视频帧的像素数据，同时用于编码和解码。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| dma_buffer | BmVpuEncDMABuffer* | 保存 YUV 数据的物理内存 |
| myIndex | int | YUV 索引，用户设置，用于释放 YUV 数据 |
| y_stride | unsigned int | Y 通道对齐后的大小 |
| cbcr_stride | unsigned int | UV 通道对齐后的大小 |
| width | unsigned int | 编码 YUV 图像的宽 |
| height | unsigned int | 编码 YUV 图像的高 |
| y_offset | size_t | Y 通道 offset。相对于缓冲区起始位置，指定每个分量的起始偏移量。以字节为单位指定 |
| cb_offset | size_t | U 通道 offset。 |
| cr_offset | size_t | V 通道 offset。 |
| already_marked | int | 如果帧缓冲区已在编码器中标记为已使用，则设置为 1。仅供内部使用。不要从外部读取或写入 |
| internal | void* | 内部实现定义的数据。不要修改。 |
| context | void* | 用户定义的指针，编码器不会修改此值。用法由用户决定，例如，可以用于标识在编码器中包含该帧的帧缓冲区的序号 |

# bm_video Encode API

* bmvpu_enc_error_string
* bmvpu_enc_get_core_idx
* bmvpu_enc_load
* bmvpu_enc_unload
* bmvpu_enc_get_bitstream_buffer_info
* bmvpu_enc_set_default_open_params
* bmvpu_fill_framebuffer_params
* bmvpu_enc_open
* bmvpu_enc_close
* bmvpu_enc_encode
* bmvpu_enc_dma_buffer_allocate
* bmvpu_enc_dma_buffer_deallocate
* bmvpu_enc_dma_buffer_attach
* bmvpu_enc_dma_buffer_deattach
* bmvpu_dma_buffer_map
* bmvpu_dma_buffer_unmap
* bmvpu_enc_dma_buffer_flush
* bmvpu_enc_dma_buffer_invalidate
* bmvpu_enc_dma_buffer_get_physical_address
* bmvpu_enc_dma_buffer_get_size
* bmvpu_enc_upload_data
* bmvpu_enc_download_data

## bmvpu_enc_error_string

**功能和说明**

* 返回编码错误码的具体描述。

**函数名**

`char const * bmvpu_enc_error_string(BmVpuEncReturnCodes code)`

**参数说明**

* `BmVpuEncReturnCodes code` 编码错误码。

## bmvpu_enc_get_core_idx

**功能和说明**

* 在指定的Sophon SoC上，获取VPU编码器core的唯一索引。

**函数名**

`int bmvpu_enc_get_core_idx(int soc_idx)`

**参数说明**

* `int soc_idx` 设备索引号。

**返回值**

* 返回值为core的唯一索引。

## bmvpu_enc_load

**功能和说明**

* 加载Sophon设备上的视频处理单元（VPU）的编码模块。
* unload()和load()的调用次数要一致。
* 在对编码器执行任何其他操作之前，必须先加载(load)编码器。
* 同样，在完成所有编码器活动之前，不得卸载(unload)编码器，包括打开编码器实例。

**函数名**

`int bmvpu_enc_load(int soc_idx)`

**参数说明**

* `int soc_idx` 设备索引号。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_unload

**功能和说明**

* 卸载(unload)编码器。

**函数名**

`int bmvpu_enc_unload(int soc_idx)`

**参数说明**

* `int soc_idx` 设备索引号。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_get_bitstream_buffer_info

**功能和说明**

* 该函数得到编码器所需的 bitstream buffer 的大小 (size) 和所需要的 对齐（alignment）值。
* 返回编码器的码流缓冲区所需的物理内存块的对齐方式和大小。
* 用户必须分配至少此大小的 DMA 缓冲区，并且必须根据对齐值对其物理地址进行对齐。
* 需要在bmvpu_enc_open()之前调用。

**函数名**

`void bmvpu_enc_get_bitstream_buffer_info(size_t *size, uint32_t *alignment)`

**参数说明**

* `size_t *size` 码流缓冲区所需的物理内存块的大小。
* `uint32_t *alignment` 码流缓冲区所需的物理内存块的对齐方式。

**返回值**

* 无。

## bmvpu_enc_set_default_open_params

**功能和说明**

* 设置编码器的默认变量，用于编码器初始化时传递参数。
* 如果调用方只想修改几个成员变量（或者不做修改），可以调用此函数。
* 需要在 bmvpu_enc_open 之前调用。

**函数名**

`void bmvpu_enc_set_default_open_params(BmVpuEncOpenParams *open_params, BmVpuCodecFormat codec_format)`

**参数说明**

* `BmVpuEncOpenParams *open_params` 用于返回编码器的参数。
* `BmVpuCodecFormat codec_format` 编码器选择，h264 或 h265。

**返回值**

* 无。

## bmvpu_fill_framebuffer_params

**功能和说明**

* 根据传入的 *fb_info* 填充 *BmVpuFramebuffer* 结构中的参数。
* 可以在此指定帧缓冲区及上下文信息。

**函数名**

`int bmvpu_fill_framebuffer_params(BmVpuFramebuffer *framebuffer, BmVpuFbInfo *fb_info, BmVpuEncDMABuffer *fb_dma_buffer, int fb_id, void *context)`

**参数说明**

* `BmVpuFramebuffer *framebuffer` 需要填充的帧缓冲区信息。
* `BmVpuFbInfo *fb_info` 从编码器获取的初始化信息，包含所需的帧缓冲区的最小个数及大小。
* `BmVpuEncDMABuffer *fb_dma_buffer` 分配给帧缓冲区的保存 YUV 数据的物理内存。
* `int fb_id` 用户设置的 YUV 数据索引。
* `void *context` 用户设置的上下文信息。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_open

**功能和说明**

* 打开一个新的编码器实例, 设置编码器参数并开始接收视频帧。
* `BmVpuEncOpenParams *open_params` 和 `BmVpuDMABuffer *bs_dmabuffer` 必须不为空。

**函数名**

`int bmvpu_enc_open(BmVpuEncoder **encoder, BmVpuEncOpenParams *open_params, BmVpuDMABuffer *bs_dmabuffer, BmVpuEncInitialInfo *initial_info)`

**参数说明**

* `BmVpuEncoder **encoder` 指向编码器实例的二级指针，接收编码器的属性和视频帧的部分设置, 例如设备 id、缓冲区设置和帧率、宽高等。
* `BmVpuEncOpenParams *open_params` 编码器各项参数。
* `BmVpuDMABuffer *bs_dmabuffer` 指向码流缓冲区的指针，使用之前已经分配的码流缓冲区。
* `BmVpuEncInitialInfo *initial_info` 编码器的初始化信息，返回给用户编码器需要的帧缓冲区最小个数和大小。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_close

**功能和说明**

* 关闭编码器实例。
* 多次尝试关闭同一实例会导致未定义的行为。

**函数名**

`int bmvpu_enc_close(BmVpuEncoder *encoder)`

**参数说明**

* `BmVpuEncoder *encoder` 视频编码器实例。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_encode

**功能和说明**

* 使用给定的编码参数对给定的原始输入帧进行编码。*encoded_frame* 填充有关于所得到的编码输出帧的信息。
* 编码的帧数据本身被存储在由用户提供的函数（在 *encoding_params* 中被设置为 *acquire_output_buffer* 和 *finish_output_buffer* 函数指针）分配的缓冲区中。

**函数名**

`int bmvpu_enc_encode(BmVpuEncoder *encoder, BmVpuRawFrame const *raw_frame, BmVpuEncodedFrame *encoded_frame, BmVpuEncParams *encoding_params, uint32_t *output_code)`

**参数说明**

* `BmVpuEncoder *encoder` 视频编码器实例。
* `BmVpuRawFrame const *raw_frame` 原始视频帧，包括帧数据、时间戳等。
* `BmVpuEncodedFrame *encoded_frame` 编码后的视频帧，包括帧数据、帧类型、时间戳等。
* `BmVpuEncParams *encoding_params` 用于编码的参数。
* `uint32_t *output_code` 返回输出状态代码。

**返回值**

* 返回值为0表示成功，其他值表示失败。

## bmvpu_enc_dma_buffer_allocate

**功能和说明**

* 根据用户指定的size分配设备内存。

**函数名**

`int bmvpu_enc_dma_buffer_allocate(int vpu_core_idx, BmVpuEncDMABuffer *buf, unsigned int size)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuEncDMABuffer *buf` 输出参数，函数执行后，将会填充该结构体的 *phys_addr*、*size*、*enable_cache* 成员变量。
* `unsigned int size` 输入参数，以字节为单位，指定需要的缓冲区大小。

**返回值**

* 返回BM_SUCESS(=0)表示分配成功 ，否则分配失败。

## bmvpu_enc_dma_buffer_deallocate

**功能和说明**

* 释放由 **bmvpu_enc_dma_buffer_allocate** 函数分配的设备内存。

**函数名**

`int bmvpu_enc_dma_buffer_deallocate(int vpu_core_idx, BmVpuEncDMABuffer *buf)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuDMABuffer *buf` 输入参数，调用前用户必须要填充该结构体的 *phys_addr*、*size*、*virt_addr* 成员变量。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_enc_dma_buffer_attach

**功能和说明**

* 将用户通过 **bmvpu_enc_dma_buffer_allocate** 函数以外的其它方式申请的设备内存地址绑定至编码器。

**函数名**

`int bmvpu_enc_dma_buffer_attach(int vpu_core_idx, uint64_t paddr, unsigned int size)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `uint64_t paddr` 输入参数，由用户通过 **bmvpu_enc_dma_buffer_allocate** 函数以外的其它方式申请的设备内存地址。
* `unsigned int size` 输入参数，该块设备内存大小(byte)。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_enc_dma_buffer_deattach

**功能和说明**

* 将用户通过 **bmvpu_enc_dma_buffer_attach** 函数绑定的设备内存解绑。

**函数名**

`int bmvpu_enc_dma_buffer_deattach(int vpu_core_idx, uint64_t paddr, unsigned int size)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `uint64_t paddr` 输入参数，由用户通过 **bmvpu_enc_dma_buffer_attach** 函数绑定的设备内存物理地址。
* `unsigned int size` 输入参数，该块设备内存大小(byte)。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_dma_buffer_map

**功能和说明**

* 将对应core上申请的设备内存映射到系统内存。

**函数名**

`int bmvpu_dma_buffer_map(int vpu_core_idx, BmVpuEncDMABuffer *buf, int port_flag)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuEncDMABuffer *buf` 输入参数，指定设备内存的地址、大小等信息。
* `int port_flag` 输入参数，配置 **mmap** 内存可读(*BM_VPU_MAPPING_FLAG_READ*)或可写(*BM_VPU_MAPPING_FLAG_WRITE*)。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_dma_buffer_unmap

**功能和说明**

* 对某个core上映射过的设备内存解除映射。

**函数名**

`int bmvpu_dma_buffer_unmap(int vpu_core_idx, BmVpuEncDMABuffer *buf)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuEncDMABuffer *buf` 输入参数，指定设备内存的地址、大小等信息。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_enc_dma_buffer_flush

**功能和说明**

* 对已分配的设备内存进行flush操作。

**函数名**

`int bmvpu_enc_dma_buffer_flush(int vpu_core_idx, BmVpuEncDMABuffer *buf)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuEncDMABuffer *buf` 输入参数，调用前用户至少要填充该结构体的 *phys_addr*、*size* 成员变量。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

## bmvpu_enc_dma_buffer_invalidate

**功能和说明**

* 对已分配的设备内存进行invalid操作。

**函数名**

`int bmvpu_enc_dma_buffer_invalidate(int vpu_core_idx, BmVpuEncDMABuffer *buf)`

**参数说明**

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `BmVpuEncDMABuffer *buf` 输入参数，调用前用户至少要填充该结构体的 *phys_addr*、*size* 成员变量。

**返回值**

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

# bmvpu_enc_dma_buffer_get_physical_address

## 功能和说明

* 返回已分配的设备内存的地址。

## 函数名

`uint64_t bmvpu_enc_dma_buffer_get_physical_address(BmVpuEncDMABuffer *buf)`

## 参数说明

* `BmVpuEncDMABuffer *buf` 输入参数，已分配的设备内存。

## 返回值

* 已分配的设备内存的物理地址。

# bmvpu_enc_dma_buffer_get_size

## 功能和说明

* 返回已分配的设备内存的大小。

## 函数名

`unsigned int bmvpu_enc_dma_buffer_get_size(BmVpuEncDMABuffer *buf)`

## 参数说明

* `BmVpuDMABuffer *buf` 输入参数。

## 返回值

* 已分配的设备内存的大小。

# bmvpu_enc_upload_data

## 功能和说明

* 向使用 **bmvpu_enc_dma_buffer_allocate()** 分配的设备内存地址传输数据。

## 函数名

`int bmvpu_enc_upload_data(int vpu_core_idx, const uint8_t* host_va, int host_stride, uint64_t vpu_pa, int vpu_stride, int width, int height)`

## 参数说明

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `const uint8_t* host_va` 输入参数, 待传输数据的host端虚拟地址。
* `int host_stride` 输入参数，host端的数据跨距。
* `uint64_t vpu_pa` 输入参数，传输数据的目标物理地址。
* `int vpu_stride` 输入参数，device端的数据跨距。
* `int width` 输入参数，数据宽度。
* `int height` 输入参数，数据高度。

## 返回值

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

# bmvpu_enc_download_data

## 功能和说明

* 从 **bmvpu_enc_dma_buffer_allocate()** 分配的设备内存地址向host端传输数据。

## 函数名

`int bmvpu_enc_download_data(int vpu_core_idx, uint8_t* host_va, int host_stride, uint64_t vpu_pa, int vpu_stride, int width, int height)`

## 参数说明

* `int vpu_core_idx` 输入参数，指定编码器所在core的索引。
* `const uint8_t* host_va` 输入参数, 传输数据的目标地址。
* `int host_stride` 输入参数，host端的数据跨距。
* `uint64_t vpu_pa` 输入参数，传输数据的物理地址。
* `int vpu_stride` 输入参数，device端的数据跨距。
* `int width` 输入参数，数据宽度。
* `int height` 输入参数，数据高度。

## 返回值

* 返回BM_SUCESS(=0)表示执行成功 ，否则执行失败。

# JPU枚举类型

* BmJpuLogLevel
* BmJpuImageFormat
* BmJpuColorFormat
* BmJpuChromaFormat
* BmJpuRotateAngle
* BmJpuMirrorDirection

## BmJpuLogLevel

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_LOG_LEVEL_ERROR | 日志等级ERROR |
| BM_JPU_LOG_LEVEL_WARNING | 日志等级WARNING |
| BM_JPU_LOG_LEVEL_INFO | 日志等级INFO |
| BM_JPU_LOG_LEVEL_DEBUG | 日志等级DEBUG |
| BM_JPU_LOG_LEVEL_LOG | 日志等级LOG |
| BM_JPU_LOG_LEVEL_TRACE | 日志等级TRACE |

## BmJpuImageFormat

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_IMAGE_FORMAT_YUV420P | YUV 4:2:0 planar |
| BM_JPU_IMAGE_FORMAT_YUV422P | YUV 4:2:2 planar |
| BM_JPU_IMAGE_FORMAT_YUV444P | YUV 4:4:4 planar |
| BM_JPU_IMAGE_FORMAT_NV12 | YUV 4:2:0 NV12 |
| BM_JPU_IMAGE_FORMAT_NV21 | YUV 4:2:0 NV21 |
| BM_JPU_IMAGE_FORMAT_NV16 | YUV 4:2:2 NV16 |
| BM_JPU_IMAGE_FORMAT_NV61 | YUV 4:2:2 NV61 |
| BM_JPU_IMAGE_FORMAT_GRAY | YUV 4:0:0 |
| BM_JPU_IMAGE_FORMAT_RGB | RGB 8:8:8 packed, for opencv |

## BmJpuColorFormat

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_COLOR_FORMAT_YUV420 | YUV 4:2:0 format |
| BM_JPU_COLOR_FORMAT_YUV422_HORIZONTAL | YUV 4:2:2 format |
| BM_JPU_COLOR_FORMAT_YUV422_VERTICAL | YUV 2:2:4 format (JPU中定义的一种格式，很少使用) |
| BM_JPU_COLOR_FORMAT_YUV444 | YUV 4:4:4 format |
| BM_JPU_COLOR_FORMAT_YUV400 | YUV 4:0:0 format |

## BmJpuChromaFormat

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_CHROMA_FORMAT_CBCR_SEPARATED | Cb、Cr分量非交织，分别存放在不同的通道 |
| BM_JPU_CHROMA_FORMAT_CBCR_INTERLEAVE | Cb、Cr分量交织，存放在一个通道 |

## BmJpuRotateAngle

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_ROTATE_NONE | 不做旋转 |
| BM_JPU_ROTATE_90 | 逆时针旋转90度 |
| BM_JPU_ROTATE_180 | 逆时针旋转180度 |
| BM_JPU_ROTATE_270 | 逆时针旋转270度 |

## BmJpuMirrorDirection

| 枚举变量 | 描述 |
|---------|------|
| BM_JPU_MIRROR_NONE | 不做镜像 |
| BM_JPU_MIRROR_VER | 竖直方向镜像 |
| BM_JPU_MIRROR_HOR | 水平方向镜像 |
| BM_JPU_MIRROR_HOR_VER | 水平和竖直方向镜像 |

# JPU通用结构体

* BmJpuFramebuffer
* BmJpuFramebufferSizes
* BmJpuRawFrame

## BmJpuFramebuffer

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| y_stride | unsigned int | Y 分量的步幅（Stride），单位: byte |
| cbcr_stride | unsigned int | Cb 和 Cr 分量的步幅（Stride），单位: byte |
| dma_buffer | bm_device_mem_t* | 用于存放 YUV 数据的一块设备内存，由 bmlib 分配 |
| y_offset | size_t | Y 分量起始地址相对于 dma_buffer 中物理地址的偏移量，单位: byte |
| cb_offset | size_t | Cb 分量起始地址相对于 dma_buffer 中物理地址的偏移量，单位: byte |
| cr_offset | size_t | Cr 分量起始地址相对于 dma_buffer 中物理地址的偏移量，单位: byte |
| context | void* | 用户定义的指针，库不会更改此值。使用方法由用户决定，例如：用于保存解码上下文信息 |
| already_marked | int | 如果帧缓冲区已标记为已显示，则设置为 1 。仅供内部使用，请不要修改 |

## BmJpuFramebufferSizes

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| aligned_frame_width | unsigned int | 帧的宽度（单位: pixel），按照 64 像素边界对齐 |
| aligned_frame_height | unsigned int | 帧的高度（单位: pixel），按照 16 像素边界对齐 |
| y_stride | unsigned int | Y 分量的跨度大小（单位: byte），包含了对齐要求 |
| cbcr_stride | unsigned int | Cb 和 Cr 分量的跨度大小（单位: byte），包含了对齐要求。Cb和Cr分量始终使用相同的跨度，因此它们共享相同的值 |
| y_size | unsigned int | Y 分量的 DMA 缓冲区大小（单位: byte） |
| cbcr_size | unsigned int | Cb 和 Cr 分量的 DMA 缓冲区大小（单位: byte）。Cb和Cr分量始终使用相同的大小，因此它们共享相同的值 |
| total_size | unsigned int | 帧缓冲区 DMA 缓冲区的总大小，包括所有分量的大小、对齐和填充字节 |
| image_format | BmJpuImageFormat | 帧的图像格式，可选项请参考 **BmJpuImageFormat** 定义 |

## BmJpuRawFrame

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| framebuffer | BmJpuFramebuffer* | 在解码时，指向包含解码后的原始帧的帧缓冲区。在编码时，指向包含要编码的原始帧的帧缓冲区 |
| context | void* | 用户定义的指针。库不会修改此值。该指针和相应的编码帧中的context指向相同的地址，库会将它们传递给用户。使用方法由用户决定，例如：可以用于标识与此编码帧关联的原始帧 |
| pts | uint64_t | 用户定义的时间戳（PTS - Presentation Time Stamp）。通常用于关联原始/编码帧的时间戳信息。库只是将其传递给关联的编码帧，不会实际更改其值 |
| dts | uint64_t | 用户定义的时间戳（DTS - Decoding Time Stamp）。通常用于关联原始/编码帧的时间戳信息。库只是将其传递给关联的编码帧，不会实际更改其值 |

# jpeg Decode 结构体

* BmJpuJPEGDecInfo
* BmJpuJPEGDecoder
* BmJpuDecOpenParams
* BmJpuDecInitialInfo
* BmJpuDecReturnCodes

## BmJpuJPEGDecInfo

* JPU帧缓冲区的宽度和高度与内部边界对齐。
* 帧aligned_frame由实际图像像素actual_frame和额外的填充像素组成。

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| aligned_frame_width | unsigned int | 对齐后的宽度，包括额外的填充像素，已对齐到内部边界 |
| aligned_frame_height | unsigned int | 对齐后的高度，包括额外的填充像素，已对齐到内部边界 |
| actual_frame_width | unsigned int | 实际帧宽度，不包括额外的填充像素 |
| actual_frame_height | unsigned int | 实际帧高度，不包括额外的填充像素 |
| y_stride | unsigned int | Y分量的跨度（每行占用的字节数） |
| cbcr_stride | unsigned int | Cr和Cb分量的跨度，通常与Y分量相同。Cb和Cr的跨度经常是相同的 |
| y_size | unsigned int | Y分量在帧缓冲区中的大小（单位: byte） |
| cbcr_size | unsigned int | Cr和Cb分量在帧缓冲区中的大小（单位: byte） |
| y_offset | unsigned int | Y分量在帧缓冲区中的偏移量（单位: byte） |
| cb_offset | unsigned int | Cr分量在帧缓冲区中的偏移量（单位: byte） |
| cr_offset | unsigned int | Cb分量在帧缓冲区中的偏移量（单位: byte） |
| framebuffer | BmJpuFramebuffer* | 包含解码后的帧像素数据的指针和相关信息 |
| image_format | BmJpuImageFormat | 解码后的帧的图像格式 |

# BmJpuJPEGDecoder

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| decoder | BmJpuDecoder* | 指向内部JPEG解码器的指针 |
| bitstream_buffer | bm_device_mem_t* | 码流缓冲区的指针，用于存储JPEG码流数据。**bm_device_mem_t: bmlib内存描述符** |
| bitstream_buffer_size | size_t | 码流缓冲区的大小 |
| bitstream_buffer_alignment | unsigned int | 码流缓冲区的内存对齐要求（单位: byte） |
| initial_info | BmJpuDecInitialInfo | 包含JPEG解码器的初始化信息 |
| framebuffers | BmJpuFramebuffer* | 记录解码器中帧缓冲区中各分量的地址偏移及大小 |
| framebuffer_addrs | bm_jpu_phys_addr_t* | 存储解码器中帧缓冲区的设备内存对应的物理地址，由 bmlib 分配 |
| framebuffer_size | size_t | 记录解码器中帧缓冲区的总内存大小（各缓冲区大小相同） |
| num_framebuffers | unsigned int | 解码器申请的帧缓冲区总帧数 |
| num_extra_framebuffers | unsigned int | 解码需要的帧缓冲区额外帧数，通常为 0，暂未使用 |
| calculated_sizes | BmJpuFramebufferSizes | 记录对齐后的帧缓冲区大小信息 |
| raw_frame | BmJpuRawFrame | 表示原始帧数据，用于存储图像的原始数据和时间戳 |
| device_index | int | 设备索引，标识使用的解码设备的索引 |
| opaque | void* | 用户自定义数据 |
| rotationEnable | int | 是否启用图像旋转。0 表示不旋转，1 表示旋转 |
| rotationAngle | BmJpuRotateAngle | 旋转角度。可选项请参考 **BmJpuRotateAngle** 定义 |
| mirrorEnable | int | 是否启用图像镜像。0 表示不镜像，1 表示镜像 |
| mirrorDirection | BmJpuMirrorDirection | 镜像方向。可选项请参考 **BmJpuMirrorDirection** 定义 |
| framebuffer_recycle | bool | 表示是否开启framebuffer_recycle模式 |
| bitstream_from_user | bool | 表示码流缓冲区的设备内存是否由外部分配 |
| framebuffer_from_user | bool | 表示帧缓冲区的设备内存是否由外部分配 |

# BmJpuDecOpenParams

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| min_frame_width | unsigned int | 解码器能够处理的最小宽度（单位: pixel），设为0表示无限制 |
| min_frame_height | unsigned int | 解码器能够处理的最小高度（单位: pixel），设为0表示无限制 |
| max_frame_width | unsigned int | 解码器能够处理的最大宽度（单位: pixel），设为0表示无限制 |
| max_frame_height | unsigned int | 解码器能够处理的最大高度（单位: pixel），设为0表示无限制 |
| color_format | BmJpuColorFormat | 解码器输出的YUV格式，**注意：BM1684/BM1684X上不支持该设置** |
| chroma_interleave | BmJpuChromaFormat | 色度分量存储方式，可选项请参考 **BmJpuChromaFormat** 定义 |
| scale_ratio | unsigned int | 缩放比例，用于指定解码输出的缩放级别。0 表示不进行缩放，n (取值1-3) 表示等比缩放为 2^n 倍 |
| bs_buffer_size | size_t | 用于码流的 DMA 缓冲区大小，这里记录了存储输入图片需要的字节大小 |
| buffer | uint8_t* | 码流缓冲区的指针。仅在 Windows 环境下使用，在其他环境下已弃用，不建议使用 |
| device_index | int | 设备索引 |
| rotationEnable | int | 是否启用图像旋转。0 表示不旋转，1 表示旋转 |
| rotationAngle | BmJpuRotateAngle | 旋转角度。可选项请参考 **BmJpuRotateAngle** 定义 |
| mirrorEnable | int | 是否启用图像镜像。0 表示不镜像，1 表示镜像 |
| mirrorDirection | BmJpuMirrorDirection | 镜像方向。可选项请参考 **BmJpuMirrorDirection** 定义 |
| roiEnable | int | 是否启用感兴趣区域（ROI） |
| roiWidth | int | ROI 的宽度 |
| roiHeight | int | ROI 的高度 |
| roiOffsetX | int | ROI 相对图像左上角的水平偏移量 |
| roiOffsetY | int | ROI 相对图像左上角的垂直偏移量 |
| framebuffer_recycle | bool | 是否启用framebuffer_recycle模式。如果开启recycle模式，则解码器会使用固定大小的帧缓冲区，当输入码流的分辨率或格式切换时，不会重新申请设备内存。此时，帧缓冲区的大小由用户指定 |
| framebuffer_size | size_t | 用户指定的帧缓冲区大小，*framebuffer_recycle = 1* 或 *framebuffer_from_user = 1* 时生效，生效时要求该值大于0 |
| bitstream_from_user | bool | 是否由外部分配码流缓冲区设备内存 |
| bs_buffer_phys_addr | bm_jpu_phys_addr_t | 用户指定的码流缓冲区的设备内存的物理地址，*bitstream_from_user = 1* 时生效 |
| framebuffer_from_user | bool | 是否由外部分配帧缓冲区设备内存 |
| framebuffer_num | int | 用户指定的帧缓冲区个数，*framebuffer_from_user = 1* 时生效，默认为1 |
| framebuffer_phys_addrs | bm_jpu_phys_addr_t* | 用户指定的帧缓冲区的设备内存的物理地址，*framebuffer_from_user = 1* 时生效，以数组的形式传入，个数由 *framebuffer_num* 指定 |
| timeout | int | 解码超时时间，默认为2s |
| timeout_count | int | 解码超时重试次数，默认为5 |

# BmJpuDecInitialInfo

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| frame_height | unsigned int | 帧的高度（单位: pixel）。请注意，这些值不一定对齐到 16 像素边界（JPU 帧缓冲区对齐要求）。这些是实际像素内容的宽度和高度。如果需要对齐，可能会在帧的右侧有填充列和在帧的下方有填充行 |
| frame_width | unsigned int | 帧的宽度（单位: pixel）。请注意，这些值不一定对齐到 16 像素边界（JPU 帧缓冲区对齐要求）。这些是实际像素内容的宽度和高度。如果需要对齐，可能会在帧的右侧有填充列和在帧的下方有填充行 |
| min_num_required_framebuffers | unsigned int | 解码需要的缓冲区最小个数，调用者必须向解码器注册至少该数量的帧缓冲区 |
| image_format | BmJpuImageFormat | 解码后帧的图像格式。可选项请参考 **BmJpuImageFormat** 定义 |
| framebuffer_alignment | unsigned int | 帧缓冲区的内存对齐要求（单位: byte） |
| roiFrameHeight | int | 感兴趣区域 (ROI) 帧的高度（单位: pixel） |
| roiFrameWidth | int | 感兴趣区域 (ROI) 帧的宽度（单位: pixel） |

# BmJpuDecReturnCodes

解码器返回代码。除BM_JPU_DEC_RETURN_CODE_OK外，这些都应被视为错误，返回时应关闭解码器。

| 错误码 | 返回值 | 描述 |
|--------|--------|------|
| BM_JPU_DEC_RETURN_CODE_OK | 0 | 操作成功完成 |
| BM_JPU_DEC_RETURN_CODE_ERROR | 1 | 通用错误码，用于当其他错误码无法匹配错误时的情况 |
| BM_JPU_DEC_RETURN_CODE_INVALID_PARAMS | 2 | 输入参数无效 |
| BM_JPU_DEC_RETURN_CODE_INVALID_HANDLE | 3 | JPU 解码器句柄无效。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_DEC_RETURN_CODE_INVALID_FRAMEBUFFER | 4 | 帧缓冲区信息无效。通常发生在 *bm_jpu_jpeg_dec_get_info()* 函数中获取的 **BmJpuFramebuffer** 结构包含无效值的情况 |
| BM_JPU_DEC_RETURN_CODE_INSUFFICIENT_FRAMEBUFFERS | 5 | 使用已注册给解码器的帧缓冲区解码失败，因为未提供足够大小的帧缓冲区 |
| BM_JPU_DEC_RETURN_CODE_INVALID_STRIDE | 6 | 某个跨度值（例如帧缓冲区的Y跨度值）无效 |
| BM_JPU_DEC_RETURN_CODE_WRONG_CALL_SEQUENCE | 7 | 在不适当的时间调用函数。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_DEC_RETURN_CODE_TIMEOUT | 8 | 操作超时 |
| BM_JPU_DEC_RETURN_CODE_ALREADY_CALLED | 9 | 调用了一个只应在解码会话的持续时间内调用一次的函数。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_DEC_RETURN_ALLOC_MEM_ERROR | 10 | 分配内存失败 |
| BM_JPU_DEC_RETURN_OVER_LIMITED | 11 | 超过解码分辨率限制 |

# JPEG Decode API

* bm_jpu_dec_load
* bm_jpu_jpeg_dec_open
* bm_jpu_jpeg_dec_decode
* bm_jpu_jpeg_dec_get_info
* bm_jpu_jpeg_dec_frame_finished
* bm_jpu_jpeg_dec_close
* bm_jpu_dec_unload
* bm_jpu_calc_framebuffer_sizes
* bm_jpu_dec_error_string
* bm_jpu_dec_get_bm_handle
* bm_jpu_jpeg_dec_flush

## bm_jpu_dec_load

**功能和说明**

* 根据传入的设备ID打开指定的解码设备节点，可以通过 bmlib 管理内存分配。

**函数名**

`BmJpuDecReturnCodes bm_jpu_dec_load(int device_index)`

**参数说明**

* `int device_index` 解码设备ID

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_jpeg_dec_open

**功能和说明**

* 初始化一个JPEG解码器实例
* 分配额外的帧缓冲区，如果需要的话（例如，用于快速解码多个JPEG图像或者保留解码后的DMA缓冲区）
* 分配一个码流缓冲区，用于存储JPEG数据以供解码器使用
* 调用 `bm_jpu_dec_open` 来实际打开解码器并传入必要的回调和参数
* 如果在任何步骤中出现错误，函数将清理已分配的资源并返回相应的错误码

**函数名**

`BmJpuDecReturnCodes bm_jpu_jpeg_dec_open(BmJpuJPEGDecoder **jpeg_decoder,BmJpuDecOpenParams *open_params, unsigned int num_extra_framebuffers)`

**参数说明**

* `BmJpuJPEGDecoder **jpeg_decoder` 指向解码器的二级指针，在接口内部完成初始化，返回给用户一个解码器实例
* `BmJpuDecOpenParams *open_params` 指向解码参数的指针，该结构体包含打开解码器时所需的参数，如设备索引、解码帧配置参数等
* `unsigned int num_extra_framebuffers` 指示函数分配额外帧缓冲区的数量。这些额外的帧缓冲区用于解码多个JPEG图像或在其他地方保留解码帧的DMA缓冲区

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_jpeg_dec_decode

**功能和说明**

* 解码JPEG数据
* 设置输入JPEG数据块及其大小
* 注意，这个解码器只支持基线（Baseline）JPEG数据，不支持渐进式（Progressive）编码

**函数名**

`BmJpuDecReturnCodes bm_jpu_jpeg_dec_decode(BmJpuJPEGDecoder *jpeg_decoder, uint8_t const *jpeg_data, size_t const jpeg_data_size, int timeout, int timeout_count)`

**参数说明**

* `BmJpuJPEGDecoder *jpeg_decoder` 指向JPEG解码器实例的指针
* `uint8_t const *jpeg_data` 待解码的图像数据
* `size_t const jpeg_data_size` 待解码的图像数据大小，单位: byte
* `int timeout` 解码超时时间
* `int timeout_count` 解码超时重试次数

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_jpeg_dec_get_info

**功能和说明**

* 从解码器获取解码信息

**函数名**

`void bm_jpu_jpeg_dec_get_info(BmJpuJPEGDecoder *jpeg_decoder, BmJpuJPEGDecInfo *info)`

**参数说明**

* `BmJpuJPEGDecoder *jpeg_decoder` 指向JPEG解码器实例的指针
* `BmJpuJPEGDecInfo *info` 用来存储解码图像的详细信息的结构体

**返回值**

* 无

## bm_jpu_jpeg_dec_frame_finished

**功能和说明**

* 通知解码器一个解码帧已经被处理完毕，并且相关的资源可以被回收
* 一旦用户处理完一帧，就必须始终调用此函数，否则JPU无法回收此帧缓冲区，如果解码器内部的帧缓冲区均被占用，将无法继续解码

**函数名**

`BmJpuDecReturnCodes bm_jpu_jpeg_dec_frame_finished(BmJpuJPEGDecoder *jpeg_decoder, BmJpuFramebuffer *framebuffer)`

**参数说明**

* `BmJpuJPEGDecoder *jpeg_decoder` 指向JPEG解码器实例的指针
* `BmJpuFramebuffer *framebuffer` 包含了已解码的图像数据的帧缓冲区

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_jpeg_dec_close

**功能和说明**

* 用于关闭JPEG解码器实例，并释放资源

**函数名**

`BmJpuDecReturnCodes bm_jpu_jpeg_dec_close(BmJpuJPEGDecoder *jpeg_decoder)`

**参数说明**

* `BmJpuJPEGDecoder *jpeg_decoder` 指向JPEG解码器实例的指针

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_dec_unload

**功能和说明**

* 释放指定的解码设备节点

**函数名**

`BmJpuDecReturnCodes bm_jpu_dec_unload(int device_index)`

**参数说明**

* `int device_index` 解码设备ID

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_calc_framebuffer_sizes

**功能和说明**

* 用于计算存放解码数据的帧缓冲区的各分量对齐后的跨度、大小等信息

**函数名**

`BmJpuDecReturnCodes bm_jpu_calc_framebuffer_sizes(unsigned int frame_width, unsigned int frame_height, unsigned int framebuffer_alignment, BmJpuImageFormat image_format, BmJpuFramebufferSizes *calculated_sizes)`

**参数说明**

* `unsigned int frame_width` 图像实际宽度
* `unsigned int frame_height` 图像实际高度
* `unsigned int framebuffer_alignment` 解码帧缓冲区内存对齐要求，设为0或1表示不对齐，单位: byte
* `BmJpuImageFormat image_format` 图像格式
* `BmJpuFramebufferSizes *calculated_sizes` 计算后的帧缓冲区大小信息

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_dec_error_string

**功能和说明**

* 返回解码错误码的具体描述

**函数名**

`char const * bm_jpu_dec_error_string(BmJpuDecReturnCodes code)`

**参数说明**

* `BmJpuDecReturnCodes code` 解码错误码

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_dec_get_bm_handle

**功能和说明**

* 获取该解码设备上bmlib的句柄

**函数名**

`bm_handle_t bm_jpu_dec_get_bm_handle(int device_index)`

**参数说明**

* `int device_index` 解码设备ID

**返回值**

* 返回值为0表示成功，其他值表示失败

## bm_jpu_jpeg_dec_flush

**功能和说明**

* 刷新解码器帧缓冲区状态，解码器内部所有帧缓冲区将解除占用，可用于后续解码

# 函数名

`BmJpuDecReturnCodes bm_jpu_jpeg_dec_flush(BmJpuJPEGDecoder *jpeg_decoder)`

## 参数说明

* `BmJpuJPEGDecoder *jpeg_decoder` 指向JPEG解码器实例的指针。

## 返回值

* 返回值为0表示成功，其他值表示失败。

# JPEG Encode 结构体

* BmJpuJPEGEncParams
* BmJpuJPEGEncoder
* BmJpuEncInitialInfo
* BmJpuEncReturnCodes

## BmJpuJPEGEncParams

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| frame_width | unsigned int | 输入帧的宽度，这是实际大小，这些大小不能为零。如果需要，它们将在内部对齐 |
| frame_height | unsigned int | 输入帧的高度，这是实际大小，这些大小不能为零。如果需要，它们将在内部对齐 |
| quality_factor | unsigned int | JPEG编码的图像质量因子。1表示最佳压缩，100表示最佳质量 |
| image_format | BmJpuImageFormat | 输入帧的图像格式 |
| acquire_output_buffer | BmJpuEncAcquireOutputBuffer | 获取编码码流输出 buffer 的回调函数，具体定义请参考 **BmJpuEncAcquireOutputBuffer** |
| finish_output_buffer | BmJpuEncFinishOutputBuffer | 释放上述 buffer 的回调函数，具体定义请参考 **BmJpuEncFinishOutputBuffer** |
| write_output_data | BmJpuWriteOutputData | 指定编码码流输出方式的回调函数，如：写入文件或写入指定的内存地址。具体定义请参考 **BmJpuWriteOutputData**。使用此函数将不会调用 `acquire_output_buffer` 和 `finish_output_buffer` 函数 |
| output_buffer_context | void* | 保存输出数据的上下文，将传递给 `acquire_output_buffer`、`finish_output_buffer` 和 `write_output_data` 函数 |
| rotationEnable | int | 是否启用图像旋转。0 表示不旋转，1 表示旋转 |
| rotationAngle | BmJpuRotateAngle | 旋转角度。可选项请参考 **BmJpuRotateAngle** 定义 |
| mirrorEnable | int | 是否启用图像镜像。0 表示不镜像，1 表示镜像 |
| mirrorDirection | BmJpuMirrorDirection | 镜像方向。可选项请参考 **BmJpuMirrorDirection** 定义 |
| bs_in_device | int | 表示编码的码流数据输出到设备内存还是系统内存，0表示输出到系统内存，1表示输出到设备内存 |
| timeout | int | 编码超时时间，默认为2s |
| timeout_count | int | 编码超时重试次数，默认为5 |
| bs_buffer_phys_addr | bm_jpu_phys_addr_t | （可选）用户外部分配的码流缓冲区的设备内存的物理地址 |
| bs_buffer_size | int | （可选）用户外部分配的码流缓冲区的大小 |

## BmJpuJPEGEncoder

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| encoder | BmJpuEncoder * | 指向内部JPEG编码器的指针 |
| bitstream_buffer_addr | bm_jpu_phys_addr_t | 码流缓冲区的设备内存的物理地址 |
| bitstream_buffer_size | size_t | 码流缓冲区的大小，单位: byte |
| bitstream_buffer_alignment | unsigned int | 码流缓冲区的对齐要求，单位: byte |
| initial_info | BmJpuEncInitialInfo | 编码器的初始化信息 |
| frame_width | unsigned int | 输入帧的宽度，单位: pixel |
| frame_height | unsigned int | 输入帧的高度，单位: pixel |
| calculated_sizes | BmJpuFramebufferSizes | 由输入帧计算得到的帧缓冲区大小信息 |
| quality_factor | unsigned int | JPEG 编码的质量因子。1 表示最佳压缩质量，100 表示最佳图像质量 |
| image_format | BmJpuImageFormat | 输入帧的图像格式 |
| device_index | int | 设备索引 |
| rotationEnable | int | 是否启用图像旋转。0 表示不旋转，1 表示旋转 |
| rotationAngle | BmJpuRotateAngle | 旋转角度。可选项请参考 BmJpuRotateAngle 定义 |
| mirrorEnable | int | 是否启用图像镜像。0 表示不镜像，1 表示镜像 |
| mirrorDirection | BmJpuMirrorDirection | 镜像方向。可选项请参考 BmJpuMirrorDirection 定义 |
| bitstream_from_user | bool | 表示码流缓冲区的设备内存是否由外部分配 |

## BmJpuEncInitialInfo

| 成员变量 | 类型 | 描述 |
|---------|------|------|
| min_num_required_framebuffers | unsigned int | 编码需要的缓冲区最小个数，调用者必须向编码器注册至少该数量的帧缓冲区 |
| framebuffer_alignment | unsigned int | 帧缓冲区的内存对齐要求（单位: byte） |

## BmJpuEncReturnCodes

* 编码器返回代码。除BM_JPU_ENC_RETURN_CODE_OK外，这些都应被视为错误，返回时应关闭编码器。

| 错误码 | 返回值 | 描述 |
|--------|--------|------|
| BM_JPU_ENC_RETURN_CODE_OK | 0 | 操作成功完成 |
| BM_JPU_ENC_RETURN_CODE_ERROR | 1 | 通用错误码，用于当其他错误码无法匹配错误时的情况 |
| BM_JPU_ENC_RETURN_CODE_INVALID_PARAMS | 2 | 输入参数无效 |
| BM_JPU_ENC_RETURN_CODE_INVALID_HANDLE | 3 | JPU 编码器句柄无效。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_ENC_RETURN_CODE_INVALID_FRAMEBUFFER | 4 | 帧缓冲区信息无效。通常发生在传递给 *bm_jpu_jpeg_enc_encode* 函数的 **BmJpuFramebuffer** 结构包含无效值的情况 |
| BM_JPU_ENC_RETURN_CODE_INSUFFICIENT_FRAMEBUFFERS | 5 | 编码时使用的帧缓冲区无效。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_ENC_RETURN_CODE_INVALID_STRIDE | 6 | 某个跨度值（例如帧缓冲区的Y跨度值）无效 |
| BM_JPU_ENC_RETURN_CODE_WRONG_CALL_SEQUENCE | 7 | 在不适当的时间调用函数。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_ENC_RETURN_CODE_TIMEOUT | 8 | 操作超时 |
| BM_JPU_ENC_RETURN_CODE_ALREADY_CALLED | 9 | 调用了一个只应在编码会话的持续时间内调用一次的函数。这是一个内部错误，很可能是JPU库中的BUG，请报告此类错误 |
| BM_JPU_ENC_RETURN_CODE_WRITE_CALLBACK_FAILED | 10 | 编码输出回调函数 **BmJpuWriteOutputData** 调用失败 |
| BM_JPU_ENC_RETURN_ALLOC_MEM_ERROR | 11 | 分配内存失败 |
| BM_JPU_ENC_BYTE_ERROR | 12 | 编码数据异常 |
| BM_JPU_ENC_RETURN_BS_BUFFER_FULL | 13 | 码流缓冲区已满 |

# JPEG Encode API

* bm_jpu_enc_load
* bm_jpu_jpeg_enc_open
* bm_jpu_jpeg_enc_encode
* bm_jpu_jpeg_enc_close
* bm_jpu_enc_unload
* bm_jpu_enc_error_string
* bm_jpu_enc_get_bm_handle

## bm_jpu_enc_load

### 功能和说明

* 根据传入的 设备ID 打开指定的编码设备节点，可以通过 bmlib 管理内存分配。

### 函数名

`BmJpuEncReturnCodes bm_jpu_enc_load(int device_index)`

### 参数说明

* `int device_index` 编码设备ID。

### 返回值

* 返回值为0表示成功，其他值表示失败。

## bm_jpu_jpeg_enc_open

### 功能和说明

* 创建一个JPEG编码器实例，并申请指定大小的码流缓冲区。

### 函数名

`BmJpuEncReturnCodes bm_jpu_jpeg_enc_open(BmJpuJPEGEncoder **jpeg_encoder, bm_jpu_phys_addr_t bs_buffer_phys_addr, int bs_buffer_size, int device_index)`

### 参数说明

* `BmJpuJPEGEncoder **jpeg_encoder` 指向编码器的二级指针，在接口内部完成初始化，返回给用户一个编码器实例。
* `bm_jpu_phys_addr_t bs_buffer_phys_addr` 用户指定的码流缓冲区设备内存物理地址，0表示由编码器内部分配。
* `int bs_buffer_size` 码流缓冲区的大小，0表示默认大小（5MB）。
* `int device_index` 编码设备ID

### 返回值

* 返回值为0表示成功，其他值表示失败。

## bm_jpu_jpeg_enc_encode

### 功能和说明

* 编码原始输入帧
* JPU编码器仅生成baseline JPEG数据，不支持渐进式编码。

### 函数名

`BmJpuEncReturnCodes bm_jpu_jpeg_enc_encode(BmJpuJPEGEncoder *jpeg_encoder, BmJpuFramebuffer const *framebuffer, BmJpuJPEGEncParams const *params, void **acquired_handle, size_t *output_buffer_size)`

### 参数说明

* `BmJpuJPEGEncoder *jpeg_encoder` 指向 `BmJpuJPEGEncoder` 结构体的指针，它包含了与JPEG编码相关的设置和状态信息。
* `mJpuFramebuffer const *framebuffer` 包含要编码的原始输入像素。它的跨度（stride）和偏移（offset）值必须有效，并且其 dma_buffer 指针必须指向包含像素数据的 DMA 缓冲区。
* `BmJpuJPEGEncParams const *params` 包含了JPEG编码的参数，如图像尺寸、质量因子等, params必须填充有效的数值；帧的宽度和高度不能为零。
* `void **acquired_handle` 用于返回获取编码后的图像数据的句柄。
* `size_t *output_buffer_size` 用于返回编码后的图像数据的大小。

### 返回值

* 返回值为0表示成功，其他值表示失败。

## bm_jpu_jpeg_enc_close

### 功能和说明

* 关闭编码器，释放资源。
* 获取与 jpeg_encoder 相关的设备句柄 handle，通常用于与硬件设备交互。
* 如果 jpeg_encoder 的 bitstream_buffer 不为空（即已分配了码流缓冲区），且设备内存由编码器内部申请，它会释放该码流缓冲区的设备内存，并释放 jpeg_encoder->bitstream_buffer 占用的内存。
* 最后释放 jpeg_encoder 结构体本身的内存，并将 jpeg_encoder 指针设置为 NULL。

### 函数名

`BmJpuEncReturnCodes bm_jpu_jpeg_enc_close(BmJpuJPEGEncoder *jpeg_encoder)`

### 参数说明

* `BmJpuJPEGEncoder *jpeg_encoder` 指向JPEG编码器实例的指针。

### 返回值

* 返回值为0表示成功，其他值表示失败。

## bm_jpu_enc_unload

### 功能和说明

* 释放指定的编码设备节点。

### 函数名

`BmJpuDecReturnCodes bm_jpu_enc_unload(int device_index)`

### 参数说明

* `int device_index` 编码设备ID。

### 返回值

* 返回值为0表示成功，其他值表示失败。

## bm_jpu_enc_error_string

### 功能和说明

* 返回编码错误码的具体描述。

### 函数名

`char const * bm_jpu_enc_error_string(BmJpuEncReturnCodes code)`

### 参数说明

* `BmJpuEncReturnCodes code` 编码错误码。

## bm_jpu_enc_get_bm_handle

### 功能和说明

* 获取该编码设备上bmlib的句柄。

### 函数名

`bm_handle_t bm_jpu_enc_get_bm_handle(int device_index)`

### 参数说明

* `int device_index` 编码设备ID。

### 返回值

* 该编码设备上bmlib的句柄。

# JPEG Encode Callback

* BmJpuEncAcquireOutputBuffer
* BmJpuEncFinishOutputBuffer
* BmJpuWriteOutputData

## BmJpuEncAcquireOutputBuffer

### 功能和说明

* 用于申请编码数据的输出buffer，可根据编码器的 *bs_in_device* 配置，选择输出到设备内存还是系统内存。
* 编码完成后，数据会从编码器中的码流缓冲区拷贝到上述申请的buffer中，用户可以从 *acquired_handle* 获取输出数据。
* **BmJpuWriteOutputData** 回调函数为空时执行该操作。

### 接口实现

`typedef void* (*BmJpuEncAcquireOutputBuffer)(void *context, size_t size, void **acquired_handle)`

### 参数说明

* `void *context` 输出上下文信息，由用户在编码参数中的 **output_buffer_context** 指定。
* `size_t size` 申请buffer的大小。
* `void **acquired_handle` 用户获取输出数据的句柄，由编码接口中的 **acquired_handle** 参数指定。

### 返回值

* 无。

## BmJpuEncFinishOutputBuffer

### 功能和说明

* 用于释放 **BmJpuEncAcquireOutputBuffer** 接口申请的buffer，与上述接口配套使用。
* **BmJpuWriteOutputData** 回调函数为空时执行该操作。

### 接口实现

`typedef void (*BmJpuEncFinishOutputBuffer)(void *context, void *acquired_handle)`

### 参数说明

* `void *context` 输出上下文信息，与 **BmJpuEncAcquireOutputBuffer** 接口中的 **context** 参数相同。
* `void *acquired_handle` 需要释放的buffer，等价于 **BmJpuEncAcquireOutputBuffer** 接口中的 **\*acquired_handle** 参数值。

### 返回值

* 无。

# BmJpuWriteOutputData

## 功能和说明

* 用于用户指定编码数据输出方式的回调函数。

## 接口实现

`typedef int (*BmJpuWriteOutputData)(void *context, uint8_t const *data, uint32_t size, BmJpuEncodedFrame *encoded_frame)`

## 参数说明

* `void *context` 输出上下文信息，由用户在编码参数中的 **output_buffer_context** 指定。
* `uint8_t const *data` 编码器码流缓冲区映射后的虚拟地址，由编码器内部mmap得到。
* `uint32_t size` 编码输出码流大小。
* `BmJpuEncodedFrame *encoded_frame` 编码器内部生成的编码帧信息，用于保存PTS、DTS等信息（暂未使用）。

## 返回值

* 返回BM_SUCESS(=0)表示执行成功，否则执行失败。

# SOPHGO LIBYUV使用指南

## 简介

BM168x系列中的各种硬件模块，可以加速对图片和视频的处理。颜色转换方面，采用专用硬件加速，速度得到显著提升。

但在有些场合，也会存在一些专用硬件覆盖不到的特殊情况。此时采用经过SIMD加速优化的软件实现，成为专用硬件有力的补充。

SOPHGO增强版**libyuv**，是随同SDK一同发布的一个组件。目的是充分利用BM168x系列提供的8核A53处理器，通过软件手段为硬件的局限性提供补充。

除了libyuv提供的标准函数之外，针对Deep learning的需求，在SOPHGO增强版libyuv中，补充了27个扩展函数。

注意：这里说的是运行在BM168x系列的A53处理器上，而不是host的处理器。这从设备加速的角度是可以理解的。这样可以避免占用host的处理器。

## libyuv扩展说明

新增了如下增强Deep learning应用方面的API。

## fast_memcpy

### 功能和说明

* Processor SIMD指令实现memcpy功能。从内存区域src拷贝n个字节到内存区域dst。

### 函数名

`void* fast_memcpy(void *dst, const void *src, size_t n)`

### 参数说明

* `src` 源内存区域。
* `n` 需要拷贝的字节数。
* `dst` 目的内存区域。

### 返回值

* 返回一个指向dst的指针。

## RGB24ToI400

### 功能和说明

* 将一帧 BGR 数据转换成 BT.601 灰度数据。

### 函数名

`int RGB24ToI400(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, int width, int height)`

### 参数说明

* `src_rgb24` packed BGR 图像数据所在的内存虚地址。
* `src_stride_rgb24` 内存中每行 BGR 图像的实际跨度。
* `dst_y` 灰度图像的虚拟地址。
* `dst_stride_y` 内存中每行灰度图像的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToI400

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 灰度数据。

### 函数名

`int RAWToI400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height)`

### 参数说明

* `src_raw` packed BGR 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 BGR 图像的实际跨度。
* `dst_y` 灰度图像的虚拟地址。
* `dst_stride_y` 内存中每行灰度图像的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## I400ToRGB24

### 功能和说明

* 将一帧 BT.601 灰度数据转换成 BGR 数据。

### 函数名

`int I400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height)`

### 参数说明

* `src_y` 灰度图像的虚拟地址。
* `src_stride_y` 内存中每行灰度图像的实际跨度。
* `dst_rgb24` packed BGR 图像数据所在的内存虚地址。
* `dst_stride_rgb24` 内存中每行 BGR 图像的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## I400ToRAW

### 功能和说明

* 将一帧 BT.601 灰度数据转换成 RGB 数据。

### 函数名

`int I400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height)`

### 参数说明

* `src_y` 灰度图像的虚拟地址。
* `src_stride_y` 内存中每行灰度图像的实际跨度。
* `dst_raw` packed RGB 图像数据所在的内存虚地址。
* `dst_stride_raw` 内存中每行 RGB 图像的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J400ToRGB24

### 功能和说明

* 将一帧 BT.601 full range 灰度数据转换成 BGR 数据。

### 函数名

`int J400ToRGB24(const uint8_t* src_y, int src_stride_y, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height)`

### 参数说明

* `src_y` 灰度图像的虚拟地址。
* `src_stride_y` 内存中每行灰度图像的实际跨度。
* `dst_rgb24` packed BGR 图像数据所在的内存虚地址。
* `dst_stride_rgb24` 内存中每行 BGR 图像的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToJ400

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 full range 灰度数据。

### 函数名

`int RAWToJ400(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, int width, int height)`

### 参数说明

* `src_raw` packed RGB 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 RGB 图像的实际跨度。
* `dst_y` 灰度图像的虚拟地址。
* `dst_stride_y` 内存中每行灰度图像的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J400ToRAW

### 功能和说明

* 将一帧 BT.601 full range 灰度数据转换成 RGB 数据。

### 函数名

`int J400ToRAW(const uint8_t* src_y, int src_stride_y, uint8_t* dst_raw, int dst_stride_raw, int width, int height)`

### 参数说明

* `src_y` 灰度图像的虚拟地址。
* `src_stride_y` 内存中每行灰度图像的实际跨度。
* `dst_raw` packed RGB 图像数据所在的内存虚地址。
* `dst_stride_raw` 内存中每行 RGB 图像的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToNV12

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 limited range 的 semi-planar YCbCr 420 数据。

### 函数名

`int RAWToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height)`

### 参数说明

* `src_raw` packed RGB 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 RGB 图像的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_uv` CbCr 分量的虚拟地址。
* `dst_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RGB24ToNV12

### 功能和说明

* 将一帧 BGR 数据转换成 BT.601 limited range 的 semi-planar YCbCr 420 数据。

### 函数名

`int RGB24ToNV12(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height)`

### 参数说明

* `src_raw` packed BGR 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 BGR 图像的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_uv` CbCr 分量的虚拟地址。
* `dst_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToJ420

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 full range 的 semi-planar YCbCr 420 数据。

### 函数名

`int RAWToJ420(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_raw` packed RGB 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 RGB 图像的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J420ToRAW

### 功能和说明

* 将一帧 BT.601 full range 的 YCbCr 420 数据转换成 RGB 数据。

### 函数名

`int J420ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_raw` packed RGB 图像数据所在的内存虚地址。
* `dst_stride_raw` 内存中每行 RGB 图像数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToJ422

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 full range 的 YCbCr 422 数据。

### 函数名

`int RAWToJ422(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_raw` packed RGB 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 RGB 图像实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J422ToRAW

### 功能和说明

* 将一帧 BT.601 full range 的 YCbCr 422 数据转换成 RGB 数据。

### 函数名

`int J422ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_raw` packed RGB 图像数据所在的内存虚地址。
* `dst_stride_raw` 内存中每行 RGB 图像数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RGB24ToJ422

### 功能和说明

* 将一帧 BGR 数据转换成 BT.601 full range 的 YCbCr 422 数据。

### 函数名

`int RGB24ToJ422(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_rgb24` packed BGR 图像数据所在的内存虚地址。
* `src_stride_rgb24` 内存中每行 BGR 图像的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J422ToRGB24

### 功能和说明

* 将一帧 BT.601 full range 的 YCbCr 422 数据转换成 BGR 数据。

### 函数名

`int J422ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_rgb24` packed BGR 图像数据所在的内存虚地址。
* `dst_stride_rgb24` 内存中每行 BGR 图像数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RAWToJ444

### 功能和说明

* 将一帧 RGB 数据转换成 BT.601 full range 的 YCbCr 444 数据。

### 函数名

`int RAWToJ444(const uint8_t* src_raw, int src_stride_raw, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_raw` packed RGB 图像数据所在的内存虚地址。
* `src_stride_raw` 内存中每行 RGB 图像实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J444ToRAW

### 功能和说明

* 将一帧 BT.601 full range 的 YCbCr 444 数据转换成 RGB 数据。

### 函数名

`int J444ToRAW(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_raw, int dst_stride_raw, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_raw` packed RGB 图像数据所在的内存虚地址。
* `dst_stride_raw` 内存中每行 RGB 图像数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed RGB 的数量。
* `height` RGB 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## RGB24ToJ444

### 功能和说明

* 将一帧 BGR 数据转换成 BT.601 full range 的 YCbCr 444 数据。

### 函数名

`int RGB24ToJ444(const uint8_t* src_rgb24, int src_stride_rgb24, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_rgb24` packed BGR 图像数据所在的内存虚地址。
* `src_stride_rgb24` 内存中每行 BGR 图像实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行 BGR 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## J444ToRGB24

### 功能和说明

* 将一帧 BT.601 full range 的 YCbCr 444 数据转换成 BGR 数据。

### 函数名

`int J444ToRGB24(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_rgb24, int dst_stride_rgb24, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_rgb24` packed BGR 图像数据所在的内存虚地址。
* `dst_stride_rgb24` 内存中每行 BGR 图像数据的实际跨度。
* `width` 每行 RGB 图像数据中 packed BGR 的数量。
* `height` BGR 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

## H420ToJ420

### 功能和说明

* 将一帧 BT.709 limited range 的 YCbCr 420 数据转换成 BT.601 full range 的数据。可以在 JPEG 编码之前作预处理函数使用。

### 函数名

`int H420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

### 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行数据中 YCbCr 分量的数量。
* `height` 图像数据的有效行数。

### 返回值

* `0` 正常结束。
* `非0` 参数异常。

# I420ToJ420

## 功能和说明

* 将一帧 BT.601 limited range 的 YCbCr 420 数据转换成 BT.601 full range 的数据。可以在 JPEG 编码之前作预处理函数使用。

## 函数名

`int I420ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

## 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行数据中 YCbCr 分量的数量。
* `height` 图像数据的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# NV12ToJ420

## 功能和说明

* 将一帧 BT.601 limited range 的 semi-planar YCbCr 420 数据转换成 BT.601 full range 的数据。可以在 JPEG 编码之前作预处理函数使用。

## 函数名

`int NV12ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_uv, int src_stride_uv, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

## 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_uv` CbCr 分量的虚拟地址。
* `src_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行数据中 YCbCr 分量的数量。
* `height` 图像数据的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# NV21ToJ420

## 功能和说明

* 将一帧 BT.601 limited range 的 semi-planar YCbCr 420 数据转换成 BT.601 full range 的数据。可以在 JPEG 编码之前作预处理函数使用。

## 函数名

`int NV21ToJ420(const uint8_t* src_y, int src_stride_y, const uint8_t* src_vu, int src_stride_vu, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_u, int dst_stride_u, uint8_t* dst_v, int dst_stride_v, int width, int height)`

## 参数说明

* `src_y` Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_vu` CrCb 分量的虚拟地址。
* `src_stride_vu` 内存中每行 CrCb 分量数据的实际跨度。
* `dst_y` Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_u` Cb 分量的虚拟地址。
* `dst_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `dst_v` Cr 分量的虚拟地址。
* `dst_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `width` 每行数据中 YCbCr 分量的数量。
* `height` 图像数据的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# I444ToNV12

## 功能和说明

* 将一帧 YCbCr 444 数据转换成 semi-planar YCbCr 420 数据。可用于 full range，也可以用于 limited range 的数据。不涉及颜色空间转换，可灵活使用。

## 函数名

`int I444ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height)`

## 参数说明

* `src_y` 源图像 Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` 源图像 Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` 源图像 Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_y` 目的图像 Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_uv` 目的图像 CbCr 分量的虚拟地址。
* `dst_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `width` 每行图像数据中像素的数量。
* `height` 图像数据像素的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# I422ToNV12

## 功能和说明

* 将一帧 YCbCr 422 数据转换成 semi-planar YCbCr 420 数据。可用于 full range，也可以用于 limited range 的数据。不涉及颜色空间转换，可灵活使用。

## 函数名

`int I422ToNV12(const uint8_t* src_y, int src_stride_y, const uint8_t* src_u, int src_stride_u, const uint8_t* src_v, int src_stride_v, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height)`

## 参数说明

* `src_y` 源图像 Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `src_u` 源图像 Cb 分量的虚拟地址。
* `src_stride_u` 内存中每行 Cb 分量数据的实际跨度。
* `src_v` 源图像 Cr 分量的虚拟地址。
* `src_stride_v` 内存中每行 Cr 分量数据的实际跨度。
* `dst_y` 目的图像 Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_uv` 目的图像 CbCr 分量的虚拟地址。
* `dst_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `width` 每行图像数据中像素的数量。
* `height` 图像数据像素的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# I400ToNV12

## 功能和说明

* 将一帧 YCbCr 400 数据转换成 semi-planar YCbCr 420 数据。可用于 full range，也可以用于 limited range 的数据。不涉及颜色空间转换，可灵活使用。

## 函数名

`int I400ToNV12(const uint8_t* src_y, int src_stride_y, uint8_t* dst_y, int dst_stride_y, uint8_t* dst_uv, int dst_stride_uv, int width, int height)`

## 参数说明

* `src_y` 源图像 Y 分量的虚拟地址。
* `src_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_y` 目的图像 Y 分量的虚拟地址。
* `dst_stride_y` 内存中每行 Y 分量数据的实际跨度。
* `dst_uv` 目的图像 CbCr 分量的虚拟地址。
* `dst_stride_uv` 内存中每行 CbCr 分量数据的实际跨度。
* `width` 每行图像数据中像素的数量。
* `height` 图像数据像素的有效行数。

## 返回值

* `0` 正常结束。
* `非0` 参数异常。

# 安装sophon-mw

sophon-mw在不同的Linux发行版上提供不同类型的安装方式。请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。
以下描述中"|ver|"仅为示例，视当前实际安装版本会有变化。

下文中$arch $system根据实际架构进行配置:
- 主机为x86 处理器的，$arch为amd64, $system为x86_64
- 主机为arm64或飞腾处理器的，$arch为arm64, $system为aarch64
- 主机为sg2042处理器的, $arch为riscv64, $system为riscv64

**如果使用Debian/Ubuntu系统：**

sophon-mw安装包由四个文件构成：
- sophon-mw-sophon-ffmpeg\_|ver|\_$arch.deb
- sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.deb
- sophon-mw-sophon-opencv\_|ver|\_$arch.deb
- sophon-mw-sophon-opencv-dev\_|ver|\_$arch.deb

**如果使用CentOS系统：**

sophon-mw安装包由四个文件构成：
- sophon-mw-sophon-ffmpeg\_|ver|\_$arch.rpm
- sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.rpm
- sophon-mw-sophon-opencv-abi0\_|ver|\_$arch.rpm
- sophon-mw-sophon-opencv-abi0-dev\_|ver|\_$arch.rpm

**如果使用Fedora系统：**

sophon-mw安装包由四个文件构成：
- sophon-mw-sophon-ffmpeg\_|ver|\_$arch.rpm
- sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.rpm
- sophon-mw-sophon-opencv\_|ver|\_$arch.rpm
- sophon-mw-sophon-opencv-dev\_|ver|\_$arch.rpm

其中：

sophon-ffmpeg/sophon-opencv包含了ffmpeg/opencv运行时环境（库文件、工具等）；sophon-ffmpeg-dev/sophon-opencv-dev包含了开发环境（头文件、pkgconfig、cmake等）。如果只是在部署环境上安装，则不需要安装sophon-ffmpeg-dev/sophon-opencv-dev。

sophon-mw-sophon-ffmpeg依赖sophon-libsophon包，而sophon-mw-sophon-opencv依赖sophon-mw-sophon-ffmpeg，因此在安装次序上必须先安装libsophon,然后sophon-mw-sophon-ffmpeg,最后安装sophon-mw-sophon-opencv。

CentOS系统中使用的libstdc++库使用旧版本ABI接口，请使用sophon-mw-sophon-opencv-abi0\_|ver|\_$arch.rpm安装sophon-mw-sophon-opencv。

安装步骤如下：

```
安装libsophon依赖库(参考《LIBSOPHON使用手册》)
安装sophon-mw

**如果使用Debian/Ubuntu系统：**

sudo dpkg -i sophon-mw-sophon-ffmpeg\_|ver|\_$arch.deb sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.deb
sudo dpkg -i sophon-mw-sophon-opencv\_|ver|\_$arch.deb sophon-mw-sophon-opencv-dev\_|ver|\_$arch.deb

**如果使用CentOS系统：**

sudo rpm -ivh sophon-mw-sophon-ffmpeg\_|ver|\_$arch.rpm sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.rpm
sudo rpm -ivh sophon-mw-sophon-opencv-abi0\_|ver|\_$arch.rpm sophon-mw-sophon-opencv-abi0-dev\_|ver|\_$arch.rpm

**如果使用Fedora系统，请在安装之前卸载已安装的包：**

已安装包目录可以通过此命令列举：
dnf list installed | grep sophon-ffmpeg

然后卸载：
sudo rpm -e sophon-mw-sophon-opencv-dev
sudo rpm -e sophon-mw-sophon-opencv
sudo rpm -e sophon-mw-sophon-ffmpeg-dev
sudo rpm -e sophon-mw-sophon-ffmpeg

再重新安装：
sudo rpm -ivh sophon-mw-sophon-ffmpeg\_|ver|\_$arch.rpm sophon-mw-sophon-ffmpeg-dev\_|ver|\_$arch.rpm
sudo rpm -ivh sophon-mw-sophon-opencv\_|ver|\_$arch.rpm sophon-mw-sophon-opencv-dev\_|ver|\_$arch.rpm

在终端执行如下命令，或者logout再login当前用户后即可使用安装的工具：
source /etc/profile

注意：位于SOC模式时，系统已经预装了：
sophon-mw-soc-sophon-ffmpeg
sophon-mw-soc-sophon-opencv

只需要按照上述步骤安装：
sophon-mw-soc-sophon-ffmpeg-dev\_|ver|\_arm64.deb
sophon-mw-soc-sophon-opencv-dev\_|ver|\_arm64.deb
```

安装位置为：

```
/opt/sophon/
├── libsophon-|ver|
├── libsophon-current -> /opt/sophon/libsophon_|ver|
├── sophon-ffmpeg_|ver|
│   ├── bin
│   ├── data
│   ├── include
│   ├── lib
│   │   ├── cmake
│   │   └── pkgconfig
│   └── share
├── sophon-ffmpeg-latest -> /opt/sophon/sophon-ffmpeg_|ver|
├── sophon-opencv_|ver|
│   ├── bin
│   ├── data
│   ├── include
│   ├── lib
│   │   ├── cmake
│   │   │   └── opencv4
│   │   └── pkgconfig
│   ├── opencv-python
│   ├── share
│   └── test
└── sophon-opencv-latest -> /opt/sophon/sophon-opencv_|ver|
```

deb包安装方式并不允许您安装同一个包的多个不同版本，但您可能用其它方式在/opt/sophon下放置了若干不同版本。
在使用deb包安装时，/opt/sophon/sophon-ffmpeg-latest和/opt/sophon/sophon-opencv-latest会指向最后安装的那个版本。在卸载后，它会指向余下的最新版本（如果有的话）。

其中include和lib/cmake lib/pkgconfig目录，分别由sophon-mw-sophon-ffmpeg-dev和sophon-mw-sophon-opencv-dev包安装产生

## 卸载方式

**如果使用Debian/Ubuntu系统：**

```
sudo apt remove sophon-mw-sophon-opencv-dev sophon-mw-sophon-opencv
sudo apt remove sophon-mw-sophon-ffmpeg-dev sophon-mw-sophon-ffmpeg
或者:
sudo dpkg -r sophon-mw-sophon-opencv-dev
sudo dpkg -r sophon-mw-sophon-opencv
sudo dpkg -r sophon-mw-sophon-ffmpeg-dev
sudo dpkg -r sophon-mw-sophon-ffmpeg
```

**如果使用CentOS系统：**

```
sudo rpm -e sophon-mw-sophon-opencv-abi0-dev
sudo rpm -e sophon-mw-sophon-opencv-abi0
sudo rpm -e sophon-mw-sophon-ffmpeg-dev
sudo rpm -e sophon-mw-sophon-ffmpeg
```

**如果使用Fedora系统：**

```
sudo rpm -e sophon-mw-sophon-opencv-dev
sudo rpm -e sophon-mw-sophon-opencv
sudo rpm -e sophon-mw-sophon-ffmpeg-dev
sudo rpm -e sophon-mw-sophon-ffmpeg
```

# 如果使用其它Linux系统：

安装包由一个文件构成：
- sophon-mw_|ver|_$system.tar.gz

可以通过如下步骤安装：

先按照《LIBSOPHON使用手册》安装好libsophon包，然后：

```bash
tar -xzvf sophon-mw_|ver|_$system.tar.gz
sudo cp -r sophon-mw_|ver|_$system/* /
sudo ln -s /opt/sophon/sophon-ffmpeg_|ver| /opt/sophon/sophon-ffmpeg-latest
sudo ln -s /opt/sophon/sophon-opencv_|ver| /opt/sophon/sophon-opencv-latest
sudo ln -s /opt/sophon/sophon-sample_|ver| /opt/sophon/sophon-sample-latest
sudo sed -i "s/usr\\/local/opt\\/sophon\\/sophon-ffmpeg-latest/g" /opt/sophon/sophon-ffmpeg-latest/lib/pkgconfig/*.pc
sudo sed -i "s/^prefix=.*$/prefix=\\/opt\\/sophon\\/sophon-opencv-latest/g" /opt/sophon/sophon-opencv-latest/lib/pkgconfig/opencv4.pc
```

注意：以上安装步骤的命令，如果直接粘贴存在问题，可以手动敲打。

最后，安装bz2 libc6 libgcc依赖库（这部分需要根据操作系统不同，选择对应的安装包，这里不统一介绍）

## 配置工作

```bash
添加库和可执行文件路径：
sudo cp /opt/sophon/sophon-ffmpeg-latest/data/01_sophon-ffmpeg.conf /etc/ld.so.conf.d/
sudo cp /opt/sophon/sophon-opencv-latest/data/02_sophon-opencv.conf /etc/ld.so.conf.d/
sudo ldconfig
sudo cp /opt/sophon/sophon-ffmpeg-latest/data/sophon-ffmpeg-autoconf.sh /etc/profile.d/
sudo cp /opt/sophon/sophon-opencv-latest/data/sophon-opencv-autoconf.sh /etc/profile.d/
sudo cp /opt/sophon/sophon-sample-latest/data/sophon-sample-autoconf.sh /etc/profile.d/
source /etc/profile
```

## 卸载方式

```bash
sudo rm -f /etc/ld.so.conf.d/01_sophon-ffmpeg.conf
sudo rm -f /etc/ld.so.conf.d/02_sophon-opencv.conf
sudo ldconfig
sudo rm -f /etc/profile.d/sophon-ffmpeg-autoconf.sh
sudo rm -f /etc/profile.d/sophon-opencv-autoconf.sh
sudo rm -f /etc/profile.d/sophon-sample-autoconf.sh
sudo rm -f /opt/sophon/sophon-ffmpeg-latest
sudo rm -f /opt/sophon/sophon-opencv-latest
sudo rm -f /opt/sophon/sophon-sample-latest
sudo rm -rf /opt/sophon/sophon-ffmpeg_|ver|
sudo rm -rf /opt/sophon/sophon-opencv_|ver|
sudo rm -rf /opt/sophon/sophon-sample_|ver|
sudo rm -rf /opt/sophon/opencv-bmcpu_|ver|
```

## 注意事项

- 如果需要用 sophon-opencv的python接口，手动设置环境变量：
  `export PYTHONPATH=$PYTHONPATH:/opt/sophon/sophon-opencv-latest/opencv-python`

# 使用sophon-sample

sophon-sample在不同的Linux发行版上提供不同类型的安装方式。请根据您的系统选择对应的方式，不要在一台机器上混用多种安装方式。
以下描述中"|ver|"仅为示例，视当前实际安装版本会有变化。

下文中$arch $system根据实际架构进行配置：
- 主机为x86 处理器的，$arch为amd64，$system为x86_64
- 主机为arm64或飞腾处理器的，$arch为arm64，$system为aarch64
- 主机为sg2042处理器的，$arch为riscv64，$system为riscv64

## 如果使用Debian/Ubuntu系统：

sophon-sample安装包由以下文件构成：
- sophon-mw-sophon-sample_|ver|_$arch.deb

## 如果使用Fedora/CentOS系统：

sophon-sample安装包由以下文件构成：
- sophon-mw-sophon-sample_|ver|_$arch.rpm

其中：
- sophon-mw-sophon-sample包含了数个用于测试sophon-ffmpeg/sophon-opencv的应用程序
- sophon-mw-sophon-sample依赖上一章节的sophon-ffmpeg/sophon-opencv包

## 安装步骤

```bash
安装libsophon依赖库(参考《LIBSOPHON使用手册》)
安装sophon-mw(参考上一章节)
安装sophon-sample
```

### 如果使用Debian/Ubuntu系统：
- `sudo dpkg -i sophon-mw-sophon-sample_|ver|_$arch.deb`

### 如果使用Fedora/CentOS系统，请在安装之前卸载已安装的包：
已安装包目录可以通过此命令列举：
- `dnf list installed | grep sophon-ffmpeg`

然后卸载：
- `sudo rpm -e sophon-mw-sophon-sample`

再安装：
- `sudo rpm -ivh sophon-mw-sophon-sample_|ver|_$arch.rpm`

## 安装位置

```
/opt/sophon/
├── libsophon-|ver|
├── libsophon-current -> /opt/sophon/libsophon |ver|
├── sophon-ffmpeg |ver|
├── sophon-ffmpeg-latest -> /opt/sophon/sophon-ffmpeg |ver|
├── sophon-opencv |ver|
├── sophon-opencv-latest -> /opt/sophon/sophon-opencv |ver|
├── sophon-sample_ |ver|
│   ├── bin
│   │   ├── test_bm_restart
│   │   ├── test_ff_bmcv_transcode
│   │   ├── test_ff_scale_transcode
│   │   ├── test_ff_video_encode
│   │   ├── test_ff_video_xcode
│   │   ├── test_ocv_jpubasic
│   │   ├── test_ocv_jpumulti
│   │   ├── test_ocv_vidbasic
│   │   ├── test_ocv_video_xcode
│   │   ├── test_ocv_vidmulti
│   │   └── water.bin
│   ├── data
│   └── sample
└── sophon-sample-latest -> /opt/sophon/sophon-sample_ |ver|
```

deb包安装方式并不允许您安装同一个包的多个不同版本，但您可能用其它方式在/opt/sophon下放置了若干不同版本。
在使用deb包安装时/opt/sophon/sophon-sample-latest会指向最后安装的那个版本。在卸载后，它会指向余下的最新版本（如果有的话）。

注意：soc模式下，deb安装包为
`sophon-mw-soc-sophon-sample_|ver|_arm64.deb`

安装位置同上

## 卸载方式

### 如果使用Debian/Ubuntu系统：
- `sudo apt remove sophon-mw-sophon-sample` 或者：
- `sudo dpkg -r sophon-mw-sophon-sample`

### 如果使用Fedora/CentOS系统：
- `sudo rpm -e sophon-mw-sophon-sample`

# 用例介绍

## test_bm_restart

此用例主要用于测试ffmpeg模块下的视频解码功能和性能，支持多路解码和断线重连功能。用户可以通过用例监测视频、码流的解码情况。

`test_bm_restart [api_version] [yuv_format] [pre_allocation_frame] [codec_name] [sophon_idx] [zero_copy] [input_file/url] [input_file/url]`

参数：
- api_version：指定解码过程使用的ffmpegAPI版本
  - 0: 使用老版本的解码avcodec_decode_video2接口
  - 1: 使用新版解码avcodec_send_packet接口
  - 2: 使用av_parser_parse2的API用于抓包
- yuv_format：是否压缩数据
  - 0表示不压缩
  - 1表示压缩
- pre_allocation_frame：允许的缓存帧数，最多为64
- codec_name：指定解码器，可选择 h264_bm/hevc_bm，no为不指定
- sophon_idx：若处于SOC模式，该选项可以随意设置（不可为空），其值将会被忽略
- zero_copy：若处于SOC模式，0表示启用Host memory，1表示不启用若处于PCIE模式，该选项可以随意设置（不可为空），其值将会被忽略
- input_file_or_url：输入的文件路径或码流地址

示例：
`test_bm_restart 1 0 1 no 0 1 ./example0.mp4 ./example1.mp4 ./example2.mp4`

## test_ff_bmcv_transcode

此用例主要用于测试ffmpeg模块下的视频转码功能和性能，通过调用ff_video_decode，ff_video_encode用例中的数据类型和函数，来实现先解码后编码的转码过程，以此保证解码和编码功能的正确性。同时此用例也可测试ffmpeg下的转码性能，运行时程序会输出即时转码帧率供参考。

`test_ff_bmcv_transcode [platform] [src_filename] [output_filename] [encode_pixel_format] [codecer_name] [width] [height] [frame_rate] [bitrate] [thread_num] [zero_copy] [sophon_idx] <optional: enable_mosaic> <optional: enable_watermark>`

参数：
- platform：平台：soc 或者 pcie
- src_filename：输入文件名 如x.mp4 x.ts 等
- output_filename：转码输出文件名 如x.mp4，x.ts 等
- encode_pixel_format：编码格式 如 I420
- encoder_name：编码 h264_bm，h265_bm
- width：编码宽度 (32，4096]
- height：编码高度 (32，4096]
- frame_rate：编码帧率
- bitrate：编码比特率encode bitrate 500 < bitrate < 10000
- thread_num：线程数量
- zero_copy：
  - PCie模式：0: 开启主从内存复制，1: 关闭
  - SoC模式：任何数字均可以，但是无效
- sophon_idx：
  - PCie模式：sophon设备id
  - SoC模式：任何数字均可以，但是无效
- enable_mosaic：可选，在左上角添加马赛克，目前仅支持bm1686且-encode_pixel_format] 为I420
- enable_watermark：可选，给视频添加水印，目前仅支持bm1686且-encode_pixel_format] 为I420

示例：

pcie mode example:
`test_ff_bmcv_transcode pcie example.mp4 test.ts I420 h264_bm 800 400 25 3000 3 0 0`

soc mode example:
`test_ff_bmcv_transcode soc example.mp4 test.ts I420 h264_bm 800 400 25 3000 3 0 0`

## test_ff_scale_transcode

此用例主要用于测试 ffmpeg 下视频转码的功能和性能。此功能通过先解码再编码的过程实现，主要调用了 ff_video_decode，ff_video_encode 中的数据类型和函数。

`test_ff_scale_transcode [src_filename] [output_filename] [encode_pixel_format] [codecer_name] [height] [width] [frame_rate] [bitrate] [thread_num] [zero_copy] [sophon_idx]`

参数：
- src_filename：输入文件名 如 x.mp4 x.ts...
- output_filename：输出文件名 如 x.mp4，x.ts...
- encode_pixel_format：编码格式 如 I420
- codecer_name：编码名 如 h264_bm，hevc_bm，h265_bm
- height：编码高度
- width：编码宽度
- frame_rate：编码帧率
- bitrate：编码比特率
- thread_num：使用线程数
- zero_copy：0: copy host mem，1: nocopy
- sophon_idx：设备索引

示例：
`test_ff_scale_transcode example.mp4 test.ts I420 h264_bm 800 400 25 3000 3 0 0`

## test_ff_video_encode

此用例主要用于测试ffmpeg模块下视频的编码功能。输入的视频限制为I420和NV12格式。通过调用此用例用户可以得到封装好的视频文件，ffmpeg支持的视频格式均可。

`test_ff_video_encode <input file> <output file> <encoder> <width> <height> <roi_enable> <input pixel format> <bitrate(kbps)> <frame rate> <sophon device index>`

参数：
- input_file：输入视频路径
- output_file：输出视频文件名
- encoder：H264或者H265，默认为H264
- width：视频宽度，输出与输入需一致，256 <= width <= 8192
- height：视频高度，输出与输入需一致，128 <= height <= 8192
- roi_enable：是否开启roi，0表示不开启，1表示开启
- input_pixel_format：I420(YUV，默认)，NV12
- bitrate：输出比特率，10 < bitrate <= 100000，默认为帧率x宽x高/8
- framerate：输出帧率，10 < framerate <= 60，默认为30
- sophon_device_index：pcie模式可用，指定运行的设备号，最小为0

示例：
- `test_ff_video_encode <input file> <output file> H264 width height 0 I420 3000 30 2`
- `test_ff_video_encode <input file> <output file> H264 width height 0 I420 3000 30`
- `test_ff_video_encode <input file> <output file> H265 width height 0 I420`
- `test_ff_video_encode <input file> <output file> H265 width height 0 NV12`
- `test_ff_video_encode <input file> <output file> H265 width height 0`

## test_ff_video_xcode

此用例主要用于测试ffmpeg下视频转码的功能和性能。此功能通过先解码再编码的过程实现，主要调用了ff_video_decode，ff_video_encode中的数据类型和函数。
转码后的视频分辨率与原视频一致，比特率不能超过10000kbps 或小于 500kbps，否则会被置为默认值3000kbps。
转码后的视频如比特率与原视频一致，那么时长也应一致。有一些丢帧属于正常现象。

`test_ff_video_xcode <input file> <output file> encoder framerate bitrate(kbps) isdmabuffer pcie_no_copyback sophon_idx`

参数：
- input_file：输入文件
- output_file：输出文件
- encoder：编码器 H264 或者 H265
- isdmabuffer：是否开启内存一致，1表示不开启，0表示开启

PCIE模式下可选：
- pcie_no_copyback：表示不将解码后YUV数据复制到host主机内存，0表示复制YUV数据到host主机内存
- sophon_idx：指定card编号，默认为0

示例：
- `test_ff_video_xcode ./file_example_MP4_1920_18MG.mp4 tran5.ts H264 30 3000 1 1 0`
- `test_ff_video_xcode ./file_example_MP4_1920_18MG.mp4 tran5.ts H264 30 3000 0 0 0`
- `test_ff_video_xcode ./file_example_MP4_1920_18MG.mp4 tran5.ts H264 30 3000 1 0 0`

# test_ocv_jpubasic

此用例主要用于测试图片编解码的基本功能。此用例进行了3种测试，主要调用了opencv中的imread、imwrite、imdecode、imencode等接口用不同方式实现图片的编解码。

## 参数说明

- `file` - 图片文件路径
- `loop` - 循环次数
- `yuv_enable` - 0表示解码后输出BGR格式，1表示解码后输出YUV格式
- `dump_enable` - 1表示输出dump文件，0表示不输出
- `card` - pcie模型下可选。指定运行的card编号

## 示例

```
test_ocv_jpubasic 1920x1080_gray.jpg 1000 1 1 0
```

# test_ocv_jpumulti

此用例主要用于测试多路图片编解码的功能和性能。

## 参数说明

- `test_type` - 测试类型，1表示只解码，2表示只编码，3表示解码编码混合
- `inputfile` - 输入文件
- `loop` - 循环次数
- `num_thread` - 线程数，最小为1，最大为12
- `outjpg` - 是否输出图片，1表示输出，0表示不输出
- `card` - PICE模式下可选参数。指定运行的card编号

## 示例

```
test_ocv_jpumulti 3 1088test1_420.jpg 10 2 1 0
```

# test_ocv_vidbasic

此用例主要用于测试视频记录为png或jpg格式的功能。如果启用dump，则也可输出BGR或YUV格式的原始数据。

## 参数说明

- `input_video` - 输入的视频文件路径
- `output_name` - 输出文件名前缀
- `frame_num` - 存储帧数
- `yuv_enable` - 是否开启yuv，0表示输出BGR格式，1表示输出YUV格式
- `card` - PCIE模式下可选参数，指定运行的card编号
- `WxH` - 可选参数，指定输出文件的分辨率，未指定则与原视频分辨率一致
- `dumpBGR_or_dumpYUV` - 可选参数，是否输出dump.BGR或dump.YUV文件

## 示例

```
test_ocv_vidbasic station.avi test_basic 10 1 0 1920x1080
```

# test_ocv_video_xcode

此用例主要用于opencv模块下视频转码的全方位测试，对于opencv库支持的不同格式的视频输入，提供h264、h265编码，yuv格式输出，roi区域等多种功能以及多种格式输出，覆盖的格式以及功能范围非常广泛。

## 参数说明

- `input` - 输入文件名
- `code_type` - 编码类型。H264enc表示H.264，H265enc表示H.265
- `frame_num` - 需要处理的帧数
- `outputname` - 指定输出文件名，可以设置为null
- `yuv_enable` - 0指定输出文件为bgr色彩格式；1指定输出文件为yuv420色彩模式
- `roi_enable` - 0表示禁用roi编码；1表示启用roi编码，启用roi编码时，输出文件名应指定为null并且在编码参数中加上roi_eanble=1
- `encodeparams` - 可选参数，可以设置roi_enable、bitrate、min_qp、gop等参数
- `device_id` - pcie模式下可选参数，指定card编号

## 示例

```
test_ocv_video_xcode rtsp_url H265enc 10000 encoder_test265.ts 1 0 0 bitrate=1000
```

# test_ocv_vidmulti

此用例主要用于opencv模块下视频以及码流的编解码性能测试，测试设备在视频多路编解码转码时的性能，终端可以输出每一个线程的编号、输入视频分辨率、重连次数、当前解码帧数、实时帧率、总平均帧率、丢帧数等，以及编码功能相关信息。

## 参数说明

- `thread_num` - 线程数，最大不超过512
- `enc_enable` - 是否开启编码。0表示不开启，1表示开启
- `card` - PCIE模式下可选参数，指定运行每个文件对应的card编号

## 环境变量

- `export VIDMULTI_DISPLAY_FRAMERATE=0` - 只显示帧数
- `export VIDMULTI_DISPLAY_FRAMERATE=1` - 会显示每一个channel的详细信息，可以看丢帧情况等

## 示例

```
test_ocv_vidmulti 3 a.264 0 1 b.264 1 1 c.264 0 0
```