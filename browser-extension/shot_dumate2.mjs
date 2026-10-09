import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(4000);
await page.locator('#dumate-panel').screenshot({ path: '/tmp/dumate2-final.png' });
// 模型页：dumate 模型列表
await page.click('[data-tab="models"]');
await page.waitForTimeout(2000);
await page.screenshot({ path: '/tmp/dumate2-models.png', fullPage: false });
await b.close();
