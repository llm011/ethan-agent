"use client";

import { useState, useRef, RefObject } from "react";
import { Send, Paperclip, Loader2 } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { uploadFile } from "@/lib/api";

interface PendingFile {
  name: string;
  path: string;
}

interface ChatInputProps {
  streaming: boolean;
  models: { id: string; description: string }[];
  selectedModel: string;
  pendingFiles: PendingFile[];
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onModelChange: (model: string) => void;
  onSend: (text: string) => void;
  onFilesChange: (files: PendingFile[]) => void;
}

export function ChatInput({
  streaming,
  models,
  selectedModel,
  pendingFiles,
  inputRef,
  onModelChange,
  onSend,
  onFilesChange,
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
    <div className="border-t border-border p-4">
      <div className="max-w-3xl mx-auto">
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
