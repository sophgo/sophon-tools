TEMPLATE = app
TARGET = multi_video_qt

# 源文件
SOURCES += \
    ChannelDecoder.cpp \
    DecoderConsole.cpp \
    ff_avframe_convert.cpp \
    ff_video_decode.cpp \
    main.cpp \
    BMLabel.cpp \
    mainwindow.cpp \
    profiler.cpp

HEADERS += \
    ChannelDecoder.h \
    DecoderConsole.h \
    ff_avframe_convert.h \
    ff_video_decode.h \
    json.h \
    BMLabel.h \
    mainwindow.h \
    profiler.h

# 需要的 Qt 模块
QT += core gui widgets

# 头文件搜索路径
INCLUDEPATH += . \
    /opt/sophon/libsophon-current/include \
    /opt/sophon/sophon-ffmpeg-latest/include \
    /opt/sophon/sophon-opencv-latest/include \
    /opt/sophon/sophon-opencv-latest/include/opencv4

# 库文件搜索路径
LIBS += \
    -L$$PWD \
    -L/opt/sophon/libsophon-current/lib \
    -L/opt/sophon/sophon-opencv-latest/lib \
    -L/opt/sophon/sophon-ffmpeg-latest/lib \
    -lpthread \
    -lbmlib \
    -lbmrt \
    -lavcodec \
    -lavformat \
    -lavutil \
    -lbmcv \
    -lopencv_core \
    -lopencv_imgproc \
    -lopencv_highgui \
    -lopencv_imgcodecs \
    -lswresample \
    -lbmvideo \
    -lbmvpuapi \
    -lbmjpuapi \
    -lbmion \
    -lbmjpulite \
    -lvpp_cmodel \
    -lswscale \
    -lbmvpulite \
    -lyuv

# 交叉编译支持
# QMAKE_CXX = aarch64-linux-gnu-g++
# QMAKE_CC = aarch64-linux-gnu-gcc
# QMAKE_LINK = aarch64-linux-gnu-g++

# 优化与警告
QMAKE_CXXFLAGS += -std=c++17 -Wall -O0 -g
QMAKE_CFLAGS += -std=gnu99 -Wall -O0 -g

# 运行库路径
QMAKE_LFLAGS += -Wl,-rpath=./

# 安装目标
target.path = /usr/sbin
INSTALLS += target

# QMAKE_POST_LINK += strip -v --strip-debug --strip-unneeded $$TARGET
