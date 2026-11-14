"use client";

/**
 * 聊天页客户端组件。
 *
 * 与 `page.tsx` 分开是因为 `generateStaticParams` 只能在 Server Component 里导出
 * （静态导出的占位声明）。业务逻辑全在这里。
 *
 * 为什么自己解析 pathname 而不用 useParams：静态导出下 `useParams()` 在
 * hydration 早期可能返回 `__placeholder__`（generateStaticParams 的占位值），
 * 会闪出一次错误的会话。直接读 pathname 更可靠。
 */

import { usePathname } from "next/navigation";
import { ChatView } from "@/components/chat-view";

export default function ChatClient() {
  const pathname = usePathname();
  const segs = (pathname ?? "").split("/").filter(Boolean);
  // /chat/<id> → ["chat", "<id>"]；/chat 或 /chat/new → 无有效 id
  const raw = segs[0] === "chat" && segs.length > 1 ? segs[1] : "";
  const sessionId = raw && raw !== "new" ? raw : undefined;
  return <ChatView initialSessionId={sessionId} />;
}
