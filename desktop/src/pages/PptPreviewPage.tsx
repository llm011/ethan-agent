import { useNavigate, useSearchParams } from "react-router-dom";
import { PptPreviewView } from "@ethan/shared/ppt/preview";
import { getApiUrl, getAuthToken, headers } from "@/lib/api-base";
import { openUrl } from "@/lib/external-link";
import "katex/dist/katex.min.css";

export default function PptPreviewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const path = searchParams.get("path");
  const sessionId = searchParams.get("session_id") ?? "";

  return (
    <PptPreviewView
      path={path}
      sessionId={sessionId}
      adapter={{
        apiUrl: getApiUrl(),
        headers: headers(),
        authToken: getAuthToken(),
        goBack: () => navigate(-1),
        openDownload: (url) => openUrl(url),
      }}
    />
  );
}
