import React from "react";
import {continueRender, delayRender, interpolate, spring, useCurrentFrame, useVideoConfig} from "@open-motion/core";
import type {Caption, Presenter, PresenterLayout, Scene} from "../types";
import {PRESENTER_BOTTOM_PX} from "../types";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

// 场景的有效姿势 = 场景覆盖 ?? 角色默认姿势（与 pipeline 的解析规则一致）。
const effectivePose = (scene: Scene | undefined, presenter: Presenter): string =>
  scene?.presenter?.pose ?? presenter.defaultPose;

// ── 确定性伪随机 ──
// 渲染器逐帧截图且分批并行，Math.random() 会让同一帧在不同 worker 上结果不同
// （眨眼在帧 N 出现在 worker A、消失在 worker B）。所有节律必须由整数 hash
// 驱动：同 seed 同值，跨帧跨 worker 可复现。
const hash32 = (seed: number): number => {
  let h = seed | 0;
  h = Math.imul(h ^ (h >>> 16), 0x7feb352d);
  h = Math.imul(h ^ (h >>> 15), 0x846ca68b);
  h ^= h >>> 16;
  return h >>> 0;
};
const rand01 = (seed: number): number => hash32(seed) / 0xffffffff;

// 眨眼节律：间隔 2.2–5.5s 伪随机、单次眨眼窗 140ms。光标从 0 推进到当前
// 时间，每帧 O(眨眼序号)，60s 视频约 15 次眨眼，成本可忽略。
const BLINK_GAP_MIN_MS = 2200;
const BLINK_GAP_MAX_MS = 5500;
const BLINK_DURATION_MS = 140;

const blinkActiveAt = (ms: number): boolean => {
  let cursor = 0;
  let index = 0;
  while (cursor <= ms) {
    const gap = BLINK_GAP_MIN_MS + rand01(hash32(index * 2654435761)) * (BLINK_GAP_MAX_MS - BLINK_GAP_MIN_MS);
    if (ms < cursor + gap) return false;
    if (ms < cursor + gap + BLINK_DURATION_MS) return true;
    cursor += gap + BLINK_DURATION_MS;
    index++;
  }
  return false;
};

// 说话口型：captions 有活跃字幕即视为说话；开合以 ~110ms 拍的伪随机方波
// 驱动（约 55% 时间张嘴），节律不机械。字幕间隙自动闭嘴。
const TALK_BEAT_MS = 110;

const talkOpenAt = (ms: number, speaking: boolean): boolean => {
  if (!speaking) return false;
  const beat = Math.floor(ms / TALK_BEAT_MS);
  return rand01(hash32(beat * 40503 + 7)) > 0.45;
};

// 虚拟人立绘层：挂在组合根上（不进 Sequence），呼吸浮动跨场景连续。
// 所有动画都是绝对帧的纯函数（时间劫持下 CSS transition/animation 不可控，禁用）。
export const PresenterLayer: React.FC<{
  presenter: Presenter;
  scenes: Scene[];
  captions: Caption[];
  layout: PresenterLayout;
}> = ({presenter, scenes, captions, layout}) => {
  const frame = useCurrentFrame(); // 根组件上 = 绝对帧
  const {fps} = useVideoConfig();
  const [ready, setReady] = React.useState(false);

  // 预加载所有姿势图和变体图，避免姿势切换帧白闪；失败也放行（不阻塞渲染）。
  React.useEffect(() => {
    const handle = delayRender("presenter images preload");
    let cancelled = false;
    const sources = [
      ...Object.values(presenter.poses),
      ...Object.values(presenter.variants ?? {}).flatMap((entry) => Object.values(entry)),
    ];
    Promise.all(
      sources.map(
        (src) =>
          new Promise<void>((resolve) => {
            const img = new Image();
            img.onload = img.onerror = () => resolve();
            img.src = `/${src}`;
          }),
      ),
    ).then(() => {
      if (!cancelled) {
        setReady(true);
        continueRender(handle);
      }
    });
    return () => {
      cancelled = true;
      // 卸载时必须无条件释放 handle：只设 cancelled 会让 then 分支跳过 continueRender，
      // delayRender 计数永久 ≥1，渲染挂死到超时。重复调用 continueRender 只递减计数，安全。
      continueRender(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentMs = (frame / fps) * 1000;
  const index = scenes.findIndex((s) => currentMs >= s.startMs && currentMs < s.startMs + s.durationMs);
  const scene = index >= 0 ? scenes[index] : undefined;
  const visible = Boolean(scene) && scene!.presenter?.visible !== false;

  const pose = effectivePose(scene, presenter);
  const prevPose = index > 0 ? effectivePose(scenes[index - 1], presenter) : pose;
  const sceneStartFrame = scene ? Math.round((scene.startMs / 1000) * fps) : 0;
  const localFrame = Math.max(0, frame - sceneStartFrame);
  const enter = spring({frame: localFrame, fps, config: {damping: 18, stiffness: 110}});
  // 姿势只在场景边界切换：从前一场景姿势 6 帧交叉淡化，worker 分批也不影响确定性。
  const crossfade = prevPose !== pose ? interpolate(localFrame, [0, 6], [0, 1], clamp) : 1;
  // 复合呼吸浮动：主起伏 + 慢漂移双频叠加，再加 ±0.6° 微摆（绕底部锚点，
  // 脚底不飘），消除单频 sin 的"贴图感"。
  const bob = Math.sin(frame / 16) * 4 + Math.sin(frame / 29 + 1.7) * 2.2;
  const sway = Math.sin(frame / 37 + 0.5) * 0.6;

  if (presenter.forceHidden || !ready || !visible) {
    return null;
  }

  // 面部变体调度：眨眼优先于口型（闭眼帧只有 4-5 帧，嘴型状态不可见）。
  // 变体是渐进增强的：某姿势缺 blink/talk 图时自动落回基础姿势图。
  const variants = presenter.variants?.[pose] ?? {};
  const speaking = captions.some((item) => currentMs >= item.startMs && currentMs < item.endMs);
  const variantImageAt = (ms: number): string => {
    if (blinkActiveAt(ms) && variants.blink) return variants.blink;
    if (talkOpenAt(ms, speaking) && variants.talk) return variants.talk;
    return presenter.poses[pose];
  };
  const currentImage = variantImageAt(currentMs);
  // 变体切换短交叉淡化：同一设定集切出的面板经 SSD 对齐后仍有 1px 级残差，
  // 整图硬切会沿轮廓边缘闪一下；2 帧淡化把硬闪压成不可察觉的柔切。回溯最近
  // 一次变体变化（纯函数，跨 worker 确定性），变化发生在 back 帧前 → 新图
  // 权重 back/(L+1)，超出回溯窗口视为淡化已完成。
  const VARIANT_FADE_FRAMES = 2;
  let fadeFrom: string | null = null;
  let fadeProgress = 1;
  for (let back = 1; back <= VARIANT_FADE_FRAMES; back++) {
    const prev = variantImageAt(((frame - back) / fps) * 1000);
    if (prev !== currentImage) {
      fadeFrom = prev;
      fadeProgress = back / (VARIANT_FADE_FRAMES + 1);
      break;
    }
  }
  const pickImage = (poseName: string): string =>
    poseName === pose ? currentImage : presenter.poses[poseName];

  const side = presenter.position === "left" ? {left: layout.presenterEdgeInset} : {right: layout.presenterEdgeInset};
  // 硬车道：宽被钳在 layout.presenterLaneWidth（外层 transform scale 同步放大车道），
  // img 双轴 contain —— 任何宽高比的姿势图都不可能溢出车道，内容侧按同宽收 padding。
  const imgStyle = (opacity: number): React.CSSProperties => ({
    position: "absolute",
    bottom: 0,
    ...(presenter.position === "left" ? {left: 0} : {right: 0}),
    width: "100%",
    height: "100%",
    objectFit: "contain",
    objectPosition: "bottom",
    opacity,
    // 未抠图的立绘用圆角卡片框降级（cutout=false）
    ...(presenter.cutout
      ? {filter: "drop-shadow(0 24px 60px rgba(0,0,0,0.45))"}
      : {borderRadius: 36, border: "2px solid rgba(255,255,255,0.16)", boxShadow: "0 24px 60px rgba(0,0,0,0.45)"}),
  });

  return (
    <div
      style={{
        position: "absolute",
        bottom: PRESENTER_BOTTOM_PX, // 避开底部字幕区（字幕 bottom + 最小高 + 留白，见 types.ts）
        width: layout.presenterLaneWidth,
        height: "46%",
        zIndex: 5,
        ...side,
        opacity: enter,
        transform: `translateX(${(1 - enter) * (presenter.position === "left" ? -120 : 120)}px) translateY(${bob}px) rotate(${sway}deg) scale(${presenter.scale})`,
        transformOrigin: presenter.position === "left" ? "bottom left" : "bottom right",
      }}
    >
      {prevPose !== pose ? <img src={`/${pickImage(prevPose)}`} style={imgStyle(1 - crossfade)} alt="" /> : null}
      {fadeFrom ? <img src={`/${fadeFrom}`} style={imgStyle(crossfade * (1 - fadeProgress))} alt="" /> : null}
      <img src={`/${currentImage}`} style={imgStyle(crossfade * fadeProgress)} alt="" />
    </div>
  );
};
