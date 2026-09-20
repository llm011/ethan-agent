import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import { createRef, createElement, useRef, useState } from "react";
import { QueryDots } from "@/components/chat/query-dots";
import { MessageList } from "@/components/chat/message-list";
import type { Message } from "@ethan/shared/chat/types";

// MessageList 里每条消息都包了 MessageBubble（依赖 markdown/katex/tauri 等一大坨）。
// 这里替换成极简替身：本文件测的是「圆点 → 定位到 data-msg-idx」这条链路，
// 消息内容怎么渲染无关紧要。
vi.mock("@/components/chat/message-bubble", () => ({
  MessageBubble: ({ msg }: { msg: Message }) =>
    createElement("div", { className: "bubble" }, String(msg.content)),
}));

function msg(id: number, role: "user" | "assistant"): Message {
  return { id, role, content: `m${id}` } as Message;
}

/** 造 n 轮对话（user/assistant 交替）。 */
function conversation(turns: number): Message[] {
  const out: Message[] = [];
  for (let i = 0; i < turns; i++) {
    out.push(msg(i * 2, "user"));
    out.push(msg(i * 2 + 1, "assistant"));
  }
  return out;
}

let scrollToSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // jsdom 没实现 scrollTo（是 undefined，直接调用会抛错）
  scrollToSpy = vi.fn();
  Object.defineProperty(Element.prototype, "scrollTo", {
    value: scrollToSpy,
    writable: true,
    configurable: true,
  });
  // MessageList 用 IntersectionObserver 做上滚触顶加载；jsdom 没有它。
  // 这里给个不会真正触发的空实现——本文件不测「上滚加载更多」那条路径，
  // 只测圆点导航。
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** 点第 n 个圆点（圆点按 user 消息顺序排列）。 */
function clickDot(n: number) {
  const dots = screen.getAllByRole("button");
  act(() => {
    fireEvent.click(dots[n]);
  });
}

// ── 直接测 QueryDots 的点击语义（真实组件，非复刻） ──────────────────

describe("QueryDots 点击跳转", () => {
  it("已渲染范围内：滚到目标位置并通知父组件", () => {
    const onBeforeScroll = vi.fn();
    const scrollRef = createRef<HTMLDivElement>();
    const messages = conversation(4); // 8 条，全部渲染

    render(
      <div>
        <div ref={scrollRef}>
          {messages.map((m, i) => (
            <div key={String(m.id)} data-msg-idx={i}>
              {String(m.content)}
            </div>
          ))}
        </div>
        <QueryDots
          messages={messages}
          startIdx={0}
          scrollRef={scrollRef}
          onBeforeScroll={onBeforeScroll}
        />
      </div>
    );

    clickDot(0);

    expect(scrollToSpy).toHaveBeenCalledTimes(1);
    expect((scrollToSpy.mock.calls[0][0] as { top: number }).top).toBe(0);
    expect(onBeforeScroll).toHaveBeenCalled();
  });

  it("目标未渲染：以目标下标请求展开（而不是静默 return）", () => {
    const onNeedOlder = vi.fn();
    const scrollRef = createRef<HTMLDivElement>();
    const messages = conversation(10); // 20 条，只渲染末尾 10 条 → startIdx=10

    render(
      <div>
        <div ref={scrollRef}>
          {messages.slice(10).map((m, i) => (
            <div key={String(m.id)} data-msg-idx={10 + i}>
              {String(m.content)}
            </div>
          ))}
        </div>
        <QueryDots
          messages={messages}
          startIdx={10}
          scrollRef={scrollRef}
          onNeedOlder={onNeedOlder}
        />
      </div>
    );

    clickDot(0);

    expect(onNeedOlder).toHaveBeenCalledWith(0);
    expect(scrollToSpy).not.toHaveBeenCalled(); // 还没渲染，先别滚
  });

  it("连续点击只让最后一次生效（前一个重试链被作废）", async () => {
    const scrollRef = createRef<HTMLDivElement>();
    const messages = conversation(10);
    // 场景：先点 idx=0（未渲染，进入等待），再点已渲染的 idx=18
    const { container } = render(
      <div>
        <div ref={scrollRef}>
          {messages.slice(10).map((m, i) => (
            <div key={String(m.id)} data-msg-idx={10 + i}>
              {String(m.content)}
            </div>
          ))}
        </div>
        <QueryDots
          messages={messages}
          startIdx={10}
          scrollRef={scrollRef}
          onNeedOlder={() => {
            /* 故意不展开：模拟目标始终进不了 DOM */
          }}
        />
      </div>
    );

    const dots = screen.getAllByRole("button");
    act(() => {
      fireEvent.click(dots[0]); // idx=0，未渲染 → 进入重试链
    });
    act(() => {
      fireEvent.click(dots[9]); // idx=18，已渲染 → 立即滚
    });

    expect(scrollToSpy).toHaveBeenCalledTimes(1);
    // 等一段时间，确认过期的那条重试链不会再补一次滚动
    await new Promise((r) => setTimeout(r, 300));
    expect(scrollToSpy).toHaveBeenCalledTimes(1);
  });

  it("少于 2 条 user 消息时不渲染圆点", () => {
    const scrollRef = createRef<HTMLDivElement>();
    const { container } = render(
      <div>
        <div ref={scrollRef} />
        <QueryDots
          messages={[msg(0, "user"), msg(1, "assistant")]}
          startIdx={0}
          scrollRef={scrollRef}
        />
      </div>
    );
    expect(container.querySelectorAll("button").length).toBe(0);
  });
});

// ── 测真实 MessageList：展开语义必须真的到位 ────────────────────────
// 上面那组用的是「自己搭的容器」，测不到 MessageList 里的 handleDotsNeedOlder。
// 这组直接渲染真组件，确保「目标早好几屏」时一次展开到位的实现是对的。

describe("MessageList 圆点导航（真实组件）", () => {
  it("首屏只渲染末尾 10 条，圆点仍覆盖全部 user 消息", () => {
    const messages = conversation(10); // 20 条
    const { container } = render(<MessageList messages={messages} streaming={false} />);

    expect(container.querySelector('[data-msg-idx="0"]')).toBeNull();
    expect(container.querySelector('[data-msg-idx="19"]')).not.toBeNull();
    // 10 个圆点（每轮一个 user 消息）
    expect(screen.getAllByRole("button").length).toBe(10);
  });

  it("目标早好几屏时一次展开到位并滚过去（回归：只展开一屏会失败）", async () => {
    // 40 轮 = 80 条消息，点 idx=0 需要从 startIdx=70 一次扩到 0
    const messages = conversation(40);
    const { container } = render(<MessageList messages={messages} streaming={false} />);

    expect(container.querySelector('[data-msg-idx="0"]')).toBeNull();

    clickDot(0);

    // 必须最终滚成功——若 handleDotsNeedOlder 只 +LOAD_MORE_COUNT，
    // 展开一次后 idx=0 仍不在 DOM，这里会超时失败。
    await waitFor(() => expect(scrollToSpy).toHaveBeenCalled());
    expect(container.querySelector('[data-msg-idx="0"]')).not.toBeNull();
  });

  it("目标在当前屏内：直接滚动，不展开", () => {
    const messages = conversation(3); // 6 条，全部渲染
    render(<MessageList messages={messages} streaming={false} />);

    clickDot(0);

    expect(scrollToSpy).toHaveBeenCalled();
  });
});

// ── programmaticScrollRef 兜底复位（回归：只置位不复位会锁死跟随） ────
// 针对 review 指出的第二个问题：圆点跳到页面中部时 near=false，原来那个
// 「滚到接近底部才复位」的分支永远等不到，flag 会一直挂着 → 之后用户手动上滑
// 也解除不了 stickToBottom（onScroll 直接 return），流式更新反复把视图拽回底部。
//
// 这里用真实 MessageList 走一遍：进入锁定态 → 圆点跳转（置 flag）→ 等兜底复位
// → 用户手动滚到中部 → 断言锁定确实被解除。
//
// 注意：点「滚到底部」后 isAtBottom=true 会让按钮消失，所以「是否锁定」不能靠
// 按钮文案判断，要靠**之后手动上滑能否解除**来验证 —— 这也正是这个 bug 的后果。

describe("圆点跳转后跟随锁定仍可解除", () => {
  /** 造一个「可滚动」的容器并返回它。 */
  function setup() {
    const messages = conversation(5); // 10 条，全部渲染
    const { container } = render(<MessageList messages={messages} streaming={false} />);
    const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
    Object.defineProperty(scroller, "scrollHeight", { value: 2000, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 400, configurable: true });
    return { container, scroller, messages };
  }

  it("跳转后用户手动上滑：能解除 stickToBottom 锁定", async () => {
    const { scroller } = setup();

    // 1) 进入锁定态：先滚到顶部让按钮出现，再点它
    act(() => {
      scroller.scrollTop = 0;
      fireEvent.scroll(scroller);
    });
    act(() => {
      fireEvent.click(screen.getByTitle("滚动到底部并跟随"));
    });

    // 2) 圆点跳转：调用 onBeforeScroll → 置 programmaticScrollRef=true
    clickDot(0);

    // 3) 等实现的 800ms 兜底复位窗口过去
    await new Promise((r) => setTimeout(r, 900));

    // 4) 用户手动滚到中部（near=false）——若不是「真·用户滚动」被 flag 拦掉，
    //    锁定必须解除，按钮应重新以「滚动到底部并跟随」出现。
    act(() => {
      scroller.scrollTop = 500; // 2000-500-400=1100 → near=false
      fireEvent.scroll(scroller);
    });

    await waitFor(() =>
      expect(screen.getByTitle("滚动到底部并跟随")).toBeTruthy()
    );
  });
});
