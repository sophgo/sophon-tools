# sophon-tools psophliteos 设备管理平台拆分 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `sophgo-liteos`（sophliteos 设备管理平台）裁掉算法业务后，作为 `source/psophliteos` 纳入 `sophon-tools` 仓库 `feat/psophliteos-import` 分支，单次提交。

**Architecture:** 先 rsync 整树到 `source/psophliteos`（排除 vben 模板残留与构建产物），再行级/函数级裁剪后端 6 处 + 前端整删 + 4 处行级裁剪，适配构建脚本到扁平 frontend 布局，重写子工程 README 与根 README 表，全量验证后单次提交。源工程 `sophgo-liteos` 全程只读不动，回退即 `rm -rf source/psophliteos` 重来。

**Tech Stack:** Go 1.19 (gin/gorm/viper)、Vite/Vue (vue-vben-admin)、docker node:16 前端构建、dpkg-deb 打包、rsync。

**重要约束（用户决策 方案 A）：** 平台导入为**单次提交**。本计划中各 Task 之间的 `go build`/`yarn build`/grep 是**验证检查点**，不单独提交；仅在 Task 19 做唯一一次 `git commit`。行号均来自真实源码核验（2026-06-22）。

**前置事实：**
- `sophon-tools` 已在 `feat/psophliteos-import` 分支（commit `ee05ce6` = 设计文档），main 未动。
- `sophgo-liteos` 不是 git 仓库（源码解包），全程只读。
- `release/` 仅含 `.gitkeep`（无二进制）；`frontend/` 扁平（仅 package.json+src，无 node_modules/dist/.git）。

---

### Task 1: 拷入源树到 source/psophliteos

**Files:**
- Create: `/home/zzt/workspace/sophon-tools/source/psophliteos/`（整树）

- [ ] **Step 1: 确认在 feat 分支且工作区干净**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git branch --show-current && git status --short
```
Expected: `feat/psophliteos-import` 且无未提交变更（或仅 docs/ 已提交）。

- [ ] **Step 2: rsync 整树（排除 vben 残留与构建产物）**

Run:
```bash
rsync -a \
  --exclude='.github' \
  --exclude='.gitpod.yml' \
  --exclude='.husky' \
  --exclude='.gitignore' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='frontend/.git' \
  /home/zzt/workspace/sophgo-liteos/ \
  /home/zzt/workspace/sophon-tools/source/psophliteos/
```
Expected: 无输出（成功）。`source/psophliteos/` 下出现 api/build/frontend/.../main.go/go.mod 等。

- [ ] **Step 3: 验证拷入结果与排除项**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
ls -la && echo "--- 应无 .github/.husky/.gitpod.yml/.gitignore ---" && \
ls -d .github .husky .gitpod.yml .gitignore 2>&1
```
Expected: 顶层含 api/build/client/config/database/frontend/global/initialization/logger/middleware/mvc/router/scrip/release/main.go/go.mod/go.sum/.env*/README.md/.editorconfig/.eslintrc.js/.vscode 等；`.github/.husky/.gitpod.yml/.gitignore` 均报"无法访问"（已排除）。

- [ ] **Step 4: 确认 frontend 为扁平布局、release 仅 .gitkeep**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
ls frontend/ | head && echo "--- release ---" && ls -la release/
```
Expected: `frontend/` 直接含 `package.json src ...`（无 sophliteos-frontend 子目录）；`release/` 仅 `.gitkeep`。

> 检查点，不提交。

---

### Task 2: 后端 — 删除 initialization/router.go 的 /algorithm 反向代理块

**Files:**
- Modify: `source/psophliteos/initialization/router.go`（删除约 24-33 行的 algorithmGroup 块）

- [ ] **Step 1: 删除 /algorithm 反代块**

用 Edit 工具，old_string：
```
	// 创建一个反向代理到算法业务
	algoURL, _ := url.Parse("http://localhost:8081")
	proxy := httputil.NewSingleHostReverseProxy(algoURL)

	algorithmGroup := Router.Group("/algorithm")
	// 添加反向代理处理器
	algorithmGroup.Any("/*path", func(c *gin.Context) {
		proxy.ServeHTTP(c.Writer, c.Request)
	})

	systemRouter := router.RouterGroupApp.System
```
new_string：
```
	systemRouter := router.RouterGroupApp.System
```

- [ ] **Step 2: 验证 import 仍有效（NewProxy 维持 net/http/httputil 与 net/url）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -n "httputil\.\|url\." initialization/router.go
```
Expected: 命中 `NewProxy` 函数内（约第 77-81 行）的 `url.Parse` 与 `httputil.NewSingleHostReverseProxy`——两 import 仍被使用，无需删除。
> 注：`NewProxy` 是全仓无引用死代码，**保留**以维持这两个 import；不可误删 NewProxy。

> 检查点，不提交。

---

### Task 3: 后端 — 删除 sys_base.go 的 AlgoRegister/AlgoExist/Register 三函数 + httpclient import

**Files:**
- Modify: `source/psophliteos/api/v1/system/sys_base.go`（删第 10 行 import + 第 178-203 行三函数）

- [ ] **Step 1: 删除 httpclient import（删 Register() 后唯一引用点消失）**

Edit，old_string：
```
	"sophliteos/client/httpclient"
	"sophliteos/config"
```
new_string：
```
	"sophliteos/config"
```

- [ ] **Step 2: 删除 AlgoRegister/AlgoExist/Register 三个函数**

Edit，old_string：
```
func (b *BaseApi) AlgoRegister(c *gin.Context) {
	global.AlgoFlag = true
	c.JSON(http.StatusOK, mvc.Ok())
}

func (b *BaseApi) AlgoExist(c *gin.Context) {
	c.JSON(http.StatusOK, mvc.Success(global.AlgoFlag))
}

func Register() {
	var req struct {
		Msg  string `json:"msg"`
		Code int    `json:"code"`
	}
	logger.Info("尝试注册algoliteos服务")

	data, _ := httpclient.NewRequest("127.0.0.1:8081/algorithm/register", "GET", nil, nil)
	json.Unmarshal(data, &req)

	if req.Msg != "ok" {
		logger.Info("algoliteos未运行服务")
		return
	}
	logger.Info("注册到algoliteos服务成功")
	global.AlgoFlag = true
}

func getType(code int) string {
```
new_string：
```
func getType(code int) string {
```

- [ ] **Step 3: 确认 json/global 仍被使用（无需删这两个 import）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -nE "json\.|global\." api/v1/system/sys_base.go | head
```
Expected: `json.Unmarshal` 出现在 Login/AlarmListen（原 32/104/128 行，删函数后行号前移）；`global.LoginError`/`global.DeviceType`/`global.Resource` 等多处——两 import 保留。

> 检查点，不提交。

---

### Task 4: 后端 — 删除 router/system/sys_base.go 的 register/algorithm 两条路由

**Files:**
- Modify: `source/psophliteos/router/system/sys_base.go`（删第 20-21 行）

- [ ] **Step 1: 删除 register/algorithm 路由**

Edit，old_string：
```
		baseRouter.POST("device/alarm", baseApi.AlarmListen)
		baseRouter.GET("register", baseApi.AlgoRegister)
		baseRouter.GET("algorithm", baseApi.AlgoExist)

	}
```
new_string：
```
		baseRouter.POST("device/alarm", baseApi.AlarmListen)

	}
```

- [ ] **Step 2: 确认 global 仍被使用（第 14 行 global.TimeOut）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && grep -n "global\." router/system/sys_base.go
```
Expected: 命中 `middleware.TimeoutMiddleware(global.TimeOut)`——`global` import 保留。

> 检查点，不提交。

---

### Task 5: 后端 — 删除 global/global.go 的 AlgoFlag 字段

**Files:**
- Modify: `source/psophliteos/global/global.go`（删第 17 行）

- [ ] **Step 1: 删除 AlgoFlag 字段**

Edit，old_string：
```
	SdkVersion       string
	AlgoFlag         bool
	Resource         types.Resource
```
new_string：
```
	SdkVersion       string
	Resource         types.Resource
```

- [ ] **Step 2: 确认无残留 AlgoFlag 引用（后端）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && grep -rn "AlgoFlag" --include="*.go" .
```
Expected: 无输出（Task 3/6 已删所有引用）。若有命中，回查并删除。

> 检查点，不提交。

---

### Task 6: 后端 — 删除 initialization/init.go 的 AlgoFlag 初始化 + Register() + system import

**Files:**
- Modify: `source/psophliteos/initialization/init.go`（删第 4 行 import、第 36 行、第 45 行）

- [ ] **Step 1: 删除 system import（删第 45 行 Register() 后唯一引用点消失）**

Edit，old_string：
```
import (
	"sophliteos/api/v1/system"
	"sophliteos/client/ssm"
	"sophliteos/config"
```
new_string：
```
import (
	"sophliteos/client/ssm"
	"sophliteos/config"
```

- [ ] **Step 2: 删除 global.AlgoFlag = false（第 36 行）**

Edit，old_string：
```
	global.Version = services.VersionInit("release_version.txt")
	global.AlgoFlag = false

	_, err := ssm.SubscribeAlarm()
```
new_string：
```
	global.Version = services.VersionInit("release_version.txt")

	_, err := ssm.SubscribeAlarm()
```

- [ ] **Step 3: 删除 system.Register() 调用（第 45 行）**

Edit，old_string：
```
		logger.Info("SubscribeAlarm Ok")
	}

	system.Register()
}
```
new_string：
```
		logger.Info("SubscribeAlarm Ok")
	}
}
```

- [ ] **Step 4: 确认 ssm/global/services/config/database/logger import 仍被使用**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && grep -nE "ssm\.|global\.|services\.|config\.|database\.|logger\." initialization/init.go
```
Expected: 各 import 均有命中（config.LoadConfig/logger.InitLogging/database.InitDB/ssm.SubscribeAlarm/global.Version 等），保留。

> 检查点，不提交。

---

### Task 7: 后端 — 删除 sys_upgrade.go 的 algoliteos 升级分支 + upgradeAlgo 函数

**Files:**
- Modify: `source/psophliteos/api/v1/system/sys_upgrade.go`（删第 40-47 行分支 + 第 138-171 行 upgradeAlgo 函数）

- [ ] **Step 1: 删除 algoliteos 升级包文件名判断分支（第 40-47 行）**

Edit，old_string：
```
	if filename == "algoliteos-linux_arm64.tgz" || filename == "algoliteos-linux_amd64.tgz" {
		if err := upgradeAlgo(); err != nil {
			c.JSON(http.StatusOK, mvc.FailWithMsg(-1, "操作失败"))
		} else {
			c.JSON(http.StatusOK, mvc.Ok())
		}
		return
	}

	if filename != "sophliteos-linux_arm64.tgz" {
```
new_string：
```
	if filename != "sophliteos-linux_arm64.tgz" {
```

- [ ] **Step 2: 删除 upgradeAlgo 函数（第 138-171 行，函数体全注释仅 return nil）**

Edit，old_string：
```
func upgradeAlgo() error {
	/* if err := os.MkdirAll("/data/sophliteos/algo", 0755); err != nil {
		logger.Error("Failed to create directory", err)
		return err
	}
	os.Chmod("/data/sophliteos/algo", 0755)

	cmd := exec.Command("tar", "-xzf", filename, "-C", "/data/sophliteos/algo")
	cmd.Dir = "/data/sophliteos"

	// 执行命令
	err := cmd.Run()
	if err != nil {
		logger.Error("tar failed", err)
	}

	script := "/data/sophliteos/algo/upgrade.sh"
	// 检查脚本文件是否存在
	_, err = os.Stat(script)
	if err != nil {
		logger.Error("Script file not found:", err)
		return err
	}
	cmd = exec.Command("sudo", "/bin/bash", script)
	cmd.Dir = "/data/sophliteos/algo"
	err = cmd.Run()
	if err != nil {
		logger.Error("script failed", err)
		return err
	}

	logger.Info("algoliteos upgrade successful!") */
	return nil
}

// 文件上传控制
```
new_string：
```
// 文件上传控制
```

- [ ] **Step 3: 确认 os/exec/syscall/io/strings/errors/time import 仍被使用（restartUpgradedProgram/saveFile）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -nE "os\.|exec\.|syscall\.|io\.|strings\.|errors\.|time\." api/v1/system/sys_upgrade.go | head
```
Expected: `restartUpgradedProgram`（syscall.Exec/os.Exit/exec.Command/time.Sleep）与 `saveFile`（os.MkdirAll/os.OpenFile/io.Copy/strings.Contains/errors.New）命中——所有 import 保留。upgradeAlgo 函数体全注释本就不使用 import，删除不影响。

> 检查点，不提交。

---

### Task 8: 后端编译验证

**Files:** 无（仅验证）

- [ ] **Step 1: go build**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && go build ./...
```
Expected: 无输出（成功）。若报 `imported and not used`，回查对应 Task 的 import 清理；若报 `undefined: AlgoRegister/AlgoExist/Register/upgradeAlgo`，回查是否有遗漏引用。

- [ ] **Step 2: go vet**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && go vet ./...
```
Expected: 无输出或仅无害提示。

- [ ] **Step 3: 后端算法业务符号残留检查**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -rn "AlgoFlag\|AlgoRegister\|AlgoExist\|upgradeAlgo\|algorithmGroup\|/algorithm\|algoliteos" --include="*.go" .
```
Expected: 无输出。`/algorithm` 字符串只在已删的反代块中出现，应已清零。

> 检查点，不提交。后端裁剪完成。

---

### Task 9: 前端 — 删除算法业务整文件/整目录（A 清单）

**Files:**
- Delete: 见下

- [ ] **Step 1: 删除算法业务视图与路由模块**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
rm -rf src/views/accessAlgo src/views/task \
       src/router/routes/modules/accessAlgo.ts
```
Expected: 无输出。

- [ ] **Step 2: 删除算法业务 API 目录**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
rm -rf src/api/task src/api/dataSource src/api/alrmRetrieval src/api/paramConfig
```
Expected: 无输出。

- [ ] **Step 3: 删除算法业务 store**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
rm -f src/store/modules/alrmRetrieval.ts
```
Expected: 无输出。

- [ ] **Step 4: 删除算法业务 mock**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
rm -rf mock/taskList mock/dataSource
```
Expected: 无输出。

- [ ] **Step 5: 删除算法业务 locales 文件（zh-CN + en 各 4 个）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
rm -f src/locales/lang/zh-CN/taskList.ts \
      src/locales/lang/zh-CN/dataSource.ts \
      src/locales/lang/zh-CN/alarmRetrieval.ts \
      src/locales/lang/zh-CN/paramConfig.ts \
      src/locales/lang/en/taskList.ts \
      src/locales/lang/en/dataSource.ts \
      src/locales/lang/en/alarmRetrieval.ts \
      src/locales/lang/en/paramConfig.ts
```
Expected: 无输出。

- [ ] **Step 6: 验证设备管理 mock/视图/api 未误删**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
ls src/views && echo "--- mock ---" && ls mock && echo "--- api ---" && ls src/api && echo "--- routes ---" && ls src/router/routes/modules
```
Expected: `views` 含 `demo logs maintenance overview sys`（无 accessAlgo/task）；`mock` 含 `logs maintenance overview sys ...`（无 taskList/dataSource）；`api` 含 `demo logs maintenance model overview sys`（无 task/dataSource/alrmRetrieval/paramConfig）；`routes/modules` 含 `logs maintenance overview`（无 accessAlgo）。

> 检查点，不提交。

---

### Task 10: 前端 — 删除 .env.development 的 /algorithm 代理条目

**Files:**
- Modify: `source/psophliteos/frontend/.env.development`（第 15 行 VITE_PROXY）

- [ ] **Step 1: 删除 /algorithm 代理条目**

Edit，old_string：
```
VITE_PROXY = [["/algorithm","http://172.28.8.21:8081/algorithm"], ["/api","http://172.28.8.21:8080/api"],["/upload","http://localhost:3300/upload"]]
```
new_string：
```
VITE_PROXY = [["/api","http://172.28.8.21:8080/api"],["/upload","http://localhost:3300/upload"]]
```

- [ ] **Step 2: 验证无 /algorithm 残留**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && grep -n "/algorithm" .env.development
```
Expected: 无输出。

> 检查点，不提交。

---

### Task 11: 前端 — 删除 api/overview/index.ts 的 IsAlgorithm + isAlgo 枚举

**Files:**
- Modify: `source/psophliteos/frontend/src/api/overview/index.ts`（删第 10 行枚举 + 第 41-43 行函数）

- [ ] **Step 1: 删除 Api 枚举中的 isAlgo**

Edit，old_string：
```
  Software = '/device/version',
  isAlgo = '/algorithm',
}
```
new_string：
```
  Software = '/device/version',
}
```

- [ ] **Step 2: 删除 IsAlgorithm 函数**

Edit，old_string：
```
export function getSoftwareInfoApi() {
  return defHttp.get({ url: Api.Software });
}
export function IsAlgorithm() {
  return defHttp.get({ url: Api.isAlgo });
}
```
new_string：
```
export function getSoftwareInfoApi() {
  return defHttp.get({ url: Api.Software });
}
```

- [ ] **Step 3: 验证 IsAlgorithm 已无导出**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && grep -n "IsAlgorithm\|isAlgo" src/api/overview/index.ts
```
Expected: 无输出。

> 检查点，不提交。

---

### Task 12: 前端 — 删除 store/modules/overview.ts 的三处算法耦合（强制配套）

**Files:**
- Modify: `source/psophliteos/frontend/src/store/modules/overview.ts`（第 4/69/139-143 行）

- [ ] **Step 1: 改 import（去掉 IsAlgorithm）**

Edit，old_string：
```
import { resourceApi, IsAlgorithm } from '/@/api/overview/index';
```
new_string：
```
import { resourceApi } from '/@/api/overview/index';
```

- [ ] **Step 2: 删除 IsAlgorithm 调用（第 69 行）**

Edit，old_string：
```
      const result = await resourceApi();
      const isAlgo = await IsAlgorithm();

      if (result) {
```
new_string：
```
      const result = await resourceApi();

      if (result) {
```

- [ ] **Step 3: 删除 if(!isAlgo) hideMenu 块（第 139-143 行）**

Edit，old_string：
```
        if (!isAlgo) {
          const algo = asyncRoutes.find((item) => item.name === 'accessAlgo');
          algo.meta.hideMenu = true;
          permissionStore.buildRoutesAction();
          permissionStore.setLastBuildMenuTime();
        }
      }
      return result;
```
new_string：
```
      }
      return result;
```

- [ ] **Step 4: 验证 IsAlgorithm/accessAlgo 已无残留**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && grep -n "IsAlgorithm\|isAlgo\|accessAlgo" src/store/modules/overview.ts
```
Expected: 无输出。

> 检查点，不提交。此 Task 是最高风险项：若任一处未删，运行期 `asyncRoutes.find('accessAlgo')` 返回 undefined → `algo.meta.hideMenu` 抛 TypeError。

---

### Task 13: 前端 — 删除 dashboard.ts 的算法业务 i18n key（zh-CN + en）

**Files:**
- Modify: `source/psophliteos/frontend/src/locales/lang/zh-CN/routes/dashboard.ts`
- Modify: `source/psophliteos/frontend/src/locales/lang/en/routes/dashboard.ts`

- [ ] **Step 1: 删除 zh-CN dashboard.ts 的算法 key**

Edit，old_string：
```
  task: '任务管理',
  taskList: '任务查询',
  accessAlgo: '算法业务',
  taskSubscribe: '任务订阅',
  dataSource: '数据源维护',
  mediaServers: '流媒体服务',
  videoManage: '视频资源管理',
  AlgoParamConfig: '算法参数配置',
  alarmRetrieval: '告警检索',
  alarmDetail: '告警详情',
  coreBoardMap: '核心板端口映射',
```
new_string：
```
  coreBoardMap: '核心板端口映射',
```

- [ ] **Step 2: 读取 en/dashboard.ts 确认对应英文 key**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
grep -nE "task:|taskList:|accessAlgo:|taskSubscribe:|dataSource:|mediaServers:|videoManage:|AlgoParamConfig:|alarmRetrieval:|alarmDetail:" src/locales/lang/en/routes/dashboard.ts
```
Expected: 列出 en 版本中这些 key 的行与值（用于 Step 3 精确删除）。若 en 文件结构不同，据实情调整 old_string。

- [ ] **Step 3: 删除 en dashboard.ts 的算法 key**

据 Step 2 读到的实际内容，用 Edit 删除对应的 `task`/`taskList`/`accessAlgo`/`taskSubscribe`/`dataSource`/`mediaServers`/`videoManage`/`AlgoParamConfig`/`alarmRetrieval`/`alarmDetail` 行。示例（若 en 文件与 zh 结构一致）：
old_string 取这些连续行块，new_string 删除之。若不连续，逐行 Edit。

- [ ] **Step 4: 验证保留视图不引用已删 key**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
grep -rnE "taskList|taskSubscribe|accessAlgo|dataSource|mediaServers|videoManage|AlgoParamConfig|alarmRetrieval|alarmDetail" src/views/{overview,maintenance,logs,sys,demo} 2>/dev/null
```
Expected: 无输出（保留视图不引用这些 key）。若有命中，说明该 key 仍被设备管理视图使用——保留该 key 不删，并记录。

- [ ] **Step 5: 全 locales 残留检查**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
grep -rnE "accessAlgo|taskList|taskSubscribe|dataSource|mediaServers|videoManage|AlgoParamConfig|alarmRetrieval|alarmDetail|paramConfig|algoType|algoThreshold" src/locales
```
Expected: 无输出。

> 检查点，不提交。

---

### Task 14: 前端构建验证

**Files:** 无（仅验证）

- [ ] **Step 1: 全前端算法业务符号残留检查**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
grep -rnE "AlgoFlag|IsAlgorithm|accessAlgo|algoliteos|/algorithm|paramConfig|algoType|algoThreshold" src mock .env.development
```
Expected: 无输出（仅 `build/vite/plugin/compress.ts` 的 `algorithm:'brotliCompress'` 不在本 grep 范围/属无关项）。

- [ ] **Step 2: （可选）yarn build 验证编译**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && yarn && yarn build
```
Expected: 构建成功，生成 `dist/`。若本机无 node/yarn 环境，跳过此步（§7.1 的 docker 构建在发布时验证），但 Step 1 的 grep 必须通过。
> 若 `import.meta.globEager` 报 accessAlgo.ts 缺失，说明 Task 9 漏删了某处对它的引用——回查 `grep -rn "accessAlgo" src`。

> 检查点，不提交。前端裁剪完成。

---

### Task 15: 构建脚本适配到扁平 frontend 布局（blocker 修复）

**Files:**
- Modify: `source/psophliteos/build/build_2_release.sh`（第 16-17 行）
- Modify: `source/psophliteos/build/build_test.sh`（第 15 行 cp）
- Modify: `source/psophliteos/build/version.sh`（删第 11-16 行前端 git 块）

- [ ] **Step 1: build_2_release.sh 第 16 行 docker cd 路径**

Edit，old_string：
```
docker run --rm -i --name node-build -v `pwd`/../frontend/:/home/node node:16 sh -c 'cd /home/node/sophliteos-frontend && yarn && yarn build'
cp -r ../frontend/sophliteos-frontend/dist ../
```
new_string：
```
docker run --rm -i --name node-build -v `pwd`/../frontend/:/home/node node:16 sh -c 'cd /home/node && yarn && yarn build'
cp -r ../frontend/dist ../
```

- [ ] **Step 2: build_test.sh 第 15 行 cp 路径**

Edit，old_string：
```
cp -r ../frontend/sophliteos-frontend/dist ../
```
new_string：
```
cp -r ../frontend/dist ../
```
> 注：build_test.sh 中此 cp 行是文件内唯一该字符串；若 Edit 报不唯一，用 `grep -n "sophliteos-frontend" build/build_test.sh` 定位后据实改。

- [ ] **Step 3: version.sh 删除前端独立 git 块（第 11-16 行）**

Edit，old_string：
```
printf  "module:sophliteos-build(master)\n" > release_version.txt
printf  "commit b74ff743953a8b17622ba382e9cedfd659d63e10\n\n" >> release_version.txt


project_path="../frontend/sophliteos-frontend"
branch=$(git --git-dir="$project_path/.git" rev-parse --abbrev-ref HEAD)
printf "module:sophliteos-frontend(%s)\n" "$branch" >> release_version.txt

commit=$(git --git-dir="$project_path/.git" rev-parse HEAD)
printf "commit %s\n\n" >> release_version.txt

# 设置Git项目路径
project_path=".."
```
new_string：
```
printf  "module:sophliteos-build(master)\n" > release_version.txt
printf  "commit b74ff743953a8b17622ba382e9cedfd659d63e10\n\n" >> release_version.txt

# 设置Git项目路径
project_path=".."
```
> 说明：前端已并入 monorepo，后端块（`project_path=".."` + git rev-parse）已记录 monorepo commit，覆盖前端版本，故前端独立 git 块整块删除。硬编码 commit hash `b74ff743...` 属版本硬编码遗留（spec §10），本次不动。

- [ ] **Step 4: 验证无 sophliteos-frontend 残留**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && grep -rn "sophliteos-frontend" build .
```
Expected: 无输出（构建脚本与全工程无 sophliteos-frontend 引用）。

> 检查点，不提交。

---

### Task 16: 子工程 README 重写 + 新建 .gitignore

**Files:**
- Modify: `source/psophliteos/README.md`（重写构建步骤）
- Create: `source/psophliteos/.gitignore`

- [ ] **Step 1: 重写子工程 README**

用 Write 工具覆盖 `source/psophliteos/README.md`，内容：
````markdown
# sophliteos

算力设备管理系统（SophLiteOS）—— Sophgo 算力设备的 Web 管理平台，提供设备资源监控、告警、日志、网络/IP、密码、OTA/SSM 升级、版本等设备运维功能。

> 本子工程自 `sophgo-liteos` 迁入并裁剪掉 algoliteos 算法业务集成。

## 目录结构
- `api`: 后端业务控制器（device-mgmt handlers）
- `router`: 路由定义
- `client/ssm`: 设备端 SSM(System Service Manager, 127.0.0.1:9779) 接口客户端
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
````

- [ ] **Step 2: 新建子工程 .gitignore**

用 Write 工具创建 `source/psophliteos/.gitignore`，内容：
```
# 前端依赖与构建产物
frontend/node_modules/
frontend/dist/
frontend/.yarn/

# 后端构建产物
sophliteos
sophliteos-linux_*.tgz
dist/

# 发布产物
release/sophliteos*
build/release*
build/sophliteos/data/sophliteos/*

# 测试
test
```

- [ ] **Step 3: 验证**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && head -5 README.md && echo "---" && cat .gitignore
```
Expected: README 首行为 `# sophliteos`；.gitignore 含上述规则。

> 检查点，不提交。

---

### Task 17: 根 README 子项目表新增 psophliteos 行

**Files:**
- Modify: `/home/zzt/workspace/sophon-tools/README.md`（子项目表末尾追加一行）

- [ ] **Step 1: 在表末尾（get_info_exporter 行后）追加 psophliteos 行**

Edit，old_string：
```
| [get_info_exporter](./source/pget_info_exporter) | source/pget_info_exporter | 否 | 用于SE5/SE7/SE9的exporter实现 |
```
new_string：
```
| [get_info_exporter](./source/pget_info_exporter) | source/pget_info_exporter | 否 | 用于SE5/SE7/SE9的exporter实现 |
| [sophliteos](./source/psophliteos) | source/psophliteos | 否 | 算力设备管理 Web 平台（Go+Vue），参考源码目录 README/build |
```
> 显示名 `sophliteos`（不带 p 前缀，与现有 `[bmsec]`/`[socbak]` 等约定一致）；路径 `source/psophliteos`；"否"=不支持根 release.sh 一键编译（需 docker+go）。

- [ ] **Step 2: 验证**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && grep -n "psophliteos\|sophliteos" README.md
```
Expected: 命中新追加行。

> 检查点，不提交。

---

### Task 18: 全量验证（spec §8）

**Files:** 无（仅验证）

- [ ] **Step 1: 后端编译**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && go build ./... && go vet ./...
```
Expected: 无输出（成功）。

- [ ] **Step 2: 算法业务符号全工程残留检查**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -rnE "AlgoFlag|IsAlgorithm|accessAlgo|algoliteos|AlgoRegister|AlgoExist|upgradeAlgo|algorithmGroup|/algorithm|paramConfig|algoType|algoThreshold" . --include="*.go" --include="*.ts" --include="*.vue" --include="*.env*" --include="*.sh" 2>/dev/null | grep -v "node_modules"
```
Expected: 无输出。唯一例外 `frontend/build/vite/plugin/compress.ts` 的 `algorithm:'brotliCompress'` 不匹配上述模式（无 `/algorithm`），故应为空。

- [ ] **Step 3: /algorithm 反代与 sophliteos-frontend 残留**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -rn "/algorithm\|algorithmGroup\|sophliteos-frontend" initialization/router.go build .
```
Expected: 无输出。

- [ ] **Step 4: i18n 残留**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && \
grep -rnE "accessAlgo|taskList|taskSubscribe|dataSource|mediaServers|videoManage|AlgoParamConfig|alarmRetrieval|alarmDetail|paramConfig|algoType|algoThreshold" src/locales
```
Expected: 无输出。

- [ ] **Step 5: 路由自检（ApiGroup/RouterGroup 不引用已删符号）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos && \
grep -rn "AlgoRegister\|AlgoExist\|CoreOperationApi" api router
```
Expected: 无 `AlgoRegister`/`AlgoExist` 命中（CoreOperationApi 本就未引用，不应出现）。

- [ ] **Step 6: 前端构建（若环境允许）**

Run:
```bash
cd /home/zzt/workspace/sophon-tools/source/psophliteos/frontend && yarn && yarn build
```
Expected: 成功生成 `dist/`。无 node 环境则跳过，但 Step 1-5 必须全过。

> 检查点，不提交。全部裁剪与适配完成，准备提交。

---

### Task 19: 单次提交（方案 A）

**Files:** 无（git 提交）

- [ ] **Step 1: 查看待提交变更概览**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git status --short | head -30 && echo "--- 新增文件数 ---" && git status --short | wc -l
```
Expected: 大量新增（source/psophliteos/*）+ 修改（README.md）。`source/psophliteos/frontend/node_modules` 与 `dist` 不应出现（.gitignore 生效；且拷入时已排除）。

- [ ] **Step 2: 暂存**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git add source/psophliteos README.md
```
Expected: 无输出。

- [ ] **Step 3: 确认未误纳入构建产物**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git diff --cached --name-only | grep -E "node_modules|/dist/|\.tgz$|\.deb$" || echo "干净：无构建产物"
```
Expected: `干净：无构建产物`。

- [ ] **Step 4: 单次提交**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git commit -m "$(cat <<'EOF'
feat: import sophliteos device-management platform (trimmed)

Import the sophliteos computing-device management platform (Go backend +
Vue frontend + deb/tgz release pipeline) from sophgo-liteos, with the
algoliteos algorithm-business integration removed (accessAlgo views/api,
/algorithm reverse proxy, AlgoRegister/AlgoExist/Register, AlgoFlag,
upgradeAlgo branch, the overview-store IsAlgorithm coupling, and the
now-unused httpclient/system imports). Build scripts adapted to the flat
frontend/ layout (no sophliteos-frontend subdir clone).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```
Expected: 提交成功，输出变更统计。

- [ ] **Step 5: 确认分支提交历史**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git log --oneline -3
```
Expected:
```
<hash> feat: import sophliteos device-management platform (trimmed)
ee05ce6 docs: add psophliteos device-management split design spec
91de034 fix(dfss_cpp): update loongarch64 toolchain prefix and fix mingw build
```

- [ ] **Step 6: 确认 main 未动**

Run:
```bash
cd /home/zzt/workspace/sophon-tools && git log --oneline main -1
```
Expected: `91de034 fix(dfss_cpp): ...`（main 仍停在原处）。

**完成。** 平台已作为 `source/psophliteos` 纳入 `feat/psophliteos-import` 分支，算法业务已排除，构建脚本已适配扁平布局，单次提交。后续可按需合并到 main 或发版。

---

## Self-Review

**1. Spec coverage：** 逐节核对 spec → 计划覆盖：
- §3 决策（排除算法业务/完整平台/方案A单次提交/psophliteos/不入根release.sh/裁剪粒度/.github不拷）→ Task 1,9,15,16,17,19 ✓
- §4 工程结构（排除.github/.gitpod.yml/.husky/.gitignore；NewProxy保留）→ Task 1,2 ✓
- §5.1 整删 18 项 → Task 9 ✓
- §5.2 行级裁剪 11 项（含 httpclient/system import 清理）→ Task 2-7 ✓
- §6 overview 耦合强制配套 → Task 12 ✓
- §7.1 构建脚本适配 3 文件 → Task 15 ✓
- §7.2 产物/根README表/不纳入根release → Task 16,17 ✓
- §8 七步验证 → Task 8,14,18 ✓
- §9 git 流程（commit1=设计文档已在 ee05ce6，commit2=平台导入）→ Task 19 ✓
- §10 风险（import清理/overview耦合/脚本适配均已在对应 Task 的步骤与验证覆盖）✓

**2. Placeholder scan：** Step 13 Task 3（en dashboard.ts 删除）依据 Step 2 实读内容操作，非占位——已要求先读再据实 Edit。其余步骤均含确切 old/new 字符串或命令。无 TBD/TODO。

**3. Type consistency：** `AlgoFlag`/`AlgoRegister`/`AlgoExist`/`Register()`/`upgradeAlgo`/`IsAlgorithm`/`accessAlgo` 等符号在删除步骤与验证 grep 中命名一致。`source/psophliteos` 路径全程一致。

无遗漏，计划可执行。
