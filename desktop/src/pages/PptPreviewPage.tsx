import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toPng } from "html-to-image";
import { jsPDF } from "jspdf";
import {
  ArrowLeft,
  Download,
  FileText,
  Loader2,
  Minus,
  Plus,
  Presentation,
} from "lucide-react";
import { PptSlide, SlideGuard } from "@ethan/shared/ppt/slide";
import { CANVAS_H, CANVAS_W } from "@ethan/shared/ppt/types";
import type { PptSlideData, PptTheme } from "@ethan/shared/ppt/types";
import { getApiUrl, getAuthToken, headers } from "@/lib/api-base";
import { openUrl } from "@/lib/external-link";
import "katex/dist/katex.min.css";

interface DeckResponse {
  name: string;
  dir: string;
  deck: { theme?: PptTheme | string };
  pages: PptSlideData[];
  page_count: number;
  pptx_path: string | null;
}

const THUMB_SCALE = 0.16;

// Tauri webview 的 cookie origin 与 API 不同，直链（<img>/<a>）统一带 ?token=
function withToken(url: string): string {
  return `${url}&token=${encodeURIComponent(getAuthToken())}`;
}

export default function PptPreviewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const path = searchParams.get("path");
  // 服务端只放行本 session 交付过的文件（会话级隔离），所有 /api/files 请求都带上
  const sessionId = searchParams.get("session_id") ?? "";
  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";
  const [deck, setDeck] = useState<DeckResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportRef = useRef<HTMLDivElement>(null);
  const mainWrapRef = useRef<HTMLDivElement>(null);
  const [mainScale, setMainScale] = useState(0.8);

  useEffect(() => {
    if (!path) {
      setError("链接缺少 path 参数"); // 不设置会永远停在 loading
      return;
    }
    fetch(`${getApiUrl()}/files/deck?path=${encodeURIComponent(path)}${sidQ}`, { headers: headers() })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`);
        return res.json();
      })
      .then((d: DeckResponse) => setDeck(d))
      .catch((e) => setError(e.message || "加载失败"));
  }, [path]);

  useEffect(() => {
    const el = mainWrapRef.current;
    if (!el) return;
    const update = () => {
      const s = Math.min((el.clientWidth - 48) / CANVAS_W, (el.clientHeight - 48) / CANVAS_H);
      setMainScale(Math.max(0.2, s));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [deck]);

  const theme = useMemo<PptTheme>(() => {
    const t = deck?.deck?.theme;
    return t && typeof t === "object" ? t : {};
  }, [deck]);

  const assetUrl = useCallback(
    (src: string) => {
      if (!deck) return src;
      const abs = src.startsWith("/") ? src : `${deck.dir}/${src}`;
      return withToken(`${getApiUrl()}/files/asset?path=${encodeURIComponent(abs)}${sidQ}`);
    },
    [deck, sidQ]
  );

  const pptxPath = deck?.pptx_path ?? path;

  const downloadPptx = () => {
    if (pptxPath) openUrl(withToken(`${getApiUrl()}/files/download?path=${encodeURIComponent(pptxPath)}${sidQ}`));
  };

  // 下载 PDF：按需懒挂载隐藏容器（不拖累首屏），全尺寸渲染后逐页截图合成（jsPDF save 走 blob 下载，Tauri v2 webview 支持）
  const downloadPdf = async () => {
    if (!deck || exporting) return;
    setExportError(null);
    setExporting(true);
    // 等 React 把导出容器挂载出来（exporting 置真后才渲染）
    await new Promise((r) => setTimeout(r, 50));
    try {
      const container = exportRef.current;
      if (!container) throw new Error("导出容器未就绪");
      const pdf = new jsPDF({ orientation: "landscape", unit: "px", format: [CANVAS_W, CANVAS_H] });
      const nodes = Array.from(container.children) as HTMLElement[];
      for (let i = 0; i < nodes.length; i++) {
        const dataUrl = await toPng(nodes[i], { pixelRatio: 2, cacheBust: true });
        if (i > 0) pdf.addPage([CANVAS_W, CANVAS_H], "landscape");
        pdf.addImage(dataUrl, "PNG", 0, 0, CANVAS_W, CANVAS_H);
      }
      pdf.save(`${deck.name}.pdf`);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "PDF 导出失败");
    } finally {
      setExporting(false);
    }
  };

  const topBar = (
    <div className="h-12 flex items-center gap-3 px-4 border-b border-border bg-background flex-shrink-0">
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> 返回
      </button>
      <div className="flex items-center gap-2 min-w-0">
        <Presentation className="w-4 h-4 text-primary flex-shrink-0" />
        <span className="text-sm font-medium truncate">{deck?.name ?? "文件预览"}</span>
      </div>
      <div className="flex-1" />
      {deck && deck.page_count > 0 && (
        <div className="flex items-center gap-1 text-sm text-muted-foreground">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.1).toFixed(2)))}
            className="p-1 rounded hover:bg-muted"
          >
            <Minus className="w-4 h-4" />
          </button>
          <span className="w-12 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(2, +(z + 0.1).toFixed(2)))}
            className="p-1 rounded hover:bg-muted"
          >
            <Plus className="w-4 h-4" />
          </button>
          <span className="mx-2 tabular-nums">
            {current + 1} / {deck.page_count}
          </span>
        </div>
      )}
      {pptxPath && (
        <button
          type="button"
          onClick={downloadPptx}
          className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-border hover:bg-muted transition-colors"
        >
          <Download className="w-4 h-4" /> PPTX
        </button>
      )}
      {deck && deck.page_count > 0 && (
        <button
          type="button"
          onClick={downloadPdf}
          disabled={exporting}
          className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
          {exporting ? "导出中…" : "PDF"}
        </button>
      )}
      {exportError && <span className="text-xs text-destructive max-w-[220px] truncate">导出失败:{exportError}</span>}
    </div>
  );

  if (error) {
    return (
      <div className="h-full flex flex-col">
        {topBar}
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
          加载失败：{error}
        </div>
      </div>
    );
  }

  if (!deck) {
    return (
      <div className="h-full flex flex-col">
        {topBar}
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (deck.page_count === 0) {
    return (
      <div className="h-full flex flex-col">
        {topBar}
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <span className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-primary/10 text-primary">
            <Presentation className="w-10 h-10" />
          </span>
          <div className="text-sm text-muted-foreground">该文件不支持逐页预览，可直接下载 PPTX</div>
        </div>
      </div>
    );
  }

  const slide = deck.pages[current];

  return (
    <div className="h-full flex flex-col">
      {topBar}
      <div className="flex-1 flex min-h-0">
        <div className="w-[190px] flex-shrink-0 overflow-y-auto border-r border-border bg-muted/30 py-3 px-2 space-y-2">
          {deck.pages.map((p, i) => (
            <button
              key={p.id ?? i}
              type="button"
              onClick={() => setCurrent(i)}
              className={`relative block w-full rounded-md overflow-hidden border-2 transition-colors ${
                i === current ? "border-primary" : "border-transparent hover:border-border"
              }`}
            >
              <span className="absolute top-1 left-1 z-10 text-[10px] px-1 rounded bg-black/50 text-white tabular-nums">
                {String(i + 1).padStart(2, "0")}
              </span>
              <div className="pointer-events-none flex justify-center bg-white">
                <SlideGuard key={p.id ?? i} width={CANVAS_W * THUMB_SCALE} height={CANVAS_H * THUMB_SCALE}>
                  <PptSlide slide={p} theme={theme} scale={THUMB_SCALE} assetUrl={assetUrl} />
                </SlideGuard>
              </div>
            </button>
          ))}
        </div>
        <div ref={mainWrapRef} className="flex-1 flex items-center justify-center bg-muted/50 overflow-auto p-6">
          <div className="shadow-xl rounded-sm overflow-hidden">
            <SlideGuard key={current} width={CANVAS_W * mainScale * zoom} height={CANVAS_H * mainScale * zoom}>
              <PptSlide slide={slide} theme={theme} scale={mainScale * zoom} assetUrl={assetUrl} />
            </SlideGuard>
          </div>
        </div>
      </div>
      {/* PDF 导出用的隐藏全尺寸渲染（屏幕外）：仅在导出时懒挂载，不拖累首屏 */}
      {exporting && (
        <div ref={exportRef} style={{ position: "absolute", left: -99999, top: 0 }} aria-hidden>
          {deck.pages.map((p, i) => (
            <SlideGuard key={p.id ?? i} width={CANVAS_W} height={CANVAS_H}>
              <PptSlide slide={p} theme={theme} scale={1} assetUrl={assetUrl} />
            </SlideGuard>
          ))}
        </div>
      )}
    </div>
  );
}
