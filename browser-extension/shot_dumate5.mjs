import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
const probe = await page.evaluate(async () => {
  const panel = document.getElementById('dumate-panel');
  const html = panel.innerHTML;
  return {
    hasReady: html.includes('已就绪'),
    hasDetecting: html.includes('正在检测'),
    htmlSnippet: html.slice(0, 500),
  };
});
console.log(JSON.stringify(probe, null, 2));
await b.close();
