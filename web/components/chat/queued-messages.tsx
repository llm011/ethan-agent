"use client";

/**
 * QueuedMessages — 排队消息列表，展示在输入框正上方。
 * 支持拖拽排序（三横线拖拽手柄）、编辑、删除。
 */

import { useState, useCallback } from "react";
import { GripVertical, Pencil, X, Check } from "lucide-react";
import type { QueuedMessage } from "./use-input-store";

interface QueuedMessagesProps {
  items: QueuedMessage[];
  onRemove: (id: string) => void;
  onEdit: (id: string, text: string) => void;
  onReorder: (fromIndex: number, toIndex: number) => void;
}

export function QueuedMessages({ items, onRemove, onEdit, onReorder }: QueuedMessagesProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  const startEdit = (item: QueuedMessage) => {
    setEditingId(item.id);
    setEditText(item.text);
  };

  const confirmEdit = () => {
    if (editingId && editText.trim()) {
      onEdit(editingId, editText.trim());
    }
    setEditingId(null);
    setEditText("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText("");
  };

  const handleDragStart = useCallback((e: React.DragEvent, index: number) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(index);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, toIndex: number) => {
    e.preventDefault();
    if (dragIndex !== null && dragIndex !== toIndex) {
      onReorder(dragIndex, toIndex);
    }
    setDragIndex(null);
    setDragOverIndex(null);
  }, [dragIndex, onReorder]);

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
    setDragOverIndex(null);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="-mb-[1px] relative z-10">
      <div className="rounded-t-xl border border-b-0 border-border bg-muted/20 overflow-hidden">
        <div className="px-3 py-1.5 text-[11px] text-muted-foreground/70 border-b border-border/40 flex items-center gap-1">
          <span>排队中</span>
          <span className="text-muted-foreground/50">&middot;</span>
          <span>{items.length} 条消息等待发送</span>
        </div>
        <div className="divide-y divide-border/40">
          {items.map((item, index) => {
            const isDragging = dragIndex === index;
            const isDragOver = dragOverIndex === index && dragIndex !== index;

            return (
              <div
                key={item.id}
                className={`group flex items-center gap-2 px-2 py-1.5 transition-colors ${
                  isDragging ? "opacity-40" : ""
                } ${isDragOver ? "bg-primary/5" : "hover:bg-muted/50"}`}
                draggable={editingId !== item.id}
                onDragStart={(e) => handleDragStart(e, index)}
                onDragOver={(e) => handleDragOver(e, index)}
                onDrop={(e) => handleDrop(e, index)}
                onDragEnd={handleDragEnd}
              >
                {/* 拖拽手柄 */}
                <div className="cursor-grab active:cursor-grabbing text-muted-foreground/40 hover:text-muted-foreground shrink-0">
                  <GripVertical className="h-3.5 w-3.5" />
                </div>

                {/* 内容 */}
                {editingId === item.id ? (
                  <div className="flex-1 flex items-center gap-1.5">
                    <input
                      type="text"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmEdit();
                        if (e.key === "Escape") cancelEdit();
                      }}
                      className="flex-1 text-xs bg-background border border-border rounded px-2 py-1 outline-none focus:border-ring"
                      autoFocus
                    />
                    <button
                      onClick={confirmEdit}
                      className="h-5 w-5 flex items-center justify-center rounded text-green-600 hover:bg-green-100 dark:hover:bg-green-950"
                      title="确认"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:bg-muted"
                      title="取消"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="flex-1 text-xs text-foreground/90 truncate select-none">
                      {item.text}
                    </span>
                    {/* 操作按钮 */}
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button
                        onClick={() => startEdit(item)}
                        className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted"
                        title="编辑"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => onRemove(item.id)}
                        className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                        title="删除"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
