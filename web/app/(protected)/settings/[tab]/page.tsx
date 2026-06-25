import SettingsTabClient from "./client";

const VALID_TABS = ["general", "providers", "channels", "identity", "soul", "tools", "heartbeat", "profile", "prompt-preview", "api-keys"];

export function generateStaticParams() {
  return VALID_TABS.map(tab => ({ tab }));
}

export default async function SettingsTabPage({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  return <SettingsTabClient tab={tab} />;
}
