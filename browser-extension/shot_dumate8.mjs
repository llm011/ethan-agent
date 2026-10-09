import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
const h1 = await page.evaluate(() => document.getElementById('dumate-panel').innerHTML.length);
await page.waitForTimeout(32000);  // 等一轮 30s 轮询
const st = await page.evaluate(() => ({
  ready: document.getElementById('dumate-panel').innerHTML.includes('已就绪'),
  htmlLen: document.getElementById('dumate-panel').innerHTML.length,
}));
console.log('before:', h1, 'after 30s:', JSON.stringify(st));
await b.close();
