import { useEffect, useState } from "react";
import { X, Download } from "lucide-react";
import { usePreview } from "./preview-context";
import { getApiUrl, getAuthToken } from "@/lib/api-base";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import { MarkdownContent } from "@/components/chat/markdown";

const STORAGE_KEY = "ethan:preview-panel-size";

export function getStoredPanelSize(): number {
  const v = localStorage.getItem(STORAGE_KEY);
  const n = Number(v);
  return v && !isNaN(n) ? n : 40;
}

export function storePanelSize(size: number) {
  try {
    localStorage.setItem(STORAGE_KEY, String(Math.round(size)));
  } catch {}
}

async function fetchFileContent(path: string, sessionId?: string | null): Promise<string> {
  const sig = await signFileUrl(getApiUrl(), getAuthToken(), [path]);
  const s = sig[path];
  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  const url = `${getApiUrl()}/files/download?path=${encodeURIComponent(path)}${sidQ}${sigQ}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch file: ${res.status}`);
  return res.text();
}

// sandbox="allow-scripts" 只隔离了同源（父页面 DOM/cookie/localStorage），
// 但脚本仍可发起任意网络请求（内网探测、本地服务副作用、数据外带）。
// 注入严格 CSP：阻断一切网络加载与请求，只保留内联脚本/样式和 data:/blob: 资源。
const CSP_META =
  '<meta http-equiv="Content-Security-Policy" content="' +
  "default-src 'none'; " +
  "script-src 'unsafe-inline'; " +
  "style-src 'unsafe-inline'; " +
  "img-src data: blob:; " +
  "font-src data: blob:; " +
  "media-src data: blob:; " +
  'form-action \'none\'; ' +
  'base-uri \'none\'">';

function hardenHtml(html: string): string {
  if (/<head[^>]*>/i.test(html)) {
    // 插到 head 开头，确保先于任何会触发加载的元素生效
    return html.replace(/<head([^>]*)>/i, `<head$1>${CSP_META}`);
  }
  if (/<html[^>]*>/i.test(html)) {
    return html.replace(/<html([^>]*)>/i, `<html$1><head>${CSP_META}</head>`);
  }
  return `${CSP_META}${html}`;
}

async function buildDownloadUrl(path: string, sessionId?: string | null): Promise<string> {
  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const sig = await signFileUrl(getApiUrl(), getAuthToken(), [path]);
  const s = sig[path];
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  return `${getApiUrl()}/files/download?path=${encodeURIComponent(path)}${sidQ}${sigQ}`;
}

export function PreviewPanel() {
  const { file, close } = usePreview();
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!file) return;
    let alive = true;
    setLoading(true);
    setError("");
    setContent("");

    fetchFileContent(file.path, file.sessionId)
      .then((text) => { if (alive) setContent(text); })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });

    return () => { alive = false; };
  }, [file]);

  if (!file) return null;

  const handleDownload = async () => {
    const url = await buildDownloadUrl(file.path, file.sessionId);
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div className="flex flex-col h-full bg-background border-l border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
        <span className="text-sm font-medium truncate flex-1 mr-2">{file.filename}</span>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleDownload}
            className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title="下载文件"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={close}
            className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title="关闭预览"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {loading && (
          <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
            加载中...
          </div>
        )}
        {error && (
          <div className="p-4 text-sm text-destructive">{error}</div>
        )}
        {!loading && !error && file.kind === "md" && content && (
          <div className="p-6">
            <MarkdownContent content={content} className="max-w-none" />
          </div>
        )}
        {!loading && !error && file.kind === "html" && content && (
          <iframe
            srcDoc={hardenHtml(content)}
            className="w-full h-full border-0"
            sandbox="allow-scripts"
            title={file.filename}
          />
        )}
      </div>
    </div>
  );
}
