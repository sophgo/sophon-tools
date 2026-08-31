# 批量部署工具
### 1. Linux
##### 1.1 环境配置
需要安装的依赖如下：
qt5-default qttools5-dev git g++ libgl1-mesa-dev patchelf fuse  

##### 1.2 运行编译
在目录下可以看到linux_docker.sh和linux_release.sh两个脚本文件；  
可以直接运行脚本文件进行编译，目前推荐使用linux_docker.sh文件进行编译；  
在编译执行完成后会生成output文件夹，在文件夹下有qt_batch_deployment_Vxxx.AppImage文件；  

##### 1.3 程序运行
程序运行指令如下：
./qt_batch_deployment_Vxxx.AppImage [Root Directory] [Json File Path] [Max Value]  
Root Directory，Json File Path， Max Value为可选参数；

##### 1.3.1 图形化模式
当不输入Root Directory，Json File Path， Max Value参数时启动图形化模式；

##### 1.3.2 命令行模式
当输入这部分参数时使用命令行模式；  
Root Directory：命令行模式运行根目录，其他相对路径会以该路径为主目录，需要为绝对路径；  
Json File Path：配置文件所在的路径，需要为绝对路径；  
Max Value：最大并行数量，默认为100； 

### 2. Windows
##### 2.1 环境配置
windows中配置qt基础环境，将qt自带的cmake和mingw64的路径添加到系统变量中；  
将C:/Qt/5.15.2/mingw81_64类似的目录添加到QT_PLATFORM_DIR的环境变量中；  
将C:/Qt/Tools/mingw810_64/bin类似的目录添加到QT_GCC_PLATFORM_DIR的环境变量中；  

##### 2.2 运行编译
在目录下可以看到windows_release.ps1脚本文件；  
运行windows_release.ps1脚本文件进行编译；
编译完成后会得到qt_batch_deployment_Vxxx.exe和qt_batch_deployment_Vxxx.7z两个文件；
qt_batch_deployment_Vxxx.exe为图形化模式应用程序；
将qt_batch_deployment_Vxxx.7z进行解压，其中qt_batch_deployment_no_ui.exe为命令行模式应用程序；

##### 2.3 程序运行
##### 1.3.1 图形化模式
双击qt_batch_deployment_Vxxx.exe启动图形化模式；

##### 1.3.2 命令行模式
命令行模式使用cmd或powershell运行qt_batch_deployment_no_ui.exe文件；
运行指令如下：
./qt_batch_deployment_no_ui.exe [Root Directory] [Json File Path] [Max Value]
Root Directory，Json File Path， Max Value为可选参数；  
Root Directory：命令行模式运行根目录，其他相对路径会以该路径为主目录，需要为绝对路径；  
Json File Path：配置文件所在的路径，需要为绝对路径；  
Max Value：最大并行数量，默认为100； 
