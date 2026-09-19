import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { createRef } from "react";
import { QueryDots } from "@/components/chat/query-dots";
import type { Message } from "@ethan/shared/chat/types";

function msg(id: number, role: "user" | "assistant"): Message {
  return { id, role, content: `m${id}` } as Message;
}

/** 造 n 轮对话（user/assistant 交替），返回消息数组。 */
function conversation(turns: number): Message[] {
  const out: Message[] = [];
  for (let i = 0; i < turns; i++) {
    out.push(msg(i * 2, "user"));
    out.push(msg(i * 2 + 1, "assistant"));
  }
  return out;
}

/**
 * 复刻 message-list 的渲染方式：只渲染末尾 visibleCount 条，且 data-msg-idx
 * 用的是「全量坐标系」（startIdx + i）。QueryDots 必须按同一坐标系查找，
 * 否则圆点会指向不存在的节点、点击静默无反应。
 */
function Harness({
  messages,
  visibleCount,
}: {
  messages: Message[];
  visibleCount: number;
}) {
  const scrollRef = createRef<HTMLDivElement>();
  const hasMore = messages.length > visibleCount;
  const startIdx = hasMore ? messages.length - visibleCount : 0;
  const visible = messages.slice(startIdx);

  return (
    <div>
      <div ref={scrollRef} data-testid="scroll">
        {visible.map((m, i) => (
          <div key={String(m.id)} data-msg-idx={startIdx + i}>
            {String(m.content)}
          </div>
        ))}
      </div>
      <QueryDots
        messages={messages}
        startIdx={startIdx}
        scrollRef={scrollRef}
        onNeedOlder={hasMore ? () => onNeedOlder() : undefined}
        onBeforeScroll={onBeforeScroll}
      />
    </div>
  );
}

const onNeedOlder = vi.fn();
const onBeforeScroll = vi.fn();

beforeEach(() => {
  onNeedOlder.mockClear();
  onBeforeScroll.mockClear();
  // jsdom 没有实现 scrollTo / offsetTop
  Element.prototype.scrollTo = vi.fn() as unknown as Element["scrollTo"];
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("QueryDots 点击跳转", () => {
  it("已渲染范围内的圆点：直接滚动，不触发分页", () => {
    // 4 轮 = 8 条消息，全部渲染（visibleCount=10 > 8 → startIdx=0）
    const messages = conversation(4);
    render(<Harness messages={messages} visibleCount={10} />);

    const dots = screen.getAllByRole("button");
    // 第 1 个圆点 → 第 1 条 user 消息（idx 0）
    act(() => {
      fireEvent.click(dots[0]);
    });

    expect(onBeforeScroll).toHaveBeenCalled();
    expect(onNeedOlder).not.toHaveBeenCalled();
  });

  it("目标在未渲染的更早一屏：先展开分页再滚动（回归：曾静默无反应）", async () => {
    // 10 轮 = 20 条消息，只渲染末尾 10 条 → startIdx=10，idx 0 不在 DOM 里
    const messages = conversation(10);
    const { container } = render(<Harness messages={messages} visibleCount={10} />);

    // 前置断言：idx=0 确实没被渲染（这正是 bug 的触发条件）
    expect(container.querySelector('[data-msg-idx="0"]')).toBeNull();
    // 而圆点仍然为它渲染了一个（圆点覆盖全量 user 消息，视觉上不缩水）
    const dots = screen.getAllByRole("button");
    expect(dots.length).toBe(10);

    act(() => {
      fireEvent.click(dots[0]);
    });

    // 关键：必须请求展开分页，而不是静默 return
    expect(onNeedOlder).toHaveBeenCalledTimes(1);
  });

  it("目标既没渲染、又没有 onNeedOlder：发出 warning 而不是静默失败", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const messages = conversation(10);
    const scrollRef = createRef<HTMLDivElement>();

    render(
      <div>
        {/* 刻意不渲染任何消息，模拟「找不到锚点」 */}
        <div ref={scrollRef} data-testid="scroll" />
        <QueryDots messages={messages} startIdx={10} scrollRef={scrollRef} />
      </div>
    );

    const dots = screen.getAllByRole("button");
    act(() => {
      fireEvent.click(dots[0]);
    });

    expect(warn).toHaveBeenCalled();
    expect(String(warn.mock.calls[0][0])).toContain("data-msg-idx=0");
  });

  it("少于 2 条 user 消息时不渲染圆点", () => {
    const { container } = render(
      <Harness messages={[msg(0, "user"), msg(1, "assistant")]} visibleCount={10} />
    );
    expect(container.querySelectorAll("button").length).toBe(0);
  });
});
