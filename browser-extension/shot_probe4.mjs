import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
page.on('pageerror', e => console.log('PAGEERR:', String(e).slice(0,200)));
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(2000);
for (let i = 0; i < 12; i++) {
  await page.waitForTimeout(1000);
  const st = await page.evaluate(() => ({
    t: Date.now() % 100000,
    statusReady: DUMATE_STATE.status ? DUMATE_STATE.status.ready : 'null',
    statusHint: DUMATE_STATE.status && DUMATE_STATE.status.hint,
    syncCalls: globalThis.__syncCalls || 'n/a',
    panelReady: document.getElementById('dumate-panel').innerHTML.includes('已就绪'),
    panelDetect: document.getElementById('dumate-panel').innerHTML.includes('正在检测'),
  }));
  console.log(i, JSON.stringify(st));
}
await b.close();
