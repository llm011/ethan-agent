"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";
const DOCS_BASE = process.env.NEXT_PUBLIC_DOCS_BASE || `${BASE_PATH}/docs-data`;

export default function PrivacyPolicyPage() {
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${DOCS_BASE}/privacy-policy.json`)
      .then((r) => r.json())
      .then((d) => setContent(d.content ?? ""))
      .catch(() => setContent("# Error\n\nFailed to load privacy policy."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-zinc-950">
        <p className="text-zinc-500">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 py-12 px-4">
      <article className="mx-auto max-w-3xl prose prose-zinc dark:prose-invert prose-headings:scroll-mt-20">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>
    </div>
  );
}
