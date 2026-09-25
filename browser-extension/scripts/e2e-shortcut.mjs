// 全量探针：把「快捷键失效」的各种场景一次跑清。
// 每个用例都在真实 Chromium + 真实扩展里跑，每步有超时。
import { chromium } from 'playwright';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';

const EXT = resolve(process.cwd(), 'dist');
const TIMEOUT = 20000;
const log = (...a) => console.log('[full]', ...a);
const results = [];

const pages = {
  '/plain': '<!doctype html><html><body><p id="p">plain</p></body></html>',
  '/input': '<!doctype html><html><body><p id="p">x</p><input id="q" placeholder="search"></body></html>',
  '/textarea': '<!doctype html><html><body><textarea id="t"></textarea></body></html>',
  '/select': '<!doctype html><html><body><select id="s"><option>a</option></select></body></html>',
  '/editable': '<!doctype html><html><body><div id="ed" contenteditable="true">edit</div></body></html>',
  '/input-inside-editable': '<!doctype html><html><body><div contenteditable="true"><input id="q2"></div></body></html>',
  '/shadow': '<!doctype html><html><body><div id="host"></div><script>const s=document.getElementById("host").attachShadow({mode:"open"});s.innerHTML="<input id=\\"sq\\"><p>shadow text</p>";</script></body></html>',
  '/iframe': '<!doctype html><html><body><p id="p">outer</p><iframe id="f" src="/inner"></iframe></body></html>',
  '/inner': '<!doctype html><html><body><input id="iq"><p>inner</p></body></html>',
  '/scrolled': '<!doctype html><html><body style="height:3000px"><p id="p" style="margin-top:2000px">deep</p></body></html>',
};

const srv = createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  res.end(pages[req.url] || pages['/plain']);
});
await new Promise(r => srv.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${srv.address().port}`;

const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'full-')), {
  headless: false,
  args: ['--headless=new', `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});

try {
  let sw = ctx.serviceWorkers()[0];
  if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: TIMEOUT });

  const page = await ctx.newPage();

  async function inject() {
    // 与 background 的真实注入一致：allFrames —— 焦点在 iframe 里时只有那层的
    // content script 收得到 keydown，只注主框架的话 iframe 用例必然是假失败
    return sw.evaluate(async () => {
      const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!t?.id) return 'no-tab';
      try {
        const r = await chrome.scripting.executeScript({
          target: { tabId: t.id, allFrames: true }, files: ['content/tab-palette.js'],
        });
        return 'ok(' + r.length + ')';
      } catch (e) { return 'fail:' + String(e?.message || e); }
    });
  }

  async function openPanelReported() {
    // 面板开在「有焦点的那一层」——焦点在 iframe 里时就开在内层，所以所有框架都要查
    for (const fr of page.frames()) {
      try { if ((await fr.locator('#__ethan_tab_palette').count()) > 0) return true; } catch { /* 框架已销毁 */ }
    }
    return false;
  }

  /** 用例模板：先关掉可能残留的面板，再按快捷键。 */
  async function runCase(name, url, prep, keys = 'Meta+Shift+K') {
    await page.goto(url, { timeout: TIMEOUT });
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(150);
    const inj = await inject();
    try { await prep(); } catch (e) { /* 焦点准备失败也继续 */ }
    let opened = false, note = '';
    if (!inj.startsWith('ok')) {
      note = 'inject failed';
    } else {
      try {
        await page.keyboard.press(keys, { timeout: 6000 });
        await page.waitForTimeout(250);
        opened = await openPanelReported();
      } catch (e) { note = 'press:' + String(e).slice(0, 60); }
    }
    log(`${name.padEnd(34)} inject=${inj.padEnd(6)} opened=${opened} ${note}`);
    results.push({ name, inj, opened: String(opened), note });
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(150);
    return opened;
  }

  // 1. 普通页面
  await runCase('普通页面 body 聚焦', `${BASE}/plain`, async () => { await page.locator('#p').click({ timeout: 4000 }); });

  // 2. 输入框聚焦（核心 bug 场景）
  await runCase('input 聚焦', `${BASE}/input`, async () => { await page.locator('#q').click({ timeout: 4000 }); });

  // 3. textarea 聚焦
  await runCase('textarea 聚焦', `${BASE}/textarea`, async () => { await page.locator('#t').click({ timeout: 4000 }); });

  // 4. select 聚焦
  await runCase('select 聚焦', `${BASE}/select`, async () => { await page.locator('#s').click({ timeout: 4000 }); });

  // 5. contenteditable 聚焦
  await runCase('contenteditable 聚焦', `${BASE}/editable`, async () => { await page.locator('#ed').click({ timeout: 4000 }); });

  // 6. shadow DOM 内的输入框
  await runCase('shadow DOM 内 input 聚焦', `${BASE}/shadow`, async () => {
    await page.locator('#host').evaluate(h => h.shadowRoot.querySelector('#sq').focus());
  });

  // 7. iframe 内输入框聚焦
  await runCase('iframe 内 input 聚焦', `${BASE}/iframe`, async () => {
    const f = page.frames().find(fr => fr.url().includes('/inner'));
    if (f) await f.locator('#iq').click({ timeout: 4000 });
  });

  // 8. 页面滚动后
  await runCase('页面滚动后 body 聚焦', `${BASE}/scrolled`, async () => {
    await page.mouse.wheel(0, 1500);
    await page.waitForTimeout(200);
    await page.locator('#p').click({ timeout: 4000 });
  });

  log('--- summary ---');
  const failed = results.filter(r => r.opened !== 'true');
  log(`total=${results.length} failed=${failed.length}`);
  for (const f of failed) log(`  FAIL: ${f.name} (inject=${f.inj} ${f.note})`);
} finally {
  await ctx.close().catch(() => {});
  await new Promise(r => srv.close(r));
}
