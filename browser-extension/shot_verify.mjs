import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
for (let i = 0; i < 10; i++) {
  await page.waitForTimeout(1000);
  if (await page.evaluate(() => document.getElementById('dumate-panel').innerHTML.includes('已就绪'))) { console.log(`READY ~${i+1}s`); break; }
  if (i === 9) console.log('NOT READY');
}
await page.waitForTimeout(2000);
console.log('PANEL:', (await page.locator('#dumate-panel').innerText()).replace(/\n/g, ' | ').slice(0, 260));
await page.locator('#dumate-panel').screenshot({ path: '/tmp/dumate-verify.png' });
await b.close();
