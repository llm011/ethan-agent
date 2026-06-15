import { DocsView } from "@/components/docs-view";

export default async function DocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <DocsView initialSlug={slug} />;
}
