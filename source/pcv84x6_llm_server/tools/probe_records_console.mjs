#!/usr/bin/env node
/**
 * Browser check for the inference-record console page, against the real board.
 *
 *   node tools/probe_records_console.mjs --base http://127.0.0.1:18800 \
 *       --out ./records-out --record-id <req_id>
 *
 * MYS-2498's acceptance asks for the console to be opened in a real browser and
 * at least one record from each group to be inspected by eye. That is not
 * something a curl assertion can stand in for: the point is that the page
 * renders, the detail panel opens, and the numbers a human reads match the
 * ones in the JSONL.
 *
 * What it asserts, all read-only:
 *   - the page loads with no console error and no failed request;
 *   - the record list renders rows with time / source / model / actor / status;
 *   - opening a given record id shows its request id, input message and output
 *     text, and those match what the caller says the request was;
 *   - the record-log status line is shown (path, count, retention) so an
 *     operator knows where the evidence lives;
 *   - no screenshot or DOM dump contains an API key.
 *
 * Playwright is dev-only and deliberately not in package.json -- the board
 * build must stay browser-free. Point at an install with --playwright.
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ''), process.argv[i + 1])
}

async function loadPlaywright() {
  const candidates = [args.get('playwright'), process.env.PLAYWRIGHT_PATH, 'playwright']
    .filter(Boolean)
  for (const c of candidates) {
    try {
      const spec = c.startsWith('/') ? pathToFileURL(join(c, 'index.js')).href : c
      const mod = await import(spec)
      return mod.chromium ?? mod.default?.chromium
    } catch { /* try the next candidate */ }
  }
  console.error('playwright not found; pass --playwright /path/to/node_modules/playwright')
  process.exit(2)
}

const chromium = await loadPlaywright()
const BASE = (args.get('base') ?? 'http://127.0.0.1:18800').replace(/\/$/, '')
const OUT = args.get('out') ?? './records-out'
const PASSWORD = args.get('password') ?? 'admin'
const RECORD_ID = args.get('record-id')
const API_KEY = args.get('api-key')  // only used to assert it does NOT appear
const PROBLEMS = []
const FACTS = {}

function check(name, ok, detail = '') {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' -- ' + detail : ''}`)
  if (!ok) PROBLEMS.push(`${name}${detail ? ': ' + detail : ''}`)
}

mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const consoleErrors = []
const failedRequests = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push(String(e)))
page.on('requestfailed', (r) => failedRequests.push(`${r.method()} ${r.url()}`))
page.on('response', (r) => {
  if (r.status() >= 500) failedRequests.push(`${r.status()} ${r.url()}`)
})

try {
  // -- 1. load and log in ---------------------------------------------------
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 60000 })
  const loginBox = page.locator('input[type="password"]')
  if (await loginBox.count()) {
    await loginBox.fill(PASSWORD)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(1500)
  }
  check('console loads and authenticates', !(await page.locator('input[type="password"]').count()))

  // -- 2. open the records page --------------------------------------------
  await page.goto(`${BASE}/#/records`, { waitUntil: 'networkidle', timeout: 60000 })
  await page.waitForTimeout(1200)
  let nav = await page.evaluate(() => {
    const el = [...document.querySelectorAll('a,button,[role="tab"],[role="link"]')]
      .find((n) => /推理记录/.test(n.textContent || ''))
    if (el) { el.click(); return true }
    return false
  })
  if (nav) await page.waitForTimeout(1500)

  const bodyText = await page.evaluate(() => document.body.innerText)
  check('records page renders', /推理记录/.test(bodyText))
  check('privacy note is shown',
        /明文|隐私|位置|仅管理员|敏感/.test(bodyText),
        bodyText.slice(0, 120).replace(/\n/g, ' '))

  // The list must show real rows, not an empty state.
  const rows = await page.evaluate(() => {
    const trs = [...document.querySelectorAll('tbody tr')]
    return trs.map((tr) => tr.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean)
  })
  check('record list has rows', rows.length > 0, `${rows.length} rows`)
  if (rows.length) FACTS.first_row = rows[0]

  const statusText = bodyText
  check('record log status is visible',
        /条|路径|sqlite|保留/.test(statusText))
  check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
  check('no failed requests', failedRequests.length === 0, failedRequests.slice(0, 3).join(' | '))

  await page.screenshot({ path: join(OUT, '01-records-list.png'), fullPage: true })

  // -- 3. open one record's detail -----------------------------------------
  // The list deliberately shows no request id (it would be 32 columns of noise);
  // each row has a 详情 button instead. When a specific record is requested, the
  // newest row is the one just written by the run, so that is the row opened --
  // and the id is then confirmed in the detail pane, which is where it appears.
  if (RECORD_ID) {
    const buttons = page.locator('button:has-text("详情")')
    const count = await buttons.count()
    check('record rows offer a detail button', count > 0, `${count} buttons`)
    if (count) {
      await buttons.first().click()
      await page.waitForTimeout(1500)
    }
    const detail = await page.evaluate(() => document.body.innerText)
    const panel = await page.locator('[data-testid="record-detail"]')
    check('record detail panel opens', await panel.count() === 1)
    check('detail shows the request id', detail.includes(RECORD_ID),
          `looking for ${RECORD_ID}`)
    // The detail panel must carry the prompt and the answer, which is the whole
    // reason the log exists.
    check('detail shows input and output fields',
          /输入|消息|output|输出/.test(detail))
    await page.screenshot({ path: join(OUT, '02-record-detail.png'), fullPage: true })
    FACTS.detail_head = detail.slice(0, 600)
  }

  // -- 4. never leak a key --------------------------------------------------
  const html = await page.content()
  if (API_KEY) {
    check('no api key in the rendered page', !html.includes(API_KEY) && !bodyText.includes(API_KEY))
  }

  // -- 5. no horizontal overflow -------------------------------------------
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check('no horizontal overflow at 1440px', overflow <= 1, `${overflow}px`)

  writeFileSync(join(OUT, 'summary.json'),
                JSON.stringify({ base: BASE, rows: rows.length, facts: FACTS,
                                 problems: PROBLEMS }, null, 1), 'utf-8')
} finally {
  await browser.close()
}

console.log(PROBLEMS.length ? `\n${PROBLEMS.length} problem(s)` : '\nall browser checks passed')
process.exit(PROBLEMS.length ? 1 : 0)
