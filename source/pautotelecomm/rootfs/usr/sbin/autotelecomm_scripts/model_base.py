import serial
import os
import glob
import subprocess
import time
import yaml

# 这里提供了ECM拨号过程中的一些基础指令
# 在拨号流程脚本中，通过对这里的拨号指令进行组合，从而达到完成拨号的效果

class serialCom:
    # 初始化，在初始化的过程中获取使用者需要使用的设备，apn，以及网络连接情况检测对象
    # serial为使用者需要使用的设备文件名，通常情况下，设备文件名为/dev/ttyUSB[0-9]+，在设备文件名已知的情况下，可以将auto修改为已知的设备文件名
    # 当设备文件名设置为auto的时候，会自动寻找可以进行通信的设备文件名
    # apn为使用者当前设备需要使用的apn，apn会根据不同的运营商有所不同
    # 例如，移动常用apn为cmnet，联通常用apn为3gnet，电信常用apn为ctnet，此外，物联网卡/白卡通常会有自己独特的apn，需要在使用前与运营商进行沟通
    # monitor_target为检测连接是否正常的目标，使用者可以指定自己需要使用的访问对象
    def __init__(self, serial="auto", apn="auto", monitor_target="www.baidu.com"):
        self.ethname = ""
        self.serial = serial
        self.apn = apn
        self.monitor_target = monitor_target
        self.isp = ""
        self.dhclient_path = ""
        self.apn_list = {"3gnet": ["CHN-CU", "CHN-UN", "CHINA UNICOM", "CHN-UNICOM", "UNICOM", "46001"],
                         "ctnet": ["CHN-TE", "CHINA Te", "CHN-CT", "CT", "46011"],
                         "cmnet": ["CHN-CM", "CHINA MO", "CHINA MOBILE", "CMCC", "46000"]}

    # 当serial设置为auto的时候，会通过该函数自行查找可以通信的设备文件名
    def search_serial(self):
        print("Start checking serial")
        s_pattern = "/dev/ttyUSB*"
        dev = glob.glob(s_pattern)
        dev.sort()
        find_dev = False
        cnt = 0
        while True:
            for ser_name in dev:
                print(ser_name)
                try:
                    self.ser = serial.Serial(ser_name, 115200, timeout=1)
                except Exception as e:
                    print("try uart error: ")
                    print(e)
                    continue
                msg = "AT \r"
                self.send_msg(msg)
                time.sleep(1)
                ret = self.recive_msg().decode("utf-8")
                # print(ret.split())
                if "OK" in ret.strip().split():
                    self.serial = ser_name
                    find_dev = True
                    break
                self.ser.close()
            if find_dev:
                break
            else:
                cnt += 1
                if cnt == 100:
                    print("auto check failed!")
                    exit(1)
                time.sleep(3)
        self.init_serial()


    # 基础功能，通过串口通信的方式向设备发送信息
    def send_msg(self, msg):
        print("-----start send message:", msg)
        self.ser.write(str(msg).encode('utf-8'))

    # 基础功能，在send_msg后获取设备的返回
    def recive_msg(self):
        print("-----start receive message:")
        self.get_ret = 0
        cnt = 0
        data = "".encode('utf-8')
        while self.ser.isOpen():
            cnt +=1
            while self.ser.inWaiting() > 0:
                data = self.ser.read(64)
                self.get_ret = 1
                if self.get_ret:
                    break
            if self.get_ret:
                break
            time.sleep(1)
            if cnt == 5:
                break
        print("-----start receive message:", data)
        return data

    # 基础功能，判断当前是否指定通信设备，auto参数下会自动寻找
    # 建立与设备的串口通信，建立成功返回0，不成功返回-1
    def init_serial(self):
        print("start init serial")
        if self.serial == "auto":
            self.search_serial()
        else:
            if not os.path.exists(self.serial):
                print("Please check", self.serial, "is exist or not")
                exit(1)
        self.ser = serial.Serial(self.serial, 115200, timeout=1)
        if self.ser.isOpen():
            return 0
        else:
            return -1

    # 基础功能，检查串口是否可以正常通信，同时关闭串口回显
    # 串口可以正常使用且回显关闭成功返回0，不成功返回-1
    def check_serial(self):
        print("\ncheck serial is ready or not")
        msg = "ATE0 \r"
        self.send_msg(msg)
        time.sleep(1)
        ret = self.recive_msg().decode("utf-8")
        res = ret.strip().split()[0]
        if res.strip() == "OK":
            return 0
        else:
            return -1

    # 检查SIM卡插入状态
    # 当插入状态正确时返回0
    # 正确插入后依然无法检测到卡，返回-1
    # SIM卡未插入，返回错误码10
    # 其他状态返回-2，需要进一步判断
    def check_simcard_insert(self):
        print("\nstart check sim card")
        msg_1 = "AT+CPIN? \r"
        self.send_msg(msg_1)
        time.sleep(1)
        ret_1 = self.recive_msg().decode("utf-8")
        cmd_1 = ret_1.split("\n")[0]
        res_1 = ret_1.split("\n")[1]
        print(ret_1.strip().split("\n")[0].strip())
        if ret_1.strip().split("\n")[0].strip() == "+CPIN: READY":
            return 0
        elif res_1.strip() == "ERROR":
            return -1
        elif ret_1.strip() == "+CME ERROR: 10":
            return 10
        else:
            return -2

    # 检查设备当前信号质量
    # 当信号质量在正常范围内时，返回当前信号质量
    # 当信号质量为99时，返回-1
    def check_signal(self):
        print("\nstart check signal")
        msg = "AT+CSQ \r"
        self.send_msg(msg)
        time.sleep(1)
        ret = self.recive_msg().decode("utf-8")
        res = int(ret.strip().split("\n")[0].strip().split(":")[1].split(",")[0].strip())
        if 1 <= res <= 31:
            return res
        else:
            return -1

    # 检查设备运营商信息与入网网段
    # sim卡入网正常的情况下返回当前入网网段
    # 未入网等不正常情况下返回-1
    def check_isp(self):
        print("\nstart checking isp")
        msg = "AT+COPS? \r"
        self.send_msg(msg)
        time.sleep(1)
        ret = self.recive_msg().decode("utf-8")
        if len(ret.strip().split()) > 1:
            signal = int(ret.split(",")[-1].strip().split()[0])
            self.isp = ret.strip().split("\"")[-2]
            print(self.isp)
            return signal
        else:
            return -1

    # 发送ECM拨号指令
    # 指令被成功接收返回0，失败返回-1
    def start_dial(self):
        cmd = "AT\r"
        self.send_msg(cmd)
        time.sleep(1)
        _ = self.recive_msg().decode("utf-8")
        msg = "AT+CGDCONT=1,\"IP\",\"" + self.apn + "\" \r"
        self.send_msg(msg)
        time.sleep(5)
        ret = self.recive_msg().decode("utf-8")
        if "OK" in ret.strip().split():
            return 0
        else:
            return -1

    # 使网卡获取动态IP
    def DHCP(self):
        ret = self.NetworkTools()
        if ret == 0:
            msg = 'ip a | grep enx'
            _, output = subprocess.getstatusoutput(msg)
            self.ethname = output.split(":")[1].strip()
            if len(self.ethname) <= 0:
                msg = "ip a | grep usb0"
                status, output = subprocess.getstatusoutput(msg)
                if status != 0:
                    print("Network port query failed")
                    exit(1)
                self.ethname = output.split(":")[1].strip()
            if len(self.ethname) <= 0:
                print("Network port query failed")
                exit(1)

            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(script_dir, 'dhclient-script')
            if self.dhclient_path == "":
                cmd = "dhclient -sf " + script_path + " " + self.ethname
            else:
                cmd = self.dhclient_path + " -sf " + script_path + " " + self.ethname
            try:
                os.system(cmd)
            except Exception as e:
                print("DCHP Error")
                return -1
        else:
            exit(1)
        return 0

    # 运行网络质量监控，通常情况下会支持进行，当一段时间（这里设置为3分钟）无法ping通指定地址或域名后，返回-1
    def monitor(self):
        host = self.monitor_target
        cnt = 0
        time.sleep(30)
        while(True):
            msg = "ping -c4 -I " + self.ethname + " " + host
            status, output = subprocess.getstatusoutput(msg)
            time.sleep(30)
            print(msg, status)
            if status != 0:
                cnt += 1
            else:
                cnt = 0
            if cnt == 3:
                break
        return -1

    # 获取基站定位信息
    def LBS(self, apikey="default"):
        cmd = "AT+MIPCALL=1,\"" + self.apn+ "\" \r"
        self.send_msg(cmd)
        time.sleep(3)
        ret = self.recive_msg().decode("utf-8")
        cmd_2 = "AT+GTGIS=6 \r"
        self.send_msg(cmd_2)
        ret2 = self.recive_msg(128).decode("gbk")
        print(ret2)
        print(ret2.strip().split())
        return -1

    # 解析APN信息
    def parseAPN(self, apn_info):
        if apn_info == "auto":
            for apn, isp_list in self.apn_list.items():
                if self.isp in isp_list:
                    self.apn = apn
                    return 0
            print("apn search failed, please check input apn")
            exit(1)
        else:
            self.apn = apn_info
            return 0

    # 重置模组
    def reset_module(self):
        self.ser = serial.Serial(self.serial, 115200, timeout=1)
        cmd = "AT+RESET=1 \r"
        self.send_msg(cmd)
        self.ser.close()
        print("send reset")

    # 判断当前使用的网络管理工具是netplan还是networkmanager
    # 都存在的情况下会以netplan优先
    def NetworkTools(self):
        cmd1 = "$(which dhclient) --help"
        cmd2 = "$(which ip) a"
        status1, _ = subprocess.getstatusoutput(cmd1)
        status2, _ = subprocess.getstatusoutput(cmd2)
        if status1 == 0 and status2 == 0:
            return 0
        elif status1 != 0 and status2 == 0:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.dhclient_path = os.path.join(script_dir, 'dhclient')
            print("cannot find dhclient, use " + self.dhclient_path)
            return 0
        else:
            print("please check network manager tool: dhclient, ip")
            exit(1)

    # 获取当前设备的usb mode信息
    def get_usbmode(self):
        return "BASE MODEL, NO THIS INFO"

    # 修改当前设备usb mode为ECM
    def switch_to_ecm(self):
        return "BASE MODEL, NO THIS INFO"
