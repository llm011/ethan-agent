"use client";

import { useEffect, useRef } from "react";
import type { McpApp } from "./types";

interface McpAppViewProps {
  apps: McpApp[];
}

/**
 * MCP Apps 渲染组件：将 MCP App HTML 在 sandbox iframe 中渲染，
 * 通过 postMessage 传入数据（遵循 SEP-1865 JSON-RPC 协议）。
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

function McpAppFrame({ app }: { app: McpApp }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const handleLoad = () => {
      // iframe 加载完毕后，通过 postMessage 发送 init 消息（SEP-1865 JSON-RPC）
      const initMsg = {
        jsonrpc: "2.0",
        method: "init",
        params: app.data || {},
      };
      iframe.contentWindow?.postMessage(initMsg, "*");
    };

    iframe.addEventListener("load", handleLoad);
    return () => iframe.removeEventListener("load", handleLoad);
  }, [app.data]);

  // 用 srcdoc 渲染 HTML，sandbox 限制能力
  return (
    <iframe
      ref={iframeRef}
      srcDoc={app.html}
      sandbox="allow-scripts"
      className="w-full border border-border rounded-lg bg-white"
      style={{ height: "480px", maxHeight: "520px" }}
      title={app.uri}
    />
  );
}
