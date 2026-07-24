import { useNavigate } from "react-router-dom";
import { FileText, FileSpreadsheet, FileArchive, File as FileIcon, Presentation, Download } from "lucide-react";
import { getApiUrl, getAuthToken } from "@/lib/api-base";
import { openUrl } from "@/lib/external-link";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import type { FileCard } from "@ethan/shared/chat/types";

// 文件卡片类型以 packages/shared 为准（web/desktop 共用，避免三处声明漂移）
export type { FileCard };

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

// 直链下载 URL：先换短期签名（Tauri webview 跨源，cookie 带不上，必须签名），
// 签名失败回退空（直链会 401，调用方应捕获提示）。
async function downloadSignedUrl(path: string, sid: string): Promise<string> {
  const sig = await signFileUrl(getApiUrl(), getAuthToken(), [path]);
  const s = sig[path];
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  return `${getApiUrl()}/files/download?path=${encodeURIComponent(path)}${sid}${sigQ}`;
}

// 文件卡片：pptx 且带项目目录时点击进 /ppt-preview 预览页，其余点击直接下载。
// 所有 URL 带 session_id——服务端只放行本 session 交付过的文件（会话级隔离）。
export function FileCardView({ card, sessionId }: { card: FileCard; sessionId?: string | null }) {
  const navigate = useNavigate();
  const Icon = KIND_ICON[card.kind] ?? FileIcon;
  const previewable = card.kind === "pptx" && !!card.project_dir;

  const handleClick = async () => {
    const sid = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
    if (previewable) {
      navigate(`/ppt-preview?path=${encodeURIComponent(card.path)}${sid}`);
    } else {
      // Tauri webview 里直接点击会被顶走，走系统浏览器下载
      openUrl(await downloadSignedUrl(card.path, sid));
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
