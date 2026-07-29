/**
 * deep-link 监听 hook。
 *
 * 监听 Rust 端 emit 的 `deep-link-url` 事件，把 ethan:// URL 解析为
 * 站内路由并 navigate。需在 HashRouter 内部调用一次（App.tsx）。
 *
 * 支持的 pattern：
 *   ethan://chat/<sessionId>  -> /chat/<sessionId>
 *   ethan://chat              -> /chat
 *   ethan://sessions          -> /sessions
 *   ethan://settings/<tab>    -> /settings/<tab>
 *   ethan://memory            -> /memory
 *   ethan://knowledge         -> /knowledge
 *   ethan://skills            -> /skills
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

/** 把 ethan:// URL 映射为站内路径，无法识别时返回 null */
function mapDeepLinkUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "ethan:") return null;
  // host 为第一段 path，pathname 为剩余部分（带前导 /）
  const host = url.hostname;
  const rest = url.pathname.replace(/^\/+/, "");
  switch (host) {
    case "chat":
      return rest ? `/chat/${rest}` : "/chat";
    case "sessions":
      return "/sessions";
    case "settings":
      return rest ? `/settings/${rest}` : "/settings/general";
    case "memory":
      return "/memory";
    case "knowledge":
      return "/knowledge";
    case "skills":
      return "/skills";
    default:
      return null;
  }
}

export function useDeepLink(): void {
  const navigate = useNavigate();

  useEffect(() => {
    if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) return;
    let unlisten: (() => void) | undefined;
    // aborted 标记：组件在 listen() resolve 前卸载时，避免给已卸载组件挂 listener
    let aborted = false;
    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        if (aborted) return;
        unlisten = await listen<string>("deep-link-url", (event) => {
          const path = mapDeepLinkUrl(event.payload);
          if (path) navigate(path);
        });
      } catch {
        // deep-link 插件不可用时静默忽略
      }
    })();
    return () => {
      aborted = true;
      unlisten?.();
    };
  }, [navigate]);
}
