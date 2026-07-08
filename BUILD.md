# 编译与打包流程

两个子项目各自产出 `.deb` 包，便于在设备上 `dpkg -i` 升级与版本管理。

| 项目 | 路径 | deb 包名 | 默认安装位置 |
|------|------|----------|--------------|
| bmssm | `source/pbmssm` | `bmssm_<VER>_<ARCH>.deb` | `/opt/sophon/bmssm/` + `/etc/systemd/system/bmssm.service` |
| sophliteos | `source/psophliteos` | `sophliteos_<soc\|pcie>_<VER>.deb` | `/opt/sophon/sophliteos/bin/sophliteos` + `/opt/sophon/sophliteos/dist` + `/opt/sophon/sophliteos/config/` |

两者都监听本机端口：bmssm `:9779`（REST/WebSocket 后端），sophliteos `:8080`（Web 前端，反代 `/api/v1/*` → bmssm）。

---

## 1. bmssm

### 构建 deb

```bash
cd source/pbmssm
# arm64（设备，musl 静态链接）
bash build/build-deb-bmssm.sh 2.0.0 arm64
# amd64（开发机/PCIE）
bash build/build-deb-bmssm.sh 2.0.0 amd64
```

产物：`source/pbmssm/release/bmssm_2.0.0_arm64.deb`

流程（`build/build-deb-bmssm.sh`）：
1. `build/version.sh <VER>` 写 `build/version.txt`（`version|commit|buildtime`）
2. `build-bmssm-arm64.sh` 交叉编译 musl 静态二进制（arm64）/ `build-bmssm.sh` 宿主编译（amd64），ldflags 注入 version/commit/buildtime
3. 组装 deb 数据树（绝对路径布局）：
   - `/opt/sophon/bmssm/bin/bmssm`
   - `/opt/sophon/bmssm/config/bmssm.yaml`（**conffile**，升级保留用户改动）
   - `/etc/systemd/system/bmssm.service`
4. `DEBIAN/`：`control`（Version/Architecture 注入）、`postinst`（建 `/var/lib/bmssm /var/log/bmssm`、enable+restart）、`prerm`（停服务）、`postrm`、`conffiles`、`md5sums`
5. `dpkg-deb --root-owner-group -b` 打包

### 版本号

- 由脚本第一个参数指定，默认 `2.0.0`
- 同时写入二进制（ldflags `bmssm/global.version`）与 deb `control Version`，二者一致
- `--version` 走 `build/version.txt`，运行时 `bmssm` 日志会打印 version/commit/buildtime

### 安装 / 升级（设备上）

```bash
# 首次安装
sudo dpkg -i bmssm_2.0.0_arm64.deb

# 升级（保留用户改过的 bmssm.yaml）
sudo dpkg -i --force-confold bmssm_2.0.0_arm64.deb
# 升级且用包内新配置覆盖
sudo dpkg -i --force-confnew bmssm_2.0.0_arm64.deb
```

`postinst` 自动 `systemctl daemon-reload && enable && restart`。

---

## 2. sophliteos

### 构建 deb（docker-free）

```bash
cd source/psophliteos
# arm64 设备（soc）
bash build/build-deb-sophliteos.sh 2.0.0 soc
# amd64 开发机（pcie）
bash build/build-deb-sophliteos.sh 2.0.0 pcie
```

产物：`source/psophliteos/release/sophliteos_soc_2.0.0.deb`

流程（`build/build-deb-sophliteos.sh`）：
1. `build/version.sh V<VER>` 写 `release_version.txt`
2. `frontend/` 下 `pnpm install`（无 node_modules 时）+ `pnpm run build` 产出 `frontend/dist`
3. `scrip/package.sh`：go 交叉编译（arm64 musl 静态 / amd64）+ 打 `sophliteos-linux_{arm64,amd64}.tgz`（含二进制/dist/config/db/service/install.sh 等）
4. `build/package-deb.sh <product> <ver>`：在 staging 临时目录组装 deb：
   - 数据树 `data/sophliteos/*`（tgz 解压产物）
   - `DEBIAN/control`（Version/Architecture 注入）、`postinst`（跑 `/data/sophliteos/install.sh`）、`preinst`/`prerm`/`postrm`、`md5sums`
   - **control.bak/changelog 是源码模板，不进 deb 控制归档**（staging 只拷运行时脚本）
5. `dpkg-deb --root-owner-group -b` 打包

`install.sh` 关键行为（升级安全）：
- 配置 `/opt/sophon/sophliteos/config/sophliteos.yaml` 仅在不存在时拷入模板（**升级保留用户改动**）
- DB `/var/lib/sophliteos/db/sophliteos.db` 仅在不存在时拷入模板（**升级保留用户/告警数据**）
- dist/binary/service 每次刷新，`systemctl restart`

### 版本号

- 由脚本第一个参数指定，默认 `2.0.0`
- 写入 deb `control Version`；`release_version.txt`（buildname/buildtime/commit）打到包内 `/var/lib/sophliteos/release_version.txt`

### 安装 / 升级（设备上）

```bash
sudo dpkg -i sophliteos_soc_2.0.0.deb
# 升级（install.sh 自动保留 config/db）
sudo dpkg -i sophliteos_soc_2.0.0.deb
```

---

## 3. 设备部署注意（172.26.166.185）

该 SE7 设备分区：`/` overlay、`/opt` mmcblk0p6、`/data` mmcblk0p7（持久）。**OTA 刷机（`ota.sh sdcard.tgz`）会重写 eMMC 分区，把 `/opt`、overlay 上的 bmssm/sophliteos 部署全部清掉**，设备回到出厂状态。每次 OTA 后需重装两个 deb。

刷机后 bmssm DB 重置，默认 `admin/admin`（temp token，强制改密）。惯用 `admin123`。

---

## 4. deb 规范符合性

两个 deb 均符合 Debian Policy 关键要求：
- `Maintainer: Sophgo <support@sophgo.com>`（含 email，policy 5.6.2）
- `Version` / `Architecture` / `Package` / `Description` 齐全
- bmssm `conffiles` 标注 `/opt/sophon/bmssm/config/bmssm.yaml`，升级由 dpkg 提示保留
- sophliteos 配置/DB 由 `install.sh` 条件拷贝，升级保留
- `md5sums` 完整，支持 `dpkg --verify`
- maintainer 脚本有 shebang + `exit 0`，权限 0755
- 数据树属主 `root:root`（`--root-owner-group`）
