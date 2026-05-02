import model_base
import time

class serialCom_fibocom(model_base.serialCom):
    def _run_at_step(self, command, wait_seconds, step_name):
        print("fibocom dial step:", step_name, "cmd:", command.strip())
        self.send_msg(command)
        time.sleep(wait_seconds)
        ret = self.recive_msg().decode("utf-8")
        print("fibocom dial step response:", step_name, ret.strip())
        if "ERROR" in ret.strip().split():
            return -1, ret
        return 0, ret

    def _has_ip_address(self, response):
        for line in response.splitlines():
            if "+CGPADDR:" not in line:
                continue
            if '"' in line:
                for value in line.split('"')[1::2]:
                    if value.strip():
                        return True
            parts = [item.strip() for item in line.split(",")]
            for value in parts[1:]:
                if value:
                    return True
        return False

    def _run_at_no_check(self, command, wait_seconds, step_name):
        print("fibocom dial step(no check):", step_name, "cmd:", command.strip())
        self.send_msg(command)
        time.sleep(wait_seconds)
        ret = self.recive_msg().decode("utf-8")
        print("fibocom dial step response(no check):", step_name, ret.strip())
        return ret

    # 获取当前设备的usb mode信息
    def get_usbmode(self):
        cmd = "AT+GTUSBMODE?\r"
        self.send_msg(cmd)
        time.sleep(3)
        ret = self.recive_msg().decode("utf-8")
        res = ret.splitlines()[1].split(':')[1].strip()
        return res

    # 修改当前设备usb mode为ECM
    def switch_to_ecm(self):
        cmd = "AT+GTUSBMODE=18\r"
        self.send_msg(cmd)
        time.sleep(3)
        ret = self.recive_msg().decode("utf-8")
        print("Change GTUSBMODE to ECM")
        return 0

    def start_dial(self):
        for pdp_type in self.get_pdp_type_candidates():
            print("start fibocom dial with pdp type:", pdp_type)
            dial_steps = [
                ("AT+CGACT=0,1\r", 3, "deactivate pdp context"),
                ("AT+CGDCONT=1,\"" + pdp_type + "\",\"" + self.apn + "\"\r", 5, "configure pdp context"),
                ("AT+CGATT=1\r", 5, "attach packet service"),
                ("AT+CGACT=1,1\r", 5, "activate pdp context"),
            ]

            self.active_pdp_type = pdp_type
            dial_failed = False
            for command, wait_seconds, step_name in dial_steps:
                status, _ = self._run_at_step(command, wait_seconds, step_name)
                if status != 0:
                    print("fibocom dial failed at step:", step_name, "pdp type:", pdp_type)
                    dial_failed = True
                    break

            if dial_failed:
                print("fallback to next pdp type after dial step failure:", pdp_type)
                continue

            self._run_at_no_check("AT+GTRNDIS=1,1\r", 10, "enable rndis/ecm dial")

            status, cgpaddr_ret = self._run_at_step("AT+CGPADDR\r", 3, "query ip address")
            if status != 0 or not self._has_ip_address(cgpaddr_ret):
                print("fibocom dial ip check failed, pdp type:", pdp_type)
                print("fallback to next pdp type after ip check failure:", pdp_type)
                continue

            status, _ = self._run_at_step("AT+CGDCONT?\r", 3, "query pdp context")
            if status != 0:
                print("fibocom dial pdp context query failed, pdp type:", pdp_type)
                print("fallback to next pdp type after pdp query failure:", pdp_type)
                continue

            print("fibocom dial success, active pdp type:", self.active_pdp_type)
            return 0

        print("fibocom dial failed for all pdp type candidates")
        return -1

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
        if ret_1 != "18":
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
        ret_1 = self.start_dial()
        if ret_1 == 0:
            print("Final PDP type:", self.active_pdp_type)
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


