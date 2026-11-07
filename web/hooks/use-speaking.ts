"use client";

/**
 * 阅读模式朗读：流式收 PCM → 直接喂给 Web Audio 播放，同时推算当前句做跟读高亮。
 *
 * 三个关键约束决定了这里的写法：
 *
 * 1. **流式 WAV 的头是假的**。服务端为了边生成边发，RIFF/data 的长度字段写的是
 *    0xFFFFFFFF（见 ethan-tts engine.stream_wav_header）。`decodeAudioData` 会把
 *    整个 buffer 当完整文件解析，流没结束就解不出来。所以这里自己剥 44 字节头，
 *    把后续 PCM16 分块推进 AudioContext —— 首包就能出声。
 * 2. **没有词级时间戳**。ethan-tts 只给音频。高亮用「按字数比例分摊已播时长」推算：
 *    整段切句后累计字符数，已播到第 k 个字就落在第几句。比按句均分准——长句自然
 *    占更长的时间；偏差主要来自句间停顿（估算把停顿也按字数摊掉了）。
 * 3. **暂停要能接上**。AudioContext.suspend() 停的是整个时钟，恢复后 currentTime
 *    从暂停处继续，所以已播时长（currentTime - startedAt）天然正确，不用额外补偿。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { speakStream } from "@/lib/api";

const SAMPLE_RATE = 24_000;
const WAV_HEADER_BYTES = 44;

export type SpeakState = "idle" | "connecting" | "playing" | "paused";

/**
 * 把正文切成朗读句（按句末标点，过长再按逗号拆，和 ethan-tts 的切句规则近似）。
 *
 * **跟读高亮必须用同一份实现**：markdown.tsx 也从这里导入。
 * 之前两处各写一份、高亮那份没做「过长再按逗号拆」，结果朗读切 5 段高亮只有 2 段，
 * 念到第 3 句还停在第 1 句上。
 */
export function splitSpeakSentences(text: string, maxLen = 40): string[] {
  const parts = text.split(/(?<=[。！？；!?;\n])/).filter((s) => s.trim());
  const out: string[] = [];
  for (const part of parts) {
    if (part.length <= maxLen) {
      out.push(part);
      continue;
    }
    for (const seg of part.split(/(?<=[，,、])/)) {
      if (seg.trim()) out.push(seg);
    }
  }
  return out.length ? out : [text];
}

export type UseSpeakingResult = {
  state: SpeakState;
  /** 当前朗读到第几句（对应 splitSpeakSentences 的索引），-1 表示还没开始 */
  currentSentence: number;
  error: string | null;
  /** 首包前的等待（冷启动要拉起服务 + 加载模型，实测 6–10 秒） */
  warmingUp: boolean;
  start: (text: string) => Promise<void>;
  pause: () => void;
  resume: () => void;
  stop: () => void;
};

type SentencePlan = { idx: number; startChar: number; chars: number };

export function useSpeaking(): UseSpeakingResult {
  const [state, setState] = useState<SpeakState>("idle");
  const [currentSentence, setCurrentSentence] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [warmingUp, setWarmingUp] = useState(false);

  const ctxRef = useRef<AudioContext | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const playheadRef = useRef(0); // 下一个 chunk 的调度时刻（AudioContext 时间轴）
  const startedAtRef = useRef(0); // 第一块音频的调度起点
  const sourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const planRef = useRef<SentencePlan[]>([]);
  const rafRef = useRef<number | null>(null);
  // 按「音频秒数」而不是 wall clock 推算进度：生成比播放慢时会出现空等，
  // 那段时间不该算进朗读进度。
  const lastTickAtRef = useRef(0);

  const teardown = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    for (const src of sourcesRef.current) {
      try {
        src.stop();
      } catch {
        /* 已经停过 */
      }
    }
    sourcesRef.current = [];
    playheadRef.current = 0;
    startedAtRef.current = 0;
    planRef.current = [];
    lastTickAtRef.current = 0;
    setCurrentSentence(-1);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    teardown();
    setState("idle");
    setWarmingUp(false);
  }, [teardown]);

  useEffect(() => () => stop(), [stop]);

  /**
   * 推算当前句：已播秒数 ÷ 总估算秒数 → 落在累计字数区间的哪一段。
   *
   * 总时长用「已调度到的时间轴上界」估算：playhead - startedAt 就是已生成音频的
   * 总长，流没结束时它还在增长，所以比例会随生成推进而收敛，不会一开始就跳到底。
   */
  const tick = useCallback(() => {
    const ctx = ctxRef.current;
    const plan = planRef.current;
    if (!ctx || plan.length === 0) {
      rafRef.current = requestAnimationFrame(tick);
      return;
    }
    const played = Math.max(0, ctx.currentTime - startedAtRef.current);
    const totalGenerated = Math.max(0.2, playheadRef.current - startedAtRef.current);
    const totalChars = plan[plan.length - 1].startChar + plan[plan.length - 1].chars;

    // 按比例把「已播秒数」换算成「已读字数」，再定位到句子
    const progressChars = Math.min(totalChars, (played / totalGenerated) * totalChars);
    let idx = plan[plan.length - 1].idx;
    for (const item of plan) {
      if (progressChars < item.startChar + item.chars) {
        idx = item.idx;
        break;
      }
    }
    setCurrentSentence((prev) => (prev === idx ? prev : idx));

    // 流已结束且播完：停止刷新（收尾由 start 里的定时器负责）
    if (played < totalGenerated) {
      rafRef.current = requestAnimationFrame(tick);
    } else {
      rafRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (text: string) => {
      stop();
      setError(null);
      setWarmingUp(true);
      setState("connecting");

      const sentences = splitSpeakSentences(text);
      let cursor = 0;
      planRef.current = sentences.map((s, idx) => {
        const chars = Math.max(1, s.trim().length);
        const plan = { idx, startChar: cursor, chars };
        cursor += chars;
        return plan;
      });

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const reader = await speakStream(text, "", controller.signal);
        setWarmingUp(false);

        const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
        ctxRef.current = ctx;
        await ctx.resume();
        playheadRef.current = ctx.currentTime + 0.05;
        startedAtRef.current = playheadRef.current;
        lastTickAtRef.current = ctx.currentTime;
        setState("playing");
        rafRef.current = requestAnimationFrame(tick);

        let headerSkipped = false;
        let tail: Uint8Array = new Uint8Array(0);

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!value?.length) continue;

          let bytes = value;
          if (!headerSkipped) {
            tail = concat(tail, bytes);
            if (tail.length < WAV_HEADER_BYTES) continue;
            bytes = tail.subarray(WAV_HEADER_BYTES);
            headerSkipped = true;
            tail = new Uint8Array(0);
          } else if (tail.length) {
            bytes = concat(tail, bytes);
            tail = new Uint8Array(0);
          }
          if (!bytes.length) continue;

          // PCM16 → 奇数字节留到下一块
          let usable = bytes;
          if (usable.length % 2 !== 0) {
            tail = usable.subarray(usable.length - 1);
            usable = usable.subarray(0, usable.length - 1);
          }
          if (!usable.length) continue;

          const frames = usable.length / 2;
          const buffer = ctx.createBuffer(1, frames, SAMPLE_RATE);
          const channel = buffer.getChannelData(0);
          const view = new DataView(usable.buffer, usable.byteOffset, usable.byteLength);
          for (let i = 0; i < frames; i++) {
            channel[i] = view.getInt16(i * 2, true) / 32768;
          }
          const src = ctx.createBufferSource();
          src.buffer = buffer;
          src.connect(ctx.destination);
          // 生成比播放快就往后续排，慢就贴着重排——总时长远短于整段音频，不会卡顿
          const when = Math.max(playheadRef.current, ctx.currentTime);
          src.start(when);
          sourcesRef.current.push(src);
          playheadRef.current = when + buffer.duration;

          if (!rafRef.current) rafRef.current = requestAnimationFrame(tick);
        }

        // 流结束：等最后一块播完再回 idle
        const remain = Math.max(0, playheadRef.current - ctx.currentTime);
        window.setTimeout(() => {
          if (!controller.signal.aborted) {
            teardown();
            setState("idle");
          }
        }, remain * 1000 + 150);
      } catch (err) {
        if (controller.signal.aborted) return; // 用户主动停止
        teardown();
        setState("idle");
        setWarmingUp(false);
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [stop, teardown, tick],
  );

  const pause = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx || state !== "playing") return;
    void ctx.suspend();
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    setState("paused");
  }, [state]);

  const resume = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx || state !== "paused") return;
    void ctx.resume();
    setState("playing");
    rafRef.current = requestAnimationFrame(tick);
  }, [state, tick]);

  return { state, currentSentence, error, warmingUp, start, pause, resume, stop };
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
}
