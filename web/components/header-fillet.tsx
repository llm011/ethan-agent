"use client";

import { useSidebar } from "@/app/layout-shell";

/**
 * 顶部 header 与左侧边栏交界处的外凸圆弧过渡。
 *
 * 布局背景：sidebar 是左侧整列（bg-sidebar + border-r），header 是 main 顶部条。
 * P 点 = sidebar 右边框 × header 底线的交界处。
 *
 * 视觉目标：
 *   1. header 与 sidebar 同色融合（header 高度内不出现 sidebar 的竖线）；
 *   2. header 底线在 P 点处不直角拐弯，而是经一段圆弧平滑弯向下方的 sidebar 右边框，
 *      圆弧凸向左上方（半径 12px，圆心在 P 点右下方 12px 处）。
 *
 * 实现原理（三个关键点）：
 *   - 融合块：header 左侧 12px 宽、向下延伸 13px 的 bg-sidebar 方块，
 *     盖住 sidebar border-r 的 header 区段与圆弧区段，并为圆弧左上侧提供 sidebar 底色；
 *     同时盖住 header border-b 的左端 12px，让底线从圆弧起点处开始。
 *   - 圆弧盘：rounded-tl-full 的 12×12 方块（-left-px + top-full）。
 *     border-radius 会把背景裁剪成"圆心在右下角的四分之一圆盘"：盘内（圆弧右下）
 *     显示内容区背景色，盘外（圆弧左上月牙）透明露出融合块的 sidebar 色；
 *     border-l + border-t 沿圆角弯曲，正是那条可见的弧线。
 *   - 对齐细节：top-full（top:100%）相对 header 的 padding box，即方块顶边恰好与
 *     border-b 完全重叠；-left-px 让 border-l 与 sidebar 的 border-r 完全重叠。
 *
 * 前置条件：
 *   - 使用此组件的 header 必须有 `relative bg-sidebar border-b border-border`；
 *   - main 不能有 overflow-hidden（本组件需要向左溢出 1px 盖住 sidebar 的 border-r）。
 *
 * 仅在桌面端 sidebar 展开时显示。
 */
export function HeaderFillet() {
  const { sidebarOpen } = useSidebar();
  if (!sidebarOpen) return null;

  return (
    <>
      {/* 融合块：盖住 sidebar 竖线（header 区段 + 圆弧区段）与 header 底线左端，
          并为圆弧左上侧提供 sidebar 底色。100% = header padding box 高度，+13px 延伸到圆弧底部。 */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-px top-0 h-[calc(100%+13px)] w-3 bg-sidebar max-md:hidden"
      />
      {/* 外凸圆弧盘：从 header 底线平滑弯向下方 sidebar 右边框 */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-px top-full h-3 w-3 rounded-tl-full border-l border-t border-border bg-background max-md:hidden"
      />
    </>
  );
}
