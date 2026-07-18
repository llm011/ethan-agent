import ChatSessionClient from "./client";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }, { id: "new" }];
}

export default function ChatSessionPage() {
  return <ChatSessionClient />;
}
