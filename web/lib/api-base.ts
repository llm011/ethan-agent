/** 基础设施：API URL、认证、headers、通用接口（Models/Modes/Version）。 */

export const API_URL = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL
    : window.location.port === "3000"
      ? `${window.location.protocol}//127.0.0.1:8900/api`
      : `${window.location.origin}/api`)
  : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8900/api");

let authToken = "";

export function setAuthToken(token: string) {
  authToken = token;
  if (typeof window !== "undefined") {
    localStorage.setItem("ethan_token", token);
    document.cookie = `ethan_token=${encodeURIComponent(token)}; max-age=2592000; path=/`; // 30 days
  }
}

export function getAuthToken(): string {
  if (authToken) return authToken;
  if (typeof window !== "undefined") {
    authToken = localStorage.getItem("ethan_token") || "";
    if (!authToken) {
      const match = document.cookie.match(/(?:^|; )ethan_token=([^;]+)/);
      if (match) authToken = decodeURIComponent(match[1]);
    }
  }
  return authToken;
}

export function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

/** 构建 assets URL（图片等静态资源），自动处理跨域鉴权。
 * 生产模式同源，cookie 自动携带；开发模式跨端口，追加 ?token= query 参数。
 */
export function assetUrl(relativePath: string): string {
  const url = `${API_URL}/${relativePath}`;
  // 跨域时 cookie 不会自动发送，需要通过 query param 带 token
  if (typeof window !== "undefined") {
    try {
      const apiOrigin = new URL(API_URL).origin;
      if (apiOrigin !== window.location.origin) {
        const token = getAuthToken();
        if (token) return `${url}?token=${encodeURIComponent(token)}`;
      }
    } catch { /* malformed URL, skip */ }
  }
  return url;
}

/**
 * 带超时的 fetch。
 *
 * 浏览器对「连不上/半死」的 socket 不会很快报错，往往要等 OS 级 TCP 超时
 * （30s~2min）才 reject。服务端挂掉时，所有 REST 调用都会这样挂住——
 * 表现就是「点了菜单要等好久才出内容」，而加载态早就走完兜底定时器了，
 * 底下那个 fetch 其实还在悬着。
 *
 * 这里给每个请求加一个硬超时，超时即 abort 并抛错，让 UI 能尽快走到失败分支。
 *
 * 默认 15s：比 /health 的 3s 宽松得多（长任务类接口确实可能需要十几秒），
 * 但远小于 TCP 超时。调用方已自带 signal（如流式对话的中断）时不额外超时。
 */
export const DEFAULT_FETCH_TIMEOUT_MS = 15_000;

/** 触发后端跑完整轮 LLM 的接口的超时上限。
 *
 * 沉淀（structured consolidation）、做梦 insight、compact、summary、regen-title
 * 都要等一次真实模型调用返回，实测 20~60s 很常见。给它们远大于默认 15s 的上限，
 * 否则前端会在服务端仍正常执行时先 abort，报一个假的失败。
 */
export const LLM_TASK_TIMEOUT_MS = 10 * 60_000;

export async function fetchWithTimeout(
  input: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<Response> {
  const { timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, signal: external, ...rest } = init;

  // 调用方自带 signal（如流式对话的中断）时，两者要**同时**生效而不能二选一：
  // 早前这里是 `if (external) return fetch(...)`，等于把超时整个丢掉 —— 于是
  // 最需要超时的流式路径（后端挂掉时 socket 半死）反而会一直悬着。用
  // AbortSignal.any 组合，谁先触发都生效；兼容不支持 any 的旧环境。
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new Error("timeout")), timeoutMs);
  let signal: AbortSignal = ctrl.signal;
  if (external) {
    // AbortSignal.any 在部分 TS lib / 目标环境里没有类型与实现，做特性探测而非直调。
    const anyFn = (AbortSignal as unknown as {
      any?: (signals: AbortSignal[]) => AbortSignal;
    }).any;
    signal = typeof anyFn === "function"
      ? anyFn([external, ctrl.signal])
      : ctrl.signal;
  }

  try {
    return await fetch(input, { ...rest, signal });
  } catch (err) {
    // 外部主动中断优先按原样抛出（AbortError），交给调用方的 abort 分支处理；
    // 只有「不是外部中断、而我们自己超时了」才改写成超时错误。
    if (external?.aborted) throw err;
    if (ctrl.signal.aborted) {
      throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function verifyAuth(token: string): Promise<boolean> {
  const res = await fetchWithTimeout(`${API_URL}/auth`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return res.ok;
}

/** 响应浏览器清理确认卡片：action="close" 关闭 tab group，action="keep" 保留。 */
export async function respondBrowserCleanup(requestId: string, action: "close" | "keep"): Promise<{ ok: boolean }> {
  const res = await fetchWithTimeout(`${API_URL}/browser/cleanup/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return res.json();
}

export interface ModelEntry {
  id: string;
  provider: string;
  description: string;
  alias: string[];
  // null = 未声明图片能力（由后端按模型名判断，默认照发图片）
  vision: boolean | null;
}

export async function fetchModels(): Promise<ModelEntry[]> {
  const res = await fetchWithTimeout(`${API_URL}/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  const data = await res.json();
  return data.models;
}

export interface ModeEntry {
  key: string;
  label: string;
  icon: string;
  accent: string;
  blurb: string;
}

export async function fetchModes(): Promise<ModeEntry[]> {
  const res = await fetchWithTimeout(`${API_URL}/modes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch modes");
  const data = await res.json();
  return data.modes;
}

export async function addModel(m: ModelEntry): Promise<{ ok: boolean; error?: string }> {
  const res = await fetchWithTimeout(`${API_URL}/models`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(m),
  });
  return res.json();
}

export async function deleteModel(provider: string, modelId: string): Promise<{ ok: boolean; error?: string }> {
  // model id 可能含 "/"（如 trae/glm-5.3-flash），走 query 参数而不是路径段
  const params = new URLSearchParams({ provider, id: modelId });
  const res = await fetchWithTimeout(`${API_URL}/models?${params.toString()}`, {
    method: "DELETE", headers: headers(),
  });
  return res.json();
}

export async function addModelsBatch(models: ModelEntry[]): Promise<{ ok: boolean; added: number; skipped: { id: string; provider: string; reason: string }[]; error?: string }> {
  const res = await fetchWithTimeout(`${API_URL}/models/batch`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ models }),
  });
  return res.json();
}

export async function deleteModelsBatch(items: { provider: string; id: string }[]): Promise<{ ok: boolean; deleted: number; missing?: number; error?: string }> {
  const res = await fetchWithTimeout(`${API_URL}/models/delete-batch`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  return res.json();
}

export async function reorderModels(items: { provider: string; id: string }[]): Promise<{ ok: boolean; error?: string }> {
  const res = await fetchWithTimeout(`${API_URL}/models/reorder`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  return res.json();
}

export async function discoverModels(provider: string): Promise<{ ok: boolean; models?: (ModelEntry & { exists?: boolean })[]; error?: string; url?: string }> {
  const res = await fetchWithTimeout(`${API_URL}/models/discover`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
  return res.json();
}

export async function respondConsent(requestId: string, allowed: boolean, message?: string): Promise<{ ok: boolean }> {
  const res = await fetchWithTimeout(`${API_URL}/consent/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ allowed, message: message || "" }),
  });
  return res.json();
}

export async function respondAskUser(requestId: string, value: string): Promise<{ ok: boolean }> {
  const res = await fetchWithTimeout(`${API_URL}/ask-user/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  return res.json();
}

/** 响应 wait_for_user 等待卡片：POST 用户的确认/取消/文本输入。 */
export async function respondWaitForUser(requestId: string, value: string): Promise<{ ok: boolean }> {
  const res = await fetchWithTimeout(`${API_URL}/wait-for-user/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed (${res.status})`);
  }
  return res.json();
}

/** Tool UI resources: 按 ui:// URI 获取工具 UI 模板 HTML（前端缓存，模板只拉一次）。 */
export async function fetchUiResource(uri: string): Promise<{ text: string; _meta?: unknown }> {
  const res = await fetchWithTimeout(`${API_URL}/ui-resources/read?uri=${encodeURIComponent(uri)}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error(`Failed to fetch UI resource: ${uri}`);
  return res.json();
}

/** 获取后端 health 信息（版本号 + agent_name，来自 /health 端点）。
 * 左上角标题用 agent_name 显示用户设置的 agent 名（见 config.defaults.agent_name）。
 */
export interface ServerHealthInfo {
  version: string | null;
  agent_name: string | null;
}
export async function fetchHealth(): Promise<ServerHealthInfo> {
  try {
    const res = await fetchWithTimeout(`${API_URL}/health`);
    const data = await res.json();
    return { version: data.version ?? null, agent_name: data.agent_name ?? null };
  } catch {
    return { version: null, agent_name: null };
  }
}

/** 获取后端版本号（与 PyPI 版本一致，来自 ethan.__version__）。
 * 与桌面端保持同名同签名，供 /version 命令使用。 */
export async function fetchVersion(): Promise<string | null> {
  const info = await fetchHealth();
  return info.version;
}
