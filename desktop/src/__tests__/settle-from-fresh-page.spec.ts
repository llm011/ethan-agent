/**
 * `settleFromFreshPage`：流式收尾「用最新一页核对定稿结果」的回归网。
 *
 * 背景（ETHA-43）：桌面端两个任务同时在跑时，点进其中一个会看到两个一模一样的
 * 气泡，点刷新就恢复。落库数据是对的 ⇒ 重复只发生在内存态 ⇒ 收尾阶段有几条写入
 * 路径交错替换同一个消息列表：
 *
 *  - `streamResume` 把网络错误吞成 `null` → 调用方走「拉最终结果」的收尾分支；
 *  - 同时还在等一条其实没接上的流；
 *  - 会话加载期间 `streaming` 仍是 false，3s 静默刷新也插进来拉一页。
 *
 * 三条路径各自按内容对账，占位气泡（`tmp:`、空正文）与后端空进度行同 key 互顶，
 * 结果就是同一条回复出了两份。这里锁住收尾函数的不变量：
 *  - 占位气泡绝不残留；
 *  - 同一条后端 assistant 行只出现一次（即便中途被挤掉，也要以 page 为准补回来）；
 *  - 本地乐观插入、后端还没落库的 user 消息不能被弄丢。
 */
import { describe, it, expect } from "vitest";
import { settleFromFreshPage } from "@/components/chat/use-chat-stream";
import type { Message } from "@ethan/shared/chat/types";
import { isTempId, newAssistantPlaceholder } from "@ethan/shared/chat/history";

type M = { id?: number | string | null; role: string; content: string };
const asMessages = (msgs: M[]) => msgs as unknown as Message[];
const m = (id: number | string | null, role: string, content = `c${id}`): M => ({ id, role, content });

describe("settleFromFreshPage", () => {
  it("占位气泡与后端空进度行同 key 时，只留一条 assistant（不产生两个气泡）", () => {
    const ph = newAssistantPlaceholder<Message>([]);
    const prev = asMessages([
      { role: "user", content: "两个任务同时在跑" },
      ph as unknown as M,
    ]);
    // 后端那条进度行 id=36415，此刻正文还是空的
    const page = asMessages([m(1, "user", "两个任务同时在跑"), m(36415, "assistant", "")]);

    const out = settleFromFreshPage(prev, page);

    expect(out.filter((x) => x.role === "assistant")).toHaveLength(1);
    expect(out.some((x) => isTempId(x.id))).toBe(false);
  });

  it("定稿行被前面的内容对账挤掉时，以 page 为准补回来（且只补一条）", () => {
    // prev 里已经有一条和后端同内容的 assistant（收尾分支重入时会出现）
    const prev = asMessages([
      m(1, "user", "hi"),
      { id: "tmp:x", role: "assistant", content: "done" },
    ]);
    const page = asMessages([m(1, "user", "hi"), m(2, "assistant", "done")]);

    const out = settleFromFreshPage(prev, page);

    const assistants = out.filter((x) => x.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].id).toBe(2);
    expect(out.some((x) => isTempId(x.id))).toBe(false);
  });

  it("后端还没落库的本地乐观 user 消息不能被弄丢", () => {
    const prev = asMessages([m(1, "user", "a"), m(2, "assistant", "b"), { role: "user", content: "刚发的" }]);
    const page = asMessages([m(1, "user", "a"), m(2, "assistant", "b")]);

    const out = settleFromFreshPage(prev, page);

    expect(out.filter((x) => x.role === "user" && x.content === "刚发的")).toHaveLength(1);
  });

  it("page 为空时原样返回（调用方拿不到最新一页，不该清空列表）", () => {
    const prev = asMessages([m(1, "user", "a")]);
    expect(settleFromFreshPage(prev, asMessages([]))).toBe(prev);
  });
});
