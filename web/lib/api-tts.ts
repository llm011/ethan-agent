/** 阅读模式朗读：把正文交给本机 ethan-tts 流式合成。 */

import { API_URL, headers } from "./api-base";

export type TtsStatus = {
  installed: boolean;
  running: boolean;
  command: string;
  voice: string;
};

/** 探测本地语音后端是否可用。不触发拉起，切到阅读模式时调一次即可。 */
export async function fetchTtsStatus(): Promise<TtsStatus> {
  const res = await fetch(`${API_URL}/tts/status`, { headers: headers() });
  if (!res.ok) throw new Error(`TTS 状态查询失败：${res.status}`);
  return res.json();
}

/**
 * 请求流式朗读，返回原始 WAV 字节流。
 *
 * 不解析、不缓存——调用方负责边收边喂给播放器。注意：HTTP 状态码在首块 body
 * 发出时就定了，服务端中途出错只能靠流提前结束体现，所以播放端要自己判断
 * 「播完了」还是「断了」。
 */
export async function speakStream(
  text: string,
  voice: string,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const res = await fetch(`${API_URL}/tts/speak`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ text, voice }),
    signal,
  });
  if (!res.ok) {
    let detail = `朗读失败：${res.status}`;
    try {
      const payload = await res.json();
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* 非 JSON 错误体，用状态码兜底 */
    }
    throw new Error(detail);
  }
  if (!res.body) throw new Error("朗读失败：响应没有音频流");
  return res.body.getReader();
}


// ── 语音后端管理（TTS / ASR 可配置）──────────────────────────────
//
// 关键语义：本地后端（ethan-tts）依赖 Apple Silicon + MLX，不是所有机器都能跑。
// 所以 UI 必须先看 available，不能假设「选了就能用」。

export type VoiceCheck = {
  name: string;
  status: "ok" | "error" | "warn";
  detail: string;
  fix: string;
};

export type VoiceBackend = {
  backend: string;
  available: boolean;
  reason: string;
  cli_path: string;
  service_url: string;
  service_running: boolean;
  checks: VoiceCheck[];
};

export type VoiceBackendsResponse = {
  tts: Record<string, VoiceBackend>;
  asr: VoiceBackend;
  platform: { system: string; machine: string; apple_silicon: boolean };
  python: string;
  current: { tts: string; asr: string };
};

/** 列出所有语音后端及可用性。只读探测，不安装。 */
export async function fetchVoiceBackends(): Promise<VoiceBackendsResponse> {
  const res = await fetch(`${API_URL}/tts/backends`, { headers: headers() });
  if (!res.ok) throw new Error(`语音后端查询失败：${res.status}`);
  return res.json();
}

export type VoiceSetupResult = {
  backend: string;
  ok: boolean;
  installing: boolean;
  message: string;
  checks: VoiceCheck[];
  started_at: string;
};

/**
 * 一键配置本地语音后端。
 *
 * 后端会先做系统预检；不满足条件直接返回 409 并给出原因，**不会**开始下载。
 * 我们把 reason 原样透给用户——这比「配置失败」有用得多。
 */
export async function setupVoiceBackend(backend = "ethan-tts"): Promise<VoiceSetupResult> {
  const res = await fetch(`${API_URL}/tts/setup`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ backend, auto_start: true }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body?.detail ?? body?.message ?? "配置失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

/** 轮询一次配置进度。 */
export async function fetchVoiceSetupStatus(): Promise<VoiceSetupResult> {
  const res = await fetch(`${API_URL}/tts/setup/status`, { headers: headers() });
  if (!res.ok) throw new Error("查询失败");
  return res.json();
}

/** 切换 TTS / ASR 后端。后端会先校验可用性，不可用则 409 且不改配置。 */
export async function selectVoiceBackend(payload: {
  tts?: string;
  asr?: string;
}): Promise<{ ok: boolean; tts: string; asr: string }> {
  const res = await fetch(`${API_URL}/tts/select`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const d = body?.detail;
    const msg = typeof d === "string" ? d : d?.message || "切换失败";
    const reason = typeof d === "object" ? d?.reason : "";
    throw new Error(reason ? `${msg}：${reason}` : msg);
  }
  return res.json();
}
