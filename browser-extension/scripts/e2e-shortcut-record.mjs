// 验证 popup 录入的组合键「录什么就触发什么」——尤其是 mac 上按非主修饰键的情况。
import { chromium } from 'playwright';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';

const EXT = resolve(process.cwd(), 'dist');
const TIMEOUT = 15000;
const log = (...a) => console.log('[rec]', ...a);

const srv = createServer((_req, res) => {
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  res.end('<!doctype html><html><body><input id="q"><p id="p">page</p></body></html>');
});
await new Promise(r => srv.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${srv.address().port}`;

const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'rec-')), {
  headless: false,
  args: ['--headless=new', `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});

const results = [];
function check(name, cond, detail = '') {
  results.push({ name, ok: !!cond });
  log(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
}

try {
  let sw = ctx.serviceWorkers()[0];
  if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 20000 });
  const extId = new URL(sw.url()).host;

  const page = await ctx.newPage();
  await page.goto(`${BASE}/plain`, { timeout: TIMEOUT });
  await page.waitForTimeout(400);

  const popup = await ctx.newPage();
  await popup.goto(`chrome-extension://${extId}/popup.html`, { timeout: TIMEOUT });
  await popup.waitForTimeout(500);

  // 在 popup 的录入框里真的按一次 Ctrl+K（mac 上这是「非主修饰键」）
  const input = popup.locator('#paletteShortcut');
  await input.click({ timeout: TIMEOUT });
  await popup.keyboard.down('Control');
  await popup.keyboard.press('k');
  await popup.keyboard.up('Control');
  await popup.waitForTimeout(500);

  const stored = await sw.evaluate(async () => {
    const s = await chrome.storage.local.get(['tabPaletteShortcut']);
    return s.tabPaletteShortcut;
  });
  log('录 Ctrl+K 后 storage =', JSON.stringify(stored));

  check('Mac 上录 Ctrl+K 存为 ctrl+k（不是 mod+k）', stored === 'ctrl+k', `stored=${stored}`);

  // 端到端：注入页面，按 Ctrl+K 应该开面板。
  // 注意必须按 URL 找那个 http 页面 —— popup 自己也是一个 tab，`active: true` 会
  // 命中 popup（chrome-extension://），对它 executeScript 会因权限被拒。
  const pageUrlPrefix = BASE;
  await sw.evaluate(async prefix => {
    const tabs = await chrome.tabs.query({});
    const t = tabs.find(x => (x.url || '').startsWith(prefix));
    if (!t) throw new Error('找不到测试页面 tab');
    await chrome.scripting.executeScript({ target: { tabId: t.id, allFrames: true }, files: ['content/tab-palette.js'] });
  }, pageUrlPrefix);
  await page.bringToFront();
  await page.waitForTimeout(300);
  await page.locator('#q').click({ timeout: TIMEOUT }); // 焦点在输入框里，也要能开
  await page.keyboard.down('Control');
  await page.keyboard.press('k');
  await page.keyboard.up('Control');
  await page.waitForTimeout(400);
  const n = await page.locator('#__ethan_tab_palette').count().catch(() => 0);
  check('录完后按 Ctrl+K（焦点在 input）真的开面板', n === 1, `panels=${n}`);
} finally {
  log('--- summary ---');
  log(`total=${results.length} failed=${results.filter(r => !r.ok).length}`);
  for (const r of results.filter(x => !x.ok)) log('  FAIL: ' + r.name);
  await ctx.close().catch(() => {});
  await new Promise(r => srv.close(r));
}
