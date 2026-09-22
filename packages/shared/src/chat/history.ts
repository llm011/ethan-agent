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
 * 目前只有单测在用它 —— 两个 chat-view 都内联成 `has_more ?? len >= PAGE` 了。
 * 保留是因为它把「后端没给 has_more 时怎么兜底」这条规则写清楚了；接入前请先
 * 读下面的失败分支语义。
 *
 * 不能只看 `messages.length`：去重会把重叠部分吃掉，若那页全是重复的，
 * 长度没涨但确实已经翻到了会话开头。所以以「这一页是否拿到满页」为准 ——
 * 后端返回不足一页就说明到头了。
 */
export function hasOlderAfterLoad<M>(older: M[] | null, pageSize: number, serverHint?: boolean): boolean {
  // 请求失败（older == null）：返回 false 表示「没拿到更早的历史」。
  // 注意别把它当成「已经到头」—— 调用方若据此把 hasOlder 置 false，一次网络失败
  // 就会让用户再也滚不上去。正确做法是失败时保留调用方原有的 hasOlder 判断。
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
 * - `prev` 中**完全没有 id** 的（本地乐观插入的 user 消息）：与 `page` 里同 role+content
 *   的条目**按出现次数对账**，page 里不够数才保留。它没有 id 可比，无条件丢弃会让
 *   刚发出去的消息在回填后凭空消失；但也不能无条件保留 —— 后端通常已经落库了同一
 *   条（那条**有 id**），再留一份就会**渲染成两个气泡**（新会话首轮跑完时最常见的
 *   现象），且这份会被插到更早的历史前面，顺序也是错的。判据必须是「内容 + 次数」
 *   而非 id：这种消息没有 id 可用（与 prependOlderMessages 的约定一致），而只看
 *   page 里「无 id」的部分会漏掉有 id 的后端消息，等于永远匹配不上。
 * - `tmp:` 占位气泡（流式中的 assistant）**不保留**：它的定稿版本一定在 `page` 里
 *   （这正是本函数的使用场景——流结束/重连后拉最新一页核对），留着会变成重复气泡。
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
  // page 里已带的内容，用来判断「无 id 的本地消息是不是已经被补进来了」。
  //
  // 用「内容 → 出现次数」而不是「内容集合」：本地那条乐观消息没有 id，只能按内容
  // 认亲，而**后端落库的那条是有 id 的**。早前只看 page 里「无 id」的部分，就永远
  // 匹配不上有 id 的后端消息，于是本地那条被当成「后端没落库」保留下来 —— 表现为
  // 新会话首轮回复结束后，用户的 query 又重复出现一条（刷新就没，因为重新拉的历史
  // 里只有后端那份）。
  //
  // 连发两条完全相同的 query 时，page 里会出现两次同样的 key，计数各自算出 1、2，
  // 与本地两条一一对应，谁也不会被多留一份。
  //
  // 但配额要先扣掉「prev 里有 id、且能在 page 里按 id 对上」的那些 —— 它们本来就由
  // page 代表，不能占掉留给无 id 乐观消息的名额。否则「连发两条相同的 query、后端只
  // 落了一条」时，page 的 1 条额度会被有 id 的那条吃掉，无 id 的那条明明没落库却被
  // 判成「已存在」而不补，用户那条 query 就从界面上消失了。
  const contentOf = (m: IdentifiedMessage): string => {
    const c = (m as { content?: unknown }).content;
    return typeof c === "string" ? c : "";
  };
  const keyOf = (m: IdentifiedMessage): string => `${m.role}\u0000${contentOf(m)}`;
  const pageIds = new Set(page.map((m) => m.id));
  const pageContentCounts = new Map<string, number>();
  for (const m of page) {
    const key = keyOf(m);
    pageContentCounts.set(key, (pageContentCounts.get(key) ?? 0) + 1);
  }
  // 扣掉 prev 里「有 id 且 page 里也有这个 id」的条数，剩下的才是无 id 消息的额度
  const claimedByPersisted = new Map<string, number>();
  for (const m of prev) {
    if (m.id == null || !pageIds.has(m.id)) continue;
    const key = keyOf(m);
    claimedByPersisted.set(key, (claimedByPersisted.get(key) ?? 0) + 1);
  }

  // 比 page 更旧的：拼在 page **前面**
  const carried: M[] = [];
  // 无 id 且 page 里没有的：拼在 page **后面**（它是用户刚发的那条，最新）
  const localTail: M[] = [];
  // 本地无 id 消息按内容累计到第几次，用来跟 page 的同内容条数对账
  const localSeen = new Map<string, number>();
  for (const m of prev) {
    if (m.id == null) {
      // 本地乐观插入的消息（没有 id）。调用方一般已经用 mergeMissingUserMessages
      // 把它补进了 page 末尾，此时 page 里有一份等价的，再留一份就是重复气泡。
      // 确实不在 page 里（后端没落库）才保留，且必须放**最后** —— 它是用户刚发的
      // 那条，比 page 里的任何一条都新；拼进 carried 会被排到更早的历史前面。
      //
      // 只对**无 id 的本地消息**做这层对账：有 id 的本地消息按 id 判，内容相同的
      // 两条有 id 消息（用户连发两次同样的 query）不应互相顶掉。
      const key = keyOf(m);
      const nth = (localSeen.get(key) ?? 0) + 1;
      localSeen.set(key, nth);
      const quota = (pageContentCounts.get(key) ?? 0) - (claimedByPersisted.get(key) ?? 0);
      if (quota < nth) localTail.push(m);
      continue;
    }
    if (typeof m.id === "number" && m.id < oldestPageId) carried.push(m);
    // 其余情况（tmp: 占位气泡、比 page 更新的消息）交给 page —— page 是权威的最新一页
  }
  if (carried.length === 0 && localTail.length === 0) return page;
  return [...carried, ...page, ...localTail];
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
