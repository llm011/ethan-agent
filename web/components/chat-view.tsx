"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Send, Paperclip, Loader2, Plus, Trash2, MessageSquare, Search, Sun, Moon, Pencil, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

// 让中文字符旁的 **bold** 正确解析：在 CJK 与 ** 之间插零宽空格
const CJK = /[一-鿿㐀-䶿　-〿＀-￯⺀-⻿]/;
function fixBold(text: string): string {
  return text
    .replace(/([^\s*_`])\*\*/g, (_, c) => (CJK.test(c) ? `${c}​**` : `${c} **`))
    .replace(/\*\*([^\s*_`])/g, (_, c) => (CJK.test(c) ? `**​${c}` : `** ${c}`));
}
import {
  ChatMessage,
  SessionInfo,
  createSession,
  deleteSession,
  fetchModels,
  fetchSession,
  fetchSessions,
  renameSession,
  streamChat,
  uploadFile,
} from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  files?: string[];
  toolActivity?: string;  // tool call indicator
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

export function ChatView() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const { theme, toggle: toggleTheme } = useTheme();

  // 防抖全文搜索：空时加载全部，有内容时调后端搜索
  useEffect(() => {
    const q = sessionSearch.trim();
    const timer = setTimeout(() => {
      setSearchLoading(true);
      fetchSessions(50, q || undefined)
        .then(setSessions)
        .catch(() => {})
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [sessionSearch]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [models, setModels] = useState<{ id: string; description: string }[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [pendingFiles, setPendingFiles] = useState<{ name: string; path: string }[]>([]);
  const [usage, setUsage] = useState<{ input: number; output: number } | null>(null);

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

  const loadSession = async (id: string) => {
    const detail = await fetchSession(id);
    setActiveSession(id);
    setMessages(detail.messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.content })));
    setSelectedModel(detail.model);
  };

  const newSession = async () => {
    const s = await createSession(selectedModel);
    setActiveSession(s.id);
    setMessages([]);
    setUsage(null);
    setSessions((prev) => [{ id: s.id, title: s.title, model: s.model, created_at: Date.now() / 1000, updated_at: Date.now() / 1000 }, ...prev]);
  };

  const removeSession = async (id: string) => {
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSession === id) {
      setActiveSession(null);
      setMessages([]);
    }
  };

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
      setSessions((prev) => [{ id: s.id, title: text.slice(0, 30) || "New chat", model: s.model, created_at: Date.now() / 1000, updated_at: Date.now() / 1000 }, ...prev]);
    }

    let content = text;
    if (pendingFiles.length > 0) {
      const fileContext = pendingFiles.map((f) => `[Uploaded file: ${f.name} at ${f.path}]`).join("\n");
      content = `${fileContext}\n\n${text}`;
    }

    const userMsg: Message = { role: "user", content, files: pendingFiles.map((f) => f.name) };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setPendingFiles([]);
    setStreaming(true);

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({ role: m.role, content: m.content }));

    let assistantContent = "";
    let currentActivity = "";
    setMessages([...newMessages, { role: "assistant", content: "" }]);

    try {
      for await (const chunk of streamChat(chatMessages, selectedModel, sessionId)) {
        if (chunk.error) {
          assistantContent = `Error: ${chunk.error}`;
          break;
        }
        if (chunk.tool && chunk.state === "start") {
          currentActivity = `⚡ ${chunk.tool}(${chunk.args || ""})`;
          setMessages([...newMessages, { role: "assistant", content: assistantContent, toolActivity: currentActivity }]);
        }
        if (chunk.tool && chunk.state !== "start") {
          currentActivity = "";
        }
        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages([...newMessages, { role: "assistant", content: assistantContent, toolActivity: currentActivity }]);
        }
        if (chunk.done && chunk.usage) {
          setUsage({ input: chunk.usage.input, output: chunk.usage.output });
          currentActivity = "";
        }
      }
    } catch (err) {
      assistantContent = `Error: ${err instanceof Error ? err.message : "Unknown error"}`;
    }

    setMessages([...newMessages, { role: "assistant", content: assistantContent }]);
    setStreaming(false);
    if (!sessionSearch.trim()) fetchSessions().then(setSessions).catch(() => {});
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-64 border-r border-border flex flex-col bg-muted/30">
        <div className="p-4 flex items-center justify-between">
          <h1 className="text-lg font-semibold">Ethan</h1>
          <Button variant="ghost" size="icon" onClick={newSession} title="New chat">
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className={`absolute left-2.5 top-2.5 h-3.5 w-3.5 ${searchLoading ? "text-primary animate-pulse" : "text-muted-foreground"}`} />
            <Input
              placeholder="Search sessions..."
              value={sessionSearch}
              onChange={(e) => setSessionSearch(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>
        <Separator className="my-1 opacity-40" />
        <ScrollArea className="flex-1 p-2">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
                activeSession === s.id ? "bg-accent text-accent-foreground" : "hover:bg-muted"
              }`}
              onClick={() => editingSessionId !== s.id && loadSession(s.id)}
            >
              <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-50" />
              {editingSessionId === s.id ? (
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") commitRename(s.id); if (e.key === "Escape") cancelEdit(); }}
                  onClick={(e) => e.stopPropagation()}
                  className="flex-1 bg-transparent outline-none border-b border-primary text-sm"
                />
              ) : (
                <span className="truncate flex-1">{s.title}</span>
              )}
              {editingSessionId === s.id ? (
                <>
                  <button onClick={(e) => { e.stopPropagation(); commitRename(s.id); }} className="text-primary hover:opacity-70"><Check className="h-3 w-3" /></button>
                  <button onClick={(e) => { e.stopPropagation(); cancelEdit(); }} className="text-muted-foreground hover:opacity-70"><X className="h-3 w-3" /></button>
                </>
              ) : (
                <>
                  <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100" onClick={(e) => startEditSession(s.id, s.title, e)}>
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); removeSession(s.id); }}>
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </>
              )}
            </div>
          ))}
        </ScrollArea>
      </aside>

      {/* Main area */}
      <main className="flex-1 flex flex-col">
        {/* Header */}
        <header className="h-12 border-b border-border flex items-center px-4 gap-3">
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="text-sm bg-transparent border border-border rounded-md px-2 py-1 outline-none"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.description || m.id}</option>
            ))}
          </select>
          {/* 当前 session 标题，可点击编辑 */}
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
                  className="flex-1 min-w-0 bg-transparent outline-none border-b border-primary text-sm"
                />
                <button onClick={() => commitRename(activeSession)} className="text-primary hover:opacity-70"><Check className="h-3.5 w-3.5" /></button>
                <button onClick={cancelEdit} className="text-muted-foreground hover:opacity-70"><X className="h-3.5 w-3.5" /></button>
              </div>
            ) : (
              <button
                className="flex items-center gap-1.5 text-sm font-medium truncate max-w-[240px] hover:text-primary group"
                onClick={(e) => startEditSession(activeSession, cur.title, e)}
                title="Click to rename"
              >
                <span className="truncate">{cur.title}</span>
                <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50 shrink-0" />
              </button>
            );
          })()}
          {usage && (
            <span className="text-xs text-muted-foreground ml-auto">
              ↑{usage.input} ↓{usage.output} tokens
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={usage ? "ml-2" : "ml-auto"}
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
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
      </main>
    </div>
  );
}
