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
