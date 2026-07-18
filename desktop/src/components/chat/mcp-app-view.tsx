import { useEffect, useRef, useState } from "react";
import { fetchUiResource } from "@/lib/api-base";
import type { McpApp } from "./types";

interface McpAppViewProps {
  apps: McpApp[];
}

/**
 * 工具 UI 资源渲染组件：将工具返回的 UI 模板在 sandbox iframe 中渲染，
 * 通过 postMessage 传入数据（JSON-RPC init）。
 *
 * 模板 HTML 按 ui:// URI 从 /api/ui-resources/read 拉取（而非内联在每条消息里），
 * 同一 URI 只请求一次，之后走模块级缓存。模板与数据分离，让带宽消耗最小化。
 */
export function McpAppView({ apps }: McpAppViewProps) {
  return (
    <div className="flex flex-col gap-3 mt-2">
      {apps.map((app, i) => (
        <McpAppFrame key={`${app.uri}-${i}`} app={app} />
      ))}
    </div>
  );
}

// 模块级模板缓存：uri → HTML（或正在拉取的 Promise），跨消息/组件复用，避免重复请求。
const _templateCache = new Map<string, Promise<string>>();

function loadTemplate(app: McpApp): Promise<string> {
  // 兼容旧数据：若结果里内联了 html，直接用，不发请求。
  if (app.html) return Promise.resolve(app.html);
  const cached = _templateCache.get(app.uri);
  if (cached) return cached;
  const p = fetchUiResource(app.uri)
    .then((r) => r.text)
    .catch((e) => {
      _templateCache.delete(app.uri); // 失败不缓存，允许重试
      throw e;
    });
  _templateCache.set(app.uri, p);
  return p;
}

function McpAppFrame({ app }: { app: McpApp }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [html, setHtml] = useState<string | null>(app.html ?? null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (html !== null) return;
    let cancelled = false;
    loadTemplate(app)
      .then((h) => !cancelled && setHtml(h))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [app, html]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || html === null) return;

    const handleLoad = () => {
      // iframe 加载完毕后，通过 postMessage 发送 init 消息（JSON-RPC），把数据打进去。
      const initMsg = {
        jsonrpc: "2.0",
        method: "init",
        params: app.data || {},
      };
      iframe.contentWindow?.postMessage(initMsg, "*");
    };

    iframe.addEventListener("load", handleLoad);
    // srcDoc 可能已加载完（缓存命中时同步），补发一次以防错过 load 事件。
    if (iframe.contentDocument?.readyState === "complete") handleLoad();
    return () => iframe.removeEventListener("load", handleLoad);
  }, [app.data, html]);

  if (error) {
    return (
      <div className="text-xs text-muted-foreground border border-border rounded-lg p-3">
        图表模板加载失败（{app.uri}）
      </div>
    );
  }

  if (html === null) {
    return (
      <div className="w-full border border-border rounded-lg bg-white flex items-center justify-center text-xs text-muted-foreground" style={{ height: "120px" }}>
        加载图表…
      </div>
    );
  }

  // 用 srcDoc 渲染 HTML，sandbox 限制能力（仅允许脚本执行）。
  return (
    <iframe
      ref={iframeRef}
      srcDoc={html}
      sandbox="allow-scripts"
      className="w-full border border-border rounded-lg bg-white"
      style={{ height: "480px", maxHeight: "520px" }}
      title={app.uri}
    />
  );
}
