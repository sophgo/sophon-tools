import model_base


class LBS(model_base.serialCom):
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
            self.simcard_check()
        else:
            print("Cannot communicate with port")
            self.serial_check()

    # 检查当前模组模式是否为ECM模式，如不是，则切换为ECM模式

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
                self.lbs()
        elif ret_1 == -1:
            print("SIM card insertion check failed")
        elif ret_1 == 10:
            print("SIM not inserted")
        else:
            print("Unknown Error")

    # 进行拨号并获取IP
    def lbs(self):
        print("\nStart get lbs info")
        self.LBS()

    def run(self):
        self.serial_open()

if __name__=="__main__":
    lbs = LBS()
    lbs.run()
