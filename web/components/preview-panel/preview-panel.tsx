"use client";

import { useEffect, useState } from "react";
import { X, Download } from "lucide-react";
import { usePreview } from "./preview-context";
import { API_URL, getAuthToken } from "@/lib/api-base";
import { signFileUrl } from "@ethan/shared/ppt/preview";
import { MarkdownContent } from "@/components/chat/markdown";

const STORAGE_KEY = "ethan:preview-panel-size";

export function getStoredPanelSize(): number {
  if (typeof window === "undefined") return 40;
  const v = localStorage.getItem(STORAGE_KEY);
  return v ? Number(v) : 40;
}

export function storePanelSize(size: number) {
  try {
    localStorage.setItem(STORAGE_KEY, String(Math.round(size)));
  } catch {}
}

async function fetchFileContent(path: string, sessionId?: string | null): Promise<string> {
  const sig = await signFileUrl(API_URL, getAuthToken(), [path]);
  const s = sig[path];
  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
  const url = `${API_URL}/files/download?path=${encodeURIComponent(path)}${sidQ}${sigQ}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch file: ${res.status}`);
  return res.text();
}

function buildDownloadUrl(path: string, sessionId?: string | null): string {
  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  return `${API_URL}/files/download?path=${encodeURIComponent(path)}${sidQ}`;
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

  const handleDownload = () => {
    const url = buildDownloadUrl(file.path, file.sessionId);
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
            srcDoc={content}
            className="w-full h-full border-0"
            sandbox="allow-scripts"
            title={file.filename}
          />
        )}
      </div>
    </div>
  );
}
