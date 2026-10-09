import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
const st = await page.evaluate(() => {
  const s = DUMATE_STATE.status;
  return {
    statusIsNull: s === null,
    statusUndefined: s === undefined,
    hasReadyField: s ? ('ready' in s) : 'n/a',
    readyValue: s ? s.ready : 'n/a',
    keys: s ? Object.keys(s).slice(0,8) : 'n/a',
  };
});
console.log(JSON.stringify(st, null, 2));
await b.close();
