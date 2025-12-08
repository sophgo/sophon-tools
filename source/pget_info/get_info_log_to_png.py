import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.ticker import AutoLocator, ScalarFormatter, MaxNLocator
import yaml
import argparse
import os
import math
from decimal import Decimal, getcontext

getcontext().prec = 50

colors = list(mcolors.TABLEAU_COLORS.keys())

parser = argparse.ArgumentParser(description="get info log file to png")
parser.add_argument('--config', type=str,
                    help='Path to the configuration file')
parser.add_argument('--log', type=str, help='Path to the log file')
args = parser.parse_args()

if not os.path.exists(args.config):
    print(f"Error: Configuration file '{args.config}' not found.")
    exit(1)
if not os.path.exists(args.log):
    print(f"Error: Log file '{args.log}' not found.")
    exit(1)

with open(args.config, 'r') as file:
    configs = yaml.safe_load(file)
if configs is None:
    exit(-1)
print("configs:", configs)

log_name = args.log
boot_time_data = []
boot_ost_time_data = []
x_value = []
reboot_flag = []
infos_data = {"": []}
basic_time = 0
warrning_info = ""

warrning_info += "Cannot find data: "

for index, _ in enumerate(configs["info"]):
    configs["info"][index]["has_data"] = False
    print("Index: ", index, " Name: ", configs["info"][index]["name"], " y_name: ", configs["info"]
          [index]["y_name"], " sampling_index: ", configs["info"][index]["sampling_index"])

with open(log_name, 'r') as file:
    while True:
        line = file.readline()
        if not line:
            break
        if line.find("BOOT_TIME(s)") >= 0:
            ost_time = int(line.split("|")[-2].split(".")[0])/60
            if len(boot_time_data) > 0:
                if ost_time < boot_ost_time_data[len(boot_ost_time_data)-1]:
                    basic_time = boot_time_data[len(boot_time_data)-1]
                    print("System Reboot Detected! New basic time:", basic_time, " min")
                    reboot_flag.append(basic_time)
            curr_time = ost_time + basic_time
            boot_ost_time_data.append(ost_time)
            boot_time_data.append(curr_time)
            print("Find BOOT_TIME:", curr_time, " min")
        for index in range(len(configs["info"]) - 1, -1, -1):
            item = configs["info"][index]
            if line.find(item["info_name"]) >= 0:
                if infos_data.get(item["name"]) is None:
                    infos_data[item["name"]] = []
                try:
                    item_data = line.split(
                        "|")[-2].split(" ")[0 + item["sampling_index"][0]].split(",")[0 + item["sampling_index"][1]]
                except Exception as e:
                    item_data = ""
                    print("Warring: Index ",
                          item["name"], " cannot find data in log file, del it")
                    warrning_info += (item["name"] + " ")
                    del configs["info"][index]
                    continue
                if item_data == "":
                    print("Warring: Index ",
                          item["name"], " cannot find data in log file, del it")
                    warrning_info += (item["name"] + " ")
                    del configs["info"][index]
                    continue
                else:
                    data = Decimal(item_data)
                if item.get("max") is not None:
                    data = min(data, item["max"])
                if item.get("min") is not None:
                    data = max(data, item["min"])
                infos_data[item["name"]].append(data)
                configs["info"][index]["has_data"] = True

for index in range(len(configs["info"]) - 1, -1, -1):
    if configs["info"][index]["has_data"] == False:
        print("Warring: Index ", configs["info"]
              [index]["name"], " has no data, del it")
        warrning_info += (configs["info"][index]["name"] + " ")
        del configs["info"][index]


def plan_square_frame(num_squares):
    if num_squares == 0:
        num_squares = 1
    # 计算接近正方形的行和列
    cols = int(num_squares ** 0.5)  # 计算列数
    rows = (num_squares + cols - 1) // cols  # 计算行数，确保总数不小于num_squares
    return cols, rows


rows = 0
cols = 0
cols, rows = plan_square_frame(len(configs["info"]))
print("rows:", rows)
print("cols:", cols)

if len(boot_time_data) <= 0:
    print("BOOT TIME is Empty!!!!")
    exit(-1)

basic_time = boot_time_data[0]
boot_time_data = [x - basic_time for x in boot_time_data]
reboot_flag = [x - basic_time for x in reboot_flag]

print("Start draw pic...")

plt.style.use("fast")
fig, axs = plt.subplots(rows, cols, figsize=(rows * 8, cols * 8))

pos = []
for j in range(cols):
    for i in range(rows):
        if j*rows+i >= len(configs["info"]):
            break
        if (cols > 1):
            ax = axs[i, j]
        else:
            ax = axs[i]
        data_temp = infos_data[configs["info"][j*rows+i]["name"]]
        if len(data_temp) < len(boot_time_data):
            print("Warring: data num is: ", len(data_temp),
                  "and boot time num is: ", len(boot_time_data))
            for ii in range(0, len(boot_time_data) - len(data_temp)):
                data = data_temp[-1]
                if configs["info"][j*rows+i].get("max") is not None:
                    data = min(data, configs["info"][j*rows+i]["max"])
                if configs["info"][j*rows+i].get("min") is not None:
                    data = max(data, configs["info"][j*rows+i]["min"])
                data_temp.append(data)
        ax.set_xlim(left=boot_time_data[0], right=boot_time_data[-1])
        ax.scatter(boot_time_data, data_temp, s=configs["point_size"], color=(
            "red"), label=configs["info"][j*rows+i]["y_name"])
        if configs["info"][j*rows+i].get("min") is not None:
            ax.set_ylim(bottom=configs["info"][j*rows+i].get("min"))
        if configs["info"][j*rows+i].get("max") is not None:
            ax.set_ylim(top=configs["info"][j*rows+i].get("max"))
        ax.xaxis.set_major_locator(AutoLocator())
        ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.yaxis.set_major_locator(AutoLocator())
        ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        reboot_label_flag = 0
        for root_flag in reboot_flag:
            if reboot_label_flag == 0:
                ax.axvline(x=root_flag, color='green', linestyle='--',
                           linewidth=1, label=f'reboot flag')
                reboot_label_flag = 1
            else:
                ax.axvline(x=root_flag, color='green',
                           linestyle='--', linewidth=1)
        if configs["info"][j*rows+i].get("y_flag") is not None:
            y_flag_count = 0
            for item in configs["info"][j*rows+i].get("y_flag"):
                ax.axhline(
                    y=item, color=mcolors.TABLEAU_COLORS[colors[y_flag_count]], alpha=0.3, linewidth=3, label=f'{item:.1f}')
                y_flag_count = y_flag_count+1
        ax.spines['top'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.set_ylabel(configs["info"][j*rows+i]["y_name"])
        ax.set_title(configs["info"][j*rows+i]["y_name"])
        ax.set_xlabel("TIME(min)")
        ax.legend(loc='upper left', bbox_to_anchor=(1, 1))
        ax.yaxis.set_major_locator(MaxNLocator(50))
        ax.autoscale_view()
        ax.grid(True, alpha=0.5)
        pos = ax.get_position()
fig.text(0.01, 0.00, warrning_info, ha='left',
         va='bottom', fontsize=10, color='red')
fig.tight_layout()
print("write pic to file: ", args.log + ".png ...")
fig.savefig(args.log + ".png", dpi=200, transparent=False)
