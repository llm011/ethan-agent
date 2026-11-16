"use client";

/**
 * 设置页「AI 内核」Tab（Web）。
 *
 * 与 desktop/src/components/settings/kernel-tab.tsx 保持同步，差异仅在 API 导入路径。
 * 业务逻辑、文案、交互完全一致。
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchKernels,
  installKernel,
  selectKernel,
  setKernelInjectContext,
  setKernelTaskRules,
  type KernelInfo,
  type KernelInjectContextMode,
} from "@/lib/api-settings";
import { KernelSelector } from "@ethan/shared/components/kernel-selector";

export function KernelTab() {
  const [kernels, setKernels] = useState<KernelInfo[]>([]);
  const [current, setCurrent] = useState("ethan");
  const [taskRules, setTaskRules] = useState<Record<string, string>>({});
  const [injectContext, setInjectContext] = useState<KernelInjectContextMode>("rules_profile");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await fetchKernels();
      setKernels(data.kernels);
      setCurrent(data.default);
      setTaskRules(data.task_rules || {});
      setInjectContext(data.inject_context || "rules_profile");
    } catch (e) {
      console.error(e);
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSelect = useCallback(
    async (kind: string) => {
      // selectKernel 内部会先确保依赖就绪；装不上会抛错，UI 展示原因
      const out = await selectKernel(kind);
      setCurrent(out.default);
      await load();
    },
    [load],
  );

  const handleInstall = useCallback(
    async (kind: string) => {
      await installKernel(kind);
      await load();
    },
    [load],
  );

  const handleTaskRules = useCallback(async (rules: Record<string, string>) => {
    const out = await setKernelTaskRules(rules);
    setTaskRules(out.task_rules || {});
  }, []);

  const handleInjectContext = useCallback(async (mode: KernelInjectContextMode) => {
    const out = await setKernelInjectContext(mode);
    setInjectContext(out.inject_context);
  }, []);

  return (
    <div className="space-y-6">
      <KernelSelector
        kernels={kernels}
        current={current}
        taskRules={taskRules}
        injectContext={injectContext}
        loading={loading}
        loadError={loadError}
        onSelect={handleSelect}
        onInstall={handleInstall}
        onSetTaskRules={handleTaskRules}
        onSetInjectContext={handleInjectContext}
        onRefresh={load}
      />
    </div>
  );
}
