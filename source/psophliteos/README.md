# sophliteos

算力设备管理系统（SophLiteOS）—— Sophgo 算力设备的 Web 管理平台，提供设备资源监控、告警、日志、网络/IP、密码、OTA/SSM 升级、版本等设备运维功能。

> 本子工程自 `sophgo-liteos` 迁入并裁剪掉 algoliteos 算法业务集成。

## 目录结构
- `api`: 后端业务控制器（device-mgmt handlers）
- `router`: 路由定义
- `client/bmssm`: 设备端 SSM(System Service Manager, 127.0.0.1:9779) 接口客户端
- `client/httpclient`: 通用 HTTP 封装
- `mvc`: 参数封装/验证/返回/i18n/异常
- `middleware`: 鉴权/熔断/超时中间件
- `database`: sqlite（User/Alarm/OptLog）
- `config`/`logger`/`global`/`initialization`: 配置/日志/全局/初始化
- `frontend`: Vue 前端（基于 vue-vben-admin），源码已在本目录下
- `build`/`scrip`/`release`: 构建脚本/部署脚本/产物落点

## 编译依赖
- go >= 1.19
- `gcc-aarch64-linux-gnu`（arm64 交叉编译）：`sudo apt-get install gcc-aarch64-linux-gnu`
- docker（前端在 node:16 容器中构建）

## 构建
前端源码已在本目录 `frontend/` 下，**无需 clone**。进入 build 目录执行：
```bash
cd build
./build_2_release.sh
```
（若 docker 需 root：`sudo ./build_2_release.sh`，且 root 的 PATH 需含 go）

## 产物
```
release/
├── sophliteos-linux_amd64.tgz
├── sophliteos-linux_arm64.tgz
├── sophliteos_pcie_1.1.2.deb
├── sophliteos_soc_1.1.2.deb
├── sophliteos_pcie_1.1.2_sdk.deb
└── sophliteos_soc_1.1.2_sdk.deb
```

## 安装运行
- x86: `tar -xvf sophliteos-linux_amd64.tgz && sudo ./install.sh` 或 `sudo dpkg -i sophliteos_pcie_1.1.2.deb`
- arm: `tar -xvf sophliteos-linux_arm64.tgz && sudo ./install.sh` 或 `sudo dpkg -i sophliteos_soc_1.1.2.deb`

---

## 登录页 LOGO 替换

登录页的 LOGO（`class="sophgo_logo"`）保留可替换，其余页面的 sophgo logo（顶部用户下拉 `__header`、菜单 `menu_logo`、应用 `logo.png`、登录表单 `logo.png`）已移除。

替换登录 LOGO 的两种方式：

### 方式一：替换部署后的图片文件（无需重新构建）

sophliteos 静态资源从 `/opt/sophon/sophliteos/dist/resource/` 提供，登录 LOGO 默认读取 `resource/img/login_logo.png`。

```bash
# 替换为目标 LOGO（建议 PNG，contain 缩放）
sudo cp /path/to/your_logo.png /opt/sophon/sophliteos/dist/resource/img/login_logo.png
```

浏览器强刷（Ctrl+Shift+R）即可生效。

> 注意：sophliteos deb 升级会刷新 `/opt/sophon/sophliteos/dist`，升级后需重新覆盖此文件。

### 方式二：构建期注入自定义路径（持久，随升级保留）

在 `source/psophliteos/frontend/.env`（或对应模式的 `.env.production`）设置：

```bash
# 任意可访问的 URL/路径，置空则不显示 LOGO
VITE_GLOB_LOGIN_LOGO = /resource/img/your_login_logo.png
```

把你的 LOGO 放进 `source/psophliteos/frontend/public/resource/img/your_login_logo.png`，重新构建 deb：

```bash
cd source/psophliteos
bash build/build-deb-sophliteos.sh 2.0.7 soc
sudo dpkg -i release/sophliteos_soc_2.0.7.deb
```

该路径随 dist 打包，升级后保留。

### 接口说明

- `Login.vue` 通过 `import.meta.env.VITE_GLOB_LOGIN_LOGO` 读取 LOGO 路径（默认 `/resource/img/login_logo.png`），内联注入 `.sophgo_logo` 的 `background-image`。
- `VITE_GLOB_APP_HIDE_MENU_LOGO=true` 可隐藏整个登录 LOGO。
