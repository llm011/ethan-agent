import { useEffect, useCallback } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";

// Lightbox 单张图片的描述信息
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

// 全屏黑色背景的图片查看器：支持多图浏览、键盘左右切换、ESC 关闭
export function Lightbox({ images, index, open, onOpenChange, onIndexChange }: LightboxProps) {
  const total = images.length;
  const current = total > 0 ? images[Math.min(index, total - 1)] : null;

  const goPrev = useCallback(() => {
    if (total <= 1) return;
    onIndexChange?.((index - 1 + total) % total);
  }, [index, total, onIndexChange]);

  const goNext = useCallback(() => {
    if (total <= 1) return;
    onIndexChange?.((index + 1) % total);
  }, [index, total, onIndexChange]);

  // 键盘事件：ESC 关闭、左右切换
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, goPrev, goNext, onOpenChange]);

  if (!current) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-w-none w-screen h-screen p-0 bg-black/95 rounded-none border-none ring-0"
        onClick={(e) => {
          // 点击背景（即 DialogContent 本身）关闭，点击图片不关闭
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

        {/* 图片本体：居中放大，最大 90vw x 90vh；阻止点击冒泡到背景 */}
        <div
          className="flex items-center justify-center w-full h-full"
          onClick={(e) => e.stopPropagation()}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={current.url}
            alt={current.title || ""}
            className="max-w-[90vw] max-h-[90vh] object-contain"
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
