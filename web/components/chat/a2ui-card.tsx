"use client";

// A2UI 卡片渲染入口：用 next/dynamic ssr:false 懒加载真正的实现，
// 避免 @a2ui 在 SSR 阶段触碰 window/DOM，也把这坨依赖切到单独的客户端 bundle。

import dynamic from "next/dynamic";

const A2uiCardImpl = dynamic(() => import("./a2ui-card-impl"), { ssr: false });

interface A2uiCardProps {
  surfaces: unknown[];
  onAction?: (text: string) => void;
}

export function A2uiCard({ surfaces, onAction }: A2uiCardProps) {
  if (!surfaces || surfaces.length === 0) return null;
  return <A2uiCardImpl surfaces={surfaces} onAction={onAction} />;
}
