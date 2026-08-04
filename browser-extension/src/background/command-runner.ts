/* eslint-disable */
// 短指令执行：popup / 右键菜单 / 选中工具条触发一条指令后，
//   1. 按 scope 取上下文（page → 正文 Markdown；selection → 选中文字）
//   2. 用上下文 + 可选 query 填 promptTemplate
//   3. 注入结果面板，开一条新结果，streamChat 把结果流式推进面板
//   4. 使用次数 +1（供右键菜单取 top-N）
//
// page 正文走 window.__ethanReader.extractMarkdown()（reader-extract.js）。
// selection 直接从页面读 window.getSelection()。

import { readCommands, bumpCommandUsage, type EthanCommand } from '../shared';
import { fetchFeishuDocMarkdown } from './reading-injector';
import { streamChat } from './chat-proxy';

const MAX_CONTENT = 12000;   // 正文/选区注入模型前的截断上限

function genId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

/** 页面正文 Markdown：普通页面 DOM 抽取；飞书文档页面 → server 端 lark-doc skill 抓全文（双层缓存）。 */
async function getPageContent(tabId: number): Promise<string> {
  // 飞书文档：虚拟滚动 DOM 拿不全，优先本地 server 调 lark-doc skill 的 fetch 接口
  // （浏览器 24h 缓存 + skill 自身磁盘缓存，失败再退 DOM 抽取）
  try {
    const tab = await chrome.tabs.get(tabId);
    const url = tab?.url || '';
    if (url) {
      const full = await fetchFeishuDocMarkdown(tabId, url);
      if (full && full.markdown) return full.markdown;
    }
  } catch {
    /* 退到通用页面抽取 */
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ['content/reader-extract.js'],
  }).catch(() => {});
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => (window as any).__ethanReader?.extractMarkdown()?.markdown || '',
  }).catch(() => []);
  return (results?.[0]?.result as string) || '';
}

/** 当前选中文字。 */
async function getSelectionText(tabId: number): Promise<string> {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => (window.getSelection()?.toString() || '').trim(),
  }).catch(() => []);
  return (results?.[0]?.result as string) || '';
}

/**
 * 对全文翻译等大 token 消耗的指令，在页面里弹出二次确认：
 * 点「取消」返回 false → runCommand 直接中止不发请求。
 * 用 executeScript 在页面里跑 window.confirm，方便用户直接看到确认弹窗。
 */
async function confirmHeavyCommand(tabId: number, title: string, message: string): Promise<boolean> {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (t: string, m: string) => window.confirm(`${t}\n\n${m}`),
      args: [title, message],
    });
    return Boolean(results?.[0]?.result);
  } catch {
    // 页面不让注入（比如 chrome:// 页面）就默认放行，由下一步 getPageContent 报错
    return true;
  }
}

/** 全文翻译等指令：二次确认的规则表（id 为真就弹）。 */
function heavyCommandConfirm(cmd: EthanCommand): { title: string; message: string } | null {
  if (cmd.id === 'translate' && cmd.scope === 'page') {
    return {
      title: '全文翻译需要调用模型翻译整页内容',
      message: '整页翻译可能消耗较多 Token，确定继续吗？\n\n（取消可以改用「翻译选中」只翻译选中的部分）',
    };
  }
  return null;
}

function fillTemplate(tpl: string, vars: { content?: string; selection?: string; query?: string }): string {
  return tpl
    .replace(/\{content\}/g, (vars.content || '').slice(0, MAX_CONTENT))
    .replace(/\{selection\}/g, (vars.selection || '').slice(0, MAX_CONTENT))
    // {query} 前置一个空格，空 query 时整体消失，模板里写「解释{query}：」读起来自然
    .replace(/\{query\}/g, vars.query ? '（' + vars.query + '）' : '');
}

/**
 * 执行一条指令。selectionText/query 可由调用方直接传（选中工具条场景），
 * 不传则 background 自行从页面读取。
 */
export async function runCommand(
  tabId: number,
  commandId: string,
  extra: { selectionText?: string; query?: string } = {},
): Promise<{ ok: boolean; error?: string }> {
  const commands = await readCommands();
  const cmd = commands.find(c => c.id === commandId);
  if (!cmd) return { ok: false, error: 'command_not_found' };

  // 全文翻译等重指令：先二次确认，用户取消直接返回
  const confirmCfg = heavyCommandConfirm(cmd);
  if (confirmCfg) {
    const ok = await confirmHeavyCommand(tabId, confirmCfg.title, confirmCfg.message);
    if (!ok) return { ok: false, error: '用户取消' };
  }

  // 取上下文
  let content = '';
  let selection = extra.selectionText || '';
  try {
    if (cmd.scope === 'page') {
      content = await getPageContent(tabId);
      if (!content) return { ok: false, error: '未能提取到正文' };
    } else {
      if (!selection) selection = await getSelectionText(tabId);
      if (!selection) return { ok: false, error: '请先选中文字' };
    }
  } catch (e: any) {
    return { ok: false, error: '当前页面不支持（' + String(e?.message || e) + '）' };
  }

  const prompt = fillTemplate(cmd.promptTemplate, { content, selection, query: extra.query });

  // 注入结果面板，开一条新结果
  const requestId = genId();
  const sessionId = 'cmd-' + genId();   // 每条指令一个 session，供面板内追问多轮
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/result-panel.js'],
    });
    await chrome.tabs.sendMessage(tabId, {
      target: 'result', type: 'newResult',
      // content script 侧监听 newResult 消息（见下）
      // ask-page 是「读完正文后我来追问」的场景，让面板自动聚焦追问框
      title: cmd.label, sessionId, requestId, focusInput: cmd.id === 'ask-page',
    });
  } catch (e: any) {
    return { ok: false, error: '面板注入失败（页面可能不允许）' };
  }

  // ask-page 是「首轮塞正文、后续追问」的多轮场景 → 带 sessionId 走多轮；
  // 其它指令首轮也带 sessionId（btw=false），让 Ethan 服务端按 session 存好 user+assistant 两条历史。
  // 这样用户在结果面板里追问时（sendFollowUp 会带同一个 sessionId），服务端能拼上之前的上下文。
  void streamChat(tabId, requestId, prompt, {
    uiTarget: 'result',
    model: cmd.model,
    sessionId: sessionId,
  });
  void bumpCommandUsage(commandId);
  return { ok: true };
}
