
// A2UI 卡片渲染：把 ui_card 工具产出的 A2UI v0.9.1 envelope 用官方 @a2ui/react 渲染。
// 仅客户端运行（用 next/dynamic ssr:false 加载本组件，见 a2ui-card.tsx 包装器）。

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { MessageProcessor, type SurfaceModel } from "@a2ui/web_core/v0_9";
import {
  basicCatalog,
  A2uiSurface,
  MarkdownContext,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import { renderMarkdown } from "@a2ui/markdown-it";
import { shadcnCatalog } from "./a2ui-catalog";

interface A2uiCardImplProps {
  surfaces: unknown[];
  onAction?: (text: string) => void;
}

export default function A2uiCardImpl({ surfaces: envelopes, onAction }: A2uiCardImplProps) {
  const [processor, setProcessor] = useState<MessageProcessor<ReactComponentImplementation> | null>(null);
  const [surfaceIds, setSurfaceIds] = useState<string[]>([]);

  // 保持对最新 onAction 的引用：useEffect 依赖项为 [envelopes]，若直接闭包捕获 onAction，
  // 父组件传入新函数引用时 processor 仍会调用旧闭包。通过 ref 始终拿到最新值。
  const onActionRef = useRef(onAction);
  onActionRef.current = onAction;

  useEffect(() => {
    const proc = new MessageProcessor<ReactComponentImplementation>(
      [shadcnCatalog],
      async (action) => {
        // 按钮等交互：把 action 转成一句自然语言，作为新一轮用户消息发回 agent。
        const fn = onActionRef.current;
        if (!fn) return;
        const ctx = action.context && Object.keys(action.context).length
          ? ` ${JSON.stringify(action.context)}`
          : "";
        fn(`[卡片操作] ${action.name}${ctx}`);
      },
    );
    try {
      // 归一化 catalogId：LLM 可能写 v0_9_1 等版本，但 bundled basicCatalog 的 id 固定。
      // processor 按 catalogId 精确匹配，不归一会报 "Catalog not found"。
      const msgs = structuredClone(envelopes) as Array<Record<string, unknown>>;
      for (const m of msgs) {
        const cs = m?.createSurface as { catalogId?: string } | undefined;
        if (cs && typeof cs === "object") cs.catalogId = basicCatalog.id;
      }
      proc.processMessages(msgs as unknown as Parameters<typeof proc.processMessages>[0]);
    } catch (e) {
      console.error("A2UI processMessages failed", e);
    }
    setProcessor(proc);
    setSurfaceIds(Array.from(proc.model.surfacesMap.values()).map((s) => s.id));
    return () => proc.model.dispose();
  // envelopes 是消息固有内容，引用稳定即可；用 JSON 长度+首条 surfaceId 做粗粒度依赖
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [envelopes]);

  if (!processor || surfaceIds.length === 0) return null;

  return (
    <MarkdownContext.Provider value={renderMarkdown}>
      <div className="a2ui-cards mt-2 flex flex-col gap-3">
        {surfaceIds.map((id) => {
          const surface = processor.model.getSurface(id);
          if (!surface) return null;
          return <SurfaceBox key={id} surface={surface} />;
        })}
      </div>
    </MarkdownContext.Provider>
  );
}

// 单个 surface 容器：订阅 surface 上的组件变化触发重渲染。
function SurfaceBox({ surface }: { surface: SurfaceModel<ReactComponentImplementation> }) {
  const subscribe = useMemo(
    () => (cb: () => void) => {
      const u1 = surface.componentsModel.onCreated.subscribe(cb);
      const u2 = surface.componentsModel.onDeleted.subscribe(cb);
      return () => {
        u1.unsubscribe();
        u2.unsubscribe();
      };
    },
    [surface],
  );
  useSyncExternalStore(subscribe, () => surface.componentsModel.get("root") ? "ready" : "empty", () => "empty");

  return (
    <div className="a2ui-surface">
      <A2uiSurface surface={surface} />
    </div>
  );
}
