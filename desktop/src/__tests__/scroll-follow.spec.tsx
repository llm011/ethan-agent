import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { createElement } from "react";
import { MessageList } from "@/components/chat/message-list";
import type { Message } from "@ethan/shared/chat/types";

// MessageList 里每条消息都包了 MessageBubble（依赖 markdown/katex/tauri 等一大坨）。
// 这里替换成极简替身：本文件测的是「滚动跟随」，消息内容怎么渲染无关紧要。
vi.mock("@/components/chat/message-bubble", () => ({
  MessageBubble: ({ msg }: { msg: Message }) =>
    createElement("div", { className: "bubble" }, String(msg.content)),
}));

function msg(id: number, role: "user" | "assistant", content?: string): Message {
  return { id, role, content: content ?? `m${id}` } as Message;
}

function conversation(turns: number): Message[] {
  const out: Message[] = [];
  for (let i = 0; i < turns; i++) {
    out.push(msg(i * 2, "user"));
    out.push(msg(i * 2 + 1, "assistant"));
  }
  return out;
}

/**
 * 把容器的几何量设成「可滚动」的一屏并返回操作句柄。
 *
 * jsdom 里所有元素都是 0×0，scrollHeight 恒为 0，不设这些值的话「在不在底部」
 * 永远是「在」（0-0-0 < 40），测不出任何东西。
 *
 * stickHeight 决定「内容变高」这类行为：流式追加时调用 bump()。
 */
function makeScrollable(el: HTMLElement, opts: { clientHeight?: number; scrollHeight?: number } = {}) {
  let scrollHeight = opts.scrollHeight ?? 2000;
  const clientHeight = opts.clientHeight ?? 400;
  // jsdom 没实现布局，scrollTop 是普通属性（写进去就存住），这里显式定义成
  // 「会被夹在 [0, scrollHeight - clientHeight] 之间」的访问器，贴近浏览器行为。
  let scrollTop = scrollHeight - clientHeight;

  Object.defineProperty(el, "scrollHeight", {
    get: () => scrollHeight,
    configurable: true,
  });
  Object.defineProperty(el, "clientHeight", {
    get: () => clientHeight,
    configurable: true,
  });
  Object.defineProperty(el, "scrollTop", {
    get: () => scrollTop,
    set: (v: number) => {
      // 真实浏览器把 scrollTop 夹在 [0, scrollHeight - clientHeight]；
      // 写一个超过范围的值不会「直接生效」，所以这里也照样夹一次。
      scrollTop = Math.max(0, Math.min(v, Math.max(0, scrollHeight - clientHeight)));
    },
    configurable: true,
  });

  return {
    /** 内容变高（流式追加一屏多一点）——不会自己触发 scroll 事件，跟真实浏览器一致。 */
    bump(delta = 600) {
      scrollHeight += delta;
    },
    /**
     * 按「当前渲染了多少条消息」重算 scrollHeight。
     *
     * 上滚分页的本质就是往列表顶部插消息，内容必然变高；不模拟这一点，补偿就永远
     * 是个 0，测试也就测不出「位置有没有被保住」。perMessage 是每条消息占的高度。
     */
    setRenderedCount(count: number, perMessage = 120) {
      scrollHeight = Math.max(clientHeight, count * perMessage);
    },
    get scrollHeight() {
      return scrollHeight;
    },
    get clientHeight() {
      return clientHeight;
    },
    /** 模拟用户滚动：改位置 + 派发一次 scroll（浏览器的顺序就是「先动位置再发事件」）。 */
    userScrollTo(top: number) {
      scrollTop = Math.max(0, Math.min(top, Math.max(0, scrollHeight - clientHeight)));
      fireEvent.scroll(el);
    },
    get scrollTop() {
      return scrollTop;
    },
    get distanceFromBottom() {
      return scrollHeight - scrollTop - clientHeight;
    },
    get atBottom() {
      return this.distanceFromBottom < 40;
    },
  };
}

/** 渲染一个有 10 条消息的列表，并返回可滚动的消息容器 + 几何句柄。 */
function setup(messages = conversation(5)) {
  const { container } = render(<MessageList messages={messages} streaming={false} />);
  const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
  const geom = makeScrollable(scroller);
  return { container, scroller, geom, messages };
}

/** 容器里渲染出来的消息下标（用于断言渲染窗口确实收敛了）。 */
function renderedIdx(container: HTMLElement): number[] {
  return Array.from(container.querySelectorAll("[data-msg-idx]"))
    .map((el) => Number(el.getAttribute("data-msg-idx")))
    .sort((a, b) => a - b);
}

beforeEach(() => {
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
  cleanup();
  vi.restoreAllMocks();
});

// 这一组是 issue 的验收标准本身：流式输出默认跟随底部 / 用户上滑后不被强行拉起 /
// 重新回到边界恢复跟随。修复前本组「用户上滑」两条是失败的。
describe("流式输出时的智能跟随", () => {
  it("默认跟随：助手内容持续追加时始终贴底", async () => {
    const messages = conversation(3); // 6 条，全部渲染
    const { rerender } = render(<MessageList messages={messages} streaming />);
    const scroller = document.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);
    expect(geom.atBottom).toBe(true);

    // 模拟流式：每来一段新内容，messages 换一个新数组（consumeStream 的做法），
    // 同时容器 scrollHeight 变高。
    for (let i = 0; i < 5; i++) {
      act(() => {
        geom.bump();
        rerender(
          <MessageList
            messages={messages.map((m) => (m.id === 5 ? { ...m, content: `m5-${i}` } : m))}
            streaming
          />
        );
      });
      await waitFor(() => expect(geom.atBottom).toBe(true));
    }

    // 内容变高后仍应贴在底部（允许 40px 容差）
    expect(geom.atBottom).toBe(true);
  });

  it("用户上滑后不再被强行拉起（核心回归）", async () => {
    const messages = conversation(5);
    const { rerender } = render(<MessageList messages={messages} streaming />);
    const scroller = document.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);

    // 用户主动向上滚到中部（远离底部）
    act(() => {
      geom.userScrollTo(500);
    });
    expect(geom.atBottom).toBe(false);

    const topAfterUserScroll = geom.scrollTop;

    // 后续流式内容持续追加：视图必须一个像素都不动
    for (let i = 0; i < 5; i++) {
      act(() => {
        geom.bump();
        rerender(
          <MessageList
            messages={messages.map((m) =>
              m.role === "assistant" && m.id === 9 ? { ...m, content: `m9-${i}` } : m
            )}
            streaming
          />
        );
      });
      await Promise.resolve();
    }

    expect(geom.scrollTop).toBe(topAfterUserScroll);
    expect(geom.atBottom).toBe(false);
  });

  it("重新滚回底部后恢复跟随", async () => {
    const messages = conversation(5);
    const { rerender } = render(<MessageList messages={messages} streaming />);
    const scroller = document.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);

    act(() => {
      geom.userScrollTo(500); // 离开底部 → 解除跟随
    });
    act(() => {
      geom.userScrollTo(1600); // 用户自己滚回底部 → 恢复跟随
    });
    expect(geom.atBottom).toBe(true);

    // 恢复跟随后再来的流式内容应当继续跟随到底
    act(() => {
      geom.bump();
      rerender(
        <MessageList messages={messages.map((m) => (m.id === 9 ? { ...m, content: "m9-new" } : m))} streaming />
      );
    });
    await waitFor(() => expect(geom.atBottom).toBe(true));
  });

  it("用户刚发出的消息：无论之前滚到哪儿，都跟随到底", async () => {
    const messages = conversation(3); // 6 条
    const { rerender } = render(<MessageList messages={messages} streaming />);
    const scroller = document.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);

    act(() => {
      geom.userScrollTo(300); // 用户正在上面翻旧消息
    });
    expect(geom.atBottom).toBe(false);

    // 用户发了新消息（user 数量 +1）
    const next = [...messages, msg(6, "user", "新问题"), msg(7, "assistant", "")];
    act(() => {
      geom.bump();
      rerender(<MessageList messages={next} streaming />);
    });

    await waitFor(() => expect(geom.atBottom).toBe(true));
  });

  it("已经在底部时内容变高：跟随态不被打断", async () => {
    const messages = conversation(3);
    const { rerender } = render(<MessageList messages={messages} streaming />);
    const scroller = document.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);

    act(() => {
      geom.bump();
      rerender(
        <MessageList messages={messages.map((m) => (m.id === 5 ? { ...m, content: "更长了" } : m))} streaming />
      );
    });
    await waitFor(() => expect(geom.atBottom).toBe(true));

    // 再来一轮，仍应贴底
    act(() => {
      geom.bump();
      rerender(
        <MessageList messages={messages.map((m) => (m.id === 5 ? { ...m, content: "更长了2" } : m))} streaming />
      );
    });
    await waitFor(() => expect(geom.atBottom).toBe(true));
  });
});

// 上滚分页是「一次性往前插 10 条」：如果不管用户在哪儿都直接提交，内容会被整体
// 往下推一个屏幕高，而补偿要等下一帧才做得到 —— 中间那一帧用户看到的是明显跳动。
// 修复前 `pnpm test` 全绿但没有任何用例覆盖这条路径。
describe("上滚分页不打断阅读位置", () => {
  /** 触发一次「展开本地更早一屏」的 IntersectionObserver 回调。 */
  function setupPaging() {
    const messages = conversation(20); // 40 条，首屏只渲染末尾 10 条
    let observerCb: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    // 记下被挂上来的观察者：下面主动断开它，模拟「哨兵已经离开视野」。
    // 真实浏览器里加载完哨兵会被推到视野外，不会连续触发；这里几何是假的，
    // 不关掉的话每次 rerender 都会重新回调，等于噪声。
    let observers: { disconnect: () => void; alive: boolean }[] = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        alive = true;
        constructor(private cb: (entries: { isIntersecting: boolean }[]) => void) {
          observerCb = cb;
          observers.push(this);
        }
        observe() {}
        unobserve() {}
        disconnect() {
          this.alive = false;
        }
        takeRecords() {
          return [];
        }
      }
    );

    const { container } = render(<MessageList messages={messages} streaming={false} />);
    const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
    const geom = makeScrollable(scroller);
    // 几何跟着「当前渲染了多少条」走：每条 120px，这样分页插入更早的消息会真的把
    // 内容变高，补偿才有对象（真实浏览器里当然就是布局的结果）。
    geom.setRenderedCount(renderedIdx(container).length);
    const syncGeometry = () => geom.setRenderedCount(renderedIdx(container).length);

    return {
      container,
      scroller,
      geom,
      messages,
      syncGeometry: () => {
        geom.setRenderedCount(renderedIdx(container).length);
        return geom;
      },
      /** 让哨兵进入视野 → 展开 10 条更早的消息。 */
      triggerLoadMore() {
        act(() => {
          observerCb?.([{ isIntersecting: true }]);
        });
      },
      /** 模拟哨兵离开视野：把还活着的观察者全部断开。 */
      detachSentinel() {
        observers.forEach((o) => o.alive && o.disconnect());
        observers = [];
        observerCb = null;
      },
    };
  }

  it("用户停在别处时：内容长高后视线仍停在原来那条消息上", async () => {
    const { container, geom, triggerLoadMore, detachSentinel, syncGeometry } = setupPaging();

    // 首屏渲染末尾 10 条（idx 30..39）；几何按「每条 120px」同步好
    expect(renderedIdx(container)[0]).toBe(30);
    geom.setRenderedCount(10);

    // 用户向上滚到中部（首屏 10 条 → scrollHeight 1200，视口 400，可滚范围 0..800）
    act(() => {
      geom.userScrollTo(300);
    });
    const before = geom.scrollTop;
    const distanceBefore = geom.distanceFromBottom;
    expect(distanceBefore).toBeGreaterThan(40); // 明确不在底部

    // 触发上滚加载更多：展开一屏更早的消息（渲染窗口变长）
    act(() => {
      triggerLoadMore();
    });
    detachSentinel();

    // 内容变高是布局的结果，发生在 React 提交之后；这里显式把它同步进来。
    act(() => {
      syncGeometry();
    });

    // 补偿在下一帧执行（要等 DOM 提交后才能读到新的 scrollHeight）。
    await act(async () => {
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // 补偿生效：scrollTop 被推下去（内容在头顶长高了），但**距离底部不变** ——
    // 也就是用户视线还停在原来那条消息上，没有被整体推走。
    expect(geom.scrollTop).toBeGreaterThan(before);
    expect(geom.distanceFromBottom).toBeCloseTo(distanceBefore, 0);
    // 仍不在底部：用户没被拽走
    expect(geom.atBottom).toBe(false);
  });

  it("用户停在底部时展开更多：继续贴底，不被列表变长顶走", async () => {
    const { geom, triggerLoadMore, detachSentinel, syncGeometry } = setupPaging();

    act(() => {
      triggerLoadMore();
    });
    detachSentinel();
    act(() => {
      syncGeometry();
    });
    await act(async () => {
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // 贴底的人：列表变长后应当仍在底部（跟随逻辑负责把他按住），
    // 而不是因为内容变高被顶离底部、出现「明明在底部却被推走」
    expect(geom.atBottom).toBe(true);
  });
});
