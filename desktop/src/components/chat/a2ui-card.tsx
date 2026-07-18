// A2UI 卡片渲染入口：用 React.lazy 懒加载真正的实现，
// 把 @a2ui 这坨依赖切到单独的 chunk，避免首屏加载过重。
import React, { Suspense } from "react";

const A2uiCardImpl = React.lazy(() => import("./a2ui-card-impl"));

interface A2uiCardProps {
  surfaces: unknown[];
  onAction?: (text: string) => void;
}

export function A2uiCard({ surfaces, onAction }: A2uiCardProps) {
  if (!surfaces || surfaces.length === 0) return null;
  return (
    <Suspense fallback={null}>
      <A2uiCardImpl surfaces={surfaces} onAction={onAction} />
    </Suspense>
  );
}
