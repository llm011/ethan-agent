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
  replaceHeadKeepLater,
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
