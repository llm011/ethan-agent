"use client";

/**
 * 设置页「语音」Tab（Web）。
 *
 * 与 desktop/src/components/settings/voice-tab.tsx 保持同步，差异仅在 API 导入路径。
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchVoiceBackends,
  selectVoiceBackend,
  setupVoiceBackend,
  type VoiceBackendsResponse,
} from "@/lib/api-tts";
import { VoiceSettings } from "@ethan/shared/components/voice-settings";

export function VoiceTab() {
  const [data, setData] = useState<VoiceBackendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchVoiceBackends());
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
    async (payload: { tts?: string; asr?: string }) => {
      setBusy(payload.tts || "asr");
      try {
        await selectVoiceBackend(payload);
        await load();
      } finally {
        setBusy("");
      }
    },
    [load],
  );

  const handleSetup = useCallback(async () => {
    setBusy("ethan-tts");
    try {
      await setupVoiceBackend("ethan-tts");
      await load();
    } finally {
      setBusy("");
    }
  }, [load]);

  return (
    <div className="space-y-6">
      <VoiceSettings
        data={data}
        loading={loading}
        busy={busy}
        onRefresh={load}
        onSelect={handleSelect}
        onSetup={handleSetup}
      />
    </div>
  );
}
