#
# Copyright (c) 2015 - 2020 DisplayLink (UK) Ltd.
#

TARGET = dfss-cpp

CC = $(CROSS_COMPILE)gcc
CXX = $(CROSS_COMPILE)g++
STRIP = $(CROSS_COMPILE)strip

GCCVERSION := $(shell $(CXX) -dumpversion | cut -f1 -d.)
ifneq ($(filter 5 6 7 8, $(GCCVERSION)),)
    EXT_LIB_FLAG_STATIC += -lstdc++fs
endif

# ---- 编译期版本信息 --------------------------------------------------------
# 优先级（高 → 低）：
#   1. 环境变量 GIT_COMMIT_HASH / GIT_COMMIT_DATE —— 构建脚本在宿主机算好传入。
#      容器内通常没有 .git（build-dfss-pip.sh 只挂 source/pdfss_cpp 子目录），
#      这是容器构建唯一可靠的信息来源。
#   2. 仓库内 git —— 开发者在仓库工作树内直接 make。
#   3. git_version 文件 —— dfss 的权威版本源（见 RELEASE.md §2）。
# 三者都拿不到时直接构建失败：历史实现把 $(shell git ...) 的失败静默当空串，
# 编出的二进制打印 "version: (-)[]"（MYS-2414）。
GIT_VERSION_FILE := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../git_version)
PKG_VERSION := $(shell cat "$(GIT_VERSION_FILE)" 2>/dev/null | tr -d '[:space:]')

GIT_DESC := $(shell git describe --tags 2>/dev/null)
GIT_SHA := $(shell git rev-parse HEAD 2>/dev/null)
GIT_DATE := $(shell git show -s --format=%ci HEAD 2>/dev/null)

ifeq ($(strip $(GIT_DESC)$(GIT_SHA)),)
    # git 不可用：退回 git_version 并标记 -nogit，避免伪装成正常构建
    GIT_VERSION_FALLBACK := $(if $(PKG_VERSION),$(PKG_VERSION)-nogit,)
else
    GIT_VERSION_FALLBACK := $(GIT_DESC)-$(GIT_SHA)
endif

# 构建脚本从宿主机传入的值优先；注意 env 里"存在但为空"也要当作未设置，
# 否则 ?= 不会回退（make 认为空的环境变量仍是已定义）。
ifneq ($(strip $(GIT_COMMIT_HASH)),)
    GIT_COMMIT_HASH := $(strip $(GIT_COMMIT_HASH))
else
    GIT_COMMIT_HASH := $(GIT_VERSION_FALLBACK)
endif

ifneq ($(strip $(GIT_COMMIT_DATE)),)
    GIT_COMMIT_DATE := $(strip $(GIT_COMMIT_DATE))
else
    GIT_COMMIT_DATE := $(if $(strip $(GIT_DATE)),$(GIT_DATE),Unknown)
endif

ifeq ($(strip $(GIT_COMMIT_HASH)),)
    $(error 无法确定版本信息：git 不可用且 $(GIT_VERSION_FILE) 缺失。请在构建脚本中通过环境变量传入 GIT_COMMIT_HASH / GIT_COMMIT_DATE)
endif

INCLUDE = -I. -I$(BUILD_PATH)/libs/$(LIBS_TYPE)/include
LIBS = -L. -L$(BUILD_PATH)/libs/$(LIBS_TYPE)/lib -L$(BUILD_PATH)/libs/$(LIBS_TYPE)/lib64 $(EXT_LIB_FLAG_STATIC) $(EXT_LIB_FLAG_DYNAMIC)

ifeq ($(NEED_DEBUG),1)
    BUILD_TYPE_FLAG := -g -O0
	STRIP_CMD := @echo "Skip stripping in debug mode"
else
    BUILD_TYPE_FLAG := -O3
	ifeq ($(shell uname -s),Darwin)
	    STRIP_CMD := $(STRIP) -x
	else
	    STRIP_CMD := $(STRIP) -v --strip-debug --strip-unneeded
	endif
endif

CFLAGS = $(EXT_FLAG) -I. $(INCLUDE) $(LIBS) -std=gnu99 -Wall ${BUILD_TYPE_FLAG}
CXXFLAGS = $(EXT_FLAG) -DGIT_COMMIT_HASH="\"$(GIT_COMMIT_HASH)\"" -DGIT_COMMIT_DATE="\"$(GIT_COMMIT_DATE)\"" -I. $(INCLUDE) $(LIBS) -Wall ${BUILD_TYPE_FLAG} -std=c++17

SRCS = $(wildcard *.c)
SRCPPS = $(wildcard *.cpp)
OBJS = $(patsubst %.c, %.o, $(SRCS))
OBJS += $(patsubst %.cpp, %.o, $(SRCPPS))
PREFIX = /usr/sbin

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) $(OBJS) -o $@ $(INCLUDE) $(LIBS)
	$(STRIP_CMD) $@*

.PHONY: clean install
clean:
	rm -rf $(TARGET)*
	rm -rf $(OBJS)
