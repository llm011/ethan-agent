"use client";

/**
 * 设置页「AI 内核」Tab（Desktop）。
 *
 * 与 web/components/settings/kernel-tab.tsx 保持同步，差异仅在 API 导入路径。
 * 业务逻辑、文案、交互完全一致。
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchKernels,
  installKernel,
  selectKernel,
  setKernelTaskRules,
  type KernelInfo,
} from "@/lib/api-settings";
import { KernelSelector } from "@ethan/shared/components/kernel-selector";

export function KernelTab() {
  const [kernels, setKernels] = useState<KernelInfo[]>([]);
  const [current, setCurrent] = useState("ethan");
  const [taskRules, setTaskRules] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchKernels();
      setKernels(data.kernels);
      setCurrent(data.default);
      setTaskRules(data.task_rules || {});
    } catch (e) {
      console.error(e);
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

  return (
    <div className="space-y-6">
      <KernelSelector
        kernels={kernels}
        current={current}
        taskRules={taskRules}
        loading={loading}
        onSelect={handleSelect}
        onInstall={handleInstall}
        onSetTaskRules={handleTaskRules}
        onRefresh={load}
      />
    </div>
  );
}
