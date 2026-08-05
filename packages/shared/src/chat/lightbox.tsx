
import { useState, useEffect, useCallback, useRef } from "react";
import { ChevronLeft, ChevronRight, X, ZoomIn, ZoomOut } from "lucide-react";
import { Dialog, DialogContent } from "../ui/dialog";

export interface LightboxImage {
  url: string;
  title?: string;
  source?: string;
}

interface LightboxProps {
  images: LightboxImage[];
  index: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onIndexChange?: (index: number) => void;
}

const ZOOM_MIN = 0.5;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.3;

export function Lightbox({ images, index, open, onOpenChange, onIndexChange }: LightboxProps) {
  const total = images.length;
  const current = total > 0 ? images[Math.min(index, total - 1)] : null;
  const [zoom, setZoom] = useState(1);
  const [hint, setHint] = useState("");
  const hintTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (open) setZoom(1);
  }, [open, index]);

  const showHint = useCallback((text: string) => {
    setHint(text);
    if (hintTimer.current) clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => setHint(""), 1500);
  }, []);

  const goPrev = useCallback(() => {
    if (total <= 1) return;
    const next = (index - 1 + total) % total;
    if (next === total - 1) showHint("已是第一张，从末尾继续");
    onIndexChange?.(next);
  }, [index, total, onIndexChange, showHint]);

  const goNext = useCallback(() => {
    if (total <= 1) return;
    const next = (index + 1) % total;
    if (next === 0) showHint("已是最后一张，从头开始");
    onIndexChange?.(next);
  }, [index, total, onIndexChange, showHint]);

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(z + ZOOM_STEP, ZOOM_MAX));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(z - ZOOM_STEP, ZOOM_MIN));
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onOpenChange(false); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); goPrev(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); goNext(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); zoomIn(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); zoomOut(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, goPrev, goNext, zoomIn, zoomOut, onOpenChange]);

  if (!current) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-w-none w-screen h-screen p-0 bg-black/95 rounded-none border-none ring-0"
        onClick={(e) => {
          if (e.target === e.currentTarget) onOpenChange(false);
        }}
      >
        {/* 右上角关闭按钮 */}
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="absolute top-3 right-3 z-10 p-1.5 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
          aria-label="关闭"
        >
          <X className="h-5 w-5" />
        </button>

        {/* 右上角图片计数器 */}
        {total > 1 && (
          <div className="absolute top-3 right-14 z-10 px-2.5 py-1 rounded-full bg-black/50 text-white text-xs tabular-nums">
            {index + 1} / {total}
          </div>
        )}

        {/* 缩放按钮 */}
        <div className="absolute top-3 left-3 z-10 flex gap-1.5">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); zoomOut(); }}
            className="p-1.5 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
            aria-label="缩小"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <span className="flex items-center px-1.5 text-white/80 text-xs tabular-nums">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); zoomIn(); }}
            className="p-1.5 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
            aria-label="放大"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
        </div>

        {/* 循环提示 */}
        {hint && (
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 px-4 py-2 rounded-lg bg-black/70 text-white text-sm pointer-events-none animate-pulse">
            {hint}
          </div>
        )}

        {/* 左右切换按钮 */}
        {total > 1 && (
          <>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); goPrev(); }}
              className="absolute left-3 top-1/2 -translate-y-1/2 z-10 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
              aria-label="上一张"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); goNext(); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 z-10 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
              aria-label="下一张"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          </>
        )}

        {/* 图片本体 */}
        <div
          className="flex items-center justify-center w-full h-full overflow-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={current.url}
            alt={current.title || ""}
            className="max-w-[90vw] max-h-[90vh] object-contain transition-transform duration-150"
            style={{ transform: `scale(${zoom})` }}
          />
        </div>

        {/* 底部标题与来源 */}
        {(current.title || current.source) && (
          <div className="absolute bottom-0 left-0 right-0 px-4 py-3 bg-gradient-to-t from-black/80 to-transparent text-white pointer-events-none">
            {current.title && (
              <div className="text-sm font-medium line-clamp-2">{current.title}</div>
            )}
            {current.source && (
              <div className="text-xs text-white/70 mt-0.5">来源：{current.source}</div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
