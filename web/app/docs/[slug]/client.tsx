"use client";

import { usePathname } from "next/navigation";
import { DocsView } from "@/components/docs-view";

export default function DocPageClient() {
  const pathname = usePathname();
  // Read directly from URL to avoid hydration race where useParams()
  // briefly returns "__placeholder__" before router catches up.
  const slug = pathname?.split("/").filter(Boolean).pop() ?? "";
  return <DocsView initialSlug={slug || undefined} />;
}
