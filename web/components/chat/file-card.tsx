"use client";

import { useState, useEffect, useRef, type SyntheticEvent } from "react";
import { useRouter } from "next/navigation";
import { AudioLines, FileText, FileSpreadsheet, FileArchive, File as FileIcon, Presentation, Download, ImageIcon, Eye, Video } from "lucide-react";
import { API_URL, getAuthToken } from "@/lib/api-base";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import { Lightbox } from "./lightbox";
import type { FileCard } from "@ethan/shared/chat/types";
import { usePreview } from "@/components/preview-panel/preview-context";

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
  mp3: AudioLines,
  m4a: AudioLines,
};

const AUDIO_KINDS = new Set(["mp3", "m4a"]);

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

// 内联查看媒体的签名 URL（走 /files/view，供图片 Lightbox 与 MP4 播放器共用）
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

function VideoFileCard({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const [url, setUrl] = useState<string>("");
  const [ratio, setRatio] = useState<string | null>(null); // 检测到的宽高比，竖屏用 9/16 否则用 16/9
  const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const refreshCountRef = useRef(0); // 防止 onError 无限循环：最多刷新一次签名，仍失败则降级

  const refreshUrl = async (): Promise<string | undefined> => {
    try {
      const u = await signedViewUrl(card.path, sid);
      setUrl(u);
      return u;
    } catch {
      return undefined;
    }
  };

  useEffect(() => {
    let alive = true;
    void signedViewUrl(card.path, sid)
      .then((u) => { if (alive) setUrl(u); })
      .catch(() => {});
    return () => { alive = false; };
  }, [card.path, sid]);

  // 签名 URL 有 10 分钟 TTL；用户点播放时若已过期会 401/403，此时换一次新签名再播。
  // refreshCountRef 保证只刷新一次：刷新后仍失败说明视频永久损坏，清空 url 降级为下载。
  const handlePlay = (e: SyntheticEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    if (video.readyState === 0 || video.error) {
      if (refreshCountRef.current >= 1) {
        setUrl(""); // 第二次失败，清空降级为下载按钮
        return;
      }
      refreshCountRef.current += 1;
      void refreshUrl().then((fresh) => {
        if (fresh) {
          const t = video.currentTime;
          video.src = fresh;
          video.currentTime = t;
          video.play().catch(() => {});
        }
      });
    }
  };

  const onLoadedMetadata = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    if (v.videoWidth && v.videoHeight) {
      setRatio(`${v.videoWidth} / ${v.videoHeight}`);
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-border/50 bg-muted/30 w-full max-w-[520px]">
      {url ? (
        <video
          src={url}
          controls
          preload="metadata"
          // 不用固定的 aspect-video（16:9）：默认竖屏 1080×1920 会留大片黑边。
          // 用检测到的真实宽高比，未检测到时回退 16/9（横屏）避免布局抖动。
          style={{ aspectRatio: ratio ?? "16 / 9" }}
          className="block w-full max-h-[520px] bg-black object-contain"
          aria-label={card.title || card.filename}
          onLoadedMetadata={onLoadedMetadata}
          onPlay={handlePlay}
          onError={handlePlay}
        />
      ) : (
        <div className="flex items-center justify-center bg-black/90 text-muted-foreground" style={{ aspectRatio: ratio ?? "16 / 9" }}>
          <Video className="h-8 w-8" />
        </div>
      )}
      <div className="flex items-center gap-3 border-t border-border/50 px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {card.title || card.filename}
          {card.size_kb != null && ` · ${fmtSize(card.size_kb)}`}
        </span>
        <button
          type="button"
          onClick={() => void downloadSigned(card.path, sid).catch(() => {})}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-primary hover:bg-primary/10"
          aria-label={`下载 ${card.title || card.filename}`}
        >
          <Download className="h-3.5 w-3.5" />
          下载
        </button>
      </div>
    </div>
  );
}

// 交付的音频（book-audio-digest 听书 MP3）：内嵌原生 audio 播放器 + 下载按钮。
// 签名过期续播策略与 VideoFileCard 一致：点播放 401 时换一次新签名，仍失败降级下载。
function AudioFileCard({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const [url, setUrl] = useState<string>("");
  const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const refreshCountRef = useRef(0);

  const refreshUrl = async (): Promise<string | undefined> => {
    try {
      const u = await signedViewUrl(card.path, sid);
      setUrl(u);
      return u;
    } catch {
      return undefined;
    }
  };

  useEffect(() => {
    let alive = true;
    void signedViewUrl(card.path, sid)
      .then((u) => { if (alive) setUrl(u); })
      .catch(() => {});
    return () => { alive = false; };
  }, [card.path, sid]);

  const handlePlay = (e: SyntheticEvent<HTMLAudioElement>) => {
    const audio = e.currentTarget;
    if (audio.readyState === 0 || audio.error) {
      if (refreshCountRef.current >= 1) {
        setUrl("");
        return;
      }
      refreshCountRef.current += 1;
      void refreshUrl().then((fresh) => {
        if (fresh) {
          const t = audio.currentTime;
          audio.src = fresh;
          audio.currentTime = t;
          audio.play().catch(() => {});
        }
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border border-border/50 bg-background w-full max-w-[520px]">
      <div className="flex items-center gap-3 px-4 pt-3">
        <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-primary/10 text-primary flex-shrink-0">
          <AudioLines className="w-5 h-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium truncate">{card.title || card.filename}</div>
          <div className="text-xs text-muted-foreground truncate">
            {card.kind.toUpperCase()}
            {card.size_kb != null && ` · ${fmtSize(card.size_kb)}`}
          </div>
        </div>
      </div>
      {url ? (
        <audio
          src={url}
          controls
          preload="metadata"
          className="block w-full px-3 py-2"
          aria-label={card.title || card.filename}
          onPlay={handlePlay}
          onError={handlePlay}
        />
      ) : (
        <div className="flex items-center justify-center h-10 text-xs text-muted-foreground">
          音频加载中…
        </div>
      )}
      <div className="flex items-center gap-3 border-t border-border/50 px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          点击下载可保存到本地（车机/通勤场景）
        </span>
        <button
          type="button"
          onClick={() => void downloadSigned(card.path, sid).catch(() => {})}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-primary hover:bg-primary/10"
          aria-label={`下载 ${card.title || card.filename}`}
        >
          <Download className="h-3.5 w-3.5" />
          下载
        </button>
      </div>
    </div>
  );
}

// 可侧边预览的文件类型
const PREVIEWABLE_KINDS = new Set(["md", "html", "htm"]);

// 文件卡片：图片渲染缩略图 + Lightbox；MP4/MP3 内嵌播放并保留下载按钮；
// pptx 项目进入 /ppt-preview；md/html 在侧边面板预览；其余点击直接下载。
// 所有 URL 带 session_id——服务端只放行本 session 交付过的文件（会话级隔离）。
export function FileCardView({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const router = useRouter();
  const preview = usePreview();

  if (IMAGE_KINDS.has(card.kind)) {
    return <ImageFileCard card={card} sessionId={sessionId} />;
  }
  if (card.kind === "mp4") {
    return <VideoFileCard card={card} sessionId={sessionId} />;
  }
  if (AUDIO_KINDS.has(card.kind)) {
    return <AudioFileCard card={card} sessionId={sessionId} />;
  }

  const Icon = KIND_ICON[card.kind] ?? FileIcon;
  const previewable = card.kind === "pptx" && !!card.project_dir;
  const sidePreviewable = PREVIEWABLE_KINDS.has(card.kind);

  const handleClick = () => {
    const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
    if (sidePreviewable) {
      preview.open({
        path: card.path,
        filename: card.title || card.filename,
        kind: card.kind === "htm" ? "html" : card.kind as "md" | "html",
        sessionId,
      });
    } else if (previewable) {
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
      {sidePreviewable ? (
        <Eye className="w-4 h-4 text-primary flex-shrink-0" />
      ) : previewable ? (
        <span className="text-xs text-primary flex-shrink-0">预览</span>
      ) : (
        <Download className="w-4 h-4 text-muted-foreground flex-shrink-0" />
      )}
    </button>
  );
}
