import type { Message } from "./types";

/**
 * 更新一条流自己的 assistant，只归并 placeholderId 与明确的服务器 messageId。
 * 恢复回放时两份可能同时存在：保留服务器行的位置/元数据，移除其占位别名。
 * 不根据正文认亲；旁路消息与不同轮相同正文必须保留。函数不修改闭包身份或输入。
 */
export function updateStreamMessage(
  messages: Message[],
  placeholderId: string,
  messageId: number | undefined,
  update: (previous: Message | undefined) => Message,
): Message[] {
  const owned = messages.find(m => m.role === "assistant" && m.id === placeholderId);
  const persisted = messageId == null ? undefined : messages.find(m => m.role === "assistant" && m.id === messageId);
  const anchor = persisted ?? owned;
  // 未设置的流字段不能擦掉服务器已知的模型、用量等元数据。
  const previous = anchor ? { ...persisted, ...Object.fromEntries(
    Object.entries(owned ?? {}).filter(([, value]) => value !== undefined),
  ), content: owned?.content || persisted?.content || "", created_at: persisted?.created_at ?? owned?.created_at } as Message : undefined;
  const next = update(previous);
  const settled = { ...next, id: messageId ?? anchor?.id ?? placeholderId };
  if (!anchor) return [...messages, settled];
  const result: Message[] = [];
  for (const message of messages) {
    if (message === anchor) result.push(settled);
    else if (message.role !== "assistant" || (message.id !== placeholderId && (messageId == null || message.id !== messageId))) {
      result.push(message);
    }
  }
  return result;
}
