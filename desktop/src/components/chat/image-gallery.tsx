import { useState } from "react";
import { ZoomIn } from "lucide-react";
import { Lightbox, type LightboxImage } from "./lightbox";
import { assetUrl, getApiUrl } from "@/lib/api-base";

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
// - url 是相对资产路径（file_read / 迁移落盘的 "assets/images/..."）：走 assetUrl()
//   拼成 /api/assets/images/...（带 immutable 缓存；桌面端自动补 ?token=）
// - 有 local_path（image_search download=true 模式）：转成 /api/images/<filename>
// - 无以上两者（image_search download=false 模式）：直接用远程 URL
function getImageSrc(card: ImageCard): string {
  // 相对资产路径（file_read / 迁移落盘的 "assets/images/..."）优先，走 assetUrl()
  if (card.url && !/^(https?:|data:|blob:)/.test(card.url)) {
    return assetUrl(card.url);
  }
  // 远程直链：直接用（image_search download=false）
  if (card.url && /^https?:/.test(card.url)) {
    return card.url;
  }
  // 本地下载图（image_search download=true）：走 /api/images/<filename>
  if (card.local_path) {
    const filename = card.local_path.split("/").pop() || "";
    if (filename) {
      return `${getApiUrl()}/images/${filename}`;
    }
  }
  return card.url;
}

// 图片画廊：
// - 1 张：按自然比例在合理上限内展示（超长/超宽图适度裁切，避免变成细条）
// - 2 张：2 列等宽方图，均分间隙
// - 3+ 张：每行 3 张等宽方图，object-cover 填满格面、消除空白，图间保持统一 8px 间隙
export function ImageGallery({ cards }: ImageGalleryProps) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);

  const images: LightboxImage[] = cards.map((c) => ({
    url: getImageSrc(c),
    title: c.title,
    source: c.source,
  }));

  const isSingle = cards.length === 1;
  const gridClass = isSingle
    ? "not-prose"
    : cards.length === 2
      ? "not-prose grid grid-cols-2 gap-2"
      : "not-prose grid grid-cols-3 gap-2";

  return (
    <>
      <div className={gridClass}>
        {cards.map((card, i) => (
          <div
            key={`${card.url}-${i}`}
            className={
              isSingle
                ? "group relative w-fit max-w-full sm:max-w-[360px] rounded-lg overflow-hidden border border-border/50 bg-muted/20"
                : "group relative aspect-square w-full rounded-lg overflow-hidden border border-border/50 bg-muted/20"
            }
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={getImageSrc(card)}
              alt={card.title || ""}
              className={
                isSingle
                  ? "my-0 block min-w-[140px] min-h-[120px] max-w-full sm:max-w-[360px] max-h-[280px] w-auto h-auto object-cover cursor-zoom-in"
                  : "my-0 block w-full h-full object-cover cursor-zoom-in transition-transform duration-200 group-hover:scale-[1.03]"
              }
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
              className="absolute top-1.5 right-1.5 p-1 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label="放大查看"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            {/* 已下载标签 */}
            {card.local_path && (
              <span className="absolute bottom-1.5 left-1.5 px-1 py-0.5 rounded bg-black/60 text-white text-[9px] font-medium">
                已下载
              </span>
            )}
            {/* 来源标签 */}
            {card.source && (
              <span className="absolute bottom-1.5 right-1.5 px-1 py-0.5 rounded bg-black/60 text-white text-[9px] truncate max-w-[80px]">
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
