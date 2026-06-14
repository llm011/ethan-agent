import { DocsView } from "@/components/docs-view";

export default function DocPage({ params }: { params: { slug: string } }) {
  return <DocsView initialSlug={params.slug} />;
}
