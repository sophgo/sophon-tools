# DSH（DeepSeek Harness）agent：装什么、怎么配、代理怎么交接登录

DSH 是第四个内置 agent，形态与另外三个一致：离线一键安装、启动 / 停止 / 自启动、
在控制台内嵌页面、重置、卸载、同步配置；默认用本机模型，预配置 `cv84x6` MCP。
它排在 Agent 页第一张卡（MYS-2293 的要求）。

和另外三个不同的是：**DSH 的 Web 页面没有密码**。它的登录凭证是启动时打印在 stdout
上的一行带 token 的 URL，只用一次。所以这个 agent 多出一套「代理代浏览器兑换 cookie」
的逻辑，这是本文档最主要的一节。

- 版本：`@deepseek-ai/dsh@0.2.1-rc.5`（npm，MIT）
- 端口：`14099`，只监听 `127.0.0.1`
- Node：私有 `24.22.1`（与 OpenClaw 同一个 tarball）。实测 DSH 的 `engines.node`
  下限是 `>=22.19.0`，板子自带的 22.22.2 也能跑；仍然用私有 Node 的理由是隔离
  ——两个 agent 不能因为对解释器的理解不同而互相弄坏，而这个运行时已经下载、校验、
  共享过了。
- 内存：空闲约 **430 MB**，对话后约 **470 MB**，单进程（无 fork 子进程）。

## 1. 安装包

两个 artifact，和 OpenClaw 一样叠在 agent 自己的目录里：

| 层 | 内容 | 大小 |
|---|---|---|
| `runtime/node` | Node 24.22.1（`node-v24.22.1-linux-arm64.tar.xz`） | 31 MB |
| `app` | 预构建的 `npm install --omit=dev @deepseek-ai/dsh@0.2.1-rc.5` 树 | 160 MB（gz） |

`app` 包在**目标架构**上打（`npm install --os=linux --cpu=arm64`），所以
`node-pty`、`koffi`、`sharp`、`node-addon-system` 这些原生依赖拿到的都是
aarch64 的预编译产物，板上不需要编译任何东西。实测 arm64 树里没有任何需要
`node-gyp` 的包：

```
$ find node_modules -name '*.node' | xargs file | grep -c aarch64   # 15/15
```

打包含前端产物（`@deepseek-ai/dsh-web-frontend/dist`，5.4 MB），所以板子上不需要
node/build 工具链。构建配方：

```bash
mkdir -p rt && cd rt
npm install --omit=dev --no-audit --no-fund --os=linux --cpu=arm64 \
  @deepseek-ai/dsh@0.2.1-rc.5
mkdir -p ../app && mv node_modules ../app/
cd .. && tar czf dsh-0.2.1-rc.5-app-linux-arm64.tar.gz app
```

**安装包不提交到仓库，也不由本 agent 上传 dfss。** 放到
`/mnt/sda2/cv84x6_llm_server/agents_mirror/`，由负责人上传到路径
`/tools/cv84x6_llm_server/agents/`；`app/agents/dsh.py` 里的 dfss 路径和 sha256
按约定写好。

## 2. 配置写在哪个文件

**结论：写 profile 自己的 patch（`$DSH_HOME/profiles/web/cordis.patch.yml`），
但只改我们管理的那几行。**

这条是实测定下来的，两条显而易见的做法都不行：

1. **写 `$DSH_HOME/cordis.patch.yml`（home 层）**：home 层在 profile 层之后应用。
   DSH 的设置页保存时会比对组合结果，发现被外层覆盖就直接拒绝：
   `Error: Configuration for "<id>" is overridden by a home patch or command-line overlay`
   （`dsh-config-editor` 的 `edit()`）。模型页会被我们弄坏。
2. **整个重写 profile patch**：这个文件正是 DSH 设置页写的，里面可能有用户从 UI
   加的插件、MCP server。重写等于删掉用户的工作。

所以 `write_config` 做的是**按 id 合并**：替换我们管理的行，其余行（包括用户自己
`insert:` 的）逐字节保留。管理的 id 是
`agent-default-model`、`session-telemetry-otel`、`sandbox-policy`、`approval`、
`permission`、`working-directory`、`workspace-controller`、`ui-settings-models`、
`mcp-cv84x6`。

### 模型路由是「行里的一个 key」，不是自己的一行

`llm-pi-ai` 是 DSH 自带的行。**同一个插件不能挂两次**——实测，插一条
`id: llm-pi-ai-cv84x6` 的 insert 行会被直接拒：

```
$ dsh --profile web --dump-config
dsh: [profiles/web/cordis.patch.yml] patch: entry "llm-pi-ai-cv84x6" not found

$ dsh --profile web --no-open --port 14097
dsh: warning: 1 entry did not activate
llm-pi-ai-cv84x6 (@deepseek-ai/dsh-llm-pi-ai): LlmError: configurable provider
"amazon-bedrock" is already declared
```

`dsh-llm-pi-ai` 的 `apply` 每进程只注册一次内置 provider 表，第二份就撞了。所以
本服务只写 **`providers.cv84x6` 这一个 key**，行里其它 provider（用户从模型页加的）
原样保留。合并是按缩进做的行级手术：只换最深的那个 key，父级里兄弟 key 一个不动。

### 为什么每一行都要写全字段

实测（`dsh --dump-config`）：**patch 替换整块 `config`，不合并**。写：

```yaml
- id: sandbox-policy
  config: {mode: workspace-write}
```

得到的就是 `{mode: workspace-write}`，bundle 里那个 `workspaceRoot: process.cwd()`
**被删掉了**。所以生成的每一行都把它需要的键写全——少写一个键不是「用默认值」，
而是「把这个键删掉」。

（`llm-pi-ai` 是唯一例外，因为它是 DSH 自己的行：`providers` 下面还有用户加的
provider，整块替换会把它们删掉。所以那一行只替换 `providers.cv84x6`，见上一节。）

### 层序

实测（逐层改同一个键，看 `--dump-config`），后者覆盖前者：

```
bundle patch（dsh-base → dsh-web-app） → profiles/web/cordis.patch.yml → $DSH_HOME/cordis.patch.yml → --patch
```

`app/agents/dsh.py` 只写第二层，别的都不碰。

## 3. 配置内容

```yaml
- id: 'agent-default-model'
  config:
    provider: 'cv84x6'
    model: '<默认模型 id>'
    reasoningEffort: 'off'          # 思考开关打开时是 'low'

# 注意：这是 DSH 自带的 llm-pi-ai 行，本服务只贡献 providers.cv84x6 这一个 key。
# 同一插件的第二行会被拒（见上一节）。
- id: 'llm-pi-ai'
  config:
    providers:
      cv84x6:
        displayName: 'CV84X6 本机'
        api: 'openai-completions'
        baseURL: 'http://127.0.0.1:<服务端口>/v1'
        headers:
          Authorization: 'Bearer <API Key>'
        models:
          - id: '<模型 id>'
            contextWindow: 32768
            maxTokens: 16384       # min(16384, context/2)
            reasoningEfforts: {off: null, low: 'low', high: 'high'}
            input: ['text', 'image']   # 按模型是否支持图片
        compat:
          maxTokensField: 'max_tokens'
          thinkingFormat: 'qwen'
        timeoutMs: 1800000
        streamIdleTimeoutMs: 1800000

- id: 'session-telemetry-otel'
  config: {mode: 'DISABLED'}

- id: 'sandbox-policy'
  config: {mode: 'workspace-write', workspaceRoot: '<agent>/workspace'}

- id: 'approval'
  config: {policy: 'never'}

- id: 'working-directory'
  config: {defaultDirectory: '<agent>/workspace'}

- insert:
  - id: 'mcp-cv84x6'
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: 'cv84x6'
      transport: 'streamable-http'
      url: 'http://127.0.0.1:<服务端口>/mcp'
      headers: {Authorization: 'Bearer <API Key>'}
      reconnect: {maxAttempts: 30}
      failOnStartupError: true
```

### 逐个字段的实测依据

**`api: openai-completions` + 自定义 `baseURL`** —— DSH 能对接自定义 OpenAI
兼容端点，不用 DeepSeek 官方 API。`dsh-llm-pi-ai` 的 `providers.<name>` 就是
"任意 OpenAI 兼容网关"那个配置面；实测抓到的请求是
`POST /v1/chat/completions`，`Authorization: Bearer <key>`。

**`compat.maxTokensField: max_tokens`** —— 不是装饰。pi-ai 默认发
`max_completion_tokens`，本服务的 `ChatCompletionRequest` 读 `max_tokens`，
不写这个键就会静默退回 512 输出上限。实测：不写时抓到
`max_completion_tokens: 16384`；写了之后是 `max_tokens: 16384`。

**`reasoningEfforts` + `compat.thinkingFormat: qwen`** —— 思考开关真正生效的地方。
pi-ai 对"没有任何 reasoning 元数据的模型"只报 `off` 一档，而 `off` 被翻译成
**省略**参数——模型模板默认怎么想还怎么想。声明了档位之后，`off` 变成显式的
`enable_thinking: false`。实测：
`.071` 不写 `reasoningEfforts` 时 `enable_thinking` 字段完全不出现；写了之后
抓到 `enable_thinking: false`。另外不声明档位时选 `off` 会直接被拒：
`UNSUPPORTED_REASONING_EFFORT: provider "cv84x6" model "..." does not support reasoning effort "off"`。

**`timeoutMs` / `streamIdleTimeoutMs`** —— pi-ai 的流空闲默认 5 分钟，这块板
约 20 tok/s，一个长回答会被中途掐断。

**`session-telemetry-otel: DISABLED`** —— DSH 默认 `FEEDBACK_ONLY`，会往
`https://dsh-otel-collector.deepseeksvc.com/v1/logs` 发 session 日志。设备通常
离线，那个 exporter 只会一直超时。`DISABLED` 时连 transport 都不构造。桌面端的
product analytics 两个 plugin 本来就 `disabled`（`profileContext.name !== 'desktop'`），
Web 不采集。

**`sandbox-policy: workspace-write`** —— bash / 文件工具只在
`<agent>/workspace` 和 `/tmp` 里能写，别的都拒。和另外三个 agent 的边界一致。
**注意**：`sandbox-policy` 和 `approval` 必须成对考虑——`permission` 插件会在
两者组合匹配不到任何 preset 时报错（`composed sandbox and approval defaults match
no preset`）。`workspace-write` + `ask` / `danger-full-access` + `never` 是
bundle 自带的两组。

**`working-directory.defaultDirectory`** —— DSH 默认用启动目录；管理器已经把
`cwd` 设成 `<agent>/workspace`，写这个键只是不让两边在 DSH 改默认值时走散。

## 4. MCP

`dsh-mcp-client` 支持远程 Streamable HTTP。**`transport` 必填**：只给 `url`
时它按 stdio 推断，然后去 spawn 一个名字叫 URL 的程序。

实测（对着一个只实现五个方法的 mock `/mcp`，带 Bearer）：

```
POST /mcp  server/discover   (protocolVersion 2026-07-28)
POST /mcp  initialize        (protocolVersion 2025-11-25)
POST /mcp  notifications/initialized
POST /mcp  tools/list
```

工具在模型侧的名字是 `mcp__<serverName>__<name>`，即 `mcp__cv84x6__kb_search`。
实测请求体里能看到这些工具。

### 连不上时它默认一声不吭

这是最要紧的一条。DSH 只注册了一个日志 exporter
（`dsh-app-boot/lib/index.js:4511`），而它只把 warn/error **缓冲起来**，等
`StartupError` 时一起报。**没有任何东西把 `ctx.logger` 写到 stdout**。所以：

- `mcp-client(cv84x6): connection attempt failed …` —— 从来不打印；
- `mcp-client(cv84x6): giving up after 10 consecutive failed attempts` —— 从来不打印。

实测：`/mcp` 没起时启动一个 DSH，`wc -l out.log` 是 **1**（只有那行启动 URL）。
这正是"静默地没有工具"。

`failOnStartupError: true` 把它变成可见的，而且**不会让启动失败**：

```
dsh: warning: 1 entry did not activate
mcp-cv84x6 (@deepseek-ai/dsh-mcp-client): Error: mcp-client(cv84x6): initial
connection or tool synchronization failed
    … SdkError: Version negotiation probe failed: fetch failed
    … Error: connect ECONNREFUSED 127.0.0.1:19999
```

进程照样服务：`GET /manifest.webmanifest` → **200**，`GET /` → 401。失败的那个
entry 不在 required 集合里，`auditStartupEntries` 只 warn 不抛。

**时机是确定的**：给每行打时间戳抓了一次，警告比启动 URL 行还早 **40 ms**
（`gap_s = -0.04`）。所以只要看到启动行，就一定能读到（或读到没有）这个警告，不需要
额外等待。`after_start` 依靠这一点。

### 失败之后怎么恢复（实测四种）

| 失败的 entry，之后把 `/mcp` 起来 | 工具注册上了吗 |
|---|---|
| 等 100 秒，什么都不改 | **没有**（mock 收到 0 个请求）|
| 用**完全相同的字节**重写 patch（只改 mtime）| **没有**（0）|
| 改一个值（比如 Bearer）| **有**（4 个请求：discover/initialize/notify/tools-list）|
| 重启 DSH | **有**（4）|

所以卡片上的建议是「**重启**」，不是「点同步配置重试」——同步通常写出一样的字节，
对已经 failed 的 entry 没有任何作用（cordis 的 HMR 只在组合结果真的变了才重载）。

代价说明：开 `failOnStartupError` 之后，如果 `/mcp` 只是**晚了一点**（本服务还在
启动），DSH 自己那条重连循环属于已经失败的 entry，不会再跑；实测等 100 秒不会自己
好。默认 `false` 时相反——晚起的 `/mcp` 在 DSH 的 ~2.5 分钟退避窗口内会自己连上，
但彻底连不上时一个字都不说。这里选了「说清楚」，因为静默失败是用户真正会踩到的那个。
`reconnect.maxAttempts: 30` 把窗口从 10 次加宽，给同一块板上服务与 agent 的启动
错峰留余量。

卡片上的那句话来自 `DshSpec.runtime_warning`，它在每次状态轮询时读日志尾部（按
size+mtime+摘要做缓存，所以轮询不重复扫）。**只看当前这个进程写的那一段**：
`agent.log` 是跨重启追加的，上一个进程的警告在上面；重启修好之后还报它就是在
骗人。所以 `forget_launch_url()`（每次 launch 都调）记下当时的文件大小，警告只在
这个偏移之后找。实测：修之前用健康的 `/mcp` 重启，卡片上仍然挂着"没有连上"。

## 5. 启动命令

```bash
<agent>/runtime/node/bin/node <agent>/app/node_modules/@deepseek-ai/dsh/lib/bin.js \
  --profile web --no-open --port 14099
```

**参数顺序是硬要求，不是风格**：launcher 只解析自己的 flag，**遇到第一个不认识的
token 就把后面全部交给 app**。把 `--port` 写前面（最自然的写法）会让后面的
`--patch` 变成 app 的参数，然后被拒：

```
error: unknown option '--patch'
```

没有 `--host`：DSH 默认就绑 loopback，而且它只接受具体的本机 IP 字面量，**拒绝
通配地址**（`0.0.0.0` 会直接被拒）。

## 6. 登录：token 交接（本 agent 特有）

DSH 的 Web 界面：

- 每个路径都在会话 cookie 之后，没有 cookie 一律 `401`；
- 唯一例外是 `GET /?token=<43 字符>`：换一个签名 cookie，然后 `303` 跳到 `./`；
- 每个 API 请求和 WebSocket 都要认证，并校验 Host / Origin。

token 只在启动时打印一次，而且**不能出现在控制台页面、日志接口或 `/api/agents`
里**。所以流程是：

1. **spec 从 agent 自己的日志里读出那一行**（只留最后一个匹配——监管进程崩溃重启后
   每个进程一个新 token，旧的那行已经没用了）。
2. **记在内存里**（spec 实例上的 `_launch_cache`），并写一份到
   `state/launch-url`（0600）——服务重启后接管仍在运行的 DSH 时，日志里已经
   没有 token 了，这一份是唯一来源。
   - 内存这份的 key 里含**日志身份**（size + mtime_ns + 尾部摘要），所以新进程
     append 了一行之后旧值不可能再被命中；
   - 每次 launch 之前（`manager._spawn`，控制台启动 / 重启 / 监管进程崩溃重启
     三条路都经过这里）还会调 `forget_launch_url()`，把内存和
     `state/launch-url` 一起清掉。
   - 这两道都必要：只清内存，服务重启接管就废了；只按日志身份，`state/launch-url`
     里上一代进程的 token 会被当成"日志里没行时的兜底"继续用出去。修之前的表现是
     ——agent 只要重启过一次，`/agents/dsh/` 就一直 503，直到整个服务重启。
3. **日志文件本身不动**，但 `GET /api/agents/<id>/logs` 出口会过一遍
   `public_log`，把 token 换成 `token=<redacted>`。
   为什么不是改文件：管理器把这个文件直接当成 agent 的 stdout，agent 自己握着
   偏移量；改写前缀再截断会丢掉 agent 在这之间写的所有内容（实测：日志只剩那一行
   启动 URL，插件报错全没了）。为了藏一个没人会从文件里读到的 token 而丢掉 agent
   自己的诊断信息，是笔坏买卖——要求本身说的是"不能出现在日志接口里"。
4. **代理在浏览器第一次访问页面时兑换**：
   - 上游 `401` + `Accept: text/html` + `GET` → 才值得兑换；
   - 拿 spec 给的 tokenized URL 去 `GET`，得到 `303` + `Set-Cookie`；
   - 把 cookie 的 `Path` 收窄到 `/agents/dsh/`，`303` 回浏览器刚才那个 URL；
   - 浏览器带着 cookie 再请求，就是正常 `200`。
5. **兑换请求本身不能进服务日志**：`httpx` 在 INFO 级别会把
   `GET http://…?token=…` 写出来，而本服务根 logger 就是 INFO。兑换的那一次调用
   临时把 `httpx` logger 提到 WARNING（`finally` 里恢复），传输异常也先抹掉 URL
   里的 token 再记。

资源（JS/CSS/XHR）的 401 **不兑换**：那说明会话中途掉了，在这里重签只会把问题藏起来，
还会和同时在飞的请求打架。

**只有 DSH 会走这条路**：基类的 `upstream_launch_url` 返回 `None` 表示「这个 agent
没有交接」，而 `""` 表示「有交接，但 token 还没打印出来」。区分这两个值很要紧——
只判断 `callable()` 的话每个 agent 都成立，opencode / PicoClaw / OpenClaw 普通的
401 会被换成本服务那句"日志里没有带 token 的地址"，对着一个根本没有 token 的 agent
说这话是错的。

日志接口和 `/api/agents` 之外还有一层：`GET /api/agents/<id>/logs` 返回前也会过一遍
`public_log`，所以即使有人手工把 token 写回日志，接口也不会把它吐出来。

### Host / Origin

DSH 的浏览器围栏是 `isSameAuthorityOrigin(origin, host)`——**Origin 必须等于请求
自己的 Host**。而代理原来给上游的是"服务端口"的 origin、agent 端口的 Host，两个不
一样，于是每个调用都 `403`。所以 spec 上有一个标量 `origin_is_host`：为真时，代理
让两个头用同一个 authority（agent 自己的），并丢掉浏览器的 `Sec-Fetch-Site`
（围栏在 Origin 之前就会拒 `cross-site`；而控制台内嵌的页面本来是同源）。

OpenClaw 保持 `False`：它校验的是 `controlUi.allowedOrigins` 这个允许列表，填的是
**本服务**的 origin，把 agent 的 authority 递过去反而是 403。这两种语义不能互换，
所以按 spec 分开。

WebSocket 同理：`origin_is_host` 的 agent 干脆不发 `Origin`（DSH 把缺失的 Origin
当作可信），cookie 才是它的凭证。

### 但改写不能无条件做：先查浏览器的 Origin

改写 Origin 并丢掉 `Sec-Fetch-Site`，等于**把 DSH 自己的 CSRF 围栏关掉**，只剩控制台
cookie 的 `SameSite=Lax`。而 `Lax` 在这里不够：同一块板上别的端口
（比如 `http://<板子>:8080/`）属于 **same-site**，它的 `fetch` 会带上控制台 cookie；
能说明"请求不是控制台页面发出的"的只剩 `Origin`。没有这道检查，那样一个页面可以
打开 DSH 的 WebSocket 去驱动它的 shell 工具。

所以对 `origin_is_host` 的 agent，在改写**之前**先比一次：

- 请求带 `Origin`，且 authority ≠ 请求自己的 `Host` → **403**，不发给上游；
- 请求不带 `Origin` → 放行。同源 `GET`/导航本来就不带（浏览器行为），`curl`
  也不带；拒掉它们会把页面给所有人弄坏，而攻击需要"另一个页面"才能成立；
- `Origin: null` / 解析不出来 → 当跨站处理。控制台自己的页面产生不了这种值。

HTTP 和 WebSocket 都覆盖（WebSocket 更关键：它没有预检，`Sec-Fetch-Site` 也不是
握手能带的头，agent 侧根本看不到）。界面上是 accept-then-close 1008，和已有的
"admin login required" 拒绝同一种形状——升级时回 HTTP 403 对页面来说和"agent 挂了"
没法区分。

## 7. 健康检查

`GET /manifest.webmanifest`。DSH 没有 `/health`：`/` 和 `/api` 全都 401，把 401
当"起来了"会让内嵌页永远白屏。这个 PWA manifest 是公开的（浏览器登录前就要取），
而且只在插件树 settle 之后才 200。实测冷启动约 6 秒（loaded 板子更慢）。

启动之后还有一道检查：**日志里必须有带 token 的行**。没有的话监听是通的，但浏览器
永远拿不到 cookie——报为 `last_error` 的警告（不是启动失败，进程确实在跑）。

## 8. 重置、同步与卸载

- **重置**：清 `config/ state/ cache/ tmp/`，重新发 key 和 secret
  （`state/launch-url` 一起清掉，这正是 token 该有的生命周期）。
  - **`data/` 里有一份要跨过这次清除**：`profiles/web/cordis.patch.yml` 就是 DSH
    设置页写的那个文件，用户从模型页/插件页做过的修改存在里面。spec 的
    `reset_keep` 让管理器在清 `data/` 之前把它读出来、清完再写回去，
    `write_config` 随后只合并我们管理的那部分。实测：不做这件事时一次重置就把用户
    加的插件和 MCP server 全删了。
  - 其余 `DSH_HOME` 内容（profile manifest、cookie 签名密钥、session 日志）照常
    清掉——那才是"重置"要的（旧 secret 留着只会让 DSH 拿着一份控制台不知道的凭证）。
  - workspace 保留（用户的文件）。
- **同步**：只重写我们管理的行（`llm-pi-ai` 里只换 `providers.cv84x6` 这一个 key），
  用户的行原样保留；key 只从**我们自己那两行**里读回来（不再取文件里第一个
  `Authorization:` —— 文件是共享的，用户自己的 MCP server 也带 Bearer），不会无缘
  无故轮换。
- **卸载**：删整个 `<agent>/` 目录。实测 DSH 没有在目录外留下任何东西（`TMPDIR`
  指到 `<agent>/tmp`，`DSH_HOME` 在 `data/dsh`）。

## 9. 实现位置

| 文件 | 作用 |
|---|---|
| `app/agents/dsh.py` | spec：安装、配置合并、命令行、token 读取/清除、MCP 失败提示、health |
| `app/agents/spec.py` | 新钩子：`origin_is_host`、`upstream_launch_url`（`None` = 无交接）、`runtime_warning`、`public_log`、`redact_from_log`、`forget_launch_url`、`reset_keep`、`identity_encoding`。默认实现 = 另外三个 agent 的行为不变 |
| `app/api/agent_proxy.py` | `_handoff_page`：token 兑换；`_spend_token`：兑换请求不落日志；`_refuse_foreign_origin`：改写前的跨站检查；Origin/Host 按 `origin_is_host` 决定 |
| `app/agents/manager.py` | 注册与排序；每次 launch 前清旧 token；`reset` 支持 `reset_keep`；`status_one` 折入 `runtime_warning`；`logs()` 出口过滤 |
| `tests/test_dsh.py` | spec 层：安装、配置、合并、命令行、token、重启、MCP 提示 |
| `tests/test_agent_proxy_dsh.py` | 代理层：交接、Host/Origin、cookie 收窄、跨站拒绝、日志不落 token |

## 10. 与设计的偏差

1. **配置写在 profile 层而不是 home 层**，理由是 home 层会让 DSH 设置页保存失败
   （见第 2 节）。设计文档里"写 `$DSH_HOME/cordis.patch.yml`（home 级）或 web
   profile 的 patch"两种都允许，这里选了后者的**按行合并**版本。
2. **不新增 `--public-url` / `--trusted-host`**：改用代理改写 Host/Origin 那一种做法。
   理由：`--public-url` 需要一个具体的对外地址，而控制台可能通过任意地址/转发端口
   访问，写死任何一个都会在下一块板子上错；而且它还要配 `--trusted-host`，等于把
   "允许哪些 authority"变成一份永远不完整的列表。代理做法只需一处判断。
3. **思考档位声明为 `off/low/high` 三档**，而不是只给 `off`。pi-ai 要求至少一个
   非 `off` 档位，否则配置校验就报错。
4. **`app` 包在构建机上按目标架构打**，而不是板上 `npm install`：板子离线，且
   npm 解析 300+ 包在两分钟以上（OpenClaw 实测 2 分 13 秒）。
5. **模型路由合并进 DSH 自带的 `llm-pi-ai` 行**，不是新增一行。设计里提的"独立行"
   实测做不到（同插件不能挂两次，见第 2 节）。合并只动 `providers.cv84x6` 一个 key，
   用户在这个行里加的其他 provider 保留。
6. **MCP 行开 `failOnStartupError`**。设计没提这一条；不开的话连不上时完全是静默的
   （DSH 的插件日志不落任何地方），而"静默地没有工具"正是这次要修的。代价是晚起的
   `/mcp` 不再自愈，卡片上因此提示「重启」。
7. **代理在改写 Origin 之前先查跨站**。设计只说"改写 Host/Origin 让校验通过"，
   无条件改写会把 DSH 的 CSRF 围栏关掉；现在只放行 Origin 与请求自身 Host 相同的
   请求，其余 403。
