import { useState } from "react";
import { ZoomIn } from "lucide-react";
import { Lightbox, type LightboxImage } from "./lightbox";
import { getApiUrl } from "@/lib/api-base";

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

// 把 card 转成可访问的图片 URL：
// - 有 local_path（download=true 模式）：转成 /api/images/<filename> 走后端 serve，
//   避免远程 URL 403/防盗链导致的破图
// - 无 local_path（download=false 模式）：直接用远程 URL
function getImageSrc(card: ImageCard): string {
  if (card.local_path) {
    const filename = card.local_path.split("/").pop() || "";
    if (filename) {
      return `${getApiUrl()}/images/${filename}`;
    }
  }
  return card.url;
}

// 图片横向滚动画廊：点击图片或 hover 的「放大查看」按钮可打开 Lightbox
// 有 local_path 时走 /api/images/<filename>（后端 serve 本地文件，无防盗链问题），
// 否则 fallback 到远程 URL（可能 403，卡片上会显示破图但 layout 不乱）。
export function ImageGallery({ cards }: ImageGalleryProps) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);

  const images: LightboxImage[] = cards.map((c) => ({
    url: getImageSrc(c),
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
              src={getImageSrc(card)}
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
