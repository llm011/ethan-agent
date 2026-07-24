"use client";

import { useRouter } from "next/navigation";
import { FileText, FileSpreadsheet, FileArchive, File as FileIcon, Presentation, Download } from "lucide-react";
import { API_URL } from "@/lib/api-base";

// 文件卡片数据结构（deliver_file 工具产出）
export interface FileCard {
  type: "file";
  filename: string;
  title?: string;
  path: string;
  size_kb: number | null;
  kind: string;
  project_dir?: string;
  page_count?: number;
}

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

// 文件卡片：pptx 且带项目目录时点击进 /ppt-preview 预览页，其余点击直接下载
export function FileCardView({ card }: { card: FileCard }) {
  const router = useRouter();
  const Icon = KIND_ICON[card.kind] ?? FileIcon;
  const previewable = card.kind === "pptx" && !!card.project_dir;

  const handleClick = () => {
    if (previewable) {
      router.push(`/ppt-preview/?path=${encodeURIComponent(card.path)}`);
    } else {
      window.open(`${API_URL}/files/download?path=${encodeURIComponent(card.path)}`, "_blank");
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
