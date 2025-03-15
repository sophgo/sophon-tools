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

GIT_COMMIT_HASH = $(shell git describe --tags)-$(shell git rev-parse HEAD)
GIT_COMMIT_DATE = $(shell git show -s --format=%ci HEAD)

INCLUDE = -I. -I$(BUILD_PATH)/libs/$(LIBS_TYPE)/include
LIBS = -L. -L$(BUILD_PATH)/libs/$(LIBS_TYPE)/lib -L$(BUILD_PATH)/libs/$(LIBS_TYPE)/lib64 $(EXT_LIB_FLAG_STATIC) $(EXT_LIB_FLAG_DYNAMIC)

CFLAGS = $(EXT_FLAG) -I. $(INCLUDE) $(LIBS) -std=gnu99 -Wall -O3
CXXFLAGS = $(EXT_FLAG) -DGIT_COMMIT_HASH="\"$(GIT_COMMIT_HASH)\"" -DGIT_COMMIT_DATE="\"$(GIT_COMMIT_DATE)\"" -I. $(INCLUDE) $(LIBS) -Wall -O3 -std=c++17

SRCS = $(wildcard *.c)
SRCPPS = $(wildcard *.cpp)
OBJS = $(patsubst %.c, %.o, $(SRCS))
OBJS += $(patsubst %.cpp, %.o, $(SRCPPS))
PREFIX = /usr/sbin

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) $(OBJS) -o $@ $(INCLUDE) $(LIBS)
	$(STRIP) -v --strip-debug --strip-unneeded $@*

.PHONY: clean install
clean:
	rm -rf $(TARGET)*
	rm -rf $(OBJS)
