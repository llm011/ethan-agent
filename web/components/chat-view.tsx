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
  deleteMessage,
  fetchSchedules,
  streamChat,
  streamResume,
  stopGeneration,
  injectMessage,
  updateSessionMode,
  fetchOnboardingStatus,
  fetchAgentSettings,
  respondConsent,
  getAnnotationsBatch,
  type Annotation,
} from "@/lib/api";
import { ReadingMode } from "@/components/chat/reading-mode";
import { ShareMode } from "@/components/chat/share-mode";
import type { Message, Usage, Quote, PendingFile } from "@ethan/shared/chat/types";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { OnboardingBanner } from "@/components/chat/onboarding-banner";
import { type ConsentRequest } from "@ethan/shared/components/consent-dialog";
import { ConsentGate } from "@ethan/shared/chat/consent-card";
import { placeholderTitle, mapDetailMessages } from "@/components/chat/chat-helpers";
import { consumeStream, type ConsumeStreamActions } from "@/components/chat/use-chat-stream";
import { handleCommand } from "@/components/chat/chat-commands";

interface ChatViewProps {
  initialSessionId?: string;
}

export function ChatView({ initialSessionId }: ChatViewProps = {}) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>(messages);
  messagesRef.current = messages;
  const [streaming, setStreaming] = useState(false);
  const [bgPolling, setBgPolling] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionSource, setSessionSource] = useState("web");
  const [sessionUsage, setSessionUsage] = useState<Usage>({ input: 0, output: 0, cache: 0 });
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null);
  const [mode, setMode] = useState<string>("");
  const [loadingSession, setLoadingSession] = useState(false);
  const [modes, setModes] = useState<ModeEntry[]>([]);

  const [annotationsByMessage, setAnnotationsByMessage] = useState<Record<number, Annotation[]>>({});
  const [readingMessage, setReadingMessage] = useState<Message | null>(null);
  const [shareMessage, setShareMessage] = useState<Message | null>(null);
  const [shareDefaultKey, setShareDefaultKey] = useState<string | null>(null);

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

  const handleQuote = useCallback((m: Message) => {
    setQuote({ role: m.role, content: m.content });
    setTimeout(() => inputRef.current?.focus(), 30);
  }, []);

  const handleSendRef = useRef<(text: string) => void>(() => {});
  const handleCardAction = useCallback((text: string) => {
    handleSendRef.current(text);
  }, []);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const justFinishedRef = useRef<string | null>(null);

  // 构建 consumeStream 所需的 actions 对象
  const getStreamActions = (): ConsumeStreamActions => ({
    setMessages, setConsentRequest, setBgPolling,
    setSessionTitle, setSessionUsage, setStopping, setStreaming,
    activeSession,
  });

  // Load session when route param changes
  useEffect(() => {
    if (!initialSessionId) {
      setActiveSession(null);
      setSessionTitle("");
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
      setSessionSource("web");
      setMode("");
      setLoadingSession(false);
      fetchAgentSettings().then((settings) => {
        if (settings.default_model) setSelectedModel(settings.default_model);
      }).catch(() => {});
      return;
    }

    if (initialSessionId === activeSession && streaming) return;

    if (justFinishedRef.current === initialSessionId) {
      justFinishedRef.current = null;
      return;
    }

    setLoadingSession(true);
    setActiveSession(null);
    setMessages([]);
    setSessionTitle("");
    setSessionUsage({ input: 0, output: 0, cache: 0 });

    let cancelled = false;

    fetchSession(initialSessionId)
      .then(async (detail) => {
        if (cancelled) return;
        setLoadingSession(false);
        setActiveSession(initialSessionId);
        setSessionTitle(detail.title || "");
        setSessionSource(detail.source || "web");
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
          const stream = await streamResume(initialSessionId).catch(() => null);
          if (cancelled) return;
          if (stream) {
            const base = loaded.length > 0 && loaded[loaded.length - 1].role === "assistant"
              ? loaded.slice(0, -1)
              : loaded;
            await consumeStream(stream, base, {
              setMessages, setConsentRequest, setBgPolling,
              setSessionTitle, setSessionUsage, setStopping, setStreaming,
              activeSession: initialSessionId,
            });
          } else {
            setStreaming(false);
            const fresh = await fetchSession(initialSessionId).catch(() => null);
            if (cancelled) return;
            if (fresh) {
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

  useEffect(() => {
    fetchModes().then(setModes).catch(() => {});
  }, []);

  useEffect(() => {
    if (sessionTitle.startsWith("[定时]")) {
      fetchSchedules().then(setSchedules).catch(() => {});
    }
  }, [sessionTitle]);

  useEffect(() => {
    if (!streaming) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [initialSessionId, streaming]);

  useEffect(() => {
    fetchOnboardingStatus().then((status) => {
      if (status.first_time) setShowOnboarding(true);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      const s = await createSession(selectedModel, mode);
      sessionId = s.id;
      setActiveSession(s.id);
      const pTitle = placeholderTitle(text);
      setSessionTitle(pTitle);
      window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId: s.id, title: pTitle } }));
      justFinishedRef.current = s.id;
      window.history.replaceState(null, "", `/chat/${s.id}/`);
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
      if (ghMatch) setSessionTitle(`PR #${ghMatch[2]} ${ghMatch[1]}`);
      else if (glMatch) setSessionTitle(`MR !${glMatch[2]} ${glMatch[1]}`);
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

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({
      role: m.role,
      content: m.content,
      images: m.images?.map((img) => ({
        data: img.dataUrl?.split(",")[1] ?? "",
        media_type: img.dataUrl?.split(";")[0].replace("data:", "") ?? "image/png",
      })),
    }));

    await consumeStream(
      streamChat(chatMessages, selectedModel, sessionId, { quote: sentQuote, mode, btw: isBtw, review: isReview }),
      newMessages,
      { setMessages, setConsentRequest, setBgPolling, setSessionTitle, setSessionUsage, setStopping, setStreaming, activeSession: sessionId },
      true,
    );
  };
  handleSendRef.current = handleSend;

  return (
    <div className="flex flex-col flex-1 h-full">
      <ChatHeader
        sessionId={activeSession}
        title={sessionTitle}
        source={sessionSource}
        usage={sessionUsage}
        schedules={schedules}
        onTitleChange={setSessionTitle}
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
        streaming={streaming}
        onQuote={handleQuote}
        onCardAction={handleCardAction}
        onRead={handleRead}
        onShare={handleShare}
        onDelete={handleDelete}
        onInject={handleInject}
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
        />
      </div>
    </div>
  );
}
