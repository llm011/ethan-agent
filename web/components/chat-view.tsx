"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Paperclip, Loader2, Pencil, Check, X, Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Clock, Calendar } from "lucide-react";

// 让中文字符旁的 **bold** 正确解析：在 CJK 与 ** 之间插零宽空格
const CJK = /[一-鿿㐀-䶿　-〿＀-￯⺀-⻿]/;
function fixBold(text: string): string {
  // 1. 修复 AI 生成的内部带空格的加粗格式：** text ** -> **text**
  let fixed = text.replace(/\*\*\s+([^\*]+?)\s+\*\*/g, '**$1**');

  // 2. 修复中文旁边的加粗格式不渲染：在 CJK 与 ** 之间插零宽空格
  fixed = fixed
    .replace(/([^\s*_`])\*\*/g, (match, c) => (CJK.test(c) ? `${c}​**` : `${c} **`))
    .replace(/\*\*([^\s*_`])/g, (match, c) => (CJK.test(c) ? `**​${c}` : `** ${c}`));

  return fixed;
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

interface Message {
  role: "user" | "assistant";
  content: string;
  files?: string[];
  toolActivity?: string;
  created_at?: number;
  usage?: { input: number; output: number; cache: number };
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

  // Onboarding state
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingAgentName, setOnboardingAgentName] = useState("");
  const [onboardingUserInfo, setOnboardingUserInfo] = useState("");
  const [onboardingSubmitting, setOnboardingSubmitting] = useState(false);

  // Load session from initialSessionId prop (route param)
  useEffect(() => {
    if (initialSessionId) {
      fetchSession(initialSessionId)
        .then((detail) => {
          setActiveSession(initialSessionId);
          setMessages(
            detail.messages.map((m: any) => ({
              role: m.role,
              content: m.content,
              created_at: m.created_at,
            }))
          );
          setSelectedModel(detail.model);
          setSessionUsage({ input: 0, output: 0, cache: 0 });
        })
        .catch(() => {
          setActiveSession(null);
          setMessages([]);
        });
    } else {
      setActiveSession(null);
      setMessages([]);
      setSessionUsage({ input: 0, output: 0, cache: 0 });
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
      // Navigate to the new session URL
      router.push(`/chat/${s.id}`);
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
    let currentActivity = "";
    setMessages([...newMessages, { role: "assistant", content: "", created_at: Date.now() / 1000 }]);

    try {
      for await (const chunk of streamChat(chatMessages, selectedModel, sessionId)) {
        if (chunk.error) {
          assistantContent = `Error: ${chunk.error}`;
          break;
        }
        if (chunk.tool && chunk.state === "start") {
          currentActivity = `⚡ ${chunk.tool}(${chunk.args || ""})`;
          setMessages([...newMessages, { role: "assistant", content: assistantContent, toolActivity: currentActivity, created_at: Date.now() / 1000 }]);
        }
        if (chunk.tool && chunk.state !== "start") {
          currentActivity = "";
        }
        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages([...newMessages, { role: "assistant", content: assistantContent, toolActivity: currentActivity, created_at: Date.now() / 1000 }]);
        }
        if (chunk.done && chunk.usage) {
          const u = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
          setSessionUsage(prev => ({ input: prev.input + u.input, output: prev.output + u.output, cache: prev.cache + u.cache }));
          setMessages(prev => {
            const msgs = [...prev];
            const last = msgs[msgs.length - 1];
            if (last && last.role === "assistant") msgs[msgs.length - 1] = { ...last, usage: u };
            return msgs;
          });
          currentActivity = "";
        }
      }
    } catch (err) {
      assistantContent = `Error: ${err instanceof Error ? err.message : "Unknown error"}`;
    }

    setMessages([...newMessages, { role: "assistant", content: assistantContent, created_at: Date.now() / 1000 }]);
    setStreaming(false);
    fetchSessions().then(setSessions).catch(() => {});
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
          {/* Model Select */}
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="text-sm bg-transparent border border-border rounded-md px-2 py-1 outline-none"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.description || m.id}</option>
            ))}
          </select>

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
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <p>Start a conversation</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
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
                  {msg.toolActivity && (
                    <div className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
                      <span className="animate-pulse">⚡</span>
                      <span>{msg.toolActivity}</span>
                    </div>
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
                      <span className="text-[10px] text-muted-foreground/30">
                        ↑{msg.usage.input} ↓{msg.usage.output}{msg.usage.cache > 0 ? ` ⚡${msg.usage.cache}` : ""}
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

      {/* Input area */}
      <div className="border-t border-border p-4">
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
          <div className="flex gap-2 mb-2 flex-wrap">
            {pendingFiles.map((f, i) => (
              <span key={i} className="text-xs bg-muted px-2 py-1 rounded-md flex items-center gap-1">
                📎 {f.name}
                <button onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-foreground">×</button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            onClick={() => fileRef.current?.click()}
            disabled={streaming}
          >
            <Paperclip className="h-4 w-4" />
          </Button>
          <input ref={fileRef} type="file" className="hidden" multiple onChange={handleFileUpload} />
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
            className="flex-1 resize-none bg-muted border border-border rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-ring min-h-[44px] max-h-[200px]"
            rows={1}
            disabled={streaming}
          />
          <Button
            size="icon"
            className="shrink-0"
            onClick={handleSend}
            disabled={streaming || (!input.trim() && pendingFiles.length === 0)}
          >
            {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}
