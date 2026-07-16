"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ChatMessage,
  createSession,
  fetchModels,
  fetchModes,
  type ModeEntry,
  type ModelEntry,
  fetchSession,
  fetchSessions,
  fetchSchedules,
  streamChat,
  streamResume,
  stopGeneration,
  type StreamChunk,
  compactSession,
  updateSessionMode,
  fetchOnboardingStatus,
  fetchAgentSettings,
  respondConsent,
  getAnnotationsBatch,
  type Annotation,
} from "@/lib/api";
import { ReadingMode } from "@/components/chat/reading-mode";
import { ShareMode } from "@/components/chat/share-mode";
import type { ToolStep } from "@/components/tool-timeline";
import type { Message, Usage, Quote, PendingFile } from "@/components/chat/types";
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
  // 对话模式：数据驱动，模式表由后端 /modes 提供（不在前端硬编码任何具体人格）
  const [mode, setMode] = useState<string>("");
  const [modes, setModes] = useState<ModeEntry[]>([]);

  // 标注缓存：messageId -> Annotation[]（按 message id 缓存，避免每气泡重复请求）
  const [annotationsByMessage, setAnnotationsByMessage] = useState<Record<number, Annotation[]>>({});
  // 阅读模式：打开时记录正在阅读的 assistant 消息
  const [readingMessage, setReadingMessage] = useState<Message | null>(null);
  // 分享模式：记录被点开的消息及其默认选中的 key（用 key 触发重挂载以重置选择）
  const [shareMessage, setShareMessage] = useState<Message | null>(null);
  const [shareDefaultKey, setShareDefaultKey] = useState<string | null>(null);

  // 取一批 assistant 消息的标注，合并进缓存
  const fetchAnnotationsFor = async (msgs: Message[]) => {
    const ids = msgs.filter((m) => m.role === "assistant" && m.id != null).map((m) => m.id as number);
    if (ids.length === 0) return;
    try {
      const map = await getAnnotationsBatch(ids);
      setAnnotationsByMessage((prev) => ({ ...prev, ...map }));
    } catch {
      // 标注读取失败不阻断阅读
    }
  };

  const handleConsentRespond = async (requestId: string, allowed: boolean) => {
    setConsentRequest(null);
    try {
      await respondConsent(requestId, allowed);
    } catch {
      // 网络错误时按拒绝处理，避免 Agent 卡死
    }
  };

  // 进入阅读模式（仅 assistant 消息，且已有稳定 id 才能存标注）
  const handleRead = (msg: Message) => {
    if (msg.id == null) return;
    setReadingMessage(msg);
  };

  // 阅读模式里新建/删除标注后，把最新列表写回缓存（气泡据此淡显回显）
  const handleAnnotationsChange = (next: Annotation[]) => {
    if (readingMessage?.id == null) return;
    const mid = readingMessage.id;
    setAnnotationsByMessage((prev) => ({ ...prev, [mid]: next }));
  };

  // 进入分享模式：默认只选中被点开的这条气泡
  const handleShare = (msg: Message) => {
    const key = msg.id != null ? `id:${msg.id}` : `idx:${messages.indexOf(msg)}`;
    setShareDefaultKey(key);
    setShareMessage(msg);
  };

  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 记录「刚由本组件流式完成并 router.replace 进来的 session id」，
  // 让下面的 useEffect 跳过对它的重新 fetch，避免流式刚结束就刷新覆盖。
  const justFinishedRef = useRef<string | null>(null);

  // SessionDetail.messages → 组件内 Message[]（fetchSession 初次加载 + 重连失败兜底共用）
  const mapDetailMessages = (detail: { messages: any[] }): Message[] =>
    detail.messages.map((m: any) => ({
      role: m.role,
      id: m.id ?? undefined,
      content: m.content,
      created_at: m.created_at,
      usage: m.usage || undefined,
      quote: m.quote || undefined,
      images: m.images && m.images.length > 0
        ? m.images.map((img: any) => ({
            name: "",
            path: "",
            isImage: true,
            dataUrl: img.data ? `data:${img.media_type || "image/png"};base64,${img.data}` : img.dataUrl,
          }))
        : undefined,
      toolSteps: m.tool_steps && m.tool_steps.length > 0
        ? m.tool_steps.map((s: any) => ({
            tool: s.tool,
            args: s.args,
            intent: s.intent,
            state: s.state as "running" | "done" | "error",
            duration_ms: s.duration_ms,
            result_preview: s.result_preview,
            result_detail: s.result_detail,
            thought: s.thought,
            entity_type: s.entity_type,
            entity_id: s.entity_id,
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
      mcpApps: m.mcp_apps && m.mcp_apps.length > 0 ? m.mcp_apps : undefined,
      matchedSkills: m.matched_skills || undefined,
      ttfb_ms: m.ttfb_ms ?? undefined,
      total_ms: m.total_ms ?? undefined,
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
    let intermediateOutput = "";
    const assistantThought = "";
    const currentToolSteps: ToolStep[] = [];
    let currentMatchedSkills: { name: string; is_default?: boolean }[] | undefined;
    const a2uiSurfaces: unknown[] = [];
    const mcpAppsCollected: Array<{ uri: string; data?: Record<string, unknown>; html?: string; csp?: Record<string, string[]> }> = [];
    const sendTime = Date.now();
    let ttft: number | undefined;
    let ttfbMs: number | undefined;
    let totalMs: number | undefined;
    let messageId: number | undefined;
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
        if (chunk.skills_matched) {
          currentMatchedSkills = chunk.skills_matched;
          continue;
        }
        if (chunk.background_polling) {
          setBgPolling(chunk.polling_message || "\U0001f4e1 后台任务运行中...");
          continue;
        }
        if (chunk.new_message) {
          // 后台任务结果作为独立消息推送（不拼到当前消息末尾）
          setBgPolling(null);
          setMessages(prev => [...prev, {
            role: "assistant",
            content: chunk.content || "",
            created_at: Date.now() / 1000,
          }]);
          continue;
        }
        if (chunk.heartbeat) {
          // watchdog 心跳：任务仍在运行但超过 3 分钟无新内容
          const elapsed = chunk.elapsed || 0;
          const mins = Math.floor(elapsed / 60);
          const secs = elapsed % 60;
          const timeStr = mins > 0 ? `${mins} 分 ${secs} 秒` : `${secs} 秒`;
          const statusNote = `_⏳ 任务仍在运行中，已用时 ${timeStr}，请稍候…_`;
          setMessages([...baseMessages, {
            role: "assistant",
            content: assistantContent || statusNote,
            thought: assistantThought,
            toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
            toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
            created_at: Date.now() / 1000,
            intermediateOutput: intermediateOutput || undefined,
          }]);
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
          if (preToolThought) {
            intermediateOutput += (intermediateOutput ? "\n\n" : "") + preToolThought;
          }
          assistantContent = "";
          currentToolSteps.push({
            tool: chunk.tool, args: chunk.args || "", intent: chunk.intent || undefined, state: "running", id: chunk.id,
            thought: preToolThought || undefined,
            entity_type: chunk.entity_type || undefined,
            entity_id: chunk.entity_id || undefined,
          });
          setMessages([...baseMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
            intermediateOutput: intermediateOutput || undefined,
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
              entity_type: chunk.entity_type || currentToolSteps[matchedIdx].entity_type,
              entity_id: chunk.entity_id || currentToolSteps[matchedIdx].entity_id,
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
            intermediateOutput: intermediateOutput || undefined,
          }]);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error") && chunk.ui && Array.isArray(chunk.ui)) {
          a2uiSurfaces.push(...chunk.ui);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error") && chunk.mcp_app) {
          mcpAppsCollected.push(chunk.mcp_app);
        }
        if (chunk.content) {
          setBgPolling(null);
          assistantContent += chunk.content;
          setMessages([...baseMessages, {
            role: "assistant", content: assistantContent, thought: assistantThought,
            toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
            toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
            created_at: Date.now() / 1000,
            intermediateOutput: intermediateOutput || undefined,
          }]);
        }
        if (chunk.done && chunk.usage) {
          finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
          if (chunk.ttfb_ms != null) ttfbMs = chunk.ttfb_ms;
          if (chunk.total_ms != null) totalMs = chunk.total_ms;
          if (chunk.message_id != null) messageId = chunk.message_id;
          if (chunk.title) setSessionTitle(chunk.title);
          setSessionUsage(prev => ({
            input: prev.input + finalUsage!.input,
            output: prev.output + finalUsage!.output,
            cache: prev.cache + finalUsage!.cache,
          }));
        }
        if (chunk.done) {
          setBgPolling(null);
        }
        if (chunk.stopped) {
          // 用户主动停止：补一个「已停止」标记（后端也会落库同样标记，这里只为即时反馈）
          if (!assistantContent.trimEnd().endsWith("（已停止）")) {
            assistantContent = assistantContent.trim()
              ? `${assistantContent}\n\n_（已停止）_`
              : "_（已停止）_";
          }
          if (chunk.usage) {
            finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
          }
          break;
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
        msgs[msgs.length - 1] = {
          ...last,
          content: assistantContent,
          thought: assistantThought,
          toolsExpanded: false,
          usage: finalUsage || last.usage,
          ttft: ttft ?? last.ttft,
          ttfb_ms: ttfbMs ?? last.ttfb_ms,
          total_ms: totalMs ?? last.total_ms,
          a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined,
          mcpApps: mcpAppsCollected.length > 0 ? mcpAppsCollected : undefined,
          matchedSkills: currentMatchedSkills,
          id: messageId ?? last.id,
          intermediateOutput: intermediateOutput || undefined,
        };
        return msgs;
      }
      return [...baseMessages, {
        role: "assistant",
        content: assistantContent,
        thought: assistantThought,
        created_at: Date.now() / 1000,
        usage: finalUsage,
        ttft,
        ttfb_ms: ttfbMs,
        total_ms: totalMs,
        a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined,
        mcpApps: mcpAppsCollected.length > 0 ? mcpAppsCollected : undefined,
        matchedSkills: currentMatchedSkills,
        id: messageId,
        intermediateOutput: intermediateOutput || undefined,
      }];
    });
    setBgPolling(null);
    setStopping(false);
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
          fetchAnnotationsFor(loaded);
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
              // loaded 末尾可能已有部分 assistant 消息（后端实时落库的进度行）。
              // consumeStream 会从 stream replay 重建 assistant 消息，先把它剥掉，
              // 否则刷新后会出现两条 assistant 消息（DB 一条 + replay 一条）。
              const base = loaded.length > 0 && loaded[loaded.length - 1].role === "assistant"
                ? loaded.slice(0, -1)
                : loaded;
              await consumeStream(stream, base);
            } else {
              setStreaming(false);
              const fresh = await fetchSession(initialSessionId).catch(() => null);
              if (fresh) {
                const freshMsgs = mapDetailMessages(fresh);
                setMessages(freshMsgs);
                fetchAnnotationsFor(freshMsgs);
              }
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
    // /btw 先判断，避免被当作未知命令拦截
    const isBtw = trimmed.toLowerCase().startsWith("/btw ");
    const isReview = trimmed === "/review" || trimmed.startsWith("/review ") || trimmed.startsWith("/review\t");
    if (trimmed.startsWith("/") && !isBtw && !isReview) {
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
        window.history.replaceState(null, "", `/chat/${s.id}/`);
        return;
      }
      if (cmd === "help") {
        pushAssistant(
          "🛠 **可用命令**\n\n" +
          "- `/new` — 新建对话，清空当前上下文\n" +
          "- `/compact` — 压缩历史对话为摘要，释放上下文\n" +
          "- `/sessions` — 列出最近的会话\n" +
          "- `/stop` — 停止当前进行中的回复\n" +
          "- `/btw <问题>` — 不带历史的单轮轻量查询\n" +
          "- `/review <链接>` — Code review：加载 review 技能分析代码\n" +
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
      if (cmd === "stop") {
        if (activeSession) {
          await stopGeneration(activeSession).catch(() => {});
        }
        return;
      }
      // 未知命令
      pushAssistant(`未知命令：\`/${cmd}\`\n\n输入 \`/help\` 查看可用命令。`);
      return;
    }

    // /btw 顺带一问：不带历史，单轮轻量查询
    const btwQuestion = isBtw ? trimmed.slice(4).trim() : null;

    let sessionId = activeSession;
    if (!sessionId) {
      const s = await createSession(selectedModel, mode);
      sessionId = s.id;
      setActiveSession(s.id);
      setSessionTitle(text.slice(0, 30) || "New chat");
      // 立即更新 URL，让用户点「新建会话」时路由能正确切换。
      // 用 replaceState 而非 router.replace：只改地址栏不触发 Next 路由导航，
      // 避免跨路由卸载组件丢失 state。
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
      // 立即从 URL 解析 PR 标题并更新（不等 review 跑完）
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

    // 模型不支持图片时弹确认，用户选择后再继续
    const modelInfo = models.find((m) => m.id === selectedModel);
    const visionSupported = modelInfo?.vision !== false;  // 默认 true（新模型大多支持）
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
        // dataUrl 格式 "data:image/png;base64,xxx"，只取后面的 base64 部分
        data: img.dataUrl?.split(",")[1] ?? "",
        media_type: img.dataUrl?.split(";")[0].replace("data:", "") ?? "image/png",
      })),
    }));

    await consumeStream(
      streamChat(chatMessages, selectedModel, sessionId, { quote: sentQuote, mode, btw: isBtw, review: isReview }),
      newMessages,
      true,
    );
    // 标题已在 done 事件中实时更新（chunk.title），无需额外 poll
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
        onRead={handleRead}
        onShare={handleShare}
        annotationsByMessage={annotationsByMessage}
      />

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
