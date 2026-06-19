import DocPageClient from "./client";

export function generateStaticParams() {
  return [{ slug: "__placeholder__" }];
}

export default function DocPage() {
  return <DocPageClient />;
}
