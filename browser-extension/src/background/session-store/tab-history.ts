/**
 * 「已关闭的 tab」（历史）与当前已打开 tab 的合并、去重。
 *
 * 数据源是 `chrome.sessions.getRecentlyClosed()` —— 它返回的就是「最近关闭的
 * tab/窗口」，正好对应「已被关掉的页面」这个语义（比 chrome.history 更贴切：
 * history 是「访问过的 URL」，包含没开成 tab 的页面，还要额外申请 history
 * 权限并触发更重的安装警告）。
 *
 * 本模块是纯函数（不碰 chrome API），方便单测。
 */
import { clampLimit, searchTabs } from './tab-search';
import type {
  BrowserSessionTab,
  BrowserTabSearchMatch,
  BrowserTabSearchParams,
  BrowserTabSearchResult,
} from '../../shared';

/** 一条已关闭的 tab —— 在 BrowserSessionTab 基础上带上关闭时间。 */
export interface ClosedTabEntry {
  tab: BrowserSessionTab;
  /** 关闭时间（毫秒时间戳）。来源见 normalizeClosedAt 对 lastModified 单位的处理。 */
  closedAt: number;
}

/**
 * 把 `sessions.Session.lastModified` 归一成**毫秒**时间戳。
 *
 * 这个字段的单位有分歧：Chrome 官方文档写的是「seconds since the epoch」，
 * 而 `@types/chrome` 的类型注释写的是 milliseconds。猜错一边的后果是「只搜今天」
 * 直接失效（按秒当毫秒会算成 1970 年，一条都留不下；按毫秒当秒会溢出到遥远的未来，
 * 昨天的也全算今天）——而且不会报错，只是搜不到历史，很难发现。
 *
 * 所以这里不赌单位，用量级判断：当前时间戳在秒级约 1.7e9、毫秒级约 1.7e12。
 * 1e11 这个分界落在两者之间且远离任何一边，足以区分。
 */
export function normalizeClosedAt(lastModified: number | undefined): number {
  if (typeof lastModified !== 'number' || !Number.isFinite(lastModified) || lastModified <= 0) {
    return 0;
  }
  return lastModified < 1e11 ? lastModified * 1000 : lastModified;
}

/** 把 URL 归一化成去重键：忽略 hash，去掉末尾斜杠差异。 */
export function dedupeKey(url: string | undefined): string {
  if (!url) return '';
  try {
    const u = new URL(url);
    u.hash = '';
    // 末尾斜杠：https://a.com/ 与 https://a.com 视为同一页
    let s = u.toString();
    if (s.endsWith('/') && u.pathname === '/') s = s.slice(0, -1);
    return s;
  } catch {
    // 非标准 URL（chrome://、about: 等）原样比对
    return url;
  }
}

/**
 * 去掉「当前还开着」的已关闭条目。
 *
 * 按 URL 去重（忽略 hash）：同一个 URL 只要现在还开在任意一个 tab 里，
 * 就不该出现在「已关闭」结果里——用户要的是「刚才关掉了、现在能找回来的」。
 */
export function excludeOpenTabs(
  closed: ClosedTabEntry[],
  openTabs: BrowserSessionTab[],
): ClosedTabEntry[] {
  const open = new Set<string>();
  for (const t of openTabs) {
    const k = dedupeKey(t.url);
    if (k) open.add(k);
  }
  const seen = new Set<string>();
  const out: ClosedTabEntry[] = [];
  for (const c of closed) {
    const k = dedupeKey(c.tab.url);
    if (!k) continue;
    if (open.has(k)) continue;
    // 同一条历史也可能重复出现（同 URL 关了又关），只留最近一次
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(c);
  }
  return out;
}

/** 只保留「今天」关闭的条目（本地时区）。 */
export function filterToday(
  closed: ClosedTabEntry[],
  now: number = Date.now(),
): ClosedTabEntry[] {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const startMs = start.getTime();
  return closed.filter(c => c.closedAt >= startMs);
}

/** 合并搜索结果里的一条，附上来源标记。 */
export interface MergedMatch extends BrowserTabSearchMatch {
  /** 'open' = 当前还开着；'closed' = 历史（已关闭）。 */
  source: 'open' | 'closed';
  /** 仅 closed：关闭时间（毫秒）。 */
  closedAt?: number;
}

export interface MergedSearchResult {
  query: string;
  total: number;
  scanned: number;
  truncated: boolean;
  matches: MergedMatch[];
}

/**
 * 在「当前已打开的 tab」+（可选）「今天关闭的 tab」里搜索。
 *
 * includeClosed 打开时才查历史；两批结果各自排序后按分数归并，
 * 保证「还开着的」和「关掉的」混合时仍然按相关度排，而不是先一堆开着的、
 * 再一堆关掉的。同分时**开着的优先**——用户多半想找还开着的那个。
 */
export function searchTabsWithHistory(
  openTabs: BrowserSessionTab[],
  closedTabs: ClosedTabEntry[],
  params: BrowserTabSearchParams,
  groups: Map<number, { title?: string; color?: string }> = new Map(),
  now: number = Date.now(),
): MergedSearchResult {
  const openResult: BrowserTabSearchResult = searchTabs(openTabs, params, groups);

  if (!params.includeClosed) {
    return {
      query: openResult.query,
      total: openResult.total,
      scanned: openResult.scanned,
      truncated: openResult.truncated,
      matches: openResult.matches.map(m => ({ ...m, source: 'open' as const })),
    };
  }

  // 历史只取今天关闭的，且不与当前开着的重复
  const candidates = filterToday(excludeOpenTabs(closedTabs, openTabs), now);
  const closedTabsOnly = candidates.map(c => c.tab);
  const closedResult = searchTabs(closedTabsOnly, params, groups);

  // 用 URL 回填关闭时间（searchTabs 的返回里没有这个字段）
  const closedAtByKey = new Map<string, number>();
  for (const c of candidates) {
    const k = dedupeKey(c.tab.url);
    if (k && !closedAtByKey.has(k)) closedAtByKey.set(k, c.closedAt);
  }

  const merged: MergedMatch[] = [
    ...openResult.matches.map(m => ({ ...m, source: 'open' as const })),
    ...closedResult.matches.map(m => {
      const k = dedupeKey(m.tab.url);
      const at = closedAtByKey.get(k);
      return {
        ...m,
        source: 'closed' as const,
        ...(typeof at === 'number' ? { closedAt: at } : {}),
      };
    }),
  ];

  // 归并排序：命中词数 → 分数 → 还开着的优先。
  // 复用 searchTabs 的排序口径，这里只补最后一层 tie-break。
  merged.sort((a, b) => {
    const ka = a.matchedKeywords.length;
    const kb = b.matchedKeywords.length;
    if (kb !== ka) return kb - ka;
    if (b.score !== a.score) return b.score - a.score;
    if (a.source !== b.source) return a.source === 'open' ? -1 : 1;
    return a.tab.tabId - b.tab.tabId;
  });

  // 截断在**合并之后**按同一个 limit 做。
  // 不能沿用两批各自的 matches 长度：那样等于把上限翻倍（两批各留 limit 条），
  // 面板会一次列出 2×limit 行，而面板要限高滚动。
  const matches = merged.slice(0, clampLimit(params.limit));

  return {
    query: openResult.query,
    total: openResult.total + closedResult.total,
    scanned: openResult.scanned + closedResult.scanned,
    // 只看合并后的总数够不够撑满 limit，两批各自的 truncated 在这里没有意义
    truncated: merged.length > matches.length,
    matches,
  };
}
