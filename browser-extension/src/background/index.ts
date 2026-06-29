/* eslint-disable */
// Extension background entry —— 用 WS 取代原 Native Messaging。
// 把扩展收到的 JSON-RPC 请求交给 handleNativeRequest 分发到 session-store/page-controller。

import { COZE_BROWSER_RPC_VERSION } from '../shared';

import { BrowserSessionStore } from './session-store';
import { handleNativeRequest } from './rpc';
import { BrowserPageController } from './page-controller';
import { releaseCdpClient } from './cdp-client';
import { BrowserWsClient, KEEPALIVE_ALARM, type WsClientConfig } from './ws-client';

const sessionStore = new BrowserSessionStore();
const pageController = new BrowserPageController(sessionStore);

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
    pageSnapshot: params => pageController.snapshot(params),
    pageClick: params => pageController.click(params),
    pageFill: params => pageController.fill(params),
    pageType: params => pageController.type(params),
    pagePress: params => pageController.press(params),
    pageHover: params => pageController.hover(params),
    pageSelect: params => pageController.select(params),
    pageScroll: params => pageController.scroll(params),
    pageScrollIntoView: params => pageController.scrollIntoView(params),
    pageScreenshot: params => pageController.screenshot(params),
    pageGet: params => pageController.get(params),
    pageMouse: params => pageController.mouse(params),
    pageWait: params => pageController.wait(params),
    pageEval: params => pageController.eval(params),
  });
}

async function loadConfig(): Promise<WsClientConfig | null> {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  if (!serverUrl || !token) {
    return null;
  }
  return { serverUrl, token };
}

const wsClient = new BrowserWsClient(loadConfig, dispatch);
wsClient.start();

// alarm 兜底：SW 被回收后由 alarm 重新拉起并补连。
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === KEEPALIVE_ALARM) {
    wsClient.ensureConnected();
  }
});

// options 改了配置 → 立即重连。
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.serverUrl || changes.token)) {
    wsClient.stop();
    wsClient.start();
  }
});

chrome.tabs.onRemoved.addListener(tabId => {
  void sessionStore.handleTabRemoved(tabId);
  void releaseCdpClient(tabId);
});

console.log('[CozeBrowser] background started, rpc v' + COZE_BROWSER_RPC_VERSION);
