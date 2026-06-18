"use client";

import { useParams } from "next/navigation";
import { ChatView } from "@/components/chat-view";

export default function ChatSessionClient() {
  const params = useParams();
  const id = params?.id as string;
  return <ChatView initialSessionId={id} />;
}
