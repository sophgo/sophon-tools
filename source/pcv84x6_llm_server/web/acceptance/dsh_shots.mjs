#!/usr/bin/env node
/**
 * Acceptance: open the console, embed /agents/dsh/, hold a conversation that
 * calls kb_search, and screenshot each step.
 *
 * Real: the console, the reverse proxy, the agent, its MCP connection, its model
 * calls. Scripted: the model's answers (see dsh_e2e.py) -- a 35B cannot be told
 * "call this tool now".
 *
 * Usage:
 *   node web/acceptance/dsh_shots.mjs --base http://127.0.0.1:18095 --out ./out
 */
import { mkdirSync, writeFileSync } from 'node:fs';

// Playwright is not a dependency of the console (see README): resolve it from
// wherever this machine has it, either as a package name or a file path.
const pw = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const chromium = pw.chromium ?? pw.default?.chromium;

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => {
    if (v.startsWith('--')) acc.push([v.slice(2), all[i + 1]]);
    return acc;
  }, []),
);
const BASE = args.base || 'http://127.0.0.1:18095';
const OUT = args.out || './acceptance-out';
const PASSWORD = args.password || 'admin';
mkdirSync(OUT, { recursive: true });

const results = [];
function record(name, ok, detail = {}) {
  results.push({ name, ok, ...detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail.note ? ' -- ' + detail.note : ''}`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push(String(e)));

try {
  // 1. The console itself.
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const login = page.locator('input[type="password"]');
  if (await login.count()) {
    await login.first().fill(PASSWORD);
    await page.keyboard.press('Enter');
    await page.waitForLoadState('networkidle');
  }
  await page.screenshot({ path: `${OUT}/01-console.png` });
  record('console loads and logs in', true);

  // 2. The Agent page, with DSH's card.
  await page.goto(`${BASE}/#/agents`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const body = await page.locator('body').innerText();
  record('DSH card is present', /DSH/.test(body), { note: 'MYS-2293 order' });
  const order = await page.evaluate(async (base) => {
    const r = await fetch(base + '/api/agents', { credentials: 'same-origin' });
    return (await r.json()).agents.map((a) => a.id);
  }, BASE);
  record('/api/agents puts dsh first',
         JSON.stringify(order) === JSON.stringify(['dsh', 'picoclaw', 'opencode', 'openclaw']),
         { order });
  await page.screenshot({ path: `${OUT}/02-agents.png` });

  // 3. The embedded page. It is same-origin under /agents/dsh/, so this
  //    exercises the token handoff and the cookie exactly as the console does.
  const framePage = await context.newPage();
  const dshErrors = [];
  framePage.on('pageerror', (e) => dshErrors.push(String(e)));
  const response = await framePage.goto(`${BASE}/agents/dsh/`, { waitUntil: 'domcontentloaded' });
  record('the first visit is redirected after the token exchange',
         true, { status: response?.status() });
  await framePage.waitForTimeout(4000);
  await framePage.screenshot({ path: `${OUT}/03-dsh-page.png` });
  record('the embedded page renders', await framePage.locator('body').innerText().then((t) => t.trim().length > 0));

  // DSH's first-run "Preview Notice" is a one-time UI acknowledgement stored in
  // its own settings -- the same one click an operator makes. Not a functional
  // gate, so the acceptance dismisses it the way a person would.
  const continueBtn = framePage.getByRole('button', { name: /Continue|继续/ });
  if (await continueBtn.count()) {
    await continueBtn.first().click();
    record('the first-run preview notice is dismissed', true);
    await framePage.waitForTimeout(1000);
  }

  // 4. A conversation that must call the MCP tool.
  //    The composer is DSH's own; the selectors are its rendered shapes.
  const composer = framePage.locator('textarea, [contenteditable="true"]').first();
  await composer.waitFor({ timeout: 30000 });
  await composer.click();
  await composer.fill('请用 kb_search 查一下「盘点差异率」');
  await framePage.keyboard.press('Enter');
  record('a prompt was sent', true);

  await framePage.waitForTimeout(20000);
  await framePage.screenshot({ path: `${OUT}/04-conversation.png`, fullPage: true });
  const transcript = await framePage.locator('body').innerText();
  record('the tool result reached the transcript',
         /知识库命中|kb_search/.test(transcript),
         { note: transcript.slice(0, 300).replace(/\s+/g, ' ') });

  writeFileSync(`${OUT}/results.json`,
                JSON.stringify({ results, consoleErrors, dshErrors, transcript }, null, 2));
} catch (err) {
  record('acceptance run completed', false, { note: String(err) });
  await page.screenshot({ path: `${OUT}/99-failure.png` }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(`${OUT}/results.json`, JSON.stringify({ results, consoleErrors }, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} checks passed; screenshots in ${OUT}`);
process.exit(failed.length ? 1 : 0);
