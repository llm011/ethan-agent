/**
 * 可拖拽分栏的宽度状态（百分比），带 localStorage 持久化。
 *
 * 抽出来是因为同一套逻辑要在 web 与 desktop 两端、多个页面（chat 的预览面板、
 * 文档页的列表/预览）复用 —— 分散复制容易各处行为漂移（拖动基准、clamp 范围、
 * 持久化键各写各的）。
 *
 * 用法：容器 ref 挂到包含**两侧**分栏的父元素上（宽度即拖动换算的分母），
 * 面板宽度用 `size`（百分比），中间放 ResizeHandle 接 `handleResize/End`。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface PaneResizeOptions {
  /** localStorage 键。不同页面用不同键，避免互相覆盖。 */
  storageKey: string;
  /** 默认宽度百分比。 */
  defaultSize?: number;
  /** 下限百分比，默认 20。 */
  min?: number;
  /** 上限百分比，默认 70。 */
  max?: number;
}

export interface PaneResize {
  /** 面板宽度百分比。 */
  size: number;
  /** 挂到「包含两侧分栏」的父容器上。 */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** 传给 ResizeHandle 的 onResize。 */
  handleResize: (deltaX: number) => void;
  /** 传给 ResizeHandle 的 onResizeEnd（落盘）。 */
  handleResizeEnd: () => void;
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

function readStored(key: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeStored(key: string, value: number) {
  try {
    localStorage.setItem(key, String(Math.round(value)));
  } catch {}
}

export function usePaneResize({
  storageKey,
  defaultSize = 40,
  min = 20,
  max = 70,
}: PaneResizeOptions): PaneResize {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(defaultSize);
  // 拖动过程中的累加基准。必须与面板**当前**宽度一致，否则第一次拖动会跳变。
  // 用 ref 而不是 state：mousemove 每帧触发，走 state 会连带重渲染整个页面。
  const sizeRef = useRef(defaultSize);

  // 延后到挂载后再读 localStorage：初始渲染两端都取 defaultSize，避免 SSR 与
  // 客户端首帧不一致导致 hydration mismatch（读 localStorage 只能在浏览器里做）。
  useEffect(() => {
    const stored = readStored(storageKey);
    const next = stored == null ? defaultSize : clamp(stored, min, max);
    sizeRef.current = next;
    setSize(next);
  }, [storageKey, defaultSize, min, max]);

  const handleResize = useCallback((deltaX: number) => {
    const el = containerRef.current;
    if (!el) return;
    const totalWidth = el.offsetWidth;
    if (!totalWidth) return;   // 父容器尚未布局完成（宽度 0）时不做换算，否则会除出 Infinity
    // 分隔线往左拖（deltaX < 0）→ 右侧面板变宽，故取负号
    const next = clamp(sizeRef.current + (-deltaX / totalWidth) * 100, min, max);
    setSize(next);
  }, [min, max]);

  const handleResizeEnd = useCallback(() => {
    setSize((current) => {
      sizeRef.current = current;
      writeStored(storageKey, current);
      return current;
    });
  }, [storageKey]);

  return { size, containerRef, handleResize, handleResizeEnd };
}
