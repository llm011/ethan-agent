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
    'transition: opacity 0.3s',
  ].join(';');

  // 标题栏
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
  ].join(';');
  header.innerHTML = '<span style="font-size: 14px;">🦊</span> Ethan Agent';

  // 步骤列表容器
  const list = document.createElement('div');
  list.id = OVERLAY_ID + '_list';
  list.style.cssText = [
    'flex: 1',
    'overflow-y: auto',
    'padding: 4px 0',
    'min-height: 0',
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
  return host;
}

function getOrCreateOverlay(): HTMLElement {
  return document.getElementById(OVERLAY_ID) || createOverlay();
}

function formatStepLabel(action: string, data: Record<string, unknown>): string {
  const ref = data.ref ? ` [${data.ref}]` : '';
  const text = data.text ? ` "${String(data.text).slice(0, 40)}"` : '';
  const key = data.key ? ` ${data.key}` : '';
  const direction = data.direction ? ` ${data.direction}` : '';
  const what = data.what ? ` ${data.what}` : '';
  const selector = data.selector ? ` ${String(data.selector).slice(0, 40)}` : '';

  const labels: Record<string, string> = {
    snapshot: '快照页面',
    click: `点击${ref}`,
    fill: `填写${ref}${text}`,
    type: `输入${ref}${text}`,
    press: `按键${key}`,
    hover: `悬停${ref}`,
    select: `选择${ref}`,
    scroll: `滚动${direction}`,
    scroll_into_view: `滚入视口${ref}`,
    screenshot: '截图',
    get: `读取${what}${ref}`,
    mouse: '鼠标操作',
    wait: '等待',
    eval: '执行脚本',
    upload: `上传${ref}`,
    save_pdf: '保存 PDF',
    click_selector: `点击${selector}`,
    fill_selector: `填写${selector}${text}`,
    hover_selector: `悬停${selector}`,
    wait_for_element: `等待元素${selector}`,
    scroll_to_text: `滚动到"${text}"`,
    extract_content: '提取内容',
    find_elements: `查找元素${selector}`,
    find_attributes: `查找属性${selector}`,
    check_exist: `检查存在${selector}`,
    input_enter: `输入并回车${selector}${text}`,
    scroll_find: `滚动查找${selector}`,
    click_vlm: `视觉点击`,
    network_start: '开始抓包',
    network_stop: '停止抓包',
  };
  return labels[action] || action;
}

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

  item.appendChild(icon);
  item.appendChild(textSpan);
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
    }
    return false;
  });
}

export {};
