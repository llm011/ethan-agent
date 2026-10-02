"use client";

import { useCallback, useEffect, useRef } from "react";

interface ResizeHandleProps {
  onResize: (deltaX: number) => void;
  onResizeEnd?: () => void;
  /**
   * flow：自己画一条分隔条并占据布局宽度（两侧本来没有 border 时用）。
   * overlay：完全不占位，覆盖在已有的 border 上（该 border 负责视觉）。
   *   侧边栏要用 overlay —— 折叠箭头是按 border 位置定位的，插入占位元素会把它挤偏。
   */
  variant?: "flow" | "overlay";
}

export function ResizeHandle({ onResize, onResizeEnd, variant = "flow" }: ResizeHandleProps) {
  const dragging = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Clean up listeners if component unmounts mid-drag
  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    const startX = e.clientX;

    const handleMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      onResize(ev.clientX - startX);
    };

    const handleMouseUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      cleanupRef.current = null;
      onResizeEnd?.();
    };

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    cleanupRef.current = handleMouseUp;
  }, [onResize, onResizeEnd]);

  const baseProps = {
    onMouseDown: handleMouseDown,
    role: "separator" as const,
    "aria-orientation": "vertical" as const,
    "aria-label": "拖拽调整宽度",
  };

  if (variant === "overlay") {
    // 视觉仍是那 1px 的 border，这里只做命中区 + hover 高亮；
    // 命中区向两侧各扩 4px —— 1px 的线在触控板上几乎点不中。
    return (
      <div
        {...baseProps}
        className="group absolute inset-y-0 left-0 z-20 w-[9px] -translate-x-1/2 cursor-col-resize"
      >
        <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent transition-colors group-hover:bg-primary group-active:bg-primary" />
      </div>
    );
  }

  return (
    <div
      {...baseProps}
      className="group relative w-1.5 shrink-0 cursor-col-resize bg-border hover:bg-primary/30 active:bg-primary/40 transition-colors"
    >
      {/* 命中区比视觉宽度宽：1.5px 的线在触控板上很难精准命中 */}
      <span className="absolute -left-[3px] -right-[3px] inset-y-0" />
    </div>
  );
}
