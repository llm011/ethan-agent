import { Suspense } from "react";
import { PptPreviewViewWeb } from "@/components/ppt-preview-view";

export default function PptPreviewPage() {
  return (
    <Suspense fallback={null}>
      <PptPreviewViewWeb />
    </Suspense>
  );
}
