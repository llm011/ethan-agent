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
    <div className="mb-1.5">
      <div className="flex items-center gap-1.5 mb-1 px-1">
        <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wider">排队</span>
        <span className="text-[10px] tabular-nums bg-muted/60 text-muted-foreground/70 rounded-full px-1.5 py-px">
          {items.length}
        </span>
      </div>
      <div className="space-y-0.5">
        {items.map((item, index) => {
          const isDragging = dragIndex === index;
          const isDragOver = dragOverIndex === index && dragIndex !== index;

          return (
            <div
              key={item.id}
              className={`group/q flex items-center gap-1.5 rounded-lg px-2 py-1.5 transition-all ${
                isDragging ? "opacity-30 scale-95" : ""
              } ${isDragOver ? "bg-primary/8 ring-1 ring-primary/20" : "bg-muted/40 hover:bg-muted/70"}`}
              draggable={editingId !== item.id}
              onDragStart={(e) => handleDragStart(e, index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDrop={(e) => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
            >
              {/* 拖拽手柄 */}
              <div className="cursor-grab active:cursor-grabbing text-muted-foreground/30 hover:text-muted-foreground/60 shrink-0 transition-colors">
                <GripVertical className="h-3 w-3" />
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
                    className="flex-1 text-xs bg-background border border-border rounded-md px-2 py-1 outline-none focus:ring-1 focus:ring-ring"
                    autoFocus
                  />
                  <button
                    onClick={confirmEdit}
                    className="h-5 w-5 flex items-center justify-center rounded text-green-600 hover:bg-green-50 dark:hover:bg-green-950/50"
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
                  <span className="flex-1 text-[13px] text-foreground/80 truncate select-none">
                    {item.text}
                  </span>
                  {/* 操作按钮 */}
                  <div className="flex items-center gap-0.5 opacity-0 group-hover/q:opacity-100 transition-opacity shrink-0">
                    <button
                      onClick={() => startEdit(item)}
                      className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground/60 hover:text-foreground hover:bg-background/80"
                      title="编辑"
                    >
                      <Pencil className="h-2.5 w-2.5" />
                    </button>
                    <button
                      onClick={() => onRemove(item.id)}
                      className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground/60 hover:text-red-500 hover:bg-background/80"
                      title="删除"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
