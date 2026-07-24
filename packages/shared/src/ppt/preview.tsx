/** ppt-preview：项目制 PPT 逐页预览（缩略图 + 主视图 + PDF 导出）。

web/desktop 两端共用本组件，差异只在「怎么拿 API_URL / 怎么导航 / 怎么打开外链」，
通过 PptPreviewProps 的 adapter 解耦——两端 page 只需传一组 adapter。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { PptSlide, SlideGuard } from "./slide";
import { CANVAS_H, CANVAS_W } from "./types";
import type { PptSlideData, PptTheme } from "./types";

interface DeckResponse {
  name: string;
  dir: string;
  deck: { theme?: PptTheme | string };
  pages: PptSlideData[];
  page_count: number;
  pptx_path: string | null;
}

const THUMB_SCALE = 0.16;

/** 浏览器直链（<img>/<a>）无法带 Authorization header 的鉴权 query 片段。
 *  web 同源部署 cookie 会自动带上，sig 留空即可；desktop/Tauri 跨源 cookie 带不上，
 *  必须用短期签名（前端先调 POST /files/sign 换，10 分钟有效，见 signFileUrl）。 */
export interface SignedQuery {
  user: string;
  sig: string;
}

/** 平台差异：API URL、导航返回、token、headers、打开外链下载。 */
export interface PptPreviewAdapter {
  apiUrl: string;
  headers: HeadersInit;
  authToken: string;
  goBack: () => void;
  openDownload: (url: string) => void;
}

export interface PptPreviewProps {
  path: string | null;
  sessionId: string;
  adapter: PptPreviewAdapter;
}

/** 收集一页里所有需要鉴权的资源 path（image 元素 src + image 背景 src）。 */
function collectAssetPaths(pages: PptSlideData[], dir: string): string[] {
  const out = new Set<string>();
  const push = (src: string | undefined) => {
    if (!src || /^https?:\/\//.test(src) || src.startsWith("gen:") || src.startsWith("icon:")) return;
    out.add(src.startsWith("/") ? src : `${dir}/${src}`);
  };
  for (const p of pages) {
    push(p.background?.type === "image" ? p.background.image?.src : undefined);
    for (const el of p.elements ?? []) {
      if (el.type === "image") push(el.src);
    }
  }
  return [...out];
}

export function PptPreviewView({ path, sessionId, adapter }: PptPreviewProps) {
  const { apiUrl, headers, authToken, goBack, openDownload } = adapter;
  const [deck, setDeck] = useState<DeckResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const exportRef = useRef<HTMLDivElement>(null);
  const mainWrapRef = useRef<HTMLDivElement>(null);
  const [mainScale, setMainScale] = useState(0.8);
  // path → 短期签名（deck 到达后批量签发，<img>/<a> 直链用）
  const [sigs, setSigs] = useState<Record<string, SignedQuery>>({});

  const sidQ = sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : "";

  useEffect(() => {
    if (!path) {
      setError("链接缺少 path 参数"); // 不设置会永远停在 loading
      return;
    }
    fetch(`${apiUrl}/files/deck?path=${encodeURIComponent(path)}${sidQ}`, { headers })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`);
        return res.json();
      })
      .then((d: DeckResponse) => setDeck(d))
      .catch((e) => setError(e.message || "加载失败"));
  }, [path, apiUrl, sidQ, headers]);

  // deck 到达后批量签发所有资源 + pptx 的短期签名（一次 POST，<img> 直链鉴权用）
  useEffect(() => {
    if (!deck || !authToken) return;
    const paths = collectAssetPaths(deck.pages, deck.dir);
    if (deck.pptx_path) paths.push(deck.pptx_path);
    if (!paths.length) return;
    signFileUrl(apiUrl, authToken, paths).then((map) => {
      if (Object.keys(map).length) setSigs((prev) => ({ ...prev, ...map }));
    });
  }, [deck, apiUrl, authToken]);

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

  // 拼直链 URL：session_id + 短期签名（有签名就带，web 同源 cookie 也能兜底）
  const directUrl = useCallback(
    (endpoint: string, absPath: string) => {
      const s = sigs[absPath];
      const sigQ = s ? `&user=${encodeURIComponent(s.user)}&sig=${encodeURIComponent(s.sig)}` : "";
      return `${apiUrl}/files/${endpoint}?path=${encodeURIComponent(absPath)}${sidQ}${sigQ}`;
    },
    [apiUrl, sigs, sidQ]
  );

  const assetUrl = useCallback(
    (src: string) => {
      if (!deck) return src;
      const abs = src.startsWith("/") ? src : `${deck.dir}/${src}`;
      return directUrl("asset", abs);
    },
    [deck, directUrl]
  );

  const pptxPath = deck?.pptx_path ?? path;
  const downloadPptx = () => {
    if (pptxPath) openDownload(directUrl("download", pptxPath));
  };

  // 下载 PDF：按需懒挂载隐藏容器（不拖累首屏），全尺寸渲染后逐页截图合成
  const downloadPdf = async () => {
    if (!deck || exporting) return;
    setExportError(null);
    setExporting(true);
    await new Promise((r) => setTimeout(r, 50)); // 等导出容器挂载
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
        onClick={goBack}
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
          加载失败:{error}
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
        {/* 左侧缩略图栏 */}
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
        {/* 主视图 */}
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

/** 用长效 token 调 POST /files/sign 批量换 path 级短期签名（10 分钟有效）。
 *  失败的 path 不进返回 map——web 同源部署靠 cookie 兜底，desktop 失败则直链 401。
 *  两端 page 都用它给 <img>/<a> 直链注入签名，避免把长效 token 拼进 URL。 */
export async function signFileUrl(
  apiUrl: string,
  authToken: string,
  paths: string[]
): Promise<Record<string, SignedQuery>> {
  if (!authToken || !paths.length) return {};
  try {
    const res = await fetch(`${apiUrl}/files/sign`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
      body: JSON.stringify({ paths }),
    });
    if (!res.ok) return {};
    const data = await res.json();
    const user: string = data.user ?? "";
    const sigs: Record<string, SignedQuery> = {};
    for (const [p, sig] of Object.entries(data.signatures ?? {})) {
      if (sig) sigs[p] = { user, sig: sig as string };
    }
    return sigs;
  } catch {
    return {};
  }
}
