import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
for (let i = 0; i < 15; i++) {
  await page.waitForTimeout(1000);
  const st = await page.evaluate(() => ({
    ready: document.getElementById('dumate-panel').innerHTML.includes('已就绪'),
    detect: document.getElementById('dumate-panel').innerHTML.includes('正在检测'),
  }));
  if (st.ready) { console.log(`READY at ~${i+1}s`); break; }
  if (i === 14) console.log('STILL:', JSON.stringify(st));
}
console.log('PANEL:', (await page.locator('#dumate-panel').innerText()).replace(/\n/g, ' | ').slice(0, 300));
await page.locator('#dumate-panel').screenshot({ path: '/tmp/dumate-final2.png' });
await b.close();
