"use client";

import { useEffect, useState } from "react";
import { SettingsView } from "@/components/settings-view";
import { fetchModels } from "@/lib/api";

export default function SettingsPage() {
  const [models, setModels] = useState<{ id: string; description: string }[]>([]);

  useEffect(() => {
    fetchModels()
      .then(setModels)
      .catch(() => {});
  }, []);

  return (
    <div className="flex flex-col flex-1 h-full min-h-0">
      <SettingsView models={models} />
    </div>
  );
}
