import { useState } from "react";
import { ZoomIn } from "lucide-react";
import { Lightbox, type LightboxImage } from "./lightbox";

// 图片卡片数据结构（image_search 工具产出）
export interface ImageCard {
  type: "image";
  title: string;
  url: string;          // 图片远程 URL
  local_path: string;   // 下载模式才有，如 "/tmp/ethan_images/img_xxx.jpg"
  source: string;       // bing images/flickr/openverse 等
  page_url: string;     // 来源页面 URL
  width: number | null;
  height: number | null;
  size_kb: number | null;
}

interface ImageGalleryProps {
  cards: ImageCard[];
}

// 图片横向滚动画廊：点击图片或 hover 的「放大查看」按钮可打开 Lightbox
// 注：local_path 是 /tmp/ethan_images/xxx.jpg 这种本地路径，前端无法直接访问，
// 所以图片源统一用 url（远程 URL）；若存在 local_path 则在卡片上展示「已下载」标签。
export function ImageGallery({ cards }: ImageGalleryProps) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);

  const images: LightboxImage[] = cards.map((c) => ({
    url: c.url,
    title: c.title,
    source: c.source,
  }));

  return (
    <>
      <div className="flex gap-2 overflow-x-auto pb-2">
        {cards.map((card, i) => (
          <div
            key={`${card.url}-${i}`}
            className="group relative min-w-[160px] w-[160px] h-[120px] rounded-lg overflow-hidden border border-border/50 flex-shrink-0"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={card.url}
              alt={card.title || ""}
              className="w-full h-full object-cover cursor-zoom-in"
              onClick={() => {
                setIndex(i);
                setOpen(true);
              }}
            />
            {/* hover 时浮现的「放大查看」按钮 */}
            <button
              type="button"
              onClick={() => {
                setIndex(i);
                setOpen(true);
              }}
              className="absolute top-1 right-1 p-1 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label="放大查看"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            {/* 已下载标签 */}
            {card.local_path && (
              <span className="absolute bottom-1 left-1 px-1 py-0.5 rounded bg-black/60 text-white text-[9px] font-medium">
                已下载
              </span>
            )}
            {/* 来源标签 */}
            {card.source && (
              <span className="absolute bottom-1 right-1 px-1 py-0.5 rounded bg-black/60 text-white text-[9px] truncate max-w-[80px]">
                {card.source}
              </span>
            )}
          </div>
        ))}
      </div>

      <Lightbox
        images={images}
        index={index}
        open={open}
        onOpenChange={setOpen}
        onIndexChange={setIndex}
      />
    </>
  );
}
