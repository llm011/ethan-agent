import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
for (let i = 0; i < 15; i++) {
  await page.waitForTimeout(1000);
  const ready = await page.evaluate(() => document.getElementById('dumate-panel').innerHTML.includes('已就绪'));
  if (ready) { console.log(`READY at ~${i+1}s`); break; }
  if (i === 14) console.log('NOT READY after 15s');
}
console.log('PANEL:', (await page.locator('#dumate-panel').innerText()).replace(/\n/g, ' | ').slice(0, 320));
await page.locator('#dumate-panel').screenshot({ path: '/tmp/dumate-final3.png' });
await b.close();
