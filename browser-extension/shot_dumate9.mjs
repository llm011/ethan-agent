import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(1000);
  const t0 = Date.now();
  const r = await page.evaluate(async () => {
    const s = performance.now();
    const resp = await fetch('/ui/api/dumate/status');
    await resp.json();
    return Math.round(performance.now() - s);
  });
  console.log(`t=${((Date.now())%100000)}ms fetch=${r}ms`);
}
await b.close();
