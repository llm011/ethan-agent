"use client";

import { usePathname } from "next/navigation";
import { ChatView } from "@/components/chat-view";

export default function ChatSessionClient() {
  const pathname = usePathname();
  // Read directly from URL — avoids hydration race where useParams()
  // briefly returns "__placeholder__" before router catches up.
  const id = pathname?.split("/").filter(Boolean).pop() ?? "";
  return <ChatView initialSessionId={id || undefined} />;
}
