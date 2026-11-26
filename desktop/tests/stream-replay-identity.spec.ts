import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consumeStream as consumeDesktop, type ConsumeStreamActions } from "../src/components/chat/use-chat-stream";
import { consumeStream as consumeWeb } from "../../web/components/chat/use-chat-stream";
import type { Message } from "@ethan/shared/chat/types";
import type { StreamChunk } from "../src/lib/api-chat";
import { updateStreamMessage } from "@ethan/shared/chat/stream-message";
import { streamResume } from "@/lib/api-chat";

vi.mock("@/lib/api-chat", () => ({ streamResume: vi.fn(async () => null) }));
vi.mock("@/lib/api-sessions", () => ({ fetchSessionPage: vi.fn(async () => ({ messages: [
  { id: 1, role: "user", content: "hi" }, { id: 42, role: "assistant", content: "main" },
] })) }));
vi.mock("@/components/chat/chat-helpers", () => ({ mapDetailMessages: (detail: { messages: Message[] }) => detail.messages }));

let frameCallbacks: Array<() => void>;
let timerCallbacks: Array<() => void>;
beforeEach(() => {
  frameCallbacks = []; timerCallbacks = [];
  vi.stubGlobal("requestAnimationFrame", (cb: () => void) => frameCallbacks.push(cb));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(globalThis, "setTimeout").mockImplementation(((cb: () => void) => timerCallbacks.push(cb)) as typeof setTimeout);
  vi.spyOn(globalThis, "clearTimeout").mockImplementation(() => {});
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
});

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function harness(deferred = false) {
  let messages: Message[] = [];
  const queued: Array<React.SetStateAction<Message[]>> = [];
  const apply = (next: React.SetStateAction<Message[]>) => { messages = typeof next === "function" ? next(messages) : next; };
  const noop = () => {};
  const actions: ConsumeStreamActions = {
    setMessages: next => { if (deferred) queued.push(next); else apply(next); },
    setConsentRequest: noop, setCleanupConfirm: noop, setAskUserRequest: noop, setWaitForUserRequest: noop,
    setBgPolling: noop, setSessionTitle: noop, setKernelSessionId: noop, setKernelKind: noop,
    setSessionUsage: noop, setStopping: noop, setStreaming: noop, setPendingInjected: noop,
    activeSession: "fixture-session", isSessionActive: () => true,
  };
  return { actions, messages: () => messages, drainOne: () => { if (queued.length) apply(queued.shift()!); },
    drain: () => { while (queued.length) apply(queued.shift()!); } };
}
const user: Message = { id: 1, role: "user", content: "hi" };
async function* chunks(events: StreamChunk[]) { yield* events; }

describe("pure stream identity updater", () => {
  it("is repeatable without mutating input and preserves unrelated identities", () => {
    const persisted: Message = Object.freeze({ id: 42, role: "assistant", content: "saved", created_at: 123 });
    const owned: Message = Object.freeze({ id: "tmp:owned", role: "assistant", content: "live", created_at: 999 });
    const other: Message = Object.freeze({ id: 43, role: "assistant", content: "live" });
    const input = Object.freeze([persisted, owned, other]) as unknown as Message[];
    const update = (previous: Message | undefined): Message => ({ ...previous!, content: "final" });
    const first = updateStreamMessage(input, "tmp:owned", 42, update);
    expect(updateStreamMessage(input, "tmp:owned", 42, update)).toEqual(first);
    expect(updateStreamMessage(first, "tmp:owned", 42, update)).toEqual(first);
    expect(first.map(m => m.id)).toEqual([42, 43]);
    expect(first[0].created_at).toBe(123);
    expect(first[1]).toBe(other);
    expect(input).toEqual([persisted, owned, other]);
  });
});

for (const [name, consume] of [["Desktop", consumeDesktop], ["Web", consumeWeb]] as const) {
  describe(`${name} actual consumeStream replay identity`, () => {
    for (const deferred of [false, true]) {
      it(`coalesces main server ID and placeholder; preserves side and same-text older turn (deferred=${deferred})`, async () => {
        const older: Message = { id: 9, role: "assistant", content: "main" };
        const persisted: Message = { id: 42, role: "assistant", content: "main", model: "saved-model" };
        // Active-run load removes the last persisted side message, not the main row.
        const base = [older, user, persisted];
        const h = harness(deferred);
        await consume(chunks([
          { content: "main" }, { heartbeat: true, elapsed: 1 },
          { new_message: true, content: "side" },
          { done: true, message_id: 42, usage: { input: 1, output: 1 } },
        ]), base, h.actions);
        h.drain();
        expect(h.messages().filter(m => m.id === 42)).toHaveLength(1);
        expect(h.messages().filter(m => m.content === "main")).toHaveLength(2); // two real turns, not three
        expect(h.messages().find(m => m.id === 42)?.model).toBe("saved-model");
        expect(h.messages().filter(m => m.content === "side")).toHaveLength(1);
        expect(h.messages().some(m => typeof m.id === "string" && m.content === "main")).toBe(false);
        // Even an already-delivered callback must not overwrite finalized metadata.
        for (const cb of frameCallbacks) cb();
        h.drain();
        expect(h.messages().find(m => m.id === 42)?.usage?.input).toBe(1);
      });
    }
    it("queued card updater retains its event-time array", async () => {
      const h = harness(true);
      const card = (filename: string) => ({ type: "file", filename, path: filename, size_kb: 1, kind: "txt" });
      await consume(chunks([{ cards: [card("one")] }, { cards: [card("two")] }, { done: true }]), [user], h.actions);
      h.drainOne(); // initial placeholder
      h.drainOne(); // first cards event, not the later final state
      expect(h.messages().find(m => m.role === "assistant")?.cards?.map(c => "filename" in c ? c.filename : "")).toEqual(["one"]);
      h.drain();
      expect(h.messages().find(m => m.role === "assistant")?.cards).toHaveLength(2);
    });
    for (const reconnect of [false, true]) {
      it(`reads done identity without usage and preserves un-replayed server metadata (reconnect=${reconnect})`, async () => {
        const persisted: Message = { id: 42, role: "assistant", content: "main", created_at: 123,
          model: "saved-model", toolSteps: [{ tool: "saved", args: "", state: "done" }],
          usage: { input: 7, output: 8, cache: 9 }, ttft: 12, a2ui: [{ saved: true }],
          mcpApps: [{ uri: "ui://saved" }], matchedSkills: [{ name: "saved" }],
          cards: [{ type: "file", filename: "saved.txt", path: "saved.txt", size_kb: 1, kind: "txt" }],
        };
        const h = harness(true);
        const done = { done: true, message_id: 42 };
        async function* dropped() { throw new Error("SSE connection dropped"); }
        if (reconnect) vi.mocked(streamResume).mockResolvedValueOnce(chunks([done]));
        await consume(reconnect ? dropped() : chunks([done]), [user, persisted], h.actions);
        h.drain();
        expect(h.messages().filter(m => m.role === "assistant")).toHaveLength(1);
        const final = h.messages().find(m => m.id === 42)!;
        expect(final.content).toBe("main");
        expect(final.created_at).toBe(123);
        expect(final.toolSteps).toEqual(persisted.toolSteps);
        expect(final.usage).toEqual(persisted.usage);
        expect(final.ttft).toBe(12);
        expect(final.model).toBe("saved-model");
        expect(final.cards).toEqual(persisted.cards);
        expect(final.a2ui).toEqual(persisted.a2ui);
        expect(final.mcpApps).toEqual(persisted.mcpApps);
        expect(final.matchedSkills).toEqual(persisted.matchedSkills);
      });
    }
    it("promotes its placeholder without changing a later legitimate side message", async () => {
      const h = harness();
      await consume(chunks([{ content: "main" }, { new_message: true, content: "side" },
        { done: true, message_id: 42, usage: { input: 1, output: 1 } }]), [user], h.actions);
      expect(h.messages().map(m => m.content)).toEqual(["hi", "main", "side"]);
      expect(h.messages()[1].id).toBe(42);
      expect(h.messages()[2].id).not.toBe(42);
    });
    for (const timer of [false, true]) {
      it(`fresh-page terminal return blocks even delivered late ${timer ? "timer" : "rAF"}`, async () => {
        const h = harness(true);
        async function* dropped() {
          yield { content: "main" };
          if (timer) { frameCallbacks[0](); yield { content: "" }; yield { content: "more" }; }
          throw new Error("SSE connection dropped");
        }
        await consume(dropped(), [user], h.actions);
        h.drain();
        expect(h.messages().filter(m => m.role === "assistant")).toHaveLength(1);
        expect(timer ? timerCallbacks : frameCallbacks).toHaveLength(1);
        expect(timer ? clearTimeout : cancelAnimationFrame).toHaveBeenCalled();
        for (const cb of [...frameCallbacks, ...timerCallbacks]) cb();
        h.drain();
        expect(h.messages().filter(m => m.role === "assistant")).toHaveLength(1);
        expect(h.messages().find(m => m.id === 42)?.content).toBe("main");
      });
    }
  });
}
