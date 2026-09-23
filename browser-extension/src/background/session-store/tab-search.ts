/**
 * tab 关键词匹配：纯函数，不碰 chrome API，方便单测。
 *
 * 语义（与 shared/types.ts 的 BrowserTabSearchParams 注释一致）：
 *   - query 以空格切词，**任一命中即算匹配**（OR）；
 *   - 大小写不敏感；
 *   - title 命中权重高于 url 命中，完全匹配 > 前缀 > 子串；
 *   - 按 (命中词数, 分数) 降序排；
 *   - 同分时活着的/活动的 tab 靠前，让 agent 少一轮来回。
 */
import type {
  BrowserSessionTab,
  BrowserTabSearchMatch,
  BrowserTabSearchParams,
  BrowserTabSearchResult,
} from '../../shared';

const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 50;

/** 各字段的命中权重。title 是用户识别页面的主要线索，给更高权重。 */
const WEIGHT_TITLE = 3;
const WEIGHT_URL = 1;

/** 匹配质量加成：整词完全相等 > 前缀 > 子串。 */
const BONUS_EXACT = 100;
const BONUS_PREFIX = 40;
const BONUS_SUBSTRING = 0;

/** groupId 为 -1（chrome.tabGroups.TAB_GROUP_ID_NONE）时视为「不在任何分组」。 */
const TAB_GROUP_ID_NONE = -1;

export function parseKeywords(query: string | undefined): string[] {
  if (!query) {
    return [];
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of query.toLowerCase().split(/\s+/)) {
    if (!raw) {
      continue;
    }
    if (seen.has(raw)) {
      continue;
    }
    seen.add(raw);
    out.push(raw);
  }
  return out;
}

/**
 * 单个关键词在单个字段里的得分。null 表示**没命中**。
 *
 * 注意返回 null 而不是 0：子串命中的加成是 0 分（BONUS_SUBSTRING），
 * 若用 0 兼作「未命中」的哨兵，`github.com` 里搜 `hub`（子串）就会被当成没命中，
 * 白白漏掉候选。命中与否必须和得分高低分开表达。
 *
 * 用「词边界」判完全匹配/前缀匹配而不是裸 includes：搜 "hub" 时
 * github.com 只能拿子串分，而 hub.docker.com 能拿前缀分——避免
 * 把所有含子串的域名都当成同等相关。
 */
function scoreField(field: string, keyword: string): number | null {
  const lower = field.toLowerCase();
  const idx = lower.indexOf(keyword);
  if (idx === -1) {
    return null;
  }

  // 词边界：字段开头，或前一字符非字母数字（即把 / . - _ 空格等当分隔符）。
  const boundaryBefore = idx === 0 || !/[a-z0-9]/.test(lower[idx - 1]!);

  if (boundaryBefore && lower.length === keyword.length) {
    return BONUS_EXACT;
  }
  if (boundaryBefore) {
    return BONUS_PREFIX;
  }
  return BONUS_SUBSTRING;
}

export interface ScoredTab {
  tab: BrowserSessionTab;
  matchedKeywords: string[];
  score: number;
  matchedIn: 'title' | 'url' | 'both';
}

/** 给单个 tab 打分。返回 null 表示未命中（无关键词时一律算命中，分数为 0）。 */
export function scoreTab(
  tab: BrowserSessionTab,
  keywords: string[],
): ScoredTab | null {
  if (keywords.length === 0) {
    return { tab, matchedKeywords: [], score: 0, matchedIn: 'url' };
  }

  const title = tab.title ?? '';
  const url = tab.url ?? '';

  let score = 0;
  let hitTitle = false;
  let hitUrl = false;
  const matchedKeywords: string[] = [];

  for (const keyword of keywords) {
    const titleScore = scoreField(title, keyword);
    const urlScore = scoreField(url, keyword);
    if (titleScore === null && urlScore === null) {
      continue;
    }
    matchedKeywords.push(keyword);
    if (titleScore !== null) {
      hitTitle = true;
      score += titleScore * WEIGHT_TITLE;
    }
    if (urlScore !== null) {
      hitUrl = true;
      score += urlScore * WEIGHT_URL;
    }
  }

  if (matchedKeywords.length === 0) {
    return null;
  }

  const matchedIn: ScoredTab['matchedIn'] =
    hitTitle && hitUrl ? 'both' : hitTitle ? 'title' : 'url';

  return { tab, matchedKeywords, score, matchedIn };
}

/** 排序：命中词数多者优先，再比分数；同分时活动的优先，最后按 tabId 稳定排序。 */
function compareScored(a: ScoredTab, b: ScoredTab): number {
  if (b.matchedKeywords.length !== a.matchedKeywords.length) {
    return b.matchedKeywords.length - a.matchedKeywords.length;
  }
  if (b.score !== a.score) {
    return b.score - a.score;
  }
  if (Boolean(b.tab.active) !== Boolean(a.tab.active)) {
    return b.tab.active ? 1 : -1;
  }
  return a.tab.tabId - b.tab.tabId;
}

export function clampLimit(limit: number | undefined): number {
  if (typeof limit !== 'number' || !Number.isFinite(limit) || limit <= 0) {
    return DEFAULT_LIMIT;
  }
  return Math.min(Math.floor(limit), MAX_LIMIT);
}

interface GroupMeta {
  title?: string;
  color?: string;
}

/**
 * 在给定 tab 集合里搜索。
 *
 * groups 用于给命中结果补上分组标题/颜色——分组信息只在扩展侧是完整的，
 * 顺手带上能让 agent 直接说「在 XX 组里」而不用再查一次。
 */
export function searchTabs(
  allTabs: BrowserSessionTab[],
  params: BrowserTabSearchParams,
  groups: Map<number, GroupMeta> = new Map(),
): BrowserTabSearchResult {
  const query = (params.query ?? '').trim();
  const keywords = parseKeywords(query);
  const limit = clampLimit(params.limit);

  // 先按 window/group 过滤出参与搜索的集合。
  let scope = allTabs;
  if (typeof params.windowId === 'number') {
    scope = scope.filter(tab => tab.windowId === params.windowId);
  }
  if (typeof params.groupId === 'number') {
    if (params.groupId === TAB_GROUP_ID_NONE) {
      // 明确要「没分组的」
      scope = scope.filter(
        tab => tab.groupId === undefined || tab.groupId === TAB_GROUP_ID_NONE,
      );
    } else {
      scope = scope.filter(tab => tab.groupId === params.groupId);
    }
  }

  const scanned = scope.length;

  // activeOnly 忽略 query，直接取活动 tab。
  const scored: ScoredTab[] = params.activeOnly
    ? scope
        .filter(tab => tab.active)
        .map(tab => ({ tab, matchedKeywords: [], score: 0, matchedIn: 'url' as const }))
    : scope
        .map(tab => scoreTab(tab, keywords))
        .filter((item): item is ScoredTab => item !== null);

  scored.sort(compareScored);

  const total = scored.length;
  const matches: BrowserTabSearchMatch[] = scored.slice(0, limit).map(item => {
    const group =
      typeof item.tab.groupId === 'number' ? groups.get(item.tab.groupId) : undefined;
    return {
      tab: item.tab,
      matchedKeywords: item.matchedKeywords,
      score: item.score,
      matchedIn: item.matchedIn,
      ...(group?.title ? { groupTitle: group.title } : {}),
      ...(group?.color ? { groupColor: group.color } : {}),
    };
  });

  return {
    query,
    scanned,
    total,
    matches,
    truncated: total > matches.length,
  };
}
