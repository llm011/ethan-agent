/**
 * 记忆列表的「分页拼接」纯函数（Web + Desktop 共用，可单测）。
 *
 * 背景：记忆页的列表原先一次性拉满（结构化记忆 50 条、事实最多 1000 条），
 * 长列表要滚很久、首屏也慢。现在改成首屏取一页，滚到底再按 offset 续拉。
 *
 * 分页引入两个经典坑，规则收在这里：
 *
 * 1. **重复条目**：offset 翻页在「两次请求之间有删除/新增」时会错位 ——
 *    服务端按 `updated_at DESC` 排序，期间有记录被编辑（updated_at 变了）
 *    就会整段重排，下一页可能把上一页的尾巴再发一次。所以按 id 去重。
 *    去重键用记录 id，不是 content：用户可能真的存了两条一样的记忆。
 *
 * 2. **hasMore 判定**：不能只看 `items.length`。一页恰好整除时长度等于页大小，
 *    会多请求一次空页。后端现在返回 `total`，直接用它算最准。
 */

/** 带 id 的列表项最小形状（避免耦合两端各自的记录类型细节）。 */
export interface IdentifiedItem {
  id: string;
}

/**
 * 首页条数。
 *
 * 结构化记忆卡片是完整 Markdown 渲染，一条动辄几 KB —— 50 条首屏已经够满一屏，
 * 再多只是拖慢打开速度。各 tab 共用同一个页大小，保证「滚一屏还有内容」的心智一致。
 */
export const MEMORY_PAGE_SIZE = 50;

/**
 * 追加下一页到列表尾部。
 *
 * - 按 id 去重（保留已在列表里的那份，避免重复 key / 重复渲染）
 * - 返回新数组（不原地改），便于 React 判断变更
 */
export function appendPage<T extends IdentifiedItem>(current: T[], page: T[]): T[] {
  if (page.length === 0) return current;
  const seen = new Set<string>();
  for (const item of current) {
    if (item.id != null) seen.add(item.id);
  }
  const fresh = page.filter((item) => item.id == null || !seen.has(item.id));
  if (fresh.length === 0) return current;
  return [...current, ...fresh];
}

/**
 * 翻页后判断「还有没有下一页」。
 *
 * 优先用后端给的 `total`：`offset + 本页条数 < total` 就是还有。
 * 这比「本页是否拿到满页」准 —— 恰好整除时后者会多请求一次空页。
 *
 * `total` 缺失时（老后端 / 接口没返回）退回按页大小判断。
 *
 * @param page  刚拉到的一页；null = 请求失败，保持调用方原有判断
 * @param total 后端返回的总条数；undefined = 该接口不提供
 */
export function hasMoreAfter<T>(
  page: T[] | null,
  total: number | undefined,
  offset: number,
  pageSize: number = MEMORY_PAGE_SIZE,
): boolean {
  // 请求失败：不要因为一次失败就以为到头了（否则用户再也拉不到后面的页）
  if (page == null) return false;
  if (typeof total === "number" && Number.isFinite(total)) {
    return offset + page.length < total;
  }
  return page.length >= pageSize;
}

/**
 * 用「刚拉到的一页」刷新列表**尾部**，同时保留更早的已加载分页。
 *
 * 使用场景：编辑/删除一条记忆后要刷新列表。这时列表里可能已经有用户翻出来的
 * 好几页，直接 `setItems(firstPage)` 会让那些页凭空消失 —— 用户看到的现象是
 * 「刚翻出来的内容突然没了」。所以只替换第一页覆盖的范围，后面的原样留着。
 *
 * 规则：
 * - `fresh` 视为权威的第一页（含编辑后的新内容、已删除的不在里面）
 * - `prev` 中「比第一页最后一条更靠后」的部分原样接上
 * - 重叠区间用 `fresh` 的版本
 * - `fresh` 为空时不改动（保守：宁可不动，也不要把已翻出来的列表清空）
 *
 * 与 chat/history.ts 的 `replaceTailKeepOlder` 是同一套思路，区别在方向：
 * 消息是「新的在后、往上翻」所以保留**更早的**；记忆列表是「往下翻」，
 * 所以保留**更靠后的**。
 */
export function replaceHeadKeepLater<T extends IdentifiedItem>(
  prev: T[],
  fresh: T[],
  pageSize: number = MEMORY_PAGE_SIZE,
): T[] {
  if (fresh.length === 0) return prev;
  // 第一页没铺满 → 本来就没有更多了，直接以 fresh 为准
  if (fresh.length < pageSize) return fresh;
  // prev 里落在第一页覆盖范围之外的（按位置切：第一页之后的部分）
  if (prev.length <= fresh.length) return fresh;
  const kept = prev.slice(fresh.length);
  const freshIds = new Set(fresh.map((i) => i.id));
  return [...fresh, ...kept.filter((i) => !freshIds.has(i.id))];
}

/** 列表内容 + 它已经覆盖到的服务端偏移。两者必须一起更新，否则会出现缺口或重复。 */
export interface LoadedList<T> {
  items: T[];
  offset: number;
}

/**
 * 把刚拉到的一页并入列表，并给出新的偏移水位。
 *
 * 这是「刷新首页」和「追加下一页」的统一入口。**水位不能拿 `items.length` 现算**：
 * 追加时 `appendPage` 会按 id 去重，列表长得比实际拉取的偏移慢；刷新时列表会先
 * 缩水再涨回来。这两种情况都会让下一次 `loadMore` 用错 offset —— 重复拉已看过的
 * 页（去重后界面看不出来，只是白转圈），或者跳过一整页。
 *
 * 分三种情况：
 * - `offset > 0`：追加下一页。水位推进到 `offset + 本页条数`。
 * - `offset === 0` 且 `sameQuery`：刷新第一页。编辑/删除一条记忆后，列表里可能已经
 *   有用户翻出来的好几页，这里只替换第一页覆盖的范围，后面的原样留着，水位随之
 *   只前进不回退（否则每编辑一次就丢一页进度）。
 * - `offset === 0` 且换查询：切 tab / 改日期 / 切归档视图。新查询和旧列表没有关系，
 *   整体重建，水位归零重算。
 *
 * @param prev      当前列表
 * @param page      刚拉到的一页
 * @param offset    本次请求用的 offset
 * @param sameQuery 本次请求和当前列表是不是同一个查询
 * @param pageSize  本次请求的页大小（算「第一页是否铺满」用）
 */
export function mergePage<T extends IdentifiedItem>(
  prev: T[],
  page: T[],
  offset: number,
  sameQuery: boolean,
  pageSize: number = MEMORY_PAGE_SIZE,
): LoadedList<T> {
  if (offset > 0) {
    return { items: appendPage(prev, page), offset: offset + page.length };
  }
  if (!sameQuery) {
    return { items: page, offset: page.length };
  }
  const items = replaceHeadKeepLater(prev, page, pageSize);
  return { items, offset: items.length };
}
