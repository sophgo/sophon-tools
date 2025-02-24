# 编译步骤

1. 找到qt交叉编译工具链使用 qmake . && make 编译出 SophUI 可执行文件
2. 将 SophUI 可执行文件拷贝到 deb/bm_services/SophonHDMI/ 下
3. 执行 dpkg-deb -b deb sophgo-hdmi_x.x.x_arm64.deb 打包deb安装包
