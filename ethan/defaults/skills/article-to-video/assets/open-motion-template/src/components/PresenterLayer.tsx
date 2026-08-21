import React from "react";
import {continueRender, delayRender, interpolate, spring, useCurrentFrame, useVideoConfig} from "@open-motion/core";
import type {Presenter, PresenterLayout, Scene} from "../types";
import {PRESENTER_BOTTOM_PX} from "../types";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

// 场景的有效姿势 = 场景覆盖 ?? 角色默认姿势（与 pipeline 的解析规则一致）。
const effectivePose = (scene: Scene | undefined, presenter: Presenter): string =>
  scene?.presenter?.pose ?? presenter.defaultPose;

// 虚拟人立绘层：挂在组合根上（不进 Sequence），呼吸浮动跨场景连续。
// 所有动画都是绝对帧的纯函数（时间劫持下 CSS transition/animation 不可控，禁用）。
export const PresenterLayer: React.FC<{presenter: Presenter; scenes: Scene[]; layout: PresenterLayout}> = ({presenter, scenes, layout}) => {
  const frame = useCurrentFrame(); // 根组件上 = 绝对帧
  const {fps} = useVideoConfig();
  const [ready, setReady] = React.useState(false);

  // 预加载所有姿势图，避免姿势切换帧白闪；失败也放行（不阻塞渲染）。
  React.useEffect(() => {
    const handle = delayRender("presenter images preload");
    let cancelled = false;
    Promise.all(
      Object.values(presenter.poses).map(
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
  const bob = Math.sin(frame / 16) * 5;

  if (presenter.forceHidden || !ready || !visible) {
    return null;
  }

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
        transform: `translateX(${(1 - enter) * (presenter.position === "left" ? -120 : 120)}px) translateY(${bob}px) scale(${presenter.scale})`,
        transformOrigin: presenter.position === "left" ? "bottom left" : "bottom right",
      }}
    >
      {prevPose !== pose ? <img src={`/${presenter.poses[prevPose]}`} style={imgStyle(1 - crossfade)} alt="" /> : null}
      <img src={`/${presenter.poses[pose]}`} style={imgStyle(crossfade)} alt="" />
    </div>
  );
};
