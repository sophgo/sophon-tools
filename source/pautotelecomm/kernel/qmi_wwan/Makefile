ifeq ($(KERNELRELEASE), )
# 设备端编译默认用当前运行内核头；交叉编译时外部传入
#   KERNELDIR=<内核源码/头目录> ARCH=<arch> CROSS_COMPILE=<交叉工具链前缀>
KERNELDIR ?= /lib/modules/$(shell uname -r)/build
# 本子项目仅面向 arm64 设备；空 ARCH 会让 kbuild 的 `ARCH ?= $(SUBARCH)` 失效
# 导致 SRCARCH 为空，因此这里默认补 arm64（外部显式传入时以外部值为准）
ARCH ?= arm64
KERNEL_VERSION := $(shell uname -r)
MODULE_PATH := drivers/net/usb/
KO_FILES := qmi_wwan.ko qmi_wwan_q.ko 
PWD :=$(shell pwd)
default:
		$(MAKE) -C $(KERNELDIR)  M=$(PWD) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE)
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


