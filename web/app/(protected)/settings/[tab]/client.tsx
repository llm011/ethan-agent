"use client";

import { useEffect, useState } from "react";
import { SettingsView } from "@/components/settings-view";
import { fetchModels } from "@/lib/api";

const VALID_TABS = ["general", "providers", "channels", "identity", "soul", "tools", "heartbeat", "profile", "prompt-preview", "api-keys"];

export default function SettingsTabClient({ tab }: { tab: string }) {
  const [models, setModels] = useState<{ id: string; description: string }[]>([]);

  useEffect(() => {
    fetchModels().then(setModels).catch(() => {});
  }, []);

  const initialTab = VALID_TABS.includes(tab) ? tab : "general";

  return (
    <div className="flex flex-col flex-1 h-full min-h-0">
      <SettingsView models={models} initialTab={initialTab as any} />
    </div>
  );
}
