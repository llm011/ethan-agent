import ChatSessionClient from "./client";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

export default function ChatSessionPage() {
  return <ChatSessionClient />;
}
