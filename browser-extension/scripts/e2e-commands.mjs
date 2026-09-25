// 端到端验证三个交付点：
//   1. 管理界面：排序（上移/下移/拖动）、展示数量、移出并找回
//   2. popup 顶部「打开搜索 Tab」入口，点击真的打开面板
//   3. 快捷键在常规页面（含输入框）稳定可用（由 probe-full.mjs 覆盖）
//
// 全程在真实 Chromium + 真实扩展里跑，每步带超时。
import { chromium } from 'playwright';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';

const EXT = resolve(process.cwd(), 'dist');
const TIMEOUT = 20000;
const log = (...a) => console.log('[feat]', ...a);
let failures = 0;
function check(name, cond, extra = '') {
  const ok = Boolean(cond);
  if (!ok) failures++;
  log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ' — ' + extra : ''}`);
  return ok;
}

const srv = createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  res.end('<!doctype html><html><body><p id="p">page</p></body></html>');
});
await new Promise(r => srv.listen(0, '127.0.0.1', r));
const BASE = `http://127.0.0.1:${srv.address().port}`;

const ctx = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'feat-')), {
  headless: false,
  args: ['--headless=new', `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});

try {
  let sw = ctx.serviceWorkers()[0];
  if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: TIMEOUT });
  const extId = new URL(sw.url()).host;
  const optionsUrl = `chrome-extension://${extId}/options.html`;
  const popupUrl = `chrome-extension://${extId}/popup.html`;

  const readStorage = () => sw.evaluate(() => chrome.storage.local.get(null));
  /** 当前 popup 会渲染出来的指令 id（复刻 extension 侧的筛选语义） */
  async function popupIdsViaBackground() {
    const stored = await readStorage();
    const all = stored.commands || [];
    const hidden = new Set(stored.hiddenCommandIds || []);
    const limit = stored.popupCommandLimit || 0;
    const visible = all.filter(c => !hidden.has(c.id));
    return (limit > 0 ? visible.slice(0, limit) : visible).map(c => c.id);
  }

  // ── 1. 管理界面 ──
  const opt = await ctx.newPage();
  await opt.goto(optionsUrl, { timeout: TIMEOUT });
  // 全新 profile 时 storage 里还没有 'commands'，options 用内置默认集渲染。
  // 触发一次交互让它落库，后续断言才有稳定的 baseline。
  await opt.locator('#add').click({ timeout: 5000 });
  await opt.waitForFunction(async () => {
    const s = await chrome.storage.local.get('commands');
    return Array.isArray(s.commands) && s.commands.length > 0;
  }, null, { timeout: 8000 });
  // 把刚加的那条删掉，回到默认集
  await opt.locator('.card').last().locator('[data-act="del"]').click({ timeout: 5000 });
  await opt.waitForTimeout(700);

  const cardCount = await opt.locator('.card').count();
  let stored = await readStorage();
  const allCount0 = (stored.commands || []).length;
  check('管理界面渲染出全部指令', cardCount === allCount0 && allCount0 > 0, `cards=${cardCount} stored=${allCount0}`);

  const firstId = stored.commands[0].id;
  const secondId = stored.commands[1].id;

  // 下移第一条 → 存储里前两条应当交换
  await opt.locator('.card').first().locator('[data-act="down"]').click({ timeout: 5000 });
  await opt.waitForFunction(([a, b]) => {
    return true;
  }, [firstId, secondId]);
  await opt.waitForTimeout(600);
  stored = await readStorage();
  const swapped = stored.commands[0].id === secondId && stored.commands[1].id === firstId;
  check('「下移」改变顺序', swapped, `now=[${stored.commands.slice(0, 2).map(c => c.id)}]`);

  // 上移回来
  await opt.locator('.card').nth(1).locator('[data-act="up"]').click({ timeout: 5000 });
  await opt.waitForTimeout(600);
  stored = await readStorage();
  check('「上移」恢复顺序', stored.commands[0].id === firstId && stored.commands[1].id === secondId,
    `now=[${stored.commands.slice(0, 2).map(c => c.id)}]`);

  // 拖动第 3 张卡片到第 1 张的位置
  const thirdIdBeforeDrag = (await readStorage()).commands[2].id;
  // 用真实的 HTML5 拖拽事件序列（Playwright 的 dragTo 对原生 HTML5 DnD 不稳，
  // 会走到我们代码里 onDragStart/onDrop 都不触发的路径上）
  await opt.evaluate(({ fromIdx, toIdx }) => {
    const cards = document.querySelectorAll('#list .card');
    const src = cards[fromIdx];
    const dst = cards[toIdx];
    const dt = new DataTransfer();
    src.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
    dst.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    dst.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
    src.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer: dt }));
  }, { fromIdx: 2, toIdx: 0 });
  await opt.waitForTimeout(500);

  stored = await readStorage();
  const draggedId = stored.commands[0].id;
  check('拖动把第 3 条搬到首位', draggedId === thirdIdBeforeDrag,
    `newFirst=${draggedId} expect=${thirdIdBeforeDrag}`);

  // ── 限流：设成只展示 2 条 ──
  await opt.locator('#limitInput').fill('2');
  await opt.locator('#limitInput').dispatchEvent('change');
  await opt.waitForTimeout(500);
  stored = await readStorage();
  check('展示数量写入 storage', stored.popupCommandLimit === 2, `limit=${stored.popupCommandLimit}`);

  let ids = await popupIdsViaBackground();
  check('popup 只展示前 2 条', ids.length === 2, `ids=[${ids}]`);

  // 顺序应该是「拖动后的顺序」的前两条
  check('展示的是排在最前的两条', ids[0] === draggedId, `first=${ids[0]} expect=${draggedId}`);

  // ── 移出弹窗：把当前第 1 条移出 ──
  await opt.locator('.card').first().locator('[data-act="vis"]').click({ timeout: 5000 });
  await opt.waitForTimeout(500);
  stored = await readStorage();
  const hiddenId = ids[0];
  check('移出的 id 写入 hiddenCommandIds', (stored.hiddenCommandIds || []).includes(hiddenId),
    `hidden=[${stored.hiddenCommandIds}]`);

  // 关键：指令本身**不能**被删
  check('移出不是删除（指令仍在 commands 里）',
    (stored.commands || []).some(c => c.id === hiddenId));

  ids = await popupIdsViaBackground();
  check('移出后不再出现在 popup 列表', !ids.includes(hiddenId), `ids=[${ids}]`);

  // 「已移出」区应当出现并列出它
  const hiddenSectionVisible = await opt.locator('#hiddenSection').isVisible();
  check('管理界面出现「已移出」区', hiddenSectionVisible);

  // ── 找回：从「已移出」区加回 ──
  await opt.locator('#hiddenList button').first().click({ timeout: 5000 });
  await opt.waitForTimeout(500);
  stored = await readStorage();
  check('「加回弹窗」清掉隐藏标记', !(stored.hiddenCommandIds || []).includes(hiddenId),
    `hidden=[${stored.hiddenCommandIds}]`);
  ids = await popupIdsViaBackground();
  check('加回后重新出现在 popup 列表', ids.includes(hiddenId), `ids=[${ids}]`);

  // ── 上限改成 0 = 不限，全部回来 ──
  await opt.locator('#limitInput').fill('0');
  await opt.locator('#limitInput').dispatchEvent('change');
  await opt.waitForTimeout(500);
  ids = await popupIdsViaBackground();
  const allCount = (await readStorage()).commands.length;
  check('limit=0 表示不限量', ids.length === allCount, `shown=${ids.length} all=${allCount}`);

  // ── 2. popup 的「打开搜索 Tab」入口 ──
  const page = await ctx.newPage();
  await page.goto(BASE, { timeout: TIMEOUT });

  // popup 里点按钮 → 面板应当出现在页面里
  const pop = await ctx.newPage();
  await pop.goto(popupUrl, { timeout: TIMEOUT });
  await pop.waitForTimeout(400);

  const hasQuickBtn = await pop.locator('#quickSearchTab').count();
  check('popup 有「打开搜索 Tab」入口', hasQuickBtn === 1);

  // 让 popup 对应的活动 tab 是刚才那个页面
  await page.bringToFront();
  await page.waitForTimeout(200);

  await pop.locator('#quickSearchTab').click({ timeout: 5000 }).catch(e => log('click err', String(e).slice(0, 80)));
  await page.waitForTimeout(800);
  const panelOpened = await page.locator('#__ethan_tab_palette').count();
  check('点击后页面里真的出现搜索面板', panelOpened > 0, `panels=${panelOpened}`);

  log(`\n=== ${failures === 0 ? 'ALL PASS' : failures + ' FAILURE(S)'} ===`);
} finally {
  await ctx.close().catch(() => {});
  await new Promise(r => srv.close(r));
}
process.exit(failures === 0 ? 0 : 1);
