/* eslint-disable */
// 浮层注入器：负责把 content/overlay.ts 注入到目标 tab，并推送步骤消息。
//
// page-controller 每次执行页面操作时调用 pushStep()，本模块负责：
//   1. 确保浮层已注入到该 tab（lazy inject，每 tab 只注入一次）
//   2. 发送 addStep / updateStep 消息

// 记录哪些 tab 已经注入过浮层，避免重复注入
const injectedTabs = new Set<number>();

// 页面导航/刷新后需要重新注入
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'loading' && injectedTabs.has(tabId)) {
    injectedTabs.delete(tabId);
  }
});

chrome.tabs.onRemoved.addListener(tabId => {
  injectedTabs.delete(tabId);
});

async function ensureInjected(tabId: number): Promise<void> {
  if (injectedTabs.has(tabId)) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/overlay.js'],
    });
    injectedTabs.add(tabId);
  } catch {
    // 某些页面（chrome://, chrome-extension://）无法注入，静默忽略
  }
}

/** 推送一个步骤到浮层，返回步骤 timestamp（用于后续状态更新） */
export async function pushStep(
  tabId: number,
  action: string,
  data: Record<string, unknown>,
): Promise<number | null> {
  await ensureInjected(tabId);
  const timestamp = Date.now();
  const label = formatLabel(action, data);
  try {
    await chrome.tabs.sendMessage(tabId, {
      target: 'overlay',
      type: 'addStep',
      entry: { action, label, timestamp, status: 'running' },
    });
    return timestamp;
  } catch {
    // 页面可能还没准备好，忽略
    return null;
  }
}

/** 更新步骤状态 */
export async function updateStepStatus(
  tabId: number,
  timestamp: number,
  status: 'done' | 'error',
): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, {
      target: 'overlay',
      type: 'updateStep',
      timestamp,
      status,
    });
  } catch {
    // 忽略
  }
}

/** 清除某 tab 的所有步骤 */
export async function clearSteps(tabId: number): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, { target: 'overlay', type: 'clearSteps' });
  } catch {}
}

/** 移除某 tab 的浮层 */
export async function removeOverlay(tabId: number): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, { target: 'overlay', type: 'removeOverlay' });
  } catch {}
  injectedTabs.delete(tabId);
}

function formatLabel(action: string, data: Record<string, unknown>): string {
  const ref = data.ref ? ` [${data.ref}]` : '';
  const text = typeof data.text === 'string' ? ` "${String(data.text).slice(0, 20)}"` : '';
  const key = typeof data.key === 'string' ? ` ${data.key}` : '';
  const direction = typeof data.direction === 'string' ? ` ${data.direction}` : '';
  const what = typeof data.what === 'string' ? ` ${data.what}` : '';
  const selector = typeof data.selector === 'string' ? ` ${String(data.selector).slice(0, 20)}` : '';
  const xpath = typeof data.xpath === 'string' ? ` xpath:${String(data.xpath).slice(0, 20)}` : '';
  const ms = typeof data.ms === 'number' && data.ms ? ` ${data.ms}ms` : '';
  const load = typeof data.load === 'string' ? ` ${data.load}` : '';
  const prompt = typeof data.prompt === 'string' ? ` "${String(data.prompt).slice(0, 20)}"` : '';
  const attributes = Array.isArray(data.attributes)
    ? ` ${(data.attributes as string[]).slice(0, 3).join('/')}` : '';
  const nth = typeof data.nth === 'number' ? ` #${data.nth}` : '';

  // eval: 从脚本内容推断做了什么，给一个简短提示
  let evalHint = '';
  {
    const script = typeof data.script === 'string' ? data.script : '';
    if (script) {
      if (/\.click\s*\(/.test(script)) evalHint = ' (点击元素)';
      else if (/\.value\s*=/.test(script)) evalHint = ' (设值)';
      else if (/scroll/.test(script)) evalHint = ' (滚动)';
      else if (/querySelector/.test(script) && !evalHint) evalHint = ' (查询)';
      else if (/fetch\s*\(/.test(script)) evalHint = ' (取数)';
      else if (script.length < 30) evalHint = ` (${script.slice(0, 12)})`;
    }
  }

  // mouse: 显示动作名 + 坐标（若有）
  let mouseLabel = '鼠标操作';
  {
    const a = typeof data.action === 'string' ? ` ${data.action}` : '';
    const x = typeof data.x === 'number' ? Math.round(data.x) : null;
    const y = typeof data.y === 'number' ? Math.round(data.y) : null;
    const coord = x != null && y != null ? ` (${x},${y})` : '';
    if (a || coord) mouseLabel = `鼠标${a || '操作'}${coord}`;
  }

  // wait: 智能组合 ms / load / selector 等
  let waitLabel = '等待';
  {
    const parts: string[] = [];
    if (ms) parts.push(String(ms).trim());
    if (load) parts.push(String(load).trim());
    if (selector) parts.push(String(selector).trim());
    if (xpath) parts.push(String(xpath).trim());
    if (parts.length) waitLabel = `等待${parts.join(' ')}`;
  }

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
    mouse: mouseLabel,
    wait: waitLabel,
    eval: `执行脚本${evalHint}`,
    upload: `上传${ref}`,
    save_pdf: '保存 PDF',
    click_selector: `点击${selector || xpath}${nth}${text}`,
    fill_selector: `填写${selector || xpath}${text}`,
    hover_selector: `悬停${selector || xpath}`,
    wait_for_element: `等待元素${selector || xpath}`,
    scroll_to_text: `滚动到${text}`,
    extract_content: `提取内容${selector}`,
    find_elements: `查找元素${selector}`,
    find_attributes: `查找属性${selector}${attributes}`,
    check_exist: `检查存在${selector || xpath}`,
    input_enter: `输入并回车${selector}${text}`,
    scroll_find: `滚动查找${selector}`,
    click_vlm: `视觉点击${prompt}`,
    network_start: '开始抓包',
    network_stop: '停止抓包',
  };
  return labels[action] || action;
}
