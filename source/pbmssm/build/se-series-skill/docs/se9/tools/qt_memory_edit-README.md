# 远程内存修改工具

使用库：libssh2、zlib1.2.13、openssl

其中libssh2和zlib库在libs目录下
openssl在windows中使用opensslv3，在linux中使用opensslv1.1.1(ubuntu18)

默认不支持debug模式，windows中默认使用静态库编译，linux中默认使用动态库编译

编译后需要使用windeployqt工具拷贝需要的Qt库文件
在windows中使用Enigma Virtual Box工具进行打包

## 编译准备

需要将最新版本的memory_edit.tar.xz文件cp到当前目录

## linux中编译方式

### 实机编译

安装qt5-default qttools5-dev git g++ libgl1-mesa-dev patchelf fuse
运行linux_release.sh脚本，运行结束后源码目录会出现*.AppImage文件，大小应该在25MB以上

### docker编译

直接运行linux_docker.sh脚本，运行结束后源码目录会出现*.AppImage文件，大小应该在25MB以上

## windows中编译方式

windows中配置qt基础环境，将qt自带的cmake和mingw64的路径添加到系统变量中
将C:/Qt/5.15.2/mingw81_64类似的目录添加到QT_PLATFORM_DIR的环境变量中
将C:/Qt/Tools/mingw810_64/bin类似的目录添加到QT_GCC_PLATFORM_DIR的环境变量中
直接执行源码目录下的windows_release.ps1文件
然后再build/output/下就会出现 远程内存修改工具_Vx.x.x.exe文件，该文件应该在25MB以上

## linux中底层库编译安装包和手动打包命令记录

这里的几条命令需要按需修改（这个是编译底层库的指示文件）
``` bash
sudo apt install qt5-default qttools5-dev git g++ libgl1-mesa-dev patchelf fuse
sudo apt download libssl1.1 libssl-dev
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/data/zzt/qt_mem_edit/temp/zlib_linux_arm64/
cmake -DBUILD_STATIC_LIBS=OFF -DBUILD_SHARED_LIBS=ON -DENABLE_ZLIB_COMPRESSION=ON -DENABLE_DEBUG_LOGGING=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/data/zzt/qt_mem_edit/temp/libss2_linux_arm64/ -DZLIB_LIBRARY=/data/zzt/qt_mem_edit/temp/zlib_linux_arm64/lib/libz.so -DZLIB_INCLUDE_DIR=/data/zzt/qt_mem_edit/temp/zlib_linux_arm64/include -DOPENSSL_ROOT_DIR=/data/zzt/qt_mem_edit/qt_mem_edit/libs/linux_arm64/openssl/ -DOPENSSL_INCLUDE_DIR="/data/zzt/qt_mem_edit/qt_mem_edit/libs/linux_arm64/openssl/include;/data/zzt/qt_mem_edit/qt_mem_edit/libs/linux_arm64/openssl/include/aarch64-linux-gnu/" -DOPENSSL_CRYPTO_LIBRARY="/data/zzt/qt_mem_edit/qt_mem_edit/libs/linux_arm64/openssl/lib/libcrypto.so.1.1;/data/zzt/qt_mem_edit/qt_mem_edit/libs/linux_arm64/openssl/lib/libssl.so.1.1" ..
```

从[https://github.com/AppImage/AppImageKit/releases](https://github.com/AppImage/AppImageKit/releases)中安装appimage工具包
参考[https://github.com/probonopd/linuxdeployqt/blob/master/BUILDING.md](https://github.com/probonopd/linuxdeployqt/blob/master/BUILDING.md)安装linuxdeployqt并进行依赖库打包

打包appimage基础目录在libs中有，需要注意库文件的软链接可能会失效
拷贝Appdir到临时目录
将编译得到的qti\_mem\_edit拷贝到Appdir/usr/bin下
将需要使用的动态库拷贝到Appdir/usr/lib下
/usr/lib/qt5/bin/linuxdeployqt Appdir/qt\_mem\_edit.desktop -appimage -verbose=2
appimagetool --comp xz Appdir

linux环境运行打包后的程序至少需要如下三个包(如果已经有桌面了，就不需要这些包)：libharfbuzz0b x11-apps libgl1

## windows中底层库编译安装包和手动打包命令记录

使用qt自带的mingw工具链、cmake和opensslv3

``` bash
cmake "-DCMAKE_INSTALL_PREFIX=./install_release" "-DCMAKE_BUILD_TYPE=Release" -G "MinGW Makefiles" ..
cmake "-DCMAKE_INSTALL_PREFIX=./install_debug" "-DCMAKE_BUILD_TYPE=Debug" -G "MinGW Makefiles" ..
```
