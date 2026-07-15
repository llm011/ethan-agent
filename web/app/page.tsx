import { redirect } from "next/navigation";

export default function Home() {
  // GitHub Pages 静态部署时无后端，直接进文档页
  const target = process.env.NEXT_PUBLIC_DOCS_BASE ? "/docs" : "/chat";
  redirect(target);
}
