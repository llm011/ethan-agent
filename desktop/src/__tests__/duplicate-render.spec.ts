import { describe, it, expect, vi } from "vitest";
import { consumeStream, type ConsumeStreamActions } from "@/components/chat/use-chat-stream";
import type { StreamChunk } from "@/lib/api";
import type { Message } from "@ethan/shared/chat/types";
import { isTempId } from "@ethan/shared/chat/history";

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
    isSessionActive: () => true,
    ...overrides,
  };
}

/**
 * 把 setMessages 的多次调用归约成最终消息数组。
 *
 * 必须模拟 React 的**单一累加器**语义：调用 updater 时传入「上一次调用的返回值」，
 * 而不是每次都从空数组起步。updater 天然是纯函数（`setMessages(prev => next)`），
 * 所以只要调用序列一致，累加结果就与真实渲染一致。
 *
 * 注意不能改成「每条 updater 都拿初始值跑一遍再取最后一个」——那会漏掉本流内多次
 * 写入之间的叠加（例如先 push 占位、再就地更新同一条），得出「只有一条消息」的假象。
 */
function finalMessages(setMessages: ConsumeStreamActions["setMessages"]): Message[] {
  const calls = vi.mocked(setMessages).mock.calls;
  let acc: Message[] = [];
  for (const [next] of calls) {
    acc = typeof next === "function" ? (next as (p: Message[]) => Message[])(acc) : (next as Message[]);
  }
  return acc;
}

async function* chunksToStream(chunks: StreamChunk[]): AsyncGenerator<StreamChunk> {
  for (const chunk of chunks) yield chunk;
}

/** 让在途的节流 flush 到期（FLUSH_INTERVAL_MS = 50）。 */
const settle = () => new Promise((r) => setTimeout(r, 120));

/**
 * 「同一条助手回复渲染成两个气泡」回归。
 *
 * 现象：桌面端偶发同一条回复出现两份，点界面上的「刷新」后恢复正常。
 * 刷新能修好 ⇒ 落库数据是对的，重复只发生在内存/渲染态 ⇒ 客户端状态机的 bug。
 *
 * 根因：`buildMsg()` 重建助手消息时**不带 `id`**，而 `flushAssistant()` 是
 * 「整条替换」而不是「合并」：
 *
 *   next[next.length - 1] = msg;      // msg 没有 id
 *
 * 占位气泡在流式期间靠 `makeTempId()` 拿到稳定 React key（`tmp:xxx`）。只要
 * **在正文到达之前**发生一次整条替换，占位 id 就被抹掉了，`MessageList` 的
 *   key={msg.id ?? `idx-${startIdx + i}`}
 * 于是退化成下标 key。走这条路径的事件不止一个：
 *
 *  - `heartbeat`（长任务每 N 秒一次「任务仍在运行中…」）—— 最常触发：
 *    后台任务动辄十几分钟，正文迟迟不来，心跳却一直在刷，第一次心跳就把 id 抹了；
 *  - 工具 `start` / `done`（`flushAssistant()` / `flushAssistant({cards})`）；
 *  - 顶层 `cards` 事件。
 *
 * id 一丢，key 就从 `tmp:xxx` 变成 `idx-N`。key 变了 React 卸载重建：markdown
 * 全量重解析、代码块重新高亮，列表滚动锚点丢失。更糟的是下标 key 在同一个列表里
 * 可能**撞车**（两处都算成同一个 idx），React 会把两个兄弟节点折叠/重复渲染，
 * 用户看到的就是「同一条回复出现两份」。
 *
 * 而且这个丢失是**不可恢复**的：`_lastFlushAt` 之外的每次 flush 都基于上一次的
 * 结果再整条替换，占位 id 再也没有回来；定稿的 `id: messageId ?? last.id` 此时
 * `last.id` 已是 `undefined`，后端又没给 `message_id`（无工具无正文的路径
 * `producers.py` 里 `msg_id` 可以为 None）⇒ 定稿后 id 仍是 undefined。
 * 用户点「刷新」重新从 DB 拉历史，id 也就回来了，重复随之消失 —— 与现象完全吻合。
 */
describe("consumeStream 重复渲染回归（同一条回复出现两个气泡）", () => {
  it("心跳在正文之前到达时，占位 id 不能被抹掉（否则 React key 塌成下标）", async () => {
    const actions = mockActions();
    // 长任务真实序列：先 model，再心跳，正文姗姗来迟。
    const stream = chunksToStream([
      { model: "gpt-x" },
      { heartbeat: true, elapsed: 5 },
      { content: "最终回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const msgs = finalMessages(actions.setMessages);
    const assistants = msgs.filter((m) => m.role === "assistant");
    // 只有一条：整条替换绝不能变成「追加第二条」
    expect(assistants).toHaveLength(1);
    // 且必须拿到稳定 key：不是 undefined / null，而是可用的 id
    expect(assistants[0].id == null).toBe(false);
  });

  it("心跳写下的占位气泡同样继承占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { heartbeat: true, elapsed: 5 },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("工具 start 事件在正文之前到达时也要保住占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { tool: "read_file", state: "start", id: "t1" },
      { content: "最终回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("顶层 cards 事件在正文之前到达时也要保住占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { cards: [{ type: "file", filename: "a.pdf", path: "/tmp/a.pdf", size_kb: 1, kind: "pdf" }] },
      { content: "最终回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("纯 model 事件在正文之前到达时也要保住占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { model: "gpt-x" },
      { content: "最终回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("后端给了真实 message_id 时要提升成数字 id（流式期间也是同一个）", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { heartbeat: true, elapsed: 3 },
      { content: "回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 }, message_id: 42 },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id).toBe(42);
  });

  it("后端未给 message_id 时，定稿必须保留占位临时 id（不能写成 undefined）", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { content: "完整回复" },
      // 无工具、无正文的路径后端 msg_id 可以为 None，done 不带 message_id
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id).toBeDefined();
    expect(isTempId(assistants[0].id)).toBe(true);
  });

  it("整个流式过程中，占位气泡的 id 从头到尾保持不变（key 不塌陷）", async () => {
    const actions = mockActions();
    // 记录每一次写入的最后一条 assistant 的 id，要求「出现了就必须一致」。
    const seenIds: Array<string | number | undefined> = [];
    let acc: Message[] = [];
    (actions.setMessages as unknown as (x: unknown) => void) = vi.fn((x: unknown) => {
      acc = typeof x === "function" ? (x as (p: Message[]) => Message[])(acc) : (x as Message[]);
      const assistants = acc.filter((m) => m.role === "assistant");
      if (assistants.length > 0) seenIds.push(assistants[assistants.length - 1].id);
    });

    const stream = chunksToStream([
      { model: "gpt-x" },
      { heartbeat: true, elapsed: 5 },
      { tool: "read_file", state: "start", id: "t1" },
      { tool: "read_file", state: "done", id: "t1" },
      { content: "最终回复" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    expect(seenIds.length).toBeGreaterThan(3);
    // 只要有 id 出现过，后续每一次写入都必须带着同一个 id
    const firstDefined = seenIds.find((id) => id != null);
    expect(firstDefined).toBeDefined();
    // 初始化时 liveId 就是 placeholderId，因此这里等价于「全程等于 placeholderId」
    expect(seenIds[0]).toBe(firstDefined);
    for (const id of seenIds) {
      expect(id).toBe(firstDefined);
    }
  });

  it("流被 stopped 打断：只留一个气泡，且不丢占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { heartbeat: true, elapsed: 3 },
      { content: "写了一半" },
      { stopped: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("流报错中断：只留一个气泡，且不丢占位 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { heartbeat: true, elapsed: 3 },
      { content: "写了一半" },
      { error: "服务端错误" },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id == null).toBe(false);
  });

  it("断线重连后，迟到的定时 flush 不得再追加第二条助手气泡", async () => {
    const actions = mockActions();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.reject(new Error("offline")) as unknown as ReturnType<typeof fetch>);
    try {
      // 主循环只吐一个 content（触发 50ms 后的定时 flush），紧接着抛网络错误。
      // 重连期间不再有内容进来 —— 迟到的 flush 绝不能凭旧闭包再写一条新气泡。
      async function* dropped(): AsyncGenerator<StreamChunk> {
        yield { content: "第一段" };
        throw new Error("SSE connection dropped");
      }

      await consumeStream(dropped(), [], actions);
      await settle();

      const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
      expect(assistants).toHaveLength(1);
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("同一分片被重复投递（SSE 重放）时不会凭空多出气泡", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { content: "重复内容" },
      { content: "重复内容" },
      { done: true, usage: { input: 1, output: 1, cache: 0 }, message_id: 7 },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(1);
  });

  it("刷新后重建列表：同一条消息只出现一次（占位 id 与真实 id 不共存）", async () => {
    // 刷新场景：ChatView 会先用 baseMessages（含上一轮定稿的消息）起流，
    // 定稿时占位气泡被就地替换，绝不能既留占位又追加定稿版。
    const actions = mockActions();
    const base: Message[] = [
      { role: "user", content: "问题", created_at: 1 },
      { role: "assistant", content: "上一轮回复", created_at: 2, id: 1 },
    ];
    const stream = chunksToStream([
      { content: "这一轮" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, base, actions);
    await settle();

    const msgs = finalMessages(actions.setMessages);
    expect(msgs.filter((m) => m.role === "assistant")).toHaveLength(2);
    expect(msgs.filter((m) => m.content === "上一轮回复")).toHaveLength(1);
    expect(msgs.filter((m) => m.content === "这一轮")).toHaveLength(1);
  });

  it("列表里绝不能出现两条内容相同的助手消息", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { heartbeat: true, elapsed: 5 },
      { content: "只应出现一次" },
      { done: true, usage: { input: 1, output: 1, cache: 0 } },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const msgs = finalMessages(actions.setMessages);
    expect(msgs.filter((m) => m.role === "assistant")).toHaveLength(1);
    expect(msgs.filter((m) => m.content === "只应出现一次")).toHaveLength(1);
  });
});

/**
 * `chunk.new_message` 旁路消息（getnote 推送）回归。
 *
 * 这条分支往列表末尾 push 一条 assistant 气泡。若它不带自己的 id，就会与占位气泡
 * 一起退化成下标 key；更严重的是「按末位更新」的 flushAssistant / 定稿会**改错对象**：
 * 把主流的正文写进旁路消息、把占位 id 盖上去 —— 两条兄弟节点同 key，
 * React 折叠/重复渲染，正是本 PR 要修的那类现象。
 */
describe("consumeStream new_message 旁路消息回归", () => {
  it("旁路消息必须有自己的 id，不能与占位气泡撞 key", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { content: "主回复" },
      { new_message: true, content: "推送的新消息" },
      { done: true, usage: { input: 1, output: 1, cache: 0 }, message_id: 55 },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    const ids = assistants.map((m) => m.id ?? null);
    // 任何人都不能没有 id（否则 key 退化成下标）
    expect(ids.every((v) => v != null)).toBe(true);
    // 且 id 必须两两互不相同（同 key 会让 React 折叠/重复渲染）
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("旁路消息不得被主流的正文覆盖（flushAssistant 不能改错对象）", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { content: "主回复" },
      { new_message: true, content: "推送的新消息" },
      { content: "续写" },
      { done: true, usage: { input: 1, output: 1, cache: 0 }, message_id: 55 },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const msgs = finalMessages(actions.setMessages);
    // 旁路消息保持自己的内容
    const pushed = msgs.filter((m) => m.content === "推送的新消息");
    expect(pushed).toHaveLength(1);
    // 主流正文完整落在同一个气泡里（没有被拆到两条上）
    expect(msgs.filter((m) => m.content.includes("主回复")).length).toBeGreaterThanOrEqual(1);
    expect(msgs.filter((m) => m.content === "主回复续写")).toHaveLength(1);
  });

  it("主流气泡拿到真实 id，旁路消息仍保持自己的 id", async () => {
    const actions = mockActions();
    const stream = chunksToStream([
      { content: "主回复" },
      { new_message: true, content: "推送" },
      { done: true, usage: { input: 1, output: 1, cache: 0 }, message_id: 55 },
    ]);

    await consumeStream(stream, [], actions);
    await settle();

    const assistants = finalMessages(actions.setMessages).filter((m) => m.role === "assistant");
    // 主流那条提升为真实 id；旁路消息不是 55，也不能被 55 覆盖
    expect(assistants.filter((m) => m.id === 55)).toHaveLength(1);
    expect(assistants.filter((m) => m.content === "推送")).toHaveLength(1);
    const pushed = assistants.find((m) => m.content === "推送")!;
    expect(pushed.id).not.toBe(55);
  });
});
