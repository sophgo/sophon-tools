import model_base
import fibocom_base
import time

class serialCom_fibocom_fm650cn(fibocom_base.serialCom_fibocom):
    def _normalize_signal_value(self, value, max_value):
        if value is None or value < 0 or value > max_value:
            return -1
        return max(1, min(31, int(value * 31 / max_value)))

    # 修改当前设备usb mode为ECM
    def switch_to_ecm(self):
        cmd = "AT+GTUSBMODE=34\r"
        self.send_msg(cmd)
        time.sleep(3)
        ret = self.recive_msg().decode("utf-8")
        print("Change GTUSBMODE to ECM")
        return 0

    # 检查当前模组模式是否为ECM模式，如不是，则切换为ECM模式
    def check_ecm_mode(self):
        ret_1 = self.get_usbmode()
        print("now status:", ret_1)
        if ret_1 != "34":
            print("to ecm mode")
            ret_2 = self.switch_to_ecm()
            if ret_2 == 0:
                self.check_ecm_mode()
        else:
            self.simcard_check()

    # 检查设备当前信号质量,5G信号质量的查询方式与4G不同，因此需要重写该函数
    # 当信号质量在正常范围内时，返回当前信号质量
    # 当信号质量为99时，返回-1
    def check_signal(self):
        print("\nstart check signal")
        msg = "AT+CSQ\r"
        self.send_msg(msg)
        time.sleep(1)
        ret = self.recive_msg().decode("utf-8")
        res = int(ret.strip().split("\n")[0].strip().split(":")[1].split(",")[0].strip())
        if 1 <= res <= 31:
            return res
        else:
            print("use AT+CESQ to check 5G signal")
            # +CESQ:<rxlev>,<ber>,<rscp>,<ecno>,<rsrq>,<rsrp>,<ss_rsrq>,<ss_rsrp>,<ss_sinr>
            msg = "AT+CESQ\r"
            self.send_msg(msg)
            time.sleep(1)
            ret = self.recive_msg().decode("utf-8")
            cesq_line = ""
            for line in ret.strip().split("\n"):
                if "+CESQ:" in line:
                    cesq_line = line
                    break

            if not cesq_line:
                return -1

            try:
                values = [int(item.strip()) for item in cesq_line.split(":", 1)[1].split(",")]
            except (IndexError, ValueError):
                return -1

            if len(values) < 9:
                return -1

            signal_candidates = [
                self._normalize_signal_value(values[7], 127),
                self._normalize_signal_value(values[5], 97),
                self._normalize_signal_value(values[2], 96),
            ]

            for signal_value in signal_candidates:
                if 1 <= signal_value <= 31:
                    return signal_value

            return -1

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
