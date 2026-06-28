"use client";

import { useState, useRef, RefObject } from "react";
import { Send, Paperclip, Loader2, X, Reply } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { uploadFile, type ModeEntry } from "@/lib/api";
import type { Quote } from "./types";

interface PendingFile {
  name: string;
  path: string;
}

// mode.accent → 完整 Tailwind 类（必须静态写全，Tailwind 不识别动态拼接的类名）。
// 新增带新配色的模式时在此补一条；未知 accent 回退 neutral。
const ACCENT_STYLES: Record<string, { on: string }> = {
  neutral: {
    on: "bg-neutral-100 border-neutral-300 text-neutral-700 dark:bg-neutral-800 dark:border-neutral-600 dark:text-neutral-200",
  },
  pink: {
    on: "bg-pink-50 border-pink-300 text-pink-700 dark:bg-pink-950/40 dark:border-pink-700 dark:text-pink-300",
  },
  blue: {
    on: "bg-blue-50 border-blue-300 text-blue-700 dark:bg-blue-950/40 dark:border-blue-700 dark:text-blue-300",
  },
};
const OFF_STYLE =
  "bg-transparent border-transparent text-muted-foreground hover:text-foreground hover:bg-muted";

interface ChatInputProps {
  streaming: boolean;
  models: { id: string; description: string }[];
  selectedModel: string;
  pendingFiles: PendingFile[];
  quote: Quote | null;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onModelChange: (model: string) => void;
  onSend: (text: string) => void;
  onFilesChange: (files: PendingFile[]) => void;
  onQuoteCancel: () => void;
  modes?: ModeEntry[];
  mode?: string;
  onModeChange?: (mode: string) => void;
}

export function ChatInput({
  streaming,
  models,
  selectedModel,
  pendingFiles,
  quote,
  inputRef,
  onModelChange,
  onSend,
  onFilesChange,
  onQuoteCancel,
  modes = [],
  mode = "",
  onModeChange,
}: ChatInputProps) {
  const [input, setInput] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const uploaded: PendingFile[] = [];
    for (const file of Array.from(files)) {
      const result = await uploadFile(file);
      uploaded.push({ name: result.filename, path: result.path });
    }
    onFilesChange([...pendingFiles, ...uploaded]);
    e.target.value = "";
  };

  const handleSend = () => {
    if (!input.trim() && pendingFiles.length === 0) return;
    if (streaming) return;
    onSend(input);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const removeFile = (index: number) => {
    onFilesChange(pendingFiles.filter((_, i) => i !== index));
  };

  return (
    <div className="p-4">
      <div className="max-w-3xl mx-auto">
        {quote && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-md bg-muted/60 border border-border/60 text-xs">
            <Reply className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="text-muted-foreground shrink-0">
              {quote.role === "user" ? "我" : "Ethan"}:
            </span>
            <span className="truncate text-muted-foreground/80 flex-1">
              {quote.content.replace(/\n/g, " ")}
            </span>
            <button
              onClick={onQuoteCancel}
              className="text-muted-foreground hover:text-foreground shrink-0"
              title="取消引用"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        {pendingFiles.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {pendingFiles.map((f, i) => (
              <span key={i} className="text-xs bg-muted px-2 py-1 rounded-md flex items-center gap-1">
                📎 {f.name}
                <button onClick={() => removeFile(i)} className="text-muted-foreground hover:text-foreground">×</button>
              </span>
            ))}
          </div>
        )}
        <div className="rounded-2xl border border-border bg-muted/40 focus-within:border-ring/50 focus-within:bg-background transition-colors">
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
          <div className="flex items-center gap-1 px-3 pb-2.5">
            <button
              onClick={() => fileRef.current?.click()}
              disabled={streaming}
              className="h-7 w-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
              title="附件"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <input ref={fileRef} type="file" className="hidden" multiple onChange={handleFileUpload} />
            <Select value={selectedModel} onValueChange={(v) => v && onModelChange(v)} disabled={streaming}>
              <SelectTrigger className="h-7 px-2.5 text-xs bg-transparent border-0 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg shadow-none focus:ring-0 focus:ring-offset-0 gap-1 w-auto max-w-[160px]">
                <SelectValue placeholder="模型" />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m.id} value={m.id} className="text-xs">{m.description || m.id}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* 对话模式下拉：由 /modes 表驱动（含默认）；选中即切换，已有会话立即落库 */}
            {modes.length > 0 && (
              <Select
                value={mode || "__default__"}
                onValueChange={(v) => { if (v) onModeChange?.(v === "__default__" ? "" : v); }}
                disabled={streaming}
              >
                <SelectTrigger
                  className={
                    "h-7 px-2.5 text-xs rounded-lg border shadow-none focus:ring-0 focus:ring-offset-0 gap-1 w-auto max-w-[160px] " +
                    (mode ? (ACCENT_STYLES[modes.find((m) => m.key === mode)?.accent ?? "neutral"] ?? ACCENT_STYLES.neutral).on : OFF_STYLE)
                  }
                >
                  <SelectValue placeholder="模式">
                    {(value: string) => {
                      const cur = modes.find((m) => (m.key || "__default__") === value);
                      if (!cur) return "模式";
                      return (
                        <span className="inline-flex items-center gap-1">
                          {cur.icon && <span>{cur.icon}</span>}
                          <span className="truncate">{cur.label}</span>
                        </span>
                      );
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {modes.map((m) => (
                    <SelectItem key={m.key || "__default__"} value={m.key || "__default__"} className="text-xs">
                      <span className="inline-flex items-center gap-1">
                        {m.icon && <span>{m.icon}</span>}
                        <span>{m.label}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <div className="flex-1" />
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
  );
}
