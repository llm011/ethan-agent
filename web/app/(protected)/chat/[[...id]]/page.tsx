/**
 * 聊天页面 —— **唯一的聊天路由**。
 *
 * ## 为什么合并成一条路由（重要）
 *
 * 之前有两条独立页面：`/chat/page.tsx` 和 `/chat/[id]/page.tsx`，两者都渲染
 * `<ChatView />`，但在 Next.js 里属于**不同的路由段**。于是发第一条消息后
 * `router.replace("/chat/<id>")` 会让 React 卸载整棵旧组件树、挂载新的：
 *   · 用户看到页面闪一下
 *   · ChatView 内部 state（消息、滚动位置）全部重建
 *   · 静态导出下 `/chat/<真实id>` 没有预生成产物，客户端还可能加载失败
 *     （表现为 "This page couldn't load"）
 *
 * Desktop 端一直是合并的（`/chat`、`/chat/new`、`/chat/:sessionId` 都指向
 * 同一个 `ChatRoute`），所以那边从来没这个问题。这里对齐它。
 *
 * 用 `[[...id]]`（可选 catch-all）而不是 `[id]`：`/chat`、`/chat/new`、
 * `/chat/<id>` 全部命中**同一个组件实例**，路由切换不再卸载重建。
 */

import ChatClient from "./client";

export function generateStaticParams() {
  // 静态导出的占位：运行时任意 id 都由客户端渲染接管
  return [{ id: [] }];
}

export default function ChatPage() {
  return <ChatClient />;
}
