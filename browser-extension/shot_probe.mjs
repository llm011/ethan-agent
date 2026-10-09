import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(6000);
const st = await page.evaluate(() => ({
  statusReady: DUMATE_STATE.status && DUMATE_STATE.status.ready,
  statusFetched: !!DUMATE_STATE.status,
  panelShowsReady: document.getElementById('dumate-panel').innerHTML.includes('已就绪'),
  panelShowsDetect: document.getElementById('dumate-panel').innerHTML.includes('正在检测'),
  htmlTail: document.getElementById('dumate-panel').innerHTML.slice(-400),
}));
console.log(JSON.stringify(st, null, 2));
await b.close();
