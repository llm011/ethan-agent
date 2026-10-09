import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
// 轮询面板 innerHTML，每 500ms 看一次，最多 12s
for (let i = 0; i < 24; i++) {
  await page.waitForTimeout(500);
  const st = await page.evaluate(() => {
    const h = document.getElementById('dumate-panel').innerHTML;
    return { ready: h.includes('已就绪'), detecting: h.includes('正在检测'), hasLogin: h.includes('已登录'), ts: Date.now() % 100000 };
  });
  console.log(i, JSON.stringify(st));
  if (st.ready) break;
}
await b.close();
