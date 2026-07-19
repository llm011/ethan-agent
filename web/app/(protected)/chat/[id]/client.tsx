"use client";

import { usePathname } from "next/navigation";
import { ChatView } from "@/components/chat-view";

export default function ChatSessionClient() {
  const pathname = usePathname();
  // Read directly from URL — avoids hydration race where useParams()
  // briefly returns "__placeholder__" before router catches up.
  const id = pathname?.split("/").filter(Boolean).pop() ?? "";
  // "new" is a virtual route meaning "start a fresh session"
  const sessionId = id && id !== "new" ? id : undefined;
  return <ChatView initialSessionId={sessionId} />;
}
