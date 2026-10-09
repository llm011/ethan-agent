import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
const st = await page.evaluate(async () => {
  try {
    const r = await fetch('/ui/api/dumate/status');
    const j = await r.json();
    return {ok: true, ready: j.ready, hasSt: true};
  } catch (e) { return {ok: false, err: String(e)}; }
});
console.log('BROWSER FETCH:', JSON.stringify(st));
await b.close();
