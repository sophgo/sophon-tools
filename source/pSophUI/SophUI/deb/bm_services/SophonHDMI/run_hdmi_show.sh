#!/bin/bash -x

#export SOPHON_QT_BG_PATH=sample.png # 配置自定义背景

#export SOPHON_QT_CMD_DEBUG=1 # 是否开启debug

#判断是否为麒麟操作系统
is_kylinos=$(cat /etc/os-release | grep kylinos |wc -l)

# 英文模式
export SOPHON_QT_EN_ENABLE=0

# 内嵌终端默认登陆用户
export SOPHON_QT_LOGIN_USER="linaro"

# QT程序左下部分内容函数
function SOPHON_QT_2() {
        if [[ "$SOPHON_QT_EN_ENABLE" == "1" ]]; then
                echo "Version Info:"
        else
                echo "版本信息:"
        fi
        bm_version;
}
export -f SOPHON_QT_2

# # QT程序右下角详细信息按钮内容函数
# function SOPHON_QT_3() {
#         ip a;
#         ip route;
#         cat /etc/netplan/*;
# }
# export -f SOPHON_QT_3

# QT程序重置网络操作函数
function SOPHON_QT_4() {
        rm -rf /etc/netplan/*;
        cp -a /media/root-ro/etc/netplan/* /etc/netplan/;
        sync;
        netplan apply;
}
export -f SOPHON_QT_4

CPU_MODEL=$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)
if [ "$CPU_MODEL" == "bm1688" ] || [ "$CPU_MODEL" == "cv186ah" ];then
        function SOPHON_QT_1() {
                if [[ "$SOPHON_QT_EN_ENABLE" == "1" ]]; then
                        echo "Device Info:"
                else
                        echo "设备信息:"
                fi
                bm_get_basic_info | grep -v '\-\-\-';
                # tpuU=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | awk '{print $1}' | awk -F':' '{print $2}');
                tpuU=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | sed 's/^/\t/');
                cpuU=$(top -bin1 | grep "Cpu(s)" | awk '{print $2 + $4}');
                echo "TPU(%):$tpuU";
                echo "CPU(%):$cpuU";
        }
        export -f SOPHON_QT_1

        get_edid=$(sudo get-edid -b 11 2>/dev/null | parse-edid 2>/dev/null | awk '/DisplaySize/ {if ($2 == 0 || $3 == 0) {print ""} else{print "get-edid"}}')
        if [ "$get_edid" == ""  ]; then
                export QT_QPA_EGLFS_PHYSICAL_WIDTH=487
                export QT_QPA_EGLFS_PHYSICAL_HEIGHT=274
        fi

        export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/lib/aarch64-linux-gnu/qt5/plugins
        export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib/aarch64-linux-gnu/qt5/lib
        export QT_QPA_FB_DRM=1
        export QT_QPA_PLATFORM=linuxfb:fb=/dev/dri/card0


        #specify connector index if not specify,use the first connected connector
        #export QT_QPA_EGLFS_KMS_CONNECTOR_INDEX=1

        #使用该环境变量配置程序默认字体大小
        export SOPHON_QT_FONT_SIZE=20

        # hdmi status file
        status_file="/sys/class/drm/card0-HDMI-A-1/status"

        hdmi_status="unknown"

        systemctl stop getty@tty1.service
        set +x
        while true; do
        # get hdmi status
        new_hdmi_status=$(cat "$status_file")
        # if hdmi status changed; do
        if [ "$new_hdmi_status" != "$hdmi_status" ]; then
                hdmi_status="$new_hdmi_status"
                if [ "$hdmi_status" = "connected" ]; then
                        # ensure card0 is not in use.
                        if [ ! -n "$(lsof /dev/dri/card0|head -n 1)" ];then
                                # hdmi connected
                                echo "HDMI connected and card0 not in use. Starting SophUI."
                                # start SophUI
                                ./SophUI 1>/dev/null 2>&1 &
                        else
                                echo "HDMI connected.However card0 is in use,can't start SophUI"
                        fi
                else
                        echo "HDMI disconnected. Stopping SophUI."
                        # stop SophUI
                        pkill -f "SophUI"
                fi
        fi
        # sleep
        sleep 1
        done
else
        # QT程序左上角内容函数
        function SOPHON_QT_1() {
                if [[ "$SOPHON_QT_EN_ENABLE" == "1" ]]; then
                        echo "Device Info:"
                else
                        echo "设备信息:"
                fi
                bm_get_basic_info | grep -v '\-\-\-';
                tpuU=$(cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | awk '{print $1}' | awk -F':' '{print $2}');
                cpuU=$(top -bin1 | grep "Cpu(s)" | awk '{print $2 + $4}');
                chip_reg_flag=$(busybox devmem 0x50010000)
                if [[ "$chip_reg_flag" == "0x16860000" ]]; then
                        echo "chip type: bm1684x"
                elif [[ "$chip_reg_flag" == "0x16840000" ]]; then
                        echo "chip type: bm1684"
                fi
                echo "TPU: $tpuU%";
                echo "CPU: $cpuU%";
        }
        export -f SOPHON_QT_1

        fl2000=$(lsmod | grep fl2000 | awk '{print $1}')

        echo $fl2000
        if [ "$fl2000" != "fl2000" ]; then
                echo "insmod fl2000"
        else
                echo "fl2000 already insmod"
        fi

        if [ $is_kylinos -gt 1 ]; then
                function SOPHON_QT_4() {
                        systemctl stop NetworkManager
                        rm -rf /etc/NetworkManager/system-connections/*
                        systemctl start NetworkManager
                        /usr/sbin/bm_set_ip eth1 192.168.150.1 255.255.255.0 '' ''
                        /usr/sbin/bm_set_ip_auto eth0
                }
                export -f SOPHON_QT_4
        else
                export PATH=$PATH:/opt/bin:/bm_bin
                export QTDIR=/usr/lib/aarch64-linux-gnu #qtsdk在系统上的路径
                export QT_QPA_FONTDIR=$QTDIR/fonts
                export QT_QPA_PLATFORM_PLUGIN_PATH=$QTDIR/qt5/plugins/
                export LD_LIBRARY_PATH=/opt/lib:$LD_LIBRARY_PATH
                export QT_QPA_PLATFORM=linuxfb:fb=/dev/fl2000-0 #framebuffer驱动
                # for ms91xx
                # export QT_QPA_PLATFORM=linuxfb:ms91xxmode=2
        fi
        export SOPHON_QT_FONT_SIZE=20 #使用该环境变量配置程序默认字体大小
        SophUI_path=/bm_services/SophonHDMI/
        SophUIDEMO_path=${SophUI_path}/SophUIDEMO.sh

        mkdir -p /dev/input/

        while true; do
                rm -f $SophUIDEMO_path
                if [ $is_kylinos -gt 1 ]; then
                        /usr/bin/xinit ${SophUI_path}/SophUI
                else
                        ${SophUI_path}/SophUI
                fi
                ret=$?
                if [ $ret -ne 0 ]; then
                echo "SophUI exited with error code: $ret"
                exit $ret
        fi
                if [ -e "$SophUIDEMO_path" ]; then
                        chmod +x $SophUIDEMO_path
                        bash -x $SophUIDEMO_path
                                ret=$?
                                if [ $ret -ne 0 ]; then
                                        echo "SophUIDEMO exited with error code: $ret"
                                        exit $ret
                                fi
                else
                        echo "File does not exist: $SophUIDEMO_path"
                fi
        done
fi
