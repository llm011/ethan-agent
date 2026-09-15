import { describe, it, expect } from "vitest";
import { collectChangedSessions, type LivePollBaseline } from "@/components/chat/use-live-sessions";

/** 新建一个空基线（第一轮轮询前的状态）。 */
const freshBaseline = (): LivePollBaseline => ({ updatedAt: new Map() });

/** 造 /poll 返回的会话列表项。 */
const sess = (id: string, updated_at: number) => ({ id, updated_at });

describe("collectChangedSessions", () => {
  it("首次见到某会话算「变化」（用于建立基线）", () => {
    const b = freshBaseline();
    expect(collectChangedSessions(b, [sess("a", 100)])).toEqual(["a"]);
  });

  it("updated_at 未前进时不报变化 —— 这是「不会一直白刷」的那条底线", () => {
    const b = freshBaseline();
    collectChangedSessions(b, [sess("a", 100), sess("b", 200)]);
    // 完全相同的输入再来一次：不应有任何变化
    expect(collectChangedSessions(b, [sess("a", 100), sess("b", 200)])).toEqual([]);
  });

  it("updated_at 前进时报出该会话 —— 别处追加一轮、以及本轮跑完落库，都靠这条被发现", () => {
    const b = freshBaseline();
    collectChangedSessions(b, [sess("a", 100), sess("b", 200)]);
    expect(collectChangedSessions(b, [sess("a", 100), sess("b", 999)])).toEqual(["b"]);
  });

  it("一轮「开始」时的时间戳推进同样被报出 —— 后端在每轮开始也 touch 了一次", () => {
    const b = freshBaseline();
    // 会话已跑完、界面停在旧内容上
    collectChangedSessions(b, [sess("a", 100)]);
    // 别处刚发起一轮：后端在 create 时把 updated_at 推到 now（内容还没落库）
    expect(collectChangedSessions(b, [sess("a", 200)])).toEqual(["a"]);
    // 这一轮结束再推一次，同样报出（此时内容才真正到库里）
    expect(collectChangedSessions(b, [sess("a", 300)])).toEqual(["a"]);
  });

  it("列表形状变化（新增别的会话）不会误报当前会话 —— 否则每开一个新会话所有窗口都白刷", () => {
    const b = freshBaseline();
    collectChangedSessions(b, [sess("a", 100), sess("b", 200)]);
    // b 消失、c 新增，但 a 没动：调用方关心的是「我开着的这条变了没」
    const changed = collectChangedSessions(b, [sess("a", 100), sess("c", 300)]);
    expect(changed).not.toContain("a");
    expect(changed).toEqual(["c"]);
  });

  it("多条会话同时变化时全部报出", () => {
    const b = freshBaseline();
    collectChangedSessions(b, [sess("a", 100), sess("b", 200)]);
    expect(collectChangedSessions(b, [sess("a", 111), sess("b", 222)]).sort()).toEqual(["a", "b"]);
  });

  it("基线随每次调用就地推进，不会把同一次变化重复报两遍", () => {
    const b = freshBaseline();
    collectChangedSessions(b, [sess("a", 100)]);
    expect(collectChangedSessions(b, [sess("a", 200)])).toEqual(["a"]);
    expect(collectChangedSessions(b, [sess("a", 200)])).toEqual([]);
  });

  it("长时间运行后清理掉已经消失的会话，避免基线随运行时长无限增长", () => {
    const b = freshBaseline();
    // 灌进远超阈值的会话，且它们在后续轮询里都不再出现
    const many = Array.from({ length: 200 }, (_, i) => sess(`gone-${i}`, i));
    collectChangedSessions(b, many);
    expect(b.updatedAt.size).toBe(200);
    // 之后只剩一条活着的会话：阈值 sessions.length*2+64 被触发，消失的那批应被清掉
    collectChangedSessions(b, [sess("alive", 1)]);
    expect(b.updatedAt.size).toBeLessThan(200);
    expect(b.updatedAt.has("alive")).toBe(true);
  });
});
