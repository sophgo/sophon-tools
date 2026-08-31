---
title: 多媒体FAQ
description: 多媒体常见问题
tableOfContents:
  maxHeadingLevel: 3
sidebar:
  hidden: true
---

## 视频解码

### 常见问题

#### 如何判断视频花屏的原因

答：这里提的视频花屏是长时间的花屏，对于偶尔的花屏有可能是网络数据传输错误导致的，此类不属于应用代码可控的方位。如果视频出现长时间的花屏，很大概率是由于视频帧读取不及时，导致内部缓存满以后，socket
recv buffer溢出导致的。

1.  将加大rmem_max到2M，如果此时花屏消失，说明应用的数据处理抖动很大，应该要加大buffer
    queue进行平滑

        echo 2097152 > /proc/sys/net/core/rmem_max

2.  用netstat -na,
    一般是一下格式，找到rtsp的那个端口（udp在应用中会有打印，tcp的话可以看目标rtsp地址），这里的Recv-Q,
    Send-Q在正常情况应该都是0，或者不满的，如果Recv-Q经常有很大的数，就说明overflow了。一般Send-Q不会出问题，如果这个也很大的话，那么很可能network
    driver驱动挂死了。

        Proto Recv-Q Send-Q Local Address Foreign Address State
        tcp 0 0 0.0.0.0:111 0.0.0.0:\* LISTEN

#### 解码不正确或者无法解码的最终调试手段

答：如果经常各种调试后，在现场仍然无法解决问题，可以通过打开环境变量，把问题发生前后的数据dump下来，供后续进行进一步分析

在PCIE模式下

    export BMVID_PCIE_DUMP_STREAM_NUM=1000

dump的数据在/data/下（需要创建该文件夹并且有写权限），dump的数据根据core
index和instance index存储。

在SOC模式下

    echo "0  0 1000 100" > /proc/vpuinfo
    echo "0  1 1000 100" > /proc/vpuinfo
    ......
    echo "0 31 1000 100" > /proc/vpuinfo

    echo "1  0 1000 100" > /proc/vpuinfo
    echo "1  1 1000 100" > /proc/vpuinfo
    ......
    echo "1 31 1000 100" > /proc/vpuinfo

(dump第1个core的第1个instance的码流数据)

这个配置会在两个文件之间循环存储1000帧数据，当问题发生的时候，把这两个发生前后的那个1000帧文件拷贝回来就可以。两个文件的存储位置在/data/[core]()%dinst%d_stream%d.bin.

停止保存码流 :

    echo "0  0 0 0" > /proc/vpuinfo
    echo "0  1 0 0" > /proc/vpuinfo
    ......
    echo "0 31 0 0" > /proc/vpuinfo

    echo "1  0 0 0" > /proc/vpuinfo
    echo "1  1 0 0" > /proc/vpuinfo
    ......
    echo "1 31 0 0" > /proc/vpuinfo

（注意：PCIE需要提前准备/data/目录的写权限）

#### 判断rtsp是否正常工作

答：

方法一：通过vlc播放视频(推荐)，分别设置tcp，udp方式

方法二：使用vidmutil测试程序播放，vidmutil默认是
udp方式，通过设置环境变量使用tcp方式。

    export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|buffer_size;1024000|max_delay;50000"
    sudo -E ./vidmulti thread_num input_video [card] [enc_enable] input_video [card] [enc_enable]...

#### 播放rtsp流出现断连情况验证

答：可以使用vlc播放相同的视频，在相同的时间下，看vlc播放是否有断连的情况，注意设置vlc的缓冲区大小。

#### 验证当前rtsp服务输出的视频是否有花屏

答：使用vlc播放视频，持续一段时间，看视频是否有花屏

#### 查看rtsp服务是否实时推流

答：通过rtspserver日志，查看当前播放的文件是否正在发送。

#### ffmpeg&opencv 支持 gb28181 协议，传入的url地址形式如下

答：

**udp实时流地址**

    gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108
    34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
    deviceid：前段设备20位编码
    localid：本地20位编码，可选项
    localip：本地ip，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
    localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同.同一个核心板端口不可重复。

**udp回放流地址**

    gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=\35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#localmediaport=20108#begtime=20191018160000#endtime=20191026163713
    34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
    deviceid：前段设备20位编码
    devicetype：录像存储累类型
    localid：本地20位编码，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
    localip：本地ip，可选项
    localmediaport：媒体接收端的视频流端口，需要做端口映射，映射两个端口(rtp:11801,rtcp:11802)，两个端口映射的in和out要相同.同一个核心板端口不可重复。
    begtime：录像起始时间
    endtime：录像结束时间

**tcp实时流地址**

    gb28181://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#localid=12478792871163624979#localip=172.10.18.201
    34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
    deviceid：前段设备20位编码
    localid：本地20位编码，可选项
    localip: 本地ip，是可选项.不设置会获取 eth0 的ip，如果没有eth0需要手动设置

**tcp回放流地址**

    gb28181_playback://34020000002019000001:123456@35.26.240.99:5666?deviceid=35018284001310090010#devicetype=3#localid=12478792871163624979#localip=172.10.18.201#begtime=20191018160000#endtime=20191026163713
    34020000002019000001:123456@35.26.240.99:5666：sip服务器国标编码:sip服务器的密码@sip服务器的ip地址:sip服务器的port
    deviceid：前段设备20位编码
    devicetype :录像存储累类型
    localid :本地20位编码，可选项
    localip :本地ip，可选项. 不设置会获取 eth0 的ip，如果没有eth0需要手动设置
    begtime :录像起始时间
    endtime :录像结束时间

:::note
1.  流媒体传输默认是udp方式，如果使用tcp方式获取实时流或回放流，需要显示的指定。

    Ffmpeg指定tcp方式为接口调用 通过av_dict_set设置
    gb28181_transport_rtp 为tcp。

    Opencv指定方式是设置环境变量

        export OPENCV_FFMPEG_CAPTURE_OPTIONS="gb28181_transport_rtp;tcp"

2.  如果使用udp方式外部无法访问到内部ip/port，localmediaport需要做端口映射，端口映射需要两个
    rtp和rtcp。

3.  做端口映射时，使用的端口号尽量不要太大，推荐10000\--20000的端口，socket端口号的最大值时65536，但是很情况下，端口号是受很多资源的限制。
    端口号使用过大可能会出现：\[bind failed\] 错误打印。
:::

#### BM168x解码性能对于H264/H265有差别吗？如果调整码率的话，最多可以解多少路呢？有没有对应的数据参考？

答：

264,265是解码路数相同的。

码率对解码帧率会有影响，这个变化就需要实测，例如我们说的BM1684解码能达到960fps是针对监控码流而言的，这类监控码流没有B帧，场景波动较小，码率基本在2\~4Mbps。如果是电影或者其他码率很高的，比如10Mbps，20Mbps甚至更多，是会有明显影响的，具体多大这个需要实测。

分辨率对于解码帧率的影响，是可以按照比例来换算的。我们说的960fps是针对1920x1080
HD分辨率而言的。

#### 是否可以通过抽帧来提高BM168x的解码路数

答：

我们opencv中提供的抽帧，是在解码出来的结果中做的，并不是只解I/P帧的抽帧概念。这里的抽帧解码主要是保证出来帧数的均匀，使得后续的分析处理是等间隔的进行，这是为后续模型分析比较复杂的时候，不能达到每帧都检测而设计的解决方案，但并不能达到增加解码路数的效果。

这里顺便解释下，为什么不提供只解I/P帧的抽帧功能。如果只解I、P帧的话，抽帧的间隔就完全取决于码流的编码结构，这样是比较难控制住性能，比如监控码流中的没有B帧，那其实就相当于没有抽帧了。如果客户可以控制编码端，那更切合实际的做法是直接降低编码端的编码帧率，比如降到15fps，那样解码路数就可以直接
提升；反之，如果客户没有办法控制编码端，那么同样的，只解IP帧的抽帧方式就也无法达到增加解码路数的效果。

#### Valgrind内存检查为什么有那么多警告，影响到应用的调试了

答：

我们的版本发布每次都会用valgrind检查一遍内存泄漏问题，如果有内存泄露问题我们会检查修正的。之所以没有去掉有些警告，是因为这些警告大部分都是内存没有初始化，如果对这些内存每个都加上初始化，会明显导致速度性能下降，而且我们确认后续操作是在硬件对其赋值后再进行的，对于此类警告，我们就不会去消除。

为了避免警告过多对上层应用调试造成影响，建议使用valgrind的suppression功能，可以通过过滤配置文件，来避免我们模块产生的valgrind警告，从而方便上层应用调试自身的程序。

#### 如何查看vpu/jpu的内存、使用率等状态

答：

在pcie模式下，可以用下面的方法查看：

    cat /proc/bmsophon/card0/bmsophon0/media

    cat /proc/bmsophon/card0/bmsophon0/jpu

在soc模式下，可以用下面的方法查看：

    cat /proc/vpuinfo

    cat /proc/jpuinfo

参数说明:

* total_mem_size: 总的物理内存大小
* used_mem_size: 已使用的物理内存大小
* free_mem_size: 剩余可用的物理内存大小
* vdec_coreid: 1684有2个解码核，1个编码核
* link_num: 在这个核上打开的总路数
* usage(instant\|long): instant显示当前解码核的利用率, long显示开机依赖解码核的利用率
* channel信息 显示每一路编解码的详细信息
* channel: 通道号
* res: 正在编解码视频的分辨率
* fps: 帧率信息，前一个是视频本身的帧率，括号内的是实际编解码帧率
* in_frames: 已经送入编解码器的帧数.可以通过设置环境变量修改更新频率
* fail_frames: 编解码失败的帧数
* success_not_get: 编解码成功尚未取走的帧数
* status: 编解码器的状态 解码器状态如下 0: 当前通道未被使用 1:通道已创建但尚未加载完成 2: 通道已创建但未初始化 3: 通道正在初始化 4:解码的分辨率不支持 5: 设置的framebuff数量过少 6: 正在解码中 7: framebuf已满 8: 解码结束 9: 解码器停止工作 10: 解码器HUNG 11: 解码器关闭。编码器状态如下 0: 当前通道未被使用 1: 正在编码

jpuinfo 参数说明: 

* JPU load balance: 显示JPU的负载均衡情况
* JPU0 = 0 表示core0的完成的编解码任务数(cat /proc/jpuinfo 后重新计数)
* JPU1 = 0 表示core1的完成的编解码任务数(cat /proc/jpuinfo 后重新计数)
* open_status: 0表示当前core未被使用，1表示当前core正在工作
* usage(short\|long): short表示当前core的瞬时利用率
* instance: 表示当前core的实例编号
* status: 表示当前core的编解码状态(1: 解码, 2:编码)
* res: 表示当前core的编解码分辨率
* decoded: 表示当前core的解码帧数
* dec_errors: 表示当前core的解码错误帧数
* last_dec_err: 表示当前core的最后一次解码错误状态 INT_JPU_TIMEOUT = -1, INT_JPU_ERROR = 1, INT_JPU_BIT_BUF_EMPTY = 2, INT_JPU_PARIAL_OVERFLOW = 3, INT_JPU_BIT_BUF_STOP = 8
* encoded: 表示当前core的编码帧数
* enc_errors: 表示当前core的编码错误帧数
* last_enc_err: 表示当前core的最后一次编码错误状态 INT_JPU_TIMEOUT = -1, INT_JPU_ERROR = 1, INT_JPU_BIT_BUF_FULL = 2, INT_JPU_PARIAL_OVERFLOW = 3, INT_JPU_BIT_BUF_STOP = 8
* fps: 表示当前core的编解码帧率

#### 视频支持32路甚至更多的时候i，报视频内存不够使用，如何优化内存使用空间

答：

在PCIE板卡下，视频内存有3G，一般来说支持32路甚至更多的路数都绰绰有余。但在soc模式下，视频内存的默认配置是2G，正常使用在16路是绰绰有余的，但在32路视频需要在应用层面上仔细设计，不能有任何的浪费。

如果解码使用的是FFMPEG框架，首先保证视频输出格式使用压缩格式，即output_format
101。Opencv框架的话，内部已经默认使用压缩格式了；

其次如果应用在获取到解码输出avFrame后，并不是直接压入队列，而是转换到RGB或者非压缩数据后再缓存的话，可以用av_dict_set
extra_frame_buffer_num为1（默认为2）。Opencv内部在最新版本中会默认优化。

最后，如果以上优化过后，仍然不够的话，在soc模式下可以考虑更改dtb设置，给视频挪用分配更多的内存，当然相应的，其他模块就要相应的减少内存。这个要从系统角度去调配。

#### 启动设备首次执行某个函数慢，重启进程再次运行正常

现象：设备上电后第一次执行程序，函数处理时间长，再次执行程序，运行正常。

解决：先做个验证，如果不重启可复现，就说明是文件cache导致的变慢。

1.  上电后第一次执行慢，第二次执行正常，之后进入root用户
2.  清除cache echo 3 \> /proc/sys/vm/drop_caches
3.  再次执行程序，运行慢，即可确定是cache导致的。

#### \[问题分析\]程序提示"VPU_DecGetOutputInfo decode fail framdIdx xxx error(0x00000000) reason(0x00400000), reasonExt(0x00000000)"是可能什么问题，这里reason的具体数值可能不同

> 这个提示通常是由码流错误造成的，提示的含义是第xxx帧解码错误，错误原因为\....。这里具体原因对于上层应用来说，不用关心，只需知道这是由码流错误导致的即可。
>
> 进一步分析，导致码流错误的原因通常可以分为两类，我们要有针对的进行处理。因为一旦频繁出现这种提示，说明解码出来的数据是不正确的，这时候有可能是各种马赛克或者图像花，对于后续的处理会造成各种异常情况，所以我们必须尽量减少这种情况的发生。
>
> 1.  网络情况导致的丢包。这时候可以用我们的测试程序vidmulti验证下，如果vidmulti没有解码错误，那么可以排除这种情况。如果确认网络丢包的话，要分辨下是否网络带宽本身就不够，如果本身带宽不够，那没有办法，只能降低视频码流的码率。如果带宽是够的，要检查下网线。当码流连接数超过20多路的时候，这时候有可能已经超出百兆了，这时网线也必须换到CAT6，与千兆网相匹配
> 2.  解码性能达到上限造成丢包。这种情况发生在流媒体环境中，对于文件播放是不会发生的。这时也可以用我们的vidmulti跑一下，作为比较。如果vidmulti也发生错误，说明性能确实到了上限了，否则说明应用本身还有优化的空间。

#### \[问题分析\]程序提示"coreIdx 0 InstIdx 0: VPU interrupt wait timeout"，这是怎么回事?

> 这个提示表示视频解码或者编码中断超时。这个提示只是警告，会再次尝试，因此只要没有连续出现就可以忽略。这种情况一般是由解码数据错误导致或者负荷过重产生的。例如在板卡情况下，由于板卡数据交换过于频繁，造成解码或者编码数据传输堵塞，使得中断超时。
>
> 当这个报错连续出现时，可能代表解码器硬件已经挂死，可以通过以下两种方式获取解码器的状态：
>
> 1.  使用 bmvpu_dec_get_status 接口来获取解码器状态。若返回值为
>     BMDEC_HUNG（10），则表示解码器已经挂死；
> 2.  送流时报错。
>
> > (1) BmApi：bmvpu_dec_decode 报错 BM_ERR_VDEC_ERR_HUNG（-2）；
> > (2) FFmpeg：avcodec_send_packet 报错 AVERROR_EXTERNAL;
> > (3) OpenCV：cv::VideoCapture-\>get(cv::CAP_PROP_STATUS) == 2；
>
> 出现以上三种情况时，需要重置解码器来做复位。

#### 申请设备内存失败， 错误返回-24。

> 设备内存每一次申请都会有一个fd，ubuntu上最大1024。如果持续申请且不释放，fd数量超过1024，就会导致申请设备内存失败，错误返回-24。
> 如果想扩大ubuntu的fd数量，可通过ulimit命令修改限制。如 ulimit -n 10000
> 可将ubuntu的fd数量扩大至10000。

#### url特殊字符对照表

有些符号在URL中是不能直接传递的，如果要在URL中传递这些特殊符号，需要使用其编码值。

编码的格式为：%加字符的ASCII码。

+------+--------+
| 字符 | 编码值 |
+======+========+
| 空格 | > %20  |
+------+--------+
| \"   | %22    |
+------+--------+
| \#   | %23    |
+------+--------+
| &    | %26    |
+------+--------+
| (    | %28    |
+------+--------+
| )    | %29    |
+------+--------+
| -    | %2B    |
+------+--------+
| ,    | %2C    |
+------+--------+
| /    | %2F    |
+------+--------+
| :    | %3A    |
+------+--------+
| ;    | %3B    |
+------+--------+
| \<   | %3C    |
+------+--------+
| =    | %3D    |
+------+--------+
| \>   | %3E    |
+------+--------+
| ?    | %3F    |
+------+--------+
| @    | %40    |
+------+--------+
| \\   | > %5C  |
+------+--------+
| \|   | > %7C  |
+------+--------+

### bm_ffmpeg问题

#### Ffmpeg的阻塞问题

原因分析：如果没有及时释放avframe，就会导致阻塞，vpu内部是循环buffer。

#### 无法连接rtsp？

答：可以通过ffmpeg固有命令来进行连接测试：（url为rtsp连接地址）

    ffmpeg -rtsp_transport tcp -i url -f rawvideo -y /dev/null

    或者

    ffmpeg -rtsp_transport udp -i url -f rawvideo -y /dev/null

    若以上无法连接成功，请检查网络。

#### 确认解码器是否能正常工作：（url为文件名或者rtsp连接地址）

答：

    ffmpeg -i url -f rawvideo -y /dev/null

#### FFMPEG JPEG 编码与转码应用示例

答：

-   **调用JPEG编码的ffmpeg命令**

        ffmpeg -c:v jpeg_bm -i src/5.jpg -c:v jpeg_bm  -is_dma_buffer 1 -y 5nx.jpg

-   **调用动态JPEG转码的ffmpeg命令**

        ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.avi -c:v jpeg_bm -is_dma_buffer 1 -y test_avi.mov

        ffmpeg -c:v jpeg_bm -num_extra_framebuffers 2 -i in_mjpeg.mov -c:v jpeg_bm -is_dma_buffer 1 -y test_mov.mov

#### 如何从FFMPEG的输入缓冲区中读取 bitstream?

答：

FFMPEG 源码应用示例
/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_reading.c
(or http://www.ffmpeg.org/doxygen/trunk/doc_2examples_2avio_reading_8c-example.html)

在这一示例中，libavformat demuxer 通过 \*\*custom AVIOContext read
callback\*\*
 访问媒体信息，而不是通过在传入FFMPEG中的文件、rstp等协议访问媒体信息的。

以下是middleware-soc中的一个使用avio + jpeg_bm解码静态jpeg图片的例子。
(/opt/sophon/sophon-ffmpeg-latest/share/ffmpeg/examples/avio_decode_jpeg.c)

#### 在soc模式下客户用ffmpeg解码时拿到AVframe将data\[0-3\] copy到系统内存发现copy时间是在20ms左右而相同数据量在系统内存两块地址copy只需要1-3ms

答：上述问题的原因是系统在ffmpeg中默认是禁止cache的，因此用处理器
copy性能很低，使能cache就能达到系统内存互相copy同样的速度。

方法1：可以用以下接口使能cache.

    av_dict_set_int(&opts, "enable_cache", 1, 0);

方法2：上述方法直接copy数据保存是非常占用内存、带宽和处理器算力。我们推荐采用以下两种零拷贝的方式来实现原始解码数据的保存：

1.  推荐使用 extra_frame_buffer_num
    参数指定增大硬件帧缓存数量，可以根据自己的需要选择缓存帧的数量。
    这个方式的弊端，一个是占用解码器内存，可能减少视频解码的路数；另一个是当不及时释放，当缓存帧全部用完时，会造成视频硬件解码堵塞。

        av_dict_set_int(&opts, "extra_frame_buffer_num", extra_frame_buffer_num, 0);

2.  推荐使用
    output_format参数设置解码器输出压缩格式数据，然后使用vpp处理输出非压缩yuv数据（当需要缩放，crop时，可以同步完成），
    然后直接零拷贝引用非压缩yuv数据。这种方式不会影响到硬件解码性能，并且可以缓存的数据空间也大很多。

        av_dict_set_int(&opts, "output_format", 101, 0);

#### \[问题分析\]客户反馈碰到如下错误提示信息\"VPU_DecRegisterFrameBuffer failed Error code is 0x3\", 然后提示Allocate Frame Buffer内存失败。

> 这个提示信息表示：分配的解码器缓存帧个数，超过了最大允许的解码帧。导致这个问题的原因有可能是：
>
> 1.  不支持的视频编码格式，比如场格式，此时可以用FAQ3.1.1.2的方法，把码流数据录下来，提交给我们分析。
> 2.  设置了过大的extra_frame_buffer_num。理论上，extra_frame_buffer_num不能超过15，超过了以后就有可能不能满足标准所需的最大缓存帧数。因为大部分编码码流并没有用到最大值，所以extra_frame_buffer_num大于15的时候，对大部分码流仍然是可以工作的。
>
> 目前发现可能导致这个问题的原因有上述两种，后续有新的案例继续增补

#### 采用TCP传输码流的时候如果码流服务器停止推流，ffmpeg阻塞在av_read_frame

> 这是因为超时时间过长导致的，可以用一下参数设置超时时间减短。
>
> av_dict_set(&options, \"stimeout\", \"1000000\", 0);

#### 将 output_format 设置为101后，发现解压缩后的yuv花屏

![image](../../../assets/se7-media-faq/image1.png)

这是因为输入码流的编码分辨率和显示分辨率存在差异导致的，avFrame中保存的是yuv的显示分辨率，而vpp解压缩需要使用编码分辨率。

解决方案是使用 AVCodecContext 中的 coded_width 和 coded_height
来作为宽高信息传递给vpp做解压缩。

#### 解码器报错\"lost a non key frame in first serveral packet\...\"

错误信息的含义是：送入的码流数据还未检测到第一个关键帧，无法开始解码。
造成这个问题的原因一般有两种情况：

1)  使用rtsp拉流，因为拉流的时间有随机性，无法保证拉取到的码流都是从I帧开始。这种情况可以忽略该报错，当第一个I帧到来后，就能够正常启动解码。

2\)
用户自定义填充的avPacket（不使用av_read_frame来获取avPacket）。这种情况下一般是由于没有填充avPacket-\>flags造成的，需要根据帧类型正确填充avPacket-\>flags。
关键帧应该将avPacket-\>flags赋值为AV_PKT_FLAG_KEY。

#### 使用ffmpeg命令 \"ffmpeg -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4\" 进行转码时，程序卡死

提示如下错误信息：

    [h264_bm @ 0x481190] bmvpu_dec_get_output timeout. dec_status:6 endof_flag=0 pkg:1

原因是默认的解码输出缓冲区配置较小，编码需要的参考帧较多，导致输出缓冲区不够用，解码器被block住。
解码器默认的输出缓冲区配置的比较小是考虑到设备内存的资源占用，并非所有使用场景都需要较大的输出缓冲区。

可以通过配置 \"extra_frame_buffer_num\" 参数来增加解码缓冲区。

例如采用以下命令：

    ffmpeg -extra_frame_buffer_num 10 -c:v h264_bm -i h264_2560x1080.mp4 -c:v h264_bm -b:v 256K -an -y ii.mp4

程序运行日志中会通过以下信息提示所需配置的解码缓冲区的大小，可以参考该信息进行配置。

    [h264_bm @ 0x491500] Minimum number of input frame buffers for BM video encoder: 8

#### ffmpeg 命令使用压缩模式解码、解压缩、编码

将 scale_bm
设为输入的w和h，将只做解压缩，数据在转码过程中，没有经过系统内存拷贝

``` bash
ffmpeg -c:v hevc_bm -output_format 101 -i src/wkc_100.265 -vf "scale_bm=iw:ih:zero_copy=1" -c:v h264_bm -g 50 -b:v 32K -ywkc_100_out.h264
```

#### 使用压缩模式解码10bit码流花屏

使用压缩模式（配置 output_format = 101），输出结果花屏。原因是 VPP
硬件不支持 10bit 的图像数据。

可以通过使用 linear 模式（output_format = 0），使解码器直接输出 8bit YUV
数据，来解决该问题。

注意：由于 OpenCV 中解码器和 VPP 无法解耦，所以 OpenCV 不支持 10bit
码流解码。

### bm_opencv问题

#### opencv下如何获取视频帧的timestamp？

答：opencv原生提供了获取timestamp的接口，可以在cap.read()每一帧后获取当前帧的timestamp.

代码如下：

    Mat frame;
    cap.read(frame);
    /* 获取timestamp，返回值为double类型 */
    int64_t timestamp = (int64_t)cap.getProperty(CAP_PROP_TIMESTAMP);

#### SA3 opencv下videocapture经常5分钟左右断网的解决方案

答：在udp方式下,SA3经常发生RTSP数据连上后3-5分钟就\"connection
timeout\"的问题，这个问题最终解决方案是更新最新的路由板软件。验证方法可以用TCP测试下，如果TCP没有问题可以确认是这类问题。

使用TCP的方式见下面：

    export  OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp”

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）
注意：最新的middleware-soc将使用TCP作为默认协议，对原来客户需要使用UDP传输协议的，需要引导客户按照下面方式进行设置

使用UDP方式：

    export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;udp”

执行应用 （如果用sudo执行，需要sudo -E把环境变量带过去）

UDP适用的环境：当网络带宽比较窄，比如4G/3G等移动通信系统，此时用udp比较合适
TCP适用的环境：网络带宽足够，对视频花屏要求比较高，对延时要求较小的应用场景，适合TCP

#### 如何获取rtsp中原来的timestamp

答：opencv中默认获取的rtsp时间戳是从0开始的，如果想获取rtsp中的原始时间戳，可以用环境变量进行控制,
然后按照问题1进行获取即可

    export OPENCV_FFMPEG_CAPTURE_OPTOINS="keep_rtsp_timestamp;1"

注意:外置的options会覆盖内部默认的设置，因此最好按照完整的options来设置

    export OPENCV_FFMPEG_CAPTURE_OPTIONS="keep_rtsp_timestamp;1|buffer_size;1024000|max_delay;500000|stimeout;20000000"

#### 确认解码器和vpp的OpenCV接口是否正常工作：

答：

    vidmulti number_of_instances url1 url2

#### 对于cvQueryFrame等老的opencv接口支持状况

答：

有些客户采用旧版opencv的C接口，接口列表如下

    void cvReleaseCapture( CvCapture** pcapture )

    IplImage* cvQueryFrame( CvCapture* capture )

    int cvGrabFrame( CvCapture* capture )

    IplImage\* cvRetrieveFrame( CvCapture* capture, int idx )

    double cvGetCaptureProperty( CvCapture* capture, int id )

    int cvSetCaptureProperty( CvCapture* capture, int id, double value )

    int cvGetCaptureDomain( CvCapture* capture)

    CvCapture * cvCreateCameraCapture (int index)

    CvCapture * cvCreateFileCaptureWithPreference (const char * filename, int apiPreference)

    CvCapture * cvCreateFileCapture (const char * filename)

对于这些接口，大部分都是支持的，只有返回值是iplImage的接口无法支持，这是因为我们硬件底层的ion内存类型是保存在MAT的uMatData类型中的，而iplIMage类型没有uMatData数据结构。

因此对于客户目前使用 cvQueryFrame接口的，建议客户基于cap.read接口封一个返回值为Mat数据的C函数接口，不要直接调用opencv老版的接口。

#### Opencv中mat是如何分配设备内存和系统内存的？

答：

因为受设计影响，这个问题细节比较多，主要从三方面能解释。

1.  在soc模式下，设备内存和系统内存是同一份物理内存，通过操作系统的ION内存进行管理，系统内存是ION内存的mmap获得。在pcie模式下，设备内存和系统内存是两份物理内存，设备内存指BM168x卡上的内存，系统内存指服务器上操作系统内存。如果用户想只开辟系统内存，和开源opencv保持一致，可
    以参见FAQ3.4.3.5的回答。
2.  在sophon
    opencv中默认会同时开辟设备内存和系统内存，其中系统内存放在mat.u-\>data或mat.data中，设备内存放在mat.u-\>addr中。只有以下几种情况会不开辟设备内存，而仅提供系统内存：
    -   当data由外部开辟并提供给mat的时候。即用以下方式声明的时候：

        > Mat mat(h, w, type, data); 或 mat.create(h, w, type, data)；

    -   在soc模式下，当type不属于（CV_8UC3, CV_32FC1,
        CV_32FC3）其中之一的时候。这里特别注意CV_8UC1是不开辟的，这是为了保证我们的opencv能够通过开源opencv的opencv_test_core的一致性验证检查。

    -   当宽或者高小于16的时候。因为这类宽高，硬件不支持
3.  在BM1682、BM1684和BM1684x的SOC模式下，mat分配的CV_8UC3类型的设备内存会自动做64对齐，即分配的内存大小一定是64对齐的（注意：仅对soc模式的CV_8UC3而言，且仅对BM1684、BM1684x和BM1682）。在PCIE模式下，分配的内存是byte对齐的。

#### Opencv mat创建失败，提示"terminate called after throwing an instance of 'cv::Exception' what(): OpenCV(4.1.0) ...... matrix.cpp:452: error: (-215:Assertion failed) u != 0 in function 'creat'"

答：

这种错误主要是设备内存分配失败。失败的原因有两种：

1.  句柄数超过系统限制，原因有可能是因为句柄泄漏，或者系统句柄数设置过小，可以用如下方法确认：

    查看系统定义的最大句柄数：

        ulimit -n

    查看当前进程所使用的句柄数：

        lsof -n|awk ‘{print $2}’|sort|uniq -c|sort -nr|more

2.  设备内存不够用。可以用如下方法确认：

    -   SOC模式下

            cat /sys/kernel/debug/ion/bm_vpp_heap_dump/summary

    -   PCIE模式下， bm-smi工具可以查看设备内存空间

解决方案：在排除代码本身的内存泄漏或者句柄泄漏问题后，可以通过加大系统最大句柄数来解决句柄的限制问题：ulimit
-HSn 65536

设备内存不够就需要通过优化程序来减少对设备内存的占用，或者通过修改dts文件中的内存布局来增加对应的设备内存。详细可以参考SM5用户手册中的说明。

#### Opencv用已有Mat的内存data，宽高去创建新的Mat后，新Mat保存的图像数据错行，显示不正常

答：保存的图像错行，通常是由于Mat中step信息丢失所造成。

一般用已有Mat去生成一个新Mat，并且要求内存复用时，可以直接赋值给新的Mat来简单实现，如
Mat1 = Mat2.

但在某些情况下，比如有些客户受限于架构，函数参数只能用C风格的指针传递，就只能用Mat中的data指针，rows，cols成员来重新恢复这个Mat。
这时候就需要注意step变量的设置，在默认情况下是AUTO_STEP配置，即每行数据没有填充数据。但是在很多种情况下，经过opencv处理后，会导致每行出现填充数据。如，

1.  soc模式下，我们的Mat考虑执行效率，在创建Mat内存时每行数据会做64字节对齐，以适配硬件加速的需求（仅在soc模式下）
2.  opencv的固有操作，如这个Mat是另一个Mat的子矩阵（即rect的选定区域），或者其他可能导致填充的操作。

因此，按照opencv定义，通用处理方式就是在生成新的Mat的时候必须指定step，如下所示:

    cv::Mat image_mat = cv::imread(filename,IMREAD_COLOR,0);
    cv::Mat image_mat_temp(image_mat.rows,image_mat.cols,CV_8UC3,image_mat.data,image_mat.step[0]);
    cv::imwrite("sophgo1.jpg",image_mat_temp);

#### 在opencv VideoCapture 解码视频时提示: maybe grab ends normally, retry count = 513

> 上述问题是因为在VideoCapture存在超时检测，如果在一定时间未收到有效的packet则会输出以上log，此时如果视频源是网络码流可以用vlc拉流验证码流是否正常，如果是文件一般是文件播放到末尾需调用VidoeCapture.release后重新VideoCapture.open

#### SOC模式下，opencv在使用8UC1 Mat的时候报错，而当Mat格式为8UC3的时候，同样的程序完全工作正常。

> 这个问题碰到的客户比较多，这次专门设立一个FAQ以便搜索。其核心内容在FAQ3.1.3.6
> \"Opencv中mat是如何分配设备内存和系统内存的\"有过介绍，可以继续参考FAQ3.1.3.6
>
> 在soc模式下，默认创建的8UC1
> Mat是不分配设备内存的。因此当需要用到硬件加速的时候，比如推理，bmcv操作等，就会导致各种内存异常错误。
>
> 解决方案可以参看FAQ3.4.3.5 \"如何指定Mat对象基于system
> memory内存去创建使用\", 指定8UC1
> Mat在创建的时候，内部使用ion分配器去分配内存。如下所示。
>
> | cv::Mat gray_mat;
> | gray_mat.allocator = hal::getAllocator();
> | gray_mat.create(h, w, CV_8UC1);

#### 如何跨进程传递Mat信息，使不同进程间零拷贝地共享Mat中的设备内存数据？

> 跨进程共享Mat的障碍在于虚拟内存和句柄在进程间共享非常困难，因此解决这个问题的本质是：如何由一块设备内存，零拷贝地重构出相同的Mat数据结构。
>
> 解决这个问题会用到下面三个接口，其中前两个接口用于重构yuvMat的数据，后一个接口用于重构opencv
> 标准Mat的数据。

``` cpp
cv::av::create(int height, int width, int color_format, void *data, long addr, int fd, int* plane_stride, int* plane_size, int color_space = AVCOL_SPC_BT709, int color_range = AVCOL_RANGE_MMPEG, int id = 0)
cv::Mat(AVFrame *frame, int id)
Mat::create(int height, int width, int total, int _type, const size_t* _steps, void* _data,unsigned long addr, int fd, int id = 0)
```

``` cpp
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

#### 调用bm_opencv imread/imwrite 编译报错

``` cpp
/usr/bin/ld: /tmp/ccozaFei.o: in function `.LEHE0':
test_opencv.cpp:(.text+0x50): undefined reference to `cv::imread(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, int, int)'
/usr/bin/ld: /tmp/ccozaFei.o: in function `.LEHE3':
test_opencv.cpp:(.text+0xf0): undefined reference to `cv::imwrite(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, cv::_InputArray const&, std::vector<int, std::allocator<int> > const&)'
collect2: 错误：ld 返回 1
```

在排查了引用so路径等问题之后，可以排查 libstdc++ 版本

:   可能是使用的sdk和编译环境的libstdc++ 版本不匹配导致的。

解决办法是：

:   设置abi0、abi1 g++ -D_GLIBCXX_USE_CXX11_ABI=0 \...\... 或 g++
    -D_GLIBCXX_USE_CXX11_ABI=1 \...\...

## 视频编码

### 常见问题

### bm_ffmpeg问题

#### 使用ffmpeg 在pcie模式下进行编解码 使用过滤器 要注意指定sophon_idx。

1.  解码，编码，过滤器默认的sophon_idx 都是0

2.  HWAccel模式下：通过hwaccel_device 指定卡id，示例:

        ffmpeg -hwaccel bmcodec -hwaccel_device 1 -c:v hevc_bm -output_format 0
               -i video.265 -vf "scale_bm=352:288:sophon_idx=1"
               -c:v h264_bm -g 256 -b:v 256K -sophon_idx 1 -y out.264

3.  常规模式下：通过sophon_idx指定卡id，示例:

        ffmpeg -c:v hevc_bm  -sophon_idx 1 -i video.265
               -vf "scale_bm=2560:1440:opt=crop:zero_copy=1:sophon_idx=1"
               -c:v h264_bm -g 256 -b:v 8M -sophon_idx 1 -y out.264

#### 编码出现花屏问题排查

1.  解码的数据直接编码，需要确认是否设置了is_dma_buffer，需要保证avframe里有物理内存数据同时设置is_dma_buffer为1或者数据在avframe的系统内存同时设置is_dma_buffer为0.
2.  bmcv处理过的数据进行编码，确认分配的物理内存在vpu的heap上通常需要调用bm_image_alloc_dev_mem_heap_mask，可以参考demo中调用方式.

#### 编码返回错误AVERROR(EINVAL)

解析：编码函数返回错误 AVERROR(EINVAL) 并且 出现如下错误打印

:   bmvpu_enc_encode params err: the input yuv(0X1243a3000) is not on the VPU(0X348f67000) heap.

    请排查外部分配的yuv是否在vpu heap上。

    > 其他情况下返回错误 AVERROR(EINVAL)：请排查参数问题

### bm_opencv问题

#### VideoWriter.write性能问题，有些客户反应，存文件慢。

解析：就目前来看看采用YUV采集，然后编码10-20ms之间写入一帧数据属于正常现象。

#### 使用opencv的video write编码，提示物理内存(heap2)分配失败

答：

确认heap2 设置的大小，如果heap2 默认大小是几十MB，需要设置heap2
size为1G。目前出厂默认配置是1G。

    Update_boot_info 可查询heap2 size

    update_boot_info –heap2_size=0x40000000 –dev=0x0 设置heap2 size为1G。设置后重装驱动。

## 图片编解码

### 常见问题

#### 是否支持avi, f4v, mov, 3gp, mp4, ts, asf, flv, mkv封装格式的H264/H265视频解析？

答：我们使用ffmpeg对这些封装格式进行支持，ffmpeg支持的我们也支持。经查，这些封装格式ffmpeg都是支持的。但是封装格式对于H265/264的支持，取决于该封装格式的标准定义，比如flv标准中对h265就没有支持，目前国内的都是自己扩展的。

#### 是否支持png, jpg, bmp, jpeg等图像格式

答：Jpg/jpeg格式除了有jpeg2000外，自身标准还有很多档次，我们采用软硬结合的方式对其进行支持。对jpeg
baseline的除了极少部分外，都用硬件加速支持，其他的jpeg/jpg/bmp/png采用软件加速的方式进行支持。主要的接口有opencv/ffmpeg库。

### bm_ffmpeg问题

#### 从内存读取图片，用AVIOContext \*avio =avio_alloc_context()，以及avformat_open_input()来初始化，发现初始化时间有290ms；但是如果从本地读取图片，只有3ms。为啥初始化时间要这么长？怎样减少初始化时间？

答：

    ret = avformat_open_input(&fmt_ctx, NULL, NULL, NULL);

这里是最简单的调用。因此，avformat内部会会读取数据，并遍历所有的数据，来确认avio中的数据格式。

若是避免在这个函数中读取数据、避免做这种匹配工作。在已经知道需要使用的demuxer的前提下，譬如，已知jpeg的demuxer是mjpeg，可将代码改成下面的试试。

    AVInputFormat\* input_format = av_find_input_format("mjpeg");

    ret = avformat_open_input(&fmt_ctx, NULL, input_format, NULL);

#### 如何查看FFMPEG中支持的分离器的名称?

答：

| <root@linaro-developer>:\~# ffmpeg -demuxers \| grep jpeg
| D jpeg_pipe piped jpeg sequence
| D jpegls_pipe piped jpegls sequence
| D mjpeg raw MJPEG video
| D mjpeg_2000 raw MJPEG 2000 video
| D mpjpeg MIME multipart JPEG
| D smjpeg Loki SDL MJPEG

#### 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm解码器信息?

答：

| root@[linaro-developer:/home/sophgo/test#](http://linaro-developer/home/bitmain/test) ffmpeg
  -decoders \| grep \_bm
| V\..... avs_bm bm AVS decoder wrapper (codec avs)
| V\..... cavs_bm bm CAVS decoder wrapper (codec cavs)
| V\..... flv1_bm bm FLV1 decoder wrapper (codec flv1)
| V\..... h263_bm bm H.263 decoder wrapper (codec h263)
| V\..... h264_bm bm H.264 decoder wrapper (codec h264)
| V\..... hevc_bm bm HEVC decoder wrapper (codec hevc)
| V\..... jpeg_bm BM JPEG DECODER (codec mjpeg)
| V\..... mpeg1_bm bm MPEG1 decoder wrapper (codec mpeg1video)
| V\..... mpeg2_bm bm MPEG2 decoder wrapper (codec mpeg2video)
| V\..... mpeg4_bm bm MPEG4 decoder wrapper (codec mpeg4)
| V\..... mpeg4v3_bm bm MPEG4V3 decoder wrapper (codec msmpeg4v3)
| V\..... vc1_bm bm VC1 decoder wrapper (codec vc1)
| V\..... vp3_bm bm VP3 decoder wrapper (codec vp3)
| V\..... vp8_bm bm VP8 decoder wrapper (codec vp8)
| V\..... wmv1_bm bm WMV1 decoder wrapper (codec wmv1)
| V\..... wmv2_bm bm WMV2 decoder wrapper (codec wmv2)
| V\..... wmv3_bm bm WMV3 decoder wrapper (codec wmv3)

#### 如何在FFMPEG中查看解码器信息，例如查看jpeg_bm编码器信息?

答：

| root@[linaro-developer:/home/sophgo/test#](http://linaro-developer/home/bitmain/test) ffmpeg
  -h decoder=jpeg_bm
| Decoder jpeg_bm \[BM JPEG DECODER\]:
| General capabilities: avoidprobe
| Threading capabilities: none
| jpeg_bm_decoder AVOptions:
| -bs_buffer_size \<int\> .D.V\..... the bitstream buffer size (Kbytes)
  for bm jpeg decoder (from 0 to INT_MAX) (default 5120)
| -chroma_interleave \<flags\> .D.V\..... chroma interleave of output
  frame for bm jpeg decoder (default 0)
| -num_extra_framebuffers \<int\> .D.V\..... the number of extra frame
  buffer for jpeg decoder (0 for still jpeg, at least 2 for motion jpeg)
  (from 0 to INT_MAX) (default 0)

#### 如何在FFMPEG中查看编码器信息，例如查看jpeg_bm编码器信息?

答：

| root@[linaro-developer:/home/sophgo/test#](http://linaro-developer/home/bitmain/test) ffmpeg
  -h encoder=jpeg_bm
| Encoder jpeg_bm \[BM JPEG ENCODER\]:
| General capabilities: none
| Threading capabilities: none
| Supported pixel formats: yuvj420p yuvj422p yuvj444p
| jpeg_bm_encoder AVOptions:
| -is_dma_buffer \<flags\> E..V\..... flag to indicate if the input
  frame buffer is DMA buffer (default 0)

#### 调用API实现jpeg编码的应用示例

答：

    AVDictionary* dict = NULL;

    av_dict_set_int(&dict, "is_dma_buffer", 1, 0);

    ret = avcodec_open2(pCodecContext, pCodec, &dict);

#### 调用FFMPEG的API实现静态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

    AVDictionary* dict = NULL;

    /* bm_jpeg 解码器的输出是 chroma-interleaved模式,例如, NV12 */

    av_dict_set_int(&dict, "chroma_interleave", 1, 0);

    /* The bitstream buffer 为 3100KB(小于 1920x1080x3),
    /* 假设最大分辨率为 1920x1080 */
    av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
    /* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
    av_dict_set_int(&dict, "num_extra_framebuffers", 0, 0);

    ret = avcodec_open2(pCodecContext, pCodec, &dict);

#### 调用FFMPEG的API实现动态jpeg图片解码时设置jpeg_bm解码器参数的应用示例

答：

    AVDictionary* dict = NULL;

    /* bm_jpeg 解码器输出的是 chroma-separated 模式, 例如, YUVJ420 */

    av_dict_set_int(&dict, "chroma_interleave", 0, 0);

    /* The bitstream buffer 为 3100KB */
    /* 假设最大分辨率为 1920x1080 */
    av_dict_set_int(&dict, "bs_buffer_size", 3100, 0);
    /* 额外的帧缓冲区: 静态jpeg设置为0，动态mjpeg设置为2 */
    av_dict_set_int(&dict, "num_extra_framebuffers", 2, 0);

    ret = avcodec_open2(pCodecContext, pCodec, &dict);

#### \[问题分析\]当用ffmpeg jpeg_bm解码超大JPEG图片的时候，有时候会报"ERROR:DMA buffer size(5242880) is less than input data size(xxxxxxx)\"，如何解决？

> 在用FFMPEG的jpeg_bm硬件解码器解码JPEG图片的时候，默认的输入buffer是5120K。在拿到JPEG文件前提前分配好输入缓存，在MJPG文件解码时可以避免频繁地创建和销毁内存。当出现默认输入buffer大小比输入jpeg文件小的时候，可以通过下面的命令来调大输入缓存。
>
> | av_dict_set_int(&opts, \"bs_buffer_size\", 8192, 0); //注意：
>   bs_buffer_size是以Kbyte为单位的

### bm_opencv问题

#### 4K图片的问题

答：有些客户需要的图片较大如8K等，由于VPP只支持4K大小的图片，所以通过opencv读取图片后，会自动保持比例缩放到一个4K以内的尺寸。

如果客户需要传递原始图片的坐标位置给远端，可以有以下两种做法：

> 1.  imread中设置flag =
>     IMREAD_UNCHANGED_SCALE，此时图片不会真正解码，会在mat.rows/cols中返回图片的原始宽高，然后可根据缩放比例计算得到原图的坐标
> 2.  传递相对坐标给远端，即坐标x/缩放后的宽，
>     坐标y/缩放后的高传递到远端。这步相对坐标计算也可以在远端完成，然后可以根据远端知道的原始图像宽高计算得到正确的原图坐标

#### Opencv imread读取图片性能问题。

原因分析：如果读取尺寸小于16x16的图片，或者progressive
格式的jpeg，不能实现硬件加速，需要软件解码，导致客户发现图片解码并没有加速。

#### 若是采用libyuv处理JPEG方面的输出或者输入，需要注意什么事项？

答：

若是处理jpeg方面的输出或者输入，需要使用J400，J420，J422，J444等字样的函数，不然输出结果会有色差。

原因是JPEG的格式转换矩阵跟视频的不一样。

#### Bm_opencv的imread jpeg解码结果和原生opencv的imread jpeg结果不同，有误差

答：是的。原生opencv使用libjpeg-turbo,而bm_opencv采用了bm168x中的jpeg硬件加速单元进行解码。

误差主要来自解码输出YUV转换到BGR的过程中。1）YUV需要上采样到YUV444才能进行BGR转换。这个upsample的做法没有标准强制统一，jpeg-turbo提供了默认Fancy
upsample，也提供了快速复制上采样的算法，原生opencv在
cvtColor函数中采用了快速复制上采样算法，而在imread和imdecode中沿用了libjpeg-turbo默认的fancy
upsample；而BM168x硬件加速单元采用快速复制的算法。2）YUV444到BGR的转换是浮点运算，浮点系数精度的不同会有+/-1的误差。其中1）是误差的主要来源。

这个误差并不是错误，而是双方采用了不同的upsample算法所导致的,即使libjpeg-turbo也同时提供了两种upsample算法。

如果用户非常关注这两者之间的差异，因为这两者之间的数值差异导致了AI模型精度的下降，我们建议有两种解决办法：

1）设置环境变量 export
USE_SOFT_JPGDEC=1，可以指定仍然使用libjpeg-turbo进行解码。但是这样会导致处理器的loading上升，不推荐

2）可能过去模型太依赖开源opencv的解码结果了，可以用bm_opencv的解码结果重新训练模型，提高模型参数的适用范围。

可以使用libjpeg-turbo提供的djpeg工具对于测试工具集的数据进行重新处理，然后用处理后的数据对模型进行训练。djpeg
的命令如下：

> | ./djpeg -nosmooth -bmp -outfile xxxxx.bmp input.jpg

然后用重新生成bmp文件作为训练数据集，进行训练即可。

#### 使用opencv的imwrite编码的结果和使用bmcv_image_jpeg_enc编码的结果有质量差异（色彩饱和度）。

> 1.  opencv下的imwrite里面有csc convert操作，色彩图像csc
>     type设定的是CSC_RGB2YPbPr_BT601，灰度图是CSC_MAX_ENUM
> 2.  在bmcv_image_jepg_enc的时候，前面调用一下bmcv_image_vpp_csc_matrix_convert接口，同时指定csc
>     type的类型，对齐imwrite里面的csc类型，这样不会有质量差异了

``` 
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

#### bm_image_create、bm_image_alloc_dev_mem、bm_image_attach相关疑问。

> 1.  bm_image_create：用于创建bm_image结构体。
> 2.  bm_image_alloc_dev_mem：申请设备内存，且内部会attach上bm_image。
> 3.  bm_image_attach：用于将从opencv等处获取到的设备内存与bm_image_create申请到的bm_image进行绑定。

#### bm_image_destroy、bm_image_detach相关疑问。

> 1.  bm_image_detach：用于将bm_image关联的设备内存进行解绑，
>     如果设备内存是内部自动申请的，才会释放这块设备内存；如果bm_image未绑定设备内存，则直接返回。
> 2.  bm_image_destroy：该函数内部嵌套调用bm_image_detach。也就是说，调用该函数，如果bm_image绑定的设备内存是通过bm_image_alloc_dev_mem申请，就会释放；
>     如果是通过bm_image_attach绑定的设备内存则不会被释放，此时需要注意该设备内存是否存在内存泄露，如果存在其他模块继续使用，则由相应模块进行释放。
> 3.  总的来说，设备内存由谁申请则由谁释放，如果是通过attach绑定的设备内存，则不能调用
>     bm_image_destroy
>     进行释放，如果确定attach绑定的设备内存不再使用，可通过bm_free_device等接口进行释放。

### bm_ffmpeg问题

#### ffmpeg中做图像格式/大小变换导致视频播放时回退或者顺序不对的情况处理办法

答：ffmpeg在编码的时候底层维护了一个avframe的队列作为编码器的输入源，编码期间应保证队列中数据有效，如果在解码后需要缩放或者像素格式转换时候需要注意送进编码器的avframe的数据有效和释放问题。

在例子ff_bmcv_transcode中从解码输出src-avframe转换成src-bm_image然后做像素格式转换或者缩放为dst-bm_image最后转回dst-avframe 去编码的过程中src-avframe、src-bm_image的设备内存是同一块，dst-avframe、dst-bm_image的设备内存是同一块。在得到dst-bm_image后即可释放src_avframe和src-bm_image的内存（二者释放其中一个即可释放设备内存），作为编码器的输入dts-bm_image在转换成dst-avframe之后其设备内存依然不能被释放（常见的异常情况是函数结束dts-bm_image的引用计数为0导致其被释放），如果dst-bm_image被释放了此时用dst-avframe去编码结果肯定会有问题。

解决方法是dst-bm_image的指针是malloc一块内存，然后将其传给av_buffer_create，这样就保证在函数结束的时候dst-bm_image引用计数不会减1，释放的方法是将malloc的dst-bm_image指针通过av_buffer_create传给释放的回调函数，当dst-avframe引用计数为0的时候会调用回调函数将malloc的指针和dst-bm_image的设备内存一起释放。详见例子ff_bmcv_transcode/ff_avframe_convert.cpp。

### bm_opencv问题

#### Opencv读取图片后，cvMat转为bmimage, 之后，调用bmcv_image_vpp_convert做缩放或者颜色空间转换，得到的图片不一致

原因分析：opencv内部的转换矩阵和bmcv_image_vpp_convert使用的转换矩阵不一致，需要调用bmcv_image_vpp_csc_matrix_covert,
并且指定CSC_YPbPr2RGB_BT601来进行转换才能保持一致。

#### 关于什么时候调用uploadMat/downloadMat接口的问题。

解析：当创建了一个cv::Mat,
然后调用cv::bmcv里面的接口进行了一些处理后，设备内存的内容改变了，这时候需要downloadMat
来同步一下设备内存和系统内存。当调用了cv::resize等opencv原生的接口后，系统内存的内容改变了，需要uploadMat，使设备内存和系统内存同步。

#### 对于VPP硬件不支持的YUV格式转换，采取什么样的软件方式最快？

答：

建议采用内部增强版本的libyuv。

相比较原始版本，增加了许多NEON64优化过的格式转换API函数。其中包含许多JPEG
YCbCr相关的函数。

位置：/opt/sophon/libsophon-current/lib/

#### OpenCV中的BGR格式，在libyuv中对应的那个格式？OpenCV中的RGB格式呢？

答：

-   OpenCV中的BGR格式，在libyuv中对应的格式为RGB24
-   OpenCV中的RGB格式，在libyuv中对应的格式为RAW。

#### 现在opencv中默认是使用ION内存作为MAT的data空间，如何指定Mat对象基于system memory内存去创建使用？

答：

    using namespace cv；

    Mat m; m.allocator = m.getDefaultAllocator();     // get system allocator

然后就可以正常调用各种mat函数了，如m.create()
m.copyto()，后面就会按照指定的allocator来分配内存了。

    m.allocator = hal::getDefaultAllocator();  // get ion allocator

就又可以恢复使用ION内存分配器来分配内存。

#### opencv转bm_image的时候，报错"Memory allocated by user, no device memory assigned. Not support BMCV!"

答：这种错误通常发生在soc模式下，所转换的Mat只分配了系统内存，没有分配设备内存，而bm_image要求必须有设备内存，因此转换失败。而在pcie模式下，接口内部会自动分配设备内存，因此不会报这个错误。

会产生这类问题的Mat通常是由外部分配的data内存attach过去的，即调用Mat(h,
w, data) 或者Mat.create(h,w, data)来创建的，而data!=NULL,由外部分配。

对于这种情况，因为bm_image必须要求设备内存，因此解决方案有

1.  新生成个Mat，默认创建设备内存，然后用copyTo()拷贝一次，把数据移到设备内存上，再重新用这个Mat来转成bm_image
2.  直接创建bm_image，然后用bm_image_copy_host_to_device,将Mat.data中的数据拷贝到bm_image的设备内存中。

#### 调用 bmcv_image_vpp_convert_padding 接口时，报缩放比例超过32倍的错："vpp not support: scaling ratio greater than 32"。

> bm1684的vpp中硬件限制图片的缩放不能超过32倍（bm1684x的vpp中硬件限制图片的缩放不能超过128倍）。即应满足
> dst_crop_w \<= src_crop_w \* 32， src_crop_w \<= dst_crop_w \* 32，
> dst_crop_h \<= src_crop_h \* 32 , src_crop_h \<= dst_crop_h \* 32。
>
> 此问题原因可能是：
>
> 1.  输入 crop_rect 中的crop_w, crop_h 与 输出 padding_attr
>     中的dst_crop_w ，dst_crop_h 缩放比例超过了32倍。
> 2.  crop_rect，padding_attr 值的数量应与 output_num的数量一致。

#### 调用 bmcv_image_vpp_basic 接口时，csc_type_t, csc_type 和 csc_matrix_t\* matrix该如何填？

bmcv中vpp在做csc 色彩转换时，默认提供了4组601系数和4组709系数，
如csc_type_t所示。

1.  csc_type可以填为CSC_MAX_ENUM， matrix填NULL，会默认配置 601
    YCbCr与RGB互转系数。
2.  csc_type可以填csc_type_t中参数，如YCbCr2RGB_BT709，matrix填NULL，会按照所选类型配置对应系数。
3.  csc_type可以填CSC_USER_DEFINED_MATRIX，matrix填自定义系数。会按照自定义系数配置。

csc_matrix_t 中系数参考如下公式：

Y = csc_coe00 \* R + csc_coe01 \* G + csc_coe02 \* B + csc_add0;

U = csc_coe10 \* R + csc_coe11 \* G + csc_coe12 \* B + csc_add1;

V = csc_coe20 \* R + csc_coe21 \* G + csc_coe22 \* B + csc_add2;

由于1684 vpp精度为10位（bm1684x vpp精度为FP32），整数处理。

csc_coe 与 csc_add的计算方法为: csc_coe = round（浮点数 \*
1024）后按整数取补码。

csc_coe取低13bit，即 csc_coe = csc_coe & 0x1fff，csc_add取低21bit，即
csc_add = csc_add & 0x1fffff。

举例如下：

floating-point coe matrix =\> fixed-point coe matrix

0.1826 0.6142 0.0620 16.0000 =\> 0x00bb 0x0275 0x003f 0x004000

#### \[问题分析\]不同线程对同一个bm_imag调用 bm_image_destroy 时，程序崩溃。

bm_image_destroy(bm_image image)
接口设计时，采用了结构体做形参，内部释放了image.image_private指向的内存，但是对指针image.image_private的修改无法传到函数外，导致第二次调用时出现了野指针问题。

为了使客户代码对于sdk的兼容性达到最好，目前不对接口做修改。
建议使用bm_image_destroy（image）后将 image.image_private =
NULL，避免多线程时引发野指针问题。

#### 在bmcv::toBMI之前是否需要调用bm_create_image，如果调用，在最后使用bm_image_destroy会不会引起内存泄露？

1.  bmcv::toBMI内部嵌套调用bm_image_create，无需再次调用bm_create_image。
2.  如果在bmcv::toBMI前调用了bm_create_image，会导致内存泄露。
3.  调用bmcv::toBMI后，除了需要调用bm_image_destroy,还需要image.image_private = NULL。
