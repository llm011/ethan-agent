"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ChatMessage,
  createSession,
  fetchModels,
  fetchModes,
  type ModeEntry,
  type ModelEntry,
  fetchSession,
  fetchSessionPage,
  deleteMessage,
  fetchSchedules,
  streamChat,
  streamResume,
  resumeFromMessage,
  stopGeneration,
  cancelToolCall,
  injectMessage,
  deleteInjectedMessage,
  setAutoConsent as setAutoConsentApi,
  updateSessionMode,
  updateSessionModel,
  fetchOnboardingStatus,
  fetchAgentSettings,
  respondConsent,
  respondBrowserCleanup,
  respondAskUser,
  respondWaitForUser,
  getAnnotationsBatch,
  renameSession,
  pinSession,
  unpinSession,
  fetchBackgroundTasks,
  type BackgroundTask,
  type Annotation,
} from "@/lib/api";
import { mergeSessionPageIntoCache, readSessionDetail, updateSessionDetail } from "@/lib/session-db";
import { MESSAGE_PAGE_SIZE, isPersistedId, prependOlderMessages, replaceTailKeepOlder } from "@ethan/shared/chat/history";
import { ReadingMode } from "@/components/chat/reading-mode";
import { ShareMode } from "@/components/chat/share-mode";
import type { Message, Usage, Quote, PendingFile } from "@ethan/shared/chat/types";
import { BackgroundTaskBar } from "@ethan/shared/components/background-task-bar";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { OnboardingBanner } from "@/components/chat/onboarding-banner";
import { type ConsentRequest } from "@ethan/shared/components/consent-dialog";
import { ConsentGate } from "@ethan/shared/chat/consent-card";
import { CleanupConfirmGate, type CleanupConfirmRequest } from "@ethan/shared/chat/cleanup-confirm-card";
import { AskUserCard, type AskUserRequest } from "@ethan/shared/chat/ask-user-card";
import { WaitForUserCard, type WaitForUserRequest } from "@ethan/shared/chat/wait-for-user-card";
import { placeholderTitle, mapDetailMessages, historicUsageOf, isFirstQuerySignificant, pendingFileToImagePayload, revokePendingBlobUrls } from "@/components/chat/chat-helpers";
import { consumeStream } from "@/components/chat/use-chat-stream";
import { handleCommand } from "@/components/chat/chat-commands";
import { useInputStore } from "@/components/chat/use-input-store";
import { IDLE_SESSION_REFRESH_EVENT, useLiveSessions } from "@/components/chat/use-live-sessions";
import { usePreview } from "@/components/preview-panel/preview-context";
import { PreviewPanel, getStoredPanelSize, storePanelSize } from "@/components/preview-panel/preview-panel";
import { ResizeHandle } from "@/components/preview-panel/resize-handle";

interface ChatViewProps {
  initialSessionId?: string;
}

export function ChatView({ initialSessionId }: ChatViewProps = {}) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>(messages);
  messagesRef.current = messages;
  const [streaming, setStreaming] = useState(false);
  // ── 消息分页 ──
  // 长会话（最多 953 条 / 11MB）一次全量拉会卡好几秒，所以首屏只取最近一页，
  // 上滚时再按 before 往回想。hasOlder=false 表示已经翻到会话开头。
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  // 正在翻页的会话 id：请求返回时若会话已经切走，就丢弃结果，
  // 否则会出现"A 会话的旧消息被塞进 B 会话"的串台。
  const olderReqSessionRef = useRef<string | null>(null);
  // streaming 的同步镜像：state 批处理有延迟，handleSend 用 ref 读取最新值，
  // 避免刚切到新会话时旧 streaming=true 还没刷新就被 if(streaming) return 拦截
  const streamingRef = useRef(false);
  const _setStreaming = (v: boolean) => { streamingRef.current = v; setStreaming(v); };
  const streamAbortRef = useRef<AbortController | null>(null);

  // handleRefreshSession 的串行化链：指向「最近一次刷新的 promise」，见其定义处。
  const refreshChainRef = useRef<Promise<void> | null>(null);

  // 订阅「后台有会话变了」的信号（定时任务 / 别的窗口 / CLI / 渠道都可能改当前这条会话）。
  // 挂在这里而不是挂在某个子组件上：刷新要同时更新消息、标题和标注，这些都是
  // ChatView 自己的状态。事件消费见下面那个 useEffect。
  useLiveSessions();

  // 当前**正在显示**的会话 id（实时）。
  //
  // 两个来源，取「最新」的一个：
  //  - 路由（initialSessionId）：用户点了侧边栏/深链切换会话时，这是权威值；
  //  - 发送时显式指派（见 handleSend 里的 displayedSessionRef.current = sessionId）：
  //    新建会话时 sessionId 先于路由生效，若不显式指派，流启动的瞬间 ref 还停在旧值，
  //    会把这次发送自己的 chunk 也丢掉。
  //
  // 用它来判断「这条流还属不属于当前显示的会话」——中途切会话后，旧流的在途 chunk 必须
  // 丢弃，否则会把上一个会话的内容写进当前会话（串台 bug）。
  //
  // 不能用 activeSession state：它是「会话数据已加载完」才置位的，加载期间是 null/旧值；
  // 而串台恰恰发生在切换的瞬间（新会话还在加载、旧流还在吐 chunk）。
  const displayedSessionRef = useRef<string | null>(initialSessionId ?? null);
  // 与 displayedSessionRef 同步写入的**镜像**，只为下面的事件监听器能用最新值 —— 监听器
  // 只在挂载时注册一次，闭包里的 activeSession state 会永远停在首次渲染的那个会话上。
  // 这里刻意用「同一处赋值、两个落点」而不是「监听器随 activeSession 重挂」：
  // 和桌面端保持同一份实现，两端行为一致才好对照。新增 setActiveSession 的调用点时，
  // 必须同时补这一行 —— 漏了就会让「后台更新自动刷新」悄悄只对部分会话生效。
  const activeSessionRef = useRef<string | null>(initialSessionId ?? null);
  const setActiveSessionBoth = useCallback((id: string | null) => {
    activeSessionRef.current = id;
    setActiveSession(id);
  }, []);
  // 路由**变化**时同步（render 阶段直接赋值，保证任何时刻读到的都是本次渲染的值）。
  // 只在路由值真的变了的时候覆盖，避免把「发送时显式指派的新会话 id」冲掉
  // ——新建会话时 sessionId 先于路由生效，那一帧路由还是旧值/undefined。
  const lastRouteSessionRef = useRef<string | null>(initialSessionId ?? null);
  const routeSessionId = initialSessionId ?? null;
  if (lastRouteSessionRef.current !== routeSessionId) {
    lastRouteSessionRef.current = routeSessionId;
    displayedSessionRef.current = routeSessionId;
    activeSessionRef.current = routeSessionId;
  }

  /**
   * 生成「该会话是否仍是当前显示会话」的判定函数，供 consumeStream 丢弃过期写入。
   *
   * 注意：流的 sessionId 目前**总是非空**（handleSend 先 createSession 拿 id 再启动流，
   * 续跑 / 恢复也都带 id），所以下面的 null 分支只是防御 —— 「新会话还没有 id」那一帧
   * 靠 handleSend 里 `displayedSessionRef.current = sessionId` 的显式指派兜住，
   * 那句是隐性的硬依赖，别删。
   */
  const sessionActiveChecker = useCallback((sessionId: string | null) => () => {
    const cur = displayedSessionRef.current;
    if (sessionId) return cur === sessionId;
    return !cur;
  }, []);

  const [bgPolling, setBgPolling] = useState<string | null>(null);
  // 后台任务条：展示本进程内运行中/刚完成的后台任务（其会话不在侧边栏列表里）
  const [bgTasks, setBgTasks] = useState<BackgroundTask[]>([]);
  const [stopping, setStopping] = useState(false);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionSource, setSessionSource] = useState("web");
  const [sessionPinnedAt, setSessionPinnedAt] = useState(0);
  const pinTogglingRef = useRef(false); // pin 切换 in-flight 标记，防快速双击竞态
  const [sessionUsage, setSessionUsage] = useState<Usage>({ input: 0, output: 0, cache: 0 });
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null);
  // 授权卡片已失效（迟到响应：请求已被后端超时清理）。新请求到达或卡片清空时复位。
  const [consentExpired, setConsentExpired] = useState(false);
  useEffect(() => { setConsentExpired(false); }, [consentRequest]);

  // 后台任务条：运行中 5s 轮询，空闲时降到 30s 心跳（ethan 无 WS 推送，轮询兜底）。
  // 不能「无运行中任务就彻底停表」——那样新发起的后台任务不会自动浮现。
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    let stopped = false;

    const schedule = (ms: number) => {
      if (stopped) return;
      if (timer) clearInterval(timer);
      timer = setInterval(async () => {
        try {
          const list = await fetchBackgroundTasks();
          if (stopped) return;
          setBgTasks(list);
          schedule(list.some(t => t.status === "running") ? 5000 : 30000);
        } catch {
          schedule(30000); // 出错退避
        }
      }, ms);
    };

    fetchBackgroundTasks()
      .then(list => { if (!stopped) { setBgTasks(list); schedule(list.some(t => t.status === "running") ? 5000 : 30000); } })
      .catch(() => schedule(30000));

    return () => { stopped = true; if (timer) clearInterval(timer); };
  }, []);
  const [cleanupConfirm, setCleanupConfirm] = useState<CleanupConfirmRequest | null>(null);
  const [askUserRequest, setAskUserRequest] = useState<AskUserRequest | null>(null);
  const [waitforUserRequest, setWaitForUserRequest] = useState<WaitForUserRequest | null>(null);
  const [mode, setMode] = useState<string>("");
  // 超级权限：开启后自动批准所有工具授权，任务中途不弹窗。持久化到 localStorage。
  const [autoConsent, setAutoConsent] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("ethan:auto-consent") === "1";
  });
  const handleAutoConsentChange = useCallback((v: boolean) => {
    setAutoConsent(v);
    try { localStorage.setItem("ethan:auto-consent", v ? "1" : "0"); } catch {}
    // 运行中切换：改的是**正在跑的那个 run** 的 ConsentProvider。没有活跃 run 时
    // 后端返回 applied=false，此时不改任何东西 —— 下一次发消息的请求体会带上
    // auto_consent，行为依然正确。失败静默：这只是让开关「提前生效」的优化，
    // 开关状态本身已经存好了，不值得因此打断用户。
    if (activeSession) setAutoConsentApi(activeSession, v).catch(() => {});
  }, [activeSession]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [modes, setModes] = useState<ModeEntry[]>([]);

  const [annotationsByMessage, setAnnotationsByMessage] = useState<Record<number, Annotation[]>>({});
  const [readingMessage, setReadingMessage] = useState<Message | null>(null);
  const [shareMessage, setShareMessage] = useState<Message | null>(null);
  const [shareDefaultKey, setShareDefaultKey] = useState<string | null>(null);

  // 输入框状态机：按 session 缓存 draft 和排队消息
  const inputStore = useInputStore();
  // 输入框附件（贴图等）也由 inputStore 管理：切走会话时随快照保存，切回时恢复
  const { files: pendingFiles, setFiles: setPendingFiles } = inputStore;
  const inputStoreRef = useRef(inputStore);
  inputStoreRef.current = inputStore;

  const preview = usePreview();

  const fetchAnnotationsFor = async (msgs: Message[]) => {
    const ids = msgs.filter((m) => m.role === "assistant" && m.id != null).map((m) => m.id as number);
    if (ids.length === 0) return;
    try {
      const map = await getAnnotationsBatch(ids);
      setAnnotationsByMessage((prev) => ({ ...prev, ...map }));
    } catch {}
  };

  const handleConsentRespond = async (requestId: string, allowed: boolean, message?: string) => {
    try {
      const res = await respondConsent(requestId, allowed, message);
      if (res.ok) {
        setConsentRequest(null);
      } else {
        // 迟到的响应：请求已被后端超时清理。直接关卡片会让用户误以为「允许」
        // 生效，而命令实际早已按拒绝处理——标记失效交由用户确认关闭。
        setConsentExpired(true);
      }
    } catch (err) {
      // 回传失败保留卡片让用户重试，否则 agent 会一直等到超时
      console.error("consent 回传失败:", err);
    }
  };

  const handleCleanupRespond = async (requestId: string, action: "close" | "keep") => {
    try {
      await respondBrowserCleanup(requestId, action);
    } catch (err) {
      console.error("cleanup 回传失败:", err);
    }
    setCleanupConfirm(null);
  };

  const handleAskUserRespond = async (requestId: string, value: string) => {
    try {
      await respondAskUser(requestId, value);
      setAskUserRequest(null);
    } catch (err) {
      // 回传失败保留卡片让用户重试，否则 agent 会一直等到超时
      console.error("ask_user 回传失败:", err);
    }
  };

  const handleWaitForUserRespond = async (requestId: string, value: string) => {
    try {
      await respondWaitForUser(requestId, value);
      setWaitForUserRequest(null);
    } catch (err) {
      // 回传失败保留卡片让用户重试，否则 agent 会一直等到超时
      console.error("wait_for_user 回传失败:", err);
    }
  };

  const handleRead = useCallback((msg: Message) => {
    if (msg.id == null) return;
    setReadingMessage(msg);
  }, []);

  const handleAnnotationsChange = (next: Annotation[]) => {
    if (readingMessage?.id == null) return;
    const mid = readingMessage.id;
    setAnnotationsByMessage((prev) => ({ ...prev, [mid]: next }));
  };

  // 阅读模式编辑正文回写：更新内存 state + IndexedDB 离线缓存里的同一条消息
  const handleEditContent = useCallback((mid: number, content: string) => {
    setMessages(prev => prev.map(m => (m.id === mid ? { ...m, content } : m)));
    setReadingMessage(prev => (prev && prev.id === mid ? { ...prev, content } : prev));
    if (activeSession) {
      updateSessionDetail(activeSession, (detail) => ({
        ...detail,
        messages: detail.messages.map(m => (m.id === mid ? { ...m, content } : m)),
      })).catch(() => {});
    }
  }, [activeSession]);

  const handleShare = useCallback((msg: Message) => {
    const key = msg.id != null ? `id:${msg.id}` : `idx:${messagesRef.current.indexOf(msg)}`;
    setShareDefaultKey(key);
    setShareMessage(msg);
  }, []);

  const handleDelete = useCallback(async (msg: Message) => {
    // 删除是写操作，必须有落库后的数字 id（流式中的占位消息还不存在于后端）
    if (!activeSession || !isPersistedId(msg.id)) return;
    if (!confirm("确定删除这条消息？删除后从会话移除，后续对话不再带上其上下文。")) return;
    try {
      await deleteMessage(activeSession, msg.id);
      setMessages(prev => prev.filter(m => m.id !== msg.id));
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除失败");
    }
  }, [activeSession]);

  // 运行中「补充信息」待处理列表：SSE injected_added/injected/injected_removed 事件驱动，
  // 刷新后从 session detail 的 pending_injected（DB 持久化镜像）恢复。
  const [pendingInjected, setPendingInjected] = useState<{ id: string; content: string }[]>([]);

  // 运行中「补充信息」：调 POST /chat/{id}/inject，把内容塞入 ChatRun inbox。
  // agent loop 下一轮调模型前会 append 到 working 末尾（prompt 结尾）。
  // 无活跃 run 时后端返回 409，这里返回 {ok:false, error} 由 InjectBox 提示。
  const handleInject = useCallback(async (content: string): Promise<{ ok: boolean; error?: string }> => {
    if (!activeSession) return { ok: false, error: "无活跃会话" };
    try {
      const res = await injectMessage(activeSession, content);
      // 乐观追加：SSE injected_added 事件按 id 去重，不会重复
      if (res.id) {
        setPendingInjected(prev => (prev.some(p => p.id === res.id) ? prev : [...prev, { id: res.id!, content }]));
      }
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : "提交失败" };
    }
  }, [activeSession]);

  // 待处理区点 × 删除一条补充信息（处理前才可删）。
  // 等 DELETE 成功才本地移除：删除失败时后端不会 emit injected_removed，
  // 乐观移除会导致 UI 不显示、run 队列/DB 镜像里仍在，模型下一轮照样读到。
  const handleRemoveInjected = useCallback(async (injId: string) => {
    if (!activeSession) return;
    try {
      await deleteInjectedMessage(activeSession, injId);
      setPendingInjected(prev => prev.filter(p => p.id !== injId));
    } catch (e) {
      alert(e instanceof Error && e.message ? e.message : "删除失败，请稍后重试");
    }
  }, [activeSession]);

  const handleQuote = useCallback((m: Message) => {
    setQuote({ role: m.role, content: m.content, message_id: isPersistedId(m.id) ? m.id : undefined });
    setTimeout(() => inputRef.current?.focus(), 30);
  }, []);

  const handleSendRef = useRef<(text: string) => void>(() => {});
  const handleCardAction = useCallback((text: string) => {
    handleSendRef.current(text);
  }, []);

  // 取消正在运行的工具调用（best-effort，静默失败）
  const handleCancelTool = useCallback(async (toolCallId: string) => {
    if (!activeSession) return;
    try {
      await cancelToolCall(activeSession, toolCallId);
    } catch {
      // 静默失败：取消是 best-effort 操作
    }
  }, [activeSession]);

  // 用户点击「操作完成，继续」按钮后，自动发送预设消息让 Agent 继续执行
  const handleActionConfirm = useCallback((message: string) => {
    handleSendRef.current(message);
  }, []);

  // 后台会话（定时任务等）执行中无 SSE 可连时，供「任务执行中」占位条拉取最新消息。
  // 不清空旧消息/不闪 loading：静默替换；正在流式输出时跳过，避免覆盖实时消息。
  // 上滚加载更早一页。
  // 以「当前列表里最旧的已落库消息 id」当 before 游标往后翻；拿到的一页按 id 去重
  // 前插，并用后端返回的 has_more 决定还能不能继续翻。
  const handleLoadOlder = useCallback(async () => {
    const sid = activeSession;
    if (!sid || loadingOlder) return;

    // 找最旧的「已落库」消息 id：临时 id / 本地乐观消息不能当游标（后端不认识）。
    const oldest = messagesRef.current.find(
      (m) => typeof m.id === "number" && Number.isFinite(m.id),
    );
    if (typeof oldest?.id !== "number") {
      setHasOlder(false);
      return;
    }

    olderReqSessionRef.current = sid;
    setLoadingOlder(true);
    try {
      const detail = await fetchSessionPage(sid, { limit: MESSAGE_PAGE_SIZE, before: oldest.id });
      // 会话已切走：丢弃这一页，避免串台
      if (olderReqSessionRef.current !== sid || !detail) return;
      const older = mapDetailMessages(detail);
      if (older.length > 0) {
        setMessages((prev) => prependOlderMessages(prev, older));
        fetchAnnotationsFor(older);
      }
      setHasOlder(detail.has_more ?? older.length >= MESSAGE_PAGE_SIZE);
    } catch {
      // 拉取失败：保留 hasOlder 原值，用户再上滚还能重试
    } finally {
      if (olderReqSessionRef.current === sid) {
        olderReqSessionRef.current = null;
        setLoadingOlder(false);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession, loadingOlder]);

  const handleRefreshSession = useCallback(async () => {
    const sid = activeSession;
    if (!sid || streaming || bgPolling) return;
    // 同一时刻只允许一次在途刷新：串行化用「上一次的 promise」而不是一个 boolean ——
    // 订阅者（占位条的 5s 轮询 / 后台变化的 3s 轮询）随时可能在上一发还没回来时再触发，
    // 用 boolean 的话第二发会被直接丢掉，而第二发往往才是真正需要的那次（新内容到了）。
    const prev = refreshChainRef.current;
    let release!: () => void;
    refreshChainRef.current = new Promise<void>((r) => (release = r));
    try {
      if (prev) await prev;
      // 只拉最近一页：这里是「后台会话执行中」的静默刷新，全量拉长会话要好几秒。
      // 用 replaceTailKeepOlder 保留用户已上滚翻出来的更早历史，不能整表替换。
      const detail = await fetchSessionPage(sid, { limit: MESSAGE_PAGE_SIZE }).catch(() => null);
      if (!detail) return;
      setSessionTitle(detail.title || "");
      const loaded = mapDetailMessages(detail);
      setMessages((prev) => replaceTailKeepOlder(prev, loaded));
      fetchAnnotationsFor(loaded);
      setSessionUsage(historicUsageOf(detail));
    } finally {
      release();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession, streaming, bgPolling]);

  // 后台（定时任务、别的窗口、CLI、渠道）往当前会话追加内容后，把界面拉上来。
  //
  // 信号来自 useLiveSessions（消费 /poll 的 updated_at 与 active_sessions 变化），
  // 这里只负责判断「变的是不是我正开着的这条」——事件里带的是会话 id 列表，
  // 不是内容，所以刷新仍然走 handleRefreshSession 那条「拉一页尾部、保留更早历史」的路径。
  //
  // 三个刻意的小决定：
  //
  // 1. sessionIds 为空数组表示「列表本身的形状变了（有会话新增/消失），但没有任何一条
  //    的时间戳前进」。新增一条会话不会改动当前这条的尾部，所以这种情况不刷新 ——
  //    否则每开一个新会话，所有打开的窗口都要白拉一次。
  // 2. 用 activeSessionRef 取当前会话，而不是闭包里的 activeSession state：这个监听器
  //    只在挂载时注册一次，闭包里的 activeSession 会永远停在首次渲染的那个会话上，
  //    切了会话就失效。刻意**不**为 activeSession 再补一个镜像 ref：那会变成「同一份
  //    状态两处赋值」，正是这次一起修掉的 streamingRef 脱节 bug 的形态；宁可让
  //    处理函数跟着 activeSession 重挂。
  // 3. 事件里没有这条会话、但 active_sessions 里出现过它，也要刷：后台轮可能在两次轮询
  //    之间跑完（一轮很短），列表切片里看不到它的 updated_at 变化，但 active 的翻转
  //    照样会带上它的 id。
  useEffect(() => {
    const handler = (e: Event) => {
      const ids = (e as CustomEvent).detail?.sessionIds as string[] | undefined;
      const sid = activeSessionRef.current;
      if (!sid || !ids || ids.length === 0) return;
      if (!ids.includes(sid)) return;
      void handleRefreshSession();
    };
    window.addEventListener(IDLE_SESSION_REFRESH_EVENT, handler);
    return () => window.removeEventListener(IDLE_SESSION_REFRESH_EVENT, handler);
  }, [handleRefreshSession]);

  const handleResume = useCallback(async (msg: Message) => {
    // 续跑要指定「从哪条消息之后继续」，必须是后端认得的真实 id
    if (!activeSession || !isPersistedId(msg.id)) return;
    _setStreaming(true);
    setPendingInjected([]); // 新 run：待处理队列重新开始
    streamAbortRef.current?.abort();
    const ac = new AbortController();
    streamAbortRef.current = ac;
    try {
      const stream = resumeFromMessage(activeSession, msg.id, selectedModel);
      await consumeStream(stream, messages, {
        setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling,
        setSessionTitle, setSessionUsage, setStopping, setStreaming: _setStreaming, setPendingInjected,
        activeSession,
        isSessionActive: sessionActiveChecker(activeSession),
      });
    } catch {
      _setStreaming(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession, messages, selectedModel]);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const justFinishedRef = useRef<string | null>(null);

  // Load session when route param changes
  useEffect(() => {
    // 守卫：handleSend 刚创建了新会话并启动了流式响应，replaceState 触发了
    // initialSessionId 变化。此时绝不能 abort 正在进行的流。
    // 标记只允许消费一次，无论是否命中都无条件清掉（对齐 desktop）：
    // 否则「加载 A 时发消息 → 切 B → 切回 A」时残留标记会让 effect 跳过加载，
    // activeSession 停留在 B，后续发送会静默发到 B。
    const skipLoad = justFinishedRef.current === initialSessionId;
    justFinishedRef.current = null;
    if (skipLoad) return;

    streamAbortRef.current?.abort();
    streamAbortRef.current = null;

    // 切会话时先把分页状态归零：否则上一个会话的 hasOlder 会残留，
    // 新会话（可能只有 3 条）会误以为还能往上翻。
    // 在途的翻页请求靠 olderReqSessionRef 失配丢弃，不会串到新会话。
    olderReqSessionRef.current = null;
    setHasOlder(false);
    setLoadingOlder(false);

    if (!initialSessionId) {
      // 切换到新会话 — 保存当前输入并切换状态机
      inputStore.switchTo(null, inputRef.current?.value);
      setActiveSessionBoth(null);
      setSessionTitle("");
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
      setPendingInjected([]);
      setSessionSource("web");
      setSessionPinnedAt(0);
      setMode("");
      setLoadingSession(false);
      // 重置 transient 状态：否则旧会话残留的 streaming=true 会让 handleSend
      // 的 `if (streaming) return;` 直接拦截，导致新会话无法创建（刷新才恢复）
      _setStreaming(false);
      setStopping(false);
      setBgPolling(null);
      setConsentRequest(null);
      setCleanupConfirm(null);
      setAskUserRequest(null);
      fetchAgentSettings().then((settings) => {
        if (settings.default_model) setSelectedModel(settings.default_model);
      }).catch(() => {});
      return;
    }

    if (initialSessionId === activeSession && streaming) return;

    // 切换到目标会话 — 保存当前输入并恢复目标会话的输入状态
    inputStore.switchTo(initialSessionId, inputRef.current?.value);

    // 重置 transient 状态：防止旧会话的 streaming 残留阻塞新会话操作
    _setStreaming(false);
    setStopping(false);
    setBgPolling(null);
    setConsentRequest(null);
    setCleanupConfirm(null);
    setAskUserRequest(null);

    // SWR：先读 IndexedDB 缓存立即渲染，网络请求在后台刷新。
    // 命中缓存时不要置 loading——否则侧边栏转圈、消息区白屏，体感反而是「卡」。
    let cancelled = false;
    let cachedHit = false;

    readSessionDetail(initialSessionId).then((cached) => {
      if (cancelled || !cached || cachedHit) return;
      cachedHit = true;
      // 若 handleSend 已基于该会话启动流式响应，别用缓存覆盖实时消息
      if (justFinishedRef.current === initialSessionId) return;
      if (streamingRef.current) return;
      const cachedMsgs = mapDetailMessages(cached);
      setLoadingSession(false);
      setActiveSessionBoth(initialSessionId);
      setSessionTitle(cached.title || "");
      setSessionSource(cached.source || "web");
      setSessionPinnedAt(cached.pinned_at || 0);
      setPendingInjected(cached.pending_injected || []);
      setMessages(cachedMsgs);
      setSelectedModel(cached.model);
      setMode(cached.mode || "");
      setSessionUsage(historicUsageOf(cached));
      window.dispatchEvent(new CustomEvent("session:loaded", { detail: { sessionId: initialSessionId } }));
      fetchAnnotationsFor(cachedMsgs);
    }).catch(() => {});

    fetchSessionPage(initialSessionId, { limit: MESSAGE_PAGE_SIZE })
      .then(async (detail) => {
        if (cancelled) return;
        // 竞态保护：如果 handleSend 已经基于 initialSessionId 启动了流式响应，
        // 就不要再用 DB 里的旧消息覆盖正在写入的实时消息；也不要重设 activeSession/title 等。
        if (justFinishedRef.current === initialSessionId) {
          justFinishedRef.current = null;
          return;
        }
        setLoadingSession(false);
        window.dispatchEvent(new CustomEvent("session:loaded", { detail: { sessionId: initialSessionId } }));
        setActiveSessionBoth(initialSessionId);
        setSessionTitle(detail.title || "");
        setSessionSource(detail.source || "web");
        setSessionPinnedAt(detail.pinned_at || 0);
        // 刷新后恢复未消费的「补充信息」（DB 持久化镜像）；SSE 回放事件按 id 去重不会重复
        setPendingInjected(detail.pending_injected || []);
        const loaded = mapDetailMessages(detail);
        setMessages(loaded);
        fetchAnnotationsFor(loaded);
        setSelectedModel(detail.model);
        setMode(detail.mode || "");
        setSessionUsage(historicUsageOf(detail));
        // 首屏只拉了一页：记下后端说的「还有更早的」，上滚时据此决定要不要再请求。
        // has_more 缺失时（老后端 / 缓存）按「拉满一页就还有」保守推断。
        setHasOlder(detail.has_more ?? loaded.length >= MESSAGE_PAGE_SIZE);
        // 回写离线缓存：只**合并**进已有全量缓存，不覆盖。
        // 这一页只有最近 30 条，直接 writeSessionDetail 会把整会话缓存降级成残页，
        // 离线打开长会话就只能看到 30 条、更早历史永久不可达。
        // 缓存尚未建立时（没有全量缓存过）保持没有——宁可离线无缓存，也不要残缺缓存。
        mergeSessionPageIntoCache(initialSessionId, detail).catch(() => {});

        if (detail.active_run) {
          _setStreaming(true);
          const ac = new AbortController();
          streamAbortRef.current = ac;
          const stream = await streamResume(initialSessionId, ac.signal).catch(() => null);
          if (cancelled) return;
          if (stream) {
            const base = loaded.length > 0 && loaded[loaded.length - 1].role === "assistant"
              ? loaded.slice(0, -1)
              : loaded;
            await consumeStream(stream, base, {
              setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling,
              setSessionTitle, setSessionUsage, setStopping, setStreaming: _setStreaming, setPendingInjected,
              activeSession: initialSessionId,
              isSessionActive: sessionActiveChecker(initialSessionId),
            }, false, ac.signal);
          } else {
            _setStreaming(false);
            // 只取一页：不带 limit 会拉回整个会话历史（含每条 tool_steps 的大字段），
            // 长会话下这是「点进去要等很久」的主要来源之一。
            const fresh = await fetchSessionPage(initialSessionId, { limit: MESSAGE_PAGE_SIZE }).catch(() => null);
            if (cancelled) return;
            if (fresh) {
              const freshMsgs = mapDetailMessages(fresh);
              // 只替换尾部、保住已翻出来的更早历史：这里拿到的只是一页，
              // 整表替换会把用户上滚加载过的消息全部丢掉（且 hasOlder 变 false 后
              // 再也滚不回来）。与其它刷新路径保持一致。
              setMessages(prev => replaceTailKeepOlder(prev, freshMsgs));
              // 这一页的 has_more 说的是「它的最旧一条之上还有没有」，与本地已加载
              // 到哪无关：用户可能已上滚翻过好几页（replaceTailKeepOlder 刚把它们保住），
              // 此时用 has_more=false 覆盖会把 hasOlder 压成 false，用户滚到已加载的
              // 最旧一条后就再也触发不了继续上滚。所以这条刷新路径只在成功回填到
              // 「后端确实还有更早」时才把它置 true，绝不用它把 true 压成 false。
              if (fresh.has_more) setHasOlder(true);
              fetchAnnotationsFor(freshMsgs);
            }
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        setLoadingSession(false);
        window.dispatchEvent(new CustomEvent("session:loaded", { detail: { sessionId: initialSessionId } }));
        setActiveSessionBoth(null);
        setSessionTitle("");
        setMessages([]);
      });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  useEffect(() => {
    Promise.all([fetchModels(), fetchAgentSettings()]).then(([m, settings]) => {
      setModels(m);
      setSelectedModel((prev) => prev || settings.default_model || (m.length > 0 ? m[0].id : ""));
    }).catch(() => {
      fetchModels().then((m) => {
        setModels(m);
        if (m.length > 0) setSelectedModel((prev) => prev || m[0].id);
      }).catch(() => {});
    });
  }, []);

  // 从其他页面（如 Agenda「拆解该安排」）带过来的待发送 prompt：
  // sessionStorage 优先，URL ?q= 兜底。仅新会话视图消费；延迟到 timer 里真正发送时才清除，
  // 这样 StrictMode 双挂载（或挂载后立即切走）时 cleanup 可整体撤销，不会丢 prompt。
  useEffect(() => {
    if (initialSessionId) return;
    let prompt = "";
    try {
      prompt = sessionStorage.getItem("ethan:pending-prompt") || "";
    } catch {}
    let fromUrl = false;
    if (!prompt) {
      const q = new URLSearchParams(window.location.search).get("q");
      if (q) {
        prompt = q;
        fromUrl = true;
      }
    }
    if (!prompt) return;
    const timer = setTimeout(() => {
      try { sessionStorage.removeItem("ethan:pending-prompt"); } catch {}
      // 清掉 URL 里的 ?q=。用 router 导航而不是 window.history.replaceState：
      // 后者只改地址栏、不更新 router，router 的 search 会停在 ?q=...，与真实 URL 失步。
      // replace:true 不产生额外历史项，行为与原 replaceState 等价。
      if (fromUrl) router.replace(window.location.pathname, { scroll: false });
      handleSendRef.current(prompt);
    }, 50);
    return () => clearTimeout(timer);
  }, [initialSessionId]);

  useEffect(() => {
    fetchModes().then(setModes).catch(() => {});
  }, []);

  useEffect(() => {
    if (sessionTitle.startsWith("[定时]")) {
      fetchSchedules().then(setSchedules).catch(() => {});
    }
  }, [sessionTitle]);

  const prevSessionRef = useRef(initialSessionId);
  const queueDrainTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // 按 sessionId 维护各会话后台 drain 的 AbortController，避免多会话切换时互相误杀
  const bgDrainAbortsRef = useRef<Map<string, AbortController>>(new Map());

  // 后台 drain：轮询旧会话直到 active_run=false，然后逐条发送排队消息
  const startBgDrain = useCallback((sessionId: string) => {
    // 同一会话重复启动时先终止旧任务；不同会话的任务互不影响
    bgDrainAbortsRef.current.get(sessionId)?.abort();
    const ac = new AbortController();
    bgDrainAbortsRef.current.set(sessionId, ac);

    (async () => {
      const POLL_INTERVAL = 2000;
      const MAX_POLLS = 300;

      for (let i = 0; i < MAX_POLLS; i++) {
        if (ac.signal.aborted) return;
        await new Promise((r) => setTimeout(r, POLL_INTERVAL));
        if (ac.signal.aborted) return;

        // 如果用户切回了这个会话，停止后台 drain，交给前台 effect 处理
        if (prevSessionRef.current === sessionId) {
          return;
        }

        try {
          const detail = await fetchSession(sessionId);
          if (detail.active_run) continue;
        } catch {
          return;
        }

        // active_run=false，开始发送排队消息
        const store = inputStoreRef.current;
        const q = store.getQueueForSession(sessionId);
        if (q.length === 0) return;

        const first = q[0];
        // 不提前出队：等流式拿到第一个 chunk（后端已接受请求）才移除，
        // 避免请求失败 / 被中止时排队消息被静默丢弃

        const chatMessages: ChatMessage[] = [{ role: "user", content: first.text }];
        if (first.images && first.images.length > 0) {
          chatMessages[0].images = await Promise.all(
            first.images.filter((f) => f.isImage).map(pendingFileToImagePayload)
          );
        }

        let accepted = false;
        try {
          const stream = streamChat(chatMessages, undefined, sessionId, { signal: ac.signal });
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          for await (const _ of stream) {
            // 拿到第一个 chunk 才出队（后端已接受请求）；首个 chunk 前失败/中止的消息留在队列
            if (!accepted) {
              accepted = true;
              store.removeFromQueueForSession(sessionId, first.id);
            }
            if (ac.signal.aborted) return;
          }
        } catch {
          // 请求失败或被中止：尚未出队的消息留在队列里，等下次 drain 或用户手动重发
          return;
        }
        if (!accepted) return;

        // 发送完一条后，检查是否还有更多排队消息 — 继续循环等下一轮 active_run=false
      }
    })().finally(() => {
      // 任务结束（完成/中止/出错）后清理自己的注册，防止 Map 泄漏
      if (bgDrainAbortsRef.current.get(sessionId) === ac) {
        bgDrainAbortsRef.current.delete(sessionId);
      }
    });
  }, []);

  // 组件卸载（离开 chat 页面）时终止所有后台 drain，
  // 防止脱离生命周期的孤儿任务在重新进入后与前台重复消费同一个流
  useEffect(() => {
    const aborts = bgDrainAbortsRef.current;
    return () => {
      aborts.forEach((ac) => ac.abort());
      aborts.clear();
    };
  }, []);

  useEffect(() => {
    // 仅 streaming 从 true→false 时 drain 队列；切会话（initialSessionId 变化）不触发
    const sessionChanged = prevSessionRef.current !== initialSessionId;
    const oldSession = prevSessionRef.current;
    prevSessionRef.current = initialSessionId;
    if (sessionChanged) {
      // 切换会话时取消尚未执行的排队消息发送（前台 timer），防止它发到新会话
      if (queueDrainTimerRef.current !== undefined) {
        clearTimeout(queueDrainTimerRef.current);
        queueDrainTimerRef.current = undefined;
      }
      // 如果旧会话有排队消息，启动后台 drain
      if (oldSession) {
        const store = inputStoreRef.current;
        const q = store.getQueueForSession(oldSession);
        if (q.length > 0) {
          startBgDrain(oldSession);
        }
      }
      // 切回的目标会话如果还有后台 drain 在跑（可能正在 stream），立即终止并交还前台：
      // 会话加载检测到 active_run 后会 resume 流式展示，结束后由前台继续 drain 剩余队列
      if (initialSessionId) {
        bgDrainAbortsRef.current.get(initialSessionId)?.abort();
        bgDrainAbortsRef.current.delete(initialSessionId);
      }
      return;
    }

    if (!streaming) {
      setTimeout(() => inputRef.current?.focus(), 50);
      // streaming 结束后，如果有排队消息，自动发送第一条（附带其图片）
      const store = inputStoreRef.current;
      if (store.queue.length > 0) {
        const first = store.queue[0];
        store.removeFromQueue(first.id);
        // 恢复该排队消息携带的图片
        if (first.images && first.images.length > 0) {
          setPendingFiles(first.images);
        }
        const targetSession = initialSessionId;
        queueDrainTimerRef.current = setTimeout(() => {
          queueDrainTimerRef.current = undefined;
          // 发送前校验会话未切走，防止竞态导致消息发到错误会话
          if (prevSessionRef.current !== targetSession) return;
          handleSendRef.current(first.text);
        }, 100);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId, streaming]);

  useEffect(() => {
    fetchOnboardingStatus().then((status) => {
      if (status.first_time) setShowOnboarding(true);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 选模型 → 立刻更新本地 state，并把当前会话的 model 写回后端。
  // 这里跟「点选重名候选」复用的 onModelChange 都走同一条路径；
  // 不在 activeSession 上时不做 PATCH（新会话的 model 会随 createSession 时一起落库）。
  //
  // 竞态保护：用户在会话内快速连点多个候选/下拉选项时，若每个选择都发一个并发
  // PATCH，HTTP 请求到达后端不保证有序，最终落库的可能是较早的选择而非最后一次。
  // 这里用一个 ref 做「最新待落库 + 是否 in-flight」的串行队列——同时最多一个在途请求，
  // 请求期间又选的新值记到 pending，等当前请求完成后再串行发一次，保证后发的永远排最后、
  // 后端最终落库的一定是最后一次点击。内存里 selectedModel 是同步 set，永远是最新值。
  const modelSyncRef = useRef<{ pending: string | null; inFlight: boolean }>({
    pending: null,
    inFlight: false,
  });

  const flushModelSync = useCallback(async () => {
    if (!activeSession) return;
    const s = modelSyncRef.current;
    if (s.inFlight || s.pending === null) return;
    const model = s.pending;
    s.inFlight = true;
    try {
      await updateSessionModel(activeSession, model);
    } catch {
      // PATCH 失败静默：下次进入该会话会重新加载旧值并再次提示重名；
      // 这种场景下重名提示反而是合理的——保留现状即可。
    } finally {
      s.inFlight = false;
      // 等待期间又选了新值 → 再串行发一次，保证最终是最后一次选择。
      if (s.pending !== null) flushModelSync();
    }
  }, [activeSession]);

  const handleModelChange = useCallback((model: string) => {
    setSelectedModel(model);
    modelSyncRef.current.pending = model;
    flushModelSync();
  }, [flushModelSync]);

  const handleSend = async (text: string) => {
    if (!text.trim() && pendingFiles.length === 0) return;
    // 用 ref 读取最新值，避免 state 批处理延迟导致新会话被旧 streaming=true 拦截
    if (streamingRef.current) return;

    const trimmed = text.trim();
    const isBtw = trimmed.toLowerCase().startsWith("/btw ");
    const isReview = trimmed === "/review" || trimmed.startsWith("/review ") || trimmed.startsWith("/review\t");
    if (trimmed.startsWith("/") && !isBtw && !isReview) {
      await handleCommand(trimmed, {
        setMessages, setActiveSession: setActiveSessionBoth, setSessionTitle,
        setSessionUsage, setPendingFiles, setQuote, setStreaming: _setStreaming,
        selectedModel, mode, activeSession,
        navigate: (to, opts) => (opts?.replace ? router.replace(to) : router.push(to)),
      });
      return;
    }

    const btwQuestion = isBtw ? trimmed.slice(4).trim() : null;

    let sessionId = activeSession;
    if (!sessionId) {
      // 竞态修复：用户点击侧边栏会话（/chat/:id）后，fetchSession 还在飞行，
      // activeSession 仍是 null，但 initialSessionId 已经稳定存在。此时发送消息
      // 绝不应该 createSession 新建一条，而要直接复用 initialSessionId。
      if (initialSessionId) {
        sessionId = initialSessionId;
        // 标记 "这个会话别让稍后到达的 fetchSession.then 用旧数据覆盖流式消息"
        justFinishedRef.current = initialSessionId;
        setActiveSessionBoth(initialSessionId);
        // 复用分支会命中上面 fetchSession.then 的 justFinishedRef 短路（直接 return，
        // 跳过 setLoadingSession(false)），这里主动清掉 loading，避免界面卡在骨架屏
        setLoadingSession(false);
      } else {
        try {
          const s = await createSession(selectedModel, mode);
          sessionId = s.id;
          setActiveSessionBoth(s.id);
          const pTitle = placeholderTitle(text);
          setSessionTitle(pTitle);
          window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId: s.id, title: pTitle } }));
          // 首轮：如果 query 信息量足够，同时 fire-and-forget 把占位标题写入后端，
          // 作为与后端 chat.py init_title 逻辑的双重保障：
          //   (1) 后端会在 chat 请求到达时按同一阈值写 init_title；
          //   (2) 前端再写一次 PATCH 保证 3s 会话轮询不会把本地标题覆盖回"新对话"
          //       （竞态：createSession 先返回"新对话"，若后端 init_title 还没执行完，
          //         侧边栏的第一次 list/fetchSessions 读到的仍是"新对话"）。
          if (isFirstQuerySignificant(text) && pTitle && pTitle !== "新对话") {
            renameSession(s.id, pTitle).catch(() => { /* PATCH 失败静默忽略，后端稍后会补 */ });
          }
          justFinishedRef.current = s.id;
          // 用 router 导航（replace 语义）而不是 window.history.replaceState：
          // App Router 的 history 由 router 内部维护，直接改 URL 会让 router 的
          // location 与真实 URL 失步 —— 之后点「+」navigate 到它以为自己已在的位置，
          // 就成了空操作（桌面端踩过同一个坑，见 chat-commands.ts 的 /new）。
          router.replace(`/chat/${s.id}/`, { scroll: false });
        } catch (e) {
          // createSession 失败（网络抖动 / 后端 500 / model 参数非法）时给用户明确反馈，
          // 否则 Promise rejection 被静默吞掉，用户只看到"点了没反应"
          setMessages(prev => [...prev, {
            role: "assistant",
            content: `⚠️ 创建会话失败：${e instanceof Error ? e.message : "未知错误"}\n\n请重试，或检查后端服务是否正常。`,
            created_at: Date.now() / 1000,
          }]);
          return;
        }
      }
    }
    let content = isBtw ? (btwQuestion ?? text) : text;
    if (isReview) {
      const target = trimmed.slice(7).trim();
      if (!target) {
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: "用法：`/review <PR/MR 链接或描述>`，例如：`/review https://github.com/foo/bar/pull/123`",
          created_at: Date.now() / 1000,
        }]);
        return;
      }
      content = `帮我 code review：${target}`;
      const ghMatch = target.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/);
      const glMatch = target.match(/gitlab\.com\/([^/]+\/[^/]+)\/-\/merge_requests\/(\d+)/);
      if (ghMatch) {
        const reviewTitle = `PR #${ghMatch[2]} ${ghMatch[1]}`;
        setSessionTitle(reviewTitle);
        if (sessionId) window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId, title: reviewTitle } }));
      } else if (glMatch) {
        const reviewTitle = `MR !${glMatch[2]} ${glMatch[1]}`;
        setSessionTitle(reviewTitle);
        if (sessionId) window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId, title: reviewTitle } }));
      }
    }
    const imageFiles = pendingFiles.filter((f) => f.isImage);
    const nonImageFiles = pendingFiles.filter((f) => !f.isImage);

    if (nonImageFiles.length > 0) {
      const fileContext = nonImageFiles.map((f) => `[Uploaded file: ${f.name} at ${f.path}]`).join("\n");
      content = `${fileContext}\n\n${content}`;
    }

    // selectedModel 可能是纯 id 或 provider/id 复合格式（重名模型时前端存复合格式）
    const modelInfo = models.find(
      (m) => m.id === selectedModel || (m.provider ? `${m.provider}/${m.id}` : m.id) === selectedModel
    );
    const visionSupported = modelInfo?.vision !== false;
    let imagesToSend = imageFiles;
    if (imageFiles.length > 0 && !visionSupported) {
      const ok = window.confirm(
        `当前模型「${selectedModel}」不支持图片输入，图片将被忽略，只发送文字。\n\n是否继续？`
      );
      if (!ok) return;
      imagesToSend = [];
    }

    const userMsg: Message = {
      role: "user",
      content,
      files: nonImageFiles.map((f) => f.name),
      images: imagesToSend.length > 0 ? imagesToSend : undefined,
      created_at: Date.now() / 1000,
      quote: quote ?? undefined,
    };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    const sentQuote = quote;
    setPendingFiles([]);
    setQuote(null);
    _setStreaming(true);
    streamAbortRef.current?.abort();
    const ac = new AbortController();
    streamAbortRef.current = ac;

    const chatMessages: ChatMessage[] = await Promise.all(newMessages.map(async (m) => ({
      role: m.role,
      content: m.content,
      images: m.images ? await Promise.all(m.images.map(pendingFileToImagePayload)) : undefined,
    })));

    // 显式把「当前显示的会话」指派为本次发送的会话：新建会话时 sessionId 先于路由生效，
    // 不指派的话流启动瞬间 ref 仍停在旧值，这个流自己的 chunk 会被守卫误丢。
    displayedSessionRef.current = sessionId;
    await consumeStream(
      streamChat(chatMessages, selectedModel, sessionId, { quote: sentQuote, mode, btw: isBtw, review: isReview, autoConsent, signal: ac.signal }),
      newMessages,
      { setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling, setSessionTitle, setSessionUsage, setStopping, setStreaming: _setStreaming, setPendingInjected, activeSession: sessionId, isSessionActive: sessionActiveChecker(sessionId) },
      true,
      ac.signal,
    );
  };
  handleSendRef.current = handleSend;

  const previewOpen = !!preview.file;
  const panelWidthRef = useRef(getStoredPanelSize());
  const [panelWidth, setPanelWidth] = useState(() => getStoredPanelSize());
  const containerRef = useRef<HTMLDivElement>(null);

  const handleResize = useCallback((deltaX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const totalWidth = container.offsetWidth;
    const newPct = Math.max(20, Math.min(60, panelWidthRef.current + (-deltaX / totalWidth) * 100));
    setPanelWidth(newPct);
  }, []);

  const handleResizeEnd = useCallback(() => {
    setPanelWidth((current) => {
      panelWidthRef.current = current;
      storePanelSize(current);
      return current;
    });
  }, []);

  return (
    <div ref={containerRef} className="flex flex-1 min-h-0">
      <div className="flex flex-col flex-1 min-w-0 min-h-0">
      <ChatHeader
        sessionId={activeSession}
        title={sessionTitle}
        source={sessionSource}
        usage={sessionUsage}
        schedules={schedules}
        pinnedAt={sessionPinnedAt}
        onTitleChange={setSessionTitle}
        onTogglePin={async () => {
          if (!activeSession || pinTogglingRef.current) return;
          pinTogglingRef.current = true;
          try {
            if (sessionPinnedAt > 0) {
              await unpinSession(activeSession);
              setSessionPinnedAt(0);
            } else {
              await pinSession(activeSession);
              setSessionPinnedAt(Date.now() / 1000);
            }
            window.dispatchEvent(new CustomEvent("session:pin-updated"));
          } catch (e) {
            console.error("toggle pin failed:", e);
          } finally {
            pinTogglingRef.current = false;
          }
        }}
      />

      {/* 后台任务条：这些任务的会话不在侧边栏/全部会话里，从主会话这里进详情 */}
      <BackgroundTaskBar
        tasks={bgTasks.filter(t => t.status === "running" || t.status === "done" || t.status === "error").slice(0, 6)}
        onOpen={(id) => router.push(`/chat/${id}`)}
        onOpenCenter={() => router.push("/background-tasks")}
      />

      {loadingSession ? (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="max-w-3xl mx-auto space-y-6 animate-pulse">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="flex gap-3">
                <div className="h-8 w-8 rounded-full bg-muted shrink-0" />
                <div className="flex-1 space-y-2 pt-1">
                  <div className="h-4 bg-muted rounded w-3/4" />
                  <div className="h-4 bg-muted rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
      <MessageList
        messages={messages}
        streaming={streaming || !!bgPolling}
        sessionId={activeSession}
        onQuote={handleQuote}
        onCardAction={handleCardAction}
        onRead={handleRead}
        onShare={handleShare}
        onDelete={handleDelete}
        onInject={handleInject}
        onCancelTool={handleCancelTool}
        onActionConfirm={handleActionConfirm}
        onResume={handleResume}
        onRefresh={handleRefreshSession}
        onLoadOlder={handleLoadOlder}
        hasOlder={hasOlder}
        loadingOlder={loadingOlder}
        annotationsByMessage={annotationsByMessage}
        pendingInjected={pendingInjected}
        onRemoveInjected={handleRemoveInjected}
      />
      )}

      {bgPolling && (
        <div className="max-w-3xl mx-auto w-full px-4 py-2">
          <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
            <span>{bgPolling}</span>
          </div>
        </div>
      )}

      <ReadingMode
        key={readingMessage?.id ?? "closed"}
        open={readingMessage != null}
        message={readingMessage}
        annotations={readingMessage && isPersistedId(readingMessage.id) ? (annotationsByMessage[readingMessage.id] ?? []) : []}
        sessionId={activeSession ?? undefined}
        onClose={() => setReadingMessage(null)}
        onChange={handleAnnotationsChange}
        onEditContent={readingMessage && isPersistedId(readingMessage.id) ? (content) => handleEditContent(readingMessage.id as number, content) : undefined}
      />

      <ShareMode
        key={shareDefaultKey ?? "share-closed"}
        open={shareMessage != null}
        messages={messages}
        defaultSelectedKey={shareDefaultKey}
        onClose={() => setShareMessage(null)}
      />

      <div>
        {showOnboarding && (
          <div className="max-w-3xl mx-auto px-4 pt-3">
            <OnboardingBanner onDismiss={() => setShowOnboarding(false)} />
          </div>
        )}
        <ConsentGate
          request={consentRequest}
          expired={consentExpired}
          onRespond={handleConsentRespond}
          onDismiss={() => setConsentRequest(null)}
        />
        <CleanupConfirmGate request={cleanupConfirm} onRespond={handleCleanupRespond} />
        {askUserRequest && (
          <div className="max-w-3xl mx-auto px-4 pb-2">
            <AskUserCard request={askUserRequest} onRespond={handleAskUserRespond} />
          </div>
        )}
        {waitforUserRequest && (
          <div className="max-w-3xl mx-auto px-4 pb-2">
            <WaitForUserCard request={waitforUserRequest} onRespond={handleWaitForUserRespond} />
          </div>
        )}
        <ChatInput
          streaming={streaming}
          models={models}
          selectedModel={selectedModel}
          pendingFiles={pendingFiles}
          quote={quote}
          inputRef={inputRef}
          onModelChange={handleModelChange}
          onSend={handleSend}
          onStop={() => {
            if (activeSession && !stopping) {
              setStopping(true);
              setConsentRequest(null);
              stopGeneration(activeSession).catch(() => { setStopping(false); });
            }
          }}
          stopping={stopping}
          onFilesChange={setPendingFiles}
          onQuoteCancel={() => setQuote(null)}
          modes={modes}
          mode={mode}
          onModeChange={(m) => {
            setMode(m);
            if (activeSession) {
              updateSessionMode(activeSession, m).catch(() => {});
            }
          }}
          autoConsent={autoConsent}
          onAutoConsentChange={handleAutoConsentChange}
          draft={inputStore.draft}
          onDraftChange={inputStore.setDraft}
          queue={inputStore.queue}
          onQueueSend={(text, images) => inputStore.addToQueue(text, images)}
          onQueueRemove={inputStore.removeFromQueue}
          onQueueEdit={inputStore.editInQueue}
          onQueueReorder={inputStore.reorderQueue}
        />
      </div>
    </div>

      {previewOpen && (
        <>
          <ResizeHandle onResize={handleResize} onResizeEnd={handleResizeEnd} />
          <div className="shrink-0 h-full overflow-hidden" style={{ width: `${panelWidth}%` }}>
            <PreviewPanel />
          </div>
        </>
      )}
    </div>
  );
}
