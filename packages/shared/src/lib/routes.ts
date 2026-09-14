/**
 * URL 路径 → 业务状态 的派生规则（Web 与桌面端共用）。
 *
 * 两端各有自己的 router（Web: Next.js App Router；桌面端: react-router 的 HashRouter），
 * 但各自从 pathname 派生的「当前活跃会话」规则必须一致 —— 这类规则历史上在两个
 * Sidebar 里各写了一份，容易悄悄漂移，故收到这里共享 + 单测。
 */

/** 开新会话的虚拟路由段：`/chat/<NEW_SESSION_SEGMENT>`。 */
export const NEW_SESSION_SEGMENT = "new";

/**
 * 从 pathname 派生当前活跃的会话 id（侧边栏高亮、标记已读用）。
 *
 * 只认 `/chat/<id>` 形态；`/chat` 与虚拟路由 `/chat/new` 都返回 `null`
 * （「当前没有活跃会话」）。
 *
 * 为什么必须排除 `"new"`：它只是「开一个新会话」的虚拟路由段，不是真会话。
 * 若不排除，派生出的 `"new"` 会被当成会话 id 传下去 —— 对不存在的会话发
 * `POST /sessions/new/read`（每次开新会话白打一个 404），且没有任何会话能命中高亮。
 */
export function activeSessionIdFromPathname(pathname: string | null | undefined): string | null {
  if (!pathname) return null;
  const matched = pathname.match(/^\/chat\/(.+)$/)?.[1];
  if (!matched || matched === NEW_SESSION_SEGMENT) return null;
  return matched;
}
