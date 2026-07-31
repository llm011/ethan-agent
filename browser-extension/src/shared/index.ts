/* eslint-disable */
// 本地内联的协议常量与类型,不依赖任何外部包。
// 只保留 sessions.* / tabs.* / pages.* 命名空间,供扩展各模块共享。
export type * from './types';

export const BROWSER_RPC_VERSION = 1;

// chrome.alarms 名称：定期唤醒 SW / 确保 offscreen 存活。
export const KEEPALIVE_ALARM = 'ethan-browser-keepalive';

export interface ServerConfig {
  serverUrl: string; // 如 ws://localhost:8900/ws/browser
  token: string;
}

/** 把 ws://host/ws/browser 转成 http://host（wss→https）。 */
export function wsToHttp(wsUrl: string): string {
  return wsUrl
    .replace(/^wss:/, 'https:')
    .replace(/^ws:/, 'http:')
    .replace(/\/ws\/browser\/?$/, '');
}

/** 从 chrome.storage.local 读 serverUrl/token，缺任一则返回 null。 */
export async function readServerConfig(): Promise<ServerConfig | null> {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  if (!serverUrl || !token) return null;
  return { serverUrl, token };
}

export const BROWSER_RPC_METHODS = {
  authenticate: 'browser.authenticate',
  sessionsCreate: 'sessions.create',
  sessionsAttachCurrent: 'sessions.attachCurrent',
  sessionsList: 'sessions.list',
  sessionsRename: 'sessions.rename',
  sessionsRelease: 'sessions.release',
  sessionsClose: 'sessions.close',
  sessionsUpdate: 'sessions.update',
  tabsOpen: 'tabs.open',
  tabsList: 'tabs.list',
  tabsUserList: 'tabs.userList',
  tabsAttach: 'tabs.attach',
  tabsActive: 'tabs.active',
  tabsActivate: 'tabs.activate',
  tabsClose: 'tabs.close',
  tabsAttachBatch: 'tabs.attachBatch',
  tabsDetach: 'tabs.detach',
  tabsMove: 'tabs.move',
  pagesSnapshot: 'pages.snapshot',
  pagesClick: 'pages.click',
  pagesFill: 'pages.fill',
  pagesType: 'pages.type',
  pagesPress: 'pages.press',
  pagesHover: 'pages.hover',
  pagesSelect: 'pages.select',
  pagesScroll: 'pages.scroll',
  pagesScrollIntoView: 'pages.scrollIntoView',
  pagesScreenshot: 'pages.screenshot',
  pagesGet: 'pages.get',
  pagesMouse: 'pages.mouse',
  pagesWait: 'pages.wait',
  pagesEval: 'pages.eval',
  pagesUpload: 'pages.upload',
  pagesSavePdf: 'pages.savePdf',
  networkStart: 'network.start',
  networkStop: 'network.stop',
  networkList: 'network.list',
  networkDetail: 'network.detail',
} as const;

export const BROWSER_RPC_ERROR_CODE = {
  invalidRequest: -32600,
  methodNotFound: -32601,
  invalidParams: -32602,
  internalError: -32603,
  unauthorized: 4001,
  browserExtensionNotConnected: 4101,
  browserOperationFailed: 4102,
  browserSessionRequired: 4103,
  browserTabNotFound: 4104,
  browserTabClaimedByAnotherSession: 4105,
  browserTabGroupFailed: 4106,
  browserSessionNotFound: 4107,
  browserTabNotInSession: 4108,
  browserPageRefNotFound: 4109,
  browserPageOperationFailed: 4110,
} as const;
