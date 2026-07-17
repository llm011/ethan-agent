/** Chat streaming 相关类型和 API。 */

import { getApiUrl, headers } from "./api-base";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: number;
  images?: { data: string; media_type: string }[];
}

export type StreamChunk = {
  content?: string;
  done?: boolean;
  stopped?: boolean;
  error?: string;
  model?: string;
  usage?: Record<string, number>;
  ttfb_ms?: number;
  total_ms?: number;
  message_id?: number;
  title?: string;
  tool?: string;
  args?: string;
  intent?: string;
  state?: string;
  id?: string;
  duration_ms?: number;
  result_preview?: string;
  result_detail?: string;
  entity_type?: string;
  entity_id?: string;
  sub_steps?: Array<{ tool: string; args: string; state: string; duration_ms?: number | null; result_preview?: string }>;
  ui?: unknown[];
  mcp_app?: { uri: string; data?: Record<string, unknown>; html?: string };
  consent_request?: boolean;
  request_id?: string;
  description?: string;
  detail?: string;
  thinking?: boolean;
  heartbeat?: boolean;
  elapsed?: number;
  skills_matched?: Array<{ name: string; is_default?: boolean }>;
  background_polling?: boolean;
  polling_message?: string;
  new_message?: boolean;
};

/** 把一个 SSE Response body 解析成事件流 */
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
        } catch { /* skip malformed */ }
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
  },
): AsyncGenerator<StreamChunk> {
  const { quote = null, mode = "" } = options ?? {};
  const res = await fetch(`${getApiUrl()}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      messages,
      model,
      stream: true,
      session_id: sessionId,
      quote: quote ?? undefined,
      mode: mode || undefined,
    }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status}`);
  }

  yield* parseSSE(res);
}

/** 重连一个仍在进行的生成 */
export async function streamResume(sessionId: string): Promise<AsyncGenerator<StreamChunk> | null> {
  const res = await fetch(`${getApiUrl()}/chat/${encodeURIComponent(sessionId)}/stream`, {
    headers: headers(),
  });
  if (res.status === 204 || !res.ok) return null;
  return parseSSE(res);
}

/** 停止生成 */
export async function stopGeneration(sessionId: string): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(`${getApiUrl()}/chat/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return { ok: false, stopped: false };
  return res.json();
}
