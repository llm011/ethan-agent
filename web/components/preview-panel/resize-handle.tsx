"use client";

import { useCallback, useEffect, useRef } from "react";

interface ResizeHandleProps {
  onResize: (deltaX: number) => void;
  onResizeEnd?: () => void;
}

export function ResizeHandle({ onResize, onResizeEnd }: ResizeHandleProps) {
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

  return (
    <div
      onMouseDown={handleMouseDown}
      className="w-1.5 shrink-0 cursor-col-resize bg-border hover:bg-primary/30 active:bg-primary/40 transition-colors"
    />
  );
}
