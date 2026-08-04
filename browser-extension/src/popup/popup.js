/* eslint-disable */
import { wsToHttp, readCommands } from '../shared';

const $ = id => document.getElementById(id);

const DEFAULT_URL = 'ws://localhost:8900/ws/browser';

/** 给 #hint 设文案；level=ok 绿/err 红/warn 黄/默认灰 */
function setHint(text, level) {
  const el = $('hint');
  if (!el) return;
  el.classList.remove('ok', 'err', 'warn');
  if (level) el.classList.add(level);
  el.textContent = text || '';
}

/** 生成 6 位随机字母+数字（大小写混合，去掉易混的 0O1l），用于多端区分的默认本端名称 */
function genRandomClientName() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  let s = '';
  const arr = new Uint8Array(6);
  crypto.getRandomValues(arr);
  for (const b of arr) s += chars[b % chars.length];
  return 'browser-' + s;
}

async function load() {
  const stored = await chrome.storage.local.get([
    'serverUrl', 'token', 'clientName', 'autoCloseCookies',
  ]);
  let { clientName } = stored;
  const { serverUrl, token, autoCloseCookies } = stored;
  // 没填过就自动生成一个可读的随机名，并立刻落盘保存
  if (!clientName || !clientName.trim()) {
    clientName = genRandomClientName();
    try {
      await chrome.storage.local.set({ clientName });
    } catch {}
  }
  $('serverUrl').value = serverUrl || DEFAULT_URL;
  $('token').value = token || '';
  $('clientName').value = clientName || '';
  // 默认开启，显式 false 才关闭
  $('autoCloseCookies').checked = autoCloseCookies !== false;
  refreshStatus();
}

function setStatus(connected, diag, clientName) {
  const dot = $('dot');
  const text = $('statusText');
  dot.classList.remove('on', 'off');

  if (connected === true) {
    dot.classList.add('on');
    text.textContent = clientName
      ? `已连接 (${clientName})`
      : '已连接到 Ethan Server';
    setHint('', '');
    return;
  }

  if (diag === 'connecting') {
    text.textContent = '正在连接…';
    setHint('', '');
    return;
  }

  if (diag === 'no_config') {
    dot.classList.add('off');
    text.textContent = '未配置';
    setHint('请填写 Server 地址和 Token', 'warn');
    return;
  }

  dot.classList.add('off');
  if (diag === 'auth_failed') {
    text.textContent = 'Token 错误';
    setHint('鉴权失败，请检查 Token 是否与 ethan web token 一致', 'err');
  } else if (diag === 'connection_failed') {
    text.textContent = '无法连接';
    setHint('正在诊断…', 'warn');
    void diagnoseConnection();
  } else {
    text.textContent = '未连接';
    setHint('', '');
  }
}

/** 诊断连接失败原因：尝试 HTTP 请求区分 server 没起 / 端口被占 */
async function diagnoseConnection() {
  const { serverUrl } = await chrome.storage.local.get(['serverUrl']);
  if (!serverUrl) {
    setHint('请先填写 Server 地址', 'warn');
    return;
  }
  const httpUrl = wsToHttp(serverUrl);

  try {
    const res = await fetch(httpUrl, { method: 'GET', signal: AbortSignal.timeout(3000) });
    // 能拿到 HTTP 响应说明端口有服务在监听
    const server = res.headers.get('server') || '';
    if (res.status === 404 || (!server.includes('uvicorn') && !server.includes('starlette'))) {
      setHint(`端口被其他服务占用（${res.status}），非 Ethan Server`, 'err');
    } else {
      setHint('Server 在线但 WS 连接失败，可能端口或路径不对（确认 /ws/browser）', 'err');
    }
  } catch (e) {
    const msg = String(e?.message || e);
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('ECONNREFUSED')) {
      setHint('Ethan Server 未启动，请运行 ethan serve', 'warn');
    } else if (msg.includes('timed out') || msg.includes('timeout')) {
      setHint('连接超时，检查地址/端口是否正确', 'warn');
    } else {
      setHint('连接失败: ' + msg, 'err');
    }
  }
}

async function queryConnected() {
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'getStatus' });
    if (resp && resp.error) {
      setHint('错误: ' + resp.error, 'err');
      return { connected: false, diag: 'error', clientName: '' };
    }
    return {
      connected: !!(resp && resp.connected),
      diag: resp?.diag || 'unknown',
      clientName: resp?.clientName || '',
    };
  } catch (e) {
    setHint('查询失败: ' + (e?.message || e), 'err');
    return { connected: false, diag: 'error', clientName: '' };
  }
}

// 检查 offscreen document 是否存在
async function checkOffscreen() {
  try {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'],
    });
    return contexts.length > 0;
  } catch (e) {
    return 'error: ' + (e?.message || e);
  }
}

async function refreshStatus() {
  setStatus(null, 'connecting');
  const offscreenExists = await checkOffscreen();
  if (offscreenExists !== true) {
    $('hint').textContent = 'offscreen 未创建: ' + offscreenExists;
    setStatus(false, 'connection_failed');
    return;
  }
  const { connected, diag, clientName } = await queryConnected();
  setStatus(connected, diag, clientName);
}

/** 轮询状态：重连 + 握手需要一点时间，连查几次直到连上或超时。 */
async function pollUntilConnected(tries = 12, intervalMs = 400) {
  setStatus(null, 'connecting');
  for (let i = 0; i < tries; i++) {
    const { connected, diag, clientName } = await queryConnected();
    if (connected) {
      setStatus(true, 'connected', clientName);
      return;
    }
    // auth_failed 不需要重试，直接显示
    if (diag === 'auth_failed') {
      setStatus(false, diag);
      return;
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
  // 超时后最后查一次状态
  const { connected, diag, clientName } = await queryConnected();
  setStatus(connected, diag || 'connection_failed', clientName);
}

/** 当前输入值写入 storage。storage.onChanged 会触发 background 自动重连。 */
async function persist() {
  await chrome.storage.local.set({
    serverUrl: $('serverUrl').value.trim() || DEFAULT_URL,
    token: $('token').value.trim(),
    clientName: $('clientName').value.trim(),
  });
}

// 输入即自动保存（防抖）——不用再点保存按钮。
let saveTimer = null;
function autoSave() {
  if (saveTimer) clearTimeout(saveTimer);
  $('hint').textContent = '';
  saveTimer = setTimeout(async () => {
    await persist();
    $('hint').textContent = '已自动保存';
    setTimeout(() => { $('hint').textContent = ''; }, 1500);
  }, 500);
}

// 「测试连接」：立即落库 + 强制重连 + 轮询状态。
async function testConnect() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  await persist();
  await chrome.runtime.sendMessage({ type: 'reconnect' }).catch(() => {});
  await pollUntilConnected();
}

$('serverUrl').addEventListener('input', autoSave);
$('token').addEventListener('input', autoSave);
$('clientName').addEventListener('input', autoSave);
$('connect').addEventListener('click', testConnect);
$('reading').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || tab.url?.startsWith('chrome://') || tab.url?.startsWith('chrome-extension://') || tab.url?.startsWith('about:')) {
    $('hint').textContent = '当前页面不支持阅读模式';
    return;
  }
  $('hint').textContent = '正在进入阅读模式…';
  const resp = await chrome.runtime.sendMessage({ type: 'reading:start', tabId: tab.id });
  if (resp?.ok) {
    window.close();
  } else {
    $('hint').textContent = resp?.error || '注入失败，页面不支持';
  }
});
$('autoCloseCookies').addEventListener('change', async (e) => {
  await chrome.storage.local.set({ autoCloseCookies: e.target.checked });
});

// 页面指令列表：读 commands 渲染成按钮，点击 → 后台执行，结果进页面右上角面板。
async function renderCommands() {
  const list = $('commandList');
  if (!list) return;
  const commands = await readCommands();
  list.innerHTML = '';
  for (const cmd of commands) {
    const btn = document.createElement('button');
    btn.className = 'cmd-btn';
    btn.title = cmd.scope === 'selection' ? '对当前选中文字执行' : '对当前页面执行';

    const iconSpan = document.createElement('span');
    iconSpan.className = 'cmd-icon';
    iconSpan.textContent = cmd.icon || '';
    const labelSpan = document.createElement('span');
    labelSpan.className = 'cmd-label';
    labelSpan.textContent = cmd.label || '';

    btn.appendChild(iconSpan);
    btn.appendChild(labelSpan);
    btn.addEventListener('click', () => runCommand(cmd));
    list.appendChild(btn);
  }
}

async function runCommand(cmd) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || tab.url?.startsWith('chrome://') || tab.url?.startsWith('chrome-extension://') || tab.url?.startsWith('about:')) {
    setHint('当前页面不支持', 'err');
    return;
  }
  // 「全文翻译」会把整页发给模型，token 消耗大：二次确认，用户取消就中止。
  if (cmd && cmd.id === 'translate' && cmd.scope === 'page') {
    const ok = window.confirm(
      '全文翻译会把当前页面整页内容发送给模型，可能消耗较多 Token。\n\n是否继续？',
    );
    if (!ok) {
      setHint('已取消', 'warn');
      return;
    }
  }
  const resp = await chrome.runtime.sendMessage({ type: 'run-command', commandId: cmd.id, tabId: tab.id });
  if (resp?.ok) {
    window.close();
  } else {
    setHint(resp?.error || '执行失败', 'err');
  }
}

$('manageCommands')?.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

load();
renderCommands();
