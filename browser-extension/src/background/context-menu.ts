/* eslint-disable */
// 右键菜单：选中文字/链接/页面 → 发给 Ethan
//
// 点击后生成 session_id，POST /api/chat 发起对话（fire-and-forget），
// 然后打开 Web UI 的对应会话页，用户在浏览器里看到 agent 的回复。

const MENU_SELECTION = 'ethan-send-selection';
const MENU_LINK = 'ethan-send-link';
const MENU_PAGE = 'ethan-send-page';

/** 把 ws://host/ws/browser 转成 http://host */
function wsToHttp(wsUrl: string): string {
  return wsUrl.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:').replace(/\/ws\/browser\/?$/, '');
}

export function setupContextMenu(): void {
  // 清除旧菜单（重装/更新时避免重复）
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_SELECTION,
      title: '发给 Ethan',
      contexts: ['selection'],
    });
    chrome.contextMenus.create({
      id: MENU_LINK,
      title: '发送链接给 Ethan',
      contexts: ['link'],
    });
    chrome.contextMenus.create({
      id: MENU_PAGE,
      title: '发送页面给 Ethan',
      contexts: ['page'],
    });
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  let content = '';
  const pageLabel = tab?.title ? tab.title : info.pageUrl || '';

  if (info.menuItemId === MENU_SELECTION) {
    const text = (info.selectionText || '').trim();
    if (!text) return;
    content = text;
  } else if (info.menuItemId === MENU_LINK) {
    const linkUrl = info.linkUrl || '';
    const linkText = info.selectionText?.trim() || linkUrl;
    content = `[${linkText}](${linkUrl})`;
  } else if (info.menuItemId === MENU_PAGE) {
    const url = info.pageUrl || tab?.url || '';
    content = `**${pageLabel}**\n\n${url}`;
  } else {
    return;
  }

  void sendToEthan(content);
});

async function sendToEthan(content: string): Promise<void> {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  if (!serverUrl || !token) {
    // 没配置 → 打开 popup 让用户配置
    chrome.action.openPopup?.();
    return;
  }

  const httpBase = wsToHttp(serverUrl);
  const sessionId = crypto.randomUUID();

  // fire-and-forget：发起对话请求，不等 agent 跑完
  void fetch(`${httpBase}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      messages: [{ role: 'user', content }],
      stream: true,
      session_id: sessionId,
      channel: 'browser-extension',
    }),
  }).catch(() => {
    // 请求失败时用户会在 Web UI 看到错误，这里静默
  });

  // 打开 Web UI 的对应会话页
  chrome.tabs.create({ url: `${httpBase}/chat/${sessionId}` });
}
