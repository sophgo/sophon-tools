#!/usr/bin/env node
/**
 * Browser acceptance for the console, against a running (mock) server.
 *
 *   node web/acceptance/ui_check.mjs --base http://127.0.0.1:8791 --out ./acceptance-out
 *
 * It does what a reviewer would do by hand and asserts the things the redesign
 * is supposed to guarantee:
 *   - 1440x1000 and a narrow viewport: no horizontal overflow, no console errors
 *   - day/night palettes both render, the choice survives a reload
 *   - the docs table of contents jumps to a section and marks it current
 *   - the chat workspace lays its parts out in order and locks send while busy
 *   - every chart has real axes and a hover readout with a value and a unit
 * Screenshots for each checkpoint land in --out.
 *
 * Playwright is a dev-only dependency of this script; the board never runs it,
 * and it is deliberately NOT in package.json -- `scripts/build_web.sh` runs a
 * plain `npm install` when node_modules is missing, and that must stay a
 * browser-free build on an offline machine. Install it once where you run the
 * check:
 *
 *   npm install --no-save playwright && npx playwright install chromium
 *
 * If it lives somewhere else, point at it:
 *
 *   node web/acceptance/ui_check.mjs --playwright /path/to/node_modules/playwright
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ''), process.argv[i + 1])
}

async function loadPlaywright() {
  const candidates = [
    args.get('playwright'),
    process.env.PLAYWRIGHT_PATH,
    'playwright',
  ].filter(Boolean)
  for (const c of candidates) {
    try {
      const spec = c.startsWith('/') ? pathToFileURL(join(c, 'index.js')).href : c
      const mod = await import(spec)
      return mod.chromium ?? mod.default?.chromium
    } catch { /* try the next candidate */ }
  }
  console.error(
    'playwright not found. Install it where this script runs:\n' +
    '  npm install --no-save playwright && npx playwright install chromium\n' +
    'or pass --playwright /path/to/node_modules/playwright')
  process.exit(2)
}

const chromium = await loadPlaywright()

const BASE = args.get('base') ?? 'http://127.0.0.1:8791'
const OUT = args.get('out') ?? './acceptance-out'
const PASSWORD = args.get('password') ?? 'admin'
mkdirSync(OUT, { recursive: true })

// A pinned browser build is convenient when the machine already has one that
// does not match this Playwright release. Unset means "use Playwright's own".
const executablePath = args.get('chrome') ?? process.env.CHROME_PATH ?? undefined

const results = []
let failed = 0
function check(name, ok, detail = '') {
  results.push({ name, ok, detail })
  if (!ok) failed++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

const browser = await chromium.launch({ executablePath })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await ctx.newPage()

const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push(String(e)))

async function shot(name) {
  await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: false })
}

/** Smooth scrolling takes as long as the distance needs -- the docs page is
 *  several screens tall -- so wait for scrollY to stop moving rather than
 *  guessing a delay. Sampling mid-flight would judge the highlight against a
 *  heading the page has not reached yet. */
async function settleScroll(p = page, timeout = 5000) {
  await p.evaluate(async (ms) => {
    const t0 = performance.now()
    let last = window.scrollY
    let still = 0
    while (performance.now() - t0 < ms) {
      await new Promise((r) => setTimeout(r, 50))
      if (Math.abs(window.scrollY - last) < 1) {
        if (++still >= 4) return
      } else {
        still = 0
        last = window.scrollY
      }
    }
  }, timeout)
}

async function noOverflow(label) {
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  check(`${label}: 无横向溢出`, m.scroll <= m.client + 1, `${m.scroll} <= ${m.client}`)
}

// -- login ------------------------------------------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.fill('[data-testid="login-password"]', PASSWORD)
await page.click('[data-testid="login-submit"]')
await page.waitForSelector('[data-testid="nav"]')
check('登录成功进入控制台', await page.isVisible('[data-testid="nav"]'))

// Load both models so the playground and overview have something to show.
const loaded = await page.evaluate(async () => {
  const r = await fetch('/api/models')
  const j = await r.json()
  const out = []
  for (const m of j.models) {
    const resp = await fetch(`/api/models/${encodeURIComponent(m.id)}/load`, { method: 'POST' })
    out.push(`${m.id}:${resp.status}`)
  }
  return out
})
check('模型加载接口返回 200', loaded.every((s) => s.endsWith(':200')), loaded.join(', '))

// -- overview + charts ------------------------------------------------------
await page.waitForTimeout(2600) // one stats poll, so the CPU series has 2 points
await page.screenshot({ path: join(OUT, '01-overview-light.png'), fullPage: true })
check('总览：CPU 图表存在', await page.isVisible('[data-testid="chart-cpu"]'))
check('总览：推理速度图表存在', await page.isVisible('[data-testid="chart-tps-svg"]'))

// Axes: ticks on both axes, plus the two axis captions.
const axes = await page.evaluate(() => {
  const svg = document.querySelector('[data-testid="chart-tps-svg"]')
  if (!svg) return null
  const texts = [...svg.querySelectorAll('text')].map((t) => t.textContent.trim())
  const grid = svg.querySelectorAll('.chart-grid').length
  const axisLines = svg.querySelectorAll('.chart-axis').length
  return { texts, grid, axisLines, label: svg.getAttribute('aria-label') }
})
check('推理速度图表：有纵轴刻度', axes && axes.grid >= 2, axes ? `${axes.grid} 条网格` : 'no svg')
check('推理速度图表：有坐标轴线', axes && axes.axisLines >= 2, `${axes?.axisLines}`)
check('推理速度图表：纵轴单位 token/s', axes && axes.texts.includes('token/s'),
      axes ? axes.texts.join('|') : '')
check('推理速度图表：横轴为时间', axes && axes.texts.some((t) => /^\d\d:\d\d:\d\d$/.test(t)),
      axes ? axes.texts.join('|') : '')
check('推理速度图表：有可访问描述', !!axes?.label && axes.label.includes('token/s'), axes?.label)

// Tick sanity: the y labels must be numbers, strictly increasing, deduplicated,
// and anchored at 0 -- the three ways an axis quietly lies.
const yTicks = await page.evaluate(() => {
  const svg = document.querySelector('[data-testid="chart-tps-svg"]')
  return [...svg.querySelectorAll('text.chart-tick')]
    .filter((t) => t.getAttribute('text-anchor') === 'end')
    .map((t) => Number(t.textContent))
})
const increasing = yTicks.every((v, i) => i === 0 || v > yTicks[i - 1])
check('推理速度图表：纵轴刻度递增且不重复',
      yTicks.length >= 2 && increasing && new Set(yTicks).size === yTicks.length,
      yTicks.join(','))
check('推理速度图表：纵轴从 0 起', yTicks[0] === 0, String(yTicks[0]))

// Hover readout: move onto the middle of the plot and read the tooltip.
const box = await page.locator('[data-testid="chart-tps-svg"]').boundingBox()
await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.5)
await page.waitForTimeout(150)
const tip = await page.locator('[data-testid="chart-tps-tip"]').textContent().catch(() => null)
check('推理速度图表：悬浮显示具体数值', !!tip && /token\/s/.test(tip) && /\d/.test(tip), tip ?? 'no tooltip')
await page.screenshot({ path: join(OUT, '02-overview-hover.png') })

// Same for the CPU chart.
const cpuBox = await page.locator('[data-testid="chart-cpu-svg"]').boundingBox()
await page.mouse.move(cpuBox.x + cpuBox.width * 0.6, cpuBox.y + cpuBox.height * 0.5)
await page.waitForTimeout(150)
const cpuTip = await page.locator('[data-testid="chart-cpu-tip"]').textContent().catch(() => null)
check('CPU 图表：悬浮显示具体数值', !!cpuTip && /%/.test(cpuTip), cpuTip ?? 'no tooltip')

await noOverflow('总览 1440')

// -- theme ------------------------------------------------------------------
await page.click('[data-testid="theme-dark"]')
await page.waitForTimeout(120)
const darkAttr = await page.getAttribute('html', 'data-theme')
const darkBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
await page.screenshot({ path: join(OUT, '03-overview-dark.png'), fullPage: true })
check('夜间主题切换生效', darkAttr === 'dark', `data-theme=${darkAttr}`)

await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('[data-testid="nav"]')
const afterReload = await page.getAttribute('html', 'data-theme')
const bgAfterReload = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
check('夜间主题在刷新后保留', afterReload === 'dark' && bgAfterReload === darkBg,
      `${afterReload} / ${bgAfterReload}`)
// Still logged in: the theme switch itself must not drop the session.
check('切换主题不丢登录', await page.isVisible('[data-testid="nav"]'))

await page.click('[data-testid="theme-light"]')
await page.waitForTimeout(120)
check('白天主题切回生效', (await page.getAttribute('html', 'data-theme')) === 'light')

// -- docs -------------------------------------------------------------------
await page.click('[data-testid="nav-docs"]')
await page.waitForSelector('[data-testid="docs-toc"]')
await page.screenshot({ path: join(OUT, '04-docs-light.png'), fullPage: true })
check('文档：浮动目录存在', await page.isVisible('[data-testid="docs-toc"]'))

// The section list is the page's own content, not a fixed number: pinning it to
// a literal made this check fail the moment a section was added (it said 7
// while the page shipped 8), which trains a reader to ignore the failure. What
// matters is that every heading on the page has an entry, in the same order.
const tocAudit = await page.evaluate(() => {
  const links = [...document.querySelectorAll('[data-testid^="toc-"]')];
  const heads = [...document.querySelectorAll('.docs h2[id]')];
  return {
    links: links.map((a) => a.textContent.trim()),
    heads: heads.map((h) => h.textContent.trim()),
    missing: heads
      .filter((h) => !links.some((a) => a.textContent.trim() === h.textContent.trim()))
      .map((h) => h.textContent.trim()),
  };
});
check('文档：目录与页面章节一一对应',
      tocAudit.links.length === tocAudit.heads.length && tocAudit.missing.length === 0,
      `${tocAudit.links.length} 目录项 / ${tocAudit.heads.length} 个章节`
      + (tocAudit.missing.length ? `，缺 ${tocAudit.missing.join('、')}` : ''))

await page.click('[data-testid="toc-limits"]')
await settleScroll()
const limitTop = await page.evaluate(() => {
  const el = document.getElementById('limits')
  return el ? el.getBoundingClientRect().top : null
})
check('文档：点目录跳到「故障与限制」', limitTop !== null && limitTop >= 0 && limitTop < 200,
      `top=${limitTop?.toFixed(0)}`)
const activeToc = await page.evaluate(() => {
  const a = document.querySelector('[data-testid="docs-toc"] a.active')
  return a?.textContent?.trim() ?? null
})
check('文档：目录高亮当前章节', activeToc === '故障与限制', activeToc ?? 'none')
await page.screenshot({ path: join(OUT, '05-docs-toc-jump.png') })

const docsText = await page.locator('.docs').innerText()
check('文档：保留了已知边界', /采样参数不生效/.test(docsText) && /NPU 故障/.test(docsText))
check('文档：删除了逐版本流水账', !/v0\.5\.0 在 CV84X6 上实测|版本历程/.test(docsText))

await page.click('[data-testid="theme-dark"]')
await page.waitForTimeout(120)
await page.screenshot({ path: join(OUT, '06-docs-dark.png'), fullPage: true })
await page.click('[data-testid="theme-light"]')

// -- playground -------------------------------------------------------------
await page.click('[data-testid="nav-playground"]')
await page.waitForSelector('[data-testid="chat-log"]')
await page.fill('[data-testid="chat-input"]', '用一句话说明这块板子能做什么')
await page.screenshot({ path: join(OUT, '07-playground-empty.png') })
check('对话：发送按钮在有输入后可用',
      await page.isEnabled('[data-testid="chat-send"]'))

await page.click('[data-testid="chat-send"]')
// While streaming, send must be gone and stop must be offered.
await page.waitForSelector('[data-testid="chat-stop"]', { timeout: 5000 })
check('对话：生成中显示停止按钮', await page.isVisible('[data-testid="chat-stop"]'))
check('对话：生成中发送按钮被移除', (await page.locator('[data-testid="chat-send"]').count()) === 0)
await page.screenshot({ path: join(OUT, '08-playground-streaming.png') })

await page.waitForSelector('[data-testid="chat-send"]', { timeout: 90000 })
const answer = await page.locator('[data-testid="chat-msg-assistant"] .msg-body').last().innerText()
check('对话：收到模型回答', answer.trim().length > 0, answer.slice(0, 60))
const meta = await page.locator('[data-testid="chat-msg-assistant"] .meta').last().innerText()
check('对话：显示速度与缓存信息', /tok\/s/.test(meta) && /缓存/.test(meta), meta)
await page.screenshot({ path: join(OUT, '09-playground-answer.png'), fullPage: true })

// Layout: input sits below the transcript, actions below the input.
const layout = await page.evaluate(() => {
  const r = (s) => document.querySelector(s)?.getBoundingClientRect()
  const log = r('[data-testid="chat-log"]')
  const input = r('[data-testid="chat-input"]')
  const send = r('[data-testid="chat-send"]')
  const tb = r('[data-testid="playground-toolbar"]')
  return {
    logBottom: log?.bottom, inputTop: input?.top, inputBottom: input?.bottom,
    sendTop: send?.top, toolbarBottom: tb?.bottom,
  }
})
check('对话：工具栏在消息流之上',
      layout.toolbarBottom <= layout.logBottom + 1, `${layout.toolbarBottom} <= ${layout.logBottom}`)
check('对话：输入区在消息流之下',
      layout.inputTop >= layout.logBottom - 1, `${layout.inputTop} >= ${layout.logBottom}`)
check('对话：发送按钮在输入框之下',
      layout.sendTop >= layout.inputBottom - 1, `${layout.sendTop} >= ${layout.inputBottom}`)

await noOverflow('对话 1440')

// -- narrow viewport --------------------------------------------------------
const narrow = await ctx.newPage()
await narrow.setViewportSize({ width: 390, height: 844 })
const narrowErrors = []
narrow.on('pageerror', (e) => narrowErrors.push(String(e)))
for (const page_ of ['overview', 'docs', 'playground']) {
  await narrow.goto(BASE, { waitUntil: 'networkidle' })
  await narrow.click(`[data-testid="nav-${page_}"]`)
  await narrow.waitForTimeout(900)
  await narrow.screenshot({ path: join(OUT, `10-narrow-${page_}.png`), fullPage: false })
  const m = await narrow.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  check(`窄屏 ${page_}: 无横向溢出`, m.scroll <= m.client + 1, `${m.scroll} <= ${m.client}`)
}
check('窄屏：无脚本异常', narrowErrors.length === 0, narrowErrors.join('; '))

// -- console errors ---------------------------------------------------------
check('页面无 console 错误', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

await browser.close()

const summary = {
  base: BASE,
  ran_at: new Date().toISOString(),
  passed: results.filter((r) => r.ok).length,
  failed,
  results,
}
writeFileSync(join(OUT, 'results.json'), JSON.stringify(summary, null, 2))
console.log(`\n${summary.passed} passed, ${failed} failed — screenshots in ${OUT}`)
process.exit(failed === 0 ? 0 : 1)
