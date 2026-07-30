/* eslint-disable */
// Extension background (service worker) entry。
//
// MV3 service worker 会被 Chrome 每 ~30s 回收，无法持久保持 WS 连接。
// 解决方案：WS 连接由 offscreen document 托管（不会被回收），SW 只负责：
//   1. 启动时创建 offscreen document
//   2. 处理 offscreen 转发来的 RPC 请求（dispatch → chrome.debugger 等操作）
//   3. 响应 popup 的状态查询 / 手动重连（转发给 offscreen）
//   4. storage 变化时通知 offscreen 重连
//   5. alarm 定期确保 offscreen document 存在（兜底）

import { BROWSER_RPC_VERSION } from '../shared';

import { BrowserSessionStore } from './session-store';
import { handleNativeRequest } from './rpc';
import { BrowserPageController } from './page-controller';
import { NetworkMonitor } from './network-monitor';
import { releaseCdpClient } from './cdp-client';
import { KEEPALIVE_ALARM } from './ws-client';
import { pushStep, updateStepStatus } from './overlay-injector';
import { setupContextMenu, sendToEthan } from './context-menu';

const sessionStore = new BrowserSessionStore();
const pageController = new BrowserPageController(sessionStore);
const networkMonitor = new NetworkMonitor(sessionStore);

const OFFSCREEN_URL = 'offscreen.html';
let offscreenCreating: Promise<void> | null = null;

// 需要推送到浮层的页面操作（method → action 名）
const STEP_METHODS: Record<string, string> = {
  'pages.snapshot': 'snapshot',
  'pages.click': 'click',
  'pages.fill': 'fill',
  'pages.type': 'type',
  'pages.press': 'press',
  'pages.hover': 'hover',
  'pages.select': 'select',
  'pages.scroll': 'scroll',
  'pages.scrollIntoView': 'scroll_into_view',
  'pages.screenshot': 'screenshot',
  'pages.get': 'get',
  'pages.mouse': 'mouse',
  'pages.wait': 'wait',
  'pages.eval': 'eval',
  'pages.upload': 'upload',
  'pages.savePdf': 'save_pdf',
};

/** 包装页面操作：执行前推送步骤到浮层，执行后更新状态 */
function withOverlay(action: string, handler: (params: any) => Promise<any>) {
  return async (params: any) => {
    // 推送步骤到浮层（fire-and-forget，不阻塞操作）
    let tabId: number | undefined;
    let stepTs: number | null = null;
    try {
      const activeTab = await sessionStore.getActiveTab({ sessionId: params.sessionId });
      tabId = activeTab.tab.tabId;
      stepTs = await pushStep(tabId, action, params);
    } catch {}

    try {
      const result = await handler(params);
      if (tabId != null && stepTs != null) {
        void updateStepStatus(tabId, stepTs, 'done');
      }
      return result;
    } catch (e) {
      if (tabId != null && stepTs != null) {
        void updateStepStatus(tabId, stepTs, 'error');
      }
      throw e;
    }
  };
}

async function dispatch(message: unknown): Promise<unknown | null> {
  return handleNativeRequest(message, {
    createSession: params => sessionStore.createSession(params),
    attachCurrentSession: params => sessionStore.attachCurrentSession(params),
    listSessions: () => sessionStore.listSessions(),
    renameSession: params => sessionStore.renameSession(params),
    releaseSession: params => sessionStore.releaseSession(params),
    closeSession: params => sessionStore.closeSession(params),
    openTab: params => sessionStore.openTab(params),
    listTabs: params => sessionStore.listTabs(params),
    listUserTabs: () => sessionStore.listUserTabs(),
    attachTab: params => sessionStore.attachTab(params),
    getActiveTab: params => sessionStore.getActiveTab(params),
    activateTab: params => sessionStore.activateTab(params),
    closeTab: params => sessionStore.closeTab(params),
    attachBatchTabs: params => sessionStore.attachBatchTabs(params),
    detachTab: params => sessionStore.detachTab(params),
    moveTab: params => sessionStore.moveTab(params),
    updateSession: params => sessionStore.updateSession(params),
    pageSnapshot: withOverlay('snapshot', params => pageController.snapshot(params)),
    pageClick: withOverlay('click', params => pageController.click(params)),
    pageFill: withOverlay('fill', params => pageController.fill(params)),
    pageType: withOverlay('type', params => pageController.type(params)),
    pagePress: withOverlay('press', params => pageController.press(params)),
    pageHover: withOverlay('hover', params => pageController.hover(params)),
    pageSelect: withOverlay('select', params => pageController.select(params)),
    pageScroll: withOverlay('scroll', params => pageController.scroll(params)),
    pageScrollIntoView: withOverlay('scroll_into_view', params => pageController.scrollIntoView(params)),
    pageScreenshot: withOverlay('screenshot', params => pageController.screenshot(params)),
    pageGet: withOverlay('get', params => pageController.get(params)),
    pageMouse: withOverlay('mouse', params => pageController.mouse(params)),
    pageWait: withOverlay('wait', params => pageController.wait(params)),
    pageEval: withOverlay('eval', params => pageController.eval(params)),
    pageUpload: withOverlay('upload', params => pageController.upload(params)),
    pageSavePdf: withOverlay('save_pdf', params => pageController.savePdf(params)),
    networkStart: params => networkMonitor.start(params),
    networkStop: params => networkMonitor.stop(params),
    networkList: params => networkMonitor.list(params),
    networkDetail: params => networkMonitor.detail(params),
  });
}

// ── offscreen document 管理 ──────────────────────────────────

// 全局标志：offscreen document 是否已创建。
// 避免重复调用 createDocument（即使 getContexts 误判也不会重复创建）。
let offscreenCreated = false;

async function hasOffscreenDocument(): Promise<boolean> {
  if (offscreenCreated) return true;
  try {
    const existingContexts = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT' as chrome.runtime.ContextType],
    });
    return existingContexts.length > 0;
  } catch {
    return false;
  }
}

async function ensureOffscreenDocument(): Promise<void> {
  if (offscreenCreating) {
    await offscreenCreating;
    return;
  }
  if (offscreenCreated) return;

  offscreenCreating = chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ['WEB_RTC' as chrome.offscreen.Reason],
    justification: 'Maintain persistent WebSocket connection to Ethan agent server',
  }).then(async () => {
    console.log('[EthanBrowser] offscreen document created');
    offscreenCreated = true;
    configPushed = false;  // 新 offscreen，需要重新推送
    // 直接推送配置，避免绕回 ensureOffscreenAndPushConfig 产生循环调用
    const cfg = await readWsConfig();
    if (cfg) {
      try {
        await chrome.runtime.sendMessage({ target: 'offscreen', type: 'config', config: cfg });
        configPushed = true;
        console.log('[EthanBrowser] config pushed to offscreen');
      } catch (e) {
        console.warn('[EthanBrowser] push config to offscreen failed', e);
      }
    }
  }).catch((e: any) => {
    if (!String(e?.message || '').includes('Only a single offscreen')) {
      console.warn('[EthanBrowser] create offscreen document failed', e);
    } else {
      offscreenCreated = true;
    }
  }).finally(() => {
    offscreenCreating = null;
  });

  await offscreenCreating;
}

// 启动时立即创建 offscreen document 并推送配置
void ensureOffscreenAndPushConfig();

// 初始化右键菜单
setupContextMenu();

/** 向 offscreen 发消息，带超时 */
async function sendToOffscreen(message: unknown, timeoutMs = 3000): Promise<any> {
  await ensureOffscreenDocument();
  return Promise.race([
    chrome.runtime.sendMessage(message).catch(e => {
      console.warn('[EthanBrowser] sendMessage to offscreen failed:', e);
      return null;
    }),
    new Promise<null>(resolve => setTimeout(() => resolve(null), timeoutMs)),
  ]);
}

// ── 消息路由 ──────────────────────────────────────────────────

// 读 storage 配置（SW 中可用 chrome.storage）
async function readWsConfig(): Promise<{ serverUrl: string; token: string } | null> {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  if (!serverUrl || !token) return null;
  return { serverUrl, token };
}

// 创建 offscreen 后主动推送配置（只在首次推送，避免重复触发重连）
let configPushed = false;
async function ensureOffscreenAndPushConfig(): Promise<void> {
  await ensureOffscreenDocument();
  if (configPushed) return;  // 已推送过，不重复
  const cfg = await readWsConfig();
  if (cfg) {
    try {
      await chrome.runtime.sendMessage({ target: 'offscreen', type: 'config', config: cfg });
      configPushed = true;
      console.log('[EthanBrowser] config pushed to offscreen');
    } catch (e) {
      console.warn('[EthanBrowser] push config to offscreen failed', e);
    }
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // 来自 offscreen 的配置请求
  if (msg?.target === 'sw' && msg.type === 'get_config') {
    readWsConfig().then(cfg => {
      sendResponse(cfg);
    }).catch(e => {
      sendResponse(null);
    });
    return true;
  }

  // 来自 offscreen 的 RPC 请求：dispatch 后返回结果
  if (msg?.target === 'sw' && msg.rpc !== undefined) {
    dispatch(msg.rpc).then(result => {
      sendResponse(result);
    }).catch(e => {
      sendResponse({ error: { message: String(e), code: -32603 } });
    });
    return true; // 异步 sendResponse
  }

  // 来自 popup 的状态查询 → 转发给 offscreen
  if (msg?.type === 'getStatus') {
    sendToOffscreen({ target: 'offscreen', type: 'get_status' }).then(resp => {
      sendResponse(resp ?? { connected: false, error: 'offscreen_no_response' });
    }).catch(e => {
      sendResponse({ connected: false, error: String(e?.message || e) });
    });
    return true;
  }

  // 来自 popup 的手动重连 → 推送配置 + 转发给 offscreen
  if (msg?.type === 'reconnect') {
    (async () => {
      try {
        await ensureOffscreenDocument();
        const cfg = await readWsConfig();
        if (cfg) {
          try {
            await chrome.runtime.sendMessage({ target: 'offscreen', type: 'config', config: cfg });
          } catch {}
        }
        const resp = await sendToOffscreen({ target: 'offscreen', type: 'reconnect' }, 5000);
        sendResponse(resp ?? { ok: false });
      } catch (e: any) {
        sendResponse({ ok: false, error: String(e?.message || e) });
      }
    })();
    return true;
  }

  return undefined;
});

// ── storage 变化 → 通知 offscreen 重连 ──────────────────────

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.serverUrl || changes.token)) {
    // 配置变化：读新配置推送给 offscreen，offscreen 收到后自动重连
    void (async () => {
      const cfg = await readWsConfig();
      if (cfg) {
        try {
          await chrome.runtime.sendMessage({ target: 'offscreen', type: 'config', config: cfg });
        } catch (e) {
          console.warn('[EthanBrowser] push updated config failed', e);
        }
      }
    })();
  }
});

// ── alarm 兜底：确保 offscreen document 存在 ─────────────────

chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === KEEPALIVE_ALARM) {
    // 定期确保 offscreen 存在并推送配置（如果 offscreen 已在则 no-op）
    void ensureOffscreenDocument();
  }
});

// ── tab 清理 ─────────────────────────────────────────────────

chrome.tabs.onRemoved.addListener(tabId => {
  void sessionStore.handleTabRemoved(tabId);
  void releaseCdpClient(tabId);
});

// ── cookie 弹窗自动关闭 ───────────────────────────────────────
// 当 Ethan session 的 tab 加载完成时，注入 cookie-closer 脚本。
chrome.tabs.onUpdated.addListener((tabId, change, _tab) => {
  if (change.status !== 'complete') return;
  void (async () => {
    try {
      const { autoCloseCookies } = await chrome.storage.local.get('autoCloseCookies');
      if (autoCloseCookies === false) return;  // 默认开启，显式 false 才关闭
      // 只注入 Ethan session 管理的 tab
      const sessions = await sessionStore.listSessions();
      const ethanTabIds = new Set<number>();
      for (const s of sessions.sessions) {
        for (const t of s.tabs) {
          if (typeof t.tabId === 'number') ethanTabIds.add(t.tabId);
        }
      }
      if (!ethanTabIds.has(tabId)) return;
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content/cookie-closer.js'],
      }).catch(() => {});  // chrome:// 等页面注入会失败，静默
    } catch {}
  })();
});

// ── 快捷键（manifest commands）─────────────────────────────────

// 在页面上下文中提取正文为 Markdown（与 browser.py 的 _MARKDOWN_SCRIPT 同源逻辑）
// 用 chrome.scripting.executeScript 的 func 参数直接传函数，避免字符串转义问题
// 注意：此函数会被序列化后在页面上下文中执行，TypeScript 类型在此无意义，用 any 简化
function extractMarkdownInPage(): any {
  const clone: any = document.body.cloneNode(true);
  clone.querySelectorAll('nav,header,footer,aside,script,style,iframe,noscript,svg,form,button,[role="navigation"],[role="banner"],[role="contentinfo"],.ad,.ads,.advertisement,.sidebar,.cookie,.popup,.modal,.share,.related,.comments').forEach((e: any) => e.remove());

  let main: any = clone.querySelector('article') || clone.querySelector('main') || clone.querySelector('[role="main"]') || clone.querySelector('#content,.content,.post-content,.article-content,.entry-content,.post-body,.article-body');
  if (!main) {
    let best: any = null;
    let bestScore = 0;
    for (const el of clone.querySelectorAll('div,section')) {
      const t = el.innerText || '';
      const len = t.length;
      if (len < 200) continue;
      const score = len - el.querySelectorAll('a').length * 50;
      if (score > bestScore) { bestScore = score; best = el; }
    }
    main = best || clone;
  }

  function cv(node: any): string {
    let r = '';
    for (const c of node.childNodes) {
      if (c.nodeType === 3) { const t = (c.textContent || '').trim(); if (t) r += t + ' '; continue; }
      if (c.nodeType !== 1) continue;
      const tag = c.tagName.toLowerCase();
      const inner = () => cv(c).trim();
      switch (tag) {
        case 'h1': r += '\n# ' + inner() + '\n\n'; break;
        case 'h2': r += '\n## ' + inner() + '\n\n'; break;
        case 'h3': r += '\n### ' + inner() + '\n\n'; break;
        case 'h4': r += '\n#### ' + inner() + '\n\n'; break;
        case 'h5': r += '\n##### ' + inner() + '\n\n'; break;
        case 'h6': r += '\n###### ' + inner() + '\n\n'; break;
        case 'p': r += inner() + '\n\n'; break;
        case 'br': r += '\n'; break;
        case 'hr': r += '\n---\n\n'; break;
        case 'strong': case 'b': r += '**' + inner() + '**'; break;
        case 'em': case 'i': r += '*' + inner() + '*'; break;
        case 'code':
          if (c.parentElement && c.parentElement.tagName.toLowerCase() === 'pre') break;
          r += '`' + (c.innerText || '') + '`'; break;
        case 'pre': {
          const code = c.querySelector('code');
          const lang = code ? (code.className.match(/language-(\w+)/) || [])[1] : '';
          r += '\n```' + (lang || '') + '\n' + (c.innerText || '') + '\n```\n\n'; break;
        }
        case 'blockquote': r += '\n> ' + inner().replace(/\n/g, '\n> ') + '\n\n'; break;
        case 'a': { const h = c.getAttribute('href') || '', t = c.innerText || ''; r += h && t ? '[' + t + '](' + h + ')' : t; break; }
        case 'img': { const s = c.getAttribute('src') || c.getAttribute('data-src') || '', a = c.getAttribute('alt') || ''; if (s) r += '![' + a + '](' + s + ')'; break; }
        case 'ul': case 'ol': r += '\n' + cvList(c, tag === 'ol') + '\n\n'; break;
        case 'table': r += cvTable(c) + '\n\n'; break;
        default: r += cv(c);
      }
    }
    return r;
  }
  function cvList(list: any, ord: boolean): string {
    let r = '', i = 1;
    for (const li of list.children) {
      if (li.tagName.toLowerCase() !== 'li') continue;
      r += (ord ? (i++) + '. ' : '- ') + cv(li).trim().replace(/\n/g, '\n  ') + '\n';
    }
    return r;
  }
  function cvTable(t: any): string {
    const rows = t.querySelectorAll('tr');
    if (!rows.length) return '';
    let r = '', first = true;
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll('th,td')).map((c: any) => (c.innerText || '').trim().replace(/\n/g, ' '));
      r += '| ' + cells.join(' | ') + ' |\n';
      if (first) { r += '|' + cells.map(() => '---').join('|') + '|\n'; first = false; }
    }
    return r;
  }

  const md = cv(main).replace(/\n{3,}/g, '\n\n').trim();
  return JSON.stringify({ markdown: md, length: md.length, title: document.title, url: location.href });
}

chrome.commands.onCommand.addListener((command) => {
  if (command === 'toggle-overlay') {
    // 切换浮层：向当前激活 tab 注入 overlay 脚本（如果还没注入），然后发 toggle 消息
    void (async () => {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) return;
        // 先确保 overlay.js 已注入
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content/overlay.js'],
        }).catch(() => {});
        // 再发 toggle 消息
        await chrome.tabs.sendMessage(tab.id, { target: 'overlay', type: 'toggleOverlay' }).catch(() => {});
      } catch {}
    })();
    return;
  }

  if (command === 'extract-markdown') {
    // 提取页面正文为 Markdown，发给 Ethan
    void (async () => {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.id) return;
        // 在页面执行 Markdown 提取函数
        const results = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: extractMarkdownInPage,
        }).catch(() => []);
        if (!results?.[0]?.result) return;
        const info = JSON.parse(results[0].result as string);
        const md = info?.markdown || '';
        if (!md) return;
        // 截断超长内容
        const maxLen = 30000;
        const content = md.length > maxLen
          ? md.slice(0, maxLen) + '\n\n<!-- 已截断（共 ' + md.length + ' 字，前 ' + maxLen + ' 字）-->\n\n来源：' + (info.url || '')
          : md;
        // 复用右键菜单的发送逻辑（发起对话 + 打开 redirect 页面）
        await sendToEthan(content);
      } catch {}
    })();
    return;
  }
});

console.log('[EthanBrowser] background started, rpc v' + BROWSER_RPC_VERSION);
