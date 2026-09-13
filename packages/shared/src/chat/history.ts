/**
 * 会话历史的「分页拼接」纯函数。
 *
 * 背景：长会话（最多 953 条消息、单会话 11MB）原先一次性全量加载，
 * 点开要卡好几秒。现在首屏只取最近 N 条，向上滚动时再按 before 翻页。
 *
 * 分页引入两个经典坑，这里用纯函数把规则收在一处（两端共用、可单测）：
 *
 * 1. 翻页拿到的旧消息是「严格早于」页首那条的，理论上不会重叠 —— 但流式结束
 *    回填、缓存刷新等路径可能让同一段历史被加载两次，所以仍然按 id 去重。
 *    去重键是后端消息 id（不是 role+content）：用户可能真的连发两条一样的内容。
 *
 * 2. 流式要给 assistant 占位消息一个 id 来渲染，但那时后端还没落库、没有真实 id。
 *    若用 `Date.now()` 之类伪造，回填时就无法与真实 id 对上，会多出一条幽灵消息。
 *    所以占位消息用 crypto.randomUUID() 生成临时 id，随后端把「运行中」状态
 *    落库（run 一启动就写 running 行），我们再把它提升成真实 id。
 */

/** 依赖 Web Crypto 的做法：不稳定，仅作为最后兜底（老 WebView / 非安全上下文）。 */
function fallbackTempId(): string {
  return `tmp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 生成占位消息的临时 id。
 *
 * 用 `crypto.randomUUID()` 而不是自增计数器：切走再切回会话、并发多个会话时
 * 计数器会串号。用 `tmp:` 前缀与后端数字 id overlap 不到一起。
 */
export function makeTempId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === "function") return `tmp:${c.randomUUID()}`;
  return fallbackTempId();
}

/** 判断一个 id 是不是没落库的临时 id。 */
export function isTempId(id: unknown): boolean {
  return typeof id === "string" && (id.startsWith("tmp:") || id.startsWith("tmp-"));
}

/**
 * 这个 id 是否可以用来和后端对话（读过程记录、加标注、删除、分享定位等）。
 *
 * 流式中的占位消息只有临时 id —— 拿它去发请求会被后端当非法参数拒掉，
 * 或者更糟：按钮亮着但点了报错。所以凡是「发请求 / 写入以 id 为主键的状态」
 * 的地方都要先过这一关。
 */
export function isPersistedId(id: unknown): id is number {
  return typeof id === "number" && Number.isFinite(id);
}

/** 消息的最小形状（只关心 id / role，避免耦合两端各自的 Message 类型细节）。 */
export interface IdentifiedMessage {
  id?: number | string | null;
  role: string;
}

/**
 * 给「刚发起、尚未落库」的 assistant 占位消息找一个可用 id。
 *
 * 优先让调用方预分配（`makeTempId()` 的结果），这样流式期间占位 id 就固定了；
 * 缺省时兜底生成一个。
 */
export function newAssistantPlaceholder<M extends IdentifiedMessage>(
  base: M[],
  extra?: Partial<M>,
): M {
  return {
    role: "assistant",
    content: "",
    created_at: Date.now() / 1000,
    id: makeTempId(),
    ...extra,
  } as unknown as M;
}

/**
 * 把一条已存在的占位消息的 id 提升为后端返回的真实 id。
 *
 * 找到旧的临时 id 就地替换；找不到（例如已经在别处被合并/替换）就原样返回，
 * 保证是幂等的 —— consumeStream 在多个事件点都会调用，重复调用必须无害。
 */
export function promoteMessageId<M extends IdentifiedMessage>(
  messages: M[],
  tempId: number | string | null | undefined,
  realId: number | null | undefined,
): M[] {
  if (tempId == null || realId == null || tempId === realId) return messages;
  let hit = false;
  const next = messages.map((m) => {
    if (m.id !== tempId) return m;
    hit = true;
    return { ...m, id: realId };
  });
  return hit ? next : messages;
}

/**
 * 向上翻页：把「更早的一页」拼到当前列表前面。
 *
 * - 按 id 去重（保留已在列表里的那份），避免重叠页造成重复 key / 重复渲染
 * - 旧的没有 id 的消息（本地乐观插入的）原样保留在最前
 * - 返回新数组（不原地改），便于 React 判断变更
 */
export function prependOlderMessages<M extends IdentifiedMessage>(current: M[], older: M[]): M[] {
  if (older.length === 0) return current;
  const seen = new Set<unknown>();
  for (const m of current) {
    if (m.id != null) seen.add(m.id);
  }
  const fresh = older.filter((m) => m.id == null || !seen.has(m.id));
  if (fresh.length === 0) return current;
  return [...fresh, ...current];
}

/**
 * 翻页后判断「还有没有更早的」。
 *
 * 不能只看 `messages.length`：去重会把重叠部分吃掉，若那页全是重复的，
 * 长度没涨但确实已经翻到了会话开头。所以以「这一页是否拿到满页」为准 ——
 * 后端返回不足一页就说明到头了。
 */
export function hasOlderAfterLoad<M>(older: M[] | null, pageSize: number, serverHint?: boolean): boolean {
  // 请求失败：保持调用方原有判断，不要因为一次失败就以为到头了
  if (older == null) return false;
  // 后端给了明确答案就以它为准（去重后长度会失真，只有后端知道还剩多少）
  if (serverHint === false) return false;
  if (serverHint === true) return true;
  return older.length >= pageSize;
}

/** 上滚一页的默认条数（首屏也是这个数，保证「一屏一页」的心智一致）。 */
export const MESSAGE_PAGE_SIZE = 30;

/**
 * 用「刚拉到的一页」刷新末尾，同时保留比这一页更早的已加载历史。
 *
 * 使用场景：流结束/断线重连后要拿最新一页核对定稿结果。这时 prev 里可能已经有
 * 用户上滚翻出来的好几页更早历史，如果直接 `setMessages(page)`，那些页会凭空消失
 * ——用户看到的现象是「刚翻上去的历史突然没了」。
 *
 * 规则：
 * - `page` 视为权威的最新一页（含定稿后的真实 id）
 * - `prev` 中比「这一页最旧那条」还旧的，原样带到前面
 * - 重叠区间用 page 的版本（更权威，且 id 已提升为真实数字）
 * - page 为空时不改动（调用方通常也不该走到这，但保持安全）
 */
export function replaceTailKeepOlder<M extends IdentifiedMessage>(
  prev: M[],
  page: M[],
): M[] {
  if (page.length === 0) return prev;
  const oldestPageId = page.find((m) => typeof m.id === "number")?.id;
  if (typeof oldestPageId !== "number") return page;
  const carried = prev.filter(
    (m) => typeof m.id === "number" && (m.id as number) < oldestPageId,
  );
  return carried.length > 0 ? [...carried, ...page] : page;
}

/**
 * 把「刚拉到的一页消息」并入已有的**全量**会话缓存。
 *
 * 缓存语义是「整个会话」：`fetchSession` 离线时只读它。而首屏 / 静默刷新走的
 * `fetchSessionPage(limit=30)` 只有最近一页——直接覆盖写会把全量缓存降级成残页，
 * 离线打开长会话就只剩 30 条，更早历史永久不可达（上滚走网络请求，离线必然失败）。
 *
 * 所以分页路径只**合并**、不覆盖，规则：
 * - `cached` 为空 → 返回 null（调用方保持「无缓存」，宁可离线无缓存也不要残缺缓存）
 * - 按 id 合并（新页优先，覆盖流式期间写入的中间态）
 * - 只保留 id >= 缓存原本最旧 id 的部分：不把缓存的覆盖范围向更早方向偷偷扩张，
 *   否则会出现「以为覆盖 1..N 但中间有空洞」的假完整缓存
 * - 缓存的条目里没有数字 id（拿不到 cutoff）→ 返回 null，保守跳过
 *
 * @returns 新的 messages 数组（已按 id 升序）；null 表示不应改写缓存
 */
export function mergeOlderMessagesIntoCache<M extends IdentifiedMessage>(
  cachedMessages: M[],
  pageMessages: M[],
): M[] | null {
  if (pageMessages.length === 0) return null;
  if (cachedMessages.length === 0) return null;
  let cutoff: number | null = null;
  for (const m of cachedMessages) {
    if (typeof m.id === "number" && (cutoff === null || m.id < cutoff)) cutoff = m.id;
  }
  if (cutoff === null) return null;
  // 绑成 const：TS 不会把 let 的收窄带进下面的闭包
  const floor: number = cutoff;
  const fresh = pageMessages.filter((m) => typeof m.id === "number" && m.id >= floor);
  if (fresh.length === 0) return null;
  const byId = new Map<number, M>();
  for (const m of cachedMessages) {
    if (typeof m.id === "number") byId.set(m.id, m);
  }
  for (const m of fresh) {
    if (typeof m.id === "number") byId.set(m.id, m);
  }
  return [...byId.entries()].sort((a, b) => a[0] - b[0]).map(([, m]) => m);
}
