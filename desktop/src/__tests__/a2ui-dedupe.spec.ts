import { describe, it, expect } from "vitest";
import { dedupeSurfaceIds } from "@/components/chat/a2ui-dedupe";

type Msg = Record<string, unknown>;
const create = (sid: string): Msg => ({ createSurface: { surfaceId: sid } });
const update = (sid: string): Msg => ({ updateComponents: { surfaceId: sid } });
const updateData = (sid: string): Msg => ({ updateDataModel: { surfaceId: sid } });
const del = (sid: string): Msg => ({ deleteSurface: { surfaceId: sid } });

const ids = (msgs: Msg[], kind: string) =>
  msgs.filter((m) => m[kind]).map((m) => (m[kind] as { surfaceId: string }).surfaceId);

describe("dedupeSurfaceIds", () => {
  it("无重复 surfaceId 时是 no-op", () => {
    const msgs = [create("a"), update("a"), create("b"), update("b")];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["a", "b"]);
    expect(ids(msgs, "updateComponents")).toEqual(["a", "b"]);
  });

  it("两张同 surfaceId 卡各自独立", () => {
    const msgs = [create("t"), update("t"), create("t"), update("t")];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2"]);
    expect(ids(msgs, "updateComponents")).toEqual(["t", "t-2"]);
  });

  it("三张同 surfaceId 卡：副本独立编号，update 跟随自己的 create", () => {
    const msgs = [
      create("t"), update("t"),
      create("t"), update("t"),
      create("t"), update("t"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2", "t-3"]);
    expect(ids(msgs, "updateComponents")).toEqual(["t", "t-2", "t-3"]);
  });

  it("同一张副本卡的多次 update 都路由到该副本", () => {
    const msgs = [
      create("t"), update("t"),
      create("t"), update("t"), updateData("t"), update("t"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2"]);
    expect(ids(msgs, "updateComponents")).toEqual(["t", "t-2", "t-2"]);
    expect(ids(msgs, "updateDataModel")).toEqual(["t-2"]);
  });

  it("先集中 create 再集中 update：内容摊到各卡，不全挤在最后一张", () => {
    const msgs = [
      create("t"), create("t"), create("t"),
      update("t"), update("t"), update("t"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2", "t-3"]);
    const routed = ids(msgs, "updateComponents");
    // 归属本身二义，但保证：每张卡恰好分到一个 update（不再全挤到 t-3）
    expect(new Set(routed)).toEqual(new Set(["t", "t-2", "t-3"]));
    expect(routed).toHaveLength(3);
  });

  it("集中 create 后的多轮 update：先摊开再回到活跃实例", () => {
    const msgs = [
      create("t"), create("t"),
      update("t"), update("t"), update("t"), update("t"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2"]);
    // 第 1 个 update → 活跃副本 t-2；第 2 个回退到未更新的 t；之后都回到活跃副本
    expect(ids(msgs, "updateComponents")).toEqual(["t-2", "t", "t-2", "t-2"]);
  });

  it("不同 surfaceId 交错互不干扰", () => {
    const msgs = [
      create("a"), create("b"),
      update("a"), update("b"),
      create("a"), update("a"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["a", "b", "a-2"]);
    expect(ids(msgs, "updateComponents")).toEqual(["a", "b", "a-2"]);
  });

  it("deleteSurface 跟随最近一次 createSurface 的实例", () => {
    const msgs = [
      create("t"), update("t"),
      create("t"), update("t"), del("t"),
    ];
    dedupeSurfaceIds(msgs);
    expect(ids(msgs, "createSurface")).toEqual(["t", "t-2"]);
    expect(ids(msgs, "deleteSurface")).toEqual(["t-2"]);
  });

  it("显式使用 sid-2 作为真实 id 时不与生成的副本 id 撞车", () => {
    const msgs = [
      create("t"), create("t"),   // 生成副本 t-2
      create("t-2"),              // 显式的 t-2 必须被改写成不冲突的 id
      update("t-2"),
    ];
    dedupeSurfaceIds(msgs);
    const created = ids(msgs, "createSurface");
    expect(new Set(created).size).toBe(3);
    expect(created[2]).toBe("t-2-2");
    expect(ids(msgs, "updateComponents")).toEqual(["t-2-2"]);
  });
});
