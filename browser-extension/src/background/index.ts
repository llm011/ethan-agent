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
import { setupContextMenu } from './context-menu';

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

console.log('[EthanBrowser] background started, rpc v' + BROWSER_RPC_VERSION);
