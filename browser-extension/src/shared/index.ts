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

// ── 页面助手指令（短指令）────────────────────────────────────
// 指令从 popup 列表 / 右键菜单 / 选中工具条触发，结果流式展示在页面右上角
// 结果面板。存 chrome.storage.local 的 'commands'；使用次数存 'commandUsage'。

export type CommandScope = 'page' | 'selection';

export interface EthanCommand {
  id: string;
  label: string;             // 展示名，如「摘要」
  icon: string;              // emoji 图标
  scope: CommandScope;       // page=整页正文 / selection=选中文字
  model?: string;            // 指定模型（如翻译走小模型）；空则用服务端默认
  /** 提示词模板，占位符：{content} 正文 / {selection} 选区 / {query} 补充提问（可空） */
  promptTemplate: string;
  builtin?: boolean;         // 内置指令（不可删，可改）
}

// 翻译等轻量指令默认走的小模型 id。取值需与 Ethan 服务端 config.models 里的 id 一致，
// 用户可在指令里改。当前默认取一个 flash-lite 级小模型。
export const DEFAULT_LITE_MODEL = 'gemini-3.1-flash-lite';

export const DEFAULT_COMMANDS: EthanCommand[] = [
  {
    id: 'summary', label: '摘要', icon: '📝', scope: 'page', builtin: true,
    promptTemplate:
      '下面是一篇网页的正文，请用中文输出结构化摘要：\n\n## 概述\n用 1-2 句话概括主旨。\n\n## 要点\n分条列出 3-6 个关键信息。\n\n正文如下：\n\n{content}',
  },
  {
    id: 'translate', label: '翻译', icon: '🌐', scope: 'page', model: DEFAULT_LITE_MODEL, builtin: true,
    promptTemplate:
      '把下面的内容翻译好，中文译成英文、其它语言译成中文，只输出译文不要解释：\n\n{content}',
  },
  {
    id: 'translate-sel', label: '翻译选中', icon: '🌐', scope: 'selection', model: DEFAULT_LITE_MODEL, builtin: true,
    promptTemplate:
      '把下面的文字翻译好，中文译成英文、其它语言译成中文，只输出译文不要解释：\n\n{selection}',
  },
  {
    id: 'explain', label: '解释一下', icon: '💡', scope: 'selection', builtin: true,
    promptTemplate:
      '用简洁的中文解释下面这段文字的含义{query}：\n\n{selection}',
  },
  {
    id: 'ask-selection', label: '就选中提问', icon: '❓', scope: 'selection', builtin: true,
    promptTemplate:
      '下面是我选中的一段文字：\n\n{selection}\n\n请针对它回答我的问题{query}。',
  },
  {
    id: 'ask-page', label: '问本页', icon: '💬', scope: 'page', builtin: true,
    promptTemplate:
      '下面是一篇网页的正文，请阅读后等待我的提问（我接下来会追问）。先用一句话说明你已读完，可以开始提问。\n\n正文如下：\n\n{content}',
  },
  // ── 写作助手（scope=selection）────────────────────────────
  {
    id: 'polish', label: '润色', icon: '✨', scope: 'selection', builtin: true,
    promptTemplate:
      '请润色下面这段文字，使其更通顺、专业、地道，保持原意与语言不变，只输出润色后的文字{query}：\n\n{selection}',
  },
  {
    id: 'rewrite', label: '改写', icon: '🔄', scope: 'selection', builtin: true,
    promptTemplate:
      '请换一种表达方式改写下面这段文字，保持原意，只输出改写后的文字{query}：\n\n{selection}',
  },
  {
    id: 'expand', label: '扩写/续写', icon: '➕', scope: 'selection', builtin: true,
    promptTemplate:
      '请在保持风格与语气一致的前提下，扩写或续写下面这段文字{query}：\n\n{selection}',
  },
  // ── 生词卡片（scope=selection）────────────────────────────
  {
    id: 'vocab', label: '生词卡片', icon: '📖', scope: 'selection', builtin: true,
    promptTemplate:
      '为下面的词或短语生成一张学习卡片，用 Markdown 输出，包含：\n' +
      '- **词条**\n- **释义**（中文）\n- **词性 / 用法**\n- **例句**（原文语言 + 中文翻译各一句）\n\n词条如下：\n\n{selection}',
  },
];

/**
 * 把内置默认集里「用户列表中缺失」的指令补进来（按 id 合并）。
 * 保证扩展升级后新增的内置指令会自动出现，同时保留用户对已有指令的改动。
 */
export function withBuiltinDefaults(saved: EthanCommand[]): EthanCommand[] {
  const ids = new Set(saved.map(c => c.id));
  const missing = DEFAULT_COMMANDS.filter(c => !ids.has(c.id));
  return [...saved, ...missing];
}

/** 读用户指令；storage 为空时回落到内置默认集，并补齐缺失的内置项。 */
export async function readCommands(): Promise<EthanCommand[]> {
  const { commands } = await chrome.storage.local.get(['commands']);
  if (Array.isArray(commands) && commands.length) return withBuiltinDefaults(commands);
  return DEFAULT_COMMANDS;
}

/** 写用户指令列表（options 页保存时用）。 */
export async function saveCommands(commands: EthanCommand[]): Promise<void> {
  await chrome.storage.local.set({ commands });
}

/** 恢复内置默认集（清空用户自定义）。 */
export async function resetCommands(): Promise<void> {
  await chrome.storage.local.set({ commands: DEFAULT_COMMANDS });
}

/** 使用次数计数（用于右键菜单取 top-N）。 */
export async function readCommandUsage(): Promise<Record<string, number>> {
  const { commandUsage } = await chrome.storage.local.get(['commandUsage']);
  return commandUsage && typeof commandUsage === 'object' ? commandUsage : {};
}

/** 指令使用次数 +1。 */
export async function bumpCommandUsage(id: string): Promise<void> {
  const usage = await readCommandUsage();
  usage[id] = (usage[id] || 0) + 1;
  await chrome.storage.local.set({ commandUsage: usage });
}

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
