"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ChatMessage,
  createSession,
  fetchModels,
  fetchModes,
  type ModeEntry,
  fetchSession,
  fetchSessions,
  fetchSchedules,
  streamChat,
  streamResume,
  type StreamChunk,
  compactSession,
  updateSessionMode,
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
import { type ConsentRequest } from "@/components/consent-dialog";
import { ConsentGate } from "@/components/chat/consent-card";

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
  // 对话模式：数据驱动，模式表由后端 /modes 提供（不在前端硬编码任何具体人格）
  const [mode, setMode] = useState<string>("");
  const [modes, setModes] = useState<ModeEntry[]>([]);

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

  // SessionDetail.messages → 组件内 Message[]（fetchSession 初次加载 + 重连失败兜底共用）
  const mapDetailMessages = (detail: { messages: any[] }): Message[] =>
    detail.messages.map((m: any) => ({
      role: m.role,
      content: m.content,
      created_at: m.created_at,
      usage: m.usage || undefined,
      quote: m.quote || undefined,
      toolSteps: m.tool_steps && m.tool_steps.length > 0
        ? m.tool_steps.map((s: any) => ({
            tool: s.tool,
            args: s.args,
            state: s.state as "running" | "done" | "error",
            duration_ms: s.duration_ms,
            result_preview: s.result_preview,
            result_detail: s.result_detail,
            thought: s.thought,
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
      a2ui: m.a2ui && m.a2ui.length > 0 ? m.a2ui : undefined,
    }));

  // 消费一条 SSE 事件流，增量更新最后一条 assistant 消息，结束后定稿。
  // 首次发送（streamChat）与刷新重连（streamResume）共用此逻辑。
  // baseMessages = assistant 之前的全部消息（含用户那句）；trackTtft 仅首发为 true。
  const consumeStream = async (
    stream: AsyncGenerator<StreamChunk>,
    baseMessages: Message[],
    trackTtft = false,
  ) => {
    let assistantContent = "";
    const assistantThought = "";
    const currentToolSteps: ToolStep[] = [];
    const a2uiSurfaces: unknown[] = [];
    const sendTime = Date.now();
    let ttft: number | undefined;
    let finalUsage: Usage | undefined;
    setMessages([...baseMessages, { role: "assistant", content: "", created_at: Date.now() / 1000 }]);

    try {
      for await (const chunk of stream) {
        if (trackTtft && ttft === undefined) ttft = Date.now() - sendTime;

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
          // 保留已流式输出的内容，把错误作为页脚追加，而不是整体覆盖用户正在读的回答
          const errLine = `⚠️ ${chunk.error}`;
          assistantContent = assistantContent.trim()
            ? `${assistantContent}\n\n---\n${errLine}`
            : errLine;
          break;
        }
        if (chunk.tool && chunk.state === "start") {
          const preToolThought = assistantContent.trim();
          assistantContent = "";
          currentToolSteps.push({
            tool: chunk.tool, args: chunk.args || "", state: "running", id: chunk.id,
            thought: preToolThought || undefined,
          });
          setMessages([...baseMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
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
              result_detail: chunk.result_detail,
              sub_steps: chunk.sub_steps?.map((s) => ({
                tool: s.tool,
                args: s.args,
                state: s.state as "running" | "done" | "error",
                duration_ms: s.duration_ms ?? undefined,
                result_preview: s.result_preview,
              })),
            };
          }
          setMessages([...baseMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error") && chunk.ui && Array.isArray(chunk.ui)) {
          a2uiSurfaces.push(...chunk.ui);
        }
        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages([...baseMessages, {
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
      const errLine = `⚠️ ${err instanceof Error ? err.message : "连接中断"}`;
      assistantContent = assistantContent.trim()
        ? `${assistantContent}\n\n---\n${errLine}`
        : errLine;
    }

    setMessages(prev => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: assistantContent, thought: assistantThought, toolsExpanded: false, usage: finalUsage || last.usage, ttft: ttft ?? last.ttft, a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined };
        return msgs;
      }
      return [...baseMessages, { role: "assistant", content: assistantContent, thought: assistantThought, created_at: Date.now() / 1000, usage: finalUsage, ttft, a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined }];
    });
    setStreaming(false);
  };

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
        .then(async (detail) => {
          setActiveSession(initialSessionId);
          setSessionTitle(detail.title || "");
          setSessionSource(detail.source || "web");
          const loaded = mapDetailMessages(detail);
          setMessages(loaded);
          setSelectedModel(detail.model);
          // 恢复对话模式：之前用工作助手还是苏念，下次进入保持一致
          setMode(detail.mode || "");
          const historicUsage = detail.messages
            .filter((m: any) => m.role === "assistant" && m.usage)
            .reduce((acc: any, m: any) => ({
              input: acc.input + (m.usage.input || 0),
              output: acc.output + (m.usage.output || 0),
              cache: acc.cache + (m.usage.cache || 0),
            }), { input: 0, output: 0, cache: 0 });
          setSessionUsage(historicUsage);

          // 该会话仍有正在进行的生成（刷新前发起的）：重连流，回放缓冲 + 继续实时，
          // 不丢失 assistant 回复。重连失败/已结束（204）则补一次 fetch 拿落库结果。
          if (detail.active_run) {
            setStreaming(true);
            const stream = await streamResume(initialSessionId).catch(() => null);
            if (stream) {
              await consumeStream(stream, loaded);
            } else {
              setStreaming(false);
              const fresh = await fetchSession(initialSessionId).catch(() => null);
              if (fresh) setMessages(mapDetailMessages(fresh));
            }
          }
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
      // 新建对话页面默认工作助手模式
      setMode("");
      // 重置模型为配置的默认模型（从 .env 读取的 AGENT_DEFAULT_MODEL）
      fetchAgentSettings().then((settings) => {
        if (settings.default_model) setSelectedModel(settings.default_model);
      }).catch(() => {});
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

  useEffect(() => {
    // 加载对话模式表（数据驱动 UI）
    fetchModes().then(setModes).catch(() => {});
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

    // ── /command 拦截：以 / 开头按命令处理，不发给 Agent ──
    const trimmed = text.trim();
    if (trimmed.startsWith("/")) {
      const [cmd, ...rest] = trimmed.slice(1).split(/\s+/);
      const arg = rest.join(" ").trim();
      const now = Date.now() / 1000;
      const pushAssistant = (content: string) =>
        setMessages((prev) => [...prev, { role: "assistant", content, created_at: now }]);

      if (cmd === "new") {
        const s = await createSession(selectedModel, mode);
        setActiveSession(s.id);
        setSessionTitle("新对话");
        setMessages([]);
        setSessionUsage({ input: 0, output: 0, cache: 0 });
        setPendingFiles([]);
        setQuote(null);
        window.history.replaceState(null, "", `/chat/${s.id}`);
        return;
      }
      if (cmd === "help") {
        pushAssistant(
          "🛠 **可用命令**\n\n" +
          "- `/new` — 新建对话，清空当前上下文\n" +
          "- `/compact` — 压缩历史对话为摘要，释放上下文\n" +
          "- `/sessions` — 列出最近的会话\n" +
          "- `/help` — 显示本帮助\n\n" +
          "（`/model` `/token` 请用顶部下拉和设置页；其它消息正常对话即可）"
        );
        return;
      }
      if (cmd === "compact") {
        if (!activeSession) {
          pushAssistant("⚠️ 当前没有会话，先聊几句再 `/compact` 吧~");
          return;
        }
        setStreaming(true);
        try {
          const r = await compactSession(activeSession);
          // 刷新会话内容（已被替换为摘要 + 最后一轮）
          const detail = await fetchSession(activeSession);
          setMessages(
            detail.messages.map((m: any) => ({
              role: m.role,
              content: m.content,
              created_at: m.created_at,
              usage: m.usage || undefined,
              toolsExpanded: false,
            }))
          );
          pushAssistant(`🧠 **已压缩历史**\n\n> ${r.summary.slice(0, 300)}${r.summary.length > 300 ? "…" : ""}\n\n继续聊吧~`);
        } catch (e) {
          pushAssistant(`⚠️ 压缩失败：${e instanceof Error ? e.message : "未知错误"}`);
        } finally {
          setStreaming(false);
        }
        return;
      }
      if (cmd === "sessions") {
        try {
          const list = await fetchSessions(8, 0);
          if (!list.length) {
            pushAssistant("暂无会话。");
          } else {
            const body = list
              .map((s) => `- \`${s.id.slice(-10)}\`  ${s.title || "（无标题）"}`)
              .join("\n");
            pushAssistant(`📋 **最近会话**\n\n${body}\n\n点击左侧侧栏可切换。`);
          }
        } catch {
          pushAssistant("⚠️ 获取会话列表失败。");
        }
        return;
      }
      // 未知命令
      pushAssistant(`未知命令：\`/${cmd}\`\n\n输入 \`/help\` 查看可用命令。`);
      return;
    }

    let sessionId = activeSession;
    if (!sessionId) {
      const s = await createSession(selectedModel, mode);
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

    await consumeStream(
      streamChat(chatMessages, selectedModel, sessionId, sentQuote, mode),
      newMessages,
      true,
    );
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
        onCardAction={(text) => handleSend(text)}
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
          onFilesChange={setPendingFiles}
          onQuoteCancel={() => setQuote(null)}
          modes={modes}
          mode={mode}
          onModeChange={(m) => {
            setMode(m);
            // 已有会话：立即落库，刷新/重进保持该模式（无会话时仅置前端 state，建会话时带上）
            if (activeSession) {
              updateSessionMode(activeSession, m).catch(() => {});
            }
          }}
        />
      </div>
    </div>
  );
}
