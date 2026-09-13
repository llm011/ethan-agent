/**
 * 分页结果并入全量缓存的规则。
 *
 * 首屏 / 静默刷新都只拉最近一页（`fetchSessionPage(limit=30)`）。这一页**不能**直接
 * writeSessionCache —— 那会把「整个会话」的缓存降级成一页，离线打开长会话就只剩
 * 最近 30 条，更早历史永久不可达。这里的用例锁住「只合并不覆盖」。
 */

import { describe, it, expect, beforeEach } from "vitest";
import { readSessionCache, writeSessionCache, mergeSessionPageIntoCache } from "@/lib/session-cache";
import type { SessionDetail } from "@/lib/api-sessions";

// jsdom + vitest 下 localStorage 不是默认可用的全局（要 --localstorage-file 或显式 stub），
// 会话缓存模块直接依赖它，这里装一个最小内存实现。
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map<string, string>();
  (globalThis as { localStorage: Storage }).localStorage = {
    get length() { return store.size; },
    clear: () => store.clear(),
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    key: (i: number) => [...store.keys()][i] ?? null,
    removeItem: (k: string) => { store.delete(k); },
    setItem: (k: string, v: string) => { store.set(k, String(v)); },
  } as Storage;
}

const msg = (id: number, content = `c${id}`) => ({ id, role: "user", content }) as any;

const detail = (messages: any[], extra: Partial<SessionDetail> = {}): SessionDetail =>
  ({ id: "s1", title: "T", model: "m", source: "web", messages, ...extra }) as unknown as SessionDetail;

const idsIn = (sid = "s1") => readSessionCache(sid)?.detail.messages.map((m: any) => m.id);

describe("mergeSessionPageIntoCache", () => {
  beforeEach(() => localStorage.clear());

  it("没有全量缓存时不落任何残缺缓存（宁可离线无缓存）", () => {
    mergeSessionPageIntoCache("s1", detail([msg(50), msg(51)]));
    expect(readSessionCache("s1")).toBeNull();
  });

  it("把最近一页并入已有全量缓存，不覆盖更早的历史", () => {
    writeSessionCache("s1", detail([msg(1), msg(2), msg(3)]));
    mergeSessionPageIntoCache("s1", detail([msg(3), msg(4), msg(5)]));
    expect(idsIn()).toEqual([1, 2, 3, 4, 5]);
  });

  it("重叠消息用新页的版本（覆盖流式期间的中间态）", () => {
    writeSessionCache("s1", detail([{ id: 3, role: "assistant", content: "流式中…" } as any]));
    mergeSessionPageIntoCache("s1", detail([{ id: 3, role: "assistant", content: "定稿内容" } as any]));
    expect(readSessionCache("s1")!.detail.messages.map((m: any) => m.content)).toEqual(["定稿内容"]);
  });

  it("不把缓存的覆盖范围向更早的方向偷偷扩张（避免中间空洞）", () => {
    // 缓存只从 id=5 开始；新页含 1..5。若整页写进去，缓存会假装覆盖 1..5 而中间是空的。
    writeSessionCache("s1", detail([msg(5), msg(6), msg(7)]));
    mergeSessionPageIntoCache("s1", detail([msg(1), msg(2), msg(3), msg(4), msg(5)]));
    expect(idsIn()).toEqual([5, 6, 7]);
  });

  it("整页都比缓存旧时不动缓存", () => {
    writeSessionCache("s1", detail([msg(9)]));
    mergeSessionPageIntoCache("s1", detail([msg(1), msg(2)]));
    expect(idsIn()).toEqual([9]);
  });

  it("整页都比缓存新时全部并入并保持 id 升序", () => {
    writeSessionCache("s1", detail([msg(1)]));
    mergeSessionPageIntoCache("s1", detail([msg(3), msg(2)]));
    expect(idsIn()).toEqual([1, 2, 3]);
  });

  it("空页不动缓存", () => {
    writeSessionCache("s1", detail([msg(1)]));
    mergeSessionPageIntoCache("s1", detail([]));
    expect(idsIn()).toEqual([1]);
  });

  it("标题等元信息跟随新页更新", () => {
    writeSessionCache("s1", detail([msg(1)], { title: "旧标题" }));
    mergeSessionPageIntoCache("s1", detail([msg(1)], { title: "新标题" }));
    expect(readSessionCache("s1")!.detail.title).toBe("新标题");
  });

  it("缓存里没有数字 id 的消息时不动（拿不到 cutoff，保守跳过）", () => {
    writeSessionCache("s1", detail([{ role: "user", content: "无 id" } as any]));
    mergeSessionPageIntoCache("s1", detail([msg(1)]));
    expect(idsIn()).toEqual([undefined]);
  });
});
