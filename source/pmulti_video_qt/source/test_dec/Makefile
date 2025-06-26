CROSS_COMPILE ?= aarch64-linux-gnu-
LIBUSB_TARGET ?= aarch64
TARGET = test_dec

INCLUDE = -I. -I../ -I/opt/sophon/libsophon-current/include/ -I/opt/sophon/sophon-ffmpeg-latest/include/ -I/opt/sophon/sophon-opencv-latest/include/ -I/opt/sophon/sophon-opencv-latest/include/opencv4/
LIBS = -L. -L../ -L/opt/sophon/libsophon-current/lib/ -L/opt/sophon/sophon-opencv-latest/lib/ -L/opt/sophon/sophon-ffmpeg-latest/lib -Wl,-Bdynamic -lpthread -lpthread -lbmlib -lbmrt -lavcodec -lavformat -lavutil -lbmcv -lopencv_core -lopencv_imgproc -lopencv_highgui -lopencv_imgcodecs -lswresample -lbmvideo -lbmvpuapi -lbmjpuapi -lbmion -lbmjpulite -lvpp_cmodel -lswscale -lbmvpulite -lyuv -Wl,-rpath=./

DBG_FLAG = -O0 -g
SRCS = $(wildcard ../*.c *.c)
OBJS = $(patsubst %.c, %.o, $(SRCS))
SRCSPP = $(filter-out ../main.cpp ../mainwindow.cpp ../BMLabel.cpp, $(wildcard ../*.cpp *.cpp))
OBJSPP = $(patsubst %.cpp, %.o, $(SRCSPP))
CFLAGS = -std=gnu99 -Wall $(DBG_FLAG) -Wl,-rpath=./ $(INCLUDE) $(LIBS) 
CXXFLAGS = -std=c++17 -Wall $(DBG_FLAG) -Wl,-rpath=./ $(INCLUDE) $(LIBS) 
CC = $(CROSS_COMPILE)gcc
CXX = $(CROSS_COMPILE)g++
PREFIX = /usr/sbin

all: $(TARGET)

$(TARGET): $(OBJS) $(OBJSPP)
	$(CXX) -std=gnu99 -Wall $(DBG_FLAG) -Wl,-rpath=./ -o $@ $^ $(CXXFLAGS)

-include $(OBJS:.o=.d) $(OBJSPP:.o=.d)

%.o: %.c
	$(CC) $(CFLAGS) -MMD -c $< -o $@

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -MMD -c $< -o $@

clean:
	rm -f $(OBJS) $(OBJSPP) $(TARGET) $(OBJS:.o=.d) $(OBJSPP:.o=.d)

.PHONY: all clean

