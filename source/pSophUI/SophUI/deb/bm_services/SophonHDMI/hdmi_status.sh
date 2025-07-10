#!/bin/bash

count=0
service_state="init"

USB_HDMI_CHIP=""
if [[ "$(lsusb | grep -i "1D5C:2000" | wc -l)" != 0 ]]; then
    USB_HDMI_CHIP="FL2000"
elif [[ "$(lsusb | grep -i "345F:9132" | wc -l)" != 0 ]]; then
    USB_HDMI_CHIP="MS9132"
elif [[ "$(lsusb | grep -i "345F:9133" | wc -l)" != 0 ]]; then
    USB_HDMI_CHIP="MS9133"
fi

if [ "${USB_HDMI_CHIP}" == "MS9132" ] || [ "${USB_HDMI_CHIP}" == "MS9133" ]; then
    sleep 10
	echo "hdmi chip is ${USB_HDMI_CHIP}, start server and exit."
	systemctl start SophonHDMI.service
	exit 0
fi

fl2000=$(lsmod | grep fl2000 | awk '{print $1}')

echo $fl2000
if [ "$fl2000" != "fl2000" ]; then
	echo "insmod fl2000"
	if [ -e /opt/data/fl2000.ko ]; then
		sudo insmod /opt/data/fl2000.ko
	else
		sudo modprobe fl2000
	fi
	sleep 3
else
	echo "fl2000 already insmod"
fi

sleep 3
status=$(find /sys -name "hdmi_status" 2>/dev/null)
path1="$status/status"
while true; do
	if [ "$status" = "" ]; then
		status=$(find /sys -name "hdmi_status" 2>/dev/null)
		path1="$status/status"
	fi
	STATUS=$(cat $path1 2>/dev/null)
	if [ $? -eq 1 ]; then
		STATUS="0"
	fi
		#echo $STATUS
		if [ $STATUS = "0" ]; then
			#delay stop service for avoid quickly hot-plug
			count=$(($count + 1))
			if [ $count -gt 60 ] && [ $service_state != "inactive" ]; then
				echo "stop hdmi service"
				systemctl stop SophonHDMI.service
				service_state="inactive"
				count=0
			fi
		else
			count=0
			if [ $service_state != "active" ]; then
				echo "start hdmi service"
				systemctl restart SophonHDMI.service
				service_state="active"
			fi
		fi
	sleep 1
done
