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

  return <SettingsView models={models} />;
}
