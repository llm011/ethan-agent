/**
 * 会话历史分页拼接规则。
 *
 * 这些函数是「上滚加载更早消息」的防回归网：
 * 一旦有人把去重改掉、或又用 Date.now() 当占位 id，这里就会红。
 */

import { describe, it, expect } from "vitest";
import {
  isTempId,
  isPersistedId,
  makeTempId,
  newAssistantPlaceholder,
  prependOlderMessages,
  promoteMessageId,
  hasOlderAfterLoad,
  replaceTailKeepOlder,
  mergeOlderMessagesIntoCache,
} from "@ethan/shared/chat/history";

type M = { id?: number | string | null; role: string; content: string };

const m = (id: number | string | null, role: string, content = `c${id}`): M => ({ id, role, content });

describe("temp id", () => {
  it("占位 id 带 tmp: 前缀，与后端数字 id overlap 不到一起", () => {
    const id = makeTempId();
    expect(isTempId(id)).toBe(true);
    expect(String(id).startsWith("tmp:")).toBe(true);
  });

  it("连续生成的占位 id 不重复", () => {
    const ids = new Set(Array.from({ length: 200 }, () => makeTempId()));
    expect(ids.size).toBe(200);
  });

  it("真实数字 id 不算临时 id", () => {
    expect(isTempId(42)).toBe(false);
    expect(isTempId(undefined)).toBe(false);
    expect(isTempId(null)).toBe(false);
  });
});

describe("newAssistantPlaceholder", () => {
  it("新占位消息带自己的临时 id（不能与历史里的 id 撞）", () => {
    const history = [m(1, "user"), m(2, "assistant")];
    const ph = newAssistantPlaceholder<M & { model: string }>(history as (M & { model: string })[], { model: "gpt" });
    expect(ph.role).toBe("assistant");
    expect(ph.content).toBe("");
    expect(isTempId(ph.id)).toBe(true);
    expect(history.some((x) => x.id === ph.id)).toBe(false);
  });

  it("同一次流式里两次创建占位得到不同 id", () => {
    const a = newAssistantPlaceholder<M>([]);
    const b = newAssistantPlaceholder<M>([]);
    expect(a.id).not.toBe(b.id);
  });
});

describe("promoteMessageId", () => {
  it("把临时 id 提升成后端真实 id（回填后不会多一条幽灵消息）", () => {
    const ph = newAssistantPlaceholder<M>([]);
    const list = [m(1, "user"), ph];
    const next = promoteMessageId(list, ph.id, 99);
    expect(next.map((x) => x.id)).toEqual([1, 99]);
    expect(next.length).toBe(2);
  });

  it("幂等：同一对 (tmp, real) 重复调用不再变化", () => {
    const ph = newAssistantPlaceholder<M>([]);
    const once = promoteMessageId([ph], ph.id, 99);
    const twice = promoteMessageId(once, ph.id, 99);
    expect(twice).toBe(once);
  });

  it("找不到临时 id 时原样返回（不误伤其他消息）", () => {
    const list = [m(1, "user"), m(2, "assistant")];
    expect(promoteMessageId(list, "tmp:不存在", 99)).toBe(list);
  });

  it("realId 缺失（后端没返回）时不改动列表", () => {
    const ph = newAssistantPlaceholder<M>([]);
    const list = [ph];
    expect(promoteMessageId(list, ph.id, null)).toBe(list);
    expect(promoteMessageId(list, ph.id, undefined)).toBe(list);
  });

  it("临时 id 已等于真实 id 时不做无谓重建", () => {
    const list = [m(7, "assistant")];
    expect(promoteMessageId(list, 7, 7)).toBe(list);
  });
});

describe("prependOlderMessages", () => {
  it("把更早的一页按原顺序拼到前面", () => {
    const current = [m(4, "user"), m(5, "assistant")];
    const older = [m(1, "user"), m(2, "assistant"), m(3, "user")];
    expect(prependOlderMessages(current, older).map((x) => x.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it("重叠页去重（同一段历史加载两次不会重复渲染）", () => {
    const current = [m(3, "user"), m(4, "assistant")];
    const older = [m(1, "user"), m(2, "assistant"), m(3, "user")];
    const out = prependOlderMessages(current, older);
    expect(out.map((x) => x.id)).toEqual([1, 2, 3, 4]);
    expect(new Set(out.map((x) => x.id)).size).toBe(out.length);
  });

  it("内容相同但 id 不同必须都保留（用户真的连发过同样的话）", () => {
    const current = [m(2, "user", "好的")];
    const older = [m(1, "user", "好的")];
    expect(prependOlderMessages(current, older).length).toBe(2);
  });

  it("整页都重复时返回原数组引用（不触发无谓重渲染）", () => {
    const current = [m(1, "user"), m(2, "assistant")];
    const older = [m(1, "user"), m(2, "assistant")];
    expect(prependOlderMessages(current, older)).toBe(current);
  });

  it("空页不改动列表", () => {
    const current = [m(1, "user")];
    expect(prependOlderMessages(current, [])).toBe(current);
  });

  it("没有 id 的本地消息原样保留在最前", () => {
    const current = [m(3, "user")];
    const older = [m(null, "assistant"), m(1, "user")];
    const out = prependOlderMessages(current, older);
    expect(out.map((x) => x.id)).toEqual([null, 1, 3]);
  });
});

describe("hasOlderAfterLoad", () => {
  it("拿到满页 → 可能还有更早的", () => {
    expect(hasOlderAfterLoad([m(1, "user"), m(2, "assistant")], 2)).toBe(true);
  });

  it("拿到不足一页 → 到头了，别再多发一次空请求", () => {
    expect(hasOlderAfterLoad([m(1, "user")], 2)).toBe(false);
  });

  it("请求失败（null）→ 不改变「还有更多」的判断依据由调用方决定，这里返回 false", () => {
    expect(hasOlderAfterLoad(null, 2)).toBe(false);
  });

  it("后端明确说没有更多时以后端为准", () => {
    expect(hasOlderAfterLoad([m(1, "user"), m(2, "assistant")], 2, false)).toBe(false);
  });

  it("后端说还有更多时，即使只回了一条也继续", () => {
    expect(hasOlderAfterLoad([m(1, "user")], 2, true)).toBe(true);
  });
});

describe("isPersistedId", () => {
  it("只有落库后的数字 id 才允许拿去发请求", () => {
    expect(isPersistedId(42)).toBe(true);
    expect(isPersistedId(0)).toBe(true);
  });

  it("占位消息的临时 id 不能发请求（后端会当非法参数）", () => {
    expect(isPersistedId(makeTempId())).toBe(false);
    expect(isPersistedId("tmp:abc")).toBe(false);
  });

  it("缺失 / 非法值一律拒绝", () => {
    expect(isPersistedId(undefined)).toBe(false);
    expect(isPersistedId(null)).toBe(false);
    expect(isPersistedId(NaN)).toBe(false);
    expect(isPersistedId("42")).toBe(false);
  });
});

describe("replaceTailKeepOlder", () => {
  it("保留比新页更早的已加载历史（上滚翻出来的页不能被冲掉）", () => {
    // 用户已经上滚翻出 1..6，然后流结束拉到最近一页 5..8
    const prev = [m(1, "user"), m(2, "assistant"), m(3, "user"), m(4, "assistant"), m(5, "user"), m(6, "assistant")];
    const page = [m(5, "user"), m(6, "assistant"), m(7, "user"), m(8, "assistant")];
    const out = replaceTailKeepOlder(prev, page);
    expect(out.map((x) => x.id)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(new Set(out.map((x) => x.id)).size).toBe(out.length);
  });

  it("重叠区间用新页的版本（真实 id / 定稿内容优先）", () => {
    const prev = [m(3, "assistant", "流式中…")];
    const page = [m(3, "assistant", "定稿内容"), m(4, "user")];
    const out = replaceTailKeepOlder(prev, page);
    expect(out.map((x) => x.content)).toEqual(["定稿内容", "c4"]);
  });

  it("比新页更旧的已加载消息保留在最前（不是被丢弃）", () => {
    const prev = [m(5, "user")];
    const page = [m(6, "assistant")];
    expect(replaceTailKeepOlder(prev, page).map((x) => x.id)).toEqual([5, 6]);
  });

  it("新页覆盖了全部已加载内容时不残留旧引用", () => {
    const prev = [m(5, "user"), m(6, "assistant")];
    const page = [m(5, "user"), m(6, "assistant"), m(7, "user")];
    const out = replaceTailKeepOlder(prev, page);
    expect(out).toBe(page);
  });

  it("新页为空时保持原状（不把列表清空）", () => {
    const prev = [m(1, "user")];
    expect(replaceTailKeepOlder(prev, [])).toBe(prev);
  });

  it("临时 id 的占位消息不会被当成更早历史留下（避免重复气泡）", () => {
    const ph = newAssistantPlaceholder<M>([]);
    const prev = [m(1, "user"), ph];
    const page = [m(2, "assistant")];
    const out = replaceTailKeepOlder(prev, page);
    expect(out.map((x) => x.id)).toEqual([1, 2]);
    expect(out.some((x) => isTempId(x.id))).toBe(false);
  });
});

describe("mergeOlderMessagesIntoCache", () => {
  it("没有缓存时不产生残缺缓存（宁可离线无缓存）", () => {
    expect(mergeOlderMessagesIntoCache([], [m(50, "user"), m(51, "assistant")])).toBeNull();
  });

  it("把最近一页并入已有全量缓存，不覆盖更早的历史", () => {
    const cached = [m(1, "user"), m(2, "assistant"), m(3, "user")];
    const page = [m(3, "user"), m(4, "assistant"), m(5, "user")];
    expect(mergeOlderMessagesIntoCache(cached, page)!.map((x) => x.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it("重叠消息用新页的版本（覆盖流式期间的中间态）", () => {
    const cached = [m(3, "assistant", "流式中…")];
    const page = [m(3, "assistant", "定稿内容")];
    expect(mergeOlderMessagesIntoCache(cached, page)!.map((x) => x.content)).toEqual(["定稿内容"]);
  });

  it("不把缓存的覆盖范围向更早方向偷偷扩张（否则离线阅读出现空洞）", () => {
    // 缓存只从 id=5 开始；新页含 1..5。若整页并入，缓存会假装覆盖 1..5 而中间是空的。
    const cached = [m(5, "user"), m(6, "assistant"), m(7, "user")];
    const page = [m(1, "user"), m(2, "assistant"), m(3, "user"), m(4, "assistant"), m(5, "user")];
    expect(mergeOlderMessagesIntoCache(cached, page)!.map((x) => x.id)).toEqual([5, 6, 7]);
  });

  it("整页都比缓存新时全部并入并保持 id 升序", () => {
    const out = mergeOlderMessagesIntoCache([m(1, "user")], [m(3, "assistant"), m(2, "user")]);
    expect(out!.map((x) => x.id)).toEqual([1, 2, 3]);
  });

  it("空页不动缓存", () => {
    expect(mergeOlderMessagesIntoCache([m(1, "user")], [])).toBeNull();
  });

  it("缓存里没有数字 id（拿不到 cutoff）时保守跳过", () => {
    expect(mergeOlderMessagesIntoCache([m(null, "user")], [m(1, "user")])).toBeNull();
  });

  it("整页都比缓存旧时不动缓存", () => {
    expect(mergeOlderMessagesIntoCache([m(9, "user")], [m(1, "user"), m(2, "user")])).toBeNull();
  });
});
