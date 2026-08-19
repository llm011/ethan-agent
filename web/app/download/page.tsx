import type { Metadata } from "next";
import DownloadClient from "./client";

export const metadata: Metadata = {
  title: "下载 · Ethan Agent",
  description:
    "下载 Ethan Agent 桌面端（macOS / Windows），或在服务器上用 pip / Docker 部署你的个人 AI Agent。",
};

export default function DownloadPage() {
  return <DownloadClient />;
}
