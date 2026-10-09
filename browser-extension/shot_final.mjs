import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(6000);
console.log('PANEL:', (await page.locator('#dumate-panel').innerText()).replace(/\n/g, ' | ').slice(0, 300));
await page.locator('#dumate-panel').screenshot({ path: '/tmp/dumate-final.png' });
// 折叠态模型页（窄视口）复测样式修复
await page.setViewportSize({ width: 500, height: 900 });
await page.click('[data-tab="models"]');
await page.waitForTimeout(1500);
await page.screenshot({ path: '/tmp/models-narrow.png' });
await b.close();
