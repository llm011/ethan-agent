/**
 * 「点 + 新建会话」的路由行为回归测试。
 *
 * 背景（真实 bug）：桌面端在新会话首次发送时才懒创建 session，创建后用
 * `window.history.replaceState(null, "", "/chat/<id>/")` 直接改写 URL。这一步绕过
 * HashRouter（它的 history 是内部维护的，不监听 popstate/hashchange），于是 router
 * 内部 location 仍停在「已是 /chat 时创建会话」之后与真实 URL 失步。之后点「+」执行
 * `navigate("/chat")`，router 认为自己已经在 /chat → 导航成为空操作 → 界面无响应。
 *
 * 修复：开新会话统一走虚拟路由 `/chat/new`（永远与当前 location 不同，一定是真实
 * 跳转），且创建会话后用 `navigate("/chat/<id>", { replace: true })` 而不是
 * replaceState，让 router 状态保持同步。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createMemoryRouter, RouterProvider, useParams } from "react-router-dom";
import { render, screen, act, waitFor } from "@testing-library/react";
import { handleCommand } from "@/components/chat/chat-commands";

// createSession 打后端，这里替换成固定返回值。
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createSession: vi.fn(async () => ({ id: "sess-new", title: "新对话" })) };
});

const noop = () => {};

/** 构造 handleCommand 的最小 actions。navigate 由用例注入以便断言。 */
function makeActions(overrides: Partial<Parameters<typeof handleCommand>[1]> = {}) {
  return {
    setMessages: (() => {}) as any,
    setActiveSession: noop,
    setSessionTitle: noop,
    setSessionUsage: noop,
    setPendingFiles: noop,
    setQuote: noop,
    setStreaming: noop,
    selectedModel: "m",
    mode: "default",
    activeSession: "sess-old",
    navigate: vi.fn(),
    ...overrides,
  } as Parameters<typeof handleCommand>[1] & { navigate: ReturnType<typeof vi.fn> };
}

describe("handleCommand /new", () => {
  beforeEach(() => {
    // 即使环境提供了 history，也确保 replaceState 不被调用（修复后不应再依赖它）。
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
  });

  it("走 router navigate 而不是 window.history.replaceState", async () => {
    const actions = makeActions();
    await handleCommand("/new", actions);

    // 核心断言：修复前这里调的是 replaceState，router 会失步。
    expect(actions.navigate).toHaveBeenCalledWith("/chat/sess-new", { replace: true });
    expect(window.history.replaceState).not.toHaveBeenCalled();
  });

  it("replace 语义：不产生额外历史项（调用方传 replace:true）", async () => {
    const actions = makeActions();
    await handleCommand("/new", actions);

    const [, opts] = actions.navigate.mock.calls[0];
    expect(opts).toEqual({ replace: true });
  });

  it("清空当前会话状态（消息 / 输入 / 引用 / 用量）", async () => {
    const setMessages = vi.fn();
    const setSessionUsage = vi.fn();
    const setQuote = vi.fn();
    const setPendingFiles = vi.fn();
    const setActiveSession = vi.fn();

    await handleCommand("/new", makeActions({
      setMessages, setSessionUsage, setQuote, setPendingFiles, setActiveSession,
    }));

    expect(setMessages).toHaveBeenCalledWith([]);
    expect(setSessionUsage).toHaveBeenCalledWith({ input: 0, output: 0, cache: 0 });
    expect(setQuote).toHaveBeenCalledWith(null);
    expect(setPendingFiles).toHaveBeenCalledWith([]);
    expect(setActiveSession).toHaveBeenCalledWith("sess-new");
  });
});

/**
 * 路由层面的回归：`/chat/new` 必须是和「已在会话中」不同的真实路径，且要映射成
 * 「空会话」（initialSessionId = undefined）。这里用一个探针组件断言 useParams 的
 * 取值，覆盖「已在一个会话里再点 +」这个原始复现场景。
 */
describe("路由 /chat/new", () => {
  /** 复刻 App.tsx 的 ChatRoute 映射：字面量 "new" → undefined（空会话）。 */
  const mapParams = (sessionId: string | undefined) =>
    sessionId === "new" ? undefined : sessionId;

  function Probe() {
    const { sessionId } = useParams<{ sessionId?: string }>();
    // 用具名哨兵而不是 JSON.stringify：后者对 undefined 返回 undefined，React 会
    // 渲染成空串，断言就看不出「映射成了空会话」。
    const mapped = mapParams(sessionId);
    return <div data-testid="sid">{mapped === undefined ? "EMPTY" : mapped}</div>;
  }

  const routes = [
    { path: "/chat/new", element: <Probe /> },
    { path: "/chat/:sessionId", element: <Probe /> },
    { path: "/chat", element: <Probe /> },
  ];

  it("'new' 被当作虚拟路由（静态段优先于 :sessionId），映射为空会话", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/chat/new"] });
    render(<RouterProvider router={router} />);

    // 静态段 /chat/new 必须优先于 /chat/:sessionId —— 否则 "new" 会被当成 sessionId，
    // ChatView 会去拉一个不存在的会话。这里同时锁住路由优先级与 → undefined 的映射。
    expect(screen.getByTestId("sid").textContent).toBe("EMPTY");
    expect(router.state.matches.at(-1)?.params).toEqual({});
  });

  it("从 /chat/<id> 导航到 /chat/new 会真正改变 location（不再被当作空操作）", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/chat/sess-old"] });
    render(<RouterProvider router={router} />);
    expect(router.state.location.pathname).toBe("/chat/sess-old");

    act(() => { void router.navigate("/chat/new"); });

    // 修复前：创建会话用的 replaceState 绕过 HashRouter，使其内部 location 失步；
    // 之后 navigate("/chat") 被判为「已在 /chat」→ 空操作。现在 /chat/new 是一个与
    // 当前 location 不同的真实路径，导航一定生效，且映射成空会话。
    await waitFor(() => expect(router.state.location.pathname).toBe("/chat/new"));
    expect(mapParams(router.state.matches.at(-1)?.params.sessionId as string)).toBeUndefined();
  });
});
