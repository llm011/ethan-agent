const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8900";

let authToken = "";

export function setAuthToken(token: string) {
  authToken = token;
  if (typeof window !== "undefined") {
    localStorage.setItem("ethan_token", token);
  }
}

export function getAuthToken(): string {
  if (authToken) return authToken;
  if (typeof window !== "undefined") {
    authToken = localStorage.getItem("ethan_token") || "";
  }
  return authToken;
}

function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export async function verifyAuth(token: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/auth`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return res.ok;
}

export async function fetchModels(): Promise<{ id: string; description: string; alias: string[] }[]> {
  const res = await fetch(`${API_URL}/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  const data = await res.json();
  return data.models;
}

export interface SessionInfo {
  id: string;
  title: string;
  model: string;
  created_at: number;
  updated_at: number;
}

export interface SessionDetail {
  id: string;
  title: string;
  model: string;
  messages: { role: string; content: string }[];
}

export async function fetchSessions(limit = 50, q?: string): Promise<SessionInfo[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set("q", q);
  const res = await fetch(`${API_URL}/sessions?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await res.json();
  return data.sessions;
}

export async function renameSession(id: string, title: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ title }),
  });
}

export async function createSession(model?: string): Promise<{ id: string; title: string; model: string }> {
  const res = await fetch(`${API_URL}/sessions${model ? `?model=${model}` : ""}`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function fetchSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${API_URL}/sessions/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${id}`, { method: "DELETE", headers: headers() });
}

export async function uploadFile(file: File): Promise<{ path: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const h: HeadersInit = {};
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}/upload`, { method: "POST", headers: h, body: form });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
): AsyncGenerator<{ content?: string; done?: boolean; error?: string; model?: string; usage?: Record<string, number>; tool?: string; args?: string; state?: string }> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ messages, model, stream: true, session_id: sessionId }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status}`);
  }

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
