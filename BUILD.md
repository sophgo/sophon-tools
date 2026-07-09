# 编译与部署

两个子项目各产 `.deb`,设备上 `dpkg -i` 安装/升级。

| 项目 | 路径 | deb 包名 | 安装位置 |
|------|------|----------|----------|
| bmssm | `source/pbmssm` | `bmssm_<VER>_<ARCH>.deb` | `/opt/sophon/bmssm/` + systemd unit |
| sophliteos | `source/psophliteos` | `sophliteos_<soc\|pcie>_<VER>.deb` | `/opt/sophon/sophliteos/{bin,dist,config}/` + systemd unit |

端口:bmssm `:9779`(后端),sophliteos `:8080`(前端,反代 `/api/v1/*`→bmssm)。

构建机:amd64,需 `go`、`node/pnpm`(sophliteos)、`dpkg-deb`。arm64 用 musl 交叉工具链(脚本自动拉取或用系统 `aarch64-linux-musl-gcc`)。

---

## 1. bmssm

### 构建

```bash
cd source/pbmssm
bash build/build-deb-bmssm.sh 2.0.0 arm64   # 设备(arm64 musl 静态)
bash build/build-deb-bmssm.sh 2.0.0 amd64   # 开发机/PCIE
```
产物 `source/pbmssm/release/bmssm_2.0.0_arm64.deb`。

只编二进制(不打 deb):`bash build/build-bmssm-arm64.sh 2.0.0` → `release/bmssm` + `release/bmssm.yaml`(校验 `statically linked`)。

流程:version.sh 写版本 → arm64 musl 静态交叉编译(`CGO_ENABLED=1 CC=aarch64-linux-musl-gcc`,`-tags 'netgo osusergo sqlite_omit_load_extension'`,`-ldflags '... -linkmode external -extldflags "-static"'`)→ 组装 deb 数据树 → `dpkg-deb --root-owner-group -b`。

数据树:`/opt/sophon/bmssm/bin/bmssm`、`/opt/sophon/bmssm/config/bmssm.yaml`(**conffile**)、`/usr/lib/systemd/system/bmssm.service`(User=root,Restart=always,`BMSSM_CONF=/opt/sophon/bmssm/config`)。
`postinst`:建 `/var/lib/bmssm /var/log/bmssm` + `daemon-reload && enable && restart`。

### 安装/升级

```bash
sudo dpkg -i bmssm_2.0.0_arm64.deb                      # 首装
sudo dpkg -i --force-confold bmssm_2.0.0_arm64.deb      # 升级(保留 bmssm.yaml 改动)
```
仅替换二进制(不动配置):`systemctl stop bmssm && cp bmssm /opt/sophon/bmssm/bin/bmssm && systemctl start bmssm`。

配置:`/opt/sophon/bmssm/config/bmssm.yaml`(`BMSSM_CONF` env 可改目录),viper WatchConfig 热加载(采样间隔/存档上限等改完需重启)。

---

## 2. sophliteos

### 构建(docker-free)

```bash
cd source/psophliteos
bash build/build-deb-sophliteos.sh 2.0.0 soc    # arm64 设备
bash build/build-deb-sophliteos.sh 2.0.0 pcie   # amd64 开发机
```
产物 `source/psophliteos/release/sophliteos_soc_2.0.0.deb`。

流程:version.sh → 前端 `pnpm install`(无 node_modules 时)+ `pnpm run build` → `cp -r frontend/dist dist` → Go 交叉编译(arm64 musl 静态 / amd64 动态,静态校验)→ 在 `build/stage` 组装 deb(dpkg 直接追踪所有文件,无 tgz/install.sh)→ `dpkg-deb --root-owner-group -b`。

数据树:`/opt/sophon/sophliteos/bin/sophliteos`、`/opt/sophon/sophliteos/config/sophliteos.yaml`(**conffile**)、`/opt/sophon/sophliteos/dist/`(前端)、`/usr/lib/systemd/system/sophliteos.service`。
`postinst`:建 `/var/lib/sophliteos/db /var/log/sophliteos` + `daemon-reload && enable && restart`。DB 由 app 首启自动建,不打进包。

### 安装/升级

```bash
sudo dpkg -i sophliteos_soc_2.0.0.deb                    # 首装
sudo dpkg -i --force-confold sophliteos_soc_2.0.0.deb    # 升级(保留 sophliteos.yaml)
```
只换前端 dist(无需重启,静态从盘读):`rsync -a dist/ /opt/sophon/sophliteos/dist/`(浏览器强刷)。只换 Go 二进制:`systemctl stop sophliteos && cp sophliteos /opt/sophon/sophliteos/bin/sophliteos && systemctl start sophliteos`。

配置:`/opt/sophon/sophliteos/config/sophliteos.yaml`(`bmssm.server` 默认 `127.0.0.1:9779`、`server.www` 默认 `/opt/sophon/sophliteos/dist`、`server.timeout`)。

---

## 3. 部署注意

- 同机部署:bmssm 与 sophliteos 都在设备上。浏览器访问 `http://<设备IP>:8080`。nginx `:80` 在测试机为 stock 配置,不转发 `/api`,不走它。
- **OTA 刷机(`ota.sh sdcard.tgz`)重写 eMMC,清掉 `/opt` 与 overlay 上的 bmssm/sophliteos**,回出厂态。每次 OTA 后需重装两个 deb。
- 刷机后 bmssm DB 重置,默认 `admin/<defaultPassword>`(temp token,强制改密)。

---

## 4. deb 规范

两 deb 均符合 Debian Policy:`Maintainer: Sophgo <support@sophgo.com>`、`Version/Architecture/Package/Description` 齐全、`md5sums` 完整(支持 `dpkg --verify`)、maintainer 脚本有 shebang+`exit 0`(0755)、数据树属主 `root:root`(`--root-owner-group`)。配置文件由 `conffiles` 标注,升级 dpkg 提示保留(或 `--force-confold`)。
