import model_base
import time

class serialCom_simcom(model_base.serialCom):
    # 获取当前设备的usb mode信息
    def get_usbmode(self):
        cmd = "AT$MYCONFIG?\r"
        self.send_msg(cmd)
        time.sleep(3)
        ret = self.recive_msg().decode("utf-8")
        res = ret.splitlines()[1].split(':')[1].split(',')[1].strip()
        if res == "0":
            return "RNDIS"
        elif res == "1":
            return "ECM"
        elif res == "2":
            return "AUTO"
        else:
            print("usbmode none: " + res)
            return "None"

    # 修改当前设备usb mode为ECM
    def switch_to_ecm(self):
        cmd = "AT$MYCONFIG=\"USBNETMODE\",1,1\r"
        self.send_msg(cmd)
        print("Change USBNETMODE to ECM")
        print("Wait model reset...")
        self.serial = "auto"
        time.sleep(10)
        self.serial_open()
        return 0

    # 初始化串口连接，判断串口是否成功连接
    def serial_open(self):
        ret_1 = self.init_serial()
        if ret_1 == 0:
            print("serial open success")
            self.serial_check()
        else:
            print("serial open failed")
            self.serial_open()

    # 检查模组是否可以正常进行数据的收发
    def serial_check(self):
        ret_1 = self.check_serial()
        if ret_1 == 0:
            print("serial is ready")
            print("start checking usb mode")
            self.check_ecm_mode()
        else:
            print("Cannot communicate with port")
            self.serial_check()

    # 检查当前模组模式是否为ECM模式，如不是，则切换为ECM模式
    def check_ecm_mode(self):
        ret_1 = self.get_usbmode()
        print("now status:", ret_1)
        if ret_1 != "ECM":
            print("to ecm mode")
            ret_2 = self.switch_to_ecm()
            if ret_2 == 0:
                self.check_ecm_mode()
        else:
            self.simcard_check()

    # 检查SIM卡状态
    def simcard_check(self):
        ret_1 = self.check_simcard_insert()
        if ret_1 == 0:
            print("SIM card inserted successfully")
            ret_2 = self.check_signal()
            if 21 <= ret_2 <= 31:
                print("Signal level is " + str(ret_2) + ", which means good")
            elif 12 <= ret_2 < 21:
                print("Signal level is " + str(ret_2) + ", which means generally")
            elif 1 <= ret_2 < 12:
                print("Signal level is " + str(ret_2) + ", which means terrible")
            else:
                print("Signal level is " + str(ret_2) + ", which means Unknown. \n \
                    Please confirm the antenna status or choose a place with good signal to place the device")
            ret_3 = self.check_isp()
            if ret_3 == -1:
                print("The sim card is not connected to the network")
            else:
                if ret_3 == 7:
                    print("Current network mode is 4G")
                elif ret_3 == 2:
                    print("Current network mode is 3G")
                elif ret_3 == 0:
                    print("Current network mode is 2G")
                elif ret_3 == 11:
                    print("Current network mode is 5G")
                else:
                    print("Current network mode is unknown")
                self.dial()
        elif ret_1 == -1:
            print("SIM card insertion check failed")
        elif ret_1 == 10:
            print("SIM not inserted")
        else:
            print("Unknown Error")

    # 进行拨号并获取IP
    def dial(self):
        print("start checking apn")
        self.parseAPN(self.apn)
        print("\nAPN:", self.apn)
        print("\nStart dialing")
        cmd = "AT \r"
        self.send_msg(cmd)
        time.sleep(1)
        _ = self.recive_msg().decode("utf-8")
        cmd = "AT+DIALMODE=0\r"
        self.send_msg(cmd)
        time.sleep(1)
        _ = self.recive_msg().decode("utf-8")
        ret_1 = self.start_dial()
        if ret_1 == 0:
            print("\nDialing Success")
            print("Start getting IP")
            ret_2 = self.DHCP()
            if ret_2 == 0:
                print("DHCP success")
                print("start monitor")
                self.start_monitor()
            else:
                print("DCHP Error")
        else:
            print("Retry dialing")
            self.dial()

    # 开始监控，当网络状态不好时重新进行拨号
    def start_monitor(self):
        ret_1 = self.monitor()
        if ret_1 == -1:
            self.simcard_check()

    def run(self):
        self.serial_open()


