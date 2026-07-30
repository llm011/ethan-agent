/* eslint-disable */
// 右键菜单：选中文字/链接/页面 → 发给 Ethan
//
// 点击后生成 session_id，POST /api/chat 发起对话（fire-and-forget），
// 然后打开 redirect 中间页：先尝试 ethan:// deep link 唤起桌面端，
// 唤不起时 2s 后自动 fallback 到 Web UI。

import { wsToHttp, readServerConfig, readCommands, readCommandUsage } from '../shared';
import { runCommand } from './command-runner';

const MENU_SELECTION = 'ethan-send-selection';
const MENU_LINK = 'ethan-send-link';
const MENU_PAGE = 'ethan-send-page';
const CMD_PREFIX = 'ethan-cmd-';   // 指令菜单项 id 前缀：ethan-cmd-<commandId>
const TOP_N = 3;                    // 右键菜单里展示的高频指令数

/**
 * 重建右键菜单：固定的「发给 Ethan」三项 + 按使用次数排序的 top-3 指令。
 * commands / commandUsage 变化时（storage.onChanged）会重建。
 */
export function setupContextMenu(): void {
  chrome.contextMenus.removeAll(async () => {
    chrome.contextMenus.create({ id: MENU_SELECTION, title: '发给 Ethan', contexts: ['selection'] });
    chrome.contextMenus.create({ id: MENU_LINK, title: '发送链接给 Ethan', contexts: ['link'] });
    chrome.contextMenus.create({ id: MENU_PAGE, title: '发送页面给 Ethan', contexts: ['page'] });

    // 高频指令：按 commandUsage 排序取前 TOP_N，scope 决定挂在选区还是整页 context
    try {
      const [commands, usage] = await Promise.all([readCommands(), readCommandUsage()]);
      const top = [...commands]
        .sort((a, b) => (usage[b.id] || 0) - (usage[a.id] || 0))
        .slice(0, TOP_N);
      if (top.length) {
        chrome.contextMenus.create({ id: 'ethan-cmd-sep', type: 'separator', contexts: ['selection', 'page'] });
        for (const cmd of top) {
          chrome.contextMenus.create({
            id: CMD_PREFIX + cmd.id,
            title: cmd.icon + ' ' + cmd.label,
            contexts: [cmd.scope === 'selection' ? 'selection' : 'page'],
          });
        }
      }
    } catch { /* 无配置时只保留固定项 */ }
  });
}

// commands / commandUsage 变化时重建菜单，让 top-3 跟随使用习惯更新
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.commands || changes.commandUsage)) {
    setupContextMenu();
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const id = String(info.menuItemId);

  // 指令项：交给 command-runner 执行，结果进页面结果面板
  if (id.startsWith(CMD_PREFIX)) {
    const commandId = id.slice(CMD_PREFIX.length);
    const tabId = tab?.id;
    if (typeof tabId === 'number') {
      void runCommand(tabId, commandId, { selectionText: info.selectionText?.trim() });
    }
    return;
  }

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

export async function sendToEthan(content: string): Promise<void> {
  const cfg = await readServerConfig();
  if (!cfg) {
    // 没配置 → 打开 popup 让用户配置
    chrome.action.openPopup?.();
    return;
  }

  const { serverUrl, token } = cfg;
  const httpBase = wsToHttp(serverUrl);
  const sessionId = crypto.randomUUID();

  // fire-and-forget：发起对话请求，不等 agent 跑完
  // stream: false 让后端在 agent 完成后返回完整响应，避免 SSE 流被中途丢弃
  void fetch(`${httpBase}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      messages: [{ role: 'user', content }],
      stream: false,
      session_id: sessionId,
      channel: 'browser-extension',
    }),
  }).catch(() => {
    // 请求失败时用户会在 redirect 后的界面看到错误
  });

  // 打开 redirect 中间页：先尝试 deep link 唤起桌面端，唤不起时 fallback 到 Web UI
  const redirectUrl = chrome.runtime.getURL('redirect.html') +
    `?deeplink=${encodeURIComponent(`ethan://chat/${sessionId}`)}` +
    `&fallback=${encodeURIComponent(`${httpBase}/chat/${sessionId}`)}`;
  chrome.tabs.create({ url: redirectUrl });
}
