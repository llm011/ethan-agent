/**
 * 记忆列表分页拼接规则（Web + Desktop 共用 @ethan/shared）。
 *
 * 这些函数是「下滑加载更多」的防回归网：
 * 一旦有人把去重改掉、或把 hasMore 判定退回「本页是否满」，
 * 现象是列表出现重复卡片、或恰好整除时多转一次圈，这里就会红。
 */

import { describe, it, expect } from "vitest";
import {
  MEMORY_PAGE_SIZE,
  appendPage,
  hasMoreAfter,
  mergePage,
  replaceHeadKeepLater,
  type LoadedList,
} from "@ethan/shared/lib/memory-paging";

interface Item {
  id: string;
}

const item = (id: string): Item => ({ id });

const page = (from: number, count: number, prefix = "m"): Item[] =>
  Array.from({ length: count }, (_, i) => item(`${prefix}${from + i}`));

describe("appendPage", () => {
  it("追加一页到尾部", () => {
    const result = appendPage(page(0, 2), page(2, 2));
    expect(result.map((i) => i.id)).toEqual(["m0", "m1", "m2", "m3"]);
  });

  it("按 id 去重（offset 翻页在记录被编辑后会重叠）", () => {
    // 第二页把第一页的尾巴又发了一次
    const result = appendPage(page(0, 3), page(2, 3));
    expect(result.map((i) => i.id)).toEqual(["m0", "m1", "m2", "m3", "m4"]);
  });

  it("整页都是重复的不改动列表", () => {
    const current = page(0, 2);
    expect(appendPage(current, page(0, 2))).toBe(current);
  });

  it("空页不改动列表", () => {
    const current = page(0, 2);
    expect(appendPage(current, [])).toBe(current);
  });

  it("不原地修改入参", () => {
    const current = page(0, 2);
    appendPage(current, page(2, 2));
    expect(current.map((i) => i.id)).toEqual(["m0", "m1"]);
  });
});

describe("hasMoreAfter", () => {
  it("优先用后端的 total", () => {
    expect(hasMoreAfter(page(0, 3), 10, 0, 3)).toBe(true);
    expect(hasMoreAfter(page(9, 1), 10, 9, 3)).toBe(false);
  });

  it("恰好整除时不会多算一页（这是 total 优于「满页即还有」的地方）", () => {
    // 10 条、页大小 5：第二页拿满 5 条，但确实到头了
    expect(hasMoreAfter(page(5, 5), 10, 5, 5)).toBe(false);
  });

  it("没有 total 时退回按页大小判断", () => {
    expect(hasMoreAfter(page(0, 3), undefined, 0, 3)).toBe(true);
    expect(hasMoreAfter(page(0, 2), undefined, 0, 3)).toBe(false);
  });

  it("请求失败（null）不改判断，避免一次失败就以为到头", () => {
    expect(hasMoreAfter(null, 100, 0, 3)).toBe(false);
  });

  it("offset 参与计算：按已加载条数而非页号", () => {
    expect(hasMoreAfter(page(50, 3), 60, 50, 3)).toBe(true);
    expect(hasMoreAfter(page(50, 3), 53, 50, 3)).toBe(false);
  });
});

describe("replaceHeadKeepLater", () => {
  it("刷新第一页时保留后面已翻出来的页", () => {
    const loaded = page(0, 4);
    const fresh = page(0, 2); // 第一页，页大小 2
    const result = replaceHeadKeepLater(loaded, fresh, 2);
    expect(result.map((i) => i.id)).toEqual(["m0", "m1", "m2", "m3"]);
  });

  it("第一页的修改会覆盖旧内容", () => {
    const loaded = [item("m0"), item("m1"), item("m2")];
    const fresh = [{ id: "m0" }, { id: "m1" }];
    const result = replaceHeadKeepLater(loaded, fresh, 2);
    expect(result.map((i) => i.id)).toEqual(["m0", "m1", "m2"]);
  });

  it("第一页没铺满说明本来就没更多了，直接以 fresh 为准", () => {
    const loaded = page(0, 3);
    const fresh = page(0, 1); // 页大小 2，只回了 1 条
    const result = replaceHeadKeepLater(loaded, fresh, 2);
    expect(result.map((i) => i.id)).toEqual(["m0"]);
  });

  it("空 fresh 不改动列表（宁可不动也不要把已翻出来的清空）", () => {
    const loaded = page(0, 3);
    expect(replaceHeadKeepLater(loaded, [], 2)).toBe(loaded);
  });

  it("删除一条后不会把后面的页顶上来造成重复", () => {
    // 第一页删掉 m1，服务端补一条 m2 进来
    const loaded = [item("m0"), item("m1"), item("m2"), item("m3")];
    const fresh = [item("m0"), item("m2")];
    const result = replaceHeadKeepLater(loaded, fresh, 2);
    const ids = result.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(["m0", "m2", "m3"]);
  });

  it("默认页大小 = MEMORY_PAGE_SIZE", () => {
    const loaded = page(0, MEMORY_PAGE_SIZE + 5);
    const fresh = page(0, MEMORY_PAGE_SIZE);
    const result = replaceHeadKeepLater(loaded, fresh);
    expect(result.length).toBe(MEMORY_PAGE_SIZE + 5);
  });
});

describe("mergePage", () => {
  const loaded = (items: Item[], offset: number): LoadedList<Item> => ({ items, offset });

  it("刷新第一页时保留已翻出来的页，水位不回退（这是 P0 的回归锁）", () => {
    // 已翻到第 2 页（页大小 2，共 4 条）
    const prev = loaded(page(0, 4), 4);
    // 删掉 m1 → 服务端补一条 m2 上来，第一页变成 [m0, m2]
    const next = mergePage(prev.items, [item("m0"), item("m2")], 0, true, 2);

    expect(next.items.map((i) => i.id)).toEqual(["m0", "m2", "m3"]);
    // 关键：水位是 3（跟着保留后的列表走），不是被第一页的 2 打回去。
    // 旧实现用 items.length 现算 + 整体替换成第一页，这里会退成 2 → 重复拉一页
    expect(next.offset).toBe(3);
  });

  it("追加时水位按请求量推进，不因去重而卡住", () => {
    const prev = loaded(page(0, 3), 3);
    // 服务端重排，第二页把 m2 又发了一次
    const next = mergePage(prev.items, page(2, 3), 3, true);

    expect(next.items.map((i) => i.id)).toEqual(["m0", "m1", "m2", "m3", "m4"]);
    // 去重后列表只有 5 条，但水位必须按「请求了 3 条」走到 6，
    // 否则下次会从 5 开始拉，把 m4 再拉一遍
    expect(next.offset).toBe(6);
  });

  it("换查询时整体重建，不保留上一个查询的页", () => {
    const prev = loaded(page(0, 4, "a"), 4);
    const next = mergePage(prev.items, page(0, 2, "b"), 0, false, 2);

    expect(next.items.map((i) => i.id)).toEqual(["b0", "b1"]);
    expect(next.offset).toBe(2);
  });

  it("刷新拿到空页时列表与水位都不动（宁可不动也不清空）", () => {
    const prev = loaded(page(0, 4), 4);
    const next = mergePage(prev.items, [], 0, true, 2);

    expect(next.items).toBe(prev.items);
    expect(next.offset).toBe(4);
  });

  it("第一页没铺满说明本来就到头了，后续页不保留", () => {
    const prev = loaded(page(0, 4), 4);
    const next = mergePage(prev.items, page(0, 1), 0, true, 2);

    expect(next.items.map((i) => i.id)).toEqual(["m0"]);
    expect(next.offset).toBe(1);
  });

  it("首屏（offset 0 + 新查询）水位等于本页条数", () => {
    const next = mergePage([], page(0, 2), 0, false, 2);
    expect(next.items.map((i) => i.id)).toEqual(["m0", "m1"]);
    expect(next.offset).toBe(2);
  });
});
