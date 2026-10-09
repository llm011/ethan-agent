import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.waitForTimeout(1500);
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(35000);
const st = await page.evaluate(() => ({
  panelReady: document.getElementById('dumate-panel').innerHTML.includes('已就绪'),
  panelDetect: document.getElementById('dumate-panel').innerHTML.includes('正在检测'),
}));
console.log('after 35s:', JSON.stringify(st));
await b.close();
