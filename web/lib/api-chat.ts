/** Chat streaming 相关类型和 API。 */

import { API_URL, headers } from "./api-base";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: number;
  images?: { data: string; media_type: string }[];  // base64 raw (no data: prefix)
}

export type StreamChunk = { content?: string; done?: boolean; stopped?: boolean; error?: string; model?: string; usage?: Record<string, number>; ttfb_ms?: number; total_ms?: number; tool?: string; args?: string; intent?: string; state?: string; id?: string; duration_ms?: number; result_preview?: string; result_detail?: string; entity_type?: string; entity_id?: string; sub_steps?: Array<{ tool: string; args: string; state: string; duration_ms?: number | null; result_preview?: string }>; ui?: unknown[]; consent_request?: boolean; request_id?: string; description?: string; detail?: string; thinking?: boolean; heartbeat?: boolean; elapsed?: number; skills_matched?: Array<{ name: string; is_default?: boolean }> };

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
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ messages, model, stream: true, session_id: sessionId, quote: quote ?? undefined, mode: mode || undefined, btw: btw || undefined, auto_consent: review || undefined }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status}`);
  }

  yield* parseSSE(res);
}

/** 重连一个仍在进行的生成：刷新页面后调此函数，回放缓冲 + 继续实时。
 *  无活跃 run 时后端返回 204，这里返回 null，调用方走普通 fetchSession。 */
export async function streamResume(sessionId: string): Promise<AsyncGenerator<StreamChunk> | null> {
  const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sessionId)}/stream`, {
    headers: headers(),
  });
  if (res.status === 204 || !res.ok) return null;
  return parseSSE(res);
}

/** 停止某 session 进行中的生成；已生成内容会被保存并标记 [已停止]。 */
export async function stopGeneration(sessionId: string): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return { ok: false, stopped: false };
  return res.json();
}
