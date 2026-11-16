# 控制台浏览器验收

给评审用的可复现步骤：不碰 NPU、不访问 10.42，用仓库自带的 mock 后端把控制台真正跑起来，
再用 headless Chromium 检查「布局、主题、目录、对话、图表」这些肉眼才看得出的东西。

## 1. 起 mock 服务

```bash
cd <仓库根>
python3 web/acceptance/mock_server.py --port 8802
```

它做三件事：

- 在 `$TMPDIR/cv84x6-ui-acceptance/` 建两个假模型目录（32k / 128k），不下载任何东西；
- 预置 60 条 decode 速度历史和一个用量初始值，让图表和表格不是空的；
- 用**真实的** `app.main.create_app` 起服务（同一套路由、鉴权、SSE），只把引擎换成
  `app/engine/mock.py`，并给每 token 加 45 ms 延迟，好让流式和速度曲线看得见。

打开 `http://127.0.0.1:8802`，密码 `admin`（首次启动的默认值）。`--root DIR` 可以换数据目录，
`--decode-delay-ms 0` 可以让 mock 回答瞬间结束。

## 2. 跑浏览器检查

Playwright **不在** `package.json` 里：`scripts/build_web.sh` 在 `node_modules` 缺失时会跑
`npm install`，而板子的构建过程不应该顺带拉一个浏览器。按需装一次：

```bash
npm install --no-save playwright
npx playwright install chromium

node web/acceptance/ui_check.mjs --base http://127.0.0.1:8802 --out ./acceptance-out
```

机器上已有别的 Playwright/Chromium 时可以直接指过去，不必重装：

```bash
node web/acceptance/ui_check.mjs --base http://127.0.0.1:8802 --out ./acceptance-out \
  --playwright /path/to/node_modules/playwright \
  --chrome /path/to/chrome-headless-shell
```

退出码 0 表示全过；`acceptance-out/results.json` 是每条检查的结构化结果，
`acceptance-out/*.png` 是对应时刻的截图。

### 检查了什么

| 组 | 检查 |
|---|---|
| 登录 | 默认密码进控制台 |
| 总览 | 两张图都存在；纵轴有刻度、递增、不重复、从 0 起；纵轴单位是 `token/s` / `%`；横轴刻度是真实时钟时间；SVG 有 `aria-label` 描述；鼠标移上去浮层给出「时间 + 数值 + 单位」 |
| 主题 | 切到夜间 → `<html data-theme="dark">` 且背景色改变；刷新后仍为夜间；切换不丢登录；切回白天生效 |
| 文档 | 浮动目录 7 项；点「故障与限制」后该标题落在顶部；目录把当前章节标为选中；`采样参数不生效`/`NPU 故障` 等已知边界仍在，逐版本流水账已删除 |
| 对话 | 输入后发送可用；生成中「发送」消失、「停止生成」出现；回答下方显示 token/速度/缓存/首字；工具栏在消息流之上、输入区在其下、发送按钮在输入框之下 |
| 尺寸 | 1440×1000 与 390×844 下无横向溢出；窄屏无脚本异常 |
| 全局 | 整轮无 console 错误、无未捕获异常 |

## 3. 手工看一眼

截图之外，值得手动确认的两点：

- **主题不闪**：切到夜间后刷新页面，首屏就是夜间（主题在 React 渲染前由
  `src/components/theme.ts` 写到 `<html>`，不存在先白后黑的闪烁）。
- **窄屏目录**：宽度小于 1080px 时目录变成折叠条，收起时不占版面，点击跳转后自动收起。

## 说明

- 这个目录只服务于人工/CI 验收，不参与打包：`scripts/package.sh` 只取 `web/dist`。
- 没有 NPU 时「TPU 频率」卡片显示 NPU 利用率并写明「未取到实时频率」；
  真实频率由后端 `monitor.py` 提供，这里只负责不把 bm-smi 的 `tpuc`（利用率）当成频率显示。

## 4. 视觉规范验收（MYS-2456 起）

上面三节是"功能没坏"的验收；视觉规范另有三件工具，都不碰 NPU。

```bash
# 起一次 mock（同 §1），然后：

# a) 全页截图矩阵：7 个页面 × 3 个宽度（1440/1024/390）× 昼/夜
python3 web/acceptance/shots.py --out ./shots
#   顺便断言无 console 错误、无横向溢出；有问题退出码为 1。

# b) 只读真实设备：用本地新构建，数据取自板卡
python3 tools/probe_console_readonly_proxy.py --upstream http://10.42.0.242:8000 --port 8899
#   只转发 GET/HEAD，唯一放行的写操作是 POST /api/login；
#   在页面上点"加载/启动/保存"会被拦成 405，不会到达板卡。

# c) 对比度：在真实 Chromium 里读出每一对"文字色 × 实际背景色"，
#    用 skill 自带的 WCAG 实现判定（4.5:1，大字号 3:1）
python3 web/acceptance/contrast_audit.py                     # 未加载模型
python3 web/acceptance/contrast_audit.py --load              # 加载 mock 模型
#   退出码 1 表示有配对不达标，可直接当门禁用。

# d) 只有在"跑起来才会出现"的状态（在线胶囊、流式对话、新密钥、已保存设置）
python3 web/acceptance/states_shots.py --out ./states

# e) 下载中的模型：自带服务并预置一个进行中的 dfss 任务，检查卡片显示「下载中」、
#    加载/删除禁用、目录不再显示「已在磁盘」，任务结束后无需刷新即解锁
python3 web/acceptance/download_lock_shots.py --out ./dl-shots

# f) 按模型类型分的页签与测试面板（MYS-2599）：自带服务，加载每种类型各一个 mock 模型；
#    桌面/手机 × 白天/夜间下检查五个页签的卡片/目录/已加载数、空页签、相似度矩阵（含逐格对比度）、
#    重排序、语音分段时间轴、OCR 检测框、错误与长文本状态；OCR-VL 用拦截的接口驱动
python3 web/acceptance/kind_panels_shots.py --out ./kind-shots
```

`audit_metrics.py` 是诊断用：把渲染后的字号/字重/文字色种类、最宽正文块（按中英文混排折算
字符数）、卡内标题外边距、横向溢出元素一次列出来，用来看规范有没有漂。

这些目录（`shots/`、`states/`、`dl-shots/`、`kind-shots/`、`acceptance-out/`）都在 `.gitignore` 里，属于每次运行的证据，
不随包发布。
