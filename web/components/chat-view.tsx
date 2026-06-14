"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Paperclip, Loader2, Pencil, Check, X, Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Clock, Calendar } from "lucide-react";

// CommonMark 规定 ** 紧内侧不能有空格，否则不渲染加粗。
// 此函数去掉 AI 生成文本中 ** 内侧的多余空白，修复渲染。
function fixBold(text: string): string {
  return text.replace(/\*\*[ \t]*((?:[^*\n]|\*(?!\*))+?)[ \t]*\*\*/g, (_, inner) => {
    const trimmed = inner.trim();
    return trimmed ? `**${trimmed}**` : `**${inner}**`;
  });
}

function formatTime(ts?: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const yyyy = d.getFullYear();
  const MM = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const HH = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
}

import {
  ChatMessage,
  SessionInfo,
  createSession,
  fetchModels,
  fetchSession,
  fetchSessions,
  fetchSchedules,
  renameSession,
  streamChat,
  uploadFile,
  fetchOnboardingStatus,
  completeOnboarding,
} from "@/lib/api";
import { ToolTimeline, ToolStep } from "@/components/tool-timeline";

interface Message {
  role: "user" | "assistant";
  content: string;
  files?: string[];
  toolSteps?: ToolStep[];
  toolsExpanded?: boolean;
  created_at?: number;
  usage?: { input: number; output: number; cache: number };
  ttft?: number;
}

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("ethan-theme") as "dark" | "light") || "dark";
    }
    return "dark";
  });

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("ethan-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("light", next === "light");
      return next;
    });
  }, []);

  return { theme, toggle };
}

interface ChatViewProps {
  initialSessionId?: string;
}

export function ChatView({ initialSessionId }: ChatViewProps = {}) {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [schedules, setSchedules] = useState<any[]>([]);

  useEffect(() => {
    fetchSchedules().then(setSchedules).catch(() => {});
  }, []);

  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const { theme, toggle: toggleTheme } = useTheme();

  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [models, setModels] = useState<{ id: string; description: string }[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [pendingFiles, setPendingFiles] = useState<{ name: string; path: string }[]>([]);
  const [sessionUsage, setSessionUsage] = useState<{ input: number; output: number; cache: number }>({ input: 0, output: 0, cache: 0 });
  const [sessionSource, setSessionSource] = useState<string>("web");

  // Onboarding state
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingAgentName, setOnboardingAgentName] = useState("");
  const [onboardingUserInfo, setOnboardingUserInfo] = useState("");
  const [onboardingSubmitting, setOnboardingSubmitting] = useState(false);

  // Load session from initialSessionId prop (route param)
  useEffect(() => {
    if (initialSessionId) {
      // 如果正在流式输出中（刚新建会话并发送消息），不重新加载
      // 因为此时 session 刚创建，DB 里还没有消息，fetchSession 会返回空数组
      if (initialSessionId === activeSession && streaming) return;

      fetchSession(initialSessionId)
        .then((detail) => {
          setActiveSession(initialSessionId);
          setMessages(
            detail.messages.map((m: any) => ({
              role: m.role,
              content: m.content,
              created_at: m.created_at,
              usage: m.usage || undefined,
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
          setSessionSource(detail.source || "web");
        })
        .catch(() => {
          setActiveSession(null);
          setMessages([]);
        });
    } else {
      setActiveSession(null);
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
      setSessionSource("web");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  // 进入对话或新建时 focus 输入框
  useEffect(() => {
    if (!streaming) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [initialSessionId, streaming]);

  useEffect(() => {
    fetchModels().then((m) => {
      setModels(m);
      if (m.length > 0) setSelectedModel((prev) => prev || m[0].id);
    }).catch(() => {});
  }, []);

  // Load sessions list for header display
  useEffect(() => {
    fetchSessions(50).then(setSessions).catch(() => {});
  }, [initialSessionId]);

  // Check first-time onboarding on mount
  useEffect(() => {
    fetchOnboardingStatus().then((status) => {
      if (status.first_time) setShowOnboarding(true);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startEditSession = (id: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(id);
    setEditingTitle(currentTitle);
  };

  const commitRename = async (id: string) => {
    const title = editingTitle.trim();
    if (title) {
      await renameSession(id, title);
      setSessions((prev) => prev.map((s) => s.id === id ? { ...s, title } : s));
    }
    setEditingSessionId(null);
  };

  const cancelEdit = () => setEditingSessionId(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      const result = await uploadFile(file);
      setPendingFiles((prev) => [...prev, { name: result.filename, path: result.path }]);
    }
    e.target.value = "";
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text && pendingFiles.length === 0) return;
    if (streaming) return;

    let sessionId = activeSession;
    if (!sessionId) {
      const s = await createSession(selectedModel);
      sessionId = s.id;
      setActiveSession(s.id);
      setSessions((prev) => [
        { id: s.id, title: text.slice(0, 30) || "New chat", model: s.model, created_at: Date.now() / 1000, updated_at: Date.now() / 1000 },
        ...prev,
      ]);
      // URL 延迟到流式结束后再更新，避免 Next.js App Router 在流式中途卸载组件
    }

    let content = text;
    if (pendingFiles.length > 0) {
      const fileContext = pendingFiles.map((f) => `[Uploaded file: ${f.name} at ${f.path}]`).join("\n");
      content = `${fileContext}\n\n${text}`;
    }

    const userMsg: Message = { role: "user", content, files: pendingFiles.map((f) => f.name), created_at: Date.now() / 1000 };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setPendingFiles([]);
    setStreaming(true);

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({ role: m.role, content: m.content }));

    let assistantContent = "";
    const currentToolSteps: ToolStep[] = [];
    const sendTime = Date.now();
    let ttft: number | undefined;
    let finalUsage: { input: number; output: number; cache: number } | undefined;
    setMessages([...newMessages, { role: "assistant", content: "", created_at: Date.now() / 1000 }]);

    try {
      for await (const chunk of streamChat(chatMessages, selectedModel, sessionId)) {
        if (ttft === undefined) ttft = Date.now() - sendTime;

        if (chunk.error) {
          assistantContent = `Error: ${chunk.error}`;
          break;
        }
        if (chunk.tool && chunk.state === "start") {
          currentToolSteps.push({ tool: chunk.tool, args: chunk.args || "", state: "running" });
          setMessages([...newMessages, {
            role: "assistant",
            content: assistantContent,
            toolSteps: [...currentToolSteps],
            toolsExpanded: true,
            created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
          for (let i = currentToolSteps.length - 1; i >= 0; i--) {
            if (currentToolSteps[i].tool === chunk.tool && currentToolSteps[i].state === "running") {
              currentToolSteps[i] = {
                ...currentToolSteps[i],
                state: chunk.state as "done" | "error",
                duration_ms: chunk.duration_ms,
                result_preview: chunk.result_preview,
              };
              break;
            }
          }
          setMessages([...newMessages, {
            role: "assistant",
            content: assistantContent,
            toolSteps: [...currentToolSteps],
            toolsExpanded: true,
            created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages([...newMessages, {
            role: "assistant",
            content: assistantContent,
            toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
            toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
            created_at: Date.now() / 1000,
          }]);
        }
        if (chunk.done) {
          if (chunk.usage) {
            finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
            setSessionUsage(prev => ({ input: prev.input + finalUsage!.input, output: prev.output + finalUsage!.output, cache: prev.cache + finalUsage!.cache }));
          }
        }
      }
    } catch (err) {
      assistantContent = `Error: ${err instanceof Error ? err.message : "Unknown error"}`;
    }

    setMessages(prev => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = {
          ...last,
          toolsExpanded: false,
          usage: finalUsage || last.usage,
          ttft,
        };
        return msgs;
      }
      return [...newMessages, { role: "assistant", content: assistantContent, created_at: Date.now() / 1000, usage: finalUsage, ttft }];
    });
    setStreaming(false);
    fetchSessions().then(setSessions).catch(() => {});
    // 流式结束后再更新 URL，此时 session 已有消息，不会触发空消息覆盖
    if (!initialSessionId && sessionId) {
      router.replace(`/chat/${sessionId}`);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleOnboardingSubmit = async () => {
    setOnboardingSubmitting(true);
    try {
      await completeOnboarding(onboardingAgentName.trim() || "Ethan", onboardingUserInfo.trim());
      setShowOnboarding(false);
    } catch {
      setShowOnboarding(false);
    } finally {
      setOnboardingSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col flex-1 h-full">
      {/* Header */}
      <header className="h-auto min-h-14 border-b border-border flex flex-col justify-center px-4 py-2 shrink-0">
        <div className="flex items-center gap-3 w-full">
          {/* Current session title, editable */}
          {activeSession && (() => {
            const cur = sessions.find((s) => s.id === activeSession);
            if (!cur) return null;
            return editingSessionId === activeSession ? (
              <div className="flex items-center gap-1 flex-1 min-w-0">
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") commitRename(activeSession); if (e.key === "Escape") cancelEdit(); }}
                  className="flex-1 min-w-0 bg-transparent outline-none border-b border-primary text-lg font-semibold"
                />
                <button onClick={() => commitRename(activeSession)} className="text-primary hover:opacity-70"><Check className="h-4 w-4" /></button>
                <button onClick={cancelEdit} className="text-muted-foreground hover:opacity-70"><X className="h-4 w-4" /></button>
              </div>
            ) : (
              <button
                className="flex items-center gap-1.5 text-lg font-semibold truncate hover:text-primary group"
                onClick={(e) => startEditSession(activeSession, cur.title, e)}
                title="Click to rename"
              >
                <span className="truncate">{cur.title}</span>
                <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50 shrink-0" />
              </button>
            );
          })()}

          {/* 来源 badge */}
          {activeSession && sessionSource && (() => {
            const sourceLabel: Record<string, string> = { lark: "飞书", repl: "命令行", web: "Web", heartbeat: "心跳" };
            const sourceColor: Record<string, string> = {
              lark: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
              repl: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
              web: "bg-green-500/15 text-green-600 dark:text-green-400",
              heartbeat: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
            };
            return (
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ${sourceColor[sessionSource] || "bg-muted text-muted-foreground"}`}>
                {sourceLabel[sessionSource] || sessionSource}
              </span>
            );
          })()}

          {(sessionUsage.input > 0 || sessionUsage.output > 0) && (
            <span className="text-xs text-muted-foreground ml-auto" title="本次对话累计 token 消耗">
              ↑{sessionUsage.input.toLocaleString()} ↓{sessionUsage.output.toLocaleString()}{sessionUsage.cache > 0 ? ` ⚡${sessionUsage.cache.toLocaleString()}` : ""}
            </span>
          )}

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className={sessionUsage.input > 0 ? "ml-2" : "ml-auto"}
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>

        {/* Scheduled Task Info Banner */}
        {(() => {
          const activeSessionInfo = sessions.find((s) => s.id === activeSession);
          if (activeSessionInfo && activeSessionInfo.title.startsWith("[定时]")) {
            const jobId = activeSessionInfo.title.replace("[定时] ", "").trim();
            const job = schedules.find(j => j.id === jobId || j.name === jobId);
            if (job) {
              return (
                <div className="mt-2 text-xs bg-muted/50 rounded-md p-2 flex items-center gap-4 text-muted-foreground border border-border/50">
                  <div className="flex items-center gap-1"><Clock className="h-3 w-3" /> <span>定时规则: {job.trigger}</span></div>
                  <div className="flex items-center gap-1"><Calendar className="h-3 w-3" /> <span>下次执行: {job.next_run_time || "已暂停"}</span></div>
                </div>
              );
            }
          }
          return null;
        })()}
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p>Start a conversation</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] md:max-w-[80%] rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted prose prose-sm dark:prose-invert max-w-none"
                }`}
              >
                {msg.role === "user" ? (
                  <>
                    {msg.files && msg.files.length > 0 && (
                      <div className="text-xs opacity-70 mb-1">
                        {msg.files.map((f, j) => <span key={j} className="mr-2">📎 {f}</span>)}
                      </div>
                    )}
                    <p className="whitespace-pre-wrap">{msg.content.split("\n\n").pop()}</p>
                    {msg.created_at && (
                      <div className="text-[10px] opacity-40 mt-1 text-right">
                        {formatTime(msg.created_at)}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    {msg.toolSteps && msg.toolSteps.length > 0 && (
                      <ToolTimeline
                        steps={msg.toolSteps}
                        defaultExpanded={msg.toolsExpanded ?? false}
                      />
                    )}
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        pre: ({ children }) => <pre className="bg-background/50 rounded-lg p-3 overflow-x-auto text-xs">{children}</pre>,
                        code: ({ className, children, ...props }) => {
                          const isInline = !className;
                          return isInline
                            ? <code className="bg-background/50 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
                            : <code className={className} {...props}>{children}</code>;
                        },
                      }}
                    >
                      {fixBold(msg.content)}
                    </ReactMarkdown>
                    <div className="flex justify-between items-end mt-2">
                      <span className="text-[10px] text-muted-foreground/40">{msg.created_at ? formatTime(msg.created_at) : ""}</span>
                      {msg.usage && (
                        <span className="text-[10px] text-muted-foreground/30 tabular-nums">
                          ↑{msg.usage.input.toLocaleString()} ↓{msg.usage.output.toLocaleString()}{msg.usage.cache > 0 ? ` ⚡${msg.usage.cache.toLocaleString()}` : ""}{msg.ttft !== undefined ? ` · ${msg.ttft < 1000 ? `${msg.ttft}ms` : `${(msg.ttft / 1000).toFixed(1)}s`}` : ""}
                        </span>
                      )}
                    </div>
                  </>
                )}
                {msg.role === "assistant" && streaming && i === messages.length - 1 && (
                  <span className="inline-block w-2 h-4 bg-foreground/50 animate-pulse ml-0.5" />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-border p-4">
        <div className="max-w-3xl mx-auto">
        {/* Onboarding banner */}
        {showOnboarding && (
          <div className="mb-4 rounded-xl border border-yellow-500/40 bg-yellow-500/10 p-4 space-y-3">
            <p className="text-sm font-semibold text-yellow-600 dark:text-yellow-400">
              👋 Welcome! Let me introduce myself.
            </p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Before we get started, I have two quick questions to personalize our experience.
              You can always update these in Settings later.
            </p>
            <div className="space-y-2">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  What would you like to call me? <span className="opacity-60">(default: Ethan)</span>
                </label>
                <input
                  type="text"
                  placeholder="Ethan"
                  value={onboardingAgentName}
                  onChange={(e) => setOnboardingAgentName(e.target.value)}
                  className="w-full bg-background border border-border rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Who are you? <span className="opacity-60">(e.g. "I'm Alex, a software engineer")</span>
                </label>
                <input
                  type="text"
                  placeholder="I'm ..."
                  value={onboardingUserInfo}
                  onChange={(e) => setOnboardingUserInfo(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleOnboardingSubmit(); }}
                  className="w-full bg-background border border-border rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowOnboarding(false)}
                className="text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-lg hover:bg-muted transition-colors"
              >
                Skip
              </button>
              <button
                onClick={handleOnboardingSubmit}
                disabled={onboardingSubmitting}
                className="text-xs bg-yellow-500 hover:bg-yellow-400 text-white font-semibold px-4 py-1.5 rounded-lg transition-colors disabled:opacity-50"
              >
                {onboardingSubmitting ? "Saving..." : "Let's go!"}
              </button>
            </div>
          </div>
        )}
        {pendingFiles.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap max-w-3xl mx-auto">
            {pendingFiles.map((f, i) => (
              <span key={i} className="text-xs bg-muted px-2 py-1 rounded-md flex items-center gap-1">
                📎 {f.name}
                <button onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-foreground">×</button>
              </span>
            ))}
          </div>
        )}
        {/* Unified input container */}
        <div className="max-w-3xl mx-auto rounded-2xl border border-border bg-muted/40 focus-within:border-ring/50 focus-within:bg-background transition-colors">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息… (Enter 发送，Shift+Enter 换行)"
            className="w-full resize-none bg-transparent px-4 pt-3 pb-2 text-sm outline-none min-h-[52px] max-h-[200px] leading-relaxed"
            rows={1}
            disabled={streaming}
          />
          {/* Bottom toolbar */}
          <div className="flex items-center gap-1 px-3 pb-2.5">
            {/* Attach */}
            <button
              onClick={() => fileRef.current?.click()}
              disabled={streaming}
              className="h-7 w-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
              title="附件"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <input ref={fileRef} type="file" className="hidden" multiple onChange={handleFileUpload} />
            {/* Model selector */}
            <Select value={selectedModel} onValueChange={(v) => v && setSelectedModel(v)} disabled={streaming}>
              <SelectTrigger className="h-7 px-2.5 text-xs bg-transparent border-0 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg shadow-none focus:ring-0 focus:ring-offset-0 gap-1 w-auto max-w-[160px]">
                <SelectValue placeholder="模型" />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m.id} value={m.id} className="text-xs">{m.description || m.id}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* Spacer */}
            <div className="flex-1" />
            {/* Send button */}
            <button
              onClick={handleSend}
              disabled={streaming || (!input.trim() && pendingFiles.length === 0)}
              className="h-7 w-7 flex items-center justify-center rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {streaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}
