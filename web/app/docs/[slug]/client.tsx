"use client";

import { useParams } from "next/navigation";
import { DocsView } from "@/components/docs-view";

export default function DocPageClient() {
  const params = useParams();
  const slug = params?.slug as string;
  return <DocsView initialSlug={slug} />;
}
