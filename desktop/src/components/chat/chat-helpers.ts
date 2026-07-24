import type { Message } from "@ethan/shared/chat/types";
import { assetUrl } from "../../lib/api-base";

// 清洗后的占位标题：去 markdown 标记 / 命令前缀，截断 40 字
// 与后端 _auto_title 逻辑对齐，让前端 0ms 显示可读标题
export function placeholderTitle(text: string): string {
  let t = text.trim();
  t = t.replace(/[*#`_~]/g, '');
  t = t.replace(/^\/(?:help|new|model|token|btw|stop)\s+/, '');
  t = t.replace(/\n/g, ' ').trim();
  if (!t) t = text.trim().replace(/\n/g, ' ');
  return t.slice(0, 40) + (t.length > 40 ? '…' : '');
}

// SessionDetail.messages → 组件内 Message[]（fetchSession 初次加载 + 重连失败兜底共用）
export function mapDetailMessages(detail: { messages: any[] }): Message[] {
  return detail.messages.map((m: any) => ({
    role: m.role,
    id: m.id ?? undefined,
    content: m.content,
    created_at: m.created_at,
    usage: m.usage || undefined,
    quote: m.quote || undefined,
    images: m.images && m.images.length > 0
      ? m.images.map((img: any) => ({
          name: "",
          path: "",
          isImage: true,
          dataUrl: img.url
            ? assetUrl(img.url)
            : img.data
              ? `data:${img.media_type || "image/png"};base64,${img.data}`
              : img.dataUrl,
        }))
      : undefined,
    toolSteps: m.tool_steps && m.tool_steps.length > 0
      ? m.tool_steps.map((s: any) => ({
          tool: s.tool,
          args: s.args,
          intent: s.intent,
          state: s.state as "running" | "done" | "error",
          duration_ms: s.duration_ms,
          result_preview: s.result_preview,
          result_detail: s.result_detail,
          thought: s.thought,
          entity_type: s.entity_type,
          entity_id: s.entity_id,
          sub_steps: s.sub_steps?.map((ss: any) => ({
            tool: ss.tool,
            args: ss.args,
            state: ss.state as "running" | "done" | "error",
            duration_ms: ss.duration_ms ?? undefined,
            result_preview: ss.result_preview,
          })),
        }))
      : undefined,
    toolsExpanded: false,
    a2ui: m.a2ui && m.a2ui.length > 0 ? m.a2ui : undefined,
    mcpApps: m.mcp_apps && m.mcp_apps.length > 0 ? m.mcp_apps : undefined,
    matchedSkills: m.matched_skills || undefined,
    ttfb_ms: m.ttfb_ms ?? undefined,
    total_ms: m.total_ms ?? undefined,
  }));
}
