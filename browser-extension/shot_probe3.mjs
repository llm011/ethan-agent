import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
for (let i = 0; i < 10; i++) {
  await page.waitForTimeout(1000);
  const st = await page.evaluate(() => {
    const s = DUMATE_STATE.status;
    return { ready: s && s.ready, hasHint: !!(s && s.hint), running: s && s.running };
  });
  console.log(i, JSON.stringify(st));
  if (st.ready) break;
}
await b.close();
