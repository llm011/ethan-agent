"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { FileText, FileSpreadsheet, FileArchive, File as FileIcon, Presentation, Download, ImageIcon } from "lucide-react";
import { API_URL, getAuthToken } from "@/lib/api-base";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import { Lightbox } from "./lightbox";
import type { FileCard } from "@ethan/shared/chat/types";

// 文件卡片类型以 packages/shared 为准（web/desktop 共用，避免三处声明漂移）
export type { FileCard };

// 图片类 kind：交付后渲染缩略图，点击开 Lightbox 放大（不走下载）
const IMAGE_KINDS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"]);

const KIND_ICON: Record<string, typeof FileIcon> = {
  pptx: Presentation,
  pdf: FileText,
  docx: FileText,
  md: FileText,
  xlsx: FileSpreadsheet,
  csv: FileSpreadsheet,
  zip: FileArchive,
};

function fmtSize(kb: number | null): string {
  if (kb == null) return "";
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.round(kb)} KB`;
}

// 直链下载：先换短期签名再触发 <a download>（不再把长效 token 拼进 URL）。
// 同源部署即便签名失败也靠 cookie 兜底；跨源失败则 401，前端提示重试。
async function downloadSigned(path: string, sid: string) {
  const sig = await signFileUrl(API_URL, getAuthToken(), [path]);
  const s = sig[path];
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  const a = document.createElement("a");
  a.href = `${API_URL}/files/download?path=${encodeURIComponent(path)}${sid}${sigQ}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// 内联查看图片的签名 URL（走 /files/view，inline 直出，供缩略图与 Lightbox 共用）
async function signedViewUrl(path: string, sid: string): Promise<string> {
  const sig = await signFileUrl(API_URL, getAuthToken(), [path]);
  const s = sig[path];
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  return `${API_URL}/files/view?path=${encodeURIComponent(path)}${sid}${sigQ}`;
}

// 交付的图片：卡片内渲染缩略图，点击开 Lightbox 全屏放大。
function ImageFileCard({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const [url, setUrl] = useState<string>("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
    void signedViewUrl(card.path, sid).then((u) => { if (alive) setUrl(u); });
    return () => { alive = false; };
  }, [card.path, sessionId]);

  return (
    <>
      <button
        type="button"
        onClick={() => url && setOpen(true)}
        className="block rounded-lg border border-border/50 overflow-hidden hover:border-border transition-colors cursor-zoom-in max-w-[320px]"
      >
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={card.title || card.filename} className="block max-w-full max-h-[240px] object-contain bg-muted/30" />
        ) : (
          <span className="flex items-center justify-center w-[240px] h-[160px] bg-muted/30 text-muted-foreground">
            <ImageIcon className="w-6 h-6" />
          </span>
        )}
        <span className="block px-3 py-1.5 text-xs text-muted-foreground truncate border-t border-border/50">
          {card.title || card.filename}
          {card.size_kb != null && ` · ${fmtSize(card.size_kb)}`}
        </span>
      </button>
      {url && (
        <Lightbox
          images={[{ url, title: card.title || card.filename }]}
          index={0}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}

// 文件卡片：图片渲染缩略图 + Lightbox；pptx 且带项目目录时点击进 /ppt-preview 预览页；其余点击直接下载。
// 所有 URL 带 session_id——服务端只放行本 session 交付过的文件（会话级隔离）。
export function FileCardView({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const router = useRouter();

  if (IMAGE_KINDS.has(card.kind)) {
    return <ImageFileCard card={card} sessionId={sessionId} />;
  }

  const Icon = KIND_ICON[card.kind] ?? FileIcon;
  const previewable = card.kind === "pptx" && !!card.project_dir;

  const handleClick = () => {
    const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
    if (previewable) {
      router.push(`/ppt-preview/?path=${encodeURIComponent(card.path)}${sid}`);
    } else {
      void downloadSigned(card.path, sid);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="text-left bg-muted/50 border border-border/50 rounded-lg p-3 w-full max-w-[320px] flex items-center gap-3 hover:bg-muted hover:border-border transition-colors cursor-pointer"
    >
      <span className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary flex-shrink-0">
        <Icon className="w-5 h-5" />
      </span>
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-medium truncate">{card.title || card.filename}</span>
        <span className="block text-xs text-muted-foreground truncate">
          {card.kind.toUpperCase()}
          {card.size_kb != null && ` · ${fmtSize(card.size_kb)}`}
          {card.page_count != null && ` · ${card.page_count} 页`}
        </span>
      </span>
      {previewable ? (
        <span className="text-xs text-primary flex-shrink-0">预览</span>
      ) : (
        <Download className="w-4 h-4 text-muted-foreground flex-shrink-0" />
      )}
    </button>
  );
}
