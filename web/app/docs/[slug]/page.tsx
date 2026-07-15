import DocPageClient from "./client";
import { DOC_NAV } from "@/lib/docs-nav";

export function generateStaticParams() {
  const slugs = DOC_NAV.flatMap(g => g.items.map(i => ({ slug: i.slug })));
  // 加一个占位，确保动态路由在 export 模式下正常工作
  slugs.push({ slug: "__placeholder__" });
  return slugs;
}

export default function DocPage() {
  return <DocPageClient />;
}
