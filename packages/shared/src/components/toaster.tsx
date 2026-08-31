"use client";

import { useEffect, useState } from "react";

/**
 * 轻量 toast 通知系统（Web / Desktop 共用，零依赖）。
 *
 * 用法：
 *   在根布局挂载 <Toaster /> 一次；
 *   任意组件里 import { toast } from "@ethan/shared/components/toaster"；
 *   toast.success("已触发"); toast.error("触发失败"); toast.info("提示");
 *
 * 设计要点：
 *   - 用模块级订阅，避免 context 依赖，组件里可直接调用 toast.xxx。
 *   - 自动 3.5s 消失，error 类 5s；支持手动关闭。
 *   - 同一时刻最多叠 3 条，更早的自动移除，防止刷屏。
 */

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

type Listener = (toasts: ToastItem[]) => void;

let toasts: ToastItem[] = [];
const listeners = new Set<Listener>();
let nextId = 1;
const MAX_VISIBLE = 3;

function emit() {
  for (const l of Array.from(listeners)) l(toasts);
}

function push(kind: ToastKind, message: string) {
  const item: ToastItem = { id: nextId++, kind, message };
  toasts = [...toasts, item].slice(-MAX_VISIBLE);
  emit();
  const duration = kind === "error" ? 5000 : 3500;
  setTimeout(() => dismiss(item.id), duration);
  return item.id;
}

function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export const toast = {
  success: (msg: string) => push("success", msg),
  error: (msg: string) => push("error", msg),
  info: (msg: string) => push("info", msg),
  dismiss,
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const l: Listener = (t) => setItems(t);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);

  return (
    <div
      role="status"
      aria-live="polite"
      className="toaster-root"
      style={{
        position: "fixed",
        top: "16px",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 10000,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "8px",
        pointerEvents: "none",
      }}
    >
      {items.map((t) => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          className="toaster-item"
          style={{
            pointerEvents: "auto",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "10px 16px",
            borderRadius: "8px",
            fontSize: "13px",
            lineHeight: "1.4",
            boxShadow: "0 4px 16px rgba(0,0,0,0.14)",
            background: t.kind === "error" ? "#dc2626" : t.kind === "success" ? "#059669" : "#0ea5e9",
            color: "#fff",
            maxWidth: "min(420px, 90vw)",
            animation: "wb-toast-in .18s ease-out",
          }}
        >
          <span style={{ flexShrink: 0 }}>
            {t.kind === "success" ? "✓" : t.kind === "error" ? "✕" : "ℹ"}
          </span>
          <span style={{ overflowWrap: "anywhere" }}>{t.message}</span>
        </div>
      ))}
      <style>{`@keyframes wb-toast-in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}`}</style>
    </div>
  );
}
