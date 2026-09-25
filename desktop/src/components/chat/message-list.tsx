import { useRef, useEffect, useCallback, useState } from "react";
import { ArrowDown } from "lucide-react";
import { MessageBubble } from "./message-bubble";
import { QueryDots } from "./query-dots";
import type { Message } from "@ethan/shared/chat/types";
import { isPersistedId } from "@ethan/shared/chat/history";
import type { Annotation } from "@/lib/api";

// 首屏显示的消息数量（约 5 轮对话 = 10 条消息）
const INITIAL_VISIBLE = 10;
// 每次向上加载更多的条数
const LOAD_MORE_COUNT = 10;

// 认为「视图在底部」的容差（px）。小于它就算在底部，跟随态成立。
const BOTTOM_EPSILON = 40;
// 程序触发滚动后，忽略 scroll 事件的时长（ms）。
//
// 不能只看「滚完是不是还在底部」：smooth 滚动会持续发 scroll 事件，中途必然经过
// near=false，用户手势的 scroll 也混在同一条事件流里，无法从事件本身区分。所以这里
// 用一个短暂的时间窗把「自己发起的滚动」整体吞掉，之后的事件才算用户操作。
const PROGRAMMATIC_IGNORE_MS = 150;

interface MessageListProps {
  messages: Message[];
  streaming: boolean;
  sessionId?: string | null;
  onQuote?: (msg: Message) => void;
  onCardAction?: (text: string) => void;
  onRead?: (msg: Message) => void;
  onShare?: (msg: Message) => void;
  onDelete?: (msg: Message) => void;
  onInject?: (content: string) => Promise<{ ok: boolean; error?: string }>;
  pendingInjected?: { id: string; content: string }[];
  onRemoveInjected?: (injId: string) => void;
  onCancelTool?: (toolCallId: string) => void;
  onActionConfirm?: (message: string) => void;
  onResume?: (msg: Message) => void;
  onRefresh?: () => void;
  /** 上滚触顶时加载更早一页；返回是否真的加载到了内容（没加载到就停止继续请求）。 */
  onLoadOlder?: () => Promise<void>;
  /** 服务端是否还有更早的消息（false = 已经到会话开头，不再显示加载指示器）。 */
  hasOlder?: boolean;
  /** 正在加载更早一页（显示加载指示器，并防止并发重复请求）。 */
  loadingOlder?: boolean;
  annotationsByMessage?: Record<number, Annotation[]>;
}

export function MessageList({ messages, streaming, sessionId, onQuote, onCardAction, onRead, onShare, onDelete, onInject, pendingInjected, onRemoveInjected, onCancelTool, onActionConfirm, onResume, onRefresh, onLoadOlder, hasOlder, loadingOlder, annotationsByMessage }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // 当前可见消息数（从末尾算）；消息列表变短（切换会话）时重置
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const prevLenRef = useRef(messages.length);
  // 记录上一次的 user 消息数量，用于识别"用户刚发送了消息"
  // （不能用 messages 末尾 role 判断：consumeStream 会立即 push 空 assistant 占位，
  // React 18 batching 后末尾是 assistant，导致 lastIsUser 误判）
  const prevUserCountRef = useRef(0);

  // ── 智能跟随滚动 ────────────────────────────────────────────────────
  //
  // 三个 ref 是这套逻辑的全部状态，刻意都用 ref 而不是 state：
  // 它们只在事件回调里读写、不参与渲染（按钮只依赖 isAtBottom），用 state 会多出
  // 一轮渲染，而「滚动 → 渲染 → 再滚动」这个循环正是抖动和竞态的来源。
  //
  // - atBottomRef：**实时**的「视图在底部吗」。scroll 事件是权威来源（用户在底部
  //   就是用户自己滚到底了，不需要额外的恢复动作），内容变高时再用 DOM 复算一次。
  // - stickRef：跟随态。这就是需求里的「默认自动跟随」——默认就是 true，流式内容
  //   增长时把视图拉到底；用户在底部以外的地方主动滚动才置 false，直到他重新回到底部。
  // - programmaticRef：程序滚动的忽略窗口截止时间戳，见 PROGRAMMATIC_IGNORE_MS。
  const atBottomRef = useRef(true);
  /** DOM 复算「视图是否在底部」，用于内容变高之后的判定。 */
  const recomputeAtBottom = (el: HTMLElement) =>
    el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_EPSILON;
  const programmaticRef = useRef(0);

  // isAtBottom 只用于渲染「回到底部」按钮的显隐
  const [isAtBottom, setIsAtBottom] = useState(true);
  const stickRef = useRef(true);
  /** 待执行的「跟到底部」帧（同一时刻只保留一个，见下面跟随副作用）。 */
  const followRafRef = useRef<number | null>(null);

  // 会话切换（消息减少）时重置 visibleCount
  useEffect(() => {
    if (messages.length < prevLenRef.current) {
      setVisibleCount(INITIAL_VISIBLE);
      // 切会话时同步重置 user 计数基线，避免误触发"新 user 消息"
      prevUserCountRef.current = messages.filter(m => m.role === "user").length;
      // 换了一个会话就是换了一套内容：下一次到达的消息属于用户没看过的对话，
      // 跟随态、底部判定、程序滚动窗口全部复位（新会话的 readMessages 通常会滚到底）。
      const el = scrollRef.current;
      stickRef.current = true;
      atBottomRef.current = true;
      programmaticRef.current = 0;
      if (el) {
        atBottomRef.current = recomputeAtBottom(el);
        setIsAtBottom(atBottomRef.current);
      } else {
        setIsAtBottom(true);
      }
    }
    prevLenRef.current = messages.length;
  }, [messages.length]);

  const hasMore = messages.length > visibleCount;
  const startIdx = hasMore ? messages.length - visibleCount : 0;
  const visibleMessages = messages.slice(startIdx);

  // 加载中标志用 ref 兜住，避免 IntersectionObserver 回调闭包拿到 stale state
  // 而在请求飞行期间反复触发（同一个哨兵会连续回调好几次）。
  const loadingRef = useRef(false);
  useEffect(() => { loadingRef.current = !!loadingOlder; }, [loadingOlder]);

  // 哨兵可见时要往外「再要一屏」吗？
  // - 本地窗口还有未展开的消息 → 纯前端展开（快，无网络）
  // - 本地窗口已到已加载数据的开头，且服务端还有更早的 → 拉下一页
  const needOlder =
    !hasMore && !!hasOlder && !!onLoadOlder && !loadingOlder && messages.length > 0;

  // 向上滚动触顶时加载更多（IntersectionObserver 监听哨兵元素）
  useEffect(() => {
    const container = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!container || !sentinel) return;
    if (!hasMore && !needOlder) return;

    const observer = new IntersectionObserver(
      async (entries) => {
        if (!entries[0]?.isIntersecting) return;
        if (loadingRef.current) return;

        // 记录加载前的滚动高度：DOM 提交后按差值把 scrollTop 推下去，视线不动。
        // 用户贴着底时则不需要补偿（他在最下面），照原样停在底部就是对的 ——
        // 那时下面这段 rAF 会因为「已被顶离底部」而把它重新贴回底部。
        const prevScrollHeight = container.scrollHeight;
        const pinned = stickRef.current;

        if (hasMore) {
          // 展开本地已加载的部分
          setVisibleCount((c) => Math.min(c + LOAD_MORE_COUNT, messages.length));
        } else if (needOlder) {
          loadingRef.current = true;
          try {
            await onLoadOlder!();
          } finally {
            // 请求返回后 messages 变长，本 effect 会重跑并重新挂 observer；
            // 这里只负责复位，避免异常路径把标志卡在 true。
            loadingRef.current = false;
          }
        }

        // 位置补偿：等 DOM 提交后按「长了多少」把 scrollTop 推下去，视线停在原处。
        if (compensateRafRef.current != null) cancelAnimationFrame(compensateRafRef.current);
        compensateRafRef.current = requestAnimationFrame(() => {
          compensateRafRef.current = null;
          // 用户已经贴底（或刚刚滚走了）：贴底的人该继续贴底，不在这里补偿 ——
          // 跟随逻辑会把他按在底部。
          if (pinned) return;
          const grew = container.scrollHeight - prevScrollHeight;
          if (grew <= 0) return;
          programmaticRef.current = Date.now() + PROGRAMMATIC_IGNORE_MS;
          container.scrollTop += grew;
        });
      },
      { root: container, threshold: 0, rootMargin: "100px 0px 0px 0px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, needOlder, messages.length, onLoadOlder]);

  // 圆点导航点到「尚未渲染的更早一屏」时展开分页。
  //
  // 必须**一次展开到目标可见**，不能按 LOAD_MORE_COUNT 一屏一屏加：目标可能比
  // startIdx 早好几屏（40 条消息点 idx=0 → 要连展开 3 次），而调用方的重试链只
  // 等有限几帧，展开一屏后就放弃了,用户看到的还是「点了没反应」。
  // 直接把 visibleCount 扩到「从 targetIdx 到末尾」即可让它进 DOM。
  const handleDotsNeedOlder = useCallback((targetIdx: number) => {
    setVisibleCount((c) => Math.max(c, Math.min(messages.length - targetIdx, messages.length)));
  }, [messages.length]);

  // 圆点导航滚过去的这次滚动是我方发起的，交给滚动监听标记成程序滚动：
  // 否则跳到页面中部（near=false）时会被当成「用户上滑离开底部」而解除跟随。
  //
  // 这个标记只覆盖 PROGRAMMATIC_IGNORE_MS 一个窗口，不依赖「有没有滚到底」来复位 ——
  // 早前用定时器 800ms 兜底复位，窗口太长：用户如果在圆点跳转后马上手动上滑，
  // 事件会被当成程序滚动吞掉，跟随解除不了；窗口只有 150ms 就不会吃掉真实手势。
  const markProgrammaticScroll = useCallback(() => {
    programmaticRef.current = Date.now() + PROGRAMMATIC_IGNORE_MS;
  }, []);

  // 滚到底部（被动跟随用）：只在真正滚得动的时候改 scrollTop。
  //
  // 已经贴底时再赋一次值看着无害，实则会打断用户**正在进行**的触摸拖拽：
  // 流式输出每来一个 chunk 就重设一次 scrollTop，浏览器会判定这次手势被接管并中止
  // 「拖到边界时的橡皮筋回弹」，手感变成「刚想往下拽就被弹回来」。
  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 1) return;
    programmaticRef.current = Date.now() + PROGRAMMATIC_IGNORE_MS;
    el.scrollTop = el.scrollHeight;
  }, []);

  // 上滚分页的位置补偿：记下展开前的 scrollHeight，提交后把差值加回 scrollTop，
  // 用户的视线就停在原来那条消息上（否则会被新插入的一屏整体往下推）。
  //
  // 用 rAF 排队而不是直接改：DOM 提交之后才能读到新的 scrollHeight。回调执行时
  // 再确认一次用户是不是已经离开了底部 —— 他可能在这一帧里滚走了，那就不要再动他。
  const compensateRafRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (compensateRafRef.current != null) cancelAnimationFrame(compensateRafRef.current);
    };
  }, []);

  // 监听滚动：这是「用户在哪儿」的唯一权威来源。
  //   - 即时刷新 atBottomRef / 按钮显隐；
  //   - 不在底部且不是自己滚的 → 解除跟随（需求核心：用户上滑后别再抢滚动位置）；
  //   - 重新滚回底部 → 恢复跟随。
  //
  // 时间是唯一判据，不区分是用户滚的还是内容变高顶出来的：内容在用户眼皮底下变高
  // 把视图顶离底部时，「别再动了」正是用户想要的；而程序自己发起的滚动落在
  // PROGRAMMATIC_IGNORE_MS 窗口内，不会误伤跟随态。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = recomputeAtBottom(el);
      atBottomRef.current = atBottom;
      setIsAtBottom(atBottom);
      if (Date.now() < programmaticRef.current) return;
      stickRef.current = atBottom;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // 挂载时先按真实滚动位置定一次初值：消息多的会话首屏读进来时可能并不在底部。
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // 消息变化 → 需要时跟随到底部。
  //
  // - 用户刚发出新消息（user 数量增加）：强制跟随到底部（无论当前滚动位置）——
  //   这是用户自己的动作，理应看到自己的消息。不能用「末尾 role 是不是 user」判断：
  //   consumeStream 会立刻 push 空 assistant 占位，React 18 batching 后末尾是
  //   assistant，会误判。
  // - 其余情况（助手流式追加、工具/卡片更新、消息增多、上滚分页展开）：跟随态为真
  //   才贴底；为假说明用户在别处看东西，一个像素都不动他。
  //
  // 滚动派发写进 rAF 回调里（而不是先 rAF 再滚），这样 jsdom 也能断言到真实行为。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const userCount = messages.filter(m => m.role === "user").length;
    const hasNewUserMessage = userCount > prevUserCountRef.current;
    prevUserCountRef.current = userCount;
    if (hasNewUserMessage) {
      stickRef.current = true;
      atBottomRef.current = true;
      setIsAtBottom(true);
    }
    // 先按当前 DOM 复算一次底部：内容变高会把视图顶离底部，此时 atBottomRef 还是
    // 上一次 scroll 事件的结论（内容没变高过，所以它并不过期，只是此刻不再成立）；
    // 用户主动上滑的结论则不同——它必须活到用户自己回到底部为止，不能被这里覆盖。
    const pin = hasNewUserMessage ? true : stickRef.current;
    if (pin && !hasNewUserMessage) {
      // 内容变高后用户其实还在「原位」：只要他原本贴着底，就继续算贴底。
      atBottomRef.current = recomputeAtBottom(el) || atBottomRef.current;
    }
    if (!pin) return;
    // 排下一帧再滚（DOM 提交后 scrollHeight 才是新的），并且**登记这次 rAF**：
    // 用户完全可能在这一帧之内就把视图滚走（流式输出时手速很快），那一帧回调如果
    // 照常执行，就会在用户已经离开底部之后把他拽回底部 —— 正是需求要修的现象。
    // 每次重新排期前取消上一次，保证同一时刻最多只有一个待执行的跟随滚动。
    if (followRafRef.current != null) cancelAnimationFrame(followRafRef.current);
    followRafRef.current = requestAnimationFrame(() => {
      followRafRef.current = null;
      // 回调真正执行的这一刻再确认一次跟随态：期间用户可能已经滚走了。
      if (!stickRef.current) return;
      scrollToBottom();
    });
  }, [messages, scrollToBottom]);

  // 卸载时清掉待执行的跟随滚动（它捕获了容器引用，留着没有意义）。
  useEffect(() => {
    return () => {
      if (followRafRef.current != null) cancelAnimationFrame(followRafRef.current);
    };
  }, []);

  const handleScrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    programmaticRef.current = Date.now() + PROGRAMMATIC_IGNORE_MS;
    el.scrollTop = el.scrollHeight;
    stickRef.current = true;
    atBottomRef.current = true;
    setIsAtBottom(true);
  }, []);

  return (
    <div className="relative flex-1 flex flex-col min-h-0">
    {/* pl-7 给左侧圆点导航让位——圆点栏是 absolute left-0 w-7 叠在容器上的，
        不留padding 会被消息内容压住。 */}
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 pl-7">
      <div className="max-w-3xl mx-auto w-full flex flex-col gap-6">
        {/* 顶部加载更多指示器：
            本地还有未展开的消息、或服务端还有更早一页时都要挂哨兵。
            hasOlder=false（已到会话开头）时刻意不渲染，避免"一直转圈但其实没有了"。 */}
        {(hasMore || needOlder || loadingOlder) && (
          <div ref={sentinelRef} className="flex items-center justify-center py-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50" />
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
              <span className="ml-1">加载更多对话…</span>
            </div>
          </div>
        )}

        {messages.length === 0 && (
          <div className="flex items-center justify-center text-muted-foreground min-h-[50vh]">
            <p>Start a conversation</p>
          </div>
        )}
        {visibleMessages.map((msg, i) => (
          // data-msg-idx 是圆点导航的锚点，必须与 QueryDots 的 startIdx 同一坐标系
          <div key={msg.id ?? `idx-${startIdx + i}`} data-msg-idx={startIdx + i}>
          <MessageBubble
            msg={msg}
            isStreaming={streaming}
            isLast={startIdx + i === messages.length - 1}
            sessionId={sessionId}
            onQuote={onQuote}
            onCardAction={onCardAction}
            onRead={onRead}
            onShare={onShare}
            onDelete={onDelete}
            onInject={onInject}
            pendingInjected={pendingInjected}
            onRemoveInjected={onRemoveInjected}
            onCancelTool={onCancelTool}
            onActionConfirm={onActionConfirm}
            onResume={onResume}
            onRefresh={onRefresh}
            annotations={isPersistedId(msg.id) ? annotationsByMessage?.[msg.id] : undefined}
          />
          </div>
        ))}
      </div>
    </div>

      {/* 左侧圆点导航：只把「已渲染」的消息交给它——messages 是完整的，但 DOM 里
          只挂了 visibleMessages 这一段。若把完整 messages 传进去，靠前的圆点会指向
          data-msg-idx 不在 DOM 中的节点，点击后静默无反应（控制台也不报错）。
          传 startIdx 让它按同一坐标系计算；onNeedOlder 让「点更早的消息」先展开分页。 */}
      <QueryDots
        messages={messages}
        startIdx={startIdx}
        scrollRef={scrollRef}
        onNeedOlder={hasMore ? handleDotsNeedOlder : undefined}
        onBeforeScroll={markProgrammaticScroll}
      />

      {/* 滚动到底部按钮：不在底部时显示；点击后回到跟随态。
          按钮本身不表示任何状态——跟随态的唯一权威是「用户在不在底部」，
          用图标颜色替它编码只会让人怀疑自己看到的到底算不算底部。 */}
      {messages.length > 0 && !isAtBottom && (
        <button
          type="button"
          onClick={handleScrollToBottom}
          className="absolute bottom-4 right-4 z-10 flex items-center justify-center h-9 w-9 rounded-full border bg-background/95 backdrop-blur shadow-md hover:bg-accent transition-colors text-muted-foreground"
          title="滚动到底部并跟随"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
