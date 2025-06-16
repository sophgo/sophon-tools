ifeq ($(KERNELRELEASE), )
KERNELDIR := /lib/modules/$(shell uname -r)/build
# 在x86主机上进行交叉编译时请使按照下面的注释配置环境变量，同时不要进行下方部分安装相关的操作
# KERNELDIR = /workspace/allinone/linux-linaro-stable
# ARCH = arm64
# CROSS_COMPILE = /workspace/env/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-
KERNEL_VERSION := $(shell uname -r)
MODULE_PATH := drivers/net/usb/
KO_FILES := qmi_wwan.ko qmi_wwan_q.ko 
PWD :=$(shell pwd)
default:
		$(MAKE) -C $(KERNELDIR)  M=$(PWD)
clean:
		rm -rf .tmp_versions Module.symvers *.mod.c *.o *.ko .*.cmd Module.markers modules.order *.a *.mod
install:
		mkdir -p /lib/modules/$(KERNEL_VERSION)/kernel/$(MODULE_PATH)
		@for ko_file in $(KO_FILES); do \
				cp -f $(PWD)/$${ko_file} /lib/modules/$(KERNEL_VERSION)/kernel/$(MODULE_PATH); \
				echo install $${ko_file} to /lib/modules/$(KERNEL_VERSION)/kernel/$(MODULE_PATH); \
	done

		depmod -a
uninstall:
		@for ko_file in $(KO_FILES); do \
				rm -rf /lib/modules/$(KERNEL_VERSION)/kernel/$(MODULE_PATH)/$${ko_file}; \
				echo remove $${ko_file} form /lib/modules/$(KERNEL_VERSION)/kernel/$(MODULE_PATH); \
	done
		depmod -a
else
	CONFIG_USB_NET_QMI_WWAN ?= m
	obj-$(CONFIG_USB_NET_QMI_WWAN)	+= cdc-wdm.o
	obj-$(CONFIG_USB_NET_QMI_WWAN)	+= qmi_wwan.o
	obj-$(CONFIG_USB_NET_QMI_WWAN)	+= qmi_wwan_q.o
endif


