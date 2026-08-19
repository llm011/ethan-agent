import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom"
import {
  ChatMessage,
  createSession,
  type ModeEntry,
  type ModelEntry,
  fetchSession,
  deleteMessage,
  fetchSchedules,
  streamChat,
  streamResume,
  resumeFromMessage,
  stopGeneration,
  injectMessage,
  cancelToolCall,
  updateSessionMode,
  respondConsent,
  respondAskUser,
  respondWaitForUser,
  getAnnotationsBatch,
  renameSession,
  pinSession,
  unpinSession,
  type Annotation,
} from "@/lib/api";
import { fetchModels } from "@/lib/api-base";
import { fetchModes } from "@/lib/api-base";
import { fetchAgentSettings, type AgentSettings } from "@/lib/api-settings";
import { fetchOnboardingStatus, type OnboardingStatus } from "@/lib/api-misc";
import { useCachedResource } from "@/lib/use-cached-resource";
import { readSessionCache, writeSessionCache } from "@/lib/session-cache";
import { ReadingMode } from "@/components/chat/reading-mode";
import { ShareMode } from "@/components/chat/share-mode";
import type { Message, Usage, Quote, PendingFile } from "@ethan/shared/chat/types";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { OnboardingBanner } from "@/components/chat/onboarding-banner";
import { type ConsentRequest } from "@ethan/shared/components/consent-dialog";
import { ConsentGate } from "@ethan/shared/chat/consent-card";
import { CleanupConfirmGate, type CleanupConfirmRequest } from "@ethan/shared/chat/cleanup-confirm-card";
import { AskUserCard, type AskUserRequest } from "@ethan/shared/chat/ask-user-card";
import { WaitForUserCard, type WaitForUserRequest } from "@ethan/shared/chat/wait-for-user-card";
import { placeholderTitle, mapDetailMessages, isFirstQuerySignificant } from "@/components/chat/chat-helpers";
import { consumeStream, type ConsumeStreamActions } from "@/components/chat/use-chat-stream";
import { handleCommand } from "@/components/chat/chat-commands";
import { useInputStore } from "@/components/chat/use-input-store";

interface ChatViewProps {
  initialSessionId?: string;
}

export function ChatView({ initialSessionId }: ChatViewProps = {}) {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>(messages);
  messagesRef.current = messages;
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef(false);
  const _setStreaming = (v: boolean) => { streamingRef.current = v; setStreaming(v); };
  const [bgPolling, setBgPolling] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionSource, setSessionSource] = useState("web");
  const [sessionPinnedAt, setSessionPinnedAt] = useState(0);
  const pinTogglingRef = useRef(false); // pin 切换 in-flight 标记，防快速双击竞态
  const [sessionUsage, setSessionUsage] = useState<Usage>({ input: 0, output: 0, cache: 0 });
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null);
  const [cleanupConfirm, setCleanupConfirm] = useState<CleanupConfirmRequest | null>(null);
  const [askUserRequest, setAskUserRequest] = useState<AskUserRequest | null>(null);
  const [waitforUserRequest, setWaitForUserRequest] = useState<WaitForUserRequest | null>(null);
  const [mode, setMode] = useState<string>("");
  // 超级权限：开启后自动批准所有工具授权，任务中途不弹窗。持久化到 localStorage。
  const [autoConsent, setAutoConsent] = useState<boolean>(() => {
    try { return localStorage.getItem("ethan:auto-consent") === "1"; } catch { return false; }
  });
  const handleAutoConsentChange = useCallback((v: boolean) => {
    setAutoConsent(v);
    try { localStorage.setItem("ethan:auto-consent", v ? "1" : "0"); } catch {}
  }, []);
  const [loadingSession, setLoadingSession] = useState(false);
  const [modes, setModes] = useState<ModeEntry[]>([]);

  const [annotationsByMessage, setAnnotationsByMessage] = useState<Record<number, Annotation[]>>({});
  const [readingMessage, setReadingMessage] = useState<Message | null>(null);
  const [shareMessage, setShareMessage] = useState<Message | null>(null);
  const [shareDefaultKey, setShareDefaultKey] = useState<string | null>(null);

  const streamAbortRef = useRef<AbortController | null>(null);

  // 输入框状态机：按 session 缓存 draft 和排队消息
  const inputStore = useInputStore();
  const inputStoreRef = useRef(inputStore);
  inputStoreRef.current = inputStore;

  const fetchAnnotationsFor = async (msgs: Message[]) => {
    const ids = msgs.filter((m) => m.role === "assistant" && m.id != null).map((m) => m.id as number);
    if (ids.length === 0) return;
    try {
      const map = await getAnnotationsBatch(ids);
      setAnnotationsByMessage((prev) => ({ ...prev, ...map }));
    } catch {}
  };

  const handleConsentRespond = async (requestId: string, allowed: boolean, message?: string) => {
    setConsentRequest(null);
    try {
      await respondConsent(requestId, allowed, message);
    } catch {}
  };

  const handleCleanupRespond = async (requestId: string, action: "close" | "keep") => {
    try {
      const { respondBrowserCleanup } = await import("@/lib/api-base");
      await respondBrowserCleanup(requestId, action);
    } catch {}
    setCleanupConfirm(null);
  };

  const handleAskUserRespond = async (requestId: string, value: string) => {
    setAskUserRequest(null);
    try {
      await respondAskUser(requestId, value);
    } catch {}
  };

  const handleWaitForUserRespond = async (requestId: string, value: string) => {
    setWaitForUserRequest(null);
    try {
      await respondWaitForUser(requestId, value);
    } catch {}
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

  const handleShare = useCallback((msg: Message) => {
    const key = msg.id != null ? `id:${msg.id}` : `idx:${messagesRef.current.indexOf(msg)}`;
    setShareDefaultKey(key);
    setShareMessage(msg);
  }, []);

  const handleDelete = useCallback(async (msg: Message) => {
    if (!activeSession || msg.id == null) return;
    if (!confirm("确定删除这条消息？删除后从会话移除，后续对话不再带上其上下文。")) return;
    try {
      await deleteMessage(activeSession, msg.id);
      setMessages(prev => prev.filter(m => m.id !== msg.id));
    } catch (e) {
      alert(e instanceof Error ? e.message : "删除失败");
    }
  }, [activeSession]);

  // 运行中「补充信息」：调 POST /chat/{id}/inject，把内容塞入 ChatRun inbox。
  // agent loop 下一轮调模型前会 append 到 working 末尾（prompt 结尾）。
  // 无活跃 run 时后端返回 409，这里返回 {ok:false, error} 由 InjectBox 提示。
  const handleInject = useCallback(async (content: string): Promise<{ ok: boolean; error?: string }> => {
    if (!activeSession) return { ok: false, error: "无活跃会话" };
    try {
      await injectMessage(activeSession, content);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : "提交失败" };
    }
  }, [activeSession]);

  const handleCancelTool = useCallback(async (toolCallId: string) => {
    if (!activeSession) return;
    try {
      await cancelToolCall(activeSession, toolCallId);
    } catch {
      // 静默失败：取消是 best-effort 操作，不弹错误提示
    }
  }, [activeSession]);

  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleQuote = useCallback((m: Message) => {
    setQuote({ role: m.role, content: m.content });
    setTimeout(() => inputRef.current?.focus(), 30);
  }, []);

  const handleSendRef = useRef<(text: string) => void>(() => {});
  const handleCardAction = useCallback((text: string) => {
    handleSendRef.current(text);
  }, []);

  // 用户点击「操作完成，继续」按钮后，自动发送预设消息让 Agent 继续执行
  const handleActionConfirm = useCallback((message: string) => {
    handleSendRef.current(message);
  }, []);

  const handleResume = useCallback(async (msg: Message) => {
    if (!activeSession || msg.id == null) return;
    _setStreaming(true);
    streamAbortRef.current?.abort();
    const ac = new AbortController();
    streamAbortRef.current = ac;
    try {
      const stream = resumeFromMessage(activeSession, msg.id);
      await consumeStream(stream, messages, {
        setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling,
        setSessionTitle, setSessionUsage, setStopping, setStreaming: _setStreaming,
        activeSession,
      }, false, ac.signal);
    } catch {
      _setStreaming(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession, messages]);

  const justFinishedRef = useRef<string | null>(null);

  // Load session when route param changes
  useEffect(() => {
    if (!initialSessionId) {
      // 切换到新会话 — 保存当前输入并切换状态机
      inputStore.switchTo(null, inputRef.current?.value);
      setActiveSession(null);
      setSessionTitle("");
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
      setSessionSource("web");
      setSessionPinnedAt(0);
      setMode("");
      setLoadingSession(false);
      // 重置 transient 状态：否则旧会话残留的 streaming=true 会让 handleSend
      // 的 `if (streaming) return;` 直接拦截，导致新会话无法创建（刷新才恢复）
      setStreaming(false);
      setStopping(false);
      setBgPolling(null);
      setConsentRequest(null);
      setAskUserRequest(null);
      return;
    }

    if (initialSessionId === activeSession && streaming) return;

    if (justFinishedRef.current === initialSessionId) {
      justFinishedRef.current = null;
      return;
    }

    // 切换到目标会话 — 保存当前输入并恢复目标会话的输入状态
    inputStore.switchTo(initialSessionId, inputRef.current?.value);

    // 重置 transient 状态：防止旧会话的 streaming 残留阻塞新会话操作
    setStreaming(false);
    setStopping(false);
    setBgPolling(null);
    setConsentRequest(null);
    setAskUserRequest(null);

    // SWR：先尝试读本地缓存，命中则立即渲染（避免白屏等待网络）
    const cached = readSessionCache(initialSessionId);
    if (cached) {
      const cachedMsgs = mapDetailMessages(cached.detail);
      setActiveSession(initialSessionId);
      setSessionTitle(cached.detail.title || "");
      setSessionSource(cached.detail.source || "web");
      setSessionPinnedAt(cached.detail.pinned_at || 0);
      setMessages(cachedMsgs);
      setSelectedModel(cached.detail.model);
      setMode(cached.detail.mode || "");
      const historicUsage = cached.detail.messages
        .filter((m: any) => m.role === "assistant" && m.usage)
        .reduce((acc: any, m: any) => ({
          input: acc.input + (m.usage.input || 0),
          output: acc.output + (m.usage.output || 0),
          cache: acc.cache + (m.usage.cache || 0),
        }), { input: 0, output: 0, cache: 0 });
      setSessionUsage(historicUsage);
      setLoadingSession(false);
      window.dispatchEvent(new CustomEvent("session:loaded", { detail: { sessionId: initialSessionId } }));
      fetchAnnotationsFor(cachedMsgs);
    } else {
      setLoadingSession(true);
      setActiveSession(null);
      setMessages([]);
      setSessionTitle("");
      setSessionUsage({ input: 0, output: 0, cache: 0 });
    }

    let cancelled = false;

    fetchSession(initialSessionId)
      .then(async (detail) => {
        if (cancelled) return;
        // 写入本地缓存
        writeSessionCache(initialSessionId, detail);
        setLoadingSession(false);
        window.dispatchEvent(new CustomEvent("session:loaded", { detail: { sessionId: initialSessionId } }));
        setActiveSession(initialSessionId);
        setSessionTitle(detail.title || "");
        setSessionSource(detail.source || "web");
        setSessionPinnedAt(detail.pinned_at || 0);
        const loaded = mapDetailMessages(detail);
        setMessages(loaded);
        fetchAnnotationsFor(loaded);
        setSelectedModel(detail.model);
        setMode(detail.mode || "");
        const historicUsage = detail.messages
          .filter((m: any) => m.role === "assistant" && m.usage)
          .reduce((acc: any, m: any) => ({
            input: acc.input + (m.usage.input || 0),
            output: acc.output + (m.usage.output || 0),
            cache: acc.cache + (m.usage.cache || 0),
          }), { input: 0, output: 0, cache: 0 });
        setSessionUsage(historicUsage);

        if (detail.active_run) {
          setStreaming(true);
          const resumeAc = new AbortController();
          const stream = await streamResume(initialSessionId, resumeAc.signal).catch(() => null);
          if (cancelled) { resumeAc.abort(); return; }
          if (stream) {
            const base = loaded.length > 0 && loaded[loaded.length - 1].role === "assistant"
              ? loaded.slice(0, -1)
              : loaded;
            await consumeStream(stream, base, {
              setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling,
              setSessionTitle, setSessionUsage, setStopping, setStreaming,
              activeSession: initialSessionId,
            }, false, resumeAc.signal);
          } else {
            setStreaming(false);
            const fresh = await fetchSession(initialSessionId).catch(() => null);
            if (cancelled) return;
            if (fresh) {
              writeSessionCache(initialSessionId, fresh);
              const freshMsgs = mapDetailMessages(fresh);
              setMessages(freshMsgs);
              fetchAnnotationsFor(freshMsgs);
            }
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        setLoadingSession(false);
        setActiveSession(null);
        setSessionTitle("");
        setMessages([]);
      });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  // A 类准静态数据：用 useCachedResource 走 SWR
  const modelsResource = useCachedResource<ModelEntry[]>("models", fetchModels, { ttlMs: 60 * 60_000 });
  const modesResource = useCachedResource<ModeEntry[]>("modes", fetchModes, { ttlMs: 24 * 60 * 60_000 });
  const settingsResource = useCachedResource<AgentSettings>("agentSettings", fetchAgentSettings, { ttlMs: 60 * 60_000 });
  const onboardingResource = useCachedResource<OnboardingStatus>("onboarding", fetchOnboardingStatus, { ttlMs: 24 * 60 * 60_000 });

  useEffect(() => {
    const models = modelsResource.data;
    if (models) {
      setModels(models);
      const def = settingsResource.data?.default_model;
      setSelectedModel((prev) => prev || def || (models.length > 0 ? models[0].id : ""));
    }
  }, [modelsResource.data, settingsResource.data]);

  useEffect(() => {
    if (modesResource.data) setModes(modesResource.data);
  }, [modesResource.data]);

  useEffect(() => {
    if (onboardingResource.data?.first_time) setShowOnboarding(true);
  }, [onboardingResource.data]);

  useEffect(() => {
    if (settingsResource.data?.default_model && !activeSession) {
      setSelectedModel((prev) => prev || settingsResource.data!.default_model);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsResource.data, activeSession]);

  useEffect(() => {
    if (sessionTitle.startsWith("[定时]")) {
      fetchSchedules().then(setSchedules).catch(() => {});
    }
  }, [sessionTitle]);

  const prevSessionRef = useRef(initialSessionId);
  const queueDrainTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    // 仅 streaming 从 true→false 时 drain 队列；切会话（initialSessionId 变化）不触发
    const sessionChanged = prevSessionRef.current !== initialSessionId;
    prevSessionRef.current = initialSessionId;
    if (sessionChanged) {
      if (queueDrainTimerRef.current !== undefined) {
        clearTimeout(queueDrainTimerRef.current);
        queueDrainTimerRef.current = undefined;
      }
      return;
    }

    if (!streaming) {
      setTimeout(() => inputRef.current?.focus(), 50);
      // streaming 结束 → 后台刷新缓存（新消息已产生）
      if (initialSessionId) {
        fetchSession(initialSessionId)
          .then((detail) => writeSessionCache(initialSessionId, detail))
          .catch(() => {});
      }
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
          if (prevSessionRef.current !== targetSession) return;
          handleSendRef.current(first.text);
        }, 100);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId, streaming]);

  const handleSend = async (text: string) => {
    if (!text.trim() && pendingFiles.length === 0) return;
    if (streaming) return;

    const trimmed = text.trim();
    const isBtw = trimmed.toLowerCase().startsWith("/btw ");
    const isReview = trimmed === "/review" || trimmed.startsWith("/review ") || trimmed.startsWith("/review\t");
    if (trimmed.startsWith("/") && !isBtw && !isReview) {
      await handleCommand(trimmed, {
        setMessages, setActiveSession, setSessionTitle,
        setSessionUsage, setPendingFiles, setQuote, setStreaming,
        selectedModel, mode, activeSession,
      });
      return;
    }

    const btwQuestion = isBtw ? trimmed.slice(4).trim() : null;

    let sessionId = activeSession;
    if (!sessionId) {
      const s = await createSession(selectedModel, mode, "desktop");
      sessionId = s.id;
      setActiveSession(s.id);
      const pTitle = placeholderTitle(text);
      setSessionTitle(pTitle);
      window.dispatchEvent(new CustomEvent("session:title-updated", {
        detail: { sessionId: s.id, title: pTitle }
      }));
      // 首轮：如果 query 信息量足够，同时 fire-and-forget 把占位标题写入后端，
      // 防止 3s 会话列表轮询把本地标题覆盖回"新对话"（createSession 返回"新对话"与后端
      // chat.py init_title 之间存在竞态）。
      if (isFirstQuerySignificant(text) && pTitle && pTitle !== "新对话") {
        renameSession(s.id, pTitle).catch(() => { /* 失败静默忽略，后端稍后会补 */ });
      }
      justFinishedRef.current = s.id;
      window.history.replaceState(null, "", `/chat/${s.id}/`);
    }
    let content = isBtw ? (btwQuestion ?? text) : text;
    if (isReview) {
      const target = trimmed.replace(/^\/review\s*/, "").trim();
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

    const modelInfo = models.find((m) => m.id === selectedModel);
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
    setStreaming(true);
    streamAbortRef.current?.abort();
    const ac = new AbortController();
    streamAbortRef.current = ac;

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({
      role: m.role,
      content: m.content,
      images: m.images?.map((img) => ({
        data: img.dataUrl?.split(",")[1] ?? "",
        media_type: img.dataUrl?.split(";")[0].replace("data:", "") ?? "image/png",
      })),
    }));

    await consumeStream(
      streamChat(chatMessages, selectedModel, sessionId, { quote: sentQuote, mode, btw: isBtw, review: isReview, autoConsent }),
      newMessages,
      { setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling, setSessionTitle, setSessionUsage, setStopping, setStreaming, activeSession: sessionId },
      true,
      ac.signal,
    );
  };
  handleSendRef.current = handleSend;

  return (
    <div className="flex flex-col flex-1 min-h-0">
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
        onReloadChat={activeSession ? () => {
          const sid = activeSession;
          setLoadingSession(true);
          setMessages([]);
          fetchSession(sid).then((detail) => {
            writeSessionCache(sid, detail);
            setLoadingSession(false);
            setSessionTitle(detail.title || "");
            setSessionSource(detail.source || "web");
            setSessionPinnedAt(detail.pinned_at || 0);
            const loaded = mapDetailMessages(detail);
            setMessages(loaded);
            fetchAnnotationsFor(loaded);
            setSelectedModel(detail.model);
            setMode(detail.mode || "");
            const historicUsage = detail.messages
              .filter((m: any) => m.role === "assistant" && m.usage)
              .reduce((acc: any, m: any) => ({
                input: acc.input + (m.usage.input || 0),
                output: acc.output + (m.usage.output || 0),
                cache: acc.cache + (m.usage.cache || 0),
              }), { input: 0, output: 0, cache: 0 });
            setSessionUsage(historicUsage);
          }).catch(() => {
            setLoadingSession(false);
          });
        } : undefined}
      />

      {loadingSession && messages.length === 0 ? (
        <div className='flex-1 overflow-y-auto p-4'>
          <div className='max-w-3xl mx-auto space-y-6'>
            <div className='flex justify-start gap-2'>
              <div className='h-7 w-7 rounded-full bg-muted animate-pulse' />
              <div className='max-w-[80%] space-y-2'>
                <div className='h-4 w-64 rounded bg-muted animate-pulse' />
                <div className='h-4 w-48 rounded bg-muted animate-pulse' />
              </div>
            </div>
            <div className='flex justify-end'>
              <div className='h-20 w-72 rounded-2xl bg-muted animate-pulse' />
            </div>
            <div className='flex justify-start gap-2'>
              <div className='h-7 w-7 rounded-full bg-muted animate-pulse' />
              <div className='max-w-[80%] space-y-2'>
                <div className='h-4 w-56 rounded bg-muted animate-pulse' />
                <div className='h-4 w-40 rounded bg-muted animate-pulse' />
                <div className='h-4 w-52 rounded bg-muted animate-pulse' />
              </div>
            </div>
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
        annotationsByMessage={annotationsByMessage}
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
        annotations={readingMessage?.id != null ? (annotationsByMessage[readingMessage.id] ?? []) : []}
        onClose={() => setReadingMessage(null)}
        onChange={handleAnnotationsChange}
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
        <ConsentGate request={consentRequest} onRespond={handleConsentRespond} />
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
          onModelChange={setSelectedModel}
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
  );
}
