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
  // 两个子框架：用来钉住「一次按键只在有焦点的那一层开一个面板」。
  // 脚本注入到每个框架，如果切换消息被每层都执行了，这里会开出 3 个面板。
  '/multi': `<!doctype html><html><body><p id="p">outer</p>
    <iframe id="f1" src="/inner1" width="180" height="60"></iframe>
    <iframe id="f2" src="/inner2" width="180" height="60"></iframe></body></html>`,
  '/inner1': '<!doctype html><html><body><input id="iq"><p>one</p></body></html>',
  '/inner2': '<!doctype html><html><body><input id="iq2"><p>two</p></body></html>',
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

  /**
   * 数一遍**所有框架**里各开了几个面板。
   *
   * 不能用「找到一个就 return true」：脚本会注入到每个框架，一次按键如果在每层都
   * 开了一个面板，只查「有没有」是查不出来的（顶层那个总会命中），而这正是最要命
   * 的那种失败——用户看到顶层面板、输入却进了 iframe 里被裁掉的那个。所以按框架
   * 计数，正常结果必须**恰好是 1**。
   */
  async function countPanels() {
    const per = [];
    for (const fr of page.frames()) {
      try {
        per.push({ url: fr.url().slice(-6), n: await fr.locator('#__ethan_tab_palette').count() });
      } catch { /* 框架已销毁 */ }
    }
    return per;
  }

  async function openPanelReported() {
    const per = await countPanels();
    const total = per.reduce((a, x) => a + x.n, 0);
    if (total > 1) {
      log(`   !! 一次按键开了 ${total} 个面板: ${per.map(x => x.url + ':' + x.n).join(' ')}`);
    }
    return { opened: total === 1, total };
  }

  /** 用例模板：先关掉可能残留的面板，再按快捷键。 */
  async function runCase(name, url, prep, keys = 'Meta+Shift+K') {
    await page.goto(url, { timeout: TIMEOUT });
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(150);
    const inj = await inject();
    try { await prep(); } catch (e) { /* 焦点准备失败也继续 */ }
    let opened = false, note = '', panels = 0;
    if (!inj.startsWith('ok')) {
      note = 'inject failed';
    } else {
      try {
        await page.keyboard.press(keys, { timeout: 6000 });
        await page.waitForTimeout(250);
        const r = await openPanelReported();
        opened = r.opened;
        panels = r.total;
        if (r.total > 1) note = `multi-frame:${r.total}`;
      } catch (e) { note = 'press:' + String(e).slice(0, 60); }
    }
    log(`${name.padEnd(34)} inject=${inj.padEnd(6)} opened=${opened} panels=${panels} ${note}`);
    results.push({ name, inj, opened: String(opened), panels: String(panels), note });
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

  // 9. 多框架页面：一次按键必须**只**开一个面板。
  //    注入是 allFrames + 消息不带 frameId，所以每层都会收到 toggle；如果每层都
  //    自己开一个，用户会看到顶层那个、而输入进了 iframe 里被裁掉的那个。
  //    countPanels 会数出总数，runCase 要求它恰好为 1。
  await runCase('多 iframe 焦点在外层', `${BASE}/multi`, async () => { await page.locator('#p').click({ timeout: 4000 }); });
  await runCase('多 iframe 焦点在第一个 iframe', `${BASE}/multi`, async () => {
    const f = page.frames().find(fr => fr.url().includes('/inner1'));
    if (f) await f.locator('#iq').click({ timeout: 4000 });
  });
  await runCase('多 iframe 焦点在第二个 iframe', `${BASE}/multi`, async () => {
    const f = page.frames().find(fr => fr.url().includes('/inner2'));
    if (f) await f.locator('#iq2').click({ timeout: 4000 });
  });

  log('--- summary ---');
  const failed = results.filter(r => r.opened !== 'true');
  log(`total=${results.length} failed=${failed.length}`);
  for (const f of failed) log(`  FAIL: ${f.name} (inject=${f.inj} ${f.note})`);
} finally {
  await ctx.close().catch(() => {});
  await new Promise(r => srv.close(r));
}
