/* eslint-disable */
const $ = id => document.getElementById(id);

const DEFAULT_URL = 'ws://localhost:8900/ws/browser';

async function load() {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  $('serverUrl').value = serverUrl || DEFAULT_URL;
  $('token').value = token || '';
  refreshStatus();
}

function setStatus(connected) {
  const dot = $('dot');
  const text = $('statusText');
  dot.classList.remove('on', 'off');
  if (connected === true) {
    dot.classList.add('on');
    text.textContent = '已连接到 Ethan Server';
  } else if (connected === false) {
    dot.classList.add('off');
    text.textContent = '未连接（检查地址/Token 或 ethan 是否启动）';
  } else {
    text.textContent = '检查连接中…';
  }
}

async function queryConnected() {
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'getStatus' });
    if (resp && resp.error) {
      $('hint').textContent = '错误: ' + resp.error;
    }
    return !!(resp && resp.connected);
  } catch (e) {
    $('hint').textContent = '查询失败: ' + (e?.message || e);
    return false;
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
  setStatus(null);
  const offscreenExists = await checkOffscreen();
  if (offscreenExists !== true) {
    $('hint').textContent = 'offscreen 未创建: ' + offscreenExists;
    setStatus(false);
    return;
  }
  const connected = await queryConnected();
  if (connected) {
    $('hint').textContent = '';
  }
  setStatus(connected);
}

/** 轮询状态：重连 + 握手需要一点时间，连查几次直到连上或超时。 */
async function pollUntilConnected(tries = 12, intervalMs = 400) {
  setStatus(null);
  for (let i = 0; i < tries; i++) {
    if (await queryConnected()) {
      setStatus(true);
      return;
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
  setStatus(false);
}

/** 当前输入值写入 storage。storage.onChanged 会触发 background 自动重连。 */
async function persist() {
  await chrome.storage.local.set({
    serverUrl: $('serverUrl').value.trim() || DEFAULT_URL,
    token: $('token').value.trim(),
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
$('connect').addEventListener('click', testConnect);
load();
