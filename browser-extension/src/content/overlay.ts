/* eslint-disable */
// 页面右上角步骤浮层：竖向长条框，列出 agent 的每一步操作。
// 固定高度，超出滚动，动态变化。由 background 通过 chrome.tabs.sendMessage 推送步骤。
//
// 注入方式：page-controller 每次执行页面操作后，调 chrome.scripting.executeScript
// 确保浮层已注入，再 chrome.tabs.sendMessage 推送步骤数据。

interface StepEntry {
  action: string;       // click / fill / type / snapshot ...
  label: string;        // 人类可读描述
  timestamp: number;
  status: 'running' | 'done' | 'error';
}

const OVERLAY_ID = '__ethan_browser_overlay__';
const MAX_STEPS = 200;

// 防重复注入
function overlayExists(): boolean {
  return !!document.getElementById(OVERLAY_ID);
}

function createOverlay(): HTMLElement {
  const host = document.createElement('div');
  host.id = OVERLAY_ID;
  host.style.cssText = [
    'position: fixed',
    'top: 16px',
    'right: 16px',
    'width: 280px',
    'max-height: 400px',
    'display: flex',
    'flex-direction: column',
    'z-index: 2147483647',
    'font-family: -apple-system, system-ui, "PingFang SC", sans-serif',
    'font-size: 12px',
    'color: #1f2430',
    'background: rgba(255, 255, 255, 0.96)',
    'border: 1px solid rgba(0, 0, 0, 0.12)',
    'border-radius: 10px',
    'box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15)',
    'backdrop-filter: blur(8px)',
    'pointer-events: auto',
    'transition: max-height 0.2s ease, opacity 0.3s',
  ].join(';');

  // 标题栏（点击可折叠列表）
  const header = document.createElement('div');
  header.style.cssText = [
    'display: flex',
    'align-items: center',
    'gap: 6px',
    'padding: 8px 12px',
    'border-bottom: 1px solid rgba(0, 0, 0, 0.08)',
    'font-weight: 600',
    'font-size: 13px',
    'flex-shrink: 0',
    'cursor: pointer',
    'user-select: none',
  ].join(';');
  header.innerHTML =
    '<span style="font-size: 14px;">🦊</span> Ethan Agent' +
    '<span id="' + OVERLAY_ID + '_chevron" style="margin-left:auto;transition:transform 0.2s;font-size:12px;opacity:0.6">▼</span>';

  // 步骤列表容器
  const list = document.createElement('div');
  list.id = OVERLAY_ID + '_list';
  list.style.cssText = [
    'flex: 1',
    'overflow-y: auto',
    'padding: 4px 0',
    'min-height: 0',
    'transition: flex 0.2s ease, min-height 0.2s ease, padding 0.2s ease',
  ].join(';');

  // 自定义滚动条样式
  const style = document.createElement('style');
  style.textContent = `
    #${OVERLAY_ID}_list::-webkit-scrollbar { width: 4px; }
    #${OVERLAY_ID}_list::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.2); border-radius: 2px; }
    #${OVERLAY_ID}_list::-webkit-scrollbar-track { background: transparent; }
  `;

  host.appendChild(header);
  host.appendChild(list);
  document.documentElement.appendChild(style);
  document.documentElement.appendChild(host);

  // 点击 header 折叠/展开列表
  let collapsed = false;
  header.onclick = () => {
    collapsed = !collapsed;
    const chevron = document.getElementById(OVERLAY_ID + '_chevron') as HTMLElement | null;
    if (collapsed) {
      list.style.flex = '0 0 0px';
      list.style.minHeight = '0';
      list.style.padding = '0';
      list.style.overflow = 'hidden';
      list.style.opacity = '0';
      if (chevron) chevron.style.transform = 'rotate(-90deg)';
      host.style.maxHeight = 'none';
    } else {
      list.style.flex = '1';
      list.style.minHeight = '0';
      list.style.padding = '4px 0';
      list.style.overflow = 'auto';
      list.style.opacity = '1';
      if (chevron) chevron.style.transform = 'rotate(0deg)';
      host.style.maxHeight = '400px';
    }
  };

  return host;
}

function getOrCreateOverlay(): HTMLElement {
  return document.getElementById(OVERLAY_ID) || createOverlay();
}

// 注：步骤标签由 background 侧的 overlay-injector.formatLabel 统一生成后随 addStep 消息传入
// （见 entry.label）。此处不再重复实现，避免两份 label 逻辑漂移。

function addStep(entry: StepEntry) {
  const overlay = getOrCreateOverlay();
  const list = document.getElementById(OVERLAY_ID + '_list');
  if (!list) return;

  // 限制最大步骤数
  while (list.children.length >= MAX_STEPS) {
    list.removeChild(list.firstChild!);
  }

  const item = document.createElement('div');
  item.dataset.stepId = entry.timestamp.toString();
  item.style.cssText = [
    'display: flex',
    'align-items: flex-start',
    'gap: 6px',
    'padding: 5px 12px',
    'border-bottom: 1px solid rgba(0, 0, 0, 0.04)',
    'line-height: 1.4',
  ].join(';');

  const icon = document.createElement('span');
  icon.style.cssText = 'flex-shrink: 0; width: 14px; text-align: center; font-size: 11px;';
  icon.textContent = '○';
  icon.style.color = '#6b7280';

  const textSpan = document.createElement('span');
  textSpan.style.cssText = 'flex: 1; word-break: break-word; color: #374151;';
  textSpan.textContent = entry.label;

  const timeSpan = document.createElement('span');
  const d = new Date(entry.timestamp);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  timeSpan.textContent = `${hh}:${mm}:${ss}`;
  timeSpan.style.cssText = 'flex-shrink: 0; font-size: 10px; color: #9ca3af; margin-left: 4px; line-height: 1.4;';

  item.appendChild(icon);
  item.appendChild(textSpan);
  item.appendChild(timeSpan);
  list.appendChild(item);

  // 自动滚动到底部
  list.scrollTop = list.scrollHeight;
}

function updateStepStatus(timestamp: number, status: 'done' | 'error') {
  const list = document.getElementById(OVERLAY_ID + '_list');
  if (!list) return;
  const item = list.querySelector(`[data-step-id="${timestamp}"]`);
  if (!item) return;
  const icon = item.querySelector('span');
  if (!icon) return;
  if (status === 'done') {
    icon.textContent = '✓';
    icon.style.color = '#16a34a';
  } else if (status === 'error') {
    icon.textContent = '✗';
    icon.style.color = '#dc2626';
  }
}

function clearSteps() {
  const list = document.getElementById(OVERLAY_ID + '_list');
  if (list) list.innerHTML = '';
}

function removeOverlay() {
  const el = document.getElementById(OVERLAY_ID);
  if (el) el.remove();
}

function toggleOverlay() {
  const el = document.getElementById(OVERLAY_ID);
  if (el) {
    el.remove();
  } else {
    createOverlay();
  }
}

// 监听来自 background 的消息
const w = window as any;
if (!w.__ethanOverlayListenerAdded) {
  w.__ethanOverlayListenerAdded = true;
  chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
    if (msg?.target !== 'overlay') return;
    if (msg.type === 'addStep') {
      addStep(msg.entry);
    } else if (msg.type === 'updateStep') {
      updateStepStatus(msg.timestamp, msg.status);
    } else if (msg.type === 'clearSteps') {
      clearSteps();
    } else if (msg.type === 'removeOverlay') {
      removeOverlay();
    } else if (msg.type === 'toggleOverlay') {
      toggleOverlay();
    }
    return false;
  });
}

export {};
