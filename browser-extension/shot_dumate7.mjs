import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/Users/jsongo/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell' });
const page = await b.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://127.0.0.1:8899/ui');
await page.click('[data-tab="benefits"]');
await page.waitForTimeout(3000);
const st = await page.evaluate(() => ({
  typeofLoadDumateStatus: typeof loadDumateStatus,
  typeofRenderDumatePanel: typeof renderDumatePanel,
  typeofApi: typeof api,
  typeofDumateState: typeof DUMATE_STATE,
  stateStatus: typeof DUMATE_STATE !== 'undefined' ? DUMATE_STATE.status : 'N/A',
  typeofRenderBenefits: typeof renderBenefits,
  benefitsLoaded: typeof BENEFITS !== 'undefined' && !!BENEFITS,
}));
console.log(JSON.stringify(st, null, 2));
await b.close();
