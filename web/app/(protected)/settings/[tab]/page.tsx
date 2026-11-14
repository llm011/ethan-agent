import SettingsTabClient from "./client";

// 静态导出（output: "export"）只会为这里列出的 tab 生成页面。
// 新增 Tab 必须同步这里，否则 /settings/<new> 根本没有产物——表现为
// 点进去 404 或被打回默认页（实测踩到：加了「AI 内核」「语音」两个 Tab，
// 但漏了这行，用户点内核设置直接被跳回 chat）。
// ⚠️ 与 components/settings-view.tsx 的 TabId 联合类型保持同步。
const VALID_TABS = ["general", "data", "fast-rules", "providers", "channels", "plugins", "identity", "soul", "tools", "heartbeat", "profile", "prompt-preview", "api-keys", "tool-tiers", "kernel", "voice", "naming", "about"];

export function generateStaticParams() {
  return VALID_TABS.map(tab => ({ tab }));
}

export default async function SettingsTabPage({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  return <SettingsTabClient tab={tab} />;
}
