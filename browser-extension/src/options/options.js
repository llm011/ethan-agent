/* eslint-disable */
async function load() {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  document.getElementById('serverUrl').value = serverUrl || 'ws://localhost:8900/ws/browser';
  document.getElementById('token').value = token || '';
}

async function save() {
  const serverUrl = document.getElementById('serverUrl').value.trim();
  const token = document.getElementById('token').value.trim();
  await chrome.storage.local.set({ serverUrl, token });
  const s = document.getElementById('status');
  s.textContent = '已保存，扩展将立即重连';
  setTimeout(() => (s.textContent = ''), 2000);
}

document.getElementById('save').addEventListener('click', save);
load();
