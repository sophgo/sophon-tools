import time
import subprocess

import fibocom_base
import redcap_base
import simcom_bash

# 这里以字典的方式记录适配设备的VID与PID，用于开机后检查设备是否成功链接
# 在使用过程中如果有新适配的设备，可以将其添加到该字典中
model_dict = {"NL668": ["1508:1001"],
              "FM650": ["2cb7:0a05", "2cb7:0a06", "2cb7:0a07"],
              "redcap": ["3466:3301"],
              "simcom": ["1e0e:9011"]}

# 对字典中存放的设备进行遍历，查看当前适配的是哪一个模组，如果检查到对应的设备，则启动对应设备的拨号流程
# 在完成设备查找前，会每3s对设备进行一次检查，运行300s未检查到设备时，进程退出，需要检查模组与设备链接是否正常
def choose_model():
    cnt = 0
    find_dev = False
    # 开始轮询检查设备
    while True:
        for k, v in model_dict.items():
            for dev_id in v:
                cmd = "lsusb | grep " + dev_id
                status, output = subprocess.getstatusoutput(cmd)
                if status == 0:
                    dev = k
                    find_dev = True
                    break
            if find_dev == True:
                break
        cnt +=1
        if cnt == 100 or find_dev == True:
            break
        time.sleep(3)
    # 未检查到设备时退出
    if not find_dev:
        print("module can not find")
        exit(1)

    # 检查到设备时启动对应拨号流程
    # 接口接入的三个参数说明如下：
    # 1. 指定通信串口：指向需要使用的通信串口，auto模式下会自动查询
    # 2. 指定需要使用的apn，auto模式下会自动查询已知apn；
    # 3. 用于判断网络是否稳定的target，会通过ping该target的方式判断了当前网络连接情况
    idx = list(model_dict.keys()).index(dev)
    if idx == 0:
        sc = fibocom_base.serialCom_fibocom("auto", "auto", "1.1.1.1")
        sc.run()
    elif idx == 1:
        sc = fibocom_base.serialCom_fibocom("auto", "auto", "1.1.1.1")
        sc.run()
    elif idx == 2:
        sc = redcap_base.serialCom_redcap("auto", "auto", "1.1.1.1")
        sc.run()
    elif idx == 3:
        sc = simcom_bash.serialCom_simcom("auto", "auto", "1.1.1.1")
        sc.run()


if __name__=="__main__":
    choose_model()
