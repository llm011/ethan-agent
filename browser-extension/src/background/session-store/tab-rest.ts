/**
 * 「让 tab 休息」(discard) 的判据。
 *
 * discard 的语义：释放渲染进程内存，标题/位置/分组留在标签栏，用户点开时
 * Chrome 按原 URL 重新加载。代价是**页面状态会没**（填到一半的表单、滚动位置、
 * SPA 登录态、暂停的视频）。
 *
 * 因为代价不可逆、收益只是省内存，这里所有判据都朝「更保守」偏：
 * 拿不准就不动。判断逻辑写成纯函数，便于单测钉住 —— 判错一次就是用户丢数据。
 */
import type { BrowserTabRestMode } from '../../shared';

/** 我们关心的、来自 chrome.tabs.Tab 的那部分字段。 */
export interface RestCandidateTab {
  id?: number;
  url?: string;
  title?: string;
  active?: boolean;
  audible?: boolean;
  pinned?: boolean;
  discarded?: boolean;
  autoDiscardable?: boolean;
  groupId?: number;
}

/** 不休息的原因，可预期的那一类。 */
export type RestSkipReason =
  | 'already-discarded'
  | 'active-tab'
  | 'audible'
  | 'pinned'
  | 'auto-discard-disabled'
  | 'unsupported-scheme'
  | 'protected-url'
  | 'live-session-tab'
  | 'opened-today';

/**
 * 按 URL / scheme 判断这个 tab 不该被碰。
 *
 * 这些页面要么本来就不占多少内存，要么 discard 会带来奇怪的后果：
 * - chrome:// / about: / devtools:// 等内部页：扩展本来也不该动
 * - file://：本地文件，可能是正在看的文档
 * - localhost / 127.0.0.1：多半挂着本地 dev server，重新加载会丢调试态
 */
export function isProtectedUrl(url: string | undefined): boolean {
  if (!url) return false;
  const u = url.toLowerCase();
  if (
    u.startsWith('chrome://') ||
    u.startsWith('chrome-extension://') ||
    u.startsWith('chrome-untrusted://') ||
    u.startsWith('about:') ||
    u.startsWith('devtools://') ||
    u.startsWith('edge://') ||
    u.startsWith('brave://')
  ) {
    return true;
  }
  if (u.startsWith('file://')) return true;
  return isLocalhostUrl(u);
}

/**
 * 是否是本地服务地址。
 *
 * 必须比对**主机名**而不是前缀：`https://localhost.example.com` 是正常公网域名，
 * 用 startsWith('https://localhost') 会把它误判成本地服务（虽然方向偏保守，
 * 但会让一个正常网站永远不休息，不对）。
 */
function isLocalhostUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  // URL.hostname 对 IPv6 会保留方括号（"[::1]"），去掉再比。
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return true;
  if (host.endsWith('.localhost')) return true;
  // 整个 127.0.0.0/8 都是回环段
  if (/^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  return false;
}

export interface RestDecisionInput {
  tab: RestCandidateTab;
  /** 该 tab 的打开时间（ms epoch）；无记录时由调用方用 lastAccessed 兜底。 */
  openedAt?: number;
  /** 今天的本地零点（ms epoch）。 */
  startOfToday: number;
  /** 活跃 Ethan session 账本里的 tab（正在被自动化操作，绝不能 discard）。 */
  liveSessionTabIds: Set<number>;
  /** 已挂 CDP 的 tab（discard 会中途 detach，打断正在跑的操作）。 */
  cdpAttachedTabIds: Set<number>;
  /**
   * 是否应用「今天打开的就不动」这条时间判据。
   *
   * 自动模式（rest_auto）为 true；用户显式点名（rest / rest_group）为 false ——
   * 那时「今天打开」不是拒绝理由，用户说了算。
   *
   * 用独立的布尔量而不是把 startOfToday 压成 -Infinity 之类的哨兵值：
   * 那种写法会被 `openedAt === undefined` 那条早退绕过（没有记录时照样判成
   * 「今天」），显式点名就失效了。
   */
  enforceRecency: boolean;
}

/**
 * 判定单个 tab 是否可以休息。
 *
 * 返回 `null` 表示「可以」；否则返回不休息的原因。
 * 顺序有意为之：先判绝对禁止的（活跃/出声/正在被操作），再判按规则不该动的。
 */
export function decideRest(
  input: RestDecisionInput,
): RestSkipReason | null {
  const {
    tab,
    openedAt,
    startOfToday,
    liveSessionTabIds,
    cdpAttachedTabIds,
    enforceRecency,
  } = input;
  const id = tab.id;

  if (typeof id !== 'number') return 'protected-url';
  if (tab.discarded) return 'already-discarded';
  // 正在看的那个：discard 会当场触发重新加载，等于打断用户。
  if (tab.active) return 'active-tab';
  // 出声的：可能在放视频/开会。
  if (tab.audible) return 'audible';
  // 用户手动固定的：说明在意，保持常驻。
  if (tab.pinned) return 'pinned';
  // 用户/浏览器显式关掉了自动 discard，尊重它。
  if (tab.autoDiscardable === false) return 'auto-discard-disabled';
  // 正在被 Ethan 操作的：discard 会打断自动化流程。
  if (liveSessionTabIds.has(id) || cdpAttachedTabIds.has(id)) {
    return 'live-session-tab';
  }
  if (isProtectedUrl(tab.url)) return 'protected-url';
  // 时间判据（只在自动模式下生效）：今天的先不动。
  // openedAt 缺失时按「今天」算 —— 拿不到证据就别动手，方向保守。
  if (enforceRecency && (openedAt === undefined || openedAt >= startOfToday)) {
    return 'opened-today';
  }

  return null;
}

/** 本地时区下「今天零点」的毫秒时间戳。 */
export function startOfLocalDay(now: number): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/**
 * 该不该做「按时间自动休息」。
 *
 * 默认开启（`yesterday`），扩展设置里可以关掉。关掉后只有显式的
 * `rest` / `rest_group` op 才动手。
 */
export function shouldAutoRest(mode: BrowserTabRestMode | undefined): boolean {
  return (mode ?? 'yesterday') !== 'off';
}
