import { describe, it, expect, vi } from "vitest";
import { consumeStream, type ConsumeStreamActions } from "@/components/chat/use-chat-stream";
import type { StreamChunk } from "@/lib/api";

// Helper: create a mock actions object
function mockActions(overrides: Partial<ConsumeStreamActions> = {}): ConsumeStreamActions {
  return {
    setMessages: vi.fn(),
    setConsentRequest: vi.fn(),
    setCleanupConfirm: vi.fn(),
    setAskUserRequest: vi.fn(),
    setWaitForUserRequest: vi.fn(),
    setBgPolling: vi.fn(),
    setSessionTitle: vi.fn(),
    setSessionUsage: vi.fn(),
    setStopping: vi.fn(),
    setStreaming: vi.fn(),
    setPendingInjected: vi.fn(),
    activeSession: "test-session",
    // 默认「一直活跃」，既有用例不受守卫影响。
    isSessionActive: () => true,
    ...overrides,
  };
}

/** 把 setMessages 的多次调用归约成一个最终消息数组（模拟 React 的连续函数式更新）。 */
function finalMessages(setMessages: ConsumeStreamActions["setMessages"]): unknown[] {
  const calls = vi.mocked(setMessages).mock.calls;
  return calls.reduce<unknown[]>((acc, [next]) => {
    return typeof next === "function" ? (next as (p: unknown[]) => unknown[])(acc) : next;
  }, []);
}

// Helper: create an async generator from an array of chunks
async function* chunksToStream(chunks: StreamChunk[]): AsyncGenerator<StreamChunk> {
  for (const chunk of chunks) {
    yield chunk;
  }
}

// Helper: create an async generator that throws
async function* throwingStream(error: Error): AsyncGenerator<StreamChunk> {
  throw error;
}

// Helper: yields some content then throws
async function* contentThenThrow(content: string, error: Error): AsyncGenerator<StreamChunk> {
  yield { content };
  throw error;
}

describe("consumeStream", () => {
  it("returns { failed: false } on normal completion", async () => {
    const stream = chunksToStream([
      { content: "Hello" },
      { content: " world" },
      { done: true, usage: { input: 10, output: 5, cache: 0 } },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: false });
  });

  it("returns { failed: true } when chunk.error is received", async () => {
    const stream = chunksToStream([
      { content: "partial" },
      { error: "Server error occurred" },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: true } when stream throws (connection interrupted)", async () => {
    const stream = throwingStream(new Error("Network failure"));

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: true } when stream throws after partial content", async () => {
    const stream = contentThenThrow("partial content", new Error("Connection reset"));

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: false } when stream is stopped by user", async () => {
    const stream = chunksToStream([
      { content: "Hello" },
      { stopped: true, usage: { input: 10, output: 2, cache: 0 } },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    // stopped is intentional, not a failure
    expect(result).toEqual({ failed: false });
  });

  it("calls setStreaming(false) on completion", async () => {
    const actions = mockActions();
    const stream = chunksToStream([{ done: true }]);

    await consumeStream(stream, [], actions);

    expect(actions.setStreaming).toHaveBeenCalledWith(false);
  });

  it("calls setStreaming(false) even on error", async () => {
    const actions = mockActions();
    const stream = throwingStream(new Error("boom"));

    await consumeStream(stream, [], actions);

    expect(actions.setStreaming).toHaveBeenCalledWith(false);
  });
});

/**
 * 串台回归：会话 A 的流在跑，用户切到会话 B，A 的 chunk 绝不能写进 B 的消息列表。
 *
 * 复现的原始场景：用户发 query → 回复流式输出中 → 切到另一个会话 →
 * 上一个会话的内容出现在新会话里。根因是 consumeStream 全程不判断「这条流还属不属于
 * 当前显示的会话」，且切会话时的 abort 是异步生效的（在途 chunk 仍会被消费）。
 */
describe("consumeStream 会话守卫（串台回归）", () => {
  it("切走会话后，后续 chunk 不再写入消息列表", async () => {
    const actions = mockActions();
    let active = true;
    actions.isSessionActive = () => active;

    // 用「闸门」控制流推进：先吐一个 chunk，切走会话，再吐剩下的。
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    async function* gated(): AsyncGenerator<StreamChunk> {
      yield { content: "A-第一段" };
      await gate;
      yield { content: "A-第二段（切走后）" };
      yield { done: true };
    }

    const p = consumeStream(gated(), [], actions);
    // 让第一段先被消费
    await new Promise((r) => setTimeout(r, 0));

    // 用户切到别的会话
    active = false;
    release();
    await p;

    const msgs = finalMessages(actions.setMessages) as Array<{ content?: string }>;
    const joined = msgs.map((m) => m.content ?? "").join("|");
    // 第一段（切走前）允许写入；切走后的内容必须被丢弃。
    expect(joined).not.toContain("A-第二段");
  });

  it("切走会话后，连占位气泡的整体替换也要丢弃（不能清掉新会话的消息）", async () => {
    const actions = mockActions();
    // 一开始就不活跃：模拟「流启动时用户已经切走」
    actions.isSessionActive = () => false;

    const stream = chunksToStream([{ content: "A" }, { done: true }]);
    await consumeStream(stream, [{ role: "user", content: "B-会话里的消息", created_at: 0 }] as never, actions);

    // 关键：不能发生任何写入，否则会把 B 的消息列表替换成 A 的内容
    expect(actions.setMessages).not.toHaveBeenCalled();
  });

  it("会话仍活跃时行为不变（守卫不误伤正常流）", async () => {
    const actions = mockActions();
    actions.isSessionActive = () => true;

    const stream = chunksToStream([{ content: "正常内容" }, { done: true }]);
    await consumeStream(stream, [], actions);

    const msgs = finalMessages(actions.setMessages) as Array<{ content?: string }>;
    expect(msgs.map((m) => m.content ?? "").join("")).toContain("正常内容");
  });
});

/**
 * 同一类串台的其它出口：标题 / 用量 / 补充信息同为「按会话展示」的状态。
 * 只守卫消息列表是不够的 —— 旧流 done 事件里的标题、token 用量会写到当前显示的会话上，
 * injected_* 会把上一个会话的待处理信息插进当前会话的待处理区。
 */
describe("consumeStream 会话守卫（标题 / 用量 / 补充信息）", () => {
  /** 先让流吐一个 chunk，切走会话（isSessionActive 转 false），再吐 tail 里的事件。 */
  async function runSwitchAway(tail: StreamChunk[]): Promise<ConsumeStreamActions> {
    const actions = mockActions();
    let active = true;
    actions.isSessionActive = () => active;

    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    async function* gated(): AsyncGenerator<StreamChunk> {
      yield { content: "A-第一段" };
      await gate;
      for (const c of tail) yield c;
    }

    const p = consumeStream(gated(), [], actions);
    await new Promise((r) => setTimeout(r, 0));
    active = false; // 用户切到会话 B
    release();
    await p;
    return actions;
  }

  it("切走后，done 里的标题 / 用量不再写到当前会话", async () => {
    const actions = await runSwitchAway([
      { done: true, usage: { input: 100, output: 50, cache: 0 }, title: "A 的标题" },
    ]);

    expect(actions.setSessionTitle).not.toHaveBeenCalled();
    expect(actions.setSessionUsage).not.toHaveBeenCalled();
  });

  it("切走后，补充信息的增删不再动当前会话的待处理区", async () => {
    const actions = await runSwitchAway([
      { injected_added: { id: "i1", content: "A 的补充信息" } },
      { injected_removed: "i2" },
    ]);

    expect(actions.setPendingInjected).not.toHaveBeenCalled();
  });

  it("切走后，标题仍要通知侧边栏（事件按会话 id 定位，不能一起丢掉）", async () => {
    const seen: Array<{ sessionId?: string; title?: string }> = [];
    const onTitle = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener("session:title-updated", onTitle);
    try {
      await runSwitchAway([{ done: true, usage: { input: 1, output: 1, cache: 0 }, title: "A 的标题" }]);
    } finally {
      window.removeEventListener("session:title-updated", onTitle);
    }

    expect(seen).toContainEqual({ sessionId: "test-session", title: "A 的标题" });
  });

  it("会话仍活跃时，标题 / 用量 / 补充信息照常写入（守卫不误伤）", async () => {
    const actions = mockActions();

    await consumeStream(
      chunksToStream([
        { injected_added: { id: "i1", content: "补充信息" } },
        { done: true, usage: { input: 1, output: 2, cache: 0 }, title: "标题" },
      ]),
      [],
      actions,
    );

    expect(actions.setSessionTitle).toHaveBeenCalledWith("标题");
    expect(actions.setSessionUsage).toHaveBeenCalled();
    expect(actions.setPendingInjected).toHaveBeenCalled();
  });
});
