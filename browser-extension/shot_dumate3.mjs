import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
page.on('pageerror', e => console.log('PAGEERR:', String(e).slice(0,200)));
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(6000);
console.log('PANEL:', (await page.locator('#dumate-panel').innerText()).replace(/\n/g, ' | '));
await b.close();
