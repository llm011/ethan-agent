import { ChatView } from "@/components/chat-view";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

interface ChatSessionPageProps {
  params: Promise<{ id: string }>;
}

export default async function ChatSessionPage({ params }: ChatSessionPageProps) {
  const { id } = await params;
  return <ChatView initialSessionId={id} />;
}
