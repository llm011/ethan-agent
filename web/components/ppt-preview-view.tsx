"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { PptPreviewView, signFileUrl } from "@ethan/shared/ppt/preview";
import { API_URL, getAuthToken, headers } from "@/lib/api-base";
import "katex/dist/katex.min.css";

export function PptPreviewViewWeb() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const path = searchParams.get("path");
  const sessionId = searchParams.get("session_id") ?? "";

  return (
    <PptPreviewView
      path={path}
      sessionId={sessionId}
      adapter={{
        apiUrl: API_URL,
        headers: headers(),
        authToken: getAuthToken(),
        goBack: () => router.back(),
        openDownload: (url) => {
          // 同源部署：直接用 <a> 下载（cookie 兜底鉴权；desktop 走 openUrl）
          const a = document.createElement("a");
          a.href = url;
          a.download = "";
          document.body.appendChild(a);
          a.click();
          a.remove();
        },
      }}
    />
  );
}

export { signFileUrl };
