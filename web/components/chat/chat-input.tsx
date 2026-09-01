"use client";

import { useState, useRef, RefObject, useCallback, useEffect } from "react";
import { Send, Paperclip, X, Reply, Square, ImageIcon, Maximize2, Minimize2, Shield, ShieldCheck } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ethan/shared/ui/select";
import { ModelSelect } from "@ethan/shared/ui/model-select";
import { uploadFile, type ModeEntry } from "@/lib/api";
import type { Quote, PendingFile } from "@ethan/shared/chat/types";
import { MdEditor } from "@/components/md-editor";
import { QueuedMessages } from "./queued-messages";
import type { QueuedMessage } from "./use-input-store";

// 哨兵值：旧会话存的纯 model id 命中多个 provider 时的「待重选」态，不可作为真实选择提交
const NEED_CHOICE = "__need_model_choice__";

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
  stopping?: boolean;
  models: { id: string; description: string; provider?: string; alias?: string[] }[];
  selectedModel: string;
  pendingFiles: PendingFile[];
  quote: Quote | null;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onModelChange: (model: string) => void;
  onSend: (text: string) => void;
  onStop?: () => void;
  onFilesChange: (files: PendingFile[]) => void;
  onQuoteCancel: () => void;
  modes?: ModeEntry[];
  mode?: string;
  onModeChange?: (mode: string) => void;
  autoConsent?: boolean;
  onAutoConsentChange?: (v: boolean) => void;
  // 排队消息相关
  queue?: QueuedMessage[];
  onQueueSend?: (text: string, images?: PendingFile[]) => void;
  onQueueRemove?: (id: string) => void;
  onQueueEdit?: (id: string, text: string) => void;
  onQueueReorder?: (from: number, to: number) => void;
  // 外部驱动 draft
  draft?: string;
  onDraftChange?: (text: string) => void;
}

export function ChatInput({
  streaming,
  stopping = false,
  models,
  selectedModel,
  pendingFiles,
  quote,
  inputRef,
  onModelChange,
  onSend,
  onStop,
  onFilesChange,
  onQuoteCancel,
  modes = [],
  mode = "",
  onModeChange,
  autoConsent = false,
  onAutoConsentChange,
  queue = [],
  onQueueSend,
  onQueueRemove,
  onQueueEdit,
  onQueueReorder,
  draft: externalDraft,
  onDraftChange,
}: ChatInputProps) {
  const [internalInput, setInternalInput] = useState("");
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // 外部驱动 draft 时使用外部值，否则使用内部 state
  const isControlled = externalDraft !== undefined;
  const input = isControlled ? externalDraft : internalInput;
  const setInput = useCallback((text: string) => {
    if (isControlled && onDraftChange) {
      onDraftChange(text);
    } else {
      setInternalInput(text);
    }
  }, [isControlled, onDraftChange]);

  // 当外部 draft 变化时同步内部（用于会话切换恢复）
  useEffect(() => {
    if (isControlled && externalDraft !== internalInput) {
      setInternalInput(externalDraft);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalDraft]);

  // 读图片文件为 base64 dataUrl，返回 PendingFile
  const readImageFile = (file: File): Promise<PendingFile> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve({
          name: file.name,
          path: "",  // 图片不走 server upload
          isImage: true,
          dataUrl: reader.result as string,
        });
      };
      reader.onerror = () => reject(new Error(`Failed to read file: ${file.name}`));
      reader.readAsDataURL(file);
    });

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const added: PendingFile[] = [];
    for (const file of Array.from(files)) {
      if (file.type.startsWith("image/")) {
        added.push(await readImageFile(file));
      } else {
        const result = await uploadFile(file);
        added.push({ name: result.filename, path: result.path });
      }
    }
    onFilesChange([...pendingFiles, ...added]);
    e.target.value = "";
  };

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter((item) => item.type.startsWith("image/"));
    if (!imageItems.length) return;
    e.preventDefault();
    const added: PendingFile[] = [];
    for (const item of imageItems) {
      const file = item.getAsFile();
      if (file) added.push(await readImageFile(file));
    }
    if (added.length) onFilesChange([...pendingFiles, ...added]);
  }, [pendingFiles, onFilesChange]);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    const added: PendingFile[] = [];
    for (const file of files) {
      if (file.type.startsWith("image/")) {
        added.push(await readImageFile(file));
      } else {
        const result = await uploadFile(file);
        added.push({ name: result.filename, path: result.path });
      }
    }
    onFilesChange([...pendingFiles, ...added]);
  }, [pendingFiles, onFilesChange]);

  const handleSend = () => {
    if (ambiguousLegacy) return; // 同名模型歧义未解决，先让用户选 provider
    if (!input.trim() && pendingFiles.length === 0) return;
    // streaming 中发送 → 进入排队队列（连同附图一起入队）
    if (streaming && onQueueSend) {
      onQueueSend(input, pendingFiles.length > 0 ? pendingFiles : undefined);
      setInput("");
      if (pendingFiles.length > 0) onFilesChange([]);
      return;
    }
    if (streaming) return;
    onSend(input);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // 输入法组合中（如中文拼音、英文候选）按 Enter 只确认候选词，不发送。
    // e.nativeEvent.isComposing 在 IME 组合期间为 true；组合结束后 Enter 才真正发送。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const removeFile = (index: number) => {
    onFilesChange(pendingFiles.filter((_, i) => i !== index));
  };

  const images = pendingFiles.filter((f) => f.isImage);
  const nonImages = pendingFiles.filter((f) => !f.isImage);

  // 选择值统一为唯一的 provider/id。
  // 旧会话存的纯 id：只命中一个模型 → 自动升级为该模型的 provider/id；
  // 命中多个同名模型 → 不能猜，列出候选让用户显式选择（选择前禁用发送），
  // 避免静默切到另一个 provider（隐私/计费都可能出错）。
  const fullIdOf = (m: { id: string; provider?: string }) => (m.provider ? `${m.provider}/${m.id}` : m.id);
  const effectiveModelValue = (() => {
    if (models.some((m) => fullIdOf(m) === selectedModel)) return selectedModel;
    const hits = models.filter((m) => m.id === selectedModel);
    if (hits.length === 1) return fullIdOf(hits[0]); // 唯一匹配，安全升级
    return hits.length > 1 ? NEED_CHOICE : selectedModel; // 重名：不猜，交给用户选
  })();
  const ambiguousLegacy =
    !models.some((m) => fullIdOf(m) === selectedModel) &&
    models.filter((m) => m.id === selectedModel).length > 1;

  return (
    <div className="px-4 pb-4 pt-1">
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

        {/* 旧会话存的纯 id 命中多个同名模型：列出候选让用户选择，选择前不能发送 */}
        {ambiguousLegacy && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-xs text-amber-700 dark:text-amber-300 flex-wrap">
            <span className="shrink-0">模型「{selectedModel}」在多个 provider 下重名，请选择要使用的：</span>
            {models
              .filter((m) => m.id === selectedModel)
              .map((m) => (
                <button
                  key={fullIdOf(m)}
                  onClick={() => onModelChange(fullIdOf(m))}
                  className="px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 hover:bg-amber-200 dark:hover:bg-amber-900 font-mono"
                >
                  {fullIdOf(m)}
                </button>
              ))}
          </div>
        )}

        {/* 排队消息列表 — 展示在输入框上方，视觉上与输入框连为一体 */}
        {queue.length > 0 && onQueueRemove && onQueueEdit && onQueueReorder && (
          <QueuedMessages
            items={queue}
            onRemove={onQueueRemove}
            onEdit={onQueueEdit}
            onReorder={onQueueReorder}
          />
        )}

        {/* 图片缩略图预览 */}
        {images.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {images.map((f, i) => {
              const realIndex = pendingFiles.indexOf(f);
              return (
                <div key={i} className="relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={f.dataUrl}
                    alt={f.name}
                    className="h-16 w-16 object-cover rounded-md border border-border"
                  />
                  <button
                    onClick={() => removeFile(realIndex)}
                    className="absolute -top-1.5 -right-1.5 h-4 w-4 rounded-full bg-background border border-border flex items-center justify-center text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* 非图片附件 */}
        {nonImages.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {nonImages.map((f, i) => {
              const realIndex = pendingFiles.indexOf(f);
              return (
                <span key={i} className="text-xs bg-muted px-2 py-1 rounded-md flex items-center gap-1">
                  📎 {f.name}
                  <button onClick={() => removeFile(realIndex)} className="text-muted-foreground hover:text-foreground">×</button>
                </span>
              );
            })}
          </div>
        )}

        <div
          className={`rounded-2xl border bg-muted/40 focus-within:border-ring/50 focus-within:bg-background transition-colors ${dragging ? "border-ring/70 bg-primary/5" : "border-border"}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          {dragging && (
            <div className="flex items-center justify-center gap-2 py-4 text-sm text-muted-foreground pointer-events-none">
              <ImageIcon className="h-4 w-4" />
              松开以添加图片
            </div>
          )}
          {!dragging && !expanded && (
            <div className="relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder="输入消息… (Enter 发送，Shift+Enter 换行，可直接粘贴图片)"
                className="w-full resize-none bg-transparent px-4 pt-3 pb-2 text-sm outline-none min-h-[52px] max-h-[200px] leading-relaxed"
                rows={1}
              />
              <button
                onClick={() => setExpanded(true)}
                className="absolute top-2 right-2 h-6 w-6 flex items-center justify-center rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
                title="展开为 Markdown 编辑器"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {!dragging && expanded && (
            <div className="relative">
              <button
                onClick={() => setExpanded(false)}
                className="absolute top-2 right-2 z-10 h-6 w-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title="收起编辑器"
              >
                <Minimize2 className="h-3.5 w-3.5" />
              </button>
              <div className="[&>div]:min-h-[280px] [&>div]:border-0 [&>div]:rounded-none">
                <MdEditor
                  value={input}
                  onChange={setInput}
                  placeholder="输入 Markdown 内容… (支持预览和分栏模式)"
                  defaultMode="edit"
                />
              </div>
            </div>
          )}
          <div className="flex items-center gap-1 px-3 pb-2.5">
            <button
              onClick={() => fileRef.current?.click()}
              disabled={streaming}
              className="h-7 w-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
              title="附件 / 图片"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <input ref={fileRef} type="file" className="hidden" multiple accept="*/*" onChange={handleFileUpload} />
            <ModelSelect
              models={models}
              value={effectiveModelValue}
              onValueChange={(v) => v !== NEED_CHOICE && onModelChange(v)}
              disabled={streaming}
              valueMode="fullId"
              size="sm"
              placeholder="模型"
              unmatchedLabel={(v) =>
                v === NEED_CHOICE ? "有多个 provider 提供该模型，请指定一个" : v
              }
              extraItems={
                ambiguousLegacy ? (
                  <SelectItem value={NEED_CHOICE} disabled className="text-xs text-amber-600 dark:text-amber-500">
                    有多个 provider 提供该模型，请指定一个
                  </SelectItem>
                ) : undefined
              }
              triggerClassName="h-7 px-2.5 text-xs bg-transparent border-0 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg shadow-none focus:ring-0 focus:ring-offset-0 gap-1 w-auto max-w-[200px]"
              contentClassName="min-w-[280px]"
            />
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
            {/* 超级权限开关：开启后普通工具授权自动批准；高危命令（rm -rf 等）仍弹窗确认 */}
            {/* TODO(开启态视觉不醒目 + 无二次确认): 当前只是 amber 浅色 pill + "已授权" 字样，
                长时间运行时用户可能忘了自己开着自动批准，导致普通 shell/写文件操作一路放行。
                建议：开启时加一圈脉动环、按钮文字改"⚠ 自动授权中"、hover tooltip 显示风险提示；
                或首次开启时弹一个二次确认（"确定开启自动批准？普通写文件、shell 执行将不弹窗"）。 */}
            {onAutoConsentChange && (
              <button
                onClick={() => onAutoConsentChange(!autoConsent)}
                className={`h-7 flex items-center gap-1 px-1.5 rounded-lg transition-colors text-xs ${autoConsent ? "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400" : "text-muted-foreground hover:text-foreground hover:bg-muted"}`}
                title={autoConsent ? "超级权限已开启：普通操作自动批准；高危命令仍会弹窗确认" : "超级权限：开启后自动批准普通工具授权，高危命令仍需确认"}
              >
                {autoConsent ? <ShieldCheck className="h-4 w-4" /> : <Shield className="h-4 w-4" />}
                <span>{autoConsent ? "已授权" : "授权"}</span>
              </button>
            )}
            <div className="flex-1" />
            {streaming && (
              <button
                onClick={() => { if (!stopping) onStop?.(); }}
                disabled={stopping}
                className={`h-7 w-7 flex items-center justify-center rounded-lg transition-opacity mr-1 ${stopping ? "bg-muted opacity-60 cursor-not-allowed" : "bg-muted text-foreground hover:opacity-80"}`}
                title={stopping ? "正在停止..." : "停止生成"}
              >
                {stopping
                  ? <span className="h-3 w-3 rounded-full border-2 border-foreground/50 border-t-transparent animate-spin" />
                  : <Square className="h-3 w-3 fill-current" />
                }
              </button>
            )}
            <button
              onClick={handleSend}
              disabled={ambiguousLegacy || (!input.trim() && pendingFiles.length === 0)}
              className="h-7 w-7 flex items-center justify-center rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
              title={ambiguousLegacy ? "请先选择要使用的 provider" : streaming ? "排队发送" : "发送"}
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
