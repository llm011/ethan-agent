// 消息里附带的上传文件（非图片）——web / desktop 共用。
//
// 交互与「产物文件」（deliver_file 的 FileCardView）对齐：
// - md / html：在侧边预览面板打开（调用方通过 onPreview 注入 usePreview().open）
// - 图片类：交给调用方的 onPreviewImage 打开全局 Lightbox
// - 其他：直接下载
//
// 落盘与访问契约见 ethan/core/uploads.py：正文在 ~/.ethan/uploads/<session_id>/，
// DB 只存 {name, path, rel_path, size, media_type}，前端靠 rel_path 拼
// /api/assets/uploads/<rel_path>（鉴权同 <img>：cookie 或 ?token=）。
import { Download, Eye, FileText, ImageIcon, Paperclip } from "lucide-react";
import type { ChatFile } from "./types";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"]);
const PREVIEW_KINDS = new Set(["md", "html", "htm"]);

/** 文件扩展名（小写，不含点）。media_type 兜底。 */
export function fileKind(f: ChatFile): string {
  const fromName = /\.([A-Za-z0-9]{1,8})$/.exec(f.name || "");
  if (fromName) return fromName[1].toLowerCase();
  const fromPath = /\.([A-Za-z0-9]{1,8})$/.exec(f.path || "");
  if (fromPath) return fromPath[1].toLowerCase();
  return "";
}

/** 服务端返回的 rel_path；老数据没有 → undefined（不可直接访问，只展示文件名）。 */
export function assetRelPathOf(f: ChatFile): string | undefined {
  return f.rel_path || undefined;
}

/** 拼附件直链。rel_path 逐段 encode，防目录名里的特殊字符。 */
export function buildAssetUrl(relPath: string, apiUrl: string, token?: string): string {
  const encoded = relPath.split("/").map(encodeURIComponent).join("/");
  const base = `${apiUrl}/assets/uploads/${encoded}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function fmtFileSize(size?: number): string {
  if (size == null || !Number.isFinite(size) || size <= 0) return "";
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

interface ChatFilesProps {
  files: ChatFile[];
  /** 打开侧边预览（md / html）。 */
  onPreview?: (opts: { name: string; path: string; relPath: string; kind: "md" | "html" }) => void;
  /** 打开全局 Lightbox（图片类）。 */
  onPreviewImage?: (opts: { url: string; title: string }) => void;
  /** 拼直链（各端 API_URL / token 不一样）。 */
  getUrl: (relPath: string) => string;
  /** 其他类型下载；不给就退化成 <a href> 直链。 */
  onDownload?: (opts: { name: string; url: string }) => void;
}

function ChipIcon({ kind }: { kind: string }) {
  if (IMAGE_EXTS.has(kind)) return <ImageIcon className="h-3.5 w-3.5 shrink-0 opacity-70" />;
  if (PREVIEW_KINDS.has(kind)) return <FileText className="h-3.5 w-3.5 shrink-0 opacity-70" />;
  return <Paperclip className="h-3.5 w-3.5 shrink-0 opacity-70" />;
}

/** 消息气泡里的一条附件 chip。 */
function ChatFileChip({ file, onPreview, onPreviewImage, getUrl, onDownload }: { file: ChatFile } & Omit<ChatFilesProps, "files">) {
  const kind = fileKind(file);
  const relPath = assetRelPathOf(file);
  const url = relPath ? getUrl(relPath) : "";
  const isImage = IMAGE_EXTS.has(kind);
  const previewable = PREVIEW_KINDS.has(kind);
  const clickable = !!url && ((isImage && !!onPreviewImage) || (previewable && !!onPreview) || !!onDownload);

  const size = fmtFileSize(file.size);

  const inner = (
    <>
      <ChipIcon kind={kind} />
      <span className="truncate max-w-[220px]">{file.name}</span>
      {size && <span className="opacity-50 shrink-0">{size}</span>}
      {clickable && !isImage && !previewable && <Download className="h-3 w-3 shrink-0 opacity-60" />}
      {clickable && previewable && <Eye className="h-3 w-3 shrink-0 opacity-60" />}
    </>
  );

  const cls =
    "inline-flex items-center gap-1.5 max-w-full rounded-md border border-foreground/15 bg-foreground/5 px-2 py-1 text-xs " +
    (clickable ? "cursor-pointer hover:bg-foreground/10 transition-colors" : "opacity-70");

  const handleClick = () => {
    if (!url) return;
    if (isImage && onPreviewImage) { onPreviewImage({ url, title: file.name }); return; }
    if (previewable && onPreview) {
      onPreview({ name: file.name, path: file.path, relPath: relPath!, kind: kind === "htm" ? "html" : "md" });
      return;
    }
    if (onDownload) { onDownload({ name: file.name, url }); return; }
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // 老数据（无 rel_path）：不可点击，只展示文件名——至少让用户知道「这条消息带过文件」。
  if (!url) return <span className={cls} title={file.path}>{inner}</span>;

  return (
    <button type="button" className={cls} onClick={handleClick} title={file.rel_path || file.path}>
      {inner}
    </button>
  );
}

/** 一条消息附带的所有上传文件。 */
export function ChatFiles({ files, ...rest }: ChatFilesProps) {
  if (!files || files.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mb-1.5">
      {files.map((f, i) => (
        <ChatFileChip key={`${f.rel_path || f.path || f.name}-${i}`} file={f} {...rest} />
      ))}
    </div>
  );
}
