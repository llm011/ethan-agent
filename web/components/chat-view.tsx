"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ChatMessage,
  createSession,
  fetchModels,
  fetchSession,
  fetchSchedules,
  streamChat,
  fetchOnboardingStatus,
  fetchAgentSettings,
  respondConsent,
} from "@/lib/api";
import type { ToolStep } from "@/components/tool-timeline";
import type { Message, Usage, Quote } from "@/components/chat/types";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { OnboardingBanner } from "@/components/chat/onboarding-banner";
import { ConsentDialog, type ConsentRequest } from "@/components/consent-dialog";

interface ChatViewProps {
  initialSessionId?: string;
}

export function ChatView({ initialSessionId }: ChatViewProps = {}) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionSource, setSessionSource] = useState("web");
  const [sessionUsage, setSessionUsage] = useState<Usage>({ input: 0, output: 0, cache: 0 });
  const [models, setModels] = useState<{ id: string; description: string }[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [pendingFiles, setPendingFiles] = useState<{ name: string; path: string }[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null);

  const handleConsentRespond = async (requestId: string, allowed: boolean) => {
    setConsentRequest(null);
    try {
      await respondConsent(requestId, allowed);
    } catch {
      // 网络错误时按拒绝处理，避免 Agent 卡死
    }
  };

  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 记录「刚由本组件流式完成并 router.replace 进来的 session id」，
  // 让下面的 useEffect 跳过对它的重新 fetch，避免流式刚结束就刷新覆盖。
  const justFinishedRef = useRef<string | null>(null);

  // Load session when route param changes
  useEffect(() => {
    if (initialSessionId) {
      // 如果正在流式输出中（刚新建会话并发送消息），不重新加载
      // 因为此时 session 刚创建，DB 里还没有消息，fetchSession 会返回空数组
      if (initialSessionId === activeSession && streaming) return;
      // 流式刚结束、本组件自己 router.replace 进来的 session：消息已是最新，
      // 跳过 fetch 避免覆盖（否则会闪烁、丢失 ttft/toolsExpanded 状态）
      if (justFinishedRef.current === initialSessionId) {
        justFinishedRef.current = null;
        return;
      }
      fetchSession(initialSessionId)
        .then((detail) => {
          setActiveSession(initialSessionId);
          setSessionTitle(detail.title || "");
          setSessionSource(detail.source || "web");
          setMessages(
            detail.messages.map((m: any) => ({
              role: m.role,
              content: m.content,
              created_at: m.created_at,
              usage: m.usage || undefined,
              toolSteps: m.tool_steps && m.tool_steps.length > 0
                ? m.tool_steps.map((s: any) => ({
                    tool: s.tool,
                    args: s.args,
                    state: s.state as "running" | "done" | "error",
                    duration_ms: s.duration_ms,
                    result_preview: s.result_preview,
                    sub_steps: s.sub_steps?.map((ss: any) => ({
                      tool: ss.tool,
                      args: ss.args,
                      state: ss.state as "running" | "done" | "error",
                      duration_ms: ss.duration_ms ?? undefined,
                      result_preview: ss.result_preview,
                    })),
                  }))
                : undefined,
              toolsExpanded: false,
            }))
          );
          setSelectedModel(detail.model);
          const historicUsage = detail.messages
            .filter((m: any) => m.role === "assistant" && m.usage)
            .reduce((acc: any, m: any) => ({
              input: acc.input + (m.usage.input || 0),
              output: acc.output + (m.usage.output || 0),
              cache: acc.cache + (m.usage.cache || 0),
            }), { input: 0, output: 0, cache: 0 });
          setSessionUsage(historicUsage);
        })
        .catch(() => {
          setActiveSession(null);
          setSessionTitle("");
          setMessages([]);
        });
    } else {
      setActiveSession(null);
      setSessionTitle("");
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
      setSessionSource("web");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  useEffect(() => {
    // 加载模型列表 + agent 设置（取 default_model 作为新建对话的默认选中）
    Promise.all([fetchModels(), fetchAgentSettings()]).then(([m, settings]) => {
      setModels(m);
      // 仅当当前没选中模型时初始化：优先用 default_model，否则列表第一个
      setSelectedModel((prev) => prev || settings.default_model || (m.length > 0 ? m[0].id : ""));
    }).catch(() => {
      fetchModels().then((m) => {
        setModels(m);
        if (m.length > 0) setSelectedModel((prev) => prev || m[0].id);
      }).catch(() => {});
    });
  }, []);

  // Only fetch schedules for scheduled-task sessions
  useEffect(() => {
    if (sessionTitle.startsWith("[定时]")) {
      fetchSchedules().then(setSchedules).catch(() => {});
    }
  }, [sessionTitle]);

  // Focus input when entering a session or after streaming ends
  useEffect(() => {
    if (!streaming) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [initialSessionId, streaming]);

  // Check first-time onboarding on mount
  useEffect(() => {
    fetchOnboardingStatus().then((status) => {
      if (status.first_time) setShowOnboarding(true);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSend = async (text: string) => {
    if (!text.trim() && pendingFiles.length === 0) return;
    if (streaming) return;

    let sessionId = activeSession;
    if (!sessionId) {
      const s = await createSession(selectedModel);
      sessionId = s.id;
      setActiveSession(s.id);
      setSessionTitle(text.slice(0, 30) || "New chat");
      // URL 延迟到流式结束后再更新，避免 Next.js App Router 在流式中途卸载组件
    }

    let content = text;
    if (pendingFiles.length > 0) {
      const fileContext = pendingFiles.map((f) => `[Uploaded file: ${f.name} at ${f.path}]`).join("\n");
      content = `${fileContext}\n\n${text}`;
    }

    const userMsg: Message = {
      role: "user",
      content,
      files: pendingFiles.map((f) => f.name),
      created_at: Date.now() / 1000,
      quote: quote ?? undefined,
    };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    const sentQuote = quote;
    setPendingFiles([]);
    setQuote(null);
    setStreaming(true);

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({ role: m.role, content: m.content }));

    let assistantContent = "";
    let assistantThought = "";
    const currentToolSteps: ToolStep[] = [];
    const sendTime = Date.now();
    let ttft: number | undefined;
    let finalUsage: Usage | undefined;
    setMessages([...newMessages, { role: "assistant", content: "", created_at: Date.now() / 1000 }]);

    try {
      for await (const chunk of streamChat(chatMessages, selectedModel, sessionId, sentQuote)) {
        if (ttft === undefined) ttft = Date.now() - sendTime;

        if (chunk.consent_request) {
          setConsentRequest({
            request_id: chunk.request_id || "",
            tool: chunk.tool || "",
            description: chunk.description || "",
            detail: chunk.detail,
          });
          continue;
        }
        if (chunk.error) {
          assistantContent = `Error: ${chunk.error}`;
          break;
        }
        if (chunk.tool && chunk.state === "start") {
          if (assistantContent) {
            assistantThought += (assistantThought ? "\n\n" : "") + assistantContent;
            assistantContent = "";
          }
          currentToolSteps.push({ tool: chunk.tool, args: chunk.args || "", state: "running", id: chunk.id });
          setMessages([...newMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
          // 优先按 id 精确匹配（同名工具并发不串），fallback 到 tool 名
          let matchedIdx = -1;
          if (chunk.id) {
            for (let i = currentToolSteps.length - 1; i >= 0; i--) {
              if (currentToolSteps[i].id === chunk.id && currentToolSteps[i].state === "running") {
                matchedIdx = i; break;
              }
            }
          }
          if (matchedIdx < 0) {
            for (let i = currentToolSteps.length - 1; i >= 0; i--) {
              if (currentToolSteps[i].tool === chunk.tool && currentToolSteps[i].state === "running") {
                matchedIdx = i; break;
              }
            }
          }
          if (matchedIdx >= 0) {
            currentToolSteps[matchedIdx] = {
              ...currentToolSteps[matchedIdx],
              state: chunk.state as "done" | "error",
              duration_ms: chunk.duration_ms,
              result_preview: chunk.result_preview,
              sub_steps: chunk.sub_steps?.map((s) => ({
                tool: s.tool,
                args: s.args,
                state: s.state as "running" | "done" | "error",
                duration_ms: s.duration_ms ?? undefined,
                result_preview: s.result_preview,
              })),
            };
          }
          setMessages([...newMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages([...newMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
            toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
            created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.done && chunk.usage) {
          finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
          setSessionUsage(prev => ({
            input: prev.input + finalUsage!.input,
            output: prev.output + finalUsage!.output,
            cache: prev.cache + finalUsage!.cache,
          }));
        }
      }
    } catch (err) {
      assistantContent = `Error: ${err instanceof Error ? err.message : "Unknown error"}`;
    }

    setMessages(prev => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: assistantContent, thought: assistantThought, toolsExpanded: false, usage: finalUsage || last.usage, ttft };
        return msgs;
      }
      return [...newMessages, { role: "assistant", content: assistantContent, thought: assistantThought, created_at: Date.now() / 1000, usage: finalUsage, ttft }];
    });
    setStreaming(false);
    // 新建会话流式结束后，改地址栏 URL 让用户能复制/刷新。
    // 用 window.history.replaceState 而非 router.replace：前者只改 URL 不触发
    // Next 路由导航，避免 /chat → /chat/[id] 跨路由导致 ChatView 卸载重建（state 丢失、刷新）。
    if (!initialSessionId && sessionId) {
      justFinishedRef.current = sessionId;
      window.history.replaceState(null, "", `/chat/${sessionId}`);
    }
  };

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

      <MessageList
        messages={messages}
        streaming={streaming}
        onQuote={(m) => {
          setQuote({ role: m.role, content: m.content });
          setTimeout(() => inputRef.current?.focus(), 30);
        }}
      />

      <div>
        <div className="max-w-3xl mx-auto px-4 pt-4">
          {showOnboarding && <OnboardingBanner onDismiss={() => setShowOnboarding(false)} />}
        </div>
        <ChatInput
          streaming={streaming}
          models={models}
          selectedModel={selectedModel}
          pendingFiles={pendingFiles}
          quote={quote}
          inputRef={inputRef}
          onModelChange={setSelectedModel}
          onSend={handleSend}
          onFilesChange={setPendingFiles}
          onQuoteCancel={() => setQuote(null)}
        />
      </div>
      <ConsentDialog request={consentRequest} onRespond={handleConsentRespond} />
    </div>
  );
}
