/** Chat streaming 相关类型和 API。 */

import { getApiUrl, headers  } from "./api-base";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: number;
  images?: { data: string; media_type: string }[];  // base64 raw (no data: prefix)
}

export type StreamChunk = { content?: string; done?: boolean; stopped?: boolean; error?: string; model?: string; usage?: Record<string, number>; ttfb_ms?: number; total_ms?: number; message_id?: number; title?: string; tool?: string; args?: string; intent?: string; state?: string; id?: string; duration_ms?: number; result_preview?: string; result_detail?: string; entity_type?: string; entity_id?: string; sub_steps?: Array<{ tool: string; args: string; state: string; duration_ms?: number | null; result_preview?: string }>; ui?: unknown[]; mcp_app?: { uri: string; data?: Record<string, unknown>; html?: string; csp?: Record<string, string[]> }; consent_request?: boolean; request_id?: string; description?: string; detail?: string; thinking?: boolean; heartbeat?: boolean; elapsed?: number; skills_matched?: Array<{ name: string; is_default?: boolean }>; background_polling?: boolean; polling_message?: string; new_message?: boolean };

/** 把一个 SSE Response body 解析成事件流（streamChat / streamResume 共用）。 */
async function* parseSSE(res: Response): AsyncGenerator<StreamChunk> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {}
      }
    }
  }
}

export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
  options?: {
    quote?: { role: "user" | "assistant"; content: string } | null;
    mode?: string;
    btw?: boolean;
    review?: boolean;
  },
): AsyncGenerator<StreamChunk> {
  const { quote = null, mode = "", btw = false, review = false } = options ?? {};
  let res: Response;
  try {
    res = await fetch(`${getApiUrl()}/chat`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ messages, model, stream: true, session_id: sessionId, quote: quote ?? undefined, mode: mode || undefined, btw: btw || undefined, auto_consent: review || undefined }),
    });
  } catch {
    // fetch 直接抛错 = 连不上后端（服务没起 / 端口不通）
    throw new Error("连接不上 Ethan 服务，请确认后端已启动（ethan serve）后重试。");
  }

  if (!res.ok) {
    throw new Error(await friendlyHttpError(res));
  }

  yield* parseSSE(res);
}

/** 把非 2xx 响应转成给用户看的中文提示。优先读后端返回的 detail，再按状态码兜底。 */
async function friendlyHttpError(res: Response): Promise<string> {
  let detail = "";
  try {
    const body = await res.clone().json();
    detail = typeof body?.detail === "string" ? body.detail : "";
  } catch {
    // 非 JSON 响应，忽略
  }
  if (detail) return detail;
  if (res.status === 401) return "登录已失效或未授权，请重新登录后重试。";
  if (res.status === 404) return "接口不存在，可能是前后端版本不匹配，建议重启服务。";
  if (res.status >= 500) return `Ethan 服务内部错误（${res.status}）。请稍后重试，或查看服务端日志 ~/.ethan/logs/api.err.log 排查。`;
  return `请求失败（${res.status}）。`;
}

/** 重连一个仍在进行的生成：刷新页面后调此函数，回放缓冲 + 继续实时。
 *  无活跃 run 时后端返回 204，这里返回 null，调用方走普通 fetchSession。 */
export async function streamResume(sessionId: string): Promise<AsyncGenerator<StreamChunk> | null> {
  const res = await fetch(`${getApiUrl()}/chat/${encodeURIComponent(sessionId)}/stream`, {
    headers: headers(),
  });
  if (res.status === 204 || !res.ok) return null;
  return parseSSE(res);
}

/** 停止某 session 进行中的生成；已生成内容会被保存并标记 [已停止]。 */
export async function stopGeneration(sessionId: string): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(`${getApiUrl()}/chat/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return { ok: false, stopped: false };
  return res.json();
}
