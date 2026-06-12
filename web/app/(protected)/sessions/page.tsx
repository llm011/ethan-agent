"use client";

import { useRouter } from "next/navigation";
import { AllSessionsView } from "@/components/all-sessions-view";

export default function SessionsPage() {
  const router = useRouter();
  return (
    <AllSessionsView onSelectSession={(id) => router.push(`/chat/${id}`)} />
  );
}
