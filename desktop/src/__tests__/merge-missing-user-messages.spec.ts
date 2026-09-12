import { describe, it, expect } from "vitest";
import { mergeMissingUserMessages } from "@/components/chat/use-chat-stream";
import type { Message } from "@ethan/shared/chat/types";

// 只关心 role/content，其余字段用最小对象填上
const u = (content: string): Message => ({ role: "user", content } as Message);
const a = (content: string): Message => ({ role: "assistant", content } as Message);

const contents = (msgs: Message[]) => msgs.map((m) => `${m.role}:${m.content}`);

describe("mergeMissingUserMessages", () => {
  it("后端漏存本轮 query 时补回（本 PR 主诉场景）", () => {
    const local = [u("你好"), a("在的"), u("帮我查下天气")];
    const fromServer = [u("你好"), a("在的")];

    const merged = mergeMissingUserMessages(local, fromServer);

    expect(contents(merged)).toEqual([
      "user:你好",
      "assistant:在的",
      "user:帮我查下天气",
    ]);
  });

  it("后端已落库则不重复补（避免重复气泡）", () => {
    const local = [u("你好"), a("在的")];
    const fromServer = [u("你好"), a("在的")];

    const merged = mergeMissingUserMessages(local, fromServer);

    expect(contents(merged)).toEqual(["user:你好", "assistant:在的"]);
  });

  // 回归：旧实现用 Set<content> 判「出现过」，连发两条相同 query 时
  // 第二条会被误判成「已有」而不补回——正是要修的 bug 本身。
  it("同一会话连发两条相同 query，只落了第一条时要补回第二条", () => {
    const local = [u("重试"), a("第一次回复"), u("重试"), a("第二次回复")];
    const fromServer = [u("重试"), a("第一次回复")];

    const merged = mergeMissingUserMessages(local, fromServer);

    expect(contents(merged)).toEqual([
      "user:重试",
      "assistant:第一次回复",
      "user:重试",
    ]);
  });

  it("两条相同 query 都已落库时不补", () => {
    const local = [u("重试"), a("第一次回复"), u("重试"), a("第二次回复")];
    const fromServer = [u("重试"), a("第一次回复"), u("重试"), a("第二次回复")];

    const merged = mergeMissingUserMessages(local, fromServer);

    expect(contents(merged)).toEqual([
      "user:重试",
      "assistant:第一次回复",
      "user:重试",
      "assistant:第二次回复",
    ]);
  });

  it("后端已落库的历史重复 query 不会被重复补回", () => {
    // 历史里本来就有两条相同 query，且都已落库 → 差额为 0，不应再补
    const local = [u("帮我"), a("第一次"), u("帮我"), a("第二次"), u("新问题")];
    const fromServer = [u("帮我"), a("第一次"), u("帮我"), a("第二次")];

    const merged = mergeMissingUserMessages(local, fromServer);

    expect(contents(merged)).toEqual([
      "user:帮我",
      "assistant:第一次",
      "user:帮我",
      "assistant:第二次",
      "user:新问题",
    ]);
  });

  it("本地没有 user 消息时原样返回后端结果", () => {
    const merged = mergeMissingUserMessages([a("只有助手")], [u("后端的")]);

    expect(contents(merged)).toEqual(["user:后端的"]);
  });
});
