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
import { streamChat } from './chat-proxy';

const MAX_CONTENT = 12000;   // 正文/选区注入模型前的截断上限

function genId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

/** 页面正文 Markdown（注入 reader-extract 后调 extractMarkdown）。 */
async function getPageContent(tabId: number): Promise<string> {
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
  // 其余指令首轮单轮（btw），面板内追问时再各自带 session。
  const multiTurn = cmd.id === 'ask-page';
  void streamChat(tabId, requestId, prompt, {
    uiTarget: 'result',
    model: cmd.model,
    sessionId: multiTurn ? sessionId : undefined,
  });
  void bumpCommandUsage(commandId);
  return { ok: true };
}
