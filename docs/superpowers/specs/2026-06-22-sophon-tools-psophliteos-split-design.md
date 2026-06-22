# sophon-tools 设备管理平台拆分设计（psophliteos）

- 日期：2026-06-22
- 来源工程：`/home/zzt/workspace/sophgo-liteos`（module `sophliteos`，"算力设备管理系统"，Go 后端 + Vite/Vue 前端）
- 目标工程：`/home/zzt/workspace/sophon-tools`（算丰设备易用性工具 monorepo，git 仓库）
- 状态：设计已与用户确认；已通过对抗式审查（4 维度并行核对真实源码），blocker/major 已修复，可进入实现
- 修订：2026-06-22 v1.1 —— 修复 3 个 blocker（删函数后未清理 import 致 go build 失败；构建脚本引用不存在的 `frontend/sophliteos-frontend` 子目录）与 5 个 major（locales 漏删、globEager 归属错误、node 版本、README 与脚本冲突、SDK deb 产物漏列）

## 1. 背景与目标

把 `sophgo-liteos` 裁掉"算法业务（algoliteos 集成）"相关代码后，作为**完整设备管理平台**（Go 后端 + Vue 前端 + deb/tgz 发布链路）纳入 `sophon-tools` 仓库新分支的 `source/psophliteos` 子目录，单次初始提交。

要求（用户原文）："排除当前项目中与云控、sophnet 等相关的代码，只保留设备管理相关的代码。"

## 2. 现状分析

### 2.1 sophgo-liteos 工程概览

Go 后端（module `sophliteos`，go 1.19，gin）+ Vite/Vue 前端（基于 vue-vben-admin 模板）。顶层目录：`api build client config database frontend global initialization logger middleware mvc router scrip release`，入口 `main.go`。

后端路由（`router/system/`）含：Base/Resource/Basic/Password/IpQuery/Alarm/Log/Ota/Version/Upgrade/SsmUpgrade/Down。后端 client：`ssm`（本机 127.0.0.1:9779 System Service Manager）、`ws`（未引用死代码）、`httpclient`（通用封装）。

前端 `views/` 分组：`accessAlgo`（算法接入）、`task`（占位桩）、`overview`、`maintenance`、`logs`、`sys`、`demo`。

### 2.2 边界判定（关键）

**字面 `sophnet` / `云控` / `cloud` 在全仓代码中零命中**（已 grep 验证）。也没有 mqtt/broker/license/长连接/远程上报。后端配置里唯一的远程地址是本机 `127.0.0.1:9779`（SSM 设备端服务）。

**唯一"非设备管理"的部分是"算法业务"集成层**，但它**全部指向本机 `127.0.0.1:8081`（同机的 algoliteos 算法服务），不是远程云平台**：

- 后端：`initialization/router.go` 的 `/algorithm` 反向代理 → localhost:8081；`api/v1/system/sys_base.go` 的 `AlgoRegister`/`AlgoExist`/`Register()` 启动时探活；`global/global.go` 的 `AlgoFlag`；`api/v1/system/sys_upgrade.go` 的 `upgradeAlgo()` 分支。
- 前端：`views/accessAlgo/*`、`api/{task,dataSource,alrmRetrieval,paramConfig}`、路由模块 `router/routes/modules/accessAlgo.ts`、`.env.development` 的 `/algorithm` 代理。

用户已拍板：**算法业务一并排除**（即便它不是真正远程云控，仍按"非设备管理"排除）。

设备管理主体清晰自洽、无云控耦合：`alarm`/`basic`/`ip`/`iptable`/`log`/`ota`/`password`/`resource`/`ssm_upgrade`/`version` + `client/ssm`（本机 9779）+ `database`（User/Alarm/OptLog 三表）+ `mvc` 框架 + `middleware` + `config/logger` + `build/scrip` 部署链路 + 前端 `overview/maintenance/logs/sys`。

> 注：`client/ssm` 中出现的"算力"=硬件算力资源监控（TOPS 展示）、"订阅"=向本机 SSM 订阅告警回调、`SSM 授权`/`SsmAuth`=SSM 鉴权 token，**均属设备管理，保留**，与云控无关。

## 3. 拆分决策（已与用户确认）

| 决策项 | 结论 |
|---|---|
| 排除范围 | 算法业务（algoliteos 集成）一并排除 |
| 子工程范围 | 完整平台（Go 后端 + Vue 前端 + deb/tgz 发布链路） |
| 提交方式 | 方案 A：sophon-tools 新分支，裁剪后单次初始提交 |
| 子目录名 | `source/psophliteos`（与 module 名 `sophliteos`、产物 `sophliteos_*.deb/tgz` 一致） |
| 构建集成 | 保留并**适配**自带 `build/build_2_release.sh`；**不**纳入根 `release.sh` 一键编译；根 README 表标"不支持一键编译" |
| 裁剪粒度 | (A) 整文件/目录删 + (B) 行级/函数级裁剪（含删函数后清理未使用 import）；同步删除 overview 耦合 |
| 死代码与杂项 | 本次只做必需裁剪，其余原样保留；vben 模板 CI/git-hooks/cloud-dev 残留不拷入 |

## 4. 新工程结构（source/psophliteos）

**保留目录/文件**：`api/ build/ client/{ssm,httpclient} config/ database/ frontend/(裁剪后) global/ initialization/ logger/ middleware/ mvc/ router/ scrip/ release/ main.go go.mod go.sum .env .env.development .env.production .env.test .editorconfig .eslintrc.js .eslintignore .prettierignore .stylelintignore .vscode/ README.md（需重写构建步骤，见 §7）`

**拷入时排除**（vben-admin 模板 CI/git-hooks/cloud-dev 残留，与设备 deb 发布无关或会与 monorepo 冲突）：`.github/`、`.gitpod.yml`、`.husky/`（跑 commitlint，会与 sophon-tools 提交规范冲突）。`frontend/node_modules/`、`frontend/dist/`、`frontend/.git/`（若有）。

> `.gitignore` 不原样拷入（其 `frontend/sophliteos-frontend` 等规则在扁平布局下无意义，且会与 monorepo 根 `.gitignore` 叠加）；如需子工程级忽略，迁入后新写一份仅含必要项（如 `frontend/node_modules/`、`frontend/dist/`、`release/` 产物）。
> `.vscode/` 保留（子工程级开发配置，无害）。

**死代码原样保留**（本次不动，预存风险见 §10）：`client/ws/`、`api/v1/system/sys_core_operation.go`（ApiGroup/RouterGroup 均未引用）、`api/v1/system/sys_down.go`（DownRouter 路由注册被注释，见 §11.4）、`sys_ota.go` 的 `OtaRollback`（未路由）、`initialization/router.go` 的 `NewProxy`（第 77-81 行，全仓无引用；**注意**：删除 `/algorithm` 反代块后，`net/http/httputil` 与 `net/url` 两个 import 仍由 NewProxy 维持有效，故 NewProxy 不可误删，否则需同时删这两个 import）。

## 5. 裁剪清单

### 5.1 (A) 整文件/目录删除

| 路径 | 说明 |
|---|---|
| `frontend/src/views/accessAlgo/` | 算法业务视图整目录（直接子目录：`alarmRetrieval`/`dataSource`(内含 videoManage)/`paramConfig`/`task`(内含 taskList/taskSubscribe)） |
| `frontend/src/views/task/` | 顶层算法业务占位桩目录（`taskList/index.vue`、`taskSubscribe/index.vue`，内容为 `<h1>taskList</h1>` 占位，无路由引用，随算法业务清理） |
| `frontend/src/router/routes/modules/accessAlgo.ts` | 算法业务一级菜单路由 |
| `frontend/src/api/task/` | 算法任务 API |
| `frontend/src/api/dataSource/` | 算法视频源 API |
| `frontend/src/api/alrmRetrieval/` | 算法告警检索 API |
| `frontend/src/api/paramConfig/` | 算法参数配置 API |
| `frontend/src/store/modules/alrmRetrieval.ts` | 算法告警图 store |
| `frontend/mock/taskList/` | 算法业务 mock |
| `frontend/mock/dataSource/` | 算法业务 mock |
| `frontend/src/locales/lang/zh-CN/taskList.ts` | 算法 i18n |
| `frontend/src/locales/lang/zh-CN/dataSource.ts` | 算法 i18n |
| `frontend/src/locales/lang/zh-CN/alarmRetrieval.ts` | 算法 i18n |
| `frontend/src/locales/lang/zh-CN/paramConfig.ts` | 算法参数配置 i18n（algoType/algoThreshold/paramConfig） |
| `frontend/src/locales/lang/en/taskList.ts` | 算法 i18n |
| `frontend/src/locales/lang/en/dataSource.ts` | 算法 i18n |
| `frontend/src/locales/lang/en/alarmRetrieval.ts` | 算法 i18n |
| `frontend/src/locales/lang/en/paramConfig.ts` | 算法参数配置 i18n |

> `frontend/mock/{logs,maintenance,overview,sys,...}` 属设备管理 mock，保留。

### 5.2 (B) 行级/函数级裁剪（混合文件，保留设备管理部分）

行号已对照真实源码核验（见 §6 核验记录）。**凡删除函数后导致 import 未使用的，必须同步删该 import，否则 `go build` 报 `imported and not used`。**

| 文件 | 删除内容 | 保留 |
|---|---|---|
| `initialization/router.go` | `/algorithm` 反向代理块（`algoURL`/`proxy`/`algorithmGroup` 及其 `Any("/*path"...)`，约 25-33 行） | system 路由组、Static、middleware.BlockerMiddleware、NewProxy（见 §4） |
| `api/v1/system/sys_base.go` | `AlgoRegister`/`AlgoExist`/`Register()` 三个函数（约 178-203 行）；**并删除第 10 行 `\"sophliteos/client/httpclient\"` import**（该 import 全文件仅被 Register() 第 194 行 `httpclient.NewRequest(...)` 引用，删 Register() 后变未使用） | `Login`/`Logout`/`AlarmListen` |
| `router/system/sys_base.go` | `register`/`algorithm` 两条路由注册（约 20-21 行） | `login`/`logout`/`device`/`alarm` 路由 |
| `global/global.go` | `AlgoFlag bool` 字段（第 17 行） | 其余全局变量（TimeOut/OtaTimeOut/Version/BlockAllRequests/DeviceType/SSmLists/SdkVersion/Resource/LoginError） |
| `initialization/init.go` | `global.AlgoFlag = false`（第 36 行）、`system.Register()`（第 45 行）；**并删除第 4 行 `\"sophliteos/api/v1/system\"` import**（该 import 全文件仅被第 45 行 system.Register() 使用，删后变未使用） | `config.LoadConfig`/`logger`/`database.InitDB`/`ssm.SubscribeAlarm()`（38-43 行）等 |
| `api/v1/system/sys_upgrade.go` | `upgradeAlgo()` 函数 + `algoliteos` 升级包文件名判断分支（第 40-47 行 `if filename == \"algoliteos-linux_arm64.tgz\" || filename == \"algoliteos-linux_amd64.tgz\"`） | `upgradeLiteOs`/`saveFile` |
| `frontend/.env.development` | `VITE_PROXY` 数组中 `["/algorithm","http://172.28.8.21:8081/algorithm"]` 那一条 | `["/api",...]`、`["/upload",...]` |
| `frontend/src/api/overview/index.ts` | `IsAlgorithm()` 函数（41-43 行）、`Api` 枚举中 `isAlgo = '/algorithm'`（第 10 行） | `resourceApi`/`resourceIp`/`setDeviceInfoApi`/`operationApi`/`getSoftwareInfoApi` 及 `Resource/Basic/Operation/Software` 枚举 |
| `frontend/src/store/modules/overview.ts` | import 的 `IsAlgorithm`（第 4 行改为 `import { resourceApi } from '/@/api/overview/index';`）、`const isAlgo = await IsAlgorithm();`（第 69 行）、`if (!isAlgo) { ... asyncRoutes.find(...'accessAlgo')...hideMenu = true ... }`（第 139-143 行，闭合 `}` 在第 143 行） | `getDeviceInfo` 主体、`init`、`updateDevice`、`useUserStoreWithOut` |
| `frontend/src/locales/lang/zh-CN/routes/dashboard.ts` | 算法相关 key：`accessAlgo`/`task`/`taskList`/`taskSubscribe`/`dataSource`/`mediaServers`/`videoManage`/`AlgoParamConfig`/`alarmRetrieval`/`alarmDetail` | 其余 dashboard key |
| `frontend/src/locales/lang/en/routes/dashboard.ts` | 同上英文 key | 其余 |

> dashboard.ts 删除集合以"`accessAlgo.ts` 路由引用的 key + 其余算法业务命名 key"为准（已与源核对，见 §6）。

## 6. 耦合处理（最高风险，强制配套）

设备管理与算法业务的**唯一运行期耦合**在 `frontend/src/store/modules/overview.ts` 的 `getDeviceInfo()`：

```
第 4 行:  import { resourceApi, IsAlgorithm } from '/@/api/overview/index';
第 69 行: const isAlgo = await IsAlgorithm();
第 139-143 行:
  if (!isAlgo) {
    const algo = asyncRoutes.find((item) => item.name === 'accessAlgo');
    algo.meta.hideMenu = true;
    permissionStore.buildRoutesAction();
    permissionStore.setLastBuildMenuTime();
  }
```

删除 `accessAlgo.ts` 路由模块后，`asyncRoutes.find(item => item.name === 'accessAlgo')` 将返回 `undefined`，若不同步删第 139-143 行，访问 `algo.meta.hideMenu` 会抛 **TypeError**。故 (B) 中 overview store 的三处删除（import/调用/`if(!isAlgo)` 块）是**强制配套项**，缺一不可。`IsAlgorithm()` 全仓仅此处引用，删除安全。

路由/菜单模块的自动加载：**`frontend/src/router/routes/index.ts:10` 与 `frontend/src/router/menus/index.ts:13`** 各自用 `import.meta.globEager('./modules/**/*.ts')` 自动加载 `router/routes/modules/` 下所有路由/菜单模块（permission store 全文无 globEager，它仅 `import { asyncRoutes } from '/@/router/routes'`）。因此删除 `accessAlgo.ts` 文件即可，**无需改 permission store 的 buildRoutesAction 逻辑**；但若只删 views 不删 `accessAlgo.ts`，globEager 仍加载该模块并指向不存在的 view 导致报错——故 (A) 中 `accessAlgo.ts` 必须删。

## 7. 构建与发布

### 7.1 构建脚本适配（blocker 修复，必做）

当前 `sophgo-liteos` 工作树的 `frontend/` 为**扁平布局**（`package.json`/`src/` 直接在 `frontend/` 根，无 `sophliteos-frontend` 子目录、无 `frontend/.git`）。但原构建脚本引用了不存在的子目录与 .git，**原样保留会导致发布链路断裂**。迁入时按"适配脚本到扁平布局"方式修改（不改 frontend 目录结构）：

| 文件 | 原内容 | 改为 |
|---|---|---|
| `build/build_2_release.sh:16` | `docker run ... node:16 sh -c 'cd /home/node/sophliteos-frontend && yarn && yarn build'` | `... sh -c 'cd /home/node && yarn && yarn build'` |
| `build/build_2_release.sh:17` | `cp -r ../frontend/sophliteos-frontend/dist ../` | `cp -r ../frontend/dist ../` |
| `build/build_test.sh`（cp 行） | `cp -r ../frontend/sophliteos-frontend/dist ../` | `cp -r ../frontend/dist ../` |
| `build/version.sh:11-16` | 前端独立 git 块：`project_path="../frontend/sophliteos-frontend"` + `git --git-dir=...rev-parse`（取前端分支/commit） | **整块删除**（前端已并入 monorepo，后端块 `:19-25` `project_path=".."` 已记录 monorepo commit，覆盖前端版本） |

> `version.sh:7-8` 的硬编码 commit hash `b74ff743...` 属"版本硬编码"遗留（§10 风险，本次不动）。
> `build_2_release.sh:7-9` 强制 CWD 必须为 build 目录，本次不改。
> docker 镜像为 **node:16**（脚本实际值）；原 `README.md:20` 写 "node17" 是源工程自身的历史笔误，本次以脚本为准、子工程 README 重写时统一为 node:16。

### 7.2 产物与集成

- 保留 `build/build_2_release.sh`：前端在 docker（node:16）容器 `yarn build`，后端 go 交叉编译 amd64/arm64（`scrip/package.sh`，arm64 用 `CC=aarch64-linux-gnu-gcc`），dpkg-deb 打包。
- 产物（`build_2_release.sh:39` mv 到 `release/`，共 6 个）：
  - `release/sophliteos-linux_amd64.tgz`、`release/sophliteos-linux_arm64.tgz`
  - `release/sophliteos_pcie_1.1.2.deb`、`release/sophliteos_soc_1.1.2.deb`
  - `release/sophliteos_pcie_1.1.2_sdk.deb`、`release/sophliteos_soc_1.1.2_sdk.deb`（由 `package-deb-sdk.sh` 产出）
- 根 `README.md` 子项目表新增一行（显示名不带 `p` 前缀，与现有约定一致）：
  `| [sophliteos](./source/psophliteos) | source/psophliteos | 否 | 算力设备管理 Web 平台（Go+Vue），参考源码目录 README/build |`
- **不**纳入根 `release.sh` 一键编译：根脚本仅遍历 `source/*/` 调用各自 `release.sh`（依赖 amd64/7z/zip/dpkg-deb/pandoc），`psophliteos` 子目录不放 `release.sh` 即不被纳入，符合"不支持一键编译"。
- 子工程 `README.md` **重写**构建步骤：明确"frontend 源码已在 `frontend/` 下，无需 clone；进入 `build/` 执行 `build_2_release.sh`（需 docker + go + gcc-aarch64-linux-gnu）"。**不沿用**原 README 的"clone sophliteos-frontend"步骤。

## 8. 验证策略

1. 后端编译：`cd source/psophliteos && go build ./... && go vet ./...` 通过（依赖 §5.2 删函数后同步删 httpclient/system 两个 import）。
2. 前端构建：`cd source/psophliteos/frontend && yarn && yarn build` 通过。
3. 算法业务符号残留检查（应为 0，排除已知无关项）：
   `grep -rn "AlgoFlag\|IsAlgorithm\|accessAlgo\|algoliteos\|AlgoRegister\|AlgoExist\|upgradeAlgo\|algorithmGroup\|/algorithm\|paramConfig\|algoType\|algoThreshold" source/psophliteos`
   - 无关例外：`frontend/build/vite/plugin/compress.ts:29` 的 `algorithm:'brotliCompress'`（压缩算法名）；`client/ssm` 中"算力/订阅/授权"文案（设备管理）。
4. `/algorithm` 反代残留：`grep -rn "/algorithm\|algorithmGroup" source/psophliteos/initialization/router.go` 应为空。
5. 构建脚本残留：`grep -rn "sophliteos-frontend" source/psophliteos/build source/psophliteos` 应为空（§7.1 适配后无残留）。
6. i18n 残留：`grep -rn "accessAlgo\|taskList\|taskSubscribe\|dataSource\|mediaServers\|videoManage\|AlgoParamConfig\|alarmRetrieval\|alarmDetail\|paramConfig\|algoType\|algoThreshold" source/psophliteos/frontend/src/locales` 应为空。
7. 路由自检：`grep -rn "AlgoRegister\|AlgoExist\|CoreOperationApi" source/psophliteos/api source/psophliteos/router` 确认 `ApiGroup`/`RouterGroup` 不再引用已删符号（`CoreOperationApi` 本就未引用，保留死代码不报错）。

## 9. git 流程

1. `cd /home/zzt/workspace/sophon-tools`
2. `git checkout -b feat/psophliteos-import`（从 main 拉新分支）
3. 拷入裁剪后的树到 `source/psophliteos`（按 §4 排除 `.github`、`.gitpod.yml`、`.husky/`、`frontend/node_modules`、`frontend/dist`、原 `.gitignore`）
4. 按 §5 执行裁剪；按 §7.1 适配构建脚本；重写子工程 `README.md`
5. 按 §8 验证通过
6. 更新根 `README.md` 子项目表
7. 提交（平台导入为单次提交；本设计文档已作为该分支首个提交先行入库）：
   ```
   feat: import sophliteos device-management platform (trimmed)

   Import the sophliteos computing-device management platform (Go backend +
   Vue frontend + deb/tgz release pipeline) from sophgo-liteos, with the
   algoliteos algorithm-business integration removed (accessAlgo views/api,
   /algorithm reverse proxy, AlgoRegister/AlgoExist/Register, AlgoFlag,
   upgradeAlgo branch, the overview-store IsAlgorithm coupling, and the
   now-unused httpclient/system imports). Build scripts adapted to the flat
   frontend/ layout (no sophliteos-frontend subdir clone).

   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

> 该分支含两个提交：commit1 = 本设计文档（先入库以便追溯设计依据），commit2 = 平台导入。

## 10. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| overview store 耦合未删干净 → 运行期 `asyncRoutes.find('accessAlgo')` 返回 undefined，`algo.meta.hideMenu` 抛 TypeError | 高 | (B) overview 三处强制同删；§8 step3 grep 验证 |
| 删函数后未清理 import → go build 报 `imported and not used`（sys_base.go:10 httpclient、init.go:4 system） | 高 | §5.2 已显式列出两个 import 删除项；§8 step1 验证 |
| 构建脚本引用不存在的 `frontend/sophliteos-frontend` 子目录与 `.git` → 发布链路断裂 | 高 | §7.1 适配脚本到扁平布局；§8 step5 grep 验证无残留 |
| `permission` store globEager 仍加载未删的 accessAlgo.ts → 路由指向不存在的 view 报错 | 中 | (A) 必须删 `accessAlgo.ts` 文件本身，不能只删 views；自动加载在 router/routes/index.ts:10 |
| `sophon-tools` 是否共享/公开未知 | 低 | 方案 A 保证算法业务代码从不入库 |
| 硬编码版本 `V1.1.2` / commit hash `b74ff743...`（散落 build_2_release.sh/build_test.sh/DEBIAN/control/README.md/version.sh） | 低 | 本次不动，留作后续统一版本管理 |
| 死代码（`client/ws`、`sys_core_operation.go`、`sys_down.go`、`OtaRollback`、`NewProxy`）保留可能误导后续维护 | 低 | 本次忠于"当前版本"原样保留；注意 NewProxy 不可误删（维持 router.go 两 import） |
| `client/ssm/types.go` 的 `CtrlBasic.Configure.ServiceAddress` 含 register/keepalive/event 等字段（interface{} 占位未启用）语义像对接远端平台 | 低 | 当前未启用，不影响；目标设备部署时确认不被启用 |
| `.husky` 不拷入后无 commitlint | 低 | sophon-tools 自有提交规范；子工程不强制 |

**回退**：新分支 `feat/psophliteos-import` 独立于 main，不影响主干；不满意直接 `git branch -D feat/psophliteos-import`。

## 11. 附录：模块分类总表（来自全工程测绘）

### 11.1 keep（设备管理，保留）

- 后端 handler：`sys_alarm`/`sys_basic`/`sys_ip_query_set`/`sys_log_query`/`sys_ota`/`sys_password`/`sys_resource`/`sys_ssm_upgrade`/`sys_version`
- 后端 client：`client/ssm`（ssm.go + types.go，本机 9779）、`client/httpclient`（shared；注意 sys_base.go 删 Register() 后不再引用它，但其它处仍用，保留）
- `database`（User/Alarm/OptLog 三表 + dbconnect/dbschema/jsontime）
- `mvc`（core/error/i18n/validation/types/services）
- `middleware`（auth/block/timeout）
- `global`（去 AlgoFlag 后）、`initialization`（去 Register/AlgoFlag 后）、`config`、`logger`、`main.go`
- `build`、`scrip`、`release`
- 前端：`views/{overview,maintenance,logs,sys,demo}`、`api/{overview,logs,maintenance,sys,model,demo}`、`router/routes/modules/{overview,logs,maintenance}.ts`、`mock/{logs,maintenance,overview,sys,...}`

### 11.2 exclude（算法业务，删除）

- 前端：`views/accessAlgo/*`、`views/task/*`（占位桩）、`api/{task,dataSource,alrmRetrieval,paramConfig}`、`router/routes/modules/accessAlgo.ts`、`store/modules/alrmRetrieval.ts`、`mock/{taskList,dataSource}`、相关 locales（taskList/dataSource/alarmRetrieval/paramConfig 的 zh-CN+en）
- 后端（行级/函数级）：`/algorithm` 反代、`AlgoRegister/AlgoExist/Register`、`global.AlgoFlag`、`init.Register()`、`upgradeAlgo`

### 11.3 shared-keep（共享基础设施，保留）

- `api/v1/system/enter.go`、`router/system/enter.go`、`router/enter.go`（聚合入口）
- `mvc/{core,error,i18n,validation}`、`client/httpclient`、`config`、`logger`、`initialization/server.go`
- 前端 `layouts/components/logics/router` 基础设施、`locales`（裁算法 key 后）、`build/vite`

### 11.4 review（死代码/残留，本次原样保留）

- `api/v1/system/sys_core_operation.go`（CoreOperationApi 未挂载路由，ApiGroup 未嵌入）
- `api/v1/system/sys_down.go`：DownApi 类型与方法定义于此；DownRouter 定义于 `router/system/sys_app.go`，`initialization/router.go:54` 调用 `InitDownRouter(PublicGroup)`（未注释），但 `sys_app.go:16` 函数体内路由注册被注释 → 无有效端点
- `client/ws/ws.go`（SocketHandler 全仓无引用）
- `api/v1/system/sys_ota.go` 的 `OtaRollback`（未路由）
- `api/v1/system/sys_ssm_upgrade.go` 的 `installSsmCtrl`/`scpInstallSsm`（注释空实现，仅 return nil）
- `initialization/router.go` 的 `NewProxy`（第 77-81 行，全仓无引用；维持 `net/http/httputil`、`net/url` import 有效，删 `/algorithm` 块后不可误删）

## 12. 附录：关键依赖边

- `frontend/views/accessAlgo/*` → `router/routes/modules/accessAlgo.ts` → `api/{task,dataSource,alrmRetrieval,paramConfig}` → `.env.development` 的 `/algorithm` 代理 → 后端 `initialization/router.go` 的 `/algorithm` 反代 → algoliteos(127.0.0.1:8081，工程外)
- `initialization/init.go` 的 `system.Register()` → `sys_base.go` 的 `Register()`(GET 127.0.0.1:8081/algorithm/register) → `global.AlgoFlag`
- `frontend/store/modules/overview.ts` 的 `IsAlgorithm()` → `sys_base.go` 的 `AlgoExist`(GET /api/algorithm) → `global.AlgoFlag`
- `frontend/store/modules/overview.ts` 的 hideMenu → `accessAlgo.ts`（运行期耦合点，排除 accessAlgo 后必须删此引用）
- `sys_upgrade.go` 的 `upgradeAlgo()` → algoliteos 升级包（algoliteos-linux_*.tgz，文件名判断在 :40-47）
- 所有 device-mgmt handler → `client/ssm`(127.0.0.1:9779) → `client/httpclient`
- device-mgmt handler + `middleware/auth` → `database`(User/Alarm/OptLog)
- 所有 handler → `mvc/{core,error,i18n,validation,types,services}`
- `router/routes/index.ts:10` globEager → `router/routes/modules/*.ts`（含 accessAlgo.ts，删文件即可）
