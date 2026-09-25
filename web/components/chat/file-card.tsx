"use client";

import { useState, useEffect, useRef, type SyntheticEvent } from "react";
import { useRouter } from "next/navigation";
import { AudioLines, FileText, FileSpreadsheet, FileArchive, File as FileIcon, Presentation, Download, ImageIcon, Eye, RotateCw, Video } from "lucide-react";
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

// 音频/视频加载看门狗超时：超过此时长仍未 canplay/loadedmetadata 即判失败。
// <audio>/<video> 在请求被拦、或连接半死时不触发 error 事件，只依赖事件会永久停在加载态；
// 这个定时器是错误态的兜底出口（与桌面端 desktop/src/components/chat/file-card.tsx 保持一致）。
const MEDIA_LOAD_TIMEOUT_MS = 15_000;

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
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
    void signedViewUrl(card.path, sid)
      .then((u) => { if (alive) setUrl(u); })
      // 签名失败不再产生 unhandled rejection：降级为明确失败态
      .catch(() => { if (alive) setFailed(true); });
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
          <span className="flex flex-col items-center justify-center gap-1 w-[240px] h-[160px] bg-muted/30 text-muted-foreground">
            <ImageIcon className="w-6 h-6" />
            {failed && <span className="text-xs text-destructive">图片加载失败</span>}
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
  const [failed, setFailed] = useState(false); // 永久失败时显示明确错误，而不是空占位
  const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const refreshCountRef = useRef(0); // 防止 onError 无限循环：最多刷新一次签名，仍失败则降级
  // 看门狗：被拦/挂死时 video 不触发 error，只靠事件会永久停在加载态（同 AudioFileCard）。
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };
  // 用 ref 读最新 url，避免在 setUrl 的 updater 里调 setFailed（updater 应是纯函数，
  // StrictMode 下可能被调用两次，副作用会重复触发）。
  const urlRef = useRef("");
  urlRef.current = url;
  const armTimer = () => {
    clearTimer();
    timerRef.current = setTimeout(() => {
      if (!urlRef.current) setFailed(true);
    }, MEDIA_LOAD_TIMEOUT_MS);
  };
  useEffect(() => clearTimer, []);

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
    setFailed(false);
    armTimer();
    void signedViewUrl(card.path, sid)
      .then((u) => { if (alive) setUrl(u); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; clearTimer(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.path, sid]);

  // 签名 URL 有 10 分钟 TTL；用户点播放时若已过期会 401/403，此时换一次新签名再播。
  // refreshCountRef 保证只刷新一次：刷新后仍失败说明视频永久损坏，降级为错误态。
  // 判据用 video.error 而不是 readyState===0——onPlay 每次正常播放都触发，
  // 刚起播时 readyState 仍可能是 0，用它会白白重签 + 重设 src 把播放打回开头。
  const recoverFromError = () => {
    if (refreshCountRef.current >= 1) {
      setUrl(""); // 第二次失败，降级为错误态 + 下载按钮
      setFailed(true);
      return;
    }
    refreshCountRef.current += 1;
    void refreshUrl()
      .then((fresh) => {
        if (fresh) {
          // refreshUrl 已 setUrl(newUrl)，React 用新 src 重挂 <video>
          armTimer();
        } else {
          setFailed(true);
        }
      })
      .catch(() => setFailed(true));
  };

  const handlePlay = (e: SyntheticEvent<HTMLVideoElement>) => {
    if (!e.currentTarget.error) return; // 正常播放不做事
    recoverFromError();
  };

  const onLoadedMetadata = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    clearTimer();
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
          onError={recoverFromError}
        />
      ) : (
        <div className="flex flex-col items-center justify-center gap-2 bg-black/90 text-muted-foreground" style={{ aspectRatio: ratio ?? "16 / 9" }}>
          <Video className="h-8 w-8" />
          {failed && <span className="text-xs text-destructive">视频加载失败</span>}
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
// 加载状态机：signing → loading → ready / error，任一分支都有出口，绝不无限 loading。
// 签名过期续播策略与 VideoFileCard 一致：点播放 401 时换一次新签名，仍失败降级错误态。
function AudioFileCard({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const [url, setUrl] = useState<string>("");
  // 状态机：signing/loading 都显示加载中，ready 显示播放器，error 显示明确错误 + 重试。
  const [state, setState] = useState<"signing" | "loading" | "ready" | "error">("signing");
  const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const refreshCountRef = useRef(0);
  // 看门狗：<audio> 在「请求被拦/连接挂死」时既不触发 error 也不触发 canplay，
  // 光靠事件会永远停在 loading。超时即判失败，保证错误态一定有出口。
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };
  const armTimer = () => {
    clearTimer();
    timerRef.current = setTimeout(() => setState((s) => (s === "ready" ? s : "error")), MEDIA_LOAD_TIMEOUT_MS);
  };
  useEffect(() => clearTimer, []);

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
    refreshCountRef.current = 0;
    setState("signing");
    void signedViewUrl(card.path, sid)
      .then((u) => {
        if (!alive) return;
        setUrl(u);
        setState("loading");
        armTimer();
      })
      .catch(() => { if (alive) setState("error"); });
    return () => {
      alive = false;
      clearTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.path, sid]);

  // 只在真正出错时换签名重试（含签名过期 401/403）。注意别用 readyState===0 当判据：
  // onPlay 在每次正常播放时都会触发，此时 readyState 可能仍是 0（刚起播还没缓冲完），
  // 会白白重签 + 重设 src，把正在播的音频打回开头。以 audio.error 为准。
  const recoverFromError = () => {
    if (refreshCountRef.current >= 1) {
      setState("error");
      return;
    }
    refreshCountRef.current += 1;
    void refreshUrl()
      .then((fresh) => {
        if (fresh) {
          // refreshUrl 已 setUrl(newUrl)，React 会用新 src 重新挂载 <audio>；
          // 重新武装看门狗，等 loadedmetadata/canplay 再判 ready。
          armTimer();
          setState("loading");
        } else {
          setState("error");
        }
      })
      .catch(() => setState("error"));
  };

  const handlePlay = (e: SyntheticEvent<HTMLAudioElement>) => {
    // 已经在播的正常播放不做事——只有带着 error 的播放才算失败重试。
    if (!e.currentTarget.error) return;
    recoverFromError();
  };

  const handleRetry = () => {
    refreshCountRef.current = 0;
    setState("signing");
    // 留空 url 让 <audio> 卸载再挂载，确保浏览器真的重新发起请求（同 src 不会重载）。
    setUrl("");
    void refreshUrl()
      .then((u) => {
        if (!u) {
          setState("error");
          return;
        }
        setState("loading");
        armTimer();
      })
      .catch(() => setState("error"));
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
      {state === "error" ? (
        <div className="flex items-center gap-2 px-4 py-2 text-xs text-muted-foreground">
          <span className="min-w-0 flex-1 text-destructive">音频加载失败</span>
          <button
            type="button"
            onClick={handleRetry}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-primary hover:bg-primary/10"
          >
            <RotateCw className="h-3.5 w-3.5" />
            重试
          </button>
        </div>
      ) : url && state !== "signing" ? (
        <audio
          src={url}
          controls
          preload="metadata"
          className="block w-full px-3 py-2"
          aria-label={card.title || card.filename}
          onLoadedMetadata={() => { clearTimer(); setState("ready"); }}
          onCanPlay={() => { clearTimer(); setState("ready"); }}
          onPlay={handlePlay}
          onError={recoverFromError}
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
