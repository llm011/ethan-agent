/* eslint-disable */
// Tab 搜索命令面板的 background 侧。
//
// 负责三件事：
//   1. 响应面板（content script）的 search / activate 请求 —— 面板在页面上下文里
//      调不了 chrome.tabs，必须经 background 代理；
//   2. 提供 chrome.commands 全局快捷键入口（页面没焦点时也能开）；
//   3. 维护 popup 里可配置的页面内快捷键，并在改动时广播给所有 tab。
//
// 关键：这条链路**只依赖 chrome.tabs / chrome.tabGroups**，不碰 ethan 的 ws。
// ethan 没起、端口不对、代理拦了 localhost，都不影响 tab 搜索。
import { searchTabsWithHistory, toClosedEntries } from './session-store/tab-history';
import type { ClosedTabEntry } from './session-store/tab-history';
import {
  getRecentlyClosed,
  queryGroups,
  queryTabs,
  updateTab,
} from './session-store/chrome-api';
import { toSessionTab } from './session-store/utils';
import {
  TAB_PALETTE_SHORTCUT_KEY,
  DEFAULT_TAB_PALETTE_SHORTCUT,
} from '../shared/tab-palette-config';

export { TAB_PALETTE_SHORTCUT_KEY, DEFAULT_TAB_PALETTE_SHORTCUT };

const PALETTE_FILE = 'content/tab-palette.js';

/** 记录已注入面板的 tab，避免重复注入。 */
const injectedTabs = new Set<number>();

chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'loading' && injectedTabs.has(tabId)) {
    injectedTabs.delete(tabId);
  }
});

chrome.tabs.onRemoved.addListener(tabId => {
  injectedTabs.delete(tabId);
});

/**
 * 确保面板已注入目标 tab。
 *
 * 用 content_scripts 声明式注入也行，但那样每个页面加载都要跑一遍脚本；
 * 「按需注入」只有在用户真的按快捷键时才付出成本，页面加载不受影响。
 * 代价是要处理注入失败（chrome:// 等特权页无法注入）。
 *
 * `allFrames: true` 是必须的：页面里键盘焦点落进 iframe 时，外层文档根本收不到
 * keydown，只有 iframe 自己的 content script 才看得到。只注主框架的话，表现就是
 * 「在嵌了输入框的 iframe 里按快捷键没反应」。注入到所有子框架后，哪一层有焦点
 * 就由哪一层打开面板。
 */
async function ensurePaletteInjected(tabId: number): Promise<boolean> {
  if (injectedTabs.has(tabId)) return true;
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: [PALETTE_FILE],
    });
    // 一个框架都没注入成功（比如整页都是特权上下文）才算失败
    if (!results || results.length === 0) return false;
    injectedTabs.add(tabId);
    return true;
  } catch {
    return false;
  }
}

/**
 * 让「该接手的那个框架」切换面板。
 *
 * 面板注入到了每个框架（见 ensurePaletteInjected），消息也不带 frameId——因为焦点
 * 在哪一层只有那一层自己知道（`document.hasFocus()` + activeElement 是不是 iframe），
 * 在 background 侧去算跨进程的焦点归属既不可靠也没必要。
 *
 * 所以这里是「广播问一遍，谁有焦点谁接手」：每层自行判断，只有接手的返回
 * `handled: true`。**必须只让一层接手**——都接手的话一次按键会在每层各开一个面板，
 * 用户看到顶层那个、输入却进了 iframe 里被裁掉的那个，比「没反应」更难自查。
 */
async function requestToggle(tabId: number): Promise<{ responded: boolean; handled: boolean }> {
  try {
    const res = (await chrome.tabs.sendMessage(tabId, {
      target: 'tabPalette', type: 'toggle',
    })) as { handled?: boolean } | undefined;
    // 有框架应答就说明注入是活的，即使它选择不接手（比如焦点在别的框架里）
    return { responded: true, handled: res?.handled === true };
  } catch {
    return { responded: false, handled: false };
  }
}

/**
 * 让所有框架关掉自己的面板。
 *
 * `close` 不带 handled 语义——每层都广播一遍，开着的那个自己会关。用途是清理
 * 「上一次按键留在某个 iframe 里、当前不可见」的面板：这类残留只有再次按快捷键
 * 才会被发现，用户看到的是「按了两次才有反应」。
 */
async function requestClose(tabId: number): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, { target: 'tabPalette', type: 'close' });
  } catch {
    /* 没有框架应答：本来就没有面板要关，忽略 */
  }
}

/** 在指定 tab 里开面板。注入失败时给用户一个可见的提示，而不是静默什么都不发生。 */
export async function openPaletteInTab(tabId: number): Promise<void> {
  const ok = await ensurePaletteInjected(tabId);
  if (!ok) {
    await notifyCannotInject(tabId);
    return;
  }
  // 先把可能残留在别的框架里的面板收掉：面板只该有一份，且它可能正开在
  // 上次有焦点的那个 iframe 里（用户看不见）。不清的话第二次按键看起来像
  // 「没反应」——其实关掉的是那个隐藏面板。
  await requestClose(tabId);
  // 有框架应答就算成功（它可能出于「焦点不在我这层」而选择不接手）
  if ((await requestToggle(tabId)).responded) return;
  // 注入成功但消息发不过去（页面刚导航走）：重试一次注入
  injectedTabs.delete(tabId);
  if (await ensurePaletteInjected(tabId)) {
    await requestToggle(tabId);
  }
}

/**
 * 特权页（chrome://、扩展页、应用商店）无法注入脚本。
 * 用系统通知告诉用户原因——否则表现是「按了快捷键没反应」，很难自查。
 */
async function notifyCannotInject(tabId: number): Promise<void> {
  try {
    const tab = await chrome.tabs.get(tabId);
    const url = tab.url || '';
    if (!/^(chrome|edge|about|devtools|chrome-extension|moz-extension):/i.test(url)) {
      return; // 不是特权页，可能是别的注入问题，不误导用户
    }
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon-128.png',
      title: '这个页面无法搜索标签页',
      message: '浏览器内部页面（如设置、新标签页）不允许扩展注入。换个普通网页再试，或点扩展图标。',
    });
  } catch {
    /* 忽略 */
  }
}

/** 打开「当前活动 tab」所在窗口的面板。 */
async function openPaletteInActiveTab(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && typeof tab.id === 'number') {
    await openPaletteInTab(tab.id);
  }
}

/** 把最新快捷键广播给所有已注入的 tab（含子框架），popup 改完立刻生效。 */
export async function broadcastShortcut(combo: string): Promise<void> {
  const targets = Array.from(injectedTabs);
  await Promise.all(
    targets.map(async tabId => {
      try {
        // 注入时是 allFrames，这里也必须不带 frameId 广播，否则 iframe 里那份
        // 用的一直是启动时读到的旧快捷键
        await chrome.tabs.sendMessage(tabId, {
          target: 'tabPalette',
          type: 'setShortcut',
          combo,
        });
      } catch {
        injectedTabs.delete(tabId);
      }
    }),
  );
}

export async function getShortcut(): Promise<string> {
  try {
    const stored = await chrome.storage.local.get([TAB_PALETTE_SHORTCUT_KEY]);
    const value = stored[TAB_PALETTE_SHORTCUT_KEY];
    return typeof value === 'string' ? value : DEFAULT_TAB_PALETTE_SHORTCUT;
  } catch {
    return DEFAULT_TAB_PALETTE_SHORTCUT;
  }
}

/** 面板发来的 search 请求：在扩展侧匹配，只回命中的几条。 */
async function handleSearch(query: string, includeClosed = false) {
  const tabs = (await queryTabs({})).map(toSessionTab);
  const groups = new Map<number, { title?: string; color?: string }>();
  try {
    for (const g of await queryGroups({})) {
      groups.set(g.id, {
        ...(g.title ? { title: g.title } : {}),
        ...(g.color ? { color: g.color } : {}),
      });
    }
  } catch {
    // tabGroups 不可用时降级：不影响搜索本身
  }

  // 只有开关打开时才去取历史：默认路径不碰 sessions，也就不会因缺权限而报错
  let closed: ClosedTabEntry[] = [];
  let closedError: string | undefined;
  if (includeClosed) {
    try {
      closed = toClosedEntries(await getRecentlyClosed());
    } catch (err) {
      // 取不到历史就当没有，不影响已打开的 tab 结果。但**要报出来**：
      // 这里曾经吞掉过一个 bug（closed tab 没有 id，toSessionTab 直接抛），
      // 表现是「开关点了完全没反应」且毫无线索。降级可以静默，错误不可以。
      closed = [];
      closedError = err instanceof Error ? err.message : String(err);
    }
  }

  const result = searchTabsWithHistory(
    tabs,
    closed,
    { query, limit: 50, includeClosed },
    groups,
  );
  // 开关开着却一条历史都没取到、且确实报错了：把原因带回面板，别让它看起来像「就是没有」
  if (closedError && includeClosed && result.matches.every(m => m.source !== 'closed')) {
    return { ...result, closedError };
  }
  return result;
}

/** 面板发来的 activate 请求：切到那个 tab 并聚焦它的窗口。 */
async function handleActivate(tabId: number, windowId?: number) {
  try {
    await updateTab(tabId, { active: true });
    if (typeof windowId === 'number') {
      await chrome.windows.update(windowId, { focused: true });
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

/** 注册消息监听。面板（content）发来的请求都在这里处理。 */
export function registerTabPaletteMessages(): void {
  // popup 的「打开标签页搜索」按钮：popup 自己会失焦关闭，所以由 background 代开
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.target === 'tabPaletteHost' && msg.type === 'open') {
      openPaletteFromExtensionUI()
        .then(() => sendResponse({ ok: true }))
        .catch(() => sendResponse({ ok: false }));
      return true;
    }
    return undefined;
  });

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || msg.target !== 'tabPalette') return;

    if (msg.type === 'search') {
      handleSearch(
        typeof msg.query === 'string' ? msg.query : '',
        msg.includeClosed === true,
      )
        .then(res => sendResponse(res))
        .catch(err =>
          sendResponse({
            matches: [],
            scanned: 0,
            total: 0,
            error: err instanceof Error ? err.message : String(err),
          }),
        );
      return true; // 异步响应
    }

    if (msg.type === 'activate') {
      handleActivate(Number(msg.tabId), msg.windowId)
        .then(res => sendResponse(res))
        .catch(err => sendResponse({ ok: false, error: String(err) }));
      return true;
    }

    if (msg.type === 'getShortcut') {
      getShortcut()
        .then(combo => sendResponse({ combo }))
        .catch(() => sendResponse({ combo: DEFAULT_TAB_PALETTE_SHORTCUT }));
      return true;
    }

    return false;
  });
}

/** 注册 chrome.commands 入口。 */
export function registerTabPaletteCommands(): void {
  chrome.commands.onCommand.addListener(command => {
    if (command === 'open-tab-palette') {
      void openPaletteInActiveTab();
    }
  });
}

/**
 * 打开面板给外部（如 popup 的按钮）用：优先当前活动 tab，
 * 打不开就退回到「新开一个空白页并在那里打开」——总比没反应好。
 */
export async function openPaletteFromExtensionUI(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && typeof tab.id === 'number') {
    const ok = await ensurePaletteInjected(tab.id);
    if (ok && (await requestToggle(tab.id)).responded) return;
  }
  // 活动 tab 是特权页：没法注入，那就让用户看到原因
  if (tab && typeof tab.id === 'number') {
    await notifyCannotInject(tab.id);
  }
}
