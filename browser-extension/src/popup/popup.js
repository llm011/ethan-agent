/* eslint-disable */
const $ = id => document.getElementById(id);

async function load() {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  $('serverUrl').value = serverUrl || 'ws://localhost:8900/ws/browser';
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

async function refreshStatus() {
  setStatus(null);
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'getStatus' });
    setStatus(!!(resp && resp.connected));
  } catch {
    setStatus(false);
  }
}

async function save() {
  const serverUrl = $('serverUrl').value.trim();
  const token = $('token').value.trim();
  await chrome.storage.local.set({ serverUrl, token });
  $('saved').textContent = '已保存，正在重连…';
  // 配置变更后 background 会自动重连；稍候刷新状态
  setTimeout(() => {
    $('saved').textContent = '';
    refreshStatus();
  }, 1200);
}

async function reconnect() {
  await chrome.runtime.sendMessage({ type: 'reconnect' });
  $('saved').textContent = '已触发重连…';
  setTimeout(() => {
    $('saved').textContent = '';
    refreshStatus();
  }, 1200);
}

$('save').addEventListener('click', save);
$('reconnect').addEventListener('click', reconnect);
load();
